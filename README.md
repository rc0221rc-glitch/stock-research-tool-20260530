# 全球上市公司文件下载与表格提取工具

这是一个面向投研使用的 Streamlit 网页工具。它可以按公司中文名、英文名、本地代码或美股 / ADR 代码搜索全球上市公司，聚合公开披露文件链接，并把文字版 PDF 中的表格导出为 Excel。

## 功能

- 全球公司模糊搜索：内置美股、港股、A 股、台股、韩股、日股、欧洲知名公司样本，并叠加 Yahoo Finance 全球证券搜索与 SEC 全量公司列表。
- 公开文件发现：支持 SEC EDGAR、巨潮资讯、港交所披露易、公司 IR 官网、Bing 定向搜索和网页搜索兜底。
- 官方公告底线：勾选年报 / 季报时，美股优先返回 SEC 10-K / 10-Q / 20-F / 6-K；A 股、科创板和部分中概 / 港股回 A 公司优先返回巨潮资讯官方 PDF。
- 中国公司增强来源：对 A 股、港股和中概股增加微信公众号 / Sogou 微信、雪球、东方财富、华尔街见闻、CNINFO 等中文投研与公告搜索入口。
- Transcript / Presentation 平台深搜：额外覆盖 Seeking Alpha、Motley Fool、MarketBeat、EarningsCall.biz、Stock Analysis、MarketScreener、AlphaSpread、GuruFocus、Investing.com、AlphaStreet、Q4、PR Newswire、BusinessWire、GlobeNewswire、Quartr、TIKR、Koyfin、BamSEC 等公开页面或搜索入口。
- Bing 定向搜索：按公司别名、年份、季度和文件类型组合逐一搜索，优先保留企业官网、公告平台和可直接下载的 PDF 链接。
- 文件类型筛选：年度报告、季度 / 中期报告、招股说明书、Transcript、Presentation、Proxy。
- 自动表格提取：下载文件打包时会同步从文字版 PDF / HTML 中提取表格，并用 `openpyxl` 生成每表一个 Sheet 的 Excel。
- 可选 Claude 增强：输入 Anthropic API Key 后，可用于 Sheet 智能命名和自动发现失败时的兜底建议。
- 健壮降级：单个数据源失败不会中断其它来源；Transcript / Presentation 搜索带线程硬超时，避免长时间卡住。

## 安装

建议使用 Python 3.10 或更高版本。

```powershell
cd C:\Users\caojm\Documents\Codex\2026-05-30\new-chat-2\outputs\stock-research-tool
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

```powershell
streamlit run app.py
```

启动后浏览器会打开本地地址，通常是 `http://localhost:8501`。

## 使用流程

1. 输入公司名或代码后按回车，或点击“搜索”，例如 `Apple`、`AAPL`、`Intel`、`INTC`、`Siltronic`、`SUMCO`、`台积电`、`2330`、`TSM`、`腾讯`、`0700`、`Infineon`。
2. 在搜索结果中点击“选择”。
3. 用复选框勾选文件类型、年份和季度，也可以勾选“全选”，年份默认覆盖最近 20 年。
4. 在按来源分组的列表中打开直链或官方平台跳转链接。
5. 点击“下载文件、提取表格并打包 ZIP”，下载到的文件、链接清单和自动生成的 Excel 会一并放入 ZIP。

## 部署到 Streamlit Cloud

1. 将本目录提交到一个 GitHub 仓库。
2. 在 Streamlit Cloud 新建应用，入口文件选择 `app.py`。
3. 如需 Claude 增强功能，可在 Streamlit Cloud 的 Secrets 中配置 Anthropic Key，也可以让用户在侧边栏临时输入。

## 数据源说明

- SEC EDGAR：通过 `data.sec.gov/submissions/CIKxxxxxxxxxx.json` 获取 10-K、20-F、10-Q、6-K、S-1、F-1、424B4、DEF 14A 等文件；多选年份时逐年拉取，保证年报 / 季报官方文件优先出现。
- 巨潮资讯：通过 `cninfo.com.cn` 官方公告接口获取 A 股、科创板等公司的年度报告、一季报、半年报和三季报 PDF。
- 港交所披露易：通过公开 handler 接口尝试获取年报、中报与招股书。
- 公司 IR 官网：抓取官方投资者关系页面中的 PDF、报告和演示材料链接。
- 中文投研来源：对中国公司生成并抓取业绩会纪要、电话会纪要、交流纪要、微信公众号文章、雪球讨论和中文公告搜索结果。
- Bing 定向搜索：按所选年份 / 季度 / 文件类型生成查询词，例如“公司名 2025 Q1 earnings presentation filetype:pdf”或“公司名 2025 一季度 业绩会纪要”，解析前排结果并过滤广告、社交媒体和弱相关链接。
- Transcript / Presentation：通过 Motley Fool 股票页、MarketBeat、EarningsCall.biz、Stock Analysis、MarketScreener、AlphaSpread、Seeking Alpha、Q4/Notified/EQS/Investis 等 IR 托管和资讯平台，以及 Quartr、TIKR、Koyfin、BamSEC 等平台入口发现。

## 已知限制

- A 股、部分港股、欧洲与亚洲本地市场没有统一开放 API，工具会优先提供官方平台或 Google PDF 搜索兜底。
- Transcript 和 Presentation 自动发现依赖第三方页面结构，可能随网站变化而失效。
- 部分平台入口可能需要登录、订阅或地区访问权限；工具会保留搜索入口，但不绕过权限限制。
- 表格提取仅支持文字版 PDF；扫描件或图片型 PDF 需要先 OCR。
- 请遵守 SEC、HKEX、IR 托管平台和第三方网页的使用条款。本工具仅供学习研究使用。

## 项目结构

```text
stock-research-tool/
├── app.py
├── requirements.txt
├── README.md
└── src/
    ├── __init__.py
    ├── company_search_global.py
    ├── filing_fetcher_us.py
    ├── hkex_fetcher.py
    ├── cninfo_fetcher.py
    ├── ir_scraper.py
    ├── transcript_fetcher.py
    ├── china_sources.py
    ├── platform_discovery.py
    ├── bing_discovery.py
    ├── download_packager.py
    ├── table_extractor.py
    ├── excel_writer.py
    └── utils.py
```
