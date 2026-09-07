# v0.4.49 验收报告

> 验收日期：2026-09-07
> 发布范围：运行时修复与 Session 快照收敛

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 自动化/构建门禁 | 6 | 6 | 0 |
| Snapshot convergence | 8 | 8 | 0 |
| Trigger workdir | 5 | 5 | 0 |
| Freeze runtime authority | 6 | 6 | 0 |
| 发布后验证 | 4 | 待发布后回填 | 0 |

## 结果

| ID | 结果 | 证据 |
|---|---|---|
| B-00 | PASS | 隔离 venv，259 pytest 全部通过 |
| B-01 | PASS | 4.49 changed Python files 的 E9/F63/F7/F82 检查通过 |
| B-02 | PASS | `compileall` 通过 |
| B-03 | PASS | 生成 `dual_tmux-0.4.49.tar.gz` 与 universal wheel |
| B-04 | PASS | 隔离安装后 CLI、源码与 metadata 均为 0.4.49 |
| B-05 | PASS | `git ls-files data/` 为空；`git diff --check` 通过 |
| S-01～S-07 | PASS | `test_persist_sync.py`、`test_config_modes.py` 全部通过 |
| E-01 | PASS | 2026-09-05 Home 恢复 OUC 的 1052 条消息并验证尾问答 |
| W-01～W-04 | PASS | `test_enter_workdir.py` 全部通过 |
| E-02 | PASS | 2026-09-06 `dt-cp-gate` pane/op_point 收敛到 ops 目录 |
| F-01～F-05 | PASS | `test_store.py`、`test_agentclient.py` 全部通过 |
| E-03 | PASS | 2026-09-06 live SSH/container 取证并绑定真实 bullet session |

## 范围校正

原草案中的 Lease v2、owner handoff、semantic activity、通用 transactional resume 和 `dt ownership` 没有对应实现，已从 v0.4.49 发布范围移除并保留到 `BL-RUNTIME-001`。本报告没有将这些项目标成通过。

## 发布后验证

D-01～D-04 在 GitHub Release 与本机真实升级完成后回填；若任一失败，Release 不宣布完成并走 hotfix/回滚。
