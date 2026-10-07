"""105 / B4b: the netlist's member key has to follow the placement the model keeps.

The defect (audit #57 finding 1, `.tmp_bug_report.md` "## 1."): the connectivity
pass keys every union-find node by ``(page, designator, pin, placement)`` — each
physical part gets its own cluster and its pins read the right net name — but the
reverse-built ``net.pins`` member is the **binary** key ``(designator, pin)``.
Two parts that answer to one designator therefore push the *same tuple* into
*different* nets:

    DCDC fixture, measured before this batch:
      ('100NF', '1') -> ['GND', 'NET1', 'VCC', 'VCCA']
      ('100NF', '2') -> ['+12V', 'GND', 'NET2']
      ('10UF',  '2') -> ['+5V', 'VCC']

One pin on four nets at once is not a state any layout can produce, and every
consumer of the netlist — rules, compare, the report's module clustering, the
architecture walk — was reading it.

The fix keeps the parser's own contract instead of inventing a placement-scoped
member key (``model.components.setdefault(designator, component)`` keeps the
**first** placement, 049: on the 毕设 board's U15/U16 the first copy's pins are
the ones the copper layer agrees with). Membership follows that placement: a
placement the model does not keep no longer claims a membership. The sheet's own
statement — two parts answer to one name — is not hidden by that: it is still
recorded in ``duplicate_designators`` / ``cross_page_designators`` and reported as
an ERROR. (The dropped copy's own ``Component`` object is the one the instances
pass already discarded, so its ``Pin.net`` readings were never reachable by a
consumer either.)

So the invariant this file pins is: **every ``(designator, pin)`` tuple sits on
exactly one net, and that net is the one the kept placement's own pin reads.**

The boards without a repeated designator are the zero-movement nail: the guard
never fires on them, so their reading is what it was — the digests below were
recorded on the pre-fix tree (`.tmp_105_before`, `outputs/105/probe_before.json`)
and must still hold.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.model import DesignModel
from boardwise.engines.review import run_review
from boardwise.parsers.schematic import build_project_model, build_schematic_model
from boardwise.rules.connectivity import DuplicateDesignators

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]
DCDC = FIXTURES / "DCDC-12V9V转5V3V3_2026-09-27.epro2"


# --------------------------------------------------------------------------
# the reading: who is on which net
# --------------------------------------------------------------------------


def _board(model: DesignModel, title: str = ""):
    boards = getattr(model, "boards", None) or [model]
    if not title:
        return boards[0]
    matches = [b for b in boards if getattr(b.board, "title", "") == title]
    assert matches, (title, [getattr(b.board, "title", "") for b in boards])
    return matches[0]


def _net_of_member(board, member: tuple[str, str]) -> list[str]:
    """Every net whose ``pins`` list carries that ``(designator, pin)`` tuple."""
    wanted = (str(member[0]), str(member[1]))
    return sorted(
        name
        for name, net in board.nets.items()
        if any((str(d), str(p)) == wanted for d, p in net.pins)
    )


def _multi_net_members(board) -> dict[tuple[str, str], list[str]]:
    where: dict[tuple[str, str], list[str]] = {}
    for name, net in board.nets.items():
        for designator, pin in net.pins:
            where.setdefault((designator, pin), []).append(name)
    return {member: sorted(names) for member, names in where.items() if len(names) > 1}


def _membership_digest(board) -> str:
    """One board's whole member reading, canonical: net -> sorted members.

    The net *keys* are part of the digest (a net that vanished would be a
    movement), the member *order* is not (the order a board lists its members in
    is the drawing's, and nothing in this batch promises it).
    """
    canonical = {
        name: sorted([str(designator), str(pin)] for designator, pin in net.pins)
        for name, net in board.nets.items()
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------
# 1. the DCDC fixture the audit measured
# --------------------------------------------------------------------------


def test_no_member_of_the_dcdc_fixture_sits_on_more_than_one_net():
    """The impossibility itself, on the board the audit measured."""
    board = _board(build_project_model(DCDC))
    assert _multi_net_members(board) == {}
    assert board.duplicate_designators == ["100NF", "10UF"], (
        "the two repeated names are still recorded — the fix moves membership, "
        "not the fact that the board renders two parts as one designator"
    )


def test_each_repeated_designator_pin_is_on_the_net_the_kept_placement_reads():
    """``(designator, pin)`` -> the net its own kept pin reads, and no other.

    The kept placement is the model's ``components[designator]`` (the first one
    in the document, 049), so the assertion is that the netlist and the pin
    reading agree — which is what a consumer that looks a member up in
    ``model.components`` (``_bridges_to_ground``, ``_has_grounded_cap``,
    checkup's clustering) silently assumed all along.
    """
    board = _board(build_project_model(DCDC))
    for designator, pin_number, expected in (
        ("100NF", "1", "GND"),
        ("100NF", "2", "+12V"),
        ("10UF", "2", "+5V"),
    ):
        own = {pin.number: pin.net for pin in board.components[designator].pins}
        assert own[pin_number] == expected, (designator, pin_number, own)
        assert _net_of_member(board, (designator, pin_number)) == [expected], (
            f"{designator} pin{pin_number} is on the nets the drawing put *any* "
            f"part of that name on, not on the one its kept placement reads"
        )


def test_the_phantom_members_are_gone_from_the_nets_they_were_welded_into():
    """The four nets the audit named, read member by member.

    ``('100NF','1')`` was welded into NET1/VCC/VCCA by three dropped copies,
    ``('100NF','2')`` into GND and ``('10UF','2')`` into VCC. What the kept
    placements' own nets keep is their own members: GND keeps the kept
    ``('100NF','1')``, +12V keeps ``('100NF','2')``, +5V keeps ``('10UF','2')``.
    This is the *declared* movement of this batch on this board: the net keys are
    all still there (a net that lost every member is not deleted — ``Pin.net``
    would then name a net the model does not carry).
    """
    board = _board(build_project_model(DCDC))
    assert sorted(board.nets) == [
        "+12V", "+5V", "GND", "NET1", "NET10", "NET2", "NET5", "NET6",
        "NET7", "NET8", "NET9", "VCC", "VCCA",
    ]
    assert _net_of_member(board, ("100NF", "2")) == ["+12V"]
    assert ("100NF", "1") not in board.nets["NET1"].pins
    assert ("100NF", "1") not in board.nets["VCC"].pins
    assert ("100NF", "1") not in board.nets["VCCA"].pins
    assert ("10UF", "2") not in board.nets["VCC"].pins
    assert ("100NF", "2") not in board.nets["GND"].pins
    # the kept placement's own neighbours are untouched
    assert ("U9", "1") in board.nets["NET1"].pins
    assert ("10UH", "2") in board.nets["VCC"].pins
    assert ("U10", "2") in board.nets["GND"].pins


def test_the_duplicate_designator_rule_still_fires_without_the_phantom_state():
    """CONN-1 is a metadata reader, so removing the impossible netlist state must
    not touch it: the rule's whole firing surface is the parser's two repeat
    lists (`duplicate_designators` / `cross_page_designators`)."""
    model = build_project_model(DCDC)
    rows = [
        (outcome.subject, outcome.state, severity)
        for outcome, severity in DuplicateDesignators()._rows(_board(model))
    ]
    assert rows == [("100NF", "VIOLATION", "ERROR"), ("10UF", "VIOLATION", "ERROR")]
    findings = [f for f in run_review(model) if f.rule_id == "conn-duplicate-designators"]
    assert [f.severity for f in findings] == ["ERROR", "ERROR"]
    assert all("kept the first placement" in f.message for f in findings)


# --------------------------------------------------------------------------
# 2. the two shapes, synthesised: twice on one page, once on each of two pages
# --------------------------------------------------------------------------


def _record(type_: str, body: dict | None = None, id_: str | None = None) -> str:
    envelope: dict = {"type": type_, "ticket": 1}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _symbol() -> list[str]:
    """A two-pin part drawn at the origin: pin 1 at (0,0), pin 2 at (20,0)."""
    out = [
        _record("DOCHEAD", {"docType": "SYMBOL", "uuid": "sym-r", "editVersion": "3.2.149"}),
        _record("META", {"title": "R", "docType": "SYMBOL"}, id_="meta-r"),
    ]
    for index, number in enumerate(("1", "2")):
        pin_id = f"sym-r-pin{number}"
        out.append(_record("PIN", {"x": float(index * 20), "y": 0.0, "zIndex": index + 2},
                           id_=pin_id))
        out.append(_record("ATTR", {"parentId": pin_id, "key": "Pin Number", "value": number},
                           id_=f"{pin_id}-n"))
    return out


def _page(uuid: str, parts: list[tuple[str, float, str]]) -> list[str]:
    """One ``SCH_PAGE``: each ``(designator, x, net name)`` gets its own wire.

    The wire spans the symbol's two pins (``x`` to ``x+20``) so that **both** are
    endpoints of it: the connectivity pass indexes a pin against a wire's ends,
    not against a point in the middle of a segment (test_063's shape)."""
    lines = [
        _record("DOCHEAD", {"docType": "SCH_PAGE", "uuid": uuid}),
        _record("CANVAS", {"originX": 0, "originY": 0, "unit": "0.01inch"},
                id_=f"canvas-{uuid}"),
    ]
    for index, (designator, x, net_name) in enumerate(parts):
        part = f"inst-{uuid}-{index}"
        lines.append(_record("COMPONENT", {"partId": part, "x": x, "y": -300.0,
                                           "rotation": 0, "isMirror": False, "zIndex": 10},
                             id_=f"c-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Designator",
                                      "value": designator}, id_=f"d-{part}"))
        lines.append(_record("ATTR", {"parentId": part, "key": "Symbol",
                                      "value": "sym-r"}, id_=f"s-{part}"))
        group = f"grp-{uuid}-{index}"
        lines.append(_record("WIRE", {"zIndex": 40}, id_=group))
        lines.append(_record("LINE", {"lineGroup": group, "startX": x, "startY": -300.0,
                                      "endX": x + 20.0, "endY": -300.0}))
        lines.append(_record("ATTR", {"parentId": group, "key": "NET", "value": net_name},
                             id_=f"net-{uuid}-{index}"))
    return lines


def _synthetic(tmp_path: Path, name: str, pages: list[list[str]]) -> Path:
    lines: list[str] = []
    for page in pages:
        lines += page
    lines += _symbol()
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("synth.epru", "\n".join(lines) + "\n")
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
    return path


def test_a_part_placed_twice_on_one_page_writes_one_member_per_pin(tmp_path):
    """Same page: two physical parts answer to ``R1`` inside one netlist.

    ``R1`` (first, on net ``NA``) and ``R1`` again (on net ``NB``) share the
    binary key, so before the fix ``('R1','1')`` was a member of **both** nets
    while only one of them can be the part the netlist describes.
    """
    path = _synthetic(tmp_path, "same_page.epro2", [
        _page("page-1", [("R1", 300.0, "NA"), ("R1", 700.0, "NB")]),
    ])
    board = _board(build_schematic_model(path))
    assert board.duplicate_designators == ["R1"]
    assert board.cross_page_designators == {}
    assert _multi_net_members(board) == {}
    assert _net_of_member(board, ("R1", "1")) == ["NA"]
    assert _net_of_member(board, ("R1", "2")) == ["NA"]
    assert "NB" in board.nets, "the second part's own net is still in the netlist"
    assert list(board.nets["NB"].pins) == []


def test_a_part_placed_once_on_each_of_two_pages_writes_one_member_per_pin(tmp_path):
    """Cross page, same board: one design drawn on two sheets (040b's second
    kind of repeat). Page-scoped connectivity puts the two copies on two
    clusters, and the same binary key was welded into both."""
    path = _synthetic(tmp_path, "cross_page.epro2", [
        _page("page-1", [("R1", 300.0, "NA")]),
        _page("page-2", [("R1", 700.0, "NB")]),
    ])
    board = _board(build_schematic_model(path))
    assert board.duplicate_designators == []
    assert board.cross_page_designators == {"R1": ["page-1", "page-2"]}
    assert _multi_net_members(board) == {}
    assert _net_of_member(board, ("R1", "1")) == ["NA"]
    assert list(board.nets["NB"].pins) == []


def test_a_page_that_places_two_parts_under_one_name_still_clashes(tmp_path):
    """The third shape — a real clash on one page — keeps its ERROR, and the
    netlist keeps exactly one member per pin either way."""
    path = _synthetic(tmp_path, "clash.epro2", [
        _page("page-1", [("R1", 300.0, "NA"), ("R1", 700.0, "NA")]),
    ])
    board = _board(build_schematic_model(path))
    assert board.duplicate_designators == ["R1"]
    assert _net_of_member(board, ("R1", "1")) == ["NA"], (
        "both copies are on NA, so the member is one entry — not a second one"
    )
    assert list(board.nets["NA"].pins).count(("R1", "1")) == 1
    rows = [
        (outcome.subject, severity)
        for outcome, severity in DuplicateDesignators()._rows(board)
    ]
    assert rows == [("R1", "ERROR")]


# --------------------------------------------------------------------------
# 3. the reading every board is held to
# --------------------------------------------------------------------------


def _fixture_files() -> list[Path]:
    return sorted(
        [p for p in (REPO / "tests" / "fixtures").glob("*.epro2")]
        + [p for p in (REPO / "tests" / "fixtures").glob("*.enet")]
        + [p for p in (REPO / "reviewsets").rglob("*.epro2")]
    )


def _loaded_boards():
    """``(file key, board title, board model)`` for every board the repository can
    parse — the 22 fixture/review-set files, which are 26 boards in total.

    22 files / 26 boards since 2026-10-07: 岳 supplied the **1.0.0 export** of the
    毕设FOC board (``ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2``), a project of
    its own with two boards under it — a different file from the 1.1.0 export,
    not a rename (its ``U6`` is the ``TPLP2981-30DBVR`` LDO where the 1.1.0
    one's is a 2x6 排针). This number is a **corpus** fact rather than a
    behavioural claim, so a fixture arriving moves it and the reason is recorded
    here instead of the number being loosened.
    """
    from boardwise.engines.review_eval import load_board_model

    for path in _fixture_files():
        key = path.relative_to(REPO).as_posix()
        model = load_board_model(str(path))
        for board in (getattr(model, "boards", None) or [model]):
            title = getattr(getattr(board, "board", None), "title", "") or "<no board>"
            yield key, title, board


def _repeats_within(board) -> bool:
    """Does a designator repeat **inside this board**?

    ``cross_board_designators`` is not part of this: it says another board
    numbers its own ``R1``, which is a fact about the project rather than a
    second placement in this netlist, so the guard this batch adds cannot fire
    because of it (`毕设FOC` Board2/Board3 and the 驱动板 are exactly that case,
    and they stay in the untouched set)."""
    return bool(board.duplicate_designators or board.cross_page_designators)


@pytest.mark.parametrize("path", _fixture_files(), ids=lambda p: p.name)
def test_no_netlist_carries_a_pin_on_two_nets(path):
    """The invariant, over every fixture in the repository — including the seven
    injected review sets and the ``.enet`` netlist. Five files repeat a
    designator (four fixtures plus the injected review set) and each of them was
    reading phantom members before this batch."""
    from boardwise.engines.review_eval import load_board_model

    model = load_board_model(str(path))
    for board in (getattr(model, "boards", None) or [model]):
        assert _multi_net_members(board) == {}, (
            f"{path.name}: {_multi_net_members(board)}"
        )


def test_every_member_agrees_with_the_kept_placements_own_pin_reading():
    """The general form of the fix, on every board: a member ``(designator, pin)``
    names a net that ``model.components[designator].pins[pin].net`` also names.

    A consumer that reads a member and then looks the designator up in
    ``model.components`` (``decap._bridges_to_ground``, ``CrystalLoadCaps.
    _has_grounded_cap``, checkup's module union) is only right if these two
    readings are the same net — before this batch they could be different nets
    on any board with a repeated name."""
    bad: list[str] = []
    seen = 0
    for key, title, board in _loaded_boards():
        seen += 1
        for name, net in board.nets.items():
            for designator, pin in net.pins:
                component = board.components.get(designator)
                own = (
                    {str(p.number): p.net for p in component.pins}
                    if component is not None
                    else None
                )
                if own is None or own.get(str(pin)) != name:
                    bad.append(f"{key} [{title}] {name}: {designator}.{pin} -> {own}")
    assert seen == 26, f"the fixture set changed: {seen} board(s)"
    assert bad == []


# --- BEGIN generated nail table (outputs/105/scratch/nail_table.py) ---------
# Recorded on the **pre-fix** tree (`.tmp_105_before`, `outputs/105/probe_before
# .json`). ``UNTOUCHED_BOARDS`` are the boards with no repeated designator at
# all: the guard this batch adds never fires on them, so their whole member
# reading (net -> sorted members) must be what it was. ``REPEATED_NET_KEYS`` are
# the boards that do repeat: their membership is expected to shrink (that is the
# fix), but the **net keys** may not — a net whose every member belonged to a
# dropped placement would otherwise vanish while ``Pin.net`` still named it.
UNTOUCHED_BOARDS = {
    "reviewsets/injected/fixed-base.epro2": {
        "Board1": "c9535d937a93806d16f96310c522f7feb1d59c617ee8118d3ad220c6f29345bf",
    },
    "reviewsets/injected/ldo-no-headroom.epro2": {
        "Board1": "2a73efe8eff128a1e29081b59390c2b901a076a93e3bdcd124b760c5d780ed66",
    },
    "reviewsets/injected/nc-pin-grounded.epro2": {
        "Board1": "4edfc6b9f57707cdf8800ac86ee3730970b34c93a23cd92199c781d38bb7a89d",
    },
    "reviewsets/injected/overvoltage-rail.epro2": {
        "Board1": "cc3090318c692154def6427850066de55daac4369ef36da170776cc2d23cd60d",
    },
    "reviewsets/injected/v3-decap-missing.epro2": {
        "Board1": "a908b1f4328cce7ff09b842db073c2b6b092ee1e6a94ff2613718d40bf165dc5",
    },
    "reviewsets/injected/value-mpn-mismatch.epro2": {
        "Board1": "c9535d937a93806d16f96310c522f7feb1d59c617ee8118d3ad220c6f29345bf",
    },
    "tests/fixtures/FPC触屏游戏机_2026-09-27.epro2": {
        "Board1": "675660f654cfdfc4ae74e1634774328a69c9355cbb56f2d0cbe91b3a3d643689",
    },
    "tests/fixtures/ProPrj_CH340G_2026-09-13.epro2": {
        "Board1": "ce3d9ddb6f7e861bf5cbe975b5225c0e6e8311a1ac27113b873dcdb5c7f3b0c0",
    },
    "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2": {
        "Board1": "ce1127476166e0cd61aa8f90b99d961e8dd3c4b9aa3362196e5a22e806b3cd93",
    },
    "tests/fixtures/ProPrj_智能药箱_2026-09-17.epro2": {
        "Board1": "051bcd2036c9d493a6fe61612e632356fbbb109d12d55e1e4dbfe4389b9fd542",
    },
    "tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2": {
        "Board2": "ed500df68cc3da383ebfb019076ac0484c1b00b3b7a154f51e01471240a25639",
        "Board3": "f15635e05341f3a5e36eb4449f7754e4214db85fc37c7a265f66ec4737dbf807",
    },
    "tests/fixtures/ProPrj_高速电机控制器_2026-09-16.epro2": {
        "驱动板": "33396cb2110c2af1feb2d5c2e2d782464243771119a488da4e5d95e1cb623f7b",
    },
    "tests/fixtures/board24v.enet": {
        "<no board>": "99dfd33f15832d729295e0986f9816ca759dc6307c0148b12648642f65e6c392",
    },
    "tests/fixtures/ch340_golden.epro2": {
        "Board1": "ce3d9ddb6f7e861bf5cbe975b5225c0e6e8311a1ac27113b873dcdb5c7f3b0c0",
    },
    "tests/fixtures/llc_board.epro2": {
        "Board1": "f55f930c9914cc2509fc08f61b558e786fa20a15fe85cdde8aed31778923220e",
    },
    "tests/fixtures/级联多电平-主拓扑_2026-09-27.epro2": {
        "Board1": "87ced66f9d40a9b8c22b6ecb4765afc67807a237e2d3876ebb862836f895f75b",
    },
    "tests/fixtures/级联多电平-驱动模块_2026-09-27.epro2": {
        "Board1": "2880432cbb82afd23c17fd61234ed32749c025b8a8505226ef16dae580b9f379",
    },
    "tests/fixtures/超声波_2026-09-27.epro2": {
        "Board1": "ca422bb6a0a387d0ad4d3e058cd97b87ad3be0f756a908d911ccd3bb1c35acd2",
    },
}

REPEATED_NET_KEYS = {
    "reviewsets/injected/duplicate-designator.epro2": {
        "Board1": ["+5V", "D+", "D-", "GND", "NET1", "NET18", "NET19", "NET2", "NET3", "NET4", "NET5", "RX", "TX", "VCC"],
    },
    "tests/fixtures/DCDC-12V9V转5V3V3_2026-09-27.epro2": {
        "Board1": ["+12V", "+5V", "GND", "NET1", "NET10", "NET2", "NET5", "NET6", "NET7", "NET8", "NET9", "VCC", "VCCA"],
    },
    "tests/fixtures/ProPrj_毕设FOC驱动板_2026-09-17.epro2": {
        "Board1": ["+24V", "+5V", "5VA", "AGND", "CAN_H", "CAN_L", "CAN_RX", "CAN_TX", "D+", "D-", "DRV_EN", "GHA", "GHB", "GHC", "GLA", "GLB", "GLC", "GND", "IA", "IA+", "IA-", "IB", "IB+", "IB-", "IC", "IC+", "IC-", "IIC1_SCL", "IIC1_SDA", "INHA", "INHB", "INHC", "INLA", "INLB", "INLC", "MISO", "MOSI", "NET1", "NET10", "NET11", "NET12", "NET13", "NET14", "NET15", "NET16", "NET17", "NET18", "NET19", "NET2", "NET22", "NET23", "NET24", "NET25", "NET26", "NET27", "NET28", "NET29", "NET3", "NET30", "NET31", "NET4", "NET5", "NET6", "NET7", "NET8", "NET87", "NET88", "NET89", "NET9", "NET90", "NET91", "NET92", "NET96", "NFAULT", "NRST", "NSCS", "OSC-IN", "OSC-OUT", "PGND", "RX", "SCK", "SHA", "SHB", "SHC", "SLA", "SLB", "SLC", "SPI3_MISO", "SPI3_MOSI", "SPI3_NSS", "SPI3_SCK", "SWCLK", "SWDIO", "TX", "VBUS", "VCC", "VCC/2", "VCCA", "VREF"],
    },
    "tests/fixtures/ProPrj_高速电机控制器_2026-09-16.epro2": {
        "控制板": ["+5V", "5VA", "AGND", "CAN_H", "CAN_L", "CAN_RX", "CAN_TX", "D+", "D-", "DRV_EN", "GND", "IA", "IA+", "IA-", "IB", "IB+", "IB-", "IC", "IC+", "IC-", "IIC1_SCL", "IIC1_SDA", "INHA", "INHB", "INHC", "INLA", "INLB", "INLC", "MISO", "MOSI", "MOTA", "MOTB", "MOTC", "NET1", "NET10", "NET105", "NET106", "NET107", "NET108", "NET109", "NET11", "NET110", "NET12", "NET13", "NET14", "NET15", "NET16", "NET19", "NET2", "NET20", "NET21", "NET22", "NET23", "NET24", "NET25", "NET26", "NET27", "NET28", "NET29", "NET3", "NET30", "NET31", "NET32", "NET33", "NET34", "NET4", "NET5", "NET6", "NET7", "NET8", "NET86", "NET87", "NET88", "NET89", "NET9", "NET90", "NET91", "NET92", "NET94", "NET95", "NFAULT", "NRST", "NSCS", "OSC-IN", "OSC-OUT", "PGND", "RX", "SCK", "SPI3_MISO", "SPI3_MOSI", "SPI3_NSS", "SPI3_SCK", "SWCLK", "SWDIO", "TX", "UA", "UB", "UBUS", "UC", "VCC", "VCC/2", "VCCA", "VM", "VREF"],
    },
    "tests/fixtures/毕设滤波采样_2026-09-27.epro2": {
        "Board1": ["1V65", "A5V", "AGND", "INNA", "INPA", "IN_A", "IN_B", "NET10", "NET11", "NET12", "NET13", "NET14", "NET15", "NET16", "NET17", "NET18", "NET19", "NET20", "NET21", "NET22", "NET23", "NET24", "NET25", "NET26", "NET27", "NET28", "NET29", "NET3", "NET30", "NET4", "NET5", "NET6", "NET7", "NET8", "NET9", "OUTNA", "OUTN_A", "OUTPA", "OUTP_A", "UAB+", "UAB-"],
    },
}
# --- END generated nail table ----------------------------------------------


def test_the_boards_without_a_repeated_designator_did_not_move_one_byte():
    """The zero-movement nail, board by board."""
    recorded = {
        (key, title) for key, titles in UNTOUCHED_BOARDS.items() for title in titles
    }
    checked = 0
    for key, title, board in _loaded_boards():
        if (key, title) in recorded:
            assert _membership_digest(board) == UNTOUCHED_BOARDS[key][title], (
                f"{key} [{title}]: a board with no repeated designator moved"
            )
            checked += 1
    assert checked == len(recorded) == 19, (
        f"the untouched set is {len(recorded)} boards, {checked} were checked"
    )


def test_a_repeated_boards_nets_are_all_still_there():
    """Membership shrinks; the netlist's *keys* do not.

    This is why the guard sits inside the member append instead of before
    ``nets.setdefault``: dropping the net as well would leave ``Pin.net``
    naming a net ``model.nets`` does not carry — a new inconsistency, and one
    every ``model.nets[name]`` consumer would trip over."""
    recorded = {
        (key, title) for key, titles in REPEATED_NET_KEYS.items() for title in titles
    }
    assert len(recorded) == 5, f"the repeated set is 5 boards, got {len(recorded)}"
    checked = 0
    for key, title, board in _loaded_boards():
        if (key, title) not in recorded:
            continue
        assert sorted(board.nets) == REPEATED_NET_KEYS[key][title], (
            f"{key} [{title}]: the net keys moved"
        )
        checked += 1
    assert checked == len(recorded)


def test_the_boards_the_audit_named_are_the_ones_that_repeat():
    """The declared movement, named: which boards repeat, and how many of them.

    The reading that moved is the member list; the rule verdicts are pinned by
    ``outputs/105/boards_reconcile.txt`` (all 21 files identical)."""
    facts = {}
    for key, title, board in _loaded_boards():
        if _repeats_within(board):
            facts.setdefault(Path(key).name, []).append(title)
    named = {
        "DCDC-12V9V转5V3V3_2026-09-27.epro2": ["Board1"],
        "ProPrj_高速电机控制器_2026-09-16.epro2": ["控制板"],
        "ProPrj_毕设FOC驱动板_2026-09-17.epro2": ["Board1"],
        "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2": ["Board1"],
        "毕设滤波采样_2026-09-27.epro2": ["Board1"],
        "duplicate-designator.epro2": ["Board1"],
    }
    assert facts == named, facts
