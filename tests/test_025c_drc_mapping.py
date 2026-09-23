"""The DRC → report mapping (025 batch 3), against the host's recorded answers.

The three shapes under test are the ones the machine actually produced, quoted
verbatim from `outputs/025_probe_p4_pcb_drc.txt` (batch 1) and the batch-1
schematic readings — not invented fixtures. That matters here more than usual:
the whole point of this layer is that the two DRCs say *different amounts*, and a
hand-written fixture would encode whatever the author assumed instead of what the
host sends (`group.list[].list[]`, every node carrying its own `count`, a leaf
whose `objs: ['err0']` is not a child list).

What these tests protect, in one line each: counts stay counts (never invented
per-item detail), "not checked" never becomes "clean", and the exit code agrees
with the sections it was derived from.
"""

from __future__ import annotations

from boardwise.engines.drc import (
    COUNT_SEVERITY,
    OFFLINE_SOURCE,
    PCB_SOURCE,
    PCB_SEVERITY_BASIS,
    SCHEMATIC_SOURCE,
    offline_section,
    pcb_section,
    schematic_section,
    summarise,
)

#: The measured PCB DRC answer for the test project's empty PCB1 (batch 1,
#: `outputs/025_probe_p4_pcb_drc.txt`): the schematic has parts, the PCB does not.
MEASURED_PCB_TREE = [{
    "name": "Netlist Error",
    "list": [{
        "name": "Netlist Error",
        "list": [{
            "visible": True,
            "errorType": "Netlist Error",
            "errorObjType": "Netlist Error",
            "ruleName": "Import Changes",
            "ruleTypeName": "Import Changes",
            "obj1": {"typeName": "Schematic Netlist", "suffix": ""},
            "obj2": {"typeName": "PCB Netlist", "suffix": ""},
            "objs": ["err0"],
            "explanation": {
                "str": (
                    "PCB and schematic netlist does not match. You can click on the rule "
                    "name \"Import Changes\" to view the difference."
                ),
                "param": {},
            },
            "globalIndex": "err0",
            "parentId": "DRCTab|_|Errors|_|Netlist Error|_|Netlist Error",
        }],
        "count": 1,
        "title": ["Netlist Error", "(1)"],
        "visible": True,
    }],
    "visible": True,
    "count": 1,
    "title": ["Netlist Error", "(1)"],
}]

#: The measured PCB DRC answer with the counts the connector computes beside it.
MEASURED_PCB_PAYLOAD = {
    "source": "pcb_Drc.check",
    "checked": True,
    "available": True,
    "mode": "groups",
    "groups": MEASURED_PCB_TREE,
    "counts": {
        "groups": 1,
        "returnedGroups": 1,
        "errors": 1,
        "errorsSource": "group-count",
        "items": 1,
        "byLabel": {"Import Changes": 1},
        "jsonChars": 667,
    },
    "truncated": False,
    "elapsedMs": 271,
    "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
    "page": {"uuid": "5dc38976c1fa45ce", "type": "pcb"},
    "uiRequested": False,
}

#: The measured schematic answer: identical on all four pages of the test project.
MEASURED_SCH_PAYLOAD = {
    "source": "sch_Drc.check",
    "checked": True,
    "elapsedMs": 13,
    "args": {"strict": True, "userInterface": False, "includeVerboseError": True},
    "page": {"uuid": "b4298962367251c8", "type": "page"},
    "uiRequested": False,
    "mode": "counts",
    "counts": [{"type": "warn", "count": 1}],
    "entries": 1,
    "total": 1,
    "byType": {"warn": 1},
    "passed": False,
}

#: The message the host really throws when `pcb_Drc.check` runs off a PCB page.
NON_PCB_THROW = {
    "code": "CONNECTOR_ERROR",
    "message": (
        "pcb_Drc.check threw Error: 指定的主题消息在对应的画布内没有相关订阅. "
        "The declaration says the call reports nothing at all when no PCB is focused; "
        "the focused document here is b4298962367251c8 (page)"
    ),
}


# --------------------------------------------------------------------------
# the schematic section: counts, and only counts
# --------------------------------------------------------------------------


def _sch_reading(page: str, payload: dict | None = None) -> dict:
    return {"pageUuid": page, "payload": MEASURED_SCH_PAYLOAD if payload is None else payload}


