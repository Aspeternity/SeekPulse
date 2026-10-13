# G0 工程建档与 GitHub 配置操作规程

> 当前仅 G0 获授权，以下带写入操作的步骤仅应在目标 Fork 验证归属和权限后执行；操作不会合并 main、发布或修改生产服务器。

## 1. 建立保留历史的真实 Fork

1. 打开 <https://github.com/AI-XMLY/nodeseek-rss-telegram-bot>，选择 **Fork**，所有者选择 `Aspeternity`。
2. 尽可能将新仓库直接命名为 `SeekPulse`；如果 GitHub 页面不允许在 Fork 时改名，可先创建同名 Fork 后通过仓库 Settings 重命名为 `SeekPulse`。
3. 确认目标地址为 `https://github.com/Aspeternity/SeekPulse`，且其提交历史包含上游基准 `8107b18e99148127bc6c993ac8384959ac871f6d`。
4. 若目标仓库已存在，应先检查历史与现有分支，禁止覆盖或重新创建。

## 2. 只在独立 G0 分支引入文件

在已检出的 Fork 工作树中：

```bash
git fetch origin
git switch main
git switch -c chore/g0-engineering-foundation
```

将本 G0 overlay 压缩包**解压为临时目录**，把压缩包内的 `.github/`、`docs/`、`scripts/`、`tests/`、`AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 复制进工作树，不覆盖上游 `app/` 和运行配置。检查：

```bash
git status --short
git diff --check
git add AGENTS.md CLAUDE.md GEMINI.md .github docs scripts tests
git commit -m "chore(g0): establish AI governance, task templates and baseline CI"
git push -u origin chore/g0-engineering-foundation
```

之后在 GitHub 创建目标为 `main` 的 **Draft PR**，无需合并。PR 附带批准范围、SHA、CI、尚未完成的 G0 事项与验收条件。

## 3. 生成 GitHub Issues

在工作树中，先查看预期创建的任务（不写入）：

```bash
python scripts/bootstrap_issues.py --repo Aspeternity/SeekPulse --dry-run
```

在已经完成目标仓库与权限核查后，由获得 G0 授权的操作者使用有效的 GitHub Token 执行：

```bash
python scripts/bootstrap_issues.py --repo Aspeternity/SeekPulse --apply
```

脚本使用 Issue body 内的稳定 `seekpulse-task` 标识避免重复创建；**如果远端已有 issue 无法完整枚举，必须拒绝继续创建**。它不会合并、删除 Issue 或修改生产环境。

## 4. Actions 与保护

- Fork 仓库的 GitHub Actions 若默认被禁用，需在 GitHub 启用并运行 G0 PR 检查。
- **Issue Forms、CODEOWNERS 和工作流保护等默认分支相关配置可能要等 G0 PR 经用户进一步授权合并后才正式生效**；在 G0 审批期可先用种子工具创建真实 Issues，但不能声称 Issue Forms 已在默认分支启用。
- `main` 配置保护，要求 PR 和必要的 CI 状态检查；禁止强制推送、自动合并。注意 GitHub 方案/权限可能限制可用的规则设置，需人工核实。
- 不要在缺少绿色检查的情况下虚构通过结论，也不因 Actions 尚未启用而声称 G0 结束。
- 本 G0 不编辑 `main`，保护规则在仓库创建后配置并验证，不声称已远端生效。

## 5. G0 验收要求

- 真实 Fork 存在，保留上游 Git 历史和 MIT 许可。
- G0 文件位于**独立分支**，Draft PR 指向 `main`。
- 实际 GitHub Issues 创建成功，并有任务唯一编号。
- `CI` 运行与 PR 最新 HEAD SHA 对应，完整绿色。
- `python scripts/context_report.py --repo Aspeternity/SeekPulse` 能核对远端提交/Issues/PR/CI，不隐瞒未知状态。
- 用户审阅并明确反馈 G0 验收结果；未获进一步授权不进入 S0。
