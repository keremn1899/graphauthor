"""Stage-A corpus evaluation: fast deterministic checks + human-readable reports.

Contract:

* Input — a completed ``run_corpus.py`` run directory containing
  ``cases/<case_id>/{packet.json,state.json,meta.json,answer.md}``.
* Output — three reports under ``<run>/reports/``:

  * ``coverage.md``: query_class × seed matrix (pass/fail/missing).
  * ``failures.md``: failures grouped by **symptom**, so one prompt regression
    produces one failure cluster rather than ``N`` identical-looking rows.
  * ``summary.md``: top-line pass rate, regressions, totals.

* Per case — writes ``stage_a.json`` next to the other artifacts so diff /
  judge scripts can read it directly.

No LLM calls. No network. Intended to run in <1s for ~200 cases.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from models import CorpusCase
from reporting import write_json


# ---------------------------------------------------------------------------
# Check result types
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """One named Stage-A check outcome."""
    name: str
    passed: bool
    detail: str = ""
    symptom: str = ""  # Canonical symptom label, used for failures.md grouping.


@dataclass
class StageAResult:
    case_id: str
    seed: str
    query_class: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    harness_error: str = ""  # Set when the harness run itself errored.
    # v8: observed routing tags (may be empty string when the engine trace
    # did not declare them, e.g. pre-v8 runs). Used for per-strategy coverage.
    retrieval_strategy: str = ""
    synthesis_mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "seed": self.seed,
            "query_class": self.query_class,
            "passed": self.passed,
            "harness_error": self.harness_error,
            "symptoms": sorted(set(self.symptoms)),
            "retrieval_strategy": self.retrieval_strategy,
            "synthesis_mode": self.synthesis_mode,
            "checks": [asdict(c) for c in self.checks],
        }


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Stage-A check helpers
# ---------------------------------------------------------------------------


def _edge_types_in_packet(packet: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for edge in packet.get("edge_records") or []:
        et = str(edge.get("edge_type", "")).strip().lower()
        if et:
            out.add(et)
    return out


def _node_ids_in_packet(packet: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for node in packet.get("node_records") or []:
        nid = str(node.get("id", "")).strip()
        if nid:
            out.add(nid)
    return out


def _gap_types_in_state(state: dict[str, Any]) -> list[str]:
    handoff = state.get("company_handoff") or {}
    internal = handoff.get("internal_handoff") or {}
    out: list[str] = []
    for gap in internal.get("gaps") or []:
        gt = str(gap.get("gap_type", "")).strip()
        if gt:
            out.append(gt)
    # Also consider the top-level `gaps` array Battalion keeps.
    for gap in state.get("gaps") or []:
        if isinstance(gap, dict):
            gt = str(gap.get("gap_type", "")).strip()
            if gt:
                out.append(gt)
    return out


_V8_STRATEGIES = {"compass_derivation", "contract_driven", "exploratory"}
_V8_SYNTHESIS_MODES = {"factual", "synthesised"}
_DIRECTED_EDGE_TYPES = {"leadsto", "contains", "expresses"}


def _retrieval_strategy(state: dict[str, Any]) -> str:
    """Read the engine's retrieval strategy from state.

    v8 canonical key is ``retrieval_strategy``. Falls back to v7's
    ``planner_route`` and translates the legacy route names so corpus
    migration is single-sided (YAML in v8 vocabulary, engine may still emit
    v7 names during the migration window).
    """
    raw = state.get("retrieval_strategy") or state.get("planner_route") or ""
    s = str(raw).strip().lower()
    legacy = {
        "map_reader": "compass_derivation",
        "targeted_retrieval": "contract_driven",
    }
    return legacy.get(s, s)


def _synthesis_mode(state: dict[str, Any]) -> str:
    raw = state.get("synthesis_mode") or ""
    return str(raw).strip().lower()


def _trail_orientation_violations(packet: dict[str, Any]) -> list[str]:
    """Return a list of violation detail strings for path_records whose node
    ordering contradicts the canonical direction of the traversed edge type.

    v8 §9: for directed SST types (``leadsto``/``contains``/``expresses``)
    PathRecord ``node_chain`` must be emitted in edge-native direction. We
    detect violations by looking up each ``(node_chain[i], node_chain[i+1])``
    pair against ``edge_records``: if only the reverse edge exists for a
    directed type, the trail was committed in expansion order rather than
    edge-native order and downstream consumers will invert cause/effect.
    """
    edges = packet.get("edge_records") or []
    # Fast lookups keyed by (type, source, target)
    fwd: set[tuple[str, str, str]] = set()
    rev_only: set[tuple[str, str, str]] = set()
    pair_types: dict[tuple[str, str], set[str]] = {}
    for e in edges:
        et = str(e.get("edge_type", "")).strip().lower()
        s = str(e.get("source_id", "")).strip()
        t = str(e.get("target_id", "")).strip()
        if not (et and s and t):
            continue
        fwd.add((et, s, t))
        pair_types.setdefault((s, t), set()).add(et)
        pair_types.setdefault((t, s), set()).add(et + "__rev")

    violations: list[str] = []
    for path in packet.get("path_records") or []:
        node_chain = path.get("node_chain") or []
        edge_chain = path.get("edge_chain") or []
        if len(node_chain) < 2 or len(edge_chain) < len(node_chain) - 1:
            continue
        for i in range(len(node_chain) - 1):
            et = str(edge_chain[i]).strip().lower()
            if et not in _DIRECTED_EDGE_TYPES:
                continue
            a, b = node_chain[i], node_chain[i + 1]
            if (et, a, b) in fwd:
                continue  # canonical orientation
            if (et, b, a) in fwd:
                violations.append(
                    f"path segment {a}->{b} ({et}) contradicts edge_record "
                    f"{b}->{a}; trail emitted in expansion order"
                )
    return violations


def _answer_substr_missing(answer: str, needles: list[str]) -> list[str]:
    if not answer or not needles:
        return []
    low = answer.lower()
    return [n for n in needles if n.lower() not in low]


def _answer_substr_present(answer: str, needles: list[str]) -> list[str]:
    if not answer or not needles:
        return []
    low = answer.lower()
    return [n for n in needles if n.lower() in low]


# ---------------------------------------------------------------------------
# Stage-A evaluator
# ---------------------------------------------------------------------------


def evaluate_stage_a(case: CorpusCase, case_dir: Path) -> StageAResult:
    """Run every enforceable check for ``case`` against its artifact bundle."""
    result = StageAResult(
        case_id=case.id,
        seed=case.seed,
        query_class=case.query_class,
        passed=True,
    )

    packet = _read_json(case_dir / "packet.json")
    state = _read_json(case_dir / "state.json")
    meta = _read_json(case_dir / "meta.json")
    answer = _read_text(case_dir / "answer.md")

    # v8: capture routing tags for coverage reporting
    result.retrieval_strategy = _retrieval_strategy(state)
    result.synthesis_mode = _synthesis_mode(state)

    # Presence check: did the harness actually produce artifacts at all? We
    # look at file presence here rather than parsed content because an empty
    # packet / state dict is legitimate (e.g. the synthetic test fixtures) and
    # must not be misreported as "harness run missing".
    any_artifact = any(
        (case_dir / name).exists()
        for name in ("packet.json", "state.json", "meta.json", "answer.md")
    )
    if not any_artifact:
        result.passed = False
        result.harness_error = "no artifacts (case did not run or write outputs)"
        result.symptoms.append("harness_run_missing")
        return result

    if (case_dir / "error.txt").exists():
        # Harness crashed: capture and stop — deterministic checks cannot be
        # evaluated meaningfully when there is no completed state.
        result.passed = False
        result.harness_error = _read_text(case_dir / "error.txt").splitlines()[0][:400]
        result.symptoms.append("harness_exception")
        return result

    gt = case.ground_truth
    rubric = case.rubric

    # 1) Required edge types ---------------------------------------------------
    if gt.required_edge_types:
        present = _edge_types_in_packet(packet)
        expected = {e.lower() for e in gt.required_edge_types}
        missing = sorted(expected - present)
        ok = not missing
        result.checks.append(
            CheckResult(
                name="required_edge_types",
                passed=ok,
                detail=("" if ok else f"missing edge types: {missing}"),
                symptom="required_edge_type_missing" if not ok else "",
            )
        )

    # 2) Required node ids (any) ----------------------------------------------
    if gt.required_node_ids_any:
        packet_ids = _node_ids_in_packet(packet)
        wanted = set(gt.required_node_ids_any)
        hit = packet_ids & wanted
        ok = bool(hit)
        result.checks.append(
            CheckResult(
                name="required_node_ids_any",
                passed=ok,
                detail=("" if ok else f"none of {sorted(wanted)} in packet"),
                symptom="required_node_missing" if not ok else "",
            )
        )

    # 3) Required node ids (all) ----------------------------------------------
    if gt.required_node_ids_all:
        packet_ids = _node_ids_in_packet(packet)
        wanted = set(gt.required_node_ids_all)
        missing = sorted(wanted - packet_ids)
        ok = not missing
        result.checks.append(
            CheckResult(
                name="required_node_ids_all",
                passed=ok,
                detail=("" if ok else f"missing node ids: {missing}"),
                symptom="required_node_missing" if not ok else "",
            )
        )

    # 4) Min edge / node counts ------------------------------------------------
    if gt.min_edge_count:
        actual = len(packet.get("edge_records") or [])
        ok = actual >= gt.min_edge_count
        result.checks.append(
            CheckResult(
                name="min_edge_count",
                passed=ok,
                detail=("" if ok else f"packet has {actual} edges, need >= {gt.min_edge_count}"),
                symptom="packet_edge_underflow" if not ok else "",
            )
        )
    if gt.min_node_count:
        actual = len(packet.get("node_records") or [])
        ok = actual >= gt.min_node_count
        result.checks.append(
            CheckResult(
                name="min_node_count",
                passed=ok,
                detail=("" if ok else f"packet has {actual} nodes, need >= {gt.min_node_count}"),
                symptom="packet_node_underflow" if not ok else "",
            )
        )

    # 5) Expected verdict ------------------------------------------------------
    if gt.expected_verdict:
        actual = str(meta.get("verdict", "")).upper()
        expected = {v.upper() for v in gt.expected_verdict}
        ok = actual in expected if actual else False
        result.checks.append(
            CheckResult(
                name="expected_verdict",
                passed=ok,
                detail=("" if ok else f"verdict={actual!r}, expected one of {sorted(expected)}"),
                symptom="verdict_mismatch" if not ok else "",
            )
        )

    # 6) Forbidden gap types ---------------------------------------------------
    if gt.expected_gap_types_forbidden:
        observed = _gap_types_in_state(state)
        forbidden = set(gt.expected_gap_types_forbidden)
        hit = sorted(set(observed) & forbidden)
        ok = not hit
        result.checks.append(
            CheckResult(
                name="forbidden_gap_types",
                passed=ok,
                detail=("" if ok else f"forbidden gap types present: {hit}"),
                symptom="forbidden_gap_emitted" if not ok else "",
            )
        )

    # 7) Required gap types ----------------------------------------------------
    if gt.expected_gap_types_required:
        observed = set(_gap_types_in_state(state))
        required = set(gt.expected_gap_types_required)
        missing = sorted(required - observed)
        ok = not missing
        result.checks.append(
            CheckResult(
                name="required_gap_types",
                passed=ok,
                detail=("" if ok else f"required gap types missing: {missing}"),
                symptom="required_gap_missing" if not ok else "",
            )
        )

    # 8) Degradation flag whitelist / denylist --------------------------------
    flags = list(packet.get("degradation_flags") or meta.get("degradation_flags") or [])
    if gt.degradation_flags_forbidden:
        forbidden = set(gt.degradation_flags_forbidden)
        hit = sorted(set(flags) & forbidden)
        ok = not hit
        result.checks.append(
            CheckResult(
                name="degradation_flags_forbidden",
                passed=ok,
                detail=("" if ok else f"forbidden degradation flags present: {hit}"),
                symptom="degradation_forbidden" if not ok else "",
            )
        )
    if gt.degradation_flags_allowed:
        allowed = set(gt.degradation_flags_allowed)
        offenders = sorted(f for f in flags if f not in allowed)
        ok = not offenders
        result.checks.append(
            CheckResult(
                name="degradation_flags_allowed",
                passed=ok,
                detail=("" if ok else f"unexpected degradation flags: {offenders}"),
                symptom="degradation_unexpected" if not ok else "",
            )
        )

    # 9) Answer anchor substrings (lightweight surface check) -----------------
    if rubric.must_not_contain:
        hit = _answer_substr_present(answer, rubric.must_not_contain)
        ok = not hit
        result.checks.append(
            CheckResult(
                name="answer_must_not_contain",
                passed=ok,
                detail=("" if ok else f"answer contains forbidden substrings: {hit}"),
                symptom="answer_forbidden_substring" if not ok else "",
            )
        )
    if rubric.must_contain:
        miss = _answer_substr_missing(answer, rubric.must_contain)
        ok = not miss
        result.checks.append(
            CheckResult(
                name="answer_must_contain",
                passed=ok,
                detail=("" if ok else f"answer missing required substrings: {miss}"),
                symptom="answer_missing_substring" if not ok else "",
            )
        )

    # 10) v8 — retrieval strategy mismatch -----------------------------------
    if gt.expected_retrieval_strategy:
        expected = gt.expected_retrieval_strategy.strip().lower()
        actual = _retrieval_strategy(state)
        ok = (actual == expected)
        hard = bool(gt.strategy_is_hard_expectation)
        # When the engine has not declared a strategy yet (pre-v8 trace) and
        # the corpus does not demand a hard match, leave the check out of the
        # failing set but still surface the symptom for reporting.
        if not actual and not hard:
            pass
        else:
            result.checks.append(
                CheckResult(
                    name="retrieval_strategy",
                    passed=ok if hard else True,
                    detail=("" if ok else f"strategy={actual or '∅'!r}, expected {expected!r} (hard={hard})"),
                    symptom="retrieval_strategy_mismatch" if not ok else "",
                )
            )
            if not ok:
                # Always list as symptom for reporting, regardless of hard/soft.
                result.symptoms.append("retrieval_strategy_mismatch")

    # 11) v9 — synthesis_mode check DEPRECATED (collapsed into uniform synthesis).
    # The field remains on corpus cases for backward compatibility but is no
    # longer enforced. Stage-A never fails on synthesis_mode after v9.
    if False and gt.expected_synthesis_mode:
        pass

    # 12) v8 — compass_derivation packet underpopulation ---------------------
    if gt.compass_landmark_count_expected:
        actual_strategy = _retrieval_strategy(state)
        # Only meaningful for compass_derivation runs. A packet that is thin
        # because the strategy was something else is not an underpopulation
        # bug — the strategy mismatch check above catches that separately.
        if actual_strategy in ("", "compass_derivation"):
            nodes = len(packet.get("node_records") or [])
            ok = nodes >= gt.compass_landmark_count_expected
            result.checks.append(
                CheckResult(
                    name="compass_derivation_packet_population",
                    passed=ok,
                    detail=("" if ok else f"packet has {nodes} nodes, expected >= {gt.compass_landmark_count_expected} from Compass landmarks"),
                    symptom="compass_derivation_packet_underpopulated" if not ok else "",
                )
            )

    # 13) v8 — ILL_POSED vs UNKNOWN_TO_GRAPH distinction ---------------------
    # When the case pins expected_verdict to exactly one of those two, verify
    # the engine emitted the matching one — they are no longer conflated.
    if gt.expected_verdict:
        expected_set = {v.upper() for v in gt.expected_verdict}
        actual_verdict = str(meta.get("verdict", "")).upper()
        v8_terminals = {"ILL_POSED", "UNKNOWN_TO_GRAPH"}
        if expected_set <= v8_terminals and actual_verdict in v8_terminals \
                and actual_verdict not in expected_set:
            result.checks.append(
                CheckResult(
                    name="ill_posed_vs_unknown_to_graph",
                    passed=False,
                    detail=f"verdict={actual_verdict!r}, expected {sorted(expected_set)} — schema gap vs content gap distinction",
                    symptom="unknown_to_graph_vs_ill_posed_mismatch",
                )
            )

    # 14) v8 — trail orientation consistency ---------------------------------
    # Always on. Fires only when a path record contradicts the edge_records
    # for a directed SST type. Empty path_records = no symptom.
    orientation_issues = _trail_orientation_violations(packet)
    if orientation_issues:
        result.checks.append(
            CheckResult(
                name="trail_orientation",
                passed=False,
                detail="; ".join(orientation_issues[:3]) + (" …" if len(orientation_issues) > 3 else ""),
                symptom="trail_orientation_violation",
            )
        )

    # Aggregate
    result.symptoms = sorted({*result.symptoms, *{c.symptom for c in result.checks if not c.passed and c.symptom}})
    result.passed = all(c.passed for c in result.checks)
    return result


# ---------------------------------------------------------------------------
# Run-level orchestration + report writers
# ---------------------------------------------------------------------------


def evaluate_run(
    run_root: Path,
    cases: list[CorpusCase],
    outcomes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate every case under ``run_root/cases/`` and write reports.

    Returns an in-memory summary ``dict`` for programmatic callers (e.g.
    ``scripts/corpus_diff.py``) so they do not have to re-parse the markdown.
    """
    cases_by_id = {c.id: c for c in cases}
    outcomes_by_id: dict[str, dict[str, Any]] = {}
    for o in outcomes or []:
        cid = o.get("case_id")
        if cid:
            outcomes_by_id[cid] = o

    stage_a_results: list[StageAResult] = []
    for case in cases:
        case_dir = run_root / "cases" / case.id
        res = evaluate_stage_a(case, case_dir)
        out = outcomes_by_id.get(case.id, {})
        if not res.harness_error and not out.get("ok", True):
            res.harness_error = str(out.get("error", ""))
            if res.harness_error:
                res.passed = False
                res.symptoms.append("harness_exception")
        # Persist per-case
        write_json(case_dir / "stage_a.json", res.to_dict())
        stage_a_results.append(res)

    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    summary = _write_summary(reports_dir, stage_a_results)
    _write_coverage(reports_dir, stage_a_results, cases_by_id)
    _write_failures(reports_dir, stage_a_results, cases_by_id)
    return summary


