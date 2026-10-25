"""537C3b2a: merge one live capture into the six-channel evidence section.

Why this file exists. ``engines.liveevidence`` (537C3b1) collects four live
channels plus an identity reading and a focus-restore record, but nothing joins
that capture to the ledger ``engines.evidence`` (537C3a) already produced. The
merge is the narrow, pure function that does it:

* only the four live channels are replaced —
  ``liveSchematic / livePcb / schematicImage / pcbImage``; ``archivePcb`` and
  ``datasheets`` keep their rows **verbatim**;
* the capture's machine-readable metadata (schema/ok/executor/identity/
  selection/focusRestore/artifacts/steps) is stored at the section root under
  ``liveCapture``, deep-copied and **not** merged into ``channels``;
* ``coverage`` still has exactly six entries, derived from the six rows;
* ``delivery`` additionally derives two non-channel disclosures, in the frozen
  order after the six channels:

  - unverified identity -> ``live-identity-unverified`` (``missing`` without an
    identity error, ``failed`` with one) — ``capture.ok`` cannot cancel it;
  - a focus restore that is not ``ok`` -> ``live-focus-restore-failed``
    (``failed``) — an ``attempted: false`` / ``unavailable`` record is still a
    disclosure, never silence.

A ``need-datasheet`` refresh must keep ``liveCapture`` and recompute delivery
from it, or the two disclosures would vanish exactly when a report is re-gated.
The Markdown and console fallbacks must consider ``liveCapture`` too, so a
section that lost ``delivery`` cannot fall back to a false ``complete``.

All data here is anonymous and synthetic: no editor, daemon, project file,
netlist or image. This stick adds a pure function and renderings only; it does
not write reports or finalize anything.
"""

from __future__ import annotations

import copy

import pytest

EVIDENCE_SCHEMA = "boardwise.review-evidence/1"
LIVE_SCHEMA = "boardwise.live-evidence/1"

CHANNELS = [
    "liveSchematic",
    "archivePcb",
    "livePcb",
    "schematicImage",
    "pcbImage",
    "datasheets",
]
LIVE_CHANNELS = ["liveSchematic", "livePcb", "schematicImage", "pcbImage"]
SOURCES = {
    "liveSchematic": "live-sch",
    "archivePcb": "archive",
    "livePcb": "live-pcb",
    "schematicImage": "image",
    "pcbImage": "image",
    "datasheets": "datasheet",
}
META_KEYS = (
    "schema",
    "ok",
    "executor",
    "identity",
    "selection",
    "focusRestore",
    "artifacts",
    "steps",
)
CLOSED = {"ok", "not-applicable"}


def _ev():
    """Lazy import: a missing new API fails on behaviour, not collection."""
    from boardwise.engines import evidence

    return evidence


# ---------------------------------------------------------------------------
# synthetic sections / captures
# ---------------------------------------------------------------------------


def _row(name: str, status: str = "ok") -> dict:
    return {
        "status": status,
        "source": SOURCES[name],
        "detail": f"synthetic detail for {name} ({status})",
        "artifacts": [],
        "errors": [],
        "steps": [],
    }


def _evidence(statuses: dict | None = None) -> dict:
    """The C3a section shape, with sentinels that must survive the merge."""
    all_statuses = {name: "ok" for name in CHANNELS}
    all_statuses.update(statuses or {})
    statuses = all_statuses
    channels = {name: _row(name, statuses[name]) for name in CHANNELS}
    channels["archivePcb"].update({
        "detail": "归档 PCB 审查 1 块板：pcb_review.available=true 且 boards 非空",
        "artifacts": [{"title": "B1", "components": 3, "copperLayers": 2}],
        "errors": ["archive-note"],
        "steps": [{
            "action": "pcb.review",
            "status": "ok",
            "stdout": "{}",
            "stderr": "",
            "exitCode": 0,
            "error": None,
        }],
    })
    channels["datasheets"].update({
        "detail": "未审 1 条 / 工程师接受未审（本轮缺口）0 条 / 审查者标记 0 个器件",
        "errors": ["datasheet-note"],
        "steps": [{
            "action": "needs_datasheet",
            "status": "ok",
            "stdout": "{}",
            "stderr": "",
            "exitCode": 0,
            "error": None,
        }],
    })
    return {
        "schema": EVIDENCE_SCHEMA,
        "channels": channels,
        "coverage": {name: channels[name]["status"] for name in CHANNELS},
        "delivery": {
            "status": "partial" if any(
                channels[name]["status"] not in CLOSED for name in CHANNELS
            ) else "complete",
            "note": "delivery 只描述证据/交付覆盖，不是板级通过或不通过。",
            "requiredDisclosures": [],
        },
    }


