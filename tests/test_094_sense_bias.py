"""094 A3b: the sense-bias closure rule, the contract's waiver, and the apply walk.

A3a built the framework (a statement the design makes, graded by who said it) and
three rules that read a *drawing*. This batch brings the one the whole channel was
built for and does the arithmetic the drawing cannot:

* ``arch-sense-bias-closure`` — a chain the contract declares a **bidirectional
  current sense** needs a bias that can hold its node. F1's numbers are the rule's
  own: ``R_th = R_up‖R_dn + Rs = 500 + 10000 = 10500Ω`` against ``R_sense = 0.1Ω``
  gives ``V_err = 1.65V × 0.1/(10500 + 0.1) ≈ 15.7µV`` where 1.65V was wanted —
  five orders of magnitude, which is what "偏置源内阻必须 ≪ 采样电阻" means. The
  ``1/10`` closure criterion is **this rule's own declaration**, written in the
  class docstring and in ``BIAS_CLOSURE_RATIO``, and the two topologies it prices
  are named there too; a topology it cannot price is UNKNOWN naming the fix;
* the contract's side: an optional ``closure: "waived"`` on a signal, which is how
  the engineer's own decision (F1's R4: "0.1Ω 直采，不加放大器") becomes an INFO
  row quoting its rationale instead of a violation the tool keeps re-deriving;
* the apply walk: ``_baseline_findings`` now carries the project's contract (094
  §二), so a write that *creates* a contract violation is graded by #55's ruling B
  — ERROR always stops the save, ``--force`` never releases it, a WARN needs the
  flag and is named in ``forcedWarns`` and in the notes.

Offline throughout: fixtures are built in memory, the real witness is the shipped
export read as a file, and the end-to-end apply scene drives the fake editor
`tests/test_057_draw_page_cli.py` already uses (imported, not copied).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.review import BUILTIN_RULES, INTENT_RULES, run_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.archclosure import (
    BIAS_CLOSURE_RATIO,
    BIAS_PHYSICS,
    MARGIN_GRADE,
    WAIVER_GRADE,
    ArchSenseBiasClosure,
)
from boardwise.rules.i18n import RULE_NAMES_ZH
from boardwise.rules.unproven import NET_MEMBERSHIP_RULES, UNPROVEN_BY_NAME

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
FOC_CONTRACT = Path("blocklib/intents/robot-ctrl-foc.intent.json")
SHELF_PATH = Path("blocklib/parts.json")
ARCH_SOURCE = Path("src/boardwise/rules/archclosure.py")
RULE_ID = "arch-sense-bias-closure"

PROV = "user_stated"


# ---------------------------------------------------------------------------
# tiny boards and shelves
# ---------------------------------------------------------------------------


def _part(
    designator: str, *, value: str = "", mpn: str = "", lcsc: str = "", pins=()
) -> Component:
    """One component; a pin is ``(number, net)`` or ``(number, name, net)``."""
    resolved = []
    for pin in pins:
        if len(pin) == 2:
            number, net = pin
            resolved.append(Pin(str(number), "", net))
        else:
            number, name, net = pin
            resolved.append(Pin(str(number), str(name), net))
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        lcsc_part=lcsc,
        pins=resolved,
    )


def _model_of(components: dict, nets: dict) -> DesignModel:
    model = DesignModel()
    model.components.update(components)
    model.nets = {name: Net(name, list(pins)) for name, pins in nets.items()}
    return model


def _ldo_entry() -> PartEntry:
    """The 3.3V rail's price: F1's `VCC` comes off a regulator on this board too."""
    return PartEntry(
        key="ic.ldo", mpn="AMS1117-3.3", lcsc="C369933", category="ic.ldo",
        facts={
            "ldo": {"fixed_output": {
                "volts": 3.3, "provenance": "issue-094 fixture, p.1",
            }},
            "supply_pins": [{"pins": ["3"], "name": "VIN",
                             "provenance": "issue-094 fixture, p.3"}],
            "required_caps": [{"pin": "2", "value": "10uF",
                               "provenance": "issue-094 fixture, p.4"}],
        },
    )


def _opamp_entry(mpn: str = "TLV9062", *, outputs=None) -> PartEntry:
    facts = {} if outputs is None else {"output_pins": list(outputs)}
    return PartEntry(
        key="ic.opamp", mpn=mpn, lcsc="C398355", category="ic.opamp", facts=facts,
    )


#: The shelf the small boards are read against: a priced LDO and two amplifiers.
#: The parts a *value* identifies (`1k`, `100mΩ`) need no entry — a resistor is a
#: resistor by its own value (`_resistor_like`), which is the reading the pull-up
#: rule already uses.
SHELF = PartLibrary(parts=[_ldo_entry(), _opamp_entry(), _opamp_entry("OPAMPX")])


def _bias_board(
    *,
    r_up: str = "1k",
    r_dn: str = "1k",
    rs: str = "10k",
    r_sense: str = "100mΩ",
    driver: Component | None = None,
    driver_net: str = "U+",
) -> DesignModel:
    """F1's live shape: a 3.3V rail, a divider, a series resistor, a 0.1Ω shunt.

    ``U+`` carries the shunt to GND, the series resistor to the divider's
    mid-point and the MCU's ADC pin — the three things F1's netlist shows. The
    defaults are the measured board's own values (R10/R16 = 1k, R17 = 10k,
    R4 = 100mΩ), so the arithmetic the rule prints is F1's arithmetic.
    """
    components = {
        "U8": _part("U8", mpn="AMS1117-3.3", pins=[("3", "+12V"), ("2", "VCC")]),
        "R10": _part("R10", value=r_up, pins=[("1", "VCC"), ("2", "VCC/2")]),
        "R16": _part("R16", value=r_dn, pins=[("2", "VCC/2"), ("1", "GND")]),
        "R17": _part("R17", value=rs, pins=[("1", "VCC/2"), ("2", "U+")]),
        "R4": _part("R4", value=r_sense, pins=[("2", "U+"), ("1", "GND")]),
        "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
    }
    nets = {
        "+12V": [("U8", "3")],
        "VCC": [("U8", "2"), ("R10", "1")],
        "VCC/2": [("R10", "2"), ("R16", "2"), ("R17", "1")],
        "GND": [("R16", "1"), ("R4", "1")],
        "U+": [("R17", "2"), ("R4", "2"), ("U1", "21")],
    }
    if driver is not None:
        components[driver.designator] = driver
        nets.setdefault(driver_net, []).append(
            (driver.designator, driver.pins[0].number)
        )
    return _model_of(components, nets)


def _unbiased_board() -> DesignModel:
    """The shipped export's shape: the shunt, the ADC pin, and nothing else."""
    return _model_of(
        {
            "R4": _part("R4", value="100mΩ", pins=[("2", "U+"), ("1", "GND")]),
            "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
        },
        {"GND": [("R4", "1")], "U+": [("R4", "2"), ("U1", "21")]},
    )