def test_four_identical_page_readings_are_reported_once_not_summed():
    """Measured 2026-09-23: the host answers warn 1 on *every* page of the test
    project, so its counts are not page-scoped. Summing them would report four
    warnings where the host says one — the failure this rule exists to prevent."""
    readings = [_sch_reading(uuid) for uuid in ("p1", "p2", "p3", "p4")]

    section = schematic_section(readings)

    assert section["checked"] is True
    assert section["source"] == SCHEMATIC_SOURCE
    assert section["warn"] == 1 and section["total"] == 1
    assert section["countsBasis"] == "host-wide"
    assert section["pageCountsAgree"] is True
    assert "fatalError" not in section and "error" not in section, (
        "a kind the host never stated must be absent, not an invented zero"
    )
    assert len(section["pages"]) == 4
    assert section["note"] == "逐条见 findings 段（规则引擎）"
    assert any("不按页累加" in note for note in section["notes"])
    # The two engines are not the same engine, and the section says so.
    assert any("不是同一套规则" in note for note in section["notes"])
    # ... and the section carries **no** per-item container at all. This is the
    # contract the module exists for: a host that says "1 warning" must not come
    # back as a list of one plausible-looking finding (the mutation that tried it
    # — `section["leafs"] = [...]` — used to pass every test in this file).
    for container in ("leafs", "items", "findings", "groups"):
        assert container not in section, f"the schematic section is counts only: {container}"


def test_pages_that_disagree_are_summed_and_labelled_as_such():
    readings = [
        _sch_reading("p1", {**MEASURED_SCH_PAYLOAD, "counts": [{"type": "error", "count": 2}],
                            "total": 2, "byType": {"error": 2}}),
        _sch_reading("p2", {**MEASURED_SCH_PAYLOAD, "counts": [{"type": "warn", "count": 3}],
                            "total": 3, "byType": {"warn": 3}}),
    ]

    section = schematic_section(readings)

    assert section["countsBasis"] == "sum-of-pages"
    assert section["pageCountsAgree"] is False
    assert section["error"] == 2 and section["warn"] == 3
    assert any("sum-of-pages" in note for note in section["notes"])


def test_no_page_answering_is_not_a_clean_schematic():
    """The direction that must never happen: a refused check reported as zero."""
    readings = [_sch_reading("p1", None) | {"payload": None, "error": {"code": "TIMEOUT", "message": "no answer"}}]

    section = schematic_section(readings)

    assert section["checked"] is False
    assert section["reason"] == "TIMEOUT: no answer"
    for kind in COUNT_SEVERITY:
        assert kind not in section, f"{kind} must be absent when nothing was checked"
    assert "totals" not in section
    assert section["note"] == "逐条见 findings 段（规则引擎）"


def test_a_partially_unreadable_run_keeps_what_it_read():
    readings = [
        _sch_reading("p1"),
        {"pageUuid": "p2", "payload": None, "error": {"code": "PAGE_MISMATCH", "message": "wrong page"}},
    ]

    section = schematic_section(readings)

    assert section["checked"] is True
    assert section["warn"] == 1
    assert section["pagesChecked"] == 1
    assert section["pagesUnreadable"] == 1
    assert section["pages"][1]["checked"] is False


def test_a_boolean_answer_is_a_verdict_without_counts():
    payload = {**MEASURED_SCH_PAYLOAD, "mode": "boolean", "counts": None, "passed": True}

    section = schematic_section([_sch_reading("p1", payload)])

    assert section["checked"] is True
    assert section["countsKnown"] is False
    assert section["passed"] is True
    assert section["countsBasis"] == "unavailable"
    assert "warn" not in section


# --------------------------------------------------------------------------
# the PCB section: the tree, mapped without losing what it carries
# --------------------------------------------------------------------------


def test_the_measured_netlist_error_leaf_is_mapped_whole():
    section = pcb_section({"documentUuid": "5dc38976c1fa45ce", "payload": MEASURED_PCB_PAYLOAD})

    assert section["checked"] is True
    assert section["source"] == PCB_SOURCE
    assert section["documentUuid"] == "5dc38976c1fa45ce"
    assert section["truncated"] is False
    assert section["totals"]["groups"] == 1
    assert section["totals"]["leafs"] == 1, "the nested sub-group must not double-count"
    assert section["totals"]["hostErrors"] == 1
    assert section["totals"]["byRule"] == {"Import Changes": 1}

    group = section["groups"][0]
    assert group["name"] == "Netlist Error" and group["count"] == 1
    assert group["leafs"] == [], "the outer node is a container, not a leaf"
    leaf = group["children"][0]["leafs"][0]
    assert leaf["ruleName"] == "Import Changes"
    assert leaf["rendered"] == "verbatim", "the host's sentence had no placeholders"
    assert leaf["explanation"].startswith("PCB and schematic netlist does not match")
    assert leaf["obj1"]["typeName"] == "Schematic Netlist"
    assert leaf["objs"] == ["err0"]
    assert leaf["globalIndex"] == "err0"
    assert leaf["raw"]["parentId"].startswith("DRCTab|_|Errors")
    assert section["severityBasis"] == PCB_SEVERITY_BASIS


