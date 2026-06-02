from __future__ import annotations

from dataclasses import replace

from .research_models import CompanyProfile, ComparableGroup


AI_COMPANY_UNIVERSE: dict[str, CompanyProfile] = {
    "NVDA": CompanyProfile("NVDA", "NVIDIA", "US", "AI accelerator leader", "GPU / AI accelerator", "AI training and inference GPU, networking, CUDA ecosystem", "0001045810", "https://investor.nvidia.com/"),
    "AMD": CompanyProfile("AMD", "Advanced Micro Devices", "US", "AI accelerator challenger", "GPU / AI accelerator", "Data center GPU, CPU and adaptive computing", "0000002488", "https://ir.amd.com/"),
    "AVGO": CompanyProfile("AVGO", "Broadcom", "US", "custom silicon and networking", "ASIC / networking", "AI custom silicon, switching, connectivity and software", "0001730168", "https://investors.broadcom.com/"),
    "MRVL": CompanyProfile("MRVL", "Marvell Technology", "US", "data infrastructure silicon", "ASIC / networking", "Custom silicon, optical DSP and data infrastructure chips", "0001835632", "https://investor.marvell.com/"),
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
        if query.casefold() in {company.name.casefold(), company.ticker.casefold()}:
            return company
    return CompanyProfile(ticker or query, query.strip() or ticker, "Unknown", "target company", "auto-discovered", "User-entered target")


def all_research_companies() -> dict[str, CompanyProfile]:
    merged = dict(AI_COMPANY_UNIVERSE)
    merged.update(EXTRA_COMPANIES)
    return merged


def recommend_comparable_groups(target_query: str, max_core_companies: int = 5) -> list[ComparableGroup]:
    target = get_company_profile(target_query)
    universe = all_research_companies()
    blueprints = TARGET_GROUP_BLUEPRINTS.get(target.ticker.upper())
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
