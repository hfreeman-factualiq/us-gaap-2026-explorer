#!/usr/bin/env python3
"""Build per-company ontology trees from v1.2, pruned to populateable concepts.

Rule: if A = B + C and the company cannot populate B and C (and does not
report A directly), omit A, B, and C from that company's tree.

Pipeline:
  1. Extract line-item labels from each company's financial statement packs
  2. Map labels → ontology concepts via Claude (LLM)
  3. Gap analysis via Claude: important unmapped lines become new company nodes
     attached under the right parent with relationships/formulas
  4. Close under formulas when ALL inputs exist
  5. Prune the v1.2 browse forest to kept nodes + structural ancestors
  6. Emit company_trees/{slug}/taxonomy-data.json (+ viewer copies)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import yaml
from openpyxl import load_workbook

from llm_mapping import (
    build_candidate_list,
    map_labels_with_llm,
    propose_gaps_with_llm,
)

ROOT = Path(__file__).resolve().parent
_V12 = ROOT / "financial_ontology_2026_v1.2" / "taxonomy-data.json"
ONTOLOGY_PATH = _V12 if _V12.exists() else ROOT / "taxonomy-data.json"
SYNONYM_PATH = ROOT / "mappings" / "label_synonyms.yaml"
STATEMENTS_DIR = ROOT / "Financial Statements"
OUT_DIR = ROOT / "company_trees"
VIEWER_DIR = ROOT / "viewer" / "companies"
PAGES_DIR = ROOT / "companies"

COMPANIES = [
    {
        "slug": "orijin",
        "name": "Orijin",
        "folder": "Orijin",
        "prefer_glob": ["*Consolidated*", "*December*", "*Dec*"],
        "sheet_keywords": {
            "is": ["p&l", "income", "vs.", "ytd", "ordinary"],
            "bs": ["balance"],
            "cf": ["cash flow", "cash flows"],
        },
        "skip_sheets": ["ar aging", "ap aging", "cash forecast", "by month"],
    },
    {
        "slug": "climb-credit",
        "name": "Climb Credit",
        "folder": "Climb Credit",
        "prefer_glob": ["*Consolidated*Dec*", "*Consolidated*"],
        "sheet_keywords": {
            "is": ["profit", "loss", "income", "p&l"],
            "bs": ["balance"],
            "cf": ["cash flow"],
        },
        "skip_sheets": [],
        # Prefer consolidated packs over CCI-only.
        "name_filter": lambda p: "consolidated" in p.name.lower(),
    },
    {
        "slug": "mantra-health",
        "name": "Mantra Health",
        "folder": "Mantra Health",
        "prefer_glob": ["*Dec*", "*YTD*"],
        "sheet_keywords": {
            "is": ["p&l", "income", "profit"],
            "bs": ["bs", "balance"],
            "cf": ["cf", "cash"],
        },
        "skip_sheets": [],
    },
    {
        "slug": "brains-and-motion",
        "name": "Brains and Motion",
        "folder": "Brains and Motion",
        "prefer_glob": ["*Dec*", "*Financial*"],
        "sheet_keywords": {
        "is": ["summary projections", "summary", "category p&l", "consolidated dept p&l"],
        "bs": ["balance sheet"],
        "cf": ["cash flow"],
      },
      "skip_sheets": [
        "documentation",
        "graph",
        "payroll",
        "pipeline",
        "bookings",
        "unit econ",
        "assumptions",
        "mapping",
        "instructor",
        "zero check",
        "msa",
        "bva",
        "location",
        "prepaid schedule",
        "actual revenue",
        "active contracts",
        "university model",
        "db_act",
        "revenue summary",
        "revenue & cor",
        "metrics",
        "actpl",
        "dept p&l - main",
        "dept p&l (by category)",
        "kidz",
        "brains and motion edu",
        "consol pl",
        "actual",
        "budget",
      ],
    },
]

# Statement buckets used to hang unmatched-but-mapped detail under extensions.
ASSET_CONCEPTS = {
    "Assets",
    "AssetsCurrent",
    "AssetsNoncurrent",
    "CashAndCashEquivalentsAtCarryingValue",
    "ReceivablesNetCurrent",
    "InventoryNet",
    "PrepaidExpenseCurrent",
    "PropertyPlantAndEquipmentNet",
    "IntangibleAssetsNetIncludingGoodwill",
    "OperatingLeaseRightOfUseAsset",
    "OtherAssetsNoncurrent",
}
LIAB_CONCEPTS = {
    "Liabilities",
    "LiabilitiesCurrent",
    "LiabilitiesNoncurrent",
    "AccountsPayableAndAccruedLiabilitiesCurrent",
    "ContractWithCustomerLiability",
    "ContractWithCustomerLiabilityCurrent",
    "ShortTermBorrowings",
    "LongTermDebt",
    "OperatingLeaseLiability",
    "OtherLiabilitiesCurrent",
    "OtherLiabilitiesNoncurrent",
    "DeferredIncomeTaxLiabilitiesNet",
}
EQUITY_CONCEPTS = {
    "StockholdersEquity",
    "RetainedEarningsAccumulatedDeficit",
    "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    "MinorityInterest",
    "CommonStockValue",
    "PreferredStockValue",
    "AdditionalPaidInCapital",
    "TreasuryStockValue",
}
IS_CONCEPTS = {
    "Revenues",
    "CostOfRevenue",
    "GrossProfit",
    "OperatingIncomeLoss",
    "OperatingExpenses",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
    "InterestAndDebtExpense",
    "IncomeTaxExpenseBenefit",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "ProfitLoss",
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",
    "NonoperatingIncomeExpense",
    "DepreciationDepletionAndAmortization",
    "nongaap:EBITDA",
}
CF_CONCEPTS = {
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "ProfitLoss",
    "AdjustmentsToReconcileNetIncomeLossToCashProvidedByUsedInOperatingActivities",
}

# Explicit formulas used when browse tc is empty / noisy (ALL inputs required).
EXPLICIT_FORMULAS: dict[str, list[str]] = {
    "GrossProfit": ["Revenues", "CostOfRevenue"],
    "OperatingIncomeLoss": ["GrossProfit", "OperatingExpenses"],
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseExcludingExchangeRateEffect": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    "nongaap:WorkingCapital": ["AssetsCurrent", "LiabilitiesCurrent"],
    "Assets": ["AssetsCurrent", "AssetsNoncurrent"],
    "Liabilities": ["LiabilitiesCurrent", "LiabilitiesNoncurrent"],
}

SKIP_LABEL_RE = re.compile(
    r"^(draft|confidential|amounts in|parameter|zero check|common sized|"
    r"section [a-z]|customer:|current month|reporting book|as of date|"
    r"location:|bookings|choose method|remarks|variance|forecast|budget|"
    r"actual|q[1-4]|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
    r"ytd|fy\s*\d|ye\s*dec|\d{4}$)",
    re.I,
)
GL_CODE_RE = re.compile(r"^\d{3,5}\s*[-–]")
NOISE_RE = re.compile(r"^[\W_]+$")


def canon_label(text: str) -> str:
    s = str(text).lower().strip()
    s = s.replace("&", " and ").replace("/", " ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Drop leading total-/net- noise variants already covered by synonyms
    return s


def is_numbery(val) -> bool:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return True
    if isinstance(val, str):
        t = val.strip().replace(",", "").replace("$", "").replace("(", "-").replace(")", "")
        if not t or t in {"-", "—", "–"}:
            return False
        try:
            float(t)
            return True
        except ValueError:
            return False
    return False


def load_synonyms() -> tuple[dict[str, str], dict[str, list[str]]]:
    raw = yaml.safe_load(SYNONYM_PATH.read_text(encoding="utf-8"))
    syn = {canon_label(k): v for k, v in (raw.get("synonyms") or {}).items()}
    aliases = raw.get("input_aliases") or {}
    return syn, aliases


def list_company_files(cfg: dict) -> list[Path]:
    folder = STATEMENTS_DIR / cfg["folder"]
    files = []
    for pat in ("*.xlsx", "*.xls", "*.xlsb"):
        files.extend(folder.glob(pat))
    files = [f for f in files if not f.name.startswith("~$")]
    name_filter = cfg.get("name_filter")
    if name_filter:
        filtered = [f for f in files if name_filter(f)]
        if filtered:
            files = filtered
    # Prefer latest by YYYY_MM prefix when present
    def sort_key(p: Path):
        m = re.match(r"(\d{4})_(\d{2})", p.name)
        if m:
            return (int(m.group(1)), int(m.group(2)), p.name)
        return (0, 0, p.name)

    files.sort(key=sort_key, reverse=True)
    return files


def pick_source_files(cfg: dict, files: list[Path], limit: int = 2) -> list[Path]:
    if not files:
        return []
    preferred = []
    for f in files:
        low = f.name.lower()
        if any(re.search(g.replace("*", ".*"), low) for g in cfg.get("prefer_glob") or []):
            preferred.append(f)
    chosen = preferred[:limit] if preferred else files[:limit]
    # Always include the chronologically latest file
    if files[0] not in chosen:
        chosen = [files[0]] + chosen
    # de-dupe preserve order
    out, seen = [], set()
    for f in chosen:
        if f not in seen:
            out.append(f)
            seen.add(f)
    return out[:limit]


def classify_sheet(name: str, cfg: dict) -> str | None:
    low = name.lower().strip()
    for skip in cfg.get("skip_sheets") or []:
        if skip.lower() in low:
            return None
    for kind, keys in (cfg.get("sheet_keywords") or {}).items():
        if any(k in low for k in keys):
            return kind
    return None


def iter_sheet_rows_xlsx(path: Path):
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        for sn in wb.sheetnames:
            ws = wb[sn]
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append(list(row[:12]) if row else [])
            yield sn, rows
    finally:
        wb.close()


def iter_sheet_rows_xlsb(path: Path):
    from pyxlsb import open_workbook

    with open_workbook(path) as wb:
        for sn in wb.sheets:
            rows = []
            with wb.get_sheet(sn) as sheet:
                for row in sheet.rows():
                    vals = [(c.v if c else None) for c in row[:12]]
                    rows.append(vals)
            yield sn, rows


def iter_sheet_rows_xls(path: Path):
    import xlrd

    book = xlrd.open_workbook(path)
    for sn in book.sheet_names():
        sh = book.sheet_by_name(sn)
        rows = []
        for r in range(sh.nrows):
            rows.append([sh.cell_value(r, c) for c in range(min(12, sh.ncols))])
        yield sn, rows


def iter_workbook(path: Path):
    suf = path.suffix.lower()
    if suf == ".xlsx":
        yield from iter_sheet_rows_xlsx(path)
    elif suf == ".xlsb":
        yield from iter_sheet_rows_xlsb(path)
    elif suf == ".xls":
        yield from iter_sheet_rows_xls(path)
    else:
        return


def extract_labels_from_rows(rows: list[list]) -> list[str]:
    labels = []
    for row in rows:
        if not row:
            continue
        # Collect candidate text cells from first 3 columns (BAM puts labels in col B)
        texts = []
        for cell in row[:4]:
            if cell is None:
                continue
            if isinstance(cell, str) and cell.strip():
                texts.append(cell.strip())
            elif isinstance(cell, (int, float)) and not isinstance(cell, bool):
                # skip pure numbers as labels
                continue
        if not texts:
            continue
        # Prefer the longest non-noise text-looking cell
        has_numeric = any(is_numbery(c) for c in row[1:8])
        for raw in texts:
            if len(raw) < 2 or len(raw) > 120:
                continue
            if NOISE_RE.match(raw):
                continue
            if SKIP_LABEL_RE.match(raw.strip()):
                continue
            if GL_CODE_RE.match(raw.strip()):
                # Keep totals only: "Total - 1110 ..." etc. already handled; skip GL lines
                if not raw.lower().startswith("total"):
                    continue
            # Keep section headers even without numbers (Current Assets, etc.)
            # but prefer lines that sit near numbers
            labels.append(raw)
            if has_numeric:
                break
    return labels


def extract_company_labels(cfg: dict) -> tuple[list[Path], dict[str, list[str]], list[str]]:
    files = list_company_files(cfg)
    sources = pick_source_files(cfg, files)
    by_stmt: dict[str, list[str]] = {"is": [], "bs": [], "cf": [], "other": []}
    all_labels: list[str] = []
    for path in sources:
        for sn, rows in iter_workbook(path):
            kind = classify_sheet(sn, cfg)
            if kind is None and cfg["slug"] == "brains-and-motion":
                continue
            if kind is None:
                # Still scan unknown sheets lightly for well-known totals
                kind = "other"
            labs = extract_labels_from_rows(rows)
            by_stmt[kind].extend(labs)
            all_labels.extend(labs)
    # unique preserve order
    def uniq(seq):
        out, seen = [], set()
        for x in seq:
            k = canon_label(x)
            if not k or k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    by_stmt = {k: uniq(v) for k, v in by_stmt.items()}
    return sources, by_stmt, uniq(all_labels)


def build_core_label_index(concepts: dict) -> dict[str, str]:
    """Map canon label → concept id for mappable core concepts only."""
    idx = {}
    for name, c in concepts.items():
        if not is_mappable_concept(name, c):
            continue
        lab = c.get("l") or ""
        if lab:
            idx[canon_label(lab)] = name
        # local-name fallback for GAAP ids
        if ":" not in name:
            idx[canon_label(name)] = name
    return idx


def is_mappable_concept(name: str, c: dict) -> bool:
    if "Placeholder" in name:
        return False
    if name.startswith("root:") or name.startswith("core:"):
        return False
    if name.startswith("et:") or name.startswith("ea:concept:") or name.startswith("discovery:"):
        return False
    if name.startswith("cdi:") or name.startswith("fibo:"):
        return False
    if name.startswith("nongaap:category:"):
        return False
    if name.startswith("nongaap:"):
        return "Placeholder" not in name and name not in {
            "nongaap:ARR",
            "nongaap:NetRevenueRetention",
            "nongaap:BeginningRecurringRevenuePlaceholder",
            "nongaap:EndingRecurringRevenuePlaceholder",
        }
    if name.startswith("ea:metric:"):
        return True
    return c.get("coreTier") == "core" and c.get("layer") in {"gaap", "core", "nongaap"}


def is_structural(name: str, c: dict) -> bool:
    if name.startswith("root:"):
        return True
    if name.startswith("core:v12:"):
        return True
    if c.get("extensionPoint"):
        return True
    return False


def attach_parents_catalog(concepts: dict, populated: set[str]) -> list[dict]:
    """Parents the LLM may attach gap concepts under."""
    preferred = [
        "Revenues",
        "CostOfRevenue",
        "GrossProfit",
        "OperatingExpenses",
        "OperatingIncomeLoss",
        "SellingGeneralAndAdministrativeExpense",
        "ResearchAndDevelopmentExpense",
        "InterestAndDebtExpense",
        "NonoperatingIncomeExpense",
        "IncomeTaxExpenseBenefit",
        "ProfitLoss",
        "Assets",
        "AssetsCurrent",
        "AssetsNoncurrent",
        "CashAndCashEquivalentsAtCarryingValue",
        "ReceivablesNetCurrent",
        "InventoryNet",
        "PropertyPlantAndEquipmentNet",
        "IntangibleAssetsNetIncludingGoodwill",
        "Liabilities",
        "LiabilitiesCurrent",
        "LiabilitiesNoncurrent",
        "AccountsPayableAndAccruedLiabilitiesCurrent",
        "ContractWithCustomerLiability",
        "ShortTermBorrowings",
        "LongTermDebt",
        "StockholdersEquity",
        "RetainedEarningsAccumulatedDeficit",
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInInvestingActivities",
        "NetCashProvidedByUsedInFinancingActivities",
        "core:v12:is_extensions",
        "core:v12:assets.extensions",
        "core:v12:liabilities.extensions",
        "core:v12:equity.extensions",
        "core:v12:cf_extensions",
        "core:v12:metrics_extensions",
        "core:v12:pl_components",
    ]
    out = []
    seen = set()
    for name in preferred:
        if name not in concepts or name in seen:
            continue
        seen.add(name)
        c = concepts[name]
        out.append(
            {
                "id": name,
                "label": c.get("l") or name,
                "populated": name in populated,
                "extensionPoint": bool(c.get("extensionPoint")),
            }
        )
    # Also allow any other currently populated GAAP/nongaap node as parent
    for name in sorted(populated):
        if name in seen or name not in concepts:
            continue
        if name.startswith("company:"):
            continue
        c = concepts[name]
        if not is_mappable_concept(name, c) and not name.startswith("core:v12:"):
            continue
        seen.add(name)
        out.append(
            {
                "id": name,
                "label": c.get("l") or name,
                "populated": True,
                "extensionPoint": bool(c.get("extensionPoint")),
            }
        )
    return out


def apply_company_gaps(
    concepts: dict,
    gaps: list[dict],
    slug: str,
    populated: set[str],
    mapped_labels: dict[str, str],
) -> list[str]:
    """Create company:* nodes from LLM gap proposals and wire relationships."""
    created = []
    order = defaultdict(lambda: 1000)
    for g in gaps:
        parent = g.get("parent")
        if not parent or parent not in concepts:
            continue
        cid = f"company:{slug}:{g['id_slug']}"
        if cid in concepts:
            # already present — still ensure links
            pass
        else:
            rel = g.get("relationship") or "child"
            weight = g.get("weight")
            if weight is None and rel == "component":
                weight = 1.0
            try:
                weight_f = float(weight) if weight is not None else None
            except (TypeError, ValueError):
                weight_f = 1.0 if rel == "component" else None

            concepts[cid] = {
                "n": cid,
                "l": g.get("label") or g.get("source_label") or cid,
                "d": g.get("definition")
                or f"Company-specific concept from {slug} financial statements.",
                "t": "company",
                "a": False,
                "p": "",
                "b": "",
                "k": "derived" if rel == "metric" else "atomic",
                "layer": "company",
                "coreTier": "extension",
                "companyGap": True,
                "companyPopulated": True,
                "companyLabels": [g.get("source_label") or g.get("label")],
                "expression": g.get("formula_expression") or "",
                "f": {
                    "atomic": rel != "metric",
                    "combination": False,
                    "classParent": False,
                    "calcTotal": False,
                    "dimensional": False,
                    "ratio": False,
                    "aggregate": False,
                },
                "pc": [],
                "tc": [],
                "cc": [],
                "cp": [],
                "sc": [],
                "gapMeta": {
                    "statement": g.get("statement"),
                    "relationship": rel,
                    "parent": parent,
                    "reason": g.get("reason"),
                    "confidence": g.get("confidence"),
                },
            }
            created.append(cid)

        # Wire browse + formula edges
        rel = g.get("relationship") or "child"
        weight = g.get("weight")
        if weight is None and rel == "component":
            weight = 1.0
        try:
            weight_f = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight_f = 1.0 if rel == "component" else None

        parent_c = concepts[parent]
        kids = parent_c.setdefault("tc", [])
        if not any(x.get("c") == cid for x in kids):
            link = {"c": cid, "o": order[parent], "net": "CompanyGap"}
            order[parent] += 10
            if weight_f is not None and rel == "component":
                link["w"] = weight_f
            kids.append(link)

        if rel == "component" and weight_f is not None:
            cc = parent_c.setdefault("cc", [])
            if not any(x.get("c") == cid for x in cc):
                cc.append({"c": cid, "w": weight_f, "net": "CompanyGap"})
            cp = concepts[cid].setdefault("cp", [])
            if not any(x.get("c") == parent for x in cp):
                cp.append({"c": parent, "w": weight_f, "net": "CompanyGap"})

        mapped_labels[cid] = g.get("source_label") or g.get("label") or cid
        populated.add(cid)
        # Parent should remain reachable
        populated.add(parent)

    return created


def available(concept: str, populated: set[str], aliases: dict[str, list[str]]) -> bool:
    if concept in populated:
        return True
    for alt in aliases.get(concept, []):
        if alt in populated:
            return True
    return False


def formula_inputs_for(name: str, concepts: dict) -> list[str] | None:
    """Return required inputs for a concept, or None if not a closed formula."""
    if "Placeholder" in name:
        return None
    if name in {
        "nongaap:ARR",
        "nongaap:NetRevenueRetention",
        "nongaap:AdjustedEBITDA",  # needs non-recurring placeholder — skip auto-derive
    }:
        return None
    if name in EXPLICIT_FORMULAS:
        return list(EXPLICIT_FORMULAS[name])
    c = concepts.get(name) or {}
    df = c.get("df")
    if df:
        # Ignore formulas that depend on placeholders
        if any("Placeholder" in x for x in df):
            return None
        return list(df)
    # Weighted browse children ⇒ formula (e.g. GrossProfit tc)
    tc = c.get("tc") or []
    weighted = [x for x in tc if "w" in x]
    if weighted and 1 < len(weighted) <= 6:
        kids = [x["c"] for x in weighted]
        if any("Placeholder" in k for k in kids):
            return None
        return kids
    return None


def close_formulas(seed: set[str], concepts: dict, aliases: dict[str, list[str]]) -> set[str]:
    populated = set(seed)
    # Candidates: anything with df / explicit formula / weighted tc, plus nongaap/metrics
    candidates = set(EXPLICIT_FORMULAS)
    for name, c in concepts.items():
        if c.get("df"):
            candidates.add(name)
        tc = c.get("tc") or []
        if any("w" in x for x in tc) and 1 < len([x for x in tc if "w" in x]) <= 6:
            candidates.add(name)
    changed = True
    while changed:
        changed = False
        for name in list(candidates):
            if name in populated:
                continue
            inputs = formula_inputs_for(name, concepts)
            if not inputs:
                continue
            if all(available(inp, populated, aliases) for inp in inputs):
                populated.add(name)
                changed = True
    return populated


def browse_children(c: dict) -> list[dict]:
    return list(c.get("tc") or [])


def collect_reachable(roots: list[str], concepts: dict) -> set[str]:
    seen = set()
    stack = list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in concepts:
            continue
        seen.add(n)
        for link in browse_children(concepts[n]):
            stack.append(link["c"])
    return seen


def prune_forest(
    roots: list[str],
    concepts: dict,
    populated: set[str],
) -> tuple[list[str], set[str]]:
    """Keep populateable nodes + structural ancestors. Drop empty shells."""

    memo: dict[str, bool] = {}

    def decide(name: str) -> bool:
        if name in memo:
            return memo[name]
        if name not in concepts:
            memo[name] = False
            return False
        # Drop Guidance / Reference for company trees
        if name in {"root:Guidance", "root:Reference"}:
            memo[name] = False
            return False
        c = concepts[name]
        raw_kids = browse_children(c)
        kept_links = []
        for link in raw_kids:
            child = link["c"]
            if decide(child):
                kept_links.append(link)
        c["_kept_tc"] = kept_links

        if name in populated:
            ok = True
        elif is_structural(name, c) and kept_links:
            ok = True
        else:
            # Non-structural (metrics, GAAP lines): only if populateable
            ok = False

        # Empty extension hooks go away
        if (c.get("extensionPoint") or str(name).endswith(".extensions")) and not kept_links:
            ok = False

        memo[name] = ok
        return ok

    new_roots = [r for r in roots if decide(r)]
    kept_nodes = {n for n, ok in memo.items() if ok}
    return new_roots, kept_nodes


def attach_extensions(
    concepts: dict,
    populated: set[str],
    kept: set[str],
    mapped_labels: dict[str, str],
) -> None:
    """Put mapped concepts not already in the browse forest under extension hooks."""
    hooks = {
        "assets": "core:v12:assets.extensions",
        "liabilities": "core:v12:liabilities.extensions",
        "equity": "core:v12:equity.extensions",
        "is": "core:v12:is_extensions",
        "cf": "core:v12:cf_extensions",
        "metrics": "core:v12:metrics_extensions",
    }
    # Ensure hooks exist in kept set if we attach anything
    reachable = collect_reachable(
        [r for r in concepts if r.startswith("root:")], concepts
    )

    def bucket(name: str) -> str | None:
        if name in ASSET_CONCEPTS or name.startswith("Assets"):
            return "assets"
        if name in LIAB_CONCEPTS or name.startswith("Liabilit"):
            return "liabilities"
        if name in EQUITY_CONCEPTS or "Equity" in name or name.endswith("StockValue"):
            return "equity"
        if name in IS_CONCEPTS or name.startswith("nongaap:") and name in {
            "nongaap:EBITDA",
            "nongaap:GrossMargin",
            "nongaap:OperatingMargin",
        }:
            return "is"
        if name in CF_CONCEPTS or name.startswith("NetCash") or name.startswith("PaymentsTo"):
            return "cf"
        if name.startswith("nongaap:") or name.startswith("ea:metric:"):
            return "metrics"
        return None

    order_counters = defaultdict(lambda: 10)
    for name in sorted(populated):
        if name in reachable and name in kept:
            continue
        b = bucket(name)
        if not b:
            continue
        hook = hooks[b]
        if hook not in concepts:
            continue
        # Skip if already a direct child of something kept
        already = False
        for n in kept:
            for link in browse_children(concepts.get(n) or {}):
                if link["c"] == name:
                    already = True
                    break
            if already:
                break
        if already:
            continue
        kids = concepts[hook].setdefault("tc", [])
        if any(x.get("c") == name for x in kids):
            continue
        kids.append({"c": name, "o": order_counters[hook], "net": "CompanyExtension"})
        order_counters[hook] += 10
        # ensure hook kept / parent chain
        concepts[hook]["extensionPoint"] = True
        # annotate source label
        if name in concepts and name in mapped_labels:
            concepts[name].setdefault("companyLabels", [])
            if mapped_labels[name] not in concepts[name]["companyLabels"]:
                concepts[name]["companyLabels"].append(mapped_labels[name])
        kept.add(name)
        kept.add(hook)


def apply_kept_tc(concepts: dict, kept: set[str]) -> None:
    for name, c in concepts.items():
        if "_kept_tc" in c:
            c["tc"] = [x for x in c["_kept_tc"] if x["c"] in kept]
            del c["_kept_tc"]
        elif name in kept:
            c["tc"] = [x for x in (c.get("tc") or []) if x["c"] in kept]
        # Filter calc / presentation / used-by to kept only for cleaner Formulas mode
        if name in kept:
            for key in ("cc", "pc", "cp"):
                if key in c and isinstance(c[key], list):
                    c[key] = [x for x in c[key] if isinstance(x, dict) and x.get("c") in kept]
            if "sc" in c and isinstance(c["sc"], list):
                c["sc"] = [x for x in c["sc"] if x in kept]
            if "df" in c and isinstance(c["df"], list):
                # keep df for transparency even if some missing — but trim to available
                pass


def slim_payload(
    base: dict,
    kept: set[str],
    roots: list[str],
    meta_extra: dict,
    mappings: list[dict],
    gaps: list[dict] | None = None,
) -> dict:
    concepts = {k: v for k, v in base["concepts"].items() if k in kept}
    for c in concepts.values():
        c.pop("_kept_tc", None)

    summary = dict(base.get("summary") or {})
    summary.update(
        {
            "ontologyNodes": len(concepts),
            "forestRoots": len(roots),
            "companyMappedLabels": sum(1 for m in mappings if m.get("concept")),
            "companyUnmappedLabels": sum(1 for m in mappings if not m.get("concept")),
            "companyPopulatedConcepts": meta_extra.get("populatedCount", 0),
            "companyGapConcepts": meta_extra.get("gapCount", 0),
        }
    )
    meta = dict(base.get("meta") or {})
    meta.update(meta_extra)
    meta["companyTree"] = True
    meta["defaultBrowseMode"] = "presentation"

    return {
        "meta": meta,
        "summary": summary,
        "ontologyRoots": roots,
        "classRoots": [r for r in (base.get("classRoots") or []) if r in kept],
        "presentationNetworkRoots": base.get("presentationNetworkRoots") or {},
        "browseModes": base.get("browseModes"),
        "concepts": concepts,
        "companyMappings": [m for m in mappings if m.get("concept")][:500],
        "companyGaps": gaps or [],
    }


def build_company_tree(cfg: dict, base: dict, aliases: dict, *, refresh_llm: bool = False) -> dict:
    concepts = base["concepts"]
    sources, by_stmt, labels = extract_company_labels(cfg)

    candidates = build_candidate_list(concepts, is_mappable_concept)
    cache_dir = OUT_DIR / cfg["slug"]
    mapped, details = map_labels_with_llm(
        company_name=cfg["name"],
        labels_by_statement=by_stmt,
        candidates=candidates,
        cache_path=cache_dir / "llm_map_cache.json",
        refresh=refresh_llm,
    )

    # Drop any accidental non-mappable ids
    mapped = {
        k: v
        for k, v in mapped.items()
        if k in concepts and is_mappable_concept(k, concepts[k])
    }

    seed = set(mapped.keys())
    work = json.loads(json.dumps(concepts))
    populated = close_formulas(seed, work, aliases)

    for concept, lab in mapped.items():
        if concept in work:
            work[concept].setdefault("companyLabels", [])
            if lab not in work[concept]["companyLabels"]:
                work[concept]["companyLabels"].append(lab)
            work[concept]["companyPopulated"] = True
    for name in populated:
        if name in work:
            work[name]["companyPopulated"] = True
            if name not in seed:
                work[name]["companyDerived"] = True

    # --- Gap analysis: important unmapped lines → new company nodes ---
    unmapped_rows = [m for m in details if not m.get("concept")]
    mapped_concept_info = [
        {"id": cid, "label": work[cid].get("l", cid), "example": mapped[cid]}
        for cid in sorted(seed)
        if cid in work
    ]
    parents = attach_parents_catalog(work, populated)
    gaps = propose_gaps_with_llm(
        company_name=cfg["name"],
        company_slug=cfg["slug"],
        unmapped_labels=unmapped_rows,
        mapped_concepts=mapped_concept_info,
        attach_parents=parents,
        cache_path=cache_dir / "llm_gap_cache.json",
        refresh=refresh_llm,
    )
    created_gaps = apply_company_gaps(work, gaps, cfg["slug"], populated, mapped)
    # Re-close formulas in case gap metrics introduced df-style nodes (none yet)
    populated = close_formulas(populated, work, aliases)

    roots = list(base.get("ontologyRoots") or [])
    base_work = {**base, "concepts": work}
    new_roots, kept = prune_forest(roots, work, populated)
    attach_extensions(work, populated, kept, mapped)

    for c in work.values():
        c.pop("_kept_tc", None)
    new_roots, kept = prune_forest(roots, work, populated | kept)
    attach_extensions(work, populated, kept, mapped)
    apply_kept_tc(work, kept)
    kept |= {n for n in populated if n in work}

    meta_extra = {
        "company": cfg["name"],
        "companySlug": cfg["slug"],
        "sourceFiles": [p.name for p in sources],
        "baseOntologyVersion": (base.get("meta") or {}).get("ontologyVersion", "1.2"),
        "mappingMethod": "claude-llm",
        "populatedCount": len(populated),
        "seedMappedCount": len(seed),
        "derivedCount": len(populated - seed - set(created_gaps)),
        "gapCount": len(created_gaps),
        "notes": (
            "Company tree pruned from ontology v1.2 using Claude mapping + gap analysis. "
            "Existing concepts are kept if reported or formula-complete. Important statement "
            "lines missing from the ontology are added as company:* nodes under the right parent "
            "with browse/formula relationships."
        ),
    }

    payload = slim_payload(base_work, kept, new_roots, meta_extra, details, gaps=gaps)
    payload["_debug"] = {
        "labelsSample": labels[:40],
        "byStatementCounts": {k: len(v) for k, v in by_stmt.items()},
        "seed": sorted(seed),
        "gapsCreated": created_gaps,
        "derived": sorted(populated - seed - set(created_gaps)),
        "populated": sorted(populated),
        "unmappedSample": [m["label"] for m in details if not m.get("concept")][:40],
    }
    return payload


def write_company(payload: dict, slug: str) -> Path:
    out = OUT_DIR / slug
    out.mkdir(parents=True, exist_ok=True)
    debug = payload.pop("_debug", None)
    path = out / "taxonomy-data.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if debug:
        (out / "coverage.json").write_text(
            json.dumps(debug, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if payload.get("companyGaps") is not None:
        (out / "gaps.json").write_text(
            json.dumps(payload["companyGaps"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    vdir = VIEWER_DIR / slug
    vdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, vdir / "taxonomy-data.json")
    # GitHub Pages serves from repo root
    pdir = PAGES_DIR / slug
    pdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, pdir / "taxonomy-data.json")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build company ontology trees via Claude")
    parser.add_argument(
        "--refresh-llm",
        action="store_true",
        help="Ignore LLM caches and re-query Claude",
    )
    parser.add_argument(
        "--company",
        action="append",
        dest="companies",
        help="Only build this company slug (repeatable)",
    )
    args = parser.parse_args()

    print(f"Loading ontology: {ONTOLOGY_PATH}")
    base = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    _, aliases = load_synonyms()
    catalog = [
        {
            "id": "v1.2",
            "label": "Ontology v1.2 (full core)",
            "path": "taxonomy-data.json",
        }
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VIEWER_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    selected = [c for c in COMPANIES if not args.companies or c["slug"] in args.companies]
    for cfg in selected:
        print(f"\n=== {cfg['name']} ===")
        payload = build_company_tree(cfg, base, aliases, refresh_llm=args.refresh_llm)
        path = write_company(payload, cfg["slug"])
        n = len(payload["concepts"])
        roots = payload["ontologyRoots"]
        print(f"  wrote {path}")
        print(f"  sources: {payload['meta'].get('sourceFiles')}")
        print(
            f"  mapped={payload['meta']['seedMappedCount']} "
            f"gaps={payload['meta']['gapCount']} "
            f"derived={payload['meta']['derivedCount']} "
            f"populated={payload['meta']['populatedCount']} "
            f"nodes={n} roots={roots}"
        )
        catalog.append(
            {
                "id": cfg["slug"],
                "label": cfg["name"],
                "path": f"companies/{cfg['slug']}/taxonomy-data.json",
                "populated": payload["meta"]["populatedCount"],
                "gaps": payload["meta"]["gapCount"],
                "nodes": n,
            }
        )

    # If building a subset, merge with existing catalog entries for other companies
    catalog_path = VIEWER_DIR / "catalog.json"
    if args.companies and catalog_path.exists():
        old = json.loads(catalog_path.read_text(encoding="utf-8"))
        by_id = {x["id"]: x for x in old}
        for entry in catalog:
            by_id[entry["id"]] = entry
        # preserve order: v1.2 then companies
        ordered = [by_id["v1.2"]] if "v1.2" in by_id else []
        for c in COMPANIES:
            if c["slug"] in by_id:
                ordered.append(by_id[c["slug"]])
        catalog = ordered

    catalog_path.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    (OUT_DIR / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    (PAGES_DIR / "catalog.json").write_text(json.dumps(catalog, indent=2), encoding="utf-8")
    print(f"\nCatalog -> {catalog_path}")


if __name__ == "__main__":
    main()
