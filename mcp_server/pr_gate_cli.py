"""PR / CI gate packaging — thin CLI over ``pr_gate`` / ``pr_gate_live``.

Usage::

    # Live (needs SST_DB_PATH or --db, OPENROUTER_API_KEY for adjudication)
    graphauthor gate --git-diff --out gate_report.json
    python -m mcp_server.pr_gate_cli --diff-file pr.diff --db graph.lbug

    # Deterministic stub (CI unit / packaging tests — zero LLM)
    graphauthor gate --diff-file pr.diff --stub stub.json --out report.json

Exit codes:
    0  PASS (VIOLATES none). Gaps / INSUFFICIENT do not fail.
    1  FAIL (one or more VIOLATES).
    2  Usage / load error.
    3  PASS but untrusted (rationalization flags) when ``--fail-untrusted``.

Honesty: receipts carry ``rule_id``, but until rule-scoping is fixed,
``check_conformance(rule_id=X)`` may still adjudicate corpus-wide. Do not
market per-rule attribution as proven. Fail-on-VIOLATES remains valid.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_UNTRUSTED = 3

ATTRIBUTION_CAVEAT = (
    "receipt.rule_id is the requested rule; adjudication may still consult "
    "sibling rules until rule-scoping lands — treat attribution as provisional"
)


def exit_code_for_result(result: dict[str, Any], *, fail_untrusted: bool = False) -> int:
    """Map a ``run_pr_gate`` result to a process exit code."""
    if str(result.get("verdict") or "").upper() == "FAIL":
        return EXIT_FAIL
    if fail_untrusted and not result.get("trusted", True):
        return EXIT_UNTRUSTED
    return EXIT_PASS


def load_diff_text(*, diff_file: Path | None, git_diff: bool, staged: bool,
                   stdin_fallback: bool = True) -> str:
    if diff_file is not None:
        return diff_file.read_text(encoding="utf-8")
    if git_diff:
        cmd = ["git", "diff", "--staged"] if staged else ["git", "diff", "HEAD"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "git diff failed")
        return proc.stdout
    if stdin_fallback and not sys.stdin.isatty():
        return sys.stdin.read()
    raise ValueError("provide --diff-file, --git-diff, or pipe a unified diff on stdin")


def load_stub(path: Path) -> dict[str, Any]:
    """Stub file shape::

        {
          "rules": ["api_rule", "db_rule"],
          "graph_version": "gv_test",
          "applicability": {"api_rule": ["src/api/"], "db_rule": ["src/db/"]},
          "verdicts": {"api_rule|src/api/x.py": "VIOLATES", ...}
        }

    Missing verdict keys default to UNGOVERNED. Empty applicability for a rule
    means that rule never applies (same as omitted prefixes).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError("stub JSON must be an object with a 'rules' list")
    return data


def _applicability_fn(stub: dict[str, Any]) -> Callable[[str, str], bool]:
    table = stub.get("applicability") or {}

    def applies(rule_id: str, path: str) -> bool:
        prefixes = table.get(rule_id)
        if prefixes is None:
            # no entry → apply to all paths (caller listed the rule)
            return True
        return any(path.startswith(p) for p in prefixes)

    return applies


def _conformance_fn(stub: dict[str, Any]) -> Callable[[str, str, str], str]:
    verdicts = stub.get("verdicts") or {}

    def conf(rule_id: str, artifact: str, path: str) -> str:
        key = f"{rule_id}|{path}"
        return str(verdicts.get(key) or "UNGOVERNED").upper()

    return conf


def run_stub_gate(diff_text: str, stub: dict[str, Any], *,
                  store_path: Path | None = None,
                  prior_receipts: list[dict] | None = None) -> dict[str, Any]:
    from mcp_server.pr_gate import run_pr_gate

    return run_pr_gate(
        diff_text,
        list(stub["rules"]),
        conformance_fn=_conformance_fn(stub),
        applicability_fn=_applicability_fn(stub),
        graph_version=str(stub.get("graph_version") or "stub"),
        store_path=store_path,
        prior_receipts=prior_receipts,
    )


