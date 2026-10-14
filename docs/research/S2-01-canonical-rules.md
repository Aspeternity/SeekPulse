# S2-01：规范化 NodeSeek 帖子与三态规则引擎

状态：已获用户授权开发，待独立分支 CI、用户验收、合并审批。关联 Issue #10。基础设计来自已批 V1.1 docs/ARCHITECTURE.md。

## 核心契约

1. app/domain.py 是纯内存、无 IO 的领域层。只有官方 NodeSeek 帖子链接 nodeseek.com / www.nodeseek.com 的正数 64 位帖子 ID 可以统一身份；只认 /post-ID 或 /post-ID-page，拒绝伪造站点、私人凭据、标题相似推断。稳定链接采用 https://www.nodeseek.com/post-ID-1。S3 的 TG/RSS 适配要转换为 SourceObservation，不在 S2 登录 TG。
2. SourceObservation 包含 source, event_id, post_id, observed_at, title/summary/category/link。None 明确表示缺失，空字符串表示已观察为空；必须提供带时区的观测时间并转为 UTC；(source,event_id) 用来去重，字段来源记录 FieldOrigin。未知分类保持未知、保留原观察值，绝不绕过分类限定。
3. CanonicalPost 只合并相同 post_id 的来源观察；后到数据只补未知字段而不覆盖已知字段；来源事件回放幂等。保存每来源首次观察时间。不把内存状态误说成跨重启数据已落库，持久化与任务事务由 #11 负责。
4. RuleSet 中多个独立单词为 OR，组合子句内部为 AND；屏蔽优先，显式分类必须核验。标题/摘要未知不能当作不存在。返回 matched/not_matched/insufficient_data 三态；如果已出现屏蔽词则立即 not_matched，未获取完整可检索文本时不能宣称屏蔽词不存在。只有正向条件已满足且无未知阻断条件时可提前 matched。
5. 本模块尚未替换现有 app/rss.py 和 app/poller.py；本阶段不改变正在运行的原版行为。接入真实 TG/RSS、规则变更事件、发送/通知是 S3/S4 的独立阶段。

## 测试和边界

- 双来源同帖、1000 个同标题不同 ID、幂等、来源时间、字段来源、非法 URL/ID、时区保护。
- OR/AND、屏蔽词、分类缺失/不符、摘要不完整、后到补全三态。
- G0 全套 Python 3.11/3.12 回归及 S2 专项 3.11/3.12 都需要在当前 SHA 全绿。所有测试离线，无真正 RSS/TG/设备/VPS 验证。
- 尚未实现渠道字段编辑删除、SQLite 来源落盘、任务队列或生产对接；不得为了通过测试声称这些能力已经通过。
- 本 PR 保持 Draft；合并、S3、发布和生产都需要单独审批。
