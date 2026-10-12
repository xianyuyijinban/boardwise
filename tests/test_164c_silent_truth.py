"""Task 164c: the silent branches, the two measurement rulings, and the two
projections that were axis-aligned boxes.

Five findings from the 161 audit, fixed in one batch, each with a regression
test that was **red before the fix** — the assertion is always the same shape:
「the rule must stop being silent (or must stop being quietly wrong) about
this case」.

* **F3** — ``derating._schematic_component`` and ``polarity._schematic_component``
  refused to match boards by designator overlap but, when ``board_uuid`` was
  empty **and the project had several boards**, the condition
  ``if uuid and uuid != board.uuid: continue`` was **always false**, so the loop
  hit the first board that carried the refdes and answered with *another board's
  declaration*. On 毕设FOC 1.0.0 that is Board1's ``R48`` (a ``0R``) and
  Board1's ``LED1`` symbol pin names. The fix is 153b's own
  ``focground.schematic_board_of`` semantics, lifted into both rules: one board
  is no choice at all and is used; several boards with no link is 「板链读不出」
  and the finding says so instead of reading board 0.
* **F4** — ``ipc._architecture_rails`` dropped two boards' disagreement about
  one net **in place** (``conflicting`` set, discarded on return) while
  ``declared_voltages``'s docstring promised the conflict came back in
  ``notes``. Now it does, and ``pcb-voltage-spacing``'s UNKNOWN row says which
  kind of unknown it is: no source names a voltage, or the sources contradict.
* **F5** — ``value <= 0.0`` threw away a negative rail (``-12V`` is a real
  design and ``parse_voltage_volts`` reads the sign on purpose) and said
  nothing. Negative rails are now priced; a statement of 0 V or an unreadable
  one is still dropped, and now says so.
* **D5** — the 200 mil decoupling rule measured ``component_distance`` (which
  refuses same-net pairs, so it answered with the diagonal across *other* nets)
  while the FOC driver rule measured 「this cap's pad on the net, edge to edge,
  from the supply pin」 — TI SLVA959B §5.3.1's own reading. ``distance`` is
  aligned to the same-net reading; the FOC side is untouched.
* **focthermal's projection** — ``BBox.from_points(pad_corners(pad))`` handed
  ``region_copper`` the **axis-aligned** box of a rotated pad, which for ROBOT's
  45° 244 × 108 mil EP encloses 62 079 sq mil against the pad's own 26 428. The
  region query stays (it is the primitive), and its answer is now restricted to
  the elements that truly meet the pad's rotated rectangle.
* **``_outside_outline``** — the board frame was the outline's AABB, so a part
  sitting in an L-shaped board's **notch** was inside the box and outside the
  board. The test is now true polygon containment, with 「touching the edge is
  not over」 kept exactly as it was.

Everything here is measured: the F3 numbers are 毕设FOC 1.0.0's own
(``board_uuid`` ``d5c055266ef55000`` = Board1, ``5455a645b144c024`` = Board2),
and every synthetic case is hand-derived in the test that uses it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.designintent import DesignIntent, IntentRail
from boardwise.core.geometry import (
    BBox,
    BoardGeometry,
    BoardOutline,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import extract_board, load_epro2_source
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb import ipc as ipc_module
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.derating import DeratingPackage
from boardwise.rules.pcb.distance import ComponentSpacing, DecapDistance
from boardwise.rules.pcb.focthermal import FocThermalExitPath, thermal_pad_of
from boardwise.rules.pcb.ipc import VoltageSpacing, declared_voltages
from boardwise.rules.pcb.polarity import PolarityOrientation

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"

#: 毕设FOC 1.0.0's two schematic boards, measured (see 153b's own file).
BOARD1_UUID = "d5c055266ef55000"
BOARD2_UUID = "5455a645b144c024"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _project(path: Path):
    return build_project_model(path)


def _pcb_view(path: Path, title: str = "PCB1"):
    """``(board, pcb_model)`` for one PCB document of a fixture."""
    source = load_epro2_source(path)
    for document in source.documents_of_type("PCB"):
        document_title = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                document_title = str(record.body.get("title") or "")
                if document_title:
                    break
        if document_title == title:
            return (
                extract_board(document, source.footprints(), source.stats),
                build_design_model(source, document),
            )
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


def _ctx(board=None, model=None, pcb_model=None, *, title="SYNTH", intent=None,
         board_uuid=""):
    return PcbReviewContext(
        board=board,
        board_title=title,
        model=model,
        pcb_model=pcb_model,
        intent=intent,
        board_uuid=board_uuid,
    )


def _evidence(row) -> str:
    return "\n".join(row.evidence)


def _pad(component, pin, *, x, y, net="", width=40.0, height=40.0, angle=0.0):
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=1,
        effective_layer_ids=[1],
        x=x,
        y=y,
        width=width,
        height=height,
        shape="RECT",
        angle=angle,
    )


def _place(designator, x, y, *, footprint=""):
    return ComponentPlacement(
        id=f"c-{designator}", designator=designator, x=x, y=y, layer_id=1,
        footprint=footprint,
    )


def _comp(designator, *, value="", pins=()):
    return Component(
        uid=f"u-{designator}", designator=designator, value=value, pins=list(pins)
    )


def _model(components):
    """A ``DesignModel`` whose net index is built from its own components' pins."""
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


