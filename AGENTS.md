# SeekPulse — AI 与人工协同开发总规则

> **必须先读本文件。** 本文件适用于 ChatGPT、Claude、Gemini、人类开发者以及自动化编码代理。`CLAUDE.md` 和 `GEMINI.md` 只负责指向本文件，不建立第二套规则。

## 0. 当前授权边界（最高优先级）

- **2026-10-15 已核实 main 基线：** S7 Docker-01～08 各自通过离线验收，且各 PR 随后获得独立 Squash Merge 授权。Docker-08 [Issue #46](https://github.com/Aspeternity/SeekPulse/issues/46) CLOSED/completed、[PR #47](https://github.com/Aspeternity/SeekPulse/pull/47) MERGED；最新 main `e86b10bd324f083955b1d38a340bbca092b0dc03`，合并后 [G0 #38723709559](https://github.com/Aspeternity/SeekPulse/actions/runs/38723709559) 4/4 PASS。**main 的 opt-in `Dockerfile.v11` 已从 Debian Trixie 改为官方 pinned Python 3.11 Alpine 3.24（多架构官方 base index digest `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`）**。旧 Dockerfile、两份 Compose、原 requirements pins、app 业务与数据/通知契约保持不变。
- **当前仅批准 Docker-09 / Issue #48 / Draft PR #49 独立离线工作**：用户针对“**启动 Docker-09 发布前安全审查与离线准备，明确不包括实际 GHCR push、Tag/Release 和 NAS/PVE 实机**”单独回复原话「批准」。唯一写入负责人 **ChatGPT**，独立分支 `research/s7-docker-09-prepublish-security-offline`。只允许以当前代码做 GHCR 发布前供应链流程审计、原生 AMD64/ARM64 临时 GitHub Runner 本地完整 V1.1 镜像 + 公开新鲜 Trivy OS/PyPI/CycloneDX Medium/Low 逐条核验、纯离线 fail-closed preflight/负向测试/ADR、签名/来源与回滚**计划**、相关治理/交接文档更新。**尚未进行 Docker-09 人工阶段验收，也未批准 PR #49 Ready/合并**。
- **风险与来源不可混淆**：Docker-08 完整 Alpine 镜像当时两架构各 OS/PyPI High/Critical 0、**Medium 7/Low 1**（新 CVE 必须复扫），并非“已安全批准发布”。历史 Debian Trixie 的 44 条 OS High package×CVE / 8 个去重 CVE 是**旧镜像历史风险**，Alpine 不再报告这 8 项不等于 Debian 已修复。即使新扫描 High/Critical 0，仍 `REVIEW_REQUIRED_NONBLOCKING`、`release_ready=false`、`release_authorized=false`、GHCR `NOT_PUBLISHED`。当前没有可核实的 SeekPulse GHCR 远端多架构 index digest；**Docker 官方基础镜像 digest 不等于 GHCR 最终镜像 digest**。
- **绝对禁止越过的闸门**：不得未经再次独立授权 PR 合并/main 修改、GHCR login/push、`packages:write`、Git Tag/Release、签名/attestation 正式发布、访问用户 NAS/PVE/Portainer/群晖/VPS、生产 SQLite/Token/Session/备份、TG/Bark/ntfy 真实通知或 Gate D–G/48–72h。父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) **OPEN/status:blocked**。Docker-09 完成后**先申请仅离线阶段验收**，如通过再单独申请 PR #49 精确 HEAD Ready + Squash Merge 权限；实际 GHCR 发布/真实 NAS/PVE Docker 部署各自另请批准。GitHub 最新代码/PR/CI + 最新明确用户审批优先于任何静态快照。

## 1. 开工前必须执行的核验

