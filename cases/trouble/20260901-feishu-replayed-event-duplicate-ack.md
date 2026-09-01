# 飞书事件重投产生重复回执

## 现象

用户发送一条消息后，机器人两次回复“指令已送达，等待对应 Client 执行”。

## 根因

commands 信封名虽然由 `event_id` 哈希确定，但原实现使用 replace 覆盖同名文件。飞书重投同一事件时，Hub 会再次执行入队路径并再次发送即时回执。Client 侧 dispatcher 能避免重复执行，却不能避免入口重复回执。

## 修复设计

- 首次入队时为 command 建立同 inode 的持久 receipt。
- command 被 Client 消费删除后 receipt 继续保留。
- 同一 `event_id` 重投时不再覆盖 command、不再回复即时回执，并记录 `feishu.ws.message.replay`。
- receipt 位于当前 username deployment 的 `feishu/bridge/receipts`，不会跨租户共享。

## 验证门禁

- 自动化覆盖入队前重投、command 消费后重投和首份 payload 不被覆盖。
- 真实飞书同一事件只出现一次即时回执、只执行一次命令。

## 部署补充发现

首次部署 `c33038c` 后，真实容器探针发现 receipt 文件为 0600、最末级 Client 目录为 0700，但递归创建的 `receipts/` 与 `receipts/commands/` 中间目录受 umask 影响成为 0755。内容未泄露，但不符合 mailbox 全目录 0700 的安全不变量。后续修复改为从 bridge root 开始逐级创建并显式 chmod 0700，同时覆盖 commands/responses 的运行时 Client 子目录。
