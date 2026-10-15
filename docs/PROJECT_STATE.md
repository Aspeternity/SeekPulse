# SeekPulse — 跨会话实时交接摘要（GitHub 实况优先）

> 2026-10-15 参考快照；此文件不授予权限。每次接手先读 `AGENTS.md`，核对 Issue/PR/main SHA、最新 CI 以及用户明确的独立审批。

## main 已完成的范围
- Docker-01～07 各自离线阶段验收、独立授权 Squash 合并均已完成。其中 Docker-07 只是**受支持 OS 修复路径与 Alpine 候选研究**，非正式 V1.1 迁移。Docker-07 [Issue #44](https://github.com/Aspeternity/SeekPulse/issues/44) CLOSED、[PR #45](https://github.com/Aspeternity/SeekPulse/pull/45) MERGED，**main `30c246be5f7cb11fb315ccecc882798b75f28160`**，新 main [G0 #38718379825](https://github.com/Aspeternity/SeekPulse/actions/runs/38718379825) **4/4 PASS**。旧 S0 Draft #17～#20 不动。
- **main V1.1 仍 Debian Trixie** 固定官方基础镜像；其 AMD64/ARM64 历史 Trivy OS High **44 条 package×CVE、8 个不同 CVE**，PyPI High 0、Critical 0，`BLOCKED_HIGH_OR_CRITICAL`、`release_ready=false`、GHCR `NOT_PUBLISHED`，绝不存在经批准的正式 GHCR V1.1 远端镜像 digest。
- Docker-07 官方 Alpine 3.24 Python3.11 `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929` 隔离完整候选：原生双架构各 319/319 离线测试 PASS，当时 OS/PyPI High/Critical 均为 0。这是候选且跨发行版，**不是**旧 Debian 8 CVE 已修复或未来应用部署安全许可。

## 当前唯一新离线开发权限：Docker-08
- 用户在具体“启动 Docker-08 Alpine 正式运行环境迁移的**方案设计及离线开发**，本次不合并/发布/实机”的申请后答复「批准」。[Issue #46](https://github.com/Aspeternity/SeekPulse/issues/46) OPEN、[Draft PR #47](https://github.com/Aspeternity/SeekPulse/pull/47) OPEN，独立分支 `feat/s7-docker-08-alpine-runtime-offline`，唯一写入负责人 **ChatGPT**。精确分支 HEAD 与当前 CI 每次必须实时查，不预报成功。
- [ADR-0015](decisions/ADR-0015-v11-alpine-runtime-migration.md) 当前处于 **离线开发/未合并/未发布**：仅在 PR 分支中最小改动 opt-in `Dockerfile.v11` 从 Debian pinned base 到官方 Alpine pinned base，保留 Python 安全 pin/业务入口/非 root，更新既有 Trivy/CycloneDX 多 distro fail-closed 验证及 CI，并运行真实原生 AMD64/ARM64 完整镜像 SQLite WAL、TLS、网络隔离、模拟通知及容器资源上限测试。旧 `Dockerfile`、`docker-compose.yml`、`compose.v11.yaml`、`app/`、依赖和数据协议**不改**。
- **本阶段尚未获得**人工离线阶段验收、PR #47 独立合并权限、GHCR 发布、NAS/PVE/群晖/Portainer/VPS 的任何查看/部署、生产 SQLite/Token/Session 或真实 TG/Bark/ntfy 通知。父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) **OPEN/status:blocked**。

## 唯一下一道审批
Docker-08 实际开发完成后，核验 PR #47 **最新精确 HEAD** 的 G0 + Docker 适用工作流，原生 AMD64/ARM64 完整镜像、Trivy OS+PyPI/CycloneDX 和本地 SQLite/TLS/权限证据；**仅向用户申请已完成离线开发范围的阶段验收**。若用户验收通过，再**另行申请 PR #47 Ready + Squash 合并权限和合并后 G0**。正式 GHCR 多架构发布及用户现有 NAS/PVE Docker 安装各自另批，不能使用旧 VPS 方案替代或自动执行。
