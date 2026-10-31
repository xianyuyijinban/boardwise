"""038F4 — the folder project's PCB document as a shared ``Epro2Source``.

The point of the batch is that **no new PCB parser exists**: ``pcb/<board>.epcb2``
is a complete record stream of its own, so the folder adapter only has to find the
file, read it verbatim, and hand it to the same ``split_documents`` /
``Epro2Source`` the ``.epro2`` container uses. Everything below is therefore about
the *seam*: which file, which title, which version, which frame — and the two
builders that must keep working on the result.

Two rules are the ones a later refactor is most likely to break, so they are the
ones spelled out: a PCB file is **not** y-flipped (its coordinates are already the
cloud frame, and its copied libraries must never be flipped either), and a project
with more than one board is **refused** rather than silently reduced to the first
one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.parsers.eprj3 import (
    Eprj3Error,
    load_eprj3_pcb_source,
    load_eprj3_text,
    pcb_files,
)
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import build_board_geometry


# --------------------------------------------------------------------------
# a folder project builder: index + any PCB files the caller spells out
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


def _pcb_stream(
    *,
    uuid: str = "pcb-uuid",
    title: str = "PCB1",
    version: str | None = "4.1.60",
    origin_y: float = 1000.0,
) -> str:
    """One board document plus the library copy a real file carries.

    The coordinates are deliberately y-up marked **and** positive: a schematic
    transform would negate them, so the assertions below cannot pass by accident.
    """
    lines = [
        _head("PCB", uuid, version),
        _record({"type": "META", "id": "META"}, {"title": title, "docType": 3}),
        _record({"type": "CANVAS", "id": "CANVAS"},
                {"originX": 0, "originY": origin_y, "yAxisDirection": "up"}),
        _record({"type": "COMPONENT", "id": "part-u1"},
                {"partId": "part-u1", "x": 10.0, "y": 20.0, "rotation": 0, "zIndex": 1}),
        _record({"type": "ATTR", "id": "attr-u1"},
                {"parentId": "part-u1", "key": "Designator", "value": "U1"}),
        # A library document in the same file: schematic-family, so a y-flip
        # applied to the whole file (the wrong read) would move this RECT.
        _head("SYMBOL", "sym-1", "1.0.0"),
        _record({"type": "META", "id": "META"}, {"title": "LIB", "docType": 2}),
        _record({"type": "RECT", "id": "r1"},
                {"dotX1": -10, "dotY1": 4, "dotX2": 10, "dotY2": -4,
                 "yAxisDirection": "up"}),
    ]
    return "\n".join(lines) + "\n"


def _write_project(
    root: Path,
    *,
    pcb: dict[str, str] | None = None,
    index_version: str | None = None,
    pcb_titles: dict[str, str] | None = None,
    page: str | None = None,
) -> Path:
    """``pcb`` maps a path under the project (``pcb/PCB1.epcb2``) to its text."""
    root.mkdir(parents=True, exist_ok=True)
    index: dict = {
        "name": root.name,
        "format": "folder",
        "profile": {"boards": {}, "schematics": {}, "sheets": {}, "pcbs": {}},
    }
    if index_version is not None:
        index["editorVersion"] = index_version
    if pcb_titles:
        for uuid, title in pcb_titles.items():
            index["profile"]["pcbs"][uuid] = {"uuid": uuid, "title": title}
    (root / f"{root.name}.eprj3").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")
    for relative, text in (pcb or {}).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    if page is not None:
        page_dir = root / "sch" / "Schematic1"
        page_dir.mkdir(parents=True, exist_ok=True)
        (page_dir / "P1.esch2").write_text(page, encoding="utf-8")
    return root


# --------------------------------------------------------------------------
# 1. finding the board: one rule, both entry points
# --------------------------------------------------------------------------


def test_the_folder_and_its_index_name_the_same_boards(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={
            "pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1"),
            "pcb/boards/PCB2.epcb2": _pcb_stream(uuid="b", title="PCB2"),
        },
    )
    index = next(root.glob("*.eprj3"))

    from_folder = pcb_files(root)
    from_index = pcb_files(index)

    assert from_folder == from_index, "the index names the folder, not a different set"
    assert {path.name for path in from_folder} == {"PCB1.epcb2", "PCB2.epcb2"}
    assert pcb_files(root) == from_folder, "two reads of one project give one order"


def test_a_schematic_page_is_not_a_board(tmp_path):
    root = _write_project(tmp_path / "proj", pcb={"pcb/PCB1.epcb2": _pcb_stream()})
    assert pcb_files(root) == [root / "pcb" / "PCB1.epcb2"], (
        "only .epcb2 under pcb/ may be picked up"
    )


# --------------------------------------------------------------------------
# 2. the refusals: no board, and more than one board
# --------------------------------------------------------------------------


def test_a_project_without_a_board_file_is_refused(tmp_path):
    root = _write_project(tmp_path / "proj")
    with pytest.raises(Eprj3Error) as caught:
        load_eprj3_pcb_source(root)
    assert ".epcb2" in str(caught.value) and "pcb/" in str(caught.value)


def test_a_board_file_without_a_board_document_is_refused(tmp_path):
    """A `.epcb2` holding only libraries is not a board — and not a clean one either."""
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": "\n".join([
            _head("SYMBOL", "sym-1", "1.0.0"),
            _record({"type": "RECT", "id": "r1"}, {"dotY1": 4}),
        ]) + "\n"},
    )
    with pytest.raises(Eprj3Error) as caught:
        load_eprj3_pcb_source(root)
    assert "PCB document" in str(caught.value)


def test_two_boards_are_refused_rather_than_the_first_picked(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={
            "pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1"),
            "pcb/PCB2.epcb2": _pcb_stream(uuid="b", title="PCB2"),
        },
    )
    with pytest.raises(Eprj3Error) as caught:
        load_eprj3_pcb_source(root)
    message = str(caught.value)
    assert "2 PCB files" in message
    assert "PCB1.epcb2" in message and "PCB2.epcb2" in message
    assert "first" in message, "the refusal has to say what it declined to do"


# --------------------------------------------------------------------------
# 3. the board's name: the project's own words first
# --------------------------------------------------------------------------


def test_the_board_takes_its_title_from_the_project_index(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1")},
        pcb_titles={"a": "Main Board"},
    )
    source = load_eprj3_pcb_source(root)
    assert source.project_meta["title"] == "Main Board"
    assert build_board_geometry(source).name == "Main Board"


def test_without_an_index_mapping_the_board_names_itself(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1")},
    )
    assert load_eprj3_pcb_source(root).project_meta["title"] == "PCB1"


# --------------------------------------------------------------------------
# 4. the version: 038F2's rule, not a second one
# --------------------------------------------------------------------------


def test_the_pcb_document_supplies_the_editor_version(tmp_path):
    root = _write_project(
        tmp_path / "proj", pcb={"pcb/PCB1.epcb2": _pcb_stream(version="4.1.60")},
    )
    source = load_eprj3_pcb_source(root)
    assert source.project_meta["editorVersion"] == "4.1.60"
    assert source.stats.editor_version == "4.1.60"
    assert build_board_geometry(source).edit_version == "4.1.60"


def test_the_index_keeps_its_say(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(version="4.1.60")},
        index_version="3.2.186",
    )
    source = load_eprj3_pcb_source(root)
    assert source.project_meta["editorVersion"] == "3.2.186"
    assert "editorVersionConflict" not in source.project_meta


def test_the_pcb_source_and_the_page_source_agree_on_the_version(tmp_path):
    """One project, two entry points, one answer — the rule lives in one place."""
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(version="4.1.60")},
        page="\n".join([
            _head("SCH_PAGE", "page-1", "4.1.60"),
            _record({"type": "WIRE", "id": "w1"}, {"zIndex": 1}),
        ]) + "\n",
    )
    _, page_meta = load_eprj3_text(root)
    pcb_meta = load_eprj3_pcb_source(root).project_meta
    assert page_meta["editorVersion"] == pcb_meta["editorVersion"] == "4.1.60"


# --------------------------------------------------------------------------
# 5. the frame: a PCB file is not a page
# --------------------------------------------------------------------------


def test_pcb_coordinates_and_its_libraries_are_read_verbatim(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(origin_y=1000.0)},
    )
    source = load_eprj3_pcb_source(root)
    board = source.first_document("PCB")
    canvas = next(record for record in board.records if record.type == "CANVAS")
    assert canvas.body["originY"] == 1000.0, (
        "a y-flip here would put the whole board in the wrong frame"
    )
    symbol = source.first_document("SYMBOL")
    rect = next(record for record in symbol.records if record.type == "RECT")
    assert rect.body["dotY1"] == 4, (
        "the SYMBOL copied into a PCB file is library payload, never flipped"
    )


# --------------------------------------------------------------------------
# 6. both builders consume the source unchanged
# --------------------------------------------------------------------------


def test_the_source_feeds_both_existing_builders(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        pcb={"pcb/PCB1.epcb2": _pcb_stream(uuid="a", title="PCB1")},
        pcb_titles={"a": "PCB1"},
    )
    source = load_eprj3_pcb_source(root)

    model = build_design_model(source)
    assert "U1" in model.components, "the netlist view reads the same documents"
    assert model.raw["project"]["format"] == "eprj3"

    board = build_board_geometry(source)
    assert board.name == "PCB1"
    assert board.edit_version == "4.1.60"
    assert source.stats.pcb_records > 0, "the PCB walk actually saw the document"
    assert source.stats.malformed_records == 0


def test_the_pcb_source_does_not_need_a_schematic_page(tmp_path):
    """A layout-only folder project still has a readable board."""
    root = _write_project(tmp_path / "proj", pcb={"pcb/PCB1.epcb2": _pcb_stream()})
    assert not (root / "sch").exists()
    source = load_eprj3_pcb_source(root)
    assert source.first_document("PCB") is not None
    assert build_board_geometry(source).name == "PCB1"
