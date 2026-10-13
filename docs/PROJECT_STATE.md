# SeekPulse 项目状态（S0 启动快照）

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
| [S0-01 #5](https://github.com/Aspeternity/SeekPulse/issues/5) | ChatGPT 当前写入负责人；分支 `research/s0-01-telegram-source-probe`；公开 TG 结构/解析与恢复可行性初步验证 |
| [S0-02 #6](https://github.com/Aspeternity/SeekPulse/issues/6) | 已授权但未执行；24h+ TG/RSS 发现时间与覆盖对照需要持续采样 |
| [S0-03 #7](https://github.com/Aspeternity/SeekPulse/issues/7) | 已授权但未执行；Apprise/Bark/ntfy 与资源 |
| [S0-04 #8](https://github.com/Aspeternity/SeekPulse/issues/8) | 已授权但需等待 #5–#7 证据；最终 Go/No-Go 需用户验收 |

## 当前证据与阻断

- 可从 [TG 官方频道公开预览](https://t.me/s/nodeseekc) 找到 NodeSeek 原帖链接样本；**不等于 Telethon 实际 MTProto 延迟测试**。
- S0 公开来源探针为研究脚本，不得替代正式 SourceAdapter。
- 当前执行环境的 DNS 访问失败，不能提供真实 RSS 与 TG 的同机网络对照；需要受控测试环境继续验证。
- 真实 TG 监听恢复需要**专用账号**和受保护的会话，仅在用户管理的测试环境中操作。**不得收集/上传凭证至 PR、Issue 或聊天记录。**
- 当前尚未完成推送端到端和 1vCPU/1GiB 资源验收。

## 唯一下一动作

执行 [S0-01 #5](https://github.com/Aspeternity/SeekPulse/issues/5) 的只读、脱敏、可复现验证，核对研究分支 PR 当前 SHA 和 CI；形成初步报告，并标记 MTProto/持续时延实验所需外部条件。**不得合并 main、发布或自动执行 S1。**
