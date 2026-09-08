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
| O-04 | daemon 默认每 2 秒巡检 | A-1 | unit |
| O-05 | daemon 看见 foreign generation 即 park 本地 pane | A-2 | unit |
| O-06 | persist→commit→park→atomic transfer 顺序不变 | A-2/A-3 | unit |
| O-07 | stale generation finish/release 被拒且状态不变 | A-4 | fault/unit |

## 2. 真实终端 E2E

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| E-01 | 前台 attach 被 `detach-client` + `kill-session` 后进程返回 | A-2 | real tmux subprocess |
| E-02 | 双隔离 HOME 接管总耗时 <= 10 秒且只有新端 writer | A-1/A-3 | integration |
| E-03 | park 后 tunnel JSON、persist snapshot、memory hash 不变 | A-5 | integration |

## 3. 部署验证

| ID | 用例 | → 部署检查 |
|---|---|---|
| D-01 | 安装构建产物并启动 daemon | daemon worker 正常 |
| D-02 | 真实两端显式 resume | <=10 秒 + 旧端回 shell |
| D-03 | `dt --help` 与 CLI manifest 对比 | 无命令/参数阉割 |
