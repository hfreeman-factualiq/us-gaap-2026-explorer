#!/usr/bin/env python3
"""Save financial_ontology_2026_v1.1 snapshot from current taxonomy-data.json."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = json.loads((ROOT / "taxonomy-data.json").read_text(encoding="utf-8"))
dst = ROOT / "financial_ontology_2026_v1.1"
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
]:
    p = ROOT / "ontology" / f
    if p.exists():
        shutil.copy2(p, dst / f)

manifest = {
    "id": "financial_ontology_2026_v1.1",
    "version": "1.1",
    "taxonomy": "US GAAP 2026 + Non-GAAP bridge (industry-agnostic core)",
    "purpose": (
        "Base tree generalizable across industries/domains; "
        "prune/grow per project from Reference & Extensions."
    ),
    "prunedForest": True,
    "coreGeneralizable": True,
    "ontologyRoots": src.get("ontologyRoots"),
    "summary": {
        k: src.get("summary", {}).get(k)
        for k in [
            "totalConcepts",
            "forestRoots",
            "coreTierCore",
            "coreTierExtension",
            "industrySpecializedParked",
            "nongaapMetrics",
            "secRules",
            "discoveryNodes",
        ]
    },
    "design": {
        "balanceSheet": "Assets / Liabilities / Equity with universal current & noncurrent line items",
        "incomeStatement": "Revenue to EPS rollup; major parents shallow (formulas in detail/Formulas mode)",
        "cashFlow": "Operating / Investing / CapEx / Financing / Net change",
        "metrics": "Cross-industry ratios only; SaaS/scoring/valuation parked in Reference",
        "reference": "Industry & specialized US GAAP + library maps + gaps for project extension",
    },
    "files": {"tree": "ontology.json", "taxonomyData": "taxonomy-data.json"},
    "previous": "financial_ontology_2026_v1.0",
}
(dst / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

readme = f"""# Financial Ontology 2026 — v1.1

Industry-agnostic **core** financial ontology tree.

Use this as the base: prune unused branches and grow industry/project-specific nodes from **Reference & Extensions**.

## Forest roots

1. Balance Sheet
2. Income Statement
3. Cash Flow Statement
4. Core Metrics & Ratios
5. Regulatory Guidance
6. Reference & Extensions

## Files

- `ontology.json` — full graph object (browse via `ontologyRoots` + concept `tc` children)
- `manifest.json` — version metadata

- Concepts: {manifest['summary'].get('totalConcepts')}
- Core-tier nodes: {manifest['summary'].get('coreTierCore')}
- Extension-tier nodes: {manifest['summary'].get('coreTierExtension')}
- Industry/specialized parked: {manifest['summary'].get('industrySpecializedParked')}
"""
(dst / "README.md").write_text(readme, encoding="utf-8")
print("saved", dst)
print(json.dumps(manifest["summary"], indent=2))
print("size_mb", round((dst / "ontology.json").stat().st_size / (1024 * 1024), 1))
