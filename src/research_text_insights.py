from __future__ import annotations

import re
import warnings
from collections import Counter
from typing import Any

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from .research_anomalies import POSITIVE, RISK
from .research_models import EvidenceItem, ObjectiveAnomaly
from .utils import request_text


READABLE_TYPES = {"transcript", "presentation", "expert_memo", "external_signal", "web"}
UNREADABLE_SOURCES = {"Bing 定向搜索", "定向搜索入口", "Transcript 搜索建议", "平台入口", "搜索建议"}

THEME_RULES = [
    {
        "theme_id": "ai_capex",
        "title": "AI/算力资本开支成为管理层讨论重点",
        "polarity": RISK,
        "positive_terms": ["ai", "artificial intelligence", "gemini", "cloud", "tpu", "infrastructure", "data center", "capex", "capital expenditure", "servers"],
        "risk_terms": ["elevated", "increase", "capacity", "depreciation", "margin", "supply", "constraints", "investment"],
        "cn_terms": ["人工智能", "算力", "资本开支", "数据中心", "服务器", "折旧", "产能", "供给"],
        "deep_dive": "拆分 AI 收入增量、云收入增速、资本开支/折旧对利润率和自由现金流的压力，并与 Microsoft/Amazon/Meta 的 AI capex 节奏横向比较。",
    },
    {
        "theme_id": "ad_demand",
        "title": "广告需求和搜索商业化边际变化值得跟踪",
        "polarity": POSITIVE,
        "positive_terms": ["advertising", "search", "youtube", "retail", "brand", "performance", "monetization", "clicks", "conversion"],
        "risk_terms": ["weakness", "slowdown", "competitive", "pricing", "regulatory"],
        "cn_terms": ["广告", "搜索", "商业化", "转化", "零售", "品牌"],
        "deep_dive": "把广告收入、YouTube、搜索点击/转化、零售广告需求与 Meta/Amazon 广告业务增速横向对比，确认是否是行业共振还是公司特异变化。",
    },
    {
        "theme_id": "cloud_growth",
        "title": "云业务增长和 AI 需求需要与利润率一起验证",
        "polarity": POSITIVE,
        "positive_terms": ["cloud", "backlog", "remaining performance obligations", "enterprise", "workloads", "ai demand", "platform"],
        "risk_terms": ["margin", "capacity", "gpu", "supply", "competition", "pricing"],
        "cn_terms": ["云", "企业客户", "订单", "积压订单", "工作负载", "毛利率", "价格竞争"],
        "deep_dive": "同时检查云收入增速、运营利润率、订单/剩余履约义务和管理层对 AI workload 的描述，避免只看收入而忽略算力成本。",
    },
    {
        "theme_id": "regulatory_pressure",
        "title": "监管/反垄断风险仍需作为估值折价变量",
        "polarity": RISK,
        "positive_terms": ["regulatory", "regulation", "antitrust", "doj", "european commission", "privacy", "litigation", "remedies"],
        "risk_terms": ["risk", "uncertainty", "fine", "remedy", "appeal", "restriction"],
        "cn_terms": ["监管", "反垄断", "诉讼", "罚款", "整改", "隐私"],
        "deep_dive": "把监管案件进展、潜在整改措施与核心广告/搜索收入暴露度相连，区分一次性罚款和业务模式受限风险。",
    },
    {
        "theme_id": "cost_efficiency",
        "title": "成本效率/裁员/费用纪律可能改善利润弹性",
        "polarity": POSITIVE,
        "positive_terms": ["efficiency", "expense discipline", "headcount", "cost", "productivity", "operating leverage", "restructuring"],
        "risk_terms": ["severance", "restructuring", "investment", "depreciation"],
        "cn_terms": ["效率", "费用纪律", "降本", "裁员", "经营杠杆", "重组"],
        "deep_dive": "把管理层费用纪律表述与 operating margin、R&D/revenue、SG&A/revenue 的连续季度变化匹配，确认利润率提升是否可持续。",
    },
]


def enrich_readable_evidence(evidence: list[EvidenceItem], max_items: int = 16) -> tuple[list[EvidenceItem], list[str]]:
    notes: list[str] = []
    enriched = list(evidence)
    candidates = sorted(
        [
        (index, item)
        for index, item in enumerate(enriched)
        if item.evidence_type in READABLE_TYPES
        and not item.quote
        and _looks_fetchable(item)
        ],
        key=lambda pair: _readability_priority(pair[1]),
    )[:max_items]
    extracted = 0
    for index, item in candidates:
        text = _fetch_readable_text(item)
        if not text:
            continue
        quote = _representative_excerpt(text)
        if not quote:
            continue
        enriched[index] = EvidenceItem(**{**item.to_dict(), "quote": quote, "trace_type": item.trace_type or "webpage"})
        extracted += 1
    notes.append(f"正文读取器：尝试 {len(candidates)} 条网页/纪要证据，成功抽取 {extracted} 条可引用正文片段。")
    return enriched, notes


