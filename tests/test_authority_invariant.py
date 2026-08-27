"""Graph writes are licensed by propose, not by a human queue.

Propose auto-commits through ``confirm_proposal``. MCP has no confirm verb.
`_apply` still has a closed set of callers.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: Trees that are not the shipping product. ``data/`` can contain admitted
#: external checkouts (and their ignored virtual environments), so scanning it
#: would mistake third-party functions for product graph-write paths.
# "build/" and "dist/" are setuptools' copies of the tree. Building a
# wheel put a second copy of every module under build/lib, and this scan
# found the same violations there — so packaging the project failed its
# own suite, which is a bad thing to discover while publishing.
_NON_PRODUCTION = (
    "tests/", "examples/", "archive/", "scratch/", "scripts/", "demo/",
    "benchmarks/", "data/", "results/", "build/", "dist/",
)


def _production_files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith(_NON_PRODUCTION):
            out.append(path)
    return out


#: Every call site of the graph-write function, and what authorises it. Adding
#: a caller without adding it here is a new way to mutate the graph, and this
#: test is the review.
_WRITE_PATHS = {
    "mcp_server/proposals.py": (
        "propose auto-commit (optional encode battery); plus the "
        "correction gate's SCRATCH-ONLY write, which never receives db_path"
    ),
    "mcp_server/materiality.py": "commit_exclusion (PrimarySource + verdict-neutrality gate)",
}


def test_every_code_path_that_writes_to_the_graph_is_accounted_for():
    """`_apply` encodes a proposal into the .lbug. Every new caller is a new way
    to mutate the graph and must be a deliberate, reviewed act.

    This test found `materiality.py` — a third write path neither the
    architecture notes nor I had counted. It is legitimate, and that is the
    point: the count was wrong and nothing would have said so.

    The fourth caller is `_apply_to_scratch` inside `_correction_gate`, added
    with the published-node correction path. It is NOT an authority act: it
    writes to a throwaway copy from `_scratch_copy` so the edit gate can compare
    the graph before and after a correction, and it is never handed the live
    `db_path`. The count cannot express that distinction, so
    `test_the_gate_scratch_write_never_touches_the_live_graph` pins it."""
    callers: list[str] = []
    for path in _production_files():
        text = path.read_text(encoding="utf-8")
        if "_apply(" not in text:
            continue
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_apply"):
                rel = path.relative_to(ROOT).as_posix()
                callers.append(f"{rel}:{node.lineno}")

    modules = {c.split(":")[0] for c in callers}
    unaccounted = sorted(modules - set(_WRITE_PATHS))
    assert not unaccounted, (
        f"new graph-write path(s) with no recorded authority: {unaccounted}. "
        f"Add them to _WRITE_PATHS with what authorises them, or route the "
        f"write through an existing path.")
    assert len(callers) == 4, (
        f"the graph-write function has {len(callers)} callers, expected 4: "
        f"{callers}")


def test_no_production_transport_wires_a_write_policy():
    """Without a WritePolicy the L1 auto-commit path cannot run. Propose still
    writes through confirm_proposal. This remains a deployment property."""
    for transport in ("mcp_server/http.py", "mcp_server/stdio.py"):
        text = (ROOT / transport).read_text(encoding="utf-8")
        assert "write_policy" not in text, (
            f"{transport} wires a write_policy — agents could reach the "
            "gate-mediated commit path without a human")


def test_l1_autonomy_is_off_even_when_a_policy_exists():
    from mcp_server.proposals import WritePolicy

    assert WritePolicy().l1_admitted is False, (
        "autonomy must require an explicit admission, never a default")


def test_an_l1_claim_without_an_admitted_policy_is_demoted_and_recorded(tmp_path):
    """Silent demotion would let a caller believe it had written at L1."""
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(db, store_path=tmp_path / "store.sqlite",
                      enable_proposals=True)
    try:
        out = surface.propose(
            encoding={"concepts": [{"id": "n_new", "label": "New",
                                    "text_content": "ADJUDICATES: if X then Y."}],
                      "edges": []},
            target_gap_id="some_gap",
            claim_level="L1",
        )
        assert out.get("claim_level_effective") == "L0"
        assert out.get("demotion_reason"), "the demotion must be recorded"
        assert out.get("status") == "COMMITTED", out
    finally:
        surface.close()


def test_a_dry_run_has_not_touched_the_graph(tmp_path):
    """Preflight must not write. Live propose does."""
    import real_ladybug as lb

    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)

    def node_ids():
        conn = lb.Connection(lb.Database(str(db)))
        try:
            rows = conn.execute("MATCH (n:Concept) RETURN n.id")
            out = set()
            while rows.has_next():
                out.add(rows.get_next()[0])
            return out
        finally:
            conn.close()

    before = node_ids()
    surface = Surface(db, store_path=tmp_path / "store.sqlite",
                      enable_proposals=True)
    try:
        out = surface.propose(
            encoding={"concepts": [{"id": "n_should_not_exist", "label": "X",
                                    "text_content": "ADJUDICATES: if X then Y."}],
                      "edges": []},
            target_gap_id="some_gap",
            dry_run=True,
        )
        assert out.get("dry_run") is True
        assert out.get("status") != "COMMITTED"
    finally:
        surface.close()

    after = node_ids()
    assert after == before, "dry-run propose mutated the graph"
    assert "n_should_not_exist" not in after


def test_the_agent_surface_exposes_no_commit_verb():
    """Capabilities are authority. `propose` is the only write-adjacent verb an
    agent gets, and it commits. MCP still has no confirm verb.

    HostWriteSurface may advance recover_existing corrections outside MCP, but
    it must not appear as an MCP tool name — that would reopen the confirm ban.
    """
    from mcp_server.stdio import TOOLS

    names = {t.name for t in TOOLS}
    for forbidden in (
        "confirm", "commit", "encode", "apply", "revert", "write",
        "write_advance", "write_submit", "write_check", "write_context",
    ):
        assert forbidden not in names, f"the agent surface exposes {forbidden!r}"
    assert "propose" in names
    assert "host_write" not in "".join(names)


def test_a_declared_exclusion_also_demands_a_primary_source(tmp_path):
    """The third write path is a human decision too. "This is intentionally
    ungoverned" is a recorded act with a source, not a shrug."""
    from mcp_server.materiality import commit_exclusion

    out = commit_exclusion(
        tmp_path / "nonexistent.lbug",
        tmp_path / "store.sqlite",
        "prop_x",
        primary_source="",
    )
    assert "error" in out and "primary_source" in out["error"]


