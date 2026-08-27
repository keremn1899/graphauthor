"""Graph-driven dispatch — unified governance routing.

One constitution (governance graph rules), enforcement dispatched by tag:
  STRUCTURAL → deterministic predicate (test/lint stub)
  SEMANTIC   → engine ConformanceVerdict (LLM judgment)
  SEMANTIC_ASSISTED_STRUCTURAL → structural pre-filter SIGNAL + engine VERDICT
    (structural may narrow/focus; NEVER falsely clear a semantic violation)

Handoffs:
  design [new]/graph-driven-dispatch-probe-handoff.md
  design [new]/semantic-assisted-structural-third-tag-handoff.md
"""

from __future__ import annotations

import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from conformance_verdict import ConformanceKind, ConformanceVerdict


class EnforcementMechanism(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    SEMANTIC = "SEMANTIC"
    SEMANTIC_ASSISTED_STRUCTURAL = "SEMANTIC_ASSISTED_STRUCTURAL"
    AMBIGUOUS = "AMBIGUOUS"  # human must confirm; probe records friction


class StructuralSignalKind(str, Enum):
    """Pre-filter output — a SIGNAL, not a verdict."""

    CANDIDATE = "CANDIDATE"  # potential violation pattern present
    LOCUS = "LOCUS"  # places the engine should examine
    ABSENT = "ABSENT"  # pattern not found (NOT decisive for SAS rules)
    CLEAR_NEGATIVE = "CLEAR_NEGATIVE"  # structurally provable absence (rare)


class StructuralSignal(BaseModel):
    """Structural pre-filter signal for SEMANTIC_ASSISTED_STRUCTURAL rules.

    Invariant: for SAS rules, ABSENT must never short-circuit to CONFORMS —
    structural absence does not prove semantic conformance.
    """

    rule_id: str
    kind: StructuralSignalKind
    detail: str = ""
    loci: list[str] = Field(default_factory=list)
    allow_short_circuit: bool = False  # True only when absence is decisive


class TaggedRule(BaseModel):
    """Rule metadata — enforcement tag is human-gated at construction."""

    rule_id: str
    node_id: str
    label: str
    mechanism: EnforcementMechanism
    human_confirmed: bool = True
    ambiguity_note: str = ""
    structural_check_id: str | None = None
    # SAS only: pre-filter id (signal producer, not verdict)
    prefilter_id: str | None = None


class StructuralCheckResult(BaseModel):
    rule_id: str
    passed: bool
    verdict: ConformanceKind
    mechanism_used: EnforcementMechanism = EnforcementMechanism.STRUCTURAL
    detail: str = ""
    checked_paths: list[str] = Field(default_factory=list)


class RuleDispatchResult(BaseModel):
    rule_id: str
    mechanism: EnforcementMechanism
    structural: StructuralCheckResult | None = None
    structural_signal: StructuralSignal | None = None
    semantic: ConformanceVerdict | None = None
    merged_verdict: ConformanceKind | None = None
    short_circuited: bool = False
    mis_dispatch_risk: str = ""


class UnifiedConformanceReport(BaseModel):
    """Merged conformance over a change — structural + semantic."""

    change_id: str
    rule_results: list[RuleDispatchResult]
    overall: ConformanceKind
    structural_count: int = 0
    semantic_llm_calls: int = 0
    mis_dispatch_flags: list[str] = Field(default_factory=list)
    tagging_notes: list[str] = Field(default_factory=list)

    def to_agent_block(self) -> str:
        lines = [f"UNIFIED_CONFORMANCE: {self.overall.value}"]
        for rr in self.rule_results:
            if rr.mechanism == EnforcementMechanism.SEMANTIC_ASSISTED_STRUCTURAL:
                sig = rr.structural_signal
                sig_s = f"{sig.kind.value}: {sig.detail[:80]}" if sig else "no signal"
                eng = rr.semantic.verdict.value if rr.semantic else "?"
                mv = rr.merged_verdict.value if rr.merged_verdict else eng
                sc = " [short-circuit]" if rr.short_circuited else ""
                lines.append(
                    f"  [SAS] {rr.rule_id}: {mv}{sc} (signal={sig_s}; engine={eng})"
                )
            elif rr.structural:
                s = rr.structural
                lines.append(
                    f"  [{s.mechanism_used.value}] {rr.rule_id}: {s.verdict.value} — {s.detail[:120]}"
                )
            elif rr.semantic:
                lines.append(
                    f"  [SEMANTIC] {rr.rule_id}: {rr.semantic.verdict.value}"
                )
        if self.mis_dispatch_flags:
            lines.append("MIS_DISPATCH_RISK:")
            for f in self.mis_dispatch_flags:
                lines.append(f"  - {f}")
        return "\n".join(lines)


# --- Structural predicates (minimal real checks + snippet analysis) -----------------

_FORBIDDEN_INTERACTION_IMPORTS = (
    "from battalion import",
    "from planner import",
    "from agent_graph import",
    "import battalion",
    "import planner",
    "battalion_synthesize(",
)

_ADAPTER_ALLOWLIST = frozenset({"engine_adapter.py"})

_CONTRACT_FORBIDDEN = (
    "openrouter",
    "call_openrouter",
    "ChatOpenAI",
    "invoke_llm",
)

_BATTALION_PACKET_MUTATION = re.compile(
    r"evidence_packet.*\.append\s*\(|"
    r'evidence_packet\s*\[.*\]\s*=.*append|'
    r'setdefault\s*\(\s*["\']node_records["\']',
    re.I | re.S,
)

_REMOVE_GOV_JSON = re.compile(
    r"remove.*governance.*json|infer.*from prose|delete.*governance.*header",
    re.I,
)


def _snippet_verdict(snippet: str, *, fail_patterns: list[str | re.Pattern], pass_msg: str, fail_msg: str) -> tuple[bool, str]:
    for pat in fail_patterns:
        if isinstance(pat, str):
            if pat.lower() in snippet.lower():
                return False, fail_msg
        elif pat.search(snippet):
            return False, fail_msg
    return True, pass_msg


def check_interaction_seam(snippet: str, project_root: Path) -> StructuralCheckResult:
    rule_id = "InteractionSeamRule"
    paths: list[str] = []
    # Snippet (proposed change)
    for pat in _FORBIDDEN_INTERACTION_IMPORTS:
        if pat in snippet:
            return StructuralCheckResult(
                rule_id=rule_id,
                passed=False,
                verdict=ConformanceKind.VIOLATES,
                detail=f"Snippet imports/invokes forbidden pipeline: {pat!r}",
            )
    # Repo scan — interaction/ must not execute pipeline tiers
    interaction = project_root / "interaction"
    if interaction.is_dir():
        for py in sorted(interaction.rglob("*.py")):
            if py.name.startswith("_"):
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            paths.append(str(py.relative_to(project_root)))
            for pat in _FORBIDDEN_INTERACTION_IMPORTS:
                if pat in text:
                    return StructuralCheckResult(
                        rule_id=rule_id,
                        passed=False,
                        verdict=ConformanceKind.VIOLATES,
                        detail=f"{py.name} contains forbidden pattern {pat!r}",
                        checked_paths=paths,
                    )
            if py.name not in _ADAPTER_ALLOWLIST and "graph.invoke(" in text:
                return StructuralCheckResult(
                    rule_id=rule_id,
                    passed=False,
                    verdict=ConformanceKind.VIOLATES,
                    detail=f"{py.name} calls graph.invoke outside EngineAdapter",
                    checked_paths=paths,
                )
    ok = "interaction/ has no direct pipeline execution imports" if paths else "snippet has no seam violation"
    return StructuralCheckResult(
        rule_id=rule_id,
        passed=True,
        verdict=ConformanceKind.CONFORMS,
        detail=ok,
        checked_paths=paths,
    )


def check_contract_determinism(snippet: str, project_root: Path) -> StructuralCheckResult:
    rule_id = "ContractDeterminismRule"
    for tok in _CONTRACT_FORBIDDEN:
        if tok.lower() in snippet.lower():
            return StructuralCheckResult(
                rule_id=rule_id,
                passed=False,
                verdict=ConformanceKind.VIOLATES,
                detail=f"Snippet references non-deterministic dependency: {tok}",
            )
    contract = project_root / "contract.py"
    paths = []
    if contract.is_file():
        text = contract.read_text(encoding="utf-8", errors="replace")
        paths.append("contract.py")
        for tok in _CONTRACT_FORBIDDEN:
            if tok.lower() in text.lower():
                return StructuralCheckResult(
                    rule_id=rule_id,
                    passed=False,
                    verdict=ConformanceKind.VIOLATES,
                    detail=f"contract.py contains {tok!r}",
                    checked_paths=paths,
                )
    return StructuralCheckResult(
        rule_id=rule_id,
        passed=True,
        verdict=ConformanceKind.CONFORMS,
        detail="contract.py has no OpenRouter/LLM imports",
        checked_paths=paths,
    )


def check_governance_structured(snippet: str, project_root: Path) -> StructuralCheckResult:
    rule_id = "GovernanceStructuredVerdictRule"
    if _REMOVE_GOV_JSON.search(snippet):
        return StructuralCheckResult(
            rule_id=rule_id,
            passed=False,
            verdict=ConformanceKind.VIOLATES,
            detail="Snippet proposes removing structured governance json",
        )
    battalion = project_root / "battalion.py"
    paths = []
    if battalion.is_file():
        text = battalion.read_text(encoding="utf-8", errors="replace")
        paths.append("battalion.py")
        if "governance_verdict" not in text or "conformance_ruling" not in text:
            return StructuralCheckResult(
                rule_id=rule_id,
                passed=False,
                verdict=ConformanceKind.VIOLATES,
                detail="battalion.py missing governance_verdict / conformance_ruling emission",
                checked_paths=paths,
            )
    return StructuralCheckResult(
        rule_id=rule_id,
        passed=True,
        verdict=ConformanceKind.CONFORMS,
        detail="battalion.py emits structured governance fields",
        checked_paths=paths,
    )


def check_packet_immutability_structural(snippet: str, project_root: Path) -> StructuralCheckResult:
    """Legacy STRUCTURAL-only facet (not used for SAS — see prefilter_packet_immutability)."""
    rule_id = "PacketImmutabilityRule"
    if _BATTALION_PACKET_MUTATION.search(snippet):
        if "battalion" in snippet.lower() or "Battalion" in snippet:
            return StructuralCheckResult(
                rule_id=rule_id,
                passed=False,
                verdict=ConformanceKind.VIOLATES,
                detail="Snippet shows Battalion mutating evidence_packet (structural facet)",
            )
    if "append_to_evidence_packet" in snippet or "backend_execute" in snippet:
        return StructuralCheckResult(
            rule_id=rule_id,
            passed=True,
            verdict=ConformanceKind.CONFORMS,
            detail="Snippet uses authorized backend append path (structural facet)",
        )
    return StructuralCheckResult(
        rule_id=rule_id,
        passed=True,
        verdict=ConformanceKind.CONFORMS,
        detail="No structural packet-mutation pattern in snippet (semantic judgment may still apply)",
    )


# --- SAS pre-filters (SIGNAL only; never a verdict) --------------------------------

_EARLY_TIER_MARKERS = (
    "squad_dispatch",
    "squad_",
    "company_prep",
    "company_llm",
    "planner_initial",
    "planner_confirm",
)
_TEXT_CONTENT_LITERAL = re.compile(
    r"""(?:\[["']text_content["']\]|\.get\(\s*["']text_content["']|\.text_content\b)""",
    re.I,
)


def prefilter_packet_immutability(snippet: str, project_root: Path) -> StructuralSignal:
    """Mutation-pattern pre-filter. ABSENT is NOT decisive (allow_short_circuit=False)."""
    rule_id = "PacketImmutabilityRule"
    loci: list[str] = []
    if _BATTALION_PACKET_MUTATION.search(snippet) and (
        "battalion" in snippet.lower() or "Battalion" in snippet
    ):
        loci.append("snippet:evidence_packet mutation pattern (.append / setdefault node_records)")
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.CANDIDATE,
            detail="Obvious packet mutation pattern in Battalion-scoped snippet",
            loci=loci,
            allow_short_circuit=False,
        )
    # Authorized backend path — still not a clear-negative for unauthorized paths elsewhere
    if "append_to_evidence_packet" in snippet and "backend" in snippet.lower():
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.LOCUS,
            detail="Authorized backend append path present — engine must confirm intent",
            loci=["snippet:append_to_evidence_packet"],
            allow_short_circuit=False,
        )
    return StructuralSignal(
        rule_id=rule_id,
        kind=StructuralSignalKind.ABSENT,
        detail=(
            "No .append/setdefault mutation pattern — structural absence is NOT decisive; "
            "engine must still judge write intent"
        ),
        allow_short_circuit=False,
    )


