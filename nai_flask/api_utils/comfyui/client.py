"""Bounded HTTP transport to a single administrator-configured ComfyUI origin."""
from urllib.parse import urlsplit

import requests

from .errors import ComfyError


class ComfyClient:
    is_mock = False

    def __init__(self, base_url="http://127.0.0.1:8188", timeout=10):
        if not isinstance(base_url, str):
            raise ValueError("ComfyUI URL must be a string.")
        parsed = urlsplit(base_url)
        # Accessing port also validates malformed/non-numeric/out-of-range ports.
        parsed.port
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("ComfyUI URL must be an administrator-configured HTTP origin.")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        if not 0 < self.timeout <= 120:
            raise ValueError("ComfyUI request timeout must be in (0, 120].")

    def _request(self, method, path, *, image=False, **kwargs):
        try:
            with requests.request(method, self.base_url + path, timeout=self.timeout,
                                  allow_redirects=False, stream=True, **kwargs) as response:
                if not 200 <= response.status_code < 300:
                    raise ComfyError("ComfyUI rejected the request.", "COMFY_UPSTREAM_ERROR", 502)
                limit = 32 * 1024 * 1024 if image else 4 * 1024 * 1024
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > limit:
                        raise ComfyError("ComfyUI response is too large.", "COMFY_PROTOCOL_ERROR", 502)
                    chunks.append(chunk)
                data = b"".join(chunks)
                if image:
                    return data
                import json
                result = json.loads(data)
                if not isinstance(result, dict):
                    raise ValueError("Expected object")
                return result
        except requests.Timeout as error:
            raise ComfyError("ComfyUI connection timed out; submission may have reached the GPU. Do not blindly resubmit.", "COMFY_TIMEOUT", 504) from error
        except requests.RequestException as error:
            raise ComfyError("Cannot connect to ComfyUI. Check its address and whether it is running.", "COMFY_OFFLINE", 503) from error
        except (ValueError, TypeError) as error:
            raise ComfyError("Invalid ComfyUI response.", "COMFY_PROTOCOL_ERROR", 502) from error

    def health(self):
        self._request("GET", "/system_stats")
        return {"online": True, "test_data": False}

    def submit(self, graph, client_id):
        return self._request("POST", "/prompt", json={"prompt": graph, "client_id": client_id})

    def history(self, prompt_id):
        return self._request("GET", f"/history/{prompt_id}")

    def queue(self):
        return self._request("GET", "/queue")

    def view(self, descriptor):
        return self._request("GET", "/view", params=descriptor, image=True)
