#!/usr/bin/env python3
"""Harvest concept/metric catalogs from edgartools, edgar_analytics, and Finnhub.

Purpose: ontology *expansion and gap discovery* — not a live EDGAR calculation engine.
Writes machine-readable catalogs under ontology/discovery/ and a gap report.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ontology" / "discovery"
ONTOLOGY_JSON = ROOT / "taxonomy-data.json"
GAAP_CACHE = ROOT / "data" / "gaap-only.json"

# Finnhub /stock/metric keys commonly returned for metric=all (catalog only).
# Optional live sample via FINNHUB_API_KEY expands this set from a real response.
FINNHUB_METRIC_CATALOG = [
    ("10DayAverageTradingVolume", "liquidity", "Trading volume"),
    ("13WeekPriceReturnDaily", "valuation", "Price return"),
    ("26WeekPriceReturnDaily", "valuation", "Price return"),
    ("3MonthAverageTradingVolume", "liquidity", "Trading volume"),
    ("52WeekHigh", "valuation", "Price level"),
    ("52WeekLow", "valuation", "Price level"),
    ("52WeekPriceReturnDaily", "valuation", "Price return"),
    ("5DayPriceReturnDaily", "valuation", "Price return"),
    ("assetTurnoverAnnual", "efficiency", "Revenue / Assets"),
    ("assetTurnoverTTM", "efficiency", "Revenue / Assets"),
    ("bookValuePerShareAnnual", "per-share", "Equity / Shares"),
    ("bookValuePerShareQuarterly", "per-share", "Equity / Shares"),
    ("currentRatioAnnual", "liquidity", "Current Assets / Current Liabilities"),
    ("currentRatioQuarterly", "liquidity", "Current Assets / Current Liabilities"),
    ("ebitdPerShareAnnual", "per-share", "EBITDA / Shares"),
    ("ebitdPerShareTTM", "per-share", "EBITDA / Shares"),
    ("ebitdaCagr5Y", "profitability", "EBITDA CAGR"),
    ("ebitdaMarginAnnual", "profitability", "EBITDA / Revenue"),
    ("ebitdaMarginTTM", "profitability", "EBITDA / Revenue"),
    ("epsAnnual", "per-share", "Net Income / Shares"),
    ("epsBasicExclExtraItemsAnnual", "per-share", "EPS basic ex items"),
    ("epsGrowth3Y", "profitability", "EPS growth"),
    ("epsGrowth5Y", "profitability", "EPS growth"),
    ("epsGrowthQuarterlyYoy", "profitability", "EPS growth YoY"),
    ("epsGrowthTTMYoy", "profitability", "EPS growth YoY"),
    ("epsTTM", "per-share", "EPS TTM"),
    ("enterpriseValue", "valuation", "Market Cap + Net Debt"),
    ("evEbitdaAnnual", "valuation", "EV / EBITDA"),
    ("evEbitdaTTM", "valuation", "EV / EBITDA"),
    ("freeCashFlowAnnual", "cashflow", "OCF - CapEx"),
    ("freeCashFlowPerShareTTM", "per-share", "FCF / Shares"),
    ("grossMarginAnnual", "profitability", "Gross Profit / Revenue"),
    ("grossMarginTTM", "profitability", "Gross Profit / Revenue"),
    ("inventoryTurnoverAnnual", "efficiency", "COGS / Inventory"),
    ("inventoryTurnoverTTM", "efficiency", "COGS / Inventory"),
    ("longTermDebt/equityAnnual", "leverage", "LT Debt / Equity"),
    ("longTermDebt/equityQuarterly", "leverage", "LT Debt / Equity"),
    ("marketCapitalization", "valuation", "Shares x Price"),
    ("netDebtAnnual", "leverage", "Debt - Cash"),
    ("netInterestCoverageAnnual", "leverage", "EBIT / Interest"),
    ("netMarginAnnual", "profitability", "Net Income / Revenue"),
    ("netMarginTTM", "profitability", "Net Income / Revenue"),
    ("netProfitMarginAnnual", "profitability", "Net Income / Revenue"),
    ("netProfitMarginTTM", "profitability", "Net Income / Revenue"),
    ("operatingMarginAnnual", "profitability", "Operating Income / Revenue"),
    ("operatingMarginTTM", "profitability", "Operating Income / Revenue"),
    ("payoutRatioAnnual", "cashflow", "Dividends / Net Income"),
    ("payoutRatioTTM", "cashflow", "Dividends / Net Income"),
    ("pbAnnual", "valuation", "Price / Book"),
    ("pbQuarterly", "valuation", "Price / Book"),
    ("peAnnual", "valuation", "Price / EPS"),
    ("peTTM", "valuation", "Price / EPS TTM"),
    ("pfcfShareAnnual", "valuation", "Price / FCF per share"),
    ("pfcfShareTTM", "valuation", "Price / FCF per share"),
    ("psAnnual", "valuation", "Price / Sales"),
    ("psTTM", "valuation", "Price / Sales"),
    ("ptbvAnnual", "valuation", "Price / Tangible Book"),
    ("ptbvQuarterly", "valuation", "Price / Tangible Book"),
    ("quickRatioAnnual", "liquidity", "(CA - Inventory) / CL"),
    ("quickRatioQuarterly", "liquidity", "(CA - Inventory) / CL"),
    ("receivablesTurnoverAnnual", "efficiency", "Revenue / AR"),
    ("receivablesTurnoverTTM", "efficiency", "Revenue / AR"),
    ("roaAnnual", "returns", "Net Income / Assets"),
    ("roaRfy", "returns", "ROA"),
    ("roaTTM", "returns", "ROA TTM"),
    ("roeAnnual", "returns", "Net Income / Equity"),
    ("roeRfy", "returns", "ROE"),
    ("roeTTM", "returns", "ROE TTM"),
    ("roiAnnual", "returns", "Return on investment"),
    ("roiTTM", "returns", "Return on investment"),
    ("revenueGrowth3Y", "profitability", "Revenue CAGR"),
    ("revenueGrowth5Y", "profitability", "Revenue CAGR"),
    ("revenueGrowthQuarterlyYoy", "profitability", "Revenue growth YoY"),
    ("revenueGrowthTTMYoy", "profitability", "Revenue growth YoY"),
    ("revenuePerShareAnnual", "per-share", "Revenue / Shares"),
    ("revenuePerShareTTM", "per-share", "Revenue / Shares"),
    ("revenueShareGrowth5Y", "per-share", "Revenue/share growth"),
    ("tangibleBookValuePerShareAnnual", "per-share", "Tangible equity / Shares"),
    ("tangibleBookValuePerShareQuarterly", "per-share", "Tangible equity / Shares"),
    ("totalDebt/totalEquityAnnual", "leverage", "Total Debt / Equity"),
    ("totalDebt/totalEquityQuarterly", "leverage", "Total Debt / Equity"),
]

# edgar_analytics derived metrics (from METRICS_REFERENCE) with formula text + input synonym keys.
EDGAR_ANALYTICS_DERIVED = [
    {"id": "Gross Margin %", "category": "profitability", "formula": "Gross Profit / Revenue x 100", "inputs": ["gross_profit", "revenue"]},
    {"id": "Operating Margin %", "category": "profitability", "formula": "Operating Income / Revenue x 100", "inputs": ["operating_income", "revenue"]},
    {"id": "Net Margin %", "category": "profitability", "formula": "Net Income / Revenue x 100", "inputs": ["net_income", "revenue"]},
    {"id": "EBIT (approx)", "category": "profitability", "formula": "Net Income + Interest + Tax", "inputs": ["net_income", "interest_expense", "income_tax_expense"]},
    {"id": "EBIT (standard)", "category": "profitability", "formula": "Operating Income", "inputs": ["operating_income"]},
    {"id": "EBITDA (approx)", "category": "profitability", "formula": "EBIT (approx) + D&A", "inputs": ["net_income", "interest_expense", "income_tax_expense", "depreciation_amortization"]},
    {"id": "EBITDA (standard)", "category": "profitability", "formula": "EBIT (standard) + D&A", "inputs": ["operating_income", "depreciation_amortization"]},
    {"id": "Current Ratio", "category": "liquidity", "formula": "Current Assets / Current Liabilities", "inputs": ["current_assets", "current_liabilities"]},
    {"id": "Quick Ratio", "category": "liquidity", "formula": "(Current Assets - Inventory) / Current Liabilities", "inputs": ["current_assets", "inventory", "current_liabilities"]},
    {"id": "Cash Ratio", "category": "liquidity", "formula": "Cash / Current Liabilities", "inputs": ["cash_equivalents", "current_liabilities"]},
    {"id": "Debt-to-Equity", "category": "leverage", "formula": "Total Liabilities / Total Equity", "inputs": ["total_liabilities", "total_equity"]},
    {"id": "Debt/Total Capital", "category": "leverage", "formula": "(ST Debt + LT Debt) / (ST Debt + LT Debt + Equity)", "inputs": ["short_term_debt", "long_term_debt", "total_equity"]},
    {"id": "Equity Ratio %", "category": "leverage", "formula": "Total Equity / Total Assets x 100", "inputs": ["total_equity", "total_assets"]},
    {"id": "Interest Coverage", "category": "leverage", "formula": "EBIT (standard) / Interest Expense", "inputs": ["operating_income", "interest_expense"]},
    {"id": "Net Debt", "category": "leverage", "formula": "ST Debt + LT Debt + Lease Liabilities - Cash", "inputs": ["short_term_debt", "long_term_debt", "operating_lease_liabilities", "finance_lease_liabilities", "cash_equivalents"]},
    {"id": "Net Debt/EBITDA", "category": "leverage", "formula": "Financial Net Debt / EBITDA (standard)", "inputs": ["short_term_debt", "long_term_debt", "cash_equivalents", "operating_income", "depreciation_amortization"]},
    {"id": "Lease Liabilities Ratio %", "category": "leverage", "formula": "(Operating + Finance Leases) / Total Assets x 100", "inputs": ["operating_lease_liabilities", "finance_lease_liabilities", "total_assets"]},
    {"id": "Cash from Operations", "category": "cashflow", "formula": "Operating Cash Flow", "inputs": ["cash_flow_operating"]},
    {"id": "Free Cash Flow", "category": "cashflow", "formula": "OCF - CapEx", "inputs": ["cash_flow_operating", "capital_expenditures"]},
    {"id": "Cash Flow Coverage", "category": "cashflow", "formula": "OCF / Current Liabilities", "inputs": ["cash_flow_operating", "current_liabilities"]},
    {"id": "Fixed Charge Coverage", "category": "cashflow", "formula": "(EBIT + Lease Expense) / (Interest + Lease Expense)", "inputs": ["operating_income", "interest_expense", "operating_lease_liabilities"]},
    {"id": "ROE %", "category": "returns", "formula": "Net Income / Total Equity x 100", "inputs": ["net_income", "total_equity"]},
    {"id": "ROA %", "category": "returns", "formula": "Net Income / Total Assets x 100", "inputs": ["net_income", "total_assets"]},
    {"id": "Accruals Ratio", "category": "quality", "formula": "(Net Income - OCF) / Total Assets", "inputs": ["net_income", "cash_flow_operating", "total_assets"]},
    {"id": "Earnings Quality", "category": "quality", "formula": "OCF / Net Income", "inputs": ["cash_flow_operating", "net_income"]},
    {"id": "Sloan Accrual", "category": "quality", "formula": "(ΔWC - ΔCash - D&A) / Avg Total Assets", "inputs": ["current_assets", "current_liabilities", "cash_equivalents", "depreciation_amortization", "total_assets"]},
    {"id": "Intangible Ratio %", "category": "composition", "formula": "Intangible Assets / Total Assets x 100", "inputs": ["intangible_assets", "total_assets"]},
    {"id": "Goodwill Ratio %", "category": "composition", "formula": "Goodwill / Total Assets x 100", "inputs": ["goodwill", "total_assets"]},
    {"id": "Tangible Equity", "category": "composition", "formula": "Total Equity - Intangibles - Goodwill", "inputs": ["total_equity", "intangible_assets", "goodwill"]},
    {"id": "P/E Ratio", "category": "valuation", "formula": "Price / Diluted EPS", "inputs": ["earnings_per_share_diluted"]},
    {"id": "P/B Ratio", "category": "valuation", "formula": "Market Cap / Total Equity", "inputs": ["total_equity"]},
    {"id": "EV/EBITDA", "category": "valuation", "formula": "Enterprise Value / EBITDA", "inputs": ["operating_income", "depreciation_amortization", "cash_equivalents", "short_term_debt", "long_term_debt"]},
    {"id": "Earnings Yield", "category": "valuation", "formula": "1 / P/E", "inputs": ["earnings_per_share_diluted"]},
    {"id": "DSO", "category": "working-capital", "formula": "AR / (Revenue / 365)", "inputs": ["accounts_receivable", "revenue"]},
    {"id": "DIO", "category": "working-capital", "formula": "Inventory / (COGS / 365)", "inputs": ["inventory", "cost_of_revenue"]},
    {"id": "DPO", "category": "working-capital", "formula": "AP / (COGS / 365)", "inputs": ["accounts_payable", "cost_of_revenue"]},
    {"id": "Cash Conversion Cycle", "category": "working-capital", "formula": "DSO + DIO - DPO", "inputs": ["accounts_receivable", "inventory", "accounts_payable", "revenue", "cost_of_revenue"]},
    {"id": "NOPAT", "category": "returns", "formula": "Operating Income x (1 - Tax Rate)", "inputs": ["operating_income", "income_tax_expense", "income_before_taxes"]},
    {"id": "Invested Capital", "category": "returns", "formula": "Equity + ST Debt + LT Debt - Cash", "inputs": ["total_equity", "short_term_debt", "long_term_debt", "cash_equivalents"]},
    {"id": "ROIC %", "category": "returns", "formula": "NOPAT / Invested Capital x 100", "inputs": ["operating_income", "income_tax_expense", "income_before_taxes", "total_equity", "short_term_debt", "long_term_debt", "cash_equivalents"]},
    {"id": "Asset Turnover", "category": "efficiency", "formula": "Revenue / Total Assets", "inputs": ["revenue", "total_assets"]},
    {"id": "Piotroski F-Score", "category": "scoring", "formula": "9 binary fundamental tests (0-9)", "inputs": ["net_income", "cash_flow_operating", "total_assets", "total_equity", "long_term_debt", "current_assets", "current_liabilities", "gross_profit", "revenue", "common_shares_outstanding"]},
    {"id": "Altman Z-Score", "category": "scoring", "formula": "Bankruptcy probability model", "inputs": ["current_assets", "current_liabilities", "total_assets", "retained_earnings", "operating_income", "total_liabilities", "total_equity", "revenue"]},
    {"id": "Beneish M-Score", "category": "scoring", "formula": "Earnings manipulation probability model", "inputs": ["accounts_receivable", "revenue", "gross_profit", "total_assets", "current_assets", "ppe_net", "depreciation_amortization", "general_administrative", "total_liabilities", "current_liabilities", "net_income", "cash_flow_operating"]},
]


def slug(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def normalize_gaap_tag(tag: str) -> str | None:
    t = tag.strip()
    if t.startswith("us-gaap:"):
        return t[len("us-gaap:") :]
    if t.startswith("us-gaap_"):
        return t[len("us-gaap_") :]
    if t.startswith("srt:"):
        return "srt:" + t[len("srt:") :]
    if t.startswith("srt_"):
        return "srt:" + t[len("srt_") :]
    # bare CamelCase likely a concept local name
    if re.match(r"^[A-Z][A-Za-z0-9]+$", t):
        return t
    return None


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def harvest_edgar_analytics() -> dict:
    from edgar_analytics.synonyms import SYNONYMS

    extracted = []
    for key, labels in SYNONYMS.items():
        gaap_tags = []
        ifrs_tags = []
        text_labels = []
        for lab in labels:
            if lab.lower().startswith("us-gaap"):
                n = normalize_gaap_tag(lab)
                if n and n not in gaap_tags:
                    gaap_tags.append(n)
            elif lab.lower().startswith("ifrs"):
                ifrs_tags.append(lab)
            else:
                text_labels.append(lab)
        extracted.append(
            {
                "id": f"ea:concept:{key}",
                "synonymKey": key,
                "label": key.replace("_", " ").title(),
                "gaapTags": gaap_tags,
                "ifrsTags": ifrs_tags,
                "textLabels": text_labels[:12],
                "source": "edgar_analytics",
                "kind": "extracted",
            }
        )

    derived = []
    for m in EDGAR_ANALYTICS_DERIVED:
        derived.append(
            {
                "id": f"ea:metric:{slug(m['id'])}",
                "label": m["id"],
                "category": m["category"],
                "expression": m["formula"],
                "inputSynonyms": m["inputs"],
                "source": "edgar_analytics",
                "kind": "derived",
            }
        )

    return {
        "meta": {
            "source": "edgar_analytics",
            "package": "edgar-analytics",
            "purpose": "Ontology expansion — synonym→GAAP maps and derived metric formulas",
            "notes": "Does not fetch or compute EDGAR filings; harvests library catalogs only.",
        },
        "extractedConcepts": extracted,
        "derivedMetrics": derived,
    }


def harvest_edgartools() -> dict:
    import edgar

    path = Path(edgar.__file__).parent / "xbrl" / "standardization" / "concept_mappings.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    standards = []
    for name, tags in raw.items():
        if name.startswith("_") or not isinstance(tags, list):
            continue
        gaap = []
        for t in tags:
            n = normalize_gaap_tag(str(t))
            if n and n not in gaap:
                gaap.append(n)
        standards.append(
            {
                "id": f"et:standard:{slug(name)}",
                "label": name,
                "gaapTags": gaap,
                "source": "edgartools",
                "kind": "standard",
            }
        )
    return {
        "meta": {
            "source": "edgartools",
            "package": "edgartools",
            "mappingFile": str(path),
            "purpose": "Ontology expansion — ~95 standardized statement concepts → XBRL tags",
            "notes": "Catalog harvest only; no SEC filing download.",
        },
        "standardConcepts": standards,
    }


def harvest_finnhub() -> dict:
    metrics = [
        {
            "id": f"fh:metric:{slug(k)}",
            "key": k,
            "label": k,
            "category": cat,
            "expression": expr,
            "source": "finnhub",
            "kind": "metric",
        }
        for k, cat, expr in FINNHUB_METRIC_CATALOG
    ]
    live_keys: list[str] = []
    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if api_key:
        try:
            url = f"https://finnhub.io/api/v1/stock/metric?symbol=AAPL&metric=all&token={api_key}"
            req = urllib.request.Request(url, headers={"User-Agent": "us-gaap-ontology-discovery/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            metric_obj = data.get("metric") or {}
            live_keys = sorted(metric_obj.keys())
            known = {m["key"] for m in metrics}
            for k in live_keys:
                if k not in known:
                    metrics.append(
                        {
                            "id": f"fh:metric:{slug(k)}",
                            "key": k,
                            "label": k,
                            "category": "live",
                            "expression": "",
                            "source": "finnhub",
                            "kind": "metric",
                            "fromLiveSample": True,
                        }
                    )
            print(f"  Finnhub live sample: {len(live_keys)} metric keys")
        except Exception as exc:  # noqa: BLE001
            print(f"  Finnhub live fetch skipped ({exc})")
    else:
        print("  FINNHUB_API_KEY not set — using curated Finnhub metric catalog")

    return {
        "meta": {
            "source": "finnhub",
            "endpoint": "/stock/metric",
            "purpose": "Ontology expansion — normalized company metrics/ratios catalog",
            "notes": (
                "Catalog of Finnhub metric keys for Graph RAG / ontology coverage. "
                "Set FINNHUB_API_KEY to enlarge from a live AAPL sample. No ongoing calc engine."
            ),
            "liveKeysSampled": len(live_keys),
        },
        "metrics": metrics,
    }


def load_ontology_concepts() -> set[str]:
    for path in (ONTOLOGY_JSON, GAAP_CACHE, ROOT / "viewer" / "taxonomy-data.json"):
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get("concepts") or {})
    return set()


def load_existing_nongaap_labels() -> set[str]:
    path = ROOT / "ontology" / "nongaap_metrics.yaml"
    if not path.exists():
        return set()
    text = path.read_text(encoding="utf-8").lower()
    # crude but effective label/id harvest
    labels = set(re.findall(r"label:\s*(.+)", text, flags=re.I))
    ids = set(re.findall(r"id:\s*(nongaap:\S+)", text, flags=re.I))
    return {x.strip().lower() for x in labels} | {x.strip().lower() for x in ids}


def gap_analysis(ea: dict, et: dict, fh: dict, ontology: set[str]) -> dict:
    # All GAAP tags referenced by discovery sources
    referenced: dict[str, list[str]] = defaultdict(list)
    for c in ea["extractedConcepts"]:
        for t in c["gaapTags"]:
            referenced[t].append(c["id"])
    for c in et["standardConcepts"]:
        for t in c["gaapTags"]:
            referenced[t].append(c["id"])

    missing_tags = sorted(t for t in referenced if t not in ontology)
    present_tags = sorted(t for t in referenced if t in ontology)

    # Statement-ish ontology concepts never referenced by discovery maps
    # Focus on concepts that look like monetary statement lines (heuristic: in ontology + have no meta: prefix)
    # Too many atomics — instead report discovery coverage ratio and unused *mapped* preferred tags.
    existing_nongaap = load_existing_nongaap_labels()
    missing_metrics = []
    covered_metrics = []
    for m in ea["derivedMetrics"]:
        lab = m["label"].lower()
        nid = m["id"].lower()
        if any(lab in x or x in lab or nid.split(":")[-1] in x for x in existing_nongaap):
            covered_metrics.append(m["id"])
        else:
            missing_metrics.append(m)

    fh_missing = []
    fh_covered = []
    for m in fh["metrics"]:
        key = m["key"].lower()
        lab = m["label"].lower()
        if any(key in x or lab in x or x in lab for x in existing_nongaap):
            fh_covered.append(m["id"])
        else:
            fh_missing.append(m)

    # Synonym keys whose GAAP tags are all missing from ontology
    orphan_synonyms = []
    for c in ea["extractedConcepts"]:
        if c["gaapTags"] and all(t not in ontology for t in c["gaapTags"]):
            orphan_synonyms.append(c)

    return {
        "meta": {
            "purpose": "Compare discovery catalogs against the unified ontology",
            "ontologyConceptCount": len(ontology),
            "discoveryGaapTagCount": len(referenced),
        },
        "summary": {
            "gaapTagsReferenced": len(referenced),
            "gaapTagsPresentInOntology": len(present_tags),
            "gaapTagsMissingFromOntology": len(missing_tags),
            "eaDerivedAlreadyCovered": len(covered_metrics),
            "eaDerivedMissingFromNongaap": len(missing_metrics),
            "finnhubAlreadyCovered": len(fh_covered),
            "finnhubMissingFromNongaap": len(fh_missing),
            "orphanSynonymsNoGaapMatch": len(orphan_synonyms),
        },
        "missingGaapTags": [
            {"tag": t, "referencedBy": referenced[t][:8]} for t in missing_tags
        ],
        "presentGaapTagsSample": present_tags[:50],
        "missingDerivedMetrics": missing_metrics,
        "missingFinnhubMetrics": [
            {"id": m["id"], "key": m["key"], "category": m["category"], "expression": m["expression"]}
            for m in fh_missing
        ],
        "orphanSynonyms": orphan_synonyms[:40],
        "requiredRelationships": [
            {
                "type": "mapsTo",
                "from": "discovery standard/synonym node",
                "to": "us-gaap local name",
                "why": "Library synonym/standard maps are the bridge from management labels to taxonomy tags",
            },
            {
                "type": "derivedFrom",
                "from": "discovery derived metric",
                "to": "extracted synonym concepts / GAAP tags",
                "why": "Formulas need explicit input edges for Graph RAG and future engines",
            },
            {
                "type": "alignsTo",
                "from": "finnhub metric",
                "to": "nongaap or gaap node",
                "why": "Finnhub ratios should hang off the same ontology forest for exploration",
            },
            {
                "type": "alternativeOf",
                "from": "approx vs standard variants",
                "to": "canonical metric",
                "why": "edgar_analytics EBIT/EBITDA approx vs standard need sibling links",
            },
        ],
    }


def build_discovery_catalog(ea: dict, et: dict, fh: dict, gaps: dict) -> dict:
    """Flatten into one catalog consumed by build_ontology.py."""
    nodes = []

    for c in ea["extractedConcepts"]:
        nodes.append(
            {
                "id": c["id"],
                "label": c["label"],
                "layer": "discovery",
                "source": "edgar_analytics",
                "kind": "extracted",
                "category": "extracted-concept",
                "mapsTo": c["gaapTags"],
                "expression": "",
                "definition": f"edgar_analytics synonym key `{c['synonymKey']}`",
            }
        )
    for m in ea["derivedMetrics"]:
        # resolve synonym inputs → GAAP tags
        syn_map = {c["synonymKey"]: c["gaapTags"] for c in ea["extractedConcepts"]}
        gaap_inputs = []
        for s in m["inputSynonyms"]:
            for t in syn_map.get(s, []):
                if t not in gaap_inputs:
                    gaap_inputs.append(t)
        nodes.append(
            {
                "id": m["id"],
                "label": m["label"],
                "layer": "discovery",
                "source": "edgar_analytics",
                "kind": "derived",
                "category": m["category"],
                "mapsTo": gaap_inputs,
                "inputSynonyms": m["inputSynonyms"],
                "expression": m["expression"],
                "definition": f"edgar_analytics derived metric: {m['expression']}",
                "gap": m["id"] in {x["id"] for x in gaps.get("missingDerivedMetrics", [])},
            }
        )

    for c in et["standardConcepts"]:
        nodes.append(
            {
                "id": c["id"],
                "label": c["label"],
                "layer": "discovery",
                "source": "edgartools",
                "kind": "standard",
                "category": "statement-standard",
                "mapsTo": c["gaapTags"],
                "expression": "",
                "definition": "edgartools standardization concept",
            }
        )

    for m in fh["metrics"]:
        nodes.append(
            {
                "id": m["id"],
                "label": m["label"],
                "layer": "discovery",
                "source": "finnhub",
                "kind": "metric",
                "category": m["category"],
                "mapsTo": [],
                "expression": m.get("expression") or "",
                "definition": f"Finnhub /stock/metric key `{m['key']}`",
                "gap": m["id"]
                in {x["id"] for x in gaps.get("missingFinnhubMetrics", [])},
            }
        )

    # Explicit gap stub nodes for missing GAAP tags (so explorer can surface them)
    for item in gaps.get("missingGaapTags", [])[:200]:
        tag = item["tag"]
        nodes.append(
            {
                "id": f"gap:missing-gaap:{tag}",
                "label": f"Missing GAAP tag: {tag}",
                "layer": "discovery",
                "source": "gap-analysis",
                "kind": "gap",
                "category": "missing-gaap",
                "mapsTo": [tag],
                "expression": "",
                "definition": (
                    "Referenced by discovery libraries but not present in the local ontology "
                    f"concept set. Referenced by: {', '.join(item['referencedBy'][:5])}"
                ),
                "gap": True,
            }
        )

    return {
        "meta": {
            "purpose": "Unified discovery catalog for ontology expansion",
            "sources": ["edgar_analytics", "edgartools", "finnhub", "gap-analysis"],
        },
        "summary": {
            "totalNodes": len(nodes),
            "bySource": {
                src: sum(1 for n in nodes if n["source"] == src)
                for src in ["edgar_analytics", "edgartools", "finnhub", "gap-analysis"]
            },
            "gapFlags": sum(1 for n in nodes if n.get("gap")),
        },
        "nodes": nodes,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Harvesting edgar_analytics…")
    ea = harvest_edgar_analytics()
    write_json(OUT / "edgar_analytics.json", ea)

    print("Harvesting edgartools…")
    et = harvest_edgartools()
    write_json(OUT / "edgartools.json", et)

    print("Harvesting Finnhub catalog…")
    fh = harvest_finnhub()
    write_json(OUT / "finnhub.json", fh)

    print("Running gap analysis…")
    ontology = load_ontology_concepts()
    gaps = gap_analysis(ea, et, fh, ontology)
    write_json(OUT / "gaps.json", gaps)

    catalog = build_discovery_catalog(ea, et, fh, gaps)
    write_json(ROOT / "ontology" / "discovery_catalog.json", catalog)

    print("Summary:", json.dumps({**gaps["summary"], **catalog["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
