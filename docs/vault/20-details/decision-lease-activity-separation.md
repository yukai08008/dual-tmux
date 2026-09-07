---
id: decision-lease-activity-separation
type: decision
status: active
updated: 2026-09-02
tags: [dual-tmux, lease, activity, fencing]
part_of:
  - "[[10-summaries/session-ownership|Session Ownership]]"
related:
  - "[[20-details/incident-20260902-lockscreen-lease|锁屏租约误判事故]]"
---

# Lease 与活动分离决策

## Decision

Lease 只表达某个 Client generation 的写权限。runtime、attached 与 semantic progress 作为独立 evidence 保存和展示，任何一个维度都不得推断另一个维度。

跨 Client resume 使用两阶段事务：先完成 ownership、入口、binding、persist/DB 和 session writer preflight，再改变 tmux；owner 可达时通过 request/ack handoff，无法证明安全时 fail closed。

## Rationale

- 屏幕锁定不会停止 cron、tmux 或 daemon，heartbeat 不等于人仍在使用。
- 整屏 hash 会被 spinner/TUI chrome 欺骗，静止也不等于可以终止长任务。
- 同一 session 多 writer 比一次接管失败风险更高，必须在启动前阻断。
- preflight 拒绝是正常控制流，不应带来删除 pane 等副作用。

## Consequences

- Lease v2 记录 generation、instance、handoff 和 evidence 时间戳。
- v1 lease 向后兼容读取并惰性迁移。
- `--force` 不再等于跳过安全检查，必须明确 stale writer 处置。
- Web/CLI/tmux chip 只能消费 ControlService 的统一 ownership snapshot。