def _write_summary(reports_dir: Path, results: list[StageAResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    harness_errors = sum(1 for r in results if r.harness_error)

    per_class: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    for r in results:
        per_class[r.query_class]["pass" if r.passed else "fail"] += 1

    lines = [
        "# Corpus Stage-A Summary",
        "",
        f"- Cases: **{total}**",
        f"- Passed: **{passed}**",
        f"- Failed: **{failed}**",
        f"- Harness errors: **{harness_errors}**",
        f"- Pass rate: **{(passed / total * 100.0 if total else 0.0):.1f}%**",
        "",
        "## By query_class",
        "",
        "| class | pass | fail |",
        "|---|---:|---:|",
    ]
    for cls in sorted(per_class):
        pc = per_class[cls]
        lines.append(f"| `{cls}` | {pc['pass']} | {pc['fail']} |")
    (reports_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "harness_errors": harness_errors,
        "per_class": dict(per_class),
    }


def _write_coverage(
    reports_dir: Path,
    results: list[StageAResult],
    cases_by_id: dict[str, CorpusCase],
) -> None:
    seeds: set[str] = set()
    classes: set[str] = set()
    cells: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"pass": 0, "fail": 0, "total": 0}
    )
    for r in results:
        seeds.add(r.seed)
        classes.add(r.query_class)
        key = (r.query_class, r.seed)
        cells[key]["total"] += 1
        cells[key]["pass" if r.passed else "fail"] += 1

    seed_list = sorted(seeds)
    class_list = sorted(classes)

    header = ["| query_class | " + " | ".join(seed_list) + " |"]
    sep = ["|---|" + "|".join(["---:"] * len(seed_list)) + "|"]
    rows: list[str] = []
    for cls in class_list:
        cells_row: list[str] = []
        for seed in seed_list:
            c = cells.get((cls, seed), {"pass": 0, "fail": 0, "total": 0})
            if c["total"] == 0:
                cells_row.append("–")
            elif c["fail"] == 0:
                cells_row.append(f"✓ {c['pass']}")
            elif c["pass"] == 0:
                cells_row.append(f"✗ {c['fail']}")
            else:
                cells_row.append(f"⚠ {c['pass']}/{c['total']}")
        rows.append(f"| `{cls}` | " + " | ".join(cells_row) + " |")

    # v8: per-strategy coverage (query_class × retrieval_strategy).
    # Cases where the engine did not emit a strategy (pre-v8 trace) collapse
    # into an `∅` column so the migration progress is visible.
    strat_cells: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"pass": 0, "fail": 0, "total": 0}
    )
    strategies: set[str] = set()
    for r in results:
        strat = r.retrieval_strategy or "∅"
        strategies.add(strat)
        key = (r.query_class, strat)
        strat_cells[key]["total"] += 1
        strat_cells[key]["pass" if r.passed else "fail"] += 1
    strat_list = sorted(strategies)
    strat_header = ["| query_class | " + " | ".join(strat_list) + " |"]
    strat_sep = ["|---|" + "|".join(["---:"] * len(strat_list)) + "|"]
    strat_rows: list[str] = []
    for cls in class_list:
        row_cells: list[str] = []
        for strat in strat_list:
            c = strat_cells.get((cls, strat), {"pass": 0, "fail": 0, "total": 0})
            if c["total"] == 0:
                row_cells.append("–")
            elif c["fail"] == 0:
                row_cells.append(f"✓ {c['pass']}")
            elif c["pass"] == 0:
                row_cells.append(f"✗ {c['fail']}")
            else:
                row_cells.append(f"⚠ {c['pass']}/{c['total']}")
        strat_rows.append(f"| `{cls}` | " + " | ".join(row_cells) + " |")

    (reports_dir / "coverage.md").write_text(
        "\n".join(
            [
                "# Coverage matrix (query_class × seed)",
                "",
                "- `✓ N`: all N cases passed.",
                "- `⚠ P/T`: P passed of T total.",
                "- `✗ N`: all N cases failed.",
                "- `–`: no case in this cell.",
                "",
                *header,
                *sep,
                *rows,
                "",
                "## Per-strategy coverage (v8: query_class × retrieval_strategy)",
                "",
                "The `∅` column aggregates cases where the engine trace did not "
                "declare a `retrieval_strategy` — expected during the v7→v8 "
                "migration window and should drain to zero post-migration.",
                "",
                *strat_header,
                *strat_sep,
                *strat_rows,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_failures(
    reports_dir: Path,
    results: list[StageAResult],
    cases_by_id: dict[str, CorpusCase],
) -> None:
    # Group by symptom → list of cases (and per-check details).
    by_symptom: dict[str, list[tuple[StageAResult, CheckResult]]] = defaultdict(list)
    for r in results:
        if r.passed:
            continue
        if not r.checks and r.harness_error:
            by_symptom["harness_exception"].append(
                (r, CheckResult(name="harness", passed=False, detail=r.harness_error))
            )
            continue
        for c in r.checks:
            if c.passed:
                continue
            sym = c.symptom or "unclassified"
            by_symptom[sym].append((r, c))

    if not by_symptom:
        (reports_dir / "failures.md").write_text(
            "# Corpus Stage-A Failures\n\nNo failures — all cases passed Stage A.\n",
            encoding="utf-8",
        )
        return

    lines = [
        "# Corpus Stage-A Failures (grouped by symptom)",
        "",
        "Failures are grouped by the deterministic **symptom** label the "
        "evaluator attached, so one underlying regression shows up as one "
        "failure cluster rather than _N_ look-alike rows.",
        "",
    ]
    # Optional hypothesis map for common symptoms — short, high-level, non-prescriptive.
    hypothesis: dict[str, str] = {
        "required_edge_type_missing": (
            "Backend did not preserve or expand an edge type the case expected. "
            "Check the Planner's retrieval program and the tool that should have "
            "surfaced this edge type (typically `hop_expansion` / `find_paths`)."
        ),
        "required_node_missing": (
            "Seed or planner program did not reach the target node(s). "
            "Compass may be mis-oriented, or `vector_search` anchors drifted."
        ),
        "packet_edge_underflow": (
            "Packet contains fewer edges than expected. Likely a tool dispatch "
            "gap or a premature Squad termination."
        ),
        "packet_node_underflow": (
            "Packet contains fewer nodes than expected. Check seeds and hop expansion."
        ),
        "verdict_mismatch": (
            "Planner Confirmation returned an unexpected verdict. Usually "
            "tracks to (a) premature EXHAUSTED (map-exhaustion fired too soon) "
            "or (b) unexpected ALTERNATIVE when the answer was reachable."
        ),
        "forbidden_gap_emitted": (
            "Company asserted a gap the packet contradicts. This is a "
            "`semantic_violation:false_relation_denial` class bug — check "
            "`_semantic_validation_logic`."
        ),
        "required_gap_missing": (
            "Company failed to report an expected gap. Meta_gap honesty "
            "regression — Company may be hallucinating rather than "
            "abstaining."
        ),
        "degradation_forbidden": (
            "A degradation flag explicitly banned by this case appeared. "
            "Treat as a hard infrastructure regression."
        ),
        "degradation_unexpected": (
            "A degradation flag appeared that is outside the whitelist for "
            "this case. Either the case whitelist needs updating or a new "
            "failure mode has appeared."
        ),
        "answer_forbidden_substring": (
            "Battalion produced a phrase the rubric forbids (e.g. a "
            "false-denial sentence)."
        ),
        "answer_missing_substring": (
            "Battalion omitted an anchor that should have appeared (node "
            "label, entity name, etc.). Often a provenance-paging failure."
        ),
        "harness_exception": (
            "The harness itself crashed. This is an infrastructure bug; "
            "read `error.txt` in the case directory."
        ),
        "retrieval_strategy_mismatch": (
            "v8: Planner's `retrieval_strategy` differs from the case's "
            "expectation. Either the corpus ground_truth is stale from v6/v7 "
            "authoring or the Planner's classification prompt is drifting."
        ),
        "synthesis_mode_mismatch": (
            "v8: Planner's `synthesis_mode` differs from the expected axis. "
            "Check the Planner prompt's synthesis_mode rubric."
        ),
        "compass_derivation_packet_underpopulated": (
            "v8: compass_derivation packet contains fewer NodeRecords than "
            "the Compass landmarks for the declared target. The Backend's "
            "compass-to-packet conversion is silently eliding landmarks."
        ),
        "unknown_to_graph_vs_ill_posed_mismatch": (
            "v8: schema-gap vs content-gap confusion. ILL_POSED means the "
            "graph's shape cannot answer this class; UNKNOWN_TO_GRAPH means "
            "the schema supports the query but no matching content exists. "
            "Verdict logic must distinguish these after the reseed budget."
        ),
        "trail_orientation_violation": (
            "v8 §9: a PathRecord was emitted in expansion order rather than "
            "the edge-native canonical direction. Downstream (Battalion) will "
            "invert cause/effect on LEADSTO trails. Reorder PathRecord "
            "`node_chain` in the trail builder."
        ),
    }

    for sym in sorted(by_symptom):
        entries = by_symptom[sym]
        lines.append(f"## `{sym}` — {len(entries)} case(s)")
        lines.append("")
        if sym in hypothesis:
            lines.append(f"_Root-cause hypothesis:_ {hypothesis[sym]}")
            lines.append("")
        for r, c in entries:
            case = cases_by_id.get(r.case_id)
            label = (case.query if case else r.case_id)[:100]
            lines.append(
                f"- **{r.case_id}** (seed=`{r.seed}`, class=`{r.query_class}`) — "
                f"{c.name}: {c.detail or 'failed'}"
            )
            lines.append(f"  - query: _{label}_")
        lines.append("")

    (reports_dir / "failures.md").write_text("\n".join(lines), encoding="utf-8")
