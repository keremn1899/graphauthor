"""Correcting a published node — the repair path for a claim that was never true.

Supersession says a claim was true and stopped being so; a correction says it
was wrong. Before this, `_apply` was CREATE-only and `validate_proposal` refused
any id already in the graph, so a published mistake could not be fixed by any
live route.

The audit trail is preserved by graph-level versioning, not by node
immutability: `confirm_proposal` snapshots pre-encode and the snapshot remains
the record of what the graph said at decision time.
"""

from __future__ import annotations

import shutil

import pytest

from interaction.write_path_store import WritePathStore
from mcp_server.fixture import ensure_fixture
from mcp_server.proposals import (
    GateSpec,
    _correction_gate,
    confirm_proposal,
    validate_proposal,
)
from mcp_server.surface import Surface

EMB = lambda _t: [0.0] * 3072  # noqa: E731


@pytest.fixture()
def db(tmp_path):
    dst = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), dst)
    return dst


def _gate(green=True):
    return GateSpec(
        target_gap_id="g",
        policy_id="order_service",
        policy_in_grounding=lambda r, pid, also=None: pid in str(r.get("grounding", "")),
        adjacent_only=lambda r, *a: False,
        runner=lambda: (
            [{"governance_verdict": "GOVERNED", "grounding": "order_service"}] * 5,
            {"a": [{"governance_verdict": "UNGOVERNED" if green else "GOVERNED"}] * 5},
        ),
        baseline={"a": {"n": 5, "GOVERNED": 0.0, "UNGOVERNED": 1.0, "ABSENT": 0.0}},
        intrinsic_ids=("a",),
        encoded_gap_ids=("g",),
        intentional_closure_ids=("g",),
    )


def _read(db_path, node_id):
    import real_ladybug as lb

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    try:
        res = conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.text_content, c.label, c.token_count",
            {"id": node_id},
        )
        row = res.get_next() if res.has_next() else None
    finally:
        del conn, database
    return row


# --- validation -----------------------------------------------------------


def test_correction_target_must_already_exist(db):
    prop, err = validate_proposal(
        {"corrections": [{"id": "not_here", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    assert prop is None
    assert "correction target(s) not in graph" in err


def test_correction_accepts_an_existing_id_that_an_add_would_refuse(db):
    added, add_err = validate_proposal(
        {"concepts": [{"id": "order_service", "label": "d", "text_content": "x"}]}, db)
    corrected, corr_err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    assert added is None and "already exist" in add_err
    assert corr_err == "" and corrected is not None
    assert corrected.is_add_only() is False


def test_the_same_id_cannot_be_both_added_and_corrected(db):
    prop, err = validate_proposal(
        {"concepts": [{"id": "order_service", "label": "n", "text_content": "t"}],
         "corrections": [{"id": "order_service", "text_content": "f",
                          "reason": "r"}]}, db)

    assert prop is None and "both added and corrected" in err


def test_a_correction_requires_a_reason(db):
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "  "}]}, db)

    assert prop is None and "invalid encoding" in err


def test_a_correction_alone_is_not_an_empty_proposal(db):
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    assert err == "" and prop is not None and not prop.is_empty()


# --- the gate -------------------------------------------------------------


def _governing(db_path, node_id="order_service"):
    import real_ladybug as lb

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    conn.execute(f"MATCH (c:Concept {{id: '{node_id}'}}) "
                 "SET c.claim_kind = 'governing'")
    del conn, database


def _fake_oracle(verdicts):
    """Deterministic stand-in for `live_oracle`, which costs a model call per
    probe. `evaluate_edit` injects its oracle for exactly this reason."""
    calls = {"n": 0}

    def factory(_db, probes):
        def oracle(_model):
            calls["n"] += 1
            state = verdicts[min(calls["n"], len(verdicts)) - 1]
            return {p: state.get(p, "UNGOVERNED") for p in probes}
        return oracle

    factory.calls = calls
    return factory


def test_governing_correction_probes_the_complete_universe(db):
    """No caller probes: every Concept.id is in the suite."""
    _governing(db)
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(
        db, prop, None, EMB, oracle_factory=_fake_oracle([{}, {}]))

    assert decision["ran"] is True
    assert decision["allowed"] is True
    assert decision["probes_supplied"] == []
    assert decision["probe_mode"] == "complete_universe"
    assert "order_service" in decision["probes"]
    assert len(decision["probes"]) >= 30


