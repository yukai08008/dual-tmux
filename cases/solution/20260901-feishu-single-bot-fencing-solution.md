# 单 PersonalAgent 与 WS fencing：解决方案

## 不变量

- 每个 deployment 只有一个总 PersonalAgent，多 Client/Web 共享。
- Web 永不持有 WS；启动多个 Web 不参与 owner 竞选。
- 任一时刻最多一个 daemon 可启动 connector。

## 实现

1. local standalone 和同 Hub 多容器使用原子文件锁。
2. 双 Client 接管通过 tom7r 原子 lease 竞选，实例 owner 使用唯一随机后缀。
3. owner 变化时 generation 单调递增；恢复的旧实例保持 standby。
4. failover connector 在执行每条入站消息前重新证明 owner + generation；父 daemon 消失时 child 自行退出。
5. Hub installation 已存在时拒绝再次扫码，必须先显式解绑/更换。
6. Client failover 从 Hub 拉取同一套加密 key+ciphertext，验证后在凭据锁内原子安装。
7. active 全局状态与逐实例 candidate 状态分离，standby 不覆盖 connected。
8. `event_id` 幂等继续作为切换窗口的最后防线。

## 真实验证

- tom7r 同时启动两个候选容器：一个 connected、一个 standby。
- 停止 active 后 standby 接管，generation 1 → 2。
- 旧 active 恢复后保持 standby，锁仍归 generation 2 owner。
