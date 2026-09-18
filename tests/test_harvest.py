"""Harvesting the curated library from the source boards (task 008b, item 2).

Every claim the task asks the harvest to be able to make has a test here:

* an entry reconciles with the board it came from (its `designators` name real
  parts on that board);
* re-running the tool is idempotent — the same board twice produces the same
  entry, and the history gains nothing;
* the same C-number on two boards becomes **one** entry whose provenance
  accumulates (`U1@smart_pillbox`, `U5@thesis_FOC_board`);
* a board that cannot be harvested says so instead of contributing an empty
  success.

The numbers are the measured ones, so a change in the reader or the boards shows
up as a failing assertion rather than as a quietly different library.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.parts import (
    PART_LIBRARY_KIND,
    UNKNOWN,
    PartEntry,
    PartProvenance,
    library_to_json,
    load_corrections,
    load_parts,
)
from boardwise.engines.harvest import (
    BASIC_CLASS_EVIDENCE,
    FOOTPRINT_UUID_PATHS,
    _merge,
    basic_flag,
    devices_to_verify,
    footprint_uuid_of_device,
    harvest,
    harvest_board,
    parameters_of,
    placed_devices,
    prefer_footprint_spelling,
    reconcile_counts,
    source_label,
    spelling_notes,
    strip_bridge_decided,
    strip_bridge_decided_notes,
)
from boardwise.parsers.board_source import load_local_project

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "blocklib" / "sources"
FIXTURES = ROOT / "tests" / "fixtures"
PILLBOX = SOURCES / "smart_pillbox.eprj2"
THESIS = SOURCES / "thesis_FOC_board.eprj2"
EDIT_LOG_ONLY = SOURCES / "highspeed_motor_ctrl.eprj2"
#: Exported as `.epro2` because they could not be harvested as local projects —
#: the same boards, the other format. The 2026-09-16 pair was superseded by the
#: 2026-09-17 pair for two of the four; all six boards are now in the library.
HIGHS = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX_EPRO2 = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
THESIS_EPRO2 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
LIBRARY = ROOT / "blocklib" / "parts.json"
#: The sidecar the committed library is harvested *with*: the two identity
#: re-anchorings and the datasheet links the boards cannot supply.
CORRECTIONS = ROOT / "blocklib" / "parts.corrections.json"

#: The harvest the committed library comes from. One list, so the artifact and
#: the tests cannot drift apart.
HARVEST_SOURCES = [PILLBOX, THESIS, HIGHS, ROBOT, PILLBOX_EPRO2, THESIS_EPRO2]

#: Measured 2026-09-17 (the library was topped up with the two `.epro2` exports
#: of the pillbox and the thesis board on top of the four 2026-09-16 sources).
#: Per board, then merged.
PILLBOX_ENTRIES = 13
THESIS_ENTRIES = 41
HIGHS_ENTRIES = 47
ROBOT_ENTRIES = 15
PILLBOX_EPRO2_ENTRIES = 13
THESIS_EPRO2_ENTRIES = 35
MERGED_ENTRIES = 92
#: Designators on parts that two or more boards share, which is why the
#: per-board totals exceed the library size by this much.
SHARED_ENTRIES = (
    PILLBOX_ENTRIES
    + THESIS_ENTRIES
    + HIGHS_ENTRIES
    + ROBOT_ENTRIES
    + PILLBOX_EPRO2_ENTRIES
    + THESIS_EPRO2_ENTRIES
    - MERGED_ENTRIES
)


def test_a_local_project_carries_the_library_identity_it_needs():
    """The finding that made 008b possible — measured, not assumed."""
    project = load_local_project(PILLBOX)
    assert project.name == "智能药箱"
    assert project.materialised
    # The device uuid the page references and the library uuid it answers to are
    # different keys; both must be there.
    device = next(iter(project.referable_devices().values()))
    assert device.library_doc_uuid and device.library_uuid
    assert device.library_uuid == "0819f05c4eef4c71ace90d822a990e87"
    assert device.attributes.get("Supplier Part")


def test_the_harvest_reports_what_each_board_contributed():
    result = harvest(HARVEST_SOURCES)
    reports = {r.board: r for r in result.sources}
    assert reports["smart_pillbox"].entries == PILLBOX_ENTRIES
    assert reports["thesis_FOC_board"].entries == THESIS_ENTRIES
    assert reports["ProPrj_高速电机控制器_2026-09-16"].entries == HIGHS_ENTRIES
    assert reports["ProPrj_ROBOT ctrl FOC_2026-09-16"].entries == ROBOT_ENTRIES
    assert reports["ProPrj_智能药箱_2026-09-17"].entries == PILLBOX_EPRO2_ENTRIES
    assert reports["ProPrj_毕设FOC驱动板_2026-09-17"].entries == THESIS_EPRO2_ENTRIES
    assert reports["smart_pillbox"].placements == 43
    assert reports["thesis_FOC_board"].placements == 137
    # The format each board was read as is reported: the same board can be
    # harvestable in one and not the other.
    assert reports["smart_pillbox"].kind == "eprj2-local"
    assert reports["ProPrj_ROBOT ctrl FOC_2026-09-16"].kind == "epro2-export"
    # The abstract library devices are reported, never curated.
    assert "Res_0603" in reports["smart_pillbox"].placeholder_devices
    assert all(p.lcsc for p in result.library.parts)


def test_every_entry_reconciles_with_the_board_it_names():
    result = harvest(HARVEST_SOURCES)
    counts = reconcile_counts(result)
    assert counts["smart_pillbox"] == PILLBOX_ENTRIES
    assert counts["thesis_FOC_board"] == THESIS_ENTRIES
    assert counts["ProPrj_高速电机控制器_2026-09-16"] == HIGHS_ENTRIES
    assert counts["ProPrj_ROBOT ctrl FOC_2026-09-16"] == ROBOT_ENTRIES
    assert counts["ProPrj_智能药箱_2026-09-17"] == PILLBOX_EPRO2_ENTRIES
    assert counts["ProPrj_毕设FOC驱动板_2026-09-17"] == THESIS_EPRO2_ENTRIES
    # A shared part appears in every total it is on, which is why the sum exceeds
    # the library size by exactly the number of shared appearances.
    assert sum(counts.values()) == len(result.library.parts) + SHARED_ENTRIES


def test_re_harvesting_the_same_board_is_idempotent():
    once = harvest(HARVEST_SOURCES)
    twice = harvest(HARVEST_SOURCES + HARVEST_SOURCES)
    assert len(twice.library.parts) == len(once.library.parts)
    assert json.dumps(library_to_json(twice.library), sort_keys=True) == json.dumps(
        library_to_json(once.library), sort_keys=True
    )
    # ...and the history did not grow duplicates either
    for part in twice.library.parts:
        assert len(part.provenance.designators) == len(set(part.provenance.designators))


def test_the_committed_library_comes_from_the_sources_it_names():
    assert sorted(load_parts(LIBRARY).sources) == sorted(
        {source_label(p) for p in HARVEST_SOURCES}
    )


def test_the_committed_library_is_exactly_a_fresh_harvest():
    """The artifact must be reproducible from **sources + sidecar**.

    Everything is compared exactly — identity, parameters, provenance, notes,
    datasheet links — **except** what only the live library can settle. The
    committed shelf has been through a real `--verify` run (2026-09-16: 83 of
    85 names upgraded; 2026-09-17: all 92 spelled as the library spells them),
    so those are compared by `--check --verify` on the machine instead. The
    rule lives in one place (`harvest.BRIDGE_DECIDED_FIELDS` +
    `strip_bridge_decided`/`strip_bridge_decided_notes`), which is also what
    the checker uses — the shelf is verified, so it carries neither the
    bridge-decided *fields* nor the two library-level spelling tallies that
    `--verify` retires.

    The datasheet links are *not* in that exception: they come from the
    corrections sidecar, so an offline harvest reproduces them — which is the
    reason they are recorded there at all.
    """
    corrections = load_corrections(CORRECTIONS)
    fresh = harvest(HARVEST_SOURCES, corrections=corrections).library
    shelf = load_parts(LIBRARY)
    # The shelf is verified: `--verify` upgrades `footprint_name` and raises the
    # "spelling is kept" note, which is exactly what retires the two
    # library-level tallies. So the comparison is source-vs-shelf with the
    # bridge's mark set aside on the shelf side — and the shelf must show that
    # mark, or "set aside" would be hiding a missing verification (below).
    fresh_json = library_to_json(fresh)
    on_disk = library_to_json(shelf)
    for part in fresh_json["parts"]:
        part["provenance"]["designators"].sort()
    for part in on_disk["parts"]:
        part["provenance"]["designators"].sort()
    assert [p["key"] for p in fresh_json["parts"]] == [p["key"] for p in on_disk["parts"]]
    assert [strip_bridge_decided(p) for p in fresh_json["parts"]] == [
        strip_bridge_decided(p) for p in on_disk["parts"]
    ]
    assert strip_bridge_decided_notes(fresh_json["notes"]) == strip_bridge_decided_notes(
        on_disk["notes"]
    )
    # The exception is only legitimate while the shelf actually shows the
    # bridge's work: the spelling tally is gone *because* the entries were
    # verified, not because nothing was ever written.
    assert fresh.notes != strip_bridge_decided_notes(fresh.notes), (
        "the harvest no longer raises the spelling tallies, so setting them "
        "aside on the shelf side would hide a difference rather than explain one"
    )
    assert any(
        "spelling is kept" in note for p in shelf.parts for note in p.notes
    ), "the shelf records no verification, so `--verify` has not run"


def test_the_spelling_tallies_are_written_by_the_harvest_and_retired_by_verify():
    """A bridge run answers the spelling question, so its notes outlive it.

    Two directions, because both are load-bearing: the engine must still raise
    the tallies (a plain harvest has the evidence, so it must say so), and the
    shelf must not carry them (a verified entry's name came from the library,
    so the tally no longer describes anything). Without the second direction a
    "comparison" could pass by ignoring notes that were never written.
    """
    bare = harvest(HARVEST_SOURCES).library
    notes = " ".join(bare.notes)
    assert "spelled differently by different sources" in notes
    assert "stored as their only source" in notes
    # The tallies the harvest raises are the same function the engine calls, so
    # the numbers in the prose are counted the same way on both sides.
    assert spelling_notes(bare.parts) == [
        n for n in bare.notes if "footprint name(s)" in n
    ]

    shelf = load_parts(LIBRARY)
    assert not [n for n in shelf.notes if "spelled differently" in n]
    assert not [n for n in shelf.notes if "stored as their only source" in n]
    # ...and the two notes are the *only* thing the bridge retired at that level:
    # the datasheet note is not a bridge fact and must survive on both sides.
    assert any("datasheetPdfUrl" in n for n in shelf.notes)
    assert strip_bridge_decided_notes(shelf.notes) == shelf.notes


def test_the_datasheet_links_in_the_library_come_from_the_sidecar():
    """Without the sidecar an offline harvest cannot produce them — so the file
    is doing real work rather than decorating one."""
    library = load_parts(LIBRARY)
    corrections = load_corrections(CORRECTIONS)
    filled = [p for p in library.parts if p.datasheetPdfUrl]
    assert len(filled) == len(corrections.datasheets) > 0
    assert all(corrections.datasheet_for(p.lcsc) is not None for p in filled)
    bare = harvest(HARVEST_SOURCES).library
    assert not any(p.datasheetPdfUrl for p in bare.parts)
    # Whatever the network did not answer for is left empty, and stays empty.
    assert len(library.parts) - len(filled) == 3, (
        "the three links the service could not provide are still recorded as missing"
    )


def test_the_same_c_number_on_many_boards_becomes_one_entry():
    """The CH340N is on **all six** boards — the strongest claim in the shelf."""
    result = harvest(HARVEST_SOURCES)
    ch340 = next(p for p in result.library.parts if p.lcsc == "C2977777")
    boards = {d.partition("@")[2] for d in ch340.provenance.designators}
    assert boards == {
        "smart_pillbox", "thesis_FOC_board",
        "ProPrj_高速电机控制器_2026-09-16", "ProPrj_ROBOT ctrl FOC_2026-09-16",
        "ProPrj_智能药箱_2026-09-17", "ProPrj_毕设FOC驱动板_2026-09-17",
    }
    for label in ("blocklib/sources/smart_pillbox.eprj2",
                  "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"):
        assert label in ch340.provenance.source
    # Both a `.eprj2` and an `.epro2` source are recorded, so the history says
    # *how* each board was read.
    assert "eprj2" in ch340.provenance.source and "epro2" in ch340.provenance.source
    assert any(d.endswith("@smart_pillbox") for d in ch340.provenance.designators)
    # Two of the six boards were read twice in different formats (the pillbox and
    # the thesis board), so this one part also proves the merge keys on the C
    # number rather than on the file: the same board's two readings did not
    # become two entries.
    assert ch340.provenance.source.count(";") == len(HARVEST_SOURCES) - 1


def test_a_shared_place_does_not_swallow_the_entry_it_shares():
    """One part placed at six designators is one entry with six names."""
    result = harvest([PILLBOX, THESIS])
    switch = next(p for p in result.library.parts if p.lcsc == "C720477")
    assert "SW1@smart_pillbox" in switch.provenance.designators
    assert "SW1@thesis_FOC_board" in switch.provenance.designators
    assert len(switch.provenance.designators) == len(set(switch.provenance.designators))


def test_a_conflicting_field_is_recorded_not_averaged():
    first = PartEntry(
        key="res.5k1_0402", lcsc="C25905", mpn="A", deviceUuid="d1", libraryUuid="l",
        basic=True, params={"Resistance": "5.1kΩ"}, datasheetUrl="u",
        provenance=PartProvenance(kind="board-extract", source="a", designators=["R1@a"]),
    )
    second = PartEntry(
        key="res.5k1_0402", lcsc="C25905", mpn="B", deviceUuid="d1", libraryUuid="l",
        basic=False, params={"Resistance": "10kΩ", "Tolerance": "±1%"},
        provenance=PartProvenance(kind="board-extract", source="b", designators=["R2@b"]),
    )
    conflicts: list[str] = []
    _merge(first, second, conflicts)
    # the first board's value stands (deterministic), and the disagreement is named
    assert first.mpn == "A" and first.params["Resistance"] == "5.1kΩ"
    assert first.basic is True
    assert len(conflicts) == 3, conflicts
    assert any("mpn disagrees" in c for c in conflicts)
    assert any("'Resistance'" in c for c in conflicts)
    assert any("Part Class disagrees" in c for c in conflicts)
    # and a field the first entry lacked is filled in
    assert first.params["Tolerance"] == "±1%"
    assert set(first.provenance.designators) == {"R1@a", "R2@b"}


def test_an_ambiguous_key_is_suffixed_for_every_claimant():
    """Measured: two different 100nF 0805 capacitors share the value/footprint slug."""
    result = harvest([PILLBOX, THESIS])
    shared = [p for p in result.library.parts if p.key.startswith("cap.100n_0805")]
    assert len(shared) == 2
    assert all("." in p.key.split("cap.100n_0805")[1] for p in shared)
    assert {p.key for p in shared} == {"cap.100n_0805.c28233", "cap.100n_0805.c49678"}


def test_a_board_that_cannot_be_harvested_says_so():
    """An edit-log-only project contributes a reason, never an empty success."""
    entries, report = harvest_board(EDIT_LOG_ONLY)
    assert entries == []
    assert not report.ok
    assert "only an edit log" in report.skipped_reason
    result = harvest([PILLBOX, EDIT_LOG_ONLY])
    assert any("skip highspeed_motor_ctrl" in line for line in result.report)
    assert len(result.library.parts) == PILLBOX_ENTRIES


def _device_name_table(project) -> dict[tuple[str, str], str]:
    """What the live library would answer: device pair -> footprint name.

    Built from the project's own footprint documents, which is what the real
    chain resolves to (`lib.device.get` → `association.footprintUuid` →
    `lib.footprint.get` → name). Keyed by the **device** pair, because that is
    what the verifier is asked about.
    """
    table: dict[tuple[str, str], str] = {}
    for device in placed_devices(project).devices.values():
        document = project.library_docs.get(
            (device.attributes.get("Footprint") or "").strip()
        )
        if document is not None and device.library_doc_uuid and device.library_uuid:
            table[(device.library_doc_uuid, device.library_uuid)] = document.title
    return table


def test_the_bridge_verifier_is_the_only_thing_that_marks_a_name_verified():
    """`--verify` upgrades, corrects, or leaves it unverified — in that order."""
    # Without a verifier nothing is called verified.
    entries, _ = harvest_board(PILLBOX)
    assert all(e.footprint_name_verified is UNKNOWN for e in entries)

    # A bridge that answers with the *project's* name confirms it, silently.
    loaded = load_local_project(PILLBOX)
    table = _device_name_table(loaded)
    entries, _ = harvest_board(
        PILLBOX, verifier=lambda device_uuid, library_uuid: table.get(
            (device_uuid, library_uuid)
        )
    )
    assert all(e.footprint_name_verified is True for e in entries)
    assert not any(any("The library's spelling is kept" in n for n in e.notes) for e in entries)

    # A bridge that answers differently is authoritative about the *vocabulary*:
    # the library's spelling is adopted and the project's is recorded.
    entries, _ = harvest_board(PILLBOX, verifier=lambda _u, _l: "R0402")
    assert all(e.footprint_name == "R0402" for e in entries)
    assert all(e.footprint_name_verified is True for e in entries)
    assert any("The library's spelling is kept" in n for n in entries[0].notes)

    # A bridge that could not answer leaves the name unverified, with a note.
    entries, _ = harvest_board(PILLBOX, verifier=lambda _u, _l: None)
    assert all(e.footprint_name_verified is UNKNOWN for e in entries)
    assert all(any("unverified" in n for n in e.notes) for e in entries)


def test_parameters_keep_the_units_and_drop_the_identity():
    attributes = {
        "Supplier Part": "C431633",
        "Manufacturer Part": "STM32G431RBT6",
        "Manufacturer": "ST(意法半导体)",
        "Datasheet": "https://example.invalid",
        "Footprint": "uuid",
        "Symbol": "uuid",
        "3D Model": "uuid",
        "Add into BOM": "yes",
        "Designator": "U?",
        "Name": "={Manufacturer Part}",
        "Value": "100nF",
        "JLCPCB Part Class": "扩展库",
        "@Page Name": "P1",
        "CPU Maximum Speed": "170MHz",
        "Voltage - Supply": "1.71V~3.6V",
        "Applications": "-",
    }
    params = parameters_of(attributes)
    assert params == {
        "Applications": "-",
        "CPU Maximum Speed": "170MHz",
        "Voltage - Supply": "1.71V~3.6V",
    }
    # the units survive verbatim — no conversion, no normalisation
    assert params["CPU Maximum Speed"] == "170MHz"


@pytest.mark.parametrize(
    "klass,expected",
    [
        ("基础库", True),
        ("扩展库", False),
        # The third spelling: the imported catalog parts write JLC's own English.
        # Treating it as "no evidence" would be a false claim.
        ("Extended Part", False),
        ("extended part", False),
        ("", UNKNOWN),
        ("未知库", UNKNOWN),
    ],
)
def test_the_basic_flag_comes_from_evidence_in_any_spelling(klass, expected):
    flag, note = basic_flag({"JLCPCB Part Class": klass} if klass else {})
    assert flag is expected
    if klass == "未知库":
        # An unrecognised class is "no evidence", never a silent `False`.
        assert "unrecognised" in note


def test_a_real_entry_carries_the_library_vocabulary_footprint_name():
    """`R0805`, not `0805` — 006b's vocabulary rule, on real data.

    The physical 0402 resistor in this library is not placed on either board, so
    the check uses the 0805 part that is.
    """
    result = harvest([THESIS])
    part = next(p for p in result.library.parts if p.lcsc == "C2907329")
    assert part.footprint_name.lower() == "r0805"
    assert not part.footprint_name.isdigit()
    assert part.footprint_name_verified is None
    # The **human** label is a different vocabulary and does not become the
    # footprint name — 006b measured where conflating them leads.
    assert part.params.get("Supplier Footprint") == "0805"
    assert part.footprint_name != part.params.get("Supplier Footprint")


def test_the_milliohm_part_is_kept_apart_from_a_megaohm_reading():
    """The real 5mΩ shunt is the #202 shape: `m` vs `M` is nine decades."""
    result = harvest([THESIS])
    shunt = next(p for p in result.library.parts if p.lcsc == "C46634460")
    assert shunt.value == "5mΩ"
    assert str(shunt.resistance()) == "0.005"
    assert shunt.key == "res.5m_2512"


