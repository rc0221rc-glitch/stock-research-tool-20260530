from __future__ import annotations

from collections import Counter
from statistics import median

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .research_models import EvidenceItem, FinancialChart

try:
    from .research_models import ObjectiveAnomaly
except ImportError:
    @dataclass
    class ObjectiveAnomaly:
        anomaly_id: str
        polarity: str
        category: str
        title: str
        observation: str
        comparison_basis: str
        magnitude: str = ""
        metric: str = ""
        ticker: str = ""
        period: str = ""
        confidence_tier: str = "medium"
        source_refs: list[str] = field(default_factory=list)
        evidence_ids: list[int] = field(default_factory=list)
        chart_ids: list[str] = field(default_factory=list)
        suggested_deep_dive: str = ""
        selected_for_deep_dive: bool = False

        def to_dict(self) -> dict[str, object]:
            return {
                "anomaly_id": self.anomaly_id,
                "polarity": self.polarity,
                "category": self.category,
                "title": self.title,
                "observation": self.observation,
                "comparison_basis": self.comparison_basis,
                "magnitude": self.magnitude,
                "metric": self.metric,
                "ticker": self.ticker,
                "period": self.period,
                "confidence_tier": self.confidence_tier,
                "source_refs": self.source_refs,
                "evidence_ids": self.evidence_ids,
                "chart_ids": self.chart_ids,
                "suggested_deep_dive": self.suggested_deep_dive,
                "selected_for_deep_dive": self.selected_for_deep_dive,
            }


POSITIVE = "积极信号"
RISK = "风险信号"


def build_objective_anomalies(evidence: list[EvidenceItem], financial_charts: list[FinancialChart]) -> list[ObjectiveAnomaly]:
    anomalies: list[ObjectiveAnomaly] = []
    anomalies.extend(_financial_trend_anomalies(financial_charts))
    anomalies.extend(_peer_rank_anomalies(financial_charts))
    anomalies.extend(_evidence_coverage_anomalies(evidence))
    return _dedupe_anomalies(anomalies)[:40]


def selected_anomalies(anomalies: list[ObjectiveAnomaly], selected_ids: list[str]) -> list[ObjectiveAnomaly]:
    selected = set(selected_ids)
    return [anomaly for anomaly in anomalies if anomaly.anomaly_id in selected]


def anomaly_markdown(anomalies: list[ObjectiveAnomaly]) -> str:
    lines = ["# 客观异常扫描结果", ""]
    for polarity in [POSITIVE, RISK]:
        items = [anomaly for anomaly in anomalies if anomaly.polarity == polarity]
        lines.append(f"## {polarity}")
        if not items:
            lines.append("- 暂未发现。")
        for anomaly in items:
            lines.append(f"- **{anomaly.title}**")
            lines.append(f"  - 观察：{anomaly.observation}")
            lines.append(f"  - 对比依据：{anomaly.comparison_basis}")
            if anomaly.magnitude:
                lines.append(f"  - 幅度：{anomaly.magnitude}")
            if anomaly.source_refs:
                lines.append(f"  - 来源：{'; '.join(anomaly.source_refs[:3])}")
        lines.append("")
    return "\n".join(lines)


def _financial_trend_anomalies(charts: list[FinancialChart]) -> list[ObjectiveAnomaly]:
    anomalies: list[ObjectiveAnomaly] = []
    for chart in charts:
        if not chart.chart_id.startswith("target_") or len(chart.points) < 2:
            continue
        points = sorted(chart.points, key=lambda point: point.end_date)
        first, last = points[0], points[-1]
        if not first.value:
            continue
        change = (last.value / first.value - 1) * 100
        threshold = _trend_threshold(last.metric)
        if abs(change) < threshold:
            continue
        polarity = _trend_polarity(last.metric, change)
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id=f"trend:{chart.chart_id}:{last.ticker}:{last.metric}",
                polarity=polarity,
                category="纵向变化",
                title=f"{last.ticker} {last.metric_label} 连续窗口显著{'上升' if change >= 0 else '下降'}",
                observation=f"{last.metric_label} 从 {first.period} 的 {first.display_value} 变化至 {last.period} 的 {last.display_value}。",
                comparison_basis=f"目标公司自身最近 {len(points)} 个季度纵向对比。",
                magnitude=f"{change:+.1f}%",
                metric=last.metric,
                ticker=last.ticker,
                period=f"{first.period} → {last.period}",
                confidence_tier="official",
                source_refs=_source_refs(last),
                chart_ids=[chart.chart_id],
                suggested_deep_dive="进一步检查驱动项是否来自价格、销量/出货、产品结构、客户结构、费用率或一次性因素。",
            )
        )
    return anomalies


