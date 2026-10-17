"""192B: 判型 / 闸门 / 合同 — the eleven holes of the v0.5.14 audit.

Every test here was first a probe that reproduced a defect on HEAD (the probes
live in the repo root's ``.tmp_hole_*`` directories; the reproductions are
recorded in ``outputs/192b/evidence.md``). One section per item, in the task
book's order:

* **①** the vocabulary read words as **substrings**, so ``MOS`` hit ``CMOS``
  (an op-amp judged a transistor) and ``USB`` hit an STM32's description (an MCU
  judged a connector) — and the corpus-wide before/after property test that says
  no fixture loses an IC to the fix;
* **②** ``DecouplingPerIC`` asked the part-kind entry point **without** a shelf,
  so it answered 「connector」 about a part the shelf had already classified;
* **③** the 039 gate (``facts_verified: false`` is not a declaration) was applied
  by ``classify_part`` and then undone by ``device_facts`` / ``_entry_category``;
* **④** ``_tier_pin`` could not read a numbered pin name (``SW1``/``PVIN1`` read
  as nothing, ``VIN1`` graded on the consuming side);
* **⑤** 190's declared-passive exemption could drop a real IC out of the
  datasheet gate silently — the guard, the trace and the corrected comment;
* **⑥** the accepted section's uniqueness key was ``part`` while the writer,
  the rewriter and the report all key on ``(part, board)``;
* **⑦** an acceptance scoped to a board the part is not on printed
  「图纸上已没有」 over a part that is on two other boards;
* **⑧** ``_completion_body`` sub-scripted ``coverage["modelEmpty"]`` on the
  re-gate path, where an old report's coverage section has no such key;
* **⑨** the intent section carried **two** different numbers under one name;
* **⑩** 「契约版本」 printed this build's constant as if the file had declared it;
* **⑪** the accepted section claimed the verdict left ``incomplete`` whatever the
  actual verdict was.

The fixtures are the tracked boards and synthetic models; the CLI is the real
one. R4b: no real project or enterprise part name is typed here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core import partkind
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.partkind import (
    DECLARATION_WORDS,
    KIND_CAPACITOR,
    KIND_CONNECTOR,
    KIND_IC,
    KIND_THERMISTOR,
    KIND_TRANSISTOR,
    SUBSTRING_WORDS,
    classify_part,
)
from boardwise.core.parts import PartLibrary, load_parts
from boardwise.engines import checkup as checkup_engine
from boardwise.engines.checkup import (
    MAX_PASSIVE_PINS,
    STATE_ACCEPTED_STALE,
    STATE_ACCEPTED_STALE_ELSEWHERE,
    accepted_unknown_counts,
    accepted_unknown_section,
    accepted_verdict_clause,
    declared_passive_exemptions,
    intent_section,
    render_intent_markdown,
    render_report_markdown,
    unreviewed_parts,
)
from boardwise.rules.connectivity import DecouplingPerIC
from boardwise.rules.facts import read_default_library
from boardwise.rules.pcb.distance import _tier_pin, device_facts
from boardwise.rules.sensebias import SamplingBias

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

#: The two measured words of item ①, verbatim from the boards that forced them.
OPAMP_TEXT = "1.8V 微功耗 CMOS 运算放大器零漂移系列 SOP-8"
MCU_TEXT = (
    "主流增强型ARM Cortex-M3 MCU，具有64 KB Flash、72 MHz CPU、电机控制、USB和CAN "
    "LQFP-48(7x7)"
)


def _component(designator: str, *, props: dict | None = None, pins: int = 0, **kwargs):
    return Component(
        uid=designator.lower(),
        designator=designator,
        props=dict(props or {}),
        pins=[Pin(str(index + 1), f"P{index + 1}", f"N{index + 1}") for index in range(pins)],
        **kwargs,
    )


# --------------------------------------------------------------------------
# ① the vocabulary: token boundaries, and the property they must not break
# --------------------------------------------------------------------------


def test_mos_inside_cmos_no_longer_makes_an_opamp_a_transistor():
    comp = _component("U1", props={"LCSC Part Name": OPAMP_TEXT}, pins=8)
    read = classify_part(comp)
    assert read.kind == KIND_IC
    assert read.basis == "metadata"
    assert "运算放大器" in read.reason or "放大器" in read.reason


def test_usb_inside_a_catalogue_description_no_longer_makes_an_mcu_a_connector():
    comp = _component("U1", props={"LCSC Part Name": MCU_TEXT}, pins=48)
    read = classify_part(comp)
    assert read.kind == KIND_IC


def test_a_touch_key_chip_is_not_a_capacitor():
    """The ①/⑤ pair: 立创 目录名里带「电容」的芯片不是电容。"""
    comp = _component("U1", props={"LCSC Part Name": "电容式触摸按键芯片(TTP223)"})
    read = classify_part(comp, pin_floor=False)
    assert read.kind == KIND_IC
    assert "芯片" in read.reason


def test_a_word_inside_a_longer_word_is_not_a_hit():
    """The boundary read itself — the half the two cases above do **not** cover.

    Both of those parts also carry an IC word (「运算放大器」/「MCU」), so the IC
    table would decide them even with the old substring read — the boundary is
    what decides a part whose *only* word signal is an infix. These are the
    witnesses, taken from the probe that measured the hole: an MPN ending
    ``CMLCC``, a catalogue string starting ``USB2.0``, and ``CMOS`` in a
    comparator's description.
    """
    from boardwise.core.partkind import _kind_of_words

    assert _kind_of_words("sop-8  mp2491cmlcc mp2491cmlcc")[0] == "unknown"
    assert _kind_of_words("usb2.0 收发器")[0] == "unknown"
    assert _kind_of_words("低功耗 cmos 比较器")[0] == "unknown"
    # …and the standalone spellings still read the family they always did.
    assert _kind_of_words("mlcc 陶瓷")[0] == KIND_CAPACITOR
    assert _kind_of_words("usb 连接器")[0] == KIND_CONNECTOR

    assert classify_part(
        _component("U1", mpn="MP2491CMLCC", footprint="SOP-8", pins=8)
    ).kind == KIND_IC
    assert classify_part(
        _component("U2", props={"LCSC Part Name": "USB2.0 收发器"}, pins=8)
    ).kind == KIND_IC


@pytest.mark.parametrize(
    "text, expected",
    [
        # Part-number families: the ASCII names are deliberately still read as
        # substrings (see SUBSTRING_WORDS), because the family token is a prefix
        # of a longer code and every one of these is a measured witness.
        ("DFN(5x6)  MCAC53N06Y-TP MCAC53N06Y-TP", KIND_TRANSISTOR),
        ("SOT-23  2N7002K 2N7002K_c22379475", KIND_TRANSISTOR),
        ("插件,P=2.54mm  PZ254V-11-04P PZ254V-11-04P", KIND_CONNECTOR),
        ("-  XT60PW-M XT60PW-M", KIND_CONNECTOR),
        ("SMD  HNTC0603-103F3450FA HNTC0603-103F3450FA", KIND_THERMISTOR),
    ],
)
def test_part_number_families_still_read(text, expected):
    from boardwise.core.partkind import _kind_of_words

    kind, _label, _hit = _kind_of_words(text.lower())
    assert kind == expected, f"{text!r} -> {kind}"


def test_the_substring_exceptions_are_explained_by_the_table():
    """The exception list is a list of **plain ASCII words**, and it is exactly them.

    A word that carries a separator (``RES-`` / ``TYPE-C``) or a CJK character is
    substring-matched by construction and needs no entry — an entry there would
    hide a word that is only *claimed* to need one. That is the invariant the
    table is checked against, and the measured families are named on top of it.
    """
    assert {"mcac", "2n7002", "pz254", "xt60", "ntc", "ptc"} <= set(SUBSTRING_WORDS)
    for word in SUBSTRING_WORDS:
        assert word == word.lower()
        assert word.isascii() and word.isalnum(), (
            f"{word!r} is not a plain ASCII word — it is substring-matched already"
        )
    vocabulary = {word.lower() for _k, _l, words in DECLARATION_WORDS for word in words}
    assert SUBSTRING_WORDS <= vocabulary, "an exception that is not in the vocabulary"


def _scan_corpus(library) -> dict[tuple[str, str, str], str]:
    """`{(file, board, designator): kind}` over every readable `.epro2` fixture."""
    from boardwise.parsers.schematic import build_project_model

    out: dict[tuple[str, str, str], str] = {}
    for path in sorted(FIXTURES.glob("*.epro2")):
        try:
            model = build_project_model(path)
        except Exception:  # noqa: BLE001 — a fixture this walk cannot read
            continue
        for board_model in (getattr(model, "boards", None) or [model]):
            title = board_model.board.title if getattr(board_model, "board", None) else ""
            for designator, comp in sorted(board_model.components.items()):
                read = classify_part(comp, library=library)
                out[(path.name, title, designator)] = read.kind
    return out


def test_no_fixture_loses_an_ic_to_the_token_boundary_reading(monkeypatch):
    """The property ① asks for: **no IC → non-IC flip anywhere on the corpus.**

    The "before" reading is reproduced by restoring 127b's substring ``_hit`` and
    dropping the IC row from the vocabulary — the two things this batch changed —
    inside one process, so the two readings cannot drift apart in the comparison.
    The two *expected* flips are asserted by name: they are the defect this item
    exists for, and a corpus that stopped producing them would mean the fix had
    been lost.
    """
    library = read_default_library()
    after = _scan_corpus(library)

    old_words = tuple(row for row in DECLARATION_WORDS if row[0] != KIND_IC)

    def substring_hit(text: str, words: tuple[str, ...]) -> str:
        for word in words:
            if word.lower() in text:
                return word
        return ""

    monkeypatch.setattr(partkind, "_hit", substring_hit)
    monkeypatch.setattr(partkind, "DECLARATION_WORDS", old_words)
    before = _scan_corpus(library)

    flips = {
        key: (before[key], after[key])
        for key in before
        if before.get(key) != after.get(key)
    }
    lost_ics = {key: pair for key, pair in flips.items() if pair[0] == KIND_IC}
    assert lost_ics == {}, f"the new reading lost ICs: {lost_ics}"
    assert all(pair[1] == KIND_IC for pair in flips.values())
    assert len(flips) == 2, f"expected exactly the two measured flips, got {flips}"
    assert {key[0] for key in flips} == {
        "毕设滤波采样_2026-09-27.epro2", "超声波_2026-09-27.epro2",
    }


# --------------------------------------------------------------------------
# ② the decoupling rule reads the same shelf as the facts rules
# --------------------------------------------------------------------------


def test_the_decoupling_rule_hands_the_shelf_to_the_part_kind_reading():
    """``U2`` is a connector by its words and an IC on the shelf.

    The part is a real shelf entry (``ic.usb-uart``) whose own text carries a
    connector word and no IC word, which is the shape the shelfless read got
    wrong: the rule and `rules/facts` answered differently about one part.
    """
    library = load_parts(ROOT / "blocklib" / "parts.json")
    comp = Component(
        uid="u2", designator="U2", mpn="CH340G", footprint="CONN-SMD_4P",
        pins=[Pin("1", "VCC", "+5V"), Pin("2", "GND", "AGND"),
              Pin("3", "TXD", "NET1"), Pin("4", "RXD", "NET2")],
    )
    r1 = Component(uid="r1", designator="R1", value="0R",
                   pins=[Pin("1", "1", "NET1"), Pin("2", "2", "NET2")])
    model = DesignModel(components={"U2": comp, "R1": r1})
    model.nets = {
        "+5V": Net(name="+5V", pins=[("U2", "1")]),
        "AGND": Net(name="AGND", pins=[("U2", "2")]),
        "NET1": Net(name="NET1", pins=[("U2", "3"), ("R1", "1")]),
        "NET2": Net(name="NET2", pins=[("U2", "4"), ("R1", "2")]),
    }
    # The premise: without a shelf the same part really is read as a connector.
    assert classify_part(comp).kind == KIND_CONNECTOR
    assert classify_part(comp, library=library).kind == KIND_IC

    findings = DecouplingPerIC().check(model)
    assert [f.rule_id for f in findings] == ["decoupling-per-ic"]
    assert "part-kind reading: ic" in " ".join(findings[0].evidence)


# --------------------------------------------------------------------------
# ③ the 039 gate holds at every caller of the shared entry point
# --------------------------------------------------------------------------


def _candidate_shelf(path: Path) -> Path:
    """A shelf whose one entry is a **candidate** (``facts_verified: false``)."""
    payload = {
        "kind": "boardwise-part-library",
        "version": 2,
        "sources": [],
        "parts": [{
            "key": "ic.candidate_ldo", "category": "ic.ldo", "mpn": "CAND123",
            "lcsc": "C999999", "manufacturer": "x", "deviceUuid": "d1",
            "libraryUuid": "l1", "footprint_name": "SOT-23-5",
            "facts_verified": False, "params": {},
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_an_unverified_shelf_entry_is_not_a_declaration_in_device_facts(tmp_path):
    shelf = load_parts(_candidate_shelf(tmp_path / "shelf.json"))
    comp = _component("X1", mpn="CAND123", pins=3)
    assert device_facts(comp, shelf).shelf_category == ""
    # …and the classification falls through to the designator rather than
    # citing the shelf (which is what the shared entry point already did).
    assert classify_part(comp, library=shelf).basis == "prefix"


def test_an_unverified_shelf_entry_is_not_a_declaration_in_sensebias(tmp_path):
    shelf = load_parts(_candidate_shelf(tmp_path / "shelf.json"))
    rule = SamplingBias(library=shelf)
    comp = _component("X1", mpn="CAND123", pins=3)
    assert rule._entry_category(comp) == ""
    assert rule._mcu_basis(comp) == ""


# --------------------------------------------------------------------------
# ④ a numbered pin name is the same name with a pin index on it
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin_name, expected",
    [
        ("SW1", "稳压器输出档"),
        ("SW2", "稳压器输出档"),
        ("PVIN1", "稳压器输入档"),
        ("VIN1", "稳压器输入档"),          # was 消耗端 — the pre-192B defect
        ("VIN2", "稳压器输入档"),
        ("VCC3", "消耗端供电脚档"),
        ("VOUT_2", "稳压器输出档"),
        ("VIN_1", "稳压器输入档"),
        # Unchanged: names that declare no tier still declare none.
        ("RON", None),
        ("PGOOD", None),
        ("1", None),
        ("IN1", None),
        ("AVIN1", None),
    ],
)
def test_tier_pin_reads_numbered_names(pin_name, expected):
    assert _tier_pin(pin_name) == expected


# --------------------------------------------------------------------------
# ⑤ the declared-passive exemption: a guard, a trace, and a corrected comment
# --------------------------------------------------------------------------


def test_the_exemption_only_covers_two_pin_parts():
    declared = {"LCSC Part Name": "厚膜电阻"}
    assert MAX_PASSIVE_PINS == 2
    assert checkup_engine._declared_passive(_component("U4", props=declared, pins=2))
    assert not checkup_engine._declared_passive(_component("U4", props=declared, pins=3))
    assert not checkup_engine._declared_passive(_component("U4", props=declared, pins=16))


def test_a_touch_key_chip_stays_in_the_datasheet_gate():
    model = DesignModel()
    model.components["U1"] = _component(
        "U1", props={"LCSC Part Name": "电容式触摸按键芯片(TTP223)"}
    )
    rows = unreviewed_parts(model, library=PartLibrary(parts=[]))
    assert [row["designator"] for row in rows] == ["U1"]
    assert checkup_engine._declared_passive(model.components["U1"]) is False


def test_every_exempted_part_is_named_in_the_report():
    model = DesignModel()
    model.components["U4"] = _component(
        "U4", value="470Ω", footprint="R0805", props={"LCSC Part Name": "厚膜电阻"}, pins=2
    )
    rows = declared_passive_exemptions(model)
    assert [row["designator"] for row in rows] == ["U4"]
    assert rows[0]["kind"] == "resistor" and rows[0]["pins"] == 2
    assert rows[0]["basis"] == "metadata"

    report = {
        "declaredPassiveExempt": rows,
        "completion": {"declaredPassiveExempt": len(rows)},
        "unreviewed_parts": [],
    }
    markdown = render_report_markdown(report)
    assert "**声明为无源件、未按 IC 问手册的件（1）**" in markdown
    assert "`U4`" in markdown


def test_the_exemption_comment_no_longer_claims_it_can_only_add_questions():
    import inspect

    source = inspect.getsource(checkup_engine._declared_passive)
    assert "只会多问" not in source


# --------------------------------------------------------------------------
# ⑥ accepted entries are unique per (part, board)
# --------------------------------------------------------------------------


def test_two_acceptances_for_one_token_on_two_boards_round_trip(tmp_path):
    document = di.DesignIntent()
    document, _ = di.accept_unknown(document, "U7", reason="板1 接受", who="t", when="t1")
    document, _ = di.accept_unknown(
        document, "U7", reason="板2 接受", who="t", when="t2", board="Board2"
    )
    assert len(document.accepted_unknown) == 2

    text = di.render_json(document)
    again = di.parse_json(text)
    assert [entry.board for entry in again.accepted_unknown] == ["", "Board2"]
    assert [entry.reason for entry in again.accepted_unknown] == ["板1 接受", "板2 接受"]

    path = tmp_path / "contract.json"
    path.write_text(text, encoding="utf-8")
    assert di.DesignIntent.load(path).accepted_unknown[1].board == "Board2"


def test_the_same_part_and_board_twice_is_still_refused():
    payload = {
        "intentVersion": 1,
        "requirements": {"rails": [], "signals": [], "buses": []},
        "blocks": [],
        "decisions": [],
        "acceptedUnknown": [
            {"part": "U7", "reason": "a", "board": "Board2"},
            {"part": "u7", "reason": "b", "board": "board2"},
        ],
    }
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.parse_json(json.dumps(payload))
    assert "(part, board)" in str(excinfo.value)


def test_the_other_sections_keep_their_single_field_uniqueness():
    payload = {
        "intentVersion": 1,
        "requirements": {
            "rails": [{"net": "+5V", "targetVoltage": "5"}],
            "signals": [], "buses": [],
        },
        "blocks": [{"id": "b1"}, {"id": "b1"}],
        "decisions": [],
    }
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.parse_json(json.dumps(payload))
    assert "states id 'b1' twice" in str(excinfo.value)


# --------------------------------------------------------------------------
# ⑦ an acceptance on a board the part is not on says so
# --------------------------------------------------------------------------


def _board_rows() -> list[dict]:
    return [
        {"designator": "U1", "mpn": "MPN-A", "name": "", "value": "",
         "boards": [{"board": "Board1", "mpn": "MPN-A", "name": "", "value": ""}]},
        {"designator": "U2", "mpn": "MPN-B", "name": "", "value": "",
         "boards": [{"board": "Board2", "mpn": "MPN-B", "name": "", "value": ""}]},
    ]


def _model_with_board(designator: str, board: str) -> object:
    from boardwise.core.model import BoardModel, BoardRef, ProjectModel

    model = BoardModel(board=BoardRef(uuid="uuid", title=board, page_uuids=()))
    model.components[designator] = Component(
        uid=designator.lower(), designator=designator
    )
    model.nets = {}
    return ProjectModel(boards=[model])


def test_a_board_scoped_acceptance_says_the_part_is_elsewhere():
    entry = di.IntentAccepted(part="U2", reason="只在 Board9 接受", board="Board9")
    model = _model_with_board("U2", "Board2")
    _remaining, accepted = accepted_unknown_section(model, [], [entry])
    row = accepted[0]
    assert row["state"] == STATE_ACCEPTED_STALE_ELSEWHERE
    assert row["stale"] is True
    assert "Board9" in row["why"] and "Board2" in row["why"]

    counts = accepted_unknown_counts(accepted)
    assert counts[STATE_ACCEPTED_STALE_ELSEWHERE] == 1
    assert counts[STATE_ACCEPTED_STALE] == 0


def test_a_part_the_drawing_lost_is_still_plainly_stale():
    entry = di.IntentAccepted(part="UNSOLDERED9", reason="还没装")
    model = _model_with_board("U2", "Board2")
    _remaining, accepted = accepted_unknown_section(model, [], [entry])
    assert accepted[0]["state"] == STATE_ACCEPTED_STALE
    assert "图纸上没有这颗件" in accepted[0]["why"]


def test_report_md_prints_the_elsewhere_board_name():
    entry = di.IntentAccepted(part="U2", reason="只在 Board9 接受", board="Board9")
    model = _model_with_board("U2", "Board2")
    _remaining, accepted = accepted_unknown_section(model, [], [entry])
    markdown = render_report_markdown({
        "accepted_unknown": accepted,
        "unreviewed_parts": [],
        "completion": {"verdict": "complete-with-open-items"},
    })
    assert "stale-elsewhere（件在别的板上）" in markdown
    assert "Board9" in markdown and "Board2" in markdown
    assert "stale（图纸上已没有）" not in markdown


# --------------------------------------------------------------------------
# ⑧ the re-gate path reads coverage with `.get`
# --------------------------------------------------------------------------


def test_regating_a_report_whose_coverage_predates_the_gate_does_not_crash():
    report = {
        "completion": {
            "scope": {"rules": 1, "boards": 1, "pages": 1},
            "coverage": {"parseIncomplete": False},
        },
        "summary": {"errorCount": 0, "errors": []},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 0, "filled": 0, "stale": 0}},
    }
    completion = cli._completion_from_report(report, needs_datasheet=[])
    assert completion["verdict"] == "complete"
    assert completion["coverage"] == {"parseIncomplete": False}


# --------------------------------------------------------------------------
# ⑨ the intent section's stale numbers are two numbers
# --------------------------------------------------------------------------


def _intent_section(newly_stale: list[str], all_stale: list[dict]) -> dict:
    facts = {
        "slots": 3, "filled": 0, "missing": [], "hints": [],
        "stale": newly_stale, "staleEntries": all_stale,
        "added": [], "extras": [],
    }
    return intent_section(facts=facts, contract_file="c.json", present=True)


def test_newly_stale_and_stale_total_are_different_numbers():
    section = _intent_section(
        ["rails:+24V"],
        [{"section": "rails", "object": "+24V"}, {"section": "signals", "object": "S1"}],
    )
    assert section["totals"]["newlyStale"] == 1
    assert section["totals"]["staleTotal"] == 2
    assert "staleEntries" not in section["totals"]

    lines: list[str] = []
    render_intent_markdown(lines, section)
    text = "\n".join(lines)
    assert "本轮新标 stale 1（stale 合计 2，不删只标）" in text
    # The heading counts the same number the delta line calls the total.
    assert "合同里记着、图纸里已没有的对象（2，不删只标）" in text


def test_a_folded_acceptance_mark_raises_the_total_and_not_the_delta():
    section = _intent_section([], [{"section": "rails", "object": "+24V"}])
    cli._fold_accepted_stale(section, [{"part": "U7"}, {"part": "U8"}])
    assert section["totals"]["staleTotal"] == 3
    assert section["totals"]["newlyStale"] == 0


# --------------------------------------------------------------------------
# ⑩ 「契约版本」 is two sentences
# --------------------------------------------------------------------------


def _intent_lines(declared) -> str:
    section = intent_section(
        facts={"slots": 0, "filled": 0, "missing": [], "hints": []},
        contract_file="c.json", present=declared is not None,
        contract_version=1, declared_version=declared,
    )
    lines: list[str] = []
    render_intent_markdown(lines, section)
    return "\n".join(line for line in lines if "契约版本" in line)


def test_an_absent_contract_declares_no_version():
    line = _intent_lines(None)
    assert "文件没声明（本次没有读入合同）" in line
    assert "本 build 读 `intentVersion 1`" in line
    assert "文件声明 `intentVersion" not in line


def test_a_read_contract_declares_its_own_version():
    line = _intent_lines(1)
    assert "文件声明 `intentVersion 1`" in line
    assert "本 build 读 `intentVersion 1`" in line


# --------------------------------------------------------------------------
# ⑪ the accepted section quotes this run's verdict
# --------------------------------------------------------------------------


def test_the_verdict_clause_is_conditional():
    assert "仍是" in accepted_verdict_clause({"verdict": "incomplete"})
    assert "complete-with-open-items" in accepted_verdict_clause(
        {"verdict": "complete-with-open-items"}
    )
    assert "completion.verdict" in accepted_verdict_clause({})


def test_report_md_does_not_claim_the_verdict_left_incomplete():
    entry = di.IntentAccepted(part="U7", reason="接受", board="Board1")
    model = _model_with_board("U7", "Board1")
    rows = [{
        "part": "U7", "state": checkup_engine.STATE_ACCEPTED, "matchedBy": "designator",
        "designator": "U7", "name": "", "value": "", "mpn": "", "supplier": "",
        "reasons": [], "reason": "接受", "who": "t", "when": "t",
        "board": "Board1", "stale": False,
    }]
    markdown = render_report_markdown({
        "accepted_unknown": rows,
        "unreviewed_parts": [],
        "completion": {"verdict": "incomplete"},
    })
    assert "它们不再让 `completion.verdict` 停在 `incomplete`" not in markdown
    assert "本轮 verdict **仍是** `incomplete`" in markdown

    other = render_report_markdown({
        "accepted_unknown": rows,
        "unreviewed_parts": [],
        "completion": {"verdict": "complete-with-open-items"},
    })
    assert "本轮值就是 `complete-with-open-items`" in other
    _ = entry, model


# --------------------------------------------------------------------------
# the corpus-level end-to-end check for ①/⑤: the gate is not shorter than it was
# --------------------------------------------------------------------------


def test_no_fixture_loses_an_unreviewed_row_to_the_token_reading(tmp_path):
    """①/⑤ together: the datasheet gate must not shrink anywhere on the corpus.

    The gate is the review's own contract ("a part no rule could judge stops the
    review"), so a word-reading change that quietly removed rows from it would be
    the one direction this batch must not move in. Compared fixture by fixture
    against the pre-192B reading, reproduced the same way as the kind property
    above.
    """
    from boardwise.parsers.schematic import build_project_model

    shelf = PartLibrary(parts=[])
    old_words = tuple(row for row in DECLARATION_WORDS if row[0] != KIND_IC)

    def substring_hit(text: str, words: tuple[str, ...]) -> str:
        for word in words:
            if word.lower() in text:
                return word
        return ""

    def scan() -> dict[str, int]:
        out: dict[str, int] = {}
        for path in sorted(FIXTURES.glob("*.epro2")):
            try:
                model = build_project_model(path)
            except Exception:  # noqa: BLE001
                continue
            out[path.name] = len(unreviewed_parts(model, library=shelf))
        return out

    after = scan()
    original_hit, original_words = partkind._hit, partkind.DECLARATION_WORDS
    try:
        partkind._hit = substring_hit
        partkind.DECLARATION_WORDS = old_words
        before = scan()
    finally:
        partkind._hit, partkind.DECLARATION_WORDS = original_hit, original_words

    assert before, "the corpus did not load"
    shrank = {name: (before[name], after[name]) for name in before if after[name] < before[name]}
    assert shrank == {}, f"the datasheet gate shrank: {shrank}"
