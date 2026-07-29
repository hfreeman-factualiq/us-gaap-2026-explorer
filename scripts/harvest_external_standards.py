#!/usr/bin/env python3
"""Harvest the formalized-standards registry into a flat concept catalog.

Reads ontology/external_standards.yaml (signal domains + standards to scrape) and
writes ontology/external_standards_catalog.json, which build_ontology.py merges as
the `standard` layer of the v1.3 base template tree.

Network is optional. With it, every scrape target is probed and its reachability is
recorded so unreachable/gated sources are visible in the tree instead of silently
missing. Without it (``--offline``), the curated key classes are still emitted.

  python scripts/harvest_external_standards.py            # probe targets
  python scripts/harvest_external_standards.py --offline  # curated only
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required. Install with: pip install pyyaml") from exc

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY = ROOT / "ontology"
REGISTRY = ONTOLOGY / "external_standards.yaml"
CATALOG_OUT = ONTOLOGY / "external_standards_catalog.json"
PROBE_OUT = ONTOLOGY / "standards" / "probe_status.json"

CONCEPT_SOURCES = [
    ROOT / "taxonomy-data.json",
    ROOT / "data" / "gaap-only.json",
    ROOT / "viewer" / "taxonomy-data.json",
]

USER_AGENT = "us-gaap-ontology-standards-harvest/1.0 (educational; ontology registry)"
PROBE_TIMEOUT = 20
SCRAPE_TIMEOUT = 60
SCRAPE_MAX_BYTES = 8_000_000
SCRAPED_CAP_PER_STANDARD = 80

# File suffixes / content hints that warrant a full-body concept scrape.
MACHINE_SUFFIXES = (".xsd", ".xmi", ".xml", ".ttl", ".owl", ".rdf", ".json", ".jsonld")


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")


def class_node_id(std_id: str, class_id: str) -> str:
    return f"std:{std_id}:{class_id.replace(':', '.')}"


def humanize(name: str) -> str:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name.replace("_", " ").replace("-", " "))
    return spaced.strip() or name


def load_registry() -> dict:
    with REGISTRY.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_known_concepts() -> set[str]:
    """Concept keys of the current ontology, used to resolve mapsTo targets."""
    for path in CONCEPT_SOURCES:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            concepts = data.get("concepts") or {}
            if concepts:
                print(f"Resolving mappings against {path.name} ({len(concepts):,} concepts)")
                return set(concepts)
    print("No ontology JSON found — mapsTo targets will all be reported as unresolved")
    return set()


def load_nongaap_ids() -> set[str]:
    path = ONTOLOGY / "nongaap_metrics.yaml"
    if not path.exists():
        return set()
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return {m["id"] for m in (doc.get("metrics") or []) if m.get("id")}


def probe(url: str) -> dict:
    """Best-effort reachability check. Never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            body = resp.read(4096)
            return {
                "status": resp.status,
                "reachable": True,
                "contentType": resp.headers.get("Content-Type", ""),
                "bytesSampled": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "reachable": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "reachable": False, "error": str(exc)[:200]}


