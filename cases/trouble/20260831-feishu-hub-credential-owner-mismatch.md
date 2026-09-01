# 飞书 Hub 凭据归属不一致

## 背景

v0.4.48 首次真实扫码成功后，加密 installation 与 key 已同步到 tom7r，但 Hub daemon 的 connector 保持 `stopped`。

## 现象

- dt Web 显示安装 `ready`、operator 已绑定。
- tom7r 上两个凭据文件均存在且 mode 为 0600。
- 容器内 `CredentialVault.load()` 返回安全权限错误。

## 根因

同步使用 `rsync -a`，保留了 macOS 本机 UID 501。tom7r 容器内 daemon 以 root 运行，凭据安全检查要求文件必须属于当前用户，因此正确地 fail-closed。

## 跟进事项

- Hub 发布流程在上传后归一化 ownership 与 0600 mode。
- 增加自动化测试，确保权限命令在 route 注册前完成。
- 真实 tom7r 容器复验 WS 与消息回包。
