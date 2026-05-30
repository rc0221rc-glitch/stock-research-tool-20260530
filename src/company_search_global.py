from __future__ import annotations

import difflib
from functools import lru_cache
from typing import Any

from .utils import normalize_text, request_json


LOCAL_COMPANIES: list[dict[str, Any]] = [
    {
        "name": "苹果",
        "name_en": "Apple Inc.",
        "ticker": "AAPL",
        "local_code": "AAPL",
        "market": "美股",
        "exchange": "NASDAQ",
        "country": "美国",
        "flag": "🇺🇸",
        "ir_url": "https://investor.apple.com/",
        "cik": "0000320193",
        "aliases": ["Apple", "AAPL", "苹果公司"],
    },
    {
        "name": "微软",
        "name_en": "Microsoft Corporation",
        "ticker": "MSFT",
        "local_code": "MSFT",
        "market": "美股",
        "exchange": "NASDAQ",
        "country": "美国",
        "flag": "🇺🇸",
        "ir_url": "https://www.microsoft.com/en-us/investor",
        "cik": "0000789019",
        "aliases": ["Microsoft", "MSFT"],
    },
    {
        "name": "英伟达",
        "name_en": "NVIDIA Corporation",
        "ticker": "NVDA",
        "local_code": "NVDA",
        "market": "美股",
        "exchange": "NASDAQ",
        "country": "美国",
        "flag": "🇺🇸",
        "ir_url": "https://investor.nvidia.com/",
        "cik": "0001045810",
        "aliases": ["NVIDIA", "NVDA"],
    },
    {
        "name": "特斯拉",
        "name_en": "Tesla, Inc.",
        "ticker": "TSLA",
        "local_code": "TSLA",
        "market": "美股",
        "exchange": "NASDAQ",
        "country": "美国",
        "flag": "🇺🇸",
        "ir_url": "https://ir.tesla.com/",
        "cik": "0001318605",
        "aliases": ["Tesla", "TSLA"],
    },
    {
        "name": "腾讯控股",
        "name_en": "Tencent Holdings Limited",
        "ticker": "TCEHY",
        "local_code": "0700",
        "market": "港股",
        "exchange": "HKEX",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://www.tencent.com/zh-cn/investors.html",
        "cik": "",
        "aliases": ["腾讯", "Tencent", "0700", "700", "TCEHY"],
    },
    {
        "name": "阿里巴巴",
        "name_en": "Alibaba Group Holding Limited",
        "ticker": "BABA",
        "local_code": "9988",
        "market": "港股",
        "exchange": "HKEX / NYSE",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://www.alibabagroup.com/en-US/ir",
        "cik": "0001577552",
        "aliases": ["Alibaba", "阿里", "9988", "BABA"],
    },
    {
        "name": "美团",
        "name_en": "Meituan",
        "ticker": "MPNGY",
        "local_code": "3690",
        "market": "港股",
        "exchange": "HKEX",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://about.meituan.com/en/investor-relations",
        "cik": "",
        "aliases": ["Meituan", "3690"],
    },
    {
        "name": "小米集团",
        "name_en": "Xiaomi Corporation",
        "ticker": "XIACY",
        "local_code": "1810",
        "market": "港股",
        "exchange": "HKEX",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://ir.mi.com/",
        "cik": "",
        "aliases": ["小米", "Xiaomi", "1810"],
    },
    {
        "name": "京东集团",
        "name_en": "JD.com, Inc.",
        "ticker": "JD",
        "local_code": "9618",
        "market": "港股",
        "exchange": "HKEX / NASDAQ",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://ir.jd.com/",
        "cik": "0001549802",
        "aliases": ["京东", "JD", "9618"],
    },
    {
        "name": "百度集团",
        "name_en": "Baidu, Inc.",
        "ticker": "BIDU",
        "local_code": "9888",
        "market": "港股",
        "exchange": "HKEX / NASDAQ",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://ir.baidu.com/",
        "cik": "0001329099",
        "aliases": ["百度", "Baidu", "9888", "BIDU"],
    },
    {
        "name": "中芯国际",
        "name_en": "Semiconductor Manufacturing International Corporation",
        "ticker": "SMICY",
        "local_code": "0981",
        "market": "港股",
        "exchange": "HKEX / SSE STAR",
        "country": "中国",
        "flag": "🇭🇰",
        "ir_url": "https://www.smics.com/en/site/company_financialSummary",
        "cik": "",
        "aliases": ["SMIC", "中芯", "0981", "688981"],
    },
    {
        "name": "比亚迪",
        "name_en": "BYD Company Limited",
        "ticker": "BYDDY",
        "local_code": "1211",
        "market": "港股",
        "exchange": "HKEX / SZSE",
        "country": "中国",
        "flag": "🇭🇰",
        "ir_url": "https://www.bydglobal.com/en/InvestorNotice.html",
        "cik": "",
        "aliases": ["BYD", "1211", "002594"],
    },
    {
        "name": "理想汽车",
        "name_en": "Li Auto Inc.",
        "ticker": "LI",
        "local_code": "2015",
        "market": "港股",
        "exchange": "HKEX / NASDAQ",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://ir.lixiang.com/",
        "cik": "0001791706",
        "aliases": ["理想", "Li Auto", "2015", "LI"],
    },
    {
        "name": "小鹏汽车",
        "name_en": "XPeng Inc.",
        "ticker": "XPEV",
        "local_code": "9868",
        "market": "港股",
        "exchange": "HKEX / NYSE",
        "country": "中国香港",
        "flag": "🇭🇰",
        "ir_url": "https://ir.xiaopeng.com/",
        "cik": "0001810997",
        "aliases": ["小鹏", "XPeng", "9868", "XPEV"],
    },
    {
        "name": "贵州茅台",
        "name_en": "Kweichow Moutai Co., Ltd.",
        "ticker": "",
        "local_code": "600519",
        "market": "A股",
        "exchange": "SSE",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://www.moutaichina.com/",
        "cik": "",
        "aliases": ["茅台", "Kweichow Moutai", "600519"],
    },
    {
        "name": "宁德时代",
        "name_en": "Contemporary Amperex Technology Co., Limited",
        "ticker": "",
        "local_code": "300750",
        "market": "A股",
        "exchange": "SZSE",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://www.catl.com/",
        "cik": "",
        "aliases": ["CATL", "300750"],
    },
    {
        "name": "中国平安",
        "name_en": "Ping An Insurance (Group) Company of China, Ltd.",
        "ticker": "",
        "local_code": "601318",
        "market": "A股",
        "exchange": "SSE / HKEX",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://group.pingan.com/investor_relations/",
        "cik": "",
        "aliases": ["平安", "Ping An", "601318", "2318"],
    },
    {
        "name": "招商银行",
        "name_en": "China Merchants Bank Co., Ltd.",
        "ticker": "",
        "local_code": "600036",
        "market": "A股",
        "exchange": "SSE / HKEX",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://www.cmbchina.com/cmbir/",
        "cik": "",
        "aliases": ["招行", "CMB", "600036", "3968"],
    },
    {
        "name": "海康威视",
        "name_en": "Hangzhou Hikvision Digital Technology Co., Ltd.",
        "ticker": "",
        "local_code": "002415",
        "market": "A股",
        "exchange": "SZSE",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://www.hikvision.com/en/about-us/investor-relations/",
        "cik": "",
        "aliases": ["Hikvision", "002415"],
    },
    {
        "name": "迈瑞医疗",
        "name_en": "Shenzhen Mindray Bio-Medical Electronics Co., Ltd.",
        "ticker": "",
        "local_code": "300760",
        "market": "A股",
        "exchange": "SZSE",
        "country": "中国",
        "flag": "🇨🇳",
        "ir_url": "https://www.mindray.com/en/investor-relations",
        "cik": "",
        "aliases": ["Mindray", "300760"],
    },
    {
        "name": "台积电",
        "name_en": "Taiwan Semiconductor Manufacturing Company Limited",
        "ticker": "TSM",
        "local_code": "2330",
        "market": "台股",
        "exchange": "TWSE / NYSE",
        "country": "中国台湾",
        "flag": "🇹🇼",
        "ir_url": "https://investor.tsmc.com/",
        "cik": "0001046179",
        "aliases": ["TSMC", "台積電", "2330", "TSM"],
    },
    {
        "name": "联发科",
        "name_en": "MediaTek Inc.",
        "ticker": "MDTKF",
        "local_code": "2454",
        "market": "台股",
        "exchange": "TWSE",
        "country": "中国台湾",
        "flag": "🇹🇼",
        "ir_url": "https://corp.mediatek.com/investors",
        "cik": "",
        "aliases": ["MediaTek", "联发", "2454"],
    },
    {
        "name": "鸿海精密",
        "name_en": "Hon Hai Precision Industry Co., Ltd.",
        "ticker": "HNHPF",
        "local_code": "2317",
        "market": "台股",
        "exchange": "TWSE",
        "country": "中国台湾",
        "flag": "🇹🇼",
        "ir_url": "https://www.honhai.com/en-us/investor-relations/financial-information",
        "cik": "",
        "aliases": ["鸿海", "Foxconn", "Hon Hai", "2317"],
    },
    {
        "name": "联电",
        "name_en": "United Microelectronics Corporation",
        "ticker": "UMC",
        "local_code": "2303",
        "market": "台股",
        "exchange": "TWSE / NYSE",
        "country": "中国台湾",
        "flag": "🇹🇼",
        "ir_url": "https://www.umc.com/en/IR/financial_reports",
        "cik": "0001033767",
        "aliases": ["UMC", "联华电子", "2303"],
    },
    {
        "name": "三星电子",
        "name_en": "Samsung Electronics Co., Ltd.",
        "ticker": "SSNLF",
        "local_code": "005930",
        "market": "韩股",
        "exchange": "KRX",
        "country": "韩国",
        "flag": "🇰🇷",
        "ir_url": "https://www.samsung.com/global/ir/",
        "cik": "0001046257",
        "aliases": ["Samsung", "三星", "005930"],
    },
    {
        "name": "SK 海力士",
        "name_en": "SK hynix Inc.",
        "ticker": "HXSCF",
        "local_code": "000660",
        "market": "韩股",
        "exchange": "KRX",
        "country": "韩国",
        "flag": "🇰🇷",
        "ir_url": "https://www.skhynix.com/eng/ir/main.do",
        "cik": "",
        "aliases": ["SK Hynix", "海力士", "000660"],
    },
    {
        "name": "丰田汽车",
        "name_en": "Toyota Motor Corporation",
        "ticker": "TM",
        "local_code": "7203",
        "market": "日股",
        "exchange": "TSE / NYSE",
        "country": "日本",
        "flag": "🇯🇵",
        "ir_url": "https://global.toyota/en/ir/",
        "cik": "0001094517",
        "aliases": ["Toyota", "丰田", "7203", "TM"],
    },
    {
        "name": "索尼集团",
        "name_en": "Sony Group Corporation",
        "ticker": "SONY",
        "local_code": "6758",
        "market": "日股",
        "exchange": "TSE / NYSE",
        "country": "日本",
        "flag": "🇯🇵",
        "ir_url": "https://www.sony.com/en/SonyInfo/IR/",
        "cik": "0000313838",
        "aliases": ["Sony", "索尼", "6758"],
    },
    {
        "name": "软银集团",
        "name_en": "SoftBank Group Corp.",
        "ticker": "SFTBY",
        "local_code": "9984",
        "market": "日股",
        "exchange": "TSE",
        "country": "日本",
        "flag": "🇯🇵",
        "ir_url": "https://group.softbank/en/ir",
        "cik": "",
        "aliases": ["SoftBank", "软银", "9984"],
    },
    {
        "name": "任天堂",
        "name_en": "Nintendo Co., Ltd.",
        "ticker": "NTDOY",
        "local_code": "7974",
        "market": "日股",
        "exchange": "TSE",
        "country": "日本",
        "flag": "🇯🇵",
        "ir_url": "https://www.nintendo.co.jp/ir/en/",
        "cik": "",
        "aliases": ["Nintendo", "7974"],
    },
    {
        "name": "英飞凌",
        "name_en": "Infineon Technologies AG",
        "ticker": "IFNNY",
        "local_code": "IFX",
        "market": "欧洲",
        "exchange": "XETRA / OTC ADR",
        "country": "德国",
        "flag": "🇩🇪",
        "ir_url": "https://www.infineon.com/cms/en/about-infineon/investor/",
        "cik": "",
        "aliases": ["Infineon", "IFNNY", "IFX"],
    },
    {
        "name": "SAP",
        "name_en": "SAP SE",
        "ticker": "SAP",
        "local_code": "SAP",
        "market": "欧洲",
        "exchange": "XETRA / NYSE",
        "country": "德国",
        "flag": "🇩🇪",
        "ir_url": "https://www.sap.com/investors/en.html",
        "cik": "0001000184",
        "aliases": ["SAP SE"],
    },
    {
        "name": "西门子",
        "name_en": "Siemens AG",
        "ticker": "SIEGY",
        "local_code": "SIE",
        "market": "欧洲",
        "exchange": "XETRA",
        "country": "德国",
        "flag": "🇩🇪",
        "ir_url": "https://www.siemens.com/global/en/company/investor-relations.html",
        "cik": "",
        "aliases": ["Siemens", "SIE"],
    },
    {
        "name": "宝马",
        "name_en": "Bayerische Motoren Werke AG",
        "ticker": "BMWYY",
        "local_code": "BMW",
        "market": "欧洲",
        "exchange": "XETRA",
        "country": "德国",
        "flag": "🇩🇪",
        "ir_url": "https://www.bmwgroup.com/en/investor-relations.html",
        "cik": "",
        "aliases": ["BMW"],
    },
    {
        "name": "大众汽车",
        "name_en": "Volkswagen AG",
        "ticker": "VWAGY",
        "local_code": "VOW3",
        "market": "欧洲",
        "exchange": "XETRA",
        "country": "德国",
        "flag": "🇩🇪",
        "ir_url": "https://www.volkswagen-group.com/en/investor-relations-15966",
        "cik": "",
        "aliases": ["Volkswagen", "VOW3"],
    },
    {
        "name": "阿斯麦",
        "name_en": "ASML Holding N.V.",
        "ticker": "ASML",
        "local_code": "ASML",
        "market": "欧洲",
        "exchange": "Euronext / NASDAQ",
        "country": "荷兰",
        "flag": "🇳🇱",
        "ir_url": "https://www.asml.com/en/investors",
        "cik": "0000937966",
        "aliases": ["ASML", "阿斯麦控股"],
    },
    {
        "name": "诺华",
        "name_en": "Novartis AG",
        "ticker": "NVS",
        "local_code": "NOVN",
        "market": "欧洲",
        "exchange": "SIX / NYSE",
        "country": "瑞士",
        "flag": "🇨🇭",
        "ir_url": "https://www.novartis.com/investors",
        "cik": "0001114448",
        "aliases": ["Novartis", "NVS", "NOVN"],
    },
    {
        "name": "罗氏",
        "name_en": "Roche Holding AG",
        "ticker": "RHHBY",
        "local_code": "ROG",
        "market": "欧洲",
        "exchange": "SIX",
        "country": "瑞士",
        "flag": "🇨🇭",
        "ir_url": "https://www.roche.com/investors",
        "cik": "",
        "aliases": ["Roche", "ROG"],
    },
    {
        "name": "雀巢",
        "name_en": "Nestle S.A.",
        "ticker": "NSRGY",
        "local_code": "NESN",
        "market": "欧洲",
        "exchange": "SIX",
        "country": "瑞士",
        "flag": "🇨🇭",
        "ir_url": "https://www.nestle.com/investors",
        "cik": "",
        "aliases": ["Nestle", "Nestlé", "NESN"],
    },
    {
        "name": "路威酩轩",
        "name_en": "LVMH Moet Hennessy Louis Vuitton SE",
        "ticker": "LVMUY",
        "local_code": "MC",
        "market": "欧洲",
        "exchange": "Euronext Paris",
        "country": "法国",
        "flag": "🇫🇷",
        "ir_url": "https://www.lvmh.com/investors",
        "cik": "",
        "aliases": ["LVMH", "MC"],
    },
    {
        "name": "空中客车",
        "name_en": "Airbus SE",
        "ticker": "EADSY",
        "local_code": "AIR",
        "market": "欧洲",
        "exchange": "Euronext Paris",
        "country": "法国",
        "flag": "🇫🇷",
        "ir_url": "https://www.airbus.com/en/investors",
        "cik": "",
        "aliases": ["Airbus", "AIR"],
    },
    {
        "name": "英国石油",
        "name_en": "BP p.l.c.",
        "ticker": "BP",
        "local_code": "BP",
        "market": "欧洲",
        "exchange": "LSE / NYSE",
        "country": "英国",
        "flag": "🇬🇧",
        "ir_url": "https://www.bp.com/en/global/corporate/investors.html",
        "cik": "0000313807",
        "aliases": ["BP plc"],
    },
    {
        "name": "意法半导体",
        "name_en": "STMicroelectronics N.V.",
        "ticker": "STM",
        "local_code": "STM",
        "market": "欧洲",
        "exchange": "Euronext / NYSE",
        "country": "瑞士",
        "flag": "🇨🇭",
        "ir_url": "https://investors.st.com/",
        "cik": "0000937875",
        "aliases": ["STMicroelectronics", "STM"],
    },
]


