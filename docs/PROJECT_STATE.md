# SeekPulse — GitHub 跨对话状态（2026-10-16 Web-first B 开发中）

> 每次新对话**先读 `AGENTS.md`、`docs/APPROVALS.md/json`、`docs/ROADMAP.md`、相关 ADR**，然后实时核实 GitHub main/PR HEAD/Issue/CI。此文件是交接快照，不是额外授权；**历史 R3-0/Docker-11 静态记录已非当前工作锚点**。

## 当前最新事实

- 仓库：`Aspeternity/SeekPulse`。**main `0fc92f9ad3ad57eb1153f15666ab1c054632da94`**；已发布 `v1.1.0-rc.1` 属于 **Prerelease**，不是用户 NAS/PVE/Portainer 实机验收后的 Stable。S7 父 Issue #16 尚有实机交付闸门；历史 GHCR/R3 方案不得当成 Web-first B 开发许可。
- 用户已确认 **Web-first**：Docker/Portainer → 独立 Web 管理中心 → 统一配置与运行管理 → RSS/TG/规则/通知引擎 → SQLite/受保护配置。RSS/TG 单独启停或双源协同；通知选择 Telegram Bot/Bark/ntfy，各自独立；启用 Bot 后保留 Telegram 命令管理。
- **A 阶段 UI V4 已验收、PR #60 已独立授权 Squash 合并**；Issue #59 CLOSED。主导航一套侧栏，系统设置四顶部分类；独立首注/登录，没有强制安装向导。main postmerge [G0 #38885495278](https://github.com/Aspeternity/SeekPulse/actions/runs/38885495278) 4/4 SUCCESS。
- **B 阶段仅获“架构设计 + 独立分支离线开发”授权**：Issue [#61](https://github.com/Aspeternity/SeekPulse/issues/61)，独立分支 `feat/web-first-b-foundation`，Draft PR [#62](https://github.com/Aspeternity/SeekPulse/pull/62)，唯一写入负责人 ChatGPT。继续直接在此分支上开发/修复，**未获 B 阶段验收、合并或发布授权**。
- **用户特意纠正首注行为**：Portainer 部署后，首次打开浏览器直接出现「创建管理员」；用户自行输入用户名、密码和确认密码。**不得生成默认账号/密码、容器日志验证码、初始化码，或附加安装向导/CLI 初始化步骤**。注册完成显示独立登录页，关闭公开注册，重启保持；只允许可信局域网访问。
- B 已有独立 `app.web_first_main` / `app.web_first` / `app.web_first_store`、`Dockerfile.web-first`、`compose.web-first.yaml`、最小 Web 依赖、V4 样式的设置与注册页面、专用 SQLite 初始化/异常拒绝、真实 Docker CI 空卷注册/登录/持久化/重启测试。**镜像仍未 GHCR 发布**，示例 Compose 使用 `web-first-b-NOT-PUBLISHED` 明确阻止误部署。版本号未升级，尚无真实采集/通知接入；见 [ADR-0019](decisions/ADR-0019-web-first-portainer-admin-bootstrap.md) 和 [B 部署候选说明](deployment/WEB_FIRST_B.md)。
- B 最新 HEAD、PR/CI 状态需**每次实时查询**，不得直接沿用本文件中任何旧的 SHA 或旧的 CI 绿灯。专项 CI：`.github/workflows/web-first-b.yml`；同时查看 G0/S1/S5 的同 SHA 运行。

## B 阶段退出闸门

1. 最终 PR #62 精确 HEAD：B 专项 Python 3.11/3.12 + Docker 首注/重启、G0、S1、S5 及必要安全回归完整成功。
2. **先单独申请用户 B 阶段离线开发验收**；收到明确验收后，再另行申请 PR Ready/Squash Merge main。
3. 实际 GHCR 发布、NAS/PVE/群晖/Portainer 登录部署、真实 Token/SQLite/Session/通知、旧 RC1 数据迁移、C 阶段集成，都须分别获得额外授权。不可将“离线 GitHub Runner Docker 测试”写成用户实机验收。

## 历史项目边界

旧 S0～S6 核心及 S7 Docker-01～11 的单项验收和 CI 已存档在对应 Issues/PR/ADR；这些算法应在 C/D 阶段**择优复用，不应该绕过适配契约直接启用双写入者或自动迁移现有生产数据库**。当此文件与最新 GitHub 状态不一致，以后者和用户明确批准为准。
