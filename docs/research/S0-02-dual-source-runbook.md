# S0-02 — Telegram MTProto / RSS 首次发现同机对照实验

**S0 只读研究；Issue #6。2026-10-14 经用户同意：以有效样本为核心，取消 24h 强制门槛。** 依赖 S0-01 Telethon 1.45.0 已完成的真人账号接入；不更改正式 app/ 或现有 Compose。

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

## 2026-10-14 后续授权：Windows 10 秒连续 3 小时补样

用户在已有 15 分钟 10 秒轮询实测（有效配对 n=1）后，明确要求“RSS 10 秒轮询再测一次，直接在电脑上测 3 个小时”。本批仅将已有研究脚本的 **10 秒显式确认模式的单次最长观察时间从 90 分钟放宽到 180 分钟**，不修改默认 RSS 间隔、不触碰原产品配置，不增加新来源或账号；用户无需每 90 分钟重启。

- Windows PowerShell：先确认未并行运行 S0-01/S0-02 和本机电源不会休眠；git 更新至本次 HEAD，再检查本地单测。启动命令：

      .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py listen --hours 3 --rss-interval 10 --ack-10s-rss

- 仍然只访问固定公共 RSS URL，Telegram 使用原授权账户的本机私有 Session，RSS **HTTP 403/429 自动停止**、其他短时网络故障指数退避至最多 600 秒；如 403/429 出现，应停止并记录，不另用脚本绕过。
- 3 小时为**观察上限/用户选择**，不是本轮必须等待才能开展其他研究的门槛；实际 10 秒轮询包含请求耗时及重试退避，不保证精确每 10 秒获取一次成功数据。无网络错误的理想上界约每分钟 6 次，3 小时约 1080 次请求（实际可能更少），使用前需确保服务使用条件允许。
- 默认复用 `s0_02_comparison.sqlite3`，会保留之前 60 秒 65 分钟及 10 秒 15 分钟的结果。报告 10 秒组累计总数据；需要区分**3 小时本轮和历史 15 分钟**，应保留完整本轮终端日志，不上传任何账号凭据、Session 或 SQLite 数据库。
- 不修改 main、app/、正式 CI 依赖、生产环境，PR #19 仍 Draft；最终源时效/覆盖结论等待本轮真实采样，样本量不足也不得推断胜负。

## 修订方案：约 2–3 小时分段观察，不强制 24 小时

2026-10-14 用户明确同意：缩短 S0-02 的必要测试时长，保留后续独立稳定性测试，不阻塞 S0-03 等可并行工作。**时间只是建议，不是机械验收闸门**。

- A 组：RSS 每 60 秒轮询，与 TG 实时事件同机对照，建议 45–75 分钟。研究工具默认此间隔，之前 5 分钟实测仅贡献 3 个有效配对样本。
- B 组：与原项目 .env.example 中的 10 秒 RSS 默认轮询保持可比较性，建议 45–75 分钟。在本轮研究中，10 秒间隔需要显式 --ack-10s-rss，且常规研究单次建议不超过 90 分钟；经用户 2026-10-14 明确要求，受控观察可最长运行 180 分钟；**先确认当前网络和 RSS 服务条件允许，再执行。**
- 两组均使用同一受控测试主机/Session/本地时钟，各自独立记录有效配对样本。每组建议先取得不少于 30 个 tg_live + rss_poll 有效配对样本，合计期望 100 个左右。**这仅是方向性研究的样本目标，不是统计学充分性保证，也不是一个达不到就必须继续等的开发阻塞条件。**
- 60s 与 10s 按顺序运行，可能受不同发帖时段和 RSS 缓存策略干扰；不能把两组 P50/P95 的差直接当作纯轮询因果收益。长时间断线、服务器缓存、HTTP 错误、RSS feed 滚动以及临近起止边界帖均需单独审阅。
- 只有 TG 回调真实首次记录且 RSS 普通成功轮询首次记录、**两者属于同一轮运行**的帖子，才进入对应轮询间隔的速度统计。TG 补查、RSS 恢复和初始基线不进入正常时差比较。分别检查 report 中 comparison_by_rss_interval_seconds，不混算旧轮次。
- 如果 RSS 返回 HTTP 403/429：工具记录 RSS_ACCESS_DENIED_STOP 或 RSS_RATE_LIMIT_STOP 后**停止本次观察**，不要重试高频轮询。其他临时网络错误会指数退避到最多 600s。无法确认服务端允许 10s 时，**不要强行执行该组**，据已有数据写清限制即可。
- S0-02 的退出可分“观测结论可用于架构权衡”“证据不足，暂不推荐某方案”。2–3 小时后先整理可用证据；不足的项目列为未验证，**不要求等待 24h，也不将 S0-02 测试时长自动变成 S1 授权**。长期 24–72h 稳定性留到后续独立的 S6/S7 阶段按授权开展。

### 运行命令（Windows PowerShell）

先确认旧的 S0-01 与 S0-02 监听程序均已结束，工作区干净，然后：

    cd "$HOME\SeekPulse-S0"
    git status --short
    git pull --ff-only
    .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_s0_dual_source_probe.py -v

A 组（先执行；可按实时样本调整观察时长）：

    .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py listen --minutes 60 --rss-interval 60

A 组结束、确认 RSS 不存在 403/429 且服务端允许高频测试后，才可开启 B 组：

    .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py listen --minutes 60 --rss-interval 10 --ack-10s-rss

得到不包含凭据的累计统计：

    .\.venv\Scripts\python.exe .\scripts\s0_dual_source_probe.py report

两轮均复用已有的 S0-02 独立 SQLite、S0-01 私有 Session 和进程互斥锁。report 中 study_sample_guidance 仅提供**样本量建议**，不是自动 Go/No-Go。若 Windows 将休眠、网络经常切换，可以安排独立非生产测试 VPS，但**本轮不需要等 VPS Docker 运行 24h 才继续研究**。

### 验收与后续决策

明确列出每种轮询间隔的实际运行分钟数、正常配对 n、P50/P95、TG 补查占比、RSS 成功/失败与 HTTP 状态、feed 窗口缺口、TG/RSS 未匹配帖及左右删失风险。P95 在小样本下不稳定，要标注不确定性。S0-02 可以在形成有边界的结论后申请用户验收；S0-04 汇总时再决定 Telethon 是否值得保留。PR 继续 Draft，不修改 main、生产配置，不启动未经批准的 S1。
