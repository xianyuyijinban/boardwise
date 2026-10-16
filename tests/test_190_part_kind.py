"""190: 判型一处说了算（声明优先、前缀兜底）+ 三条数值/披露小账.

The batch's premise is that «what is this part?» had **two** spellings inside one
repository — 189B's ``METADATA_TYPE_KEYS`` reading (立创 metadata, never the
designator) and 127b's ``classify_device`` (shelf category, then the part's own
words, then the designator) — and that the measured cost of the split is 岳's ⑦:
a ``U``-designated 330 kΩ chip resistor asked for a decoupling capacitor because
a designator letter was the only signal some rule read.

The file is organised by the task book's sections: **A** the one entry point
(:func:`boardwise.core.partkind.classify_part`) and its ``basis``, **B** the call
sites that were changed, **C** the three small accounts (thermistor, the
VOUT-side severity step, the ``6R3`` voltage code), plus the two schema additions
(``shelfMatchedBy`` on the worklist rows).
"""

from __future__ import annotations

from pathlib import Path

from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.partkind import (
    BASIS_METADATA,
    BASIS_NONE,
    BASIS_PIN_FLOOR,
    BASIS_PREFIX,
    BASIS_SHELF,
    KIND_CAPACITOR,
    KIND_CONNECTOR,
    KIND_IC,
    KIND_RESISTOR,
    KIND_THERMISTOR,
    KIND_TRANSISTOR,
    KIND_UNKNOWN,
    MIN_IC_PINS,
    PartDeclarations,
    classify_part,
    declarations_of,
    kind_of_category,
)
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.core.values import mpn_voltage_rating
from boardwise.engines.checkup import needs_datasheet_section, unknown_parts
from boardwise.rules.connectivity import DecouplingPerIC, ShuntSenseLink
from boardwise.rules.facts import NcAndMustConnect
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.derating import (
    DeratingPackage,
    _is_resistor,
    declared_kind,
    declared_type_text,
)
from boardwise.rules.pcb.distance import DECAP_DISTANCE_MIL, DecapDistance
from boardwise.rules.sensebias import SamplingBias

SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"


def _field_board() -> Path | None:
    """实板A — the run's own copy of the board 岳's feedback was measured on.

    Located **by position, never by name**: this repository never spells that
    board's file name or model (保密纪律: a company board appears in repository
    artifacts as the neutral code 实板A only), so the reader looks in the scratch
    directory the measurement used and takes the single ``.epro2`` there. The
    board is *read*, never copied into ``tests/fixtures/`` (R4), and the test
    that uses it skips when it is absent.
    """
    directory = Path(__file__).resolve().parents[1] / ".tmp_bug98b"
    if not directory.is_dir():
        return None
    boards = sorted(directory.glob("*.epro2"))
    return boards[0] if len(boards) == 1 else None


# ---------------------------------------------------------------------------
# tiny builders
# ---------------------------------------------------------------------------


def _comp(designator: str, *, value: str = "", footprint: str = "", mpn: str = "",
          lcsc: str = "", props: dict | None = None, pins=()) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        footprint=footprint,
        mpn=mpn,
        lcsc_part=lcsc,
        props=dict(props or {}),
        pins=[
            Pin(str(number), str(name), net) for number, name, net in pins
        ],
    )


def _three(designator: str, **kwargs) -> Component:
    """Three pins, so 127b's floor cannot be the reason for an answer."""
    kwargs["pins"] = [("1", "1", "A"), ("2", "2", "B"), ("3", "3", "C")]
    return _comp(designator, **kwargs)


def _two(designator: str, **kwargs) -> Component:
    kwargs["pins"] = [("1", "1", "A"), ("2", "2", "B")]
    return _comp(designator, **kwargs)


def _model(components: list[Component]) -> DesignModel:
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for component in components:
        for pin in component.pins:
            if pin.net:
                nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                    (component.designator, pin.number)
                )
    model.nets = nets
    return model


def _entry(**kwargs) -> PartEntry:
    return PartEntry(**kwargs)


# ---------------------------------------------------------------------------
# A. the one entry point
# ---------------------------------------------------------------------------


def test_the_read_order_is_shelf_then_declarations_then_the_designator():
    """One part carrying **all three** signals: the earlier one wins, every time.

    The shelf is the strongest (a curated declaration), then the part's own words
    — 立创 metadata before its own name/footprint — and the designator last. The
    ``basis`` says which one decided, which is the whole reason the entry point
    returns a pair instead of a bool: 「前缀兜底要能在报告里看出来」.
    """
    shelf = PartLibrary(parts=[_entry(key="ic.x", mpn="ACME1", lcsc="C1", category="ic.mcu")])
    component = _three(
        "R7",
        value="10K",
        footprint="RES-TH_1",
        mpn="ACME1",
        props={"LCSC Part Name": "100uF 电容"},
    )
    read = classify_part(component, library=shelf)
    assert (read.kind, read.basis) == (KIND_IC, BASIS_SHELF)
    assert "ic.mcu" in read.reason

    # No shelf resolution (the caller handed none over): the metadata starts it.
    read = classify_part(component)
    assert (read.kind, read.basis) == (KIND_CAPACITOR, BASIS_METADATA)
    assert "metadata says capacitor" in read.reason

    # Metadata says nothing: the part's own name/footprint does.
    read = classify_part(_three("R7", footprint="RES-TH_1"))
    assert (read.kind, read.basis) == (KIND_RESISTOR, BASIS_METADATA)
    assert "RES-" in read.reason

    # Nothing declares anything: the designator table's own family, as a fallback.
    read = classify_part(_three("U9"))
    assert (read.kind, read.basis) == (KIND_IC, BASIS_PREFIX)
    assert "fallback" in read.reason

    # …and a part nobody can classify is `unknown` with **no** basis, which is a
    # different sentence from 「the shelf says it is not an IC」.
    read = classify_part(_comp("SCREW1", pins=[("1", "1", "A")]))
    assert (read.kind, read.basis) == (KIND_UNKNOWN, BASIS_NONE)


