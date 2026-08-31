# v0.4.40 PRD — Agent Adapter 与统一控制内核

> 父版本：v0.4.39
> 起草日期：2026-08-31
> 类型：基础架构迭代（沿用项目 SemVer 发布线）
> 范围来源：公司推广准备评估

## 0. 一句话目标

建立可查询、不可虚报的 Agent 能力模型，以及供 CLI、Web 和未来飞书共同调用的统一控制服务。

## 1. 范围与不变量

### 1.1 In-scope

- 为 OpenCode、Codex、Claude 建立 Agent Adapter 注册表和能力矩阵。
- 明确区分客户端元数据采集与可恢复会话 freeze。
- 建立结构化 `ControlService`、操作目录、结果和错误合同。
- 将隧道 list/get/send/freeze/resume/model 的 CLI/Web 调用迁入控制内核。
- Web 暴露只读 capabilities/operations API。
- 更新 README 架构和能力边界。

### 1.2 Out-of-scope

- Codex/Claude 的原生会话启动、freeze/resume：v0.4.41。
- Web 全 CLI 功能、安全与审计：v0.4.42。
- 飞书绑定、身份与控制面：v0.4.43 及以后。

### 1.3 不变量

- 本地模式无需 Hub 即可使用。
- Hub 切换继续遵守 merge-before-commit，无损保留隧道。
- 旧 tunnel JSON 继续可读，Agent 新字段保持向后兼容。
- 不支持的能力返回明确错误，不能伪装成功。
- 运行时数据不在 Git 追踪中。
- Web 变更必须有自动化测试和浏览器 E2E。

## 2. 顶层蓝图

```text
CLI ─┐
Web ─┼─> ControlService ─> operation catalog ─> tunnel/tmux/agent operations
飞书 ┘          │
                └─> Agent Adapter registry ─> opencode/codex/claude capabilities
```

## 3. Agent Adapter

每个 adapter 提供稳定的客户端标识、显示名、别名和能力对象。能力至少覆盖 detect、version、start、send、metadata_freeze、session_freeze、resume、model，以及 local/ssh/docker 环境。

## 4. ControlService

控制操作具备 name、required capability、risk、surfaces、audit event 元数据。服务返回统一 `ControlResult`，失败使用带 code、HTTP status 和 detail 的 `ControlError`。

## 5. 迁移策略

本版用薄服务层包住已经稳定的 CLI 实现，避免重写 freeze/resume 的远端与持久化细节；CLI 和 Web 都改从同一服务入口调用。后续版本再逐项下沉内部实现。

## 6. 风险登记表

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | 循环依赖导致 CLI/Web 启动失败 | 控制层对旧实现延迟导入，并以 compile/import 测试门禁 | Coder |
| R2 | high | Codex/Claude 能力被误报为完整支持 | session_freeze/resume/start/model 明确为 false，并增加测试 | PM |
| R3 | medium | Web 错误语义变化造成前端回归 | 保持原 HTTP 状态兼容，新增结构化 JSON API 测试 | Tester |
| R4 | medium | 控制层迁移改变同步副作用 | 复用既有 apply 实现，运行全量回归与真实升级验证 | Coder |

## 7. 签名

Agent-PM-v0.4.40
