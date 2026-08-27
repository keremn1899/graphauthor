"""Semantic path verification cases — real files through the callable CLI.

Handoff: design [new]/semantic-path-verification-handoff.md

Buckets:
  moat     — scope-only, honest UNGOVERNED on out-of-handbook real input (≥5)
  closure  — UNGOVERNED vs INSUFFICIENT_EVIDENCE stay distinct
  sas      — PacketImmutability / LatePayload on real files + proposed violates (≥10)
"""

from __future__ import annotations

PACKET_RULE = "PacketImmutabilityRule"
LATE_PAYLOAD_RULE = "LatePayloadRule"

# --- 1a Moat: genuine out-of-handbook predicates on real files -----------------

MOAT_CASES: list[dict] = [
    {
        "id": "SV_MOAT_PYTEST_INTEGRATION",
        "bucket": "moat",
        "scope_only": True,
        "file": "tests/test_integration.py",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must every pytest file that calls the real engine use the "
            "@pytest.mark.integration marker?"
        ),
        "framing_template": "scope_moat",
    },
    {
        "id": "SV_MOAT_CONDA_DEPS",
        "bucket": "moat",
        "scope_only": True,
        "file": "environment.yml",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must this project pin langgraph to an exact minor version in environment.yml?"
        ),
        "framing_template": "scope_moat",
    },
    {
        "id": "SV_MOAT_BENCHMARK_CASES",
        "bucket": "moat",
        "scope_only": True,
        "file": "benchmark_v4.py",
        "lines": "34-41",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must benchmark_v4 use exactly these seed queries and no others?"
        ),
        "framing_template": "scope_moat",
    },
    {
        "id": "SV_MOAT_VIZ_PYVIS",
        "bucket": "moat",
        "scope_only": True,
        "file": "tools/viz_sst.py",
        "lines": "1-30",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must graph visualization HTML exports use pyvis specifically "
            "(not d3, cytoscape, or another library)?"
        ),
        "framing_template": "scope_moat",
    },
    {
        "id": "SV_MOAT_CRON_SCHEDULE",
        "bucket": "moat",
        "scope_only": True,
        "file": "scripts/cron_metaqa_smoke.sh",
        "lines": "1-22",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must MetaQA cron smoke tests run at 06:00 UTC daily?"
        ),
        "framing_template": "scope_moat",
    },
    {
        "id": "SV_MOAT_OPENROUTER_MODEL",
        "bucket": "moat",
        "scope_only": True,
        "file": "planner.py",
        "lines": "1-40",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must the Planner tier use google/gemini-3.1-flash-lite-preview specifically "
            "as its OpenRouter model?"
        ),
        "framing_template": "scope_moat",
    },
]

# --- 1b Closure: UNGOVERNED ≠ INSUFFICIENT on unframed input -----------------

CLOSURE_CASES: list[dict] = [
    {
        "id": "SV_CLOSURE_UNGOVERNED_README",
        "bucket": "closure",
        "scope_only": True,
        "file": "README.md",
        "lines": "1-25",
        "founder_expected": "UNGOVERNED",
        "scope_question": (
            "must the repository README open with a one-paragraph product pitch "
            "before any installation instructions?"
        ),
        "framing_template": "scope_moat",
        "closure_axis": "ungoverned",
    },
    {
        "id": "SV_CLOSURE_INSUFFICIENT_EMPTY",
        "bucket": "closure",
        "scope_only": True,
        "snippet": "# (no code change shown — empty context)\n",
        "founder_expected": "INSUFFICIENT_EVIDENCE",
        "insufficient_question": (
            "can you determine whether an unspecified proposed code change "
            "conforms to or violates any architecture handbook rule? "
            "(No change, file path, or diff is shown — only this empty placeholder.)"
        ),
        "framing_template": "insufficient",
        "closure_axis": "insufficient",
    },
    {
        "id": "SV_CLOSURE_INSUFFICIENT_NO_PROPOSAL",
        "bucket": "closure",
        "scope_only": True,
        "file": "main.py",
        "lines": "1-15",
        "founder_expected": "INSUFFICIENT_EVIDENCE",
        "insufficient_question": (
            "can you determine whether a proposed battalion_synthesize mutation "
            "that appends to evidence_packet.node_records would conform or violate "
            "handbook policy? (No proposed mutation is included — only unrelated "
            "imports from main.py are shown.)"
        ),
        "framing_template": "insufficient",
        "closure_axis": "insufficient",
    },
]

