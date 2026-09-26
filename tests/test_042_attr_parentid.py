"""042: an ATTR block displaced from its COMPONENT is filed by its parentId.

The bug this batch fixes is not "a missing feature" — it is a silent drop.
EasyEDA Pro's incremental save inserts an edited ``COMPONENT`` back at its old
``ticket`` position and appends that component's ATTRs to the end of the
document, so "the ATTRs follow the COMPONENT" holds only for untouched parts.
Where it fails, two things happen at once:

* the edited part is read with **no attributes at all**, and a component with no
  ``Designator`` is not a part downstream, so it leaves the model and the report
  without a trace (measured on ``robot_live.epro2``: 5 of 49 parts, including the
  3.3 V regulator and the USB-C socket);
* the displaced block is picked up by whatever component the block happens to
  follow, **overwriting** that neighbour's own values (measured: the same
  document renames a 100 nF capacitor to the resistor's ``R14`` and drops the
  resistor).

The fix is in ``schematic._split_page``: every ``COMPONENT`` records its own
record id, and an attribute whose ``parentId`` names one is filed to *that*
instance, whatever it follows. Adjacency stays as the fallback for documents
that parent their ATTRs elsewhere (the synthetic ``eprj3`` page does).

These tests use a **synthetic** project built in ``tmp_path`` (a minimal
``.epru`` inside a ``.epro2`` zip) rather than a real board, and the real
fixtures only through their own public readings, so nothing here depends on 岳's
project being on the machine — except the one acceptance test that skips itself
when it is not.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.geometry import ParseStats
from boardwise.parsers.epru import load_epro2_source
from boardwise.parsers.schematic import (
    _split_page,
    _iter_schematic_records,
    build_project_model,
    collect_page_layout,
)

FIXTURES = Path(__file__).parent / "fixtures"
#: 岳's own live project. Not in the repository (it is a real board): the
#: acceptance test below skips itself when the file is absent.
ROBOT_LIVE = Path(__file__).resolve().parents[1] / ".tmp_robot_review" / "robot_live.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
MOTOR = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"
EPRJ3 = FIXTURES / "eprj3_synth"


# --------------------------------------------------------------------------
# a synthetic page with a displaced block
# --------------------------------------------------------------------------


def _record(record_type: str, uid: str | None = None, body: dict | None = None,
            ticket: int | None = None, first_ticket: int | None = None) -> str:
    """One ``.epru`` line: ``<envelope JSON>||<body JSON>`` (no trailing ``|``)."""
    envelope: dict = {"type": record_type}
    if uid is not None:
        envelope["id"] = uid
    if ticket is not None:
        envelope["ticket"] = ticket
    if first_ticket is not None:
        envelope["firstTicket"] = first_ticket
    return json.dumps(envelope) + "||" + (json.dumps(body) if body is not None else "")


def _attr(uid: str, parent: str, key: str, value: str) -> str:
    return _record("ATTR", uid, {"parentId": parent, "key": key, "value": value})


def _component(uid: str, part_id: str, ticket: int, first_ticket: int,
               x: float, y: float, z_index: int | None) -> str:
    return _record("COMPONENT", uid, {
        "partId": part_id, "ticket": ticket, "firstTicket": first_ticket,
        "x": x, "y": y, "rotation": 0, "isMirror": False, "zIndex": z_index,
    })


def _page(*lines: str) -> list[str]:
    return [_record("DOCHEAD", "page-1", {"docType": "SCH_PAGE", "uuid": "page-1"}),
            *lines]


def _project(tmp_path: Path, lines: list[str], name: str = "synth.epro2") -> Path:
    """A one-page ``.epro2`` archive holding `lines` as its record stream."""
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


def _records_of(path: Path) -> list:
    """The page's records, before any grouping — what ``_split_page`` is handed."""
    from boardwise.parsers.epru_stream import load_epru_text

    text, _meta = load_epru_text(path)
    return _iter_schematic_records(text, ParseStats())


