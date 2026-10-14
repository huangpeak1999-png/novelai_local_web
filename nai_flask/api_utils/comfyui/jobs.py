"""Session-owned, bounded M1 task registry with idempotent submission."""
import copy
import hashlib
import io
import json
import re
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

from PIL import Image, UnidentifiedImageError

from .errors import ComfyError


def safe_descriptor(value):
    if not isinstance(value, dict):
        raise ComfyError("Invalid output image descriptor.", "COMFY_PROTOCOL_ERROR", 502)
    filename, subfolder = value.get("filename"), value.get("subfolder", "")
    if (not isinstance(filename, str) or not filename or len(filename) > 255
            or any(char in filename for char in "/\\:\x00") or filename in {".", ".."}
            or not isinstance(subfolder, str) or len(subfolder) > 1024
            or any(char in subfolder for char in "\\:\x00") or PurePosixPath(subfolder).is_absolute()
            or ".." in PurePosixPath(subfolder).parts or value.get("type", "output") != "output"):
        raise ComfyError("Unsafe output image descriptor.", "COMFY_PROTOCOL_ERROR", 502)
    return {"filename": filename, "subfolder": subfolder, "type": "output"}


class JobService:
    def __init__(self, client, registry, data_dir, *, deadline=600, clock=time.monotonic, max_jobs=128):
        self.client, self.registry = client, registry
        self.directory = Path(data_dir) / "comfyui-results"
        self.deadline, self.clock, self.max_jobs = float(deadline), clock, max_jobs
        if not 1 <= self.deadline <= 3600:
            raise ValueError("ComfyUI task timeout must be in [1, 3600].")
        self.jobs = {}
        self.lock = threading.RLock()

    def _prune(self):
        for key, job in list(self.jobs.items()):
            if self.clock() - job["created"] > max(3600, self.deadline * 2):
                self.jobs.pop(key)
                if self.client.is_mock:
                    self.client.jobs.pop(job["prompt_id"], None)
                for image in job["images"]:
                    (self.directory / image["file"]).unlink(missing_ok=True)

    def submit(self, owner, payload):
        if not isinstance(payload, dict) or set(payload) - {"workflow_id", "parameters", "target", "request_id"}:
            raise ComfyError("Invalid submission fields.")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{8,128}", request_id):
            raise ComfyError("A unique request_id is required.")
        target = payload.get("target")
        if target is not None and (not isinstance(target, dict) or set(target) != {"pageId", "panelId"}
                                   or any(not isinstance(v, str) or not 1 <= len(v) <= 128 for v in target.values())):
            raise ComfyError("target must contain pageId and panelId.")
        graph, outputs = self.registry.build(payload.get("workflow_id"), payload.get("parameters", {}))
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        # Serialize submit and record before making an upstream request: uncertain timeouts
        # retain their request ID, so a browser retry cannot charge/run the GPU twice.
        with self.lock:
            self._prune()
            for job in self.jobs.values():
                if job["owner"] == owner and job["request_id"] == request_id:
                    if job["digest"] != digest:
                        raise ComfyError("request_id was reused with different parameters.", "COMFY_DUPLICATE_CONFLICT", 409)
                    return self.public(job)
            if len(self.jobs) >= self.max_jobs:
                raise ComfyError("Task registry is full; restart or wait for expired tasks.", "COMFY_BUSY", 429)
            if sum(j["owner"] == owner and j["status"] in {"queued", "running"} for j in self.jobs.values()) >= 2:
                raise ComfyError("Too many active tasks for this session.", "COMFY_BUSY", 429)
            job = {"id": uuid.uuid4().hex, "owner": owner, "request_id": request_id, "digest": digest,
                   "workflow_id": payload["workflow_id"], "target": copy.deepcopy(target), "created": self.clock(),
                   "status": "queued", "prompt_id": None, "images": [], "outputs": outputs,
                   "error": None, "code": None, "queue_position": None, "test_data": self.client.is_mock}
            self.jobs[job["id"]] = job
            try:
                response = self.client.submit(graph, uuid.uuid4().hex)
                prompt_id = response.get("prompt_id")
                if response.get("node_errors") or not isinstance(prompt_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", prompt_id):
                    raise ComfyError("ComfyUI did not accept the workflow.", "COMFY_WORKFLOW_REJECTED", 502)
                job["prompt_id"] = prompt_id
            except ComfyError as error:
                self._fail(job, error)
            return self.public(job)

    def _owned(self, owner, job_id):
        job = self.jobs.get(job_id)
        if job is None or job["owner"] != owner:
            raise ComfyError("Task not found.", "COMFY_JOB_NOT_FOUND", 404)
        return job

    @staticmethod
    def _fail(job, error):
        job.update(status="timed_out" if error.code == "COMFY_TIMEOUT" else "failed", error=error.message, code=error.code)

    def poll(self, owner, job_id):
        with self.lock:
            self._prune()
            job = self._owned(owner, job_id)
            if job["status"] not in {"queued", "running"}:
                return self.public(job)
            try:
                if self.clock() - job["created"] >= self.deadline:
                    raise ComfyError("Task deadline exceeded. The ComfyUI task may still be running; check ComfyUI before resubmitting.", "COMFY_TIMEOUT", 504)
                record = self.client.history(job["prompt_id"]).get(job["prompt_id"])
                if record:
                    status = record.get("status", {})
                    if status.get("status_str") == "error" or any(m[0] in {"execution_error", "execution_interrupted"} for m in status.get("messages", [])):
                        raise ComfyError("ComfyUI execution failed. Check the ComfyUI console.", "COMFY_EXECUTION_FAILED", 502)
                    if status.get("completed"):
                        self._complete(job, record)
                        return self.public(job)
                queue = self.client.queue()
                pending = [row[1] for row in queue.get("queue_pending", [])]
                running = [row[1] for row in queue.get("queue_running", [])]
                if job["prompt_id"] in pending:
                    job.update(status="queued", queue_position=pending.index(job["prompt_id"]) + 1)
                elif job["prompt_id"] in running:
                    job.update(status="running", queue_position=None)
                # A queue/history race must not fabricate completion or failure.
            except ComfyError as error:
                self._fail(job, error)
            except (KeyError, TypeError, ValueError, IndexError) as error:
                self._fail(job, ComfyError("Malformed ComfyUI task response.", "COMFY_PROTOCOL_ERROR", 502))
            return self.public(job)

    def _complete(self, job, record):
        descriptors = []
        for node in job["outputs"]:
            descriptors.extend(record.get("outputs", {}).get(node, {}).get("images", []))
        if not descriptors or len(descriptors) > 8:
            raise ComfyError("No supported output images (maximum 8).", "COMFY_OUTPUT_MISSING", 502)
        images = []
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            for index, descriptor in enumerate(descriptors):
                data = self.client.view(safe_descriptor(descriptor))
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"} or image.width * image.height > 32_000_000:
                        raise ValueError("Unsupported image")
                    width, height, fmt = image.width, image.height, image.format
                    image.verify()
                filename = f"{job['id']}-{index}.image"
                image_info = {"file": filename, "width": width, "height": height,
                              "mime_type": {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]}
                images.append(image_info)
                temporary = self.directory / (filename + ".tmp")
                try:
                    temporary.write_bytes(data)
                    temporary.replace(self.directory / filename)
                finally:
                    temporary.unlink(missing_ok=True)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            for image in images:
                (self.directory / image["file"]).unlink(missing_ok=True)
            raise ComfyError("Could not validate/save the output image. The GPU task was not resubmitted.", "COMFY_IMAGE_SAVE_FAILED", 500) from error
        except ComfyError:
            for image in images:
                (self.directory / image["file"]).unlink(missing_ok=True)
            raise
        job.update(images=images, status="completed", queue_position=None)

    def image(self, owner, job_id, index):
        with self.lock:
            job = self._owned(owner, job_id)
            if job["status"] != "completed" or not 0 <= index < len(job["images"]):
                raise ComfyError("Image not found.", "COMFY_IMAGE_NOT_FOUND", 404)
            info = job["images"][index]
            return self.directory / info["file"], info["mime_type"]

    @staticmethod
    def public(job):
        result = {key: copy.deepcopy(job[key]) for key in (
            "id", "workflow_id", "prompt_id", "target", "status", "error", "code", "queue_position", "test_data")}
        result["images"] = [{"url": f"/api/comfyui/jobs/{job['id']}/images/{index}",
                             **{key: info[key] for key in ("width", "height", "mime_type")}}
                            for index, info in enumerate(job["images"])]
        return result
