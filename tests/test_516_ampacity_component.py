"""516 A2: ``pcb-track-ampacity`` judges the **conductor**, not the net name.

On 实板 A one piece of copper is exported twice: ``IRbus`` in the schematic and
``IRBUS`` on the PCB (``Gear``/``GEAR`` the same). ``net_clearance(IRbus, IRBUS)``
reports ``distance = 0``, same layer, ``overlapping = True`` — physically one
conductor — and the rule only measured the declared half, leaving the other
half's 10 mil copper unread.

The fix expands each declared net to its **connected component** under
「copper that overlaps on a shared layer」 (a BFS, so a third name reachable only
through a second is included too), judges the component at its **narrowest**
width, and names every member in the row. A declared net that turns out to be one
conductor with an undeclared net also gets a standing **INFO**, so the extra
copper the rule measured is never silent.

**Where issue #84 fits.** The narrowest width is the judgement **only while the
conductor carries nothing wider that could be the current path**: copper at least
three times the narrowest segment and at least the width the declared current
needs is load-bearing, and the narrow segments beside it are then reported as a
branch (UNKNOWN, named) instead of an overload. The boards below therefore state
their wide copper **under** that bar (40 mil against a 53.8 mil requirement), so
what they pin is the closure and the ERROR path — the load-bearing shapes, 实板
A's ``IRbus``/``IRBUS`` among them, are pinned in
``tests/test_84_ampacity_branch.py``.
"""

from __future__ import annotations

from boardwise.core.designintent import DesignIntent, IntentSignal
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    Point,
    TrackSegment,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.ipc import TrackAmpacity, required_width_mil

LAYERS = {
    1: LayerInfo(layer_id=1, name="Top Layer", layer_type="TOP"),
    2: LayerInfo(layer_id=2, name="Bottom Layer", layer_type="BOTTOM"),
}


def _track(ident: str, *, x1: float, x2: float, net: str, width: float) -> TrackSegment:
    """One axis-aligned track on layer 1; a gap is ``|x1 - x2| - w1/2 - w2/2``."""
    return TrackSegment(
        id=ident,
        net=net,
        layer_id=1,
        start=Point(x1, 0.0),
        end=Point(x2, 0.0),
        width=width,
    )


def _board(tracks: list[TrackSegment]) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        layers=dict(LAYERS),
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=0.0, y=0.0, layer_id=1)
            for d in sorted({t.net or "" for t in tracks})
        ],
        pads=[],
        tracks=list(tracks),
    )


def _model(nets: list[str]) -> DesignModel:
    model = DesignModel()
    rows: dict[str, Net] = {}
    for index, net in enumerate(nets, start=1):
        designator = f"J{index}"
        model.components[designator] = Component(
            uid=f"u-{designator}", designator=designator, pins=[Pin("1", "1", net)]
        )
        rows.setdefault(net, Net(name=net)).pins.append((designator, "1"))
    model.nets = rows
    return model


def _ctx(board: BoardGeometry, nets: list[str], signals: list[IntentSignal]) -> PcbReviewContext:
    return PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=_model(nets),
        intent=DesignIntent(signals=list(signals), rails=[]),
        module_of={},
    )


def _errors(findings):
    return [f for f in findings if f.severity == "ERROR"]


