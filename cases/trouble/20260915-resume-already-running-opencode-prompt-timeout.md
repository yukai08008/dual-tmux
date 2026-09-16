# 2026-09-15：Resume 已运行的 OpenCode 会话在权限/交互弹窗时报 12 秒超时

## 现象

用户执行 `dt resume dt-company-change` 时失败：

```text
· pulling Hub state
· checking trigger activity across terminals
· local session is authoritative (no remote sync needed)
skip remote bullet TUI is live; persist recovery not needed
skip op_company_change already running opencode
[err] op_company_change OpenCode session ses_f5cef638fffe8zmLTKf1SPNHwu did not become ready within 12s
```

## 现场证据与根因

1. **会话已在运行且匹配**：
   `op_company_change` 窗格内一直在运行 `opencode --model xs-cli-proxy/grok-4.6`，其实际持有的 live session ID 正好等于 tunnel 固化的 `ses_f5cef638fffe8zmLTKf1SPNHwu`。
2. **多余的就绪等待**：
   `_start_side` 在检测到该窗格已运行 opencode 时，正确跳过了重复启动（`sent = False`，打印 `skip ... already running opencode`）。但在后续逻辑中，仍无条件调用了 `_wait_opencode_ready(tmux_name, session_id)`。
3. **TUI 就绪判断规则过窄**：
   当时 OpenCode 恰好停留在外部目录访问权限确认对话框（`Permission required: Access external directory ... Allow once / Allow always / Reject`）。
   旧的 `_pane_shows_agent` 仅匹配 `RUNNING_RE`（`esc interrupt`）和 `FOOTER_RE`（`ctrl+p commands|OpenCode \d|tokens\b|\$[\d.]+ spent`），无法识别权限弹窗、提问交互或 Build 模型状态，误判为“TUI 尚未就绪”，最终在 12 秒后抛出 `SystemExit` 中断整个 resume。

## 影响

- 用户无法通过 `dt resume` 重新进入正在等待交互或权限确认的已有会话。
- 自动化或脚本 resume 遭遇偶发假死和超时报错。
