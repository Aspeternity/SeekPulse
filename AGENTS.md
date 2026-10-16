# SeekPulse — AI 与人工协同开发总规则

> **必须先读本文件。** 本文件适用于 ChatGPT、Claude、Gemini、人类开发者及自动化编码代理；`CLAUDE.md` 和 `GEMINI.md` 仅指向本文件。每次开工须从 GitHub 独立恢复当次项目状态，不能以静态摘要取代最新 Issue/PR/CI/用户审批。

## 0. 当前授权边界（2026-10-16 Web-first B）

- **最新已核实 main**：`0fc92f9ad3ad57eb1153f15666ab1c054632da94`；Web-first A 阶段 V4 已获用户 UI 验收「符合预期」，[PR #60](https://github.com/Aspeternity/SeekPulse/pull/60) 获单独授权 Squash Merge、[postmerge G0 #38885495278](https://github.com/Aspeternity/SeekPulse/actions/runs/38885495278) 4/4 PASS，[Issue #59](https://github.com/Aspeternity/SeekPulse/issues/59) CLOSED。
- **当前唯一新增开发权限**：用户明确回复「批准B阶段」「那你可开发啊」，对应 **Issue [#61](https://github.com/Aspeternity/SeekPulse/issues/61)、独立 `feat/web-first-b-foundation` 分支、Draft [PR #62](https://github.com/Aspeternity/SeekPulse/pull/62)**，ChatGPT 唯一写入；仅允许 B 阶段的 Portainer 单容器 Web-first 入口、独立管理员注册登录、持久化数据库及离线测试、ADR/交接维护。**未批准** B 阶段人工验收、PR Ready/合并、发行 GHCR 镜像、访问 NAS/PVE/群晖/Portainer 实机、真通知或进入 C 阶段。
- **用户特别纠偏（最高优先级）**：首次打开 Web **直接显示用户自己填写用户名、密码、确认密码的注册页**；注册成功后跳到独立登录页，此后关闭公开注册。**不得**自动生成管理员账号密码、一次性验证码/初始化码、要求用户查看容器日志或额外安装向导。采用可信局域网内首位注册者成为唯一管理员的模型；默认不暴露公网。
- **用户批准的 Web-first 架构**：Portainer/Docker → Web 配置管理中心 → 统一配置服务/运行管理器 → RSS/TG、规则与 Telegram Bot/Bark/ntfy → SQLite/受保护配置。RSS 与 TG 各自启停，双源协同时复用统一帖子/去重/恢复算法；Bot 可选且启用后支持通知和命令管理。B 先实现独立 Web 底座，完整来源/通知接入留 C。
- **原 V1.1 RC1 已发布为 prerelease，未获用户真实 NAS/PVE/Portainer 稳定版验收**；旧 R3/Docker-01～11 的 Issue/PR/ADR 是历史证据，不是 B 阶段扩权。父 S7 #16 的剩余实机闸门需实时核实，不能自行关闭。现有 `app.v11_main`、原镜像和生产 SQLite 协议在 B 中保持不动。
- **下一道审批**：B 阶段最新 PR 精确 HEAD 的 GitHub CI 全绿、离线镜像与安全/恢复回归完成后，**单独请求用户 B 阶段开发成果验收**；通过后**再单独请求 PR #62 Ready/Squash Merge + postmerge CI**。镜像发布、现有 NAS/PVE 部署、C 阶段另批。若与此静态段落冲突，以更新的 GitHub Issue、提交、CI 和用户明确审批为准。

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
