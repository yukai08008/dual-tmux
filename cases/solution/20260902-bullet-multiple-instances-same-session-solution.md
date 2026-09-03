# bullet 同一 session 被多个 opencode 进程并发持有 — 解决

> 日期：2026-09-02 | 分支：hotfix/v0.4.49-bullet-fencing

## 现场处置

- kill m7 容器内 3 个孤儿 opencode（pts/5,6,7），保留 09:21 现役实例（pid 3145566）；kill host 上 9/2 孤儿 docker exec 跳点。bullet pane 恢复正常。

## 代码修复（bullet 单实例 fencing）

1. `recovery.py` 新增：
   - `remote_session_pids(data)`：经 ssh + docker exec 用 `[s]es_xxx` bracket 模式 pgrep 远端持有该 session 的进程；ssh/容器不可达返回 None（未知）。
   - `fence_remote_bullet(data)`：TERM + 1s 后 KILL 兜底清理远端实例，返回被清理 pid 列表。
2. `cli.py` 新增：
   - `_pane_shows_agent`：pane 尾部含 TUI footer（`ctrl+p commands` / `esc interrupt` 等）即视为已附着 live Agent。
   - `_fence_remote_bullet`：bullet 侧 resume/start 前调用——pane 已附着 TUI → 跳过（同时修掉 resume 命令被打进 TUI 输入框变 queue 的缺陷）；检查失败 → 拒绝盲启；有孤儿 → 清理后再启动。
   - `_apply_model_legacy` 的 bullet 换模型路径同样先 fence（换模型本就是重启）。

## 验证

- 232 tests 全过（新增 12 条：pgrep 解析/pattern bracket、ssh 失败与超时返回 None、kill 命令构造、TUI 检测、跳过/拒绝/放行/本地跳过策略）。
- 真实只读验证：`remote_session_pids(dt-company_intro_v2)` = `[3145566]`（清理后唯一实例）；`_pane_shows_agent(run_company_intro_v2)` = True。

## 跟进事项

- bullet 远端 opencode.db 无 persist 快照备份；评估把远端 bullet 会话快照纳入 persist/Hub 同步。
