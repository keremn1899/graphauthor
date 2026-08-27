from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from mcp_server.graph_http import GraphCatalogue, graph_routes


class _Surface:
    def __init__(self, path):
        self._db_path = path
        self.calls: list[tuple] = []

    def orient(self, context="graph_card"):
        self.calls.append(("orient", context))
        return {"graph_id": "g", "context_view": context, "capabilities": ["read"]}

    # Signature tracks the real Surface: the transport calls positionally, so a
    # double that lags its producer fails as a 503 naming nothing useful.
    def what_governs(self, question, explain=False, as_of=None):
        self.calls.append(("what_governs", question, explain, as_of))
        return {"status": "UNGOVERNED", "ungoverned_predicate": question}

    def check_conformance(self, **kwargs):
        self.calls.append(("check_conformance", kwargs))
        return {"kind": "UNGOVERNED", "receipt": {"graph_version": "v1"}}

    def run_traversal(
        self,
        name,
        parameters,
        *,
        version=None,
        evidence="packet",
        graph_version="",
        explain=False,
    ):
        self.calls.append(
            (
                "run_traversal",
                name,
                parameters,
                version,
                evidence,
                graph_version,
                explain,
            )
        )
        return {
            "kind": "NAMED_TRAVERSAL",
            "outcome": "FOUND",
            "graph_version": "gv_test",
            "evidence": {"node_records": [{"id": "topic:test"}]},
            "execution_receipt": {"recipe_name": name},
        }


def _client(tmp_path):
    db = tmp_path / "g.lbug"
    db.touch()
    surface = _Surface(db)
    app = Starlette(
        routes=graph_routes(GraphCatalogue(db, library_dirs=[]), current_surface=surface)
    )
    return TestClient(app), surface


def test_graph_http_exposes_orientation_without_write_authority(tmp_path):
    client, surface = _client(tmp_path)
    with client:
        response = client.get("/orient", params={"graph": "g", "context": "capabilities"})
    assert response.status_code == 200
    assert response.json()["context_view"] == "capabilities"
    assert surface.calls == [("orient", "capabilities")]


def test_graph_http_exposes_coverage_space_verbatim(tmp_path):
    client, surface = _client(tmp_path)
    with client:
        response = client.post(
            "/what-governs",
            json={"graph_id": "g", "question": "Who owns retries?", "explain": True},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "UNGOVERNED"
    assert surface.calls == [("what_governs", "Who owns retries?", True, None)]


def test_graph_http_exposes_diff_conformance_without_proposal_verbs(tmp_path):
    client, surface = _client(tmp_path)
    with client:
        response = client.post(
            "/check-conformance",
            json={
                "graph_id": "g",
                "diff": "diff --git a/a.py b/a.py",
                "prior_diff_receipts": [{"graph_version": "v0"}],
            },
        )
    assert response.status_code == 200
    assert response.json()["kind"] == "UNGOVERNED"
    assert surface.calls[0][0] == "check_conformance"
    assert surface.calls[0][1]["diff"].startswith("diff --git")
    route_paths = {route.path for route in client.app.routes}
    assert "/propose" not in route_paths
    assert "/confirm" not in route_paths


def test_graph_http_runs_named_traversal_and_returns_receipt(tmp_path):
    client, surface = _client(tmp_path)
    with client:
        response = client.post(
            "/run-traversal",
            json={
                "graph_id": "g",
                "name": "prepare_topic_edit",
                "version": 1,
                "parameters": {"topic_id": "topic:test"},
                "graph_version": "gv_test",
            },
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "FOUND"
    assert response.json()["execution_receipt"]["recipe_name"] == "prepare_topic_edit"
    assert surface.calls == [
        (
            "run_traversal",
            "prepare_topic_edit",
            {"topic_id": "topic:test"},
            1,
            "packet",
            "gv_test",
            False,
        )
    ]


def test_graph_http_query_validation_is_typed(tmp_path):
    client, _surface = _client(tmp_path)
    with client:
        assert client.post("/what-governs", json={"graph_id": "g"}).status_code == 400
        assert client.post("/check-conformance", json={"graph_id": "g"}).status_code == 400
        assert client.post("/run-traversal", json={"graph_id": "g"}).status_code == 400
        assert client.get("/orient", params={"graph": "missing"}).status_code == 404