def test_a_case_only_disagreement_is_not_a_conflict():
    """Measured: a local project case-folds document titles, an export does not."""
    assert prefer_footprint_spelling("r0603", "R0603") == ("R0603", True)
    assert prefer_footprint_spelling("R0603", "r0603") == ("R0603", False)
    assert prefer_footprint_spelling("R0603", "R0603") == ("R0603", False)
    # A real difference is none of this function's business.
    assert prefer_footprint_spelling("R0603", "R0805") == ("R0603", False)


def test_the_library_says_which_names_came_from_one_source_only():
    """A name only one source spelled is left alone — and the fact is recorded.

    Two different signals, and they are easy to confuse:

    * ``case-preserving`` (per entry) means **two** sources disagreed about the
      case of the same name, so a choice was made and both spellings are on
      record. The spelling kept is whichever a source actually used.
    * the *library-level* tally names the entries where **one** source was the
      only evidence: nothing was upper-cased, because a rewrite with no second
      spelling to compare against has no evidence behind it.

    The shelf itself carries neither — ``--verify`` settled every name against
    the live library on 2026-09-17 (see
    `test_the_spelling_tallies_are_written_by_the_harvest_and_retired_by_verify`).
    What must hold without a bridge is the *behaviour*, so it is asserted on a
    harvest: both signals are raised, and the choice keeps a spelling somebody
    wrote rather than one we invented.
    """
    bare = harvest(HARVEST_SOURCES).library

    disagreed = [p for p in bare.parts if any("case-preserving" in n for n in p.notes)]
    assert disagreed, "the fixture set no longer exercises the case-folded path"
    for part in disagreed:
        assert part.footprint_name in part.notes[0] or part.footprint_name.lower() in (
            part.notes[0]
        ), "the kept spelling must be one a source actually wrote"
        # Both spellings are recorded, so the choice is auditable.
        assert part.footprint_name.lower() in part.notes[0].lower()

    one_source = [p for p in bare.parts if p.footprint_name == p.footprint_name.lower()]
    assert one_source, "nothing exercises the one-source-only path any more"
    assert not [p for p in one_source if any("case-preserving" in n for n in p.notes)], (
        "an entry with two spellings on record is not a one-source-only name"
    )
    assert any("are stored as their only source" in note for note in bare.notes)