def _live_row(name: str, status: str = "ok") -> dict:
    return {
        "status": status,
        "source": SOURCES[name],
        "detail": f"live detail for {name} ({status})",
        "artifacts": [{
            "file": f"{name}.png",
            "bytes": 10,
            "sha256": "b" * 64,
        }],
        "errors": [] if status == "ok" else [f"{name}: synthetic failure"],
        "steps": [{
            "documentUuid": "p1",
            "action": "doc.open",
            "status": "ok",
            "stdout": "{}",
            "stderr": "",
            "exitCode": 0,
            "error": None,
        }],
    }


def _capture(
    *,
    statuses: dict | None = None,
    ok: bool = True,
    verified: bool = True,
    identity_ok: bool = True,
    identity_error: dict | None = None,
    focus: dict | None = None,
) -> dict:
    all_statuses = {name: "ok" for name in LIVE_CHANNELS}
    all_statuses.update(statuses or {})
    statuses = all_statuses
    focus = focus or {
        "ok": True,
        "attempted": True,
        "status": "restored",
        "originalUuid": "p1",
        "error": None,
    }
    return {
        "schema": LIVE_SCHEMA,
        "ok": ok,
        "executor": "bridge-client",
        "identity": {
            "ok": identity_ok,
            "expectedProjectUuid": "proj-a",
            "projectUuid": "proj-a",
            "activeUuid": "p1",
            "verifiedAgainstReport": verified,
            "problems": [] if verified else [
                "doc.list 没有可读的 focused projectUuid：本次不声称已核实同一设计"
            ],
            "error": identity_error,
        },
        "selection": {
            "ok": True,
            "schematic": {
                "explicit": False,
                "requested": [],
                "available": ["p1"],
                "selected": ["p1"],
                "unknown": [],
                "coversAll": True,
            },
            "pcb": {
                "explicit": False,
                "requested": [],
                "available": ["b1"],
                "selected": ["b1"],
                "unknown": [],
                "coversAll": True,
            },
            "error": None,
        },
        "channels": {name: _live_row(name, statuses[name]) for name in LIVE_CHANNELS},
        "steps": [{
            "documentUuid": "p1",
            "action": "doc.open",
            "status": "ok",
            "stdout": "{}",
            "stderr": "",
            "exitCode": 0,
            "error": None,
        }],
        "artifacts": [{"file": "cap.png", "bytes": 10, "sha256": "c" * 64}],
        "focusRestore": focus,
    }


def _codes(section: dict) -> list[str]:
    return [row["code"] for row in section["delivery"]["requiredDisclosures"]]


def _extras(section: dict) -> list[dict]:
    return [
        row for row in section["delivery"]["requiredDisclosures"]
        if not row.get("channel")
    ]


def _merged(evidence: dict | None = None, capture: dict | None = None) -> dict:
    return _ev().merge_live_capture(
        evidence if evidence is not None else _evidence(),
        capture if capture is not None else _capture(),
    )


# ---------------------------------------------------------------------------
# 1. the merge itself: four live rows replaced, everything else preserved
# ---------------------------------------------------------------------------


def test_merge_replaces_the_four_live_channels_and_keeps_the_section_shape():
    evidence = _evidence()
    capture = _capture()
    merged = _merged(evidence, capture)

    assert merged is not evidence
    assert merged["schema"] == EVIDENCE_SCHEMA
    # Exactly the six channels, in the frozen order — no seventh "identity" row.
    assert list(merged["channels"]) == CHANNELS
    assert list(merged["coverage"]) == CHANNELS
    assert merged["coverage"] == {
        name: merged["channels"][name]["status"] for name in CHANNELS
    }

    for name in LIVE_CHANNELS:
        assert merged["channels"][name] == capture["channels"][name], name
        assert merged["channels"][name] is not capture["channels"][name]
    for name in ("archivePcb", "datasheets"):
        assert merged["channels"][name] == evidence["channels"][name], name

    # The capture metadata lives at the section root, under `liveCapture`.
    assert set(merged["liveCapture"]) == set(META_KEYS)
    assert merged["liveCapture"] == {key: capture[key] for key in META_KEYS}
    assert "channels" not in merged["liveCapture"]

    # All six closed + verified identity + restored focus -> complete, no rows.
    assert merged["delivery"]["status"] == "complete"
    assert merged["delivery"]["requiredDisclosures"] == []
    # `capture.ok` is copied, never recomputed into a board-level conclusion.
    assertive = _merged(_evidence(), _capture(ok=False))
    assert assertive["liveCapture"]["ok"] is False


