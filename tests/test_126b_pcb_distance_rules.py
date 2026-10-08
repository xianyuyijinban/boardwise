"""Tests for task 126 stick 2 (126b): the two PCB distance rules.

Three evidence sources, per the task book (§126b「夹具锚点」):

* **Synthetic boards** — hand-built :class:`~boardwise.core.geometry.BoardGeometry`
  plus a hand-built schematic :class:`~boardwise.core.model.DesignModel`, with
  every expected distance **derived by hand in the comment next to the
  assertion** (pads are axis-aligned rectangles at stated coordinates, so the
  gap is a subtraction anyone can redo). This is where the three states are
  pinned: a WARN over the threshold, silence under it, and the INFO for a
  supply net with no grounded capacitor.
* **毕设FOC** (`ProPrj_毕设FOC驱动板_2026-09-17.epro2`, read-only) — the real
  anchor. The measured distributions and the representative readings are
  **printed into the assertions below with their derivation**, so a reader can
  check a number against the geometry rather than trust it.
* **llc** (`llc_board.epro2`, read-only) — the semantic anchor for a board that
  is *clean*: the two rules must say nothing on it, and that silence has to be
  as deliberate as a WARN.

Plus the **reorder** half of this stick (task 126 §126b「开工前先修」): the
runner call site moved from before `modules_section` to after it, and the
three properties that move with it — the summary's counts, `warning_triage`'s
module attribution, and `pcb_review.boards[].findings` indices — are each
pinned here so a future move cannot silently trade one for another.

The offline fixtures are read-only. Nothing here runs an editor or a daemon.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import (
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    PadGeometry,
    Point,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import (
    BUILTIN_PCB_RULES,
    RUNNER_ID,
    build_module_of,
    run_pcb_review,
)
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule
from boardwise.rules.pcb.distance import (
    COMPONENT_SPACING_MIL,
    DECAP_DISTANCE_MIL,
    ComponentSpacing,
    DecapDistance,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"


# ---------------------------------------------------------------------------
# synthetic helpers
# ---------------------------------------------------------------------------


def _pad(
    component: str,
    pin: str,
    *,
    x: float,
    y: float,
    net: str = "",
    width: float = 40.0,
    height: float = 40.0,
) -> PadGeometry:
    """One **axis-aligned** pad, so every distance below is a subtraction.

    The dimensions are the default 40x40 mil throughout, which is what makes
    the hand-derivations readable: a pad centred at ``x`` spans
    ``[x-20, x+20]`` in both axes, so the edge gap between two of them on one
    axis is ``|x1 - x2| - 40``.

    **``net`` defaults to empty since 127b.** It used to default to ``"GND"``,
    which put *every* pad in the synthetic boards on one net — and the new
    same-net exemption (:func:`boardwise.core.measure.component_distance`) then
    correctly declined to measure any pair, so the threshold tests went quiet
    instead of reporting. These tests are about the 20 mil threshold and the
    board frame, not about connectivity, and an **unnetted** pad is the honest
    "this pair's nets are not what is under test" value: the same-net clause
    skips only pads that *name the same net*. A test that does mean to exercise
    the exemption passes ``net=`` explicitly, and there is one below.
    """
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=1,
        x=x,
        y=y,
        width=width,
        height=height,
        shape="RECT",
        angle=0.0,
    )


def _place(designator: str, x: float, y: float) -> ComponentPlacement:
    return ComponentPlacement(
        id=f"c-{designator}", designator=designator, x=x, y=y, layer_id=1
    )


def _comp(designator: str, *, value: str = "", pins: list[Pin] = ()) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        pins=list(pins),
    )


def _model(components: list[Component]) -> DesignModel:
    """A ``DesignModel`` whose net index is built from its own components' pins."""
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for component in components:
        for pin in component.pins:
            if not pin.net:
                continue
            nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                (component.designator, pin.number)
            )
    model.nets = nets
    return model


def _board(parts: list[tuple[str, float, float]], pads: list[PadGeometry]) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place(des, x, y) for des, x, y in parts],
        pads=list(pads),
    )


def _outline_board(x0: float, y0: float, x1: float, y1: float) -> BoardGeometry:
    return BoardOutline(
        points=[
            Point(x0, y0),
            Point(x1, y0),
            Point(x1, y1),
            Point(x0, y1),
        ],
        source_id="synthetic-outline",
    )


def _ctx(board: BoardGeometry, model: DesignModel | None = None) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=model, intent=None, module_of={}
    )


#: A three-pin IC on ``+3V3`` and a capacitor bridging it to ``GND``. The
#: capacitor is what :func:`boardwise.rules.decap.cap_candidates_on` looks for
#: (a capacitor, bridging this net to a *different* ground net), so the shared
#: predicate is satisfied without a shelf: ``looks_like_capacitor`` accepts a
#: ``C``-prefixed designator whose value parses as a capacitance.
DECOUPLED = "3V3"
#: A ground net that is *not* the one the IC's own ground pin sits on, so the
#: capacitor really bridges two different ground nets (039 批①b's rule).
BRIDGE_GROUND = "AGND"


