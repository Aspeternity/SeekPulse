# ADR-0007 — Gate B：V1.1 单实例接入、正式通知目标与安全切换

日期：2026-10-14 · Issue #29 / 父 Issue #16 · **用户已批准设计与离线开发，未批准合并/生产/VPS/真实发信**

## 现状与风险

B01：app.main 仍只启动旧 FeedPoller 和 Telegram Bot；S3 双来源、S4 Worker、S5 Web 未集成。B02：S1 targets.chat_id 为 INTEGER NOT NULL，不能用假的 Telegram chat_id 伪造 Bark/ntfy 目标，S2/S4 都以 targets.id 为外键。B03：S3 已持久化 source_observations，但缺少可靠的观察→入队崩溃恢复游标；旧 Poller 与新 Worker 并行可能重复发送，切换前观察结果不能补发。B04：VPS/Session/真实通知与迁移没有授权。

## 决定

1. **旧入口保留默认**：Dockerfile、Compose、requirements.txt 不改变；app.main 继续旧流程。新 app.v11_main 作为 **显式启用**的 opt-in 单 asyncio 进程入口。新旧 Python 版本均使用相同的 Linux flock 数据库运行互斥锁，V1.1 还对规范化的现有 .session 文件获取第二把锁（不同数据库路径亦拒绝共享 Session）；但无法控制尚未升级、未实现锁的旧镜像，生产切换前必须人工确认旧实例已停止并核实 Session 独占。已升级的 legacy app.main 在看到 Gate B schema 标记后立即拒绝启动，避免因旧 delivery_history 不含 S2 sent 记录而重复通知；旧版回滚必须通过迁移前备份恢复到新数据库路径。
2. **版本化目标身份迁移**：仅在显式 opt-in V1.1 数据初始化路径，使用 SQLite 单事务安全重建 targets.chat_id 为 nullable，保存原 id/user/chat_id、索引与 S2/S4 外键；chat_id NULL 的行必须 chat_type='push'。s7_schema_meta 记录 schema 版本；PRAGMA foreign_key_check 和 rollback 为强制条件。新 push 目标没有 Telegram chat_id，新建时 disabled、在同一事务内绑定 Bark/ntfy 及大写 safe secret_ref；管理员启用时先在同一写事务内验证受保护配置存在并指向官方 HTTPS 目标，不能误启缺失或未验证的目标。正式数据库迁移须另获批准、在停止旧服务后从 S6 一致性备份中具备可回滚状态。
3. **秘钥和通道隔离**：现有 Web 管理员仅可注册自己名下 push 目标，禁止任意 URL、跨用户 ID、冒充 Telegram ID；Web/S4 数据库仅存 secret_ref，不保存通知 URL/Token/Key。真实受保护参数仅从 SEEKPULSE_PUSH_<REF> 环境名读取，受现有 AppriseNotifier 的 HTTPS 官方主机与单设备/主题约束。旧 Bot 列表、旧 Poller 和 TG 目标配额只看 chat_id 非空；S4 旧试验性“Telegram chat_id 绑 Bark”在 V1.1 新入口禁止进入 live 模式，人工重新配置，不能偷发。
4. **显式 Prime 与 durable enqueue**：新 gate_b_dispatch_state 中记录 source_observations.id 高水位。用户将来明确批准生产切换、先确认旧 Poller 停机后执行 Prime；在 Prime 之前新 runner **必须拒绝启动**。Prime 只记录历史观测高水位，不向已存在帖子补发通知。新事件按有界行数逐条读取，按已初始化/启用用户与 S4 当前规则持久 enqueue 进 S2，只有**完成该事件所有用户入队后**推进游标；进程崩溃可重新扫描，S2 任务唯一键去重。失败时 fail closed 不前进游标。
5. **年龄与恢复**：超过 30 分钟的来源观察只审计不补推；RSS 发帖时间不可靠/缺失，不可把首次观察称为论坛发帖时间。TG 历史补查需要严格按 message.date 防旧帖在长离线恢复时被当成新帖；若平台时间不可核实则安全跳过并记录来源缺口。S2 既有 lease/recover/RetryAfter、S3 独立退避、S4 每目标限流继续复用，不再造第二套任务表。
6. **单进程启动与关闭**：新的 opt-in 入口组织旧 PTB Bot **仅管理命令**、S3 RSS/可选已授权 Telethon SourceSupervisor、可靠 dispatcher、S4 DeliveryWorker、S5 回环 Uvicorn Web，生命周期由单事件循环管理、一个 Web worker、只信任本机请求、不接受代理头；任一关键前置条件缺失不得启动发送。只从受保护环境读取真实凭据，永不交互登录或在日志打印机密。本轮测试只使用 mock 和临时 SQLite，不开真实服务。
7. **不能夸大保证**：API accepted 不等于手机到达。ADR-0002 的“API 已接受但 DB 状态尚未持久提交”的极端重复风险不变；不能承诺严格 exactly-once。正式 VPS 单机性能、停机/迁移、安全快照/回滚及 48–72 小时仍分别审批。

## 本轮范围及验收

Gate B 独立分支 feat/gate-b-01-v11-runtime-cutover，Draft PR、双 Python 版本离线真实 SQLite/Web/模拟 Bot+TG/RSS/Apprise 回归；验证 schema 单事务迁移与外键、用户隔离、创建/停用/重启、旧数据不补推、source overlap 正常去重、崩溃游标恢复、TG 消息过期、双实例互斥、生命周期关闭。S1–S6 全量行为和 G0 应继续通过。当前主分支 main 36aa8a1，未获 Gate B 合并、实机、S7 最终验收、Tag/Release/部署权限。

## 回滚

Gate B PR 未合并时关闭 Draft 即可。未来如果获授权实际迁移，须先停所有实例并验 S6 快照；数据库 schema 已升级后不可盲目回滚字段、删除 WAL 或覆写源库。应在所有进程停止条件下使用获批快照恢复至 **新路径**，检查完整性，再将配置指向旧版可读恢复文件。以上均仅为未来运行方案，不是本轮执行记录。