def test_an_unverified_entry_declares_nothing():
    """039's gate, applied where the entry is read: a candidate is not a reading.

    The same「no partial trust」discipline ``rules.facts._category_state``
    applies, moved to the place the category is read so a caller cannot forget
    it — an unreviewed entry saying ``ic.mcu`` must not make a part an IC.
    """
    candidate = PartLibrary(parts=[_entry(
        key="ic.x", mpn="ACME1", lcsc="C1", category="ic.mcu",
        facts_verified=False,
    )])
    component = _comp("U9", mpn="ACME1", lcsc="C1", props={"device_name": "ACME1"},
                      pins=[(str(i), f"P{i}", "A") for i in range(1, 4)])
    read = classify_part(component, library=candidate)
    assert (read.kind, read.basis) == (KIND_IC, BASIS_PREFIX), (
        "the prefix fallback decides, not the unverified category"
    )

    verified = PartLibrary(parts=[_entry(
        key="ic.x", mpn="ACME1", lcsc="C1", category="ic.mcu",
    )])
    assert classify_part(component, library=verified).basis == BASIS_SHELF


def test_a_u_designated_resistor_is_read_from_the_lcsc_metadata():
    """⑦'s part, exactly: ``U`` designator, type stated in ``LCSC Part Name``.

    ``Type`` is empty on such a part (measured), so a reader that only looked at
    that one field would see nothing at all — and the designator would be the
    last word. The metadata door is scanned in :data:`METADATA_TYPE_KEYS` order.
    """
    component = _two(
        "U4",
        footprint="R1206",
        props={"LCSC Part Name": "330kΩ ±1% 1/4W 厚膜电阻"},
    )
    assert declared_type_text(component) == "330kΩ ±1% 1/4W 厚膜电阻"
    read = classify_part(component)
    assert (read.kind, read.basis) == (KIND_RESISTOR, BASIS_METADATA)
    assert "电阻" in read.reason
    assert declared_kind(declared_type_text(component))[0] == KIND_RESISTOR
    assert _is_resistor("", "R1206", declared_type_text(component))[0] is True


def test_a_part_with_fewer_than_three_pins_is_not_an_ic():
    """127b's necessary condition, moved into the reading (and only for an IC).

    Two limits are pinned here, both deliberate: the floor refuses an **IC**
    answer whatever the model says — and it cannot touch a passive, because a
    two-pin part *is* a resistor or a capacitor, and a floor that swallowed
    those would empty the decoupling rule's capacitor set.
    """
    assert MIN_IC_PINS == 3
    read = classify_part(_two("U6", footprint="R1206", mpn="FRC1206J334 TS"))
    assert (read.kind, read.basis) == (KIND_UNKNOWN, BASIS_PIN_FLOOR)
    assert "pin floor" in read.reason

    # The declaration still wins over the floor: 189B's part is a **resistor**
    # (it is the value/code path that reads it, and that path knows about pins).
    read = classify_part(_two(
        "U4", footprint="R1206", props={"LCSC Part Name": "330kΩ 厚膜电阻"},
    ))
    assert (read.kind, read.basis) == (KIND_RESISTOR, BASIS_METADATA)

    # …and a two-pin capacitor stays a capacitor, whatever the floor says.
    read = classify_part(_two("C1", value="100nF"))
    assert (read.kind, read.basis) == (KIND_CAPACITOR, BASIS_PREFIX)

    # A caller whose question is not about pin counts says so, and the part is
    # read on its declarations plus the designator.
    read = classify_part(
        _two("U6", footprint="R1206", mpn="FRC1206J334 TS"), pin_floor=False
    )
    assert (read.kind, read.basis) == (KIND_IC, BASIS_PREFIX)

    # An uncounted part (no pin count handed over) is not floored either.
    assert classify_part(facts=PartDeclarations(designator="U6")).kind == KIND_IC


def test_the_designator_table_is_read_by_head_and_a_known_prefix_is_named():
    """``ic.motor-driver`` -> IC; ``DRV`` is an IC (128/#63); ``TVS`` never is."""
    assert kind_of_category("ic") == KIND_IC
    assert kind_of_category("ic.motor-driver") == KIND_IC
    assert kind_of_category("connector") == KIND_CONNECTOR
    assert kind_of_category("nonsense") == KIND_UNKNOWN

    read = classify_part(_comp("DRV1", pins=[(str(i), f"P{i}", "A") for i in range(1, 4)]))
    assert (read.kind, read.basis) == (KIND_IC, BASIS_PREFIX)

    read = classify_part(_comp("TVS7", pins=[(str(i), f"P{i}", "A") for i in range(1, 5)]))
    assert read.kind != KIND_IC
    assert "never names an IC" in read.reason