def prefilter_late_payload(snippet: str, project_root: Path) -> StructuralSignal:
    """Early-tier text_content access pre-filter. ABSENT is NOT decisive."""
    rule_id = "LatePayloadRule"
    early = any(m in snippet.lower() for m in _EARLY_TIER_MARKERS) or any(
        m in snippet for m in ("Squad", "Company", "Planner")
    )
    literal_hits = list(_TEXT_CONTENT_LITERAL.finditer(snippet))
    if early and literal_hits:
        loci = [f"snippet:text_content@{m.start()}" for m in literal_hits[:5]]
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.CANDIDATE,
            detail="Early tier appears to access text_content literally",
            loci=loci,
            allow_short_circuit=False,
        )
    if literal_hits:
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.LOCUS,
            detail="text_content access present — tier context needs judgment",
            loci=[f"snippet:text_content@{m.start()}" for m in literal_hits[:5]],
            allow_short_circuit=False,
        )
    return StructuralSignal(
        rule_id=rule_id,
        kind=StructuralSignalKind.ABSENT,
        detail=(
            "No literal text_content access pattern — structural absence is NOT decisive; "
            "engine must still judge early-tier payload paging"
        ),
        allow_short_circuit=False,
    )


# --- Credential governance (demo foundation) ------------------------------------

