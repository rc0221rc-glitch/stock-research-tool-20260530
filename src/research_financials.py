from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .research_models import CompanyProfile, FinancialChart, FinancialDataPoint, FinancialSource
from .utils import request_json
from .wind_client import WIND_SOURCE_NOTE, is_wind_available, normalize_windcode, parse_wind_tables, wind_financial_query, wind_rows_by_column, wind_units_by_column


METRIC_CONCEPTS: dict[str, list[str]] = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "rd_expense": ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
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
}


@dataclass
class MetricSeries:
    metric: str
    label: str
    points: list[FinancialDataPoint]


def build_financial_charts(companies: list[CompanyProfile], quarter_count: int = 4) -> tuple[list[FinancialChart], list[str]]:
    notes: list[str] = []
    all_series: dict[str, dict[str, MetricSeries]] = {}
    public_companies = [company for company in companies if company.is_public]
    for company in public_companies:
        company_series: dict[str, MetricSeries] = {}
        if company.cik:
            try:
                company_series = fetch_company_metric_series(company, quarter_count=quarter_count)
            except Exception as exc:
                notes.append(f"{company.ticker}: SEC companyfacts 财务数据抓取失败：{exc}")
        if _needs_wind_financials(company, company_series):
            try:
                wind_series = fetch_wind_metric_series(company, quarter_count=quarter_count)
                company_series = _prefer_primary_series(company_series, wind_series)
            except Exception as exc:
                if is_wind_available():
                    notes.append(f"{company.ticker}: Wind 财务数据抓取失败：{exc}")
        if company_series:
            all_series[company.ticker] = company_series

    if is_wind_available() and any(_series_uses_wind(series) for series in all_series.values()):
        notes.append(WIND_SOURCE_NOTE)

    charts: list[FinancialChart] = []
    if not all_series:
        return charts, notes

    target = public_companies[0] if public_companies else companies[0]
    target_series = all_series.get(target.ticker, {})
    if not target_series and all_series:
        target_series = next(iter(all_series.values()))
    revenue_points = target_series.get("revenue", MetricSeries("revenue", METRIC_LABELS["revenue"], [])).points
    if revenue_points:
        charts.append(
            FinancialChart(
                chart_id="target_revenue_trend",
                title=f"{target.ticker} quarterly revenue trend",
                subtitle=_source_subtitle(revenue_points, "Latest quarters from audited filings / Wind fundamentals; click any point to inspect source metadata."),
                chart_type="bar_line",
                y_axis=_axis_label(revenue_points),
                points=revenue_points,
                insight=_trend_insight(target.ticker, "revenue", revenue_points),
                source_note=_source_note_for_points(revenue_points),
            )
        )

    for margin_metric in ["gross_margin", "operating_margin", "rd_intensity"]:
        points = target_series.get(margin_metric, MetricSeries(margin_metric, METRIC_LABELS[margin_metric], [])).points
        if points:
            charts.append(
                FinancialChart(
                    chart_id=f"target_{margin_metric}",
                    title=f"{target.ticker} {METRIC_LABELS[margin_metric]}",
                    subtitle=_source_subtitle(points, "Derived from reported income statement fields; source links remain attached to the underlying metrics."),
                    chart_type="line",
                    y_axis="%",
                    points=points,
                    insight=_trend_insight(target.ticker, margin_metric, points),
                    source_note=_source_note_for_points(points),
                )
            )

    peer_revenue = _latest_peer_points(all_series, "revenue")
    if len(peer_revenue) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_revenue",
                title="Latest reported revenue: target vs selected public comparables",
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
                title="Latest gross margin: target vs selected public comparables",
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
                title="Latest operating margin: target vs selected public comparables",
                subtitle="Operating margin is calculated as operating income divided by revenue for the same reported period where available.",
                chart_type="bar",
                y_axis="%",
                points=peer_operating_margin,
                insight=_peer_insight("operating_margin", peer_operating_margin),
                source_note=_source_note_for_points(peer_operating_margin),
            )
        )
    return charts, notes


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
    return series


def fetch_wind_metric_series(company: CompanyProfile, quarter_count: int = 4) -> dict[str, MetricSeries]:
    windcode = normalize_windcode(company.ticker)
    if not _looks_like_windcode(windcode):
        return {}
    periods = _recent_completed_quarters(quarter_count)
    raw_metric_points: dict[str, list[FinancialDataPoint]] = {}
    for period, row, units in _fetch_wind_period_rows(windcode, periods):
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
    return series


