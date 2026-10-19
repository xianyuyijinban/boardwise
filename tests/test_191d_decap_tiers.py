"""Tests for task 191D: 去耦距离按电源轨分档（岳 2026-10-17 裁）.

The one 200 mil line 126b/190 graded every decoupling rail by became four, and
**which of the four grades a row is read from the part's own pins on the net
being measured** — not from the net's name and not from the part's function in
general (the same ``+5V`` is U5's ``VIN`` and U11's ``VOUT``, 131b's measured
case). Every case below is synthetic, with the gap **derived by hand next to the
assertion**: pads are 40x40 mil at stated coordinates, so the edge-to-edge
distance is ``|x1 - x2| - 40`` in one axis.

What this module pins, in order:

1. the four labels and their four numbers, against the constants rather than
   against copies of them;
2. the pin-name table's split — which names are 消耗端供电脚 and which of the
   ``IN`` family are 稳压器输入 (the split is the new judgement);
3. each tier's line, at the line and one printable step past it, with the tier's
   name and number **in the message**;
4. that the tier is read per (part, net) pair, so one capacitor serving two ICs
   is graded twice — and can be over one line and inside the other;
5. that the FOC pack's TI figure is the same number this table's consumer tier
   carries, which is what 「与它同口径」 means in the task book.

The corpus measurement (which real rows moved, and why) is in
``outputs/191d/evidence.md`` rather than here: it is a before/after over 15
boards, and a test that re-derived it would be a second implementation of the
comparison script.
"""

from __future__ import annotations

import pytest

from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.distance import (
    DECAP_DISTANCE_MIL,
    DECAP_TIER_CONSUMER,
    DECAP_TIER_MIL,
    DECAP_TIER_ORDER,
    DECAP_TIER_PINS,
    DECAP_TIER_REGULATOR_IN,
    DECAP_TIER_REGULATOR_OUT,
    DECAP_TIER_UNDECLARED,
    DecapDistance,
    _decap_rail_tier,
    _tier_pin,
)

#: The rail measured in every case below. A supply net to the rule's own reader
#: (:func:`boardwise.core.power_domains.infer_net_domains` knows ``+5V`` / ``3V3``
#: by name), so the cases are about the tier and never about whether the net
#: counts as a supply net at all.
RAIL = "+5V"
#: The capacitor's other terminal. A ground net that is not the IC's own, so the
#: capacitor really bridges this rail to ground (039 批①b's predicate, inherited
#: through :func:`boardwise.rules.decap.cap_candidates_on`).
BRIDGE = "AGND"


# ---------------------------------------------------------------------------
# tiny builders (the shape test_126b / test_190 use for this rule)
# ---------------------------------------------------------------------------


def _comp(designator: str, *, value: str = "", pins=()) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        pins=[Pin(str(number), str(name), net) for number, name, net in pins],
    )


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


def _pad(component: str, pin: str, *, x: float, y: float, net: str) -> PadGeometry:
    """One axis-aligned 40x40 mil pad: it spans ``[x-20, x+20]`` × ``[y-20, y+20]``."""
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        footprint_layer_id=1,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
    )


def _place(designator: str, x: float, y: float) -> ComponentPlacement:
    return ComponentPlacement(
        id=f"c-{designator}", designator=designator, x=x, y=y, layer_id=1
    )


def _ctx(board: BoardGeometry, model: DesignModel) -> PcbReviewContext:
    return PcbReviewContext(board=board, board_title="SYNTH", model=model)


def _ctx_of(pin_name: str, *, cap_x: float) -> PcbReviewContext:
    """One IC whose ``RAIL`` pin is named ``pin_name``, and one bypass capacitor.

    The IC's other pins are the shape 127b's floor and 190's classifier need for
    the part to be an IC at all (three pins, one of them a grounded ``GND``), and
    they sit on nets the rule does not measure, so the only pin the tier can read
    is the one under test.
    """
    ic = _comp(
        "U1",
        pins=[("1", pin_name, RAIL), ("2", "OUT", "SIG"), ("3", "GND", "GND")],
    )
    cap = _comp("C1", value="100nF", pins=[("1", "1", RAIL), ("2", "2", BRIDGE)])
    model = _model([ic, cap])
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place("U1", 0.0, 0.0), _place("C1", cap_x, 0.0)],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net=RAIL),
            _pad("U1", "2", x=0.0, y=20.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=40.0, net="GND"),
            _pad("C1", "1", x=cap_x, y=0.0, net=RAIL),
            _pad("C1", "2", x=cap_x, y=20.0, net=BRIDGE),
        ],
    )
    return _ctx(board, model)


