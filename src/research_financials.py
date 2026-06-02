from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import io
import re
from typing import Any

import requests

from .research_display import company_display_name, point_display_name
from .research_models import CompanyProfile, FinancialChart, FinancialDataPoint, FinancialSource
from .utils import request_json
from .wind_client import WIND_SOURCE_NOTE, is_wind_available, normalize_windcode, parse_wind_tables, wind_financial_query, wind_rows_by_column, wind_units_by_column


METRIC_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "rd_expense": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "cash_from_operations": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}

METRIC_LABELS = {
    "revenue": "Revenue",
    "gross_profit": "Gross Profit",
    "rd_expense": "R&D Expense",
    "operating_income": "Operating Income",
    "net_income": "Net Income",
    "gross_margin": "Gross Margin",
    "operating_margin": "Operating Margin",
    "rd_intensity": "R&D / Revenue",
    "cash_from_operations": "Operating Cash Flow",
    "capex": "Capital Expenditures",
    "free_cash_flow": "Free Cash Flow",
    "capex_intensity": "CapEx / Revenue",
    "inventory": "Inventory",
    "construction_in_progress": "Construction in Progress",
}


@dataclass
class MetricSeries:
    metric: str
    label: str
    points: list[FinancialDataPoint]


def build_financial_charts(
    companies: list[CompanyProfile],
    quarter_count: int = 4,
    target: CompanyProfile | None = None,
) -> tuple[list[FinancialChart], list[str]]:
    notes: list[str] = []
    all_series: dict[str, dict[str, MetricSeries]] = {}
    public_companies = [company for company in companies if company.is_public]
    for company in public_companies:
        company_series: dict[str, MetricSeries] = {}
        if _is_china_a_share(company):
            if is_wind_available():
                try:
                    company_series = fetch_wind_metric_series(company, quarter_count=quarter_count)
                except Exception as exc:
                    notes.append(f"{company.ticker}: Wind 财务数据抓取失败：{_compact_wind_error(exc)}")
            try:
                cninfo_series = fetch_cninfo_metric_series(company, quarter_count=quarter_count)
                company_series = _prefer_primary_series(company_series, cninfo_series)
                if cninfo_series:
                    notes.append(f"{company.ticker}: 已补充巨潮官方 PDF 表格数据，用于净利润、现金流、存货、在建工程等披露字段。")
            except Exception as exc:
                if not company_series:
                    notes.append(f"{company.ticker}: 巨潮 PDF 财务表格提取失败：{exc}")
            if not company_series:
                try:
                    company_series = fetch_cninfo_metric_series(company, quarter_count=quarter_count)
                    if company_series:
                        notes.append(f"{company.ticker}: Wind 不可用或无返回，已从巨潮官方 PDF 提取主要财务表格生成图表。")
                except Exception as exc:
                    notes.append(f"{company.ticker}: 巨潮 PDF 财务表格提取失败：{exc}")
            if not company_series and not is_wind_available():
                notes.append(f"{company.ticker}: 当前运行环境没有本机 Wind MCP；A股财务图表已尝试改从巨潮官方 PDF 提取。")
        elif company.cik:
            try:
                company_series = fetch_company_metric_series(company, quarter_count=quarter_count)
            except Exception as exc:
                notes.append(f"{company.ticker}: SEC companyfacts 财务数据抓取失败：{exc}")
        if not _is_china_a_share(company) and _needs_wind_financials(company, company_series):
            try:
                wind_series = fetch_wind_metric_series(company, quarter_count=quarter_count)
                company_series = _prefer_primary_series(company_series, wind_series)
            except Exception as exc:
                if is_wind_available():
                    notes.append(f"{company.ticker}: Wind 财务数据抓取失败：{_compact_wind_error(exc)}")
        if company_series:
            all_series[_company_series_key(company)] = company_series

    if is_wind_available() and any(_series_uses_wind(series) for series in all_series.values()):
        notes.append(WIND_SOURCE_NOTE)

    charts: list[FinancialChart] = []
    if not all_series:
        return charts, notes

    target = target or companies[0]
    target_name = company_display_name(target)
    target_series = all_series.get(_company_series_key(target), {})
    if not target_series:
        notes.append(
            f"{target.ticker or target.name}: target financial series unavailable; skipped target-only charts rather than substituting peer data."
        )
    revenue_points = target_series.get("revenue", MetricSeries("revenue", METRIC_LABELS["revenue"], [])).points
    if revenue_points:
        charts.append(
            FinancialChart(
                chart_id="target_revenue_trend",
                title=f"{target_name} Revenue trend",
                subtitle=_source_subtitle(revenue_points, "Latest quarters from audited filings / Wind fundamentals; click any point to inspect source metadata."),
                chart_type="bar_line",
                y_axis=_axis_label(revenue_points),
                points=revenue_points,
                insight=_trend_insight(target_name, "revenue", revenue_points),
                source_note=_source_note_for_points(revenue_points),
            )
        )

    for supplemental_metric in ["net_income", "cash_from_operations", "capex", "free_cash_flow", "inventory", "construction_in_progress"]:
        points = target_series.get(supplemental_metric, MetricSeries(supplemental_metric, METRIC_LABELS.get(supplemental_metric, supplemental_metric), [])).points
        if points:
            charts.append(
                FinancialChart(
                    chart_id=f"target_{supplemental_metric}",
                    title=f"{target_name} {METRIC_LABELS.get(supplemental_metric, supplemental_metric)} trend",
                    subtitle=_source_subtitle(points, "Latest reported periods from filings / Wind fundamentals; click any point to inspect source metadata."),
                    chart_type="line" if supplemental_metric in {"inventory", "construction_in_progress"} else "bar_line",
                    y_axis=_axis_label(points),
                    points=points,
                    insight=_trend_insight(target_name, supplemental_metric, points),
                    source_note=_source_note_for_points(points),
                )
            )

    for margin_metric in ["gross_margin", "operating_margin", "rd_intensity", "capex_intensity"]:
        points = target_series.get(margin_metric, MetricSeries(margin_metric, METRIC_LABELS[margin_metric], [])).points
        if points:
            charts.append(
                FinancialChart(
                    chart_id=f"target_{margin_metric}",
                    title=f"{target_name} {METRIC_LABELS[margin_metric]}",
                    subtitle=_source_subtitle(points, "Derived from reported income statement fields; source links remain attached to the underlying metrics."),
                    chart_type="line",
                    y_axis="%",
                    points=points,
                    insight=_trend_insight(target_name, margin_metric, points),
                    source_note=_source_note_for_points(points),
                )
            )

    peer_revenue = _latest_peer_points(all_series, "revenue")
    if len(peer_revenue) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_revenue",
                title="Latest reported revenue: target company vs selected public comparables",
                subtitle="Cross-sectional view over companies with available SEC XBRL or Wind fundamentals data in this prototype.",
                chart_type="bar",
                y_axis=_axis_label(peer_revenue),
                points=peer_revenue,
                insight=_peer_insight("revenue", peer_revenue),
                source_note=_source_note_for_points(peer_revenue),
            )
        )

    peer_gross_margin = _latest_peer_points(all_series, "gross_margin")
    if len(peer_gross_margin) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_gross_margin",
                title="Latest gross margin: target company vs selected public comparables",
                subtitle="Gross margin is calculated or directly sourced for the same reported period where available.",
                chart_type="bar",
                y_axis="%",
                points=peer_gross_margin,
                insight=_peer_insight("gross_margin", peer_gross_margin),
                source_note=_source_note_for_points(peer_gross_margin),
            )
        )

    peer_operating_margin = _latest_peer_points(all_series, "operating_margin")
    if len(peer_operating_margin) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_operating_margin",
                title="Latest operating margin: target company vs selected public comparables",
                subtitle="Operating margin is calculated as operating income divided by revenue for the same reported period where available.",
                chart_type="bar",
                y_axis="%",
                points=peer_operating_margin,
                insight=_peer_insight("operating_margin", peer_operating_margin),
                source_note=_source_note_for_points(peer_operating_margin),
            )
        )
    for peer_metric in ["rd_intensity", "capex_intensity"]:
        peer_points = _latest_peer_points(all_series, peer_metric)
        if len(peer_points) >= 2:
            charts.append(
                FinancialChart(
                    chart_id=f"peer_latest_{peer_metric}",
                    title=f"Latest {METRIC_LABELS[peer_metric]}: target company vs selected public comparables",
                    subtitle=f"{METRIC_LABELS[peer_metric]} is calculated from reported quarterly financial fields where available.",
                    chart_type="bar",
                    y_axis="%",
                    points=peer_points,
                    insight=_peer_insight(peer_metric, peer_points),
                    source_note=_source_note_for_points(peer_points),
                )
            )
    charts = _validate_target_chart_identity(charts, target, notes)
    return charts, notes


