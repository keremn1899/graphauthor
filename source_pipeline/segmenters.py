"""Small deterministic reference segmenters.

These are demonstrations of the protocol, not universal semantic chunkers.
"""

from __future__ import annotations

import hashlib
import re

from source_pipeline.contracts import (
    SegmentationContext,
    SegmentationDecision,
    SegmenterDescriptor,
    SourceAtom,
    SourceUnit,
)


class BoundedTextSegmenter:
    """Losslessly bound an oversized text unit at nearby textual breaks."""

    descriptor = SegmenterDescriptor(
        segmenter_id="bounded-text",
        version=1,
    )

    def supports(self, unit: SourceUnit, context: SegmentationContext) -> bool:
        return len(unit.text) > context.max_atom_chars

    @staticmethod
    def _boundary(text: str, start: int, limit: int) -> int:
        minimum = start + max(1, (limit - start) // 2)
        candidates: list[int] = []
        for pattern in (r"\n\n", r"\n", r"(?<=[.!?])\s+", r"\s+"):
            candidates = [
                match.end()
                for match in re.finditer(pattern, text[start:limit])
                if start + match.end() >= minimum
            ]
            if candidates:
                return start + candidates[-1]
        return limit

    def segment(
        self,
        unit: SourceUnit,
        context: SegmentationContext,
    ) -> SegmentationDecision:
        spans: list[tuple[int, int]] = []
        start = 0
        while start < len(unit.text):
            limit = min(len(unit.text), start + context.max_atom_chars)
            end = (
                len(unit.text)
                if limit == len(unit.text)
                else self._boundary(unit.text, start, limit)
            )
            spans.append((start, end))
            start = end

        atoms = []
        locator_hash = hashlib.sha256(unit.locator.encode("utf-8")).hexdigest()[:8]
        for index, (start, end) in enumerate(spans, start=1):
            atoms.append(
                SourceAtom(
                    atom_id=f"{unit.unit_id}@bounded-{locator_hash}-{index}",
                    source_id=unit.source_id,
                    unit_id=unit.unit_id,
                    start=start,
                    end=end,
                    text=unit.text[start:end],
                    label=f"{unit.kind} part {index}",
                    metadata={"segmented_by": self.descriptor.segmenter_id},
                )
            )
        return SegmentationDecision(
            status="APPLIED",
            atoms=tuple(atoms),
            basis="heuristic",
        )
