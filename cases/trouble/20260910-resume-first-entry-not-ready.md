# 2026-09-10：Resume 首次进入信息未就绪

## 现象

`dt resume dt-company_intro_v2` 第一次执行时显示恢复成功并 detached，但进入后的会话信息不完整或错误；约 30 秒后再次执行，第二次才显示正确内容。

典型输出包含：

```text
ok imported trigger persist JSON
ok trigger opencode --auto -s ses_fb3abe746ffeOlpNp1l60ZJTdN
ok bullet opencode --auto -s ses_f7a0e7ee7ffeY9A0szul4PZEVC
ok resumed DST dt-company_intro_v2
[detached]
```

## 证据与根因

Resume 已完成 JSON import，但 `_start_side` 发送 `opencode --auto -s` 后立即返回；没有等待目标进程、目标 session ID 和 OpenCode footer 同时出现。OpenCode 首次启动或导入大快照时仍在加载，用户看到的是一个尚未稳定的 TUI。第二次 resume 恰好复用了已加载的 session，所以看起来恢复正确。

这是一个恢复完成判定过早的时序问题，不能只用“命令已发送”或“tmux pane 已存在”作为成功证据。

## 影响

- 用户第一次进入可能误判为进入了错误会话。
- Trigger 的后续输入可能在初始化期间排队或被错误处理。
- 自动化流程可能在 session 尚未可读时开始轮询，制造重复 resume。

