# ETF Monitor — BTC/ETH ETF 资金流向监控

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)

每日自动抓取 BTC/ETH 现货 ETF 资金流向数据，存入 SQLite 数据库，生成带趋势图表的 HTML 报告。

## ✨ 功能

- 📡 从 [Farside Investors](https://farside.co.uk/) 抓取 BTC/ETH ETF 每日资金流
- 💰 获取 BTC/ETH 实时价格（CoinGecko）和恐慌贪婪指数（Alternative.me）
- 🗄️ SQLite 本地持久化存储，自动去重
- 📊 生成带 SVG 图表的 HTML 报告（每日柱状图 + 累计趋势线 + 各ETF明细）
- 📸 Playwright 自动截图（可选）

## 📦 安装

```bash
git clone https://github.com/Jacksonfan000820/etf_monitor.git
cd etf_monitor
pip install -r requirements.txt
playwright install chromium
```

## 🚀 使用

```bash
python3 etf_db.py
```

输出：
- `etf_flows.db` — SQLite 数据库（自动创建）
- `/tmp/etf_db_YYYYMMDD_HHMM.html` — HTML 报告
- `/tmp/etf_db_YYYYMMDD_HHMM.png` — 截图（可选）

### 定时运行（crontab）

```bash
# 每天上午 10:00 运行（Farside 数据通常在美股收盘后 1-2 小时更新完）
0 10 * * * cd /path/to/etf_monitor && python3 etf_db.py
```

## 📊 报告预览

![报告示例](screenshots/report.png)

报告包含：
- BTC/ETH 实时价格 + 恐慌贪婪指数
- BTC ETF 每日净流入柱状图
- BTC ETF 累计资金流趋势线
- 各 ETF 累计统计表
- 最近 7 天明细表

## 🗄️ 数据库结构

### btc_flows
| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 交易日期 (YYYY-MM-DD) |
| IBIT, FBTC, GBTC, ARKB, BITB, HODL, BRRR, BTCW, EZBC, BTCO, BTC, DEFI | REAL | 各 ETF 净流（百万美元） |
| total | REAL | 当日总计 |
| fetched_at | TEXT | 抓取时间戳 |

### eth_flows
| 字段 | 类型 |
|------|------|
| ETHA, ETHB, FETH, ETHW, TETH, ETHV, QETH, EZET, ETHE, ETH | REAL |

### prices
| 字段 | 类型 |
|------|------|
| btc_price, eth_price | REAL |
| fear_greed | INTEGER |

## 📡 数据来源

- [Farside Investors](https://farside.co.uk/) — ETF 资金流数据（通过 curl_cffi 绕过 Cloudflare）
- [CoinGecko](https://www.coingecko.com/) — BTC/ETH 实时价格
- [Alternative.me](https://alternative.me/) — 恐慌贪婪指数

## ⚠️ 注意事项

- Farside 数据可能有 **1-3 小时的延迟**（T+1 日分批更新），建议上午 9:30 以后运行
- CoinGecko 公开 API 偶发超时，脚本内置 3 次重试
- 数据库文件 `etf_flows.db` 不会被 Git 追踪（已加入 .gitignore）

## 📄 License

MIT © Jackson Fan
