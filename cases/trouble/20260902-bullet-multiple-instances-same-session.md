# bullet 同一 session 被多个 opencode 进程并发持有

> 日期：2026-09-02 | 隧道：dt-company_intro_v2 | 分支：hotfix/v0.4.49-bullet-fencing

## 背景

用户核对 dt-company_intro_v2 的 oc 会话数据一致性时发现异常。标识层三方一致（local/Hub/m7 都是 ses_fb37c74b / nimble-cactus），但 m7 容器内有 **4 个 opencode 进程同时持有同一 bullet session**（pts/5-8），host 上还有一条 9/2 遗留的孤儿 docker exec 跳点。

## 根因

- `ensure_agent` 只能看到本地 pane 的前台命令（`ssh` 跳点），看不到远端容器内是否已有同一 session 的 opencode 在跑；每次 `dt re` / resume / 重连都直接再发一条 `opencode --auto -s <id>`，孤儿实例不断累积。
- 反向缺陷：pane 已附着 live bullet TUI 时，resume 命令会被当作普通文本打进 TUI 输入框，变成 queued 消息。
- 多个实例在同一 session 的 sqlite 上互相阻塞 → 2026-09-02 上午的「消息一直 queue、turn 挂死 77 分钟」事故（见 20260902-bullet-stalled-messages-queued）。

## 影响

- bullet turn 互相阻塞、消息积压、上下文被多实例交叉污染风险。
- bullet 的 oc 会话数据只有容器内 opencode.db 一份，persist 树无 nimble-cactus 快照（无备份，见跟进项）。
