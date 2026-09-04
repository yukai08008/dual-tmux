---
id: session-ownership
type: summary
status: active
updated: 2026-09-02
tags: [dual-tmux, ownership, resume, session]
depends_on:
  - "[[20-details/decision-lease-activity-separation|Lease 与活动分离决策]]"
  - "[[20-details/decision-session-snapshot-convergence|Session snapshot 收敛决策]]"
related:
  - "[[20-details/incident-20260902-lockscreen-lease|锁屏租约误判事故]]"
---

# Session Ownership

## Summary

dual-tmux 的跨 Client 安全性必须同时维护四个正交事实：写权限租约、runtime 存活、用户 attached 和 Agent semantic progress。lease heartbeat 只证明 owner daemon 在线，不能表示用户活跃或任务有进展。

## Current state

- v0.4.48.post4 仍使用 v1 文本 lease 和整屏 fingerprint。
- claim 失败会隐式 drop 本地 tmux；相同 session ID 没有 writer 单活保护。
- v0.4.49 规划 Lease v2、handoff、两阶段 resume 和 writer probe。
- v0.4.49 同时规划内建 snapshot export/manifest 与 freshness resolver；同 ID 旧 revision 不算恢复成功。
- v0.4.50 规划四维 Web 面板与安全接管向导。

## Details

- [[20-details/decision-lease-activity-separation|Lease 与活动分离决策]]
- [[20-details/decision-session-snapshot-convergence|Session snapshot 收敛决策]]
- [[20-details/incident-20260902-lockscreen-lease|2026-09-02 锁屏租约误判事故]]
