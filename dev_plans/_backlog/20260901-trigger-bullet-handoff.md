# BL-WEB-001：展示 trigger → bullet 的中间交接

## 需求

用户向 trigger 提交需求后，trigger 会理解并改写成发给 bullet 的任务。该中间结果具有独立价值，应在 trigger 与 bullet terminal 之间展示真实的任务摘要、关键约束和交接状态。

## 验收

- 内容来自真实 pane/event，不由 Web 猜测。
- 与 trigger 最终回复明确区分。
- 多次交接按时间顺序展示。
- 刷新或切换隧道后仍可恢复。
