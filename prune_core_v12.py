#!/usr/bin/env python3
"""v1.2 — maximally extensible generalized financial ontology core.

Design principles:
- Collapse redundant rollups into a short canonical chain
- Prefer a few abstract extension points over many peers
- Keep equations available via calc (`cc`) / Formulas mode
- Park everything domain-specific under Reference & Extensions

Browse forest (shallow):
  Balance Sheet → Assets | Liabilities | Equity
  Income Statement → Revenue → Gross Profit → Operating Income → Pretax → Net Income → EPS
  Cash Flow → Operating | Investing | Financing | Net Change
  Metrics → Profitability | Liquidity | Leverage | Cash Generation | Returns
  Guidance → core Non-GAAP principles
  Reference & Extensions → grow/prune surface for projects
"""

from __future__ import annotations

from collections import defaultdict

from prune_ontology import (
    NET_BS,
    NET_CF,
    NET_IS,
    _canon_label,
    pruned_calc_children,
)
from prune_core_v11 import (
    INDUSTRY_RE,
    SPECIALIZED_RE,
    apply_core_generalizable,
    ensure_core_node,
    is_industry_or_specialized,
    link,
    pick,
)

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
        "d": "Extensible financial position model — Assets, Liabilities, Equity.",
    },
    "root:IncomeStatement": {
        "l": "Income Statement",
        "d": "Collapsed earnings chain — Revenue → Gross Profit → Operating Income → Net Income → EPS.",
    },
    "root:CashFlowStatement": {
        "l": "Cash Flow Statement",
        "d": "Collapsed cash flow model — Operating, Investing, Financing, Net Change.",
    },
    "root:Metrics": {
        "l": "Core Metrics",
        "d": "Minimal cross-industry metric set with formulas; extend per project.",
    },
    "root:Guidance": {
        "l": "Regulatory Guidance",
        "d": "Core SEC Non-GAAP principles for reconciliation and presentation.",
    },
    "root:Reference": {
        "l": "Reference & Extensions",
        "d": "Extension surface — industry/specialized concepts, libraries, gaps.",
    },
}

# Canonical metric canons kept in v1.2 (more collapsed than v1.1).
V12_METRIC_CANONS = {
    "gross margin",
    "operating margin",
    "net margin",
    "ebitda",
    "current ratio",
    "quick ratio",
    "working capital",
    "debt to equity",
    "net debt",
    "free cash flow",
    "roe",
    "roa",
    "roic",
}

V12_METRIC_CATEGORIES = [
    ("profitability", "Profitability", {"gross margin", "operating margin", "net margin", "ebitda", "ebit"}),
    ("liquidity", "Liquidity", {"current ratio", "quick ratio", "cash ratio", "working capital"}),
    ("leverage", "Leverage", {"debt to equity", "net debt", "interest coverage"}),
    ("cashflow", "Cash Generation", {"free cash flow", "cash burn"}),
    ("returns", "Returns", {"roe", "roa", "roic", "asset turnover"}),
]


def _make_root(name: str, children: list[dict]) -> dict:
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
        "coreTier": "core",
        "extensible": True,
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


def _mark(concepts: dict, name: str, **flags) -> None:
    if name not in concepts:
        return
    concepts[name].update(flags)
    concepts[name]["coreTier"] = flags.get("coreTier", "core")


def _extension_hook(
    concepts: dict,
    hook_id: str,
    label: str,
    parent_gaap: str | None,
    hint: str,
) -> str:
    """Empty extensible placeholder children list — projects attach here."""
    kids = []
    if parent_gaap and parent_gaap in concepts:
        kids.append(link(parent_gaap, 5, "PrimaryGAAP"))
        _mark(concepts, parent_gaap, coreTier="core", extensible=True)
    ensure_core_node(
        concepts,
        hook_id,
        label,
        hint,
        kids,
        layer="core",
    )
    concepts[hook_id]["extensible"] = True
    concepts[hook_id]["extensionPoint"] = True
    return hook_id


