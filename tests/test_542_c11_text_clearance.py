"""542-C11: a part's text row must keep clear of every conductor.

The landed page (201H/532 lineage) put `SEC_12V`'s vertical run at ``x =
872.4402373472949`` and `C11`'s value row at ``(820, 75)-(872.4402373472949,
85)``: the run's x **is** the row's right edge, digit for digit.  Nothing is
printed through the row — `readability`'s `text-on-wire` measures penetration
against `TEXT_WIRE_PENETRATION = 10`, so a zero-width overlap is not a finding —
but the host lands the conductor at two decimals (the connector writes
``872.44``), which puts the wire 0.0002373 unit **inside** the text box, and the
host's own drawlint reports the chord.  Zero clearance is not a drawing.

Why the router produced it: `_detours` offers **every row's raw edges** as the
bend coordinates of a Z route (532's corridor between a row and a body), and
`_route`'s `text_hits` reads a conductor with `_crosses(..., margin=1.0)` — a
shared edge is not a crossing — so the route that runs exactly along a row's
edge scores zero on every text key *and* wins on `length` because hugging the
row is the shortest way round.

**The same rule catches a second row on the same page, and that is disclosed
here on purpose.**  `feedback`'s `FB_SENSE` left `R8.1` and ran at ``y = 370``,
which is the bottom edge of `U4`'s reference row ``(505, 360)-(514.1355811518324,
370)`` — zero clearance again, on the model and on the page alike.  The fix has
no per-part and no per-coordinate branch, so it moved that run to ``y = 372``
(gap 2.0) as well; the main agent accepted that as an explicit scope exception on
2026-10-27, and the tests below are what makes it carry a reading rather than a
promise.

The tests are the two halves of the fix and the readings that were missing:

* **the rows** — `C11`'s value row and `U4`'s reference row are still printed
  (no value is hidden), and the shortest distance from each to every run of the
  page is at least `TEXT_WIRE_CLEARANCE`, measured both on the model's
  coordinates and after the host's two-decimal landing;
* **the netlists** — `SEC_12V` is still one chain through `D3.1`, `C11.1` and
  `C13.1`, and `FB_SENSE` still ends on `R7.2`, `R8.1` and `U4.1`, i.e. the fix
  moved conductors and not connections;
* **the mechanism** — the router spends four units of length to keep two units of
  clearance (it must not be answered by a per-part coordinate);
* **the offer** — the detour family contains the **snapped** clearance
  coordinate on each of a row's four sides, pinned to the numbers, which is the
  half the old code did not have at all.

**What these tests are not.**  `islandlayout.TEXT_WIRE_CLEARANCE` is a router
preference plus a candidate offer, not a hard gate: every electrical key and
every `bends` slot outranks it, so a layout whose only clean route would buy a
bend, a short or a body crossing still lands its row closer than one unit.  The
smallest such case is a two-pin link whose only route is a one-bend L along a
row's edge — it keeps the edge and wins on `bends` against the clear Z routes
(the batch's review notes work it through with numbers).  So
nothing here asserts 「all layouts keep >= 1 unit」.  The page tests assert that
*measurement* — `C11`'s row, `U4`'s row, and the whole-page census that reads all
37 printed rows: each measures at least 2 units from every conductor (the two that
used to be at 0 are named too), on the model's coordinates and after the host's
two-decimal landing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: The decimals the connector lands a conductor at (the host wrote ``872.44`` for
#: a modelled ``872.4402373472949``): a clearance that only exists at full
#: precision is not a clearance on the page.
LANDING_DECIMALS = 2

#: The batch's target, stated as the test's own reading rather than borrowed from
#: the module: 「文字框与导体 >= 1 unit」.  The module publishes the number it
#: actually reserves beside a row (`TEXT_WIRE_CLEARANCE`, which may be larger);
#: the page tests check the knob is not *smaller* than this one, so a later batch
#: that shrank it would have to say so here rather than silently pass.
ROW_CLEARANCE = 1.0

#: The page's own floor, measured (not a rule): every one of the 37 printed rows on
#: the flyback page is at least this far from every conductor, on the model and as
#: landed.  Before 542 the two rows the batch names measured 0.0, and
#: `test_every_printed_row_on_the_page_keeps_two_units` is the census that carries
#: the sentence (`islandlayout.TEXT_WIRE_CLEARANCE` is a router preference, not a
#: guarantee — see that constant's own account of its limits).
PAGE_ROW_CLEARANCE = 2.0

#: How many rows the host prints for this page — `plan.texts`, fixed so a dropped
#: or hidden row cannot make the census above pass by measuring fewer rows.
PAGE_ROWS = 37

#: `secondary`'s output rail — the net whose run sat on `C11`'s value row.
SEC_12V_PINS = (("D3", "1"), ("C11", "1"), ("C13", "1"))

#: `feedback`'s chain, in the order 542-V1 reads it (`test_542_fb_sense_route.py`).
FB_SENSE_PINS = (("R7", "2"), ("R8", "1"), ("U4", "1"))


def _library(stem: str) -> dict[str, SymbolProfile]:
    payload = json.loads((SPECS / f"{stem}.library.json").read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


def _inputs():
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


@pytest.fixture(scope="module")
def page():
    """The real page, through the compiler entry the landed page used."""
    circuit, presentation, book = _inputs()
    result = dc.compile(
        circuit, presentation, book, dc.CompileBudget(max_candidates=64),
    )
    assert result.ok, [item.detail for item in result.failures]
    assert len(result.candidates) == 1, len(result.candidates)
    return result.candidates[0], circuit, book


# --------------------------------------------------------------- the readings


def _landed(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], LANDING_DECIMALS), round(point[1], LANDING_DECIMALS))


def _run_box(a: tuple[float, float], b: tuple[float, float]):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _runs(plan, landed: bool):
    """Every straight run of the page, as a box — optionally as the host lands it."""
    for segment in plan.segments:
        points = [_landed(point) for point in segment.points] if landed else [
            point for point in segment.points
        ]
        for index in range(len(points) - 1):
            yield segment.net, _run_box(points[index], points[index + 1])


def _row(plan, part_id: str, kind: str):
    """The one text row the host prints for a part's designator or its value."""
    rows = [
        text for text in plan.texts
        if text.part_id == part_id and text.kind == kind
    ]
    assert len(rows) == 1, (
        part_id, kind, [(text.kind, text.text) for text in plan.texts
                        if text.part_id == part_id],
    )
    return rows[0]