def _opamp_board(
    *, mpn: str = "TLV9062", pin_name: str = "OUTA", lcsc: str = ""
) -> DesignModel:
    """The same shunt, biased by an amplifier's output instead of by resistors.

    ``lcsc`` is how a scene that runs through the **review** (rather than through a
    hand-built shelf) makes the part recognisable: the rule's default instance loads
    the repository shelf, where this board's amplifier is `C398355`.
    """
    return _model_of(
        {
            "R4": _part("R4", value="100mΩ", pins=[("2", "U+"), ("1", "GND")]),
            "U9": _part("U9", mpn=mpn, lcsc=lcsc, pins=[("1", pin_name, "U+")]),
            "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
        },
        {"GND": [("R4", "1")], "U+": [("R4", "2"), ("U9", "1"), ("U1", "21")]},
    )


#: The repository shelf's own quad/dual single-supply amplifier, which is what a
#: scene going through `run_review` has to name for the part to be recognised.
REPO_OPAMP_LCSC = "C398355"


def _opamp_board_from_the_repo_shelf() -> DesignModel:
    """The same board, with the amplifier the **repository shelf** knows."""
    return _opamp_board(mpn="TLV9062IDR", lcsc=REPO_OPAMP_LCSC, pin_name="OUTA")


def _chain(
    net: str = "U+",
    *,
    provenance: str = PROV,
    closure: str = "",
    kind: str = "current-sense",
    polarity: str = "bidirectional",
    requires=(),
) -> di.IntentSignal:
    return di.IntentSignal(
        net=net,
        slots={"polarity": polarity} if polarity else {},
        kind=kind,
        adc_swing="0..3.3V",
        requires=list(requires),
        closure=closure,
        provenance=provenance,
    )


R4_DECISION = di.IntentDecision(
    subject="R4",
    decision="0.1Ω 直采，不加放大器",
    rationale="接受低边分流只有正半轴可测、约 7.8bit 有效位",
    stated_value="0.1Ω",
    provenance=PROV,
)


def _intent(*signals: di.IntentSignal, decisions=(), path: str = "mem://094.json"):
    return di.IntentSource(
        document=di.DesignIntent(signals=list(signals), decisions=list(decisions)),
        path=path,
    )


def _rows(model: DesignModel, intent, shelf: PartLibrary = SHELF):
    rule = ArchSenseBiasClosure(library=shelf, intent=intent)
    return rule._rows(model)


def _only(model: DesignModel, intent, shelf: PartLibrary = SHELF):
    """The one row this board and contract produce."""
    rows = _rows(model, intent, shelf)
    assert len(rows) == 1, [row[0].message for row in rows]
    return rows[0]


# ---------------------------------------------------------------------------
# the seam: where the rule sits, and what it does with no contract
# ---------------------------------------------------------------------------


