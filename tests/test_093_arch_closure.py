"""093 A3a: the architecture self-consistency framework and three closure rules.

Three batches built the intent channel without letting it move a grade (090 A1
wrote the contract, 091 A2a read a repair direction out of it, 092 A2b drove two
rating rules with it). This is the batch where **intent reaches the grading**,
and the rules it brings are all one shape: a statement the design makes that the
drawing can contradict.

* ``arch-rail-voltage-clash`` — the contract's rail voltage against the drawing's
  own reading of the same net. The grade is the statement's own provenance
  (:data:`INTENT_GRADES`): a `user_stated` requirement contradicted by the board
  is an **ERROR**, an `ai_asserted` draft is a WARN (052 §4), and a rail nobody
  declares or nobody prices is not looked at at all;
* ``arch-opendrain-pullup`` — the shelf's `pull_required` records marked
  `open_drain`: F2's nFAULT, reproduced here on the real export;
* ``arch-nrst-closure`` — a controller's reset pin with nothing else on its net:
  F3's shape, reproduced on the same export.

Everything offline: fixtures are read as files, no bridge, no network.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from boardwise.core import designintent as di
from boardwise.core.circuitspec import (
    PROVENANCE_AI,
    PROVENANCE_USER_STATED,
    PROVENANCE_VERIFIED,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import (
    CATEGORY_VOCABULARY,
    PartEntry,
    PartError,
    PartLibrary,
    entry_from_json,
    load_parts,
)
from boardwise.engines.review import BUILTIN_RULES, INTENT_RULES, _rules_for, run_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.archclosure import (
    INTENT_GRADES,
    MEASUREMENT_GRADE,
    STRUCTURAL_GRADE,
    ArchRailVoltageClash,
    ArchSenseBiasClosure,
    NrstClosure,
    OpenDrainPullup,
    _is_reset_name,
    intent_grade,
)
from boardwise.rules.unproven import NET_MEMBERSHIP_RULES, UNPROVEN_BY_NAME

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SHELF = Path("blocklib/parts.json")
FOC_CONTRACT = Path("blocklib/intents/robot-ctrl-foc.intent.json")
ARCH_SOURCE = Path("src/boardwise/rules/archclosure.py")
CLI_SOURCE = Path("src/boardwise/cli.py")
PAGE_A = "aaaa1111aaaa1111"
PAGE_B = "bbbb2222bbbb2222"

#: The DRV8313's own net names on the ctrl FOC export, as F2/F3 found them.
FOC_FAULT_NET = "NFAULT"
FOC_RESET_NET = "NRST"


# ---------------------------------------------------------------------------
# tiny boards
# ---------------------------------------------------------------------------


def _part(designator: str, *, value: str = "", mpn: str = "", pins=()) -> Component:
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
        pins=resolved,
    )


def _model_of(components: dict, nets: dict) -> DesignModel:
    model = DesignModel()
    model.components.update(components)
    model.nets = {name: Net(name, list(pins)) for name, pins in nets.items()}
    return model


def _rail(net: str, **slots: str) -> di.IntentRail:
    return di.IntentRail(net=net, slots=dict(slots))


def _intent(*rails: di.IntentRail, path: str = "mem://contract.json") -> di.IntentSource:
    return di.IntentSource(document=di.DesignIntent(rails=list(rails)), path=path)


def _decision(subject: str, decision: str, *, provenance: str = PROVENANCE_USER_STATED):
    return di.IntentDecision(subject=subject, decision=decision, provenance=provenance)


def _contract_with(*decisions: di.IntentDecision) -> di.IntentSource:
    return di.IntentSource(
        document=di.DesignIntent(decisions=list(decisions)),
        path="mem://decisions.json",
    )


#: A shelf part that declares an **open-drain** pin needing an external pull-up
#: (the DRV8313 nFAULT shape, as a fixture).
def _open_drain_entry(
    *, mpn: str = "DRVX", pin: str = "18", to: str = "VCC", expected: str = "10k"
) -> PartEntry:
    return PartEntry(
        key="ic.opendrain", mpn=mpn, lcsc="C1", category="ic.motor-driver",
        facts={
            "pull_required": [{
                "pin": pin, "to": to, "expected_value": expected, "open_drain": True,
                "provenance": "issue-093 fixture datasheet, p.3 pin table "
                              "(open-drain output requires an external pullup), "
                              "http://example.com/ds.pdf",
            }],
        },
    )


def _fault_board(pins=(("18", "FAULT#", FOC_FAULT_NET),), *, components=None, nets=None) -> DesignModel:
    """One open-drain part on a net the MCU reads — F2's shape, as a fixture.

    ``components``/``nets`` are *additions*: a net given here has the members
    appended to the base netlist, which is what keeps a fixture one sentence
    ("a 10k from NFAULT to 3V3") instead of a restated netlist.
    """
    board = {
        "DRV1": _part("DRV1", mpn="DRVX", pins=pins),
        "U1": _part("U1", mpn="MCUX", pins=[("34", "PB12", FOC_FAULT_NET)]),
    }
    nets_ = {FOC_FAULT_NET: [("DRV1", "18"), ("U1", "34")]}
    board.update(components or {})
    for name, members in (nets or {}).items():
        nets_.setdefault(name, [])
        nets_[name] = [*nets_[name], *members]
    return _model_of(board, nets_)


def _opendrain_rule(shelf: PartLibrary | None = None, intent=None) -> OpenDrainPullup:
    return OpenDrainPullup(
        library=shelf if shelf is not None else PartLibrary(parts=[_open_drain_entry()]),
        intent=intent,
    )


#: A controller by the architecture walk's own evidence (four `P<port><n>` pins),
#: with the STM32G4 spelling of the reset pin (F3's `U1.7`).
def _mcu_part(designator: str = "U1", reset_net: str | None = FOC_RESET_NET) -> Component:
    return _part(
        designator,
        mpn="STM32X",
        pins=[
            ("1", "VBAT", "VCC"),
            ("7", "PG10-NRST", reset_net),
            ("12", "PA0", None),
            ("13", "PA1", None),
            ("14", "PA2", None),
            ("15", "PA3", None),
        ],
    )


def _mcu_board(reset_net: str | None = FOC_RESET_NET, *, components=None, nets=None) -> DesignModel:
    """One controller with a reset pin — F3's shape, as a fixture (net additions merge)."""
    board = {"U1": _mcu_part(reset_net=reset_net)}
    nets_: dict = {"VCC": [("U1", "1")]}
    if reset_net:
        nets_[reset_net] = [("U1", "7")]
    board.update(components or {})
    for name, members in (nets or {}).items():
        nets_.setdefault(name, [])
        nets_[name] = [*nets_[name], *members]
    return _model_of(board, nets_)


