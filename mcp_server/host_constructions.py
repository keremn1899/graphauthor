"""Host-agent constructions on the local product catalogue.

The catalogue walk (`graph_http.GraphCatalogue`) stops at
``OUTPUT_SCAN_DEPTH = 3``, and both of these graphs sit five and seven levels
down inside their run directories. So they are invisible to the default scan
even though they are in this tree — which is what the named shelf is for: a
directory link at depth one, carrying a readable label instead of the picker
saying "Uncertified Preview".

The constructions used to live only in the sibling host-agent worktree. They are
in this repository now, so **this tree is the first place looked**, and the
sibling is a fallback for a checkout that predates the merge.
``SST_HOST_AGENT_ROOT`` overrides where that fallback points.

``data/construction_trials/`` is gitignored; the links are local state, never a
commit.
"""

from __future__ import annotations

import os
from pathlib import Path


HOST_AGENT_DEFAULT = Path()

# (catalogue directory name, path relative to a repository root)
SHELF: tuple[tuple[str, Path], ...] = ()



def host_agent_root() -> Path:
    configured = os.environ.get("SST_HOST_AGENT_ROOT", "").strip()
    return Path(configured).expanduser() if configured else HOST_AGENT_DEFAULT


def resolve_shelf_source(project_root: Path | str, relative: Path) -> Path | None:
    """Where this construction actually is: this repo first, sibling second.

    Returning the local copy matters beyond tidiness — a link into the sibling
    worktree breaks when that worktree is removed or checks out another branch,
    and the catalogue would then offer a row that cannot be opened.
    """
    for root in (Path(project_root), host_agent_root()):
        candidate = root / relative
        if (candidate / "graph.lbug").is_file():
            return candidate
    return None


def ensure_host_construction_shelf(project_root: Path | str) -> list[Path]:
    """Link present host constructions into this worktree's construction trials.

    Returns the ``graph.lbug`` paths that are now on the local shelf. A
    construction found in neither root is skipped. A real directory already
    occupying a shelf name is left alone; a stale link is repointed.
    """
    root = Path(project_root)
    dest_root = root / "data" / "construction_trials"
    linked: list[Path] = []
    for name, relative in SHELF:
        source = resolve_shelf_source(root, relative)
        if source is None:
            continue
        dest_root.mkdir(parents=True, exist_ok=True)
        dest = dest_root / name
        try:
            if dest.is_symlink():
                if dest.resolve() == source.resolve():
                    linked.append(dest / "graph.lbug")
                    continue
                # Points somewhere else — most likely the sibling worktree from
                # before these graphs landed here. Repoint it.
                dest.unlink()
            elif dest.exists():
                existing = dest / "graph.lbug"
                if existing.is_file():
                    linked.append(existing)
                continue
            dest.symlink_to(source.resolve(), target_is_directory=True)
        except OSError:
            continue
        linked.append(dest / "graph.lbug")
    return linked
