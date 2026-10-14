# S7-03 — 真实 VPS 48–72 小时验收：空白证据表

**状态：尚未开始，暂无任何真实 VPS 观测记录。本文件只提供预先审批的收集字段。**

## A. 测试头信息（执行前必须已分别获用户批准）

| 字段 | 待填写内容 |
|---|---|
| 执行授权链接及精确范围 | NOT_AUTHORIZED |
| 主机代号（非公网地址）/系统与架构 | NOT_OBSERVED |
| 目标配置 | 1 vCPU / 1 GiB RAM；实际值 NOT_OBSERVED |
| 运行的完整 V1.1 Commit SHA / 镜像 Digest | UNKNOWN |
| 预检与集成阻断 B01–B04 | BLOCKED |
| 仅供测试的 Telegram/Bark/ntfy 接收者授权 | NOT_AUTHORIZED |
| 备份清单校验与回滚审查（不填真实路径） | NOT_STARTED |
| 测试开始 UTC / 结束 UTC / 有效小时数 | NOT_STARTED |
| 记录者、第二 AI 独立审查人 | NOT_ASSIGNED |
| 最终验收审批与发布审批 | NOT_GRANTED |

## B. 采样 CSV 数据字典（不包含任何真实记录）

时间戳统一 UTC ISO8601；建议脱敏保存到用户控制的本地位置，原始日志不入 GitHub。每 60 秒的资源快照：

\`\`\`csv
sample_at_utc,commit_sha,uptime_seconds,cpu_percent,process_rss_mib,swap_mib,disk_free_mib,db_size_mib,wal_size_mib,container_restart_count,oom_count,collector_status,notes_code
\`\`\`

每 5 分钟的来源/队列健康汇总（两个来源单独行，不包含私密 Telegram ID、标题、Token）：

\`\`\`csv
window_start_utc,window_end_utc,source_code,source_enabled,last_success_utc,retry_at_utc,last_error_code,gap_code,known_external_posts,source_observed_posts,unknown_count,queue_pending,queue_retry,queue_expired,queue_failed,queue_oldest_age_seconds
\`\`\`

经**另行授权**的真实目标通知结果，用匿名目标代号和安全错误码记录：

\`\`\`csv
first_seen_utc,api_accept_utc,source_count,anonymous_post_key,anonymous_target_key,channel,status_code,attempts,latency_ms,clock_ok,notes_code
\`\`\`

CSV 中的“status_code”是**脱敏业务状态或受限错误码**，不应保留 HTTP 请求正文、设备 key、原始帖子标题、Session 或手机号。只有存在可信回执的记录才能用于 API 接受延迟；其他任务列入失败/积压分母，不能静默丢弃。

## C. 分时段审查记录（待填）

| 窗口 | 运行有效小时数 | 双源健康与覆盖 | API 延迟样本 n / P50 / P95 | OOM/重启/错误 | 结论 |
|---|---|---|---|---|---|
| 0–4h（仅在获批灰度后） | NOT_STARTED | UNKNOWN | UNKNOWN | UNKNOWN | NOT_STARTED |
| 4–24h | NOT_STARTED | UNKNOWN | UNKNOWN | UNKNOWN | NOT_STARTED |
| 24–48h | NOT_STARTED | UNKNOWN | UNKNOWN | UNKNOWN | NOT_STARTED |
| 48–72h（如需且获批准） | NOT_STARTED | UNKNOWN | UNKNOWN | UNKNOWN | NOT_STARTED |

## D. 故障、恢复与独立交接汇总

| 案例 | 是否已单独批准实机 | 受验 SHA/证据 | 结果 |
|---|---|---|---|
| TG Session 丢失、重新授权及有界补查 | 否 | 无 | NOT_STARTED |
| RSS 超时/HTTP429、独立退避 | 否 | 无 | NOT_STARTED |
| SQLite 占锁/空间不足及安全失败 | 否 | 无 | NOT_STARTED |
| 任务租约过期/断网不补推旧帖 | 否 | 无 | NOT_STARTED |
| WAL 快照校验并恢复到**新路径** | 否 | 无 | NOT_STARTED |
| 停止单实例、恢复、回滚（不覆盖旧 DB） | 否 | 无 | NOT_STARTED |
| 第二 AI 无历史对话独立读取实时 GitHub | 仅方案获准 | 无 | NOT_STARTED |

**最终判断**：\`BLOCKED — 尚缺 G-B 正式主流程接入、非 TG 目标身份、安全迁移与独立 VPS 授权\`。任何“PASS”必须填实际运行证据、时间窗、观察者和 SHA。**禁止**复制以上空白模板冒充已经采集到证据。

请与 \`docs/research/S7-01-vps-final-acceptance-plan.md\`、\`S7-02-independent-ai-handoff.md\`、Issue #16 一起使用。