# 飞书消息路由目录权限错误

## 背景

2026-09-01，真实扫码创建 PersonalAgent 后，用户向机器人发送消息，机器人回复“请求处理失败，请稍后重试”。

## 事实证据

- tom7r 容器 `dual-tmux-feishu-bridge` 健康，WS 为 `connected`，generation=4，failures=0。
- daemon 的 `last_message_at` 为 2026-08-31 18:50:06 +08:00，说明真实消息已到达 WS callback。
- Hub 消息处理必须先通过 `/data/feishu/bridge/routes` 将 operator 映射到 Client。
- 该目录及路由文件为宿主同步来源 UID 501、group staff、mode 0700/0600；容器读取时返回 `Permission denied`。
- 当前发布流程只对 `credential.key` 与 `installation.json` 执行 Hub ownership 归一化，未覆盖 `bridge/routes`。
- `PermissionError` 不属于当前 callback 捕获的 `FeishuError`，因此进入通用异常分支并返回固定失败文案。

## 根因

`rsync -a` 保留了 Client 侧 route 目录/文件 ownership，而 Hub 发布后的安全归一化遗漏了 mailbox route。容器所在存储边界不能读取 UID 501 的 0700 目录，导致 operator 路由在入队前失败。

## 影响

- 扫码、凭据安装和 WS 连接均显示成功，但所有需要 Hub 路由的机器人消息都无法进入目标 Client mailbox。
- v0.4.48 的真实 `/dt ls` 闭环发布门禁失败。
- 错误文案隐藏了具体错误码，Web/daemon 状态仍可能显示健康。

## 待推进

- 将 Hub `feishu/bridge` 下 routes、commands、responses、callbacks、pairing 的目录和文件统一归一化为 Hub 服务身份，并保持目录 0700、文件 0600。
- 发布后增加可读/可写探针，不仅检查 credentials。
- callback 将 `PermissionError` 映射为可审计的 bridge 权限错误，同时避免向飞书泄露内部路径。
- 增加真实 ownership 回归测试和多租户 deployment namespace 设计评审。
