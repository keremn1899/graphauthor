"""Turn (rule + code change) into a focused conformance case for the engine.

Handoff: design [new]/callable-conformance-surface-handoff.md §2–3
"""

from __future__ import annotations

import re
from pathlib import Path

# Rule-specific question templates — mirror the dogfood cases.py framing pattern.
_RULE_QUESTIONS: dict[str, str] = {
    "PacketImmutabilityRule": (
        "Per the architecture handbook (PacketImmutabilityRule): does this proposed "
        "code change conform to EvidencePacket immutability — may it append or mutate "
        "node_records, edge_records, or path_records outside backend_execute / "
        "backend_execute_recovery?"
    ),
    "ContractDeterminismRule": (
        "Per the architecture handbook (ContractDeterminismRule): does this proposed "
        "code change conform to contract determinism — may build_agent_response or "
        "contract.py invoke an LLM or other non-deterministic dependency?"
    ),
    "InteractionSeamRule": (
        "Per the architecture handbook (InteractionSeamRule): does this proposed "
        "code change conform to the interaction seam — must interaction/ delegate "
        "pipeline execution only through EngineAdapter without importing battalion, "
        "planner, or agent_graph tiers?"
    ),
    "LatePayloadRule": (
        "Per the architecture handbook (LatePayloadRule): does this proposed "
        "code change conform to late payload paging — may upstream tiers (Planner, "
        "Squad, Company) access full text_content before Battalion synthesis?"
    ),
    "GovernanceStructuredVerdictRule": (
        "Per the architecture handbook (GovernanceStructuredVerdictRule): does this "
        "proposed code change preserve structured governance_verdict / "
        "conformance_ruling emission — must Battalion emit typed governance json "
        "rather than inferring GOVERNED vs UNGOVERNED from prose via regex?"
    ),
}

_SCOPE_QUESTION_DEFAULT = (
    "Per the architecture handbook: does published policy govern this specific "
    "question about the code change shown?"
)

# Scope-only moat framing — explicit out-of-handbook ask; demands honest UNGOVERNED.
_SCOPE_MOAT_SUFFIX = (
    " If the SST architecture handbook has no rule governing this topic, respond "
    "UNGOVERNED and name the ungoverned predicate explicitly — do not invent policy "
    "or cite unrelated handbook rules."
)

# Insufficient-evidence framing — no proposed change / cannot ground.
_INSUFFICIENT_SUFFIX = (
    " The snippet does NOT show a complete proposed change. If the evidence is "
    "insufficient to determine governance or conformance, respond with "
    "INSUFFICIENT_EVIDENCE — do not guess GOVERNED, UNGOVERNED, CONFORMS, or VIOLATES; "
    "do not invent a violation or policy."
)

# Real-file conform framing — existing code slice, not hypothetical.
_EXISTING_CODE_PREFIX = "Existing code in this repository (not a hypothetical proposal):"


def list_rule_ids(handbook: str | None = None) -> list[str]:
    from conformance_check.handbooks import load_tagged_rules, resolve_handbook

    cfg = resolve_handbook(handbook)
    return [r.rule_id for r in load_tagged_rules(cfg)]


def _ensure_dogfood_path() -> None:
    """Backward-compatible path setup for SST handbook."""
    from conformance_check.handbooks import ensure_handbook_path, resolve_handbook

    ensure_handbook_path(resolve_handbook("sst"))


def resolve_rule(rule_name: str, handbook: str | None = None):
    """Resolve a rule id or alias to TaggedRule."""
    from conformance_check.handbooks import load_tagged_rules, resolve_handbook

    cfg = resolve_handbook(handbook)
    tagged = load_tagged_rules(cfg)
    key = rule_name.strip()
    by_id = {r.rule_id: r for r in tagged}
    if key in by_id:
        return by_id[key]
    lower = key.lower()
    for rid, tr in by_id.items():
        if rid.lower() == lower or rid.lower().startswith(lower):
            return tr
    raise ValueError(
        f"Unknown rule {rule_name!r}. Known: {', '.join(sorted(by_id))}"
    )


def _rule_questions(handbook: str | None = None) -> dict[str, str]:
    from conformance_check.handbooks import load_rule_questions, resolve_handbook

    return load_rule_questions(resolve_handbook(handbook))


def _scope_defaults(handbook: str | None = None) -> tuple[str, str]:
    from conformance_check.handbooks import load_scope_defaults, resolve_handbook

    return load_scope_defaults(resolve_handbook(handbook))


def frame_conformance_question(
    rule_id: str | None,
    *,
    question: str | None = None,
    handbook: str | None = None,
) -> str:
    """Build the focused conformance question for a rule (or scope-only)."""
    if question:
        return question.strip()
    scope_default, _ = _scope_defaults(handbook)
    if not rule_id:
        return scope_default
    templates = _rule_questions(handbook)
    template = templates.get(rule_id)
    if not template:
        label = "credential governance handbook" if handbook == "credential" else "architecture handbook"
        return (
            f"Per the {label} ({rule_id}): does this proposed "
            f"code change conform to {rule_id}?"
        )
    return template


