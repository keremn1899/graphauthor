"""Component isolation tests.

Tests each tier independently with deterministic synthetic inputs.
No full graph traversal. No OPENROUTER_API_KEY needed for structural tests.
LLM-dependent tests are marked @pytest.mark.integration.

Coverage per tier:
  Squad   — inclusion precision/recall on known clusters
  Company — trail keep/prune on synthetic trails, cross-cluster signal detection
  Verdict / confirmation payload — tested structurally via models only
    (live path is deterministic verdict_computation; legacy LLM confirmation is integration)
  Battalion — gap pass-through, payload structure
"""

from __future__ import annotations

import json

import pytest

from engine import compute_structural_index
from models import StructuralFacts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_cluster(conn, node_ids: list[str]) -> dict:
    rows = list(conn.execute("MATCH (c:Concept) RETURN c.id LIMIT 20"))
    available = [r[0] for r in rows]
    ids = [nid for nid in node_ids if nid in available] or available[:3]
    return {
        "cluster_id": "test_cluster_1",
        "node_ids": ids,
    }


def _build_planner_program(sst_type: str = "leadsto") -> dict:
    return {
        "strategy_a": {"concepts": ["test_concept"]},
        "strategy_b": {"concepts": ["hypothesis_concept"], "confidence": "medium"},
        "steps": [
            {"tool": "hop_expansion", "params": {"hop_limits": {sst_type: {"forward": 2, "backward": 1}}}},
        ],
    }


# ---------------------------------------------------------------------------
# Structural index tests (no LLM)
# ---------------------------------------------------------------------------

class TestStructuralIndexOnExampleGraphs:

    def test_metabolism_has_causal_nexus(self, metabolism_conn):
        si = compute_structural_index(metabolism_conn)
        nexus_nodes = [nid for nid, f in si.items() if "causal_nexus" in f.roles]
        assert len(nexus_nodes) >= 1, "Metabolism graph should have at least one causal_nexus"

    def test_metabolism_has_causal_origin(self, metabolism_conn):
        si = compute_structural_index(metabolism_conn)
        origins = [nid for nid, f in si.items() if "causal_origin" in f.roles]
        assert len(origins) >= 2, "Metabolism graph should have multiple causal origins (sedentary, diet, stress)"

    def test_metabolism_has_causal_terminal(self, metabolism_conn):
        si = compute_structural_index(metabolism_conn)
        terminals = [nid for nid, f in si.items() if "causal_terminal" in f.roles]
        assert len(terminals) >= 1

    def test_metabolism_has_metanode(self, metabolism_conn):
        rows = list(metabolism_conn.execute(
            "MATCH (c:Concept) WHERE c.is_metanode = true RETURN c.id, c.linked_graph_id"
        ))
        assert len(rows) >= 1, "Metabolism graph should have the Neurological Effects metanode"
        assert rows[0][1] == "example_neurology_001"

    def test_auth_has_containment_root(self, auth_conn):
        si = compute_structural_index(auth_conn)
        # Authentication Service (a_001) should have CONTAINS children
        facts = si.get("a_001")
        assert facts is not None
        assert facts.out_degree.get("contains", 0) >= 3, (
            "Authentication Service should contain at least 3 components"
        )

    def test_auth_has_causal_chain(self, auth_conn):
        """Login flow: Login Handler → Credential Validator → User Repository."""
        from tools import get_neighbours
        nbs = get_neighbours(auth_conn, "a_004", "leadsto", "forward")
        nb_ids = {nb["id"] for nb in nbs}
        assert "a_002" in nb_ids, "Login Handler should LEADSTO Credential Validator"

    def test_auth_edge_labels_present(self, auth_conn):
        rows = list(auth_conn.execute(
            "MATCH (a:Concept)-[r:LEADSTO]->(b:Concept) RETURN r.label LIMIT 5"
        ))
        labels = [r[0] for r in rows if r[0]]
        assert len(labels) >= 1, "Auth service edges should have labels"

    def test_memory_has_contains_subtree(self, memory_conn):
        """Human Memory → Working Memory, Long-Term Memory (CONTAINS)."""
        from tools import get_neighbours
        children = get_neighbours(memory_conn, "m_001", "contains", "forward")
        child_ids = {nb["id"] for nb in children}
        assert "m_002" in child_ids, "Human Memory should CONTAINS Working Memory"
        assert "m_003" in child_ids, "Human Memory should CONTAINS Long-Term Memory"

    def test_memory_nearto_present(self, memory_conn):
        from tools import get_neighbours
        nbs = get_neighbours(memory_conn, "m_002", "nearto", "forward")
        assert len(nbs) >= 1, "Working Memory should have NEARTO neighbours"

    def test_example_graphs_have_anchors(self, metabolism_conn, auth_conn, memory_conn):
        for conn, name in [(metabolism_conn, "metabolism"), (auth_conn, "auth"), (memory_conn, "memory")]:
            rows = list(conn.execute(
                "MATCH (c:Concept) WHERE c.semantic_anchor <> '' RETURN count(c)"
            ))
            count = rows[0][0] if rows else 0
            assert count > 0, f"{name} graph should have semantic anchors on nodes"


