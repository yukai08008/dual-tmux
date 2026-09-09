# 2026-09-09：macOS ps 截断 OpenCode Session ID

## 现象

`dt freeze dt-alex-serp` 能看到 trigger pane 的 `cmd=opencode`，却报告没有 trigger
OpenCode，要求先执行 `dt enter --oc`。

## 根因

本地 OpenCode 进程实际参数完整包含
`opencode --auto -s ses_f9a125dbdffelXmINuIVU0D7CT`。但 macOS 在一次 `ps` 调用中
同时输出 `command` 和 `etime` 时，会按列宽把 command 截成 `opencode --auto`。
dual-tmux 因而丢失显式 session ID；同时，基于目录的保守回退不会把启动前已经存在
的历史 session 猜成当前进程，最终正确地 fail-closed，但给出了错误的操作建议。

