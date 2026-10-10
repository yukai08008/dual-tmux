# BL-ABC-001：abc 原生客户端（已落地）与 one-shot 派发模型（二期）

## 状态

- **一期（abc 原生客户端适配）已落地**，分支 `feat/abc-native-client`：注册表/探测/discovery/journal 快照导出导入/resume 合成/pane 解析/孤儿扫描全链路，契约快照同步再生。本机真实冒烟通过：本地 abc REPL 隧道 freeze（bullet `20261010-154957` 绑定）→ drop → resume 以 `abc --resume --journal "$HOME/.abc/sessions/<sid>.jsonl"` 确定性续跑 → 跨 drop 上下文连续（"你让我用一句话介绍我自己"）→ 同一 journal 追加（35084→38790 字节）。
- 冒烟发现并修复两处：
  - dt：resume 路径 `~` 被单引号包裹不展开（shell 语义），改 `"$/HOME/..."` 双引号形式，兼容未升级 abc。
  - abc（andybot_core `fix/journal-expanduser`）：`RunJournal`/CLI 对显式 `--journal` 路径不 expanduser，字面 `~` 在 cwd 下建假目录并以空白会话续跑。待 MR 合入。
  - 附带修复 dt 既有老 bug：macOS `ps -o command= -o etime=` 组合把 command 截断到 16 字符列宽，`agent_process` 拆成两次调用——codex/claude 在 macOS 上的 fresh-start 本地 discovery 同样受益。

## 二期：one-shot 派发模型（未排期）

### 动机

当前 bullet 模型 = 常驻 TUI/REPL + `dt send` send-keys + pane 哈希猜状态。abc 的三模式（一次性/管道/REPL）允许 bullet 改为 **每回合一个进程**：

- `echo <任务> | abc` 在 run 点执行，**进程退出即回合完成**——完成判定从 pane 文本启发式退化为进程退出码，stalled/多重写者/TUI chrome 过滤这一整层复杂度对 abc bullet 结构性消失。
- journal 即真相：回合结果读 `~/.abc/sessions/<sid>.jsonl` 的 deliverable 行，不猜 pane。
- 僵尸问题从构造上消失（无常驻进程可泄漏）；orphan 巡检对 one-shot bullet 退化为 no-op。

### 范围草案

- `dt send` 对 abc bullet 新增派发形态：向 run 点注入 `printf %s '<task>' | abc --resume --journal "$HOME/.abc/sessions/<sid>.jsonl"`（或 `--journal` + `resume-task`），记录 `bullet.send` 事件不变。
- `dt bullet` 诊断对 one-shot bullet 读 journal 尾部事实（task_goal/deliverable/llm_attempt），hint 口径不变。
- 派发锁：同一 bullet 同时只允许一个回合进程（复用 occupancy/entries 单写者语义）。
- 触发侧仍用常驻客户端；one-shot 只作用于 bullet。

### 非目标

- 不改 opencode/codex/claude bullet 的现有流程。
- 不在二期引入 abc 子代理 delegation 的跨机复制。

### 验收口径

- 长任务（数分钟）派发后 `dt bullet --json` 全程给出事实进展；完成判定与进程退出一致，无 pane 猜测。
- 断链恢复：回合中途 `docker exec` 链路死亡 → 下一轮派发前 orphan/围栏清场 → journal 回放无损。
- 多轮派发串行正确，journal 单调追加，`dt log --cat bullet` 时间线完整。
