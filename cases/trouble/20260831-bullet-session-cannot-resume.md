# bullet 会话无法接续

## 背景

本机 `dt-msg2` 执行 resume 后，`run_msg2` 显示 `Session not found: ses_fb76167aeffeNpvMwO5CKFL5x7`。用户预期 bullet 位于 tom7r 容器。

## 现场证据

- tunnel 的 `runtime.server=tom7r`，但 `runtime.container` 为空，directory 为 `/Users/andy`。
- resume 后 `run_msg2` 实际是本机 zsh；`opencode -s` 被发到本机。
- 2026-08-28 的来源 tmux 快照显示 `run_msg2` 的 foreground command 是本地 `opencode`，cwd `/Users/andy`，不是 ssh/docker。
- session 快照 `happy-circuit.json` 完整存在于中心服务器 `tm_andy_home` 来源树，本机也已拉取；会话内容未丢失。
- tom7r 登录宿主机和已检查的容器数据库中均没有该 session ID。

## 根因

1. SSH 退出后，bullet 在来源 Mac 本地启动；freeze 捕获了本地 session，却只增量更新 runtime，遗留了旧远端跳板，形成混合绑定。
2. resume 发送跳板命令后未等待连接稳定，立即发送 session resume 命令；跳板失败或尚未落稳时，命令会落到本机 shell。
3. 旧逻辑只为 trigger 导入本地 persist JSON，没有覆盖合法的本地 bullet。

## 影响

- 远端 runtime 已漂移为本地 bullet 的 tunnel 无法可靠接续。
- 失败不会删除 persist JSON，但表现为 session 丢失。
- 其他同类 tunnel 可能存在相同的历史混合记录。

## 跟进

- hotfix v0.4.41 增加 freeze 工作点收敛、跳板稳定门禁和本地 bullet import。
- `dt-msg2` 按证据恢复为本地 bullet；如未来指定容器，必须显式重建/配置工作点，不能猜测容器名。
