# Web trigger 语义进展检测 hotfix

## 方案

- parser 输出 `phase=running|idle|unknown` 与稳定的 `completion_id`。
- `esc interrupt` 作为 OpenCode running 的明确证据；新完成 footer 作为成功证据。
- 600 秒仅提示长任务；连续 600 秒无语义进展提示可能停滞；1800 秒提示需要关注，均不自动判失败。
- pane 离线、发送失败或明确非 auto 等确定性信号才失败。
- 非 waiting 后台刷新不再写 `trigger 更新` / `bullet 更新` 日志。

## 不变量

- 不重启或改写 tunnel/session。
- 不因 wall-clock 超时中断 Agent。
- 不把 spinner/elapsed 等纯 TUI heartbeat 当作语义进展。