def _worst_gap(plan, box, *, landed: bool):
    """``(the shortest distance from this row to any run, the net it is to)``."""
    return min((il.box_gap(box, run), net) for net, run in _runs(plan, landed))


def _assert_row_clears(plan, part_id: str, kind: str) -> None:
    """One row, both readings — the model's coordinates and the landed page's."""
    row = _row(plan, part_id, kind)
    for landed in (False, True):
        gap, net = _worst_gap(plan, row.bbox, landed=landed)
        assert gap >= ROW_CLEARANCE - 1e-9, (
            f"{part_id}'s {kind} row {row.text!r} at {row.bbox} is {gap:.7f} "
            f"unit(s) from {net}{' (as landed)' if landed else ''} — a conductor "
            "on the row's own edge is not a drawing"
        )


def _assert_net_ends_on(plan, circuit, book, net_id: str, pins) -> None:
    """Every pin of this net is still an endpoint of one of its drawn runs."""
    origins = {part.part_id: (part.x, part.y) for part in plan.parts}
    poses = {
        part.part_id: SymbolPose(
            rotation=int(round(part.rotation)), mirror=bool(part.mirror),
        )
        for part in plan.parts
    }
    tips = il._tips(book, circuit, poses, origins)
    drawn = [
        point
        for segment in plan.segments if segment.net == net_id
        for point in segment.points
    ]
    for part, pin in pins:
        tip = tips[il.IslandPin(part_id=part, pin=pin)]
        assert any(
            abs(tip[0] - point[0]) < 1e-6 and abs(tip[1] - point[1]) < 1e-6
            for point in drawn
        ), f"{net_id} no longer ends on {part}.{pin} at {tip}"


# -------------------------------------------------------------------- the page


def test_c11_value_row_keeps_a_unit_from_every_conductor(page):
    """The measured defect: gap 0.0002373 after landing, and 0 on the model."""
    plan, _circuit, _book = page
    # S-21 / 532: a capacitor's value is never hidden, so a page that dropped the
    # row to make this test pass would be the wrong answer.
    part = [item for item in plan.parts if item.part_id == "C11"][0]
    assert part.value_visible
    _assert_row_clears(plan, "C11", "value")
    assert il.TEXT_WIRE_CLEARANCE >= ROW_CLEARANCE, il.TEXT_WIRE_CLEARANCE


