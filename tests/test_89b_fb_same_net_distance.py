"""Issue #89B: ``pcb-regulator-fb-placement`` measures its capacitors **on the net**.

The defect. #89A gave ``pcb-regulator-cap-distance`` a same-net, layer-blind
reader (:func:`boardwise.rules.pcb.regulator.same_net_loop_distance`) and left
this rule on the old one. So both of its capacitor numbers —
「how far is the upper leg from the nearest output capacitor」 and 「how far is
the FB-pin from the FB-node capacitor」 — were taken with
:func:`boardwise.core.measure.component_distance`, which refuses **same-net**
pairs (127b: two pads of one net meeting is the design) and **cross-layer**
ones (127a). Both numbers are same-net *by construction*: the output capacitor
shares the output net with the upper leg, and the FB-node capacitor shares the
tap net with the FB pin. Every real pair was therefore refused, ``None`` came
back, and the rule wrote it as 「no capacitor … is placed on this PCB
document」 — about parts :meth:`BoardGeometry.component` had already proved are
on the board, and merging 「nothing is drawn」, 「not on this document」 and
「on the board but unmeasurable」 into one sentence.

The fix, in the task book's order:

1. the output-capacitor gap is measured from the **upper leg** on each
   ``output_net`` — ``same_net_loop_distance(board, divider.upper, candidate,
   output_net)`` — and a nearer pad on another net cannot stand in for it;
2. the FB-node gap is measured from the **IC's FB pad** on the tap net —
   ``same_net_loop_distance(board, divider.ic, candidate, divider.tap_net)`` —
   so a ground or bootstrap pad of that capacitor does not enter the minimum;
3. the IC→leg reading is **unchanged** (:func:`component_distance`, the
   IC-to-leg 口径, neither of them a decoupling loop), and so are the severity,
   verdict and the ``measurement`` anchor on the upper leg;
4. same-net cross-layer SMD pairs are **measured**, and the four states a
   reading can be in (measured / nothing drawn / not on this document / placed
   with no pad on the net) are four different sentences, the last one
   unmeasurable — not ``0 mil`` and not 「not placed」;
5. the real 毕设FOC 1.0.0 row is re-pinned to the numbers the offline rule
   actually prints.

**Every number below is a subtraction**, deliberately: pads are 40×40, so an
on-axis gap is ``|dx| - 40``. The fixture row at the end is read, not written:
it comes out of ``run_pcb_review`` over the real ``.epro2``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.measure import component_distance
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.pcbreview import run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.fbplacement import (
    BASIS_CROSS_NET,
    BASIS_SAME_NET,
    CAP_MEASURED,
    CAP_NO_ANCHOR_PAD,
    CAP_NO_CANDIDATE,
    CAP_NO_SAME_NET_PAD,
    CAP_NOT_PLACED,
    SENSE_CAP_RAIL,
    FbDivider,
    RegulatorFbPlacement,
)
from boardwise.rules.pcb.regulator import same_net_loop_distance

OUT = "+5V"
TAP = "TAP"
BST = "BST"
GND = "GND"

TOP = 1
BOTTOM = 2

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"


# ---------------------------------------------------------------------------
# synthetic helpers — 40x40 pads, so every gap below is a subtraction
# ---------------------------------------------------------------------------


def _pad(
    component: str, pin: str, *, x: float, y: float, net: str, layer: int = TOP
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


def _resistor(designator: str, a: str, b: str) -> Component:
    return _comp(designator, value="100k", pins=[Pin("1", "1", a), Pin("2", "2", b)])


def _cap(designator: str, value: str, a: str, b: str) -> Component:
    return _comp(designator, value=value, pins=[Pin("1", "1", a), Pin("2", "2", b)])


def _regulator(designator: str = "U1", *, fb_net: str = TAP, out: bool = True) -> Component:
    """An ``ic.buck`` with a ``VOUT``-named pin (so the output node is declared).

    ``out=False`` drops the output pin, which is how the 「no output node
    established」 path is reached without the rule guessing one.
    """
    pins = [Pin("3", "GND", GND)]
    if out:
        pins.insert(0, Pin("1", "VOUT", OUT))
    pins.append(Pin("2", "FB", fb_net))
    return _comp(designator, mpn="SYNTHREG", lcsc="C0", pins=pins)


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


def _shelf() -> PartLibrary:
    return PartLibrary(
        parts=[
            PartEntry(
                key="test.synthreg.c0", mpn="SYNTHREG", lcsc="C0", category="ic.buck"
            )
        ]
    )


def _rows(model: DesignModel, board: BoardGeometry) -> list:
    ctx = PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=model,
        intent=None,
        module_of={},
        pcb_model=model,
    )
    return RegulatorFbPlacement().check_with_library(ctx, _shelf())


def _row(model: DesignModel, board: BoardGeometry):
    rows = _rows(model, board)
    assert len(rows) == 1, "one divider, one row"
    return rows[0]


# ---------------------------------------------------------------------------
# the geometry every test starts from
#
#   U1   top:    p1 VOUT  (+5V)  (0,0)      p2 FB (TAP) (0,60)
#                p3 GND   (GND)  (0,120)
#   R1   top:    p1       (+5V)  (100,0)    p2 (TAP) (100,40)   ← upper leg
#   R2   top:    p1       (TAP)  (100,80)   p2 (GND) (100,120)  ← lower leg
#   C1   bottom: p1 10uF  (+5V)  (300,0)    p2 (GND) (150,0)
#   C2   bottom: p1 100nF (+5V)  (240,0)    p2 (GND) (240,80)
#   C3   bottom: p1 100nF (TAP)  (400,60)   p2 (BST) (60,60)   ← FB-node cap
# ---------------------------------------------------------------------------


def _divider_model(*, caps: list[Component] | None = None) -> DesignModel:
    return _model(
        [
            _regulator(),
            _resistor("R1", OUT, TAP),
            _resistor("R2", TAP, GND),
            *(
                [_cap("C1", "10uF", OUT, GND), _cap("C2", "100nF", OUT, GND),
                 _cap("C3", "100nF", TAP, BST)]
                if caps is None
                else caps
            ),
        ]
    )


def _divider_board(*, drop: tuple[str, ...] = ()) -> BoardGeometry:
    pads = [
        _pad("U1", "1", x=0.0, y=0.0, net=OUT),
        _pad("U1", "2", x=0.0, y=60.0, net=TAP),
        _pad("U1", "3", x=0.0, y=120.0, net=GND),
        _pad("R1", "1", x=100.0, y=0.0, net=OUT),
        _pad("R1", "2", x=100.0, y=40.0, net=TAP),
        _pad("R2", "1", x=100.0, y=80.0, net=TAP),
        _pad("R2", "2", x=100.0, y=120.0, net=GND),
        _pad("C1", "1", x=300.0, y=0.0, net=OUT, layer=BOTTOM),
        _pad("C1", "2", x=150.0, y=0.0, net=GND, layer=BOTTOM),
        _pad("C2", "1", x=240.0, y=0.0, net=OUT, layer=BOTTOM),
        _pad("C2", "2", x=240.0, y=80.0, net=GND, layer=BOTTOM),
        _pad("C3", "1", x=400.0, y=60.0, net=TAP, layer=BOTTOM),
        _pad("C3", "2", x=60.0, y=60.0, net=BST, layer=BOTTOM),
    ]
    pads = [pad for pad in pads if pad.component not in drop]
    parts = [
        ("U1", 0.0, 60.0, TOP),
        ("R1", 100.0, 0.0, TOP),
        ("R2", 100.0, 80.0, TOP),
        ("C1", 300.0, 0.0, BOTTOM),
        ("C2", 240.0, 0.0, BOTTOM),
        ("C3", 400.0, 60.0, BOTTOM),
    ]
    return _board([part for part in parts if part[0] not in drop], pads)


# ---------------------------------------------------------------------------
# 1. the output capacitor: measured from the upper leg, on the output net
# ---------------------------------------------------------------------------


def test_the_output_cap_is_measured_from_the_upper_leg_on_the_output_net():
    """The issue's own pair: same net **and** cross-layer, so the old reader is blind.

    ``R1``'s output pad is on the top face, ``C1``'s on the bottom, and both are
    ``+5V``. :func:`component_distance` refuses that pair twice over and answers
    ``None``; the rule must not turn that into 「no capacitor is placed」 — and it
    must not report the **nearer** pad either: ``C1``'s ground pad sits 10.0 mil
    from ``R1``'s output pad in plan view, while the output net's own gap is
    ``(300 - 20) - (100 + 20) = 160.0 mil``. The reported pad pair is ``1 / 1``
    — the leg's ``+5V`` pad against the capacitor's — which is what makes the
    number the loop rather than a coincidence.
    """
    model, board = _divider_model(), _divider_board()

    assert component_distance(board, "R1", "C1") is None
    loop = same_net_loop_distance(board, "R1", "C1", OUT)
    assert loop is not None
    assert loop.edge_distance == pytest.approx(160.0)
    assert (loop.pad_a, loop.pad_b) == ("1", "1")

    # The nearer pair on another net, stated so the pin below is about the filter
    # and not about a coincidence in the layout.
    nearer = min(
        math.dist((a.x, a.y), (b.x, b.y))
        for a in board.pads_for_component("R1")
        for b in board.pads_for_component("C1")
    )
    assert nearer == pytest.approx(math.hypot(50.0, 0.0))

    row = _row(model, board)
    assert row.severity == "INFO"
    assert (
        "the nearest energy storage capacitor on that output node is C1 at "
        "160.0 mil from the upper leg R1 (pads 1 / 1)"
    ) in row.message
    assert "no capacitor on +5V" not in row.message
    assert "has no pad on +5V" not in row.message
    assert "state measured" in " ".join(row.evidence)


# ---------------------------------------------------------------------------
# 2. the FB-node capacitor: measured from the FB pad, on the tap net
# ---------------------------------------------------------------------------


def test_the_fb_node_cap_is_measured_from_the_fb_pad_on_the_tap_net():
    """``C3`` is on the tap and on the bottom face; its bootstrap pad is nearer.

    ``U1``'s ``FB`` pad is ``(0, 60)`` on the top face; ``C3``'s ``TAP`` pad is
    ``(400, 60)`` on the bottom (``360.0 mil``), and its ``BST`` pad is
    ``(60, 60)`` on the bottom (``20.0 mil``). A net-blind or layer-blind
    minimum reports 20.0 against a bootstrap pad; the reading is on the tap net,
    so it reports 360.0 with pads ``2 / 1`` — the IC's ``FB`` pad and the
    capacitor's tap pad.

    ``component_distance`` answers ``None`` for the pair (cross-layer), which is
    the defect #89B closes: the FB-node capacitor is on the board and is
    measurable in plan view.
    """
    model, board = _divider_model(), _divider_board()

    assert component_distance(board, "U1", "C3") is None
    loop = same_net_loop_distance(board, "U1", "C3", TAP)
    assert loop is not None
    assert loop.edge_distance == pytest.approx(360.0)
    assert (loop.pad_a, loop.pad_b) == ("2", "1")
    # The other nets of those two parts answer None — no pad of the other part.
    assert same_net_loop_distance(board, "U1", "C3", BST) is None
    assert same_net_loop_distance(board, "U1", "C3", GND) is None

    row = _row(model, board)
    assert (
        "FB-node capacitor C3 at 360.0 mil from U1 on the tap net 'TAP' "
        "(pads 2 / 1)"
    ) in row.message
    assert "20.0 mil" not in row.message


# ---------------------------------------------------------------------------
# 3. several candidates: the pool rule and the leg readings are unchanged
# ---------------------------------------------------------------------------


def test_the_pool_rule_and_the_leg_readings_are_unchanged():
    """``C2`` (100 nF) is nearer than ``C1`` (10 µF), and storage still wins.

    The whole point of the pool split is that the nearest *bypass* capacitor is
    a real measurement and a misleading answer to 「where is the output
    capacitor」: ``C2`` sits ``(240 - 20) - (100 + 20) = 100.0 mil`` from the leg
    against ``C1``'s 160.0, and the row still names ``C1`` with its pool label.
    With ``C1`` gone the same board reports ``C2`` at 100.0 — the in-pool
    nearest, not a fallback to 「no capacitor」.

    The two leg readings are the ones that did **not** move in this batch: they
    are :func:`component_distance` from the IC, and ``measurement`` still
    anchors the nearer leg.
    """
    model, board = _divider_model(), _divider_board()
    row = _row(model, board)
    assert "energy storage" in row.message
    assert "C1 at 160.0 mil" in row.message

    legs = {
        "R1": component_distance(board, "U1", "R1"),
        "R2": component_distance(board, "U1", "R2"),
    }
    assert all(distance is not None for distance in legs.values())
    assert "upper leg R1 at " in row.message and "lower leg R2 at " in row.message
    for role, designator in (("upper", "R1"), ("lower", "R2")):
        distance = legs[designator]
        assert (
            f"{role} leg {designator} at {distance.edge_distance:.1f} mil "
            f"(pads {distance.pad_a} / {distance.pad_b})"
        ) in row.message
    assert row.target.counterpart_ref == "R1"
    assert row.target.measurement == {
        "kind": "distance",
        "value": round(min(d.edge_distance for d in legs.values()), 1),
        "unit": "mil",
    }

    # Only the bypass pool is populated: the in-pool nearest is what is reported.
    only_hf = _divider_model(
        caps=[_cap("C2", "100nF", OUT, GND), _cap("C3", "100nF", TAP, BST)]
    )
    assert (
        "the nearest high-frequency bypass capacitor on that output node is C2 "
        "at 100.0 mil"
    ) in _row(only_hf, _divider_board()).message


# ---------------------------------------------------------------------------
# 4. the empty paths, told apart — output capacitor
# ---------------------------------------------------------------------------


def test_the_three_empty_output_cap_paths_are_three_sentences():
    """Nothing drawn / not on this document / on it but no pad on the net.

    The old code collapsed the last two into 「no capacitor on ``+5V`` is placed
    on this PCB document」, which is a false statement about a part the board
    places. Each state gets its own sentence here, and the unmeasurable one says
    what it is: not ``0 mil``.
    """
    # (a) nothing on the output node reads as a capacitor at all.
    no_cap = _divider_model(caps=[_cap("C3", "100nF", TAP, BST)])
    row = _row(no_cap, _divider_board())
    assert "no capacitor is drawn on +5V at all" in row.message
    assert "are not placed on this PCB document" not in row.message
    assert "has no pad on +5V" not in row.message

    # (b) the netlist has them, this document places neither.
    row = _row(_divider_model(), _divider_board(drop=("C1", "C2")))
    assert (
        "the capacitors on +5V (C1, C2) are not placed on this PCB document"
    ) in row.message
    assert "no capacitor is drawn on +5V" not in row.message
    assert "has no pad on +5V" not in row.message

    # (c) placed, but no pad of it carries the output net: unmeasurable.
    board = _divider_board(drop=("C1", "C2"))
    board = BoardGeometry(
        source=board.source,
        name=board.name,
        components=list(board.components)
        + [
            ComponentPlacement(id="c-C1", designator="C1", x=300.0, y=0.0, layer_id=BOTTOM),
            ComponentPlacement(id="c-C2", designator="C2", x=240.0, y=0.0, layer_id=BOTTOM),
        ],
        pads=list(board.pads)
        + [
            _pad("C1", "1", x=300.0, y=0.0, net="NET_ALT_A", layer=BOTTOM),
            _pad("C1", "2", x=150.0, y=0.0, net="NET_ALT_B", layer=BOTTOM),
            _pad("C2", "1", x=240.0, y=0.0, net="NET_ALT_A", layer=BOTTOM),
            _pad("C2", "2", x=240.0, y=80.0, net="NET_ALT_B", layer=BOTTOM),
        ],
    )
    row = _row(_divider_model(), board)
    assert (
        "C1, C2 is placed on this PCB document but has no pad on +5V, so the "
        "sensing point's gap is unmeasurable — not 0 mil"
    ) in row.message
    assert "no capacitor is drawn on +5V" not in row.message
    assert "are not placed on this PCB document" not in row.message

    # And the state itself is exposed in the evidence, so a reader of a report
    # does not have to parse prose to see which of the four they are looking at.
    evidence = " ".join(row.evidence)
    assert f"state {CAP_NO_SAME_NET_PAD}" in evidence
    assert f"state {CAP_NO_CANDIDATE}" not in evidence
    assert f"state {CAP_NOT_PLACED}" not in evidence
    assert f"state {CAP_MEASURED}" not in evidence


# ---------------------------------------------------------------------------
# 5. the empty paths, told apart — FB-node capacitor
# ---------------------------------------------------------------------------


def test_the_three_empty_fb_node_cap_paths_are_three_sentences():
    """Same three states for the tap, and the tap's members are still quoted."""
    # (a) the tap carries no capacitor at all (it is still loaded — by the FB pin).
    row = _row(_divider_model(caps=[_cap("C1", "10uF", OUT, GND)]), _divider_board())
    assert "no capacitor is drawn on the FB node 'TAP'" in row.message
    assert "are not placed on this PCB document" not in row.message
    assert "no pad on the FB node" not in row.message

    # (b) drawn, but this document places it nowhere.
    row = _row(_divider_model(), _divider_board(drop=("C3",)))
    assert (
        "the capacitors on the FB node 'TAP' (C3) are not placed on this PCB "
        "document"
    ) in row.message
    assert "no capacitor is drawn on the FB node" not in row.message

    # (c) placed, but its pads carry neither side of the tap net.
    board = _divider_board(drop=("C3",))
    board = BoardGeometry(
        source=board.source,
        name=board.name,
        components=list(board.components)
        + [ComponentPlacement(id="c-C3", designator="C3", x=400.0, y=60.0, layer_id=BOTTOM)],
        pads=list(board.pads)
        + [
            _pad("C3", "1", x=400.0, y=60.0, net="NET_ALT_A", layer=BOTTOM),
            _pad("C3", "2", x=60.0, y=60.0, net="NET_ALT_B", layer=BOTTOM),
        ],
    )
    row = _row(_divider_model(), board)
    assert (
        "C3 is placed on this PCB document but has no pad on the FB node 'TAP', "
        "so its gap is unmeasurable — not 0 mil"
    ) in row.message
    assert f"state: {CAP_NO_SAME_NET_PAD}" in " ".join(row.evidence)


