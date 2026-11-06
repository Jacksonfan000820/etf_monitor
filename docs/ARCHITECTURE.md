# 架构与边界

## 两条独立路径

1. `etf_db.py` → Farside / 价格与情绪接口 → `flow_quality.py` 校验 → SQLite → HTML/SVG → 可选 Playwright 截图。
2. `market-digest/digest.py` → ETF、`sources.py` RSS/Atom、授权提供的 X JSON、配置的官方公告 → 标明状态的报告 → 本地 JSON / 文本 → 显式选择时才进入发送接口。

两套 ETF 解析和交易日历暂独立：根模块使用 pandas_market_calendars，digest 使用 exchange_calendars。统一前须证明真实源表、缺报、节假日、提前收盘和旧库回归均兼容。

## 工程辅助

- `scripts/offline_demo.py` 仅解析版本管理中的历史表，输出 stdout，不依赖网络/日历/数据库/机器人。
- `scripts/check.py` 检查关键测试依赖，在两个正确工作目录执行测试，并编译源文件。它不是部署或实时可用性检查器。
- fixtures 用于重现 schema，不能伪装为当前数据。测试中模拟的 HTTP 与发送不能作为实际投递证明。

## 尚未完成

全市场覆盖、X 自动监控、自动发现交易所活动、长期新闻快照、跨次运行去重、投递账本、补跑、生产告警与完整依赖 hash 锁均不应被默认视为可用。发送能力与 Actions 部署应分别检查实际代码和运行记录；详见运行手册及模块路线图。