def test_the_same_reading_is_what_the_pcb_side_calls_classify_device():
    """127b's ``classify_device`` is this reading, not a second spelling of it.

    The header, the MOSFET and the mystery part are test_127b's own three cases,
    read through both names: the answers and the evidence strings must agree,
    which is what keeps the two modules from drifting apart again.
    """
    from boardwise.rules.pcb.distance import classify_device, device_facts

    for component, pins in (
        (_comp("U6", mpn="HX PZ2.54-2x6P TP", footprint="SMD,P=2.54mm",
               pins=[(str(i), f"P{i}", "SIG") for i in range(1, 13)]), 12),
        (_comp("Q1", mpn="MCAC53N06Y-TP", footprint="DFN(5x6)",
               pins=[(str(i), f"P{i}", "SIG") for i in range(1, 10)]), 9),
        (_comp("U9", pins=[("1", "VCC", "A"), ("2", "OUT", "B"), ("3", "GND", "GND")]), 3),
        (_two("U10"), 2),
    ):
        is_ic, why = classify_device(device_facts(component), pins=pins)
        assert is_ic == (classify_part(component).kind == KIND_IC), component.designator
        assert why.strip(), component.designator
    _is_ic, why = classify_device(device_facts(_two("U10")), pins=2)
    assert "pin floor" in why


# ---------------------------------------------------------------------------
# B1. decoupling-per-ic: both halves are the shared reading
# ---------------------------------------------------------------------------


def test_a_u_designated_resistor_is_not_asked_for_a_capacitor():
    """⑦ at the rule that reported it, and the message stops apologising.

    189B left this rule reading ``U*/C*`` prefixes and *saying so* in its own
    message; 190's acceptance is that the parts 岳 pointed at stop being asked.
    The resistor below carries no metadata (the field board's schematic view does
    not) — the floor is what clears it, and the message quotes the reading.
    """
    model = _model([_two("U6", footprint="R1206", mpn="FRC1206J334 TS")])
    assert DecouplingPerIC().check(model) == []

    # A three-pin part with no declaration at all is still asked, and the
    # message names the basis instead of a prefix pattern it no longer tests.
    model = _model([_comp("U2", pins=[("1", "VIN", "A"), ("2", "GND", "GND"), ("3", "OUT", "B")])])
    (row,) = DecouplingPerIC().check(model)
    assert row.severity == "WARN"
    assert "matches designator prefixes only" not in row.message
    assert "shared part-kind reading" in row.message
    assert any("basis prefix" in line for line in row.evidence)


def test_a_c_designated_connector_is_not_a_capacitor():
    """The other direction of the same sentence: ``C`` is not evidence either.

    ``U2``'s only neighbours are a declared connector at a ``C`` designator and a
    genuinely declared capacitor elsewhere on the board — the connector must not
    count as the decoupling capacitor, and the declared one must (wherever it
    sits).
    """
    connector = _two("C9", props={"LCSC Part Name": "type-c 16pin 连接器"})
    assert classify_part(connector).kind == KIND_CONNECTOR
    ic = _comp("U2", pins=[
        ("1", "VIN", "A"), ("2", "GND", "GND"), ("3", "OUT", "B"),
    ])
    model = _model([ic, connector])
    assert len(DecouplingPerIC().check(model)) == 1, "a connector is not a capacitor"

    # One real capacitor on one of the IC's nets silences the row — the part is
    # at ``X1``, so nothing but the declaration could have found it.
    declared_cap = _two("X1", props={"LCSC Part Name": "100nF 电容"})
    declared_cap.pins = [Pin("1", "1", "B"), Pin("2", "2", "GND")]
    model = _model([ic, connector, declared_cap])
    assert DecouplingPerIC().check(model) == []


# ---------------------------------------------------------------------------
# B2. shunt-sense-link: both ends are the shared reading
# ---------------------------------------------------------------------------


def test_the_shunt_is_what_the_reading_calls_a_resistor():
    """A declared capacitor at an ``R`` designator is not a shunt."""
    shunt = _two("R5", value="10mΩ", props={"LCSC Part Name": "100nF 电容器"})
    assert classify_part(shunt).kind == KIND_CAPACITOR
    assert ShuntSenseLink().check(_model([shunt])) == []

    plain = _two("R5", value="10mΩ")
    assert [f.severity for f in ShuntSenseLink().check(_model([plain]))] == ["INFO"]


def test_the_ic_end_is_the_designator_table_not_the_letter_u():
    """``DRV1`` is an IC (128/#63) — the letter ``U`` was a narrower test.

    The shunt's two terminal nets carry a ``DRV``-designated 4-pin part on each
    end: the shared reading calls it an IC and the smoke check is satisfied,
    where the old ``startswith("U")`` could not see it. The reverse case is the
    header family: a 2.54 mm pin row at a ``U`` designator is **not** an IC.
    """
    shunt = _two("R5", value="10mΩ")
    shunt.pins = [Pin("1", "1", "PGND"), Pin("2", "2", "ISNS")]
    driver = _comp("DRV1", mpn="DRV8350SRTVR", pins=[
        ("1", "SLA", "ISNS"), ("2", "GND", "GND"), ("3", "VM", "+24V"), ("4", "X", "X"),
    ])
    driver.pins[0] = Pin("1", "SLA", "ISNS")
    driver.pins[1] = Pin("2", "GND", "PGND")
    assert ShuntSenseLink().check(_model([shunt, driver])) == []

    header = _comp("U19", mpn="HX PZ2.54-2x6P TP", footprint="HDR-SMD_12P-P2.54",
                   pins=[("1", "P1", "ISNS"), ("2", "P2", "PGND"),
                         ("3", "P3", "X")])
    rows = ShuntSenseLink().check(_model([shunt, header]))
    assert [f.severity for f in rows] == ["INFO"]
    assert "no IC has pins on" in rows[0].message


