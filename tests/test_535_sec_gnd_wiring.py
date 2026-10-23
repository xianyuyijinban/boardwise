"""535: the pin the search cannot leave, and the L that pays the crossing.

The merge of the island drawing line put a re-measured flyback library under this
page.  Five of its symbols gained a ``valueRow`` — the string the **host** draws,
which is what `SymbolProfile.value_row` states where the host's device name is
not the spec's value (`SS310 (100V 3A schottky)` → `SS310`, `4N60 (600V 4A NMOS)`
→ `4N60`, `TL431 (SOT-23-3)` → `TL431`, `220uF/25V SMD electrolytic` →
`220uF/25V-SMT`, `1nF/1kV` → `1nF/1KV`).  Those rows are the boxes
`_declared_rows` puts in `router.boxes`, so narrowing them moved the routing:
`SEC_SW` stopped detouring under the row `D3`'s value used to occupy, the `y=840`
corridor opened, `SEC_12V` came down it and ran left along `y=640` — straight
across the one corridor the flyback's `C13.2` had left.

`C13.2` at ``(440, 660)`` stands inside its own part's **drawn** rows — the value
row ``(435, 650)-(473.151, 660)`` and the reference row ``(435, 660)-(448.11,
670)``, both printed by the host at the symbol's own offsets — and beside its own
pin lead ``(430, 659.5)-(439, 660.5)``.  All four of its lattice neighbours are
walls, so ``_Router.route`` can never step away from the pin however far it
searches; the only drawing there is the two-leg L.  With `SEC_12V`'s new run
crossing that L, 175/B-1's rule (a *bent* shortcut may not undercut the search's
own price) refused it, and the page was refused as `layout-unsat` through 069
sec.1's flag ladder — while the same page under the older value rows compiles,
which is what makes the refusal a regression rather than a stricter rule
(`tools/535_plan_probe.py`, `tools/535_elbow_probe.py`).

The fix is `drawcompiler._no_step_out` (the start-node half of
`_unenterable_goal`'s proof) plus `_elbow_route(..., crossings=True)`: where the
search **provably** cannot move, the L that pays `CROSS_COST` is the drawing a
reader would make, because a crossing is a price and not a wall (074 keeps an
ordinary wire's crossing legal).  Everywhere the search could have answered, the
free-elbow rule stands untouched.
"""

from __future__ import annotations

import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutSegment
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply, drawcompiler as dc
from boardwise.engines.router import _Router

from gate_skip import skip_if_the_147_gate_refused

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
LOCKS_144 = ROOT / "outputs" / "144" / "presentation_144.json"

#: The page's own measured geometry (`tools/535_plan_probe.py`).  They move only
#: if a symbol's drawn rows, the placement or the routing order change, and then
#: every reading in this file has to be re-taken.
BURIED_PIN = (440.0, 660.0)
PRICED_ELBOW = [(440.0, 660.0), (475.0, 660.0), (475.0, 600.0)]
CROSSING_NET = "SEC_12V"
SEC_GND_PADS = [(240.0, 690.0), (440.0, 660.0), (500.0, 600.0),
                (640.0, 305.0), (955.0, 300.0)]


def _router(**overrides) -> _Router:
    options = dict(
        grid=5.0, residue=(0.0, 0.0), boxes=[], bounds=(0.0, 0.0, 200.0, 200.0)
    )
    options.update(overrides)
    return _Router(**options)


def _crosses(router, points) -> list[tuple[str, tuple[float, float]]]:
    """Every foreign run this polyline enters, with the net it belongs to."""
    out = []
    for start, end in zip(points, points[1:]):
        for index, foreign in enumerate(router.edges):
            spot = dc._proper_crossing(start, end, foreign[0], foreign[1])
            if spot is not None:
                net = router.edge_nets[index] if index < len(router.edge_nets) else ""
                out.append((net, spot))
    return out


# -------------------------------------------- the start the search cannot leave


def test_a_pin_whose_neighbours_are_all_walls_is_known_in_advance():
    """`_no_step_out` reads `route`'s own stepping rule off the start node.

    ``route`` pushes the start and only ever expands a neighbour whose node
    `_wall` lets through, so a node inside a drawn row — with all four neighbours
    inside rows — can never reach a goal however long it searches.  The pair of
    boxes here is that shape: they share the pin's own row, which is how a symbol's
    value row below the pin and its reference row above it leave the pin with
    nowhere to step.
    """
    boxes = [(35.0, 90.0, 70.0, 100.0), (35.0, 100.0, 70.0, 110.0)]
    buried = _router(boxes=boxes)
    assert dc._no_step_out(buried, (40.0, 100.0))
    # An ordinary open lattice point, and a point on a box's own outline (a
    # neighbour of it is outside), are both free: the test is about being
    # *enclosed*, not about touching a box.
    assert not dc._no_step_out(_router(), (40.0, 100.0))
    assert not dc._no_step_out(_router(boxes=boxes), (5.0, 100.0))


