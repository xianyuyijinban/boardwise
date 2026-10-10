"""147: the three defect classes 岳 caught by eye, and the boxes that see them.

Everything here is a **handwritten literal** plan (the 053b idiom): the contract
being pinned is "given these profiles and this plan, what does the checker see",
and a compiler fixture would drag the compiler's own placement into the test.

The three defects, all found on `test/P1`'s landed 146 page with every gate green
(`outputs/147/FINDINGS.md`):

* a wire *through* a two-pin part's body — invisible until 147 because every
  two-pin profile stated its body as the **line** between its pins, and no wire can
  cross a line (sec.1);
* a wire running **along** a pin's own drawn lead, and a flag's glyph/name where a
  wire runs (sec.2, sec.3);
* a conductor printed **through** a text row — the class the page lint has asked
  since 111 and the compiler's gate never did (sec.2).

Plus the two host behaviours 147 had to measure before any of it could be modelled:
where the host prints a **wire's name**, and where it prints a **rail flag's name**
(sec.2), and that it does **not** turn a part's own text rows with the part's pose
(sec.4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core import textmetrics
from boardwise.core.circuitspec import CircuitSpec, SpecNet, SpecPart
from boardwise.core.layoutplan import (
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import (
    PIN_LINE_OVERLAP,
    SymbolPin,
    SymbolProfile,
    flag_glyph_box,
    pose_box,
)
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability
from boardwise.engines.readability import (
    KIND_TEXT_ON_WIRE,
    KIND_WIRE_ON_PIN_LINE,
    KIND_WIRE_THROUGH_BODY,
    check,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = (0.0, 0.0, 1000.0, 800.0)
HASH = "a" * 64

RES = "R-TEST"
FLAG = "PWR-HVDC"


def _resistor() -> SymbolProfile:
    """A two-pin part whose drawn extent is a **rectangle**, not the pin axis.

    The shape 147 measured on the real library: the host draws an 0603 resistor as
    a 20 x 8 box, and the profile used to state `(-10, 0, 10, 0)` — the interval
    between the two pin inner ends, a line no wire can cross.
    """
    return SymbolProfile(
        symbol_ref=RES,
        title="Resistor, horizontal",
        body=(-10.0, -5.0, 10.0, 5.0),
        pins=[
            SymbolPin(number="1", tip=(-30.0, 0.0), name="1", direction="left",
                      length=20.0),
            SymbolPin(number="2", tip=(30.0, 0.0), name="2", direction="right",
                      length=20.0),
        ],
    )


def _rail_flag() -> SymbolProfile:
    """A pin-less flag: its origin is the connection, its body hangs away from it."""
    return SymbolProfile(
        symbol_ref=FLAG,
        title="Rail flag",
        body=(-5.0, 0.0, 5.0, 10.0),
        pins=[],
    )


def _plan(*, parts=None, segments=None, labels=(), power_symbols=(),
          texts=()) -> LayoutPlan:
    return LayoutPlan(
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=parts if parts is not None else [],
        segments=segments if segments is not None else [],
        junctions=[],
        labels=list(labels),
        power_symbols=list(power_symbols),
        texts=list(texts),
    )


def _circuit(*nets, parts=None) -> CircuitSpec:
    return CircuitSpec(
        parts=parts or [SpecPart(id="P1", symbol_ref=RES, value="10k")],
        nets=list(nets),
        nc=[],
    )


def _presentation() -> PresentationSpec:
    return PresentationSpec(grammar_ref="147", user_locks=[])


def _kinds(plan, circuit, profiles=None) -> list[str]:
    return [kind for kind, _objects in _findings(plan, circuit, profiles)]


def _findings(plan, circuit, profiles=None) -> list[tuple[str, tuple[str, ...]]]:
    """``(kind, objects)`` for every hard violation — objects included so a test can
    say *which* box it means (a flag's glyph and a flag's name row are two boxes and
    both can be crossed by one wire)."""
    default = [_resistor(), _rail_flag()]
    book = {profile.symbol_ref: profile for profile in (profiles or default)}
    result = check(plan, circuit, _presentation(), book, page_box=PAGE)
    return [(item.kind, item.objects) for item in result.hard_violations]


# ------------------------------------------------- 1. the drawn extent, not a line


def test_the_pose_box_fold_is_one_function_and_answers_for_every_consumer():
    """147: four implementations of "this box through this pose" became one.

    `readability._body_in_page`, `drawcompiler._body_box`, `drawapply`'s stub pass
    and `pagecompiler._body_box` each folded the four corners and re-bounded them;
    this pins the shared fold and the two engines' agreement about it.
    """
    box = (-10.0, -5.0, 10.0, 5.0)
    assert pose_box(box, rotation=0.0, mirror=False, ox=400.0, oy=400.0) == (
        390.0, 395.0, 410.0, 405.0,
    )
    # A quarter turn is no longer the same rectangle: it is re-bounded.
    assert pose_box(box, rotation=90.0, mirror=False, ox=400.0, oy=400.0) == (
        395.0, 390.0, 405.0, 410.0,
    )
    # Nobody measured is not a zero-area box.
    assert pose_box(None, rotation=0.0, mirror=False, ox=0.0, oy=0.0) is None

    part = LayoutPart(
        part_id="P1", symbol_ref=RES, symbol_hash=HASH,
        x=400.0, y=400.0, rotation=90.0, mirror=False, reference="P1",
    )
    placed = readability._placed_parts(
        _plan(parts=[part]), {RES: _resistor()},
    )
    assert placed[0].body == (395.0, 390.0, 405.0, 410.0)
    assert dc._body_box(_resistor(), dc.SymbolPose(90, False), (400.0, 400.0)) == (
        395.0, 390.0, 405.0, 410.0,
    )


def test_a_wire_across_a_two_pin_part_is_a_wire_through_body():
    """The defect that was invisible while the body was a line (147 sec.1)."""
    part = LayoutPart(
        part_id="P1", symbol_ref=RES, symbol_hash=HASH,
        x=400.0, y=400.0, rotation=0.0, mirror=False, reference="P1",
    )
    circuit = _circuit(SpecNet(id="A", cls="signal", members=["P1.1", "P1.2"]))
    crossed = _plan(
        parts=[part],
        segments=[LayoutSegment(net="A", points=[(400.0, 480.0), (400.0, 320.0)])],
    )
    assert KIND_WIRE_THROUGH_BODY in _kinds(crossed, circuit)
    # One unit clear of the drawn extent on each side, and the same run reaches
    # both pins: no `wire-through-body` finding.
    kinds = _kinds(
        _plan(
            parts=[part],
            segments=[
                LayoutSegment(net="A", points=[(415.0, 480.0), (415.0, 320.0)]),
                LayoutSegment(net="A", points=[(415.0, 400.0), (430.0, 400.0)]),
                LayoutSegment(net="A", points=[(430.0, 400.0), (415.0, 400.0)]),
            ],
        ),
        circuit,
    )
    assert KIND_WIRE_THROUGH_BODY not in kinds


# --------------------------------------------- 2. a wire along a pin's own lead


def test_a_wire_running_along_a_pin_lead_is_reported_and_arriving_from_outside_is_not():
    """Constraint 4b (147): the lead is a line, and a wire lying on it hides it."""
    part = LayoutPart(
        part_id="P1", symbol_ref=RES, symbol_hash=HASH,
        x=400.0, y=400.0, rotation=0.0, mirror=False, reference="P1",
    )
    circuit = _circuit(
        SpecNet(id="A", cls="signal", members=["P1.1"]),
        SpecNet(id="B", cls="signal", members=["P1.2"]),
    )
    # P1.1's tip is at (370, 400) and its lead runs *inward* to (390, 400). A wire
    # from the tip inward lies on the lead.
    along = _plan(
        parts=[part],
        segments=[LayoutSegment(net="A", points=[(370.0, 400.0), (385.0, 400.0)])],
    )
    kinds = _kinds(along, circuit)
    assert KIND_WIRE_ON_PIN_LINE in kinds

    # A wire reaching the same tip from **outside** the symbol overlaps nothing:
    # it runs along the lead's own axis, on the far side of the tip.
    outside = _plan(
        parts=[part],
        segments=[LayoutSegment(net="A", points=[(350.0, 400.0), (370.0, 400.0)])],
    )
    assert KIND_WIRE_ON_PIN_LINE not in _kinds(outside, circuit)


def test_the_pin_lead_the_router_reserves_and_the_gate_refuses_agree():
    """One length, two consumers: the landing a tip keeps is what the gate tolerates."""
    assert PIN_LINE_OVERLAP == 1.0
    profile = _resistor()
    walls = dc._pin_walls(profile, dc.SymbolPose(0, False), (400.0, 400.0))
    # P1.1's tip is (370, 400) and its lead runs inward to (390, 400). The wall
    # starts one unit in (the landing the gate tolerates) and ends exactly at the
    # lead's inner end, thickened across the lead only.
    assert walls[0] == (371.0, 399.5, 390.0, 400.5)
    assert walls[1] == (410.0, 399.5, 429.0, 400.5)


# ----------------------------------------------- 3. text rows and conductors


def test_a_conductor_printed_through_a_text_row_is_reported_at_the_lint_threshold():
    """Constraint 5b (147): the compiler's gate asks what the page lint asks."""
    part = LayoutPart(
        part_id="P1", symbol_ref=RES, symbol_hash=HASH,
        x=400.0, y=700.0, rotation=0.0, mirror=False, reference="P1",
    )
    circuit = _circuit(
        SpecNet(id="A", cls="signal", members=["P1.1", "P1.2"]),
    )
    label = LayoutLabel(
        net="NOTE", text="NOTE", x=400.0, y=500.0, bbox=(400.0, 490.0, 470.0, 520.0),
    )
    # A conductor straight through the row: 30 units of chord.
    through = _plan(
        parts=[part],
        segments=[
            LayoutSegment(net="A", points=[(430.0, 470.0), (430.0, 540.0)]),
        ],
        labels=[label],
    )
    kinds = _kinds(through, circuit)
    assert KIND_TEXT_ON_WIRE in kinds

    # The same conductor moved clear of the row by a unit: no finding.
    clear = _plan(
        parts=[part],
        segments=[
            LayoutSegment(net="B", points=[(480.0, 470.0), (480.0, 540.0)]),
        ],
        labels=[label],
    )
    assert KIND_TEXT_ON_WIRE not in _kinds(clear, circuit)


