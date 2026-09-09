# 2026-09-09：所有 tmux 操作使用精确 Target

## 修复机制

1. session 级操作统一使用 `=session_name`，关闭 tmux 隐式前缀匹配。
2. pane 级操作统一使用 `=session_name:`，既精确选择 session，又保留“当前 pane”
   语义。
3. destructive fencing 先以精确 target 检查存在性，再精确 detach/kill；旧隧道
   永远不能清理名字更长的其他隧道。
4. 远端 OpenCode writer fallback 只有在对应 pane 仍是 SSH/docker/tmux transport 时
   才成立；已返回 zsh/bash 的 pane 必须报告 0 writer，使 resume fail-closed。

## 保持的不变量

- 不改变任何 tunnel、session 或 snapshot 数据格式。
- 不删除、覆盖或裁剪现有 OpenCode 消息。
- CLI 命令与原有使用方式不变。
- 独热 ownership、故障接管和“被踢端退回 shell”的行为不变；只修正它们作用的
  tmux 对象必须是完全同名目标。

