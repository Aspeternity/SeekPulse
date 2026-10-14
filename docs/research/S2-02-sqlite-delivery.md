# S2-02：SQLite 统一帖子观测与目标级持久化任务

已获用户明确 S2 阶段授权，关联 Issue #11 和已批准 ADR-0002。S2-01 规范化领域模型在 Draft PR #22；本任务使用独立 stacked Draft PR（基于 feat/s2-01-canonical-post-rules），便于在不擅自合并 main 的情况下测试相同的模型和数据库契约。

## 当前实现边界

- 新模块 app/delivery.py 的 CoreStore 只访问本地 SQLite，不发任何网络请求，不接受 Telegram Session/Token；不接线到原版轮询器。调用者必须先初始化原有 Database，再初始化新 CoreStore。
- SQLite 创建三个新业务表（canonical_posts、source_observations、delivery_tasks）和独立版本元数据，保持原 users、user_settings、targets、delivery_history、旧迁移记录不变。所有新表和索引通过 IF NOT EXISTS 建立；相同 schema version 的 init 重复运行幂等，版本不匹配时拒绝继续。**不会自动重发或自动把旧 delivery_history 转换成新任务**，因为无法证明哪个历史目标成功；未来正式迁移前须另外审查目标绑定与历史行为。
- 来源观测 (source,event_id) 在 SQLite 内唯一；多来源以 post_id 关联同一 canonical_posts。BEGIN IMMEDIATE 短事务保证来源同一事件不会插出两条记录；冲突 post_id 拒绝。检索时按观测写入顺序重新构造 Domain CanonicalPost，保留首个字段来源和首次发现时间。
- 投递任务严格唯一键 (user_id,post_id,target_id)。enqueue 只接受已观察帖子、当前用户自己启用的目标，跨用户目标整批拒绝。已创建任务不会被重复来源、第二次入队或更长 TTL 覆盖终态。同用户不同目标各自存状态；同帖后到紧急规则可将尚未认领的普通任务优先级提升为紧急，但不能重置 TTL/次数，也不能撤回已认领或已发送任务。
- 状态：pending -> leased -> sent / retry_wait / failed_permanent / suppressed / expired；retry_wait 可再次 leased。claim 使用 BEGIN IMMEDIATE、随机 lease_token、lease_until 与次数增加来防止并发 Worker 重复认领；晚到的过期 Worker token 不得覆盖新租约或已完成记录。
- 启动/每次 claim 前可恢复 lease_until 已到的租约：次数未耗尽回 retry_wait，到最大次数记 failed_permanent。过期任务转 expired 并保留审计，已 sent 不重复发送。错误只能存白名单式短代码（例如 network、http_429），不写包含 Token 的异常文本。
- 失败遵守有界指数退避，带 Retry-After 的请求以更长等待时间为准；永久失败不自动重试；超期等待立即 expired。suppress 仅撤销未认领的任务，已在发送中的 HTTP 无法撤回。检查用户和目标是否仍启用发生在认领时；**规则细节在 S4 发送前仍必须重新验证，不能仅靠这张表推断用户规则现状**。
- 写事务绝不跨 Bot/Apprise/HTTP await。SQLite 不能与外部 API 形成一个原子事务；API 成功但本机持久化 sent 之前崩溃，极端情况下重试可能重复通知，**不承诺严格 exactly once**。

## 现有实现没有解决的事项

- 实际 S3 RSS/TG 采集适配与游标、用户规则变更事务/补偿、S4 路由多规则最高优先级合并及普通任务防饿死、公网通知渠道重试/限流、S5 Web 权限、真实资源监控。以上均须分别授权。
- 该版本优先保证逻辑正确与恢复安全；首次 30min TTL 只是已批候选默认值，后续阶段根据用户实际条件再确认。尚未执行真实 VPS 或 Telegram 推送。
- 对 legacy delivery_history 采取**保留旧表、不自动导入新目标任务**的增量迁移策略；正式切换 live Poller 前必须针对旧历史、防重复补发进行单独过渡验收。

## 验收矩阵

- 1000 个同名但 ID 不同的帖子，两来源重复观测在 SQLite 保留 1000 个 post 和 2000 个唯一 source event；同一用户/目标的首次路由生成恰好 1000 条任务、第二次并发路由新增 0 条任务。
- 同帖子多目标部分成功/重试、两用户隔离、跨用户伪造目标拒绝、16 个并发入队仅创建一条、两个 Worker 抢同一任务不得双重认领。
- 重启过期租约安全恢复、旧 token 完成失败、次数耗尽永久失败、HTTP 429 Retry-After、过期审计、规则修改抑制未认领、pause/target disable 阻止后续 claim。
- 旧数据库已有投递历史时追加 schema，不更改旧行也不悄悄自动重发；在 Python 3.11/3.12 CI 跑全部新旧测试。
- **必须先验收 S2-01/02 并另行批准合并各 PR，才能进入 main；不自动开展 S3**。
