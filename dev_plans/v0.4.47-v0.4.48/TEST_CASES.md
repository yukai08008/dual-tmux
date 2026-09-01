# v0.4.48 TEST_CASES — 飞书扫码即用与常驻长连接

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量回归 | `uv run pytest tests/` |
| B-01 | 编译/lint/build | `compileall`、focused Ruff、`uv build` |
| B-02 | 运行数据未追踪 | `git ls-files data/` 为空 |

## 1. Registration / credentials

| ID | 用例 | 验收 | 自动化 |
|---|---|---|---|
| B-10 | registration begin 参数、QR、TTL 正确 | W-1/W-2 | pytest fake transport |
| B-11 | pending/slow_down/成功/拒绝/过期状态机 | W-2 | pytest fake transport |
| S-12 | client_secret 仅以 AEAD 密文落盘；key 为 0600 | W-2 | pytest |
| S-13 | Web/API/日志/Hub 邮箱不出现 secret/device_code | W-2 | pytest |

## 2. Daemon / WS / lease

| ID | 用例 | 验收 | 自动化 |
|---|---|---|---|
| D-20 | 无安装时 daemon 不建 WS | W-3 | pytest |
| D-21 | active 安装启动恢复；解绑停止 connector | W-3 | pytest fake connector |
| D-22 | 断线按上限退避，成功后清零 | W-3 | pytest fake clock |
| D-23 | Web 进程退出不影响独立 daemon | W-3 | process E2E |
| D-24 | local/Hub 租约单活、过期接管、fencing | W-5 | pytest |
| D-25 | event_id 重复不执行，消息通过 ControlService 回包 | W-4/W-6 | pytest fake connector |
| D-26 | 同机双 daemon 只有一个 active；租约过期后 generation 单调递增 | W-5 | pytest fake clock |
| D-27 | Hub 双实例/双 Client 竞选、断网与旧 owner 恢复不双活 | W-5 | pytest fault injection |

## 3. Web

| ID | 用例 | 验收 | 自动化 |
|---|---|---|---|
| W-30 | 页面不展示或要求 App ID/App Secret/callback | W-1 | pytest/Browser |
| W-31 | pair 返回 QR/TTL，status 展示安装和 WS 状态 | W-1/W-2 | pytest/Browser |
| S-32 | Web POST 跨 Origin继续拒绝 | W-1 | pytest |
| W-33 | 解绑需确认且停止 connector | W-3 | Browser |
| W-34 | 已存在总 PersonalAgent 时另一 Web 禁止再次扫码，并展示 Hub owner/status | W-1/W-5 | pytest/Browser |

## 4. E2E/发布

| ID | 用例 | 验收 |
|---|---|---|
| E-40 | 隔离 Web → QR → registration success → daemon connected → unbind | W-8 |
| E-41 | Hub WS → inbox → Client dispatch → outbox 回包 | W-4/W-6 |
| E-42 | 真实升级前后 config/tunnel 哈希一致 | W-7 |
| E-43 | 无预置 App 的企业飞书真实扫码、私聊命令与回包 | 正式发布硬门禁 |
