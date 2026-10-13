# S0-03 — Apprise / Bark / ntfy 隔离可行性验证

**状态：第二批隔离故障语义与资源评估进行中；真实手机推送仍 UNVERIFIED。**
关联 Issue：https://github.com/Aspeternity/SeekPulse/issues/7

## 技术判断与资料
- Apprise 文档 https://appriseit.com/library/results/：当前 async_notify() 返回结果对象，检查 bool(result) 与逐服务结果，不使用 result is True。
- Bark https://appriseit.com/services/bark/ 支持 bark://；ntfy https://appriseit.com/services/ntfy/ 支持 ntfy://。
- 当前试验固定 apprise==2.0.1（PyPI 2026-10-03）。正式加入项目依赖必须后续单独审查兼容性、安全、版本固定和资源开销。

## 实验隔离
- GitHub Actions 安装测试版，临时绑定 127.0.0.1 模拟 Bark 与 ntfy 的 HTTP 接收端。
- 每个服务尝试异步发送一次，验证 Apprise 服务配置、返回对象与逐目标成功状态。
- 针对 ntfy 模拟一次 HTTP 403 永久拒绝，验证返回失败。未验证 429/5xx、超时、重试策略。
- 所有目标是临时本机假地址；没有真实设备 Key、API Token、Telegram 账号或生产环境访问。
- JSON 工件不保留消息正文或敏感密钥。

## 第二批：故障语义与有限资源试验（2026-10-14）

- **沿用 Draft PR #18 的已有研究脚本**，仅增加隔离 127.0.0.1 HTTP 服务的场景，完全没有真实 Bark/ntfy 设备密钥或 Bot Token。
- 固定 Apprise 2.0.1，每种服务使用 1 个伪设备/主题，依次模拟 HTTP **200、403、429、503** 和服务器响应过慢。请求目标只能由脚本构造为本机回环地址；实验脚本没有可传入任意 URL 的选项。
- 显式加 ?retry=0，避免把 Apprise 自带重试与未来 SeekPulse 持久化任务重试混淆。**响应失败只验证库是否正确报告失败**；正式阶段需要按目标区分永久失败（如 403）、可能重试（429、5xx、超时），定义有界退避与死信处理，**不是现在自动加入正式业务重试代码**。
- 超时配置：AppriseAsset(service_timeout=2)、连接/读取预算 cto=1&rto=1，以及研究脚本外层 asyncio.wait_for(..., timeout=4)。如果外层预算先超时，明确记录 LOCAL_DEADLINE_TIMEOUT 而不是假装有 API 成功结果。
- 结果既检查整体 bool(result)，又保留 AppriseResult 每服务状态、请求次数和诊断类别；只输出脱敏汇总，不输出 HTTP path、正文、伪设备标识或 URL。
- 额外在 GitHub Actions **Ubuntu Docker 受限容器**中运行一遍固定依赖与循环测试，用 --cpus=1 --memory=1g --memory-swap=1g 施加资源上限；报告 Linux 进程峰值 RSS 与 cgroup memory.peak / memory.max / cpu.max，**仅代表受约束的 CI 容器短时估计，不代表用户真实 VPS、生产资源或持续 24 小时稳定性**。
- 这个实验不会验证 iOS/APNs 到达，亦不实现生产任意 URL 配置的安全审查。未来正式 Bark/ntfy 目标仍必须采取允许的 provider/scheme、受控域名/终点、禁止意外向 localhost/内网探测、限制重定向等措施；仅一个回环模拟器不构成 SSRF 防护证明。

## 本批预期验收

1. HEAD 相关基础 CI 与 Apprise 实验 CI 均通过；本机 6 项结果归类测试全部 PASS。
2. 原始 JSON 工件逐一证明 Bark 与 ntfy 成功/403/429/503/慢响应被准确分类，不发生自动重发（预期每个案例只有一次本地 HTTP POST）；如真实库输出与预期不同，**以失败和实测日志为准**，不能改写为模拟“通过”。
3. Docker 受限容器核实 CPU/内存配额已经生效，并记录峰值供资源预评估，**不声称真实 1vCPU/1GiB VPS 实机验收**。
4. 仍然不触碰 app/、Dockerfile、requirements.txt、正式 compose、main；PR 保持 Draft，待用户明确批准后才可合并。

## 尚待验证
- 真实 Bark/ntfy 到达手机的时间与可靠性，必须使用受控设备，不能以 HTTP 200 假设 APNs 或 Android 通知到达。
- 自建 ntfy iOS 即时通知需正确的 upstream-base-url。参考：https://docs.ntfy.sh/config/#ios-instant-notifications
- 在 1 vCPU/1 GiB 的隔离 VPS 上测试完整依赖与资源占用；GitHub Runner 结果不能直接代表低配机器。
- 不同服务限速、自动重试与持久化任务重试的职责边界；SSR F/回环/私有地址不可作为最终用户任意配置。

## 授权边界
本次仅执行 S0 技术研究；不修改既有 app/ 业务代码、不合并 main、不发布、不发送真实推送、不修改生产环境。
