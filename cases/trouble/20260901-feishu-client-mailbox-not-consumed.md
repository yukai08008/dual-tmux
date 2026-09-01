# 飞书 Client mailbox 未自动消费

## 现象

飞书立即回复“指令已送达，等待对应 Client 执行”，之后长期没有最终结果；每次手工执行 `dt feishu sync` 才会回包。

## 事实证据

- tom7r Hub daemon 持续 `connected`、Docker `healthy`，入站消息正常写入 `commands/tm_ouc`。
- 2026-09-01 15:00 的 `/dt ls` 到 15:04 仍完整积压。
- 本机 crontab 每分钟运行 `/Users/andy_ouc/.local/bin/dt tick`，该正式安装版本为 `0.4.46.post1`。
- 0.4.46.post1 的 `cmd_tick` 不包含 `sync_client`，因此运行次数再多也不会消费 mailbox。
- 候选仓库的手工 sync 随即完成 `commands=1, errors=0` 并由 Hub WS 回包。

## 根因与设计缺口

Hub 入站/回包是常驻 WS worker，但 Client 执行只在候选版的一分钟 tick 中实现，且没有随扫码自动安装/升级常驻 Client daemon。运行时版本漂移使整个执行段永久缺席；即使升级到候选版，分钟级延迟也不适合作为聊天主路径。

## 修复方向

- Client daemon 每 5 秒以一次轻量 SSH 探针检查自己的 mailbox，有任务时才打开 rsync。
- `dt tick` 保留一分钟兜底。
- daemon、tick、手工 sync 共享跨进程文件锁，避免并发执行同一 event。
- 扫码完成自动安装原生 user service；升级 hotfix 对已有 active PersonalAgent 补装 daemon。
- 全链路为确定性 ControlService，不调用大模型；只有 `/dt send` 的目标 Agent 内容处理使用模型。
