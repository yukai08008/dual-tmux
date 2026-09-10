# 2026-09-09：Live Bullet 交接与有界监督方案

## 恢复顺序

现场处置必须先保全历史，再处理进程：

1. 导出正确 session JSON，并备份 OpenCode SQLite；不得删除 message/part 行。
2. 根据 pane、工作目录、顶层 session 和进程启动时间确认 live Trigger/Bullet。
3. 找出同 session 的全部 `opencode --auto` 及其 snapshot-git 子进程；TERM 后确认，
   必要时 KILL，直到该 session 为零进程。
4. 重新绑定正确 session，每侧只启动一份 OpenCode；确认目录、slug、session ID 和
   新输出一致后再恢复任务。
5. handoff 按 `freeze live sides -> save binding -> export/sync -> commit -> park ->
   atomic transfer` 执行。任何 live side 无法证明时 fail closed，不改变 ownership。

## 实现约束

- `freeze_sides()` 必须在 handoff export 前运行，刷新后的数据必须先写入 tunnel JSON。
- claimant 成功取得 handoff generation 后，必须从 Hub 重新读取 old owner 提交的单隧道
  binding，主动同步 OpenCode persist，再对刷新后的 session 做 preflight/import；不得继续
  使用 handoff 请求前载入的内存副本。
- 若 claimant 本地 Trigger pane 仍运行与刷新后 binding 不同的 session，先备份该旧
  session，再退出旧 TUI 并恢复目标 session；“pane 已经是 opencode”不能作为跳过依据。
- remote OpenCode 按 `/proc/<pid>/stat` field 22 启动 ticks 排序，不按 PID；自动发现只接收
  `parent_id IS NULL` 的顶层 session。
- 本地接管后，旧 owner 的 Trigger pane 和旧 Bullet 写进程必须退出，保持单一 owner。
- owner 持续续租但 handoff worker 无响应时，只能在同 generation 的 stale evidence、
  已超时请求、覆盖 Trigger 最后变化的快照以及可验证远端 fencing 同时成立时接管。
- OpenCode snapshot 冲突按 append-only message/part 图做 union；先备份，只补缺失 ID，
  immutable identity 冲突才拒绝。

## Trigger 监督规则

固定使用有界抓取：

```bash
tmux capture-pane -t <run_*> -p -S -60 | tail -n 60 | head -c 12000
```

不得扩大 `-S`、复制前轮输出或把 spinner 当作进展。正向进展至少需要一种新证据：
token/context 变化、新工具调用、新 assistant 语义输出或明确完成态。连续八轮无证据后，
先执行 OpenCode 排障；单一干净进程再达到一轮 quiet cap 才暂停任务并上报。

Bullet 开发模型顺序为：

```text
gpt-5.6-sol -> grok-4.6 -> gpt-5.6-terra -> gpt-5.5
```

模型 cooldown 时不保留旧 loop 自动重试。通过 `dt model <dt> --run <provider>/<id>`
切换，不在健康 turn 中途切换，也不把页脚模型当作实际 stream 已切换的充分证据。

## OpenCode 死客户端排障

1. 枚举同 session 的完整进程树，而不是只看 tmux pane 前台或 TUI。
2. 检查子进程是否包含 `git gc`、`pack-objects`、`repack`、`diff-files`、`ls-files`，
   并检查 `~/.local/share/opencode/snapshot/` 日志锁错误。
3. 备份 session 后终止该 session 的所有旧 OpenCode 和遗留 git；确认零 PID 后只启动
   一份 `opencode --auto -s <id>`，重置监督 baseline。
4. 若单一进程仍无进展，按模型顺序切换。上述排障与第二次 quiet cap 均失败后才暂停
   并报告 PID、snapshot-git 状态、页脚模型和实际 stream 模型。

## 发布约束

- 先创建 draft release，上传 wheel/sdist，验证资产非空且 wheel metadata/version marker
  一致，再公开 release。
- 不重用已经公开过的版本 URL。若事故恢复不得不重建同 URL，本地验证先执行
  `uv cache clean --force dual-tmux` 再强制安装，并比对远端与本地 wheel hash。

## 回归矩阵

| 失效模式 | 自动化回归 |
|---|---|
| 交接导出旧 binding | `test_handoff_persists_refreshed_live_bindings_before_export` |
| claimant 用请求前旧 binding 覆盖 owner 新值 | `test_resume_reloads_owner_committed_binding_after_handoff` |
| 单隧道权威读取被本地时间戳合并覆盖 | `test_read_tunnel_binding_uses_remote_value_without_local_merge` |
| 本地旧 Trigger TUI 阻止目标 binding 启动 | `test_resume_trigger_backs_up_and_replaces_mismatched_live_session` |
| live side 无法证明仍继续交接 | `test_handoff_live_freeze_failure_never_exports_or_parks` |
| persist/commit/park 顺序错误 | `test_handoff_orders_persist_park_ack_release` |
| persist 期间 Lease 过期 | `test_handoff_persist_keeps_short_lease_alive` |
| 远端按 PID 误选旧进程或 child | `test_active_remote_orders_by_process_start_and_ignores_child_sessions` |
| 同 session 多实例 | `tests/test_bullet_fencing.py` 的 remote PID/fencing 用例 |
| Trigger 无限扩大抓取 | `tests/test_store.py` 的 bounded polling skill 断言 |
| 跨 Client 合法历史分支被拒绝 | `tests/test_oc_export.py` 的 snapshot union/identity 用例 |
| 源码版本标记与构件元数据不一致 | `test_source_version_markers_match`、`test_cli_version_matches_package_metadata` |
| release tag 与 wheel 不一致 | `test_discover_latest_rejects_tag_asset_version_mismatch` |

## 验证基线

`v0.4.55.post12` 发布时全量结果为 `380 passed, 2 skipped`。本案例新增回归后应继续执行
完整 `pytest`、变更文件 Ruff 和 `git diff --check`；任一矩阵用例失败均不得发布。
