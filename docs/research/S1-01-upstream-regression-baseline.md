# S1-01：原版回归基线与依赖兼容

关联 [Issue #9](https://github.com/Aspeternity/SeekPulse/issues/9)。用户于 2026-10-14 同意 S0-04 条件式 Go 并单独授权 S1；本批不执行 S2–S7、不改原版业务语义。

## 覆盖范围

测试运行未经修改的 AI-XMLY app 模块。全部网络交互使用伪造的异步 RSS 响应及 Bot AsyncMock，全部数据库均为测试内临时 SQLite。没有真实 TG 账号、凭据、Session、HTTP 请求或通知。

| 分组 | 测试对象 | 已有上游行为 |
|---|---|---|
| RSS 与文本 | app.rss、app.bot、app.categories、app.utils | RSS/Atom 解析、分类别名、未知类别、HTML 与长度处理；普通独立关键词 OR、组合规则 AND、大小写不敏感、输入去重 |
| SQLite / 用户 | app.db | 每用户关键词、屏蔽词和目标隔离；跨用户改动拒绝；启停；按用户+帖子已有唯一历史；数据库重复初始化/重启 |
| RSS 到 Telegram | app.poller + app.db | 首次旧帖标记 read 不补推；屏蔽优先；分类限制；独立用户和多目标；同帖去重；暂停用户；Forbidden 禁用目标；全部目标失败可下一轮再试 |
| 依赖 | requirements.txt、importlib.metadata | 当前五个上游发行包精确 pin 和安装版本契约，不在本阶段擅自升级 |
| CI | 原 G0 CI + 专项 S1 workflow | 原 Python 3.11/3.12 全套检查继续；新增 Python 3.12 专项离线回归，为 S1 提供明确质量信号 |

## 已发现的上游遗留风险

原版轮询在一个目标成功但另一个目标失败时，使用整个用户+帖子的发送状态。结果是失败目标后续不会独立重试。S1 的对应测试仅记录这个现有事实，绝不将其认定为 V1.1 正确设计。待获 S2/S4 授权后，必须使用独立于用户和帖子 ID 的目标级持久化任务与重试，替换这一现状特征测试。

尚未具备：TG/RSS 双源真正一体化、字段不全时等待补全、任务租约、Bark/ntfy 正式通知、Web 权限及真机资源。S1 测试不把这些未实现能力伪称通过。

## 运行命令（独立 checkout）

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests -p 'test_s1_*.py' -v
    python -m unittest discover -s tests -v
    python -m compileall -q app scripts tests

无需 .env、手机号、Bot Token、Telegram Session。只在测试自己的临时数据库工作。

## 交付门槛

- 所有 S1 测试在专用 CI 通过；原 G0 CI 的 Python 3.11/3.12、治理和 Docker 检查在最新 S1 PR HEAD 全绿。
- 没有改 app、Dockerfile、requirements.txt、正式 Compose 或生产；保留 S0 研究 PR Draft、main 不变。
- CI 失败要找到测试与原版行为不符之处，不能减弱断言追求绿灯，更不能在 S1 偷改原版业务行为。
- 写明实际覆盖、当前多目标独立重试缺口及其他未验收项。用户需单独 S1 验收；合并、S2 和发布仍需另批。
