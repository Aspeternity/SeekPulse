# 跨对话与多 AI 开发交接工作流

> 统一执行规范见根目录 `AGENTS.md`；本文件只解释操作细节，不引入另一个审批来源。

## 1. 恢复进度的标准路径

1. 阅读 `AGENTS.md`、`docs/APPROVALS.md`、`docs/PLAN.md`、`docs/ROADMAP.md`、相关 ADR。
2. 从远程查看默认分支、当前任务 Issue、相关分支和 PR 的 **SHA、状态、负责人**。
3. 对 PR HEAD SHA 查最新全部 CI run/checks；不能用 main 的绿灯代替 PR HEAD，也不能用上一提交的绿灯代替最新提交。
4. 审核实机验收证据及用户授权，不可从 CI 自动推断。
5. 生成可核实的上下文报告：`python scripts/context_report.py --repo Aspeternity/SeekPulse`。
6. 若任务负责人不一致、需要接管他人工作分支，先更新 Issue 和交接说明，**不擅自重写远端代码**。

## 2. 中断时留存

Issue/PR 必须写明：阶段、任务唯一编号、负责人、已完成、未完成、分支、HEAD SHA、最新 CI、测试和生产验收、当前问题、下一动作、是否需要用户同意。未 push 的本地修改单独标注，不能声称保存在远程。

## 3. 同时使用 Claude / Gemini / ChatGPT

- 可以在不同 Issue 上并行分析，但依赖的共同接口应先稳定；只有一个 AI 拥有同一 Issue 工作分支的写权限/责任。
- 审查 AI 主要写 PR Review，不应直接覆盖负责人代码。
- 任务接管必须通过 Issue 评论或正文记录负责人更换和接管 SHA；需要获得相应工作授权。
- 状态摘要只能作为索引。不同 AI 若得出不一致结论，应暂停操作并报告证据差异。

## 4. 通用新对话指令

```text
继续 SeekPulse 项目。请先读取 AGENTS.md、docs/APPROVALS.md、docs/PLAN.md、docs/ROADMAP.md 和相关 ADR；然后独立访问 GitHub 核对当前 main/工作分支 SHA、Issues、PR、最新 CI、真实验收及唯一任务负责人。先向我报告可核实的完成状态、阻断和建议下一步，不要未经授权修改代码。不能访问远程时报告 UNKNOWN，不能凭旧聊天或状态摘要推断已完成。未经我明确批准，不合并 main、不发布版本、不操作生产环境。
```

## 5. 交接报告功能边界

`scripts/context_report.py` 为只读工具，可通过环境变量 `GITHUB_TOKEN` 访问 GitHub；不要求把 Token 写入文件。网络/API 失败应显示 `UNKNOWN`；无网络的 `--offline` 报告**只表示本地快照**，不能代表实时远程状态。支持 Markdown/JSON、指定 Issue。

## 6. G0 后的跨 AI 验收

G0 至少验证报告工具能安全处理缺失远端和工作区未提交情况；S7 完整跨 AI 验收需由无旧对话上下文的第二种 AI 独立判断 SHA/PR/CI/验收/审批和唯一下一动作。**S7 规划材料**：[`docs/research/S7-02-independent-ai-handoff.md`](research/S7-02-independent-ai-handoff.md)；该规程尚未实际运行，不能声称跨 AI 验收通过。
