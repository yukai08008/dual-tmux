# v0.4.76 PRD — Trigger 受控运维 Bullet（S12）

> 父版本：main @ 1615642（v0.4.75 发布后）
> 起草日期：2026-09-15
> 类型：功能版
> 范围来源：用户需求「trigger 管理 bullet（断开、重建、换模型）基于事件体系改进」+ ROADMAP S12

## 0. 一句话目标

把 trigger 对 bullet 的运维从手工配方（raw send-keys / 手工 pgrep / 手敲 --auto）迁移到受控动词与事件反馈闭环：行动前有事实依据（`dt bullet`），动作可审计（`dt send` / `bullet.rebuild.*` 事件），恢复一步到位（`dt rebuild`）。

## 1. 范围与不变量

### 1.1 In-scope

- `dt bullet <dt> [--json]`：聚合 evidence/health/pane/写者/最近事件 + 事实 hint。
- `dt rebuild <dt> [--force]`：占用守卫 + working fail-closed + 路由修复 + 跳板重连 + 孤儿 fence + persist 导入 + 绑定会话围栏重启；span 事件。
- ControlService.rebuild + 操作目录 `bullet.rebuild`（CLI/Web/飞书同源）。
- 技能（dual-tmux / tmux-trigger）与 AGENTS.md 改写：派发走 `dt send`、行动前 `dt bullet --json`、恢复 `dt rebuild`、事件查询 `dt log --cat bullet`。
- CLI 契约增量（新增 bullet、rebuild 命令）。

### 1.2 Out-of-scope

- 事件跨机汇聚；普通模型切换的 TUI 自动化（维持 /models + freeze 两级）。
- Web/飞书 UI 上的 rebuild 按钮（API 已具备，UI 后续按需）。

### 1.3 不变量

- 现有 CLI 命令集不减少；新动词只增。
- rebuild fail-closed：working 无 --force 拒绝；远端探测失败拒绝盲启。
- 读路径（dt bullet / dt log）不发射事件。
- hint 只陈述事实，不判任务成败。
- 技能保留 dt 不可用时的 raw send-keys fallback。

## 2. 验收

- 全量 pytest 通过（新增 ~12 用例）。
- `dt bullet --json` 各 hint 规则有测试证明；`dt rebuild` working 拒绝/--force/fence→start 顺序有测试。
- 契约快照差异仅为新增两命令；操作目录增量 `bullet.rebuild`。
- 技能文本包含新动词（golden 断言）。

## 3. 风险登记表

| ID | 风险 | 缓解 | 严重度 |
|---|---|---|---|
| R1 | rebuild 误杀进行中回合 | working fail-closed + --force + bullet.fence 记录 pids | high |
| R2 | trigger 依赖新动词但 dt 未升级 | 技能保留 fallback 路径 | medium |
| R3 | dt bullet 远端写者探针慢 | 仅远程隧道调用一次只读探针，与 resume 预检同源 | low |

## 4. 签名

签名：Agent-PM-0.4.76