def test_the_rule_is_a_builtin_a_contract_carrier_and_a_net_membership_rule():
    """Three registries, each with its own reason for naming the rule."""
    assert RULE_ID in [rule.id for rule in BUILTIN_RULES]
    assert ArchSenseBiasClosure in INTENT_RULES, (
        "its subject (a declared bidirectional current sense) only exists in a "
        "contract — spelled-out registries in test_092/test_093 keep this honest"
    )
    assert RULE_ID in NET_MEMBERSHIP_RULES, (
        "the arithmetic reads which resistors sit on the net and where their far "
        "ends go, so a welded name can mislead it (issue #19)"
    )
    assert RULE_ID in RULE_NAMES_ZH, "every built-in rule has a Chinese name"


def test_without_a_contract_the_rule_moves_nothing():
    model = _bias_board()
    assert _rows(model, None) == []
    ids = {finding.rule_id for finding in run_review(model)}
    assert RULE_ID not in ids, (
        "a reading that names no contract is byte-for-byte what it was"
    )


def test_the_subject_is_a_bidirectional_current_sense_chain():
    """Two spellings of the same subject, and two shapes that are not it."""
    model = _unbiased_board()
    for signal in (
        _chain(kind="pwm"),
        _chain(kind="current-sense", polarity="unipolar"),
        _chain(kind="reset", polarity=""),
    ):
        assert _rows(model, _intent(signal)) == [], signal
    asked = _rows(model, _intent(_chain(kind="voltage", polarity="", requires=["bias-reference"])))
    assert len(asked) == 1, "a chain that requires a bias is a subject by name"
    assert asked[0][1] == "ERROR"


# ---------------------------------------------------------------------------
# the five rows
# ---------------------------------------------------------------------------


def test_the_weak_bias_row_is_f1_arithmetic_number_by_number():
    """F1's own arithmetic, checked figure by figure rather than "mentions R_th".

    The numbers are the report's (`outputs/ctrlfoc_20261001/review-findings.md`
    §F1): 1k‖1k = 500Ω, through R17 = 10k onto R4 = 0.1Ω, so
    ``1.65V × 0.1Ω/(500Ω + 10000Ω + 0.1Ω) ≈ 15.7µV`` — five orders below the
    1.65V it wanted. Everything the row claims is one of these figures.
    """
    (outcome, severity, target) = _only(_bias_board(), _intent(_chain()))
    assert severity == "ERROR", "user_stated and contradicted by the drawing (093 §〇)"
    assert outcome.state == "VIOLATION"
    message = outcome.message
    assert "R_th = 10500Ω" in message
    assert "R_sense = 0.1Ω" in message
    assert "R_th = (R_up‖R_dn) + Rs = 500Ω + 10000Ω = 10500Ω" in message
    assert "1.65V × 0.1Ω/(10500Ω + 0.1Ω) ≈ 15.7µV" in message
    assert "差约 5 个数量级" in message
    assert "而想要的是 1.65V" in message
    assert "形同虚设" in message
    assert "requirements.signals[net=U+].kind = 'current-sense'" in message
    assert "分级 ERROR（093 §〇）" in message and "user_stated" in message
    # The evidence carries the same reading, so a reader can check it part by part.
    evidence = "\n".join(outcome.evidence)
    assert "采样电阻 R4 = 0.1Ω @ U+ → GND" in evidence
    assert "分压 R10（1kΩ）@'VCC' / R16（1kΩ）@GND" in evidence
    assert "R_th = 500 + 10000 = 10500Ω；V_bias = 1.65V" in evidence
    assert "R_sense/10 = 0.01Ω" in evidence
    assert target is not None and target.net_refs == ["U+"], (
        "the row is about a net, so the mark lands on the chain"
    )


def test_an_ai_drafted_chain_gets_a_warn_and_the_052_sentence():
    """052 §4: a guess may not be the yardstick a board is judged against."""
    (outcome, severity, _target) = _only(
        _bias_board(), _intent(_chain(provenance="ai_asserted"))
    )
    assert severity == "WARN"
    assert "分级 WARN（093 §〇）" in outcome.message
    assert "确认前不要照改" in outcome.message


def test_no_bias_network_at_all_is_the_shipped_exports_shape():
    """F1 before the engineer added anything: nothing reaches a bias, so ERROR."""
    (outcome, severity, _target) = _only(_unbiased_board(), _intent(_chain()))
    assert severity == "ERROR" and outcome.state == "VIOLATION"
    assert "**没有任何偏置网络**" in outcome.message
    assert "网成员 R4.2, U1.21" in outcome.message
    assert "到地的电阻只有 R4（0.1Ω，采样电阻）" in outcome.message
    assert BIAS_PHYSICS in outcome.message
    assert 'closure 写 "waived"' in outcome.message, "the row names the way out"
    (draft, draft_severity, _t) = _only(
        _unbiased_board(), _intent(_chain(provenance="ai_asserted"))
    )
    assert draft_severity == "WARN" and draft.state == "VIOLATION"