# ---------------------------------------------------------------------------
# 5b. #89 review: the anchor side, the rail-side shape, several output nets
# ---------------------------------------------------------------------------


RAIL_12 = "+12V"
OUT2 = "OUT2"


def _rail_side_model() -> DesignModel:
    """``R1`` spans ``+12V``/``TAP`` — the ``SENSE_CAP_RAIL`` shape.

    The regulator's output pin is on ``+5V`` while the upper leg's non-tap end is
    on ``+12V``, so ``divider.rail_net`` is **not** one of this regulator's
    output nets. The upper leg therefore has no pad on ``+5V`` *by construction*
    and #89B's same-net loop cannot exist. The pre-review code asked for it
    anyway, got ``None`` for every candidate, and printed that as the
    capacitor's fault — a structural non-reading written as a defect.
    """
    return _model([
        _comp(
            "U1",
            mpn="SYNTHREG",
            lcsc="C0",
            pins=[
                Pin("1", "VOUT", OUT),
                Pin("2", "FB", TAP),
                Pin("3", "GND", GND),
            ],
        ),
        _resistor("R1", RAIL_12, TAP),
        _resistor("R2", TAP, GND),
        _cap("C1", "10uF", OUT, GND),
        _cap("C2", "100nF", OUT, GND),
    ])


