"""Mechanical parser selection and verified segmentation execution."""

from __future__ import annotations

from collections.abc import Iterable

from source_pipeline.contracts import (
    ParseDiagnostic,
    ParsedSource,
    SegmentationContext,
    SegmentationDecision,
    SegmentationRecord,
    SegmentedSource,
    SourceArtifact,
    SourceAtom,
    SourceParser,
    SourceUnit,
    UnitSegmenter,
)


def parse_artifact(
    artifact: SourceArtifact,
    parsers: Iterable[SourceParser],
) -> ParsedSource:
    """Use the first declaring parser; selection order is explicit."""

    checked: list[str] = []
    for parser in parsers:
        checked.append(parser.descriptor.parser_id)
        support = parser.supports(artifact)
        if not support.supported:
            continue
        result = parser.parse(artifact)
        if result.parser != parser.descriptor:
            raise ValueError(
                f"parser {parser.descriptor.parser_id!r} returned a different descriptor"
            )
        if result.source_id != artifact.source_id:
            raise ValueError("parser changed source identity")
        if result.artifact_fingerprint != artifact.fingerprint():
            raise ValueError("parser result is not bound to the supplied artifact")
        return result
    raise ValueError(
        "no source parser accepted artifact; checked " + ", ".join(checked)
    )


def _validate_partition(
    unit: SourceUnit,
    decision: SegmentationDecision,
    context: SegmentationContext,
) -> tuple[SourceAtom, ...]:
    atoms = tuple(sorted(decision.atoms, key=lambda atom: (atom.start, atom.end)))
    cursor = 0
    seen: set[str] = set()
    for atom in atoms:
        if atom.atom_id in seen:
            raise ValueError(f"duplicate source atom id: {atom.atom_id}")
        seen.add(atom.atom_id)
        if atom.source_id != unit.source_id or atom.unit_id != unit.unit_id:
            raise ValueError("segmenter changed source or unit identity")
        if atom.start != cursor:
            raise ValueError(
                f"segmentation is not an exact partition of {unit.unit_id}: "
                f"expected offset {cursor}, got {atom.start}"
            )
        if atom.end > len(unit.text):
            raise ValueError(f"source atom lies outside unit: {atom.atom_id}")
        if unit.text[atom.start : atom.end] != atom.text:
            raise ValueError(f"source atom text does not match unit: {atom.atom_id}")
        if len(atom.text) > context.max_atom_chars:
            raise ValueError(
                f"source atom exceeds max_atom_chars={context.max_atom_chars}: "
                f"{atom.atom_id}"
            )
        cursor = atom.end
    if cursor != len(unit.text):
        raise ValueError(
            f"segmentation is not an exact partition of {unit.unit_id}: "
            f"ended at {cursor} of {len(unit.text)}"
        )
    return atoms


def _passthrough_atom(unit: SourceUnit) -> SourceAtom:
    return SourceAtom(
        atom_id=f"{unit.unit_id}@whole",
        source_id=unit.source_id,
        unit_id=unit.unit_id,
        start=0,
        end=len(unit.text),
        text=unit.text,
        label=unit.kind,
        metadata={"passthrough": True},
    )


def segment_parsed_source(
    parsed: ParsedSource,
    segmenters: Iterable[UnitSegmenter],
    *,
    context: SegmentationContext | None = None,
) -> SegmentedSource:
    """Try segmenters in order, preserving every declined unit as passthrough."""

    ctx = context or SegmentationContext()
    candidates = tuple(segmenters)
    all_atoms: list[SourceAtom] = []
    records: list[SegmentationRecord] = []

    for unit in parsed.units:
        attempted = []
        diagnostics: list[ParseDiagnostic] = []
        selected = None
        accepted: tuple[SourceAtom, ...] | None = None
        saw_failure = False
        saw_abstention = False

        for segmenter in candidates:
            if not segmenter.supports(unit, ctx):
                continue
            segmenter_id = segmenter.descriptor.segmenter_id
            attempted.append(segmenter.descriptor)
            try:
                decision = segmenter.segment(unit, ctx)
            except Exception as exc:
                saw_failure = True
                diagnostics.append(
                    ParseDiagnostic(
                        code="segmenter_exception",
                        severity="error",
                        message=f"{type(exc).__name__}: {exc}",
                        locator=unit.locator,
                        details={"segmenter_id": segmenter_id},
                    )
                )
                continue
            diagnostics.extend(decision.diagnostics)
            if (
                decision.basis == "agent_program"
                and not segmenter.descriptor.config_fingerprint
            ):
                raise ValueError(
                    "agent-authored segmenter requires a code/config fingerprint: "
                    f"{segmenter_id}"
                )
            if decision.status == "FAILED":
                saw_failure = True
                continue
            if decision.status == "ABSTAINED":
                saw_abstention = True
                continue
            accepted = _validate_partition(unit, decision, ctx)
            selected = segmenter.descriptor
            break

        if accepted is not None:
            all_atoms.extend(accepted)
            records.append(
                SegmentationRecord(
                    unit_id=unit.unit_id,
                    status="APPLIED",
                    attempted_segmenters=tuple(attempted),
                    selected_segmenter=selected,
                    atom_ids=tuple(atom.atom_id for atom in accepted),
                    diagnostics=tuple(diagnostics),
                )
            )
            continue

        passthrough = _passthrough_atom(unit)
        all_atoms.append(passthrough)
        status = "FAILED" if saw_failure else "ABSTAINED" if saw_abstention else "PASSTHROUGH"
        if len(unit.text) > ctx.max_atom_chars:
            diagnostics.append(
                ParseDiagnostic(
                    code="oversized_passthrough",
                    severity="warning",
                    message=(
                        f"no segmenter partitioned {len(unit.text)} characters; "
                        "the complete unit remains visible"
                    ),
                    locator=unit.locator,
                    details={"max_atom_chars": ctx.max_atom_chars},
                )
            )
        records.append(
            SegmentationRecord(
                unit_id=unit.unit_id,
                status=status,
                attempted_segmenters=tuple(attempted),
                atom_ids=(passthrough.atom_id,),
                diagnostics=tuple(diagnostics),
            )
        )

    return SegmentedSource(
        parsed_source_fingerprint=parsed.fingerprint(),
        atoms=tuple(all_atoms),
        records=tuple(records),
    )