def test_a_waiver_the_engineer_stated_is_an_info_row_quoting_the_decision():
    """F1's real outcome was a decision (R4), so the rule reports it as one."""
    (outcome, severity, _target) = _only(
        _unbiased_board(),
        _intent(_chain(closure="waived"), decisions=[R4_DECISION]),
    )
    assert severity == WAIVER_GRADE == "INFO"
    assert outcome.state == "OK"
    assert "requirements.signals[net=U+].closure = 'waived'" in outcome.message
    assert "decisions[subject='R4']" in outcome.message
    assert "0.1Ω 直采，不加放大器" in outcome.message
    assert "接受低边分流只有正半轴可测、约 7.8bit 有效位" in outcome.message
    assert "这是工程师签过字的决定，不是漏掉的检查" in outcome.message
    assert "仍然只能测正半轴" in outcome.message, (
        "the waiver withdraws the check, not the consequence"
    )


def test_a_waiver_nobody_backed_says_so_rather_than_looking_signed():
    (outcome, severity, _target) = _only(
        _unbiased_board(), _intent(_chain(closure="waived"))
    )
    assert severity == "INFO"
    assert "合同 decisions[] 里没有为这条链背书的条目" in outcome.message


def test_a_draft_waiver_is_a_warn_because_a_draft_cannot_exempt_itself():
    (outcome, severity, _target) = _only(
        _unbiased_board(),
        _intent(_chain(closure="waived", provenance="ai_asserted"),
                decisions=[R4_DECISION]),
    )
    assert severity == "WARN" and outcome.state == "VIOLATION"
    assert "草稿不能自己豁免自己（052 §4" in outcome.message
    assert "请工程师确认这条豁免" in outcome.message
    assert "不是工程师本人" in outcome.message


def test_the_marginal_ratio_is_a_warn_carrying_both_numbers():
    """``R_sense/10 < R_th < R_sense`` — inside the decade, so a look rather than a verdict."""
    model = _bias_board(r_up="10Ω", r_dn="10Ω", rs="100mΩ", r_sense="10Ω")
    (outcome, severity, _target) = _only(model, _intent(_chain()))
    assert severity == MARGIN_GRADE == "WARN" and outcome.state == "VIOLATION"
    assert "比值存疑" in outcome.message
    assert "R_th = 5.1Ω" in outcome.message
    assert "R_sense/10（1Ω）与 R_sense（10Ω）之间" in outcome.message
    assert "R_th = (R_up‖R_dn) + Rs = 5Ω + 0.1Ω = 5.1Ω" in outcome.message
    assert "1.65V × 10Ω/(5.1Ω + 10Ω)" in outcome.message


def test_a_closed_bias_is_an_info_measurement_with_its_numbers():
    """092's discipline: "checked and fine" is filed, so it cannot read as "never looked"."""
    model = _bias_board(r_up="1Ω", r_dn="1Ω", rs="100mΩ", r_sense="10Ω")
    (outcome, severity, _target) = _only(model, _intent(_chain()))
    assert severity == "INFO" and outcome.state == "OK"
    assert "偏置**闭合成立**" in outcome.message
    assert "R_th = 0.6Ω ≤ R_sense/10 = 1Ω" in outcome.message
    assert "1.65V × 10Ω/(0.6Ω + 10Ω)" in outcome.message
    assert "测量行：查过且闭合，不是一个沉默" in outcome.message


def test_the_two_boundaries_of_the_criterion_are_where_it_says_they_are():
    """``≤ R_sense/10`` closed, ``= R_sense`` still weak — the ``≤``/``<`` matter."""
    closed = _bias_board(r_up="1Ω", r_dn="1Ω", rs="500mΩ", r_sense="10Ω")
    assert _only(closed, _intent(_chain()))[1] == "INFO"
    just_over = _bias_board(r_up="1Ω", r_dn="1Ω", rs="600mΩ", r_sense="10Ω")
    assert _only(just_over, _intent(_chain()))[1] == "WARN"
    at_the_line = _bias_board(r_up="1Ω", r_dn="1Ω", rs="9500mΩ", r_sense="10Ω")
    (outcome, severity, _t) = _only(at_the_line, _intent(_chain()))
    assert severity == "ERROR", "R_th == R_sense is not a closure, it is a dead heat"
    assert "R_th = 10Ω **大于等于**采样电阻 R_sense = 10Ω" in outcome.message


