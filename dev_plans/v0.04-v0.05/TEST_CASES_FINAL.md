# v0.05 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 不变量回归 | 4 | 4 | 0 |
| 客户端采集 | 6 | 6 | 0 |
| Freeze 集成 | 4 | 4 | 0 |
| 真实环境 | 2 | 2 | 0 |

## 逐条结果

| ID | 结果 | 备注 |
|---|---|---|
| B-00 | PASS | 66 pytest tests passed |
| B-01 | PASS | compileall passed |
| B-02 | PASS | sdist + wheel build passed |
| B-03 | PASS | `data/` tracked count = 0 |
| A-01~A-06 | PASS | 三种格式、本地、SSH、Docker 与白名单均覆盖 |
| F-01~F-04 | PASS | OpenCode session 保留；Codex/Claude 无假 session；旧 JSON 兼容 |
| E-01 | PASS | 本机：OpenCode 1.18.20、Codex 0.151.0、Claude 2.1.169 |
| E-02 | PASS | tom7r 容器：OpenCode 1.18.25、Codex 0.141.0、Claude 2.1.191 |

## 遗留问题

- Codex/Claude session resume 未实现，符合本版 Out-of-scope。
- Web 展示转入 v0.06 双数版。
