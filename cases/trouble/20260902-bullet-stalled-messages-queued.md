# bullet 卡死且消息长期积压在 queue（dt-company_intro_v2）

> 日期：2026-09-02 | 隧道：dt-company_intro_v2 | 状态：已缓解（esc 中断），根治见 BL-TRIGGER-001

## 背景

用户发现 bullet（run_company_intro_v2，docker@root@106.75.97.247，OpenCode 1.18.25，grok-4.6 via xs-cp-gateway）一直 queue：发往 bullet 的消息不被处理，长期无反馈。

## 排查事实

- pane 内容 30 秒级 diff 仅底栏进度条动画变化，无任何新输出。
- 容器内 `opencode.log`：最后一次 `stream providerID=xs-cp-gateway modelID=grok-4.6` 在 10:01:33 CST，此后 77 分钟无 loop step / 无 stream 事件。
- 上下文 220.5K tokens；TUI 显示 `esc interrupt` 进行中。
- 结论：模型流请求挂起且 OpenCode 无超时，turn 永不结束 → OpenCode 队列机制使后续消息无限排队。

## 关联缺陷

- `activity.pane_hash` 整屏哈希含 TUI chrome（进度条/spinner），卡死时哈希仍每分钟变化，`frozen_last_ticks` / `idle_enough` 失效。

## 缓解

- 对 run_company_intro_v2 发送 Escape 中断挂起的 turn，queue 恢复可消费。
