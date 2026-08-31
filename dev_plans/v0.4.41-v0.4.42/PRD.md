# v0.4.42 PRD — 抗抖动健康检测与自动恢复

> 父版本：v0.4.41
> 起草日期：2026-08-31
> 类型：可靠性与 Web 状态版
> 范围来源：bullet 断连事故复盘与公司列装要求

## 0. 一句话目标

把 tmux、SSH、容器、Agent 与 session 变成可观测的健康状态机，并在明确授权的 tunnel 上安全、可退避、可熔断地自动恢复。

## 1. 范围与不变量

### 1.1 In-scope

- 分层 probe：tmux、transport、container、directory、Agent、session。
- 状态：healthy、suspect、degraded、recovering、attention、disabled。
- 连续三次结构性失败才自动恢复；指数退避并在五次失败后熔断。
- 每 tunnel 显式 `auto_recover` 开关，默认关闭。
- `dt health [name] --json` 与 `dt recover <name>` 管理入口。
- `dt tick` 执行观测和获锁后的恢复状态机。
- 远端 OpenCode session 缺失时，从本地已同步 persist JSON 导入宿主机/容器。
- Web 展示缓存健康状态；不在浏览器轮询中直接执行 SSH probe。

### 1.2 Out-of-scope

- 仅因输出长期不变化而重启 Agent；正常空闲与 freeze 不能可靠等价。
- 自动猜测容器名或工作目录。
- Codex/Claude 原生 session import/resume，顺延后续版本。
- 常驻秒级 daemon；本版沿用分钟 tick。

### 1.3 不变量

- 单次网络抖动不得触发恢复。
- 无 Hub 所有权不得恢复或改写现场。
- probe/恢复失败不得清空 session ID、覆盖最后健康工作点或删除 persist JSON。
- 本地模式不产生 SSH 调用。
- Web 只读健康缓存，不因刷新页面触发远端副作用。
- 运行时数据不进入 Git；Web 变更执行浏览器 E2E。

## 2. 状态机

```text
healthy --1 fail--> suspect --3 fails--> degraded
                                      ├─ disabled: 保持 degraded
                                      └─ enabled + owned --> recovering
recovering --success--> healthy
recovering --failure--> degraded + next_retry_at
5 failures --> attention + circuit_until
```

退避为 60、120、300、600、1800 秒；tick 本身提供自然抖动。健康一次即清零连续失败，但恢复尝试计数只在真正验证健康后清零。

## 3. Probe 合同

每层返回 `ok/status/detail`，总状态只依据结构性条件：tmux 是否存在、当前 pane 是否是预期 Agent/transport、SSH 是否可达、容器是否运行、目标目录是否存在、数据库是否包含 session。

## 4. 恢复合同

恢复前 claim Hub lock。远端按 SSH → container → directory → session import → pane reconnect → Agent resume → 再 probe 的顺序执行。本地按 persist import → Agent resume → 再 probe 执行。

## 5. 风险登记

| ID | 严重度 | 风险 | 缓解 | 责任人 |
|---|---|---|---|---|
| R1 | high | 把正常空闲误判为 freeze | 不以画面静止触发自动恢复 | PM |
| R2 | high | 双 Client 同时恢复 | 恢复前强制 Hub ownership gate | Coder |
| R3 | high | 向错误容器导入 session | 只使用已记录容器名并先验证 running | Coder |
| R4 | high | 重试风暴 | 三次失败门槛、指数退避、五次熔断 | Tester |
| R5 | medium | tick SSH 探测耗时 | 仅检查 live/auto-enabled tunnel，短超时，Web 读缓存 | Coder |

## 6. 签名

Agent-PM-v0.4.42
