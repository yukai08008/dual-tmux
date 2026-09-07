# v0.4.53 发布后：upgrade API 限流与 native cron 写超时

## 现场

- 本机 0.4.51 执行 `dt upgrade`，GitHub Releases API 返回 403 rate limit。
- 旧 fallback 执行 `uv tool upgrade dual-tmux`，因 receipt 固定旧来源而输出 `Nothing to upgrade`，版本仍为 0.4.51。
- 直接安装 v0.4.53 wheel 成功，配置与 10 个 tunnel 文件哈希不变。
- `dt doctor` 已生成 `dt-persist-native`，但 `crontab -` 连续两次超时；旧 tmux/OpenCode 行与 `dt tick` 行仍正常。

## 影响

- 未修复时，未认证/共享出口用户可能无法用 `dt upgrade` 获得新 Release。
- handoff 会直接调用 native sync，因此安全接管不依赖 cron；但日常快照上传不能只押注 native cron 安装成功。

## hotfix

- API 请求遇到网络/HTTP 错误时，解析不受 API rate-limit 约束的 GitHub `/releases/latest` 最终重定向，构造同仓库、同 tag 的 wheel URL。
- `dt tick` 发现当前 owner 有本地 native side 时运行 native persist sync；失败写审计事件，下一轮会重试。cron 保留为冗余。
