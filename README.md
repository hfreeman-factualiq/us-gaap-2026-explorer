# US GAAP 2026 Concept Explorer

Simple HTML explorer for the US GAAP 2026 taxonomy: how concepts are grouped, what they are built from, and what depends on them.

## Run locally

```bash
cd viewer
python -m http.server 8877 --bind 127.0.0.1
```

Open http://127.0.0.1:8877

## How to use

1. The tree starts with the three top concepts: **Assets**, **Liabilities**, **Inventory Adjustments**
2. Click ▸ to expand children (subtypes, formulas, or “used by” — toggle at the top)
3. Select any concept to see relationships on the right
4. Search by label or technical name

## Data

`viewer/taxonomy-data.json` is a compact extract of the FASB US GAAP 2026 taxonomy.
