from __future__ import annotations

from dataclasses import replace
from typing import Any

from .company_search_global import find_best_company, search_companies
from .research_llm import LLMProviderConfig, generate_llm_comparable_groups, missing_llm_key_record, resolve_llm_provider_config
from .research_models import CompanyProfile, ComparableGroup, ModelRunRecord


AI_COMPANY_UNIVERSE: dict[str, CompanyProfile] = {
    "NVDA": CompanyProfile("NVDA", "NVIDIA", "US", "AI accelerator leader", "GPU / AI accelerator", "AI training and inference GPU, networking, CUDA ecosystem", "0001045810", "https://investor.nvidia.com/"),
    "AMD": CompanyProfile("AMD", "Advanced Micro Devices", "US", "AI accelerator challenger", "GPU / AI accelerator", "Data center GPU, CPU and adaptive computing", "0000002488", "https://ir.amd.com/"),
    "AVGO": CompanyProfile("AVGO", "Broadcom", "US", "custom silicon and networking", "ASIC / networking", "AI custom silicon, switching, connectivity and software", "0001730168", "https://investors.broadcom.com/"),
    "MRVL": CompanyProfile(
        "MRVL",
        "Marvell Technology",
        "US",
        "data infrastructure silicon",
        "ASIC / networking",
        "Custom silicon, optical DSP and data infrastructure chips",
        "0001835632",
        "https://investor.marvell.com/",
        aliases=("Marvell Technology Inc", "Marvell Technology, Inc.", "9MW", "9MW.MU", "9MW.DU", "9MW.F", "9MW.DE"),
    ),
    "ARM": CompanyProfile("ARM", "Arm Holdings", "US", "CPU IP platform", "CPU IP", "CPU architecture IP used in cloud, mobile and edge AI", "0001973239", "https://investors.arm.com/"),
    "TSM": CompanyProfile("TSM", "Taiwan Semiconductor Manufacturing", "US ADR / Taiwan", "leading foundry", "advanced foundry", "Advanced-node wafer manufacturing and CoWoS packaging", "0001046179", "https://investor.tsmc.com/"),
    "ASML": CompanyProfile("ASML", "ASML Holding", "US ADR / Netherlands", "lithography bottleneck", "semiconductor equipment", "EUV and DUV lithography systems", "0000937966", "https://www.asml.com/en/investors"),
    "AMAT": CompanyProfile("AMAT", "Applied Materials", "US", "wafer equipment", "semiconductor equipment", "Deposition, etch and process control equipment", "0000006951", "https://ir.appliedmaterials.com/"),
    "LRCX": CompanyProfile("LRCX", "Lam Research", "US", "wafer equipment", "semiconductor equipment", "Etch and deposition equipment", "0000707549", "https://investor.lamresearch.com/"),
    "MU": CompanyProfile("MU", "Micron Technology", "US", "memory supplier", "HBM / DRAM / NAND", "Memory and storage supplier with HBM exposure", "0000723125", "https://investors.micron.com/"),
    "005930.KS": CompanyProfile("005930.KS", "Samsung Electronics", "Korea", "memory and foundry", "HBM / DRAM / foundry", "Memory, foundry and consumer electronics", "", "https://www.samsung.com/global/ir/"),
    "000660.KS": CompanyProfile("000660.KS", "SK Hynix", "Korea", "HBM leader", "HBM / DRAM", "High-bandwidth memory and DRAM supplier", "", "https://www.skhynix.com/ir/"),
    "MSFT": CompanyProfile("MSFT", "Microsoft", "US", "CSP and AI platform", "CSP / AI demand", "Azure, OpenAI partnership and enterprise AI demand", "0000789019", "https://www.microsoft.com/en-us/Investor/"),
    "GOOGL": CompanyProfile("GOOGL", "Alphabet", "US", "CSP and model owner", "CSP / AI demand", "Google Cloud, TPU, Gemini and advertising AI", "0001652044", "https://abc.xyz/investor/"),
    "AMZN": CompanyProfile("AMZN", "Amazon", "US", "CSP and AI platform", "CSP / AI demand", "AWS, Trainium/Inferentia and AI workloads", "0001018724", "https://ir.aboutamazon.com/"),
    "META": CompanyProfile("META", "Meta Platforms", "US", "hyperscale AI spender", "CSP / AI demand", "AI capex, recommender systems and Llama ecosystem", "0001326801", "https://investor.fb.com/"),
    "ORCL": CompanyProfile("ORCL", "Oracle", "US", "cloud infrastructure", "CSP / AI demand", "OCI AI infrastructure and enterprise workloads", "0001341439", "https://investor.oracle.com/"),
    "SMCI": CompanyProfile("SMCI", "Super Micro Computer", "US", "AI server integrator", "AI servers", "AI servers and rack-scale infrastructure", "0001375365", "https://ir.supermicro.com/"),
    "DELL": CompanyProfile("DELL", "Dell Technologies", "US", "AI server OEM", "AI servers", "Enterprise servers, storage and AI infrastructure", "0001571996", "https://investors.delltechnologies.com/"),
    "HPE": CompanyProfile("HPE", "Hewlett Packard Enterprise", "US", "server and HPC platform", "AI servers", "Servers, HPC and enterprise infrastructure", "0001645590", "https://investors.hpe.com/"),
    "ANET": CompanyProfile("ANET", "Arista Networks", "US", "AI networking", "AI networking", "Data center switching for AI clusters", "0001596532", "https://investors.arista.com/"),
    "VRT": CompanyProfile("VRT", "Vertiv", "US", "power and cooling", "data center power / cooling", "Thermal and power infrastructure for data centers", "0001674101", "https://investors.vertiv.com/"),
    "OPENAI": CompanyProfile("OPENAI", "OpenAI", "Private", "frontier model company", "AI model company", "Frontier models, ChatGPT, API and enterprise AI demand", "", "https://openai.com/", False, "private company"),
    "ANTHROPIC": CompanyProfile("ANTHROPIC", "Anthropic", "Private", "frontier model company", "AI model company", "Claude models, enterprise API demand and compute procurement", "", "https://www.anthropic.com/", False, "private company"),
    "XAI": CompanyProfile("XAI", "xAI", "Private", "frontier model company", "AI model company", "Grok models and large-scale compute buildout", "", "https://x.ai/", False, "private company"),
}