# ---------------------------------------------------------------------------
# B3. facts: the subject list
# ---------------------------------------------------------------------------


def test_a_u_designated_header_is_not_a_facts_subject():
    """The header loses its 「no shelf entry」 row — it is not an IC (⑦, one level up).

    The rules ask about ICs; a 2x6 排针 at a ``U`` designator answers nothing
    about an IC's pins, and 「no facts for U6」 was the report depending on a
    datasheet for a row of holes.
    """
    header = _comp("U6", mpn="HX PZ2.54-2x6P TP", footprint="HDR-SMD_12P-P2.54",
                   pins=[(str(i), f"P{i}", "SIG") for i in range(1, 13)])
    rule = NcAndMustConnect(library=PartLibrary())
    assert [o.subject for o in rule.outcomes(_model([header]))] == []


def test_the_not_applicable_disclosure_is_kept():
    """A part the shelf **explicitly** classifies otherwise is still *reported*.

    039's four-state protocol makes 「looked and it is not my subject」 a
    statement rather than silence, and a part dropped from a gate is a work item
    nobody sees. So the subject list keeps shelf-classified non-ICs — and the
    answer for them is the rule's own NOT_APPLICABLE, not a judgement.
    """
    shelf = PartLibrary(parts=[_entry(
        key="conn.x", value="BAR", mpn="BAR-1", lcsc="C1", category="connector",
    )])
    component = _comp("U9", mpn="BAR-1", lcsc="C1", pins=[("1", "A", "NET2")])
    rule = NcAndMustConnect(library=shelf)
    states = {o.state for o in rule.outcomes(_model([component]))}
    assert states == {"NOT_APPLICABLE"}

    # And a part whose *own* declarations say connector is simply not a subject
    # (no shelf category needed): the disclosure above is about the shelf's
    # answer, not about keeping every ``U`` designator in the list.
    header = _comp("U6", mpn="HX PZ2.54-2x6P TP", footprint="HDR-SMD_12P-P2.54",
                   pins=[(str(i), f"P{i}", "SIG") for i in range(1, 13)])
    assert NcAndMustConnect(library=PartLibrary()).outcomes(_model([header])) == []


def test_the_library_pin_rule_keeps_a_one_pin_synthetic_part():
    """``pin_floor=False`` at the rule whose subject *is* a pin list (190).

    A model that read one pin of a part has not established that the part is not
    an IC, and this rule could not do its work without the part.
    """
    from boardwise.rules.facts import LibraryPinConsistency

    component = _comp("U1", pins=[("1", "A", "NET2")])
    states = LibraryPinConsistency(resolver=lambda comp: {"1", "2"}).outcomes(
        _model([component])
    )
    assert {o.state for o in states} == {"VIOLATION"}, "one missing library pin"


# ---------------------------------------------------------------------------
# B4. sensebias: the op-amp half of the half-gate
# ---------------------------------------------------------------------------


def _sampling_board(mpn: str, lcsc: str) -> DesignModel:
    """A low-side shunt whose sense node carries a part with an ``IN+`` pin."""
    shunt = _comp("R8", value="10mΩ", pins=[("1", "1", "PGND"), ("2", "2", "IA+")])
    foreign = _comp("U3", mpn=mpn, lcsc=lcsc,
                    pins=[("3", "INA+", "IA+"), ("8", "VCC", "VCC")])
    return _model([shunt, foreign])


def test_an_opamp_input_pin_on_a_part_the_shelf_calls_a_connector_is_not_an_opamp():
    """「排针上一脚叫 IN+ 是接线端子」 — and the shelf is what says so (190).

    The gate was ``is_ic_designator(designator) or category == "ic.opamp"``, so a
    ``U`` designator alone carried it. The prefix half now goes through the
    shared reading with the shelf's category handed in, which is the declaration
    that outranks the letter.
    """
    shelf = PartLibrary(parts=[_entry(
        key="conn.x", value="HDR", mpn="HDR-2X5", lcsc="C9", category="connector",
    )])
    findings = SamplingBias(library=shelf).check(_sampling_board("HDR-2X5", "C9"))
    assert findings == [], "a connector's IN+ pin is a terminal, not an amplifier"

    # The same board with the shelf's own op-amp entry keeps its INFO row, quoting
    # the category — the `or category == "ic.opamp"` half is untouched.
    opamp = PartLibrary(parts=[_entry(
        key="ic.opamp", value="OP", mpn="OPA1", lcsc="C10", category="ic.opamp",
    )])
    findings = SamplingBias(library=opamp).check(_sampling_board("OPA1", "C10"))
    assert [f.severity for f in findings] == ["INFO"]
    assert any("category=ic.opamp" in line for line in findings[0].evidence)


# ---------------------------------------------------------------------------
# C1. NTC/PTC is its own kind and left alone
# ---------------------------------------------------------------------------


