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

## 2. Session Ownership API

| ID | 用例 | → acceptance | 自动化 |
|----|------|--------------|--------|
| B-30 | spinner/footer/token 变化不改变 semantic fingerprint | activity semantics | tests/test_activity.py |
| B-31 | attached、runtime、lease、progress 四维状态互不推断 | activity semantics | tests/test_activity.py |
| B-32 | 少于 30 个样本返回 insufficient_evidence；时间窗口准确 | activity semantics | tests/test_activity.py |
| B-33 | 锁屏等价场景：cron heartbeat 可续租但不刷新 user/progress 时间 | activity semantics | tests/test_activity.py |
| B-40 | v1 lock 兼容读取并在续租时原子升级 v2 | lease v2 | tests/test_hub_sync.py |
| B-41 | foreign owner attached/working 时拒绝 handoff | lease v2 | tests/test_hub_sync.py |
| B-42 | idle owner ack：persist → park → release → claimant generation+1 | lease v2 | tests/test_hub_sync.py |
| B-43 | owner 不可达时普通 resume fail closed 且原因准确 | lease v2 | tests/test_hub_sync.py |
| B-50 | resume preflight claim 失败，本地 op/run 均保留 | transactional resume | tests/test_bullet_resume.py |
| B-51 | 远端已有相同 session writer 时返回 duplicate_writer，不启动新进程 | transactional resume | tests/test_agent_sessions.py |
| B-52 | force 未给 stale-writer disposition 时拒绝执行 | transactional resume | tests/test_bullet_resume.py |
| B-53 | commit 中途失败回滚 generation，binding/pane/Hub 不发布半状态 | transactional resume | tests/test_bullet_resume.py |
| B-60 | `dt resume --plan` 与 `dt ownership --json` 无副作用且 schema 稳定 | diagnostics | tests/test_control.py |
| E-30 | tm_ouc 锁屏、tm_andy_home 请求 handoff，owner 自动 park 后安全接管 | cross-client | 两台真实 Client |
| E-31 | 容器内预置相同 session writer，resume 不产生第二进程 | writer singleton | tom7r container |
| E-32 | v1/v2 Client 混合运行，锁与现有 tunnel binding 无损 | compatibility | 两版本真实 Client |
| B-70 | persist job 先 export 活跃 trigger，再原子发布 manifest+snapshot | snapshot export | tests/test_persist_sync.py |
| B-71 | persist identity 与 config.client 不一致/源目录为空时明确失败 | snapshot identity | tests/test_persist_sync.py |
| B-72 | 本地已有同 session ID 但 revision 较旧，仍执行备份导入并验证尾消息 | snapshot freshness | tests/test_persist_sync.py |
| B-73 | 本地 revision 更新时不反向降级 | snapshot freshness | tests/test_persist_sync.py |
| B-74 | 两个 source 的同 ID revision 分叉返回 snapshot_conflict | snapshot conflict | tests/test_persist_sync.py |
| B-75 | binding 已拉取但 snapshot 缺失时，resume plan 精确显示缺口 | diagnostics | tests/test_bullet_resume.py |
| B-76 | `dt pull` 同步 OpenCode/tmux persist；重叠 cron 等待，SSH/rsync 失败可见 | snapshot transport | tests/test_config_modes.py + tests/test_persist_sync.py |
| B-77 | stale TUI 在 import 前退出、import 后重新启动；live remote bullet 不被恢复覆盖 | transactional resume | tests/test_bullet_resume.py |
| E-40 | OUC 更新 trigger/bullet 并锁屏，Home 同步后两侧最后问答一致 | cross-client snapshot | 已通过（2026-09-05，Home 恢复 1052 条消息并验证“你好”结果） |

## 3. 合集闭环验证

| ID | 用例 | 说明 |
|----|------|------|
| E-01 | 全量 pytest 回归 | 全部 hotfix 合并后跑一次 |
| E-02 | 版本一致性 | CLI 与包 metadata 版本一致 |
| E-03 | session 单活 | 每个绑定 session ID 的 writer 数量 ≤1 |
| E-04 | 故障零副作用 | 所有 preflight/claim 拒绝路径不删除 pane、不改 binding |
| E-05 | conversation freshness | resume 后 trigger/bullet 的 revision 与 owner 发布 manifest 一致 |
