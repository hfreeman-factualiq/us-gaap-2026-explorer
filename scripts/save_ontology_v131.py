#!/usr/bin/env python3
"""Save financial_ontology_2026_v1.31 snapshot."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = json.loads((ROOT / "taxonomy-data.json").read_text(encoding="utf-8"))
dst = ROOT / "financial_ontology_2026_v1.31"
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
    "id": "financial_ontology_2026_v1.31",
    "version": "1.31",
    "taxonomy": (
        "US GAAP 2026 + Non-GAAP bridge + formalized standards "
        "(financial + strategy/ops/governance)"
    ),
    "purpose": (
        "Base template tree. Extends v1.3 with strategy, decision, value-stream, "
        "supply-chain, capability, eng-health, risk, governance, service-delivery "
        "and ESG-materiality domains, and scrapes machine-readable XSD/XMI artifacts "
        "into standard-class nodes."
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
            "scrapedClasses",
        ]
    },
    "design": {
        "balanceSheet": "Assets | Liabilities | Equity + extension hooks",
        "incomeStatement": "Revenue → Gross Profit → Operating Income → Pretax → NI → EPS; components collapsed",
        "cashFlow": "Operating | Investing(+CapEx) | Financing | Net Change + extension hook",
        "metrics": "5 buckets (Profitability, Liquidity, Leverage, Cash Generation, Returns)",
        "signals": (
            "20 signal domains (financial underwriting + strategy/ops/governance) → "
            "signals → mapped GAAP/non-GAAP + formalizing standard classes"
        ),
        "standards": (
            "Integration buckets (full | partial | registered) → standard → "
            "key classes (curated + scraped) + scrape targets"
        ),
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
    "previous": "financial_ontology_2026_v1.3",
}
(dst / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

m = manifest["summary"]
readme = f"""# Financial Ontology 2026 — v1.31

v1.3 plus **strategy / ops / governance** frameworks and a live scrape of
machine-readable XSD/XMI artifacts into standard-class nodes.

## What v1.31 adds over v1.3

- **10 new standards**: BMM, DMN, VDML, SCOR DS, BIAN, DORA, Open FAIR, COBIT 2019,
  ITIL 4, SASB/ISSB
- **10 new signal domains**: Strategy & Motivation, Decision Logic, Value Streams,
  Supply Chain, Capability Architecture, Eng Health, Risk & Exposure, Enterprise
  Governance, Service Delivery, ESG Materiality
- **Machine-readable scrape**: reachable `.xsd` / `.xmi` / `.json` targets are
  downloaded and class/type names merged as `scraped-class` nodes

## Forest

Same 8 roots as v1.3; Signal Domains now covers **{m.get('signalDomains')}** domains
and **{m.get('signals')}** signals across **{m.get('standards')}** registered standards
(**{m.get('standardClasses')}** classes, **{m.get('scrapedClasses') or 0}** scraped).

## Stats

- Concepts: {m.get('totalConcepts')}
- Core-tier: {m.get('coreTierCore')}
- Extension-tier: {m.get('coreTierExtension')}
- Extension points: {m.get('extensionPoints')}
- Scrape targets reachable: {m.get('scrapeTargetsReachable')} / {m.get('scrapeTargets')}
"""
(dst / "README.md").write_text(readme, encoding="utf-8")
print("saved", dst)
print(json.dumps(manifest["summary"], indent=2))
print("size_mb", round((dst / "ontology.json").stat().st_size / (1024 * 1024), 1))
