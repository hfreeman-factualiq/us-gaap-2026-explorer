# US GAAP 2026 Concept Explorer

A simple [Streamlit](https://streamlit.io) app for exploring the US GAAP 2026 taxonomy: how concepts are **grouped**, what they are **built from**, and which other concepts **depend on them**.

## Features

- **Relationships** — inspect built-from parts, used-by dependents, type hierarchy, and traits
- **Visual tree** — interactive graph; click nodes to expand and follow connections
- **Type browser** — walk the class–subclass hierarchy (Assets, Liabilities, …)

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data

`data/taxonomy-data.json` is a compact extract of the FASB US GAAP 2026 taxonomy (elements, labels, metamodel relationships, and calculation linkbases).

## Deploy

**GitHub:** https://github.com/hfreeman-factualiq/us-gaap-2026-explorer

**Streamlit Cloud (one-click):**  
https://share.streamlit.io/deploy?repository=hfreeman-factualiq/us-gaap-2026-explorer&branch=master&mainModule=app.py

Sign in with GitHub, confirm `app.py` as the main file, then Deploy.
