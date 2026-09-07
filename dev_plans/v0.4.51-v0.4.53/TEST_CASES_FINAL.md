# v0.4.53 验收报告

> 日期：2026-09-07  
> 分支：`feature/v0.4.53-native-session-runtime`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| Python 全量测试 | 289 | 289 | 0 |
| Native/Ownership/Handoff 自动化 | 38 | 38 | 0 |
| 隔离 Hub E2E | 1 | 1 | 0 |
| 构建/编译/diff/runtime-data 门禁 | 4 | 4 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | 全量 Python 回归 | PASS | `289 passed` |
| B-01 | focused Ruff / compileall / build | PASS | 新增与改动合同通过；wheel/sdist 0.4.53 构建成功 |
| B-02 | runtime data 不进 Git | PASS | `git ls-files data/` 为空 |
| N-01 | Codex/Claude 精确 UUID | PASS | 两工具参数化；其他 session 不进 tree |
| N-02 | manifest/hash/UUID/truncated/symlink | PASS | active 与 sealed manifest 一致性校验 |
| N-03 | identical / append-only / backup | PASS | 幂等、更新、备份均通过 |
| N-04 | divergent history | PASS | fail closed，local bytes 不变 |
| N-05 | generation fencing | PASS | commit 后 fence 失败会回滚 |
| O-01 | durable persist handoff 顺序 | PASS | export → OC sync → native sync → verify → park → ack → release |
| O-02 | 上传失败不释放 | PASS | export 和 native sync 两种失败均覆盖 |
| O-03 | plan native facts | PASS | missing/local/hub/newer/conflict/unsupported 合同 |
| O-04 | OpenCode 回归 | PASS | 全量测试通过 |
| E-01 | 隔离 HOME import | PASS | 原 UUID 可由 native parser 发现 |
| E-02 | tom7r 往返 | PASS | `andy/sessions/native/tm_e2e_20260907` 上传/下载/导入成功并已清理 |
| E-03 | 混合 v0.4.51 owner | PASS | 老 owner 按旧协议 reject；新方缺 snapshot 时启动前失败并释放 |
| E-04 | Claude 跨 cwd UUID 查找 | PASS | 隔离 HOME 中仅放来源 cwd JSONL，在另一 cwd 执行 `--resume UUID` 未报 not-found 并进入请求阶段后主动中止 |

## 真实客户端基线

- Codex CLI `0.151.0`
- Claude Code `2.1.169`
- tmux `3.6a`

## 遗留问题

- 未启动用户真实 Codex/Claude session 做在线 writer E2E，避免污染当前会话；exact resume argv 与 writer probe 已由自动化覆盖。
- v0.4.54 Ownership Web 需消费 `native_snapshots` 状态并完成浏览器 E2E。
