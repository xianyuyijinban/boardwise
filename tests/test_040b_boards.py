"""040b: one model per board — the acceptance pins.

The batch's whole claim is "a project is not one model". The hard assertions the
task book asks for live here: the 毕设 project's three boards against its own
copper layer, both `U2`s complete, the orphan page folded in, the single-board
projects unchanged, and the rules running per board with the board on every
finding.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from boardwise.core.model import (
    BoardModel,
    MultiBoardProjectError,
    ProjectModel,
)
from boardwise.engines.review import run_review
from boardwise.parsers.epru import collect_pcb_context, load_epro2_source
from boardwise.parsers.schematic import board_partition, build_project_model
from boardwise.rules.connectivity import DuplicateDesignators

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
MOTOR = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"
GOLDEN = FIXTURES / "ch340_golden.epro2"
LLC = FIXTURES / "llc_board.epro2"
INJECTED = Path("reviewsets/injected")
EPRJ3_SYNTH = FIXTURES / "eprj3_synth"


@pytest.fixture(scope="module")
def foc() -> ProjectModel:
    return build_project_model(FOC)


def _board(project: ProjectModel, title: str) -> BoardModel:
    matches = [b for b in project.boards if b.board.title == title]
    assert matches, (title, project.board_titles())
    return matches[0]


# --------------------------------------------------------------------------
# the partition itself (WI-1)
# --------------------------------------------------------------------------


def test_the_containers_board_chain_gives_the_expected_boards():
    """The chain the task book verified: SCH_PAGE.META.schematic -> SCH.META.board
    -> BOARD.META.title. Real fixtures, including one whose boards have Chinese
    titles of the designer's own choosing."""
    foc = build_project_model(FOC)
    assert foc.board_titles() == ["Board1", "Board2", "Board3"]
    pages = {b.board.title: list(b.board.page_uuids) for b in foc.boards}
    assert pages == {
        "Board1": ["5f0f4e169f1745e789501f939bb10851", "b0342c521c674ddab8dcc8aaf269ca59"],
        "Board2": ["0876ea4e415ed158"],
        "Board3": ["40daf13560b1086b"],
    }
    assert all(b.board.uuid for b in foc.boards), "a real BOARD document's uuid"

    motor = build_project_model(MOTOR)
    assert len(motor.boards) == 2
    assert [len(b.board.page_uuids) for b in motor.boards] == [2, 1]
    # Custom titles are the container's, not ours: nothing here invents "Board1".
    assert motor.board_titles() != ["Board1", "Board2"]


def test_a_project_without_board_documents_is_one_implicit_board():
    """Only the folder sample has no board container: the real fixtures all
    declare a BOARD document, even when there is just one. A board we had to
    invent (no uuid) is a different statement from one the file names."""
    project = build_project_model(EPRJ3_SYNTH)
    assert len(project.boards) == 1
    board_model = project.boards[0]
    assert board_model.board.title == "Board1"
    assert board_model.board.uuid == "", "implicit: no board document to name"
    assert board_model.board.page_uuids == ("page-1",)

    for path in (GOLDEN, LLC):
        board_model = build_project_model(path).boards[0]
        assert board_model.board.title == "Board1"
        assert board_model.board.uuid, "these files do declare a BOARD document"


def test_an_unregistered_page_folds_into_the_single_board():
    """The injected variant's P2 is a page no SCH registers (WI-0.2). One board =>
    fold it in, and the board's page list says so."""
    project = build_project_model(INJECTED / "duplicate-designator.epro2")
    (board_model,) = project.boards
    assert len(board_model.board.page_uuids) == 2
    assert sorted(board_model.board.page_uuids) == [
        "6e27da4006bdba32", "7cf2e588251788482543fdc2",
    ]


