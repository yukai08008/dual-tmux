# E1 故障基线与后续机制入口

本文件记录 v0.4.51 characterization 阶段对偶发故障的分类。目标是先固定“当前可证明的安全行为”和“尚未解决的机制缺口”，避免后续重构把异常吞掉，或把历史风险误写成已经解决。

| 类别 | 当前基线 | 自动化入口 | 后续退出条件 |
|---|---|---|---|
| SSH timeout | health 返回 `transport=unreachable`，其余远端层为 `unknown`，不猜健康 | `test_fault_baseline.py` | Operation error 带 phase、timeout 与 retry safety |
| Hub lock held | 保留 holder、age、generation，不把冲突当成功 | `test_fault_baseline.py` | 所有写操作校验 generation；旧端自动 fencing |
| session missing | 只查记录的 session ID；缺失时明确失败，不选“最新 session” | `test_fault_baseline.py` | 三种 Agent adapter 均返回统一 `session_missing` |
| 部分写入 | `save()` 异常会向上传播，不会报告成功；但旧文件可能已损坏 | `test_fault_baseline.py` | tunnel/entry/health/memory 全部使用 fsync + atomic replace |
| 多端独热 | 当前是长 TTL owner + tick 延迟驱逐，尚非严格独热 | `exclusive-trigger-ownership.md` | 新端 ≤10 秒；旧端 detach/kill 回 shell；全部写操作 fencing |

## 当前明确不宣称的保证

- 普通 tunnel `store.save()` 目前直接 `write_text`，发生真实 short write 时不能保证保留旧版本。
- Hub tunnel lock 当前 TTL 为 300 秒，generation 尚未贯穿每次写操作。
- `send`、`freeze`、`reconnect` 等入口尚未全部通过 ownership policy。
- cron 驱逐存在最长约一分钟延迟，不能满足独热接管 SLA。

这些项目在 E5 的 Operation Runtime、短租约 fencing 和 atomic repository 中消除。在对应故障注入与真实双端 E2E 通过前，不得把它们从风险表删除。
