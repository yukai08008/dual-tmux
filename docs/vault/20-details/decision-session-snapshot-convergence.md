---
id: decision-session-snapshot-convergence
type: decision
status: active
updated: 2026-09-02
tags: [dual-tmux, session, snapshot, resume]
part_of:
  - "[[10-summaries/session-ownership|Session Ownership]]"
related:
  - "[[20-details/incident-20260902-lockscreen-lease|锁屏租约误判事故]]"
---

# Session snapshot 收敛决策

## Decision

跨 Client resume 必须分别证明 binding 正确和 conversation snapshot 最新。Session ID 相同只证明身份相同，不证明本地消息内容达到 owner 的最新 revision。

Owner Client 内建原子 export 并发布 manifest；接管方比较 session updated_at、最后 message ID/hash 和内容 hash。本地 revision 较旧时先备份再导入/合并并验证，多源分叉时 fail closed。

## Rationale

- `dt pull` 只同步 tunnel/entry，不同步 conversation。
- 现有 persist job 只 rsync 已存在的 JSON，无法保证 export 实际发生。
- OUC 的 Hub OpenCode source 目录为空，而 Home 同 ID trigger 停在数日前。
- OUC lease holder 为 `tm_ouc`，Hub persist source 为 `tm_andy_ouc`，identity 漂移未被阻断。
- `ensure_local()` 只做 by-ID existence check，会把同 ID 的旧内容误判为无需导入。

## Consequences

- persist publish 必须以 export 成功和 manifest 完整为前置条件。
- `config.client`、persist source 和 lease holder 的 identity 漂移必须可诊断。
- resume plan 同时展示 binding revision、snapshot source/revision 与 freshness。
- 导入后必须校验尾消息，不能只验证 session ID 存在。
