# 锁屏 Client 被判活跃且 resume 拒绝后删除本地 pane

## 状态

- L1：`v0.4.49 (ACTIVE)`
- L2：`feature/v0.4.49-session-ownership (FORKED)`
- L3：`issue-lockscreen-lease-false-active (FOUND)`

## 现象

`tm_ouc` 是已锁屏的另一台笔记本。`tm_andy_home` 执行：

```text
dt resume dt-company_intro_v2
· dropped tmux  op_company_intro_v2 run_company_intro_v2
[err] dt-company_intro_v2 active on tm_ouc (98s ago). last 30 ticks still changing.
```

随后 `dt enter` 也因相同 ownership gate 失败。

## 证据

- Hub lock：`holder@timestamp@generation` 格式的 v1 lease，由 `tm_ouc` 后台 tick 在锁屏期间续租。
- `dt tick` 对任何仍有 op/run tmux 的 tunnel 调用 `hub.claim()`，不要求用户 attached 或 pane 有有效增量。
- activity 最后 30 个 `dt-company_intro_v2` 样本跨约 4 小时；18:17–18:30 有变化，之后最近 15 个 fingerprint 相同。
- `frozen_last_ticks()` 只判断最后 N 条 hash 是否全同，不检查样本覆盖时长；错误信息无条件称 “still changing”。
- `require_active()` 捕获 claim 失败后调用 `drop_local()`，因此 preflight 拒绝会先删除本地 pane。
- 远端容器曾同时存在两个 `opencode --auto -s ses_fb37c…` writer；再次 force resume 可能产生第三个。
- bullet 远端数据库含 2026-09-02 18:26 的 `hi → 你好…`，但 Home trigger 数据库最后更新仍是 8 月 30 日。
- Hub `~/andy/sessions/opencode/tm_andy_ouc/` 为空，没有 OUC 当天 trigger snapshot；生成的 persist job 只 rsync 现有目录，不执行 OpenCode export。
- OUC 的 lease holder 名为 `tm_ouc`，历史 persist source 却名为 `tm_andy_ouc`，存在 Client identity 漂移，当前机制没有把它作为错误暴露。
- `ensure_local()` 在本地查到相同 session ID 后立即返回，不比较远端/本地 revision，因此即使未来 snapshot 上传，本地旧副本仍可能被当作已恢复。

## 第一性原理根因

系统混淆了四个不同事实：owner lease、runtime 存活、用户 attached、Agent semantic progress。cron heartbeat 只能证明 Client 后台还运行，不能证明用户活跃；pane 整屏 hash 也不能证明 Agent 有有效进展。

同时 resume 不是事务：所有权与 writer 安全检查没有在任何本地 pane 变更前完成，session identity 也缺少跨 TTY writer 单活约束。Binding 同步和 conversation snapshot 同步互相独立且没有 freshness 合同，“ID 相同”被错误当成“内容最新”。

## 影响

- 锁屏但未睡眠的笔记本可无限占有 tunnel。
- 空闲判断被稀疏历史污染，无法自然 handoff。
- 正常拒绝路径会破坏本机可观察现场。
- 强制接管可能形成同 session 多 writer，存在历史并发写入风险。
- 跨 Client resume 可以恢复正确 session ID，却展示该 ID 在本机数天前的旧内容。

## 规划去向

- v0.4.49：机制修复，见 `dev_plans/v0.4.48-v0.4.49/`。
- v0.4.50：Web/终端交互，见 `dev_plans/v0.4.49-v0.4.50/`。
- 架构决策：`docs/vault/20-details/decision-lease-activity-separation.md`。
