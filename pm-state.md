# 项目状态: dual-tmux

> 最近更新: 2026-08-31 09:44 +08:00 | 更新者: Codex PM

## 状态树

### v0.04 (RELEASED) — 当前发布线

- 发布包版本：`0.4.36`，远端基线提交：`204b2f8`
- **hotfix/hub-bidirectional-sync** (CODE_COMPLETE)
  - **issue-local-misses-remote-tunnels** (RESOLVED): 已实现 minute tick 的无删除 merge-sync；本地与 tom7r 的 6 条隧道集合和内容哈希一致。

## 当前焦点

- hotfix 代码与测试完成，等待用户授权 push/MR；未合并、未发布。
- 候选发布版本：`0.4.37`。

## 待办

- [x] 核对本地、tom7r、另一 Client 三方数据事实
- [x] 使用显式 `dt pull` 恢复本机缺失的 4 条隧道
- [x] 完成 merge-sync 自动化测试和真实 tom7r 冒烟
- [x] Review 后将 L3 标为 RESOLVED、hotfix 标为 CODE_COMPLETE
- [ ] 经用户确认后 push/MR 合并发布

## Git 权限模式

- `mr-only`：未收到允许 PM 直接推送/合并 `main` 的明确授权；当前只在 hotfix 分支开发。
