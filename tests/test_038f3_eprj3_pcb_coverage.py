"""038F3 — a folder project's board is disclosed as *un-reviewed*, not denied.

038F4 gave the folder container a PCB reader (`pcb_files` /
`load_eprj3_pcb_source`). 038F5 wired the offline `checkup --file` PCB runner to
it, so the *disclosure* this batch added no longer needs the wiring to be absent
to be exercised: the tests below make the runner **fail on purpose** and check
that the same three statements stay honest — `coverage.pcbReviewMissing` true,
`evidence.channels.archivePcb` `failed`, and a canvas note that names the board
instead of denying it. The success path belongs to `test_038f5`.

The batch's own change is the *fact supply*, not the gate: the folder's board
files are listed once by 038F4's adapter and handed to the same
`pcb_had_documents` the `.epro2` path already fills, so the existing gate,
verdict sentence and evidence ledger do the rest. The index's `pcb_count` is
deliberately **not** the authority — the tests below put a wrong count in the
index on purpose, in both directions.

The report schema, the conclusion's authority, the rules and the exit-code
precedence are untouched; the last test pins the no-PCB path so this batch
cannot quietly widen 「未审」 into 「没有」.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli

SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"


# --------------------------------------------------------------------------
# a folder project: one page (so the model is not empty) + optional board file
# --------------------------------------------------------------------------


def _record(envelope: dict, body: dict | None = None) -> str:
    head = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return head + "|||" if body is None else (
        head + "||" + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "|"
    )


def _symbol(uuid: str, title: str, pins: list[tuple[str, float, float]]) -> list[str]:
    out = [_record({"type": "DOCHEAD"},
                   {"docType": "SYMBOL", "uuid": uuid, "editVersion": "1.0.0"}),
           _record({"type": "META", "id": "META"}, {"title": title, "docType": "SYMBOL"})]
    for index, (number, x, y) in enumerate(pins):
        pin_id = f"e{index + 1}"
        out.append(_record({"type": "PIN", "id": pin_id},
                           {"x": x, "y": y, "zIndex": index + 2}))
        out.append(_record({"type": "ATTR", "id": f"n{index}"},
                           {"parentId": pin_id, "key": "Pin Number", "value": number}))
        out.append(_record({"type": "ATTR", "id": f"t{index}"},
                           {"parentId": pin_id, "key": "Pin Type", "value": "1"}))
    return out


def _page(*, version: str = "4.1.60") -> list[str]:
    """One schematic page with two placed parts and one signal net."""
    out = [_record({"type": "DOCHEAD"},
                   {"docType": "SCH_PAGE", "uuid": "page-1", "editVersion": version}),
           _record({"type": "CANVAS"},
                   {"originX": 0, "originY": 0, "unit": "0.01inch"})]
    out += _symbol("sym-1", "R", [("1", 0.0, 0.0), ("2", 20.0, 0.0)])
    for name, part, x in (("U1", "inst-u1", 300.0), ("U2", "inst-u2", 400.0)):
        out.append(_record({"type": "COMPONENT", "id": f"c-{part}"},
                           {"partId": part, "x": x, "y": -500.0, "rotation": 0,
                            "isMirror": False, "zIndex": 10}))
        out.append(_record({"type": "ATTR", "id": f"d-{part}"},
                           {"parentId": part, "key": "Designator", "value": name}))
        out.append(_record({"type": "ATTR", "id": f"s-{part}"},
                           {"parentId": part, "key": "Symbol", "value": "sym-1"}))
    out.append(_record({"type": "WIRE", "id": "grp-1"}, {"zIndex": 40}))
    out.append(_record({"type": "LINE"},
                       {"lineGroup": "grp-1", "startX": 300.0, "startY": -500.0,
                        "endX": 400.0, "endY": -500.0}))
    out.append(_record({"type": "ATTR", "id": "net-1"},
                       {"parentId": "grp-1", "key": "NET", "value": "SIG_A"}))
    return out


def _pcb_stream(*, uuid: str = "pcb-uuid", title: str = "PCB1") -> str:
    lines = [
        _record({"type": "DOCHEAD"},
                {"docType": "PCB", "uuid": uuid, "editVersion": "4.1.60"}),
        _record({"type": "META", "id": "META"}, {"title": title, "docType": 3}),
        _record({"type": "CANVAS", "id": "CANVAS"},
                {"originX": 0, "originY": 1000.0, "yAxisDirection": "up"}),
        _record({"type": "COMPONENT", "id": "part-u1"},
                {"partId": "part-u1", "x": 10.0, "y": 20.0, "rotation": 0, "zIndex": 1}),
        _record({"type": "ATTR", "id": "attr-u1"},
                {"parentId": "part-u1", "key": "Designator", "value": "U1"}),
    ]
    return "\n".join(lines) + "\n"


def _write_project(
    root: Path,
    *,
    boards: dict[str, str] | None = None,
    index_pcb_count: int = 0,
) -> Path:
    """``boards`` maps a path under the project to that board file's text.

    ``index_pcb_count`` is written into the index verbatim — a number the batch
    deliberately refuses to read as the truth about what is on disk.
    """
    root.mkdir(parents=True, exist_ok=True)
    index = {
        "name": root.name,
        "owner_uuid": "0123456789abcdef0123456789abcdef",
        "format": "folder",
        "pcb_count": index_pcb_count,
        "profile": {"schematics": {}, "sheets": {}, "pcbs": {}},
    }
    (root / f"{root.name}.eprj3").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    page_dir = root / "sch" / "Schematic1"
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "P1.esch2").write_text(
        "\n".join(_page()) + "\n", encoding="utf-8")
    for relative, text in (boards or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _run_checkup(tmp_path: Path, monkeypatch, project: Path, name: str) -> tuple[int, dict]:
    """One offline checkup over a synthetic folder project, returning (rc, report)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / f"home-{name}"))
    out = tmp_path / name
    rc = cli.main([
        "checkup", "--file", str(project), "--out", str(out), "--library", str(SHELF),
    ])
    return rc, json.loads((out / "report.json").read_text(encoding="utf-8"))