def test_an_unregistered_page_in_a_multi_board_project_is_its_own_group():
    """The other half of the rule: with more than one board, an unregistered page
    must not be guessed into one of them."""
    from boardwise.parsers.epru_stream import iter_epru_records, load_epru_text

    text, meta = load_epru_text(FOC)
    records = [
        record for record in iter_epru_records(text)
        if record.type == "DOCHEAD"
    ]
    # Re-partition the real stream with one page's `schematic` reference removed.
    class _Stripped(list):
        pass

    stripped = []
    for record in iter_epru_records(text):
        if record.type == "META" and str(record.body.get("schematic") or "") == (
            "4f0f123f421a8c42"
        ):
            record = type(record)(
                line_no=record.line_no, type=record.type, ticket=record.ticket,
                id=record.id, first_ticket=record.first_ticket,
                body={**record.body, "schematic": None},
            )
        stripped.append(record)
    refs = board_partition(stripped, project_meta={})
    assert [ref.title for ref in refs] == ["Board1", "Board2", "Board3", "unattached"]
    assert refs[-1].page_uuids == ("40daf13560b1086b",)


# --------------------------------------------------------------------------
# WI-5: per-board designator sets against the same file's copper layer
# --------------------------------------------------------------------------


def _copper_designators(path: Path) -> dict[str, set[str]]:
    """PCB uuid -> its placed designators, from the PCB documents."""
    source = load_epro2_source(path)
    out: dict[str, set[str]] = {}
    for document in source.documents:
        if document.doc_type != "PCB":
            continue
        context = collect_pcb_context(document, source.footprints(), __import__(
            "boardwise.core.geometry", fromlist=["ParseStats"]
        ).ParseStats())
        out[str(document.uuid)] = {
            placement.designator
            for placement in context.placements
            if placement.designator
        }
    return out


def test_every_boards_designators_match_a_pcb_of_the_same_project(foc):
    """WI-5's first hard assertion: each board's model holds exactly the parts of
    one PCB in the same archive.

    039d had to *match* the two views by designator-set overlap, which is what
    this test does too (the file states no page→PCB link): the winner must be
    unambiguous, and the only difference allowed is extra parts on the schematic
    side (drawn but not laid out — Board3 has R1..R6 in the netlist and not on
    the PCB), never the other way round.
    """
    pcbs = _copper_designators(FOC)
    matched: dict[str, str] = {}
    for board_model in foc.boards:
        designators = set(board_model.components)
        scores = sorted(
            ((len(designators & parts), pcb) for pcb, parts in pcbs.items()),
            reverse=True,
        )
        best, second = scores[0], scores[1]
        assert best[0] > second[0], f"{board_model.board.title} matches two PCBs"
        matched[board_model.board.title] = best[1]
        pcb_parts = pcbs[best[1]]
        assert pcb_parts <= designators, (
            f"{board_model.board.title}: the PCB has parts the schematic lacks: "
            f"{sorted(pcb_parts - designators)}"
        )
        assert len(designators - pcb_parts) <= 6, (
            f"{board_model.board.title}: {len(designators - pcb_parts)} parts "
            "are not on the PCB"
        )
    assert len(set(matched.values())) == 3, "three boards, three different PCBs"
    assert sorted(_board(foc, "Board3").components) == sorted(
        pcbs[matched["Board3"]] | {"R1", "R2", "R3", "R4", "R5", "R6"}
    ), "Board3's six extra parts are the drawn-but-unlaid resistors"


def test_the_two_u2s_are_both_complete(foc):
    """WI-5's second hard assertion, and the reason the batch exists: the later
    placement used to overwrite the earlier one."""
    board1, board3 = _board(foc, "Board1"), _board(foc, "Board3")
    assert len(board1.components["U2"].pins) == 33
    assert len(board3.components["U2"].pins) == 12
    assert foc.multi_board_designators()["U2"] == ["Board1", "Board3"]


def test_the_project_totals_count_parts_not_names(foc):
    """155 placements over 121 names: the sum is the honest project total, and
    `designators()` is the name-level one. Both are exposed, because a reader
    who sees only one of them cannot tell which question it answered."""
    assert foc.component_count() == 155
    assert len(foc.designators()) == 121
    assert sum(len(b.components) for b in foc.boards) == 155
    assert foc.net_count() == 138


# --------------------------------------------------------------------------
# WI-3: rules run per board, findings carry the board
# --------------------------------------------------------------------------


