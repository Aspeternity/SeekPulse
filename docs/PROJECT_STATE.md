# SeekPulse — 跨会话项目状态（Issue / PR / 精确 SHA / CI 优先）

> 2026-10-15 最新开发快照；本文件不能代替 `AGENTS.md` 和实际 GitHub 记录或用户独立批准。

## main 已批准合并的阶段

- S1–S6、S7-01、Gate B、Docker-01 [#32/PR #33](https://github.com/Aspeternity/SeekPulse/pull/33)、Docker-02 [#34/PR #35](https://github.com/Aspeternity/SeekPulse/pull/35)、Docker-03 [#36/PR #37](https://github.com/Aspeternity/SeekPulse/pull/37)、Docker-04 [#38/PR #39](https://github.com/Aspeternity/SeekPulse/pull/39) 均各自完成离线验收、独立授权合并、合并后精确 G0 核验。
- `main fbb4f4009954567e3ed2943c0428075d8cf32fec`，真正合并后 [G0 #38639966882](https://github.com/Aspeternity/SeekPulse/actions/runs/38639966882) **4/4 PASS**；旧 S0 Draft #17–#20 未动。旧默认 `Dockerfile`/`docker-compose.yml`、旧 `requirements.txt` 保留。V1.1 仅 opt-in，非 root/只读 rootfs、回环 Web、数据库首次 `--init-fresh → --check → --run`；旧 DB 仍经 S6 verified backup + `--prepare`。
- Docker-04 公开 DB 2026-10-14 的 AMD64/ARM64 本地镜像 Trivy + CycloneDX 成功：每架构 Debian 87 / PyPI 65、Critical 0、High 48 条（OS 44 + Python 4）、High 去重 CVE 12 个，Medium 81、Low 77、Unknown 3。**安全结论 `BLOCKED_HIGH_OR_CRITICAL`，`release_ready=false`，正式 GHCR 镜像未发布也无远端 registry digest**。固定的 Python 官方基础镜像 digest 不是 SeekPulse 正式发行 digest。

## 当前唯一授权：Docker-05 / High CVE 离线修复开发

- 用户在紧邻申请“**是否批准启动下一阶段的 High CVE 专项审查与离线修复开发？仍不发布 GHCR、不部署 NAS/PVE；完成修复和复测后再单独申请验收**”后回复“批准”。[Issue #40](https://github.com/Aspeternity/SeekPulse/issues/40)，唯一写入负责人 ChatGPT，独立分支 `feat/s7-docker-05-high-cve-remediation`、ADR-0012；最新 PR 和 commit SHA **必须实时在 GitHub 核实**，不能在文档中预记 PASS。
- 已批准工作：只对 `Dockerfile.v11` 的最终镜像使用 `requirements-v11-security.txt` 修补 `aiohttp/jaraco.context/wheel` 已证实的 4 条 PyPI High 记录及 setuptools 内捆绑旧副本的额外 2 条 High，使用仅 V1.1 的 4 个精确版本（含 `setuptools==84.0.0`）；旧版依赖和应用、数据库/Web/通知契约不动。Debian ncurses/systemd/acl/util-linux/Perl 的 8 个 High CVE 仍需准确分析，不擅自混装 Debian unstable 或添加 scanner 忽略/免责。新增两版 Python 回归及 AMD64/ARM64 QEMU/Trivy 复扫；**即使 PyPI 归零，剩余 OS High 仍阻断正式镜像发布**。
- 官方 Debian 稳定版多数暂无可直接引入的受支持修复或标注 no-dsa/postponed；只记录上游状态与运行时影响评估，不将 OS High 标记已修复。详见 ADR-0012 和实时扫描结果。

## 尚未授权 / 唯一下一步

- 父 [S7 #16](https://github.com/Aspeternity/SeekPulse/issues/16) 继续 OPEN/status:blocked，用户不需要单独 VPS 预检；PVE/Portainer 与群晖 NAS 尚未获准登录或部署。正式 GHCR Push/Tag/Release、远端 digest、生产 SQLite/Session/Token、通知、48–72h、Gate D–G 全部 NOT_STARTED。
- **唯一下一步**：完成 Issue #40 开发和最新 HEAD G0 + Docker-01/02/03/04/05 CI，按两架构真实 PyPI/OS High 复扫更新风险审计；**仅向用户申请 Docker-05 离线修复开发阶段验收**。人工验收通过后仍须另申请 Squash 合并；High CVE 风险处置与 GHCR 真实发布/实机部署各另行批准，不能自动顺延。