#: A page that reproduces the measured shape: the frame's own block sits
#: *before* its COMPONENT record, an edited capacitor (``c-c2``) was pushed back
#: to its ``firstTicket`` slot, and its block was appended straight after the
#: untouched resistor's block — no separator, so nothing but the record id says
#: whose it is.
_INTERLEAVED = _page(
    _attr("f-w", "frame", "Width", "1170"),
    _attr("f-h", "frame", "Height", "825"),
    _attr("f-ps", "frame", "Page Size", "A4"),
    _component("frame", "pidframe.1", 1, 1, 0.0, 0.0, None),
    _component("c-c2", "C0402.1", 104, 100, 40.0, -20.0, 6),
    _component("c-r1", "R0402.1", 101, 101, 10.0, -20.0, 5),
    _attr("a-des", "c-r1", "Designator", "R1"),
    _attr("a-val", "c-r1", "Value", "10k"),
    _attr("b-des", "c-c2", "Designator", "C2"),
    _attr("b-val", "c-c2", "Value", "100nF"),
    _attr("b-sym", "c-c2", "Symbol", "sym-c2"),
)


def test_a_displaced_block_is_filed_by_the_record_id_it_names(tmp_path):
    """Both parts survive, and each keeps its own designator.

    Before 042 the page read as *one* part: ``R1`` holding ``C2``'s value, and
    no ``C2`` at all — the difference between "the drawing has two parts" and
    "the model has one".
    """
    path = _project(tmp_path, _INTERLEAVED)
    stats = ParseStats()
    project = build_project_model(path, parse_stats=stats)
    components = project.boards[0].components
    assert {name: part.value for name, part in components.items()} == {
        "R1": "10k",
        "C2": "100nF",
    }
    assert stats.attrs_attached_by_parent_id == 3, (
        "the three attributes that only the record id could place"
    )
    assert stats.instances_without_designator == 0


def test_the_neighbour_of_a_displaced_block_is_not_renamed(tmp_path):
    """The overwrite half of the bug, asserted on its own.

    The displaced block is the *last* thing on the page, directly after R1's own
    block, so a rule that files by position writes ``C2`` over ``R1`` — which is
    how one document's 100 nF capacitor came to be called ``R14``.
    """
    path = _project(tmp_path, _INTERLEAVED)
    instances = _split_page(_records_of(path)).instances
    by_designator = {
        inst.attrs.get("Designator"): inst for inst in instances
        if inst.attrs.get("Designator")
    }
    assert set(by_designator) == {"R1", "C2"}
    assert by_designator["R1"].attrs["Value"] == "10k"
    assert by_designator["C2"].attrs["Value"] == "100nF"
    # R1's block is its own; the displaced one carries R1's *neighbour* id
    assert by_designator["R1"].record_id == "c-r1"
    assert by_designator["C2"].record_id == "c-c2"


def test_a_block_that_precedes_its_component_is_found(tmp_path):
    """The lookup cannot be "scan backwards from the component".

    On ``robot_live.epro2`` the page frame's block sits **before** its COMPONENT
    record — the editor moved the component, not the attributes — so a
    one-directional search would miss it. Here the frame's ``Width`` arrives
    before the frame does.
    """
    path = _project(tmp_path, _INTERLEAVED)
    split = _split_page(_records_of(path))
    frame = next(inst for inst in split.instances if inst.z_index is None)
    assert frame.record_id == "frame"
    # The frame's attributes stay page-level (see the next test), which is the
    # one exception to the parentId rule; what this test pins is that the record
    # *id* of the frame is read at all, from a block that precedes it.
    assert any(item.body.get("parentId") == "frame" for item in split.loose)


def test_the_page_frame_keeps_its_attributes_page_level(tmp_path):
    """A page is not a placement, so its geometry stays readable as a page.

    The frame is the one COMPONENT with no ``zIndex`` — the marker the parts
    pass, the layout reader and the drop counter all already use. Its ATTRs
    (``Width``/``Height``/``Page Size``/``@Page Name``…) stay in the loose list,
    which is where :func:`collect_page_layout` reads ``sheet_attrs`` from, so
    attaching them to the instance would move a *page's* geometry onto a part
    for no reader's benefit (measured: it changes the 高速板's pooled frame box
    from 1655x1170 to 1170x825).
    """
    path = _project(tmp_path, _INTERLEAVED)
    split = _split_page(_records_of(path))
    loose_keys = {item.body.get("key") for item in split.loose
                  if item.body.get("parentId") == "frame"}
    assert loose_keys == {"Width", "Height", "Page Size"}
    layout = collect_page_layout(path)
    assert layout.sheet_attrs == {"Width": "1170", "Height": "825", "Page Size": "A4"}
    assert layout.sheet_origin == (0.0, 0.0)
    assert [part.designator for part in layout.parts] == ["C2", "R1"]


