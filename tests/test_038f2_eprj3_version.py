"""038F2 — where a folder (`.eprj3`) project keeps its editor version.

An `.epro2` names its editor in `project2.json`; a folder project has no such
file, and the index the format does have usually carries no `editorVersion`
either — so every consumer that asks "which editor wrote this"
(`ParseStats.editor_version`) read *unknown* for a V4 export, including the
real sample this batch was measured against.

The version **is** in the project, once per document, in the `DOCHEAD` body's
`editVersion`. Only the documents that *are* the design may speak for it —
`SCH` / `SCH_PAGE` / `PCB` / `PANEL`. `SYMBOL` / `DEVICE` / `FOOTPRINT` are
library payload carried inside the same stream, and their `editVersion` is
whenever that part was last saved somewhere else, so it is not this project's
editor version and must never stand in for it.

The rules, each tested below: the index wins when it names a version; one
content version becomes `editorVersion`; several are a **conflict** that is
disclosed under `editorVersionConflict` and deliberately not resolved by
picking one; none stays unknown. The version travels to `ParseStats` through the
`meta["editorVersion"]` path every container already uses — `ParseStats` itself
is not extended and `edit_version` is not filled to make the pair look neat.
"""

from __future__ import annotations

import json
from pathlib import Path

from boardwise.core.geometry import ParseStats
from boardwise.parsers.eprj3 import load_eprj3_text
from boardwise.parsers.schematic import build_schematic_model


# --------------------------------------------------------------------------
# a project builder: one folder, one DOCHEAD per document, versions explicit
# --------------------------------------------------------------------------


def _record(envelope: dict, body: dict | None = None) -> str:
    head = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return head + "|||"
    return head + "||" + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "|"


def _head(doc_type: str, version: str | None = None) -> str:
    body = {"docType": doc_type, "uuid": f"u-{doc_type.lower()}"}
    if version is not None:
        body["editVersion"] = version
    return _record({"type": "DOCHEAD"}, body)


