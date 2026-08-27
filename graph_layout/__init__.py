"""Server-side arrangement of the ambient map.

Layout is a backend concern here (decided 2026-07-27): it is persisted so every
client sees the same map in the same place, and the frontend never lays out. G6
renders the coordinates this package produces; it does not compute them.

Pure Python on purpose. Because layout is deterministic, versioned and cached,
it is allowed to be slow — we pay once per topology change and amortise it over
the life of the graph. That is an asymmetry over anything running a force
layout live in a browser, and it is worth spending.

See `design [new]/graph-arrangement.md`.
"""

from graph_layout.contract import (
    Arrangement,
    LENSES,
    DEFAULT_LENS,
    arrange,
    lens_names,
    select_lens,
)
from graph_layout.ordering import Ordering, reconcile

__all__ = [
    "Arrangement",
    "LENSES",
    "DEFAULT_LENS",
    "Ordering",
    "arrange",
    "lens_names",
    "select_lens",
    "reconcile",
]