def build_v12_balance_sheet(concepts: dict) -> list[dict]:
    """Three pillars with collapsed universal children + extension hooks."""

    def group(gid: str, label: str, primary: str | None, members: list[tuple[str, list[str]]], hook_hint: str) -> str:
        kids = []
        if primary and primary in concepts:
            kids.append(link(primary, 5, NET_BS))
            _mark(concepts, primary, coreTier="core")
            # Clear noisy presentation under primary; keep calc in Formulas mode
            concepts[primary]["tc"] = []
        order = 10
        for mlabel, cands in members:
            name = pick(concepts, cands)
            if not name:
                continue
            _mark(concepts, name, coreTier="core")
            concepts[name]["tc"] = []
            kids.append(link(name, order, NET_BS))
            order += 10
        # Extension hook for project growth
        hook = f"{gid}.extensions"
        ensure_core_node(
            concepts,
            hook,
            f"{label} — Extensions",
            hook_hint,
            [],
            layer="core",
        )
        concepts[hook]["extensible"] = True
        concepts[hook]["extensionPoint"] = True
        kids.append(link(hook, 900, "ExtensionPoint"))
        ensure_core_node(concepts, gid, label, f"Core {label} group.", kids, layer="core")
        concepts[gid]["extensible"] = True
        return gid

    assets = group(
        "core:v12:assets",
        "Assets",
        pick(concepts, ["Assets", "AssetsAbstract"]),
        [
            ("Current Assets", ["AssetsCurrent", "AssetsCurrentAbstract"]),
            ("Cash & Equivalents", ["CashAndCashEquivalentsAtCarryingValue", "Cash"]),
            ("Receivables", ["ReceivablesNetCurrent", "AccountsReceivableNetCurrent", "ReceivablesNetCurrentAbstract"]),
            ("Inventory", ["InventoryNet", "InventoryNetAbstract"]),
            ("Noncurrent Assets", ["AssetsNoncurrent", "AssetsNoncurrentAbstract"]),
            ("PP&E", ["PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipmentNetAbstract"]),
            ("Intangibles & Goodwill", ["IntangibleAssetsNetIncludingGoodwill", "Goodwill"]),
        ],
        "Attach industry/project asset lines here (e.g., loan book, policy assets, mineral rights).",
    )
    liabilities = group(
        "core:v12:liabilities",
        "Liabilities",
        pick(concepts, ["Liabilities", "LiabilitiesAbstract"]),
        [
            ("Current Liabilities", ["LiabilitiesCurrent", "LiabilitiesCurrentAbstract"]),
            ("Payables & Accruals", ["AccountsPayableAndAccruedLiabilitiesCurrent", "AccountsPayableCurrent"]),
            ("Deferred Revenue", ["ContractWithCustomerLiability", "DeferredRevenue", "ContractWithCustomerLiabilityCurrent"]),
            ("Short-term Debt", ["ShortTermBorrowings", "LongTermDebtCurrent", "DebtCurrent"]),
            ("Noncurrent Liabilities", ["LiabilitiesNoncurrent", "LiabilitiesNoncurrentAbstract"]),
            ("Long-term Debt", ["LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]),
            ("Lease Liabilities", ["OperatingLeaseLiability", "FinanceLeaseLiability"]),
        ],
        "Attach industry/project liability lines here (e.g., deposits, reserves, member redeemables).",
    )
    equity = group(
        "core:v12:equity",
        "Equity",
        pick(concepts, ["StockholdersEquity", "StockholdersEquityAbstract"]),
        [
            ("Equity Attributable to Parent", ["StockholdersEquity"]),
            ("Retained Earnings", ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"]),
            ("AOCI", ["AccumulatedOtherComprehensiveIncomeLossNetOfTax"]),
            ("Noncontrolling Interest", ["MinorityInterest"]),
        ],
        "Attach equity variants here (partners' capital, mezzanine equity, units).",
    )
    return [
        link(assets, 10, NET_BS),
        link(liabilities, 20, NET_BS),
        link(equity, 30, NET_BS),
    ]


def build_v12_income_statement(concepts: dict) -> list[dict]:
    """Collapsed P&L chain. Intermediate noise folded into extension hooks."""
    chain = [
        ("Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
        ("Cost of Revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
        ("Gross Profit", ["GrossProfit"]),
        ("Operating Income", ["OperatingIncomeLoss"]),
        ("Income Before Tax", [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ]),
        ("Net Income", ["ProfitLoss", "NetIncomeLoss"]),
        ("EPS (Diluted)", ["EarningsPerShareDiluted", "EarningsPerShareBasic"]),
    ]

    # Supporting detail collapsed under Operating Income extension, not peers of Gross Profit
    support = [
        ("Operating Expenses", ["OperatingExpenses"]),
        ("R&D", ["ResearchAndDevelopmentExpense"]),
        ("SG&A", ["SellingGeneralAndAdministrativeExpense"]),
        ("Interest Expense", ["InterestAndDebtExpense", "InterestExpense"]),
        ("Income Tax", ["IncomeTaxExpenseBenefit"]),
        ("EPS (Basic)", ["EarningsPerShareBasic"]),
    ]

    links = []
    for i, (label, cands) in enumerate(chain):
        name = pick(concepts, cands)
        if not name:
            continue
        _mark(concepts, name, coreTier="core", extensible=True)
        # Keep chain shallow: Gross Profit / Operating Income keep calc children that are in-chain only
        if name in {"GrossProfit", "OperatingIncomeLoss", "ProfitLoss", "NetIncomeLoss"}:
            cc = pruned_calc_children(concepts, name, NET_IS)
            keep = []
            allow = {
                "Revenues",
                "CostOfRevenue",
                "GrossProfit",
                "OperatingExpenses",
                "OperatingIncomeLoss",
                "NonoperatingIncomeExpense",
                "InterestAndDebtExpense",
                "IncomeTaxExpenseBenefit",
                "ProfitLoss",
                "NetIncomeLoss",
                "IncomeLossFromContinuingOperationsIncludingPortionAttributableToNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            }
            for j, item in enumerate(cc):
                if item["c"] in allow and not is_industry_or_specialized(item["c"], concepts.get(item["c"])):
                    keep.append(
                        {"c": item["c"], "o": (j + 1) * 10, "net": item.get("net") or NET_IS, "w": item.get("w", 1)}
                    )
            concepts[name]["tc"] = keep[:6]
        else:
            concepts[name]["tc"] = []
        links.append(link(name, (i + 1) * 10, NET_IS))

    # Single collapsed "P&L Components" bucket for support lines
    detail_kids = []
    for j, (label, cands) in enumerate(support):
        name = pick(concepts, cands)
        if not name:
            continue
        _mark(concepts, name, coreTier="core")
        concepts[name]["tc"] = []
        detail_kids.append(link(name, (j + 1) * 10, NET_IS))
    ensure_core_node(
        concepts,
        "core:v12:pl_components",
        "P&L Components",
        "Collapsed operating/expense/tax components. Extend with project-specific opex lines.",
        detail_kids,
        layer="core",
    )
    concepts["core:v12:pl_components"]["extensible"] = True
    links.append(link("core:v12:pl_components", 80, "Collapsed"))

    ensure_core_node(
        concepts,
        "core:v12:is_extensions",
        "Income Statement — Extensions",
        "Attach industry revenue/expense models here (premiums, interest income, brokerage, etc.).",
        [],
        layer="core",
    )
    concepts["core:v12:is_extensions"]["extensionPoint"] = True
    concepts["core:v12:is_extensions"]["extensible"] = True
    links.append(link("core:v12:is_extensions", 90, "ExtensionPoint"))
    return links


def build_v12_cash_flow(concepts: dict) -> list[dict]:
    sections = [
        ("Operating", ["NetCashProvidedByUsedInOperatingActivities"]),
        ("Investing", ["NetCashProvidedByUsedInInvestingActivities"]),
        ("Financing", ["NetCashProvidedByUsedInFinancingActivities"]),
        ("Net Change in Cash", [
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
            "CashAndCashEquivalentsPeriodIncreaseDecrease",
        ]),
    ]
    links = []
    for i, (label, cands) in enumerate(sections):
        name = pick(concepts, cands)
        if not name:
            continue
        _mark(concepts, name, coreTier="core", extensible=True)
        # CapEx as notable investing detail only
        if "Investing" in label:
            capex = pick(concepts, ["PaymentsToAcquirePropertyPlantAndEquipment"])
            if capex:
                _mark(concepts, capex, coreTier="core")
                concepts[capex]["tc"] = []
                concepts[name]["tc"] = [link(capex, 10, NET_CF)]
            else:
                concepts[name]["tc"] = []
        elif "Operating" in label:
            # Keep NI + adjustments if present (universal indirect bridge)
            keep_names = {
                "ProfitLoss",
                "NetIncomeLoss",
                "AdjustmentsToReconcileNetIncomeLossToCashProvidedByUsedInOperatingActivities",
            }
            cc = pruned_calc_children(concepts, name, NET_CF) or pruned_calc_children(concepts, name, None)
            concepts[name]["tc"] = [
                {"c": x["c"], "o": (j + 1) * 10, "net": x.get("net") or NET_CF, "w": x.get("w", 1)}
                for j, x in enumerate(cc)
                if x["c"] in keep_names
            ]
        else:
            concepts[name]["tc"] = []
        links.append(link(name, (i + 1) * 10, NET_CF))

    ensure_core_node(
        concepts,
        "core:v12:cf_extensions",
        "Cash Flow — Extensions",
        "Attach project-specific investing/financing lines (acquisitions, deposits, member redemptions).",
        [],
        layer="core",
    )
    concepts["core:v12:cf_extensions"]["extensionPoint"] = True
    links.append(link("core:v12:cf_extensions", 90, "ExtensionPoint"))
    return links


def build_v12_metrics(concepts: dict) -> list[dict]:
    candidates = []
    for c in concepts.values():
        if c.get("layer") not in {"nongaap", "discovery"}:
            continue
        if str(c.get("n", "")).startswith("fh:"):
            continue
        if not (c.get("expression") or c.get("df") or c.get("mapsTo") or c.get("k") == "derived"):
            continue
        candidates.append(c)

    def rank(c: dict) -> tuple:
        return (0 if c.get("layer") == "nongaap" else 1, 0 if "approx" not in (c.get("l") or "").lower() else 1, c.get("n"))

    by_canon: dict[str, dict] = {}
    for c in sorted(candidates, key=rank):
        key = _canon_label(c.get("l") or c.get("n") or "")
        # Map ebit into profitability but prefer ebitda as the kept operating proxy in core
        if key == "ebit":
            c["coreTier"] = "extension"
            continue
        if key not in V12_METRIC_CANONS:
            c["coreTier"] = "extension"
            continue
        if key not in by_canon:
            by_canon[key] = c
            c["coreTier"] = "core"
        else:
            by_canon[key].setdefault("alts", []).append(c["n"])
            c["dedupedInto"] = by_canon[key]["n"]
            c["coreTier"] = "duplicate"

    groups: dict[str, list[str]] = defaultdict(list)
    for cat_key, _label, canons in V12_METRIC_CATEGORIES:
        for key, c in by_canon.items():
            if key in canons:
                inputs = [i for i in (c.get("df") or c.get("mapsTo") or []) if i in concepts]
                c["tc"] = [link(i, (j + 1) * 10, "DerivedFrom") for j, i in enumerate(inputs[:6])]
                groups[cat_key].append(c["n"])

    links = []
    for i, (cat_key, cat_label, _canons) in enumerate(V12_METRIC_CATEGORIES):
        ids = list(dict.fromkeys(groups.get(cat_key) or []))
        if not ids:
            continue
        cid = f"core:v12:metrics:{cat_key}"
        ensure_core_node(
            concepts,
            cid,
            cat_label,
            f"Core {cat_label} metrics.",
            [link(mid, (j + 1) * 10, "Metrics") for j, mid in enumerate(ids)],
            layer="nongaap",
        )
        concepts[cid]["extensible"] = True
        links.append(link(cid, (i + 1) * 10, "Metrics"))

    ensure_core_node(
        concepts,
        "core:v12:metrics_extensions",
        "Metrics — Extensions",
        "Attach domain KPIs here (SaaS ARR/NDR, bank NIM, insurer combined ratio, scoring models).",
        [],
        layer="core",
    )
    concepts["core:v12:metrics_extensions"]["extensionPoint"] = True
    links.append(link("core:v12:metrics_extensions", 90, "ExtensionPoint"))
    return links


def build_v12_guidance(concepts: dict) -> list[dict]:
    prefer = ["cdi:100.01", "cdi:102.05", "cdi:102.07", "cdi:102.10"]
    links = []
    for i, rid in enumerate(prefer):
        if rid not in concepts:
            continue
        r = concepts[rid]
        r["coreTier"] = "core"
        gov = [g for g in (r.get("governs") or []) if g in concepts][:8]
        r["tc"] = [link(g, (j + 1) * 10, "Governs") for j, g in enumerate(gov)]
        links.append(link(rid, (i + 1) * 10, "Guidance"))
    ensure_core_node(
        concepts,
        "core:v12:guidance_extensions",
        "Guidance — Full C&DI Set",
        "Additional SEC Non-GAAP C&DIs for specialized presentation questions.",
        [],
        layer="rule",
    )
    # Point hook at full set if present
    if "reference:AllNonGAAP_CDIs" in concepts:
        concepts["core:v12:guidance_extensions"]["tc"] = [
            link("reference:AllNonGAAP_CDIs", 10, "Guidance")
        ]
        concepts["core:v12:guidance_extensions"]["pc"] = concepts["core:v12:guidance_extensions"]["tc"]
        concepts["core:v12:guidance_extensions"]["sc"] = ["reference:AllNonGAAP_CDIs"]
    concepts["core:v12:guidance_extensions"]["extensionPoint"] = True
    links.append(link("core:v12:guidance_extensions", 90, "ExtensionPoint"))
    return links


def apply_core_v12(concepts: dict) -> dict:
    """Build v1.2 collapsed extensible forest on top of v1.1 machinery."""
    base = apply_core_generalizable(concepts)

    concepts["root:BalanceSheet"] = _make_root("root:BalanceSheet", build_v12_balance_sheet(concepts))
    concepts["root:IncomeStatement"] = _make_root("root:IncomeStatement", build_v12_income_statement(concepts))
    concepts["root:CashFlowStatement"] = _make_root("root:CashFlowStatement", build_v12_cash_flow(concepts))
    concepts["root:Metrics"] = _make_root("root:Metrics", build_v12_metrics(concepts))
    concepts["root:Guidance"] = _make_root("root:Guidance", build_v12_guidance(concepts))

    # Reference: keep v1.1 reference children, ensure extension folder first
    ref = concepts.get("root:Reference") or {}
    ref_kids = list(ref.get("tc") or ref.get("pc") or [])
    # Prepend a clear "How to extend" node
    ensure_core_node(
        concepts,
        "core:v12:how_to_extend",
        "How to Extend This Model",
        (
            "Project workflow: (1) keep the six core roots, (2) attach domain lines under each "
            "'— Extensions' hook, (3) promote only needed specialized GAAP from Industry & Specialized, "
            "(4) add domain metrics under Metrics — Extensions. Do not fork the core chain."
        ),
        [
            link("core:v12:assets.extensions", 10),
            link("core:v12:liabilities.extensions", 20),
            link("core:v12:equity.extensions", 30),
            link("core:v12:is_extensions", 40),
            link("core:v12:cf_extensions", 50),
            link("core:v12:metrics_extensions", 60),
        ],
        layer="core",
    )
    # Fix asset/liab/equity extension ids to match group() naming
    for old, new in [
        ("core:v12:assets.extensions", "core:v12:assets.extensions"),
    ]:
        pass
    # group() created core:v12:assets.extensions via f"{gid}.extensions"
    # gid is core:v12:assets so hook is core:v12:assets.extensions — good

    concepts["core:v12:how_to_extend"]["tc"] = [
        link(hid, (i + 1) * 10)
        for i, hid in enumerate(
            [
                "core:v12:assets.extensions",
                "core:v12:liabilities.extensions",
                "core:v12:equity.extensions",
                "core:v12:is_extensions",
                "core:v12:cf_extensions",
                "core:v12:metrics_extensions",
            ]
        )
        if hid in concepts
    ]
    concepts["core:v12:how_to_extend"]["pc"] = concepts["core:v12:how_to_extend"]["tc"]
    concepts["core:v12:how_to_extend"]["sc"] = [x["c"] for x in concepts["core:v12:how_to_extend"]["tc"]]

    new_ref = [link("core:v12:how_to_extend", 5, "Reference")] + ref_kids
    concepts["root:Reference"] = _make_root("root:Reference", new_ref)

    core_n = sum(1 for c in concepts.values() if c.get("coreTier") == "core")
    ext_n = sum(1 for c in concepts.values() if c.get("coreTier") == "extension")
    hooks = sum(1 for c in concepts.values() if c.get("extensionPoint"))

    return {
        **base,
        "coreGeneralizable": True,
        "coreCollapsed": True,
        "versionTag": "1.2",
        "coreTierCore": core_n,
        "coreTierExtension": ext_n,
        "extensionPoints": hooks,
    }
