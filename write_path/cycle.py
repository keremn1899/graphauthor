"""Part C — repeatable encode-connect-verify cycle with automatic distractor gate."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from write_path.distractor import check_closure, check_distractors, verdict_rates
from write_path.models import (
    ConfirmedCuration,
    CycleGateResult,
    EncodeCycleResult,
)


class CorpusAdapter(Protocol):
    """Domain hook — apply human-supplied source to corpus; return db path."""

    def apply_encoding(self, confirmed: ConfirmedCuration) -> str:
        """Return path to updated corpus DB."""
        ...

    def encoding_spec(self, gap_id: str) -> dict:
        """Connectivity metadata for closure/distractor checks."""
        ...


CaptureFn = Callable[[Any, dict, Any, Any], dict]


class WritePathCycleRunner:
    """Orchestrates one confirmed curation through verify + distractor gate."""

    def __init__(
        self,
        *,
        adapter: CorpusAdapter,
        capture_fn: CaptureFn,
        queries_for: Callable[[list[str]], list[dict]],
        policy_in_grounding: Callable,
        adjacent_only: Callable,
        gap_anchor_ids: tuple[str, ...],
        flaky_anchor_ids: tuple[str, ...],
        intentional_closure_ids: tuple[str, ...],
        intrinsic_ids: tuple[str, ...],
        verify_query_ids: list[str],
        min_gov_rate: float = 0.7,
    ):
        self._adapter = adapter
        self._capture = capture_fn
        self._queries_for = queries_for
        self._policy_in_grounding = policy_in_grounding
        self._adjacent_only = adjacent_only
        self._gap_anchor_ids = gap_anchor_ids
        self._flaky_anchor_ids = flaky_anchor_ids
        self._intentional_closure_ids = intentional_closure_ids
        self._intrinsic_ids = intrinsic_ids
        self._verify_query_ids = verify_query_ids
        self._min_gov_rate = min_gov_rate
        self._encoded_gaps: list[str] = []
        self._baseline: dict[str, dict] | None = None

    @property
    def encoded_gaps(self) -> list[str]:
        return list(self._encoded_gaps)

    def measure_baseline(
        self,
        graph,
        compass,
        si,
        *,
        runs: int,
    ) -> dict[str, dict]:
        rows = self._run_captures(graph, compass, si, runs=runs, phase="baseline")
        baseline = {
            qid: verdict_rates([r for r in rows if r["query_id"] == qid])
            for qid in self._verify_query_ids
        }
        self._baseline = baseline
        return baseline

    def run_confirmed_cycle(
        self,
        confirmed: ConfirmedCuration,
        graph,
        compass,
        si,
        *,
        runs: int,
        refresh_fn: Callable[[str], tuple[Any, Any, Any]] | None = None,
    ) -> EncodeCycleResult:
        if self._baseline is None:
            raise RuntimeError("call measure_baseline() first")

        gap_id = confirmed.gap_id
        spec = self._adapter.encoding_spec(gap_id)

        db_path = self._adapter.apply_encoding(confirmed)
        if refresh_fn is not None:
            graph, compass, si = refresh_fn(db_path)

        rows = self._run_captures(
            graph, compass, si, runs=runs, phase=f"post_{gap_id}",
        )
        by_q: dict[str, list[dict]] = {}
        for r in rows:
            by_q.setdefault(r["query_id"], []).append(r)

        closure = check_closure(
            gap_id,
            by_q.get(gap_id, []),
            policy_id=spec["policy_id"],
            also_valid=spec.get("also_valid_policies"),
            wrong_adjacent=spec.get("wrong_adjacent_only"),
            policy_in_grounding=self._policy_in_grounding,
            adjacent_only=self._adjacent_only,
            min_gov_rate=self._min_gov_rate,
        )

        encoded_so_far = self._encoded_gaps + [gap_id]
        clean, findings = check_distractors(
            self._baseline,
            by_q,
            encoded_gap_ids=encoded_so_far,
            gap_anchor_ids=self._gap_anchor_ids,
            flaky_anchor_ids=self._flaky_anchor_ids,
            intentional_closure_ids=self._intentional_closure_ids,
            intrinsic_ids=self._intrinsic_ids,
        )

        intrinsic_ok = all(
            verdict_rates(by_q.get(qid, [])).get("distribution", {}).get("GOVERNED", 0) == 0
            for qid in self._intrinsic_ids
            if qid in by_q
        )

        gate = CycleGateResult(
            distractor_clean=clean and intrinsic_ok,
            findings=findings,
            closure_ok=closure["closes_cleanly"],
            right_reason=closure["right_reason"],
            governed=closure["governed"],
            n=closure["n"],
        )

        committed = gate.distractor_clean and gate.closure_ok
        failure = ""
        if not gate.closure_ok:
            failure = "closure_failed_or_wrong_reason"
        elif not gate.distractor_clean:
            failure = "distractor_gate_failed"

        if committed:
            self._encoded_gaps.append(gap_id)

        return EncodeCycleResult(
            gap_id=gap_id,
            committed=committed,
            gate=gate,
            failure_reason=failure,
            db_path=db_path,
            captures=rows,
        )

    def _run_captures(
        self,
        graph,
        compass,
        si,
        *,
        runs: int,
        phase: str,
    ) -> list[dict]:
        queries = self._queries_for(self._verify_query_ids)
        rows: list[dict] = []
        for run in range(1, runs + 1):
            for q in queries:
                rec = self._capture(graph, q, compass, si)
                rec.update({"run": run, "phase": phase, "query_id": q["id"]})
                rows.append(rec)
                print(
                    f"  [{phase}] run{run:02d} {q['id']:12s} "
                    f"gov={rec.get('governance_verdict', '?'):10s}",
                    flush=True,
                )
        return rows
