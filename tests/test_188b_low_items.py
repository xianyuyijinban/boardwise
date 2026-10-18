"""188B: the 185/186 low items — payload names, doctor's fixes, gate traces, index reads.

Fourteen small fixes, one file, grouped by where they live rather than by batch:

* **cli.py** — the `--json` payloads of `need-datasheet`/`triage` name the
  five-field section beside the old string (低2); doctor stops sending a reader
  with a stale window id to re-open an extension that is attached (低3); the
  `--facts` sidecar is compared with the command line and warned about without
  being refused (186 中3); a recursively nested JSON leaves as exit 2 rather than
  a traceback (186 低1); `--json` is written **before** the shelf, so a json write
  that cannot land leaves the shelf byte-identical (186 低4); `parts select
  --write` without `--library` writes to the shelf the read resolved, in the exe
  as well as the checkout (187B 遗留4);
* **checkup.py** — `conclusion.mayQuotePassed` (低4), the category half of "the
  shelf judged it" and the trace of the rows that left the list (186 中2/中1);
* **daemon.py / docs** — `ping` is daemon-owned and never consults a hint (低7);
  the SOP names the conclusion sentence by its heading, states the
  `exitCode 0 ≠ 可投板` rule, and says what to do with a pre-185 report (低5/低6);
* **tools** — a `--staged` run scans the **index** blobs, not the working tree
  (186 低3), and the word gate's docstring says the list must spell out every
  spelling of a word (186 低6/低7).

The fixtures are synthetic and use **neutral** codes (R4b): no real project name
or part number is typed here. The one board read is a tracked synthetic fixture,
and its part's name is taken from the board's own record. Nothing here touches
the live bridge, the daemon on 61190, or the repository's own shelf.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.parts import (
    PartEntry,
    PartLibrary,
    entry_to_json,
    load_parts,
    save_parts,
)
from boardwise.engines.checkup import (
    CONCLUSION_KEYS,
    UNKNOWN_REASON_UNCATEGORISED,
    UNREVIEWED_CLEARING_NOTE,
    conclusion_section,
    render_report_markdown,
    reviewed_by_shelf,
    shelf_judgement,
    unreviewed_clearing_note,
    unreviewed_parts,
)

REPO = Path(__file__).resolve().parents[1]
SHELF = REPO / "blocklib" / "parts.json"
SOP = REPO / "docs" / "review-sop.md"
BRIDGE_DOC = REPO / "docs" / "bridge.md"

#: The neutral stand-in used wherever a part has to be named. No real project
#: name, board name or part number is typed into this file (R4b); the one board a
#: test reads is reached through `test_186_pdf_facts_path`'s own fixture helper,
#: which reads the name off that board's record. Every `ACME-*` string below is
#: synthetic on purpose.

#: The uuid pair 039's schema demands of an entry a rule acts on (test_186's
#: helpers, same values: one synthetic pair, spelled once).
DEVICE_UUID = "0123456789abcdef0123456789abcdef"
LIBRARY_UUID = "fedcba9876543210fedcba9876543210"

FACTS = {
    "nc_pins": {"pins": ["2"], "provenance": "file:acme.pdf p.3"},
    "supply_pins": [
        {"pins": ["1"], "name": "VIN", "v_operating": [2.2, 5.5],
         "provenance": "file:acme.pdf p.3"}
    ],
}


def _verified_flags() -> list[str]:
    return [
        "--verified",
        "--device-uuid", DEVICE_UUID,
        "--library-uuid", LIBRARY_UUID,
    ]


def _facts_file(tmp_path: Path) -> Path:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(FACTS, ensure_ascii=False), encoding="utf-8")
    return path


def _entry(key: str, *, mpn: str = "", lcsc: str = "C1", category: str = "",
           facts: dict | None = None, verified: bool = True) -> PartEntry:
    return PartEntry(
        key=key,
        mpn=mpn,
        lcsc=lcsc,
        category=category,
        deviceUuid=DEVICE_UUID,
        libraryUuid=LIBRARY_UUID,
        facts=dict(facts) if facts else None,
        facts_trust="verified" if verified else "candidate",
    )


def _shelf(tmp_path: Path, *entries: PartEntry) -> Path:
    path = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=list(entries)), path)
    return path


def _checkup(board: Path, shelf: Path, out: Path, monkeypatch, home: Path) -> dict:
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    code = cli.main([
        "checkup", "--file", str(board), "--out", str(out), "--library", str(shelf),
    ])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert code in (0, 1, 3), f"checkup exited {code}"
    return report


def _name_only_fixture():
    """``(board, designator, device name)`` — borrowed from 186's own fixture.

    The name-only part is a property of that board's record, so it is read from
    the board rather than spelled here (test_186's argument, unchanged): a real
    part number typed into a test file is the leak this repository gates on.
    """
    import test_186_pdf_facts_path as pdf186

    return pdf186._name_only_fixture()


#: A report shaped like one `checkup` writes, with exactly the two things the
#: re-gate commands need — a `needs_datasheet` worklist and one untriaged warning
#: slot. Hand-built on purpose: `need-datasheet` / `triage` are **pure file
#: operations** (058 §三 / issue #12), so the payload they emit is a property of
#: this dict and needs no board, no library and no fixture.
def _seed_report(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "boardwise.checkup/7",
        "generatedAt": "2026-10-16T00:00:00+0800",
        "source": {"tier": "file", "tierLabel": "离线文件"},
        "model": {"components": 1, "nets": 0, "designators": ["U1"]},
        "summary": {
            "errorCount": 0, "errors": [], "exitCode": 0, "mayClaimPassed": False,
            "unreviewedParts": 1,
            "conclusion": "不能写「通过」：1 颗器件缺手册未审",
        },
        "pending": {},
        "drc": {}, "modules": [], "findings": [],
        "unreviewed_parts": [{
            "designator": "U1", "mpn": "", "supplier": "", "reasons": ["无 MPN"],
            "isIc": True, "onShelf": False, "shelfKey": "", "shelfMatchedBy": "",
            "factsPresent": [], "missingFacts": ["supply_pins"], "channels": {},
        }],
        "needs_datasheet": [{
            "part": "U1", "pins": [], "trigger": "facts", "reason": "无 MPN",
            "dependentFindings": [], "factSeed": True, "boards": [], "channels": {},
            "mpn": "", "supplier": "", "missingFacts": ["supply_pins"],
        }],
        "warning_triage": [{
            "key": "boardwise-rule:demo-rule:U1", "rule_id": "demo-rule",
            "severity": "WARN", "verdict": "", "reason": "",
        }],
        "completion": {
            "verdict": "incomplete",
            "verdictWhy": ["1 颗器件缺手册未审", "1 条 warning 待分诊"],
            "unreviewedParts": 1, "warningsPendingTriage": 1, "errors": 0,
        },
    }
    path = out / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 低2 — the payloads name the section beside the old string
# --------------------------------------------------------------------------


def test_need_datasheet_json_carries_the_conclusion_section(tmp_path, monkeypatch):
    """`--json` gains `conclusionSection`; the old `conclusion` string stays.

    The payload carried `"conclusion"` as the **narrow** `summary.conclusion`
    sentence while the report had a section of the same name five fields wide —
    one word, two shapes, and a consumer that read the payload's `conclusion`
    expecting the section got a string. The section is added under its own name
    and the string is untouched (CLI keys are only ever added).
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    _seed_report(out)
    payload_path = tmp_path / "need.json"
    assert cli.main([
        "need-datasheet", "--out", str(out), "--part", "U1",
        "--reason", "图上读不出的在位功能", "--json", str(payload_path),
    ]) == 0

    payload = _read(payload_path)
    written = _read(out / "report.json")
    assert tuple(payload["conclusionSection"]) == CONCLUSION_KEYS
    assert payload["conclusionSection"] == written["conclusion"]
    assert isinstance(payload["conclusion"], str), (
        "旧 `conclusion` 键的含义动了：它是窄义 summary.conclusion 字符串"
    )
    assert payload["conclusion"] == written["summary"]["conclusion"]


def test_triage_json_carries_the_conclusion_section(tmp_path, monkeypatch):
    """The same addition on `triage --json-path` (`--json` is its alias)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    report = _read(_seed_report(out))
    payload_path = tmp_path / "triage.json"
    assert cli.main([
        "triage", "--out", str(out), "--key", report["warning_triage"][0]["key"],
        "--verdict", "无害", "--reason", "对本板功能无影响",
        "--json-path", str(payload_path),
    ]) == 0

    payload = _read(payload_path)
    written = _read(out / "report.json")
    assert tuple(payload["conclusionSection"]) == CONCLUSION_KEYS
    assert payload["conclusionSection"] == written["conclusion"]
    assert isinstance(payload["conclusion"], str)
    # The alias spelling of the same flag (`--json`) lands the same payload.
    alias_path = tmp_path / "triage2.json"
    report = _read(_seed_report(tmp_path / "out2"))
    assert cli.main([
        "triage", "--out", str(tmp_path / "out2"),
        "--key", report["warning_triage"][0]["key"],
        "--verdict", "无害", "--reason", "同上", "--json", str(alias_path),
    ]) == 0
    assert _read(alias_path)["conclusionSection"] == _read(
        tmp_path / "out2" / "report.json"
    )["conclusion"]


# --------------------------------------------------------------------------
# 低3 — doctor's fix for a hint that named nothing
# --------------------------------------------------------------------------


def test_the_stale_and_not_connected_fixes_point_at_the_window_table():
    """Both codes get their own sentence, and neither blames the extension.

    `INSTANCE_STALE` is a stale id (the connector re-mints one per handshake) and
    `PROJECT_NOT_CONNECTED` is a project no online window has open; the extension
    is attached in both cases, so "先让扩展连上" would send the reader somewhere
    they have nothing to do — the mistake issue #6 fixed for
    `WINDOW_UNSPECIFIED`, one code over.
    """
    from boardwise.cli import CONNECTOR_FIX, MULTI_WINDOW_FIX, _connector_fix

    stale = _connector_fix("[INSTANCE_STALE] no live window answers to 'inst-gone'")
    gone = _connector_fix("[PROJECT_NOT_CONNECTED] no window has project 'x' open")
    for fix, code in ((stale, "INSTANCE_STALE"), (gone, "PROJECT_NOT_CONNECTED")):
        assert fix not in (CONNECTOR_FIX, MULTI_WINDOW_FIX), code
        assert "bridge status" in fix and "windows[]" in fix, fix
        assert "立创 EDA Pro" not in fix, fix
    assert "--instance" in stale and "重取在线窗口 id" in stale
    assert "--project" in gone
    # An unrecognised error keeps the sentence it always had: a code nobody has
    # given a story is not evidence for one.
    assert _connector_fix("[CONNECTOR_ERROR] the page refused") == CONNECTOR_FIX
    assert _connector_fix("") == CONNECTOR_FIX


# --------------------------------------------------------------------------
# 低4 — mayQuotePassed, the one boolean a script may gate on
# --------------------------------------------------------------------------


def test_may_quote_passed_is_derived_from_the_verdict_alone():
    """`complete` → true, everything else → false, in the writer's own section."""
    complete = conclusion_section({
        "summary": {"exitCode": 0, "mayClaimPassed": True},
        "completion": {"verdict": "complete", "verdictWhy": []},
    })
    open_items = conclusion_section({
        "summary": {"exitCode": 0, "mayClaimPassed": False},
        "completion": {"verdict": "complete-with-open-items", "verdictWhy": ["38 颗器件缺手册未审"]},
    })
    assert complete["mayQuotePassed"] is True
    assert open_items["mayQuotePassed"] is False
    assert complete["exitCode"] == open_items["exitCode"] == 0, (
        "两个状态退出码都是 0 —— 这正是「脚本不能卡 exitCode」那条规则的理由"
    )
    # A report with no `completion` at all says "" and may quote nothing.
    assert conclusion_section({"summary": {}})["mayQuotePassed"] is False


def test_the_sop_says_the_script_rule_and_the_report_may_not_say_passed():
    """The sentence the field exists for is written where the reader looks."""
    sop = SOP.read_text(encoding="utf-8")
    assert "mayQuotePassed" in sop
    assert "exitCode 0 ≠ 可投板" in sop
    assert "脚本判读只看" in sop


# --------------------------------------------------------------------------
# 低5 / 低6 — the SOP's older-report fallback and the head, not the last line
# --------------------------------------------------------------------------


def test_the_sop_stops_calling_the_conclusion_the_last_line():
    """《末行》 was wrong twice: the sentence is under a heading, and the two
    strings come from the same *function*, not from the same call (188B 低6)."""
    sop = SOP.read_text(encoding="utf-8")
    assert "末行" not in sop, "SOP 还在说「末行」——结论句在 `### 整工程能不能投板：` 后面"
    assert "### 整工程能不能投板：" in sop and "后那一句" in sop
    assert "同一函数" in sop and "同一次调用" in sop  # …and says which one it is not


def test_the_comment_no_longer_claims_one_call():
    """`conclusion_section` and the renderer make **two** calls to one function."""
    import re as _re

    def _flat(path: Path) -> str:
        # Docstring prose, not code: wrap width is layout, so compare whole
        # sentences (test_doc_claims' rule for the same problem).
        return _re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))

    checkup_source = _flat(REPO / "src" / "boardwise" / "engines" / "checkup.py")
    assert "the *same call*" not in checkup_source
    assert "Same function, not the same call" in checkup_source
    cli_source = _flat(REPO / "src" / "boardwise" / "cli.py")
    assert "same *function*, not the same *call*" in cli_source


