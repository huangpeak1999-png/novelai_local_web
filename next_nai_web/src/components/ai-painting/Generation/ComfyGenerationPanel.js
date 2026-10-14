'use client';

import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, MenuItem, Stack, TextField, Typography } from '@mui/material';
import apiClient from '@/utils/ApiClient';
import { createClientId } from '@/utils/browserCapabilities.mjs';
import useImageGeneration from './useImageGeneration';
import { generateForComicTarget } from './comfyGeneration.mjs';

async function decodeImage(blob) {
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('图片读取失败'));
    reader.readAsDataURL(blob);
  });
  const image = new window.Image();
  image.src = dataUrl;
  await image.decode();
  return { dataUrl, width: image.naturalWidth, height: image.naturalHeight };
}

const statuses = { idle: '就绪', queued: '排队中', running: '生成中', processing: '提交中', completed: '已完成', failed: '失败', timed_out: '超时' };

export default function ComfyGenerationPanel({ target, receiveImage }) {
  const [workflows, setWorkflows] = useState([]);
  const [workflowId, setWorkflowId] = useState('');
  const [values, setValues] = useState({});
  const [testData, setTestData] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [preview, setPreview] = useState(null);
  const [protocolStatus, setProtocolStatus] = useState(null);
  const { startGeneration, isGenerating, generationStatus } = useImageGeneration();
  const guard = useRef(false);
  const controller = useRef(null);
  const previewUrl = useRef(null);
  const workflow = workflows.find((item) => item.id === workflowId);

  function selectWorkflow(id, presets = workflows) {
    setWorkflowId(id);
    setValues(Object.fromEntries(Object.entries(presets.find((item) => item.id === id)?.fields || {})
      .map(([name, spec]) => [name, spec.default ?? ''])));
  }

  useEffect(() => {
    const abort = new AbortController();
    apiClient.request('/comfyui/workflows', { signal: abort.signal }).then((data) => {
      setWorkflows(data.workflows);
      setTestData(data.test_data);
      const first = data.workflows[0];
      if (first) {
        setWorkflowId(first.id);
        setValues(Object.fromEntries(Object.entries(first.fields).map(([name, spec]) => [name, spec.default ?? ''])));
      }
    }).catch((cause) => { if (!abort.signal.aborted) setError(cause.data?.error || cause.message); });
    return () => { abort.abort(); controller.current?.abort(); if (previewUrl.current) URL.revokeObjectURL(previewUrl.current); };
  }, []);

  async function generate() {
    if (guard.current || !workflow) return;
    guard.current = true;
    setError(''); setNotice(''); setProtocolStatus(null);
    controller.current = new AbortController();
    let item;
    try {
      const parameters = Object.fromEntries(Object.entries(workflow.fields)
        .filter(([name, spec]) => values[name] !== '' || spec.type === 'string')
        .map(([name, spec]) => [name, spec.type === 'string' ? values[name] : Number(values[name])]));
      const result = await generateForComicTarget({
        target,
        generate: async (bound) => {
          item = await startGeneration({ engine: 'comfyui', workflowId, parameters,
            requestId: createClientId(), target: bound, signal: controller.current.signal });
          if (!item) throw new Error('未取得生图结果');
          // Decode to the editor's existing image shape; project export keeps embedded data.
          const image = await decodeImage(item.cachedBlob);
          if (controller.current.signal.aborted) throw new Error('COMFY_POLLING_STOPPED');
          if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
          previewUrl.current = item.objectUrlToRevoke;
          setPreview({ ...item, image });
          return { ...item, image };
        },
        receive: receiveImage,
      });
      setNotice(result.target ? (result.assigned ? '图片已回填提交时的画格。' : '原页面或画格已删除，图片保留在预览中。') : '图片已生成，可选择画格后分配。');
    } catch (cause) {
      if (!controller.current.signal.aborted) {
        setError(cause.data?.error || cause.message);
        setProtocolStatus(cause.data?.status || null);
      }
      if (item?.objectUrlToRevoke && previewUrl.current !== item.objectUrlToRevoke) URL.revokeObjectURL(item.objectUrlToRevoke);
    } finally { guard.current = false; }
  }

  return <Stack spacing={1.5} sx={{ p: 2 }}>
    {testData && <Alert severity="warning">Mock 测试数据：未使用 GPU 或真实模型。</Alert>}
    {error && <Alert severity="error">{error}</Alert>}
    {notice && <Alert severity="info">{notice}</Alert>}
    {!workflows.length && !error && <Alert severity="info">尚未配置工作流。请按 docs/comfyui-integration.md 注册你的 API 工作流。</Alert>}
    <TextField select fullWidth label="工作流" value={workflowId} disabled={isGenerating || !workflows.length}
      onChange={(event) => selectWorkflow(event.target.value)}>
      {workflows.map((item) => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
    </TextField>
    {workflow && <Typography variant="body2">{workflow.description}</Typography>}
    {Object.entries(workflow?.fields || {}).map(([name, spec]) => <TextField key={name} fullWidth
      label={spec.label || name} value={values[name] ?? ''} disabled={isGenerating}
      required={spec.required || name === 'positive_prompt'} select={Boolean(spec.choices)}
      multiline={spec.type === 'string' && !spec.choices} minRows={name === 'positive_prompt' ? 3 : 1}
      type={spec.type === 'string' || spec.choices ? 'text' : 'number'}
      inputProps={{ min: spec.min, max: spec.max, step: spec.type === 'integer' ? 1 : 'any' }}
      onChange={(event) => setValues((previous) => ({ ...previous, [name]: event.target.value }))}>
      {spec.choices?.map((choice) => <MenuItem key={choice} value={choice}>{choice}</MenuItem>)}
    </TextField>)}
    <Typography variant="body2" role="status" aria-live="polite">
      {statuses[protocolStatus || generationStatus.status] || generationStatus.status}
      {generationStatus.queuePosition ? ` · 队列位置 ${generationStatus.queuePosition}` : ''}
      {target ? ` · 画格 #${target.panelNumber || target.panelId}` : ' · 未选择画格'}
    </Typography>
    <Button variant="contained" onClick={generate} disabled={isGenerating || !workflow}>ComfyUI 生成</Button>
    {preview && <>
      <Box component="img" src={preview.src} alt={preview.testData ? 'Mock 测试图像，非 GPU 生成' : 'ComfyUI 生成结果'} sx={{ width: '100%', maxHeight: 320, objectFit: 'contain' }} />
      <Button component="a" href={preview.src} download={preview.testData ? 'MOCK-TEST-DATA.png' : 'comfycomic.png'}>下载图片</Button>
      {!preview.target && <Button disabled={!target} onClick={async () => {
        try {
          const bound = { pageId: target.pageId, panelId: target.panelId };
          const assigned = await receiveImage({ ...bound, image: preview.image });
          setNotice(assigned ? '已分配到点击时选中的画格。' : '目标画格不存在。');
        } catch { setError('画格保存失败，请下载图片保留结果。'); }
      }}>分配到当前画格</Button>}
    </>}
  </Stack>;
}
