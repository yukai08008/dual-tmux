# v0.4.47 TEST_CASES — 飞书绑定与鉴权 API

约定：B-xx = pytest；S-xx = security；E-xx = integration。

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量 Python 回归 | `uv run pytest tests/` |
| B-01 | Python 编译 | `uv run python -m compileall -q src tests` |
| B-02 | 运行时数据未追踪 | `git ls-files data/`（应为空） |

## 1. 配置与秘密

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| S-01 | 环境变量 secret 可解析且不落盘 | F-1 | pytest |
| S-02 | 0600 secret 文件可读取，0640/0644 拒绝 | F-1 | pytest |
| S-03 | 配置/状态文件不含 secret/OAuth token | F-1 | pytest |

## 2. Pairing、身份与重放

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| S-10 | state 具备足够熵，只保存摘要 | F-2 | pytest |
| S-11 | state 正常消费一次，复用、过期、未知均拒绝 | F-2 | pytest |
| S-12 | callback transport 可注入并绑定 open/union/user ID | F-2/F-3 | pytest |
| S-13 | 预配置 allowlist 拒绝不匹配身份 | F-3 | pytest |
| S-14 | event_id 首次接受、再次拒绝 | F-4 | pytest |

## 3. 命令策略与执行

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| B-20 | 支持命令被确定性解析，send 保留消息正文 | F-5 | pytest |
| S-21 | 未绑定 operator 被拒绝 | F-3 | pytest |
| S-22 | drop/rm 首次签发确认，错误/过期/复用/跨目标拒绝 | F-6 | pytest |
| S-23 | upgrade/hotfix/cron/shell/SSH/未知命令拒绝 | F-7 | pytest |
| B-24 | 每条命令调用对应 ControlService 方法 | F-5 | pytest |
| E-25 | 成功、拒绝、重放均写审计事件且不含消息/secret | F-8 | pytest |

## 4. 集成验证

| ID | 用例 | → 部署检查 |
|---|---|---|
| E-30 | 隔离 home 执行 configure → pair → callback → dispatch | API 冒烟 |
| E-31 | 执行前后既有 tunnel JSON 内容哈希一致 | 数据无损 |
