# 项目状态: dual-tmux

> 最近更新: 2026-09-01 13:38 +08:00 | 更新者: Codex PM

## 状态树

### v0.4.48 (ACTIVE) — 飞书扫码 Web 与 tom7r 事件桥

- **feature/v0.4.48-feishu-web-bridge** (MERGED): PR #12 已合并，远端 main=`e1e2494`。Web QR/绑定管理、tom7r mailbox bridge、飞书 callback/event、Client 离线可靠消费、outbox 回包合同与 Docker 部署模板已完成；159 tests、Browser E2E、编译/lint/build、tom7r 容器 build/health 全绿。企业飞书真实 E2E 因缺 App 凭据/HTTPS callback 仍为 P1 发布门禁；v0.4.48 保持 ACTIVE，不创建 Release。
- **feature/v0.4.48-feishu-scan-ws** (DEVELOPING): 飞书 Device Registration、自动加密凭据、独立 `dt daemon`、local/Hub 单活 WS、mailbox 路由与回包均已实现；已集成 main 的 Web durable turn tracking hotfix。真实消息发现 Hub route ownership 回归，修复并完成 `/dt ls` 闭环前不得进入 MERGE_PENDING。
  - **issue-feishu-scan-to-create** (RESOLVED): 已移除正式路径中的 App ID/Secret/callback 配置，改为扫码自动创建 PersonalAgent；Hub 删除失败时保留本地安装。
  - **issue-feishu-hub-credential-owner** (RESOLVED): 首次真实扫码发现 `rsync -a` 保留 Client UID，Hub daemon 安全校验拒绝读取；发布后归一化为 Hub SSH 用户 ownership + 0600，tom7r WS 已 `connected`。
  - **issue-feishu-single-bot-fencing** (RESOLVED): 一个 deployment 只有一个总 PersonalAgent；本地/Hub/双 Client 接管均使用唯一实例 owner、原子 lease 与 generation fencing。重复扫码 fail-closed，Hub 状态统一展示；tom7r 双容器接管与旧 owner 恢复实测无双 active。
  - **issue-feishu-route-permission-denied** (CLOSED): Hub ownership/0700/0600 归一化、结构化错误和容器读写探针通过；2026-09-01 真实 `/dt ls` 完整回包，用户确认收到。
  - **issue-feishu-replayed-event-duplicate-ack** (CLOSED): deployment 内持久 receipt、逐级 0700 和重投拒绝探针通过；真实 `/dt ls` 只回执一次、执行一次。
  - **issue-feishu-raw-json-reply** (FIXING): 真实闭环返回 ControlResult JSON，不适合作为用户界面；改为飞书 interactive Markdown 卡片并提供可读纯文本 fallback，待真实卡片确认。
  - **issue-feishu-client-mailbox-not-consumed** (FIXING): tom7r WS 常驻但本机 0.4.46.post1 tick 不含 mailbox sync，命令永久积压；将候选版 Client daemon 提升为 5 秒确定性 worker，tick 保留一分钟兜底，三入口使用跨进程锁串行化。
- **hotfix/v0.4.48-web-durable-turn-tracking** (MERGED): pending turn 写前日志、completion 基线、页面恢复和幂等消费已合并至 main；161 tests、真实 `dt-portal` 恢复与刷新 E2E 通过。
  - **issue-web-trigger-result-not-collected** (CLOSED): 缺失的 `Grok 4.6 · 3m 0s` 结果已归集到问答区；刷新后未重复，pending 正确关闭。

### v0.4.47 (ARCHIVED) — 飞书绑定与鉴权 API

- **feature/v0.4.47-feishu-binding-api** (MERGED): PR #11 已合并至 main（`6b1d371`）；secret 边界、OAuth pairing、operator allowlist、防重放、确认与 ControlService 分发完成。奇数 API 版未单独发布，能力进入 v0.4.48。

### v0.4.46 (RELEASED) — Web 全功能控制面