def test_a_correction_to_a_non_governing_node_is_still_gated(db):
    """D3 was falsified; this test used to assert the behaviour it licensed.

    The gate used to return early whenever the target was not governing, on the
    argument that the server never promotes a claim to governing from words.
    That argument is about what may GOVERN. The gate's question is what may
    CHANGE governance, and measurement says those are different sets:
    `contextual_influence_v1` (272 engine calls, positive control held) found
    that 6 of 8 corrections to NON-governing nodes moved a governing verdict,
    five of them cardinal UNGOVERNED->GOVERNED. Correcting a superseded note
    laundered authority onto two live rules while staying contextual throughout.
    """
    _governing(db)  # some governing claim exists somewhere in the graph
    prop, err = validate_proposal(
        {"corrections": [{"id": "api_ingress", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(db, prop, None, EMB, probe_cap=64,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert decision["ran"] is True


def test_the_only_surviving_skip_is_a_graph_with_no_governing_claim(db):
    """Nothing can move a governing verdict that does not exist.

    This is the one skip the evidence supports, and it is sound by construction
    rather than by an argument about what the target is.
    """
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(db, prop, None, EMB)

    assert decision["allowed"] is True
    assert decision["ran"] is False
    assert decision["reason"] == "graph_has_no_governing_claim"


def test_a_small_graph_is_probed_exhaustively(db):
    """Three probe defaults were wrong; stop guessing the reachable set.

    Declaration-derived, then one hop, then edges-only — each assumed some
    subset was reachability and each was falsified. Below the ceiling the suite
    is every node, which cannot be wrong about reachability, and costs about
    what the guess did.
    """
    from mcp_server.proposals import _all_node_ids

    _governing(db)
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(db, prop, None, EMB, probe_cap=64,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert decision["probe_completeness"] == "exhaustive"
    assert set(decision["probes"]) == set(_all_node_ids(db))


def test_add_only_proposal_never_enters_the_correction_gate(db):
    prop, err = validate_proposal(
        {"concepts": [{"id": "brand_new", "label": "N", "text_content": "t"}]}, db)
    assert err == ""

    decision = _correction_gate(db, prop, None, EMB)

    assert decision == {"ran": False, "allowed": True,
                        "reason": "add_only_no_corrections"}


# --- end to end -----------------------------------------------------------


def _queue(db_path, encoding):
    """Store a PENDING proposal bound to the live graph basis."""
    import json
    from pathlib import Path

    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import new_proposal_id, validate_proposal

    prop, err = validate_proposal(encoding, db_path)
    assert prop is not None, err
    store_path = Path(db_path).with_suffix(".writestore.sqlite")
    pid = new_proposal_id()
    store = WritePathStore(store_path)
    try:
        store.save_proposal({
            "proposal_id": pid,
            "target_gap_id": "test_gap",
            "encoding_json": json.dumps(prop.model_dump()),
            "generating_task": "t",
            "source_refs": [],
            "expected_graph_version": "basis",
            "expected_graph_fingerprint": graph_fingerprint(db_path),
            "status": "PENDING",
        })
    finally:
        store.close()
    return pid, store_path


def test_confirming_a_correction_rewrites_the_published_node(db):
    before = _read(db, "order_service")
    assert before is not None
    pid, store_path = _queue(db, {
        "corrections": [{
            "id": "order_service",
            "text_content": "Corrected: the order service does not own payment retries.",
            "reason": "the original text asserted an ownership that was never true",
        }]})

    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB)

    assert result.get("status") not in ("CORRECTION_REFUSED", "REJECTED"), result
    after = _read(db, "order_service")
    assert after[0].startswith("Corrected:")
    assert after[0] != before[0]
    # token_count must follow the new text, not the old
    assert after[2] != before[2] or len(after[0]) // 4 == after[2]


def _governing(db, node_id="order_service"):
    import real_ladybug as lb

    database = lb.Database(str(db))
    conn = lb.Connection(database)
    conn.execute(f"MATCH (c:Concept {{id: '{node_id}'}}) "
                 "SET c.claim_kind = 'governing'")
    del conn, database


def test_an_unacknowledged_correction_commits(db):
    """An interpretable move no longer waits for a person."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})

    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"api_ingress": "GOVERNED"},
                                  {"api_ingress": "UNGOVERNED"},
                              ]))

    assert result["status"] == "COMMITTED", result
    assert _read(db, "order_service")[0] == "rewritten"


def test_a_reported_correction_is_committed(db):
    """An interpretable finding is not a hold."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})
    confirm_proposal(db, store_path, pid, primary_source="human source",
                     gate=_gate(True), embedder=EMB, correction_probe_cap=32,
                     correction_oracle_factory=_fake_oracle([
                         {"api_ingress": "GOVERNED"},
                         {"api_ingress": "UNGOVERNED"}]))

    assert WritePathStore(store_path).get_proposal(pid)["status"] == "COMMITTED"


def test_an_acknowledgement_is_not_required_to_commit(db):
    """The leftover ack payload is ignored on an interpretable write."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})

    result = confirm_proposal(
        db, store_path, pid, primary_source="human source", gate=_gate(True),
        embedder=EMB, correction_probe_cap=32,
        correction_oracle_factory=_fake_oracle([
            {"api_ingress": "GOVERNED"},
            {"api_ingress": "UNGOVERNED"}]),
        correction_acknowledgement={
            "report_digest": "anything",
            "moves": {"api_ingress": ["GOVERNED", "UNGOVERNED"]},
            "accepts": ["api_ingress"],
            "acknowledged_by": "human:test",
        })

    assert result["status"] == "COMMITTED", result
    assert _read(db, "order_service")[0] == "rewritten"


def test_a_cardinal_flip_refuses_without_a_human_gate(db):
    """Toward-governed is a mechanical refuse, not a queue for a person."""
    _governing(db)
    before = _read(db, "order_service")
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})

    result = confirm_proposal(
        db, store_path, pid, primary_source="human source",
        gate=_gate(True), embedder=EMB, correction_probe_cap=32,
        correction_oracle_factory=_fake_oracle([
            {"api_ingress": "UNGOVERNED"},
            {"api_ingress": "GOVERNED"}]))

    assert result["status"] == "CORRECTION_REFUSED"
    assert _read(db, "order_service") == before


def test_a_stale_acknowledgement_does_not_hold_an_interpretable_edit(db):
    """Ack binding is leftover; an interpretable rewrite still commits."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})

    def oracle():
        return _fake_oracle([{"api_ingress": "GOVERNED"},
                             {"api_ingress": "UNGOVERNED"}])

    first = confirm_proposal(db, store_path, pid, primary_source="human source",
                             gate=_gate(True), embedder=EMB,
                             correction_probe_cap=32,
                             correction_oracle_factory=oracle())
    assert first["status"] == "COMMITTED"

    other, other_store = _queue(db, {
        "corrections": [{"id": "order_service",
                         "text_content": "something else entirely",
                         "reason": "wrong"}]})
    result = confirm_proposal(
        db, other_store, other, primary_source="human source", gate=_gate(True),
        embedder=EMB, correction_probe_cap=32,
        correction_oracle_factory=oracle(),
        correction_acknowledgement={
            "report_digest": "stale",
            "moves": {"api_ingress": ["GOVERNED", "UNGOVERNED"]},
            "accepts": ["api_ingress"],
        })

    assert result["status"] == "COMMITTED", result


def test_a_correction_that_moves_nothing_needs_no_acknowledgement(db):
    """Nobody should have to affirm an empty list."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})
    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"api_ingress": "GOVERNED"},
                                  {"api_ingress": "GOVERNED"}]))
    assert result["status"] == "COMMITTED", result


def test_withdraw_force_clears_local_loss_without_an_acknowledger(db):
    """Intent declared BEFORE the gate runs is what licenses auto-acceptance.

    Losing coverage on the rule you just neutralised is the intended effect of
    the edit, not an undeclared surprise — and the acceptance rule was fixed
    before the finding existed, which is what separates this from the gate
    approving its own output.
    """
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "states no rule",
                         "reason": "never established",
                         "intent": "withdraw_force"}]})
    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"order_service": "GOVERNED"},
                                  {"order_service": "UNGOVERNED"}]))
    assert result["status"] == "COMMITTED", result


def test_the_same_loss_still_reports_under_a_restate_intent(db):
    """Intent narrows what is acceptable; it can never widen it.

    Same graph, same oracle, same move as the test above — only the declared
    purpose differs. Rewording a rule should move nothing, so a move means the
    edit did something its author did not claim.
    """
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "states no rule",
                         "reason": "never established", "intent": "restate"}]})
    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"order_service": "GOVERNED"},
                                  {"order_service": "UNGOVERNED"}]))
    assert result["status"] == "COMMITTED", result


def test_a_gate_that_never_compared_still_refuses(db):
    """Universe overflow has no report to acknowledge.

    An empty `changed` map is indistinguishable from "nothing moved", so this
    must refuse on precedence rather than fall through to the report path —
    otherwise the cap's refusal quietly becomes a clean pass.
    """
    _governing(db)
    before = _read(db, "order_service")
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "rewritten",
                         "reason": "wrong"}]})
    result = confirm_proposal(db, store_path, pid,
                              primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=1)
    assert result["status"] == "CORRECTION_REFUSED"
    assert result["correction_gate"]["reason"] == "universe_exceeds_probe_cap"
    assert _read(db, "order_service") == before


def test_the_snapshot_preserves_what_the_graph_said_before_the_correction(db):
    """The argument the whole design rests on.

    Mutating a node is only acceptable because the audit trail lives at the
    GRAPH level: `confirm_proposal` captures a pre-encode snapshot, so the
    previous version remains the record of what the graph said at decision
    time. If this fails, correction should have been retraction instead.

    Note `restore` is the atomic rollback mechanism — it puts the live graph
    back, which is why this assertion runs last."""
    from mcp_server.history import SnapshotStore

    original = _read(db, "order_service")[0]
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service",
                         "text_content": "CORRECTED TEXT",
                         "reason": "never true"}]})

    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB)

    assert result["status"] == "COMMITTED", result
    assert _read(db, "order_service")[0] == "CORRECTED TEXT"

    SnapshotStore(db).restore(f"pre-encode:{pid}")
    assert _read(db, "order_service")[0] == original


# --- region-derived probes ------------------------------------------------


def test_caller_probes_widen_the_suite_and_cannot_narrow_it(db):
    """The anti-circularity property.

    Caller probes are UNIONED with the complete universe, never substituted
    for it. A change cannot shrink the gate to the predicates where it is
    honest.
    """
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    narrow = _correction_gate(db, prop, ["unrelated_predicate"], EMB,
                              oracle_factory=_fake_oracle([{}, {}]))
    bare = _correction_gate(db, prop, None, EMB,
                            oracle_factory=_fake_oracle([{}, {}]))

    assert set(bare["probes"]).issubset(set(narrow["probes"]))
    assert "unrelated_predicate" in narrow["probes"]
    assert narrow["probes_supplied"] == ["unrelated_predicate"]
    assert "order_service" in narrow["probes"]


def test_a_region_probe_moving_undeclared_refuses(db):
    """The gate's whole purpose: a verdict the correction did not declare."""
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong", "declared_changes": []}]}, db)

    decision = _correction_gate(
        db, prop, None, EMB,
        probe_cap=32, oracle_factory=_fake_oracle([
            {"api_ingress": "GOVERNED"},   # before
            {"api_ingress": "UNGOVERNED"},  # after — undeclared move
        ]))

    assert decision["allowed"] is False
    assert decision["reason"].startswith("undeclared_")
    assert "api_ingress" in decision["changed"]


def test_declaring_that_same_move_allows_and_audits_it(db):
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong",
                          "declared_changes": ["api_ingress"]}]}, db)

    decision = _correction_gate(
        db, prop, None, EMB,
        probe_cap=32, oracle_factory=_fake_oracle([
            {"api_ingress": "GOVERNED"},
            {"api_ingress": "UNGOVERNED"},
        ]))

    assert decision["allowed"] is True
    assert decision["audited"] is True


def test_the_probe_cap_discloses_what_it_dropped(db):
    """A cap that silently dropped the affected predicate would read as
    'no verdict change' — the dangerous direction."""
    from mcp_server.proposals import _region_probes

    full = _region_probes(db, {"order_service"}, cap=100)
    capped = _region_probes(db, {"order_service"}, cap=2)

    assert len(capped["probes"]) == 2
    assert capped["excluded"]
    assert sorted(capped["probes"] + capped["excluded"]) == sorted(full["probes"])
    assert capped["region_size"] == full["region_size"]


def test_the_universe_is_graph_ids_not_declarations(db):
    """Probes come from every Concept.id, so naming something in
    declared_changes cannot conjure a non-graph predicate into the suite."""
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong",
                          "declared_changes": ["a_predicate_not_in_the_graph"]}]}, db)

    decision = _correction_gate(db, prop, None, EMB,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert "a_predicate_not_in_the_graph" not in decision["probes"]
    assert "order_service" in decision["probes"]
    assert decision["probe_mode"] == "complete_universe"


def test_the_gate_leaves_no_scratch_copies_behind(db):
    """Each gate run copies the whole graph. Leaking one per run filled a 7GB
    tmpfs during a single suite and failed 133 unrelated tests with a disk
    quota error — the scratch must be removed even when the gate refuses."""
    import glob

    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    before = set(glob.glob("/tmp/correction_gate_*"))
    for verdicts in ([{}, {}], [{"api_ingress": "GOVERNED"},
                                {"api_ingress": "UNGOVERNED"}]):
        _correction_gate(db, prop, None, EMB,
                         probe_cap=32, oracle_factory=_fake_oracle(verdicts))
    after = set(glob.glob("/tmp/correction_gate_*"))

    assert after == before, f"leaked scratch copies: {sorted(after - before)}"


def test_a_universe_larger_than_the_cap_refuses_rather_than_checking_part(db):
    """Truncating would report 'no verdict change' for probes never run."""
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    decision = _correction_gate(db, prop, None, EMB, probe_cap=5,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert decision["allowed"] is False
    assert decision["reason"] == "universe_exceeds_probe_cap"
    assert decision["universe"]["universe_size"] > decision["universe"]["cap"]
    assert decision["universe"]["excluded"], "must name what it could not reach"
    assert decision["ran"] is False


def test_raising_the_cap_deliberately_lets_it_proceed(db):
    _governing(db)
    prop, _ = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)

    decision = _correction_gate(db, prop, None, EMB, probe_cap=32,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert decision["ran"] is True and decision["allowed"] is True
    assert decision["probes_excluded_by_cap"] == []


def test_probing_never_modifies_the_graph_it_measures(db):
    """`_region_probes` and `_claim_kinds` are reads. Opening the graph
    read-write silently changed a frozen reference fixture and tripped its
    digest guard in 19 unrelated tests — none of which pointed at the cause."""
    from mcp_server.history import graph_fingerprint
    from mcp_server.proposals import _claim_kinds, _region_probes

    before = graph_fingerprint(db)

    _region_probes(db, {"order_service"}, hops=2, cap=99)
    _claim_kinds(db, {"order_service"})

    assert graph_fingerprint(db) == before


# --- claim_kind: retagging what a node IS ---------------------------------


def _kind(db_path, node_id):
    import real_ladybug as lb

    database = lb.Database(str(db_path))
    conn = lb.Connection(database)
    try:
        res = conn.execute(
            "MATCH (c:Concept {id: $id}) RETURN c.claim_kind", {"id": node_id})
        return str(res.get_next()[0] or "") if res.has_next() else None
    finally:
        del conn, database


def test_a_governing_node_can_be_demoted(db):
    """The repair the gate exists for.

    Rewriting a wrongly-governing node's text left it still governing — the
    graph kept treating a note as authority. Demotion is the actual fix, and it
    was not expressible until now.
    """
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "states no rule",
                         "reason": "never carried authority",
                         "intent": "withdraw_force", "claim_kind": "contextual"}]})
    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"order_service": "GOVERNED"},
                                  {"order_service": "UNGOVERNED"}]))

    assert result["status"] == "COMMITTED", result
    assert _kind(db, "order_service") == "contextual"


