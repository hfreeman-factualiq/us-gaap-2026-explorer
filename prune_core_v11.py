#!/usr/bin/env python3
"""v1.1 core generalizable forest — industry-agnostic base tree.

Purpose: a shallow, abstract, deduplicated skeleton that generalizes across
industries/domains. Project-specific trees prune/grow from this base.

All original taxonomy relationships remain on nodes (`pc`/`cc`/`sc`).
Curated browse children are written to `tc` (and `coreTier`).
"""

from __future__ import annotations

import re
from collections import defaultdict

from prune_ontology import (
    FOREST_ORDER as V10_FOREST_ORDER,
    NET_BS,
    NET_CF,
    NET_IS,
    ROOT_META as V10_ROOT_META,
    _canon_label,
    is_scaffolding,
    pruned_calc_children,
    restructure_forest,
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
    **V10_ROOT_META,
    "root:BalanceSheet": {
        "l": "Balance Sheet",
        "d": "Industry-agnostic financial position — Assets, Liabilities, Equity.",
    },
    "root:IncomeStatement": {
        "l": "Income Statement",
        "d": "Universal earnings rollup — Revenue through Net Income / EPS.",
    },
    "root:CashFlowStatement": {
        "l": "Cash Flow Statement",
        "d": "Universal cash flow — Operating, Investing, Financing.",
    },
    "root:Metrics": {
        "l": "Core Metrics & Ratios",
        "d": "Cross-industry management and analytical metrics with formulas.",
    },
    "root:Reference": {
        "l": "Reference & Extensions",
        "d": "Industry/specialized taxonomy, library maps, FIBO, coverage gaps.",
    },
}

# ---------------------------------------------------------------------------
# Core concept allowlists (preferred first). First existing name wins.
# ---------------------------------------------------------------------------

