# v0.4.55 阶段验收报告

> 执行时间：2026-09-08 17:58 +08:00
> 状态：本地与真实 Hub 门禁通过，验收完成；经用户授权作为安全能力例外发布，进入 MERGE_PENDING

## 验收摘要

| 维度 | 数量 | 通过 | 失败 | 待执行 |
|---|---:|---:|---:|---:|
| Python 自动化 | 338 | 336 | 0 | 2（opt-in） |
| 独热聚焦测试 | 100 | 98 | 0 | 2（opt-in） |
| Ruff（变更文件） | 11 files | 11 | 0 | 0 |
| 构建 | 2 artifacts | 2 | 0 | 0 |
| 真实 SSH Hub | 3 | 3 | 0 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python 回归 | PASS | 默认门禁 `336 passed, 2 skipped`；2 个 opt-in Hub 用例另行通过 |
| B-02 | 静态检查 | PASS（变更范围） | 变更文件 Ruff 全绿；仓库全量仍有 24 个父版本既有问题，本版未机械扩修 |
| B-03 | 运行时数据未追踪 | PASS | `git ls-files data/` 为 0 |
| B-04 | 构建 | PASS | wheel + sdist，版本 0.4.55 |
| O-01 | cooperative handoff deadline | PASS | fake-clock + shared-state integration |
| O-02 | 删除固定 65 秒 sleep | PASS | 常量与路径均移除 |
| O-03 | 超时 fail-closed | PASS | 不调用 force claim |
| O-04 | 1 秒 watchdog | PASS | 完整 cache 仍为 15 秒，只有活跃 tunnel 进入快循环 |
| O-05 | foreign generation park | PASS | daemon 单元测试 |
| O-06 | persist→commit→park→atomic transfer | PASS | 顺序、deadline 与 cancel/commit 竞态回归测试 |
| O-07 | stale generation 无副作用 | PASS | finish/release generation fence |
| O-08 | committing 重入恢复 | PASS | 不重复 persist/probe，直接 park + finish；避免事务卡住 Lease TTL |
| O-09 | 滚动升级协议门 | PASS | v2 请求对旧 daemon 不可见；新 daemon 明确拒绝 legacy pending，均不 park |
| O-10 | SSH remote shell 参数安全 | PASS | handoff 的 tunnel/request/instance 等动态参数逐项 quoting；真实 Hub 回归通过 |
| O-11 | 新旧 Lease TTL | PASS | v2=4 秒；legacy sidecar/无 sidecar=300 秒；健康 legacy owner 首次 renew、过期 legacy fault takeover 均可迁移为 v2 |
| O-12 | renew fencing | PASS | client/instance/generation 三者匹配才续租；stale renew sidecar byte-for-byte 不变 |
| O-13 | owner self-fence | PASS | Hub 短暂不可达不立即 park；最近确认满 TTL 后 park；重启无证明时不自授新宽限期 |
| O-14 | 原子故障接管 | PASS | m7 flock 内 reservation → 服务端清场 → finish generation++，竞争端不可插队 |
| O-15 | 清场失败 fail-closed | PASS | cancel reservation；不 finish、不启动 writer |
| O-16 | 清场完成证明 | PASS | 同一远端动作 TERM/KILL 后再次 pgrep；writer 残留返回失败 |
| O-17 | persist keepalive | PASS | handoff 持久化期间独立续租，避免短 Lease 抢跑 |
| O-18 | Web/API mutation fence | PASS | `ControlService.send` 在 `tmux send-keys` 前走同一 Ownership gate；拒绝时零输入副作用 |
| O-19 | reservation 响应丢失 | PASS | begin 使用同一 request_id 重试；m7 返回 idempotent，不生成第二个 claimant 决策 |
| E-01 | 前台 attach 返回 shell | PASS | macOS 真实 tmux + PTY，返回后执行 shell marker |
| E-02 | 双隔离 HOME 独热接管 | PASS（本机集成） | 原子 transfer 前断言旧 op/run 已不存在；耗时 <10 秒 |
| E-03 | binding/persist/memory 不删除 | PASS | 接管前后 byte-for-byte 一致 |
| E-04 | 完整 resume 到 Trigger 输入就绪 | PASS | `ControlService.resume → restore → verify → send → INPUT_ACK` 全链路；本机重复 5 次通过，真实 Hub 为 5.930 秒 |
| E-05 | m7 真实故障接管到输入就绪 | PASS | 真实 tom7r：4 秒 Lease 过期、reservation、旧 writer 清场、generation++、新 tmux INPUT_ACK；连续 5 次 6.410–8.019 秒，后续整组复跑 7.116/6.811 秒 |
| D-01 | 隔离 daemon + 真实 SSH Hub | PASS | tom7r 随机 `dte2e_*` 租户，完成后精确清理 |
| D-02 | 双隔离 Client 显式 handoff | PASS | ownership 接管复跑 6.771 / 5.605 / 5.258 / 5.976 秒；完整 ControlService resume + 输入确认 5.930 秒；旧 attach 返回 shell |
| D-03 | 重复 Hub 原子协议与 fence | PASS | 5 次最大 2.138 秒；late commit 保留旧 owner；stale release 被拒 |
| D-04 | 故障接管与残留清理 | PASS | 随机 `dte2e_*` 隔离租户；每轮 finally 精确清理，tom7r 检查无残留 |

## 遗留问题

- 两个 Client 目前使用同机隔离 HOME，Hub 为真实 tom7r；不同物理 Client 的发布安装验证仍留到候选版部署，不影响协议门禁结论。
- 仓库全量 Ruff 的父版本问题不属于本版；本版 11 个变更代码/测试文件全绿。
- m7 能撤销 generation 并清理服务端 writer，但无法改变完全离线机器的物理屏幕；故障端恢复后必须先校验 generation 并 self-fence 回 shell，不能自动复活。
- 滚动升级期间 v0.4.54/v0.4.55 不互相接管；这是保证旧端不被超时后的旧逻辑误踢出的安全门，完成双端升级后解除。
