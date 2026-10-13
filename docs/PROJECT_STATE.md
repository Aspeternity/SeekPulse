# SeekPulse 当前项目状态（G0 交接索引）

> 更新：2026-10-13。**这是已核实事实的时间快照，不是实时 GitHub 状态。** 新会话必须先按 `AGENTS.md` 重新检查远端提交、PR、Issues、对应 SHA 的 CI 和用户审批，冲突时暂停操作。

## 审批与开发边界

- 用户正式批准 **SeekPulse V1.1 开发方案**，并于 2026-10-13 **确认 G0 验收通过**；目前仍**只存在 G0 阶段授权**。
- **S0–S7 均未获执行授权**。创建这些阶段的 Issue 仅是规划，不意味着可以开始。
- **明确禁止未经额外授权**：合并 `main`、发布版本或 Tag、修改生产环境、覆盖已有分支。
- G0 最终用户验收：**已确认通过**（2026-10-13 用户在 G0 验收报告后回复“批准”）；G0 PR 仍为 Draft，**未获合并授权**。

## GitHub 核验入口

| 项目 | 截至本次记录的核验结果 |
|---|---|
| 仓库 | <https://github.com/Aspeternity/SeekPulse>，由 AI-XMLY 上游 Fork，保留 MIT 与 Git 历史 |
| `main` 基准 | `8107b18e99148127bc6c993ac8384959ac871f6d`（本次核实时仍未改变） |
| G0 工作分支 | `chore/g0-engineering-foundation`（**从 GitHub 读取最新 HEAD，不使用本文的旧提交号**） |
| G0 Draft PR | [#1](https://github.com/Aspeternity/SeekPulse/pull/1)，目标 `main`，未合并 |
| 保护规则 | [Protect main](https://github.com/Aspeternity/SeekPulse/rules/25001077)：Active；默认分支、必经 PR、禁止删除和强推、要求目标分支最新与四项 CI |
| G0 实际任务 | [#2](https://github.com/Aspeternity/SeekPulse/issues/2)、[#3](https://github.com/Aspeternity/SeekPulse/issues/3)、[#4](https://github.com/Aspeternity/SeekPulse/issues/4) |
| S0 已规划任务 | [#5–#8](https://github.com/Aspeternity/SeekPulse/issues)；带 `status:blocked`，**未授权** |
| S1–S7 已规划任务 | [#9–#16](https://github.com/Aspeternity/SeekPulse/issues)；带 `status:blocked`，**未授权** |
| 已创建的 Issue | 共 15 个，稳定标识 G0-01～03、S0-01～04、S1-01～S7-01 |
| 历史 CI 证据 | [PR Run #38403905292](https://github.com/Aspeternity/SeekPulse/actions/runs/38403905292) 对 `241375139a4d58ce7c821c2d5357500fe1d20799` 四项全绿；**本次验收记录提交会产生更新的 HEAD，必须重新检查最新 SHA 的 CI** |

## 新 AI 的唯一接续流程

1. **注意：G0 文件目前只在工作分支和 Draft PR 中，尚未合并 main。** 先读取 `chore/g0-engineering-foundation` 分支的 `AGENTS.md`、`docs/APPROVALS.md` 和本文件；不要从 `main` 找这些未合并文档。
2. 读取 GitHub Issue #2～#16 和 Draft PR #1，核对真实状态、当前写入负责人及分支提交。
3. 核对四项 GitHub Actions 必需检查对 **当前 PR HEAD SHA** 的结果，不能沿用本文件提到的历史运行。
4. 确认 `main` 仍保留基线，并核验审批记录：**G0 已验收通过；S0 尚未授权**。若有更新授权，应核对原文和上下文。
5. 唯一下一步：**确认当前 PR HEAD 的最新 CI，保持 Draft PR，向用户单独申请 S0 授权；未经明确合并授权不得修改 main。**

## 事实权威顺序

批准范围：`docs/APPROVALS.md` / `docs/APPROVALS.json` 与后续真实用户指令；代码：Git SHA；任务：GitHub Issues；审查：PR；CI：当前 SHA 对应检查；用户验收：明确的用户确认。本文仅是索引。