CORE_BS = {
    "assets": {
        "label": "Assets",
        "candidates": ["AssetsAbstract", "Assets"],
        "children": {
            "current": {
                "label": "Current Assets",
                "candidates": ["AssetsCurrentAbstract", "AssetsCurrent"],
                "children": {
                    "cash": {
                        "label": "Cash & Cash Equivalents",
                        "candidates": [
                            "CashCashEquivalentsAndShortTermInvestmentsAbstract",
                            "CashAndCashEquivalentsAtCarryingValue",
                            "CashAndCashEquivalentsAtCarryingValueAbstract",
                            "Cash",
                        ],
                    },
                    "sti": {
                        "label": "Short-term Investments",
                        "candidates": [
                            "ShortTermInvestments",
                            "ShortTermInvestmentsAbstract",
                            "MarketableSecuritiesCurrent",
                        ],
                    },
                    "receivables": {
                        "label": "Receivables",
                        "candidates": [
                            "ReceivablesNetCurrentAbstract",
                            "ReceivablesNetCurrent",
                            "AccountsReceivableNetCurrent",
                        ],
                    },
                    "inventory": {
                        "label": "Inventory",
                        "candidates": ["InventoryNetAbstract", "InventoryNet"],
                    },
                    "prepaids": {
                        "label": "Prepaid & Other Current Assets",
                        "candidates": [
                            "PrepaidExpenseCurrentAbstract",
                            "PrepaidExpenseCurrent",
                            "OtherAssetsCurrent",
                        ],
                    },
                    "contract_assets": {
                        "label": "Contract Assets",
                        "candidates": [
                            "ContractWithCustomerAssetNetCurrentAbstract",
                            "ContractWithCustomerAssetNetCurrent",
                        ],
                    },
                },
            },
            "noncurrent": {
                "label": "Noncurrent Assets",
                "candidates": ["AssetsNoncurrentAbstract", "AssetsNoncurrent"],
                "children": {
                    "ppe": {
                        "label": "Property, Plant & Equipment",
                        "candidates": [
                            "PropertyPlantAndEquipmentNetAbstract",
                            "PropertyPlantAndEquipmentNet",
                        ],
                    },
                    "intangibles": {
                        "label": "Intangible Assets & Goodwill",
                        "candidates": [
                            "IntangibleAssetsNetIncludingGoodwill",
                            "IntangibleAssetsNetExcludingGoodwill",
                            "Goodwill",
                        ],
                    },
                    "lt_investments": {
                        "label": "Long-term Investments",
                        "candidates": [
                            "LongTermInvestmentsAndReceivablesNetAbstract",
                            "LongTermInvestments",
                            "Investments",
                        ],
                    },
                    "rou": {
                        "label": "Right-of-Use Assets",
                        "candidates": [
                            "OperatingLeaseRightOfUseAsset",
                            "FinanceLeaseRightOfUseAsset",
                        ],
                    },
                    "other_nc": {
                        "label": "Other Noncurrent Assets",
                        "candidates": ["OtherAssetsNoncurrent", "OtherAssets"],
                    },
                },
            },
        },
    },
    "liabilities": {
        "label": "Liabilities",
        "candidates": ["LiabilitiesAbstract", "Liabilities"],
        "children": {
            "current": {
                "label": "Current Liabilities",
                "candidates": ["LiabilitiesCurrentAbstract", "LiabilitiesCurrent"],
                "children": {
                    "st_debt": {
                        "label": "Short-term Debt",
                        "candidates": [
                            "ShortTermBorrowings",
                            "DebtCurrent",
                            "LongTermDebtCurrent",
                        ],
                    },
                    "payables": {
                        "label": "Payables & Accruals",
                        "candidates": [
                            "AccountsPayableAndAccruedLiabilitiesCurrent",
                            "AccountsPayableCurrent",
                            "AccruedLiabilitiesCurrent",
                        ],
                    },
                    "deferred_rev": {
                        "label": "Deferred Revenue / Contract Liabilities",
                        "candidates": [
                            "ContractWithCustomerLiabilityCurrent",
                            "DeferredRevenueCurrent",
                            "ContractWithCustomerLiability",
                        ],
                    },
                    "other_cl": {
                        "label": "Other Current Liabilities",
                        "candidates": ["OtherLiabilitiesCurrent"],
                    },
                },
            },
            "noncurrent": {
                "label": "Noncurrent Liabilities",
                "candidates": ["LiabilitiesNoncurrentAbstract", "LiabilitiesNoncurrent"],
                "children": {
                    "lt_debt": {
                        "label": "Long-term Debt",
                        "candidates": [
                            "LongTermDebtNoncurrent",
                            "LongTermDebt",
                            "LongTermDebtAndCapitalLeaseObligations",
                        ],
                    },
                    "leases": {
                        "label": "Lease Liabilities",
                        "candidates": [
                            "OperatingLeaseLiability",
                            "OperatingLeaseLiabilityNoncurrent",
                            "FinanceLeaseLiability",
                        ],
                    },
                    "deferred_tax": {
                        "label": "Deferred Tax Liabilities",
                        "candidates": [
                            "DeferredIncomeTaxLiabilitiesNet",
                            "DeferredTaxLiabilitiesNoncurrent",
                            "DeferredTaxLiabilities",
                        ],
                    },
                    "other_ncl": {
                        "label": "Other Noncurrent Liabilities",
                        "candidates": ["OtherLiabilitiesNoncurrent", "OtherLiabilities"],
                    },
                },
            },
        },
    },
    "equity": {
        "label": "Equity",
        "candidates": [
            "StockholdersEquityAbstract",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterestAbstract",
            "StockholdersEquity",
        ],
        "children": {
            "parent_equity": {
                "label": "Equity Attributable to Parent",
                "candidates": [
                    "StockholdersEquity",
                    "StockholdersEquityAbstract",
                ],
            },
            "common": {
                "label": "Common Stock & APIC",
                "candidates": [
                    "CommonStockValue",
                    "AdditionalPaidInCapital",
                    "CommonStocksIncludingAdditionalPaidInCapital",
                ],
            },
            "retained": {
                "label": "Retained Earnings",
                "candidates": ["RetainedEarningsAccumulatedDeficit", "RetainedEarnings"],
            },
            "treasury": {
                "label": "Treasury Stock",
                "candidates": ["TreasuryStockValue", "TreasuryStockCommonValue"],
            },
            "aoci": {
                "label": "Accumulated Other Comprehensive Income",
                "candidates": [
                    "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
                    "AccumulatedOtherComprehensiveIncomeLossNetOfTaxAbstract",
                ],
            },
            "nci": {
                "label": "Noncontrolling Interest",
                "candidates": [
                    "MinorityInterest",
                    "StockholdersEquityAttributableToNoncontrollingInterest",
                ],
            },
        },
    },
}

