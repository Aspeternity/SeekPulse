# SeekPulse Web-first B — Portainer 单容器部署候选（**尚未发布**）

> **此文档记录离线开发与验收方法，不是实际安装通知。** 用户仅批准 B 阶段独立分支开发，没有批准镜像发布、NAS/PVE/群晖/Portainer 实机操作、生产数据库升级或现有 RC1 实例切换。不要将 `compose.web-first.yaml` 中的 `web-first-b-NOT-PUBLISHED` 当成已发布可拉取镜像。

## 最终预期的首次使用体验

1. 在 Portainer 使用 **一份 Compose** 创建 Stack；只有镜像、端口和**自动建立的命名数据卷**，不要求填 Bot Token、管理员密码、密码哈希、Telegram API 或任何初始化码。
2. 容器完成**全新数据卷**的 SQLite 创建后即可提供 Web，完全不依赖 Telegram Bot。
3. 浏览器打开 `http://<NAS或PVE的局域网IP>:8765`，**第一次自动进入「创建管理员」页面**。用户自己输入用户名、密码、确认密码；没有默认账号、日志中的验证码或外部命令。
4. 注册后进入**单独的登录页面**；再用刚创建的用户名密码登录。此后关闭公开注册，配置随 Docker 命名卷保留，重启后仍需登录。
5. 六个主菜单和 V4 设置四顶部标签保留。B 阶段只有认证、账户修改、偏好设置、日志级别偏好及健康页是真正连通的；**RSS/TG、Bot/Bark/ntfy、规则和推送历史仍标记「待后续阶段接入」**，不能误以为已有真实推送。

## 部署文件和安全约束

- 镜像源：`Dockerfile.web-first`。Python3.11/Alpine3.24 不变基础 digest、稳定 zlib；仅安装 `requirements-web-first.txt`（FastAPI、Uvicorn、Jinja2、Multipart），不包含 Bot/Telethon/采集 Worker 的生产入口。
- `compose.web-first.yaml` 使用 bridge 网络、`8765:8765/tcp`、只读根文件系统、10001 非 root、去除 capabilities、no-new-privileges、/tmp tmpfs、命名卷 `seekpulse_web_first_data` 和独立 `/healthz` 健康检测。正式发布后必须改成**已核验的 GHCR 不可变摘要**。
- Docker 创建空命名卷时利用镜像内预设的 0700/10001 目录属性，无需容器启动时 root chown，不需用户先 chmod；已有卷仍必须接受权限与结构检查。
- `8765:8765` 会让宿主端口监听全部地址；**只允许可信家庭 LAN，不能开放 WAN 映射或未经审核的反向代理。** 当前是无 TLS 的 HTTP，敏感凭据会经过局域网，请按可信网络环境使用。未初始化服务的**首位成功注册者**会拥有管理员权限，部署后应立即注册。不能未经用户批准擅自增加「去容器日志取码」步骤。
- 管理数据单独存于 `web-first.sqlite`，不会自动导入、合并或迁移已有的 `bot.db`。旧 RC1 卷、未知文件、残留 sidecar、损坏 SQLite 一律拒绝静默重建/覆盖，必须人工评估恢复路径，**不要删除数据卷试图修复错误**。
- 目前不构建/推送 GHCR、不创建 Tag/Release、不执行用户真实机器操作。B 开发仅借助 GitHub Actions 临时测试容器。

## 当前验证

`.github/workflows/web-first-b.yml` 包含 Python 3.11+3.12 离线 ASGI/SQLite/安全回归，以及 GitHub 临时 Runner 上**真实 Docker build、空命名卷启动、HTTP 首次注册、登录、保存偏好、重启、持久化登录、Portainer Compose 静态合约**，使用测试假密码和本机 127.0.0.1 端口；测试完成自动移除容器/卷，不向外发通知。

最终只以**最新 PR HEAD** 的完整成功 CI 为合格证据；旧 SHA 的绿色结果不能替代本次代码结果。还需用户 B 阶段验收、后续单独合并审批，以及未来独立的 GHCR 发布与真实 Portainer 部署批准。

## 后续需求

C 阶段才处理 RSS/TG 可分别启停、双来源融合、Telegram Bot 通知与命令、Bark/ntfy 密钥配置/发送及业务状态动态生效；D 阶段整合规则/历史/备份/诊断。不能因 B 阶段 Web 可登录就认定监控和通知系统已完成。