def test_archive_and_datasheet_rows_survive_the_merge_verbatim():
    evidence = _evidence({"datasheets": "unavailable"})
    capture = _capture()

    merged = _merged(evidence, capture)

    for name in ("archivePcb", "datasheets"):
        assert merged["channels"][name] == evidence["channels"][name]
        assert merged["channels"][name] is not evidence["channels"][name]
    assert merged["channels"]["archivePcb"]["artifacts"] == [
        {"title": "B1", "components": 3, "copperLayers": 2}
    ]
    assert merged["channels"]["archivePcb"]["errors"] == ["archive-note"]
    assert merged["channels"]["archivePcb"]["steps"][0]["action"] == "pcb.review"
    assert merged["channels"]["datasheets"]["errors"] == ["datasheet-note"]
    assert merged["coverage"]["datasheets"] == "unavailable"
    assert merged["coverage"]["archivePcb"] == "ok"


def test_a_failed_live_channel_keeps_its_detail_artifacts_errors_and_steps():
    capture = _capture(statuses={"livePcb": "failed", "pcbImage": "missing"})
    capture["channels"]["livePcb"] = {
        "status": "failed",
        "source": "live-pcb",
        "detail": "实时 PCB 回读失败：READBACK_PROBLEMS；几何/出图仍保留",
        "artifacts": [{"file": "pcb-partial.png", "bytes": 123, "sha256": "d" * 64}],
        "errors": ["pcb.readback (b1): READBACK_PROBLEMS: 退出码 0 但读数不可用"],
        "steps": [
            {
                "documentUuid": "b1",
                "action": "pcb.readback",
                "status": "failed",
                "stdout": "{}",
                "stderr": "READBACK_PROBLEMS",
                "exitCode": 1,
                "error": {"code": "READBACK_PROBLEMS", "message": "读数不可用"},
            },
            {
                "documentUuid": "b1",
                "action": "export.render",
                "status": "ok",
                "stdout": "{}",
                "stderr": "",
                "exitCode": 0,
                "error": None,
            },
        ],
    }

    merged = _merged(_evidence(), capture)
    row = merged["channels"]["livePcb"]

    assert row == capture["channels"]["livePcb"]
    assert row["artifacts"][0]["file"] == "pcb-partial.png"
    assert row["steps"][0]["error"]["code"] == "READBACK_PROBLEMS"
    assert merged["coverage"]["livePcb"] == "failed"
    disclosure = next(
        item for item in merged["delivery"]["requiredDisclosures"]
        if item.get("channel") == "livePcb"
    )
    assert disclosure["code"] == "live-pcb-evidence"
    assert disclosure["status"] == "failed"
    assert "实时 PCB 回读失败" in disclosure["message"]


# ---------------------------------------------------------------------------
# 2. identity / focusRestore — two non-channel disclosures
# ---------------------------------------------------------------------------


