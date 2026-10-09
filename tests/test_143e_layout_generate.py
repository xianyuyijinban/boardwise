"""Tests for the 143e batch: the ten defects found in ``engines/generate.py``
and ``engines/layout.py`` by the adversarial review of ``outputs/143_dig/06``.

One section per defect, D1..D10 as the report numbers them. The boards are
synthetic wherever the defect can be shown on one (fast and exact) and the
golden CH340G is used for exactly two things: the D1 measurement that the
finished plan's *own* anchors pass the annotation rulers, and the D2 check that
the new disclosure is silent on a board where nothing was dropped.

Every fix is named in the section docstring with the reason the defect existed,
so a later reader can tell "this test is about a hole that was real" from "this
test is about a shape we like".
"""

from __future__ import annotations

import inspect
import re

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.values import _CAP_UNITS
from boardwise.engines import generate, layout
from boardwise.engines.generate import (
    LONG_NET_LABEL_UNITS,
    _DECOUPLING_HINTS,
    _decoupling_next_to_host,
    _is_capacitor_value,
    canvas_pin_offsets,
    generate_plan,
)
from boardwise.engines.layout import Placement, Rect, RoutedNet
from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

GOLDEN = "tests/fixtures/ch340_golden.epro2"


def _module_source(module) -> str:
    """The module's prose with its line layout folded away.

    A docstring/comment claim is load-bearing in this repo, and a claim is about
    a *sentence*: the comment leaders have to go as well as the wrapping, or a
    sentence that wraps gets a stray ``#:`` in its middle and the test would be
    pinning the layout instead of the claim.
    """
    text = re.sub(r"(?m)^[ \t]*#:?[ \t]?", " ", inspect.getsource(module))
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------
# shared boards
# --------------------------------------------------------------------------


def _two_part_model() -> tuple[DesignModel, dict]:
    """U1 + R1 on a signal net and a ground rail — the review's toy board."""
    components = {
        "U1": Component(uid="u1", designator="U1", pins=[
            Pin(number="1", name="1", net="SIG"),
            Pin(number="2", name="2", net="GND"),
        ]),
        "R1": Component(uid="r1", designator="R1", value="1K", footprint="0603", pins=[
            Pin(number="1", name="1", net="SIG"),
            Pin(number="2", name="2", net="GND"),
        ]),
    }
    nets = {
        "SIG": Net(name="SIG", pins=[("U1", "1"), ("R1", "1")]),
        "GND": Net(name="GND", pins=[("U1", "2"), ("R1", "2")]),
    }
    offsets = {
        "U1": {"1": (0.0, 0.0), "2": (0.0, 60.0)},
        "R1": {"1": (60.0, 0.0), "2": (60.0, 60.0)},
    }
    return DesignModel(components=components, nets=nets), offsets


def _pinless_row_board():
    """A bounded part, a part with no offsets at all, and a second bounded one.

    The shape ``_widen_gaps`` mislaid: a pin-less part *in the middle* of a row,
    where ``previous is None`` does not hold.
    """
    count = 5
    left = [Pin(number=str(i + 1), name=str(i + 1), net=f"N{i + 1}") for i in range(count)]
    right = [Pin(number=str(i + 1), name=str(i + 1), net=f"N{i + 1}") for i in range(count)]
    components = {
        "U": Component(uid="u", designator="U", pins=left),
        "LOGO": Component(uid="logo", designator="LOGO", pins=[]),
        "V": Component(uid="v", designator="V", pins=right),
    }
    model = DesignModel(components=components)
    for i in range(count):
        model.nets[f"N{i + 1}"] = Net(
            name=f"N{i + 1}", pins=[("U", str(i + 1)), ("V", str(i + 1))]
        )
    offsets = {
        "U": {str(i + 1): (80.0, float(i * 20)) for i in range(count)},
        "V": {str(i + 1): (0.0, float(100 + i * 20)) for i in range(count)},
    }
    return model, offsets


@pytest.fixture(scope="module")
def golden_auto_plan():
    """One golden plan, built once: the solver path is ~45 s per call."""
    model = build_schematic_model(GOLDEN)
    offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
    return model, generate_plan(model, offsets)