def test_page_level_kinds_are_never_filed_by_parent_id(tmp_path):
    """``NET`` / ``NO_CONNECT`` / a standalone ``Global Net Name`` stay loose.

    Their ``parentId`` is a wire group, a symbol pin (``"<container>-e<n>"``) or
    a *library* template id — never a component placement. A rule that filed
    "anything whose parentId is some id I know" would sink them into the
    neighbour they follow, and the netlist would lose the labels.
    """
    path = _project(tmp_path, _page(
        _component("c-r2", "R0402.1", 1, 1, 0.0, 0.0, 4),
        _attr("n1", "c-r2", "NET", "VCC"),           # parentId is a component id here
        _attr("n2", "c-r2", "NO_CONNECT", "yes"),
        _attr("n3", "c-r2", "Global Net Name", "PGND"),
        _attr("n4", "c-r2", "Designator", "R2"),
    ))
    records = _records_of(path)
    split = _split_page(records)
    (instance,) = split.instances
    assert instance.attrs == {"Designator": "R2"}
    assert sorted(item.body["key"] for item in split.loose) == [
        "Global Net Name", "NET", "NO_CONNECT",
    ]


def test_a_document_that_parents_attrs_elsewhere_keeps_the_adjacency_rule(tmp_path):
    """The fallback, stated as a test.

    A stream whose ATTRs name no component (an unknown parentId, or none at
    all) is read exactly as before — adjacency decides. That is what keeps the
    synthetic ``eprj3`` page working, whose every ATTR parents to something
    other than a component record.
    """
    path = _project(tmp_path, _page(
        _component("c-u3", "U.1", 1, 1, 0.0, 0.0, 7),
        _attr("x1", "", "Designator", "U3"),
        _attr("x2", "no-such-record", "Value", "LM358"),
    ))
    stats = ParseStats()
    project = build_project_model(path, parse_stats=stats)
    part = project.boards[0].components["U3"]
    assert part.value == "LM358"
    assert stats.attrs_attached_by_parent_id == 0, (
        "nothing was placed by a record id, so the counter must not move"
    )


def test_the_synthetic_eprj3_page_is_read_by_adjacency_and_only_by_adjacency():
    """The one fixture whose ATTRs never parent to a component.

    2 parts before 042 and 2 after, and the counter is 0: the new rule is a
    no-op there, which is why the eprj3 read does not need a special case.
    """
    stats = ParseStats()
    project = build_project_model(EPRJ3, parse_stats=stats)
    assert project.component_count() == 2
    assert stats.attrs_attached_by_parent_id == 0
    assert stats.instances_without_designator == 0


# --------------------------------------------------------------------------
# the counters, measured on the fixture set (042 §WI-2)
# --------------------------------------------------------------------------

#: fixture -> (components, attrs_attached_by_parent_id). Measured 2026-09-26.
#: The counter is 0 exactly where the document was never incrementally edited
#: (the golden board, the CH340G backup, the 智能药箱 board, the synthetic
#: eprj3 page); it is non-zero wherever a block was displaced, which is the
#: signal that used to be nothing at all.
MEASURED = {
    "ch340_golden.epro2": (17, 0),
    "ProPrj_CH340G_2026-09-13.epro2": (17, 0),
    "llc_board.epro2": (47, 5),
    "ProPrj_智能药箱_2026-09-17.epro2": (43, 0),
    "ProPrj_毕设FOC驱动板_2026-09-17.epro2": (155, 18),
    "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2": (49, 156),
    "ProPrj_高速电机控制器_2026-09-16.epro2": (163, 1718),
    "eprj3_synth": (2, 0),
}


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_the_counters_report_each_fixture(name):
    """Both counters, per fixture, and the invariant that matters: nothing is
    unnamed. ``instances_without_designator`` was 5 on ROBOT and 67 on the 高速板
    *before* the fix and is 0 everywhere now — that number is the one a reviewer
    can look at to know a parse did not swallow a part."""
    components, attached = MEASURED[name]
    stats = ParseStats()
    project = build_project_model(FIXTURES / name, parse_stats=stats)
    assert project.component_count() == components
    assert stats.attrs_attached_by_parent_id == attached
    assert stats.instances_without_designator == 0
    assert stats.malformed_records == 0
    # the new keys are part of the reportable stats, not private fields
    assert stats.as_dict()["attrs_attached_by_parent_id"] == attached
    assert stats.as_dict()["instances_without_designator"] == 0