def test_unverified_identity_forces_partial_even_when_capture_ok_and_six_closed():
    evidence = _evidence()
    ev = _ev()
    assert ev.evidence_delivery(evidence["channels"])["status"] == "complete"

    capture = _capture(verified=False, identity_ok=True)
    assert capture["ok"] is True
    assert capture["identity"]["ok"] is True

    merged = _merged(evidence, capture)
    extras = _extras(merged)

    assert merged["delivery"]["status"] == "partial"
    assert [row["code"] for row in extras] == ["live-identity-unverified"]
    assert extras[0]["status"] == "missing"
    assert extras[0]["source"] == "liveCapture"
    assert extras[0]["channel"] is None
    assert "未核实" in extras[0]["message"]
    assert "同一报告" in extras[0]["message"] or "设计" in extras[0]["message"]
    assert "capture.ok" in extras[0]["message"]
    # The extra disclosure is not a seventh coverage channel.
    assert set(merged["coverage"]) == set(CHANNELS)
    assert "identity" not in merged["channels"]

    # An identity error is a failed disclosure (not `missing`) and carries its code.
    error = {
        "code": "PROJECT_IDENTITY_MISMATCH",
        "message": "焦点工程 'proj-b' 与报告期望 'proj-a' 不一致：拒绝导航",
        "expected": "proj-a",
        "actual": "proj-b",
    }
    merged_error = _merged(
        evidence,
        _capture(verified=False, identity_ok=False, identity_error=error),
    )
    failed = _extras(merged_error)
    assert [row["code"] for row in failed] == ["live-identity-unverified"]
    assert failed[0]["status"] == "failed"
    assert "PROJECT_IDENTITY_MISMATCH" in failed[0]["message"]
    assert "不一致" in failed[0]["message"]
    assert merged_error["delivery"]["status"] == "partial"


def test_focus_restore_failure_is_disclosed_even_when_not_attempted():
    focus = {
        "ok": False,
        "attempted": False,
        "status": "unavailable",
        "originalUuid": None,
        "error": {
            "code": "FOCUS_UNAVAILABLE",
            "message": "doc.list 的 active.uuid 不可读，无法保证恢复原焦点：未调用 doc.open",
        },
    }
    merged = _merged(_evidence(), _capture(focus=focus))
    extras = _extras(merged)

    assert merged["delivery"]["status"] == "partial"
    assert [row["code"] for row in extras] == ["live-focus-restore-failed"]
    assert extras[0]["status"] == "failed"
    assert extras[0]["source"] == "liveCapture"
    assert "FOCUS_UNAVAILABLE" in extras[0]["message"]
    assert "active.uuid 不可读" in extras[0]["message"]
    assert "unavailable" in extras[0]["message"]

    # An attempted restore that failed carries that error too.
    failed_focus = {
        "ok": False,
        "attempted": True,
        "status": "failed",
        "originalUuid": "p1",
        "error": {"code": "DOC_OPEN_FAILED", "message": "doc.open 失败"},
    }
    failed_msg = _extras(_merged(_evidence(), _capture(focus=failed_focus)))[0]
    assert "DOC_OPEN_FAILED" in failed_msg["message"]
    assert "doc.open 失败" in failed_msg["message"]


def test_extra_disclosures_follow_the_six_channels_in_identity_then_focus_order():
    capture = _capture(
        statuses={"livePcb": "failed", "pcbImage": "missing"},
        verified=False,
        focus={"ok": False, "attempted": True, "status": "failed",
               "originalUuid": "p1",
               "error": {"code": "DOC_OPEN_FAILED", "message": "doc.open 失败"}},
    )
    merged = _merged(_evidence(), capture)
    rows = merged["delivery"]["requiredDisclosures"]

    assert [row["code"] for row in rows] == [
        "live-pcb-evidence",
        "pcb-visual-review",
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]
    assert [row["channel"] for row in rows[:2]] == ["livePcb", "pcbImage"]
    assert all(row["channel"] is None for row in rows[2:])
    assert all(row["source"] == "liveCapture" for row in rows[2:])
    assert set(merged["coverage"]) == set(CHANNELS)
    assert len(merged["coverage"]) == 6


# ---------------------------------------------------------------------------
# 3. Markdown / console must not hide or mangle the extra disclosures
# ---------------------------------------------------------------------------


def test_markdown_and_console_show_extra_disclosures_without_a_channel_none():
    ev = _ev()
    merged = _merged(
        _evidence(),
        _capture(
            verified=False,
            focus={"ok": False, "attempted": True, "status": "failed",
                   "originalUuid": "p1",
                   "error": {"code": "DOC_OPEN_FAILED", "message": "doc.open 失败"}},
        ),
    )

    markdown = "\n".join(ev.render_evidence_markdown(merged))
    for code in ("live-identity-unverified", "live-focus-restore-failed"):
        assert f"`{code}`" in markdown
    assert "channel=None" not in markdown
    assert "`None`" not in markdown
    assert "liveCapture" in markdown

    line = ev.evidence_console_line(merged)
    assert line.startswith("evidence: partial (")
    assert "live-identity-unverified" in line
    assert "live-focus-restore-failed" in line
    assert "None" not in line

    # The fallback path must see `liveCapture` too: without `delivery` it must
    # not fall back to a false `complete`, and the extra codes must still show.
    fallback = copy.deepcopy(merged)
    fallback.pop("delivery")
    fallback_markdown = "\n".join(ev.render_evidence_markdown(fallback))
    assert "live-identity-unverified" in fallback_markdown
    assert "live-focus-restore-failed" in fallback_markdown
    fallback_line = ev.evidence_console_line(fallback)
    assert fallback_line.startswith("evidence: partial")
    assert "live-identity-unverified" in fallback_line
    assert "live-focus-restore-failed" in fallback_line


