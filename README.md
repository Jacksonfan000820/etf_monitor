# Market Intelligence

**以来源证据为基础的市场观察工具：BTC/ETH 现货 ETF 资金流、新闻摘录与本地日报。**

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://www.python.org/)

从 ETF Monitor 扩展而来，保留原有数据库、HTML/SVG 报告和命令入口。当前是可测试的工程项目，不是全市场金融数据服务，也不是投资建议或自动交易系统。

## 能做什么

| 模块 | 当前实现 | 边界 |
| --- | --- | --- |
| ETF Monitor | Farside BTC/ETH 资金流、SQLite、HTML 趋势图、价格及情绪指标、可选截图 | 数据延迟、缺报和源站改版都可能影响结果 |
| Market Digest | ETF 摘要、配置的 RSS/Atom 摘录、人工指定官方公告证据 | 不是全网新闻或交易所活动发现器 |
| X/KOL | 导入明确提供且有权使用的 JSON 导出 | 没有 X 自动监控、登录或 API 接入 |
| 输出 | 本地 JSON / 文本日报；可选飞书发送接口 | 默认不发送；真实投递与定时以部署验收为准 |

新闻标题和描述是来源摘录，不代表独立核实的事实。美股/美国金融方向目前以 Fed、SEC 等候选新闻源为起点，不覆盖所有个股。数据源失败必须显示 unavailable / stale / pending，不能用零或编造数据补齐。

## 30 秒离线预览

Python 3.11 或 3.12，无需安装第三方依赖：

```sh
python scripts/offline_demo.py
```

使用已纳入版本管理的历史 HTML 样本，输出标有 `historical_fixture_only` 的 JSON。**不联网、不写数据库、不发送消息，也不代表最新行情。** 可从任意工作目录运行。

## 安装与验证

先克隆本仓库并进入根目录，再执行：

```sh
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -r market-digest/requirements.txt
python scripts/check.py
```

统一检查入口运行根目录测试、digest 测试和 Python 编译检查；缺少日历等测试依赖时明确失败，避免把跳过日历测试误认为完整验证。各阶段失败后仍继续其他检查，最终返回非零退出码。测试使用 fixtures / mock，不发送真实消息。

Playwright 浏览器只在需要 ETF 截图时安装：

```sh
python -m playwright install chromium
```

## 运行 ETF Monitor

```sh
python etf_db.py
```

该命令会联网读取 Farside、CoinGecko 和 Alternative.me，并更新根目录的 `etf_flows.db`。HTML 写入 `/tmp/etf_db_YYYYMMDD_HHMM.html`，截图可用时写入同名 PNG。截图失败仍保留 HTML；根 CLI 的 `/tmp` 输出目前面向 Linux/macOS，Windows 请使用 WSL。

- 资金流单位：百万美元。空白、破折号和缺列是 SQL NULL，真实零值是 0。
- 根据 ticker 表头解析；未知列、错误行宽、冲突日期和不一致总额会拒绝更新。
- 五交易日窗口按 NYSE 已收盘交易日计算，考虑节假日、夏令时与提前收盘。缺任一天不计算窗口净额。
- 查询时间为北京时间，抓取时间为 UTC，源日期为美国交易日。
- SQLite 更新采用新增列兼容旧库，不删除原有记录。旧版本的假零/错列无法自动恢复，源页面之外的历史需另行核对。
- 累计图只加总已知值，不应视为完整全历史；价格失败或陈旧需按报告状态解读。

数据库包括 `btc_flows`、`eth_flows`、`prices`；ETF 表按日期去重，保留各 ticker、total 与 fetched_at。完整字段由 `etf_db.py` 中的 `BTC_COLS` / `ETH_COLS` 和迁移逻辑维护，避免文档表格滞后。

## 运行 Market Digest

```sh
cd market-digest
python digest.py
```

默认会联网采集已配置来源，只写 `out/report.json` 与 `out/report.txt`，不发送。**dry run 指不发送，不代表离线。**

```sh
python digest.py --sources sources.json --announcements announcements.json --output out
python digest.py --x-posts /your/private/path/x-posts.json
```

配置、导入格式和发送约束详见 [模块说明](market-digest/README.md)。凭据只通过环境变量或 GitHub Actions Secrets 提供，不放在代码、命令参数、日志或公共 issue 中。不要为测试调用真实发送接口。

## 项目结构

```text
etf_db.py                 ETF 数据库、价格、HTML 报告与截图入口
flow_quality.py           ETF 解析与交易日质量判断
fixtures/                 历史源表回归样本
market-digest/            独立日报模块、源配置、测试与路线图
scripts/check.py          两套测试与编译统一入口
scripts/offline_demo.py   不联网的历史样本预览
test_etf.py               ETF 回归测试
test_scripts.py           维护脚本与离线边界测试
docs/                    架构、运行维护、贡献与安全指南
.github/workflows/       以实际 YAML 为准的 GitHub Actions 配置
```

保持两个入口独立是为了保护原有 ETF 使用方式。两套解析实现尚未统一，不应在缺少兼容性回归时直接替换。

## 运行与维护

- [运行手册](docs/OPERATIONS.md)：运行前检查、数据状态、故障排查、备份和发布。
- [贡献指南](docs/CONTRIBUTING.md)：开发约定、测试、变更说明与提交流程。
- [安全说明](docs/SECURITY.md)：敏感数据、源站边界与漏洞报告。
- [架构说明](docs/ARCHITECTURE.md)：模块边界、数据流与剩余风险。
- [后续路线](market-digest/docs/ROADMAP.md) / [验证边界](market-digest/docs/VALIDATION.md)：区分已实现、未验证与待做事项。

离线检查通过不等于线上源可用、投递成功或定时任务已启用。不要仅凭 workflow 存在或任务显示绿色就宣称数据完整。发布应记录具体提交、测试结果、实时来源验证与实际部署状态。

## 数据来源与许可

ETF 来源 [Farside Investors](https://farside.co.uk/)，价格来源 [CoinGecko](https://www.coingecko.com/)，情绪来源 [Alternative.me](https://alternative.me/)。新闻和公告保留原文链接。使用者需遵守各来源的许可、频率和访问限制，不绕过登录、付费墙或反爬限制。

代码采用 [MIT License](LICENSE) © Jackson Fan。代码许可不授予第三方新闻、数据或商标的再分发权。项目不保证数据准确、及时或持续可用；任何金融决策应独立核实。