def test_the_three_no_board_shapes_are_kept_apart_from_a_clean_board():
    """A DRC that could not run carries no counts at all — see the module rule."""
    thrown = pcb_section({"documentUuid": None, "payload": None, "error": NON_PCB_THROW}, documents_listed=1)
    assert thrown["checked"] is False
    assert "指定的主题消息在对应的画布内没有相关订阅" in thrown["reason"]
    assert "groups" not in thrown and "totals" not in thrown

    declared_undefined = pcb_section({
        "documentUuid": None,
        "payload": {"checked": False, "available": False, "groups": None, "counts": None,
                    "reason": "the host returned undefined, its declared answer"},
    }, documents_listed=1)
    assert declared_undefined["checked"] is False
    assert "undefined" in declared_undefined["reason"]

    nothing_listed = pcb_section(None, documents_listed=0)
    assert nothing_listed["checked"] is False
    assert nothing_listed["reason"] == "no PCB document was listed for this project"
    assert nothing_listed["documentsListed"] == 0


def test_a_clean_board_is_checked_with_no_groups():
    payload = {"checked": True, "mode": "groups", "groups": [],
               "counts": {"groups": 0, "returnedGroups": 0, "errors": 0}, "truncated": False}
    section = pcb_section({"documentUuid": "pcb1", "payload": payload})

    assert section["checked"] is True
    assert section["groups"] == []
    assert section["totals"]["leafs"] == 0
    assert section["truncated"] is False


def test_a_truncated_tree_says_so_and_keeps_the_hosts_totals():
    payload = {
        **MEASURED_PCB_PAYLOAD,
        "truncated": True,
        "counts": {**MEASURED_PCB_PAYLOAD["counts"], "groups": 3, "returnedGroups": 1},
        "notes": ["2 group(s) were dropped to keep the answer inside maxChars (1000)"],
    }
    section = pcb_section({"documentUuid": "pcb1", "payload": payload})

    assert section["truncated"] is True
    assert section["droppedGroups"] == 2
    assert section["totals"]["groups"] == 3 and section["totals"]["groupsReturned"] == 1
    assert any("整组丢弃" in note for note in section["notes"])
    assert section["connectorNotes"]


def _tree_with_parent_id(parent_id: str) -> dict:
    return {
        "checked": True, "mode": "groups", "truncated": False,
        "counts": {"groups": 1, "returnedGroups": 1, "errors": 1},
        "groups": [{"name": "G", "count": 1, "list": [
            {"ruleName": "R", "errorType": "R", "parentId": parent_id,
             "explanation": {"str": "something", "param": {}}}]}],
    }


def test_the_hosts_own_parent_id_decides_the_severity_when_it_says():
    """Measured shape: `DRCTab|_|Errors|_|…` names the tab the item sits under —
    the only severity the host states anywhere in the tree."""
    errors = pcb_section({"documentUuid": "p", "payload": _tree_with_parent_id("DRCTab|_|Errors|_|G")})
    warnings = pcb_section({"documentUuid": "p", "payload": _tree_with_parent_id("DRCTab|_|Warnings|_|G")})

    error_leaf = _first_leaf(errors)
    warn_leaf = _first_leaf(warnings)
    assert (error_leaf["severity"], error_leaf["severitySource"]) == ("ERROR", "parentId")
    assert (warn_leaf["severity"], warn_leaf["severitySource"]) == ("WARN", "parentId")
    assert errors["totals"]["bySeverity"] == {"ERROR": 1}
    assert warnings["totals"]["bySeverity"] == {"WARN": 1}

    # ... and the split survives into the summary: a warning must not exit 1.
    split = summarise(drc={"schematic": {}, "pcb": warnings}, findings=[])
    assert split["errors"] == [] and split["warnings"][0]["severity"] == "WARN"
    assert split["exitCode"] == 0
    strict = summarise(drc={"schematic": {}, "pcb": errors}, findings=[])
    assert strict["exitCode"] == 1


