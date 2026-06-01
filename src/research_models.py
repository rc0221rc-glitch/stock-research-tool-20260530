from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    market: str
    role: str
    segment: str
    description: str = ""
    cik: str = ""
    ir_url: str = ""
    is_public: bool = True
    source_hint: str = ""

    def to_company_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "name_en": self.name,
            "market": self.market,
            "country": self.market,
            "cik": self.cik,
            "ir_url": self.ir_url,
            "source": self.source_hint or "AI research universe",
        }


@dataclass
class ComparableGroup:
    group_id: str
    title: str
    purpose: str
    selection_logic: str
    companies: list[CompanyProfile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["companies"] = [asdict(company) for company in self.companies]
        return data


@dataclass
class EvidenceItem:
    title: str
    url: str
    source: str
    company: str = ""
    ticker: str = ""
    evidence_type: str = ""
    period: str = ""
    date: str = ""
    confidence_tier: str = "medium"
    confidence_reason: str = ""
    trace_type: str = "link"
    quote: str = ""
    page: str = ""
    cell_reference: str = ""
    screenshot_path: str = ""
    is_user_provided: bool = False
    access_scope: str = "public"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SignalScore:
    importance: int
    evidence_strength: int
    novelty: int
    investment_relevance: int
    time_sensitivity: int
    actionability: int

    @property
    def total(self) -> int:
        return (
            self.importance
            + self.evidence_strength
            + self.novelty
            + self.investment_relevance
            + self.time_sensitivity
            + self.actionability
        )

    def to_dict(self) -> dict[str, int]:
        data = asdict(self)
        data["total"] = self.total
        return data


@dataclass
class ResearchSignal:
    title: str
    conclusion: str
    signal_type: str
    status: str
    score: SignalScore
    evidence_ids: list[int] = field(default_factory=list)
    chart_hint: str = ""
    chart_reason: str = ""
    reasoning_summary: str = ""
    reasoning_chain: list[str] = field(default_factory=list)
    next_validation_actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = self.score.to_dict()
        return data


@dataclass
class AuditFinding:
    topic: str
    status: str
    finding: str
    severity: str = "info"
    related_evidence_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinancialSource:
    title: str
    url: str
    accession: str = ""
    form: str = ""
    filed: str = ""
    concept: str = ""
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FinancialDataPoint:
    ticker: str
    company: str
    metric: str
    metric_label: str
    period: str
    end_date: str
    value: float
    display_value: str
    unit: str
    series: str = ""
    sources: list[FinancialSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = [source.to_dict() for source in self.sources]
        return data


@dataclass
class FinancialChart:
    chart_id: str
    title: str
    subtitle: str
    chart_type: str
    y_axis: str
    points: list[FinancialDataPoint] = field(default_factory=list)
    insight: str = ""
    source_note: str = "SEC XBRL companyfacts; each point links to the filing accession index."

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["points"] = [point.to_dict() for point in self.points]
        return data


@dataclass
class ResearchDraft:
    target: CompanyProfile
    quarter_count: int
    comparable_groups: list[ComparableGroup]
    evidence: list[EvidenceItem]
    signals: list[ResearchSignal]
    audit_findings: list[AuditFinding]
    next_fetch_plan: list[str]
    generated_at: str
    financial_charts: list[FinancialChart] = field(default_factory=list)
    run_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": asdict(self.target),
            "quarter_count": self.quarter_count,
            "comparable_groups": [group.to_dict() for group in self.comparable_groups],
            "evidence": [item.to_dict() for item in self.evidence],
            "signals": [signal.to_dict() for signal in self.signals],
            "audit_findings": [finding.to_dict() for finding in self.audit_findings],
            "next_fetch_plan": self.next_fetch_plan,
            "generated_at": self.generated_at,
            "financial_charts": [chart.to_dict() for chart in self.financial_charts],
            "run_notes": self.run_notes,
        }