# ------------------------------------------------- 4. the rows the host prints


def test_the_host_prints_a_rail_flags_name_in_the_band_past_its_glyph():
    """Measured on the landed page's two rail flags (`147/FINDINGS.md` sec.2).

    Nothing else in the repo may model this: the boxes are the numbers the render
    shows, to the unit.
    """
    hvdc = textmetrics.flag_name_box(
        (154.5, 690.0, 165.5, 700.5), (160.0, 690.0), "HVDC", axis_up=True,
    )
    assert hvdc == pytest.approx((145.835, 700.5, 174.165, 710.5))
    sec = textmetrics.flag_name_box(
        (274.5, 729.5, 285.5, 740.0), (280.0, 740.0), "SEC_12V", axis_up=False,
    )
    assert sec == pytest.approx((258.045, 719.5, 301.955, 729.5))


def test_a_ground_flag_prints_no_name_and_a_rail_flag_does():
    """The model's one branch: only the rail family prints its net (measured)."""
    ground = SymbolProfile(
        symbol_ref="PWR-GND", title="Ground flag", body=(-10.5, 0.0, 10.5, 19.5),
        pins=[],
    )
    plan = _plan(
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-GND", symbol_hash=HASH, net="PGND",
                              x=200.0, y=400.0, rotation=180.0),
            LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH, net="HVDC",
                              x=600.0, y=400.0, rotation=0.0),
        ],
    )
    boxes = readability._text_boxes(plan, {"PWR-GND": ground, FLAG: _rail_flag()})
    names = [name for name, _box, _owner, _text in boxes]
    assert "powerSymbols[0] name" not in names
    assert "powerSymbols[1] name" in names