_HARDCODED_CREDENTIAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"""(?:api[_-]?key|password|secret|client_secret|private_key)\s*=\s*["'][^"']{8,}["']""", re.I),
    re.compile(r"""sk-(?:live|test)-[a-zA-Z0-9]{12,}""", re.I),
    re.compile(r"""-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"""),
    re.compile(r"""postgresql://[^:]+:[^@]+@""", re.I),
]

_LOG_SINK_MARKERS = re.compile(
    r"\b(?:logger|logging|log)\.(?:debug|info|warning|error|exception|critical)\s*\(",
    re.I,
)
_SECRET_NEAR_LOG = re.compile(
    r"\b(?:api[_-]?key|secret|password|token|client_secret|private_key)\b",
    re.I,
)


def _credential_software_dirs(project_root: Path) -> list[Path]:
    """Software trees for credential structural repo scans."""
    candidates: list[Path] = []
    env = os.environ.get("CREDENTIAL_GOVERNANCE_REPO", "").strip()
    if env:
        candidates.append(Path(env).expanduser().resolve() / "software")
    sw_env = os.environ.get("CREDENTIAL_SOFTWARE_DIR", "").strip()
    if sw_env:
        candidates.append(Path(sw_env).expanduser().resolve())
    candidates.append(project_root.parent / "credential-governance" / "software")
    candidates.append(project_root / "examples" / "credential-governance" / "software")
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        r = p.resolve()
        if r.is_dir() and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def check_no_hardcoded_credential(snippet: str, project_root: Path) -> StructuralCheckResult:
    rule_id = "NoHardcodedCredentialRule"
    for pat in _HARDCODED_CREDENTIAL_PATTERNS:
        m = pat.search(snippet)
        if m:
            return StructuralCheckResult(
                rule_id=rule_id,
                passed=False,
                verdict=ConformanceKind.VIOLATES,
                detail=f"Hardcoded credential literal pattern: {m.group(0)[:60]!r}",
            )
    paths: list[str] = []
    for sw_dir in _credential_software_dirs(project_root):
        for py in sorted(sw_dir.rglob("*.py")):
            if py.name.startswith("_"):
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            paths.append(str(py))
            for pat in _HARDCODED_CREDENTIAL_PATTERNS:
                if pat.search(text):
                    return StructuralCheckResult(
                        rule_id=rule_id,
                        passed=False,
                        verdict=ConformanceKind.VIOLATES,
                        detail=f"{py.name} contains hardcoded credential pattern",
                        checked_paths=paths,
                    )
    ok = "no hardcoded credential literals in snippet or software/" if paths else "snippet has no hardcoded credential literal"
    return StructuralCheckResult(
        rule_id=rule_id,
        passed=True,
        verdict=ConformanceKind.CONFORMS,
        detail=ok,
        checked_paths=paths,
    )


