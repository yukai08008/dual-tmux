# bullet 会话无法接续：解决方案

## 修复

- freeze 成功捕获 bullet 后，用真实工作点收敛 `runtime`；本地工作点会清除陈旧 server/container/cmd。
- resume 对远端 bullet 先重放跳板，并要求 pane command 稳定保持远端状态；失败时停止，不发送 session 命令。
- resume 对本地 bullet 与 trigger 一样，从 `~/sessions/opencode/tm_*/` 查找并导入快照。
- 本地 bullet 启动时尽量使用已记录且实际存在的工作目录。

## 安全边界

- 不猜测历史 tunnel 的容器名。
- 跳板失败不会把远端 session ID 发送给本机 OpenCode。
- 不删除或覆盖 persist JSON。

## 验证

- 自动化覆盖本地 runtime 收敛、跳板失败停止、稳定后顺序启动、本地 bullet import。
- 对 `dt-msg2` 核对 session JSON 与历史 tmux pane，确认会话未丢失。
