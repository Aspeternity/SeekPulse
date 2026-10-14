# S6-01 / Issue #15 — 离线可靠性、备份与恢复验收说明

状态：2026-10-14 用户「批准」开始 S6 开发，**尚未验收、合并或批准 VPS 实机部署/恢复**。

## 预期文件

- \`app/maintenance.py\`: **按需运行的离线 CLI**，命令均不给运行时注册定时任务；不触及 app.main/Web/Worker 的生产入口。
- \`tests/test_s6_maintenance.py\`: WAL 未 checkpoint 的已提交写入、恢复后 S1–S4 全表状态、SHA-256/完整性/版本、符号链接、安全权限、磁盘写满、不可覆盖/侧车文件不复用。
- \`tests/test_s6_recovery.py\`: 长时间断网和失效任务审计、租约栅栏与重启、Telegram Session 授权失效、RSS 429 和来源隔离、长期缺口、目标单独冷却、SQLite 独占锁、Web 会话重启失效。
- \`.github/workflows/s6-recovery.yml\`: Python 3.11 与 3.12 的 S6 专项和 S1–S5 全量回归、Ruff、编译。G0 保持上游固定依赖，不动原 Docker、requirements.txt。
- \`docs/decisions/ADR-0006-s6-consistent-backup.md\`: 数据恢复不可绕过安全审批/失效语义。

## 无生产凭据的安全命令样式（仅在明确获批的运维机器执行）

\`\`\`bash
python -m app.maintenance inspect --database /private/path/bot.db
python -m app.maintenance backup --database /private/path/bot.db --bundle /private/backups/seekpulse-YYYYmmdd
python -m app.maintenance verify --bundle /private/backups/seekpulse-YYYYmmdd
python -m app.maintenance restore-new --bundle /private/backups/seekpulse-YYYYmmdd --destination /private/restore/new.db
\`\`\`

所有返回均为不含原始数据库路径/用户内容的 JSON 状态或安全错误码。备份是**可逆操作**：从当前数据库复制到新目录；验证无误后，离线恢复产生不同路径的新文件，不会原地替换 \`bot.db\`。严禁生产进程运行时修改 \`DATABASE_PATH\` 或同时启动两个 Worker。迁移、停机、恢复后重启、真实低配 VPS 资源记录需要用户另行批准。

## 验收矩阵

| ID | 案例 | 期望 |
|---|---|---|
| S6-T01 | WAL 热备份与恢复 | Snapshot 含未 checkpoint WAL 事务，恢复的新文件具完整 S1/S2/S3/S4 表和原状态 |
| S6-T02 | 备份损坏/版本/归属 | SHA、大小、完整性/FK、未知 schema 版本失败关闭，旧 DB 不变 |
| S6-T03 | 磁盘写满与半成品 | ENOSPC 返回受限错误码，临时目录/文件删除，不发布错误的“成功”清单 |
| S6-T04 | 现有路径/sidecar/符号链接 | 不覆盖、不跟随链接、不删除 -wal/-shm，不触发旧任务重发 |
| S6-T05 | 锁与恢复 | SQLite 独占锁期间诊断安全失败，解锁后可正常取数和认领队列 |
| S6-T06 | 12h 离线/租约 | 旧任务过期可审计、新任务可继续，过期租约 token 不可确认 |
| S6-T07 | TG Session 失效与 RSS 429 | 独立退避、未越过游标、重新授权后有界补查且不复投旧消息 |
| S6-T08 | Web Session 轮替与目标冷却 | 旧会话失效，冷却持久且独立，不包含真实用户凭据 |

## 限制和后续审批

所有自动测试仅使用临时 SQLite / mock，未在真实 VPS、Telegram 账号、Bark、ntfy、用户 Web 浏览器运行。S6 的代码只保证**独立本地工具与故障注入模拟**，不承诺生产无损跨版本迁移、自动回滚或备份加密/上传。S7 48–72h 实机实验、生产上线或发布 Tag/Release 尚未获授权。

停机切换的危险事项（包含是否影响旧 -wal/-shm/正在运行的用户和真实投递的幂等性）必须在真实 VPS 演练之前另行批准，不以 CI 成功代替。

## 离线资源、依赖和数据保护审查（不代表 VPS 实测）

- **新增运行依赖**：`app.maintenance` 只使用 Python 标准库（sqlite3/hashlib/pathlib/os 等），不添加 pip 包、数据库服务、Redis、网络访问或额外后台 Worker；S6 CI 专项复用 S5 固定依赖做完整回归，不修改原 Dockerfile / Compose / requirements.txt。
- **磁盘预留**：在线快照需同磁盘临时存储完整 SQLite 图像，加 manifest 与文件系统余量；`restore-new` 还需要另一份完整镜像空间。具体峰值磁盘、IO 时长、CPU/RAM 与 1 vCPU/1 GiB 性能指标均**未实测**，应在 S7 真实 VPS 期间定量核对，严禁宣称达到目标。
- **敏感边界**：DB 快照虽设置 0700/0600，**内容未加密**，应由用户自行在获批机器上使用加密备份及受控保留策略；独立的 Telegram Telethon Session、.env、Bot Token 和运行时密钥**不会**包含在 SQLite 快照中，必要时须按单独审批的安全流程备份/重新授权，绝不上传到 GitHub/CI。
- **错误分类**：除操作系统 ENOSPC/EDQUOT 外，SQLite 底层 `SQLITE_FULL` 也统一输出 `disk_full`；SQLITE_BUSY/LOCKED 表示占锁，IOERR 类错误仅返回 `io_failure`，所有用户原文异常和绝对路径均不得打印。测试覆盖各分支。