def frame_scope_moat_question(core_question: str, *, handbook: str | None = None) -> str:
    """Scope-only question for genuine out-of-handbook predicates (moat check)."""
    _, moat_suffix = _scope_defaults(handbook)
    q = core_question.strip()
    handbook_prefix = (
        "per the credential governance handbook"
        if handbook == "credential"
        else "per the architecture handbook"
    )
    if handbook_prefix not in q.lower():
        prefix = (
            "Per the credential governance handbook:"
            if handbook == "credential"
            else "Per the architecture handbook:"
        )
        q = f"{prefix} {q}"
    return q + moat_suffix


def frame_insufficient_question(core_question: str, *, handbook: str | None = None) -> str:
    """Scope question when evidence cannot support a governance determination."""
    scope_default, _ = _scope_defaults(handbook)
    q = core_question.strip()
    if not q.lower().startswith(scope_default.split(":")[0].lower()):
        q = f"{scope_default.rstrip('.?')} — {q}"
    return q + _INSUFFICIENT_SUFFIX


def frame_existing_code_question(
    rule_id: str, module_hint: str, core_question: str, *, handbook: str | None = None
) -> str:
    """Focused question for a real-file conforming slice (not a hypothetical diff)."""
    base = core_question.strip()
    if not base:
        base = frame_conformance_question(rule_id, handbook=handbook)
    return f"{_EXISTING_CODE_PREFIX} {module_hint}\n\n{base}"


def frame_proposed_change_question(
    rule_id: str, module_hint: str, core_question: str, *, handbook: str | None = None
) -> str:
    """Focused question for a proposed violating change to a real module."""
    base = core_question.strip() or frame_conformance_question(rule_id, handbook=handbook)
    return (
        f"Proposed change to {module_hint} (not yet in the repository):\n\n{base}"
    )


def parse_lines_spec(spec: str) -> tuple[int, int]:
    """Parse '120-145' or '120' into 1-based inclusive line range."""
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        start, end = int(a), int(b)
    else:
        start = end = int(spec)
    if start < 1 or end < start:
        raise ValueError(f"Invalid line range: {spec!r}")
    return start, end


def read_snippet_from_file(
    path: Path,
    *,
    lines: tuple[int, int] | None = None,
    max_chars: int = 12_000,
) -> tuple[str, str]:
    """Read file (or line slice) as snippet. Returns (snippet, label)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = path.name
    if lines:
        start, end = lines
        all_lines = text.splitlines()
        if end > len(all_lines):
            end = len(all_lines)
        snippet = "\n".join(all_lines[start - 1 : end])
        label = f"{rel}:{start}-{end}"
    else:
        snippet = text
        label = rel
    if len(snippet) > max_chars:
        snippet = snippet[:max_chars] + "\n# ... (truncated)"
    return snippet, label


def read_snippet_from_diff(path: Path, *, max_chars: int = 12_000) -> tuple[str, str]:
    """Read a unified diff as snippet context."""
    text = path.read_text(encoding="utf-8", errors="replace")
    label = f"diff:{path.name}"
    if len(text) > max_chars:
        text = text[:max_chars] + "\n# ... (truncated)"
    return text, label


def build_case(
    *,
    rule_id: str | None,
    snippet: str,
    snippet_label: str = "code change",
    question: str | None = None,
    change_id: str = "cli",
    ruling_allow_signals: list[str] | None = None,
    ruling_deny_signals: list[str] | None = None,
    question_style: str | None = None,
    handbook: str | None = None,
) -> dict:
    """Assemble a dispatch-router case dict from rule + change."""
    scope_default, _ = _scope_defaults(handbook)
    if question is None and question_style == "scope_moat":
        q = frame_scope_moat_question(scope_default, handbook=handbook)
    elif question is None and question_style == "insufficient":
        q = frame_insufficient_question(scope_default, handbook=handbook)
    else:
        q = frame_conformance_question(rule_id, question=question, handbook=handbook)
    case: dict = {
        "id": change_id,
        "snippet": snippet.strip(),
        "snippet_label": snippet_label,
        "question": q,
    }
    if rule_id:
        case["rule_ids"] = [rule_id]
    else:
        case["rule_ids"] = []
    if ruling_allow_signals:
        case["ruling_allow_signals"] = ruling_allow_signals
    if ruling_deny_signals:
        case["ruling_deny_signals"] = ruling_deny_signals
    return case


def structural_only_case_ids(handbook: str | None = None) -> list[str]:
    """Batch cases fully decidable without LLM (STRUCTURAL rules only)."""
    from conformance_check.handbooks import load_dispatch_cases, load_tagged_rules, resolve_handbook
    from governance_dispatch import EnforcementMechanism

    cfg = resolve_handbook(handbook)
    mech = {r.rule_id: r.mechanism for r in load_tagged_rules(cfg)}
    ids: list[str] = []
    for case in load_dispatch_cases(cfg):
        rids = case.get("rule_ids") or []
        if not rids:
            continue
        if all(mech.get(r) == EnforcementMechanism.STRUCTURAL for r in rids):
            ids.append(case["id"])
    return ids