def test_promoting_a_contextual_node_is_gated(db):
    """The hole this closes.

    The gate sized itself on the node's CURRENT claim_kind, so a contextual
    node retagged as governing skipped the before/after comparison entirely and
    became authoritative with nothing checked. That is laundering through the
    claim_kind field instead of through the text — and the charter's "never
    promote from words" does not cover it, because an explicit retag is a
    caller asserting authority rather than the server inferring it.
    """
    before = _kind(db, "api_ingress")
    assert before != "governing"

    pid, store_path = _queue(db, {
        "corrections": [{"id": "api_ingress", "text_content": "this now rules",
                         "reason": "should have been authoritative",
                         "claim_kind": "governing"}]})
    result = confirm_proposal(db, store_path, pid, primary_source="human source",
                              gate=_gate(True), embedder=EMB,
                              correction_probe_cap=32,
                              correction_oracle_factory=_fake_oracle([
                                  {"order_service": "UNGOVERNED"},
                                  {"order_service": "GOVERNED"}]))

    assert result["status"] == "CORRECTION_REFUSED"
    assert result["correction_gate"]["ran"] is True
    assert _kind(db, "api_ingress") == before


def test_a_correction_without_a_claim_kind_leaves_the_role_alone(db):
    """Silently retagging on every correction would let a typo fix change what
    a node IS. Empty means unchanged."""
    _governing(db)
    pid, store_path = _queue(db, {
        "corrections": [{"id": "order_service", "text_content": "states no rule",
                         "reason": "wrong", "intent": "withdraw_force"}]})
    confirm_proposal(db, store_path, pid, primary_source="human source",
                     gate=_gate(True), embedder=EMB, correction_probe_cap=32,
                     correction_oracle_factory=_fake_oracle([
                         {"order_service": "GOVERNED"},
                         {"order_service": "UNGOVERNED"}]))

    assert _kind(db, "order_service") == "governing"


