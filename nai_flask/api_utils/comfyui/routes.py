"""Blueprint wiring; existing application retains Host/Origin/session/CSRF policy."""
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint, g, jsonify, request, send_file

from .client import ComfyClient
from .errors import ComfyError
from .jobs import JobService
from .mock import MockComfyClient
from .workflows import WorkflowRegistry


def is_loopback_request():
    try:
        peer = ipaddress.ip_address(request.remote_addr or "")
        if isinstance(peer, ipaddress.IPv6Address) and peer.ipv4_mapped:
            peer = peer.ipv4_mapped
        return peer.is_loopback and urlsplit(f"http://{request.host}").hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        return False


def register_comfyui(app, *, session_required, current_session, create_session, delete_session, set_cookie):
    mock, local = app.config["COMFYUI_MOCK"], app.config["COMFYUI_LOCAL_MODE"]
    if type(mock) is not bool or type(local) is not bool:
        raise ValueError("ComfyUI mock/local flags must be JSON booleans.")
    if (mock or local) and (app.config["ALLOW_LAN"] or not (app.testing or app.config["COMFYUI_ENV"] == "development")):
        raise ValueError("ComfyUI mock/local entry requires explicit development/test mode and loopback-only binding.")
    manifest = app.config["COMFYUI_WORKFLOWS"]
    if mock:
        manifest = Path(__file__).parent / "mock_workflows" / "presets.json"
    elif manifest and not Path(manifest).is_absolute():
        manifest = Path(app.root_path) / manifest
    registry = WorkflowRegistry(manifest, mock=mock)
    client = MockComfyClient() if mock else ComfyClient(app.config["COMFYUI_URL"], app.config["COMFYUI_TIMEOUT_SECONDS"])
    service = JobService(client, registry, app.config["DATA_DIR"], deadline=app.config["COMFYUI_JOB_TIMEOUT_SECONDS"])
    app.extensions["comfyui"] = service
    bp = Blueprint("comfyui", __name__, url_prefix="/api/comfyui")

    @bp.before_request
    def development_boundary():
        if (mock or local) and not is_loopback_request():
            raise ComfyError("ComfyUI development access is loopback only.", "COMFY_LOCAL_ONLY", 403)

    @bp.errorhandler(ComfyError)
    def handle_error(error):
        return jsonify(success=False, error=error.message, code=error.code), error.status

    @bp.get("/capabilities")
    def capabilities():
        return jsonify(local_entry=local and is_loopback_request(), test_data=mock)

    @bp.post("/session")
    def local_session():
        if not local or not is_loopback_request():
            raise ComfyError("Local development entry is disabled.", "COMFY_LOCAL_DISABLED", 403)
        existing_id, existing = current_session()
        if existing:
            return jsonify(authenticated=True, csrf_token=existing["csrf_token"])
        delete_session(existing_id)
        session_id, entry = create_session("", {"auth": {"login_mode": "comfy_local"}}, login_mode="comfy_local")
        response = jsonify(authenticated=True, csrf_token=entry["csrf_token"], local_only=True)
        set_cookie(response, session_id)
        return response

    @bp.get("/health")
    @session_required()
    def health():
        return jsonify(client.health())

    @bp.get("/workflows")
    @session_required()
    def workflows():
        return jsonify(workflows=registry.list(), test_data=mock)

    @bp.post("/jobs")
    @session_required(csrf=True)
    def submit():
        result = service.submit(g.local_session_id, request.get_json(silent=True))
        return jsonify(result), 202

    @bp.get("/jobs/<job_id>")
    @session_required()
    def poll(job_id):
        return jsonify(service.poll(g.local_session_id, job_id))

    @bp.get("/jobs/<job_id>/images/<int:index>")
    @session_required()
    def image(job_id, index):
        path, mime = service.image(g.local_session_id, job_id, index)
        if not path.is_file():
            raise ComfyError("Saved image is unavailable.", "COMFY_IMAGE_NOT_FOUND", 404)
        response = send_file(path, mimetype=mime, download_name="comfycomic-test.png" if mock else "comfycomic-image", conditional=True)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.register_blueprint(bp)
