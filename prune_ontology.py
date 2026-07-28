#!/usr/bin/env python3
"""Prune and restructure the unified ontology into an analyst-aligned browse forest.

Keeps raw presentation/calculation arcs (`pc`/`cc`/`sc`) intact for detail views.
Writes curated tree children as `tc` and replaces `ontologyRoots` with a
financial-professional backbone:

  Balance Sheet → Income Statement → Cash Flow → Metrics & Ratios → Guidance → Reference
"""

from __future__ import annotations

import re
from collections import defaultdict

# Preferred statement networks for pruned presentation browsing.
NET_BS = "StatementOfFinancialPositionClassified"
NET_IS = "StatementOfIncome"
NET_CF = "StatementOfCashFlowsIndirect"
NET_EQ = "StatementOfShareholdersEquityAndOtherComprehensiveIncome"

FOREST_ORDER = [
    "root:BalanceSheet",
    "root:IncomeStatement",
    "root:CashFlowStatement",
    "root:Metrics",
    "root:Guidance",
    "root:Reference",
]

ROOT_META = {
    "root:BalanceSheet": {
        "l": "Balance Sheet",
        "d": "Statement of financial position — Assets, Liabilities, and Equity (classified).",
    },
    "root:IncomeStatement": {
        "l": "Income Statement",
        "d": "Top-down earnings rollup (Revenue → Gross Profit → Operating Income → Net Income) via calculation relationships.",
    },
    "root:CashFlowStatement": {
        "l": "Cash Flow Statement",
        "d": "Operating, Investing, and Financing cash flows (indirect method calculation tree).",
    },
    "root:Metrics": {
        "l": "Metrics & Ratios",
        "d": "Deduplicated Non-GAAP / management metrics and analytical ratios with formulas and GAAP inputs.",
    },
    "root:Guidance": {
        "l": "Regulatory Guidance",
        "d": "SEC Non-GAAP Compliance & Disclosure Interpretations (C&DIs).",
    },
    "root:Reference": {
        "l": "Reference Sources",
        "d": "FIBO alignments, library concept maps (edgartools / edgar_analytics / Finnhub), and coverage gaps.",
    },
}

# Classic IS order for analysts (calc-backed concepts).
INCOME_STATEMENT_ORDER = [
    "Revenues",
    "CostOfRevenue",
    "GrossProfit",
    "OperatingExpenses",
    "OperatingIncomeLoss",
    "NonoperatingIncomeExpense",
    "InterestAndDebtExpense",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    "IncomeLossFromEquityMethodInvestments",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "IncomeTaxExpenseBenefit",
    "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
    "IncomeLossFromDiscontinuedOperationsNetOfTax",
    "ProfitLoss",
    "NetIncomeLossAttributableToNoncontrollingInterest",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
]

CASH_FLOW_ORDER = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
]

# Metric category display order for financial professionals.
METRIC_CATEGORY_ORDER = [
    ("profitability", "Profitability"),
    ("liquidity", "Liquidity"),
    ("leverage", "Leverage & Solvency"),
    ("cashflow", "Cash Flow Metrics"),
    ("returns", "Returns & Efficiency"),
    ("efficiency", "Returns & Efficiency"),
    ("quality", "Earnings Quality"),
    ("composition", "Balance Sheet Composition"),
    ("working-capital", "Working Capital Cycle"),
    ("valuation", "Valuation"),
    ("scoring", "Scoring Models"),
    ("per-share", "Per-Share"),
    ("saas", "SaaS / Growth KPIs"),
    ("reconciliation", "Reconciliations"),
    ("adjustment", "Adjustments"),
    ("other", "Other"),
]