def _peer_rank_anomalies(charts: list[FinancialChart]) -> list[ObjectiveAnomaly]:
    anomalies: list[ObjectiveAnomaly] = []
    for chart in charts:
        if not chart.chart_id.startswith("peer_") or len(chart.points) < 3:
            continue
        points = sorted(chart.points, key=lambda point: point.value, reverse=True)
        values = [point.value for point in points]
        median_value = median(values)
        top = points[0]
        bottom = points[-1]
        for point, rank_label in [(top, "最高"), (bottom, "最低")]:
            if not median_value:
                continue
            diff = (point.value / median_value - 1) * 100
            if abs(diff) < _peer_threshold(point.metric):
                continue
            polarity = _peer_polarity(point.metric, rank_label)
            anomalies.append(
                ObjectiveAnomaly(
                    anomaly_id=f"peer:{chart.chart_id}:{point.ticker}:{point.metric}:{rank_label}",
                    polarity=polarity,
                    category="横向对比",
                    title=f"{point.ticker} {point.metric_label} 在可比组中{rank_label}",
                    observation=f"{point.period} 的 {point.metric_label} 为 {point.display_value}，在本组 {len(points)} 家公司中排名{rank_label}。",
                    comparison_basis=f"与同一可比组最新可得季度中位数对比。",
                    magnitude=f"较中位数 {diff:+.1f}%",
                    metric=point.metric,
                    ticker=point.ticker,
                    period=point.period,
                    confidence_tier="official",
                    source_refs=_source_refs(point),
                    chart_ids=[chart.chart_id],
                    suggested_deep_dive="进一步确认该横向差异是否由业务结构、会计口径、币种、周期位置或竞争优势/劣势造成。",
                )
            )
    return anomalies


def _evidence_coverage_anomalies(evidence: list[EvidenceItem]) -> list[ObjectiveAnomaly]:
    anomalies: list[ObjectiveAnomaly] = []
    by_type = Counter(item.evidence_type for item in evidence)
    by_tier = Counter(item.confidence_tier for item in evidence)
    if by_type.get("transcript", 0) >= 3:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:transcript-rich",
                polarity=POSITIVE,
                category="资料覆盖",
                title="业绩会纪要覆盖较充分",
                observation=f"当前找到 {by_type.get('transcript', 0)} 条 transcript 候选，具备做管理层措辞变化分析的基础。",
                comparison_basis="资料类型覆盖度客观统计。",
                magnitude=f"{by_type.get('transcript', 0)} 条 transcript",
                confidence_tier="medium",
                evidence_ids=_evidence_ids_by_type(evidence, "transcript")[:8],
                suggested_deep_dive="对同一公司连续季度和可比公司同季度的需求、价格、库存、客户、CapEx 关键词做变化分析。",
            )
        )
    expert_memo_ids = _expert_memo_evidence_ids(evidence)
    if len(expert_memo_ids) >= 2:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:wechat-expert-memo-rich",
                polarity=POSITIVE,
                category="高潜力外部线索",
                title="微信/中文专家交流纪要线索较多",
                observation=f"当前找到 {len(expert_memo_ids)} 条专家交流、产业链调研或渠道调研类候选，可能包含官方文件之外的需求、价格、库存和客户变化线索。",
                comparison_basis="微信公众号、雪球等中文投研平台候选证据统计。",
                magnitude=f"{len(expert_memo_ids)} 条专家/调研纪要线索",
                confidence_tier="platform",
                evidence_ids=expert_memo_ids[:8],
                suggested_deep_dive="逐条打开专家纪要，抽取具体观点和可验证事实，并至少用三类独立来源交叉验证：公司公告/财务数据、同行披露、产业链上下游或媒体报道。",
            )
        )
    elif by_type.get("transcript", 0) > 0 and len(expert_memo_ids) == 0:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:wechat-expert-memo-gap",
                polarity=RISK,
                category="资料缺口",
                title="专家交流/产业链调研纪要缺口明显",
                observation="虽然已有部分业绩会或纪要候选，但尚未识别到专家交流、产业链调研或渠道调研类线索。",
                comparison_basis="中文外部纪要关键词覆盖度客观统计。",
                confidence_tier="medium",
                suggested_deep_dive="补抓微信公众号、雪球、华尔街见闻、卖方纪要转载等来源中的专家交流纪要，再与官方披露交叉验证。",
            )
        )
    elif by_type.get("transcript", 0) == 0:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:transcript-gap",
                polarity=RISK,
                category="资料缺口",
                title="业绩会纪要缺口明显",
                observation="当前没有找到 transcript 候选，管理层措辞变化分析无法可靠展开。",
                comparison_basis="资料类型覆盖度客观统计。",
                confidence_tier="medium",
                suggested_deep_dive="优先补抓公司 IR、Seeking Alpha、Motley Fool、业绩会纪要平台和中文纪要来源。",
            )
        )
    if by_type.get("presentation", 0) == 0:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:presentation-gap",
                polarity=RISK,
                category="资料缺口",
                title="演示材料缺口明显",
                observation="当前没有找到 presentation 候选，分部经营数据、产品结构和管理层重点展示内容可能缺失。",
                comparison_basis="资料类型覆盖度客观统计。",
                confidence_tier="medium",
                suggested_deep_dive="优先补抓公司官网 IR、SEC 8-K/6-K 附件、交易所公告和 PDF 搜索结果。",
            )
        )
    if by_tier.get("official", 0) >= 8:
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id="evidence:official-rich",
                polarity=POSITIVE,
                category="来源质量",
                title="官方/监管来源覆盖较充分",
                observation=f"当前识别到 {by_tier.get('official', 0)} 条官方或监管来源候选，适合作为财务与经营事实底座。",
                comparison_basis="来源置信度分层客观统计。",
                magnitude=f"{by_tier.get('official', 0)} 条官方/监管证据",
                confidence_tier="official",
                evidence_ids=[index for index, item in enumerate(evidence) if item.confidence_tier == "official"][:8],
                suggested_deep_dive="优先从这些来源抽取表格、页码、单元格和管理层原文，作为最终 HTML 的可追溯证据。",
            )
        )
    return anomalies


