# 飞书 Hub 凭据归属不一致：解决方案

## 解决步骤

1. 保留 `CredentialVault` 的 owner/mode/symlink 严格校验，不降低安全标准。
2. 加密凭据上传后，在 Hub 端执行 `chmod 600`。
3. 使用 Hub 当前 SSH 用户的 `id -u`/`id -g` 设置两个文件的 ownership。
4. Hub 未确认权限修正时返回 `hub_installation_permissions`，不宣告同步成功。
5. 在 tom7r 的常驻 daemon 容器中验证凭据可解密和 WS 可启动。

## 关键点

- 修复发生在跨机器部署边界，而不是绕过本地安全检查。
- 不在日志、命令输出或案例中记录 App Secret。
- local-only 模式不受影响；Hub 模式在不同 UID 的机器间同步仍可安全运行。
