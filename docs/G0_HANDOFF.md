# G0 工程文件包 — 初始交接记录

**制作日期：2026-10-13，历史快照。新 AI 不得把这份记录当成 GitHub 实时状态。**

## 已制作（本地文件，不代表远程提交）

- `AGENTS.md`、`CLAUDE.md`、`GEMINI.md`：多 AI 共用规则与入口。
- `docs/PLAN.md`、`APPROVALS.md` 和 `APPROVALS.json`：已批准 V1.1 与仅 G0 执行范围；后续授权应增量记录。
- `docs/ARCHITECTURE.md`、`ROADMAP.md`、`TEST_MATRIX.md`、`decisions/ADR-0001..0003`：技术契约与验收门槛。
- `.github/ISSUE_TEMPLATE/`、`PULL_REQUEST_TEMPLATE.md`、`CODEOWNERS`、`workflows/g0-ci.yml`：任务/审查模板及 CI 定义。
- `docs/ISSUE_SEED.json`：15 个稳定编号任务，其中 G0 3 项，后续 S0–S7 均明确标记为未授权。
- `scripts/context_report.py`：只读 GitHub 实时交接报告，断网或无数据时标记 UNKNOWN。
- `scripts/bootstrap_issues.py`：默认 dry-run，显式 --apply 才创建 Issue，且先枚举避免重复。
- `scripts/validate_g0.py`、`tests/`：治理验证与初始行为冒烟测试。

## 本地核验结果

- G0 必要文件与审批范围检查：通过。
- 本地 G0 工具单测：8 项通过。
- Python 源码语法编译：通过。
- Workflow 与 Issue Forms YAML 语法：通过。
- 任务种子 JSON：15 项有效且稳定标识不重复。
- **上游应用测试、真正 GitHub Actions、真实 PR HEAD CI：尚未运行，不能标记通过。**

## 远端已知阻断

制作时 `Aspeternity/SeekPulse` 尚不存在；当前连接的 GitHub 工具不提供创建仓库或 Fork 操作，远程电脑也未在线。不能在此情况下声称已创建 Issue、PR、CI 或配置 main 分支保护。

## 下一步（G0 内）

1. 在 GitHub 真实 Fork 上游并命名 `Aspeternity/SeekPulse`，确认保留上游提交历史。
2. 创建 G0 分支，按 `docs/OPERATIONS.md` 导入工程文件。
3. 创建真实 GitHub Issues，开 Draft PR，不合并 main。
4. 开启并核验 G0 CI 对应最新 PR HEAD SHA、远端访问控制以及交接报告。
5. 请求用户 G0 实机/流程验收；**未获得明确下一阶段授权，不执行 S0。**

**G0 不包含业务功能修改，`app/`、`Dockerfile`、上游依赖和 Compose 不在本工程包内。**