def test_the_sop_says_how_to_read_a_report_without_a_conclusion_section():
    """A pre-185 `report.json` has no section: rebuild it, or read the five."""
    sop = SOP.read_text(encoding="utf-8")
    assert "没有 `conclusion` 节" in sop
    assert "`boardwise checkup`" in sop and "`triage`" in sop
    assert "旧五处顺序" in sop


# --------------------------------------------------------------------------
# 低7 — ping is daemon-owned, so a hint means nothing to it
# --------------------------------------------------------------------------


def test_ping_answers_although_the_hint_names_nothing(tmp_path):
    """The fact docs/bridge.md now states, measured on the real daemon.

    Driven through `handle_request` (no socket, no editor): a daemon-owned action
    is answered before routing, so a `ping` carrying a **stale**
    `targetInstance` comes back `pong: true`. A script that read that as "the
    instance is alive" would gate on the wrong thing — liveness is `windows[]`.
    """
    from test_bridge import TOKEN
    from boardwise.bridge.daemon import BridgeDaemon

    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    reply = asyncio.run(daemon.handle_request(
        "ping", {}, "cli", target_instance="inst-gone", target_project="no-such-project",
    ))
    assert reply["pong"] is True
    assert reply["windows"] == [], "no editor is attached in this test"
    # …and the source says so where the next reader will look.
    source = (REPO / "src" / "boardwise" / "bridge" / "daemon.py").read_text(
        encoding="utf-8"
    )
    assert "No hint is consulted" in source


