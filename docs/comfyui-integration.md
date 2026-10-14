# ComfyComic M1：ComfyUI 接入

本轮保留原 NovelAI 模式、AGPL-3.0 许可证和原作者版权。新增基础文生图适配，不包含真实 Qwen/Krea2 工作流或模型。云端结果只验证 Mock，不代表 RTX 4070 Super 上真实 GPU 联调通过。

## 架构

安卓/桌面浏览器 → 同源 `/api/comfyui/*` → Flask Blueprint → 工作流注册器、会话任务管理器 → ComfyUI HTTP API。

* `nai_flask/api_utils/comfyui/`：`workflows.py` 校验及复制工作流；`client.py` 真实 HTTP；`mock.py` 进程内协议模拟器；`jobs.py` 归属、状态、幂等及图片存储；`routes.py` 安全接口。
* `/comfycomic` 直接复用现有 `ComicWorkspace`。`ImageGenerationService` 按 `engine` 分派；`useImageGeneration` 负责生成状态。NovelAI 路径保留。
* 每次请求带固定 `target: {pageId, panelId}`，前后端均保留提交时目标。结果转为原编辑器的 `{dataUrl, width, height}`，调用原 `receiveGeneratedImage`。原画格被删除时保留预览，不转投其他画格。
* 原画格、布局、图层、气泡、文字、自由切割、构图、触摸处理及工程 ZIP/JSON 数据格式不变。图像以原有 data URL 进入工程，不依赖会话图片 URL 才能重新导入。

## 配置

应用从 `nai_flask/config.local.json` 读取配置（不提交 Git）。参见 `nai_flask/comfyui.example.json`、`comfyui.mock.example.json`。如果已有配置，请合并字段，不要覆盖自己的配置。

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `comfyui_url` | `http://127.0.0.1:8188` | 仅管理员配置的 HTTP origin，不接收前端覆盖；不带路径、凭据、查询串 |
| `comfyui_workflows` | `""` | 预设数组 JSON 路径；相对后端目录；空值为未注册 |
| `comfyui_timeout_seconds` | `10` | 单次上游网络超时，范围 `(0,120]` |
| `comfyui_job_timeout_seconds` | `600` | 包括排队的任务期限，范围 `[1,3600]` |
| `comfyui_env` | `production` | 本地开发入口/Mock 必须明确设为 `development`（测试用 `TESTING=True`） |
| `comfyui_local_mode` | `false` | 允许仅 loopback 的开发会话，无需 NovelAI |
| `comfyui_mock` | `false` | 独立 Mock；不能与真实预设混用 |

Mock 和本地开发入口要求 `allow_lan=false`；启动时不满足即拒绝。Mock 无监听端口，不是无鉴权 HTTP 服务；使用相同受保护的应用 API，图片含明显测试水印。

## 工作流注册与映射

在 ComfyUI 中导出 **API 格式** JSON，不能使用包含 `nodes/links` 的 UI 工程导出。将真实 JSON 放入未跟踪的 `nai_flask/workflows.local/`。新建同目录 `presets.json`，内容为预设数组；文件变更后重启 Flask。程序不假设模型名称、采样器或自定义节点已安装。

以下只是映射结构说明。`YOUR_*` 必须替换成你自己的 API 图中真实节点 ID 和 input 名称，**不是可运行工作流**：

```json
[
  {
    "id": "my-text-to-image",
    "name": "我的文生图",
    "description": "用户在本机验证后的 API 工作流",
    "file": "my-api-workflow.json",
    "fields": {
      "positive_prompt": {
        "label": "正向提示词", "type": "string", "required": true,
        "targets": [{"node": "YOUR_TEXT_NODE", "input": "YOUR_TEXT_INPUT"}]
      },
      "seed": {
        "label": "Seed", "type": "integer", "default": 0,
        "min": 0, "max": 9007199254740991,
        "targets": [{"node": "YOUR_SAMPLER_NODE", "input": "YOUR_SEED_INPUT"}]
      }
    },
    "output_nodes": ["YOUR_SAVE_IMAGE_NODE"]
  }
]
```

必须配置正向提示词映射 `positive_prompt` 和至少一个 `output_nodes`。其余字段可省略。可按相同结构增加 `negative_prompt`、`width`、`height`、`steps`、`cfg`、`sampler` 等；字段类型支持 `string/integer/number`，可配 `default/required/min/max/choices/label`。一个字段可映射多个 literal input；不允许覆盖节点连接或重复映射同一个 input。不在配置中的参数会被拒绝。数值建议始终设置合理上下限，seed 使用 JS 安全整数范围。宽高上限还需按 12GB 显存和具体模型自行验证。

