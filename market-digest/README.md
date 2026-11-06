# 币圈、美股与 ETF 综合情报模块

这是可运行的 Python 工程起点，不是已经上线的完整金融平台。本模块位于原 ETF 仓库的独立 `market-digest/` 目录。完整项目方向包括币圈、美股/美国金融、ETF、X/KOL、交易所活动、飞书推送和可靠运行。真实数据接入、合规授权、质量与部署仍须逐步验收。

**已添加用户授权的正式飞书日报工作流：每天北京时间 09:00（UTC 01:00）。GitHub Actions 可能延迟或漏跑，不保证准点；实际投递以运行记录中的 Feishu API code 0 及接收端为准。首次正式发送与定时验收记录见 Actions。**

## 实际交付范围

- **ETF**：Farside BTC/ETH 现货 ETF 资金流 HTML 解析；JSON 保留百万美元，文本换算为“净流入/净流出 × 亿美元”；近五交易日逐日明细；区分缺失和零；列合计核对；真实 XNYS 已收盘交易日；连续 5 交易日窗口；current/stale/unavailable 状态。非全市场 ETF 行情、持仓或 AUM 系统。
- **币圈/美国金融新闻**：新增可运行 RSS/Atom 适配器。优先配置华尔街见闻中文（按美国市场/宏观关键词筛选）、動區動趨繁体中文，保留 Fed、SEC、CoinDesk；独立故障隔离、单次运行 URL 去重、时间窗口过滤、明确未知发布时间、标题与描述原文摘录、源链接。Fed 为宏观政策、SEC 为监管新闻，不等于全面个股新闻覆盖。两路中文 RSS 已于 2026-11-06 实测通过（仅代表当次可用）；其余源保留独立失败提示。文本按中文优先、时间倒序，每组最多四条，只引用标题与链接，不生成未核实翻译。
- **X/KOL**：新增用户提供且有权使用的 JSON 导出导入器，校验作者与 URL 一致、帖子 ID 去重、时间窗口、原文及链接。**没有直接调用 X API、自动抓取、授权登录或智能观点总结**；导入内容真实性未独立验证。
- **交易所活动**：新增币安官方 CMS、OKX 官方活动列表自动发现（近七天、每所最多两条、仅列表首页）。Bitget 只列已验证的官方入口，自动发现未接通。仍支持人工配置公告 URL；所有内容仅为公告候选，截止日期、地区、KYC、投入门槛、奖励与用户资格未核实。白名单、HTTPS、禁止重定向。
- **飞书**：已有文本机器人发送函数，只在明确 `--send` 时调用；凭据仅来自环境变量；不自动重试不确定发送；消息超过 18,000 UTF-8 字节直接阻止发送，避免静默截断。**签名机器人和分片发送尚未实现**。
- **GitHub Actions**：`market-digest.yml` 在每日 UTC 01:00 生成并发送一份日报；手动触发默认 dry run，必须显式选择发送。禁止重跑尝试再次发送，发送不重试；并发串行化。尚无跨工作流投递账本，额外手动发送前务必核对当天接收记录。
- **可靠性**：抓取超时、2MB 内容限额、读源白名单、禁止重定向、RSS DTD 拒绝、有限条数、单源失败降级、50 项测试（含真实日历边界，测试不访问新闻源）。尚无数据库、长期快照、跨运行去重、补跑和告警。

## 本地快速开始

推荐 Python 3.12。从仓库根目录先 `cd market-digest`，然后运行：

```sh
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell 则使用：.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python digest.py
```

默认只生成 `out/report.json` 和 `out/report.txt`，不发送。49 项解析/流程测试只需要 Python 标准库；另 1 项真实交易日历测试需要安装 `requirements.txt`，未安装时明确跳过。依赖缺失或日历错误时 ETF 显示 unavailable，不用普通工作日替代。

```sh
python digest.py --sources sources.json --announcements announcements.json --output out
python digest.py --x-posts /your/private/path/x-posts.json
# 仅在已配置环境变量、确认目标机器人和报告后执行：
python digest.py --send
```

- `sources.json`：新闻源、72 小时窗口、每源最多 3 条；支持 1–168 小时、1–50 条、最多 30 源。新域名须核实后加入 `sources.py` 中的白名单，不能通过配置放开任意网络目的地。
- `announcements.json`：具体官方公告 HTTPS URL 数组，默认空。支持 `www.binance.com`、`www.okx.com`、`announcements.bybit.com`。
- X 导出格式见 `examples/x-posts.example.json`。示例是明确标注的虚构 fixture，不代表真实帖子，固定历史时间会被时间窗口过滤。实际导出不要提交到仓库，存私有目录。获取导出的授权、来源真实性仍由操作方核实。
- 未知发布时间新闻会标记 undated，不能宣称最新；过期和超前时间不收录。新闻摘录不是核实过的事实，也不是投资建议。

## 文件导航

- `digest.py`：ETF、公告、编排、文本输出、飞书。
- `sources.py`：RSS/Atom 和 X 导入。
- `activities.py`：币安与 OKX 官方列表候选发现。
- `sources.json` / `announcements.json`：非敏感源配置。
- `tests/`：离线解析、校验和 dry-run 集成测试。
- `docs/digest-workflow.yml.example`：未激活的手动 dry-run 示例。
- `AGENTS.md`：本地 Codex 的执行约束与验收要求。
- `docs/ROADMAP.md`：完整项目分阶段路线与明确缺口。
- `docs/VALIDATION.md`：测试边界与交接记录。

## GitHub / 飞书部署与运行边界

1. 先跑测试和真实源 dry run，核对数据日期、来源和失败状态。离线测试不等于线上可用。
2. 正式工作流 `.github/workflows/market-digest.yml` 每天北京时间 09:00 调度；文档示例仍仅供 dry run 参考。首发仅允许精确初始化提交消息触发一次，普通代码提交不发送。
3. 飞书必须先核实接收机器人、消息内容和授权，凭据仅从环境变量 `FEISHU_WEBHOOK_URL` 读取。不要把真实 webhook 放到代码、聊天或日志。
4. 当前只支持 `open.feishu.cn` 文本机器人。签名机器人、分片、投递账本未实现；不要降低现有安全设置来适配。
5. 发送超过 18,000 UTF-8 字节会被阻止。发送结果不确定时先核实，禁止盲重试。
6. 正式工作流不上传报告 artifact，也不把原文内容写入公开日志；仅记录源状态、数据日期、消息长度和投递结果。目标为已配置并验证的 FEISHU_WEBHOOK_URL。

完整依赖 hash 锁、Action 完整 SHA 固定、漏洞扫描、秘密扫描与生产监控仍需补齐。不要绕过访问控制、反爬或安全限制。

