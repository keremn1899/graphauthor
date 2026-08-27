"""Let an agent actually run: model chooses, the real Surface answers, repeat.

Every comprehension case so far is single-shot with the tool result pasted into
the prompt by hand. That measures whether one decision is legible; it cannot see
anything that only exists across turns — looping, re-asking a refused question,
skipping a prerequisite, never stopping, or sending arguments the surface
rejects and not recovering.

The dispatcher is a **real `Surface`**, not a stub. That is affordable because
the authoring loop is almost entirely zero-LLM on the engine side — `orient`,
`coverage`, `propose`, `proposal_status` and `escalate` cost nothing but a
database read — so only the model's own turns spend tokens. Scenarios are chosen
to stay on that path. `discover` / `what_governs` / `check_conformance` run the
full pipeline and are deliberately not exercised here; single-shot cases already
cover their selection, and putting them in a loop would buy little for a lot.

What this catches that single-shot cannot: a trajectory. The assertions are
about the *shape* of what happened — which verbs, in what order, whether it
terminated, whether it repeated itself — not about any one reply.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from tests.agent_comprehension import _extract_json, tool_catalogue

SYSTEM = (
    "You are an autonomous coding agent working against a governance graph. "
    "You will be called repeatedly. Each turn, choose ONE tool call; you will "
    "be shown its real result and asked again.\n\n"
    "Reply with ONE JSON object and nothing else. Exactly two keys:\n"
    '{"tool": "<tool name, or \\"none\\" when the task is done or you must '
    'stop>", "arguments": {…}}\n'
    "Put every argument inside `arguments`. Stop as soon as the task is "
    "complete or you are blocked — do not keep calling tools."
)

#: Exactly what `_dispatch` serves. The catalogue shown to the agent is
#: filtered to this, because advertising a verb the harness will refuse
#: produces a loop that looks like an agent failure and is not one.
#:
#: `discover` / `what_governs` / `check_conformance` are absent on purpose:
#: each runs the full pipeline, and single-shot cases already cover how they
#: are selected. What is under test here is sequencing, not retrieval.
DISPATCHED = ("orient", "coverage", "propose", "proposal_status", "escalate",
              "history")

#: Turn ceiling. Reaching it is itself a finding: an agent that has not stopped
#: by here is looping, and a loop against a governance surface is worse than a
#: refusal because it looks like progress.
MAX_TURNS = 6

#: How much of a tool result the agent sees. Real payloads carry full node
#: bodies; a transcript of those would exhaust the context before the loop
#: finishes and would test summarisation rather than sequencing.
RESULT_BUDGET = 700


@dataclass
class Turn:
    tool: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    error: str = ""


@dataclass
class Trajectory:
    turns: list[Turn] = field(default_factory=list)
    stopped: bool = False
    raw_replies: list[str] = field(default_factory=list)

    @property
    def verbs(self) -> list[str]:
        return [t.tool for t in self.turns]

    def first_index(self, verb: str) -> int:
        return self.verbs.index(verb) if verb in self.verbs else -1

    @property
    def repeated_calls(self) -> list[str]:
        """Identical (verb, arguments) issued more than once.

        Re-asking a question you already have the answer to is the cheapest
        loop to fall into and the hardest to see from one turn.
        """
        seen: dict[str, int] = {}
        for t in self.turns:
            key = f"{t.tool}({json.dumps(t.arguments, sort_keys=True)})"
            seen[key] = seen.get(key, 0) + 1
        return sorted(k for k, n in seen.items() if n > 1)


def _dispatch(surface, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call the real surface. Unknown verbs and bad arguments come back as
    errors the agent can read, exactly as a real client would see them."""
    args = dict(args or {})
    try:
        if tool == "orient":
            return surface.orient()
        if tool == "coverage":
            return surface.coverage(
                include_violations=bool(args.get("include_violations", False)))
        if tool == "propose":
            return surface.propose(
                encoding=args.get("encoding") or {},
                provenance=args.get("provenance"),
                target_gap_id=args.get("target_gap_id", ""),
                claim_level=args.get("claim_level", "L0"),
                dry_run=bool(args.get("dry_run", False)),
            )
        if tool == "proposal_status":
            return surface.proposal_status(args.get("proposal_id", ""))
        if tool == "escalate":
            return surface.escalate(**args)
        if tool == "history":
            return surface.history_action(args)
        return {"error": f"unknown or unavailable tool: {tool!r}"}
    except TypeError as exc:
        # A real client surfaces argument errors; the agent should adapt.
        return {"error": f"invalid arguments for {tool}: {exc}"}


def _summarise(result: dict[str, Any]) -> str:
    text = json.dumps(result, default=str)
    if len(text) <= RESULT_BUDGET:
        return text
    return text[:RESULT_BUDGET] + f"… [{len(text) - RESULT_BUDGET} chars omitted]"


def run_session(surface, task: str, chat: Callable[[str, str], str],
                max_turns: int = MAX_TURNS) -> Trajectory:
    """Drive the agent until it stops or runs out of turns."""
    traj = Trajectory()
    transcript: list[str] = []

    for _ in range(max_turns):
        user = (
            f"TASK\n{task}\n\n"
            + ("TRANSCRIPT SO FAR\n" + "\n".join(transcript) + "\n\n"
               if transcript else "")
            + "Choose your next tool call."
        )
        raw = chat(SYSTEM + "\nTOOLS\n" + tool_catalogue(only=DISPATCHED), user)
        traj.raw_replies.append(raw)

        try:
            parsed = _extract_json(raw)
        except Exception:
            parsed = {}
        tool = str(parsed.get("tool") or "").strip()
        args = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}

        if not tool or tool == "none":
            traj.stopped = True
            break

        result = _dispatch(surface, tool, args)
        traj.turns.append(Turn(tool=tool, arguments=args, result=result,
                               error=str(result.get("error") or "")))
        transcript.append(f"CALLED {tool}({json.dumps(args, default=str)[:300]})"
                          f"\nRESULT {_summarise(result)}")

    return traj