TARGET_GROUP_BLUEPRINTS: dict[str, list[dict[str, object]]] = {
    "GOOGL": [
        {
            "group_id": "core_digital_ads_cloud",
            "title": "核心业务可比：数字广告 + 云/AI 平台",
            "purpose": "对比 Alphabet 的广告商业化、云业务增长、AI 投入和经营杠杆是否优于主要平台型科技公司。",
            "selection_logic": "选择同样拥有大规模数字广告、云/AI 平台或平台型流量商业化能力的公司；不是泛 AI 硬件可比。",
            "tickers": ["META", "AMZN", "MSFT"],
        },
        {
            "group_id": "ai_infra_cross_check",
            "title": "交叉验证：AI 基础设施与算力供给",
            "purpose": "用 AI 芯片、服务器和基础设施公司的收入/订单/管理层表述验证 hyperscaler AI capex 周期。",
            "selection_logic": "这些不是 Alphabet 核心可比公司，而是验证 AI capex、算力供给和数据中心建设节奏的上下游对象。",
            "tickers": ["NVDA", "AMD", "SMCI", "ANET", "VRT"],
        },
        {
            "group_id": "private_model_watch",
            "title": "私有模型公司观察：Gemini 竞争与模型需求",
            "purpose": "用 OpenAI/Anthropic/xAI 的融资、API价格、模型能力和算力采购验证模型层竞争压力与算力需求。",
            "selection_logic": "私有模型公司不是财务可比对象，但会影响 Google Gemini、云 AI 需求和资本开支叙事。",
            "tickers": ["OPENAI", "ANTHROPIC", "XAI"],
        },
    ],
    "GOOG": [
        {
            "group_id": "core_digital_ads_cloud",
            "title": "核心业务可比：数字广告 + 云/AI 平台",
            "purpose": "对比 Alphabet 的广告商业化、云业务增长、AI 投入和经营杠杆是否优于主要平台型科技公司。",
            "selection_logic": "选择同样拥有大规模数字广告、云/AI 平台或平台型流量商业化能力的公司；不是泛 AI 硬件可比。",
            "tickers": ["META", "AMZN", "MSFT"],
        },
        {
            "group_id": "ai_infra_cross_check",
            "title": "交叉验证：AI 基础设施与算力供给",
            "purpose": "用 AI 芯片、服务器和基础设施公司的收入/订单/管理层表述验证 hyperscaler AI capex 周期。",
            "selection_logic": "这些不是 Alphabet 核心可比公司，而是验证 AI capex、算力供给和数据中心建设节奏的上下游对象。",
            "tickers": ["NVDA", "AMD", "SMCI", "ANET", "VRT"],
        },
    ],
    "NVDA": [
        {
            "group_id": "core_accelerator",
            "title": "核心业务可比：AI 加速器与数据中心芯片",
            "purpose": "判断 NVIDIA 数据中心 GPU 增长、定价、供给约束是否优于直接可比芯片公司。",
            "selection_logic": "优先选择同处 AI 训练 / 推理加速、ASIC 或数据中心芯片预算竞争池的公司，而非泛半导体公司。",
            "tickers": ["AMD", "AVGO", "MRVL", "ARM"],
        },
        {
            "group_id": "upstream_supply",
            "title": "上游交叉验证：先进制程、HBM、设备",
            "purpose": "用 foundry、HBM 和设备公司的订单 / 产能 / 管理层表述验证 AI 芯片景气度和瓶颈。",
            "selection_logic": "选择会直接受 NVIDIA/AI 加速器需求拉动或约束其交付能力的上游环节。",
            "tickers": ["TSM", "ASML", "MU", "000660.KS", "005930.KS"],
        },
        {
            "group_id": "downstream_demand",
            "title": "下游需求验证：CSP 与模型使用方",
            "purpose": "观察 CSP capex、AI 基础设施需求、模型调用和云收入是否支撑芯片订单持续性。",
            "selection_logic": "选择 GPU/AI 服务器最大采购方和 AI 云平台代表。",
            "tickers": ["MSFT", "GOOGL", "AMZN", "META", "ORCL"],
        },
        {
            "group_id": "infrastructure_route",
            "title": "基础设施与替代路线：服务器、网络、电力散热",
            "purpose": "用服务器、网络和电力散热环节确认 AI 集群建设节奏，并识别非 GPU 瓶颈。",
            "selection_logic": "选择订单会随 AI 集群建设同步变化的硬件集成和数据中心基础设施公司。",
            "tickers": ["SMCI", "DELL", "HPE", "ANET", "VRT"],
        },
        {
            "group_id": "private_model_watch",
            "title": "私有关键玩家观察：模型公司需求与融资信号",
            "purpose": "通过模型公司融资、ARR/收入传闻、API 价格、用户增长、采购和合作交叉验证算力需求。",
            "selection_logic": "选择非上市但对 AI 算力需求、生态叙事和客户预算影响很大的 frontier model 公司。",
            "tickers": ["OPENAI", "ANTHROPIC", "XAI"],
        },
    ],
    "TSM": [
        {
            "group_id": "core_foundry",
            "title": "核心业务可比：先进晶圆代工",
            "purpose": "判断先进制程与先进封装需求是否显著领先其他晶圆代工厂。",
            "selection_logic": "优先选择先进制程、AI 客户和晶圆代工业务可比度最高的公司。",
            "tickers": ["005930.KS", "SMIC", "UMC", "GFS"],
        },
        {
            "group_id": "upstream_equipment",
            "title": "上游交叉验证：设备和光刻",
            "purpose": "用设备订单、EUV 交付和资本开支验证先进制程扩产节奏。",
            "selection_logic": "选择对先进制程扩产最敏感的关键设备公司。",
            "tickers": ["ASML", "AMAT", "LRCX"],
        },
        {
            "group_id": "downstream_ai_chip",
            "title": "下游需求验证：AI 芯片客户",
            "purpose": "观察 AI 芯片需求是否继续拉动先进制程与 CoWoS。",
            "selection_logic": "选择先进节点和先进封装需求最大的 AI 芯片客户。",
            "tickers": ["NVDA", "AMD", "AVGO", "MRVL"],
        },
        {
            "group_id": "private_model_watch",
            "title": "私有关键玩家观察：模型公司需求与融资信号",
            "purpose": "用模型公司融资、ARR/收入传闻、API价格、用户增长、采购和合作交叉验证先进制程与封装需求。",
            "selection_logic": "OpenAI / Anthropic / xAI 虽非晶圆代工直接可比公司，但它们是 AI 算力需求的重要源头和交叉验证对象。",
            "tickers": ["OPENAI", "ANTHROPIC", "XAI"],
        },
    ],
}


