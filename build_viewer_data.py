#!/usr/bin/env python3
"""Build compact JSON for the US GAAP 2026 taxonomy/ontology viewer."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent / "us-gaap-2026"
OUT = Path(__file__).resolve().parent / "viewer" / "taxonomy-data.json"

NS = {
    "xs": "http://www.w3.org/2001/XMLSchema",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
}

XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
XLINK_LABEL = "{http://www.w3.org/1999/xlink}label"
XLINK_FROM = "{http://www.w3.org/1999/xlink}from"
XLINK_TO = "{http://www.w3.org/1999/xlink}to"
XLINK_ARCROLE = "{http://www.w3.org/1999/xlink}arcrole"
XLINK_ROLE = "{http://www.w3.org/1999/xlink}role"
XLINK_TITLE = "{http://www.w3.org/1999/xlink}title"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

LABEL_ROLE = "http://www.xbrl.org/2003/role/label"
DOC_ROLE = "http://www.xbrl.org/2003/role/documentation"
TOTAL_LABEL_ROLE = "http://www.xbrl.org/2003/role/totalLabel"

ARCROLE_SHORT = {
    "http://www.xbrl.org/2021/arcrole/class-subclass": "classSubclass",
    "http://www.xbrl.org/2021/arcrole/concept-dimensional-equivalent": "dimensionalEquivalent",
    "http://www.xbrl.org/2021/arcrole/aggregate-other": "aggregateOther",
    "http://www.xbrl.org/2021/arcrole/concept-numerator": "numerator",
    "http://www.xbrl.org/2021/arcrole/concept-denominator": "denominator",
    "http://www.xbrl.org/2021/arcrole/trait-concept": "traitConcept",
    "http://www.xbrl.org/2021/arcrole/trait-domain": "traitDomain",
    "http://www.xbrl.org/2021/arcrole/domain-member": "domainMember",
    "http://xbrl.org/int/dim/arcrole/domain-member": "domainMember",
    "http://www.xbrl.org/2021/arcrole/instant-accrual": "instantAccrual",
    "http://www.xbrl.org/2021/arcrole/instant-contra": "instantContra",
    "http://www.xbrl.org/2021/arcrole/instant-inflow": "instantInflow",
    "http://www.xbrl.org/2021/arcrole/instant-outflow": "instantOutflow",
    "https://xbrl.org/2023/arcrole/summation-item": "summation",
    "http://www.xbrl.org/2003/arcrole/summation-item": "summation",
}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def concept_from_href(href: str) -> str:
    frag = href.rsplit("#", 1)[-1]
    if frag.startswith("us-gaap_"):
        return frag[len("us-gaap_") :]
    if frag.startswith("us-gaap-metaModel_"):
        return "meta:" + frag[len("us-gaap-metaModel_") :]
    if frag.startswith("srt_"):
        return "srt:" + frag[len("srt_") :]
    return frag


def parse_elements(path: Path) -> dict[str, dict]:
    print(f"Parsing elements: {path.name}")
    concepts: dict[str, dict] = {}
    for _event, el in ET.iterparse(path, events=("end",)):
        if local(el.tag) != "element":
            continue
        name = el.get("name")
        if not name:
            el.clear()
            continue
        typ = el.get("type", "")
        concepts[name] = {
            "id": el.get("id") or f"us-gaap_{name}",
            "name": name,
            "type": typ.split(":")[-1] if typ else "",
            "abstract": el.get("abstract") == "true",
            "period": el.get("{http://www.xbrl.org/2003/instance}periodType") or "",
            "balance": el.get("{http://www.xbrl.org/2003/instance}balance") or "",
            "nillable": el.get("nillable") == "true",
            "substitutionGroup": (el.get("substitutionGroup") or "").split(":")[-1],
        }
        el.clear()
    print(f"  {len(concepts)} concepts")
    return concepts


def parse_meta_elements(path: Path) -> dict[str, dict]:
    print(f"Parsing meta elements: {path.name}")
    concepts: dict[str, dict] = {}
    for _event, el in ET.iterparse(path, events=("end",)):
        if local(el.tag) != "element":
            continue
        name = el.get("name")
        if not name:
            el.clear()
            continue
        key = f"meta:{name}"
        typ = el.get("type", "")
        concepts[key] = {
            "id": el.get("id") or f"us-gaap-metaModel_{name}",
            "name": key,
            "type": typ.split(":")[-1] if typ else "",
            "abstract": el.get("abstract") == "true",
            "period": el.get("{http://www.xbrl.org/2003/instance}periodType") or "",
            "balance": "",
            "nillable": el.get("nillable") == "true",
            "substitutionGroup": (el.get("substitutionGroup") or "").split(":")[-1],
            "isMeta": True,
        }
        el.clear()
    print(f"  {len(concepts)} meta concepts")
    return concepts


def parse_labels(path: Path, wanted: set[str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    print(f"Parsing labels: {path.name}")
    labels: dict[str, str] = {}
    docs: dict[str, str] = {}
    loc_map: dict[str, str] = {}
    count = 0
    for _event, el in ET.iterparse(path, events=("end",)):
        tag = local(el.tag)
        if tag == "loc":
            label = el.get(XLINK_LABEL)
            href = el.get(XLINK_HREF) or ""
            concept = concept_from_href(href)
            if wanted is None or concept in wanted or concept.startswith("meta:"):
                loc_map[label] = concept
        elif tag == "labelArc":
            frm = el.get(XLINK_FROM)
            to = el.get(XLINK_TO)
            # store pending via attributes on nothing — handled via pairing below
            # We'll resolve when we see label resources keyed by to label.
            # Instead stash arcs temporarily on loc_map reverse isn't enough.
            # Use a side dict:
            pass
        el.clear()
        count += 1
        if count % 200000 == 0:
            print(f"  scanned {count} nodes...")
    # Two-pass is heavy; use a smarter single-pass with arcs.
    return labels, docs


def parse_labels_fast(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Extract standard labels + documentation via streaming with arc pairing."""
    print(f"Parsing labels (streaming): {path.name}")
    labels: dict[str, str] = {}
    docs: dict[str, str] = {}
    loc_map: dict[str, str] = {}
    # label resource local-name -> (role, text)
    resources: dict[str, list[tuple[str, str]]] = defaultdict(list)
    arcs: list[tuple[str, str]] = []  # (from_loc, to_label)

    for _event, el in ET.iterparse(path, events=("end",)):
        tag = local(el.tag)
        if tag == "loc":
            loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
        elif tag == "label":
            role = el.get(XLINK_ROLE) or LABEL_ROLE
            if role in (LABEL_ROLE, DOC_ROLE, TOTAL_LABEL_ROLE):
                text = (el.text or "").strip()
                if text:
                    resources[el.get(XLINK_LABEL)].append((role, text))
        elif tag == "labelArc":
            arcs.append((el.get(XLINK_FROM), el.get(XLINK_TO)))
        el.clear()

    for frm, to in arcs:
        concept = loc_map.get(frm)
        if not concept:
            continue
        for role, text in resources.get(to, []):
            if role == LABEL_ROLE and concept not in labels:
                labels[concept] = text
            elif role == DOC_ROLE and concept not in docs:
                docs[concept] = text
            elif role == TOTAL_LABEL_ROLE:
                # mark later via concepts flags if needed
                pass
    print(f"  {len(labels)} labels, {len(docs)} docs")
    return labels, docs


