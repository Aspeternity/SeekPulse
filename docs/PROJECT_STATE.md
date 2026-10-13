# SeekPulse 项目状态（S0-01 实验验证中）

> 2026-10-13 记录。**快照不是实时 GitHub 事实**：所有 AI 必须读取 `AGENTS.md`、审批记录及 Issues/PR/最新 HEAD CI，并在有冲突时停止写入。

## 已核实的授权

- SeekPulse **V1.1 已批准**。
- **G0 已验收，用户单独批准合并 PR #1，现已合并**；`main` 基准为 `4900a52eef1583804b44bcd00145767df7fc1e26`，合并后 [CI #38407234902](https://github.com/Aspeternity/SeekPulse/actions/runs/38407234902) 4/4 PASS。
- **用户于 2026-10-13 明确批准进入 S0**。本次授权仅为 Issues #5–#8 技术可行性验证。
- **未授权**：S1–S7 业务开发、合并新增 PR、Release/Tag、任何生产环境操作。
- S0 尚未实机验收；未做出 Go/No-Go 决定。

## 工作任务（截至本次快照）

| 任务 | 进度与负责人 |
|---|---|
| [S0-01 #5](https://github.com/Aspeternity/SeekPulse/issues/5) | ChatGPT 当前写入负责人；[Draft PR #17](https://github.com/Aspeternity/SeekPulse/pull/17)；分支 `research/s0-01-telegram-source-probe`；公开 TG/RSS 采样与链接解析通过；隔离 Telethon 只读测试工具已实现并经过 8 项离线模拟 + 固定版本库接口 CI；**真人 MTProto 事件、停机恢复待实测** |
| [S0-02 #6](https://github.com/Aspeternity/SeekPulse/issues/6) | 已授权但未执行；24h+ TG/RSS 发现时间与覆盖对照需要持续采样 |
| [S0-03 #7](https://github.com/Aspeternity/SeekPulse/issues/7) | 已授权但未执行；Apprise/Bark/ntfy 与资源 |
| [S0-04 #8](https://github.com/Aspeternity/SeekPulse/issues/8) | 已授权但需等待 #5–#7 证据；最终 Go/No-Go 需用户验收 |

## 当前证据与阻断

- 可从 [TG 官方频道公开预览](https://t.me/s/nodeseekc) 找到 NodeSeek 原帖链接样本；**不等于 Telethon 实际 MTProto 延迟测试**。
- S0 公开来源探针为研究脚本，不得替代正式 SourceAdapter。GitHub Actions [Run #38409533402](https://github.com/Aspeternity/SeekPulse/actions/runs/38409533402) 实际 HTTP 采样：TG 公开 HTML 20 个唯一帖子、RSS 20 个条目/20 个唯一帖子，交集 20；**不是 MTProto 或 24h 时效验收**。
- 当前执行环境的 DNS 访问失败，不能提供真实 RSS 与 TG 的同机网络对照；需要受控测试环境继续验证。
- 真实 TG 监听恢复需要**专用账号**和受保护的会话，仅在用户管理的测试环境中操作。**不得收集/上传凭证至 PR、Issue 或聊天记录。**
- S0-01 专用测试工具及说明：[scripts/s0_mtproto_probe.py](../scripts/s0_mtproto_probe.py) 和 [S0-01 受控测试操作手册](research/S0-01-MTProto-test-runbook.md)。工具默认写入用户目录私有 Session 与脱敏 SQLite，**不发送 Telegram Bot 消息、不修改上游 app/**。
- [G0 基线 CI #38413041301](https://github.com/Aspeternity/SeekPulse/actions/runs/38413041301) 四项全绿；[S0 诊断 CI #38413041414](https://github.com/Aspeternity/SeekPulse/actions/runs/38413041414) 两项通过，包含 Telethon 1.45.0 的真实库离线导入验证和 8 项模拟测试。**仅对应 `053137921c2d9e9d1c3b8f23facd29a34b3acd1d`，后续新提交需重新验 CI。**
- 真人 Telethon 账号授权、实际新帖事件和真实停机补查均 **UNVERIFIED**；没有任何可分享的 Session/Token/API Hash 凭证。S0-02 的 24 小时延迟对照仍未开始。
- 当前尚未完成推送端到端和 1vCPU/1GiB 资源验收。

## 唯一下一动作

**等待用户选择并准备非生产测试设备与专用 Telegram 账号**，按 [S0-01 受控操作手册](research/S0-01-MTProto-test-runbook.md) 在本机完成 auth / listen / 离线后 listen / report；只提供脱敏汇总，审核是否有新帖真实触发、漏消息补查及风险。当前 [Draft PR #17](https://github.com/Aspeternity/SeekPulse/pull/17) 不合并，S0-02 长期对照尚待开展；**不得触碰 main、发布或启动 S1。**
