# 飞书 Client mailbox 常驻消费修复

## 实现

- 本地 `dt daemon` 增加独立 mailbox worker，每 5 秒通过一次轻量 SSH `find` 探测当前 Client 的 callbacks/commands。
- 仅在发现 JSON envelope 时启动完整 rsync、ControlService 执行和 response 上传。
- `dt tick` 保留一分钟同步兜底；手工 `dt feishu sync` 继续可用于诊断。
- 三个入口共享 `~/.dual-tmux/feishu/sync.lock` 非阻塞文件锁，忙碌 consumer 返回 `skipped=busy`。
- Hub role 禁止启动 Client worker，避免中心容器误消费本地命令。
- 扫码完成自动安装原生 user service；升级 hotfix 为已有 PersonalAgent 补装/更新服务。
- daemon 状态分别展示 WS connector 与 `mailbox_worker`，Hub ownership 的 standby 不再被误解为整个 daemon 停止。

## 真实验证

2026-09-01 15:18:52，将不含 chat_id 的合成 `/dt ls` 放入真实 tom7r `commands/tm_ouc`，随后未调用手工 sync：

- 本机 macOS launchd worker 保持 running；
- t=0/2/4/6 秒 command 仍在，t=8 秒已自动消费；
- 15:19:02 本地事件记录 `commands=1, errors=0`；
- response 正确写入 tom7r，测试 response 与 receipt 随后清理；
- tom7r 飞书 WS 容器全程 healthy/connected。

## 机制边界

`/dt ls/show/health/freeze/resume/recover` 的解析和执行全部是确定性程序逻辑，不调用大模型。`/dt send` 也由规则代码负责路由；只有文字进入目标 trigger/bullet 后，Agent 对内容的处理才使用其配置模型。
