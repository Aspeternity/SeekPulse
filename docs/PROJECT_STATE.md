# SeekPulse — 跨会话开发交接状态（GitHub 实时事实优先）

> 2026-10-15 快照。`AGENTS.md`、最新 Issues/PR/提交 SHA/CI 和用户的明确批准是最终依据；此文件不自动赋予实施许可。

## 已完成并分别独立批准合并
- S1–S6、S7-01 规划、Gate B、Docker-01 [#32/PR #33](https://github.com/Aspeternity/SeekPulse/pull/33)、Docker-02 [#34/PR #35](https://github.com/Aspeternity/SeekPulse/pull/35)、Docker-03 [#36/PR #37](https://github.com/Aspeternity/SeekPulse/pull/37) 均已完成各自**离线范围**人工验收、独立 Squash 合并和合并后 G0。
- 最新合并后 main `1d24b1564983465de340b3e30a758f52f45062ec`；精确 SHA 的 [G0 #38631128468](https://github.com/Aspeternity/SeekPulse/actions/runs/38631128468) **4/4 PASS**。旧研究 S0 Draft PR #17–#20 未合并。
- V1.1 `Dockerfile.v11` / `compose.v11.yaml` 是 opt-in，非 root/私有数据卷/管理 Web 回环；全新空卷须显式 `--init-fresh → --check → --run`，已有数据必须经过 S6 verified backup + `--prepare`，不能自动覆盖/Prime。旧 `Dockerfile` / `docker-compose.yml` 保持。
- Docker-03 已本地 Buildx/QEMU 证明 AMD64+ARM64 OCI/manifest 与 ARM64 无网络 CLI；**从未发布 GHCR 可拉取的 SeekPulse V1.1 镜像或正式 registry index digest**。

## 当前唯一开发授权：Docker-04 / Issue #38
- 用户在明确提出“Docker-04 发布前安全审查与离线开发（基础镜像 Digest 固定、OS/Python 漏洞扫描、SBOM 和供应链检查），仍不推送 GHCR、NAS/PVE 部署须另行批准”后直接回答“批准”。审计见 [Issue #38](https://github.com/Aspeternity/SeekPulse/issues/38)。
- 唯一写入负责人：ChatGPT，分支 `feat/s7-docker-04-security-review`，[Draft PR #39](https://github.com/Aspeternity/SeekPulse/pull/39)。本阶段**未获人工阶段验收、合并或发布授权**；PR HEAD/CI 结果会随提交变化，必须实时核对。
- ADR-0011：在 GitHub runner 核实官方 `python:3.11-slim` 双架构 index Digest 并固定到 V1.1 Dockerfile；对本地构建的 AMD64/ARM64 镜像执行公开漏洞库 OS/Debian + Python/PyPI CVE 检查、CycloneDX SBOM、scanner DB 新鲜度/完整性/架构与供应链校验。**CI 扫描执行成功 ≠ CVE 无风险，也 ≠ 用户授权发布**；缺数据库/漏扫判 UNKNOWN，High/Critical 判发布阻断。
- 官方基础镜像候选 index digest `sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`，证据为临时只读 [GH Actions #38632803851](https://github.com/Aspeternity/SeekPulse/actions/runs/38632803851)（含 AMD64 和 ARM64）。**它不是未来 GHCR 发行镜像 digest**。

## 明确未获准 / 唯一下一步
- 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) 继续 OPEN/status:blocked；独立 VPS 预检 #31 已因用户使用现有 PVE/Portainer/群晖而取消，但**从未授权进入这些机器**。未开始正式 GHCR registry push、Tag/Release、实际 Docker 部署、真实 Telegram/Bark/ntfy 通知、Web 隧道、生产 SQLite/Session/Token、灾难演练或 48–72h/Gate D–G。
- **唯一下一步**：对 Draft PR #39 最新 HEAD 完整核对 G0、Docker-01/02/03/04 CI 与 OS/Python CVE/双架构 SBOM 证据；发现阻断明确记录风险、不得误报可发布。完成后**仅申请 Docker-04 本次离线安全审查阶段验收**；通过后再单独申请 PR 合并，GHCR 发布及 NAS/PVE 实机再各自申请授权。