EXTRA_COMPANIES: dict[str, CompanyProfile] = {
    "SMIC": CompanyProfile("SMIC", "Semiconductor Manufacturing International", "Hong Kong / China", "China foundry", "mature / China foundry", "China-based wafer foundry", "", "https://www.smics.com/en/site/company_financialSummary"),
    "UMC": CompanyProfile("UMC", "United Microelectronics", "US ADR / Taiwan", "mature foundry", "mature foundry", "Specialty and mature-node wafer foundry", "0001033767", "https://www.umc.com/en/IR/"),
    "GFS": CompanyProfile("GFS", "GlobalFoundries", "US", "specialty foundry", "specialty foundry", "Specialty foundry with automotive and industrial exposure", "0001709048", "https://investors.gf.com/"),
}


def normalize_ticker(value: str) -> str:
    return (value or "").strip().upper()


def get_company_profile(query: str) -> CompanyProfile:
    ticker = normalize_ticker(query)
    if ticker in AI_COMPANY_UNIVERSE:
        return AI_COMPANY_UNIVERSE[ticker]
    if ticker in EXTRA_COMPANIES:
        return EXTRA_COMPANIES[ticker]
    for company in [*AI_COMPANY_UNIVERSE.values(), *EXTRA_COMPANIES.values()]:
        query_key = query.casefold().strip()
        alias_keys = {str(alias).casefold().strip() for alias in company.aliases}
        if query_key in {company.name.casefold(), company.ticker.casefold(), *alias_keys}:
            return company
    discovered = _discover_global_company(query)
    if discovered:
        return discovered
    return CompanyProfile(ticker or query, query.strip() or ticker, "Unknown", "target company", "auto-discovered", "User-entered target")


