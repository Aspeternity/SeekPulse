# SeekPulse — AI 与人工协同开发总规则

> **必须先读本文件。** 本文件适用于 ChatGPT、Claude、Gemini、人类开发者以及自动化编码代理。`CLAUDE.md` 和 `GEMINI.md` 只负责指向本文件，不建立第二套规则。

## 0. 当前授权边界（最高优先级）

- **2026-10-15 已核实 main：** SeekPulse 处于 **S7 / V1.1 Docker Compose 正式发布前收尾**；S0 条件式 Go、S1～S6 离线核心功能已验收合并；S7 **Docker-01～10 分别离线阶段人工验收并另外获得独立 Squash Merge 授权**。Docker-10 [Issue #50](https://github.com/Aspeternity/SeekPulse/issues/50) CLOSED/completed、[PR #51](https://github.com/Aspeternity/SeekPulse/pull/51) MERGED。最新 main `c6c8d8ca68a7e5763baca0e2b4ef5e1592974a93`，[postmerge G0 #38742527999](https://github.com/Aspeternity/SeekPulse/actions/runs/38742527999) 4/4 PASS。正式 opt-in `Dockerfile.v11` 使用固定官方 Python3.11 Alpine3.24 **基础镜像** index digest `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`，官方 Alpine stable `zlib=1.3.2-r1`、V1.1-only `python-dotenv==1.2.2`，构建期固定 pip26.2.1 完成 pip check 后卸载以免带入已知高危 vendored 库；旧 Dockerfile、Compose、原 requirements、app 业务均不改变。
- **当次完整本地镜像安全结果，不等于可发布**：Docker-10 原生 AMD64、ARM64 完整 V1.1 受验 HEAD 的真实 Trivy OS+PyPI/CycloneDX **Critical/High/Medium/Low/Unknown 各 0，原八项目标 CVE 无报告**，最新 DB/构建仍可能发生变化。旧 Debian Trixie 的 44 个包级/8 个不同 OS High CVE 是**另一旧镜像**历史记录，不能说 Alpine 迁移把 Debian 原镜像漏洞修好。`manual_review_completed=false`、`release_ready=false`、`release_authorized=false`、GHCR **`NOT_PUBLISHED`**；本项目尚无已获准/回读验证的 SeekPulse **远端**多架构 GHCR index digest、签名/attestation、Git Tag/Release 或用户真实 NAS/PVE/群晖/Portainer Docker 部署。
- **当前唯一新增许可：Docker-11 / Issue #52 / Draft PR #53 的 GHCR 最终发行前安全与供应链**方案设计及离线准备。用户对“**启动 GHCR 正式发布前的最终安全与供应链复核方案设计与离线准备；不包含真正推送 GHCR、创建 Tag/Release 或操作 NAS/PVE**”单独回复原话「批准」。唯一写入负责人 ChatGPT，分支 `research/s7-docker-11-final-ghcr-release-preflight-offline`；仅允许 [ADR-0018](docs/decisions/ADR-0018-v11-final-ghcr-release-supply-chain.md)、本地只读安全证据 gate/负向回归、修复发行审计 Workflow 的浮动 Action 版本引用并确保精确 PR HEAD checkout、原生 AMD64/ARM64 正式 V1.1 本地镜像/Trivy/CycloneDX 与 Docker-03 本地 OCI 归档验证、无权限的 GHCR 发行/远端不可变 digest/Sigstore 签名与回滚**设计**、交接文档更新。**尚未批准 Docker-11 人工阶段验收，也未批准 PR #53 转 Ready/合并**。
- **必须独立审批的禁区**：不得利用本轮批准对 main 另写、GHCR login/push、`packages: write` / `id-token: write`、创建 Git Tag/GitHub Release、真正生成镜像签名/远端 SBOM/provenance attest、冒充真正 GHCR image index digest、访问用户 NAS/PVE/群晖/Portainer/VPS、生产 SQLite/Token/Session/备份或真 TG/Bark/ntfy 通知、Gate D–G/48–72h 实机。父 [S7 Issue #16](https://github.com/Aspeternity/SeekPulse/issues/16) **OPEN/status:blocked**。完成 Docker-11 仅申请**离线阶段人工验收**；通过后再单独申请 Draft PR #53 **精确 HEAD Squash Merge**，真正 GHCR 发布以及用户现有 NAS/PVE Docker 实机操作须之后各自新批准。GitHub 实时 commit/PR/Issue/CI 与明确用户审批永远优先于合并前静态摘要。

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
