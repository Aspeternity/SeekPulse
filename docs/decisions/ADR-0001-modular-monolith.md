# ADR-0001：采用模块化单体，不采用微服务或动态插件框架

- 状态：已在 SeekPulse V1.1 方案中批准；**实施仍受阶段审批限制**
- 日期：2026-10-13

## 背景

双来源、三通知渠道、Web/Bot 共享规则，需要清晰的职责分隔；项目目标运行在低配单机 VPS。

## 决定

Python asyncio 单进程，内部抽象 Source、Normalizer、RuleEngine、Router、Notifier。SQLite WAL 作为单机唯一业务存储。TG 和 RSS 保持各自采集方式，通过标准化事件衔接；TG 原生 SDK，Bark/ntfy 使用受限 Apprise。

## 反对方案

每来源单服务 + Redis 消息中间件、PostgreSQL、多 Worker Web、用户上传 Python 插件；对当前规模过度设计并增加重复采集与安全风险。

## 结果和验收

模块接口通过测试；来源故障不影响其他来源；无动态执行未审核第三方代码；在 S0/S6 实测资源开销。
