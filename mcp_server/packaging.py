"""Project packaging (backlog C4) + durable lineage by travel (B3).

A graph is not just a `.lbug`. Its canonical workbook encoding, exact-source
sidecar, graph-local traversal recipes, and event/proposal store must travel
with it. The workbook program itself remains in the workbook and is not treated
as authority merely because it produced an encoding.

The bundle is a manifest-based archive (tar.gz): every source-of-truth component
is listed with a sha256, so integrity is verifiable and tampering is detectable
before anyone trusts the unpacked graph. Generated artifacts (the structural
`.idx`) are included for convenience but flagged `regenerable`.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_components(db_path: Path | str, *, store_path: Path | str | None = None,
                       config_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Gather a graph project's source-of-truth assets that must travel together.
    The store sidecar (events + proposals) is what carries lineage + receipts."""
    db = Path(db_path)
    store = Path(store_path) if store_path else db.with_suffix(".writestore.sqlite")
    candidates = [
        ("graph", db, False),
        ("encoding", db.parent / "encoding.json", False),
        ("sources", Path(str(db) + ".sources.json"), False),
        ("metadata", Path(str(db) + ".metadata.json"), False),
        ("recipes", db.with_suffix(".recipes.md"), False),
        ("stores", store, False),
        ("index", db.with_suffix(".lbug.idx"), True),
    ]
    if config_path:
        candidates.append(("config", Path(config_path), False))
    comps = []
    for kind, p, regenerable in candidates:
        if Path(p).exists():
            comps.append({"kind": kind, "name": Path(p).name, "path": str(p),
                          "regenerable": regenerable})
    return comps


def build_manifest(components: list[dict]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "components": [
            {"kind": c["kind"], "name": c["name"], "sha256": _sha256(Path(c["path"])),
             "bytes": Path(c["path"]).stat().st_size, "regenerable": c.get("regenerable", False)}
            for c in components
        ],
    }


def bundle(components: list[dict], out_archive: Path | str) -> dict[str, Any]:
    """Write the components + manifest into a tar.gz bundle."""
    out_archive = Path(out_archive)
    out_archive.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(components)
    with tarfile.open(out_archive, "w:gz") as tar:
        for c in components:
            tar.add(c["path"], arcname=f"components/{c['name']}")
        data = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return {"archive": str(out_archive), "manifest": manifest}


def read_manifest(archive: Path | str) -> dict[str, Any]:
    with tarfile.open(archive, "r:gz") as tar:
        f = tar.extractfile("manifest.json")
        return json.load(f)


def verify(archive: Path | str) -> dict[str, Any]:
    """Integrity check: every component present and hash-matching the manifest."""
    manifest = read_manifest(archive)
    mismatches: list[dict] = []
    with tarfile.open(archive, "r:gz") as tar:
        for c in manifest["components"]:
            member = tar.extractfile(f"components/{c['name']}")
            if member is None:
                mismatches.append({"name": c["name"], "reason": "missing"})
                continue
            h = hashlib.sha256()
            for chunk in iter(lambda: member.read(65536), b""):
                h.update(chunk)
            if h.hexdigest() != c["sha256"]:
                mismatches.append({"name": c["name"], "reason": "hash_mismatch"})
    return {"valid": not mismatches, "mismatches": mismatches, "manifest": manifest}


def unpack(archive: Path | str, dest: Path | str) -> dict[str, Any]:
    """Verify, then extract components. Refuses to unpack a tampered bundle."""
    dest = Path(dest)
    v = verify(archive)
    if not v["valid"]:
        return {"unpacked": False, "reason": "integrity check failed",
                "mismatches": v["mismatches"]}
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        for c in v["manifest"]["components"]:
            member = tar.extractfile(f"components/{c['name']}")
            (dest / c["name"]).write_bytes(member.read())
    return {"unpacked": True, "dest": str(dest), "manifest": v["manifest"],
            "components": [c["name"] for c in v["manifest"]["components"]]}
