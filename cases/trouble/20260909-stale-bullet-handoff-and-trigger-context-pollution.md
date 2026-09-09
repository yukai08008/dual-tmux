# 2026-09-09：旧 Bullet 交接与 Trigger 上下文污染

## 用户可见现象

同一天内，`dt-company_intro_v2` 与 `dt-alex-serp` 出现了一组相互关联的故障：

- `dt resume` 被 `owner_evidence_stale` 拒绝，或连续返回
  `handoff timed out before the old Trigger was persisted and parked`。
- Resume 看似成功，但进入的不是另一台机器当天继续过的会话。
- `dt-company_intro_v2` 进入后充满重复内容；Trigger 上下文持续增长到
  `192.6K / 96%`，而 Bullet token 不变、界面只显示 spinner。
- `dt-alex-serp` 恢复到了错误的旧会话；另一次 pane 仍引用已经不存在的目录
  `/Users/andy_ouc/.dual-tmux/ops/op_alex_serp`，报 `FileSystem.access NotFound`。
- `dt upgrade` 发现 `0.4.55.post10`，但对应 GitHub Release wheel 尚不存在，返回
  HTTP 404。后续同 URL 重建 wheel 时，本地 `uv` 缓存又保留了旧构件。

## 现场证据

### Trigger 轮询递归复制

Trigger 连续执行逐渐扩大的 pane 抓取，例如：

```text
sleep 35 && tmux capture-pane ... -S -220/-300/...
```

每轮工具结果都重新带入更长的 Bullet 历史，也包含前一轮已经看过的内容。判断依据
主要是“还在转”，没有要求出现新 token、工具调用或语义输出，因此等待既不可靠又污染
Trigger 自身上下文。

### 交接导出旧绑定

OUC 侧已经替换了 live Bullet OpenCode，但隧道保存的仍是约 18:13-18:15 的旧
session ID。旧 handoff 直接按保存值导出，没有在 persist/park 前重新识别 live pane，
因此成功交接也可能恢复旧历史。

修复后确认的 live binding 为：

| 隧道 | Bullet session | slug | directory |
|---|---|---|---|
| `dt-company_intro_v2` | `ses_f7a0e7ee7ffeY9A0szul4PZEVC` | `curious-tiger` | `/root/intro_v2` |
| `dt-alex-serp` | `ses_f7a56b71effeyJ95aH9HMyuX6K` | `proud-squid` | `/workspace` |

### Remote OpenCode 选择错误

远端发现逻辑按 PID 倒序选择 OpenCode。旧 PID `3775456` 大于新 PID `352714`，
旧进程因此胜出。Linux PID 会回绕和复用，不是进程启动时间；并且子 agent session
也可能被误选。

### OpenCode 客户端内部死锁

同一 session 曾同时存活三份 `opencode --auto`，其中两份已运行两天。Escape、
Ctrl+C 和重复 `dt re` 看似退出或重开，旧容器进程实际没有完全结束。多个进程共享：

```text
/root/.local/share/opencode/snapshot/<project-id>/...
```

一份运行八天的 OpenCode 正在执行 snapshot `git gc` / `pack-objects` / `repack`，
当前 Bullet 同时执行 `diff-files` / `ls-files`。日志循环出现：

```text
cleanup failed: gc is already running
failed to list snapshot files
```

TUI 只显示 spinner，token 保持 `90.9K`，没有工具调用或显式错误。页脚虽已显示
Grok 4.6，旧 loop 仍可能在重试处于 16 小时 cooldown 的 `gpt-5.6-sol` stream。

## 根因图

1. Trigger 用无限制的重复历史抓取代替进展证据，制造重复上下文并延迟处置。
2. OpenCode 不互斥同 session 的 `--auto` 进程，snapshot git 又与对话 loop 同步耦合；
   dual-tmux 重复 resume 放大了这一客户端缺陷。
3. handoff 信任持久化 binding，没有先冻结并保存当前 live Trigger/Bullet。
4. remote discovery 把 PID 当时间，可能把旧进程或 child session 当作现役 Bullet。
5. Lease worker 与 handoff worker 独立；后者死亡时，前者仍可持续续租，形成“有 owner
   但不能交接”的假健康状态。
6. 发布流程先暴露版本、后上传 wheel，并允许同一版本 URL 重建，导致 404 与缓存旧包。

这不是 `intro_v2` 业务代码或 CLIProxy 导致，也不能仅归因于 Grok/网关假死。主因是
OpenCode 的多实例与 snapshot-git 行为缺少隔离和可见错误；dual-tmux 在 live binding、
进程排序、交接健康和轮询策略上的缺口共同扩大了影响。

## 风险

- 用户进入旧会话并继续开发，产生历史分叉或在错误目录修改代码。
- 同一 Bullet 被多个写进程并发持有，消息排队、重复或交叉污染。
- 交接宣称成功但导出的不是 live session，违反单一 owner 和无损恢复语义。
- Trigger 因轮询本身耗尽上下文，随后无法继续监督 Bullet。
- 发布版本不可安装，或显示新版本但执行的仍是缓存中的旧代码。

