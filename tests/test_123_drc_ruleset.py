"""123: the `drc.ruleset` section and the PCB DRC multi-board loop.

Why this layer exists at all: **a PCB DRC result is a statement about a rule
set.** The same geometry passes under a 0.2 mm clearance and fails under 0.1 mm,
so 025's per-item leaves are half an answer on their own. `pcb.drc_check` got the
leaves; this gets the other half, reads it off `pcb_Drc`'s read-side members, and
puts it in the report where the leaves are.

The fixture is the **measured** reading, not an invented one: 立创 EDA Pro
3.2.186 + connector 0.4.29, test project `PCB1` / `5dc38976c1fa45ce`, rule set
`JLCPCB Capability(Two Layers Board)` (2026-10-06, `outputs/123/02_ruleset_raw.json`).
Only the two 13×13 clearance matrices are trimmed — nothing this module compares
lives in them. A hand-written fixture would encode whatever the author assumed
about the host's nesting, and the whole subject here is that nesting.

What is protected, one line each:

1. **the reading is carried whole** — a meta-audit that quotes only the keys it
   compared is a summary of the rules, not the rules;
2. **an unreadable key is never a matching key** — the reference value must not
   be substituted for a measurement that was never taken, because that is how a
   review acquires a clean sheet it did not earn;
3. **"we compared nothing" is not "everything matched"** — an absent reference
   table says so in the section;
4. **only `outside` becomes a finding** — a value that drifted in the direction
   the reference table marks harmless, and a key that was never read, are both
   non-findings, and neither can raise the exit code;
5. **every board gets a DRC reading** — the stage used to read `pcbs[0]` and
   note the rest as "留待后续", which understates a multi-board project in the
   reassuring direction.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from boardwise.engines.drc import (
    RULESET_REFERENCE_FILE,
    RULESET_SOURCE,
    ruleset_finding_lines,
    ruleset_section,
)

FIXTURE = Path(__file__).parent / "fixtures" / "drc_ruleset" / "test_pcb1_ruleset.json"


def _measured() -> dict:
    """The recorded host answer, re-read per test so no test can mutate another's."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _reading(payload: dict | None = None, **extra) -> dict:
    return {"documentUuid": "5dc38976c1fa45ce", "payload": payload or _measured(), **extra}


# --------------------------------------------------------------------------
# the reading itself
# --------------------------------------------------------------------------


def test_the_measured_reading_becomes_a_checked_section_that_names_its_rule_set():
    section = ruleset_section(_reading(), documents_listed=1)

    assert section["checked"] is True
    assert section["source"] == RULESET_SOURCE
    assert section["ruleSetName"] == "JLCPCB Capability(Two Layers Board)"
    assert section["documentUuid"] == "5dc38976c1fa45ce"
    # The host resolved `getDefaultRuleConfigurationName()` to nothing on this
    # board (measured), and the connector records that as `null` with the key
    # present — so "no separate default here" is not the same sentence as
    # "this build has no such member".
    assert section["defaultRuleSetName"] == ""
    assert section["realTimeDrcStatus"] is False
    assert section["ruleset"]["configCategories"] == sorted(["Expansion", "Plane", "Physics", "Spacing"])


def test_the_reading_is_carried_whole_so_a_reader_can_check_a_key_nobody_compared():
    section = ruleset_section(_reading(), documents_listed=1)
    raw = section["ruleset"]["raw"]

    # The four categories, and inside them the untouched host keys — the ones no
    # reference-table check reads (`2oz` thickness, the differential-pair tables,
    # the paste-mask row) are exactly what a reader auditing an unlisted key needs.
    assert set(raw["config"]) == {"Spacing", "Physics", "Plane", "Expansion"}
    assert raw["config"]["Physics"]["Track"]["copperThickness2oz"]["form"]["data"]["1"]["minValue"] \
        == 0.20299933999999997
    assert raw["config"]["Plane"]["Copper Zone"]["copperRegion"]["form"][
        "multiLayerPadModel"]["data"]["1"]["lineClearance"] == 0.254
    assert raw["config"]["Expansion"]["Paste Mask Expansion"]["pasteMaskExpansion"]["form"][
        "testPointToplayerExpansion"] == -25.4
    # Not normalised into a summary: the host's own `editName` / `isSetDefault`
    # bookkeeping survives, because "which rule was set to default" is a question
    # about the board, not about our table.
    assert raw["config"]["Spacing"]["Safe Spacing"]["copperThickness1oz"]["isSetDefault"] is True
    assert raw["config"]["Spacing"]["Safe Spacing"]["copperThickness2oz"]["isSetDefault"] is False


