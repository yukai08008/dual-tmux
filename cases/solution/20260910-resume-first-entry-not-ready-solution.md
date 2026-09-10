# 2026-09-10：Resume 首次进入信息未就绪解决方案

Resume 的完成条件现在包括：

- pane 命令为 `opencode`；
- 进程解析出的 session ID 等于目标 binding；
- pane 中出现 OpenCode footer；
- 上述条件在 12 秒内满足，否则恢复失败并进入现有回滚流程。

恢复顺序保持为：先拉取 Hub/persist/tick，完成 session import，再启动 TUI，等待 ready，最后返回 `resumed DST`。旧 Trigger TUI 与目标 ID 不一致时仍先导出备份，再退出旧进程。

回归测试：

- `test_resume_waits_for_trigger_session_ready`
- `test_control_resume_restores_input_ready_trigger_under_ten_seconds`
- `test_resume_trigger_backs_up_and_replaces_mismatched_live_session`

验证要求：运行完整 pytest、变更文件 Ruff 和 `git diff --check`。只有 ready 栅栏通过后，用户才能继续向 Trigger 发送任务。