def test_bridge_doc_says_ping_is_not_an_instance_liveness_probe():
    import re as _re

    doc = _re.sub(r"\s+", " ", BRIDGE_DOC.read_text(encoding="utf-8"))
    assert "A daemon-owned action never consults a hint" in doc
    assert "not a liveness probe for a window" in doc
    assert "bridge status" in doc and "windows[]" in doc
    # And the trap in one line, where a reader scanning the ping list meets it.
    assert "still gets a pong" in doc


# --------------------------------------------------------------------------
# 186 中2 — "the shelf judged it" needs a category as well as facts
# --------------------------------------------------------------------------


def test_the_judgement_needs_facts_and_a_category():
    """An entry with facts but no class is one the rules still refuse."""
    assert shelf_judgement(None) is False
    assert shelf_judgement(_entry("ic.a", facts=FACTS)) is False, (
        "没有 category 的条目规则按 UNKNOWN 答（_category_state）——不算已判"
    )
    assert shelf_judgement(_entry("ic.b", category="ic.ldo")) is False, "没有 facts"
    assert shelf_judgement(
        _entry("ic.c", category="ic.ldo", facts=FACTS)
    ) is True
    # The candidate's facts are held back, so a candidate is never judged
    # whatever its category says (039's gate, unchanged).
    assert shelf_judgement(
        _entry("ic.d", category="ic.ldo", facts=FACTS, verified=False)
    ) is False