def _rail_side_board() -> BoardGeometry:
    """``R1``'s pads are on ``+12V``/``TAP``; the capacitors are on ``+5V``.

    Every pad is 40x40. The nearest **cross-net** pair is ``R1.1`` (``+12V``,
    x 80..120) against ``C1.2`` (``GND``, x 280..320) — ``280 - 120 = 160.0 mil``
    — which is the reading the row must quote, on
    :data:`BASIS_CROSS_NET`, instead of 「unmeasurable」.
    """
    return _board(
        [
            ("U1", 0.0, 60.0, TOP),
            ("R1", 100.0, 0.0, TOP),
            ("R2", 100.0, 80.0, TOP),
            ("C1", 400.0, 0.0, BOTTOM),
            ("C2", 340.0, 160.0, BOTTOM),
        ],
        [
            _pad("U1", "1", x=0.0, y=0.0, net=OUT),
            _pad("U1", "2", x=0.0, y=60.0, net=TAP),
            _pad("U1", "3", x=0.0, y=120.0, net=GND),
            _pad("R1", "1", x=100.0, y=0.0, net=RAIL_12),
            _pad("R1", "2", x=100.0, y=40.0, net=TAP),
            _pad("R2", "1", x=100.0, y=80.0, net=TAP),
            _pad("R2", "2", x=100.0, y=120.0, net=GND),
            _pad("C1", "1", x=400.0, y=0.0, net=OUT, layer=BOTTOM),
            _pad("C1", "2", x=300.0, y=0.0, net=GND, layer=BOTTOM),
            _pad("C2", "1", x=340.0, y=160.0, net=OUT, layer=BOTTOM),
            _pad("C2", "2", x=340.0, y=240.0, net=GND, layer=BOTTOM),
        ],
    )


