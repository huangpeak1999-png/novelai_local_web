# Windows 11 本地启动与联调

本说明面向 RTX 4070 Super 12GB / 32GB 内存的目标电脑。云端仅验证了 Mock；本机真实模型可用性、显存、速度和 ComfyUI 兼容性需要你提供真实 API 工作流后确认。

## 1. 获取分支并安装依赖

在仓库根目录的 PowerShell 执行（要求 Git、Python 3.11+、Node.js 20+；原项目安装脚本也可用于准备环境）：

```powershell
git fetch origin
git switch feature/comfyui-m1
cd next_nai_web
npm ci
npm test
npm run lint
npm run build
cd ..\nai_flask
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
```

Next 原项目构建会获取 Google 字体，需要联网。无需 NovelAI 账户、GPU 或 ComfyUI 即可执行自动化测试。Flask 直接提供 `next_nai_web/out` 静态站点；前端 `/api` 与 Flask 同源，不要直接在手机端配置 8188。

## 2. 先验证 Mock 完整链路

仍在 `nai_flask` 目录执行；如果已有 `config.local.json`，先备份并合并配置，勿直接覆盖：

```powershell
Copy-Item comfyui.mock.example.json config.local.json
.\.venv\Scripts\python.exe app.py
```

用这台 Windows 电脑打开 `http://127.0.0.1:5000/comfycomic`。也可从登录页点击 ComfyComic 入口。

1. 页面应显示“仅限本机”的说明和 Mock 测试提示，不要求 NovelAI 登录。
2. 新建/使用漫画页，套用模板或画出画格，选中一格。
3. 选择 Mock 工作流、填写正向提示词，点击“ComfyUI 生成”。应出现排队、生成中、完成状态。
4. 输出是明确带 `MOCK / TEST DATA / NOT GPU GENERATED` 字样的 512×512 测试图，自动放入提交时选中的画格。
5. 生成期间切换到另一画格：结果仍属于原画格。未选画格时也可只生成预览，再点击“分配到当前画格”。
6. 下载图片、保存漫画页、导出可编辑工程，再导入检查图层/文字/构图和图像保留。

Mock 只模拟协议状态，seed 不改变图像，不代表提示词/采样器或模型效果验证。失败/超时/保存失败等由自动化测试注入验证，不提供远程用户可控的故障开关。

## 3. 换成真实 ComfyUI

停止 Flask。启动本机 ComfyUI，保持监听 `127.0.0.1:8188`，在本机 ComfyUI 页面先单独验证你的工作流能生成图片。

导出 **API 格式**工作流，保存在 `nai_flask/workflows.local/`，按 [接入说明](comfyui-integration.md) 建立 `presets.json` 映射。先根据真实节点标记正向文本和输出节点；不确定参数时只暴露必需的正向提示词，其余留在工作流中。

```powershell
New-Item -ItemType Directory -Force workflows.local
Copy-Item comfyui.example.json config.local.json
```

将自己的 API JSON 和 `presets.json` 放好后，再启动 Flask：

```powershell
.\.venv\Scripts\python.exe app.py
```

确认配置为 `comfyui_mock=false`，真实列表不应包含 Mock 预设。访问 `/comfycomic`，选择真实预设后先以你在 ComfyUI 已验证的低显存配置生成一张图。12GB 显存不保证所有 Qwen/Krea2 配置可用，应在 ComfyUI 侧调整模型量化、卸载与分辨率。

可用浏览器控制台检查健康接口（页面已有会话后）：

```javascript
await fetch('/api/comfyui/health', {credentials: 'include'}).then(r => r.json())
```

应显示 `online:true, test_data:false`。在 ComfyUI 控制台核对任务、prompt ID 和实际模型输出，再验证切换画格、导出和重新导入。请勿把真实敏感工作流、提示词、私图或 Token 提交 Git。

## 排错与边界

* 空预设：未设置 manifest 或预设数组为空。文件不存在/映射不匹配会在启动时明确失败，请核对真实 API 节点 input。
* `COMFY_OFFLINE`：检查本机 ComfyUI 是否启动及配置地址。
* `COMFY_EXECUTION_FAILED`：查看 ComfyUI 控制台；可能缺节点、模型或显存不足。M1 不安装或替你猜测自定义节点。
* `COMFY_TIMEOUT`：先检查 ComfyUI 队列/历史，任务可能仍在执行。按需要调整任务期限，最长 3600 秒；不要盲目重提。
* `COMFY_IMAGE_SAVE_FAILED`：检查磁盘空间/权限；不会再次执行 GPU。图片还可能保存在 ComfyUI 输出目录。
* 画格落盘失败：页面保留预览，可先下载图片，再处理 IndexedDB 配额/浏览器存储问题。
* 返回认证/CSRF 错误：重新打开入口刷新会话；不要删除校验代码。
* 页面刷新/离开后不恢复在途任务；请先核对 ComfyUI，再决定是否重试。

**安卓/Tailscale 联调暂未开放。** 本轮只能在 Windows 电脑的 loopback 地址验证独立入口。下一阶段先完成正式本地账号认证与 Tailscale 安全接入，再测试手机，不能把本轮开发入口代理到局域网或公网。
