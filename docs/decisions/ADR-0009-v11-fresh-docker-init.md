# ADR-0009 — V1.1 全新 Docker 数据卷的一次性初始化与启动校验

日期：2026-10-15 · Issue #34 / 父 #16 · **已获独立 Docker-02 离线开发授权；未获阶段验收、合并、GHCR 发布或真实部署授权**

## 问题、影响与分流

Gate B / ADR-0007 的 `app.v11_main --prepare` 是**已有数据库迁移**：必须先验证 S6 一致性备份 Bundle，然后在独占数据库锁内初始化/版本化迁移并显式 Prime，避免旧帖子补推及迁移后回滚重发。新建 Docker 数据卷不包含旧数据库、没有需要保护的已有用户资料，也没有可以从旧库创建的 S6 Bundle。复用 `--prepare` 会在首次安装时必然失败；在 `--run` 中自动建库/迁移或省略 Prime 则破坏安全闸门。

因此新增一个**只服务于全新专用空目录**的第三种路径 `--init-fresh`；原 `--prepare` 和旧 Dockerfile/Compose 语义原封不动。新增 `--check` 只读核对准备状态，运行入口也必须在任何 stores 初始化/网络启动之前做同样的 fail-closed 核对。两种路径明确不互通，不把首次空库权限移植到生产旧库。

## 新建库的精确授权条件

1. CLI 必须同时明确 `--init-fresh`、`SEEKPULSE_V11_ENABLE=1`、`SEEKPULSE_FRESH_INIT_CONFIRM=CREATE_EMPTY_DATABASE`（不可由镜像或 Compose 提供默认确认）；选择已有 `DATABASE_PATH` 环境变量且**绝对、已存在、非符号链接/规范化父目录**。初始化不从环境读取 Bot Token / Telegram Session、也不需要账号登录。
2. `DATABASE_PATH` 自身、`-wal/-shm/-journal` 任何侧车都必须不存在（含悬空 symlink）；专用数据目录不得有其他对象，唯一允许本程序新建的 `.owner.lock`（为此前被拒启动残留）除外。严禁悄悄跳过、覆盖、截断、删除已有 SQLite、Session、旧用户备份或其他文件。文件名可以是自定义 DB 名称，但目录必须为新实例独占。
3. 使用 Gate B 现有 `fcntl` 独占数据库锁，再次检查空目录；于该目录创建不可预测、`0600` 的单一暂存 DB（不触碰正式路径），完成现有 `Database/CoreStore/SourceStore/RouteStore/ObservationDispatcher/GateBTargetStore` 初始化与空用户、空任务/空观察的显式 Prime，版本化目标外键/完整性核验、S6 schema/integrity 检查。必须确保所有 SQLite 写连接结束后，对**仅属于本次新建 staging 的数据库**执行 `PRAGMA wal_checkpoint(TRUNCATE)` 并切换 `journal_mode=DELETE` 形成独立单文件，再进行 S6 完整性及 Prime 校验；任何 WAL/SHM/JOURNAL 残留都阻断发布，绝不能直接删除正式数据库的 WAL。
4. 用同一文件系统内的 **atomic no-overwrite hardlink** 将已验证文件从暂存路径发布到指定正式路径（`os.link`），再 fsync 目录与清理原暂存 hardlink；如果已有 DB 竞争者抢先创建，`EEXIST` 必须失败，绝不覆写。意外失败仅删除本命令随机生成的暂存文件/侧车，绝不删除或改写已有正式库。实例锁按原协议保留，可供下一次启动使用。
5. 新库的“无历史数据”前提并不是“跳过原生产备份要求”：`--prepare` 对任何**已有库**继续强制 S6 已校验 Bundle；`--init-fresh` 遇到已存在库即拒绝，不允许用它修复、覆盖、重置或迁移旧库。恢复必须依 ADR-0007/ADR-0006 到独立新路径。
6. `--run` 在进入原有可写 Store、启动 Bot/Web/来源/Worker 之前，先只读要求**确实存在**正式数据库，且 Gate B target schema 版本有效、`targets.chat_id` nullable 已按 B02 初始化、`gate_b_dispatch_state` 已存在有效 singleton/Prime 游标；否则以安全错误失败。不得因此自动建库、Prime、迁移或触发通知。`--check` 可供独立只读核验，不等同于实机网络验收。

## 安全和运维边界

- 首次初始化**只在本 Issue 获准的离线 GitHub CI / TemporaryDirectory 中执行**。操作者将来要在自己 NAS/PVE/Portainer 运行同一命令，必须另获真实部署阶段授权；本次仅提供未来示例。镜像内无 Token/Session/预置数据库，也不自动执行 `--init-fresh`。默认 `compose.v11.yaml` 的 `command: ["--run"]`、`restart: "no"`、非 root、只读 rootfs、绝对持久卷、Linux host-loopback Web 均保持。
- Prime 初值必须是当前零条来源观察的高水位 0；RSS 首个采样窗口沿用 S3 `bootstrap_rss` 不补发政策，TG 默认未启用，不读取任何 Telegram 消息。真实来源账号会话、初次用户命令、API 通知均不在此测试范围。
- GitHub Actions 专项测试必须用**假值、临时目录、完全关闭网络的临时容器**模拟首次 init/check/重复拒绝，包含错误注入、磁盘/原子发布失败、symlink/sidecar/非空目录、竞争锁和旧库保护。经用户后续同意才可推送 GHCR 镜像，CI build 仅存在于临时 runner。
- 运行时 Linux SQLite 仍可能在读取已存在 WAL 数据时创建短暂 SHM 辅助文件；`--check` 不是 SQLite 导出/快照，也不替代 S6 backup；不能在 CI 或 GitHub 输出敏感数据库行。
- Synology NAS（尤其文件系统/权限/非 root hardlink 约束）、PVE Portainer、x64/ARM64、多架构正式 GHCR digest、真实 Bot/Web/通知、重启/升级/故障测试、48–72h 完全未实测。Linux Docker 宿主环境的可用性不能从 runner 全绿推导。

## 测试、审批与回滚

- 独立 `feat/s7-docker-02-fresh-first-boot`、Draft PR、G0 + Gate B + S7 Docker-01 + Docker-02 专项双 Python 回归，CI 只构建本地镜像且不 push。最新精确 HEAD 的完整作业全部成功后向用户申请**离线阶段验收**，之后再独立请求 Squash 合并。
- 本 PR 不触碰已有生产数据/容器。未合并前关闭 Draft 即回滚；将来迁移旧库严禁以“重置空库”或降级新镜像替代 S6 验证备份和原子切换。与上游旧入口的兼容契约应由回归测试确认。
