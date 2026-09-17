# E1 故障基线与后续机制入口

本文件记录 v0.4.51 characterization 阶段对偶发故障的分类。目标是先固定“当前可证明的安全行为”和“尚未解决的机制缺口”，避免后续重构把异常吞掉，或把历史风险误写成已经解决。

| 类别 | 当前基线 | 自动化入口 | 后续退出条件 |
|---|---|---|---|
| SSH timeout | health 返回 `transport=unreachable`，其余远端层为 `unknown`，不猜健康 | `test_fault_baseline.py` | Operation error 带 phase、timeout 与 retry safety |
| Hub lock held | 保留 holder、age、generation，不把冲突当成功 | `test_fault_baseline.py` | 所有写操作校验 generation；旧端自动 fencing |
| session missing | 只查记录的 session ID；缺失时明确失败，不选“最新 session” | `test_fault_baseline.py` | 三种 Agent adapter 均返回统一 `session_missing` |
| 部分写入 | `save()` 异常会向上传播，不会报告成功；但旧文件可能已损坏 | `test_fault_baseline.py` | tunnel/entry/health/memory 全部使用 fsync + atomic replace |
| 多端独热 | 当前是长 TTL owner + tick 延迟驱逐，尚非严格独热 | `exclusive-trigger-ownership.md` | 新端 ≤10 秒；旧端 detach/kill 回 shell；全部写操作 fencing |

## Recovery drop 安全前提

auto-recovery 的破坏性动作是一条链：`observe()` 达到失败阈值 → `recover_now()` 发起 resume → resume 以 `occupancy_steal` 抢占 occupancy → 原持有端在下一个 tick 由 `enforce_local()` 掉落本地 `op_*`/`run_*`（发出 `dt.drop`）。因此 recovery 间接拥有 drop 能力，2026-09-17 的 IS-260917185420 事故正是这条链在 trigger_agent 探针假阴性 + 用户活跃 turn 期间被点燃。该动作只允许在以下前提下发生（`recovery.py`）：

1. **warm-up 静默期**：`times.resume_at` 之后 `RECOVERY_WARMUP_SECONDS`（默认 60 秒）内，探针失败不计入连续失败——resume 后 Agent TUI 尚未就绪，`trigger_agent` 层（pane command 比对）会假阴性。
2. **turn 安静窗口**：发起 recovery 前检查 trigger 侧最近 `RECOVERY_TURN_WINDOW_SECONDS`（默认 300 秒）内是否有 turn 活动。活动证据来自两路独立信号，取较新者：本地 activity evidence（trigger 侧 working 态或语义指纹变化），以及经 hub 同步的各 client ticks 指纹变化（在本地 pane 已被掉落的机器上仍能看到持有方的 turn）。窗口期内跳过本次动作并发 `recovery.drop.suppressed` 事件，安静满窗口后重新评估。
3. 两个前提同时满足才可能触达 drop 链：连续失败达 `FAIL_THRESHOLD` 且无近期 turn 活动。活动证据缺失时 fail-open（不阻止 recovery），保证真实 trigger_agent 死亡的恢复时延只增加一个安静窗口，正常故障的 drop 语义不变。

## 当前明确不宣称的保证

- 普通 tunnel `store.save()` 目前直接 `write_text`，发生真实 short write 时不能保证保留旧版本。
- Hub tunnel lock 当前 TTL 为 300 秒，generation 尚未贯穿每次写操作。
- `send`、`freeze`、`reconnect` 等入口尚未全部通过 ownership policy。
- cron 驱逐存在最长约一分钟延迟，不能满足独热接管 SLA。

这些项目在 E5 的 Operation Runtime、短租约 fencing 和 atomic repository 中消除。在对应故障注入与真实双端 E2E 通过前，不得把它们从风险表删除。