CORE_IS = [
    ("Revenue", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]),
    ("Cost of Revenue", ["CostOfRevenue", "CostOfGoodsAndServicesSold"]),
    ("Gross Profit", ["GrossProfit"]),
    ("Operating Expenses", ["OperatingExpenses"]),
    ("Research & Development", ["ResearchAndDevelopmentExpense"]),
    ("Selling, General & Administrative", ["SellingGeneralAndAdministrativeExpense"]),
    ("Operating Income", ["OperatingIncomeLoss"]),
    ("Nonoperating Income (Expense)", ["NonoperatingIncomeExpense"]),
    ("Interest Expense", ["InterestAndDebtExpense", "InterestExpense"]),
    ("Income Before Tax", [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ]),
    ("Income Tax", ["IncomeTaxExpenseBenefit"]),
    ("Net Income", ["ProfitLoss", "NetIncomeLoss"]),
    ("Earnings Per Share — Basic", ["EarningsPerShareBasic"]),
    ("Earnings Per Share — Diluted", ["EarningsPerShareDiluted"]),
]

CORE_CF = [
    ("Cash from Operating Activities", ["NetCashProvidedByUsedInOperatingActivities"]),
    ("Cash from Investing Activities", ["NetCashProvidedByUsedInInvestingActivities"]),
    ("Capital Expenditures", ["PaymentsToAcquirePropertyPlantAndEquipment"]),
    ("Cash from Financing Activities", ["NetCashProvidedByUsedInFinancingActivities"]),
    ("Net Change in Cash", [
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
        "CashAndCashEquivalentsPeriodIncreaseDecrease",
    ]),
]

# Metrics kept in the core (canonical labels after _canon_label).
CORE_METRIC_CANONS = {
    "gross margin",
    "operating margin",
    "net margin",
    "ebit",
    "ebitda",
    "current ratio",
    "quick ratio",
    "cash ratio",
    "working capital",
    "debt to equity",
    "net debt",
    "interest coverage",
    "free cash flow",
    "cash burn",
    "roe",
    "roa",
    "roic",
    "asset turnover",
    "accruals ratio",
    "earnings quality",
    "cash conversion cycle",
    "dso",
    "dio",
    "dpo",
}

CORE_METRIC_CATEGORIES = [
    ("profitability", "Profitability"),
    ("liquidity", "Liquidity"),
    ("leverage", "Leverage & Solvency"),
    ("cashflow", "Cash Flow"),
    ("returns", "Returns & Efficiency"),
    ("quality", "Earnings Quality"),
    ("working-capital", "Working Capital"),
]

INDUSTRY_RE = re.compile(
    r"(OilAndGas|Insurance|Bank|Deposit|Mortgage|REIT|RealEstate|Broker|Dealer|"
    r"Policyholder|Underwriting|FederalHomeLoan|PartnersCapital|LimitedPartner|"
    r"GeneralPartner|LLCMembers|Utilities|Airline|Healthcare|Pharmaceutical|"
    r"Crypto|FilmCost|Mining|Agriculture|Livestock|Timber|Regulated|"
    r"AffordableHousing|Reinsurance|PremiumsEarned|Actuarial|"
    r"MerchantMarine|Demutualization|FloorBrokerage|ServicingFee|"
    r"PolicyAcquisition|VOBA|Catastrophe|Condemnation|FederalFunds|"
    r"TrustAssets|InvestmentIncome|RealizedInvestment)",
    re.I,
)

SPECIALIZED_RE = re.compile(
    r"(ExcludingAccruedInterest|AfterAllowanceForCreditLoss|BeforeAllowanceForCreditLoss|"
    r"SalesTypeLease|DirectFinancingLease|HeldToMaturity|AvailableForSale|"
    r"IncludingDisposalGroup|DiscontinuedOperation|"
    r"ExtensibleEnumeration|TextBlock|TableTextBlock|"
    r"PledgingPurpose|RelatedPartyType|CounterpartyName|"
    r"NonredeemableNoncontrolling|RedeemableNoncontrolling)",
    re.I,
)