# --------------------------------------------------------------------------
# D1 — the solver path validated the router's candidate, not the drawn anchor
# --------------------------------------------------------------------------


def test_a_moved_label_is_measured_where_it_is_drawn(monkeypatch):
    """D1: the gate must measure the anchor the plan *draws*.

    ``auto`` hands a signal name to ``layout.clear_label_point``, which may
    return a different point from ``route.attach``; the plan used to report
    violations measured at ``attach``, so the drawn anchor was checked by
    nobody. Here the search is forced to return an anchor that is *off* the
    wire — under the old wiring nothing could see that, because the point
    measured was ``attach`` (which the router always puts on its wire).
    """
    model, offsets = _two_part_model()
    monkeypatch.setattr(generate, "needs_signal_label", lambda route, **kw: (True, "test"))
    off_wire = (7.0, 700.0)
    monkeypatch.setattr(layout, "clear_label_point", lambda *a, **k: (off_wire, ""))

    plan = generate_plan(model, offsets, strategy="auto")
    moved = [step for step in plan.net_names if step.net == "SIG"]
    assert moved and (moved[0].x, moved[0].y) == off_wire, "the search did not move it"
    codes = {v.code for v in plan.violations}
    assert "FLAG_NOT_ON_WIRE" in codes, (
        "the drawn anchor is off its wire and nothing reported it: "
        f"{sorted(codes)}"
    )


def test_the_drawn_anchor_is_held_to_the_same_clearance_ruler():
    """D1: constraints 4/5 for a given anchor, one implementation."""
    model = DesignModel(
        components={"U1": Component(uid="u", designator="U1", pins=[
            Pin(number="1", name="1", net="A")])},
        nets={"A": Net(name="A", pins=[("U1", "1")])},
    )
    routes = [RoutedNet(net="A", polylines=[[(0.0, 0.0), (100.0, 0.0)]], kind="port")]
    pins = {("U1", "1"): (0.0, 0.0)}
    # a foreign part whose box starts 15 units past the wire's end
    near = [Placement("R9", 0.0, 0.0, Rect(115.0, -10.0, 155.0, 10.0))]
    far = [Placement("R9", 0.0, 0.0, Rect(125.0, -10.0, 165.0, 10.0))]

    too_close = layout.annotation_anchor_violations(model, routes, near, [("A", 100.0, 0.0)])
    assert [v.code for v in too_close] == ["LABEL_TOO_CLOSE"], too_close
    # exactly LABEL_CLEARANCE away is clean: the ruler is strict
    assert layout.annotation_anchor_violations(model, routes, far, [("A", 100.0, 0.0)]) == []
    # and an anchor off its own wire is never forgiven — here it is also 145
    # units from the foreign box, so the *only* finding is the floating one
    off = layout.annotation_anchor_violations(model, routes, near, [("A", 300.0, 0.0)])
    assert {v.code for v in off} == {"FLAG_NOT_ON_WIRE"}, off

    # validate_full measures with the same function, not a second copy of it
    attach_inside = [RoutedNet(net="A", polylines=[[(0.0, 0.0), (100.0, 0.0)]],
                               attach=(100.0, 0.0), kind="port")]
    codes = {
        v.code
        for v in layout.validate_full(model, near, attach_inside, pins)
    }
    assert "LABEL_TOO_CLOSE" in codes


def test_the_finished_golden_plan_passes_the_annotation_rulers(golden_auto_plan):
    """D1 on the real board: the anchors the solver draws are clean.

    This is a *measurement*, not a promise: on the golden board the four naming
    steps the solver places (three rail flags and one long signal name) all sit
    on their own wires and clear of every foreign box, so wiring both rulers
    into ``plan.violations`` adds no row here — which is exactly why the hole
    could live this long. The point is that it now *would* report one.
    """
    _model, plan = golden_auto_plan
    codes = {v.code for v in plan.violations}
    annotation_codes = {
        code for code in codes
        if code.startswith("LABEL_") or code in {"FLAG_NOT_ON_WIRE", "NO_ATTACH_POINT"}
    }
    assert not annotation_codes, sorted(annotation_codes)
    assert plan.net_names, "the golden board has rails to flag"
    for step in plan.net_names:
        assert any(
            layout._point_on_segment((step.x, step.y), seg)
            for wire in plan.wires if wire.net == step.net
            for seg in [
                layout.Segment(ax, ay, bx, by, wire.net)
                for (ax, ay), (bx, by) in zip(wire.points, wire.points[1:])
            ]
        ), f"{step.kind} {step.net} is not on its net's wire"


