# dual-tmux Web 前端架构建议

## 结论

dual-tmux 的 Web 控制台建议采用：

> **前后端源码解耦、API 契约耦合、单进程/单安装包交付。**

开发时使用正式 Web 框架组织前端，部署时仍保持 `dt web` 一个命令，不额外引入需要用户维护的 Node 服务。

```text
React + TypeScript + Vite
          │
          │ OpenAPI / JSON / SSE
          ▼
FastAPI Web Adapter
          │
          ▼
ControlService
          │
    ┌─────┼─────┐
   tmux   Hub   recovery
```

## 为什么适合 dual-tmux

当前 `src/dual_tmux/web.py` 已经是一个大型单文件，同时包含：

- HTTP Server 和路由
- HTML 模板
- 全局 CSS
- 页面级 JavaScript
- 前端状态管理
- API 参数转换
- `ControlService` 调用
- 部分业务判断

随着飞书、技能、终端、健康恢复和多 tunnel 管理继续增长，修改一个页面容易影响其他功能。

但也不建议立即拆成两个独立部署的服务，因为 dual-tmux 是本地 CLI 工具：

- Web 只监听 `127.0.0.1`。
- 需要直接访问本机 tmux 和文件。
- 用户期待 `dt web` 即开即用。
- 独立 Node 服务会增加安装、升级和守护复杂度。

## 推荐技术组合

### 后端：FastAPI

FastAPI 只作为 Web 适配层，不承载 tunnel 核心业务逻辑。

优点：

- 路由和请求模型可以按功能拆分。
- 自动生成 OpenAPI。
- 前端可从 OpenAPI 生成 TypeScript 类型。
- 后续可支持 SSE 和 WebSocket。
- 现有同步 tmux、SSH 和 rsync 操作可以先保留，交给线程池执行。

路由只做输入校验和协议转换：

```python
@router.post("/tunnels/{name}/resume")
def resume(name: str, request: ResumeRequest):
    return controls.resume(name, force=request.force).as_dict()
```

真正的业务仍由 `ControlService`、`hub`、`recovery` 和 `tmux` 完成。

### 前端：React + TypeScript + Vite

Tunnel 页面已经存在明显的复杂交互状态：

- 多 tunnel 标签
- op/run pane 切换
- pane 轮询
- pending turn 与 completion baseline
- health/sync 状态
- freeze/resume/reconnect
- 基于 capability 的控件启用和禁用
- 浏览器工作区恢复

推荐搭配：

- **TanStack Query**：管理 API 数据、轮询、缓存和 mutation。
- **Zustand**：仅保存标签、选中 pane、布局等纯 UI 状态。
- **OpenAPI 生成类型**：减少前后端字段漂移。
- **Zod**：可用于对实时数据或外部输入做额外校验。
- **CSS Modules**：控制样式作用域，避免再形成一个全局 CSS 大块。
- **Vitest + Testing Library**：组件和交互测试。
- **Playwright**：覆盖关键控制链路。

暂时不建议引入 Redux、Next.js 或微前端。

## 前端按业务能力切片

不建议只按 `components/pages/utils` 划分目录，否则这些目录最终仍会变成杂物箱。建议以 feature 为边界：

```text
webui/
├── src/
│   ├── app/
│   │   ├── router.tsx
│   │   ├── providers.tsx
│   │   └── shell/
│   ├── features/
│   │   ├── tunnels/
│   │   ├── panes/
│   │   ├── sessions/
│   │   ├── health/
│   │   ├── hub/
│   │   ├── skills/
│   │   ├── memory/
│   │   └── feishu/
│   ├── shared/
│   │   ├── api/
│   │   ├── ui/
│   │   └── types/
│   └── main.tsx
└── vite.config.ts
```

每个 feature 内部保留它自己的 API、query、类型和组件：

```text
features/tunnels/
├── api.ts
├── queries.ts
├── types.ts
├── TunnelList.tsx
├── TunnelWorkspace.tsx
└── TunnelActions.tsx
```

页面层只负责组合 feature，不直接拼接请求和实现业务规则。