# Normalize discovery/nongaap labels to detect duplicates.
_CANON_ALIASES = {
    "free cash flow": "free cash flow",
    "free cash flow (fcf)": "free cash flow",
    "fcf": "free cash flow",
    "ebitda": "ebitda",
    "ebitda (standard)": "ebitda",
    "ebitda (approx)": "ebitda approx",
    "ebit (standard)": "ebit",
    "ebit (approx)": "ebit approx",
    "net debt": "net debt",
    "working capital": "working capital",
    "gross margin": "gross margin",
    "gross margin %": "gross margin",
    "operating margin": "operating margin",
    "operating margin %": "operating margin",
    "net margin %": "net margin",
    "net margin": "net margin",
    "cash burn": "cash burn",
    "cash burn (ocf - capex)": "cash burn",
    "current ratio": "current ratio",
    "quick ratio": "quick ratio",
    "cash ratio": "cash ratio",
    "debt-to-equity": "debt to equity",
    "roe %": "roe",
    "roa %": "roa",
    "roic %": "roic",
}


def _canon_label(label: str) -> str:
    s = (label or "").strip().lower()
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    if s in _CANON_ALIASES:
        return _CANON_ALIASES[s]
    s2 = re.sub(r"\s*\(.*?\)\s*", " ", s).strip()
    s2 = s2.replace("%", "").strip()
    return _CANON_ALIASES.get(s2, s2)


def is_scaffolding(name: str, concept: dict | None = None) -> bool:
    """XBRL presentation chrome that analysts don't navigate as line items."""
    n = name or ""
    if n in {"StatementTable", "StatementLineItems"}:
        return True
    if n.endswith("Axis") or n.endswith("Domain") or n.endswith("Member"):
        return True
    if "Axis" in n and n.endswith("Axis"):
        return True
    if n.startswith("dei_") or n.startswith("dei:"):
        return True
    if concept:
        lab = (concept.get("l") or "").lower()
        if lab.endswith("[axis]") or lab.endswith("[domain]") or lab.endswith("[member]"):
            return True
        if lab in {"statement [table]", "statement [line items]"}:
            return True
    return False