def test_a_series_resistor_straight_onto_a_rail_is_priced_by_the_same_formula():
    """A 10k pull onto a rail is a bias too — and the rail's own impedance is zero."""
    model = _model_of(
        {
            "R4": _part("R4", value="100mΩ", pins=[("2", "U+"), ("1", "GND")]),
            "R20": _part("R20", value="10k", pins=[("1", "3V3"), ("2", "U+")]),
            "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
        },
        {"GND": [("R4", "1")], "U+": [("R4", "2"), ("R20", "2"), ("U1", "21")],
         "3V3": [("R20", "1")]},
    )
    (outcome, severity, _target) = _only(model, _intent(_chain()))
    assert severity == "ERROR"
    assert "Rs + 0Ω（串阻直接接轨，轨内阻记 0）= 10000Ω + 0Ω" in outcome.message
    assert "R_th = 10000Ω" in outcome.message
    assert "3.3V × 0.1Ω/(10000Ω + 0.1Ω)" in outcome.message
    assert "V_bias = 3.3V（net name '3V3'）" in "\n".join(outcome.evidence)


# ---------------------------------------------------------------------------
# the shapes the rule closes, and the ones it refuses to guess
# ---------------------------------------------------------------------------


def test_an_opamp_output_on_the_net_closes_the_chain():
    """Output impedance is ohms, so the Thévenin arithmetic is meaningless there."""
    (outcome, severity, _target) = _only(_opamp_board(), _intent(_chain()))
    assert severity == "INFO" and outcome.state == "OK"
    assert "运放 U9 的输出脚（OUTA）直连" in outcome.message
    assert "输出阻抗在 Ω 级" in outcome.message
    assert outcome.evidence[-1].endswith("引脚名 'OUTA'）")


def test_the_shelf_can_name_the_output_pin_when_the_symbol_does_not():
    """Explicit data wins: a pin named `1` is the output when the entry says so."""
    from boardwise.rules.archclosure import ArchSenseBiasClosure as Rule

    shelf = PartLibrary(parts=[_opamp_entry("OPAMPX", outputs=["1"])])
    rule = Rule(library=shelf, intent=_intent(_chain()))
    [(outcome, severity, _target)] = rule._rows(_opamp_board(mpn="OPAMPX", pin_name="1"))
    assert severity == "INFO" and outcome.state == "OK"
    assert "运放 U9 的输出脚（1）直连" in outcome.message
    assert outcome.evidence[-1].endswith("facts.output_pins 点名了引脚 1）")


def test_an_opamp_whose_output_pin_is_unreadable_is_unknown_naming_the_fact():
    """An input pin and an output pin are opposite conclusions — so: ask."""
    from boardwise.rules.archclosure import ArchSenseBiasClosure as Rule

    board = _opamp_board(mpn="TLM9062", pin_name="1")
    shelf = PartLibrary(parts=[_opamp_entry("TLM9062")])
    rule = Rule(library=shelf, intent=_intent(_chain()))
    [(outcome, severity, _target)] = rule._rows(board)
    assert outcome.state == "UNKNOWN" and severity == "INFO"
    assert UNPROVEN_BY_NAME not in (outcome.missing_fact or "")
    assert "fields.facts.output_pins" in outcome.missing_fact
    assert "哪一脚是输出读不出来" in outcome.message


def test_a_topology_the_rule_cannot_price_is_unknown_and_names_the_fix():
    """A resistor to a mid-net that is not a divider: do not guess what it is."""
    model = _model_of(
        {
            "R4": _part("R4", value="100mΩ", pins=[("2", "U+"), ("1", "GND")]),
            "R17": _part("R17", value="10k", pins=[("1", "MID"), ("2", "U+")]),
            "R21": _part("R21", value="1k", pins=[("1", "MID"), ("2", "GND")]),
            "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
        },
        {"GND": [("R4", "1"), ("R21", "2")],
         "U+": [("R4", "2"), ("R17", "2"), ("U1", "21")],
         "MID": [("R17", "1"), ("R21", "1")]},
    )
    (outcome, severity, _target) = _only(model, _intent(_chain()))
    assert outcome.state == "UNKNOWN" and severity == "INFO"
    assert "拓扑对不上，本规则不猜" in outcome.message
    assert "R17（10kΩ → 'MID'）" in outcome.message
    assert "requirements.signals[net=U+].closure 写 'waived'" in outcome.missing_fact


def test_a_chain_with_no_grounded_resistor_has_no_ratio_to_judge():
    model = _model_of(
        {"U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")])},
        {"U+": [("U1", "21")]},
    )
    (outcome, severity, _target) = _only(model, _intent(_chain()))
    assert outcome.state == "UNKNOWN" and severity == "INFO"
    assert "采样电阻 R_sense 读不出来" in outcome.message
    assert "U+ 的采样电阻" in outcome.missing_fact


def test_a_welded_net_name_refuses_before_the_rule_judges():
    """Issue #19: neither the parts nor the rails of a welded name are this board's."""
    model = _bias_board()
    model.unproven_nets = {"U+": ("page-a", "page-b")}
    (outcome, severity, _target) = _only(model, _intent(_chain(closure="waived")))
    assert outcome.state == "UNKNOWN" and severity == "INFO"
    assert UNPROVEN_BY_NAME in outcome.missing_fact
    assert "whether the bias on chain 'U+' closes" in outcome.message


