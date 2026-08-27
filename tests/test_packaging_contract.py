"""What `pip install` is allowed to drag in, and what it must pin.

The MCP server's job is to open a graph and answer typed questions about it.
Every dependency beyond that is weight an integrator pays to run a read-only
tool — and it stops being merely weight the moment a host agent owns the
reasoning, because then this package *is* the product and its install size is
the first thing anyone experiences.

Measured, not asserted from taste: `[mcp]` installs 35 packages / 83 MB and
serves all 11 tools over stdio against a real 500-node graph; `[all]` installs
89 / 245 MB. The base list drifting back is a silent 3x regression that no
other test would notice, because everything still works — on the machine that
already had them.

Two things are pinned here.

**The base list stays small.** Named exactly, so adding one is a deliberate
edit to this file rather than a line in `pyproject.toml` nobody reviews.

**`mcp` stays below 2.0.** Not caution: mcp 2.0.0 removed `Server.list_tools`,
and the stdio server raises AttributeError during startup, before serving a
single request. `mcp>=1.0` resolved to 2.0.0 on a fresh install, so the
published package would have handed every new user a server that dies
immediately and says nothing useful about why.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"

#: Everything the read path needs, and nothing else. `requests` is here because
#: `engine.py` imports it at module scope; it used to arrive only as a
#: transitive of langchain-openai, so the base install depended on an extra it
#: never named.
ALLOWED_BASE = {
    "real_ladybug",
    "pydantic",
    "requests",
    "python-dotenv",
    "httpx",
    # graph.md is the user-owned semantic contract read by the base MCP server.
    "pyyaml",
}

#: Must never be base. Each is genuinely needed by something, and that
#: something is never "read a graph".
HEAVY = {
    "beautifulsoup4": "the optional workbook HTML parser",
}


def _name(requirement: str) -> str:
    """`pydantic>=2.0` -> `pydantic`. Extras and markers are not used here."""
    return re.split(r"[<>=!\[;\s]", requirement.strip(), maxsplit=1)[0].lower()


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_base_install_carries_only_what_reading_a_graph_needs():
    base = {_name(d) for d in _pyproject()["project"]["dependencies"]}
    extra = base - {n.lower() for n in ALLOWED_BASE}
    assert not extra, (
        f"new base dependencies {sorted(extra)} — a graph-reading MCP server "
        f"installs these for every user. Put it in an extra, or add it to "
        f"ALLOWED_BASE here with the reason."
    )


def test_no_heavy_dependency_is_a_base_dependency():
    base = {_name(d) for d in _pyproject()["project"]["dependencies"]}
    offenders = sorted(base & set(HEAVY))
    assert not offenders, (
        "these are base dependencies again: "
        + ", ".join(f"{n} (needed by {HEAVY[n]})" for n in offenders)
    )


def test_every_heavy_dependency_is_reachable_through_some_extra():
    """Small and unusable is not the goal.

    The split is only honest if everything that was dropped is still
    installable by name — otherwise this test would pass by deleting features.
    """
    extras = _pyproject()["project"]["optional-dependencies"]
    offered = {_name(d) for group in extras.values() for d in group}
    missing = sorted(set(HEAVY) - offered)
    assert not missing, f"dropped from base and offered nowhere: {missing}"


def test_the_all_extra_really_is_all():
    """`[all]` is what the old base install was, so nobody is worse off."""
    extras = _pyproject()["project"]["optional-dependencies"]
    all_names = {_name(d) for d in extras["all"]}
    missing = sorted(set(HEAVY) - all_names)
    assert not missing, f"[all] does not include {missing}"


def test_mcp_is_pinned_below_the_release_that_breaks_the_server():
    """mcp 2.0.0 removed `Server.list_tools`; the stdio server cannot start."""
    extras = _pyproject()["project"]["optional-dependencies"]
    groups = {k: v for k, v in extras.items() if any(_name(d) == "mcp" for d in v)}
    assert groups, "no extra offers mcp any more"
    for group, reqs in groups.items():
        spec = next(d for d in reqs if _name(d) == "mcp")
        assert "<2" in spec.replace(" ", ""), (
            f"extra [{group}] declares {spec!r}: a fresh install resolves to "
            f"mcp 2.0.0, whose Server has no list_tools, and the server raises "
            f"AttributeError before answering anything"
        )

    req = REQUIREMENTS.read_text(encoding="utf-8")
    line = next(l for l in req.splitlines() if _name(l) == "mcp")
    assert "<2" in line.replace(" ", ""), (
        f"requirements.txt declares {line!r} — the dev environment would drift "
        f"onto the broken major while the package pins away from it"
    )


def test_requirements_declares_what_engine_imports_at_module_scope():
    """`requests` is imported by `engine.py` before anything can guard it.

    It was absent from both dependency lists and arrived only because
    langchain-openai depended on it. Removing langchain from the base install
    is exactly the change that would have exposed that.
    """
    req = {_name(l) for l in REQUIREMENTS.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")}
    assert "requests" in req, "requirements.txt no longer declares requests"

    source = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert re.search(r"^import requests", source, re.M), (
        "engine.py no longer imports requests at module scope — if that import "
        "became lazy or went away, drop it from the base dependencies too "
        "rather than leaving this test defending a requirement nobody has"
    )