def test_the_elbow_that_crosses_is_a_last_resort_only_where_the_search_is_stuck():
    """175/B-1's price, and the one caller allowed to pay it (535).

    The foreign run at ``y=80`` crosses **both** L-shapes from the start to the
    target, so the free-elbow rule refuses both — and the search, which pays
    :data:`~engines.router.CROSS_COST` for the same crossing, walks round the run
    instead (that is 175/B-1's own doctrine: a price, not a wall).  Where the
    search **cannot** take even one step — the start enclosed by its own part's
    rows — the L is the only drawing there is, and it is taken.

    A pinned elbow is the drawing that leaves `SEC_GND`'s `C13.2` reachable; the
    guard is what keeps it off every other pin on every page.
    """
    foreign = ((20.0, 80.0), (100.0, 80.0))
    target = [(80.0, 60.0), (80.0, 20.0)]
    router = _router(boxes=[])
    router.edges = [foreign]
    router.edge_nets = ["SEC_12V"]
    assert not dc._no_step_out(router, (40.0, 100.0))

    # Both L-shapes exist and both are refused by the crossing alone: the run
    # crosses the first one's second leg and the second one's first leg.
    assert dc._elbow_route(router, (40.0, 100.0), (80.0, 60.0), set()) is None
    priced = dc._elbow_route(
        router, (40.0, 100.0), (80.0, 60.0), set(), crossings=True
    )
    assert priced == [(40.0, 100.0), (80.0, 100.0), (80.0, 60.0)], priced
    assert _crosses(router, priced) == [("SEC_12V", (80.0, 80.0))], priced

    # The search can move here, so it answers, and its answer walks round the run
    # — the priced elbow is *not* what a pin the search can leave gets.
    reachable = dc._attach(
        router, (40.0, 100.0), [LayoutSegment(net="SEC_GND", points=target)],
        set(), "SEC_GND",
    )
    assert reachable is not None, "the search has a way round the run"
    assert reachable.points != priced, reachable.points
    assert _crosses(router, reachable.points) == [], reachable.points

    # Enclosed by its own part's rows, the same pin gets the priced L.
    buried = _router(boxes=[(35.0, 90.0, 70.0, 100.0), (35.0, 100.0, 70.0, 110.0)])
    buried.edges = [foreign]
    buried.edge_nets = ["SEC_12V"]
    assert dc._no_step_out(buried, (40.0, 100.0))
    assert dc._elbow_route(buried, (40.0, 100.0), (80.0, 60.0), set()) is None
    attached = dc._attach(
        buried, (40.0, 100.0), [LayoutSegment(net="SEC_GND", points=target)],
        set(), "SEC_GND",
    )
    assert attached is not None, (
        "a pin the search provably cannot leave has no conductor without the L"
    )
    assert attached.points == [(40.0, 100.0), (80.0, 100.0), (80.0, 60.0)], (
        attached.points
    )


# ------------------------------------------------------ the page the merge refused


def _compile_locked():
    if not LOCKS_144.is_file():
        pytest.skip(
            f"缺本地产物 {LOCKS_144.relative_to(ROOT).as_posix()}（未入库，"
            ".gitignore 忽略 outputs/）：144 的锁定表是未入库的本地产物，"
            "生成见 outputs/144 或任务 144；产物在时本条按原断言真跑"
        )
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(LOCKS_144)
    book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")
    result = dc.compile(circuit, presentation, book, dc.CompileBudget())
    skip_if_the_147_gate_refused(result, "535, the secondary return's own pin")
    return circuit, presentation, book, result


def test_the_secondary_return_reaches_its_own_buried_pin(monkeypatch):
    """The regression, at the pin it happened on: `SEC_GND` is a conductor again.

    535's chain, in one page: the library's re-measured `valueRow`s narrowed the
    value rows the router routes around, `SEC_12V`'s route moved across `C13.2`'s
    only exit, and the pin — enclosed by its own part's drawn rows — could not be
    reached by the search at all.  So this asserts the three facts together: the
    pin is one the search cannot leave, the attachment that reaches it crosses
    exactly one foreign run (`SEC_12V`'s, the price the search could not weigh),
    and every pad of the net is on the net's own geometry — a multi-pin net
    without a conductor is the one shape 053 sec.7 forbids outright.
    """
    seen: dict[str, object] = {}
    real = dc._attach

    def spy(router, point, segments, blocked, net_id):
        out = real(router, point, segments, blocked, net_id)
        if net_id == "SEC_GND" and dc._key(point) == dc._key(BURIED_PIN):
            seen["buried"] = dc._no_step_out(router, point)
            seen["points"] = None if out is None else [tuple(item) for item in out.points]
            seen["crosses"] = [] if out is None else _crosses(router, out.points)
        return out

    monkeypatch.setattr(dc, "_attach", spy)
    circuit, presentation, book, result = _compile_locked()
    assert result.ok, [item.detail for item in result.failures]
    assert seen.get("points") == [tuple(point) for point in PRICED_ELBOW], seen
    assert seen.get("buried") is True, (
        "the pin this batch is about is one `_no_step_out` calls enclosed: "
        f"{seen}"
    )
    assert [net for net, _spot in seen["crosses"]] == [CROSSING_NET], seen
    plan = result.candidates[0]
    geometry = [segment.points for segment in plan.segments if segment.net == "SEC_GND"]
    assert geometry, "SEC_GND has no conductor at all — the regression itself"
    for pad in SEC_GND_PADS:
        assert any(dc._on_polyline(pad, points) for points in geometry), (
            f"SEC_GND's pad at {pad} is not on the net's own wiring: {geometry}"
        )
