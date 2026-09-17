# 删除共识：墓碑化删除（Tombstone Deletion Consensus）

> 状态：IMPLEMENTED（v0.4.79；BL-SYNC-001 DELIVERED）
> 起草：2026-09-16 | 案例来源：dt-a 删除后在其他副本复活

## 目标

让"删除一个隧道"成为复制数据集中**带逻辑时钟的一等事实**，使所有 Client 与 Hub 最终一致地同意删除——包括离线后重新上线的副本。同时支持"删后重建同名隧道"（新时钟压过旧墓碑）。

## 背景：现行删除为什么必然复活

现行同步是显式的并集（union）语义：

- `merge_snapshot` 的 docstring 即 *"Merge ... without deletions"*——合并永不删除。
- `dt pull` / `dt push` 都是裸 rsync，无 `--delete`。
- 因此"删除"只是执行删除那一侧的本地操作 + 一次 best-effort 的 Hub 物理清理（`hub.remove_remote`）。**删除不是复制数据集里的事实**，任何仍持有旧副本的机器在下一次 `push`/`sync` 时都会把它原样推回 Hub（复活），再经 pull 流向所有机器。
- 更隐蔽的危害：已删除的隧道在本机仍被 tick 健康采样（probe 事件照发）、仍可被 `dt resume`——逻辑上已死的隧道以僵尸形态继续参与接管与同步。

dt-a 案例（2026-09-16）：Hub 侧已无 `dt-a.json`，本机副本仍在且被 tick 持续采样；本机事件里无 `dt.rm`。两侧对"dt-a 是否存在"没有共同事实。

## 设计：墓碑（tombstone）

### 存储与格式

```
~/.dual-tmux/tombstones/dt-<name>.json        # 本机
~/<user>/dual-tmux/tombstones/dt-<name>.json  # Hub
```

```json
{"schema": 1, "name": "dt-a", "deleted_at": "2026-09-16T12:00:00+08:00", "deleted_by": "tm_andy_home"}
```

- 墓碑目录与 `tunnels/` 分离：`tunnels/` 的 `dt-*.json` glob、`dt ls`、DataNode 仓储均不受影响。
- 墓碑极小，默认永久保留；doctor 提供超过 90 天的修剪（防无限累积）。

### 合并语义（merge_snapshot 扩展）

墓碑以对等记录身份参与既有的逻辑时钟比较（`updated_at`，`_copy_newer(logical_time=True)`）：

| 本机 | Hub | 结果 |
|---|---|---|
| 活记录 T1 | 墓碑 T2 ≥ T1 | 删本机活文件（事件 `sync.tombstone.applied`） |
| 墓碑 T1 | 活记录 T2 > T1 | 活记录胜出：删本机墓碑 + 删 Hub 墓碑（删后重建，`dt.new` 事件已在；v0.4.79 修正——原稿"删 Hub 活文件"与本文"墓碑作废"不变量及收敛性矛盾） |
| 只有一侧有墓碑 | | 墓碑复制到另一侧；对侧活文件按上行两条规则处理 |
| 都没有 | | 无操作 |

判定只用既有时钟字段，不引入新协议。 recreated（重建同名）天然正确：新 `dt new` 写入的 `updated_at` 晚于墓碑，合并后墓碑作废。

### 各路径改动

| 路径 | 改动 |
|---|---|
| `dt rm` | 物理清理（本机文件/ops/locks/ownership）保持现状；新增写本机墓碑 + Hub 墓碑（替代 `remove_remote` 的 tunnels 项；entries/locks/ownership 清理保留）。occupancy 被他机持有时照常删除但发 warn 事件 |
| `merge_snapshot` | 上表四条规则；墓碑目录纳入快照合并 |
| `dt push` / `dt pull` | rsync 增加墓碑目录；pull 全量后本地应用一次墓碑过滤 |
| `dt tick`（sync_best_effort） | 经 merge 自动获得墓碑语义，复活窗口收敛到一个 tick |
| `hub.remove_remote` | tunnels 项删除职责移交墓碑；locks/ownership/entries 清理保留 |
| `dt doctor` | 新增自检：陈旧墓碑修剪（>90 天）；墓碑指向的活文件不一致告警 |

### 事件

| kind | sev | 触发 |
|---|---|---|
| `dt.rm` | info | 现有，detail 增 `tombstone=true` |
| `sync.tombstone.applied` | info | 合并时墓碑删除了本侧活副本 |
| `dt.rm.recreate` | info | 墓碑被更新的活记录作废（删后重建） |

`dt log --name dt-a` 从此能回答"谁在何时删了它、哪些副本随后收敛"。

## 边界与不变量

- **收敛共识，非即时共识**：离线副本要等下一次 pull/sync 才删除。相比现状（永不收敛 + 可复活）是质变；即时全局共识需要客户端注册表与确认协议，明确不做。
- Hub 不可达时 `dt rm` 照常完成本机删除并写本机墓碑，Hub 墓碑由后续同步补写——删除从 best-effort 变为最终一致。
- 墓碑不是保护对象：不存在"墓碑不可清理"的红线；活记录时钟更高即作废。
- 既有不变量全部保持：CLI 不阉割（`dt rm` 参数不变）；local-only 模式只写本机墓碑；运行时数据不进 git。

## 与相邻机制的关系

- 逻辑时钟（`updated_at`）：复用，不新增协议字段。
- 占用（occupancy）：删除与占用解耦——他机持有 occupancy 不阻止删除（墓碑照写），但事件可见；他机下次同步删副本时自身占用状态由其自行处理。
- S14 孤儿巡检：删除不再产生"孤儿隧道"（僵尸被墓碑收敛），巡检聚焦进程层。