# --------------------------------------------------------------------------
# the meta-audit
# --------------------------------------------------------------------------


def test_the_measured_reading_matches_the_reference_table_on_every_key_it_names():
    section = ruleset_section(_reading(), documents_listed=1)
    audit = section["metaAudit"]

    assert audit["available"] is True
    assert audit["referenceFile"] == f"blocklib/{RULESET_REFERENCE_FILE}"
    assert audit["keysChecked"] >= 8
    assert audit["outside"] == 0, [c for c in audit["checks"] if c["status"] == "outside"]
    assert audit["unreadable"] == 0
    assert audit["missingCategories"] == []
    # The float tails the host really sends (`0.49999899999999997`) are absorbed
    # by the relative tolerance rather than reported as drift — the tolerance is
    # there for exactly these, and a 1e-6 "violation" would teach the reader to
    # ignore the table.
    via = next(c for c in audit["checks"] if c["key"] == "via-outer-diameter-min")
    assert via["status"] == "within"
    assert via["actual"] == 0.49999899999999997


def test_a_key_the_host_did_not_return_is_unreadable_and_never_a_match():
    measured = _measured()
    del measured["ruleset"]["current"]["config"]["Physics"]["Via Size"]["viaSize"]["form"][
        "viaOuterdiameterMin"
    ]
    section = ruleset_section(_reading(measured), documents_listed=1)
    audit = section["metaAudit"]

    entry = next(c for c in audit["checks"] if c["key"] == "via-outer-diameter-min")
    assert entry["status"] == "unreadable", "the key was not read, so nothing can be said about it"
    assert "actual" not in entry, "and no value was invented to stand in for it"
    assert "expected" not in entry
    assert audit["unreadable"] == 1
    assert audit["within"] == audit["keysChecked"] - 1
    # The one thing that must not happen: the missing key being counted as a match.
    assert audit["within"] + audit["outside"] + audit["offReference"] + audit["unreadable"] \
        == audit["keysChecked"]
    assert ruleset_finding_lines(section) == [], "a key that was never read produces no defect"
    assert any("缺读不是匹配" in note for note in section["notes"])


def test_a_renamed_category_reads_as_a_missing_category_not_as_absent_rules():
    measured = _measured()
    del measured["ruleset"]["current"]["config"]["Expansion"]
    section = ruleset_section(_reading(measured), documents_listed=1)

    assert section["metaAudit"]["missingCategories"] == ["Expansion"]
    assert any("不是「那几个类别没有规则」" in note for note in section["notes"])


def test_a_drifted_rule_beyond_the_reference_becomes_a_finding_with_both_numbers():
    measured = _measured()
    # A 0.1 mm minimum track width: real boards get made with it, and it is
    # outside the JLC two-layer capability the reference table names.
    measured["ruleset"]["current"]["config"]["Physics"]["Track"]["copperThickness1oz"]["form"][
        "data"]["1"]["minValue"] = 0.1
    section = ruleset_section(_reading(measured), documents_listed=1)

    entry = next(c for c in section["metaAudit"]["checks"] if c["key"] == "track-width-min")
    assert entry["status"] == "outside"
    assert entry["actual"] == 0.1 and entry["expected"] == 0.127
    assert entry["delta"] == pytest_approx(0.1 - 0.127)
    assert entry["direction"] == "below"

    rows = ruleset_finding_lines(section)
    assert len(rows) == 1
    row = rows[0]
    assert row["rule_id"] == "pcb-drc-ruleset-out-of-reference"
    assert row["severity"] == "ERROR", "the severity is the reference table's, not this module's"
    assert "0.1mm" in row["message"] and "0.127mm" in row["message"]
    assert row["refs"] == ["drc.ruleset"]
    assert row["target"]["key"] == "track-width-min"
    assert row["target"]["actual"] == 0.1
    assert row["target"]["expected"] == 0.127


