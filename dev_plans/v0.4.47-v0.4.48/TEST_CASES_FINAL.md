# v0.4.48 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 待外部条件 | 失败 |
|---|---:|---:|---:|---:|
| 自动化/安全/构建 | 174 | 174 | 0 | 0 |
| 应用内 Browser E2E 场景 | 1 | 1 | 0 | 0 |
| 企业飞书真实 E2E | 1 | 0 | 1 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | 全量 pytest | PASS | 174 tests |
| B-01 | compileall/focused Ruff/build | PASS | sdist + wheel 0.4.48 |
| B-02 | runtime data 未追踪 | PASS | `git ls-files data/` 为空 |
| B-10~S-13 | Device Registration、空响应、加密凭据与 secret 边界 | PASS | pytest；TTL 尊重飞书返回值 |
| D-20~D-25 | daemon、WS 退避、local/Hub 单活与 mailbox 回包 | PASS | pytest；含 Hub 删除失败保留本地安装、`chat_id` 回传 |
| W-30~S-32 | Web 页面/API/QR/same-origin | PASS | pytest + Browser |
| E-40 | Browser → 官方 QR → pending status | PASS | 无 console error；官方 launcher URL；TTL 3600s；未扫码创建 App |
| E-41 | Hub WS → inbox → Client dispatch → outbox 合同 | PASS | 重复同步不重复执行；回包保留 chat_id |
| E-41a | tom7r Python 3.12 daemon 容器 build/health | PASS | 无凭据启动 `running=true`、connector=`stopped`；测试容器、镜像和临时目录已清理 |
| E-42 | 真实 Client 数据无损 | PASS | 本版验证使用隔离 `DUAL_TMUX_HOME`，未写真实 `~/.dual-tmux` |
| E-43 | 无预置 App 的企业飞书真实扫码、私聊命令与回包 | PENDING | 需要用户在飞书 App 扫描一次性 QR 并确认 |

## 遗留问题

- P1 发布门禁：E-43 尚未执行，因此当前分支可进入 CODE_COMPLETE/PR，但不得合并或创建 v0.4.48 Release。
- E-43 不需要用户提供 App ID、App Secret、verification token 或 HTTPS callback；只需扫描 dt Web 生成的飞书官方二维码并确认。成功后由 tom7r daemon 持有 WebSocket，完成 `/dt ls` 和离线 mailbox 回包验证。
