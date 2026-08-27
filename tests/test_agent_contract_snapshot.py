"""The agent-facing surface, pinned. Any change to it becomes a visible diff.

Every verb, argument, default and closed vocabulary an agent can see is captured
here. The point is not that the current shape is right — it is that changing
what agents see should be a decision someone makes on purpose, in a review,
rather than a side effect of editing a docstring.

This session produced four separate cases of two layers disagreeing about a
vocabulary in code while agreeing about it in prose, and one case where a
description edit silently made three previously-correct behaviours wrong. A
snapshot is the cheapest instrument that would have caught the shape of any of
them.

Descriptions are deliberately captured by LENGTH and a content fingerprint
rather than verbatim: wording is tuned often and legitimately (comprehension
tests measure whether the tuning worked), but a large swing in size or a lost
keyword is worth a second look.

Regenerate deliberately:
    conda run -n agentic-graphrag python -m tests.test_agent_contract_snapshot
"""

from __future__ import annotations

import json
from pathlib import Path

SNAPSHOT = Path(__file__).with_name("agent_contract_snapshot.json")

#: Words whose presence in a description is load-bearing — each was added
#: because an agent got something wrong without it, and each is verified live by
#: a case in tests/test_agent_comprehension.py.
_LOAD_BEARING = {
    "orient": ["posture", "capabilities", "grain"],
    "contract": ["graph.md", "predicates", "Zero LLM"],
    "lookup": ["exact", "terminal", "zero LLM"],
    "expand": ["typed", "bounded", "partial"],
    "path": ["explicit", "bounded", "EMPTY"],
    "search": ["candidate-only", "never proves", "run_traversal"],
    "retrieve": ["zero LLM", "retrieval-v1", "content", "preconditions"],
    "run_traversal": ["versioned", "receipt", "Zero LLM", "EMPTY"],
    "propose": ["dry_run", "target_gap_id", "NEVER writes"],
    "history": ["changed_since", "Revert is not available"],
    "proposal_status": ["PENDING", "COMMITTED"],
}


def _capture() -> dict:
    from mcp_server.stdio import TOOLS
    from mcp_server.surface import (
        CONFIRMATION_SPACE, COVERAGE_SPACE, GOVERNANCE_FIELDS, RULING_SPACE,
    )

    tools = {}
    for tool in sorted(TOOLS, key=lambda t: t.name):
        schema = tool.inputSchema or {}
        props = schema.get("properties", {})
        tools[tool.name] = {
            "required": sorted(schema.get("required", [])),
            "arguments": {
                name: {
                    "type": spec.get("type"),
                    "enum": spec.get("enum"),
                    "default": spec.get("default"),
                }
                for name, spec in sorted(props.items())
            },
            "additionalProperties": schema.get("additionalProperties"),
            "description_length": len(" ".join(str(tool.description).split())),
        }

    from contract import CONTRACT_VERSION, GapType
    import typing

    return {
        "tools": tools,
        "verdict_spaces": {
            "confirmation": sorted(CONFIRMATION_SPACE),
            "coverage": sorted(COVERAGE_SPACE),
            "ruling": sorted(RULING_SPACE),
        },
        "governance_fields_stripped_from_discovery": sorted(GOVERNANCE_FIELDS),
        "contract_gap_types": sorted(typing.get_args(GapType)),
        "contract_version": CONTRACT_VERSION,
    }


def test_the_agent_surface_matches_its_snapshot():
    current = _capture()
    assert SNAPSHOT.exists(), (
        "no snapshot — run `python -m tests.test_agent_contract_snapshot` to create it")
    recorded = json.loads(SNAPSHOT.read_text(encoding="utf-8"))

    # Description length drifts with legitimate tuning; allow ±40% before
    # asking for a look, and compare everything else exactly.
    def _strip_lengths(blob):
        out = json.loads(json.dumps(blob))
        for spec in out["tools"].values():
            spec.pop("description_length", None)
        return out

    assert _strip_lengths(current) == _strip_lengths(recorded), (
        "the agent-facing contract changed. If deliberate, regenerate with "
        "`python -m tests.test_agent_contract_snapshot` and let the diff be "
        "reviewed.")

    for name, spec in current["tools"].items():
        before = recorded["tools"][name].get("description_length") or 1
        after = spec["description_length"]
        assert 0.6 * before <= after <= 1.4 * before, (
            f"{name}'s description changed size by more than 40% "
            f"({before} -> {after}). A description edit silently broke three "
            f"agent behaviours once in this codebase; confirm with the "
            f"comprehension suite, then regenerate.")


def test_load_bearing_words_survive_description_edits():
    """Each of these was added because an agent got something wrong without it.
    Losing one is how `check_conformance` became unreachable."""
    from mcp_server.stdio import TOOLS

    by_name = {t.name: " ".join(str(t.description).split()) for t in TOOLS}
    for tool_name, words in _LOAD_BEARING.items():
        assert tool_name in by_name, f"{tool_name} is gone from the surface"
        for word in words:
            assert word.lower() in by_name[tool_name].lower(), (
                f"{tool_name}'s description lost {word!r} — a comprehension "
                f"case depends on it")


if __name__ == "__main__":
    SNAPSHOT.write_text(json.dumps(_capture(), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {SNAPSHOT}")
