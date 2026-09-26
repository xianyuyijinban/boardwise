"""040: page-scoped connectivity (F1/F2/F3) and the two kinds of repeat.

The absolute pins of task 040 §WI-4, plus the measurements that make F3 safe.
Everything here is a *reading of a committed fixture*: the multi-board files are
read-only exports of real projects, and the values were cross-checked against the
same files' own copper layer (`PAD_NET`) — see `outputs/040_summary.txt` for the
agreement counts (schematic agree 501 -> 588 of the named pads that both views
can name, disagrees 172 -> 85).

Why these pins and not a count: a count says "something moved", a pin says what
the model now says, and the values below are the ones the engineer's board and
the copper layer agree on.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from boardwise.core.model import DesignModel
from boardwise.parsers.epru_stream import iter_epru_records, load_epru_text
from boardwise.parsers.schematic import (
    _wire_head_groups,
    build_project_model,
    build_schematic_model,
    collect_page_layout,
)
from boardwise.rules.connectivity import DuplicateDesignators

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
MOTOR = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"


def _pins(model, designator: str) -> dict[str, str | None]:
    return {pin.number: pin.net for pin in model.components[designator].pins}


def _board(project, title: str):
    """One board's model by title — the 040b reading of "the model with X on it"."""
    matches = [b for b in project.boards if b.board.title == title]
    assert matches, (title, project.board_titles())
    return matches[0]


@pytest.fixture(scope="module")
def foc():
    """The 毕设 project: three boards (040b). Its refs live on specific boards."""
    return build_project_model(FOC)


@pytest.fixture(scope="module")
def motor():
    return build_project_model(MOTOR)


# --------------------------------------------------------------------------
# the two anomalies this task exists for
# --------------------------------------------------------------------------


def test_c115_bridges_the_24v_rail_and_the_return_net(foc):
    """The engineer's report: C115 (330uF) sits between +24V and the return.

    Before 040 the model said both pins were on AGND — the weld of three pages
    (F1) plus a symbol graphic that shorted the capacitor bank's two rails
    (F3). `tests/fixtures/ProPrj_毕设FOC驱动板_*.epro2`'s PCB3 says the same as
    this assertion: {'1': '+24V', '2': 'PGND'}, and C115 is on Board3.
    """
    assert _pins(_board(foc, "Board3"), "C115") == {"1": "+24V", "2": "PGND"}


def test_the_whole_330uF_bank_still_reads_two_nets(foc):
    """The bank's other electrolytics, on the boards that carry them, and the
    same copper layer agreeing each time."""
    board1, board3 = _board(foc, "Board1"), _board(foc, "Board3")
    assert _pins(board3, "C116") == {"1": "+24V", "2": "PGND"}
    # Board1's own 24V input stage, same shape, same reading.
    assert _pins(board1, "C17") == {"1": "+24V", "2": "PGND"}
    assert _pins(board3, "D2") == {"1": "PGND", "2": "+24V"}
    # CN3 is the 24V input connector. Pins 3/4 are marked NO_CONNECT in the file
    # (a 2-pole XT30 with four footprint pads), so the model reads them as
    # unconnected — which it did before 040 too, and which the copper agrees
    # with ({1: PGND, 2: +24V, 3: None, 4: None}). 039d's probe printed NET8 for
    # pin 3 because it reported the cluster of an NC pin; the model has never
    # given an NC pin a net.
    assert _pins(board3, "CN3") == {"1": "PGND", "2": "+24V", "3": None, "4": None}
    # The MOTC-sense RC caps are Board1's; their net is unnamed in the drawing
    # (the copper calls it $1N66627), which is why the model auto-names it.
    assert _pins(board1, "C40") == {"1": "AGND", "2": "NET13"}