# ---------------------------------------------------------------------------
# the criterion is the rule's own, and it says so
# ---------------------------------------------------------------------------


def test_the_tenth_is_declared_rather_than_hidden():
    """A number a reader can disagree with, in the docstring and in the constant."""
    source = ARCH_SOURCE.read_text(encoding="utf-8")
    doc = " ".join((ArchSenseBiasClosure.__doc__ or "").split())
    assert BIAS_CLOSURE_RATIO == 0.1
    assert "BIAS_CLOSURE_RATIO" in source
    assert "1/10`` is this rule's own declared criterion, not a standard" in doc
    assert "``R_th ≤ R_sense/10``" in doc
    # The topology it prices is defined where the number is, so "which shapes
    # count" is not something a reader has to reverse-engineer from the code.
    assert "``R_th = R_up‖R_dn + Rs``" in doc
    assert "``V_err = V_bias × R_sense/(R_th + R_sense)``" in doc
    assert "series resistor straight onto a priced rail" in doc
    assert "op-amp" in doc
    assert "UNKNOWN" in doc and "topology" in doc
    # ... and the module table says how a waiver is graded, next to the four tiers
    # it sits beside (a user_stated *waiver* is INFO although a violation is ERROR).
    module = " ".join(source.split("class ", 1)[0].split())
    assert "a `user_stated` **waiver**" in module


# ---------------------------------------------------------------------------
# the contract's side: an optional waiver
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty `BOARDWISE_HOME`, so the default landing spot is a temp directory.

    Same convention `tests/test_090_design_intent.py` uses: the user-level spot
    (`<home>/design-intent/<projectUuid>.json`) is where the tool looks, and a test
    never touches the real home.
    """
    root = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(root))
    return root


def _contract_payload(**signal) -> dict:
    body = {"net": "U+", "kind": "current-sense", "polarity": "bidirectional",
            "provenance": PROV}
    body.update(signal)
    return {"intentVersion": 1, "requirements": {"signals": [body]}}


def test_the_closure_key_is_optional_and_not_written_when_it_says_nothing():
    """Rule 1 of this contract: an optional field is absent, never empty."""
    text = di.render_json(di.DesignIntent(signals=[_chain()]))
    assert "closure" not in text
    parsed = di.parse_json(text)
    assert parsed.signals[0].closure == ""
    assert parsed.signals[0].waived is False


def test_a_waiver_round_trips_through_the_canonical_form():
    text = di.render_json(di.DesignIntent(signals=[_chain(closure="waived")]))
    assert '"closure": "waived"' in text
    back = di.parse_json(text)
    assert back.signals[0].waived is True
    assert di.render_json(back) == text, "one shape in, one shape out"


def test_an_unknown_closure_token_is_refused_with_its_path():
    """A token no consumer grades would be a declaration nobody reads."""
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.DesignIntent.from_dict(_contract_payload(closure="closed"))
    message = str(excinfo.value)
    assert "requirements.signals[0].closure" in message
    assert "'closed'" in message and "waived" in message


def test_regeneration_keeps_a_waiver_byte_for_byte():
    """090 §二's discipline applied to this batch's key: an answer is never lost."""
    from boardwise.core.architecture import generate_architecture
    from boardwise.core.parts import load_parts

    slots = generate_architecture(
        build_project_model(ROBOT), library=load_parts(SHELF_PATH)
    ).section["slots"]
    document = di.parse_json(FOC_CONTRACT.read_text(encoding="utf-8"))
    merged, _facts = di.merge(document, slots)
    text = di.render_json(merged)
    assert text.count('"closure": "waived"') == 2, "both phase chains keep theirs"
    kept = {signal.net: signal for signal in di.parse_json(text).signals}
    assert kept["U+"].waived is True and kept["W+"].waived is True
    assert di.render_json(document) == FOC_CONTRACT.read_text(encoding="utf-8"), (
        "and the merge never mutates the document it was handed"
    )


# ---------------------------------------------------------------------------
# the real case: the ctrl FOC export
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot():
    return build_project_model(ROBOT)


@pytest.fixture(scope="module")
def shelf():
    from boardwise.core.parts import load_parts

    return load_parts(SHELF_PATH)


def test_the_shipped_contract_is_canonical_and_waives_both_phase_chains():
    """094 §一.2: U+/W+ carry `closure: "waived"` — the R4 decision, user_stated."""
    text = FOC_CONTRACT.read_text(encoding="utf-8")
    document = di.parse_json(text)
    assert di.render_json(document) == text, "the shipped file is canonical"
    assert [signal.net for signal in document.signals] == ["U+", "W+"]
    assert [signal.closure for signal in document.signals] == ["waived", "waived"]
    assert [signal.provenance for signal in document.signals] == [PROV, PROV]


def test_the_export_and_the_shipped_contract_file_two_exemptions(robot, shelf):
    """The witness the batch asks for: INFO rows, quoting R4's own rationale."""
    rows = _rows(robot, di.IntentSource.load(FOC_CONTRACT), shelf)
    assert [(outcome.subject, severity) for outcome, severity, _t in rows] == [
        ("U+", "INFO"), ("W+", "INFO"),
    ]
    u_plus, w_plus = (row[0].message for row in rows)
    assert "**豁免（waived）成立**" in u_plus
    assert "0.1Ω 直采，不加放大器" in u_plus
    assert "接受低边分流只有正半轴可测、约 7.8bit 有效位" in u_plus
    assert "网成员 U1.21, DRV1.6, R4.2" in u_plus, "the citation names this chain's net"
    assert "decisions[] 里没有为这条链背书的条目" in w_plus, (
        "W+ has no decision of its own and the row says so instead of borrowing R4's"
    )