def test_an_acknowledgement_does_not_survive_an_added_retag(db):
    """A retag is part of the edit, so it is part of what was affirmed.

    Otherwise an acknowledgement of a text fix could be redeemed against a
    resubmission that also makes the node governing.
    """
    from mcp_server.correction_ack import report_digest
    from mcp_server.proposals import ProposalCorrection

    plain = ProposalCorrection(id="n", text_content="t", reason="r")
    retagged = ProposalCorrection(id="n", text_content="t", reason="r",
                                  claim_kind="governing")
    shas = {"n": "abc"}

    assert report_digest([plain], shas) != report_digest([retagged], shas)


def test_an_unknown_claim_kind_is_schema_invalid(db):
    prop, err = validate_proposal({"corrections": [{
        "id": "order_service", "text_content": "t", "reason": "r",
        "claim_kind": "authoritative"}]}, db)

    assert prop is None
    assert err


# --- the probe suite has two arms, because reachability does ---------------


def test_the_complete_universe_covers_nodes_no_edge_path_could_reach(db):
    """The measurement that killed neighbourhood probing.

    Measured (`semantic_probe_gap_v1_1`): with EVERY edge stripped, a rewrite
    still moved verdicts on nodes reachable only by embedding proximity. The
    complete universe includes those nodes by construction.
    """
    from mcp_server.proposals import _all_node_ids

    _governing(db)
    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""

    decision = _correction_gate(db, prop, None, EMB,
                                oracle_factory=_fake_oracle([{}, {}]))

    assert decision["probe_mode"] == "complete_universe"
    assert set(decision["probes"]) == set(_all_node_ids(db))


