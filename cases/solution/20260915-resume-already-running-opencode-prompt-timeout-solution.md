# 2026-09-15：Resume 已运行的 OpenCode 会话在权限/交互弹窗时报 12 秒超时解决方案

## 修复机制

1. **已运行且匹配的会话免除就绪等待**：
   在 `src/dual_tmux/cli.py` 的 `_start_side` 中，当进程已存在且无需重启（`not sent`），且当前运行的 live session ID 与目标固化 session ID 一致时，直接返回，不再执行 `_wait_opencode_ready`。
2. **扩充 Agent TUI 状态识别范围**：
   在 `src/dual_tmux/paneparse.py` 中新增 `PROMPT_RE`，覆盖 `Permission required`、`Allow once`、`Allow always`、`ctrl+f fullscreen`、`Ask anything`、`⇆ select`、`enter confirm` 等交互弹窗特征。
3. **全面升级 `_pane_shows_agent`**：
   将 `STATUS_RE`（`Build · ...`）、`BUILD_RE` 以及 `PROMPT_RE` 全部纳入 `_pane_shows_agent` 判定，避免新启动或已处于交互态的 OpenCode 被误判为未渲染。

## 不变量与守护规则

- 若窗格中的 live session 与目标 session ID 不一致，依然必须备份旧 session 并安全退出旧进程后重建。
- 若确实发起了新的启动命令（`sent is True`），依然必须等待目标 session ID 出现并满足 TUI 呈现。
- 若窗格中已是目标 session，resume 绝不可因前台正等待用户输入权限/确认而失败。

## 回归自动化测试

- `tests/test_bullet_resume.py::test_resume_skips_wait_when_trigger_already_running_bound_session`
- `tests/test_bullet_resume.py::test_pane_shows_agent_detects_prompts_and_build_status`
- `tests/test_bullet_fencing.py::test_pane_shows_agent_detects_tui`