def pick(concepts: dict, candidates: list[str]) -> str | None:
    for name in candidates:
        if name in concepts:
            return name
    return None


def ensure_core_node(
    concepts: dict,
    node_id: str,
    label: str,
    definition: str,
    children: list[dict],
    layer: str = "core",
) -> None:
    concepts[node_id] = {
        "n": node_id,
        "l": label,
        "d": definition,
        "t": "coreGroup",
        "a": True,
        "p": "",
        "b": "",
        "k": "abstract",
        "layer": layer,
        "coreTier": "core",
        "f": {
            "atomic": False,
            "combination": True,
            "classParent": True,
            "calcTotal": False,
            "dimensional": False,
            "ratio": False,
            "aggregate": False,
        },
        "pc": children,
        "tc": children,
        "sc": [c["c"] for c in children],
    }


def link(name: str, order: int, net: str = "Core") -> dict:
    return {"c": name, "o": order, "net": net}


def mark_core(concepts: dict, name: str) -> None:
    if name in concepts:
        concepts[name]["coreTier"] = "core"


def is_industry_or_specialized(name: str, concept: dict | None = None) -> bool:
    if INDUSTRY_RE.search(name or ""):
        return True
    if SPECIALIZED_RE.search(name or ""):
        return True
    if concept:
        lab = concept.get("l") or ""
        if INDUSTRY_RE.search(lab) or SPECIALIZED_RE.search(lab.replace(" ", "")):
            return True
        if is_scaffolding(name, concept):
            return True
    return False


def build_slot_tree(concepts: dict, slot: dict, path: str, order_base: int = 10) -> str | None:
    """Materialize a nested CORE_BS slot into core:* group nodes + GAAP picks."""
    node_id = pick(concepts, slot.get("candidates") or [])
    children_spec = slot.get("children") or {}
    child_links: list[dict] = []
    for i, (key, child_slot) in enumerate(children_spec.items()):
        child_id = build_slot_tree(concepts, child_slot, f"{path}.{key}", (i + 1) * 10)
        if child_id:
            child_links.append(link(child_id, (i + 1) * 10))

    label = slot["label"]
    if node_id:
        mark_core(concepts, node_id)
        # Prefer pointing at the real GAAP node when it has no further core children,
        # but if we synthesized children, wrap so both abstract GAAP and core kids show.
        if child_links:
            wrap_id = f"core:{path}"
            # Include the GAAP total/abstract first when useful
            kids = [link(node_id, 5, NET_BS)] + child_links
            # Avoid duplicate if node_id already among children
            seen = set()
            deduped = []
            for lk in kids:
                if lk["c"] in seen:
                    continue
                seen.add(lk["c"])
                deduped.append(lk)
            ensure_core_node(
                concepts,
                wrap_id,
                label,
                f"Core generalizable group: {label}. Primary GAAP concept: {node_id}.",
                deduped,
            )
            # Attach pruned universal children onto the GAAP node itself for drill
            concepts[node_id]["tc"] = child_links
            return wrap_id
        concepts[node_id]["tc"] = []
        return node_id

    if child_links:
        wrap_id = f"core:{path}"
        ensure_core_node(
            concepts,
            wrap_id,
            label,
            f"Core generalizable group: {label}.",
            child_links,
        )
        return wrap_id
    return None


def collect_specialized_under(concepts: dict, roots: list[str], core_ids: set[str]) -> list[str]:
    """Walk raw pc/cc from statement roots; return industry/specialized names not in core."""
    found: list[str] = []
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in concepts:
            continue
        seen.add(n)
        c = concepts[n]
        if n not in core_ids and is_industry_or_specialized(n, c):
            found.append(n)
        for key in ("pc", "cc", "sc"):
            val = c.get(key) or []
            if key == "sc":
                stack.extend(val)
            else:
                stack.extend(x.get("c") for x in val if isinstance(x, dict))
    # stable unique
    out = []
    seen2 = set()
    for n in found:
        if n not in seen2:
            seen2.add(n)
            out.append(n)
    return out


