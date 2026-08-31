# dual-tmux 项目进展与待办

> 更新时间：2026-09-01
> 状态真相源：[pm-state.md](../pm-state.md)
> 当前 L1：`v0.4.48 (ACTIVE)`

## 1. 总体结论

dual-tmux 已从双 tmux/OpenCode 工具发展为支持 OpenCode、Codex、Claude，多 Client、Local/Hub、Web 与飞书入口的 Agent 控制平台。核心能力已可用，当前正式发布线为 `v0.4.46.post1`；仓库 `main` 的包版本为 `0.4.48`，但 v0.4.48 尚未完成发布门禁。

当前有四种不同状态，不能混为一谈：

| 范围 | 状态 | 事实 |
|---|---|---|
| `v0.4.46.post1` | RELEASED | 当前最新正式 tag |
| `main` / v0.4.48 主体 | MERGED | PR #12 已合并，159 tests 通过 |
| `feature/v0.4.48-feishu-scan-ws` | CODE_COMPLETE | 领先 main 5 个提交，174 tests 与 Browser/容器验收报告全绿 |
| v0.4.48 Release | BLOCKED | 仍需真实飞书 `/dt ls` mailbox 执行与回包 E2E |

## 2. 已完成能力

- DT/DST 双 tmux 隧道生命周期，以及冻结、恢复、换模型、分支和跨 Client 接续。
- OpenCode、Codex、Claude 三客户端的 session 发现、冻结与恢复合同。
- Local-first、Hub 同步、安全切换、锁、心跳和远端 session import。
- 分层健康状态机、保守恢复、退避与熔断。
- CLI/Web 共用 ControlService；Web 已覆盖 tunnel、Agent、Hub、Memory、Events 和 Doctor。
- 飞书安全绑定、mailbox、inbox/outbox、Web QR 与 Docker 部署模板。
- 候选分支已实现扫码自动创建 PersonalAgent、加密凭据、`dt daemon`、local/Hub 单活 WS 和 Hub credential ownership 修复。
- 真实故障以 `cases/trouble/` 与 `cases/solution/` 成对记录。

## 3. v0.4.48 发布门禁

候选分支已经完成真实扫码、PersonalAgent、operator 绑定以及 tom7r WS connected。剩余 P1 场景是完整命令闭环：

1. 用户在飞书发送 `/dt ls`。
2. tom7r WS 接收并写入目标 Client mailbox。
3. Client 通过 ControlService 执行命令。
4. outbox 把结果返回原 `chat_id`。
5. 验证无重复执行、无 secret 泄漏、Client 离线后仍可可靠消费。

通过后才能将 L2 从 `CODE_COMPLETE` 推进至 `MERGE_PENDING`，再合并、打 tag、创建 Release，并执行真实升级与数据无损验证。

## 4. 当前 L3 hotfix

`issue-web-trigger-result-not-collected (RESOLVED)`：用户提交给 trigger 后，terminal 已出现完整完成结果，但 Web 的 trigger 问答区没有生成回答。修复已进入 `MERGE_PENDING`。

第一性原理根因：一次用户提交是一条需要跨页面生命周期保存的 turn，而旧实现把 `waiting`、提交基线和完成归因只存在浏览器内存。刷新、恢复或切换生命周期后，系统仍能看见 pane，却已经不知道哪个问题在等待哪个新结果。

修复不变量：

- 每次提交持久化唯一 pending turn 和提交前 completion 基线。
- 只有该基线之后的新 completion 才能完成本轮。
- pending turn 在刷新、tab 关闭/重开和 Web 服务重启后可恢复。
- 同一 completion 最多消费一次；旧结果不得回答新问题。
- 长任务保持 running/attention，不因固定秒数直接失败。
- 完成结果必须落入 trigger 问答区，而不只是 terminal 或轮询日志。

验收结果：161 项测试通过；真实 `dt-portal` 的缺失结果已恢复为 `Grok 4.6 · 3m 0s` 回答；再次刷新后没有重复回答，pending 已清空，浏览器控制台无错误。

## 5. Web Backlog

### 5.1 Trigger → Bullet 中间交接

在 trigger 与 bullet 会话之间展示 trigger 实际改写并发送的任务、关键约束和交接状态，内容来自真实 pane/event，不由 Web 猜测。

### 5.2 Terminal 浏览体验

- 增高 trigger/bullet terminal。
- 每侧至少保留并展示最近 500 行。
- 仅当用户接近底部或主动发送后自动跟随。
- 用户向上回看时不得强制下滚，并提供“回到底部”。
- 切换 tab 后保持各自滚动位置。

### 5.3 任务生命周期自适应轮询

- 取消固定 1.5 秒任务判定轮询，和 `tmux-trigger` 的 15–30 秒周期一致。
- terminal 画面刷新与任务完成判定解耦。
- 无有效增量时退避，有新语义输出或用户操作时收紧；隐藏 tab 降频或暂停。
- 不再根据轮询次数或短暂静默推断完成。

参考诊断基线：P95 首包 20.4 秒；轮次聚合延迟 124440 秒；30823 个步骤等待聚合。聚合积压应独立呈现，不能靠提高前端轮询频率掩盖。

### 5.4 轮询时间线与核心文本提取

- 每条轮询展示采样时间、累计耗时、当前/下一次轮询间隔及简短进展摘要。
- 优先保留 trigger 面向用户的状态、trigger → bullet 交接和最终结果。
- 过滤 spinner、TUI chrome、命令回显、内部推理、系统指令残片和重复 footer。
- 仅动画变化不得产生新摘要；无法可靠提取时显示“暂无新的有效摘要”。
- OpenCode、Codex、Claude 分别建立真实 pane golden fixtures。

## 6. 推荐执行顺序

1. 完成并关闭当前 durable turn tracking hotfix。
2. 在 `feature/v0.4.48-feishu-scan-ws` 完成真实 `/dt ls` 回包 E2E。
3. 将 hotfix 与候选分支已有 progress/completion 状态机按不变量合并，避免叠加两套临时规则。
4. 跑 pytest、构建、Browser E2E、tom7r daemon 与运行时数据不入 Git检查。
5. 合并 v0.4.48 候选分支，更新验收报告和 `pm-state.md`。
6. 发布 v0.4.48，并执行真实升级及配置/tunnel 哈希无损验证。
7. 下一双数 Web 版本承接四组体验 backlog。