def _fail_the_pcb_runner(monkeypatch) -> None:
    """Make the PCB runner produce **no section**, explicitly (038F5 restated F3).

    Since 038F5 the folder project's board *is* reviewed, so 「有板但没有
    `pcb_review`」 has to be staged instead of relied upon as a missing feature.
    A runner that raises is the real residual case — `_run_pcb_runner` catches
    it, names the reason in `source.notes`, and returns no section — so these
    disclosure tests exercise the branch a user could actually hit. Passing
    because the wiring does not exist would be a test that rots the day it lands.
    """
    from boardwise.engines import pcbreview

    def _boom(*_args, **_kwargs):
        raise RuntimeError("038F3 disclosure scenario: PCB runner produced no section")

    monkeypatch.setattr(pcbreview, "run_pcb_review", _boom)


# --------------------------------------------------------------------------
# 1. a board file exists → the report says "not reviewed", never "no PCB"
# --------------------------------------------------------------------------


def test_a_folder_project_with_a_board_file_is_disclosed_as_unreviewed(
    tmp_path, monkeypatch
):
    project = _write_project(
        tmp_path / "proj",
        boards={"pcb/PCB1.epcb2": _pcb_stream()},
        index_pcb_count=0,  # the index claims no board; the disk has one
    )
    _fail_the_pcb_runner(monkeypatch)
    rc, report = _run_checkup(tmp_path, monkeypatch, project, "with-board")

    coverage = report["completion"]["coverage"]
    assert coverage["pcbReviewMissing"] is True, (
        "a folder project with pcb/PCB1.epcb2 has a board: the missing pcb_review "
        "section is 「not reviewed」"
    )
    assert coverage["parseIncomplete"] is False, (
        "038F1: a normal EOF must not be read as a truncated record stream"
    )
    assert "pcb_review" not in report, (
        "the runner produced no section, and the failure is named in source.notes"
    )
    assert any("PCB 审查未完成" in note for note in report["source"]["notes"]), (
        "the staged failure has to be the reason, not a silent absence"
    )
    assert report["completion"]["verdict"] == "incomplete"
    assert rc == report["conclusion"]["exitCode"], (
        "the offline incomplete semantics are reused, not re-decided here"
    )
    assert any("PCB" in why for why in report["completion"]["verdictWhy"]), (
        "the verdict's own sentence has to name the un-reviewed board"
    )