def _rows(rule, model) -> list[tuple[str, str, str]]:
    """``(severity, state, message)`` per row, findings and outcomes paired.

    One reading, two outputs — a rule whose ``check`` and whose ``outcomes``
    disagree about how many rows it filed would be two judgements (the 092
    discipline).
    """
    outcomes = rule.outcomes(model)
    findings = rule.check(model)
    assert len(outcomes) == len(findings), (outcomes, findings)
    return [
        (finding.severity, outcome.state, finding.message)
        for outcome, finding in zip(outcomes, findings)
    ]


# ---------------------------------------------------------------------------
# the framework: who said it decides how loud the contradiction is
# ---------------------------------------------------------------------------


def test_the_grading_table_is_the_batch_contract_in_one_place():
    """093 §〇 as data: `user_stated` is the only ERROR, the weaker tiers are WARN.

    The table is read through :func:`intent_grade` by every consumer, so the
    vocabulary and the grade cannot drift. `verified_recipe` is the tier the
    batch's own table does not name — it is *not* the engineer's own statement,
    so it grades as WARN, and its sentence says which tier spoke so a reader
    never confuses it with a draft.
    """
    assert INTENT_GRADES == {
        PROVENANCE_USER_STATED: "ERROR",
        PROVENANCE_VERIFIED: "WARN",
        PROVENANCE_AI: "WARN",
    }
    stated = intent_grade(di.IntentRail(net="+12V", provenance=PROVENANCE_USER_STATED))
    assert stated[0] == "ERROR" and "user_stated" in stated[1]
    for tier in (PROVENANCE_VERIFIED, PROVENANCE_AI):
        severity, why = intent_grade(di.IntentRail(net="+12V", provenance=tier))
        assert severity == "WARN", tier
        assert tier in why, why
    # An entry with no provenance at all is the contract's own default (a
    # draft), and one carrying a token this build does not know is WARN too:
    # ERROR needs a statement this build can name.
    assert intent_grade(di.IntentRail(net="+12V"))[0] == "WARN"
    assert intent_grade(di.IntentRail(net="+12V", provenance="magic"))[0] == "WARN"
    assert "magic" in intent_grade(di.IntentRail(net="+12V", provenance="magic"))[1]


def test_a_structural_violation_is_a_warn_and_a_closure_is_a_measurement():
    """The table's fourth row: no contract needed, WARN when violated.

    And a satisfied structural closure is filed as an **INFO measurement** — the
    092 discipline: silence about a closed structure reads exactly like a rule
    that never looked. A structural rule's message may never carry an ERROR: the
    ERROR tier belongs to a stated requirement, and no structural rule has one.
    """
    assert STRUCTURAL_GRADE == "WARN" and MEASUREMENT_GRADE == "INFO"
    rule = _opendrain_rule()
    [(severity, state, _message)] = _rows(rule, _fault_board())
    assert (severity, state) == (STRUCTURAL_GRADE, "VIOLATION")
    assert severity != "ERROR", "no structural finding may grade as an ERROR"
    closed = _fault_board(
        components={"R1": _part("R1", value="10k",
                                pins=[("1", FOC_FAULT_NET), ("2", "3V3")])},
        nets={FOC_FAULT_NET: [("R1", "1")], "3V3": [("R1", "2")]},
    )
    [(severity, state, _message)] = _rows(rule, closed)
    assert (severity, state) == (MEASUREMENT_GRADE, "OK")


