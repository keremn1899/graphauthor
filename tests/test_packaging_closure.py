"""Every root module reachable from shipped code must itself ship.

`check_conformance` and `discover` faulted with `No module named
'judgment_view'` on the first graph-arm run driven from a project directory.
The module exists at the repo root and is imported by `company.py` and
`pipeline_b.py`, both of which are listed in `py-modules` — but it is not, so an
installed server importing them from anywhere except the repo root breaks.

That is a product bug, not a test-harness one: the MCP server runs with the
user's workspace as its cwd, which is never this repo.

A first pass at this audit checked only what the *packages* import directly and
reported the wrong module, because the real path is
`mcp_server` → `company` → `judgment_view`. Transitive closure is the check.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _listed_modules() -> set[str]:
    text = (ROOT / "pyproject.toml").read_text()
    block = text.split("py-modules = [", 1)[1].split("]", 1)[0]
    return set(re.findall(r'"([^"]+)"', block))


def _found_packages() -> list[str]:
    text = (ROOT / "pyproject.toml").read_text()
    section = text.split("[tool.setuptools.packages.find]", 1)[1].split("exclude", 1)[0]
    return [name.rstrip("*") for name in re.findall(r'"([^"]+)"', section)]


def _root_imports(path: Path, root_modules: set[str]) -> set[str]:
    text = path.read_text(errors="replace")
    found = re.findall(r"^\s*(?:from|import)\s+([a-z_][a-z0-9_]*)", text, re.M)
    return {name for name in found if name in root_modules}


def test_every_reachable_root_module_is_packaged():
    listed = _listed_modules()
    root_modules = {p.stem for p in ROOT.glob("*.py")}

    frontier = [f for pkg in _found_packages()
                if (ROOT / pkg).is_dir()
                for f in (ROOT / pkg).rglob("*.py")]
    frontier += [ROOT / f"{m}.py" for m in listed if (ROOT / f"{m}.py").exists()]

    seen: set[Path] = set()
    missing: set[str] = set()
    while frontier:
        current = frontier.pop()
        if current in seen or not current.exists():
            continue
        seen.add(current)
        for module in _root_imports(current, root_modules):
            if module not in listed:
                missing.add(module)
            nxt = ROOT / f"{module}.py"
            if nxt.exists() and nxt not in seen:
                frontier.append(nxt)

    assert not missing, (
        "root modules reachable from shipped code but absent from py-modules: "
        f"{sorted(missing)} — an installed server importing them from a user's "
        "workspace will raise ModuleNotFoundError")


def test_the_two_that_were_missing_are_listed():
    """Named explicitly so a future reshuffle of py-modules cannot quietly drop
    the ones that were actually observed breaking a run."""
    listed = _listed_modules()
    assert "judgment_view" in listed
    assert "claim" in listed