# --------------------------------------------------------------------------
# D2 — a netlist pin with no known position was dropped in total silence
# --------------------------------------------------------------------------


def _unknown_position_board():
    components = {
        "U": Component(uid="u", designator="U", pins=[
            Pin(number="1", name="1", net="SIG"),
            Pin(number="2", name="2", net="SIG"),
            Pin(number="3", name="3", net="SIG"),  # netlist member, no offset
        ]),
        "R": Component(uid="r", designator="R", pins=[
            Pin(number="1", name="1", net="SIG"),
            Pin(number="2", name="2", net=None),   # a genuine NC pin, for contrast
        ]),
    }
    nets = {"SIG": Net(name="SIG", pins=[("U", "1"), ("U", "2"), ("U", "3"), ("R", "1")])}
    offsets = {"U": {"1": (0.0, 0.0), "2": (0.0, 30.0)},
               "R": {"1": (200.0, 0.0), "2": (200.0, 30.0)}}
    return DesignModel(components=components, nets=nets), offsets


def test_a_pin_the_plan_cannot_place_is_disclosed_not_silently_dropped():
    """D2: "we could not draw it" must not read as "left open on purpose"."""
    model, offsets = _unknown_position_board()
    plan = generate_plan(model, offsets)

    assert ("U", "3") in plan.unplaced_pins
    assert ("U", "3") not in plan.nc_pins, "unplaced is not the same as left open"
    assert ("R", "2") in plan.nc_pins, "the genuine NC pin stays where it was"
    assert any("U.3" in note for note in plan.notes), plan.notes
    assert any("UNPLACED" in note for note in plan.notes), plan.notes
    # disclosure, not a verdict: the plan is not made undrawable by it
    assert "NET_UNROUTABLE" not in {v.code for v in plan.violations}


def test_a_net_nothing_was_drawn_for_is_named_in_the_notes():
    """D2's family: a whole net can vanish the same way, one level up."""
    components = {
        "U": Component(uid="u", designator="U", pins=[
            Pin(number="1", name="1", net="N1"), Pin(number="2", name="2", net="N2")]),
        "R": Component(uid="r", designator="R", pins=[
            Pin(number="1", name="1", net="N1"), Pin(number="2", name="2", net="N2")]),
    }
    nets = {
        "N1": Net(name="N1", pins=[("U", "1"), ("R", "1")]),
        # N2's members exist in the netlist but only one of them can be placed
        "N2": Net(name="N2", pins=[("U", "2"), ("R", "2")]),
    }
    offsets = {"U": {"1": (0.0, 0.0)}, "R": {"1": (100.0, 0.0), "2": (100.0, 30.0)}}
    plan = generate_plan(DesignModel(components=components, nets=nets), offsets)
    assert ("U", "2") in plan.unplaced_pins
    assert any("net N2 is in the netlist but nothing was drawn" in n for n in plan.notes), plan.notes


def test_the_golden_page_discloses_nothing_because_it_dropped_nothing(golden_auto_plan):
    """D2's honesty check on the real board: no false alarms."""
    _model, plan = golden_auto_plan
    assert plan.unplaced_pins == []
    assert not [n for n in plan.notes if "UNPLACED" in n or "no known pins" in n]


# --------------------------------------------------------------------------
# D3 — the widened page parked a pin-less part flush against its neighbour
# --------------------------------------------------------------------------


