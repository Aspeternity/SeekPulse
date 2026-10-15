# ADR-0016 — SeekPulse V1.1 GHCR 发布前公开漏洞复核与双架构证据链（离线准备）

2026-10-15 · Docker-09 [Issue #48](https://github.com/Aspeternity/SeekPulse/issues/48) · S7 [#16](https://github.com/Aspeternity/SeekPulse/issues/16)

**状态：仅方案设计与本地 CI 研究获批（PROPOSED, NOT ACCEPTED, NOT MERGED, NOT PUBLISHED）。** 用户针对“Docker-09 的发布前安全审查与离线准备，不包含实际 GHCR 推送、创建 Release/Tag 或 NAS/PVE 部署”独立回复「批准」。这不是 Docker-09 阶段验收、PR 合并、发布、生产镜像或实机授权。

## 1. 当前可证事实（以最新实时 GitHub 为准）

- Docker-08 独立阶段验收 + [PR #47](https://github.com/Aspeternity/SeekPulse/pull/47) 独立 Squash Merge：main **`e86b10bd324f083955b1d38a340bbca092b0dc03`**，同 SHA 合并后 [G0 #38723709559](https://github.com/Aspeternity/SeekPulse/actions/runs/38723709559) **4/4 PASS**。
- 新的**仅 opt-in** `Dockerfile.v11` 引用 Docker 官方 `python:3.11-alpine3.24@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`，其 digest 为官方 **基础镜像** multiarch index，**不是** SeekPulse GHCR 镜像 digest。已测试原生 `linux/amd64` 与 `linux/arm64` 完整本地镜像，分别 **328/328** 离线业务回归与 **5/5** 资源受限测试成功，原版 Docker/Compose/业务协议/依赖 pin 均不变。
- Docker-08 当次实际完整镜像 Trivy OS+PyPI **High/Critical 各 0**，**Medium 7、Low 1**（每个平台），软件库存为 38 个 Alpine 与 63 个 PyPI。数据库 UpdatedAt 2026-10-15T07:10:08Z；扫描只有“当时的镜像+当时的 DB”意义，不能称安全永久通过。历史 Debian Trixie 的 **44 条 OS High 受影响包×CVE / 8 个去重 CVE** 仍为不同旧镜像的真实发现；不能声称已通过 Alpine 对 Debian 做安全修补。
- 即使发现的 High/Critical=0，旧报告还有 Medium/Low、上游公告和供应链/用户运行环境尚未审查。发版状态必须 `REVIEW_REQUIRED_NONBLOCKING` / **`release_ready=false` / `release_authorized=false` / GHCR `NOT_PUBLISHED`**。未使用 Docker login、GHCR push、签名/attestation/发布 Tag/Release、正式远端 index digest、用户 Docker 主机。

## 2. 决策：新增纯离线的逐项风险清单

新建只读 `scripts/v11_pre_release_review.py` 与 `tests/test_s7_pre_release_review.py`，利用**同一张镜像**上的 Trivy JSON、CycloneDX SBOM、Docker inspect 和**现有** `scripts/v11_security_evidence.py` 已验证报告：
- 现有 verifier 负责 DB 新鲜度、SBOM 库存和扫描/镜像身份、两类 OS+Python 完整性与 High/Critical 漏洞计数，禁止缺失或错误扫描冒充 0。
- 新 preflight 负责再核对 repo/源码 **40 字符 HEAD SHA**、镜像/架构/OS Family、完整数量一致性与没有“已发布/已授权”字段；逐条列出实际 `os-pkgs` / `lang-pkgs` Medium、Low 或 UNKNOWN：漏洞 ID、包名、已装版本、Trivy 的 FixedVersion（若存在）、人工待核验状态；仅使用公开元数据，**绝不读取或输出 Token/Session/env**。并明确 High/Critical 新增时的 `BLOCKED_HIGH_OR_CRITICAL` 拒绝、UNKNOWN 的 `UNKNOWN_REVIEW_REQUIRED` 拒绝，Medium/Low 的 `MANUAL_REVIEW_REQUIRED`。
- `FixedVersion` 是 Trivy 当前公开数据的 *提示*，**不是已核实的仓库可升级版本**；有修复候选的漏洞也不得在本阶段擅自升级依赖或 `apk` 包。若有修复建议，单独提交风险与兼容性评估。漏洞 ID 在不同包/架构可能重复，因此报告区分“受影响包×漏洞的记录数”与“去重漏洞 ID”；不以记录数冒充 CVE 总数。
- 输出必须在任何情况下 `release_ready=false`、`release_authorized=false`、`remote_index_digest=null`、`ghcr_image_status=NOT_PUBLISHED`，不允许接受 `latest`、用户臆造的 GHCR digest 或本地 OCI SHA 代替远端已验证 digest。

新增 `.github/workflows/s7-v11-prepublish-review-offline.yml`：GitHub 仅临时的、**原生 AMD64/ARM64** Runner，`permissions:contents:read`，重新从**正式** `Dockerfile.v11` 无私密参数构建应用本地镜像、Trivy 公开最新 DB 同镜像 OS/PyPI 扫描与 CycloneDX、调用已有校验器和新 preflight；打印精确漏洞 ID + package/version/fixed 供人工复核；无 registry login/push、`packages:write`、tag/Release、上传扫描原始产物、系统/网络凭据或真实发送。原 Docker-03 双平台 OCI 完整性和 immutable GHCR 引用语法验证仍是单独必需检查，不在新 workflow 中造一个虚假可发布 digest。

## 3. 正式发布的未来独立阶段（本次不执行）

1. **Gate R1 安全审查**：对两架构同一 **最终** Source SHA 的完整 Trivy/CycloneDX 再扫码、记录时间；逐 Medium/Low 对照 Alpine / PyPI 官方安全公告、业务使用路径、固定版本的可用性/兼容性、是否需要修复、接受理由和用户明确批准。High/Critical 不得偷放过，UNKNOWN/Missing scan 必须阻断。不同发行版的历史 CVE 不当作已修复。
2. **Gate R2 供应链/签名设计**：核对官方基础 index digest，保证多平台的 OCI labels/manifest/layers（`scripts/inspect_v11_oci.py`），锁定唯一提交 SHA + SemVer 标签；审查构建器/Action SHA、最小权限、完整 SBOM 与产物来源。当前 CI 使用 `--provenance=false --sbom=false` **仅意味着没有发布 provenance/构建 attestation**；Trivy CycloneDX 是本地 **SBOM 文档**，*不是*已签名 SBOM。后续是否采用 GitHub OIDC + Sigstore/cosign 无密钥签名、署名/attestation 及验证策略，需要**新的受审方案及 GHCR 发布授权**。本轮**不生成签名、密钥、GitHub Release attestation、远端 artifact**。
3. **Gate R3 正式 GHCR 发布（单独批准）**：发布专属 GitHub workflow、`packages:write` 权限、必要认证/来源控制、唯一不可变 `ghcr.io/aspeternity/seekpulse:v1.1.0-rc.N`/SemVer、远端 OCI multiarch index 回读并验证真实 GHCR **`@sha256:<64位>`**、平台 config 和源 SHA、SBOM/可选签名验证。禁止 `latest`，不得在 GitHub issue/PR 和文档中写臆造的 registry digest。
4. **Gate R4 真实 NAS/PVE/群晖/Portainer 独立批准**：正式 registry digest 填入私有 `SEEKPULSE_IMAGE`；一次性 `--init-fresh`（仅确认全新空卷）或旧库按 S6 verified backup / `--prepare`；核对持久卷 UID/GID、SQLite WAL/文件系统硬链接、host networking 127.0.0.1/SSH 转发、无端口暴露，安全启动和回滚；确认用户现有其他 Docker 应用不能被自动变更。生产 Token/Session/真实通知、48–72h 必须单独授权。**回滚是恢复经验证的旧不可变镜像 digest + 已校验备份/兼容库，不能通过回滚绕过 DB 升级安全或旧 Debian CVE 阻断**。

## 4. 强制可追溯结论

Docker-09 **退出条件仅为“发布前安全审查证据及流程准备可交付”**，不等于最终安全风险已获用户接受，更不等于 `release_ready=true`。新 CI 可以因扫描有效而全绿，但 Medium/Low 的存在会持续列为**待人工处置**；须把两架构本次公开清单、版本、上游修复提示、检索日期、CI SHA、残余风险和后续批准步骤写入 Issue/PR。

每道独立闸门：Docker-09 实施完成 → 用户单独**阶段验收** → 用户另行单独 PR Squash 合并 → main G0 → 新的安全/发行方案批准 → 实际 GHCR 发布批准 → 用户 NAS/PVE 部署及真实通知批准。父 #16 始终 OPEN/status:blocked 直至全部获批完成。
