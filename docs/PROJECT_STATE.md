# SeekPulse — S6 / Issue #15 当前交接索引

> 2026-10-14 快照。审批/PR/HEAD/CI 以实时 GitHub 和用户原话为准，本文件仅供新对话接续。

- S1–S5 已分别用户阶段验收、独立获批合并：PR #21–#26。当前开发基线 main `9fe66d9db8330ac84ae14718eb413634560420d1`，合并后 G0 push [#38558377125](https://github.com/Aspeternity/SeekPulse/actions/runs/38558377125) 4/4 PASS；Issue #14 已关闭。
- 最新用户针对“是否批准启动 S6 / Issue #15 开发？”明确回复「批准」，**只授权 S6 的开发与离线模拟 CI**。当前 Issue #15、负责人 ChatGPT、分支 `feat/s6-01-recovery-backup`、独立 Draft PR。S6 用户阶段验收及合并均需新的独立批准。
- S6 主要新增 `app/maintenance.py` 离线维护 CLI：SQLite WAL 在线备份 API、私有快照目录、SHA-256/完整性/FK/已知 schema 版本验证、只恢复到新 DB 路径、敏感信息不输出；故障注入测试覆盖 ENOSPC/SQLITE_BUSY/长断网/Session 失效/429/旧租约失效。ADR-0006 限制禁止覆盖现役 DB、修改生产配置与真实迁移。
- S1–S5 原主运行代码、`app/main.py`、旧 FeedPoller、Compose、Dockerfile、已锁定 requirements.txt 不修改。S4 非 TG 新目标正式注册和旧历史迁移仍未授权。
- S0 研究 PR #17–#20 依旧 Draft、未合并。S6 未进行真实 VPS 演练；S7、Tag/Release、生产部署及真正消息通知均未授权。
- 下一步：最新 HEAD 的 G0/S1/S6 全量 Python 3.11/3.12 CI；记录失败/修复并重新跑，再向用户**申请 S6-01 离线阶段验收**；通过后再单独申请合并。不得自行合并 main。