def test_no_shipped_entry_loses_its_judged_status_to_the_category_rule():
    """The 全库对拍 before the tightening was accepted (task book's own gate).

    Every entry the old rule judged (`entry.facts is not None`) must still be
    judged, or a part on a shipped board would fall back into 未审 with nobody
    having asked for that — the task book says to **stop and report** in that
    case, so the assertion is here rather than in a shell transcript.
    """
    library = load_parts(SHELF)
    regressed = [
        entry.key for entry in library.parts
        if entry.facts is not None and not shelf_judgement(entry)
    ]
    assert regressed == [], (
        f"收紧后有在库器件从「已判」回退「未审」：{regressed}（停下报，不要硬改）"
    )
    assert sum(1 for entry in library.parts if entry.facts is not None) > 0, (
        "对拍得有料：货架上一个带 facts 的条目都没有，这条就没验到东西"
    )


def test_an_entry_with_facts_but_no_category_is_listed_not_silently_dropped(
    tmp_path, monkeypatch
):
    """The gate's two lists stay complementary: judged, or unreviewed with a reason.

    A part whose entry has facts and no class is **not** judged (the rules answer
    UNKNOWN for it), so it has to appear on the 未审 list with the reason that
    names the real blocker — otherwise the tightening would have moved it from
    "silently judged" to "silently dropped", which is the same gate saying nothing.
    """
    board, designator, name = _name_only_fixture()
    shelf = _shelf(
        tmp_path,
        _entry("ic.by_name", mpn=name, lcsc="C9900001881", facts=FACTS),
    )
    report = _checkup(board, shelf, tmp_path / "out", monkeypatch, tmp_path / "home")
    row = next(
        r for r in report["unreviewed_parts"] if r["designator"] == designator
    )
    assert UNKNOWN_REASON_UNCATEGORISED in row["reasons"], row["reasons"]
    assert designator not in {r["designator"] for r in report["reviewedByShelf"]}
    assert report["summary"]["mayClaimPassed"] is False
    assert UNKNOWN_REASON_UNCATEGORISED in report["summary"]["unreviewedByReason"]
    # …and it is classed as work a datasheet will not fix (「工具读不懂」), because
    # what is missing is a `category` on the entry, not a document to go and find.
    from boardwise.engines.checkup import REASON_CLASS_UNDECODABLE

    assert REASON_CLASS_UNDECODABLE in report["summary"]["unreviewedByClass"]
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert UNKNOWN_REASON_UNCATEGORISED in markdown


