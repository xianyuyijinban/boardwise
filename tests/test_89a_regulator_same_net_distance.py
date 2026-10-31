"""Issue #89A: ``pcb-regulator-cap-distance`` measures the loop **on the net**.

The defect. Until this batch the rule measured a regulator/capacitor pair with
:func:`boardwise.core.measure.component_distance`, which by design refuses
**same-net** pad pairs (127b: two pads of one net meeting is the design, not a
defect) and **cross-layer** ones (127a: a top pad and a bottom pad 0.0 mil apart
in plan view measure the board's thickness). A decoupling capacitor's supply pad
and its regulator's supply pad are same-net *by construction*, and on a real
board they are frequently on opposite faces, so every real candidate came back
``None`` — and ``_one_pool`` then wrote that ``None`` as 「candidates exist but
none is placed on this PCB document」 about a part
:meth:`~boardwise.core.geometry.BoardGeometry.component` had already proved is on
the board. It also meant the rule's number was the closest pair across *other*
nets — a placement gap, not the loop the capacitor stands on.

The fix. The gap is now :func:`boardwise.rules.pcb.regulator.
same_net_loop_distance`: only pads whose ``pad.net == net`` take part, the pair
is measured with :func:`boardwise.core.measure.pad_edge_distance` (planar,
layer-blind), the minimum over the pairs is the number, and the pad pair that
produced it is kept. That is exactly the reading
:class:`~boardwise.rules.pcb.distance.DecapDistance` takes since 164c, so one
context yields one number from both rules — pinned here, not asserted in prose.

What this file pins, in the task book's order:

1. the issue's own minimal geometry — ``U1`` on the top face, ``C7`` on the
   bottom, only ``+12V``/``GND`` shared — where ``component_distance`` returns
   ``None`` and the rule now reports the ``+12V`` pad-to-pad gap, with no
   「none is placed」 in the message;
2. same-layer same-net, cross-layer same-net, several same-net pads taking the
   nearest, and nearest-candidate selection, each with a hand-derived number
   (pads are 40x40, so an on-axis gap is ``|dx| - 40``);
3. the three empty-pool paths told apart — no capacitor on the net, candidates
   this board does not place, and candidates it does place but with no pad on
   the net. The third must read as unmeasurable, never as 0 mil and never as
   unplaced;
4. the same loop number out of ``DecapDistance`` and ``RegulatorCapDistance``;
5. ``component_distance``'s own refusals unchanged, so the shared primitive is
   still the cross-net reader the other spacing rules rely on.

Synthetic boards only; no fixture, no editor, no daemon.
"""

from __future__ import annotations

import math

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    PadGeometry,
)
from boardwise.core.measure import component_distance
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.distance import DecapDistance
from boardwise.rules.pcb.regulator import (
    RegulatorCapDistance,
    same_net_loop_distance,
)

SUPPLY = "+12V"
OUT_NET = "OUT_NET"
GND = "GND"
AGND = "AGND"
OUT_GROUND = "OUT_GND"

TOP = 1
BOTTOM = 2


# ---------------------------------------------------------------------------
# synthetic helpers — 40x40 pads, so every gap below is a subtraction
# ---------------------------------------------------------------------------


def _pad(
    component: str,
    pin: str,
    *,
    x: float,
    y: float,
    net: str,
    layer: int = TOP,
) -> PadGeometry:
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        footprint_layer_id=layer,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _comp(
    designator: str,
    *,
    value: str = "",
    mpn: str = "",
    lcsc: str = "",
    pins: list[Pin] | None = None,
) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        lcsc_part=lcsc,
        pins=list(pins or ()),
    )


def _regulator(designator: str = "U1", *, pins: list[Pin] | None = None) -> Component:
    """A shelf-named ``ic.ldo`` with the three pins the two rules both need.

    Three pins is also :func:`boardwise.rules.pcb.distance.classify_device`'s
    floor, so the same part is an IC for ``DecapDistance`` — that is what makes
    the two-rules-one-number test possible on one context.
    """
    return _comp(
        designator,
        mpn="SYNTHREG",
        lcsc="C0",
        pins=pins
        or [
            Pin("1", "VIN", SUPPLY),
            Pin("2", "VOUT", OUT_NET),
            Pin("3", "GND", GND),
        ],
    )


