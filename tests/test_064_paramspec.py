"""064: the shelf's specs as a **selection criterion**, not a sleeping field.

Issue #64 measured `blocklib/parts.json` carrying specifications that no rule
consumed: `diode.smcj28ca` / `smcj40ca` / `smcj64ca` put their breakdown step in
the MPN, `ic.tplp2981_30dbvr` puts 3.0 V in the part number, and
`ic.stm32h743vit6` carries ten spec fields. This file pins the two selection
rules that consume them, and pins the reconnaissance that decided those two and
not the others.

Four halves, in the order the work went:

* **the reconnaissance** (measured on this build's own shelf, 109 entries) —
  which categories carry a parseable spec at all, so the choice of the two
  subjects is a measurement and not a preference;
* **SEL-1** (`sel-tvs-standoff-rail`): a TVS's stand-off voltage against the
  rail it hangs on, with the acceptance anchor nailed to the real 毕设FOC 1.0.0
  board (D1 = SMCJ28CA on +24 V — OK) and to a synthetic board that hangs a
  lower SMCJ step on the same rail (VIOLATION);
* **SEL-2** (`sel-ldo-fixed-output`): a fixed LDO's output step against the rail
  behind its output pin, including the self-reference refusal that is this
  module's own addition;
* **the wiring**: `BUILTIN_RULES`, `INTENT_RULES`, `NET_MEMBERSHIP_RULES`,
  `RULE_NAMES_ZH` and the README count — every registry that has to name a new
  rule, spelled out so one that is missed is a failing test.

Offline throughout: fixtures are read as files, no bridge, no network. The
UNKNOWN path (the acceptance anchor's third bullet) is built by **removing a
field from a synthetic entry** — never by editing `blocklib/`, which is data.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from boardwise.core import designintent as di
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary, load_parts
from boardwise.engines.review import BUILTIN_RULES, INTENT_RULES, _rules_for
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.i18n import RULE_NAMES_ZH
from boardwise.rules.paramspec import (
    LdoFixedOutput,
    TvsStandoffRail,
    sel_rail_voltage,
)
from boardwise.rules.unproven import NET_MEMBERSHIP_RULES

FIXTURES = Path(__file__).parent / "fixtures"
SHELF = Path("blocklib/parts.json")

#: The acceptance board, 2026-10-07: the only fixture carrying `+24V` and a
#: shelf-backed TVS together. D1 is `SMCJ28CA` on `+24V` — the anchor's OK.
FOC_V1 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

TVS_RULE = "sel-tvs-standoff-rail"
LDO_RULE = "sel-ldo-fixed-output"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _part(designator: str, *, value: str = "", mpn: str = "", pins=()) -> Component:
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


def _tvs_model(rail: str = "+24V", ground: str = "PGND", *, mpn="SMCJ28CA") -> DesignModel:
    """One two-lead TVS across ``rail`` and ``ground`` — SEL-1's subject."""
    return _model_of(
        {"D1": _part("D1", value="", mpn=mpn, pins=[("1", rail), ("2", ground)])},
        {rail: [("D1", "1")], ground: [("D1", "2")]},
    )


def _tvs_entry(
    *,
    standoff: str | None = "28V",
    kind: str | None = "TVS",
    mpn: str = "SMCJ28CA",
    **extra: str,
) -> PartEntry:
    """One shelf TVS, its spec written the way the real catalog writes it.

    ``standoff=None`` **deletes the field** rather than blanking it: the
    acceptance anchor's UNKNOWN path is a spec that is not there, and a blank
    value is a different thing (a listing that says "" is not a listing that
    says nothing).
    """
    params: dict[str, str] = {}
    if standoff is not None:
        params["Reverse Stand-Off Voltage (Vrwm)"] = standoff
    if kind is not None:
        params["Type"] = kind
    params.update(extra)
    return PartEntry(
        key=f"diode.{mpn.lower()}",
        mpn=mpn,
        lcsc="C99999",
        params=params,
        **{k: v for k, v in extra.pop("_meta", {}).items()},
    )