# --------------------------------------------------------------------------
# 186 中1 — the name-match disclosure and the trace of the rows that left
# --------------------------------------------------------------------------


def test_a_judged_row_leaves_a_trace_saying_which_identity_step_matched(
    tmp_path, monkeypatch
):
    """`reviewedByShelf` answers "why is this part not on the 未审 list?".

    The entry here is found by **device name** — 186 §B's weaker step, exact but
    weaker than an MPN or a C-number. Before the trace existed the part simply
    disappeared from both lists and the report never said the shelf had claimed
    anything about it, let alone how it had been identified.
    """
    board, designator, name = _name_only_fixture()
    shelf = _shelf(
        tmp_path,
        _entry("ic.by_name", mpn=name, lcsc="C9900001882",
               category="ic.ldo", facts=FACTS),
    )
    report = _checkup(board, shelf, tmp_path / "out", monkeypatch, tmp_path / "home")

    assert designator not in {r["designator"] for r in report["unreviewed_parts"]}
    assert designator not in {row["part"] for row in report["needs_datasheet"]}
    row = next(
        r for r in report["reviewedByShelf"] if r["designator"] == designator
    )
    assert row["shelfKey"] == "ic.by_name"
    assert row["shelfMatchedBy"] == "name", "按器件名命中必须留痕（弱证据）"
    assert row["category"] == "ic.ldo" and row["factsVerified"] is True
    assert row["factsPresent"] == sorted(FACTS)


def test_a_listed_row_matched_by_name_says_so_in_the_report(tmp_path, monkeypatch):
    """The weaker identity is disclosed in `report.md`, from the row's own field."""
    board, designator, name = _name_only_fixture()
    # A **candidate** entry: found by name, facts held back by the gate → the
    # part stays on the list, and the row records how the shelf found it.
    shelf = _shelf(
        tmp_path,
        _entry("ic.by_name", mpn=name, lcsc="C9900001883",
               category="ic.ldo", facts=FACTS, verified=False),
    )
    report = _checkup(board, shelf, tmp_path / "out", monkeypatch, tmp_path / "home")
    row = next(r for r in report["unreviewed_parts"] if r["designator"] == designator)
    assert row["shelfMatchedBy"] == "name"

    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "货架⇢按器件名匹配（弱证据）" in markdown
    assert f"`{designator}`" in markdown.split("货架⇢按器件名匹配")[1].split("\n")[0]
    # A report whose rows carry no such match says nothing about one.
    assert "货架⇢按器件名匹配" not in render_report_markdown({
        "summary": {"unreviewedParts": 0}, "unreviewed_parts": [],
    })


def test_the_trace_and_the_list_come_from_one_chain():
    """The unit half: `reviewed_by_shelf` judges exactly what the list does not.

    One synthetic board, one shell entry: the judged part is in the trace and not
    in the list; the un-judged ones are in the list and not in the trace. That is
    the invariant the two functions share by construction, asserted directly
    rather than through a report file.
    """
    from boardwise.core.model import Component, DesignModel

    library = PartLibrary(parts=[
        _entry("ic.by_mpn", mpn="ACME-JUDGED-1", lcsc="C1",
               category="ic.ldo", facts=FACTS),
        _entry("ic.by_mpn2", mpn="ACME-NO-CAT-1", lcsc="C2", facts=FACTS),
    ])
    model = DesignModel(components={
        "U1": Component(uid="u1", designator="U1", mpn="ACME-JUDGED-1", props={}),
        "U2": Component(uid="u2", designator="U2", mpn="ACME-NO-CAT-1", props={}),
        "U3": Component(uid="u3", designator="U3", mpn="ACME-ON-NO-SHELF", props={}),
    }, nets={})

    judged = {row["designator"] for row in reviewed_by_shelf(model, library=library)}
    listed = {
        row["designator"] for row in unreviewed_parts(model, library=library)
    }
    assert judged == {"U1"}
    assert listed == {"U2", "U3"}
    assert not (judged & listed), "同一颗料不能既算已判又在未审清单里"
    trace = next(
        row for row in reviewed_by_shelf(model, library=library)
        if row["designator"] == "U1"
    )
    assert trace["shelfMatchedBy"] == "mpn" and trace["category"] == "ic.ldo"
    # No shelf at all: nothing was judged, and every part is on the list.
    assert reviewed_by_shelf(model, library=None) == []
    assert len(unreviewed_parts(model, library=None)) == 3