## 后端建议结构

```text
src/dual_tmux/
├── control.py
├── hub.py
├── recovery.py
├── tmux.py
└── web/
    ├── app.py
    ├── dependencies.py
    ├── schemas/
    ├── routes/
    │   ├── tunnels.py
    │   ├── panes.py
    │   ├── sessions.py
    │   ├── health.py
    │   ├── skills.py
    │   └── feishu.py
    └── static/          # Vite 构建产物
```

固定调用链应为：

```text
React → HTTP route → ControlService → domain modules
```

不应出现：

```text
React → 任意私有接口 → 直接改 JSON / 调 subprocess
```

## 耦合边界

建议保留三种明确、可管理的耦合。

### 1. API 契约耦合

前端知道 `/api/v1/tunnels` 和响应 DTO，但不知道 Python 内部实现和 tunnel JSON 的全部字段。

### 2. 能力耦合

前端根据 `/api/capabilities` 决定是否显示或启用 model、resume 和 freeze，不硬编码 OpenCode/Codex/Claude 的判断逻辑。

### 3. 同包交付耦合

Vite 的静态构建产物打进 Python wheel，由 `dt web` 直接托管。

需要避免：

- 前端直接依赖 tunnel JSON 的完整内部结构。
- 页面复制 Hub 锁和恢复规则。
- GET 请求隐式执行 resume 或其他写操作。
- 前端通过错误文本判断业务状态。
- 每个页面分别封装一套 `fetch()`。

## Pane 实时展示

现阶段不必立即模拟完整终端，可以分两步演进：

1. 保留 `tmux capture-pane`，从 1.5 秒 HTTP 轮询逐步改为 SSE 推送“pane 快照已变化”。
2. 只在真正需要完整交互式终端时，再引入 PTY + WebSocket + xterm.js。

当前 pane 本质上是 Agent TUI 的文本观察窗口。过早引入 xterm.js 容易让用户误以为页面具备完整 attach、resize、鼠标和 alternate-screen 语义。

## API 设计建议

使用资源化接口：

```text
GET    /api/v1/tunnels
GET    /api/v1/tunnels/{name}
GET    /api/v1/tunnels/{name}/panes/{side}
POST   /api/v1/tunnels/{name}/panes/{side}/messages
POST   /api/v1/tunnels/{name}/freeze
POST   /api/v1/tunnels/{name}/resume
POST   /api/v1/tunnels/{name}/reconnect
POST   /api/v1/tunnels/{name}/drop
GET    /api/v1/tunnels/{name}/health
POST   /api/v1/tunnels/{name}/recovery
GET    /api/v1/events
```

写操作统一返回：

```json
{
  "ok": true,
  "operation": "session.resume",
  "data": {},
  "warnings": [],
  "audit_event": "control.session.resume",
  "request_id": "..."
}
```

resume、recovery 和 Hub sync 等耗时操作可以逐步转成 operation/job：

```text
POST /resume → 202 + operation_id
GET  /operations/{id}
SSE  /operations/{id}/events
```

这样前端不会因一次 SSH 检查耗时而让按钮长期停留在 loading。

## 建议迁移顺序

1. 冻结现有 `/api` 行为，补充契约测试。
2. 引入 FastAPI，但暂时继续返回旧页面。
3. 把 API 路由迁到 `web/routes/`，全部通过 `ControlService`。
4. 建立 React 应用外壳和 tunnel 列表。
5. 迁移 pane 捕获、消息发送和 pending turn。
6. 迁移 health、Hub、skills、memory 和 Feishu。
7. 删除 `web.py` 中的 HTML/CSS/JavaScript 字符串。
8. 最后再根据实际需求引入 SSE 或 WebSocket。

## 推荐的最终形态

> **FastAPI + React/TypeScript + Vite，开发时前后端分离，发布时将 Vite 静态产物嵌入 Python wheel；所有业务操作通过 `ControlService` 收口。**

这种方式可以保留 `dt web` 的轻量使用体验，同时解决当前单文件 Web 控制台的扩展和测试问题。
