# v0.4.53 Codex / Claude Native Session Runtime 方案

## 方案

以冻结 UUID 为唯一 allowlist，从 Codex/Claude 原生 store 精确定位一个 JSONL，写入：

```text
~/sessions/native/<source>/<tool>/<uuid>/
  active.json
  revisions/<sha256>/manifest.json
  revisions/<sha256>/payload/<native-relative-path>.jsonl
```

Hub 保持现有租户隔离：`~/<user>/sessions/native/...`。manifest 保存 schema、tool、
UUID、source Client/instance、generation、冻结 cwd、Agent 版本、文件大小与 SHA-256。

## 安全规则

- 不复制认证、全局配置、skills、索引或其他 session。
- JSONL、manifest 与目录 UUID 必须一致；active/revision manifest 必须一致。
- identical 幂等；snapshot 是 local 的 append-only 后继时先备份再替换；local 更新时不降级；分叉拒绝。
- staging 校验完成后原子 rename；generation 在 commit 前后复核，后验失效时回滚。
- handoff 严格执行 export → Hub sync → park → ack → release；任何 persist 失败不放 lease。
- 最终仍由 Ownership writer probe 验证 trigger/bullet 各有且只有一个 writer。

## 兼容

OpenCode 路径不变。v0.4.51 老 owner 会明确拒绝 native handoff；lease 过期后即使新
Client claim，缺 snapshot 也会在启动 writer 前失败并释放新取得的 generation。