def prefilter_secret_in_sink(snippet: str, project_root: Path) -> StructuralSignal:
    rule_id = "SecretInSinkRule"
    log_hits = list(_LOG_SINK_MARKERS.finditer(snippet))
    secret_hits = list(_SECRET_NEAR_LOG.finditer(snippet))
    if log_hits and secret_hits:
        loci = [f"snippet:log@{log_hits[0].start()}", f"snippet:secret_ref@{secret_hits[0].start()}"]
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.CANDIDATE,
            detail="Log/telemetry call near secret-named variable — engine must judge if value is secret",
            loci=loci,
            allow_short_circuit=False,
        )
    if log_hits:
        return StructuralSignal(
            rule_id=rule_id,
            kind=StructuralSignalKind.LOCUS,
            detail="Log call present — engine must confirm no secret material in sink",
            loci=[f"snippet:log@{m.start()}" for m in log_hits[:3]],
            allow_short_circuit=False,
        )
    return StructuralSignal(
        rule_id=rule_id,
        kind=StructuralSignalKind.ABSENT,
        detail="No log-call + secret-name co-occurrence pattern — structural absence is NOT decisive",
        allow_short_circuit=False,
    )


STRUCTURAL_CHECKS: dict[str, Callable[[str, Path], StructuralCheckResult]] = {
    "interaction_seam": check_interaction_seam,
    "contract_determinism": check_contract_determinism,
    "governance_structured": check_governance_structured,
    "packet_immutability_structural": check_packet_immutability_structural,
    "no_hardcoded_credential": check_no_hardcoded_credential,
}