def test_the_host_draws_a_wires_name_and_the_checker_sees_where():
    """`wire_name_box` as a **finding**: a name row landing on a foreign body."""
    part = LayoutPart(
        part_id="P2", symbol_ref=RES, symbol_hash=HASH,
        x=190.0, y=600.0, rotation=0.0, mirror=False, reference="P2",
    )
    circuit = _circuit(
        SpecNet(id="SENSE", cls="signal", members=["P2.1", "P2.2"]),
        parts=[SpecPart(id="P2", symbol_ref=RES, value="10k")],
    )
    # A run (100,600)-(240,600) reaches both pin tips; the host anchors the name
    # at the run's midpoint (170, 600) and grows it rightward — over P2's drawn
    # extent (180..200, 595..605).
    plan = _plan(
        parts=[part],
        segments=[LayoutSegment(net="SENSE", points=[(100.0, 600.0), (240.0, 600.0)])],
    )
    kinds = _kinds(plan, circuit)
    assert readability.KIND_TEXT_OVERLAP in kinds
    boxes = readability._text_boxes(plan, {RES: _resistor()})
    row = [box for name, box, _owner, _text in boxes if name == "segments[0]"][0]
    assert row[0] == pytest.approx(170.0)
    assert row[2] == pytest.approx(170.0 + textmetrics.render_width("SENSE"))