# --------------------------------------------------------------------------
# 186 中3 — the sidecar identity comparison (WARN, never a refusal)
# --------------------------------------------------------------------------


def _sidecar(tmp_path: Path, *, label: str, url: str = "") -> Path:
    path = tmp_path / "acme.candidate.json"
    path.write_text(
        json.dumps({"label": label, "url": url, "facts": FACTS}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_a_sidecar_naming_another_part_warns_without_refusing(capsys, tmp_path):
    """The hand-off 186 §A encourages, with the copy-paste error next to it."""
    shelf = _shelf(tmp_path)
    sidecar = _sidecar(
        tmp_path,
        label="C9900009999 ACME OTHER-PART-9000",
        url="https://datasheet.lcsc.com/datasheet/pdf/x.pdf?productCode=C9900009999",
    )
    code = cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000001",
        "--category", "ic.ldo", "--facts", str(sidecar), "--library", str(shelf),
        *_verified_flags(),
    ])
    assert code == 0, "警告不是拒写（186 中3：不拒）"
    err = capsys.readouterr().err
    assert "WARN" in err and "C9900009999" in err
    assert "ACME-PWR-1000" in err

    entry = load_parts(shelf).parts[0]
    assert entry.facts is not None, "facts 照写"
    assert "188B 中3" in entry.provenance.note, (
        "警告要落进 provenance：只有终端喊一声，审计时什么都不剩"
    )
    assert "C9900009999" in entry.provenance.note


def test_a_sidecar_for_the_same_part_warns_about_nothing(capsys, tmp_path):
    """The control: a matching sidecar writes no warning and no provenance noise."""
    shelf = _shelf(tmp_path)
    sidecar = _sidecar(
        tmp_path,
        label="C9900000001 ACME ACME-PWR-1000",
        url="https://datasheet.lcsc.com/datasheet/pdf/x.pdf?productCode=C9900000001",
    )
    assert cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000001",
        "--category", "ic.ldo", "--facts", str(sidecar), "--library", str(shelf),
        *_verified_flags(),
    ]) == 0
    assert "WARN" not in capsys.readouterr().err
    assert "188B 中3" not in load_parts(shelf).parts[0].provenance.note


def test_the_update_path_records_the_warning_in_provenance(capsys, tmp_path):
    """The other write route (`--facts` onto an entry already on the shelf)."""
    shelf = _shelf(tmp_path, _entry("candidate.acme", lcsc="C9900000002",
                                    mpn="ACME-PWR-1000", verified=False))
    sidecar = _sidecar(tmp_path, label="C9900007777 ACME SOMETHING-ELSE")
    assert cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000002",
        "--category", "ic.ldo", "--facts", str(sidecar), "--library", str(shelf),
        *_verified_flags(),
    ]) == 0
    assert "WARN" in capsys.readouterr().err
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    entry = next(p for p in raw["parts"] if p["key"] == "candidate.acme")
    assert "188B 中3" in entry["provenance"]["note"]
    assert entry["facts"]["nc_pins"], "facts 照写进条目"


# --------------------------------------------------------------------------
# 186 低1 — a recursively nested facts object is bad input, not a traceback
# --------------------------------------------------------------------------


def test_a_recursively_nested_facts_file_exits_two(capsys, tmp_path):
    shelf = _shelf(tmp_path)
    deep = tmp_path / "deep.json"
    depth = 20000  # past what json.loads can decode without a RecursionError
    deep.write_text("[" * depth + "]" * depth, encoding="utf-8")
    code = cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000003",
        "--facts", str(deep), "--library", str(shelf),
    ])
    assert code == 2, "嵌套太深是输入不可用（exit 2），不是崩栈"
    err = capsys.readouterr().err
    assert "RecursionError" in err and "嵌套太深" in err
    assert json.loads(shelf.read_text(encoding="utf-8"))["parts"] == []


def test_a_recursively_nested_fact_value_exits_two(capsys):
    """`--fact` goes through the same parser, so it needs the same guard."""
    args = argparse.Namespace(facts=None, fact=["nc_pins=" + "[" * 20000 + "]" * 20000])
    facts, source, error, warnings = cli._facts_from_flags(args)
    assert not facts and not source and warnings == []
    assert "RecursionError" in error and "nc_pins" in error
    # The control: the same flag spelled sanely is parsed, not refused.
    ok, _src, _error, _warn = cli._facts_from_flags(
        argparse.Namespace(facts=None, fact=['nc_pins={"pins":["2"],"provenance":"file:x p.1"}'])
    )
    assert list(ok) == ["nc_pins"]


