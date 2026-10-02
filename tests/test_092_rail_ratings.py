"""092 A2b: the rail ratings, and the contract that finally reaches the rules.

Two halves, both commissioned by 092 and both pinned here:

* **the wiring** — 091 A2a built the seam (`run_review(model, intent=…)`) and left
  `checkup` on the wrong side of it: the rule walk ran *before* the shelf was
  loaded, the architecture enumerated and the contract resolved, so a
  `checkup --intent` drove the report's `intent` section and nothing else. The
  three steps move up, the rules read the contract, and a reading that names **no**
  contract stays what it was;
* **the two rail-rating rules** (`pwr-cap-voltage-rating`, `path-ldo-dissipation`)
  — one discipline, three states: a measurement is always reported (INFO), only a
  limit this build can state is a WARN, and what cannot be read is UNKNOWN with
  the address of the missing answer. No derating standard is invented: the
  comparisons are `rating >= rail` and `P <= declared limit`, nothing else.

Offline throughout: fixtures are read as files, no bridge, no network.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import shutil
from pathlib import Path

import pytest

from boardwise.core import designintent as di
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartError, PartLibrary, entry_from_json
from boardwise.core.values import mpn_voltage_rating, parse_current_amps
from boardwise.engines.review import BUILTIN_RULES, _rules_for, run_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.railratings import (
    CapVoltageRating,
    LdoDissipation,
    cap_voltage_rating,
)
from boardwise.rules.unproven import UNPROVEN_BY_NAME

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SHELF = Path("blocklib/parts.json")
FOC_CONTRACT = Path("blocklib/intents/robot-ctrl-foc.intent.json")
RAILRATINGS_SOURCE = Path("src/boardwise/rules/railratings.py")
CLI_SOURCE = Path("src/boardwise/cli.py")

#: The two MPNs the ctrl FOC export's capacitors carry, and the code field each
#: one states its rating in (value + tolerance + voltage: 10 uF ±20 % 25 V).
FOC_10U_MPN = "HGC0603R5106M250NTHJ"
FOC_100N_MPN = "CGA0603X7R104K500JT"


def _part(designator: str, *, value: str = "", mpn: str = "", pins=()):
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        pins=[Pin(str(number), "", net) for number, net in pins],
    )


def _model_of(components: dict, nets: dict) -> DesignModel:
    model = DesignModel()
    model.components.update(components)
    model.nets = {name: Net(name, list(pins)) for name, pins in nets.items()}
    return model


def _cap_model(
    *, designator: str = "C1", value: str = "100nF", mpn: str = "CAP1",
    rail: str = "+24V", ground: str = "GND",
) -> DesignModel:
    """One capacitor between ``rail`` and ``ground`` — the subject R1 judges."""
    return _model_of(
        {designator: _part(designator, value=value, mpn=mpn,
                           pins=[("1", rail), ("2", ground)])},
        {rail: [(designator, "1")], ground: [(designator, "2")]},
    )


def _cap_shelf(rating: str, *, mpn: str = "CAP1", lcsc: str = "C1") -> PartLibrary:
    """A one-entry shelf: the catalog's own ``Voltage Rating`` field.

    That field is where the shelf really keeps a rating (`blocklib/parts.json`:
    ``"Voltage Rating": "50V"``), which is why the rule reads the entry rather
    than mining a description.
    """
    params = {"Voltage Rating": rating} if rating else {}
    return PartLibrary(parts=[
        PartEntry(key="cap.100n_0603", mpn=mpn, lcsc=lcsc, params=params),
    ])


def _ldo_entry(*, limit_mw: float | None = None, dropout_mv: float = 400.0) -> PartEntry:
    """One curated LDO on the shelf: VIN on pin 1, its cap on pin 2 (= VOUT)."""
    ldo: dict = {
        "dropout_max_mv": dropout_mv,
        "condition": "Iout=500mA",
        "provenance": "issue-092 fixture datasheet, p.3, http://example.com/ds.pdf",
    }
    if limit_mw is not None:
        ldo["max_dissipation_mw"] = {
            "mw": limit_mw,
            "provenance": (
                "issue-092 fixture datasheet, p.2 (Power Dissipation), "
                "http://example.com/ds.pdf"
            ),
        }
    return PartEntry(
        key="ic.ldo", mpn="LDO1", lcsc="C2", category="ic.ldo",
        facts={
            "ldo": ldo,
            "supply_pins": [{"pins": ["1"], "name": "VIN",
                             "v_operating": [2.2, 30.0],
                             "provenance": "issue-092 fixture datasheet, p.3"}],
            "required_caps": [{"pin": "2", "value": "1uF",
                               "provenance": "issue-092 fixture datasheet, p.4"}],
        },
    )


def _ldo_model(*, vin: str = "+24V", vout: str = "3V3") -> DesignModel:
    return _model_of(
        {"U1": _part("U1", mpn="LDO1", pins=[("1", vin), ("2", vout)])},
        {vin: [("U1", "1")], vout: [("U1", "2")]},
    )


def _intent(*rails: di.IntentRail, path: str = "mem://contract.json") -> di.IntentSource:
    return di.IntentSource(document=di.DesignIntent(rails=list(rails)), path=path)


def _rail(net: str, **slots: str) -> di.IntentRail:
    return di.IntentRail(net=net, slots=dict(slots))


def _cap_rule(shelf: PartLibrary, intent: di.IntentSource) -> CapVoltageRating:
    return CapVoltageRating(library=shelf, intent=intent)


def _ldo_rule(shelf: PartLibrary, intent: di.IntentSource) -> LdoDissipation:
    return LdoDissipation(library=shelf, intent=intent)


def _rows(rule, model) -> list[tuple[str, str, str]]:
    """``(severity, state, message)`` for every row the rule files.

    One row each, in order: the findings are built from the same walk as the
    four-state rows, and pairing them by position is what keeps "the state and
    the severity are two readings of one row" true for a rule that files two
    rows about one part (R2's measurement and its missing current).
    """
    outcomes = rule.outcomes(model)
    findings = rule.check(model)
    assert len(outcomes) == len(findings), (outcomes, findings)
    return [
        (finding.severity, outcome.state, finding.message)
        for outcome, finding in zip(outcomes, findings)
    ]


# ---------------------------------------------------------------------------
# the value readers the two rules stand on
# ---------------------------------------------------------------------------


def test_the_voltage_code_reader_reads_its_field_and_refuses_everything_else():
    """071 §1 C's anchor rule, applied to the one field that carries a rating.

    ``_VOLTAGE_TAIL_RE`` is the shape this module *already* refuses a value
    reading for ("its second group is a rating"), so reading the rating out of
    it is the same claim the guard makes — and a token without the tail is not
    a rating this build can state.
    """
    assert mpn_voltage_rating(FOC_10U_MPN) == (25.0, "106M250")
    assert mpn_voltage_rating(FOC_100N_MPN) == (50.0, "104K500")
    # The bare EIA code in an MPN says nothing about voltage (the guard's own
    # witnesses), and neither does a token whose shape is a different family.
    for token in ("CC0603KRX7R9BB104", "CL05B104KO5NNNC", "C1608X5R1V225KT000E",
                  "100nF/50V", "", "abc"):
        assert mpn_voltage_rating(token) is None, token
    # A code asking for ten kilovolts is refused rather than reported: the
    # exponent guard, so a mis-shaped tail cannot produce a 10 kV "rating".
    assert mpn_voltage_rating("XX106K103") is None


def test_the_shelf_and_the_code_reader_agree_on_every_catalogued_capacitor():
    """Two independent readings of one number, checked against each other.

    The catalog states the rating in its own ``Voltage Rating`` field; the part
    number states it in its own code field. Where both speak they must agree,
    and this is the measurement that says the code reader is the same claim the
    catalog already makes — 11 capacitors, 11 agreements, 0 disagreements.
    """
    from boardwise.core.parts import load_parts

    library = load_parts(SHELF)
    checked = 0
    for entry in library.parts:
        if not entry.key.startswith("cap."):
            continue
        decoded = mpn_voltage_rating(entry.mpn or "")
        if decoded is None:
            continue
        stated = next(
            (entry.params[key] for key in
             ("Voltage Rating", "Voltage Rated", "Rated Voltage", "Rated voltage")
             if entry.params.get(key)),
            "",
        )
        assert stated, f"{entry.key}: a code field with no stamped rating to check"
        assert float(stated.rstrip("Vv")) == decoded[0], entry.key
        checked += 1
    assert checked == 11, checked


def test_the_current_reader_needs_a_unit_and_keeps_the_sign():
    assert parse_current_amps("5A") == 5.0
    assert parse_current_amps("5 A") == 5.0
    assert parse_current_amps("500mA") == 0.5
    assert parse_current_amps("1.5A") == 1.5
    assert parse_current_amps("200uA") == pytest.approx(2e-4)
    assert parse_current_amps("200µA") == pytest.approx(2e-4)
    assert parse_current_amps("-5A") == -5.0
    # A bare number is refused on purpose (the 011 lesson: an unparseable
    # quantity may never become a guess), and so is a unit it does not know.
    for token in ("5", "", "5V", "5W", "1.5安", "mA", "abc"):
        assert parse_current_amps(token) is None, token


# ---------------------------------------------------------------------------
# R1: the capacitor's rating against the rail it sits on
# ---------------------------------------------------------------------------


def test_a_rating_above_the_rail_is_an_info_measurement():
    """The measurement is the point: the ratio is stated, nothing is graded."""
    rule = _cap_rule(_cap_shelf("50V"), _intent(_rail("+24V", targetVoltage="24V")))
    [(severity, state, message)] = _rows(rule, _cap_model())
    assert severity == "INFO"
    assert state == "OK"
    assert "耐压 50 V ≥ 所在轨 +24V = 24 V" in message
    assert "2.08x" in message
    assert "不套降额系数" in message and "不发明降额标准" in message
    assert "Voltage Rating = '50V'" in message, "the rating's source is named"


def test_a_rating_below_the_rail_is_a_warn_and_not_a_derating_opinion():
    """An over-voltage is a fact about two numbers, so no policy is needed."""
    rule = _cap_rule(_cap_shelf("16V"), _intent(_rail("+24V", targetVoltage="24V")))
    # The rule's own four-state row *and* the finding agree on the subject.
    by_subject = {o.subject: o for o in rule.outcomes(_cap_model())}
    assert by_subject["C1"].state == "VIOLATION"
    [(severity, state, message)] = _rows(rule, _cap_model())
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "耐压 16 V < 所在轨 +24V = 24 V" in message
    assert "确定的越限" in message and "不是降额口味" in message
    finding = rule.check(_cap_model())[0]
    assert finding.target.component_ref == "C1", "the canvas gets a ref"
    assert finding.severity == "WARN"


def test_a_rating_equal_to_the_rail_is_within_it():
    """``>=`` is the line: equality is a pass in the measurement, not a WARN."""
    rule = _cap_rule(_cap_shelf("24V"), _intent(_rail("+24V", targetVoltage="24V")))
    [(severity, state, message)] = _rows(rule, _cap_model())
    assert (severity, state) == ("INFO", "OK")
    assert "比值 1.00x" in message


def test_a_rating_nobody_states_is_unknown_and_names_the_part_and_rail():
    """The C-series case: no shelf entry, no MPN, and no rating in the value."""
    rule = _cap_rule(_cap_shelf("", mpn="OTHER"), _intent(_rail("+24V", targetVoltage="24V")))
    [(severity, state, message)] = _rows(rule, _cap_model())
    assert (severity, state) == ("INFO", "UNKNOWN"), "an unknown is not a defect"
    assert "的耐压读不出" in message
    assert "needs_datasheet 同族点名：C1 的耐压（所在轨 +24V = 24 V）" in message
    # Three reading sites, all named — a work order with an address.
    for site in ("Voltage Rating", "100nF/50V", "value+tolerance+voltage"):
        assert site in message, site
    assert rule.outcomes(_cap_model())[0].missing_fact == "C1 的耐压（所在轨 +24V = 24 V）"


def test_the_three_reading_sites_are_tried_in_the_catalog_then_board_order():
    """Shelf field → the board's value field → the MPN's code field.

    Each source is removed in turn so the *fallback* is measured, not just the
    winning reading: a rule that silently skipped a site would look identical
    whenever the first one answered.
    """
    model = _cap_model(value="100nF/16V", mpn=FOC_100N_MPN)
    entry = _cap_shelf("50V", mpn=FOC_100N_MPN).parts[0]
    volts, where = cap_voltage_rating(model.components["C1"], entry)
    assert (volts, "Voltage Rating = '50V'" in where) == (50.0, True), where
    # ... without a shelf entry: the board's own field, which states 16 V.
    volts, where = cap_voltage_rating(model.components["C1"], None)
    assert (volts, "100nF/16V" in where) == (16.0, True), where
    # ... and with neither: the MPN's code field, named as the anchor it is.
    bare = _cap_model(value="100nF", mpn=FOC_100N_MPN)
    volts, where = cap_voltage_rating(bare.components["C1"], None)
    assert (volts, "104K500" in where) == (50.0, True), where
    assert "071 §1 C" in where


def test_a_capacitance_prefix_is_never_read_as_a_voltage():
    """``10UF`` states no rating: ``U`` is a capacitance unit, and the token
    has to be a whole voltage (``parse_voltage_volts``) to count."""
    model = _cap_model(value="10UF", mpn="")
    assert cap_voltage_rating(model.components["C1"], None) == (None, "")


def test_a_rail_with_no_voltage_anywhere_is_unknown_naming_both_addresses():
    """``+24V`` says 24 V by name; a rail that says nothing needs a declaration.

    Both places an answer could come from are named, because "the drawing never
    says" and "the contract never asked" are two different fixes.
    """
    rule = _cap_rule(_cap_shelf("50V"), _intent(_rail("RAILX")))
    model = _cap_model(rail="RAILX")
    [(severity, state, message)] = _rows(rule, model)
    assert (severity, state) == ("INFO", "UNKNOWN")
    assert "所在轨 RAILX 的电压读不出" in message
    assert "耐压 50 V" in message, "a rating that IS known is still stated"
    missing = rule.outcomes(model)[0].missing_fact
    assert "no source names the voltage of net 'RAILX'" in missing
    assert "requirements.rails[net=RAILX].targetVoltage" in missing
    assert "mem://contract.json" in missing, "the file to write is named"


def test_the_contracts_voltage_wins_over_the_drawings_and_a_draft_is_flagged():
    """The requirement is the yardstick; a draft requirement says so out loud.

    The rail is named ``+12V`` (so the drawing's inference states 12 V) while the
    contract declares 24 V. The contract wins — it *is* the requirement — and
    because the declaration is an ``ai_asserted`` draft the row carries 052 §4's
    caveat rather than reading as a statement (A2a's own wording discipline; the
    severity is not moved by provenance, because grading by intent is A3's).
    """
    shelf = _cap_shelf("16V")
    stated = _intent(_rail("+12V", targetVoltage="24V"))
    stated.document.rails[0].provenance = "user_stated"
    [(severity, state, message)] = _rows(_cap_rule(shelf, stated), _cap_model(rail="+12V"))
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "所在轨 +12V = 24 V" in message
    assert "合同 requirements.rails[net=+12V].targetVoltage = '24V'" in message
    assert "052 §4" not in message

    draft = _intent(di.IntentRail(net="+12V", slots={"targetVoltage": "24V"},
                                 provenance="ai_asserted"))
    [(severity, _, message)] = _rows(_cap_rule(shelf, draft), _cap_model(rail="+12V"))
    assert severity == "WARN", "an intent states a direction; grading by it is A3's"
    assert "ai_asserted 草稿（052 §4），确认前不要照改" in message


def test_a_declared_voltage_this_build_cannot_read_is_unknown():
    rule = _cap_rule(_cap_shelf("50V"), _intent(_rail("+24V", targetVoltage="twenty-four volts")))
    [(severity, state, message)] = _rows(rule, _cap_model())
    assert (severity, state) == ("INFO", "UNKNOWN")
    assert "不是本工具能读量的写法" in message
    assert "`24V`、`3.3V`" in message, "the spelling that would work is given"


def test_a_welded_rail_name_is_refused_rather_than_judged():
    """Issue #19: "a capacitor sits on this rail" is read from a net's members.

    On a name the per-page merge welded blind the capacitor may be the other
    board's part, so the row is UNKNOWN with the merge's own sentence (which is
    also why this rule is in ``NET_MEMBERSHIP_RULES``).
    """
    model = _cap_model()
    model.unproven_nets = {name: ("aaaa1111aaaa111111", "bbbb2222bbbb222222")
                           for name in model.nets}
    rule = _cap_rule(_cap_shelf("50V"), _intent(_rail("+24V", targetVoltage="24V")))
    assert rule.check(model)[0].severity == "INFO"
    outcome = rule.outcomes(model)[0]
    assert outcome.state == "UNKNOWN"
    assert UNPROVEN_BY_NAME in outcome.missing_fact
    assert "+24V" in outcome.message


# ---------------------------------------------------------------------------
# R2: the LDO's dissipation
# ---------------------------------------------------------------------------


def test_the_dissipation_needs_the_declared_current_and_says_where():
    """The drop is a measurement; the load is a requirement nobody wrote.

    The ctrl FOC witness in one shape: an INFO row carrying the headroom, and an
    UNKNOWN row that is the ``intent-missing`` work order for the output rail's
    ``continuousCurrent``.
    """
    rule = _ldo_rule(
        PartLibrary(parts=[_ldo_entry()]),
        _intent(_rail("+24V", targetVoltage="24V"), _rail("3V3", targetVoltage="3.3V")),
    )
    rows = _rows(rule, _ldo_model())
    assert [state for _, state, _ in rows] == ["OK", "UNKNOWN"]
    measurement, missing = rows[0][2], rows[1][2]
    assert "压差 Vin − Vout = 20.7 V" in measurement
    assert "还差电流的声明" in measurement
    assert "intent-missing" in missing
    assert "requirements.rails[net=3V3].continuousCurrent" in missing
    assert "mem://contract.json" in missing, "where to write it is named"
    # The four-state row carries the same sentence as its ``missing_fact``: the
    # report's row and the protocol's reason are one reading, not two.
    fact = rule.outcomes(_ldo_model())[1].missing_fact
    assert "requirements.rails[net=3V3].continuousCurrent 没声明" in fact
    assert fact in missing


def test_a_declared_current_without_a_limit_is_still_only_a_measurement():
    """No ``maxDissipation`` in the shelf ⇒ report P and invent no package limit."""
    rule = _ldo_rule(
        PartLibrary(parts=[_ldo_entry()]),
        _intent(_rail("+24V", targetVoltage="24V"),
                _rail("3V3", targetVoltage="3.3V", continuousCurrent="1A")),
    )
    [(severity, state, message)] = _rows(rule, _ldo_model())
    assert (severity, state) == ("INFO", "OK")
    assert "20.7 V" in message and "1 A = 20.7 W" in message
    assert "货架条目没声明 maxDissipation" in message
    assert "不编封装限值" in message and "不发明降额标准" in message


def test_a_declared_limit_turns_an_overrun_into_a_warn():
    """The limit is a datasheet claim, and its page travels in the message."""
    shelf = PartLibrary(parts=[_ldo_entry(limit_mw=1000.0)])
    over = _ldo_rule(shelf, _intent(
        _rail("+24V", targetVoltage="24V"),
        _rail("3V3", targetVoltage="3.3V", continuousCurrent="1A"),
    ))
    [(severity, state, message)] = _rows(over, _ldo_model())
    assert (severity, state) == ("WARN", "VIOLATION")
    assert "20.7 W vs 货架声明的限值 1000 mW" in message
    assert "超出限值 20.70x" in message
    assert "p.2 (Power Dissipation)" in message, "the citation is quoted"
    assert "不是降额口味" in message

    under = _ldo_rule(shelf, _intent(
        _rail("+24V", targetVoltage="24V"),
        _rail("3V3", targetVoltage="3.3V", continuousCurrent="20mA"),
    ))
    [(severity, state, message)] = _rows(under, _ldo_model())
    assert (severity, state) == ("INFO", "OK")
    assert "在限值内（0.41x）" in message


def test_a_current_the_parsers_cannot_read_is_not_a_declaration():
    """ "N/A", "1.5安" and a bare number are three ways of saying nothing."""
    rule = _ldo_rule(
        PartLibrary(parts=[_ldo_entry()]),
        _intent(_rail("+24V", targetVoltage="24V"),
                _rail("3V3", targetVoltage="3.3V", continuousCurrent="1.5安")),
    )
    rows = _rows(rule, _ldo_model())
    assert [state for _, state, _ in rows] == ["OK", "UNKNOWN"]
    assert "= '1.5安' 不是本工具能读的电流" in rows[1][2]
    assert "要 `5A`、`500mA` 这样的拼法" in rows[1][2]


def test_a_headroom_that_is_not_positive_is_the_other_rules_subject():
    """``path-ldo-dropout`` judges a headroom against the documented dropout —
    a dissipation estimate of zero or less states nothing, so this rule is
    silent rather than reporting a number nobody can act on."""
    rule = _ldo_rule(
        PartLibrary(parts=[_ldo_entry()]),
        _intent(_rail("3V3A", targetVoltage="3.3V"),
                _rail("3V3", targetVoltage="3.3V", continuousCurrent="1A")),
    )
    model = _ldo_model(vin="3V3A", vout="3V3")
    assert rule.check(model) == []
    assert rule.outcomes(model) == []


def test_a_part_the_shelf_does_not_call_an_ldo_is_left_alone():
    """Whether a part *is* an LDO is ``path-ldo-dropout``'s conclusion, from the
    same facts; this rule neither repeats it nor judges a part it cannot name."""
    shelf = PartLibrary(parts=[PartEntry(key="ic.mcu", mpn="LDO1", lcsc="C2",
                                         category="ic.mcu", facts={"ldo": {}})])
    rule = _ldo_rule(shelf, _intent(_rail("+24V", targetVoltage="24V")))
    assert rule.check(_ldo_model()) == []


def test_the_limit_fact_is_optional_page_cited_and_the_schema_stays_closed():
    """090's rule 1, on the one new key: absent means absent, wrong is refused."""
    page = "issue-092 fixture datasheet, p.3, http://example.com/ds.pdf"
    base = {
        "key": "ic.ldo", "lcsc": "C2", "facts_verified": False,
        "facts": {"ldo": {"dropout_max_mv": 400.0, "condition": "Iout=500mA",
                          "provenance": page}},
    }
    without = entry_from_json(base)
    assert "max_dissipation_mw" not in (without.candidate_facts or {})["ldo"], (
        "an unstated limit does not occupy a key"
    )
    with_limit = json.loads(json.dumps(base))
    with_limit["facts"]["ldo"]["max_dissipation_mw"] = {
        "mw": 1000.0,
        "provenance": "issue-092 fixture datasheet, p.2, http://example.com/ds.pdf",
    }
    entry = entry_from_json(with_limit)
    assert entry.candidate_facts["ldo"]["max_dissipation_mw"]["mw"] == 1000.0

    for bad in (
        {"watts": 1.0, "provenance": page},      # unknown key
        {"mw": "1W", "provenance": page},        # a number, not text
        {"mw": 1000.0},                          # no citation
        {"mw": 1000.0, "provenance": "the datasheet"},  # no page
    ):
        payload = json.loads(json.dumps(base))
        payload["facts"]["ldo"]["max_dissipation_mw"] = bad
        with pytest.raises(PartError):
            entry_from_json(payload)


# ---------------------------------------------------------------------------
# the seam: no contract, no subject — and the rules never touch a disk
# ---------------------------------------------------------------------------


def _foc_findings(intent=None):
    model = build_project_model(ROBOT)
    return run_review(model, intent=intent)


def test_without_a_contract_the_rail_rules_have_no_subject_at_all():
    """The rail declarations *are* the subject, so a reading that names no
    contract files nothing from these two rules — which is what keeps 091 A2a's
    zero-movement promise: the rule set grew, the reading did not."""
    shelf = _cap_shelf("50V")
    assert CapVoltageRating(library=shelf).check(_cap_model()) == []
    assert CapVoltageRating(library=shelf).outcomes(_cap_model()) == []
    assert LdoDissipation(library=shelf).check(_ldo_model()) == []
    assert LdoDissipation(library=shelf).outcomes(_ldo_model()) == []

    plain = _foc_findings()
    explicit = _foc_findings(None)
    assert [
        (f.rule_id, f.severity, f.message, f.target) for f in plain
    ] == [
        (f.rule_id, f.severity, f.message, f.target) for f in explicit
    ]
    ids = {f.rule_id for f in plain}
    assert "pwr-cap-voltage-rating" not in ids and "path-ldo-dissipation" not in ids


def test_run_review_hands_the_contract_to_the_three_rules_that_read_one():
    """091 A2a's seam, now with three carriers — and the shared instances stay
    contract-free, because ``BUILTIN_RULES`` outlives any single run."""
    from boardwise.rules.params import ValueMpnMatch

    assert _rules_for(None) is BUILTIN_RULES, "no contract, no copy"
    contract = _intent(_rail("+24V", targetVoltage="24V"))
    rules = _rules_for(contract)
    assert [rule.id for rule in rules] == [rule.id for rule in BUILTIN_RULES]
    carriers = {
        rule.id: rule for rule in rules
        if isinstance(rule, (ValueMpnMatch, CapVoltageRating, LdoDissipation))
    }
    assert set(carriers) == {
        "param-value-mpn-match", "pwr-cap-voltage-rating", "path-ldo-dissipation",
    }
    assert all(rule.intent is contract for rule in carriers.values())
    for rule, template in zip(rules, BUILTIN_RULES):
        if rule.id in carriers:
            assert rule is not template
            continue
        assert rule is template, rule.id
    for template in BUILTIN_RULES:
        if isinstance(template, (ValueMpnMatch, CapVoltageRating, LdoDissipation)):
            assert template.intent is None, "the shared instance kept no answer"


def test_the_rules_read_core_only_and_never_a_disk():
    """006c's layer table: ``rules`` may import ``core`` (and its own layer).

    The contract arrives as an ``IntentSource`` handed in at construction; a
    rule that opened the file itself would be reading an answer nobody chose
    for this reading.
    """
    import boardwise.rules.railratings as railratings

    source = RAILRATINGS_SOURCE.read_text(encoding="utf-8")
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
    for rule in (railratings.CapVoltageRating, railratings.LdoDissipation):
        body = inspect.getsource(rule)
        assert "read_text" not in body and "open(" not in body


# ---------------------------------------------------------------------------
# the real case: the ctrl FOC export and its shipped contract
# ---------------------------------------------------------------------------


def test_the_ctrl_foc_export_against_the_shipped_contract_witnesses_both_rules():
    """092 §三's witness: a real board, the shipped contract, and the rows.

    What the export's own fields say, and why the rows are these:

    * the contract declares rails ``+12V`` / ``VCC`` / ``VCCA`` with no
      ``targetVoltage``, so the voltages come from the drawing's own inference —
      ``+12V`` from the net's name, ``VCC`` from U8's decoded output (12 V and
      3.3 V) — and ``VCCA`` from nothing at all, which is why C17's row is about
      the rail rather than about the capacitor;
    * the capacitors with a catalogued MPN (C7/C10 = 25 V, C13/C14/C16/C18 =
      50 V) are measured and reported as INFO; the ones with no MPN and no shelf
      entry (C1/C5/C6/C8/C9/C15) have no rating anywhere this build reads, so
      each is an UNKNOWN naming the part and its rail — the C-series list the
      task book asks for, plus the three VCC decoupling capacitors that are in
      exactly the same state (unstated is unstated, at 3.3 V as at 12 V);
    * **C4 is not judged**, and that is the scope rather than an omission: its
      two pins sit on ``NET2``/``NET3`` (the gate driver's own pins), which
      neither the contract nor the drawing's inference prices as a rail — R1
      compares a capacitor against *a rail*, and a capacitor on no rail has no
      rail voltage to be compared with;
    * U8 (AMS1117-3.3) drops 12 V − 3.3 V = **8.7 V**, the shelf declares no
      ``maxDissipation``, and the contract declares no ``continuousCurrent`` for
      ``VCC``: one INFO measurement row and one UNKNOWN ``intent-missing`` row.
    """
    contract = di.IntentSource.load(FOC_CONTRACT)
    findings = _foc_findings(contract)

    rating = [f for f in findings if f.rule_id == "pwr-cap-voltage-rating"]
    by_ref = {f.target.component_ref: f.message for f in rating}
    # The capacitors whose rating is nowhere in this build's three reading sites.
    unstated = [f for f in rating if "的耐压读不出" in f.message]
    assert [f.target.component_ref for f in unstated] == [
        "C5", "C6", "C9", "C1", "C15", "C8",
    ]
    for ref in ("C1", "C5", "C6", "C8", "C9", "C15"):
        assert "needs_datasheet 同族点名" in by_ref[ref], ref
        assert f"{ref} 的耐压（所在轨 " in by_ref[ref], ref
    assert "所在轨 +12V = 12 V" in by_ref["C5"]
    assert "所在轨 VCC = 3.3 V" in by_ref["C1"]
    # The capacitor that has a rating but sits on a rail nobody priced.
    assert "所在轨 VCCA 的电压读不出" in by_ref["C17"]
    assert "耐压 50 V" in by_ref["C17"], "the rating that IS known is stated"
    assert "requirements.rails[net=VCCA].targetVoltage" in by_ref["C17"]
    assert str(FOC_CONTRACT) in by_ref["C17"], "the contract is named"
    # The capacitors whose rating the shelf or the code field does state: the
    # ratio is the measurement, and nothing here is a WARN.
    # Rails in the contract's order, capacitors by designator inside each rail
    # (the plain ``sorted`` the rest of the rule pack uses — deterministic, and
    # the reader sees one rail's parts together).
    assert [f.target.component_ref for f in rating] == [
        "C10", "C5", "C6", "C9",          # rail +12V = 12 V
        "C1", "C13", "C14", "C15", "C16", "C18", "C7", "C8",   # rail VCC = 3.3 V
        "C17",                            # rail VCCA — not priced anywhere
    ]
    assert all(f.severity == "INFO" for f in rating), "no WARN on this board"
    assert "耐压 25 V ≥ 所在轨 +12V = 12 V，比值 2.08x" in by_ref["C10"]
    assert "cap.10u_0603 的 Voltage Rating = '25V'" in by_ref["C10"]
    assert "耐压 50 V ≥ 所在轨 VCC = 3.3 V，比值 15.15x" in by_ref["C13"]
    assert "耐压 25 V ≥ 所在轨 VCC = 3.3 V，比值 7.58x" in by_ref["C7"]
    assert "C4" not in by_ref, (
        "C4 sits on NET2/NET3 — no rail, so no rail voltage to compare against"
    )

    dissipation = [f for f in findings if f.rule_id == "path-ldo-dissipation"]
    assert [f.target.component_ref for f in dissipation] == ["U8", "U8"]
    assert all(f.severity == "INFO" for f in dissipation)
    assert "压差 Vin − Vout = 8.7 V" in dissipation[0].message
    assert "intent-missing" in dissipation[1].message
    assert "requirements.rails[net=VCC].continuousCurrent" in dissipation[1].message
    assert str(FOC_CONTRACT) in dissipation[1].message


# ---------------------------------------------------------------------------
# the wiring: `checkup` hands the contract to the rule walk
# ---------------------------------------------------------------------------


def _checkup_args(**overrides) -> argparse.Namespace:
    base = {
        "file": "", "project": "", "instance": "", "out": "checkup",
        "port": None, "intent": "", "library": None,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _checkup_report(tmp_path, name: str, **overrides) -> dict:
    from boardwise.cli import _cmd_checkup

    out = tmp_path / name
    code = _cmd_checkup(_checkup_args(file=str(ROBOT), out=str(out), **overrides))
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return {"exit": code, "report": report}


def test_checkup_hands_the_contract_to_the_rule_walk(monkeypatch, tmp_path):
    """The half A2a left undone: the rules see the contract, not just the report.

    Three claims at once — with ``--intent`` the rail rows are in the report's
    findings; without one (and with ``BOARDWISE_HOME`` pointing at an empty
    directory, so the default slot cannot answer either) they are not; and the
    two readings agree on the exit code and the verdict, because an intent adds
    rows and moves no gate.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    without = _checkup_report(tmp_path, "no-contract")
    with_intent = _checkup_report(tmp_path, "with-contract", intent=str(FOC_CONTRACT))

    def refs(payload):
        return sorted(
            f["target"]["component_ref"]
            for f in payload["report"]["findings"]
            if f["rule_id"] in ("pwr-cap-voltage-rating", "path-ldo-dissipation")
        )

    assert refs(without) == []
    assert refs(with_intent) == ["C1", "C10", "C13", "C14", "C15", "C16", "C17",
                                "C18", "C5", "C6", "C7", "C8", "C9", "U8", "U8"]
    assert with_intent["report"]["summary"]["exitCode"] == without["report"]["summary"]["exitCode"]
    assert with_intent["report"]["completion"]["verdict"] == without["report"]["completion"]["verdict"]
    assert with_intent["exit"] == without["exit"]
    assert with_intent["report"]["schema"] == without["report"]["schema"]


def test_checkup_reads_the_contract_from_its_default_slot(monkeypatch, tmp_path):
    """``~/.boardwise/design-intent/<projectUuid>.json`` answers with no flag.

    The first run reports where that file *would* be (it does not exist, and
    ``checkup`` never creates it); the contract is then placed there and the
    second run — no ``--intent`` anywhere — reads it, both in the report's
    ``intent`` section and in the rule walk.
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    first = _checkup_report(tmp_path, "first")
    slot = Path(first["report"]["intent"]["contract"]["file"])
    assert not slot.exists(), "checkup does not create the contract"
    assert slot.parent.name == "design-intent", slot

    slot.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FOC_CONTRACT, slot)
    second = _checkup_report(tmp_path, "second")
    assert second["report"]["intent"]["contract"]["present"] is True
    rows = [
        f for f in second["report"]["findings"]
        if f["rule_id"] == "path-ldo-dissipation"
    ]
    assert rows, "the default slot reached the rule walk"
    assert "8.7 V" in rows[0]["message"]


def test_the_checkup_wiring_moved_three_steps_and_no_gate():
    """A structural pin on the reorder, because the move is the batch.

    ``_cmd_checkup`` must resolve the shelf, the enumeration and the contract
    **before** it walks the rules — the defect A2a recorded was exactly that the
    walk came first — and it must hand the contract in as an ``IntentSource``.
    """
    source = CLI_SOURCE.read_text(encoding="utf-8")
    body = source.split("def _cmd_checkup(", 1)[1]
    shelf_at = body.index('shelf, shelf_note = _checkup_shelf(args)')
    contract_at = body.index("contract, contract_path, contract_error = _load_intent_contract(")
    walk_at = body.index("for finding in run_review(")
    assert shelf_at < contract_at < walk_at, (shelf_at, contract_at, walk_at)
    assert "intent=intent_source" in body
    assert "intent_source = (" in body
    # ... and the report still reads the same rule set it always did.
    assert {rule.id for rule in BUILTIN_RULES} >= {
        "pwr-cap-voltage-rating", "path-ldo-dissipation",
    }