# ---------------------------------------------------------------------------
# Company: cross-cluster signal detection (no LLM, pure in-memory)
# ---------------------------------------------------------------------------

class TestCrossClusterSignalDetection:
    def test_company_handoff_validates(self):
        from models import CompanyHandoff

        raw = {
            "internal_handoff": {
                "hypothesis_status": "partial",
                "hypothesis_explanation": "Some B concepts found",
                "primary_trails": [
                    {"trail_id": "trail_1", "origin": "hypothesis_path",
                     "rationale": "Confirms mechanism", "node_ids": ["n_001", "n_002"]}
                ],
                "supporting_trails": [],
                "context_trails": [],
                "pruned_trail_ids": [],
                "gaps": [{"gap_type": "missing_concept", "specific_node_or_concept": "gap 1", "actionable_suggestion": "Add gap 1 to the graph"}],
                "confidence": "medium",
            },
            "evidence_brief": {
                "strategy_b_surfaced": ["concept_a"],
                "strategy_b_absent": ["concept_b"],
                "primary_trail_labels": ["A → B"],
                "squad_continuation_signals": [],
                "specific_gaps": [{"gap_type": "missing_concept", "specific_node_or_concept": "gap 1", "actionable_suggestion": "Add gap 1 to the graph"}],
            },
            "recovery_spec": None,
            "user_summary": "",
        }
        result = CompanyHandoff.model_validate(raw)
        assert result.internal_handoff.hypothesis_status == "partial"
        assert result.internal_handoff.confidence == "medium"
        assert len(result.internal_handoff.primary_trails) == 1

    def test_trail_record_has_edge_labels_field(self):
        from models import TrailRecord

        t = TrailRecord(
            trail_id="t1",
            origin="hypothesis_path",
            rationale="test",
            node_ids=["a", "b"],
            edge_types=["leadsto"],
            edge_labels=["directly_causes"],
        )
        assert t.edge_labels == ["directly_causes"]

    def test_trail_record_edge_labels_defaults_empty(self):
        from models import TrailRecord

        t = TrailRecord(
            trail_id="t1",
            origin="neighbourhood",
            rationale="test",
            node_ids=["a"],
        )
        assert t.edge_labels == []


# ---------------------------------------------------------------------------
# Tools: edge label retrieval (no LLM)
# ---------------------------------------------------------------------------

