"""Deterministic graphs for surface tests — built, never borrowed.

The grain-path tests used to copy `data/construction_runs/graphs/*.lbug`, which
is a gitignored build output: green on the machine that happened to produce it,
`pytest.skip` everywhere else. A test that skips when the artifact is missing
reports the same thing whether the code works or nobody ever ran it.

`build_fixture` writes the hexagonal-orders corpus with orthogonal unit-vector
embeddings, so none of this needs OpenRouter.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.fixture import build_fixture

#: A recorded grain identity in the shape `construction` writes it: two rule
#: nodes, each deciding on its own text. That self-containment is the property
#: the grain gate measures, so an exemplar set that lacked it would make the
#: tests agree with a reference the real gate would reject.
GRAIN_SEEDS = [
    {
        "id": "retry_limit_rule",
        "label": "Retry limit",
        "text_content": (
            "ADJUDICATES: If a component issues an outbound HTTP call, then it "
            "MUST NOT retry more than three times."
        ),
    },
    {
        "id": "cache_eviction_rule",
        "label": "Cache eviction",
        "text_content": (
            "ADJUDICATES: If a cache entry is older than one hour, then it "
            "MUST be evicted."
        ),
    },
]


def graph_with_grain(tmp_path, *, seeds=None) -> Path:
    """A fixture graph with a `.grain.json` sidecar beside it."""
    db = graph_without_grain(tmp_path)
    db.with_suffix(".grain.json").write_text(
        json.dumps({"seeds": list(GRAIN_SEEDS if seeds is None else seeds)}),
        encoding="utf-8",
    )
    return db


def graph_without_grain(tmp_path) -> Path:
    """The common case: a graph that never recorded a grain identity."""
    db = Path(tmp_path) / "g.lbug"
    build_fixture(db)
    return db
