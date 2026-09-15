# v0.4.77 PRD — 自动恢复收敛（S12 补全）

> 父版本：main @ aa4d3de（v0.4.76 发布后）
> 起草日期：2026-09-16
> 类型：行为收敛版
> 范围来源：用户设计决策「用户一律 resume，中途故障是 dt 机制该解决的问题」+ ROADMAP S12 补全

## 0. 一句话目标

把用户心智模型收敛为"恢复一律 `dt resume`，中途故障 dt 自动处理"：`auto_recover` 默认开启、stalled 边沿自动触发围栏重建、`dt bullet` 直接给出恢复动词。

## 1. 范围

1. `auto_recover` 默认开：TunnelNode 模型默认 True；`from_legacy_tunnel` 缺 key 按 True；observe / tick 门 / Web 展示统一 `get("auto_recover", True)`；显式 `false` 不受影响。
2. stalled 边沿自动重建：`recovery.auto_rebuild_if_stalled` —— stalled 才动手、fail-closed 不变（working 由 rebuild 内部拒绝）、退避 5/15/30 分钟、每周期最多 3 次、观察到 working 清零计数、用尽转 attention 并发 `recovery.rebuild.hold`；tick 每分钟接线；探测死隧道路径不变（observe→recover_now→自动 resume）。
3. `dt bullet` 增加 `recovery` 字段：trigger 侧 runtime down → `dt resume`；trigger 活 + bullet stalled/多写者/管道断 → `dt rebuild`；健康 → 空。技能同步说明。

## 2. 不变量

- 显式 `auto_recover: false` 永远优先于默认值。
- 自动重建不得杀 working 回合（继承 rebuild fail-closed）；成功不清退避，只有观察到 working 才清零。
- 事件退避三件套（auto/auto.fail/hold）遵守边沿触发原则，不刷屏。
- 现有 CLI/契约零变更（本版无新动词、无新参数）。

## 3. 验收

- 全量 pytest 通过（新增 14 用例：默认开、退避、上限、attention、working 清零、recovery 建议规则）。
- 隧道 JSON 往返后 `auto_recover: true` 落盘（默认物化）。
- `dt bullet` 对 trigger-down 隧道给出 `dt resume` 建议。

## 4. 风险

| ID | 风险 | 缓解 | 严重度 |
|---|---|---|---|
| R1 | 默认开让未预期用户进入自动恢复 | 恢复动作本身经过占用门与 fail-closed；事件全程可审计；显式关闭仍可 | medium |
| R2 | stalled 误判导致误重建 | 判定基于语义指纹 10 分钟无进展（非 spinner）；rebuild 内部 working 二次拒绝 | medium |
| R3 | 自动重建风暴 | 退避 + 3 次上限 + attention 终态 + working 清零 | low |

## 5. 签名

签名：Agent-PM-0.4.77