def parse_meta_labels_inline(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Meta model embeds labels in the XSD annotation."""
    print(f"Parsing inline meta labels: {path.name}")
    labels: dict[str, str] = {}
    docs: dict[str, str] = {}
    loc_map: dict[str, str] = {}
    resources: dict[str, list[tuple[str, str]]] = defaultdict(list)
    arcs: list[tuple[str, str]] = []

    for _event, el in ET.iterparse(path, events=("end",)):
        tag = local(el.tag)
        if tag == "loc":
            loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
        elif tag == "label":
            role = el.get(XLINK_ROLE) or LABEL_ROLE
            text = (el.text or "").strip()
            if text:
                resources[el.get(XLINK_LABEL)].append((role, text))
        elif tag == "labelArc":
            arcs.append((el.get(XLINK_FROM), el.get(XLINK_TO)))
        el.clear()

    for frm, to in arcs:
        concept = loc_map.get(frm)
        if not concept:
            continue
        for role, text in resources.get(to, []):
            if role == LABEL_ROLE:
                labels[concept] = text
            elif role == DOC_ROLE:
                docs[concept] = text
    print(f"  {len(labels)} meta labels")
    return labels, docs


def parse_definition_file(path: Path) -> list[tuple[str, str, str, float]]:
    """Return list of (arcrole_short, from_concept, to_concept, order)."""
    print(f"  arcs: {path.name}")
    loc_map: dict[str, str] = {}
    arcs: list[tuple[str, str, str, float]] = []
    for _event, el in ET.iterparse(path, events=("end",)):
        tag = local(el.tag)
        if tag == "loc":
            loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
        elif tag == "definitionArc":
            arcrole = el.get(XLINK_ARCROLE) or ""
            short = ARCROLE_SHORT.get(arcrole)
            if not short:
                el.clear()
                continue
            frm = loc_map.get(el.get(XLINK_FROM))
            to = loc_map.get(el.get(XLINK_TO))
            if frm and to:
                order = float(el.get("order") or 0)
                arcs.append((short, frm, to, order))
        el.clear()
    return arcs


def parse_calculation_files(dirs: list[Path]) -> list[tuple[str, str, str, float, str]]:
    """Return (network_role, parent, child, weight, order_as_float_str) via short form."""
    results: list[tuple[str, str, str, float, str]] = []
    files = []
    for d in dirs:
        files.extend(sorted(d.glob("*-cal-*.xml")))
    print(f"Parsing {len(files)} calculation linkbases")
    for path in files:
        loc_map: dict[str, str] = {}
        current_role = ""
        role_short = path.stem
        for _event, el in ET.iterparse(path, events=("end",)):
            tag = local(el.tag)
            if tag == "calculationLink":
                # closing tag — role already captured from attrs when opened;
                # with end-only we get attrs on end too for calculationLink
                current_role = el.get(XLINK_ROLE) or current_role
            elif tag == "loc":
                loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
            elif tag == "calculationArc":
                arcrole = el.get(XLINK_ARCROLE) or ""
                short = ARCROLE_SHORT.get(arcrole, "summation")
                if short != "summation":
                    el.clear()
                    continue
                frm = loc_map.get(el.get(XLINK_FROM))
                to = loc_map.get(el.get(XLINK_TO))
                if frm and to:
                    weight = float(el.get("weight") or 1)
                    order = float(el.get("order") or 0)
                    # Prefer role URI fragment
                    role = current_role or role_short
                    results.append((role, frm, to, weight, order))
            el.clear()
        # Fix: calculationLink role needs to be known before arcs.
        # Re-parse this file properly with start events for calculationLink.
    # Re-do properly:
    results.clear()
    for path in files:
        loc_map = {}
        current_role = path.stem
        for event, el in ET.iterparse(path, events=("start", "end")):
            tag = local(el.tag)
            if event == "start" and tag == "calculationLink":
                current_role = el.get(XLINK_ROLE) or path.stem
                loc_map = {}
            elif event == "end" and tag == "loc":
                loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
            elif event == "end" and tag == "calculationArc":
                frm = loc_map.get(el.get(XLINK_FROM))
                to = loc_map.get(el.get(XLINK_TO))
                if frm and to:
                    results.append(
                        (
                            current_role,
                            frm,
                            to,
                            float(el.get("weight") or 1),
                            float(el.get("order") or 0),
                        )
                    )
            if event == "end":
                el.clear()
    print(f"  {len(results)} calculation arcs")
    return results


def parse_presentation_files(dirs: list[Path]) -> list[tuple[str, str, str, float]]:
    """Return (network_role, parent, child, order) from presentation linkbases."""
    results: list[tuple[str, str, str, float]] = []
    files: list[Path] = []
    for d in dirs:
        files.extend(sorted(d.glob("*-pre-*.xml")))
    print(f"Parsing {len(files)} presentation linkbases")
    for path in files:
        loc_map: dict[str, str] = {}
        current_role = path.stem
        for event, el in ET.iterparse(path, events=("start", "end")):
            tag = local(el.tag)
            if event == "start" and tag == "presentationLink":
                current_role = el.get(XLINK_ROLE) or path.stem
                loc_map = {}
            elif event == "end" and tag == "loc":
                loc_map[el.get(XLINK_LABEL)] = concept_from_href(el.get(XLINK_HREF) or "")
            elif event == "end" and tag == "presentationArc":
                frm = loc_map.get(el.get(XLINK_FROM))
                to = loc_map.get(el.get(XLINK_TO))
                if frm and to:
                    results.append(
                        (current_role, frm, to, float(el.get("order") or 0))
                    )
            if event == "end":
                el.clear()
    print(f"  {len(results)} presentation arcs")
    return results


def role_name(role_uri: str) -> str:
    if "/" in role_uri:
        return role_uri.rsplit("/", 1)[-1]
    return role_uri


def classify(
    name: str,
    children_class: dict[str, list],
    parents_class: dict[str, list],
    calc_children: dict[str, list],
    dim_eq: dict[str, list],
    numerators: dict[str, list],
    denominators: dict[str, list],
    aggregates: dict[str, list],
    concept_info: dict,
) -> dict:
    flags = {
        "classParent": name in children_class and len(children_class[name]) > 0,
        "classChild": name in parents_class and len(parents_class[name]) > 0,
        "calcTotal": name in calc_children and len(calc_children[name]) > 0,
        "dimensionalCombo": name in dim_eq and len(dim_eq[name]) > 0,
        "ratio": (name in numerators and len(numerators[name]) > 0)
        or (name in denominators and len(denominators[name]) > 0),
        "aggregate": name in aggregates and len(aggregates[name]) > 0,
        "abstract": bool(concept_info.get("abstract")),
        "meta": bool(concept_info.get("isMeta")),
    }
    # Primary kind for filtering
    if flags["dimensionalCombo"]:
        kind = "dimensional"
    elif flags["ratio"]:
        kind = "ratio"
    elif flags["calcTotal"] and flags["classParent"]:
        kind = "class+total"
    elif flags["calcTotal"]:
        kind = "total"
    elif flags["classParent"]:
        kind = "class"
    elif flags["aggregate"]:
        kind = "aggregate"
    elif flags["abstract"]:
        kind = "abstract"
    elif flags["meta"]:
        kind = "meta"
    else:
        kind = "atomic"

    flags["atomic"] = kind == "atomic"
    flags["combination"] = kind in {
        "dimensional",
        "ratio",
        "class+total",
        "total",
        "class",
        "aggregate",
    }
    return {"kind": kind, **flags}


# Preferred statement presentation networks (role URI fragment -> synthetic root).
PREFERRED_STATEMENT_NETWORKS: dict[str, str] = {
    "StatementOfFinancialPositionClassified": "root:FinancialPosition",
    "StatementOfIncome": "root:ComprehensiveIncome",
    "StatementOfCashFlowsIndirect": "root:CashFlows",
    "StatementOfShareholdersEquityAndOtherComprehensiveIncome": "root:Equity",
}

# Additional statement networks attached as alternate variants under the same synthetic roots.
ALT_STATEMENT_NETWORKS: dict[str, str] = {
    "StatementOfFinancialPositionClassifiedFirstAlternative": "root:FinancialPosition",
    "StatementOfFinancialPositionClassifiedSecondAlternative": "root:FinancialPosition",
    "StatementOfFinancialPositionUnclassified-DepositBasedOperations": "root:FinancialPosition",
    "StatementOfFinancialPositionUnclassified-InvestmentBasedOperations": "root:FinancialPosition",
    "StatementOfFinancialPositionUnclassified-SecuritiesBasedOperations": "root:FinancialPosition",
    "StatementOfIncomeFirstAlternative": "root:ComprehensiveIncome",
    "StatementOfIncomeInsuranceBasedOperations": "root:ComprehensiveIncome",
    "StatementOfIncomeInterestBasedRevenue": "root:ComprehensiveIncome",
    "StatementOfIncomeRealEstateOperations": "root:ComprehensiveIncome",
    "StatementOfIncomeSecuritiesBasedIncome": "root:ComprehensiveIncome",
    "StatementOfOtherComprehensiveIncome": "root:ComprehensiveIncome",
    "StatementOfCashFlowsDirect": "root:CashFlows",
    "StatementOfCashFlowsIndirectAdditionalElements": "root:CashFlows",
    "StatementOfCashFlowsIndirectInvestmentBasedOperations": "root:CashFlows",
    "StatementOfCashFlowsUnclassified-DepositBasedOperations": "root:CashFlows",
    "StatementOfCashFlowsUnclassified-SecuritiesBasedOperations": "root:CashFlows",
    "StatementOfCashFlowsRealEstate": "root:CashFlows",
}


def build_gaap_data() -> dict:
    """Parse local US GAAP 2026 package into compact ontology JSON structure."""
    elts = ROOT / "elts"
    meta = ROOT / "meta"
    stm = ROOT / "stm"
    dis = ROOT / "dis"

    concepts = parse_elements(elts / "us-gaap-2026.xsd")
    concepts.update(parse_meta_elements(meta / "us-gaap-metaModel-2026.xsd"))

    labels, docs = parse_labels_fast(elts / "us-gaap-lab-2026.xml")
    print("Parsing documentation labels...")
    doc_labels, doc_docs = parse_labels_fast(elts / "us-gaap-doc-2026.xml")
    for k, v in doc_docs.items():
        docs.setdefault(k, v)
    for k, v in doc_labels.items():
        labels.setdefault(k, v)

    meta_labels, meta_docs = parse_meta_labels_inline(meta / "us-gaap-metaModel-2026.xsd")
    labels.update(meta_labels)
    docs.update(meta_docs)

    meta_files = [
        meta / "us-gaap-classSubclass-2026.xsd",
        meta / "us-gaap-conceptDimensionalEquivalent-2026.xsd",
        meta / "us-gaap-aggregateOther-2026.xsd",
        meta / "us-gaap-conceptNumerator-2026.xsd",
        meta / "us-gaap-conceptDenominator-2026.xsd",
        meta / "us-gaap-traitConcept-2026.xsd",
        meta / "us-gaap-traitDomain-2026.xsd",
        meta / "us-gaap-domainMember-2026.xsd",
        meta / "us-gaap-instantAccrual-2026.xsd",
        meta / "us-gaap-instantContra-2026.xsd",
        meta / "us-gaap-instantInflow-2026.xsd",
        meta / "us-gaap-instantOutflow-2026.xsd",
    ]

    print("Parsing meta definition arcs...")
    all_arcs: list[tuple[str, str, str, float]] = []
    for f in meta_files:
        if f.exists():
            all_arcs.extend(parse_definition_file(f))

    children_class: dict[str, list[tuple[str, float]]] = defaultdict(list)
    parents_class: dict[str, list[tuple[str, float]]] = defaultdict(list)
    dim_eq: dict[str, list[tuple[str, float]]] = defaultdict(list)
    aggregates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    numerators: dict[str, list[tuple[str, float]]] = defaultdict(list)
    denominators: dict[str, list[tuple[str, float]]] = defaultdict(list)
    traits: dict[str, list[tuple[str, float]]] = defaultdict(list)
    trait_of: dict[str, list[tuple[str, float]]] = defaultdict(list)
    domain_members: dict[str, list[tuple[str, float]]] = defaultdict(list)
    instant_rels: dict[str, list[tuple[str, str, float]]] = defaultdict(list)

    for short, frm, to, order in all_arcs:
        if short == "classSubclass":
            children_class[frm].append((to, order))
            parents_class[to].append((frm, order))
        elif short == "dimensionalEquivalent":
            dim_eq[frm].append((to, order))
        elif short == "aggregateOther":
            aggregates[frm].append((to, order))
        elif short == "numerator":
            numerators[frm].append((to, order))
        elif short == "denominator":
            denominators[frm].append((to, order))
        elif short == "traitConcept":
            traits[to].append((frm, order))
            trait_of[frm].append((to, order))
        elif short == "traitDomain":
            domain_members[frm].append((to, order))
        elif short == "domainMember":
            domain_members[frm].append((to, order))
        elif short.startswith("instant"):
            instant_rels[frm].append((short, to, order))

    for d in (
        children_class,
        parents_class,
        dim_eq,
        aggregates,
        numerators,
        denominators,
        traits,
        trait_of,
        domain_members,
    ):
        for k in d:
            d[k].sort(key=lambda x: x[1])

    calc_arcs = parse_calculation_files([stm, dis])
    calc_children: dict[str, list[dict]] = defaultdict(list)
    calc_parents: dict[str, list[dict]] = defaultdict(list)
    for role, frm, to, weight, order in calc_arcs:
        rn = role_name(role)
        item = {"concept": to, "weight": weight, "order": order, "network": rn, "role": role}
        calc_children[frm].append(item)
        calc_parents[to].append(
            {"concept": frm, "weight": weight, "order": order, "network": rn, "role": role}
        )

    for k in calc_children:
        calc_children[k].sort(key=lambda x: (x["network"], x["order"]))
    for k in calc_parents:
        calc_parents[k].sort(key=lambda x: (x["network"], x["order"]))

    # Statement presentation trees (stm only — primary financial statements).
    pre_arcs = parse_presentation_files([stm])
    pre_children: dict[str, list[dict]] = defaultdict(list)
    pre_parents: dict[str, list[dict]] = defaultdict(list)
    network_children: dict[str, set[str]] = defaultdict(set)
    network_parents: dict[str, set[str]] = defaultdict(set)
    for role, frm, to, order in pre_arcs:
        rn = role_name(role)
        pre_children[frm].append(
            {"concept": to, "order": order, "network": rn, "role": role}
        )
        pre_parents[to].append(
            {"concept": frm, "order": order, "network": rn, "role": role}
        )
        network_children[rn].add(frm)
        network_parents[rn].add(to)

    for k in pre_children:
        pre_children[k].sort(key=lambda x: (x["network"], x["order"]))
    for k in pre_parents:
        pre_parents[k].sort(key=lambda x: (x["network"], x["order"]))

    # Presentation roots per network (nodes that appear as parents but never as children).
    presentation_network_roots: dict[str, list[str]] = {}
    for rn in sorted(set(network_children) | set(network_parents)):
        roots = sorted(network_children[rn] - network_parents[rn])
        presentation_network_roots[rn] = roots

    class_nodes = set(children_class) | set(parents_class)
    class_roots = sorted(n for n in class_nodes if n not in parents_class)

    referenced = set(class_nodes)
    referenced.update(dim_eq)
    for items in dim_eq.values():
        referenced.update(c for c, _ in items)
    referenced.update(aggregates)
    for items in aggregates.values():
        referenced.update(c for c, _ in items)
    referenced.update(numerators)
    referenced.update(denominators)
    for items in numerators.values():
        referenced.update(c for c, _ in items)
    for items in denominators.values():
        referenced.update(c for c, _ in items)
    referenced.update(calc_children)
    referenced.update(calc_parents)
    referenced.update(pre_children)
    referenced.update(pre_parents)
    referenced.update(traits)
    for items in traits.values():
        referenced.update(c for c, _ in items)
    for items in trait_of.values():
        referenced.update(c for c, _ in items)
    referenced.update(domain_members)
    for items in domain_members.values():
        referenced.update(c for c, _ in items)

    for name in referenced:
        if name not in concepts:
            concepts[name] = {
                "id": name,
                "name": name,
                "type": "",
                "abstract": False,
                "period": "",
                "balance": "",
                "nillable": True,
                "substitutionGroup": "",
                "external": True,
            }

    out_concepts: dict[str, dict] = {}
    kind_counts: dict[str, int] = defaultdict(int)
    for name, info in concepts.items():
        cls = classify(
            name,
            children_class,
            parents_class,
            calc_children,
            dim_eq,
            numerators,
            denominators,
            aggregates,
            info,
        )
        kind_counts[cls["kind"]] += 1
        entry = {
            "n": name,
            "l": labels.get(name, ""),
            "d": docs.get(name, "")[:500] if docs.get(name) else "",
            "t": info.get("type", ""),
            "a": info.get("abstract", False),
            "p": info.get("period", ""),
            "b": info.get("balance", ""),
            "k": cls["kind"],
            "layer": "gaap",
            "f": {
                "atomic": cls["atomic"],
                "combination": cls["combination"],
                "classParent": cls["classParent"],
                "calcTotal": cls["calcTotal"],
                "dimensional": cls["dimensionalCombo"],
                "ratio": cls["ratio"],
                "aggregate": cls["aggregate"],
            },
        }
        if name in children_class:
            entry["sc"] = [c for c, _ in children_class[name]]
        if name in parents_class:
            entry["sp"] = [c for c, _ in parents_class[name]]
        if name in calc_children:
            entry["cc"] = [
                {"c": x["concept"], "w": x["weight"], "net": x["network"]}
                for x in calc_children[name]
            ]
        if name in calc_parents:
            entry["cp"] = [
                {"c": x["concept"], "w": x["weight"], "net": x["network"]}
                for x in calc_parents[name]
            ]
        if name in pre_children:
            entry["pc"] = [
                {"c": x["concept"], "o": x["order"], "net": x["network"]}
                for x in pre_children[name]
            ]
        if name in pre_parents:
            entry["pp"] = [
                {"c": x["concept"], "o": x["order"], "net": x["network"]}
                for x in pre_parents[name]
            ]
        if name in dim_eq:
            entry["de"] = [c for c, _ in dim_eq[name]]
        if name in numerators:
            entry["num"] = [c for c, _ in numerators[name]]
        if name in denominators:
            entry["den"] = [c for c, _ in denominators[name]]
        if name in aggregates:
            entry["ao"] = [c for c, _ in aggregates[name]]
        if name in traits:
            entry["tr"] = [c for c, _ in traits[name]]
        if name in domain_members:
            entry["dm"] = [c for c, _ in domain_members[name]]
        if name in instant_rels:
            entry["ir"] = [{"r": r, "c": c} for r, c, _ in instant_rels[name]]
        out_concepts[name] = entry

    summary = {
        "totalConcepts": len(out_concepts),
        "ontologyNodes": len(class_nodes),
        "ontologyRoots": len(class_roots),
        "calcArcs": len(calc_arcs),
        "preArcs": len(pre_arcs),
        "preNetworks": len(presentation_network_roots),
        "calcTotals": sum(1 for e in out_concepts.values() if e["f"]["calcTotal"]),
        "dimensionalCombos": sum(1 for e in out_concepts.values() if e["f"]["dimensional"]),
        "ratios": sum(1 for e in out_concepts.values() if e["f"]["ratio"]),
        "aggregates": sum(1 for e in out_concepts.values() if e["f"]["aggregate"]),
        "atomicInOntology": sum(1 for n in class_nodes if out_concepts[n]["k"] == "atomic"),
        "kindCounts": dict(sorted(kind_counts.items(), key=lambda x: -x[1])),
    }

    return {
        "meta": {
            "taxonomy": "US GAAP",
            "version": "2026",
            "publisher": "FASB",
            "publicationDate": "2026-01-31",
            "notes": (
                "Atomic = no class children, not a calculation total, not a dimensional "
                "equivalent, not a ratio. Combinations include class parents (ontology "
                "aggregates), calculation totals (summation), dimensional equivalents "
                "(base concept + axis/member), ratios (numerator/denominator), and "
                "aggregate-other residuals. Presentation children (pc) come from statement "
                "linkbases under stm/."
            ),
        },
        "summary": summary,
        "ontologyRoots": class_roots,
        "classRoots": class_roots,
        "presentationNetworkRoots": presentation_network_roots,
        "preferredStatementNetworks": PREFERRED_STATEMENT_NETWORKS,
        "altStatementNetworks": ALT_STATEMENT_NETWORKS,
        "concepts": out_concepts,
    }


def write_gaap_json(data: dict, out: Path | None = None) -> Path:
    target = out or OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {target} ...")
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"Done. {size_mb:.1f} MB")
    print("Summary:", json.dumps(data["summary"], indent=2))
    return target


def main() -> None:
    data = build_gaap_data()
    write_gaap_json(data)


if __name__ == "__main__":
    main()
