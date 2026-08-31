# 项目状态: dual-tmux

> 最近更新: 2026-08-31 13:59 +08:00 | 更新者: Codex PM

## 状态树

### v0.4.44 (RELEASED) — hotfix: persisted entry authority

- **hotfix/v0.4.44-entry-authority** (MERGED): PR #8 已合并并发布；以原 tmux entry 与已登记 runtime 为远端 workpoint 权威来源，修复 SSH remote command 覆盖 host 和本机 cwd 污染展示/再次 freeze；110 tests 与真实容器 freeze 通过。

### v0.4.43 (RELEASED) — hotfix: remote freeze binding correctness

- **hotfix/v0.4.43-freeze-remote-binding** (MERGED): PR #7 已合并并发布；修复 disconnected shell 被当作远端 OpenCode、latest remote session 误绑、本机 cwd 污染远端 runtime，以及空白新 TUI 误绑同 cwd 旧 session。

### v0.4.42 (RELEASED) — 抗抖动健康检测与自动恢复

- **feature/v0.4.42-health-recovery** (MERGED): PR #6 已合并；分层 probe、状态机、显式自动恢复、远端 session import、CLI/Web 状态已发布。

### v0.4.40 (RELEASED) — Agent Adapter 与统一控制内核

- **feature/v0.4.40-control-kernel** (MERGED): PR #4 已合并；三客户端真实能力注册表、CLI/Web/未来飞书共用 ControlService、能力/操作 Web API 已发布。
  - **issue-bullet-session-cannot-resume** (CLOSED): v0.4.41 hotfix 已发布；混合工作点、跳板竞态、本地 bullet persist import 和提示符误判均已修复。

> 版本编号说明：从本版本起，L1 与实际 Python 包版本/Git 标签保持一致。以下 `v0.04`～`v0.08` 是历史内部里程碑，仅作记录，不再延续编号。

### v0.08 (RELEASED) — 本地/Hub 交互发布版

- **feature/v0.08-local-hub-ux** (MERGED): PR #3 已合并；CLI、双语文档与 Web 指南已完成，发布包版本 `0.4.39`。
- **docs/foundational-operating-modes** (MERGED): 已将纯本地模式与 Hub 同步模式提升为 README 顶层基础运行模型，补充模式对照、数据边界、切换命令与无损不变量。

### v0.07 (ARCHIVED) — Local-first API 版

- **feature/v0.07-local-first-config** (MERGED): 纯本地配置、可选 Hub、merge-before-commit 迁移事务和本地运行路径已被 v0.08 / PR #3 吸收。

### v0.06 (RELEASED) — Web 发布版

- **feature/v0.06-agent-client-web** (MERGED): PR #2 已合并，CLI/Web 已展示两侧客户端名称、版本和位置；包版本 `0.4.38`。

### v0.05 (ARCHIVED) — API 开发版

- **feature/v0.05-agent-client-metadata** (MERGED): API 能力已被 v0.06 吸收并通过 PR #2 合并。

### v0.04 (RELEASED) — 当前发布线

- 发布包版本：`0.4.37`，标签 `v0.4.37` 指向 `b392601`
- **hotfix/hub-bidirectional-sync** (MERGED)
  - **issue-local-misses-remote-tunnels** (CLOSED): minute tick 已实现无删除 merge-sync；本地与 tom7r 的 6 条隧道集合和内容哈希一致。

## 当前焦点

- `v0.4.44` hotfix 已发布并在本机升级完成；`dt-company_intro_v2` 已按最初 freeze 留下的入口恢复至 `106.75.97.247:24500 / me_andy_browser / /root/intro_v2 / nimble-cactus (ses_fb37c74b8ffe9VH0RIKOSZfQJW)`。重复 freeze 后入口、runtime、run_point、本地与 Hub 记录仍一致，分层健康状态全绿；tom7r 仅为 Hub，不是 bullet runtime。

## 待办

- [x] 完成 v0.4.42 三件套、health probe 与状态机
- [x] 完成远端 session import、CLI/tick/Web 接入
- [x] 完成故障注入、浏览器 E2E、PR #6、v0.4.42 发布与真实升级
- [x] 合并 PR #8、发布 v0.4.44 并完成本机真实升级
- [x] 以最初 freeze 入口恢复 dt-company_intro_v2 远端容器 session
- [x] 验证重复 freeze 后本地/Hub 权威入口不漂移且 health 全绿

- [x] 完成 v0.4.40 三件套与 Agent Adapter
- [x] 完成 ControlService 并迁移 CLI/Web 操作
- [x] 完成 88 tests、浏览器 E2E、构建与封板报告
- [x] 创建并合并 PR #4，发布 v0.4.40
- [x] 本机真实执行 `dt upgrade` 并验证数据无损
- [ ] 三客户端原生生命周期适配顺延到 v0.4.42（v0.4.41 被紧急 hotfix 占用）
- [x] 定位 dt-msg2 bullet 接续失败并确认 session 数据未丢失
- [x] 恢复 happy-circuit session，校正本地/中心工作点
- [x] 合并 PR #5 并发布 v0.4.41 hotfix
- [x] 本机真实升级 0.4.40 → 0.4.41，配置/tunnel 哈希不变且 bullet 保持原 session 运行

- [x] 核对本地、tom7r、另一 Client 三方数据事实
- [x] 使用显式 `dt pull` 恢复本机缺失的 4 条隧道
- [x] 完成 merge-sync 自动化测试和真实 tom7r 冒烟
- [x] Review 后将 L3 标为 RESOLVED、hotfix 标为 CODE_COMPLETE
- [x] 经用户确认后推送 hotfix 分支并校验远端 SHA
- [x] 创建 PR #1 并合并到 `main`
- [x] 打 `v0.4.37` 标签、创建 GitHub Release 并验证 `dt upgrade`
- [x] 完成 v0.05 三件套、采集器、freeze 集成与回归测试
- [x] 完成 v0.06 Web 展示、封板并发布 `0.4.38`
- [x] 完成本地模式与 Hub 切换影响评估、v0.07/v0.08 三件套
- [x] 实现纯本地初始化、无网络 Hub helper 和本地 tunnel runtime
- [x] 实现旧 Hub → 新 Hub → 配置落盘的无损迁移事务
- [x] 完成 78 tests、构建、浏览器 E2E 和真实 tom7r 哈希验证
- [x] 创建并合并 PR #3，校验远端 `main` SHA
- [x] 发布 `v0.4.39`（sdist + wheel）
- [x] 本机真实执行 `dt upgrade`：`0.4.38` → `0.4.39`
- [x] 升级后确认 Hub 模式、tom7r 配置和 `dt push` 正常

## Git 权限模式

- `pm-maintainer`：用户已明确授权做完后合并并发布；本 hotfix 通过 PR 保留审计记录。

## 案例目录

- 项目本地案例统一收录在 `cases/`，使用 `trouble/` + `solution/` 成对记录。
