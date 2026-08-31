# v0.06 PRD — Agent 客户端版本展示

> 父版本：v0.05 API 能力
> 起草日期：2026-08-31
> 类型：Web 版（双数）
> 范围来源：v0.05 Agent 客户端元数据

## 0. 一句话目标

把 freeze 固化的 trigger/bullet 客户端名称、版本和运行位置展示在 CLI 与 Web 隧道页面，并正式发布为 dual-tmux `0.4.38`。

## 1. 范围与不变量

### 1.1 In-scope

- `dt ls` side 单元格显示 `tool@version`。
- `dt inspect` 分列显示客户端版本与 local/ssh/docker 位置。
- Web `/api/tunnels`、`/api/tunnel` 返回两侧完整 `agent_client`。
- Web 隧道页显示两侧客户端名称、版本和位置。
- 文档说明 `tool/parser/agent_client` 的职责差异。

### 1.2 Out-of-scope

- Codex/Claude pane 内容专用 parser。
- Codex/Claude session resume。

### 1.3 不变量

- 旧隧道无字段时显示 `—`，页面不报错。
- Web 不显示 executable 全路径，避免无必要暴露本机目录；API/JSON 保留审计字段。
- 运行时数据不在 Git 追踪中。

## 2. 风险登记表

| ID | 严重度 | 风险 | 缓解措施 | 责任人 |
|---|---|---|---|---|
| R1 | medium | 旧 JSON 导致前端取空对象失败 | 所有读取使用空对象回退并加旧数据测试 | Coder |
| R2 | low | 元数据挤压现有布局 | 使用紧凑单行 client 状态条 | PM |

## 3. 签名

Agent-PM-v0.06