工作流文件必须位于预设目录内，拒绝越界路径。启动校验映射目标和图连接；未知参数/缺失必填参数明确报错。上游仍会校验真实节点和模型是否存在。支持未来按配置增加不同结构的 Qwen、Krea2 预设；M1 只提供文生图参数输入，文件/参考图/遮罩上传尚未实现。

输出节点须产生 `type=output` 的 PNG/JPEG/WebP 图片（例如你自己的 SaveImage）。`temp/input` 输出暂不支持。单任务最多 8 张、单图不超过 32 MiB/3200 万像素。M1 前端显示第一张，后端安全 URL 保留所有返回图片。拒绝上游重定向、异常响应和路径穿越；不把文件系统路径或上游图完整内容暴露给前端。

## 接口

所有 mutation 沿用现有 Host、真实 peer 和 Origin 检查；生成还要求有效 HttpOnly/SameSite=Strict Session 与 `X-CSRF-Token`。GET 工作流/健康/任务/图片也要求会话。开发会话只允许 ComfyUI API 与会话查询/注销，不能访问 NovelAI 账户或本地文件浏览 API。

| 路径 | 方法 | 行为 |
| --- | --- | --- |
| `/api/comfyui/capabilities` | GET | 只公开开发入口是否启用及是否 Mock，不公开地址或工作流 |
| `/api/comfyui/session` | POST | 显式启用且 loopback 时建立开发会话；仍需合法 Origin |
| `/api/comfyui/health` | GET | 通过 ComfyUI `/system_stats` 检查连通性 |
| `/api/comfyui/workflows` | GET | 返回已校验预设和支持字段 |
| `/api/comfyui/jobs` | POST | `{request_id, workflow_id, parameters, target}`；返回 202 和任务 |
| `/api/comfyui/jobs/{id}` | GET | 查询内部任务，经 `/history/{prompt_id}`、`/queue` 更新状态 |
| `/api/comfyui/jobs/{id}/images/{index}` | GET | 当前会话拥有的已保存图片，无任意文件路径参数 |

状态为 `queued/running/completed/failed/timed_out`；轮询显示队列位置，尚无 WebSocket 节点级百分比。结果包含 `prompt_id/test_data/target/images/error/code`。离线为 `COMFY_OFFLINE`，超时为 `COMFY_TIMEOUT`，上游执行失败为 `COMFY_EXECUTION_FAILED`，图片验证/落盘失败为 `COMFY_IMAGE_SAVE_FAILED`。失败任务仍返回任务对象，前端按终态明确显示；健康端点离线直接返回 503/504。

同会话相同 `request_id` 和内容返回原任务；同 ID 不同内容返回 409。提交超时也保留 ID，避免不确定情况下再次提交。同会话最多 2 个在途任务，全局最多 128 条；过期记录在提交/轮询时清理（至少保留 1 小时），清理同时删除所属结果图。任务和幂等状态仅存在单进程内存，不支持多 worker、重启恢复或跨会话取图。请使用现有单进程 Waitress。GPU/HTTP 操作暂以锁串行管理，M2 再完善后台执行和任务持久化。

生成图片存于私有 `data/comfyui-results/`，不加入原 NovelAI 图库索引。会话注销/过期/服务重启后无法通过旧 URL 再取图，磁盘文件可能保留，需自行管理；在页面中及时下载图像或导出可编辑漫画工程。轮询超时/离线不会自动重试 GPU；已提交的上游任务可能继续执行，需要先检查 ComfyUI 的队列/历史。离开页面会停止前端轮询，但不会取消 GPU 任务；刷新后 M1 不恢复在途任务。

## 安全边界与 M2 阻塞事项

M1 独立入口只面向本机开发测试，**不能作为安卓远程使用的完成品**。不修改现有 NovelAI 登录验证、Host 白名单和 CSRF 策略。请勿打开 `allow_lan`、端口映射或用反向代理暴露本地开发入口；保持 ComfyUI 只监听 `127.0.0.1:8188`。

M2 需要应用自身的正式认证（与 NovelAI 凭据解耦）、安全 Cookie/HTTPS、Tailscale 明确 Host/peer/Origin 白名单、会话与图片授权/过期策略及审计；Tailscale 仅负责网络连通，不能替代应用认证。本轮没有开放 Tailscale Host 支持。
