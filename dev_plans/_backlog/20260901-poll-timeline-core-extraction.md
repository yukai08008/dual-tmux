# BL-WEB-004：轮询时间线与核心文本提取

## 需求

- 每条轮询展示采样时间、累计耗时、当前/下一次间隔和 trigger 的简短进展摘要。
- 优先保留 trigger 面向用户的状态、trigger → bullet 交接和最终答案。
- 过滤 spinner、TUI chrome、命令回显、内部推理、系统指令残片和重复 footer。
- 仅动画变化不生成摘要；无法可靠提取时显示“暂无新的有效摘要”。
- OpenCode、Codex、Claude 分别建立真实 pane golden fixtures。

## 反例

`dt-portal` 曾把 `summarize for the user concisely.` 作为核心正文展示；该类系统指令残片必须过滤。

## 验收

用户只看时间线即可知道何时提交、已等待多久、当前进展、下一次检查时间和最终结果，且摘要不含内部推理或 TUI 噪声。
