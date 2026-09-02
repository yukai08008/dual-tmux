# BL-TRIGGER-001：trigger 有能力判断 bullet 状态（卡死检测）

## 背景

2026-09-02 真实案例（dt-company_intro_v2）：bullet 的模型请求（grok-4.6 via xs-cp-gateway，上下文 220K tokens）在 10:01 CST 发出后 77 分钟零输出，turn 一直不结束。OpenCode TUI 进度条/spinner 持续动画，表面看"活着"，实际已卡死。期间 trigger/用户发往 bullet 的消息全部停留在 queue，长期无反馈。

现有机制在此场景失效：

- `activity.pane_hash` 对 pane 最后 10 行整体取哈希，包含 TUI 进度条/spinner；spinner 动画使哈希每分钟变化，`frozen_last_ticks` 永远判不出 frozen。
- 因此健康检查、lock 接管（`idle_enough`）、trigger 的轮询脚本都观察不到"卡死"，只能看到"仍在运行"。
- trigger 侧无任何手段区分「bullet 正在长任务」与「bullet 卡死、消息在排队」。

## 需求

- 定义 bullet 的可判定状态：`idle`（可收消息）/ `working`（turn 进行中且有有效增量）/ `stalled`（turn 进行中但 N 分钟无有效输出）/ `down`（pane/跳板断）。
- "有效增量"必须剥离 TUI chrome（进度条、spinner、token 计数、footer），以 `paneparse` 解析结果或剥离 chrome 后的文本哈希为准，而不是整屏哈希。
- `dt inspect` / `dt health` / Web / `activity` 指纹统一暴露该状态，trigger 轮询时可直接读取（如 `dt inspect --json` 含 bullet 状态与 stalled 时长）。
- trigger 的轮询纪律（tmux-trigger skill）据此升级：发现 `stalled` 超过阈值时停止继续 send-keys 堆 queue，改为上报/提醒用户，可选经确认后 esc 中断卡死 turn 再重发。
- stalled 阈值建议可配，默认参考：turn 内零有效输出 ≥5–10 分钟记 stalled（正常长任务通常有工具输出或流式文本增量）。

## 非目标

- 不自动 esc 中断或重启 bullet（避免误杀真实长任务），自动动作必须显式确认。
- 不替代 BL-WEB-004 的核心文本提取，两者共用"剥离 chrome"的解析底座。

## 验收

- 复现卡死（mock 网关挂起或真实案例重放）时，`dt inspect` 在阈值内将 bullet 标为 `stalled`，trigger 不再向其堆叠消息。
- 正常长任务（持续有工具/流式输出）不误判 stalled。
- spinner 纯动画 30 分钟以上应被判 frozen/stalled（修复 pane_hash 被 chrome 欺骗的问题）。
