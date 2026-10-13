# S0-01 — 专用测试账号 MTProto 只读验证

状态：**离线模拟验证完成；真人账号 MTProto 尚未执行，因此不能判 PASS。**

## 安全边界

- 仅在用户控制的非生产测试设备上运行；使用单独的 Telegram 测试账号，并通过 Telegram 客户端手动加入 @nodeseekc。
- 工具只读取官方频道消息 ID 和 NodeSeek 原帖 ID，不发消息、不入群、不发送 Bot 通知。
- API ID、API Hash、手机号、登录码、2FA 密码及 Session 均不得进入聊天、PR、Issues、CI 或普通日志。
- 会话及观察 SQLite 默认在用户目录 ~/.local/share/seekpulse-s0/，不在 Git 工作树中；视 Session 为高敏感凭证。
- 不要同时运行多份探针；锁文件异常残留时先核实原进程已经结束再清理。

## 环境准备

从 GitHub 检出 research/s0-01-telegram-source-probe 分支；依赖仅在测试环境手工安装，不改主应用依赖。推荐 Python 3.12。

Linux：
- `python3 -m venv .venv`
- `.venv/bin/python -m pip install Telethon==1.45.0`
- `.venv/bin/python -m unittest discover -s tests -p 'test_s0_mtproto_probe.py' -v`

Windows PowerShell：
- `py -3.12 -m venv .venv`
- `.\.venv\Scripts\python.exe -m pip install Telethon==1.45.0`
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_s0_mtproto_probe.py -v`

## 验证步骤（以下使用 Linux Python 路径）

1. 在 my.telegram.org 申请该测试账号的 API ID / API Hash。运行 `.venv/bin/python scripts/s0_mtproto_probe.py auth`，凭证、验证码仅在本机交互式输入。
2. 执行 `.venv/bin/python scripts/s0_mtproto_probe.py listen --minutes 15`。初次只建立最新消息基线，不计入历史旧帖。确认期间 Telegram 客户端确实有新帖子。
3. 停止探针，等官方频道再次发布至少一个新帖子，再用**同一会话与状态目录**运行第 2 步。回查应记录遗漏的 ID；如果离线期间没有新帖，不能判定恢复成功。
4. 运行 `.venv/bin/python scripts/s0_mtproto_probe.py report`，只分享这个 JSON 统计报告，不要分享 observations.sqlite3、s0_user.session、环境变量、终端认证记录。

## 正确认定证据

- event_callback：收到普通 NewMessage 回调；catchup_callback：启动补查期间的回调，不将后者称为实时。
- history：通过按消息 ID 查询补充发现；同一 message_id 仅记录首次发现。
- 出现 BACKFILL_LIMIT_EXCEEDED：当前窗口不够，已保护游标不前进；必须记录为未通过并调查。
- 仅看 Telegram 消息日期不能推算 NodeSeek 论坛原帖发布时间。
- S0-02 / Issue #6 才负责 24 小时以上同机 TG+RSS 时间对照；本工具不能据此宣布 TG 更快。
- 编辑/删除事件尚未做实机验证，不能记为 PASS。

## 清理

确认测试进程退出后，可由用户自行删除 ~/.local/share/seekpulse-s0/，并在 Telegram 客户端撤销对应测试会话。禁止将这个目录导出到仓库或聊天。
