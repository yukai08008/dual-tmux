# v0.4.49 TEST_CASES — 运行时修复与 Session 快照收敛

## 0. 发布门禁

| ID | 用例 | 验证 |
|---|---|---|
| B-00 | 全量测试 | `uv run pytest -q` |
| B-01 | focused Ruff | `ruff check --select E9,F63,F7,F82` changed Python files |
| B-02 | 编译 | `python -m compileall -q src` |
| B-03 | 构建 | `uv build` |
| B-04 | 版本一致性 | wheel metadata、`dual_tmux.__version__`、CLI 均为 0.4.49 |
| B-05 | 运行时数据不入 Git | `git ls-files data/` 为空 |

## 1. Snapshot convergence

| ID | 用例 | 自动化 |
|---|---|---|
| S-01 | payload revision 优先于文件 mtime | `tests/test_persist_sync.py` |
| S-02 | 同 revision 不同 tail 返回 `snapshot_conflict` | `tests/test_persist_sync.py` |
| S-03 | 同 ID 本地旧副本备份、导入并验证尾消息 | `tests/test_persist_sync.py` |
| S-04 | 本地 revision 较新时禁止降级 | `tests/test_persist_sync.py` |
| S-05 | 非祖先的新 snapshot fail closed | `tests/test_persist_sync.py` |
| S-06 | `dt pull` 同步 OpenCode/tmux persist | `tests/test_config_modes.py` |
| S-07 | persist 重叠等待，SSH/rsync 失败可见 | `tests/test_persist_sync.py` |
| E-01 | OUC→Home 恢复 1052 条消息并验证尾问答 | 2026-09-05 已通过 |

## 2. Trigger workdir

| ID | 用例 | 自动化 |
|---|---|---|
| W-01 | 新 pane 以请求的 ops cwd 创建 | `tests/test_enter_workdir.py` |
| W-02 | 错误 cwd 的空闲 shell被安全纠正 | `tests/test_enter_workdir.py` |
| W-03 | 前台 Agent/其他程序保持不变 | `tests/test_enter_workdir.py` |
| W-04 | enter 在 discover/attach 前建立 workdir | `tests/test_enter_workdir.py` |
| E-02 | `dt-cp-gate` pane/op_point 均为专属 ops 目录 | 2026-09-06 已通过 |

## 3. Freeze runtime authority

| ID | 用例 | 自动化 |
|---|---|---|
| F-01 | live SSH 覆盖 docker-only scrollback | `tests/test_store.py` |
| F-02 | 仅识别交互式远端 docker exec | `tests/test_store.py` |
| F-03 | 探测失败不提交候选 runtime | `tests/test_agentclient.py` |
| F-04 | 验证成功后提交 live runtime/session | `tests/test_agentclient.py` |
| F-05 | partial freeze 保存成功 side、返回失败并记录事件 | `tests/test_agentclient.py` |
| E-03 | `dt-cp-gate` live SSH+container freeze 到真实 session | 2026-09-06 已通过 |

## 4. 发布后验证

| ID | 用例 | 预期 |
|---|---|---|
| D-01 | GitHub Release 资产 | wheel + sdist 可下载且版本为 0.4.49 |
| D-02 | 本机 `dt upgrade` | 从 0.4.48.post6 升级到 0.4.49 |
| D-03 | 升级无损 | config 与全部 tunnel SHA-256 不变 |
| D-04 | 服务状态 | daemon/mailbox worker 正常，`dt tick` 成功 |
