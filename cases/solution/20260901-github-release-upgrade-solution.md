# GitHub Release wheel 升级修复

## 实现

- `dt upgrade` 查询固定官方仓库 `releases/latest`。
- 仅接受稳定 Release、`github.com` 官方下载域名、固定仓库路径、universal wheel，并要求 tag `vX` 与 wheel 版本 `X` 完全一致。
- 比较 `X.Y.Z[.postN]`，相同版本不重装，旧 release 不允许覆盖新版本。
- 发现新版本时执行 `uv tool install --force <wheel URL>`，打破旧 uv receipt 固定 asset URL 的限制。
- GitHub API 不可用时保留 `uv tool upgrade dual-tmux` 兼容回退。

## 验证

- 自动化覆盖官方 asset、外部 host 拒绝、tag/asset 版本不匹配拒绝、强制升级、同版跳过和禁止降级。
- 199 tests、focused Ruff、compileall、sdist/wheel build 通过。
- 本机先使用 v0.4.48 Release wheel 完成无损安装；config 与全部 tunnel 哈希保持不变。

## 发布

首次作为 v0.4.48.post1 独立 hotfix 发布，不改写 v0.4.48 tag 或 Release 历史。真实安装随后发现 pyproject 构建版本与 `dual_tmux.__version__` 漂移，包元数据为 post1 但 `dt --version` 显示 0.4.48；继续以 v0.4.48.post2 修正双版本源一致性，同样不改写既有 tag/asset。
