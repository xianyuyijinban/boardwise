"""038F5 — a folder project's board reaches the CLI and the offline PCB runner.

038F4 gave the container a PCB source (`load_eprj3_pcb_source`); this batch is
the **wiring**, and the testing question is therefore 「does the folder reach the
one existing path?」 rather than 「is there a new path?」:

* ``_load_model(view="pcb")`` returns 038F4's source through the same
  ``build_design_model`` / ``build_board_geometry`` the ``.epro2`` branch uses;
* ``engines.pcbreview._review_units`` only chooses the container source
  (eprj3 adapter vs ``.epro2``) and shares `_pcb_documents`, footprints, artwork,
  `extract_board` and `build_design_model` with it — the section shape, the rule
  list and the finding severity are untouched;
* ``checkup --file`` actually runs that runner and produces `pcb_review` plus the
  geometry canvas, so `pcbReviewMissing` is false for a project that was really
  reviewed;

and the two refusals stay loud: a folder with **no** board file is still "no
PCB", and a folder with **several** is refused by name rather than reduced to the
first (the adapter's own rule since 038F4).

The synthetic project is a folder shell around a board stream in the same record
frame the real sample uses; the real V4 sample's readings (counts, GHA, the two
schematic ERRORs, 107↔88) are recorded in `outputs/review/v4-eprj3-tierb.md`,
not asserted here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.parsers.eprj3 import Eprj3Error

SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"


# --------------------------------------------------------------------------
# a folder project: one schematic page + the board files the caller spells out
# --------------------------------------------------------------------------


def _record(envelope: dict, body: dict | None = None) -> str:
    head = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return head + "|||"
    return head + "||" + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "|"


def _head(doc_type: str, uuid: str, version: str | None = None) -> str:
    body: dict = {"docType": doc_type, "uuid": uuid}
    if version is not None:
        body["editVersion"] = version
    return _record({"type": "DOCHEAD"}, body)


def _pcb_stream(*, uuid: str = "pcb-uuid", title: str = "PCB1") -> str:
    """One board document with one placed part and one track-less outline-free body.

    Small on purpose: what this batch proves is the *seam*, and a stream with
    the same DOCHEAD / META / COMPONENT records the real board carries is enough
    for the runner to read one board and for the canvas to draw its empty frame.
    """
    lines = [
        _head("PCB", uuid, "4.1.60"),
        _record({"type": "META", "id": "META"}, {"title": title, "docType": 3}),
        _record({"type": "CANVAS", "id": "CANVAS"},
                {"originX": 0, "originY": 1000.0, "yAxisDirection": "up"}),
        _record({"type": "COMPONENT", "id": "part-u1"},
                {"partId": "part-u1", "x": 10.0, "y": 20.0, "rotation": 0, "zIndex": 1}),
        _record({"type": "ATTR", "id": "attr-u1"},
                {"parentId": "part-u1", "key": "Designator", "value": "U1"}),
    ]
    return "\n".join(lines) + "\n"


def _page(*, version: str = "4.1.60") -> list[str]:
    """One schematic page with two placed parts and one signal net."""
    out = [_head("SCH_PAGE", "page-1", version),
           _record({"type": "CANVAS"},
                   {"originX": 0, "originY": 0, "unit": "0.01inch"})]
    out += [
        _head("SYMBOL", "sym-1", "1.0.0"),
        _record({"type": "META", "id": "META"}, {"title": "R", "docType": "SYMBOL"}),
    ]
    for index, (number, x, y) in enumerate((("1", 0.0, 0.0), ("2", 20.0, 0.0))):
        pin_id = f"e{index + 1}"
        out.append(_record({"type": "PIN", "id": pin_id},
                           {"x": x, "y": y, "zIndex": index + 2}))
        out.append(_record({"type": "ATTR", "id": f"n{index}"},
                           {"parentId": pin_id, "key": "Pin Number", "value": number}))
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


def _write_project(
    root: Path,
    *,
    boards: dict[str, str] | None = None,
    page: bool = True,
    pcb_titles: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    index: dict = {
        "name": root.name,
        "owner_uuid": "0123456789abcdef0123456789abcdef",
        "format": "folder",
        "profile": {"schematics": {}, "sheets": {}, "pcbs": {}},
    }
    for uuid, title in (pcb_titles or {}).items():
        index["profile"]["pcbs"][uuid] = {"uuid": uuid, "title": title}
    (root / f"{root.name}.eprj3").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    if page:
        page_dir = root / "sch" / "Schematic1"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "P1.esch2").write_text(
            "\n".join(_page()) + "\n", encoding="utf-8")
    for relative, text in (boards or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# 1. `_load_model(view="pcb")` — the adapter, through the old builders
# --------------------------------------------------------------------------


def test_load_model_pcb_view_uses_the_folder_adapter(tmp_path):
    root = _write_project(
        tmp_path / "proj", boards={"pcb/PCB1.epcb2": _pcb_stream()})

    model, board = cli._load_model(root, view="pcb")

    assert "U1" in model.components, "the netlist view is the board's own document"
    assert model.raw["project"]["format"] == "eprj3", (
        "038F4's source keeps the container's identity; no V3/V4 model split"
    )
    assert board is not None and board.name == "PCB1"
    assert board.edit_version == "4.1.60", "038F2's version reaches the pcb view"


def test_load_model_schematic_view_is_untouched(tmp_path):
    root = _write_project(
        tmp_path / "proj", boards={"pcb/PCB1.epcb2": _pcb_stream()})

    model, board = cli._load_model(root, view="schematic")

    assert len(model.components) == 2 and board is None, (
        "the schematic view still reads pages and carries no geometry"
    )


# --------------------------------------------------------------------------
# 2. `review --view pcb` — the same loader, end to end
# --------------------------------------------------------------------------


def test_review_pcb_view_reads_the_folder_board(tmp_path, capsys):
    root = _write_project(
        tmp_path / "proj", boards={"pcb/PCB1.epcb2": _pcb_stream()})
    out_path = tmp_path / "review.json"

    code = cli.main(["review", str(root), "--view", "pcb",
                     "--json", str(out_path)])
    out = capsys.readouterr().out

    assert code in (0, 1), out
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(payload.get("findings"), list), "the report shape is unchanged"
    assert "U1" in out or "PCB1" in out or "components" in out


# --------------------------------------------------------------------------
# 3. `run_pcb_review` — one board, one shared rule walk
# --------------------------------------------------------------------------


def test_the_runner_reviews_the_folder_board(tmp_path):
    from boardwise.engines.pcbreview import RUNNER_ID, run_pcb_review

    root = _write_project(
        tmp_path / "proj", boards={"pcb/PCB1.epcb2": _pcb_stream()})

    findings, section = run_pcb_review(root)

    assert section is not None and section["available"] is True
    assert section["runner"] == RUNNER_ID
    assert len(section["boards"]) == 1, "one .epcb2 → exactly one board"
    entry = section["boards"][0]
    assert entry["title"] == "PCB1"
    assert entry["checksRun"], "the shared rule list actually ran"
    assert isinstance(findings, list)


def test_a_multi_board_folder_is_refused_by_the_adapter(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        boards={
            "pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1"),
            "pcb/PCB2.epcb2": _pcb_stream(uuid="b", title="PCB2"),
        })

    with pytest.raises(Eprj3Error) as caught:
        cli._load_model(root, view="pcb")
    assert "2 PCB files" in str(caught.value)

    from boardwise.engines.pcbreview import run_pcb_review

    with pytest.raises(Eprj3Error):
        run_pcb_review(root)


def test_review_pcb_view_refuses_a_multi_board_folder(tmp_path, capsys):
    root = _write_project(
        tmp_path / "proj",
        boards={
            "pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1"),
            "pcb/PCB2.epcb2": _pcb_stream(uuid="b", title="PCB2"),
        })

    code = cli.main(["review", str(root), "--view", "pcb",
                     "--json", str(tmp_path / "r.json")])
    err = capsys.readouterr().err

    assert code == 2, "a refusal is exit 2, never a report about one of two boards"
    assert "2 PCB files" in err


# --------------------------------------------------------------------------
# 4. `checkup --file` — pcb_review, canvas, coverage, evidence
# --------------------------------------------------------------------------


def _run_checkup(tmp_path: Path, monkeypatch, project: Path, name: str) -> tuple[int, dict, Path]:
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / f"home-{name}"))
    out = tmp_path / name
    code = cli.main([
        "checkup", "--file", str(project), "--out", str(out), "--library", str(SHELF),
    ])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    return code, report, out


def test_checkup_produces_pcb_review_and_a_canvas(tmp_path, monkeypatch):
    root = _write_project(
        tmp_path / "proj", boards={"pcb/PCB1.epcb2": _pcb_stream()})

    code, report, out = _run_checkup(tmp_path, monkeypatch, root, "wired")

    review = report["pcb_review"]
    assert review["available"] is True
    assert review["runner"]
    assert len(review["boards"]) == 1
    assert review["boards"][0]["title"] == "PCB1"
    assert review["boards"][0]["checksRun"], "the PCB rule list ran"

    coverage = report["completion"]["coverage"]
    assert coverage["pcbReviewMissing"] is False, (
        "the board was actually reviewed: the 126d gate has nothing to report"
    )
    assert coverage["parseIncomplete"] is False

    channel = report["evidence"]["channels"]["archivePcb"]
    assert channel["status"] == "ok", channel

    canvas = report["ai_slots"]["canvas_images"]
    assert canvas, "a reviewed board gets its geometry picture"
    assert not canvas[0].get("error"), canvas[0]
    assert canvas[0]["board"] == "PCB1"
    assert (out / canvas[0]["file"]).is_file(), (
        "the report's file name and the file on disk are one string"
    )
    assert "geometry-render" in report["ai_slots"]["canvas_images_note"] or (
        "SVG" in report["ai_slots"]["canvas_images_note"]
    )

    assert code == report["conclusion"]["exitCode"]


def test_checkup_keeps_the_multi_board_refusal_loud(tmp_path, monkeypatch):
    root = _write_project(
        tmp_path / "proj",
        boards={
            "pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1"),
            "pcb/PCB2.epcb2": _pcb_stream(uuid="b", title="PCB2"),
        })

    code, report, _out = _run_checkup(tmp_path, monkeypatch, root, "multi")

    assert "pcb_review" not in report, "no board was picked without a mapping"
    notes = report["source"]["notes"]
    assert any("PCB 审查未完成" in note and "2 PCB files" in note for note in notes), (
        "the refusal is named in source.notes, not silently reduced to one board"
    )
    assert report["completion"]["coverage"]["pcbReviewMissing"] is True
    assert code == report["conclusion"]["exitCode"]
    assert report["completion"]["verdict"] == "incomplete"


def test_checkup_without_a_board_file_is_still_no_pcb(tmp_path, monkeypatch):
    root = _write_project(tmp_path / "proj")

    code, report, _out = _run_checkup(tmp_path, monkeypatch, root, "no-board")

    assert "pcb_review" not in report
    assert report["completion"]["coverage"]["pcbReviewMissing"] is False
    channel = report["evidence"]["channels"]["archivePcb"]
    assert channel["status"] == "not-applicable", (
        "no .epcb2 anywhere is 「nothing to review」, not a missing check"
    )
    assert code == report["conclusion"]["exitCode"]