def _dedupe_links(links: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for link in links:
        c = link.get("c")
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(link)
    return out


def pruned_presentation_children(
    concepts: dict,
    name: str,
    preferred_net: str | None = None,
) -> list[dict]:
    """Return presentation children suitable for analyst browsing."""
    c = concepts.get(name) or {}
    raw = list(c.get("pc") or [])
    if preferred_net:
        filtered = [x for x in raw if x.get("net") == preferred_net]
        if filtered:
            raw = filtered

    # Prefer preferred nets when mixed and no explicit filter
    if not preferred_net:
        preferred = {
            NET_BS,
            NET_IS,
            NET_CF,
            NET_EQ,
            "DerivedFrom",
            "NonGAAP",
            "NonGAAPCategory",
            "Governs",
            "AlignsTo",
            "MapsTo",
            "ClassSubclass",
        }
        pref_links = [x for x in raw if x.get("net") in preferred]
        if pref_links:
            raw = pref_links

    expanded: list[dict] = []
    for link in raw:
        child = link["c"]
        child_c = concepts.get(child) or {}
        if is_scaffolding(child, child_c):
            # Skip through StatementLineItems / Table into real line items
            if child in {"StatementTable", "StatementLineItems"}:
                nested = pruned_presentation_children(concepts, child, preferred_net or link.get("net"))
                expanded.extend(nested)
            continue
        # Skip redundant total that mirrors its abstract parent (Assets under AssetsAbstract)
        parent_base = name[:-8] if name.endswith("Abstract") else name
        if name.endswith("Abstract") and child == parent_base:
            continue
        expanded.append(
            {"c": child, "o": link.get("o", 0), "net": link.get("net") or preferred_net or ""}
        )

    return _dedupe_links(sorted(expanded, key=lambda x: (x.get("o", 0), x["c"])))


def pruned_calc_children(concepts: dict, name: str, preferred_net: str | None = None) -> list[dict]:
    c = concepts.get(name) or {}
    raw = list(c.get("cc") or [])
    if preferred_net:
        filtered = [x for x in raw if x.get("net") == preferred_net]
        if filtered:
            raw = filtered
    out = []
    for link in raw:
        out.append(
            {
                "c": link["c"],
                "o": link.get("o", 0),
                "net": link.get("net") or "",
                "w": link.get("w", 1.0),
            }
        )
    return _dedupe_links(out)


def make_root(name: str, children: list[dict]) -> dict:
    meta = ROOT_META[name]
    return {
        "n": name,
        "l": meta["l"],
        "d": meta["d"],
        "t": "root",
        "a": True,
        "p": "",
        "b": "",
        "k": "root",
        "layer": "root",
        "f": {
            "atomic": False,
            "combination": True,
            "classParent": False,
            "calcTotal": False,
            "dimensional": False,
            "ratio": False,
            "aggregate": False,
        },
        "pc": children,
        "tc": children,
        "sc": [c["c"] for c in children],
    }


def apply_curated_tree_children(concepts: dict) -> int:
    """Attach `tc` (tree children) on GAAP nodes using pruned presentation."""
    # Infer preferred net from existing pc majority / known roots
    count = 0
    for name, c in list(concepts.items()):
        if c.get("layer") not in {None, "gaap"} and not str(name).startswith(
            ("Assets", "Liabilities", "Stockholders", "Income", "Net", "Operating", "Cash", "Revenue", "Profit", "Gross", "Cost")
        ):
            # Still compute for all nodes that have pc
            pass
        if not c.get("pc") and not c.get("cc"):
            continue

        # Choose preferred net from this node's presentation parents/children
        nets = [x.get("net") for x in (c.get("pc") or []) if x.get("net")]
        preferred = None
        for cand in (NET_BS, NET_IS, NET_CF, NET_EQ):
            if cand in nets:
                preferred = cand
                break
        if not preferred and nets:
            # most common
            preferred = max(set(nets), key=nets.count)

        tc = pruned_presentation_children(concepts, name, preferred)
        # For income/cash key totals, prefer calc children when presentation is empty/noisy
        if name in set(INCOME_STATEMENT_ORDER + CASH_FLOW_ORDER):
            cc = pruned_calc_children(concepts, name, NET_IS if name in INCOME_STATEMENT_ORDER else NET_CF)
            if cc:
                # Use calc as tree children so formulas drill naturally
                tc = [{"c": x["c"], "o": (i + 1) * 10, "net": x.get("net") or "", "w": x.get("w", 1.0)} for i, x in enumerate(cc)]
        if tc:
            c["tc"] = tc
            count += 1
        elif c.get("sc"):
            c["tc"] = [{"c": x, "o": (i + 1) * 10, "net": "ClassSubclass"} for i, x in enumerate(c["sc"])]
            count += 1
    return count


def _metric_category(node: dict) -> str:
    cat = (node.get("category") or "").lower()
    if cat in {"cash flow", "cashflow", "liquidity"} and "cash" in (node.get("l") or "").lower():
        if "burn" in (node.get("l") or "").lower() or "free cash" in (node.get("l") or "").lower():
            return "cashflow"
    mapping = {
        "liquidity": "liquidity",
        "leverage": "leverage",
        "profitability": "profitability",
        "returns": "returns",
        "efficiency": "efficiency",
        "quality": "quality",
        "composition": "composition",
        "working-capital": "working-capital",
        "valuation": "valuation",
        "scoring": "scoring",
        "per-share": "per-share",
        "saas": "saas",
        "reconciliation": "reconciliation",
        "adjustment": "adjustment",
        "cashflow": "cashflow",
    }
    if cat in mapping:
        return mapping[cat]
    lab = (node.get("l") or "").lower()
    if any(k in lab for k in ("margin", "ebit", "revenue", "gross profit")):
        return "profitability"
    if any(k in lab for k in ("current ratio", "quick ratio", "cash ratio", "working capital")):
        return "liquidity"
    if any(k in lab for k in ("debt", "leverage", "interest coverage", "net debt")):
        return "leverage"
    if any(k in lab for k in ("roe", "roa", "roic", "turnover")):
        return "returns"
    if any(k in lab for k in ("piotroski", "altman", "beneish", "score")):
        return "scoring"
    if any(k in lab for k in ("p/e", "p/b", "ev/", "yield", "valuation")):
        return "valuation"
    if "cash" in lab or "fcf" in lab:
        return "cashflow"
    return cat or "other"


def build_metrics_tree(concepts: dict) -> list[dict]:
    """Deduplicate Non-GAAP + discovery derived metrics into analyst categories."""
    # Collect candidates: prefer nongaap, then ea derived, skip finnhub price noise in primary tree
    # (Finnhub stays under Reference)
    candidates: list[dict] = []
    for n, c in concepts.items():
        if c.get("layer") == "nongaap" and c.get("k") == "derived":
            candidates.append(c)
        elif c.get("layer") == "discovery" and c.get("source") == "edgar_analytics" and c.get("k") in {
            "discovery",
            "derived",
            "gap",
        }:
            if c.get("expression") or (c.get("mapsTo") and n.startswith("ea:metric:")):
                candidates.append(c)

    # Dedupe by canonical label; prefer nongaap > ea
    def rank(c: dict) -> tuple:
        layer = c.get("layer")
        return (0 if layer == "nongaap" else 1, c.get("n") or "")

    by_canon: dict[str, dict] = {}
    for c in sorted(candidates, key=rank):
        key = _canon_label(c.get("l") or c.get("n") or "")
        if not key:
            continue
        if key not in by_canon:
            by_canon[key] = c
        else:
            # link alternative
            primary = by_canon[key]
            primary.setdefault("alts", [])
            if c["n"] not in primary["alts"] and c["n"] != primary["n"]:
                primary["alts"].append(c["n"])
            c["dedupedInto"] = primary["n"]

    # Group into categories
    groups: dict[str, list[str]] = defaultdict(list)
    for c in by_canon.values():
        # Tree children for metrics: GAAP inputs / mapsTo / df
        inputs = list(c.get("df") or c.get("mapsTo") or [])
        # Prefer existing concepts only
        inputs = [i for i in inputs if i in concepts]
        c["tc"] = [{"c": i, "o": (j + 1) * 10, "net": "DerivedFrom"} for j, i in enumerate(inputs)]
        cat = _metric_category(c)
        # merge efficiency into returns folder
        if cat == "efficiency":
            cat = "returns"
        groups[cat].append(c["n"])

    # Build category nodes
    cat_links = []
    label_map = {k: lab for k, lab in METRIC_CATEGORY_ORDER}
    # Preserve unique category folders in declared order
    seen_labels: set[str] = set()
    order_i = 0
    for cat_key, cat_label in METRIC_CATEGORY_ORDER:
        ids = groups.get(cat_key) or []
        if cat_key == "efficiency":
            continue
        if cat_label in seen_labels:
            # already emitted (returns+efficiency)
            continue
        if cat_key == "returns":
            ids = list(dict.fromkeys((groups.get("returns") or []) + (groups.get("efficiency") or [])))
        if not ids:
            continue
        seen_labels.add(cat_label)
        order_i += 1
        cid = f"metrics:category:{cat_key}"
        concepts[cid] = {
            "n": cid,
            "l": cat_label,
            "d": f"Analytical metrics — {cat_label}.",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "abstract",
            "layer": "nongaap",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": True,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": mid, "o": (j + 1) * 10, "net": "MetricsCategory"} for j, mid in enumerate(ids)],
            "tc": [{"c": mid, "o": (j + 1) * 10, "net": "MetricsCategory"} for j, mid in enumerate(ids)],
            "sc": ids,
        }
        cat_links.append({"c": cid, "o": order_i * 10, "net": "Metrics"})

    # Catch-all remaining categories
    for cat_key, ids in sorted(groups.items()):
        if cat_key in {"efficiency"}:
            continue
        if any(cat_key == k for k, _ in METRIC_CATEGORY_ORDER):
            continue
        if not ids:
            continue
        order_i += 1
        cid = f"metrics:category:{cat_key}"
        concepts[cid] = {
            "n": cid,
            "l": cat_key.replace("-", " ").replace("_", " ").title(),
            "d": f"Analytical metrics — {cat_key}.",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "abstract",
            "layer": "nongaap",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": True,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": mid, "o": (j + 1) * 10, "net": "MetricsCategory"} for j, mid in enumerate(ids)],
            "tc": [{"c": mid, "o": (j + 1) * 10, "net": "MetricsCategory"} for j, mid in enumerate(ids)],
            "sc": ids,
        }
        cat_links.append({"c": cid, "o": order_i * 10, "net": "Metrics"})

    return cat_links