def build_text_theme_anomalies(evidence: list[EvidenceItem]) -> list[ObjectiveAnomaly]:
    anomalies: list[ObjectiveAnomaly] = []
    readable = [
        (index, item, f"{item.title}\n{item.quote}")
        for index, item in enumerate(evidence)
        if item.evidence_type in READABLE_TYPES and item.quote and not _is_search_entry(item)
    ]
    if not readable:
        return []
    for rule in THEME_RULES:
        matched: list[int] = []
        source_counter: Counter[str] = Counter()
        for index, item, text in readable:
            lowered = text.casefold()
            if _theme_hit(lowered, rule):
                matched.append(index)
                source_counter[item.source] += 1
        if not matched:
            continue
        confidence = "medium" if len(source_counter) >= 2 else "low"
        anomalies.append(
            ObjectiveAnomaly(
                anomaly_id=f"text:{rule['theme_id']}",
                polarity=str(rule["polarity"]),
                category="管理层/外部文字信号",
                title=str(rule["title"]),
                observation=f"在 {len(matched)} 条可读 transcript/presentation/外部资料正文中命中该主题；当前来源数 {len(source_counter)} 个，属于可进一步深挖的经营/行业信号。",
                comparison_basis="只统计已抽取 quote 的正文证据，不把搜索入口或资料数量本身作为投资信号。",
                magnitude=f"{len(matched)} 条正文命中 / {len(source_counter)} 个来源",
                confidence_tier=confidence,
                evidence_ids=matched[:8],
                suggested_deep_dive=str(rule["deep_dive"]),
            )
        )
    return anomalies


def _looks_fetchable(item: EvidenceItem) -> bool:
    if not item.url.startswith("http"):
        return False
    if _is_search_entry(item):
        return False
    lowered = item.url.casefold()
    if any(token in lowered for token in ["bing.com/search", "google.com/search", "weixin.sogou.com", "app.tikr.com", "koyfin.com/search", "bamsec.com/search", "quartr.com/search"]):
        return False
    if item.source in UNREADABLE_SOURCES:
        return False
    return True


def _readability_priority(item: EvidenceItem) -> tuple[int, int]:
    text = f"{item.source} {item.title} {item.url}".casefold()
    if item.evidence_type == "transcript" and any(token in text for token in ["fool.com/earnings", "stockanalysis.com", "marketbeat.com", "earningscall.biz"]):
        return (0, 0)
    if item.evidence_type == "transcript":
        return (1, 0)
    if item.evidence_type == "presentation":
        return (2, 0)
    if item.evidence_type in {"expert_memo", "external_signal"}:
        return (3, 0)
    return (4, 0)


def _is_search_entry(item: EvidenceItem) -> bool:
    text = f"{item.source} {item.trace_type} {item.url} {item.title}".casefold()
    return any(token in text for token in ["搜索", "search_entry", "search?q=", "bing.com/search", "google.com/search"])


def _fetch_readable_text(item: EvidenceItem) -> str:
    url = item.url
    try:
        html = request_text(url, timeout=12)
    except Exception:
        return ""
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()
    selectors = [
        "#transcript-panel-full",
        "div.article-body",
        "div.prose",
        "div.article-content",
        "section.article-body",
        "div.transcript-body",
        "div[itemprop='articleBody']",
        "article",
        "main",
    ]
    nodes = [soup.select_one(selector) for selector in selectors]
    nodes = [node for node in nodes if node]
    if not nodes:
        nodes = soup.find_all(["article", "main", "section", "div"])
    best_text = ""
    for node in nodes:
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        if len(text) > len(best_text):
            best_text = text
    if len(best_text) < 500:
        return ""
    if _looks_like_admin_filing_page(best_text) and not _has_business_discussion(best_text):
        return ""
    if item.evidence_type == "transcript" and not _has_transcript_markers(best_text):
        return ""
    if item.evidence_type == "presentation" and not _has_business_discussion(best_text):
        return ""
    return best_text[:12000]


def _representative_excerpt(text: str) -> str:
    sentences = re.split(r"(?<=[。.!?])\s+", text)
    keywords = [
        "ai",
        "artificial intelligence",
        "cloud",
        "advertising",
        "search",
        "youtube",
        "capex",
        "margin",
        "regulatory",
        "revenue",
        "人工智能",
        "云",
        "广告",
        "监管",
        "资本开支",
    ]
    selected = [sentence for sentence in sentences if any(keyword in sentence.casefold() for keyword in keywords) and len(sentence) > 40]
    if not selected:
        return ""
    excerpt = " ".join(selected[:4])
    return excerpt[:1200].strip()


def _theme_hit(lowered_text: str, rule: dict[str, Any]) -> bool:
    terms = [*rule.get("positive_terms", []), *rule.get("cn_terms", [])]
    risk_terms = rule.get("risk_terms", [])
    term_hits = sum(1 for term in terms if str(term).casefold() in lowered_text)
    risk_hits = sum(1 for term in risk_terms if str(term).casefold() in lowered_text)
    return term_hits >= 2 or (term_hits >= 1 and risk_hits >= 1)


def _looks_like_admin_filing_page(text: str) -> bool:
    lowered = text.casefold()
    return any(
        token in lowered
        for token in [
            "exact name of registrant",
            "commission file number",
            "securities exchange act of 1934",
            "indicate by check mark",
        ]
    )


def _has_business_discussion(text: str) -> bool:
    lowered = text.casefold()
    business_terms = [
        "revenue",
        "operating income",
        "margin",
        "capex",
        "capital expenditures",
        "cloud",
        "advertising",
        "search",
        "youtube",
        "ai",
        "artificial intelligence",
        "data center",
        "customers",
        "demand",
        "guidance",
        "营业收入",
        "毛利率",
        "资本开支",
        "人工智能",
        "客户",
        "需求",
    ]
    return sum(1 for term in business_terms if term in lowered) >= 2


def _has_transcript_markers(text: str) -> bool:
    lowered = text.casefold()
    markers = ["operator", "question-and-answer", "q&a", "prepared remarks", "earnings call", "conference call", "analyst"]
    return sum(1 for marker in markers if marker in lowered) >= 2
