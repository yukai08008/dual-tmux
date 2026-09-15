# v0.4.75 TEST CASES — 事件体系

## 0. 不变量回归

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| B-01 | 全量测试通过 | pytest tests/ -q | pytest |
| B-02 | ruff 无告警 | ruff check src tests | ruff |
| B-03 | 旧 events.jsonl 行可读且派生 cat/sev 正确 | T-01 | pytest |
| B-04 | CLI 契约快照一致（log 新参数不破坏） | test_cli_contract | pytest |

## 1. 事件模型 v2（log.py）

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| T-01 | emit 写入 sev/cat；非法 sev/cat 回落注册表 | 行含合法字段 | pytest |
| T-02 | meta fallback：.fail→error、.reject/.stalled→warn、trigger./bullet. 前缀归类 | 规则正确 | pytest |
| T-03 | read_events 按 cat/sev 过滤（含旧行派生） | 过滤命中 | pytest |
| T-04 | 超 8MB 触发重写保留最近 20000 行 | 行数受限 | pytest |
| T-05 | KIND_META 条目完整（cat∈CATEGORIES, sev∈SEVERITIES, label 非空） | 注册表合法 | pytest |
| T-06 | 源码 emit 字面量 kind 均可被 meta 解析 | 无漂移 | pytest |

## 2. system 层采集点

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| S-01 | cmd_re 发 transport.reconnect（含 transport 分类） | kind+transport 字段 | pytest |
| S-02 | resume 管道落地失败发 reconnect.fail（sev=error） | error 事件 | pytest |
| S-03 | reconcile_remote_runtime 各状态发 transport.reconcile（warn/info） | status 字段 | pytest |
| S-04 | 模型替换成功/失败发 dt.model.ok/.fail（含 old/new） | 字段完整 | pytest |
| S-05 | acquire_for_resume 透传 plan reason 到 hub.occupancy | reason 字段 | pytest |

## 3. trigger / bullet 层采集点

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| A-01 | ControlService.send 发 trigger.send/bullet.send（preview≤60） | kind+preview | pytest |
| A-02 | ControlService.interrupt 发 *.interrupt | kind+interrupt | pytest |
| A-03 | _start_side ensure_agent 成功发 side.start.ok | kind | pytest |
| A-04 | _wait_opencode_ready 超时发 side.start.fail 后 raise | error 事件 | pytest |
| A-05 | fence_remote_bullet 清理发 bullet.fence（pids） | pids 字段 | pytest |
| A-06 | activity_evidence idle→working 发 turn/run.start；重复采样不重发 | 边沿一次 | pytest |
| A-07 | working→idle 发 turn/run.end；进入 stalled 发 .stalled(warn) | 转移正确 | pytest |
| A-08 | observe 连续失败达阈值发 trigger/bullet.probe.fail 一次 | 阈值一次 | pytest |

## 4. 展示层

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| W-01 | /api/events 接受 cat/sev 参数并过滤 | 参数生效 | pytest |
| W-02 | ControlService.events 返回行均含 cat/sev（旧行补全） | 字段补全 | pytest |
| W-03 | /events 页含筛选控件与徽章样式 | 渲染包含 | pytest |
| W-04 | 隧道详情页含 Recent events 区块 | 渲染包含 | pytest |
| W-05 | dt log --cat/--sev 过滤生效 | CLI 过滤 | pytest |

## 5. 部署验证

| ID | 用例 |
|---|---|
| D-01 | wheel 安装后 dt --version = 0.4.75 |
| D-02 | 真实隧道运行 dt tick 两次，turn/run 事件不重复 |
| D-03 | Web /events 页筛选 trigger 类别仅显示交互事件 |
