# v0.4.55 阶段验收报告

> 执行时间：2026-09-08 14:39 +08:00  
> 状态：本地代码与集成门禁通过；真实异机 Hub 验证待执行，版本保持 ACTIVE

## 验收摘要

| 维度 | 数量 | 通过 | 失败 | 待执行 |
|---|---:|---:|---:|---:|
| Python 自动化 | 314 | 314 | 0 | 0 |
| 独热聚焦测试 | 44 | 44 | 0 | 0 |
| Ruff（变更文件） | 6 files | 6 | 0 | 0 |
| 构建 | 2 artifacts | 2 | 0 | 0 |
| 真实异机部署 | 3 | 0 | 0 | 3 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python 回归 | PASS | `314 passed` |
| B-02 | 静态检查 | PASS（变更范围） | 变更文件 Ruff 全绿；仓库全量仍有 24 个父版本既有问题，本版未机械扩修 |
| B-03 | 运行时数据未追踪 | PASS | `git ls-files data/` 为 0 |
| B-04 | 构建 | PASS | wheel + sdist，版本 0.4.55 |
| O-01 | cooperative handoff deadline | PASS | fake-clock + shared-state integration |
| O-02 | 删除固定 65 秒 sleep | PASS | 常量与路径均移除 |
| O-03 | 超时 fail-closed | PASS | 不调用 force claim |
| O-04 | 2 秒 watchdog | PASS | 完整 cache 仍为 15 秒，活跃 tunnel 优先 |
| O-05 | foreign generation park | PASS | daemon 单元测试 |
| O-06 | persist→park→ack→release | PASS | 顺序回归测试 |
| O-07 | stale generation 无 release | PASS | ack 冲突后只 park，不 release |
| E-01 | 前台 attach 返回 shell | PASS | macOS 真实 tmux + PTY，返回后执行 shell marker |
| E-02 | 双隔离 HOME 独热接管 | PASS（本机集成） | 共享 lease 模型；claim 时断言旧 op/run 已不存在；耗时 <10 秒 |
| E-03 | binding/persist/memory 不删除 | PASS | 接管前后 byte-for-byte 一致 |
| D-01 | 异机安装与 daemon | PENDING | 不在本轮触碰用户真实运行环境 |
| D-02 | 真实两端显式 resume | PENDING | 需选择安全测试 tunnel/Client |
| D-03 | CLI manifest 对比 | PARTIAL PASS | `dt --help`、`dt --version` 通过；完整历史 manifest 待正向移植 |

## 遗留问题

- 真实异机 Hub 的网络时延、持久化耗时和 daemon 调度仍需部署验证，未通过前不封板、不发布。
- 仓库全量 Ruff 有 24 个继承自父版本的问题；本版变更文件全绿。避免把无关格式化混入独热协议 diff。
- 物理故障域（旧机断电/隔离/daemon 死亡）无法同时保证“远程杀旧 tmux”和“10 秒安全接管”；协议选择 fail-closed。
