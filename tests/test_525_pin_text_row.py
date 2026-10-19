"""525: the search finally sees the text rows it has to keep pin tips out of.

The defect these tests pin: `part_box` is "drawn body + every pin tip" and
carries no texts, so a layout could keep every body box apart, keep all 33
relations, and still have a neighbour's **value row** land on a pin tip. The
router's `_blocked_points` treats that tip as a wall, so the net owning it was
refused however the parts were arranged — measured 2026-10-19, 21 of 21 buried
tips sat inside another part's value row.

The measurements are `experiments/textfit/` (the CP-SAT replay) and
`experiments/pintext/probe.py` (the annealing round, `pin-text` 0.0 with every
relation kept).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.core.textmetrics import render_width
from boardwise.engines import drawcompiler as dc
from boardwise.engines import placement as pl

SPECS = Path(__file__).resolve().parents[1] / "blocklib" / "specs"


def _library_from(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for item in raw["profiles"]:
        profile = SymbolProfile.from_dict(item)
        out[profile.symbol_ref] = profile
    return out


def _flyback_request() -> pl.PlacementInput:
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    )
    ctx = prepared.context
    assert ctx is not None
    parts = []
    for part_id in sorted(ctx.slots):
        parts.append(pl.PlacementPart(
            part_id=part_id, profile=ctx.profile(part_id),
            poses=tuple(ctx.accepted[part_id]),
            value=(ctx.circuit.part(part_id).value
                   if ctx.circuit.part(part_id) is not None else ""),
        ))
    nets = tuple(
        pl.PlacementNet(
            net_id=net.id,
            members=tuple(
                (member.partition(".")[0], member.partition(".")[2])
                for member in net.members
            ),
            cls=net.cls,
        )
        for net in circuit.nets
    )
    relations = tuple(
        pl.PlacementRelation(kind=item.kind, subject=item.subject,
                             object=item.object, reason=item.reason)
        for item in ctx.binding.constraints
    )
    return pl.PlacementInput(
        parts=tuple(parts), nets=nets, relations=relations,
        progress=ctx.progress, lateral=ctx.lateral(),
        page_box=ctx.budget.page_box, keepouts=tuple(ctx.budget.keepouts),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        channel=ctx.budget.channel, lane=ctx.budget.lane,
    )


def _state(request: pl.PlacementInput) -> pl._State:
    seed = pl._seed(request, pl._ranks(request.relations, request.part_ids()))
    return seed


def test_the_two_text_row_heights_agree():
    """The row this module prices must be the row the compiler draws.

    A taller box here prices a collision no reader can see (the 146 mistake,
    mirrored); a shorter one misses the burial that stopped the router.
    """
    assert pl.TEXT_ROW_HEIGHT == dc.TEXT_ROW_HEIGHT == 10.0


def test_a_value_row_is_the_hosts_own_box():
    """Anchor offset, width and height all come from the host's model."""
    request = _flyback_request()
    part = request.part("R7")
    declared = [item for item in part.profile.texts if item.kind == "value"]
    assert declared, "R7 must declare a value row for this test to mean anything"
    origin = (100.0, 50.0)
    rows = [row for row in pl.text_rows(request, "R7", origin) if row[0] == "value"]
    assert len(rows) == 1
    kind, text, box = rows[0]
    assert text == part.value == "17.8k 1% TH"
    assert box[0] == pytest.approx(origin[0] + declared[0].x)
    assert box[1] == pytest.approx(origin[1] + declared[0].y)
    assert box[2] - box[0] == pytest.approx(render_width(text))
    assert box[3] - box[1] == pytest.approx(pl.TEXT_ROW_HEIGHT)


def test_a_part_that_declares_no_row_contributes_none():
    """Every pre-146 library states no anchors, and must compile as it did."""
    request = _flyback_request()
    origin = (0.0, 0.0)
    silent = [part for part in request.parts
              if not pl.text_rows(request, part.part_id, origin)]
    assert not silent, (
        "the flyback library states anchors for every part; a silent part here "
        "means the model stopped reading SymbolProfile.texts"
    )


def test_the_term_is_absent_unless_the_request_turns_it_on():
    """Off by default: the ladder's pages keep their cost list byte for byte."""
    request = _flyback_request()
    state = _state(request)
    names = [term.name for term in pl.evaluate(request, state)]
    assert "pin-text" not in names
    asked = request.__class__(**{**request.__dict__, "pin_text": True})
    names = [term.name for term in pl.evaluate(asked, state)]
    assert "pin-text" in names


