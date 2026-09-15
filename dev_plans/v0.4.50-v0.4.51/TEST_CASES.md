# v0.4.51 TEST_CASES — CLI 基线与版本化契约

约定：

- B-xx：Python 单元/契约测试
- I-xx：隔离集成测试
- E-xx：安装和真实入口冒烟

## 0. 不变量回归

| ID | 范围 | 命令/验证 |
|---|---|---|
| B-00 | 全量 Python 回归 | `.venv/bin/python -m pytest tests/ -q` |
| B-01 | 运行时数据不入 Git | `git ls-files data/ \| wc -l` 等于 0 |
| B-02 | CLI 完整性 | parser 与 `docs/contracts/cli-v1.json` 完全一致 |
| B-03 | Web 故障隔离 | `tests/test_cli_contract.py` 验证非 Web CLI 延迟导入 Web |

## 1. CLI 语法契约

| ID | 用例 | 自动化 |
|---|---|---|
| B-10 | manifest schema/program 正确 | `tests/test_cli_contract.py` |
| B-11 | 全部一级命令存在 | `tests/test_cli_contract.py` |
| B-12 | skill/feishu 嵌套命令存在 | `tests/test_cli_contract.py` |
| B-13 | flags/defaults/choices/type 稳定 | `tests/test_cli_contract.py` |
| B-14 | 意外删除或改默认值使测试失败 | mutation review |

## 2. Dispatch 与生命周期

| ID | 用例 | 自动化 |
|---|---|---|
| I-20 | 无子命令进入最新 Trigger | `tests/test_cli_lifecycle_baseline.py` |
| I-21 | local new/freeze/drop/resume | `tests/test_cli_lifecycle_baseline.py` |
| I-22 | Hub claim/release 与生命周期 | `tests/test_cli_lifecycle_baseline.py` |
| I-23 | 三种 Agent capability 不退化 | `tests/test_agents.py` + `agent-capabilities-v1.json` |
| I-24 | drop 先 detach 再 kill，使 attach 返回原 shell | `tests/test_cli_lifecycle_baseline.py` |

## 3. API 与数据

| ID | 用例 | 自动化 |
|---|---|---|
| B-30 | ControlResult 最小字段稳定 | `tests/test_api_contract.py` + `control-envelope-v1.json` |
| B-31 | ControlError code/status/detail 稳定 | `tests/test_api_contract.py` + `control-envelope-v1.json` |
| B-32 | Web API 方法/路径/读写风险清单 | `tests/test_api_contract.py` + `web-api-v1.json` |
| B-33 | config/tunnel/entry/health/memory/web-state 旧 fixture 可读 | `tests/test_legacy_data_contract.py` |

## 4. 故障回归

| ID | 用例 | 自动化 |
|---|---|---|
| B-40 | SSH timeout 返回稳定 unreachable | `tests/test_fault_baseline.py` |
| B-41 | Hub lock held 保留 holder/age/generation | `tests/test_fault_baseline.py` |
| B-42 | session missing 不猜最新会话 | `tests/test_fault_baseline.py` |
| B-43 | 部分写入抛出失败，不报告成功 | `tests/test_fault_baseline.py`；原子保旧进入 E5 |

## 5. 部署验证

| ID | 用例 | 期望 |
|---|---|---|
| E-50 | wheel 安装 | 不需要 Web/Node 即可运行 CLI |
| E-51 | `dt --version` | 退出 0，版本正确 |
| E-52 | `dt doctor` | CLI 基础检查正常 |
| E-53 | 当前用户核心工作流 | 命令和操作习惯无变化 |