def apply_core_is(concepts: dict) -> list[dict]:
    links = []
    for i, (label, candidates) in enumerate(CORE_IS):
        name = pick(concepts, candidates)
        if not name:
            continue
        mark_core(concepts, name)
        # For rollup nodes, keep only non-specialized calc children (universal)
        cc = pruned_calc_children(
            concepts,
            name,
            NET_IS if name not in {"EarningsPerShareBasic", "EarningsPerShareDiluted"} else None,
        )
        universal = []
        for j, item in enumerate(cc):
            child = item["c"]
            if is_industry_or_specialized(child, concepts.get(child)):
                continue
            universal.append(
                {
                    "c": child,
                    "o": (j + 1) * 10,
                    "net": item.get("net") or NET_IS,
                    "w": item.get("w", 1.0),
                }
            )
        # Keep major IS parents shallow — formulas live in Formulas mode / detail pane.
        # This is what makes the core tree industry-agnostic and project-extendable.
        if name in {
            "Revenues",
            "CostOfRevenue",
            "OperatingExpenses",
            "NonoperatingIncomeExpense",
            "InterestAndDebtExpense",
            "IncomeTaxExpenseBenefit",
        }:
            concepts[name]["tc"] = []
        else:
            concepts[name]["tc"] = universal[:12]
        links.append(link(name, (i + 1) * 10, NET_IS))
    return links


def apply_core_cf(concepts: dict) -> list[dict]:
    links = []
    for i, (label, candidates) in enumerate(CORE_CF):
        name = pick(concepts, candidates)
        if not name:
            continue
        mark_core(concepts, name)
        cc = pruned_calc_children(concepts, name, NET_CF) or pruned_calc_children(concepts, name, None)
        universal = []
        for j, item in enumerate(cc):
            child = item["c"]
            if is_industry_or_specialized(child, concepts.get(child)):
                continue
            universal.append(
                {
                    "c": child,
                    "o": (j + 1) * 10,
                    "net": item.get("net") or NET_CF,
                    "w": item.get("w", 1.0),
                }
            )
        if name == "PaymentsToAcquirePropertyPlantAndEquipment":
            concepts[name]["tc"] = []
        elif name.startswith("NetCashProvidedByUsedIn"):
            # Keep only continuing-operations child if present, else none
            concepts[name]["tc"] = [
                x
                for x in universal[:4]
                if "ContinuingOperations" in x["c"] or x["c"] in {"ProfitLoss", "AdjustmentsToReconcileNetIncomeLossToCashProvidedByUsedInOperatingActivities"}
            ]
        else:
            concepts[name]["tc"] = universal[:8]
        links.append(link(name, (i + 1) * 10, NET_CF))
    return links


def apply_core_metrics(concepts: dict) -> list[dict]:
    # Gather derived candidates
    candidates = []
    for c in concepts.values():
        if c.get("k") in {"derived", "discovery", "gap"} and (
            c.get("layer") in {"nongaap", "discovery"}
        ):
            if c.get("expression") or c.get("df") or c.get("mapsTo"):
                if str(c.get("n", "")).startswith("fh:"):
                    continue  # finnhub stays in reference
                candidates.append(c)

    def rank(c: dict) -> tuple:
        return (0 if c.get("layer") == "nongaap" else 1, c.get("n") or "")

    by_canon: dict[str, dict] = {}
    for c in sorted(candidates, key=rank):
        key = _canon_label(c.get("l") or c.get("n") or "")
        if key not in CORE_METRIC_CANONS:
            # keep non-core for extensions folder later
            c["coreTier"] = "extension"
            continue
        if key not in by_canon:
            by_canon[key] = c
            c["coreTier"] = "core"
        else:
            primary = by_canon[key]
            primary.setdefault("alts", [])
            if c["n"] not in primary["alts"] and c["n"] != primary["n"]:
                primary["alts"].append(c["n"])
            c["dedupedInto"] = primary["n"]
            c["coreTier"] = "duplicate"

    # category buckets
    def metric_cat(c: dict) -> str:
        lab = _canon_label(c.get("l") or "")
        if lab in {"gross margin", "operating margin", "net margin", "ebit", "ebitda"}:
            return "profitability"
        if lab in {"current ratio", "quick ratio", "cash ratio", "working capital"}:
            return "liquidity"
        if lab in {"debt to equity", "net debt", "interest coverage"}:
            return "leverage"
        if lab in {"free cash flow", "cash burn"}:
            return "cashflow"
        if lab in {"roe", "roa", "roic", "asset turnover"}:
            return "returns"
        if lab in {"accruals ratio", "earnings quality"}:
            return "quality"
        if lab in {"cash conversion cycle", "dso", "dio", "dpo"}:
            return "working-capital"
        return "other"

    groups: dict[str, list[str]] = defaultdict(list)
    for c in by_canon.values():
        inputs = [i for i in (c.get("df") or c.get("mapsTo") or []) if i in concepts]
        c["tc"] = [link(i, (j + 1) * 10, "DerivedFrom") for j, i in enumerate(inputs)]
        groups[metric_cat(c)].append(c["n"])

    cat_links = []
    for i, (cat_key, cat_label) in enumerate(CORE_METRIC_CATEGORIES):
        ids = groups.get(cat_key) or []
        if not ids:
            continue
        cid = f"core:metrics:{cat_key}"
        ensure_core_node(
            concepts,
            cid,
            cat_label,
            f"Core cross-industry metrics — {cat_label}.",
            [link(mid, (j + 1) * 10, "MetricsCategory") for j, mid in enumerate(ids)],
            layer="nongaap",
        )
        cat_links.append(link(cid, (i + 1) * 10, "Metrics"))
    return cat_links


