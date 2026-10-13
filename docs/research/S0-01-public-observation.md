# S0-01 — NodeSeek Telegram 官方频道可行性初步观测

**状态：研究中；尚不能验收 MTProto 实时监听及断线恢复。**  
**日期：2026-10-13**  
**关联 Issue：[#5](https://github.com/Aspeternity/SeekPulse/issues/5)**

## 公开来源中已观察的事实

- [NodeSeek 官方频道公开预览](https://t.me/s/nodeseekc) 存在连续的新帖信息，显示原帖标题、部分摘要以及指向 NodeSeek 的原帖链接。
- 已人工观察到下述两个公开样例：
  - `https://www.nodeseek.com/post-981300-1` → 规范化 `post_id=981300`
  - `https://www.nodeseek.com/post-981314-1` → 规范化 `post_id=981314`
- 公开 HTML 可能展示部分摘要，但不能假定版块字段、正文或作者完整。
- `https://rss.nodeseek.com/` 被某些 Web 文本浏览器标记为不支持 `application/xml`，这**不是 RSS 服务故障证据**。
- 当前隔离代码执行环境直接访问 TG/RSS 遇到 DNS 解析失败，无法在该环境收集可信的实时时效数据；网络可用性需另行验证。

## 已完成的、仅属于 S0 的探针

`scripts/s0_public_probe.py` 使用 Python 标准库，只读 GET 一次公开 TG HTML 和 RSS（同时开始请求），提供脱敏 JSON：来源、采样时间、HTTP 状态、链接数量、帖子 ID 及错误类型；不保存标题、摘要、Telegram 会话或任何凭证。

- 帖子身份采用经过域名严格校验的 NodeSeek 链接 `/post-<id>-<page>`；拒绝非 NodeSeek 域名/伪造链接。
- 基于公开预览的检测**不是 Telethon MTProto 新消息事件**；只能检验公网页面的链接可识别性。
- 单次两个网页的请求时间和 ID 交集**不能衡量论坛→TG/RSS 的发布延迟或漏报率**，其结果字段明确写成 `UNMEASURED`。
- GitHub Actions 如可访问公共网络，保存单次源采样工件，但外部网络失败不得被 CI 绿误称为“来源可行性通过”。

## 尚未验证，需后续实验

1. 使用专门的测试 Telegram 账号，经用户自行控制的受信环境完成 Telethon 登录与订阅；不将 API ID、API Hash、登录验证码、Session 上传 GitHub/聊天。
2. 用 `events.NewMessage` 监听实际 `@nodeseekc` 频道，核查频道 ID、消息 ID、可用文本、URL entities、编辑和删除边界。
3. 使用 Telethon `catch_up()` 和有限 `iter_messages(..., min_id=...)` 验证短时断网/重启的真实补查能力；不要凭 API 文档当作实机 PASS。
4. 与 RSS 同机持续采样 24h+，记录同一 `post_id` 在两来源首次被看到的时间和数据缺口；归属后续 [#6](https://github.com/Aspeternity/SeekPulse/issues/6)。
5. 必须对“标题可识别、版块缺失、内容截断、非原帖链接、编辑/删除消息”等情况保留脱敏样本与 PASS/FAIL 证据。

## 阶段授权边界

当前只授权 S0 技术验证，未获批准修改 `app/` 业务运行行为、合并 main、部署生产环境、发布 Release 或开始 S1。未经 Telegram 账号专用测试，不得宣称“实时通道稳定、低于 RSS 延迟、能够完整断线恢复”。