# --------------------------------------------------------------------------
# 186 低4 — `--json` is written before the shelf
# --------------------------------------------------------------------------


def test_a_json_write_that_cannot_land_leaves_the_shelf_untouched(capsys, tmp_path):
    """Two writes, one of them optional: the failure must not move the shelf."""
    source = tmp_path / "source.json"
    shutil.copyfile(SHELF, source)
    before = source.read_bytes()
    bad = tmp_path / "no-such-dir" / "out.json"
    code = cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000004",
        "--category", "ic.ldo", "--library", str(source), "--json", str(bad),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "--json 写不了" in err and "货架一个字没动" in err
    assert source.read_bytes() == before, (
        "json 写失败却改了货架 —— 调用方看到 exit 2 而货架已经动了"
    )


def test_the_update_path_has_the_same_order(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry("candidate.acme", lcsc="C9900000005",
                                    mpn="ACME-PWR-1000", verified=False))
    before = shelf.read_bytes()
    assert cli.main([
        "parts", "add", "ACME-PWR-1000", "--lcsc", "C9900000005",
        "--category", "ic.ldo", "--facts", str(_facts_file(tmp_path)),
        "--library", str(shelf), "--json", str(tmp_path / "nope" / "out.json"),
    ]) == 2
    assert "--json 写不了" in capsys.readouterr().err
    assert shelf.read_bytes() == before


def test_a_json_write_that_cannot_be_validated_writes_neither_file(capsys, tmp_path):
    """A document the validator refuses is refused **before** either file exists.

    The `--json` half of the order only stays honest if the shelf document is
    checked first: a json written about a write the validator would then refuse
    would say `ok: true` about nothing. The dry run is
    `_prospective_shelf` — the same validator (`library_from_json`) the write
    re-parses with, one step earlier.
    """
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    out = tmp_path / "out.json"
    broken = json.loads(shelf.read_text(encoding="utf-8"))
    broken["parts"].append({"key": "dup", "lcsc": "C1"})   # duplicate C-number
    prospects, error = cli._prospective_shelf(broken, shelf)
    assert prospects is None and "验证器不认" in error
    assert shelf.read_bytes() == before and not out.exists()
    # The valid document goes through the same door, and produces the answers the
    # json would need (the entry it is about, and the shelf's own count).
    good = json.loads(shelf.read_text(encoding="utf-8"))
    good["parts"].append(entry_to_json(_entry("ic.fresh", lcsc="C9999999")))
    prospects, error = cli._prospective_shelf(good, shelf)
    assert error == "" and prospects.get("ic.fresh") is not None
    assert len(prospects.parts) == len(good["parts"])
    assert shelf.read_bytes() == before, "干跑不许写盘"


# --------------------------------------------------------------------------
# 186 低3 — `--staged` reads the index blobs
# --------------------------------------------------------------------------


def _guard():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_repo_hygiene_188b", REPO / "tools" / "check_repo_hygiene.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, cwd=REPO)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def test_the_index_reader_returns_the_staged_bytes_not_the_working_tree():
    """`git show :<path>` is the read; the working tree is a different answer.

    Of the tracked files here, hundreds differ between the two (line endings
    through `text=auto`), so this is not a distinction that only exists in
    theory — the old `--staged` implementation scanned the tree and reported on
    bytes the commit would not carry.
    """
    guard = _guard()
    blobs = guard.index_blobs()
    tracked = _tracked()
    assert set(blobs) == set(tracked)
    differing = sorted(
        path for path, data in blobs.items()
        if (REPO / path).is_file() and (REPO / path).read_bytes() != data
    )
    assert differing, "这条测试要有区分度：没有任何文件在索引与工作树之间不同"
    sample = differing[0]
    want = subprocess.run(["git", "show", f":{sample}"], capture_output=True, cwd=REPO)
    assert blobs[sample] == want.stdout, "读到的不是索引 blob"
    assert (REPO / sample).read_bytes() != blobs[sample], "读的其实是工作树"


def test_the_word_gate_reads_through_the_reader_it_is_given(tmp_path):
    """The seam itself: with a reader, the working tree is not consulted."""
    guard = _guard()
    (tmp_path / "a.txt").write_text("nothing here\n", encoding="utf-8")
    reader = lambda relative: {  # noqa: E731
        "a.txt": "the ACME word is here".encode("utf-8")
    }.get(relative)
    report = guard.sensitive_report(tmp_path, ["ACME"], ["a.txt"], [], reader)
    assert report["hits"] == ["a.txt:1 (word #1)"]
    # Without one, the same call reads the file on disk and finds nothing.
    assert guard.sensitive_report(tmp_path, ["ACME"], ["a.txt"], [])["hits"] == []


