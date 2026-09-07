# v0.4.51 PRD — Session Ownership API

> 父版本：v0.4.49
> 起草日期：2026-09-07
> 类型：API 版（奇数）
> 范围来源：BL-RUNTIME-001；锁屏误判、拒绝接管删除 pane、重复 session writer 事故

## 0. 一句话目标

建立一个可被 CLI、Web 和飞书共同消费的 Ownership 事实源与安全接管协议，使任何 Client 在改变 tmux/session 前都能证明“谁有写权、是否有人连接、Agent 是否推进、是否存在重复 writer、能否安全交接”。

## 1. 范围

### 1.1 In-scope

- Lease v2：holder、generation、renewed_at、instance_id、handoff、evidence；兼容旧 v1 锁并惰性迁移。
- 四维事实：lease、runtime、attached、progress；snapshot freshness 与 session writer 独立展示。
- 语义活动：剥离 spinner、footer、token、时间和 TUI chrome；以真实有效文本判断 progress。
- `dt ownership <name> [--json]` 稳定输出合同。
- `dt resume <name> --plan` 只读 preflight；普通 resume 在 preflight/claim 失败时零 pane/binding 副作用。
- owner daemon 处理 handoff：persist → park → release → claimant claim/verify。
- 相同 session ID writer 探测；重复或探测失败默认禁止启动。
- generation fencing：旧 generation 的自动恢复和写操作 fail closed。
- ControlService 暴露 ownership、resume plan、handoff 状态，供后续 Web/飞书复用。

### 1.2 Out-of-scope

- Ownership Web 面板、接管向导和时间线 UI，进入后续偶数 Web 版。
- 自动终止 working/stalled Agent；只上报并等待明确决策。
- 以操作系统锁屏状态作为活动依据。
- Codex/Claude 的 Client-local session store 跨机器复制；本版可探测三客户端 writer，但涉及本地 store 的跨 Client handoff 明确 fail closed，不能假装可恢复。

### 1.3 不变量

- v1 Client 继续读取和续租旧锁；v2 sidecar 不改变旧锁合同。
- lease heartbeat 不等于 attached 或 progress。
- `unknown`、`insufficient_evidence`、`probe_failed` 不得被解释为 idle。
- preflight 失败不得 kill/detach/reconnect pane，不得修改 binding。
- 同一 session ID 同时最多一个可写进程；无法证明时 fail closed。
- owner handoff 必须先持久化，后 park，最后释放。
- 所有权变化必须递增 generation；旧 generation 写操作被拒绝。
- 运行时 ownership/handoff/evidence 数据不进入 Git。

## 2. 模型

```text
OwnershipSnapshot
├── lease: free/owned/foreign/expired + holder/generation/instance
├── runtime: trigger/bullet = down/shell/transport/agent
├── attached: trigger/bullet = true/false/unknown
├── progress: trigger/bullet = idle/working/stalled/unknown
├── writers: trigger/bullet = count/pids/probe status
├── snapshot: source/revision/freshness/conflict
└── takeover: safe/action/reason
```

## 3. Lease v2 与兼容

- `locks/<tunnel>` 继续写 v1 文本，作为混合版本兼容锁。
- `ownership/<tunnel>.json` 在同一 `flock` 临界区内更新 v2 元数据。
- 缺少 sidecar 时从 v1 合成 snapshot；当前 owner 下一次 claim/renew 时创建 sidecar。
- sidecar 与 v1 holder/generation 不一致时，以 v1 为权威并丢弃陈旧扩展字段。

## 4. Handoff

```text
claimant plan
  → request_handoff(request_id)
  → owner daemon revalidates attached/progress/generation
  → persist snapshots and Hub state
  → park local panes
  → acknowledge + release
  → claimant acquires generation+1
  → resume exact sessions
  → verify writer count <= 1
```

owner attached、working、stalled、generation 漂移或 persist 失败时拒绝并记录明确原因。

## 5. Resume 事务

1. Plan：binding、runtime、snapshot、lease、attached、progress、writer 全部只读。
2. Acquire：free/owned 直接 claim；foreign idle/detached 请求 handoff；不确定状态停止。
3. Commit：恢复 transport 与 session。
4. Verify：session ID、writer 单活、generation 一致。
5. Rollback：新取得的 generation 在 commit/verify 失败时释放；binding 不发布半状态。

## 6. 风险

| ID | 风险 | 缓解 | 严重度 |
|---|---|---|---|
| R1 | 混合版本锁互相破坏 | 保留 v1 文件 + sidecar；真实 v1/v2 E2E | critical |
| R2 | spinner 被当成进展 | semantic fingerprint golden fixtures | high |
| R3 | handoff 误杀有效会话 | attached/working/stalled 全部拒绝自动 park | critical |
| R4 | preflight 产生副作用 | plan 纯函数化 + pane/binding hash 故障注入 | critical |
| R5 | writer 探测假阴性 | probe_failed=unknown，默认禁止启动 | critical |

## 7. 签名

`Agent-PM-0.4.51-code-complete`
