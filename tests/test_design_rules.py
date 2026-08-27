"""The product's design rules, as a test rather than a document.

Every rule here was decided once, in conversation, and then had to be re-applied
by hand each time a surface was added — which is exactly the shape of a rule
that quietly stops being true. Drift does not arrive as a decision to abandon a
rule; it arrives as one new panel with a rounded corner, and then a second that
matches the first. A stylesheet cannot argue back. This can.

The rules are deliberately few, and each is here because it is *checkable from
the source text*. Anything needing judgement — whether a particular grey is the
right grey, whether a panel earns its place — is not a rule and is not here.

Scope is the product surfaces. ``frontend/src/explorations`` is where things are
tried before they are decided, so it is exempt on purpose: a lab that has to
follow the rules cannot be used to question them.

Why Python, for a stylesheet: this is the suite that runs. The frontend has no
test runner, and a rule enforced by a tool nobody invokes is a rule in prose
with extra steps.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PRODUCT_CSS = Path(__file__).resolve().parent.parent / "frontend" / "src" / "product"

#: Colour tokens. Defined once in `styles/graphDna.ts`; stylesheets only read them.
#:
#: The status trio joined this list when the nav started reporting the same
#: "waiting for you" the queue does. Before that, Review was the only surface
#: with status and the colours lived as hex inside its own stylesheet — which
#: was survivable while exactly one file painted them and stopped being so the
#: moment a second did. `GRAPH_DNA_STATUS` is now the source.
CHROME_TOKENS = (
    "--canvas",
    "--panel",
    "--ink",
    "--ink-muted",
    "--rule",
    "--attention",
    "--alarm",
    "--settled",
)

#: The one place colour is spent, and the whole of it — now empty.
#:
#: The monochrome rule is about the *map*: geometry and weight carry meaning
#: there, so colour would be decoration. A queue is not a map, and which
#: decisions are on fire is the first thing an operator needs; colour earns its
#: place by encoding a state that changes what you do.
#:
#: That argument is unchanged. What changed is where the values live. They were
#: pinned here, by value, as four hex literals in `ReviewWorkspace.css`, because
#: a stylesheet was the only thing painting them. They are now Radix tokens in
#: `GRAPH_DNA_STATUS`, which is what makes them theme-aware — hand-mixed hex has
#: no dark form, and the darkened variant for small text was correcting in the
#: wrong direction on half the product.
#:
#: So the exception is *discharged* rather than moved: no stylesheet spends
#: colour at all any more, and `test_declared_status_colours_are_all_still_used`
#: says an exception that stops being needed leaves this file. It stays as an
#: empty mapping, with this note, because the rule it guards still has to be
#: re-argued if someone reaches for hex again.
STATUS_COLOUR: dict[str, set[str]] = {}

#: The header is the layer that owns the top band, so it is the one thing that
#: legitimately pins itself to the top of the surface.
BAND_OWNER = "product-shell__top"

#: The two floating bands, and the one layer allowed to occupy each.
#:
#: Identity floats at the top on every surface; the instrument floats at the
#: foot. Everything else either runs underneath them (a fixed canvas, which is
#: what the map wants) or stops short of them (a scrolling document, which
#: cannot have its text crossed by a transparent bar). What is forbidden is a
#: third layer *pinning itself* to either edge, because that is how each surface
#: came to grow its own bar: Review had a second full-width band under the
#: header, Construct a stepper of its own.
INSTRUMENT_OWNER = "product-shell__instrument"

#: Surfaces whose content scrolls, and must therefore inset from both bands.
#:
#: Named rather than detected: "does this scroll" is not answerable from a
#: stylesheet, and a rule that guesses is a rule that will be wrong about the
#: one surface nobody checked. A new scrolling surface is added here by the
#: person who knows it scrolls.
#: Keyed to the scroll containers themselves, not the surface that holds them.
#: The first version named the outer surface, which passed while the panels were
#: visibly short — insetting the whole surface moves the panel's background down
#: with the text, and the seam that leaves across the top of the page is what the
#: rule was supposed to be about.
SCROLLING_SURFACES = {
    "ReviewWorkspace.css": {".review-queue", ".review-inspector"},
}


class Rule:
    """One CSS rule: its selector and its own declarations, nothing borrowed."""

    def __init__(self, selector: str, body: str) -> None:
        self.selector = selector
        self.body = body

    def value(self, prop: str) -> str | None:
        match = re.search(rf"(?:^|;)\s*{re.escape(prop)}\s*:\s*([^;]+)", self.body)
        return match.group(1).strip() if match else None

    def has(self, prop: str) -> bool:
        return self.value(prop) is not None


def _uncommented(text: str) -> str:
    """Strip comments, so prose *about* a rule never trips it."""
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _rules(text: str) -> list[Rule]:
    """Parse top-level and nested rules, tracking braces properly.

    Splitting on ``}`` was the first attempt and it was wrong: a block then
    carried the tail of its neighbour, and the header was reported as pinning a
    `bottom: 0` that belonged to the rule after it.
    """
    body = _uncommented(text)
    rules: list[Rule] = []
    i = 0
    while True:
        brace = body.find("{", i)
        if brace < 0:
            break
        selector = body[i:brace].strip().splitlines()
        selector = selector[-1].strip() if selector else ""
        depth, j = 1, brace + 1
        while j < len(body) and depth:
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
            j += 1
        inner = body[brace + 1 : j - 1]
        if "{" in inner:  # an at-rule; recurse into it
            rules.extend(_rules(inner))
        else:
            rules.append(Rule(selector, inner))
        i = j
    return rules


#: The smallest a control may be when the thing pointing at it is a finger.
#:
#: 44 is the published floor, and the number to *ask for* is larger than the
#: number you want: a border-box cell with a 1px rule each side lands two pixels
#: short of whatever is set on it, which is how the first pass at this shipped a
#: 43px "44px" target. The rule below therefore checks what is declared, and the
#: declarations that clear it by a pixel or two are deliberate.
TOUCH_FLOOR_PX = 44

#: Properties that decide how big a target is. `max-*` is absent on purpose —
#: a ceiling is not a size, and a coarse block is allowed to cap a list's
#: height while the rows inside it grow.
TARGET_SIZE_PROPS = ("height", "min-height", "width", "min-width")


def _coarse_rules(text: str) -> list[Rule]:
    """Every rule written inside a `pointer: coarse` block."""
    body = _uncommented(text)
    found: list[Rule] = []
    for match in re.finditer(r"@media[^{]*pointer\s*:\s*coarse[^{]*\{", body):
        depth, j = 1, match.end()
        while j < len(body) and depth:
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
            j += 1
        found.extend(_rules(body[match.end() : j - 1]))
    return found


def _px(value: str) -> float | None:
    """The pixel size a declaration asks for, if it asks in pixels at all."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)px\s*", value)
    return float(match.group(1)) if match else None


