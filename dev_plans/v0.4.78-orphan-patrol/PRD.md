# v0.4.78 PRD — 孤儿进程治理（S13/S14 落地）

> 父版本：feat 分支基于 hotfix/v0.4.49-workpoint-alias-hops@189091f（已并入 v0.4.77 main 与本机 hotfix 修复）
> 起草日期：2026-09-16
> 类型：功能版
> 范围来源：ROADMAP S13/S14（用户在另一机器上立项）+ dt-cp-gate 三孤儿案例

## 0. 一句话目标

一条隧道在任何时刻只保留一对活跃 agent：启动前清场、断链时收尾、泄漏后例巡发现并可清理，全程事件可审计。

## 1. 范围

- **S13 不变量**：resume/rebuild 在 TUI 不在场时先全容器清场（`orphan.sweep`，fail-closed：探针失败拒绝盲启）；`dt drop`（用户主动）与 `dt rm --kill` 断链前按绑定会话围栏；daemon park 路径不受影响（远端 bullet 永不是占用清退对象）。
- **S14 巡检**：容器 run 点 opencode 扫描分类（合法写者=绑定会话最新者，否则最新者整体；其余 age≥600s 为孤儿）；`dt orphans [dt] [--json] [--clean]`；tick 低频巡检（每小时，env 可调）；`orphan.found`/`orphan.clean.ok/.fail` 事件；`auto_orphan_clean` 按隧道开关。
- 红线：合法写者永不清理；DST 冻结只扫不清；他机占用跳过；host run 点不扫描（无法归因）。
- 事件体系新增 `orphan` 分类（`--cat orphan` 可查）。
- 随带合入 hotfix 分支既有内容：v0.4.77 merge 冲突解决、reconnect(force=)、prompt/hostkey pane 模式、本地 runtime reconcile 保护、persist 快照回退、native_persist import 保护、upgrade 比较修复、test_parse_hops 环境隔离、S13/S14 立项文本、2 组案例与回归清单。

## 2. 不变量

- 现有 CLI 命令集不减少（新增 orphans 一个命令）。
- 清理动作永不触及合法写者；fail-closed 于探测失败。
- daemon park 不围栏远端 bullet（项目既有不变量）。

## 3. 验收

- 全量 pytest 通过（新增 17 个 orphan 用例）。
- 契约增量为 orphans 命令（其余零变更）。
- `dt orphans --json` 真实输出合法写者与孤儿清单。

## 4. 风险

| ID | 风险 | 缓解 | 严重度 |
|---|---|---|---|
| R1 | 误杀正在使用的交互 TUI | 合法写者=最新进程整体受保护；宽限 600s；自动清理默认关 | high→medium |
| R2 | 扫描脚本容器兼容性（busybox） | 脚本仅用 pgrep/procfs/awk，无 ps -eo 依赖；失败即 unavailable 不动作 | medium |
| R3 | host run 点误归因 | host 点完全不扫描/不清场 | eliminated |

## 5. 签名

签名：Agent-PM-0.4.78
