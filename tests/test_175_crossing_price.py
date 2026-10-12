"""175/B-1: crossing another net's wire is priced as a detour, and the shortcut obeys.

**What 岳 ruled (2026-10-12).** 「宁可多绕也不穿干线」 — a wire a reader sees
cutting a trunk reads as a join, so the price of one crossing has to be worth a
detour rather than cheaper than one. 173 measured what it was: `CROSS_COST = 2.0`
(two lattice steps) while the flyback page's own `COMP` run could avoid its two
crossings of `SEC_12V` for about 80 steps. Two changes here:

* :data:`boardwise.engines.router.CROSS_COST` is now high and **finite** (120
  steps) — finite on purpose, because a schematic is not planar and a refusal
  would turn a crowded page into an undrawable one. The search still draws a
  crossing when nothing cheaper exists (:func:`test_a_crossing_is_still_drawn_when_nothing_cheaper_exists`);
* the one-bend shortcut is held to the same price
  (:func:`boardwise.engines.drawcompiler._elbow_route`), because 175 **measured**
  that raising the constant alone did not move `COMP` at all: that run is drawn by
  the shortcut, which never consulted a price. Its **straight** case stays
  ungated — 074 hardens a flag's lead, not ordinary wiring (that promise lives in
  `test_053b_drawcompiler.test_only_a_leads_run_is_gated_and_ordinary_wiring_
  still_crosses` and is re-stated here as the contrast case).

The end-to-end pin is the delivered 150 landing page: `COMP`'s drawn run, and the
page's hard violations.
"""

from __future__ import annotations

import functools
import math
import pathlib

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply, drawcompiler as dc, router

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
#: 150's delivered landing page and 173's own reproduction inputs (`outputs/173/
#: evidence.md` section B measured this page's `COMP` run cutting `SEC_12V` twice).
PAGE_150 = ROOT / "outputs" / "150" / "presentation_150_r5rot.json"


# ------------------------------------------------------------------- 代价的取值


def test_the_crossing_price_is_high_finite_and_worth_a_detour():
    """120 steps: above every detour a page offers, finite so nothing is refused.

    173 measured the detour the flyback page really had to offer (~80 lattice
    steps) and the old price (2.0). The lower bound is the ruling's own words —
    a price below the detour it competes with is the defect — and the upper bound
    is :func:`boardwise.engines.layout._INFINITE_COST`'s measured full sheet
    crossing (~230 steps): the search will spend a whole detour on one crossing,
    but it will not walk the sheet to dodge one.
    """
    assert math.isfinite(router.CROSS_COST)
    assert router.CROSS_COST >= 100.0, (
        "the crossing price must be above the detours a page offers (173 measured "
        "~80 steps on the flyback page)"
    )
    assert router.CROSS_COST < 230.0, (
        "kept below the ~230-step full sheet crossing, so a crossing is still "
        "drawn when the only alternative is walking the sheet"
    )
    assert router.CROSS_COST == dc.CROSS_COST, (
        "the name drawcompiler re-exports is the router's own (112)"
    )


# --------------------------------------------------------- 一折快路与搜索同价


def _router(**overrides) -> dc._Router:
    router_ = dc.lattice_router(
        grid=5.0, residue=(0.0, 0.0), boxes=(), bounds=(0.0, 0.0, 400.0, 400.0),
    )
    for name, value in overrides.items():
        setattr(router_, name, value)
    return router_


def test_a_straight_run_across_a_foreign_wire_is_still_returned():
    """The contrast case: a straight run has no alternative to weigh.

    074 hardens a **flag's lead**; an ordinary wire may cross (the gate counts
    crossings as an advisory metric). The shortcut's degenerate corner case is a
    run that is collinear with its own endpoints, so there is nothing to choose —
    the price cannot reach it, and nothing here pretends otherwise.
    """
    router_ = _router(edges=[((100.0, 100.0), (100.0, 300.0))], edge_nets=["GND"])
    run = [(50.0, 200.0), (250.0, 200.0)]
    assert dc.one_bend_route(router_, run[0], run[1], set()) == run


def test_a_bent_elbow_that_would_cross_gives_way_to_the_other_corner():
    """The first free L is not taken when its legs run through a foreign wire.

    Two L-shapes exist for one pin pair; the far corner here is the one that
    arrives without crossing, and it is what the shortcut now returns. Before
    175 the near corner won on "first free", and the crossing it drew was the
    `COMP` shape 岳 read as a join.
    """
    router_ = _router(edges=[((150.0, 100.0), (150.0, 250.0))], edge_nets=["GND"])
    start, end = (50.0, 200.0), (250.0, 300.0)
    first_corner = (end[0], start[1])
    assert dc._run_crosses_a_foreign_wire(router_, start, first_corner), (
        "premise: the near corner's run cuts the foreign wire at (150,200)"
    )
    assert dc.one_bend_route(router_, start, end, set()) == [
        start, (start[0], end[1]), end,
    ]


def test_a_crossing_is_still_drawn_when_nothing_cheaper_exists():
    """The price, never a wall (岳's ruling and 137's rule).

    Both corners of one pin pair are blocked by a foreign wire's interior: the
    shortcut returns nothing, and the search — which pays the crossing and finds
    the cheapest route anyway — still answers. An unroutable net on a page like
    this would be the refusal 175 exists to avoid.
    """
    router_ = _router(
        edges=[((150.0, 100.0), (150.0, 250.0)), ((200.0, 250.0), (200.0, 350.0))],
        edge_nets=["GND", "VCC"],
    )
    start, end = (50.0, 200.0), (250.0, 300.0)
    assert dc.one_bend_route(router_, start, end, set()) is None, (
        "premise: both L-shapes run through a foreign wire"
    )
    path = router_.route(start, end)
    assert path is not None and path[0] == start and path[-1] == end


