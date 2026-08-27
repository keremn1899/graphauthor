"""Callable conformance surface — rule + real file → typed verdict.

Handoffs:
  design [new]/callable-conformance-surface-handoff.md
  design [new]/checkpoint-consolidation-self-use-handoff.md
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from conformance_verdict import ConformanceKind, ConformanceVerdict
from governance_dispatch import DispatchRouter, RuleDispatchResult, UnifiedConformanceReport, _merge_verdicts

from conformance_check.framing import (
    build_case,
    list_rule_ids,
    read_snippet_from_diff,
    read_snippet_from_file,
    resolve_rule,
    structural_only_case_ids,
)

PROJ = Path(__file__).resolve().parents[1]

VERDICT_EXIT_CODES: dict[ConformanceKind, int] = {
    ConformanceKind.CONFORMS: 0,
    ConformanceKind.VIOLATES: 1,
    ConformanceKind.UNGOVERNED: 2,
    ConformanceKind.INSUFFICIENT_EVIDENCE: 3,
}


def verdict_exit_code(verdict: ConformanceKind) -> int:
    return VERDICT_EXIT_CODES.get(verdict, 3)


def _ensure_dogfood_path() -> None:
    dogfood = PROJ / "examples" / "dogfood"
    if str(dogfood) not in sys.path:
        sys.path.insert(0, str(dogfood))
    if str(PROJ) not in sys.path:
        sys.path.insert(0, str(PROJ))


def _make_semantic_runner(*, dry_run: bool, handbook: str | None = None):
    if dry_run:
        return None

    from conformance_check.handbooks import ensure_handbook_path, resolve_handbook

    cfg = resolve_handbook(handbook)
    ensure_handbook_path(cfg)
    dogfood = PROJ / "examples" / "dogfood"
    if str(dogfood) not in sys.path:
        sys.path.insert(0, str(dogfood))
    from framework import GOV_FRAME, setup_engine
    from harness_core import capture_case

    if not cfg.db_path.exists():
        raise FileNotFoundError(
            f"Handbook graph missing at {cfg.db_path}. Run: {cfg.build_command}"
        )
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise EnvironmentError("OPENROUTER_API_KEY required for semantic/SAS paths (or use dry_run=True)")

    os.environ.setdefault("SST_LLM_TEMPERATURE", "0")
    graph, compass, si = setup_engine(cfg.db_path)

    def _semantic(case: dict) -> ConformanceVerdict:
        rec = capture_case(graph, case, GOV_FRAME, compass, si)
        return ConformanceVerdict.model_validate(rec["conformance_verdict"])

    return _semantic


def _handbook_db_conn(handbook: str | None = None):
    from conformance_check.handbooks import resolve_handbook
    from engine import get_connection

    cfg = resolve_handbook(handbook)
    if not cfg.db_path.exists():
        return None
    return get_connection(db_path=cfg.db_path)


def _dispatch_router(
    *,
    handbook: str | None,
    project_root: Path,
    dry_run: bool,
):
    from conformance_check.handbooks import load_tagged_rules, resolve_handbook

    cfg = resolve_handbook(handbook)
    tagged_rules = load_tagged_rules(cfg)
    db_conn = _handbook_db_conn(handbook)
    semantic_runner = _make_semantic_runner(dry_run=dry_run, handbook=handbook)
    return DispatchRouter(
        tagged_rules,
        project_root,
        semantic_runner=semantic_runner,
        db_conn=db_conn,
    )


def structural_insufficient_reason(
    *,
    snippet: str | None = None,
    diff_text: str | None = None,
) -> str | None:
    """Return a reason when there is structurally nothing to judge (no LLM call)."""
    if snippet is not None:
        stripped = snippet.strip()
        if not stripped:
            return "empty snippet — no code to judge"
        substantive = [
            ln
            for ln in stripped.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if not substantive:
            return "snippet contains no substantive code"
    if diff_text is not None:
        stripped = diff_text.strip()
        if not stripped:
            return "empty diff — no changes to judge"
        has_change = any(
            ln.startswith(("+", "-"))
            and not ln.startswith(("+++", "---", "@@"))
            for ln in stripped.splitlines()
        )
        if not has_change:
            return "diff has no added/removed lines"
    return None


def read_git_diff(*, staged: bool = False, cwd: Path | None = None) -> tuple[str, str]:
    """Return (diff_text, label) from the working tree."""
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    result = subprocess.run(
        cmd,
        cwd=cwd or PROJ,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git diff failed")
    label = "git diff --staged" if staged else "git diff"
    return result.stdout, label


def _insufficient_report(change_id: str, reason: str) -> UnifiedConformanceReport:
    """Structural INSUFFICIENT — CLI detected absent evidence without calling the engine."""
    return UnifiedConformanceReport(
        change_id=change_id,
        rule_results=[],
        overall=ConformanceKind.INSUFFICIENT_EVIDENCE,
        structural_count=0,
        semantic_llm_calls=0,
        mis_dispatch_flags=[],
        tagging_notes=[f"structural_insufficient: {reason}"],
    )


def _load_change_snippet(
    *,
    snippet: str | None = None,
    file: Path | str | None = None,
    lines: str | None = None,
    diff: Path | str | None = None,
    git_diff: bool = False,
    staged: bool = False,
) -> tuple[str, str]:
    """Resolve snippet text and label from inputs."""
    if snippet is not None:
        return snippet, "inline snippet"
    if git_diff:
        text, label = read_git_diff(staged=staged)
        reason = structural_insufficient_reason(diff_text=text)
        if reason:
            raise _StructuralInsufficient(reason)
        return text, label
    if file is not None:
        fpath = Path(file)
        if fpath.is_file() and fpath.stat().st_size == 0:
            raise _StructuralInsufficient("empty file — no code to judge")
        line_range = None
        if lines:
            from conformance_check.framing import parse_lines_spec

            line_range = parse_lines_spec(lines)
        return read_snippet_from_file(fpath, lines=line_range)
    if diff is not None:
        text, label = read_snippet_from_diff(Path(diff))
        reason = structural_insufficient_reason(diff_text=text)
        if reason:
            raise _StructuralInsufficient(reason)
        return text, label
    raise ValueError("Provide snippet, file, diff, or --git-diff")


class _StructuralInsufficient(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def check_conformance(
    *,
    rule: str | None = None,
    snippet: str | None = None,
    file: Path | str | None = None,
    lines: str | None = None,
    diff: Path | str | None = None,
    question: str | None = None,
    scope_only: bool = False,
    change_id: str = "cli",
    dry_run: bool = False,
    project_root: Path | str | None = None,
    ruling_allow_signals: list[str] | None = None,
    ruling_deny_signals: list[str] | None = None,
    question_style: str | None = None,
    git_diff: bool = False,
    staged: bool = False,
    handbook: str | None = None,
    target_file: str | None = None,
) -> UnifiedConformanceReport:
    """Check one rule against one code change; returns merged conformance report."""
    from conformance_check.handbooks import resolve_handbook

    resolve_handbook(handbook)
    root = Path(project_root) if project_root else PROJ

    if scope_only and rule:
        raise ValueError("Use scope_only without rule, or pass rule without scope_only")

    rule_id: str | None = None
    if rule:
        rule_id = resolve_rule(rule, handbook=handbook).rule_id

    try:
        snippet, label = _load_change_snippet(
            snippet=snippet,
            file=file,
            lines=lines,
            diff=diff,
            git_diff=git_diff,
            staged=staged,
        )
    except _StructuralInsufficient as exc:
        return _insufficient_report(change_id, exc.reason)

    reason = structural_insufficient_reason(snippet=snippet)
    if reason:
        return _insufficient_report(change_id, reason)

    case = build_case(
        rule_id=rule_id,
        snippet=snippet,
        snippet_label=label,
        question=question,
        change_id=change_id,
        ruling_allow_signals=ruling_allow_signals,
        ruling_deny_signals=ruling_deny_signals,
        question_style=question_style,
        handbook=handbook,
    )
    if file is not None:
        case["target_file"] = str(file)
    elif target_file:
        # Snippet callers (e.g. MCP) can name the component's file without a
        # disk read — required for the applicability gate to identify the
        # component and short-circuit OOS rule×component at zero LLM.
        case["target_file"] = str(target_file)

    router = _dispatch_router(handbook=handbook, project_root=root, dry_run=dry_run)
    return router.dispatch_change(case)


def scan_conformance(
    *,
    snippet: str | None = None,
    file: Path | str | None = None,
    lines: str | None = None,
    diff: Path | str | None = None,
    git_diff: bool = False,
    staged: bool = False,
    change_id: str = "scan",
    dry_run: bool = False,
    project_root: Path | str | None = None,
    handbook: str | None = None,
) -> UnifiedConformanceReport:
    """Run all handbook rules against one change; merge into a single report."""
    try:
        snippet, label = _load_change_snippet(
            snippet=snippet,
            file=file,
            lines=lines,
            diff=diff,
            git_diff=git_diff,
            staged=staged,
        )
    except _StructuralInsufficient as exc:
        return _insufficient_report(change_id, exc.reason)

    reason = structural_insufficient_reason(snippet=snippet)
    if reason:
        return _insufficient_report(change_id, reason)

    rule_results: list[RuleDispatchResult] = []
    total_llm = 0
    flags: list[str] = []
    notes: list[str] = []
    structural_n = 0

    for rid in list_rule_ids(handbook=handbook):
        report = check_conformance(
            rule=rid,
            snippet=snippet,
            file=file,
            lines=lines,
            change_id=f"{change_id}:{rid}",
            dry_run=dry_run,
            project_root=project_root,
            handbook=handbook,
        )
        rule_results.extend(report.rule_results)
        total_llm += report.semantic_llm_calls
        flags.extend(report.mis_dispatch_flags)
        notes.extend(report.tagging_notes)
        structural_n += report.structural_count

    overall = _merge_verdicts(rule_results) if rule_results else ConformanceKind.INSUFFICIENT_EVIDENCE

    return UnifiedConformanceReport(
        change_id=change_id,
        rule_results=rule_results,
        overall=overall,
        structural_count=structural_n,
        semantic_llm_calls=total_llm,
        mis_dispatch_flags=list(dict.fromkeys(flags)),
        tagging_notes=list(dict.fromkeys(notes)),
    )


def report_to_json(report: UnifiedConformanceReport) -> dict[str, Any]:
    """Serialize report for machine consumers."""
    return {
        "change_id": report.change_id,
        "overall": report.overall.value,
        "exit_code": verdict_exit_code(report.overall),
        "structural_count": report.structural_count,
        "semantic_llm_calls": report.semantic_llm_calls,
        "mis_dispatch_flags": report.mis_dispatch_flags,
        "tagging_notes": report.tagging_notes,
        "agent_block": report.to_agent_block(),
        "rule_results": [
            {
                "rule_id": rr.rule_id,
                "mechanism": rr.mechanism.value,
                "merged_verdict": rr.merged_verdict.value if rr.merged_verdict else None,
                "short_circuited": rr.short_circuited,
                "structural": rr.structural.model_dump() if rr.structural else None,
                "structural_signal": rr.structural_signal.model_dump() if rr.structural_signal else None,
                "semantic": rr.semantic.model_dump() if rr.semantic else None,
            }
            for rr in report.rule_results
        ],
    }


def run_sanity_batch(*, dry_run: bool = True, handbook: str | None = None) -> dict[str, Any]:
    """Regression guard: reproduce batch probe verdicts through the callable."""
    from conformance_check.handbooks import load_dispatch_cases, load_tagged_rules, resolve_handbook

    cfg = resolve_handbook(handbook)
    tagged_rules = load_tagged_rules(cfg)
    mech = {r.rule_id: r.mechanism for r in tagged_rules}
    if dry_run:
        case_ids = set(structural_only_case_ids(handbook=handbook))
        cases = [c for c in load_dispatch_cases(cfg) if c["id"] in case_ids]
    else:
        cases = load_dispatch_cases(cfg)

    semantic_runner = _make_semantic_runner(dry_run=dry_run, handbook=handbook)
    router = _dispatch_router(handbook=handbook, project_root=PROJ, dry_run=dry_run)

    rows: list[dict] = []
    for batch_case in cases:
        case = dict(batch_case)
        report = router.dispatch_change(case)
        founder = batch_case.get("founder_expected", "")
        match = report.overall.value == founder if founder else None
        rows.append(
            {
                "case_id": batch_case["id"],
                "founder_expected": founder,
                "overall": report.overall.value,
                "match": match,
                "mechanisms": [mech.get(r, "?") for r in batch_case.get("rule_ids") or []],
            }
        )

    matches = sum(1 for r in rows if r.get("match"))
    total = len(rows)
    rate = matches / max(total, 1)
    if rate == 1.0:
        outcome = "BATCH_REPRO_OK"
    elif rate >= 0.8:
        outcome = "BATCH_REPRO_PARTIAL"
    else:
        outcome = "BATCH_REPRO_FAIL"

    return {
        "outcome": outcome,
        "dry_run": dry_run,
        "match_rate": rate,
        "matches": matches,
        "total": total,
        "rows": rows,
    }