def _company_series_key(company: CompanyProfile) -> str:
    return (company.ticker or company.name).upper()


def _validate_target_chart_identity(
    charts: list[FinancialChart],
    target: CompanyProfile,
    notes: list[str],
) -> list[FinancialChart]:
    target_ticker = (target.ticker or "").upper()
    if not target_ticker:
        return charts
    valid_charts: list[FinancialChart] = []
    for chart in charts:
        if not chart.chart_id.startswith("target_"):
            valid_charts.append(chart)
            continue
        mismatched_tickers = sorted(
            {
                point.ticker
                for point in chart.points
                if (point.ticker or "").upper() != target_ticker
            }
        )
        if mismatched_tickers:
            notes.append(
                f"{target_ticker}: dropped {chart.chart_id} because target-only chart contained peer ticker(s): {', '.join(mismatched_tickers)}."
            )
            continue
        valid_charts.append(chart)
    return valid_charts


def fetch_cninfo_metric_series(company: CompanyProfile, quarter_count: int = 4) -> dict[str, MetricSeries]:
    from .cninfo_fetcher import fetch_cninfo_filings

    years = _recent_years_for_filings(quarter_count)
    filings = fetch_cninfo_filings(
        company.to_company_dict(),
        kinds=["quarterly", "annual"],
        years=years,
        quarters=["Q1", "Q2", "Q3", "Q4"],
        limit=max(quarter_count + 4, 12),
    )
    raw_metric_points: dict[str, list[FinancialDataPoint]] = {}
    for filing in filings[: max(quarter_count + 2, 8)]:
        if not str(filing.get("url") or "").casefold().endswith(".pdf"):
            continue
        points = _extract_cninfo_points_from_pdf(company, filing)
        for point in points:
            raw_metric_points.setdefault(point.metric, []).append(point)

    series: dict[str, MetricSeries] = {}
    for metric, points in raw_metric_points.items():
        unique: dict[str, FinancialDataPoint] = {}
        for point in points:
            existing = unique.get(point.end_date)
            if not existing or _cninfo_point_priority(point) > _cninfo_point_priority(existing):
                unique[point.end_date] = point
        latest = sorted(unique.values(), key=lambda point: point.end_date)[-quarter_count:]
        if latest:
            series[metric] = MetricSeries(metric, METRIC_LABELS.get(metric, metric), latest)

    derived = _derived_margin_points(company, raw_metric_points, "gross_margin", "gross_profit", "revenue")
    if derived:
        series["gross_margin"] = MetricSeries("gross_margin", METRIC_LABELS["gross_margin"], sorted(derived, key=lambda point: point.end_date)[-quarter_count:])
    derived = _derived_margin_points(company, raw_metric_points, "operating_margin", "operating_income", "revenue")
    if derived:
        series["operating_margin"] = MetricSeries("operating_margin", METRIC_LABELS["operating_margin"], sorted(derived, key=lambda point: point.end_date)[-quarter_count:])
    derived = _derived_margin_points(company, raw_metric_points, "rd_intensity", "rd_expense", "revenue")
    if derived:
        series["rd_intensity"] = MetricSeries("rd_intensity", METRIC_LABELS["rd_intensity"], sorted(derived, key=lambda point: point.end_date)[-quarter_count:])
    derived = _derived_margin_points(company, raw_metric_points, "capex_intensity", "capex", "revenue")
    if derived:
        series["capex_intensity"] = MetricSeries("capex_intensity", METRIC_LABELS["capex_intensity"], sorted(derived, key=lambda point: point.end_date)[-quarter_count:])
    fcf = _derived_free_cash_flow_points(company, raw_metric_points)
    if fcf:
        series["free_cash_flow"] = MetricSeries("free_cash_flow", METRIC_LABELS["free_cash_flow"], sorted(fcf, key=lambda point: point.end_date)[-quarter_count:])
    return series