def run_live_gate(diff_text: str, *, db_path: Path,
                  store_path: Path | None = None,
                  prior_receipts: list[dict] | None = None) -> dict[str, Any]:
    from mcp_server.pr_gate import pr_gate_live
    from mcp_server.surface import Surface

    surface = Surface(db_path, store_path=store_path, capabilities=("query",))
    return pr_gate_live(
        surface, diff_text, store_path=store_path, prior_receipts=prior_receipts,
    )


def enrich_report(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out["packaging"] = {
        "tool": "graphauthor gate",
        "fail_policy": "VIOLATES_only",
        "attribution_caveat": ATTRIBUTION_CAVEAT,
    }
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="graphauthor gate",
        description=(
            "Graph-native PR gate: fail only on VIOLATES; UNGOVERNED → gaps; "
            "INSUFFICIENT → needs_attention. Receipts bind to (diff_hash, graph_version)."
        ),
        epilog=ATTRIBUTION_CAVEAT,
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--diff-file", type=Path, help="Unified diff file")
    src.add_argument("--git-diff", action="store_true",
                     help="Use git diff HEAD (or --staged)")
    ap.add_argument("--staged", action="store_true",
                    help="With --git-diff: staged changes only")
    ap.add_argument("--db", type=Path, default=None,
                    help="Governance .lbug (default: SST_DB_PATH)")
    ap.add_argument("--store", type=Path, default=None,
                    help="Optional event/receipt store (.sqlite)")
    ap.add_argument("--stub", type=Path, default=None,
                    help="Deterministic stub JSON (no LLM; for tests/CI dry runs)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Write full JSON report to this path")
    ap.add_argument("--fail-untrusted", action="store_true",
                    help="Exit 3 when PASS but rationalization flags are present")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress human summary on stderr (JSON still on --out / stdout)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        diff_text = load_diff_text(
            diff_file=args.diff_file, git_diff=args.git_diff, staged=args.staged,
        )
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"graphauthor gate: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if not diff_text.strip():
        from mcp_server.pr_gate import diff_hash as _dh

        # Empty diff → nothing to check → PASS with empty buckets
        result = {
            "verdict": "PASS",
            "trusted": True,
            "diff_hash": _dh(""),
            "graph_version": "",
            "file_count": 0,
            "blocking": [],
            "gaps": [],
            "needs_attention": [],
            "conforming": [],
            "rationalizations": [],
            "receipts": [],
            "note": "empty_diff",
        }
    elif args.stub is not None:
        try:
            stub = load_stub(args.stub)
            result = run_stub_gate(diff_text, stub, store_path=args.store)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"graphauthor gate: stub error: {exc}", file=sys.stderr)
            return EXIT_USAGE
    else:
        db = args.db or Path(os.environ.get("SST_DB_PATH", ""))
        if not db or not Path(db).exists():
            print(
                "graphauthor gate: live mode needs --db or SST_DB_PATH pointing at a .lbug "
                "(or pass --stub for deterministic runs)",
                file=sys.stderr,
            )
            return EXIT_USAGE
        try:
            result = run_live_gate(diff_text, db_path=Path(db), store_path=args.store)
        except Exception as exc:  # noqa: BLE001 — surface to CI
            print(f"graphauthor gate: live gate failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return EXIT_USAGE

    report = enrich_report(result)
    payload = json.dumps(report, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    if not args.quiet:
        v = report.get("verdict")
        print(
            f"graphauthor gate: {v}  files={report.get('file_count')}  "
            f"blocking={len(report.get('blocking') or [])}  "
            f"gaps={len(report.get('gaps') or [])}  "
            f"needs_attention={len(report.get('needs_attention') or [])}  "
            f"trusted={report.get('trusted')}",
            file=sys.stderr,
        )
        print(f"graphauthor gate: note: {ATTRIBUTION_CAVEAT}", file=sys.stderr)

    return exit_code_for_result(report, fail_untrusted=args.fail_untrusted)


if __name__ == "__main__":
    raise SystemExit(main())
