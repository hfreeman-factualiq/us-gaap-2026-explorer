#!/usr/bin/env python3
"""v1.3 / v1.31 — v1.2 collapsed extensible core plus the formalized-standards scrape surface.

Adds two roots on top of v1.2 without touching the canonical BS/IS/CF chain:

  Signal Domains        underwriting/monitoring domains → signals → the GAAP,
                        non-GAAP and external-standard classes that formalize each one
  Standards & Sources   every ontology / taxonomy / schema we scrape concepts from,
                        bucketed by how far it is integrated, with its scrape targets

Both are driven by ontology/external_standards.yaml via
scripts/harvest_external_standards.py, so growing the scrape surface is a registry
edit rather than a code change. v1.31 expands the registry with strategy, decision,
value-stream, supply-chain, capability, eng-health, risk, governance, service-delivery
and ESG-materiality domains.
"""

from __future__ import annotations

from prune_core_v11 import ensure_core_node, link
from prune_core_v12 import ROOT_META as V12_ROOT_META, apply_core_v12

FOREST_ORDER = [
    "root:BalanceSheet",
    "root:IncomeStatement",
    "root:CashFlowStatement",
    "root:Metrics",
    "root:Signals",
    "root:Standards",
    "root:Guidance",
    "root:Reference",
]

ROOT_META = {
    **V12_ROOT_META,
    "root:Signals": {
        "l": "Signal Domains",
        "d": (
            "Underwriting signals by domain, each bound to the formalized ontology, "
            "taxonomy or schema that already defines it."
        ),
    },
    "root:Standards": {
        "l": "Standards & Scrape Sources",
        "d": (
            "Registry of formalized ontologies / taxonomies / schemas to scrape for "
            "concepts, with integration status and per-source scrape targets."
        ),
    },
}

NET_SIGNAL = "Signal"
NET_STANDARD = "Standard"

