# S5-01 / Issue #14 — 本地 Web 及安全离线验收手册

当前：2026-10-14 用户批准 S5 开发；本文件属于独立 Draft PR，不代表阶段验收、main 合并或真实部署授权。

## 功能交付与依赖

- FastAPI 0.143.0、Jinja2 3.1.6、Uvicorn 0.54.0、python-multipart 0.0.32；HTMX 2.0.8 已 vendor 在 app/web_ui/static，附带 0BSD 许可。专用 requirements-s5.txt 向上引用已固定 S1-S4 依赖，原 requirements.txt 不变。
- 中文响应式后台：概览、关键词/屏蔽词/AND 组合、S3 来源状态、现有通知目标及 S4 路由、历史和设置。概览片段通过本地 HTMX 定时查询同一 SQLite；统计最近 200 条有效的来源首次观测至 API 接受延迟 P50/P95 并区分手机到达。Web 添加关键词遵守 Bot 原有 MAX_KEYWORDS_PER_USER 数量上限。CSS 支持明暗模式，无 CDN。
- 认证与防护：独立 scrypt 密码哈希、服务端会话/CSRF、登录限速、Host/loopback/Origin 安全限制、Jinja2 自动转义与 CSP。Web 仅管理员本人视角，不可访问其他 Bot 用户数据。

## 离线验证

安装可选 S5 依赖：python -m pip install -r requirements-s5.txt

执行 S5 专项：python -m unittest discover -s tests -p 'test_s5_*.py' -v

执行全量回归：python -m unittest discover -s tests -v

所有 S5 集成测试通过 httpx ASGITransport、临时 SQLite 和无凭据模拟，不运行实际服务。G0 保留原版锁定依赖，因此只跑标准库管理员密码、Session、Host 测试；S5 专项 CI 必须在 Python 3.11 和 3.12 完整运行包括 ASGI 安全测试，不得以 G0 合法缺依赖 skip 冒充 S5 通过。

## 以后经独立审批的本地预览步骤（本轮不执行）

1. 既有 Telegram Bot 的管理员先用 /start 建立本人 profile。Web 指定 Telegram 用户 ID，不是群 chat_id，也不能写入 GitHub。
2. 在授权的机器终端交互执行 python -m app.web_auth，输入独立的 12 字符以上密码并获取 scrypt 哈希；明文不得放命令行历史或 PR。
3. 以受保护环境为单独 Web 预览进程提供 SEEKPULSE_ADMIN_TG_USER_ID、SEEKPULSE_WEB_PASSWORD_HASH、DATABASE_PATH；任何凭据均不上传到聊天/GitHub。
4. 经再次批准后才可运行 python -m app.web_cli。入口固定 127.0.0.1，默认端口 8765，可通过可信 SSH local forwarding 访问，不能公开暴露公网或开启不可信反向代理。
5. 新增 Bark/ntfy 真正目标 ID、设备 Key、安全迁移，尚需独立审批；现有 Web 仅绑定合法已有 target_id 的通道与安全引用，不直接保存 URL/Token。

## 重要范围边界

本 S5 PR 不改变 app/main.py，来源与 Worker 不被自动启动，旧 FeedPoller 仍是原运行路径。S3 来源开关修改的是持久状态，不立即停止旧进程。S4 的高级路由参数由 Web 操作时写同一 SQLite，现有 Bot 命令保持旧版可操作的关键词/版块/暂停等范围。

暂未完成生产多渠道上线、真实浏览器/手机提醒、APNs 验证、低配 VPS 负载、生产历史迁移或单进程 Web 集成。上述必须另获用户授权，不因离线 CI 全绿自动合并或部署。