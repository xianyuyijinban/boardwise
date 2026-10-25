"""537C3a: `checkup` 的六通道证据 / 覆盖账.

Why this file exists. The 537 复盘 measured a review that read live schematic,
read the archived PCB, failed to read live PCB and produced no PCB image — and
the final report disclosed **none** of that in a machine-readable place. A reader
could not tell "PCB checked and clean" from "PCB never read", and `partial`
delivery was hidden behind one coarse verdict.

So every `checkup` report now carries a top-level ``evidence`` section:

* ``schema`` — ``boardwise.review-evidence/1``;
* ``channels`` — the frozen six, in a frozen order
  (liveSchematic / archivePcb / livePcb / schematicImage / pcbImage /
  datasheets), each ``{status, source, detail, artifacts, errors, steps}``;
* ``coverage`` — the status of each channel, **derived from** ``channels`` (one
  status map, never a second hand-kept one);
* ``delivery`` — ``complete`` only when every channel is ``ok`` or
  ``not-applicable``, else ``partial``, with a Chinese note that says this is
  **evidence/coverage only, not a board-level pass or fail**, and one
  ``requiredDisclosures[]`` row per open channel.

What these tests pin, in order:

1. the section is always present, additive, and leaves `schema`/`source` alone;
2. each channel's status follows the frozen semantics — "not read" is not
   "failed", "no PCB document" is not "PCB not read";
3. delivery is complete only on all-ok/all-N/A, and it never moves the board
   verdict;
4. the disclosure codes are fixed, ordered, and their messages are specific;
5. `report.json` / `report.md` / `review-summary.md` / stdout are four renderings
   of one section, and the console line is read from the section;
6. a hand-built report with no ``evidence`` renders exactly as before.

All inputs are anonymous/synthetic: a bare ``DesignModel`` / a namespace for the
report-shape tests, synthetic channel payloads for the builder tests, and the
repository's synthetic CH340 fixture for the one end-to-end run. No editor, no
daemon, no real project.
"""

from __future__ import annotations

import json

