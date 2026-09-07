# BL-RUNTIME-002 — Codex/Claude Client-local session store 跨机器复制

## 背景

v0.4.51 已能识别 OpenCode、Codex、Claude 的精确 session writer，并对 lease、attached、progress 与重复 writer 做统一判断。但 Codex 的 `~/.codex/sessions` 和 Claude 的 `~/.claude/projects` 仍属于 Client-local store；只同步 session ID 不足以保证另一台 Client 可以 resume。

## v0.4.53 交付状态

- PR #31 已合并，完整验收见 `dev_plans/v0.4.51-v0.4.53/TEST_CASES_FINAL.md`。
- 已交付精确 UUID export/import、manifest/hash、append-only 血缘、原子导入、generation fencing 与 Hub native persist。
- v0.4.51 的拒绝门已由安全复制协议替代；混合旧 owner 仍会明确拒绝 handoff，不会无数据接管。

## 后续范围

- 为 Codex/Claude 建立按 Client/source 隔离的中心 snapshot tree、manifest、revision 和尾记录 hash。
- export/import 必须保留原 session UUID，并验证目标 Client 可发现该 UUID。
- 与现有 OpenCode persist 一样采用 merge-before-commit；分叉与冲突 fail closed。
- 加密/权限边界不得把认证文件、全局配置或其他项目 session 一并同步。
- 完成 local→Hub→另一 Client 的真实 E2E 后，才移除 v0.4.51 的 handoff 拒绝门。