def _model(components: list[Component]) -> DesignModel:
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


def _board(
    parts: list[tuple[str, float, float, int]], pads: list[PadGeometry]
) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=x, y=y, layer_id=layer)
            for d, x, y, layer in parts
        ],
        pads=list(pads),
    )


def _ctx(board: BoardGeometry, model: DesignModel) -> PcbReviewContext:
    return PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=model,
        intent=None,
        module_of={},
        pcb_model=model,
    )


def _shelf() -> PartLibrary:
    return PartLibrary(
        parts=[
            PartEntry(
                key="test.synthreg.c0", mpn="SYNTHREG", lcsc="C0", category="ic.ldo"
            )
        ]
    )


def _rows(model: DesignModel, board: BoardGeometry) -> dict:
    """``{(regulator, side, pool): finding}`` from the rule itself."""
    findings = RegulatorCapDistance().check_with_library(
        _ctx(board, model), _shelf()
    )
    rows: dict = {}
    for finding in findings:
        side = "VIN" if "VIN" in finding.message else (
            "VOUT" if "VOUT" in finding.message else "?"
        )
        pool = (
            "HF" if "high-frequency bypass" in finding.message
            else "STORAGE" if "energy storage" in finding.message
            else "?"
        )
        rows[(finding.target.component_ref, side, pool)] = finding
    return rows


# ---------------------------------------------------------------------------
# 1. the issue's minimal geometry: U1 on top, C7 on the bottom, +12V/GND only
# ---------------------------------------------------------------------------


