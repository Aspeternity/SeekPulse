# S0-03 — Apprise / Bark / ntfy 隔离可行性验证

**状态：试验中，尚未验收真实手机推送。**
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

## 尚待验证
- 真实 Bark/ntfy 到达手机的时间与可靠性，必须使用受控设备，不能以 HTTP 200 假设 APNs 或 Android 通知到达。
- 自建 ntfy iOS 即时通知需正确的 upstream-base-url。参考：https://docs.ntfy.sh/config/#ios-instant-notifications
- 在 1 vCPU/1 GiB 的隔离 VPS 上测试完整依赖与资源占用；GitHub Runner 结果不能直接代表低配机器。
- 不同服务限速、自动重试与持久化任务重试的职责边界；SSR F/回环/私有地址不可作为最终用户任意配置。

## 授权边界
本次仅执行 S0 技术研究；不修改既有 app/ 业务代码、不合并 main、不发布、不发送真实推送、不修改生产环境。
