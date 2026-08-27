"""L2-3 batch/tiering/audit — pytest wrapper over the battery's core claims."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "l23_battery", Path(__file__).parent.parent / "scripts" / "run_l23_battery.py")
l23 = importlib.util.module_from_spec(spec)
sys.modules["l23_battery"] = l23
spec.loader.exec_module(l23)


def test_structural_distractor_check_semantics():
    from mcp_server.proposals import structural_distractor_check

    pre = {"concepts": {"a": {"label": "A", "content_sha": "s1"},
                        "b": {"label": "B", "content_sha": "s2"}}, "edges": []}
    post_ok = {"concepts": {**pre["concepts"], "new1": {"label": "N", "content_sha": "s3"}}, "edges": []}
    clean, f = structural_distractor_check(pre, post_ok, {"new1"})
    assert clean and not f
    post_mut = {"concepts": {"a": {"label": "A", "content_sha": "CHANGED"},
                             "b": pre["concepts"]["b"]}, "edges": []}
    clean, f = structural_distractor_check(pre, post_mut, set())
    assert not clean and any("mutated:a" in x for x in f)
    post_rm = {"concepts": {"a": pre["concepts"]["a"]}, "edges": []}
    clean, f = structural_distractor_check(pre, post_rm, set())
    assert not clean and any("removed:b" in x for x in f)
    post_sneak = {"concepts": {**pre["concepts"], "sneak": {"label": "S", "content_sha": "x"}}, "edges": []}
    clean, f = structural_distractor_check(pre, post_sneak, set())
    assert not clean and any("unexpected_concept_added:sneak" in x for x in f)


def test_batch_pins_run_once_and_survivor_semantics(tmp_path, monkeypatch):
    """B1+B2 compressed: pins once; closure-red requeued; survivors committed."""
    import json
    import shutil

    from interaction.write_path_store import WritePathStore
    from mcp_server.fixture import ensure_fixture
    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import confirm_batch, new_proposal_id, validate_proposal
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    store = tmp_path / "s.sqlite"
    fp = graph_fingerprint(db)
    pids = []
    records = WritePathStore(store)
    try:
        for cid in ("x1", "bad", "x2"):
            encoding = l23.ENC(cid)
            prop, err = validate_proposal(encoding, db)
            assert prop is not None, err
            pid = new_proposal_id()
            records.save_proposal({
                "proposal_id": pid,
                "target_gap_id": f"{cid}_policy",
                "encoding_json": json.dumps(prop.model_dump()),
                "generating_task": "t",
                "source_refs": [],
                "expected_graph_version": "basis",
                "expected_graph_fingerprint": fp,
                "status": "PENDING",
            })
            pids.append(pid)
    finally:
        records.close()
    s = Surface(db, enable_history=True, enable_proposals=True, store_path=store)
    v0 = s.orient()["graph_version"]
    s.close()

    fac = l23.SpecFactory(closure_red_for={"bad_policy"})
    r = confirm_batch(db, store, pids, primary_source="src", gate_builder=fac.build,
                      embedder=l23.EMB, legislatable=lambda p: p.endswith("_policy"))
    assert fac.pins_calls == 1
    assert r["results"][pids[1]]["reason"] == "closure_red"
    assert r["results"][pids[0]]["status"] == "COMMITTED"
    from interaction.event_log import EventStore
    from mcp_server.ledger import project_activities

    event_store = EventStore(store)
    try:
        events = event_store.list_events()
    finally:
        event_store.close()
    committed = {
        row["proposal_id"]: row
        for row in events
        if row["type"] == "graph.committed"
    }
    assert committed[pids[0]]["subject_node_ids"] == '["x1"]'
    assert committed[pids[2]]["subject_node_ids"] == '["x2"]'
    assert pids[1] not in committed
    failed_events = [
        row for row in events if row["proposal_id"] == pids[1]
    ]
    assert failed_events == []
    assert not any(
        any(e.get("proposal_id") == pids[1] for e in activity["events"])
        and activity["needs_me"]
        for activity in project_activities(events).values()
    )
    s = Surface(db, enable_history=True, enable_proposals=True, store_path=store)
    try:
        added = {c["id"] for c in s.changed_since(v0)["concepts_added"]}
        assert added == {"x1", "x2"}
        assert s.proposal_status(pids[1])["status"] == "PENDING"
    finally:
        s.close()


def test_structural_purity_check_semantics():
    from mcp_server.proposals import structural_purity_check

    pure, f = structural_purity_check({"concepts": [
        {"id": "p", "label": "ReplayPort", "text_content": "Inbound port accepting replay requests.",
         "semantic_anchor": "port"}]})
    assert pure and not f
    impure, f = structural_purity_check({"concepts": [
        {"id": "q", "label": "Q", "text_content": "Requests MUST carry a token; omission is a violation."}]})
    assert not impure and "adjudicative_language_in:q" in f[0]
    # markers err toward impurity, never refusal — empty encoding is pure
    assert structural_purity_check({"concepts": []}) == (True, [])
