"""Task 164b: the power/MCU rules read the **schematic's** value, not the board's copy.

岳's ruling (``tasks/158``): 「PCB 审查的电气语义一律以原理图为准」. The PCB
document's own ``Value`` field is a **systematic placeholder**, measured on the
acceptance fixtures: 毕设FOC 1.0.0's ``PCB1`` contradicts the schematic on 98 of
122 parts (23 of them read ``100nF``, 20 read ``10K``), 1.1.0's on 99 of 105. The
two实锤 this stick was written for:

* **F1** — ``pcb-regulator-cap-distance`` filed ``C93`` as a *high-frequency
  bypass* because the PCB document copies ``100nF`` over the schematic's
  ``22µF``, and its evidence line claimed 「declared '100nF'」 while naming the
  schematic as the source. ``_pool_reason``'s sentence was, word for word, the
  lie the ruling is about.
* **F2** — ``pcb-mcu-supply-groups`` split the same way, so ``C1`` (schematic
  ``2.2µF``) was reported as a sub-1 µF bypass while ``pcb-derating-package`` —
  which 153 already repointed at the schematic — printed the very divergence
  ``C1 (原理图 '2.2uF' vs PCB 文档 '100nF')``.
* **F8** — ``pcb-mcu-crystal-placement`` computed the series-equivalent load
  from the board's copy: ROBOT's ``C2`` states ``12pF`` in the schematic and the
  PCB document says ``100nF``, so the row reported 串联等效 CL = **50005pF**
  against a 12 pF spec instead of 11 pF.

**The口径 under test** (the same one ``focground._value_ohms`` established in
153b): the **schematic page's** declaration wins, the PCB document's copy is only
a fallback, and when the two disagree **both are written into the evidence**.

**What this file pins, and where.** Every fixture test below goes through
:func:`boardwise.engines.pcbreview.run_pcb_review` **with ``model=`` set** — the
shape ``cli``'s ``checkup`` uses. That matters: the 131d/131e/131f suites call
the runner with no model, so their contexts carry ``ctx.model is None``, the
board link resolves to nothing, and those tables pin the *PCB-fallback* reading.
The production path always passes the schematic model, and this is the file that
pins what production actually reads. Fixtures are read-only; nothing here touches
an editor or a daemon.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.pcbreview import run_pcb_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.crystal import McuCrystalPlacement, is_crystal_member
from boardwise.rules.pcb.crystalkeepout import McuCrystalKeepout
from boardwise.rules.pcb.mcureset import McuResetBoot
from boardwise.rules.pcb.mcusupply import McuSupplyGroups
from boardwise.rules.pcb.regulator import RegulatorCapDistance

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"


@lru_cache(maxsize=None)
def _schematic(path: Path):
    """The fixture's schematic model, parsed once per session."""
    return build_project_model(path)


def _rows(path: Path, rule_id: str, rule=None) -> list:
    """The rule's rows, read the way ``checkup`` reads them (``model=`` set)."""
    rules = None if rule is None else [rule]
    findings, _section = run_pcb_review(path, model=_schematic(path), rules=rules)
    return [f for f in findings if f.rule_id == rule_id]


def _blob(rows) -> str:
    return "\n".join(f"{row.message}\n{' | '.join(row.evidence)}" for row in rows)


# ---------------------------------------------------------------------------
# synthetic helpers — one PCB view and one schematic page that disagree
# ---------------------------------------------------------------------------


def _pad(component: str, pin: str, *, x: float, y: float, net: str = "") -> PadGeometry:
    """One axis-aligned 40x40 pad (the same shape 131b's synthetic boards use)."""
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=1,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _comp(designator: str, *, value: str = "", mpn: str = "", pins=()) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        pins=list(pins),
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


def _board(parts, pads) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=x, y=y, layer_id=1)
            for d, x, y in parts
        ],
        pads=list(pads),
    )


def _schematic_page(components: list[Component], uuid: str = "sch-board-1"):
    """A stand-in for one schematic page: ``.board.uuid`` + ``.components``.

    All ``schematic_board_of`` reads from the project model is ``.boards``, each
    entry's ``.board.uuid`` and its ``.components`` — so a two-field stand-in is
    the whole contract, and using one keeps the synthetic case readable.
    """
    return SimpleNamespace(
        boards=[
            SimpleNamespace(
                board=SimpleNamespace(uuid=uuid),
                components={c.designator: c for c in components},
            )
        ]
    )


