# v0.4.46 PRD — Web 全功能控制面

> 父版本：v0.4.45（PR #9）
> 起草日期：2026-08-31
> 类型：Web 版（偶数）
> 范围来源：正式列装要求“通过 Web 可以实现所有功能”

## 0. 一句话目标

让日常 tunnel、Agent、同步和恢复操作无需回到终端，并通过同一个 ControlService 保持 CLI/Web/未来飞书语义一致。

## 1. 范围与不变量

### 1.1 In-scope

- Tunnel：列表、详情、创建、删除、连接重放、drop、pane 输入输出。
- Session：三客户端选择、freeze、resume、模型切换（按能力显隐）。
- Hub：查看当前 local/Hub 模式、push、pull；模式切换必须展示影响并确认。
- Health：缓存状态、立即 probe、显式 recover、auto_recover 开关。
- 已有 Memory、Events、Skills、Doctor 能力通过 Web 可达；不能安全映射的维护命令显示 CLI escape hatch 和原因。
- 所有写操作进入统一操作目录、结构化错误和事件审计。
- 浏览器 E2E 覆盖创建 → 操作 → freeze/resume → 删除的闭环。

### 1.2 Out-of-scope

- 浏览器直接执行 `upgrade`/`hotfix`；软件供应链更新保留 CLI，并在 Web 展示版本与命令。
- 浏览器保存 SSH 密钥、Agent 凭据或飞书凭据。
- 公网监听；继续仅绑定 `127.0.0.1`。
- 飞书扫码绑定本身；本版输出稳定 ControlService 合同供下一版本接入。

### 1.3 “所有功能”的验收边界

“所有功能”指公司用户日常管理 tunnel 所需的全部业务操作可在 Web 完成；安装、升级、cron 安装和破坏性运维属于主机维护面，Web 必须可见、可诊断并提供明确命令，但不远程代执行。

### 1.4 不变量

- Web 不绕过 Hub ownership、客户端 capability 或恢复熔断。
- 删除、force takeover、模式切换等高风险操作必须二次确认。
- 页面刷新不触发 SSH probe、push/pull、恢复或删除。
- local 模式 Web 操作不产生 SSH 调用。
- 不修改 `~/.ssh`，不把运行时数据纳入 Git。

## 2. 控制面结构

```text
Web UI → /api/control/* → ControlService → CLI domain functions
飞书（未来） ────────────────┘
```

HTTP handler 不直接拼接 tmux/ssh 命令；只做输入解析、CSRF/local-origin 校验和 ControlError 映射。

## 3. 风险登记

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | Web 误删 tunnel | 名称回显确认 + ControlService 审计 | Coder |
| R2 | high | 页面轮询产生副作用 | GET 全部只读，写操作仅 POST | Reviewer |
| R3 | high | Web 与 CLI 行为漂移 | 两者共用 ControlService/领域函数 | Coder |
| R4 | high | 模式切换造成 Hub 数据丢失 | 复用 merge-before-commit 事务 | Tester |
| R5 | medium | UI 暴露客户端不支持操作 | capability matrix 驱动禁用和说明 | Coder |

## 4. 签名

Agent-PM-v0.4.46
