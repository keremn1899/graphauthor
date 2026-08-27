"""`state` and `POST /graph/publish` — which surface a graph belongs on.

The product used to answer this from the directory a file happened to sit in.
That is not a decision anyone made, so it could not be changed by anyone
either: a construction stayed a construction forever. `state` is the recorded
half — a marker file beside the graph — and these tests pin the two things
that make it worth having over the old `source` tag.

**It survives the graph being open.** `source` reports discovery, and the
process's own graph is discovered as `current` wherever it lives. A list
filtered on `source` therefore loses a construction at the exact moment
someone is looking at it.

**It goes both ways.** Publishing is withdrawable, because a graph coming back
for another cut is the normal case, not an error path.
"""

from __future__ import annotations

import json

import real_ladybug as lb

import graph_read
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_server.graph_http import GraphCatalogue, graph_routes


def _graph(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = lb.Connection(lb.Database(str(path)))
    conn.execute(
        "CREATE NODE TABLE Concept (id STRING, label STRING, "
        "semantic_anchor STRING, text_content STRING, embedding FLOAT[3072], "
        "token_count INT64, centrality_score DOUBLE, is_metanode BOOLEAN, "
        "linked_graph_id STRING, kind STRING, source_unit_ids STRING[], "
        "PRIMARY KEY (id))"
    )
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(
            f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)"
        )
    conn.execute(
        "CREATE (:Concept {id: 'a', label: 'A', semantic_anchor: '', "
        "text_content: 'a', token_count: 1, centrality_score: 0.1, "
        "is_metanode: false, linked_graph_id: '', kind: 'claim', "
        "source_unit_ids: ['u1']})"
    )
    conn.close()
    del conn
    return path


def _client(tmp_path, *, current=None):
    built = _graph(tmp_path / "runs" / "trial-one" / "graph.lbug")
    shelf = _graph(tmp_path / "library" / "bundled.lbug")
    catalogue = GraphCatalogue(
        db_path=current or (tmp_path / "unopened.lbug"),
        output_roots=[tmp_path / "runs"],
        library_dirs=[tmp_path / "library"],
    )
    app = Starlette(routes=[])
    for route in graph_routes(catalogue):
        app.routes.append(route)
    return TestClient(app), catalogue, built, shelf


def _rows(client):
    return {row["label"]: row for row in client.get("/graphs").json()["graphs"]}


def test_a_construction_output_starts_in_construction(tmp_path):
    client, _cat, _built, _shelf = _client(tmp_path)
    rows = _rows(client)
    assert rows["Trial One"]["state"] == "construction"


def test_a_library_graph_is_not_on_this_axis_at_all(tmp_path):
    """Empty is a third answer, not a synonym for unpublished.

    A bundled example has nobody to review it and nothing to publish. Calling
    it "unpublished" would put it in a queue it can never leave.
    """
    client, _cat, _built, _shelf = _client(tmp_path)
    assert _rows(client)["Bundled"]["state"] == ""


def test_publishing_moves_it_and_withdrawing_brings_it_back(tmp_path):
    client, _cat, _built, _shelf = _client(tmp_path)
    graph_id = _rows(client)["Trial One"]["id"]

    published = client.post("/publish", json={"graph_id": graph_id})
    assert published.status_code == 200, published.text
    assert published.json()["state"] == "published"
    assert _rows(client)["Trial One"]["state"] == "published"

    withdrawn = client.post(
        "/publish", json={"graph_id": graph_id, "published": False}
    )
    assert withdrawn.json()["state"] == "construction"
    assert _rows(client)["Trial One"]["state"] == "construction"


def test_state_survives_the_graph_being_the_open_one(tmp_path):
    """The positive control for the whole design.

    `source` flips to `current` here — that is the bug this replaces, and
    asserting it keeps the test honest about what would have happened.
    """
    client, _cat, _built, _shelf = _client(
        tmp_path, current=tmp_path / "runs" / "trial-one" / "graph.lbug"
    )
    row = next(
        r for r in client.get("/graphs").json()["graphs"] if r["is_current"]
    )
    assert row["source"] == "current"
    assert row["state"] == "construction"


def test_a_graph_no_construction_produced_cannot_be_published(tmp_path):
    client, _cat, _built, _shelf = _client(tmp_path)
    graph_id = _rows(client)["Bundled"]["id"]
    refused = client.post("/publish", json={"graph_id": graph_id})
    assert refused.json().get("kind") == "invalid"
    assert "was not built under this workspace" in refused.json()["error"]


def test_publishing_an_unknown_graph_is_a_miss_not_a_crash(tmp_path):
    client, _cat, _built, _shelf = _client(tmp_path)
    missed = client.post("/publish", json={"graph_id": "no-such-graph"})
    assert missed.json().get("kind") == "not_found"