def test_a_staged_run_scans_the_index_and_a_plain_run_the_tree(monkeypatch):
    """Which of the two the command picks, and that it picks by mode."""
    guard = _guard()
    word = "ZZQX-188B-" + "NOT-IN-ANY-FILE"  # 拆写防自命中（hygiene 全库扫描会扫到本文件）
    monkeypatch.setattr(guard, "_word_list", lambda path: ([word], []))
    read: list[str] = []

    def _index_reader(blobs=None):
        def _read(relative):
            read.append(relative)
            return b"nothing to see"

        return _read

    monkeypatch.setattr(guard, "index_reader", _index_reader)
    assert guard.main(["hygiene", "--staged"]) == 0
    assert read, "--staged 没走索引读口"
    read.clear()

    def _refuse(blobs=None):
        raise AssertionError("不是 --staged，却去读了索引")

    monkeypatch.setattr(guard, "index_reader", _refuse)
    assert guard.main(["hygiene"]) == 0
    assert read == []


def test_the_word_list_docstring_says_every_spelling_must_be_written_down():
    source = (REPO / "tools" / "check_repo_hygiene.py").read_text(encoding="utf-8")
    assert "Every spelling has to be listed" in source
    assert "The list must spell out every variant" in source


# --------------------------------------------------------------------------
# 186 低6/低7 — the clearing note names the category and the C-number's source
# --------------------------------------------------------------------------


def test_the_clearing_note_names_the_category_flag_and_the_c_code_source():
    """Since 188B a facts-only entry is not judged, so the instruction needs it."""
    assert "--category <类别>" in UNREVIEWED_CLEARING_NOTE
    assert "C 码来源：立创商城搜索" in UNREVIEWED_CLEARING_NOTE
    extended = unreviewed_clearing_note("blocklib/parts.json")
    assert UNREVIEWED_CLEARING_NOTE in extended
    assert "--category <类别>" in extended and "--library blocklib/parts.json" in extended
    # The console copy of the same instruction (`parts fetch`, when the extractor
    # proposed nothing) has to name the flag too: a reader who follows only that
    # one would otherwise create the very entry this batch stops crediting.
    import boardwise.cli as cli_module

    assert "--category <类别>" in cli_module.EMPTY_FACTS_HINT
    assert "parts add" in cli_module.EMPTY_FACTS_HINT


# --------------------------------------------------------------------------
# 187B 遗留4 — `parts select --write` without `--library`, under a frozen build
# --------------------------------------------------------------------------


@pytest.fixture()
def frozen(monkeypatch, tmp_path):
    """A process shaped exactly like a PyInstaller one-file bundle (187B's)."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


def test_parts_select_write_without_library_lands_in_the_users_shelf(
    frozen, monkeypatch, tmp_path, capsys
):
    """The frozen write path resolves like the read one (187B 遗留4).

    Before this, `--write` with no `--library` handed `None` to `save_parts` —
    `Path(None)`, a TypeError out of the middle of the flow. The destination is
    now `_parts_library_path(writable=True)`: under a frozen build the user's own
    `~/.boardwise/parts.json`, seeded from the bundled shelf, which is the file
    the review reads back.
    """
    import test_select as select_tests
    import boardwise.engines.select as select_module

    from boardwise import resources
    from boardwise.rules.facts import default_library_path

    home = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(home))
    monkeypatch.chdir(frozen)
    bundle = frozen / resources.FROZEN_SUBDIR / "blocklib"
    bundle.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SHELF, bundle / "parts.json")

    select_tests._stub_bridge(
        monkeypatch,
        [{"uuid": "dev-new", "supplierId": "C1234567", "libraryUuid": "lib-1",
          "footprintName": "R0603"}],
    )
    monkeypatch.setattr(select_module, "select", lambda *a, **k: select_tests._fake_result())

    code = cli.main(["parts", "select", "anything", "--resolve", "--write"])
    out = capsys.readouterr().out
    assert code == 0, out
    user_shelf = home / "parts.json"
    assert user_shelf.is_file(), (
        "冻结态的 --write 没写进用户货架（187B 遗留4：读写两端要同一个文件）"
    )
    assert str(user_shelf) in out
    payload = json.loads(user_shelf.read_text(encoding="utf-8"))
    added = next(p for p in payload["parts"] if p["lcsc"] == "C1234567")
    assert added["provenance"]["kind"] == "catalog-select"
    assert len(payload["parts"]) > 1, "用户货架是从内置架复制的，不该只剩新条目"
    assert default_library_path() == str(user_shelf), "写完读侧必须优先它"
