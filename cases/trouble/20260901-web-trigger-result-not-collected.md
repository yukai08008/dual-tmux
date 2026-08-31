# Web trigger 完成结果未归集

## 状态

- L1：`v0.4.48 (ACTIVE)`
- L2：`hotfix/v0.4.48-web-durable-turn-tracking (MERGED)`
- L3：`issue-web-trigger-result-not-collected (CLOSED)`

## 现象

用户在 `dt-portal` 的 trigger 问答区提交“为 chank.orbitx.cn 增加门户卡片并反代 24630”。trigger terminal 随后出现完整结果：入口、卡片和证书均完成，耗时 3 分钟；问答历史只有提问，没有回答。

## 现场证据

- `op_portal` 与 `run_portal` 均在线。
- `/api/tunnel?t=dt-portal` 已解析到正文、模型 `Grok 4.6` 和耗时 `3m 0s`。
- `~/.dual-tmux/web-state.json` 中最后一项是该次 `ask`，不存在对应 `ans`。
- 日志在任务运行期间有 pane 更新，之后退化为普通 `trigger 更新`；没有 `done`。

## 第一性原理根因

一次 Web 提问本质上是一条需要可靠完成的 turn，至少包含“问题、提交时基线、运行状态、完成标识和消费状态”。旧实现只持久化问答文本与日志，把 `waiting`、pane 基线和计时器留在浏览器内存。

页面恢复后，系统虽然还能观察 terminal，却失去了“当前结果属于哪个未完成提问”的因果关系，因此不会把完成结果归集到问答区。

## 影响

- 刷新、切换或重新打开页面可能永久漏掉已完成结果。
- 仅延长超时无法解决；它只减少复现概率。
- 依赖 pane 安静次数可能提前完成，也可能把旧结果归给新问题。

## 修复方向

- 持久化 pending turn。
- 为 pane completion 建立稳定 ID。
- 以提交前 completion ID 作为基线，只消费之后的新 completion。
- 页面恢复时重建 waiting 状态并继续归集。
- 完成消费必须幂等。
