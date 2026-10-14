# SeekPulse — 当前项目交接状态

> 更新于 2026-10-15。此文件只记录辅助快照，**GitHub Issues、PR、实时提交和 CI、用户明确审批为最终依据**，不可将过期状态当授权。

## 已验收合并的代码

- `main`：`d39761f47aa44ebc5a521a79338a35f166f9edf0`；合并后 [G0 #38623045093](https://github.com/Aspeternity/SeekPulse/actions/runs/38623045093) 精确对应，**4/4 PASS**。S1–S6、S7-01/PR #28、Gate B/PR #30、Docker-01/PR #33、Docker-02/PR #35 均分别完成离线验收及独立合并；旧 S0 Draft PR #17–#20 不动。
- Docker-01 [#32](https://github.com/Aspeternity/SeekPulse/issues/32)：`Dockerfile.v11`、`compose.v11.yaml`、固定 S1–S5 依赖、非 root/只读 rootfs/绝对卷、管理 Web 仅 Linux host 回环、单实例、默认不自动重启。旧 `Dockerfile`/`docker-compose.yml` 原入口不变。
- Docker-02 [#34](https://github.com/Aspeternity/SeekPulse/issues/34)：显式 `--init-fresh` 只服务新独立空卷（确认、唯一锁、stage+WAL checkpoint、完整性、Prime=0、禁止覆盖），`--check` 只读预检，`--run` 未准备则拒绝；已有数据库仍必须经 S6 verified backup 后走 `--prepare`。
- 当前 **无已获授权推送的 GHCR V1.1 镜像或经过远端验证的 digest**；离线 CI 通过 ≠ NAS/PVE 真部署或已发消息。

## 当前唯一开发授权：Docker-03 / 发布前离线准备

- 用户在明确申请“**Docker-03 多架构 GHCR 镜像发布准备的开发与离线 CI；不推送 GHCR、不部署 NAS/PVE，发布另行批准**”后答复“**批准**”。审计位置：[Issue #36](https://github.com/Aspeternity/SeekPulse/issues/36)。
- 唯一写入负责人 ChatGPT；分支 `feat/s7-docker-03-image-release-readiness`；[Draft PR #37](https://github.com/Aspeternity/SeekPulse/pull/37)。**未获 Docker-03 用户阶段验收或合并授权**。最新 HEAD SHA 和 CI 必须实时查看 PR，不能沿用本文件快照。
- 仅开发并通过 GitHub 临时 runner 验证：Buildx/QEMU `linux/amd64` + `linux/arm64` 本地 OCI archive、manifest/blob/config digest、nonroot/运行入口与敏感环境保护、版本 SemVer/rc、不可变 GHCR Digest 规则、Portainer/群晖未来使用说明。ADR-0010，`scripts/inspect_v11_oci.py`、`scripts/v11_release_policy.py`、`tests/test_s7_release_readiness.py`、`.github/workflows/s7-v11-release-readiness.yml`。**不执行任何 GHCR login/push/tag/release**。
- OCI 本地 SHA **不能**充当 GHCR 未来实际发布的 registry index digest；最新实时 CVE/依赖/基础镜像扫描、SBOM/签名和真正 GHCR 权限需未来独立审查。

## 未获准 / 唯一下一步

- 用户明确不需要 VPS 预检；原 [Issue #31](https://github.com/Aspeternity/SeekPulse/issues/31) 已 `not_planned` 关闭。用户已有 PVE/Portainer 和群晖 Docker，但从未授权连接、读取容器、部署或发送真实通知。父 [S7 Issue #16](https://github.com/Aspeternity/SeekPulse/issues/16) 继续 OPEN/status:blocked；真实 Gate D–G、48–72h、迁移/恢复、TG Session/Bot/Bark/ntfy secrets/发送、Web SSH 实测均 NOT_STARTED。
- **唯一下一步**：核验 Draft PR #37 最新精确 HEAD 的 G0、Docker-01、Docker-02 和 Docker-03 CI，完成 GitHub #36/#37/#16 审计，然后**单独请求 Docker-03 仅离线开发阶段验收**。通过后仍须单独请求 Squash 合并；GHCR 发布与 PVE/群晖实际部署再各自申请授权。
