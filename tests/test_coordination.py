"""Single-owner RW-lock semantics (B13): readers concurrent, writer exclusive,
writer-preferring. Deterministic via barriers/events, not sleeps where possible."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp_server.coordination import RWLock  # noqa: E402


def test_readers_run_concurrently():
    lock = RWLock()
    both_inside = threading.Barrier(2, timeout=3)
    passed = []

    def reader():
        with lock.read():
            # both readers must be inside at once, or the barrier times out
            passed.append(both_inside.wait())

    ts = [threading.Thread(target=reader) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(4)
    assert len(passed) == 2  # concurrent entry


def test_writer_excludes_readers():
    lock = RWLock()
    order = []
    go = threading.Event()

    def writer():
        with lock.write():
            order.append("w_in")
            time.sleep(0.1)
            order.append("w_out")

    def reader():
        go.wait(1)
        with lock.read():
            order.append("r_in")

    tw = threading.Thread(target=writer)
    tr = threading.Thread(target=reader)
    tw.start()
    time.sleep(0.03)   # let the writer acquire first
    tr.start()
    go.set()
    tw.join(3)
    tr.join(3)
    assert order == ["w_in", "w_out", "r_in"]   # reader waited out the writer


def test_writer_preference_blocks_late_readers():
    lock = RWLock()
    order = []
    r1_inside = threading.Event()

    def long_reader():
        with lock.read():
            r1_inside.set()
            order.append("r1_in")
            time.sleep(0.15)
            order.append("r1_out")

    def writer():
        with lock.write():
            order.append("w_in")

    def late_reader():
        with lock.read():
            order.append("r2_in")

    t_r1 = threading.Thread(target=long_reader)
    t_r1.start()
    r1_inside.wait(1)
    t_w = threading.Thread(target=writer)
    t_w.start()
    time.sleep(0.03)   # writer is now waiting behind r1
    t_r2 = threading.Thread(target=late_reader)
    t_r2.start()       # must queue behind the waiting writer
    for t in (t_r1, t_w, t_r2):
        t.join(3)
    assert order.index("r1_out") < order.index("w_in")   # writer waited for r1
    assert order.index("w_in") < order.index("r2_in")    # late reader waited for writer


# --------------------------------------------------------------------------
# Wiring: the lock is only worth having if the read paths actually take it.
#
# The three tests above prove `RWLock` has the semantics it claims. They say
# nothing about whether anything uses it — and when this was checked, two DB
# read paths did not. A lock nobody takes is indistinguishable from no lock.
# --------------------------------------------------------------------------

import contextlib  # noqa: E402
import shutil  # noqa: E402


class _RecordingLock(RWLock):
    """An RWLock that remembers which side was taken, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []

    @contextlib.contextmanager
    def read(self):
        self.events.append("read")
        with super().read():
            yield

    @contextlib.contextmanager
    def write(self):
        self.events.append("write")
        with super().write():
            yield


def _surface_on_fixture(tmp_path):
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(db)
    lock = _RecordingLock()
    surface._rw_lock = lock
    return surface, lock, db


def test_orient_reads_the_graph_under_the_shared_lock(tmp_path):
    """`orient` calls `describe_graph` against the live connection.

    It is zero-LLM and cheap, which is exactly why it was easy to miss: it does
    not look like a query, but it reads the same file a confirm rewrites.
    """
    surface, lock, _db = _surface_on_fixture(tmp_path)
    surface.orient()
    assert "read" in lock.events, "orient() read the graph without taking the lock"


def test_the_map_plane_reads_under_the_shared_lock(tmp_path):
    """`/graph/map` is the canvas. It opens the owned .lbug directly.

    The catalogue has a private `RLock` of its own, which serialises the
    catalogue's *own* bookkeeping and knows nothing about the operator plane —
    so a confirm and a canvas refresh could touch the file at the same moment.
    """
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from mcp_server.graph_http import GraphCatalogue, graph_routes

    surface, lock, db = _surface_on_fixture(tmp_path)
    catalogue = GraphCatalogue(db, library_dirs=[], on_activate=None)
    app = Starlette(routes=graph_routes(catalogue, current_surface=surface,
                                        rw_lock=lock))
    with TestClient(app) as client:
        response = client.get("/map", params={"graph": db.stem})
    assert response.status_code == 200, response.text
    assert "read" in lock.events, "/graph/map read the graph without taking the lock"


