# ADR-0019 — Web-first B：Portainer 单容器控制面、独立管理员与首装持久化

日期：2026-10-16 · Issue #61 · 用户已明确批准 **B 阶段架构设计与独立分支离线开发**；未批准阶段验收、PR 合并、GHCR 发布、NAS/PVE 实机或 C 阶段真实采集/推送接入。

## 问题与已验收的产品契约

V1.1 RC1 的 `app.v11_main` 在 Web 之前构建 Telegram Bot，`compose.v11.yaml` 需用户先提供 Bot Token、管理员 TG ID、scrypt 密码摘要及显式全新数据库初始化；Web 绑定 loopback、身份依赖 TG `users` 表。这个入口不是已通过 A 阶段 V4 UI 验收的 Web-first 产品：管理员首次单独注册/随后登录、无强制向导、Web 自主管理、RSS/TG 独立、通知渠道自由组合。

不能通过把新入口偷偷塞进旧 `--run` 来修复：现有 Gate B DB schema/Prime/迁移/重复推送保护是针对已经运行过的旧 Bot 数据。旧版 RC1 有独立发行与回滚证据。

## 决定：隔离增量而非就地转换旧库

1. **B 阶段 opt-in 新入口**：新增 `app.web_first_main`、`app.web_first` 和 `app.web_first_store`，一进程单 Web worker、无 Bot/TG/Worker 启动依赖；默认启动只读/写自己的受控管理数据，不导入旧 Bot 运行入口或触发消息采集。旧 `app.v11_main`、现有 `Dockerfile.v11`、`compose.v11.yaml`、业务数据库、消息路由和发布镜像严格不动。新入口即使尚未配置任一通知渠道，Web 仍正常开放。
2. **Portainer 初装**：新增 `Dockerfile.web-first` 和 `compose.web-first.yaml`（**仅为未来授权后构建/部署的示例**），使用已在 CI 证实的 Linux 非 root uid/gid 10001、只读 rootfs、限制 capabilities、不挂 Docker socket、Docker 管理**命名卷**，网络用 bridge + Web TCP 端口映射，默认 HTTP 局域网访问。不得复用旧生产卷；不得将旧 `compose.v11.yaml` 变成静默新入口。用户只需在 Portainer 部署一份 Compose；不要求填 Bot Token、TG API、Bark/ntfy Secret、管理员密码哈希或运行 init CLI。
3. **独立 SQLite 管理域**：在新专用数据卷内使用 `web-first.sqlite`（管理员摘要、非敏感 Web 偏好、schema 版本）。保留旧 `bot.db` 与 `s3/s4` 等表协议；**B 不宣称已迁移或连接旧业务历史**。C 阶段需独立 ADR 确定与可靠投递核心/新凭据存储的适配或迁移；不能同时存在两套实际规则的写入者。
4. **安全的新安装检查**：启动只在明确空白且具备正确权限的私有目录创建新 DB；先获取 Linux 独占锁，检查非符号链接、数据库侧车和任何未知对象，随机私有暂存、SQLite schema 创建 + 校验、同卷 atomic no-clobber hardlink 发布。已存在、损坏、schema 不符、旧库误挂载或中断遗留 staging 均 **fail closed**，不删除、不重建、不直接迁移。已创建且完整的 B 库重启直接校验复用。
5. **管理员注册与防抢注**：系统首次缺失管理员时自动生成随机一次性初始化码，只将其以 `0600` 文件保存在专用卷、向容器日志提示如何在 Portainer 获取；首次独立 `/register` 页面填写用户名、密码、确认及该码。只有匹配随机码、有效 CSRF、未限流且不存在管理员时才在 SQLite 单事务创建唯一管理员；创建后删除一次性码，并永久关闭公开注册入口。重启未完成注册可以复用原码，不暴露于网页响应/业务日志。容器日志可被 Portainer 管理员读取这一点是可信边界，日志访问应视为管理权限；不要求每次输入初装码。
6. **认证**：复用 `app.web_auth.password_hash/check_password` 的 scrypt 协议与 `WebAuth` 的内存会话/CSRF/按客户端限流，移除对 TG 用户 ID 的要求；Web 用户名和 scrypt hash 存在私有 SQLite，明文密码不落盘、不回显、不进 Compose，重启注销旧会话；首次注册与登录为不同页面。受保护的 POST 检查 Origin+CSRF+大小限制，并设置 SameSite/HttpOnly cookie、安全响应头与登录失败限流。系统配置可以在 Web 修改且重启保留。
7. **局域网访问而非公网安全假设**：容器监听 `0.0.0.0` **仅在容器命名空间**，通过 Compose 8765/tcp 映射到宿主机供家庭 LAN 使用；默认 HTTP，没有 TLS，**只适合可信局域网和防火墙阻止 WAN 的部署**。不默认支持公网直连。Host 应限于 IP literal、`localhost`，拒绝恶意 Forwarded/X-Forwarded 和 DNS rebinding host；未来 HTTPS 反向代理需另审网络信任与 `Secure` cookie，不为减少 Compose 行数牺牲认证。验证码是防止首装抢注的必要一次性步骤，但无需用户提前设置环境变量。
8. **UI B 阶段边界**：沿用 V4 的六大入口和设置四顶部分类，独立注册/登录真实可用。概览、来源、规则、渠道和历史未接入的部分明确显示“待 C/D 阶段接入”，不提供会假装成功的生产开关或推送测试。B 仅持久化少量非敏感 Web 偏好、账户修改、退出、状态观测；完整 Bot/Telethon/Bark/ntfy 凭据的写入、运行动态应用和历史接入归 C/D 阶段。
9. **部署和回滚**：GitHub CI 可离线 build `Dockerfile.web-first`、模拟网络禁用与 SQLite/HTTP 客户端；B 实机部署须单独授权。PR 未合并可直接关闭分支回滚；未来已经初始化的 B 数据卷不得让旧 RC1 启动或盲目覆盖，版本降级需兼容性验证与有校验的备份后停机切换。

## 验收分界

本 Issue 内只进行 ADR → 实作 → 离线回归 → 精确 HEAD CI → 请求用户 **B 阶段验收**。即使所有测试通过也不等于 Portainer 实机验收、合并、发行或生产配置迁移。用户之后需对 B 阶段结果单独确认，并另行批准 PR 合并和下一阶段。
