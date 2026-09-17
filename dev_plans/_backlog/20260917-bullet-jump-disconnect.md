# BL-BULLET-001：tick 单隧道 resume 失败中断整轮（bullet 断链/远端缺失）

## 背景

2026-09-17 处置 dt-a 墓碑化（v0.4.79）后，tick 仍每分钟以 `cmd.fail` 退出，报错换成两族同源症状：

- **dt-portal**：`bullet jump did not stay connected (cmd=zsh); stopped before sending the session command`——共 2 次（2026-09-16 00:33 首次、09-17 08:54 再次），每次均先出现 `transport.reconnect.fail dt-portal`，即 bullet 跳板链路建立后立即断开。
- **dt-demo**：`bullet session  missing remotely and no …`——自 2026-09-14 21:09 起累计 11 次，至今每分钟拉断 tick（dt-a 治愈后成为当前主断点）。

连同已由墓碑化处置治愈的 dt-a（09-12 起 1948 次 rsync link_stat 失败），三个实例暴露同一结构性问题：**tick 的自动 resume 路径对单条死/断链隧道 fail-closed，一条坏隧道让整轮 tick 以异常终止**，其余隧道的采样、恢复与同步全部跳过，且每分钟产生一条 `cmd.fail` 噪音。

## 需求（草案，立项时可调整）

- tick/resume 容错隔离：单隧道 resume/transport 失败记录事件（`recovery.attempt.fail` / `transport.reconnect.fail` 已有）后继续处理下一隧道，不再以异常终止整轮 tick。
- 可选：连续失败 N 次的隧道进入 attention/降频（复用 v0.4.77 退避思路），避免每分钟重试同一具尸体。

## 非目标

- 不在本条内修 dt-portal / dt-demo 自身的断链与远端缺失——那是现场处置（`dt rebuild` / `dt rm` 走 v0.4.79 墓碑路径），由 owner 决定。
- 不重写 bullet 传输层；断链重试语义维持现状。

## 验收

- 人为构造一条断链/远端缺失隧道时，`dt tick` 仍完成其余隧道的采样与恢复，整轮不再触发 `cmd.fail`。
- 失败隧道与原因可经 `dt log` 追溯（事件含隧道名与错误）。
- 全量 pytest 零回归；真实 tick 冒烟通过。