def _shelf(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _ldo_entry(
    *,
    output: str | None = "3.3V",
    kind: str | None = "固定",
    mpn: str = "AMS1117-3.3",
    out_pin: str | None = "2",
) -> PartEntry:
    """One fixed-output LDO on the shelf, with the pin facts SEL-2 needs.

    VIN on pin 1 and the output cap on pin 2 is the AMS1117 shape
    ``ldo_output_pin`` reads; ``out_pin=None`` is the measured shape of
    ``ic.tplp2981_30dbvr``, whose entry carries no ``facts`` at all.
    """
    params: dict[str, str] = {}
    if output is not None:
        params["Output Voltage"] = output
    if kind is not None:
        params["Output Type"] = kind
    facts = None
    if out_pin is not None:
        facts = {
            "supply_pins": [{"pins": ["1"], "name": "VIN",
                             "provenance": "064 fixture datasheet, p.3"}],
            "required_caps": [{"pin": out_pin, "value": "22uF",
                               "provenance": "064 fixture datasheet, p.4"}],
        }
    return PartEntry(
        key="ic.ldo.fixture", mpn=mpn, lcsc="C88888", category="ic.ldo",
        params=params, facts=facts,
    )


def _ldo_model(
    vout: str = "VCC", vin: str = "+12V", *, mpn="AMS1117-3.3"
) -> DesignModel:
    """One 3-lead LDO: VIN on pin 1, output on pin 2.

    ``mpn`` is the part the board names, and it must be the part the shelf
    holds — :func:`boardwise.core.parts.find_facts` is an exact-match reader,
    so a mismatch makes both rules say nothing at all, which is a different
    answer from every one this file pins.
    """
    return _model_of(
        {"U1": _part("U1", mpn=mpn, pins=[("1", vin), ("2", vout), ("3", vout)])},
        {vin: [("U1", "1")], vout: [("U1", "2"), ("U1", "3")]},
    )


def _intent(*rails: di.IntentRail) -> di.IntentSource:
    return di.IntentSource(
        document=di.DesignIntent(rails=list(rails)),
        path="mem://contract.json",
    )


def _rail(net: str, **slots: str) -> di.IntentRail:
    return di.IntentRail(net=net, slots=dict(slots))


def _row_for(rule, model, subject: str):
    """The one row a rule filed about ``subject`` — a missing one fails loudly."""
    rows = [o for o in rule.outcomes(model) if o.subject == subject]
    assert len(rows) == 1, [o.subject for o in rule.outcomes(model)]
    return rows[0]


def _message(rule, model, subject: str) -> str:
    return _row_for(rule, model, subject).message


# ---------------------------------------------------------------------------
# 1: the reconnaissance, pinned
# ---------------------------------------------------------------------------


def test_the_shelf_survey_that_chose_the_two_subjects_is_still_true():
    """064's scope was decided by measuring `parts.json`, so the measurement is
    a test — not a sentence in a docstring that drifts.

    What is pinned is the **shape of the answer**: which categories carry a
    parseable voltage spec at all, and that TVS and the fixed-output LDOs are
    the two families the shelf actually supports. If a later intake fills in
    the MOS or the electrolytic rows, this goes red and the "left for later" list
    in the module docstring has to be re-read — which is the point.
    """
    library = load_parts(SHELF)
    by_key = library.by_key()

    # The two subjects #64 named, with the fields this batch reads.
    assert by_key["diode.smcj28ca"].params["Reverse Stand-Off Voltage (Vrwm)"] == "28V"
    assert by_key["diode.smcj28ca"].params["Type"] == "TVS"
    assert by_key["ic.tplp2981_30dbvr"].params["Output Voltage"] == "3V"
    assert by_key["ic.tplp2981_30dbvr"].params["Output Type"] == "固定"

    # Every TVS step the shelf carries is what its MPN's digits say (the issue's
    # own claim), and each one is a whole number of volts.
    for step in (28, 40, 64):
        entry = by_key[f"diode.smcj{step}ca"]
        assert entry.params["Reverse Stand-Off Voltage (Vrwm)"] == f"{step}V"
        assert str(step) in entry.mpn

    # Coverage, measured per category: a category counts as "carrying a spec"
    # when at least one of its entries names a voltage field this build can
    # read. Two of the three numbers below are the reason the batch is two rules
    # wide and not five.
    def carries_voltage(entry: PartEntry) -> bool:
        return any(
            key in entry.params
            for key in (
                "Reverse Stand-Off Voltage (Vrwm)",
                "Voltage - Breakdown",
                "Clamping Voltage",
                "Output Voltage",
                "Drain to Source Voltage",
                "Voltage Rating",
                "Voltage Rated",
                "Rated Voltage",
                "Voltage - Forward(Vf)",
                "Forward Voltage (VF)",
            )
        )

    coverage: dict[str, list[int]] = {}
    for entry in library.parts:
        bucket = coverage.setdefault(entry.category or "uncategorized", [0, 0])
        bucket[1] += 1
        if carries_voltage(entry):
            bucket[0] += 1
    # ic.ldo: 4/4 (measured 2026-10-07) — the family is fully stated.
    assert coverage["ic.ldo"][0] == coverage["ic.ldo"][1] >= 4
    # fet: 2/2 on Vds/Id — as complete as the LDOs, and **left for later**
    # because no fixture board carries a shelf-backed MOSFET with a rail it
    # could be judged against, so the rule would ship unexercised (see the
    # module's "left for later" list).
    assert coverage["fet"][0] == coverage["fet"][1] == 2
    # ic.ldo is the only category whose voltage coverage is total *and* whose
    # spec is a selection criterion in its own right; the capacitors' ratings
    # are total too, but `pwr-cap-voltage-rating` already consumes that class,
    # which is why this module does not re-add it.
    assert "capacitor" not in {c for c, v in coverage.items() if v[0] == v[1]}


# ---------------------------------------------------------------------------
# 2: SEL-1, a TVS's stand-off voltage against the rail it protects
# ---------------------------------------------------------------------------


def test_the_acceptance_anchor_the_foc_board_d1_is_ok():
    """The anchor, on the real 毕设FOC 1.0.0 board: D1 is `SMCJ28CA` (28 V
    step) on `+24V`, and 28 ≥ 24 — OK, with the margin reported as a ratio and
    no coefficient applied to it.

    This is the "the tool says the reference design is fine" row. A rule that
    cannot say fine about the board that was designed on purpose is measuring
    the wrong number (the same objection that retired the LED current
    computation in `param-led-current`).
    """
    project = build_project_model(str(FOC_V1))
    model = project.boards[0]
    rule = TvsStandoffRail()
    row = _row_for(rule, model, "D1")

    assert row.state == "OK", row.message
    assert "28" in row.message and "24" in row.message
    assert "1.17x" in row.message, "the margin is reported, not judged"
    # The measurement discipline: the OK row rides an INFO finding.
    findings = [f for f in rule.check(model) if f.message == row.message]
    assert [f.severity for f in findings] == ["INFO"]
    # And the other two thirds of a TVS selection are quoted, not judged.
    assert "34.4" in row.message and "45.4" in row.message


def test_a_lower_tvs_step_on_the_same_rail_is_a_violation():
    """The anchor's second half, synthesized: the same board, a `SMCJ18CA`-style
    entry (18 V stand-off) hung on the same `+24V` — the device would conduct on
    the rail's *normal* voltage, so this is a certain over-voltage, not a taste.

    Built as a synthetic shelf entry rather than by editing `blocklib/`: the
    shelf is data, and the pin says so.
    """
    entry = _tvs_entry(standoff="18V", mpn="SMCJ18CA")
    rule = TvsStandoffRail(library=_shelf(entry))
    model = _tvs_model(mpn="SMCJ18CA")
    row = _row_for(rule, model, "D1")

    assert row.state == "VIOLATION", row.message
    assert [f.severity for f in rule.check(model)] == ["WARN"]
    assert "18" in row.message and "24" in row.message
    assert "0.75x" in row.message
    # Both numbers travel in the evidence — a verdict a reader cannot audit is
    # a verdict they have to take on faith.
    assert any("18 V" in e for e in row.evidence)
    assert any("24 V" in e for e in row.evidence)


def test_the_direction_is_the_direction_and_not_its_mirror():
    """Pins the inequality itself: `Vrwm >= rail` passes and `Vrwm < rail`
    fails, on the two entries the shelf really has (28 V and 64 V steps), with
    the rail swept across both sides of each.

    This is the mutation that catches a flipped comparison — the shape where
    the rule passes the parts that are fine and accuses the parts that are
    wrong, which a single (board, part) pair cannot detect.
    """
    for standoff, rail, expected in (
        ("28V", "+24V", "OK"),        # the real pair: passes
        ("18V", "+24V", "VIOLATION"),  # under-rated: fails
        ("64V", "+48V", "OK"),        # over-rated: still passes
        ("28V", "+48V", "VIOLATION"),  # under-rated on a higher bus
        ("28V", "+5V", "OK"),         # generous: passes
    ):
        # The MPN carries the step, as the real SMCJ entries' does, and the
        # board names the same part the shelf does — `find_facts` is an exact
        # match and a mismatch would silently make the rule say nothing.
        entry = _tvs_entry(standoff=standoff, mpn=f"SMCJ{standoff.rstrip('V')}CA")
        rule = TvsStandoffRail(library=_shelf(entry))
        row = _row_for(rule, _tvs_model(rail=rail, mpn=entry.mpn), "D1")
        assert row.state == expected, (standoff, rail, row.message)


def test_a_contract_rail_wins_over_the_drawings_own_name():
    """The contract is the requirement and the net name is the drawing. When
    they disagree, this rule prices the bus from the contract and says so —
    the same precedence `pwr-cap-voltage-rating` uses, for the same reason
    (otherwise the board is being compared with itself).
    """
    rule = TvsStandoffRail(
        library=_shelf(_tvs_entry(standoff="18V")), intent=_intent(_rail("+24V", targetVoltage="24V"))
    )
    # The drawing alone: `+24V` parses to 24 V, so the verdict is the same —
    # which is why the contract's voice has to be visible in the message.
    row = _row_for(rule, _tvs_model(), "D1")
    assert row.state == "VIOLATION"
    assert any("24 V" in e for e in row.evidence)

    # A net that names nothing, priced only by the contract.
    rule = TvsStandoffRail(
        library=_shelf(_tvs_entry(standoff="28V")), intent=_intent(_rail("VBUS", targetVoltage="24V"))
    )
    model = _model_of(
        {"D1": _part("D1", mpn="SMCJ28CA", pins=[("1", "VBUS"), ("2", "PGND")])},
        {"VBUS": [("D1", "1")], "PGND": [("D1", "2")]},
    )
    row = _row_for(rule, model, "D1")
    assert row.state == "OK", row.message
    assert "targetVoltage" in " ".join(row.evidence)


def test_a_tvs_with_no_spec_field_is_unknown_naming_the_field():
    """The acceptance anchor's UNKNOWN path: the entry is on the shelf and the
    board is right there, but the spec is missing — so the row is UNKNOWN and
    names **which** fact is absent. Never a pass, never a guess.
    """
    entry = _tvs_entry(standoff=None)
    rule = TvsStandoffRail(library=_shelf(entry))
    row = _row_for(rule, _tvs_model(), "D1")

    assert row.state == "UNKNOWN", row.message
    assert "Vrwm" in row.missing_fact
    assert "Reverse Stand-Off Voltage (Vrwm)" in row.message
    # An UNKNOWN is filed as INFO: it is a work order, not a defect.
    assert [f.severity for f in rule.check(_tvs_model())] == ["INFO"]


def test_a_spec_the_reader_cannot_parse_is_unknown_not_a_guess():
    """`"-"` is this catalog's placeholder for "not stated", and a reading of
    it as a voltage would be a number nobody wrote. A *range* (`3V3~5V`) is
    two figures, not one rating — the same refusal, for the same reason.
    """
    for raw in ("-", "3V3~5V", ""):
        entry = _tvs_entry(standoff=raw)
        rule = TvsStandoffRail(library=_shelf(entry))
        row = _row_for(rule, _tvs_model(), "D1")
        assert row.state == "UNKNOWN", (raw, row.message)


def test_a_diode_that_names_no_type_is_unknown_rather_than_not_a_tvs():
    """Three answers, three states: `Type: TVS` is a subject, `Type: 整流` is
    NOT_APPLICABLE, and **no `Type` at all** is UNKNOWN — because "the listing
    did not say" is not "it is not a TVS". The same three-way answer
    `_category_state` gives the IC rules.
    """
    not_a_tvs = TvsStandoffRail(library=_shelf(_tvs_entry(kind="整流")))
    row = _row_for(not_a_tvs, _tvs_model(), "D1")
    assert row.state == "NOT_APPLICABLE"
    assert not_a_tvs.check(_tvs_model()) == []

    untyped = TvsStandoffRail(library=_shelf(_tvs_entry(kind=None)))
    row = _row_for(untyped, _tvs_model(), "D1")
    assert row.state == "UNKNOWN"
    assert "Type" in row.missing_fact


def test_a_tvs_on_several_non_ground_nets_says_it_cannot_tell_which_rail():
    """A three-channel array sits on three buses, and "which rail does it
    protect" is a question this rule has no right to answer. UNKNOWN, named.
    """
    model = _model_of(
        {"D1": _part("D1", mpn="SMCJ28CA", pins=[("1", "+24V"), ("2", "+12V"), ("3", "PGND")])},
        {"+24V": [("D1", "1")], "+12V": [("D1", "2")], "PGND": [("D1", "3")]},
    )
    rule = TvsStandoffRail(library=_shelf(_tvs_entry()))
    row = _row_for(rule, model, "D1")
    assert row.state == "UNKNOWN"
    assert "+24V" in row.message and "+12V" in row.message


def test_a_rail_no_source_prices_is_unknown_naming_the_rail():
    """A rail nobody prices is not a zero-volt rail. The row names the rail and
    the two places a voltage could come from — the contract slot and the net
    name — which are two different fixes.
    """
    model = _model_of(
        {"D1": _part("D1", mpn="SMCJ28CA", pins=[("1", "VOUTB"), ("2", "PGND")])},
        {"VOUTB": [("D1", "1")], "PGND": [("D1", "2")]},
    )
    rule = TvsStandoffRail(library=_shelf(_tvs_entry()))
    row = _row_for(rule, model, "D1")
    assert row.state == "UNKNOWN"
    assert "VOUTB" in row.message
    assert "VOUTB" in row.missing_fact


def test_the_rule_says_nothing_about_parts_that_are_not_on_the_shelf():
    """A diode-designator part with no entry has no spec to read. `path-ldo-dropout`
    skips the same way, and one row per unlisted part would drown the real ones.
    """
    rule = TvsStandoffRail(library=_shelf())
    assert rule.outcomes(_tvs_model()) == []
    assert rule.check(_tvs_model()) == []


def test_the_real_tvs_entry_judged_by_itself_agrees_with_the_board():
    """The measured entry — the shelf's own `diode.smcj28ca`, read through the
    real `load_parts` path, not a synthetic stand-in — on the real board.

    Two readings of the same fact have to agree: if the synthetic entry above
    and the repository's own data drift apart, one of the two is fiction.
    """
    rule = TvsStandoffRail(library=load_parts(SHELF))
    row = _row_for(rule, build_project_model(str(FOC_V1)).boards[0], "D1")
    assert row.state == "OK"
    assert "1.17x" in row.message


# ---------------------------------------------------------------------------
# 3: SEL-2, a fixed LDO's output step against the rail it feeds
# ---------------------------------------------------------------------------


def test_a_fixed_ldo_whose_step_matches_its_rail_is_ok():
    """The pin case: AMS1117-3.3 feeding a rail the board names `+3.3V`. Two
    documents, two numbers, and they agree — OK, both quoted.
    """
    rule = LdoFixedOutput(library=_shelf(_ldo_entry()))
    model = _model_of(
        {"U1": _part("U1", mpn="AMS1117-3.3", pins=[("1", "+12V"), ("2", "+3.3V")])},
        {"+12V": [("U1", "1")], "+3.3V": [("U1", "2")]},
    )
    row = _row_for(rule, model, "U1")
    assert row.state == "OK", row.message
    assert "3.3" in row.message
    assert [f.severity for f in rule.check(model)] == ["INFO"]


def test_the_wrong_step_for_the_rail_is_a_violation_that_repairs_neither_side():
    """`TPLP2981-30DBVR` is the issue's own example — the `30` is 3.0 V. Hung
    on a 3.3 V rail the two documents disagree, and 052 §2.1's ruling holds
    here for the same question: *which side is wrong* is a design decision, so
    the row names both repairs and repairs neither.
    """
    entry = _ldo_entry(output="3V", mpn="TPLP2981-30DBVR")
    rule = LdoFixedOutput(library=_shelf(entry))
    model = _model_of(
        {"U1": _part("U1", mpn="TPLP2981-30DBVR", pins=[("1", "+5V"), ("2", "+3.3V")])},
        {"+5V": [("U1", "1")], "+3.3V": [("U1", "2")]},
    )
    row = _row_for(rule, model, "U1")
    assert row.state == "VIOLATION", row.message
    assert [f.severity for f in rule.check(model)] == ["WARN"]
    assert "-0.3" in row.message or "0.3" in row.message
    # The finding carries its subject's identity but proposes no direction.
    findings = rule.check(model)
    assert findings[0].target.component_ref == "U1"
    assert findings[0].target.suggested_after == ""
    assert findings[0].target.expected_before == ""


def test_the_rule_refuses_to_check_a_part_against_a_number_decoded_from_its_own_name():
    """This module's own addition, and the reason `sel_rail_voltage` exists.

    `infer_net_domains` prices an LDO's output rail from the LDO's own MPN
    suffix. Judging "is AMS1117-3.3's fixed output 3.3 V" against a rail priced
    by decoding `AMS1117-3.3` would announce the part correct on the strength of
    the very string under audit. So that reading is not evidence about itself:
    the row is UNKNOWN and names the contract slot that would settle it.

    This is what the three measured boards actually produce (§5 below pins it).
    """
    rule = LdoFixedOutput(library=_shelf(_ldo_entry()))
    model = _ldo_model(vout="VCC")
    row = _row_for(rule, model, "U1")
    assert row.state == "UNKNOWN", row.message
    assert "U1" in row.message
    assert "targetVoltage" in row.message
    assert "VCC" in row.missing_fact


def test_a_rail_priced_by_another_part_is_evidence_and_is_accepted():
    """The other half of the self-reference rule, and it is not a blanket
    refusal: a rail priced by a **different** LDO, or written in the net name,
    or declared in the contract, is independent evidence and the rule judges.

    (b) is the one that needs setting up: U1's output rail ``VCC`` is priced by
    U9's output pin, and the reader has to accept that reading for U1 — U9 is
    not the part under audit. U9's entry states its own 3.3 V, so the domain
    inference puts a price on the net from U9's side, never mentioning U1.
    """
    # (a) the net name says it: `+3.3V` belongs to no part.
    rule = LdoFixedOutput(library=_shelf(_ldo_entry()))
    named = _model_of(
        {"U1": _part("U1", mpn="AMS1117-3.3", pins=[("1", "+12V"), ("2", "+3.3V")])},
        {"+12V": [("U1", "1")], "+3.3V": [("U1", "2")]},
    )
    assert _row_for(rule, named, "U1").state == "OK"

    # (b) another regulator prices the rail, and U1 is judged against it. Two
    # distinct entries (distinct MPNs, distinct C-numbers) or `find_facts` by
    # MPN would resolve both `U1` and `U9` to one of them.
    shelf = _shelf(
        _ldo_entry(mpn="AMS1117-3.3", out_pin="2"),
        PartEntry(
            key="ic.ldo.u9", mpn="U9-LDO", lcsc="C77777", category="ic.ldo",
            params={"Output Voltage": "3.3V", "Output Type": "固定"},
            facts={
                "supply_pins": [{"pins": ["1"], "name": "VIN", "provenance": "064 fixture, p.3"}],
                "required_caps": [{"pin": "9", "value": "1uF", "provenance": "064 fixture, p.4"}],
            },
        ),
    )
    two_ldos = _model_of(
        {
            "U1": _part("U1", mpn="AMS1117-3.3", pins=[("1", "+12V"), ("2", "VCC")]),
            "U9": _part("U9", mpn="U9-LDO", pins=[("1", "+12V"), ("2", "VCC"), ("9", "VCC")]),
        },
        {"+12V": [("U1", "1"), ("U9", "1")], "VCC": [("U1", "2"), ("U9", "2"), ("U9", "9")]},
    )
    row = _row_for(LdoFixedOutput(library=shelf), two_ldos, "U1")
    assert row.state == "OK", row.message
    assert any("U9" in e for e in row.evidence), (
        "the rail's price is quoted so a reader can see whose reading it was"
    )

    # (c) the contract declares it, which is what the missing fact asks for.
    declared = LdoFixedOutput(
        library=_shelf(_ldo_entry()), intent=_intent(_rail("VCC", targetVoltage="3.3V"))
    )
    row = _row_for(declared, _ldo_model(vout="VCC"), "U1")
    assert row.state == "OK", row.message


def test_an_ldo_whose_entry_names_no_output_pin_is_unknown_naming_the_pin():
    """The measured `ic.tplp2981_30dbvr`: the catalog states 3 V, the shelf entry
    carries **no facts at all**, so which pin that 3 V leaves by is the missing
    fact. The rule does not guess pin 2 out of a SOT-23-5 pinout.
    """
    entry = _ldo_entry(output="3V", mpn="TPLP2981-30DBVR", out_pin=None)
    rule = LdoFixedOutput(library=_shelf(entry))
    # The board must name the part the shelf has: `find_facts` is an exact
    # match, and a mismatch would make the rule say nothing at all — which is
    # a different (and untested) answer from the one this test is about.
    row = _row_for(rule, _ldo_model(mpn="TPLP2981-30DBVR"), "U1")
    assert row.state == "UNKNOWN"
    assert "输出脚" in row.missing_fact


def test_an_ldo_with_no_output_voltage_anywhere_is_unknown_naming_the_spec():
    """The acceptance anchor's UNKNOWN path, on the LDO side: the entry is on
    the shelf with no `Output Voltage`, no `ldo.fixed_output` fact, and no
    suffix the decoder will read. All three readings refused → UNKNOWN.

    The MPN matters here and is not incidental: with ``AMS1117-3.3`` the third
    reading *does* answer (its `-3.3` tail is one of the two shapes
    :func:`boardwise.core.power_domains.ldo_output_voltage` reads), so the row
    would be an OK and this test would pin the wrong thing. ``TPLP2981-30DBVR``
    is the measured part that answers None at every door — its `30` is a
    voltage to a human and a packaging code to the reader.
    """
    entry = _ldo_entry(output=None, kind=None, mpn="TPLP2981-30DBVR")
    rule = LdoFixedOutput(library=_shelf(entry))
    row = _row_for(rule, _ldo_model(mpn="TPLP2981-30DBVR"), "U1")
    assert row.state == "UNKNOWN", row.message
    assert "固定输出电压" in row.missing_fact
    assert "Output Voltage" in row.message


def test_an_adjustable_ldo_is_not_a_subject_and_a_non_ldo_is_silent():
    """An adjustable regulator's output is a divider's job, and a part whose
    category says it is not an LDO is another rule's row entirely.
    """
    adjustable = LdoFixedOutput(library=_shelf(_ldo_entry(kind="可调")))
    row = _row_for(adjustable, _ldo_model(), "U1")
    assert row.state == "NOT_APPLICABLE"
    assert adjustable.check(_ldo_model()) == []

    mcu = PartEntry(key="ic.mcu.x", mpn="STM32H743VIT6", lcsc="C1", category="ic.mcu")
    quiet = LdoFixedOutput(library=_shelf(mcu))
    assert quiet.outcomes(_ldo_model()) == []


def test_a_cited_ldo_fixed_output_fact_outranks_the_catalog_field():
    """Issue #17's curated fact, when one exists, is the strongest reading —
    and this build's shelf declares none, which is why every measured LDO falls
    to step 2 (the `Output Voltage` field).
    """
    entry = _ldo_entry(output="3.3V")
    assert entry.facts is not None
    entry.facts["ldo"] = {
        "fixed_output": {"volts": 3.3, "provenance": "064 fixture datasheet, p.1"}
    }
    rule = LdoFixedOutput(library=_shelf(entry))
    row = _row_for(rule, _ldo_model(vout="+3.3V"), "U1")
    assert row.state == "OK"
    assert any("ldo.fixed_output" in e for e in row.evidence)


def test_the_real_ldo_entries_produce_the_measured_rows():
    """The three measured boards, on the repository's own shelf.

    What they produce is the honest answer, not a clean one: FOC's `U5` and
    ROBOT's `U8` are both UNKNOWN **because** their rails are priced from their
    own part numbers (the self-reference refusal), and 药箱's `U11` likewise.
    A future intake that adds `ldo.fixed_output` facts or a contract turns each
    of those into a verdict; until then they are work orders with an address,
    and that is what this pins.
    """
    for fixture, subject in ((FOC_V1, "U5"), (ROBOT, "U8"), (PILLBOX, "U11")):
        rule = LdoFixedOutput(library=load_parts(SHELF))
        row = _row_for(rule, build_project_model(str(fixture)).boards[0], subject)
        assert row.state == "UNKNOWN", (fixture.name, subject, row.message)
        assert subject in row.missing_fact or "轨压" in row.missing_fact


def test_llc_reports_neither_rule_because_it_carries_neither_part():
    """The third measured board: no shelf-backed TVS and no shelf-backed LDO,
    so two rules that read the shelf have nothing to say. Silence is the right
    answer here, and it is pinned so a future rule does not start guessing.
    """
    project = build_project_model(str(LLC))
    model = project.boards[0]
    for rule in (TvsStandoffRail(library=load_parts(SHELF)), LdoFixedOutput(library=load_parts(SHELF))):
        assert rule.outcomes(model) == [], rule.id


# ---------------------------------------------------------------------------
# 4: the wiring — every registry that has to name a new rule
# ---------------------------------------------------------------------------


def test_both_rules_are_builtins_and_22_is_the_count_now():
    """The structural pin. 20 since 094 A3b added `arch-sense-bias-closure`;
    **22 since #64 added the two selection rules** — the specs the shelf was
    already carrying and nothing was consuming.

    Two rules, not five: the reconnaissance (§1) measured the MOS and
    electrolytic families as spec-complete too, but neither has a board in the
    fixture set to exercise a verdict against, so shipping them would mean
    shipping rules whose only tests are synthetic.
    """
    ids = [rule.id for rule in BUILTIN_RULES]
    assert TVS_RULE in ids and LDO_RULE in ids
    assert len(ids) == 22


def test_both_rules_take_the_contract_at_construction_and_are_carriers():
    """Both are in `INTENT_RULES`, for the leak reason rather than a
    subject reason: their subject is a part on the board, so they still run
    without a contract — the contract only moves *which* document the rail's
    voltage comes from.
    """
    assert TvsStandoffRail in INTENT_RULES and LdoFixedOutput in INTENT_RULES
    contract = _intent(_rail("+24V", targetVoltage="24V"))
    rules = _rules_for(contract)
    carriers = {
        rule.id: rule for rule in rules
        if isinstance(rule, (TvsStandoffRail, LdoFixedOutput))
    }
    assert set(carriers) == {TVS_RULE, LDO_RULE}
    assert all(rule.intent is contract for rule in carriers.values())
    # The module-level instances stay contract-free: BUILTIN_RULES outlives
    # one run, and a rule that kept this reading's answer would leak it.
    assert all(
        rule.intent is None
        for rule in BUILTIN_RULES
        if isinstance(rule, (TvsStandoffRail, LdoFixedOutput))
    )
    # And the ids line up under the seam.
    assert [rule.id for rule in rules] == [rule.id for rule in BUILTIN_RULES]


def test_both_rules_are_net_membership_rules():
    """Both read a net's voltage through the domain inference, so a rail welded
    by name (#19) would hand them another board's bus. Spelled out here because
    `test_093` asserts the registry's ids are all real rules, not that a new
    rule *joined* it.
    """
    assert TVS_RULE in NET_MEMBERSHIP_RULES
    assert LDO_RULE in NET_MEMBERSHIP_RULES
    assert {TVS_RULE, LDO_RULE} <= {rule.id for rule in BUILTIN_RULES}


def test_both_rules_have_chinese_names():
    """`test_018`'s pin is bidirectional: an id with no name fails, and so does
    a name with no id. Named here so adding the rule without the name is red
    where the reader looks.
    """
    assert RULE_NAMES_ZH[TVS_RULE]
    assert RULE_NAMES_ZH[LDO_RULE]


def test_a_welded_rail_is_unknown_not_a_pass():
    """The issue #19 refusal, end to end on one of the new rules: a net the
    merge could not prove gets UNKNOWN, never OK.
    """
    from boardwise.rules.unproven import UNPROVEN_BY_NAME

    model = _tvs_model()
    model.unproven_nets = {"+24V": ("page-a", "page-b")}  # type: ignore[assignment]
    rule = TvsStandoffRail(library=_shelf(_tvs_entry()))
    row = _row_for(rule, model, "D1")
    assert row.state == "UNKNOWN"
    assert UNPROVEN_BY_NAME in row.missing_fact


# ---------------------------------------------------------------------------
# 5: the reader itself
# ---------------------------------------------------------------------------


def test_sel_rail_voltage_prefers_the_contract_then_the_name_then_the_drawing():
    """The precedence, pinned on its own so a reordering is caught here rather
    than through a verdict that happens to come out the same.
    """
    from boardwise.core.power_domains import infer_net_domains

    library = _shelf()
    model = _model_of({}, {"+5V": [], "VBUS": []})
    guesses = infer_net_domains(model, library)

    # contract first
    assert sel_rail_voltage(
        _intent(_rail("+5V", targetVoltage="5V")), guesses, "+5V"
    )[:2] == (5.0, "合同 requirements.rails[net=+5V].targetVoltage = '5V'")
    # then the net name
    assert sel_rail_voltage(None, guesses, "+5V")[:2] == (5.0, "net name '+5V'")
    # and nothing at all is a refusal that names both places an answer could go
    volts, source, why = sel_rail_voltage(None, guesses, "VBUS")
    assert volts is None and source == ""
    assert "VBUS" in why
    volts, _s, why = sel_rail_voltage(_intent(), guesses, "VBUS")
    assert volts is None and "targetVoltage" in why


def test_sel_rail_voltage_refuses_only_its_own_subjects_reading():
    """The self-reference check keys on the designator, so it fires for the
    part being judged and not for a neighbour: ``U9 AMS1117-3.3 output`` prices
    the rail for **U8** without being evidence about U8 either — which is the
    case a "refuse every decode" implementation would get wrong by refusing
    every answer.
    """
    from boardwise.core.power_domains import infer_net_domains

    shelf = _shelf(
        _ldo_entry(mpn="LDO-A"),
        PartEntry(
            key="ic.ldo.b", mpn="LDO-B", lcsc="C66666", category="ic.ldo",
            facts={"supply_pins": [{"pins": ["1"], "name": "VIN", "provenance": "064 fixture, p.3"}],
                   "required_caps": [{"pin": "2", "value": "1uF", "provenance": "064 fixture, p.4"}]},
        ),
    )
    model = _model_of(
        {
            "U8": _part("U8", mpn="LDO-A", pins=[("1", "+12V"), ("2", "VCC")]),
            "U9": _part("U9", mpn="LDO-B", pins=[("1", "+12V"), ("2", "VCC")]),
        },
        {"+12V": [("U8", "1"), ("U9", "1")], "VCC": [("U8", "2"), ("U9", "2")]},
    )
    guesses = infer_net_domains(model, shelf)
    # `LDO-A` decodes to nothing and `LDO-B` neither, so this net has no price
    # at all here; the point of the pin is that the check is keyed on the
    # subject string, which is what the two rules pass in.
    assert sel_rail_voltage(None, guesses, "VCC", subject="U8")[0] is None
    assert "U8" not in (sel_rail_voltage(None, guesses, "VCC", subject="U8")[2] or "")


def test_the_readers_refuse_what_they_cannot_measure():
    """`parse_voltage_volts` is the codebase's shared reader for a stated
    voltage and this module goes through it rather than growing a second one:
    a value it refuses is a value this rule has no reading for.
    """
    from boardwise.core.values import parse_voltage_volts

    from boardwise.rules.paramspec import _read_volts

    assert _read_volts("28V") == 28.0
    assert _read_volts("3.3V") == 3.3
    for raw in ("-", "28 V ~ 60 V", "", "1kΩ"):
        assert _read_volts(raw) is None, raw
        assert parse_voltage_volts(raw) is None or raw == "1kΩ"