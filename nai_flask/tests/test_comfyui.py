import json

import pytest
import requests

from app import create_app
from api_utils.comfyui.client import ComfyClient
from api_utils.comfyui.errors import ComfyError
from api_utils.comfyui.jobs import safe_descriptor
from api_utils.comfyui.workflows import WorkflowRegistry
from conftest import ORIGIN, login


@pytest.fixture
def comfy(tmp_path):
    app = create_app({"TESTING": True, "DATA_DIR": str(tmp_path), "COMFYUI_MOCK": True,
                      "COMFYUI_LOCAL_MODE": True})
    client = app.test_client()
    response = client.post('/api/comfyui/session', json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 200
    return app, client, {"Origin": ORIGIN, "X-CSRF-Token": response.json['csrf_token']}


def payload(**changes):
    return {"request_id": "request-12345678", "workflow_id": "mock-text-to-image",
            "parameters": {"positive_prompt": "test comic", "seed": 42},
            "target": {"pageId": "page-original", "panelId": "panel-original"}, **changes}


def submit(comfy, **changes):
    _, client, headers = comfy
    response = client.post('/api/comfyui/jobs', json=payload(**changes), headers=headers)
    assert response.status_code == 202
    return response.json


def test_workflow_substitution_isolated_and_missing_fields(comfy):
    registry = comfy[0].extensions['comfyui'].registry
    graph, outputs = registry.build('mock-text-to-image', {"positive_prompt": "hello", "seed": 99})
    assert graph['mock_prompt']['inputs']['text'] == 'hello'
    assert graph['mock_output']['inputs']['seed'] == 99
    assert outputs == ['mock_output']
    graph['mock_prompt']['inputs']['text'] = 'changed'
    again, _ = registry.build('mock-text-to-image', {"positive_prompt": "new"})
    assert again['mock_output']['inputs']['seed'] == 0
    with pytest.raises(ComfyError, match='Missing workflow parameter'):
        registry.build('mock-text-to-image', {})
    with pytest.raises(ComfyError, match='Unsupported workflow parameters'):
        registry.build('mock-text-to-image', {"positive_prompt": "x", "url": "http://evil"})
    with pytest.raises(ComfyError, match='Invalid workflow parameter'):
        registry.build('mock-text-to-image', {"positive_prompt": "x", "seed": -1})


@pytest.mark.parametrize('broken', ['missing_node', 'missing_input', 'ui_export', 'path_escape', 'link_mapping', 'no_prompt'])
def test_invalid_workflow_mapping_rejected(tmp_path, broken):
    source = __import__('pathlib').Path(__file__).parents[1] / 'api_utils/comfyui/mock_workflows'
    preset = json.loads((source / 'presets.json').read_text())
    graph = json.loads((source / 'text-to-image.json').read_text())
    if broken == 'missing_node':
        preset[0]['fields']['positive_prompt']['targets'][0]['node'] = 'unknown'
    elif broken == 'missing_input':
        preset[0]['fields']['positive_prompt']['targets'][0]['input'] = 'unknown'
    elif broken == 'ui_export':
        graph = {"nodes": [], "links": []}
    elif broken == 'path_escape':
        preset[0]['file'] = '../escape.json'
    elif broken == 'link_mapping':
        preset[0]['fields']['positive_prompt']['targets'] = [{"node": "mock_output", "input": "text"}]
    else:
        del preset[0]['fields']['positive_prompt']
    (tmp_path / 'presets.json').write_text(json.dumps(preset))
    (tmp_path / 'text-to-image.json').write_text(json.dumps(graph))
    with pytest.raises(ValueError):
        WorkflowRegistry(tmp_path / 'presets.json', mock=True)


def test_mock_full_lifecycle_and_bound_target(comfy):
    _, client, _ = comfy
    assert client.get('/api/comfyui/health').json == {"online": True, "test_data": True}
    job = submit(comfy)
    assert job['test_data'] is True
    assert job['status'] == 'queued'
    path = f"/api/comfyui/jobs/{job['id']}"
    assert client.get(path).json['status'] == 'queued'
    assert client.get(path).json['status'] == 'running'
    result = client.get(path).json
    assert result['status'] == 'completed'
    assert result['target'] == payload()['target']
    image = client.get(result['images'][0]['url'])
    assert image.status_code == 200
    assert image.data.startswith(b'\x89PNG')
    assert image.headers['Cache-Control'] == 'no-store'
    assert 'comfycomic-test.png' in image.headers['Content-Disposition']
    assert 'file' not in result['images'][0]


def test_idempotency_and_uncertain_submission_not_retried(comfy, monkeypatch):
    app, client, headers = comfy
    job = submit(comfy)
    assert submit(comfy)['id'] == job['id']
    assert len(app.extensions['comfyui'].client.jobs) == 1
    conflict = payload(parameters={"positive_prompt": "changed"})
    assert client.post('/api/comfyui/jobs', json=conflict, headers=headers).status_code == 409
    calls = []
    def timeout(*args):
        calls.append(1)
        raise ComfyError('Uncertain submit timeout', 'COMFY_TIMEOUT', 504)
    monkeypatch.setattr(app.extensions['comfyui'].client, 'submit', timeout)
    failed = submit(comfy, request_id='uncertain-request')
    assert failed['status'] == 'timed_out'
    assert submit(comfy, request_id='uncertain-request')['id'] == failed['id']
    assert len(calls) == 1


@pytest.mark.parametrize('scenario,expected', [('failure', 'failed'), ('timeout', 'timed_out')])
def test_failure_and_deadline(comfy, scenario, expected):
    app, client, _ = comfy
    service = app.extensions['comfyui']
    service.client.scenario = scenario
    job = submit(comfy)
    path = f"/api/comfyui/jobs/{job['id']}"
    if scenario == 'timeout':
        service.clock = lambda: service.jobs[job['id']]['created'] + 601
    for _ in range(3):
        result = client.get(path).json
    assert result['status'] == expected
    assert result['error']


@pytest.mark.parametrize('exception,code', [(requests.ConnectionError, 'COMFY_OFFLINE'), (requests.Timeout, 'COMFY_TIMEOUT')])
def test_real_transport_offline_and_timeout(monkeypatch, exception, code):
    def fail(*args, **kwargs):
        raise exception('private upstream details')
    monkeypatch.setattr(requests, 'request', fail)
    with pytest.raises(ComfyError) as caught:
        ComfyClient().health()
    assert caught.value.code == code
    assert 'private' not in caught.value.message


def test_offline_api_is_explicit(comfy, monkeypatch):
    app, client, _ = comfy
    def offline(*args):
        raise ComfyError('Cannot connect to ComfyUI.', 'COMFY_OFFLINE', 503)
    monkeypatch.setattr(app.extensions['comfyui'].client, 'health', offline)
    monkeypatch.setattr(app.extensions['comfyui'].client, 'submit', offline)
    assert client.get('/api/comfyui/health').status_code == 503
    assert submit(comfy)['code'] == 'COMFY_OFFLINE'


def test_security_auth_csrf_owner_loopback_and_scope(comfy):
    app, client, _ = comfy
    anonymous = app.test_client()
    assert anonymous.get('/api/comfyui/workflows').status_code == 401
    assert client.post('/api/comfyui/jobs', json=payload(), headers={"Origin": ORIGIN}).status_code == 403
    assert client.post('/api/comfyui/session', json={}).status_code == 403
    assert client.get('/api/account').status_code == 403
    assert client.get('/api/local/settings').status_code == 403
    assert client.get('/api/comfyui/workflows', headers={'Host': 'evil.example'}).status_code == 400
    assert client.get('/api/comfyui/workflows', environ_overrides={'REMOTE_ADDR': '192.168.1.9'}).status_code == 403
    assert client.post('/api/comfyui/session', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    job = submit(comfy)
    path = f"/api/comfyui/jobs/{job['id']}"
    for _ in range(3):
        result = client.get(path).json
    other = app.test_client()
    other.post('/api/comfyui/session', json={}, headers={'Origin': ORIGIN})
    assert other.get(path).status_code == 404
    assert other.get(result['images'][0]['url']).status_code == 404


def test_unsafe_configuration_refused(tmp_path):
    for changes in ({'COMFYUI_MOCK': True}, {'COMFYUI_LOCAL_MODE': True},
                    {'COMFYUI_MOCK': 'true'}, {'COMFYUI_URL': 'http://localhost:8188/path'}):
        with pytest.raises(ValueError):
            create_app({'DATA_DIR': str(tmp_path), **changes})


def test_development_mock_cannot_enable_lan(tmp_path, monkeypatch):
    monkeypatch.setattr('app.discover_lan_ipv4_addresses', lambda: [])
    with pytest.raises(ValueError, match='loopback-only'):
        create_app({'TESTING': True, 'DATA_DIR': str(tmp_path), 'COMFYUI_MOCK': True, 'ALLOW_LAN': True})


def test_active_job_limit_and_no_browser_url_override(comfy):
    _, client, headers = comfy
    submit(comfy)
    submit(comfy, request_id='request-22222222')
    response = client.post('/api/comfyui/jobs', json=payload(request_id='request-33333333'), headers=headers)
    assert response.status_code == 429
    response = client.post('/api/comfyui/jobs', json=payload(url='http://evil.example'), headers=headers)
    assert response.status_code == 400


@pytest.mark.parametrize('descriptor', [
    {'filename': '../secret.png'}, {'filename': 'x.png', 'subfolder': '../'},
    {'filename': 'C:\\secret.png'}, {'filename': 'x.png', 'type': 'input'},
])
def test_output_paths_are_not_browser_paths(descriptor):
    with pytest.raises(ComfyError):
        safe_descriptor(descriptor)


def test_save_failure_does_not_resubmit(comfy, monkeypatch):
    app, client, _ = comfy
    service = app.extensions['comfyui']
    job = submit(comfy)
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(__import__('pathlib').Path, 'write_bytes', fail)
    for _ in range(3):
        result = client.get(f"/api/comfyui/jobs/{job['id']}").json
    assert result['code'] == 'COMFY_IMAGE_SAVE_FAILED'
    assert len(service.client.jobs) == 1


def test_existing_novelai_session_can_use_comfyui(app, client):
    login(client)
    assert client.get('/api/comfyui/workflows').json['workflows'] == []
    assert client.post('/api/comfyui/session', headers={'Origin': ORIGIN}).status_code == 403


def test_different_graph_and_optional_sampling_fields(tmp_path):
    graph = {
        'text-a': {'class_type': 'SyntheticText', 'inputs': {'words': '', 'avoid': ''}},
        'text-b': {'class_type': 'SyntheticText', 'inputs': {'words': ''}},
        'sampler-z': {'class_type': 'SyntheticSampler', 'inputs': {'w': 256, 'h': 256, 's': 0, 'steps': 5, 'cfg': 1.0, 'algorithm': 'a'}},
        'out': {'class_type': 'SyntheticOutput', 'inputs': {'image': ['sampler-z', 0]}},
    }
    def field(node, input_name, kind, default):
        return {'type': kind, 'default': default, 'targets': [{'node': node, 'input': input_name}]}
    fields = {
        'positive_prompt': {'type': 'string', 'targets': [{'node': node, 'input': 'words'} for node in ['text-a', 'text-b']]},
        'negative_prompt': field('text-a', 'avoid', 'string', ''),
        'width': field('sampler-z', 'w', 'integer', 512),
        'height': field('sampler-z', 'h', 'integer', 768),
        'seed': field('sampler-z', 's', 'integer', 7),
        'steps': field('sampler-z', 'steps', 'integer', 20),
        'cfg': field('sampler-z', 'cfg', 'number', 2.5),
        'sampler': {**field('sampler-z', 'algorithm', 'string', 'a'), 'choices': ['a', 'b']},
    }
    preset = [{'id': 'synthetic-test', 'name': 'Synthetic fixture', 'description': 'Unit test only',
               'file': 'graph.json', 'fields': fields, 'output_nodes': ['out']}]
    (tmp_path / 'graph.json').write_text(json.dumps(graph))
    (tmp_path / 'presets.json').write_text(json.dumps(preset))
    registry = WorkflowRegistry(tmp_path / 'presets.json')
    replaced, _ = registry.build('synthetic-test', {'positive_prompt': 'hello', 'negative_prompt': 'blur', 'seed': 123, 'sampler': 'b'})
    assert replaced['text-a']['inputs'] == {'words': 'hello', 'avoid': 'blur'}
    assert replaced['text-b']['inputs']['words'] == 'hello'
    assert replaced['sampler-z']['inputs'] == {'w': 512, 'h': 768, 's': 123, 'steps': 20, 'cfg': 2.5, 'algorithm': 'b'}
    assert graph['text-a']['inputs']['words'] == ''
