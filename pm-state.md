# 项目状态: dual-tmux

> 最近更新: 2026-08-31 10:05 +08:00 | 更新者: Codex PM

## 状态树

### v0.04 (RELEASED) — 当前发布线

- 发布包版本：`0.4.37`，PR #1 合并提交：`434cb8c`
- **hotfix/hub-bidirectional-sync** (MERGED)
  - **issue-local-misses-remote-tunnels** (CLOSED): minute tick 已实现无删除 merge-sync；本地与 tom7r 的 6 条隧道集合和内容哈希一致。

## 当前焦点

- PR #1 已合并，正在执行 `v0.4.37` 标签、GitHub Release 与安装升级验证。

## 待办

- [x] 核对本地、tom7r、另一 Client 三方数据事实
- [x] 使用显式 `dt pull` 恢复本机缺失的 4 条隧道
- [x] 完成 merge-sync 自动化测试和真实 tom7r 冒烟
- [x] Review 后将 L3 标为 RESOLVED、hotfix 标为 CODE_COMPLETE
- [x] 经用户确认后推送 hotfix 分支并校验远端 SHA
- [x] 创建 PR #1 并合并到 `main`
- [ ] 打 `v0.4.37` 标签、创建 GitHub Release 并验证 `dt upgrade`

## Git 权限模式

- `pm-maintainer`：用户已明确授权做完后合并并发布；本 hotfix 通过 PR 保留审计记录。

## 案例目录

- 项目本地案例统一收录在 `cases/`，使用 `trouble/` + `solution/` 成对记录。
