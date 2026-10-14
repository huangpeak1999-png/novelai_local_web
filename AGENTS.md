# ComfyComic 开发约束

* 原许可证为 AGPL-3.0，保留版权信息；只在用户 Fork 开发分支提交，不修改上游、不自动合并。
* 前端 `next_nai_web` 使用 Next.js/React/MUI，静态 export 由 Flask 提供；浏览器只用同源 `/api`。
* `nai_flask/app.py` 保留原安全边界与 NovelAI 逻辑。ComfyUI 功能放在 `api_utils/comfyui/`，禁止向浏览器开放任意请求地址或文件路径。
* 保留 `ComicWorkspace`、工程格式、图层、气泡、构图和触摸行为；生成目标在提交时固定页面/画格 ID，禁止异步完成时读取当前选择。
* 工作流为服务端信任配置，不把模型名、业务节点 ID/连接写死在适配器；不要虚构可用的 Qwen 工作流。
* Mock 必须显式开发/测试启用、仅 loopback、受会话/CSRF 保护并标记测试图。独立开发会话不得用于 NovelAI 或任意本地文件浏览。
* 不提交 `config.local.json`、`workflows.local/`、凭据、真实工作流、私图、运行数据。运行时输出使用忽略的 data 目录。

验证命令：

```sh
cd nai_flask
python -m pip install -r requirements.txt
python -m pytest
cd ../next_nai_web
npm ci
npm test
npm run lint
npm run build
```

后端测试以 `nai_flask` 为工作目录（与现有 CI 一致）。前端测试沿用 Node 内置 runner，不为基础适配增加大型依赖。云端 Mock 通过不等于真实 GPU 通过；更改前先记录基线，交付时如实报告限制。更多约束见 `docs/comfyui-integration.md`。
