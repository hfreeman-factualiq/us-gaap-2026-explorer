#!/usr/bin/env python3
"""Build unified financial ontology: US GAAP + Non-GAAP + SEC C&DIs + curated FIBO.

One-command rebuild:
  python build_ontology.py

Optional:
  python scripts/fetch_external_resources.py   # refresh C&DIs / FIBO vendor extract
  python build_ontology.py --skip-gaap         # reuse cached gaap-only intermediate
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

from build_viewer_data import (
    ALT_STATEMENT_NETWORKS,
    PREFERRED_STATEMENT_NETWORKS,
    build_gaap_data,
)
from prune_ontology import FOREST_ORDER as _V10_FOREST, ROOT_META as _V10_META, restructure_forest
from prune_core_v11 import (
    FOREST_ORDER as CORE_FOREST_ORDER,
    ROOT_META as CORE_ROOT_META,
    apply_core_generalizable,
)
from prune_core_v12 import (
    FOREST_ORDER as V12_FOREST_ORDER,
    ROOT_META as V12_ROOT_META,
    apply_core_v12,
)
from prune_core_v13 import (
    FOREST_ORDER as V13_FOREST_ORDER,
    ROOT_META as V13_ROOT_META,
    apply_core_v13,
)

ROOT = Path(__file__).resolve().parent
ONTOLOGY = ROOT / "ontology"
VIEWER_OUT = ROOT / "viewer" / "taxonomy-data.json"
ROOT_OUT = ROOT / "taxonomy-data.json"
DATA_OUT = ROOT / "data" / "ontology-full.json"
SUMMARY_MD = ONTOLOGY / "summary.md"

# Active forest = collapsed extensible core + standards scrape surface (v1.31)
FOREST_ORDER = V13_FOREST_ORDER
ROOT_META = V13_ROOT_META

# Keep legacy labels available for merge helpers that still create old roots;
# final forest is replaced by prune_core_v12.apply_core_v12().
SYNTHETIC_ROOT_META = {
    **ROOT_META,
    "root:FinancialPosition": {
        "l": "Financial Position (legacy)",
        "d": "Legacy balance-sheet root.",
    },
    "root:ComprehensiveIncome": {
        "l": "Comprehensive Income (legacy)",
        "d": "Legacy income root.",
    },
    "root:CashFlows": {
        "l": "Cash Flows (legacy)",
        "d": "Legacy cash-flow root.",
    },
    "root:Equity": {
        "l": "Equity (legacy)",
        "d": "Legacy equity root.",
    },
    "root:ClassOntology": {
        "l": "Class Ontology (legacy)",
        "d": "Legacy class–subclass root.",
    },
    "root:NonGAAP": {
        "l": "Non-GAAP Metrics (legacy)",
        "d": "Legacy Non-GAAP root.",
    },
    "root:FIBO": {
        "l": "FIBO-Aligned Metrics",
        "d": "Curated FIBO financial concepts aligned to US GAAP and non-GAAP nodes.",
    },
    "root:Discovery": {
        "l": "Discovery Sources (legacy)",
        "d": "Legacy discovery root.",
    },
}


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def ensure_external_seeds() -> None:
    """Ensure C&DI / FIBO JSON exist (generate curated offline if missing)."""
    cdi = ONTOLOGY / "sec_nongaap_cdis.json"
    fibo = ONTOLOGY / "fibo_metrics_curated.json"
    if cdi.exists() and fibo.exists():
        return
    print("External ontology JSON missing — generating curated seeds offline...")
    import scripts.fetch_external_resources as fetch

    fetch.refresh_cdis(try_network=False)
    fetch.refresh_fibo(try_network=False)


def make_root_node(name: str, children: list[dict] | None = None) -> dict:
    meta = SYNTHETIC_ROOT_META[name]
    entry = {
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
    }
    if children:
        entry["pc"] = children
        # Also expose as sc for class-mode browsing of synthetic roots
        entry["sc"] = [c["c"] for c in children]
    return entry


def attach_statement_roots(concepts: dict, gaap: dict) -> None:
    net_roots: dict[str, list[str]] = gaap.get("presentationNetworkRoots") or {}
    preferred = gaap.get("preferredStatementNetworks") or PREFERRED_STATEMENT_NETWORKS
    alts = gaap.get("altStatementNetworks") or ALT_STATEMENT_NETWORKS

    buckets: dict[str, list[dict]] = defaultdict(list)
    order_counter: dict[str, int] = defaultdict(int)

    def add_link(root_id: str, concept: str, network: str, preferred_flag: bool) -> None:
        if concept not in concepts:
            return
        order_counter[root_id] += 10
        buckets[root_id].append(
            {
                "c": concept,
                "o": order_counter[root_id],
                "net": network,
                "preferred": preferred_flag,
            }
        )

    for network, root_id in preferred.items():
        for concept in net_roots.get(network, []):
            add_link(root_id, concept, network, True)

    for network, root_id in alts.items():
        for concept in net_roots.get(network, []):
            add_link(root_id, concept, network, False)

    # Any remaining statement networks under stm that map by name heuristics
    for network, roots in net_roots.items():
        if network in preferred or network in alts:
            continue
        root_id = None
        nlow = network.lower()
        if "financialposition" in nlow or "balancesheet" in nlow:
            root_id = "root:FinancialPosition"
        elif "cashflow" in nlow:
            root_id = "root:CashFlows"
        elif "equity" in nlow or "stockholder" in nlow or "shareholder" in nlow:
            root_id = "root:Equity"
        elif "income" in nlow or "comprehensive" in nlow:
            root_id = "root:ComprehensiveIncome"
        if not root_id:
            continue
        for concept in roots:
            add_link(root_id, concept, network, False)

    for root_id in (
        "root:FinancialPosition",
        "root:ComprehensiveIncome",
        "root:CashFlows",
        "root:Equity",
    ):
        # Prefer first link per concept (preferred networks are inserted first).
        seen: set[str] = set()
        deduped: list[dict] = []
        for link in buckets.get(root_id, []):
            if link["c"] in seen:
                continue
            seen.add(link["c"])
            deduped.append(link)
        concepts[root_id] = make_root_node(root_id, deduped)


def attach_class_ontology_root(concepts: dict, class_roots: list[str]) -> None:
    kids = [{"c": r, "o": (i + 1) * 10, "net": "ClassSubclass"} for i, r in enumerate(class_roots)]
    concepts["root:ClassOntology"] = make_root_node("root:ClassOntology", kids)
    for r in class_roots:
        if r in concepts:
            concepts[r].setdefault("sp", [])
            if "root:ClassOntology" not in concepts[r]["sp"]:
                concepts[r]["sp"] = ["root:ClassOntology"] + concepts[r]["sp"]


def formula_input_refs(formula: dict | None) -> list[str]:
    if not formula or not isinstance(formula, dict):
        return []
    refs: list[str] = []
    if formula.get("op") == "ref" and formula.get("concept"):
        refs.append(str(formula["concept"]))
    for arg in formula.get("args") or []:
        refs.extend(formula_input_refs(arg))
    return refs


def merge_nongaap(concepts: dict, catalog: dict) -> list[str]:
    metrics = catalog.get("metrics") or []
    metric_ids: list[str] = []
    categories: dict[str, list[str]] = defaultdict(list)

    for m in metrics:
        mid = m["id"]
        metric_ids.append(mid)
        cat = m.get("category") or "other"
        categories[cat].append(mid)

        inputs = list(m.get("inputs") or [])
        for ref in formula_input_refs(m.get("formula")):
            if ref not in inputs:
                inputs.append(ref)

        entry = {
            "n": mid,
            "l": m.get("label") or mid,
            "d": (m.get("definition") or "")[:500],
            "t": "derivedMetric",
            "a": False,
            "p": "duration",
            "b": "",
            "k": "derived",
            "layer": "nongaap",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": False,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "formula": m.get("formula"),
            "expression": m.get("expression") or "",
            "df": inputs,  # derivedFrom GAAP / metric refs
            "secCaveats": m.get("secCaveats") or [],
            "fiboAligns": m.get("fiboAligns") or [],
            "category": cat,
        }
        if m.get("reconciliationHint"):
            entry["reconciliationHint"] = m["reconciliationHint"]
        if m.get("alternativeOf"):
            entry["alternativeOf"] = m["alternativeOf"]
        if m.get("isPlaceholder"):
            entry["isPlaceholder"] = True
        if m.get("isApproximation"):
            entry["isApproximation"] = True
        if m.get("alternateInputs"):
            entry["alternateInputs"] = m["alternateInputs"]

        # Presentation children = formula inputs (for Non-GAAP browse mode)
        entry["pc"] = [
            {"c": c, "o": (i + 1) * 10, "net": "DerivedFrom"}
            for i, c in enumerate(inputs)
            if c
        ]
        entry["sc"] = [c["c"] for c in entry["pc"]]

        concepts[mid] = entry

        # Inverse edges on GAAP / other metric nodes
        for inp in inputs:
            if inp not in concepts:
                continue
            concepts[inp].setdefault("fo", [])  # formulaOf
            if mid not in concepts[inp]["fo"]:
                concepts[inp]["fo"].append(mid)

        alt = m.get("alternativeOf")
        if alt and alt in concepts:
            concepts[alt].setdefault("alts", [])
            if mid not in concepts[alt]["alts"]:
                concepts[alt]["alts"].append(mid)

    # Category abstract nodes under root:NonGAAP
    cat_nodes = []
    for i, (cat, ids) in enumerate(sorted(categories.items())):
        cid = f"nongaap:category:{cat}"
        concepts[cid] = {
            "n": cid,
            "l": cat.replace("_", " ").title(),
            "d": f"Non-GAAP metrics in category '{cat}'.",
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
            "pc": [{"c": mid, "o": (j + 1) * 10, "net": "NonGAAPCategory"} for j, mid in enumerate(ids)],
            "sc": ids,
        }
        cat_nodes.append({"c": cid, "o": (i + 1) * 10, "net": "NonGAAP"})

    concepts["root:NonGAAP"] = make_root_node("root:NonGAAP", cat_nodes)
    return metric_ids


def merge_cdis(concepts: dict, cdi_doc: dict) -> int:
    rules = cdi_doc.get("rules") or []
    rule_children = []
    for i, rule in enumerate(rules):
        rid = rule["id"]
        governs = list(rule.get("governs") or [])
        # Also pick up reverse links from metrics' secCaveats
        for name, c in concepts.items():
            if c.get("layer") == "nongaap" and rid in (c.get("secCaveats") or []):
                if name not in governs:
                    governs.append(name)

        entry = {
            "n": rid,
            "l": rule.get("title") or rid,
            "d": (rule.get("answer") or rule.get("question") or "")[:500],
            "t": "secRule",
            "a": False,
            "p": "",
            "b": "",
            "k": "rule",
            "layer": "rule",
            "f": {
                "atomic": False,
                "combination": False,
                "classParent": False,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "questionId": rule.get("questionId"),
            "question": rule.get("question"),
            "answer": rule.get("answer"),
            "tags": rule.get("tags") or [],
            "sourceUrl": rule.get("sourceUrl"),
            "governs": governs,
            "pc": [{"c": g, "o": (j + 1) * 10, "net": "Governs"} for j, g in enumerate(governs)],
            "sc": governs,
        }
        # Prefer clean staff labels: "C&DI {id} — {short title}"
        qid = rule.get("questionId") or rid.replace("cdi:", "")
        title = (rule.get("title") or "").strip()
        q = (rule.get("question") or "").strip()
        # Scraped SEC pages often concatenate many Q&As into one blob.
        noisy = (
            title.lower().count("question") > 1
            or q.lower().count("question") > 1
            or "[may" in title.lower()
            or "[december" in title.lower()
            or len(title) > 100
        )
        if noisy:
            # Use curated short titles when present and clean; else id-only
            if title and title.lower().count("question") <= 1 and len(title) <= 100 and not title.lower().startswith("question"):
                short = title
            else:
                short = f"Non-GAAP Financial Measures"
            entry["l"] = f"C&DI {qid} — {short}"
        else:
            if title.lower().startswith("question"):
                title = title.split(":", 1)[-1].strip() if ":" in title else title
            if not title and q:
                title = q.split(":", 1)[-1].strip() if q.lower().startswith("question") else q
                title = title[:90] + ("…" if len(title) > 90 else "")
            entry["l"] = f"C&DI {qid} — {title or 'Non-GAAP Financial Measures'}"
        concepts[rid] = entry
        rule_children.append({"c": rid, "o": (i + 1) * 10, "net": "SEC_CDI"})

        for g in governs:
            if g in concepts:
                concepts[g].setdefault("secCaveats", [])
                if rid not in concepts[g]["secCaveats"]:
                    concepts[g]["secCaveats"].append(rid)

    # Attach rules folder under NonGAAP root
    if "root:NonGAAP" in concepts:
        rules_folder = "nongaap:SEC_CDIs"
        concepts[rules_folder] = {
            "n": rules_folder,
            "l": "SEC Non-GAAP C&DIs",
            "d": "Staff Compliance & Disclosure Interpretations governing non-GAAP measures.",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "abstract",
            "layer": "rule",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": True,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": rule_children,
            "sc": [c["c"] for c in rule_children],
        }
        root = concepts["root:NonGAAP"]
        root.setdefault("pc", []).append(
            {"c": rules_folder, "o": 1000, "net": "NonGAAP"}
        )
        root.setdefault("sc", []).append(rules_folder)
    return len(rules)


def merge_fibo(concepts: dict, fibo_doc: dict) -> int:
    items = fibo_doc.get("concepts") or []
    kids = []
    for i, item in enumerate(items):
        fid = item["id"]
        aligns = list(item.get("alignsTo") or [])
        entry = {
            "n": fid,
            "l": item.get("label") or fid,
            "d": (item.get("definition") or "")[:500],
            "t": "fiboConcept",
            "a": False,
            "p": "",
            "b": "",
            "k": "fibo",
            "layer": "fibo",
            "f": {
                "atomic": False,
                "combination": True,
                "classParent": False,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "fiboIri": item.get("fiboIri"),
            "alignsTo": aligns,
            "mapped": bool(item.get("mapped")),
            "pc": [{"c": a, "o": (j + 1) * 10, "net": "AlignsTo"} for j, a in enumerate(aligns)],
            "sc": aligns,
        }
        concepts[fid] = entry
        kids.append({"c": fid, "o": (i + 1) * 10, "net": "FIBO"})

        for a in aligns:
            if a in concepts:
                concepts[a].setdefault("fiboAligned", [])
                if fid not in concepts[a]["fiboAligned"]:
                    concepts[a]["fiboAligned"].append(fid)

    concepts["root:FIBO"] = make_root_node("root:FIBO", kids)
    return len(items)


def merge_discovery(concepts: dict, catalog: dict) -> dict:
    """Merge harvested edgartools / edgar_analytics / Finnhub nodes for exploration."""
    nodes = catalog.get("nodes") or []
    by_source: dict[str, list[str]] = defaultdict(list)
    by_category: dict[str, list[str]] = defaultdict(list)
    gap_ids: list[str] = []
    added = 0

    for item in nodes:
        nid = item["id"]
        maps = [t for t in (item.get("mapsTo") or []) if t]
        # Keep mapsTo edges even when target missing — still useful for gap browsing
        kind = "gap" if item.get("gap") or item.get("kind") == "gap" else "discovery"
        entry = {
            "n": nid,
            "l": item.get("label") or nid,
            "d": (item.get("definition") or "")[:500],
            "t": "discovery",
            "a": False,
            "p": "",
            "b": "",
            "k": kind,
            "layer": "discovery",
            "source": item.get("source"),
            "category": item.get("category"),
            "expression": item.get("expression") or "",
            "mapsTo": maps,
            "inputSynonyms": item.get("inputSynonyms") or [],
            "gap": bool(item.get("gap") or item.get("kind") == "gap"),
            "f": {
                "atomic": False,
                "combination": bool(maps),
                "classParent": False,
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": t, "o": (j + 1) * 10, "net": "MapsTo"} for j, t in enumerate(maps)],
            "sc": maps,
        }
        concepts[nid] = entry
        added += 1
        src = item.get("source") or "unknown"
        by_source[src].append(nid)
        by_category[item.get("category") or "other"].append(nid)
        if entry["gap"]:
            gap_ids.append(nid)

        for t in maps:
            if t in concepts:
                concepts[t].setdefault("discoveredBy", [])
                if nid not in concepts[t]["discoveredBy"]:
                    concepts[t]["discoveredBy"].append(nid)

    # Source folders
    source_nodes = []
    for i, (src, ids) in enumerate(sorted(by_source.items())):
        sid = f"discovery:source:{src}"
        concepts[sid] = {
            "n": sid,
            "l": src.replace("_", " ").title(),
            "d": f"Nodes harvested from {src} for ontology expansion.",
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
            "pc": [{"c": x, "o": (j + 1) * 10, "net": "DiscoverySource"} for j, x in enumerate(ids)],
            "sc": ids,
        }
        source_nodes.append({"c": sid, "o": (i + 1) * 10, "net": "Discovery"})

    # Gaps folder
    if gap_ids:
        gid = "discovery:gaps"
        concepts[gid] = {
            "n": gid,
            "l": "Coverage Gaps",
            "d": "Metrics/tags found in discovery libraries but missing or under-covered in our Non-GAAP layer.",
            "t": "category",
            "a": True,
            "p": "",
            "b": "",
            "k": "gap",
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
            "pc": [{"c": x, "o": (j + 1) * 10, "net": "Gap"} for j, x in enumerate(gap_ids)],
            "sc": gap_ids,
        }
        source_nodes.append({"c": gid, "o": 900, "net": "Discovery"})

    concepts["root:Discovery"] = make_root_node("root:Discovery", source_nodes)
    return {
        "discoveryNodes": added,
        "discoverySources": len(by_source),
        "discoveryGaps": len(gap_ids),
    }


STANDARD_ROLE = {
    "signalDomain": "abstract",
    "signal": "signal",
    "standard": "standard",
    "standardClass": "standard",
    "scrapeTarget": "scrape",
}

STANDARD_PASSTHROUGH = [
    "classId",
    "domain",
    "domainLabels",
    "domains",
    "expression",
    "formats",
    "gaapTags",
    "integration",
    "keyClasses",
    "nongaapRefs",
    "order",
    "primaryStandards",
    "probe",
    "scrapeKind",
    "scrapeTargets",
    "signalKey",
    "signals",
    "standard",
    "standardClasses",
    "steward",
    "url",
    "verified",
]


def merge_external_standards(concepts: dict, catalog: dict) -> dict:
    """Merge the formalized-standards registry (signal domains, standards, scrape targets)."""
    nodes = catalog.get("nodes") or []
    for item in nodes:
        nid = item["id"]
        kind = item.get("kind") or "standard"
        maps = [t for t in (item.get("mapsTo") or []) if t]
        entry = {
            "n": nid,
            "l": item.get("label") or nid,
            "d": (item.get("definition") or "")[:500],
            "t": kind,
            "a": kind in {"signalDomain", "standard"},
            "p": "",
            "b": "",
            "k": STANDARD_ROLE.get(kind, "standard"),
            "layer": "standard",
            "stdKind": kind,
            "category": item.get("category"),
            "mapsTo": maps,
            "gap": bool(item.get("gap")),
            "f": {
                "atomic": False,
                "combination": bool(maps),
                "classParent": kind in {"signalDomain", "standard"},
                "calcTotal": False,
                "dimensional": False,
                "ratio": False,
                "aggregate": False,
            },
            "pc": [{"c": t, "o": (j + 1) * 10, "net": "MapsTo"} for j, t in enumerate(maps)],
            "sc": maps,
        }
        for key in STANDARD_PASSTHROUGH:
            if item.get(key) not in (None, [], ""):
                entry[key] = item[key]
        concepts[nid] = entry

        for target in maps:
            if target in concepts and target != nid:
                concepts[target].setdefault("standardizedBy", [])
                if nid not in concepts[target]["standardizedBy"]:
                    concepts[target]["standardizedBy"].append(nid)

    summary = catalog.get("summary") or {}
    return {
        "standardNodes": len(nodes),
        "signalDomains": summary.get("signalDomains", 0),
        "signals": summary.get("signals", 0),
        "standards": summary.get("standards", 0),
        "standardClasses": summary.get("standardClasses", 0),
        "scrapedClasses": summary.get("scrapedClasses", 0),
        "scrapeTargets": summary.get("scrapeTargets", 0),
        "scrapeTargetsReachable": summary.get("reachableTargets", 0),
    }


def write_summary(data: dict) -> None:
    s = data["summary"]
    lines = [
        "# Ontology build summary",
        "",
        f"- Total concepts: **{s.get('totalConcepts', 0):,}**",
        f"- Presentation arcs: **{s.get('preArcs', 0):,}**",
        f"- Calculation arcs: **{s.get('calcArcs', 0):,}**",
        f"- Non-GAAP metrics: **{s.get('nongaapMetrics', 0):,}**",
        f"- SEC C&DI rules: **{s.get('secRules', 0):,}**",
        f"- FIBO curated concepts: **{s.get('fiboConcepts', 0):,}**",
        f"- Discovery nodes: **{s.get('discoveryNodes', 0):,}**",
        f"- Discovery gaps flagged: **{s.get('discoveryGaps', 0):,}**",
        f"- Signal domains: **{s.get('signalDomains', 0):,}**",
        f"- Signals: **{s.get('signals', 0):,}**",
        f"- Formalized standards registered: **{s.get('standards', 0):,}**",
        f"- Standard key classes: **{s.get('standardClasses', 0):,}**",
        f"- Scraped classes (from XSD/XMI/JSON): **{s.get('scrapedClasses', 0):,}**",
        f"- Scrape targets: **{s.get('scrapeTargets', 0):,}**",
        f"- Forest roots: {', '.join(data.get('ontologyRoots') or [])}",
        "",
        "## Layers",
        "",
    ]
    for layer, count in sorted((s.get("layerCounts") or {}).items()):
        lines.append(f"- `{layer}`: {count:,}")
    lines.append("")
    SUMMARY_MD.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {SUMMARY_MD}")


def dump_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {path} ...")
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    mb = path.stat().st_size / (1024 * 1024)
    print(f"  {mb:.1f} MB")


def build(skip_gaap: bool = False) -> dict:
    ensure_external_seeds()

    cache = ROOT / "data" / "gaap-only.json"
    if skip_gaap and cache.exists():
        print(f"Loading cached GAAP graph: {cache}")
        gaap = load_json(cache)
    else:
        print("Building GAAP graph from local taxonomy package...")
        gaap = build_gaap_data()
        dump_json(cache, gaap)

    concepts = gaap["concepts"]
    attach_statement_roots(concepts, gaap)
    attach_class_ontology_root(concepts, gaap.get("classRoots") or gaap.get("ontologyRoots") or [])

    catalog = load_yaml(ONTOLOGY / "nongaap_metrics.yaml")
    metric_ids = merge_nongaap(concepts, catalog)

    cdi_doc = load_json(ONTOLOGY / "sec_nongaap_cdis.json")
    n_rules = merge_cdis(concepts, cdi_doc)

    fibo_doc = load_json(ONTOLOGY / "fibo_metrics_curated.json")
    n_fibo = merge_fibo(concepts, fibo_doc)

    discovery_path = ONTOLOGY / "discovery_catalog.json"
    discovery_stats = {"discoveryNodes": 0, "discoverySources": 0, "discoveryGaps": 0}
    if discovery_path.exists():
        discovery_stats = merge_discovery(concepts, load_json(discovery_path))
    else:
        print("No ontology/discovery_catalog.json — run scripts/harvest_discovery_sources.py")

    standards_path = ONTOLOGY / "external_standards_catalog.json"
    standards_stats = {"standardNodes": 0, "signals": 0, "standards": 0}
    if not standards_path.exists() and (ONTOLOGY / "external_standards.yaml").exists():
        print("Standards catalog missing — harvesting registry offline…")
        import scripts.harvest_external_standards as harvest_standards

        harvest_standards.harvest(try_network=False)
    if standards_path.exists():
        standards_stats = merge_external_standards(concepts, load_json(standards_path))
    else:
        print("No ontology/external_standards_catalog.json — run scripts/harvest_external_standards.py")

    print("Pruning / restructuring forest for collapsed extensible core + standards (v1.31)…")
    prune_stats = apply_core_v13(concepts)

    layer_counts: dict[str, int] = defaultdict(int)
    kind_counts: dict[str, int] = defaultdict(int)
    for c in concepts.values():
        layer_counts[c.get("layer") or "gaap"] += 1
        kind_counts[c.get("k") or ""] += 1

    summary = dict(gaap.get("summary") or {})
    summary.update(
        {
            "totalConcepts": len(concepts),
            "nongaapMetrics": len(metric_ids),
            "secRules": n_rules,
            "fiboConcepts": n_fibo,
            "forestRoots": len(FOREST_ORDER),
            "layerCounts": dict(sorted(layer_counts.items())),
            "kindCounts": dict(sorted(kind_counts.items(), key=lambda x: -x[1])),
            **discovery_stats,
            **standards_stats,
            **prune_stats,
        }
    )

    data = {
        "meta": {
            **(gaap.get("meta") or {}),
            "unifiedOntology": True,
            "prunedForest": True,
            "coreGeneralizable": True,
            "coreCollapsed": True,
            "ontologyVersion": "1.31",
            "layers": [
                "gaap",
                "nongaap",
                "fibo",
                "rule",
                "discovery",
                "standard",
                "root",
                "core",
            ],
            "defaultBrowseMode": "presentation",
            "notes": (
                (gaap.get("meta") or {}).get("notes", "")
                + " v1.2 collapsed extensible core: short BS/IS/CF chains with explicit "
                "extension hooks for project grow/prune. Specialized concepts remain under "
                "Reference & Extensions. v1.3 adds Signal Domains and Standards & Scrape "
                "Sources driven by ontology/external_standards.yaml. v1.31 expands that "
                "registry with strategy/ops/governance frameworks (BMM, DMN, VDML, SCOR, "
                "BIAN, DORA, Open FAIR, COBIT, ITIL 4, SASB/ISSB) and scrapes machine-readable "
                "XSD/XMI artifacts into standard-class nodes."
            ),
        },
        "summary": summary,
        "ontologyRoots": FOREST_ORDER,
        "classRoots": gaap.get("classRoots") or [],
        "presentationNetworkRoots": gaap.get("presentationNetworkRoots") or {},
        "browseModes": ["presentation", "subtypes", "formula", "usedby", "nongaap", "discovery"],
        "concepts": concepts,
    }
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Build unified financial ontology JSON")
    parser.add_argument(
        "--skip-gaap",
        action="store_true",
        help="Reuse data/gaap-only.json instead of re-parsing XBRL",
    )
    args = parser.parse_args()

    data = build(skip_gaap=args.skip_gaap)
    dump_json(VIEWER_OUT, data)
    dump_json(ROOT_OUT, data)
    dump_json(DATA_OUT, data)
    write_summary(data)

    # Keep viewer/index in sync if it is a copy
    viewer_index = ROOT / "viewer" / "index.html"
    root_index = ROOT / "index.html"
    if root_index.exists():
        shutil.copy2(root_index, viewer_index)
        print(f"Synced {viewer_index}")

    print("Summary:", json.dumps(data["summary"], indent=2)[:1200])


if __name__ == "__main__":
    main()
