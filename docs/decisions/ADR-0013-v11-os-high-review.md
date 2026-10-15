# ADR-0013 — Docker-06 Debian OS High 漏洞处置：证据、候选与发布阻断

日期：2026-10-15 · [Issue #42](https://github.com/Aspeternity/SeekPulse/issues/42) · 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16)

> **独立权限**：用户仅批准 Docker-06 的 Debian OS High 漏洞审查和 GitHub 临时 runner 离线修复开发；**未批准阶段验收、合并 PR、接受/豁免剩余 High、GHCR login/push/Tag/Release 或 NAS/PVE/群晖实机部署**。执行结果必须与最新代码 HEAD、GitHub CI 和官方漏洞数据对应；CI 绿色不是安全发行资格。

## 1. 事实基线与指标定义

- 已获用户独立验收并 Squash 合并的 Docker-01～05 以 [main `e78112a7123758da24340f4c59f3df190c445ea8`](https://github.com/Aspeternity/SeekPulse/commit/e78112a7123758da24340f4c59f3df190c445ea8) 为起点；其合并后 [G0 #38703450876](https://github.com/Aspeternity/SeekPulse/actions/runs/38703450876) **4/4 PASS**。
- Docker-05 [PR #41](https://github.com/Aspeternity/SeekPulse/pull/41) 的实际 Trivy [#38643432789](https://github.com/Aspeternity/SeekPulse/actions/runs/38643432789)（AMD64 job #116124724088、ARM64 job #116124724316）每架构：Python High **0**，Debian OS High **44 个包×漏洞记录**，去重 **8 个 CVE 标识**，Critical 0。**44≠44 个独立漏洞**。SBOM 87 Debian / 63 PyPI 包，环境本身已确认 non-root、pip check、OCI 两架构、ARM64 断网 CLI。
- **固定基础镜像**（由 Docker-04 官方 Registry 已验 AMD64/ARM64 的索引 digest）`python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce` 为 Debian **Trixie**；它是**基础镜像索引 digest**，不是 SeekPulse GHCR 已发布的 index digest。当前没有发布任何 V1.1 SeekPulse GHCR 镜像，不能擅自引用 tag 或假冒远端 digest。
- Trivy 基于 Debian **source package** 关联其各种 binary package，可能给 libtinfo/libsystemd/libmount 等都打同一 CVE 标识。这不自动证明每个包都包含可利用路径，也**不构成自动将严重性降为 LOW 或白名单放行的理由**。

## 2. Debian 官方跟踪器（2026-10-15 只读核查）

| CVE | 发行版中的 source package | 受影响函数/程序和必须具备的攻击前提 | Debian 13 Trixie / Debian 12 Bookworm 状态 | 离线决策 |
|---|---|---|---|---|
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | ncurses | `infocmp` CLI 的恶意 terminfo 字符串引发栈溢出；`libtinfo` 等被扫描命中不意味着运行了该 CLI | 两者 vulnerable；官方 no-dsa | 不从测试分支混入；核查镜像 `infocmp` 是否存在与应用能否调用，但继续报告 |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | systemd | `systemd-homed` 管理的登录用户的本地权限提升；镜像只带 `libsystemd0/libudev1` 不表示运行了 `systemd-homed` | Trixie vulnerable no-dsa；Bookworm vulnerable/postponed | 以运行入口/进程和已存在服务判断真实暴露前提；不豁免 CVE |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | acl | `libacl` 路径函数处理攻击者控制的符号链接且有**特权调用者**；修复需要新的 `acl_*_at` ABI | Trixie vulnerable no-dsa；Bookworm vulnerable/postponed | 不混装 sid 的 `acl 2.4.0`，避免 ABI 问题 |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | util-linux | `mount` helper 错误状态和后置钩子，须特权 mount / 允许的 fstab 设置 | 两者 vulnerable；Trixie no-dsa | rootless/cap_drop/no-new-privileges 限制暴露面，不冒充补丁 |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | util-linux | `nsenter --join-cgroup` 需特权操作并遗留文件描述符 | 两者 vulnerable；Trixie no-dsa | 当前单 Python 进程不会主动 nsenter，但仍计入 OS High |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | util-linux | `X-mount.subdir` 和支持 fast-path 的内核 + fstab 授权条目/中间符号链接 | 两者 vulnerable；Trixie no-dsa | 不更改用户真实主机 mount/fstab；仍阻断 |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | util-linux | 授权 bind mount 来源路径 TOCTOU、SUID mount 和扩展 owner/group/mode 选项 | 两者 vulnerable；Trixie no-dsa | 已有容器限制可减小利用前提，但不自动解除 |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | perl / Archive::Tar | 处理不可信 TAR header 中异常声明大小可导致内存耗尽；不等于 Python `tarfile` | 两者 vulnerable/postponed | 不给 Perl 加未批准的单包上游 patch，也不假称不可利用 |

**稳定版替换结论**：官方 Debian Bookworm 与 Trixie 对上述 8 项均显示 vulnerable（若未来更新，以新鲜官方信息与实际镜像为准），所以仅将基础镜像由 `slim` 退回 `slim-bookworm` **不能消除这些 CVE**，并可能带入更多旧包漏洞。forky/sid 当时含部分上游修复，但属于**测试/不稳定 Debian 依赖集合**，不得在已固定的稳定运行时强行跨系列混装。纯粹 `apt upgrade` 不会凭空产生 Debian stable 目前没有发布的官方安全修复版本。

## 3. 本阶段允许的实现和证据契约

1. **单独的只读审计器** `scripts/v11_os_high_review.py` 接受同一 runner 内真实 Trivy image JSON 与经 Docker-04 验证的公开扫描摘要，逐 CVE/逐 package 输出安装版本、是否有扫描器报告修复版本、Trivy 统计数及报告与扫描的一致性。新增 CVE 不得静默忽略。漏扫 OS/语言、镜像身份或统计不一致必须 fail-closed。扫描中某历史 CVE 不出现时只能判 `NOT_REPORTED_VERIFY_UPSTREAM`，不能自动称 `FIXED`。
2. 保留 `scripts/v11_security_evidence.py` 中的 OS/PyPI 完整 Trivy、CycloneDX、时效和身份校验，并在同一步骤中计算额外的 OS 高危来源矩阵。即使候选镜像新扫描 OS High 降低，**任何 High 仍然 `BLOCKED_HIGH_OR_CRITICAL`；没有 High 也仍为 `REQUIRES_USER_RELEASE_APPROVAL`，不自动 `release_ready=true`**。
3. **候选只读对比 CI**：GitHub 临时 runner 经 Docker 官方 Registry 只读核实 `python:3.11-slim-bookworm` 含 amd64/arm64 多平台 index，分别拉取临时本地镜像、Trivy `--pkg-types os`，输出其当前 8 项匹配和 OS High 统计，不上传报告、不更改 V1.1 runtime `FROM`。候选扫描**不等于**替换后应用可运行，也不等于 CVE 已消失。若 Registry/DB 不可用，不能宣称候选通过。
4. 严格保留 `compose.v11.yaml` 的非 root、cap_drop ALL、read_only、no-new-privileges、无 Docker Socket/Port、明确 `--run` 的 opt-in 初始数据库保护；回归这些静态契约。**本阶段不修改当前 V1.1 基础镜像或 App**，因为已核查的全部 8 个漏洞暂无可直接使用的官方稳定版修复；否则就是为“清零 CI”而添加不受支持的、可能破坏 glibc/ABI 的跨版本变化。
5. **用户权限**：只对独立 Docker-06 Draft PR / GitHub 临时 runner，`contents: read`，无 GHCR login/push/Tag/Release、无 NAS/PVE/群晖/VPS、无用户 Token/Session/生产数据库/真实通知；父 S7 #16 始终 OPEN/blocked。此 ADR 说明“有明确理由没有进行不安全的运行时修补”，不声称漏洞已解决。

## 4. 验收与下一审批

- Python3.11/3.12 全量离线回归、新 OS 风险审计正向/负向测试、G0 + Docker01～06 相同最新 HEAD CI，Trixie 双平台真实扫描与 Bookworm 官方双平台候选只读对照；记录两个平台 DB 时间、High/Unknown 数量和 8 项细节。
- 如确认无需更改 app/、Dockerfile.v11 与镜像 pin，**离线审查与自动审计可以申请验收，但不叫“8 项全部修复完成”**。风险保留到 Debian 官方更新、后续受支持的基础镜像经兼容性验收或用户另行明确批准的风险处置阶段。
- 本阶段完成后仅向用户申请“Docker-06 **已完成的离线 OS High 官方状态审查、候选比较和自动化证据**阶段验收”；以后再单独申请 PR 合并、正式 GHCR 发布和实际 NAS/PVE 操作。即使 CI 21/21 绿色也不跨越权限闸门。
