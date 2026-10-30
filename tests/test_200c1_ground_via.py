"""Task 200C1: ``pcb-hs-via-ground-companion`` — the ground via beside a signal via.

One question per high-speed via: **is a ground-class via centre within the
house radius** (:data:`boardwise.core.highspeed.GROUND_VIA_RADIUS_MIL`, 50.0
mil, inclusive) of this via's centre? Nothing else — no reference-pair
question, no return-via array, no stub, no impedance (200C1 §1.4).

The tests run in the order the task book asks (``tasks/200c1_ground_via.md``
§4.1): the silence cases first (40 mil, the 50.0 boundary, non-high-speed,
zero vias), then the rows (50.1, 55, no ground via at all), then the nearest
pick among several, then the once-per-run readings, then the registration, then
the real fixtures read-only — where **0 findings is not a pass**, it is a
statement about how far the reading reached.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.geometry import BoardGeometry, NetGeometry, Point, ViaGeometry
from boardwise.core.highspeed import (
    GROUND_VIA_RADIUS_MIL,
    ground_vias,
    measure_via_ground,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.highspeed import GroundViaCompanion

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
KICAD_HS_PCB = FIXTURES / "kicad_hs" / "kicad_hs.kicad_pcb"

RULE_ID = "pcb-hs-via-ground-companion"


# ---------------------------------------------------------------------------
# Board builders: a via list and a net table, nothing else. The rule reads no
# copper, so these boards carry none — which also proves it does not.
# ---------------------------------------------------------------------------


def _via(via_id: str, net: str | None, x: float, y: float) -> ViaGeometry:
    return ViaGeometry(id=via_id, net=net, x=x, y=y)


def _board(vias, nets) -> BoardGeometry:
    board = BoardGeometry(source="synthetic")
    board.nets = {name: NetGeometry(name=name) for name in nets}
    board.vias = list(vias)
    for via in board.vias:
        if via.net:
            board.nets.setdefault(via.net, NetGeometry(name=via.net)).vias.append(via)
    return board


def _check(board: BoardGeometry) -> list:
    return GroundViaCompanion().check(PcbReviewContext(board=board))


# ---------------------------------------------------------------------------
# 1. silence where silence is right
# ---------------------------------------------------------------------------


def test_a_ground_via_at_40_mil_is_silent():
    board = _board(
        [_via("s1", "USB_D+", 1000.0, 1000.0), _via("g1", "GND", 1040.0, 1000.0)],
        ["USB_D+", "GND"],
    )
    assert _check(board) == []


def test_the_50_mil_boundary_is_inclusive_and_silent():
    """Exactly 50.0 mil is accompanied — the constant's own docstring says so."""
    board = _board(
        [_via("s1", "USB_D+", 1000.0, 1000.0), _via("g1", "GND", 1030.0, 1040.0)],
        ["USB_D+", "GND"],
    )

    reading = measure_via_ground(board.vias[0], ground_vias(board))
    assert reading.nearest_distance_mil == pytest.approx(50.0)
    assert _check(board) == []


def test_a_non_high_speed_via_is_silent_however_far_the_ground_via_is():
    board = _board(
        [_via("s1", "LED_A", 0.0, 0.0), _via("g1", "GND", 5000.0, 5000.0)],
        ["LED_A", "GND"],
    )
    assert _check(board) == []


def test_a_via_with_no_net_is_silent_and_never_counts_as_ground():
    board = _board(
        [_via("s1", "USB_D+", 0.0, 0.0), _via("u1", None, 5.0, 0.0)],
        ["USB_D+"],
    )
    assert ground_vias(board) == []
    findings = _check(board)
    assert len(findings) == 1, "an unattributed via is not a companion"
    assert "没有伴随地孔" in findings[0].message
    assert "板上没有任何 GND 类过孔" in findings[0].message


def test_zero_vias_and_zero_high_speed_nets_are_both_silent():
    assert _check(BoardGeometry()) == []
    # Vias, but not one high-speed net: the rule returns before sieving ground.
    board = _board(
        [_via("s1", "LED_A", 0.0, 0.0), _via("g1", "GND", 10.0, 0.0)],
        ["LED_A", "GND"],
    )
    assert _check(board) == []
    # A high-speed net that carries no via at all is likewise nothing to judge.
    board = _board([_via("g1", "GND", 10.0, 0.0)], ["USB_D+", "GND"])
    assert _check(board) == []


# ---------------------------------------------------------------------------
# 2. the rows
# ---------------------------------------------------------------------------


