# 2026-09-15：Remote Bullet 恢复报 session missing remotely and no local persist JSON

## 现象

用户在对旧隧道执行 `dt resume dt-cp-gate` 时失败报错：

```text
· pulling Hub state
· checking trigger activity across terminals
· syncing updated session from remote terminal (tm_andy_home)
· session sync complete
ok  resent run_cp_gate <- ssh -t -o ServerAliveInterval=15 -o ServerAliveCountMax=3 root@10.88.0.20 "docker exec -it me_andy_browser bash -lc 'cd /workspace && exec bash'"
[err] bullet session ses_f8a384577ffeb75HokVSq3nf13 missing remotely and no local persist JSON
```

## 现场证据与根因

1. **SSH 批量模式对未录入 Known Hosts 失败**：
   `_ssh_argv` 在非交互探针和命令执行中使用 `BatchMode=yes`，但缺少 `-o StrictHostKeyChecking=accept-new`。当连接未被提前写入 `~/.ssh/known_hosts` 的新内网 IP/WireGuard 宿主机（如 `10.88.0.20`）时，SSH 无法交互确认指纹，直接以 `Host key verification failed`（返回码 255）退出。
2. **容器自愈路由（reconcile_remote_runtime）被短路**：
   `dt-cp-gate` 的历史 `runtime.container` 误绑为已销毁的 `me_andy_browser`，而真正的 bullet 会话 `ses_f8a384577ffeb75HokVSq3nf13` 存活在 `cp_gateway_24629` 中。因为第 1 点 SSH 探测直接被阻断，`remote_session_locations` 返回 `None`，导致原本具备的容器自愈修正未能生效，`jump` 命令被发往不存在的容器。
3. **`ensure_remote_session` 误诊网络不可达为会话丢失**：
   探针失败后，`_remote_probe(data).get("session").get("ok")` 为 `False`。代码未判断 `transport` 是否连通，且在本地无 bullet 快照（远端会话通常无本机快照）时，直接抛出 `missing remotely and no local persist JSON`，误导用户以为远端会话已丢失。
4. **Trigger 快照选择器未降级至现存快照**：
   同时暴露出的连锁问题：本地 Client（`tm_andy_ouc`）曾记录过空行 tick，被推选为 `preferred_source`；但本机本地既无 sqlite 会话又无对应快照文件，`_tick_snapshots` 未能自动回退到包含真实快照的来源（`tm_andy_home`），导致报 `trigger session ... has no persist JSON under .../tm_andy_ouc/`。

## 业务影响

- 跨网段或新 IP 宿主机上的远端容器会话在 resume 时直接崩溃。
- 会话自愈机制被网络握手误报中断，无法自动纠正漂移的容器名。
- 给出错误的排障提示，阻碍正常的会话恢复。