def _sheets() -> list[tuple[str, str]]:
    return sorted(
        (path.name, path.read_text(encoding="utf-8"))
        for path in PRODUCT_CSS.glob("*.css")
    )


def _values(text: str, prop: str) -> list[str]:
    return [
        m.group(1).strip()
        for m in re.finditer(rf"{re.escape(prop)}\s*:\s*([^;}}]+)", _uncommented(text))
    ]


@pytest.fixture(scope="module")
def sheets() -> list[tuple[str, str]]:
    found = _sheets()
    # Guards every rule below: a path that stopped resolving would otherwise
    # turn the whole file into a vacuous pass.
    assert len(found) > 5, f"expected the product stylesheets at {PRODUCT_CSS}"
    return found


def test_corners_are_square_or_a_full_circle(sheets):
    """Square corners.

    The one exception is a full circle, which is not a rounded rectangle at all
    — it is the node's own shape, quoted deliberately (the reader's chain marks
    each step with one, and Review marks a status the same way).
    """
    offenders = [
        f"{name}: border-radius: {value}"
        for name, text in sheets
        for value in _values(text, "border-radius")
        if value not in ("0", "50%")
    ]
    assert offenders == []


def test_surfaces_are_separated_by_rules_not_shadows(sheets):
    """No implied light source.

    A floating surface is separated from what is under it by a rule — a fact
    about the surface — rather than by a shadow it would cast if this were a
    room, or by a frosted pane. ``inset`` is allowed: an inset edge is a border
    drawn on one side, not a cast shadow.

    Ask's fog is the one frost: dim plus blur, on `.ask-spotlight` only. A
    second surface may not claim it by putting `backdrop-filter` on itself.
    """
    offenders: list[str] = []
    for name, text in sheets:
        offenders += [
            f"{name}: box-shadow: {value}"
            for value in _values(text, "box-shadow")
            if value != "none" and not value.startswith("inset")
        ]
        for rule in _rules(text):
            for prop in ("backdrop-filter", "-webkit-backdrop-filter"):
                value = rule.value(prop)
                if not value or value == "none":
                    continue
                if ".ask-spotlight" in rule.selector:
                    continue
                offenders.append(f"{name}: {rule.selector} {prop}: {value}")
    assert offenders == []


