# S0-02 — Telegram MTProto / RSS 首次发现同机对照实验

**S0 只读研究；Issue #6；24h+ 实际数据未验证。** 依赖 S0-01 Telethon 1.45.0 已完成的真人账号接入；不更改正式 app/ 或现有 Compose。

## 核心统计口径

- 对同一 NodeSeek post_id，同一机器首次观察的时间差定义为 RSS 首见 UTC 减去 TG 首见 UTC：正数表示本机先发现 TG，负数表示本机先发现 RSS。这既不是论坛原帖发布时间差，也不是通知到手机时间。
- RSS 首见时间取 GET 完成、XML 解析后首次写库的时间，包含轮询等待与网络开销；不能根据 60 秒设置就断言 TG 更快。
- **仅 tg_live + rss_poll 的正常配对样本参与时间差统计**。tg_history、tg_catchup、rss_resume 及第一次 rss_baseline 都不能作为实时速度样本。
- 首次 RSS feed 视为旧帖基线；Telegram 首次启动只建立最新频道消息 ID 游标。开头/结尾均有删失；来源独占帖不等于实际永久漏报。
- RSS 默认每 60 秒轮询，允许 60 至 600 秒。超时/429/解析失败保存失败类别并指数退避到 600 秒；前后 RSS 快照没有交集则记录 RSS_WINDOW_NO_OVERLAP，不推断完整覆盖。
- TG 仍用 Telethon 的新消息事件及按频道消息 ID 的历史补查；停机补回的消息不参与实时速度统计。

## 数据与保密边界

- 默认复用受控测试设备的 S0-01 Telegram Session（~/.local/share/seekpulse-s0/s0_user.session）及**相同 probe.lock 互斥锁**。S0-01 和 S0-02 不得同时监听。
- S0-02 另存 SQLite 到 ~/.local/share/seekpulse-s0/s0_02_comparison.sqlite3，不改动 S0-01 observations.sqlite3。
- 只保存公开频道消息 ID、帖子 ID、源首次观察时间及错误分类；不保存正文、标题或账号信息。不得把 Session、API Hash、手机号、验证码、两步验证密码及私有 SQLite 上传聊天或 GitHub。
- 只读官方频道和固定公开 RSS，不发送 TG/Bot 消息、不访问需登录的论坛页面，不运行生产容器。

## Windows 本机 5 分钟联调

此前用户克隆了单一 S0-01 分支，因此先显式抓取 S0-02 分支。在 C:\Users\Asp\SeekPulse-S0 打开 PowerShell：

    git status --short
    git fetch origin "refs/heads/research/s0-02-tg-rss-observation:refs/remotes/origin/research/s0-02-tg-rss-observation"
    git switch --track origin/research/s0-02-tg-rss-observation
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_s0_dual_source_probe.py -v

工作区应先无未提交更改。S0-02 分支继承旧 S0-01 研究代码；之前完成 auth 的本机 Session 可继续使用，无需重新授权。运行：

    .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py listen --minutes 5 --rss-interval 60

在本机输入 API ID 和隐藏的 API Hash。结束后可不输入凭证直接生成脱敏摘要：

    .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py report

预期输出 BASELINE、TG_STARTUP_CHECK、TG_LIVE、RSS、TG_CHECK 和 S0_02_REPORT（具体出现 TG_LIVE 的数量取决于实际发帖）。五分钟仅是烟雾测试，不能据此推荐最终轮询间隔。

## 24h+ 非生产试验和退出门槛

Windows 短测通过后，**优先在独立测试 VPS 中使用隔离的 Docker 容器**连续运行至少 24 小时，不让 Windows 睡眠/经常切换网络破坏连续性。不在已经承载生产 1Panel/正式机器人业务的容器里运行，不修改正式 compose。跨机器测试账号需在目标机上单独完成安全登录；不可把 Windows Session 上传或发送到聊天。

同一研究脚本支持：

    python scripts/s0_dual_source_probe.py listen --hours 24 --rss-interval 60
    python scripts/s0_dual_source_probe.py report

验收须同时核查同一 HEAD 的 CI、首次源观察时间、TG 历史恢复分类、RSS 错误与 feed 窗口、有效配对样本数、P50/P95、两源覆盖差异及样本的左右删失。报告 continuous_24h_observed=true 只表示一次 24h 进程自然完成，不证明网络一路正常。

S0-02 完成后进入 S0-04 Go/No-Go 汇总，仍需用户验收。PR 仅保留 Draft 状态，**不合并 main、不发布、不实施 S1**。
