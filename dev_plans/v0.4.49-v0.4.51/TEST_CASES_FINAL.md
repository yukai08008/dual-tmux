# v0.4.51 验收报告 — Session Ownership API

> 验收日期：2026-09-07
> 分支：`feature/v0.4.51-session-ownership`
> 合并：PR #28，merge commit `f2f8f31dd6e9169816485e53aa4080ad8dfd30ad`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 自动化测试 | 277 | 277 | 0 |
| focused Ruff / compileall / build | 3 | 3 | 0 |
| tom7r 隔离 Lease/Handoff E2E | 2 | 2 | 0 |
| 真实隧道只读验证 | 2 | 2 | 0 |

## 逐项结果

| ID | 结果 | 证据 |
|---|---|---|
| B-00 | PASS | `uv run --group dev pytest -q`，277 tests |
| B-01 | PASS | changed-file Ruff、`compileall`、sdist/wheel build |
| B-02 | PASS | `git ls-files data/` = 0 |
| A-01~A-05 | PASS | spinner/footer/token/clock golden、真实语义变化、stall、样本窗口测试 |
| L-01~L-04 | PASS | v1 合成、sidecar 对齐、陈旧 sidecar fail closed；tom7r 隔离目录验证 generation 1→2 |
| L-05 | PASS | tom7r 隔离 request→ack→release→claim E2E，请求方 generation=2 |
| O-01~O-06 | PASS | schema、stale evidence、duplicate/unknown writer、三客户端 local/SSH/container fixtures |
| R-01 | PASS | 真实 `dt-company_intro_v2 --plan` 前后 event/binding SHA-1 完全一致 |
| R-02 | PASS | claim rejection 单测证明不调用 `drop_local` |
| R-03~R-04 | PASS | daemon 顺序与 persist 故障注入测试 |
| R-05~R-06 | PASS | commit failure 仅释放本次 generation，不 save；force 仍受 preflight 限制 |
| R-07 | PASS | CLI 与 ControlService 直接返回同一 ownership/plan schema |
| E-01 | PASS | tom7r Linux `flock` + Python sidecar，v1 文本保持 `client@epoch@generation` |
| E-02 | PASS | tom7r 临时目录双实例 handoff；测试目录已删除 |
| E-03 | PASS（隔离自动化） | duplicate writer fixture 阻止 commit；未触碰真实 Agent 进程 |
| E-04 | PASS（状态模拟） | heartbeat/attached/progress 独立；未锁定用户当前桌面 |

## 结论

- API 代码完成并已通过 PR #28 合并。
- 本版是奇数 API 版；不把 Ownership Web UI 冒充为已完成，UI 留到 v0.4.52。
- 无 P0/P1 代码门禁遗留；Codex/Claude 的 Client-local store 跨机器复制仍是后续协议项，本版会明确拒绝这类 handoff；真实多 Client 业务隧道切换应在发布/升级后的受控隧道上做一次非破坏 smoke。
