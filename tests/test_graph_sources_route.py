"""`GET /graph/sources` — the node-to-passage join and the coverage view.

Two shapes, one route: with `?id=` it answers "what was this node built
from"; without, "which source units produced nothing". Both rest on the
sidecar, and both have a failure mode worth pinning — an empty list that
means "cannot show" being read as "there is nothing".
"""

from __future__ import annotations

import real_ladybug as lb
from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_server.graph_http import GraphCatalogue, graph_routes
from source_pipeline.sources_sidecar import write_sidecar
from source_pipeline.workbook import Atom


def _graph_with_nodes(path, rows):
    """rows: [(node_id, [unit ids])]"""
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
            f"CREATE REL TABLE {rel} (FROM Concept TO Concept, label STRING DEFAULT NULL)")
    for node_id, units in rows:
        listed = ", ".join(f"'{u}'" for u in units)
        conn.execute(
            f"CREATE (:Concept {{id: '{node_id}', label: '{node_id}', "
            f"semantic_anchor: '', text_content: 'body of {node_id}', "
            f"token_count: 3, centrality_score: 0.1, is_metanode: false, "
            f"linked_graph_id: '', kind: 'claim', "
            f"source_unit_ids: [{listed}]}})"
        )
    conn.close()


def _atom(aid, text):
    return Atom(atom_id=aid, source_id="src", unit_id=aid.split("@")[0],
                text=text, start=0, end=len(text), locator=aid.split("@")[0],
                heading_path=("Section",))


def _client(db):
    app = Starlette(routes=graph_routes(GraphCatalogue(db, library_dirs=[]),
                                        current_surface=None))
    return TestClient(app)


def test_a_node_resolves_to_the_passage_it_was_built_from(tmp_path):
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:1@whole"])])
    write_sidecar(db, [_atom("src#u:1@whole", "The passage behind claim A.")],
                  source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources", params={"id": "claim:a"}).json()

    assert body["available"] is True
    assert body["cited_unit_ids"] == ["src#u:1@whole"]
    assert "passage behind claim A" in body["units"][0]["excerpt"]
    assert body["unresolved_unit_ids"] == []


def test_a_cited_unit_the_sidecar_lacks_is_named_not_dropped(tmp_path):
    """A short list that looks complete is the failure being avoided."""
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:1@whole", "src#u:gone@whole"])])
    write_sidecar(db, [_atom("src#u:1@whole", "Only this one survived.")],
                  source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources", params={"id": "claim:a"}).json()

    assert len(body["units"]) == 1
    assert body["unresolved_unit_ids"] == ["src#u:gone@whole"]


def test_coverage_names_the_units_that_produced_nothing(tmp_path):
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [
        ("claim:a", ["src#u:1@whole"]),
        ("claim:b", ["src#u:4@whole"]),
    ])
    write_sidecar(db, [_atom(f"src#u:{i}@whole", f"Unit {i}.") for i in (1, 2, 3, 4)],
                  source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources").json()

    assert body["unit_count"] == 4
    assert body["produced_count"] == 2
    produced = {r["unit_id"]: r["produced"] for r in body["units"]}
    assert produced == {
        "src#u:1@whole": True, "src#u:2@whole": False,
        "src#u:3@whole": False, "src#u:4@whole": True,
    }
    assert [r["unit_id"] for r in body["units"]] == [
        "src#u:1@whole", "src#u:2@whole", "src#u:3@whole", "src#u:4@whole"
    ], "document order lost; a run of misses is no longer distinguishable"


def test_coverage_says_which_nodes_a_unit_produced(tmp_path):
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [
        ("claim:a", ["src#u:1@whole"]),
        ("claim:b", ["src#u:1@whole"]),
    ])
    write_sidecar(db, [_atom("src#u:1@whole", "One unit, two claims.")],
                  source_fingerprint="fp")

    with _client(db) as client:
        row = client.get("/sources").json()["units"][0]

    assert sorted(row["node_ids"]) == ["claim:a", "claim:b"]


def test_a_graph_without_a_sidecar_says_so_rather_than_returning_empty(tmp_path):
    """"Cannot show sources" and "sources produced nothing" are opposite facts.

    An empty list says the second. Every graph built before sidecars existed
    is in the first state, so this is the common case, not the edge one.
    """
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:1@whole"])])

    with _client(db) as client:
        body = client.get("/sources").json()

    assert body["available"] is False
    assert body["units"] == []
    assert "sidecar" in body["reason"]


# --- chrome, which `atoms coverage` has always separated ----------------


def _chrome_atom(aid, text):
    a = _atom(aid, text)
    return Atom(atom_id=a.atom_id, source_id=a.source_id, unit_id=a.unit_id,
                text=a.text, start=a.start, end=a.end, locator=a.locator,
                heading_path=a.heading_path, chrome=True)


def test_boilerplate_is_not_counted_as_a_substantive_miss(tmp_path):
    """A hundred ignored page footers bury the one long passage that matters."""
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:1@whole"])])
    write_sidecar(db, [
        _atom("src#u:1@whole", "A passage that produced a claim."),
        _atom("src#u:2@whole", "A long unproduced passage. " * 40),
        _chrome_atom("src#u:3@whole", "Page 4"),
        _chrome_atom("src#u:4@whole", "Preprint. Under review."),
    ], source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources").json()

    assert body["missed_by_size"] == ["src#u:2@whole"], (
        "chrome is being reported as a substantive miss"
    )
    rows = {r["unit_id"]: r for r in body["units"]}
    assert rows["src#u:3@whole"]["chrome"] is True
    assert rows["src#u:2@whole"]["chrome"] is False


def test_boilerplate_that_produced_a_node_is_flagged(tmp_path):
    """The inverse view: this is how a running header becomes a character."""
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:3@whole"])])
    write_sidecar(db, [
        _atom("src#u:1@whole", "Real prose that produced nothing."),
        _chrome_atom("src#u:3@whole", "Preprint. Under review."),
    ], source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources").json()

    assert body["chrome_that_produced"] == ["src#u:3@whole"]


def test_misses_are_ranked_by_size(tmp_path):
    """One ignored 6,000-character passage is a real miss; a one-line atom is
    usually not. Only size ordering shows the difference."""
    db = tmp_path / "g.lbug"
    _graph_with_nodes(db, [("claim:a", ["src#u:0@whole"])])
    write_sidecar(db, [
        _atom("src#u:0@whole", "produced"),
        _atom("src#u:1@whole", "tiny"),
        _atom("src#u:2@whole", "medium " * 30),
        _atom("src#u:3@whole", "large " * 200),
    ], source_fingerprint="fp")

    with _client(db) as client:
        body = client.get("/sources").json()

    assert body["missed_by_size"] == [
        "src#u:3@whole", "src#u:2@whole", "src#u:1@whole"]
