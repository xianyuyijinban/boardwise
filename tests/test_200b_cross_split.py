"""Task 200B: ``pcb-hs-cross-split`` — the high-speed family's first judgement.

The rule answers one question per high-speed track: **along the line, is the
adjacent reference layer's ground copper continuous, and is it the same piece of
copper?** Everything here is geometric — exact parameters, no sampling — and the
file's own stackup decides which layer is 「the reference」.

The tests are ordered as the task book asks (:doc:`tasks/200b_cross_split.md`
§4.1): the behaviour counter-examples first — silence where silence is right,
one row where one row is right — then the measurement's own invariants, then the
registration, then the real fixtures (read-only) and the two readings the task
book insists are recorded rather than claimed: a ``PLANE`` reference layer is
**未测**, and a fixture with no zones is a **coverage limitation**, never a
positive example.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    NetGeometry,
    NetMeta,
    PourShape,
    StackupEntry,
    TrackSegment,
)
from boardwise.core.highspeed import (
    BREAK_BOUNDARY,
    BREAK_GAP,
    STATUS_MEASURED,
    STATUS_NO_COVERAGE,
    STATUS_NO_GROUND_POUR,
    STATUS_NO_REFERENCE,
    STATUS_PLANE,
    STATUS_ZERO_LENGTH,
    high_speed_nets,
    is_high_speed_net_name,
    measure_track_coverage,
)
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.highspeed import CrossSplit

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
LLC = FIXTURES / "llc_board.epro2"
KICAD_HS_PCB = FIXTURES / "kicad_hs" / "kicad_hs.kicad_pcb"

RULE_ID = "pcb-hs-cross-split"


# ---------------------------------------------------------------------------
# A four-layer board whose Inner1 (15) is a plane and Inner2 (16) a signal
# layer — the same physical layout 毕设FOC 1.0.0 carries (ids 1/15/16/2 at
# z_index 1000/1002/1004/9000), so the reference of a bottom trace (2) is
# Inner2 (16) and every measurement below happens on real, splittable copper.
# ---------------------------------------------------------------------------

LAYERS = {
    1: LayerInfo(layer_id=1, name="Top Layer", layer_type="SIGNAL"),
    15: LayerInfo(layer_id=15, name="Inner1", layer_type="PLANE"),
    16: LayerInfo(layer_id=16, name="Inner2", layer_type="SIGNAL"),
    2: LayerInfo(layer_id=2, name="Bottom Layer", layer_type="SIGNAL"),
}

STACKUP = [
    StackupEntry(layer_id=1, z_index=1000),
    StackupEntry(layer_id=15, z_index=1002),
    StackupEntry(layer_id=16, z_index=1004),
    StackupEntry(layer_id=2, z_index=9000),
]


def _point(x: float, y: float):
    from boardwise.core.geometry import Point

    return Point(x, y)


def _rect_points(x0: float, y0: float, x1: float, y1: float):
    return [_point(x0, y0), _point(x1, y0), _point(x1, y1), _point(x0, y1)]


def _track(track_id: str, start, end, net: str, layer: int = 2) -> TrackSegment:
    return TrackSegment(
        id=track_id, net=net, layer_id=layer, start=_point(*start), end=_point(*end), width=8.0
    )


def _pour(pour_id: str, net: str, layer: int, ring, voids=(), kind="poured") -> PourShape:
    rings = [list(ring)] + [list(void) for void in voids]
    return PourShape(
        id=pour_id, net=net, layer_id=layer, kind=kind, points=list(ring), rings=rings
    )


def _board(tracks, pours, nets, meta=()) -> BoardGeometry:
    board = BoardGeometry(source="synthetic", layers=dict(LAYERS), stackup=list(STACKUP))
    board.nets = {name: NetGeometry(name=name) for name in nets}
    board.net_meta = {item.name: item for item in meta}
    board.pours = list(pours)
    board.tracks = list(tracks)
    for track in board.tracks:
        geoms = board.nets.setdefault(track.net, NetGeometry(name=track.net))
        geoms.tracks.append(track)
    return board


# ---------------------------------------------------------------------------
# 1. behaviour counter-examples (written before the positive cases)
# ---------------------------------------------------------------------------


def test_a_continuous_single_pour_is_silent():
    """One pour spanning the whole trace: covered end to end, nothing to say."""
    track = _track("t1", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [_pour("p1", "GND", 16, _rect_points(-100, -100, 1100, 100))],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    assert coverage.status == STATUS_MEASURED
    assert coverage.breaks == []
    assert len(coverage.runs) == 1 and coverage.runs[0].start == 0.0
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_a_trace_crossing_a_gap_in_the_ground_copper_is_one_warn():
    """Two pours with bare laminate between them: a gap, one row, one coordinate."""
    track = _track("t2", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [
            _pour("p1", "GND", 16, _rect_points(-100, -100, 400, 100)),
            _pour("p2", "GND", 16, _rect_points(600, -100, 1100, 100)),
        ],
        ["USB_D+", "GND"],
    )
    findings = CrossSplit().check(PcbReviewContext(board=board))

    assert len(findings) == 1
    row = findings[0]
    assert row.rule_id == RULE_ID and row.severity == "WARN"
    assert row.target.net_refs == ["USB_D+"]
    assert "gap" in row.message and "house rule" not in row.message
    assert "200B" in row.message and "可迭代" in row.message
    assert "t2" in row.message and "USB_D+" in row.message
    assert "Inner2" in row.message and "Bottom Layer" in row.message
    text = " | ".join(row.evidence)
    assert "gap" in text and "(500.0, 0.0) mil" in text


def test_two_pours_that_touch_directly_are_a_boundary_not_a_gap():
    """Adjacent pours, no uncovered stretch: the copper changes owner."""
    track = _track("t3", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [
            _pour("p1", "GND", 16, _rect_points(-100, -100, 500, 100)),
            _pour("p2", "GND", 16, _rect_points(500, -100, 1100, 100)),
        ],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    assert [item.kind for item in coverage.breaks] == [BREAK_BOUNDARY]
    boundary = coverage.breaks[0]
    assert boundary.before == (0,) and boundary.after == (1,)
    assert boundary.at.x == pytest.approx(500.0)
    assert len(CrossSplit().check(PcbReviewContext(board=board))) == 1


def test_a_void_in_the_pour_is_read_as_a_gap():
    """A POURED island's rings carry its voids; the segment over a void is split."""
    track = _track("t4", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [
            _pour(
                "p1",
                "GND",
                16,
                _rect_points(-100, -100, 1100, 100),
                voids=[_rect_points(400, -50, 600, 50)],
            )
        ],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    assert [item.kind for item in coverage.breaks] == [BREAK_GAP]
    assert coverage.breaks[0].at.x == pytest.approx(500.0)
    assert len(CrossSplit().check(PcbReviewContext(board=board))) == 1


def test_a_non_high_speed_net_is_silent_even_across_a_gap():
    track = _track("t5", (0, 0), (1000, 0), "LED_A")
    board = _board(
        [track],
        [
            _pour("p1", "GND", 16, _rect_points(-100, -100, 400, 100)),
            _pour("p2", "GND", 16, _rect_points(600, -100, 1100, 100)),
        ],
        ["LED_A", "GND"],
    )
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_a_plane_reference_layer_is_not_measured_and_says_so():
    """A ``PLANE`` neighbour has no split geometry in the file: 未测, not 「整」."""
    track = _track("t6", (0, 0), (1000, 0), "USB_D+", layer=1)  # Top -> Inner1 (PLANE)
    board = _board(
        [track],
        [_pour("p1", "GND", 15, _rect_points(-100, -100, 400, 100))],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    assert coverage.reference_layer_id == 15
    assert coverage.status == STATUS_PLANE
    assert coverage.breaks == []
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_no_reference_layer_no_ground_pour_and_no_coverage_are_three_silences():
    track = _track("t7", (0, 0), (1000, 0), "USB_D+")

    # No stackup at all: no neighbour to name.
    bare = BoardGeometry(source="synthetic")
    assert measure_track_coverage(bare, track).status == STATUS_NO_REFERENCE

    # A reference layer with copper on a non-ground net only.
    board = _board([track], [_pour("p1", "+3V3", 16, _rect_points(-100, -100, 1100, 100))],
                   ["USB_D+", "+3V3"])
    assert measure_track_coverage(board, track).status == STATUS_NO_GROUND_POUR
    assert CrossSplit().check(PcbReviewContext(board=board)) == []

    # Ground copper exists but nowhere under this segment.
    board = _board([track], [_pour("p1", "GND", 16, _rect_points(2000, 2000, 3000, 3000))],
                   ["USB_D+", "GND"])
    assert measure_track_coverage(board, track).status == STATUS_NO_COVERAGE
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_a_zero_length_segment_is_silent():
    track = _track("t8", (100, 100), (100, 100), "USB_D+")
    board = _board([track], [_pour("p1", "GND", 16, _rect_points(-100, -100, 1100, 1100))],
                   ["USB_D+", "GND"])
    assert measure_track_coverage(board, track).status == STATUS_ZERO_LENGTH
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_overlapping_pours_that_share_one_object_are_not_a_boundary():
    """A void cut through a pour's middle, with a second pour bridging it.

    Both covered intervals are held by ``p0`` (the big one), so the copper never
    changes owner: the segment sees one island with a slot, and 200B §1.2 says
    that is not a boundary. Nothing is filed.
    """
    track = _track("t9", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [
            _pour(
                "p0",
                "GND",
                16,
                _rect_points(-100, -100, 1100, 100),
                voids=[_rect_points(400, -50, 600, 50)],
            ),
            _pour("p1", "GND", 16, _rect_points(350, -60, 650, 60)),
        ],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    assert coverage.breaks == [], coverage.breaks
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_a_truth_table_of_every_junction_shape():
    """The three junction shapes side by side, one board each.

    ``overlap`` (shared pour) → nothing; ``touch`` (no shared pour) → boundary;
    ``separated`` (bare laminate) → gap. The same geometry with different pours
    is the only variable, which is what makes this a table rather than an
    anecdote.
    """
    cases = {
        "overlap": ([_pour("a", "GND", 16, _rect_points(-100, -100, 550, 100)),
                     _pour("b", "GND", 16, _rect_points(450, -100, 1100, 100))], []),
        "touch": ([_pour("a", "GND", 16, _rect_points(-100, -100, 500, 100)),
                   _pour("b", "GND", 16, _rect_points(500, -100, 1100, 100))], [BREAK_BOUNDARY]),
        "separated": ([_pour("a", "GND", 16, _rect_points(-100, -100, 400, 100)),
                       _pour("b", "GND", 16, _rect_points(600, -100, 1100, 100))], [BREAK_GAP]),
    }
    for label, (pours, expected) in cases.items():
        track = _track("t", (0, 0), (1000, 0), "USB_D+")
        board = _board([track], pours, ["USB_D+", "GND"])
        coverage = measure_track_coverage(board, track)
        assert [item.kind for item in coverage.breaks] == expected, label


# ---------------------------------------------------------------------------
# 2. the high-speed net set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("USB_D+", True),
        ("USB_D-", True),
        ("SPI1_SCK", True),
        ("DDR3_DQ0", True),
        ("clk_24m", True),
        ("PCIE_RX0_P", True),
        ("HDMI_TX2+", True),
        ("LVDS_IN", True),
        ("MIPI_CSI0", True),
        ("RGMII_TXC", True),
        ("ETH_MDIO", True),
        ("DQS0", True),
        ("+24V", False),
        ("GND", False),
        ("LED_A", False),
        ("MOTOR_U", False),
        ("", False),
    ],
)
def test_the_name_sieve_is_token_prefix_and_upper_case(name, expected):
    assert is_high_speed_net_name(name) is expected


def test_the_set_is_182s_pairs_plus_the_sieve_and_is_sorted():
    board = _board([], [], ["USB_D+", "USB_D-", "CLK_50M", "LED_A", "GND"])
    assert high_speed_nets(board) == ["CLK_50M", "USB_D+", "USB_D-"]


def test_a_high_speed_netclass_puts_a_plain_named_net_in_the_set():
    board = _board(
        [],
        [],
        ["DP_A", "DP_B", "LED_A"],
        [
            NetMeta(name="DP_A", net_class="DDR_DATA"),
            NetMeta(name="DP_B", net_class="default"),
        ],
    )
    assert high_speed_nets(board) == ["DP_A"]


def test_the_set_is_computed_once_per_run():
    """The set is a pure function of the board, and the rule calls it once."""
    from boardwise.rules.pcb import highspeed as rule_module

    calls = []
    original = rule_module.high_speed_nets

    def counting(board):
        calls.append(board)
        return original(board)

    rule_module.high_speed_nets = counting
    try:
        track = _track("t1", (0, 0), (1000, 0), "USB_D+")
        board = _board(
            [track, _track("t1b", (0, 50), (1000, 50), "USB_D+")],
            [_pour("p1", "GND", 16, _rect_points(-100, -100, 400, 100)),
             _pour("p2", "GND", 16, _rect_points(600, -100, 1100, 100))],
            ["USB_D+", "GND"],
        )
        findings = CrossSplit().check(PcbReviewContext(board=board))
        assert len(calls) == 1, "one set per run, not one per track"
        assert len(findings) == 2
    finally:
        rule_module.high_speed_nets = original


# ---------------------------------------------------------------------------
# 3. geometry invariants
# ---------------------------------------------------------------------------


def test_the_split_points_are_exact_parameters_not_samples():
    """The gap ends exactly where the copper does, and only one row comes out.

    A 0.4 mm-wide ``POURED`` island is far narrower than any fixed sampling step
    would resolve, and the parameters land exactly on its edges — the assertion
    that says 「exact intersection, not a step」.
    """
    track = _track("t10", (0, 0), (1000, 0), "USB_D+")
    # Copper in 0..400, void 400..700, copper 700..1000.
    board = _board(
        [track],
        [   _pour("p1", "GND", 16, _rect_points(-50, -50, 400, 50)),
            _pour("p2", "GND", 16, _rect_points(400, -50, 700, 50)),
        ],
        ["USB_D+", "GND"],
    )
    coverage = measure_track_coverage(board, track)

    # p1 and p2 touch at 400 → boundary there; no gap.
    assert [(round(b.start, 6), round(b.end, 6)) for b in coverage.breaks] == [(0.4, 0.4)]
    assert coverage.breaks[0].kind == BREAK_BOUNDARY

    # Now split them for real: p1 ends at 400, p2 starts at 700.
    board.pours[1] = _pour("p2", "GND", 16, _rect_points(700, -50, 1000, 50))
    coverage = measure_track_coverage(board, track)
    assert [item.kind for item in coverage.breaks] == [BREAK_GAP]
    assert (coverage.breaks[0].start, coverage.breaks[0].end) == pytest.approx((0.4, 0.7))


def test_one_track_files_one_row_that_lists_every_break():
    track = _track("t11", (0, 0), (1000, 0), "USB_D+")
    board = _board(
        [track],
        [
            _pour("p1", "GND", 16, _rect_points(-50, -50, 200, 50)),
            _pour("p2", "GND", 16, _rect_points(200, -50, 400, 50)),  # boundary at 0.2
            _pour("p3", "GND", 16, _rect_points(600, -50, 1100, 50)),  # gap 0.4..0.6
        ],
        ["USB_D+", "GND"],
    )
    findings = CrossSplit().check(PcbReviewContext(board=board))

    assert len(findings) == 1
    text = " | ".join(findings[0].evidence)
    assert text.count("boundary") == 1 and text.count("gap") == 1
    assert "共 2 处断点" in findings[0].message


def test_a_superseded_pour_region_is_not_counted_twice():
    """A ``POURED`` result replaces its ``POUR`` region (135): one object, one break.

    With both records present the segment would otherwise see the outline and
    its result as two pours touching at the same place — a phantom boundary
    between a region and itself.
    """
    track = _track("t12", (0, 0), (1000, 0), "USB_D+")
    region = PourShape(
        id="e-1", net="GND", layer_id=16, kind="pour",
        points=_rect_points(-100, -100, 1100, 100),
    )
    result = PourShape(
        id="e-2", net="GND", layer_id=16, kind="poured", poured_from="e-1",
        points=_rect_points(-100, -100, 1100, 100),
        rings=[_rect_points(-100, -100, 1100, 100)],
    )
    board = _board([track], [region, result], ["USB_D+", "GND"])

    coverage = measure_track_coverage(board, track)
    assert coverage.breaks == []
    assert [run.pours for run in coverage.runs] == [frozenset({1})], (
        "the result (ordinal 1) is the copper; the superseded region is not"
    )
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


def test_the_projection_primitive_is_not_reused_for_the_verdict():
    """A diagonal split can leave all four corners outside while the middle is over copper.

    This is the reason 200B measures intervals instead of reading
    ``return_path_projection``'s corner mask: the corners of this trace's
    footprint are all outside the pour and the verdict here is still 「no
    defect」, because the copper under the line is continuous.
    """
    from boardwise.core.measure import return_path_projection

    track = _track("t13", (0, 0), (1000, 0), "USB_D+")
    # A diamond whose widest point is over the trace's middle only.
    diamond = [_point(500, -150), _point(900, 0), _point(500, 150), _point(100, 0)]
    board = _board([track], [_pour("p1", "GND", 16, diamond)], ["USB_D+", "GND"])

    projection = return_path_projection(board, "USB_D+").rows[0]
    assert projection.cover_status == "none", (
        "the corner mask cannot see this trace as covered"
    )
    coverage = measure_track_coverage(board, track)
    assert coverage.status == STATUS_MEASURED
    assert coverage.breaks == [], "but the line itself is over one continuous pour"
    assert coverage.runs[0].start == pytest.approx(0.1)
    assert coverage.runs[0].end == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# 4. registration
# ---------------------------------------------------------------------------


def test_the_rule_is_registered_last_with_its_identity():
    ids = [rule.id for rule in BUILTIN_PCB_RULES]

    # 200B appended after 182's inventory; **200C1 appended after 200B**, so the
    # split rule is no longer last — it is immediately before the via rule.
    # **200C2 appended its two pair rules after 200C1**, so 200B now sits three
    # places from the end; the family's order is still inventory → split → via →
    # pair, and this pin keeps saying so from 200B's side.
    assert ids[-4] == RULE_ID, "200C2 appends after this rule"
    assert ids[-5] == "pcb-hs-diffpair-inventory"
    assert ids[-3] == "pcb-hs-via-ground-companion"
    assert ids[-2:] == ["pcb-hs-diffpair-skew", "pcb-hs-diffpair-via-parity"]
    rule = {rule.id: rule for rule in BUILTIN_PCB_RULES}[RULE_ID]
    assert isinstance(rule, CrossSplit)
    assert rule.level == "L1-pcb-geometry"
    assert "200B" in rule.source and "可迭代" in rule.source


def test_an_empty_board_and_a_board_with_no_high_speed_net_are_silent():
    assert CrossSplit().check(PcbReviewContext(board=BoardGeometry())) == []
    board = _board([_track("t", (0, 0), (100, 0), "LED_A")], [], ["LED_A"])
    assert CrossSplit().check(PcbReviewContext(board=board)) == []


# ---------------------------------------------------------------------------
# 5. the real fixtures (read-only)
# ---------------------------------------------------------------------------


def _rows(path: Path) -> list:
    findings, _section = run_pcb_review(path)
    return [row for row in findings if row.rule_id == RULE_ID]


def test_the_foc_fixture_runs_the_rule_and_reports_only_measured_breaks():
    """毕设FOC 1.0.0: whatever the reading is, every row is a WARN with a coordinate."""
    rows = _rows(FOC_100)
    for row in rows:
        assert row.severity == "WARN"
        assert row.level == "L1-pcb-geometry"
        assert row.board == "PCB1"
        assert row.target.net_refs, "the net is kept as the target"
        assert any("@" in item and "mil" in item for item in row.evidence)
        assert "200B" in row.message

    findings, section = run_pcb_review(FOC_100)
    checks = section["boards"][0]["checksRun"]
    assert checks[-4] == RULE_ID and "pcb-hs-diffpair-inventory" in checks
    assert checks[-3] == "pcb-hs-via-ground-companion"
    assert checks[-2:] == ["pcb-hs-diffpair-skew", "pcb-hs-diffpair-via-parity"]


def test_the_kicad_fixture_is_a_coverage_limitation_not_a_positive_example():
    """kicad_hs has no zones: the rule must run and find nothing to measure.

    This is the fixture the task book names (``kicad_hs`` 必跑), and the
    assertion is deliberately about **the absence of a measurement**, not about
    the board being clean: the file carries no copper zones at all, so there is
    no ground pour on any reference layer for the rule to read.
    """
    from boardwise.parsers.kicad import read_kicad_board

    board = read_kicad_board(KICAD_HS_PCB)
    assert board.pours == [], "the fixture has no zones — that is the limitation"

    findings, section = run_pcb_review(KICAD_HS_PCB)
    assert [row for row in findings if row.rule_id == RULE_ID] == []
    assert RULE_ID in section["boards"][0]["checksRun"]
    assert section["rules_errored"] == []


def test_the_llc_fixture_runs_cleanly_and_files_only_warn_rows():
    """llc is the two-layer control: the rule runs, and anything it files is a WARN."""
    findings, section = run_pcb_review(LLC)
    rows = [row for row in findings if row.rule_id == RULE_ID]
    assert all(row.severity == "WARN" for row in rows)
    assert RULE_ID in section["boards"][0]["checksRun"]
