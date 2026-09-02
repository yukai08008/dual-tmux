# 终端 tmux 状态栏不再显示同步状态 — 解决

> 日期：2026-09-02 | 分支：hotfix/v0.4.49-tmux-sync-status

## 根因

同步链路本身无故障（tick 正常、双端哈希一致）；缺失的是终端侧同步状态可视化能力。

## 解决步骤

1. 新增 `src/dual_tmux/statusbar.py`：
   - `write_state`/`read_state`：`~/.dual-tmux/hub-sync.json` 原子落盘最近一次 Hub 同步结果（ok/ts/detail）。
   - `apply`：为 dt 会话设置 session 级 `status-right`，渲染 `● dt:<name> 已同步 HH:MM`（绿）/ `同步失败`（红）/ `local`（黄），并保留原有全局 status-right 后缀。
   - 用户自定义过 status-right 的会话跳过（以 `@dt_status` marker 区分 dt 托管）。
2. `hub.sync_best_effort` / `push_best_effort` 在 ok/fail 时写状态文件。
3. `dt tick`（每分钟 cron）刷新所有已注册隧道的 op_*/run_* 状态栏；`dt push` / `dt pull` 后立即刷新。
4. 测试：`tests/test_statusbar.py` 8 条（状态读写、chip 渲染、缺失会话跳过、用户自定义保护、重复刷新不叠加、local 模式计数）。

## 关键点

- 只设 session 级选项，不动全局配置，不影响非 dt 会话。
- 状态文件 write-then-rename，与项目邮箱/状态落盘约定一致。
- tick 由 cron 每分钟执行，状态栏延迟 ≤1 分钟。

## 验证

- 208 tests 全过；ruff check/format 干净。
- 真实环境：源码跑 `dt tick` 后 `op_company_intro_v2` / `run_company_intro_v2` status-right 显示 `● dt:company_intro_v2 已同步 10:10`，原有默认后缀保留，非 dt 会话不受影响。

## 跟进事项

- 合并发布后通过 `dt upgrade` 让 cron tick 使用新版本，状态栏随每分钟 tick 持续刷新。