def test_colour_is_spent_only_on_status_and_only_there(sheets):
    """Monochrome, per executable-design-constraints §1.5 / §2.1.

    On the map, geometry and weight carry meaning, so colour would be
    decoration. The bounded exception is Review's status marks — see
    ``STATUS_COLOUR``. The check runs both ways: no colour outside that set, and
    the set itself does not grow without someone editing this file.
    """
    offenders: list[str] = []
    for name, text in sheets:
        allowed = STATUS_COLOUR.get(name, set())
        for match in re.finditer(r"#([0-9a-fA-F]{3,8})\b", _uncommented(text)):
            raw = match.group(1)
            full = "".join(c * 2 for c in raw) if len(raw) == 3 else raw[:6]
            channels = [int(full[i:i + 2], 16) for i in (0, 2, 4)]
            # Greyscale means the channels agree. A little slack for the
            # mauve-cast dark greys, which are still neutral to the eye.
            if max(channels) - min(channels) <= 8:
                continue
            if f"#{raw.lower()}" in allowed:
                continue
            offenders.append(f"{name}: #{raw}")
    assert offenders == []


def test_declared_status_colours_are_all_still_used(sheets):
    """The exception shrinks when it stops being needed.

    An allowlist that only ever grows is not a boundary. If a status colour
    leaves the product, it leaves this file too.
    """
    text_by_name = dict(sheets)
    unused = [
        f"{name}: {colour}"
        for name, colours in STATUS_COLOUR.items()
        for colour in colours
        if colour not in text_by_name.get(name, "").lower()
    ]
    assert unused == []


def test_chrome_tokens_have_exactly_one_source(sheets):
    """Colour tokens are defined once, in `styles/graphDna.ts`.

    This is the rule that had already been broken. `ProductShell.css` declared
    `--ink-muted` and `--rule` as hex while the DNA workbench declared them as
    Radix tokens, and the two disagreed — so every chrome knob on that page was
    tuning a value the product did not use. Stylesheets may only *read* them.
    """
    offenders: list[str] = []
    for name, text in sheets:
        for rule in _rules(text):
            for token in CHROME_TOKENS:
                if rule.has(token):
                    offenders.append(f"{name}: {rule.selector} defines {token}")
    assert offenders == []


def test_docked_panels_hang_below_the_header_band(sheets):
    """Every docked panel takes its top edge from `--dock-top`, never a literal.

    Rewritten, because the rule outlived the sentence that described it. It used
    to say "docked panels start *below* the header band", and that was true when
    `--dock-top` was the height of the bar. The band is deliberately zero now —
    panels run to the top edge and the header floats over them — so the old
    docstring described a layout the product had stopped having, on a test that
    was green the whole time. `chrome-constraints.md` §0 names this failure mode:
    a rule can pass and stop being true, and then it is documentation that lies.

    What it still guarantees, and why that is worth a test: the header, the
    library, Ask and the node reader all want the same corner, and every pair of
    them collided before there was one answer. Stacking order cannot settle it —
    whichever layer wins, the other is unreadable. One token decides where the
    dock begins, so that relationship is changed in one place and every panel
    moves together. A panel that pins `top: 0` itself has opted out of the next
    change silently, which is §2.13 (two sources for one value) in a different
    costume.

    A docked panel is one pinned to a side edge for the full height, carrying
    its own surface. That last part is what separates a panel from the drag
    strip inside one, which is also full height and also absolute.
    """
    offenders: list[str] = []
    for name, text in sheets:
        for rule in _rules(text):
            if BAND_OWNER in rule.selector:
                continue
            if rule.value("position") != "absolute":
                continue
            if not rule.has("bottom") or not rule.has("background"):
                continue
            side = rule.value("left") or rule.value("right")
            if side is None or side.strip() != "0":
                continue
            top = rule.value("top")
            if top is None or "--dock-top" in top:
                continue
            offenders.append(f"{name}: {rule.selector} pins top: {top}")
    assert offenders == []