def test_the_rail_side_shape_reads_a_cross_net_gap_instead_of_blaming_the_cap():
    """``SENSE_CAP_RAIL`` keeps a useful number, on a stated reading basis.

    The upper leg has no ``+5V`` pad, so the same-net loop is not a reading that
    *failed* — it is a reading that does not exist for this topology. The row
    quotes the nearest cross-net pad pair and says that is what it is (#89
    review), instead of 「C1, C2 … has no pad on +5V」 about two capacitors that
    are exactly where the drawing puts them.
    """
    model, board = _rail_side_model(), _rail_side_board()
    assert same_net_loop_distance(board, "R1", "C1", OUT) is None

    row = _row(model, board)
    assert SENSE_CAP_RAIL in row.message
    assert (
        "the nearest energy storage capacitor on that output node is C1 at "
        "160.0 mil from the upper leg R1 (pads 1 / 2)"
    ) in row.message
    assert "cross-net" in row.message
    assert "has no pad on +5V" in row.message  # the **anchor**, and the row says so
    assert "is placed on this PCB document but has no pad on" not in row.message
    assert "unmeasurable" not in row.message

    evidence = " ".join(row.evidence)
    assert f"reading basis {BASIS_CROSS_NET}" in evidence
    assert f"state {CAP_MEASURED}" in evidence
    assert "anchor R1 has no pad on +5V" in evidence
    assert "placed but with no pad on the node (none)" in evidence


