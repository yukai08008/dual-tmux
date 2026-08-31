# v0.07 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 配置与兼容 | 4 | 4 | 0 |
| 迁移事务 | 4 | 4 | 0 |
| 模式行为 | 3 | 3 | 0 |
| 部署验证 | 3 | 3 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | Full Python regression | PASS | 78 passed |
| B-01 | compileall | PASS | no syntax error |
| B-02 | runtime data | PASS | `git ls-files data/` empty |
| B-10 | Client-only initialization | PASS | no server/user serialized |
| B-11 | legacy Hub config | PASS | inferred as Hub mode |
| B-12 | partial Hub pair | PASS | rejected |
| B-13 | atomic config write | PASS | `fsync` + `os.replace` |
| B-20 | attach transaction | PASS | candidate merge before write |
| B-21 | replace transaction | PASS | old Hub then candidate Hub |
| B-22 | detach transaction | PASS | final old-Hub merge |
| B-23 | failed candidate | PASS | old config bytes unchanged |
| B-30 | local background helpers | PASS | no network calls |
| B-31 | explicit pull locally | PASS | actionable error |
| B-32 | local doctor | PASS | no SSH requirement |
| E-40 | isolated local config | PASS | local mode and workspace verified |
| E-41 | local → tom7r → local | PASS | 6 tunnels retained |
| E-42 | existing tom7r config | PASS | 6 local/remote SHA-256 pairs identical |

## 遗留问题

- Full-repository Ruff still contains historical lint debt outside this feature's scope; the new configuration test module and core config/runtime modules pass scoped Ruff checks.
- No P0/P1 issue remains.