@lru_cache(maxsize=1)
def _sec_company_tickers() -> list[dict[str, Any]]:
    try:
        raw = request_json("https://www.sec.gov/files/company_tickers.json", timeout=10)
        return [
            {
                "name": item.get("title", ""),
                "name_en": item.get("title", ""),
                "ticker": item.get("ticker", ""),
                "local_code": item.get("ticker", ""),
                "market": "美股",
                "exchange": "SEC",
                "country": "美国",
                "flag": "🇺🇸",
                "ir_url": "",
                "cik": str(item.get("cik_str", "")).zfill(10),
                "aliases": [item.get("ticker", ""), item.get("title", "")],
                "source": "SEC company_tickers",
            }
            for item in raw.values()
        ]
    except Exception:
        return []


def _score_company(query: str, company: dict[str, Any]) -> float:
    normalized_query = normalize_text(query)
    fields = [
        company.get("name", ""),
        company.get("name_en", ""),
        company.get("ticker", ""),
        company.get("local_code", ""),
        *(company.get("aliases", []) or []),
    ]
    normalized_fields = [normalize_text(field) for field in fields if field]
    if not normalized_query:
        return 0
    if normalized_query.isdigit():
        query_number = normalized_query.lstrip("0") or "0"
        for index, field in enumerate(normalized_fields):
            digits = "".join(ch for ch in field if ch.isdigit())
            if digits and (digits.lstrip("0") or "0") == query_number:
                return 1.0 - index * 0.01
        return 0
    for index, field in enumerate(normalized_fields):
        if normalized_query == field:
            return 1.0 - index * 0.01
    is_short_ascii = normalized_query.isascii() and normalized_query.isalnum() and len(normalized_query) <= 5
    if is_short_ascii:
        for field in normalized_fields:
            if len(normalized_query) >= 4 and len(field) >= len(normalized_query) + 3 and normalized_query in field:
                ratio = len(normalized_query) / max(len(field), 1)
                return 0.80 + min(ratio, 1) * 0.08
        return 0
    for field in normalized_fields:
        if len(normalized_query) >= 2 and (normalized_query in field or (len(field) >= 4 and field in normalized_query)):
            ratio = len(normalized_query) / max(len(field), 1)
            return 0.84 + min(ratio, 1) * 0.1
    if len(normalized_query) <= 3:
        return 0
    best = max((difflib.SequenceMatcher(None, normalized_query, field).ratio() for field in normalized_fields), default=0)
    return best if best >= 0.68 else 0