- **feature/v0.4.46-web-control-plane** (MERGED): PR #10 已合并并发布；tunnel、三客户端、Hub 同步、健康恢复、配置模式、Memory、Events、Doctor 已统一落到 Web/ControlService。131 tests、浏览器 E2E、构建、隔离安装与本机 0.4.44 → 0.4.46 无损升级通过。

### v0.4.45 (ARCHIVED) — 三客户端原生会话生命周期

- **feature/v0.4.45-native-agent-lifecycle** (MERGED): PR #9 已合并；OpenCode、Codex、Claude 已建立统一 session 发现/冻结/恢复合同。奇数 API 版不单独发布，能力进入 v0.4.46。

### v0.4.44 (RELEASED) — hotfix: persisted entry authority

- **hotfix/v0.4.44-entry-authority** (MERGED): PR #8 已合并并发布；以原 tmux entry 与已登记 runtime 为远端 workpoint 权威来源，修复 SSH remote command 覆盖 host 和本机 cwd 污染展示/再次 freeze；110 tests 与真实容器 freeze 通过。

### v0.4.43 (RELEASED) — hotfix: remote freeze binding correctness

- **hotfix/v0.4.43-freeze-remote-binding** (MERGED): PR #7 已合并并发布；修复 disconnected shell 被当作远端 OpenCode、latest remote session 误绑、本机 cwd 污染远端 runtime，以及空白新 TUI 误绑同 cwd 旧 session。

### v0.4.42 (RELEASED) — 抗抖动健康检测与自动恢复

- **feature/v0.4.42-health-recovery** (MERGED): PR #6 已合并；分层 probe、状态机、显式自动恢复、远端 session import、CLI/Web 状态已发布。

### v0.4.40 (RELEASED) — Agent Adapter 与统一控制内核

- **feature/v0.4.40-control-kernel** (MERGED): PR #4 已合并；三客户端真实能力注册表、CLI/Web/未来飞书共用 ControlService、能力/操作 Web API 已发布。
  - **issue-bullet-session-cannot-resume** (CLOSED): v0.4.41 hotfix 已发布；混合工作点、跳板竞态、本地 bullet persist import 和提示符误判均已修复。

> 版本编号说明：从本版本起，L1 与实际 Python 包版本/Git 标签保持一致。以下 `v0.04`～`v0.08` 是历史内部里程碑，仅作记录，不再延续编号。

### v0.08 (RELEASED) — 本地/Hub 交互发布版

- **feature/v0.08-local-hub-ux** (MERGED): PR #3 已合并；CLI、双语文档与 Web 指南已完成，发布包版本 `0.4.39`。
- **docs/foundational-operating-modes** (MERGED): 已将纯本地模式与 Hub 同步模式提升为 README 顶层基础运行模型，补充模式对照、数据边界、切换命令与无损不变量。

### v0.07 (ARCHIVED) — Local-first API 版

- **feature/v0.07-local-first-config** (MERGED): 纯本地配置、可选 Hub、merge-before-commit 迁移事务和本地运行路径已被 v0.08 / PR #3 吸收。

### v0.06 (RELEASED) — Web 发布版

- **feature/v0.06-agent-client-web** (MERGED): PR #2 已合并，CLI/Web 已展示两侧客户端名称、版本和位置；包版本 `0.4.38`。

### v0.05 (ARCHIVED) — API 开发版

- **feature/v0.05-agent-client-metadata** (MERGED): API 能力已被 v0.06 吸收并通过 PR #2 合并。

### v0.04 (RELEASED) — 当前发布线

- 发布包版本：`0.4.37`，标签 `v0.4.37` 指向 `b392601`
- **hotfix/hub-bidirectional-sync** (MERGED)
  - **issue-local-misses-remote-tunnels** (CLOSED): minute tick 已实现无删除 merge-sync；本地与 tom7r 的 6 条隧道集合和内容哈希一致。

## 当前焦点

- 推进 `v0.4.48` 飞书扫码 Web 与 tom7r 中心事件桥，完成偶数版封板发布。

## Backlog

### Web：展示 trigger → bullet 的中间交接