def _extract_cninfo_points_from_pdf(company: CompanyProfile, filing: dict[str, Any]) -> list[FinancialDataPoint]:
    url = str(filing.get("url") or "")
    title = str(filing.get("title") or "")
    period_info = _cninfo_period_info(title, str(filing.get("date") or ""))
    if not url or not period_info:
        return []
    try:
        pdf_bytes = requests.get(url, timeout=18, headers={"User-Agent": "Mozilla/5.0"}).content
    except Exception:
        return []
    try:
        import pdfplumber
    except Exception:
        return []

    metrics: dict[str, tuple[float, int, str]] = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        max_pages = min(len(pdf.pages), 14)
        for page_number, page in enumerate(pdf.pages[:max_pages], start=1):
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []
            for table in tables:
                if period_info["kind"] == "annual":
                    quarter_metrics = _extract_annual_quarter_points(company, filing, table, page_number, period_info["year"])
                    if quarter_metrics:
                        return quarter_metrics
                for row_index, row in enumerate(table):
                    row_values = ["" if cell is None else str(cell).strip() for cell in (row or [])]
                    window_rows = table[row_index : row_index + 3]
                    label = _row_label(row_values, window_rows)
                    values = _numeric_cells(row_values, skip_leading_years=True)
                    if not values:
                        continue
                    metric = _metric_from_cninfo_label(label)
                    if not metric or metric in metrics:
                        continue
                    value_index = _cninfo_value_index(metric, period_info["kind"], values)
                    if value_index >= len(values):
                        continue
                    metrics[metric] = (values[value_index], page_number, label)
            if _cninfo_has_core_metrics(metrics):
                break

    points: list[FinancialDataPoint] = []
    for metric, (value, page_number, label) in metrics.items():
        if metric in {"gross_profit", "operating_income", "rd_expense"} and period_info["kind"] in {"h1", "annual"}:
            continue
        source = FinancialSource(
            title=f"{company_display_name(company)} 巨潮公告 {title}",
            url=url,
            accession="CNINFO",
            form=str(filing.get("form") or ""),
            filed=str(filing.get("date") or ""),
            concept=f"CNINFO:{metric}:P{page_number}:{label[:80]}",
            unit="CNY",
        )
        points.append(
            FinancialDataPoint(
                ticker=company.ticker,
                company=company.name,
                metric=metric,
                metric_label=METRIC_LABELS.get(metric, metric),
                period=period_info["period"],
                end_date=period_info["end_date"],
                value=value,
                display_value=_format_reported_value(value, "CNY"),
                unit="CNY",
                series=company.ticker,
                sources=[source],
            )
        )
    return points


def _row_window_label(rows: list[list[Any]]) -> str:
    pieces: list[str] = []
    for row in rows:
        for cell in row or []:
            text = "" if cell is None else str(cell).strip()
            if text and not _looks_like_numeric_cell(text):
                pieces.append(text)
    return "".join(pieces)


def _row_label(row_values: list[str], window_rows: list[list[Any]]) -> str:
    direct = "".join(cell for cell in row_values[:4] if cell and not _looks_like_numeric_cell(cell))
    return direct or _row_window_label(window_rows)


def _numeric_cells_with_options(row: list[str], skip_leading_years: bool) -> list[float]:
    values: list[float] = []
    for index, cell in enumerate(row):
        if skip_leading_years and index <= 3 and re.fullmatch(r"20\d{2}年?", (cell or "").strip()):
            continue
        value = _parse_cn_number(cell)
        if value is not None:
            values.append(value)
    return values


def _numeric_cells(row: list[str], skip_leading_years: bool = False) -> list[float]:
    return _numeric_cells_with_options(row, skip_leading_years=skip_leading_years)


def _extract_annual_quarter_points(
    company: CompanyProfile,
    filing: dict[str, Any],
    table: list[list[Any]],
    page_number: int,
    year: str,
) -> list[FinancialDataPoint]:
    header_text = _row_window_label(table[:2])
    if not all(token in header_text for token in ["第一季度", "第二季度", "第三季度", "第四季度"]):
        return []
    points: list[FinancialDataPoint] = []
    quarter_end_dates = {
        "Q1": f"{year}-03-31",
        "Q2": f"{year}-06-30",
        "Q3": f"{year}-09-30",
        "Q4": f"{year}-12-31",
    }
    for row_index, row in enumerate(table):
        row_values = ["" if cell is None else str(cell).strip() for cell in (row or [])]
        label = _row_label(row_values, table[row_index : row_index + 3])
        metric = _metric_from_cninfo_label(label)
        if metric not in {"revenue", "net_income", "cash_from_operations"}:
            continue
        values = _numeric_cells(row_values)
        if len(values) < 4:
            continue
        for quarter, value in zip(["Q1", "Q2", "Q3", "Q4"], values[:4]):
            source = FinancialSource(
                title=f"{company_display_name(company)} 巨潮公告 {filing.get('title') or ''}",
                url=str(filing.get("url") or ""),
                accession="CNINFO",
                form=str(filing.get("form") or ""),
                filed=str(filing.get("date") or ""),
                concept=f"CNINFO:{metric}:P{page_number}:{label[:80]}:{quarter}",
                unit="CNY",
            )
            points.append(
                FinancialDataPoint(
                    ticker=company.ticker,
                    company=company.name,
                    metric=metric,
                    metric_label=METRIC_LABELS.get(metric, metric),
                    period=f"{year}{quarter}",
                    end_date=quarter_end_dates[quarter],
                    value=value,
                    display_value=_format_reported_value(value, "CNY"),
                    unit="CNY",
                    series=company.ticker,
                    sources=[source],
                )
            )
    return points


def _looks_like_numeric_cell(value: str) -> bool:
    return _parse_cn_number(value) is not None or value.strip() in {"--", "-", "—"}


def _parse_cn_number(value: str) -> float | None:
    text = (value or "").replace(",", "").replace("，", "").strip()
    if not text or text in {"--", "-", "—"} or "%" in text:
        return None
    text = text.replace("－", "-").replace("−", "-")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except Exception:
        return None


def _metric_from_cninfo_label(label: str) -> str:
    compact = label.replace(" ", "")
    if "营业收入" in compact and "营业成本" not in compact and "总成本" not in compact:
        return "revenue"
    if "归属于上市公司股东" in compact and "净利润" in compact and "扣除非经常" not in compact and "综合收益" not in compact:
        return "net_income"
    if "经营活动产生的现金流量净额" in compact:
        return "cash_from_operations"
    if "营业利润" in compact and "利润率" not in compact:
        return "operating_income"
    if "研发费用" in compact and "占" not in compact and "率" not in compact:
        return "rd_expense"
    if compact.startswith("存货") or compact == "存货":
        return "inventory"
    if "在建工程" in compact:
        return "construction_in_progress"
    return ""


def _cninfo_value_index(metric: str, report_kind: str, values: list[float]) -> int:
    if metric in {"inventory", "construction_in_progress"}:
        return 0
    if metric == "cash_from_operations" and report_kind in {"q1", "q3"} and len(values) >= 3:
        return 2
    return 0


def _cninfo_has_core_metrics(metrics: dict[str, tuple[float, int, str]]) -> bool:
    return "revenue" in metrics and ("net_income" in metrics or "inventory" in metrics)


def _cninfo_period_info(title: str, fallback_year: str = "") -> dict[str, str]:
    year = _year_from_text(title) or _year_from_text(fallback_year)
    if not year:
        return {}
    if "第一季度" in title or "一季度" in title:
        return {"kind": "q1", "period": f"{year}Q1", "end_date": f"{year}-03-31", "year": year}
    if "半年度" in title or "中期" in title:
        return {"kind": "h1", "period": f"{year}H1", "end_date": f"{year}-06-30", "year": year}
    if "第三季度" in title or "三季度" in title:
        return {"kind": "q3", "period": f"{year}Q3", "end_date": f"{year}-09-30", "year": year}
    if "年度报告" in title or "年报" in title:
        return {"kind": "annual", "period": f"FY{year}", "end_date": f"{year}-12-31", "year": year}
    return {}


