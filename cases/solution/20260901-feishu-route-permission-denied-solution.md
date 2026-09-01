# 飞书 mailbox 路由权限修复

## 解决步骤

- 飞书文件上传改用 `rsync --no-owner --no-group`，不再把 Client UID/GID 带入 Hub。
- Hub 发布后统一将 credentials、routes 和 mailbox 文件归属到 Hub SSH 用户；目录设为 0700，文件设为 0600。
- route 的 `PermissionError` 转换为结构化 `bridge_unavailable`，不向飞书泄露服务端路径。
- 增加容器内真实 route 读写探针与 ownership 回归测试。

## 真实验证

2026-09-01 13:29，飞书 `/dt ls` 成功进入 `tm_ouc` commands mailbox；本地 Client 在 13:30 执行一条命令，结果为 `commands=1, errors=0`；response 被 tom7r WS 成功回传并删除，用户确认收到完整结果。

## 不变量

- deployment 隔离键仍是 `server + user`。
- daemon 只挂载当前用户的 dual-tmux 根目录。
- bridge 全部目录为 0700、全部 envelope 为 0600。
