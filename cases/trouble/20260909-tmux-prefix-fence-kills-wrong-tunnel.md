# 2026-09-09：tmux 前缀匹配导致错误隧道被清理

## 现象

`dt resume dt-alex-serp` 成功后，`op_alex_serp` 与 `run_alex_serp` 会在数秒至
数十秒后同时消失，前台用户直接退回 shell；事件日志却只记录守护进程在清理
`dt-a` 的 `op_a` / `run_a`。

## 根因

tmux 的 session target 默认接受唯一前缀。`op_a` / `run_a` 不存在时，
`tmux has-session -t op_a` 和后续 `kill-session -t op_a` 会命中实际存在的
`op_alex_serp` / `run_alex_serp`。因此守护进程对过期旧隧道 `dt-a` 的正常 fencing
错误删除了正在使用的 `dt-alex-serp`。

同一缺陷还会使 pane 查询、send-keys、attach 和状态栏操作命中同名前缀的其他
隧道，并让远端 writer 探针把已退回本机 shell 的 pane 误报为健康。

## 复现证据

- daemon 开启：alex 两个 session 在 `dt-a` 清理周期内同时时消失。
- daemon 关闭：同一 trigger OpenCode 与 bullet SSH 连续稳定。
- 对 session target 使用 tmux 精确语法 `=name` 后，清理 `op_a` 不再命中
  `op_alex_serp`。

