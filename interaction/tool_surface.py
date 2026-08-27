"""Tool surface — ``what_governs`` for agent decision points."""

from __future__ import annotations

from interaction.engine_adapter import EngineAdapter
from interaction.models import GovernanceVerdict

WHAT_GOVERNS_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "what_governs",
        "description": (
            "Consult the policy graph for ONE focused decision: does published policy "
            "govern this specific question? Returns a structured GOVERNANCE STATUS "
            "(GOVERNED | PARTIALLY_GOVERNED | UNGOVERNED | ABSENT) — "
            "authoritative over your recollection "
            "for this domain. Call fresh at each decision; do not reuse earlier "
            "groundings for unrelated sub-issues."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Focused natural-language question for this decision only.",
                },
                "decision_id": {
                    "type": "string",
                    "description": "Stable id for this sub-decision within the case.",
                },
            },
            "required": ["question", "decision_id"],
        },
    },
}

RESOLVE_DECISION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "resolve_decision",
        "description": (
            "Record your action for one sub-decision AFTER calling what_governs. "
            "If status is PARTIALLY_GOVERNED or UNGOVERNED you MUST NOT ACT — "
            "use ESCALATE or REFUSE per policy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "decision_id": {"type": "string"},
                "action": {"type": "string", "enum": ["ACT", "ESCALATE", "REFUSE"]},
                "resolution": {"type": "string"},
                "policies_cited": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["decision_id", "action", "resolution"],
        },
    },
}

FINISH_CASE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "finish_case",
        "description": "Call when every sub-decision has been grounded and resolved.",
        "parameters": {"type": "object", "properties": {}},
    },
}

FRAMEWORK_TOOLS = [
    WHAT_GOVERNS_TOOL_SCHEMA,
    RESOLVE_DECISION_TOOL_SCHEMA,
    FINISH_CASE_TOOL_SCHEMA,
]


class GovernanceTool:
    """Real tool surface wrapping the SST engine adapter."""

    def __init__(self, adapter: EngineAdapter):
        self._adapter = adapter

    def what_governs(self, question: str, decision_id: str = "") -> GovernanceVerdict:
        verdict = self._adapter.query(question)
        if decision_id and not verdict.question:
            verdict = verdict.model_copy(update={"question": question})
        return verdict

    def does_this_conform(self, question: str, decision_id: str = "") -> "ConformanceVerdict":
        """Structured conformance verdict (CONFORMS|VIOLATES|UNGOVERNED|INSUFFICIENT)."""
        from conformance_verdict import ConformanceVerdict

        cv = self._adapter.query_conformance(question)
        return cv

    def conformance_result_text(self, verdict: "ConformanceVerdict") -> str:
        return verdict.to_agent_block()

    def tool_result_text(self, verdict: GovernanceVerdict) -> str:
        return verdict.to_agent_block()