INTEGRATION_BUCKETS = [
    (
        "full",
        "Integrated — parsed into the tree",
        "Sources whose concepts already exist as nodes in this ontology.",
    ),
    (
        "partial",
        "Partially integrated — curated subset",
        "Sources with a curated subset merged; remaining modules are still to be scraped.",
    ),
    (
        "registered",
        "Registered — to scrape",
        "Sources declared as scrape targets; key classes are curated stubs until harvested.",
    ),
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


def _set_children(concepts: dict, node_id: str, kids: list[dict]) -> None:
    node = concepts[node_id]
    node["tc"] = kids
    node["pc"] = kids
    node["sc"] = [k["c"] for k in kids]


def _by_kind(concepts: dict, kind: str) -> list[dict]:
    return [c for c in concepts.values() if c.get("stdKind") == kind]


def build_v13_signals(concepts: dict) -> list[dict]:
    """Signal Domains root: domain → signal → mapped GAAP / non-GAAP / standard class."""
    domains = sorted(_by_kind(concepts, "signalDomain"), key=lambda c: (c.get("order") or 0, c["n"]))
    links: list[dict] = []

    for i, dom in enumerate(domains):
        dom_kids: list[dict] = []
        order = 10
        for sig_id in dom.get("signals") or []:
            sig = concepts.get(sig_id)
            if not sig:
                continue
            sig_kids: list[dict] = []
            for target in sig.get("mapsTo") or []:
                if target in concepts:
                    sig_kids.append(link(target, (len(sig_kids) + 1) * 10, "MapsTo"))
            for cls in sig.get("standardClasses") or []:
                if cls in concepts:
                    sig_kids.append(link(cls, (len(sig_kids) + 1) * 10, "FormalizedBy"))
            _set_children(concepts, sig_id, sig_kids)
            sig["coreTier"] = "core"
            dom_kids.append(link(sig_id, order, NET_SIGNAL))
            order += 10

        for j, std_id in enumerate(dom.get("primaryStandards") or []):
            if std_id in concepts:
                dom_kids.append(link(std_id, 500 + j * 10, "PrimaryStandard"))

        _set_children(concepts, dom["n"], dom_kids)
        dom["coreTier"] = "core"
        dom["extensible"] = True
        links.append(link(dom["n"], (i + 1) * 10, NET_SIGNAL))

    ensure_core_node(
        concepts,
        "core:v13:signal_extensions",
        "Signal Domains — Extensions",
        (
            "Attach project-specific signals here, or add a domain to "
            "ontology/external_standards.yaml and re-harvest."
        ),
        [],
        layer="standard",
    )
    concepts["core:v13:signal_extensions"]["extensionPoint"] = True
    concepts["core:v13:signal_extensions"]["extensible"] = True
    links.append(link("core:v13:signal_extensions", 900, "ExtensionPoint"))
    return links


def build_v13_standards(concepts: dict) -> list[dict]:
    """Standards root: integration bucket → standard → key classes + scrape targets."""
    standards = sorted(_by_kind(concepts, "standard"), key=lambda c: (c.get("l") or c["n"]))
    links: list[dict] = []

    for std in standards:
        sid = std["n"]
        kids: list[dict] = []
        for cls in std.get("keyClasses") or []:
            if cls in concepts:
                concepts[cls]["coreTier"] = "extension"
                kids.append(link(cls, (len(kids) + 1) * 10, "KeyClass"))

        targets = [t for t in (std.get("scrapeTargets") or []) if t in concepts]
        if targets:
            folder = f"{sid}:sources"
            ensure_core_node(
                concepts,
                folder,
                "Scrape Targets",
                f"Artifacts to harvest concepts from for {std.get('l') or sid}.",
                [link(t, (j + 1) * 10, "ScrapeTarget") for j, t in enumerate(targets)],
                layer="standard",
            )
            concepts[folder]["stdKind"] = "scrapeFolder"
            concepts[folder]["k"] = "scrape"
            for t in targets:
                concepts[t]["coreTier"] = "extension"
            kids.append(link(folder, 900, "ScrapeTarget"))

        _set_children(concepts, sid, kids)
        std["coreTier"] = "core"
        std["extensible"] = True

    for i, (bucket, label, description) in enumerate(INTEGRATION_BUCKETS):
        ids = [s["n"] for s in standards if (s.get("integration") or "registered") == bucket]
        if not ids:
            continue
        bid = f"core:v13:standards:{bucket}"
        ensure_core_node(
            concepts,
            bid,
            label,
            description,
            [link(x, (j + 1) * 10, NET_STANDARD) for j, x in enumerate(ids)],
            layer="standard",
        )
        concepts[bid]["extensible"] = True
        links.append(link(bid, (i + 1) * 10, NET_STANDARD))

    ensure_core_node(
        concepts,
        "core:v13:standards_extensions",
        "Standards — Extensions",
        (
            "Register another ontology/taxonomy/schema in "
            "ontology/external_standards.yaml, then run "
            "scripts/harvest_external_standards.py."
        ),
        [],
        layer="standard",
    )
    concepts["core:v13:standards_extensions"]["extensionPoint"] = True
    concepts["core:v13:standards_extensions"]["extensible"] = True
    links.append(link("core:v13:standards_extensions", 900, "ExtensionPoint"))
    return links


def apply_core_v13(concepts: dict) -> dict:
    """Build the v1.3 forest: v1.2 core + Signal Domains + Standards & Scrape Sources."""
    base = apply_core_v12(concepts)

    concepts["root:Signals"] = _make_root("root:Signals", build_v13_signals(concepts))
    concepts["root:Standards"] = _make_root("root:Standards", build_v13_standards(concepts))

    # Surface the new hooks in the extension guide written by v1.2.
    guide = concepts.get("core:v12:how_to_extend")
    if guide:
        extra = [
            h
            for h in ["core:v13:signal_extensions", "core:v13:standards_extensions"]
            if h in concepts
        ]
        kids = list(guide.get("tc") or [])
        start = len(kids)
        kids += [link(h, (start + i + 1) * 10) for i, h in enumerate(extra)]
        _set_children(concepts, "core:v12:how_to_extend", kids)

    # Re-anchor the reference root so the standards registry is discoverable there too.
    ref = concepts.get("root:Reference") or {}
    ref_kids = list(ref.get("tc") or ref.get("pc") or [])
    if "root:Standards" not in {k["c"] for k in ref_kids}:
        ref_kids.append(link("root:Standards", 110, "Reference"))
    concepts["root:Reference"] = _make_root("root:Reference", ref_kids)

    core_n = sum(1 for c in concepts.values() if c.get("coreTier") == "core")
    ext_n = sum(1 for c in concepts.values() if c.get("coreTier") == "extension")
    hooks = sum(1 for c in concepts.values() if c.get("extensionPoint"))

    return {
        **base,
        "versionTag": "1.31",
        "coreTierCore": core_n,
        "coreTierExtension": ext_n,
        "extensionPoints": hooks,
        "signalDomains": len(_by_kind(concepts, "signalDomain")),
        "signals": len(_by_kind(concepts, "signal")),
        "standards": len(_by_kind(concepts, "standard")),
        "standardClasses": len(_by_kind(concepts, "standardClass")),
        "scrapeTargets": len(_by_kind(concepts, "scrapeTarget")),
    }