def test_u4_reference_row_keeps_a_unit_from_every_conductor(page):
    """The disclosed scope exception: `feedback`'s row, found by the same census.

    `U4`'s reference row's bottom edge is ``y = 370`` and `FB_SENSE` left `R8.1`
    at exactly that y — the C11 defect one island over, answered by the same rule
    (no per-part branch).  Measured after the fix: the run sits at ``y = 372``,
    gap 2.0, on the model and after landing alike.
    """
    plan, _circuit, _book = page
    _assert_row_clears(plan, "U4", "reference")


def test_every_printed_row_on_the_page_keeps_two_units(page):
    """The whole page, not only the two rows the batch names.

    The module's own account says the flyback page's 37 printed rows all measure
    at least two units from every conductor, and that sentence is only true if a
    test reads **every** row: the two named tests above would keep passing while a
    third row quietly came back to 0.  So this is the census — every row of
    `plan.texts`, both readings (the model's coordinates and the host's
    two-decimal landing), shortest distance to every run of the page, and the
    floor is the measured ``2.0``.  The message names the worst row by part,
    kind, text and net, which is the reading a reader needs to act on.
    """
    plan, _circuit, _book = page
    assert len(plan.texts) == PAGE_ROWS, len(plan.texts)
    readings = [
        (gap, text, net, landed)
        for text in plan.texts
        for landed in (False, True)
        for gap, net in [_worst_gap(plan, text.bbox, landed=landed)]
    ]
    gap, text, net, landed = min(readings, key=lambda item: item[0])
    assert gap >= PAGE_ROW_CLEARANCE - 1e-9, (
        f"{text.part_id}'s {text.kind} row {text.text!r} at {text.bbox} is "
        f"{gap:.4f} unit(s) from {net}{' (as landed)' if landed else ''}; the "
        f"page floor is {PAGE_ROW_CLEARANCE:g} over all {PAGE_ROWS} printed rows"
    )


def test_sec_12v_still_laces_d3_c11_c13(page):
    """The fix moves a conductor, not a connection."""
    plan, circuit, book = page
    _assert_net_ends_on(plan, circuit, book, "SEC_12V", SEC_12V_PINS)


def test_fb_sense_still_laces_r7_r8_u4(page):
    """`feedback`'s reading: the same three pin tips 542-V1 pinned, still there."""
    plan, circuit, book = page
    _assert_net_ends_on(plan, circuit, book, "FB_SENSE", FB_SENSE_PINS)


# --------------------------------------------------------------- the mechanism


def test_router_spends_length_to_keep_row_clearance():
    """Four units of conductor are cheaper than a conductor on a row's edge.

    Both L-shapes run down the middle of the row (``x = 25`` is inside it, and a
    vertical run through a row is `text_hits`), so the only clean family left is
    the Z: one bend coordinate on the row's edge (``x = 20``, zero clearance, the
    shorter route at 150 units) and one outside it (``x = 18``, gap 2.0 — past
    `clearance + landing`, the route 531's own reading accepts — at 154).  The
    old ranking read both as text-free — `text_hits` counts a *penetration*, and
    a run on an edge penetrates nothing — so the hugging route won on `length`.
    This is the landed page's own arithmetic, with the row's height exaggerated
    so the L family cannot short-circuit the comparison.
    """
    row = (20.0, 0.0, 30.0, 100.0)
    field = il._Field(extents=(), bodies=(), pins=(), leads=(), rows=(row,))
    routed = il._route((25.0, -20.0), (25.0, 120.0), field, [20.0, 18.0])
    assert routed is not None
    path, tier, _complaints = routed
    assert tier == 1, path
    gaps = [il.box_gap(_run_box(a, b), row) for a, b in zip(path, path[1:])]
    assert min(gaps) >= ROW_CLEARANCE - 1e-9, (
        f"the route {path} runs {min(gaps):g} unit(s) from the row {row}"
    )