def all_research_companies() -> dict[str, CompanyProfile]:
    merged = dict(AI_COMPANY_UNIVERSE)
    merged.update(EXTRA_COMPANIES)
    return merged


def recommend_comparable_groups(target_query: str, max_core_companies: int = 5) -> list[ComparableGroup]:
    target = get_company_profile(target_query)
    universe = all_research_companies()
    blueprints = TARGET_GROUP_BLUEPRINTS.get(target.ticker.upper())
    if not blueprints and "alphabet" in target.name.casefold():
        blueprints = TARGET_GROUP_BLUEPRINTS.get("GOOGL")
    if not blueprints:
        blueprints = _fallback_blueprints(target)
    groups: list[ComparableGroup] = []
    for blueprint in blueprints:
        tickers = [str(ticker).upper() for ticker in blueprint["tickers"]]
        companies = [universe[ticker] for ticker in tickers if ticker in universe]
        if blueprint["group_id"] == "core_accelerator":
            companies = companies[:max_core_companies]
        groups.append(
            ComparableGroup(
                group_id=str(blueprint["group_id"]),
                title=str(blueprint["title"]),
                purpose=str(blueprint["purpose"]),
                selection_logic=str(blueprint["selection_logic"]),
                companies=companies,
            )
        )
    return groups


def recommend_comparable_groups_with_llm(
    target_query: str,
    deepseek_api_key: str = "",
    llm_config: LLMProviderConfig | None = None,
    max_core_companies: int = 5,
) -> tuple[list[ComparableGroup], ModelRunRecord]:
    target = get_company_profile(target_query)
    llm_config = llm_config or resolve_llm_provider_config(deepseek_api_key)
    if not llm_config.api_key:
        return [], missing_llm_key_record(llm_config)
    raw_groups, run = generate_llm_comparable_groups(
        config=llm_config,
        target=target,
        max_core_companies=max_core_companies,
    )
    groups = _groups_from_llm_payload(raw_groups, target)
    if run.status != "success" or not groups:
        return [], run
    return groups, run


def build_selected_groups(base_groups: list[ComparableGroup], selected_by_group: dict[str, list[str]], extra_companies: list[str] | None = None) -> list[ComparableGroup]:
    universe = all_research_companies()
    selected_groups: list[ComparableGroup] = []
    for group in base_groups:
        selected_tickers = {normalize_ticker(ticker) for ticker in selected_by_group.get(group.group_id, [])}
        companies = [company for company in group.companies if normalize_ticker(company.ticker) in selected_tickers]
        if companies:
            selected_groups.append(replace(group, companies=companies))
    extras = [get_company_profile(value) for value in (extra_companies or []) if value.strip()]
    if extras:
        selected_groups.append(
            ComparableGroup(
                group_id="user_added",
                title="用户新增观察公司",
                purpose="保留用户认为需要纳入的额外公司，用于后续证据抓取和信号验证。",
                selection_logic="用户手动添加，系统后续需要重新判断其与目标公司的可比关系。",
                companies=extras,
            )
        )
    return selected_groups


