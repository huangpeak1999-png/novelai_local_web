"""Exercise the real adapter's HTTP contract without a GPU or network dependency."""
import json

import pytest

from api_utils.comfyui.client import ComfyClient
from api_utils.comfyui.errors import ComfyError


class Response:
    def __init__(self, data, status=200):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.status_code = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def iter_content(self, size):
        yield self.data


def test_real_http_paths_and_parameters(monkeypatch):
    calls = []
    replies = iter([{}, {'prompt_id': 'prompt-123'}, {'prompt-123': {'outputs': {}}},
                    {'queue_pending': [], 'queue_running': []}, b'image bytes'])
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return Response(next(replies))
    monkeypatch.setattr('requests.request', request)
    client = ComfyClient('http://127.0.0.1:8188', timeout=5)
    assert client.health()['test_data'] is False
    graph = {'arbitrary-node': {'class_type': 'Synthetic', 'inputs': {}}}
    assert client.submit(graph, 'client-123')['prompt_id'] == 'prompt-123'
    client.history('prompt-123')
    client.queue()
    descriptor = {'filename': 'result.png', 'subfolder': 'comic', 'type': 'output'}
    assert client.view(descriptor) == b'image bytes'
    assert [(call[0], call[1]) for call in calls] == [
        ('GET', 'http://127.0.0.1:8188/system_stats'), ('POST', 'http://127.0.0.1:8188/prompt'),
        ('GET', 'http://127.0.0.1:8188/history/prompt-123'), ('GET', 'http://127.0.0.1:8188/queue'),
        ('GET', 'http://127.0.0.1:8188/view')]
    assert calls[1][2]['json'] == {'prompt': graph, 'client_id': 'client-123'}
    assert calls[-1][2]['params'] == descriptor
    assert all(call[2]['allow_redirects'] is False and call[2]['timeout'] == 5 for call in calls)


@pytest.mark.parametrize('response,code', [
    (Response({}, 302), 'COMFY_UPSTREAM_ERROR'), (Response({}, 500), 'COMFY_UPSTREAM_ERROR'),
    (Response(b'not JSON'), 'COMFY_PROTOCOL_ERROR'), (Response([]), 'COMFY_PROTOCOL_ERROR'),
    (Response(b'x' * (4 * 1024 * 1024 + 1)), 'COMFY_PROTOCOL_ERROR'),
])
def test_bad_http_responses(monkeypatch, response, code):
    monkeypatch.setattr('requests.request', lambda *args, **kwargs: response)
    with pytest.raises(ComfyError) as caught:
        ComfyClient().health()
    assert caught.value.code == code
