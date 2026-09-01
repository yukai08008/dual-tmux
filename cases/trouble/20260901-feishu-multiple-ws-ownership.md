# 多 Client / 多 daemon 飞书 WS 所有权风险

## 背景

一个 dual-tmux deployment 只应使用一个总 PersonalAgent，但多台机器都可以启动 Web 或 daemon。

## 风险

- 单纯启动 Web 不会产生 WS；重复扫码却可能覆盖中心 installation。
- 旧实现中的显式 Hub role 无条件启动 connector，两个 Hub daemon 可能双活。
- 两个 daemon 共用状态文件时，standby 可能覆盖 active 的 Web 展示。
- Client 睡眠恢复后，旧实例不能凭旧身份重新抢回 WS。

## 发布影响

这是 v0.4.48 正式列装的 P1 门禁：在唯一 owner、generation fencing 和重复扫码保护完成前不得发布。
