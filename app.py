"""US GAAP 2026 — simple concept relationship explorer."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st
from streamlit_agraph import Config, Edge, Node, agraph

DATA_PATH = Path(__file__).parent / "data" / "taxonomy-data.json"
CHILD_LIMIT = 40

ROLE_COLOR = {
    "atomic": "#1f6b3a",
    "total": "#1e4d8c",
    "class+total": "#0b6e6a",
    "class": "#3d5a40",
    "dimensional": "#6b2d7b",
    "ratio": "#9b1d4a",
    "aggregate": "#8a4b12",
    "abstract": "#4a5560",
    "meta": "#4a5560",
}

ROLE_LABEL = {
    "atomic": "Standalone",
    "total": "Has formula",
    "class+total": "Group + formula",
    "class": "Broader type",
    "dimensional": "Tagged form",
    "ratio": "Ratio",
    "aggregate": "Has residual",
    "abstract": "Abstract",
    "meta": "Meta",
}


@st.cache_data(show_spinner="Loading taxonomy…")
def load_data() -> dict:
    with DATA_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def get(data: dict, name: str) -> dict | None:
    return data["concepts"].get(name)


def label(data: dict, name: str) -> str:
    c = get(data, name)
    return (c.get("l") if c else None) or name


def short(text: str, n: int = 40) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def role_label(c: dict | None) -> str:
    if not c:
        return "Concept"
    return ROLE_LABEL.get(c.get("k", "atomic"), "Concept")


def role_color(c: dict | None, focus: bool = False) -> str:
    if focus:
        return "#0b6e6a"
    if not c:
        return "#5a6b78"
    return ROLE_COLOR.get(c.get("k", "atomic"), "#5a6b78")


def unique_names(items: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        name = item["c"]
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def calc_children(c: dict) -> list[str]:
    return unique_names(c.get("cc") or [])


def calc_parents(c: dict) -> list[str]:
    return unique_names(c.get("cp") or [])


def init_state(data: dict) -> None:
    roots = [r for r in (data.get("ontologyRoots") or []) if get(data, r)]
    if "selected" not in st.session_state:
        st.session_state.selected = roots[0] if roots else next(iter(data["concepts"]))
    if "expanded" not in st.session_state:
        st.session_state.expanded = set()
    if "page" not in st.session_state:
        st.session_state.page = "Visual tree"
    if "last_click" not in st.session_state:
        st.session_state.last_click = None


def children_of(data: dict, name: str, mode: str) -> list[str]:
    c = get(data, name)
    if not c:
        return []
    if mode.startswith("Formulas"):
        return calc_children(c)
    if mode.startswith("Used"):
        return calc_parents(c)
    return list(c.get("sc") or [])


def search(data: dict, query: str, limit: int = 30) -> list[str]:
    q = query.strip().lower()
    if not q:
        return []
    hits = []
    for c in data["concepts"].values():
        if q in c["n"].lower() or q in (c.get("l") or "").lower():
            hits.append(c["n"])
            if len(hits) >= limit:
                break
    hits.sort(key=lambda n: label(data, n).lower())
    return hits


def build_tree_graph(data: dict, mode: str):
    """Only roots + children of explicitly expanded nodes."""
    roots = [r for r in (data.get("ontologyRoots") or []) if get(data, r)]
    expanded: set[str] = set(st.session_state.expanded)
    focus = st.session_state.selected

    visible = set(roots)
    edge_pairs: list[tuple[str, str]] = []
    truncated: dict[str, int] = {}

    queue = [r for r in roots if r in expanded]
    queued = set(queue)
    while queue:
        parent = queue.pop(0)
        kids = children_of(data, parent, mode)
        if len(kids) > CHILD_LIMIT:
            truncated[parent] = len(kids) - CHILD_LIMIT
            kids = kids[:CHILD_LIMIT]
        for child in kids:
            edge_pairs.append((parent, child))
            visible.add(child)
            if child in expanded and child not in queued:
                queue.append(child)
                queued.add(child)

    nodes = []
    for name in visible:
        c = get(data, name)
        n_kids = len(children_of(data, name, mode))
        if name in expanded:
            marker = " (−)"
        elif n_kids:
            marker = " (+)"
        else:
            marker = ""
        nodes.append(
            Node(
                id=name,
                label=short(label(data, name), 32) + marker,
                title=f"{label(data, name)}\n{name}\n{role_label(c)}",
                color=role_color(c, focus=(name == focus)),
                size=32 if name in roots else (22 if name == focus else 14),
            )
        )

    edges = [Edge(source=a, target=b, color="#9aafbf") for a, b in edge_pairs]
    return nodes, edges, truncated, roots


def link_rows(data: dict, names: list[str], key_prefix: str) -> None:
    if not names:
        st.caption("None")
        return
    for i, name in enumerate(names[:50]):
        left, right = st.columns([5, 1])
        left.markdown(f"**{label(data, name)}**  \n`{name}` · {role_label(get(data, name))}")
        if right.button("Open", key=f"{key_prefix}-{i}-{name}"):
            st.session_state.selected = name
            st.rerun()
    if len(names) > 50:
        st.caption(f"Showing 50 of {len(names)}.")


def render_details(data: dict, name: str) -> None:
    c = get(data, name)
    if not c:
        st.warning("Concept not found.")
        return

    st.subheader(c.get("l") or c["n"])
    st.code(c["n"], language=None)
    st.caption(role_label(c))

    if c.get("d"):
        with st.expander("Documentation"):
            st.write(c["d"])

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Type", c.get("t") or "—")
    m2.metric("Period", c.get("p") or "—")
    m3.metric("Balance", c.get("b") or "—")
    m4.metric("Abstract", "yes" if c.get("a") else "no")

    st.markdown("#### Built from")
    st.caption("Parts this concept needs.")
    shown = False
    if c.get("de"):
        st.markdown("Tagged equivalent:")
        link_rows(data, c["de"], "de")
        shown = True
    if c.get("num") or c.get("den"):
        st.markdown("Ratio parts:")
        link_rows(data, list(c.get("num") or []) + list(c.get("den") or []), "ratio")
        shown = True
    if c.get("cc"):
        seen: set[str] = set()
        for item in c["cc"]:
            child = item["c"]
            if child in seen:
                continue
            seen.add(child)
            sign = item["w"] if item["w"] < 0 else f'+{item["w"]}'
            left, mid, right = st.columns([1, 4, 1])
            left.code(str(sign))
            mid.markdown(f"**{label(data, child)}**  \n`{child}`")
            if right.button("Open", key=f"cc-{child}"):
                st.session_state.selected = child
                st.rerun()
        shown = True
    if not shown:
        st.caption("No parts — standalone here.")

    st.markdown("#### Used by")
    st.caption("Concepts that depend on this one.")
    link_rows(data, calc_parents(c), "cp")

    st.markdown("#### Type grouping")
    if c.get("sp"):
        st.markdown("Broader:")
        link_rows(data, c["sp"], "sp")
    if c.get("sc"):
        st.markdown("Narrower:")
        link_rows(data, c["sc"], "sc")
    if not c.get("sp") and not c.get("sc"):
        st.caption("Not in the type tree.")

    if c.get("ao"):
        st.markdown("#### Residual other")
        link_rows(data, c["ao"], "ao")

    if c.get("tr"):
        st.markdown("#### Traits")
        link_rows(data, c["tr"][:20], "tr")


def toggle_expand(name: str) -> None:
    expanded = set(st.session_state.expanded)
    if name in expanded:
        expanded.discard(name)
    else:
        expanded.add(name)
    st.session_state.expanded = expanded
    st.session_state.selected = name
    st.session_state.last_click = None


def render_visual_tree(data: dict) -> None:
    st.subheader("Visual tree")
    st.caption(
        "Starts with only the top 3 nodes. Expand a node to reveal its children, then keep going."
    )

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        mode = st.selectbox(
            "Child links",
            [
                "Subtypes (type hierarchy)",
                "Formulas (built from)",
                "Used by",
            ],
        )
    with c2:
        st.write("")
        st.write("")
        if st.button("Reset to top 3", use_container_width=True):
            st.session_state.expanded = set()
            st.session_state.last_click = None
            roots = data.get("ontologyRoots") or []
            if roots:
                st.session_state.selected = roots[0]
            st.rerun()
    with c3:
        st.write("")
        st.write("")
        if st.button("Concept details", use_container_width=True):
            st.session_state.page = "Concept details"
            st.rerun()

    nodes, edges, truncated, roots = build_tree_graph(data, mode)

    st.markdown("##### Start here — expand a top node")
    root_cols = st.columns(len(roots) or 1)
    for i, root in enumerate(roots):
        with root_cols[i]:
            n_kids = len(children_of(data, root, mode))
            open_ = root in st.session_state.expanded
            title = f"{'Collapse' if open_ else 'Expand'} {short(label(data, root), 16)}"
            if st.button(f"{title} ({n_kids})", key=f"root-{root}", use_container_width=True):
                toggle_expand(root)
                st.rerun()

    st.caption(f"{len(nodes)} nodes visible · {len(st.session_state.expanded)} expanded")

    config = Config(
        width=1100,
        height=520,
        directed=True,
        physics=False,
        hierarchical=True,
        levelSeparation=120,
        nodeSpacing=150,
        direction="UD",
        sortMethod="directed",
    )
    clicked = agraph(nodes=nodes, edges=edges, config=config)

    # agraph re-emits the same click every rerun — only react to a new click id
    if clicked and get(data, clicked) and clicked != st.session_state.last_click:
        st.session_state.last_click = clicked
        st.session_state.selected = clicked
        st.rerun()

    if truncated:
        for parent, more in truncated.items():
            st.caption(f"{label(data, parent)}: showing {CHILD_LIMIT} of {CHILD_LIMIT + more} children.")

    focus = st.session_state.selected
    kids = children_of(data, focus, mode)
    st.markdown(f"#### Children of {label(data, focus)}")
    st.caption(f"{len(kids)} children · use Expand to add them to the tree")

    open_ = focus in st.session_state.expanded
    if st.button("Collapse selected" if open_ else "Expand selected in tree", key="toggle-focus"):
        toggle_expand(focus)
        st.rerun()

    if not kids:
        st.caption("No children for this link type.")
        return

    for i, child in enumerate(kids[:CHILD_LIMIT]):
        left, a, b = st.columns([4, 1, 1])
        left.markdown(f"**{label(data, child)}**  \n`{child}`")
        if a.button("Select", key=f"sel-{i}-{child}"):
            st.session_state.selected = child
            st.session_state.last_click = None
            st.rerun()
        if b.button("Expand", key=f"ex-{i}-{child}"):
            st.session_state.expanded = set(st.session_state.expanded) | {focus, child}
            st.session_state.selected = child
            st.session_state.last_click = None
            st.rerun()


def render_sidebar(data: dict) -> None:
    with st.sidebar:
        st.header("Navigate")
        page = st.radio(
            "Page",
            ["Visual tree", "Concept details"],
            index=0 if st.session_state.page == "Visual tree" else 1,
        )
        st.session_state.page = page

        st.divider()
        query = st.text_input("Search", placeholder="Gross Profit, Cash…")
        if query.strip():
            hits = search(data, query)
            if not hits:
                st.caption("No matches.")
            for name in hits:
                c = get(data, name)
                if st.button(
                    f"{short(label(data, name), 46)}\n{role_label(c)}",
                    key=f"s-{name}",
                    use_container_width=True,
                ):
                    st.session_state.selected = name
                    st.session_state.last_click = None
                    for p in (c or {}).get("sp") or []:
                        st.session_state.expanded.add(p)
                    st.session_state.page = "Concept details"
                    st.rerun()

        st.divider()
        st.caption("Selected")
        st.markdown(f"**{label(data, st.session_state.selected)}**")
        st.code(st.session_state.selected, language=None)


def main() -> None:
    st.set_page_config(
        page_title="US GAAP 2026 Explorer",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    data = load_data()
    init_state(data)
    render_sidebar(data)

    summary = data.get("summary", {})
    st.title("US GAAP 2026")
    st.caption("Start from Assets, Liabilities, and Inventory Adjustments — then expand outward.")

    a, b, c, d = st.columns(4)
    a.metric("Concepts", f"{summary.get('totalConcepts', 0):,}")
    b.metric("In type tree", f"{summary.get('ontologyNodes', 0):,}")
    c.metric("With formula", f"{summary.get('calcTotals', 0):,}")
    d.metric("Ratios", f"{summary.get('ratios', 0):,}")

    if st.session_state.page == "Visual tree":
        render_visual_tree(data)
    else:
        render_details(data, st.session_state.selected)


if __name__ == "__main__":
    main()
