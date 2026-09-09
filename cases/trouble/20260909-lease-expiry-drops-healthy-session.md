# 2026-09-09：Lease 过期误踢健康会话

## 背景

本机在 `dt-company_intro_v2` 中正常工作时，两次由 daemon 主动删除
`op_company_intro_v2` 与 `run_company_intro_v2`，前台 attach 直接退回 shell。
对应 generation 18、19；业务健康探针在退出前仍全部正常。

## 现场证据

- 09:01:35：`ownership.fence.park holder=none generation=18`
- 09:04:25：`ownership.self_fence.park reason=renewal_failed`
- generation 19 最后一次 Hub 续租为 09:04:19，Lease TTL 为 4 秒。
- 09:04:12 健康记录显示 trigger、bullet、SSH、容器和 session 全部健康。
- 每分钟 `dt tick` 会对活动隧道再次执行 `hub.claim`，同时 daemon 的
  ownership worker、lease worker 和 resume keepalive 都可能续写同一 Lease。

## 根因

Lease 到期被错误地等同于 generation 已被夺走。SSH/Hub 操作稍慢或多个本机
写入者争用时，精确相同的 owner/instance/generation 也无法在 deadline 后恢复；
watchdog 随即执行 destructive park。`dt tick` 的重复 claim 又扩大了竞争窗口。

## 不变量

- m7 仍是唯一 Ownership 权威。
- 明确出现 foreign owner、higher generation 或 fault-takeover reservation 时，
  旧端必须立即删除本地 tmux，让前台回到 shell。
- 短暂延迟本身不能删除健康会话。
- 新端故障接管仍须在 10 秒体验预算内完成。

## 跟进

- hotfix v0.4.55.post3：Lease 单写者、tick 只读、精确 generation 原子恢复。
- 增加真实 Hub 延迟、过期恢复、reservation 竞争及多 tick 周期验证。