def test_u5_is_the_ch340n_of_the_other_three_boards(foc):
    """pin 5 -> VCC, not AGND; and the pin that is really grounded is 3."""
    board1 = _board(foc, "Board1")
    assert _pins(board1, "U5") == {
        "1": "D+", "2": "D-", "3": "GND", "4": None,
        "5": "VCC", "6": "RX", "7": "TX", "8": "VCC",
    }
    # PCB1 of the same archive (U5's board) says {5: VCC, 8: VCC, 3: GND,
    # 4: None}; so does the schematic's own symbol (Pin Name VCC on pin 5).
    assert "U5" not in board1.repeated_designators()


def test_the_header_brackets_no_longer_short_u2s_columns(foc):
    """U2 on page 40daf is a 2x6 header whose symbol draws a bracket over each
    column's three pins. The bracket is decoration: the file gives each of those
    pins its own stub wire with its own NET label (IC-, IC+, SLC / GLC, SHC,
    GHC), and PCB3 confirms six *different* nets. F3 keeps them apart.

    040b makes this a direct assertion: the board carrying that header is its own
    model now, so `Board3.components["U2"]` **is** the 2x6 header. (Before 040b a
    project-wide dict let the *other* U2 — the 28-pin part on Board1 — overwrite
    it, and the assertion had to go through net membership.)
    """
    board3 = _board(foc, "Board3")
    u2 = board3.components["U2"]
    assert len(u2.pins) == 12, "the 2x6 header, complete"
    by_net = {pin.number: pin.net for pin in u2.pins}
    assert by_net == {
        "1": "PGND", "2": "IC-", "3": "PGND", "4": "IC+", "5": "PGND", "6": "SLC",
        "7": "+24V", "8": "GLC", "9": "+24V", "10": "SHC", "11": "+24V", "12": "GHC",
    }
    # No net holds two of the three bracket-mates any more.
    for triple in (("2", "4", "6"), ("8", "10", "12")):
        members = {("U2", number) for number in triple}
        for name, net in board3.nets.items():
            shared = members & set(net.pins)
            assert len(shared) <= 1, (name, sorted(shared))


def test_both_u2s_survive_as_complete_parts(foc):
    """The worked example for 040b §WI-2: the 毕设 project places two different
    parts under one name, on two boards. Both are now whole — 12 pins on Board3,
    33 on Board1 — instead of the later one silently overwriting the earlier.
    """
    board1, board3 = _board(foc, "Board1"), _board(foc, "Board3")
    assert (len(board1.components["U2"].pins), len(board3.components["U2"].pins)) == (
        33, 12,
    )
    assert board1.components["U2"].footprint != board3.components["U2"].footprint, (
        "two different parts, which is why one name cannot hold both"
    )
    assert foc.multi_board_designators()["U2"] == ["Board1", "Board3"]


# --------------------------------------------------------------------------
# F3's judge, and why it is safe
# --------------------------------------------------------------------------


def _schematic_records(path):
    text, _meta = load_epru_text(path)
    return list(iter_epru_records(text))


@pytest.mark.parametrize("path", [FOC, MOTOR, FIXTURES / "ch340_golden.epro2",
                                  FIXTURES / "llc_board.epro2"])
def test_every_net_label_sits_on_a_wire_group(path):
    """The measurement F3 turns on: a group is a wire when a WIRE record names
    it, and **every** NET label is parented to such a group — 0 exceptions on
    every fixture. A label parented to a non-wire group would mean the judge
    throws away a named connection.
    """
    records = _schematic_records(path)
    wires = _wire_head_groups(records)
    labels = [
        str((record.body or {}).get("parentId") or "")
        for record in records
        if record.type == "ATTR" and (record.body or {}).get("key") == "NET"
    ]
    assert labels, "fixture has no NET labels; the check would be vacuous"
    stray = sorted({label for label in labels if label and label not in wires})
    assert stray == []