def test_the_source_label_is_repo_relative_and_cwd_independent():
    assert source_label(PILLBOX) == "blocklib/sources/smart_pillbox.eprj2"
    assert source_label(ROBOT) == "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
    # Outside the repository there is no relative form to produce, so the path
    # is kept as-is rather than made up.
    assert source_label("/tmp/not-in-a-repo/x.eprj2").startswith("/tmp/")


def test_the_committed_library_never_writes_a_human_footprint_label():
    """006b's vocabulary rule: the library name (`R0402`), never `0402`."""
    library = load_parts(LIBRARY)
    for part in library.parts:
        assert not part.footprint_name.isdigit(), part.key
        assert part.footprint_name == part.footprint_name.strip()


def test_the_verifier_is_asked_about_the_device_never_about_a_project_uuid():
    """The measured chain starts at the device; a project uuid is not a key.

    The verifier records what it was handed, so this checks the *question*, not
    just the answer.
    """
    asked: list[tuple[str, str]] = []

    def verifier(device_uuid: str, library_uuid: str) -> str:
        asked.append((device_uuid, library_uuid))
        return ""

    harvest_board(PILLBOX, verifier=verifier)
    project = load_local_project(PILLBOX)
    project_footprint_uuids = {
        (d.attributes.get("Footprint") or "").strip()
        for d in placed_devices(project).devices.values()
    }
    assert asked, "the verifier was never consulted"
    for device_uuid, library_uuid in asked:
        assert device_uuid not in project_footprint_uuids, (
            "the verifier was handed a project-local footprint uuid, which cannot "
            "be resolved in the live library (006b, re-measured 2026-09-16)"
        )
        assert library_uuid == "0819f05c4eef4c71ace90d822a990e87"
    # The harvester asks once per entry it is about to write, and the pairs it
    # asks about are exactly the ones those entries carry. Collapsing them to one
    # call per device is the *tool's* job (`devices_to_verify`), covered in
    # `tests/test_harvest_verify.py`.
    result = harvest([PILLBOX])
    assert set(asked) == {(p.deviceUuid, p.libraryUuid) for p in result.library.parts}
    assert len(asked) <= len(project.placements)