# ---------------------------------------------------------------------------
# Disposition guards: terminal means terminal, and only terminal.
# ---------------------------------------------------------------------------


def _stored(tmp_path, status: str, pid: str = "prop_g"):
    import json

    from interaction.write_path_store import WritePathStore

    store = tmp_path / "store.sqlite"
    s = WritePathStore(store)
    s.save_proposal({
        "proposal_id": pid, "target_gap_id": "g1",
        "encoding_json": json.dumps({"concepts": [], "edges": []}),
        "claim_level": "L0", "demotion_reason": "", "generating_task": "t",
        "source_refs": [], "conversation_id": "c", "status": status,
    })
    s.close()
    return store


@pytest.mark.parametrize("status", ["COMMITTED", "REJECTED"])
def test_a_terminal_proposal_cannot_be_rejected(tmp_path, status):
    """Relabelling a COMMITTED proposal as REJECTED leaves the audit trail
    contradicting the graph it describes."""
    from mcp_server.proposals import reject_proposal

    out = reject_proposal(_stored(tmp_path, status), "prop_g", reason="x")
    assert "error" in out and status in out["error"]


@pytest.mark.parametrize("status", ["PENDING", "GATE_FAILED", "ENCODE_FAILED",
                                    "GRAIN_FAILED"])
def test_a_non_terminal_proposal_can_be_dropped(tmp_path, status):
    """A gate-failed proposal was restored — nothing of it is in the graph — so
    dropping it rather than requeueing is the operator's ordinary choice. An
    earlier guard allowed only PENDING and broke that; the m4 battery caught it
    where the pytest suite did not."""
    from mcp_server.proposals import reject_proposal

    out = reject_proposal(_stored(tmp_path, status), "prop_g", reason="not needed")
    assert out.get("status") == "REJECTED", out


def test_the_gate_scratch_write_never_touches_the_live_graph():
    """The fourth `_apply` caller is a gate probe, not an authority path.

    `_correction_gate` evaluates a correction by applying it to a COPY and
    asking the oracle what changed. If that copy were ever the live graph, a
    refused correction would already have mutated the thing it was refusing to
    mutate — the gate would be the leak."""
    import tempfile

    from mcp_server.fixture import ensure_fixture
    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import _correction_gate, validate_proposal

    live = Path(tempfile.mkdtemp()) / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), live)

    import real_ladybug as lb

    database = lb.Database(str(live))
    conn = lb.Connection(database)
    conn.execute("MATCH (c:Concept {id: 'order_service'}) SET c.claim_kind = 'governing'")
    del conn, database

    before = graph_fingerprint(live)
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "scratch probe",
                          "reason": "gate evaluation only"}]}, live)
    assert err == ""

    # The oracle is injected: `live_oracle` issues a what_governs per probe,
    # which is engine work. This test is about file isolation, not verdicts.
    def _factory(_db, probes):
        return lambda _model: {p: "UNGOVERNED" for p in probes}

    decision = _correction_gate(live, prop, None, lambda _t: [0.0] * 3072,
                                probe_cap=32, oracle_factory=_factory)

    assert decision["ran"] is True, "the gate must actually have applied to a copy"
    assert graph_fingerprint(live) == before
