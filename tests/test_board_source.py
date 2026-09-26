"""Reading a board, either format (task 008b, work item 2).

The load-bearing test here is the **cross-validation**: the `.epro2` reader's
placement link is checked against `build_schematic_model`'s — the parser that has
been in service since 005 — on every exported fixture. It is not a style
preference; the first version of this reader grouped an instance's attributes by
hand and found "85 placements" that were a *different* 85, because the grouping
rule has four clauses (an attribute run ends at any other element, except
`ELE_PLACEHOLDER` and `LINE`, and a body-less record ends it too). The reader now
calls the proven parser, and this file is what says so out loud.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.engines.generate import strip_dangling_nets
from boardwise.parsers.board_source import (
    LocalProjectError,
    library_footprint_name,
    load_board_source,
    load_exported_project,
    load_local_project,
)
from boardwise.parsers.schematic import build_project_model

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "blocklib" / "sources"
FIXTURES = ROOT / "tests" / "fixtures"

PILLBOX = SOURCES / "smart_pillbox.eprj2"
THESIS = SOURCES / "thesis_FOC_board.eprj2"
EDIT_LOG_ONLY = SOURCES / "highspeed_motor_ctrl.eprj2"

#: The four exported fixtures. Two of them are the same boards as the two
#: unharvestable local projects — that pair is the point of the module.
EXPORTS = [
    FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2",
    FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
    FIXTURES / "ch340_golden.epro2",
    FIXTURES / "llc_board.epro2",
]

HIGHS= FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"


# --------------------------------------------------------------------------
# the local project
# --------------------------------------------------------------------------


def test_a_local_project_carries_the_library_identity_it_needs():
    project = load_local_project(PILLBOX)
    assert project.kind == "eprj2-local"
    assert project.name == "智能药箱"
    assert project.materialised
    device = next(iter(project.referable_devices().values()))
    assert device.library_doc_uuid and device.library_uuid
    assert device.library_uuid == "0819f05c4eef4c71ace90d822a990e87"
    assert device.attributes.get("Supplier Part")


def test_an_edit_log_only_project_is_refused_with_that_reason():
    with pytest.raises(LocalProjectError, match="only an edit log"):
        load_local_project(EDIT_LOG_ONLY)


# --------------------------------------------------------------------------
# the export
# --------------------------------------------------------------------------


def test_an_export_carries_the_library_identity_it_needs():
    project = load_exported_project(ROBOT)
    assert project.kind == "epro2-export"
    assert project.name == "ROBOT ctrl FOC"
    assert project.materialised
    # 49, not 44: the export reader goes through the parser's `_split_page`, so
    # 042 §WI-1's displaced-block fix reaches it too. The file's own DEVICE
    # documents are untouched by that (60) — the change is which placements the
    # reader can see, and the PCB document lists all 49 of them.
    assert len(project.placements) == 49
    assert len(project.devices) == 60
    device = next(d for d in project.devices.values() if d.is_real_part)
    assert device.library_uuid == "0819f05c4eef4c71ace90d822a990e87"
    assert device.library_doc_uuid
    assert device.attributes["Supplier Part"].startswith("C")


@pytest.mark.parametrize("path", EXPORTS, ids=lambda p: p.name[:28])
def test_the_export_reader_agrees_with_the_proven_parser_on_every_fixture(path):
    """Same designators, same devices — checked against 005's parser.

    040b: the parser's answer is a **project** (one model per board), so the
    comparison is against every board's designators, not against one merged
    dict — which is also the stronger statement, since a merged dict was what
    let two boards' same-named parts overwrite each other.
    """
    project = load_exported_project(path)
    parser_project = build_project_model(path)
    mine = {placement.designator for placement in project.placements}
    assert mine == set(parser_project.designators()), (
        f"{path.name}: the export reader and build_project_model disagree"
    )
    for board_model in parser_project.boards:
        assert set(board_model.components) <= mine
    assert all(placement.device_uuid for placement in project.placements)


@pytest.mark.parametrize("path", EXPORTS, ids=lambda p: p.name[:28])
def test_the_export_reader_keeps_the_library_footprint_vocabulary(path):
    """`R0402`, not `0402` — and the human label is nowhere near this field."""
    project = load_exported_project(path)
    names = set()
    for device in project.referable_devices().values():
        if not device.is_real_part:
            continue
        name, verified = library_footprint_name(project, device)
        assert verified is None, "no bridge check has run, so nothing is verified"
        assert name, device.uuid
        names.add(name)
        human = device.attributes.get("Supplier Footprint", "")
        assert not name.isdigit()
        if human:
            assert name.upper() != human.upper() or not human[0].isalpha()
    assert names, "no placed device had a resolvable footprint"


def test_a_missing_footprint_attribute_is_not_guessed_at():
    project = load_exported_project(ROBOT)
    device = next(iter(project.devices.values()))
    device.attributes.pop("Footprint", None)
    name, verified = library_footprint_name(project, device)
    assert (name, verified) == ("", None)


# --------------------------------------------------------------------------
# the same board, two formats — the finding this module exists for
# --------------------------------------------------------------------------


def test_the_same_board_is_unharvestable_as_an_edit_log_and_fine_as_an_export():
    """Measured: 0 identity in the local file, full identity in the export.

    This is the evidence behind "re-save it locally, or export an `.epro2`" —
    and behind reading that sentence as *the save mode never stored the
    attributes*, not as *the format cannot hold them*.
    """
    with pytest.raises(LocalProjectError, match="only an edit log"):
        load_board_source(SOURCES / "ROBOT_ctrl_FOC.eprj2")
    exported = load_board_source(ROBOT)
    real = [d for d in exported.referable_devices().values() if d.is_real_part]
    # 19, not 15: the four real parts whose attribute blocks the editor had
    # displaced are visible again (042 §WI-1) — and the board's PCB lists them.
    assert len(real) == 19
    assert all(d.attributes.get("Supplier Part") for d in real)


# --------------------------------------------------------------------------
# the dispatcher
# --------------------------------------------------------------------------


def test_the_format_is_decided_by_the_file():
    assert load_board_source(PILLBOX).kind == "eprj2-local"
    assert load_board_source(ROBOT).kind == "epro2-export"


def test_an_unknown_format_is_refused_by_name(tmp_path):
    odd = tmp_path / "board.kicad_pcb"
    odd.write_text("nope", encoding="utf-8")
    with pytest.raises(LocalProjectError, match="unsupported board format"):
        load_board_source(odd)


def test_a_file_that_is_not_a_project_is_refused(tmp_path):
    not_a_project = tmp_path / "board.epro2"
    not_a_project.write_text("not a zip", encoding="utf-8")
    with pytest.raises(LocalProjectError):
        load_board_source(not_a_project)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(LocalProjectError, match="not a file"):
        load_board_source(tmp_path / "nope.eprj2")
