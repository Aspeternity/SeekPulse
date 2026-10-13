# G0 工程建档 — 实际 GitHub 交接记录

> 核验日期：2026-10-13。仓库信息随时间变化；**必须以 GitHub 实时核查为准**，不能引用此记录代替最新 CI 或用户授权。

## 本轮实际建档

- 仓库：<https://github.com/Aspeternity/SeekPulse>，保留上游 `AI-XMLY/nodeseek-rss-telegram-bot` Git 历史及 MIT LICENSE。
- `main` 保留上游基准 `8107b18e99148127bc6c993ac8384959ac871f6d`；没有合并任何 G0 代码。
- 独立分支：`chore/g0-engineering-foundation`。
- [Draft PR #1](https://github.com/Aspeternity/SeekPulse/pull/1)：仅工程治理、任务模板、基础 CI、交接工具及测试；未合并。
- 初始提交 `e2289b478a3a45a2b12906b57243a38cd105dce5` 新增 30 个工程文件，不改上游 `app/`、`Dockerfile`、`docker-compose.yml`、`requirements.txt`。
- [CI #38393797865](https://github.com/Aspeternity/SeekPulse/actions/runs/38393797865) 在上述初始提交上四项成功：Governance and handoff、Python 3.11 baseline、Python 3.12 baseline、Unmodified upstream Docker build。
- [Protect main Ruleset](https://github.com/Aspeternity/SeekPulse/rules/25001077)：Active；四项必需检查匹配 GitHub Actions，要求 PR、最新分支检查、审查讨论解决；禁止删除/强推；无 bypass。
- GitHub Issues 共 15 项实际创建：G0 [#2](https://github.com/Aspeternity/SeekPulse/issues/2)、[#3](https://github.com/Aspeternity/SeekPulse/issues/3)、[#4](https://github.com/Aspeternity/SeekPulse/issues/4)；S0 [#5–#8](https://github.com/Aspeternity/SeekPulse/issues)；S1–S7 [#9–#16](https://github.com/Aspeternity/SeekPulse/issues)。后续阶段的 Issue 均保留 `status:blocked`。
- 多 AI 规范：根目录 `AGENTS.md` 为唯一主规则，`CLAUDE.md` 和 `GEMINI.md` 仅引用该规则；Issue、PR 和状态报告协同工作。
- `scripts/bootstrap_issues.py` 默认 dry-run，正式执行时核查已存在的稳定任务标识；**不要重复创建 #2–#16**。

## 强制注意

1. 当前 **只批准 G0**；S0–S7 只规划，未执行。
2. G0 **尚未获用户最终验收**；CI 绿不等于验收通过。
3. 此文件更新本身会产生新的分支提交，**必须重新验证该新 PR HEAD 的 CI**；历史 CI 绿不得代替当前 CI。
4. 工程文件还在 G0 工作分支，`main` 尚没有 `AGENTS.md` 等文件。所有 AI 新会话必须先切换/读取该工作分支。
5. 未经用户明确授权，不合并 `main`、不发布、不操作生产环境，也不能提前开始 S0。

## 新会话快速恢复

1. 读取分支 `chore/g0-engineering-foundation` 的 `AGENTS.md`、`docs/PLAN.md`、`docs/APPROVALS.md`、`docs/PROJECT_STATE.md`。
2. 检查 [PR #1](https://github.com/Aspeternity/SeekPulse/pull/1) 最新 HEAD、四项对应 GitHub Actions、Issue #2–#16、Ruleset、`main` SHA。
3. 可运行 `python scripts/context_report.py --repo Aspeternity/SeekPulse` 辅助核对；若 GitHub 无法访问，将远端状态标为 UNKNOWN。
4. 向用户报告核验结果并申请 **G0 阶段验收**。得到单独 S0 授权后才可进入技术可行性验证。