def test_the_footprint_uuid_comes_from_the_device_dump_and_says_which_path():
    for item, expected in [
        ({"association": {"footprintUuid": "fp-1"}}, ("fp-1", "association.footprintUuid")),
        ({"association": {"footprint": {"uuid": "fp-2"}}}, ("fp-2", "association.footprint.uuid")),
        ({"association": {"footprint": "fp-3"}}, ("fp-3", "association.footprint")),
        ({"footprintUuid": "fp-4"}, ("fp-4", "footprintUuid")),
        ({"footprint": {"uuid": "fp-5"}}, ("fp-5", "footprint.uuid")),
        ({"association": {}}, ("", "")),
        ({"association": {"footprintUuid": "   "}}, ("", "")),
        ({}, ("", "")),
        (None, ("", "")),
        ("a string", ("", "")),
    ]:
        assert footprint_uuid_of_device(item) == expected, item
    # the measured chain is tried first
    assert FOOTPRINT_UUID_PATHS[0] == ("association", "footprintUuid")


def test_the_devices_to_verify_are_the_ones_the_harvest_would_write():
    """One rule for "which devices", shared by the harvest and the verifier."""
    wanted = devices_to_verify(HARVEST_SOURCES)
    result = harvest(HARVEST_SOURCES)
    entry_pairs = {(p.deviceUuid, p.libraryUuid) for p in result.library.parts}
    assert set(wanted) == entry_pairs
    assert all(label for label in wanted.values())
    # a board that cannot be read contributes nothing rather than failing the lot
    assert devices_to_verify([EDIT_LOG_ONLY]) == {}
    labels = set(devices_to_verify([PILLBOX]).values())
    assert any("CH340N" in label for label in labels)


def test_the_library_file_declares_its_kind(tmp_path):
    result = harvest([PILLBOX])
    assert library_to_json(result.library)["kind"] == PART_LIBRARY_KIND
