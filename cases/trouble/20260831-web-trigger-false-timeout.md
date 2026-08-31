# Web trigger 90 秒误报失败并持续 poll

## 背景

`dt-company_intro_v2` 的 trigger 任务正常运行超过 90 秒时，Web 把当前 OpenCode TUI 快照显示为“失败”；之后日志持续出现 `trigger 更新` / `bullet 更新`。

## 事实

- trigger tmux、OpenCode 和 bullet SSH 均存活。
- trigger 现场存在正常完成的 `Build · grok-4.6 · 4m 3s`。
- bullet 现场存在正常完成的 `Build · Grok 4.6 · 45m 11s`。
- 没有对应的后端失败事件。

## 根因

1. Web 把固定 90 秒 deadline 直接解释为失败。
2. 完成检测依赖连续 8 次完整 pane 文本不变；OpenCode spinner/footer 使全文持续变化。
3. parser 没有暴露 running/idle 和新 completion ID，前端只能猜测。
4. 非 waiting 状态仍把每次后台画面变化写为 poll 日志。
