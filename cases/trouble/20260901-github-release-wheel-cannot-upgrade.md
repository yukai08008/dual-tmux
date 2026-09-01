# GitHub Release wheel 安装后 `dt upgrade` 无法发现新版

## 现象

本机从 v0.4.46.post1 GitHub Release wheel 安装。v0.4.48 发布后执行 `uv tool upgrade dual-tmux` 返回 `Nothing to upgrade`，版本仍为 0.4.46.post1。

## 根因

uv receipt 将 requirement 固定为具体旧 wheel URL。`uv tool upgrade` 只重新解析同一 URL，不会自动查询 GitHub Releases，因此即使远端已有新 tag/asset 也无法发现。

## 修复

`dt upgrade` 固定查询官方仓库 `/releases/latest`，只接受 `github.com/yukai08008/dual-tmux/releases/download/<tag>/dual_tmux-*-py3-none-any.whl`，版本变化时执行 `uv tool install --force <asset>`。GitHub API 不可用时保留原 uv upgrade 作为兼容回退。
