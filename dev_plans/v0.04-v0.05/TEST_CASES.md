# v0.05 TEST_CASES — Agent 客户端元数据

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量 Python 测试 | `uv run pytest -q` |
| B-01 | Python 编译 | `uv run python -m compileall -q src tests` |
| B-02 | 构建 | `uv build` |
| B-03 | 运行时数据未追踪 | `git ls-files data/ | wc -l` |

## 1. 采集测试

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| A-01 | 解析 `1.18.20` OpenCode 输出 | AC-1 | 是 |
| A-02 | 解析 `codex-cli 0.151.0` | AC-1 | 是 |
| A-03 | 解析 `2.1.169 (Claude Code)` | AC-1 | 是 |
| A-04 | local 收集 executable/version | AC-2 | 是 |
| A-05 | SSH 查询命令只包含白名单 Agent | AC-3 | 是 |
| A-06 | Docker 查询正确 quote 容器名 | AC-3 | 是 |

## 2. Freeze 测试

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| F-01 | OpenCode freeze 保留 session 且写 agent_client | AC-4 | 是 |
| F-02 | Codex/Claude freeze 只写客户端元数据且不伪造 session | AC-4 | 是 |
| F-03 | 采集失败写 error，不破坏已有 side | AC-4 | 是 |
| F-04 | 旧 JSON inspect 与 parser 回退正常 | AC-5 | 是 |

## 3. 部署验证

| ID | 用例 | → 部署检查 |
|---|---|---|
| E-01 | 本机三种真实 CLI 版本与采集结果一致 | 版本采集通过 |
| E-02 | 真实 tunnel freeze 后 JSON 含两侧 agent_client | freeze 固化 |