def _trend_threshold(metric: str) -> float:
    if metric in {"gross_margin", "operating_margin", "rd_intensity"}:
        return 6.0
    return 20.0


def _peer_threshold(metric: str) -> float:
    if metric in {"gross_margin", "operating_margin", "rd_intensity"}:
        return 15.0
    return 35.0


def _trend_polarity(metric: str, change: float) -> str:
    if metric == "rd_intensity":
        return RISK if change > 0 else POSITIVE
    if metric in {"revenue", "gross_profit", "operating_income", "net_income", "gross_margin", "operating_margin"}:
        return POSITIVE if change > 0 else RISK
    return POSITIVE if change > 0 else RISK


def _peer_polarity(metric: str, rank_label: str) -> str:
    if metric == "rd_intensity":
        return RISK if rank_label == "最高" else POSITIVE
    return POSITIVE if rank_label == "最高" else RISK


def _source_refs(point: object) -> list[str]:
    sources = getattr(point, "sources", []) or []
    refs = []
    for source in sources:
        concept = getattr(source, "concept", "")
        accession = getattr(source, "accession", "")
        url = getattr(source, "url", "")
        refs.append(" · ".join(part for part in [concept, accession, url] if part))
    return refs


def _evidence_ids_by_type(evidence: list[EvidenceItem], evidence_type: str) -> list[int]:
    return [index for index, item in enumerate(evidence) if item.evidence_type == evidence_type]


def _expert_memo_evidence_ids(evidence: list[EvidenceItem]) -> list[int]:
    keywords = ["专家交流", "专家电话", "专家会议", "行业专家", "产业链专家", "渠道调研", "草根调研", "专家访谈"]
    ids: list[int] = []
    for index, item in enumerate(evidence):
        text = f"{item.title} {item.source} {item.url} {item.confidence_reason}"
        if item.evidence_type == "expert_memo" or (item.evidence_type == "transcript" and any(keyword in text for keyword in keywords)):
            ids.append(index)
    return ids


def _dedupe_anomalies(anomalies: list[ObjectiveAnomaly]) -> list[ObjectiveAnomaly]:
    seen: set[str] = set()
    deduped: list[ObjectiveAnomaly] = []
    for anomaly in anomalies:
        if anomaly.anomaly_id in seen:
            continue
        seen.add(anomaly.anomaly_id)
        deduped.append(anomaly)
    return sorted(deduped, key=lambda item: (0 if item.polarity == POSITIVE else 1, item.category, item.title))