1. 读取本文件、`docs/PLAN.md`、`docs/APPROVALS.md` / `docs/APPROVALS.json`、`docs/ROADMAP.md`、相关 ADR。
2. 读取对应 GitHub Issue 的目标、唯一写入负责人、验收条件和依赖项，并确认当前阶段确已获授权。
3. 核对远端仓库、默认分支 SHA、工作分支 SHA、关联 Draft/正式 PR、该 SHA 对应的最新 CI、已记录的用户实机验收。
4. 本地先运行 `git status --short`，检查未提交内容和他人的分支，禁止覆盖。
5. 可使用 `python scripts/context_report.py --repo Aspeternity/SeekPulse` 辅助收集状态；**该报告是观测快照，不取代 GitHub 与审批证据。**
6. 如果 GitHub 无法访问、结果过期或数据冲突：将结论标记为 `UNKNOWN/UNVERIFIED`，不能猜测或根据旧聊天记录继续写入。

## 2. 修改边界

- 每项开发工作必须对应唯一 Issue，有清晰的范围、验收条件、负责人和依赖项；使用独立分支及 PR。
- 同一 Issue 同一时刻只有一个写入负责人。其他 AI 可审查，不能直接覆盖负责人的分支；交接时必须在 Issue 记录负责人变更、HEAD SHA、剩余问题。
- 一次修改聚焦一个目标。Bug 必须先复现、先核验既有测试，再改根因；不堆补丁、不留无用诊断接口和死代码。
- 任何架构/协议/持久化契约变更，先提交 ADR 和影响分析，获得所需审批再实施。
- 尊重既有上游行为，G0 阶段不修改 `app/`、`Dockerfile`、`requirements.txt`、现有 README、现有 Compose。

## 3. 测试、CI、验收和发布不是同一件事

- 必须区分：`已审批` → `开发中` → `已提交` → `CI 通过` → `待实机验收` → `实机验收通过` → `获准合并` → `已合并` → `获准发布` → `已发布`。
- 只有**与当前 HEAD SHA 精确对应**的最后一次完整绿色 CI 才能报告“CI 通过”；检查没运行或查不到时为 `UNKNOWN`。
- PR 包含测试说明、风险和回滚方式。任何后续代码提交都使原来的 HEAD CI 证据失效。
- 不得自动合并、自动发布、自动更新生产环境；CI 绿并不代表用户验收或授权。
- 临时调试代码在问题验收后移除；长期有效的回归测试必须保留。

## 4. 数据、安全与许可

- 仅以 AI-XMLY MIT 上游为代码基线，保留许可和历史；Hootrix GPLv3 项目只能借鉴理念，不能未经许可直接复制代码。
- 不记录、不回显 Bot Token、API Hash、Telegram Session、管理员密码；不把凭据放入源码、Issues、PR、日志或交接报告。
- 数据库迁移、账号登录、生产部署、网络暴露、访问控制变更均需明确阶段与审批。

## 5. 每次工作结束必须留下的记录

在 GitHub Issue / PR 更新：本次范围、已做与未做、变更文件、提交 SHA、CI run/结论、实际验收、风险、下一个操作、是否还需用户批准。`docs/PROJECT_STATE.md` 只作参考摘要，不能取代这些实时事实。

推荐的交接回复结构：`阶段 / 已授权范围 / 当前 Issue 与负责人 / HEAD SHA / PR / 最新 CI / 实机验收 / 阻断 / 唯一下一步`。

## 6. 失联、冲突和接管

- 会话突然中断时，从已推送的提交、Draft PR 和 Issue 恢复；未推送的本地内容必须单独标记，不能当作已同步。
- 同一个 Issue 已存在活动分支/PR/负责人时，禁止新建平行实现，先核实并记录接管。
- 当文档与 GitHub 不一致，GitHub 代码、CI 及明确的用户审批证据优先；更新文档之前先调查差异。

## 7. 文档索引

- 已批方案：`docs/PLAN.md`
- 审批边界：`docs/APPROVALS.md` / `docs/APPROVALS.json`
- 阶段路线图：`docs/ROADMAP.md`
- 架构契约：`docs/ARCHITECTURE.md`
- ADR：`docs/decisions/`
- 测试矩阵：`docs/TEST_MATRIX.md`
- 最新状态参考：`docs/PROJECT_STATE.md`
- GitHub 实际任务：Issues / PR（建档前种子见 `docs/ISSUE_SEED.json`）