- 用户向 trigger 提交需求后，trigger 会先理解、整理并改写成发给 bullet 的任务；这段中间结果具有独立价值，不应只存在于 terminal 原文中。
- 在「trigger 会话」与「bullet 会话」两个区域之间增加交接区，展示 trigger 实际发给 bullet 的任务摘要、关键约束和当前交接状态，并与 trigger 最终回复明确区分。
- 验收：内容来自真实 pane/event 增量，不由 Web 猜测；长任务和多次交接可按时间顺序查看；切换隧道或刷新后仍能恢复。

### Web：改善 terminal 高度、滚动与回看

- 增加 trigger/bullet terminal 可视区域高度。
- terminal 仅在用户已经接近底部或刚主动发送消息时自动跟随新输出；用户向上查看历史后，不得强制下滚，并提供明确的「回到底部」入口。
- 每侧至少采集并可滚动查看最近 500 行；切换 tab、轮询刷新时保持各自滚动位置。

### Web：任务生命周期自适应轮询

- 当前 Web 固定每 1.5 秒请求一次，与 `tmux-trigger` 规定的 15–30 秒轮询周期不一致，也不符合 Agent 任务通常以几十秒到数分钟完成的节奏。
- 将 terminal 画面刷新与任务完成判定解耦：活动 tab 可按较低频率刷新画面；任务判定在提交后采用 15–30 秒自适应退避，无有效增量时逐步放慢，检测到有效输出或用户主动操作时再收紧；后台/隐藏 tab 进一步降频或暂停。
- 不再用高频轮询次数推断结束；结束应依据有效 pane/event 增量及稳定窗口，长任务只显示持续时间和最近进展，不制造请求风暴。
- 参考诊断基线：P95 首包耗时 20.4 秒（警告区间）；轮次聚合延迟 124440 秒；有 30823 个步骤等待聚合。后两项应作为聚合积压信号单独呈现，不能靠提高前端轮询频率掩盖。
- 参考状态阈值：P95 首包 10–30 秒为警告、≥30 秒为严重；P95 总耗时 30–60 秒为警告、≥60 秒为严重；任意零首包或 600 秒级请求为严重；HTTP 错误率 1%–5% 为警告、≥5% 为严重；路由 P95 ≥3 秒、入口 P95 ≥2 秒为警告。诊断窗口为 30 分钟，状态优先级为 `critical > warning > unknown > healthy`。
- 验收：正常长任务的请求频率与 15–30 秒策略一致；首包与持续运行期间均可见最近进展；切换 tab 不产生突发并发轮询；完成识别延迟可控且不得再次把“仍在运行”误判为失败。

### Web：轮询时间线与核心文本提取

- 每条轮询记录必须展示采样时间、从本轮提交开始的累计耗时，以及当前/下一次轮询间隔；结束记录展示本轮总耗时。
- 每次有效轮询同时展示 trigger 原本给出的简短进展摘要，例如「bullet 仍在写文档，继续等待」，而不是只显示 `trigger 更新`、模型 footer 或 spinner。
- 重做核心文本提取：优先保留 trigger 面向用户的状态说明、trigger → bullet 的交接摘要和最终答案；过滤 TUI chrome、进度动画、工具命令回显、内部推理、系统指令残片、重复 footer 和无意义的局部文本。当前 `dt-portal` 中泄漏的 `summarize for the user concisely.` 属于应过滤的反例。
- 摘要需要按语义去重；仅 spinner 或进度条变化不得生成新的摘要记录。无法可靠提取时应明确显示「暂无新的有效摘要」，不能拿任意 pane 尾部冒充核心文本。
- 为 OpenCode/Codex/Claude 分别保留 parser/adapter 边界，并用真实 pane 快照建立 golden fixtures，至少覆盖：等待首包、调用工具、派发 bullet、长时间运行、最终完成、错误和非 auto 授权等待。
- 验收：用户只看轮询时间线即可知道「何时提交、已等待多久、trigger 认为进展到哪、下一次何时检查、最终结果是什么」；核心摘要不得出现内部推理或 TUI 噪声。

## 待办

