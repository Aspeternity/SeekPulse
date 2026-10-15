# SeekPulse 开发路线图 — 审批闸门

> 2026-10-15：SeekPulse 仍处 **S7 V1.1 Docker Compose 正式发行前收尾**，Docker-01～10 各自离线验收并另获独立 Squash Merge；Docker-10 PR #51 已合并，main `c6c8d8ca68a7e5763baca0e2b4ef5e1592974a93`，postmerge G0 #38742527999 4/4 PASS。当前仅批准 **Docker-11 / Issue #52 / Draft PR #53** GHCR 发行前最终安全与供应链方案及离线准备，尚无阶段验收、PR 合并、实际 GHCR 推送/Tag/Release 或 NAS/PVE 实机。父 S7 #16 继续 OPEN/status:blocked。


| ID | 阶段 | 必需产物 | 退出门槛 | 状态 |
|---|---|---|---|---|
| G0 | 工程建档 | 上游 Fork、治理/许可、Issues/PR、基础 CI、接续脚本 | Draft PR + HEAD SHA 对应完整 CI + 用户验收 | 已验收（2026-10-13 用户确认；Draft PR #1 仍未合并；记录更新后须核验最新 HEAD CI） |
| S0 | 来源与通知可行性 | TG/RSS 采样及延迟对照、Apprise 验证、资源预评估 | 有可复现样本、故障与限制报告、用户批准下一步 | **条件式 Go 已验收**（#8；残余风险保留） |
| S1 | 上游基线 | 回归测试及 CI 稳定性、依赖兼容 | 原功能回归通过、版本锁定评估 | **已验收并合并 PR #21**（#9） |
| S2 | 统一业务核心 | 标准帖子、规则契约、原子投递与迁移 | 并发、字段不全、重启模拟通过 | **已验收合并**（#10/#11，PR #22/#23，main b895bc8） |
| S3 | 双来源接入 | TG/RSS 适配、游标补查、来源健康 | 双源独立及故障恢复通过 | **已验收并合并**（Issue #12、PR #24，main f5c3f3c，CI 4/4） |
| S4 | 多渠道通知 | Telegram、Bark、ntfy、路由、优先级 | 多目标发送与限流/重试通过 | **已验收并合并**（Issue #13、PR #25，main 6d5f078，CI 4/4；仅离线核心） |
| S5 | Web 管理 | 界面、认证、规则管理、状态统计 | 双端一致、权限与 CSRF/XSS 测试通过 | **离线已验收并合并**（Issue #14、PR #26，main 9fe66d9，G0 4/4） |
| S6 | 稳定性硬化 | WAL 快照/校验/恢复至新 DB 路径、故障注入、人工回滚规程 | 可验证恢复、资源与故障测试通过 | **离线验收并合并**（Issue #15 / PR #27，main 12ce325，G0 4/4；实机未验） |
| S7 | V1.1 Docker Compose 最终安全/供应链与 GHCR/现有 NAS/PVE 交付 | Docker-01～10 离线验收合并；Docker-11 #52 / Draft #53：精确源码 HEAD、Action SHA、双架构 Trivy/CycloneDX/OCI 本地安全证据、不可变 digest/签名与回滚方案 | 最新 HEAD 全 CI 全绿 + 独立离线验收 + 另行合并；真实 GHCR 发行/Tag/Release 和 NAS/PVE/群晖 Docker 实机各独立批准 | **Docker-01～10 已完成；Docker-11 仅离线设计/准备获批，尚未阶段验收/合并；GHCR NOT_PUBLISHED，父 #16 OPEN blocked** |

### 开发原则

- 顺序以数据和接口依赖为准；新需求须评估范围和必要性，避免功能膨胀。
- 每阶段至少一个可验收的 PR，PR 相关 Issue 建立依赖；不能把未完成和已验收混为一谈。
- 按 `AGENTS.md` 的流程核验“唯一写入负责人”和仓库现状。
- 提前完成一个阶段的设计文档不构成对该阶段的代码执行授权。
