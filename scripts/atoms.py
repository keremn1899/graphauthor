#!/usr/bin/env python3
"""Prepare and inspect a workbook, then validate or materialize its output.

Exploration has two halves and only the second is interesting. Browsing a
source is easy; `coverage` — which atoms a program produced nothing from — is
the repair loop, and it is ranked by size because a hundred ignored one-line
atoms are navigation chrome while one ignored 6,000-character passage is a
real miss.

    workbook prepare     --workbook wb --source a.html b.pdf
    workbook stats       --workbook wb
    workbook grep        --workbook wb "Hrafnkell" -C 1
    workbook show        --workbook wb <atom_id>
    workbook sample      --workbook wb -n 5 --seed 7
    workbook coverage    --workbook wb --encoding wb/out/encoding.json
    workbook validate    --workbook wb --encoding wb/out/encoding.json
    workbook audit       --workbook wb --encoding wb/out/encoding.json
    workbook materialize --workbook wb --encoding wb/out/encoding.json

Everything reads the same stream the program does. Grepping raw source instead
is authoring against a view the program never receives.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from source_pipeline import (
    BoundedTextSegmenter,
    HtmlSourceParser,
    MarkdownSourceParser,
    PdfSourceParser,
    PlainTextSourceParser,
    SegmentationContext,
    SourceArtifact,
    parse_artifact,
    segment_parsed_source,
)
from source_pipeline.workbook import Atom, StaleAtomStream, Workbook, write_workbook
from source_pipeline.encoding import (
    canonical_encoding,
    predicate_vocabulary,
    validate_encoding,
    write_graph,
)

MEDIA = {
    ".html": "text/html", ".htm": "text/html", ".xhtml": "text/html",
    ".md": "text/markdown", ".markdown": "text/markdown",
    ".pdf": "application/pdf", ".txt": "text/plain", ".rst": "text/x-rst",
}


def _line(atom: Atom, note: str = "") -> str:
    head = " > ".join(atom.heading_path[-2:]) if atom.heading_path else "-"
    preview = re.sub(r"\s+", " ", atom.text)[:70]
    return f"{atom.atom_id:44} {atom.chars:>6}c  {head:38} {preview!r}{note}"


def _load(args) -> tuple[Workbook, list[Atom]]:
    book = Workbook.open(args.workbook)
    try:
        book.check_fresh()
    except StaleAtomStream as error:
        # A stale stream is refused rather than used: authoring against a view
        # that no longer matches the sources fails much later and confusingly.
        raise SystemExit(f"workbook: {error}")
    return book, list(book.atoms())


def _read_encoding(path: Path | str) -> dict:
    value = json.loads(Path(path).read_text())
    if isinstance(value, dict) and "encoding" in value:
        value = value["encoding"]
    if not isinstance(value, dict):
        raise SystemExit("workbook: encoding must be a JSON object")
    return value


def _known_source_ids(atoms: list[Atom]) -> set[str]:
    return {
        ref
        for atom in atoms
        for ref in (str(atom.atom_id), str(atom.unit_id))
        if ref
    }


def cmd_prepare(args) -> int:
    sources = [Path(v).resolve() for v in args.source]
    parsers = [
        HtmlSourceParser(), MarkdownSourceParser(),
        PdfSourceParser(), PlainTextSourceParser(),
    ]
    atoms: list[Atom] = []
    for path in sources:
        media = args.media_type.strip() or MEDIA.get(path.suffix.lower(), "text/plain")
        artifact = SourceArtifact(
            source_id=path.stem, media_type=media,
            content=path.read_bytes(), locator=str(path),
        )
        parsed = parse_artifact(artifact, parsers)
        segmented = segment_parsed_source(
            parsed, [BoundedTextSegmenter()],
            context=SegmentationContext(max_atom_chars=args.max_atom_chars),
        )
        units = {u.unit_id: u for u in parsed.units}
        for atom in segmented.atoms:
            unit = units.get(atom.unit_id)
            atoms.append(Atom(
                atom_id=atom.atom_id, source_id=atom.source_id,
                unit_id=atom.unit_id, text=atom.text,
                start=atom.start, end=atom.end,
                kind=(unit.kind if unit else ""),
                heading_path=tuple(unit.heading_path) if unit else (),
                locator=(unit.locator if unit else ""),
                chrome=bool(unit.chrome) if unit else False,
                prose=bool(unit.prose) if unit else False,
            ))

    book = write_workbook(
        args.workbook, sources=sources, atoms=atoms, producer="atoms-prepare",
        parser_config={"max_atom_chars": args.max_atom_chars},
    )
    print(json.dumps({
        "workbook": str(book.root), "sources": len(sources),
        "atoms": len(atoms), "producer": "atoms-prepare",
        "source_fingerprint": book.manifest["source_fingerprint"],
    }, indent=2))
    return 0


def cmd_stats(args) -> int:
    book, atoms = _load(args)
    if not atoms:
        print("no atoms"); return 1
    sizes = sorted(a.chars for a in atoms)
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    chrome_count = 0
    for atom in atoms:
        by_source[atom.source_id] = by_source.get(atom.source_id, 0) + 1
        by_kind[atom.kind or "?"] = by_kind.get(atom.kind or "?", 0) + 1
        if atom.chrome:
            chrome_count += 1

    def pct(p: float) -> int:
        return sizes[min(len(sizes) - 1, int(len(sizes) * p))]

    report = {
        "atoms": len(atoms),
        "producer": book.manifest.get("atom_stream_producer"),
        "chars_total": sum(sizes),
        "chars": {"min": sizes[0], "p50": pct(0.5), "p90": pct(0.9),
                  "p99": pct(0.99), "max": sizes[-1]},
        "by_source": dict(sorted(by_source.items(), key=lambda kv: -kv[1])),
        "by_kind": dict(sorted(by_kind.items(), key=lambda kv: -kv[1])),
        # Chrome is whatever the parser flagged as navigation, not a guess
        # made here from a missing heading path — that guess was right for
        # one site's HTML and dropped every page of a PDF.
        "chrome": chrome_count,
        "prose": sum(1 for a in atoms if a.prose),
    }
    print(json.dumps(report, indent=2) if args.json else _render_stats(report))
    return 0


def _render_stats(r: dict) -> str:
    lines = [
        f"{r['atoms']} atoms, {r['chars_total']:,} chars   (stream written by {r['producer']})",
        f"  chars  min {r['chars']['min']}  p50 {r['chars']['p50']}  "
        f"p90 {r['chars']['p90']}  p99 {r['chars']['p99']}  max {r['chars']['max']}",
        f"  flagged as chrome by the parser: {r['chrome']}",
        f"  carrying prose, per the parser:  {r['prose']}",
        "  by kind:   " + ", ".join(f"{k}={v}" for k, v in r["by_kind"].items()),
    ]
    sources = list(r["by_source"].items())
    lines.append("  by source: " + ", ".join(f"{k}={v}" for k, v in sources[:6])
                 + (f"  (+{len(sources)-6} more)" if len(sources) > 6 else ""))
    return "\n".join(lines)


def cmd_grep(args) -> int:
    book, atoms = _load(args)
    flags = 0 if args.case_sensitive else re.IGNORECASE
    pattern = re.compile(args.pattern, flags)
    hits = 0
    for atom in atoms:
        if args.kind and atom.kind != args.kind:
            continue
        if args.source and atom.source_id != args.source:
            continue
        if not pattern.search(atom.text):
            continue
        hits += 1
        if hits > args.limit:
            continue
        print(_line(atom))
        if args.context:
            for match in list(pattern.finditer(atom.text))[: args.context]:
                lo = max(0, match.start() - 60)
                hi = min(len(atom.text), match.end() + 60)
                snippet = re.sub(r"\s+", " ", atom.text[lo:hi])
                print(f"      …{snippet}…")
    print(f"\n{hits} atom(s) matched" + (f", showing {args.limit}" if hits > args.limit else ""))
    return 0 if hits else 1


def cmd_show(args) -> int:
    _, atoms = _load(args)
    index = {a.atom_id: i for i, a in enumerate(atoms)}
    if args.atom_id not in index:
        print(f"no such atom: {args.atom_id}", file=sys.stderr); return 2
    i = index[args.atom_id]
    atom = atoms[i]
    print(f"{atom.atom_id}\n  source   {atom.source_id}\n  kind     {atom.kind}")
    print(f"  heading  {' > '.join(atom.heading_path) or '-'}")
    print(f"  offsets  {atom.start}-{atom.end} ({atom.chars} chars)")
    print(f"  locator  {atom.locator}\n")
    print(atom.text)
    if i:
        print(f"\n  previous: {atoms[i-1].atom_id}")
    if i + 1 < len(atoms):
        print(f"  next:     {atoms[i+1].atom_id}")
    return 0


def cmd_sample(args) -> int:
    _, atoms = _load(args)
    # Seeded: an unseeded sample makes every finding an anecdote nobody else
    # can re-check.
    rng = random.Random(args.seed)
    for atom in rng.sample(atoms, min(args.n, len(atoms))):
        print(_line(atom))
    print(f"\n{min(args.n, len(atoms))} of {len(atoms)} atoms, seed {args.seed}")
    return 0


def cmd_coverage(args) -> int:
    _, atoms = _load(args)
    encoding = _read_encoding(args.encoding)

    used: set[str] = set()
    for row in list(encoding.get("concepts") or []) + list(encoding.get("edges") or []):
        for unit_id in row.get("source_unit_ids") or []:
            used.add(str(unit_id))

    # Match on either grain. The field is called `source_unit_ids`, the
    # acceptance check is `every_node_has_a_source_unit`, and the stream
    # exposes both `unit_id` and `atom_id` -- so citing the unit is the
    # name-correct choice, and matching only on `atom_id` reported an entire
    # 1,442-atom corpus as unused while `every_node_has_a_source_unit` passed.
    #
    # Two cold agents hit this independently: one read this function's source
    # and picked `atom_id`, the other followed the naming and got 0/1442.
    # Being strict here does not enforce a convention, it just makes the
    # coverage number silently wrong for one of the two reasonable choices.
    missed = [a for a in atoms
              if a.atom_id not in used and a.unit_id not in used]
    # Ranked by size: a hundred ignored one-line atoms are chrome, one ignored
    # 6,000-character passage is a real miss, and only size ordering shows it.
    missed.sort(key=lambda a: -a.chars)
    chrome = [a for a in missed if a.chrome]

    print(f"{len(atoms) - len(missed)}/{len(atoms)} atoms contributed to the encoding")
    print(f"{len(missed)} produced nothing"
          f" ({sum(a.chars for a in missed):,} chars), largest first:\n")
    for atom in missed[: args.limit]:
        print(_line(atom, note="   [chrome]" if atom.chrome else ""))
    if chrome:
        print(f"\n{len(chrome)} of those are parser-flagged chrome, and are "
              "usually correct to ignore")
    # The inverse view: chrome that DID produce nodes is how a translator's
    # name ends up as a character.
    chrome_used = [a for a in atoms
                   if a.chrome and (a.atom_id in used or a.unit_id in used)]
    if chrome_used:
        print(f"\nWARNING: {len(chrome_used)} chrome atom(s) DID produce "
              "nodes — check for boilerplate leaking in:")
        for atom in chrome_used[:5]:
            print(_line(atom))
    return 0


def cmd_validate(args) -> int:
    _, atoms = _load(args)
    encoding = _read_encoding(args.encoding)
    problems = validate_encoding(
        encoding, known_source_unit_ids=_known_source_ids(atoms)
    )
    report = {
        "status": "VALID" if not problems else "INVALID",
        "problems": problems,
        "concepts": len(encoding.get("concepts") or []),
        "edges": len(encoding.get("edges") or []),
    }
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


def cmd_audit(args) -> int:
    """One machine-readable feedback pass for an agent's edit/run/audit loop."""
    _, atoms = _load(args)
    encoding = _read_encoding(args.encoding)
    known = _known_source_ids(atoms)
    problems = validate_encoding(encoding, known_source_unit_ids=known)
    used = {
        str(ref)
        for row in list(encoding.get("concepts") or []) + list(encoding.get("edges") or [])
        if isinstance(row, dict)
        for ref in row.get("source_unit_ids") or []
    }
    unused = [
        atom for atom in atoms
        if atom.atom_id not in used and atom.unit_id not in used
    ]
    chrome_used = [
        atom for atom in atoms
        if atom.chrome and (atom.atom_id in used or atom.unit_id in used)
    ]
    substantive_unused = [
        atom for atom in unused if atom.prose and atom.chars >= args.substantive_chars
    ]
    report = {
        "status": "VALID" if not problems else "INVALID",
        "mechanical_problems": problems,
        "concepts": len(encoding.get("concepts") or []),
        "edges": len(encoding.get("edges") or []),
        "predicate_vocabulary": predicate_vocabulary(encoding) if not problems else {},
        "coverage": {
            "atoms_total": len(atoms),
            "atoms_contributed": len(atoms) - len(unused),
            "unused_atom_ids": [atom.atom_id for atom in sorted(unused, key=lambda row: -row.chars)],
            "substantive_unused_atom_ids": [
                atom.atom_id for atom in sorted(substantive_unused, key=lambda row: -row.chars)
            ],
            "chrome_used_atom_ids": [atom.atom_id for atom in chrome_used],
        },
        "interpretation": (
            "Coverage fields are repair observations, not generic completeness criteria. "
            "The workbook program decides which unused units matter."
        ),
    }
    print(json.dumps(report, indent=2))
    return 0 if not problems else 1