def _ctx(board, pcb_model, project, uuid: str = "sch-board-1") -> PcbReviewContext:
    return PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=project,
        intent=None,
        module_of={},
        pcb_model=pcb_model,
        board_uuid=uuid,
    )


def _shelf(category: str = "ic.ldo") -> PartLibrary:
    return PartLibrary(parts=[
        PartEntry(key="test.synthreg.c0", mpn="SYNTHREG", lcsc="C0", category=category)
    ])


# ---------------------------------------------------------------------------
# F1 — regulator-cap-distance reads the schematic page
# ---------------------------------------------------------------------------


def test_f1_c93_is_energy_storage_and_the_evidence_names_both_views():
    """毕设FOC 1.0.0 ``PCB1``: ``C93`` declares ``22µF`` on the schematic.

    The PCB document copies ``100nF`` over it, which is what filed a 22 µF part
    into the ``< 1 µF`` pool. Under the ruling it is **energy storage**, and the
    evidence says which view said what rather than 「declared '100nF'」.
    """
    rows = _rows(FOC_100, "pcb-regulator-cap-distance", RegulatorCapDistance())
    hf = _blob([r for r in rows if "nearest high-frequency" in r.message])
    storage = _blob([r for r in rows if "nearest energy storage" in r.message])
    assert "candidate C93" in storage, "C93 must be offered to the storage pool"
    assert "energy storage pool" in storage
    assert "原理图 '22uF'" in storage, "the schematic's own declaration"
    assert "PCB 文档 '100nF'" in storage, "and the board copy it disagrees with"
    # The old reading: 「C93 ... declared '100nF' = 0.1 µF < 1 µF」.
    assert "candidate C93: declared '100nF'" not in hf
    assert "C93: declared '100nF' = 0.1 µF < 1 µF — high-frequency bypass pool" not in hf


def test_f1_u5_vin_hf_pool_no_longer_hands_u5_a_22_microfarad_part():
    """The pinned case, on the row that was wrong: U5's ``VIN`` net ``+5V``.

    131b's own anchor recorded 「U5's VIN storage pool empty / nearest HF
    ``C93 @ 521.2 mil``」. ``C93`` is a **storage** part, so it may appear in the
    storage row and must not be the HF nearest.
    """
    rows = _rows(FOC_100, "pcb-regulator-cap-distance", RegulatorCapDistance())
    vin_hf = [
        r for r in rows
        if "VIN" in r.message and "'+5V'" in r.message
        and "high-frequency bypass" in r.message
    ]
    assert vin_hf, "the U5/U6 VIN rows must exist on PCB1"
    for row in vin_hf:
        assert "is C93 " not in row.message, (
            f"C93 (schematic 22µF) is still the HF nearest: {row.message}"
        )


def test_f1_the_pool_is_read_from_the_schematic_page_when_the_two_disagree():
    """The synthetic case, with nothing but the two views to argue about.

    ``pcb_model`` says ``C_ST`` is ``100nF``; the schematic page says ``2.2µF``.
    The rule must measure a 2.2 µF part — i.e. the schematic — and say so.
    """
    pcb_model = _model([
        _comp("U1", mpn="SYNTHREG", pins=[
            Pin("1", "VIN", "VIN_NET"), Pin("2", "VOUT", "OUT_NET"),
        ]),
        _comp("C_ST", value="100nF", pins=[
            Pin("1", "1", "OUT_NET"), Pin("2", "2", "AGND"),
        ]),
    ])
    schematic = _schematic_page([
        _comp("U1", mpn="SYNTHREG"),
        _comp("C_ST", value="2.2uF"),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C_ST", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="VIN_NET"),
            _pad("U1", "2", x=0.0, y=0.0, net="OUT_NET"),
            _pad("C_ST", "1", x=60.0, y=0.0, net="OUT_NET"),
            _pad("C_ST", "2", x=60.0, y=0.0, net="AGND"),
        ],
    )
    ctx = _ctx(board, pcb_model, schematic)
    rows = RegulatorCapDistance().check_with_library(ctx, _shelf())
    storage = [r for r in rows if "nearest energy storage" in r.message]
    hf = [r for r in rows if "nearest high-frequency" in r.message]
    assert any("is C_ST at" in r.message for r in storage), (
        "2.2 µF is storage under 裁定 ③, whatever the board copy says"
    )
    assert not any("is C_ST at" in r.message for r in hf)
    blob = _blob(storage)
    assert "原理图 '2.2uF'" in blob and "PCB 文档 '100nF'" in blob


