# 项目状态: dual-tmux

> 最近更新: 2026-08-31 12:58 +08:00 | 更新者: Codex PM

## 状态树

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

- `v0.4.39` 已正式发布，Release 包含 sdist/wheel；本机从 GitHub 安装源实测 `dt upgrade` 从 `0.4.38` 升级到 `0.4.39`，现有 tom7r Hub 配置和推送正常。

## 待办

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
