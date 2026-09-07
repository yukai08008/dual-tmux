# v0.4.54 TEST_CASES — Ownership 与安全接管 Web

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量 backend/Web | `pytest tests/ -v` |
| B-01 | 运行时数据不入 Git | `git ls-files data/ \| wc -l` == 0 |
| B-02 | 编译与构建 | `compileall` + wheel/sdist |

## 1. Cache 与合同

| ID | 用例 | 预期 | 自动化 |
|---|---|---|---|
| B-10 | 原子写入并读取 cache | facts/age/freshness 正确 | test_ownership |
| B-11 | cache 缺失/超过 180 秒 | plan fail closed | test_control |
| B-12 | GET plan 时 live snapshot 抛错 | 仍仅从 cache 返回 | test_web |
| B-13 | local-only | source local、TTL n/a、无虚假 Hub lease | test_web + Browser |

## 2. Web 面板与接管

| ID | 用例 | 预期 | 自动化 |
|---|---|---|---|
| W-10 | Lease + trigger/bullet facts | 字段独立、unknown 明示 | test_web + Browser |
| W-11 | OpenCode/Codex/Claude native 状态 | tool/session/status 正确 | test_web |
| W-12 | 页面加载/刷新/tab 切换 | 不 resume/handoff/claim | source contract + Browser |
| W-13 | safe handoff | request id 与 pending/ack/reject 可见 | test_web + E2E |
| W-14 | duplicate/unknown/conflict/stale | 普通与 force 均禁用 | test_web |
| W-15 | force | 输入全名确认；后端再次验证 | test_web + Browser |

## 3. 发布门禁

| ID | 用例 | 预期 |
|---|---|---|
| R-01 | `TEST_CASES_FINAL.md` 逐条证据 | PASS |
| R-02 | 无 P0/P1 遗留 | PASS |
| R-03 | 隔离安装版本一致 | 0.4.54 |
| R-04 | config/tunnel/session binding hash | 升级前后不变 |
| R-05 | `v0.4.54-final`、Release、真实 upgrade | PASS |
