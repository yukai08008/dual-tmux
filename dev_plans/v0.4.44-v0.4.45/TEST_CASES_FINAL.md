# v0.4.45 验收报告

> 验收日期：2026-08-31
> 目标分支：`feature/v0.4.45-native-agent-lifecycle`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 全量 pytest | 125 | 125 | 0 |
| Adapter/集成专项 | 15 | 15 | 0 |
| 构建产物 | 2 | 2 | 0 |
| 不变量 | 4 | 4 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python 回归 | PASS | `uv run pytest -q`，125 passed |
| B-02 | 运行时数据未追踪 | PASS | `git ls-files data/` 无输出 |
| B-03 | 编译检查 | PASS | `uv run python -m compileall -q src tests` |
| A-01 | Codex 显式 UUID 发现 | PASS | 真实 `session_meta` 格式 fixture |
| A-02 | Claude 显式 UUID 发现 | PASS | `--resume` / `--session-id` |
| A-03 | cwd + start time 唯一关联 | PASS | 仅接受启动前 5 秒至启动后 60 秒窗口 |
| A-04 | 历史或多候选拒绝绑定 | PASS | 不回退 latest |
| A-05 | 恢复命令保持 UUID | PASS | Codex/Claude 两侧集成断言 |
| A-06 | SSH/Docker probe quoting | PASS | 容器名与 cwd 安全 quoting |
| I-01 | freeze 保存 Codex session | PASS | session/client metadata 均保留 |
| I-02 | freeze 保存 Claude session | PASS | session/client metadata 均保留 |
| I-03 | resume 按 adapter 分发 | PASS | `codex resume` / `claude --resume` |
| I-04 | OpenCode 回归 | PASS | 原 110 用例全部保留通过 |

## 构建验证

- `dist/dual_tmux-0.4.45.tar.gz`
- `dist/dual_tmux-0.4.45-py3-none-any.whl`
- 新增模块与专项测试 Ruff 检查通过。

## 遗留问题

- Codex/Claude 没有稳定公开的跨机 session import 合同；本版只恢复目标机器上确实存在的原生会话，不复制私有存储。
- Web 对三客户端的能力引导与完整操作闭环进入 v0.4.46。
