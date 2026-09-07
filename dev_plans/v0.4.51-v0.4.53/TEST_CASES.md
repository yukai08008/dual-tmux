# v0.4.53 TEST_CASES — Native Session Runtime

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量 Python 回归 | `uv run pytest` |
| B-01 | lint/compile/build | `uv run ruff check src tests && uv run python -m compileall -q src && uv build` |
| B-02 | runtime data 不进 Git | `git ls-files data/` 为空 |

## 1. 快照协议

| ID | 用例 | 自动化 |
|---|---|---|
| N-01 | Codex/Claude 精确 UUID，不带其他 session | `tests/test_native_persist.py` |
| N-02 | manifest/hash/UUID/truncated 校验 | `tests/test_native_persist.py` |
| N-03 | identical 幂等、append-only 更新和备份 | `tests/test_native_persist.py` |
| N-04 | divergent history fail closed | `tests/test_native_persist.py` |
| N-05 | generation 改变不 commit | `tests/test_native_persist.py` |

## 2. Ownership 集成

| ID | 用例 | 自动化 |
|---|---|---|
| O-01 | persist → native sync → park → ack → release | `tests/test_daemon.py` |
| O-02 | upload 失败不 park/release | `tests/test_daemon.py` |
| O-03 | plan 展示 native snapshot 状态 | `tests/test_ownership.py` |
| O-04 | OpenCode handoff 回归 | 全量 pytest |

## 3. 部署验证

| ID | 用例 | 结果要求 |
|---|---|---|
| E-01 | 隔离 HOME local export/import | 原 UUID 可发现 |
| E-02 | 两 Client + Hub handoff | writer=1、旧 generation 不能 commit |
| E-03 | 混合 v0.4.51 owner | 明确拒绝且无第二 writer |
