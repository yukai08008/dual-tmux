# 2026-09-09：Lease 误踢修复方案

## 机制

1. daemon 的 lease worker 是活动隧道 Lease 的唯一稳态写入者；ownership worker
   只读事实并处理 handoff。
2. `dt tick` 不再 claim 活动隧道，只在确认本 Client 当前 owned 后采样、导出与同步。
3. Lease v2 即使跨过 4 秒 deadline，也允许完全相同的
   `client + instance_id + generation` 在 Hub flock 内原子续租。
4. fault takeover 与续租共用同一 Hub flock：reservation 先发生时旧端续租失败并
   self-fence；续租先发生时新端看到活动 Lease，不能开始故障接管。
5. foreign/free 以及已确认的 generation 变化继续 fail-closed，不改变旧端退出 shell
   的体验合同。

## 验证要求

- 单元测试覆盖过期精确恢复、错误 instance/generation 拒绝、takeover reservation
  后拒绝旧端、tick 不 claim、daemon writer 职责分离。
- 本机安装后恢复 `dt-company_intro_v2`，观察多个分钟 tick 周期，确认 Lease 连续且
  tmux 不被删除。
- 完整 pytest、Ruff、构建通过后才发布。

## 验收结果

- PR #42 已合并到 `main`（merge `a13ee1a`），Release `v0.4.55.post3` 已发布。
- 348 tests collected：346 passed、2 skipped；聚焦 Ruff、wheel/sdist build 通过。
- 本机真实安装 post3 并重启 daemon；`dt-company_intro_v2` generation 19 跨过
  09:20、09:21、09:22 三个分钟 tick，trigger/bullet 均持续存在，无 `dt.drop`。
- 实测确认 tick 不再发出 `hub.claim`；OpenCode SQLite integrity check 为 `ok`。
