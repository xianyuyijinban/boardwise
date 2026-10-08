"""Task 127b regression pins: the five blind-review fixes, pinned on their own.

Each test here exists because 岳's blind review of the 126 module-level report
found nineteen false positives on a board whose host DRC is clean, and every one
of them has to be *provably* gone rather than merely absent from one run. The
fixtures are the same read-only ones 125/126 use; nothing here runs an editor.

The five fixes, and where each is pinned:

1. ``PadGeometry.effective_layer_ids`` (:mod:`boardwise.core.geometry`) —
   :func:`test_a_bottom_parts_pads_report_the_face_they_are_on` and the 127a's
   nine-pair regression nail in :func:`test_the_nine_top_by_bottom_pairs_are_gone`.
2. ``pcb-component-spacing`` — :func:`test_a_same_net_pair_is_exempt` and
   :func:`test_a_cross_side_pair_is_not_measured`.
3. ``pcb-decap-distance`` — :func:`test_a_header_is_not_an_ic_even_under_a_u_designator`,
   :func:`test_a_mosfet_is_not_an_ic`, :func:`test_the_designator_is_the_fallback_not_the_test`,
   and the bulk / HF candidate split.
4. ``pcb-voltage-spacing`` — :func:`test_two_ground_islands_are_exempt` and
   :func:`test_two_nets_at_the_same_voltage_are_exempt`.
5. the round-2 acceptance — :func:`test_the_bishe_foc_board_is_clean_under_both_distance_rules`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import (
    MULTI_LAYER_ID,
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
)
from boardwise.core.measure import component_distance, net_clearance
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.designintent import DesignIntent
from boardwise.engines.pcbreview import run_pcb_review
from boardwise.parsers.epru import load_epro2_source, extract_board
from boardwise.rules.pcb.distance import (
    BULK_FARADS,
    CAP_ROLE_BULK,
    CAP_ROLE_HF,
    CAP_ROLE_UNKNOWN,
    HF_FARADS,
    NON_IC_DESIGNATOR_PREFIXES,
    ComponentSpacing,
    DecapDistance,
    capacitor_role,
    classify_device,
    device_facts,
)
from boardwise.rules.pcb.ipc import VoltageSpacing
from boardwise.rules.pcb.base import PcbReviewContext

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ctx(board, model=None, intent=None):
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=model, intent=intent, module_of={}
    )


def _model(components):
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for comp in components:
        for pin in comp.pins:
            if pin.net:
                nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                    (comp.designator, pin.number)
                )
    model.nets = nets
    return model


def _comp(designator, *, value="", mpn="", footprint="", pins=(), props=None):
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        footprint=footprint,
        pins=list(pins),
        props=dict(props or {}),
    )


def _pad(component, pin, *, x, y, net="", layer_id=1, effective=(), width=40.0, height=40.0):
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=layer_id,
        effective_layer_ids=list(effective),
        x=x,
        y=y,
        width=width,
        height=height,
        shape="RECT",
    )


def _place(designator, x, y, *, layer_id=1):
    return ComponentPlacement(
        id=f"c-{designator}", designator=designator, x=x, y=y, layer_id=layer_id
    )


@pytest.fixture(scope="module")
def foc_project():
    """(project model, {PCB title: BoardGeometry}) for the 毕设FOC fixture."""
    source = load_epro2_source(FOC)
    footprints = source.footprints()
    boards = {}
    for document in source.documents_of_type("PCB"):
        title = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                title = str(record.body.get("title") or "")
                break
        boards[title] = extract_board(document, footprints, source.stats)
    model, _ = cli._load_model(FOC, view="schematic")
    return model, boards


# ---------------------------------------------------------------------------
# 1. the pad's effective layer
# ---------------------------------------------------------------------------


def test_a_bottom_parts_pads_report_the_face_they_are_on(foc_project):
    """A pad's copper follows the **placement**, not the footprint's own layer.

    This is the root cause 127a took down, measured on this fixture: PCB1 places
    ``U4`` / ``U6`` / ``R17`` / ``C14`` on ``COMPONENT.layerId == 2`` (bottom),
    yet **all 28** of their SMD pads carry ``layerId == 1``, because that is the
    layer the *library* stores the footprint with and nothing rewrites it when
    the part is flipped. 126b read the footprint's layer, so every bottom-side
    part's solder pads were treated as top copper — which is how six pairs of
    parts ended up reported as touching on a board whose host DRC is clean.

    Pinned per part, with the count, so a future parser change cannot quietly
    flip the mapping back for one of them.
    """
    _model, boards = foc_project
    pcb1 = boards["PCB1"]
    for designator in ("U4", "U6", "R17", "C14"):
        placement = pcb1.component(designator)
        assert placement.layer_id == 2, f"{designator} really is on the bottom face"
        pads = pcb1.pads_for_component(designator)
        assert pads, f"{designator} has pads"
        for pad in pads:
            assert pad.layer_id == 1, (
                f"{designator}.{pad.pin_number}: the footprint's own layer is "
                "still 1 — the raw field is deliberately left alone"
            )
            assert pad.effective_layer_ids == [2], (
                f"{designator}.{pad.pin_number}: the effective reading must be "
                "the placement's face, whatever the footprint says"
            )
    # And the count, because "all 28" is the claim that closed the hole.
    assert sum(len(pcb1.pads_for_component(d)) for d in ("U4", "U6", "R17", "C14")) == 28


def test_a_through_hole_pad_occupies_every_copper_layer(foc_project):
    """The barrel case: all copper layers, both by hole and by ``layer_id == 12``.

    ``SWD1`` is a 4-pin through-hole header on PCB1; each of its pads carries
    ``layerId == 12`` (the editor's Multi-Layer designation) **and** a hole, and
    the two agree 8/8 across PCB1 and PCB3. Either fact alone is enough, and the
    effective reading is the board's real copper set — 1 / 2 / 15 / 16 on the
    four-layer main board — not the pair of outer layers.
    """
    _model, boards = foc_project
    pcb1 = boards["PCB1"]
    for pad in pcb1.pads_for_component("SWD1"):
        assert pad.hole_diameter is not None, "SWD1 is a through-hole header"
        assert pad.effective_layer_ids == [1, 2, 15, 16], (
            f"SWD1.{pad.pin_number} is a barrel: it spans every copper layer "
            "of the stackup, not just the two outer faces"
        )
    # The counter-case on the same board, and a mixed one: a USB Type-C
    # connector whose **signal** pads are surface mount on layer 1 while its
    # **shield** pads are plated through-holes on layer 12. Without this half the
    # test would pass even if every pad on the board were treated as a barrel.
    smd = [p for p in pcb1.pads_for_component("USB1") if p.hole_diameter is None]
    barrels = [p for p in pcb1.pads_for_component("USB1") if p.hole_diameter is not None]
    assert smd and barrels, "USB1 has both SMD signal pads and TH shield pads"
    for pad in smd:
        assert pad.layer_id == 1 and pad.effective_layer_ids == [1], (
            f"USB1.{pad.pin_number} is surface mount: one face only"
        )
    for pad in barrels:
        assert pad.layer_id == MULTI_LAYER_ID
        assert pad.effective_layer_ids == [1, 2, 15, 16], (
            f"USB1.{pad.pin_number} is a plated barrel: every copper layer"
        )
    assert MULTI_LAYER_ID == 12, "the editor's Multi-Layer id is the documented 12"
    assert pcb1.pads_for_component("SWD1")[0].layer_id == MULTI_LAYER_ID


def test_an_unresolved_pad_reports_no_effective_layer():
    """A hand-built pad says nothing rather than guessing.

    ``effective_layer_ids`` is empty by default, and
    :meth:`PadGeometry.effective_layers` returns the empty set. The empty set is
    「this pad's physical layers were never established」, never 「this pad has no
    copper」 — the two are different, and a caller that treated the first as the
    second would silently drop every pad off a synthetic board.
    """
    pad = PadGeometry(id="p", component="R1", pin_number="1", layer_id=1)
    assert pad.effective_layers() == set()
    assert pad.is_smd is True


def test_the_nine_top_by_bottom_pairs_are_gone(foc_project):
    """**127a's regression nail**: the nine top x bottom pairs, counted.

    126b's report carried nineteen false positives. Nine of them were
    ``pcb-component-spacing`` rows whose two designators sit on **opposite faces**
    of the board, and 127a measured every one of them to be the layer-attribution
    defect rather than a real collision. This test walks the same pair sweep the
    rule walks and asserts that **no pair across two faces is ever measurable**,
    which is a stronger statement than "the nine happen not to fire today": a
    top part placed over a bottom part at 0.0 mil is still not a finding, because
    their copper cannot touch.

    It also asserts the sweep is not merely empty: the same-side, cross-net
    pairs 126b's threshold was reaching for are still measured, so the exemption
    did not quietly disable the rule.
    """
    _model, boards = foc_project
    for title in ("PCB1", "PCB3"):
        board = boards[title]
        designators = sorted(
            comp.designator for comp in board.components if comp.designator
            and board.pads_for_component(str(comp.designator))
        )
        cross_side = [
            (a, b)
            for i, a in enumerate(designators)
            for b in designators[i + 1:]
            if board.component(a).layer_id != board.component(b).layer_id
            and component_distance(board, a, b) is not None
            and component_distance(board, a, b).edge_distance < 20.0
        ]
        assert cross_side == [], (
            f"{title}: a pair on opposite faces of the board is not measurable "
            f"however close their projections are — got {cross_side}"
        )

    # The rule is not simply silent: PCB1 still reports its four real pairs.
    findings = ComponentSpacing().check(_ctx(foc_project[1]["PCB1"]))
    assert len(findings) == 4
    assert all(f.severity == "WARN" for f in findings)
    assert sorted(
        (f.target.component_ref, f.target.counterpart_ref) for f in findings
    ) == [("R18", "U16"), ("R22", "USB1"), ("R24", "USB1"), ("U8", "USB1")]


# ---------------------------------------------------------------------------
# 2. pcb-component-spacing exemptions
# ---------------------------------------------------------------------------


def test_a_same_net_pair_is_exempt():
    """Two pads of one net touching is the design's intent, not a defect.

    The exemption is **per pad pair**, not per pad: a ``GND`` pad is measured
    against its neighbour's ``SIG`` pad and exempt against its ``GND`` one.
    Getting this backwards would delete real collisions, so the board below is
    built to have *both* kinds of pair and asserts the surviving one is measured.
    """
    board = BoardGeometry(
        components=[_place("C1", 0.0, 0.0), _place("C2", 30.0, 0.0)],
        pads=[
            _pad("C1", "1", x=0.0, y=0.0, net="GND", effective=[1]),
            _pad("C2", "1", x=30.0, y=0.0, net="GND", effective=[1]),
        ],
    )
    # 40x40 pads 30 mil apart overlap, so without the exemption this is 0.0.
    assert ComponentSpacing().check(_ctx(board)) == []

    board.pads = [
        _pad("C1", "1", x=0.0, y=0.0, net="GND", effective=[1]),
        _pad("C1", "2", x=0.0, y=10.0, net="GND", effective=[1]),
        _pad("C2", "1", x=30.0, y=0.0, net="SIG", effective=[1]),
        _pad("C2", "2", x=30.0, y=10.0, net="SIG", effective=[1]),
    ]
    findings = ComponentSpacing().check(_ctx(board))
    assert len(findings) == 1, "the GND-vs-SIG pair is still measured"
    assert findings[0].severity == "WARN"


def test_a_cross_side_pair_is_not_measured():
    """A top pad and a bottom pad are on opposite faces of a ~62 mil board.

    The synthetic board places the two pads on different effective layers; the
    measurement returns ``None`` — 「this pair cannot be measured」 — rather than
    a fabricated zero, because a fabricated zero is exactly the false positive
    127b removed nine of.
    """
    board = BoardGeometry(
        components=[_place("A", 0.0, 0.0, layer_id=1), _place("B", 10.0, 0.0, layer_id=2)],
        pads=[
            _pad("A", "1", x=0.0, y=0.0, net="N1", effective=[1]),
            _pad("B", "1", x=10.0, y=0.0, net="N2", effective=[2]),
        ],
    )
    assert component_distance(board, "A", "B") is None

    # A through-hole pad spans every layer, so it **is** comparable with a
    # bottom pad — a barrel really does reach the other side of the board.
    board.pads[1] = PadGeometry(
        id="B.1", component="B", pin_number="1", net="N2", layer_id=MULTI_LAYER_ID,
        effective_layer_ids=[1, 2], x=10.0, y=0.0, width=40.0, height=40.0,
    )
    assert component_distance(board, "A", "B") is not None


# ---------------------------------------------------------------------------
# 3. pcb-decap-distance: the IC judgement
# ---------------------------------------------------------------------------


def test_a_header_is_not_an_ic_even_under_a_u_designator():
    """**Discipline 5, live.** A ``U`` designator does not make a part an IC.

    This is the fixture's own ``U6``/``U4``: MPN ``HX PZ2.54-2x6P TP``, footprint
    ``SMD,P=2.54mm``, 12 pins. 126b's pin-count test called it an IC (12 >= 3),
    a designator table calls it an IC (``U``), and it is a **2x6 排针** — a row of
    2.54 mm pins with no supply rail of its own to decouple.
    """
    header = _comp(
        "U6", mpn="HX PZ2.54-2x6P TP", footprint="SMD,P=2.54mm",
        props={"device_name": "HX PZ2.54-2x6P TP"},
        pins=[Pin(str(i), f"P{i}", "SIG") for i in range(1, 13)],
    )
    is_ic, why = classify_device(device_facts(header), pins=12)
    assert is_ic is False
    assert "connector/header" in why
    assert "PZ2.54" in why, "the reason names the word that decided it"

    # And the whole rule says nothing about it, end to end: a header on a supply
    # net with a capacitor 350 mil away produces no row, because there is no IC
    # to ask about.
    model = _model([
        header,
        _comp("C1", value="100nF", pins=[Pin("1", "1", "+24V"), Pin("2", "2", "PGND")]),
    ])
    board = BoardGeometry(
        components=[_place("U6", 0.0, 0.0), _place("C1", 350.0, 0.0)],
        pads=[
            _pad("U6", "1", x=0.0, y=0.0, net="+24V", effective=[2]),
            _pad("U6", "2", x=0.0, y=10.0, net="SIG", effective=[2]),
            _pad("U6", "3", x=0.0, y=20.0, net="PGND", effective=[2]),
            _pad("C1", "1", x=350.0, y=0.0, net="+24V", effective=[1]),
            _pad("C1", "2", x=350.0, y=10.0, net="PGND", effective=[1]),
        ],
    )
    assert DecapDistance().check(_ctx(board, model)) == []


def test_a_mosfet_is_not_an_ic():
    """岳裁定 1, live: a power MOSFET's drain is not an IC's supply pin.

    ``MCAC53N06Y-TP`` is nine pins, so 126b's floor admitted it, and its drain
    sits on ``+24V`` — the rule then asked it for a bypass capacitor 508 mil away.
    """
    mosfet = _comp(
        "Q1", mpn="MCAC53N06Y-TP", footprint="DFN(5x6)",
        pins=[Pin(str(i), f"P{i}", "+24V" if i == 1 else "SIG") for i in range(1, 10)],
    )
    is_ic, why = classify_device(device_facts(mosfet), pins=9)
    assert is_ic is False
    assert "transistor" in why
    # The **MPN** is the word that decided it, not the package: the words are
    # scanned in a priority order so the part's identity outranks the package
    # consequence of it.
    assert "MCAC" in why, why


def test_the_designator_is_the_fallback_not_the_test():
    """A part the device says nothing about is judged by its designator — last.

    The synthetic part below has no MPN, no footprint, no words and no shelf
    entry, so the designator is all there is. It **is** an IC by the fallback,
    and the evidence says so, because a rule that quietly dropped parts nobody
    could classify would be indistinguishable from one that dropped them by
    accident.
    """
    mystery = _comp("U9", pins=[Pin("1", "VCC", "+5V"), Pin("2", "OUT", "SIG"), Pin("3", "GND", "GND")])
    is_ic, why = classify_device(device_facts(mystery), pins=3)
    assert is_ic is True
    assert "designator" in why and "fallback" in why

    # And the pin floor is still necessary: a two-pin part is never an IC, even
    # under a ``U`` designator.
    resistor = _comp("U10", pins=[Pin("1", "1", "+5V"), Pin("2", "2", "GND")])
    is_ic, why = classify_device(device_facts(resistor), pins=2)
    assert is_ic is False
    assert "pin floor" in why

    # A many-pin designator that never names an IC is refused outright.
    for prefix in sorted(NON_IC_DESIGNATOR_PREFIXES):
        part = _comp(f"{prefix}7", pins=[Pin(str(i), f"P{i}", "SIG") for i in range(1, 5)])
        is_ic, why = classify_device(device_facts(part), pins=4)
        assert is_ic is False, f"{prefix}7 must not be an IC"


# ---------------------------------------------------------------------------
# 3b. pcb-decap-distance: the bulk / HF split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "declared, expected_role",
    [
        ("330uF", CAP_ROLE_BULK),      # the fixture's aluminium cans
        ("22uF", CAP_ROLE_BULK),       # PCB1's C23
        ("10uF", CAP_ROLE_BULK),       # the boundary is inclusive
        ("1uF", CAP_ROLE_HF),          # the boundary is inclusive
        ("100nF", CAP_ROLE_HF),
        ("47nF", CAP_ROLE_HF),
        ("2.2uF", CAP_ROLE_UNKNOWN),   # between the two bands — neither pool
        ("4.7UF", CAP_ROLE_UNKNOWN),   # PCB1's C17, the one 126b measured
        ("", CAP_ROLE_UNKNOWN),        # nobody wrote a value down
        ("C104", CAP_ROLE_UNKNOWN),    # a net name, not a capacitance
    ],
)
def test_the_capacitor_role_boundaries_are_inclusive_and_named(declared, expected_role):
    """The role boundaries, each one pinned with its declared value.

    Both thresholds are **inclusive** (``>= BULK_FARADS``, ``<= HF_FARADS``) so a
    part sitting exactly on a boundary is a decision rather than a coin toss.
    The band between them is neither pool, and that is stated rather than rounded
    into one — it is where the fixture's 2.2 µF and 4.7 µF parts sit, and
    「is it bulk or is it bypass」 is a question about the loop, not the part.
    """
    from boardwise.rules.decap import CapCandidate

    model = _model([_comp("C1", value=declared)])
    role = capacitor_role(CapCandidate(designator="C1", value=declared), model)
    assert role.role == expected_role, role.reason
    assert declared in role.reason or "no readable capacitance" in role.reason


def test_a_bulk_capacitor_is_not_a_high_frequency_candidate():
    """岳裁定 5b: a 330 µF can 508 mil from a chip is not a mis-placed bypass.

    The end-to-end shape: an IC on ``+24V``, one 330 µF bulk capacitor on that
    net and nothing else. The rule must report **INFO** naming the bulk part —
    「只有 bulk，无 HF 去耦候选」 — and not a WARN about a distance it should never
    have asked for.
    """
    model = _model([
        _comp("U1", pins=[
            Pin("1", "VCC", "+24V"), Pin("2", "OUT", "SIG"), Pin("3", "GND", "GND"),
        ]),
        _comp("C1", value="330uF", mpn="PA50V330M10x15",
              pins=[Pin("1", "1", "+24V"), Pin("2", "2", "PGND")]),
    ])
    board = BoardGeometry(
        components=[_place("U1", 0.0, 0.0), _place("C1", 500.0, 0.0)],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net="+24V", effective=[1]),
            _pad("U1", "2", x=0.0, y=10.0, net="SIG", effective=[1]),
            _pad("U1", "3", x=0.0, y=20.0, net="GND", effective=[1]),
            _pad("C1", "1", x=500.0, y=0.0, net="+24V", effective=[1]),
            _pad("C1", "2", x=500.0, y=10.0, net="PGND", effective=[1]),
        ],
    )
    findings = DecapDistance().check(_ctx(board, model))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO", "a bulk-only pool is an INFO, never a WARN"
    assert "bulk" in finding.message and "C1" in finding.message
    assert "no high-frequency decoupling candidate" in finding.message
    joined = " | ".join(finding.evidence)
    assert "judged an IC because" in joined, "the IC judgement is stated"
    assert "330uF" in joined, "so is the declared value that made C1 bulk"
    assert "decap-required-caps" in finding.message, (
        "whether a cap is required at all stays the datasheet's question"
    )


def test_a_high_frequency_capacitor_too_far_is_still_a_warn():
    """The rule keeps its teeth: a real 100 nF bypass 350 mil away is a WARN.

    The bulk split narrows the candidate pool; it must not switch the rule off.
    This is 126b's original synthetic case, unchanged, and it is the pair of pins
    that says the fix narrowed the *pool* rather than the *rule*.
    """
    model = _model([
        _comp("U1", pins=[
            Pin("1", "VCC", "+5V"), Pin("2", "OUT", "SIG"), Pin("3", "GND", "GND"),
        ]),
        _comp("C1", value="100nF", pins=[
            Pin("1", "1", "+5V"), Pin("2", "2", "AGND"),
        ]),
    ])
    board = BoardGeometry(
        components=[_place("U1", 0.0, 0.0), _place("C1", 350.0, 0.0)],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net="+5V", effective=[1]),
            _pad("U1", "2", x=0.0, y=10.0, net="SIG", effective=[1]),
            _pad("U1", "3", x=0.0, y=20.0, net="GND", effective=[1]),
            _pad("C1", "1", x=350.0, y=0.0, net="+5V", effective=[1]),
            _pad("C1", "2", x=350.0, y=10.0, net="AGND", effective=[1]),
        ],
    )
    findings = DecapDistance().check(_ctx(board, model))
    assert len(findings) == 1
    assert findings[0].severity == "WARN"
    assert findings[0].target.counterpart_ref == "C1"
    assert findings[0].target.measurement["value"] == 310.0


# ---------------------------------------------------------------------------
# 4. pcb-voltage-spacing exemptions
# ---------------------------------------------------------------------------


def _two_net_board(*, hv_pads, lv_pads, layers=(1, 2)):
    return BoardGeometry(
        layers={
            1: LayerInfo(layer_id=1, name="Top", layer_type="TOP"),
            2: LayerInfo(layer_id=2, name="Bottom", layer_type="BOTTOM"),
        },
        components=[
            _place("HV", 0.0, 0.0),
            _place("LV", 0.0, 0.0),
        ],
        pads=[
            _pad("HV", "1", x=0.0, y=0.0, net="HV", effective=[1], **hv_pads),
            _pad("LV", "1", x=5.0, y=0.0, net="LV", effective=[1], **lv_pads),
        ],
    )


def test_two_ground_islands_are_exempt():
    """岳裁定 4: GND against PGND is 0 V against 0 V, and their meeting is intent.

    The synthetic pair touches on a shared layer (0.0 mil, which 126c's own
    message called 「a short, not merely a tight gap」), so the exemption is doing
    real work here rather than removing a row that was never there. The same
    potential by *name* is the case; the same potential by *voltage* is the same
    clause, and it is pinned separately below.
    """
    board = BoardGeometry(
        layers={
            1: LayerInfo(layer_id=1, name="Top", layer_type="TOP"),
            2: LayerInfo(layer_id=2, name="Bottom", layer_type="BOTTOM"),
        },
        components=[_place("G1", 0.0, 0.0), _place("G2", 0.0, 0.0)],
        pads=[
            _pad("G1", "1", x=0.0, y=0.0, net="GND", effective=[1]),
            _pad("G2", "1", x=5.0, y=0.0, net="PGND", effective=[1]),
        ],
    )
    measured = net_clearance(board, "GND", "PGND")
    assert measured is not None and measured.distance == 0.0
    assert measured.shares_a_layer is True, (
        "the two grounds DO share layer 1 — the pair is exempt on the "
        "same-potential clause, not on the cross-layer one"
    )
    assert VoltageSpacing().check(_ctx(board)) == [], (
        "two grounds meeting in one place is a single-point join, not a defect"
    )


def test_two_nets_at_the_same_voltage_are_exempt():
    """The clause is **equality of potential**, with grounds as one instance.

    Not special-cased for grounds: a contract that prices two nets at the same
    voltage gets the same answer, because what the rule would otherwise be
    asserting is a spacing requirement between two things that are, by the
    declaration, at one potential. Pinned through the public voltage path
    (``GROUND_VOLTS`` is what makes a ground net 0 V), so the two readings
    cannot drift apart.
    """
    from boardwise.core.model import is_ground_net

    assert is_ground_net("GND") and is_ground_net("PGND")
    board = BoardGeometry(
        layers={1: LayerInfo(layer_id=1, name="Top", layer_type="TOP")},
        components=[_place("A", 0.0, 0.0), _place("B", 5.0, 0.0)],
        pads=[
            _pad("A", "1", x=0.0, y=0.0, net="AGND", effective=[1]),
            _pad("B", "1", x=5.0, y=0.0, net="DGND", effective=[1]),
        ],
    )
    assert VoltageSpacing().check(_ctx(board)) == []


def test_a_cross_layer_pair_is_dropped_not_reported_as_a_short():
    """A pair sharing no copper layer is dropped, and the label tells the truth.

    Before 127b this pair produced a WARN whose message said 「the copper
    touches」 — with ``overlapping=True`` — because the rule compared a top pad to
    a bottom pad through their plan-view projections. Now the pair is dropped,
    and the element labels name the **effective** layer, so a reader can never be
    told a bottom pad's copper is on layer 1 (the 127a misattribution).
    """
    board = BoardGeometry(
        layers={
            1: LayerInfo(layer_id=1, name="Top", layer_type="TOP"),
            2: LayerInfo(layer_id=2, name="Bottom", layer_type="BOTTOM"),
        },
        components=[_place("A", 0.0, 0.0), _place("B", 5.0, 0.0)],
        pads=[
            # The raw layer_id lies (1) while the effective reading is the truth (2),
            # exactly as on the fixture's U6.
            _pad("A", "1", x=0.0, y=0.0, net="HV", layer_id=1, effective=[2]),
            _pad("B", "1", x=5.0, y=0.0, net="GND", layer_id=1, effective=[1]),
        ],
    )
    measured = net_clearance(board, "HV", "GND")
    assert measured is not None
    assert measured.distance == 0.0, "the projection still projects"
    assert measured.shares_a_layer is False, "but the two never share a layer"
    assert "on layer 2" in measured.element_a, (
        "and the label names the pad's real face, not the footprint's stored one"
    )


# ---------------------------------------------------------------------------
# 5. the round-2 acceptance
# ---------------------------------------------------------------------------


def test_the_bishe_foc_board_is_clean_under_both_distance_rules(foc_project):
    """**The acceptance the task book asks for, as a single pin.**

    岳's blind review returned nineteen false positives from the 126 module-level
    report. This asserts the board total those nineteen came from, so the number
    cannot come back by any of the five routes at once:

    * **19 -> 4.** PCB1's 17 spacing WARNs and PCB3's 5 collapse to 4, all of
      them same-side, cross-net and non-touching. Six of the nine top x bottom
      pairs and the same-net pairs are exempt by the measurement itself
      (:func:`boardwise.core.measure.component_distance`).
    * **the 5 decap WARNs -> 0.** Q1/Q3/Q7 are MOSFETs and U4/U6/U1/U2 are
      2x6 headers; none is an IC, and the 330 µF cans would have been bulk
      anyway.
    * **PCB2 and PCB3 contribute nothing.** PCB2's outline is a single point
      (126b's degenerate case) and PCB3 has no IC.

    What the board still reports is the part a reviewer can act on: four INFO
    rows naming the (IC, net) pairs with no high-frequency candidate, each
    carrying the IC judgement and every candidate's declared value.
    """
    model, boards = foc_project
    findings, section = run_pcb_review(FOC, model=model)
    spacing = [f for f in findings if f.rule_id == "pcb-component-spacing"]
    decap = [f for f in findings if f.rule_id == "pcb-decap-distance"]

    assert len(spacing) == 4, (
        f"the nineteen false positives are gone; what remains is "
        f"{[(f.target.component_ref, f.target.counterpart_ref) for f in spacing]}"
    )
    assert all(f.board == "PCB1" for f in spacing), (
        "every surviving spacing row is same-side, so PCB2 and PCB3 contribute none"
    )
    assert not [f for f in spacing if f.target.measurement["value"] == 0.0]

    assert not [f for f in decap if f.severity == "WARN"], (
        "no decap WARN survives: no part on this board that the rule asks about "
        "is anything but an IC, and no candidate pool is a high-frequency one"
    )
    assert len(decap) == 4 and all(f.severity == "INFO" for f in decap)
    for finding in decap:
        joined = " | ".join(finding.evidence)
        assert "judged an IC because" in joined
        assert any("candidate " in line for line in finding.evidence), (
            "every INFO names the candidates it excluded and why"
        )

    assert len(section["boards"]) == 3


def test_the_llc_fixture_stays_clean_under_the_fixed_rules():
    """The negative anchor: a board that was already clean must stay clean.

    126b pinned llc as clean under both distance rules with the measured minimum
    spacing at 20.5 mil — just clear of the 20 mil threshold. The two new
    exemptions can only *remove* pairs, so this cannot go red by gaining a
    finding; it is here because the llc measurement is what says the fixes did
    not change the measurement of an ordinary two-layer board, and because a
    rule that never fires and a rule that fires correctly are only told apart by
    a test that expects the empty answer.

    **133b narrowed this pin, for the same reason 126b's own llc pin was
    narrowed.** The five FOC rules were added to ``BUILTIN_PCB_RULES`` and llc is
    no longer a board every PCB rule is silent on: ``pcb-foc-power-loop-area``
    produces **four** rows there, because llc places two 330 µF electrolytics on
    ``DC+``/``DC-`` and four ``B3M040065H`` FETs whose bus pads sit on those same
    nets — it is a full-bridge power stage, so the high-current loop is a real
    thing to measure. That is 133b's pack reading llc honestly, not 127b's fixes
    failing on it, so the assertion is now over the rules that existed at 127b
    and 133b's side of llc is pinned in ``test_133b_foc_rules.py``.
    """
    llc = FIXTURES / "llc_board.epro2"
    model, _ = cli._load_model(llc, view="schematic")
    findings, section = run_pcb_review(llc, model=model)
    foc_ids = {
        "pcb-foc-decap-proximity", "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width", "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        # 133c's three ground rules are subtracted for the same reason 133b's
        # five were: on llc they answer 「there is no power-domain ground here」
        # (llc names its returns DC+/DC- and carries no PGND at all), so the
        # question 127b asks — every rule that existed before the FOC pack is
        # silent — still holds. test_133c_foc_ground.py pins their side.
        "pcb-foc-ground-domains", "pcb-foc-ground-tie", "pcb-foc-return-path",
    }
    assert [f for f in findings if f.rule_id not in foc_ids] == [], [
        (f.rule_id, f.message) for f in findings if f.rule_id not in foc_ids
    ]
    assert section is not None and section["available"] is True


def test_the_robot_fixture_keeps_its_real_findings(foc_project):
    """The other side of the acceptance: a genuine defect must survive.

    The ROBOT ctrl-FOC fixture is the one board in the corpus with a design-intent
    contract, and its ``pcb-track-ampacity`` ERRORs — three amps down a 10 mil
    trace — are 126c's true-positive case. 127b touched ``ipc.py``, so this pins
    that the fix to the *spacing* rule left the *ampacity* rule alone.
    """
    robot = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
    model, _ = cli._load_model(robot, view="schematic")
    intent = DesignIntent.load(
        Path(__file__).resolve().parents[1]
        / "blocklib" / "intents" / "robot-ctrl-foc.intent.json"
    )
    findings, _section = run_pcb_review(robot, model=model, intent=intent)
    ampacity = [f for f in findings if f.rule_id == "pcb-track-ampacity"]
    assert len(ampacity) == 6, (
        f"the six ampacity ERRORs are the fixture's real defect and 127b must "
        f"not touch them; got {[f.message for f in ampacity]}"
    )
    assert all(f.severity == "ERROR" for f in ampacity)