def test_the_evidence_ledger_records_missing_pcb_evidence(tmp_path, monkeypatch):
    project = _write_project(
        tmp_path / "proj",
        boards={"pcb/PCB1.epcb2": _pcb_stream()},
    )
    _fail_the_pcb_runner(monkeypatch)
    _rc, report = _run_checkup(tmp_path, monkeypatch, project, "evidence")

    channel = report["evidence"]["channels"]["archivePcb"]
    assert channel["status"] == "failed", (
        "documents exist and no reading did: the channel is missing evidence, "
        "not 「no PCB」"
    )
    assert channel["status"] != "not-applicable"
    assert "PCB" in channel["detail"]


def test_the_canvas_note_names_the_unreviewed_pcb_step(tmp_path, monkeypatch):
    project = _write_project(
        tmp_path / "proj",
        boards={"pcb/PCB1.epcb2": _pcb_stream()},
    )
    _fail_the_pcb_runner(monkeypatch)
    _rc, report = _run_checkup(tmp_path, monkeypatch, project, "canvas")

    note = report["ai_slots"]["canvas_images_note"]
    assert "工程有 PCB" in note, note
    assert "没有 PCB 文档" not in note, (
        "the project has a board file; the note may not say it has none"
    )
    assert "审查未出结果" in note, (
        "038F5: the staged failure is named as the reason, not a missing feature"
    )
    assert report["ai_slots"]["canvas_images"] == [], (
        "nothing was rendered, and the note says why"
    )


def test_the_version_and_frame_readings_survive_the_disclosure(tmp_path, monkeypatch):
    """038F2's editor version and 038F1's EOF reading are not disturbed here."""
    project = _write_project(
        tmp_path / "proj",
        boards={"pcb/PCB1.epcb2": _pcb_stream()},
    )
    _rc, report = _run_checkup(tmp_path, monkeypatch, project, "version")

    parse = report["source"]["parseStats"]
    assert parse.get("editor_version") == "4.1.60", (
        "the DOCHEAD editVersion is the only version a folder project carries"
    )
    assert report["completion"]["coverage"]["parseIncomplete"] is False
    assert report["schema"] == "boardwise.checkup/7", "no schema bump for a disclosure"


# --------------------------------------------------------------------------
# 2. no board file → the old 「no PCB」 semantics, unchanged
# --------------------------------------------------------------------------


def test_a_folder_project_without_a_board_file_keeps_the_old_semantics(
    tmp_path, monkeypatch
):
    project = _write_project(
        tmp_path / "proj",
        index_pcb_count=3,  # the index claims boards; the disk has none
    )
    _rc, report = _run_checkup(tmp_path, monkeypatch, project, "no-board")

    coverage = report["completion"]["coverage"]
    assert coverage["pcbReviewMissing"] is False, (
        "the index's pcb_count is not the authority — pcb_files is"
    )
    channel = report["evidence"]["channels"]["archivePcb"]
    assert channel["status"] == "not-applicable", channel
    note = report["ai_slots"]["canvas_images_note"]
    assert "没有 PCB 文档" in note, (
        "with no .epcb2 anywhere the old sentence stays true and is kept"
    )


def test_a_page_file_is_not_a_board(tmp_path, monkeypatch):
    """Only `pcb/**/*.epcb2` counts; a stray .esch2 does not make a board."""
    project = _write_project(tmp_path / "proj")
    (project / "sch" / "Schematic1" / "P1.esch2").write_text(
        "\n".join(_page()) + "\n", encoding="utf-8")
    _rc, report = _run_checkup(tmp_path, monkeypatch, project, "page-only")

    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    assert report["evidence"]["channels"]["archivePcb"]["status"] == "not-applicable"
