# SeekPulse — GitHub 跨会话接力状态（静态快照 2026-10-15）

> **每次接手以 GitHub 当前 main/PR/Issue SHA、最新 CI、明确用户审批优先。** 本页不是新授权。

## 项目实际阶段
- **目前 S7：V1.1 Docker/Compose 交付与正式发布前的安全收尾**。S0 **条件式 Go**；S1～S6 双来源 TG/RSS、规则/通知/SQLite/WAL、Bot/Web/备份等**离线**功能已验收合并。**尚未正式 GHCR 发布或在用户 NAS/PVE/群晖/Portainer 实机部署**；不能把离线测试当生产运行证据。
- S7 **Docker-01～09 每个均离线阶段验收并获独立 Squash Merge 授权**；Docker-09 [Issue #48](https://github.com/Aspeternity/SeekPulse/issues/48) CLOSED/completed、[PR #49](https://github.com/Aspeternity/SeekPulse/pull/49) MERGED，main `09ab09416a94d472f32bf74e52da4897772d06fd`、合并后 [G0 #38731768690](https://github.com/Aspeternity/SeekPulse/actions/runs/38731768690) 4/4 PASS。主线仅 opt-in `Dockerfile.v11` 使用官方 Python3.11 Alpine3.24 pinned 多架构基础镜像，旧 Dockerfile、Compose、原版 requirements/app 行为没有改变。
- Docker-09 原生 AMD64/ARM64 实测每平台 **Medium=7, Low=1, High/Critical=0**：`pip 24.0` 六项、`python-dotenv 1.0.1` 一项、`zlib 1.3.2-r0` 一项；zlib CVE-2026-85091 另有公开来源评级差异。旧 Debian Trixie 的 44 包级/8 去重 High CVE 是其他**旧镜像历史证据**，不代表新 Alpine 镜像或已在 Debian 修复。至今 `release_ready=false`、`release_authorized=false`、GHCR `NOT_PUBLISHED`、无正式 SeekPulse 远端多架构 digest。

## 当前唯一许可：Docker-10 已知漏洞**离线修复开发**
- 用户对明确请求“**启动 Docker-10 的漏洞修复方案设计及离线开发，非阶段验收、合并、GHCR 发布、NAS/PVE**”回复 **「批准」**，同时询问项目阶段。已在回复解释 **S7**，不是从头开发。独立 [Issue #50](https://github.com/Aspeternity/SeekPulse/issues/50) OPEN、[Draft PR #51](https://github.com/Aspeternity/SeekPulse/pull/51) OPEN、分支 `fix/s7-docker-10-remediate-runtime-cves-offline`，唯一写入者 ChatGPT；最新 HEAD/CI 必须实时查询，**未完成不得预报绿色**。
- [ADR-0017](decisions/ADR-0017-v11-runtime-vulnerability-remediation.md) 研发候选：只在 opt-in V1.1 `Dockerfile.v11` 的旧固定 Alpine3.24 基础上，从 Alpine stable 仓库精确 `zlib=1.3.2-r1`、启动 pip 安装前升级固定 `pip==26.2.1`；`requirements-v11-security.txt` 只加 `python-dotenv==1.2.2`，原四个安全 pin 保留；旧 Dockerfile/两份 Compose/原版 requirements `app/` 和 DB/通知协议全部不改。两原生架构本地完整镜像、SQLite WAL/TLS/资源限制和最新 Trivy OS+PyPI/CycloneDX **对 8 个明确目标 CVE 全部不再报告**，无 ignore/隐瞒风险。
- **未批准** Docker-10 代码阶段验收、PR #51 独立合并、GHCR login/push/Tag/Release/签名/attestation/正式 registry digest、用户 NAS/PVE/群晖/Portainer/VPS、生产 SQLite/Token/Session/备份、真实 TG/Bark/ntfy 或 Gate D–G/48–72h。父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) 必须继续 **OPEN/status:blocked**。

## 唯一下一步
验证 PR #51 **最新精确 HEAD** 的所有适用 G0 + Docker-01～10 CI，原生双架构真实 zlib/pip/dotenv 版本与目标 8 CVE、全部现存高危检测及历史风险标记；如测试失败先找根因，修复后新 SHA 全部重跑。**只向用户单独申请 Docker-10 已完成离线范围阶段验收**；批准后另申请精确 HEAD PR Ready/Squash 合并及 postmerge G0；真正 GHCR 发布和家中 NAS/PVE Docker 实机各须后续新批准。