def build_guidance_tree(concepts: dict) -> list[dict]:
    rules = sorted(
        [c for c in concepts.values() if c.get("k") == "rule" and str(c.get("n", "")).startswith("cdi:")],
        key=lambda c: c.get("questionId") or c.get("n"),
    )
    links = []
    for i, r in enumerate(rules):
        # Tree children = governed metrics that exist
        gov = [g for g in (r.get("governs") or []) if g in concepts]
        r["tc"] = [{"c": g, "o": (j + 1) * 10, "net": "Governs"} for j, g in enumerate(gov)]
        links.append({"c": r["n"], "o": (i + 1) * 10, "net": "Guidance"})
    return links


def build_reference_tree(concepts: dict) -> list[dict]:
    links = []
    # FIBO
    if "root:FIBO" in concepts:
        fibo_kids = concepts["root:FIBO"].get("pc") or concepts["root:FIBO"].get("tc") or []
        concepts["reference:FIBO"] = {
            **{k: v for k, v in concepts["root:FIBO"].items() if k != "n"},
            "n": "reference:FIBO",
            "l": "FIBO Alignments",
            "layer": "fibo",
            "k": "abstract",
            "tc": fibo_kids,
            "pc": fibo_kids,
            "sc": [x["c"] for x in fibo_kids],
        }
        # Keep original root:FIBO but prefer reference folder in new forest
        links.append({"c": "root:FIBO", "o": 10, "net": "Reference"})

    # Library maps (edgartools standards + ea extracted concepts) — not derived metrics
    for src, label, pred in [
        (
            "edgartools",
            "edgartools Standard Concepts",
            lambda c: c.get("source") == "edgartools" and c.get("layer") == "discovery",
        ),
        (
            "edgar_analytics_concepts",
            "edgar_analytics Extracted Concepts",
            lambda c: c.get("source") == "edgar_analytics"
            and c.get("layer") == "discovery"
            and str(c.get("n", "")).startswith("ea:concept:"),
        ),
        (
            "finnhub",
            "Finnhub Metric Keys",
            lambda c: c.get("source") == "finnhub" and c.get("layer") == "discovery",
        ),
        (
            "gaps",
            "Coverage Gaps",
            lambda c: c.get("gap") and c.get("layer") == "discovery",
        ),
    ]:
        ids = sorted(c["n"] for c in concepts.values() if pred(c))
        if not ids:
            continue
        cid = f"reference:{src}"
        concepts[cid] = {
            "n": cid,
            "l": label,
            "d": f"Reference catalog — {label}.",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "abstract",
            "layer": "discovery",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": True,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": i, "o": (j + 1) * 10, "net": "Reference"} for j, i in enumerate(ids)],
            "tc": [{"c": i, "o": (j + 1) * 10, "net": "Reference"} for j, i in enumerate(ids)],
            "sc": ids,
        }
        for i, node_id in enumerate(ids):
            node = concepts[node_id]
            maps = [t for t in (node.get("mapsTo") or []) if t in concepts]
            if maps and not node.get("tc"):
                node["tc"] = [{"c": t, "o": (j + 1) * 10, "net": "MapsTo"} for j, t in enumerate(maps)]
        links.append({"c": cid, "o": 20 + len(links) * 10, "net": "Reference"})

    # Class ontology as reference (type system, not primary statements)
    if "Assets" in concepts or "Liabilities" in concepts:
        class_ids = [x for x in ["Assets", "Liabilities", "InventoryAdjustments"] if x in concepts]
        for cid_name in class_ids:
            node = concepts[cid_name]
            if node.get("sc"):
                node["tc"] = [
                    {"c": x, "o": (j + 1) * 10, "net": "ClassSubclass"} for j, x in enumerate(node["sc"])
                ]
        cid = "reference:ClassOntology"
        concepts[cid] = {
            "n": cid,
            "l": "FASB Class Ontology",
            "d": "Class–subclass type hierarchy (Assets / Liabilities / Inventory Adjustments).",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "abstract",
            "layer": "gaap",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": True,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": x, "o": (i + 1) * 10, "net": "ClassSubclass"} for i, x in enumerate(class_ids)],
            "tc": [{"c": x, "o": (i + 1) * 10, "net": "ClassSubclass"} for i, x in enumerate(class_ids)],
            "sc": class_ids,
        }
        links.append({"c": cid, "o": 100, "net": "Reference"})

    return links