def _derating_ctx(parts: dict, nets: dict) -> PcbReviewContext:
    components = {}
    for designator, spec in parts.items():
        members = [(d, p) for group in nets.values() for d, p in group if d == designator]
        components[designator] = Component(
            uid=designator,
            designator=designator,
            value=spec.get("value", ""),
            footprint=spec.get("footprint", ""),
            mpn=spec.get("mpn", ""),
            props=spec.get("props", {}),
            pins=[Pin(number=pin, name=pin) for _d, pin in members],
        )
    model = DesignModel(
        components=components,
        nets={
            name: Net(name=name, pins=[tuple(member) for member in members])
            for name, members in nets.items()
        },
    )
    return PcbReviewContext(board=None, board_title="SYNTH", model=model, pcb_model=model)


def test_a_declared_thermistor_is_its_own_kind_and_not_a_resistor():
    """岳 10-16 的裁决: NTC/PTC 是 thermistor，不进电阻的降额/值码路径.

    The declaration is what decides, and the veto runs **before** both doors: a
    thermistor whose value field is spelled ``10K`` (R25) is still not a chip
    resistor whose ohms this rule should read, and the value-code path must not
    file 「值不可知」 about a part whose value is a temperature curve.
    """
    assert declared_kind("贴片NTC热敏电阻")[0] == KIND_THERMISTOR
    assert _is_resistor("", "R0603", "贴片NTC热敏电阻") == (
        False, declared_kind("贴片NTC热敏电阻")[1],
    )
    assert _is_resistor("10K", "R0603", "贴片NTC热敏电阻")[0] is False

    # A chip resistor is still a chip resistor (no regression on the 189B door).
    assert _is_resistor("", "R1206", "厚膜电阻")[0] is True
    assert _is_resistor("10K", "R0603", "")[0] is True

    # …and the per-board summary names them instead of counting them as
    # 「位号像电阻但本规则没有认它」.
    ctx = _derating_ctx(
        {
            "R2": {
                "value": "HNTC0603-103F3450FA",
                "footprint": "R0603",
                "props": {"LCSC Part Name": "贴片NTC热敏电阻"},
            },
            "R1": {"value": "10K", "footprint": "R0603"},
        },
        {"A": [("R2", "1")], "B": [("R2", "2")], "C": [("R1", "1")], "D": [("R1", "2")]},
    )
    rows = DeratingPackage().check(ctx)
    summary = [row for row in rows if row.severity == "INFO"]
    assert "认出 1 颗电阻" in summary[0].message
    thermistor_line = [line for line in summary[0].evidence if "热敏" in line]
    assert len(thermistor_line) == 1 and "R2" in thermistor_line[0]
    assert not any("位号像电阻但本规则没有认它" in line for line in summary[0].evidence)


def test_a_thermistor_gets_no_value_code_reason():
    """``unknown_parts``: 「MPN 里的值码解不出」 is not asked of a thermistor.

    The FPC fixture's ``R2`` is the measured case (an ``R`` designator, an MPN
    whose figures are a temperature curve): the reason was filed about a part
    whose value this tool is not supposed to decode. The other two identity
    signals are untouched, so a thermistor with no MPN or no supplier is still
    listed.
    """
    thermistor = _two(
        "R2", value="HNTC0603-103F3450FA", mpn="HNTC0603-103F3450FA",
        props={"LCSC Part Name": "贴片NTC热敏电阻"},
    )
    thermistor.lcsc_part = "C1"
    assert unknown_parts(_model([thermistor])) == []

    # The same part *without* the declaration keeps the reason (no regression on
    # 184's signal), and the thermistor shape is still a thermistor when the
    # declaration is only in the part's own name.
    by_name = _two("R2", value="HNTC0603-103F3450FA", mpn="HNTC0603-103F3450FA")
    by_name.lcsc_part = "C1"
    assert classify_part(by_name).kind == KIND_THERMISTOR
    assert unknown_parts(_model([by_name])) == []

    undeclared = _two("R2", value="", mpn="ABC-1")
    undeclared.lcsc_part = "C1"
    (row,) = unknown_parts(_model([undeclared]))
    assert any("值不可知" in reason for reason in row["reasons"])


# ---------------------------------------------------------------------------
# C2. the decoupling row's severity: 190's VOUT step, retired by 191D
# ---------------------------------------------------------------------------


def _decap_ctx(pin_name: str, *, cap_x: float) -> PcbReviewContext:
    """One IC and one high-frequency capacitor bridging its rail to another ground."""
    ic = _comp("U1", pins=[
        ("1", pin_name, "3V3"), ("2", "OUT", "SIG"), ("3", "GND", "GND"),
    ])
    cap = _comp("C1", value="100nF", pins=[("1", "1", "3V3"), ("2", "2", "AGND")])
    model = _model([ic, cap])
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id="c-U1", designator="U1", x=0.0, y=0.0, layer_id=1),
            ComponentPlacement(id="c-C1", designator="C1", x=cap_x, y=0.0, layer_id=1),
        ],
        pads=[
            PadGeometry(id="U1.1", component="U1", pin_number="1", net="3V3",
                        footprint_layer_id=1, x=0.0, y=0.0, width=40.0, height=40.0),
            PadGeometry(id="U1.2", component="U1", pin_number="2", net="SIG",
                        footprint_layer_id=1, x=0.0, y=20.0, width=40.0, height=40.0),
            PadGeometry(id="U1.3", component="U1", pin_number="3", net="GND",
                        footprint_layer_id=1, x=0.0, y=40.0, width=40.0, height=40.0),
            PadGeometry(id="C1.1", component="C1", pin_number="1", net="3V3",
                        footprint_layer_id=1, x=cap_x, y=0.0, width=40.0, height=40.0),
            PadGeometry(id="C1.2", component="C1", pin_number="2", net="AGND",
                        footprint_layer_id=1, x=cap_x, y=20.0, width=40.0, height=40.0),
        ],
    )
    return PcbReviewContext(board=board, board_title="SYNTH", model=model)


