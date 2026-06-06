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
- 网页转 PDF：对 transcript、presentation 和普通网页链接，会抓取网页正文并转成 PDF 放入下载包，避免只保存链接。
- 可选 Claude 增强：输入 Anthropic API Key 后，可用于 Sheet 智能命名和自动发现失败时的兜底建议。
- 健壮降级：单个数据源失败不会中断其它来源；Transcript / Presentation 搜索带线程硬超时，避免长时间卡住。

## 开源工具集成

当前版本已开始吸收 GitHub 高星开源项目中适合本工具目标的成熟能力：

- 网页正文抽取：接入 `trafilatura` 与 `readability-lxml`，用于更稳定地阅读 transcript、presentation 网页、微信公众号转载页和财经新闻页面。
- 网页转 PDF：网页放入下载包前优先使用开源正文抽取结果，同时保留原始 HTML 表格抽取，减少广告、导航栏、登录提示对 PDF 的污染。
- 表格与 Excel：继续使用 `pdfplumber`、`BeautifulSoup` 与 `openpyxl`，后续可评估接入 `camelot` 或 `docling` 处理更复杂 PDF 表格。
- 金融数据：当前已有 `yfinance`、SEC companyfacts、巨潮、Wind MCP 通道；后续可评估接入 `akshare` 与 `edgartools`，分别增强中国市场数据和 SEC/XBRL 解析。
- 可视化：当前 HTML 使用原生交互图表逻辑；后续可评估接入 `plotly.py` 或 ECharts，以提升固定 13 张财务图的移动端交互体验。

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

## AI 行业研究工具入口

本仓库新增了独立的研究产品原型入口，不影响原来的文件下载器：

```powershell
streamlit run research_app.py
```

当前 `research_app.py` 面向 AI 产业链研究 V0.1，支持：

- 输入目标公司，默认从 `NVDA` 开始。
- 自动生成精选可比组，包括核心业务、上游供给、下游需求、基础设施 / 替代路线、私有模型公司观察组。
- 用户可删除 / 新增可比公司。
- 选择最近 4 / 8 / 12 个季度。
- 复用现有 SEC、IR、Transcript、Presentation、Bing 定向搜索和中文来源模块，生成证据审计与信号草稿。
- 在用户确认草稿后，生成投资备忘录 HTML 和交互式看板 HTML。
- HTML 中的信号卡片、审计项和证据表支持点击打开来源抽屉，后续会继续补 PDF / 网页截图、页码跳转和表格单元格溯源。

### 大模型厂商

研究入口左侧边栏支持按厂商选择模型：

- `Anthropic（qweapi）`：默认优先调用 `claude-opus-4-8`，通过 `https://qweapi.com/v1/chat/completions`。
- `OpenAI（qweapi）`：默认优先调用 `gpt-5.5`，通过 `https://qweapi.com/v1/chat/completions`。
- `DeepSeek（直连）`：默认优先调用 `deepseek-v4-pro`，通过 DeepSeek 官方兼容接口。
- 本地 `.env` 或 Streamlit Secrets 可配置：`LLM_PROVIDER=anthropic` / `openai` / `deepseek`、`QWEAPI_API_KEY=你的 qweapi key`、`ANTHROPIC_QWEAPI_MODEL=claude-opus-4-8`、`OPENAI_QWEAPI_MODEL=gpt-5.5`、`DEEPSEEK_API_KEY=你的 DeepSeek key`
- 侧边栏提供“测试模型连接”按钮，可在正式研究前确认模型是否可调用。

研究工具默认本地会话即可运行；如果配置 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY` 环境变量，会把任务、报告元数据和访问日志写入 Supabase/Postgres。V0.1 先预留微信登录、授权用户可见、访问行为记录和异步任务队列结构，后台队列与企业微信通知会在下一阶段接入。

## 使用流程

1. 输入公司名或代码后按回车，或点击“搜索”，例如 `Apple`、`AAPL`、`Intel`、`INTC`、`Siltronic`、`SUMCO`、`台积电`、`2330`、`TSM`、`腾讯`、`0700`、`Infineon`。
2. 在搜索结果中点击“选择”。
3. 用复选框勾选文件类型、年份和季度，也可以勾选“全选”，年份默认覆盖最近 20 年。
4. 在按来源分组的列表中打开直链或官方平台跳转链接。
5. 点击“下载文件、提取表格并打包 ZIP”，下载到的文件、网页转 PDF、链接清单和自动生成的 Excel 会一并放入 ZIP。

## 部署到 Streamlit Cloud

1. 将本目录提交到一个 GitHub 仓库。
2. 在 Streamlit Cloud 新建应用，入口文件选择 `app.py`。
3. 如需 Claude 增强功能，可在 Streamlit Cloud 的 Secrets 中配置 Anthropic Key，也可以让用户在侧边栏临时输入。

## 部署到 Vercel

Vercel 轻量版已隔离在 `vercel` 分支，避免 Vercel 的 `pyproject.toml` / API 入口影响 Streamlit Cloud 构建。由于 Vercel Serverless Functions 不适合直接运行 Streamlit 长连接服务，Vercel 版只提供搜索、文件清单和小体积 ZIP 打包；完整交互与大文件下载仍建议使用 Streamlit Cloud。

1. 在 Vercel 新建项目并导入同一个 GitHub 仓库。
2. Production Branch 选择 `vercel`。
3. Framework Preset 选择 `Other`。
4. Root Directory 保持仓库根目录。
5. 如需 Claude 增强，可在 Vercel Environment Variables 中添加 `ANTHROPIC_API_KEY`。

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
- 网页转 PDF 采用正文提取方式，不模拟完整浏览器渲染；极端复杂或登录态页面可能只保留可抓取正文和来源 URL。
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
