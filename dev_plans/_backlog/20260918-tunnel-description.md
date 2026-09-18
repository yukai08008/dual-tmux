# BL-LS-001：`dt ls` 增加隧道语义描述（description 字段）

## 背景

存量隧道已 10+ 条（DST 为主），`dt ls` 目前只有 DT / IS_DST / op / run / trigger / bullet 六列（`ui.py print_ls`），全是机器标识（会话名、模型、session id 短码），没有一条人类可读的"这条隧道是干嘛的"。语义目前只能靠隧道名猜（dt-news-analysis 可猜，dt-alex-serp / dt-company_intro_v2 靠记忆），跨机器、跨人交接时更差。用户需求：`dt ls` 时多一个简短描述，帮助理解隧道对应语义。

## 需求（草案，立项时可调整）

- 注册表新增可选字段 `description`（string，一句话语义，建议 ≤60 字符）：
  - `dt new` 增加 `--desc "..."`，创建时写入。
  - 新命令 `dt desc <dt> "..."` 设置/更新（存量隧道一次性补录走这里）；无描述文本时打印当前值。实现沿 `dt model`（apply_model）的 load → 变更 → `store.save` 既有模式，零新增写路径。
- 展示：
  - `dt ls` 新增 DESCRIPTION 列（空显示 `—`，超长截断 + dim 样式，保证表格不破版）。
  - Web 隧道列表/详情同步展示（`list_tunnels` 返回原始 JSON dict，字段自然流到 `/api`，前端补渲染）。
  - 飞书 `/dt ls` 为可选（P2）。
  - `dt show` 无需改动（全量 JSON 自带）。
- 模型层补全：`datanode/adapters.py from_legacy_tunnel`（L109）把字段白名单进 TunnelNode，需增补可选 `description`（默认 ""），避免强类型层信息丢失。
- Hub 同步零改动：tunnels/*.json 整文件 push/pull/merge，description 搭车；它不是并发写热点，整文件 last-write-wins 语义可接受。

## 红线

- **tick/daemon 回写不得丢字段**：注册表的 trigger/bullet/model 等字段会被会话真相同步覆盖写回（2026-09-18 模型批量切换事故实证：活跃会话的模型经 tick 回写注册表）。必须逐个 save 点核实回写是"加载后改键"而非"重建 dict"，`description` 在所有路径下存活。
- 旧隧道 JSON 完全兼容：字段缺失时读取、升级、同步全部无感（`record.get("description")` 语义）。
- CLI 契约零破坏：只增不改（新增 `desc` 动词 + `new --desc` 选项），`cli_contract.py` 快照增量更新并随卡评审。
- 描述是元数据不是控制面：任何代码不得因 description 存在/缺失改变隧道行为。

## 验收

- `dt new --desc` 创建的隧道与 `dt desc` 补录的存量隧道，`dt ls` 均正确显示描述列；未设置描述的老隧道显示 `—` 且无告警。
- 对一条有描述的隧道跑真实 tick/daemon 周期与 `dt model` 变更后，description 仍在（`dt show` 可见）。
- push/pull 到 Hub 后对端 `dt ls` 能看到同一描述。
- 全量 pytest 零回归（新增 set/display/截断/回写存活用例）；CLI 契约快照测试通过。