import re
import types
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import DesignModel
from boardwise.engines.checkup import (
    finding_chains,
    render_report_markdown,
    render_review_summary,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"
LIBRARY = FIXTURES.parent.parent / "blocklib" / "parts.json"

#: The frozen six, in the frozen order. This is a contract, not a convenience:
#: the report, both Markdown products and the console render in exactly this
#: order, and `requiredDisclosures[]` follows it too.
CHANNELS = [
    "liveSchematic",
    "archivePcb",
    "livePcb",
    "schematicImage",
    "pcbImage",
    "datasheets",
]

SOURCES = {
    "liveSchematic": "live-sch",
    "archivePcb": "archive",
    "livePcb": "live-pcb",
    "schematicImage": "image",
    "pcbImage": "image",
    "datasheets": "datasheet",
}

DISCLOSURE_CODES = {
    "liveSchematic": "live-schematic-evidence",
    "archivePcb": "archive-pcb-evidence",
    "livePcb": "live-pcb-evidence",
    "schematicImage": "schematic-visual-review",
    "pcbImage": "pcb-visual-review",
    "datasheets": "datasheet-evidence",
}

STATUSES = {"ok", "failed", "missing", "unavailable", "not-applicable"}
CLOSED_STATUSES = {"ok", "not-applicable"}

EVIDENCE_KEYS = {"schema", "channels", "coverage", "delivery"}
CHANNEL_KEYS = {"status", "source", "detail", "artifacts", "errors", "steps"}
DELIVERY_KEYS = {"status", "note", "requiredDisclosures"}
DISCLOSURE_KEYS = {"code", "channel", "status", "message"}

_AUTO = object()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _evidence_module():
    """Lazy import: the report-shape tests below must fail on behaviour, not on
    a module-level import error at collection time."""
    from boardwise.engines import evidence

    return evidence


def _report(
    monkeypatch,
    tier: str = "project-file",
    *,
    model=_AUTO,
    evidence=_AUTO,
    pcb_review=None,
    unreviewed_parts=None,
    accepted_unknown=None,
    needs_datasheet=None,
    summary_extra: dict | None = None,
) -> dict:
    """One report assembled through the real :func:`boardwise.cli._checkup_report`."""
    monkeypatch.setattr(cli, "_repo_connector_version", lambda: "0.5.21")
    source = {
        "project": {"friendlyName": "synthetic"},
        "pageUuid": None,
        "pageType": None,
        "hostVersion": "3.2.186",
        "connectorVersion": "0.5.21",
        "file": "synthetic.epro2" if tier == "file" else None,
    }
    summary = {
        "errorCount": 0,
        "errors": [],
        "warningCount": 0,
        "warnings": [],
        "infoCount": 0,
        "exitCode": 0,
        "countsIncomplete": False,
    }
    summary.update(summary_extra or {})
    kwargs = {}
    if evidence is not _AUTO:
        kwargs["evidence"] = evidence
    return cli._checkup_report(
        tier=tier,
        source=source,
        model=DesignModel() if model is _AUTO else model,
        attempts=[],
        notes=[],
        drc={},
        findings=[],
        summary=summary,
        modules=[],
        slots={},
        pcb_review=pcb_review,
        unreviewed_parts=unreviewed_parts,
        accepted_unknown=accepted_unknown,
        needs_datasheet=needs_datasheet,
        **kwargs,
    )


def _nonempty_model() -> object:
    """A model-shaped stand-in with two components and two nets.

    `_checkup_report` only reads `.components` / `.nets` /
    `.duplicate_designators` / `.cross_page_designators` off a non-`ProjectModel`
    object, so a namespace is enough and no real project is touched.
    """
    return types.SimpleNamespace(
        components={"R1": object(), "C1": object()},
        nets={"A": object(), "B": object()},
        duplicate_designators=[],
        cross_page_designators={},
    )


def _build(**overrides) -> dict:
    """Build the section through the real builder with synthetic channel inputs."""
    kwargs = dict(
        tier="project-file",
        model_empty=False,
        pcb_had_documents=False,
        pcb_review=None,
        canvas=[],
        unreviewed=[],
        accepted_unknown=[],
        needs_datasheet=[],
    )
    kwargs.update(overrides)
    return _evidence_module().evidence_section(**kwargs)


def _status(evidence: dict, channel: str) -> str:
    return evidence["channels"][channel]["status"]


def _open_channels(evidence: dict) -> list[str]:
    return [
        name
        for name in CHANNELS
        if evidence["coverage"][name] not in CLOSED_STATUSES
    ]


def _codes(evidence: dict) -> list[str]:
    return [row["code"] for row in evidence["delivery"]["requiredDisclosures"]]


def _good_board_pcb_review() -> dict:
    return {
        "available": True,
        "boards": [
            {"title": "B1", "components": 3, "copperLayers": 2, "findings": []},
        ],
        "runner": "synthetic",
        "rules_errored": [],
    }


def _canvas_ok(page: str = "P1") -> list[dict]:
    return [
        {
            "page": page,
            "pageUuid": f"uuid-{page}",
            "file": f"canvas-{page}.png",
            "bytes": 10,
            "sha256": "a" * 64,
        }
    ]


def _canvas_partial() -> list[dict]:
    return [
        {
            "page": "P1",
            "pageUuid": "uuid-P1",
            "file": "canvas-P1.png",
            "bytes": 10,
            "sha256": "a" * 64,
        },
        {
            "page": "P2",
            "pageUuid": "uuid-P2",
            "error": "TIMEOUT: export.render hung",
        },
    ]


def _literal_evidence(statuses: dict | None = None) -> dict:
    """A hand-written section of the frozen shape (render tests only).

    Written out longhand rather than built by the module under test, so the
    renderers are pinned against the **contract**, not against the builder.
    """
    statuses = statuses or {
        "liveSchematic": "ok",
        "archivePcb": "ok",
        "livePcb": "missing",
        "schematicImage": "ok",
        "pcbImage": "missing",
        "datasheets": "ok",
    }
    channels = {}
    for name in CHANNELS:
        channels[name] = {
            "status": statuses[name],
            "source": SOURCES[name],
            "detail": f"detail for {name} ({statuses[name]})",
            "artifacts": [],
            "errors": [],
            "steps": [],
        }
    coverage = {name: statuses[name] for name in CHANNELS}
    partial = [name for name in CHANNELS if statuses[name] not in CLOSED_STATUSES]
    return {
        "schema": "boardwise.review-evidence/1",
        "channels": channels,
        "coverage": coverage,
        "delivery": {
            "status": "partial" if partial else "complete",
            "note": "delivery 只描述证据/交付覆盖，不是板级通过或不通过。",
            "requiredDisclosures": [
                {
                    "code": DISCLOSURE_CODES[name],
                    "channel": name,
                    "status": statuses[name],
                    "message": f"通道 {name} 的证据未采集或不可用（状态 {statuses[name]}）。",
                }
                for name in partial
            ],
        },
    }


def _hand_built_report() -> dict:
    """A report dict of the shape a test (or an older run) builds by hand."""
    return {
        "source": {"tier": "file", "tierLabel": "离线文件（--file）：不连编辑器",
                   "file": "board.epro2", "notes": ["a note"]},
        "model": {"view": "schematic", "components": 0, "nets": 0,
                  "designators": [], "boards": []},
        "summary": {"errorCount": 0, "warnCount": 0, "infoCount": 0,
                    "exitCode": 0, "countsIncomplete": False,
                    "conclusion": "无 ERROR", "errors": [], "warnings": []},
        "drc": {},
        "modules": [],
        "findings": [],
        "ai_slots": {},
    }


def _section_text(markdown: str) -> str:
    """The `## 证据覆盖（evidence）` section, up to the next level-2 heading."""
    start = markdown.index("## 证据覆盖（evidence）")
    rest = markdown[start:]
    match = re.search(r"\n## ", rest)
    return rest if match is None else rest[: match.start()]


# ---------------------------------------------------------------------------
# 1. shape: always present, additive, frozen
# ---------------------------------------------------------------------------


def test_every_checkup_report_carries_the_frozen_evidence_section(monkeypatch):
    report = _report(monkeypatch)
    evidence = report["evidence"]

    assert set(evidence) == EVIDENCE_KEYS
    assert evidence["schema"] == "boardwise.review-evidence/1"
    assert list(evidence["channels"]) == CHANNELS
    for name in CHANNELS:
        row = evidence["channels"][name]
        assert set(row) == CHANNEL_KEYS, (name, set(row))
        assert row["status"] in STATUSES
        assert row["source"] == SOURCES[name]
        assert isinstance(row["detail"], str) and row["detail"]
        assert isinstance(row["artifacts"], list)
        assert isinstance(row["errors"], list)
        # C3a collects nothing step-by-step; C3b will fill this. It is present
        # and empty now so the shape does not change under C3b.
        assert row["steps"] == []
    # `coverage` is the derived status map, one entry per channel, same order.
    assert list(evidence["coverage"]) == CHANNELS
    assert evidence["coverage"] == {
        name: evidence["channels"][name]["status"] for name in CHANNELS
    }
    delivery = evidence["delivery"]
    assert set(delivery) == DELIVERY_KEYS
    assert delivery["status"] in {"complete", "partial"}
    assert isinstance(delivery["note"], str) and delivery["note"]
    assert "证据" in delivery["note"] and "不是板级" in delivery["note"]
    for row in delivery["requiredDisclosures"]:
        assert set(row) == DISCLOSURE_KEYS
        assert row["channel"] in CHANNELS
        assert row["code"] == DISCLOSURE_CODES[row["channel"]]
        assert row["status"] == evidence["coverage"][row["channel"]]
        assert re.search(r"[\u4e00-\u9fff]", row["message"])


def test_the_section_is_additive_and_leaves_schema_and_source_alone(monkeypatch):
    report = _report(monkeypatch, "file")

    # The schema id is *not* bumped: this batch adds a reading, it does not move
    # a gate (completion / summary.exitCode / the process exit code).
    assert report["schema"] == "boardwise.checkup/7"
    assert "evidence" not in report["source"]
    assert report["source"]["tier"] == "file"
    assert report["source"]["hostVersion"] == "3.2.186"
    # `environment` (537C2) is still there, untouched and beside the new key.
    assert "environment" in report
    assert "evidence" in report
    # Nothing in the old keys changed meaning.
    assert report["summary"]["exitCode"] == 0
    assert "completion" not in report


def test_coverage_is_derived_from_channels_and_nothing_else():
    """Two statuses that disagree would be the drift this section exists to stop."""
    ev_module = _evidence_module()
    channels = {
        name: {
            "status": status,
            "source": SOURCES[name],
            "detail": "x",
            "artifacts": [],
            "errors": [],
            "steps": [],
        }
        for name, status in zip(CHANNELS, [
            "ok", "failed", "missing", "unavailable", "not-applicable", "ok",
        ])
    }

    coverage = ev_module.evidence_coverage(channels)

    assert list(coverage) == CHANNELS
    assert coverage == {name: channels[name]["status"] for name in CHANNELS}
    # A copy of the mapping is returned; mutating it does not move the source.
    coverage[CHANNELS[0]] = "missing"
    assert channels[CHANNELS[0]]["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. the six channels' frozen semantics
# ---------------------------------------------------------------------------


def test_archive_pcb_ok_with_a_pcb_document_while_live_pcb_and_pcb_image_are_missing(monkeypatch):
    evidence = _build(
        tier="file",
        pcb_had_documents=True,
        pcb_review=_good_board_pcb_review(),
    )

    assert _status(evidence, "archivePcb") == "ok"
    assert evidence["channels"]["archivePcb"]["artifacts"], "the board readings are real artifacts"
    # Collected? No. Failed? Not proven either. So: missing, both of them.
    assert _status(evidence, "livePcb") == "missing"
    assert _status(evidence, "pcbImage") == "missing"
    assert evidence["delivery"]["status"] == "partial"
    assert "live-pcb-evidence" in _codes(evidence)
    assert "pcb-visual-review" in _codes(evidence)
    # A file-tier run is never live schematic evidence.
    assert _status(evidence, "liveSchematic") == "missing"
    assert "live-schematic-evidence" in _codes(evidence)


def test_confirmed_no_pcb_document_makes_all_three_pcb_channels_not_applicable(monkeypatch):
    evidence = _build(tier="file", pcb_had_documents=False, pcb_review=None)

    for name in ("archivePcb", "livePcb", "pcbImage"):
        assert _status(evidence, name) == "not-applicable", name
        assert evidence["channels"][name]["detail"], name
    # N/A is closed: it needs no disclosure.
    assert "archive-pcb-evidence" not in _codes(evidence)
    assert "live-pcb-evidence" not in _codes(evidence)
    assert "pcb-visual-review" not in _codes(evidence)
    assert evidence["delivery"]["requiredDisclosures"]
    assert all(row["channel"] in {"liveSchematic", "schematicImage", "datasheets"}
               for row in evidence["delivery"]["requiredDisclosures"])

    online = _build(tier="project-file", pcb_had_documents=False, pcb_review=None)
    assert _status(online, "archivePcb") == "not-applicable"


def test_pcb_documents_without_a_pcb_review_section_is_failed_not_missing():
    """「有 PCB 文档但没出结果」 is a check that did not happen, not a channel
    nobody tried — 126d's distinction, now visible in the coverage ledger."""
    evidence = _build(tier="file", pcb_had_documents=True, pcb_review=None)

    assert _status(evidence, "archivePcb") == "failed"
    assert "archive-pcb-evidence" in _codes(evidence)
    row = next(
        row for row in evidence["delivery"]["requiredDisclosures"]
        if row["channel"] == "archivePcb"
    )
    assert "pcb_review" in row["message"]
    # And the live channels are still not *failed*: nothing was read.
    assert _status(evidence, "livePcb") == "missing"


def test_the_tiers_without_a_whole_project_archive_report_unknown_not_absent():
    for tier in ("per-page", "netlist"):
        evidence = _build(tier=tier, pcb_had_documents=False, pcb_review=None)
        assert _status(evidence, "archivePcb") == "missing", tier
        assert _status(evidence, "livePcb") == "missing", tier
        assert _status(evidence, "pcbImage") == "missing", tier
        assert "archive-pcb-evidence" in _codes(evidence), tier
        detail = evidence["channels"]["archivePcb"]["detail"]
        assert "未知" in detail, tier


def test_live_schematic_is_ok_only_for_the_netlist_tier_with_a_non_empty_model():
    """H4: archive is not live.

    A `project-file` / `per-page` run only ever got an *archive* of the
    schematic; the original session's live schematic evidence was a direct
    readback/netlist. So those tiers must say `missing` (not collected), while
    the `netlist` tier — which reads `sch.netlist` / `sch.geometry` directly —
    is the one that may say `ok`.
    """
    assert _status(_build(tier="netlist", model_empty=False), "liveSchematic") == "ok"

    for tier in ("project-file", "per-page"):
        archived = _build(tier=tier, model_empty=False)
        assert _status(archived, "liveSchematic") == "missing", tier
        detail = archived["channels"]["liveSchematic"]["detail"]
        assert "归档" in detail, tier
        assert "不等于 live" in detail, tier
        assert "live-schematic-evidence" in _codes(archived), tier

    # An empty model is never usable evidence, whichever online tier read it.
    for tier in ("project-file", "per-page", "netlist"):
        empty = _build(tier=tier, model_empty=True)
        assert _status(empty, "liveSchematic") == "failed", tier
        assert "空模型" in empty["channels"]["liveSchematic"]["detail"], tier
        assert "live-schematic-evidence" in _codes(empty), tier

    # Offline never attempted a live read, so it is missing, not failed.
    offline = _build(tier="file", model_empty=False)
    assert _status(offline, "liveSchematic") == "missing"


def test_an_archived_online_run_does_not_claim_live_schematic_evidence(monkeypatch):
    """The report path must not promote an archive to live evidence either."""
    report = _report(monkeypatch, "project-file", model=_nonempty_model())

    channel = report["evidence"]["channels"]["liveSchematic"]
    assert channel["status"] == "missing"
    assert "归档" in channel["detail"]
    assert "live-schematic-evidence" in [
        row["code"] for row in report["evidence"]["delivery"]["requiredDisclosures"]
    ]


def test_schematic_image_offline_is_missing_even_with_geometry_on_the_canvas():
    """189C's offline geometry SVG draws a PCB, not a live schematic: it must not
    be promoted to 「原理图视觉复核」."""
    evidence = _build(tier="file", canvas=_canvas_ok())

    assert _status(evidence, "schematicImage") == "missing"
    assert evidence["channels"]["schematicImage"]["artifacts"] == []
    assert "离线" in evidence["channels"]["schematicImage"]["detail"]


def test_schematic_image_ok_when_every_page_rendered():
    evidence = _build(tier="project-file", canvas=_canvas_ok())

    assert _status(evidence, "schematicImage") == "ok"
    artifacts = evidence["channels"]["schematicImage"]["artifacts"]
    assert len(artifacts) == 1
    # Only the metadata the canvas item already carries is copied.
    assert artifacts[0]["page"] == "P1"
    assert artifacts[0]["file"] == "canvas-P1.png"
    assert artifacts[0]["sha256"] == "a" * 64
    assert evidence["channels"]["schematicImage"]["errors"] == []
    assert "schematic-visual-review" not in _codes(evidence)


def test_a_png_fallback_svg_is_a_valid_image_and_keeps_its_history():
    """031's PNG-timeout→SVG fallback leaves `pngError` (no `error`) beside a real
    SVG. The image is usable — `ok` — but the detail must not claim there were no
    render errors, and the fallback record must survive in artifacts."""
    evidence = _build(tier="project-file", canvas=[{
        "page": "P1",
        "pageUuid": "uuid-P1",
        "format": "svg",
        "pngError": "TIMEOUT: export.render png",
        "file": "canvas-P1.svg",
        "bytes": 12,
        "sha256": "b" * 64,
    }])

    channel = evidence["channels"]["schematicImage"]
    assert channel["status"] == "ok", "a valid fallback image is not a failure"
    assert channel["errors"] == []
    artifact = channel["artifacts"][0]
    assert artifact["format"] == "svg"
    assert artifact["pngError"] == "TIMEOUT: export.render png"
    assert artifact["file"] == "canvas-P1.svg"
    assert "无渲染错误" not in channel["detail"]
    assert "PNG" in channel["detail"]
    assert "schematic-visual-review" not in _codes(evidence)


def test_schematic_image_with_one_failed_page_is_failed_and_keeps_the_good_ones():
    evidence = _build(tier="project-file", canvas=_canvas_partial())

    channel = evidence["channels"]["schematicImage"]
    assert channel["status"] == "failed"
    # The success is not thrown away with the failure.
    assert [row["page"] for row in channel["artifacts"]] == ["P1"]
    assert any("TIMEOUT" in error for error in channel["errors"])
    assert "schematic-visual-review" in _codes(evidence)


def test_schematic_image_with_no_canvas_after_a_model_is_failed_not_ok():
    evidence = _build(tier="project-file", canvas=[], model_empty=False)

    assert _status(evidence, "schematicImage") == "failed"
    assert "没有" in evidence["channels"]["schematicImage"]["detail"] or \
        "一页" in evidence["channels"]["schematicImage"]["detail"]
    assert "schematic-visual-review" in _codes(evidence)

    # A canvas entry that answered without a file is a failure too, not a
    # successful set with a hole in it.
    hollow = _build(
        tier="project-file", canvas=[{"page": "P1", "pageUuid": "u1"}]
    )
    assert _status(hollow, "schematicImage") == "failed"
    assert hollow["channels"]["schematicImage"]["errors"]


def test_datasheets_are_unavailable_for_each_kind_of_open_item_and_ok_at_true_zero():
    triggers = {
        "unreviewed": dict(unreviewed=[{"part": "U1"}]),
        "accepted_unknown": dict(accepted_unknown=[{"part": "U2", "state": "accepted"}]),
        "marked": dict(needs_datasheet=[{"trigger": "marked", "part": "U3", "pin": "1"}]),
        "empty_model": dict(model_empty=True),
    }
    for label, kwargs in triggers.items():
        evidence = _build(**kwargs)
        assert _status(evidence, "datasheets") == "unavailable", label
        assert "datasheet-evidence" in _codes(evidence), label

    clean = _build()
    assert _status(clean, "datasheets") == "ok"
    assert "datasheet-evidence" not in _codes(clean)


def test_datasheet_detail_keeps_the_three_counts_apart():
    """工程师接受未审不是手册已核, and the three debts are not summed into one
    「唯一器件数」."""
    evidence = _build(
        unreviewed=[{"part": "U1"}, {"part": "U2"}],
        accepted_unknown=[
            {"part": "U3", "state": "accepted"},
            {"part": "U4", "state": "accepted"},
        ],
        needs_datasheet=[
            {"trigger": "marked", "part": "U1", "pin": "1"},
            {"trigger": "marked", "part": "U5", "pin": "2"},
        ],
    )

    detail = evidence["channels"]["datasheets"]["detail"]
    assert "未审 2" in detail
    assert "接受未审（本轮缺口）2" in detail
    assert "标记 2" in detail
    # The sum (6) is not what the detail reports.
    assert "6" not in detail
    assert "不相加" in detail
    assert _status(evidence, "datasheets") == "unavailable"


def test_a_stale_acceptance_record_does_not_claim_a_current_datasheet_gap():
    """Only `state == "accepted"` is a current debt.

    `stale` / `stale-elsewhere` / `not-unreviewed` are records of an acceptance
    whose part the drawing (or this board) no longer has, or a part that was
    judged anyway. They stay disclosed, but a report full of them must not read
    as 「手册证据未齐」 for the board in front of the reader.
    """
    stale_only = _build(accepted_unknown=[
        {"part": "U9", "state": "stale"},
        {"part": "U10", "state": "stale-elsewhere"},
        {"part": "U11", "state": "not-unreviewed"},
    ])
    assert _status(stale_only, "datasheets") == "ok"
    assert "datasheet-evidence" not in _codes(stale_only)
    detail = stale_only["channels"]["datasheets"]["detail"]
    assert "stale" in detail, "the stale records are still disclosed"
    assert "不构成本轮手册缺口" in detail

    # The one state that *is* a current debt still downgrades the channel.
    accepted = _build(accepted_unknown=[{"part": "U1", "state": "accepted"}])
    assert _status(accepted, "datasheets") == "unavailable"
    assert "datasheet-evidence" in _codes(accepted)

    # A mix: the accepted row is the debt, the stale ones are not extra debts.
    mixed = _build(accepted_unknown=[
        {"part": "U1", "state": "accepted"},
        {"part": "U2", "state": "stale"},
    ])
    assert _status(mixed, "datasheets") == "unavailable"
    assert "接受未审（本轮缺口）1" in mixed["channels"]["datasheets"]["detail"]


# ---------------------------------------------------------------------------
# 3. delivery: complete only on all-ok/all-N/A, and never a board verdict
# ---------------------------------------------------------------------------


def test_delivery_is_complete_only_when_every_channel_is_ok_or_not_applicable():
    ev_module = _evidence_module()

    def channels(statuses):
        return {
            name: {
                "status": status,
                "source": SOURCES[name],
                "detail": "x",
                "artifacts": [],
                "errors": [],
                "steps": [],
            }
            for name, status in zip(CHANNELS, statuses)
        }

    # All ok, all N/A, and a mix of the two are the only `complete` shapes.
    assert ev_module.evidence_delivery(channels(["ok"] * 6))["status"] == "complete"
    assert ev_module.evidence_delivery(
        channels(["not-applicable"] * 6)
    )["status"] == "complete"
    mixed = channels(["ok", "not-applicable", "not-applicable",
                      "ok", "not-applicable", "ok"])
    assert ev_module.evidence_delivery(mixed)["status"] == "complete"
    assert ev_module.evidence_delivery(mixed)["requiredDisclosures"] == []

    # Any non-ok/non-N/A status — including `missing` — makes it partial, and
    # each open channel gets exactly one disclosure row, in channel order.
    for status in ("failed", "missing", "unavailable"):
        one_open = channels(["ok", "ok", "ok", "ok", "ok", "ok"])
        one_open["livePcb"]["status"] = status
        delivery = ev_module.evidence_delivery(one_open)
        assert delivery["status"] == "partial", status
        assert [row["channel"] for row in delivery["requiredDisclosures"]] == ["livePcb"]
        assert delivery["requiredDisclosures"][0]["status"] == status

    # Production: with no live PCB/image channel collected (C3b has not landed),
    # n/a does not stand in for a missing reading.
    mostly_closed = _build(
        tier="file",
        pcb_had_documents=False,
        unreviewed=[],
    )
    assert _status(mostly_closed, "liveSchematic") == "missing"
    assert mostly_closed["delivery"]["status"] == "partial"
    assert _codes(mostly_closed) == [
        "live-schematic-evidence",
        "schematic-visual-review",
    ]


def test_delivery_partial_does_not_touch_the_board_verdict(monkeypatch):
    partial_evidence = _build(tier="file", pcb_had_documents=True, pcb_review=None)

    report = _report(
        monkeypatch, "file", evidence=partial_evidence, summary_extra={"exitCode": 0}
    )

    assert report["evidence"]["delivery"]["status"] == "partial"
    # The ledger is a reading: it does not move the exit code or the summary.
    assert report["summary"]["exitCode"] == 0
    assert "completion" not in report
    # And `partial` is not board verdict vocabulary.
    assert report["evidence"]["delivery"]["status"] not in {"pass", "fail", "passed", "failed"}


def test_a_need_datasheet_mark_refreshes_the_datasheets_channel():
    """A re-gate must not leave the ledger saying `ok` about a section it just
    changed."""
    report = _hand_built_report()
    report["evidence"] = _literal_evidence({name: "ok" for name in CHANNELS})
    report["unreviewed_parts"] = []
    report["accepted_unknown"] = []
    report["warning_triage"] = []
    report["completion"] = {"coverage": {"modelEmpty": False}}

    cli._apply_needs_datasheet(
        report, [{"trigger": "marked", "part": "U1", "pin": "1"}]
    )

    evidence = report["evidence"]
    assert evidence["coverage"]["datasheets"] == "unavailable"
    assert "datasheet-evidence" in _codes(evidence)
    assert evidence["delivery"]["status"] == "partial"
    # Still derived, not patched by hand.
    assert evidence["coverage"] == {
        name: evidence["channels"][name]["status"] for name in CHANNELS
    }
    # A pre-537C3a report stays without a ledger: none is invented.
    old = _hand_built_report()
    cli._apply_needs_datasheet(old, [{"trigger": "marked", "part": "U2", "pin": "1"}])
    assert "evidence" not in old


# ---------------------------------------------------------------------------
# 4. requiredDisclosures: fixed codes, fixed order, specific messages
# ---------------------------------------------------------------------------


def test_required_disclosures_follow_the_frozen_channel_order_and_codes():
    evidence = _build(
        tier="project-file",
        model_empty=True,
        pcb_had_documents=True,
        pcb_review=None,
        canvas=[],
        unreviewed=[{"part": "U1"}],
        accepted_unknown=[],
        needs_datasheet=[],
    )

    assert _open_channels(evidence) == CHANNELS
    rows = evidence["delivery"]["requiredDisclosures"]
    assert [row["channel"] for row in rows] == CHANNELS
    assert [row["code"] for row in rows] == [DISCLOSURE_CODES[name] for name in CHANNELS]


def test_the_three_high_risk_messages_say_what_they_cost():
    # A PCB document exists but the review did not run → the live/image channels
    # are still open (missing), so all three disclosures are present.
    live_pcb = _build(
        tier="project-file", model_empty=False, pcb_had_documents=True
    )
    pcb_image = _build(
        tier="project-file", model_empty=False, pcb_had_documents=True
    )
    datasheet = _build(tier="project-file", unreviewed=[{"part": "U1"}])

    live_msg = next(row["message"] for row in live_pcb["delivery"]["requiredDisclosures"]
                    if row["channel"] == "livePcb")
    image_msg = next(row["message"] for row in pcb_image["delivery"]["requiredDisclosures"]
                     if row["channel"] == "pcbImage")
    data_msg = next(row["message"] for row in datasheet["delivery"]["requiredDisclosures"]
                    if row["channel"] == "datasheets")

    assert "未完成实时 PCB 回读" in live_msg
    assert "未完成 PCB 视觉复核" in image_msg
    assert "手册证据未齐" in data_msg and "待核" in data_msg
    # No message pretends the board passed or failed.
    for message in (live_msg, image_msg, data_msg):
        assert "通过" not in message or "不是" in message


# ---------------------------------------------------------------------------
# 5. rendering: report.md / review-summary.md / stdout, one section
# ---------------------------------------------------------------------------


def test_report_md_renders_the_section_as_bullets_not_a_findings_table():
    report = _hand_built_report()
    report["evidence"] = _literal_evidence()

    markdown = render_report_markdown(report)
    section = _section_text(markdown)

    assert "## 证据覆盖（evidence）" in markdown
    for name in CHANNELS:
        assert f"`{name}`" in section
        assert SOURCES[name] in section
        assert f"detail for {name}" in section
    assert "delivery" in section and "partial" in section
    assert "不是板级通过或不通过" in section
    for name in ("livePcb", "pcbImage"):
        assert DISCLOSURE_CODES[name] in section
    # Bullets only: a `|` row inside this section would be counted as a finding
    # row by the review-summary's own row arithmetic.
    assert not [line for line in section.splitlines() if line.strip().startswith("|")]


def test_review_summary_renders_the_same_section_between_findings_and_worklist():
    report = _hand_built_report()
    report["evidence"] = _literal_evidence()

    chains = finding_chains(report)
    text = render_review_summary(report, chains)

    assert "## 证据覆盖（evidence）" in text
    assert DISCLOSURE_CODES["livePcb"] in text
    assert DISCLOSURE_CODES["pcbImage"] in text
    assert "不是板级通过或不通过" in text
    for heading in ("## 1. 连接状态", "## 2. 逐条问题", "## 3. 待确认", "## 4. 下一步"):
        assert heading in text, heading
    assert text.index("## 2. 逐条问题") < text.index("## 证据覆盖（evidence）") \
        < text.index("## 3. 待确认")


def test_a_report_without_evidence_renders_no_evidence_text():
    report = _hand_built_report()

    markdown = render_report_markdown(report)
    review = render_review_summary(report, [])

    for text in (markdown, review):
        assert "证据覆盖" not in text
        assert "requiredDisclosures" not in text
        assert "liveSchematic" not in text
        assert "boardwise.review-evidence" not in text
    for heading in ("## 1. 连接状态", "## 2. 逐条问题", "## 3. 待确认", "## 4. 下一步"):
        assert heading in review, heading
    assert "本次审查没有 finding" in review


def test_the_console_line_is_read_from_the_section_and_lists_every_open_channel():
    ev_module = _evidence_module()

    partial = _literal_evidence()
    line = ev_module.evidence_console_line(partial)
    assert line.startswith("evidence: partial (")
    assert "livePcb=missing" in line
    assert "pcbImage=missing" in line

    complete = _literal_evidence({
        name: "ok" for name in CHANNELS
    })
    complete_line = ev_module.evidence_console_line(complete)
    assert complete_line.startswith("evidence: complete")
    # A `complete` line has nothing to list; an empty `()` would read like a
    # channel called nothing.
    assert "()" not in complete_line

    # No section, no line — the pre-537C3a rendering is untouched.
    assert ev_module.evidence_console_line(None) == ""
    assert ev_module.evidence_console_line({}) == ""


# ---------------------------------------------------------------------------
# 6. end to end: one offline run, four renderings of the same section
# ---------------------------------------------------------------------------


def test_an_offline_run_puts_the_same_evidence_in_json_markdown_summary_and_stdout(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "_repo_connector_version", lambda: "0.5.21")
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"

    code = cli.main([
        "checkup", "--file", str(GOLDEN), "--out", str(out), "--library", str(LIBRARY),
    ])
    printed = capsys.readouterr().out

    assert code in (0, 1, 3), "an offline run over the synthetic fixture must still run"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    evidence = report["evidence"]
    assert evidence["schema"] == "boardwise.review-evidence/1"
    assert code == report["summary"]["exitCode"]

    # --- the real inputs reached the builder: this fixture carries no PCB
    # document, so `_cmd_checkup`'s real `pcb_had_documents=False` is what makes
    # the PCB trio N/A. A caller that guessed from notes would not say this.
    assert evidence["coverage"]["liveSchematic"] == "missing"
    assert evidence["coverage"]["archivePcb"] == "not-applicable"
    assert evidence["coverage"]["livePcb"] == "not-applicable"
    assert evidence["coverage"]["pcbImage"] == "not-applicable"
    assert evidence["coverage"]["schematicImage"] == "missing"
    assert evidence["coverage"]["datasheets"] == "unavailable"
    assert evidence["delivery"]["status"] == "partial"
    # `report.json` carries its own derived map, not a second hand-set one.
    assert evidence["coverage"] == {
        name: evidence["channels"][name]["status"] for name in CHANNELS
    }

    # --- stdout: one evidence line, the same delivery and the same open channels.
    lines = [line for line in printed.splitlines() if line.strip().startswith("evidence:")]
    assert len(lines) == 1, printed
    console = lines[0].strip()
    assert f"evidence: {evidence['delivery']['status']}" in console
    for name in _open_channels(evidence):
        assert f"{name}={evidence['coverage'][name]}" in console, (name, console)

    # --- both Markdown products carry the same section.
    for name in ("report.md", "review-summary.md"):
        text = (out / name).read_text(encoding="utf-8")
        section = _section_text(text)
        assert evidence["delivery"]["status"] in section, name
        for channel in _open_channels(evidence):
            assert f"`{channel}`" in section, (name, channel)
            assert DISCLOSURE_CODES[channel] in section, (name, channel)
        assert "不是板级通过或不通过" in section, name
        assert not [line for line in section.splitlines() if line.strip().startswith("|")], name

    # --- the ledger did not move the gates it sits beside.
    assert "completion" in report
    assert report["completion"]["verdict"] == "incomplete"
    assert code == 3
