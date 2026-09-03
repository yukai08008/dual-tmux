# v0.4.49 PRD — Hotfix 合集（开发线）

> 父版本：v0.4.48.post2（tag v0.4.48.post2）
> 起草日期：2026-09-02
> 类型：API 版（奇数，默认不单独发布；纯 hotfix 不受奇偶约束，可破例走 post 发布）
> 范围来源：用户口述问题清单（逐条追加）

## 0. 一句话目标

集中修复 v0.4.48.post2 发布后发现的问题，每个问题一个独立 hotfix 分支（L3），全部闭环后决定并入 v0.4.50 或以 post 版发布。

## 1. 范围与不变量

### 1.1 In-scope

- 用户口述的 hotfix 问题清单（见第 3 节，逐条追加，每条对应 `hotfix/v0.4.49-*` 分支）。

### 1.2 Out-of-scope

- Backlog 中的新功能（项目级 Agent 套件、Web 交接区、自适应轮询等）不在本版，归 v0.4.50+。
- 协议/数据模型变更（奇数版虽为 API 版，但本版定位为修复合集，不主动引入新协议）。

### 1.3 不变量（继承 v0.4.48）

- 一个 deployment 只有一个总 PersonalAgent；凭据仅以 AEAD 密文落盘。
- local/Hub WS 单活租约 + generation fencing；旧 generation fail-closed。
- 运行时数据不在 git 追踪中。
- 升级路径不降级；config/tunnel 哈希在升级前后不变。
- 每个 hotfix：commit message 标注 `hotfix`，附简要测试验证，不混入功能开发。

## 2. 工作方式

```
main (v0.4.48.post2)
  └── hotfix/v0.4.49-<issue-slug>   ← 每个问题一个分支（L3）
        → 本地测试验证 → PR → 合并 main
```

- Git 权限模式：`pm-maintainer`（门禁全过后经 PR 合并保留审计记录）。
- 全部 hotfix 合并后：跑全量 pytest 回归，更新 pm-state.md，再决定发布形式。

## 3. Hotfix 清单

| # | 分支 | 问题 | 状态 |
|---|------|------|------|
| 1 | hotfix/v0.4.49-tmux-sync-status | 终端 tmux 状态栏无同步状态提示（同步链路本身健康，属可视化缺口） | MERGED (PR #18) |
| 2 | hotfix/v0.4.49-tick-cron-path | cron 裸 PATH 无 homebrew，`dt tick` 每分钟 FileNotFoundError: tmux 崩溃（14292 次 start 仅 10 次完成），错误被 `>/dev/null` 吞掉 | MERGED (PR #20, post4) |
| 3 | hotfix/v0.4.49-bullet-fencing | bullet 同一 session 被多个 opencode 进程并发持有（m7 实测 4 实例），导致 turn 互相阻塞、消息积压 queue；pane 已附着 TUI 时 resume 命令被打进输入框 | FIXED |

## 4. 风险登记表

| ID | 风险 | 缓解 | 严重度 |
|----|------|------|--------|
| R1 | hotfix 触及飞书/升级等已验证路径引入回归 | 每个 hotfix 独立分支 + 相关测试全跑 + 合并前全量回归 | medium |
| R2 | 多个 hotfix 并行改同一文件产生冲突 | 按序合并，后一个 rebase 到最新 main | low |
