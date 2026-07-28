# Financial Ontology 2026 (US GAAP + Non-GAAP Bridge)

Unified machine-readable ontology and interactive explorer for the FASB **US GAAP 2026** taxonomy, extended with:

- Statement **presentation** trees (balance sheet, income, cash flows, equity)
- XBRL **calculation** formulas
- FASB **class–subclass** ontology
- Curated **Non-GAAP** metrics (FCF, Cash Burn, EBITDA, Working Capital, SaaS KPIs, …) with GAAP tag inputs
- **SEC Non-GAAP C&DI** rule nodes
- Curated **FIBO** alignments
- **Discovery catalogs** from `edgartools`, `edgar_analytics`, and Finnhub (ontology expansion / gap-finding only)

This project does **not** run a live EDGAR calculation engine. The discovery libraries are harvested for their concept maps, synonym→GAAP bridges, and metric catalogs so you can explore unused/missing relationships.

## Live site

https://hfreeman-factualiq.github.io/us-gaap-2026-explorer/

Use the **Tree** dropdown to switch between the full v1.2 ontology and each company’s pruned tree (Orijin, Climb Credit, Mantra Health, Brains and Motion). Company trees include LLM-mapped GAAP concepts plus gap-added company-specific line items.

## Run the explorer locally

From the repo root:

```bash
python -m http.server 8877 --bind 127.0.0.1
```

Open http://127.0.0.1:8877

## Rebuild company trees

Requires `claudekey.txt` (or `ANTHROPIC_API_KEY`) and local financial statement packs under `Financial Statements/` (not published).

```bash
pip install -r requirements.txt
python build_company_trees.py --refresh-llm
```

## Browse modes

| Mode | Tree edges |
|------|------------|
| **Tree** (default) | Analyst-aligned curated forest (`tc`) |
| **Formulas** | Calculation children (`cc`) with weights |
| **Class** | FASB class–subclass (`sc`) |
| **Used by** | Calculation parents (`cp`) |
| **Metrics** | Deduplicated metrics & ratios |
| **Reference** | FIBO, library maps, coverage gaps |

### Analyst forest roots

1. **Balance Sheet** — Assets / Liabilities / Equity (classified presentation; axes & tables skipped)
2. **Income Statement** — top-down calc rollup (Revenue → … → Net Income / EPS)
3. **Cash Flow Statement** — Operating / Investing / Financing
4. **Metrics & Ratios** — deduplicated Non-GAAP + analytics (FCF, margins, ROE, scores, …)
5. **Regulatory Guidance** — SEC Non-GAAP C&DIs
6. **Reference Sources** — FIBO, edgartools/edgar_analytics/Finnhub catalogs, gaps, class ontology

Raw XBRL presentation/calculation arcs remain on each node for detail panes; the browse tree uses curated `tc` children.

## Discovery outputs

| Path | Role |
|------|------|
| `ontology/discovery/edgar_analytics.json` | Synonym→GAAP maps + derived metrics |
| `ontology/discovery/edgartools.json` | ~95 standard concepts → XBRL tags |
| `ontology/discovery/finnhub.json` | Finnhub `/stock/metric` key catalog |
| `ontology/discovery/gaps.json` | Missing tags/metrics + required relationship types |
| `ontology/discovery_catalog.json` | Flattened catalog merged into the explorer |

## Source files

| Path | Role |
|------|------|
| `us-gaap-2026/` | Local FASB taxonomy package |
| `ontology/nongaap_metrics.yaml` | Non-GAAP formula catalog (source of truth) |
| `ontology/sec_nongaap_cdis.json` | SEC C&DI rules |
| `ontology/fibo_metrics_curated.json` | Curated FIBO ↔ GAAP/Non-GAAP map |
| `build_viewer_data.py` | GAAP parse |
| `build_ontology.py` | Merge layers into unified JSON |
| `scripts/fetch_external_resources.py` | SEC C&DIs / FIBO refresh |
| `scripts/harvest_discovery_sources.py` | Library catalog harvest + gap analysis |

## Live site

https://hfreeman-factualiq.github.io/us-gaap-2026-explorer/
