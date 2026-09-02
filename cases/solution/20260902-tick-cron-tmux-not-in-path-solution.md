# cron `dt tick` 每分钟崩溃：tmux 不在 cron PATH — 解决

> 日期：2026-09-02 | 分支：hotfix/v0.4.49-tick-cron-path

## 解决步骤

1. `tmux.py`：新增 `bin()`，解析顺序 `shutil.which` → `/opt/homebrew/bin/tmux` → `/usr/local/bin/tmux` → `/usr/bin/tmux`；全部 16 处 tmux 子进程调用与 statusbar 的 show/set-option 统一走 `bin()`。运行时修复，不依赖 crontab 可写。
2. `cron.py`：cron 行加 `PATH=/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/bin:/usr/bin:/bin` 前缀（对齐 dt-persist 脚本）；`install()` 支持替换旧格式行。
3. `hotfix.py install_tick`：行内容陈旧即重装（doctor/upgrade 每次 apply 都会纠偏）。
4. `cli.py main()`：未捕获异常现在写 `cmd.fail` 事件再抛出——cron 吞 stderr 时故障仍可见。

## 验证

- 220 tests 全过（新增 cron 行 PATH、旧行替换、tmux bin fallback、cmd.fail 事件、install_tick 纠偏共 7 条）。
- 用裸 cron 环境（无 homebrew PATH）从源码跑 `dt tick`：`hub sync` 成功、exit 0。

## 跟进事项

- 本机 crontab 写挂起恢复后，`dt doctor` 会自动把 tick 行替换为带 PATH 的新格式。
- 考虑给 `upgrade.py` 的 GitHub discovery 加 token 支持（今天 403 rate limit 导致 `dt upgrade` 静默走 fallback）。