def test_a_ground_via_at_50_1_mil_is_one_warn_with_the_measured_distance():
    board = _board(
        [_via("s1", "USB_D+", 1000.0, 1000.0), _via("g1", "GND", 1050.1, 1000.0)],
        ["USB_D+", "GND"],
    )
    findings = _check(board)

    assert len(findings) == 1
    row = findings[0]
    assert row.rule_id == RULE_ID and row.severity == "WARN"
    assert row.level == "L1-pcb-geometry"
    assert row.target.net_refs == ["USB_D+"]
    assert "s1" in row.message and "USB_D+" in row.message
    assert "(1000.0, 1000.0) mil" in row.message
    assert "50.0 mil" in row.message or "50.0" in row.message
    assert "g1" in row.message and "50.10 mil" in row.message
    text = " | ".join(row.evidence)
    assert "s1" in text and "(1000.0, 1000.0) mil" in text
    assert "g1" in text and "50.10 mil" in text
    assert "50.0 mil" in text


def test_a_ground_via_at_55_mil_is_one_warn():
    board = _board(
        [_via("s1", "SPI1_SCK", 0.0, 0.0), _via("g1", "GND", 0.0, 55.0)],
        ["SPI1_SCK", "GND"],
    )
    findings = _check(board)
    assert len(findings) == 1
    assert "55.00 mil" in " | ".join(findings[0].evidence)


def test_no_ground_via_at_all_is_a_warn_that_says_so():
    board = _board([_via("s1", "USB_D+", 10.0, 20.0)], ["USB_D+", "+3V3"])
    findings = _check(board)

    assert len(findings) == 1
    row = findings[0]
    assert "板上没有任何 GND 类过孔" in row.message
    assert "无（板上 GND 类过孔数为 0）" in " | ".join(row.evidence)
    # Not a fabricated distance: the measurement reports the absence.
    reading = measure_via_ground(board.vias[0], [])
    assert reading.nearest_via_id is None
    assert reading.nearest_distance_mil is None


def test_each_high_speed_via_files_at_most_one_row():
    """Two far ground vias on one signal via are still one defect."""
    board = _board(
        [
            _via("s1", "USB_D+", 0.0, 0.0),
            _via("g1", "GND", 200.0, 0.0),
            _via("g2", "GND", 0.0, 300.0),
        ],
        ["USB_D+", "GND"],
    )
    findings = _check(board)
    assert len(findings) == 1
    assert [row.target.net_refs for row in findings] == [["USB_D+"]]


# ---------------------------------------------------------------------------
# 3. the nearest pick, and every ground name counts
# ---------------------------------------------------------------------------


def test_the_nearest_ground_via_is_the_one_named_and_the_tie_breaks_on_id():
    board = _board(
        [
            _via("s1", "USB_D+", 0.0, 0.0),
            _via("g120", "GND", 300.0, 0.0),
            _via("g7", "GND", 60.0, 0.0),
            _via("g9", "GND", 0.0, -400.0),
        ],
        ["USB_D+", "GND"],
    )
    reading = measure_via_ground(board.vias[0], ground_vias(board))
    assert (reading.nearest_via_id, reading.nearest_distance_mil) == ("g7", 60.0)
    assert len(_check(board)) == 1

    # A tie is broken by via id, not by board order: rename g7's twin.
    board.vias[2] = _via("g8", "GND", 60.0, 0.0)
    reading = measure_via_ground(board.vias[0], ground_vias(board))
    assert reading.nearest_via_id == "g8"
    board.vias[2] = _via("g7", "GND", 60.0, 0.0)
    board.vias[1] = _via("g6", "GND", -60.0, 0.0)
    reading = measure_via_ground(board.vias[0], ground_vias(board))
    assert reading.nearest_via_id == "g6", "the smaller id wins the tie"


@pytest.mark.parametrize("name", ["GND", "AGND", "PGND", "VSS", "SEC_GND", "EARTH"])
def test_every_ground_class_name_counts_as_a_companion(name):
    board = _board(
        [_via("s1", "USB_D+", 0.0, 0.0), _via("g1", name, 20.0, 0.0)],
        ["USB_D+", name],
    )
    assert [via.id for via in ground_vias(board)] == ["g1"]
    assert _check(board) == []


def test_the_reading_distinguishes_a_measured_silence_from_an_absence():
    """``measure_via_ground`` is pure: the same inputs give the same record."""
    board = _board(
        [_via("s1", "USB_D+", 1.5, -2.5), _via("g1", "GND", 1.5, 47.5)],
        ["USB_D+", "GND"],
    )
    first = measure_via_ground(board.vias[0], ground_vias(board))
    second = measure_via_ground(board.vias[0], ground_vias(board))
    assert first == second
    assert first.at == Point(1.5, -2.5)
    assert first.nearest_distance_mil == pytest.approx(50.0)
    assert _check(board) == [], "the altitude of the radius is not the test's business"


# ---------------------------------------------------------------------------
# 4. once per run
# ---------------------------------------------------------------------------