def _contract(rails):
    return DesignIntent(
        rails=[
            IntentRail(net=net, slots=slots, provenance="user_stated")
            for net, slots in rails.items()
        ]
    )


# ===========================================================================
# F5 — a negative rail is a rail; 0 V and unreadable statements are dropped
#       with a note instead of in silence
# ===========================================================================


def test_a_negative_rail_is_priced_instead_of_being_dropped_silently():
    """F5: ``-12V`` is a real design and the parser reads the sign on purpose.

    ``parse_voltage_volts``'s own docstring says 「``-12V`` names a real rail」,
    and the old ``value <= 0.0`` guard threw exactly that spelling away — a
    contract that priced a negative rail got no entry, no note and no UNKNOWN
    row naming the reason. The net then fell to 「no source names its voltage」
    while a source had named it.
    """
    model = _model([])
    ctx = _ctx(model=model, pcb_model=model, intent=_contract({"-12V": {"voltage": "-12V"}}))
    volts, notes = declared_voltages(ctx, ctx.model)
    assert volts["-12V"][0] == -12.0, "the sign is part of the voltage"
    assert "contract" in volts["-12V"][1]
    assert not [note for note in notes if "-12V" in note], (
        "a rail that was read needs no note: silence is the finding-free state, "
        "not the only one"
    )


def test_a_zero_volt_rail_and_an_unreadable_one_are_dropped_with_a_note():
    """F5's other half: what is *not* read is said out loud.

    Two statements are still refused — ``0V`` (a 0 V rail is the board's
    reference, and both callers price grounds by convention rather than from the
    contract) and a spelling this build cannot read. The defect was never that
    they were refused; it was that they vanished. Each now gets a note addressed
    to its own net, which is also what lets the UNKNOWN row say *why* it is
    unknown.
    """
    model = _model([])
    ctx = _ctx(
        model=model,
        pcb_model=model,
        intent=_contract({"RAIL0": {"voltage": "0V"}, "JUNK": {"voltage": "banana"}}),
    )
    volts, notes = declared_voltages(ctx, ctx.model)
    assert "RAIL0" not in volts and "JUNK" not in volts
    joined = " || ".join(notes)
    assert "RAIL0" in joined and "'0V'" in joined, (
        "the dropped 0 V statement is named, with the text it was read from"
    )
    assert "JUNK" in joined and "'banana'" in joined, (
        "the unreadable statement is quoted rather than merely counted"
    )


# ===========================================================================
# F4 — two boards' disagreement about one net is stated, not swallowed
# ===========================================================================


