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
    local_code: str = ""
    exchange: str = ""
    country: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def to_company_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "name_en": self.name,
            "market": self.market,
            "country": self.country or self.market,
            "local_code": self.local_code,
            "exchange": self.exchange,
            "cik": self.cik,
            "ir_url": self.ir_url,
            "source": self.source_hint or "AI research universe",
            "aliases": list(self.aliases),
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
    anomaly_ids: list[str] = field(default_factory=list)
    chart_hint: str = ""
    chart_reason: str = ""
    reasoning_summary: str = ""
    reasoning_chain: list[str] = field(default_factory=list)
    next_validation_actions: list[str] = field(default_factory=list)
    source_count: int = 0

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
    required: bool = False
    data_status: str = "available"
    missing_reason: str = ""
    expected_companies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["points"] = [point.to_dict() for point in self.points]
        return data


@dataclass
class ModelRunRecord:
    provider: str
    model: str
    purpose: str
    status: str
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    prompt_summary: str = ""
    output_summary: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationCheck:
    check_id: str
    category: str
    requirement: str
    status: str
    observed: str
    required: str
    severity: str = "must"
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationReport:
    status: str
    passed: int
    failed: int
    warning: int
    checks: list[ValidationCheck] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "failed": self.failed,
            "warning": self.warning,
            "checks": [check.to_dict() for check in self.checks],
        }


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
    objective_anomalies: list[ObjectiveAnomaly] = field(default_factory=list)
    model_runs: list[ModelRunRecord] = field(default_factory=list)
    validation_report: ValidationReport | None = None
    report_label: str = "原型草稿：未完成专业深度研究"
    run_notes: list[str] = field(default_factory=list)
    run_metadata: dict[str, Any] = field(default_factory=dict)

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
            "objective_anomalies": [anomaly.to_dict() for anomaly in self.objective_anomalies],
            "model_runs": [run.to_dict() for run in self.model_runs],
            "validation_report": self.validation_report.to_dict() if self.validation_report else None,
            "report_label": self.report_label,
            "run_notes": self.run_notes,
            "run_metadata": self.run_metadata,
        }