def test_detours_offer_the_snapped_clear_coordinate_on_every_side():
    """The offer half, pinned to the **numbers** the mechanism must produce.

    A row's raw edges stay offered (532's corridor) and the plain ring channels
    are far away, so "some coordinate exists on the clear side" would have passed
    on the old code too.  What the fix owes is the reserve's own coordinate: the
    edge pushed out by the clearance **plus the landing digit**, then put on the
    lattice.  For ``(20, 0, 30, 20)`` on the 5-unit lattice that is 15 left, 35
    right, -5 below and 25 above — ``snap_down(20 - 1.01)``, ``snap_up(30 +
    1.01)``, ``snap_down(0 - 1.01)``, ``snap_up(20 + 1.01)`` — and every one of
    them clears the row by the lattice step, which neither the raw edges nor the
    32-unit channels do.

    The row is chosen so the four numbers are **distinct**: with a 10-unit-tall
    row the left and above coordinates are both 15, and dropping either side from
    the offer would still pass.  Each of the four is asserted separately, and the
    mutation record for this test removes them one at a time.
    """
    row = (20.0, 0.0, 30.0, 20.0)
    budget = il.IslandBudget()
    detours = il._detours(100.0, budget, 0, rows=(row,))
    reserve = ROW_CLEARANCE + il.TEXT_WIRE_LANDING

    # The case's own arithmetic, spelled out so this test does not merely re-run
    # the implementation it is checking: (20, 0, 30, 20) on the 5-unit lattice,
    # one unit plus the landing digit out, rounded away from the row.
    expected = {"left": 15.0, "right": 35.0, "below": -5.0, "above": 25.0}
    assert len(set(expected.values())) == 4, expected
    tied = {
        "left": il._snap_down(row[0] - reserve, budget.grid),
        "right": il._snap_up(row[2] + reserve, budget.grid),
        "below": il._snap_down(row[1] - reserve, budget.grid),
        "above": il._snap_up(row[3] + reserve, budget.grid),
    }
    assert tied == expected, tied

    for side, value in expected.items():
        assert any(abs(item - value) < 1e-6 for item in detours), (
            f"no detour at {value} on the row's {side} side — {sorted(detours)}"
        )
        # the reserve survives the lattice **and** the host's two-decimal landing
        gap = {
            "left": row[0] - value, "right": value - row[2],
            "below": row[1] - value, "above": value - row[3],
        }[side]
        assert gap >= ROW_CLEARANCE, (side, value, gap)
        assert round(gap, LANDING_DECIMALS) >= ROW_CLEARANCE, (side, value, gap)

    # 532's corridor is not thrown away: the raw edges are still offered, and it
    # is `_route`'s `row_chords` key that declines them.
    for edge in (row[0], row[2], row[1], row[3]):
        assert any(abs(item - edge) < 1e-6 for item in detours), edge


def test_router_treats_the_landing_digit_as_part_of_the_reserve():
    """A model gap in ``[clearance, clearance + landing)`` can land *inside* the row.

    The offer hands the router coordinates ``clearance + TEXT_WIRE_LANDING`` out,
    so a coordinate closer than that is one the host can round into the row: a run
    at ``x = 873.4422373472949`` beside a row whose right edge is
    ``872.4402373472949`` is 1.002 unit away on the model — clear by the naked
    clearance — and lands at ``873.44``, i.e. 0.99976 away.  The old threshold
    (`< TEXT_WIRE_CLEARANCE`) scored that route 0 and let `length` keep it (it is
    2 units shorter than the clear alternative); the fixed threshold scores 1 and
    takes the clear one.

    The two L-shapes are out of the running because both run *through* the row
    (``x = 871`` is more than a unit inside ``869 .. 872.44``), which is
    `text_hits` — an earlier key than `bends`.  So the comparison is exactly Z
    versus Z, and the only difference between the two is what the clearance
    threshold says about 1.002.
    """
    row = (869.0, 0.0, 872.4402373472949, 10.0)
    field = il._Field(extents=(), bodies=(), pins=(), leads=(), rows=(row,))
    near = row[2] + 1.002  # model gap 1.002, landed 0.9998
    far = row[0] - 2.0  # model gap 2.0
    routed = il._route((871.0, -20.0), (871.0, 120.0), field, [near, far])
    assert routed is not None
    path, tier, _complaints = routed
    assert tier == 1, path
    gaps = [il.box_gap(_run_box(a, b), row) for a, b in zip(path, path[1:])]
    assert min(gaps) > ROW_CLEARANCE, (
        f"the route {path} runs {min(gaps):g} unit(s) from the row {row} — the "
        "near candidate is 1.002 on the model and lands at 0.99976"
    )
    landed = [
        il.box_gap(row, _run_box(_landed(a), _landed(b)))
        for a, b in zip(path, path[1:])
    ]
    assert min(landed) >= ROW_CLEARANCE, (path, landed)