def _groups_from_llm_payload(raw_groups: list[dict[str, Any]], target: CompanyProfile) -> list[ComparableGroup]:
    groups: list[ComparableGroup] = []
    target_keys = _company_identity_keys(target)
    for index, raw_group in enumerate(raw_groups[:4], start=1):
        if not isinstance(raw_group, dict):
            continue
        raw_companies = raw_group.get("companies", [])
        if not isinstance(raw_companies, list):
            continue
        group_id = str(raw_group.get("group_id") or f"llm_group_{index}").strip() or f"llm_group_{index}"
        companies: list[CompanyProfile] = []
        is_core_group = "core" in group_id.casefold() or "核心" in str(raw_group.get("title") or "")
        for raw_company in raw_companies[:8]:
            if is_core_group and not _passes_core_comparable_filter(raw_company):
                continue
            company = _profile_from_llm_company(raw_company)
            if not company:
                continue
            keys = _company_identity_keys(company)
            if keys & target_keys:
                continue
            if normalize_ticker(company.ticker) in {normalize_ticker(existing.ticker) for existing in companies}:
                continue
            companies.append(company)
        if not companies:
            continue
        groups.append(
            ComparableGroup(
                group_id=_safe_group_id(group_id),
                title=str(raw_group.get("title") or "AI 精选可比/验证公司"),
                purpose=str(raw_group.get("purpose") or "用于横向对比和交叉验证"),
                selection_logic=str(raw_group.get("selection_logic") or "由大模型根据核心业务可比性筛选"),
                companies=companies,
            )
        )
    return groups


def _company_identity_keys(company: CompanyProfile) -> set[str]:
    return {
        key
        for key in [
            normalize_ticker(company.ticker),
            normalize_ticker(company.local_code),
            company.name.casefold().strip(),
            *(normalize_ticker(alias) for alias in company.aliases),
            *(str(alias).casefold().strip() for alias in company.aliases),
        ]
        if key
    }


def _passes_core_comparable_filter(raw_company: Any) -> bool:
    if not isinstance(raw_company, dict):
        return False
    if raw_company.get("is_core_comparable") is False:
        return False
    confidence = str(raw_company.get("confidence") or "medium").casefold()
    if confidence == "low":
        return False
    try:
        score = float(raw_company.get("comparability_score", 0))
    except Exception:
        score = 0
    return score >= 4 or score == 0


def _profile_from_llm_company(raw_company: Any) -> CompanyProfile | None:
    if not isinstance(raw_company, dict):
        return None
    name = str(raw_company.get("name") or "").strip()
    ticker = str(raw_company.get("ticker") or "").strip().upper()
    local_code = str(raw_company.get("local_code") or "").strip()
    market = str(raw_company.get("market") or "Global").strip()
    known = _known_primary_profile({name, ticker, local_code, *(raw_company.get("aliases") or [])})
    if known:
        return _merge_llm_company_metadata(known, raw_company)
    found = _best_global_match(ticker or local_code or name, raw_company)
    if found:
        profile = _company_profile_from_global_result(found, ticker or local_code or name)
        return _merge_llm_company_metadata(profile, raw_company)
    if not name and not ticker:
        return None
    return CompanyProfile(
        ticker=ticker or local_code or name.upper(),
        name=name or ticker or local_code,
        market=market,
        role="LLM selected comparable",
        segment=str(raw_company.get("segment") or "LLM selected comparable").strip(),
        description=str(raw_company.get("reason") or "").strip(),
        source_hint="LLM comparable selection",
        local_code=local_code,
    )