def test_the_ic_without_a_tap_pad_is_the_anchor_side_not_the_fb_cap():
    """The FB-node reading's anchor is the **IC**, and the row says so.

    ``U1`` is placed but no pad of it carries ``TAP``, so the FB-node gap has no
    leg to measure. The old wording named ``C3`` — 「is placed on this PCB
    document but has no pad on the FB node 'TAP'」 — about a capacitor whose
    ``TAP`` pad is right there. #89 review: a separate state
    (:data:`CAP_NO_ANCHOR_PAD`), and the sentence names the IC.
    """
    board = _divider_board()
    board = BoardGeometry(
        source=board.source,
        name=board.name,
        components=list(board.components),
        pads=[pad for pad in board.pads if not (pad.component == "U1" and pad.net == TAP)],
    )

    row = _row(_divider_model(), board)
    assert "U1 has no pad on the FB node 'TAP' on this PCB document" in row.message
    assert "not the capacitors' doing" in row.message
    assert "C3 is placed on this PCB document but has no pad on the FB node" not in (
        row.message
    )
    evidence = " ".join(row.evidence)
    assert f"state: {CAP_NO_ANCHOR_PAD}" in evidence
    assert f"state: {CAP_NO_SAME_NET_PAD}" not in evidence


def test_a_measured_capacitor_is_not_also_listed_as_missing_another_output_nets_pad():
    """Two output nets: a part measured on one is not 「missing」 the other's pad.

    ``U1`` names two output pins (``VOUT`` on ``+5V``, ``OUT_1`` on ``OUT2``),
    and ``C1`` — a case-grounded 10 µF capacitor — has a pad on each of them. The
    measurement on ``+5V`` succeeds (``160.0 mil``, pads ``1 / 1``); the second
    output net has no pad of the **anchor** and, in the pre-review code, added
    ``C1`` to the 「placed but with no pad on the node」 list — the same
    designator printed as measured and as missing in one evidence block (#89
    review). The anchor side is what the second net lacks, and the evidence says
    that instead.
    """
    model = _model([
        _comp(
            "U1",
            mpn="SYNTHREG",
            lcsc="C0",
            pins=[
                Pin("1", "VOUT", OUT),
                Pin("4", "OUT_1", OUT2),
                Pin("2", "FB", TAP),
                Pin("3", "GND", GND),
            ],
        ),
        _resistor("R1", OUT, TAP),
        _resistor("R2", TAP, GND),
        _comp(
            "C1",
            value="10uF",
            pins=[
                Pin("1", "1", OUT),
                Pin("2", "2", OUT2),
                Pin("3", "3", GND),
            ],
        ),
    ])
    board = _board(
        [
            ("U1", 0.0, 160.0, TOP),
            ("R1", 100.0, 0.0, TOP),
            ("R2", 100.0, 80.0, TOP),
            ("C1", 300.0, 0.0, BOTTOM),
        ],
        [
            _pad("U1", "1", x=0.0, y=60.0, net=OUT),
            _pad("U1", "4", x=0.0, y=100.0, net=OUT2),
            _pad("U1", "2", x=0.0, y=140.0, net=TAP),
            _pad("U1", "3", x=0.0, y=180.0, net=GND),
            _pad("R1", "1", x=100.0, y=0.0, net=OUT),
            _pad("R1", "2", x=100.0, y=40.0, net=TAP),
            _pad("R2", "1", x=100.0, y=80.0, net=TAP),
            _pad("R2", "2", x=100.0, y=120.0, net=GND),
            _pad("C1", "1", x=300.0, y=0.0, net=OUT, layer=BOTTOM),
            _pad("C1", "2", x=300.0, y=40.0, net=OUT2, layer=BOTTOM),
            _pad("C1", "3", x=300.0, y=80.0, net=GND, layer=BOTTOM),
        ],
    )

    row = _row(model, board)
    assert (
        "the nearest energy storage capacitor on that output node is C1 at "
        "160.0 mil from the upper leg R1 (pads 1 / 1)"
    ) in row.message
    evidence = " ".join(row.evidence)
    assert f"state {CAP_MEASURED}" in evidence
    assert f"reading basis {BASIS_SAME_NET}" in evidence
    # The second output net has no anchor pad, and that is the stated reason —
    # not a capacitor that is missing a pad it demonstrably has.
    assert "anchor R1 has no pad on OUT2" in evidence
    assert "placed but with no pad on the node (none)" in evidence
    assert "is placed on this PCB document but has no pad on" not in row.message


