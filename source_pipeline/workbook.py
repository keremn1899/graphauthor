"""The workbook: where a construction lives so it can be found again.

Deliberately thin. Running a program is native to an agent — it has a terminal
and writes Python — so this is a directory convention and a manifest, not an
execution engine.

```
workbook/
  workbook.json    sources, parser config, who wrote the atom stream, baseline
  atoms.jsonl      the atom stream, one JSON object per line
  build.py         the agent's program (we never write this)
  out/encoding.json
  out/graph.lbug + graph.lbug.sources.json
```

**One atom stream, and the manifest says who wrote it.** The construction
program chooses its own parsers, so a default
`prepare` could produce a different stream than the program does — which is
exactly the divergence the stream exists to prevent. The manifest therefore
records the producer, and everything reads that one file.

The manifest is fingerprinted against source content. A stale stream is
refused rather than silently used, because authoring against a stale view is
the failure that surfaces much later as an inexplicable acceptance result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

MANIFEST_NAME = "workbook.json"
ATOMS_NAME = "atoms.jsonl"
SCHEMA_VERSION = "workbook-v1"


@dataclass(frozen=True)
class Atom:
    """One addressable passage, as both exploration and the program see it."""

    atom_id: str
    source_id: str
    unit_id: str
    text: str
    start: int
    end: int
    kind: str = ""
    heading_path: tuple[str, ...] = ()
    locator: str = ""
    #: Set by the parser that produced it, never inferred downstream.
    chrome: bool = False
    #: The unit carried running prose. Set by the parser that produced
    #: it, because each parser has its own `kind` vocabulary and a
    #: program selecting on `kind` works for one and silently matches
    #: nothing for the rest.
    prose: bool = False

    @property
    def chars(self) -> int:
        return len(self.text)

    def to_json(self) -> dict[str, Any]:
        return {
            "atom_id": self.atom_id,
            "source_id": self.source_id,
            "unit_id": self.unit_id,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "kind": self.kind,
            "heading_path": list(self.heading_path),
            "locator": self.locator,
            "chrome": self.chrome,
            "prose": self.prose,
        }

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "Atom":
        return cls(
            atom_id=row["atom_id"],
            source_id=row.get("source_id", ""),
            unit_id=row.get("unit_id", ""),
            text=row.get("text", ""),
            start=int(row.get("start", 0)),
            end=int(row.get("end", 0)),
            kind=row.get("kind", ""),
            heading_path=tuple(row.get("heading_path") or ()),
            locator=row.get("locator", ""),
            chrome=bool(row.get("chrome", False)),
            prose=bool(row.get("prose", False)),
        )


class StaleAtomStream(RuntimeError):
    """The sources moved under the stream. Re-prepare rather than guess."""


@dataclass
class Workbook:
    root: Path
    manifest: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def open(cls, root: Path | str) -> "Workbook":
        root = Path(root)
        path = root / MANIFEST_NAME
        if not path.exists():
            raise FileNotFoundError(
                f"no workbook at {root}; run `workbook prepare --workbook {root} "
                "--source ...` first"
            )
        return cls(root=root, manifest=json.loads(path.read_text()))

    @property
    def atoms_path(self) -> Path:
        return self.root / ATOMS_NAME

    def source_fingerprint(self) -> str:
        """Content hash of every source, in declared order."""
        digest = hashlib.sha256()
        for entry in self.manifest.get("sources") or []:
            digest.update(entry["sha256"].encode("utf-8"))
        return digest.hexdigest()[:16]

    def check_fresh(self) -> None:
        """Refuse a stream whose sources have changed since it was written."""
        recorded = self.manifest.get("source_fingerprint", "")
        live = hashlib.sha256()
        for entry in self.manifest.get("sources") or []:
            path = Path(entry["path"])
            if not path.exists():
                raise StaleAtomStream(f"source has gone: {path}")
            live.update(
                hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8")
            )
        if live.hexdigest()[:16] != recorded:
            raise StaleAtomStream(
                "sources have changed since the atom stream was written; "
                "re-run `workbook prepare`"
            )

    def atoms(self) -> Iterator[Atom]:
        if not self.atoms_path.exists():
            raise FileNotFoundError(f"no atom stream at {self.atoms_path}")
        with self.atoms_path.open() as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield Atom.from_json(json.loads(line))


def write_workbook(
    root: Path | str,
    *,
    sources: list[Path],
    atoms: list[Atom],
    producer: str,
    parser_config: dict[str, Any] | None = None,
) -> Workbook:
    """Write the stream and the manifest that pins it."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    source_entries = []
    digest = hashlib.sha256()
    for path in sources:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(sha.encode("utf-8"))
        source_entries.append({
            "path": str(path),
            "sha256": sha,
            "bytes": path.stat().st_size,
        })

    with (root / ATOMS_NAME).open("w") as handle:
        for atom in atoms:
            handle.write(json.dumps(atom.to_json(), ensure_ascii=False) + "\n")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "sources": source_entries,
        "source_fingerprint": digest.hexdigest()[:16],
        # Who wrote the stream: `prepare` with the recorded config, or a
        # program that parses its own way. Exploration reads whichever it is,
        # so this is the field that keeps one view rather than two.
        "atom_stream_producer": producer,
        "parser_config": parser_config or {},
        "atom_count": len(atoms),
        # Set when a graph is published out of this workbook. A rebuild whose
        # baseline has moved underneath it must refuse: proposals made outside
        # would otherwise be silently reverted.
        "baseline_graph_version": "",
    }
    (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")
    return Workbook(root=root, manifest=manifest)
