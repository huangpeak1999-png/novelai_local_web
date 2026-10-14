import assert from 'node:assert/strict';
import { generateComfyImage, generateForComicTarget } from './comfyGeneration.mjs';

// A selection object may change while GPU/network work is in flight.
const selection = { pageId: 'page-1', panelId: 'panel-1' };
let complete;
const pending = new Promise((resolve) => { complete = resolve; });
const received = [];
const operation = generateForComicTarget({ target: selection,
  generate: async (target) => { assert.deepEqual(target, selection); return pending; },
  receive: async (value) => { received.push(value); return true; },
});
selection.pageId = 'page-2'; selection.panelId = 'panel-2';
complete({ image: { dataUrl: 'data:image/png;base64,dGVzdA==' } });
const bound = await operation;
assert.equal(bound.assigned, true);
assert.deepEqual(received[0], { pageId: 'page-1', panelId: 'panel-1', image: bound.image });

const deleted = await generateForComicTarget({ target: selection,
  generate: async () => ({ image: 'preview retained' }), receive: async () => false });
assert.equal(deleted.assigned, false);
assert.equal(deleted.image, 'preview retained');

const calls = [], progress = [];
const states = ['queued', 'running', 'completed'];
const api = { request: async (path, options) => {
  calls.push({ path, options });
  const status = states.shift();
  return { id: 'job-123', status, test_data: true, images: status === 'completed'
    ? [{ url: '/api/comfyui/jobs/job-123/images/0', width: 512, height: 512 }] : [] };
} };
const params = { workflowId: 'preset', requestId: 'request-12345', parameters: { positive_prompt: 'comic' }, target: selection };
const result = await generateComfyImage(params, (status) => progress.push(status.status), {
  api, wait: async () => {}, fetchImage: async (url, options) => {
    assert.equal(url, '/api/comfyui/jobs/job-123/images/0');
    assert.equal(options.credentials, 'include');
    return { ok: true, blob: async () => new Blob(['test image']) };
  },
});
assert.equal(result.testData, true);
assert.deepEqual(progress, ['queued', 'running', 'completed']);
assert.deepEqual(calls[0].options.body.target, selection);
assert.equal(calls[0].path, '/comfyui/jobs');
URL.revokeObjectURL(result.objectUrlToRevoke);
await assert.rejects(generateComfyImage(params, () => {}, {
  api: { request: async () => ({ id: 'failed', status: 'timed_out', error: 'GPU deadline', code: 'COMFY_TIMEOUT' }) },
}), /GPU deadline/);
await assert.rejects(generateComfyImage(params, () => {}, {
  api: { request: async () => ({ id: 'unsafe', status: 'completed', images: [{ url: 'http://evil/image' }] }) },
}), /COMFY_INVALID_IMAGE/);
