# v0.4.45 PRD — 三客户端原生会话生命周期

> 父版本：v0.4.44
> 起草日期：2026-08-31
> 类型：API 版（奇数）
> 范围来源：正式列装计划中遗留的 OpenCode、Codex、Claude 一致接续能力

## 0. 一句话目标

让 dual-tmux 能保守、可验证地冻结并恢复 OpenCode、Codex 与 Claude Code 的真实会话，而不是只记录客户端版本。

## 1. 范围与不变量

### 1.1 In-scope

- 统一 Agent session 数据结构与适配器行为：发现、启动、恢复、存在性检查。
- Codex：识别 UUID 会话，生成 `codex resume <UUID>`。
- Claude Code：识别 UUID 会话，生成 `claude --resume <UUID>`。
- 本地、SSH、Docker 三种 workpoint 的会话发现。
- freeze、resume、DST 判定和能力矩阵改用适配器合同。
- 对当前进程显式参数优先；后备关联必须同时满足 cwd 与进程启动时间。

### 1.2 Out-of-scope

- Codex/Claude 会话文件跨机器复制或格式迁移；客户端没有稳定公开 import 合同时不伪造。
- Codex/Claude 模型热切换；保持能力矩阵为不支持。
- Web 新交互；由 v0.4.46 双数 Web 版承接。
- 飞书扫码绑定；在 Web 控制面完整后独立推进。

### 1.3 不变量

- 不把同 cwd 的历史旧会话冒充当前进程。
- 不能证明 session 归属时 freeze 失败并保留诊断，不猜“最新”。
- OpenCode 已发布行为和入口权威规则不得回归。
- 远端发现只读取已登记 workpoint，不扫描或改写其他机器。
- 恢复不得创建新 session ID。
- 运行时数据不进入 Git。

## 2. 适配器合同

```text
pane process + canonical workpoint
  -> identify client
  -> explicit session id from argv
  -> otherwise session file with matching cwd and created/mtime >= process start
  -> frozen side metadata
  -> adapter.resume_command(session id)
```

三客户端共用上层 freeze/resume 流程，差异只留在 adapter 中。

## 3. 影响评估

- OpenCode：继续使用 SQLite 精确探测和 persist import，不改变格式。
- Codex/Claude：首次从 metadata-only 提升为 session-aware；旧记录没有 session ID 时仍明确不可恢复。
- Hub：同步 JSON 字段兼容，旧客户端会忽略新增字段。
- health/recovery：本版提供 adapter session probe 基础；自动跨机 import 仍只对 OpenCode 开启。

## 4. 风险登记

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | cwd 相同导致误绑历史会话 | 进程启动时间门槛 + 唯一候选，否则失败 | Coder |
| R2 | high | 客户端升级改变存储格式 | 解析首条 metadata，fixture 覆盖，失败不猜 | Coder |
| R3 | high | 恢复命令意外创建新会话 | 必须携带已冻结 UUID，并在测试中断言 | Tester |
| R4 | medium | 远端 shell quoting 错误 | 统一 shlex quote，SSH/Docker 单测 | Tester |

## 5. 签名

Agent-PM-v0.4.45