def restructure_forest(concepts: dict) -> dict:
    """Replace synthetic roots with analyst-aligned forest; attach curated `tc` links."""
    stats = {"treeChildrenSet": 0, "metricCategories": 0, "prunedScaffolding": True}

    stats["treeChildrenSet"] = apply_curated_tree_children(concepts)

    # --- Balance Sheet ---
    bs_children = []
    for i, (node, label) in enumerate(
        [
            ("AssetsAbstract", "Assets"),
            ("LiabilitiesAbstract", "Liabilities"),
            ("StockholdersEquityAbstract", "Equity (Parent)"),
        ]
    ):
        if node not in concepts:
            # fallbacks
            alt = {
                "AssetsAbstract": "Assets",
                "LiabilitiesAbstract": "Liabilities",
                "StockholdersEquityAbstract": "StockholdersEquity",
            }.get(node)
            if alt and alt in concepts:
                node = alt
            else:
                continue
        concepts[node]["tc"] = pruned_presentation_children(concepts, node, NET_BS)
        bs_children.append({"c": node, "o": (i + 1) * 10, "net": NET_BS})
    concepts["root:BalanceSheet"] = make_root("root:BalanceSheet", bs_children)

    # --- Income Statement (calc-first top-down) ---
    is_children = []
    for i, node in enumerate(INCOME_STATEMENT_ORDER):
        if node not in concepts:
            continue
        cc = pruned_calc_children(concepts, node, NET_IS)
        if cc:
            concepts[node]["tc"] = [
                {"c": x["c"], "o": (j + 1) * 10, "net": x.get("net") or NET_IS, "w": x.get("w", 1.0)}
                for j, x in enumerate(cc)
            ]
        is_children.append({"c": node, "o": (i + 1) * 10, "net": NET_IS})
    concepts["root:IncomeStatement"] = make_root("root:IncomeStatement", is_children)

    # --- Cash Flow ---
    cf_children = []
    for i, node in enumerate(CASH_FLOW_ORDER):
        if node not in concepts:
            continue
        cc = pruned_calc_children(concepts, node, NET_CF)
        if not cc:
            cc = pruned_calc_children(concepts, node, None)
        if cc:
            concepts[node]["tc"] = [
                {"c": x["c"], "o": (j + 1) * 10, "net": x.get("net") or NET_CF, "w": x.get("w", 1.0)}
                for j, x in enumerate(cc)
            ]
        cf_children.append({"c": node, "o": (i + 1) * 10, "net": NET_CF})
    concepts["root:CashFlowStatement"] = make_root("root:CashFlowStatement", cf_children)

    # --- Metrics ---
    metric_links = build_metrics_tree(concepts)
    concepts["root:Metrics"] = make_root("root:Metrics", metric_links)
    stats["metricCategories"] = len(metric_links)

    # --- Guidance ---
    guidance_links = build_guidance_tree(concepts)
    concepts["root:Guidance"] = make_root("root:Guidance", guidance_links)

    # --- Reference ---
    ref_links = build_reference_tree(concepts)
    concepts["root:Reference"] = make_root("root:Reference", ref_links)

    # Remove old roots from being primary (keep nodes for back-compat search)
    legacy = [
        "root:FinancialPosition",
        "root:ComprehensiveIncome",
        "root:CashFlows",
        "root:Equity",
        "root:ClassOntology",
        "root:NonGAAP",
        "root:Discovery",
    ]
    for name in legacy:
        if name in concepts:
            concepts[name]["legacyRoot"] = True
            concepts[name]["d"] = (
                (concepts[name].get("d") or "")
                + " [Legacy root — superseded by analyst-aligned forest.]"
            )[:500]

    return stats
