# cron `dt tick` 每分钟崩溃：tmux 不在 cron PATH

> 日期：2026-09-02 | 分支：hotfix/v0.4.49-tick-cron-path

## 背景

用户发现隧道状态栏同步时间停留在 10:59 不前进，追问"中间没有同步吗"。

## 排查事实

- `events.jsonl`：历史上 **14292 次 `cmd.start cmd=tick`，只有 10 次 `cmd.ok`**，且无 `cmd.fail`——cron tick 从装上起几乎从未跑完。
- 用真实 cron 环境复现（`env -i HOME=$HOME`，PATH=/usr/bin:/bin）：`FileNotFoundError: 'tmux'`。tmux 在 `/opt/homebrew/bin/tmux`，cron 裸 PATH 找不到。
- 崩溃发生在 `hub.enforce_local()` 的 `has_session`（早于 hub.sync），traceback 被 crontab 的 `>/dev/null 2>&1` 吞掉；main() 只对非零 SystemExit 记 `cmd.fail`，未处理异常不留痕。
- 同步此前"看起来正常"是因为手动 `dt tick`/`dt push`/Web 操作在工作终端（PATH 正常）里跑。

## 根因

1. tmux 调用全部依赖 PATH 查找，cron/launchd 等裸环境直接崩。
2. 未捕获异常不写事件日志，故障长期不可见。
3. cron 行本身不带 PATH（对比：dt-persist 脚本自带 `export PATH=...`，所以它们一直正常）。

## 附带发现

本机 `crontab -` / `crontab <file>` 写操作当前挂起（读正常、daemon 正常），疑似 TCC 授权状态；cron 行更新因此只能等写恢复后由 doctor/hotfix 应用，运行时修复不依赖 cron 行变更。
