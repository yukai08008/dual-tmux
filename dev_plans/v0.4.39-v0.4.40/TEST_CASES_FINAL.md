# v0.4.40 验收报告

> 执行日期：2026-08-31
> 分支：`feature/v0.4.40-control-kernel`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| Python 自动化 | 88 | 88 | 0 |
| 静态/构建门禁 | 4 | 4 | 0 |
| 浏览器 E2E 场景 | 4 | 4 | 0 |
| 发布后验证 | 4 | 1 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python 回归 | PASS | 88 passed |
| B-02 | compileall | PASS | `src`、`tests` 无语法错误 |
| B-03 | wheel/sdist 构建 | PASS | 已生成 0.4.40 两种制品 |
| B-04 | `git ls-files data/` 为空 | PASS | 无运行时数据被追踪 |
| A-01～A-04 | Adapter 注册、能力真实性、JSON 合同 | PASS | pytest 覆盖 |
| C-01～C-04 | ControlService 目录、结果、错误与旧实现桥接 | PASS | pytest 覆盖 |
| W-01～W-03 | capabilities/operations API 与共享控制入口 | PASS | 真实 HTTP + pytest |
| E-01 | Dashboard 页面 | PASS | 浏览器实测 |
| E-01 | Tunnels 页面 | PASS | 浏览器实测 |
| E-01 | Skills 页面 | PASS | 浏览器实测 |
| E-01 | Guide 页面与控制台 | PASS | 浏览器实测，无 console error/warn |
| D-01 | wheel 安装后版本 | PASS | 独立 venv 显示 `dt 0.4.40` |
| D-02 | GitHub Release 资产 | PENDING | 合并、打标并发布后验证 |
| D-03 | 真实 `dt upgrade` | PENDING | 发布后从本机 0.4.39 升级 |
| D-04 | 升级前后配置和 tunnel 哈希 | PENDING | 与 D-03 同步执行 |

## 遗留问题

- 无 P0/P1 代码遗留。
- Codex/Claude 原生 session start/freeze/resume/model 明确不在本版范围，能力矩阵返回 false，计划在 v0.4.41 实现。
- 发布后验证结果将在 Release 完成后回填，属于发布流水线验证，不改变本版功能门禁结论。
