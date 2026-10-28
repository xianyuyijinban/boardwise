"""534 r22 — the final label re-seat: the trigger, the bound, and the silence.

The pass exists because a bare label's box is chosen inside the per-net loop
(:func:`drawcompiler._label_at`) and therefore sees only the conductors laid
*before its own net's turn*: the `ch343_power` island's `V3` box dodged the GND
run it could see and landed on the VCC lead laid later in that same loop. The
gate refused the drawing (`text-on-wire … for 14 units`). Field evidence:
`.tmp_534/final-label-reseat-r1/verify.txt`, whose `reseat=off` module fails on
exactly that violation and whose `reseat=on` module is `ok=True` with no label
pierced.

Four facts are pinned here, each one a way the pass could quietly stop working:

1. **The trigger is any positive penetration.** Half a unit of a foreign
   conductor inside the box is enough; a conductor that only *touches* the
   outline (zero-length interior run) is not — the same interior test the gate
   uses (`router._segment_hits_box`). An eight-unit chord must not be needed to
   wake this pass up.
2. **The anchor does not move.** Only the box is typography; `(x, y)` is the
   electrical fact a label joins, and a re-seat that moved it would rename a
   different node.
3. **The bound is a named refusal.** `NAME_ESCAPE_ROUNDS` is finite; when the
   last round still leaves a pierced box the pass returns a `layout-unsat`
   naming it — never `None`. The old tail returned `None` after the loop, which
   would have handed the gate the very drawing this pass exists to refuse.
4. **A clean picture is byte-identical.** A label with nothing through it is not
   re-decided, so `bbox`, `occupied`, `solids` and the router walls are untouched
   — a page this pass has nothing to say about cannot move.

Plus the page-level reading the batch ships on: the shipped four-island sheet's
`V3` name carrier is **horizontal** (S-20; `textmetrics.wire_name_row` on the
carrier's own polyline), and no label on that page is left with a foreign
conductor through its box.
"""

from __future__ import annotations

import functools
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutLabel, LayoutSegment
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.textmetrics import (
    WIRE_NAME_AXIS_HORIZONTAL,
    wire_name_row,
)
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler

DRAWCOMPILER = pathlib.Path(dc.__file__)


class _Ctx:
    """The two readings the re-seat makes of a context: no part, no flag book."""

    book: dict = {}

    def profile(self, part_id: str):
        return None


class _Router:
    """Only the two lists the pass keeps in step: the walls it hands the router."""

    def __init__(self) -> None:
        self.flag_walls: list = []
        self.boxes: list = []


def _label(net: str = "V3", bbox=(0.0, -5.0, 10.0, 5.0)) -> LayoutLabel:
    return LayoutLabel(net=net, text=net, bbox=bbox, x=0.0, y=0.0, part_id="")


def _reseat(labels, segments, occupied=None, solids=None, router=None):
    occupied = [] if occupied is None else occupied
    solids = [] if solids is None else solids
    router = _Router() if router is None else router
    if not router.boxes:
        router.boxes = [*solids]
    failure = dc._reseat_crossed_labels(
        _Ctx(), None, segments, labels, (), occupied, solids, router,
    )
    return failure, occupied, solids, router


def test_half_a_unit_of_a_foreign_conductor_is_enough():
    """A sub-unit chord through the box wakes the pass (the gate's own interior test)."""
    label = _label()
    segment = LayoutSegment(net="VCC", points=[(-20.0, 0.0), (0.5, 0.0)])
    assert dc._foreign_runs_through(label.bbox, label.net, [segment]) == ["VCC"]

    # The real call hands in the label's own box as both an obstacle and a wall.
    failure, occupied, solids, router = _reseat(
        [label], [segment], occupied=[label.bbox], solids=[label.bbox])

    assert failure is None, failure.detail if failure else ""
    assert dc._foreign_runs_through(label.bbox, "V3", [segment]) == []
    assert label.bbox != (0.0, -5.0, 10.0, 5.0), "the pierced box was kept"
    # The anchor is the electrical fact and does not move with the box.
    assert (label.x, label.y) == (0.0, 0.0)
    # One sourced picture: the router walls are `solids` (+ flag walls).
    assert solids == [label.bbox]
    assert router.boxes == [*solids, *router.flag_walls]


def test_a_conductor_that_only_touches_the_outline_is_not_penetration():
    """Zero-length interior run: adjacent ink, not a cut — the box stays put."""
    label = _label()
    segment = LayoutSegment(net="VCC", points=[(-20.0, 0.0), (0.0, 0.0)])
    assert dc._foreign_runs_through(label.bbox, "V3", [segment]) == []

    failure, _occupied, solids, _router = _reseat([label], [segment])

    assert failure is None
    assert label.bbox == (0.0, -5.0, 10.0, 5.0)
    assert solids == []


def test_the_labels_own_net_may_ride_through_its_box():
    """A name carrier's own wire is what the label is for, not a collision."""
    label = _label()
    segment = LayoutSegment(net="V3", points=[(-20.0, 0.0), (20.0, 0.0)])
    assert dc._foreign_runs_through(label.bbox, "V3", [segment]) == []

    failure, _occupied, _solids, _router = _reseat([label], [segment])

    assert failure is None
    assert label.bbox == (0.0, -5.0, 10.0, 5.0)


