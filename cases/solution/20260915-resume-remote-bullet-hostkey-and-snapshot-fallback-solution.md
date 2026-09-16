# 2026-09-15：Remote Bullet 恢复报 session missing remotely 解决方案

## 修复机制

1. **SSH 参数补全 `StrictHostKeyChecking=accept-new`**：
   在 `src/dual_tmux/cli.py` 的 `_ssh_argv` 与 `src/dual_tmux/hub.py` 的 `ssh_argv` 中，显式添加 `-o StrictHostKeyChecking=accept-new`。在批量静默探测时自动接受安全的新主机公钥并写入 known_hosts，彻底消除因首连内网 IP/别名导致的 `Host key verification failed`。
2. **打通远程容器运行时自愈**：
   SSH 批量探针畅通后，`reconcile_remote_runtime` 能够顺利扫描宿主机上全部存活容器。当发现配置的 `runtime.container` 不存在或错误时，以精确 session id 为唯一证据，自动修正 `runtime.container`（`me_andy_browser` → `cp_gateway_24629`）并同步重写 `run_<name>.cmd`。
3. **`ensure_remote_session` 绝不虚报会话丢失**：
   在 `src/dual_tmux/recovery.py` 中，`ensure_remote_session` 作为快照导入器，当本机无快照（`snapshot is None`）时仅返回 `False`，不发起非法中断。确凿的远端扫描缺失检查交由 `control.py` 在 `route["status"] == "missing"` 时统一 fail-closed。
4. **Trigger 快照跨 Client 智能回退**：
   在 `src/dual_tmux/oc.py` 的 `_tick_snapshots` 中增加防御兜底：若推选来源下既无本地 sqlite 会话又无快照文件，自动通过 `resolve_snapshot(info)` 回退到包含真实快照的合法机器目录（如 `tm_andy_home`），避免空 tick 误判导致的死锁。

## 不变量与守护红线

- 批量 SSH 探测必须支持新主机首次免确认接入（`accept-new`）。
- 宿主机或容器不可达时，绝不得向用户谎称“会话在远端已丢失”。
- 只要任意 Client 拥有该会话的有效快照，resume 绝不可因本地空闲 tick 而拒不导入。

## 回归自动化测试

- `tests/test_bullet_resume.py::test_ssh_argv_includes_accept_new_for_batch_mode`
- `tests/test_bullet_resume.py::test_ensure_remote_session_returns_false_when_no_snapshot`
- `tests/test_persist_sync.py::test_ensure_local_tick_pick_falls_back_when_source_tenant_has_no_snapshot`

## 验证结果

- 全量测试 `709 passed, 1 skipped`
- 现场实测 `apply_resume("dt-cp-gate")`：
  ```text
  ok  imported trigger persist JSON
  ok  trigger opencode --auto -s ses_f8a866ee3ffeUsBBZU2XgZ5IAH -> op_cp_gate
  ok  bullet opencode --auto -s ses_f8a384577ffeb75HokVSq3nf13 -> run_cp_gate
  Resumed: dt-cp-gate
  Runtime container: cp_gateway_24629
  ```
