# 全球上市公司文件下载与表格提取工具

这是一个面向投研使用的 Streamlit 网页工具。它可以按公司中文名、英文名、本地代码或美股 / ADR 代码搜索全球上市公司，聚合公开披露文件链接，并把文字版 PDF 中的表格导出为 Excel。

## 功能

- 全球公司模糊搜索：内置美股、港股、A 股、台股、韩股、日股、欧洲知名公司样本，并可用 SEC 全量公司列表搜索美股。
- 公开文件发现：支持 SEC EDGAR、港交所披露易、公司 IR 官网、网页搜索兜底。
- 文件类型筛选：年度报告、季度 / 中期报告、招股说明书、Transcript、Presentation、Proxy。
- PDF 表格提取：使用 `pdfplumber` 提取文字版 PDF 表格，并用 `openpyxl` 生成每表一个 Sheet 的 Excel。
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

1. 在“文件下载”页输入公司名或代码，例如 `Apple`、`AAPL`、`台积电`、`2330`、`TSM`、`腾讯`、`0700`、`Infineon`。
2. 在搜索结果中点击“选择”。
3. 勾选文件类型与年份，点击“获取文件列表”。
4. 在按来源分组的列表中打开直链或官方平台跳转链接。
5. 在“PDF 表格提取”页上传一个或多个文字版 PDF，生成并下载 Excel。

## 部署到 Streamlit Cloud

1. 将本目录提交到一个 GitHub 仓库。
2. 在 Streamlit Cloud 新建应用，入口文件选择 `app.py`。
3. 如需 Claude 增强功能，可在 Streamlit Cloud 的 Secrets 中配置 Anthropic Key，也可以让用户在侧边栏临时输入。

## 数据源说明

- SEC EDGAR：通过 `data.sec.gov/submissions/CIKxxxxxxxxxx.json` 获取 10-K、20-F、10-Q、6-K、S-1、F-1、424B4、DEF 14A 等文件。
- 港交所披露易：通过公开 handler 接口尝试获取年报、中报与招股书。
- 公司 IR 官网：抓取官方投资者关系页面中的 PDF、报告和演示材料链接。
- Transcript / Presentation：通过 Motley Fool、Stock Analysis、DuckDuckGo 网页搜索和可选 Claude 兜底发现。

## 已知限制

- A 股、部分港股、欧洲与亚洲本地市场没有统一开放 API，工具会优先提供官方平台或 Google PDF 搜索兜底。
- Transcript 和 Presentation 自动发现依赖第三方页面结构，可能随网站变化而失效。
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
    ├── ir_scraper.py
    ├── transcript_fetcher.py
    ├── table_extractor.py
    ├── excel_writer.py
    └── utils.py
```
