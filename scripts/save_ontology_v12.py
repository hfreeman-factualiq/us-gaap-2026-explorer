#!/usr/bin/env python3
"""Save financial_ontology_2026_v1.2 snapshot."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
src = json.loads((ROOT / "taxonomy-data.json").read_text(encoding="utf-8"))
dst = ROOT / "financial_ontology_2026_v1.2"
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

s = src.get("summary") or {}
manifest = {
    "id": "financial_ontology_2026_v1.2",
    "version": "1.2",
    "taxonomy": "US GAAP 2026 + Non-GAAP bridge (collapsed extensible core)",
    "purpose": (
        "Most extensible generalized base model. Short canonical chains with "
        "explicit extension hooks; grow/prune per project without forking the core."
    ),
    "prunedForest": True,
    "coreGeneralizable": True,
    "coreCollapsed": True,
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
        ]
    },
    "design": {
        "balanceSheet": "Assets | Liabilities | Equity + extension hooks",
        "incomeStatement": "Revenue → Gross Profit → Operating Income → Pretax → NI → EPS; components collapsed",
        "cashFlow": "Operating | Investing(+CapEx) | Financing | Net Change + extension hook",
        "metrics": "5 buckets (Profitability, Liquidity, Leverage, Cash Generation, Returns)",
        "extensionModel": "Attach under '— Extensions' hooks; promote from Industry & Specialized as needed",
    },
    "files": {"tree": "ontology.json", "taxonomyData": "taxonomy-data.json"},
    "previous": "financial_ontology_2026_v1.1",
}
(dst / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

readme = f"""# Financial Ontology 2026 — v1.2

Collapsed, **maximally extensible** generalized core.

## How to use on a project

1. Keep the six core roots as-is
2. Attach domain lines under each **Extensions** hook
3. Promote only needed specialized GAAP from **Industry & Specialized**
4. Add domain KPIs under **Metrics — Extensions**
5. Do not fork the core earnings / BS / CF chain

## Forest

1. Balance Sheet — Assets | Liabilities | Equity
2. Income Statement — Revenue → … → EPS (+ collapsed P&L Components)
3. Cash Flow Statement — Operating | Investing | Financing | Net Change
4. Core Metrics — 5 universal buckets
5. Regulatory Guidance — principle C&DIs
6. Reference & Extensions — grow/prune surface

## Stats

- Concepts: {manifest['summary'].get('totalConcepts')}
- Core-tier: {manifest['summary'].get('coreTierCore')}
- Extension-tier: {manifest['summary'].get('coreTierExtension')}
- Extension points: {manifest['summary'].get('extensionPoints')}
- Specialized parked: {manifest['summary'].get('industrySpecializedParked')}
"""
(dst / "README.md").write_text(readme, encoding="utf-8")
print("saved", dst)
print(json.dumps(manifest["summary"], indent=2))
print("size_mb", round((dst / "ontology.json").stat().st_size / (1024 * 1024), 1))
