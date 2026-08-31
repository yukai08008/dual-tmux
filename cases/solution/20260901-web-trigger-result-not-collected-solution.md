# Web trigger 完成结果未归集：解决方案

## 修复

- OpenCode pane parser 输出 `phase` 与稳定 `completion_id`；运行态不产生 completion，TUI 重绘不改变已完成 turn 的 ID。
- Web 提交前先读取当前 completion 作为基线，创建唯一 pending turn，并在 `send-keys` 前同步写入服务端 `web-state.json`。
- `pending`、开始时间、基线 completion 与最近已消费 completion 均进入 Web 状态清洗和持久化合同。
- 页面刷新、tab 重开或 Web 服务重启后，从 pending turn 恢复 waiting 状态。
- 只有 `phase=idle` 且 completion ID 相对提交基线与最近已消费 ID 均发生变化时，才生成 answer 并关闭 pending。
- 完成、失败和人工处理状态立即持久化；同一 completion 不会重复生成回答。
- 90 秒只提示长任务并继续等待，不再直接失败。

## 不变量

- 先持久化 turn，再向 trigger 发送，避免产生无法归因的任务。
- 旧 completion 不回答新问题。
- 同一 completion 最多消费一次。
- 页面生命周期不改变 turn 的事实状态。
- terminal 可观察性与问答归集是两层；看见 pane 不等于完成归集。

## 验证

- `161 passed`，compileall 通过，`git ls-files data/` 为 0。
- parser 测试覆盖 running 无 completion、completed completion ID 以及 TUI redraw 稳定性。
- Web 状态测试覆盖 pending turn 与 last completion 的保存/恢复。
- 真实 `dt-portal`：原缺失提问恢复后自动生成 `Grok 4.6 · 3m 0s` 回答。
- 页面再次刷新后 answer 数量保持 2、pending 为 null、浏览器控制台无错误。