def test_removing_the_waiver_reports_the_missing_bias_as_an_error(robot, shelf):
    """The same board, the same rule, the opposite row: F1's defect, machine-read."""
    variant = di.parse_json(FOC_CONTRACT.read_text(encoding="utf-8"))
    for signal in variant.signals:
        signal.closure = ""
    rows = _rows(
        robot,
        di.IntentSource(document=variant, path="mem://094-variant.json"),
        shelf,
    )
    assert [(outcome.subject, severity) for outcome, severity, _t in rows] == [
        ("U+", "ERROR"), ("W+", "ERROR"),
    ]
    for outcome, _severity, target in rows:
        assert "**没有任何偏置网络**" in outcome.message
        assert outcome.state == "VIOLATION"
        assert target is not None and target.net_refs == [outcome.subject]


def test_the_review_of_this_board_reports_the_exemptions_and_nothing_else(robot):
    """`run_review` end to end: with the contract, two INFO **findings**; without, none."""
    with_contract = [
        finding for finding in run_review(robot, intent=di.IntentSource.load(FOC_CONTRACT))
        if finding.rule_id == RULE_ID
    ]
    assert [(finding.severity, finding.target.net_refs[0]) for finding in with_contract
            if finding.target] == [("INFO", "U+"), ("INFO", "W+")]
    without = [
        finding for finding in run_review(robot)
        if finding.rule_id == RULE_ID
    ]
    assert without == [], "no contract, no chain declared, no row"


# ---------------------------------------------------------------------------
# the apply walk reads the contract (094 §二)
# ---------------------------------------------------------------------------


def test_the_apply_walk_carries_the_projects_contract(robot):
    """`_baseline_findings(model, intent=…)` — the seam #55's gate reads."""
    source = di.IntentSource.load(FOC_CONTRACT)
    with_contract = {item.split("|", 1)[0] for item in cli._baseline_findings(
        robot, intent=source
    )}
    without = {item.split("|", 1)[0] for item in cli._baseline_findings(robot)}
    assert RULE_ID in with_contract
    assert RULE_ID not in without
    assert cli._baseline_findings(robot, intent=None) == cli._baseline_findings(robot), (
        "no contract is the reading it always was, byte for byte"
    )
    signatures = cli._baseline_findings(robot, intent=source)
    assert f"{RULE_ID}|INFO|||U+" in signatures, (
        "the row is about a net, so the signature carries the net and no designator"
    )