def _paged(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _write_project(
    root: Path,
    *,
    index_version: str | None = None,
    page_versions: tuple[str | None, ...] = (None,),
    library_versions: tuple[str, ...] = (),
    cfg_version: str | None = None,
    pcb_version: str | None = None,
    panel_version: str | None = None,
) -> Path:
    """One synthetic folder project, every version spelled out by the caller."""
    root.mkdir(parents=True, exist_ok=True)
    index: dict = {
        "name": root.name,
        "format": "folder",
        "profile": {"boards": {}, "schematics": {}, "sheets": {}, "pcbs": {}},
    }
    if index_version is not None:
        index["editorVersion"] = index_version
    (root / f"{root.name}.eprj3").write_text(
        json.dumps(index, ensure_ascii=False), encoding="utf-8")

    page_dir = root / "sch" / "Schematic1"
    page_dir.mkdir(parents=True, exist_ok=True)
    for number, page_version in enumerate(page_versions, start=1):
        lines = [_head("SCH_PAGE", page_version),
                 _record({"type": "WIRE", "id": "w1"}, {"zIndex": 1})]
        for library_version in library_versions:
            for library_type in ("SYMBOL", "DEVICE", "FOOTPRINT"):
                lines.append(_head(library_type, library_version))
        (page_dir / f"P{number}.esch2").write_text(_paged(*lines), encoding="utf-8")

    if cfg_version is not None:
        (page_dir / "Schematic1.ecfg").write_text(
            _paged(_head("SCH", cfg_version)), encoding="utf-8")
    if pcb_version is not None:
        (root / "pcb").mkdir(exist_ok=True)
        (root / "pcb" / "PCB1.epcb2").write_text(
            _paged(_head("PCB", pcb_version)), encoding="utf-8")
    if panel_version is not None:
        (root / "panel").mkdir(exist_ok=True)
        (root / "panel" / "Panel1.epan2").write_text(
            _paged(_head("PANEL", panel_version)), encoding="utf-8")
    return root


def _meta(root: Path) -> tuple[str, dict]:
    return load_eprj3_text(root)


# --------------------------------------------------------------------------
# 1. the index keeps its precedence
# --------------------------------------------------------------------------


def test_the_index_names_the_version_and_content_never_overrides_it(tmp_path):
    root = _write_project(
        tmp_path / "proj",
        index_version="3.2.186",
        page_versions=("4.1.60",),
        pcb_version="4.1.61",
    )
    _, meta = _meta(root)

    assert meta["editorVersion"] == "3.2.186"
    assert "editorVersionConflict" not in meta, (
        "a conflict between documents does not matter once the index has spoken"
    )


def test_the_index_and_the_documents_may_agree(tmp_path):
    root = _write_project(
        tmp_path / "proj", index_version="4.1.60", cfg_version="4.1.60",
        page_versions=("4.1.60",), pcb_version="4.1.60",
    )
    _, meta = _meta(root)

    assert meta["editorVersion"] == "4.1.60"
    assert "editorVersionConflict" not in meta


# --------------------------------------------------------------------------
# 2. the content documents: one version, from any of them
# --------------------------------------------------------------------------


def test_pages_that_agree_give_one_version(tmp_path):
    root = _write_project(tmp_path / "proj", page_versions=("4.1.60", "4.1.60"))
    _, meta = _meta(root)

    assert meta["editorVersion"] == "4.1.60"
    assert "editorVersionConflict" not in meta
    assert meta["pages"] == ["P1", "P2"]


def test_the_root_schematic_and_the_pages_agree(tmp_path):
    root = _write_project(
        tmp_path / "proj", cfg_version="4.1.60", page_versions=("4.1.60",))
    _, meta = _meta(root)

    assert meta["editorVersion"] == "4.1.60"
    assert "editorVersionConflict" not in meta, (
        "the same version written twice is one version, not a conflict"
    )


def test_pcb_and_panel_documents_supply_the_version(tmp_path):
    from_pcb = _meta(_write_project(tmp_path / "pcb_only", pcb_version="4.1.60"))[1]
    from_panel = _meta(_write_project(tmp_path / "panel_only", panel_version="4.1.60"))[1]

    assert from_pcb["editorVersion"] == "4.1.60"
    assert from_panel["editorVersion"] == "4.1.60"


def test_reading_a_version_does_not_pull_pcb_records_into_the_stream(tmp_path):
    root = _write_project(tmp_path / "proj", page_versions=(None,), pcb_version="4.1.60")
    text, meta = _meta(root)

    assert meta["editorVersion"] == "4.1.60"
    assert '"docType":"PCB"' not in text, (
        "tier A reads the schematic tree; the PCB file is opened for its DOCHEAD only"
    )


# --------------------------------------------------------------------------
# 3. library payload cannot impersonate the editor
# --------------------------------------------------------------------------


def test_a_library_version_never_stands_in_for_the_editor(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=(None,), library_versions=("2.3.0",))
    _, meta = _meta(root)

    assert meta.get("editorVersion") is None
    assert "editorVersionConflict" not in meta, (
        "one library version is not a conflict either — it is simply not the "
        "project's version"
    )


def test_a_library_version_next_to_a_content_version_is_ignored(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=("4.1.60",), library_versions=("2.3.0",))
    _, meta = _meta(root)

    assert meta["editorVersion"] == "4.1.60"
    assert "editorVersionConflict" not in meta


def test_no_version_anywhere_stays_unknown(tmp_path):
    root = _write_project(tmp_path / "proj", page_versions=(None,))
    _, meta = _meta(root)

    assert meta.get("editorVersion") is None
    assert "editorVersionConflict" not in meta


# --------------------------------------------------------------------------
# 4. a conflict is disclosed, never resolved by picking
# --------------------------------------------------------------------------


def test_conflicting_content_versions_are_disclosed_not_picked(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=("4.1.60",), pcb_version="4.1.61")
    _, meta = _meta(root)

    assert meta.get("editorVersion") is None, (
        "neither value may be presented as the version")
    assert meta["editorVersionConflict"] == ["4.1.60", "4.1.61"]


def test_three_way_conflict_lists_every_value_in_stream_order(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=("4.1.60", "4.1.62"), cfg_version="4.1.61")
    _, meta = _meta(root)

    assert meta.get("editorVersion") is None
    assert meta["editorVersionConflict"] == ["4.1.60", "4.1.62", "4.1.61"]


# --------------------------------------------------------------------------
# 5. the same fact through the parse path every consumer uses
# --------------------------------------------------------------------------


def test_the_version_reaches_parse_stats_and_edit_version_stays_alone(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=("4.1.60",), library_versions=("2.3.0",))
    stats = ParseStats(source=str(root))

    model = build_schematic_model(root, parse_stats=stats)

    assert stats.editor_version == "4.1.60"
    assert stats.edit_version is None, (
        "edit_version keeps its own per-document meaning; it is not filled to match"
    )
    assert model.components == {}
    assert stats.malformed_records == 0


def test_a_conflict_reaches_parse_stats_as_unknown(tmp_path):
    root = _write_project(
        tmp_path / "proj", page_versions=("4.1.60",), pcb_version="4.1.61")
    stats = ParseStats(source=str(root))

    build_schematic_model(root, parse_stats=stats)

    assert stats.editor_version is None
