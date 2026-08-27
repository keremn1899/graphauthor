"""Persistent embedding cache — avoids re-embedding unchanged anchors across DB rebuilds.

Embeddings are keyed on SHA-256(model + "\x00" + anchor) and stored compressed
in a SQLite file that lives alongside the .lbug it was built for. The file
survives DB deletion/rebuild, so a predicate-map change (edge-only rebuild)
or a crash-and-resume never hits the embedding API for nodes whose anchor
hasn't changed.

Usage:
    cache = EmbeddingCache(path)
    emb = cache.get(model, anchor)   # None on miss
    cache.put(model, anchor, emb)
    cache.commit()                   # flush every N puts
    cache.close()
"""

from __future__ import annotations

import hashlib
import sqlite3
import struct
import zlib
from pathlib import Path


def _pack(emb: list[float]) -> bytes:
    return zlib.compress(struct.pack(f"{len(emb)}f", *emb), level=1)


def _unpack(raw: bytes) -> list[float]:
    data = zlib.decompress(raw)
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def _key(model: str, anchor: str) -> str:
    return hashlib.sha256(f"{model}\x00{anchor}".encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, blob BLOB)"
        )
        self._db.commit()
        self._puts_since_commit = 0

    def get(self, model: str, anchor: str) -> list[float] | None:
        row = self._db.execute(
            "SELECT blob FROM cache WHERE key = ?", (_key(model, anchor),)
        ).fetchone()
        return _unpack(row[0]) if row else None

    def put(self, model: str, anchor: str, emb: list[float]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO cache (key, blob) VALUES (?, ?)",
            (_key(model, anchor), _pack(emb)),
        )
        self._puts_since_commit += 1

    def commit(self) -> None:
        self._db.commit()
        self._puts_since_commit = 0

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def __enter__(self) -> "EmbeddingCache":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