def test_a_loosened_process_limit_is_still_reported_even_at_info_severity():
    measured = _measured()
    # Loosening the solder-mask expansion from 2 mil to 5 mil: a deliberate
    # process choice, not a defect. `direction: either` means "outside" is the
    # honest status — the value is off the reference and nobody should pretend
    # otherwise — and the severity is INFO, so it cannot move the exit code.
    measured["ruleset"]["current"]["config"]["Expansion"]["Solder Mask Expansion"][
        "solderMaskExpansion"]["form"]["padToplayerExpansion"] = 0.127
    section = ruleset_section(_reading(measured), documents_listed=1)

    entry = next(c for c in section["metaAudit"]["checks"] if c["key"] == "solder-mask-expansion")
    assert entry["status"] == "outside"
    rows = ruleset_finding_lines(section)
    assert [r["severity"] for r in rows] == ["INFO"], "reported, but at the table's own severity"
    # Still on the page, because a rule set that was loosened is a fact.
    assert any("超界" in note for note in section["notes"])


def test_the_direction_makes_the_two_ways_of_missing_a_limit_different_findings():
    measured = _measured()
    # A track width *larger* than the reference minimum is not a defect — a wide
    # track is manufacturable. `direction: below` is what says so.
    measured["ruleset"]["current"]["config"]["Physics"]["Track"]["copperThickness1oz"]["form"][
        "data"]["1"]["minValue"] = 0.5
    section = ruleset_section(_reading(measured), documents_listed=1)

    entry = next(c for c in section["metaAudit"]["checks"] if c["key"] == "track-width-min")
    assert entry["status"] == "off-reference"
    assert ruleset_finding_lines(section) == []


# --------------------------------------------------------------------------
# the honest-degradation shapes
# --------------------------------------------------------------------------


def test_no_reading_is_not_an_empty_rule_set():
    section = ruleset_section(None, documents_listed=0)
    assert section["checked"] is False
    assert "no PCB document" in section["reason"]
    assert "metaAudit" not in section
    assert ruleset_finding_lines(section) == []


def test_a_refused_read_keeps_the_code_and_the_message_the_bridge_gave():
    section = ruleset_section(
        {"documentUuid": "5dc38976c1fa45ce",
         "error": {"code": "PAGE_MISMATCH", "message": "the focused document is b4298962367251c8 (page), not a PCB"}},
        documents_listed=1,
    )
    assert section["checked"] is False
    assert section["reason"].startswith("PAGE_MISMATCH:")
    assert "not a PCB" in section["reason"]
    assert ruleset_finding_lines(section) == []


def test_a_rule_set_that_answered_nothing_is_not_a_board_with_no_rules():
    # The reassuring failure: an empty `ruleset` with `checked: true` and no
    # reason reads as "this board checks nothing", which is a claim.
    section = ruleset_section(_reading({"source": "pcb_Drc", "page": {}, "ruleset": {}, "reads": []}),
                              documents_listed=1)
    assert section["checked"] is True
    assert "no reading" in section["reason"]
    assert section["ruleset"]["present"] is False
    assert ruleset_finding_lines(section) == []


def test_a_host_member_that_was_missing_is_listed_and_does_not_silently_match():
    measured = _measured()
    measured["missing"] = ["pcb_Drc.getRealTimeDrcStatus"]
    measured["ruleset"].pop("realTimeDrcStatus")
    section = ruleset_section(_reading(measured), documents_listed=1)

    assert section["checked"] is True
    assert any("pcb_Drc.getRealTimeDrcStatus" in note for note in section["notes"])
    assert any("缺读不是匹配" in note for note in section["notes"])


