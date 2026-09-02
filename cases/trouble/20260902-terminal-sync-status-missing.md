# 终端 tmux 状态栏不再显示同步状态

> 日期：2026-09-02 | 隧道：dt-company_intro_v2（全部 op_*/run_*）

## 背景

用户在终端操作 trigger/bullet 时，以前下方有同步状态提示，现在消失，怀疑 Hub 同步中断。

## 排查事实

- `dt tick` 正常：`hub sync tom7r:~/andy/dual-tmux`，5 live DT。
- 本地与 Hub 的 `dt-company_intro_v2.json` SHA256 完全一致 → 同步链路健康。
- 全量 git 历史搜索 `status-right` / `set-option` / `select-pane -T`：dual-tmux 从未在 tmux 状态栏渲染同步状态；用户记忆中的提示很可能来自 dt web 隧道页底部的同步 chip（web.py `syncbox`，仍在工作）。
- 结论：不是同步故障，是终端侧缺少同步状态可视化（能力缺口）。

## 影响

用户在终端无法直观判断当前隧道同步是否健康，只能跑 `dt tick` / `dt doctor` 手动确认。