def test_only_the_band_owners_pin_themselves_to_an_edge(sheets):
    """A surface may not grow its own bar.

    The docked-panel rule above covers full-height side panels. This is the
    other half: a layer pinned across the *top* or the *bottom* of the window,
    which is what a bar is. Exactly two are allowed — identity at the top,
    instrument at the foot — and everything a surface wants to put in either
    goes through `Instrument`, into the band that already exists.

    This is the rule the product broke three separate ways before it existed:
    Review grew a second full-width band directly under the header, Construct
    put its stage controls in the reading column, and Graph floated its own
    cluster below the shell's. Three answers to one question, and no way to see
    that from any one file.
    """
    owners = (BAND_OWNER, INSTRUMENT_OWNER)
    offenders: list[str] = []
    for name, text in sheets:
        for rule in _rules(text):
            if any(owner in rule.selector for owner in owners):
                continue
            if rule.value("position") not in {"absolute", "fixed"}:
                continue
            spans = (rule.value("left") or "").strip() == "0" and \
                    (rule.value("right") or "").strip() == "0"
            if not spans:
                continue
            for edge in ("top", "bottom"):
                pinned = (rule.value(edge) or "").strip()
                if pinned == "0" and rule.has("background"):
                    offenders.append(f"{name}: {rule.selector} pins {edge}: 0 across the window")
    assert offenders == []


def test_a_surface_does_not_declare_its_own_palette(sheets):
    """Colour comes from the shell's tokens, never a surface's private set.

    `CHROME_TOKENS` already stops a stylesheet *redefining* the shared names.
    This catches the other shape of the same mistake: a surface inventing a
    parallel palette under its own prefix and painting from that instead — so
    the shell's theme switch, and the focus state that rebinds those tokens,
    both silently stop reaching it.

    The construction wizard is the live example, with `--cw-bg`, `--cw-ink`,
    `--cw-rule` and two status colours of its own. It sits in `explorations/`
    and is exempt on purpose; the exemption ends the moment it is ported into
    `product/`, which is exactly when this should start failing.
    """
    offenders: list[str] = []
    for name, text in sheets:
        for rule in _rules(text):
            for match in re.finditer(r"(--[a-z0-9-]+)\s*:", rule.body):
                token = match.group(1)
                if token in CHROME_TOKENS:
                    continue  # its own rule reports this, with a better message
                if re.search(r"#[0-9a-fA-F]{3,8}\b", rule.value(token) or ""):
                    offenders.append(f"{name}: {rule.selector} defines {token} as a literal colour")
    assert offenders == []


