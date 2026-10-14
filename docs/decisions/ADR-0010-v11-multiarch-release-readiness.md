# ADR-0010 — V1.1 多架构 OCI / GHCR 发布准备（无远程发布）

日期：2026-10-15 · Docker-03 [Issue #36](https://github.com/Aspeternity/SeekPulse/issues/36) / 父 [#16](https://github.com/Aspeternity/SeekPulse/issues/16) · **仅获离线开发及 CI 构建授权**，尚未获得 Docker-03 阶段验收、PR 合并、GHCR 推送、Tag/Release、现场部署授权。

## 一、问题与决定

Docker-01 / #32 提供 opt-in `Dockerfile.v11` + `compose.v11.yaml`，Docker-02 / #34 完成新空数据卷的 `--init-fresh → --check → --run` 显式流程；前序代码均已用户验收和独立批准合并，当前基线 main `d39761f47aa44ebc5a521a79338a35f166f9edf0`，合并后 [G0 #38623045093](https://github.com/Aspeternity/SeekPulse/actions/runs/38623045093) 4/4 PASS。但既没有已发布 GHCR 镜像，也没有真实 NAS/PVE CPU 架构和 Compose 方言测试。不能把单平台 CI 绿色冒充可供群晖 ARM64 拉取的正式多平台镜像。

本次只新增**发布就绪设计与离线 CI 验证**：

1. **多架构镜像本地验证**：GitHub 临时 Linux runner 以 Docker Buildx / QEMU 构建 `linux/amd64` 和 `linux/arm64` 的**单一 OCI image-layout tar archive**，默认禁用 build attestation 以便解析两平台 manifest，使用 Python 标准库检查其 `index.json`、manifest/blob SHA256、镜像 config、arch、入口、10001:10001 非 root、版本/源 SHA / license labels、敏感 ENV。OCI 导出位置固定 `$RUNNER_TEMP`，不上传 artifact，不登录 GHCR，不推送 registry。ARM64 在 QEMU 下的验证仅说明模拟 Linux user-space 有效，**不代表真实群晖 ARM64 的 kernel/文件系统/性能兼容性**。
2. **唯一运行镜像，不改变业务行为**：保留旧 `Dockerfile` / `docker-compose.yml`；V1.1 使用相同 Python 3.11、`requirements-s5.txt`、`app.v11_main`、`CMD ["--run"]`、10001 UID/GID，仅新增镜像 OCI `version`、`revision`、`source`、`licenses` 等只读 LABEL 与有保守默认值的 build ARG。**不在构建时提供 Bot/Telethon/Bark/ntfy 真实凭据**，不能给镜像预装数据库或 Session。
3. **版本和标签准则**：将来若另行获批发布，允许唯一完整 SemVer `vX.Y.Z` 或 `vX.Y.Z-rc.N`，拒绝 `latest`、浮动 `vX.Y`、复用已经发布的相同 tag，以及未批准的短 SHA 标签。本地发布规划脚本只生成 JSON 方案，不创建远端 tag，也不进行 API 查询/写入。必须在用户批准的独立发布流程中再验证 GitHub tag/ref 不重用、Git 提交 SHA、关联 G0/多架构 CI、GHCR Package 权限和不可变镜像引用；**发布完成之后**实际从 GHCR 查询、多端解析并记录真实 `sha256:` 的 multiarch registry index digest，`compose.v11.yaml` 的 `SEEKPULSE_IMAGE=ghcr.io/aspeternity/seekpulse@sha256:<正式 index digest>` 才可用于实机。
4. **严禁混淆 OCI archive digest 与 GHCR digest**：本地 OCI archive 的 index / manifest / config digest 只能证明临时离线包完整性。GHCR 会接收不同的 manifest/attestation 或索引格式，**本地校验不能生成 GHCR 的正式发布 Digest**，在发布批准和远端读取之前状态始终 `NOT_PUBLISHED/UNVERIFIED`，绝不生成假的 64 位 Hex digest 供用户复制。
5. **安全/供应链原则**：Release 前至少两层检查：本轮离线 CI 的完整层/hash/架构/config/非 root/无密钥/默认不发送/Compose 没有特权、Docker Socket 或公开管理端口；正式发布前还须**独立批准并执行**对镜像、Python 依赖和基础 Debian layer 的实时 CVE/恶意内容扫描、基础镜像不可变 Digest 锁定/审查、GHCR 验证及可审计供应链签名/SBOM 决策。本轮不宣称完成实时 CVE 扫描。CI 的公开依赖下载是临时构建输入，不代表访问任何用户的生产 API。
6. **部署契约不变**：`compose.v11.yaml` 只能在未来镜像真正存在后、从 Portainer Standalone/群晖 Container Manager 拉取 Digest 镜像；目录必须是宿主绝对路径且非 root 可写；仅 Linux host network 的 127.0.0.1 Web + SSH 转发（host network 有宿主回环网络访问风险，必须实机单独评估）；初次创建空库必须先显式 `--init-fresh` 和 `--check`，旧库只能经过 S6 verified backup + `--prepare`；禁止同时运行旧版和新版；未完成 Gate D 不自动更改 `restart: "no"`。
7. **无需 VPS**：用户已有 PVE/Portainer 与群晖 Docker，未来任选其一作为经单独批准的真实测试环境。不能为本轮 CI 登录/探测或修改这些宿主机。Portainer 与群晖的 Engine/Compose 版本、平台 CPU、host network 和挂载/硬链接兼容均为 **NOT_STARTED**。

## 二、权限、回滚与验收

- **独立离线开发**：Issue #36，分支 `feat/s7-docker-03-image-release-readiness`，Draft PR，唯一写入负责人 ChatGPT。新发布流程与验证只在 GitHub runner 执行，CI 权限 `contents: read`，**绝不请求 packages:write 或 docker login / push / remote registry cache push**。对 CI 的最新精确 HEAD，逐项验证 G0、Docker-01/02、Docker-03 全量测试及 OCI 检查，必要时记录失败原因与修复；完成后**仅请求用户 Docker-03 离线阶段验收**。验收通过后，还必须**另行请求 PR 合并 main**，不可自动合并。
- Docker-03 不生成/上传 GHCR 镜像，不创建 Release/Tag，不读取/使用生产 SQLite/Session/Token、不发送 TG/Bark/ntfy 通知、不部署 PVE/群晖/NAS、不运行 Gate D–G/48–72h。
- **回滚**：新 Draft PR 未合并可关闭，不会影响原 V1.1 Dockerfile/Compose 所服务的真实宿主机；即使未来获准合并，此阶段仍不产生新的可拉取镜像，因此不能把 DB 降级当作真实回滚方案。
- **未来独立发布闸门**：确定并核实版本/架构/安全扫描/SBOM/标签可用性 → 向用户申请 GHCR 实际推送 → GitHub Actions 受控发布、远端多架构索引 + Digest 实证 → 用户选择 PVE/群晖后另行申请 Gate D 部署/运行与真正的恢复/告警测试。以上步骤目前全部 **UNAUTHORIZED / NOT_STARTED**。

