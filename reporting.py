"""Shared test reporting helpers for human + LLM analysis workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORT_ROOT = ROOT / "data" / "test_reports"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _slugify(text: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9_-]+", "_", (text or "").strip().lower())
    return out.strip("_") or "unknown"


def build_run_id(test_type: str, suite: str | None = None) -> str:
    ts = utc_timestamp()
    st = _slugify(test_type)
    if suite:
        return f"{st}_{_slugify(suite)}_{ts}"
    return f"{st}_{ts}"


def friendly_filename(
    test_type: str,
    suite_or_seed: str,
    case_or_scenario: str,
    result: str,
    ext: str,
) -> str:
    return (
        f"{_slugify(test_type)}__{_slugify(suite_or_seed)}__"
        f"{_slugify(case_or_scenario)}__{_slugify(result)}__{utc_timestamp()}.{ext.lstrip('.')}"
    )


@dataclass(frozen=True)
class ReportPaths:
    run_id: str
    root: Path
    raw: Path
    normalized: Path
    reports: Path


def ensure_report_paths(test_type: str, run_id: str) -> ReportPaths:
    root = REPORT_ROOT / _slugify(test_type) / utc_date() / run_id
    raw = root / "raw"
    normalized = root / "normalized"
    reports = root / "reports"
    for p in (raw, normalized, reports):
        p.mkdir(parents=True, exist_ok=True)
    readme = reports / "README.md"
    if not readme.exists():
        readme.write_text(
            "\n".join(
                [
                    f"# {test_type} report folder",
                    "",
                    "- `summary.md`: quick human summary.",
                    "- `summary.json` or `cases.jsonl`: normalized machine-readable records.",
                    "- `faults.json`: categorized failures for LLM diagnosis.",
                    "",
                    "Use `case_id` and `run_id` to join records across files.",
                ]
            ),
            encoding="utf-8",
        )
    return ReportPaths(run_id=run_id, root=root, raw=raw, normalized=normalized, reports=reports)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def append_index(entry: dict[str, Any]) -> None:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    idx_path = REPORT_ROOT / "index.json"
    rows: list[dict[str, Any]] = []
    if idx_path.exists():
        rows = json.loads(idx_path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            rows = []
    rows.append(entry)
    write_json(idx_path, rows)


def classify_fault(case: dict[str, Any]) -> str:
    if case.get("error_type"):
        et = str(case["error_type"]).lower()
        if "timeout" in et:
            return "timeout"
        if "provider" in et or "openrouter" in et:
            return "provider_failure"
        if "tool" in et:
            return "tool_failure"
        if "state" in et or "schema" in et:
            return "state_contract_failure"
    if case.get("forbidden_violations", 0) > 0:
        return "hallucination_risk"
    if case.get("answerable") is False and not case.get("gap_reported", False):
        return "abstention_failure"
    if case.get("retrieval_recall") is not None and case.get("retrieval_recall", 1.0) < 0.4:
        return "retrieval_miss"
    return "unknown"


def parse_sst_log_lines(log_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in log_text.splitlines():
        if "|" not in line:
            continue
        parts = [x.strip() for x in line.split("|")]
        name = parts[0]
        fields: dict[str, Any] = {}
        for token in parts[1:]:
            if "=" not in token:
                continue
            k, v = token.split("=", 1)
            fields[k.strip()] = v.strip().strip("'")
        events.append({"event": name, "fields": fields, "raw": line})
    return events