def test_a_wire_group_belongs_to_exactly_one_page():
    """`_PageSplit.pages` maps a group to its page; that is only meaningful
    while a group id (a uuid) is not reused across pages of one archive."""
    for path in (FOC, MOTOR):
        records = _schematic_records(path)
        page = ""
        seen: dict[str, set[str]] = {}
        for record in records:
            if record.type == "DOCHEAD":
                page = (
                    str(record.body.get("uuid") or "")
                    if record.body.get("docType") == "SCH_PAGE"
                    else ""
                )
                continue
            if record.type == "LINE" and record.body:
                group = str(record.body.get("lineGroup") or "")
                if group:
                    seen.setdefault(group, set()).add(page)
        assert [group for group, pages in seen.items() if len(pages) > 1] == []


def test_pages_are_not_welded(foc, motor):
    """F1: no pin's net can leave its own page. The pre-040 model had a single
    141-pin cluster spanning three pages on the 毕设 project; the fix shows up as
    a *net count that goes up* (85 -> 112 per board, 113 -> 121) and as nets
    whose members all come from one page.

    040b: the counts are per board now, and the per-board numbers are what the
    040 measurement of the same fix was reading through a project-wide dict.
    """
    board3 = _board(foc, "Board3")
    assert [len(b.nets) for b in foc.boards] == [90, 13, 35]
    # The 高速电机控制器 project: two boards with the designer's own titles
    # (板名自定义 — the board *is* the unit, not a board numbered by us).
    assert [len(b.nets) for b in motor.boards] == [94, 50]
    assert motor.board_titles() != ["Board1", "Board2"]
    # The old weld's signature: one net with 100+ members. None is left.
    for board_model in (*foc.boards, *motor.boards):
        assert max(len(net.pins) for net in board_model.nets.values()) < 100
    # +24V and PGND are the bank's rails, and they no longer share a net.
    assert ("C115", "1") in board3.nets["+24V"].pins
    assert ("C115", "1") not in board3.nets["PGND"].pins


def test_the_drawings_still_carry_the_hazard_the_model_now_ignores(motor, foc):
    """What the drawings contain, counted: non-wire groups whose own segment runs
    from one wire group's endpoint to another's — the shape that shorts two nets.

    039d measured 2 on the 毕设 board (the C115 bank's 46-unit vertical on page
    40daf, plus one on page 5f0f) and 4 on the 高速电机控制器 board; the counts
    are unchanged, because the *files* are unchanged and F3 does not edit the
    drawing, it stops calling these groups wires. The model's immunity is
    asserted by the pins above (C115 = +24V/PGND, U2's triples apart) and by the
    two boards' net counts.
    """
    for path, expected in ((FOC, 2), (MOTOR, 4)):
        assert len(_graphic_bridges(path)) == expected, path


def _graphic_bridges(path) -> list[tuple[str, str, tuple, tuple]]:
    """Non-wire segments that join two *different* wire groups' endpoints."""
    records = _schematic_records(path)
    wires = _wire_head_groups(records)
    page = ""
    segments: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {}
    page_of: dict[str, str] = {}
    for record in records:
        if record.type == "DOCHEAD":
            page = (
                str(record.body.get("uuid") or "")
                if record.body.get("docType") == "SCH_PAGE"
                else ""
            )
            continue
        if record.type != "LINE" or not record.body:
            continue
        group = str(record.body.get("lineGroup") or "")
        if not group:
            continue
        segment = (
            (round(float(record.body.get("startX") or 0), 6),
             round(-float(record.body.get("startY") or 0), 6)),
            (round(float(record.body.get("endX") or 0), 6),
             round(-float(record.body.get("endY") or 0), 6)),
        )
        segments.setdefault(group, []).append(segment)
        page_of.setdefault(group, page)
    endpoint_wires: dict[tuple[str, tuple[float, float]], set[str]] = {}
    for group in wires:
        for start, end in segments.get(group, ()):
            for point in (start, end):
                endpoint_wires.setdefault((page_of[group], point), set()).add(group)
    bridges = []
    for group, own in segments.items():
        if group in wires:
            continue
        for start, end in own:
            left = endpoint_wires.get((page_of[group], start), set())
            right = endpoint_wires.get((page_of[group], end), set())
            if not left:
                continue
            for other in right:
                if other not in left:  # one end on wire A, the other on wire B
                    bridges.append((group, page_of[group], start, end))
    return bridges


