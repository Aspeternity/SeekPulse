# SeekPulse V1.1 — 架构契约（设计，尚未实现）

## 1. 部署及运行

- 单体 Python/asyncio 进程，内含 RSS 轮询、Telethon 事件接收、Telegram 命令、持久化任务 Worker、FastAPI 单 Worker。
- 仅一个采集实例与一个运行中的相同 Telegram Session；启动互斥和一致性检查为 S2/S3 实施事项。
- 单机 SQLite WAL，短事务；数据库不可在 HTTP 发送期间保持写事务；无需 Redis、PostgreSQL、外部 Broker。
- Web 绑定宿主机回环地址，不能因公开 Web 而扩大 Session、密钥或数据库暴露面。

## 2. 数据流

`RSS | TG channel → SourceEvent → CanonicalPost → PostStore → RuleEvaluation → RoutePlan → DeliveryTasks → ChannelWorkers`

- `SourceEvent` 带来源身份、消息 ID、原始接收时间和字段来源，不应包含不必要的私人 Telegram 内容。
- `CanonicalPost` 以 NodeSeek 帖子原始 ID 唯一，来源不足时不能凭标题相似强制合并。
- `RuleEvaluation` 可明确区分 `matched`、`not_matched`、`insufficient_data`；屏蔽词与版块安全优先。
- `RoutePlan` 按用户/目标合并多规则并取对应最高优先级。
- `DeliveryTask` 使用唯一约束 `(user_id, post_id, target_id)`。收到另一来源不会再生成相同目标任务；不同目标独立记录状态。

## 3. 任务状态与失败语义

`pending → leased → sent | retry_wait | failed_permanent | suppressed | expired`

- Worker 从 SQLite 原子认领，记录租约到期及尝试次数；重启后恢复超时租约。
- API 成功返回后标记 `sent`，**不代表用户手机已显示**。
- API 成功但数据库写入前崩溃，极端情况下可能重复；不做不可实现的严格 Exactly Once 承诺。
- 用户暂停/删除规则时重新检查尚未发送的任务；网络发送中的请求无法保证撤回。
- 原则上过期保留状态供审计；恢复时优先新鲜消息，不能用旧消息淹没紧急新帖。

## 4. 来源与通知的模块化边界

- `SourceAdapter` 统一生命周期、健康状态和事件输出；拉取/推送实现可不同，**不设计通用动态代码插件加载器**。
- `NotifierAdapter` 统一配置校验、测试、发送、可重试/永久失败状态；Telegram 保留原生 SDK，Bark/ntfy 采用受限 Apprise 适配。
- 每个目标独立并发/限流/超时；紧急通道优先认领但服从平台限制；普通通道避免永久饥饿。
- 通知安全：不得允许未验证的自定义 URL 或内部网络探测；秘密不入日志/普通诊断包。

## 5. 未知数据与时间

- Telegram 消息可能没有分类或完整正文。只有满足规则所需字段才推送；不足时等待补充，而非直接绕过限制。
- 来源观察时间使用同一服务器时钟，不等于论坛发布时间；阶段 S0 验证频道实际覆盖和延迟。
- 显示真实指标口径：首次来源观察 → 通知 API 接受；无法无条件衡量手机提醒时间。

## 6. Web 与 Bot 权限

- 共用应用服务层和业务数据库，不维护两套关键词配置。
- Bot 数据保留上游的用户和目标隔离；默认仅授权管理员，额外用户按审批白名单管理。
- 首版 Web 仅管理员本人范围，无通用多租户 Web；服务器部署机密与普通运行设置分开。

## 7. 实施顺序

G0 不修改应用核心；S0 先探测验证；S1 建测试基线；S2 再以测试驱动方式进行最小必要重构，不在 G0 预先实施这些契约。
