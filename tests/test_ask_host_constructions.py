"""Ask retrieve on host-agent constructions — not LOTR, not the hex fixture.

Graphs are read from this worktree when present, otherwise from the sibling
host-agent worktree (``experiment/host-agent-packet``). They are not merged.

Natures covered across the three graphs:

- identity (exact lookup by id and by label)
- containment (CONTAINS expand)
- proximity / attribute (NEARTO and EXPRESSES expand)
- membership / relation (bounded CONTAINS and LEADSTO path)
- typed empty (known node, wrong edge type)
- exact miss (lookup never widens)
- candidate search (lexical; never a closed-world empty)

Planning is the Ask loop choosing those ops, plus ``plan_retrieval`` compiling
an executable retrieval-v1 program. The loop model and Battalion are stubbed;
these tests do not spend on OpenRouter.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from mcp_server import ask as ask_mod
from mcp_server.retrieve import Retrieve
from mcp_server.surface import Surface


_REPO = Path(__file__).resolve().parents[1]
_HOST = Path(
    os.environ.get(
        "SST_HOST_AGENT_ROOT",
        "/home/kerem/Desktop/Personal Projects/Agent Prototype 3 - Host Retrieval Experiment",
    )
)


def _locate(*candidates: Path) -> Path:
    for path in candidates:
        if path.is_file():
            return path
    return candidates[-1]


KEP = _locate(
    _REPO / "data/construction_trials/kep-kustomize/graph.lbug",
    _REPO / "data/construction_trials/kubernetes_kep_lifecycle/workspace_v1/graph.lbug",
    _HOST / "results/kubernetes_kep_lifecycle/construction/run_1_correction/workspace_v1/graph.lbug",
)
CATTRS_HOST = _locate(
    _REPO / "data/construction_trials/cattrs-host-owned/graph.lbug",
    _REPO / "data/construction_trials/cattrs_host_owned_construction_v1/stage_b/graph.lbug",
    _HOST / (
        "data/construction_trials/cattrs_host_owned_construction_v1/"
        "stage_b/run_1_correction/host_workspace/uncertified_preview/graph.lbug"
    ),
)
CATTRS_REF = _locate(
    _REPO / "data/construction_trials/cattrs_external_v2/reference/graph.lbug",
    _HOST / "data/construction_trials/cattrs_external_v2/reference/graph.lbug",
)

KEP_PARENT = "kep_2377_lifecycle_metadata"
KEP_CHILD = "kustomize_declarative_purpose_and_goals"
KEP_GRANDCHILD = "kustomization_yaml_format_and_commands"
KEP_LABEL = "KEP 2386 Lifecycle and Status"
KEP_LABEL_ID = "kep_2386_lifecycle_metadata"

HOST_EDGE = "edge_boundary_architecture"
HOST_EDGE_LABEL = "Edge Boundary Architecture"
HOST_LEGACY = "legacy_genconverter_alias"
HOST_CODEGEN = "converter_codegen_specialization"
HOST_DISPATCH = "dispatch_predicate_priority"
HOST_CACHE = "dispatch_cache_invalidation_lifecycle"
HOST_PRECONF = "preconf_serializer_factories"

REF_ROOT = "cattrs_architecture"
REF_LAYER = "converter_registry"
REF_DECISION = "decision_current_converter_is_rule_registry"
REF_ROOT_LABEL = "Cattrs architecture"


def _surface_for(path: Path):
    """Open a COPY. LadybugDB writes on open, and these graphs are tracked.

    Opening the originals left `cattrs_external_v2/reference/graph.lbug` and two
    others modified in the working tree, which made every later frozen-hash
    check in the same run fail — eighteen of them, none of which had anything to
    do with what they were testing. The battery files pass in isolation and only
    go red after this module has run.

    `tests/test_pulse_software_host_transfer_v1.py` already copies before
    opening for exactly this reason.
    """
    if not path.is_file():
        pytest.skip(f"constructed graph not present: {path}")
    with tempfile.TemporaryDirectory(prefix="ask-host-construction-") as room:
        copied = Path(room) / path.name
        shutil.copy2(path, copied)
        # The structural-index sidecar is a cache; carrying it keeps this fast,
        # and a stale one is rebuilt rather than trusted.
        sidecar = path.with_suffix(path.suffix + ".idx")
        if sidecar.is_file():
            shutil.copy2(sidecar, copied.with_suffix(copied.suffix + ".idx"))
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
            instance = Surface(copied)
            yield instance
            instance.close()


@pytest.fixture(scope="module")
def kep_surface() -> Surface:
    yield from _surface_for(KEP)


@pytest.fixture(scope="module")
def host_surface() -> Surface:
    yield from _surface_for(CATTRS_HOST)


@pytest.fixture(scope="module")
def ref_surface() -> Surface:
    yield from _surface_for(CATTRS_REF)


@pytest.fixture
def kep_ops(kep_surface: Surface) -> Retrieve:
    return Retrieve(kep_surface)


@pytest.fixture
def host_ops(host_surface: Surface) -> Retrieve:
    return Retrieve(host_surface)


@pytest.fixture
def ref_ops(ref_surface: Surface) -> Retrieve:
    return Retrieve(ref_surface)


def _stub_claim(query, packet, _conn, verdict="CONFIRMED", compass=None):
    return {
        "query": query,
        "evidence_packet": packet,
        "confirmation_response": {"verdict": verdict},
        "final_answer": "stub-claim",
        "provenance": [],
        "gaps": [],
        "company_handoff": {"internal_handoff": {"gaps": []}},
        "retrieval_strategy": "contract_driven",
        "degradation_flags": list(packet.get("degradation_flags") or []),
    }


def _script_ask(monkeypatch, turns: list[str]):
    leftover = iter(turns)
    monkeypatch.setattr(ask_mod, "_call_loop_model", lambda _msgs: next(leftover))
    import claim as claim_mod

    monkeypatch.setattr(claim_mod, "write_claim", _stub_claim)


def _ids(result: dict) -> set[str]:
    return {row["id"] for row in result["evidence"]["node_records"]}


def _ops(state: dict) -> list[str]:
    return [row["operation"] for row in state["evidence_packet"]["packet_provenance"]]


# ---------------------------------------------------------------------------
# Kubernetes KEP workspace — hierarchical CONTAINS tree
# ---------------------------------------------------------------------------


def test_kep_lookup_identity_by_id_and_label(kep_ops: Retrieve):
    by_id = kep_ops.lookup([KEP_PARENT])
    by_label = kep_ops.lookup([KEP_LABEL])

    assert by_id["outcome"] == "FOUND"
    assert by_id["evidence_scope"] == "closure-derived"
    assert by_id["evidence"]["node_records"][0]["id"] == KEP_PARENT
    assert by_label["outcome"] == "FOUND"
    assert by_label["evidence"]["node_records"][0]["id"] == KEP_LABEL_ID


def test_kep_expand_containment(kep_ops: Retrieve):
    result = kep_ops.expand(
        [KEP_PARENT],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "FOUND"
    assert KEP_CHILD in _ids(result)
    assert all(
        edge["edge_type"] == "contains" for edge in result["evidence"]["edge_records"]
    )


def test_kep_path_membership_over_contains(kep_ops: Retrieve):
    result = kep_ops.path(
        [KEP_PARENT],
        [KEP_GRANDCHILD],
        edge_types=["contains"],
        max_hops=2,
    )
    assert result["outcome"] == "FOUND"
    assert result["evidence"]["path_records"]
    chain = result["evidence"]["path_records"][0]
    assert chain["source"] == KEP_PARENT
    assert chain["target"] == KEP_GRANDCHILD


def test_kep_typed_empty_is_not_an_unresolved_seed(kep_ops: Retrieve):
    result = kep_ops.expand(
        [KEP_PARENT],
        edge_types=["leadsto"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "EMPTY"
    assert result["evidence_scope"] == "closure-derived"
    assert result["seed_resolution"]["complete"] is True


def test_kep_exact_miss_is_terminal(kep_ops: Retrieve):
    result = kep_ops.lookup(["Sauron"])
    assert result["outcome"] == "EXACT_MISS"
    assert result["evidence_scope"] == "closure-derived"


def test_kep_search_kustomize_is_candidates(kep_ops: Retrieve):
    result = kep_ops.search("kustomize", mode="lexical", limit=8)
    assert result["outcome"] == "CANDIDATES"
    assert result["candidate_only"] is True
    assert result["evidence_scope"] == "candidate-derived"
    assert any("kustomize" in item or "kep_" in item for item in _ids(result))


def test_kep_search_miss_cannot_be_terminal_empty(kep_ops: Retrieve):
    result = kep_ops.search("definitely_missing_search_term_9f37", mode="lexical")
    assert result["outcome"] == "NO_CANDIDATES"
    assert result["outcome"] != "EMPTY"


def test_kep_ask_containment_lookup_then_expand(kep_surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [KEP_PARENT]}),
        json.dumps({
            "tool": "expand",
            "node_ids": [KEP_PARENT],
            "edge_types": ["contains"],
            "direction": "outgoing",
            "depth": 1,
        }),
        json.dumps({"final": {"reason": "children in packet"}}),
    ])
    state = ask_mod.run_ask(kep_surface, "What does KEP 2377 contain?")
    ids = {row["id"] for row in state["evidence_packet"]["node_records"]}
    assert KEP_PARENT in ids
    assert KEP_CHILD in ids
    assert _ops(state) == ["lookup", "expand"]
    assert state["confirmation_response"]["verdict"] == "CONFIRMED"


def test_kep_ask_membership_uses_path(kep_surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [KEP_PARENT, KEP_GRANDCHILD]}),
        json.dumps({
            "tool": "path",
            "source_ids": [KEP_PARENT],
            "target_ids": [KEP_GRANDCHILD],
            "edge_types": ["contains"],
            "max_hops": 2,
        }),
        json.dumps({"final": {"reason": "path in packet"}}),
    ])
    state = ask_mod.run_ask(
        kep_surface, "Is kustomization.yaml contained under KEP 2377?"
    )
    assert state["evidence_packet"]["path_records"]
    assert _ops(state) == ["lookup", "path"]


def test_kep_ask_exact_miss_does_not_widen(kep_surface: Surface, monkeypatch):
    searched: list = []
    orig = ask_mod.Retrieve.search

    def _search(self, *args, **kwargs):
        searched.append((args, kwargs))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(ask_mod.Retrieve, "search", _search)
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": ["Sauron"]}),
        json.dumps({"tool": "search", "query": "Sauron", "mode": "lexical"}),
        json.dumps({"final": {"reason": "missed"}}),
    ])
    state = ask_mod.run_ask(kep_surface, "Is Sauron in this graph?")
    assert searched == []
    assert state["confirmation_response"]["verdict"] == "UNKNOWN_TO_GRAPH"




# ---------------------------------------------------------------------------
# Cattrs host-owned Stage B — sparse LEADSTO / EXPRESSES / NEARTO
# ---------------------------------------------------------------------------


def test_host_lookup_identity_by_id_and_label(host_ops: Retrieve):
    by_id = host_ops.lookup([HOST_EDGE])
    by_label = host_ops.lookup([HOST_EDGE_LABEL])

    assert by_id["outcome"] == "FOUND"
    assert by_id["evidence"]["node_records"][0]["id"] == HOST_EDGE
    assert by_label["outcome"] == "FOUND"
    assert by_label["evidence"]["node_records"][0]["id"] == HOST_EDGE


def test_host_expand_nearto_legacy_alias(host_ops: Retrieve):
    result = host_ops.expand(
        [HOST_LEGACY],
        edge_types=["nearto"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "FOUND"
    assert HOST_CODEGEN in _ids(result)
    assert all(
        edge["edge_type"] == "nearto" for edge in result["evidence"]["edge_records"]
    )


def test_host_expand_expresses_codegen_to_registry(host_ops: Retrieve):
    result = host_ops.expand(
        [HOST_CODEGEN],
        edge_types=["expresses"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "FOUND"
    assert "converter_rule_registry" in _ids(result)


def test_host_path_leadsto_dispatch_to_cache(host_ops: Retrieve):
    result = host_ops.path(
        [HOST_DISPATCH],
        [HOST_CACHE],
        edge_types=["leadsto"],
        max_hops=1,
    )
    assert result["outcome"] == "FOUND"
    assert result["evidence"]["path_records"]
    chain = result["evidence"]["path_records"][0]
    assert chain["source"] == HOST_DISPATCH
    assert chain["target"] == HOST_CACHE


def test_host_typed_empty_contains_on_known_node(host_ops: Retrieve):
    result = host_ops.expand(
        [HOST_EDGE],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "EMPTY"
    assert result["seed_resolution"]["complete"] is True


def test_host_search_preconf_is_candidates(host_ops: Retrieve):
    result = host_ops.search("preconf", mode="lexical", limit=8)
    assert result["outcome"] == "CANDIDATES"
    assert HOST_PRECONF in _ids(result) or "preconf_converter_customization" in _ids(result)


def test_host_ask_proximity_lookup_then_expand(host_surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [HOST_LEGACY]}),
        json.dumps({
            "tool": "expand",
            "node_ids": [HOST_LEGACY],
            "edge_types": ["nearto"],
            "direction": "outgoing",
            "depth": 1,
        }),
        json.dumps({"final": {"reason": "near-to neighbour in packet"}}),
    ])
    state = ask_mod.run_ask(
        host_surface, "What is near the GenConverter alias?"
    )
    ids = {row["id"] for row in state["evidence_packet"]["node_records"]}
    assert HOST_LEGACY in ids
    assert HOST_CODEGEN in ids
    assert _ops(state) == ["lookup", "expand"]


def test_host_ask_causal_uses_path(host_surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [HOST_DISPATCH, HOST_CACHE]}),
        json.dumps({
            "tool": "path",
            "source_ids": [HOST_DISPATCH],
            "target_ids": [HOST_CACHE],
            "edge_types": ["leadsto"],
            "max_hops": 1,
        }),
        json.dumps({"final": {"reason": "leadsto path in packet"}}),
    ])
    state = ask_mod.run_ask(
        host_surface, "Does dispatch priority lead to cache invalidation?"
    )
    assert state["evidence_packet"]["path_records"]
    assert _ops(state) == ["lookup", "path"]




# ---------------------------------------------------------------------------
# Cattrs external v2 reference — already in this tree; also on the host branch
# ---------------------------------------------------------------------------


def test_ref_lookup_architecture(ref_ops: Retrieve):
    by_id = ref_ops.lookup([REF_ROOT])
    by_label = ref_ops.lookup([REF_ROOT_LABEL])
    assert by_id["outcome"] == "FOUND"
    assert by_id["evidence"]["node_records"][0]["id"] == REF_ROOT
    assert by_label["outcome"] == "FOUND"
    assert by_label["evidence"]["node_records"][0]["id"] == REF_ROOT


def test_ref_expand_architecture_contains_layers(ref_ops: Retrieve):
    result = ref_ops.expand(
        [REF_ROOT],
        edge_types=["contains"],
        direction="outgoing",
        depth=1,
    )
    assert result["outcome"] == "FOUND"
    kids = _ids(result)
    assert REF_LAYER in kids
    assert "edge_boundary" in kids
    assert "strategy_layer" in kids


def test_ref_path_architecture_to_decision(ref_ops: Retrieve):
    result = ref_ops.path(
        [REF_ROOT],
        [REF_DECISION],
        edge_types=["contains"],
        max_hops=2,
    )
    assert result["outcome"] == "FOUND"
    chain = result["evidence"]["path_records"][0]
    assert chain["source"] == REF_ROOT
    assert chain["target"] == REF_DECISION


def test_ref_search_frozenset_is_candidates(ref_ops: Retrieve):
    result = ref_ops.search("frozenset", mode="lexical", limit=8)
    assert result["outcome"] == "CANDIDATES"
    ids = _ids(result)
    assert any("frozenset" in item or "abstract_set" in item for item in ids)


def test_ref_ask_identity_uses_lookup_then_stops(ref_surface: Surface, monkeypatch):
    _script_ask(monkeypatch, [
        json.dumps({"tool": "lookup", "references": [REF_ROOT_LABEL]}),
        json.dumps({"final": {"reason": "named node"}}),
    ])
    state = ask_mod.run_ask(ref_surface, "What is Cattrs architecture?")
    ids = {row["id"] for row in state["evidence_packet"]["node_records"]}
    assert REF_ROOT in ids
    assert _ops(state) == ["lookup"]
    assert state["confirmation_response"]["verdict"] == "CONFIRMED"