def test_the_marker_records_the_shape_that_was_approved(tmp_path):
    """The one fact that cannot be recovered after a rebuild.

    Deliberately `topology_version` and not `graph_version`: the latter hashes
    size and mtime, and `compute_structural_index` writes `centrality_score`
    back on every cold read — so a graph would report itself as changed merely
    because somebody listed the catalogue. The positive control below is that
    the two disagree on exactly that.
    """
    client, _cat, built, _shelf = _client(tmp_path)
    graph_id = _rows(client)["Trial One"]["id"]
    client.post("/publish", json={"graph_id": graph_id})

    marker = json.loads(
        built.with_name(built.name + ".published.json").read_text()
    )
    recorded = marker["published_topology_version"]
    assert recorded, "nothing was recorded about what was approved"

    conn = graph_read._open(built)
    try:
        live = graph_read.topology_version(
            graph_read.read_nodes(conn), graph_read.read_edges(conn)
        )
    finally:
        conn.close()
        del conn
    assert live == recorded


def test_reading_the_graph_does_not_look_like_a_change(tmp_path):
    """The positive control for choosing topology over file identity.

    Opening a graph rewrites it here, so `graph_version` moves on a read. If
    the marker had pinned that, every published graph would report drift after
    the first listing.
    """
    client, _cat, built, _shelf = _client(tmp_path)
    before_file = graph_read.graph_version(built)
    conn = graph_read._open(built)
    try:
        nodes, edges = graph_read.read_nodes(conn), graph_read.read_edges(conn)
        topo = graph_read.topology_version(nodes, edges)
    finally:
        conn.close()
        del conn
    client.get("/graphs")  # the catalogue opens every graph to count it

    conn = graph_read._open(built)
    try:
        after_topo = graph_read.topology_version(
            graph_read.read_nodes(conn), graph_read.read_edges(conn)
        )
    finally:
        conn.close()
        del conn
    assert after_topo == topo
    assert graph_read.graph_version(built) != before_file, (
        "if file identity no longer moves on a read, the marker could pin it "
        "and this test is protecting nothing"
    )


def test_the_two_surfaces_are_complements(tmp_path):
    """Every graph is on exactly one shelf.

    The Graph surface shows `state !== "construction"`; Constructions shows
    `state === "construction"`. Those are complements by construction, and the
    filters live in one component with a `constructionMode` flag — so a typo on
    one side would show a graph twice or lose it entirely, and no frontend test
    runner exists to catch it. Pinned on the payload instead.
    """
    client, _cat, _built, _shelf = _client(tmp_path)
    rows = client.get("/graphs").json()["graphs"]
    assert rows, "nothing to partition"

    for row in rows:
        assert row["state"] in ("construction", "published", ""), row["state"]
    in_construction = [r["id"] for r in rows if r["state"] == "construction"]
    on_graph = [r["id"] for r in rows if r["state"] != "construction"]
    assert set(in_construction) & set(on_graph) == set()
    assert len(in_construction) + len(on_graph) == len(rows)
    assert in_construction and on_graph, (
        "a fixture with only one shelf populated cannot show a partition"
    )


def test_the_marker_is_a_file_beside_the_graph(tmp_path):
    """Pinned because it is what makes the state travel with the graph.

    A row in a database on the operator's machine would be lost the moment
    someone copied the workspace somewhere else, which for a directory-shaped
    product is the ordinary way work moves.
    """
    client, _cat, built, _shelf = _client(tmp_path)
    graph_id = _rows(client)["Trial One"]["id"]
    client.post("/publish", json={"graph_id": graph_id})
    marker = built.with_name(built.name + ".published.json")
    assert marker.exists()
    assert "published_at" in marker.read_text()


def test_a_workspace_reached_through_a_symlink_is_still_a_construction(tmp_path):
    """Found on the real catalogue, not imagined.

    A workspace shelf is routinely a symlink, and one of the five here points
    into a different checkout of this project. Resolving the path before
    testing containment said that graph was not a construction while the row
    above it, discovered the same way, said it was.
    """
    elsewhere = tmp_path / "elsewhere" / "deep" / "run"
    _graph(elsewhere / "graph.lbug")
    shelf = tmp_path / "runs" / "linked"
    shelf.parent.mkdir(parents=True, exist_ok=True)
    shelf.symlink_to(elsewhere, target_is_directory=True)

    catalogue = GraphCatalogue(
        db_path=tmp_path / "unopened.lbug", output_roots=[tmp_path / "runs"]
    )
    app = Starlette(routes=[])
    for route in graph_routes(catalogue):
        app.routes.append(route)
    rows = _rows(TestClient(app))
    assert rows["Linked"]["state"] == "construction"