def test_the_arch_rules_read_core_only_and_never_a_disk():
    """006c's layer table: ``rules`` may import ``core`` (and its own layer).

    The contract arrives as an :class:`~boardwise.core.designintent.IntentSource`
    handed in at construction; a rule that opened the file itself would be
    reading an answer nobody chose for this reading.
    """
    import boardwise.rules.archclosure as archclosure

    source = ARCH_SOURCE.read_text(encoding="utf-8")
    layers: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.level:
            head = (node.module or "").split(".")[0]
            layers.add(head if node.level >= 2 else "(same layer)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("boardwise."):
                    layers.add(alias.name.split(".")[1])
    assert layers <= {"core", "(same layer)"}, layers
    import inspect

    for rule in (
        archclosure.ArchRailVoltageClash,
        archclosure.OpenDrainPullup,
        archclosure.NrstClosure,
    ):
        body = inspect.getsource(rule)
        assert "read_text" not in body and "open(" not in body


# ---------------------------------------------------------------------------
# R1: the contract's rail voltage against the drawing's own reading
# ---------------------------------------------------------------------------


def _rail_rule(intent: di.IntentSource | None, net: str = "+12V") -> ArchRailVoltageClash:
    return ArchRailVoltageClash(intent=intent)


def _rail_board(net: str = "+12V") -> DesignModel:
    """One capacitor on a rail the **name** prices (`+12V` says 12 V)."""
    return _model_of(
        {"C1": _part("C1", value="100nF", mpn="CAP1",
                     pins=[("1", net), ("2", "GND")])},
        {net: [("C1", "1")], "GND": [("C1", "2")]},
    )


def _rail_of(provenance: str, *, declared: str = "24V", net: str = "+12V"):
    return _intent(di.IntentRail(net=net, slots={"targetVoltage": declared},
                                 provenance=provenance))


def test_a_clash_with_a_user_stated_rail_is_an_error_that_names_both_sources():
    """The engineer said 24 V, the drawing says 12 V — and the tool picks neither.

    091 A2a's refusal, one level up: a rule that saw two disagreeing documents
    and "fixed" one of them would be inventing a requirement. Both raw fields,
    both values and both sources travel in the message, so the person who has to
    decide can see exactly what the tool saw.
    """
    rule = _rail_rule(_rail_of(PROVENANCE_USER_STATED))
    model = _rail_board()
    [(severity, state, message)] = _rows(rule, model)
    assert (severity, state) == ("ERROR", "VIOLATION")
    assert "+12V：合同 requirements.rails[net=+12V].targetVoltage = '24V'（24 V）" in message
    assert "图纸的读数 12 V" in message
    assert "net name '+12V'" in message, "the drawing's own evidence is quoted"
    assert "谁错由人裁" in message and "不替你选边" in message
    assert "分级 ERROR（093 §〇）" in message and "user_stated" in message
    # The four-state row and the finding are one reading, and the finding carries
    # the rail as its structured identity (the signature the apply gate compares).
    [outcome] = rule.outcomes(model)
    [finding] = rule.check(model)
    assert outcome.state == "VIOLATION" and finding.severity == "ERROR"
    assert finding.target is not None and finding.target.net_refs == ["+12V"]
    assert len(finding.evidence) == 2
    assert finding.evidence[0].startswith("合同 requirements.rails[net=+12V]")
    assert finding.evidence[1].startswith("图纸 +12V = 12 V")


def test_a_clash_with_a_draft_or_a_recipe_is_only_a_warn_and_says_which():
    """052 §4's line, in code: a guess may not be graded as a violation.

    The `ai_asserted` row carries the caveat ("确认前不要照改"); the
    `verified_recipe` row carries its own, because it is stronger than a draft
    but is still not the engineer's own word — the two WARNs must never read
    alike.
    """
    draft = _rows(_rail_rule(_rail_of(PROVENANCE_AI)), _rail_board())
    assert [row[0] for row in draft] == ["WARN"]
    assert "ai_asserted" in draft[0][2] and "052 §4" in draft[0][2]
    assert "分级 WARN" in draft[0][2]
    recipe = _rows(_rail_rule(_rail_of(PROVENANCE_VERIFIED)), _rail_board())
    assert [row[0] for row in recipe] == ["WARN"]
    assert "verified_recipe" in recipe[0][2]
    assert "不是工程师本人声明" in recipe[0][2]


def test_a_rail_both_documents_price_the_same_way_files_no_finding():
    """The negative control the witness board needs: agreement is not a defect."""
    rule = _rail_rule(_rail_of(PROVENANCE_USER_STATED, declared="12V"))
    model = _rail_board()
    assert rule.check(model) == []
    [outcome] = rule.outcomes(model)
    assert outcome.state == "OK"
    assert "一致" in outcome.message and "net name '+12V'" in outcome.message


def test_a_rail_the_drawing_cannot_price_is_not_looked_at():
    """"图上判不出 → 不查": a net nobody prices has nothing to disagree with.

    A declaration of 24 V against a rail the drawing never prices is neither a
    pass nor a fail — and the same silence covers an unreadable declaration
    (092's own rule reports that slot) and a rail the contract never priced
    (which is the shipped ctrl FOC contract's shape: `role` and `provenance`
    only).
    """
    rule = _rail_rule(_rail_of(PROVENANCE_USER_STATED, declared="24V", net="RAILX"))
    model = _rail_board(net="RAILX")
    assert rule.outcomes(model) == [] and rule.check(model) == []
    unreadable = _rail_rule(_rail_of(PROVENANCE_USER_STATED, declared="twenty-four V"))
    assert unreadable.check(_rail_board()) == []
    unpriced = _rail_rule(_intent(di.IntentRail(net="+12V", provenance=PROVENANCE_USER_STATED)))
    assert unpriced.check(_rail_board()) == []


def test_without_a_contract_the_rail_rule_has_no_subject_at_all():
    """A1/A2's zero-movement reading: no contract, no row — and no new instance."""
    rule = ArchRailVoltageClash()
    assert rule.outcomes(_rail_board()) == [] and rule.check(_rail_board()) == []
    assert _rules_for(None) is BUILTIN_RULES, "no contract, no copy"


def test_a_welded_rail_is_refused_rather_than_judged():
    """Issue #19: one side of the clash *is* the drawing's inference.

    On a name the per-page merge welded blind, that voltage may have been taken
    from a regulator on the page next door, so neither "they agree" nor "they
    clash" is established — the row is UNKNOWN quoting the merge's sentence.
    """
    model = _rail_board()
    model.unproven_nets = {name: (PAGE_A, PAGE_B) for name in model.nets}
    rule = _rail_rule(_rail_of(PROVENANCE_USER_STATED))
    [(severity, state, message)] = _rows(rule, model)
    assert (severity, state) == (MEASUREMENT_GRADE, "UNKNOWN")
    assert UNPROVEN_BY_NAME in rule.outcomes(model)[0].missing_fact
    assert "+12V" in message


# ---------------------------------------------------------------------------
# R2: an open-drain output with nothing pulling it up
# ---------------------------------------------------------------------------


def test_an_open_drain_pin_with_no_pull_up_is_a_warn_quoting_the_shelf_and_the_fix():
    """F2's finding, as a rule: the pin, the net, the datasheet line, the fix."""
    rule = _opendrain_rule()
    model = _fault_board()
    [(severity, state, message)] = _rows(rule, model)
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "DRV1 pin18（FAULT#" in message
    assert f"网 '{FOC_FAULT_NET}' 上没有上拉" in message
    assert "DRV1.18" in message and "U1.34" in message, (
        "the net's members are quoted"
    )
    assert "没有电阻跨到 power-class 轨" in message
    assert "p.3 pin table" in message and "open-drain output requires an external pullup" in message
    assert "10k" in message and "修法：给" in message and "VCC" in message
    assert "合同 decisions[]" in message, "F2's legitimate exit is named"
    [finding] = rule.check(model)
    assert finding.target is not None
    assert finding.target.component_ref == "DRV1" and finding.target.pin_refs == ["18"]


@pytest.mark.parametrize("rail", ["3V3", "+3V3", "5V", "+5V", "1V8", "+1V8"])
def test_the_pull_up_rail_prices_the_same_how_it_is_spelled(rail):
    """Issue #71, measured at the rule it was reached through.

    ``power_domains.voltage_from_net_name`` is how ``_power_class`` decides the
    far end of a pull-up is a power-class rail. It priced ``3V3`` as 3.3 V and
    ``+3V3`` as **nothing**, so the *same board* — a ``10k`` from nFAULT to
    ``+3V3`` — was reported "开漏输出没有上拉" while the identical resistor to
    ``+5V`` passed. The pull-up is present in both readings; only the spelling
    of the rail it reaches decided the verdict, which is the hole #71 closes.
    """
    rule = _opendrain_rule()
    board = _fault_board(
        components={"R1": _part("R1", value="10k",
                                pins=[("1", FOC_FAULT_NET), ("2", rail)])},
        nets={FOC_FAULT_NET: [("R1", "1")], rail: [("R1", "2")]},
    )
    [(severity, state, message)] = _rows(rule, board)
    assert (severity, state) == ("INFO", "OK"), (rail, message)
    assert f"跨到 {rail!r}" in message
    assert "没有电阻跨到 power-class 轨" not in message


def test_a_resistor_to_a_power_rail_is_the_closure_and_is_a_measurement():
    """The other half of the same row: a closure is stated, not silently passed.

    Only a **resistor** counts, and only a rail this build can price counts as
    power-class — a capacitor from the fault net to the rail is a filter, and a
    rule that accepted one would report the wrong thing as closed.
    """
    rule = _opendrain_rule()
    with_pull_up = _fault_board(
        components={"R1": _part("R1", value="10k",
                                pins=[("1", FOC_FAULT_NET), ("2", "3V3")])},
        nets={FOC_FAULT_NET: [("R1", "1")], "3V3": [("R1", "2")]},
    )
    [(severity, state, message)] = _rows(rule, with_pull_up)
    assert (severity, state) == ("INFO", "OK")
    assert "有上拉：R1（10k）跨到 '3V3'" in message
    assert "net name '3V3' 报了 3.3 V" in message
    assert "测量行" in message

    with_capacitor = _fault_board(
        components={"C9": _part("C9", value="100nF", mpn="CAPX",
                                pins=[("1", FOC_FAULT_NET), ("2", "3V3")])},
        nets={FOC_FAULT_NET: [("C9", "1")], "3V3": [("C9", "2")]},
    )
    [(severity, state, _message)] = _rows(rule, with_capacitor)
    assert (severity, state) == ("WARN", "VIOLATION"), (
        "a filter capacitor to the rail is not a pull-up"
    )


def test_a_user_stated_decision_closes_it_and_a_draft_one_only_says_so():
    """F2's exit: the dependency is real but invisible on the drawing.

    The contract can declare that the pin uses the controller's internal pull-up
    — and only a `user_stated` decision closes the finding, because an AI-written
    draft is exactly the claim nobody has vouched for (052 §4). The draft is not
    swallowed either: the WARN names it and says why it does not count.
    """
    stated = _contract_with(_decision("U1", "PB12 用 MCU 内部上拉读 nFAULT", provenance=PROVENANCE_USER_STATED))
    [(severity, state, message)] = _rows(_opendrain_rule(intent=stated), _fault_board())
    assert (severity, state) == ("INFO", "OK")
    assert "按设计决策闭合" in message and "designMarks" not in message
    assert "decisions[subject='U1']" in message
    assert "user_stated" in message and "固件里必须真的" in message

    draft = _contract_with(_decision("U1", "假设固件开内部上拉", provenance=PROVENANCE_AI))
    [(severity, state, message)] = _rows(_opendrain_rule(intent=draft), _fault_board())
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "另有一条 decisions[subject='U1']" in message
    assert "不按它判闭合" in message and "052 §4" in message

    # A decision about something else is not a closure for this pin.
    elsewhere = _contract_with(_decision("R9", "把限流电阻改成 100Ω"))
    assert _rows(_opendrain_rule(intent=elsewhere), _fault_board())[0][0] == "WARN"


def test_the_open_drain_marker_is_what_makes_a_pull_requirement_this_rules_subject():
    """A connector's CC pin is the same fact kind and the opposite requirement.

    ``pull_required`` records without the marker belong to
    ``conn-usb-cc-pulldown`` (a pull-**down to ground**); reading them here would
    report every correctly designed Type-C socket as a missing pull-up. The
    marker is the filter, and this is the test that keeps it one.
    """
    pull_down = PartEntry(
        key="conn.type_c", mpn="TYPE-C", lcsc="C2765186", category="connector",
        facts={"pull_required": [{
            "pin": "4", "to": "GND", "expected_value": "5.1k",
            "provenance": "ST AN5225 Table 6, http://x.example/ds.pdf",
        }]},
    )
    model = _model_of(
        {"USB1": _part("USB1", mpn="TYPE-C", pins=[("4", "CC2", "CC2")]),
         "R27": _part("R27", value="5.1K", pins=[("1", "CC2"), ("2", "GND")])},
        {"CC2": [("USB1", "4"), ("R27", "1")], "GND": [("R27", "2")]},
    )
    assert OpenDrainPullup(library=PartLibrary(parts=[pull_down])).check(model) == []
    assert OpenDrainPullup(library=PartLibrary(parts=[pull_down])).outcomes(model) == []


def test_a_fault_pin_on_no_net_at_all_is_still_a_missing_pull_up():
    """A pin that reaches nothing has nothing pulling it up either."""
    model = _fault_board(pins=(("18", "FAULT#", None),))
    model.nets.pop(FOC_FAULT_NET)
    model.components["U1"].pins[0].net = None
    [(severity, state, message)] = _rows(_opendrain_rule(), model)
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "不接任何网" in message and "10k" in message


def test_a_welded_fault_net_is_refused_rather_than_judged():
    """Issue #19: "a resistor is on this net" is read from the net's members."""
    model = _fault_board()
    model.unproven_nets = {name: (PAGE_A, PAGE_B) for name in model.nets}
    [(severity, state, message)] = _rows(_opendrain_rule(), model)
    assert (severity, state) == (MEASUREMENT_GRADE, "UNKNOWN")
    assert UNPROVEN_BY_NAME in _opendrain_rule().outcomes(model)[0].missing_fact
    assert FOC_FAULT_NET in message


def test_a_part_with_no_open_drain_facts_is_never_a_subject():
    """The rule has no subject without the shelf saying so — no guessing from names."""
    bare = PartEntry(key="ic.plain", mpn="DRVX", lcsc="C1", category="ic.motor-driver")
    rule = OpenDrainPullup(library=PartLibrary(parts=[bare]))
    assert rule.check(_fault_board()) == [] and rule.outcomes(_fault_board()) == []


# ---------------------------------------------------------------------------
# R3: a controller's reset pin with nothing on it
# ---------------------------------------------------------------------------


def _nrst_rule(shelf: PartLibrary | None = None) -> NrstClosure:
    return NrstClosure(library=shelf if shelf is not None else PartLibrary(parts=[]))


def test_a_naked_reset_pin_is_a_warn_naming_the_consequences_and_the_fix():
    """F3's finding, as a rule: single-member net, no key, no cap, no programmer."""
    rule = _nrst_rule()
    [(severity, state, message)] = _rows(rule, _mcu_board())
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "U1 pin7（PG10-NRST）在网 'NRST' 上是**单成员网**" in message
    assert "没有电容、没有按键、没有测试点、也没有编程器引出" in message
    assert "随机复位" in message and "connect-under-reset" in message
    assert "100nF" in message and "SWD 座" in message
    assert "ST AN5093" in message, "the fix carries its own citation"
    assert "控制器判据：" in message and "P<端口><数字>" in message
    [finding] = rule.check(_mcu_board())
    assert finding.target is not None
    assert finding.target.component_ref == "U1" and finding.target.pin_refs == ["7"]


def test_a_reset_net_with_something_on_it_is_a_measurement():
    """The closure is stated (INFO), never silently passed — the 092 discipline."""
    closed = _mcu_board(
        components={"C73": _part("C73", value="100nF", mpn="CAPX",
                                 pins=[("1", FOC_RESET_NET), ("2", "GND")])},
        nets={FOC_RESET_NET: [("C73", "1")], "GND": [("C73", "2")]},
    )
    [(severity, state, message)] = _rows(_nrst_rule(), closed)
    assert (severity, state) == ("INFO", "OK")
    assert "有 2 个成员" in message and "U1.7, C73.1" in message
    assert "复位脚不裸奔" in message


def test_the_reset_pin_is_read_off_the_consequences_name_not_the_prefix():
    """A name segment has to *be* the word: ``PG10-NRST`` yes, ``PRESET`` no."""
    for name in ("NRST", "nRST", "RESET", "RESET#", "PG10-NRST", "MCLR-NRST"):
        assert _is_reset_name(name), name
    for name in ("PRESET", "NRSTX", "PGNRST", "PB12", "", None):
        assert not _is_reset_name(name), name
    # A compound name that *carries* the word is one — the symbol is naming a
    # reset there — so the whole name does not have to be the word.
    assert _is_reset_name("NRST_OUT") and _is_reset_name("RESET_CONF")
    # ... and a part with no reset-named pin files nothing, even when it *is* a
    # controller by its port pins.
    quiet = _model_of(
        {"U1": _part("U1", mpn="STM32X",
                     pins=[(str(n), f"PA{n}", None) for n in range(4)])},
        {},
    )
    assert _nrst_rule().check(quiet) == [] and _nrst_rule().outcomes(quiet) == []


def test_a_part_no_evidence_calls_a_controller_is_not_judged():
    """The architecture walk's own evidence decides, and nothing else does.

    A motor driver with a `RESET#` pin is not a controller (its pins are not
    ``P<port><n>``, and the shelf does not call it an MCU), so its reset pin is
    not this rule's subject — the same reading
    :func:`boardwise.core.architecture.controller_evidence` publishes.
    """
    driver = _model_of(
        {"DRV1": _part("DRV1", mpn="DRVX",
                       pins=[("16", "RESET#", "NRESET"), ("18", "FAULT#", "NFAULT")])},
        {"NRESET": [("DRV1", "16")], "NFAULT": [("DRV1", "18")]},
    )
    assert _nrst_rule().check(driver) == [] and _nrst_rule().outcomes(driver) == []


def test_a_shelf_mcu_is_recognised_without_any_port_pins():
    """The other half of the controller evidence: ``category: ic.mcu``.

    Both routes are the architecture walk's own (093 A3a made
    ``controller_evidence`` public rather than writing a second recogniser), so
    a shelf-classified MCU whose symbol uses plain pin names is judged too.
    """
    entry = PartEntry(key="ic.mcu", mpn="MCUX", lcsc="C9", category="ic.mcu")
    model = _model_of(
        {"U9": _part("U9", mpn="MCUX",
                     pins=[("1", "RESET", FOC_RESET_NET), ("2", "VDD", "VCC")])},
        {FOC_RESET_NET: [("U9", "1")], "VCC": [("U9", "2")]},
    )
    [(severity, state, message)] = _rows(NrstClosure(library=PartLibrary(parts=[entry])), model)
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "货架 category=ic.mcu（ic.mcu）" in message


def test_a_reset_pin_that_reaches_no_net_at_all_is_a_warn():
    model = _mcu_board(reset_net=None)
    [(severity, state, message)] = _rows(_nrst_rule(), model)
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "不接任何网" in message and "100nF" in message


def test_a_welded_reset_net_is_refused_rather_than_judged():
    """"Is this reset pin alone" is a count of the net's members (issue #19)."""
    model = _mcu_board()
    model.unproven_nets = {name: (PAGE_A, PAGE_B) for name in model.nets}
    [(severity, state, message)] = _rows(_nrst_rule(), model)
    assert (severity, state) == (MEASUREMENT_GRADE, "UNKNOWN")
    assert UNPROVEN_BY_NAME in _nrst_rule().outcomes(model)[0].missing_fact
    assert FOC_RESET_NET in message


# ---------------------------------------------------------------------------
# the shelf's data side (issue #56): DRV8313 nFAULT + VM bypasses
# ---------------------------------------------------------------------------


def test_the_shipped_shelf_marks_the_drv8313_fault_pin_and_its_vm_bypasses():
    """F2/F4's data side, on the committed shelf: the two claims the driver needs.

    The entry had neither a category nor facts, which is why no rule could see
    the part at all (§6 of the ctrl FOC review). What is recorded is exactly the
    pin table's two statements — an open-drain fault output that needs an
    external pull-up, and one 0.1 uF bypass per VM pin.
    """
    entry = load_parts(SHELF).by_lcsc()["C92482"]
    assert entry.mpn == "DRV8313PWPR"
    assert entry.category == "ic.motor-driver"
    assert entry.category in CATEGORY_VOCABULARY
    assert entry.facts_verified is True, "a curated fact drives rules, so it is a reviewed claim"
    [pull] = entry.facts["pull_required"]
    assert pull["pin"] == "18" and pull["open_drain"] is True
    assert pull["to"] == "VCC" and pull["expected_value"] == "10k"
    assert "p.3" in pull["provenance"] and "external pullup" in pull["provenance"]
    assert "http" in pull["provenance"], "a fact without a source is not recorded"
    assert [(cap["pin"], cap["value"]) for cap in entry.facts["required_caps"]] == [
        ("4", "0.1uF"), ("11", "0.1uF"),
    ]
    assert all("p.3" in cap["provenance"] for cap in entry.facts["required_caps"])
    assert any("093 A3a" in note for note in entry.notes), (
        "the curation says where it came from"
    )
    # The marker is the driver's alone: every other pull requirement on the shelf
    # is a connector's CC pull-down, which is another rule's subject.
    marked = {
        part.lcsc for part in load_parts(SHELF).parts
        for record in (part.facts or {}).get("pull_required", [])
        if record.get("open_drain")
    }
    assert marked == {"C92482"}, marked


def test_the_open_drain_marker_is_optional_and_the_record_schema_stays_closed():
    """090's rule on the one new key: absent means absent, wrong is refused.

    A record written before this key existed must round-trip byte-identically
    (the shelf's own reproducibility promise), and a marker that is not a
    boolean is a malformed fact rather than a truthy one.
    """
    page = "issue-093 fixture datasheet, p.3, http://example.com/ds.pdf"
    base = {
        "key": "conn.type_c", "lcsc": "C2765186", "mpn": "TYPE-C",
        "deviceUuid": "f809d2f6af2d4c2eb58795bc97ecb0d8",
        "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
        "category": "connector",
    }
    without = entry_from_json({**base, "facts": {"pull_required": [
        {"pin": "4", "to": "GND", "expected_value": "5.1k", "provenance": page},
    ]}}, "<t>")
    assert "open_drain" not in without.facts["pull_required"][0], (
        "an unstated marker does not occupy a key"
    )
    with_marker = entry_from_json({**base, "facts": {"pull_required": [
        {"pin": "18", "to": "VCC", "expected_value": "10k", "open_drain": True,
         "provenance": page},
    ]}}, "<t>")
    assert with_marker.facts["pull_required"][0]["open_drain"] is True

    for bad in (
        "yes", 1, {},           # not a boolean
    ):
        payload = {**base, "facts": {"pull_required": [
            {"pin": "18", "to": "VCC", "expected_value": "10k", "open_drain": bad,
             "provenance": page},
        ]}}
        with pytest.raises(PartError, match="open_drain"):
            entry_from_json(payload, "<t>")
    unknown = {**base, "facts": {"pull_required": [
        {"pin": "18", "to": "VCC", "expected_value": "10k", "od": True,
         "provenance": page},
    ]}}
    with pytest.raises(PartError, match="unknown key"):
        entry_from_json(unknown, "<t>")


# ---------------------------------------------------------------------------
# the seam: which rules carry a contract, and which rules a welded net refuses
# ---------------------------------------------------------------------------


def test_run_review_hands_the_contract_to_the_six_rules_that_read_one():
    """091 A2a's seam, now with eight carriers — and the shared instances stay clean.

    094 A3b added `arch-sense-bias-closure`, whose subject (a bidirectional
    current-sense chain) only exists in a contract. 064 added the two selection
    rules, which take the contract for a weaker reason: their subject is a part
    on the board, so they run without one — the contract only decides *which*
    document the rail's voltage is read from.
    """
    contract = _intent(_rail("+12V", targetVoltage="12V"))
    rules = _rules_for(contract)
    assert [rule.id for rule in rules] == [rule.id for rule in BUILTIN_RULES]
    carriers = {
        rule.id: rule for rule in rules if rule.__class__ in set(INTENT_RULES)
    }
    assert set(carriers) == {
        "param-value-mpn-match", "pwr-cap-voltage-rating", "path-ldo-dissipation",
        "arch-rail-voltage-clash", "arch-opendrain-pullup", "arch-sense-bias-closure",
        "sel-tvs-standoff-rail", "sel-ldo-fixed-output",
    }
    assert all(rule.intent is contract for rule in carriers.values())
    assert NrstClosure not in INTENT_RULES, (
        "the reset rule's whole subject is the shelf and the netlist"
    )
    assert {rule.id for rule in BUILTIN_RULES if isinstance(rule, ArchRailVoltageClash)} == {
        "arch-rail-voltage-clash"
    }
    for rule, template in zip(rules, BUILTIN_RULES):
        if rule.id in carriers:
            assert rule is not template
            continue
        assert rule is template, rule.id
    for template in BUILTIN_RULES:
        if isinstance(template, (ArchRailVoltageClash, OpenDrainPullup,
                                 ArchSenseBiasClosure)):
            assert template.intent is None, "the shared instance kept no answer"


def test_the_three_arch_rules_are_registered_where_a_welded_net_is_refused():
    """Issue #19's registry: every one of these three reads net membership."""
    for rule_id in (
        "arch-rail-voltage-clash", "arch-opendrain-pullup", "arch-nrst-closure",
    ):
        assert rule_id in NET_MEMBERSHIP_RULES, rule_id
    ids = {rule.id for rule in BUILTIN_RULES}
    assert ids >= set(NET_MEMBERSHIP_RULES)


# ---------------------------------------------------------------------------
# the real case: the ctrl FOC export reproduces F2 and F3, and R1 stays quiet
# ---------------------------------------------------------------------------


def _foc_findings(intent=None):
    return run_review(build_project_model(ROBOT), intent=intent)


def test_the_ctrl_foc_export_reproduces_f2_and_f3_from_the_rules():
    """093 §二's witness: two rules, one real board, the review's own findings.

    F2 and F3 were found by hand against the datasheet (the review's §6 says so:
    ``DRV1`` never entered any facts rule, because ``IC_PATTERN`` demands a
    ``U``-prefixed designator). The rules now say the same two things from the
    export alone:

    * ``DRV1 pin18`` sits on ``NFAULT`` with **no** resistor to a rail — the
      driver's open-drain fault output, the board's only remaining fault path
      after the internal comparator was tied off;
    * ``U1 pin7`` (``PG10-NRST``) sits on the single-member net ``NRST``.

    R1 files **nothing** here, and that is the negative control: the shipped
    contract declares no `targetVoltage` at all, so there is no requirement to
    contradict (the measured rows below are the two F-cases and nothing else).
    """
    findings = _foc_findings(di.IntentSource.load(FOC_CONTRACT))
    by_rule = {}
    for finding in findings:
        by_rule.setdefault(finding.rule_id, []).append(finding)

    assert by_rule.get("arch-rail-voltage-clash", []) == [], (
        "the shipped contract prices no rail, so R1 has no subject"
    )

    [fault] = by_rule["arch-opendrain-pullup"]
    assert fault.severity == "WARN"
    assert fault.target.component_ref == "DRV1" and fault.target.pin_refs == ["18"]
    assert "网 'NFAULT' 上没有上拉" in fault.message
    assert "U1.34, DRV1.18" in fault.message
    assert "open-drain output requires an external pullup" in fault.message
    assert "loads" not in fault.message
    assert "修法：给 'NFAULT' 加 10k 上拉到 'VCC'" in fault.message

    [reset] = by_rule["arch-nrst-closure"]
    assert reset.severity == "WARN"
    assert reset.target.component_ref == "U1" and reset.target.pin_refs == ["7"]
    assert "网 'NRST' 上是**单成员网**" in reset.message
    assert "F3 的形状" in reset.message


def test_the_ctrl_foc_negative_control_holds_when_the_contract_prices_the_rail():
    """The same board with a rail **priced** at the drawing's own value.

    The shipped contract declares no voltage, which would make the negative
    control vacuous; here ``+12V`` is declared at exactly what the drawing's own
    inference says (12 V), so the rule has a subject and both documents agree —
    no row, and the rest of the reading is unchanged.
    """
    contract = di.IntentSource.load(FOC_CONTRACT)
    contract.document.rails[0].slots["targetVoltage"] = "12V"
    contract.document.rails[0].provenance = PROVENANCE_USER_STATED
    by_rule = {}
    for finding in _foc_findings(contract):
        by_rule.setdefault(finding.rule_id, []).append(finding)
    assert by_rule.get("arch-rail-voltage-clash", []) == []
    assert len(by_rule["arch-opendrain-pullup"]) == 1
    assert len(by_rule["arch-nrst-closure"]) == 1

    # ... and the same contract declaring a *different* voltage is the ERROR the
    # linkage test below drives through the apply gate.
    clashing = di.IntentSource.load(FOC_CONTRACT)
    clashing.document.rails[0].slots["targetVoltage"] = "24V"
    clashing.document.rails[0].provenance = PROVENANCE_USER_STATED
    [row] = [
        finding for finding in _foc_findings(clashing)
        if finding.rule_id == "arch-rail-voltage-clash"
    ]
    assert row.severity == "ERROR"
    assert "合同 requirements.rails[net=+12V].targetVoltage = '24V'" in row.message
    assert "图纸的读数 12 V" in row.message


# ---------------------------------------------------------------------------
# the linkage: an intent ERROR is what #55's gate blocks
# ---------------------------------------------------------------------------


def _clash_finding(provenance: str):
    contract = di.IntentSource.load(FOC_CONTRACT)
    contract.document.rails[0].slots["targetVoltage"] = "24V"
    contract.document.rails[0].provenance = provenance
    return next(
        finding for finding in _foc_findings(contract)
        if finding.rule_id == "arch-rail-voltage-clash"
    )


def test_the_apply_gate_blocks_an_intent_error_and_force_never_releases_it():
    """#55 ruling B, driven by this batch's own ERROR finding.

    The gate grades the signatures a write *grows*: an ERROR stops the save and
    ``--force`` does not touch it (``warning-triage``'s own words: no flag makes
    a contradiction with the engineer's statement right), while a WARN is
    released only by ``--force`` — and then named in ``forcedWarns`` and in the
    report's notes, never silently. The findings here are the real ones a rule
    files on the real export; nothing about the grade is hand-made.
    """
    from boardwise.cli import _finding_signature, _new_findings_verdict, _signature_severity

    error = _clash_finding(PROVENANCE_USER_STATED)
    assert error.severity == "ERROR"
    signature = _finding_signature(error)
    assert _signature_severity(signature) == "ERROR"
    assert signature.endswith("|+12V"), signature
    quiet = _new_findings_verdict([signature], force=False)
    forced = _new_findings_verdict([signature], force=True)
    assert quiet["blocking"] == [signature]
    assert forced["blocking"] == [signature], "--force never releases an ERROR"
    assert forced["forcedWarns"] == []

    warn_signature = _finding_signature(_clash_finding(PROVENANCE_AI))
    released = _new_findings_verdict([warn_signature], force=True)
    assert released["blocking"] == [], "a WARN is released by --force"
    assert released["forcedWarns"] == [warn_signature], (
        "and the release is named, so it reaches the report"
    )
    assert _new_findings_verdict([warn_signature], force=False)["blocking"] == [warn_signature]


def test_the_gate_stops_the_run_at_exit_2_when_it_blocks():
    """The blocking verdict's consequence, pinned structurally in the CLI.

    Every apply path that grades grown findings returns the edit family's "the
    promised effect is not on the page" code (2) from exactly that branch; a
    source pin is what keeps that sentence true without a bridge.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")
    assert source.count('return done(2, "failed", "new_findings")') == 3, (
        "the three gates: draw apply, edit apply --insert, edit apply --move"
    )
    for gate in (
        "_render_draw_apply", "_render_edit_apply_insert", "_render_edit_apply_move",
    ):
        # One gate's own body: from its `def` to the next one at column zero.
        newline = chr(10)
        body = source.split(f"{newline}def {gate}(", 1)[1].split(f"{newline}def ", 1)[0]
        graded = body.index("_grade_new_findings(")
        blocked = body.index('return done(2, "failed", "new_findings")')
        assert graded < blocked, gate


def test_the_gate_walk_passes_no_contract_today_so_the_structural_warns_reach_it():
    """What reaches the gate **today**, measured rather than assumed.

    ``_baseline_findings`` runs ``run_review(model)`` with **no** contract, so an
    intent-driven ERROR cannot appear in an apply run's baseline or in what it
    grows — the grading mechanism is what this batch pinned, and wiring the
    contract into the apply walk is a change to ``apply`` (093 §〇 says "不改代码").
    The two structural rules need no contract, so their WARNs *do* reach it: F2's
    missing pull-up and F3's naked reset pin would stop a write on this board
    even before any intent existed.
    """
    from boardwise.cli import _baseline_findings

    model = build_project_model(ROBOT)
    signatures = _baseline_findings(model)
    ids = {signature.split("|", 1)[0] for signature in signatures}
    assert "arch-opendrain-pullup" in ids
    assert "arch-nrst-closure" in ids
    assert "arch-rail-voltage-clash" not in ids, (
        "apply's walk has no contract, so the intent ERROR cannot be in it yet"
    )