def test_a_wire_of_the_named_net_is_exempt_from_its_own_name_row():
    """The host prints the name *along* the wire, so that wire always touches it."""
    part = LayoutPart(
        part_id="P1", symbol_ref=RES, symbol_hash=HASH,
        x=400.0, y=700.0, rotation=0.0, mirror=False, reference="P1",
    )
    circuit = _circuit(SpecNet(id="SENSE", cls="signal", members=["P1.1", "P1.2"]))
    plan = _plan(
        parts=[part],
        segments=[LayoutSegment(net="SENSE", points=[(400.0, 500.0), (520.0, 500.0)])],
    )
    assert KIND_TEXT_ON_WIRE not in _kinds(plan, circuit)


# --------------------------------------- 5. the library states what the host draws


def test_every_placed_symbol_in_the_flyback_library_has_a_two_dimensional_body():
    """147's root cause, as a data claim.

    A two-pin profile whose body is the pin axis has **zero** extent across it, and
    a zero-area box is one that no wire and no text row can ever cross — which is
    how three overlapping defects passed every gate. Every profile whose symbol has
    pins must now state both extents, and every pin tip must stay outside its own
    body (a wire reaches a part at its tip).
    """
    library = json.loads(
        (ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json").read_text(
            encoding="utf-8"
        )
    )
    #: ``C0805`` is the one profile no page in this repo has ever placed, so the
    #: host has never been asked for its bbox and it keeps the pin-derived box.
    #: Named rather than skipped silently: a reader has to see which symbol is
    #: still stating a lower bound, and re-measuring it is on the next batch's list.
    unmeasured = {"C0805"}
    checked = 0
    for item in library["profiles"]:
        if not item.get("pins") or item["symbolRef"] in unmeasured:
            continue  # a flag: its body is the glyph, measured by its own test
        box = item["body"]
        assert box[2] > box[0] and box[3] > box[1], (
            f"{item['symbolRef']}: body {box} has no extent in one direction — a "
            "wire cannot be tested against a line"
        )
        for pin in item["pins"]:
            tip = pin["tip"]
            inside = (
                box[0] < tip[0] < box[2] and box[1] < tip[1] < box[3]
            )
            assert not inside, f"{item['symbolRef']}.{pin['number']} tip {tip} in {box}"
        checked += 1
    assert checked == 13, "the library's pinned symbols are the claim's subject"


def test_the_flag_profiles_carry_the_measured_glyph_not_one_convention_box():
    """Two families, two sizes — both measured off the host (147 sec.2)."""
    library = json.loads(
        (ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json").read_text(
            encoding="utf-8"
        )
    )
    bodies = {
        item["symbolRef"]: tuple(item["body"]) for item in library["profiles"]
    }
    assert bodies["PWR-GND"] == (-10.5, 0.0, 10.5, 19.5)
    assert bodies["PWR-HVDC"] == (-5.5, 0.0, 5.5, 10.5)
    assert bodies["PWR-SEC_12V"] == (-5.5, 0.0, 5.5, 10.5)
    # And the reserved box is the drawn one: the host hangs a 20-wide ground
    # symbol 10 units off its connection, not a 12-wide glyph 18 units off.
    profile = SymbolProfile.from_dict(
        next(item for item in library["profiles"] if item["symbolRef"] == "PWR-GND")
    )
    assert flag_glyph_box(profile, rotation=0.0, anchor=(700.0, 395.0)) == (
        689.5, 375.5, 710.5, 395.0,
    )


# ------------------------------------------------ 6. a flag with a wire on it


def test_a_wire_crossing_a_flags_glyph_or_its_name_is_reported():
    """岳's second criticism, as a constraint: the pennant printed on its own rail."""
    plan = _plan(
        power_symbols=[
            LayoutPowerSymbol(symbol_ref=FLAG, symbol_hash=HASH, net="HVDC",
                              x=600.0, y=400.0, rotation=0.0),
        ],
        segments=[LayoutSegment(net="OTHER", points=[(600.0, 430.0), (600.0, 370.0)])],
    )
    circuit = _circuit(
        SpecNet(id="OTHER", cls="signal", members=["P1.1"]),
        SpecNet(id="HVDC", cls="power", members=["P1.2"]),
    )
    kinds = _kinds(plan, circuit)
    assert KIND_WIRE_THROUGH_BODY in kinds  # the glyph
    assert KIND_TEXT_ON_WIRE in kinds  # the name row past it
    # …and it is the **name row**, not the glyph box, that the text half names:
    # the two are separate boxes and only the row is 10 units past the glyph.
    assert any(
        "powerSymbols[0] name" in objects
        for kind, objects in _findings(plan, circuit)
        if kind == KIND_TEXT_ON_WIRE
    )