PREFILTERS: dict[str, Callable[[str, Path], StructuralSignal]] = {
    "packet_immutability": prefilter_packet_immutability,
    "late_payload": prefilter_late_payload,
    "secret_in_sink": prefilter_secret_in_sink,
}


def merge_sas_verdict(
    signal: StructuralSignal,
    engine: ConformanceVerdict | None,
    *,
    short_circuited: bool = False,
) -> ConformanceKind:
    """Merge structural SIGNAL + engine VERDICT for SAS rules.

    Invariant: structural may narrow/focus; it may NEVER override the engine's
    semantic backstop. ABSENT never implies CONFORMS unless allow_short_circuit
    and CLEAR_NEGATIVE (not used for Packet/LatePayload).
    """
    if short_circuited and signal.allow_short_circuit and signal.kind == StructuralSignalKind.CLEAR_NEGATIVE:
        return ConformanceKind.CONFORMS
    if engine is None:
        return ConformanceKind.INSUFFICIENT_EVIDENCE
    # Preserve closure — never collapse UNGOVERNED / INSUFFICIENT
    return engine.verdict


def focus_case_with_signal(case: dict, signal: StructuralSignal) -> dict:
    """Inject structural signal into the case so engine judgment is focused."""
    focused = dict(case)
    loci = ", ".join(signal.loci) if signal.loci else "(none)"
    focus_block = (
        f"\n\n[Structural pre-filter signal — not a verdict]\n"
        f"kind={signal.kind.value}\n"
        f"detail={signal.detail}\n"
        f"loci={loci}\n"
        f"Note: structural absence does not prove conformance; judge write/read intent."
    )
    focused["question"] = case.get("question", "") + focus_block
    focused["_structural_signal"] = signal.model_dump()
    return focused