class _Enumeration:
    """A stand-in for 044's enumeration, carrying only the rails section."""

    def __init__(self, rails):
        self.section = {"chains": {"rails": list(rails)}}


def _fake_architecture(rails):
    def _generate(model, library=None, **_kwargs):
        return _Enumeration(rails)

    return _generate


def test_architecture_rails_returns_the_cross_board_conflict(monkeypatch):
    """F4's core: the conflict set left ``_architecture_rails`` before.

    Two boards naming one net at two voltages is the case the function's own
    docstring singles out (「picking one would let a board's spacing verdict
    depend on which board was enumerated first」). It dropped the net — which is
    right — and dropped the **reason** too, so ``declared_voltages`` had nothing
    to put in ``notes`` while its docstring promised the conflict came back
    there.
    """
    monkeypatch.setattr(
        ipc_module,
        "generate_architecture",
        _fake_architecture(
            [
                {"net": "VCC", "voltage": 5.0, "board": "Board1"},
                {"net": "VCC", "voltage": 3.3, "board": "Board2"},
                {"net": "5V", "voltage": 5.0, "board": "Board1"},
            ]
        ),
    )
    rails, conflicts = ipc_module._architecture_rails(object())
    assert {net for net, _volts, _where in rails} == {"5V"}, (
        "the conflicted net still gets no entry — that half was already right"
    )
    assert len(conflicts) == 1
    note = conflicts[0]
    assert "VCC" in note
    assert "5" in note and "3.3" in note, "both numbers, so the reader can judge"
    assert "Board1" in note and "Board2" in note, "and both boards, so it is actionable"


def test_declared_voltages_carries_the_conflict_into_its_notes(monkeypatch):
    """The channel the docstring already described is now the one that is used."""
    monkeypatch.setattr(
        ipc_module,
        "generate_architecture",
        _fake_architecture(
            [
                {"net": "VCC", "voltage": 5.0, "board": "Board1"},
                {"net": "VCC", "voltage": 3.3, "board": "Board2"},
            ]
        ),
    )
    model = _model([])
    ctx = _ctx(model=model, pcb_model=model)
    volts, notes = declared_voltages(ctx, model)
    assert "VCC" not in volts
    assert any(
        note.startswith("net 'VCC':") and "the sources disagree" in note
        for note in notes
    ), f"the conflict must arrive addressed to its net: {notes}"


def test_the_unknown_row_tells_the_two_kinds_of_unknown_apart(monkeypatch):
    """「没有源报电压」 vs 「两源互相矛盾」 — one row per kind, different wording.

    The row is the reader's whole answer for an unpriced rail, so an UNKNOWN that
    says 「no source names this voltage」 when two sources named two different
    voltages sends the engineer to write a number that is already there.
    """
    monkeypatch.setattr(
        ipc_module,
        "generate_architecture",
        _fake_architecture(
            [
                {"net": "VCC", "voltage": 5.0, "board": "Board1"},
                {"net": "VCC", "voltage": 3.3, "board": "Board2"},
            ]
        ),
    )
    board = BoardGeometry(
        name="SYNTH",
        layers={1: LayerInfo(1, "TOP", "SIGNAL")},
        tracks=[
            TrackSegment(
                id="t-vcc", net="VCC", layer_id=1,
                start=Point(0.0, 0.0), end=Point(100.0, 0.0), width=10.0,
            ),
            TrackSegment(
                id="t-sig", net="SIG", layer_id=1,
                start=Point(400.0, 0.0), end=Point(500.0, 0.0), width=10.0,
            ),
        ],
    )
    model = _model([])
    ctx = _ctx(board=board, model=model, pcb_model=model, title="SYNTH")
    volts, conflicts = declared_voltages(ctx, model)
    assert any("VCC" in note for note in conflicts)

    rows = {
        finding.target.net_refs[0]: finding
        for finding in VoltageSpacing().check(ctx)
        if finding.severity == "INFO" and finding.target is not None
    }
    vcc = rows["VCC"]
    assert "conflicting voltage sources" in vcc.message, (
        "the contradicted rail says so, and quotes both sides"
    )
    assert "5" in vcc.message and "3.3" in vcc.message
    assert "Board1" in vcc.message and "Board2" in vcc.message
    assert "no established voltage" not in vcc.message, (
        "it must not read as 「nobody priced this」 — two sources did"
    )

    # The other kind is unchanged: a rail nobody names still says nobody named it.
    assert "SIG" not in rows, "a signal net is not a rail and gets no row at all"