# --------------------------------------------------------------------------
# the repeat semantics (WI-3): the model tells the two kinds apart
# --------------------------------------------------------------------------


def test_the_model_separates_the_three_kinds_of_repeat(foc, motor):
    """One name, three readings — and 040b is what made the third one visible.

    Board1: U15/U16 twice on page 5f0f (same page, same netlist).
    Board3: 28 names that are also on another board (cross-board).
    Neither board repeats a name across *its own* pages on the 毕设 project; the
    高速电机控制器 project does (below), which is why the middle class has a test.
    """
    board1, board3 = _board(foc, "Board1"), _board(foc, "Board3")
    assert board1.duplicate_designators == ["U15", "U16"]
    assert board1.cross_page_designators == {}
    assert len(board3.cross_board_designators) == 28
    assert board3.cross_board_designators["C1"] == ["Board1", "Board2", "Board3"]
    assert foc.multi_board_designators()["C1"] == ["Board1", "Board2", "Board3"]
    # the union of the three classes is the 30 refs oracle A1 ruled on
    assert len(foc.repeated_designators()) == 30
    assert "U15" in foc.repeated_designators() and "U16" in foc.repeated_designators()
    # 高速电机控制器: same-page repeats again, and 12 cross-board names. Neither
    # real multi-board fixture repeats a name across *its own* pages (their
    # second pages are the empty ones), which is why the middle class is tested
    # on a synthetic model — it is a pure function of the fields, and the fixture
    # set cannot produce it.
    same_page = {name for b in motor.boards for name in b.duplicate_designators}
    assert same_page == {"U15", "U16", "U17", "U20"}
    assert len(motor.multi_board_designators()) == 12
    for board_model in (*foc.boards, *motor.boards):
        assert board_model.cross_page_designators == {}


def test_the_middle_class_names_the_pages_of_one_board():
    """A name on two pages of one board is one netlist's clash (040 §WI-3), and
    since 040b its message says so instead of blaming another board."""
    from boardwise.core.model import BoardModel, BoardRef

    board = BoardModel(board=BoardRef(uuid="b", title="Board1"))
    board.cross_page_designators = {"R1": ["pageA", "pageB"]}
    (finding,) = DuplicateDesignators().check(board)
    assert finding.severity == "ERROR"
    assert "pages of one board" in finding.message
    assert "pageA" in finding.message and "pageB" in finding.message
    assert "Board1" not in finding.message, "the board is the finding's own field"


def test_single_page_boards_have_neither_kind():
    for name in ("ch340_golden.epro2", "llc_board.epro2",
                 "ProPrj_CH340G_2026-09-13.epro2",
                 "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"):
        model = build_schematic_model(FIXTURES / name)
        assert model.duplicate_designators == [], name
        assert model.cross_page_designators == {}, name


def test_the_rule_reports_all_three_kinds_and_names_the_subject(foc):
    """Three classes, all ERROR (oracle A1, unchanged), and the message says which
    class it is: same page, another page of the same board, or another board."""
    findings = []
    for board_model in foc.boards:
        findings.extend(DuplicateDesignators().check(board_model))
    same_page = [f for f in findings if "more than one placed part on one page" in f.message]
    cross_board = [f for f in findings if "more than one board" in f.message]
    assert sorted(f.message.split()[0] for f in same_page) == ["U15", "U16"]
    assert "C1 is placed on more than one board (Board1、Board2、Board3)" == (
        cross_board[0].message.split(";")[0]
    ), cross_board[0].message
    assert len(cross_board) == 28, "one report per name, not one per board"
    assert {f.severity for f in findings} == {"ERROR"}
    assert len(findings) == len(foc.repeated_designators()) == 30