def test_a_write_in_progress_excludes_a_concurrent_orient(tmp_path):
    """End-to-end exclusion, not just "a method was called".

    Holding the write side must actually stall a real read path. Asserted in the
    safe direction: while the write is held the read must NOT complete, and once
    released it must.
    """
    surface, lock, _db = _surface_on_fixture(tmp_path)
    surface.orient()          # warm caches so the timed section is the lock

    finished = threading.Event()
    failed: list[BaseException] = []

    def _reader():
        try:
            surface.orient()
        except BaseException as exc:      # noqa: BLE001 - reported below
            failed.append(exc)
        finally:
            finished.set()

    with lock.write():
        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        assert not finished.wait(timeout=1.5), (
            "orient() completed while the write side was held")

    assert finished.wait(timeout=10), "orient() never completed after the write released"
    thread.join(timeout=5)
    assert not failed, f"reader raised: {failed[0]!r}"


def test_the_engine_reads_its_compass_inside_the_lock(tmp_path):
    """The snapshot must be taken under the lock, not before it.

    `invoke` built its initial state from the session's compass and structural
    index and *then* took the read lock. A confirm landing in between left the
    engine reasoning about the old graph's shape while querying the new graph's
    contents — a torn read that no single lock acquisition would reveal.
    """
    surface, lock, _db = _surface_on_fixture(tmp_path)
    order: list[str] = []

    session = surface._session

    class _Watched:
        """Records reads of the shape-describing fields, passes everything on."""

        def __getattr__(self, name):
            if name in ("compass", "structural_index"):
                order.append(f"snapshot:{name}")
            return getattr(session, name)

    surface._session = _Watched()

    class _Ordering(_RecordingLock):
        @contextlib.contextmanager
        def read(self):
            order.append("lock")
            with RWLock.read(self):
                yield

    surface._rw_lock = _Ordering()
    try:
        surface.discover("what leads to a delayed order?")
    except Exception:
        pass                      # an engine/LLM failure is fine; ordering is not
    finally:
        surface._session = session

    assert "lock" in order, "discover() never took the read lock"
    snapshots = [i for i, e in enumerate(order) if e.startswith("snapshot:")]
    first_lock = order.index("lock")
    assert not [i for i in snapshots if i < first_lock], (
        f"compass/index snapshotted before the lock was taken: {order}")


def test_every_verb_that_reads_the_graph_takes_the_lock(tmp_path):
    """`discover` was guarded. `what_governs` and `check_conformance` were not.

    All three run the engine against the owned `.lbug` — the first through
    `Surface._invoke`, the other two through `EngineAdapter`, which is a
    different path to the same file. Guarding one of three reads as though the
    plane were covered.

    The engine may fail here for want of an API key; the lock is taken before
    any of that, which is the whole point.
    """
    for verb, call in (
        ("discover", lambda s: s.discover("what leads to a delayed order?")),
        ("retrieve", lambda s: s.retrieve({
            "contract_version": "retrieval-v1",
            "steps": [{"tool": "exact_node_lookup",
                       "params": {"label_or_id": "dependency_direction_rule"},
                       "assign_to": "rule"}],
            "collect": "$rule",
        })),
        ("what_governs", lambda s: s.what_governs("what governs refunds?")),
        ("check_conformance",
         lambda s: s.check_conformance(rule_id="r1", artifact="some text")),
    ):
        room = tmp_path / verb
        room.mkdir(parents=True, exist_ok=True)
        surface, lock, _db = _surface_on_fixture(room)
        try:
            call(surface)
        except Exception:
            pass
        assert "read" in lock.events, f"{verb}() read the graph without the lock"