def test_two_names_on_one_conductor_are_judged_at_the_narrowest():
    """``IRbus``/``IRBUS`` are one 3 A conductor; the 10 mil alias decides it.

    ``IRbus`` carries a **40 mil** track and ``IRBUS`` a **10 mil** track,
    overlapping on layer 1. The component's minimum on that layer is 10 mil; 3 A
    external needs 53.8 mil, so the row is an **ERROR** naming both names — the
    narrow copper is the *undeclared* half, which is exactly the 实板 A shape —
    and because ``IRBUS`` is not in the contract, an INFO says the rule measured
    its copper too.

    **Why 40 and not 60 (issue #84).** What this test pins is the *closure*: the
    narrowest copper on the conductor, whichever name carries it, decides the row.
    It used to state the declared half at 60 mil — 「wide enough for 3 A on its
    own」 — and that is exactly the shape #84 reclassifies: copper at least three
    times the narrowest segment (30 mil) **and** at least the 53.8 mil the current
    needs is load-bearing, so the 10 mil copper beside it is reported as a branch
    (UNKNOWN, named) rather than as an overload. 40 mil sits under that bar
    (``max(3 × 10, 53.8) = 53.8``), so the ERROR path this test exists for is
    still reached and the closure is still pinned as a violation; the 60 mil
    board — the shape #84 actually changes — is pinned in
    ``tests/test_84_ampacity_branch.py`` beside the issue's own numbers.
    """
    board = _board([
        _track("a", x1=0.0, x2=100.0, net="IRbus", width=40.0),
        _track("b", x1=50.0, x2=150.0, net="IRBUS", width=10.0),
    ])
    ctx = _ctx(board, ["IRbus", "IRBUS"], [IntentSignal(net="IRbus", slots={"range": "±3A"})])
    findings = TrackAmpacity().check(ctx)
    errors = _errors(findings)
    assert len(errors) == 1, [f.message for f in findings]
    error = errors[0]
    assert error.target.measurement["value"] == 10.0
    assert error.target.measurement["layer_ids"] == [1]
    assert error.target.net_refs == ["IRBUS", "IRbus"]
    assert "one conductor, 2 names" in error.message
    assert "IRbus" in error.message and "IRBUS" in error.message
    assert f"{required_width_mil(3.0):.1f}" in error.message
    infos = [f for f in findings if f.severity == "INFO"]
    assert len(infos) == 1, [f.message for f in findings]
    assert "IRBUS" in infos[0].message
    assert "unnamed" in infos[0].message


def test_a_single_name_with_no_neighbour_is_unchanged():
    """One declared net, no overlapped copper: exactly the old single-net row."""
    board = _board([_track("a", x1=0.0, x2=100.0, net="IRbus", width=10.0)])
    ctx = _ctx(board, ["IRbus"], [IntentSignal(net="IRbus", slots={"range": "±3A"})])
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "ERROR"
    assert finding.target.net_refs == ["IRbus"]
    assert finding.target.measurement["value"] == 10.0
    assert "one conductor" not in finding.message


def test_the_closure_walks_a_chain_of_three_names():
    """A third name reachable only through a second is still the same conductor.

    ``NA`` (60 mil, declared) overlaps ``NB`` (60 mil), which overlaps ``NC``
    (40 mil); ``NA`` and ``NC`` do **not** touch. A single-hop reading would stop
    at ``NB``, see 60 mil, and pass — the swing here is that ``NC``'s 40 mil is
    the bottleneck, so the closure is what makes the row exist at all. 40 rather
    than #84's narrower shapes for the same reason as the test above: the bar on
    this layer is ``max(3 × 40, 53.8) = 120`` mil, so nothing here load-bears and
    the row stays the ERROR this test is about.
    """
    board = _board([
        _track("a", x1=0.0, x2=100.0, net="NA", width=60.0),
        _track("b", x1=100.0, x2=320.0, net="NB", width=60.0),
        _track("c", x1=300.0, x2=400.0, net="NC", width=40.0),
    ])
    ctx = _ctx(board, ["NA", "NB", "NC"], [IntentSignal(net="NA", slots={"range": "±3A"})])
    findings = TrackAmpacity().check(ctx)
    errors = _errors(findings)
    assert len(errors) == 1, [f.message for f in findings]
    error = errors[0]
    assert error.target.measurement["value"] == 40.0
    assert error.target.net_refs == ["NA", "NB", "NC"]
    assert "one conductor, 3 names" in error.message
    for net in ("NA", "NB", "NC"):
        assert net in error.message


def test_a_conductor_with_room_to_spare_is_silent_but_still_discloses_the_alias():
    """Margin stays silence; the undeclared alias is still named in an INFO."""
    board = _board([
        _track("a", x1=0.0, x2=100.0, net="IRbus", width=60.0),
        _track("b", x1=50.0, x2=150.0, net="IRBUS", width=60.0),
    ])
    ctx = _ctx(board, ["IRbus", "IRBUS"], [IntentSignal(net="IRbus", slots={"range": "±3A"})])
    findings = TrackAmpacity().check(ctx)
    assert _errors(findings) == [], [f.message for f in findings]
    assert [f.severity for f in findings] == ["INFO"], [f.message for f in findings]
    assert "IRBUS" in findings[0].message
