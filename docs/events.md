# 事件体系（Events）

> 权威实现：`src/dual_tmux/log.py`。本文回答三个问题：记录什么、在哪记录、怎么不被噪音淹没。

## 目标

帮助用户理解隧道与 Agent 生命周期，辅助系统运维。事件回答「这台机器上 dual-tmux 对每个隧道做过什么、Trigger/Bullet 当前处于什么状态」。

## 存储与边界

- 存储：`~/.dual-tmux/events.jsonl`，全局单文件、append-only JSONL，每行 `{ts, kind, pid, sev, cat, ...fields}`。
- **事件留在本机**，不进 hub push/pull（与 config/ops 一致；跨机汇聚留作后续版本，需先解决 append-only 多写者合并）。
- 保留上限：超过 8MB（约 2 万行 +20% slack）时原子重写保留最近 `MAX_EVENT_LINES=20000` 行。
- 并发：CLI / daemon / web 各进程独立 append，与旧行为一致，无锁。

## 事件分类（cat）与严重度（sev）

| cat | 含义 | 典型 kind |
|---|---|---|
| `system` | 隧道生命周期与系统运维 | `dt.new`、`hub.push`、`freeze.*`、`transport.reconnect` |
| `trigger` | 用户与 Trigger 的交互 | `trigger.send`、`trigger.turn.*`、`bullet.send`（命令 Bullet） |
| `bullet` | 远端 Bullet Agent 生命周期 | `bullet.start.*`、`bullet.run.*`、`bullet.fence` |

| sev | 含义 |
|---|---|
| `info` | 正常生命周期事实 |
| `warn` | 需要留意（stalled、探测失败、被占用拒绝） |
| `error` | 操作失败（freeze.fail、transport.reconnect.fail、启动失败） |

`KIND_META` 注册表给出 kind → (cat, sev, 中文标签)；未注册 kind 走 fallback：后缀 `.fail`→error、`.reject/.violation/.stalled/.unconfirmed`→warn；前缀 `trigger.`→trigger、`bullet.`→bullet，其余 system。**旧行（无 sev/cat 字段）在读取时按同规则派生**，`ControlService.events` 返回前统一补全。

## 事件清单（v0.4.75 口径）

### system — 隧道生命周期

| kind | 触发时机 | 采集点 | 关键字段 |
|---|---|---|---|
| `dt.new` / `dt.branch` / `dt.rm` | 隧道创建/分支/删除 | cli.py | name, op, run |
| `dt.enter` / `dt.work` / `dt.resume` / `dt.drop` | 用户动词 | cli.py / hub.py | name, generation |
| `hub.occupancy` | 占用声明（接管） | occupancy.py | holder, generation, **reason**（occupancy_steal/already_owned/require_active/resume） |
| `hub.occupancy.release` / `hub.release` | 释放占用 | occupancy.py / hub.py | generation |
| `occupancy.fence.park` | 他机占用，本机退出 | daemon.py | holder, generation |
| `hub.push/pull/sync(.ok/.fail)` | 用户级同步 | hub.py | host, root |
| `transport.reconnect(.ok/.fail)` | **建立管道**：SSH/docker 跳板重连 | cli.py（re/resume）、control.py | transport, landed |
| `transport.reconcile` | 管道路由检查/修复 | recovery.py | status, changed, container |
| `dt.model.ok / .fail` | **替换模型** | cli.py | model, sides, old, error |
| `freeze.*` | **持久化隧道**（固化） | cli.py / binding.py | session, rebuild, sides |
| `persist.export(.fail)` / `persist.native.sync(.fail)` | 快照导出/原生同步 | cli.py | — |
| `recovery.ok / .fail` | 健康自动恢复（本质是自动 resume，`auto_recover` 默认开） | recovery.py | failures |
| `recovery.rebuild.auto` | **stalled 边沿触发的自动重建**（v0.4.77；退避 5/15/30 分钟、每周期最多 3 次、working 清零、用尽转 attention） | recovery.py | attempt, next_retry_at |
| `recovery.rebuild.auto.fail` / `recovery.rebuild.hold` | 自动重建失败 / 次数用尽停止 | recovery.py | attempt, error / attempts |

