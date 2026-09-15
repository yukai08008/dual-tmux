# v0.4.76 TEST CASES — Trigger 受控运维 Bullet

## 0. 不变量回归

| ID | 用例 | 自动化 |
|---|---|---|
| B-01 | 全量 pytest 通过 | pytest |
| B-02 | CLI 契约差异仅新增 bullet/rebuild 两命令 | test_cli_contract |
| B-03 | 操作目录增量 bullet.rebuild | test_control |
| B-04 | 命令集保护：现有命令不减少 | test_cli_contract |

## 1. dt bullet

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| T-01 | 聚合 evidence 状态 + no_progress 秒数 | snapshot 字段 | pytest |
| T-02 | stalled → hint stalled_do_not_queue | hint 规则 | pytest |
| T-03 | 多写者 → multiple_writers hint | hint 规则 | pytest |
| T-04 | 远端管道非 ssh/docker 且非 working → transport_down | hint 规则 | pytest |
| T-05 | working → working_wait_for_turn_end | hint 规则 | pytest |
| T-06 | 无 evidence/health 时兜底不崩溃，默认 ok_to_dispatch | 兜底 | pytest |
| T-07 | events 段含 bullet 类最近事件且只读（不发射） | 只读 | pytest |
| T-08 | 本地隧道（无 server）跳过远端写者探针 | writers not_remote | pytest |

## 2. dt rebuild

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| R-01 | evidence working 无 --force 拒绝，发 rebuild.fail | fail-closed | pytest |
| R-02 | --force 覆盖 working 拒绝 | 覆盖 | pytest |
| R-03 | 远端路径顺序：reconcile → reconnect → fence → start | 顺序 | pytest |
| R-04 | 探测失败（fence 返回 None）拒绝盲启 | fail-closed | pytest |
| R-05 | 成功路径发 bullet.rebuild.start/.ok span | span 事件 | pytest |
| R-06 | ControlService.rebuild 返回 ControlResult 并校验 TunnelNode | control 合同 | pytest |

## 3. 技能与契约

| ID | 用例 | 自动化 |
|---|---|---|
| S-01 | tmux-trigger SKILL.md 含 dt send/dt bullet/dt rebuild/dt log 守则 | pytest |
| S-02 | dual-tmux SKILL.md 与 AGENTS.md 含新动词 | pytest |
| S-03 | KIND_META 含 bullet.rebuild.* | pytest |

## 4. 部署验证

| ID | 用例 |
|---|---|
| D-01 | wheel 安装后 dt --version = 0.4.76 |
| D-02 | 真实隧道 dt bullet --json 输出 hint |
| D-03 | dt upgrade 真实发现 v0.4.76 |
