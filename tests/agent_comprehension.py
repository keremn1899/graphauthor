"""Harness: put a real model in front of the real MCP surface and see what it does.

Every other test here asks whether the surface *behaves* correctly. This asks
whether it can be *understood* — because agents are the primary users, and a
tool schema that is accurate but unreadable fails exactly as hard as a wrong
one. Nothing verified that until now.

What it does NOT do: check prose. Each case asserts on the tool the model
chose and the arguments it built, because those are the only things that
change what happens to the graph.

Fully offline-safe: `run_case` takes any `chat` callable, so the cases can be
driven by a stub in unit tests and by OpenRouter in integration tests.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

#: Real MCP clients use structured tool calls; this harness has only a prose
#: channel, so the format has to be as easy as possible to emit correctly. An
#: earlier version asked for a third top-level `why` field and models kept
#: closing the root object early, stranding `target_gap_id` after a stray brace
#: — a correct decision scored as a wrong one because of JSON shape. Two keys,
#: flat, nothing optional.
SYSTEM = (
    "You are an autonomous coding agent with access to a governance graph "
    "through the tools below. Before acting on anything that might be "
    "governed, you consult the graph.\n\n"
    "Reply with ONE JSON object and nothing else. Exactly two keys:\n"
    '{\"tool\": \"<tool name, or \\\"none\\\">\", \"arguments\": {…}}\n'
    "Put every argument inside `arguments`. Do not add any other top-level key."
)


@dataclass
class Case:
    """One decision an agent has to get right."""

    name: str
    #: What the agent has been asked to do, plus whatever the surface told it.
    prompt: str
    #: Tool the agent must choose. `None` means "any of `allowed`".
    expect_tool: str | None = None
    allowed: tuple[str, ...] = ()
    #: Arguments that must be present and non-empty.
    require_args: tuple[str, ...] = ()
    #: `(argument, substring)` pairs the argument must contain, lowercased.
    require_arg_contains: tuple[tuple[str, str], ...] = ()
    #: `(argument, substring)` pairs the argument must NOT contain. Lets a case
    #: forbid a specific *move* rather than a whole verb — re-issuing the same
    #: failed query is wrong, while rephrasing to find the right identifier is
    #: legitimate recovery, and both use the same tool.
    forbid_arg_contains: tuple[tuple[str, str], ...] = ()
    #: Tools that would be actively wrong here.
    forbid_tools: tuple[str, ...] = ()
    #: What this case is really testing, for the failure message.
    rationale: str = ""


@dataclass
class Result:
    case: Case
    tool: str
    arguments: dict[str, Any]
    why: str
    raw: str
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def tool_catalogue(only: tuple[str, ...] | None = None) -> str:
    """The real tool schemas — the same text a live agent would receive.

    `only` restricts the listing. A harness must advertise exactly what it can
    dispatch: the multi-turn runner served a subset while showing the whole
    catalogue, and the agent duly called a listed verb, got "unknown tool", and
    looped re-orienting. Showing an agent a tool you will refuse is a harness
    defect that reads as an agent defect.
    """
    from mcp_server.stdio import TOOLS

    lines = []
    for tool in TOOLS:
        if only is not None and tool.name not in only:
            continue
        props = (tool.inputSchema or {}).get("properties", {})
        required = (tool.inputSchema or {}).get("required", [])
        rendered = []
        for name, spec in props.items():
            suffix = "*" if name in required else ""
            enum = spec.get("enum") or []
            if enum:
                suffix += "[" + "|".join(map(str, enum)) + "]"
            rendered.append(name + suffix)
        args = ", ".join(rendered) or "(no arguments)"
        lines.append(f"- {tool.name}({args})\n    {' '.join(str(tool.description).split())}")
    return "\n".join(lines)


class TruncatedReply(ValueError):
    """The model was cut off mid-JSON. Not a decision — a budget problem.

    This masqueraded as "chose nothing" until it was traced: a correct
    `propose` with a full encoding ran past `max_tokens` and arrived as
    unparseable text, so a passing case read as a hard failure. Any harness
    that silently turns its own truncation into a model error will lie about
    the model.
    """


def _extract_json(text: str) -> dict[str, Any]:
    """Models fence their JSON, prepend prose, or both. Be forgiving here —
    output format is not what is under test."""
    body = text.strip()
    if "```" in body:
        chunk = body.split("```")[1]
        body = chunk[4:] if chunk.lower().startswith("json") else chunk
    start = body.find("{")
    if start == -1:
        return {}

    # `raw_decode` takes the FIRST complete object and ignores whatever trails
    # it. Models sometimes close the root early and append a stray `, "why": …`,
    # which `json.loads` rejects wholesale as "Extra data" — scoring a correct
    # tool choice as "chose nothing". Output format is explicitly not what is
    # under test, so a formatting quirk must not read as a decision.
    try:
        parsed, _end = json.JSONDecoder().raw_decode(body[start:])
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        pass

    # Nothing parseable from the first brace. If the reply never closed it, the
    # model was cut off — a budget problem, not a decision.
    if body.rfind("}") == -1:
        raise TruncatedReply("reply opened a JSON object and never closed it")
    return {}


def run_case(case: Case, chat: Callable[[str, str], str]) -> Result:
    raw = chat(SYSTEM + "\nTOOLS\n" + tool_catalogue(), case.prompt)
    try:
        parsed = _extract_json(raw)
    except TruncatedReply as exc:
        return Result(case=case, tool="", arguments={}, why="", raw=raw,
                      failures=[f"harness: {exc} — raise max_tokens; this is "
                                f"not a model decision"])
    tool = str(parsed.get("tool") or "").strip()
    arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
    result = Result(case=case, tool=tool, arguments=arguments,
                    why=str(parsed.get("why") or ""), raw=raw)

    if not parsed:
        result.failures.append(f"no JSON in reply: {raw[:160]!r}")
        return result

    if case.expect_tool and tool != case.expect_tool:
        result.failures.append(f"chose {tool!r}, expected {case.expect_tool!r}")
    if case.allowed and tool not in case.allowed:
        result.failures.append(f"chose {tool!r}, expected one of {case.allowed}")
    if tool in case.forbid_tools:
        result.failures.append(f"chose {tool!r}, which is wrong here")
    for key in case.require_args:
        if not str(arguments.get(key) or "").strip():
            result.failures.append(f"missing argument {key!r}")
    for key, needle in case.require_arg_contains:
        if needle.lower() not in json.dumps(arguments.get(key, "")).lower():
            result.failures.append(f"argument {key!r} does not mention {needle!r}")
    for key, needle in case.forbid_arg_contains:
        if needle.lower() in json.dumps(arguments.get(key, "")).lower():
            result.failures.append(f"argument {key!r} repeats {needle!r}")
    return result


def openrouter_chat(model: str | None = None,
                    temperature: float = 0.0) -> Callable[[str, str], str]:
    """A chat callable backed by OpenRouter. Requires OPENROUTER_API_KEY."""
    from langchain_openai import ChatOpenAI

    from model_roles import planner_model

    client = ChatOpenAI(
        model=model or planner_model(),
        temperature=temperature,
        # A correct `propose` carries a full encoding and ran past 1200,
        # arriving truncated and scoring as a hard failure. Budget for the
        # longest legitimate answer, not the typical one.
        max_tokens=4000,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
    )

    def chat(system: str, user: str) -> str:
        reply = client.invoke([("system", system), ("user", user)])
        return str(getattr(reply, "content", reply))

    return chat


#: Runs per case, and how many must pass. A single run cannot gate anything
#: here: across repeated full runs the same suite failed three DIFFERENT cases
#: each time, because several sit at the edge of the model's reliability rather
#: than clearly inside or outside it. Tuning descriptions against a one-shot
#: signal just moves which case fails — that was measured, repeatedly, before
#: this was added.
#:
#: Majority-of-three converts a noisy observation into a stable one, and makes
#: the failure message honest: "2 of 3 runs chose the wrong verb" is a claim
#: about the surface; "it failed" was a claim about one sample.
REPEATS = 3


def majority(repeats: int) -> int:
    """More than half — derived, never fixed.

    A quorum pinned at 2 made `repeats=1` unsatisfiable, and the "report the
    first failure" path then raised StopIteration because there was no failure
    to report. The model-tier script hit it immediately and every case came back
    FAIL, which looked like four models failing the whole surface.
    """
    return repeats // 2 + 1


def run_case_repeated(case: Case, chat: Callable[[str, str], str],
                      repeats: int = REPEATS,
                      quorum: int | None = None) -> Result:
    """Run a case several times; report the majority outcome."""
    quorum = majority(repeats) if quorum is None else quorum
    results = [run_case(case, chat) for _ in range(repeats)]
    passed = [r for r in results if r.passed]
    if len(passed) >= quorum:
        return passed[-1]

    # A caller may demand a quorum higher than the number of runs; report the
    # last result rather than raising when nothing failed.
    worst = next((r for r in results if not r.passed), results[-1])
    tally: dict[str, int] = {}
    for r in results:
        tally[r.tool or "none"] = tally.get(r.tool or "none", 0) + 1
    worst.failures = list(worst.failures) + [
        f"{len(results) - len(passed)} of {len(results)} runs failed; "
        f"tools chosen: {tally}"
    ]
    return worst