def test_the_high_speed_set_and_the_ground_sieve_each_run_once():
    from boardwise.rules.pcb import highspeed as rule_module

    calls = {"nets": 0, "ground": 0}
    original_nets = rule_module.high_speed_nets
    original_ground = rule_module.ground_vias

    def counting_nets(board):
        calls["nets"] += 1
        return original_nets(board)

    def counting_ground(board):
        calls["ground"] += 1
        return original_ground(board)

    rule_module.high_speed_nets = counting_nets
    rule_module.ground_vias = counting_ground
    try:
        board = _board(
            [
                _via("s1", "USB_D+", 0.0, 0.0),
                _via("s2", "USB_D-", 1000.0, 0.0),
                _via("g1", "GND", 2000.0, 0.0),
            ],
            ["USB_D+", "USB_D-", "GND"],
        )
        findings = GroundViaCompanion().check(PcbReviewContext(board=board))
    finally:
        rule_module.high_speed_nets = original_nets
        rule_module.ground_vias = original_ground

    assert calls == {"nets": 1, "ground": 1}
    assert len(findings) == 2, "one row per high-speed via, not one per pair"


# ---------------------------------------------------------------------------
# 5. registration
# ---------------------------------------------------------------------------


def test_the_rule_is_registered_last_with_its_identity():
    ids = [rule.id for rule in BUILTIN_PCB_RULES]

    # 200B was appended after 200B's split rule when it landed; **200C2 then
    # appended its two pair rules after it**, so the via rule is no longer last —
    # the family's order stays inventory → split → via → pair.
    assert ids[-3] == RULE_ID, "200C2 appends after 200C1"
    assert ids[-4] == "pcb-hs-cross-split"
    assert ids[-5] == "pcb-hs-diffpair-inventory"
    assert ids[-2:] == ["pcb-hs-diffpair-skew", "pcb-hs-diffpair-via-parity"]
    rule = {rule.id: rule for rule in BUILTIN_PCB_RULES}[RULE_ID]
    assert isinstance(rule, GroundViaCompanion)
    assert rule.level == "L1-pcb-geometry"
    assert rule.title == "高速过孔伴随地孔"
    assert "200C1" in rule.source and "可迭代" in rule.source


def test_the_radius_constant_is_the_house_rule_the_task_book_names():
    """50.0 mil, and the source says *house rule* — 200C1 §1.2 requires both."""
    import inspect

    from boardwise.core import highspeed as core_module

    assert GROUND_VIA_RADIUS_MIL == 50.0
    source = inspect.getsource(core_module)
    block = source[source.index("GROUND_VIA_RADIUS_MIL = 50.0") - 700 :]
    assert "house rule" in block.split("GROUND_VIA_RADIUS_MIL = 50.0")[0]
    assert "可调" in block or "tunable" in block
    assert "屋规" in GroundViaCompanion().source


# ---------------------------------------------------------------------------
# 6. the real fixtures (read-only)
# ---------------------------------------------------------------------------


def _rows(path: Path) -> list:
    findings, _section = run_pcb_review(path)
    return [row for row in findings if row.rule_id == RULE_ID]


def test_the_foc_fixture_runs_the_rule_and_files_only_measured_warns():
    findings, section = run_pcb_review(FOC_100)
    rows = [row for row in findings if row.rule_id == RULE_ID]

    checks = section["boards"][0]["checksRun"]
    assert checks[-3] == RULE_ID, "the reading is registered and runs on the real board"
    assert checks[-2:] == ["pcb-hs-diffpair-skew", "pcb-hs-diffpair-via-parity"]
    assert section["rules_errored"] == []
    for row in rows:
        assert row.severity == "WARN" and row.level == "L1-pcb-geometry"
        assert row.board == "PCB1"
        assert row.target.net_refs, "the via's net is kept as the target"
        text = " | ".join(row.evidence)
        assert "mil" in text and "阈值" in text


def test_the_robot_fixture_runs_the_rule_and_files_only_warns():
    findings, section = run_pcb_review(ROBOT)
    rows = [row for row in findings if row.rule_id == RULE_ID]
    assert all(row.severity == "WARN" for row in rows)
    assert RULE_ID in section["boards"][0]["checksRun"]
    assert section["rules_errored"] == []


def test_the_kicad_fixture_must_run_and_is_only_a_coverage_note():
    """kicad_hs carries no vias at all: 0 rows is 覆盖不足, never a pass."""
    from boardwise.parsers.kicad import read_kicad_board

    board = read_kicad_board(KICAD_HS_PCB)
    assert board.vias == [], "the fixture has no vias — the task book's 覆盖不足 case"

    findings, section = run_pcb_review(KICAD_HS_PCB)
    assert [row for row in findings if row.rule_id == RULE_ID] == []
    assert RULE_ID in section["boards"][0]["checksRun"]
    assert section["rules_errored"] == []
