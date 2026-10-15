# SeekPulse — AI 与人工协同开发总规则

> **必须先读本文件。** 本文件适用于 ChatGPT、Claude、Gemini、人类开发者以及自动化编码代理。`CLAUDE.md` 和 `GEMINI.md` 只负责指向本文件，不建立第二套规则。

## 0. 当前授权边界（最高优先级）

- **2026-10-15 最新 main 基线**：Docker-01～07 各自完成离线范围阶段验收，PR 均在之后获单独合并授权；Docker-07 [Issue #44](https://github.com/Aspeternity/SeekPulse/issues/44) CLOSED/completed、[PR #45](https://github.com/Aspeternity/SeekPulse/pull/45) Squash MERGED。main `30c246be5f7cb11fb315ccecc882798b75f28160`，合并后 [G0 #38718379825](https://github.com/Aspeternity/SeekPulse/actions/runs/38718379825) 4/4 PASS。当前 main `Dockerfile.v11` **仍为 Debian Trixie**，实际 OS High 44 包×CVE 记录 / 8 个独立 CVE，Python High 0，**GHCR BLOCKED_HIGH_OR_CRITICAL / NOT_PUBLISHED**。
- **当前新批准的独立阶段**：用户在明确申请“**启动 Docker-08：Alpine 正式运行环境迁移与离线兼容性验证的方案设计及离线开发；本次不包含合并、发布或实机部署**”后答复「批准」。唯一写入负责人 **ChatGPT**，独立 [Issue #46](https://github.com/Aspeternity/SeekPulse/issues/46)、[Draft PR #47](https://github.com/Aspeternity/SeekPulse/pull/47)，分支 `feat/s7-docker-08-alpine-runtime-offline`。**只允许在 Draft 分支内修改 opt-in `Dockerfile.v11` Alpine 3.24 官方多架构 pinned base、与之直接相关的 fail-closed OS+PyPI CVE/CI 契约、ADR、离线原生双架构 WAL/TLS/模拟通知/权限回归**。这不等于正式批准在 main 使用 Alpine，亦不等于用户阶段验收或 PR 合并许可。
- **现有底线**：Docker-07 仅证明 Alpine **本地完整候选**两架构各 319 单元测试和当时 Trivy OS/PyPI High/Critical=0；旧 Debian CVE 并非自动“修复”。在 Docker-08 最新 HEAD 完整 CI 与用户验收之前，新代码一律非生产。不得掩盖任何新 Alpine CVE、绕过扫描器/忽略漏洞/宣称零风险；必须验证 GHCR `NOT_PUBLISHED` 且 `release_ready=false`。
- **一律未授权**：擅自合并 main、GHCR login/push/tag/Release/正式远端镜像 digest、连接用户 NAS/PVE/Portainer/群晖/VPS、访问生产 SQLite/Session/Token/备份、TG/Bark/ntfy 真通知、Gate D–G/48–72h。父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) 保持 **OPEN/status:blocked**。需要分别申请 Docker-08 **阶段验收**，然后**独立 PR 精确 SHA 合并权限**；真正发布/实机再单独批准。审批和实时 GitHub SHA/CI 优先于静态交接文件；不允许历史权限自动继承。

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
