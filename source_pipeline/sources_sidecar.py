"""`graph.lbug.sources.json` — resolve a node's source units back to text.

A graph cannot show its own sources. `Concept.source_unit_ids` holds atom
*ids*; the passage text lives in the workbook's `atoms.jsonl`; and nothing
beside a built `.lbug` names the workbook that built it. The join key is
exact — atom id to atom id, no matching and no heuristic — so the only thing
missing is a pointer.

This is that pointer, written beside the graph at materialization:

```
graph.lbug                  the graph
graph.lbug.sources.json     {atom_id: {excerpt, locator, heading_path, span}}
```

**Why a copy rather than a path to the workbook.** A path breaks when the
workbook moves, and a graph that cannot explain itself once it has been copied
somewhere is not portable. So the excerpt travels with the graph.

**Why that is safe here.** The sidecar carries the same `source_fingerprint`
the workbook manifest computes, so drift is *detectable*: asked to resolve a
unit, it can say "the source changed after this graph was built" instead of
quietly returning an excerpt that no longer matches. That is the read-side
version of the refusal `StaleAtomStream` already makes on the write side, and
it is the whole reason a copy is acceptable — an undetectable copy would not
be.

A graph with no sidecar degrades honestly. `resolve` returns `None` and the
reader says the source is not available for this graph, rather than showing
nothing and implying there was none to show.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

SIDECAR_SUFFIX = ".sources.json"
SCHEMA_VERSION = "sources-v1"

#: Enough to recognise the passage, not enough to be a second copy of the
#: corpus. A reader who needs the whole unit opens the workbook.
EXCERPT_CHARS = 2000


def sidecar_path(graph_path: Path | str) -> Path:
    return Path(str(graph_path) + SIDECAR_SUFFIX)


@dataclass(frozen=True)
class ResolvedUnit:
    """One source passage, as the reader should show it."""

    atom_id: str
    excerpt: str
    locator: str
    heading_path: tuple[str, ...]
    start: int
    end: int
    truncated: bool
    #: Parser-flagged boilerplate: page furniture, nav chrome, running heads.
    chrome: bool = False
    #: Full length of the unit, not of the excerpt.
    chars: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "excerpt": self.excerpt,
            "locator": self.locator,
            "heading_path": list(self.heading_path),
            "start": self.start,
            "end": self.end,
            "truncated": self.truncated,
            "chrome": self.chrome,
            "chars": self.chars,
        }


class SourcesStale(RuntimeError):
    """The sources moved after this graph was built. Say so; do not guess."""


def write_sidecar(
    graph_path: Path | str,
    atoms: Iterable[Any],
    *,
    source_fingerprint: str,
    workbook_root: Path | str | None = None,
) -> Path:
    """Write the sidecar for a graph from the atom stream that built it.

    `atoms` is anything carrying `atom_id` / `text` / `locator` /
    `heading_path` / `start` / `end` — the `Atom` dataclass, or a plain dict.
    Construction passes both shapes around, and an attribute-only reader would
    write a sidecar full of empty rows for the dict case without failing.
    """
    def _get(atom: Any, key: str, default: Any = "") -> Any:
        if isinstance(atom, Mapping):
            return atom.get(key, default)
        return getattr(atom, key, default)

    units: dict[str, Any] = {}
    #: unit_id -> the atom ids that came from it. Workbook programs may cite
    #: either the parser-level unit or the bounded atom. A sidecar keyed only
    #: on atom ids would silently fail to resolve the first, producing a blank
    #: panel that looks like a graph without sources rather than a missed join.
    by_unit: dict[str, list[str]] = {}
    for atom in atoms:
        text = str(_get(atom, "text") or "")
        excerpt = text[:EXCERPT_CHARS]
        units[str(_get(atom, "atom_id"))] = {
            "excerpt": excerpt,
            "locator": str(_get(atom, "locator") or ""),
            "heading_path": list(_get(atom, "heading_path", ()) or ()),
            "start": int(_get(atom, "start", 0) or 0),
            "end": int(_get(atom, "end", 0) or 0),
            "truncated": len(text) > EXCERPT_CHARS,
            # Set by the parser that produced the atom, never inferred here.
            # Without it a coverage view reports every page footer and running
            # header as an uncovered unit, and a hundred of those bury the one
            # six-thousand-character passage that is a real miss. `atoms
            # coverage` has always known this; the sidecar did not.
            "chrome": bool(_get(atom, "chrome", False)),
            "chars": len(text),
        }
        unit_id = str(_get(atom, "unit_id") or "")
        if unit_id:
            by_unit.setdefault(unit_id, []).append(str(_get(atom, "atom_id")))
    payload = {
        "schema": SCHEMA_VERSION,
        "source_fingerprint": source_fingerprint,
        "workbook_root": str(workbook_root) if workbook_root else "",
        "unit_count": len(units),
        "units": units,
        "by_unit": by_unit,
    }
    out = sidecar_path(graph_path)
    out.write_text(json.dumps(payload, indent=1, sort_keys=True))
    return out


@dataclass
class Sources:
    """Read side. Never raises for a missing sidecar; that is a normal state."""

    path: Path
    payload: Mapping[str, Any]

    @classmethod
    def for_graph(cls, graph_path: Path | str) -> "Sources | None":
        path = sidecar_path(graph_path)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            # A corrupt sidecar is the same situation as none: the graph
            # cannot show its sources. It must not take the graph down.
            return None
        return cls(path=path, payload=payload)

    @property
    def source_fingerprint(self) -> str:
        return str(self.payload.get("source_fingerprint") or "")

    @property
    def workbook_root(self) -> str:
        return str(self.payload.get("workbook_root") or "")

    def is_stale_against(self, live_fingerprint: str) -> bool:
        """True when the sources have changed since this graph was built.

        A caller that cannot compute a live fingerprint — the workbook is gone,
        the graph was copied elsewhere — passes "" and gets False. Unknown is
        not the same as stale, and claiming staleness we cannot demonstrate
        would train people to ignore the warning.
        """
        live = str(live_fingerprint or "")
        if not live or not self.source_fingerprint:
            return False
        return live != self.source_fingerprint

    def resolve(self, atom_id: str) -> ResolvedUnit | None:
        """Exact on the atom id, then exact on the unit id. Never fuzzy.

        The second lookup is not a fallback for typos -- it is the other
        vocabulary construction actually writes (see `write_sidecar`). A unit
        cut into several bounded atoms maps to several; `resolve` returns the
        first and `resolve_unit` returns all of them, because collapsing a
        real one-to-many into one silently drops evidence.
        """
        key = str(atom_id)
        row = (self.payload.get("units") or {}).get(key)
        if not isinstance(row, dict):
            for aid in (self.payload.get("by_unit") or {}).get(key, []):
                row = (self.payload.get("units") or {}).get(aid)
                if isinstance(row, dict):
                    atom_id = aid
                    break
        if not isinstance(row, dict):
            return None
        return ResolvedUnit(
            atom_id=str(atom_id),
            excerpt=str(row.get("excerpt") or ""),
            locator=str(row.get("locator") or ""),
            heading_path=tuple(row.get("heading_path") or ()),
            start=int(row.get("start") or 0),
            end=int(row.get("end") or 0),
            truncated=bool(row.get("truncated")),
            chrome=bool(row.get("chrome")),
            chars=int(row.get("chars") or len(str(row.get("excerpt") or ""))),
        )

    def resolve_all(self, atom_ids: Iterable[str]) -> list[ResolvedUnit]:
        out = []
        for aid in atom_ids:
            hit = self.resolve(aid)
            if hit is not None:
                out.append(hit)
        return out

    def resolve_unit(self, unit_id: str) -> list[ResolvedUnit]:
        """Every atom cut from one source unit, in the order they were written."""
        ids = (self.payload.get("by_unit") or {}).get(str(unit_id))
        if not ids:
            hit = self.resolve(unit_id)
            return [hit] if hit else []
        return [u for u in (self.resolve(a) for a in ids) if u is not None]

    def unit_ids_in_order(self) -> list[str]:
        """Every unit, in the order the atoms were written — document order.

        `unit_ids()` returns a set and is fine for membership. The coverage
        view must not use it: a *run* of uncovered units is a skipped section
        and reads completely differently from the same number scattered, and
        set order destroys exactly that.
        """
        return list((self.payload.get("units") or {}).keys())

    def unit_ids(self) -> set[str]:
        return set((self.payload.get("units") or {}).keys())

    def uncovered(self, cited: Iterable[str]) -> list[str]:
        """Units that produced no node — the coverage view's whole content.

        Ordered by the sidecar's own key order, which is the order the atoms
        were written, which is document order. A *run* of uncovered units is a
        skipped section and reads differently from the same number scattered;
        sorting would destroy exactly that signal.
        """
        cited_set = {str(c) for c in cited}
        return [uid for uid in (self.payload.get("units") or {}) if uid not in cited_set]
