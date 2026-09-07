# Session Ownership 与安全接管解决方案

## 背景

旧实现只用 `client@timestamp@generation` 表示活跃 Client，把 lease heartbeat、用户是否 attached、Agent 是否推进和 session writer 数量混成一个结论。锁屏、网络抖动或重复 resume 时可能误判；更严重的是 claim 被拒绝后会删除本地 pane。

## 根因

- 旧锁只能回答“最近谁续租”，不能证明 Agent 是否工作。
- pane 整屏 hash 会被 spinner、footer、token 和时钟动画持续改变。
- resume 没有 plan/acquire/commit/verify 边界，preflight 与 pane mutation 交织。
- Client 名不足以区分同名的两个安装实例，release 也缺少 generation fencing。

## 解决

- 保留 `locks/<tunnel>` v1 文本，增加 `ownership/<tunnel>.json` sidecar；两者在同一 `flock` 临界区更新。
- 增加稳定 instance ID、单调 generation、expected-generation release 与 sidecar/v1 冲突回退。
- 持久化过滤 TUI chrome 的语义证据，独立记录 runtime、attached、progress、writer。
- `dt ownership` 输出统一事实；`dt resume --plan` 完全只读。
- resume 采用 plan → acquire/handoff → commit → verify；失败不发布 binding，并只释放自己新取得的 generation。
- handoff 由 owner daemon 按 persist → park → ack → release 执行；claimant 再 claim 新 generation 并验证精确 session writer。

## 验证

- 277 个自动化测试通过，changed-file Ruff、compileall、build 通过。
- tom7r 隔离目录完成 generation 递增、旧 generation release 拒绝以及双实例 handoff E2E。
- 真实 `dt-company_intro_v2` 的只读 plan 前后 event 与 binding 哈希不变。

## 跟进

- v0.4.52 Web 展示四维事实、接管原因和 handoff 时间线。
- Codex/Claude 的 Client-local session store 尚未进入中心 persist；跨 Client handoff 会 fail closed，后续需补复制协议后才能开放。
- 发布/升级后选择非关键隧道做一次真实双 Client smoke，不自动终止任何真实重复 writer。
