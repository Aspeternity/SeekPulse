# S7 / R3-0 — 当前 main 的 GHCR RC 离线证据及发行顺序（**设计 / 未验收 / 未发布**）

日期：2026-10-16 · [R3-0 Issue #54](https://github.com/Aspeternity/SeekPulse/issues/54) · [父 Issue #16](https://github.com/Aspeternity/SeekPulse/issues/16) · [ADR-0018](../decisions/ADR-0018-v11-final-ghcr-release-supply-chain.md)

> **审批边界**：用户已单独批准「R3-0 方案及离线验证」，并未批准 R3-0 阶段验收、Draft PR Ready/合并、真正 GHCR 发布、Git Tag/Release、OIDC/cosign/attestation 或对 NAS/PVE/Portainer/群晖 Docker 的任何操作。即使本次扫描全 0，仍 `release_ready=false` / `release_authorized=false` / GHCR `NOT_PUBLISHED`。唯一写入负责人 ChatGPT。

## 1. 源码与安全证据身份（不能混淆的三类 SHA）

- 已验收 Docker-11：原 PR #53 HEAD `eb98fdc0f91adc6cda0cf0eda305bb0609b1b916`，8/8 workflow / 27/27 job PASS；合并后 main 为 **`cf5f6010ff45c2511c2343f2466c63538397fdea`**，[postmerge G0 #38787500228](https://github.com/Aspeternity/SeekPulse/actions/runs/38787500228) 4/4 PASS。两 Git tree 同为 `3e9c8ea5dd35876069512f6a76cdda09f9dca4ea`，但**Git commit/revision label 必须用新 main SHA**。
- [R3-0 专项只读 workflow](../../.github/workflows/s7-r30-main-candidate-offline.yml) 在 PR 上执行时，审查**精确 PR base/main SHA** `github.event.pull_request.base.sha`，只读取对应 main 源码并用 `git rev-parse HEAD` 再校验；不会把 PR 分支 HEAD、synthetic merge-ref 的 `GITHUB_SHA`、或前一阶段 SHA 当新主线的身份。该 workflow 自身的静态政策测试可 checkout PR HEAD，但不会用它当扫描镜像源码；每次 base 移动必须重新核对真实 SHA/CI。
- 官方 Python3.11 Alpine3.24 **基础镜像** index SHA `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929` 只固定基础来源，**不是** SeekPulse 自己的最终 GHCR index digest；Trivy 检查所用本地 Docker `image ID` 也不是远端 index digest。远端 `ghcr.io/aspeternity/seekpulse@sha256:...` **当前未知，不得代填**。

## 2. 本阶段 R3-0 可执行的离线证明（不接触 registry 写权限）

本专项沿用 Docker-04/09/11 的成熟检查器（**不新增第二套 Trivy 或 CVE 逻辑**）。GitHub 临时 Runner 原生 AMD64、ARM64 各自用同一真实 main commit 构建完整 opt-in `Dockerfile.v11` 本地镜像；在 `0.0.0-ci` 的离线校验身份下，用 `SEEKPULSE_BUILD_REVISION` 设对应 main SHA；检查固定底座、OCI labels、用户 10001:10001、唯一 V1.1 入口、非 root/只读/no-network 的运行烟测。完成 Trivy OS+PyPI 原始 JSON、CycloneDX、48 小时内公开 DB、inspect 本地 image ID/包库存和五级漏洞重算（Critical/High/Medium/Low/Unknown **任何一条**都应 FAIL）；不得使用 ignore、降低等级或隐藏扫描类别。Runner 不上传镜像、原始私有扫描文件，也不推送远端。
- 本地核验期待输出：`R30_EXACT_MAIN_SOURCE=PASS`、`R30_RUNTIME_NO_NETWORK=PASS`、`R30_MAIN_OFFLINE_EVIDENCE_ONLY=PASS`，逐平台附精确 SHA、包库存/Trivy 五级计数、DB 更新时间及下载时间、真实 Job run ID。
- 输出 `LOCAL_EVIDENCE_CLEAN_AWAITING_MANUAL_RELEASE_APPROVAL` 只表示**当次**本地镜像与**当次**公开 DB 未报告漏洞，不等于 GHCR package 已存在、远端签名/attestation 已验证，也不代表人工风险接受。DB/依赖/底座如变化，必须再次扫描；失败或不可用则 `BLOCKED/UNKNOWN`。
- 历史 Debian Trixie 44 条包×CVE/8 个 OS High 是**另一旧镜像**历史证据；Alpine 本次未报告不是“Debian 已修复”的同义词。

本次额外复用 Docker-03 的 `scripts/inspect_v11_oci.py`，对**同一精确 main SHA** 用 QEMU/Buildx 生成**仅在临时 Runner 的本地** AMD64+ARM64 OCI archive，逐项验证 OCI index/platform manifest/config/layer SHA、`org.opencontainers.image.revision` 和 `0.0.0-ci`。预期 `R30_EXACT_MAIN_OCI_SOURCE=PASS`、`R30_MAIN_MULTIARCH_LOCAL_OCI_ONLY=PASS`，`remote_ghcr_digest=null`；**注意该 QEMU 归档与各 native 扫描镜像属于不同构建，不能据此推定字节一致，更不能冒充未来 GHCR index**。没有 registry 登录、推送或上传 archive。

## 3. 将来真正 R3-1 发行的顺序（**仅方案，不执行**）

**不允许“先扫描一个本地构建，换个 Runner 重建再推送就视为相同字节”。**

1. **R3-0 离线成果验收和 PR 合并另行授权。** 得到新的主线源码 SHA 后，还要对拟发行的**最终 main SHA**和精确依赖做当期再扫描、人工审查漏洞、选择 RC 版本（例如 `v1.1.0-rc.1` 只是提案）与受控发行窗口，拒绝将本次 `0.0.0-ci` 镜像误标为已发布 RC。
2. **R3-1 方案及真正 GHCR 推送必须新的独立用户批准。** 未来实施受保护 main + 精确 commit + 用户审批锁，最小权限与受保护环境；只有该阶段可经批准使用 `packages: write`，若选择无密钥 Sigstore 则需经单独审计 `id-token: write`。当前不创建带该权限/发布命令的工作流。
3. **同一批发布字节闭环：** 未来应让实际将推送的 AMD64/ARM64 构建输出成为可寻址且不可变的候选 manifest/config/layers，在**同一候选构建**上完成 Trivy、SBOM 与身份审查，并以相同内容执行上传；不得依赖另起一次 build 的相同源码 SHA 作为字节相等证明。如 registry 接收/转换引起 digest 变化，必须从 registry 回读实际 blob/index 与扫描对象逐一比较并重新判断；任何差异立即停止，不签名、不挂 RC 标签。
4. **远端回读**：先获取真实 GHCR OCI 多平台 index digest；验证每个受支持平台 `linux/amd64`、`linux/arm64` 的平台 manifest、config、rootfs layers 和 OCI revision/version/UID/entrypoint 与受审对象一致，检查未引入未知额外平台；重扫**真正的远端受验字节**并关联签名/SBOM。可使用 Docker `buildx imagetools inspect --raw` 读 index，但打印的 digest 必须源于已真实推送的 SeekPulse 镜像，不能来自本地 OCI 文件、基础镜像或文档预填。
5. **签名与 SBOM/来源证明独立许可**：未来在真实远端 index digest 上实施 Cosign/Sigstore OIDC 签名/证明，验证 OIDC issuer、严格指定的 GitHub 工作流身份与分支/源码 SHA、证书链、签名指向同一个 index digest，SBOM/attestation 与双平台镜像一致；不可用或无法验证应阻断并另行申请改案，不允许静默变成未签名发布。
6. **RC Tag/Release 需另一独立许可**：仅在真实 registry 字节、漏洞与身份验证通过、用户批准剩余风险后添加不可漂移的 SemVer RC 镜像标签及 Git Tag/GitHub Release；**不使用 `latest`**。若将版本 label 从 `0.0.0-ci` 改为 RC，必须在 RC 实际候选**重新构建后复验其最终字节**。
7. **NAS/PVE/群晖/Portainer 部署另批**：现有 Docker 环境采用用户批准、已远端验证的 `ghcr.io/aspeternity/seekpulse@sha256:<真实64位hex>`，保护绝对路径/UID 10001/SQLite WAL 和 Session、禁 Docker socket、Web 回环及最小网络授权；先校验备份与 schema，按用户授权安排首次空卷初始化/真实通知/受控观察。不可自动运行任何实机命令。
8. **失败与回滚**：构建或扫描 FAIL → 不推送/不打标签；推送部分失败 → 远端索引未核验则不宣称发布、需隔离未授权候选；来源/签名/远端双平台不符 → 拒绝进入部署；已部署后失败 → 只按经批准且数据库兼容的**历史已验证安全 digest**和校验过的备份回滚，不盲退至 Debian 历史含 High 漏洞镜像，不用不兼容旧 schema 覆盖现有数据。恢复/通知/实机操作仍需单独批准。

## 4. R3-0 可接受产物与仍未解决的风险

- **可提交人工离线验收**：精确 main 双原生平台最新真实安全证据、源码/包/DB 的可复核日志、现有 fail-closed 测试与只读 CI、发行字节/签名/发布/回滚顺序说明；之后另行申请 Draft PR Squash Merge。
- **不能在本阶段宣称**：已拥有可发布字节及远端 OCI index digest、已签名镜像、已完成远端 attestation、生产部署可用、真实用户 NAS/PVE 路由/ACL/资源稳定性、手机已收到 TG/Bark/ntfy、48–72h 通过。当前 `manual_release_security_review_completed=false`、`release_ready=false`、`release_authorized=false`、`remote_index_digest=null`。
- **保留风险**：公开 Trivy DB 的时效/覆盖与新 CVE、可重构建依赖差异、Python/Alpine 稳定分支新漏洞、构建和最终发布 OCI 字节的身份断层、OIDC issuer/签名信任链实现细节、GHCR 权限/远端字节一致性和 NAS/PVE 实机存储/回滚；没有用户明确人工风险接受前不得解除父 #16 的 BLOCKED。

参考（仅作发行设计，不在本阶段执行）：[Docker multiarch registry inspect](https://docs.docker.com/reference/cli/docker/buildx/imagetools/inspect/)、[Sigstore keyless verification](https://docs.sigstore.dev/cosign/verifying/verify/)。
