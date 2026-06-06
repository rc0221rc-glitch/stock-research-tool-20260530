from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .research_models import CompanyProfile, ComparableGroup, EvidenceItem, FinancialChart, ModelRunRecord, ObjectiveAnomaly, ResearchSignal, SignalScore


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-v4-pro"
QWEAPI_BASE_URL = "https://qweapi.com"
ANTHROPIC_TOP_MODEL = "claude-opus-4-8"
OPENAI_TOP_MODEL = "gpt-5.5"
QWEAPI_DEFAULT_MODEL = ANTHROPIC_TOP_MODEL
QWEAPI_GPT_MODEL = OPENAI_TOP_MODEL
PROVIDER_MODEL_OPTIONS: dict[str, list[str]] = {
    "deepseek": [DEEPSEEK_MODEL, "deepseek-r1", "deepseek-v3.2"],
    "anthropic": [ANTHROPIC_TOP_MODEL, "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6"],
    "openai": [OPENAI_TOP_MODEL, "gpt-5.4", "gpt-5.3-codex"],
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str

    @property
    def chat_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/v1/chat/completions"


def resolve_llm_provider_config(
    explicit_key: str = "",
    *,
    provider: str = "",
    model: str = "",
    base_url: str = "",
) -> LLMProviderConfig:
    provider = _normalize_provider(provider or _read_config_value("LLM_PROVIDER") or "anthropic")
    if provider in {"anthropic", "openai", "qweapi"}:
        default_model = _default_model_for_provider(provider)
        return LLMProviderConfig(
            provider=provider,
            base_url=(base_url or _read_config_value("QWEAPI_BASE_URL") or QWEAPI_BASE_URL).strip(),
            model=(model or _model_config_value_for_provider(provider) or default_model).strip(),
            api_key=(
                explicit_key.strip()
                or _api_key_config_value_for_provider(provider)
                or _read_config_value("OPENAI_API_KEY")
            ),
        )
    return LLMProviderConfig(
        provider="deepseek",
        base_url=(base_url or _read_config_value("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL).strip(),
        model=(model or _read_config_value("DEEPSEEK_MODEL") or DEEPSEEK_MODEL).strip(),
        api_key=explicit_key.strip() or _read_config_value("DEEPSEEK_API_KEY"),
    )


def llm_key_status(explicit_key: str = "", *, provider: str = "qweapi") -> dict[str, bool]:
    provider = _normalize_provider(provider or "anthropic")
    names = _api_key_names_for_provider(provider)
    return {
        "ui": bool(explicit_key.strip()),
        "streamlit_secrets": any(bool(_read_streamlit_secret(name)) for name in names),
        "process_env": any(bool(os.getenv(name, "").strip()) for name in names),
        "local_env": any(bool(_read_local_env_secret(name)) for name in names),
    }


def _normalize_provider(provider: str) -> str:
    normalized = (provider or "").strip().lower().replace("-", "_")
    if normalized in {"qwe", "qweapi", "openai_compatible"}:
        return "anthropic"
    if normalized in {"claude", "anthropic"}:
        return "anthropic"
    if normalized in {"openai", "gpt"}:
        return "openai"
    if normalized in {"deepseek", "deep_seek"}:
        return "deepseek"
    return "anthropic"


def _default_model_for_provider(provider: str) -> str:
    return PROVIDER_MODEL_OPTIONS.get(provider, [ANTHROPIC_TOP_MODEL])[0]


def _api_key_names_for_provider(provider: str) -> list[str]:
    if provider == "deepseek":
        return ["DEEPSEEK_API_KEY"]
    if provider == "openai":
        return ["QWEAPI_API_KEY", "OPENAI_QWEAPI_API_KEY", "OPENAI_API_KEY"]
    return ["QWEAPI_API_KEY", "ANTHROPIC_QWEAPI_API_KEY", "ANTHROPIC_API_KEY"]


def _api_key_config_value_for_provider(provider: str) -> str:
    for name in _api_key_names_for_provider(provider):
        value = _read_config_value(name)
        if value:
            return value
    return ""


def _model_config_value_for_provider(provider: str) -> str:
    names = {
        "deepseek": ["DEEPSEEK_MODEL"],
        "openai": ["OPENAI_QWEAPI_MODEL"],
        "anthropic": ["ANTHROPIC_QWEAPI_MODEL"],
    }.get(provider, [])
    for name in names:
        value = _read_config_value(name)
        if value:
            return value
    return ""


def test_llm_connection(config: LLMProviderConfig, timeout: int = 30) -> tuple[bool, str]:
    if not config.api_key:
        return False, f"{config.provider} API key is missing"
    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": '请只返回一个 JSON 对象：{"ok":true}',
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 80,
    }
    try:
        response, mode, notes = _post_chat_completion(config, payload, timeout)
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return True, f"连接成功：provider={config.provider}; model={data.get('model') or config.model}; mode={mode}; notes={'; '.join(notes) or 'none'}; sample={content[:120]}"
    except Exception as exc:
        return False, str(exc)


def resolve_deepseek_api_key(explicit_key: str = "") -> str:
    return resolve_llm_provider_config(explicit_key, provider="deepseek").api_key


def deepseek_key_status(explicit_key: str = "") -> dict[str, bool]:
    return llm_key_status(explicit_key, provider="deepseek")


def generate_deepseek_research_signals(
    *,
    api_key: str,
    target_name: str,
    quarter_count: int,
    comparable_groups: list[ComparableGroup],
    evidence: list[EvidenceItem],
    financial_charts: list[FinancialChart],
    selected_anomalies: list[ObjectiveAnomaly] | None = None,
    fallback_signals: list[ResearchSignal],
    timeout: int = 180,
) -> tuple[list[ResearchSignal], list[str], ModelRunRecord]:
    config = resolve_llm_provider_config(api_key, provider="deepseek")
    return generate_llm_research_signals(
        config=config,
        target_name=target_name,
        quarter_count=quarter_count,
        comparable_groups=comparable_groups,
        evidence=evidence,
        financial_charts=financial_charts,
        selected_anomalies=selected_anomalies,
        fallback_signals=fallback_signals,
        timeout=timeout,
    )


def generate_llm_research_signals(
    *,
    config: LLMProviderConfig,
    target_name: str,
    quarter_count: int,
    comparable_groups: list[ComparableGroup],
    evidence: list[EvidenceItem],
    financial_charts: list[FinancialChart],
    selected_anomalies: list[ObjectiveAnomaly] | None = None,
    fallback_signals: list[ResearchSignal],
    timeout: int = 180,
) -> tuple[list[ResearchSignal], list[str], ModelRunRecord]:
    started = datetime.now()
    start = time.monotonic()
    run = ModelRunRecord(
        provider=config.provider,
        model=config.model,
        purpose="Deep-analyze user-selected objective anomalies using collected financial charts, comparables, and source evidence.",
        status="attempted",
        started_at=started.strftime("%Y-%m-%d %H:%M:%S"),
        prompt_summary=f"target={target_name}; quarters={quarter_count}; evidence={len(evidence)}; charts={len(financial_charts)}",
    )
    try:
        payload = _with_model(_build_payload(target_name, quarter_count, comparable_groups, evidence, financial_charts, selected_anomalies or [], fallback_signals), config.model)
        response, compatibility_mode, retry_notes = _post_chat_completion(config, payload, timeout)
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed, parse_note = _parse_or_repair_json_object(config, content, timeout)
        signals = _signals_from_payload(parsed, evidence)
        next_plan_raw = parsed.get("next_fetch_plan", [])
        next_plan = [str(item) for item in (next_plan_raw if isinstance(next_plan_raw, list) else []) if str(item).strip()]
        signals, next_plan, contract_note = _ensure_signal_contract(
            config=config,
            target_name=target_name,
            quarter_count=quarter_count,
            comparable_groups=comparable_groups,
            evidence=evidence,
            financial_charts=financial_charts,
            selected_anomalies=selected_anomalies or [],
            fallback_signals=fallback_signals,
            current_signals=signals,
            current_plan=next_plan,
            timeout=timeout,
        )
        if not signals:
            raise ValueError(f"{config.provider} returned no valid signals")
        completed = datetime.now()
        run.status = "success"
        run.completed_at = completed.strftime("%Y-%m-%d %H:%M:%S")
        run.duration_seconds = time.monotonic() - start
        usage = data.get("usage", {})
        run.output_summary = (
            f"signals={len(signals)}; next_fetch_plan={len(next_plan)}; "
            f"tokens={usage.get('total_tokens', 'unknown')}; compatibility={compatibility_mode}; "
            f"retries={'; '.join([note for note in [*retry_notes, parse_note, contract_note] if note]) or 'none'}"
        )
        return signals, next_plan, run
    except Exception as exc:
        completed = datetime.now()
        run.status = "failed"
        run.completed_at = completed.strftime("%Y-%m-%d %H:%M:%S")
        run.duration_seconds = time.monotonic() - start
        run.error = str(exc)
        return fallback_signals, [], run


def missing_deepseek_key_record() -> ModelRunRecord:
    return missing_llm_key_record(resolve_llm_provider_config(provider="deepseek"))


def missing_llm_key_record(config: LLMProviderConfig) -> ModelRunRecord:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return ModelRunRecord(
        provider=config.provider,
        model=config.model,
        purpose="Generate evidence-grounded alpha signals from collected financial charts, comparables, and source evidence.",
        status="skipped",
        started_at=now,
        completed_at=now,
        duration_seconds=0.0,
        error=f"Missing {config.provider} API key from UI, Streamlit Secrets, process env, or local .env; LLM analysis was not executed.",
    )


def generate_deepseek_comparable_groups(
    *,
    api_key: str,
    target: CompanyProfile,
    max_core_companies: int = 5,
    timeout: int = 120,
) -> tuple[list[dict[str, Any]], ModelRunRecord]:
    config = resolve_llm_provider_config(api_key, provider="deepseek")
    return generate_llm_comparable_groups(
        config=config,
        target=target,
        max_core_companies=max_core_companies,
        timeout=timeout,
    )


def generate_llm_comparable_groups(
    *,
    config: LLMProviderConfig,
    target: CompanyProfile,
    max_core_companies: int = 5,
    timeout: int = 120,
) -> tuple[list[dict[str, Any]], ModelRunRecord]:
    started = datetime.now()
    start = time.monotonic()
    run = ModelRunRecord(
        provider=config.provider,
        model=config.model,
        purpose="Select highly comparable global companies before evidence collection.",
        status="attempted",
        started_at=started.strftime("%Y-%m-%d %H:%M:%S"),
        prompt_summary=f"target={target.ticker} {target.name}; market={target.market}; max_core={max_core_companies}",
    )
    try:
        payload = _with_model(_build_comparable_payload(target, max_core_companies), config.model)
        response, compatibility_mode, retry_notes = _post_chat_completion(config, payload, timeout)
        data = response.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed, parse_note = _parse_or_repair_json_object(config, content, timeout)
        groups = _comparable_groups_from_payload(parsed)
        if not isinstance(groups, list) or not groups:
            raise ValueError(f"{config.provider} returned no comparable groups")
        completed = datetime.now()
        run.status = "success"
        run.completed_at = completed.strftime("%Y-%m-%d %H:%M:%S")
        run.duration_seconds = time.monotonic() - start
        usage = data.get("usage", {})
        rejected = parsed.get("rejected_near_misses", [])
        run.output_summary = (
            f"groups={len(groups)}; rejected_near_misses={len(rejected) if isinstance(rejected, list) else 0}; "
            f"tokens={usage.get('total_tokens', 'unknown')}; compatibility={compatibility_mode}; "
            f"retries={'; '.join([note for note in [*retry_notes, parse_note] if note]) or 'none'}"
        )
        return groups, run
    except Exception as exc:
        completed = datetime.now()
        run.status = "failed"
        run.completed_at = completed.strftime("%Y-%m-%d %H:%M:%S")
        run.duration_seconds = time.monotonic() - start
        run.error = str(exc)
        return [], run


def _comparable_groups_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups = payload.get("groups", [])
    if isinstance(groups, list) and groups:
        return [group for group in groups if isinstance(group, dict)]
    core = payload.get("core_comparables") or payload.get("core_comparable_companies") or payload.get("核心可比公司")
    validators = payload.get("cross_chain_validation") or payload.get("cross_chain_validators") or payload.get("交叉验证对象")
    normalized: list[dict[str, Any]] = []
    if isinstance(core, list) and core:
        normalized.append(
            {
                "group_id": "core_comparable",
                "title": "核心业务高度可比公司",
                "purpose": "用于目标公司横向对比",
                "selection_logic": str(payload.get("selection_logic") or "由大模型根据核心业务可比性筛选"),
                "companies": core,
            }
        )
    if isinstance(validators, list) and validators:
        normalized.append(
            {
                "group_id": "cross_chain_validation",
                "title": "上下游/需求侧交叉验证对象（非核心可比）",
                "purpose": "用于验证行业景气度或风险，不作为核心可比公司",
                "selection_logic": str(payload.get("cross_chain_logic") or "由大模型根据产业链关系筛选"),
                "companies": validators,
            }
        )
    return normalized


def _build_comparable_payload(target: CompanyProfile, max_core_companies: int) -> dict[str, Any]:
    system = (
        "你是一名资深产业研究员，负责为全球上市公司选择高度可比公司。"
        "第一版产品面向中文投资研究用户，必须中文优先。"
        "你的任务不是选泛同行、指数成分或市值相近公司，而是严格判断核心收入/利润来源是否处于同一细分市场。"
        "如果一家公司只是同属大行业、上下游、客户/供应商、替代技术路线或宏观温度计，不得放入核心可比组；"
        "可放入交叉验证组，并明确标注“非核心可比”。"
        "不要编造不存在的代码；不确定时给公司英文名和主要上市地，并把置信度降为 medium/low。"
        "Return strict JSON only."
    )
    user = {
        "task": "为目标公司选择全球范围内3-5家核心业务高度可比公司，并可选给出少量上下游/需求侧交叉验证对象。",
        "target": target.to_company_dict(),
        "hard_rules": [
            "核心可比公司必须与目标公司的重点业务处在同一细分市场或直接争夺同一客户预算。",
            "不要因为同属半导体、互联网、汽车、医药、能源等大行业就判定为可比。",
            "例如：德州仪器与ADI可比，但与英特尔不可比；晶圆代工厂与IDM或设备厂通常不是核心可比。",
            "默认核心可比公司数量为3-5家；宁缺毋滥，无法确认时少选并说明。",
            "comparability_score 使用 1-5 分，5 代表最强可比，1 代表不适合作核心可比；核心可比组只放 4-5 分。",
            "允许覆盖美国、中国A股/港股/中概股、欧洲、日本、韩国及其他全球上市公司。",
            "交叉验证对象必须单独分组，不能伪装成核心可比公司。",
            "每家公司必须给出选择理由、可比维度、置信度和是否核心可比。",
        ],
        "json_schema": {
            "groups": [
                {
                    "group_id": "core_comparable",
                    "title": "核心业务高度可比公司",
                    "purpose": "用于目标公司横向对比",
                    "selection_logic": "为什么这些公司与目标公司高度可比",
                    "companies": [
                        {
                            "ticker": "股票代码或ADR/本地代码；未知可留空",
                            "name": "公司英文名",
                            "market": "主要上市地",
                            "segment": "细分市场",
                            "reason": "为什么高度可比",
                            "comparability_score": "1-5 integer; 5 means strongest comparable",
                            "confidence": "high|medium|low",
                            "is_core_comparable": True,
                        }
                    ],
                },
                {
                    "group_id": "cross_chain_validation",
                    "title": "上下游/需求侧交叉验证对象（非核心可比）",
                    "purpose": "用于验证行业景气度或风险，不作为核心可比公司",
                    "selection_logic": "为什么这些对象适合作交叉验证",
                    "companies": [],
                },
            ],
            "rejected_near_misses": [
                {
                    "name": "看似相关但不应作为核心可比的公司",
                    "reason": "排除原因",
                }
            ],
        },
        "max_core_companies": max(3, min(5, max_core_companies)),
    }
    return {
        "model": QWEAPI_DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "temperature": 0.1,
        "max_tokens": 5000,
    }


def _read_streamlit_secret(name: str) -> str:
    try:
        import streamlit as st
    except Exception:
        return ""
    try:
        secrets = st.secrets
        direct = str(secrets.get(name, "") or secrets.get(name.lower(), "") or "").strip()
        if direct:
            return direct
        for section_name in _secret_sections_for_name(name):
            section = secrets.get(section_name, {})
            if hasattr(section, "get"):
                for key in _section_secret_aliases(name):
                    value = str(section.get(key, "") or "").strip()
                    if value:
                        return value
    except Exception:
        return ""
    return ""


def _secret_sections_for_name(name: str) -> tuple[str, ...]:
    normalized = name.strip().upper()
    if normalized.startswith("DEEPSEEK_"):
        return ("deepseek", "llm")
    if normalized.startswith("OPENAI_"):
        return ("openai", "qweapi", "llm")
    if normalized.startswith("ANTHROPIC_"):
        return ("anthropic", "qweapi", "llm")
    if normalized.startswith("QWEAPI_"):
        return ("qweapi", "llm")
    return ("llm", "qweapi", "deepseek")


def _section_secret_aliases(name: str) -> tuple[str, ...]:
    normalized = name.strip().upper()
    aliases = [name, name.lower()]
    if normalized.endswith("API_KEY"):
        aliases.extend(["api_key", "key"])
    elif normalized.endswith("BASE_URL"):
        aliases.extend(["base_url", "url"])
    elif normalized.endswith("MODEL"):
        aliases.append("model")
    elif normalized == "LLM_PROVIDER":
        aliases.append("provider")
    return tuple(dict.fromkeys(aliases))


def _read_config_value(name: str) -> str:
    return (
        _read_streamlit_secret(name)
        or os.getenv(name, "").strip()
        or _read_local_env_secret(name)
    )


def _read_local_env_secret(name: str) -> str:
    candidates = [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        try:
            for raw_line in resolved.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip().lstrip("\ufeff") == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def _post_chat_completion(config: LLMProviderConfig, payload: dict[str, Any], timeout: int) -> tuple[requests.Response, str, list[str]]:
    variants = _payload_variants(payload)
    retry_notes: list[str] = []
    last_error = ""
    for compatibility_mode, candidate in variants:
        response = requests.post(
            config.chat_url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json=candidate,
            timeout=timeout,
        )
        if response.status_code < 400:
            return response, compatibility_mode, retry_notes
        last_error = _safe_response_error(response)
        retry_notes.append(f"{compatibility_mode}: {last_error}")
        if not _is_retryable_payload_error(last_error):
            break
    raise RuntimeError(last_error or f"{config.provider} request failed")


def _payload_variants(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    base = dict(payload)
    no_thinking = dict(base)
    no_thinking.pop("thinking", None)
    no_thinking.pop("reasoning_effort", None)
    plain_json_prompt = dict(no_thinking)
    plain_json_prompt.pop("response_format", None)
    return [
        ("thinking_json", base),
        ("json_no_thinking", no_thinking),
        ("plain_prompt_json", plain_json_prompt),
    ]


def _with_model(payload: dict[str, Any], model: str) -> dict[str, Any]:
    updated = dict(payload)
    updated["model"] = model
    return updated


def _safe_response_error(response: requests.Response) -> str:
    text = response.text.replace("\n", " ").strip()
    if len(text) > 500:
        text = text[:500] + "..."
    return f"HTTP {response.status_code}: {text}"


def _is_retryable_payload_error(error_text: str) -> bool:
    lowered = error_text.lower()
    retryable_markers = [
        "unknown parameter",
        "unsupported",
        "invalid request",
        "response_format",
        "thinking",
        "reasoning_effort",
        "json",
    ]
    return "http 400" in lowered and any(marker in lowered for marker in retryable_markers)


def _build_payload(
    target_name: str,
    quarter_count: int,
    comparable_groups: list[ComparableGroup],
    evidence: list[EvidenceItem],
    financial_charts: list[FinancialChart],
    selected_anomalies: list[ObjectiveAnomaly],
    fallback_signals: list[ResearchSignal],
) -> dict[str, Any]:
    system = (
        "你是一名资深二级市场/产业研究员。第一版产品面向中文用户，必须优先使用专业、清晰的中文表达。"
        "Use only the supplied evidence and chart data. Do not invent facts. "
        "The user has already selected objective anomalies for deep dive. Focus on those selected anomalies only. "
        "If evidence is weak, mark the signal as needs_validation. "
        "Return strict JSON only."
    )
    user = {
        "task": "围绕用户勾选的客观异常条目，生成中文深度分析信号；不要重新泛泛挑选指标。",
        "target": target_name,
        "quarter_count": quarter_count,
        "rules": [
            "输出语言必须是中文，标题、结论、推理摘要、下一步验证动作都用中文。",
            "每个深度分析信号必须对应至少一个 selected_anomalies 中的 anomaly_id。",
            "积极信号和风险信号要分清楚；证据不足时标为 needs_validation。",
            "禁止把资料覆盖充分、监管来源较多、transcript 候选较多、搜索入口较多本身写成积极信号；这些只能放在证据审计或资料缺口里。",
            "积极/风险信号必须是关于公司经营、行业景气、竞争格局、财务质量、资本开支、利润率、客户/地区/业务结构、管理层判断变化的具体结论。",
            "如果没有读到 transcript/presentation 正文或没有足够财务图表，不要编造经营结论；输出 data_gap 或 needs_validation。",
            "深度分析必须至少使用一个 financial_charts 中的具体数据点或一个 evidence.quote 原文片段；不能只复述异常标题。",
            "涉及管理层观点、需求、竞争、云/AI 投入、广告商业化等文字判断时，必须引用 has_readable_text=true 的 evidence。",
            "Each signal must reference evidence_ids and explain chart choice.",
            "Do not claim unsupported facts. Use needs_validation for hypotheses.",
            "Prefer signals that combine vertical company trend and horizontal peer/cross-chain comparison.",
            "Return JSON with keys: signals, next_fetch_plan.",
        ],
        "selected_objective_anomalies": [anomaly.to_dict() for anomaly in selected_anomalies],
        "comparable_groups": [
            {
                "group_id": group.group_id,
                "title": group.title,
                "purpose": group.purpose,
                "selection_logic": group.selection_logic,
                "companies": [company.ticker for company in group.companies],
            }
            for group in comparable_groups
        ],
        "financial_charts": [_chart_summary(chart) for chart in financial_charts],
        "evidence": [_evidence_summary(index, item) for index, item in _select_prompt_evidence(evidence, limit=60)],
        "fallback_signal_templates": [
            {
                "title": signal.title,
                "signal_type": signal.signal_type,
                "status": signal.status,
                "chart_hint": signal.chart_hint,
            }
            for signal in fallback_signals
        ],
        "json_schema": {
            "signals": [
                {
                    "title": "string",
                    "conclusion": "string",
                    "signal_type": "积极信号|风险信号|高潜力待验证线索",
                    "status": "evidence_backed|needs_validation|data_gap",
                    "score": {
                        "importance": "1-5 integer",
                        "evidence_strength": "1-5 integer",
                        "novelty": "1-5 integer",
                        "investment_relevance": "1-5 integer",
                        "time_sensitivity": "1-5 integer",
                        "actionability": "1-5 integer",
                    },
                    "evidence_ids": "array of integer ids from supplied evidence",
                    "anomaly_ids": "array of anomaly_id strings from selected_objective_anomalies",
                    "chart_hint": "string",
                    "chart_reason": "string",
                    "reasoning_summary": "string",
                    "reasoning_chain": ["short evidence-grounded steps"],
                    "next_validation_actions": ["specific follow-up actions"],
                }
            ],
            "next_fetch_plan": ["string"],
        },
    }
    return {
        "model": QWEAPI_DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
        "temperature": 0.2,
        "max_tokens": 6000,
    }


def _chart_summary(chart: FinancialChart) -> dict[str, Any]:
    return {
        "chart_id": chart.chart_id,
        "title": chart.title,
        "chart_type": chart.chart_type,
        "insight": chart.insight,
        "points": [
            {
                "ticker": point.ticker,
                "period": point.period,
                "metric": point.metric_label,
                "value": point.display_value,
                "source": point.sources[0].url if point.sources else "",
                "concept": point.sources[0].concept if point.sources else "",
            }
            for point in chart.points[:12]
        ],
    }


def _evidence_summary(index: int, item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": index,
        "ticker": item.ticker,
        "company": item.company,
        "type": item.evidence_type,
        "source": item.source,
        "confidence": item.confidence_tier,
        "date": item.date,
        "title": item.title[:220],
        "url": item.url,
        "quote": item.quote[:900],
        "has_readable_text": bool(item.quote),
    }


def _select_prompt_evidence(evidence: list[EvidenceItem], limit: int) -> list[tuple[int, EvidenceItem]]:
    priority = {
        "official": 0,
        "platform": 1,
        "media": 2,
        "search": 3,
        "medium": 4,
    }
    type_priority = {
        "private_company": 0,
        "presentation": 1,
        "transcript": 2,
        "annual": 3,
        "quarterly": 4,
    }
    indexed = list(enumerate(evidence))
    selected = sorted(
        indexed,
        key=lambda pair: (
            0 if pair[1].quote else 1,
            0 if pair[1].screenshot_path else 1,
            type_priority.get(pair[1].evidence_type, 8),
            priority.get(pair[1].confidence_tier, 9),
            pair[1].ticker,
        ),
    )
    return selected[:limit]


def _parse_json_object(content: str) -> dict[str, Any]:
    content = (content or "").strip()
    if not content:
        raise ValueError("Empty model output")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _parse_or_repair_json_object(config: LLMProviderConfig, content: str, timeout: int) -> tuple[dict[str, Any], str]:
    try:
        return _parse_json_object(content), ""
    except Exception as first_exc:
        repaired = _repair_json_with_llm(config, content, timeout)
        try:
            return _parse_json_object(repaired), f"json_repair_success_after={type(first_exc).__name__}"
        except Exception as second_exc:
            raise ValueError(f"Initial JSON parse failed: {first_exc}; repair parse failed: {second_exc}") from second_exc


def _repair_json_with_llm(config: LLMProviderConfig, broken_content: str, timeout: int) -> str:
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": "You repair malformed JSON. Return strict JSON only. Do not add prose."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Repair the following malformed JSON into valid JSON with keys signals and next_fetch_plan. Preserve all useful content.",
                        "malformed_json": broken_content[:12000],
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 6000,
    }
    response, _mode, _notes = _post_chat_completion(config, payload, timeout)
    data = response.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _ensure_signal_contract(
    *,
    config: LLMProviderConfig,
    target_name: str,
    quarter_count: int,
    comparable_groups: list[ComparableGroup],
    evidence: list[EvidenceItem],
    financial_charts: list[FinancialChart],
    selected_anomalies: list[ObjectiveAnomaly],
    fallback_signals: list[ResearchSignal],
    current_signals: list[ResearchSignal],
    current_plan: list[str],
    timeout: int,
) -> tuple[list[ResearchSignal], list[str], str]:
    ok, reason = _signal_contract_status(current_signals)
    if ok:
        return current_signals, current_plan, ""
    repair_payload = _build_payload(target_name, quarter_count, comparable_groups, evidence, financial_charts, selected_anomalies, fallback_signals)
    repair_payload["messages"].append(
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "signals": [signal.to_dict() for signal in current_signals],
                    "next_fetch_plan": current_plan,
                },
                ensure_ascii=False,
            ),
        }
    )
    repair_payload["messages"].append(
        {
            "role": "user",
            "content": (
                f"The previous answer failed the output contract: {reason}. "
                "Return a corrected strict JSON object with 5-8 signals. "
                "It must use Chinese, focus on selected objective anomalies, and include positive/risk classification where applicable. "
                "Use only supplied evidence/chart data and keep evidence_ids valid integers."
            ),
        }
    )
    repair_payload = _with_model(repair_payload, config.model)
    response, mode, notes = _post_chat_completion(config, repair_payload, timeout)
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    parsed, parse_note = _parse_or_repair_json_object(config, content, timeout)
    repaired_signals = _signals_from_payload(parsed, evidence)
    next_plan_raw = parsed.get("next_fetch_plan", [])
    repaired_plan = [str(item) for item in (next_plan_raw if isinstance(next_plan_raw, list) else []) if str(item).strip()]
    repaired_ok, repaired_reason = _signal_contract_status(repaired_signals)
    note_parts = [f"signal_contract_repair={reason}", f"mode={mode}", *notes]
    if parse_note:
        note_parts.append(parse_note)
    if repaired_ok:
        return repaired_signals, repaired_plan or current_plan, "; ".join(note_parts)
    if current_signals:
        note_parts.append(f"repair_still_failed={repaired_reason}; kept_initial_signals")
        return current_signals, current_plan, "; ".join(note_parts)
    raise ValueError(f"{config.provider} signal contract failed: {repaired_reason}")


