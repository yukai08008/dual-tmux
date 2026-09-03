# 本机 trigger 会话无 persist 快照导出 + persist 租户名不一致

> 日期：2026-09-02 | 状态：已解决（solution 20260903-trigger-persist-export-missing-solution）

## 背景

核对"另一台机器 pull 能否拿到一致会话"时发现：本机（tm_ouc）从未导出过 OpenCode 会话快照——`~/sessions/opencode/tm_ouc/` 与 `tm_andy_ouc/` 均为空，Hub 上 dt-company_intro_v2 的 trigger 快照停留在 8/30 12:25（tm_andy_home 导出）。

## 两个缺口

1. **导出器缺失**：persist 合同（docs/persist-sync.md）第 1 步"每分钟导出本机 OpenCode 会话"由外部 persist 工具负责，本机没有安装/运行它；dt 自身只读快照、从不导出。
2. **租户名不一致**：`~/.config/session-persist/name` = `tm_andy_ouc`，dt `client` = `tm_ouc`。文档要求两者相同；`sync_persist_identity` 只修正非法值，合法但不一致的旧值被保留。

## 影响

- 另一台机器 `dt pull` + `dt resume` 时，trigger 只能从 Hub import 旧快照，丢 8/30 之后的 trigger 对话。
- bullet 不受影响（会话在服务端容器，resume 直接接同一个远端 session）。

## 临时缓解（2026-09-02）

- 手工 `opencode export ses_fb3abe74…` 371 条消息 → `~/sessions/opencode/tm_andy_ouc/misty-rocket.json`，persist cron 已推上 Hub 并校验内容一致。

## 待决策

- 是否把"每分钟 opencode export 本机活跃会话"收进 dt（例如 tick 内对 live trigger 做快照导出），消除对外部 persist 工具的依赖。
- 是否将 persist 租户名归一到 dt client（考虑存量目录迁移）。
