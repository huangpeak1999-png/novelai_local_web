/** Independent engine adapter; API origin/graph selection belongs to Flask. */
export async function generateComfyImage(params, onProgress, {
  api, fetchImage = fetch, wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now = Date.now,
}) {
  const target = params.target ? { pageId: params.target.pageId, panelId: params.target.panelId } : null;
  let job = await api.request('/comfyui/jobs', {
    method: 'POST', signal: params.signal,
    body: { request_id: params.requestId, workflow_id: params.workflowId, parameters: params.parameters, target },
  });
  const started = now();
  while (['queued', 'running'].includes(job.status)) {
    onProgress(job);
    if (params.signal?.aborted) throw new Error('COMFY_POLLING_STOPPED');
    if (now() - started > 3_610_000) throw new Error('COMFY_POLL_TIMEOUT');
    await wait(1000);
    job = await api.request(`/comfyui/jobs/${encodeURIComponent(job.id)}`, { signal: params.signal });
  }
  onProgress(job);
  if (job.status !== 'completed') {
    throw Object.assign(new Error(job.error || 'ComfyUI 任务失败'), { code: job.code, data: job });
  }
  const image = job.images?.[0];
  if (!image?.url?.startsWith(`/api/comfyui/jobs/${job.id}/images/`)) throw new Error('COMFY_INVALID_IMAGE');
  const response = await fetchImage(image.url, { credentials: 'include', signal: params.signal });
  if (!response.ok) throw new Error('COMFY_IMAGE_DOWNLOAD_FAILED');
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  return { success: true, imageUrl: url, downloadUrl: url, objectUrlToRevoke: url, cachedBlob: blob,
    width: image.width, height: image.height, model: `comfyui:${params.workflowId}`,
    target, testData: Boolean(job.test_data), jobId: job.id };
}

/** Snapshot the original target before any asynchronous work or selection change. */
export async function generateForComicTarget({ target, generate, receive }) {
  const bound = target ? Object.freeze({ pageId: target.pageId, panelId: target.panelId }) : null;
  const result = await generate(bound);
  if (!result) throw new Error('COMFY_NO_RESULT');
  const assigned = bound ? await receive({ ...bound, image: result.image }) : false;
  return { ...result, target: bound, assigned };
}
