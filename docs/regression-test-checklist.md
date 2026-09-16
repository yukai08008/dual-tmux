# dual-tmux 回归测试清单与防护矩阵

> 维护原则：每次解决线上/真实运行故障后，必须在此清单登记回归项、守护不变量及对应的自动化测试用例。任何后续改动均需通过本清单用例，严禁功能回退。

---

## 1. 运行方式

运行全量回归套件：
```bash
uv run pytest -q
```

运行特定回归领域：
```bash
# 1. 恢复流程与 TUI 就绪状态回归
uv run pytest -q tests/test_bullet_resume.py tests/test_bullet_fencing.py

# 2. Workpoint、跳板与进程识别回归
uv run pytest -q tests/test_store.py tests/test_agentclient.py

# 3. 快照收敛与会话同步回归
uv run pytest -q tests/test_persist_sync.py tests/test_oc_export.py

# 4. CLI / Web 协议与生命周期基线回归
uv run pytest -q tests/test_cli_lifecycle_baseline.py tests/test_api_contract.py tests/test_cli_contract.py
```

---

## 2. 回归清单与测试矩阵

| 编号 | 场景 / 故障特征 | 核心守护不变量 | 自动化测试用例 | 案例索引 |
|---|---|---|---|---|
| **REG-01** | **已运行的 Trigger 在权限/交互弹窗时 resume 报 12s 超时** | 当 live session 与目标一致且进程已存活时免除等待；`_pane_shows_agent` 必须能识别权限弹窗、提问选择和 Build 状态 | `tests/test_bullet_resume.py::test_resume_skips_wait_when_trigger_already_running_bound_session`<br>`tests/test_bullet_resume.py::test_pane_shows_agent_detects_prompts_and_build_status` | [trouble/20260915](cases/trouble/20260915-resume-already-running-opencode-prompt-timeout.md) |
| **REG-02** | **首次 resume 会话未同步完成就进入 tmux** | 同步完成（Hub/persist/tick）是 attach tmux 的硬前置条件；未完成或失败严禁进入 tmux | `tests/test_bullet_resume.py::test_refresh_resume_inputs_prints_sync_stages_before_returning`<br>`tests/test_bullet_resume.py::test_cmd_resume_attaches_only_after_restore` | [trouble/20260910](cases/trouble/20260910-resume-first-entry-not-ready.md) |
| **REG-03** | **macOS `ps` 截断 command 导致 session ID 丢失** | 单独使用 `ps -ww ... -o command=` 读取完整参数，不得因宽度挤占丢失 `-s ses_xxx` | `tests/test_agentclient.py::test_agent_process_reads_untruncated_command_separately_from_elapsed` | [trouble/20260909](cases/trouble/20260909-macos-ps-truncates-opencode-session-id.md) |
| **REG-04** | **Shell alias 与 `cd/logout` 污染 resume chain** | Shell alias 展开仅限 SSH 命令；排除同机 `cd` 与 `logout/exit`，保留 SSH/docker 链；独立存储 `ssh_cmd` | `tests/test_store.py::test_workpoint_resolves_shell_alias_to_ssh`<br>`tests/test_store.py::test_workpoint_excludes_disconnect_commands_from_resume_chain`<br>`tests/test_store.py::test_apply_runtime_parses_target_from_ssh_cmd_not_mixed_chain` | [trouble/20260903](cases/trouble/20260903-workpoint-shell-alias-runtime-corruption.md) |
| **REG-05** | **多宿主/同容器多 OpenCode 进程时 freeze 误绑** | 按当前 SSH 进程启动时间过滤其他旧 pane；优先已绑定 session；从最新 message 读取实际模型 | `tests/test_agentclient.py::test_active_remote_orders_by_process_start_and_ignores_child_sessions` | [trouble/20260903](cases/trouble/20260903-workpoint-shell-alias-runtime-corruption.md) |
| **REG-06** | **同一 Session 启动多个 Bullet 实例（Fencing 穿透）** | 正确识别远端唯一进程，多实例必须执行 fencing；单存活实例绝不可重复启动 | `tests/test_bullet_fencing.py::test_fence_remote_bullet`<br>`tests/test_bullet_resume.py::test_start_remote_bullet_is_idempotent_with_one_exact_writer`<br>`tests/test_bullet_resume.py::test_start_remote_bullet_fences_duplicate_exact_writers` | [trouble/20260902](cases/trouble/20260902-bullet-multiple-instances-same-session.md) |
| **REG-07** | **本地 Trigger 会话未自动导出快照，跨端 resume 丢失数据** | 本地 tick 必须自动导出新鲜 trigger 快照供 Hub persist 同步 | `tests/test_oc_export.py` 全组测试 | [trouble/20260902](cases/trouble/20260902-trigger-persist-export-missing.md) |
| **REG-08** | **非祖先的分支快照直接导入导致数据降级或冲突** | snapshot 恢复必须验证 tail 连续性；非祖先分支必须 fail-closed 或合规 union，禁止静默覆盖 | `tests/test_persist_sync.py::test_ensure_local_rejects_non_ancestral_snapshot_without_verifiable_db`<br>`tests/test_persist_sync.py::test_ensure_local_does_not_downgrade_newer_local` | [trouble/20260909](cases/trouble/20260909-cross-client-snapshot-branch-blocks-resume.md) |
| **REG-09** | **Cron 裸 PATH 缺少 homebrew 导致 `dt tick` 崩溃** | cron 任务必须注入健全 PATH；tmux 丢失时具备 fallback 解析，错误记录事件 | `tests/test_cron.py::test_cron_command_has_path` | [trouble/20260902](cases/trouble/20260902-tick-cron-tmux-not-in-path.md) |
| **REG-10** | **旧端 Bullet 存活时跨端接管导致上下文污染** | 跨端接管前必须验证 writer probe 与 occupancy 租约状态，杜绝双写 | `tests/test_cli_lifecycle_baseline.py::test_hub_drop_releases_and_resume_claims_with_force` | [trouble/20260909](cases/trouble/20260909-stale-bullet-handoff-and-trigger-context-pollution.md) |
| **REG-11** | **未存已知主机 Key 导致批量 SSH 探针阻断自愈** | 静默探针 SSH 参数必须包含 `StrictHostKeyChecking=accept-new`；探针必须成功执行容器自愈路由，避免错误容器名阻塞恢复 | `tests/test_bullet_resume.py::test_ssh_argv_includes_accept_new_for_batch_mode`<br>`tests/test_bullet_resume.py::test_ensure_remote_session_returns_false_when_no_snapshot` | [trouble/20260915](cases/trouble/20260915-resume-remote-bullet-hostkey-and-snapshot-fallback.md) |
| **REG-12** | **Trigger 快照来源推选空租户导致死锁拒绝** | 推选来源无快照且本地无会话时，必须通过 `resolve_snapshot` 回退到包含有效快照的合法机器目录，禁止盲目报错 | `tests/test_persist_sync.py::test_ensure_local_tick_pick_falls_back_when_source_tenant_has_no_snapshot` | [trouble/20260915](cases/trouble/20260915-resume-remote-bullet-hostkey-and-snapshot-fallback.md) |

---

## 3. 回归测试守护规范

每当排查出新缺陷并在代码中完成修复时：
1. **必须在 `tests/` 编写对应复现与守护测试**（Red -> Green），不能仅凭肉眼或临时命令验证。
2. **在 `cases/trouble/` 和 `cases/solution/` 沉淀案例文档**。
3. **将新用例登记至本清单（REG-xx）**，写明核心守护不变量。
4. **提交代码前必须运行全量回归**：`uv run pytest -q` 确保既有清单全部保持 100% 通过。