# ---------------------------------------------------------------------------
# 1. the table itself: four labels, four numbers, and where they come from
# ---------------------------------------------------------------------------


def test_the_tier_table_is_the_four_numbers_the_ruling_names():
    """200 / 300 / 800 / 200 mil, and the base two are the constant 126b pinned.

    The exercise is that the number a finding prints and the number it compares
    against are **one value**: both come out of :data:`DECAP_TIER_MIL`, and the
    two tiers at 200 are written as :data:`DECAP_DISTANCE_MIL` rather than as a
    second literal 200.0, so a later re-tuning of the base moves them together.
    """
    assert DECAP_TIER_ORDER == (
        DECAP_TIER_CONSUMER,
        DECAP_TIER_REGULATOR_IN,
        DECAP_TIER_REGULATOR_OUT,
    ), "the precedence order is most-demanding first; 侧别读不出 is not one of them"
    assert DECAP_TIER_MIL == {
        DECAP_TIER_CONSUMER: 200.0,
        DECAP_TIER_REGULATOR_IN: 300.0,
        DECAP_TIER_REGULATOR_OUT: 800.0,
        DECAP_TIER_UNDECLARED: 200.0,
    }
    assert DECAP_TIER_MIL[DECAP_TIER_CONSUMER] == DECAP_DISTANCE_MIL
    assert DECAP_TIER_MIL[DECAP_TIER_UNDECLARED] == DECAP_DISTANCE_MIL
    assert DECAP_TIER_UNDECLARED not in DECAP_TIER_ORDER, (
        "a rail whose names declared nothing is not competing with the three "
        "readings; it is the absence of one"
    )


def test_the_pin_table_splits_the_consumer_names_from_the_regulator_input():
    """The new judgement: every ``IN``-role name is not the same question.

    ``VIN``/``PVIN`` mean *the part produces this rail's counterpart* — the
    capacitor is sited for a stage that does not end at that pin — while
    ``VCC``/``VDD``/``AVDD``… mean *the part eats this rail*. Both read as
    ``"IN"`` through :func:`boardwise.core.pinrole.pin_role`, which is why the
    split is a table here; the names the classifier declines outright (``AVDD``,
    ``PVIN``, ``VS`` have no entry in its whole-name table) are entries too.
    """
    for name in ("VCC", "VDD", "AVDD", "DVDD", "VDDA", "VBAT", "VS"):
        assert _tier_pin(name) == DECAP_TIER_CONSUMER, name
    for name in ("VIN", "PVIN"):
        assert _tier_pin(name) == DECAP_TIER_REGULATOR_IN, name
    for name in ("VOUT", "SW"):
        assert _tier_pin(name) == DECAP_TIER_REGULATOR_OUT, name

    # The table is the *split* only: names the classifier already knows are read
    # through it rather than re-listed here (``VDD_1``, ``VOUTA``, ``OUTPUT``),
    # and a name that declares nothing reads nothing.
    assert _tier_pin("VDD_1") == DECAP_TIER_CONSUMER
    assert _tier_pin("VOUTA") == DECAP_TIER_REGULATOR_OUT
    assert _tier_pin("OUTPUT") == DECAP_TIER_REGULATOR_OUT
    assert _tier_pin("AVDD_1") == DECAP_TIER_CONSUMER, "the token scan reads the family"
    assert _tier_pin("RON") is None and _tier_pin("1") is None
    assert _tier_pin("PH0-OSC_IN") is None, (
        "131d's refusal holds here too: an oscillator pin is not a supply tier"
    )
    assert all(
        tier in DECAP_TIER_MIL for tier in DECAP_TIER_PINS.values()
    ), "every tier the table names has a threshold"


