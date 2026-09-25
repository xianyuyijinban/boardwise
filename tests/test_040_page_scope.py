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
    build_schematic_model,
    collect_page_layout,
)
from boardwise.rules.connectivity import DuplicateDesignators

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
MOTOR = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"


def _pins(model, designator: str) -> dict[str, str | None]:
    return {pin.number: pin.net for pin in model.components[designator].pins}


@pytest.fixture(scope="module")
def foc() -> DesignModel:
    return build_schematic_model(FOC)


@pytest.fixture(scope="module")
def motor() -> DesignModel:
    return build_schematic_model(MOTOR)


# --------------------------------------------------------------------------
# the two anomalies this task exists for
# --------------------------------------------------------------------------


def test_c115_bridges_the_24v_rail_and_the_return_net(foc):
    """The engineer's report: C115 (330uF) sits between +24V and the return.

    Before 040 the model said both pins were on AGND — the weld of three pages
    (F1) plus a symbol graphic that shorted the capacitor bank's two rails
    (F3). `tests/fixtures/ProPrj_毕设FOC驱动板_*.epro2`'s PCB3 says the same as
    this assertion: {'1': '+24V', '2': 'PGND'}.
    """
    assert _pins(foc, "C115") == {"1": "+24V", "2": "PGND"}


def test_the_whole_330uF_bank_still_reads_two_nets(foc):
    """The bank's other electrolytics, from the same page and the same copper."""
    for designator in ("C116", "C17"):
        assert _pins(foc, designator) == {"1": "+24V", "2": "PGND"}, designator
    assert _pins(foc, "D2") == {"1": "PGND", "2": "+24V"}
    # CN3 is the 24V input connector. Pins 3/4 are marked NO_CONNECT in the file
    # (a 2-pole XT30 with four footprint pads), so the model reads them as
    # unconnected — which it did before 040 too, and which the copper agrees
    # with ({1: PGND, 2: +24V, 3: None, 4: None}). 039d's probe printed NET8 for
    # pin 3 because it reported the cluster of an NC pin; the model has never
    # given an NC pin a net.
    assert _pins(foc, "CN3") == {"1": "PGND", "2": "+24V", "3": None, "4": None}


def test_u5_is_the_ch340n_of_the_other_three_boards(foc):
    """pin 5 -> VCC, not AGND; and the pin that is really grounded is 3."""
    assert _pins(foc, "U5") == {
        "1": "D+", "2": "D-", "3": "GND", "4": None,
        "5": "VCC", "6": "RX", "7": "TX", "8": "VCC",
    }
    # PCB1 of the same archive (U5's board) says {5: VCC, 8: VCC, 3: GND,
    # 4: None}; so does the schematic's own symbol (Pin Name VCC on pin 5).
    assert "U5" not in foc.duplicate_designators


def test_the_header_brackets_no_longer_short_u2s_columns(foc):
    """U2 on page 40daf is a 2x6 header whose symbol draws a bracket over each
    column's three pins. The bracket is decoration: the file gives each of those
    pins its own stub wire with its own NET label (IC-, IC+, SLC / GLC, SHC,
    GHC), and PCB3 confirms six *different* nets. F3 keeps them apart.

    Asserted through net membership rather than `components["U2"].pins`, because
    U2's designator is also used on another page of this multi-board project —
    the model keeps the last placement per designator (040b's problem), while
    the nets still carry every placement's pins. The pre-040 model put
    U2.2/U2.4/U2.6 on one net and U2.8/U2.10/U2.12 on another; both triples were
    wrong.
    """
    def net_of(member):
        return sorted(
            name for name, net in foc.nets.items() if member in net.pins
        )

    assert "IC-" in net_of(("U2", "2"))
    assert "IC+" in net_of(("U2", "4"))
    assert "SLC" in net_of(("U2", "6"))
    assert "GLC" in net_of(("U2", "8"))
    # No net holds two of the three bracket-mates any more.
    for triple in (("2", "4", "6"), ("8", "10", "12")):
        members = {("U2", number) for number in triple}
        for name, net in foc.nets.items():
            shared = members & set(net.pins)
            assert len(shared) <= 1, (name, sorted(shared))


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
    141-pin cluster spanning three pages on the 毕设 board; the fix shows up as
    a *net count that goes up* (85 -> 112 and 113 -> 121) and as nets whose
    members all come from one page. Checked through the nets' own members: a
    designator that exists on two pages appears in two nets, which is the
    visible form of the repeat (040b re-scopes the model per board).
    """
    assert len(foc.nets) == 112
    assert len(motor.nets) == 121
    # The old weld's signature: one net with 100+ members. None is left.
    assert max(len(net.pins) for net in foc.nets.values()) < 100
    # +24V and PGND are the bank's rails, and they no longer share a net.
    assert ("C115", "1") in foc.nets["+24V"].pins
    assert ("C115", "1") not in foc.nets["PGND"].pins


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


def test_the_model_separates_same_page_from_cross_page_repeats(foc, motor):
    # 毕设: U15 and U16 appear twice *within* page 5f0f; 28 refs appear once on
    # each of two or three pages.
    assert foc.duplicate_designators == ["U15", "U16"]
    assert len(foc.cross_page_designators) == 28
    assert sorted(foc.cross_page_designators["C1"]) == [
        "0876ea4e415ed158",
        "40daf13560b1086b",
        "5f0f4e169f1745e789501f939bb10851",
    ]
    assert foc.repeated_designators() == sorted(
        foc.duplicate_designators + list(foc.cross_page_designators)
    )
    # 高速电机控制器: same split, other numbers.
    assert motor.duplicate_designators == ["U15", "U16", "U17", "U20"]
    assert len(motor.cross_page_designators) == 12


def test_single_page_boards_have_neither_kind():
    for name in ("ch340_golden.epro2", "llc_board.epro2",
                 "ProPrj_CH340G_2026-09-13.epro2",
                 "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"):
        model = build_schematic_model(FIXTURES / name)
        assert model.duplicate_designators == [], name
        assert model.cross_page_designators == {}, name


def test_the_rule_reports_both_kinds_and_names_the_pages(foc):
    """Both kinds are reported (the severity question is a ruling, see
    `CROSS_PAGE_REPEAT_IS_A_DEFECT`); what is new in 040 is that the cross-page
    finding names the pages, so a reader can tell the two apart."""
    findings = DuplicateDesignators().check(foc)
    by_message = {finding.message: finding for finding in findings}
    same_page = [
        finding for finding in findings
        if finding.message.startswith(("U15 is used by more than one placed part on one page",
                                       "U16 is used by more than one placed part on one page"))
    ]
    cross = [
        finding for finding in findings
        if finding.message.startswith("C1 is placed once on each of 3 pages")
    ]
    assert len(same_page) == 2, list(by_message)[:4]
    assert len(cross) == 1
    # the pages are named, so a reader can see which board is which
    assert "40daf135" in cross[0].message and "5f0f4e16" in cross[0].message
    assert len(findings) == len(foc.repeated_designators()) == 30


def test_an_injected_same_page_repeat_is_still_a_violation():
    """The injected `duplicate-designator` variant is a *cross-page* repeat by
    construction (011d: "append a new SCH_PAGE holding a copy of R24"), so it is
    listed under `cross_page_designators` — and the rule still reports it as an
    ERROR, which its signed record demands."""
    model = build_schematic_model(
        Path("reviewsets/injected/duplicate-designator.epro2")
    )
    assert model.duplicate_designators == []
    assert list(model.cross_page_designators) == ["R24"]
    finding = DuplicateDesignators().check(model)[0]
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