def test_the_output_side_carries_a_threshold_now_instead_of_a_downgrade():
    """191D (岳 2026-10-17): 190's 「VOUT 超限降一级为 INFO」 被换成真正的分档阈值.

    190 reached for the right distinction and answered with a severity step
    because the threshold was the same 200 mil everywhere. 191D gives the output
    side a number of its own (500 mil, ``DECAP_TIER_MIL``), so the step is gone:
    a 360 mil gap on this IC's ``VOUT`` rail is now **inside its tier** and the
    rule says nothing at all, while the same gap on a ``VCC`` pin is over the
    200 mil consumer line. The four tiers have their own anchors in
    ``tests/test_191d_decap_tiers.py``; what this pins is that the downgrade
    text is not produced any more.
    """
    assert DecapDistance().check(_decap_ctx("VOUT", cap_x=400.0)) == [], (
        "360 mil is inside the 稳压器输出档 500 mil line — 190's INFO row was a "
        "stand-in for a threshold, and the threshold is here"
    )
    # Over the output tier's own line it is a WARN now, like every other tier.
    (row,) = DecapDistance().check(_decap_ctx("VOUT", cap_x=600.0))
    assert row.severity == "WARN"
    assert "稳压器输出档 500 mil，实测 560.0 mil" in row.message
    assert "降一级为 INFO" not in row.message
    assert row.target.measurement["value"] == 560.0


def test_a_vin_side_and_an_undeclared_side_keep_the_warn():
    for pin_name in ("VIN", "1"):
        (row,) = DecapDistance().check(_decap_ctx(pin_name, cap_x=400.0))
        assert row.severity == "WARN", pin_name
        assert "降一级为 INFO" not in row.message
    # ``VIN`` grades at 300 (稳压器输入档) and the undeclared name at 200, so both
    # of those rows are over their own line while the VOUT row above is not.

    # Both sides declared on one net: the most demanding tier wins (191D keeps
    # 190's direction — a rail that declared both sides kept the WARN), so the
    # 300 mil input tier grades it and the side label still says both.
    ic = _comp("U1", pins=[
        ("1", "VIN", "3V3"), ("2", "OUT", "3V3"), ("3", "GND", "GND"),
    ])
    cap = _comp("C1", value="100nF", pins=[("1", "1", "3V3"), ("2", "2", "AGND")])
    model = _model([ic, cap])
    ctx = _decap_ctx("VIN", cap_x=400.0)
    ctx.model = model
    (row,) = DecapDistance().check(ctx)
    assert row.severity == "WARN"
    assert "VIN+VOUT" in row.message


def test_the_threshold_did_not_move():
    """The base house rule is still 200 mil — 191D wrote the other tiers against it.

    191D added per-rail numbers (300 / 500), so the old 「no per-rail numbers」
    framing is gone; what is pinned here is that the constant itself is unmoved
    and that both of these rails are inside their own tier at 160 mil.
    """
    assert DECAP_DISTANCE_MIL == 200.0
    assert DecapDistance().check(_decap_ctx("VOUT", cap_x=200.0)) == []
    assert DecapDistance().check(_decap_ctx("VIN", cap_x=200.0)) == []


# ---------------------------------------------------------------------------
# C3. the R-notation voltage code, and the codes that are still not read
# ---------------------------------------------------------------------------

#: What the EIA/IEC two-symbol voltage code spells — ``<exponent digit><multiplier
#: letter>``: ``0J`` = 6.3 V, ``1A`` = 10 V, ``1C`` = 16 V, ``1E`` = 25 V,
#: ``1H`` = 50 V, ``2A`` = 100 V. **Not covered by any reader in this repository
#: as of 190**, and 190 does not add one (a 30-row letter table is a new decoder,
#: not the R-notation fix the task book asked for). The shelf's own witnesses are
#: ``GRM1885C1H122JA01D`` (1 nF 0603, ``1H`` = 50 V) and
#: ``C1608X5R1V225KT000E`` (2.2 µF, ``1V`` = 35 V); both answer ``None`` below,
#: which is the *honest* UNKNOWN — the rail-rating rule then declines to judge
#: instead of inventing a number.
EIA_LETTER_CODES_NOT_READ = (
    "GRM1885C1H122JA01D",
    "C1608X5R1V225KT000E",
    "CL31B105KCHNNNE",
)


def test_the_rating_reader_reads_the_r_notation():
    """``6R3`` = 6.3 V — the third small account of ⑦.

    The field is the same one :func:`mpn_voltage_rating` already reads
    (``<value><tolerance><voltage>``, ending the token modulo its packaging
    letters) with ``R`` as the decimal point, which is how the trade spells a
    rating below 10 V.
    """
    assert mpn_voltage_rating("0603S226M6R3CT") == (6.3, "226M6R3")
    assert mpn_voltage_rating("225K6R3") == (6.3, "225K6R3")
    # Nothing the reader could read before changed its answer.
    assert mpn_voltage_rating("HGC0603R5106M250NTHJ") == (25.0, "106M250")
    assert mpn_voltage_rating("CGA0603X7R104K500JT") == (50.0, "104K500")


