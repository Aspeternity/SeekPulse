# 上游来源与许可

- 上游：<https://github.com/AI-XMLY/nodeseek-rss-telegram-bot>
- 推荐冻结基准提交：`8107b18e99148127bc6c993ac8384959ac871f6d`
- 核查日期：2026-10-13
- 上游 License：MIT。Fork 过程中保留原历史与原 `LICENSE` 文件。
- 该提交为本次核查到的上游最新提交，不代表未来永不变化。

## G0 约束

G0 仅增加工程治理、Issue/PR/CI、验证脚手架，不修改原版 `app/` 或部署配置，也不升级任何运行依赖。

## 代码复用边界

- `Hootrix/keyword_alert_bot` 许可证为 GPLv3：只学习架构思想，**不得直接拷贝受 GPLv3 约束的实现到计划保留 MIT 的核心代码中**。
- `caronc/apprise` 采用 BSD-2-Clause，未来作为依赖时应保留对应许可证声明与版本锁定。
- 新增第三方依赖、许可证和安全评估属于未来开发阶段，G0 不提前引入生产依赖。

## Fork 和基准验证

在 GitHub 完成 Fork 并命名 `Aspeternity/SeekPulse` 后，验证仓库存在上游原始提交与历史；切出 `chore/g0-engineering-foundation` 独立分支，再添加本包文件并提交 Draft PR。禁止直接把 G0 文件写入 `main`。
