# v0.06 TEST_CASES — Agent 客户端版本展示

| ID | 用例 | 自动化/验证 |
|---|---|---|
| B-00 | 全量测试 | `uv run pytest -q` |
| B-01 | 编译 | `uv run python -m compileall -q src tests` |
| B-02 | 构建 | `uv build` |
| B-03 | 运行时数据未追踪 | `git ls-files data/` 为空 |
| W-01 | `_tunnels` 输出两侧 agent_client | pytest |
| W-02 | Web 页面含 client 状态条 | pytest |
| E-01 | DOM 显示 `codex 0.151.0 · local` | Browser |
| E-02 | DOM 显示 `claude 2.1.191 · docker` | Browser |