def test_the_browser_paints_no_control_the_product_did_not_choose():
    """Form controls carry a user-agent appearance, and the product's rules
    cannot see it.

    Every other rule in this file reads declarations. A UA default is the
    absence of one, so a blue checkbox and a grey button slab sit in a
    monochrome product and no amount of scanning stylesheets will find them.
    Three shipped before this: the composer's checkboxes in Chrome's accent
    blue, and every secondary decision button in Review as ButtonFace grey.

    The reset is the only place this can be fixed once, so the reset is what is
    pinned — for `input` as well as `button`.

    This test used to require the opposite for inputs: that whoever draws a
    checkbox declares its own `accent-color`, on the stated grounds that "the
    reset cannot supply it". That was simply untrue — `accent-color` inherits
    and applies perfectly well from an element selector — and the belief cost a
    fourth blue checkbox. The per-component form could only check selectors
    that *mention* a checkbox, so `.settings__check input` was invisible to it:
    the class was never given a rule, and a scan for wrong declarations cannot
    find a missing one. That is the same reason this whole test exists, applied
    one level up.
    """
    base = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "src" / "styles" / "base.css"
    ).read_text()
    rule = next(
        (r for r in _rules(base) if r.selector.strip() == "button"), None
    )
    assert rule is not None, "base.css no longer resets button"
    for prop in ("background", "color"):
        assert rule.has(prop), (
            f"base.css button reset does not set {prop} — the user agent will"
        )

    # A tick, a radio dot and a range track are all painted from `accent-color`.
    # One element selector covers every control the product will ever add.
    inputs = next(
        (r for r in _rules(base) if r.selector.strip() == "input"), None
    )
    assert inputs is not None, "base.css no longer resets input"
    assert inputs.has("accent-color"), (
        "base.css input reset does not set accent-color — every checkbox, "
        "radio and range in the product reverts to the user agent's blue"
    )

    # And it stays the only source. A surface restating it is how the four
    # copies drifted in the first place, and the next one to be forgotten is
    # the one that ships.
    for name, text in _sheets():
        for r in _rules(text):
            assert not r.has("accent-color"), (
                f"{name}: {r.selector} redeclares accent-color — it is set "
                f"once, on `input`, in base.css"
            )


def test_a_touch_target_is_never_sized_below_the_floor(sheets):
    """A `pointer: coarse` block exists to make a target reachable by a thumb.

    So a size *under* 44px inside one is either a mistake or a decision that
    the finger does not matter here — and both are worth stopping, because the
    block's whole reason for existing is the number it just went under.

    Two things this deliberately does not check. It does not require that a
    control be 44px: most are sized by their content and their padding, and a
    rule demanding a declared height on every button would be a rule about how
    CSS is written rather than about how big anything is. And it does not look
    outside these blocks at all — small is correct for a mouse, which is the
    whole point of scoping by pointer rather than by width.

    Pseudo-elements are exempt, and for a reason that has now cut both ways.
    The pattern this product settled on for a hairline grip is a 44px reach
    around a 1px mark, and a pseudo-element is where *both* halves of that end
    up: `.ov__resize` keeps its mark in `::after` while the element grows, and
    `.panel-divider` does the opposite — the element keeps its 9px of layout
    and the reach is an overflowing `::before`.

    That second form exists because the first was wrong there. The divider sits
    in a grid track both workspaces declare as a literal `9px`, so widening the
    element overflowed the track to one side and laid 35px of resize target
    across the pane beside it. This rule passed it, and would pass it again: a
    declared `width: 44px` is exactly what it asks for. What it cannot see is
    whether the 44px landed where a finger is aiming, which is why the inventory
    that found it was a measurement in a browser and not a scan of this text.
    """
    offenders = []
    seen = 0
    for name, text in sheets:
        for rule in _coarse_rules(text):
            seen += 1
            if "::" in rule.selector:
                continue
            for prop in TARGET_SIZE_PROPS:
                value = rule.value(prop)
                size = _px(value) if value else None
                if size is not None and 0 < size < TOUCH_FLOOR_PX:
                    offenders.append(
                        f"{name}: {rule.selector} sets {prop}: {value} under "
                        f"`pointer: coarse` — below the {TOUCH_FLOOR_PX}px floor"
                    )
    # A parser that stopped finding coarse blocks would report a clean product
    # forever, which is the failure this whole file was written against.
    assert seen > 10, "no `pointer: coarse` rules found — the parser has drifted"
    assert offenders == []


