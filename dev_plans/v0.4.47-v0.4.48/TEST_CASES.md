# v0.4.48 TEST_CASES — 飞书扫码 Web 与 tom7r 事件桥

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-00 | 全量回归 | `uv run pytest tests/` |
| B-01 | 编译/lint/build | `compileall`、focused Ruff、`uv build` |
| B-02 | 运行数据未追踪 | `git ls-files data/` 为空 |

## 1. Bridge

| ID | 用例 | 验收 | 自动化 |
|---|---|---|---|
| B-10 | state/identity 只注册摘要 | W-5 | pytest |
| B-11 | callback 按 state 投递正确 Client | W-3 | pytest |
| B-12 | sender 三类 ID 任一匹配路由 | W-3 | pytest |
| B-13 | inbox 原子写、重复 event 只执行一次 | W-4 | pytest |
| S-14 | verification token 错误拒绝，challenge 正确 | W-6 | pytest |
| B-15 | local-only 不联网；新 Hub 可重注册 | W-7 | pytest |

## 2. Web

| ID | 用例 | 验收 | 自动化 |
|---|---|---|---|
| W-20 | 飞书导航/页面/配置/绑定/解绑 API | W-1 | pytest |
| W-21 | pair 返回本地生成 QR data URI、URL 和 TTL | W-2 | pytest |
| S-22 | Web POST 跨 Origin 继续拒绝 | W-1 | pytest |
| W-23 | 页面轮询 status 并可触发 bridge sync | W-2/W-3 | Browser |

## 3. E2E/发布

| ID | 用例 | 验收 |
|---|---|---|
| E-30 | 隔离 Web 配置 → QR → callback → 已绑定 → unbind | W-8 |
| E-31 | 隔离 bridge command inbox → Client dispatch → outbox | W-3/W-4 |
| E-32 | 真实升级前后 config/tunnel 哈希一致 | W-7 |
| E-33 | 企业 App 真实扫码与飞书命令 | 正式推广前必补；凭据未提供则登记遗留 |
