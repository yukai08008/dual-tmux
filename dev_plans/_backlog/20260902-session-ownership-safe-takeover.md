# BL-RUNTIME-001：Session Ownership 与安全接管

## 状态

`PLANNED`：API 底座进入 v0.4.49；Web 交互进入 v0.4.50。

## 现场

`dt-company_intro_v2` 在 `tm_ouc` 笔记本锁屏后仍由 cron `dt tick` 续租。另一 Client 执行 resume 时，错误称“last 30 ticks still changing”，随后本地 op/run tmux 已被删除。真实样本显示：最后 30 条跨约 4 小时，只有早期活动；最近 15 条 fingerprint 相同。同时远端曾出现多个 OpenCode 进程打开同一 session ID。

## 核心问题

- Lease heartbeat 被错误解释为用户活跃。
- runtime、attached、progress 和 ownership 混成一个状态。
- “最后 30 条”不是时间窗口，稀疏采样保留数小时前的活动。
- resume 在 preflight 拒绝路径产生删除本地 pane 的副作用。
- session ID 没有 writer 单活保护。
- Tunnel binding 与 conversation snapshot 分属两条同步链；`dt pull` 只拉前者。
- persist job 只 rsync 假定已存在的 JSON，不内建 export；OUC 的 Hub source 目录为空。
- `ensure_local()` 发现同 session ID 已存在就跳过，无法识别本机内容 revision 陈旧。

## 规划

- v0.4.49：语义活动、Lease v2、daemon handoff、transactional resume、session writer singleton、snapshot export/manifest/freshness resolver、CLI/JSON 合同。
- v0.4.50：四维状态面板、安全接管向导、跨 Web/CLI/tmux 状态收敛与正式发布。

## 验收摘要

- 锁屏后台 tick 显示 owner online，但不显示用户 active/busy。
- preflight/claim 失败不删除本地 tmux、不改 binding。
- 同一 session ID 最多一个 writer。
- 同一 session ID 的最新 revision 和尾消息在接管后必须与 owner manifest 一致。
- owner 可达时通过 persist→park→release→claim→verify 安全 handoff。
- 所有状态附带样本数、真实覆盖时间和明确拒绝原因。
