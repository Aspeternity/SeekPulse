# S3-01：双来源只读适配、游标与健康（Issue #12）

状态：2026-10-14 用户明确批准 S3 开发；此记录属于 Draft PR 的开发说明，必须结合 PR 最新 HEAD、GitHub Actions、用户验收判断阶段是否完成。

## 交付边界

- 新增 `app/source_state.py`：同一 SQLite 中**增量**创建 `s3_source_status`、`s3_rss_seen`，不迁移/删除/重放旧 `delivery_history`，不改变 S2 `delivery_tasks`。RSS 默认启用；TG 默认关闭，必须由授权的运维入口在准备好专用账户及受保护的 Session 后显式开启。启停和健康状态分别持久化。
- `app/source_adapters.py`：只允许官方 `https://rss.nodeseek.com/` 和 `@nodeseekc`；RSS 官方帖子链接及 TG 隐藏实体链接都通过 S2 的严格 post ID 规范化。来源观测只写 S2 `CoreStore.observe()`，不排队、不真实发送通知。
- RSS 首次成功抓取只将窗口帖子 ID 原子标记为已见，不把旧帖当作新帖。后续发现新帖时**先写 CoreStore，后写 RSS checkpoint**；失败时重试是幂等的。403 暂缓至少一小时；429 使用受限 Retry-After + 退避；无已知重叠且达到 feed 条数上限时记录 `rss_window_no_overlap`，发现不合规/无法识别的条目时持久化 `rss_unrecognized_entry`，**不宣称无漏帖**。
- TG 初始化时先建立最新消息 ID 基线，不追发旧帖。NewMessage 只记观测，**绝不推进历史游标**；历史按 ID 升序补查，超过可恢复窗口立即记录 `backfill_limit` 并**不推进游标**；发现未能识别的频道消息时先记录持久警告 `tg_unrecognized_message` 再推进已完整扫描的游标，避免格式变化被静默隐藏。每批完整写入后才推进 cursor；重启可重试、跨来源同帖幂等。Session 无效返回 `auth_required`，不自动询问/记录手机号、验证码或 API Hash。
- `SourceSupervisor` 为可选的源生命周期协作层，独立处理 RSS/TG 故障，TG 初始基线后绑定限定频道 NewMessage 并再次回查关闭注册竞态。**故意未从 `app/main.py` 启动**：正式从旧 FeedPoller 切到 CoreStore 路由及投递是之后 S4/上线迁移的独立审批闸门，不能在 S3 偷偷启用两套通知。
- `app/rss.py` 新增兼容字段 `summary_known`，区分 RSS 未提供摘要与明确提供空摘要，旧 `FeedEntry` 调用保持默认值兼容；其他 legacy RSS/关键词/Bot 行为不变。
- 原 `requirements.txt` 继续严格满足 S1 上游固定版本契约；`requirements-s3.txt` 在原依赖上**另行**固定 Telethon 1.45.0，实际使用须有授权的独立专用 Session（本次 CI 不登录 Telegram）。

## CI 与离线验收

`python -m pip install -r requirements-s3.txt`
`python -m unittest discover -s tests -p 'test_s3_*.py' -v`
`python -m unittest discover -s tests -v`

- 验证首次跳过旧帖、后续正常增量、同一 RSS/TG Post ID 合并、来源字段补全与三态规则；禁用和恢复独立，危险 URL/多链接失配不误识别。
- 验证断线/超时、HTTP 403/429、有界退避、游标不跳跃、回调与回查竞争、超窗停滞警告、重启后续跑、历史数据库和任务无改动，Python 3.11/3.12。
- CI 只覆盖模拟 TG/RSS、离线临时 SQLite，不覆盖真实 Telegram Session、频率限制和手机/VPS；S0 采样工具 PR #17–#20 仍保持 Draft/未合并。

## 风险与下一阶段边界

1. TG 频道编辑/删除与真实 Session 失效/重连：需后续授权实机证据；无完整历史可用时保留 gap 标记，不能认定零漏帖。
2. RSS feed 只保留有限条目，断网超过窗口可能丢失历史数据。持续 403/429 必须尊重服务器返回，不能突破限流。
3. S2 持久化的帖子观测**不等于已经安排任务、更不等于用户已收到消息**；S4 需要原子路由/通知 Worker、规则联动、分用户独立任务和实际旧历史迁移验证。
4. 多实例采集/Session 独占、正式启动秘密管理、生产容器更新、真实双源运行与资源验收，均须单独审查；本次没有实际部署或使用 Telegram 凭据。

回滚：关闭未合并的 S3 Draft PR；main/生产未改变。未来若合并并且真的初始化 S3 表，迁移也是增量的，不能在未经批准时删除历史或原表。
