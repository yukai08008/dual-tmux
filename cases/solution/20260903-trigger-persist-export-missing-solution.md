# 本机 trigger 会话无 persist 快照导出 + persist 租户名不一致 — 解决

> 日期：2026-09-03 | 分支：hotfix/v0.4.49-trigger-snapshot-export

## 修复原则

只有一份活动的隧道/会话，可在不同机器操作，且任何机器拿到的都是最新数据。

## 解决步骤

1. `oc.py`：
   - `export_snapshot(info, tenant)`：本机 sqlite 里存在的 session 才导出；按 `time_updated` 与快照文件 mtime 做新鲜度门控，只有内容变化才重新导出；write-then-rename 原子落盘；导出后校验 `info.id` 与 session 一致。
   - `oc_bin()`：opencode 二进制 which + 绝对路径兜底（与 tmux `bin()` 同一课——cron/launchd 裸 PATH）。
   - `persist_tenant()`：读取 `~/.config/session-persist/name`（persist 脚本实际同步的租户目录），缺省回退 dt client。**不做强制改名**：`.tmux.conf` 的 resurrect-dir 也引用该租户，贸然改名会破坏 tmux-resurrect；导出写入 name 文件指向的租户即可让数据进入既有同步管道。
2. `cli.py`：tick 每分钟对本 Client 持有的隧道导出 trigger（本地模式的 bullet 一并导出）；单隧道导出失败只记 `persist.export.fail` 事件，不拖垮整轮 tick。

## 验证

- 241 tests 全过（新增 9 条：写入/新鲜跳过/非本地跳过/失败清理/id 校验/租户回退/oc_bin 兜底）。
- 真实 tick：dt-msg、dt-msg2 等 trigger 快照自动导出到 `~/sessions/opencode/tm_andy_ouc/`；dt-company_intro_v2 的 misty-rocket 因新鲜被跳过（门控正确）；persist cron 推送后 Hub 内容一致。
- 事件日志出现 `persist.export`，失败会记 `persist.export.fail`。

## 不变量

- 只有持有 tunnel lock 的 Client 导出（单写者）。
- 快照对 resume 而言按 slug 全源搜索 + mtime 取最新（`persist_snapshot`），新导出天然胜出旧快照。
