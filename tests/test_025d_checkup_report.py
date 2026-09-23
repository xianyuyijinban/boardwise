"""checkup's report assembly (025 batch 4), against real archives and shaped models.

The three things this file protects, in the order they matter:

1. **A name is a claim.** The module naming rules must fire on positive evidence
   and stay silent otherwise: `未命名模块 N` is a useful answer ("we did not
   recognise this block") while a wrong name is a lie with a table around it.
   Two measured false positives are pinned here — an LCSC code read as a
   regulator family, and a lone regulator naming a whole-board blob.
2. **A grouping is not a guess.** Page attribution is read out of the archive's
   `SCH_PAGE` documents (positional join, because the ids do not join), and when
   the tier carries no page information the report says `unresolved` instead of
   inventing a split.
3. **Nothing disappears.** Parts no page claims and findings no module claims land
   in one `未归属` module rather than being dropped — an omission and a wrong
   grouping are both failures, but only one of them is invisible.

The models are built by hand where the shape matters (naming, dominance) and come
from real `.epro2` fixtures where the *data* matters (page attribution).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel, Net
from boardwise.engines.checkup import (
    FAMILY_DOMINANCE,
    MODULE_BASIS_CONNECTIVITY,
    MODULE_BASIS_PAGE,
    MODULE_BASIS_UNATTRIBUTED,
    PAGE_ATTRIBUTION_ARCHIVE,
    PAGE_ATTRIBUTION_UNRESOLVED,
    UNATTRIBUTED_NAME,
    UNKNOWN_REASON_NO_MPN,
    UNKNOWN_REASON_NO_SUPPLIER,
    UNKNOWN_REASON_UNDECODABLE,
    page_attribution_from_archive,
    modules_section,
    render_report_markdown,
    summary_template,
    unknown_parts,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CH340 = FIXTURES / "ch340_golden.epro2"
BISHE = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"


def component(designator: str, *, value: str = "", footprint: str = "", mpn: str = "",
              supplier: str = "", device_name: str = "") -> Component:
    return Component(
        uid=f"u-{designator}", designator=designator, value=value, footprint=footprint,
        mpn=mpn, lcsc_part=supplier,
        props={"device_name": device_name} if device_name else {},
    )


def model_of(*components: Component, nets: dict[str, list[tuple[str, str]]] | None = None) -> DesignModel:
    model = DesignModel()
    for part in components:
        model.components[part.designator] = part
    for name, pins in (nets or {}).items():
        model.nets[name] = Net(name=name, pins=list(pins))
    return model


# --------------------------------------------------------------------------
# page attribution: a positional join, because the ids do not join
# --------------------------------------------------------------------------


def test_page_attribution_reads_the_archives_own_page_structure():
    pages = page_attribution_from_archive(CH340)

    with_components = {uuid: page for uuid, page in pages.items() if page["components"]}
    assert len(with_components) == 1
    page = next(iter(with_components.values()))
    assert page["title"] == "P1"
    # The golden board is one page with 17 real parts — the same set the model has.
    assert len(page["components"]) == 17
    assert "U1" in page["components"] and "R24" in page["components"]


def test_pages_sharing_a_title_are_still_separate_pages():
    """Measured on the 毕设 fixture: three pages all titled `P1`. Attribution is by
    document, so the page uuid is what tells them apart — and a module name that
    hid that would put two different pages under one heading."""
    pages = page_attribution_from_archive(BISHE)

    with_components = {uuid: page for uuid, page in pages.items() if page["components"]}
    assert len(with_components) == 3
    assert {page["title"] for page in with_components.values()} == {"P1"}
    assert all(page["uuid"] in pages for page in with_components.values())


def test_an_unreadable_archive_yields_nothing_rather_than_an_empty_grouping(tmp_path):
    assert page_attribution_from_archive(tmp_path / "nope.epro2") == {}


def test_modules_from_pages_disambiguate_repeated_titles_and_flag_collisions():
    pages = page_attribution_from_archive(BISHE)
    model, _ = _load(BISHE)

    modules, facts = modules_section(
        model=model, findings=[], attribution=pages,
        attribution_source=PAGE_ATTRIBUTION_ARCHIVE,
    )

    assert facts["moduleBasis"] == MODULE_BASIS_PAGE
    assert facts["pageCount"] == 4 and facts["pagesWithComponents"] == 3
    names = [module["name"] for module in modules]
    assert all("（" in name for name in names), f"repeated titles must be disambiguated: {names}"
    assert all(module["pages"] for module in modules)
    # The fixture really does reuse designators across pages (30 of them), and the
    # module says so instead of quietly listing the same ref twice.
    assert any("跨页重号" in (module.get("note") or "") for module in modules)


def _load(path: Path):
    from boardwise.cli import _load_model

    return _load_model(path, view="schematic")


# --------------------------------------------------------------------------
# connectivity clustering, and the names it may not invent
# --------------------------------------------------------------------------


def test_clustering_excludes_ground_so_it_does_not_answer_one_blob():
    """GND joins everything; a grouping that returns one module for every board has
    told the reader nothing. Two sub-circuits sharing only ground must come apart."""
    model = model_of(
        component("R1"), component("R2"), component("C1"), component("C2"),
        nets={
            "GND": [("R1", "1"), ("R2", "1"), ("C1", "1"), ("C2", "1")],
            "SIG_A": [("R1", "2"), ("C1", "2")],
            "SIG_B": [("R2", "2"), ("C2", "2")],
        },
    )
    modules, facts = modules_section(model=model, findings=[], attribution=None)

    assert facts["moduleBasis"] == MODULE_BASIS_CONNECTIVITY
    assert facts["pageAttribution"] == PAGE_ATTRIBUTION_UNRESOLVED
    assert [module["components"] for module in modules] == [["C1", "R1"], ["C2", "R2"]]
    assert any("不按页" in note or "页归属不可解" in note for note in facts["notes"])


def test_a_cluster_whose_parts_are_mostly_mcus_is_named_mcu():
    model = model_of(
        component("U1", mpn="STM32F103C8T6", device_name="STM32F103C8T6"),
        component("C1", value="100nF"), component("X1", value="8MHz"),
        nets={"SIG": [("U1", "1"), ("C1", "1"), ("X1", "1")]},
    )
    modules, _facts = modules_section(model=model, findings=[], attribution=None)

    assert modules[0]["name"] == "MCU"
    assert "命中主控家族" in modules[0]["basis"]
    assert "U1=STM32F103C8T6" in modules[0]["basis"], "the evidence must be quotable"


def test_a_lone_regulator_among_other_functional_parts_does_not_name_the_block():
    """The false positive that made the dominance rule necessary: one LDO inside a
    blob of ICs and connectors is *in* the block, it is not what the block *is*."""
    functional = [
        component("U1", mpn="RT9013-33GB", device_name="RT9013-33GB"),
        component("U2", mpn="LM358"), component("U3", mpn="LM358"),
        component("Q1", mpn="AO3400"), component("Q2", mpn="AO3400"),
    ]
    model = model_of(*functional, nets={"SIG": [(part.designator, "1") for part in functional]})
    modules, _facts = modules_section(model=model, findings=[], attribution=None)

    assert modules[0]["name"] == "未命名模块 1"
    assert "未命中任何命名特征" in modules[0]["basis"]
    assert 1 / 5 < FAMILY_DOMINANCE, "the regulator really is a minority here"


def test_a_supplier_code_is_never_read_as_a_part_family():
    """Measured 2026-09-23: the LCSC code `C57895` contains `7895`, which an
    unanchored `78\\d{2}` regulator pattern read as a 7800-series regulator — and
    named a cluster of decoupling capacitors 电源."""
    model = model_of(
        component("C1", value="100nF", supplier="C57895"),
        component("C2", value="1uF", supplier="C57896"),
        component("R1", value="10k", supplier="C25804"),
        nets={"SIG": [("C1", "1"), ("C2", "1"), ("R1", "1")]},
    )
    modules, _facts = modules_section(model=model, findings=[], attribution=None)

    assert modules[0]["name"] == "未命名模块 1"


def test_interface_nets_name_a_cluster_only_when_they_are_its_connections():
    bridge = model_of(
        component("U1", mpn="CH340G", device_name="CH340G"),
        component("USB1", device_name="TYPE-C 16PIN"),
        nets={
            "GND": [("U1", "1"), ("USB1", "1")],
            "RX": [("U1", "2"), ("USB1", "2")], "TX": [("U1", "3"), ("USB1", "3")],
            "D+": [("U1", "4"), ("USB1", "4")], "D-": [("U1", "5"), ("USB1", "5")],
        },
    )
    modules, _facts = modules_section(model=bridge, findings=[], attribution=None)
    assert modules[0]["name"] == "接口"
    # Either interface rule may be the one that fires (the part names here, the net
    # names on a board of bare passives) — what must hold is that the basis quotes
    # the evidence and the ratio it was measured against.
    assert "接口" in modules[0]["basis"]
    assert "2/2" in modules[0]["basis"] or "非地网是" in modules[0]["basis"]


# --------------------------------------------------------------------------
# nothing disappears
# --------------------------------------------------------------------------


def test_findings_are_indexed_into_the_module_that_holds_their_parts():
    model = model_of(
        component("R1"), component("R2"), component("C1"),
        nets={"A": [("R1", "1"), ("C1", "1")], "B": [("R2", "1")]},
    )
    findings = [
        {"rule_id": "param-value-mpn-match", "severity": "ERROR", "refs": ["R1"]},
        {"rule_id": "decap-required-caps", "severity": "WARN", "refs": ["C1"]},
        {"rule_id": "orphan-rule", "severity": "WARN", "refs": []},
    ]
    modules, _facts = modules_section(model=model, findings=findings, attribution=None)

    first = next(module for module in modules if "C1" in module["components"])
    assert first["findings"] == [0, 1], "both findings name parts in this cluster"
    catch_all = next(module for module in modules if module["name"] == UNATTRIBUTED_NAME)
    assert catch_all["basis"] == MODULE_BASIS_UNATTRIBUTED
    assert catch_all["findings"] == [2], "a finding with no refs must not vanish"


def test_parts_no_page_claims_land_in_the_unattributed_module():
    pages = {
        "page-1": {"uuid": "page-1", "title": "P1", "components": ["R1"]},
        "page-2": {"uuid": "page-2", "title": "P2", "components": ["R2"]},
    }
    model = model_of(component("R1"), component("R2"), component("U9"))
    modules, _facts = modules_section(
        model=model, findings=[], attribution=pages,
        attribution_source=PAGE_ATTRIBUTION_ARCHIVE,
    )

    catch_all = next(module for module in modules if module["name"] == UNATTRIBUTED_NAME)
    assert catch_all["components"] == ["U9"]
    assert "不在任何页" in catch_all["note"]


# --------------------------------------------------------------------------
# unknown parts: three signals, and one guard against listing every IC
# --------------------------------------------------------------------------


def test_unknown_parts_reports_each_reason_separately():
    parts = unknown_parts(model_of(
        component("R2", footprint="0603", device_name="Res_0603"),
        component("C25", value="30pF", mpn="CC0402JRNPO9BN300", supplier="C107004"),
        component("R24", value="5.1K", mpn="", supplier=""),
        component("U1", mpn="CH340G", supplier="C14267"),
    ))

    by_ref = {part["designator"]: part for part in parts}
    assert set(by_ref) == {"R2", "R24"}, "a part with MPN + supplier is not unknown"
    assert UNKNOWN_REASON_NO_MPN in by_ref["R2"]["reasons"]
    assert UNKNOWN_REASON_NO_SUPPLIER in by_ref["R2"]["reasons"]
    assert by_ref["R2"]["question"] == by_ref["R24"]["question"]


def test_an_undecodable_mpn_is_flagged_for_the_prefixes_it_means_something_for():
    parts = unknown_parts(model_of(
        component("C9", value="330uF", mpn="EEUFR1V331", supplier="C1"),   # non-EIA notation
        component("U9", mpn="LM358", supplier="C2"),                       # an IC: never EIA
        component("R9", value="4.7k", mpn="FRC0805J472", supplier="C3"),    # decodes fine
    ))

    by_ref = {part["designator"]: part for part in parts}
    assert UNKNOWN_REASON_UNDECODABLE in by_ref["C9"]["reasons"]
    assert "U9" not in by_ref, "asking a decoder about an IC's MPN would list every IC"
    assert "R9" not in by_ref


# --------------------------------------------------------------------------
# report.md: renders the JSON, and nothing the JSON does not say
# --------------------------------------------------------------------------


def _report_dict(**overrides) -> dict:
    report = {
        "schema": "boardwise.checkup/2",
        "generatedAt": "2026-09-23T00:00:00+0800",
        "source": {"tier": "file", "tierLabel": "离线文件", "file": "board.epro2",
                   "pageAttribution": "archive", "moduleBasis": "connectivity",
                   "hostVersion": "", "connectorVersion": "",
                   "attempts": [{"tier": "file", "ok": True}], "notes": ["a note"]},
        "model": {"view": "schematic", "components": 2, "nets": 1, "designators": ["R1", "U1"],
                  "duplicateDesignators": []},
        "summary": {"errorCount": 1, "warnCount": 1, "infoCount": 0, "countsIncomplete": False,
                    "exitCode": 1,
                    "errors": [{"section": "drc.pcb", "severity": "ERROR", "ruleName": "Import Changes",
                                "count": 1, "ref": "drc.pcb.groups[0].leafs[0]", "net": ""}],
                    "warnings": [{"section": "findings", "severity": "WARN", "ruleId": "decap-required-caps",
                                  "count": 1, "ref": "findings[0]"}]},
        "pending": {},
        "drc": {
            "schematic": {"checked": True, "warn": 1, "pagesChecked": 4, "pageCount": 4,
                          "countsBasis": "host-wide", "note": "逐条见 findings 段（规则引擎）",
                          "notes": ["两个引擎不是同一套"]},
            "pcb": {"checked": True, "truncated": False,
                    "totals": {"leafs": 1},
                    "groups": [{"index": 0, "name": "Netlist Error", "count": 1, "leafs": [],
                                "children": [{"index": 0, "name": "Netlist Error", "leafs": [
                                    {"ruleName": "Import Changes", "net": "",
                                     "explanation": "PCB and schematic netlist does not match"}]}]}],
                    "notes": ["severity 取自 parentId"]},
        },
        "modules": [{"name": "U1", "basis": "page", "components": ["R1", "U1"], "findings": [0],
                     "pages": ["p1"]}],
        "findings": [{"rule_id": "decap-required-caps", "severity": "WARN", "message": "U1 needs C",
                      "refs": ["U1"]}],
        "ai_slots": {"unknown_parts": [{"designator": "U1", "name": "X", "value": "", "footprint": "SOP-8",
                                        "mpn": "", "supplier": "", "reasons": ["无 MPN"],
                                        "question": "核对"}],
                     "canvas_images": [{"page": "P1", "pageUuid": "p1", "file": "canvas-P1.png",
                                        "bytes": 1234}],
                     "canvas_images_note": "",
                     "summary_template": summary_template()},
    }
    report.update(overrides)
    return report


def test_report_markdown_carries_every_section_and_the_slot():
    text = render_report_markdown(_report_dict())

    assert "**结论：1 项 ERROR**（退出码 1）" in text
    assert "## 错误（ERROR）" in text and "Import Changes" in text
    assert "## 主机 DRC" in text
    assert "原理图 ERC：warn 1（4/4 页，计数口径 `host-wide`）" in text
    assert "| Netlist Error | Import Changes |" in text
    assert "### U1（2 器件）" in text and "依据：page" in text
    assert "| 0 | WARN | decap-required-caps" in text
    assert "## 警告（WARN）" in text
    assert "[P1](canvas-P1.png)" in text
    assert "【结论先行】" in text
    assert "report schema：`boardwise.checkup/2`" in text


def test_report_markdown_says_not_checked_instead_of_printing_zeroes():
    report = _report_dict()
    report["drc"]["schematic"] = {"checked": False, "reason": "离线路径不调 DRC",
                                  "source": "offline-not-available"}
    report["drc"]["pcb"] = {"checked": False, "reason": "离线路径不调 DRC",
                            "source": "offline-not-available"}
    report["ai_slots"]["canvas_images"] = []
    report["ai_slots"]["canvas_images_note"] = "离线路径不出图"
    report["summary"] = {"errorCount": 0, "warnCount": 0, "infoCount": 0, "exitCode": 0,
                         "countsIncomplete": False, "errors": [], "warnings": []}

    text = render_report_markdown(report)

    assert "**未检查** —— 离线路径不调 DRC" in text
    assert "无图。离线路径不出图" in text
    assert "**结论：无 ERROR**（退出码 0）" in text


def test_every_unknown_part_gets_the_same_question():
    """The slot is a worklist: one template question, so the model's job is uniform
    and the *reason* beside each entry is what differs."""
    text = render_report_markdown(_report_dict())
    assert "核对该器件周边配置是否符合规格书典型应用" in text
    assert json.loads(json.dumps(_report_dict()))["ai_slots"]["summary_template"] == summary_template()
