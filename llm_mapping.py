#!/usr/bin/env python3
"""Map company statement labels → ontology concepts via Claude, plus gap analysis.

Gap analysis: important statement concepts with no existing ontology home are
proposed as new company nodes (parent, formula/relationships) and attached into
that company's tree.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from anthropic import Anthropic
from json_repair import repair_json

ROOT = Path(__file__).resolve().parent
KEY_FILE = ROOT / "claudekey.txt"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

log = logging.getLogger("llm")

# Batches are independent, so they run concurrently. The gate bounds total
# in-flight requests across all companies so we do not trip rate limits.
API_CONCURRENCY = int(os.environ.get("LLM_API_CONCURRENCY", "12"))
BATCH_WORKERS = int(os.environ.get("LLM_BATCH_WORKERS", "6"))
_API_GATE = threading.BoundedSemaphore(API_CONCURRENCY)
_CLIENT_LOCK = threading.Lock()
_CLIENT: Anthropic | None = None


def get_client() -> Anthropic:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = Anthropic(api_key=load_api_key(), max_retries=4)
        return _CLIENT

MAP_SYSTEM = """You map private-company source evidence to ontology concept IDs.

Rules:
- Only use concept IDs from the provided CANDIDATES list.
- Sources include financial statements, board books, and investor memos.
- Candidate layers include US GAAP, Non-GAAP metrics, strategic/operational signals,
  and formal standard classes (BMM, DMN, VDML, SCOR, BIAN, DORA, FAIR, COBIT,
  ITIL, SASB/ISSB, and others).
- Map a label only when it clearly evidences that concept.
- Prefer totals over detail when both exist (e.g. "Total Revenue" → Revenues).
- Product/channel revenue lines (Subscription Revenue, Interest Income, etc.) should usually stay UNMAPPED here — gap analysis will add them as new children. Only map them to Revenues if they are clearly the company's sole revenue total.
- A narrative sentence may map to a strategic or operational signal when it contains
  concrete evidence (a stated goal, decision rule, risk, KPI, incident, control, etc.).
- Do NOT map: company names, dates, decorative headings, bank/GL account codes,
  boilerplate, or generic mentions with no substantive evidence.
- Do NOT map a bank account or GL code to Cash — only map labels like "Cash", "Total Cash", "Cash & Equivalents".
- If unsure, return concept null.
- confidence is 0–1. Only emit a non-null concept when confidence >= 0.75.

Return ONLY a JSON array (no markdown):
{"label":"<exact input label>","concept":"<id or null>","confidence":0.0,"reason":"<short>"}
"""

GAP_SYSTEM = """You perform ontology gap analysis for a company's source documents.

You receive:
- Labels/evidence from financial statements, board books, and investor memos that did
  NOT map to an existing ontology concept
- Concepts already mapped/populated for this company
- Allowed attach parents (existing tree nodes / extension hooks)

Task: propose NEW company-specific concepts for important economic line items that belong in the tree but have no home yet.

Include:
- Material revenue streams, cost pools, opex categories, BS line items, CF lines, KPIs
- Material company-specific strategic objectives, operating capabilities, risks,
  controls, service/engineering health metrics, ESG topics, and outcome measures
- Lines that are children/components of an existing total (e.g. Subscription Revenue under Revenues)

