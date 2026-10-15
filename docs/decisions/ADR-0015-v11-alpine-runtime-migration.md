# ADR-0015 — V1.1 opt-in Docker Alpine 3.24 运行环境迁移（仅离线开发候选）

日期：2026-10-15 · [Docker-08 Issue #46](https://github.com/Aspeternity/SeekPulse/issues/46) · 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16)

**状态：DEVELOPMENT AUTHORIZED / NOT MERGED / NOT RELEASED。** 用户在 Docker-07 [Issue #44](https://github.com/Aspeternity/SeekPulse/issues/44) 已验收、[PR #45](https://github.com/Aspeternity/SeekPulse/pull/45) 独立授权 Squash 合并、main `30c246be5f7cb11fb315ccecc882798b75f28160` 且 [post-merge G0 #38718379825](https://github.com/Aspeternity/SeekPulse/actions/runs/38718379825) 4/4 后，针对 **“Docker-08：Alpine 正式运行环境迁移与离线兼容性验证，是否批准方案设计及离线开发；不包含合并、发布或实机部署”** 单独回答「批准」。据此仅可更改本独立分支的 opt-in V1.1 候选并跑临时 GitHub runner，不能认定已完成阶段验收、实际发布授权或用户宿主兼容性。

## 1. 旧 Debian Trixie 安全风险与新候选范围

- 旧 `Dockerfile.v11` 使用官方 Python 3.11 slim Debian Trixie 多架构索引 `sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce`。Docker-06 真实完整本地 AMD64/ARM64：PyPI High=0，Debian OS High **44 条受影响 binary package×CVE 记录 / 8 个不同 CVE**，Critical=0；因 Debian stable 官方尚无合适支持的全面修补，GHCR 发行为 `BLOCKED_HIGH_OR_CRITICAL` / `NOT_PUBLISHED`。
- Docker-07 [PR #45](https://github.com/Aspeternity/SeekPulse/pull/45) 原生两架构 **完整** V1.1 app Alpine 3.24 临时镜像：各 319/319 原有 Python 离线回归、pip 和权限/断网检查 PASS，两架构当次 Trivy OS+PyPI High/Critical 均 0；官方 `python:3.11-alpine3.24` **两架构 index digest `sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`**，Trivy DB `2026-10-15T07:10:08Z`。这是支持迁移设计的**候选证据**，并非正式运行时和/或生产行为的证明。
- Debian 8 个历史 CVE 不会因为包集合切换到 Alpine 而变成“已修复”。迁移后旧 Debian CVE 状态仍保留至 ADR-0013/014 的历史记录；如果 Alpine 新 CVE 报 HIGH/CRITICAL，其**完整安装后的新镜像**继续被阻断，绝不通过忽略规则、移除漏洞元数据或混合发行版降低显示计数。

## 2. 设计决策（仅已获批准的离线分支内）

1. **最小正式 opt-in Dockerfile 变化**：`Dockerfile.v11` `FROM` 改为 `python:3.11-alpine3.24@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`（原生 AMD64/ARM64 同一官方 index），把 Debian 的 `groupadd/useradd/install` 变为已在 Docker-07 候选上实际验证的 Alpine 可用、数值 UID/GID=10001 的目录创建和权限设定。仍保留准确 `ARG` 版本/修订号、OCI 标签、`HOME=/tmp` 可写 tmpfs、完整 `requirements-s5.txt + requirements-v11-security.txt` 同层安全升级与 `pip check`、`COPY app`、`USER 10001:10001`、`ENTRYPOINT python -m app.v11_main`、`CMD --run`。不更改应用/协议/源/数据库结构。
2. **原 fail-closed 证据逻辑保留而不是绕过**：Docker-04/06 本地扫描审计工具明确指定期望的 OS family，保留 Debian fixture/历史 8 CVE 的统计测试，新增 Alpine `pkg:apk` 库存与扫描 Family 校验，禁止拿 Debian purl 库存当作 Alpine 完整证据。缺失 OS/PyPI 类别、Trivy DB 超时/过期、镜像/平台/入口不匹配继续 CI 失败；历史 Debian CVE 缺失在 Alpine 记为 `NOT_REPORTED_IN_DIFFERENT_DISTRO_NOT_A_FIX`，**不得**标 `FIXED`。
3. **完整构建与真实扫描**：利用已有 Docker-01～07 回归，特别 Docker-04 的原始 Trivy OS+library 和 CycloneDX 同镜像验证；隔离 runner 原生 AMD64/ARM64 针对 **`Dockerfile.v11`** 的公开官方 index 固定 digest、依赖安全版本、非 root、无密钥与发布动作；如果任何 HIGH/CRITICAL 或未知扫描状态，相关安全门槛不得标记通过。即使全为 0 也始终 `release_ready=false` / `release_authorized=false`，GHCR 未发布。不要把内网/产品环境兼容等同于 Github Actions 模拟。
4. **应用契约和隔离集成**：S1–S7 完整离线测试包含 SQLite/WAL/事务恢复、Feed/Telegram/通知模拟、Web 管理认证/CSRF/loopback、Gate B 生命周期；额外在已迁移 `Dockerfile.v11` 构建的原生 AMD64/ARM64 容器中，以 `--network none` + 只读 rootfs + nonroot + `cap_drop ALL` + `no-new-privileges`、tmpfs/内存/CPU 上限验证 SQLite WAL/fsync/hardlink、Python TLS 默认 CA/证书验证与无凭据 fail-closed CLI。此处**不会**发送任何真实 TG/Bark/ntfy 请求，TLS 不会连接真实远端。
5. **Compose/Portainer/群晖 API 均不变**：已批准的 `compose.v11.yaml` 仍 `network_mode: host`（Web bind 127.0.0.1）且无 ports、只读 rootfs、`cap_drop ALL`、`no-new-privileges`、显式镜像 digest 和绝对 bind 数据卷 `create_host_path:false`、`restart:no`。原 `Dockerfile`、`docker-compose.yml`、上游 `requirements*.txt` 和 `app/` 不变。真实 PVE / 群晖 NAS 不在测试或审批范围。

## 3. 明确风险、回滚和停止条件

- **ABI / musl**：Alpine 的 musl 与 glibc 不同，第三方 wheel 构建、加密/证书/CA、时区、SQLite 锁和硬链接在真实挂载卷可能有平台差异。即使双架构原生 GitHub runner 绿色，也不覆盖 NAS/PVE/Portainer/群晖实机的引擎版本、SELinux/AppArmor、映射 UID/GID、SMB/NFS/硬链接和 host network；这些后续独立 Gate D 只读/隔离验收和真实部署另批。
- **证据风险**：已记录的 Debian Trixie 44/8 作为**历史基线**不可删除、豁免；迁移后的 Trivy 可能随公开 DB 增加新发现，若 HIGH/CRITICAL 出现必须 `BLOCKED_HIGH_OR_CRITICAL`，未知/无 OS/Python inventory 必须 fail closed。安全扫描 PASS 和“零 High”均不等于自动发布安全/法律风险接受。
- **CI-only 回滚**：本 Draft PR 未合并前，关闭 PR/撤销分支即可，main 仍 `30c246be...` 的 Debian Trixie，用户没有新镜像；若未来经独立合并，需要恢复旧基线也应新授权、复扫旧 8 High，不允许偷偷 downgrade 规避风险。
- **继续禁止**：自动合并 main、GHCR login/push、Tag/Release、正式 index digest、连接用户 NAS/PVE/Portainer/群晖/VPS、读写生产 SQLite/Session/Token、真通知/初次登陆或 48–72h 实机、Gate D–G。

## 4. 退出门槛与下一审批

- PR 的最新精确 HEAD 上所有适用 G0 / Docker01–08 CI 全绿；至少原生 AMD64+ARM64 **正式 `Dockerfile.v11`** 完整应用、SQLite/WAL/TLS/离线假通知与容器限制、真实 Trivy/CycloneDX/安全 pin 校验，报告 DB 时间与发现数量，失败不能假称 PASS。
- CI 和完整阶段变更说明（不改变 Docker Compose 宿主/旧版），在 Issue #46 / Draft PR 记下 SHA、CI、风险、rollback。
- **只申请 Docker-08 已完成离线代码与验证范围的阶段验收**。用户单独确认后，再单独申请精确 PR Squash 合并；如合并再验新 main G0。正式 GHCR 推送/Tag、NAS/PVE/群晖现场以及真实通知/数据库/备份仍须**完全独立**批准。