def _merge_results(primary: list[dict[str, Any]], secondary: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for company in [*primary, *secondary]:
        keys = [company.get("ticker", ""), company.get("local_code", ""), company.get("cik", ""), company.get("name_en", "")]
        key = "|".join(str(item).casefold() for item in keys if item)
        if key in seen:
            continue
        seen.add(key)
        merged.append(company)
        if len(merged) >= limit:
            break
    return merged


def search_companies(query: str, limit: int = 12, include_sec: bool = True) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    local_scored = []
    for company in LOCAL_COMPANIES:
        score = _score_company(query, company)
        if score >= 0.62:
            enriched = dict(company)
            enriched["match_score"] = score
            enriched["source"] = "本地公司库"
            local_scored.append(enriched)
    local_scored.sort(key=lambda item: item["match_score"], reverse=True)

    sec_scored: list[dict[str, Any]] = []
    if include_sec:
        for company in _sec_company_tickers():
            score = _score_company(query, company)
            if score >= 0.58:
                enriched = dict(company)
                enriched["match_score"] = score
                sec_scored.append(enriched)
        sec_scored.sort(key=lambda item: item["match_score"], reverse=True)
    return _merge_results(local_scored, sec_scored, limit)


def find_best_company(query: str) -> dict[str, Any] | None:
    results = search_companies(query, limit=1)
    return results[0] if results else None
