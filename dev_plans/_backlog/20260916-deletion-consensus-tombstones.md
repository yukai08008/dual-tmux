# BL-SYNC-001：删除共识——隧道删除在所有副本收敛（墓碑化）

## v0.4.79 交付状态

PR #88（merge `6c40032`）+ 修复 PR #89（v0.4.79.post1，Hub 墓碑 base64 传输）；Release `v0.4.79`/`v0.4.79.post1` 已发布（Latest，35 个累积 wheel，SHA 校验一致），`dt upgrade` 验证通过。真实冒烟（tom7r，dt-tomb-smoke）：删后重建压过旧墓碑、`dt rm` 双侧墓碑、他机旧副本 pull 收敛（`sync.tombstone.applied`）、Hub 活文件经 sync 物理清理、`dt log --name` 完整时间线。任务卡：agent_issues `IS-250916234105-tombstone-consensus`。

## 背景

2026-09-16 真实案例（dt-a）：Hub 侧的 `dt-a.json` 已清理，但本机副本仍在，且被每分钟 tick 继续健康采样（probe 事件照发）。任何一次 `dt push`/`sync` 都会把本机副本重新推上 Hub（复活），再经 pull 流向所有机器——一个逻辑上已删除的隧道以僵尸形态持续参与接管与同步，本机随时可以 `dt resume dt-a`。

机制根源（详见设计文档"背景"节）：

- dt 的同步是显式并集语义（`merge_snapshot`："without deletions"；`dt pull`/`push` 裸 rsync 无 `--delete`）。
- "删除"只是执行侧的本地操作 + best-effort 的 Hub 物理清理，**不是复制数据集里带时钟的事实**。dt 已有每隧道逻辑时钟（`updated_at`）支撑 newest-wins 更新，唯独删除没有参与这套时钟。

## 需求（指向设计文档）

**权威设计：[docs/deletion-consensus.md](../../docs/deletion-consensus.md)**——存储格式、合并语义真值表、各路径改动、事件与不变量全部在此，本条目只做引导。

要点速览：

1. `dt rm` 写墓碑 `tombstones/dt-<name>.json`（`{name, deleted_at, deleted_by}`）到本机 + Hub，替代现在的 tunnels 物理清理 + best-effort 远端 rm。
2. `merge_snapshot` 让墓碑以对等身份参与逻辑时钟比较：墓碑更新 → 两侧删活文件；活记录更新（删后重建同名）→ 墓碑作废。
3. push/pull/merge 全路径携带墓碑；他机副本在下一次同步时删除，发 `sync.tombstone.applied` 事件。
4. doctor 修剪 90 天以上墓碑。

## 非目标

- 不做即时全局共识（客户端注册表 + 确认协议）。离线副本在下一次同步收敛，可接受且已在设计文档边界节声明。
- 不改变 `dt rm` 的 CLI 参数与人机交互。

## 验收

- A 机 `dt rm dt-a` 后：Hub 写入墓碑；B 机（持有旧副本）下一次 pull/sync 后本地 `dt-a.json` 删除并出现 `sync.tombstone.applied`；Hub 与 B 机均不再复活。
- 删后同名重建：新 `dt new dt-a` 的时钟压过旧墓碑，B 机合并后保留新隧道、墓碑清除。
- `dt log --name dt-a` 可完整追溯删除与各副本收敛时间线。
- Hub 不可达时 `dt rm` 本机照常完成并写本机墓碑，Hub 墓碑由后续同步补写。
