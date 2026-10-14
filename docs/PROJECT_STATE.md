# SeekPulse 实时开发交接索引（S1）

> 快照日期：2026-10-14。此文件仅为参考索引；新对话必须重新核对 GitHub Issues、PR、main/分支 SHA、最新 CI 与用户审批。

## 授权边界

- V1.1 方案已批准：RSS + 官方 Telegram 频道为两个可独立启停的来源。不承诺 TG 比 10 秒 RSS 更快。
- G0 已验收；S0-04 条件式 Go 已由用户于 2026-10-14 验收，见 [Issue #8](https://github.com/Aspeternity/SeekPulse/issues/8)。
- 用户在明确询问是否验收 S0-04 并正式授权 S1（Issue #9）后回复“批准”；[S1 Issue #9](https://github.com/Aspeternity/SeekPulse/issues/9) 已获开发授权，范围仅为原版行为回归、依赖与 CI。
- 未授权：S2–S7、合并任何 PR 到 main、Release/Tag、生产部署、真实通知推送、擅自改上游业务行为、上传凭据/Session/私有数据库。

## GitHub 工作入口

| 对象 | 创建 S1 时的记录（新会话必须重新核对） |
|---|---|
| 仓库 | https://github.com/Aspeternity/SeekPulse |
| main | 4900a52eef1583804b44bcd00145767df7fc1e26 |
| S0-01 | #5 / Draft PR #17 / 54dc579，保持未合并 |
| S0-02 | #6 / stacked Draft PR #19 / 60dbaf5，保持未合并 |
| S0-03 | #7 / Draft PR #18 / 38b8c79，保持未合并 |
| S0-04 | #8 验收通过 / Draft PR #20 / 900815e，报告仍未合并 |
| S1-01 | #9 / 写入负责人 ChatGPT / 分支 test/s1-01-upstream-regression-baseline / PR HEAD 与 CI 以 Issue 最新记录为准 |
| CI | G0 原有 Python 3.11/3.12 + 基础工程检查；S1 增加独立无网回归检查 |

## 技术结论与风险

- RSS 60s：累计 65min，有效配对 24，TG 先 19，RSS 先 5；RSS 相对 TG P50 +12.209s。
- RSS 10s：累计 195.02min，有效配对 33，TG 先 18，RSS 先 15，P50 +0.154s；P95 +1408.214s。用户在 3h 运行中调试多次网络且记不清时段，不能把 P95 当作稳定 RSS 延迟。
- Apprise 2.0.1 的 Bark/ntfy 回环模拟 10/10 PASS，受限 CI 容器 10/10 PASS；真实手机/APNs、全栈 VPS 容量尚未验证。
- 上游 FeedPoller 当前按每用户+帖子记录送达，只要一个目标发送成功，其他失败目标不会独立重试。这是明确的遗留风险，不是 V1.1 目标；S2/S4 需要用户另行授权重构。
- 上游首次 RSS 轮询只标记旧帖已读，普通关键词独立 OR、组合关键词 AND、屏蔽优先、分类过滤，以及多用户数据隔离，均是 S1 回归对象。

## 唯一下一步

查看 [S1 #9](https://github.com/Aspeternity/SeekPulse/issues/9) 所指最新 Draft PR/HEAD/CI，验证隔离回归后向用户申请 S1 验收，不自动合并 main 或进入 S2。