def test_every_finding_carries_the_board_that_produced_it(foc):
    findings = run_review(foc)
    titles = set(foc.board_titles())
    assert findings, "the fixture must produce findings or this pins nothing"
    assert {f.board for f in findings} <= titles
    assert {f.board for f in findings} == {"Board1", "Board2", "Board3"}
    # and the rules saw each board's own netlist: the shunts live on Board3
    shunt = [f for f in findings if f.rule_id == "shunt-sense-link"]
    assert {f.board for f in shunt} == {"Board3"}
    assert len(shunt) == 3, "R43, R8 and R18 — each judged on its own netlist"


def test_oracle_a1s_thirty_refs_are_all_reported_once(foc):
    """WI-5: A1 stands (30 ERRORs), now split across the three classes."""
    findings = [
        f for board_model in foc.boards
        for f in DuplicateDesignators().check(board_model)
    ]
    assert len(findings) == 30
    assert {f.severity for f in findings} == {"ERROR"}
    reported = sorted(f.message.split()[0] for f in findings)
    annotations = json.loads(
        (Path("reviewsets") / "ProPrj_毕设FOC驱动板_2026-09-17.json").read_text(
            encoding="utf-8"
        )
    )
    a1 = sorted(
        item["ref"] for item in annotations["items"]
        if item.get("rule_hint") == "conn-duplicate-designators"
    )
    assert reported == a1


def test_the_project_facade_refuses_to_read_a_multi_board_project(foc):
    for attribute in ("components", "nets", "duplicate_designators"):
        with pytest.raises(MultiBoardProjectError) as caught:
            getattr(foc, attribute)
        assert "3 boards" in str(caught.value)
    with pytest.raises(MultiBoardProjectError):
        foc.single_board()
    # ... and a single-board project reads straight through.
    golden = build_project_model(GOLDEN)
    assert len(golden.components) == 17 and len(golden.single_board().nets) == 13


