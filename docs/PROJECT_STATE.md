# SeekPulse — S4 / Issue #13 当前交接索引

> 2026-10-14 快照；审批/HEAD/CI 必须实时核对 GitHub Issue/PR 和用户授权上下文，不能以本文件代替。

- 已验收合并：S1 [PR #21](https://github.com/Aspeternity/SeekPulse/pull/21)、S2 [PR #22/#23](https://github.com/Aspeternity/SeekPulse/pull/23)、S3 [PR #24](https://github.com/Aspeternity/SeekPulse/pull/24)。S3 合并 commit `f5c3f3c22703f4980206fff92212396330f2fac1`，main G0 push [#38544956951](https://github.com/Aspeternity/SeekPulse/actions/runs/38544956951) 4/4 PASS。
- 2026-10-14 用户最新明确指示 **「批准开发」**，直接回应 S4 / Issue #13 开发许可请求。S4 独立分支 `feat/s4-01-routing-notifiers`，唯一写入 ChatGPT；用户未批准 S4 代码验收/合并。
- S4 工作项：保留 S2 单一任务队列、User+Post+Target 幂等；用户默认目标与逐规则覆盖，普通/紧急优先级、多目标限流与公平；Telegram 原生/Bark/ntfy 受限适配，SQLite 策略/冷却且所有外部消息发送都在数据库事务外。具体增量设计 ADR-0004。
- **重要边界**：S4 只能绑定已存在的合法 target_id，完整 Bark/ntfy 非 TG 目标身份创建/旧目标迁移尚待审核；`app/main.py` 依然是旧 FeedPoller，正式切换及真实 Token/Session 和推送、生产部署均未授权。不把模拟 API 接受当作手机真实送达。
- S0 研究 Draft PR #17–#20 仍未授权合并，互不干涉。
- 下一步：在 S4 Draft PR 确认精确 HEAD 的 G0、S1、S2、S3、S4 CI 或所需全量回归；失败先复现定位，不合并 main；准备阶段验收清单。S5–S7、发布/Tag/部署均未授权。
