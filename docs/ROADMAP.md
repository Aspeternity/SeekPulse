# SeekPulse 开发路线图 — 审批闸门

> 2026-10-15：**目前 S7，V1.1 Docker/Compose 发行前安全收尾**。S0 条件式 Go、S1～S6 离线验收合并，**Docker-01～09 各自离线验收并获独立 Squash Merge**；Docker-09 PR #49 已合并，新 main `09ab09416a94d472f32bf74e52da4897772d06fd`，postmerge G0 #38731768690 4/4 PASS。当前仅 **Docker-10 #50 / Draft PR #51 已获已知 pip/dotenv/zlib CVE 的离线受控修复开发批准**，尚未阶段验收/合并。正式 GHCR 仍 NOT_PUBLISHED、真实 NAS/PVE/群晖 Docker 部署另批；父 S7 #16 OPEN/status:blocked。


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
| S7 | V1.1 Docker Compose 发行前安全收尾和 GHCR/NAS/PVE 交付 | Docker-01～09 各自已验收合并；Docker-10 #50 / Draft PR #51：稳定 Alpine zlib 1.3.2-r1、pip 26.2.1、dotenv 1.2.2 定向修复/双架构真实 Trivy/CycloneDX + 全量回归 | 最新精确 HEAD 的所有适用 CI 全绿、独立离线阶段验收、再单独 PR Squash 合并；正式 GHCR 发版和 NAS/PVE 实机各申请新授权 | **当前 S7，Docker-01～09 已完成，Docker-10 仅离线开发获批/未验收未合并；GHCR NOT_PUBLISHED / 父 #16 OPEN blocked** |

### 开发原则

- 顺序以数据和接口依赖为准；新需求须评估范围和必要性，避免功能膨胀。
- 每阶段至少一个可验收的 PR，PR 相关 Issue 建立依赖；不能把未完成和已验收混为一谈。
- 按 `AGENTS.md` 的流程核验“唯一写入负责人”和仓库现状。
- 提前完成一个阶段的设计文档不构成对该阶段的代码执行授权。