def test_a_rail_no_source_prices_keeps_its_own_wording():
    """The control case, so the new branch cannot swallow the ordinary UNKNOWN."""
    model = _model([])
    board = BoardGeometry(
        name="SYNTH",
        layers={1: LayerInfo(1, "TOP", "SIGNAL")},
        tracks=[
            TrackSegment(
                id="t-vcc", net="VCC", layer_id=1,
                start=Point(0.0, 0.0), end=Point(100.0, 0.0), width=10.0,
            )
        ],
    )
    ctx = _ctx(
        board=board, model=model, pcb_model=model, intent=_contract({"VCC": {}})
    )
    volts, conflicts = declared_voltages(ctx, model)
    assert conflicts == []
    rows = [f for f in VoltageSpacing().check(ctx) if f.severity == "INFO"]
    assert len(rows) == 1
    assert "no established voltage" in rows[0].message
    assert "conflicting voltage sources" not in rows[0].message


# ===========================================================================
# F3 — a missing board link on a multi-board project is 「板链读不出」, not board 0
# ===========================================================================


def test_derating_stops_answering_with_board_zeros_declaration():
    """F3 on the derating rule, on 毕设FOC 1.0.0 (122 + 10 parts, two boards).

    ``R48`` is the measured case: Board1's page says ``0R`` and PCB1's own copy
    says ``10K``. With the link present the rule reads the page's ``0R``; with
    the link **missing** the old loop answered with Board1's ``0R`` all the same —
    which is 「another board's declaration, presented as this board's」.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    project = _project(FOC_100)
    assert len(project.boards) > 1, "the case is only real on a multi-board project"

    linked = _ctx(board, project, pcb_model, board_uuid=BOARD1_UUID)
    unlinked = _ctx(board, project, pcb_model, board_uuid="")

    assert str(DeratingPackage._schematic_component(linked, "R48").value) == "0R"
    assert DeratingPackage._schematic_component(unlinked, "R48") is None, (
        "no link + several boards = no page to answer with"
    )

    rows = DeratingPackage().check(unlinked)
    summary = rows[-1]
    joined = _evidence(summary)
    assert "板链读不出" in joined, "the summary states what could not be resolved"
    assert "未判断" in joined, "and that the schematic-first reading did not happen"
    assert "不按位号重合度" in joined, (
        "the reader is told which wrong road was refused"
    )
    assert "不一致" not in joined, (
        "with no page there is no second view, so no divergence can be reported: "
        "the old run listed 37 of them, all of them Board1's"
    )

    # The control: with the link, the page's declarations are used again.
    linked_summary = _evidence(DeratingPackage().check(linked)[-1])
    assert "不一致" in linked_summary
    assert "板链读不出" not in linked_summary


def test_polarity_stops_reading_pins_off_board_zeros_symbols():
    """F3 on the polarity rule: Board1's ``LED1`` symbol is not this board's.

    The polarity rule reads *which pin is ``+``* off the schematic symbol. With
    the link missing the old loop handed it Board1's ``LED1`` — a symbol whose
    pin names are ``('1', '+')``/``('2', '-')`` — and the rule judged this
    board's silkscreen against another board's symbol. The measured change is
    visible in the summary line: three parts with declared polarity pins become
    zero.
    """
    board, pcb_model = _pcb_view(FOC_100, "PCB1")
    project = _project(FOC_100)

    linked = _ctx(board, project, pcb_model, board_uuid=BOARD1_UUID)
    unlinked = _ctx(board, project, pcb_model, board_uuid="")

    linked_led = PolarityOrientation._schematic_component(linked, "LED1")
    assert [(pin.number, pin.name) for pin in linked_led.pins] == [("1", "+"), ("2", "-")]
    assert PolarityOrientation._schematic_component(unlinked, "LED1") is None

    linked_rows = PolarityOrientation().check(linked)
    unlinked_rows = PolarityOrientation().check(unlinked)
    assert "3 颗原理图声明了极性脚" in linked_rows[-1].message
    assert "0 颗原理图声明了极性脚" in unlinked_rows[-1].message, (
        "with no page located, no symbol pin names reach the rule"
    )

    joined = _evidence(unlinked_rows[-1])
    assert "板链读不出" in joined and "未判断" in joined

    # The row that reports 「this part's schematic says no polarity pin」 must not
    # claim the schematic said nothing when the schematic was never located.
    unnameable = [
        row for row in unlinked_rows if row.severity == "INFO" and "没有声明" in row.message
    ]
    assert unnameable, "the library-type-only parts still get their row"
    assert "板链" in unnameable[0].message and "未判断" in unnameable[0].message, (
        "「原理图没有声明极性脚」 would be a claim about a page nobody read"
    )
    assert "板链" not in "".join(
        row.message for row in linked_rows if "没有声明" in row.message
    ), "with the page located the row keeps its original meaning"


def test_a_single_board_project_with_no_link_still_reads_that_board():
    """The branch that must not change: one board is no choice at all.

    153b pinned this for ``focground.schematic_board_of`` on 智能药箱 (whose PCB1
    declares no ``META.board`` and whose project has exactly one board). The two
    rules here carry the same lookup, so the same case is pinned on the same
    fixture: the page is used, and **no** 「板链读不出」 note appears.
    """
    pillbox = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
    board, pcb_model = _pcb_view(pillbox, "PCB1")
    project = _project(pillbox)
    assert len(project.boards) == 1

    ctx = _ctx(board, project, pcb_model, board_uuid="")
    page = project.boards[0]
    designator = next(iter(sorted(page.components)))
    assert DeratingPackage._schematic_component(ctx, designator) is page.components[designator]
    assert PolarityOrientation._schematic_component(ctx, designator) is page.components[designator]
    assert "板链读不出" not in _evidence(DeratingPackage().check(ctx)[-1])


# ===========================================================================
# D5 — the 200 mil decoupling rule measures on the net, like the FOC rule does
# ===========================================================================

DECOUPLED = "3V3"
BRIDGE_GROUND = "AGND"


def _decap_board(*, cap_x: float, cap_y: float):
    """An IC and its decoupling capacitor, with the two readings pulled apart.

    ``U1``'s supply pad sits at the origin and its ground pad at ``(0, 200)``;
    ``C1`` sits at ``(cap_x, cap_y)``, supply pad and ground pad 200 mil apart on
    x. The two numbers the two measurement rules produce are therefore
    **deliberately different**:

    * ``core.measure.component_distance`` refuses the same-net pair, so its
      nearest answer is ``U1.GND`` ↔ ``C1.3V3`` — the diagonal across two nets,
      a placement distance;
    * the same-net reading is ``U1.3V3`` ↔ ``C1.3V3`` edge to edge, which is the
      loop the capacitor actually decouples and what TI SLVA959B §5.3.1 asks
      about.
    """
    model = _model(
        [
            _comp(
                "U1",
                pins=[
                    Pin("1", "VCC", DECOUPLED),
                    Pin("2", "OUT", "SIG"),
                    Pin("3", "GND", "GND"),
                ],
            ),
            _comp(
                "C1",
                value="100nF",
                pins=[Pin("1", "1", DECOUPLED), Pin("2", "2", BRIDGE_GROUND)],
            ),
        ]
    )
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place("U1", 0.0, 0.0), _place("C1", cap_x, cap_y)],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net=DECOUPLED),
            _pad("U1", "2", x=0.0, y=0.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=200.0, net="GND"),
            _pad("C1", "1", x=cap_x, y=cap_y, net=DECOUPLED),
            _pad("C1", "2", x=cap_x + 200.0, y=cap_y, net=BRIDGE_GROUND),
        ],
    )
    return model, board


def test_the_decap_rule_measures_the_same_net_pads_edge_to_edge():
    """D5: the two rules now measure one thing, and the row says which.

    The capacitor is placed at ``(0, 250)``, i.e. **210 mil** from the IC's
    supply pad edge to edge (250 − 40) — over the 200 mil house rule, so WARN.
    The old reading (``component_distance``) answered **10 mil**, because the
    pair it was allowed to measure was ``U1``'s ground pad at ``(0, 200)``
    against ``C1``'s supply pad at ``(0, 250)``: two *different* nets 10 mil
    apart. The rule therefore called a capacitor 210 mil away 「10 mil from the
    IC」 and stayed silent.
    """
    model, board = _decap_board(cap_x=0.0, cap_y=250.0)
    findings = DecapDistance().check(_ctx(board, model, model))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN"
    assert finding.target.measurement == {
        "kind": "distance", "value": 210.0, "unit": "mil",
    }
    assert "210.0" in finding.message

    joined = _evidence(finding)
    assert "10.0 mil" in joined, (
        "the cross-net placement distance is still quoted, so a reader can see "
        "both numbers and which one is the finding"
    )
    assert "different" in joined, "and it is named as the other measurement"


def test_the_decap_rule_is_silent_when_the_same_net_gap_is_inside_the_rule():
    """The other direction: the same-net reading can also be the quiet one.

    At ``(0, 150)`` the supply pad is 110 mil from the IC's — inside 200, so
    nothing to report — while the cross-net pair is 90 mil. Neither reading
    fires, which is the honest 「placement is fine」 state.
    """
    model, board = _decap_board(cap_x=0.0, cap_y=150.0)
    assert DecapDistance().check(_ctx(board, model, model)) == []


def test_a_capacitor_whose_supply_pad_is_not_placed_is_unmeasurable_not_far():
    """The gap needs the capacitor's pad on the net, and its absence is not zero.

    A capacitor the schematic names but this PCB document places with no pad on
    the supply net has no loop length to measure. The rule stays silent (its
    documented state for 「the candidates exist, this PCB document does not carry
    them」) rather than borrowing another net's distance.
    """
    model, board = _decap_board(cap_x=0.0, cap_y=250.0)
    board.pads = [pad for pad in board.pads if pad.id != "C1.1"]
    assert DecapDistance().check(_ctx(board, model, model)) == []


# ===========================================================================
# focthermal — the region query is restricted to the rotated rectangle
# ===========================================================================


SYNTH_DRIVER_MPN = "SYNTHDRV-000"


def _driver_shelf():
    return PartLibrary(
        parts=[
            PartEntry(
                key="synthetic:driver",
                value=SYNTH_DRIVER_MPN,
                mpn=SYNTH_DRIVER_MPN,
                category="ic.motor-driver",
            )
        ]
    )


def _driver_ctx(board):
    component = type(
        "_Component",
        (),
        {
            "mpn": SYNTH_DRIVER_MPN,
            "lcsc_part": "",
            "value": SYNTH_DRIVER_MPN,
            "pins": (),
            "footprint": "SYNTH-WQFN",
        },
    )()
    model = type("_Model", (), {"components": {"U1": component}})()
    return PcbReviewContext(board=board, board_title="SYNTH", pcb_model=model)


def _rotated_thermal_board():
    """A 45° exposed pad, one via under it and one in the empty AABB corner.

    The pad is 200 × 100 mil at 45°, so its own area is 20 000 sq mil and its
    axis-aligned box reaches 212.13 mil on each side — 45 000 sq mil, of which
    the four corner triangles (25 000 sq mil) are not pad at all. The AABB
    corner point ``(100, -100)`` is 91.4 mil clear of the pad's own edge, so it
    is copper the old reading attributed to the projection and the new one does
    not. ``(31.8, -31.8)`` sits 45 mil along the pad's short axis — inside the
    rectangle's ±50 mil half-height — so it stays.
    """
    layers = {1: LayerInfo(1, "TOP", "SIGNAL"), 2: LayerInfo(2, "BOTTOM", "SIGNAL")}
    stackup = [
        StackupEntry(z_index=0, layer_id=1),
        StackupEntry(z_index=1, layer_id=2),
    ]
    pads = [
        _pad("U1", "1", x=0.0, y=0.0, net="VCC", width=30.0, height=11.3),
        PadGeometry(
            id="p-ep",
            component="U1",
            pin_number="33",
            net="GND",
            layer_id=1,
            effective_layer_ids=[1],
            x=0.0,
            y=0.0,
            width=200.0,
            height=100.0,
            shape="RECT",
            angle=45.0,
        ),
    ]
    vias = [
        ViaGeometry(
            id="v_inside", net="GND", x=31.8, y=-31.8,
            hole_diameter=12.008, via_diameter=24.016, via_type="NORMAL",
        ),
        ViaGeometry(
            id="v_outside", net="GND", x=100.0, y=-100.0,
            hole_diameter=12.008, via_diameter=24.016, via_type="NORMAL",
        ),
    ]
    return BoardGeometry(
        name="synthetic",
        layers=layers,
        stackup=stackup,
        components=[_place("U1", 0.0, 0.0, footprint="SYNTH-WQFN")],
        pads=pads,
        vias=vias,
        pours=[
            PourShape(
                id="pour1", net="GND", layer_id=2, kind="pour",
                points=[
                    Point(-100.0, -100.0),
                    Point(200.0, -100.0),
                    Point(200.0, 200.0),
                    Point(-100.0, 200.0),
                ],
            )
        ],
    )


def test_the_region_query_knows_the_pad_is_a_rotated_rectangle():
    """The leftover of 162a: an AABB projection is not the pad's projection.

    ``region_copper`` takes an axis-aligned box, so the rule's own reading of
    「what is under the pad」 was the box *around* a rotated rectangle. For this
    synthetic 45° pad the box is 2.25× the pad's area, and for ROBOT's real
    DRV1 EP it is 62 079 sq mil against the pad's 26 428 (measured, 2.35×). The
    fix keeps the primitive and restricts its answer to the elements that truly
    meet the pad's corner rectangle.
    """
    board = _rotated_thermal_board()
    thermal = thermal_pad_of(board, "U1")
    assert thermal is not None and thermal.pad.id == "p-ep"
    corners = thermal.pad
    assert (corners.width, corners.height, corners.angle) == (200.0, 100.0, 45.0)
    box = BBox.from_points(
        [
            Point(35.36, 106.07), Point(-106.07, -35.36),
            Point(-35.36, -106.07), Point(106.07, 35.36),
        ]
    )
    assert abs(box.width * box.height - 45000.0) < 50.0, (
        "the axis-aligned box really is 2.25x the pad's own 20 000 sq mil "
        "(212.13^2 = 45 000; the corners are read to two decimals above)"
    )

    rows = FocThermalExitPath().check_with_library(_driver_ctx(board), _driver_shelf())
    assert len(rows) == 1
    row = rows[0]
    joined = _evidence(row) + "\n" + row.message
    assert "via v_inside" in joined, "the via under the pad is still inventoried"
    assert "via v_outside" not in joined, (
        "the via in the empty corner of the box is not under the pad"
    )
    assert "pad U1.33" in joined, "the pad is under itself"
    assert "rotated" in joined, (
        "the evidence says which rectangle the projection is"
    )


# ===========================================================================
# the board frame — true polygon containment, 「touching is not over」 kept
# ===========================================================================


def _l_shaped_board(*, pad_x: float, pad_y: float):
    """An L-shaped board: the notch is ``x > 200 and y > 200``.

    The outline's axis-aligned box is ``(0,0)-(500,500)``, so a part in the
    notch is inside the box and outside the board. That is the case the old
    reading could not see.
    """
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place("C9", pad_x, pad_y)],
        pads=[_pad("C9", "1", x=pad_x, y=pad_y)],
    )
    board.outline = BoardOutline(
        points=[
            Point(0.0, 0.0),
            Point(500.0, 0.0),
            Point(500.0, 200.0),
            Point(200.0, 200.0),
            Point(200.0, 500.0),
            Point(0.0, 500.0),
        ],
        source_id="synthetic-L",
    )
    return board


def test_a_part_in_an_l_shaped_boards_notch_is_outside_the_board():
    """The board frame is a polygon, not its bounding box.

    ``C9`` is centred at ``(220, 220)`` with a 40 × 40 pad, so its four corners
    are at ``200..240`` on both axes: every one of them is in the notch, and the
    deepest is 40 mil past the two edges that bound it. The old reading compared
    the pad's box with the outline's box, found it inside, and said nothing —
    on a board where the part is off the board.
    """
    board = _l_shaped_board(pad_x=220.0, pad_y=220.0)
    findings = ComponentSpacing().check(_ctx(board))
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].target.component_ref == "C9"
    assert errors[0].target.measurement == {
        "kind": "distance", "value": 40.0, "unit": "mil",
    }
    assert "outline" in errors[0].message


def test_a_part_inside_the_l_and_one_touching_its_edge_file_nothing():
    """The two directions that must stay quiet, on the same outline.

    ``(100, 100)`` is inside the board. ``(180, 180)`` puts the pad's
    upper-right corner exactly on the notch's inner corner — the one point where
    the outline's two edges meet — so it is on the boundary and not past it, and
    「touching the edge is not over」 is the口径 126b pinned, kept verbatim.
    """
    inside = _l_shaped_board(pad_x=100.0, pad_y=100.0)
    assert ComponentSpacing().check(_ctx(inside)) == []

    touching = _l_shaped_board(pad_x=180.0, pad_y=180.0)
    assert ComponentSpacing().check(_ctx(touching)) == []


def test_a_rectangular_outline_still_measures_the_overhang_it_always_did():
    """The 126b anchor, re-derived against the polygon test: 40.0 mil, one edge.

    ``C9`` at ``(520, 100)`` with a 40 × 40 pad hangs 40 mil past the frame's
    right edge at 500 and is inside it on every other axis. A polygon test that
    returned 「the deepest corner's distance to the nearest edge」 must not turn
    that into a diagonal.
    """
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place("C9", 520.0, 100.0)],
        pads=[_pad("C9", "1", x=520.0, y=100.0)],
    )
    board.outline = BoardOutline(
        points=[
            Point(0.0, 0.0), Point(500.0, 0.0), Point(500.0, 500.0), Point(0.0, 500.0),
        ],
        source_id="synthetic-rect",
    )
    findings = [
        f for f in ComponentSpacing().check(_ctx(board)) if f.severity == "ERROR"
    ]
    assert len(findings) == 1
    assert findings[0].target.measurement == {
        "kind": "distance", "value": 40.0, "unit": "mil",
    }


def test_the_outline_polygon_helper_is_the_boards_own_shape():
    """A guard on the fixture itself, so the two tests above mean what they say."""
    board = _l_shaped_board(pad_x=220.0, pad_y=220.0)
    assert len(board.outline.points) == 6
    frame = BBox.from_points(board.outline.points)
    assert (frame.min_x, frame.min_y, frame.max_x, frame.max_y) == (0.0, 0.0, 500.0, 500.0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
