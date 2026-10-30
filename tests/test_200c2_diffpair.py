"""Task 200C2 (A3): ``pcb-hs-diffpair-skew`` and ``pcb-hs-diffpair-via-parity``.

Two questions about **one differential pair**, both answered from the single
:class:`~boardwise.core.highspeed.DiffPairReading`:

* is the pair's two-sided **length** within the house tolerance, and do the two
  sides run on the same set of layers (``WARN``, ``DIFFPAIR_SKEW_MIL = 5.0``,
  strict);
* do the two sides use the same number of **vias** (``INFO``, a count, not a
  defect by itself).

The tests follow ``tasks/200c2_diffpair.md`` §4.1: silence first (equal pair,
the 5.0 boundary, one side unrouted, unlayered tracks), then the rows (5.1, 6,
different layer sets, 2:1 vias, all three facts at once), then the source labels
and the registration, then the real fixtures read-only — where a pair with no
copper is **覆盖不足**, never a pass.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    NetGeometry,
    Point,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.geometry import NetMeta
from boardwise.core.highspeed import (
    DIFFPAIR_SKEW_MIL,
    identify_diff_pairs,
    measure_diff_pair,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.highspeed import DiffPairSkew, DiffPairViaParity

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
KICAD_HS_PCB = FIXTURES / "kicad_hs" / "kicad_hs.kicad_pcb"

SKEW_ID = "pcb-hs-diffpair-skew"
PARITY_ID = "pcb-hs-diffpair-via-parity"


# ---------------------------------------------------------------------------
# Board builders: tracks, vias and an optional declaration, nothing else.
# ---------------------------------------------------------------------------


def _track(track_id: str, net: str, layer_id: int | None, length: float, y: float = 0.0):
    return TrackSegment(
        id=track_id,
        net=net,
        layer_id=layer_id,
        start=Point(0.0, y),
        end=Point(length, y),
        width=6.0,
    )


def _board(tracks=(), vias=(), declared=()) -> BoardGeometry:
    """A synthetic board whose ``nets`` table is built from its copper."""
    board = BoardGeometry(source="synthetic")
    board.tracks = list(tracks)
    board.vias = list(vias)
    nets: dict[str, NetGeometry] = {}
    for track in board.tracks:
        if track.net:
            nets.setdefault(track.net, NetGeometry(name=track.net)).tracks.append(track)
    for via in board.vias:
        if via.net:
            nets.setdefault(via.net, NetGeometry(name=via.net)).vias.append(via)
    board.nets = nets
    for group, positive, names in declared:
        for name in names:
            board.net_meta[name] = NetMeta(
                name=name, diff_pair=group, diff_positive=(name == positive)
            )
    return board


def _pair(board: BoardGeometry):
    pairs = identify_diff_pairs(board)
    assert len(pairs) == 1, pairs
    return pairs[0]


def _skew(board: BoardGeometry) -> list:
    return DiffPairSkew().check(PcbReviewContext(board=board))


def _parity(board: BoardGeometry) -> list:
    return DiffPairViaParity().check(PcbReviewContext(board=board))


def _equal_board(**kwargs) -> BoardGeometry:
    """``HS_P`` / ``HS_N`` routed 100 mil each on layer 1, no vias."""
    return _board(
        tracks=[_track("p1", "HS_P", 1, 100.0), _track("n1", "HS_N", 1, 100.0, 10.0)],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. silence where silence is right
# ---------------------------------------------------------------------------


def test_an_equal_pair_on_one_layer_with_no_vias_is_silent():
    board = _equal_board()

    reading = measure_diff_pair(board, _pair(board))
    assert reading.skew_mil == 0.0
    assert reading.layers_comparable and not reading.layer_sets_differ
    assert _skew(board) == []
    assert _parity(board) == []


def test_the_5_mil_boundary_is_silent_and_5_1_is_a_warn():
    """The constant is the boundary of 「等长」: 5.0 has not crossed it."""
    board = _board(
        tracks=[_track("p1", "HS_P", 1, 100.0), _track("n1", "HS_N", 1, 105.0, 10.0)]
    )
    reading = measure_diff_pair(board, _pair(board))
    assert reading.skew_mil == pytest.approx(5.0)
    assert _skew(board) == []
    assert DIFFPAIR_SKEW_MIL == 5.0

    board = _board(
        tracks=[_track("p1", "HS_P", 1, 100.0), _track("n1", "HS_N", 1, 105.1, 10.0)]
    )
    findings = _skew(board)
    assert len(findings) == 1
    row = findings[0]
    assert row.rule_id == SKEW_ID and row.severity == "WARN"
    assert row.level == "L1-pcb-geometry"
    assert row.target.net_refs == ["HS_P", "HS_N"]
    assert "5.10 mil" in row.message
    assert "5.0 mil" in row.message, "the threshold is stated in the row"
    assert "超阈值" in row.message
    # The layer fact is stated even though it did not fire (§1.2).
    assert "层集合相同" in row.message


def test_a_six_mil_skew_is_one_warn_listing_both_lengths_and_layers():
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("n1", "HS_N", 1, 60.0, 10.0),
            _track("n2", "HS_N", 2, 46.0, 10.0),
        ]
    )
    findings = _skew(board)

    assert len(findings) == 1
    row = findings[0]
    assert "6.00 mil" in row.message
    text = " | ".join(row.evidence)
    assert "100.000 mil" in text and "106.000 mil" in text
    assert "6.000 mil" in text
    assert "逐层长度" in text
    # The layer fact *did* differ here and is reported beside the length one.
    assert "层集合不同" in row.message
    assert "过孔数：正 0 / 负 0" in text


def test_different_layer_sets_warn_even_at_zero_skew():
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("n1", "HS_N", 1, 40.0, 10.0),
            _track("n2", "HS_N", 2, 60.0, 10.0),
        ]
    )
    reading = measure_diff_pair(board, _pair(board))
    assert reading.skew_mil == 0.0
    assert reading.positive_layer_ids == frozenset({1})
    assert reading.negative_layer_ids == frozenset({1, 2})

    findings = _skew(board)
    assert len(findings) == 1
    assert "层集合不同" in findings[0].message
    assert "0.00 mil" in findings[0].message
    # A layer-only defect is still exactly one row, and the via counts agree.
    assert _parity(board) == []


def test_one_side_without_a_track_silences_the_whole_pair():
    """§1.4: a length difference against zero copper is not a skew."""
    board = _board(
        tracks=[_track("p1", "HS_P", 1, 100.0), _track("n1", "HS_N", 1, 100.0, 10.0)],
        vias=[ViaGeometry(id="v1", net="HS_N", x=0.0, y=10.0)],
        declared=[("DP7", "HS_P", ["HS_P", "HS_N"])],
    )
    board.nets["HS_N"].tracks = []
    board.tracks = [track for track in board.tracks if track.net != "HS_N"]

    reading = measure_diff_pair(board, _pair(board))
    assert reading.measurable is False
    assert reading.negative_length_mil == 0.0
    assert reading.positive_vias == 0 and reading.negative_vias == 1
    assert _skew(board) == [], "no skew is claimed against an unrouted net"
    assert _parity(board) == [], "and no via parity either"


def test_an_unlayered_track_reports_lengths_but_never_a_layer_difference():
    """§1.4: an unlayered track is 未测 for the layer set, not a different set."""
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("n1", "HS_N", 2, 70.0, 10.0),
            _track("n2", "HS_N", None, 30.0, 10.0),
        ],
        vias=[ViaGeometry(id="v1", net="HS_N", x=0.0, y=10.0)],
    )
    reading = measure_diff_pair(board, _pair(board))

    assert reading.negative_length_mil == pytest.approx(100.0), "the length still reads"
    assert reading.negative_vias == 1, "the via count still reads"
    assert reading.negative_unlayered_tracks == 1
    assert reading.layers_comparable is False
    assert reading.layer_sets_differ is False, "not comparable is not 「different」"
    # The layer sets *would* differ (1 vs 2) if the unlayered track were ignored.
    assert reading.positive_layer_ids != reading.negative_layer_ids
    assert _skew(board) == [], "no layer WARN is fabricated from an unlayered track"
    assert [row.rule_id for row in _parity(board)] == [PARITY_ID]


def test_a_board_with_no_pair_is_silent_for_both_rules():
    assert _skew(BoardGeometry()) == []
    assert _parity(BoardGeometry()) == []
    board = _board(tracks=[_track("t1", "GND", 1, 100.0)])
    assert _skew(board) == []
    assert _parity(board) == []


# ---------------------------------------------------------------------------
# 2. the via-parity row
# ---------------------------------------------------------------------------


def test_two_to_one_vias_is_one_info_and_no_skew_warn():
    board = _board(
        tracks=[_track("p1", "HS_P", 1, 100.0), _track("n1", "HS_N", 1, 100.0, 10.0)],
        vias=[
            ViaGeometry(id="vp1", net="HS_P", x=10.0, y=0.0),
            ViaGeometry(id="vp2", net="HS_P", x=90.0, y=0.0),
            ViaGeometry(id="vn1", net="HS_N", x=10.0, y=10.0),
        ],
    )
    findings = _parity(board)

    assert len(findings) == 1
    row = findings[0]
    assert row.rule_id == PARITY_ID and row.severity == "INFO"
    assert row.level == "L1-pcb-geometry"
    assert row.target.net_refs == ["HS_P", "HS_N"]
    assert "2:1" in row.message
    assert "HS_P 2 个" in row.message and "HS_N 1 个" in row.message
    text = " | ".join(row.evidence)
    assert "过孔数：正 2 / 负 1" in text
    assert "100.000 mil" in text, "the length reading travels with the via count"
    assert _skew(board) == [], "equal lengths and layers: nothing for the WARN rule"


def test_all_three_facts_can_fire_together_and_the_skew_row_lists_both():
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("n1", "HS_N", 1, 40.0, 10.0),
            _track("n2", "HS_N", 2, 54.0, 10.0),
        ],
        vias=[
            ViaGeometry(id="vp1", net="HS_P", x=0.0, y=0.0),
            ViaGeometry(id="vn1", net="HS_N", x=0.0, y=10.0),
            ViaGeometry(id="vn2", net="HS_N", x=40.0, y=10.0),
            ViaGeometry(id="vn3", net="HS_N", x=94.0, y=10.0),
        ],
    )
    skew_rows = _skew(board)
    parity_rows = _parity(board)

    assert len(skew_rows) == 1 and len(parity_rows) == 1
    assert skew_rows[0].severity == "WARN" and parity_rows[0].severity == "INFO"
    message = skew_rows[0].message
    assert "6.00 mil" in message and "超阈值" in message
    assert "层集合不同" in message
    assert "过孔数：正 1 / 负 3" in " | ".join(skew_rows[0].evidence)
    assert "1:3" in parity_rows[0].message


def test_each_rule_files_at_most_one_row_per_pair():
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("p2", "HS_P", 2, 20.0),
            _track("n1", "HS_N", 1, 100.0, 10.0),
            _track("n2", "HS_N", 3, 30.0, 10.0),
        ],
        vias=[
            ViaGeometry(id="vp1", net="HS_P", x=1.0, y=0.0),
            ViaGeometry(id="vn1", net="HS_N", x=1.0, y=10.0),
            ViaGeometry(id="vn2", net="HS_N", x=2.0, y=10.0),
        ],
    )
    assert len(_skew(board)) == 1
    assert len(_parity(board)) == 1


def test_layers_and_vias_are_compared_per_pair_not_per_board():
    """Two pairs, opposite verdicts: the rows are per pair, not per fixture."""
    board = _board(
        tracks=[
            _track("p1", "HS_P", 1, 100.0),
            _track("n1", "HS_N", 1, 100.0, 10.0),
            _track("q1", "CLK_P", 1, 100.0, 20.0),
            _track("r1", "CLK_N", 1, 120.0, 30.0),
        ],
    )
    assert len(identify_diff_pairs(board)) == 2
    findings = _skew(board)
    assert len(findings) == 1
    assert "CLK_" in findings[0].message
    assert "20.00 mil" in findings[0].message


# ---------------------------------------------------------------------------
# 3. the source label survives
# ---------------------------------------------------------------------------


def test_the_declared_source_is_kept_in_the_row():
    board = _board(
        tracks=[_track("p1", "D+", 1, 100.0), _track("n1", "D-", 1, 106.0, 10.0)],
        declared=[("DP1", "D-", ["D+", "D-"])],
    )
    reading = measure_diff_pair(board, _pair(board))
    assert (reading.group, reading.source) == ("DP1", "declared")
    assert (reading.positive, reading.negative) == ("D-", "D+")

    row = _skew(board)[0]
    assert "DP1" in row.message and "编辑器声明" in row.message
    assert row.evidence[0] == "DP1: 正 D- / 负 D+（declared）"
    assert row.target.net_refs == ["D-", "D+"]


def test_the_heuristic_source_is_kept_in_the_row():
    board = _equal_board(
        vias=[ViaGeometry(id="v1", net="HS_P", x=0.0, y=0.0)],
    )
    reading = measure_diff_pair(board, _pair(board))
    assert reading.source == "heuristic"

    row = _parity(board)[0]
    assert "网名启发式" in row.message and "heuristic" in row.evidence[0]


# ---------------------------------------------------------------------------
# 4. registration
# ---------------------------------------------------------------------------


def test_both_rules_are_registered_after_200c1_with_their_identities():
    ids = [rule.id for rule in BUILTIN_PCB_RULES]

    assert ids[-2:] == [SKEW_ID, PARITY_ID], "200C2 appends both, skew first"
    assert ids[-3] == "pcb-hs-via-ground-companion"
    rules = {rule.id: rule for rule in BUILTIN_PCB_RULES}
    assert isinstance(rules[SKEW_ID], DiffPairSkew)
    assert isinstance(rules[PARITY_ID], DiffPairViaParity)
    assert rules[SKEW_ID].level == "L1-pcb-geometry"
    assert rules[PARITY_ID].level == "L1-pcb-geometry"
    assert rules[SKEW_ID].title == "差分对内长度/层偏差"
    assert rules[PARITY_ID].title == "差分对过孔数不对称"
    for rule_id in (SKEW_ID, PARITY_ID):
        assert "200C2" in rules[rule_id].source and "可迭代" in rules[rule_id].source


def test_the_skew_constant_is_documented_as_a_tunable_house_rule():
    import inspect

    from boardwise.core import highspeed as core_module

    source = inspect.getsource(core_module)
    block = source[: source.index("DIFFPAIR_SKEW_MIL = 5.0")]
    tail = block[-900:]
    assert "house rule" in tail
    assert "tunable" in tail


# ---------------------------------------------------------------------------
# 5. the real fixtures (read-only)
# ---------------------------------------------------------------------------


def _rows(path: Path, rule_id: str) -> list:
    findings, section = run_pcb_review(path)
    assert section["rules_errored"] == []
    return [row for row in findings if row.rule_id == rule_id]


def test_the_foc_fixture_reads_its_two_pairs_and_files_one_of_each():
    """Measured on 毕设FOC 1.0.0 PCB1: DP1 differs in layers *and* vias; DP2 is even.

    The numbers are the fixture's, read through ``track_width_stats``: DP1's
    ``D-`` is 636.541 mil on layer 1 and ``D+`` 636.809 mil over layers 1 and 2,
    with 0 and 2 vias; DP2's ``CAN_L`` / ``CAN_H`` are 455.928 / 455.366 mil on
    layer 1 with no vias. Skew is **within** 5 mil for both — the DP1 WARN comes
    from the layer set, which is exactly the second fact the task book asks for.
    """
    skew_rows = _rows(FOC_100, SKEW_ID)
    parity_rows = _rows(FOC_100, PARITY_ID)

    assert len(skew_rows) == 1 and len(parity_rows) == 1
    assert {row.board for row in skew_rows} == {"PCB1"}
    assert skew_rows[0].severity == "WARN" and parity_rows[0].severity == "INFO"
    text = " | ".join(skew_rows[0].evidence)
    assert "DP1" in text and "636.541 mil" in text and "636.809 mil" in text
    assert "层集合不同" in skew_rows[0].message
    assert "0:2" in parity_rows[0].message, "D- carries none, D+ carries two"


def test_the_robot_fixture_reads_its_one_pair():
    skew_rows = _rows(ROBOT, SKEW_ID)
    parity_rows = _rows(ROBOT, PARITY_ID)

    assert len(skew_rows) == 1 and len(parity_rows) == 1
    assert skew_rows[0].board == "PCB1"
    text = " | ".join(skew_rows[0].evidence)
    assert "271.912 mil" in text and "271.800 mil" in text
    assert "层集合不同" in skew_rows[0].message


def test_the_kicad_fixture_pair_has_no_copper_and_is_only_a_coverage_note():
    """``kicad_hs`` pairs ``USB_D+``/``USB_D-`` by name and routes neither: 覆盖不足."""
    from boardwise.parsers.kicad import read_kicad_board

    board = read_kicad_board(KICAD_HS_PCB)
    pairs = identify_diff_pairs(board)
    assert [(pair.positive, pair.negative) for pair in pairs] == [("USB_D+", "USB_D-")]
    reading = measure_diff_pair(board, pairs[0])
    assert reading.positive_tracks == 0 and reading.negative_tracks == 0
    assert reading.measurable is False

    assert _rows(KICAD_HS_PCB, SKEW_ID) == []
    assert _rows(KICAD_HS_PCB, PARITY_ID) == []
    findings, section = run_pcb_review(KICAD_HS_PCB)
    assert section["boards"][0]["checksRun"][-2:] == [SKEW_ID, PARITY_ID], (
        "both rules ran; the zero rows are about the fixture's missing copper"
    )