def _issue_89_board():
    """``U1`` top face, ``C7`` bottom face, ``+12V``/``GND`` **both** shared.

    Issue #89's own minimal geometry, literally: the two parts share two nets —
    the supply rail and ground — and every pad is on the opposite face to the
    other part's, so **both** legs of the loop are same-net *and* cross-layer.
    That is the pair ``component_distance`` refuses twice over.

    Geometry, all pads 40x40:

    * ``U1.1`` (``VIN``, ``+12V``) at (0, 0) on the **top** face;
    * ``U1.2`` (``VOUT``, ``OUT_NET``) at (0, 40);
    * ``U1.3`` (``GND``, ``GND``) at (0, 80);
    * ``C7.1`` (``+12V``) at (160, 0) on the **bottom** face;
    * ``C7.2`` (``GND``) at (100, 0), also on the bottom.

    So the ``+12V`` loop leg is ``160 - 40 = 120.0 mil`` and the ``GND`` leg is
    ``hypot(100 - 40, 80 - 40) = hypot(60, 40) ≈ 72.1 mil``. Note also the number
    the old reading could not produce *and* the one a net-blind reading would
    have produced instead: the closest pair of **any** two pads here is
    ``U1.1``↔``C7.2`` at ``100 - 40 = 60.0 mil`` — the capacitor's *ground* pad,
    which is not a leg of the supply loop.
    """
    model = _model([
        _regulator(),
        _comp(
            "C7",
            value="100nF",
            pins=[Pin("1", "1", SUPPLY), Pin("2", "2", GND)],
        ),
    ])
    board = _board(
        [("U1", 0.0, 40.0, TOP), ("C7", 160.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
            _pad("U1", "3", x=0.0, y=80.0, net=GND),
            _pad("C7", "1", x=160.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C7", "2", x=100.0, y=0.0, net=GND, layer=BOTTOM),
        ],
    )
    return model, board


def test_issue_89_minimal_geometry_is_measured_on_the_net():
    """The old reading is ``None``; both same-net cross-layer legs are measured.

    This is the whole issue in one board. ``component_distance`` answers
    ``None`` twice over: every pad pair is same-net, and the cross-net pairs are
    cross-layer. The rule must not turn that ``None`` into 「none is placed」 —
    the part is on this board — and it must not report the 60.0 mil gap to the
    capacitor's ground pad as the **supply** loop, because that leg is ``GND``'s,
    not ``+12V``'s. Both legs are measurable, and each is measured on its own net:
    ``+12V`` at 120.0 mil (``pads 1 / 1``) and ``GND`` at ≈72.1 mil
    (``pads 3 / 2``).
    """
    model, board = _issue_89_board()

    assert component_distance(board, "U1", "C7") is None

    loop = same_net_loop_distance(board, "U1", "C7", SUPPLY)
    assert loop is not None
    assert loop.edge_distance == pytest.approx(120.0)
    assert (loop.pad_a, loop.pad_b) == ("1", "1")
    # The ground leg is same-net *and* cross-layer too, and is measured rather
    # than refused: 100 - 40 = 60 in x, 80 - 40 = 40 in y.
    ground = same_net_loop_distance(board, "U1", "C7", GND)
    assert ground is not None
    assert ground.edge_distance == pytest.approx(math.hypot(60.0, 40.0))
    assert (ground.pad_a, ground.pad_b) == ("3", "2")

    rows = _rows(model, board)
    hf = rows[("U1", "VIN", "HF")]
    assert hf.severity == "INFO"
    assert hf.target.counterpart_ref == "C7"
    assert hf.target.net_refs == [SUPPLY]
    assert hf.target.measurement == {
        "kind": "distance", "value": 120.0, "unit": "mil",
    }
    assert "120.0 mil edge-to-edge" in hf.message
    assert "pads 1 / 1" in hf.message
    assert "none is placed" not in hf.message
    assert "not placed" not in hf.message
    assert "no same-net pad pair" not in hf.message

    # The empty pool row on the same net is about the **pool**, not about the
    # net and not about placement: ``C7`` is on ``+12V`` and is measurable, it is
    # simply in the other pool. Until #89's review this row said 「no capacitor
    # on the net at all」 directly under an evidence list naming ``C7`` — two
    # statements that cannot both be true, pinned green by this very test.
    storage = rows[("U1", "VIN", "STORAGE")]
    assert storage.target.counterpart_ref == ""
    assert "no capacitor on the net at all" not in storage.message
    assert "the net is not empty: C7 on '+12V' is outside this pool" in storage.message
    assert "not placed" not in storage.message
    assert not any(
        "no candidate capacitor bridges" in line for line in storage.evidence
    )
    assert any(
        "candidates bridging '+12V' to a ground net are outside this pool: C7"
        in line
        for line in storage.evidence
    )


def test_the_ground_pad_is_not_a_leg_of_the_supply_loop():
    """The nearest pad pair on this board is a **ground** one, and is not read.

    A separate board from the issue's minimal geometry, built to cover the two
    things that one cannot: a **differently named** ground net, and the fact that
    the reader filters by ``pad.net`` rather than by 「is this pad on some
    ground」. ``U1``'s ground pin is ``GND`` while ``C7``'s is ``AGND``, so
    neither part has a pad on the other's ground net.

    ``U1.1``↔``C7.2`` (``AGND``) is the closest pair on the board — 60.0 mil
    edge to edge, ``100.0`` centre to centre — while the ``+12V`` leg is 120.0.
    A net-blind minimum would report 60.0 for the supply loop; the reading is on
    ``+12V`` only, so it reports 120.0. ``GND`` and ``AGND`` both answer ``None``
    for their own reason (no pad of the other part on that net), which is the
    filter working in both directions rather than a ground exemption.
    """
    model = _model([
        _regulator(),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    board = _board(
        [("U1", 0.0, 40.0, TOP), ("C7", 160.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
            _pad("U1", "3", x=0.0, y=80.0, net=GND),
            _pad("C7", "1", x=160.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C7", "2", x=100.0, y=0.0, net=AGND, layer=BOTTOM),
        ],
    )
    all_pairs = min(
        math.dist((pad_a.x, pad_a.y), (pad_b.x, pad_b.y))
        for pad_a in board.pads_for_component("U1")
        for pad_b in board.pads_for_component("C7")
    )
    assert all_pairs == pytest.approx(math.hypot(100.0, 0.0))
    assert same_net_loop_distance(board, "U1", "C7", SUPPLY).edge_distance == (
        pytest.approx(120.0)
    )
    assert same_net_loop_distance(board, "U1", "C7", GND) is None
    assert same_net_loop_distance(board, "U1", "C7", AGND) is None
    # The row for the rail is still the 120.0 leg, and it is C7's supply pad
    # that produced it — not the nearer ground pad.
    hf = _rows(model, board)[("U1", "VIN", "HF")]
    assert hf.target.measurement["value"] == 120.0
    assert "pads 1 / 1" in hf.message


# ---------------------------------------------------------------------------
# 2. same layer, several pads, several candidates — all measured exactly
# ---------------------------------------------------------------------------


def test_same_layer_same_net_is_measured_and_the_nearest_pad_pair_wins():
    """Two ``+12V`` pads on the regulator: the minimum pair wins, and names itself.

    ``U1.1`` at (0, 0) and ``U1.4`` at (0, 200) are both ``VIN``; ``C7.1`` sits
    at (100, 0) and ``C7.2`` (its ground pad) at (100, 40). Every pad is on the
    **top** face, so this is the same-layer case: the row names whichever
    regulator pad the capacitor sits beside — ``60.0 mil`` either way,
    ``pads 1 / 1`` in the first placement and ``pads 4 / 1`` in the second.
    ``component_distance`` on the same board answers 60.0 too, but from
    ``U1.1``↔``C7.2`` — the **ground** pad — which is the misattribution the
    pad-identity pin below is there to catch.
    """
    model = _model([
        _regulator(
            pins=[
                Pin("1", "VIN", SUPPLY),
                Pin("2", "VOUT", OUT_NET),
                Pin("3", "GND", GND),
                Pin("4", "VIN", SUPPLY),
            ]
        ),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])

    def board_with(cap_y: float) -> BoardGeometry:
        return _board(
            [("U1", 0.0, 100.0, TOP), ("C7", 100.0, cap_y, TOP)],
            [
                _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
                _pad("U1", "2", x=0.0, y=60.0, net=OUT_NET),
                _pad("U1", "3", x=0.0, y=120.0, net=GND),
                _pad("U1", "4", x=0.0, y=200.0, net=SUPPLY),
                _pad("C7", "1", x=100.0, y=cap_y, net=SUPPLY),
                _pad("C7", "2", x=100.0, y=cap_y + 40.0, net=AGND),
            ],
        )

    board = board_with(0.0)
    # The shared reader is not silent here, and its answer is a **different
    # pair**: U1's rail pad against C7's *ground* pad, which happens to be the
    # same number. That is why the pad identities are pinned, not just the gap.
    placement = component_distance(board, "U1", "C7")
    assert placement is not None
    assert (placement.pad_a, placement.pad_b) == ("1", "2")
    loop = same_net_loop_distance(board, "U1", "C7", SUPPLY)
    assert loop.edge_distance == pytest.approx(60.0)
    assert (loop.pad_a, loop.pad_b) == ("1", "1")
    hf = _rows(model, board)[("U1", "VIN", "HF")]
    assert hf.target.measurement == {
        "kind": "distance", "value": 60.0, "unit": "mil",
    }
    assert "pads 1 / 1" in hf.message

    # Beside the regulator's *other* VIN pin the row names that pin instead.
    board = board_with(200.0)
    loop = same_net_loop_distance(board, "U1", "C7", SUPPLY)
    assert loop.edge_distance == pytest.approx(60.0)
    assert (loop.pad_a, loop.pad_b) == ("4", "1")
    assert "pads 4 / 1" in _rows(model, board)[("U1", "VIN", "HF")].message


def test_the_nearest_candidate_is_the_one_reported_and_every_member_is_listed():
    """Two HF members on ``+12V``: the nearer one is the row, both are evidence.

    ``C8``'s pad sits at (100, 0) → ``100 - 40 = 60.0 mil``; ``C7``'s at
    (300, 0) → ``260.0 mil``. Both are on the **bottom** face while ``U1`` is on
    the top, so this is also the cross-layer case with a real choice in it.
    """
    model = _model([
        _regulator(),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
        _comp("C8", value="10nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    board = _board(
        [("U1", 0.0, 0.0, TOP), ("C7", 300.0, 0.0, BOTTOM), ("C8", 100.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
            _pad("U1", "3", x=0.0, y=80.0, net=GND),
            _pad("C7", "1", x=300.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C7", "2", x=300.0, y=40.0, net=AGND, layer=BOTTOM),
            _pad("C8", "1", x=100.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C8", "2", x=100.0, y=40.0, net=AGND, layer=BOTTOM),
        ],
    )
    assert component_distance(board, "U1", "C7") is None
    assert component_distance(board, "U1", "C8") is None

    hf = _rows(model, board)[("U1", "VIN", "HF")]
    assert hf.target.counterpart_ref == "C8"
    assert hf.target.measurement["value"] == 60.0
    measured_line = next(
        line for line in hf.evidence if line.startswith("measured high-frequency")
    )
    assert "C7=260.0" in measured_line, measured_line
    assert "C8=60.0" in measured_line, measured_line


# ---------------------------------------------------------------------------
# 3. the three empty-pool paths, told apart
# ---------------------------------------------------------------------------


def _empty_board(pads_c7: list[PadGeometry] | None):
    """``U1`` plus, optionally, a placed ``C7`` with the pads given."""
    parts = [("U1", 0.0, 0.0, TOP)]
    pads = [
        _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
        _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
        _pad("U1", "3", x=0.0, y=80.0, net=GND),
    ]
    if pads_c7 is not None:
        parts.append(("C7", 100.0, 0.0, BOTTOM))
        pads += pads_c7
    return _board(parts, pads)


def test_no_candidate_at_all_is_the_design_statement():
    """Path A: nothing bridges ``+12V`` to a ground net — say only that."""
    model = _model([_regulator()])
    row = _rows(model, _empty_board(None))[("U1", "VIN", "HF")]
    assert row.target.counterpart_ref == ""
    assert row.target.measurement is None
    assert "(no capacitor on the net at all)" in row.message
    assert "not placed" not in row.message
    assert "no same-net pad pair" not in row.message


def test_a_candidate_this_board_does_not_place_keeps_the_old_path():
    """Path B: the netlist names ``C9``, this PCB document carries no ``C9``."""
    model = _model([
        _regulator(),
        _comp("C9", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    row = _rows(model, _empty_board(None))[("U1", "VIN", "HF")]
    assert row.target.counterpart_ref == ""
    assert row.target.measurement is None
    assert "candidates exist but none is placed on this PCB document" in row.message
    assert any("not placed on this PCB document: C9" in line for line in row.evidence)


def test_a_placed_candidate_with_no_pad_on_the_net_is_unmeasurable_not_unplaced():
    """Path C — **the issue's second half.** On the board, but no ``+12V`` pad.

    ``C7`` is placed (so :meth:`BoardGeometry.component` finds it) but both its
    pads are on other nets: ``GND`` and ``AGND``. There is no supply leg to
    measure, so the row is unmeasurable — never 0 mil, never 「none is placed」.
    """
    board = _empty_board([
        _pad("C7", "1", x=100.0, y=0.0, net=GND, layer=BOTTOM),
        _pad("C7", "2", x=100.0, y=40.0, net=AGND, layer=BOTTOM),
    ])
    assert board.component("C7") is not None
    assert same_net_loop_distance(board, "U1", "C7", SUPPLY) is None
    model = _model([
        _regulator(),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    row = _rows(model, board)[("U1", "VIN", "HF")]
    assert row.severity == "INFO"
    assert row.target.counterpart_ref == ""
    assert row.target.measurement is None
    assert "none is placed" not in row.message
    assert "no same-net pad pair on '+12V' is measurable" in row.message
    assert "unmeasurable, not 0 mil" in row.message
    assert any(
        "on this PCB document with no pad on '+12V': C7" in line
        for line in row.evidence
    )


def test_both_empty_reasons_are_reported_together_rather_than_one_standing_in():
    """One unplaced candidate and one placed-but-padless: the row says both.

    A single reason would be a false statement about the other candidate, which
    is the failure mode #89 filed — the old wording claimed 「none is placed」
    about a part that is placed.
    """
    board = _empty_board([
        _pad("C7", "1", x=100.0, y=0.0, net=GND, layer=BOTTOM),
        _pad("C7", "2", x=100.0, y=40.0, net=AGND, layer=BOTTOM),
    ])
    model = _model([
        _regulator(),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
        _comp("C9", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    row = _rows(model, board)[("U1", "VIN", "HF")]
    assert "none is placed on this PCB document" not in row.message
    assert "some candidates are not placed on this PCB document" in row.message
    assert "no measurable same-net pad pair" in row.message
    evidence = " ".join(row.evidence)
    assert "not placed on this PCB document: C9" in evidence
    assert "on this PCB document with no pad on '+12V': C7" in evidence


def test_an_empty_pool_on_a_populated_net_says_pool_not_net():
    """Path D (#89 review): the net has a candidate, **this** pool has none.

    ``+12V`` carries a 10 µF storage capacitor, so the storage pool has a
    reading — and the high-frequency pool has none because the net's only
    candidate is in the other pool, not because the net is empty. Until the
    review the empty-pool row of *every* pool printed 「no capacitor on the net
    at all」 and its evidence printed 「no candidate capacitor bridges …」
    directly under a candidate list that named that capacitor.
    """
    model = _model([
        _regulator(),
        _comp("C6", value="10uF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", GND)]),
    ])
    board = _board(
        [("U1", 0.0, 40.0, TOP), ("C6", 200.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
            _pad("U1", "3", x=0.0, y=80.0, net=GND),
            _pad("C6", "1", x=200.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C6", "2", x=200.0, y=40.0, net=GND, layer=BOTTOM),
        ],
    )

    storage = _rows(model, board)[("U1", "VIN", "STORAGE")]
    assert storage.target.counterpart_ref == "C6"
    assert storage.target.measurement == {
        "kind": "distance", "value": 160.0, "unit": "mil",
    }

    hf = _rows(model, board)[("U1", "VIN", "HF")]
    assert hf.target.counterpart_ref == ""
    assert hf.target.measurement is None
    assert "the VIN high-frequency bypass pool is empty on this net" in hf.message
    assert "no capacitor on the net at all" not in hf.message
    assert "not placed" not in hf.message
    assert "the net is not empty: C6 on '+12V' is outside this pool" in hf.message
    assert not any(
        "no candidate capacitor bridges" in line for line in hf.evidence
    )
    assert any(
        "candidates bridging '+12V' to a ground net are outside this pool: C6"
        in line
        for line in hf.evidence
    )


# ---------------------------------------------------------------------------
# 4. one context, two rules, one number
# ---------------------------------------------------------------------------

def test_the_regulator_rule_and_decap_distance_report_the_same_loop_gap():
    """The consistency 164c established, now on the regulator side too.

    ``U1`` sits at x=0 on the top face and ``C7`` at x=400 on the bottom, both
    with a ``+12V`` pad at their own y=0: the loop leg is ``400 - 40 = 360.0
    mil``. ``DecapDistance`` grades that against the 300 mil 稳压器输入档 line
    and emits its WARN carrying 360.0; ``RegulatorCapDistance`` emits its INFO
    carrying the same 360.0. Two rules, one context, one number — and the number
    is the same-net pad-to-pad projection, not ``component_distance``'s
    placement gap (which is ``None`` here, all pairs being same-net or
    cross-layer).
    """
    model = _model([
        _regulator(),
        _comp("C7", value="100nF", pins=[Pin("1", "1", SUPPLY), Pin("2", "2", AGND)]),
    ])
    board = _board(
        [("U1", 0.0, 0.0, TOP), ("C7", 400.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("U1", "2", x=0.0, y=40.0, net=OUT_NET),
            _pad("U1", "3", x=0.0, y=80.0, net=GND),
            _pad("C7", "1", x=400.0, y=0.0, net=SUPPLY, layer=BOTTOM),
            _pad("C7", "2", x=400.0, y=40.0, net=AGND, layer=BOTTOM),
        ],
    )
    ctx = _ctx(board, model)
    decap = [f for f in DecapDistance().check(ctx) if f.target.counterpart_ref]
    assert len(decap) == 1
    assert decap[0].target.component_ref == "U1"
    assert decap[0].target.net_refs == [SUPPLY]
    assert decap[0].target.counterpart_ref == "C7"
    assert decap[0].target.measurement["value"] == 360.0
    assert decap[0].severity == "WARN"

    regulator = _rows(model, board)[("U1", "VIN", "HF")]
    assert regulator.target.counterpart_ref == "C7"
    assert regulator.target.measurement["value"] == decap[0].target.measurement["value"]
    assert component_distance(board, "U1", "C7") is None


# ---------------------------------------------------------------------------
# 5. the shared primitive is untouched
# ---------------------------------------------------------------------------


def test_component_distance_still_reads_cross_net_pairs_and_refuses_the_rest():
    """``component_distance`` keeps both 127b refusals and its cross-net answer.

    Pinned here rather than in its own suite so a future reader sees the two
    readers side by side, with one board per clause:

    * **same-net, same layer** → ``None`` (the refusal this rule's old reading
      ran into);
    * **cross-net, cross-layer** → ``None``, even though the two pads sit at the
      very same coordinates and a layer-blind reading would answer 0.0 — the
      refusal is about the faces, not about the gap;
    * **cross-net, same layer** → a real number, 60.0 mil between ``U1``'s
      ``+12V`` pad and ``C7``'s ``OUT_NET`` pad, which is the reading
      ``pcb-component-spacing`` and ``pcb-voltage-spacing`` are built on.
    """
    same_net_board = _board(
        [("U1", 0.0, 0.0, TOP), ("C7", 100.0, 0.0, TOP)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("C7", "1", x=100.0, y=0.0, net=SUPPLY),
        ],
    )
    assert component_distance(same_net_board, "U1", "C7") is None

    # Cross-net **and** cross-layer, with the pads exactly on top of each other
    # in plan view: overlapping rectangles, so the only thing standing between
    # this pair and a fabricated 0.0 mil is the layer refusal.
    cross_layer_board = _board(
        [("U1", 0.0, 0.0, TOP), ("C7", 0.0, 0.0, BOTTOM)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("C7", "1", x=0.0, y=0.0, net=OUT_NET, layer=BOTTOM),
        ],
    )
    assert component_distance(cross_layer_board, "U1", "C7") is None

    cross_net_board = _board(
        [("U1", 0.0, 0.0, TOP), ("C7", 100.0, 0.0, TOP)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=SUPPLY),
            _pad("C7", "1", x=100.0, y=0.0, net=OUT_NET),
        ],
    )
    reading = component_distance(cross_net_board, "U1", "C7")
    assert reading is not None
    assert reading.edge_distance == pytest.approx(60.0)
    # ... and the loop reader answers on the net, not on the pair: nothing on
    # ``SUPPLY`` for the cross-net board, 60.0 for the same-net one.
    assert same_net_loop_distance(
        cross_net_board, "U1", "C7", SUPPLY
    ) is None
    assert same_net_loop_distance(
        same_net_board, "U1", "C7", SUPPLY
    ).edge_distance == pytest.approx(60.0)
