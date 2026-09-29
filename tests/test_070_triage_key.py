"""070 (issue #13): a triage key is an identity — and two warnings cannot share one.

063 made `warning_triage[]`'s `key` the row's stable identity so a verdict can be
written against it and survive a re-run. Issue #13 measured the flaw underneath:
the key was built from `refs`, and `refs` is a **heuristic** — a allow-list of
prefixes applied to prose — so it leaks. `EC` was not on that list, and
`param-value-mpn-match` writes its designator only into the message, so `refs`
came back empty and the key degenerated to `boardwise-rule:param-value-mpn-match:`.
Two findings on `EC1` and `EC3` then shared that one key and a single `triage`
command wrote one verdict into both parts — while the structured
`target.component_ref` naming each part sat right there in the finding, unread.

What this file pins, in the order the fix was ruled (岳's three recommendations):

* the key reads the finding's **structured** identity first (`target`), and only
  falls back to the prose refs recipe 063 had;
* `finding_refs` reads `target.component_ref` too — which is the same reading
  `review-mark` marks the canvas with, so a finding that names its part only in
  its target gets a mark again (the second symptom of one root cause);
* a collision that survives every structured field is **suffixed** `#2`/`#3` in a
  deterministic order and said out loud in the report's notes — never silent;
* the issue's own path end to end: two same-rule findings on two parts, one
  verdict, the other part untouched, through `checkup` → `triage` → `checkup`.

The board is **synthetic** — a minimal `.epru` inside a real ZIP, built here (no
fixture from ``tests/fixtures/``, no editor, no daemon). Its two electrolytic
capacitors carry a board value that contradicts their (decodable) MPN, which is
what makes `param-value-mpn-match` report them exactly as the issue reports them.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import boardwise.cli as cli
from boardwise.cli import marks_from_findings
from boardwise.core.model import DesignModel
from boardwise.engines.checkup import (
    disambiguated_triage_keys,
    triage_key,
    warning_triage_slots,
)
from boardwise.engines.review import DESIGNATOR_PREFIXES, finding_refs
from boardwise.rules.base import Finding, FindingTarget

WARN_RULE = "param-value-mpn-match"

#: The MPN decodes to the EIA code `107` = 100 uF while the board declares 1 uF:
#: 100x apart, well past the 25x capacitor tolerance, so the rule reports a WARN
#: on each part that carries it. This is the #13 shape — one rule, one warning
#: per part, and a designator (`EC1`) whose prefix the prose reader never knew.
#:
#: **Re-pointed by 071 §1 C, and this is the reason.** The board's parts used to
#: carry ``GRM31CR61A107ME19L``, a Murata part whose size is spelled ``31`` —
#: Murata's *own* two-figure code, which is not one of the industry's size
#: spellings (four-figure imperial, three-figure metric). Under the anchor gate a
#: reading that carries no syntactic anchor may not accuse a BOM line, so that
#: MPN now answers UNKNOWN on the two capacitors (the shape #25 measured:
#: electrolytics whose digits are not a code field) and the #13 key scenario —
#: two warnings of ONE rule, one verdict each — would have lost its subject.
#: ``CC1206KKX7R0BB107`` states the same 100 uF with the package size ``1206``
#: *in* the token, so the reading is anchored and the warnings come back exactly
#: as the issue reports them. ``test_the_unanchored_electrolytic_shape_is_unknown``
#: below pins what happened to the retired spelling, so the change is a
#: measurement rather than a memory.
MPN = "CC1206KKX7R0BB107"
RETIRED_MPN = "GRM31CR61A107ME19L"
PARTS = [("EC1", "1uF"), ("EC3", "1uF"), ("R7", "10k")]


# --------------------------------------------------------------------------
# a synthetic board: two electrolytic capacitors that contradict their MPN
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    """One `.epru` line: a JSON envelope, `||`, a JSON body, `|`."""
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol(uuid: str, pins: list[tuple[str, float, float]]) -> list[str]:
    out = [_record("DOCHEAD", {"docType": "SYMBOL", "uuid": uuid, "editVersion": "3.2.149"}),
           _record("META", {"title": "CAP", "docType": "SYMBOL"}, id_="meta-1")]
    for index, (number, x, y) in enumerate(pins):
        pin_id = f"{uuid}-pin{index}"
        out.append(_record("PIN", {"x": x, "y": y, "zIndex": index + 2}, id_=pin_id))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
                           id_=f"{pin_id}-n"))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Name", "value": f"P{number}"},
                           id_=f"{pin_id}-name"))
    return out


def _board(tmp_path: Path) -> Path:
    """A one-page `.epro2` whose parts declare a value their MPN contradicts."""
    lines = [_record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": "page-1"}),
             _record("CANVAS", {"originX": 0, "originY": 0, "unit": "0.01inch"}, id_="canvas-1")]
    lines += _symbol("sym-cap", [("1", 0.0, 0.0), ("2", 20.0, 0.0)])
    for index, (designator, value) in enumerate(PARTS):
        part = f"inst-{designator}"
        x, y = 300.0 + index * 200.0, -500.0
        lines.append(_record("COMPONENT", {"partId": part, "x": x, "y": y, "rotation": 0,
                                          "isMirror": False, "zIndex": 10}, id_=f"c-{part}"))
        for key, val, mark in (("Designator", designator, "d"), ("Symbol", "sym-cap", "s"),
                               ("Value", value, "v"), ("Manufacturer Part", MPN, "m")):
            lines.append(_record("ATTR", {"parentId": part, "key": key, "value": val},
                                 id_=f"{mark}-{part}"))
        group = f"grp-{index}"
        lines.append(_record("WIRE", {"zIndex": 40}, id_=group))
        lines.append(_record("LINE", {"lineGroup": group, "startX": x, "startY": y,
                                      "endX": x + 100.0, "endY": y}))
        lines.append(_record("ATTR", {"parentId": group, "key": "NET", "value": f"SIG_{index}"},
                             id_=f"net-{index}"))
    path = tmp_path / "synth_ec.epro2"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


# --------------------------------------------------------------------------
# helpers: the real commands, offline
# --------------------------------------------------------------------------


def _checkup(board: Path, out: Path) -> dict:
    code = cli.main(["checkup", "--file", str(board), "--out", str(out)])
    assert code == 0, f"checkup exited {code} on the synthetic board"
    return _read(out)


def _triage(out: Path, *argv: str) -> int:
    return cli.main(["triage", "--out", str(out), *argv])


def _read(out: Path) -> dict:
    return json.loads((out / "report.json").read_text(encoding="utf-8"))


def _keys(report: dict) -> list[str]:
    return [str(slot.get("key") or "") for slot in report["warning_triage"]]


def _slot_keys(slots: list[dict]) -> list[str]:
    return [str(slot.get("key") or "") for slot in slots]


def _slot(report: dict, key: str) -> dict:
    return next(slot for slot in report["warning_triage"] if slot.get("key") == key)


def _verdict_of(report: dict, key: str) -> str:
    return str(_slot(report, key).get("verdict") or "")


def _clean_board(monkeypatch) -> None:
    """Lift the datasheet trigger, so the warnings are the only open items left.

    Same isolation `test_063` uses: the three synthetic parts have no shelf entry,
    so the facts gate alone holds `completion.verdict` at `incomplete`. Nothing
    about the triage path under test changes.
    """
    monkeypatch.setattr(cli, "unreviewed_parts", lambda *args, **kwargs: [])


def _sidecar(out: Path) -> dict:
    return json.loads((out / "warning-triage.json").read_text(encoding="utf-8"))


def _warn(rule_id: str, *, refs: list[str], target: dict | None, message: str = "") -> dict:
    """A report finding as `checkup` carries it: the dataclass fields plus refs."""
    return {
        "source": "boardwise-rule",
        "rule_id": rule_id,
        "severity": "WARN",
        "message": message or f"{target and target.get('component_ref')}: a warning",
        "level": "L2-facts",
        "evidence": [],
        "refs": refs,
        "target": target,
    }


# --------------------------------------------------------------------------
# ① the key reads the structured identity first (岳's recommendation 1)
# --------------------------------------------------------------------------


def test_two_findings_of_one_rule_on_different_parts_get_their_own_keys():
    """#13 itself: same rule, **empty evidence**, two parts — two identities.

    This is the collision the issue measured. `refs` here is what the pre-070
    reading produced for both findings (the designator prefix was not on the
    allow-list and the evidence was empty), so a key built from `refs` alone
    collapses the two rows into one — which is why the fix reads `target`.
    """
    ec3 = _warn(WARN_RULE, refs=[], target={"component_ref": "EC3", "pin_refs": [],
                                            "net_refs": []})
    ec1 = _warn(WARN_RULE, refs=[], target={"component_ref": "EC1", "pin_refs": [],
                                            "net_refs": []})
    keys = [
        triage_key(slot, rule_id=WARN_RULE, refs=slot["refs"], target=slot["target"])
        for slot in (ec3, ec1)
    ]
    assert keys == [
        f"boardwise-rule:{WARN_RULE}:EC3",
        f"boardwise-rule:{WARN_RULE}:EC1",
    ]
    assert keys[0] != keys[1], "one key for two parts is what let one verdict fill both"
    assert f"boardwise-rule:{WARN_RULE}:" not in keys, "the degenerate key is gone"


def test_the_target_is_read_before_the_prose_and_the_refs_are_only_a_fallback():
    """Structured identity first; `refs` (the 063 recipe) is the fallback."""
    with_target = _warn(WARN_RULE, refs=["R99"], target={
        "component_ref": "EC3", "pin_refs": ["2"], "net_refs": ["VIN"],
    })
    assert triage_key(with_target, rule_id=WARN_RULE, refs=with_target["refs"],
                      target=with_target["target"]) == (
        f"boardwise-rule:{WARN_RULE}:EC3,pin:2,net:VIN"
    )
    # A finding with no structured target at all keeps the 063 recipe verbatim,
    # so keys an existing sidecar was written against do not move.
    prose_only = _warn(WARN_RULE, refs=["R7"], target=None)
    assert triage_key(prose_only, rule_id=WARN_RULE, refs=prose_only["refs"]) == (
        f"boardwise-rule:{WARN_RULE}:R7"
    )


def test_pins_and_nets_keep_two_findings_on_one_part_apart():
    """A rule that reports per pin (a decoupling rail) is not one warning."""
    first = _warn("decap-required-caps", refs=["U21"], target={
        "component_ref": "U21", "pin_refs": ["8"], "net_refs": ["NET178"],
    })
    second = _warn("decap-required-caps", refs=["U21"], target={
        "component_ref": "U21", "pin_refs": ["19"], "net_refs": ["3V3"],
    })
    keys = [
        triage_key(slot, rule_id=slot["rule_id"], refs=slot["refs"], target=slot["target"])
        for slot in (first, second)
    ]
    assert keys == [
        "boardwise-rule:decap-required-caps:U21,pin:8,net:NET178",
        "boardwise-rule:decap-required-caps:U21,pin:19,net:3V3",
    ]
    assert keys[0] != keys[1], "one part, two pins, two rails: two warnings"


def test_the_identity_ignores_pin_and_net_order():
    """Same rail written in another order is the same warning, not a second one."""
    forward = _warn(WARN_RULE, refs=[], target={
        "component_ref": "U1", "pin_refs": ["9", "2"], "net_refs": ["3V3", "VIN"],
    })
    backward = _warn(WARN_RULE, refs=[], target={
        "component_ref": "U1", "pin_refs": ["2", "9"], "net_refs": ["VIN", "3V3"],
    })
    keys = {
        triage_key(slot, rule_id=WARN_RULE, refs=slot["refs"], target=slot["target"])
        for slot in (forward, backward)
    }
    assert keys == {f"boardwise-rule:{WARN_RULE}:U1,pin:2,pin:9,net:3V3,net:VIN"}


# --------------------------------------------------------------------------
# ② finding_refs reads the same structure (岳's recommendation 2) — and so
#    does `review-mark`, which reads the refs the same way
# --------------------------------------------------------------------------


def test_finding_refs_reads_the_structured_target_when_the_evidence_is_empty():
    """The ref the finding always had, finally read — `EC3` with no prose at all."""
    finding = Finding(
        rule_id=WARN_RULE, severity="WARN", message="no designator in this prose",
        level="L2-facts", evidence=[],
        target=FindingTarget(component_ref="EC3"),
    )
    assert finding_refs(finding) == ["EC3"]


def test_a_real_designator_is_read_even_when_the_allow_list_never_named_its_prefix():
    """`EC` is a designator prefix (issue #13) — the shelf's `C` does not cover it."""
    assert "EC" in DESIGNATOR_PREFIXES
    finding = Finding(
        rule_id=WARN_RULE, severity="WARN", message="something else entirely",
        level="L2-facts", evidence=["EC5 pin1 @ VIN"],
    )
    assert finding_refs(finding) == ["EC5"]


def test_a_repairable_finding_marks_the_canvas_through_its_target():
    """The second symptom of the same root cause: `review-mark` lost the mark too.

    An older report carries the finding without a `refs` field at all, so the
    marks are derived here — from the target, because the prose has no
    designator to read (`param-value-mpn-match`'s evidence is empty on the board
    the issue was measured on).
    """
    marks, skipped = marks_from_findings([
        {"rule_id": WARN_RULE, "severity": "WARN", "message": "board value contradicts its MPN",
         "level": "L2-facts", "evidence": [],
         "target": {"component_ref": "EC3", "pin_refs": [], "net_refs": []}},
    ])
    assert skipped == []
    assert [(mark["ref"], mark["ruleId"], mark["severity"]) for mark in marks] == [
        ("EC3", WARN_RULE, "WARN"),
    ]
    # A finding with neither a target nor a readable ref is still *reported* as
    # unmarkable rather than silently dropped (the 012 contract, unchanged).
    _marks, still_skipped = marks_from_findings([
        {"rule_id": "x", "severity": "INFO", "message": "无位号", "level": "L1",
         "evidence": [], "target": None},
    ])
    assert len(still_skipped) == 1


# --------------------------------------------------------------------------
# ③ the uniqueness assertion (岳's recommendation 3): suffixed, deterministic,
#    and never silent
# --------------------------------------------------------------------------


def _identical_findings(count: int) -> list[dict]:
    """`count` findings that are **identical in every identity field**."""
    return [
        _warn(WARN_RULE, refs=["U9"], target={"component_ref": "U9"},
              message="同一个判定，出现两次")
        for _ in range(count)
    ]


def test_a_surviving_collision_is_suffixed_in_a_deterministic_order():
    """Two rows with one identity: `#2`/`#3`, same keys on a second run."""
    slots = warning_triage_slots(
        model=DesignModel(), drc={}, findings=_identical_findings(3), modules=[]
    )
    base = f"boardwise-rule:{WARN_RULE}:U9"
    assert _slot_keys(slots) == [base, f"{base}#2", f"{base}#3"]
    assert disambiguated_triage_keys(slots) == [base]
    again = warning_triage_slots(
        model=DesignModel(), drc={}, findings=_identical_findings(3), modules=[]
    )
    assert _slot_keys(again) == _slot_keys(slots), "同输入同 key：并表才能并上"
    # Nothing else about the rows is touched: the suffix is the key and only the key.
    assert [slot["text"] for slot in slots] == [slot["text"] for slot in again]


def test_the_collision_is_said_out_loud_in_the_report_notes(capsys, tmp_path, monkeypatch):
    """A suffixed key that nobody is told about is the silent collision again.

    `checkup` never produces two identical identities on a real board (the
    structured identity covers them), so the rule engine is stubbed here to hand
    it exactly that — the note is what is under test, not the rule. The stub
    takes ``**kwargs`` because `checkup` hands the runner a collector for broken
    rules (#30 fork 2).
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, out = _board(tmp_path), tmp_path / "out"
    monkeypatch.setattr(
        cli, "run_review",
        lambda model, **kwargs: [
            Finding(rule_id=WARN_RULE, severity="WARN", message="同一个判定", level="L2-facts",
                    evidence=[], target=FindingTarget(component_ref="U9"))
        ] * 2,
    )
    report = _checkup(board, out)
    capsys.readouterr()

    base = f"boardwise-rule:{WARN_RULE}:U9"
    assert _keys(report) == [base, f"{base}#2"]
    note = next(
        (note for note in report["source"]["notes"] if "身份完全相同" in note), None
    )
    assert note is not None, "the suffix must show up in the report, not only in the key"
    assert base in note and "#2" in note and "issue #13" in note


# --------------------------------------------------------------------------
# ④ issue #13's own path: two parts, one verdict, and the second part is not it
# --------------------------------------------------------------------------


def test_issue_13_two_findings_of_one_rule_get_two_verdicts(capsys, tmp_path, monkeypatch):
    """The regression the issue asks for, through the real commands."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    _clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    before = _checkup(board, out)
    capsys.readouterr()

    keys = _keys(before)
    assert keys == [
        f"boardwise-rule:{WARN_RULE}:EC1",
        f"boardwise-rule:{WARN_RULE}:EC3",
        f"boardwise-rule:{WARN_RULE}:R7",
    ], "each part is one warning, because the key is an identity and not a heuristic"
    assert before["completion"]["warningsPendingTriage"] == 3

    ec1, ec3 = keys[0], keys[1]
    assert _triage(out, "--key", ec1, "--verdict", "无害", "--reason", "1uF 是设计值，料号该改") == 0
    printed = capsys.readouterr().out
    assert f"（1 条槽位）" in printed, "one command, one warning — the issue's own symptom is gone"

    judged = _read(out)
    assert _verdict_of(judged, ec1) == "无害"
    assert _verdict_of(judged, ec3) == "", "the other part keeps its own, still-empty judgement"
    assert _verdict_of(judged, keys[2]) == ""
    assert judged["completion"]["warningsPendingTriage"] == 2

    # Judging the second one differently is the whole point of `verdict` — and it
    # is exactly what the shared key used to make impossible.
    assert _triage(out, "--key", ec3, "--verdict", "有害", "--reason", "这颗真错了") == 0
    capsys.readouterr()
    after = _checkup(board, out)
    printed = capsys.readouterr().out
    assert (_verdict_of(after, ec1), _verdict_of(after, ec3)) == ("无害", "有害")
    assert _verdict_of(after, keys[2]) == ""
    assert after["completion"]["warningsPendingTriage"] == 1
    assert "已并入 2 条" in printed
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "| 无害 | 1uF 是设计值，料号该改 |" in markdown
    assert "| 有害 | 这颗真错了 |" in markdown


def test_a_sidecar_key_from_before_the_fix_is_reported_and_never_migrated(
    capsys, tmp_path, monkeypatch
):
    """The degenerate key stays an audit trail (裁决 4): 未匹配如实报，不发明迁移."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    _clean_board(monkeypatch)
    board, out = _board(tmp_path), tmp_path / "out"
    keys = _keys(_checkup(board, out))
    capsys.readouterr()

    degenerate = f"boardwise-rule:{WARN_RULE}:"
    entries = [
        {"key": degenerate, "verdict": "无害", "reason": "旧退化 key 上的判定",
         "source": "boardwise-rule", "text": "EC3 或 EC1，说不清是哪颗"},
        {"key": keys[1], "verdict": "有益", "reason": "真 EC3 的判定",
         "source": "boardwise-rule", "text": "EC3"},
    ]
    (out / "warning-triage.json").write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False), encoding="utf-8"
    )

    after = _checkup(board, out)
    printed = capsys.readouterr().out
    notes = " ".join(after["source"]["notes"])

    assert _verdict_of(after, keys[1]) == "有益", "the key that still identifies a row merges"
    assert degenerate not in _keys(after)
    assert all(_verdict_of(after, key) == "" for key in keys if key != keys[1]), (
        "the degenerate judgement is not spread onto the rows it might have meant"
    )
    assert "1 条分诊结论已并入" in notes
    assert "1 条分诊结论没有对应槽位" in notes and "不删" in notes
    assert "已并入 1 条" in printed and "另 1 条没匹配上" in printed
    # checkup never writes that file: the audit trail is the triage command's.
    assert _sidecar(out)["entries"] == entries

def test_the_unanchored_electrolytic_shape_is_unknown():
    """071 §1 C, pinned where this file felt it: the retired MPN stops accusing.

    ``GRM31CR61A107ME19L`` is a real 100 uF part and its ``107`` really is the
    EIA code for 100 uF — and that is exactly the case the anchor gate answers
    with silence: Murata's ``31`` is a *manufacturer's* size spelling, not one of
    the industry's (four-figure imperial / three-figure metric), so the reading
    carries no syntactic anchor and may not be the only witness against a BOM
    line. A part whose token states the size (``CC1206KKX7R0BB107``, the MPN the
    tests above use) says the same 100 uF and is allowed to warn.

    This is the #25 shape measured on this repository's own part numbers
    (``UVR1H101MPD``, ``50YXF100MEFC``, ``EEU-FC1H101`` …), and it is why the
    board above had to be re-pointed rather than the gate loosened again.
    """
    from boardwise.core.model import Component, DesignModel, Pin
    from boardwise.rules.params import ValueMpnMatch

    def decision(mpn: str) -> tuple[str, str]:
        model = DesignModel()
        model.components["EC1"] = Component(
            uid="ec1", designator="EC1", value="1uF", mpn=mpn,
            pins=[Pin("1", "A", "SIG")],
        )
        rule = ValueMpnMatch()
        findings = rule.check(model)
        outcomes = {o.state: o for o in rule.outcomes(model)}
        return (
            findings[0].severity if findings else "-",
            outcomes["UNKNOWN"].message if "UNKNOWN" in outcomes else "",
        )

    severity, message = decision(RETIRED_MPN)
    assert severity == "-", "no warning: an unanchored reading may not accuse"
    assert "字符串解码无锚点，低置信" in message
    assert "107" in message, "the row still says what it read, it just does not accuse"
    assert decision(MPN)[0] == "WARN", "the anchored spelling of the same value warns"
