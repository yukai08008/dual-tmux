# v0.4.46 验收报告

> 验收日期：2026-08-31
> 目标分支：`feature/v0.4.46-web-control-plane`

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| 全量 pytest | 131 | 131 | 0 |
| Control/Web 新增自动化 | 8 | 8 | 0 |
| 浏览器 E2E 场景 | 4 | 4 | 0 |
| 构建产物 | 2 | 2 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-01 | 全量 Python | PASS | 131 tests collected / all pass |
| B-02 | 浏览器 E2E | PASS | 应用内浏览器，真实 stdlib Web server |
| B-03 | 运行时数据 | PASS | `git ls-files data/` 无输出 |
| C-01 | create/remove/reconnect/drop | PASS | remove/drop 强制确认合同 |
| C-02 | 三客户端 freeze/resume/send | PASS | capability 与 v0.4.45 adapter 共用 |
| C-03 | push/pull/config mode | PASS | 模式切换复用 merge-before-commit |
| C-04 | health probe/recover/auto | PASS | GET 仍只读缓存 |
| C-05 | 高风险确认 | PASS | remove、drop、force recover、mode switch |
| W-01 | GET 无副作用 | PASS | config/health/memory/events 均为只读路径 |
| W-02 | POST 结构化结果 | PASS | ControlResult/ControlError |
| W-03 | capability 驱动 UI | PASS | 非 OpenCode 隐藏 auto、禁用模型切换 |
| W-04 | 浏览器管理闭环 | PASS | 隔离 local-only home 创建 Codex/Claude tunnel、核对双 pane、运行 health；临时数据移入废纸篓 |

## 浏览器实测证据

- 在隔离 `DUAL_TMUX_HOME` 中通过页面创建 `dt-web-e2e`。
- 持久记录为 trigger=`codex`、bullet=`claude`、runtime server 为空、directory=`/tmp`。
- `op_web_e2e` 与 `run_web_e2e` 两个 tmux pane 均为 live。
- Web 健康检查产生明确 layer 结果；页面没有因加载自动执行 probe。
- 最终导航包含 Dashboard、隧道、Memory、Events、Doctor、Skills、指南。
- Doctor 页面初始为“尚未运行”，只有显式点击才进行 SSH/系统检查。

## 安全门

- Web 仅监听 `127.0.0.1`。
- 跨 Origin POST 返回 `403 origin_rejected`。
- 删除要求输入精确 tunnel 名；drop 同样要求名称确认。
- 模式切换要求 UI 确认并携带 `confirm=switch-mode`。
- `upgrade`、`hotfix`、cron 安装保持 CLI-only。

## 构建

- `dist/dual_tmux-0.4.46.tar.gz`
- `dist/dual_tmux-0.4.46-py3-none-any.whl`
- 隔离 wheel 安装输出 `dt 0.4.46`。

## 遗留问题

- 飞书扫码绑定/管理仍是正式列装路线中的下一项，使用本版扩展后的 ControlService 操作目录接入。
