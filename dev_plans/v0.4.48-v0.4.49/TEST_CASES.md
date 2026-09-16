# v0.4.49 TEST_CASES — 运行时修复与 Session 快照收敛

## 0. 发布门禁

| ID | 用例 | 验证 |
|---|---|---|
| B-00 | 全量测试 | `uv run pytest -q` |
| B-01 | focused Ruff | `ruff check --select E9,F63,F7,F82` changed Python files |
| B-02 | 编译 | `python -m compileall -q src` |
| B-03 | 构建 | `uv build` |
| B-04 | 版本一致性 | wheel metadata、`dual_tmux.__version__`、CLI 均为 0.4.49 |
| B-05 | 运行时数据不入 Git | `git ls-files data/` 为空 |

## 1. Snapshot convergence

| ID | 用例 | 自动化 |
|---|---|---|
| S-01 | payload revision 优先于文件 mtime | `tests/test_persist_sync.py` |
| S-02 | 同 revision 不同 tail 返回 `snapshot_conflict` | `tests/test_persist_sync.py` |
| S-03 | 同 ID 本地旧副本备份、导入并验证尾消息 | `tests/test_persist_sync.py` |
| S-04 | 本地 revision 较新时禁止降级 | `tests/test_persist_sync.py` |
| S-05 | 非祖先的新 snapshot fail closed | `tests/test_persist_sync.py` |
| S-06 | `dt pull` 同步 OpenCode/tmux persist | `tests/test_config_modes.py` |
| S-07 | persist 重叠等待，SSH/rsync 失败可见 | `tests/test_persist_sync.py` |
| E-01 | OUC→Home 恢复 1052 条消息并验证尾问答 | 2026-09-05 已通过 |

## 2. Trigger workdir
## 1.1 Earlier Hotfix Regression Cases

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
| B-50 | shell alias 仅展开 SSH 命令，拒绝非法 token/非 SSH alias | workpoint-alias-hops | tests/test_store.py |
| B-51 | replay chain 排除同机 `cd` 与 `logout/exit`，保留 SSH 与 docker exec | workpoint-alias-hops | tests/test_store.py |
| B-52 | runtime 从独立 `ssh_cmd` 解析目标；兼容单条直接 SSH resume 命令 | workpoint-alias-hops | tests/test_store.py |
| B-53 | pane 只观测宿主机时保留已知 container 与远端 directory | workpoint-alias-hops | tests/test_store.py |
| E-50 | dt-alex-serp freeze 绑定 container 内最新活动会话 calm-garden | workpoint-alias-hops | 实测（已通过） |
| B-54 | remote freeze 按当前 SSH 连接年龄过滤其他 pane，优先已绑定 session，并从最新消息读取实际 model | workpoint-alias-hops | tests/test_agentclient.py |
| E-51 | dt-company_intro_v2 freeze 从陈旧 quiet-orchid 修正为当前 pane nimble-cactus，保留 GPT 5.6 live model | workpoint-alias-hops | 实测（已通过） |
| B-55 | 已在运行目标会话时 resume 免除重复等待；TUI 识别支持权限弹窗与交互状态 | resume-already-running-opencode | tests/test_bullet_resume.py |
| E-52 | dt-company-change 在权限确认弹窗时 resume 秒级完成并正常 attach | resume-already-running-opencode | 实测（已通过） |
| B-56 | 批量 SSH 探针带 accept-new 保证容器自愈生效；trigger 快照空租户自动回退 | resume-remote-bullet-hostkey-fallback | tests/test_bullet_resume.py, tests/test_persist_sync.py |
| E-53 | dt-cp-gate 宿主容器自动自愈为 cp_gateway_24629，trigger 快照成功恢复 | resume-remote-bullet-hostkey-fallback | 实测（已通过） |

| ID | 用例 | 自动化 |
|---|---|---|
| W-01 | 新 pane 以请求的 ops cwd 创建 | `tests/test_enter_workdir.py` |
| W-02 | 错误 cwd 的空闲 shell被安全纠正 | `tests/test_enter_workdir.py` |
| W-03 | 前台 Agent/其他程序保持不变 | `tests/test_enter_workdir.py` |
| W-04 | enter 在 discover/attach 前建立 workdir | `tests/test_enter_workdir.py` |
| E-02 | `dt-cp-gate` pane/op_point 均为专属 ops 目录 | 2026-09-06 已通过 |

## 3. Freeze runtime authority

| ID | 用例 | 自动化 |
|---|---|---|
| F-01 | live SSH 覆盖 docker-only scrollback | `tests/test_store.py` |
| F-02 | 仅识别交互式远端 docker exec | `tests/test_store.py` |
| F-03 | 探测失败不提交候选 runtime | `tests/test_agentclient.py` |
| F-04 | 验证成功后提交 live runtime/session | `tests/test_agentclient.py` |
| F-05 | partial freeze 保存成功 side、返回失败并记录事件 | `tests/test_agentclient.py` |
| E-03 | `dt-cp-gate` live SSH+container freeze 到真实 session | 2026-09-06 已通过 |

## 4. 发布后验证

| ID | 用例 | 预期 |
|---|---|---|
| D-01 | GitHub Release 资产 | wheel + sdist 可下载且版本为 0.4.49 |
| D-02 | 本机 `dt upgrade` | 从 0.4.48.post6 升级到 0.4.49 |
| D-03 | 升级无损 | config 与全部 tunnel SHA-256 不变 |
| D-04 | 服务状态 | daemon/mailbox worker 正常，`dt tick` 成功 |