def test_a_part_measured_on_one_output_net_is_not_also_listed_as_missing_another():
    """#89 review: the measured list wins over the missing-pad list.

    The reading this pins is the one the divider walk produces when a regulator
    names two output nets **and the anchor leg has a pad on both** while the
    capacitor has one on the first only: the second net's gap is ``None`` (the
    capacitor really has no pad there) *and* the same designator was just
    measured on the first. Printing both facts is a contradiction, so the
    measured name stays out of the 「placed but with no pad on the node」 list.
    The leg is given three pads here because that is what the shape requires;
    the divider is built directly so the test is about the reading rather than
    about the divider walk, which has its own tests above.
    """
    model = _model([
        _comp(
            "U1",
            mpn="SYNTHREG",
            lcsc="C0",
            pins=[
                Pin("1", "VOUT", OUT),
                Pin("4", "OUT_1", OUT2),
                Pin("2", "FB", TAP),
                Pin("3", "GND", GND),
            ],
        ),
        _resistor("R2", TAP, GND),
        _comp(
            "R1",
            value="100k",
            pins=[
                Pin("1", "1", OUT),
                Pin("2", "2", TAP),
                Pin("3", "3", OUT2),
            ],
        ),
        _comp(
            "C1",
            value="10uF",
            pins=[
                Pin("1", "1", OUT),
                Pin("2", "2", GND),
                Pin("3", "3", OUT2),
            ],
        ),
    ])
    board = _board(
        [
            ("U1", 0.0, 160.0, TOP),
            ("R1", 100.0, 0.0, TOP),
            ("R2", 100.0, 80.0, TOP),
            ("C1", 300.0, 0.0, BOTTOM),
        ],
        [
            _pad("U1", "1", x=0.0, y=60.0, net=OUT),
            _pad("U1", "4", x=0.0, y=100.0, net=OUT2),
            _pad("U1", "2", x=0.0, y=140.0, net=TAP),
            _pad("U1", "3", x=0.0, y=180.0, net=GND),
            _pad("R1", "1", x=100.0, y=0.0, net=OUT),
            _pad("R1", "2", x=100.0, y=40.0, net=TAP),
            _pad("R1", "3", x=100.0, y=80.0, net=OUT2),
            _pad("R2", "1", x=100.0, y=120.0, net=TAP),
            _pad("R2", "2", x=100.0, y=160.0, net=GND),
            _pad("C1", "1", x=300.0, y=0.0, net=OUT, layer=BOTTOM),
            _pad("C1", "2", x=300.0, y=80.0, net=GND, layer=BOTTOM),
        ],
    )
    divider = FbDivider(
        ic="U1",
        category="ic.buck",
        fb_pin_number="2",
        fb_pin_name="FB",
        tap_net=TAP,
        upper="R1",
        lower="R2",
        rail_net=OUT,
        ground_net=GND,
        rail_volts=5.0,
        output_nets=(OUT, OUT2),
        output_basis="test: two pins whose names resolve to the OUT role",
    )

    reading = RegulatorFbPlacement()._nearest_output_cap(
        model, divider, board, _shelf()
    )
    assert reading.state == CAP_MEASURED
    assert reading.designator == "C1"
    assert reading.pool == "storage"
    assert reading.basis == BASIS_SAME_NET
    assert reading.candidates == ("C1",)
    assert reading.distance.edge_distance == pytest.approx(160.0)
    assert reading.unmeasurable == ()
    # The anchor has a pad on **both** output nets here, so the failure on
    # ``OUT2`` is the capacitor's own missing pad — recorded, then removed
    # because the same part is the measured winner.
    assert reading.anchor_without == ()