# ---------------------------------------------------------------------------
# 4. need-datasheet refresh keeps the capture and its disclosures
# ---------------------------------------------------------------------------


def test_refresh_datasheets_keeps_live_capture_and_only_moves_the_datasheet_channel():
    ev = _ev()
    evidence = _evidence()  # datasheets starts closed
    merged = _merged(
        evidence,
        _capture(
            verified=False,
            focus={"ok": False, "attempted": True, "status": "failed",
                   "originalUuid": "p1",
                   "error": {"code": "DOC_OPEN_FAILED", "message": "doc.open 失败"}},
        ),
    )
    assert _codes(merged) == [
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]
    before_live = {name: copy.deepcopy(merged["channels"][name]) for name in LIVE_CHANNELS}
    before_archive = copy.deepcopy(merged["channels"]["archivePcb"])
    before_capture = copy.deepcopy(merged["liveCapture"])

    refreshed = ev.refresh_datasheets(
        merged, needs_datasheet=[{"trigger": "marked", "part": "U1", "pin": "1"}]
    )

    assert refreshed["coverage"]["datasheets"] == "unavailable"
    assert refreshed["delivery"]["status"] == "partial"
    assert _codes(refreshed) == [
        "datasheet-evidence",
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]
    assert refreshed["liveCapture"] == before_capture
    for name in LIVE_CHANNELS:
        assert refreshed["channels"][name] == before_live[name]
    assert refreshed["channels"]["archivePcb"] == before_archive

    # A pre-C3b evidence section never grows a `liveCapture` from a re-gate.
    old = _evidence()
    assert "liveCapture" not in old
    old_refreshed = ev.refresh_datasheets(
        old, needs_datasheet=[{"trigger": "marked", "part": "U1", "pin": "1"}]
    )
    assert "liveCapture" not in old_refreshed
    assert "datasheet-evidence" in _codes(old_refreshed)


# ---------------------------------------------------------------------------
# 5. bad input is refused, and a merge never mutates its arguments
# ---------------------------------------------------------------------------


def test_malformed_evidence_or_capture_is_rejected():
    ev = _ev()
    good_evidence = _evidence()
    good_capture = _capture()

    bad_evidence: list[object] = [None, {}]
    case = copy.deepcopy(good_evidence)
    case["schema"] = "boardwise.review-evidence/0"
    bad_evidence.append(case)
    case = copy.deepcopy(good_evidence)
    del case["channels"]["datasheets"]
    bad_evidence.append(case)
    case = copy.deepcopy(good_evidence)
    case["channels"]["livePcb"] = "ok"
    bad_evidence.append(case)
    case = copy.deepcopy(good_evidence)
    case["channels"]["archivePcb"]["status"] = "pass"
    bad_evidence.append(case)
    case = copy.deepcopy(good_evidence)
    case["channels"]["liveSchematic"]["status"] = "done"
    bad_evidence.append(case)

    for bad in bad_evidence:
        with pytest.raises(ValueError):
            ev.merge_live_capture(bad, good_capture)

    bad_capture: list[object] = [None, {}]
    case = copy.deepcopy(good_capture)
    case["schema"] = "boardwise.live-evidence/0"
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    del case["channels"]["pcbImage"]
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    case["channels"]["livePcb"] = ["ok"]
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    case["channels"]["schematicImage"]["status"] = "done"
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    del case["identity"]
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    del case["focusRestore"]
    bad_capture.append(case)
    case = copy.deepcopy(good_capture)
    case["channels"]["liveSchematic"]["status"] = None
    bad_capture.append(case)

    for bad in bad_capture:
        with pytest.raises(ValueError):
            ev.merge_live_capture(good_evidence, bad)


