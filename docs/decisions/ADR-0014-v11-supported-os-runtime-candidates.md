# ADR-0014（提案 / 未采纳）— V1.1 Debian OS High 的受支持处置与隔离候选

日期：2026-10-15 · 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) · [Docker-07 #44](https://github.com/Aspeternity/SeekPulse/issues/44)

**状态：PROPOSED / CANDIDATE ONLY。不是运行环境切换决定。** 用户在 Docker-06 阶段验收与 PR #43 独立合并成功后，对“单独制定受支持的 OS 漏洞修复或替代基础镜像方案”回复「批准」。本次范围仅限研究、文档、独立分支和 GitHub 临时 runner 的公开镜像本地候选试验；尚未批准正式 runtime 迁移、OS High 风险豁免、GHCR 发布或 NAS/PVE/群晖/Portainer 实机。

## 1. 已证事实与三个不能混淆的概念

- Docker-06 合并后的 main 为 [accc0b26097b75a5fa724b5ca303d0c87c9be195](https://github.com/Aspeternity/SeekPulse/commit/accc0b26097b75a5fa724b5ca303d0c87c9be195)，其 [G0 #38711994265](https://github.com/Aspeternity/SeekPulse/actions/runs/38711994265) 4/4 成功。当前 **已完成 V1.1 本地 Debian Trixie 镜像** AMD64/ARM64 两架构的真实 Trivy/CycloneDX：PyPI High=0，OS High=44 个「受影响 binary package × CVE」报告条目，**8 个不同 CVE**，Critical=0。
- 仅官方 **Bookworm 基础镜像**的 OS-only 候选每架构 55 个 High 条目、上述 8 个 CVE 全在，但它**不是安装完同一 V1.1 Python 应用的镜像**；故 55/44 不能作等价风险排名。
- 扫描器 HIGH 是客观可追溯的包级检测；某一漏洞特权攻击前提在既有非 root 10001、cap_drop ALL、read_only rootfs、no-new-privileges 和无 Docker socket 下难以达成，可用于暴露面评价，但**既不消除 CVE，也不授权绕过 High 安全门槛**。
- 若将未来候选切换到另一个发行版，原 Debian CVE ID 不再出现可能只是发行版/包不相同。必须标 **NOT_REPORTED_IN_DIFFERENT_DISTRO** 而非声称 8 个漏洞已经修复；同时必须扫描该新发行版自身的安全风险和 PyPI 依赖。

## 2. Debian 官方稳定版状态（2026-10-15 再核实）

| CVE | source package | Trixie / Bookworm | 备注 |
|---|---|---|---|
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses | vulnerable / vulnerable | infocmp CLI；稳定版 no-dsa |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | systemd | vulnerable / vulnerable | systemd-homed 本地权限；no-dsa/postponed |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | acl | vulnerable / vulnerable | acl 2.4.0 引入新 ABI，不从 sid/forky 混装 |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | util-linux | vulnerable / vulnerable | mount 辅助程序后处理特权前提 |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | util-linux | vulnerable / vulnerable | nsenter --join-cgroup 特权前提 |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | util-linux | vulnerable / vulnerable | fstab/X-mount.subdir 特权前提 |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux | vulnerable / vulnerable | 授权 bind mount SUID/权限变更 |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl | vulnerable / vulnerable | Archive::Tar 不可信 tar 大小声明；postponed |

官方 unstable/forky 部分已修复，但并不构成可合法混装至 Trixie/Bookworm 的 ABI、安全维护、供应链依据。若未来 Debian stable 有正式安全更新，重新验证其 source/binary 固定版本、官方 index digest、两架构应用完整镜像、Trivy/SBOM/运行行为，而不是简单跑 apt upgrade 就宣布清零。

## 3. 候选决策矩阵（未选定生产方案）

| 路线 | 官方支持与优势 | 风险 / 是否进入本轮 |
|---|---|---|
| A. 继续 Trixie，等受支持修复 | 保留当前经验证的 glibc/依赖/交付约束；后续最小变化 | **保底方案；目前 8 个 OS CVE 仍未修复，保持 GHCR BLOCKED** |
| B. 改用 Bookworm | Debian 官方稳定系列；glbic 兼容概率较高 | Docker-06 证据显示原 8 个 CVE 未消失；**不以版本回退冒充修复** |
| C. 官方 Python 3.11 + Alpine 3.24 | 官方 Python 镜像、amd64/arm64、Alpine 3.24 稳定支持（官方发布支持期截至 2028-06-01） | **仅隔离研究候选**；musl 不等于 glibc，Python native wheels、OpenSSL/证书、SQLite/WAL、非 root UID、平台兼容及 Alpine 自身 CVE 必须独立验证 |
| D. 其他 distroless / Ubuntu 组合 | 理论上可减少不必要程序 | 暂无同等 Python 3.11 双平台依赖链/安全修复证据；不投入未经证实的新复杂度，不以删除包管理元数据隐藏漏洞 |

Alpine 官方分支支持见 https://www.alpinelinux.org/releases/ ；官方 Python 标签/支持架构见 https://github.com/docker-library/official-images/blob/master/library/python 。官方列出的 Python 3.11-alpine3.24 同时包含 amd64 与 arm64v8，不等于 SeekPulse 已通过两个平台兼容/安全验收。

## 4. Docker-07 严格受限的离线可行性验证

1. 单独的 **CI-only candidate Dockerfile**（不能被 Compose 引用、不能当作 GHCR 正式产物），以 Docker 官方 Registry **按完整多架构索引 digest** 拉取 `python:3.11-alpine3.24`；每个 CI arch 必须输出实际 index digest/平台与本地 inspect 身份。未成功确认官方身份或两个目标平台，不得通过。
2. 构建与当前 `Dockerfile.v11` 完整应用等价的软件包集合：同 `requirements-s5.txt` / `requirements-v11-security.txt` 的确定版本，同 `app/`，同 Python 3.11 和 V1.1 入口；仍数值 UID/GID=10001、禁真实机密。若 musl wheel/编译依赖失败则如实标不可行，不偷偷依赖第三方源或降级 pin。
3. 在无网络、无凭据、只读 rootfs、cap_drop/no-new-privileges 中核验 `pip check`、现有四个 Python 安全 pin、基础 app imports，验证不自动运行 RSS/TG/通知。不得接入用户 NAS/PVE。
4. 对 **相同候选完整应用镜像**扫描 Alpine OS 与所有 PyPI 包的 Trivy HIGH/CRITICAL、CycloneDX SBOM，并核验 CVE DB 时效、扫描类别、镜像平台/标识、非 root 和本地候选禁止发布。不能将 OS-langs 缺失、扫描异常、空包清单记成“0 CVE”。记录真实 High ID/包版本；无高危仅代表一次扫描结果，不是最终安全发布资格。
5. 如果两个 arch 的官方 base digest 不一致，禁止把结果说成同一个确定候选；继续保持 `REQUIRES_DIGEST_RECONCILIATION`，再有权限的前提下重测。
6. 比较实测镜像大小与现有隔离镜像，确认未来需要额外的 Web 登录/SQLite/WAL、TLS 验证、双源/通知模拟全回归和群晖/Portainer NAS/PVE 平台验收，不能仅凭 import 和 Trivy 宣称完整兼容。

## 5. 不变条件、验收与下一次独立授权

- 本阶段 **不改** `Dockerfile.v11`、`compose.v11.yaml`、旧版 Dockerfile、`app/`、任何 requirements pin、DB/迁移/用户/通知协议。**不允许**删除 Debian dpkg 元数据、ignore/降级 Trivy、sid/forky 混装、借 CI 绿色解除发布阻断。
- 继续 `BLOCKED_HIGH_OR_CRITICAL`（针对**当前正式候选 V1.1 Debian**），`release_ready=false`、`release_authorized=false`、`GHCR NOT_PUBLISHED`，父 #16 继续 OPEN/status:blocked。
- 单独 Issue/分支/Draft PR/CI；无 GHCR login/push、正式 Tag/Release、任何 NAS/PVE/Portainer/群晖/VPS 登录、生产 Token/Session/SQLite、真实 TG/Bark/ntfy，或 Gate D–G/48–72h。
- 完成且验证对应最新 HEAD 的临时 runner 证据后，**先申请 Docker-07 仅候选研究阶段验收**。若 Alpine 证据可行，将另行提出“是否同意实际变更 V1.1 运行基础镜像”的独立方案和开发授权（先兼容性/安全回归，后另行验收、独立合并）。本 ADR **不得被理解为已正式选用 Alpine**。

## 6. 第一轮双架构真实候选证据（仅已完成的旧 HEAD，非当前最终 PR CI）

[Draft PR #45](https://github.com/Aspeternity/SeekPulse/pull/45) 原 HEAD `8c3c5d03c317ec1081442a39d7a6d8163294a420` 的 [G0 #38714422113](https://github.com/Aspeternity/SeekPulse/actions/runs/38714422113) **4/4 PASS**、[Docker-07 #38714422199](https://github.com/Aspeternity/SeekPulse/actions/runs/38714422199) **3/3 PASS**（官方 Registry index job + AMD64/ARM64 完整应用构建、pip、断网只读 import、OS+PyPI Trivy 与 SBOM）。两架构均绑定同一个官方多平台候选 digest：

`docker.io/library/python:3.11-alpine3.24@sha256:d9368b3a5ac59afea7b5d4f2e2aea0941dbf9fdee9c369c5bec00b98244bc929`

| 该次本地完整候选 | AMD64 | ARM64 |
|---|---:|---:|
| 本地镜像 Docker inspect 大小（byte） | 137481095 | 141675652 |
| Trivy OS High / Critical | 0 / 0 | 0 / 0 |
| Trivy PyPI High / Critical | 0 / 0 | 0 / 0 |
| pip check / 指定四个 Python 安全 pin | PASS | PASS |
| non-root UID/GID 10001、只读根文件系统、断网 app import | PASS | PASS |

当时公开 Trivy DB `UpdatedAt=2026-10-15T07:10:08Z`；正式 `Dockerfile.v11` 没有任何替换、GHCR `NOT_PUBLISHED`。**这是不同 distro 安装的同 V1.1 app 候选的一次真实扫描结果，不是 Debian 漏洞已经修复、也不是随后的完整业务测试已通过或获得发布授权**。此后新增候选内部 **全 S1–S7 单元回归**；最终 PR HEAD 要独立重新实测，不能复用这里旧 HEAD 的绿色为新 HEAD 结论。
