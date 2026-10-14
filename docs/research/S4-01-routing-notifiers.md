# S4-01 / Issue #13 — Telegram、Bark、ntfy 与规则路由开发验收说明

**授权**：2026-10-14 用户针对“是否批准启动 S4 / Issue #13 开发？”回复「批准开发」。本次仅创建 S4 独立分支和 Draft PR，在本地与 GitHub CI 执行无凭据模拟测试。不合并、发布或部署。

## 本阶段交付

- `app/routing.py`: RuleSet 三态门槛；默认目标、规则完整覆盖、普通/紧急层级合并；同目标优先级取最大，只有 matched 才能入 S2 任务队列。多来源重复由已有 (user,post,target) 唯一键保底。
- `app/route_store.py`: 追加 S4 路由策略/通道映射/限流冷却表；目标/关键词必须归属用户，持久存储的是 `BARK_SECRET` 一类引用，不保存 URL/Token；无新目标注册 API。
- `app/notifiers.py`: Bot 原生 send_message，HTML 安全编码；分类 RetryAfter/Forbidden/TimedOut。Bark/ntfy 使用仅允许固定官方 host 的 Apprise 2.0.1，强制单服务、停用 Apprise 自动重试/重定向，仅以布尔及逐服务结果认定成功。Apprise 未暴露确切 HTTP 状态时按可重试失败处理，S2 max_attempts/TTL 有界；不得编造 403 证据。
- `app/worker.py`: 尝试领取前避开 in-flight/cooldown 目标；每 5 个领取轮次至少尝试一次普通任务避免紧急消息饿死正常消息；跨目标并发；任务发送前从现有 SQLite 重新读取规则/目标，失效则 fenced suppress；发送后 API 接受才将 S2 标记 sent；失败独立重试并记录短安全代码。
- `app/delivery.py`: **向后兼容**的 claim optional priority/exclusion 参数及 token 栅栏已租赁 suppress，旧 S2 逻辑不变。
- `requirements-s4.txt`：沿用 `requirements-s3.txt`，另外固定 `apprise==2.0.1`；现有 `requirements.txt` 原样保留满足已验收 S1 契约。CI Python 3.11/3.12，S1/S2/G0 继承回归。
- 测试全部使用临时 SQLite、模拟 Bot 和伪 Apprise 返回对象，**不联网、不上传 Token/Session，不发送真实消息**。

## 必须保留的验收边界

- `app/main.py` 不创建此 S4 Worker；旧 FeedPoller 仍为既有运行时，真正从旧历史迁移/切换多渠道须另获批准。
- **正式注册 Bark/ntfy 新目标的表结构与旧目标共存方案尚未完成。** S4 测试只给已存在目标 ID 绑定 provider，不能承诺生产用户今天就可在 Web/Bot 新建 Bark/ntfy 目标。切勿伪造 Telegram chat ID。
- Telegram、Bark 和 ntfy 的模拟 API success 不能证明手机提醒送达、移动 APNs 路由、真实平台限流或自建 ntfy 服务。S0 Apprise PR #18 为独立研究，继续 Draft 未合并。
- 官方 host allowlist 只允许 `api.day.app`、`ntfy.sh`，并**只接收 `barks://`、`ntfys://` 加密 URL**，拒绝 `bark://`、`ntfy://` 的明文协议；未来要允许自建 Bark/ntfy 必须独立审批 DNS/SSRF/重定向/网络路径。
- 每目标冷却协调器以单个 Worker 实例为假设；多进程或跨主机不保证跨实例目标限流，未来正式运行必须先落实单实例所有权。
- S4 仍遵守 ADR-0002：API 接受后、SQLite sent 落库前崩溃存在极端重复窗口，不承诺 strict exactly-once。

## 回滚

关闭独立 Draft PR 即回滚；没有 main、生产数据库、真实 Telegram Session、Bark/ntfy 配置或服务器变更。成功 CI 仅代表相应精确 PR HEAD 的自动测试，不能代替用户阶段验收或单独合并审批。
