# 2026-09-09：跨 Client 快照分支阻塞 Resume

## 背景

执行 `dt resume dt-alex-serp` 时，系统报告本地 session 更新较晚但不包含
`tm_andy_home` 的持久化 tail，要求用户先人工修复。

## 现场证据

- session：`ses_f9a125dbdffelXmINuIVU0D7CT`
- 共同消息：278 条
- 本机有效独有消息：14 条
- `tm_andy_home` 有效独有消息：6 条
- 本机总计 292 条；无损 union 后为 298 条，两边 tail 均保留。
- 共同 ID `msg_080b2211f001pmrUZmiI2TSNZX` 在 home 快照为执行中的 pending
  状态，本机版本为其完成态，说明相同 ID 的记录也可能随流式执行自然丰富。

## 根因

旧 resolver 只按 `session.time.updated` 选择一个“最新”快照，再用单 tail 祖先关系
判定是否可导入。OpenCode session 实际是以全局唯一 message/part ID 组成的
append-only 图；多端各自新增合法分支时，单 tail 模型会把可无损求并集的数据误判
为冲突。

## 不变量

- 不删除或覆盖本机已有 message/part。
- 导入前保留完整 session JSON 与 SQLite 物理备份。
- 只有相同 ID 的 immutable graph identity（role/parent、part type/tool/call）不一致
  才视为真正冲突。
- Resume 前置完成合并，不先 claim 或修改 tmux。
