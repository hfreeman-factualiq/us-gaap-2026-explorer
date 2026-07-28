"""US GAAP 2026 — simple concept relationship explorer."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

DATA_PATH = Path(__file__).parent / "data" / "taxonomy-data.json"

ROLE = {
    "atomic": ("Standalone", "#1f6b3a"),
    "total": ("Has formula", "#1e4d8c"),
    "class+total": ("Group + formula", "#3d5a40"),
    "class": ("Broader type", "#3d5a40"),
    "dimensional": ("Tagged form", "#6b2d7b"),
    "ratio": ("Ratio", "#9b1d4a"),
    "aggregate": ("Has residual", "#8a4b12"),
    "abstract": ("Abstract", "#4a5560"),
    "meta": ("Meta", "#4a5560"),
}

EDGE_STYLE = {
    "narrower": ("#0b6e6a", "narrower type"),
    "broader": ("#5a6b78", "broader type"),
    "built_from": ("#1e4d8c", "built from"),
    "used_by": ("#8a4b12", "used by"),
    "tagged": ("#6b2d7b", "tagged as"),
    "ratio": ("#9b1d4a", "ratio part"),
    "residual": ("#8a4b12", "residual"),
    "trait": ("#9aafbf", "trait"),
}


@lru_cache(maxsize=1)
def load_data() -> dict:
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def concept(data: dict, name: str) -> dict | None:
    return data["concepts"].get(name)


def label_of(data: dict, name: str) -> str:
    c = concept(data, name)
    return (c.get("l") if c else None) or name


def role_of(c: dict) -> tuple[str, str]:
    return ROLE.get(c.get("k", "atomic"), ("Concept", "#5a6b78"))


def short_label(text: str, limit: int = 42) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def unique_calc_parents(c: dict) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in c.get("cp") or []:
        name = item["c"]
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def unique_calc_children(c: dict) -> list[tuple[str, float]]:
    """Dedupe formula parts across networks; keep first weight seen."""
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    for item in c.get("cc") or []:
        name = item["c"]
        if name in seen:
            continue
        seen.add(name)
        out.append((name, float(item.get("w", 1))))
    return out


def formulas_by_network(c: dict) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    seen_in_net: dict[str, set[str]] = {}
    for item in c.get("cc") or []:
        net = item.get("net") or "Formula"
        seen_in_net.setdefault(net, set())
        if item["c"] in seen_in_net[net]:
            continue
        seen_in_net[net].add(item["c"])
        groups.setdefault(net, []).append(item)
    return groups


def summarize(data: dict, c: dict) -> str:
    bits: list[str] = []
    if c.get("sp"):
        bits.append("grouped under **" + "**, **".join(label_of(data, n) for n in c["sp"]) + "**")
    if c.get("sc"):
        bits.append(f"broader type for **{len(c['sc'])}** narrower subtypes")
    if c.get("cc"):
        bits.append("built from a calculation formula")
    if c.get("de"):
        bits.append(f"tagged form of **{label_of(data, c['de'][0])}**")
    if c.get("num") or c.get("den"):
        bits.append("defined as a ratio of other concepts")
    if c.get("cp"):
        bits.append(f"used by **{len(unique_calc_parents(c))}** other concept(s)")
    if not bits:
        if c.get("f", {}).get("atomic"):
            return "Standalone leaf concept — no formula, subtypes, tagged form, or ratio parts in this model."
        return "No grouping or composition links found for this concept in the loaded metamodel."
    return "How it relates: " + "; ".join(bits) + "."


def search_matches(data: dict, query: str, limit: int = 40) -> list[dict]:
    q = query.strip().lower()
    if not q:
        return []
    hits = []
    for c in data["concepts"].values():
        if q in c["n"].lower() or q in (c.get("l") or "").lower():
            hits.append(c)
            if len(hits) >= limit:
                break
    hits.sort(key=lambda c: (c.get("l") or c["n"]).lower())
    return hits


def render_concept_links(data: dict, names: list[str], key_prefix: str) -> None:
    if not names:
        st.caption("None")
        return
    for i, name in enumerate(names):
        c = concept(data, name)
        role, _ = role_of(c) if c else ("Concept", "")
        cols = st.columns([4, 1])
        cols[0].markdown(f"**{label_of(data, name)}**  \n`{name}` · {role}")
        if cols[1].button("Open", key=f"{key_prefix}-{i}-{name}", use_container_width=True):
            st.session_state.selected = name
            st.rerun()


def render_relationship_panel(data: dict, name: str) -> None:
    c = concept(data, name)
    if not c:
        st.warning("Concept not found.")
        return

    role, color = role_of(c)
    st.markdown(f"### {c.get('l') or c['n']}")
    st.code(c["n"], language=None)
    st.markdown(
        f'<span style="background:{color}22;color:{color};padding:3px 10px;'
        f'border-radius:999px;font-size:0.8rem;font-weight:600">{role}</span>',
        unsafe_allow_html=True,
    )
    st.write(summarize(data, c))
    if c.get("d"):
        with st.expander("Documentation"):
            st.write(c["d"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Type", c.get("t") or "—")
    m2.metric("Period", c.get("p") or "—")
    m3.metric("Balance", c.get("b") or "—")
    m4.metric("Abstract", "yes" if c.get("a") else "no")

    st.subheader("Built from")
    st.caption("Concepts this one needs — formula parts, ratio inputs, or tagged pieces.")
    built_names: list[str] = []
    if c.get("de"):
        st.markdown("**Tagged equivalent**")
        roles = ["Base concept", "Axis (tag)", "Member (value)", "Other"]
        for i, n in enumerate(c["de"]):
            st.caption(roles[i] if i < len(roles) else "Part")
            render_concept_links(data, [n], f"de-{i}")
            built_names.append(n)
    if c.get("num") or c.get("den"):
        st.markdown("**Ratio parts**")
        render_concept_links(data, list(c.get("num") or []), "num")
        render_concept_links(data, list(c.get("den") or []), "den")
    groups = formulas_by_network(c)
    if groups:
        for net, parts in groups.items():
            with st.expander(f"Formula · {net}", expanded=len(groups) == 1):
                for item in parts:
                    sign = item["w"] if item["w"] < 0 else f'+{item["w"]}'
                    child = item["c"]
                    cols = st.columns([1, 4, 1])
                    cols[0].markdown(f"`{sign}`")
                    cols[1].markdown(f"**{label_of(data, child)}**  \n`{child}`")
                    if cols[2].button("Open", key=f"cc-{net}-{child}", use_container_width=True):
                        st.session_state.selected = child
                        st.rerun()
    if not (c.get("de") or c.get("num") or c.get("den") or groups):
        st.caption("No parts — this concept is not built from others here.")

    st.subheader("Used by")
    st.caption("Other concepts that depend on this one in their formulas.")
    parents = unique_calc_parents(c)
    render_concept_links(data, parents, "cp") if parents else st.caption("Not used as a formula part by others here.")

    st.subheader("Type grouping")
    st.caption("Broader and narrower types in the ontology hierarchy.")
    if c.get("sp"):
        st.markdown("**Broader**")
        render_concept_links(data, c["sp"], "sp")
    if c.get("sc"):
        st.markdown(f"**Narrower subtypes ({len(c['sc'])})**")
        render_concept_links(data, c["sc"][:80], "sc")
        if len(c["sc"]) > 80:
            st.caption(f"Showing first 80 of {len(c['sc'])}.")
    if not c.get("sp") and not c.get("sc"):
        st.caption("Not in the class–subclass type tree.")

    if c.get("ao"):
        st.subheader("Residual “other”")
        render_concept_links(data, c["ao"], "ao")

    if c.get("tr"):
        st.subheader("Traits")
        render_concept_links(data, c["tr"][:30], "tr")


def neighbor_edges(data: dict, name: str, modes: set[str]) -> list[tuple[str, str, str]]:
    """Return (from, to, kind) edges for the selected node."""
    c = concept(data, name)
    if not c:
        return []
    edges: list[tuple[str, str, str]] = []

    if "types" in modes:
        for child in c.get("sc") or []:
            edges.append((name, child, "narrower"))
        for parent in c.get("sp") or []:
            edges.append((parent, name, "broader"))

    if "formula" in modes:
        for child, _w in unique_calc_children(c):
            edges.append((name, child, "built_from"))
        for parent in unique_calc_parents(c):
            edges.append((parent, name, "used_by"))

    if "tagged" in modes and c.get("de"):
        for part in c["de"]:
            edges.append((name, part, "tagged"))

    if "ratio" in modes:
        for part in c.get("num") or []:
            edges.append((name, part, "ratio"))
        for part in c.get("den") or []:
            edges.append((name, part, "ratio"))

    if "residual" in modes:
        for part in c.get("ao") or []:
            edges.append((name, part, "residual"))

    if "traits" in modes:
        for trait in (c.get("tr") or [])[:12]:
            edges.append((name, trait, "trait"))

    return edges


def build_graph(data: dict, focus: str, modes: set[str], depth: int) -> tuple[list[Node], list[Edge]]:
    """Expand outward from focus along selected relationship kinds."""
    frontier = {focus}
    visible = {focus}
    edge_set: set[tuple[str, str, str]] = set()

    for _ in range(max(1, depth)):
        nxt: set[str] = set()
        for node in frontier:
            for frm, to, kind in neighbor_edges(data, node, modes):
                edge_set.add((frm, to, kind))
                for end in (frm, to):
                    if end not in visible:
                        nxt.add(end)
                        visible.add(end)
        frontier = nxt
        if not frontier:
            break

    # Cap graph size for readability
    if len(visible) > 80:
        # Keep focus + direct neighbors preferentially
        direct = {focus}
        for frm, to, _k in list(edge_set):
            if frm == focus or to == focus:
                direct.add(frm)
                direct.add(to)
        extras = [n for n in visible if n not in direct][: max(0, 80 - len(direct))]
        visible = direct.union(extras)
        edge_set = {e for e in edge_set if e[0] in visible and e[1] in visible}

    nodes: list[Node] = []
    for name in visible:
        c = concept(data, name)
        role, color = role_of(c) if c else ("Concept", "#5a6b78")
        title = f"{label_of(data, name)}\n{name}\n{role}"
        size = 28 if name == focus else 18
        nodes.append(
            Node(
                id=name,
                label=short_label(label_of(data, name), 36),
                title=title,
                color=color if name != focus else "#0b6e6a",
                size=size,
                font={"color": "#15202b", "size": 12 if name == focus else 11},
            )
        )

    edges: list[Edge] = []
    for frm, to, kind in edge_set:
        color, label = EDGE_STYLE.get(kind, ("#9aafbf", kind))
        edges.append(
            Edge(
                source=frm,
                target=to,
                label=label if len(edge_set) <= 25 else "",
                color=color,
                width=2 if focus in (frm, to) else 1,
            )
        )
    return nodes, edges


def render_visual_tree(data: dict) -> None:
    st.markdown("### Visual tree")
    st.caption(
        "Click a node to focus it. The graph shows how that concept connects to related concepts. "
        "Use the toggles to choose which relationship kinds to expand."
    )

    focus = st.session_state.selected
    c = concept(data, focus)
    if not c:
        st.info("Select a concept from search first.")
        return

    role, _ = role_of(c)
    st.markdown(f"**Focus:** {c.get('l') or c['n']}  \n`{focus}` · {role}")

    cols = st.columns([2, 1, 1])
    with cols[0]:
        modes = set(
            st.multiselect(
                "Show connections",
                options=["types", "formula", "tagged", "ratio", "residual", "traits"],
                default=["types", "formula"],
                format_func=lambda x: {
                    "types": "Type hierarchy (broader / narrower)",
                    "formula": "Formulas (built from / used by)",
                    "tagged": "Tagged equivalents",
                    "ratio": "Ratio parts",
                    "residual": "Residual other",
                    "traits": "Traits",
                }[x],
                help="Which kinds of links to expand from the focus concept.",
            )
        )
    with cols[1]:
        depth = st.slider("Expand depth", min_value=1, max_value=3, value=1)
    with cols[2]:
        st.write("")
        st.write("")
        if st.button("Reset to Assets", use_container_width=True) and concept(data, "Assets"):
            st.session_state.selected = "Assets"
            st.rerun()

    if not modes:
        st.warning("Pick at least one connection kind.")
        return

    nodes, edges = build_graph(data, focus, modes, depth)
    st.caption(f"Showing {len(nodes)} nodes · {len(edges)} links — click any node to move the focus.")

    config = Config(
        width="100%",
        height=620,
        directed=True,
        physics=True,
        hierarchical=False,
        nodeHighlightBehavior=True,
        highlightColor="#d3ebe9",
        collapsible=False,
    )
    clicked = agraph(nodes=nodes, edges=edges, config=config)
    if clicked and clicked != focus and concept(data, clicked):
        st.session_state.selected = clicked
        st.rerun()

    # Quick expand lists under the graph
    left, right = st.columns(2)
    with left:
        st.markdown("**Narrower subtypes**")
        render_concept_links(data, (c.get("sc") or [])[:20], "vt-sc")
    with right:
        st.markdown("**Built-from parts**")
        render_concept_links(data, [n for n, _ in unique_calc_children(c)][:20], "vt-cc")


def render_type_browser(data: dict) -> None:
    st.markdown("### Browse type hierarchy")
    st.caption("Walk the class–subclass tree (Assets / Liabilities / …). Open a node to inspect it.")

    roots = data.get("ontologyRoots") or []
    if not roots:
        st.info("No ontology roots in the data file.")
        return

    root = st.selectbox(
        "Root",
        options=roots,
        format_func=lambda n: label_of(data, n),
        key="type_root",
    )

    def walk(name: str, depth: int = 0) -> None:
        c = concept(data, name)
        if not c:
            return
        kids = c.get("sc") or []
        role, _ = role_of(c)
        label = f"{label_of(data, name)} · {role}"
        if kids:
            with st.expander(label, expanded=depth < 1 or name == st.session_state.selected):
                if st.button("Focus in visual tree", key=f"walk-{name}-{depth}", use_container_width=False):
                    st.session_state.selected = name
                    st.session_state.main_tab = "Visual tree"
                    st.rerun()
                for child in kids[:100]:
                    walk(child, depth + 1)
                if len(kids) > 100:
                    st.caption(f"{len(kids) - 100} more subtypes not shown.")
        else:
            cols = st.columns([5, 1])
            cols[0].markdown(f"{'&nbsp;' * (depth * 2)}• **{label_of(data, name)}**  \n`{name}`", unsafe_allow_html=True)
            if cols[1].button("Open", key=f"leaf-{name}"):
                st.session_state.selected = name
                st.rerun()

    walk(root)


def main() -> None:
    st.set_page_config(
        page_title="US GAAP 2026 Explorer",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    data = load_data()
    summary = data.get("summary", {})

    if "selected" not in st.session_state:
        st.session_state.selected = "Assets" if concept(data, "Assets") else next(iter(data["concepts"]))

    st.title("US GAAP 2026")
    st.caption("Explore how concepts are grouped, what they are built from, and what depends on them.")

    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Concepts", f"{summary.get('totalConcepts', 0):,}")
    s2.metric("In type tree", f"{summary.get('ontologyNodes', 0):,}")
    s3.metric("With formula", f"{summary.get('calcTotals', 0):,}")
    s4.metric("Tagged forms", f"{summary.get('dimensionalCombos', 0):,}")
    s5.metric("Ratios", f"{summary.get('ratios', 0):,}")

    with st.sidebar:
        st.header("Find a concept")
        query = st.text_input("Search", placeholder="e.g. Gross Profit, Assets, Cash")
        if query.strip():
            hits = search_matches(data, query)
            if not hits:
                st.caption("No matches.")
            for c in hits:
                role, _ = role_of(c)
                if st.button(
                    f"{c.get('l') or c['n']}\n{c['n']} · {role}",
                    key=f"search-{c['n']}",
                    use_container_width=True,
                ):
                    st.session_state.selected = c["n"]
                    st.rerun()
        else:
            st.caption("Search by label or technical name.")

        st.divider()
        st.markdown("**Current focus**")
        cur = concept(data, st.session_state.selected)
        if cur:
            st.markdown(f"**{cur.get('l') or cur['n']}**")
            st.code(cur["n"], language=None)

        st.divider()
        st.markdown(
            """
**Relationship kinds**
- **Grouped under** — broader / narrower types
- **Built from** — formula, ratio, or tagged parts
- **Used by** — concepts that need this one
- **Traits** — shared characteristics
"""
        )

    tab_labels = ["Relationships", "Visual tree", "Type browser"]
    # Keep tab selection sticky when jumping from type browser
    default_index = tab_labels.index(st.session_state.get("main_tab", "Relationships")) if st.session_state.get("main_tab") in tab_labels else 0
    tabs = st.tabs(tab_labels)
    # Clear one-shot tab redirect after render choice
    if "main_tab" in st.session_state:
        # Streamlit tabs aren't programmatically selectable reliably; show a hint instead
        pass

    with tabs[0]:
        render_relationship_panel(data, st.session_state.selected)
    with tabs[1]:
        render_visual_tree(data)
    with tabs[2]:
        render_type_browser(data)

    st.session_state.pop("main_tab", None)


if __name__ == "__main__":
    main()
