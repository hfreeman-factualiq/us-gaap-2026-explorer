#!/usr/bin/env python3
"""Save financial_ontology_2026_v1.3 snapshot."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = json.loads((ROOT / "taxonomy-data.json").read_text(encoding="utf-8"))
dst = ROOT / "financial_ontology_2026_v1.3"
dst.mkdir(exist_ok=True)

(dst / "ontology.json").write_text(
    json.dumps(src, ensure_ascii=False, separators=(",", ":")),
    encoding="utf-8",
)
shutil.copy2(ROOT / "taxonomy-data.json", dst / "taxonomy-data.json")

for f in [
    "summary.md",
    "discovery_catalog.json",
    "nongaap_metrics.yaml",
    "sec_nongaap_cdis.json",
    "fibo_metrics_curated.json",
    "external_standards.yaml",
    "external_standards_catalog.json",
]:
    p = ROOT / "ontology" / f
    if p.exists():
        shutil.copy2(p, dst / f)

probe = ROOT / "ontology" / "standards" / "probe_status.json"
if probe.exists():
    shutil.copy2(probe, dst / "standards_probe_status.json")

s = src.get("summary") or {}
manifest = {
    "id": "financial_ontology_2026_v1.3",
    "version": "1.3",
    "taxonomy": "US GAAP 2026 + Non-GAAP bridge + formalized-standards scrape surface",
    "purpose": (
        "Base template tree. v1.2 collapsed extensible core plus a signal-domain map "
        "and a registry of formalized ontologies/taxonomies/schemas to scrape for "
        "concepts, so every underwriting signal names the standard that defines it."
    ),
    "prunedForest": True,
    "coreGeneralizable": True,
    "coreCollapsed": True,
    "standardsRegistry": True,
    "ontologyRoots": src.get("ontologyRoots"),
    "summary": {
        k: s.get(k)
        for k in [
            "totalConcepts",
            "forestRoots",
            "coreTierCore",
            "coreTierExtension",
            "industrySpecializedParked",
            "extensionPoints",
            "nongaapMetrics",
            "secRules",
            "discoveryNodes",
            "signalDomains",
            "signals",
            "standards",
            "standardClasses",
            "scrapeTargets",
            "scrapeTargetsReachable",
        ]
    },
    "design": {
        "balanceSheet": "Assets | Liabilities | Equity + extension hooks",
        "incomeStatement": "Revenue → Gross Profit → Operating Income → Pretax → NI → EPS; components collapsed",
        "cashFlow": "Operating | Investing(+CapEx) | Financing | Net Change + extension hook",
        "metrics": "5 buckets (Profitability, Liquidity, Leverage, Cash Generation, Returns)",
        "signals": "10 signal domains → signals → mapped GAAP/non-GAAP + formalizing standard classes",
        "standards": "Integration buckets (full | partial | registered) → standard → key classes + scrape targets",
        "extensionModel": "Attach under '— Extensions' hooks; promote from Industry & Specialized as needed",
        "registry": "ontology/external_standards.yaml is the source of truth for signals and scrape sources",
    },
    "files": {
        "tree": "ontology.json",
        "taxonomyData": "taxonomy-data.json",
        "standardsRegistry": "external_standards.yaml",
        "standardsCatalog": "external_standards_catalog.json",
        "scrapeProbeStatus": "standards_probe_status.json",
    },
    "previous": "financial_ontology_2026_v1.2",
}
(dst / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

m = manifest["summary"]
readme = f"""# Financial Ontology 2026 — v1.3

The v1.2 collapsed extensible core, plus an explicit **signal → standard** map and a
**registry of formalized ontologies / taxonomies / schemas to scrape for concepts**.

## What v1.3 adds over v1.2

- **Signal Domains** root — {m.get('signalDomains')} domains, {m.get('signals')} signals.
  Every signal (`rev`, `cac`, `runway`, `equity_events`, `attrition`, `rf_versions`,
  `cost_per_outcome`, …) links to the GAAP tags, non-GAAP metrics and external standard
  classes that formalize it.
- **Standards & Scrape Sources** root — {m.get('standards')} standards,
  {m.get('standardClasses')} key classes, {m.get('scrapeTargets')} scrape targets
  ({m.get('scrapeTargetsReachable')} reachable at snapshot time), bucketed by integration
  status: parsed in / curated subset / registered to scrape.
- `external_standards.yaml` — the registry that drives both roots. Add a standard or a
  signal there and re-harvest; no tree code changes.

## Registered sources

| Standard | Format | Signal domains |
|---|---|---|
| FASB US GAAP XBRL Taxonomy | XBRL | income statement, cash flow, balance sheet, plan, reporting |
| XBRL Global Ledger (XBRL GL) | XML / XBRL | income statement, plan & forecast, reporting |
| Open-SaaS metrics schema | JSON Schema | unit economics, commercial |
| ACTUS | JSON / OWL | cash flow & runway, balance sheet |
| Open Cap Format (OCF) | JSON Schema | balance sheet (equity events) |
| APQC PCF | XML / XLSX | commercial & pipeline, team |
| Schema.org (Action / Offer) | JSON-LD | commercial, external events |
| W3C Organization Ontology (ORG) | OWL / RDF | team & headcount |
| ISO 30414 | Metric spec | team & headcount |
| FIBO | OWL / RDF | unit economics, balance sheet, external events, reporting |
| Financial Regulation Ontology (FRO) | OWL / RDF | external events, reporting |
| ArchiMate business metamodel | XML / XSD | external events |
| SEC EDGAR Inline XBRL | iXBRL / JSON | reporting & narrative |
| IRIS+ (GIIN) | JSON / XML | impact & outcomes |
| IMP five dimensions | RDF / JSON | impact & outcomes |

## Forest

1. Balance Sheet — Assets | Liabilities | Equity
2. Income Statement — Revenue → … → EPS (+ collapsed P&L Components)
3. Cash Flow Statement — Operating | Investing | Financing | Net Change
4. Core Metrics — 5 universal buckets
5. **Signal Domains** — 10 domains → signals → formalizing standards
6. **Standards & Scrape Sources** — registry + scrape targets
7. Regulatory Guidance — principle C&DIs
8. Reference & Extensions — grow/prune surface

## How to use on a project

1. Keep the eight core roots as-is
2. Attach domain lines under each **Extensions** hook
3. Promote only needed specialized GAAP from **Industry & Specialized**
4. Add domain KPIs under **Metrics — Extensions**
5. Register new scrape sources in `external_standards.yaml`, not in tree code
6. Do not fork the core earnings / BS / CF chain

## Stats

- Concepts: {m.get('totalConcepts')}
- Core-tier: {m.get('coreTierCore')}
- Extension-tier: {m.get('coreTierExtension')}
- Extension points: {m.get('extensionPoints')}
- Specialized parked: {m.get('industrySpecializedParked')}
"""
(dst / "README.md").write_text(readme, encoding="utf-8")
print("saved", dst)
print(json.dumps(manifest["summary"], indent=2))
print("size_mb", round((dst / "ontology.json").stat().st_size / (1024 * 1024), 1))