# --- 1c SAS / semantic correctness on real files (two-sided) -------------------

SAS_CASES: list[dict] = [
    # CONFORMS — real file slices
    {
        "id": "SV_PKT_REAL_BACKEND_APPEND",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "file": "backend_tools.py",
        "lines": "656-726",
        "founder_expected": "CONFORMS",
        "existing_question": (
            "does append_to_evidence_packet conform to PacketImmutabilityRule as an "
            "authorized append-only EvidencePacket extension callable from "
            "backend_execute / backend_execute_recovery?"
        ),
        "module_hint": "backend_tools.py",
        "ruling_allow_signals": [r"may append", r"permitted", r"append-only", r"authorized"],
        "ruling_deny_signals": [r"must not mutate", r"forbidden"],
    },
    {
        "id": "SV_PKT_REAL_BATTALION_READ",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "file": "battalion.py",
        "lines": "350-380",
        "founder_expected": "CONFORMS",
        "existing_question": (
            "does this battalion_synthesize entry conform to PacketImmutabilityRule "
            "when it reads the evidence_packet without mutating node_records?"
        ),
        "module_hint": "battalion.py",
        "ruling_allow_signals": [r"may read", r"permitted", r"conform", r"read only"],
        "ruling_deny_signals": [r"must not mutate", r"append", r"violat"],
    },
    {
        "id": "SV_LATE_REAL_BATTALION_PAGE",
        "bucket": "sas",
        "rule": LATE_PAYLOAD_RULE,
        "file": "battalion.py",
        "lines": "530-610",
        "founder_expected": "CONFORMS",
        "existing_question": (
            "does battalion_synthesize paging text_content from EvidencePacket "
            "node_records in this trail-building section conform to LatePayloadRule "
            "(Battalion is the authorized full-payload tier)?"
        ),
        "module_hint": "battalion.py",
        "ruling_allow_signals": [r"may page", r"permitted", r"authorized", r"conform", r"battalion"],
        "ruling_deny_signals": [r"must not page", r"forbidden for battalion"],
    },
    {
        "id": "SV_PKT_REAL_CONTRACT_CLEAN",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "file": "contract.py",
        "lines": "1-50",
        "founder_expected": "CONFORMS",
        "existing_question": (
            "does contract.py conform to PacketImmutabilityRule — it does not touch "
            "EvidencePacket at all?"
        ),
        "module_hint": "contract.py",
        "ruling_allow_signals": [r"conform", r"does not", r"no mutation", r"permitted"],
        "ruling_deny_signals": [r"violat", r"mutat"],
    },
    {
        "id": "SV_LATE_REAL_PLANNER_NO_PAYLOAD",
        "bucket": "sas",
        "rule": LATE_PAYLOAD_RULE,
        "file": "planner.py",
        "lines": "1-80",
        "founder_expected": "CONFORMS",
        "existing_question": (
            "does this planner.py section conform to LatePayloadRule — Planner works "
            "on anchors/compass without paging full text_content from EvidencePacket?"
        ),
        "module_hint": "planner.py",
        "ruling_allow_signals": [r"conform", r"does not page", r"anchors only", r"permitted"],
        "ruling_deny_signals": [r"text_content", r"violat", r"must not page"],
    },
    # VIOLATES — proposed changes to real modules
    {
        "id": "SV_PKT_VIOLATE_BATTALION_APPEND",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "snippet": '''\
# Proposed change to battalion.py battalion_synthesize:
packet = state.get("evidence_packet") or {}
packet.setdefault("node_records", []).append({
    "id": "synth_invented",
    "label": "InventedNode",
    "text_content": "Battalion invented this record.",
})
return {"final_answer": answer, "evidence_packet": packet}
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may battalion_synthesize append a new node_records entry directly "
            "to the EvidencePacket as shown?"
        ),
        "module_hint": "battalion.py",
        "ruling_deny_signals": [r"must not", r"may not", r"not permitted", r"violat", r"forbidden"],
        "ruling_allow_signals": [r"may append", r"permitted"],
    },
    {
        "id": "SV_PKT_VIOLATE_BATTALION_REASSIGN",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "snippet": '''\
# Proposed change to battalion.py — list concat reassignment (no .append token):
packet = state.get("evidence_packet") or {}
nodes = list(packet.get("node_records") or [])
nodes = nodes + [{"id": "invented", "label": "X", "text_content": "y"}]
return {"final_answer": answer, "evidence_packet": {**packet, "node_records": nodes}}
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may battalion_synthesize replace EvidencePacket.node_records with a new "
            "list that includes an invented node via list concat (no .append call)?"
        ),
        "module_hint": "battalion.py",
        "ruling_deny_signals": [r"must not", r"may not", r"not permitted", r"violat", r"immutable"],
        "ruling_allow_signals": [r"may append", r"permitted"],
    },
    {
        "id": "SV_LATE_VIOLATE_SQUAD_PAGE",
        "bucket": "sas",
        "rule": LATE_PAYLOAD_RULE,
        "snippet": '''\
# Proposed change to squad.py squad_dispatch:
def squad_agent(cluster, packet):
    bodies = []
    for rec in packet.get("node_records") or []:
        bodies.append(rec.get("text_content") or "")
    prompt = "Reason over full bodies:\\n" + "\\n".join(bodies)
    return call_fast_llm(prompt)
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may squad_dispatch page full text_content for all EvidencePacket nodes "
            "into the Squad prompt as shown?"
        ),
        "module_hint": "squad.py",
        "ruling_deny_signals": [r"must not", r"may not", r"not permitted", r"violat", r"battalion"],
        "ruling_allow_signals": [r"may page", r"permitted"],
    },
    {
        "id": "SV_LATE_VIOLATE_COMPANY_INDIRECT",
        "bucket": "sas",
        "rule": LATE_PAYLOAD_RULE,
        "snippet": '''\
# Proposed change to company.py company_llm — indirect text_content key:
FULL_BODY_KEY = "text" + "_content"
def company_llm(state):
    packet = state.get("evidence_packet") or {}
    bodies = [rec.get(FULL_BODY_KEY) or "" for rec in packet.get("node_records") or []]
    return interpret(bodies)
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may company_llm page full concept-node markdown bodies via an indirection "
            "key that resolves to text_content for interpretive reasoning?"
        ),
        "module_hint": "company.py",
        "ruling_deny_signals": [r"must not", r"may not", r"violat", r"battalion", r"late"],
        "ruling_allow_signals": [r"may page", r"permitted"],
    },
    {
        "id": "SV_PKT_VIOLATE_BACKEND_UNAUTHORIZED",
        "bucket": "sas",
        "rule": PACKET_RULE,
        "snippet": '''\
# Proposed change to planner.py (unauthorized tier mutating packet):
def planner_confirm(state):
    packet = state.get("evidence_packet") or {}
    packet["node_records"] = packet.get("node_records", []) + [{"id": "planner_add"}]
    return {**state, "evidence_packet": packet}
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may planner_confirm mutate evidence_packet.node_records in place as shown?"
        ),
        "module_hint": "planner.py",
        "ruling_deny_signals": [r"must not", r"may not", r"violat", r"forbidden", r"planner"],
        "ruling_allow_signals": [r"may mutate", r"permitted"],
    },
    {
        "id": "SV_LATE_VIOLATE_PLANNER_LITERAL",
        "bucket": "sas",
        "rule": LATE_PAYLOAD_RULE,
        "snippet": '''\
# Proposed change to planner.py planner_initial:
def planner_initial(state):
    packet = state.get("evidence_packet") or {}
    for rec in packet.get("node_records") or []:
        _ = rec.get("text_content")  # early full-body read
    return state
''',
        "founder_expected": "VIOLATES",
        "proposed_question": (
            "may planner_initial read full text_content from EvidencePacket node_records "
            "during planning as shown?"
        ),
        "module_hint": "planner.py",
        "ruling_deny_signals": [r"must not", r"may not", r"violat", r"early", r"battalion"],
        "ruling_allow_signals": [r"may read", r"permitted"],
    },
]

ALL_CASES = MOAT_CASES + CLOSURE_CASES + SAS_CASES

SMOKE_IDS = (
    "SV_MOAT_PYTEST_INTEGRATION",
    "SV_CLOSURE_INSUFFICIENT_EMPTY",
    "SV_PKT_REAL_BACKEND_APPEND",
    "SV_PKT_VIOLATE_BATTALION_APPEND",
)
