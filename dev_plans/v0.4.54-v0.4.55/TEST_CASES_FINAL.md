# v0.4.55 阶段验收报告

> 执行时间：2026-09-08 15:30 +08:00
> 状态：代码 review 修正完成，本地与真实 Hub 门禁通过；版本保持 ACTIVE，未 merge/push/release

## 验收摘要

| 维度 | 数量 | 通过 | 失败 | 待执行 |
|---|---:|---:|---:|---:|
| Python 自动化 | 321 | 320 | 0 | 1（opt-in） |
| 独热聚焦测试 | 57 | 56 | 0 | 1（opt-in） |
| Ruff（变更文件） | 6 files | 6 | 0 | 0 |
| 构建 | 2 artifacts | 2 | 0 | 0 |
| 真实 SSH Hub | 3 | 3 | 0 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python 回归 | PASS | 默认门禁 `320 passed, 1 skipped`；opt-in Hub 用例另行通过 |
| B-02 | 静态检查 | PASS（变更范围） | 变更文件 Ruff 全绿；仓库全量仍有 24 个父版本既有问题，本版未机械扩修 |
| B-03 | 运行时数据未追踪 | PASS | `git ls-files data/` 为 0 |
| B-04 | 构建 | PASS | wheel + sdist，版本 0.4.55 |
| O-01 | cooperative handoff deadline | PASS | fake-clock + shared-state integration |
| O-02 | 删除固定 65 秒 sleep | PASS | 常量与路径均移除 |
| O-03 | 超时 fail-closed | PASS | 不调用 force claim |
| O-04 | 2 秒 watchdog | PASS | 完整 cache 仍为 15 秒，活跃 tunnel 优先 |
| O-05 | foreign generation park | PASS | daemon 单元测试 |
| O-06 | persist→commit→park→atomic transfer | PASS | 顺序、deadline 与 cancel/commit 竞态回归测试 |
| O-07 | stale generation 无副作用 | PASS | finish/release generation fence |
| O-08 | committing 重入恢复 | PASS | 不重复 persist/probe，直接 park + finish；避免事务卡住 Lease TTL |
| O-09 | 滚动升级协议门 | PASS | v2 请求对旧 daemon 不可见；新 daemon 明确拒绝 legacy pending，均不 park |
| O-10 | SSH remote shell 参数安全 | PASS | handoff 的 tunnel/request/instance 等动态参数逐项 quoting；真实 Hub 回归通过 |
| E-01 | 前台 attach 返回 shell | PASS | macOS 真实 tmux + PTY，返回后执行 shell marker |
| E-02 | 双隔离 HOME 独热接管 | PASS（本机集成） | 原子 transfer 前断言旧 op/run 已不存在；耗时 <10 秒 |
| E-03 | binding/persist/memory 不删除 | PASS | 接管前后 byte-for-byte 一致 |
| E-04 | 完整 resume 到 Trigger 输入就绪 | PASS | `ControlService.resume → restore → verify → send → INPUT_ACK` 全链路；本机重复 5 次通过，真实 Hub 为 5.930 秒 |
| D-01 | 隔离 daemon + 真实 SSH Hub | PASS | tom7r 随机 `dte2e_*` 租户，完成后精确清理 |
| D-02 | 双隔离 Client 显式 handoff | PASS | ownership 接管复跑 6.771 / 5.605 / 5.258 / 5.976 秒；完整 ControlService resume + 输入确认 5.930 秒；旧 attach 返回 shell |
| D-03 | 重复 Hub 原子协议与 fence | PASS | 5 次最大 2.138 秒；late commit 保留旧 owner；stale release 被拒 |

## 遗留问题

- 两个 Client 目前使用同机隔离 HOME，Hub 为真实 tom7r；不同物理 Client 的发布安装验证仍留到候选版部署，不影响协议门禁结论。
- 仓库全量 Ruff 有 24 个继承自父版本的问题；本版变更文件全绿。避免把无关格式化混入独热协议 diff。
- 物理故障域（旧机断电/隔离/daemon 死亡）无法同时保证“远程杀旧 tmux”和“10 秒安全接管”；协议选择 fail-closed。
- 滚动升级期间 v0.4.54/v0.4.55 不互相接管；这是保证旧端不被超时后的旧逻辑误踢出的安全门，完成双端升级后解除。
