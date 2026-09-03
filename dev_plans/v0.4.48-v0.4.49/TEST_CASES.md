# v0.4.49 TEST_CASES — Hotfix 合集

约定：
- B-xx = backend pytest
- E-xx = 真实环境验证（本机/tom7r）

## 0. 不变量回归（每个 hotfix merge 前必跑）

| ID | 范围 | 命令 |
|----|------|------|
| B-00 | 全量测试 | `.venv/bin/python -m pytest tests/ -q` |
| B-01 | 运行时数据不入 git | `git ls-files data/ \| wc -l` == 0 |

## 1. 各 Hotfix 测试用例

| ID | 用例 | → 对应 hotfix | 自动化 |
|----|------|--------------|--------|
| B-10 | hub-sync 状态读写/损坏回退 | tmux-sync-status | tests/test_statusbar.py |
| B-11 | chip 渲染 已同步/同步失败/local | tmux-sync-status | tests/test_statusbar.py |
| B-12 | 缺失会话跳过、用户自定义 status-right 保护 | tmux-sync-status | tests/test_statusbar.py |
| B-13 | 重复刷新不叠加、local 模式计数 | tmux-sync-status | tests/test_statusbar.py |
| E-10 | 源码 `dt tick` 后真实 tmux status-right 显示 ● 已同步 | tmux-sync-status | 手测（已通过 10:10） |
| B-20 | cron 行带 PATH；install 替换旧行不丢其他条目 | tick-cron-path | tests/test_cron.py |
| B-21 | tmux bin fallback（which 失败 → homebrew 绝对路径） | tick-cron-path | tests/test_cron.py |
| B-22 | 未捕获异常写 cmd.fail 事件 | tick-cron-path | tests/test_cron.py |
| B-23 | hotfix install_tick 对陈旧行纠偏 | tick-cron-path | tests/test_cron.py |
| E-20 | 裸 cron 环境（PATH=/usr/bin:/bin）源码 `dt tick` 成功 | tick-cron-path | 手测（已通过） |
| B-30 | remote_session_pids 解析/pattern bracket/失败与超时返回 None | bullet-fencing | tests/test_bullet_fencing.py |
| B-31 | fence kill 命令构造与空跑/失败策略 | bullet-fencing | tests/test_bullet_fencing.py |
| B-32 | pane TUI 检测；已附着跳过/检查失败拒启/清理后放行/本地跳过 | bullet-fencing | tests/test_bullet_fencing.py |
| E-30 | 真实隧道 remote_session_pids=[现役 pid]、TUI 检测 True | bullet-fencing | 手测（已通过） |
| B-40 | export_snapshot 写入/新鲜跳过/非本地跳过/失败清理/id 校验 | trigger-snapshot-export | tests/test_oc_export.py |
| B-41 | persist_tenant 读 name 文件、回退 dt client；oc_bin 兜底 | trigger-snapshot-export | tests/test_oc_export.py |
| E-40 | 真实 tick 自动导出各隧道 trigger 快照并经 persist cron 上 Hub | trigger-snapshot-export | 手测（已通过） |

## 2. 合集闭环验证

| ID | 用例 | 说明 |
|----|------|------|
| E-01 | 全量 pytest 回归 | 全部 hotfix 合并后跑一次 |
| E-02 | 版本一致性 | CLI 与包 metadata 版本一致 |