# ---------------------------------------------------------------------------
# 2. each tier grades at its own line: at the line, and one step past it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pin_name", "tier", "limit"),
    [
        ("VCC", "消耗端供电脚档", 200.0),
        ("VIN", "稳压器输入档", 300.0),
        ("VOUT", "稳压器输出档", 800.0),
        ("1", "侧别读不出档", 200.0),
    ],
)
def test_each_tier_grades_at_its_own_line(pin_name, tier, limit):
    """四档各一条：刚好在阈值内 → 静默；刚好超 → WARN 且 message 带档名与阈值.

    ``cap_x = limit + 40`` puts the capacitor's pad edge exactly ``limit`` mil
    from the IC's, which the rule reads as **inside** (the comparison is
    ``<=``, the convention 126b pinned). One printable step further — the tenth
    of a mil :func:`boardwise.rules.pcb.distance._mil` rounds to — is over it.
    """
    assert DECAP_TIER_MIL[tier] == limit

    at_the_line = _ctx_of(pin_name, cap_x=limit + 40.0)
    reading = _decap_rail_tier(at_the_line.model.components["U1"], RAIL)
    assert reading.name == tier and reading.limit == limit
    assert DecapDistance().check(at_the_line) == [], (
        f"{pin_name} at exactly {limit} mil is inside the {tier} line"
    )

    past_it = _ctx_of(pin_name, cap_x=limit + 40.1)
    (row,) = DecapDistance().check(past_it)
    assert row.severity == "WARN", "over the tier's own line is a WARN on every tier"
    assert row.target.measurement["value"] == round(limit + 0.1, 1)
    assert f"{tier} {limit:.0f} mil，实测 {limit + 0.1:.1f} mil" in row.message, row.message
    assert f"over the line this rail's own tier draws" in row.message
    # The reason travels with the row: which pin of which part read the tier.
    (tier_evidence,) = [
        line for line in row.evidence if line.startswith("tier reading (191D):")
    ]
    if tier == DECAP_TIER_UNDECLARED:
        assert "no pin of U1" in tier_evidence, tier_evidence
    else:
        assert f"pin 1 ({pin_name!r})" in tier_evidence, tier_evidence


# ---------------------------------------------------------------------------
# 3. the tier is read per (part, net) pair
# ---------------------------------------------------------------------------


def test_the_tier_is_read_from_this_parts_own_pins_on_that_net():
    """``VIN`` on one rail and ``VOUT`` on another: two tiers, one part.

    The same shape 189B's rail-side test reads (so the two readers cannot
    disagree about a pin), and the same object: the tier is a statement about
    *this rail on this part*.
    """
    component = Component(
        uid="u-U1",
        designator="U1",
        pins=[
            Pin(number="1", name="VIN", net="+12V"),
            Pin(number="2", name="VOUT", net="3V3"),
            Pin(number="3", name="FB", net="FB1"),
        ],
    )
    assert _decap_rail_tier(component, "+12V").name == DECAP_TIER_REGULATOR_IN
    assert _decap_rail_tier(component, "3V3").name == DECAP_TIER_REGULATOR_OUT
    assert _decap_rail_tier(component, "FB1").name == DECAP_TIER_UNDECLARED
    assert _decap_rail_tier(component, "nowhere").name == DECAP_TIER_UNDECLARED

    output = _decap_rail_tier(component, "3V3")
    assert output.limit == 800.0
    assert "pin 2 ('VOUT')" in output.why and "800" in output.why
    undeclared = _decap_rail_tier(component, "FB1")
    assert undeclared.limit == DECAP_DISTANCE_MIL
    assert "no pin of U1" in undeclared.why


def test_the_most_demanding_tier_wins_when_one_net_carries_two():
    """``VIN`` and ``VCC`` tied to one rail: the strictest reading grades it.

    190's direction, kept: a rail that declared both of its sides kept the WARN
    rather than being carried to the loosest line. The evidence names the other
    pin as well, so the choice is readable rather than implicit.
    """
    both = Component(
        uid="u-U2",
        designator="U2",
        pins=[Pin(number="1", name="VIN", net="X"), Pin(number="2", name="VCC", net="X")],
    )
    reading = _decap_rail_tier(both, "X")
    assert reading.name == DECAP_TIER_CONSUMER
    assert reading.limit == 200.0
    assert "pin 2 ('VCC')" in reading.why
    assert "pin 1 ('VIN') as 稳压器输入档" in reading.why, (
        "the looser reading that lost is named, not silently dropped"
    )


