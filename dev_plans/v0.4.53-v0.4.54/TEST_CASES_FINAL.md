# v0.4.54 验收报告

> 验收日期：2026-09-07  
> 分支：`feature/v0.4.54-ownership-web`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 自动化测试 | 299 | 299 | 0 |
| 聚焦 Ruff | 10 files | 10 | 0 |
| Browser E2E | 4 | 4 | 0 |
| 构建/隔离安装 | 4 | 4 | 0 |
| Git/数据门禁 | 2 | 2 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 证据 |
|---|---|---|---|
| B-00 | 全量 backend/Web | PASS | `299 passed` |
| B-01 | 运行时数据不入 Git | PASS | `git ls-files data/` 为空 |
| B-02 | 编译与构建 | PASS | compileall；sdist/wheel 成功 |
| B-10 | cache 原子写读 | PASS | `test_ownership_cache_is_atomic_read_only_and_stale` |
| B-11 | cache missing/stale | PASS | cached plan fail closed tests |
| B-12 | Web GET 无 live probe | PASS | live snapshot 设为 pytest fail 后 GET 仍成功 |
| B-13 | local-only | PASS | Browser 显示“本地单机（无 Hub lease）”和 TTL n/a |
| W-10 | 四维事实面板 | PASS | Browser 显示 lease/runtime/attached/progress/writer/PID |
| W-11 | Codex/Claude native 状态 | PASS | Browser fixture 显示 local Codex、hub Claude 与 UUID |
| W-12 | 页面生命周期零副作用 | PASS | reload 后 `op_browser`/`run_browser` 仍不存在；源码无 auto-resume |
| W-13 | Handoff 状态与实时重验 | PASS | handler/control contract tests；request id/status 渲染 |
| W-14 | 硬安全门 | PASS | ownership conflict/duplicate/unknown/stale tests |
| W-15 | Force 确认 | PASS | 精确 tunnel 名 HTTP 409 test；UI 仅 claim 时启用 |
| R-01 | 验收报告 | PASS | 本文件 |
| R-02 | P0/P1 遗留 | PASS | 无阻断遗留 |
| R-03 | 隔离安装版本一致 | PASS | CLI 与 metadata 均为 `0.4.54` |
| R-04 | 数据无损 | PASS | 本机真实升级前后 config + 10 tunnel 聚合 SHA-256 均为 `940a3e1985d2b0652d2654601c9e477fc65061fedc98f04595694ab2ef709cbb` |
| R-05 | Tag、Release、真实 upgrade | PASS | `v0.4.54-final`/`v0.4.54` 指向 `a3a88c1`；GitHub wheel 安装后 `dt 0.4.54` |

## Browser E2E 证据

- 本地 `127.0.0.1:8891/tunnels?t=dt-browser` 使用隔离 `DUAL_TMUX_HOME`。
- local-only、Codex trigger、Claude bullet、runtime/attached/progress/writer/native snapshot 均可视。
- 页面 reload 后 facts 保持，未创建 tmux session。
- 浏览器 console warning/error 为 0。
- 真实本机 `dt-company_intro_v2` 显示 Hub Lease generation 3、trigger attached/working、bullet detached/working 及 writer/PID；cache 持续刷新。
- launchd daemon 重启为 PID 17336，`mailbox_worker=running`、飞书 owner=`tom7r`、本地 connector=`standby`；10 条 tunnel 中 10 条均已生成 cache。

## 遗留问题

- Python 依赖 `lark-oapi` 在测试中产生上游 naive UTC deprecation warning；不影响业务与发布。
- 真实破坏性跨机 handoff 未为验收人为中断正在工作的 Agent；既有协议与 generation fencing 未在本 Web 版修改，真实面板证据及 fail-closed 状态已验证。