def apply_core_guidance(concepts: dict) -> list[dict]:
    """Keep principle-level C&DIs that generalize; park the rest under reference."""
    prefer = {
        "cdi:100.01",
        "cdi:100.04",
        "cdi:102.03",
        "cdi:102.05",
        "cdi:102.07",
        "cdi:102.09",
        "cdi:102.10",
    }
    core_links = []
    other = []
    rules = [
        c
        for c in concepts.values()
        if c.get("k") == "rule" and str(c.get("n", "")).startswith("cdi:")
    ]
    rules.sort(key=lambda c: c.get("questionId") or c.get("n"))
    for r in rules:
        gov = [g for g in (r.get("governs") or []) if g in concepts]
        r["tc"] = [link(g, (j + 1) * 10, "Governs") for j, g in enumerate(gov)]
        if r["n"] in prefer or r.get("governs"):
            r["coreTier"] = "core"
            core_links.append(link(r["n"], (len(core_links) + 1) * 10, "Guidance"))
        else:
            r["coreTier"] = "extension"
            other.append(r["n"])

    if other:
        ensure_core_node(
            concepts,
            "reference:AllNonGAAP_CDIs",
            "All SEC Non-GAAP C&DIs",
            "Full C&DI set including niche staff Q&As.",
            [link(n, (i + 1) * 10, "Guidance") for i, n in enumerate(other)],
            layer="rule",
        )
    return core_links


def build_extensions_folder(concepts: dict, specialized_ids: list[str]) -> str:
    # Cap size for browseability; full set remains searchable in concepts dict
    ids = specialized_ids[:250]
    for n in ids:
        if n in concepts:
            concepts[n]["coreTier"] = concepts[n].get("coreTier") or "extension"
            # Don't recurse huge trees from extensions by default
            if not concepts[n].get("tc"):
                concepts[n]["tc"] = []
    ensure_core_node(
        concepts,
        "reference:IndustryAndSpecialized",
        "Industry & Specialized Line Items",
        (
            "US GAAP concepts that are industry-specific or highly specialized "
            "(banking, insurance, oil & gas, CECL granular variants, lease subtypes, etc.). "
            "Grow project trees from these when the domain requires them."
        ),
        [link(n, (i + 1) * 10, "Extension") for i, n in enumerate(ids)],
        layer="gaap",
    )
    return "reference:IndustryAndSpecialized"


