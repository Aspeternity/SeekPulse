# ADR-0004 — S4 复用 S2 投递队列与增量目标路由配置

- 日期：2026-10-14
- 状态：已批准的 V1.1/S4 范围内实现约束；任何新的目标身份/迁移方案须单独审核
- 关联：Issue #13、ADR-0001、ADR-0002、docs/ARCHITECTURE.md

## 背景

S2 的 delivery_tasks 唯一键为 (user_id,post_id,target_id)，target_id 引用上游 targets(id)；上游 `targets.chat_id` 专供 Telegram，`app/main.py` 仍使用旧 FeedPoller。S4 必须支持每用户默认/单规则覆盖、多目标、紧急优先、独立重试与受限 Bark/ntfy，但不能未经审批重造数据库、开启真实推送或破坏旧投递历史。

## 决定及影响

1. 保留现有 users/keywords/targets/delivery_history 和 S2 的唯一投递队列，不重建主键与投递语义；`app/delivery.py` **仅新增可选** priority 和 exclude_target_ids 的 claim 过滤，以及令已租赁未发送任务安全抑制的令牌栅栏接口。既有调用不变。
2. 新增 `RouteStore` 四类职责所需的独立增量表：用户默认目标、规则路由覆盖与优先级、现有目标 ID → provider/受保护 secret 引用、目标限流冷却；所有目标/规则归属检查均使用当前用户身份，权限不可跨用户。
3. 目标集合语义：默认继承现有启用的 targets；用户明确设置空集合表示不投递；规则层可以继承默认或完整覆盖。一个目标最终采用它命中规则中最高优先级，不制造两条同目标任务。规则不足字段时交由 S2 fail-closed 三态判断。
4. **新 Bark/ntfy 目标 ID 的正式创建/旧 Telegram-only 表结构兼容是待审迁移项目。** S4 只允许将已有合法目标 ID 映射为通道用于隔离测试，禁止伪造 chat_id 或改写旧 targets 主键。S5/生产切换前须先设计并验收新的目标注册方案，不能把 S4 的原型映射当作可直接上线的完整多渠道配置。
5. 目标秘密不写 SQLite：只存如 `BARK_PRIMARY` 的引用。运行时 Resolver 在受保护配置里取实际 Apprise URL；仅允许已审官方 host（Bark api.day.app、ntfy ntfy.sh）及 **Apprise 加密 HTTPS scheme `barks://`、`ntfys://`**；明确拒绝 `bark://`、`ntfy://` 明文 HTTP 形式，禁止任意 webhook/IP/内网、重定向及自动重试。自建服务器如需要须独立审核允许列表/防 SSRF 与网络路径。
6. Worker 为有限并发单进程；一次 claim 在本轮排除正在发送及处于持久冷却的目标，允许跨目标并发；每 5 次有一次正常任务优先轮次（但不破坏平台速率要求）。HTTP 429 延长目标冷却，原任务使用 S2 有界重试并保持所有终态可审计。
7. 领取后的发送前，基于 SQLite 最新用户/关键词/屏蔽词/分类/目标重新计算路线；不匹配则以租约 token 做 `suppressed`。外部 API 调用时不保持 SQLite 写事务。API 接受 ≠ 手机显示；外部 API 接受后本地标记 sent 之前崩溃仍有极端重复风险（ADR-0002）。
8. **S4 不修改或启动** `app/main.py`、旧 FeedPoller、真实 Bot Session、部署与旧历史迁移。通知 Worker 须由未来独立批准的切换过程启用。

## 被拒方案

- 建第二套任务队列/Redis，破坏 S2 task 唯一键；
- 为 Bark/ntfy 偷偷制造负数假 chat_id，令老 FeedPoller 误发；
- 多实例争抢同一 Telegram Session 或在 SQLite 写事务期间等待外部网络；
- 允许数据库任意 URL/webhook/私网 URL 及将设备密钥写入审计/日志。

## 回滚与待验证

S4 独立 Draft PR 未合并时关闭即可回滚；未来合并后的 S4 表均为新增，旧源/旧 Bot 保持默认行为不变。S4 离线测试不能替代真实 Bark/ntfy 手机、Bot 限速、生产安全域名/IP 校验、目标身份迁移和真实 1vCPU/1GiB VPS 性能。以上独立阶段需用户另行批准。