def test_a_tip_inside_another_parts_row_is_priced_and_outside_is_not():
    """The measured defect, in one layout: put a tip in a row and the term wakes.

    R7 states a value row; R9's first pin is driven onto that row's centre. The
    term must charge it, and must release it when the part moves one row clear.
    """
    request = _flyback_request()
    state = _state(request)
    host, guest = "R7", "R9"
    box = next(
        row[2] for row in pl.text_rows(request, host, state.origins[host])
        if row[0] == "value"
    )
    centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    pose = state.poses[guest]
    pin = request.part(guest).profile.pins[0]
    offset = pl.posed_tip(pin.tip, pose, (0.0, 0.0))
    buried = (
        centre[0] - offset[0],
        centre[1] - offset[1],
    )
    state.origins[guest] = buried
    term = pl._pin_text_term(request, state, pl._pins_of(request, state))
    assert term.name == "pin-text"
    assert term.value == pytest.approx(
        min(box[2] - box[0], box[3] - box[1]) / 2.0 + pl.PIN_TEXT_EDGE,
        abs=1e-6,
    ), term.detail
    assert guest in term.detail

    state.origins[guest] = (buried[0], buried[1] + 3 * pl.TEXT_ROW_HEIGHT)
    term = pl._pin_text_term(request, state, pl._pins_of(request, state))
    assert term.value == pytest.approx(0.0)


def test_a_tip_on_a_rows_edge_still_counts():
    """The edge is where the router's wall is, so it cannot be "free".

    `_Router._wall` reads `box0 - 1e-6 < x < box2 + 1e-6` — the far edge is
    inside the wall — so a tip exactly on a row's edge cannot receive a wire end.
    A depth of 0 there would leave the search no gradient at all
    (:data:`pl.PIN_TEXT_EDGE`).
    """
    request = _flyback_request()
    state = _state(request)
    host, guest = "R7", "R9"
    box = next(
        row[2] for row in pl.text_rows(request, host, state.origins[host])
        if row[0] == "value"
    )
    pose = state.poses[guest]
    pin = request.part(guest).profile.pins[0]
    offset = pl.posed_tip(pin.tip, pose, (0.0, 0.0))
    # the row's own lower-left corner, which is on two of its edges
    on_edge = (box[0] - offset[0], box[1] - offset[1])
    state.origins[guest] = on_edge
    term = pl._pin_text_term(request, state, pl._pins_of(request, state))
    # One charge per (tip, row) pair the corner sits on: the corner is on two
    # edges of the value row, and the guest's second tip or the host's reference
    # row may land on it too, so this is a floor, not an equality.
    assert term.value >= pl.PIN_TEXT_EDGE, term.detail
    assert guest in term.detail, term.detail


def test_a_part_may_lie_in_its_own_row():
    """A symbol's own anchors over its own tips are the library's business.

    C5 declares one legal pose and its own value row already covers its own tip;
    pricing that is infeasible on the request's own terms
    (`experiments/textfit/self_burial.txt`).
    """
    request = _flyback_request()
    part = request.part("C5")
    origin = (0.0, 0.0)
    pose = part.poses[0]
    rows = pl.text_rows(request, "C5", origin)
    assert rows, "C5 must declare a row"
    covered = [
        pin.number for pin in part.profile.pins
        for row in rows
        if (lambda box, tip: box[0] <= tip[0] <= box[2] and box[1] <= tip[1] <= box[3])(
            row[2], pl.posed_tip(pin.tip, pose, origin)
        )
    ]
    assert covered, (
        "this test's premise is that C5's own row touches its own tip (`C5.1` "
        "sits on the row's own lower edge, experiments/textfit/self_burial.txt); "
        "if the library changed, the exemption is still right and this assertion "
        "is what has to move"
    )
    state = pl._State(origins={p.part_id: (0.0, 0.0) for p in request.parts},
                      poses={p.part_id: p.poses[0] for p in request.parts})
    term = pl._pin_text_term(request, state, pl._pins_of(request, state))
    charged = [number for number in covered if f"C5.{number}" in term.detail]
    assert not charged, term.detail
