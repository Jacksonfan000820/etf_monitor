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
# 服务器 cron 时区应为 Asia/Shanghai；数据分批更新，不保证10点已齐全
0 10 * * * cd /path/to/etf_monitor && python3 etf_db.py
```

## 📊 报告预览

![报告示例](screenshots/report.png)

报告包含：
- BTC/ETH 实时价格 + 恐慌贪婪指数
- BTC ETF 每日净流入柱状图
- BTC ETF 累计资金流趋势线
- 各 ETF 累计统计表
- 最近 7 个已存储交易日明细表及最近 5 个已收盘美国交易日统计

## 🗄️ 数据库结构

### btc_flows
| 字段 | 类型 | 说明 |
|------|------|------|
| date | TEXT | 交易日期 (YYYY-MM-DD) |
| IBIT, FBTC, GBTC, ARKB, BITB, HODL, BRRR, BTCW, EZBC, BTCO, BTC, DEFI, MSBT | REAL | 各 ETF 净流（百万美元） |
| total | REAL | 当日总计 |
| fetched_at | TEXT | 抓取时间戳 |

### eth_flows
| 字段 | 类型 |
|------|------|
| ETHA, ETHB, FETH, ETHW, TETH, ETHV, QETH, EZET, ETHE, ETH, MSSE | REAL |

### prices
| 字段 | 类型 |
|------|------|
| btc_price, eth_price | REAL |
| fear_greed | INTEGER |

## 📡 数据来源

- [Farside Investors](https://farside.co.uk/) — ETF 资金流数据（使用 curl_cffi HTTP 客户端）
- [CoinGecko](https://www.coingecko.com/) — BTC/ETH 实时价格
- [Alternative.me](https://alternative.me/) — 恐慌贪婪指数

## ⚠️ 注意事项

- Farside 数据分批发布，查询时间不代表所有基金已经报齐；请检查报告中的美国交易日及缺报日期。
- CoinGecko 公开 API 偶发超时，脚本内置 3 次重试
- 数据库文件 `etf_flows.db` 不会被 Git 追踪（已加入 .gitignore）

## 📄 License

MIT © Jackson Fan


## 数据质量与测试

- 空白、破折号、缺列保存为 SQL NULL；数字 0 是真实零值。缺失基金时总额视为待更新。
- 按源表的 ticker 表头映射，不按固定位置猜测。无法识别表头、新增未知 ticker、错误行宽、冲突日期、非有限数字及明显不一致的总额会拒绝本次抓取。
- HTTP 失败直接中止资金流更新，不生成伪成功报告；价格失败或陈旧显示待更新。
- NYSE 日历考虑周末、节假日、提前收盘和夏令时。最近五交易日是查询时已收盘的五个美国交易日，不是最近五条有值记录；任何一天缺报都不计算净额。刚收盘尚未发布与历史陈旧统一标记 pending_or_stale 并列出缺报日期。
- 查询时间显示北京时间（含 UTC 偏移），源日期为美国交易日。抓取时间使用 UTC。
- 旧版历史中的假零和错列无法凭数据库恢复。更新不会删除旧库；源页面覆盖的日期会重抓覆盖，更早历史必须与源核对。累计图表只加总已知值，不能当作完整全历史。
- 保留 HTML/SVG、SQLite、价格/情绪指标及可选 Playwright 截图。截图失败不会丢失 HTML。

```bash
python -m unittest -v
python -m py_compile etf_db.py flow_quality.py
```

测试采用本地 HTML 和模拟 HTTP，不依赖实时网站，也不会触发截图或写入正式数据库。

真实表结构回归样本采集于北京时间 2026-11-07（UTC 2026-11-06），来源 Farside BTC/ETH 页面；包含分行表头、新增 MSBT/MSSE。DEFI 为旧库兼容字段，源表不提供时不视为必填。已有数据库采用添加列迁移，不删表或删记录。历史上市前的破折号保守视为缺失，因此这些日期可能不计算总额。
