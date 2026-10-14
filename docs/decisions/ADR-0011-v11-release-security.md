# ADR-0011 — Docker-04 V1.1 发布前安全扫描、SBOM 与不可变基础镜像

日期：2026-10-15 · [Issue #38](https://github.com/Aspeternity/SeekPulse/issues/38) · 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16)

**审批状态：用户仅批准发布前安全审查与离线开发/CI。未经独立批准不能验收本阶段、合并 PR、向 GHCR 发布镜像、创建 Tag/Release、部署或测试真实 NAS/PVE。**

## 1. 核实的技术基线和问题

- Docker-01/02/03 已分别由用户阶段验收、独立授权合并。当前 main `1d24b1564983465de340b3e30a758f52f45062ec`，合并后 G0 [#38631128468](https://github.com/Aspeternity/SeekPulse/actions/runs/38631128468) 4/4 PASS。
- `Dockerfile.v11` 仍以**可变标签** `python:3.11-slim` 构建，虽然 requirements-s5/S4/S3/上游直接依赖明确 pin，但传递依赖可变化。Docker-03 已证明 QEMU AMD64+ARM64 OCI 构建、labels、nonroot/无秘密和 ARM64 离线运行正常，**没有做 CVE 扫描、SBOM 或对基础镜像绑定 Digest**。
- 本轮必须保留旧 `Dockerfile`、`docker-compose.yml`、实际 Bot/Web/SQLite 代码和 S6 verified backup/Prime 等既有运行契约；只修改 V1.1 特定镜像安全/CI/文档。

## 2. 方案、可信边界和报告

### 官方镜像的固定和验证
1. 仅从 Docker 官方 `docker.io/library/python:3.11-slim` 公共 Registry 解析 `sha256:<64位>` **多架构 manifest index digest**，检查该 digest 确实含 `linux/amd64` + `linux/arm64` 平台；CI 可下载公开 registry manifest，但不得登录 GHCR 或访问真实机器。将验证过的 digest 写为 `Dockerfile.v11` 默认 `FROM python:3.11-slim@sha256:<真实 digest>`，保存来源与核验时间，所有后续构建必须锁定它。**不能**凭猜测填写或以单平台 manifest 代替多平台索引。
2. `FROM` 的官方基础镜像 index digest **与** `GHCR/SeekPulse` 将来发布的最终 multiarch index digest 是两个不同对象；`FROM` 固定不能证明 GHCR 镜像存在。正式发布时依旧要求从 GHCR 读取并核验单独的正式 digest。
3. 基础镜像升级属于新的供应链更改：需要以后单独审查官方新 digest、OS 包版本、CVE/兼容性、两平台构建、镜像运行和影响记录，不能把 `latest` 或浮动 tag 引回去。

### 漏洞扫描（正式发布的必要前置证据）
1. 只在 GitHub runner 构建**本地** V1.1 镜像，使用固定版本/commit 的公开 scanner 读取 OS（Debian）与 Python 环境包，扫描 AMD64 和 ARM64 各自的镜像、用公开**新鲜的漏洞数据库**，并生成 CycloneDX JSON SBOM（每平台）及机器可解析的 CVE JSON。
2. 报告验证器须拒绝缺失/空 JSON、未知架构、无 OS 包 / 无 PyPI 包 inventory、扫描结果缺失、没有漏洞数据库元数据/扫描时间、与预期镜像不符、扫描器失效和过期数据库。对检测到的 **High/Critical**（明确标注修复版本和是否可修复）列入发布阻断清单；中低级漏洞也记录数量但不能自动忽略。出现已知漏洞时允许 CI **生成完整审查报告**，但发布状态应为 `BLOCKED`，不得把 CI 的运行 success 误述为安全放行。不可用/过期则 `UNKNOWN`，同样不得放行。
3. 本阶段报告仅是 **某个 runner 构建、某个时间点的快照**，基础镜像内 apt 包、实时 CVE/修复信息变化会使它过期；正式发布之前必须在将发布的**精确镜像**和新鲜漏洞数据库上重新扫描、归类并获得单独审批。

### SBOM 与供应链最小原则
1. 每架构 CycloneDX SBOM 中需要保留 OS 与 Python 所安装组件、包名/版本、scanner 版本/生成时间，scanner/DB 元数据；不得嵌入账号/会话/secret。CI 缓存或 artifact 不能充当正式发布签名；只有在未来明确获得发布批准后才决定永久保存/签名、生成独立构建 provenance 和 GHCR attestation。
2. 新 CI 没有 `packages: write`、GHCR 登录/推送、远程缓存或发布权限，所有工具/Action 尽量 SHA 固定且下载时来源可核实。不得下载并执行无版本范围的脚本绕过供应链审查。
3. 静态 supply-chain gate 继续验证 `Dockerfile.v11` 使用 pin 的 base digest、run 非 root、`CMD ["--run"]` 且保持显式 opt-in、密钥不进 build args/ENV/层、`compose.v11.yaml` 没有 Docker Socket/公开管理端口/特权/自动启动。**未知不等于安全**。

## 3. 当前授权边界、失败处理与回滚

- **唯一负责人** ChatGPT，独立分支 `feat/s7-docker-04-security-review`、Draft PR、Issue #38，先记录 ADR 再开发。所有真实扫描只在 GitHub Actions 临时 runner 用公开 Python 镜像和漏洞库、无生产 Token/Session/数据库或 NodeSeek/Telegram/Bark/ntfy 真实请求。
- CI 失败时先据日志定位根因。对于 CVE 不允许虚构已修复或盲目修改原版依赖，先记录影响范围、可修复版本、扫描准确度及处置建议；后续是否修复依赖需独立评估改动范围。
- 本阶段不修改 main、不合并 Draft PR、不发布任何 GHCR 镜像、Tag/Release、部署 NAS/PVE/群晖/Portainer/VPS、接触真实备份/登录 Session/通知、执行 48–72h/Gate D–G。
- 回滚仅需关闭未合并 Draft PR，已合并的 Docker-01/02/03 和用户环境不会被影响。
- **唯一下一审批**：离线审查/代码/CI 完成并按最新 SHA 核验后，单独向用户申请 Docker-04 *仅离线开发和发布前安全审查范围阶段验收*。验收后另行申请合并，再另行申请 GHCR 发布和真实 NAS/PVE 部署。不能顺延。

## 4. 未完成的正式发布判断

- `NOT_PUBLISHED`：GHCR V1.1 镜像未推送且无可验证 registry digest；本轮不创建正式版本号/Release。
- `NOT_RELEASE_READY`：即使 scanner 与 SBOM 完全有效，也只代表离线审查数据有效；尚需对漏洞处置进行人工批准、基础镜像与依赖合规性、完整 SBOM/签名/attestation 政策、最新扫描、官方 Git tag 唯一性、真正 registry index digest、双架构拉取验证和真实 Docker 宿主机部署/网络/备份/回滚的独立验收。任何一项未知均不应声称“正式安全放行”。
