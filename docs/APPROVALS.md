# 审批及执行权限记录（人工可核实）

> **最新（2026-10-14）：S1–S6 已分别验收合并；S7-01 规划 PR #28 已验收且单独获批合并（main `36aa8a1`，新 G0 4/4）。用户现已单独批准 Gate B / Issue #29 仅 B01/B02/B03 设计与离线开发，PR #30 尚未验收/合并。真实 VPS、生产迁移/Session/消息/48–72h、Tag/Release/部署均未授权。** 历史阶段记录不能替代最新授权。

## 2026-10-13：V1.1 方案批准，G0 授权

用户原文：

> 正式批准 SeekPulse V1.1 最终开发方案。先执行 G0 工程建档，按方案建立 AI 协作规范、GitHub 任务体系和基础 CI。未经我进一步授权，不合并 main、不发布版本、不修改生产环境。

解释与边界：

- **V1.1 架构基线：已批准。**
- **当前执行范围：仅 G0 工程建档。**
- **S0 技术可行性验证：尚待 G0 验收后单独授权执行。**
- **S1–S7：阶段实施，依实际阶段授权和验收进行。**
- **禁止自动合并 `main`、发布版本、修改生产环境。**
- 即便 CI 全绿，也不能替代用户实机验收和下一阶段批准。

后续审批必须保留原始授权文字、日期、允许执行范围及边界。AI 不可自行新增授权条目；用户口头审批应附可定位来源后再记录。

> 提醒：将本文件复制进仓库并不证明 G0 PR 已提交/合并，更不证明新阶段获批。对应 Issue、PR、提交 SHA 和实时 CI 需要另行验证。

## 2026-10-13：G0 阶段验收通过（非 S0 授权）

本次用户回复原文：

> 批准

**上下文**：紧接着 SeekPulse G0 收尾核验报告。该报告明确说明“G0 可以提交验收”“待你确认 G0 验收通过后，再单独讨论是否授权进入 S0”“不会自动合并 main 或开始下一阶段”。

