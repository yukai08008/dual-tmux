# v0.05 PRD — Agent 客户端元数据

> 父版本：v0.4.37
> 起草日期：2026-08-31
> 类型：API 版（单数）
> 范围来源：用户对话定稿

## 0. 一句话目标

在每次 freeze 时分别记录 trigger 与 bullet 实际使用的 Agent CLI 名称、版本、可执行文件和运行位置，为不同客户端/版本的行为差异提供可审计依据。

## 1. 范围与不变量

### 1.1 In-scope

- 支持 `opencode`、`codex`、`claude` 三种 Agent CLI。
- trigger 本地采集；bullet 根据工作点在 local、SSH 或 Docker 内采集。
- freeze 将结果写入每侧 `agent_client`，并写入事件日志与 `dt inspect`。
- 本地 pane 为 Codex/Claude 时自动识别；远端可通过 `dt freeze --tool` 明确指定。
- OpenCode 保持现有 session/model/slug freeze 行为。
- Codex/Claude 本版只固化客户端元数据，不宣称 session resume 已实现。

### 1.2 Out-of-scope

- Codex/Claude 会话数据库解析、session resume 与 persist。
- Codex/Claude 专用 Web pane parser；留给下一双数 Web 版。
- 自动安装或升级任何 Agent CLI。

### 1.3 不变量

- 旧隧道缺少 `agent_client` 时继续兼容。
- 不采集凭据、环境变量、配置内容或认证信息。
- 版本查询只允许固定白名单命令，禁止把隧道 JSON 拼成任意 shell。
- Agent 版本采集失败不覆盖已有 session 信息，并留下错误字段。
- 运行时数据不在 Git 追踪中。

### 1.4 与历史版本的关系

v0.4.37 只记录 `tool/model/session_id/parser`。v0.05 增加可选的 `agent_client` 对象，不改变已有字段语义。

## 2. 顶层蓝图

```text
tmux pane + work point + --tool
             │
             ▼
      resolve agent CLI
             │
     ┌───────┼────────┐
     ▼       ▼        ▼
   local    ssh     docker
     └───────┼────────┘
             ▼
 name/version/path/location/collected_at
             │
             ▼
 tunnel.trigger.agent_client
 tunnel.bullet.agent_client
```

## 3. 数据模型

```json
{
  "agent_client": {
    "name": "opencode",
    "version": "1.18.20",
    "version_output": "1.18.20",
    "executable": "/Users/name/.opencode/bin/opencode",
    "location": "local",
    "host": "",
    "container": "",
    "collected_at": "2026-08-31T10:00:00+08:00",
    "error": ""
  }
}
```

## 4. 风险登记表

| ID | 严重度 | 风险 | 缓解措施 | 责任人 |
|---|---|---|---|---|
| R1 | high | SSH/Docker 查询形成命令注入 | Agent 名称白名单；所有容器参数 shell quote | Coder |
| R2 | medium | pane 命令是 ssh，无法自动判断远端 Agent | 使用已有 side tool；支持 `--tool codex/claude` 显式指定 | PM |
| R3 | medium | CLI 的版本输出格式变化 | 保存原始首行，同时用宽松数字正则提取规范版本 | Coder |
| R4 | low | 采集失败阻断已有 OpenCode freeze | 失败写 `error`，session freeze 独立执行 | Tester |

## 5. 签名

Agent-PM-v0.05
