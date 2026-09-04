---
id: incident-20260902-lockscreen-lease
type: incident
status: active
updated: 2026-09-02
tags: [dual-tmux, incident, lockscreen, resume]
part_of:
  - "[[10-summaries/session-ownership|Session Ownership]]"
implements:
  - "[[20-details/decision-lease-activity-separation|Lease 与活动分离决策]]"
  - "[[20-details/decision-session-snapshot-convergence|Session snapshot 收敛决策]]"
related: []
---

# 2026-09-02 — 锁屏租约误判与有副作用的 resume 拒绝

## Summary

锁屏的 `tm_ouc` 仍由 cron tick 续租；`tm_andy_home` resume 被判“last 30 ticks still changing”，且拒绝前本地 op/run tmux 已被删除。

## Impact

本机进入无 pane 的半完成状态；直接 force 存在为同一远端 session 再启动 writer 的风险。

## Evidence

- 最近 30 条样本跨约 4 小时，而最近 15 条 fingerprint 相同。
- tick 对“任一 tmux session 存在”的 tunnel 续租，不检查 attached/semantic progress。
- `require_active()` 在 claim 异常路径执行 `drop_local()`。
- 远端曾有两个进程持有相同 OpenCode session ID。
- OUC 的 Hub trigger snapshot 目录为空；Home 同 ID trigger 仍是 8 月 30 日内容，而 bullet 已有 9 月 2 日最新问答。
- `ensure_local()` 只检查 ID 存在，不检查 snapshot revision。

## Root cause

ownership、liveness、interaction 和 progress 未建模为独立事实；resume 缺少 preflight/commit 边界和 writer singleton。Binding 与 conversation snapshot 没有共同 freshness 合同。

## Repair

进入 v0.4.49/v0.4.50 规划，当前不以 `--force` 临时绕过。

## Prevention

实施 [[20-details/decision-lease-activity-separation|Lease 与活动分离决策]] 和 [[20-details/decision-session-snapshot-convergence|Session snapshot 收敛决策]]，并以双 Client、锁屏 heartbeat、断网、stale snapshot 和 duplicate writer 做真实 E2E。
