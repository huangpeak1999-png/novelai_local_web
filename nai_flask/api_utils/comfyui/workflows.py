"""Trusted, server-owned API workflow registry. Never accept graphs from browsers."""
import copy
import json
import math
from pathlib import Path

from .errors import ComfyError


def load_json(path):
    path = Path(path)
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Workflow configuration exceeds 2 MiB.")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_value(name, value, spec):
    kind = spec["type"]
    if kind == "string":
        valid = isinstance(value, str) and len(value) <= 12000
    else:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and (kind != "integer" or type(value) is int)
                 and spec.get("min", -float("inf")) <= value <= spec.get("max", float("inf")))
    if not valid or ("choices" in spec and value not in spec["choices"]):
        raise ComfyError(f"Invalid workflow parameter: {name}")


class WorkflowRegistry:
    def __init__(self, manifest=None, *, mock=False):
        self.presets = {}
        if not manifest:
            return
        manifest = Path(manifest).resolve()
        entries = load_json(manifest)
        if not isinstance(entries, list):
            raise ValueError("Workflow manifest must be an array.")
        for entry in entries:
            try:
                self._register(entry, manifest.parent, mock)
            except (KeyError, TypeError, ComfyError) as error:
                raise ValueError(f"Invalid workflow configuration: {error}") from error

    def _register(self, entry, root, mock):
        import re
        workflow_id = entry["id"]
        if not isinstance(workflow_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", workflow_id) or workflow_id in self.presets:
            raise ValueError("Workflow ID is invalid or duplicated.")
        for key in ("name", "description"):
            if not isinstance(entry[key], str) or len(entry[key]) > 2000:
                raise ValueError(f"Invalid workflow {key}.")
        if bool(entry.get("test_only")) != mock:
            raise ValueError("Mock workflows and real workflows must use separate registries.")
        path = (root / entry["file"]).resolve()
        if not path.is_relative_to(root) or path.suffix != ".json":
            raise ValueError("Workflow file must be a JSON file inside the manifest directory.")
        graph = load_json(path)
        if not isinstance(graph, dict) or not graph:
            raise ValueError("An API workflow must be a non-empty node object, not a UI export.")
        for node_id, node in graph.items():
            if not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
                raise ValueError(f"Invalid API node: {node_id}")
            for value in node["inputs"].values():
                if isinstance(value, list) and (len(value) != 2 or str(value[0]) not in graph or type(value[1]) is not int or value[1] < 0):
                    raise ValueError(f"Invalid node connection in {node_id}.")
        fields = entry["fields"]
        if not isinstance(fields, dict) or "positive_prompt" not in fields:
            raise ValueError("positive_prompt mapping is required.")
        if fields["positive_prompt"]["type"] != "string":
            raise ValueError("positive_prompt must map a string field.")
        mapped = set()
        for name, spec in fields.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or spec["type"] not in {"string", "integer", "number"}:
                raise ValueError("Invalid workflow field definition.")
            targets = spec["targets"]
            if not isinstance(targets, list) or not targets:
                raise ValueError(f"Missing mapping targets: {name}")
            for target in targets:
                node_id, input_name = target["node"], target["input"]
                if node_id not in graph or input_name not in graph[node_id]["inputs"]:
                    raise ValueError(f"Missing mapping node/input: {name}")
                if isinstance(graph[node_id]["inputs"][input_name], list) or (node_id, input_name) in mapped:
                    raise ValueError("Mappings must replace unique literal inputs, never graph links.")
                mapped.add((node_id, input_name))
            if "default" in spec:
                validate_value(name, spec["default"], spec)
        outputs = entry["output_nodes"]
        if not isinstance(outputs, list) or not outputs or any(node not in graph for node in outputs):
            raise ValueError("output_nodes must reference API graph nodes.")
        self.presets[workflow_id] = (copy.deepcopy(entry), graph)

    def list(self):
        return [{key: copy.deepcopy(entry[key]) for key in ("id", "name", "description", "fields", "output_nodes")}
                for entry, _ in self.presets.values()]

    def build(self, workflow_id, values):
        if not isinstance(workflow_id, str) or workflow_id not in self.presets:
            raise ComfyError("Unknown workflow preset.", "COMFY_WORKFLOW_UNKNOWN")
        entry, template = self.presets[workflow_id]
        if not isinstance(values, dict) or set(values) - set(entry["fields"]):
            raise ComfyError("Unsupported workflow parameters.")
        graph = copy.deepcopy(template)
        for name, spec in entry["fields"].items():
            if name not in values and "default" not in spec:
                if spec.get("required", name == "positive_prompt"):
                    raise ComfyError(f"Missing workflow parameter: {name}", "COMFY_MAPPING_REQUIRED")
                continue
            value = values.get(name, spec.get("default"))
            validate_value(name, value, spec)
            for target in spec["targets"]:
                graph[target["node"]]["inputs"][target["input"]] = value
        return graph, entry["output_nodes"]
