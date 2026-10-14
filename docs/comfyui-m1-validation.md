# M1 云端验证记录

环境：2026-10-14，Linux / Python 3.12 / Node.js 24；Fork `huangpeak1999-png/novelai_local_web`，基于 `d4546ed`，分支 `feature/comfyui-m1`。现有 CI 使用 Python 3.11 / Node 20，未修改其版本或流程。

## 基线

开始时云工作区为空，克隆了用户 Fork；未修改上游。首次执行缺少 pytest 和 npm 依赖，按 `nai_flask/requirements.txt` 与前端 lock 文件安装后：

* `cd nai_flask && python -m pytest`：262 passed。
* `cd next_nai_web && npm test`：32 passed。
* `npm run lint`：0 errors，1 条已有 `ImageReferenceControl.js:350` 的 `no-img-element` 警告。
* 默认沙箱 `npm run build`：webpack 失败，日志无详细原因。允许构建网络访问后，相同原有 Next/font 构建流程和新增入口均成功；未更换字体或关闭构建校验。

## 本轮验证

后端新增覆盖配置字段替换、多个节点映射、可选采样字段、无效节点/输入/图连接、Mock 排队→执行→完成/图片、离线、超时、执行失败、幂等与不确定提交、保存失败、会话/CSRF/Host/Origin/peer/资源归属隔离、开发环境/LAN 限制、并发上限和禁止浏览器地址覆盖，以及真实客户端的 prompt/history/queue/view HTTP 协议、重定向和异常响应。

前端新增覆盖生成中切换页面/画格后的原目标绑定、目标已删除保留预览、Mock 状态轮询与受保护图片下载、失败/超时及恶意图片 URL 拒绝。原有工程、图层、气泡、布局、编辑等测试全部保留。

完整结果：

* `python -m pytest`（在 nai_flask）：293 passed。
* `npm test`：33 passed。
* `npm run lint`：0 errors，仍为同 1 条已有警告。
* `npm run build`：通过，静态导出包含 `/comfycomic`、`/login`、`/main`。
* `python scripts/verify_release.py`：发布扫描通过。
* `git diff --check`：通过。

## 浏览器 Mock 冒烟

使用环境已有 Playwright/Chromium、临时私有 data 目录、显式 development+Mock+local 配置，Waitress 只监听 `127.0.0.1:5000`：

1. 桌面 1440×1000：无 NovelAI 账户访问入口、使用原模板创建两个画格，向画格 1 提交后选中画格 2；完成后直接读取 IndexedDB 草稿，确认只有原页面的画格 1 保存了 PNG data URL，画格 2 仍无图；前端预览出现，浏览器 pageerror 为 0。
2. 移动模拟 393×851、touch：新浏览器上下文进入开发入口，触摸选择画格、输入提示词、生成并回填；无页面横向溢出，无 pageerror。

可复现脚本：`scripts/comfyui_browser_smoke.py`，在已构建并开启 loopback Mock 的 Linux 开发环境运行。Playwright/Chromium 仅为可选验证工具，没有加入产品依赖。脚本首先确认 Mock 标记，避免误向真实 GPU 提交。图像与截图都为 Mock，不提交生成文件。

未完成的验证：Windows 实机、安卓 Chrome 真机、Tailscale、真实 ComfyUI/模型节点/显存/图像质量，均未声称通过。云端不具备用户电脑的 GPU 或真实 API 工作流。