def test_a_leaf_with_no_readable_severity_is_treated_as_an_error_not_a_warning():
    """Over-reporting is visible and correctable; under-reporting is silent."""
    section = pcb_section({"documentUuid": "p", "payload": _tree_with_parent_id("")})
    leaf = _first_leaf(section)

    assert leaf["severity"] == "ERROR"
    assert leaf["severitySource"] == "assumed"
    assert any("assumed" in note for note in section["notes"])


# --------------------------------------------------------------------------
# leaf rendering: three paths, three labels
# --------------------------------------------------------------------------


def _leaf(**overrides) -> dict:
    leaf = {
        "errorType": "Clearance",
        "ruleName": "Clearance",
        "net": "VCC",
        "pos": {"x": 12.5, "y": -4},
        "layer": 1,
        "explanation": {"str": "Clearance violation", "param": {}},
    }
    leaf.update(overrides)
    return leaf


def _first_leaf(section: dict) -> dict:
    group = section["groups"][0]
    return (group["leafs"] or group["children"][0]["leafs"])[0]


def test_a_placeholder_template_is_filled_from_param():
    payload = {"checked": True, "mode": "groups", "truncated": False,
               "counts": {"groups": 1, "returnedGroups": 1, "errors": 1},
               "groups": [{"name": "Clearance", "count": 1, "list": [
                   _leaf(explanation={"str": "间距 {actual} < {required} ({net})",
                                      "param": {"actual": "0.1", "required": "0.2", "net": "VCC"}})]}]}
    leaf = _first_leaf(pcb_section({"documentUuid": "p", "payload": payload}))

    assert leaf["rendered"] == "template"
    assert leaf["explanation"] == "间距 0.1 < 0.2 (VCC)"


def test_a_template_with_a_missing_value_is_passed_through_rather_than_mangled():
    payload = {"checked": True, "mode": "groups", "truncated": False,
               "counts": {"groups": 1, "returnedGroups": 1, "errors": 1},
               "groups": [{"name": "Clearance", "count": 1, "list": [
                   _leaf(explanation={"str": "间距 {actual} < {required}", "param": {"actual": "0.1"}})]}]}
    leaf = _first_leaf(pcb_section({"documentUuid": "p", "payload": payload}))

    assert leaf["rendered"] == "verbatim"
    assert leaf["explanation"] == "间距 {actual} < {required}"


def test_no_explanation_falls_back_to_the_fields_the_leaf_does_have():
    payload = {"checked": True, "mode": "groups", "truncated": False,
               "counts": {"groups": 1, "returnedGroups": 1, "errors": 1},
               "groups": [{"name": "Unrouted", "count": 1, "list": [
                   _leaf(explanation=None, errorType="Unrouted", ruleName="Unrouted")]}]}
    leaf = _first_leaf(pcb_section({"documentUuid": "p", "payload": payload}))

    assert leaf["rendered"] == "fallback"
    assert leaf["explanation"] == "Unrouted / net VCC / @(12.5, -4) / layer 1"


def test_a_leaf_with_nothing_to_render_says_so_instead_of_inventing_a_sentence():
    payload = {"checked": True, "mode": "groups", "truncated": False,
               "counts": {"groups": 1, "returnedGroups": 1, "errors": 1},
               "groups": [{"name": "?", "count": 1, "list": [{"visible": True}]}]}
    leaf = _first_leaf(pcb_section({"documentUuid": "p", "payload": payload}))

    assert leaf["rendered"] == "none"
    assert leaf["explanation"] == ""
    assert leaf["raw"] == {"visible": True}


# --------------------------------------------------------------------------
# 分流: counts + references, and an exit code that matches
# --------------------------------------------------------------------------


def _sections(*, sch_readings=None, pcb_reading=None):
    return {
        "schematic": schematic_section(sch_readings or []),
        "pcb": pcb_section(pcb_reading),
    }


def test_a_clean_board_with_no_findings_exits_zero():
    drc = _sections(
        sch_readings=[_sch_reading("p1", {**MEASURED_SCH_PAYLOAD, "counts": [{"type": "warn", "count": 0}],
                                      "total": 0, "byType": {"warn": 0}, "passed": True})],
        pcb_reading={"documentUuid": "pcb1", "payload": {
            "checked": True, "mode": "groups", "groups": [],
            "counts": {"groups": 0, "returnedGroups": 0, "errors": 0}, "truncated": False}},
    )
    summary = summarise(drc=drc, findings=[])

    assert summary["exitCode"] == 0
    assert summary["errors"] == []
    assert summary["warnings"] == [{
        "section": "drc.schematic", "source": SCHEMATIC_SOURCE, "severity": "WARN",
        "kind": "warn", "count": 0, "ref": "drc.schematic",
        "detail": "主机 ERC 聚合计数；逐条不在返回值里（见 findings 段的说明）",
    }]
    assert summary["countsIncomplete"] is False