def apply_core_generalizable(concepts: dict) -> dict:
    """Replace browse forest with industry-agnostic core skeleton."""
    # Start from v1.0 analyst structure so merges exist, then overwrite tc/roots.
    v10_stats = restructure_forest(concepts)

    core_ids: set[str] = set()

    # Balance sheet
    bs_links = []
    for i, (key, slot) in enumerate(CORE_BS.items()):
        nid = build_slot_tree(concepts, slot, f"bs.{key}", (i + 1) * 10)
        if nid:
            core_ids.add(nid)
            bs_links.append(link(nid, (i + 1) * 10, NET_BS))
    concepts["root:BalanceSheet"] = _make_root("root:BalanceSheet", bs_links)

    # Income statement
    is_links = apply_core_is(concepts)
    for lk in is_links:
        core_ids.add(lk["c"])
    concepts["root:IncomeStatement"] = _make_root("root:IncomeStatement", is_links)

    # Cash flow
    cf_links = apply_core_cf(concepts)
    for lk in cf_links:
        core_ids.add(lk["c"])
    concepts["root:CashFlowStatement"] = _make_root("root:CashFlowStatement", cf_links)

    # Metrics
    metric_links = apply_core_metrics(concepts)
    for lk in metric_links:
        core_ids.add(lk["c"])
    concepts["root:Metrics"] = _make_root("root:Metrics", metric_links)

    # Guidance
    guidance_links = apply_core_guidance(concepts)
    concepts["root:Guidance"] = _make_root("root:Guidance", guidance_links)

    # Specialized harvest for extensions
    specialized = collect_specialized_under(
        concepts,
        [
            "AssetsAbstract",
            "LiabilitiesAbstract",
            "StockholdersEquityAbstract",
            "Revenues",
            "OperatingExpenses",
            "NetCashProvidedByUsedInOperatingActivities",
        ],
        core_ids,
    )
    ext_id = build_extensions_folder(concepts, specialized)

    # Reference
    ref_links = [link(ext_id, 10, "Reference")]
    if "root:FIBO" in concepts:
        ref_links.append(link("root:FIBO", 20, "Reference"))
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
            and str(c.get("n", "")).startswith("ea:concept:"),
        ),
        (
            "finnhub",
            "Finnhub Metric Keys",
            lambda c: c.get("source") == "finnhub",
        ),
        (
            "gaps",
            "Coverage Gaps",
            lambda c: c.get("gap") and c.get("layer") == "discovery",
        ),
        (
            "metric_extensions",
            "Extended / Domain Metrics",
            lambda c: c.get("coreTier") == "extension"
            and c.get("layer") in {"nongaap", "discovery"}
            and (c.get("expression") or c.get("k") == "derived"),
        ),
    ]:
        ids = sorted(c["n"] for c in concepts.values() if pred(c))
        if not ids:
            continue
        cid = f"reference:{src}"
        ensure_core_node(
            concepts,
            cid,
            label,
            f"Reference catalog — {label}.",
            [link(i, (j + 1) * 10, "Reference") for j, i in enumerate(ids[:300])],
            layer="discovery" if "edgartools" in src or "edgar" in src or "finnhub" in src or src == "gaps" else "nongaap",
        )
        ref_links.append(link(cid, 20 + len(ref_links) * 10, "Reference"))

    if "reference:AllNonGAAP_CDIs" in concepts:
        ref_links.append(link("reference:AllNonGAAP_CDIs", 90, "Reference"))
    if "reference:ClassOntology" in concepts or "Assets" in concepts:
        # ensure class ontology reference exists from v1.0 path
        if "reference:ClassOntology" not in concepts and "Assets" in concepts:
            class_ids = [x for x in ["Assets", "Liabilities", "InventoryAdjustments"] if x in concepts]
            ensure_core_node(
                concepts,
                "reference:ClassOntology",
                "FASB Class Ontology",
                "Class–subclass type hierarchy.",
                [link(x, (i + 1) * 10) for i, x in enumerate(class_ids)],
                layer="gaap",
            )
        if "reference:ClassOntology" in concepts:
            ref_links.append(link("reference:ClassOntology", 100, "Reference"))

    concepts["root:Reference"] = _make_root("root:Reference", ref_links)

    # Count core-tier nodes
    core_count = sum(1 for c in concepts.values() if c.get("coreTier") == "core")
    ext_count = sum(1 for c in concepts.values() if c.get("coreTier") == "extension")

    return {
        **v10_stats,
        "coreGeneralizable": True,
        "coreTierCore": core_count,
        "coreTierExtension": ext_count,
        "industrySpecializedParked": len(specialized),
        "versionTag": "1.1",
    }


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