def test_the_browser_decorates_no_touch_the_product_did_not_choose():
    """The UA-default bug class, in the register only a finger can see.

    Same shape as `test_the_browser_paints_no_control_the_product_did_not_choose`
    and the same reason: both symptoms are the *absence* of a declaration, so
    no scan of the stylesheets for a wrong value will ever find them. A tap
    flashes a translucent slab the product never chose, and a double-tap zooms
    a page that is a fixed frame — which also makes every single tap wait to
    find out whether a second one is coming.

    Pinned on the document, once, for the same reason `accent-color` is: a rule
    that has to be remembered per control is the bug wearing a different hat.
    The map is the stated exception and states it itself, in
    `ProductGraphCanvas.css`, by claiming its own gestures with
    `touch-action: none`.
    """
    base = (
        Path(__file__).resolve().parent.parent
        / "frontend" / "src" / "styles" / "base.css"
    ).read_text()
    root = next((r for r in _rules(base) if r.selector.strip() == "html"), None)
    assert root is not None, "base.css no longer has an `html` rule"
    assert root.value("-webkit-tap-highlight-color") == "transparent", (
        "base.css does not clear the tap highlight — every tap in the product "
        "flashes a grey slab the design never chose"
    )
    assert root.value("touch-action") == "manipulation", (
        "base.css does not set touch-action: manipulation — double-tap zoom "
        "returns, and with it the delay it imposes on every ordinary tap"
    )

    # And it stays the only source, for the reason the accent-color copies drifted.
    for name, text in _sheets():
        for r in _rules(text):
            assert not r.has("-webkit-tap-highlight-color"), (
                f"{name}: {r.selector} redeclares the tap highlight — it is "
                f"cleared once, on `html`, in base.css"
            )


def test_host_down_is_identity_not_a_surface_error():
    """Host-down occupies one slot: identity's "Unavailable".

    The sentence is authored in `client.ts`. A surface that copies it, or that
    prints a resource error without going through `visibleError` /
    `surfaceError`, restates the same fact. The helpers in `resource.ts` are
    the standard; this pins that they still exist and that product files do
    not hardcode the host sentence beside them.
    """
    root = Path(__file__).resolve().parent.parent
    resource = (root / "frontend" / "src" / "api" / "resource.ts").read_text(
        encoding="utf-8",
    )
    assert "export function isHostUnreachable" in resource
    assert "export function surfaceError" in resource
    assert "export function visibleError" in resource
    sentence = "Cannot reach the operator host"
    product = root / "frontend" / "src" / "product"
    offenders = []
    for path in list(product.glob("*.ts")) + list(product.glob("*.tsx")) + list(
        product.glob("*.css")
    ):
        text = path.read_text(encoding="utf-8")
        if sentence in text:
            offenders.append(path.name)
    assert offenders == [], (
        "host-down sentence copied into a surface — identity already says it: "
        + ", ".join(offenders)
    )


def test_settings_does_not_author_the_look():
    """Settings operates the host and this screen. It does not pick a palette.

    Light/dark is the identity bar. The Radix family, type, motion and focus
    palette live in `styles/graphDna.ts` and are tried in the DNA workbench.
    A picker here would let two people on one host get two products, which is
    chrome-constraints §3.11.
    """
    root = Path(__file__).resolve().parent.parent
    settings = (
        root / "frontend" / "src" / "product" / "SettingsPanel.tsx"
    ).read_text(encoding="utf-8")
    forbidden = (
        'from "../styles/graphDna"',
        'from "../explorations/dnaParamsStore"',
        "@radix-ui/colors",
        "graphDnaParams",
        "GRAPH_DNA_THEME",
        "slateDark",
        "mauveDark",
        "grayDark",
    )
    offenders = [needle for needle in forbidden if needle in settings]
    assert offenders == [], (
        "Settings is authoring the look rather than operating the host: "
        + ", ".join(offenders)
    )


