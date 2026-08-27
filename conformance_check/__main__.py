"""On-demand conformance check — rule + real file → typed verdict.

Founder loop (your own repo):
    # Scan all architecture rules on uncommitted changes (needs .env + graph)
    set -a && source .env && set +a
    conda run -n agentic-graphrag python -m conformance_check --scan --git-diff

    # Free structural scan on a file you're editing
    conda run -n agentic-graphrag python -m conformance_check --scan --file path/to/file.py --dry-run

    # One rule, targeted
    conda run -n agentic-graphrag python -m conformance_check \\
      --rule InteractionSeamRule --file interaction/tool_surface.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys

from conformance_check.framing import list_rule_ids
from conformance_check.surface import (
    check_conformance,
    report_to_json,
    run_sanity_batch,
    scan_conformance,
    verdict_exit_code,
)


def _print_report(report, fmt: str) -> None:
    if fmt in ("agent", "both"):
        print(report.to_agent_block())
        if fmt == "both":
            print("---")
    if fmt in ("json", "both"):
        print(json.dumps(report_to_json(report), indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check code changes against a governance handbook",
        epilog=(
            "Founder loop: python -m conformance_check --scan --git-diff  "
            "(add --handbook credential for credential governance demo)"
        ),
    )
    ap.add_argument(
        "--handbook",
        choices=("sst", "credential"),
        default="sst",
        help="Handbook constitution (default: sst architecture)",
    )
    ap.add_argument("--rule", help="One rule id (e.g. InteractionSeamRule)")
    ap.add_argument(
        "--scan",
        action="store_true",
        help="Run all handbook rules against the change (default reach-for mode)",
    )
    ap.add_argument("--scope-only", action="store_true", help="Scope question only (moat / out-of-handbook)")
    ap.add_argument("--file", type=str, help="Path to source file")
    ap.add_argument("--lines", type=str, help="Line range 120-145 or single line 120")
    ap.add_argument("--diff", type=str, help="Path to unified diff file")
    ap.add_argument("--git-diff", action="store_true", help="Use git diff of working tree as the change")
    ap.add_argument("--staged", action="store_true", help="With --git-diff: use staged changes only")
    ap.add_argument("--snippet", type=str, help="Inline code snippet")
    ap.add_argument("--question", type=str, help="Override focused conformance question")
    ap.add_argument("--dry-run", action="store_true", help="Structural/SAS pre-filters only (no LLM)")
    ap.add_argument(
        "--format",
        choices=("agent", "json", "both"),
        default="agent",
        help="Output format (default: human-readable agent block)",
    )
    ap.add_argument("--list-rules", action="store_true", help="List known rule ids and exit")
    ap.add_argument(
        "--sanity-batch",
        action="store_true",
        help="Run batch reproduction guard (structural cases if --dry-run)",
    )
    args = ap.parse_args(argv)

    if args.list_rules:
        for rid in list_rule_ids(handbook=args.handbook):
            print(rid)
        return 0

    if args.sanity_batch:
        summary = run_sanity_batch(dry_run=args.dry_run, handbook=args.handbook)
        if args.format in ("json", "both"):
            print(json.dumps(summary, indent=2))
        else:
            print(f"SANITY_BATCH: {summary['outcome']} ({summary['matches']}/{summary['total']})")
            for row in summary["rows"]:
                ok = "OK" if row.get("match") else "MISS"
                print(
                    f"  {row['case_id']:28s} → {row['overall']:22s} "
                    f"(founder={row['founder_expected']}) [{ok}]"
                )
        return 0 if summary["outcome"] == "BATCH_REPRO_OK" else 1

    has_change = any([args.file, args.diff, args.snippet, args.git_diff])
    if not has_change:
        ap.error("Provide --file, --diff, --snippet, or --git-diff")

    if args.scan:
        if args.rule or args.scope_only:
            ap.error("--scan cannot be combined with --rule or --scope-only")
        report = scan_conformance(
            snippet=args.snippet,
            file=args.file,
            lines=args.lines,
            diff=args.diff,
            git_diff=args.git_diff,
            staged=args.staged,
            dry_run=args.dry_run,
            handbook=args.handbook,
        )
        _print_report(report, args.format)
        return verdict_exit_code(report.overall)

    if not args.scope_only and not args.rule:
        ap.error("Provide --scan, --rule, or --scope-only")

    report = check_conformance(
        rule=args.rule,
        snippet=args.snippet,
        file=args.file,
        lines=args.lines,
        diff=args.diff,
        git_diff=args.git_diff,
        staged=args.staged,
        question=args.question,
        scope_only=args.scope_only,
        dry_run=args.dry_run,
        handbook=args.handbook,
    )

    _print_report(report, args.format)
    return verdict_exit_code(report.overall)


if __name__ == "__main__":
    raise SystemExit(main())