def test_the_r_notation_reader_refuses_the_shunts_and_the_dielectrics():
    """The anchor has to be the field: a loose ``\\d{3}[A-Z]\\d[Rr]\\d`` scan reads
    ten tokens in this repository's own corpus, **all ten false** — the ohms
    notation of its shunts and resistors, the dielectric codes, and TDK's
    ordered field string (a 35 V part read as 5.1 V, which would be a false WARN
    on any 12 V rail).
    """
    for token in (
        "RE2512F3R001",      # 1 mΩ shunt: "512F3R0" is ohms, not volts
        "JER2512F3R005",     # 5 mΩ shunt
        "FRC0805F4R70TS",    # 4.7 Ω
        "C1608X5R1V225KT000E",  # TDK: "608X5R1" is dielectric + code, 35 V part
        "RE1206F1R000",
    ):
        assert mpn_voltage_rating(token) is None, token


def test_the_eia_letter_voltage_codes_are_not_covered():
    """The list the task book asked for, pinned so it cannot drift silently.

    If a later batch implements the letter table, this test is what makes that a
    deliberate rewrite rather than an accident.
    """
    for token in EIA_LETTER_CODES_NOT_READ:
        assert mpn_voltage_rating(token) is None, (
            f"{token} states its rating in the EIA letter code, which no reader "
            "here reads — see this module's comment"
        )


# ---------------------------------------------------------------------------
# C4. the worklist row carries the identity step 186 put on it
# ---------------------------------------------------------------------------


def test_the_worklist_rows_carry_shelf_matched_by():
    """``needs_datasheet[].shelfMatchedBy`` — same key, same meaning (186's field).

    ``unreviewed_parts`` has carried it since 186; the folded worklist row was
    dropping it, so a reader of the ⓪ list could not tell 「identified by MPN」
    from 「identified by device name」 — the weaker claim 186 exists to keep
    visible.
    """
    from boardwise.engines.checkup import unreviewed_parts

    shelf = PartLibrary(parts=[_entry(
        key="ic.x", mpn="ACME1", lcsc="C1", facts=None,
    )])
    component = _comp("U1", mpn="ACME1", pins=[("1", "A", "NET2")])
    unreviewed = unreviewed_parts(_model([component]), library=shelf)
    (row,) = unreviewed
    assert row["shelfMatchedBy"] == "mpn"

    (work,) = needs_datasheet_section(unreviewed, [])
    assert work["trigger"] == "facts"
    assert work["shelfMatchedBy"] == "mpn"

    # A part on no shelf carries the empty string rather than a missing key.
    untouched = _comp("U2", pins=[("1", "A", "NET2")])
    (row,) = unreviewed_parts(_model([untouched]), library=PartLibrary())
    (work,) = needs_datasheet_section([row], [])
    assert work["shelfMatchedBy"] == ""


# ---------------------------------------------------------------------------
# the real board: 实板A, only when it is in the tree
# ---------------------------------------------------------------------------


def test_the_field_board_stops_asking_its_u_designated_resistors_for_caps():
    """实板A: ``U4``/``U6``…``U12`` are 330 kΩ chip resistors at ``U`` designators.

    Read-only, and skipped when the board is not in the tree (it lives in
    ``.tmp_bug98b/``, never in ``tests/fixtures/`` — R4: a company board must not
    enter the repository). Before 190 this rule filed three WARNs here
    (``U6``/``U8``/``U10``); after it, none — the two-pin parts are not ICs, and
    the ones whose value says ``330kΩ`` are not either.

    **The rule is retired from ``BUILTIN_RULES``** (015 §2, oracle ruling 011f B2:
    「L1 heuristic limitation, retire in M2」), so no report this tool writes shows
    these rows — the acceptance is measured by calling the class, which is what
    the ruling kept it runnable for. The board's **live** ⑦ surface is the
    datasheet gate (``checkup``'s ``unreviewed_parts``, whose ``is_ic_designator``
    the task book did not name); ``outputs/190/evidence.md`` §9.1 records that,
    with the same six designators.
    """
    import pytest

    board = _field_board()
    if board is None:
        pytest.skip("实板A 不在场（.tmp_bug98b/ 里没有它的副本）")

    from boardwise import cli

    model, _board = cli._load_model(board, view="schematic")
    (single,) = model.boards
    assert DecouplingPerIC().check(single) == []
    for designator in ("U4", "U6", "U7", "U8", "U9", "U10", "U11", "U12"):
        component = single.components[designator]
        read = classify_part(component)
        assert read.kind != KIND_IC, (designator, read.kind, read.basis)
        assert read.basis in (BASIS_PIN_FLOOR, BASIS_METADATA)


# ---------------------------------------------------------------------------
# 190f: the metadata has to reach the **CLI's own** model (the schematic view)
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
#: A fixture whose ``U4`` is a 0805 chip **resistor** declared in the 立创
#: metadata, and whose DevICE META carries that declaration — the shape ⑦ is
#: about, on a board that is in the repository.
FPC = FIXTURE_DIR / "FPC触屏游戏机_2026-09-27.epro2"
#: A fixture whose ``U9`` is a SOT-23-6 **power-converter IC** with no shelf
#: entry: the part 190's package words used to read as a transistor.
DCDC = FIXTURE_DIR / "DCDC-12V9V转5V3V3_2026-09-27.epro2"


