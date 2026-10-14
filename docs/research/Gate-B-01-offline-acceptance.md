# Gate B-01 — V1.1 正式链路集成的离线验收手册

日期：2026-10-14 · Issue #29 / 父 Issue #16 · **开发获批，未进行用户阶段验收、独立合并或生产操作**

## 提交范围

- B01：新增 opt-in 新入口 app.v11_main（单进程、单 Telegram Bot、双源 SourceSupervisor、S2 持久分发、S4 Worker、S5 回环 Web）；旧 app.main + Dockerfile/Compose 默认启动方式保持不变。升级后旧入口与新入口共享 instance_lock，只有一个新版本拥有 DB lock。**未升级旧镜像不会自动获取此锁，实机仍要审计手动停机。**
- B02：GateBTargetStore 的单事务版本化 SQLite targets.chat_id nullable 迁移，绝不生成假 Telegram chat_id；Bark/ntfy 由 Web 管理员注册为独立 target ID，初始 disabled，受保护环境引用，不存真实 URL/Key/Token。旧 Bot 的 Telegram 目标查询/计数与旧 Poller 只包含真实 chat_id；发现旧试验性非 Telegram 绑定时 fail closed。
- B03：ObservationDispatcher 手工 Prime 历史高水位，不补旧帖；对新 source_observations 按用户规则顺序持久入 S2，成功再推进游标，崩溃后重扫利用 UNIQUE(user,post,target) 去重。30 分钟 age/TTL 约束，RSS/TG 用可核实发布日期过滤长离线老内容，双来源逐目标分离、按原 S4 限流。
- 本次不能执行真实 --prepare 或 --run：V1.1 CLI 必须获得后续 VPS/生产与 Session 的独立审批。Gate B 只是脱离现有默认启动的**可离线验证的 opt-in 路径**。

## 强制闸门

1. 不操作生产 SQLite。正式迁移前必须停旧 Bot/Worker 实例，核验共享锁，并从 S6 在线 Backup API 制作并验证一致性快照；数据库与 Secret/Telethon Session 分开保存。当前 CI 全部使用临时 DB，绝不放任何真实凭据。
2. 运行入口不存在历史 Prime 或非 Telegram 目标类型不合法时直接拒绝启动；用户需要另行批准并人工执行 Prime、设置受保护环境、启用单实例。
3. 真实设备 Key 只能通过 SEEKPULSE_PUSH_<REF> 运行环境提供，HTTPS 官方主机受原 AppriseNotifier 验证；不在 PR/Issue/日志/CSV 打印原始值。Bark/ntfy URL 和自定义域名/内部网络不可由 Web 直接配置。
4. 除 S2/S4 受控任务外没有第二个消息队列；旧 FeedPoller 与新 Worker 禁止并行。普通第三方 API 确认与 SQLite commit 无法原子化，ADR-0002 的极端重复风险仍存在。
5. 即使 Gate B 离线 CI 全绿，也**不等于** S7 Gate C VPS 资源预检、Gate D 真实灰度、Gate E 48–72h 全链路稳定性或 Gate F 恢复演练获得授权。

## 双 Python 版本离线测试（不需要凭据）

- Gate B 专项 workflow 每版本运行 test_gate_b_targets、test_gate_b_dispatch、test_gate_b_runtime。
- 全量运行 S1–S6 以及 Gate B 的测试，Ruff 检查实际 Gate B 修改文件，compileall。
- GitHub G0 原上游依赖不含 FastAPI/Apprise/Telethon 时，相关仅在 GateB 工作流安装的可选 Web/新运行时集成测试可合法 skip；**不能将 skip 冒充 Gate B 专项执行通过**。

## 验收前必查

| 项目 | 预期 |
|---|---|
| 源表迁移 | 所有旧 targets.id/chat_id 保留，s2_delivery_tasks/s4_* 外键完整，无 FK orphan 或假 chat_id；失败 rollback |
| 新 Bark/ntfy | 独立 target id，chat_id NULL，默认 disabled，管理员身份隔离，密钥环境引用不泄露 |
| 旧版 Bot | 原命令、目标计数与 FeedPoller 不向 push 目标发 TG 消息；老数据和 schema 可由获批快照回退 |
| Prime | 未 Prime 绝不启动；Prime 跳过旧观察，旧未完成任务时拒绝首次 Prime |
| 崩溃恢复 | 同一用户/帖子/目标正常唯一入队；观察处理全用户后才 checkpoint；错误不跳游标 |
| 时间窗口 | RSS/TG 时间不足或 >30min 的旧消息安全跳过；不将 source observed 时间当作论坛发布 |
| 生命周期 | 用户显式 opt-in，共享锁，组件异常提前退出时所有发送循环停，回环 Web 不对外暴露 |
| 真实范围 | Telegram Session、VPS、生产 SQLite、真实通知、48–72h：NOT_STARTED / NOT_AUTHORIZED |

## 回滚

本 PR 未合并时关闭即可。未来真实数据库迁移属于独立审批：必须停服务并操作已校验快照恢复到新数据库路径；禁止直接 DROP/修补正在用的旧库或无视 WAL。最终在 Issue #29 留下精确 HEAD、CI、用户离线验收与下一步独立合并闸门。