def fetch_body(url: str) -> tuple[bytes | None, dict]:
    """Download a full artifact body for concept extraction."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as resp:
            raw = resp.read(SCRAPE_MAX_BYTES + 1)
            truncated = len(raw) > SCRAPE_MAX_BYTES
            if truncated:
                raw = raw[:SCRAPE_MAX_BYTES]
            return raw, {
                "status": resp.status,
                "reachable": True,
                "contentType": resp.headers.get("Content-Type", ""),
                "bytes": len(raw),
                "truncated": truncated,
            }
    except urllib.error.HTTPError as exc:
        return None, {"status": exc.code, "reachable": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return None, {"status": None, "reachable": False, "error": str(exc)[:200]}


def is_machine_readable(url: str, content_type: str = "") -> bool:
    low = (url or "").lower().split("?")[0]
    if any(low.endswith(sfx) for sfx in MACHINE_SUFFIXES):
        return True
    ct = (content_type or "").lower()
    return any(
        tok in ct
        for tok in (
            "xml",
            "xsd",
            "rdf",
            "turtle",
            "owl",
            "json",
            "ld+json",
        )
    )


def extract_from_xsd(text: str) -> list[str]:
    names: list[str] = []
    for pat in (
        r'<(?:xs:|xsd:)?complexType\s+[^>]*name="([^"]+)"',
        r'<(?:xs:|xsd:)?simpleType\s+[^>]*name="([^"]+)"',
        r'<(?:xs:|xsd:)?element\s+[^>]*name="([^"]+)"',
    ):
        for m in re.finditer(pat, text, flags=re.I):
            names.append(m.group(1))
    return names


def extract_from_xmi(text: str) -> list[str]:
    names: list[str] = []
    # Prefer Class / Enumeration / DataType elements (attribute order varies)
    for m in re.finditer(
        r"<[^>]*\bxmi:type=\"uml:(?:Class|Enumeration|DataType)\"[^>]*>",
        text,
        flags=re.I,
    ):
        tag = m.group(0)
        name_m = re.search(r'\bname="([^"]+)"', tag)
        if name_m:
            names.append(name_m.group(1))
            continue
        id_m = re.search(r'\bxmi:id="([^"]+)"', tag)
        if id_m:
            raw = id_m.group(1)
            # BMM uses ids like BMM-Assessment or BMM-Assessment-usingAssessment
            # Keep only the class-level token (second segment when hyphenated).
            parts = raw.split("-")
            if len(parts) >= 2 and parts[0].isupper() or (parts and parts[0].isalpha()):
                # Class ids are typically PREFIX-ClassName (two segments)
                if len(parts) == 2:
                    names.append(parts[1])
                elif len(parts) > 2 and parts[1][0:1].isupper():
                    # Skip association/property ids with more segments
                    pass
    # Fallback: any name= on Class-like tags
    if not names:
        for m in re.finditer(r'\bname="([A-Z][A-Za-z0-9_]{2,})"', text):
            names.append(m.group(1))
    return names


def extract_from_ttl(text: str) -> list[str]:
    names: list[str] = []
    for m in re.finditer(r"(?:^|\s)(?:[\w-]+:)?([A-Za-z][\w-]*)\s+a\s+(?:owl:Class|rdfs:Class)", text):
        names.append(m.group(1))
    return names


def extract_from_actus(data: dict) -> list[str]:
    names: list[str] = []
    tax = data.get("taxonomy") or {}
    if isinstance(tax, dict):
        for item in tax.values():
            if isinstance(item, dict):
                names.append(item.get("acronym") or item.get("name") or item.get("identifier") or "")
            elif isinstance(item, str):
                names.append(item)
    terms = data.get("terms") or {}
    if isinstance(terms, dict):
        for item in terms.values():
            if isinstance(item, dict):
                names.append(item.get("acronym") or item.get("name") or item.get("identifier") or "")
    states = data.get("states") or {}
    if isinstance(states, dict):
        names.extend(states.keys())
    event = data.get("event") or {}
    if isinstance(event, dict):
        names.extend(f"Event_{k}" for k in event.keys())
    return [n for n in names if n]


def extract_from_json(text: str) -> list[str]:
    names: list[str] = []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return names
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("name"):
                n = str(item["name"])
                if n.endswith((".json", ".yaml", ".yml", ".xsd", ".ttl", ".md")):
                    names.append(Path(n).stem)
        return names
    if isinstance(data, dict):
        # ACTUS dictionary shape
        if "taxonomy" in data and "terms" in data:
            return extract_from_actus(data)
        # OCF git tree listing
        tree = data.get("tree")
        if isinstance(tree, list):
            for item in tree:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path") or "")
                if "/schema/" in path.replace("\\", "/") and path.endswith(".schema.json"):
                    names.append(Path(path).name.replace(".schema.json", ""))
                elif path.endswith(".schema.json"):
                    names.append(Path(path).name.replace(".schema.json", ""))
                elif path.endswith((".json",)) and "enum" in path.lower():
                    names.append(Path(path).stem.replace(".schema", ""))
            if names:
                return names
        defs = data.get("$defs") or data.get("definitions") or {}
        if isinstance(defs, dict):
            names.extend(str(k) for k in defs.keys())
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if not isinstance(item, dict):
                    continue
                types = item.get("@type")
                type_list = types if isinstance(types, list) else [types]
                if any(t and "Class" in str(t) for t in type_list):
                    lid = item.get("@id") or ""
                    if isinstance(lid, str) and lid:
                        names.append(lid.rsplit("/", 1)[-1].rsplit("#", 1)[-1])
        # GitHub search repositories response
        items = data.get("items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("full_name"):
                    names.append(str(item["full_name"]).replace("/", "_"))
    return names


def extract_concepts(url: str, body: bytes, content_type: str = "") -> list[str]:
    text = body.decode("utf-8", errors="replace")
    low = url.lower().split("?")[0]
    if low.endswith(".xsd") or "xmlschema" in (content_type or "").lower():
        return extract_from_xsd(text)
    if low.endswith(".xmi") or "xmi" in low:
        return extract_from_xmi(text)
    if low.endswith((".ttl", ".owl", ".rdf")):
        return extract_from_ttl(text) or extract_from_xmi(text)
    if low.endswith((".json", ".jsonld")) or "json" in (content_type or "").lower():
        return extract_from_json(text)
    if low.endswith(".xml") or "xml" in (content_type or "").lower():
        return extract_from_xsd(text) or extract_from_xmi(text)
    return []


def scrapeable_prefix(std_id: str) -> str:
    """Stable short prefix for scraped class ids (matches curated keyClasses)."""
    return {
        "bmm": "bmm",
        "dmn": "dmn",
        "vdml": "vdml",
        "scor-ds": "scor",
        "bian": "bian",
        "dora": "dora",
        "open-fair": "fair",
        "cobit": "cobit",
        "itil4": "itil",
        "sasb-issb": "sasb",
        "open-saas": "opensaas",
        "actus": "actus",
        "ocf": "ocf",
        "apqc-pcf": "apqc",
        "schema-org": "schema",
        "w3c-org": "org",
        "iso-30414": "iso30414",
        "fibo": "fibo",
        "fro": "fro",
        "archimate": "archimate",
        "iris-plus": "iris",
        "imp": "imp",
        "xbrl-gl": "gl-cor",
        "us-gaap-xbrl": "us-gaap",
        "sec-ixbrl": "sec",
    }.get(std_id, std_id.replace("-", ""))


def scrape_machine_readable(registry: dict, probes: dict, try_network: bool) -> dict[str, list[dict]]:
    """Download reachable machine-readable targets and extract class/type names."""
    scraped: dict[str, list[dict]] = {}
    if not try_network:
        return scraped

    for std in registry.get("standards") or []:
        sid = std["id"]
        prefix = scrapeable_prefix(sid)
        seen: set[str] = set()
        # Prefer curated names already known so we don't duplicate them as scraped
        for kc in std.get("keyClasses") or []:
            local = (kc["id"].split(":")[-1] if ":" in kc["id"] else kc["id"]).lower()
            seen.add(local)

        for i, target in enumerate(std.get("scrape") or []):
            key = f"{sid}#{i}"
            status = probes.get(key) or {}
            url = target.get("url") or ""
            kind = target.get("kind") or ""
            if kind in {"manual", "local"}:
                continue
            if status.get("reachable") is not True:
                continue
            if not is_machine_readable(url, status.get("contentType") or ""):
                continue
            print(f"  scrape {sid} <- {url}")
            body, meta = fetch_body(url)
            status["scrape"] = meta
            if not body:
                continue
            names = extract_concepts(url, body, meta.get("contentType") or "")
            # Drop noise
            skip = {
                "string",
                "boolean",
                "integer",
                "decimal",
                "anyuri",
                "id",
                "idref",
                "qname",
                "date",
                "datetime",
                "double",
                "float",
                "ncname",
                "token",
                "language",
                "name",
                "nmtoken",
            }
            added = 0
            bucket = scraped.setdefault(sid, [])
            for name in names:
                local = name.strip()
                if not local or local.lower() in skip or len(local) < 2:
                    continue
                # Strip leading t/Type prefixes common in DMN XSDs (tDecision → Decision)
                clean = re.sub(r"^t(?=[A-Z])", "", local)
                if clean.lower() in seen:
                    continue
                seen.add(clean.lower())
                class_id = f"{prefix}:{clean}"
                bucket.append(
                    {
                        "id": class_id,
                        "label": humanize(clean),
                        "note": f"Scraped from {url}",
                        "scrapedFrom": url,
                    }
                )
                added += 1
                if len(bucket) >= SCRAPED_CAP_PER_STANDARD:
                    break
            print(f"    +{added} concepts (cap {SCRAPED_CAP_PER_STANDARD})")
            if len(scraped.get(sid, [])) >= SCRAPED_CAP_PER_STANDARD:
                break
    return scraped


def probe_targets(registry: dict, try_network: bool) -> dict:
    results: dict[str, dict] = {}
    for std in registry.get("standards") or []:
        for i, target in enumerate(std.get("scrape") or []):
            key = f"{std['id']}#{i}"
            kind = target.get("kind") or "http-html"
            url = target.get("url") or ""
            if kind == "local":
                path = ROOT / url
                results[key] = {
                    "url": url,
                    "kind": kind,
                    "reachable": path.exists(),
                    "status": "present" if path.exists() else "missing",
                }
                continue
            if not try_network or kind == "manual":
                results[key] = {
                    "url": url,
                    "kind": kind,
                    "reachable": None,
                    "status": "not-probed" if kind != "manual" else "manual-download",
                }
                continue
            print(f"  probe {std['id']} -> {url}")
            results[key] = {"url": url, "kind": kind, **probe(url)}
    return results


def build_nodes(
    registry: dict,
    probes: dict,
    known: set[str],
    nongaap: set[str],
    scraped: dict[str, list[dict]] | None = None,
) -> tuple[list[dict], dict]:
    nodes: list[dict] = []
    class_index: dict[str, str] = {}
    unresolved: list[dict] = []
    scraped = scraped or {}
    standards = registry.get("standards") or []
    domains = registry.get("signalDomains") or []
    domain_labels = {d["id"]: d.get("label") or d["id"] for d in domains}
    scraped_count = 0

    def resolve(refs: list[str], origin: str) -> list[str]:
        out: list[str] = []
        for ref in refs or []:
            if ref in known or ref in nongaap:
                if ref not in out:
                    out.append(ref)
            else:
                unresolved.append({"ref": ref, "origin": origin})
        return out

    # --- standards, their scrape targets and key classes ---------------------
    for std in standards:
        sid = std["id"]
        node_id = f"std:{sid}"
        targets = std.get("scrape") or []
        target_ids: list[str] = []

        for i, target in enumerate(targets):
            tid = f"scrape:{sid}:{i}"
            status = probes.get(f"{sid}#{i}", {})
            nodes.append(
                {
                    "id": tid,
                    "label": f"{target.get('kind', 'http')} — {target.get('url', '')}",
                    "layer": "standard",
                    "kind": "scrapeTarget",
                    "standard": sid,
                    "category": "scrape-target",
                    "url": target.get("url"),
                    "scrapeKind": target.get("kind"),
                    "definition": target.get("note") or "",
                    "probe": status,
                    "mapsTo": [],
                }
            )
            target_ids.append(tid)

        class_ids: list[str] = []
        curated_ids = {kc["id"] for kc in (std.get("keyClasses") or [])}
        for kc in std.get("keyClasses") or []:
            cid = class_node_id(sid, kc["id"])
            class_index[kc["id"]] = cid
            maps = resolve(kc.get("mapsTo") or [], f"{sid}/{kc['id']}")
            nodes.append(
                {
                    "id": cid,
                    "label": kc.get("label") or kc["id"],
                    "layer": "standard",
                    "kind": "standardClass",
                    "standard": sid,
                    "category": "standard-class",
                    "classId": kc["id"],
                    "expression": kc.get("expression") or "",
                    "definition": kc.get("note") or f"{std['label']} class `{kc['id']}`.",
                    "mapsTo": maps,
                }
            )
            class_ids.append(cid)

        for kc in scraped.get(sid) or []:
            if kc["id"] in curated_ids:
                continue
            cid = class_node_id(sid, kc["id"])
            if cid in class_index.values():
                continue
            class_index[kc["id"]] = cid
            nodes.append(
                {
                    "id": cid,
                    "label": kc.get("label") or kc["id"],
                    "layer": "standard",
                    "kind": "standardClass",
                    "standard": sid,
                    "category": "scraped-class",
                    "classId": kc["id"],
                    "expression": "",
                    "definition": kc.get("note") or f"Scraped from {std['label']}.",
                    "scrapedFrom": kc.get("scrapedFrom"),
                    "mapsTo": [],
                }
            )
            class_ids.append(cid)
            scraped_count += 1

        nodes.append(
            {
                "id": node_id,
                "label": std["label"],
                "layer": "standard",
                "kind": "standard",
                "standard": sid,
                "category": f"integration-{std.get('integration', 'registered')}",
                "steward": std.get("steward"),
                "formats": std.get("formats") or [],
                "integration": std.get("integration") or "registered",
                "verified": std.get("verified", True),
                "domains": std.get("domains") or [],
                "domainLabels": [domain_labels.get(d, d) for d in std.get("domains") or []],
                "definition": (std.get("coverage") or "").strip(),
                "scrapeTargets": target_ids,
                "keyClasses": class_ids,
                "mapsTo": [],
            }
        )

    # --- signal domains and signals -----------------------------------------
    for dom in domains:
        did = dom["id"]
        signal_ids: list[str] = []
        for sig in dom.get("signals") or []:
            sig_id = f"signal:{did}.{sig['key']}"
            gaap = resolve(sig.get("gaap") or [], sig_id)
            ng = resolve(sig.get("nongaap") or [], sig_id)
            class_nodes: list[str] = []
            for cref in sig.get("classes") or []:
                target = class_index.get(cref)
                if target:
                    class_nodes.append(target)
                else:
                    unresolved.append({"ref": cref, "origin": sig_id, "kind": "standardClass"})
            nodes.append(
                {
                    "id": sig_id,
                    "label": sig.get("label") or sig["key"],
                    "layer": "standard",
                    "kind": "signal",
                    "signalKey": sig["key"],
                    "domain": did,
                    "category": "signal",
                    "definition": (
                        f"{dom.get('label')} signal `{sig['key']}` — formalized by "
                        + (", ".join(sig.get("classes") or []) or "no standard class yet")
                    ),
                    "mapsTo": gaap + ng,
                    "gaapTags": gaap,
                    "nongaapRefs": ng,
                    "standardClasses": class_nodes,
                    "gap": not (gaap or ng or class_nodes),
                }
            )
            signal_ids.append(sig_id)

        nodes.append(
            {
                "id": f"domain:{did}",
                "label": dom.get("label") or did,
                "layer": "standard",
                "kind": "signalDomain",
                "domain": did,
                "order": dom.get("order") or 0,
                "category": "signal-domain",
                "definition": (dom.get("description") or "").strip(),
                "primaryStandards": [f"std:{s}" for s in dom.get("primaryStandards") or []],
                "signals": signal_ids,
                "mapsTo": [],
            }
        )

    stats = {
        "standards": len(standards),
        "standardClasses": sum(1 for n in nodes if n["kind"] == "standardClass"),
        "scrapedClasses": scraped_count,
        "scrapeTargets": sum(1 for n in nodes if n["kind"] == "scrapeTarget"),
        "signalDomains": len(domains),
        "signals": sum(1 for n in nodes if n["kind"] == "signal"),
        "signalsWithoutMapping": sum(1 for n in nodes if n.get("gap")),
        "unresolvedRefs": len(unresolved),
        "integrationCounts": {
            key: sum(1 for s in standards if (s.get("integration") or "registered") == key)
            for key in ["full", "partial", "registered"]
        },
        "reachableTargets": sum(1 for p in probes.values() if p.get("reachable") is True),
        "unreachableTargets": sum(1 for p in probes.values() if p.get("reachable") is False),
    }
    return nodes, {"stats": stats, "unresolved": unresolved}


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {path}")


def harvest(try_network: bool = True) -> dict:
    registry = load_registry()
    known = load_known_concepts()
    nongaap = load_nongaap_ids()
    print(f"Probing scrape targets (network={'on' if try_network else 'off'})…")
    probes = probe_targets(registry, try_network)
    print("Scraping machine-readable artifacts…")
    scraped = scrape_machine_readable(registry, probes, try_network)
    nodes, report = build_nodes(registry, probes, known, nongaap, scraped=scraped)

    catalog = {
        "meta": {
            "purpose": "Formalized ontologies / taxonomies / schemas to scrape for concepts",
            "registry": str(REGISTRY.relative_to(ROOT)).replace("\\", "/"),
            "registryVersion": registry.get("version"),
            "notes": (
                "Signal domains map underwriting signals to the standard that already "
                "codifies them. Scrape targets carry probe status so gated or moved "
                "artifacts stay visible. Machine-readable XSD/XMI/JSON targets are "
                "downloaded and class/type names are merged as scraped-class nodes."
            ),
        },
        "summary": report["stats"],
        "nodes": nodes,
    }
    write_json(CATALOG_OUT, catalog)
    write_json(
        PROBE_OUT,
        {
            "meta": {"networkProbed": try_network, "timeoutSeconds": PROBE_TIMEOUT},
            "targets": probes,
            "scrapedByStandard": {k: len(v) for k, v in scraped.items()},
            "unresolvedReferences": report["unresolved"],
        },
    )
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Harvest external standards registry")
    parser.add_argument("--offline", action="store_true", help="Skip network probes")
    args = parser.parse_args()
    catalog = harvest(try_network=not args.offline)
    print("Summary:", json.dumps(catalog["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
