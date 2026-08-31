# v0.4.40 TEST_CASES — Agent Adapter 与统一控制内核

## 0. 不变量回归

| ID | 范围 | 命令 |
|---|---|---|
| B-01 | 全量 Python 回归 | `pytest` |
| B-02 | 语法与导入 | `python -m compileall -q src tests` |
| B-03 | 构建 | `python -m build` |
| B-04 | 运行时数据不追踪 | `git ls-files data/` |

## 1. Agent Adapter

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| A-01 | 三种 adapter 均可按规范名和别名查找 | A1 | pytest |
| A-02 | OpenCode 声明现有完整能力 | A1 | pytest |
| A-03 | Codex/Claude 声明 metadata freeze，但不声明 session resume | A1 | pytest |
| A-04 | 能力矩阵可安全 JSON 序列化 | A1 | pytest |

## 2. ControlService

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| C-01 | operation catalog 包含风险、surface、审计事件和所需能力 | A2 | pytest |
| C-02 | list/get/send 返回统一 ControlResult | A2 | pytest |
| C-03 | 未知 tunnel/side 转成结构化 ControlError | A2 | pytest |
| C-04 | freeze/resume/model 调用既有稳定实现 | A2/A3 | pytest |

## 3. CLI/Web

| ID | 用例 | → acceptance | 自动化 |
|---|---|---|---|
| W-01 | `/api/capabilities` 返回三客户端矩阵 | A3 | HTTP pytest |
| W-02 | `/api/operations` 返回控制操作目录 | A3 | HTTP pytest |
| W-03 | Web freeze/resume/model/send 通过控制服务 | A3 | pytest |
| E-01 | Dashboard/Tunnels/Guide/Skills 及新 API 浏览器冒烟 | A4 | browser E2E |

## 4. 发布验证

| ID | 用例 | → 部署检查 |
|---|---|---|
| D-01 | wheel/sdist 安装后 `dt --version` 为 0.4.40 | Release |
| D-02 | GitHub Release 资产可访问 | Release |
| D-03 | 已安装 0.4.39 执行 `dt upgrade` 到 0.4.40 | Upgrade |
| D-04 | 升级前后本地配置与 tunnel 文件哈希不变 | Safety |
