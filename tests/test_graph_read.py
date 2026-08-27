"""`/graph` — the read-only map plane behind the ambient canvas.

Deterministic: no LLM, no network. What is under test is the projection and its
guarantees — a skeletal payload, a stable layout, and no way for the browser to
name a filesystem path.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from starlette.testclient import TestClient  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _fixture_db(tmp_path: Path, name: str = "current.lbug") -> Path:
    from mcp_server.fixture import ensure_fixture

    return ensure_fixture(tmp_path / name)


# ------------------------------------------------------------------ projection


def test_map_is_skeletal_and_never_ships_bodies_or_embeddings(tmp_path):
    """"Payloads paged in late" applies literally: the map carries labels and
    anchors, never `text_content` and never an embedding. A full graph read that
    dragged bodies along would be the single biggest cost on the wire."""
    import graph_read

    m = graph_read.read_map(_fixture_db(tmp_path))
    assert m["node_count"] > 0 and m["edge_count"] > 0
    assert len(m["nodes"]) == m["node_count"]

    for n in m["nodes"]:
        assert "text_content" not in n
        assert "embedding" not in n
        assert {"id", "label", "semantic_anchor", "x", "y"} <= set(n)
        # Structural roles are engine vocabulary for the Graph Compass, not
        # something a map client can act on. They were emitted here and only
        # ever printed back; asserted absent so they cannot drift in again.
        assert "roles" not in n

    for e in m["edges"]:
        assert e["type"] in graph_read.REL_TYPES
        assert e["source"] and e["target"]


def test_read_node_pages_body_without_embedding(tmp_path):
    """The body is a separate late load — map stays skeletal; open loads text."""
    import graph_read

    db = _fixture_db(tmp_path)
    m = graph_read.read_map(db)
    node_id = m["nodes"][0]["id"]
    body = graph_read.read_node(db, node_id)
    assert "error" not in body
    assert body["id"] == node_id
    assert "text_content" in body
    assert "embedding" not in body
    assert graph_read.read_node(db, "")["error"] == "missing node id"
    assert graph_read.read_node(db, "no-such-node")["error"] == "unknown node"


def test_every_node_and_edge_is_present_uncapped(tmp_path):
    """Decided: the full map, no cap. A silently truncated map is worse than a
    slow one — the operator cannot tell what is missing."""
    import real_ladybug as lb

    import graph_read

    db = _fixture_db(tmp_path)
    conn = lb.Connection(lb.Database(str(db)))
    total_nodes = conn.execute("MATCH (n:Concept) RETURN count(n)").get_next()[0]
    total_edges = sum(
        conn.execute(f"MATCH ()-[e:{t}]->() RETURN count(e)").get_next()[0]
        for t in graph_read.REL_TYPES
    )

    m = graph_read.read_map(db)
    assert m["node_count"] == total_nodes
    assert m["edge_count"] == total_edges


def test_reading_an_empty_database_does_not_seed_it(tmp_path):
    """The canvas must never write. `engine.get_connection` auto-seeds an empty
    file — reading a graph through it would silently invent an AI-history graph
    inside the user's empty database."""
    import real_ladybug as lb

    import graph_read

    empty = tmp_path / "empty.lbug"
    conn = lb.Connection(lb.Database(str(empty)))
    conn.execute(
        "CREATE NODE TABLE Concept (id STRING, label STRING, text_content STRING, "
        "semantic_anchor STRING, token_count INT64, centrality_score DOUBLE, "
        "is_metanode BOOLEAN DEFAULT false, linked_graph_id STRING DEFAULT '', "
        "PRIMARY KEY (id))"
    )
    for rel in graph_read.REL_TYPES:
        conn.execute(f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    del conn

    m = graph_read.read_map(empty)
    assert m["node_count"] == 0 and m["nodes"] == []


# --------------------------------------------------------------------- layout


def test_layout_is_deterministic_and_cached_by_version(tmp_path):
    """The map is a place the operator learns; it must not move between reads,
    machines or sessions. That is the whole reason layout is server-side."""
    import graph_read

    db = _fixture_db(tmp_path)
    first = graph_read.read_map(db)
    sidecar = db.with_name(f"{db.stem}.layout.json")
    assert sidecar.exists(), "layout was not persisted"

    second = graph_read.read_map(db)
    assert {n["id"]: (n["x"], n["y"]) for n in first["nodes"]} == \
           {n["id"]: (n["x"], n["y"]) for n in second["nodes"]}

    # computing from scratch reproduces the same coordinates
    sidecar.unlink()
    third = graph_read.read_map(db)
    assert {n["id"]: (n["x"], n["y"]) for n in first["nodes"]} == \
           {n["id"]: (n["x"], n["y"]) for n in third["nodes"]}


def test_stale_layout_is_recomputed_when_the_graph_changes(tmp_path):
    import graph_read

    db = _fixture_db(tmp_path)
    graph_read.read_map(db)
    sidecar = db.with_name(f"{db.stem}.layout.json")
    sidecar.write_text(json.dumps({"version": graph_read.LAYOUT_SIDECAR_VERSION,
                                   "topology_version": "stale",
                                   "lenses": {"canonical": {
                                       "positions": {"x": [1, 1]}}}}))

    m = graph_read.read_map(db)
    saved = json.loads(sidecar.read_text())
    assert saved["topology_version"] == m["topology_version"] != "stale"
    assert len(saved["lenses"]["canonical"]["positions"]) == m["node_count"]


def test_layout_survives_writes_that_do_not_change_the_graphs_shape(tmp_path):
    """`graph_version` moves on any write — including `centrality_score`, which
    the structural index writes back on every cold read. Keying layout on it
    meant reading the map could invalidate the map. Layout keys on topology."""
    import real_ladybug as lb

    import graph_read

    db = _fixture_db(tmp_path)
    first = graph_read.read_map(db)

    conn = lb.Connection(lb.Database(str(db)))
    conn.execute("MATCH (c:Concept) SET c.centrality_score = 0.5")
    conn.close()

    second = graph_read.read_map(db)
    assert second["topology_version"] == first["topology_version"]
    assert {n["id"]: (n["x"], n["y"]) for n in first["nodes"]} == \
           {n["id"]: (n["x"], n["y"]) for n in second["nodes"]}


def test_adding_a_node_does_not_move_the_rest_of_the_map(tmp_path):
    """The map is a place the operator learns. A commit inserts material next to
    where it belongs; it does not renumber everything else. Before the ordering
    ledger persisted slots, one added node moved the average node 184 units."""
    import gc

    import real_ladybug as lb

    import graph_read

    db = _fixture_db(tmp_path)
    before = {n["id"]: (n["x"], n["y"]) for n in graph_read.read_map(db)["nodes"]}
    gc.collect()

    busiest = max(before)
    database = lb.Database(str(db))
    conn = lb.Connection(database)
    conn.execute(
        "CREATE (c:Concept {id: 'zz_new_rule', label: 'New rule', "
        "text_content: '', semantic_anchor: '', embedding: $e, token_count: 0, "
        "centrality_score: 0.0, is_metanode: false, linked_graph_id: ''})",
        {"e": [0.0] * 3072},
    )
    conn.execute(
        "MATCH (a:Concept {id: $p}), (b:Concept {id: 'zz_new_rule'}) "
        "CREATE (a)-[:CONTAINS]->(b)", {"p": busiest}
    )
    del conn, database
    gc.collect()

    after_map = graph_read.read_map(db)
    after = {n["id"]: (n["x"], n["y"]) for n in after_map["nodes"]}
    assert "zz_new_rule" in after

    moved = [nid for nid, xy in before.items() if after.get(nid) != xy]
    # Ancestors of the insertion re-centre over their widened child span. That
    # is honest movement; a reshuffle of the whole map is not.
    assert len(moved) <= 4, f"too much of the map moved: {moved}"
    assert after_map["layout_delta"] is not None


def test_lenses_are_offered_and_keep_separate_ledgers(tmp_path):
    """Slots mean different things in a containment tree and a causal layering,
    so a shared ledger would make switching lenses and back reshuffle the map."""
    import gc

    import graph_read

    db = _fixture_db(tmp_path)
    canonical = graph_read.read_map(db)
    assert canonical["lens"] == "canonical"
    assert "causal" in canonical["available_lenses"]
    gc.collect()

    causal = graph_read.read_map(db, "causal")
    assert causal["lens"] == "causal"
    causal_pos = {n["id"]: (n["x"], n["y"]) for n in causal["nodes"]}
    assert causal_pos != {n["id"]: (n["x"], n["y"]) for n in canonical["nodes"]}
    gc.collect()

    # Going back gets the operator the same map they left.
    again = graph_read.read_map(db)
    assert {n["id"]: (n["x"], n["y"]) for n in again["nodes"]} == \
           {n["id"]: (n["x"], n["y"]) for n in canonical["nodes"]}
    gc.collect()

    # An unknown lens falls back rather than costing the operator their map.
    assert graph_read.read_map(db, "no-such-lens")["lens"] == "canonical"


def test_an_inapplicable_lens_falls_back_rather_than_drawing_a_tray(tmp_path):
    """`causal` is a real name. On a containment tree it has nothing to say,
    and arranging it anyway is the broken-control case `applicable_lenses`
    exists to prevent. The map read must fall back, not just hide the button.
    """
    import graph_read

    nodes = [{"id": "root"}] + [{"id": f"c{i:02d}"} for i in range(15)]
    edges = [{"source": "root", "target": f"c{i:02d}", "type": "CONTAINS",
              "label": ""} for i in range(15)]
    layout = graph_read.load_or_build_layout(
        tmp_path / "tree.lbug", "topo-tree", nodes, edges, "causal")
    assert layout["lens"] == "canonical"


def test_isolated_nodes_go_to_the_gap_gutter(tmp_path):
    """Orphans are output, not noise — the honest gaps are the roadmap. They get
    a designed band instead of an accidental tail."""
    import graph_read

    m = graph_read.read_map(_fixture_db(tmp_path))
    # Isolation read off the edges rather than off a structural `orphan` role.
    # The map no longer ships roles, and this is the more direct statement of
    # the property anyway: a node no edge touches is what the gutter is for.
    touched = {e["source"] for e in m["edges"]} | {e["target"] for e in m["edges"]}
    orphans = {n["id"] for n in m["nodes"] if n["id"] not in touched}
    if orphans:
        assert orphans <= set(m["gutter"])


def test_tier_is_null_rather_than_leaf_when_it_cannot_be_computed(tmp_path):
    """An unmeasured node must not render as the smallest one — that would say
    "peripheral" about something we simply did not measure."""
    import graph_read

    flat = [{"is_metanode": False, "betweenness": None, "centrality_score": 0.0}
            for _ in range(4)]
    context = graph_read._tier_context(flat, measured=False)
    assert graph_read._tier(flat[0], context) is None
    assert graph_read._tier({"is_metanode": True}, context) == "landmark"


def test_tier_falls_back_to_degree_when_betweenness_separates_nothing(tmp_path):
    """`agreements` is 23 roots with a fan-out of two, so real betweenness is
    ~0 everywhere and absolute cut-offs made all 31 nodes `leaf` — a map with no
    hierarchy at all. The channel is chosen per graph."""
    import graph_read

    nodes = [{"is_metanode": False, "betweenness": 0.0,
              "centrality_score": s}
             for s in (1.0, 0.8, 0.4, 0.2, 0.1, 0.05)]
    context = graph_read._tier_context(nodes, measured=True)
    assert context["channel"] == "degree"
    tiers = [graph_read._tier(n, context) for n in nodes]
    assert "landmark" in tiers and "hub" in tiers and "leaf" in tiers


def test_layout_separates_nodes_and_puts_children_below_parents(tmp_path):
    """A tidy tree over the spanning forest: CONTAINS is the hierarchy of an SST
    graph, so a contained node sits below the thing that contains it."""
    import graph_read

    db = _fixture_db(tmp_path)
    m = graph_read.read_map(db)
    pos = {n["id"]: (n["x"], n["y"]) for n in m["nodes"]}

    assert len(set(pos.values())) > 1, "everything landed on one point"

    contains = [e for e in m["edges"] if e["type"] == "CONTAINS"]
    checked = 0
    for e in contains:
        if e["source"] in pos and e["target"] in pos:
            if pos[e["target"]][1] > pos[e["source"]][1]:
                checked += 1
    assert checked > 0, "no CONTAINS child was placed below its parent"


# ------------------------------------------------------------------- catalogue


def test_browser_cannot_name_a_path(tmp_path):
    """Ids are resolved against a server-owned catalogue. A path — absolute,
    relative or traversing — is simply not an id, so there is nothing to inject."""
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    cat = GraphCatalogue(db)

    assert cat.resolve(None) == db
    assert cat.resolve("current") == db
    for hostile in ("../../../etc/passwd", "/etc/passwd", "../current",
                    "current.lbug", "", "  ", "nope"):
        if hostile == "":
            continue  # empty means "the current graph", covered above
        assert cat.resolve(hostile) is None, f"resolved a path-ish id: {hostile!r}"


def test_catalogue_reports_counts_so_the_picker_can_say_what_a_graph_is(tmp_path):
    """Size on disk tells the operator nothing about whether a graph is worth
    opening; "14 nodes" does. An unreadable graph is still listed — hiding it
    would be a quieter lie than showing it without counts."""
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    graphs = tmp_path / "graphs"
    graphs.mkdir()
    (graphs / "broken.lbug").write_bytes(b"not a database")

    rows = {g["id"]: g for g in GraphCatalogue(db).list()}
    assert rows["current"]["node_count"] > 0
    assert rows["current"]["edge_count"] > 0
    assert "broken" in rows and rows["broken"]["node_count"] is None


def test_catalogue_reuses_counts_until_the_graph_file_changes(tmp_path, monkeypatch):
    """Shell and map consumers may list concurrently. Counting is cached by
    the graph's stat signature, while any actual file write invalidates it."""
    import graph_read
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    real_open = graph_read._open
    opened = 0

    def counted_open(path):
        nonlocal opened
        opened += 1
        return real_open(path)

    monkeypatch.setattr(graph_read, "_open", counted_open)
    catalogue = GraphCatalogue(db, library_dirs=[])

    first = catalogue.list()
    second = catalogue.list()
    assert first == second
    assert opened == 1

    stat = db.stat()
    os.utime(db, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    catalogue.list()
    assert opened == 2


def test_catalogue_lists_published_graphs_but_never_rejected_ones(tmp_path):
    """A `.rejected.lbug` is preserved for inspection and is NOT authoritative.
    Offering it as something to browse would present uncertified output as the
    graph."""
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    graphs = tmp_path / "graphs"
    graphs.mkdir()
    shutil.copy2(db, graphs / "published_one.lbug")
    shutil.copy2(db, graphs / "published_one.rejected.lbug")

    cat = GraphCatalogue(db)
    ids = {g["id"] for g in cat.list()}
    assert "published_one" in ids
    assert not any("rejected" in i for i in ids)
    assert cat.resolve("published_one.rejected") is None
    assert [g for g in cat.list() if g["is_current"]][0]["id"] == "current"


def test_catalogue_lists_ready_made_library_and_opens_a_local_graph(tmp_path):
    """The product entry has usable examples, and an explicit open command can
    add a graph outside those roots without making paths valid read ids."""
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    shutil.copy2(db, library / "ready_made.lbug")
    outside = tmp_path / "project" / "team_graph.lbug"
    outside.parent.mkdir()
    shutil.copy2(db, outside)

    cat = GraphCatalogue(db, library_dirs=[library])
    listed = {row["id"]: row for row in cat.list()}
    assert listed["ready_made"]["source"] == "example"
    assert listed["ready_made"]["node_count"] > 0

    opened = cat.open_path(str(outside))
    assert opened["graph"]["source"] == "opened"
    assert opened["workspace"]["directory"] == str(outside.parent)
    graph_id = opened["graph"]["id"]
    assert cat.resolve(graph_id) == outside
    assert cat.resolve(str(outside)) is None

    assert "error" in cat.open_path(str(tmp_path / "missing.lbug"))


def test_catalogue_finds_construction_output_below_the_top_of_its_tree(tmp_path):
    """A construction chooses where it lands; the catalogue has to follow it.

    Shallow globbing lost real work. The `graphs/graphs/` case is not
    hypothetical — `default_construction_out` documents itself as preventing
    that drift, it happened anyway, and the graph it produced carries a recorded
    construction origin, so the product built it, logged it, and could not then
    show it to anyone.
    """
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    runs = tmp_path / "construction_runs"
    (runs / "graphs" / "graphs").mkdir(parents=True)
    (runs / "trials" / "prose-workspace").mkdir(parents=True)
    shutil.copy2(db, runs / "top_level.lbug")
    shutil.copy2(db, runs / "graphs" / "graphs" / "drifted.lbug")
    shutil.copy2(db, runs / "trials" / "prose-workspace" / "graph.lbug")
    # Version history, not graphs to open, and there can be hundreds.
    snapshots = runs / "graphs" / "held.lbug.snapshots"
    snapshots.mkdir()
    shutil.copy2(db, snapshots / "0e17ad4a.lbug")
    # A rejected build is still refused, wherever it sits.
    shutil.copy2(db, runs / "graphs" / "attempt.rejected.lbug")

    cat = GraphCatalogue(db, library_dirs=[], output_roots=[runs])
    listed = {row["id"]: row for row in cat.list()}

    assert listed["top_level"]["source"] == "construction"
    assert listed["drifted"]["source"] == "construction"
    assert "0e17ad4a" not in listed
    assert "attempt.rejected" not in listed

    # A file named for nothing borrows the name of the workspace that made it,
    # or five trials all arrive called "Graph".
    assert listed["graph"]["label"] == "Prose Workspace"


def test_browse_lists_one_directory_and_grants_nothing_new(tmp_path):
    """Browsing is a convenience over `open_path`, not a new authority.

    A browser cannot tell a server where a file is — a native dialog yields a
    `File`, never a path — so the listing has to come from the host. That is
    only acceptable because every graph it names was already openable by typing
    the path, which is what the last two assertions pin.
    """
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    room = tmp_path / "room"
    room.mkdir()
    shutil.copy2(db, room / "kept.lbug")
    (room / "notes.md").write_text("not a graph", encoding="utf-8")
    (room / "deeper").mkdir()
    (room / ".hidden").mkdir()
    (room / "kept.lbug.snapshots").mkdir()

    cat = GraphCatalogue(db, library_dirs=[])
    listing = cat.browse(str(room))

    assert listing["path"] == str(room)
    assert [d["name"] for d in listing["directories"]] == ["deeper"]
    assert [g["name"] for g in listing["graphs"]] == ["kept.lbug"]
    assert listing["parent"] == str(tmp_path)

    # Naming a file is not opening it, and what it names is exactly what the
    # typed path already accepted.
    assert "error" not in cat.open_path(listing["graphs"][0]["path"])
    assert "error" in cat.browse(str(tmp_path / "nowhere"))


def test_catalogue_activates_only_after_owner_accepts_the_switch(tmp_path):
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    library = tmp_path / "library"
    library.mkdir()
    other = library / "other.lbug"
    shutil.copy2(db, other)
    accepted = []
    cat = GraphCatalogue(
        db,
        library_dirs=[library],
        on_activate=lambda path: accepted.append(path) or {"changed": True},
    )

    result = cat.activate("other")

    assert accepted == [other.resolve()]
    assert result["graph"]["is_current"] is True
    assert cat.resolve(None).resolve() == other.resolve()


# ------------------------------------------------------------------------ HTTP


def _app(db: Path):
    from mcp_server.graph_http import GraphCatalogue, graph_routes
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount

    inner = Starlette(routes=[Mount("/graph", routes=graph_routes(GraphCatalogue(db)))])

    async def gate(scope, receive, send):
        from mcp_server.http import _authorized

        if scope["type"] == "http" and not _authorized(scope.get("headers") or [], TOKEN):
            await Response("unauthorized", status_code=401)(scope, receive, send)
            return
        await inner(scope, receive, send)

    return gate


def test_graph_routes_are_gated_and_serve_the_map(tmp_path):
    db = _fixture_db(tmp_path)
    client = TestClient(_app(db))

    assert client.get("/graph/map").status_code == 401
    assert client.get("/graph/graphs").status_code == 401

    r = client.get("/graph/map", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["graph_id"] == "current"
    assert body["node_count"] == len(body["nodes"])

    listed = client.get("/graph/graphs", headers=AUTH).json()["graphs"]
    assert [g["id"] for g in listed] == ["current"]

    assert client.get("/graph/map?graph=../../etc/passwd", headers=AUTH).status_code == 404
    assert client.get("/graph/map?graph=nope", headers=AUTH).status_code == 404


def test_graph_node_route_pages_body(tmp_path):
    db = _fixture_db(tmp_path)
    client = TestClient(_app(db))
    node_id = client.get("/graph/map", headers=AUTH).json()["nodes"][0]["id"]

    missing = client.get("/graph/node", headers=AUTH)
    assert missing.status_code == 400

    unknown = client.get("/graph/node", params={"id": "nope"}, headers=AUTH)
    assert unknown.status_code == 404

    r = client.get("/graph/node", params={"id": node_id}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == node_id
    assert "text_content" in body
    assert "embedding" not in body
    assert client.get("/graph/node", params={"id": node_id}).status_code == 401


# ------------------------------------------------------- cold-read degradation


def test_structural_index_is_cached_so_the_cost_is_paid_once(tmp_path):
    """Brandes is O(V*E) in pure Python — seconds on a few thousand nodes. The
    map read used the engine's sidecar but never wrote one, so any graph the
    engine had not opened first paid that on EVERY page load."""
    import graph_read

    db = _fixture_db(tmp_path)
    idx = db.with_suffix(".lbug.idx")
    idx.unlink(missing_ok=True)

    graph_read.read_map(db)
    assert idx.exists(), "structural index was computed and thrown away"

    data = json.loads(idx.read_text())
    assert data["node_count"] == graph_read.read_map(db)["node_count"]


def test_large_cold_graph_skips_betweenness_and_says_so(tmp_path, monkeypatch):
    """A first open must not block for a minute on chrome. Above the threshold
    betweenness is skipped — and reported as null, never 0.0, because "not
    measured" and "not central" are different claims and node size depends on
    which one it is."""
    import graph_read

    db = _fixture_db(tmp_path)
    db.with_suffix(".lbug.idx").unlink(missing_ok=True)
    monkeypatch.setattr(graph_read, "LARGE_GRAPH_NODES", 1)  # force the large path

    m = graph_read.read_map(db)
    assert m["structural_mode"] == "fast"
    assert all(n["betweenness"] is None for n in m["nodes"])
    # The map still arrives — skipping Brandes costs the sizing channel, not the
    # map. (This used to also assert roles survived the fast path; the read no
    # longer emits them at all.)
    assert m["nodes"] and m["edges"]


def test_small_graph_reports_measured_betweenness(tmp_path):
    import graph_read

    db = _fixture_db(tmp_path)
    db.with_suffix(".lbug.idx").unlink(missing_ok=True)
    m = graph_read.read_map(db)
    assert m["structural_mode"] == "full"
    assert all(isinstance(n["betweenness"], float) for n in m["nodes"])


def test_catalogue_finds_constructed_graphs_below_the_top_of_their_tree(tmp_path):
    """A construction picks its own workspace; the catalogue follows it there.

    Every path here is one this repository actually produced: a per-trial
    workspace whose file is named `graph.lbug`, and the `graphs/graphs/` drift
    that `default_construction_out` documents itself as preventing. Under a
    shallow scan both were invisible, so work the product had built and logged
    could not be reopened from the product.
    """
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    runs = tmp_path / "construction_runs"
    trials = tmp_path / "construction_trials"
    for relative in (
        "graphs/one.lbug",
        "graphs/graphs/drifted.lbug",
        "graphs/one.lbug.snapshots/deadbeef.lbug",
    ):
        target = runs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db, target)
    for trial in ("prose-workspace", "code-workspace"):
        target = trials / trial / "graph.lbug"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db, target)

    cat = GraphCatalogue(db, library_dirs=[], output_roots=[runs, trials])
    listed = {row["label"]: row for row in cat.list()}

    assert "One" in listed and "Drifted" in listed
    assert listed["One"]["source"] == "construction"
    # A generic file name borrows the workspace, or both trials read as "Graph".
    assert "Prose Workspace" in listed and "Code Workspace" in listed
    # Version history is not a shelf of graphs to open.
    assert not any(row["workspace_name"].endswith(".lbug.snapshots") for row in cat.list())


def test_catalogue_does_not_crawl_arbitrarily_deep(tmp_path):
    """Bounded, so an output root that grows a research tree stays a catalogue."""
    from mcp_server.graph_http import GraphCatalogue

    db = _fixture_db(tmp_path)
    runs = tmp_path / "construction_runs"
    deep = runs / "a" / "b" / "c" / "d" / "buried.lbug"
    deep.parent.mkdir(parents=True)
    shutil.copy2(db, deep)

    cat = GraphCatalogue(db, library_dirs=[], output_roots=[runs])

    assert "Buried" not in {row["label"] for row in cat.list()}
