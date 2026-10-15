# SeekPulse — GitHub 跨对话交接（静态快照 2026-10-15）

> 每次接手**先核对 GitHub 实时 main、Issue #52 / PR #53、父 #16、审批评论、精确 HEAD 和最新 CI**；本文件不是独立授权。

## 产品与开发阶段
- **S7：V1.1 Docker Compose 正式发行前收尾**。S0 条件式 Go、S1～S6 离线业务核心已验收合并。**S7 Docker-01～10 已分别离线阶段验收并另行独立批准 Squash Merge main**。最新 main `c6c8d8ca68a7e5763baca0e2b4ef5e1592974a93`（[Docker-10 PR #51](https://github.com/Aspeternity/SeekPulse/pull/51) MERGED，[Issue #50](https://github.com/Aspeternity/SeekPulse/issues/50) CLOSED/completed，合并后 [G0 #38742527999](https://github.com/Aspeternity/SeekPulse/actions/runs/38742527999) 4/4 PASS）。
- 主线 opt-in `Dockerfile.v11` 为 pinned 官方 Python3.11 Alpine3.24 多架构**基础镜像** index，zlib1.3.2-r1、V1.1-only python-dotenv1.2.2、构建期 pip26.2.1 运行 pip check 后卸载。原 Dockerfile/两份 Compose/原上游 requirements/业务 app 均不改。Docker-10 **最后经用户验收 HEAD** 原生 AMD64+ARM64 全镜像 Trivy OS+PyPI/CycloneDX **Critical/High/Medium/Low/Unknown=0**，8 个此前 CVE 不再被报告，**只限当次镜像/DB**；旧 Debian Trixie 44 个包级/8 不同 High 是不同旧镜像历史证据，不能说 Debian 已修复。
- GHCR 目前 **`NOT_PUBLISHED`** / `manual_review_completed=false` / `release_ready=false` / `release_authorized=false`，无已批准或回读验证的远端 SeekPulse index digest、正式 Git Tag/Release/签名/远端 SBOM attest、NAS/PVE/群晖/Portainer 用户 Docker 实机/生产凭据/真实通知。

## 当前仅独立批准 Docker-11 发行前最终安全/供应链离线准备
- 用户对“**GHCR 正式发布前最终安全与供应链复核方案设计与离线准备，不含实际 GHCR push/Tag/Release 或 NAS/PVE**”独立回复原话 **「批准」**；唯一写入者 ChatGPT。独立 [Issue #52](https://github.com/Aspeternity/SeekPulse/issues/52) OPEN、[Draft PR #53](https://github.com/Aspeternity/SeekPulse/pull/53) OPEN，分支 `research/s7-docker-11-final-ghcr-release-preflight-offline`；PR 精确 HEAD 必须**实时读取**，任何新 commit 必须重新核查 CI。
- [ADR-0018](decisions/ADR-0018-v11-final-ghcr-release-supply-chain.md)：复用已验证的真实 Trivy/OS+PyPI/CycloneDX 和 Docker-03 本地 OCI 双架构清单，新增纯 stdlib `scripts/v11_final_release_gate.py` 失败关闭、负向测试；GH Actions 固定 40 hex SHA、checkout **精确 PR head 而非临时 merge SHA**，标签来源同一 commit；完善未来获批的 registry index 真 `@sha256` 回读、SBOM/签名/来源证明、NAS/PVE Docker 不变镜像/SQLite 备份恢复**方案**，不实施任何远端行动。
- **此用户批准不包含 Docker-11 人工阶段验收、PR #53 转 Ready/合并、GHCR 登录/推送/tag/Release、Sigstore/OIDC 实际签名/attestation、修改用户 NAS/PVE/群晖/Portainer/VPS、生产 SQLite/Token/Session/备份、真实 TG/Bark/ntfy/48–72h 运行**。父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) 必须继续 OPEN/status:blocked。

## 唯一下一步
核查 PR #53 **最新精确 HEAD** 的 G0 + 所有适用 Docker 工作流、原生 AMD64/ARM64 正式全镜像新鲜 Trivy/CycloneDX、Docker-03 多架构 OCI archive 与 source SHA、所有负向安全合同；将真实风险/证据与审批边界写入 Issue #52 / Draft PR #53 / 父 #16。**先单独向用户申请本轮“仅离线方案与准备”阶段验收**，如通过再单独申请 PR #53 Ready + Squash 合并 main 和 postmerge G0；**正式 GHCR push/tag/Release 与 NAS/PVE Docker 真部署依旧分别新批准**。