- [x] 完成 v0.4.47 飞书绑定/鉴权 API 与安全测试
- [x] 合并 v0.4.47（不单独发布），进入 v0.4.48 Web/中心事件桥
- [x] 合并 PR #12，完成 v0.4.48 Web/中心事件桥代码与无凭据 E2E
- [x] 完成 scan-to-create、自动凭据加密、dt daemon 与 WS Connector Manager
- [ ] 完成企业飞书真实扫码、tom7r WS connected 与消息回包 E2E
- [ ] 将 v0.4.46.post1 Web progress hotfix 正向合入 main 后发布 v0.4.48

- [x] 完成 v0.4.42 三件套、health probe 与状态机
- [x] 完成远端 session import、CLI/tick/Web 接入
- [x] 完成故障注入、浏览器 E2E、PR #6、v0.4.42 发布与真实升级
- [x] 合并 PR #8、发布 v0.4.44 并完成本机真实升级
- [x] 以最初 freeze 入口恢复 dt-company_intro_v2 远端容器 session
- [x] 验证重复 freeze 后本地/Hub 权威入口不漂移且 health 全绿

- [x] 完成 v0.4.40 三件套与 Agent Adapter
- [x] 完成 ControlService 并迁移 CLI/Web 操作
- [x] 完成 88 tests、浏览器 E2E、构建与封板报告
- [x] 创建并合并 PR #4，发布 v0.4.40
- [x] 本机真实执行 `dt upgrade` 并验证数据无损
- [x] 完成 v0.4.45 三客户端原生生命周期适配并合并 PR #9
- [x] 完成 v0.4.46 Web 全功能控制面、Memory/Events/Doctor 与安全确认
- [x] 完成 131 tests、应用内浏览器 E2E、构建和隔离安装
- [x] 合并 PR #10、发布 v0.4.46 并完成本机 0.4.44 → 0.4.46 无损升级
- [x] 升级后验证配置/tunnel 哈希不变、dt-company_intro_v2 全层健康
- [x] 定位 dt-msg2 bullet 接续失败并确认 session 数据未丢失
- [x] 恢复 happy-circuit session，校正本地/中心工作点
- [x] 合并 PR #5 并发布 v0.4.41 hotfix
- [x] 本机真实升级 0.4.40 → 0.4.41，配置/tunnel 哈希不变且 bullet 保持原 session 运行

- [x] 核对本地、tom7r、另一 Client 三方数据事实
- [x] 使用显式 `dt pull` 恢复本机缺失的 4 条隧道
- [x] 完成 merge-sync 自动化测试和真实 tom7r 冒烟
- [x] Review 后将 L3 标为 RESOLVED、hotfix 标为 CODE_COMPLETE
- [x] 经用户确认后推送 hotfix 分支并校验远端 SHA
- [x] 创建 PR #1 并合并到 `main`
- [x] 打 `v0.4.37` 标签、创建 GitHub Release 并验证 `dt upgrade`
- [x] 完成 v0.05 三件套、采集器、freeze 集成与回归测试
- [x] 完成 v0.06 Web 展示、封板并发布 `0.4.38`
- [x] 完成本地模式与 Hub 切换影响评估、v0.07/v0.08 三件套
- [x] 实现纯本地初始化、无网络 Hub helper 和本地 tunnel runtime
- [x] 实现旧 Hub → 新 Hub → 配置落盘的无损迁移事务
- [x] 完成 78 tests、构建、浏览器 E2E 和真实 tom7r 哈希验证
- [x] 创建并合并 PR #3，校验远端 `main` SHA
- [x] 发布 `v0.4.39`（sdist + wheel）
- [x] 本机真实执行 `dt upgrade`：`0.4.38` → `0.4.39`
- [x] 升级后确认 Hub 模式、tom7r 配置和 `dt push` 正常

## Git 权限模式

- `pm-maintainer`：用户已明确授权做完后合并并发布；本 hotfix 通过 PR 保留审计记录。

## 案例目录

- 项目本地案例统一收录在 `cases/`，使用 `trouble/` + `solution/` 成对记录。
