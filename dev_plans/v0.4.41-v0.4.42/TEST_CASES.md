# v0.4.42 TEST_CASES — 抗抖动健康检测与自动恢复

## 0. 不变量

| ID | 范围 | 命令 |
|---|---|---|
| B-01 | 全量回归 | `pytest` |
| B-02 | 编译 | `python -m compileall -q src tests` |
| B-03 | 构建 | `uv build` |
| B-04 | 运行时数据 | `git ls-files data/` 为空 |

## 1. Probe

| ID | 用例 | 验收 |
|---|---|---|
| H-01 | 本地健康 DST | healthy，各层 JSON 完整 |
| H-02 | tmux 缺失 | structural failure |
| H-03 | SSH 不可达 | transport fail |
| H-04 | 容器停止 | container fail |
| H-05 | session 缺失 | session fail |

## 2. 状态机

| ID | 用例 | 验收 |
|---|---|---|
| S-01 | 单次/两次失败 | suspect，不恢复 |
| S-02 | 第三次失败且 disabled | degraded，不恢复 |
| S-03 | 第三次失败且 enabled/owned | recovering |
| S-04 | 恢复失败 | next_retry_at 按退避增长 |
| S-05 | 五次失败 | attention + circuit |
| S-06 | 健康验证 | 清零失败并回 healthy |

## 3. 恢复

| ID | 用例 | 验收 |
|---|---|---|
| R-01 | 本地 session 缺失 | import 后 resume |
| R-02 | 远端 DB 缺 session | 导入记录目标并验证 |
| R-03 | 无 ownership | 不执行恢复 |
| R-04 | 目标不明确 | fail closed，不猜容器 |

## 4. CLI/Web/E2E

| ID | 用例 | 验收 |
|---|---|---|
| C-01 | `dt health --json` | 机器可读 JSON |
| C-02 | recover enable/disable/status/now | 状态与 tunnel 设置正确 |
| W-01 | `/api/health` | 只读缓存 |
| W-02 | Dashboard/Tunnels | 显示 health status |
| E-01 | 浏览器导航与状态显示 | 无 console error |

## 5. 发布

| ID | 用例 | 验收 |
|---|---|---|
| D-01 | 独立 wheel 安装 | `dt 0.4.42` |
| D-02 | GitHub Release | wheel + sdist |
| D-03 | 真实升级 | `0.4.41 → 0.4.42`，数据无损 |