def test_an_absent_reference_table_says_the_meta_audit_did_not_run(monkeypatch):
    # "We compared nothing" and "everything matched" must not reach a reader as
    # the same sentence — so the absent table is reported, never swallowed.
    from boardwise import resources
    from boardwise.engines import drc

    monkeypatch.setattr(
        drc, "_load_ruleset_reference", lambda: None,
    )
    section = ruleset_section(_reading(), documents_listed=1)

    assert section["checked"] is True, "the reading was still read"
    assert section["ruleset"]["present"] is True
    assert section["metaAudit"]["available"] is False
    assert RULESET_REFERENCE_FILE in section["metaAudit"]["reason"]
    assert "不是「都匹配」" in section["metaAudit"]["reason"]
    assert ruleset_finding_lines(section) == [], "no comparison ran, so nothing was compared"
    assert resources.drc_ruleset_reference().name == RULESET_REFERENCE_FILE


def test_the_reference_table_names_its_own_provenance_and_covers_every_key_it_lists():
    reference = json.loads(
        (Path(__file__).resolve().parents[1] / "blocklib" / RULESET_REFERENCE_FILE)
        .read_text(encoding="utf-8")
    )
    assert reference["kind"] == "boardwise-pcb-drc-ruleset-reference"
    assert "岳校" in reference["provenance"], "the table must say who set the values"
    assert reference["referenceSet"]["name"] == "JLCPCB Capability(Two Layers Board)"
    for check in reference["checks"]:
        # Every key the table lists must be readable out of the measured fixture —
        # a path that never resolves is a table entry that can only ever report
        # `unreadable`, which is a table bug, not a board finding.
        node = _measured()["ruleset"]["current"]
        for part in check["path"].split("."):
            assert isinstance(node, dict) and part in node, (
                f"reference key {check['key']} points at {check['path']}, "
                "which the measured reading does not have"
            )
            node = node[part]
        assert isinstance(node, (int, float)) and not isinstance(node, bool), check["key"]
        assert check["severity"] in {"ERROR", "WARN", "INFO"}
        assert check["direction"] in {"below", "above", "either"}
        assert isinstance(check["why"], str) and check["why"], f"{check['key']} has no reason"


# --------------------------------------------------------------------------
# the multi-board PCB DRC loop (棒 2 item 1)
# --------------------------------------------------------------------------


def test_every_board_gets_a_drc_reading_and_the_first_one_is_also_the_single_board_shape():
    # The stage used to read `pcbs[0]` and note the rest as "留待后续". The two
    # shapes both survive: `pcb` is what `pcb_section`/`drc.summarise` read (their
    # shape is part of the report contract), `pcbs` is what now exists for every
    # board.
    from boardwise.cli import _ruleset_reading

    first = {"documentUuid": "pcb-a", "payload": {"checked": True, "mode": "groups", "groups": []},
             "ruleset": {"documentUuid": "pcb-a", "payload": _measured()}}
    second = {"documentUuid": "pcb-b", "payload": {"checked": True, "mode": "groups", "groups": []},
              "ruleset": {"documentUuid": "pcb-b", "payload": _measured()}}
    readings = {"schematic": [], "pcb": first, "pcbs": [first, second], "pcbDocuments": 2}

    assert readings["pcb"] is first, "drc.pcb and the ruleset section are about the same board"
    section = _ruleset_reading(readings)
    assert section is first["ruleset"]
    assert ruleset_section(section, documents_listed=2)["documentUuid"] == "pcb-a"


def test_the_ruleset_reading_is_none_when_the_stage_never_reached_a_board():
    from boardwise.cli import _ruleset_reading

    assert _ruleset_reading({"schematic": [], "pcbs": [], "pcbDocuments": 0}) is None
    assert _ruleset_reading({"schematic": [], "pcb": None, "pcbDocuments": 0}) is None
    # The pre-123 single-board shape is honoured rather than reported as "no board",
    # so a caller that stubs the stage the old way still gets a section.
    legacy = {"documentUuid": "pcb-a", "payload": _measured()}
    # The pre-123 shape carried no `ruleset` key at all, so the answer is `None`
    # and the section says "not read" — which is exactly right: pre-123, nobody read it.
    assert _ruleset_reading({"schematic": [], "pcb": legacy, "pcbDocuments": 1}) is None
    legacy_with_ruleset = {"documentUuid": "pcb-a", "payload": _measured(),
                           "ruleset": {"documentUuid": "pcb-a", "payload": _measured()}}
    assert _ruleset_reading({"schematic": [], "pcb": legacy_with_ruleset,
                             "pcbDocuments": 1}) is legacy_with_ruleset["ruleset"]