def test_one_capacitor_serving_two_ics_is_graded_one_pair_at_a_time():
    """131b's shape: the same ``+5V`` is U5's ``VIN`` and U11's ``VOUT``.

    One capacitor, two (IC, rail) pairs, two tiers — and a 360.0 mil gap that is
    **over** U5's 300 mil input line and **inside** U11's 500 mil output line.
    So the answer is one WARN about U5 and silence about U11, which is only
    possible if the threshold is read per pair: a rule with one line would
    either file two rows or none.
    """
    u5 = _comp(
        "U5",
        pins=[("1", "VIN", RAIL), ("2", "OUT", "SIG"), ("3", "GND", "GND")],
    )
    u11 = _comp(
        "U11",
        pins=[("1", "VOUT", RAIL), ("2", "OUT", "SIG2"), ("3", "GND", "GND")],
    )
    cap = _comp("C1", value="100nF", pins=[("1", "1", RAIL), ("2", "2", BRIDGE)])
    model = _model([u5, u11, cap])
    # U11 sits 40 mil up in y, so its pad [20, 60] touches U5's [−20, 20] on that
    # axis: the edge-to-edge gap to C1 is the same 360.0 mil in x for both parts.
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            _place("U5", 0.0, 0.0),
            _place("U11", 0.0, 40.0),
            _place("C1", 400.0, 0.0),
        ],
        pads=[
            _pad("U5", "1", x=0.0, y=0.0, net=RAIL),
            _pad("U5", "2", x=0.0, y=20.0, net="SIG"),
            _pad("U5", "3", x=0.0, y=40.0, net="GND"),
            _pad("U11", "1", x=0.0, y=20.0, net=RAIL),
            _pad("U11", "2", x=0.0, y=60.0, net="SIG2"),
            _pad("U11", "3", x=0.0, y=80.0, net="GND"),
            _pad("C1", "1", x=400.0, y=0.0, net=RAIL),
            _pad("C1", "2", x=400.0, y=20.0, net=BRIDGE),
        ],
    )
    assert _decap_rail_tier(u5, RAIL).name == DECAP_TIER_REGULATOR_IN
    assert _decap_rail_tier(u11, RAIL).name == DECAP_TIER_REGULATOR_OUT

    rows = DecapDistance().check(_ctx(board, model))
    (row,) = rows
    assert row.target.component_ref == "U5", (
        "the row is U5's: on U11 the same 360 mil is inside its own 500 mil line"
    )
    assert row.severity == "WARN"
    assert row.target.measurement["value"] == 360.0
    assert "稳压器输入档 300 mil，实测 360.0 mil" in row.message
    assert row.target.counterpart_ref == "C1", "one capacitor, measured twice"


# ---------------------------------------------------------------------------
# 4. 「与它同口径」: the FOC pack's figure is this table's consumer tier
# ---------------------------------------------------------------------------


def test_the_foc_pack_quotes_the_consumer_tier_figure():
    """``rules/pcb/foc.py`` 的 TI 数字就是这个表的 消耗端供电脚档 值.

    The FOC rule measures a driver's **own** supply pins (``VM`` / ``DVDD`` /
    ``VCC``) — the pins the driver eats the rail through — so the tier it would
    read is the consumer one, whose number is the TI figure it already carries.
    That is what keeps the two rules from grading one pin two ways, and it is
    asserted here rather than left to the docstrings: the measured check that no
    FOC row moved over the corpus is in ``outputs/191d/evidence.md``.
    """
    from boardwise.rules.pcb.foc import TI_DECAP_REFERENCE_MIL

    assert TI_DECAP_REFERENCE_MIL == DECAP_TIER_MIL[DECAP_TIER_CONSUMER]
    for pin_name in ("VM", "DVDD", "VCC", "VINP"):
        tier = _tier_pin(pin_name)
        assert tier is not None, pin_name
    assert _tier_pin("VM") == DECAP_TIER_CONSUMER
    assert _tier_pin("DVDD") == DECAP_TIER_CONSUMER