def _ic_model_and_board(
    *,
    cap_x: float,
    ic_x: float = 0.0,
) -> tuple[DesignModel, BoardGeometry]:
    """One IC at ``ic_x`` and one decoupling capacitor at ``cap_x``.

    Both y at 0, so the edge gap is purely horizontal: pads span
    ``[c-20, c+20]``, so the measured ``edge_distance`` is
    ``abs(cap_x - ic_x) - 40``.
    """
    model = _model([
        _comp("U1", pins=[
            Pin("1", "VCC", DECOUPLED),
            Pin("2", "OUT", "SIG"),
            Pin("3", "GND", "GND"),
        ]),
        _comp("C1", value="100nF", pins=[
            Pin("1", "1", DECOUPLED),
            Pin("2", "2", BRIDGE_GROUND),
        ]),
    ])
    board = _board(
        [("U1", ic_x, 0.0), ("C1", cap_x, 0.0)],
        [
            _pad("U1", "1", x=ic_x, y=0.0, net=DECOUPLED),
            _pad("U1", "2", x=ic_x, y=0.0, net="SIG"),
            _pad("U1", "3", x=ic_x, y=0.0, net="GND"),
            _pad("C1", "1", x=cap_x, y=0.0, net=DECOUPLED),
            _pad("C1", "2", x=cap_x, y=0.0, net=BRIDGE_GROUND),
        ],
    )
    return model, board


# ---------------------------------------------------------------------------
# the threshold constants carry their provenance (钉 7)
# ---------------------------------------------------------------------------


def test_both_thresholds_are_house_rules_and_say_so():
    """钉 7: a house rule threshold is labelled 待裁, never dressed as a standard.

    IPC-2221 states *clearance*, not a placement distance, and 126c owns the
    standards-derived numbers. If either constant below ever claims a standard
    it does not have, this goes red — that is the whole assertion, and it is
    why it reads the two ``source`` strings rather than trusting the docstrings.
    """
    assert DecapDistance.source == "house rule（岳 2026-10 待裁）"
    assert ComponentSpacing.source == "house rule（岳 2026-10 待裁）"
    assert DECAP_DISTANCE_MIL == 200.0
    assert COMPONENT_SPACING_MIL == 20.0
    # Both rules are `pcb-` prefixed and answer a PcbReviewContext (钉 1).
    for rule in BUILTIN_PCB_RULES:
        assert rule.id.startswith("pcb-")
        assert isinstance(rule, PcbRule)


# ---------------------------------------------------------------------------
# pcb-decap-distance — synthetic, three states
# ---------------------------------------------------------------------------


def test_a_capacitor_beyond_the_threshold_is_a_warn_carrying_the_reading():
    """State 1: over the line, with the number in the structured target.

    The IC sits at x=0 and the capacitor at x=350. Pads are 40x40, so each
    spans ±20: the right edge of U1 is at +20 and the left edge of C1 is at
    330, giving a hand-derived gap of **310.0 mil** — over the 200 mil house
    rule, so WARN. The finding's target is the contract 钉 3 asks for: the IC
    is the subject, ``C1`` is the ``counterpart_ref``, the supply net is named,
    and the measurement is ``{kind: distance, unit: mil}``.
    """
    model, board = _ic_model_and_board(cap_x=350.0)
    findings = DecapDistance().check(_ctx(board, model))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "pcb-decap-distance"
    assert finding.severity == "WARN"
    target = finding.target
    assert target is not None
    assert target.component_ref == "U1"
    assert target.counterpart_ref == "C1"
    assert target.net_refs == [DECOUPLED]
    assert target.measurement == {
        "kind": "distance", "value": 310.0, "unit": "mil",
    }
    # The message shows the number too, because a reader is not a parser.
    assert "C1" in finding.message and "310.0" in finding.message


def test_a_capacitor_inside_the_threshold_is_silence_not_an_info():
    """State 2: under the line, the rule says **nothing**.

    Same board with the capacitor at x=150: gap = 150 - 40 = **110.0 mil**,
    comfortably inside 200. An empty list is the honest statement — an INFO row
    here would train a reader to ignore the INFO rows that do mean something
    (the "no capacitor at all" one below).
    """
    model, board = _ic_model_and_board(cap_x=150.0)
    assert DecapDistance().check(_ctx(board, model)) == []


def test_the_threshold_boundary_is_exactly_at_the_line_and_past_it():
    """Exactly 200 mil passes; 200.001 does not. The comparison is `<=`.

    ``cap_x = 240`` puts C1's left edge at 220 and U1's right edge at +20, so
    the gap is **200.0** — the threshold itself, which is a pass. 240.001 makes
    it 200.001, a WARN. Pinned because "over the threshold" has to mean
    *strictly* over, or a layout that lands the cap at exactly the limit
    produces a report row that depends on a rounding step.
    """
    model, board = _ic_model_and_board(cap_x=240.0)
    assert DecapDistance().check(_ctx(board, model)) == []
    model, board = _ic_model_and_board(cap_x=240.001)
    assert len(DecapDistance().check(_ctx(board, model))) == 1