def _best_global_match(query: str, raw_company: dict[str, Any]) -> dict[str, Any] | None:
    queries = [
        str(value).strip()
        for value in [
            query,
            raw_company.get("ticker"),
            raw_company.get("local_code"),
            raw_company.get("name"),
        ]
        if str(value or "").strip()
    ]
    queries = list(dict.fromkeys(queries))
    if not queries:
        return None
    results: list[dict[str, Any]] = []
    for candidate_query in queries:
        try:
            results = search_companies(candidate_query, limit=6)
        except Exception:
            results = []
        if results:
            break
    if not results:
        return None
    raw_name = str(raw_company.get("name") or "").casefold()
    raw_ticker = normalize_ticker(str(raw_company.get("ticker") or ""))
    raw_local_code = normalize_ticker(str(raw_company.get("local_code") or ""))
    for result in results:
        result_ticker = normalize_ticker(str(result.get("ticker") or ""))
        result_local_code = normalize_ticker(str(result.get("local_code") or ""))
        result_names = {
            str(result.get("name") or "").casefold(),
            str(result.get("name_en") or "").casefold(),
            *(str(alias).casefold() for alias in (result.get("aliases") or [])),
        }
        result_codes = {code for code in [result_ticker, result_local_code] if code}
        raw_codes = {code for code in [raw_ticker, raw_local_code] if code}
        if raw_codes and raw_codes & result_codes:
            return result
        if raw_name and raw_name in result_names:
            return result
    return None


def _merge_llm_company_metadata(profile: CompanyProfile, raw_company: dict[str, Any]) -> CompanyProfile:
    reason = str(raw_company.get("reason") or "").strip()
    segment = str(raw_company.get("segment") or profile.segment).strip()
    confidence = str(raw_company.get("confidence") or "").strip()
    description_parts = [part for part in [profile.description, reason, f"LLM confidence: {confidence}" if confidence else ""] if part]
    return replace(
        profile,
        role="LLM selected comparable" if raw_company.get("is_core_comparable", True) else "LLM selected cross-chain validator",
        segment=segment or profile.segment,
        description="; ".join(description_parts),
        source_hint=(profile.source_hint + " + LLM comparable selection").strip(" +"),
    )


def _safe_group_id(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip().lower())
    return cleaned.strip("_") or "llm_comparable_group"


def _discover_global_company(query: str) -> CompanyProfile | None:
    try:
        company = find_best_company(query)
    except Exception:
        company = None
    if not company:
        return None
    return _company_profile_from_global_result(company, query)


def _company_profile_from_global_result(company: dict[str, Any], query: str) -> CompanyProfile:
    ticker = str(company.get("ticker") or company.get("local_code") or query or "").strip().upper()
    local_code = str(company.get("local_code") or "").strip()
    name = str(company.get("name_en") or company.get("name") or query or ticker).strip()
    market = str(company.get("market") or company.get("country") or "Global listed company").strip()
    exchange = str(company.get("exchange") or "").strip()
    country = str(company.get("country") or "").strip()
    source = str(company.get("source") or "global company search").strip()
    ir_url = str(company.get("ir_url") or "").strip()
    aliases = tuple(str(alias).strip() for alias in (company.get("aliases") or []) if str(alias).strip())
    if "alphabet" in name.casefold() and ticker in {"GOOG", "GOOGL"}:
        ticker = "GOOGL"
        ir_url = ir_url or "https://abc.xyz/investor/"
    primary_profile = _known_primary_profile(
        {
            ticker,
            local_code,
            name,
            query,
            *aliases,
        }
    )
    if primary_profile:
        merged_aliases = tuple(
            dict.fromkeys(
                [
                    *primary_profile.aliases,
                    ticker,
                    local_code,
                    name,
                    query,
                    *aliases,
                ]
            )
        )
        return replace(
            primary_profile,
            source_hint=(primary_profile.source_hint or source or "global company search"),
            local_code=primary_profile.local_code or local_code,
            exchange=primary_profile.exchange or exchange,
            country=primary_profile.country or country,
            aliases=tuple(alias for alias in merged_aliases if alias),
        )
    if not str(company.get("cik") or "").strip():
        sec_primary = _sec_primary_result_for_name(name)
        if sec_primary:
            merged_aliases = tuple(
                dict.fromkeys(
                    [
                        ticker,
                        local_code,
                        name,
                        query,
                        *aliases,
                        *(sec_primary.get("aliases") or []),
                    ]
                )
            )
            sec_profile = _company_profile_from_global_result({**sec_primary, "aliases": merged_aliases}, name)
            return replace(
                sec_profile,
                source_hint=f"{source} + SEC primary listing match",
                aliases=tuple(alias for alias in merged_aliases if alias),
            )
    return CompanyProfile(
        ticker=ticker,
        name=name,
        market=market,
        role="global listed company",
        segment=_segment_hint(company),
        description=_global_company_description(company),
        cik=str(company.get("cik") or "").strip(),
        ir_url=ir_url,
        is_public=True,
        source_hint=source,
        local_code=local_code,
        exchange=exchange,
        country=country,
        aliases=aliases,
    )


