#!/usr/bin/env python3
"""Download / refresh external ontology resources (SEC Non-GAAP C&DIs, FIBO).

Writes:
  ontology/sec_nongaap_cdis.json   (parsed or merged with curated seed)
  vendor/fibo/                     (sparse GitHub archive extract)
  ontology/fibo_metrics_curated.json (always refreshed from curated map + optional scan)

Network required. Safe to re-run. Does not fail the ontology build if offline —
build_ontology.py falls back to committed curated JSON under ontology/.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
VENDOR = ROOT / "vendor"
FIBO_DIR = VENDOR / "fibo"

SEC_CDI_URL = (
    "https://www.sec.gov/rules-regulations/staff-guidance/"
    "corporation-finance-interpretations/non-gaap-financial-measures"
)
# Public GitHub zip of FIBO production-ish branch tip (large). Prefer sparse curated extract.
FIBO_ZIP_URL = "https://github.com/edmcouncil/fibo/archive/refs/tags/master_2026Q1.zip"

USER_AGENT = "us-gaap-ontology-builder/1.0 (educational; local ontology merge)"


def fetch(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class SecCdiParser(HTMLParser):
    """Best-effort extraction of Question/Answer blocks from SEC Non-GAAP C&DI page."""

    def __init__(self) -> None:
        super().__init__()
        self._bits: list[str] = []
        self.text = ""

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self._bits.append(data.strip())

    def close(self) -> None:
        super().close()
        self.text = "\n".join(self._bits)


QUESTION_RE = re.compile(
    r"Question\s+(\d+\.\d+)\s*[:.\s]*(.*?)(?=Answer\s*:)",
    re.IGNORECASE | re.DOTALL,
)
ANSWER_RE = re.compile(
    r"Answer\s*:\s*(.*?)(?=Question\s+\d+\.\d+|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def parse_sec_cdis(html: str) -> list[dict]:
    parser = SecCdiParser()
    parser.feed(html)
    parser.close()
    text = parser.text
    # Fallback: strip tags crudely if parser missed structure
    if "Question" not in text:
        text = re.sub(r"<[^>]+>", "\n", html)

    questions = list(QUESTION_RE.finditer(text))
    answers = list(ANSWER_RE.finditer(text))
    by_id: dict[str, dict] = {}

    for q in questions:
        qid = q.group(1).strip()
        title = re.sub(r"\s+", " ", q.group(2)).strip()[:240]
        by_id[qid] = {
            "id": f"cdi:{qid}",
            "questionId": qid,
            "title": title or f"Non-GAAP C&DI Question {qid}",
            "question": re.sub(r"\s+", " ", q.group(0)).strip()[:2000],
            "answer": "",
            "tags": guess_tags(title + " " + q.group(0)),
            "sourceUrl": SEC_CDI_URL,
            "layer": "rule",
        }

    # Pair answers in order when regex groups align poorly
    for i, a in enumerate(answers):
        ans = re.sub(r"\s+", " ", a.group(1)).strip()[:4000]
        # Prefer matching nearby question id from preceding text
        preceding = text[max(0, a.start() - 200) : a.start()]
        m = re.search(r"Question\s+(\d+\.\d+)", preceding, re.I)
        if m and m.group(1) in by_id:
            by_id[m.group(1)]["answer"] = ans
        elif i < len(questions):
            qid = questions[i].group(1)
            if qid in by_id and not by_id[qid]["answer"]:
                by_id[qid]["answer"] = ans

    return sorted(by_id.values(), key=lambda x: [int(p) for p in x["questionId"].split(".")])


def guess_tags(blob: str) -> list[str]:
    b = blob.lower()
    tags = []
    for tag, keys in [
        ("reconciliation", ["reconcil"]),
        ("liquidity", ["liquidity", "cash flow", "free cash"]),
        ("per-share", ["per share", "per-share"]),
        ("ebitda", ["ebitda", "ebit"]),
        ("prominence", ["prominen"]),
        ("adjustment", ["adjust", "non-recurring", "one-time"]),
        ("definition", ["what is a non-gaap", "definition"]),
    ]:
        if any(k in b for k in keys):
            tags.append(tag)
    return tags or ["general"]


CURATED_CDIS = [
    {
        "id": "cdi:100.01",
        "questionId": "100.01",
        "title": "Misleading non-GAAP adjustments (Reg G Rule 100(b))",
        "question": "Can certain adjustments cause a non-GAAP measure to be misleading?",
        "answer": (
            "Yes. Certain adjustments may violate Rule 100(b) of Regulation G because they "
            "cause the presentation of the non-GAAP measure to be misleading. Whether an "
            "adjustment is misleading depends on facts and circumstances."
        ),
        "tags": ["adjustment", "definition"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": [
            "nongaap:AdjustedEBITDA",
            "nongaap:NonRecurringAdjustmentsPlaceholder",
            "nongaap:ARR",
            "nongaap:NetRevenueRetention",
        ],
    },
    {
        "id": "cdi:102.05",
        "questionId": "102.05",
        "title": "Non-GAAP per-share measures and liquidity",
        "question": (
            "May non-GAAP performance measures be presented on a per-share basis? What about "
            "liquidity measures?"
        ),
        "answer": (
            "Non-GAAP per-share performance measures should be reconciled to GAAP EPS. "
            "Non-GAAP liquidity measures that measure cash generated must not be presented "
            "on a per-share basis. Substance controls over management's label."
        ),
        "tags": ["liquidity", "per-share", "reconciliation"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": [
            "nongaap:FreeCashFlow",
            "nongaap:FreeCashFlowAltInvesting",
            "nongaap:CashBurn",
            "nongaap:CashBurnCapEx",
            "nongaap:WorkingCapital",
            "nongaap:NetDebt",
        ],
    },
    {
        "id": "cdi:102.07",
        "questionId": "102.07",
        "title": "Free cash flow",
        "question": (
            "Some companies present free cash flow as operating cash flow less capital "
            "expenditures. Is this prohibited?"
        ),
        "answer": (
            "No. Deducting CapEx from GAAP operating cash flow does not violate Item "
            "10(e)(1)(ii). Companies must clearly describe the calculation, reconcile to "
            "GAAP, avoid implying residual discretionary cash, and must not present FCF "
            "on a per-share basis."
        ),
        "tags": ["liquidity", "reconciliation"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": [
            "nongaap:FreeCashFlow",
            "nongaap:FreeCashFlowAltInvesting",
            "nongaap:CashBurn",
            "nongaap:CashBurnCapEx",
        ],
    },
    {
        "id": "cdi:102.09",
        "questionId": "102.09",
        "title": "EBIT / EBITDA and Adjusted EBITDA covenants",
        "question": (
            "May a company disclose Adjusted EBITDA used in a material credit-agreement "
            "covenant even if it excludes cash charges?"
        ),
        "answer": (
            "Item 10(e) generally prohibits excluding cash-settled charges from non-GAAP "
            "liquidity measures other than EBIT/EBITDA. Where a credit-agreement covenant "
            "is material to liquidity, disclosure of the covenant measure may still be "
            "required in MD&A with clear reconciliation and context."
        ),
        "tags": ["ebitda", "liquidity", "reconciliation"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": [
            "nongaap:EBITDA",
            "nongaap:AdjustedEBITDA",
            "nongaap:NetIncomeToEBITDABridge",
        ],
    },
    {
        "id": "cdi:102.03",
        "questionId": "102.03",
        "title": "Non-recurring / infrequent / unusual labels",
        "question": (
            "How does the prohibition on adjusting for non-recurring items work when "
            "labeling charges or gains?"
        ),
        "answer": (
            "It is not appropriate to state that a charge or gain is non-recurring, "
            "infrequent, or unusual unless it meets specified criteria. Registrants may "
            "still adjust for items they believe appropriate, subject to Regulation G and "
            "Item 10(e)."
        ),
        "tags": ["adjustment", "reconciliation"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": ["nongaap:AdjustedEBITDA", "nongaap:NonRecurringAdjustmentsPlaceholder"],
    },
    {
        "id": "cdi:102.10",
        "questionId": "102.10",
        "title": "Equal or greater prominence of GAAP measures",
        "question": (
            "What presentations cause a non-GAAP measure to be more prominent than the "
            "comparable GAAP measure?"
        ),
        "answer": (
            "Examples include presenting a full non-GAAP income statement, omitting "
            "comparable GAAP figures or presenting them less prominently, starting "
            "reconciliations with non-GAAP measures, and similar prominence failures. "
            "GAAP must be presented with equal or greater prominence."
        ),
        "tags": ["prominence", "reconciliation"],
        "sourceUrl": SEC_CDI_URL,
        "layer": "rule",
        "governs": [
            "nongaap:EBITDA",
            "nongaap:AdjustedEBITDA",
            "nongaap:FreeCashFlow",
            "nongaap:ARR",
            "nongaap:NetRevenueRetention",
            "nongaap:NetIncomeToEBITDABridge",
        ],
    },
]


CURATED_FIBO = [
    {
        "id": "fibo:EBITDA",
        "label": "EBITDA",
        "definition": "Earnings before interest, taxes, depreciation and amortization (FIBO-aligned management metric).",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FBC/FinancialInstruments/FinancialInstruments/",
        "alignsTo": ["nongaap:EBITDA", "OperatingIncomeLoss", "DepreciationDepletionAndAmortization"],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:FreeCashFlow",
        "label": "Free Cash Flow",
        "definition": "Cash available after capital expenditures; aligned to operating cash flow minus CapEx.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FBC/FinancialInstruments/FinancialInstruments/",
        "alignsTo": [
            "nongaap:FreeCashFlow",
            "NetCashProvidedByUsedInOperatingActivities",
            "PaymentsToAcquirePropertyPlantAndEquipment",
        ],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:WorkingCapital",
        "label": "Working Capital",
        "definition": "Current assets minus current liabilities.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/",
        "alignsTo": ["nongaap:WorkingCapital", "AssetsCurrent", "LiabilitiesCurrent"],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:NetDebt",
        "label": "Net Debt",
        "definition": "Interest-bearing obligations net of cash and cash equivalents.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FBC/DebtAndEquities/Debt/",
        "alignsTo": [
            "nongaap:NetDebt",
            "LongTermDebtAndCapitalLeaseObligations",
            "CashAndCashEquivalentsAtCarryingValue",
        ],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:GrossMargin",
        "label": "Gross Margin",
        "definition": "Gross profit relative to revenue.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/",
        "alignsTo": ["nongaap:GrossMargin", "GrossProfit", "RevenueFromContractWithCustomerExcludingAssessedTax"],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:CashFlowFromOperations",
        "label": "Cash Flow from Operations",
        "definition": "FIBO-aligned operating cash flow concept mapped to US GAAP operating activities net cash.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/",
        "alignsTo": ["NetCashProvidedByUsedInOperatingActivities"],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:OperatingIncome",
        "label": "Operating Income",
        "definition": "FIBO-aligned operating income mapped to us-gaap OperatingIncomeLoss.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/",
        "alignsTo": ["OperatingIncomeLoss"],
        "layer": "fibo",
        "mapped": True,
    },
    {
        "id": "fibo:Revenue",
        "label": "Revenue",
        "definition": "FIBO-aligned revenue concept mapped to primary US GAAP revenue tags.",
        "fiboIri": "https://spec.edmcouncil.org/fibo/ontology/FND/Accounting/CurrencyAmount/",
        "alignsTo": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
        "layer": "fibo",
        "mapped": True,
    },
]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def refresh_cdis(try_network: bool = True) -> None:
    curated_by_id = {c["id"]: c for c in CURATED_CDIS}
    fetched: list[dict] = []
    if try_network:
        try:
            print(f"Fetching SEC C&DIs: {SEC_CDI_URL}")
            html = fetch(SEC_CDI_URL).decode("utf-8", errors="replace")
            fetched = parse_sec_cdis(html)
            print(f"  parsed {len(fetched)} question blocks")
        except Exception as exc:  # noqa: BLE001
            print(f"  network/parse failed ({exc}); using curated seed only")

    merged: dict[str, dict] = {}
    for item in fetched:
        merged[item["id"]] = item
    for cid, item in curated_by_id.items():
        if cid in merged:
            # Preserve curated governs/tags while keeping fresher answer text when present
            base = merged[cid]
            base["governs"] = item.get("governs", [])
            base["tags"] = sorted(set(base.get("tags", []) + item.get("tags", [])))
            if not base.get("answer"):
                base["answer"] = item["answer"]
            if len(item.get("title", "")) > len(base.get("title", "")):
                base["title"] = item["title"]
        else:
            merged[cid] = item

    payload = {
        "meta": {
            "source": SEC_CDI_URL,
            "notes": (
                "SEC staff C&DIs on Non-GAAP Financial Measures. For agent guidance only; "
                "not legal advice. Curated governs[] edges link rules to nongaap metrics."
            ),
        },
        "rules": sorted(merged.values(), key=lambda x: x.get("questionId", x["id"])),
    }
    write_json(ONTOLOGY / "sec_nongaap_cdis.json", payload)


def refresh_fibo(try_network: bool = True) -> None:
    write_json(
        ONTOLOGY / "fibo_metrics_curated.json",
        {
            "meta": {
                "source": "https://github.com/edmcouncil/fibo",
                "notes": (
                    "Curated FIBO-aligned financial metric stubs mapped to US GAAP / non-GAAP "
                    "nodes. Full FIBO OWL is not imported; optional vendor/fibo extract is for "
                    "reference only."
                ),
            },
            "concepts": CURATED_FIBO,
        },
    )

    if not try_network:
        return
    try:
        print(f"Fetching FIBO zip (may be large): {FIBO_ZIP_URL}")
        raw = fetch(FIBO_ZIP_URL, timeout=300)
        FIBO_DIR.mkdir(parents=True, exist_ok=True)
        # Extract only FND/Accounting and FBC paths to keep vendor slim
        keep_parts = ("/FND/Accounting/", "/FBC/", "/README")
        with zipfile.ZipFile(BytesIO(raw)) as zf:
            names = zf.namelist()
            kept = 0
            for name in names:
                if any(p in name.replace("\\", "/") for p in keep_parts) and not name.endswith("/"):
                    # Flatten into vendor/fibo/...
                    parts = Path(name).parts
                    # drop top-level fibo-xxx/ folder
                    rel = Path(*parts[1:]) if len(parts) > 1 else Path(parts[-1])
                    target = FIBO_DIR / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zf.read(name))
                    kept += 1
            print(f"  extracted {kept} files into {FIBO_DIR}")
            (FIBO_DIR / "SOURCE.txt").write_text(
                f"Extracted from {FIBO_ZIP_URL}\nkept paths: {keep_parts}\n",
                encoding="utf-8",
            )
    except Exception as exc:  # noqa: BLE001
        print(f"  FIBO download/extract skipped ({exc})")


def main() -> int:
    try_network = "--offline" not in sys.argv
    ONTOLOGY.mkdir(parents=True, exist_ok=True)
    refresh_cdis(try_network=try_network)
    refresh_fibo(try_network=try_network)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
