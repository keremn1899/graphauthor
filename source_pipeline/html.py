"""Deterministic visible-content extraction for fetched HTML pages.

Raw HTML remains pinned by ``SourceArtifact``.  This parser claims only an
addressable extracted-text representation: DOM selection, removed elements and
link resolution are all reported.  It performs no readability scoring and no
semantic graph construction.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from source_pipeline.contracts import (
    ParseDiagnostic,
    ParsedSource,
    ParserDescriptor,
    ParserSupport,
    SourceArtifact,
    assemble_units,
)


_INERT_TAGS = frozenset(
    {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object"}
)
_ATOMIC_TAGS = frozenset(
    {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "pre",
        "blockquote",
        "dt",
        "dd",
        "figcaption",
    }
)
_INLINE_TAGS = frozenset(
    {
        "a",
        "abbr",
        "b",
        "br",
        "cite",
        "code",
        "em",
        "i",
        "mark",
        "q",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
        "wbr",
    }
)


def _config_fingerprint(*, prefer_main: bool, drop_selectors: tuple[str, ...]) -> str:
    payload = json.dumps(
        {"prefer_main": prefer_main, "drop_selectors": drop_selectors},
        sort_keys=True,
        separators=(",", ":"),
    )
    return "hcfg_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _dom_path(tag) -> str:
    parts: list[str] = []
    cursor = tag
    while getattr(cursor, "name", None) and cursor.name != "[document]":
        same_name = [
            sibling
            for sibling in cursor.parent.children
            if getattr(sibling, "name", None) == cursor.name
        ] if getattr(cursor, "parent", None) is not None else [cursor]
        index = same_name.index(cursor) + 1 if cursor in same_name else 1
        parts.append(f"{cursor.name}[{index}]")
        cursor = cursor.parent
    return "/" + "/".join(reversed(parts))


def _clean_text(tag, *, preserve: bool = False) -> str:
    if preserve:
        return tag.get_text("", strip=False).strip("\n")
    return _normalize_inline(tag.get_text(" ", strip=True))


def _normalize_inline(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = re.sub(r"\s+([,.;:!?%)\]}])", r"\1", normalized)
    normalized = re.sub(r"([(\[{])\s+", r"\1", normalized)
    return normalized


def _direct_text(tag) -> str:
    """Visible inline text owned by a container, excluding nested blocks."""

    from bs4 import NavigableString

    pieces: list[str] = []
    for child in tag.children:
        if isinstance(child, NavigableString):
            pieces.append(str(child))
        elif getattr(child, "name", None) in _INLINE_TAGS:
            pieces.append(child.get_text(" ", strip=True))
    return _normalize_inline(" ".join(pieces))


def _inline_run(nodes, base_uri: str) -> tuple[str, tuple[str, ...]]:
    """Normalize one ordered run of direct text/inline children.

    Block descendants are never included, which is the accounting boundary
    that prevents a parent container from duplicating a paragraph later
    emitted as its own addressable unit.
    """

    from bs4 import NavigableString

    pieces: list[str] = []
    links: list[str] = []
    for node in nodes:
        if isinstance(node, NavigableString):
            pieces.append(str(node))
            continue
        if getattr(node, "name", "").casefold() in {"br", "wbr"}:
            pieces.append(" ")
        else:
            pieces.append(node.get_text(" ", strip=True))
        candidates = [node] if getattr(node, "name", "") == "a" else []
        candidates.extend(node.find_all("a", href=True))
        for anchor in candidates:
            href = str(anchor.get("href") or "").strip()
            if not href:
                continue
            resolved = urljoin(base_uri, href) if base_uri else href
            if resolved not in links:
                links.append(resolved)
    return _normalize_inline(" ".join(pieces)), tuple(links)


def _links(tag, base_uri: str) -> tuple[str, ...]:
    out: list[str] = []
    for anchor in tag.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        resolved = urljoin(base_uri, href) if base_uri else href
        if resolved not in out:
            out.append(resolved)
    return tuple(out)


#: Elements whose contents are what a page says about itself rather than what
#: it is about. The parser can see these because it holds the tree; a
#: downstream heuristic cannot, which is why the flag is set here.
#: The HTML kinds that carry running text. A parser knows this; a downstream
#: rule reading `kind` has to guess at a vocabulary it did not define.
_PROSE_KINDS = frozenset({"p", "text", "list_item", "blockquote"})

CHROME_ANCESTORS = frozenset({"nav", "footer", "header", "aside"})
CHROME_ROLES = frozenset({"navigation", "banner", "contentinfo", "complementary"})


def _is_chrome(tag) -> bool:
    """True when a block sits inside navigation or boilerplate.

    Walks ancestors rather than inspecting the block alone: a <p> is not
    chrome, and a <p> inside a <footer> is.
    """
    for parent in [tag, *tag.parents]:
        name = getattr(parent, "name", "") or ""
        if name in CHROME_ANCESTORS:
            return True
        try:
            role = str(parent.get("role") or "").strip().lower()
        except AttributeError:
            continue
        if role in CHROME_ROLES:
            return True
    return False


class HtmlSourceParser:
    """Extract stable, typed visible blocks from one HTML artifact."""

    def __init__(
        self,
        *,
        prefer_main: bool = True,
        drop_selectors: Iterable[str] = (),
    ) -> None:
        self.prefer_main = prefer_main
        self.drop_selectors = tuple(str(value) for value in drop_selectors)
        self.descriptor = ParserDescriptor(
            parser_id="html-visible-blocks",
            version=1,
            media_types=("text/html", "application/xhtml+xml"),
            config_fingerprint=_config_fingerprint(
                prefer_main=prefer_main,
                drop_selectors=self.drop_selectors,
            ),
        )

    def supports(self, artifact: SourceArtifact) -> ParserSupport:
        media_type = artifact.media_type.split(";", 1)[0].strip().casefold()
        suffix_match = artifact.locator.casefold().endswith((".html", ".htm", ".xhtml"))
        supported = media_type in self.descriptor.media_types or suffix_match
        return ParserSupport(
            supported=supported,
            reason="HTML media type or filename" if supported else "not HTML",
        )

    @staticmethod
    def _choose_root(soup, prefer_main: bool):
        if not prefer_main:
            return soup.body or soup, "body" if soup.body else "document"
        main = soup.find("main")
        if main is not None:
            return main, "main"
        role_main = soup.find(attrs={"role": "main"})
        if role_main is not None:
            return role_main, "[role=main]"
        articles = soup.find_all("article")
        if len(articles) == 1:
            return articles[0], "article"
        return soup.body or soup, "body" if soup.body else "document"

    def parse(self, artifact: SourceArtifact) -> ParsedSource:
        try:
            from bs4 import BeautifulSoup, NavigableString, Tag
        except ModuleNotFoundError as exc:  # pragma: no cover - packaging guard
            raise RuntimeError(
                "HTML construction requires beautifulsoup4; install the construct extra"
            ) from exc

        soup = BeautifulSoup(artifact.content, "html.parser")
        diagnostics: list[ParseDiagnostic] = []
        removed: list[dict] = []

        for tag_name in sorted(_INERT_TAGS):
            for tag in list(soup.find_all(tag_name)):
                text = _clean_text(tag)
                removed.append(
                    {
                        "selector": tag_name,
                        "locator": _dom_path(tag),
                        "visible_characters": len(text),
                        "reason": "inert_or_nontext_html",
                    }
                )
                tag.decompose()

        for selector in self.drop_selectors:
            for tag in list(soup.select(selector)):
                text = _clean_text(tag)
                removed.append(
                    {
                        "selector": selector,
                        "locator": _dom_path(tag),
                        "visible_characters": len(text),
                        "reason": "configured_drop_selector",
                    }
                )
                tag.decompose()

        full_visible = _clean_text(soup.body or soup)
        root, root_selector = self._choose_root(soup, self.prefer_main)
        root_visible = _clean_text(root)
        omitted_visible = max(0, len(full_visible) - len(root_visible))
        partial = bool(omitted_visible) or any(
            row["visible_characters"] and row["reason"] == "configured_drop_selector"
            for row in removed
        )
        if root_selector not in {"body", "document"}:
            diagnostics.append(
                ParseDiagnostic(
                    code="html_content_root_selected",
                    severity="warning" if omitted_visible else "info",
                    message=f"selected {root_selector} as the page content root",
                    locator=_dom_path(root),
                    details={"omitted_visible_characters_estimate": omitted_visible},
                )
            )
        if removed:
            diagnostics.append(
                ParseDiagnostic(
                    code="html_elements_removed",
                    severity="warning" if partial else "info",
                    message=f"removed {len(removed)} configured or non-content elements",
                    details={"elements": removed},
                )
            )

        base_tag = soup.find("base", href=True)
        base_uri = (
            urljoin(artifact.source_uri, str(base_tag.get("href")))
            if base_tag is not None
            else artifact.source_uri
        )
        title = _clean_text(soup.title) if soup.title is not None else ""
        canonical = soup.find("link", attrs={"rel": re.compile("canonical", re.I)})
        canonical_uri = ""
        if canonical is not None and canonical.get("href"):
            canonical_uri = urljoin(base_uri, str(canonical.get("href")))

        raw_blocks: list[dict] = []

        def emit(
            tag,
            text: str,
            kind: str,
            *,
            metadata: dict | None = None,
            locator: str = "",
            links: tuple[str, ...] | None = None,
        ) -> None:
            cleaned = text if kind == "code_block" else " ".join(text.split())
            if not cleaned.strip():
                return
            resolved_locator = locator or _dom_path(tag)
            raw_blocks.append(
                {
                    "tag": tag,
                    "locator": resolved_locator,
                    "text": cleaned,
                    "kind": kind,
                    "links": _links(tag, base_uri) if links is None else links,
                    "metadata": metadata or {},
                }
            )

        def walk(container) -> None:
            inline_nodes: list = []
            inline_run_number = 0

            def flush_inline() -> None:
                nonlocal inline_run_number
                if not inline_nodes:
                    return
                text, links = _inline_run(inline_nodes, base_uri)
                inline_nodes.clear()
                if not text:
                    return
                inline_run_number += 1
                emit(
                    container,
                    text,
                    "text",
                    locator=f"{_dom_path(container)}/text-run[{inline_run_number}]",
                    links=links,
                    metadata={"inline_run": inline_run_number},
                )

            for child in container.children:
                if isinstance(child, NavigableString):
                    inline_nodes.append(child)
                    continue
                if not isinstance(child, Tag) or child.name in _INERT_TAGS:
                    continue
                name = child.name.casefold()
                if name in _INLINE_TAGS:
                    inline_nodes.append(child)
                    continue
                flush_inline()
                if name in _ATOMIC_TAGS:
                    kind = (
                        "heading"
                        if name.startswith("h") and len(name) == 2 and name[1].isdigit()
                        else "code_block"
                        if name == "pre"
                        else "quote"
                        if name == "blockquote"
                        else name
                    )
                    emit(
                        child,
                        _clean_text(child, preserve=name == "pre"),
                        kind,
                        metadata={"heading_level": int(name[1])} if kind == "heading" else {},
                    )
                    continue
                if name == "li":
                    pieces = [_direct_text(child)]
                    pieces.extend(
                        _clean_text(nested)
                        for nested in child.find_all(_ATOMIC_TAGS, recursive=False)
                    )
                    text = _normalize_inline(" ".join(piece for piece in pieces if piece))
                    emit(child, text, "list_item")
                    for nested in child.find_all(["ul", "ol"], recursive=False):
                        walk(nested)
                    continue
                if name == "tr":
                    cells = [
                        _clean_text(cell)
                        for cell in child.find_all(["th", "td"], recursive=False)
                    ]
                    emit(
                        child,
                        " | ".join(cell for cell in cells if cell),
                        "table_row",
                        metadata={"cells": cells},
                    )
                    continue

                # Generic containers are walked in source order. Their direct
                # inline material is flushed around, rather than merged across,
                # nested block elements.
                walk(child)

            flush_inline()

        walk(root)

        heading_stack: list[str] = []
        outline: list[dict] = []
        records: list[dict] = []
        seen_locators: set[str] = set()
        for order, block in enumerate(raw_blocks, start=1):
            locator = block["locator"]
            if locator in seen_locators:
                continue
            seen_locators.add(locator)
            metadata = dict(block["metadata"])
            if block["kind"] == "heading":
                level = int(metadata["heading_level"])
                heading_stack = heading_stack[: level - 1]
                while len(heading_stack) < level - 1:
                    heading_stack.append("")
                heading_stack.append(block["text"])
                outline.append(
                    {
                        "heading": block["text"],
                        "level": level,
                        "path": [value for value in heading_stack if value],
                        "locator": locator,
                    }
                )
            stable = hashlib.sha256(locator.encode("utf-8")).hexdigest()[:12]
            records.append(
                {
                    "unit_id": f"{artifact.source_id}#html:{stable}",
                    "locator": locator,
                    "text": block["text"],
                    "kind": block["kind"],
                    "heading_path": tuple(value for value in heading_stack if value),
                    "links": block["links"],
                    "chrome": _is_chrome(block["tag"]),
                    # Running text, as opposed to a heading, a table row, a
                    # caption or a code block. Chrome is never prose.
                    "prose": (block["kind"] in _PROSE_KINDS
                              and not _is_chrome(block["tag"])),
                    "metadata": {
                        **metadata,
                        "parser_order": order,
                        "html_tag": block["tag"].name,
                        "source_parser": self.descriptor.parser_id,
                    },
                }
            )

        if not records:
            return ParsedSource(
                source_id=artifact.source_id,
                artifact_fingerprint=artifact.fingerprint(),
                artifact_content_sha256=artifact.content_sha256,
                parser=self.descriptor,
                status="ABSTAINED",
                fidelity="EXTRACTED",
                representation="",
                diagnostics=tuple(
                    [
                        *diagnostics,
                        ParseDiagnostic(
                            code="html_no_visible_blocks",
                            severity="warning",
                            message="HTML parser found no addressable visible blocks",
                        ),
                    ]
                ),
                metadata={"title": title, "content_root": root_selector},
            )

        representation, units = assemble_units(
            source_id=artifact.source_id,
            records=records,
        )
        return ParsedSource(
            source_id=artifact.source_id,
            artifact_fingerprint=artifact.fingerprint(),
            artifact_content_sha256=artifact.content_sha256,
            parser=self.descriptor,
            status="PARTIAL" if partial else "PARSED",
            fidelity="EXTRACTED",
            representation=representation,
            units=units,
            outline=tuple(outline),
            diagnostics=tuple(diagnostics),
            metadata={
                "title": title,
                "canonical_uri": canonical_uri,
                "base_uri": base_uri,
                "content_root": root_selector,
                "raw_content_sha256": artifact.content_sha256,
            },
        )