# ---------------------------------------------------------------------------
# 6. the real fixture, read rather than written
# ---------------------------------------------------------------------------


def test_the_real_fixture_row_carries_the_same_net_readings():
    """毕设FOC 1.0.0's ``U11`` row, as the offline rule actually prints it.

    The legs did not move (``U11 -> R14`` **37.2 mil**, pads 6/1; ``U11 -> R21``
    **47.4 mil**, pads 5/1 — still :func:`component_distance`), and the two
    capacitor numbers did:

    * the FB-node capacitor ``C92`` is **650.9 mil** from ``U11``'s ``FB`` pad
      on the tap ``$1N66466`` (pads 5/1), where the cross-net reading said
      638.8 (pads 8/1);
    * the nearest storage capacitor on ``+5V`` is ``C101`` at **684.1 mil** from
      ``R14`` (pads 2/1), where the cross-net reading said 745.2.

    Both are now the same net's own gap, and both say so in the evidence.
    """
    schematic, _geometry = cli._load_model(FOC_100, view="schematic")
    findings, _section = run_pcb_review(
        FOC_100, model=schematic, rules=[RegulatorFbPlacement()]
    )
    assert len(findings) == 1
    row = findings[0]
    assert row.target.component_ref == "U11"
    assert "upper leg R14 at 37.2 mil (pads 6 / 1)" in row.message
    assert "lower leg R21 at 47.4 mil (pads 5 / 1)" in row.message
    assert row.target.measurement == {
        "kind": "distance", "value": 37.2, "unit": "mil",
    }
    assert (
        "FB-node capacitor C92 at 650.9 mil from U11 on the tap net "
        "'$1N66466' (pads 5 / 1)"
    ) in row.message
    assert "C101 at 684.1 mil from the upper leg R14 (pads 2 / 1)" in row.message
    evidence = " ".join(row.evidence)
    assert "FB-node capacitor: C92 @ $1N66466 = 650.9 mil edge-to-edge" in evidence
    assert "state measured" in evidence
    assert f"state {CAP_MEASURED}" in evidence