def test_merge_does_not_mutate_its_inputs_and_does_not_alias_the_capture():
    ev = _ev()
    evidence = _evidence()
    capture = _capture(verified=False)
    evidence_snapshot = copy.deepcopy(evidence)
    capture_snapshot = copy.deepcopy(capture)

    merged = ev.merge_live_capture(evidence, capture)
    assert evidence == evidence_snapshot
    assert capture == capture_snapshot

    merged["channels"]["livePcb"]["detail"] = "changed"
    merged["channels"]["livePcb"]["artifacts"][0]["file"] = "changed.png"
    merged["channels"]["archivePcb"]["artifacts"].append({"title": "injected"})
    merged["liveCapture"]["identity"]["verifiedAgainstReport"] = True
    merged["liveCapture"]["steps"][0]["action"] = "changed"

    assert evidence == evidence_snapshot
    assert capture == capture_snapshot


# ---------------------------------------------------------------------------
# 6. old sections: no liveCapture means exactly the C3a behaviour
# ---------------------------------------------------------------------------


def test_old_evidence_without_live_capture_keeps_c3a_delivery_and_rendering():
    ev = _ev()
    evidence = _evidence({"livePcb": "missing", "pcbImage": "missing"})
    channels = evidence["channels"]
    delivery = ev.evidence_delivery(channels)

    assert delivery["status"] == "partial"
    assert [row["code"] for row in delivery["requiredDisclosures"]] == [
        "live-pcb-evidence",
        "pcb-visual-review",
    ]
    assert ev.evidence_delivery(channels, live_capture=None) == delivery

    evidence["delivery"] = delivery
    line = ev.evidence_console_line(evidence)
    assert line == "evidence: partial (livePcb=missing, pcbImage=missing)"

    markdown = "\n".join(ev.render_evidence_markdown(evidence))
    assert "liveCapture" not in markdown
    assert "live-identity-unverified" not in markdown
    assert "live-focus-restore-failed" not in markdown
    assert "`livePcb`" in markdown


# ---------------------------------------------------------------------------
# 7. a present-but-unusable liveCapture fails closed
# ---------------------------------------------------------------------------


def test_a_present_but_empty_live_capture_fails_closed():
    ev = _ev()
    evidence = _evidence()
    channels = evidence["channels"]
    assert ev.evidence_delivery(channels)["status"] == "complete"

    delivery = ev.evidence_delivery(channels, live_capture={})
    assert delivery["status"] == "partial"
    assert [row["code"] for row in delivery["requiredDisclosures"]] == [
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]
    assert [row["status"] for row in delivery["requiredDisclosures"]] == [
        "missing",
        "failed",
    ]

    # A report that carries an empty `liveCapture` cannot be refreshed into a
    # `complete`: the record is present, and present-but-unreadable is not
    # "no collection".
    evidence["liveCapture"] = {}
    refreshed = ev.refresh_datasheets(evidence, needs_datasheet=[])
    assert refreshed["liveCapture"] == {}
    assert refreshed["delivery"]["status"] == "partial"
    assert [row["code"] for row in refreshed["delivery"]["requiredDisclosures"]] == [
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]

    # Rendering without `delivery` falls back and must not claim complete either.
    refreshed.pop("delivery")
    line = ev.evidence_console_line(refreshed)
    assert line.startswith("evidence: partial")
    assert "live-identity-unverified" in line
    assert "live-focus-restore-failed" in line
    markdown = "\n".join(ev.render_evidence_markdown(refreshed))
    assert "`live-identity-unverified`" in markdown
    assert "`live-focus-restore-failed`" in markdown


@pytest.mark.parametrize("bad_capture", [[], "", 0, False, "capture", ["x"]])
def test_a_present_non_dict_live_capture_fails_closed(bad_capture):
    ev = _ev()
    channels = _evidence()["channels"]

    delivery = ev.evidence_delivery(channels, live_capture=bad_capture)
    assert delivery["status"] == "partial"
    assert [row["code"] for row in delivery["requiredDisclosures"]] == [
        "live-identity-unverified",
        "live-focus-restore-failed",
    ]

    # `None` is the one value that means "pre-C3b, no capture at all".
    assert ev.evidence_delivery(channels, live_capture=None)["status"] == "complete"