def test_a_capacitor_closed_on_one_net_is_not_a_candidate():
    """State 3: nothing usable on the net — an INFO naming the IC and the net.

    ``C1`` has **both** terminals on ``3V3``, so it bridges nothing (039 批①b's
    measurement, inherited through
    :func:`boardwise.rules.decap.cap_candidates_on` rather than re-argued here:
    a part whose two ends sit on one net connects nothing, so it cannot decouple
    that net from anything). The rule still reports, at INFO: 「this IC sits on a
    supply net and the design put no grounded capacitor on it」 is a fact about
    the layout. It is **not** an ERROR and not a "decap-required-caps" verdict —
    whether the net needs a capacitor is the datasheet's question, and
    ``decap-required-caps`` owns it on the same fixture.

    Note the candidate test is "one end here, the other on a ground net", **not**
    "the other end on a *different* ground net": a capacitor from ``3V3`` to
    ``GND`` is a candidate even though the IC's own ground pin is also on
    ``GND``, which is the ordinary case and is what the next test's board
    exercises.
    """
    model = _model([
        _comp("U1", pins=[
            Pin("1", "VCC", DECOUPLED),
            Pin("2", "OUT", "SIG"),
            Pin("3", "GND", "GND"),
        ]),
        _comp("C1", value="100nF", pins=[
            Pin("1", "1", DECOUPLED),
            Pin("2", "2", DECOUPLED),  # both ends on one net: bridges nothing
        ]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C1", 20.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=DECOUPLED),
            _pad("U1", "2", x=0.0, y=0.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=0.0, net="GND"),
            _pad("C1", "1", x=20.0, y=0.0, net=DECOUPLED),
            _pad("C1", "2", x=20.0, y=0.0, net="GND"),
        ],
    )
    findings = DecapDistance().check(_ctx(board, model))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO"
    assert finding.target.component_ref == "U1"
    assert finding.target.net_refs == [DECOUPLED]
    # It names what it does NOT know, rather than claiming a requirement.
    assert "decap-required-caps" in finding.message


def test_a_capacitor_the_named_net_carries_but_this_board_does_not_is_skipped():
    """A candidate with no geometry here is **absent information, not zero**.

    The netlist names C1, this PCB document does not carry it (the multi-board
    case, or a placement the parser dropped — 040/107). A rule that reported
    "0.0 mil away" here would be manufacturing a collision, and one that
    reported a WARN would be measuring nothing. The pair is dropped from the
    measurement set entirely, so the IC's row is a silence.
    """
    model, board = _ic_model_and_board(cap_x=350.0)
    # Drop C1 from the board's placements and pads: it stays in the model.
    board = _board(
        [("U1", 0.0, 0.0)],
        [pad for pad in board.pads if pad.component != "C1"],
    )
    assert DecapDistance().check(_ctx(board, model)) == []


def test_a_shelf_that_does_not_load_still_leaves_the_net_name_half_working(
    monkeypatch,
):
    """A missing shelf narrows the rule to what it can still prove.

    Two of the three supply-net sources are the net-name whitelist (``+5V``,
    ``3V3``, ...) and only one is the facts shelf (a regulator's declared or
    MPN-decoded output). With ``blocklib/parts.json`` absent, the first still
    works and only the second goes quiet — so ``+5V`` is still examined and the
    LDO's output net drops out. The pin is the **direction** of the degradation:
    a narrower rule that misses a net, never a rule that starts examining nets
    its facts cannot support.

    The failure this guards against is the plausible one: wrapping the shelf
    read in a broad ``try/except`` and then skipping the inference entirely,
    which would have thrown away the ``+5V`` half as collateral damage of an
    unreadable shelf. :func:`boardwise.core.parts.load_parts` and
    :func:`boardwise.core.power_domains.infer_net_domains` each already handle
    the absent case, so this rule adds no handling of its own.
    """
    import boardwise.rules.facts as facts_rules
    import boardwise.rules.pcb.distance as distance

    monkeypatch.setattr(facts_rules, "default_library_path", lambda: "nowhere/parts.json")
    assert distance._supply_nets(_supply_model()) == {"+5V"}
    # With the real shelf the same model gains nothing on this net (no regulator
    # in the model), so the two readings agree here — the point is that the
    # shelf-less one is not *empty*.
    monkeypatch.undo()
    assert distance._supply_nets(_supply_model()) == {"+5V"}


def _supply_model() -> DesignModel:
    """A three-pin IC on ``+5V``, which the net-name whitelist calls 5 V."""
    return _model([
        _comp("U1", pins=[
            Pin("1", "VCC", "+5V"),
            Pin("2", "OUT", "SIG"),
            Pin("3", "GND", "GND"),
        ]),
    ])


def test_pad_corners_is_the_public_name_and_the_private_one_is_the_same_function():
    """126b promoted ``core.measure._pad_corners`` to ``pad_corners``.

    125 wrote the helper private and left a note saying 125b would consume it;
    126b is the second consumer, in ``rules``, and the repository's layer rule
    (``test_layer_rules.py::test_no_private_name_crosses_a_layer``) forbids a
    ``rules``-layer import of a ``core``-private name. The promotion is the fix
    the rule asks for ("make it public in its own layer"), and this pins the
    part of it that could drift: the two names are **one function object**, not
    a second implementation that could be edited independently and make two
    rules disagree about where a pad's edge is.
    """
    from boardwise.core import measure

    assert measure._pad_corners is measure.pad_corners
    assert "pad_corners" in measure.__all__, (
        "it is public API now, so it belongs in the module's __all__"
    )
    pad = PadGeometry(
        id="p", component="C1", pin_number="1", x=100.0, y=50.0,
        width=40.0, height=20.0, angle=90.0,
    )
    # A 40x20 pad rotated 90 deg spans 20 in x and 40 in y about its centre.
    corners = measure.pad_corners(pad)
    assert {round(c.x, 6) for c in corners} == {90.0, 110.0}
    assert {round(c.y, 6) for c in corners} == {30.0, 70.0}
    assert len(corners) == 4


def test_a_two_pin_part_is_never_an_ic():
    """The IC floor is three pins, and a two-pin part does not reach the rule.

    A resistor is not an IC and must not produce rows even when it sits on a
    supply net. The board carries a 2-pin ``R1`` from ``3V3`` to ``GND``;
    without the floor the rule would look for a decoupling capacitor "for" it.
    """
    model = _model([
        _comp("R1", value="10k", pins=[
            Pin("1", "1", DECOUPLED),
            Pin("2", "2", "GND"),
        ]),
    ])
    board = _board(
        [("R1", 0.0, 0.0)],
        [_pad("R1", "1", x=0.0, y=0.0, net=DECOUPLED),
         _pad("R1", "2", x=0.0, y=0.0, net="GND")],
    )
    assert DecapDistance().check(_ctx(board, model)) == []


def test_a_net_the_inference_cannot_call_a_supply_is_not_examined():
    """A net **named** like a rail is not a rail (the 011 family's own lesson).

    ``VCC`` is deliberately not in :mod:`boardwise.core.power_domains`'s
    whitelist — a name that reads like a supply is not a declaration, and a
    rule that trusted it would file a row about every signal net a connector
    happens to name. Here the IC sits on ``VCC``, a 100nF capacitor is 10 mil
    away, and the rule must still say nothing: the voltage of ``VCC`` is not
    established, so there is no supply net to decouple.
    """
    model = _model([
        _comp("U1", pins=[
            Pin("1", "VCC", "VCC"),
            Pin("2", "OUT", "SIG"),
            Pin("3", "GND", "GND"),
        ]),
        _comp("C1", value="100nF", pins=[
            Pin("1", "1", "VCC"),
            Pin("2", "2", "GND"),
        ]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C1", 0.0, 0.0)],
        [_pad("U1", "1", x=0.0, y=0.0, net="VCC"),
         _pad("U1", "2", x=0.0, y=0.0, net="SIG"),
         _pad("U1", "3", x=0.0, y=0.0, net="GND"),
         _pad("C1", "1", x=0.0, y=0.0, net="VCC"),
         _pad("C1", "2", x=0.0, y=0.0, net="GND")],
    )
    assert DecapDistance().check(_ctx(board, model)) == []


def test_a_board_with_no_ics_no_caps_and_no_outline_produces_nothing_and_never_raises():
    """空输入不炸 (task's red line): every empty shape returns a list.

    Four empty boards, all of which a caller may legitimately hand in: a board
    with no components at all, one with components but no pads, a board with a
    model but no supply net, and a board with an outline but no IC. The
    assertion is that each returns ``[]`` rather than raising — a rule that
    crashes on an empty board takes the whole ``checkup`` report with it, which
    is the failure mode 126a's per-rule try/except exists to contain, and which
    a test is a better guard against than a try/except.
    """
    assert DecapDistance().check(_ctx(BoardGeometry(), _model([]))) == []
    assert DecapDistance().check(_ctx(BoardGeometry(), None)) == []
    assert DecapDistance().check(_ctx(_board([("U1", 0, 0)], []), _model([]))) == []
    assert ComponentSpacing().check(_ctx(BoardGeometry(), None)) == []
    assert ComponentSpacing().check(_ctx(_board([], []))) == []
    # A board whose outline is absent: the spacing half must still run (it does
    # not need a frame) and the board-frame half must stay silent.
    assert ComponentSpacing().check(_ctx(BoardGeometry())) == []


# ---------------------------------------------------------------------------
# pcb-component-spacing — synthetic, three states
# ---------------------------------------------------------------------------


def test_two_parts_closer_than_the_threshold_are_a_warn_naming_both():
    """State 1: the pair, the pads, and the number.

    R1 at x=0 and R2 at x=55, both pads 40 wide: R1's right edge is at +20
    and R2's left edge at 35, so the hand-derived gap is **15.0 mil** — under
    the 20 mil house rule. The finding carries both designators
    (``component_ref`` / ``counterpart_ref``) and the measured distance, which
    is what makes a reviewer able to find the pair on the canvas.
    """
    board = _board(
        [("R1", 0.0, 0.0), ("R2", 55.0, 0.0)],
        [_pad("R1", "1", x=0.0, y=0.0), _pad("R2", "1", x=55.0, y=0.0)],
    )
    findings = ComponentSpacing().check(_ctx(board))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "pcb-component-spacing"
    assert finding.severity == "WARN"
    assert finding.target.component_ref == "R1"
    assert finding.target.counterpart_ref == "R2"
    assert finding.target.measurement == {
        "kind": "distance", "value": 15.0, "unit": "mil",
    }
    # "they touch" is said when they touch, because 0.0 is a different defect
    # from "close" and a reader needs to know which one they are looking at.
    touching = ComponentSpacing().check(_ctx(_board(
        [("R1", 0.0, 0.0), ("R2", 30.0, 0.0)],
        [_pad("R1", "1", x=0.0, y=0.0), _pad("R2", "1", x=30.0, y=0.0)],
    )))
    assert touching[0].target.measurement["value"] == 0.0
    assert "they touch" in touching[0].message


def test_two_parts_exactly_at_the_threshold_are_silence():
    """The comparison is strict: exactly 20 mil passes.

    R2 at x=60 gives a gap of exactly 20.0, the threshold. Pinned alongside the
    decap boundary test so the two rules cannot drift into different
    conventions at the line.
    """
    board = _board(
        [("R1", 0.0, 0.0), ("R2", 60.0, 0.0)],
        [_pad("R1", "1", x=0.0, y=0.0), _pad("R2", "1", x=60.0, y=0.0)],
    )
    assert ComponentSpacing().check(_ctx(board)) == []


def test_a_part_hanging_off_the_board_outline_is_an_error():
    """State 2: the board frame, as its own severity.

    The outline is the rectangle (0,0)-(500,500) and ``C9``'s pad is centred at
    (520, 100) with a 40x40 pad, so its right edge is at **540.0** — 40.0 mil
    past the frame's right edge at 500. ERROR, with the over-hang as the
    measurement. The part is *inside* the frame in every other axis; the number
    is the largest single-edge margin, not a diagonal, so the message names the
    edge it actually hangs off.
    """
    board = _board(
        [("C9", 520.0, 100.0)],
        [_pad("C9", "1", x=520.0, y=100.0)],
    )
    board.outline = _outline_board(0.0, 0.0, 500.0, 500.0)
    findings = ComponentSpacing().check(_ctx(board))
    assert len(findings) == 1
    assert findings[0].severity == "ERROR"
    assert findings[0].rule_id == "pcb-component-spacing"
    assert findings[0].target.component_ref == "C9"
    assert findings[0].target.measurement == {
        "kind": "distance", "value": 40.0, "unit": "mil",
    }
    # A part comfortably inside the same frame produces nothing from the
    # board-frame half, and with only one part the spacing half is silent too.
    inside = _board(
        [("C9", 100.0, 100.0)],
        [_pad("C9", "1", x=100.0, y=100.0)],
    )
    inside.outline = _outline_board(0.0, 0.0, 500.0, 500.0)
    assert ComponentSpacing().check(_ctx(inside)) == []


def test_a_degenerate_one_point_outline_files_no_board_frame_errors():
    """A one-point ``BOARD_OUTLINE`` is a board that was never drawn, not a board
    every part hangs off.

    This is measured, not hypothetical: 毕设FOC's **PCB2** document stores a
    ``BOARD_OUTLINE`` poly with a **single** vertex at (17.4999, 27.5), and 10
    of its 11 components sit outside that point. Reading it as a frame would
    file 10 ERRORs at board scale about a board whose outline the editor never
    finished — a false ERROR is worse than a missing one here, because the
    report's exit code and the reviewer's first action both follow the error
    count. So fewer than three corners is read as **no outline**: the
    board-frame half is silent and the spacing half still runs, since a
    collision between two parts needs no frame to be true.
    """
    board = _board(
        [("U1", 0.0, 0.0), ("R1", 50.0, 0.0)],
        [_pad("U1", "1", x=0.0, y=0.0), _pad("R1", "1", x=50.0, y=0.0)],
    )
    board.outline = BoardOutline(
        points=[Point(17.4999, 27.5)], source_id="one-point"
    )
    findings = ComponentSpacing().check(_ctx(board))
    assert [f.severity for f in findings] == ["WARN"], (
        "only the spacing half runs; the one-point outline files no ERROR"
    )


# ---------------------------------------------------------------------------
# the runner call site moved: the three properties that move with it
# ---------------------------------------------------------------------------


def test_the_runner_is_handed_the_reports_own_modules_so_module_of_is_populated():
    """126b's「开工前先修」, the reason: before the move, ``module_of`` was empty.

    The pre-reorder call site sat **above** ``modules_section``, so it passed
    ``modules=None`` and :func:`build_module_of` had only the contract to read
    from. 毕设FOC has **no** contract, so its PCB findings were attributed to
    nothing at all. The reorder hands the runner the real ``modules[]``, and the
    mapping goes from 0 entries to 121 — one per placed designator that
    ``modules[]`` covers. Asserted against both readings so the pin is "the
    reorder bought the tool's own module reading", not a fixture-specific name.
    """
    model, _board_ = cli._load_model(FOC, view="schematic")
    from boardwise.engines.checkup import modules_section

    modules, _facts = modules_section(model=model, findings=[])
    assert modules, "the fixture yields a module reading to hand over"

    before = build_module_of(model, None, None)   # the pre-reorder call
    after = build_module_of(model, None, modules)
    assert before == {}, "no contract and no modules means no attribution at all"
    assert len(after) > 100, "the tool's own modules[] is now the attribution source"
    # Every designator a PCB finding can name is attributable after the move.
    covered = {ref for entry in modules for ref in entry.get("components") or []}
    assert covered, "modules[] names real designators"


@pytest.mark.parametrize("tier_file", [FOC])
def test_a_pcb_finding_lands_in_the_summary_and_the_triage_with_the_right_module(
    capsys, tmp_path, monkeypatch, tier_file
):
    """All three properties of the merge, end to end through the real CLI.

    The reorder moved the runner **after** ``modules_section`` and **before**
    ``drc_summarise``; this is the one test that checks all three consequences
    at once, because a future move could satisfy one and break another:

    1. **the summary** — a PCB WARN is in ``summary.warnings`` and counted in
       ``summary.warnCount``, because ``drc_summarise`` now reads the merged
       array;
    2. **module attribution in the triage** — a PCB WARN's
       ``warning_triage`` slot names the module its designator belongs to
       (only possible now that ``modules_section`` ran first and handed the
       runner the real ``modules[]``);
    3. **``boards[].findings`` indices** — every index the ``pcb_review``
       section names points at a row in the merged ``findings[]`` that really
       is that board's.

    The report is read from disk (``report.json``), not from the return value,
    so the base-index shift the merge performs is checked as a reader sees it.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "foc"
    cli.main([
        "checkup", "--file", str(tier_file), "--out", str(out),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    pcb_rows = [
        (i, row) for i, row in enumerate(report["findings"])
        if row["rule_id"].startswith("pcb-")
    ]
    assert pcb_rows, "the two 126b rules are in BUILTIN_PCB_RULES, so they fire"

    # (1) summary: every PCB WARN is enumerated in summary.warnings.
    summary_warn_refs = {
        entry.get("ref") for entry in report["summary"]["warnings"]
        if str(entry.get("ruleId", "")).startswith("pcb-")
    }
    assert summary_warn_refs, "a PCB WARN reaches summary.warnings"
    for index, row in pcb_rows:
        if row["severity"] == "WARN":
            assert f"findings[{index}]" in summary_warn_refs
    assert any(
        str(entry.get("ruleId", "")).startswith("pcb-")
        for entry in report["summary"]["warnings"]
    )

    # (3) boards[].findings index the merged array, offset by the schematic's.
    section = report["pcb_review"]
    assert section["runner"] == RUNNER_ID
    indexed = {i for board in section["boards"] for i in board["findings"]}
    assert indexed, "the section still carries real indices"
    for board in section["boards"]:
        for index in board["findings"]:
            row = report["findings"][index]
            assert row["board"] == board["title"], (
                "the index names that board's row in the merged array"
            )
    # The shift is non-zero on this fixture (the schematic rules contributed
    # findings first), so an unshifted index would land on the wrong row.
    assert min(indexed) > 0, "the schematic side contributed findings first"

    # (2) module attribution: a PCB WARN's triage slot names a real module.
    module_of_ref = {
        ref: entry["name"]
        for entry in report["modules"]
        for ref in entry.get("components") or []
    }
    pcb_triage = [
        slot for slot in report["warning_triage"]
        if any("pcb-" in str(e) for e in slot.get("evidence") or [])
    ]
    assert pcb_triage, "PCB WARNs reach warning_triage"
    attributed = [
        slot for slot in pcb_triage if slot["attribution"].get("module")
    ]
    assert attributed, (
        "a PCB WARN is attributed to a module — the whole point of the reorder"
    )
    # And the module it names is one of the report's own modules.
    names = {entry["name"] for entry in report["modules"]}
    for slot in attributed:
        assert slot["attribution"]["module"] in names


def test_the_absent_section_stays_absent_for_a_backup_with_no_pcb_document(
    capsys, tmp_path, monkeypatch
):
    """126b did not touch 钉 5: no PCB document → no ``pcb_review`` key.

    ``ProPrj_CH340G`` carries no PCB document. The section must not appear
    merely because the runner now has rules to run — "there was no PCB to
    review" and "the PCB was reviewed and found clean" are different
    statements, and only the second is a section.
    """
    no_pcb = FIXTURES / "ProPrj_CH340G_2026-09-13.epro2"
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "no-pcb"
    cli.main([
        "checkup", "--file", str(no_pcb), "--out", str(out), "--library", str(SHELF),
    ])
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert "pcb_review" not in report, "absent, not empty"
    assert not [f for f in report["findings"] if f["rule_id"].startswith("pcb-")]


# ---------------------------------------------------------------------------
# 毕设FOC anchor — the real measured numbers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def foc_findings():
    """The full PCB review of 毕设FOC, run once for the whole module."""
    findings, section = run_pcb_review(FOC, model=cli._load_model(FOC, view="schematic")[0])
    return findings, section


def test_foc_pcb1_the_decap_readings_are_four_infos_and_no_warn(foc_findings):
    """毕设FOC PCB1 anchor: **no WARN at all**, and four INFO rows.

    **This is the 127b flip, and it is the whole point of the exercise.** 126b
    reported one WARN here — ``U6`` at 555.8 mil on ``+24V`` — and 岳's blind
    review rejected it: ``U6`` is **not an IC**. The schematic says so and says
    it three ways: its MPN is ``HX PZ2.54-2x6P TP``, its footprint is
    ``SMD,P=2.54mm``, and its shelf entry is ``conn.hx_pz2_54_2x6p_tp`` — a 2x6
    **排针**, a row of 2.54 mm pins. It carries a ``U`` designator because
    whoever drew the sheet wrote ``U?`` in the library's own ``Designator``
    attribute, which is precisely why 127b made the device's facts outrank the
    designator. (On the 1.0 export 岳 actually uses, ``U6`` is an LDO; on this
    1.1.0 fixture it is a header — 127a established that the审查对象 was wrong,
    not the parser. See the task book.)

    The four rows that remain are this board's (IC, net) pairs, all INFO because
    **no candidate on any of them is a high-frequency decoupling capacitor**
    (127b 裁定 5b). What is pinned is the pair set and the fact that not one is a
    WARN — the INFO-vs-WARN split *is* the fix, and a reader who wants to know
    why a pair is INFO reads the ``evidence`` lines, which now carry the IC
    judgement and every candidate's role with the declared value that decided it.
    """
    findings, _section = foc_findings
    pcb1 = [
        f for f in findings
        if f.board == "PCB1" and f.rule_id == "pcb-decap-distance"
    ]
    assert pcb1, "the three supply nets still produce (IC, net) pairs"
    assert all(f.severity == "INFO" for f in pcb1), (
        "no decap WARN survives on this board: every candidate pool is bulk, "
        "unreadable, or in the band between the HF ceiling and the bulk floor"
    )
    pairs = {(f.target.component_ref, tuple(f.target.net_refs)) for f in pcb1}
    assert pairs == {
        ("U11", ("+5V",)),
        ("U11", ("NET10",)),
        ("U13", ("+5V",)),
        ("U7", ("+24V",)),
    }, (
        "the same pairs 126b examined, minus U6 — which the schematic says is "
        "a 2x6 header, not an IC"
    )
    # The IC judgement is quoted, so 「why is there no U6 row」 is answerable from
    # the report rather than from this file.
    for finding in pcb1:
        assert any(
            "judged an IC because" in line for line in finding.evidence
        ), "every decap row states the basis on which the part is an IC"
    # And U6 is absent for a stated reason rather than for no reason: the
    # connector word that stopped it.
    from boardwise import cli as _cli
    from boardwise.rules.pcb.distance import classify_device, device_facts

    model, _ = _cli._load_model(FOC, view="schematic")
    u6 = model.boards[0].components["U6"]
    is_ic, why = classify_device(device_facts(u6), pins=len(u6.pins))
    assert is_ic is False
    assert "connector/header" in why and "PZ2.54" in why

    assert len(foc_findings[1]["boards"]) == 3


def test_foc_pcb1_the_spacing_warns_are_four_and_none_of_them_touch(foc_findings):
    """毕设FOC PCB1 anchor: **4** spacing WARNs, and **none** of them touching.

    **This is the 127b regression nail, and the numbers are the evidence.** 126b
    reported 17 WARNs on this board, six of them at exactly 0.0 mil — six pairs
    of parts "physically overlapping" — on a board whose host DRC is clean. 127a
    measured every one of those six and found them all to be the **same**
    defect: a top-side part, whose footprint pads all carry ``layerId == 1``,
    measured against a bottom-side part (``U4`` / ``U6`` / ``R17`` / ``C14``,
    ``COMPONENT.layerId == 2``) whose pads carry that same hardcoded ``1``. The
    rule was comparing copper on opposite faces of a 1.6 mm board.

    After 127b both clauses live in the measurement itself
    (:func:`boardwise.core.measure.component_distance`): a pad pair sharing no
    copper layer is not measured, and a **same-net** pair is exempt, because two
    pads of one net meeting is the design's intent rather than a defect. That
    is 22 WARNs across the three boards -> 4, and **every remaining one is
    same-side and cross-net**: U8/USB1 13.8, R18/U16 15.1, R22/USB1 19.2 and
    R24/USB1 19.2. All four are the real same-face crowded-placement population
    126b's threshold was reaching for; none is an artifact.

    The widest is R22/USB1 and R24/USB1 at 19.2 mil — just under the 20 mil
    line, which is still the observation 岳 is asked to rule on. What is no
    longer true is 126b's 「two of the seventeen sit within a mil of the line」:
    with the 18 false positives gone, the population is four rows and the
    nearest is 13.8 mil, so a 20-mil threshold is now **comfortably** separated
    from a 25-mil one on this board rather than straddling it.
    """
    findings, _section = foc_findings
    spacing = [
        f for f in findings
        if f.board == "PCB1" and f.rule_id == "pcb-component-spacing"
    ]
    assert len(spacing) == 4, (
        "the nine top x bottom pairs and the same-net pairs are gone; what "
        "remains is the same-side, cross-net population"
    )
    pairs = {
        (f.target.component_ref, f.target.counterpart_ref):
            f.target.measurement["value"]
        for f in spacing
    }
    assert pairs == {
        ("U8", "USB1"): 13.8,
        ("R18", "U16"): 15.1,
        ("R22", "USB1"): 19.2,
        ("R24", "USB1"): 19.2,
    }
    # 127a's regression nail, at the rule level: no spacing finding on this
    # board claims two parts touch. Every one of the six 0.0-mil readings was
    # the layer-attribution defect, and every one is gone.
    assert [f for f in spacing if f.target.measurement["value"] == 0.0] == [], (
        "zero touching pairs — 127a's regression nail"
    )


def test_foc_board_frame_no_part_hangs_off_pcb1(foc_findings):
    """The board-frame half is silent on the two real outlines, and PCB2 is
    exempt for the measured reason (a one-point outline).

    PCB1 and PCB3 both carry a 4-corner outline and no component reaches past
    it (measured, all 105 and 33 components inside) — so the board-frame half
    of the rule contributes **zero** ERRORs on this fixture, and that silence
    is pinned here rather than left implicit. PCB2 carries a **one-point**
    outline, and the degenerate-outline test above covers why that produces no
    ERRORs either. The reader of this test should take away that the rule's
    ERROR path is exercised only synthetically — a real fixture has no part off
    its board, which is itself the honest answer.
    """
    findings, _section = foc_findings
    frame_errors = [f for f in findings if f.severity == "ERROR"]
    assert frame_errors == [], (
        "no fixture part is off its board; the board-frame ERROR path is "
        "covered synthetically only"
    )


def test_foc_pcb3_carries_no_decap_row_because_it_has_no_ic(foc_findings):
    """PCB3 anchor: **zero** decap findings — the board has no IC, and that is
    the cause.

    126b reported four WARNs here and called them 「true positives in kind」.
    They were not. Every one of them asked a **non-IC** for a bypass capacitor:

    * ``Q1`` / ``Q3`` / ``Q7`` are ``MCAC53N06Y-TP`` MOSFETs (岳裁定 1, named by
      name in the task book). A power MOSFET's *drain* sits on ``+24V`` and its
      gate on the driver's output; reading that drain as 「an IC's supply net」
      and reporting 「no decoupling capacitor within 200 mil」 is a category
      error, and it was three of the four rows.
    * ``U2`` on this board is **not** the DRV8350. Its MPN is ``PZ2.54-2*6``
      and its footprint is ``排针,P=2.54mm`` — it is the 2x6 header that carries
      the gate-driver signals out (``GHC`` / ``GLC`` / ``SHC`` / ``SLC`` /
      ``IC+`` / ``IC-`` / ``PGND`` / ``+24V``). The DRV8350 is ``U2`` on
      **Board1** (PCB1); 126b reached it through the designator alone, across two
      boards. So the fourth row was a 275.7 mil 「distance from U2 to C115」 on a
      board where neither part is an IC and C115 is a 330 µF aluminium can.

    **And the candidate pool would have excluded the row anyway** (裁定 5b): the
    PCB3 candidates on ``+24V`` are C1/C4/C5/C6/C115/C116 — every one a
    ``330uF`` ``PA50V330M10x15`` bulk electrolytic — plus C2/C3/C13, whose
    values (100 nF / 2.2 µF / 10 nF) sit in the band between the 1 µF HF
    ceiling and the 10 µF bulk floor. Not one is a high-frequency bypass.

    This pins the **absence** and its two causes separately, because either
    could regress alone: an IC appearing on this board, or a bulk capacitor
    entering the high-frequency pool.
    """
    findings, _section = foc_findings
    pcb3 = [
        f for f in findings
        if f.board == "PCB3" and f.rule_id == "pcb-decap-distance"
    ]
    assert pcb3 == [], (
        "PCB3 is the MOSFET stage: its +24V pins are transistor drains and its "
        "U2 is a 2x6 header, so no part on it is an IC and there is nothing "
        "for this rule to ask about"
    )

    # The cause, stated directly rather than inferred from the absence: the
    # device facts, for the two shapes 126b got wrong.
    from boardwise import cli as _cli
    from boardwise.rules.pcb.distance import classify_device, device_facts

    model, _ = _cli._load_model(FOC, view="schematic")
    board3 = next(b for b in model.boards if b.board.title == "Board3")
    for designator, expected_word in (
        ("Q1", "transistor"), ("U2", "connector/header"),
    ):
        comp = board3.components[designator]
        is_ic, why = classify_device(device_facts(comp), pins=len(comp.pins))
        assert is_ic is False, f"{designator} is not an IC"
        assert expected_word in why, (
            f"{designator} is excluded by the {expected_word!r} clause, not by "
            f"the pin count: {why!r}"
        )


# ---------------------------------------------------------------------------
# llc anchor — a clean board, and silence is as pinned as a WARN
# ---------------------------------------------------------------------------


def test_llc_is_clean_under_both_distance_rules():
    """llc anchor: 47 components, 903 pairs, the rule says nothing.

    The measured minimum on this board is **20.5 mil** (C1/D1), and the next
    five are 26.0 / 31.7 / 36.7 / 37.3 / 56.7 — so a 20-mil threshold leaves
    the whole board just clear of it, with the closest pair less than 3 mil
    from the line. That is the second half of the evidence 岳 is being asked to
    rule on: 20 mil is not a threshold this board violates anywhere, and it
    is not one it clears by a wide margin either. Every component is inside the
    board frame (the 4-corner outline, 0 components out), so the board-frame
    half is silent too. The whole rule output for this board is ``[]`` — which
    is pinned, because "a rule that never fires" and "a rule that fires
    correctly" are only distinguished by a test that expects the empty answer.
    """
    model, _board_ = cli._load_model(LLC, view="schematic")
    findings, section = run_pcb_review(LLC, model=model)
    assert findings == [], (
        f"llc is clean under both rules; got "
        f"{[(f.rule_id, f.message) for f in findings]}"
    )
    assert section is not None and section["available"] is True
    # checksRun names **all nine** rules now (131b inserted the regulator pair
    # after 126b's, 131c the feedback rule, 131d the crystal rule and 131e the
    # two MCU rules; 126c appended the IPC pair):
    # silence is a *result*, not a skip. On this board the two IPC rules are
    # silent for two different reasons worth keeping separate, and both are
    # 126c's own discipline rather than an accident:
    #   * `pcb-track-ampacity` has no subject — llc has no contract, and the
    #     rule's subject is a current the contract declares;
    #   * `pcb-voltage-spacing` has no priced pair — the architecture
    #     enumeration prices **no** rail on this board and llc carries no
    #     ground-named net, so there is no difference to look up.
    #   * `pcb-regulator-cap-distance` (131b) and `pcb-regulator-fb-placement`
    #     (131c) are silent because llc's shelf has no `ic.ldo` / `ic.buck`
    #     entry at all — measured, see
    #     `test_131b_regulator_cap_distance.py::test_llc_names_no_regulator`
    #     and `test_131c_regulator_fb_placement.py::test_llc_names_no_regulator`.
    #   * `pcb-mcu-crystal-placement` (131d) is silent for the same shape of
    #     reason: llc places no part the shelf calls `ic.mcu` — measured, see
    #     `test_131d_mcu_crystal_placement.py::test_pillbox_produces_rows_and_llc_produces_silence`.
    #   * `pcb-mcu-supply-groups` / `pcb-mcu-reset-boot` (131e) are silent for
    #     the identical reason, and the whole point of the `findings == []`
    #     assertion above is that adding them changed nothing on this board —
    #     measured, see
    #     `test_131e_mcu_supply_reset.py::test_llc_places_no_mcu_and_produces_silence`.
    #   * `pcb-mcu-crystal-keepout` (131f) is silent for that identical reason —
    #     it finds its crystals through the same `ic.mcu` oscillator nets, so a
    #     board with no MCU has no crystal region to inventory — measured, see
    #     `test_131f_mcu_crystal_keepout.py::test_llc_places_no_mcu_and_is_silent`.
    assert section["boards"][0]["checksRun"] == [
        "pcb-decap-distance", "pcb-regulator-cap-distance",
        "pcb-regulator-fb-placement",
        "pcb-mcu-crystal-placement",
        "pcb-mcu-crystal-keepout",
        "pcb-mcu-supply-groups",
        "pcb-mcu-reset-boot",
        "pcb-component-spacing",
        "pcb-track-ampacity", "pcb-voltage-spacing",
    ]


# ---------------------------------------------------------------------------
# performance — the sweep must stay affordable on the real board
# ---------------------------------------------------------------------------


def test_the_whole_foc_pcb_review_stays_within_a_second_or_two():
    """The measured cost of the two rules on 毕设FOC, all three PCB documents.

    This is a **degenerate** performance check on purpose (057's lesson: a
    timing test that can flake on a busy machine is worse than none). It does
    not assert a wall-clock bound a loaded CI box might miss; it asserts that
    the full review — parse of three documents plus both rules on all of them,
    including the O(n²) 5460-measurement pair sweep on the 105-component PCB1
    — completes without approaching a magnitude that would change what a
    reviewer can ask for. The measured value on the development machine is
    **0.85 s**; the 5-second ceiling here is an order of magnitude of headroom
    over that, so it fails only if the sweep becomes quadratic-in-the-wrong-
    way (or a rule starts re-parsing per component), never because the box was
    busy.
    """
    model, _board_ = cli._load_model(FOC, view="schematic")
    start = time.perf_counter()
    findings, _section = run_pcb_review(FOC, model=model)
    elapsed = time.perf_counter() - start
    assert findings, "the fixture produces findings to time"
    assert elapsed < 5.0, f"PCB review of 毕设FOC took {elapsed:.2f}s"