def test_scrolling_surfaces_stop_short_of_both_bands(sheets):
    """A document does not scroll under the chrome; the map does.

    The map runs edge to edge on purpose — a graph reads fine beneath a word,
    and it is the surface that should use every pixel. A scrolling column
    cannot: mid-scroll its text passes through both bands, and at rest those
    bands are lettering with no box behind them, so text crossed text and
    neither could be read.

    Two fixes were wrong before this one, in opposite directions. Padding the
    *contents* only holds at the two ends of a scroll. Padding the whole
    *surface* fixed the text and broke the panel: the queue's background then
    began at the bar's lower edge rather than the window's, so every page had a
    seam across the top and the panel looked cut short.

    What holds is a transparent border on the scroll container. `overflow` clips
    content at the padding box, so nothing scrolls into the band; `background-
    clip` defaults to the border box, so the panel's surface still paints the
    full height. Either declaration satisfies this rule — what is checked is
    that the container names both bands, not which property it uses.
    """
    # First occurrence wins, so the self-check below can shadow a real sheet
    # with a synthetic broken one. `dict(sheets)` would let the real file
    # overwrite the violation and the rule would report itself clean.
    text_by_name: dict[str, str] = {}
    for entry_name, entry_text in sheets:
        text_by_name.setdefault(entry_name, entry_text)
    offenders: list[str] = []
    for name, selectors in SCROLLING_SURFACES.items():
        text = text_by_name.get(name)
        if text is None:
            offenders.append(f"{name}: named as a scrolling surface but has no stylesheet")
            continue
        for selector in sorted(selectors):
            rule = next(
                (
                    r
                    for r in _rules(text)
                    if selector in [part.strip() for part in r.selector.split(",")]
                    and (r.has("overflow") or r.has("overflow-y"))
                ),
                None,
            )
            if rule is None:
                offenders.append(f"{name}: no scrolling rule for {selector}")
                continue
            for edge, band in (("top", "--shell-band"),
                               ("bottom", "--instrument-band")):
                inset = (rule.value(f"padding-{edge}") or "") + (
                    rule.value(f"border-{edge}") or ""
                )
                if band not in inset:
                    offenders.append(
                        f"{name}: {selector} does not clear the {edge} band ({band})"
                    )
    assert offenders == []


# --------------------------------------------------------------------------
# The rules, checked against themselves.
#
# A lint that cannot fail is worse than no lint: it reports a clean surface
# forever and nobody looks again. Each rule above is fed the violation it
# exists to catch, and has to reject it.


VIOLATIONS = [
    ("corners", test_corners_are_square_or_a_full_circle,
     ".panel { border-radius: 6px; }"),
    ("shadows", test_surfaces_are_separated_by_rules_not_shadows,
     ".panel { box-shadow: 0 8px 24px rgb(0 0 0 / 18%); }"),
    ("blur", test_surfaces_are_separated_by_rules_not_shadows,
     ".panel { backdrop-filter: blur(7px); }"),
    ("colour", test_colour_is_spent_only_on_status_and_only_there,
     ".panel { color: #2f6fed; }"),
    ("token source", test_chrome_tokens_have_exactly_one_source,
     ".panel { --ink: #202020; }"),
    ("dock", test_docked_panels_hang_below_the_header_band,
     ".panel { position: absolute; top: 0; left: 0; bottom: 0;"
     " background: var(--panel); }"),
    ("own bar", test_only_the_band_owners_pin_themselves_to_an_edge,
     ".surface__toolbar { position: absolute; top: 0; left: 0; right: 0;"
     " background: var(--panel); }"),
    ("own palette", test_a_surface_does_not_declare_its_own_palette,
     ".surface { --surface-ink: #202020; }"),
    ("scroll inset", test_scrolling_surfaces_stop_short_of_both_bands,
     ".review-queue, .review-inspector { overflow: auto;"
     " padding-top: 1rem; padding-bottom: 1rem; }"),
    # The 43px "44px" target, which is how this one actually goes wrong.
    ("touch floor", test_a_touch_target_is_never_sized_below_the_floor,
     "@media (pointer: coarse) { .toolbar__cell { min-height: 43px; } }"),
]


@pytest.mark.parametrize("label,rule,css", VIOLATIONS, ids=[v[0] for v in VIOLATIONS])
def test_each_rule_rejects_its_own_violation(label, rule, css):
    # The scroll rule looks up a named sheet rather than scanning all of them,
    # so its violation has to arrive under that name; the rule reads
    # first-occurrence-wins so this shadows the real file.
    sheet_name = "ReviewWorkspace.css" if label == "scroll inset" else "Synthetic.css"
    synthetic = [(sheet_name, css)] + _sheets()
    with pytest.raises(AssertionError):
        rule(synthetic)


def test_the_status_exception_does_not_cover_a_new_file():
    """Colour is allowed in Review, not wherever someone puts a status mark."""
    borrowed = [("SomewhereElse.css", ".mark { background: #bd563c; }")]
    with pytest.raises(AssertionError):
        test_colour_is_spent_only_on_status_and_only_there(borrowed + _sheets())