def cmd_materialize(args) -> int:
    book, _ = _load(args)
    encoding = _read_encoding(args.encoding)
    out = Path(args.out) if args.out else book.root / "out" / "graph.lbug"
    encoding_out = book.root / "out" / "encoding.json"
    encoding_out.parent.mkdir(parents=True, exist_ok=True)
    encoding_out.write_text(
        json.dumps(canonical_encoding(encoding), indent=2, ensure_ascii=False) + "\n"
    )
    traversal_input = Path(args.traversals) if args.traversals else Path(args.encoding).with_name("traversals.json")
    traversals = None
    if args.traversals and not traversal_input.exists():
        raise SystemExit(f"traversal program file does not exist: {traversal_input}")
    if traversal_input.exists():
        traversals = json.loads(traversal_input.read_text(encoding="utf-8"))
    write_graph(encoding, out, workbook=book, traversals=traversals)
    report = {
        "status": "MATERIALIZED",
        "graph": str(out),
        "encoding": str(encoding_out),
        "sources": str(out) + ".sources.json",
        "metadata": str(out) + ".metadata.json",
    }
    if traversals is not None:
        report["traversals"] = str(out) + ".traversals.json"
    print(json.dumps(report, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workbook", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workbook", default="workbook", help="Workbook directory")

    # `--workbook` reads naturally after the subcommand, and the docstring
    # above wrote it that way before argparse was, so it is accepted in both
    # positions. SUPPRESS is what makes that work: without it the subparser
    # would set `workbook` to its own default and silently overwrite a value
    # given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workbook", default=argparse.SUPPRESS,
                        help="Workbook directory")

    sub = p.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", parents=[common], help="Parse and segment sources into the workbook")
    prep.add_argument("--source", required=True, nargs="+")
    prep.add_argument("--max-atom-chars", type=int, default=6000)
    prep.add_argument("--media-type", default="")
    prep.set_defaults(func=cmd_prepare)

    st = sub.add_parser("stats", parents=[common], help="Shape of the corpus")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    gr = sub.add_parser("grep", parents=[common], help="Find atoms matching a regex")
    gr.add_argument("pattern")
    gr.add_argument("-C", "--context", type=int, default=0,
                    help="Show up to N matched snippets per atom")
    gr.add_argument("--kind", default="")
    gr.add_argument("--source", default="")
    gr.add_argument("--limit", type=int, default=40)
    gr.add_argument("--case-sensitive", action="store_true")
    gr.set_defaults(func=cmd_grep)

    sh = sub.add_parser("show", parents=[common], help="One atom in full")
    sh.add_argument("atom_id")
    sh.set_defaults(func=cmd_show)

    sa = sub.add_parser("sample", parents=[common], help="A reproducible sample")
    sa.add_argument("-n", type=int, default=5)
    sa.add_argument("--seed", type=int, default=0)
    sa.set_defaults(func=cmd_sample)

    cv = sub.add_parser("coverage", parents=[common], help="Which atoms produced nothing")
    cv.add_argument("--encoding", required=True)
    cv.add_argument("--limit", type=int, default=20)
    cv.set_defaults(func=cmd_coverage)

    va = sub.add_parser("validate", parents=[common], help="Check an agent-authored encoding mechanically")
    va.add_argument("--encoding", required=True)
    va.set_defaults(func=cmd_validate)

    audit = sub.add_parser(
        "audit", parents=[common], help="Machine-readable validation and coverage feedback"
    )
    audit.add_argument("--encoding", required=True)
    audit.add_argument(
        "--substantive-chars", type=int, default=40,
        help="Report unused prose atoms at least this large (observation only)",
    )
    audit.set_defaults(func=cmd_audit)

    ma = sub.add_parser("materialize", parents=[common], help="Write a valid encoding as a graph")
    ma.add_argument("--encoding", required=True)
    ma.add_argument("--out", default="", help="Defaults to WORKBOOK/out/graph.lbug")
    ma.add_argument(
        "--traversals",
        default="",
        help="Agent-authored traversal programs; defaults to encoding directory/traversals.json when present",
    )
    ma.set_defaults(func=cmd_materialize)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