def _merge_verdicts(results: list[RuleDispatchResult]) -> ConformanceKind:
    if not results:
        return ConformanceKind.INSUFFICIENT_EVIDENCE
    kinds: list[ConformanceKind] = []
    for rr in results:
        if rr.merged_verdict is not None:
            kinds.append(rr.merged_verdict)
        elif rr.structural:
            kinds.append(rr.structural.verdict)
        elif rr.semantic:
            kinds.append(rr.semantic.verdict)
    if ConformanceKind.VIOLATES in kinds:
        return ConformanceKind.VIOLATES
    if all(k == ConformanceKind.UNGOVERNED for k in kinds):
        return ConformanceKind.UNGOVERNED
    if ConformanceKind.INSUFFICIENT_EVIDENCE in kinds:
        if ConformanceKind.CONFORMS in kinds or ConformanceKind.VIOLATES in kinds:
            pass  # mixed — VIOLATES already handled
        elif all(k in (ConformanceKind.INSUFFICIENT_EVIDENCE, ConformanceKind.UNGOVERNED) for k in kinds):
            return ConformanceKind.INSUFFICIENT_EVIDENCE
    if all(k == ConformanceKind.CONFORMS for k in kinds):
        return ConformanceKind.CONFORMS
    if ConformanceKind.UNGOVERNED in kinds and ConformanceKind.CONFORMS in kinds:
        return ConformanceKind.VIOLATES if ConformanceKind.VIOLATES in kinds else ConformanceKind.CONFORMS
    return ConformanceKind.CONFORMS if ConformanceKind.CONFORMS in kinds else kinds[0]


