# v0.4.55 TEST_CASES — Trigger 独热接管

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-01 | 全量 Python 回归 | `pytest tests/ -q` |
| B-02 | 静态检查 | `ruff check src tests` |
| B-03 | 运行时数据未追踪 | `git ls-files data/ \| wc -l` = 0 |
| B-04 | 构建 | `python -m build` |

## 1. 协议与时序

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| O-01 | cooperative handoff 在 deadline 内 atomic transfer | A-1 | fake clock |
| O-02 | 不再调用固定 65 秒 sleep | A-1 | fake clock |
| O-03 | 10 秒超时保持旧 owner，不 force claim | A-3 | fake clock |
| O-04 | daemon 默认每 1 秒巡检 | A-1 | unit |
| O-05 | daemon 看见 foreign generation 即 park 本地 pane | A-2 | unit |
| O-06 | persist→commit→park→atomic transfer 顺序不变 | A-2/A-3 | unit |
| O-07 | stale generation finish/release 被拒且状态不变 | A-4 | fault/unit |
| O-08 | daemon 在 `committing` 中重启后跳过重复 persist 并完成 transfer | A-1/A-3 | unit |
| O-09 | v0.4.54/v0.4.55 混跑在 park 前拒绝，不触发旧协议接管 | A-3 | compatibility |
| O-10 | handoff 动态参数经 SSH remote shell 前逐项 quoting | A-3/A-4 | security/unit |
| O-11 | Lease v2 使用 4 秒 TTL，legacy sidecar/无 sidecar 保持 300 秒 | A-6/A-7 | compatibility/unit |
| O-12 | renew 只接受同 client + instance + generation，stale renew 无副作用 | A-4/A-9 | unit + local shell |
| O-13 | daemon 每 1 秒 renew；Hub 不可达仅在现有 Lease 窗口内宽限，到期 park | A-7/A-9 | fake clock/unit |
| O-14 | fault takeover 先 reserve，再清场证明，最后原子 generation++ | A-7/A-8 | local Hub script/unit |
| O-15 | 清场失败 cancel reservation，不 claim、不启动新 writer | A-8 | fault/unit |
| O-16 | 服务端 writer TERM/KILL 后必须二次探测为空 | A-7/A-8 | remote-script/unit |
| O-17 | 健康 handoff persist 期间独立 keepalive，避免短 Lease 误接管 | A-1/A-3 | unit |
| O-18 | ControlService/Web send 在写 tmux 前验证 ownership，旧端 API 不可绕过 fence | A-3/A-9 | control/unit |
| O-19 | fault reservation 响应丢失时使用同一 request_id 幂等重试 | A-7/A-8 | fault/unit |

## 2. 真实终端 E2E

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| E-01 | 前台 attach 被 `detach-client` + `kill-session` 后进程返回 | A-2 | real tmux subprocess |
| E-02 | 双隔离 HOME 接管总耗时 <= 10 秒且 transfer 后只允许新 owner 恢复 | A-1/A-3 | integration |
| E-03 | park 后 tunnel JSON、persist snapshot、memory hash 不变 | A-5 | integration |
| E-04 | 完整 `ControlService.resume` 恢复 Trigger 并实际处理输入，总耗时 <= 10 秒 | A-1/A-2 | real Hub + tmux + input probe |
| E-05 | 真实 m7 Lease 过期 → reservation → 远端 writer 清场 → generation++ → 新 Trigger INPUT_ACK <= 10 秒 | A-7/A-8/A-9 | opt-in real SSH Hub + tmux |

## 3. 部署验证

| ID | 用例 | → 部署检查 |
|---|---|---|
| D-01 | 安装构建产物并启动 daemon | daemon worker 正常 |
| D-02 | 真实两端显式 resume | <=10 秒 + 旧端回 shell |
| D-03 | `dt --help` 与 CLI manifest 对比 | 无命令/参数阉割 |
| D-04 | 真实故障接管重复执行并检查 `dte2e_*` | 每次 <10 秒且无隔离租户/进程残留 |