def test_f1_a_board_with_no_schematic_page_falls_back_and_says_so():
    """``schematic=None`` is an ordinary answer, not a licence to guess.

    With no board link the PCB document's copy is the only value there is, and
    the row must read it **and say it is a fallback** rather than claim the
    schematic declared it.
    """
    pcb_model = _model([
        _comp("U1", mpn="SYNTHREG", pins=[Pin("1", "VIN", "VIN_NET")]),
        _comp("C_ST", value="100nF", pins=[
            Pin("1", "1", "VIN_NET"), Pin("2", "2", "AGND"),
        ]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C_ST", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="VIN_NET"),
            _pad("C_ST", "1", x=60.0, y=0.0, net="VIN_NET"),
            _pad("C_ST", "2", x=60.0, y=0.0, net="AGND"),
        ],
    )
    ctx = _ctx(board, pcb_model, None)
    rows = RegulatorCapDistance().check_with_library(ctx, _shelf())
    hf = [r for r in rows if "nearest high-frequency" in r.message]
    assert hf, "with no schematic page the board copy is still measured"
    blob = _blob(hf)
    assert "回退 PCB 文档值" in blob, "the fallback must be visible on the row"


# ---------------------------------------------------------------------------
# F2 — mcu-supply-groups splits the same way
# ---------------------------------------------------------------------------


def test_f2_c1_is_a_reservoir_not_a_sub_microfarad_bypass():
    """毕设FOC 1.0.0 ``PCB1``: ``C1`` declares ``2.2µF`` on the schematic.

    131e's pinned anchor reads it as 「nearest 高频旁路 **C1** 100nF @ 33.5 mil」
    on the ``GND`` group. Under the ruling that same row must carry 2.2 µF and
    put ``C1`` in the reservoir column.
    """
    rows = _rows(FOC_100, "pcb-mcu-supply-groups", McuSupplyGroups())
    gnd = [r for r in rows if "supply group 'GND'" in r.message]
    assert gnd
    message = gnd[0].message
    assert "**C1** 2.2uF @ 33.5 mil" in message, message
    assert "**C1** 100nF" not in message, "the board copy's placeholder is gone"


def test_f2_the_supply_row_and_the_derating_row_agree_on_c1():
    """Two rules, one part, one value — 岳's ruling is what makes them agree.

    ``pcb-derating-package`` was repointed at the schematic by 153 and prints
    ``C1 (原理图 '2.2uF' vs PCB 文档 '100nF')``. The supply row must quote the
    same pair, and no rule may still call ``C1`` a ``100nF`` part.
    """
    supply = _blob(_rows(FOC_100, "pcb-mcu-supply-groups", McuSupplyGroups()))
    derating = _blob(_rows(FOC_100, "pcb-derating-package"))
    assert "原理图 '2.2uF'" in supply and "PCB 文档 '100nF'" in supply
    assert "C1 (原理图 '2.2uF' vs PCB 文档 '100nF')" in derating
    assert "C1 value 100nF" not in supply, "the VCAP row's old reading is gone"
    assert "C1 value 2.2uF" in supply


def test_f2_the_pool_split_reads_the_schematic_page_too():
    """The synthetic case for the same口径, on the empty-pool branch as well."""
    pcb_model = _model([
        _comp("U1", mpn="SYNTHMCU", pins=[
            Pin("1", "VDD", "V_NET"), Pin("2", "VSS", "GND"),
        ]),
        _comp("C_ST", value="100nF", pins=[
            Pin("1", "1", "V_NET"), Pin("2", "2", "GND"),
        ]),
    ])
    schematic = _schematic_page([
        _comp("U1", mpn="SYNTHMCU"),
        _comp("C_ST", value="4.7uF"),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C_ST", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="V_NET"),
            _pad("U1", "2", x=0.0, y=0.0, net="GND"),
            _pad("C_ST", "1", x=60.0, y=0.0, net="V_NET"),
            _pad("C_ST", "2", x=60.0, y=0.0, net="GND"),
        ],
    )
    ctx = _ctx(board, pcb_model, schematic)
    library = PartLibrary(parts=[
        PartEntry(key="test.synthmcu.c1", mpn="SYNTHMCU", lcsc="C1", category="ic.mcu")
    ])
    rows = McuSupplyGroups().check_with_library(ctx, library)
    group = [r for r in rows if "'V_NET'" in r.message]
    assert group
    message = group[0].message
    assert "**C_ST** 4.7uF @ 20.0 mil" in message, message
    assert "**none** — the pool holds no capacitor below" in message, (
        "the bypass column is empty because 4.7 µF is not a bypass"
    )


def test_f2_a_board_with_no_schematic_page_says_it_is_a_fallback():
    """No board link: the copy is used, and the row admits it."""
    pcb_model = _model([
        _comp("U1", mpn="SYNTHMCU", pins=[
            Pin("1", "VDD", "V_NET"), Pin("2", "VSS", "GND"),
        ]),
        _comp("C_ST", value="100nF", pins=[
            Pin("1", "1", "V_NET"), Pin("2", "2", "GND"),
        ]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C_ST", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="V_NET"),
            _pad("C_ST", "1", x=60.0, y=0.0, net="V_NET"),
            _pad("C_ST", "2", x=60.0, y=0.0, net="GND"),
        ],
    )
    ctx = _ctx(board, pcb_model, None)
    library = PartLibrary(parts=[
        PartEntry(key="test.synthmcu.c1", mpn="SYNTHMCU", lcsc="C1", category="ic.mcu")
    ])
    rows = McuSupplyGroups().check_with_library(ctx, library)
    assert "回退 PCB 文档值" in _blob(rows)


# ---------------------------------------------------------------------------
# mcu-reset-boot — the inventory's values
# ---------------------------------------------------------------------------


def test_reset_net_member_values_read_the_schematic_page():
    """``NRST``'s members are described by the value the schematic declares.

    The bucket test itself stays where it is (a member's *own shape* decides
    which bucket it is in); what follows the ruling is the value the row prints
    and the value a reader compares against the reset-time question.
    """
    pcb_model = _model([
        _comp("U1", mpn="SYNTHMCU", pins=[
            Pin("1", "NRST", "NRST"), Pin("2", "VSS", "GND"),
        ]),
        _comp("C_R", value="100nF", pins=[
            Pin("1", "1", "NRST"), Pin("2", "2", "GND"),
        ]),
    ])
    schematic = _schematic_page([
        _comp("U1", mpn="SYNTHMCU"),
        _comp("C_R", value="2.2uF"),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C_R", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="NRST"),
            _pad("U1", "2", x=0.0, y=0.0, net="GND"),
            _pad("C_R", "1", x=60.0, y=0.0, net="NRST"),
            _pad("C_R", "2", x=60.0, y=0.0, net="GND"),
        ],
    )
    ctx = _ctx(board, pcb_model, schematic)
    library = PartLibrary(parts=[
        PartEntry(key="test.synthmcu.c1", mpn="SYNTHMCU", lcsc="C1", category="ic.mcu")
    ])
    rows = McuResetBoot().check_with_library(ctx, library)
    assert rows, "an NRST pin with a member produces a row"
    blob = _blob(rows)
    assert "C_R value 2.2uF" in blob, blob
    assert "原理图 '2.2uF'" in blob and "PCB 文档 '100nF'" in blob


def test_boot_strap_values_read_the_schematic_page():
    """Same for the boot row: the strap is described by the schematic's value."""
    pcb_model = _model([
        _comp("U1", mpn="SYNTHMCU", pins=[
            Pin("1", "BOOT0", "BOOT0"), Pin("2", "VSS", "GND"),
        ]),
        _comp("R_B", value="10K", pins=[
            Pin("1", "1", "BOOT0"), Pin("2", "2", "GND"),
        ]),
    ])
    schematic = _schematic_page([
        _comp("U1", mpn="SYNTHMCU"),
        _comp("R_B", value="4.7K"),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("R_B", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="BOOT0"),
            _pad("R_B", "1", x=60.0, y=0.0, net="BOOT0"),
            _pad("R_B", "2", x=60.0, y=0.0, net="GND"),
        ],
    )
    ctx = _ctx(board, pcb_model, schematic)
    library = PartLibrary(parts=[
        PartEntry(key="test.synthmcu.c1", mpn="SYNTHMCU", lcsc="C1", category="ic.mcu")
    ])
    rows = McuResetBoot().check_with_library(ctx, library)
    assert rows
    blob = _blob(rows)
    assert "R_B value 4.7K" in blob, blob
    assert "原理图 '4.7K'" in blob and "PCB 文档 '10K'" in blob


# ---------------------------------------------------------------------------
# F8 — the crystal rules
# ---------------------------------------------------------------------------


def test_f8_load_capacitance_is_computed_from_the_schematic_declaration():
    """ROBOT: ``C2`` declares ``12pF``; the board copy reads ``100nF``.

    The old row computed 串联等效 CL = 50005pF against a 12 pF spec — a
    placeholder value read as physics. With the schematic's 12 pF the equivalent
    is ``12/2 + 5 = 11 pF``.
    """
    rows = _rows(ROBOT, "pcb-mcu-crystal-placement", McuCrystalPlacement())
    blob = _blob(rows)
    assert "C2" in blob
    assert "实测容值 12pF" in blob, "the schematic's declaration"
    assert "11pF" in blob, "12/2 + 5pF parasitic"
    assert "50005pF" not in blob, "the 100nF placeholder's arithmetic is gone"
    assert "原理图 '12pF'" in blob and "PCB 文档 '100nF'" in blob


def test_f8_the_1_1_0_load_caps_read_20pf_not_100nf():
    """毕设FOC 1.1.0 ``PCB1``: ``C20``/``C21`` declare ``20pF``.

    The board copy says ``100nF`` for both, which produced 串联等效 CL =
    50005pF. The schematic's 20 pF gives ``20/2 + 5 = 15 pF``, and the row is
    still a three-column measurement with no verdict.
    """
    rows = _rows(FOC_110, "pcb-mcu-crystal-placement", McuCrystalPlacement())
    blob = _blob(rows)
    for designator in ("C20", "C21"):
        assert f"{designator}" in blob
    assert "实测容值 20pF" in blob
    assert "15pF" in blob
    assert "50005pF" not in blob
    assert "合格" not in blob and "不合格" not in blob


def test_f8_crystal_recognition_is_unchanged_across_the_corpus():
    """The sieve's verdict must not move: it is an identity step, not a value.

    Measured on the four acceptance fixtures: 1.0.0's ``X1``, 1.1.0's ``X1``,
    ROBOT's ``X2`` and 药箱's ``X1`` (+ its ``BUZZER2``, whose ``2.7kHz`` the
    frequency hint has always read as a crystal — a pre-existing false positive
    this stick neither introduces nor fixes). Reading the schematic page's
    declaration (falling back to the board's) keeps every one of them.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.engines.pcbreview import _pcb_documents
    from boardwise.rules.pcb.focground import schematic_board_of

    expected = {
        "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2": {("PCB1", "X1")},
        "ProPrj_毕设FOC驱动板_2026-09-17.epro2": {("PCB1", "X1")},
        "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2": {("PCB1", "X2")},
        "ProPrj_智能药箱_2026-09-17.epro2": {("PCB1", "X1"), ("PCB1", "BUZZER2")},
    }
    for name, want in expected.items():
        path = FIXTURES / name
        source = load_epro2_source(path)
        footprints = source.footprints()
        artwork = source.footprint_artwork()
        found: set[tuple[str, str]] = set()
        for title, uuid, document in _pcb_documents(source):
            model = build_design_model(source, document)
            ctx = PcbReviewContext(
                board=None, board_title=title, model=_schematic(path),
                module_of={}, pcb_model=model, board_uuid=uuid,
            )
            page = schematic_board_of(ctx)
            found |= {
                (title, d)
                for d in model.components
                if is_crystal_member(model, d, page)
            }
        assert found == want, f"{name}: {found}"


def test_f8_the_crystal_identity_line_quotes_the_schematic_declaration():
    """ROBOT's ``X2``: both views state ``8MHz``, and the row says which one won.

    1.0.0's ``X1`` is the interesting shape in the other direction — the
    schematic states **nothing**, so the board's ``25MHz`` is used *as a
    fallback*, and the row says so instead of implying the schematic wrote it.
    """
    robot = _blob(_rows(ROBOT, "pcb-mcu-crystal-placement", McuCrystalPlacement()))
    assert "crystal X2" in robot and "8MHz" in robot
    assert "原理图" in robot
    foc = _blob(_rows(FOC_100, "pcb-mcu-crystal-placement", McuCrystalPlacement()))
    assert "回退 PCB 文档值" in foc and "'25MHz'" in foc


def test_f8_crystalkeepout_identity_reads_through_the_same_page():
    """131f's identity line is the same object read the same way.

    The keepout rule names the crystal by the sieve and quotes its value and
    footprint; that line now carries the two-view reading too, so 131d and 131f
    cannot describe the same part differently.
    """
    rows = _rows(FOC_100, "pcb-mcu-crystal-keepout", McuCrystalKeepout())
    blob = _blob(rows)
    assert "recognised as a crystal" in blob
    assert "回退 PCB 文档值" in blob and "'25MHz'" in blob
    assert "SMD3225-4P" in blob, "the schematic page's own footprint is quoted"