def test_the_read_guard_is_reentrant(tmp_path):
    """Nesting the guard must not hang.

    The lock is writer-preferring, so a thread that holds the read side and then
    asks for it again while a writer is queued waits for that writer — which is
    waiting for the reader it already is. Verbs compose (a conformance ruling
    adjudicates per node), so nesting is reachable, and the failure mode is a
    hung server rather than a wrong answer.
    """
    surface, lock, _db = _surface_on_fixture(tmp_path)

    entered = threading.Event()
    writer_queued = threading.Event()
    done = threading.Event()

    def _writer():
        entered.wait(timeout=5)
        writer_queued.set()
        with lock.write():
            pass

    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()

    def _nested():
        with surface._read_guard():
            entered.set()
            writer_queued.wait(timeout=5)
            time.sleep(0.2)          # let the writer actually queue
            with surface._read_guard():
                pass
        done.set()

    nested = threading.Thread(target=_nested, daemon=True)
    nested.start()
    assert done.wait(timeout=10), "nested read guard deadlocked behind a queued writer"
    nested.join(timeout=5)
    thread.join(timeout=5)


def test_the_l1_auto_commit_path_holds_the_write_side(tmp_path, monkeypatch):
    """The read plane has a write path, and it was the least protected of all.

    `propose(claim_level="L1")` with an admitted policy closes the session,
    mutates the `.lbug`, and reopens. Unguarded, a concurrent reader does not
    merely see stale data — it is holding a connection that gets closed
    underneath it. The code even says "single-owner DB"; the intent was there
    and the exclusion was not.

    The commit itself is stubbed: what is under test is whether the writer's
    exclusion is held while it runs, not whether the gate passes.
    """
    from mcp_server.fixture import ensure_fixture
    from mcp_server.surface import Surface

    db = tmp_path / "g.lbug"
    shutil.copy2(ensure_fixture("runtime/hexagonal_orders.lbug"), db)
    surface = Surface(db, store_path=tmp_path / "store.sqlite",
                      enable_proposals=True)
    lock = _RecordingLock()
    surface._rw_lock = lock

    seen: list[dict] = []

    def _stub_commit(*_args, **_kwargs):
        seen.append(lock._state())
        return {"status": "COMMITTED", "claim_level_effective": "L1"}

    monkeypatch.setattr("mcp_server.proposals.attempt_green_auto_commit", _stub_commit)

    class _AdmittedPolicy:
        l1_admitted = True
        gate_provider = object()
        embedder = None
        admission_evidence = "test"

    surface._write_policy = _AdmittedPolicy()
    try:
        surface.propose(
            encoding={"concepts": [{"id": "n_new", "label": "New",
                                    "text_content": "ADJUDICATES: if X then Y."}],
                      "edges": []},
            target_gap_id="some_gap",
            claim_level="L1",
        )
    finally:
        surface.close()

    assert seen, "the L1 commit path never ran; the test proves nothing"
    assert seen[0]["writer"] is True, (
        f"the graph was mutated without the write side held: {seen[0]}")


def test_listing_the_catalogue_counts_the_owned_graph_under_the_lock(tmp_path):
    """`/graph/graphs` opens every listed graph to count its nodes and edges.

    That includes the one this process owns, so a routine catalogue refresh
    reads the file a confirm is rewriting. The count is wrapped in a
    try/except that degrades to a `read_error` row, which is why this could
    have gone unnoticed indefinitely: the symptom is a wrong number or a
    momentarily unreadable graph, not a crash.

    Library graphs stay unguarded on purpose — nobody in this process writes
    them, and taking a writer-preferring read side for them would queue an
    unrelated browse behind a commit.
    """
    from mcp_server.graph_http import GraphCatalogue

    surface, lock, db = _surface_on_fixture(tmp_path)
    catalogue = GraphCatalogue(db, library_dirs=[], on_activate=None, rw_lock=lock)

    rows = catalogue.list()
    owned = [r for r in rows if r.get("is_current")]
    assert owned, f"the owned graph was not listed: {rows}"
    assert not owned[0].get("read_error"), owned[0]["read_error"]
    assert owned[0].get("node_count"), "the count did not actually run"
    assert "read" in lock.events, (
        "the catalogue counted the owned graph without taking the lock")
