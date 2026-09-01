# v0.4.48 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 待外部条件 | 失败 |
|---|---:|---:|---:|---:|
| 应用内 Browser E2E 场景 | 3 | 3 | 0 | 0 |
| 自动化/安全/构建 | 200 | 200 | 0 | 0 |
| 企业飞书真实 E2E | 2 | 2 | 0 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | 全量 pytest | PASS | 200 tests（含 post2 版本源一致性回归） |
| B-01 | compileall/focused Ruff/build | PASS | sdist + wheel 0.4.48 |
| B-02 | runtime data 未追踪 | PASS | `git ls-files data/` 为空 |
| B-10~B-15 | bridge 摘要/路由/可靠性/验证/模式 | PASS | pytest + 隔离 mailbox |
| B-10~S-13 | Device Registration、空响应、加密凭据与 secret 边界 | PASS | pytest；TTL 尊重飞书返回值 |
| D-20~D-25 | daemon、WS 退避、local/Hub 单活与 mailbox 回包 | PASS | pytest；含 Hub 删除失败保留本地安装、`chat_id` 回传 |
| D-26~D-28 | 原子 owner、generation fencing、双容器接管、旧 owner 恢复与逐消息 fence | PASS | pytest + tom7r fault injection；generation 1 → 2，无双 active |
| D-29~D-32 | Hub bridge ownership、权限诊断和 username namespace 隔离 | PASS | pytest + tom7r 容器内真实 routes 读写探针；真实双 daemon E2E 待 E-45 |
| D-33 | 飞书重投的入口回执和 command 持久幂等 | PASS | pytest；command 消费后 receipt 仍阻止同 event 再入队 |
| D-34 | 人类可读 Markdown 卡片与纯文本 fallback | PASS | pytest；卡片拒绝后自动发送可读 text，不返回 JSON |
| D-35 | Client daemon mailbox worker、空队列轻探针与跨进程锁 | PASS | pytest；5 秒 worker，tick 兜底，busy consumer 跳过 |
| W-30~S-32 | Web 页面/API/QR/same-origin | PASS | pytest + Browser |
| W-34 | deployment 已安装时禁止另一 Web 重复扫码，统一展示 Hub 状态 | PASS | pytest；`already_installed` fail-closed |
| W-24 | pending turn 跨刷新恢复并幂等归集 | PASS | 真实 dt-portal 缺失结果恢复；刷新后 answer 不重复；无 console error |
| W-25 | 合并后 Web 状态机与飞书页冒烟 | PASS | Browser 验证 600/600/1800、durable pending、legacy reconcile、owner/generation；无 console error |
| E-40 | Browser → 官方 QR → pending status | PASS | 无 console error；官方 launcher URL；TTL 3600s；未扫码创建 App |
| E-41 | Hub WS → inbox → Client dispatch → outbox 合同 | PASS | 重复同步不重复执行；回包保留 chat_id |
| E-41a | tom7r Python 3.12 daemon 容器 build/health | PASS | 无凭据启动 `running=true`、connector=`stopped`；测试容器、镜像和临时目录已清理 |
| E-42 | 真实 Client 数据无损 | PASS | 本版验证使用隔离 `DUAL_TMUX_HOME`，未写真实 `~/.dual-tmux` |
| E-43 | 无预置 App 的企业飞书真实扫码、私聊命令与回包 | PASS | `/dt ls` 于 13:29 入队，Client `commands=1 errors=0`，response 被 WS 回传；用户确认收到完整结果 |
| E-46 | `/dt ls` 人类可读 Markdown 卡片 | PASS | tom7r `f2ea308` 真实回包；用户收到并进一步确认长卡片折叠策略 |
| E-47 | GitHub Release wheel 可发现后续稳定版本且不降级 | PASS | 官方 host/path/tag/version 校验；本机 v0.4.48 wheel 安装后 config/tunnel 哈希不变 |
| E-48 | post1 → post2 真实自升级与版本一致性 | PASS | `dt upgrade` 自动选择 post2；CLI/metadata 均为 0.4.48.post2；config/tunnel 哈希不变；mailbox worker running |

## 遗留问题

- v0.4.48 当前 deployment 发布门禁全部通过。
- E-45 双 username daemon/volume 隔离仍是公司列装门禁，进入后续列装计划；不阻断 v0.4.48 发布。