### trigger — 交互层

| kind | 触发时机 | 采集点 | 关键字段 |
|---|---|---|---|
| `trigger.send` | 向 Trigger 注入 prompt（CLI/Web/飞书） | control.py | chars, preview（≤60 字符，**不记全文**） |
| `bullet.send` | **命令 Bullet**：向 Bullet 工作点注入指令 | control.py | chars, preview |
| `trigger.interrupt` / `bullet.interrupt` | 打断（C-c / Escape） | control.py | interrupt |
| `trigger.turn.start / .end` | Trigger 回合开始/结束（idle↔working 边沿） | activity.py | — |
| `trigger.stalled` | Trigger 疑似卡死（进入 stalled） | activity.py | — |
| `trigger.start.ok / .fail` | Trigger 启动成功/就绪超时 | cli.py | tool, error |

### bullet — Bullet 生命周期

| kind | 触发时机 | 采集点 | 关键字段 |
|---|---|---|---|
| `bullet.start.ok / .fail` | Bullet 启动 | cli.py | tool, error |
| `bullet.run.start / .end` | Bullet 开始/结束运行（边沿） | activity.py | — |
| `bullet.stalled` | Bullet 疑似卡死 | activity.py | — |
| `bullet.fence` | 清理远端孤儿实例 | recovery.py | pids, session |
| `bullet.rebuild.start / .ok / .fail` | `dt rebuild` 围栏化重建（span） | cli.py | ms, error |
| `bullet.probe.fail` | 探测失败（健康→降级转移时） | recovery.py | bullet_agent/session/bullet_pane 状态 |

## 噪音控制（不变量）

1. **周期性观察事件只做边沿触发**。`activity_evidence` 对照持久化的 ownership-evidence 上一状态，只有状态变化才发射；tick 与 daemon 共用该去重。
2. **探测失败每个降级周期只报一次**：`recovery.observe` 仅在 `consecutive_failures` 首次达到 `FAIL_THRESHOLD` 时发射 probe.fail，恢复后计数清零。
3. **自动重建有退避与上限**：stalled 触发的 `recovery.rebuild.auto` 间隔 5/15/30 分钟，每周期最多 3 次，观察到 working 才清零，用尽后转 attention 等人工（`recovery.rebuild.hold`）。
4. 单次命令类事件（send/freeze/model/resume）天然低频，直接发射。
5. 文件级兜底：2 万行上限防止长期运行淹没磁盘。

## 成败语义（保守口径）

只记录可观察事实：回合开始/结束、stalled、探测失败、启动失败、命令失败。**不做猜测性"成功"判定**——`turn.end` 表示回合结束，不代表任务成功；成功判断留给用户阅读 pane 内容。

## 消费面

| 面 | 入口 | 说明 |
|---|---|---|
| CLI | `dt log [-n N] [--kind 前缀] [--name DT] [--cat c] [--sev s]` | 中文标签 + 严重度着色 |
| CLI | `dt bullet <dt> [--json]` | Bullet 一站式诊断：活动状态/健康/管道/写者/最近事件 + hint |
| Web | `/events` 页 | 类别/严重度徽章、四维筛选、中文标签表格 |
| Web | 隧道详情 `Recent events` | 选定隧道后拉取最近 20 条 |
| API | `GET /api/events?limit&kind&t&cat&sev` | 旧格式行返回前补全 cat/sev（增量字段，非破坏） |

## 与相邻数据的关系

- `ticks.log` / `activity.log`：pane 指纹心跳，不是生命周期事件，继续独立。
- `skill-usage.jsonl`：技能使用审计，独立。
- `health/<name>.json`：健康状态机持久层；事件只报其转移，不复制其内容。
- 隧道 JSON 内 `created_at/freeze_at/resume_at` 等时间戳：粗粒度最后时间，事件是完整流水。
