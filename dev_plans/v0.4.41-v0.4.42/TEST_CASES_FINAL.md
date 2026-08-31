# v0.4.42 TEST_CASES FINAL

> 执行日期：2026-08-31
> 结果：PASS

## 质量门

| 范围 | 结果 | 证据 |
|---|---|---|
| 全量回归 | PASS | `pytest -q`：103 passed |
| 编译 | PASS | `python -m compileall -q src tests` |
| 新增代码 lint | PASS | recovery/runtime/tests scoped Ruff |
| 构建 | PASS | wheel + sdist 0.4.42 |
| 隔离安装 | PASS | wheel 安装后 `dt 0.4.42` |
| 运行时数据 | PASS | `git ls-files data/` 为空 |
| GitHub Release | PASS | PR #6；tag/release `v0.4.42`，wheel + sdist |
| 真实升级 | PASS | 本机 `0.4.41 → 0.4.42`；config/tunnels/entries 哈希不变 |

## Probe / 状态机 / 恢复

| ID | 结果 | 说明 |
|---|---|---|
| H-01/H-02 | PASS | 本地健康/缺失由分层 probe 覆盖 |
| H-03/H-04 | PASS | SSH 255 与容器停止严格区分 |
| H-05/R-02 | PASS | OpenCode sqlite session probe 与定向 persist import |
| S-01/S-02 | PASS | 三次失败门槛；disabled 不恢复 |
| S-03/S-06 | PASS | enabled 第三次恢复且健康清零 |
| S-04/S-05 | PASS | 60/120/300/600/1800 退避与第五次熔断 |
| R-03/R-04 | PASS | Hub ownership gate；不猜容器和目录 |

## CLI / Web / E2E

| ID | 结果 | 说明 |
|---|---|---|
| C-01/C-02 | PASS | health/recover parser、help、状态持久化 |
| W-01 | PASS | `/api/health` 单元测试确认只读缓存 |
| W-02 | PASS | Dashboard 与隧道详情显示 health/auto 状态 |
| E-01 | PASS | Codex in-app Browser 实测 Dashboard → 隧道页；console 无 error/warning |

## 不变量结论

- 单次抖动不恢复，静态 pane 不作为故障信号。
- auto recovery 默认关闭且逐 tunnel opt-in。
- 本地模式不会对远端 tunnel 发 SSH health probe。
- 失败路径不修改 session ID、persist JSON 或最后健康工作点。
- 无 P0/P1 遗留。
