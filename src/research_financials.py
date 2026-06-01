from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .research_models import CompanyProfile, FinancialChart, FinancialDataPoint, FinancialSource
from .utils import request_json


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
    public_companies = [company for company in companies if company.is_public and company.cik]
    for company in public_companies:
        try:
            all_series[company.ticker] = fetch_company_metric_series(company, quarter_count=quarter_count)
        except Exception as exc:
            notes.append(f"{company.ticker}: SEC companyfacts 财务数据抓取失败：{exc}")

    charts: list[FinancialChart] = []
    if not all_series:
        return charts, notes

    target = public_companies[0] if public_companies else companies[0]
    target_series = all_series.get(target.ticker, {})
    revenue_points = target_series.get("revenue", MetricSeries("revenue", METRIC_LABELS["revenue"], [])).points
    if revenue_points:
        charts.append(
            FinancialChart(
                chart_id="target_revenue_trend",
                title=f"{target.ticker} quarterly revenue trend",
                subtitle="Latest quarters from SEC XBRL; click any point/bar in the final interaction layer to inspect source filing.",
                chart_type="bar_line",
                y_axis="USD, normalized display",
                points=revenue_points,
                insight=_trend_insight(target.ticker, "revenue", revenue_points),
            )
        )

    for margin_metric in ["gross_margin", "operating_margin", "rd_intensity"]:
        points = target_series.get(margin_metric, MetricSeries(margin_metric, METRIC_LABELS[margin_metric], [])).points
        if points:
            charts.append(
                FinancialChart(
                    chart_id=f"target_{margin_metric}",
                    title=f"{target.ticker} {METRIC_LABELS[margin_metric]}",
                    subtitle="Derived from SEC XBRL income statement concepts; source links remain attached to the underlying revenue/profit concepts.",
                    chart_type="line",
                    y_axis="%",
                    points=points,
                    insight=_trend_insight(target.ticker, margin_metric, points),
                )
            )

    peer_revenue = _latest_peer_points(all_series, "revenue")
    if len(peer_revenue) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_revenue",
                title="Latest reported revenue: target vs selected public comparables",
                subtitle="Cross-sectional view over companies with available SEC XBRL data in this prototype.",
                chart_type="bar",
                y_axis="USD, normalized display",
                points=peer_revenue,
                insight=_peer_insight("revenue", peer_revenue),
            )
        )

    peer_gross_margin = _latest_peer_points(all_series, "gross_margin")
    if len(peer_gross_margin) >= 2:
        charts.append(
            FinancialChart(
                chart_id="peer_latest_gross_margin",
                title="Latest gross margin: target vs selected public comparables",
                subtitle="Gross margin is calculated as gross profit divided by revenue for the same reported period where available.",
                chart_type="bar",
                y_axis="%",
                points=peer_gross_margin,
                insight=_peer_insight("gross_margin", peer_gross_margin),
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
