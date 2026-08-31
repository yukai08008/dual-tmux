# v0.4.46 TEST_CASES — Web 全功能控制面

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-01 | 全量 Python | `uv run pytest -q` |
| B-02 | 浏览器 E2E | 本地 `dt web --no-open` 实测 |
| B-03 | 运行时数据 | `git ls-files data/` 为空 |

## 1. ControlService

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| C-01 | create/remove/reconnect/drop | A1 | pytest |
| C-02 | freeze/resume/send 三客户端 | A2 | pytest |
| C-03 | push/pull/config mode | A3 | pytest |
| C-04 | health probe/recover/auto | A4 | pytest |
| C-05 | 高风险操作缺确认被拒绝 | A1/A3/A4 | pytest |

## 2. HTTP/Web

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| W-01 | GET API 无副作用 | A5 | pytest |
| W-02 | POST 映射结构化结果与错误 | A1-A4 | pytest |
| W-03 | capability 驱动按钮状态 | A5 | pytest/E2E |
| W-04 | 创建到删除浏览器闭环 | A6 | Browser |
