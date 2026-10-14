# ADR-0006 — S6 SQLite WAL 一致性备份、只读体检与安全恢复

日期：2026-10-14 · 状态：S6 Issue #15 已获开发授权，尚未阶段验收 / 合并 / 部署授权

## 现状与问题

已验收的 S1 旧 Bot、S2 持久任务、S3 双来源、S4 路由和 S5 管理后台共享一个 SQLite 数据库，S2/S3 均使用 WAL。直接 cp 正在运行的 \`bot.db\` 会丢失未 checkpoint 的已提交事务，导致投递游标、租约和业务配置错位；恢复过程中若偷偷覆盖现有 DB / 残留 -wal/-shm sidecar，可能造成错误合并或双重通知。独立 S6 要保证可检查、可证明数据一致性、可逆，不能强制修改已批单机运行时。

## 选择与约束

1. **单份存储，无新业务表**：只新增独立 \`app.maintenance\` CLI；不改 \`app/main.py\`、Dockerfile、Compose、已有 DB schema 或通知逻辑，也不添加 Debug API、Redis、第二套数据库。
2. **正确的 WAL 快照**：使用 Python \`sqlite3.Connection.backup()\` 官方在线备份 API 从 \`mode=ro\` 打开的现有 DB 读取一致性快照，包含提交到 WAL 但尚未 checkpoint 的变更。SQLite 备份完成后转换副本至独立的 \`journal_mode=DELETE\`，保证备份不依赖原服务的 -wal/-shm。
3. **Fail-closed 验证**：对源与副本执行完整 \`PRAGMA integrity_check\`、\`PRAGMA foreign_key_check\`；要求当前已实现的 S1–S4 表齐全，S2 \`core_schema_version=1\` / S4 \`routing_schema_version=1\`，不自动识别或升级未知版本。不因数据库连接失败创建空数据库。
4. **原子私有备份目录**：所有临时文件在目的父目录，临时目录 0700，\`snapshot.sqlite3\`/JSON manifest 0600；manifest 只写格式版本、DB SHA-256、字节长度、当前 schema 两版本和创建时间，不记录 Token、Session、帖子、用户 ID、文件路径或通知 URL。先备份、验证、fsync、再 rename 发布目录；失败删除私有临时目录，**拒绝覆盖已有目的目录**。
5. **恢复永不覆写**：先核验备份哈希/尺寸、SQLite 完整性与 schema；随后通过同一文件系统的临时文件、校验、\`os.link()\` 原子**独占**创建一个不存在的新数据库文件。存在原 DB、目标 -wal/-shm/-journal 或符号链接时拒绝。磁盘写满等错误不得留下半成品或覆盖旧数据。
6. **切换/回滚留给明确获批的人工运维**：本 CLI **不实现**覆盖/改名现役 \`DATABASE_PATH\`、不停止/重启服务、不删除旧文件或 WAL sidecar、不自动修改环境变量、不开真实 Telegram Session/通知。经另行授权的运维，先停所有访问同 DB 的进程、核对队列租约/备份、恢复至全新路径，明确手工指定 \`DATABASE_PATH\` 指向新文件，保留旧 DB/WAL 与原快照以便反向切换；严禁两个实例并行消费同一数据库。
7. **只读诊断**：\`inspect\` 输出 full SQLite integrity、schema、库文件/WAL 字节数、总用户数、任务状态总数与两个来源的游标/重试时间和安全短错误码。不会输出用户名、关键词、聊天 ID、错误异常文本或机密；所有 CLI 失败仅输出受限错误代号（如 \`disk_full\`、\`database_busy\`、\`checksum_mismatch\`），不打印异常正文。
8. **故障注入**：测试使用临时 SQLite、mock 文件复制失败、旧任务的虚拟时钟、官方源假客户端和单线程 SQLite 锁；覆盖磁盘不足、占锁、超时租约、12–24h 离线、TG 授权失效/恢复、RSS HTTP429、未知 schema、FK 损坏、篡改/符号链接/重复恢复。无测试用命令被保留在产品运行时接口中。

## 异常和剩余限制

- 创建备份需数据库最终可读，否则报安全短码拒绝。备份本身包含用户业务数据，**不是加密备份**，必须在用户批准的本地存储和 0700/0600 权限内保管、独立做离机加密及保留策略。脚本不执行上传、备份轮换或密钥管理。
- SQLite 备份/检查消耗 IO 和可能等待 busy（有界进度检查）；不保证与 1 vCPU / 1 GiB 实机资源预算一致。S7 需要实际部署验证。
- 从旧文件恢复历史 S2 租约时须按实际当前时钟调用已存在 \`CoreStore.recover()\`，到期任务审计为 expired，不跨时间窗口补推旧消息；原 API 接受但尚未持久标记 sent 的崩溃窗口仍存在可能的重复，ADR-0002 不变。
- 恢复到新文件不是无感上线，**不能**把 S6 离线可恢复性当成 Telegram/Bark/ntfy 或 Web 生产验证。真正升级/切换/回滚需要用户独立许可及停服实机操作。
- 不自动迁移旧多平台目标身份；未来数据库 schema 变化必须另行版本化迁移与独立审批。

## 被拒方案

热拷贝 \`bot.db\`、备份主文件不带 WAL、直接覆盖生产 DB、\`rm *-wal\`、备份清单包含用户数据、未知 schema 自动 upgrade、自动启动第二个消息消费者、上传原始 DB 作为 CI 工件、为故障测试在 app 中留隐藏诊断端口。