class DispatchRouter:
    """Classify rules by tag → dispatch → merge."""

    def __init__(
        self,
        rules: list[TaggedRule],
        project_root: Path,
        *,
        semantic_runner: Callable[[dict], ConformanceVerdict] | None = None,
        db_conn: Any | None = None,
    ):
        self.rules = {r.rule_id: r for r in rules}
        self.project_root = project_root
        self.semantic_runner = semantic_runner
        self.db_conn = db_conn
        self._semantic_calls = 0

    def _applicability_verdict(self, rule_id: str, case: dict) -> ConformanceVerdict | None:
        if not self.db_conn:
            return None
        from component_applicability import (
            applicability_verdict,
            evaluate_component_applicability,
        )

        result = evaluate_component_applicability(
            self.db_conn,
            rule_id=rule_id,
            snippet_label=str(case.get("snippet_label") or ""),
            target_file=case.get("target_file"),
        )
        if not result.gated:
            return None
        fields = applicability_verdict(result)
        return ConformanceVerdict(
            verdict=ConformanceKind.UNGOVERNED,
            rule=fields["rule"],
            predicate=fields["predicate"],
            grounding=fields["grounding"],
            confidence_note=fields["confidence_note"],
            governance_status=fields["governance_status"],
            engine_verdict=fields["engine_verdict"],
        )

    @property
    def semantic_llm_calls(self) -> int:
        return self._semantic_calls

    def rules_for_case(self, rule_ids: list[str]) -> list[TaggedRule]:
        out = []
        for rid in rule_ids:
            if rid in self.rules:
                out.append(self.rules[rid])
        return out

    def dispatch_rule(
        self,
        tagged: TaggedRule,
        case: dict,
        *,
        allow_semantic: bool = True,
    ) -> RuleDispatchResult:
        mech = tagged.mechanism
        mis = ""
        structural_res: StructuralCheckResult | None = None
        structural_signal: StructuralSignal | None = None
        semantic_res: ConformanceVerdict | None = None
        merged: ConformanceKind | None = None
        short_circuited = False

        applicability = self._applicability_verdict(tagged.rule_id, case)
        if applicability:
            return RuleDispatchResult(
                rule_id=tagged.rule_id,
                mechanism=mech,
                semantic=applicability,
                merged_verdict=ConformanceKind.UNGOVERNED,
                short_circuited=True,
            )

        if mech == EnforcementMechanism.STRUCTURAL:
            check_id = tagged.structural_check_id or ""
            fn = STRUCTURAL_CHECKS.get(check_id)
            if not fn:
                mis = f"STRUCTURAL rule {tagged.rule_id} has no check wired — silent unenforce risk"
                structural_res = StructuralCheckResult(
                    rule_id=tagged.rule_id,
                    passed=False,
                    verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
                    detail="no structural check registered",
                )
            else:
                structural_res = fn(case.get("snippet", ""), self.project_root)
                structural_res.rule_id = tagged.rule_id
            merged = structural_res.verdict if structural_res else None

        elif mech == EnforcementMechanism.SEMANTIC:
            if self.semantic_runner and allow_semantic:
                self._semantic_calls += 1
                semantic_res = self.semantic_runner(case)
            else:
                semantic_res = ConformanceVerdict(
                    verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
                    confidence_note="semantic runner not available (dry-run)",
                )
            merged = semantic_res.verdict if semantic_res else None

        elif mech == EnforcementMechanism.SEMANTIC_ASSISTED_STRUCTURAL:
            # 1) Structural pre-filter → SIGNAL (never a verdict alone)
            pf_id = tagged.prefilter_id or ""
            pf = PREFILTERS.get(pf_id)
            if not pf:
                mis = f"SAS rule {tagged.rule_id} has no prefilter wired"
                structural_signal = StructuralSignal(
                    rule_id=tagged.rule_id,
                    kind=StructuralSignalKind.ABSENT,
                    detail="no prefilter registered",
                    allow_short_circuit=False,
                )
            else:
                structural_signal = pf(case.get("snippet", ""), self.project_root)
                structural_signal.rule_id = tagged.rule_id

            # 2) Short-circuit ONLY when structurally decisive (not for Packet/LatePayload)
            if (
                structural_signal.allow_short_circuit
                and structural_signal.kind == StructuralSignalKind.CLEAR_NEGATIVE
            ):
                short_circuited = True
                merged = merge_sas_verdict(structural_signal, None, short_circuited=True)
            else:
                # 3) Engine judgment informed by signal (semantic backstop always runs)
                focused = focus_case_with_signal(case, structural_signal)
                if self.semantic_runner and allow_semantic:
                    self._semantic_calls += 1
                    semantic_res = self.semantic_runner(focused)
                else:
                    semantic_res = ConformanceVerdict(
                        verdict=ConformanceKind.INSUFFICIENT_EVIDENCE,
                        confidence_note="semantic runner not available (dry-run)",
                        grounding=f"prefilter={structural_signal.kind.value}: {structural_signal.detail}",
                    )
                # 4) Merge — engine is authoritative; signal never falsely clears
                merged = merge_sas_verdict(structural_signal, semantic_res)

        elif mech == EnforcementMechanism.AMBIGUOUS:
            mis = f"TAGGING_AMBIGUOUS: {tagged.rule_id} — {tagged.ambiguity_note}"
            if self.semantic_runner and allow_semantic:
                self._semantic_calls += 1
                semantic_res = self.semantic_runner(case)
            merged = semantic_res.verdict if semantic_res else None

        return RuleDispatchResult(
            rule_id=tagged.rule_id,
            mechanism=mech,
            structural=structural_res,
            structural_signal=structural_signal,
            semantic=semantic_res,
            merged_verdict=merged,
            short_circuited=short_circuited,
            mis_dispatch_risk=mis,
        )

    def dispatch_change(self, case: dict) -> UnifiedConformanceReport:
        calls_before = self._semantic_calls
        rule_ids = case.get("rule_ids") or []
        tagged_rules = self.rules_for_case(rule_ids)
        flags: list[str] = []
        tagging_notes: list[str] = []
        results: list[RuleDispatchResult] = []

        if not rule_ids:
            # Ungoverned scope — semantic only on question
            if self.semantic_runner:
                self._semantic_calls += 1
                cv = self.semantic_runner(case)
                results.append(
                    RuleDispatchResult(
                        rule_id="(scope)",
                        mechanism=EnforcementMechanism.SEMANTIC,
                        semantic=cv,
                    )
                )
        else:
            for tr in tagged_rules:
                if tr.mechanism == EnforcementMechanism.AMBIGUOUS:
                    tagging_notes.append(f"{tr.rule_id}: {tr.ambiguity_note}")
                rr = self.dispatch_rule(tr, case)
                if rr.mis_dispatch_risk:
                    flags.append(rr.mis_dispatch_risk)
                results.append(rr)

        structural_n = sum(
            1
            for r in results
            if (r.structural and r.mechanism == EnforcementMechanism.STRUCTURAL)
            or (r.structural_signal is not None)
        )
        overall = _merge_verdicts(results)

        return UnifiedConformanceReport(
            change_id=case.get("id", "?"),
            rule_results=results,
            overall=overall,
            structural_count=structural_n,
            semantic_llm_calls=self._semantic_calls - calls_before,
            mis_dispatch_flags=flags,
            tagging_notes=tagging_notes,
        )