def test_the_contract_is_resolved_from_the_projects_own_landing_spot(tmp_path, home):
    """A2b's path, reused: `--intent PATH`, else the project's default file."""
    import argparse

    args = argparse.Namespace()
    notes: list[str] = []
    assert cli._intent_source_for_apply(args, "", notes) is None, (
        "no project and no file: there is no default spot to look in, and a guessed "
        "name would be somebody else's contract"
    )
    path = di.default_contract_path("proj-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FOC_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    source = cli._intent_source_for_apply(args, "proj-1", notes)
    assert source is not None
    assert source.path == str(path)
    assert source.document.signals[0].waived is True
    explicit = argparse.Namespace(intent=str(tmp_path / "nope.json"))
    assert cli._intent_source_for_apply(explicit, "proj-1", notes) is None
    assert any("不存在" in note for note in notes), (
        "a contract that was named and is missing is a note, and the run goes on"
    )


# ---------------------------------------------------------------------------
# the real linkage: a write that breaks the contract is not saved
# ---------------------------------------------------------------------------


def _page_cli():
    """`test_057`'s fake editor and its plan/apply plumbing — imported, not copied."""
    tests_dir = str(Path(__file__).resolve().parent)
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import test_057_draw_page_cli as module

    return module


def _land_the_contract(document: di.DesignIntent) -> Path:
    """Write a contract where the tool looks for it (`proj-1` is the fake's project)."""
    path = di.default_contract_path("proj-1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(di.render_json(document), encoding="utf-8")
    return path


def _plan_and_apply(monkeypatch, tmp_path, *, models, extra=()):
    """One `draw plan` + `draw apply` through the fake page, with these model reads.

    ``models`` is what the three parses answer in order: the plan's own reading,
    the apply run's reading before the write, and the one after it. ``_baseline_findings``
    is **not** stubbed — that is the point: the run's real walk, with the contract
    resolved from `proj-1`'s landing spot, is what the gate grades.
    """
    from boardwise.core.changeplan import ChangePlan

    page_cli = _page_cli()
    editor = page_cli._PageEditor()
    circuit, presentation = page_cli.write_specs(tmp_path)
    page_cli._stub_editor(monkeypatch, editor)
    reads = list(models)

    async def _export(call, notes):
        return b"export-bytes"

    def _parse(blob, notes):
        return reads.pop(0) if reads else models[-1]

    monkeypatch.setattr(cli, "_live_project_export", _export)
    monkeypatch.setattr(cli, "_model_from_export", _parse)
    out = tmp_path / "plan.json"
    plan_code = cli.main(page_cli._plan_args(
        circuit, presentation, "--page", "page-1", "--out", str(out),
    ))
    assert plan_code == 0, "the plan itself is not what this scene is testing"
    plan = ChangePlan.load(out)
    editor.netlists = [{"components": {}}, page_cli._netlist_for(plan)]
    code, report = page_cli._apply(
        editor, out, circuit, presentation, tmp_path, *extra
    )
    return code, report, editor


def test_a_write_that_breaks_the_contracts_closure_is_not_saved(
    monkeypatch, tmp_path, home, capsys
):
    """The linkage 093 §八.5 left open: the contract reaches the gate, and an ERROR stops it.

    The plan is built against a board whose chain is **closed** (an op-amp's
    output drives it) and the write lands on a board where that amplifier is gone
    — so the contract's own `user_stated` statement is violated *by this write*,
    which is exactly what #55's gate grades. ``sch.doc.save`` must not be called.
    """
    _land_the_contract(di.DesignIntent(signals=[_chain()]))
    code, report, editor = _plan_and_apply(
        monkeypatch, tmp_path,
        models=[_opamp_board_from_the_repo_shelf(),
                _opamp_board_from_the_repo_shelf(), _unbiased_board()],
    )
    assert code == 2, report["notes"]
    assert report["reason"] == "new_findings"
    assert f"{RULE_ID}|ERROR|||U+" in report["findings"]["new"]
    assert report["findings"]["newBySeverity"]["ERROR"] == [f"{RULE_ID}|ERROR|||U+"]
    assert "sch.doc.save" not in [action for action, _params in editor.writes]
    assert RULE_ID in " ".join(report["notes"]), (
        "the blocking row is named in the notes, not only counted"
    )


def test_force_never_releases_the_contracts_error(monkeypatch, tmp_path, home, capsys):
    """#55 ruling B: no flag makes a contradiction with the engineer's word right."""
    _land_the_contract(di.DesignIntent(signals=[_chain()]))
    code, report, editor = _plan_and_apply(
        monkeypatch, tmp_path,
        models=[_opamp_board_from_the_repo_shelf(),
                _opamp_board_from_the_repo_shelf(), _unbiased_board()],
        extra=("--force",),
    )
    assert code == 2, report["notes"]
    assert report["findings"]["forcedWarns"] == []
    assert "sch.doc.save" not in [action for action, _params in editor.writes]


def test_a_draft_contracts_warn_needs_force_and_is_named_when_released(
    monkeypatch, tmp_path, home, capsys
):
    """The middle tier on the same scene: blocked without `--force`, named with it."""
    _land_the_contract(di.DesignIntent(signals=[_chain(provenance="ai_asserted")]))
    signature = f"{RULE_ID}|WARN|||U+"
    blocked, report, editor = _plan_and_apply(
        monkeypatch, tmp_path,
        models=[_opamp_board_from_the_repo_shelf(),
                _opamp_board_from_the_repo_shelf(), _unbiased_board()],
    )
    assert blocked == 2
    assert report["findings"]["new"] == [signature]
    assert "sch.doc.save" not in [action for action, _params in editor.writes]

    second = tmp_path / "second"
    second.mkdir()
    released, report, editor = _plan_and_apply(
        monkeypatch, second,
        models=[_opamp_board_from_the_repo_shelf(),
                _opamp_board_from_the_repo_shelf(), _unbiased_board()],
        extra=("--force",),
    )
    assert released == 0, report["notes"]
    assert report["findings"]["forcedWarns"] == [signature], (
        "the released WARN is named in the report, never dropped silently"
    )
    assert "sch.doc.save" in [action for action, _params in editor.writes]
    assert any("--force" in note and "forcedWarns" in note for note in report["notes"])