def test_an_injected_same_board_repeat_is_still_a_violation():
    """The injected `duplicate-designator` variant appends a *second page* to a
    one-board project (011d: "a second page carries a second R24"). 040b folds an
    unregistered page into the project's single board, so the repeat is the
    middle class — one netlist, two pages — and the rule still reports ERROR,
    which the variant's signed record demands."""
    project = build_project_model(
        Path("reviewsets/injected/duplicate-designator.epro2")
    )
    (board_model,) = project.boards
    assert board_model.board.title == "Board1"
    assert len(board_model.board.page_uuids) == 2, (
        "the orphan page is Board1's second page (040b §WI-0.2)"
    )
    assert board_model.duplicate_designators == []
    assert board_model.cross_page_designators == {"R24": ["6e27da4006bdba32", "7cf2e588251788482543fdc2"]}
    (finding,) = DuplicateDesignators().check(board_model)
    assert finding.severity == "ERROR" and "R24" in finding.message


# --------------------------------------------------------------------------
# the boards 040 may not move (WI-4): golden x3, byte for byte
# --------------------------------------------------------------------------


def _signature(path) -> dict:
    """Canonical reading of a board: components, every pin's net, every net's
    members — sorted, hashed. Ordered structures are collapsed to sorted lists
    so the hash speaks about the reading, not about dictionary order."""
    model = build_schematic_model(path)
    payload = {
        "components": sorted(model.components),
        "pins": sorted(
            f"{designator}.{pin.number}={pin.net or ''}"
            for designator, comp in model.components.items()
            for pin in comp.pins
        ),
        "nets": sorted(
            f"{name}: " + ",".join(sorted(f"{d}.{n}" for d, n in net.pins))
            for name, net in model.nets.items()
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "sha256": hashlib.sha256(blob).hexdigest(),
        "components": len(model.components),
        "nets": len(model.nets),
        "pins": sum(len(c.pins) for c in model.components.values()),
    }


#: The three single-page boards whose reading 040 must not touch. The hash is
#: the assertion; the counts are there so a failure says *what* moved. Re-derive
#: with `.tmp_040/signatures.py` (kept with the batch) and paste.
FROZEN_SIGNATURES = {
    "ch340_golden.epro2": (
        "1d3c8953046ae5e5416b98e5ea5f576ae17fed106586ed74350eee11c5319caf", 17, 13, 66),
    "ProPrj_CH340G_2026-09-13.epro2": (
        "1d3c8953046ae5e5416b98e5ea5f576ae17fed106586ed74350eee11c5319caf", 17, 13, 66),
    "llc_board.epro2": (
        "b5a73eae4ab28c9794e092ce068be3b446fbcd8048e83ff40760caf8e569fb69", 47, 40, 111),
}


@pytest.mark.parametrize("name", sorted(FROZEN_SIGNATURES))
def test_the_single_page_boards_are_byte_for_byte_unchanged(name):
    digest, components, nets, pins = FROZEN_SIGNATURES[name]
    signature = _signature(FIXTURES / name)
    assert (
        signature["sha256"], signature["components"], signature["nets"], signature["pins"]
    ) == (digest, components, nets, pins)


def test_the_replay_layout_still_reads_the_same_drawing():
    """`collect_page_layout` feeds the replay generator (006b). 040 changed which
    groups count as wires for *connectivity*; the layout must not move (measured
    against the pre-040 parser with `.tmp_040/compare_head.py`: 17 parts, 17
    flags, 45 polyline runs over 33 groups, no notes — identical)."""
    layout = collect_page_layout(FIXTURES / "ch340_golden.epro2")
    assert (len(layout.parts), len(layout.flags), len(layout.wires), layout.notes) == (
        17, 17, 45, [])
    assert len({wire.group for wire in layout.wires}) == 33  # branched runs share a group
