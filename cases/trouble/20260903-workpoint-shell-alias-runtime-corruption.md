# shell alias 跳板导致 workpoint runtime 损坏

> 日期：2026-09-03 | 状态：已解决（solution 20260903-workpoint-shell-alias-runtime-solution）

## 现象

新隧道 `dt-alex-serp` 的 bullet 已在远端容器运行，但 `dt freeze` 无法绑定，会尝试连接主机 `cd`：

```text
runtime.server = cd
runtime.cmd = ssh ... cd "cd ~ && exec bash"
freeze.client.fail: version command exited 255
```

## 根因

- pane hop 历史包含 `cd ~ && tom1r && logout`，旧逻辑把整条 `resume_cmd` 交给 SSH target parser，首个位置参数 `cd` 被误判为主机。
- `tom1r` 是 zsh alias，不是可靠的 SSH config endpoint；旧逻辑无法取得 alias 内的真实 host/port。
- pane scrollback 只剩宿主机 SSH hop 时，freeze 会用宿主机目录 `~` 覆盖已知容器 `/workspace`。

## 影响

- remote client 版本探测连接错误主机，bullet session discovery 失败。
- runtime 无法跨机器恢复到真实容器工作目录。
