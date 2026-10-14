# SeekPulse — S7 / Issue #16 规划阶段交接快照

> 截至 2026-10-14：本文件只是检索索引，不取代用户授权、实时 GitHub、准确 SHA/CI 或实机证据。

- **仓库与基线：** https://github.com/Aspeternity/SeekPulse。S1–S6 已分别离线阶段验收、独立获得合并授权并入 main：PR #21–#27。S6 squash 后 `main`=`12ce325f4ab09b3e596398d515ab5e7704d89729`，其 G0 push [#38567964267](https://github.com/Aspeternity/SeekPulse/actions/runs/38567964267) **4/4 PASS**，Issue #15 closed。新会话应再次实时确认。
- **最新用户批准**：「批准」，紧邻问题是“是否批准启动 S7 / Issue #16 的验收规划与准备？真实 VPS 操作、部署和正式发布仍需另行审批”。**只准做规划、只读代码审查、脱敏模板、跨 AI 交接规程、独立文档 Draft PR + CI。**不准启动 S7 真实运行、触碰 VPS/Session/DB、合并或发布。
- **当前任务**：Issue [#16](https://github.com/Aspeternity/SeekPulse/issues/16)，唯一负责者 ChatGPT（文档规划），工作分支 `docs/s7-01-acceptance-readiness`，本次变更只应为治理和 S7 验收文档；PR HEAD 与 CI 必须重新在 GitHub 精确核验。S0 研究 PR #17–#20 仍 Draft/未合并。
- **BLOCKER B01**：现有 `app/main.py` 只启动旧 RSS `FeedPoller` 和 Bot，Dockerfile 只安装旧 `requirements.txt`；S3 双来源、S4 多渠道 Worker、S5 Web 尚未集成进正式入口。**不能**把运行旧 Bot 48–72h 声称为 V1.1 全功能验收。
- **BLOCKER B02/B03**：Bark/ntfy 非 TG 新目标的正式身份注册/迁移和安全的旧 FeedPoller→S2/S3/S4 切换尚无独立批准的可部署实现；重复发送、单 TG Session 所有权和历史基线需单独审查和批准。
- **BLOCKER B04**：真实 VPS/账号、真正 Telegram/Bark/ntfy 发送、SQLite/WAL 备份/切换、48–72h 计时和资源/延迟测试尚未授权，**现场验收 NOT_STARTED**。
- **规划交付：** `docs/research/S7-01-vps-final-acceptance-plan.md`（Gate A–G、48–72h 与指标）、`docs/research/S7-02-independent-ai-handoff.md`（无旧对话 AI B）、`docs/research/S7-03-observation-template.md`（空白、脱敏、不虚构数据）。
- **唯一下一步**：完成本 docs-only Draft PR CI 并申请用户确认 S7 规划是否可作为后续验收依据；真实集成缺口需**另行批准设计/开发**，VPS 只读预检、灰度真发信、连续观测、故障恢复/部署、最终验收/Release 也各自另行授权。禁止擅自合并 main。
