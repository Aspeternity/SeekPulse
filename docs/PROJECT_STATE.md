# SeekPulse — GitHub 跨对话状态（2026-10-16 静态快照）

> 必须优先实时核对 main、[R3-0 Issue #54](https://github.com/Aspeternity/SeekPulse/issues/54)、相应 Draft PR、父 [#16](https://github.com/Aspeternity/SeekPulse/issues/16)、审批记录和最新精确 HEAD CI；此文件不是独立权限来源。

## 最新 main 与已完成范围
- SeekPulse V1.1 / S7。S0 条件式 Go、S1～S6 离线核心，以及 S7 **Docker-01～11 各自离线验收、另行 Squash Merge**。Docker-11 [Issue #52](https://github.com/Aspeternity/SeekPulse/issues/52) CLOSED/completed、[PR #53](https://github.com/Aspeternity/SeekPulse/pull/53) MERGED，main `cf5f6010ff45c2511c2343f2466c63538397fdea`，新 [G0 #38787500228](https://github.com/Aspeternity/SeekPulse/actions/runs/38787500228) **4/4 PASS**；原受验 PR HEAD `eb98fdc0f91adc6cda0cf0eda305bb0609b1b916` 和新 main Git tree `3e9c8ea5dd35876069512f6a76cdda09f9dca4ea` 一致，但 revision 不相同。
- opt-in `Dockerfile.v11` 固定官方 Python3.11 Alpine3.24 多架构**基础** index digest，Docker-10 zlib/dotenv/pip 修复已纳入。旧版 Dockerfile/Compose、原 requirements、app/DB/通知协议未改。旧 PR 原生 AMD64/ARM64 实镜像当时 Trivy OS+PyPI/CycloneDX 五级漏洞均 0（38 Alpine+62 PyPI；只限当次 DB 与镜像）。旧 Debian Trixie High 不可借 Alpine 缺报称为 Debian 漏洞已修复。
- 正式 GHCR `NOT_PUBLISHED`、`release_ready=false`、`release_authorized=false`、`remote_index_digest=null`；无正式签名/远端 SBOM attestation/Tag/Release/NAS/PVE 实机。父 #16 **OPEN / status:blocked**。

## 当前唯一新增许可：R3-0 发行候选方案与离线复核
- 用户在单独请求「启动 R3-0 方案及离线验证，不包含 GHCR 推送、签名、Tag/Release 或 NAS/PVE 部署」后直接回复 **「批准」**。唯一写入者 ChatGPT，[Issue #54](https://github.com/Aspeternity/SeekPulse/issues/54) / `research/s7-r3-0-main-candidate-offline` 分支/Draft PR，**没有** R3-0 离线验收或 PR 合并权限。
- [R3-0 方案](research/S7-R3-0-main-candidate-offline.md) 复用 [ADR-0018](decisions/ADR-0018-v11-final-ghcr-release-supply-chain.md) 与已证明的 fail-closed validators；新的 GitHub 只读临时 Runner 在 R3-0 PR 上明确 checkout **精确 PR base/main SHA**（非 PR HEAD/synthetic merge ref），原生 amd64/arm64 两镜像真实 Trivy OS+PyPI/CycloneDX、来源/SBOM/DB/运行保护和零发现，再设计未来一次实际发行字节/远端核验/签名/回滚顺序。此阶段没有正式 GHCR blob、tag 或用户现有 NAS/PVE 连接。
- 若 CVE、数据库、包库存、影像 SHA、OCI 来源不符，标 `BLOCKED` 不掩盖；即使全部 PASS 也仅 `LOCAL_EVIDENCE_CLEAN_AWAITING_MANUAL_RELEASE_APPROVAL`。R3-0 当前代码/CI 必须以实时 GitHub HEAD 为准。

## 下一道审批
首先独立复核最新 R3-0 Draft PR 精确 HEAD 的 G0 + 原生 AMD64/ARM64 **main-source** 正式扫描真实 Job；**仅申请 R3-0 离线阶段验收**。如用户批准，再另行请求 PR Ready/Squash Merge + postmerge G0；真正 GHCR push/sign/Tag/Release、用户 NAS/PVE/群晖/Portainer 的不可变 digest Compose/SQLite/通知/回滚和 48–72h 分别后续审批。不得为了刷新文件而自行写入 main。