def test_a_pinless_part_keeps_its_aisle_on_the_widened_page():
    """D3: ``_pack`` gives it ``COL_AISLE``; ``_widen_gaps`` gave it zero."""
    model, offsets = _pinless_row_board()
    order = ["U", "LOGO", "V"]
    exits = layout.net_exits(model, offsets)
    plain = {p.designator: p for p in layout.plan_placement(offsets, order)}
    widened = {
        p.designator: p
        for p in layout.plan_placement(offsets, order, exits=exits)
    }

    assert plain["LOGO"].bbox is None and widened["LOGO"].bbox is None
    u_edge = plain["U"].bbox.x1
    assert widened["LOGO"].x == plain["LOGO"].x, (
        "a pin-less part is not something a wider aisle may rearrange"
    )
    assert widened["LOGO"].x - u_edge >= layout.COL_AISLE, (
        f"pin-less part at {widened['LOGO'].x} is flush on U's box edge {u_edge}"
    )
    # and the aisle that needed the room went to the pair that asked for it
    assert widened["V"].x - widened["LOGO"].x > plain["V"].x - plain["LOGO"].x


@pytest.mark.parametrize("first_is_pinless", [True, False])
def test_two_pinless_parts_keep_their_own_spacing(first_is_pinless):
    """D3's family: the branch must hold at the row start and mid-row."""
    model, offsets = _pinless_row_board()
    offsets = dict(offsets)
    if first_is_pinless:
        order = ["LOGO", "U", "V"]
    else:
        offsets["LOGO2"] = {}
        model.components["LOGO2"] = Component(uid="logo2", designator="LOGO2", pins=[])
        order = ["U", "LOGO", "LOGO2", "V"]
    exits = layout.net_exits(model, offsets)
    plain = {p.designator: p for p in layout.plan_placement(offsets, order)}
    widened = {p.designator: p for p in layout.plan_placement(offsets, order, exits=exits)}
    for designator in order:
        if plain[designator].bbox is not None:
            continue
        assert widened[designator].x == plain[designator].x, (
            f"{designator} moved from {plain[designator].x} to "
            f"{widened[designator].x} on the widened page"
        )
    # a pin-less part still leaves the base aisle to the part after it in the
    # plain page, and the two pages agree about that too
    for left, right in zip(order, order[1:]):
        if plain[left].bbox is not None or plain[right].bbox is not None:
            continue
        assert widened[right].x - widened[left].x == plain[right].x - plain[left].x


# --------------------------------------------------------------------------
# D4 — the threshold's unit was wrong by 10x in the load-bearing comment
# --------------------------------------------------------------------------


def test_the_thresholds_are_stated_in_the_canvas_unit():
    """D4: one canvas unit is 10 mil; the arithmetic has to match.

    The **number** is 岳's (it is pinned unchanged below); what was wrong is the
    sentence around it, which read "1 unit = 1 mil = 0.0254 mm" and made every
    figure derived from it 10x too small — including "1500 mil is ~38 mm", which
    was the ruling's own justification.
    """
    assert LONG_NET_LABEL_UNITS == 1500.0, "a unit fix must not move the policy"
    mil = 0.0254  # mm per mil
    assert round(LONG_NET_LABEL_UNITS * 10 * mil, 1) == 381.0
    assert round(layout.WIRE_CLEARANCE * 10 * mil, 2) == 2.54

    for module in (generate, layout):
        source = _module_source(module)
        assert "1 unit = 1 mil" not in source, module.__name__
        assert "10 mil" in source, module.__name__


# --------------------------------------------------------------------------
# D5 — the price map's documented invariant was false
# --------------------------------------------------------------------------


def test_the_price_map_documents_first_writer_wins():
    """D5: the map keeps the *first* wire's ring, not the nearest one.

    The sentence is what 137's numbers rest on, so it is the thing pinned: the
    old text claimed ``setdefault`` keeps the nearest wire's ring, which the
    incremental build makes impossible (the golden board has 6258 cells priced
    one ring too cheap because of it). The pricing itself is deliberately
    untouched — correcting it measures *worse* (34 -> 35 findings), and that is
    recorded in the comment this test reads.
    """
    source = _module_source(layout)
    assert "first-writer-wins" in source
    assert "keeps the *nearest* wire's ring" not in source
    assert "6258" in source, "the measurement behind the claim has to stay visible"
    assert "34 to **35**" in source


# --------------------------------------------------------------------------
# D6 — OUT_OF_SHEET measured the whole sheet, not the frame it documents
# --------------------------------------------------------------------------


