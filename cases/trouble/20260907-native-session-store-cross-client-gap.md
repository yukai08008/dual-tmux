# Codex / Claude 跨 Client 只有 UUID、没有本地 session store

## 背景

v0.4.51 已能冻结三类 Agent、识别 writer 并执行 Ownership handoff，但 Codex
会话只存在 `~/.codex/sessions`，Claude 会话只存在 `~/.claude/projects`。另一台
Client 即使拿到 UUID，也不能保证原生 CLI 能发现并接续该会话。

## 根因

- Hub 原来只同步 tunnel binding、tmux persist 与 OpenCode export。
- Codex/Claude 没有按冻结 UUID 导出到 Hub 的协议。
- 直接 rsync 整个配置根会同时复制认证、全局设置、skills 和无关项目会话，风险不可接受。

## v0.4.51 的安全行为

trigger 或本地 bullet 使用 Codex/Claude 时，跨 Client handoff 以
`snapshot_persistence_unsupported` 拒绝，避免启动同 UUID 的空会话或第二 writer。

## 跟进

由 v0.4.53 的精确 native session snapshot 协议关闭此缺口。