def _year_from_text(text: str) -> str:
    match = re.search(r"(20\d{2})", text or "")
    return match.group(1) if match else ""


def _recent_years_for_filings(quarter_count: int) -> list[str]:
    end_year = date.today().year
    year_count = max(2, min(5, (quarter_count + 3) // 4 + 2))
    return [str(end_year - offset) for offset in range(year_count)]


def _cninfo_point_priority(point: FinancialDataPoint) -> tuple[int, str]:
    accession = point.sources[0].accession if point.sources else ""
    source_score = 1 if accession == "CNINFO" else 0
    period_score = 2 if "Q" in point.period else 1
    return (source_score + period_score, point.period)


def _is_china_a_share(company: CompanyProfile) -> bool:
    text = f"{company.ticker} {company.local_code} {company.market} {company.exchange} {company.country}".casefold()
    if "a股" in text or "szse" in text or "sse" in text or "bjse" in text:
        return True
    return bool(company.local_code and company.local_code.isdigit() and len(company.local_code) == 6 and "中国" in company.country)


def _compact_wind_error(exc: Exception) -> str:
    text = str(exc)
    if "QUOTA_ERROR" in text or "余额" in text or "充值" in text:
        return "Wind 当前额度/余额不足，已自动改用巨潮官方 PDF 表格兜底。"
    if len(text) > 220:
        return text[:220] + "..."
    return text


def fetch_company_metric_series(company: CompanyProfile, quarter_count: int = 4) -> dict[str, MetricSeries]:
    facts = request_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(company.cik).lstrip('0').zfill(10)}.json", timeout=14)
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    series: dict[str, MetricSeries] = {}
    raw_metric_points: dict[str, list[FinancialDataPoint]] = {}
    for metric, concepts in METRIC_CONCEPTS.items():
        points = _points_for_concepts(company, metric, concepts, us_gaap, quarter_count)
        if points:
            raw_metric_points[metric] = points
            series[metric] = MetricSeries(metric, METRIC_LABELS[metric], points)

    derived = _derived_margin_points(company, raw_metric_points, "gross_margin", "gross_profit", "revenue")
    if derived:
        series["gross_margin"] = MetricSeries("gross_margin", METRIC_LABELS["gross_margin"], derived)
    derived = _derived_margin_points(company, raw_metric_points, "operating_margin", "operating_income", "revenue")
    if derived:
        series["operating_margin"] = MetricSeries("operating_margin", METRIC_LABELS["operating_margin"], derived)
    derived = _derived_margin_points(company, raw_metric_points, "rd_intensity", "rd_expense", "revenue")
    if derived:
        series["rd_intensity"] = MetricSeries("rd_intensity", METRIC_LABELS["rd_intensity"], derived)
    derived = _derived_margin_points(company, raw_metric_points, "capex_intensity", "capex", "revenue")
    if derived:
        series["capex_intensity"] = MetricSeries("capex_intensity", METRIC_LABELS["capex_intensity"], derived)
    fcf = _derived_free_cash_flow_points(company, raw_metric_points)
    if fcf:
        series["free_cash_flow"] = MetricSeries("free_cash_flow", METRIC_LABELS["free_cash_flow"], fcf)
    return series


def fetch_wind_metric_series(company: CompanyProfile, quarter_count: int = 4) -> dict[str, MetricSeries]:
    periods = _recent_completed_quarters(quarter_count)
    errors: list[str] = []
    for windcode in _windcode_candidates(company):
        raw_metric_points: dict[str, list[FinancialDataPoint]] = {}
        for period, row, units in _fetch_wind_period_rows(windcode, periods, errors):
            if not row:
                continue
            currency = str(row.get("记账本位币") or row.get("交易币种") or "")
            extracted = _extract_wind_metrics(row, units, period, currency)
            for metric, value in extracted.items():
                if value is None:
                    continue
                source = _wind_source(company, windcode, period, value["column"], value["unit"])
                normalized_value = _normalize_wind_value(float(value["value"]), value["unit"])
                normalized_unit = _wind_unit_label(value["unit"], currency)
                raw_metric_points.setdefault(metric, []).append(
                    FinancialDataPoint(
                        ticker=company.ticker,
                        company=company.name,
                        metric=metric,
                        metric_label=METRIC_LABELS[metric],
                        period=period,
                        end_date=_quarter_end_date(period),
                        value=normalized_value,
                        display_value=_format_wind_value(normalized_value, normalized_unit, currency),
                        unit=normalized_unit,
                        series=company.ticker,
                        sources=[source],
                    )
                )

        series: dict[str, MetricSeries] = {}
        for metric, points in raw_metric_points.items():
            if points:
                series[metric] = MetricSeries(metric, METRIC_LABELS[metric], sorted(points, key=lambda point: point.end_date))

        derived = _derived_margin_points(company, raw_metric_points, "gross_margin", "gross_profit", "revenue")
        if derived and "gross_margin" not in series:
            series["gross_margin"] = MetricSeries("gross_margin", METRIC_LABELS["gross_margin"], derived)
        derived = _derived_margin_points(company, raw_metric_points, "operating_margin", "operating_income", "revenue")
        if derived and "operating_margin" not in series:
            series["operating_margin"] = MetricSeries("operating_margin", METRIC_LABELS["operating_margin"], derived)
        derived = _derived_margin_points(company, raw_metric_points, "rd_intensity", "rd_expense", "revenue")
        if derived and "rd_intensity" not in series:
            series["rd_intensity"] = MetricSeries("rd_intensity", METRIC_LABELS["rd_intensity"], derived)
        derived = _derived_margin_points(company, raw_metric_points, "capex_intensity", "capex", "revenue")
        if derived and "capex_intensity" not in series:
            series["capex_intensity"] = MetricSeries("capex_intensity", METRIC_LABELS["capex_intensity"], derived)
        fcf = _derived_free_cash_flow_points(company, raw_metric_points)
        if fcf and "free_cash_flow" not in series:
            series["free_cash_flow"] = MetricSeries("free_cash_flow", METRIC_LABELS["free_cash_flow"], fcf)
        if series:
            return series
    if errors:
        raise RuntimeError("; ".join(dict.fromkeys(errors))[:1000])
    return {}

def _fetch_wind_period_rows(windcode: str, periods: list[str], errors: list[str] | None = None) -> list[tuple[str, dict[str, Any], dict[str, str]]]:
    bulk_rows = _fetch_wind_bulk_rows(windcode, periods, errors)
    by_period = {period: (row, units) for period, row, units in bulk_rows}
    rows: list[tuple[str, dict[str, Any], dict[str, str]]] = []
    for period in periods:
        row, units = by_period.get(period, ({}, {}))
        if not row or _extract_wind_metrics(row, units, period, str(row.get("记账本位币") or row.get("交易币种") or "")).get("revenue") is None:
            fallback_row, fallback_units = _fetch_wind_period_row(windcode, period, errors)
            row = {**row, **fallback_row}
            units = {**units, **fallback_units}
        rows.append((period, row, units))
    return rows


def _fetch_wind_bulk_rows(windcode: str, periods: list[str], errors: list[str] | None = None) -> list[tuple[str, dict[str, Any], dict[str, str]]]:
    if len(periods) < 2:
        return []
    suffix = f"{periods[0]}{periods[-1]}revenuegrossmarginoperatingmargin"
    try:
        result = wind_financial_query(windcode, suffix)
    except Exception as exc:
        if errors is not None:
            errors.append(f"{windcode}: {exc}")
        return []
    rows_with_units: list[tuple[str, dict[str, Any], dict[str, str]]] = []
    for table in parse_wind_tables(result):
        units = wind_units_by_column(table)
        for row in wind_rows_by_column(table):
            period = _period_from_wind_row(row) or ""
            if period:
                rows_with_units.append((period, row, units))
    return rows_with_units


def _fetch_wind_period_row(windcode: str, period: str, errors: list[str] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    suffixes = [
        f"{period}营业收入销售毛利率营业利润率营业利润营业成本净利润研发费用",
        f"{period}revenuegrossmarginoperatingmargin",
    ]
    merged_row: dict[str, Any] = {}
    merged_units: dict[str, str] = {}
    for suffix in suffixes:
        try:
            result = wind_financial_query(windcode, suffix)
        except Exception as exc:
            if errors is not None:
                errors.append(f"{windcode} {period}: {exc}")
            continue
        tables = parse_wind_tables(result)
        for table in tables:
            rows = wind_rows_by_column(table)
            if rows:
                merged_row.update(rows[0])
                merged_units.update(wind_units_by_column(table))
    return merged_row, merged_units


def _extract_wind_metrics(row: dict[str, Any], units: dict[str, str], period: str, currency: str) -> dict[str, dict[str, Any] | None]:
    revenue = _pick_numeric_column(row, units, include=["营业收入"], exclude=["总收入", "营业总收入", "成本"])
    if revenue is None:
        revenue = _pick_numeric_column(row, units, include=["总营业收入"], exclude=["成本"])
    if revenue is None:
        revenue = _pick_numeric_column(row, units, include=["营业总收入"], exclude=["成本"])

    gross_profit = _pick_numeric_column(row, units, include=["毛利润"], exclude=["毛利率", "毛利"])
    if gross_profit is None:
        gross_profit = _pick_numeric_column(row, units, include=["毛利额"], exclude=["毛利率", "毛利"])
    cost = _pick_numeric_column(row, units, include=["营业成本"], exclude=["总成本"])
    if gross_profit is None and revenue and cost:
        gross_profit = {
            "column": f"{period}营业收入-营业成本",
            "unit": revenue["unit"],
            "value": float(revenue["value"]) - float(cost["value"]),
        }

    operating_income = _pick_numeric_column(row, units, include=["营业利润"], exclude=["营业利润率"])
    net_income = _pick_numeric_column(row, units, include=["净利润"], exclude=["净利率", "ROE", "ROA"])
    rd_expense = _pick_numeric_column(row, units, include=["研发费用"], exclude=["占比", "率"])
    cash_from_operations = _pick_numeric_column(row, units, include=["经营活动产生的现金流量净额"], exclude=[])
    if cash_from_operations is None:
        cash_from_operations = _pick_numeric_column(row, units, include=["经营性现金流"], exclude=["率"])
    if cash_from_operations is None:
        cash_from_operations = _pick_numeric_column(row, units, include=["经营现金流"], exclude=["率"])
    capex = _pick_numeric_column(row, units, include=["购建固定资产"], exclude=[])
    if capex is None:
        capex = _pick_numeric_column(row, units, include=["资本开支"], exclude=["率", "占比"])
    gross_margin = _pick_numeric_column(row, units, include=["毛利率"], exclude=[])
    if gross_margin is None:
        gross_margin = _pick_ratio_column(row, units, include=["毛利"], exclude=["毛利润", "毛利额"])
    operating_margin = _pick_numeric_column(row, units, include=["营业利润率"], exclude=[])
    if operating_margin is None:
        operating_margin = _pick_numeric_column(row, units, include=["营业利润/营业总收入"], exclude=[])
    rd_intensity = _pick_numeric_column(row, units, include=["研发费用占收入", "研发费用率"], exclude=[])

    return {
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "rd_expense": rd_expense,
        "cash_from_operations": cash_from_operations,
        "capex": capex,
        "gross_margin": _as_percent_metric(gross_margin, period, "销售毛利率") if gross_margin else None,
        "operating_margin": _as_percent_metric(operating_margin, period, "营业利润率") if operating_margin else None,
        "rd_intensity": _as_percent_metric(rd_intensity, period, "研发费用占收入") if rd_intensity else None,
    }


def _pick_numeric_column(row: dict[str, Any], units: dict[str, str], include: list[str], exclude: list[str]) -> dict[str, Any] | None:
    preferred: list[tuple[int, str, float]] = []
    for name, value in row.items():
        if not _is_number(value):
            continue
        if not all(token in name for token in include):
            continue
        if any(token in name for token in exclude):
            continue
        score = 0
        if name.startswith(("202", "201")):
            score += 2
        if "单季度" in name:
            score += 1
        if "营业收入" in name and "总" not in name:
            score += 2
        preferred.append((score, name, float(value)))
    if not preferred:
        return None
    _, name, value = sorted(preferred, reverse=True)[0]
    return {"column": name, "unit": units.get(name, ""), "value": value}


def _pick_ratio_column(row: dict[str, Any], units: dict[str, str], include: list[str], exclude: list[str]) -> dict[str, Any] | None:
    for name, value in row.items():
        if not _is_number(value):
            continue
        if not all(token in name for token in include):
            continue
        if any(token in name for token in exclude):
            continue
        unit = units.get(name, "")
        numeric_value = float(value)
        if unit == "%" or abs(numeric_value) <= 1:
            return {"column": name, "unit": unit or "ratio", "value": numeric_value}
    return None


def _as_percent_metric(value: dict[str, Any], period: str, label: str) -> dict[str, Any]:
    numeric_value = float(value["value"])
    if value.get("unit") != "%" and abs(numeric_value) <= 1:
        numeric_value *= 100
    return {"column": value.get("column") or f"{period}{label}", "unit": "%", "value": numeric_value}


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def _period_from_wind_row(row: dict[str, Any]) -> str:
    value = str(row.get("日期") or row.get("报告期") or row.get("时间") or "").strip()
    match = re.search(r"Q([1-4])\s*FY\s*(20\d{2})", value, flags=re.I)
    if match:
        return f"{match.group(2)}Q{match.group(1)}"
    match = re.search(r"(20\d{2})\s*Q([1-4])", value, flags=re.I)
    if match:
        return f"{match.group(1)}Q{match.group(2)}"
    return ""


def _needs_wind_financials(company: CompanyProfile, series: dict[str, MetricSeries]) -> bool:
    if not company.is_public or not is_wind_available():
        return False
    if not series:
        return True
    text = f"{company.ticker} {company.market} {company.name}".casefold()
    is_china_or_hk = any(token in text for token in ["china", "hong kong", "a股", "港股", "中芯", "smic"])
    has_revenue = bool(series.get("revenue") and series["revenue"].points)
    has_margin = bool(series.get("gross_margin") and series["gross_margin"].points)
    return is_china_or_hk and not (has_revenue and has_margin)


def _windcode_candidates(company: CompanyProfile) -> list[str]:
    raw_values = [company.ticker, company.local_code, *company.aliases]
    candidates: list[str] = []
    for value in raw_values:
        windcode = normalize_windcode(str(value))
        if _looks_like_windcode(windcode) and windcode not in candidates:
            candidates.append(windcode)
        for inferred in _infer_windcodes_from_market(company, str(value)):
            if inferred not in candidates:
                candidates.append(inferred)
    return candidates


def _infer_windcodes_from_market(company: CompanyProfile, value: str) -> list[str]:
    code = (value or "").strip().upper()
    if not code or "." in code or not re.fullmatch(r"[A-Z0-9]{1,8}", code):
        return []
    text = f"{company.market} {company.exchange} {company.country}".casefold()
    suffixes: list[str] = []
    if "xetra" in text or "germany" in text or "德国" in text:
        suffixes.append(".DE")
    if "tse" in text or "japan" in text or "日本" in text:
        suffixes.append(".T")
    if "krx" in text or "korea" in text or "韩国" in text:
        suffixes.append(".KS")
    if "twse" in text or "taiwan" in text or "台湾" in text:
        suffixes.append(".TW")
    if "hkex" in text or "hong kong" in text or "港股" in text or "香港" in text:
        suffixes.append(".HK")
    return [normalize_windcode(f"{code}{suffix}") for suffix in suffixes if _looks_like_windcode(normalize_windcode(f"{code}{suffix}"))]


def _prefer_primary_series(primary: dict[str, MetricSeries], secondary: dict[str, MetricSeries]) -> dict[str, MetricSeries]:
    merged = dict(primary)
    for metric, series in secondary.items():
        existing = merged.get(metric)
        if not existing or len(series.points) > len(existing.points):
            merged[metric] = series
    return merged


def _series_uses_wind(series_by_metric: dict[str, MetricSeries]) -> bool:
    for series in series_by_metric.values():
        for point in series.points:
            if any(source.accession == "Wind MCP" for source in point.sources):
                return True
    return False


def _looks_like_windcode(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{1,8}\.(SH|SZ|BJ|HK|O|N|T|KS|KQ|TW|DE|F|L|PA|AS|SW)", value or ""))


def _recent_completed_quarters(count: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    if today.month <= 3:
        year, quarter = today.year - 1, 4
    elif today.month <= 6:
        year, quarter = today.year, 1
    elif today.month <= 9:
        year, quarter = today.year, 2
    else:
        year, quarter = today.year, 3
    periods: list[str] = []
    for _ in range(max(1, count)):
        periods.append(f"{year}Q{quarter}")
        quarter -= 1
        if quarter == 0:
            year -= 1
            quarter = 4
    return list(reversed(periods))


def _quarter_end_date(period: str) -> str:
    match = re.fullmatch(r"(\d{4})Q([1-4])", period)
    if not match:
        return period
    year = int(match.group(1))
    quarter = int(match.group(2))
    return {
        1: f"{year}-03-31",
        2: f"{year}-06-30",
        3: f"{year}-09-30",
        4: f"{year}-12-31",
    }[quarter]


def _wind_source(company: CompanyProfile, windcode: str, period: str, column: str, unit: str) -> FinancialSource:
    return FinancialSource(
        title=f"{company_display_name(company)} Wind fundamentals {period}",
        url="https://aifinmarket.wind.com.cn",
        accession="Wind MCP",
        form="Wind fundamentals",
        filed=period,
        concept=f"{windcode}:{column}",
        unit=unit,
    )


def _normalize_wind_value(value: float, unit: str) -> float:
    unit_text = (unit or "").strip()
    if unit_text == "%":
        return value
    if "万亿元" in unit_text:
        return value * 1_000_000_000_000
    if "亿元" in unit_text:
        return value * 100_000_000
    if "百万元" in unit_text or "百万" in unit_text:
        return value * 1_000_000
    if "万元" in unit_text:
        return value * 10_000
    if "千元" in unit_text:
        return value * 1_000
    return value


def _wind_unit_label(unit: str, currency: str) -> str:
    if unit == "%":
        return "percent"
    return currency or unit or "reported currency"


def _format_wind_value(value: float, unit: str, currency: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    label = currency or unit
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{label} {value / 1_000_000_000:.2f}bn"
    if absolute >= 1_000_000:
        return f"{label} {value / 1_000_000:.1f}m"
    return f"{label} {value:,.0f}".strip()


def _format_reported_value(value: float, unit: str) -> str:
    if unit == "percent":
        return f"{value:.1f}%"
    if unit == "CNY":
        absolute = abs(value)
        if absolute >= 100_000_000:
            return f"CNY {value / 100_000_000:.2f}亿"
        if absolute >= 10_000:
            return f"CNY {value / 10_000:.1f}万"
        return f"CNY {value:,.0f}"
    return _format_value(value, unit)


def _source_subtitle(points: list[FinancialDataPoint], fallback: str) -> str:
    if any(any(source.accession == "Wind MCP" for source in point.sources) for point in points):
        return "Latest quarters from Wind fundamentals and/or regulatory filings; click any point to inspect source metadata."
    return fallback


def _source_note_for_points(points: list[FinancialDataPoint]) -> str:
    has_wind = any(any(source.accession == "Wind MCP" for source in point.sources) for point in points)
    has_cninfo = any(any(source.accession == "CNINFO" for source in point.sources) for point in points)
    has_sec = any(any(source.accession and source.accession not in {"Wind MCP", "CNINFO"} for source in point.sources) for point in points)
    if has_wind and (has_sec or has_cninfo):
        return "Mixed regulatory filings and Wind fundamentals. Wind data source: 万得 Wind 金融数据服务."
    if has_wind:
        return WIND_SOURCE_NOTE
    if has_cninfo:
        return "巨潮资讯官方公告 PDF 表格提取；每个点保留公告链接、页码和表格行来源。"
    return "SEC XBRL companyfacts; each point links to the filing accession index."


def _axis_label(points: list[FinancialDataPoint]) -> str:
    units = {point.unit for point in points if point.unit and point.unit != "percent"}
    if not units:
        return "%"
    if len(units) == 1:
        return next(iter(units))
    return "Reported currency; not FX-normalized"


def _points_for_concepts(
    company: CompanyProfile,
    metric: str,
    concepts: list[str],
    us_gaap: dict[str, Any],
    quarter_count: int,
) -> list[FinancialDataPoint]:
    candidates: list[dict[str, Any]] = []
    all_items: list[dict[str, Any]] = []
    for concept in concepts:
        fact = us_gaap.get(concept)
        if not fact:
            continue
        units = fact.get("units", {})
        unit_name = "USD" if "USD" in units else next(iter(units), "")
        if not unit_name:
            continue
        concept_items = [{**item, "unit": unit_name, "concept": concept} for item in units.get(unit_name, [])]
        concept_candidates: list[dict[str, Any]] = []
        for item in concept_items:
            if _is_quarter_fact(item):
                concept_candidates.append(item)
        candidates.extend(concept_candidates)
        all_items.extend(concept_items)

    base_items = _normalize_to_quarter_items(candidates, all_items or candidates)
    unique: dict[str, dict[str, Any]] = {}
    for item in base_items:
        key = str(item.get("end", ""))
        if not key:
            continue
        existing = unique.get(key)
        if not existing or _quarter_item_score(item) > _quarter_item_score(existing):
            unique[key] = item
    quarter_items = _with_derived_q4(list(unique.values()), all_items or candidates)
    quarter_items = _dedupe_quarter_items(quarter_items)
    latest = sorted(quarter_items, key=lambda item: str(item.get("end", "")), reverse=True)[:quarter_count]
    points: list[FinancialDataPoint] = []
    for item in sorted(latest, key=lambda value: str(value.get("end", ""))):
        value = float(item.get("val") or 0)
        period = _period_label(item)
        source = _source_for_item(company, item, str(item.get("concept", "")))
        points.append(
            FinancialDataPoint(
                ticker=company.ticker,
                company=company.name,
                metric=metric,
                metric_label=METRIC_LABELS[metric],
                period=period,
                end_date=str(item.get("end") or ""),
                value=value,
                display_value=_format_value(value, str(item.get("unit") or "USD")),
                unit=str(item.get("unit") or "USD"),
                series=company.ticker,
                sources=[source],
            )
        )
    return points


def _normalize_to_quarter_items(candidates: list[dict[str, Any]], all_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    quarter_items: list[dict[str, Any]] = list(candidates)
    cumulative_by_fy: dict[str, dict[str, dict[str, Any]]] = {}
    for item in all_candidates:
        form = str(item.get("form", "")).upper()
        fp = str(item.get("fp") or "").upper()
        fy = str(item.get("fy") or "")
        start = str(item.get("start") or "")
        end = str(item.get("end") or "")
        if form not in {"10-Q", "6-K"} or fp not in {"Q1", "Q2", "Q3"} or not fy or not start or not end:
            continue
        duration = _duration_days(start, end)
        if (fp == "Q1" and 55 <= duration <= 115) or (fp in {"Q2", "Q3"} and 115 < duration <= 285):
            existing = cumulative_by_fy.setdefault(fy, {}).get(fp)
            if not existing or _quarter_item_score(item) > _quarter_item_score(existing):
                cumulative_by_fy[fy][fp] = item

    for fy, by_fp in cumulative_by_fy.items():
        q1 = by_fp.get("Q1")
        q2 = by_fp.get("Q2")
        q3 = by_fp.get("Q3")
        if q1:
            quarter_items.append(q1)
        if q1 and q2:
            quarter_items.append(_single_quarter_from_ytd(q2, float(q2.get("val") or 0) - float(q1.get("val") or 0), "Q2"))
        if q2 and q3:
            quarter_items.append(_single_quarter_from_ytd(q3, float(q3.get("val") or 0) - float(q2.get("val") or 0), "Q3"))

    return quarter_items


def _single_quarter_from_ytd(item: dict[str, Any], value: float, fp: str) -> dict[str, Any]:
    normalized = dict(item)
    normalized["val"] = value
    normalized["fp"] = fp
    normalized["derived_quarter"] = True
    return normalized


def _dedupe_quarter_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for item in items:
        end = str(item.get("end") or "")
        fp = str(item.get("fp") or "").upper()
        key = end or f"{item.get('fy')}:{fp}:{item.get('frame')}"
        existing = unique.get(key)
        if not existing or _quarter_item_score(item) > _quarter_item_score(existing):
            unique[key] = item
    return sorted(unique.values(), key=lambda item: str(item.get("end") or ""))


def _derived_margin_points(
    company: CompanyProfile,
    raw_metric_points: dict[str, list[FinancialDataPoint]],
    metric: str,
    numerator_metric: str,
    denominator_metric: str,
) -> list[FinancialDataPoint]:
    numerator = {point.end_date: point for point in raw_metric_points.get(numerator_metric, [])}
    denominator = {point.end_date: point for point in raw_metric_points.get(denominator_metric, [])}
    points: list[FinancialDataPoint] = []
    for end_date in sorted(set(numerator) & set(denominator)):
        revenue = denominator[end_date].value
        if not revenue:
            continue
        value = numerator[end_date].value / revenue * 100
        sources = [*numerator[end_date].sources, *denominator[end_date].sources]
        points.append(
            FinancialDataPoint(
                ticker=company.ticker,
                company=company.name,
                metric=metric,
                metric_label=METRIC_LABELS[metric],
                period=numerator[end_date].period,
                end_date=end_date,
                value=value,
                display_value=f"{value:.1f}%",
                unit="percent",
                series=company.ticker,
                sources=sources,
            )
        )
    return points


def _derived_free_cash_flow_points(
    company: CompanyProfile,
    raw_metric_points: dict[str, list[FinancialDataPoint]],
) -> list[FinancialDataPoint]:
    operating_cash = {point.end_date: point for point in raw_metric_points.get("cash_from_operations", [])}
    capex = {point.end_date: point for point in raw_metric_points.get("capex", [])}
    points: list[FinancialDataPoint] = []
    for end_date in sorted(set(operating_cash) & set(capex)):
        value = operating_cash[end_date].value - abs(capex[end_date].value)
        sources = [*operating_cash[end_date].sources, *capex[end_date].sources]
        points.append(
            FinancialDataPoint(
                ticker=company.ticker,
                company=company.name,
                metric="free_cash_flow",
                metric_label=METRIC_LABELS["free_cash_flow"],
                period=operating_cash[end_date].period,
                end_date=end_date,
                value=value,
                display_value=_format_value(value, operating_cash[end_date].unit or capex[end_date].unit),
                unit=operating_cash[end_date].unit or capex[end_date].unit,
                series=company.ticker,
                sources=sources,
            )
        )
    return points


def _latest_peer_points(all_series: dict[str, dict[str, MetricSeries]], metric: str) -> list[FinancialDataPoint]:
    points: list[FinancialDataPoint] = []
    for ticker, series_by_metric in all_series.items():
        series = series_by_metric.get(metric)
        if not series or not series.points:
            continue
        point = sorted(series.points, key=lambda item: item.end_date)[-1]
        points.append(point)
    return sorted(points, key=lambda point: point.value, reverse=True)


def _is_quarter_fact(item: dict[str, Any]) -> bool:
    form = str(item.get("form", "")).upper()
    frame = str(item.get("frame", ""))
    fp = str(item.get("fp", "")).upper()
    start = str(item.get("start", ""))
    end = str(item.get("end", ""))
    if form not in {"10-Q", "10-K", "20-F", "40-F", "6-K"}:
        return False
    if re.search(r"Q[1-4]$", frame):
        return True
    if fp in {"Q1", "Q2", "Q3"} and start and end and 55 <= _duration_days(start, end) <= 115:
        return True
    if fp == "FY" and start and end:
        return _duration_days(start, end) <= 115
    return False


def _duration_days(start: str, end: str) -> int:
    try:
        start_parts = [int(part) for part in start.split("-")]
        end_parts = [int(part) for part in end.split("-")]
        return (date(*end_parts) - date(*start_parts)).days
    except Exception:
        return 999


def _latest_end_date(items: list[dict[str, Any]]) -> str:
    return max((str(item.get("end") or "") for item in items), default="")


def _quarter_item_score(item: dict[str, Any]) -> tuple[int, int, str]:
    frame = str(item.get("frame") or "")
    start = str(item.get("start") or "")
    end = str(item.get("end") or "")
    duration = _duration_days(start, end) if start and end else 999
    has_explicit_quarter_frame = 1 if re.search(r"Q[1-4]$", frame) else 0
    has_single_quarter_duration = 1 if 55 <= duration <= 115 else 0
    filing_lag_score = -_filing_lag_days(item)
    return (filing_lag_score, has_single_quarter_duration, has_explicit_quarter_frame, str(item.get("filed") or ""))


def _filing_lag_days(item: dict[str, Any]) -> int:
    filed = str(item.get("filed") or "")
    end = str(item.get("end") or "")
    try:
        filed_date = _parse_date(filed)
        end_date = _parse_date(end)
        return max(0, (filed_date - end_date).days)
    except Exception:
        return 9999


def _parse_date(value: str) -> date:
    parts = [int(part) for part in value.split("-")]
    return date(*parts)


def _with_derived_q4(quarter_items: list[dict[str, Any]], all_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_fy_fp: dict[tuple[str, str], dict[str, Any]] = {}
    for item in quarter_items:
        fy = str(item.get("fy") or "")
        fp = str(item.get("fp") or "")
        if fy and fp:
            existing = by_fy_fp.get((fy, fp))
            if not existing or _quarter_item_score(item) > _quarter_item_score(existing):
                by_fy_fp[(fy, fp)] = item

    annual_items = [item for item in all_candidates if str(item.get("fp") or "").upper() == "FY" and _duration_days(str(item.get("start") or ""), str(item.get("end") or "")) > 300]
    derived: list[dict[str, Any]] = []
    for annual in annual_items:
        fy = str(annual.get("fy") or "")
        if not fy:
            continue
        q1, q2, q3 = by_fy_fp.get((fy, "Q1")), by_fy_fp.get((fy, "Q2")), by_fy_fp.get((fy, "Q3"))
        if not (q1 and q2 and q3):
            continue
        annual_value = float(annual.get("val") or 0)
        q4_value = annual_value - float(q1.get("val") or 0) - float(q2.get("val") or 0) - float(q3.get("val") or 0)
        if q4_value < 0:
            continue
        derived.append(
            {
                **annual,
                "val": q4_value,
                "fp": "Q4",
                "frame": f"FY{fy}Q4_DERIVED",
                "concept": annual.get("concept"),
                "unit": annual.get("unit"),
                "derived_note": "Derived as fiscal-year value minus Q1-Q3 single-quarter values.",
            }
        )
    return [*quarter_items, *derived]


def _period_label(item: dict[str, Any]) -> str:
    fy = item.get("fy") or ""
    fp = item.get("fp") or ""
    if fy and fp:
        return f"FY{fy} {fp}"
    frame = item.get("frame") or ""
    if frame:
        return str(frame).replace("CY", "")
    return str(item.get("end") or "")


def _source_for_item(company: CompanyProfile, item: dict[str, Any], concept: str) -> FinancialSource:
    accession = str(item.get("accn") or "")
    cik_int = str(int(company.cik)) if company.cik else ""
    accession_clean = accession.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_clean}/{accession}-index.html" if accession and cik_int else ""
    return FinancialSource(
        title=f"{company_display_name(company)} {item.get('form', '')} filed {item.get('filed', '')}",
        url=url,
        accession=accession,
        form=str(item.get("form") or ""),
        filed=str(item.get("filed") or ""),
        concept=concept,
        unit=str(item.get("unit") or ""),
    )


def _format_value(value: float, unit: str) -> str:
    if unit.lower() == "shares":
        return f"{value / 1_000_000:.1f}m shares"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}bn"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.1f}m"
    return f"${value:,.0f}" if unit == "USD" else f"{value:,.0f} {unit}"


def _trend_insight(ticker: str, metric: str, points: list[FinancialDataPoint]) -> str:
    if len(points) < 2:
        return f"{ticker} has one available data point for {METRIC_LABELS.get(metric, metric)}."
    first = points[0].value
    last = points[-1].value
    if not first:
        return f"{ticker} latest {METRIC_LABELS.get(metric, metric)} is {points[-1].display_value}."
    change = (last / first - 1) * 100
    direction = "increased" if change >= 0 else "decreased"
    return f"{ticker} {METRIC_LABELS.get(metric, metric)} {direction} {abs(change):.1f}% from {points[0].period} to {points[-1].period}."


def _peer_insight(metric: str, points: list[FinancialDataPoint]) -> str:
    if len(points) < 2:
        return ""
    leader = points[0]
    laggard = points[-1]
    return f"{point_display_name(leader)} is highest on latest available {METRIC_LABELS.get(metric, metric)} ({leader.display_value}); {point_display_name(laggard)} is lowest ({laggard.display_value})."