def test_errors_and_warnings_are_split_with_references_a_reader_can_follow():
    drc = _sections(
        sch_readings=[_sch_reading("p1", {**MEASURED_SCH_PAYLOAD,
                                          "counts": [{"type": "error", "count": 2}, {"type": "warn", "count": 1}],
                                          "total": 3, "byType": {"error": 2, "warn": 1}})],
        pcb_reading={"documentUuid": "pcb1", "payload": MEASURED_PCB_PAYLOAD},
    )
    findings = [
        {"rule_id": "param-value-mpn-match", "severity": "ERROR", "message": "U3 value vs MPN",
         "refs": ["U3"]},
        {"rule_id": "param-led-current", "severity": "WARN", "message": "LED current", "refs": ["D1"]},
        {"rule_id": "decap-note", "severity": "INFO", "message": "note", "refs": []},
    ]

    summary = summarise(drc=drc, findings=findings)

    refs = [entry["ref"] for entry in summary["errors"]]
    assert refs == ["drc.schematic", "drc.pcb.groups[0].children[0].leafs[0]", "findings[0]"]
    assert summary["errorCount"] == 2 + 1 + 1
    assert summary["warnCount"] == 1 + 1
    assert summary["infoCount"] == 1
    assert summary["exitCode"] == 1
    assert summary["countsIncomplete"] is False
    pcb_entry = summary["errors"][1]
    assert pcb_entry["ruleName"] == "Import Changes" and pcb_entry["count"] == 1
    rule_entry = summary["errors"][2]
    assert rule_entry["ruleId"] == "param-value-mpn-match" and rule_entry["refs"] == ["U3"]


def test_sections_that_could_not_be_read_add_no_entries_and_do_not_claim_clean():
    drc = _sections(
        sch_readings=[{"pageUuid": "p1", "payload": None,
                       "error": {"code": "NO_CONNECTOR", "message": "gone"}}],
        pcb_reading={"documentUuid": None, "payload": None, "error": NON_PCB_THROW},
    )
    summary = summarise(drc=drc, findings=[])

    assert summary["errors"] == [] and summary["warnings"] == []
    assert summary["exitCode"] == 0, "nothing was found because nothing was checked"
    assert summary["countsIncomplete"] is False
    # ... and the sections themselves carry the reason, so exit 0 is not readable
    # as "this board passed".
    assert drc["schematic"]["checked"] is False and drc["schematic"]["reason"]
    assert drc["pcb"]["checked"] is False and drc["pcb"]["reason"]


def test_an_unknown_count_still_means_errors_and_says_the_count_is_incomplete():
    drc = _sections(
        sch_readings=[_sch_reading("p1", {**MEASURED_SCH_PAYLOAD, "mode": "boolean",
                                          "counts": None, "passed": False})],
        pcb_reading=None,
    )
    summary = summarise(drc=drc, findings=[])

    assert summary["exitCode"] == 1
    assert summary["countsIncomplete"] is True
    entry = summary["errors"][0]
    assert entry["count"] is None and entry["countsKnown"] is False
    assert "不可枚举" in entry["detail"]
    assert "countsIncompleteReason" in summary


def test_a_truncated_pcb_tree_marks_the_total_unknown():
    truncated = {**MEASURED_PCB_PAYLOAD, "truncated": True,
                 "counts": {**MEASURED_PCB_PAYLOAD["counts"], "groups": 4, "returnedGroups": 1}}
    drc = _sections(pcb_reading={"documentUuid": "pcb1", "payload": truncated})
    summary = summarise(drc=drc, findings=[])

    assert summary["exitCode"] == 1
    assert summary["countsIncomplete"] is True
    assert summary["errors"][-1]["ref"] == "drc.pcb.totals"
    assert summary["errors"][-1]["count"] is None


def test_the_offline_section_says_there_was_no_editor_to_ask():
    section = offline_section("离线路径不调 DRC")

    assert section["checked"] is False
    assert section["source"] == OFFLINE_SOURCE
    assert section["reason"] == "离线路径不调 DRC"
    assert "totals" not in section
    summary = summarise(drc={"schematic": section, "pcb": section}, findings=[])
    assert summary["errors"] == [] and summary["exitCode"] == 0
