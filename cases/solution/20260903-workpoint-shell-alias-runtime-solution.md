# shell alias 跳板导致 workpoint runtime 损坏 - 解决

> 日期：2026-09-03 | 分支：hotfix/v0.4.49-workpoint-alias-hops

## 修复

1. `sshutil.resolve_shell_alias()` 通过交互 shell 查询单个安全 alias，只接受以 `ssh` 开头的展开结果，并按进程缓存。
2. workpoint 独立记录 `ssh_cmd`，runtime 不再从混合 `resume_cmd` 推导 SSH 目标。
3. replay chain 排除同机 `cd` 与 `logout/exit`，只保留连接 hop；`docker exec` 不重复记录。
4. 进程树发现直接 SSH 时同步记录 `ssh_cmd`；单条旧式直接 SSH `resume_cmd` 继续兼容端口解析。
5. 已知 runtime 指向容器时，宿主机-only pane 观测不覆盖容器 directory。

## 真实验证

- 公网入口 `root@106.75.97.247:24500` 可访问 `alex_serp_24656`，容器 OpenCode 版本 `1.18.27`。
- 源码 legacy freeze 自动绑定 bullet：`ses_f9a099310ffevgu6ktnoIkF7Xy`，slug `calm-garden`，model `xs-grok/grok-4.6`。
- runtime 保持 `alex_serp_24656:/workspace`，重建命令包含公网 SSH 端口与 `docker exec`。
- 全量测试：245 passed, 1 warning。