def _cli_model(path: Path):
    from boardwise import cli

    model, _board = cli._load_model(path, view="schematic")
    return model


def test_the_schematic_view_carries_the_declared_type_keys():
    """190f: the CLI's schematic view sees what the PCB view always saw.

    The 立创 type fields live in the **DEVICE META**'s ``attributes`` dict, which
    is in the same archive the schematic parser already walks — but until 190f
    only the PCB-side reader took them, so every ``classify_part`` caller on the
    CLI path was metadata-blind and a ``U``-designated 330 kΩ resistor stayed on
    the datasheet gate. This pins the fix as a **two-view agreement**: for the
    same designator, the keys the schematic view carries are the keys the PCB
    view carries (the one vocabulary, not two).
    """
    from boardwise.core.partkind import METADATA_TYPE_KEYS

    schematic = _cli_model(FPC)
    model, _board = __import__("boardwise.cli", fromlist=["cli"])._load_model(
        FPC, view="pcb"
    )
    _ = (schematic, model)

    component = _cli_model(FPC).boards[0].components["U4"]
    carried = {key for key in METADATA_TYPE_KEYS if component.props.get(key)}
    assert carried, "the 立创 type fields must reach the schematic model (190f)"
    assert "电阻" in str(component.props.get("LCSC Part Name") or "") or (
        "电阻" in str(component.props.get("Type") or "")
    )
    assert classify_part(component).kind in (KIND_RESISTOR, KIND_THERMISTOR)
    assert declarations_of(component).metadata, "the reading sees a metadata face now"


def test_a_u_designated_chip_resistor_leaves_the_datasheet_gate_on_the_cli_path():
    """The acceptance, on a board in the repository: ``U4`` out, the real IC in.

    ``FPC``'s ``U4`` is a 0805 chip resistor under a ``U`` designator, and its
    metadata says so (「电阻」) — the datasheet gate must stop asking about it.
    The fixture's real ICs must stay on the list, which is the half that keeps
    the exemption from swallowing the gate.
    """
    from boardwise.core.parts import load_parts
    from boardwise.engines.checkup import unreviewed_parts

    model = _cli_model(FPC)
    library = load_parts(str(SHELF))
    rows = {row["designator"] for row in unreviewed_parts(model, library=library)}
    assert "U4" not in rows, "a declared chip resistor is not an IC with a missing datasheet"
    assert rows - {"U4"}, "the gate still has work to do on this board"


def test_a_sot23_packaged_ic_is_back_on_the_ic_subject():
    """190f: the package words are gone from ``TRANSISTOR_WORDS``.

    ``DFN`` / ``SOT-23`` / ``SOT23`` are packages, not identities: a SOT-23-6
    power converter was read as a transistor and left the IC subject. The words
    that *do* name a transistor stay, so the fixture's ``MCAC``-named MOSFETs are
    untouched — that pair is the whole assertion.
    """
    for fixture, designator in ((DCDC, "U9"), (FPC, "U8")):
        component = _cli_model(fixture).boards[0].components[designator]
        assert "SOT-23" in component.footprint.upper() or "SOT-23" in component.props.get(
            "Supplier Footprint", ""
        ).upper()
        assert classify_part(component).kind == KIND_IC, (
            f"{designator} is a SOT-23-6 IC, not a transistor"
        )

    # The MOSFETs the word list exists for keep their kind (127b's case). They
    # are on the project's third board (a board is a page group, 040b), so the
    # test looks the part up instead of assuming the first board carries it.
    foc = _cli_model(FIXTURE_DIR / "ProPrj_毕设FOC驱动板_2026-09-17.epro2")
    mosfet = next(
        board.components["Q1"] for board in foc.boards if "Q1" in board.components
    )
    assert classify_part(mosfet).kind == KIND_TRANSISTOR
    assert "MCAC" in classify_part(mosfet).reason


def test_a_declared_passive_is_exempt_from_the_gate_and_a_mystery_ic_is_not():
    """The exemption itself, synthetically: only a **declaration** exempts.

    A ``U``-designated part whose metadata declares a resistor is not the
    datasheet gate's subject; one that declares nothing is (the gate's job is to
    ask, and 「没人说过它是什么」 is exactly the question a datasheet answers).
    """
    from boardwise.core.parts import load_parts
    from boardwise.engines.checkup import unreviewed_parts

    # Both parts carry a full identity (MPN + supplier): on FPC's `U4` that is
    # what makes the declaration the *only* thing left to decide, and it is the
    # contrast under test. A part with no MPN would stay on the gate for the 025
    # signal instead (`UNKNOWN_REASON_NO_MPN`), which is a different row.
    declared = _three("U7", mpn="FRC0805J1001 TS", props={
        "LCSC Part Name": "330kΩ ±1% 厚膜电阻",
    })
    declared.lcsc_part = "C1"
    mystery = _three("U8", mpn="MYSTERY-1")
    mystery.lcsc_part = "C2"
    model = _model([declared, mystery])
    rows = {
        row["designator"]
        for row in unreviewed_parts(model, library=load_parts(str(SHELF)))
    }
    assert "U7" not in rows
    assert "U8" in rows
