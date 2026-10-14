# ADR-0008 — V1.1 Docker 镜像 / Compose 离线交付与回环 Web

日期：2026-10-15 · 状态：按用户批准仅进行离线开发，不含发布或真实部署 · Issue #32 / 父 #16

## 背景

用户已明确取消专门的 VPS 体检。SeekPulse 的批准产品形态一直是单机 Docker + Compose；未来可在现有 PVE/Portainer（独立 Docker Engine）或群晖 NAS Container Manager 中运行。Gate B / PR #30 已合并 opt-in `app.v11_main`，但旧 Dockerfile 只安装 `requirements.txt` 并启动 `app.main`；旧 Compose 采用本地 `build: .`。无经批准的可拉取 GHCR V1.1 镜像。

S5 既有安全契约（ADR-0005）**同时要求 TCP 客户端与 Host 均为 loopback**，不仅是 Uvicorn 监听地址。因此将容器 Web 改监听 `0.0.0.0` 并映射宿主回环端口也会被认证中间件拒绝；为了“方便 Portainer”删除客户端回环检查更不可取。

## 本次决定

1. **不破坏旧版默认入口**：保留旧 `Dockerfile`、`docker-compose.yml`、`requirements.txt`，另外提供 `Dockerfile.v11` 和 `compose.v11.yaml`；镜像只能在获准构建/发布以后被 Compose 拉取。未授权不得自动推送 GHCR，也不提前宣称已发布。
2. **只打包，不绕过 Gate B**：V1.1 镜像包含 `requirements-s5.txt` 固定直接依赖链与 `app/web_ui`，固定入口 `python -m app.v11_main --run`。必须显式 `SEEKPULSE_V11_ENABLE=1`，未 Prime、未验证迁移/备份、异常用户或推送目标则拒绝运行；不从镜像 build、Compose config 或首次启动自动生成 Session、Bot Token 或对旧库做迁移。
3. **Linux host 网络保护 Web**：V1.1 专用 Compose 明确要求 Linux Docker host networking，**无 ports 映射**。Uvicorn 仍由现有代码固定绑定 `127.0.0.1`；请求必须实际来自同主机回环并保持允许的 Host，远程管理员通过 SSH 本地端口转发访问。不启用公开 LAN Web、不可信反代或 forwarded headers，也不改 S5 安全判断。host networking 与 Swarm stack/macOS 非兼容，必须在未来独立实机阶段核实 Docker/Portainer/群晖支持；未来如需私网反代，单独设计和审批。
4. **资源与数据保护**：镜像默认 10001:10001 非 root，Compose 默认无特权、全部 capability drop、no-new-privileges、只读 rootfs、有限 /tmp tmpfs、单实例、无 Docker Socket。显式 bind 到由操作者事先建立并设置非 root 写权限的 **绝对路径**（SQLite/WAL/owner.lock/TG Session 在同一持久卷）；不让 Compose 默默创建未授权宿主数据目录。用户可以用 NAS/PVE 的实际非 root UID/GID 覆盖。
5. **保护构建上下文与运行秘密**：`.dockerignore` 排除 `.env`、`data`、Session/SQLite/WAL/日志/备份；镜像内无私密文件。现有 Bot、Web、Bark/ntfy 均通过运行环境引用，标准 Docker 环境变量可由宿主管理员/Portainer 管理员在 `inspect` 中看到，不能视为硬件密钥库；不得记录原值在 CI、GitHub 或交接材料。示例均为假占位符，要求单独保护。
6. **离线 CI 不构成发布**：GitHub runner 上 build `Dockerfile.v11`、验证镜像依赖/Web 文件/非 root/拒绝默认运行、检验 Compose 解析及 host 网络安全约束，Python 3.11/3.12 全量回归。全部用假变量，无实际 Telethon 登录、通知发送、DB 迁移、实机部署；绝不 push 镜像。

## 当前未解决项与后续独立闸门

- `--prepare` 当前要求独立验证的 S6 备份，即使全新初始化也不能私自跳过。**本次仅提供镜像与编排产物，不宣称新机器“执行 up 即可开始通知”**。首次新库的安全初始化和旧库迁移的具体操作闭环须在后续 Gate D 独立评估、授权与实机验证；不能修改 B03 去重/Prime/回滚契约。
- Host 网络只面向 Linux Docker standalone/Compose；真实 Portainer、群晖版本、CPU 架构（尤其 ARM64）、宿主卷权限、SSH 隧道、登录与通知都未实测，状态为 UNKNOWN / NOT_STARTED。
- `restart: "no"` 是当前未完成灰度许可前的 fail-closed 默认。获准完成准备/迁移/灰度后是否使用 `unless-stopped` 另行审查。
- 公开 GHCR digest/tag、构建多架构镜像并推送、生产 SQLite 操作、Telegram/Bark/ntfy Session/密钥和真实通知、48–72h 运行、Gate D–G、最终合并 main、Release/Tag 均**没有**包含在本批准中。

**回滚**：本 PR 的离线改动不触碰既有服务或 DB，未合并时关闭 Draft 即可；合并后也不自动改变上游旧 Docker/Compose。未来真实 Schema 迁移必须按 ADR-0007 备份/恢复到新路径，不能以降级镜像代替数据库回滚。
