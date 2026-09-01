# Cases

本目录保存 dual-tmux 在真实使用中发现的问题与已验证的解决方案，用于跨会话追踪和回归。

## 目录约定

- `trouble/`：问题现象、事实证据、根因和影响。
- `solution/`：对应解决步骤、不变量和验证结果。

## 索引

| 日期 | 案例 | 问题 | 解决方案 | 状态 |
|---|---|---|---|---|
| 2026-09-01 | 飞书多 WS 所有权 | [trouble](trouble/20260901-feishu-multiple-ws-ownership.md) | [solution](solution/20260901-feishu-single-bot-fencing-solution.md) | RESOLVED |
| 2026-08-31 | 飞书 Hub 凭据归属不一致 | [trouble](trouble/20260831-feishu-hub-credential-owner-mismatch.md) | [solution](solution/20260831-feishu-hub-credential-owner-mismatch-solution.md) | RESOLVED |
| 2026-08-31 | 中心隧道未自动同步 | [trouble](trouble/20260831-中心隧道未自动同步.md) | [solution](solution/20260831-中心隧道未自动同步-解决.md) | RESOLVED |
