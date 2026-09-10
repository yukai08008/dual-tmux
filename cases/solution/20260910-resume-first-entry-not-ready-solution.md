# 2026-09-10：Resume 首次进入信息未就绪解决方案

第一次进入错误会话，不是简单的“同步可能慢”。`dt resume` 必须把同步完成当作进入 tmux 的硬前置条件。

完成条件现在包括：

- Hub tunnels/entries 的 rsync 进程已经成功退出；
- OpenCode / native persist rsync 进程已经成功退出；
- 终端展示的进度来自真实 subprocess 完成状态，而不是提前打印 complete；
- persist JSON 已导入；
- pane 命令为 `opencode`，进程 session ID 等于目标 binding，且 footer 可见；
- 上述 TUI ready 条件在超时内满足，否则恢复失败并进入现有回滚流程。

进度阶段按顺序输出：

- `pulling Hub state`
- `syncing OpenCode sessions`
- `syncing native sessions`
- `session sync complete`

`session sync complete` 只能在 rsync/persist 全部成功返回后出现。失败时不得继续使用旧 persist 数据静默恢复，也不得 `attach` / `ensure_session` / `reconnect`。

恢复顺序：先拉 Hub/persist/tick 并显示 rsync 进度，完成 session import，再启动 TUI，等待 ready，最后才 attach tmux。旧 Trigger TUI 与目标 ID 不一致时仍先导出备份，再退出旧进程。

回归测试：

- `test_refresh_resume_inputs_prints_sync_stages_before_returning`
- `test_refresh_resume_inputs_fails_closed_when_persist_sync_fails`
- `test_cmd_resume_attaches_only_after_restore`
- `test_cmd_resume_does_not_attach_when_sync_fails`
- `test_resume_waits_for_trigger_session_ready`
- `test_rsync_progress_streams_info_progress2`

验证要求：运行完整 pytest、变更文件 Ruff 和 `git diff --check`。只有同步完成且 ready 栅栏通过后，用户才能进入 Trigger。