# ---------------------------------------------------------------------------
# 6. 岳 2026-10-19: 输入侧「有没有滤波」是 WARN, 其余档仍是 INFO
# ---------------------------------------------------------------------------


def _no_capacitor(pin_name: str) -> list:
    """One IC alone on the page: its rail has no bridging capacitor at all."""
    ic = _comp(
        "U1",
        pins=[("1", pin_name, RAIL), ("2", "OUT", "SIG"), ("3", "GND", "GND")],
    )
    model = _model([ic])
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[_place("U1", 0.0, 0.0)],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net=RAIL),
            _pad("U1", "2", x=0.0, y=20.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=40.0, net="GND"),
        ],
    )
    return DecapDistance().check(_ctx(board, model))


def test_a_regulator_input_rail_with_no_capacitor_at_all_is_a_warn():
    """岳 2026-10-19「重点是输入侧是否有去耦滤波」.

    The rule's default for an empty pool is INFO because *whether a rail needs a
    capacitor* is the datasheet's question. A rail that is some **regulator's
    input** is the exception: the input capacitor is what the regulator's loop
    stands on, so "this board put nothing on it" is a layout defect the rule can
    state without a datasheet. This is the only emptiness that is raised.
    """
    (row,) = _no_capacitor("VIN")
    assert row.severity == "WARN", row.message
    assert "regulator input" in row.message
    assert row.target.component_ref == "U1"
    assert row.target.net_refs == [RAIL]


def test_a_consumer_rail_with_no_capacitor_stays_info():
    """The same emptiness on a rail the part *eats* is still a question to look up.

    ``VDD`` is the 消耗端供电脚 tier (200 mil), not the regulator-input one, and
    raising it would be this rule inventing a requirement the datasheet owns.
    """
    (row,) = _no_capacitor("VDD")
    assert row.severity == "INFO", row.message
    assert "regulator input" not in row.message


def test_a_pool_that_is_all_bulk_or_unclassified_stays_info_even_on_the_input_tier():
    """毕设FOC's ``+5V`` — four capacitors, none of them in either pool.

    ``C23`` is 22 uF (bulk), three 2.2 uF sit between the 1 uF HF ceiling and the
    10 uF bulk floor, and ``C30`` states no value. That is a statement about the
    classifier, not about the rail having no filtering, so it must not be raised
    to WARN — measured 2026-10-19 while landing the input-tier rule.
    """
    ic = _comp(
        "U1",
        pins=[("1", "VIN", RAIL), ("2", "OUT", "SIG"), ("3", "GND", "GND")],
    )
    caps = [
        _comp("C1", value="22uF", pins=[("1", "1", RAIL), ("2", "2", BRIDGE)]),
        _comp("C2", value="2.2uF", pins=[("1", "1", RAIL), ("2", "2", BRIDGE)]),
        _comp("C3", value="", pins=[("1", "1", RAIL), ("2", "2", BRIDGE)]),
    ]
    model = _model([ic, *caps])
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            _place("U1", 0.0, 0.0),
            _place("C1", 400.0, 0.0),
            _place("C2", 500.0, 0.0),
            _place("C3", 600.0, 0.0),
        ],
        pads=[
            _pad("U1", "1", x=0.0, y=0.0, net=RAIL),
            _pad("U1", "2", x=0.0, y=20.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=40.0, net="GND"),
            _pad("C1", "1", x=400.0, y=0.0, net=RAIL),
            _pad("C1", "2", x=400.0, y=20.0, net=BRIDGE),
            _pad("C2", "1", x=500.0, y=0.0, net=RAIL),
            _pad("C2", "2", x=500.0, y=20.0, net=BRIDGE),
            _pad("C3", "1", x=600.0, y=0.0, net=RAIL),
            _pad("C3", "2", x=600.0, y=20.0, net=BRIDGE),
        ],
    )
    rows = DecapDistance().check(_ctx(board, model))
    assert rows, "the (IC, net) pair still produces a row"
    assert all(row.severity == "INFO" for row in rows), [
        (row.severity, row.message) for row in rows
    ]