def test_a_box_in_the_sheet_frame_margin_is_out_of_sheet():
    """D6: FRAME is a keep-out; the default ruler is now the inset sheet."""
    model = DesignModel()
    on_the_edge = [Placement("U1", 0.0, 0.0, Rect(0.0, 0.0, 100.0, 200.0))]
    codes = {v.code for v in layout.validate_full(model, on_the_edge, [], {})}
    assert "OUT_OF_SHEET" in codes

    # exactly on the frame is legal (the comparison is strict), just inside it is not
    at_frame = [Placement("U1", 0.0, 0.0,
                          Rect(layout.FRAME, layout.FRAME,
                               layout.SHEET_WIDTH - layout.FRAME, 200.0))]
    assert "OUT_OF_SHEET" not in {
        v.code for v in layout.validate_full(model, at_frame, [], {})
    }
    just_over = [Placement("U1", 0.0, 0.0,
                           Rect(layout.FRAME, layout.FRAME,
                                layout.SHEET_WIDTH - layout.FRAME + 5.0, 200.0))]
    assert "OUT_OF_SHEET" in {
        v.code for v in layout.validate_full(model, just_over, [], {})
    }

    # a caller that measured the page itself still overrides the default
    assert "OUT_OF_SHEET" not in {
        v.code
        for v in layout.validate_full(
            model, on_the_edge, [], {},
            frame=Rect(0.0, 0.0, layout.SHEET_WIDTH, layout.SHEET_HEIGHT),
        )
    }


def test_a_widened_row_that_lands_in_the_old_blind_band_is_reported():
    """D6's real scenario: ``_widen_gaps`` delegates this check here."""
    found = None
    for n_boxes in range(3, 10):
        for width in range(50, 260, 5):
            model, offsets = _crowded_row_board(n_boxes, float(width))
            order = [f"B{i}" for i in range(n_boxes)]
            plain = layout.plan_placement(offsets, order)
            if len({p.y for p in plain}) != 1:
                continue
            if any(p.bbox and p.bbox.x1 > layout.SHEET_WIDTH - layout.FRAME
                   for p in plain):
                continue
            exits = layout.net_exits(model, offsets)
            widened = layout.plan_placement(offsets, order, exits=exits)
            band = [
                p for p in widened
                if p.bbox
                and layout.SHEET_WIDTH - layout.FRAME
                < p.bbox.x1
                <= layout.SHEET_WIDTH
            ]
            if band:
                found = (model, widened, band)
                break
        if found:
            break
    assert found is not None, "no configuration in the scanned range enters the band"
    model, widened, band = found
    codes = {v.code for v in layout.validate_full(model, widened, [], {})}
    assert "OUT_OF_SHEET" in codes, (
        f"{[p.designator for p in band]} sits in the frame margin and the gate "
        "says clean"
    )


def _crowded_row_board(n_boxes: int, w: float, demand: int = 5):
    """``n_boxes`` boxes of width ``w``, each pair facing ``demand`` nets."""
    components, nets, offsets = {}, {}, {}
    for i in range(n_boxes):
        components[f"B{i}"] = Component(uid=f"b{i}", designator=f"B{i}", pins=[])
        offsets[f"B{i}"] = {}
    for i in range(n_boxes):
        for k in range(demand):
            components[f"B{i}"].pins.append(
                Pin(number=str(k + 1), name=str(k + 1), net=f"N{i}_{k}")
            )
            offsets[f"B{i}"][str(k + 1)] = (w - 40.0, float(k * 20))
        if i + 1 < n_boxes:
            for k in range(demand):
                components[f"B{i + 1}"].pins.append(
                    Pin(number=str(100 + k), name=str(100 + k), net=f"N{i}_{k}")
                )
                offsets[f"B{i + 1}"][str(100 + k)] = (0.0, float(k * 20))
    for i in range(n_boxes - 1):
        for k in range(demand):
            nets[f"N{i}_{k}"] = Net(
                name=f"N{i}_{k}",
                pins=[(f"B{i}", str(k + 1)), (f"B{i + 1}", str(100 + k))],
            )
    return DesignModel(components=components, nets=nets), offsets


