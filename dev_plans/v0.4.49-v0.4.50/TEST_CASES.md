# v0.4.50 TEST_CASES — Ownership 与安全接管 Web 版

约定：
- B-xx = backend/contract pytest
- W-xx = Web/Browser 测试
- E-xx = 双 Client/Hub/容器真实 E2E

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量 backend | `pytest tests/ -v` |
| B-01 | 运行时数据不入 Git | `git ls-files data/ \| wc -l` == 0 |
| W-00 | Web 回归 | 项目现有 Web 测试 + Browser E2E |

## 1. Ownership 面板

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| B-10 | ownership snapshot schema 与 v0.4.49 合同一致 | 单一事实源 | tests/test_control.py |
| W-10 | held + agent + detached + idle 分四项展示 | 不误标 active | tests/test_web.py + Browser |
| W-11 | insufficient_evidence 显示实际样本数/窗口 | 不虚构 30 ticks | tests/test_web.py |
| W-12 | owner unreachable 与 lease expired 明确区分 | 可解释状态 | tests/test_web.py |
| W-13 | tab 切换/刷新后 snapshot 和选中 tunnel 保持 | durable UI | Browser |
| W-14 | 同 ID 旧 trigger 显示 stale revision，不显示“已恢复” | snapshot freshness | tests/test_web.py + Browser |

## 2. 安全接管向导

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| W-20 | resume plan 展示 holder、target session、writer 和预计动作 | preflight 可见 | tests/test_web.py |
| W-21 | owner attached/working 拒绝，页面不进入 commit | fail closed | tests/test_web.py |
| W-22 | handoff request/ack 的 persist→park→release→claim→verify 时间线 | 阶段可审计 | Browser |
| W-23 | 刷新期间重复 POST 使用同一 transaction ID | 幂等 | tests/test_web.py |
| W-24 | duplicate writer 禁止普通接管 | writer 单活 | tests/test_web.py |
| W-25 | force 要求输入 tunnel 名并选择 stale writer 处置 | 高风险确认 | Browser |
| W-26 | claim/preflight 失败前后本地 pane 集合不变 | 零副作用 | Browser + shell probe |

## 3. 跨端一致性与真实 E2E

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| E-10 | tm_ouc 锁屏但 cron heartbeat：Web 显示 online/detached/idle | 语义准确 | 两台 Client |
| E-11 | tm_ouc daemon ack handoff，tm_andy_home 安全恢复原 session | 完整闭环 | 两台 Client |
| E-12 | owner 正在 working 时接管被拒且任务不中断 | 安全拒绝 | 两台 Client |
| E-13 | 容器已有相同 session writer 时不产生第二/第三进程 | writer 单活 | tom7r |
| E-14 | Web/CLI/tmux chip 的 holder/generation/phase 一致 | 跨端收敛 | Browser + CLI |
| E-15 | owner 网络中断、lease expiry、claim 和 rollback | 故障恢复 | 网络故障注入 |
| E-16 | dt-portal durable pending turn 完整回归 | 历史不变量 | Browser |
| E-17 | OUC 最新 trigger 问答经 snapshot 收敛后在 Home Web 可见 | conversation continuity | 两台 Client + Browser |

## 4. 发布门禁

| ID | 用例 | 预期 |
|---|---|---|
| R-01 | `TEST_CASES_FINAL.md` 逐条有证据 | PASS |
| R-02 | 无 P0/P1 遗留 | PASS |
| R-03 | wheel/sdist 构建与隔离安装 | PASS |
| R-04 | 升级前后 config/tunnel/session binding 哈希一致 | PASS |
| R-05 | 打 `v0.4.50-final` 并验证真实 upgrade | PASS |