# --------------------------------------------------------------------------
# acceptance: the PCB document is the ground truth inside the same file
# --------------------------------------------------------------------------

#: (fixture, expected part count). The PCB document parents its ATTRs by record
#: id the way the schematic now does, so it lists, per designator, what the
#: editor actually placed — the one independent check available offline.
WITH_COPPER = [
    ("llc_board.epro2", 47),
    ("ProPrj_ROBOT ctrl FOC_2026-09-16.epro2", 49),
    ("ProPrj_高速电机控制器_2026-09-16.epro2", 49),
    ("ProPrj_毕设FOC驱动板_2026-09-17.epro2", 33),
]


@pytest.mark.parametrize("name,pcb_count", WITH_COPPER)
def test_every_part_the_copper_has_is_named_by_the_schematic(name, pcb_count):
    """The acceptance form of §WI-1: no designator on the PCB is missing.

    On ROBOT this is exact — 49 designators on both sides, and the PCB's five
    extras are precisely the ones that used to be dropped. On the 高速板 the
    schematic holds several boards' worth (145 names incl. the second board)
    while the PCB only covers the driver board, so the assertion is the subset
    plus the count.
    """
    placed = {p.designator for p in
              load_epro2_source(FIXTURES / name).pcb_context().placements
              if p.designator}
    assert len(placed) == pcb_count
    named = set(build_project_model(FIXTURES / name).designators())
    assert placed - named == set()
    if name == "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2":
        assert len(named) == pcb_count, "one board, so the two lists are equal"
        assert {"C11", "R4", "SWD", "U8", "USB1"} <= named, (
            "the five the PCB lists and the parse used to drop"
        )


@pytest.mark.skipif(not ROBOT_LIVE.exists(),
                    reason="岳's live project is not on this machine (never committed)")
def test_the_robot_boards_live_export_reads_as_49_parts():
    """§5's acceptance, against the project the bug was found on.

    ``robot_live.epro2`` is that project's own export, so this is the same
    question ``sch.geometry`` answered live: 49 parts, not 44, and the five that
    were missing carry the parts the board actually has — R4 the U-phase shunt,
    U8 the AMS1117-3.3 regulator, USB1 the Type-C socket, SWD the debug header
    and C11 the capacitor that had been answering to R4's name.
    """
    path = ROBOT_LIVE
    stats = ParseStats()
    project = build_project_model(path, parse_stats=stats)
    assert project.component_count() == 49
    assert sorted(project.designators()) == [
        "10UH", "C1", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17",
        "C18", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "DRV1", "R1",
        "R10", "R11", "R12", "R13", "R14", "R2", "R3", "R4", "R5", "R6", "R7",
        "R8", "R9", "SCREW1", "SCREW2", "SCREW3", "SCREW4", "SWD", "U1", "U2",
        "U3", "U4", "U5", "U6", "U7", "U8", "USB1", "X2",
    ]
    assert project.designators() == sorted(
        p.designator for p in load_epro2_source(path).pcb_context().placements
        if p.designator
    ), "and that list is exactly the board's own copper"
    components = project.boards[0].components
    assert components["U8"].mpn == "AMS1117-3.3"
    assert components["USB1"].lcsc_part == "C2765186"
    assert components["R4"].mpn == "RE1206F1R100"
    assert components["C11"].mpn == "CC0603KRX7R9BB104"
    assert components["SWD"].mpn == "HX PZ2.54-1x4P WZ"
    assert stats.attrs_attached_by_parent_id > 0, "this document was edited"
    assert stats.instances_without_designator == 0
    # and the schematic keeps the instance attribute the task book names
    r4 = next(inst for inst in _split_page(_records_of(path)).instances
              if inst.attrs.get("Designator") == "R4")
    assert r4.attrs["Designator"] == "R4"
    assert r4.record_id == "55938e9efdab989f"
