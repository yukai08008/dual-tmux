# 2026-09-09：跨 Client 快照自动 Union

## 机制

1. resolver 收集同一 session 的全部合法 `tm_*` 快照，而不是只选最大更新时间。
2. 对每份含本地缺失 ID 的快照检查共同 message/part 的 immutable graph identity。
3. preflight 只验证，不 claim、不停 pane、不导入。
4. commit 阶段只做一次本地导出备份，再依次调用 OpenCode merge import；已有 ID
   保持本机记录，缺失 ID 插入本地数据库。
5. 每次导入验证远端 tail，全部结束后再验证原本地 tail 仍存在。
6. 相同 session 的多分支属于正常状态；真正 ID identity 冲突继续 fail-closed。

## 真实恢复

`dt-alex-serp` 已先保存 session JSON 和完整 SQLite 备份，再将 292 条本机消息与
`tm_andy_home` 6 条独有消息合并为 298 条；两边 tail 均存在，integrity=`ok`。
随后成功恢复 trigger/bullet 并取得 ownership generation 3。

## 发布结果

- PR #44 合并至 `main`（merge `0b575d4`），Release `v0.4.55.post4` 已发布。
- 350 tests collected：348 passed、2 skipped；聚焦 Ruff、wheel/sdist build 通过。
- 本机升级正式 post4 并重启 daemon 后，再次无冲突恢复 `dt-alex-serp`，取得
  generation 4。