def _known_primary_profile(candidates: set[str]) -> CompanyProfile | None:
    normalized_candidates = {
        value
        for candidate in candidates
        for value in {normalize_ticker(str(candidate)), str(candidate).casefold().strip()}
        if value
    }
    for company in [*AI_COMPANY_UNIVERSE.values(), *EXTRA_COMPANIES.values()]:
        if normalized_candidates & _company_identity_keys(company):
            return company
    return None


def _sec_primary_result_for_name(name: str) -> dict[str, Any] | None:
    normalized_name = name.casefold().replace(",", "").replace(".", "").strip()
    if not normalized_name or len(normalized_name) < 6:
        return None
    try:
        results = search_companies(name, limit=8)
    except Exception:
        return None
    for result in results:
        if not str(result.get("cik") or "").strip():
            continue
        result_name = str(result.get("name_en") or result.get("name") or "").casefold().replace(",", "").replace(".", "").strip()
        score = float(result.get("match_score") or 0)
        if result_name == normalized_name or score >= 0.93:
            return result
    return None


def _segment_hint(company: dict[str, Any]) -> str:
    exchange = str(company.get("exchange") or "").strip()
    market = str(company.get("market") or "").strip()
    if exchange or market:
        return "global listed company / " + " / ".join(value for value in [market, exchange] if value)
    return "global listed company"


def _global_company_description(company: dict[str, Any]) -> str:
    parts = [
        str(company.get("name_en") or company.get("name") or "").strip(),
        str(company.get("exchange") or "").strip(),
        str(company.get("country") or "").strip(),
    ]
    source = str(company.get("source") or "global company search").strip()
    text = " · ".join(part for part in parts if part)
    return f"{text}; discovered via {source}" if text else f"Discovered via {source}"


def _fallback_blueprints(target: CompanyProfile) -> list[dict[str, object]]:
    if "model" in target.segment.casefold() or not target.is_public:
        return [
            {
                "group_id": "private_model_watch",
                "title": "模型公司可比：融资、收入、价格与能力",
                "purpose": "交叉验证模型公司商业化、算力需求和竞争位置。",
                "selection_logic": "选择 frontier model 公司和主要云生态中的模型玩家。",
                "tickers": ["OPENAI", "ANTHROPIC", "XAI", "MSFT", "GOOGL"],
            },
            {
                "group_id": "compute_supply",
                "title": "算力供给验证：GPU、CSP 与服务器",
                "purpose": "用芯片、云和服务器公司信号验证模型公司算力扩张。",
                "selection_logic": "选择直接提供或采购 AI 训练 / 推理基础设施的公司。",
                "tickers": ["NVDA", "AMD", "MSFT", "AMZN", "SMCI"],
            },
        ]
    if target.source_hint and "global company search" in target.source_hint.casefold() or target.source_hint in {"巨潮资讯公司搜索", "Yahoo Finance 全球搜索", "SEC company_tickers"}:
        return []
    return [
        {
            "group_id": "ai_chain_default",
            "title": "AI 产业链默认精选组",
            "purpose": "先用 AI 产业链中最关键的芯片、云和基础设施公司建立研究起点。",
            "selection_logic": "目标公司暂无细分模板时，选择最能解释 AI 景气度的核心节点。",
            "tickers": ["NVDA", "AMD", "TSM", "MSFT", "AMZN"],
        },
        {
            "group_id": "infrastructure_default",
            "title": "基础设施交叉验证组",
            "purpose": "观察服务器、网络、电力散热等硬件交付信号。",
            "selection_logic": "这些公司对 AI 集群建设的订单和瓶颈变化较敏感。",
            "tickers": ["SMCI", "DELL", "ANET", "VRT"],
        },
        {
            "group_id": "private_model_watch",
            "title": "私有关键玩家观察：模型公司需求与融资信号",
            "purpose": "通过模型公司融资、ARR/收入传闻、API价格、用户增长、采购和合作交叉验证 AI 产业链景气度。",
            "selection_logic": "这些非上市模型公司不是财务可比公司，但会显著影响算力需求、CSP capex 和上游芯片/制造订单。",
            "tickers": ["OPENAI", "ANTHROPIC", "XAI"],
        },
    ]