Exclude:
- Noise, dates, company names, individual bank accounts / GL codes
- Generic prose, aspirations without a measurable concept, duplicate evidence
- Lines already covered by a mapped total (don't duplicate "Total Revenue" if Revenues is mapped)
- Tiny misc fluff

For each gap, specify:
- id_slug: short kebab-case id (will become company:{slug}:{id_slug})
- label: display name
- source_label: exact statement label
- statement: is | bs | cf | metrics
- parent: must be an id from ATTACH_PARENTS
- relationship: "component" (rolls into parent via formula weight) | "child" (browse child only) | "metric"
- weight: number for formula component (usually 1 or -1); null if not a component
- definition: one sentence
- formula_expression: optional, e.g. "part of Revenues" or "Subscription + Hardware + Service"
- confidence: 0–1 (only include if >= 0.7)
- reason: short

Return ONLY a JSON array (no markdown). If none, return [].
"""


def load_api_key() -> str:
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    raise FileNotFoundError(
        f"No Anthropic API key. Set ANTHROPIC_API_KEY or create {KEY_FILE.name}"
    )


def build_candidate_list(concepts: dict, is_mappable) -> list[dict]:
    out = []
    for name, c in concepts.items():
        if not is_mappable(name, c):
            continue
        out.append(
            {
                "id": name,
                "label": c.get("l") or name,
                "layer": c.get("layer") or "",
            }
        )
    out.sort(key=lambda x: x["id"])
    return out


def _chunk(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _parse_json_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        raise ValueError(f"No JSON array in model response: {text[:240]}")
    payload = text[start : end + 1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        repaired = repair_json(payload)
        result = json.loads(repaired)
        if not isinstance(result, list):
            raise ValueError("Repaired model response is not a JSON array")
        return result


def _cached_system(*blocks: str) -> list[dict]:
    """System prompt as blocks, with the large trailing block prompt-cached.

    Every batch for a company repeats the same candidate/parent catalog, so
    caching that prefix makes batches after the first far faster and cheaper.
    """
    out = [{"type": "text", "text": b} for b in blocks if b]
    if out:
        out[-1]["cache_control"] = {"type": "ephemeral"}
    return out


def _claude_json_array(
    client: Anthropic,
    *,
    model: str,
    system,
    user: str,
    tag: str = "",
    attempts: int = 4,
) -> list:
    for attempt in range(attempts):
        try:
            with _API_GATE:
                started = time.time()
                msg = client.messages.create(
                    model=model,
                    max_tokens=8192,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
            usage = getattr(msg, "usage", None)
            log.debug(
                "%s api ok in %.1fs (in=%s out=%s cache_read=%s)",
                tag,
                time.time() - started,
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
                getattr(usage, "cache_read_input_tokens", 0),
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
            return _parse_json_array(text)
        except Exception as e:  # noqa: BLE001 - retry transport, rate limit and parse errors alike
            if attempt == attempts - 1:
                log.error("%s giving up after %d attempts: %s", tag, attempts, e)
                return []
            delay = min(30, 2 ** attempt) + random.uniform(0, 1.5)
            log.warning("%s retry %d/%d in %.1fs: %s", tag, attempt + 1, attempts - 1, delay, e)
            time.sleep(delay)
    return []


def _run_batches(batches: list, fn, *, workers: int) -> list:
    """Run fn(index, batch) over all batches, in order-preserving results.

    The first batch runs alone to write the prompt cache; the rest then run
    concurrently against a warm cache.
    """
    results: list = [None] * len(batches)
    if not batches:
        return results
    results[0] = fn(0, batches[0])
    rest = list(range(1, len(batches)))
    if not rest:
        return results
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(rest)))) as pool:
        futures = {pool.submit(fn, i, batches[i]): i for i in rest}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results


def map_labels_with_llm(
    *,
    company_name: str,
    labels_by_statement: dict[str, list[str]],
    candidates: list[dict],
    cache_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    batch_size: int = 35,
    min_confidence: float = 0.75,
    refresh: bool = False,
    workers: int = BATCH_WORKERS,
    progress=None,
) -> tuple[dict[str, str], list[dict]]:
    """Return (concept→example_label, detail rows)."""

    if cache_path and cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("model") == model
            and cached.get("company") == company_name
            and cached.get("stage") == "map"
        ):
            log.info("[%s] map cache hit (%s)", company_name, cache_path.name)
            return cached["mapped"], cached["details"]

    client = get_client()
    cand_block = json.dumps(candidates, ensure_ascii=False)

    work_items: list[dict] = []
    for stmt, labs in labels_by_statement.items():
        for lab in labs:
            work_items.append({"label": lab, "statement": stmt})

    seen = set()
    unique_items = []
    for item in work_items:
        if item["label"] in seen:
            continue
        seen.add(item["label"])
        unique_items.append(item)

    details: list[dict] = []
    mapped: dict[str, str] = {}

    batches = list(_chunk(unique_items, batch_size))
    system = _cached_system(MAP_SYSTEM, f"CANDIDATES ({len(candidates)}):\n{cand_block}")
    log.info(
        "[%s] map: %d labels in %d batches (%s, %d workers)",
        company_name,
        len(unique_items),
        len(batches),
        model,
        workers,
    )
    finished = [0]
    gate = threading.Lock()

    def run_batch(idx: int, batch: list[dict]) -> list:
        rows = _claude_json_array(
            client,
            model=model,
            system=system,
            user=(
                f"Company: {company_name}\n\n"
                f"LABELS TO MAP (batch {idx + 1}; source=is|bs|cf|other|document):\n"
                f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n"
            ),
            tag=f"[{company_name}] map batch {idx + 1}/{len(batches)}",
        )
        with gate:
            finished[0] += 1
            log.info(
                "[%s] map batch %d/%d done (%d complete)",
                company_name,
                idx + 1,
                len(batches),
                finished[0],
            )
            if progress:
                progress("map", finished[0], len(batches))
        return rows

    candidate_ids = {c["id"] for c in candidates}
    for batch, rows in zip(batches, _run_batches(batches, run_batch, workers=workers)):
        by_label = {r.get("label"): r for r in (rows or []) if isinstance(r, dict)}
        for item in batch:
            lab = item["label"]
            row = by_label.get(lab) or {}
            concept = row.get("concept")
            conf = float(row.get("confidence") or 0)
            if concept in ("", "null", "None"):
                concept = None
            if concept and conf >= min_confidence and concept in candidate_ids:
                mapped.setdefault(concept, lab)
                details.append(
                    {
                        "label": lab,
                        "concept": concept,
                        "method": "llm",
                        "score": conf,
                        "reason": row.get("reason") or "",
                        "statement": item["statement"],
                    }
                )
            else:
                details.append(
                    {
                        "label": lab,
                        "concept": None,
                        "method": "llm-unmapped",
                        "score": conf,
                        "reason": row.get("reason") or "",
                        "statement": item["statement"],
                    }
                )

    log.info(
        "[%s] map done: %d concepts from %d labels",
        company_name,
        len(mapped),
        len(unique_items),
    )

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "stage": "map",
                    "company": company_name,
                    "model": model,
                    "mapped": mapped,
                    "details": details,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return mapped, details


def propose_gaps_with_llm(
    *,
    company_name: str,
    company_slug: str,
    unmapped_labels: list[dict],
    mapped_concepts: list[dict],
    attach_parents: list[dict],
    cache_path: Path | None = None,
    model: str = DEFAULT_MODEL,
    batch_size: int = 50,
    min_confidence: float = 0.7,
    refresh: bool = False,
    workers: int = BATCH_WORKERS,
    progress=None,
) -> list[dict]:
    """Propose new company concepts for important unmapped labels."""

    if cache_path and cache_path.exists() and not refresh:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("model") == model
            and cached.get("company") == company_name
            and cached.get("stage") == "gaps"
        ):
            log.info("[%s] gap cache hit (%s)", company_name, cache_path.name)
            return cached["gaps"]

    # Pre-filter obvious noise before spending tokens
    skip_re = re.compile(
        r"^(draft|confidential|amounts in|zero check|forecast|budget|actual|"
        r"q[1-4]|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|"
        r"ytd|fy\s*\d|parameter|remarks|variance|customer:|reporting book|"
        r"as of date|location:|0x[0-9a-f]+)",
        re.I,
    )
    gl_re = re.compile(r"^\d{3,5}\s*[-–]")
    filtered = []
    for row in unmapped_labels:
        lab = (row.get("label") or "").strip()
        if len(lab) < 3 or len(lab) > 100:
            continue
        if skip_re.match(lab) or gl_re.match(lab):
            continue
        filtered.append(row)

    if not filtered:
        return []

    client = get_client()
    parents_block = json.dumps(attach_parents, ensure_ascii=False)
    mapped_block = json.dumps(mapped_concepts, ensure_ascii=False)

    gaps: list[dict] = []
    parent_ids = {p["id"] for p in attach_parents}
    batches = list(_chunk(filtered, batch_size))
    system = _cached_system(
        GAP_SYSTEM,
        f"ALREADY MAPPED CONCEPTS:\n{mapped_block}\n\n"
        f"ATTACH_PARENTS (parent must be one of these ids):\n{parents_block}",
    )
    log.info(
        "[%s] gaps: %d unmapped labels in %d batches (%s, %d workers)",
        company_name,
        len(filtered),
        len(batches),
        model,
        workers,
    )
    finished = [0]
    gate = threading.Lock()

    def run_batch(idx: int, batch: list[dict]) -> list:
        rows = _claude_json_array(
            client,
            model=model,
            system=system,
            user=(
                f"Company: {company_name} (slug={company_slug})\n\n"
                f"UNMAPPED LABELS (batch {idx + 1}):\n"
                f"{json.dumps(batch, ensure_ascii=False, indent=2)}\n"
            ),
            tag=f"[{company_name}] gap batch {idx + 1}/{len(batches)}",
        )
        with gate:
            finished[0] += 1
            log.info(
                "[%s] gap batch %d/%d done (%d complete)",
                company_name,
                idx + 1,
                len(batches),
                finished[0],
            )
            if progress:
                progress("gaps", finished[0], len(batches))
        return rows

    for rows in _run_batches(batches, run_batch, workers=workers):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            conf = float(row.get("confidence") or 0)
            parent = row.get("parent")
            slug = row.get("id_slug") or ""
            label = row.get("label") or row.get("source_label")
            if conf < min_confidence or not parent or parent not in parent_ids:
                continue
            if not slug or not label:
                continue
            slug = re.sub(r"[^a-z0-9\-]+", "-", str(slug).lower()).strip("-")
            if not slug:
                continue
            gaps.append(
                {
                    "id_slug": slug,
                    "label": label,
                    "source_label": row.get("source_label") or label,
                    "statement": row.get("statement") or "other",
                    "parent": parent,
                    "relationship": row.get("relationship") or "child",
                    "weight": row.get("weight"),
                    "definition": row.get("definition") or "",
                    "formula_expression": row.get("formula_expression") or "",
                    "confidence": conf,
                    "reason": row.get("reason") or "",
                }
            )

    # De-dupe by id_slug
    dedup = {}
    for g in gaps:
        dedup[g["id_slug"]] = g
    gaps = list(dedup.values())
    log.info("[%s] gaps done: %d proposals", company_name, len(gaps))

    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "stage": "gaps",
                    "company": company_name,
                    "model": model,
                    "gaps": gaps,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return gaps