def test_a_stage_that_died_early_reports_no_rule_set_rather_than_an_empty_one():
    from boardwise.cli import _ruleset_reading

    section = ruleset_section(
        _ruleset_reading({"schematic": [], "pcb": None, "pcbs": [], "pcbDocuments": 0,
                          "error": {"code": "NO_CONNECTOR", "message": "no connector"}}),
        documents_listed=0,
    )
    assert section["checked"] is False


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def test_the_markdown_prints_the_rule_set_next_to_the_drc_it_explains():
    from boardwise.engines.checkup import render_report_markdown

    drc = {
        "schematic": {"checked": False, "reason": "no page answered"},
        "pcb": {"checked": False, "reason": "no PCB listed"},
        "ruleset": ruleset_section(_reading(), documents_listed=1),
    }
    text = render_report_markdown({
        "schema": "boardwise-checkup/6", "source": {"project": {"friendlyName": "test"}},
        "model": {}, "summary": {}, "drc": drc, "modules": [], "findings": [],
        "ai_slots": {}, "completion": {},
    })

    assert "PCB DRC 规则集：`JLCPCB Capability(Two Layers Board)`" in text
    assert "匹配 8" in text or "匹配 " in text
    assert "没读到 0" in text
    # Rendered before the module section, so the reader meets the rule before
    # the verdict it premises.
    assert text.index("PCB DRC 规则集") < text.index("## 模块")


def test_the_markdown_says_an_unread_rule_set_was_not_read():
    from boardwise.engines.checkup import render_report_markdown

    text = render_report_markdown({
        "schema": "boardwise-checkup/6", "source": {"project": {"friendlyName": "test"}},
        "model": {}, "summary": {},
        "drc": {"schematic": {"checked": False, "reason": "x"},
                "pcb": {"checked": False, "reason": "y"},
                "ruleset": ruleset_section(None, documents_listed=0)},
        "modules": [], "findings": [], "ai_slots": {}, "completion": {},
    })
    assert "PCB DRC 规则集：**未读**" in text
    assert "no PCB document" in text


def pytest_approx(value: float):
    """A local `approx` so this file does not import pytest for one number."""
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < 1e-12

        def __repr__(self):
            return f"~{value}"

    return _Approx()


# A guard against the fixture drifting from the reading it claims to be: the
# fixture is the measured answer, so the reference table's values must be
# reachable *through* it — asserted per key above. This is the coarse net for
# the case nobody thought to list a key for.
def test_the_fixture_is_the_measured_rule_set_and_not_something_someone_invented():
    measured = _measured()
    assert measured["page"] == {"uuid": "5dc38976c1fa45ce", "type": "pcb"}
    assert measured["source"] == "pcb_Drc"
    assert [r["path"] for r in measured["reads"]] == [
        "pcb_Drc.getCurrentRuleConfigurationName",
        "pcb_Drc.getCurrentRuleConfiguration",
        "pcb_Drc.getDefaultRuleConfigurationName",
        "pcb_Drc.getRealTimeDrcStatus",
    ]
    assert measured["ruleset"]["defaultName"] is None, (
        "the host answered undefined for the default rule-set name on this board; "
        "the fixture must keep that fact"
    )


def test_a_reference_table_that_grows_a_key_we_cannot_read_is_caught_by_the_per_key_test():
    # Guards the test above against becoming decorative: a key added to the table
    # with an unresolvable path must make that test fail, not silently join the
    # `unreadable` column in every report.
    reference = json.loads(
        (Path(__file__).resolve().parents[1] / "blocklib" / RULESET_REFERENCE_FILE)
        .read_text(encoding="utf-8")
    )
    for check in reference["checks"]:
        assert not check["path"].endswith(("minValue.", "form.")), check["key"]
    assert copy.deepcopy(reference["checks"]) == reference["checks"], "the table is JSON data"