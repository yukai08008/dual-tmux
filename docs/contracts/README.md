# Public contracts

本目录保存 dual-tmux 对外接口的版本化契约快照。契约用于发现无意的兼容性变化，不替代实现代码。

## CLI v1

`cli-v1.json` 由 `dual_tmux.cli_contract.cli_manifest()` 从 argparse parser 生成，记录：

- 一级和嵌套子命令；
- positional/option 类型；
- flag、nargs、required、default 和 choices；
- 参数转换类型。

`tests/test_cli_contract.py` 会比较实时 parser 与此快照。任何差异都必须被视为公开 CLI 变更并显式评审：

1. 确认不是意外删除、改名或默认值漂移；
2. 为兼容或迁移行为补测试；
3. 只有在变更被接受后才更新快照；
4. 破坏性变化必须创建新契约版本，不能覆盖旧版本含义。

当前路线图要求六次演进始终保留 `cli-v1.json` 所覆盖的全部命令能力。

## Web API 与 Control envelope v1

`web-api-v1.json` 冻结当前旧 Web Handler 的全部 `/api/*` 方法和路径，并记录：

- 请求编码与响应形态；
- 本地/网络读写风险；
- 错误 envelope；
- 已经接入的 Control operation。

`control-envelope-v1.json` 冻结 `ControlResult` 与 `ControlError` 的最小机器字段。这里特意保留 `legacy-mixed` 和 `legacy-envelope` 标记：它们不是理想设计，而是 FastAPI 双轨迁移时必须显式消除、不能悄悄改变的现状。

`tests/test_api_contract.py` 会同时检查契约快照、运行时 result/error 字段，以及真实 `Handler` 中的路由集合。增加、删除或改造 API 时必须显式评审契约差异。

故障分类、当前可证明的失败语义以及尚未解决的机制缺口见 `docs/failure-baseline.md`。

## Agent capability v1

`agent-capabilities-v1.json` 冻结 OpenCode、Codex 和 Claude Code 当前可被真实支持的 detect/start/send/freeze/resume/model 与 location 能力。后续 adapter 迁移不得通过夸大 capability 或静默删除能力绕过测试。