def test_an_untouched_label_is_byte_identical():
    """Nothing pierced → nothing rewritten: boxes, obstacle lists and walls stay."""
    clean = _label("V3")
    other = _label("GND", (-40.0, -5.0, -30.0, 5.0))
    segment = LayoutSegment(net="VCC", points=[(40.0, 0.0), (80.0, 0.0)])
    occupied = [clean.bbox, other.bbox]
    solids = [clean.bbox, other.bbox]
    router = _Router()
    router.boxes = [*solids]

    failure, out_occupied, out_solids, out_router = _reseat(
        [clean, other], [segment], list(occupied), list(solids), router)

    assert failure is None
    assert [item.bbox for item in (clean, other)] == [
        (0.0, -5.0, 10.0, 5.0), (-40.0, -5.0, -30.0, 5.0)]
    assert out_occupied == occupied
    assert out_solids == solids
    assert out_router.boxes == solids


def test_rounds_exhausted_names_the_pierced_label_instead_of_returning_none(monkeypatch):
    """`NAME_ESCAPE_ROUNDS` spent with a box still pierced is a named refusal."""
    label = _label()
    segment = LayoutSegment(net="VCC", points=[(-20.0, 0.0), (20.0, 0.0)])
    monkeypatch.setattr(dc, "NAME_ESCAPE_ROUNDS", 0)

    failure, _occupied, _solids, _router = _reseat([label], [segment])

    assert failure is not None, (
        "the ladder ran out of rounds with the box pierced and the pass "
        "returned None — a pierced row would be delivered")
    assert failure.category == dc.FAILURE_LAYOUT_UNSAT
    assert failure.subject == "labels[0]"
    assert "conductor through its box" in failure.detail
    assert "VCC" in failure.detail
    # Nothing was committed: a refused pass leaves the picture as it found it.
    assert label.bbox == (0.0, -5.0, 10.0, 5.0)


def test_a_box_with_no_legal_seat_is_a_named_refusal_not_a_none():
    """Every seat the ladder offers is itself pierced → named refusal, no delivery."""
    label = _label()
    # A wall of foreign runs on both compass axes, far enough out to cover the
    # first rungs in every direction.
    segments = [
        LayoutSegment(net="VCC", points=[(-200.0, 0.0), (200.0, 0.0)]),
        LayoutSegment(net="GND", points=[(0.0, -200.0), (0.0, 200.0)]),
        LayoutSegment(net="+5V", points=[(-200.0, 40.0), (200.0, 40.0)]),
        LayoutSegment(net="GND2", points=[(-200.0, -40.0), (200.0, -40.0)]),
        LayoutSegment(net="VCC2", points=[(40.0, -200.0), (40.0, 200.0)]),
        LayoutSegment(net="VCC3", points=[(-40.0, -200.0), (-40.0, 200.0)]),
    ]
    failure, _occupied, _solids, _router = _reseat([label], segments)

    assert failure is not None, "no free seat was found and the pass said None"
    assert failure.category == dc.FAILURE_LAYOUT_UNSAT
    assert failure.subject == "labels[0]"
    assert label.bbox == (0.0, -5.0, 10.0, 5.0)


def _four_island_sheet():
    root = pathlib.Path(__file__).resolve().parents[1]
    specs = root / "blocklib" / "specs"
    return (CircuitSpec.load(specs / "ch343_uart.circuit.json"),
            PresentationSpec.load(specs / "ch343_uart.presentation.json"),
            drawapply.load_library(specs / "ch343_uart.library.json"))


@functools.lru_cache(maxsize=1)
def _compiled_page():
    circuit, presentation, book = _four_island_sheet()
    result = pagecompiler.compile_page(
        circuit, presentation, book,
        pagecompiler.PageCompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)))
    assert result.pages, [item.detail for item in result.failures][:2]
    return result.pages[0].plan


def test_no_label_on_the_shipped_page_is_left_pierced():
    """The whole page, after every conductor exists: no name printed on a wire."""
    plan = _compiled_page()
    pierced = [
        f"{label.net}@{list(label.bbox)}<-{sorted(set(dc._foreign_runs_through(label.bbox, label.net, plan.segments)))}"
        for label in plan.labels
        if dc._foreign_runs_through(label.bbox, label.net, plan.segments)
    ]
    assert pierced == [], pierced


def test_v3_name_carrier_is_horizontal_on_the_shipped_page():
    """S-20 on the page's own geometry: V3's carriers name their wire flat.

    The page cannot place a net label at all (the host's `sch.place_netlabel` is
    unusable, 029), so the name is carried by the short stub `drawapply` stakes
    at the label's anchor — the wire the host will print the name on. Both V3
    carriers are measured here with :func:`textmetrics.wire_name_row`, the ruler
    the gate uses: the 5-unit straight stub is a one-run tie that `max` keeps
    horizontal, and the bent H-V carrier's longest run is its first, also
    horizontal.
    """
    plan = _compiled_page()
    circuit, presentation, book = _four_island_sheet()
    change_plan = drawapply.module_plan(
        plan, circuit, presentation, book,
        label_stubs=True, keep_names=True, module_label="page ch343_uart")
    change = change_plan.to_jsonable()["change"]
    carriers = [wire for wire in change["wires"] if wire.get("net") == "V3"]
    assert carriers, [wire.get("net") for wire in change["wires"]]
    rows = []
    for wire in carriers:
        row = wire_name_row([tuple(point) for point in wire["points"]], "V3")
        assert row is not None, wire
        rows.append((row.axis, wire["points"]))
    assert all(axis == WIRE_NAME_AXIS_HORIZONTAL for axis, _points in rows), rows
    # The straight stub is the one that sets the name down on the anchor itself.
    assert any(len(wire["points"]) == 2 for wire in carriers), carriers
