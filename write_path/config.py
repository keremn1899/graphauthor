"""Configurable knobs for write-path machinery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RecurrenceConfig:
    """How often a typed predicate must appear before curation review."""

    min_occurrences: int = 3
    window_size: int | None = None  # optional cap on recent records considered

    def __post_init__(self) -> None:
        if self.min_occurrences < 1:
            raise ValueError("min_occurrences must be >= 1")