def _fetch_wind_period_rows(windcode: str, periods: list[str]) -> list[tuple[str, dict[str, Any], dict[str, str]]]:
    bulk_rows = _fetch_wind_bulk_rows(windcode, periods)
    by_period = {period: (row, units) for period, row, units in bulk_rows}
    rows: list[tuple[str, dict[str, Any], dict[str, str]]] = []
    for period in periods:
        row, units = by_period.get(period, ({}, {}))
        if not row or _extract_wind_metrics(row, units, period, str(row.get("记账本位币") or row.get("交易币种") or "")).get("revenue") is None:
            fallback_row, fallback_units = _fetch_wind_period_row(windcode, period)
            row = {**row, **fallback_row}
            units = {**units, **fallback_units}
        rows.append((period, row, units))
    return rows


def _fetch_wind_bulk_rows(windcode: str, periods: list[str]) -> list[tuple[str, dict[str, Any], dict[str, str]]]:
    if len(periods) < 2:
        return []
    suffix = f"{periods[0]}{periods[-1]}revenuegrossmarginoperatingmargin"
    try:
        result = wind_financial_query(windcode, suffix)
    except Exception:
        return []
    rows_with_units: list[tuple[str, dict[str, Any], dict[str, str]]] = []
    for table in parse_wind_tables(result):
        units = wind_units_by_column(table)
        for row in wind_rows_by_column(table):
            period = _period_from_wind_row(row) or ""
            if period:
                rows_with_units.append((period, row, units))
    return rows_with_units


def _fetch_wind_period_row(windcode: str, period: str) -> tuple[dict[str, Any], dict[str, str]]:
    suffixes = [
        f"{period}营业收入销售毛利率营业利润率营业利润营业成本净利润研发费用",
        f"{period}revenuegrossmarginoperatingmargin",
    ]
    merged_row: dict[str, Any] = {}
    merged_units: dict[str, str] = {}
    for suffix in suffixes:
        try:
            result = wind_financial_query(windcode, suffix)
        except Exception:
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

    gross_profit = _pick_numeric_column(row, units, include=["毛利"], exclude=["毛利率"])
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
    gross_margin = _pick_numeric_column(row, units, include=["毛利率"], exclude=[])
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


def _as_percent_metric(value: dict[str, Any], period: str, label: str) -> dict[str, Any]:
    return {"column": value.get("column") or f"{period}{label}", "unit": "%", "value": value["value"]}


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
    return bool(re.fullmatch(r"[A-Z0-9]{1,8}\.(SH|SZ|BJ|HK|O|N)", value or ""))


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
        title=f"{company.ticker} Wind fundamentals {period}",
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


def _source_subtitle(points: list[FinancialDataPoint], fallback: str) -> str:
    if any(any(source.accession == "Wind MCP" for source in point.sources) for point in points):
        return "Latest quarters from Wind fundamentals and/or regulatory filings; click any point to inspect source metadata."
    return fallback


def _source_note_for_points(points: list[FinancialDataPoint]) -> str:
    has_wind = any(any(source.accession == "Wind MCP" for source in point.sources) for point in points)
    has_sec = any(any(source.accession and source.accession != "Wind MCP" for source in point.sources) for point in points)
    if has_wind and has_sec:
        return "Mixed SEC XBRL companyfacts and Wind fundamentals. Wind data source: 万得 Wind 金融数据服务."
    if has_wind:
        return WIND_SOURCE_NOTE
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
    concept_used = ""
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
        if concept_candidates and _latest_end_date(concept_candidates) >= _latest_end_date(candidates):
            candidates = concept_candidates
            all_items = concept_items
            concept_used = concept
        if candidates and _latest_end_date(candidates) >= "2023-01-01":
            break

    unique: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = str(item.get("end", ""))
        if not key:
            continue
        existing = unique.get(key)
        if not existing or _quarter_item_score(item) > _quarter_item_score(existing):
            unique[key] = item
    quarter_items = _with_derived_q4(list(unique.values()), all_items if "all_items" in locals() else candidates)
    latest = sorted(quarter_items, key=lambda item: str(item.get("end", "")), reverse=True)[:quarter_count]
    points: list[FinancialDataPoint] = []
    for item in sorted(latest, key=lambda value: str(value.get("end", ""))):
        value = float(item.get("val") or 0)
        period = _period_label(item)
        source = _source_for_item(company, item, concept_used or str(item.get("concept", "")))
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


def _latest_peer_points(all_series: dict[str, dict[str, MetricSeries]], metric: str) -> list[FinancialDataPoint]:
    points: list[FinancialDataPoint] = []
    for ticker, series_by_metric in all_series.items():
        series = series_by_metric.get(metric)
        if not series or not series.points:
            continue
        point = series.points[-1]
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
        title=f"{company.ticker} {item.get('form', '')} filed {item.get('filed', '')}",
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
    return f"{leader.ticker} is highest on latest available {METRIC_LABELS.get(metric, metric)} ({leader.display_value}); {laggard.ticker} is lowest ({laggard.display_value})."
