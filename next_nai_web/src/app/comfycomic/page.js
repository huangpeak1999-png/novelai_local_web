'use client';

import { useEffect, useRef, useState } from 'react';
import { Alert, Box, Button, CircularProgress, MenuItem, Stack, TextField, Typography } from '@mui/material';
import apiClient from '@/utils/ApiClient';
import ComicWorkspace from '@/components/ai-painting/ComicWorkspace/ComicWorkspace';
import ComfyGenerationPanel from '@/components/ai-painting/Generation/ComfyGenerationPanel';

export default function ComfyComicPage() {
  const workspace = useRef(null);
  const [target, setTarget] = useState(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const [localOnly, setLocalOnly] = useState(false);
  const [formOpen, setFormOpen] = useState(true);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        let session = await apiClient.getSession();
        if (!session.authenticated) {
          const capabilities = await apiClient.request('/comfyui/capabilities');
          if (!capabilities.local_entry) throw new Error('请先在登录页建立会话，或按本地测试文档明确启用 loopback 开发入口。');
          session = await apiClient.request('/comfyui/session', { method: 'POST', body: {} });
          apiClient.setCsrfToken(session.csrf_token);
        }
        if (active) {
          setLocalOnly(session.local_only || session.account_snapshot?.auth?.login_mode === 'comfy_local');
          setReady(true);
        }
      } catch (cause) { if (active) setError(cause.data?.error || cause.message); }
    })();
    return () => { active = false; };
  }, []);

  return <Stack sx={{ height: '100dvh', minHeight: 0 }}>
    <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2, py: 1, flexWrap: 'wrap' }}>
      <Typography component="h1" variant="h6">ComfyComic M1</Typography>
      <TextField select size="small" label="生成引擎" value="comfyui" sx={{ minWidth: 150 }}
        onChange={(event) => { if (event.target.value === 'novelai') window.location.assign('/login'); }}>
        <MenuItem value="comfyui">ComfyUI</MenuItem>
        <MenuItem value="novelai">NovelAI（登录）</MenuItem>
      </TextField>
      <Button onClick={() => setFormOpen((open) => !open)}>{formOpen ? '收起生成面板' : '显示生成面板'}</Button>
      {ready && <Button onClick={async () => {
        try { await apiClient.logout(); window.location.assign('/login'); }
        catch (cause) { setError(cause.data?.error || cause.message); }
      }}>退出会话</Button>}
    </Stack>
    {localOnly && <Alert severity="info">仅限本机的开发测试入口。Tailscale 远程认证尚未实现。</Alert>}
    {error && <Alert severity="error">{error} <Button href="/login">返回登录页</Button></Alert>}
    {!ready && !error && <CircularProgress sx={{ m: 3 }} />}
    {ready && <Box sx={{ display: 'flex', flexDirection: { xs: 'column', md: 'row' }, flex: 1, minHeight: 0 }}>
      <Box sx={{ flex: 1, minWidth: 0, minHeight: 0 }}>
        <ComicWorkspace ref={workspace} onSelectTask={(next) => setTarget(next)}
          onEditTask={() => setFormOpen(true)} onGenerate={() => setFormOpen(true)}
          generationAction={{ text: 'ComfyUI 生成参数', disabled: false }} />
      </Box>
      <Box sx={{ display: formOpen ? 'block' : 'none', width: { xs: '100%', md: 340 },
        maxHeight: { xs: '45dvh', md: '100%' }, flexShrink: 0, overflowY: 'auto', border: '1px solid', borderColor: 'divider' }}>
        <ComfyGenerationPanel target={target} receiveImage={(result) => workspace.current?.receiveGeneratedImage(result) ?? false} />
      </Box>
    </Box>}
  </Stack>;
}
