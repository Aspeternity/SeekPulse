# SeekPulse — 当前阶段 S2 开发参考索引

> 本文件只是 2026-10-14 的快照。新对话必须以 GitHub Issues、PR、main SHA、最新 CI 与用户真实批准为准。

- main（S2 启动时）：94f26d2a1f58924c9e060698a655dd28601ace94；S1 [PR #21](https://github.com/Aspeternity/SeekPulse/pull/21) 已经用户单独批准 Squash 合并，合并后 CI [#38495140224](https://github.com/Aspeternity/SeekPulse/actions/runs/38495140224) 4/4 PASS。
- S0-04 条件式 Go 已验收，S0 研究 PR #17/#18/#19/#20 仍保持 Draft；S0 网络受人为调试的 10 秒组无法证明 TG 稳定提速。
- 用户最新明确授权：在“是否批准开始 S2 开发？”后回复“批准”；S2 [#10](https://github.com/Aspeternity/SeekPulse/issues/10) 规范化帖子/规则三态，[#11](https://github.com/Aspeternity/SeekPulse/issues/11) SQLite 原子目标级投递状态；每 Issue 唯一写入负责人 ChatGPT，分别 Draft PR。
- S2-01 分支 feat/s2-01-canonical-post-rules（从 main 94f26d2 派生），S2-02 分支 feat/s2-02-sqlite-delivery-queue（待 S2-01 模型稳定后建立依赖分支）。两者 HEAD SHA/CI 必须在各自 Issue 重新核验。
- 本阶段只开发领域模型、SQLite 核心与无网络的回归；不接入真实 TG/Bot 推送、不改变生产。S3–S7、任何 PR 合并、版本发布、部署均没有授权。
- 已批准设计：docs/ARCHITECTURE.md、docs/decisions/ADR-0002-delivery-semantics.md；SQLite 短事务，不在 HTTP 发送时保持写锁，目标级唯一任务，不承诺严格 exactly once。
- 唯一下一步：在研究分支写好 S2-01 并核对当前 HEAD CI；随后可在独立 stacked 分支实施 S2-02，最终分别提交用户验收，不能擅自合并。