**对本次批准的明确解释**：
- **G0 工程建档：用户验收通过。** 包括独立 G0 分支、Draft PR #1、15 个 Issues、Protect main Ruleset、工程规范和该次提交对应的完整 CI。
- **当前执行范围：仅 G0 工程建档及其收尾记录；G0 已验收。**
- **S0 技术验证及 S1–S7：均尚未授权实施；应先单独请求 S0 授权。**
- **未授权合并 `main`、发布 Release/Tag、修改生产环境。**
- [G0 Draft PR #1](https://github.com/Aspeternity/SeekPulse/pull/1) 保持 Draft，用户的 G0 验收不应解释为合并授权。
- 阶段验收及 CI 结果需要分别记录；此审批事件不意味着后续文档提交的 CI 自动通过。

这条记录由用户在 G0 验收上下文中的明确回复产生。后续 AI 必须核对最新实际授权，不能将简短的“批准”在脱离上下文时解释为其他阶段的授权。


## 2026-10-14：S0-04 条件式 Go 验收通过，独立授权 S1

用户原文：

> 批准

**上下文**：ChatGPT 在完成 [S0-04 / Issue #8](https://github.com/Aspeternity/SeekPulse/issues/8) 技术建议报告及 [Draft PR #20](https://github.com/Aspeternity/SeekPulse/pull/20) 的对应 HEAD CI 后，向用户明确询问：“是否验收通过 S0-04 的条件式 Go 结论，并正式授权开始 S1（Issue #9）开发？”用户直接回复“批准”。

**批准的解释与边界：**

- **S0-04 报告：条件式 Go 验收通过**，保留已批准 RSS+Telegram 独立来源、分别启停能力，不将 TG 相对原版 10 秒 RSS 的稳定速度优势当作事实。S0-01/02/03 未覆盖风险继续保留，不借验收掩盖。
- **S1 / Issue #9：明确批准开展代码开发**，范围限定于原版 RSS、关键词独立 OR/组合 AND、屏蔽词、分类、多用户多目标的回归测试以及 Python 3.11/3.12、现有依赖锁定与 CI 兼容检查；独立分支、Draft PR、按最新 SHA 验证 CI、完成后申请用户验收。
- **仍未批准**：S2–S7 实施、合并 main 或任何现有研究 PR、正式业务行为变更、Release/Tag、真实通知推送、生产修改或凭据/Session 上传。
- **实施记录**：S0-04 [Issue #8](https://github.com/Aspeternity/SeekPulse/issues/8) 已关闭（只表示报告已验收），S1-01 [Issue #9](https://github.com/Aspeternity/SeekPulse/issues/9) 进行中。审批来源为当前用户回复和直接上下文，不代表 GitHub 提供独立电子签名。


## 2026-10-14：S1-01 验收、独立合并 PR #21，以及授权 S2

用户依次原文：“S1-01 验收通过” → （在助手明确询问“是否批准合并 PR #21？”后）“批准” → （在助手确认合并完成、main CI 4/4 全绿，并询问“是否批准开始 S2 开发？”后）“批准”。

- **S1-01 验收和 PR #21 合并分别获批准**。GitHub [PR #21](https://github.com/Aspeternity/SeekPulse/pull/21) 已 Squash 合并到 main [94f26d2](https://github.com/Aspeternity/SeekPulse/commit/94f26d2a1f58924c9e060698a655dd28601ace94)，合并后 [G0 CI #38495140224](https://github.com/Aspeternity/SeekPulse/actions/runs/38495140224) 4/4 PASS，旧研究 PR #17–#20 仍 Draft 未合并。
- **S2 正式获开发授权**：覆盖 [#10 S2-01](https://github.com/Aspeternity/SeekPulse/issues/10) 标准 NodeSeek 帖子模型、字段来源追溯及三态规则；[#11 S2-02](https://github.com/Aspeternity/SeekPulse/issues/11) SQLite 单目标原子去重任务、租约认领、失败/重试/失效与迁移测试。设计基线为已批 V1.1、docs/ARCHITECTURE.md 和 ADR-0002。每 Issue 独立负责人/分支/Draft PR，按 SHA 全绿后用户验收。
- **未授权**：自动合并 S2 PR、S3–S7 开发、发布/Tag、生产部署、真实 TG/Bark/ntfy 推送、上传私有 Session 或改变已批准产品范围。S2 工作仅在独立开发分支完成，不能因为 CI 通过自动合并。
- 以上 GitHub 审批摘要只记录本次对话用户原话及紧邻的明确问题，**不冒充独立签名**；后续仍须核对实时 Issue、PR、main、CI 和用户最新指令。


## 2026-10-14：S2 验收及合并完成，独立授权 S3 / Issue #12 开发

用户在明确离线 S2 验收范围后回复「验收通过」，随后分别回答「批准」授权合并 [PR #22](https://github.com/Aspeternity/SeekPulse/pull/22) 与 [PR #23](https://github.com/Aspeternity/SeekPulse/pull/23)。两 PR 分别 Squash 合并为 [84622a1](https://github.com/Aspeternity/SeekPulse/commit/84622a10149f0c0c0538437c98cbe5e7e67b045e)、[b895bc8](https://github.com/Aspeternity/SeekPulse/commit/b895bc8d5961090b8c2fcf40f9ab0be00a212143)；合并后 main CI [#38537413073](https://github.com/Aspeternity/SeekPulse/actions/runs/38537413073) 4/4 全绿。S2 完成仅代表离线业务核心，不等于真实通知可用。

**S3 开发授权原文：**「批准启动 S3 / Issue #12 开发」。直接上下文为助手明确申请 S3 / Issue #12 Telegram + RSS 双源适配、游标补查、来源健康及独立失败恢复的开发，并说明独立分支、Draft PR、按最新 SHA 核验 CI、用户阶段验收和单独合并审批。

- **获准：** S3 Issue #12、单一负责人 ChatGPT、`feat/s3-01-dual-source-adapters` 独立分支与 Draft PR；通过无凭据模拟构建两源→S2 CoreStore 观察、来源持久游标、退避/健康、断线补查。
- **未获准：** 合并 S3 PR、启动 S4–S7、发布/Tag、真实 Telegram Session/账号登录、生产部署/迁移、真实 Bot/Bark/ntfy 通知及上传敏感凭据。
- 上述仅为当前聊天授权及上下文的可核实摘要，**不是 GitHub 独立用户签名**。实际 HEAD/PR/CI 请实时核验 Issue #12 和对应 Draft PR。


## 2026-10-14：S3-01 验收、PR #24 单独合并及授权 S4 / Issue #13 开发

用户先明确回复「批准 S3-01 阶段验收通过」，随后在助手限定“是否批准将已验收的 S3-01 / PR #24（f6dc6c8）合并至 main？本次仅用于合并及合并后 CI 核验、不包含 S4、发布或生产部署”的独立请求下回复「批准」。PR #24 [Squash 合并为 f5c3f3c](https://github.com/Aspeternity/SeekPulse/commit/f5c3f3c22703f4980206fff92212396330f2fac1)；合并后 [G0 push #38544956951](https://github.com/Aspeternity/SeekPulse/actions/runs/38544956951) 4/4 PASS；Issue #12 完成关闭。

**S4 开发授权原文：**「批准开发」。紧邻上下文为 ChatGPT 明确询问：“是否批准启动 S4 / Issue #13 开发？仍采用独立分支、Draft PR、完整 CI、用户阶段验收和单独合并审批的流程，不擅自发布或部署。”因此本批准**只覆盖 S4 的开发及相应隔离测试**，不允许 PR 合并、真实通知或上线。

- **获准：** S4 / Issue #13、唯一负责人 ChatGPT、独立 `feat/s4-01-routing-notifiers` 分支和 Draft PR；实现用户默认与单规则覆盖路由、普通/紧急两级优先级、目标独立限流/退避、Telegram 原生/Bark/ntfy 受限通知、S2 SQLite 状态机协同与离线测试。
- **已批架构约束：** 保留原 S2 投递唯一键，不制造假 Telegram chat_id、不读取或上传敏感密钥；Additive S4 策略/冷却表是本阶段路由配置的最小实现，详见 ADR-0004 及其生产迁移待办。
- **未获准：** 合并 S4 PR、S5–S7、正式运行改造、旧历史迁移、真实 Telegram/Bark/ntfy 推送、Token/Session 上传、发布/Tag、生产部署。
- 审批证据源于用户当前会话的明确原话和前后文，**不冒充独立 GitHub 用户审查签名**。后续仍以实时 GitHub PR/Issue HEAD、CI 及新的用户指令为准。

## 2026-10-14：S4-01 离线验收并获独立合并授权；S5 / Issue #14 获开发授权

用户明确原话「批准 S4-01 按目前已完成的离线开发范围验收通过 批准合并权限」，同时授权 S4-01 离线验收与 PR #25 合并。合并 [PR #25](https://github.com/Aspeternity/SeekPulse/pull/25) 的 main commit [6d5f078](https://github.com/Aspeternity/SeekPulse/commit/6d5f0787e6e3e8cae0364eb94d9a092701f0b5ed)，新 main [G0 CI #38550293273](https://github.com/Aspeternity/SeekPulse/actions/runs/38550293273) 4/4 PASS；Issue #13 已关闭。S4 完成是离线核心，不代表真实通知及非 Telegram 目标已上线。

**本次 S5 开发授权原话**：「批准」。直接回应助手明确问题：“是否批准启动 S5 / Issue #14 开发？仍执行独立分支、Draft PR、完整 CI、阶段验收和单独合并审批，不擅自部署。”

- **获准**：单独 S5 / Issue #14 开发，分支 feat/s5-01-admin-web，负责人 ChatGPT；FastAPI/Jinja2/HTMX 本地资源、管理员登录/Session/CSRF/XSS/回环限制、Web 与既有 SQLite/Telegram Bot 共享关键词/屏蔽/版块/现有目标/来源状态和历史/统计，离线 CI 与验收说明。
- **未获准**：合并 S5 PR、启动 S6–S7、生产 Web、真实 Telegram/Bark/ntfy 发送、上传真实 Session、发布/Tag、生产迁移/部署。S4 尚待审批的非 Telegram 新目标正式注册/安全迁移不能借 S5 偷偷实现。
- 授权摘要来自当前会话的用户原话及紧邻的审批请求，不冒充 GitHub 用户独立 Code Review；后续仍以精确 SHA 的 Issue/PR/CI 和用户新授权为准。


## 2026-10-14：S5-01 离线验收、PR #26 单独合并；授权 S6 / Issue #15 开发

用户先对 S5-01 限定的离线阶段请求回复「验收通过」，后对明确“是否批准将已验收的 S5-01 / PR #26（9b9805c）通过 Squash 合并至 main？本次授权仅包含 PR 合并及合并后 CI，不包含 S6、发布或部署”的独立申请回复「批准」。PR #26 [Squash 合并 commit 9fe66d9](https://github.com/Aspeternity/SeekPulse/commit/9fe66d9db8330ac84ae14718eb413634560420d1)；main 新 [G0 CI #38558377125](https://github.com/Aspeternity/SeekPulse/actions/runs/38558377125) **4/4 PASS**，Issue #14 已关闭。已验收仅为离线 Web 核心，不代表真实浏览器或 VPS 上线。

**本次 S6 独立开发授权原话**：「批准」。直接回应助手明确请求：“是否批准启动 S6 / Issue #15 开发？仍遵循独立分支、Draft PR、完整 CI、阶段验收和单独合并审批流程，不擅自部署。”

- **获准**：S6 / Issue #15、ChatGPT 唯一写入负责人，独立分支 `feat/s6-01-recovery-backup` 与 Draft PR；以现有 S1–S5 SQLite/WAL 及 ADR-0002 为基线，开发只读体检、在线一致性备份/校验、仅恢复至不存在新数据库路径、停机人工切换/回滚指南，测试磁盘不足/锁定/长时间断线/Session 失效/429，资源及依赖风险核对。后续以实际最新 SHA 全绿再申请用户阶段验收。
- **未获准**：合并 S6 PR、S7、真实 VPS 备份/恢复/覆盖运行中主数据库、生产服务或 DB 环境变量修改、真实 Telegram/Bark/ntfy/Web、正式非 TG 新目标注册与历史迁移、Release/Tag/部署。
- 此记录为用户当前对话原话与紧邻的阶段授权请求的摘要，不冒充 Github 签署的独立 Review；可在 Issue #15、Draft PR 及 CI 核验最新状态。


## 2026-10-14：S6-01 已验收/独立合并；S7 / Issue #16 仅获规划准备授权

用户先明确批准 S6-01 限定离线验收，随后另行回复「批准」，针对已验收的 PR #27（HEAD `387ff1f`）Squash 合并 main 及合并后 CI 核验。 [PR #27](https://github.com/Aspeternity/SeekPulse/pull/27) 合并 commit [`12ce325`](https://github.com/Aspeternity/SeekPulse/commit/12ce325f4ab09b3e596398d515ab5e7704d89729)；主分支 [G0 push #38567964267](https://github.com/Aspeternity/SeekPulse/actions/runs/38567964267) **4/4 SUCCESS**，Issue #15 已关闭。S6 的成果仍限离线可靠性测试，未执行真实生产备份/恢复。

**S7 当前用户原话**：「批准」。其紧邻的具体申请是：“**是否批准启动 S7 / Issue #16 的验收规划与准备？真实 VPS 操作、部署和正式发布仍需另行审批，不会因为启动 S7 就自动执行。**” 本批准不等于完整 S7 阶段执行授权，不代表实机测试启动、结果通过或用户已验收。

- **仅获准**：ChatGPT 独立 S7 验收规划准备；基于 `main 12ce325` 和 `docs/s7-01-acceptance-readiness` 创建仅文档 Draft PR，更新验收门槛、已知运行形态差距、时间窗/指标、脱敏证据模板、跨 AI 交接测试规程、GitHub CI 和 Issue #16 的阶段记录。
- **关键阻断**：现有 `app/main.py` 只启动旧 `FeedPoller`/Telegram Bot，Docker 只安装上游 `requirements.txt`；S3 双源、S4 多渠道 Worker、S5 Web 尚未接入正式进程；没有 Bark/ntfy 新目标正式注册与旧历史安全切换。以上都需要**新的集成开发方案与单独审批**，不能以旧 RSS Bot 连续运行 72 小时冒充 V1.1 全链路验收。
- **未获准**：真实 VPS 登录、只读实机预检、现场 48–72h 运行、凭据/Session、真实消息、生产镜像/配置/数据库写入或备份/迁移、功能代码和 schema 改造、停机/回滚演练、合并本 Draft PR、最终验收、Tag/Release 或部署。
- **下一闸门**：文档 Draft PR 的最新 HEAD CI 与规划审阅通过后，先针对上述生产集成阻断单独征求开发授权；真实 VPS 预检与灰度又是后续独立授权。所有未观测状态明确记 `NOT_STARTED`、`BLOCKED` 或 `UNKNOWN`。
- 这是用户当前会话明确指令的摘要，**不是**用户在 GitHub UI 签署的 Reviewer 审查，不自动改变既有分支合并权限。


## 2026-10-14：S7-01 规划验收/PR #28 独立合并；Gate B / Issue #29 获离线开发授权

S7-01 文档规划经用户回复「批准」验收后，用户另行回复「批准」，明确授权 PR #28（`3734d2a`）Squash 合并与合并后 CI 核验。合并 commit [`36aa8a1`](https://github.com/Aspeternity/SeekPulse/commit/36aa8a10e0f698fe8ffc8bd5cca1b52be6550aec)，新主分支 [G0 push #38578973921](https://github.com/Aspeternity/SeekPulse/actions/runs/38578973921) **4/4 PASS**。S7 父 Issue #16 继续 open/blocked，规划不构成实机验收。

**本次 Gate B 独立开发授权用户原话**：「批准」。紧邻明确请求：“是否批准启动 Gate B 的设计与离线开发？若批准，将继续采用独立开发分支、Draft PR、完整 CI、阶段验收和单独合并审批。此次不包含真实 VPS 操作、正式切换或生产部署。”

- **获准**：以 ChatGPT 为唯一写入负责人，基于 main `36aa8a1` 的 Gate B Issue #29 / Draft PR #30 / 分支 `feat/gate-b-01-v11-runtime-cutover`，设计与离线实现 B01 opt-in 单 asyncio 进程集成 S3/S4/S5 与 Bot、B02 真实 Bark/ntfy 独立 target ID、B03 历史观察 Prime/崩溃去重/过期过滤/锁及恢复语义；在临时 SQLite/内存 ASGI/假通知适配器中验证，保留旧默认 Docker/Compose，新增 ADR-0007。
- **未获准**：PR #30 合并 main、Gate B 阶段验收、真实 VPS 预检/操作、生产 DB/Schema/Session/Key/通知/Worker 切换、真实手机到达、48–72h、第二 AI 真运行、Tag/Release 或部署。
- **下一审批**：以最新 GateB PR HEAD 双 Python 版本 CI 证据完成离线回归，向用户申请 Gate B-01 **仅离线开发范围阶段验收**；通过后再独立申请 PR #30 合并。Issue #16 仍未整体关闭。
- 用户原话及其紧邻请求可在当前 ChatGPT 对话与 Issue #29 核对；本记录不冒充 GitHub 用户独立 Reviewer 签署。
