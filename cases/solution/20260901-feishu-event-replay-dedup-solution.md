# 飞书事件重投去重修复

## 解决步骤

- command 首次入队时建立同 inode 的持久 receipt。
- Client 消费并删除 command 后保留 receipt。
- 同一 `event_id` 再次到达时不覆盖 payload、不重新入队，也不再次发送“指令已送达”回执。
- receipt 保存在当前 username deployment 内，跨用户不共享。
- 逐级强制创建 0700 的 receipts/commands/Client 目录，消除 umask 造成的 0755 中间目录。

## 验证

- 自动化覆盖入队前重投、消费后重投、首份 payload 保持和目录权限。
- tom7r 容器探针结果：首次 `accepted=true`，消费后重投 `accepted=false`，receipt 仍存在，command 未重建。
- 2026-09-01 真实 `/dt ls` 只出现一条即时回执，只执行一次，Client 记录 `commands=1, errors=0`。

## 不变量

- receipt 文件为 0600，完整目录链为 0700。
- event 去重只影响入口幂等，不改变正常 command/response 生命周期。
