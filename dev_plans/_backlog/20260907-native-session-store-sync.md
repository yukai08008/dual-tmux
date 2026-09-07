# BL-RUNTIME-002 — Codex/Claude Client-local session store 跨机器复制

## 背景

v0.4.51 已能识别 OpenCode、Codex、Claude 的精确 session writer，并对 lease、attached、progress 与重复 writer 做统一判断。但 Codex 的 `~/.codex/sessions` 和 Claude 的 `~/.claude/projects` 仍属于 Client-local store；只同步 session ID 不足以保证另一台 Client 可以 resume。

## 当前安全行为

- 同一机器上的三客户端 freeze/resume 继续可用。
- 远端 bullet 留在同一 SSH/container store 时可 handoff。
- trigger 或 local bullet 使用 Codex/Claude 时，跨 Client handoff 返回 `snapshot_persistence_unsupported`，不会启动一个缺数据的新 writer。

## 后续范围

- 为 Codex/Claude 建立按 Client/source 隔离的中心 snapshot tree、manifest、revision 和尾记录 hash。
- export/import 必须保留原 session UUID，并验证目标 Client 可发现该 UUID。
- 与现有 OpenCode persist 一样采用 merge-before-commit；分叉与冲突 fail closed。
- 加密/权限边界不得把认证文件、全局配置或其他项目 session 一并同步。
- 完成 local→Hub→另一 Client 的真实 E2E 后，才移除 v0.4.51 的 handoff 拒绝门。
