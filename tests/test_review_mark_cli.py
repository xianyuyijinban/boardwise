"""`boardwise review-mark` (012v2 §八) and the `refs` the review report carries.

Two layers, tested where each one lives:

- **the report** — `render_json` now states each finding's `refs` (derived from
  evidence, allow-listed), and `finding_refs` is what makes that derivation
  predictable. The allow-list is the part worth pinning: `AMS1117`, `SS34` and
  `CH340G` all *look* like designators, and a shape-only rule would send them to
  the canvas as refs that resolve to nothing;
- **the command** — the findings are read from a path / stdin / a literal, one
  mark per ref is sent **in finding order** (that order is what `--focus N`
  counts), and the exit code separates "all on the canvas" from "part of it".
  The daemon is a stub here; nothing in this file needs a socket, let alone an
  editor.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from boardwise.cli import (
    FindingsError,
    _cmd_review_mark,
    _load_findings,
    build_parser,
    marks_from_findings,
)
from boardwise.engines.review import finding_refs, render_json
from boardwise.rules.base import Finding

ROOT = Path(__file__).resolve().parents[1]

#: What `boardwise review --json` writes, trimmed to the fields that matter here.
REPORT = {
    "summary": {"ERROR": 1, "WARN": 1, "INFO": 0},
    "findings": [
        {
            "rule_id": "decoupling-per-ic",
            "severity": "WARN",
            "message": "U1 附近没有去耦电容",
            "level": "L1",
            "evidence": ["U1 pin16 @ 3V3", "C116 pin1 @ VM"],
            "refs": ["U1", "C116"],
        },
        {
            "rule_id": "value-mpn-match",
            "severity": "ERROR",
            "message": "R5 的值与 MPN 不符",
            "level": "L2",
            "evidence": ["R5 pin1 @ FB"],
            "refs": ["R5"],
        },
    ],
}


# --------------------------------------------------------------------------
# the report's refs
# --------------------------------------------------------------------------


def test_finding_refs_reads_evidence_first_and_deduplicates():
    finding = Finding(
        rule_id="decoupling-per-ic",
        severity="WARN",
        message="C116 附近的 C116 重复出现",
        level="L1",
        evidence=["U1 pin16 @ 3V3", "C116 pin1 @ VM"],
    )
    assert finding_refs(finding) == ["U1", "C116"]


@pytest.mark.parametrize(
    "text",
    [
        "AMS1117-3.3 是 LDO",       # a part number, not a designator
        "SS34 的封装不对",           # ditto
        "CH340G 的晶振",             # ditto
        "FRC0805J471 是 470R",       # ditto
        "pin16 @ 3V3 悬空",          # `pin16` and `3V3` are not designators
        "PC14 悬空",                 # an MCU pin name
        "D5V 是电源网络",             # a net name that starts like a diode
    ],
)
def test_designator_shapes_that_must_not_become_refs(text):
    finding = Finding(
        rule_id="x", severity="INFO", message=text, level="L1", evidence=[text]
    )
    assert finding_refs(finding) == [], text


def test_the_reader_keeps_a_real_designator_out_of_a_part_number():
    finding = Finding(
        rule_id="x", severity="WARN", message="缺去耦电容",
        level="L1", evidence=["AMS1117-3.3", "C116 pin1 @ VM"],
    )
    assert finding_refs(finding) == ["C116"]


def test_render_json_states_the_refs_of_every_finding():
    payload = json.loads(render_json([
        Finding(rule_id="decoupling-per-ic", severity="WARN", message="U1 缺电容",
                level="L1", evidence=["C116 pin1 @ VM"]),
    ]))
    # Evidence first, then the message — and both are read: a rule that names the
    # IC in prose and the capacitor in evidence should mark both.
    assert payload["findings"][0]["refs"] == ["C116", "U1"]
    # The rule's own fields are untouched — refs is an addition, not a rewrite.
    assert payload["findings"][0]["rule_id"] == "decoupling-per-ic"
    assert payload["findings"][0]["evidence"] == ["C116 pin1 @ VM"]


# --------------------------------------------------------------------------
# findings -> marks
# --------------------------------------------------------------------------


def test_one_mark_per_ref_in_finding_order():
    marks, skipped = marks_from_findings(REPORT["findings"])
    assert skipped == []
    assert [(mark["ref"], mark["ruleId"], mark["severity"]) for mark in marks] == [
        ("U1", "decoupling-per-ic", "WARN"),
        ("C116", "decoupling-per-ic", "WARN"),
        ("R5", "value-mpn-match", "ERROR"),
    ]
    assert [mark["finding"] for mark in marks] == [1, 1, 2]
    assert marks[0]["text"] == "U1 附近没有去耦电容"


def test_a_report_without_refs_still_marks_by_reading_the_evidence():
    # The field was added with the action; a report written before it must keep
    # working, because the reports on disk are the reason to run this at all.
    findings = [{key: value for key, value in entry.items() if key != "refs"}
                for entry in REPORT["findings"]]
    marks, _ = marks_from_findings(findings)
    assert [mark["ref"] for mark in marks] == ["U1", "C116", "R5"]


def test_a_finding_with_no_ref_is_skipped_and_counted():
    marks, skipped = marks_from_findings([
        {"rule_id": "duplicate-designators", "severity": "WARN", "message": "位号重复",
         "level": "L1", "evidence": ["设计里出现了两次"]},
        REPORT["findings"][1],
    ])
    assert [mark["ref"] for mark in marks] == ["R5"]
    assert len(skipped) == 1
    assert skipped[0]["finding"] == 1
    assert skipped[0]["ruleId"] == "duplicate-designators"
    assert "没有点名任何位号" in skipped[0]["reason"]


def test_a_declared_ref_string_is_accepted_as_one_ref():
    marks, _ = marks_from_findings([
        {"rule_id": "x", "severity": "INFO", "message": "m", "ref": "C9", "evidence": []},
    ])
    assert [mark["ref"] for mark in marks] == ["C9"]


# --------------------------------------------------------------------------
# reading the findings
# --------------------------------------------------------------------------


def test_findings_come_from_a_path_stdin_or_a_literal(tmp_path, monkeypatch, capsys):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    findings, label = _load_findings(str(path))
    assert len(findings) == 2 and label == str(path)

    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(REPORT)))
    findings, label = _load_findings("-")
    assert len(findings) == 2 and label == "<stdin>"

    findings, label = _load_findings(json.dumps(REPORT["findings"]))
    assert len(findings) == 2

    findings, _ = _load_findings(json.dumps(REPORT["findings"][0]))
    assert len(findings) == 1, "a single finding is a legitimate input too"
    assert capsys.readouterr().out == ""


def test_an_input_that_is_not_a_report_is_refused_with_the_reason(tmp_path):
    with pytest.raises(FindingsError) as missing:
        _load_findings(str(tmp_path / "nope.json"))
    assert "not a file" in str(missing.value)

    with pytest.raises(FindingsError) as broken:
        _load_findings("{not json}")
    assert "is not JSON" in str(broken.value)

    with pytest.raises(FindingsError) as empty:
        _load_findings('{"summary": {"ERROR": 0}}')
    assert "carries no findings" in str(empty.value)

    with pytest.raises(FindingsError) as not_objects:
        _load_findings('{"findings": ["C116"]}')
    assert "must be a JSON object" in str(not_objects.value)


# --------------------------------------------------------------------------
# the command
# --------------------------------------------------------------------------


class _StubReviewMark:
    """A daemon stub that answers `review.mark` from what it was sent."""

    def __init__(self, *, designators=("U1", "C116", "R5"), mode="markers",
                 cleared=bool, zoom_ok=True, fail=None):
        self.designators = set(designators)
        self.mode = mode
        self.cleared = cleared
        self.zoom_ok = zoom_ok
        self.fail = fail
        self.calls = []
        self.params = []

    async def call(self, action, params=None):
        assert action == "review.mark", action
        self.calls.append(action)
        self.params.append(params)
        if self.fail:
            raise self.fail
        if params.get("clear"):
            return {"mode": "markers", "cleared": self.cleared, "count": 0,
                    "marked": [], "unresolved": [], "readOnly": True,
                    "note": "every indicator marker on the focused canvas was removed"}

        marked, unresolved = [], []
        for position, mark in enumerate(params["marks"], 1):
            if mark["ref"] in self.designators:
                marked.append({**mark, "position": position, "marker": len(marked) + 1,
                               "designator": mark["ref"], "primitiveId": f"p-{mark['ref']}",
                               "x": position * 10, "y": position * 20})
            else:
                unresolved.append({**mark, "position": position,
                                   "reason": "no component with this designator on the focused page"})
        payload = {
            "mode": self.mode,
            "cleared": False,
            "page": {"components": len(self.designators), "designators": len(self.designators),
                     "withoutPosition": 0, "active": {"uuid": "page-1", "type": "page"}},
            "count": len(params["marks"]),
            "marked": marked,
            "unresolved": unresolved,
            "markers": {"attempted": len(marked), "accepted": len(marked)},
            "readOnly": True,
            "note": "markers are geometric: generateIndicatorMarkers takes shapes, not text",
        }
        if self.mode == "list":
            payload["markers"] = {"attempted": 0, "accepted": 0,
                                  "reason": "generateIndicatorMarkers() is not available on this editor"}
        focus = params.get("focus")
        if focus is not None:
            target = params["marks"][focus - 1]
            landed = [entry for entry in marked if entry["position"] == focus]
            payload["focused"] = (
                {"position": focus, "ref": target["ref"], "x": landed[0]["x"], "y": landed[0]["y"],
                 "zoomed": self.zoom_ok and bool(landed)} if landed
                else {"position": focus, "ref": target["ref"], "zoomed": False,
                      "reason": "this finding has no position on this page"}
            )
        return payload

    async def close(self):
        pass


@pytest.fixture
def stub_daemon(monkeypatch):
    from boardwise.bridge.protocol import BridgeError

    def install(daemon):
        class Client:
            @classmethod
            async def open(cls, uri, token, role, client=""):
                assert role == "cli"
                return daemon

        monkeypatch.setattr(
            "boardwise.cli._open_cli",
            lambda args: (Client, BridgeError, 61190, "token"),
        )
        return daemon

    return install


def _args(tmp_path, *extra, report=None):
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report or REPORT), encoding="utf-8")
    return build_parser().parse_args(["review-mark", str(path), *extra])


def test_the_marks_are_sent_in_finding_order_and_everything_lands(stub_daemon, capsys, tmp_path):
    daemon = stub_daemon(_StubReviewMark())
    out_path = tmp_path / "marks.json"
    code = _cmd_review_mark(_args(tmp_path, "--json", str(out_path)))
    out = capsys.readouterr().out
    assert code == 0, out
    assert daemon.calls == ["review.mark"]
    sent = daemon.params[0]
    assert [mark["ref"] for mark in sent["marks"]] == ["U1", "C116", "R5"]
    assert sent["clear"] is False
    assert sent["markers"] is True
    assert sent["color"] == "#FF0000"
    assert "pageUuid" not in sent, "no --page means the page is not claimed"
    # `finding` is a CLI-side bookkeeping field; the wire contract is position order.
    assert set(sent["marks"][0]) == {"ref", "ruleId", "severity", "text"}
    assert "marker#1" in out and "marker#3" in out
    assert "全部到位" in out
    assert "review-mark clear" in out
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["complete"] is True
    assert written["response"]["marked"][0]["ref"] == "U1"


def test_a_ref_that_is_not_on_the_page_makes_it_partial(stub_daemon, capsys, tmp_path):
    stub_daemon(_StubReviewMark(designators=("C116",)))
    code = _cmd_review_mark(_args(tmp_path))
    out = capsys.readouterr().out
    assert code == 1
    assert "未打标" in out
    assert "no component with this designator" in out
    assert "部分到位" in out


def test_a_degraded_host_is_reported_as_degraded(stub_daemon, capsys, tmp_path):
    stub_daemon(_StubReviewMark(mode="list"))
    code = _cmd_review_mark(_args(tmp_path))
    out = capsys.readouterr().out
    assert code == 1, "a jump list is not the same answer as markers on the canvas"
    assert "降级为跳转清单" in out
    assert "generateIndicatorMarkers() is not available" in out


def test_a_finding_with_no_ref_makes_it_partial_and_says_which(stub_daemon, capsys, tmp_path):
    stub_daemon(_StubReviewMark())
    report = {"findings": [
        *REPORT["findings"],
        {"rule_id": "x", "severity": "INFO", "message": "无位号", "level": "L1", "evidence": []},
    ]}
    code = _cmd_review_mark(_args(tmp_path, report=report))
    out = capsys.readouterr().out
    assert code == 1
    assert "发现 #3" in out
    assert "没有点名任何位号" in out


def test_focus_is_forwarded_and_its_answer_is_reported(stub_daemon, capsys, tmp_path):
    daemon = stub_daemon(_StubReviewMark())
    code = _cmd_review_mark(_args(tmp_path, "--focus", "2"))
    out = capsys.readouterr().out
    assert code == 0
    assert daemon.params[0]["focus"] == 2
    assert "跳转到第 2 条 C116：已缩放" in out


def test_a_refused_zoom_is_reported_without_failing_the_run(stub_daemon, capsys, tmp_path):
    stub_daemon(_StubReviewMark(zoom_ok=False))
    code = _cmd_review_mark(_args(tmp_path, "--focus", "1"))
    out = capsys.readouterr().out
    assert code == 0, "the marks landed; only the zoom did not"
    assert "未缩放" in out


def test_page_no_markers_and_zoom_reach_the_action(stub_daemon, tmp_path):
    daemon = stub_daemon(_StubReviewMark())
    code = _cmd_review_mark(_args(tmp_path, "--page", "page-1", "--no-markers", "--zoom",
                                "--color", "#00FF00"))
    assert code == 0
    sent = daemon.params[0]
    assert sent["pageUuid"] == "page-1"
    assert sent["markers"] is False
    assert sent["zoom"] is True
    assert sent["color"] == "#00FF00"


def test_a_report_with_no_markable_ref_never_calls_the_daemon(tmp_path, capsys):
    report = {"findings": [{"rule_id": "x", "severity": "INFO", "message": "m",
                            "level": "L1", "evidence": ["设计里出现了两次"]}]}
    code = _cmd_review_mark(_args(tmp_path, report=report))
    out = capsys.readouterr().err
    assert code == 1
    assert "没有可标记的位号" in out
    assert "没有调用编辑器" in out


def test_bad_findings_exit_2_before_any_socket(tmp_path, capsys):
    args = build_parser().parse_args(["review-mark", str(tmp_path / "missing.json")])
    assert _cmd_review_mark(args) == 2
    assert "not a file" in capsys.readouterr().err


def test_clear_sends_only_the_clear_flag(stub_daemon, capsys, tmp_path):
    daemon = stub_daemon(_StubReviewMark(cleared=True))
    args = build_parser().parse_args(["review-mark", "clear"])
    code = _cmd_review_mark(args)
    out = capsys.readouterr().out
    assert code == 0
    assert daemon.params[0]["clear"] is True
    assert "marks" not in daemon.params[0]
    assert "已清除" in out


def test_clear_that_the_canvas_refuses_is_exit_1(stub_daemon, capsys, tmp_path):
    stub_daemon(_StubReviewMark(cleared=False))
    args = build_parser().parse_args(["review-mark", "clear"])
    code = _cmd_review_mark(args)
    assert code == 1
    assert "画布拒绝清除" in capsys.readouterr().out


def test_a_daemon_side_refusal_is_reported_as_exit_1(stub_daemon, capsys, tmp_path):
    from boardwise.bridge.protocol import BridgeError

    stub_daemon(_StubReviewMark(fail=BridgeError("PAGE_MISMATCH", "the focused page is X, not Y")))
    code = _cmd_review_mark(_args(tmp_path, "--page", "page-other"))
    err = capsys.readouterr().err
    assert code == 1
    assert "PAGE_MISMATCH" in err


def test_no_daemon_exits_2(tmp_path, capsys, monkeypatch):
    # The real transport, a port nothing listens on: doctor/review-mark must
    # report it, not raise.
    args = build_parser().parse_args(
        ["review-mark", "clear", "--port", "1"]
    )
    code = _cmd_review_mark(args)
    assert code == 2
    assert "daemon not reachable" in capsys.readouterr().err
