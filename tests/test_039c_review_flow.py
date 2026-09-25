"""039 批②: the review-flow upgrade — datasheet gate / warning triage / aesthetics.

Three work items, one file, because they are one flow (岳's three steps):

* **WI-1 the datasheet gate** — `unreviewed_parts` (the promoted `unknown_parts`)
  with its three acquisition channels, the conclusion that may not claim a pass
  while parts are unreviewed, and `parts fetch` (both channels: the engineer's
  `--file` and the shelf's LCSC links) plus the narrow fact extractor;
* **WI-2 warning triage** — the `warning_triage` slots and the
  "modules with warnings first" order, with the ERC attribution limit *stated*
  rather than papered over (the probe is `outputs/039c_erc_probe.txt`);
* **WI-3 the aesthetics switch** — `~/.boardwise/config.json`'s first setting,
  `boardwise config get/set`, the per-run override, and a `layout_review` section
  that is **absent** when the switch is off.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.config import (
    ConfigError,
    get_setting,
    parse_value,
    resolved_settings,
    set_setting,
    source_of,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary, load_parts
from boardwise.engines.checkup import (
    LAYOUT_AXES,
    TRIAGE_VERDICTS,
    layout_review_section,
    order_modules_by_warnings,
    unreviewed_parts,
    warning_triage_slots,
)
from boardwise.engines.datasheet import candidate_facts, pages_from_marked_text

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
BOARD = ROOT / "tests" / "fixtures" / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PROV = "test datasheet, p.1, http://example.com/ds.pdf"


def _entry(
    key: str,
    *,
    mpn: str,
    lcsc: str = "C1",
    facts: dict | None = None,
    facts_verified: bool = True,
    datasheet_url: str = "",
    datasheet_pdf_url: str = "",
) -> PartEntry:
    return PartEntry(
        key=key,
        mpn=mpn,
        lcsc=lcsc,
        manufacturer="ACME",
        deviceUuid="dev-1",
        libraryUuid="0819f05c4eef4c71ace90d822a990e87",
        footprint_name="SOT-23-5",
        category="ic.ldo",
        facts=facts,
        facts_verified=facts_verified,
        datasheetUrl=datasheet_url,
        datasheetPdfUrl=datasheet_pdf_url,
    )


def _model() -> DesignModel:
    """Three U-prefix parts and one passive, i.e. every case the list has."""
    model = DesignModel()
    model.components["U1"] = Component(  # verified facts ⇒ not unreviewed
        uid="u1", designator="U1", mpn="KNOWN1", lcsc_part="C1",
        pins=[Pin("1", "VIN", "+5V")],
    )
    model.components["U2"] = Component(  # candidate ⇒ facts drive nothing
        uid="u2", designator="U2", mpn="CAND1", lcsc_part="C2",
        pins=[Pin("1", "VIN", "+5V")],
    )
    model.components["U3"] = Component(  # no shelf entry at all
        uid="u3", designator="U3", mpn="NOWHERE1", lcsc_part="C3",
        pins=[Pin("1", "VIN", "+5V")],
    )
    model.components["R4"] = Component(  # a passive with no MPN/supplier
        uid="r4", designator="R4", value="10kΩ",
        pins=[Pin("1", "A", "+5V"), Pin("2", "B", "GND")],
    )
    model.nets = {"+5V": Net("+5V", [("U1", "1"), ("U2", "1"), ("U3", "1"), ("R4", "1")])}
    return model


def _library() -> PartLibrary:
    return PartLibrary(parts=[
        _entry("ic.known1", mpn="KNOWN1", lcsc="C1",
               facts={"supply_pins": [{"pins": ["1"], "name": "VIN",
                                       "v_operating": [2.2, 5.5], "provenance": PROV}]}),
        _entry("candidate.cand1", mpn="CAND1", lcsc="C2", facts_verified=False,
               facts={"supply_pins": [{"pins": ["1"], "name": "VIN",
                                       "v_operating": [2.2, 5.5], "provenance": PROV}]},
               datasheet_pdf_url="https://example.com/cand1.pdf"),
    ])


# ------------------------------------------------------------------ WI-1


def test_unreviewed_parts_carries_the_facts_and_the_three_channels(tmp_path):
    """The promoted section: who is on it, what is missing, and where a datasheet
    could still come from (engineer / LCSC / the vendor's site)."""
    (tmp_path / "NOWHERE1.pdf").write_bytes(b"%PDF-1.4 fake")
    rows = {
        row["designator"]: row
        for row in unreviewed_parts(_model(), library=_library(), datasheet_dir=tmp_path)
    }
    # U1 has verified facts and a full identity: the review can judge it.
    assert "U1" not in rows
    # U2 is a candidate: its claim does not drive a rule, so the part is unreviewed.
    assert rows["U2"]["factsVerified"] is False
    assert rows["U2"]["missingFacts"] == [
        "required_caps", "nc_pins", "must_connect", "led", "ldo", "pull_required",
    ]
    assert rows["U2"]["channels"]["lcsc"]["ok"] is True
    assert rows["U2"]["channels"]["engineer"]["ok"] is False
    # U3 is on no shelf at all, and the engineer's folder happens to hold its PDF.
    assert rows["U3"]["onShelf"] is False
    assert rows["U3"]["missingFacts"] and rows["U3"]["channels"]["engineer"]["ok"] is True
    assert rows["U3"]["channels"]["lcsc"]["ok"] is False
    # ... and the vendor channel is never the CLI's: it hands over the queries.
    official = rows["U3"]["channels"]["official"]
    assert official["ok"] is None and official["by"] == "ai"
    assert official["suggestedQueries"] and "datasheet" in official["suggestedQueries"][0]
    # The passive with no MPN and no supplier keeps the 025 signals.
    assert rows["R4"]["isIc"] is False
    assert rows["R4"]["missingFacts"] == []
    assert rows["R4"]["reasons"]


def test_the_promoted_section_keeps_the_v2_slot_name(capsys, tmp_path, monkeypatch):
    """A `/2` reader keeps working: `ai_slots.unknown_parts` is the same list."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    code = cli.main([
        "checkup", "--file", str(BOARD), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    assert code == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["schema"] == "boardwise.checkup/3"
    assert report["ai_slots"]["unknown_parts"] == report["unreviewed_parts"]
    assert report["unreviewed_parts"], "this board has parts with no MPN"
    old_fields = {"designator", "name", "value", "footprint", "mpn", "supplier",
                  "reasons", "question"}
    assert old_fields <= set(report["unreviewed_parts"][0])


def test_the_conclusion_may_not_claim_a_pass_while_parts_are_unreviewed(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    code = cli.main([
        "checkup", "--file", str(BOARD), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    assert code == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    count = report["summary"]["unreviewedParts"]
    assert count > 0
    assert report["summary"]["mayClaimPassed"] is False
    assert report["summary"]["conclusion"] == f"DRC/连接性已审，{count} 颗器件缺手册未审"
    assert "通过" not in report["summary"]["conclusion"]
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    conclusion_line = next(
        line for line in markdown.splitlines() if line.startswith("**结论：")
    )
    assert "通过" not in conclusion_line
    assert f"{count} 颗器件缺手册未审" in conclusion_line
    assert f"## 未审器件（{count}）" in markdown


# ------------------------------- parts fetch: the two channels it owns


_MARKED = """<<<page 1>>>
Table 5-1 Pin Functions
VCC 3 Supply 3.3V supply voltage
<<<page 4>>>
8.3 Recommended Operating Conditions
Supply voltage, VCC 3 3.6 V
"""


def test_fetch_with_a_local_pdf_writes_a_gated_candidate(monkeypatch, tmp_path, capsys):
    """The engineer's channel: no network at all, and the entry lands gated."""
    from boardwise.core.parts import save_parts
    shelf = tmp_path / "shelf.json"
    save_parts(PartLibrary(parts=[_entry("ic.nowhere1", mpn="NOWHERE1", lcsc="C3")]), shelf)
    pdf = tmp_path / "NOWHERE1.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(cli, "_pdf_text", lambda path: (_MARKED, "stub extractor"))
    code = cli.main([
        "parts", "fetch", "NOWHERE1", "--file", str(pdf), "--library", str(shelf),
        "--out", str(tmp_path / "datasheets"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    entry = load_parts(shelf).get("ic.nowhere1")
    assert entry.facts_verified is False
    assert entry.facts is None, "the gate holds the claim back"
    assert [r["v_operating"] for r in entry.candidate_facts["supply_pins"]] == [[3.0, 3.6]]
    provenance = entry.candidate_facts["supply_pins"][0]["provenance"]
    assert "p.1" in provenance and "p.2" in provenance, "both halves cite their page"
    assert f"file:{pdf}" in provenance, "an engineer's PDF is cited by its own path"
    assert "facts_verified=false" in out
    # The text dump landed beside the PDF, page markers and all.
    assert (tmp_path / "datasheets" / "NOWHERE1.txt").read_text(encoding="utf-8") == _MARKED


def test_fetch_uses_the_shelf_entry_lcsc_pdf_url(monkeypatch, tmp_path, capsys):
    """The LCSC channel: the URL comes from the entry, and the download is checked."""
    shelf = tmp_path / "shelf.json"
    from boardwise.core.parts import save_parts
    save_parts(PartLibrary(parts=[_entry(
        "ic.cand1", mpn="CAND1", lcsc="C2", facts=None,
        datasheet_pdf_url="https://example.com/cand1.pdf",
    )]), shelf)
    seen: dict = {}

    def fake_download(url: str, dest: Path) -> int:
        seen["url"] = url
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF-1.4 fake")
        return 12

    monkeypatch.setattr(cli, "_download_pdf", fake_download)
    monkeypatch.setattr(cli, "_pdf_text", lambda path: (_MARKED, "stub"))
    code = cli.main([
        "parts", "fetch", "CAND1", "--library", str(shelf), "--out", str(tmp_path / "ds"),
    ])
    capsys.readouterr()
    assert code == 0
    assert seen["url"] == "https://example.com/cand1.pdf"
    entry = load_parts(shelf).get("ic.cand1")
    assert entry.facts_verified is False and entry.candidate_facts


def test_fetch_reports_the_three_channels_when_it_cannot_get_a_pdf(tmp_path, capsys):
    from boardwise.core.parts import save_parts
    shelf = tmp_path / "shelf.json"
    save_parts(PartLibrary(parts=[_entry("ic.cand1", mpn="CAND1", lcsc="C2")]), shelf)
    code = cli.main(["parts", "fetch", "CAND1", "--library", str(shelf)])
    err = capsys.readouterr().err
    assert code == 2
    assert "没有任何 datasheet 链接" in err
    assert "① 工程师给" in err and "② 立创找" in err and "③ 官网搜" in err
    assert "CAND1 datasheet pdf" in err


def test_fetch_refuses_to_overwrite_verified_facts(capsys, tmp_path):
    from boardwise.core.parts import save_parts
    shelf = tmp_path / "shelf.json"
    save_parts(PartLibrary(parts=[_entry(
        "ic.cand1", mpn="CAND1", lcsc="C2",
        facts={"supply_pins": [{"pins": ["1"], "name": "VIN", "provenance": PROV}]},
    )]), shelf)
    before = shelf.read_bytes()
    code = cli.main(["parts", "fetch", "CAND1", "--library", str(shelf)])
    err = capsys.readouterr().err
    assert code == 2
    assert "已经有核验过的 facts" in err and "--force" in err
    assert shelf.read_bytes() == before


def test_fetch_writes_nothing_when_the_extractor_proposes_nothing(
    monkeypatch, tmp_path, capsys
):
    from boardwise.core.parts import save_parts
    shelf = tmp_path / "shelf.json"
    save_parts(PartLibrary(parts=[_entry("ic.cand1", mpn="CAND1", lcsc="C2")]), shelf)
    before = shelf.read_bytes()
    monkeypatch.setattr(cli, "_pdf_text", lambda path: ("<<<page 1>>>\nnothing here\n", "stub"))
    pdf = tmp_path / "cand1.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    code = cli.main(["parts", "fetch", "CAND1", "--file", str(pdf), "--library", str(shelf),
                     "--out", str(tmp_path / "ds")])
    out = capsys.readouterr().out
    assert code == 0
    assert "没有提出任何候选事实" in out
    assert shelf.read_bytes() == before, "no claim ⇒ no gate, and no write"


def test_fetch_of_an_unknown_part_explains_the_three_channels(capsys, tmp_path):
    code = cli.main(["parts", "fetch", "NOSUCHPART", "--library", str(SHELF)])
    err = capsys.readouterr().err
    assert code == 2
    assert "不在库里" in err and "parts add" in err
    assert "NOSUCHPART datasheet pdf" in err


# ------------------------------------------------------- the fact extractor


def test_pages_from_marked_text_keeps_every_page_number():
    pages = pages_from_marked_text("<<<page 1>>>\na\n<<<page 2>>>\n\n<<<page 3>>>\nc")
    assert pages == ["a", "", "c"], "an empty page stays a page: numbering must not shift"


def test_the_extractor_joins_a_pin_table_with_a_specification_row():
    """The two halves a datasheet states separately, with both quoted."""
    facts, _notes = candidate_facts(
        ["Table 5-1 Pin Functions\nVCC 3 Supply 3.3V supply voltage\n",
         "8.3 Recommended Operating Conditions\nSupply voltage, VCC 3 3.6 V\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    (record,) = facts["supply_pins"]
    assert record["pins"] == ["3"] and record["name"] == "VCC"
    assert record["v_operating"] == [3.0, 3.6]
    assert "p.1" in record["provenance"] and "p.2" in record["provenance"]
    assert "VCC 3 Supply" in record["provenance"]
    assert "https://example.com/ds.pdf" in record["provenance"]


def test_the_extractor_separates_absolute_maximum_from_operating():
    """A limit under an absolute-maximum heading is not an operating range."""
    facts, _ = candidate_facts(
        ["Pin Functions\nVCC 3 Supply\n",
         "8.1 Absolute Maximum Ratings\nSupply voltage, VCC –0.3 6 V\n",
         "8.3 Recommended Operating Conditions\nSupply voltage, VCC 3 3.6 V\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    by_kind = {}
    for record in facts["supply_pins"]:
        by_kind["abs" if "v_abs_max" in record else "op"] = record
    assert by_kind["abs"]["v_abs_max"] == [-0.3, 6.0], "the minus sign survives"
    assert by_kind["op"]["v_operating"] == [3.0, 3.6]


def test_the_extractor_refuses_a_figure_number_as_a_voltage_range():
    facts, _ = candidate_facts(
        ["Pin Functions\nVCC 3 Supply\n",
         "Figure 4-24 VDD - off comparator\nVDD 4 to 24 V\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    for record in facts.get("supply_pins", []):
        assert record.get("v_operating") != [4.0, 24.0], "a figure caption is not a spec"


def test_the_extractor_does_not_read_a_unit_suffix_as_a_pin_name():
    """`1OUT1 8 V+` is a package drawing, and `V/µs` is a slew rate."""
    facts, _ = candidate_facts(
        ["Pin Functions\nV+ 8 — Positive supply\n",
         "For VS 1 to 6.5 V/µs something\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    assert all(record.get("v_operating") != [1.0, 6.5] for record in facts.get("supply_pins", []))


def test_the_extractor_caps_the_capacitor_unit_and_continues_an_nc_list():
    facts, _ = candidate_facts(
        ["VDD Bypass Capacitor (Pin 13) C2 Ceramic, X7R, 0.1µF ±10%, 4V 1\n",
         "2, 3, 4, 5, 14,\n15, 16, 17 Y Y NC Not internally connected. May be used for routing.\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    assert facts["required_caps"][0]["value"] == "0.1uF"
    assert facts["required_caps"][0]["pin"] == "13"
    assert facts["nc_pins"]["pins"] == ["2", "3", "4", "5", "14", "15", "16", "17"]


def test_the_extractor_says_nothing_when_it_cannot_be_certain():
    facts, notes = candidate_facts(
        ["This part runs from a supply between about three and five volts.\n"],
        label="Test part", url="https://example.com/ds.pdf",
    )
    assert facts == {}
    assert any("没有可自动提取" in note for note in notes)


# ------------------------------------------------------------------ WI-2


def _drc(**overrides) -> dict:
    body = {
        "schematic": {
            "checked": True,
            # The shape `drc.schematic_section` actually produces: the per-kind
            # counts are `totals` (host-wide) and `counts` belongs to a *page*
            # reading. An earlier draft of this test used the page shape at the
            # section level, which hid a real bug in `warning_triage_slots`.
            "totals": {"warn": 1},
            "countsBasis": "host-wide",
            "pagesChecked": 4, "pageCount": 4,
            "pages": [{"pageUuid": "p1", "checked": True, "counts": {"warn": 1}}],
        },
        "pcb": {"checked": True, "groups": [
            {"index": 0, "name": "Netlist Error", "leafs": [
                {"ruleName": "Import Changes", "errorType": "Netlist Error",
                 "explanation": "PCB and schematic netlist does not match.",
                 "net": "VCC", "severity": "", "severitySource": "absent",
                 "globalIndex": "err1"},
                {"ruleName": "Clearance", "explanation": "too close", "net": "",
                 "severity": "error", "severitySource": "host", "globalIndex": "err2"},
            ]},
        ]},
    }
    body.update(overrides)
    return body


def test_warning_triage_has_one_slot_per_warning_and_never_fills_the_verdict():
    modules = [{"name": "接口", "components": ["U1"], "findings": [0]}]
    findings = [{"severity": "WARN", "message": "U1 pin1 的净电压未知", "rule_id": "x",
                 "refs": ["U1"]}]
    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1",
                                       pins=[Pin("1", "VIN", "VCC")])
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    slots = warning_triage_slots(model=model, drc=_drc(), findings=findings, modules=modules)
    by_source = {}
    for slot in slots:
        by_source.setdefault(slot["source"], []).append(slot)
        assert slot["verdict"] == "" and slot["reason"] == ""
    # The host ERC gives counts only: no text, host-wide scope, and it says so.
    (erc,) = by_source["host-erc"]
    assert erc["count"] == 1 and erc["text"] == ""
    assert erc["attribution"] == {"scope": "host-wide", "page": None, "module": None}
    assert "底部面板" in erc["textUnavailable"]
    # The PCB leaf that is a warning-ish item carries text and a net-resolved module.
    (pcb,) = by_source["pcb-drc"]
    assert "Import Changes" in pcb["text"]
    assert pcb["attribution"]["module"] == "接口"
    # The error-severity leaf is not a triage candidate.
    assert all("Clearance" not in slot["text"] for slot in slots)
    # A rule's own WARN is attributable exactly.
    (rule,) = by_source["boardwise-rule"]
    assert rule["text"] == "U1 pin1 的净电压未知"
    assert rule["attribution"] == {
        "scope": "finding", "page": None, "net": "", "module": "接口",
    }
    assert set(TRIAGE_VERDICTS) == {"有益", "有害", "无害"}


def test_modules_with_warnings_come_first_and_nothing_else_moves():
    findings = [
        {"severity": "ERROR", "rule_id": "a", "message": "", "refs": ["U1"]},
        {"severity": "WARN", "rule_id": "b", "message": "", "refs": ["U3"]},
    ]
    modules = [
        {"name": "一", "components": ["U1"], "findings": [0]},
        {"name": "二", "components": ["U2"], "findings": []},
        {"name": "三", "components": ["U3"], "findings": [1]},
    ]
    ordered = order_modules_by_warnings(modules, findings)
    assert [module["name"] for module in ordered] == ["三", "一", "二"]
    assert ordered[0]["warningFindings"] == [1]
    assert ordered[1]["warningFindings"] == [], "an ERROR is not a warning to triage"


def test_the_report_says_how_the_modules_were_ordered(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    code = cli.main([
        "checkup", "--file", str(BOARD), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    assert code == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["source"]["modulesOrderedBy"] == "warnings-first"
    assert all("warningFindings" in module for module in report["modules"])
    assert isinstance(report["warning_triage"], list)


# ------------------------------------------------------------------ WI-3


def test_the_settings_table_parses_switches_and_refuses_everything_else():
    assert parse_value("review.aesthetics", "on") is True
    assert parse_value("review.aesthetics", "OFF") is False
    assert parse_value("review.aesthetics", "关") is False
    for bad in ("maybe", "2", ""):
        with pytest.raises(ConfigError):
            parse_value("review.aesthetics", bad)
    with pytest.raises(ConfigError):
        parse_value("review.aesthetic", "on")


def test_settings_round_trip_and_read_the_nested_spelling(tmp_path):
    home = tmp_path / "home"
    assert get_setting("review.aesthetics", home=home) is False
    assert source_of("review.aesthetics", home=home) == "default"
    path = set_setting("review.aesthetics", True, home=home)
    assert path == home / "config.json"
    assert get_setting("review.aesthetics", home=home) is True
    assert source_of("review.aesthetics", home=home) == "file"
    # A human who hand-writes the nested form gets the same answer.
    path.write_text(json.dumps({"review": {"aesthetics": False}}), encoding="utf-8")
    assert get_setting("review.aesthetics", home=home) is False
    assert resolved_settings(home=home)["review.aesthetics"]["source"] == "file"


def test_config_cli_get_and_set(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    assert cli.main(["config", "get", "review.aesthetics"]) == 0
    assert capsys.readouterr().out.strip() == "off"
    assert cli.main(["config", "set", "review.aesthetics", "on"]) == 0
    capsys.readouterr()
    assert cli.main(["config", "get", "review.aesthetics"]) == 0
    assert capsys.readouterr().out.strip() == "on"
    assert cli.main(["config", "get", "review.aesthetics", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["value"] is True and payload["source"] == "file"
    assert cli.main(["config", "set", "nope.nope", "on"]) == 2
    assert cli.main(["config", "set", "review.aesthetics", "maybe"]) == 2
    assert cli.main(["config", "show"]) == 0
    assert "review.aesthetics" in capsys.readouterr().out


def _layout_of(out_dir: Path) -> dict:
    return json.loads((out_dir / "report.json").read_text(encoding="utf-8")).get(
        "layout_review", {}
    )


def test_the_aesthetics_switch_is_off_by_default_and_the_section_is_absent(
    capsys, tmp_path, monkeypatch
):
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "default"
    assert cli.main([
        "checkup", "--file", str(BOARD), "--out", str(out), "--library", str(SHELF),
    ]) == 0
    capsys.readouterr()
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert "layout_review" not in report, "off means absent, not empty"
    assert "## 布局审美" not in (out / "report.md").read_text(encoding="utf-8")
    assert report["ai_slots"]["aesthetics"]["enabled"] is False

    out_on = tmp_path / "on"
    assert cli.main([
        "checkup", "--file", str(BOARD), "--out", str(out_on), "--library", str(SHELF),
        "--aesthetics",
    ]) == 0
    capsys.readouterr()
    layout = _layout_of(out_on)
    assert layout["enabled"] is True and layout["source"] == "cli"
    assert [axis["name"] for axis in layout["axes"]] == [name for _key, name, _q in LAYOUT_AXES]
    assert all(axis["score"] is None and axis["evidence"] == "" for axis in layout["axes"])
    assert "禁止编分数" in layout["visionRequired"]


def test_the_config_turns_it_on_and_the_cli_flag_wins_over_it(
    capsys, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    set_setting("review.aesthetics", True, home=home)
    out = tmp_path / "from-config"
    assert cli.main([
        "checkup", "--file", str(BOARD), "--out", str(out), "--library", str(SHELF),
    ]) == 0
    capsys.readouterr()
    layout = _layout_of(out)
    assert layout["enabled"] is True and layout["source"] == "config"

    out_off = tmp_path / "override-off"
    assert cli.main([
        "checkup", "--file", str(BOARD), "--out", str(out_off), "--library", str(SHELF),
        "--no-aesthetics",
    ]) == 0
    capsys.readouterr()
    report = json.loads((out_off / "report.json").read_text(encoding="utf-8"))
    assert "layout_review" not in report, "the single-run override wins"
    assert report["ai_slots"]["aesthetics"]["enabled"] is False


def test_the_layout_section_slots_are_the_five_axes():
    section = layout_review_section(source="cli", pages=[{"page": "P1", "file": "canvas-P1.png"}])
    assert [axis["key"] for axis in section["axes"]] == [
        "topology", "flow", "text", "grouping", "netlabels",
    ]
    assert section["scale"].startswith("1–5")
    assert section["skipped"] is None
    assert section["pages"][0]["file"] == "canvas-P1.png"