# --------------------------------------------------------------------------
# D7 — the note contradicted itself and the strategy
# --------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["text", "label"])
def test_the_note_blames_the_strategy_it_actually_used(strategy):
    """D7: ``text``/``label`` name every signal net, so "because short" is a lie."""
    model, offsets = _two_part_model()
    plan = generate_plan(model, offsets, strategy=strategy)
    notes = [n for n in plan.notes if n.startswith("net SIG is named because")]
    assert notes, plan.notes
    assert f"strategy {strategy} names every signal net" in notes[0]
    assert "read it off the wires" not in notes[0]


def test_the_auto_note_still_quotes_the_auto_answer():
    """D7's other half: the ``auto`` wording is the ruled one and stays."""
    model, offsets = _two_part_model()
    plan = generate_plan(model, offsets, strategy="auto")
    assert not [n for n in plan.notes if "is named because" in n], (
        "a short single-page signal net is read off its wires under auto"
    )


# --------------------------------------------------------------------------
# D8 — ``none`` claims "no names at all" while flagging the rails
# --------------------------------------------------------------------------


def test_none_names_no_signal_net_and_still_flags_the_rails():
    """D8: the behaviour was argued for; the docstring was the stale sentence."""
    model, offsets = _two_part_model()
    plan = generate_plan(model, offsets, strategy="none")
    kinds = {step.kind for step in plan.net_names}
    assert kinds == {"Ground"}, kinds
    assert not [s for s in plan.net_names if s.net == "SIG"]


def test_the_strategy_table_says_what_none_does_not_do():
    """D8: the enum's own documentation must match the code beside it."""
    source = _module_source(generate)
    assert "no signal name primitive" in source
    assert "wires only, no names at all" not in source


# --------------------------------------------------------------------------
# D9 — two module headers disagreed about the y axis
# --------------------------------------------------------------------------


def test_the_layout_header_states_the_measured_y_axis():
    """D9: canvas y grows *upward*; this module converts nothing."""
    source = _module_source(layout)
    assert "y grows upward" in source
    assert "y grows downward" not in source
    assert "TITLE_BLOCK" in source and "bottom-left" in source


def test_the_generate_header_points_at_the_boundary_not_a_conversion():
    """D9: the parser negates once; ``canvas_pin_offsets`` is an identity."""
    source = _module_source(generate)
    assert "the one conversion point" not in source
    assert "identity" in source
    raw = {"U1": {"1": (1.0, 2.0)}}
    assert canvas_pin_offsets(raw) == raw


# --------------------------------------------------------------------------
# D10 — the decoupling hint was case-sensitive; the reader it claims is not
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("100nF", True), ("100NF", True), ("100nf", True),
        ("0.1uF", True), ("0.1UF", True), ("22pF", True), ("22PF", True),
        ("22μF", True), ("22µF", True),          # Greek mu and the micro sign
        ("4u7", True), ("2n2", True),            # the trade's mid-letter notation
        ("5.1K", False), ("10R", False), ("", False), ("0603", False),
    ],
)
def test_the_decoupling_hint_uses_the_rule_engines_own_reader(value, expected):
    """D10: one ruler — the hint must not know fewer spellings than the rules."""
    assert _is_capacitor_value(value) is expected


def test_a_cap_spelled_in_upper_case_is_placed_next_to_its_host():
    """D10's consequence: the ordering hint, not just the predicate."""
    for value in ("100nF", "100NF", "0.1UF", "4u7"):
        components = {
            "U": Component(uid="u", designator="U", pins=[
                Pin(number="1", name="1", net="VCC"), Pin(number="2", name="2", net="SIG")]),
            "C1": Component(uid="c1", designator="C1", value=value, footprint="0603", pins=[
                Pin(number="1", name="1", net="VCC"), Pin(number="2", name="2", net="GND")]),
        }
        nets = {
            "VCC": Net(name="VCC", pins=[("U", "1"), ("C1", "1")]),
            "SIG": Net(name="SIG", pins=[("U", "2")]),
            "GND": Net(name="GND", pins=[("C1", "2")]),
        }
        model = DesignModel(components=components, nets=nets)
        assert _decoupling_next_to_host(model, "U") == {"C1"}, value


def test_the_hint_constant_is_pinned_to_the_readers_unit_table():
    """D10's other family member: a hint list cannot drift from the reader."""
    assert set(_DECOUPLING_HINTS) <= set(_CAP_UNITS)
