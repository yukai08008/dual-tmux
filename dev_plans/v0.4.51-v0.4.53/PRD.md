# v0.4.53 PRD — Codex / Claude Native Session Runtime

> 父版本：v0.4.51-final  
> 起草日期：2026-09-07  
> 类型：API 版（奇数）  
> 范围来源：BL-RUNTIME-002 / 用户确认推进

## 0. 一句话目标

让已冻结的 Codex 与 Claude 会话可以在两个 dual-tmux Client 之间经 Hub 安全接续，同时保持原 UUID、单 writer 和失败不释放 owner。

## 1. 范围与不变量

### 1.1 In-scope

- 按冻结 UUID 精确定位 Codex `~/.codex/sessions/**/*.jsonl` 与 Claude `~/.claude/projects/**/*.jsonl`。
- 单文件 payload + manifest，记录 hash、source Client/instance、generation、workdir、版本与更新时间。
- `~/sessions/native/<client>/<tool>/<uuid>` 与 `~/<user>/sessions/native/...` 双向同步。
- append-only 血缘判断、冲突拒绝、staging/validate/atomic commit、替换前备份。
- handoff 的 persist → park → ack → release 顺序；接管 generation fencing 与 writer 验证。
- `dt resume --plan` 输出 native snapshot 状态。

### 1.2 Out-of-scope

- v0.4.52 Ownership Web，待 v0.4.53 API 冻结后以 v0.4.54 Web 重新基线。
- 同步认证、全局配置、skills、索引或未冻结会话。
- 改写 Codex/Claude 的私有数据库或云端协议。

### 1.3 不变量

- v0.4.51 Lease v2 与 resume transaction 外部合同保持兼容。
- OpenCode persist 路径与恢复行为不回归。
- Hub 上传失败、manifest/hash 失败、历史分叉或 generation 改变均不得释放 owner 或启动第二 writer。
- 运行时数据不进入 Git；认证材料永不进入 snapshot。
- Web 不在本版修改；后续 Web e2e 必须覆盖新状态。

## 2. 顶层蓝图

```text
frozen UUID → exact JSONL → immutable revision + active manifest
            → ~/sessions/native/<source>/<tool>/<uuid>
            → Hub tenant tree → target staging/hash/ancestry/fence
            → atomic native store commit → exact UUID resume → writer=1
```

## 3. 快照协议

每个 active manifest 只允许一个 `.jsonl`，路径必须是 native store 下的安全相对路径。revision 等于 payload SHA-256；active 与 revision 内封存 manifest 必须一致。每个 source 仅保留最近两个 immutable revision，避免长会话逐分钟无限放大。

## 4. 冲突与事务

- 相同 bytes：幂等。
- local 是 snapshot 前缀：备份 local 后导入新 snapshot。
- snapshot 是 local 前缀：保留 local，不降级。
- 其他关系：`native_snapshot_conflict`，fail closed。
- 导入前后验证 JSONL UUID/hash；commit 前后二次读取 lease generation。

## 5. 风险登记表

| ID | 风险 | 严重度 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | 凭据或其他 session 泄漏 | high | allowlist 单 UUID JSONL；不遍历复制配置根 | Coder |
| R2 | 错 UUID 导入 | high | 路径、manifest、JSONL 三重校验 | Coder |
| R3 | 分叉历史被覆盖 | high | byte-prefix ancestry，否则拒绝 | Coder |
| R4 | 传输中断/半文件 | high | revision manifest + hash + staging | Coder |
| R5 | durable upload 前 park | high | daemon 顺序门禁和失败测试 | Tester |
| R6 | 混合 Client 版本 | medium | v0.4.51 owner 明确 reject；不绕过 | PM |

## 6. 签名

Agent-PM-0.4.53
