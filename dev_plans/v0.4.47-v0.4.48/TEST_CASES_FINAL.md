# v0.4.48 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 待外部条件 | 失败 |
|---|---:|---:|---:|---:|
| 应用内 Browser E2E 场景 | 3 | 3 | 0 | 0 |
| 自动化/安全/构建 | 188 | 188 | 0 | 0 |
| 企业飞书真实 E2E | 2 | 1 | 1 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | 全量 pytest | PASS | 188 tests |
| B-01 | compileall/focused Ruff/build | PASS | sdist + wheel 0.4.48 |
| B-02 | runtime data 未追踪 | PASS | `git ls-files data/` 为空 |
| B-10~B-15 | bridge 摘要/路由/可靠性/验证/模式 | PASS | pytest + 隔离 mailbox |
| B-10~S-13 | Device Registration、空响应、加密凭据与 secret 边界 | PASS | pytest；TTL 尊重飞书返回值 |
| D-20~D-25 | daemon、WS 退避、local/Hub 单活与 mailbox 回包 | PASS | pytest；含 Hub 删除失败保留本地安装、`chat_id` 回传 |
| D-26~D-28 | 原子 owner、generation fencing、双容器接管、旧 owner 恢复与逐消息 fence | PASS | pytest + tom7r fault injection；generation 1 → 2，无双 active |
| D-29~D-32 | Hub bridge ownership、权限诊断和 username namespace 隔离 | PASS | pytest + tom7r 容器内真实 routes 读写探针；真实双 daemon E2E 待 E-45 |
| D-33 | 飞书重投的入口回执和 command 持久幂等 | PASS | pytest；command 消费后 receipt 仍阻止同 event 再入队 |
| D-34 | 人类可读 Markdown 卡片与纯文本 fallback | PASS | pytest；卡片拒绝后自动发送可读 text，不返回 JSON |
| W-30~S-32 | Web 页面/API/QR/same-origin | PASS | pytest + Browser |
| W-34 | deployment 已安装时禁止另一 Web 重复扫码，统一展示 Hub 状态 | PASS | pytest；`already_installed` fail-closed |
| W-24 | pending turn 跨刷新恢复并幂等归集 | PASS | 真实 dt-portal 缺失结果恢复；刷新后 answer 不重复；无 console error |
| W-25 | 合并后 Web 状态机与飞书页冒烟 | PASS | Browser 验证 600/600/1800、durable pending、legacy reconcile、owner/generation；无 console error |
| E-40 | Browser → 官方 QR → pending status | PASS | 无 console error；官方 launcher URL；TTL 3600s；未扫码创建 App |
| E-41 | Hub WS → inbox → Client dispatch → outbox 合同 | PASS | 重复同步不重复执行；回包保留 chat_id |
| E-41a | tom7r Python 3.12 daemon 容器 build/health | PASS | 无凭据启动 `running=true`、connector=`stopped`；测试容器、镜像和临时目录已清理 |
| E-42 | 真实 Client 数据无损 | PASS | 本版验证使用隔离 `DUAL_TMUX_HOME`，未写真实 `~/.dual-tmux` |
| E-43 | 无预置 App 的企业飞书真实扫码、私聊命令与回包 | PASS | `/dt ls` 于 13:29 入队，Client `commands=1 errors=0`，response 被 WS 回传；用户确认收到完整结果 |
| E-46 | `/dt ls` 人类可读 Markdown 卡片 | PENDING | 代码与 fallback 自动化通过；待 tom7r 部署后真实飞书确认 |

## 遗留问题

- P1 发布门禁：E-46 待真实卡片确认；通过前不得创建 v0.4.48 Release。
- E-45 双 username daemon/volume 隔离仍是公司列装门禁，但不阻断 Andy 单 deployment 的 v0.4.48 发布。