def _signal_contract_status(signals: list[ResearchSignal]) -> tuple[bool, str]:
    if len(signals) < 5 or len(signals) > 8:
        return False, f"signal_count={len(signals)}"
    text = " ".join(f"{signal.signal_type} {signal.status} {signal.title} {signal.conclusion}" for signal in signals).lower()
    forbidden = ["资料覆盖", "来源覆盖", "监管来源覆盖", "transcript 候选", "候选证据", "搜索入口", "coverage"]
    if any(token in text for token in forbidden):
        return False, "contains_evidence_coverage_as_signal"
    has_positive = any(token in text for token in ["亮点", "positive", "highlight", "growth", "领先", "优势"])
    has_risk = any(token in text for token in ["风险", "risk", "decline", "pressure", "erosion", "underinvestment"])
    has_validation = any(token in text for token in ["待验证", "needs_validation", "hypothesis", "验证", "线索"])
    missing = []
    if not has_positive:
        missing.append("positive_highlight")
    if not has_risk:
        missing.append("risk")
    if not has_validation:
        missing.append("validation_lead")
    if missing:
        return False, "missing_" + ",".join(missing)
    return True, ""


def _signals_from_payload(payload: dict[str, Any], evidence: list[EvidenceItem]) -> list[ResearchSignal]:
    signals: list[ResearchSignal] = []
    for item in payload.get("signals", [])[:8]:
        if not isinstance(item, dict):
            continue
        score_data = item.get("score") if isinstance(item.get("score"), dict) else {}
        score = SignalScore(
            importance=_score_value(score_data.get("importance"), 4),
            evidence_strength=_score_value(score_data.get("evidence_strength"), 3),
            novelty=_score_value(score_data.get("novelty"), 3),
            investment_relevance=_score_value(score_data.get("investment_relevance"), 4),
            time_sensitivity=_score_value(score_data.get("time_sensitivity"), 3),
            actionability=_score_value(score_data.get("actionability"), 3),
        )
        evidence_ids = []
        raw_evidence_ids = item.get("evidence_ids", [])
        for value in raw_evidence_ids if isinstance(raw_evidence_ids, list) else []:
            try:
                index = int(value)
            except Exception:
                continue
            if 0 <= index < len(evidence):
                evidence_ids.append(index)
        raw_anomaly_ids = item.get("anomaly_ids", [])
        anomaly_ids = [str(value) for value in raw_anomaly_ids if str(value).strip()] if isinstance(raw_anomaly_ids, list) else []
        valid_evidence_ids = evidence_ids[:10]
        source_count = len({evidence[index].source for index in valid_evidence_ids if 0 <= index < len(evidence) and evidence[index].source})
        status = _status_value(str(item.get("status") or ""))
        if status == "evidence_backed" and source_count < 3:
            status = "needs_validation"
        signals.append(
            ResearchSignal(
                title=str(item.get("title") or "未命名信号"),
                conclusion=str(item.get("conclusion") or ""),
                signal_type=str(item.get("signal_type") or "高潜力待验证线索"),
                status=status,
                score=score,
                evidence_ids=valid_evidence_ids,
                anomaly_ids=anomaly_ids[:10],
                chart_hint=str(item.get("chart_hint") or ""),
                chart_reason=str(item.get("chart_reason") or ""),
                reasoning_summary=str(item.get("reasoning_summary") or ""),
                reasoning_chain=_string_list(item.get("reasoning_chain"), limit=6),
                next_validation_actions=_string_list(item.get("next_validation_actions"), limit=6),
                source_count=source_count,
            )
        )
    return signals


def _score_value(value: Any, default: int) -> int:
    try:
        number = int(value)
    except Exception:
        number = default
    return max(1, min(5, number))


def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if str(item).strip()]


def _status_value(value: str) -> str:
    value = value.strip()
    if value in {"evidence_backed", "needs_validation", "data_gap"}:
        return value
    if "验证" in value or "hypothesis" in value.lower():
        return "needs_validation"
    return "evidence_backed" if value else "needs_validation"
