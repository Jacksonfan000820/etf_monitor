# 币圈、美股与 ETF 综合情报模块

这是可运行的 Python 工程起点，不是已经上线的完整金融平台。本模块位于原 ETF 仓库的独立 `market-digest/` 目录。完整项目方向包括币圈、美股/美国金融、ETF、X/KOL、交易所活动、飞书推送和可靠运行。真实数据接入、合规授权、质量与部署仍须逐步验收。

**本模块已整合进现有 ETF 仓库，尚未部署或启用定时，不代表已在用户电脑安装。没有发送真实飞书消息。**

## 实际交付范围

- **ETF**：Farside BTC/ETH 现货 ETF 资金流 HTML 解析；百万美元单位；区分缺失和零；列合计核对；真实 XNYS 已收盘交易日；连续 5 交易日窗口；current/stale/unavailable 状态。非全市场 ETF 行情、持仓或 AUM 系统。
- **币圈/美国金融新闻**：新增可运行 RSS/Atom 适配器。配置 Fed、SEC、CoinDesk 候选源；独立故障隔离、单次运行 URL 去重、时间窗口过滤、明确未知发布时间、标题与描述原文摘录、源链接。Fed 为宏观政策、SEC 为监管新闻，不等于全面个股新闻覆盖。候选 URL 尚未在本次环境进行真实联网验证，可能需要更新或处理访问限制。
- **X/KOL**：新增用户提供且有权使用的 JSON 导出导入器，校验作者与 URL 一致、帖子 ID 去重、时间窗口、原文及链接。**没有直接调用 X API、自动抓取、授权登录或智能观点总结**；导入内容真实性未独立验证。
- **交易所活动**：人工配置官方公告 URL，抓取标题和 meta 描述；白名单、HTTPS、禁止重定向。只是候选公告证据，不是完整活动发现、资格判断或收益核验。
- **飞书**：已有文本机器人发送函数，只在明确 `--send` 时调用；凭据仅来自环境变量；不自动重试不确定发送；消息超过 18,000 UTF-8 字节直接阻止发送，避免静默截断。**签名机器人和分片发送尚未实现**。
- **GitHub Actions**：仓库 CI 增加离线测试；文档附有未启用的手动 dry-run 示例，不含定时或发送步骤。
- **可靠性**：抓取超时、2MB 内容限额、读源白名单、禁止重定向、RSS DTD 拒绝、有限条数、单源失败降级、34 项测试（含真实日历边界，测试不访问新闻源）。尚无数据库、长期快照、跨运行去重、补跑和告警。

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

默认只生成 `out/report.json` 和 `out/report.txt`，不发送。33 项解析/流程测试只需要 Python 标准库；第 34 项真实交易日历测试需要安装 `requirements.txt`，未安装时明确跳过。依赖缺失或日历错误时 ETF 显示 unavailable，不用普通工作日替代。

```sh
python digest.py --sources sources.json --announcements announcements.json --output out
python digest.py --x-posts /your/private/path/x-posts.json
# 仅在已配置环境变量、确认目标机器人和报告后执行：
python digest.py --send
```

- `sources.json`：新闻源、72 小时窗口、每源最多 10 条；支持 1–168 小时、1–50 条、最多 30 源。新域名须核实后加入 `sources.py` 中的白名单，不能通过配置放开任意网络目的地。
- `announcements.json`：具体官方公告 HTTPS URL 数组，默认空。支持 `www.binance.com`、`www.okx.com`、`announcements.bybit.com`。
- X 导出格式见 `examples/x-posts.example.json`。示例是明确标注的虚构 fixture，不代表真实帖子，固定历史时间会被时间窗口过滤。实际导出不要提交到仓库，存私有目录。获取导出的授权、来源真实性仍由操作方核实。
- 未知发布时间新闻会标记 undated，不能宣称最新；过期和超前时间不收录。新闻摘录不是核实过的事实，也不是投资建议。

## 文件导航

- `digest.py`：ETF、公告、编排、文本输出、飞书。
- `sources.py`：RSS/Atom 和 X 导入。
- `sources.json` / `announcements.json`：非敏感源配置。
- `tests/`：离线解析、校验和 dry-run 集成测试。
- `docs/digest-workflow.yml.example`：未激活的手动 dry-run 示例。
- `AGENTS.md`：本地 Codex 的执行约束与验收要求。
- `docs/ROADMAP.md`：完整项目分阶段路线与明确缺口。
- `docs/VALIDATION.md`：测试边界与交接记录。

## GitHub / 飞书部署（尚未执行）

1. 先跑测试和真实源 dry run，核对数据日期、来源和失败状态。离线测试不等于线上可用。
2. 当前根目录 CI 只执行测试。文档内的 `digest-workflow.yml.example` 是不含发送、不含定时的手动 dry-run 模板；经授权后可复制到仓库根 `.github/workflows/`。
3. 飞书必须先核实接收机器人、消息内容和授权，凭据仅从环境变量 `FEISHU_WEBHOOK_URL` 读取。不要把真实 webhook 放到代码、聊天或日志。
4. 当前只支持 `open.feishu.cn` 文本机器人。签名机器人、分片、投递账本未实现；不要降低现有安全设置来适配。
5. 发送超过 18,000 UTF-8 字节会被阻止。发送结果不确定时先核实，禁止盲重试。
6. 模板上传报告 artifact 前，应确认内容使用许可与仓库访问范围。生产定时、发送、目标频道和时区须另行验证和授权。

完整依赖 hash 锁、Action 完整 SHA 固定、漏洞扫描、秘密扫描与生产监控仍需补齐。不要绕过访问控制、反爬或安全限制。
