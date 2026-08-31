# v0.4.45 TEST_CASES — 三客户端原生会话生命周期

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-01 | 全量 Python 回归 | `pytest -q` |
| B-02 | 运行时数据未追踪 | `git ls-files data/` |
| B-03 | 编译检查 | `python -m compileall -q src tests` |

## 1. Adapter

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| A-01 | Codex 显式 `resume UUID` 优先识别 | A1 | pytest |
| A-02 | Claude 显式 `--resume UUID` 优先识别 | A2 | pytest |
| A-03 | cwd + start time 唯一候选可绑定 | A1/A2 | pytest |
| A-04 | 旧候选或多候选不绑定 | A4 | pytest |
| A-05 | 生成的恢复命令携带同一 UUID | A1/A2 | pytest |
| A-06 | SSH 与 Docker probe quoting 正确 | A3 | pytest |

## 2. 集成

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| I-01 | freeze 保存 Codex session 与客户端版本 | A1 | pytest |
| I-02 | freeze 保存 Claude session 与客户端版本 | A2 | pytest |
| I-03 | resume 对两侧分别调用正确 adapter | A1/A2 | pytest |
| I-04 | OpenCode freeze/resume 全量回归 | A5 | pytest |

## 3. 验收报告

完成质量门后写入 `TEST_CASES_FINAL.md`。