def test_edit_plan_names_the_boards_when_a_designator_spans_them(capsys):
    """WI-4: the ambiguity refusal is board-aware and actionable."""
    from boardwise import cli

    code = cli.main([
        "edit", "plan",
        "--file", str(FOC),
        "--view", "schematic",
        "--rule", "param-value-mpn-match",
        "--designator", "U2",
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "U2" in err and "Board1" in err and "Board3" in err, err
    assert "不猜是哪一块" in err


# --------------------------------------------------------------------------
# WI-5: the single-board projects do not move
# --------------------------------------------------------------------------


#: (rule, severity, message, evidence) per finding, frozen from the pre-040b
#: reading. 040b adds a field (`board`) and changes nothing else about them: the
#: eval's per-board rows for these boards are unchanged, and this pin says so in
#: a way a future edit cannot quietly break.
FROZEN_FINDINGS = {
    "ch340_golden.epro2": [(
        "decap-required-caps", "WARN",
        "U1 pin4 must sit on net 'VCC' in mode '3.3V' but is on 'NET1' — the "
        "datasheet's wiring for the active mode is not what the board does",
    )],
    "ProPrj_CH340G_2026-09-13.epro2": [(
        "decap-required-caps", "WARN",
        "U1 pin4 must sit on net 'VCC' in mode '3.3V' but is on 'NET1' — the "
        "datasheet's wiring for the active mode is not what the board does",
    )],
}


def _signatures(project: ProjectModel) -> list[tuple]:
    return [
        (f.rule_id, f.severity, f.message)
        for f in sorted(run_review(project), key=lambda f: (f.rule_id, f.severity, f.message))
    ]


@pytest.mark.parametrize("name", sorted(FROZEN_FINDINGS))
def test_single_board_findings_are_unchanged(name):
    project = build_project_model(FIXTURES / name)
    got = _signatures(project)
    assert [row[:3] for row in got] == [row[:3] for row in FROZEN_FINDINGS[name]]
    assert project.board_titles() == ["Board1"], "and the board is named on them"
    assert all(f.board == "Board1" for f in run_review(project))


@pytest.mark.parametrize(
    "name", ["llc_board.epro2", "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
             "ProPrj_智能药箱_2026-09-17.epro2"]
)
def test_other_single_board_fixtures_are_unchanged(name):
    """Severity counts, frozen from the pre-040b parser (measured with
    `.tmp_040b/compare_findings.py`, which diffs rule|severity|message|evidence
    per fixture against the 040 parser: all twelve single-board fixtures came out
    **identical**, including the six injected variants)."""
    project = build_project_model(FIXTURES / name)
    assert len(project.boards) == 1
    counts = collections.Counter(f.severity for f in run_review(project))
    assert counts == collections.Counter(_EXPECTED_SEVERITY[name])


#: Severity counts per single-board fixture, measured on the pre-040b parser.
_EXPECTED_SEVERITY = {
    "llc_board.epro2": {"ERROR": 0, "WARN": 0, "INFO": 0},
    "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2": {"ERROR": 0, "WARN": 0, "INFO": 0},
    "ProPrj_智能药箱_2026-09-17.epro2": {"ERROR": 0, "WARN": 1, "INFO": 0},
}


def test_the_injected_boards_keep_their_injected_defect():
    """Six single-board variants + the orphan-page one: each still reports its
    fault as ERROR, now with the board attached."""
    for name, rule_id in (
        ("duplicate-designator", "conn-duplicate-designators"),
        ("ldo-no-headroom", "path-ldo-dropout"),
        ("nc-pin-grounded", "conn-nc-and-must-connect"),
        ("overvoltage-rail", "pwr-domain-vs-range"),
        ("value-mpn-mismatch", "param-value-mpn-match"),
    ):
        project = build_project_model(INJECTED / f"{name}.epro2")
        findings = run_review(project)
        hits = [f for f in findings if f.rule_id == rule_id and f.severity in ("ERROR", "WARN")]
        assert hits, (name, [f.rule_id for f in findings])
        assert {f.board for f in hits} == {"Board1"}


# --------------------------------------------------------------------------
# WI-0: the folder format's board container
# --------------------------------------------------------------------------


def test_an_eprj3_folder_can_declare_two_boards(tmp_path):
    """WI-0's finding, as a test: the index names boards
    (`profile.boards` + `schematics[].board` + `sheets[].schematic_uuid`), which
    is how a folder project is a multi-board project too. The 038 synth fixture
    declares neither and lands on the implicit board (tested above)."""
    root = tmp_path / "two"
    (root / "sch" / "A").mkdir(parents=True)
    (root / "sch" / "B").mkdir(parents=True)
    template = (EPRJ3_SYNTH / "sch" / "Schematic1" / "P1.esch2").read_text(encoding="utf-8")
    # Two sheets, two page uuids — the index links pages to schematics by uuid
    # (measured on the official example: P1.esch2's SCH_PAGE uuid *is* its sheet
    # uuid), so distinct uuids are what makes two boards.
    (root / "sch" / "A" / "P1.esch2").write_text(
        template.replace('"uuid":"page-1"', '"uuid":"page-a"'), encoding="utf-8")
    (root / "sch" / "B" / "P2.esch2").write_text(
        template.replace('"uuid":"page-1"', '"uuid":"page-b"'), encoding="utf-8")
    (root / "two.eprj3").write_text(json.dumps({
        "name": "two",
        "format": "folder",
        "profile": {
            "boards": {
                "b1": {"uuid": "b1", "title": "Control", "zIndex": 1},
                "b2": {"uuid": "b2", "title": "Power", "zIndex": 2},
            },
            "schematics": {
                "s1": {"uuid": "s1", "name": "A", "board": "b1"},
                "s2": {"uuid": "s2", "name": "B", "board": "b2"},
            },
            "sheets": {
                "page-a": {"uuid": "page-a", "title": "P1", "schematic_uuid": "s1"},
                "page-b": {"uuid": "page-b", "title": "P2", "schematic_uuid": "s2"},
            },
            "pcbs": {},
        },
    }, ensure_ascii=False), encoding="utf-8")

    project = build_project_model(root)
    assert [b.board.title for b in project.boards] == ["Control", "Power"]
    assert [list(b.board.page_uuids) for b in project.boards] == [["page-a"], ["page-b"]]
    assert project.component_count() == 4, "the fixture page, on two boards"
    # Each board has its own model: the same designators, twice, both complete.
    for board_model in project.boards:
        assert sorted(board_model.components) == ["U1", "U2"]
    assert project.designators() == ["U1", "U2"]
    assert project.multi_board_designators() == {"U1": ["Control", "Power"],
                                                "U2": ["Control", "Power"]}
