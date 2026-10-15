# ADR-0018 — V1.1 GHCR 最终安全/供应链发布闸门：源提交、双架构、SBOM、签名与回滚

日期：2026-10-15 · [Docker-11 Issue #52](https://github.com/Aspeternity/SeekPulse/issues/52) · 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16)

**状态：仅发行前最终审查方案设计及离线准备获批（PROPOSED / DRAFT / NOT STAGE ACCEPTED / NOT MERGED / NOT PUBLISHED）。** 用户回复“批准”所对应的请求明确为“GHCR 正式发布前最终安全与供应链复核**方案设计与离线准备**，**不包括**真正推送 GHCR、创建 Tag/Release，或操作 NAS/PVE”。此次仅在独立 Issue #52 / Draft PR 中编制本 ADR、只读安全检查/负向测试及 GitHub 临时 Runner 本地复核；不是实际签名、发行或生产部署授权。

## 1. 真实基线与信任边界

- Docker-01～10 **各自通过离线阶段人工验收并另获授权 Squash Merge**。Docker-10 [Issue #50](https://github.com/Aspeternity/SeekPulse/issues/50) CLOSED/completed、[PR #51](https://github.com/Aspeternity/SeekPulse/pull/51) MERGED；main `c6c8d8ca68a7e5763baca0e2b4ef5e1592974a93`、[postmerge G0 #38742527999](https://github.com/Aspeternity/SeekPulse/actions/runs/38742527999) 4/4 PASS。S0 条件式 Go、S1～S6 离线核心业务完成。当前 **S7 / V1.1 Docker Compose 正式发行前收尾**，不是 VPS 裸机安装阶段。
- 正式 opt-in `Dockerfile.v11` pinned Docker 官方 Python3.11 Alpine3.24 **基础多架构 index digest** `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`（**绝非**最终 SeekPulse GHCR 远端 index digest）。Alpine 官方稳定仓库 `zlib=1.3.2-r1`、V1.1-only `python-dotenv==1.2.2`；固定 `pip==26.2.1` 只在构建时安装及 `pip check`，然后删除 pip 及其有已知漏洞的 vendored copy。原版 Dockerfile、Compose、上游 requirements 与应用协议均不改。
- Docker-10 **已受验代码树**原生 AMD64/ARM64 本地镜像 Trivy OS/PyPI/CycloneDX **Critical/High/Medium/Low/Unknown 各 0**、原 8 项 CVE 无报告，这是当次镜像/Trivy DB 的结果，**不是**永久或真正 GHCR 发行/来源安全认证。另有旧 Debian Trixie 的 44 包级/8 个去重 High CVE 是**另一历史镜像**，Alpine 未报告不等于 Debian 已修复。
- 现在**没有**已获用户认可的 `release_ready=true`、`release_authorized=true`、远端 SeekPulse 多架构 GHCR index digest、已签名镜像/远端 attest 的 CycloneDX、正式 GitHub Release/Tag；本地 OCI SHA、Trivy CycloneDX、官方 base SHA 都不得冒充生产远端 digest。父 S7 #16 必须 **OPEN/status:blocked**。

## 2. 发布前离线 Final Evidence Gate（本次实现，只读）

**目标不是创造另一套 Trivy/OCI 系统**：复用已通过的 `scripts/v11_security_evidence.py`、`scripts/v11_pre_release_review.py`、`scripts/inspect_v11_oci.py`、`scripts/v11_release_policy.py`。新增 `scripts/v11_final_release_gate.py` 只对同一**真实最终本地镜像**的 Trivy JSON、CycloneDX 已校验报告、prepublish review 和 docker inspect 做更窄的最终发行**前**拒绝检查：
1. 必须是 GitHub 已 checkout 的**精确来源 commit SHA**，40 位小写，与 PR head（如 pull_request）一致，**不能拿 `GITHUB_SHA` 的合成 merge ref 作真正源码 revision**。在 CI 使用 `github.event.pull_request.head.sha || github.sha` checkout，并用 `git rev-parse HEAD` 二次核对后通过显式 `SOURCE_SHA` 传递 build label/审计。两个原生平台都由**同一 SOURCE_SHA** 构建，精确 HEAD 对应的 CI 测试必须同时完成。PR 上先完成合并前代码树验证，未来正式发行重跑 main 精确 SHA 版本。
2. 保证 scanner 与 `docker image inspect` 的 image ID、OS Alpine v3.24、`linux/amd64` / `linux/arm64`、非 root UID/GID 10001、V1.1 唯一入口和 `--run`、OCI `source/version/revision/licenses` labels 一致；`RepoDigests` 仍空（本地未发布），禁止凭证 baked into image config。继续使用 Docker-03 双架构 OCI archive 描述符/manifest/config/layer SHA 实际校验，不产生臆造 index digest。
3. Trivy 必须有 OS+PyPI 两类库存、有效新鲜漏洞 DB（48h 内，禁止未来时戳）、同源同镜像 CycloneDX（2h 内）、Alpine 软件包和 PyPI 库存、完整无抑制 CVE；**Critical/High/Medium/Low/Unknown 五个计数全 0** 才可声明“**当前本地镜像在本次扫描中没有被报告的漏洞**”。任何新增记录或篡改计数严格 FAIL；不允许 ignore/ignore-unfixed、变更严重程度或用不同发行版伪称已修复。
4. 验证现有预发布 report 的每个字段与调用 `review_pre_release` 从本次 scan 重新推导的值**严格一致**。发行名称必须符合 SemVer RC 规则，只可形成尚未获批的 `ghcr.io/aspeternity/seekpulse:v1.1.0-rc.1` **方案**；远端 digest 必须 null，镜像/构建来源签名、远端 SBOM attest 必须 false。输出 **`LOCAL_EVIDENCE_CLEAN_AWAITING_MANUAL_RELEASE_APPROVAL`**，并始终 **`release_ready=false` / `release_authorized=false` / GHCR `NOT_PUBLISHED`**。不能通过本地检查授予审批或发布权限。
5. 发行相关 GitHub 工作流与 Actions 依赖采用**完整 40 位不可变提交 SHA**、`permissions: contents: read`；不登录 GHCR，不用 `packages: write`、`id-token: write`、生产 Secrets、Git Tag/Release、远端签名/attestation 或上传完整 Trivy/OCI artifact；测试必须覆盖错误来源、错架构、过期 DB、伪造预发布报告、缺失/新增 CVE、已有远端 digest、声称已签名/已授权等反例。研究 CI 允许读取**公开**的 Trivy 漏洞数据库和 pip 官方依赖，但容器运行时测试使用无网络环境。

## 3. 将来获得独立发布批准后执行的 R3（**本次绝不执行**）

严格分开**审查目标**与**实际将发布的字节**。目前每架构 native 本地 Trivy 与 Docker-03 QEMU OCI 归档是不同构建，只能证明同一 HEAD 的条件下均通过，**不能声称本地 OCI 归档所有 digest 与最后 GHCR 上的 blob 完全相同**。未来发布流程必须保证一个获准的、被实际扫描并验证的候选构建**与最终推送的 OCI index 和平台 manifest/layers**一致；若重新构建，重新验证/扫描并记录实际差异。不能把“同源码 SHA”当作“镜像字节相同”。

**建议发行门槛：**
- **R3-0 独立批准发行方案与当期最后安全证据**：唯一 main 源 commit、拟定首个 `v1.1.0-rc.1` 发行名、确切 Dockerfile pin、SBOM/Trivy scanner DB 时间、所有 CVE、双架构完整回归和最小 CI 权限。用户明确认可剩余风险及发行路径；任何 High/Critical/Unknown 必须阻断。
- **R3-1 GHCR 推送（需另行单独批准）**：专用后续 release workflow（**本次不建立含写权限/推送动作的可执行工作流**），固定 Actions SHA/最小权限，只在受保护 main、明确批准的精确 commit SHA 触发；需要 `packages: write` 和（若选 Sigstore 无密钥签名）`id-token: write` 的理由、信任身份及权限按独立批准审计。优先先将不可变平台 digest 发布为可校验候选，再验证再挂 SemVer 标签；任一失败不得宣称 RC 已可用。不要生成 `latest`。
- **R3-2 远端证实**：从 GHCR **回读**实际 index `ghcr.io/aspeternity/seekpulse@sha256:<64hex>`，验证 index 恰含 `linux/amd64`、`linux/arm64` 且无额外不受支持平台，逐一下载并核对 manifest/config labels 的源 SHA/版本/UID/入口/架构及 SBOM/Trivy 漏洞库存，**确认被复扫字节与实际推送字节相同**，任何平台遗漏/label 不符 FAIL。不许把官方 Python base index SHA 或 local `docker image inspect` ID 冒充它。
- **R3-3 签名/Attestation 建议**：优先考虑 GitHub OIDC + Sigstore/cosign 无密钥签名，将可信 workflow/ref SHA 与**真正远端 OCI index digest** 绑定，并同时生成 SBOM（例如 CycloneDX）及来源 attestation。必须验证 issuer/identity/证书信任链、签名绑定的 digest、SBOM 指向相同 manifest/image、source SHA；如签名方案不可用，视为**新的阻断和人工改案**，不可默默降级无签名发布。**当前只进行设计，不签名、不拿 OIDC、不创建密钥/attest**。
- **R3-4 Tag/Release 另行审批**：在远端来源/签名/风险审查成功后才按用户独立许可决定 Git Tag、GitHub Release 与公告内容。Tag 必须指向受审源码及 digest，不可漂移、不可使用 `latest` 代替不变 index。
- **R4 NAS/PVE/群晖/Portainer 独立授权部署**：用户有现存多 Docker 容器，禁止检查陌生裸 VPS 或改变其他服务。Compose 的 `SEEKPULSE_IMAGE` 必须填已经批准/远端核验的 **`@sha256`** 镜像引用；继续 `network_mode: host` + Web `127.0.0.1`、无暴露端口、非 root UID/GID 10001、只读 rootfs、无 Docker socket、绝对路径受保护持久目录。首次仅全新空卷可 `--init-fresh`；已有数据按 S6 校验备份/迁移/回滚策略另批。真实 Token/Session、TG/Bark/ntfy 通知、48–72h 稳定性观察按用户批准的实机 Gate 分段执行。失败回滚使用**此前经核验安全且数据库兼容的远端 digest + 校验过的备份**，不可盲退回含 High CVE 的历史旧镜像，也不能倒退 schema 而损坏数据库。

## 4. Docker-11 本阶段退出标准、后续审批

仅要求 ADR-0018、明确供应链未完成项、失败关闭离线 preflight/反例测试、两架构真实本地漏洞复扫和完整 OCI/业务回归，在**同一 PR HEAD** 的所有适用 CI 全绿或如有变化真实报告失败；不需要、也不能生成正式 registry index、签名、Tag/Release 或用户实机。完成后**先单独申请 Docker-11 离线阶段验收**，通过后**另行**申请 Draft PR 的精确 HEAD Squash 合并及 postmerge G0；**最后再申请真正 GHCR 发布方案/执行和 NAS/PVE 实机部署的独立授权**。父 Issue #16 始终 OPEN/status:blocked。