def test_a_leg_that_merely_ends_near_a_foreign_wire_is_not_a_crossing():
    """The check asks the search's own question at the search's own nodes.

    A run that **stops 5 units short** of a foreign wire, and one that stops
    exactly at its *endpoint* (a vertex, which the editor does not join), both
    leave the shortcut free: only a node strictly inside another net's run is a
    crossing — the same test
    :meth:`boardwise.engines.router._Router._crossing` applies.
    """
    router_ = _router(edges=[((100.0, 100.0), (100.0, 300.0))], edge_nets=["GND"])
    assert not dc._run_crosses_a_foreign_wire(router_, (50.0, 195.0), (95.0, 195.0))
    assert not dc._run_crosses_a_foreign_wire(router_, (50.0, 100.0), (100.0, 100.0))
    assert dc._run_crosses_a_foreign_wire(router_, (50.0, 195.0), (150.0, 195.0))


# ------------------------------------------------------ 真页：150 落地页的 COMP


@functools.cache
def _landing_page():
    result = dc.compile(
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(PAGE_150),
        drawapply.load_library(SPECS / "flyback_uc3845.library.json"),
        dc.CompileBudget(),
    )
    assert result.ok, [item.detail for item in result.failures]
    return result.candidates[0], result


def _routes(plan, net: str) -> list[list[tuple[float, float]]]:
    return [list(segment.points) for segment in plan.segments if segment.net == net]


def test_the_landing_pages_component_run_no_longer_cuts_the_trunk_twice():
    """The measured instance: 173's `COMP` route (old → new).

    ``old`` (173, and this tree before 175):
    ``[(760,645),(755,645),(755,605),(795,605)]`` — cutting `SEC_12V`'s trunk at
    (755,615) and (765,605). ``new``: ``[(760,645),(760,620),(795,620),
    (795,605)]``, one crossing at (765,620): the remaining one is what the search
    could not buy its way out of inside 120 steps, which is the finite price
    doing its job rather than a wall doing nothing.
    """
    plan, _result = _landing_page()
    assert _routes(plan, "COMP") == [[
        (760.0, 645.0), (760.0, 620.0), (795.0, 620.0), (795.0, 605.0),
    ]]


def test_the_landing_pages_component_run_crosses_the_trunk_at_most_once():
    """Counted on the drawn geometry, not read off the plan's own words.

    `SEC_12V`'s trunk is its own polyline; a crossing is a lattice node strictly
    inside both runs. 173 measured two for `COMP`; one is what is left — the
    search could not buy its way out of the second for under 120 steps, which is
    the finite price doing its job.
    """
    plan, _result = _landing_page()
    crossings = _crossings(_routes(plan, "COMP"), _routes(plan, "SEC_12V"))
    assert crossings <= 1, f"COMP cuts SEC_12V {crossings} time(s)"


def test_the_second_long_run_is_bought_out_of_its_crossing():
    """What the price *is for*, on the run the search draws.

    `FB_SENSE` is the wire whose route answers the constant: at 2.0 steps per
    crossing the search kept it short and cut `SEC_12V`'s trunk; at 120 it pays a
    detour around the page instead. That detour is the ruling 「宁可多绕也不穿干线」
    made visible, and this assertion is what a lowered price takes red.
    """
    plan, _result = _landing_page()
    assert _crossings(_routes(plan, "FB_SENSE"), _routes(plan, "SEC_12V")) == 0, (
        "FB_SENSE's run still cuts SEC_12V's trunk — the crossing price is not "
        "worth the detour it buys"
    )


def _crossings(first: list, second: list) -> int:
    """Nodes strictly inside one of the first's runs and one of the second's."""
    count = 0
    for run in first:
        for start, end in zip(run, run[1:]):
            steps = max(
                1,
                int(round(max(abs(end[0] - start[0]), abs(end[1] - start[1])) / 5.0)),
            )
            for index in range(steps + 1):
                ratio = index / steps
                node = (
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                )
                for other in second:
                    for a, b in zip(other, other[1:]):
                        if router._strictly_on_segment(node, a, b):
                            count += 1
    return count


def test_the_landing_page_still_draws_every_net_and_refuses_nothing():
    """No net is lost to the new price — the draw line's answer to `NET_UNROUTABLE`.

    ``NET_UNROUTABLE`` is the **solver** line's code (`engines/layout.py`; the
    compiler does not emit it), so the property to check here is its equivalent:
    every net of the circuit still has a conductor on the page (a wire, a flag or
    a label), and the checker's hard list is empty. A re-routed wire that gave up
    on a net would show up as a missing net, not as a code.
    """
    plan, result = _landing_page()
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    drawn = {segment.net for segment in plan.segments}
    drawn |= {label.net for label in plan.labels}
    drawn |= {symbol.net for symbol in plan.power_symbols}
    assert {net.id for net in circuit.nets} <= drawn
    assert plan.evidence.hard_violations == []
    assert [item.category for item in result.failures] == []
