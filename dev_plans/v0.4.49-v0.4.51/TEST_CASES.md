# v0.4.51 TEST_CASES — Session Ownership API

## 0. 不变量回归

| ID | 用例 |
|---|---|
| B-00 | 全量 pytest |
| B-01 | focused Ruff、compileall、build |
| B-02 | `git ls-files data/` 为空 |

## 1. Semantic activity

| ID | 用例 |
|---|---|
| A-01 | spinner/footer/token/clock 变化不改变 semantic fingerprint |
| A-02 | 面向用户的真实文本变化更新 last_semantic_change_at |
| A-03 | attached、runtime、progress 独立记录 |
| A-04 | working marker 无语义进展达到阈值后为 stalled |
| A-05 | 样本数与真实窗口准确，证据不足返回 insufficient_evidence |

## 2. Lease v2

| ID | 用例 |
|---|---|
| L-01 | 无 sidecar 的 v1 lock 可读 |
| L-02 | 同 owner renew 惰性创建 v2 sidecar，v1 文本保持兼容 |
| L-03 | 新 owner claim generation+1，旧 generation 校验失败 |
| L-04 | 陈旧 sidecar 不覆盖 v1 holder/generation |
| L-05 | handoff request/ack/reject 带 request_id 幂等 |

## 3. Ownership snapshot 与 writer

| ID | 用例 |
|---|---|
| O-01 | lease/runtime/attached/progress/writers/snapshot 字段稳定 |
| O-02 | foreign attached/working/stalled 拒绝自动接管 |
| O-03 | free 或 foreign idle+detached 产生正确 action |
| O-04 | writer probe 失败为 unknown，不当作 0 |
| O-05 | 同一 session 多 writer 返回 duplicate_writer |
| O-06 | OpenCode/Codex/Claude local/SSH/container writer probe fixtures |

## 4. Resume 与 handoff

| ID | 用例 |
|---|---|
| R-01 | `resume --plan` 不调用 claim、tmux、save 或 push |
| R-02 | claim 拒绝前后 pane 集合和 binding hash 不变 |
| R-03 | owner daemon 按 persist→park→ack→release 顺序执行 |
| R-04 | persist/park 失败不释放 lease |
| R-05 | commit/verify 失败释放新 generation且不发布 binding |
| R-06 | duplicate writer 未给显式处置时 force 仍拒绝 |
| R-07 | CLI JSON 与 ControlService 返回同一 schema |

## 5. 真实环境

| ID | 用例 |
|---|---|
| E-01 | tom7r 上 v1 lock 由 v2 Client 读取/续租，旧格式仍可读 |
| E-02 | 两台 Client 完成 request→persist→park→release→claim→verify |
| E-03 | 容器中预置重复 session writer，普通 resume 不启动第三个进程 |
| E-04 | 锁屏/无人 attached + heartbeat 场景不显示用户 active |
