# 项目状态: dual-tmux

> 最近更新: 2026-08-31 10:08 +08:00 | 更新者: Codex PM

## 状态树

### v0.06 (ACTIVE) — Web 发布版

- **feature/v0.06-agent-client-web** (MERGE_PENDING): CLI/Web 已展示两侧客户端名称、版本和位置；66 项测试、构建、新增模块 lint 与浏览器 DOM 验收通过，候选包版本 `0.4.38`。

### v0.05 (ACTIVE) — API 开发版

- **feature/v0.05-agent-client-metadata** (CODE_COMPLETE): freeze 已采集 trigger/bullet 的 OpenCode、Codex、Claude 客户端名称、版本、路径和运行位置；66 项测试与真实本机/tom7r 容器验证通过。

### v0.04 (RELEASED) — 当前发布线

- 发布包版本：`0.4.37`，标签 `v0.4.37` 指向 `b392601`
- **hotfix/hub-bidirectional-sync** (MERGED)
  - **issue-local-misses-remote-tunnels** (CLOSED): minute tick 已实现无删除 merge-sync；本地与 tom7r 的 6 条隧道集合和内容哈希一致。

## 当前焦点

- v0.05 API 与 v0.06 Web 已完成，进入全量封板、PR、合并与 `0.4.38` 发布。

## 待办

- [x] 核对本地、tom7r、另一 Client 三方数据事实
- [x] 使用显式 `dt pull` 恢复本机缺失的 4 条隧道
- [x] 完成 merge-sync 自动化测试和真实 tom7r 冒烟
- [x] Review 后将 L3 标为 RESOLVED、hotfix 标为 CODE_COMPLETE
- [x] 经用户确认后推送 hotfix 分支并校验远端 SHA
- [x] 创建 PR #1 并合并到 `main`
- [x] 打 `v0.4.37` 标签、创建 GitHub Release 并验证 `dt upgrade`
- [x] 完成 v0.05 三件套、采集器、freeze 集成与回归测试
- [ ] 完成 v0.06 Web 展示、封板并发布 `0.4.38`

## Git 权限模式

- `pm-maintainer`：用户已明确授权做完后合并并发布；本 hotfix 通过 PR 保留审计记录。

## 案例目录

- 项目本地案例统一收录在 `cases/`，使用 `trouble/` + `solution/` 成对记录。