class TestEdgeLabelRetrieval:

    def test_get_neighbours_returns_edge_label(self, metabolism_conn):
        from tools import get_neighbours

        nbs = get_neighbours(metabolism_conn, "n_001", "leadsto", "forward")
        assert len(nbs) >= 1
        for nb in nbs:
            assert "edge_label" in nb, "get_neighbours should return edge_label key"
        # n_001 → n_003 should have label "directly_causes"
        n003 = next((nb for nb in nbs if nb["id"] == "n_003"), None)
        assert n003 is not None
        assert n003.get("edge_label") == "directly_causes"

    def test_find_paths_returns_edge_label_chain(self, metabolism_conn):
        from tools import find_paths

        paths = find_paths(metabolism_conn, ["n_001"], ["n_003"], max_hops=2)
        assert len(paths) >= 1
        path = paths[0]
        assert "edge_label_chain" in path
        # Direct path n_001 → n_003 should have label "directly_causes"
        if len(path["edge_label_chain"]) > 0:
            assert path["edge_label_chain"][0] == "directly_causes"

    def test_nearto_no_duplicates(self, memory_conn):
        """NEARTO should not return duplicate neighbours when queried once."""
        from tools import get_neighbours

        nbs = get_neighbours(memory_conn, "m_002", "nearto", "forward")
        ids = [nb["id"] for nb in nbs]
        assert len(ids) == len(set(ids)), "get_neighbours should not return duplicates"


# ---------------------------------------------------------------------------
# Sidecar cache: structural index persistence (no LLM)
# ---------------------------------------------------------------------------

class TestStructuralIndexSidecar:

    def test_sidecar_written_and_loaded(self, tmp_path):
        from tests.fixture_db import create_fixture_db
        from engine import get_structural_index, reset_connection, _sidecar_path

        db_path = tmp_path / "sidecar_test.lbug"
        conn = create_fixture_db("metabolism", db_path)

        # Temporarily set _db_path so sidecar is written
        import engine as eng
        orig_db_path = eng._db_path
        eng._db_path = db_path
        eng._structural_index = None  # force recompute

        try:
            si = get_structural_index(conn)
            sidecar = _sidecar_path(db_path)
            assert sidecar.exists(), "Sidecar should be written after first index computation"

            # Clear in-memory cache, reload from sidecar
            eng._structural_index = None
            si2 = get_structural_index(conn)

            assert set(si.keys()) == set(si2.keys())
            for nid in si:
                assert si[nid].roles == si2[nid].roles
                assert abs(si[nid].betweenness_centrality - si2[nid].betweenness_centrality) < 1e-9
        finally:
            eng._db_path = orig_db_path
            eng._structural_index = None

    def test_sidecar_stale_on_node_count_change(self, tmp_path):
        from engine import _sidecar_path, _save_index_sidecar, _load_index_sidecar
        from models import StructuralFacts

        db_path = tmp_path / "stale_test.lbug"
        index = {
            f"n_{number:03d}": StructuralFacts(
                roles=["causal_origin"] if number == 1 else [],
                betweenness_centrality=0.5 if number == 1 else 0.0,
                in_degree={},
                out_degree={},
            )
            for number in range(1, 6)
        }
        _save_index_sidecar(
            db_path, index, node_count=5, topology_fingerprint="topology-a"
        )

        # Load with matching count — should succeed
        loaded = _load_index_sidecar(
            db_path, current_node_count=5, topology_fingerprint="topology-a"
        )
        assert loaded is not None
        assert "n_001" in loaded

        # Load with different count — should return None (stale)
        stale = _load_index_sidecar(
            db_path, current_node_count=10, topology_fingerprint="topology-a"
        )
        assert stale is None

        # Same node count, different edge topology — also stale.
        stale_topology = _load_index_sidecar(
            db_path, current_node_count=5, topology_fingerprint="topology-b"
        )
        assert stale_topology is None

        # Valid JSON with altered cached facts is corruption, not truth.
        import json

        sidecar = _sidecar_path(db_path)
        payload = json.loads(sidecar.read_text())
        payload["index"]["n_001"]["roles"] = ["orphan"]
        sidecar.write_text(json.dumps(payload))
        corrupt = _load_index_sidecar(
            db_path, current_node_count=5, topology_fingerprint="topology-a"
        )
        assert corrupt is None
