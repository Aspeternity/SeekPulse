# SeekPulse — AI 与人工协同开发总规则

> **必须先读本文件。** 本文件适用于 ChatGPT、Claude、Gemini、人类开发者以及自动化编码代理。`CLAUDE.md` 和 `GEMINI.md` 只负责指向本文件，不建立第二套规则。

## 0. 当前授权边界（最高优先级）

- **2026-10-15 已核实 main 基线：** SeekPulse V1.1 已结束 S0 条件式 Go 和 S1～S6 业务核心的**离线**验收与合并；目前处于 **S7 Docker/Compose 安全与交付收尾**，并非已发布实机服务。S7 Docker-01～09 每项分别获用户独立离线验收、独立 Squash 合并授权。Docker-09 [Issue #48](https://github.com/Aspeternity/SeekPulse/issues/48) CLOSED/completed、[PR #49](https://github.com/Aspeternity/SeekPulse/pull/49) MERGED，新 main `09ab09416a94d472f32bf74e52da4897772d06fd`，postmerge [G0 #38731768690](https://github.com/Aspeternity/SeekPulse/actions/runs/38731768690) **4/4 PASS**。main 的 opt-in `Dockerfile.v11` 已有官方 pinned Python3.11 Alpine3.24，多架构**基础镜像** index `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`，不是已发行的 SeekPulse GHCR digest；旧 Dockerfile/Compose/业务代码不变。
- **当前唯一新增许可：Docker-10 / Issue #50 / Draft PR #51 的已知漏洞最小化修复**。用户对“**启动 Docker-10 的漏洞修复方案设计及离线开发，明确不包括阶段验收、PR 合并、GHCR 发布或 NAS/PVE 部署**”单独答复原话「批准」，并要求说明目前项目阶段。唯一写入负责人 ChatGPT，分支 `fix/s7-docker-10-remediate-runtime-cves-offline`。只允许在独立 Draft PR 上：保留固定 Alpine 基础 digest，从官方 **Alpine v3.24 stable** 精确安装 `zlib=1.3.2-r1`；V1.1 镜像依赖安装前固定 `pip==26.2.1`、通过 `pip check` 后移除仅供构建的 pip 及其旧 vendored 库；只在 V1.1 专用 `requirements-v11-security.txt` 加 `python-dotenv==1.2.2`；做原生 AMD64/ARM64 完整镜像、SQLite WAL/TLS/资源限制、Trivy OS+PyPI/CycloneDX 新鲜扫描和 Docker-09 的 **8 个明确 CVE ID 全部不再报告**的失败关闭验证。复用已有 CI；不堆积死代码、临时日志或新的生产诊断接口。
- **待审批风险：** Docker-09 实测旧镜像两架构各 Medium 7、Low 1，涉及 pip/dotenv/zlib，其中 zlib CVE-2026-85091 跨来源严重程度存在不同评级；**当前用户只批准尝试离线修复，修复是否成功必须等新 PR 最新 HEAD 真镜像扫描**。历史 Debian Trixie 44 包级/8 个 High CVE 是旧 Debian 镜像真实事实，不因为 Alpine 不再报告而被认为是 Debian 已修复。任何新 High/Critical/UNKNOWN、失效扫描/缺失包库存或双架构不可重复构建必须阻断。即使目标 CVE 清除仍 `release_ready=false`、`release_authorized=false`、GHCR `NOT_PUBLISHED`。
- **一律尚未授权：** Docker-10 阶段验收、PR #51 Ready/Squash 合并 main、GHCR login/push/tag/Release 或远端签名/attestation/SeekPulse 正式 image digest、NAS/PVE/Portainer/群晖/VPS 现场、生产 SQLite/Token/Session/备份、真实 Telegram/Bark/ntfy、Gate D–G/48–72h。父 [S7 Issue #16](https://github.com/Aspeternity/SeekPulse/issues/16) **OPEN/status:blocked**。完成后必须**先单独申请 Docker-10 离线阶段验收**，如通过再**单独申请精确 HEAD PR #51 Squash 合并授权**。真正 GHCR 发布与用户现有 NAS/PVE Docker 实机安装是不同的后续批准。实时 GitHub PR/Issue/CI + 明确用户审批高于静态快照。

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
