# ADR-0005 — S5 本地管理员 Web 的安全边界和共享数据契约

日期：2026-10-14 · 状态：S5 / Issue #14 已获开发授权，不等于阶段验收或合并批准

## 背景和决定

1. **单管理员、共享数据。** 管理员 ID 由 SEEKPULSE_ADMIN_TG_USER_ID 显式指定，必须先通过原 Telegram Bot /start 初始化。Web 仅管理该用户自己的规则、屏蔽词、版块、现有目标和投递历史；直接调用现有 Database、SourceStore、RouteStore，共用一份 SQLite，不新建用户/关键词/目标体系。不能读取其他 Bot 用户信息。
2. **运行隔离。** app/main.py、Dockerfile、Compose 和原 requirements.txt 均保持原样；独立 app.web_cli 仅供未来明确获批的本地预览，固定 127.0.0.1，单 Worker，不接受代理头，关闭访问日志。此次不启动服务、不修改生产环境；未来正式接入单进程须经过独立 S6 设计和实机测试。
3. **防暴露。** 同时验证客户端 socket 为 loopback 及 Host 属于 localhost、127.0.0.1 或 IPv6 ::1，拒绝 X-Forwarded-*、Forwarded 和 Host DNS rebinding。仅供本机或可信 SSH 隧道访问，不提供公开 Web/SaaS/不可信反代。
4. **认证。** 独立 Web 管理密码采用 scrypt 盐化哈希，从受保护环境读取 SEEKPULSE_WEB_PASSWORD_HASH；不允许 Bot Token 兼作 Web 凭据。交互式 python -m app.web_auth 仅输出哈希。服务端内存保存不可逆 SHA256 会话 token 键、CSRF 和到期时间，HttpOnly、SameSite Strict cookie；成功登录后旋转会话，退出及进程重启失效，匿名登录页也要求 CSRF。五次失败后有界登录限速。
5. **请求安全。** 写操作必须 POST、管理员登录和 CSRF token；提供 Origin 时必须同源。Jinja2 自动转义，CSP 禁止内联脚本及第三方源，并启用 NoSniff、NoReferrer、Frame Deny、NoStore。HTMX 2.0.8 本地静态资源，随附 Zero-Clause BSD 许可证，无任何 CDN/远程 JS。请求值及 ID 均在服务器校验；不反射机密或原始异常。
6. **唯一业务配置。** Web/Bot 修改关键词、AND 条件、屏蔽词、启停、版块时共用上游方法；来源启停只调整 S3 状态，不能宣称已启动未集成的 TG 采集；通知只允许为已有且合法归属的 target_id 配置 provider 及环境变量安全引用。**非 Telegram 正式新目标身份/迁移仍未完成，本阶段绝不制造假 chat_id 或输入设备 URL/Key。**
7. **只读健康和历史。** 任务统计、来源健康、最近 50 项管理员 S2 任务及最近 40 项旧 Bot 历史必须 LIMIT 且带 user_id 作用域；显示 API 接受不等于手机收到，不推断全链路延迟。

## 被拒方案和残余风险

拒绝公开后台、Web 普通用户登录、Redis/第二套业务配置、GET 改数据、自定义 webhook、在线脚本加载或绕过原 Bot 目标归属。S5 的 ASGI/SQLite 测试均不联网；真实浏览器 UI、SSH 隧道、低配 VPS、生产进程并入、真实 Bot/推送和旧历史迁移都需要单独批准和验收。S5 PR 未合并时直接关闭即可回滚，不触及主分支及生产。