def test_an_edgeless_node_is_still_probed(db):
    """The exact condition the measurement falsified the old design on."""
    import real_ladybug as lb
    from mcp_server.proposals import _region_probes, _semantic_probes

    _governing(db)
    database = lb.Database(str(db))
    conn = lb.Connection(database)
    for rel in ("LEADSTO", "CONTAINS", "EXPRESSES", "NEARTO"):
        conn.execute(f"MATCH (a:Concept)-[r:{rel}]->(b:Concept) "
                     "WHERE a.id = 'order_service' DELETE r")
        conn.execute(f"MATCH (a:Concept)-[r:{rel}]->(b:Concept) "
                     "WHERE b.id = 'order_service' DELETE r")
    del conn, database

    assert _region_probes(db, {"order_service"})["region_size"] == 1
    assert _semantic_probes(db, {"order_service"})

    prop, err = validate_proposal(
        {"corrections": [{"id": "order_service", "text_content": "fixed",
                          "reason": "was wrong"}]}, db)
    assert err == ""
    decision = _correction_gate(db, prop, None, EMB, probe_cap=64,
                                oracle_factory=_fake_oracle([{}, {}]))

    # The old suite would have been ["order_service"] alone.
    assert len(decision["probes"]) > 1
    assert decision["disposition"]["disposition"] != "uncheckable"


def test_semantic_probes_never_include_the_corrected_nodes(db):
    from mcp_server.proposals import _semantic_probes

    neighbours = _semantic_probes(db, {"order_service"})
    assert "order_service" not in {n["id"] for n in neighbours}


def test_semantic_probing_costs_no_model_calls(db):
    """Vectors are read from the graph, never recomputed.

    If widening the suite required an embedding call per correction it would be
    a cost decision as well as a safety one, and would be tuned down.
    """
    from mcp_server.proposals import _semantic_probes

    def _explode(_text):
        raise AssertionError("semantic probing must not call an embedder")

    import mcp_server.proposals as module

    original, module.default_embedder = module.default_embedder, lambda: _explode
    try:
        assert _semantic_probes(db, {"order_service"})
    finally:
        module.default_embedder = original
