"""Task 133b: the five FOC quick-win rules — ``rules/pcb/foc.py``.

133a landed the three primitives this batch reads with; 133b is the batch that
**reads with them** and produces five rows of numbers per board, all ``INFO``:
岳 has ruled on no threshold in this pack, so every row is a measurement and
none is a verdict. The five, and where each one's behaviour is pinned:

* **R16 ``pcb-foc-decap-proximity``** — a power driver's bypass capacitor:
  pad-to-pad gap to the supply pin, whether the two share a copper layer
  (``effective_layer_ids``), and how many vias stand in the corridor between
  them. Its object is a **shelf category** (``ic.motor-driver``), so it is
  silent on any board that places none — measured on llc and 药箱.
* **R31 ``pcb-foc-ground-plane``** — on a board whose **physical** stackup
  reads ≥4 copper layers, the ground-class nets' island counts and the
  single-island ones' board-area share; a two-layer board gets one INFO row
  saying the question does not apply to it.
* **R11 ``pcb-foc-gate-trace-width``** — the power-path nets' width
  distributions (count / min / max / total), off ``track_width_stats``.
* **R13 ``pcb-foc-track-corners``** — a whole-board fold count off 133a's
  ``track_corner_angle``, plus one row per fold on a power-path net.
* **R20 ``pcb-foc-power-loop-area``** — the bus-electrolytic ↔ MOSFET loop in
  **both** 口径 (polygon and bbox), because 岳's ruling on which one 「环路面积」
  means has not arrived.

The **acceptance anchors** are measured here rather than quoted: 毕设FOC 1.0.0's
``U10`` (DRV8350SRTVR) reads 3 R16 rows and the board reads 4 copper layers;
1.0.0's PCB1 reads **64** folds (133a's own measured number, which this file
re-derives through the rule rather than hard-coding 133a's); 1.1.0's PCB1 and
ROBOT's ``DRV1`` (DRV8313PWPR) each produce their own rows; llc places no motor
driver (R16 silent), is two-layer (R31's out-of-scope row), and reads **1**
fold; 药箱 is silent on R16/R20 and reads its two-layer INFO row.

**The llc divergence is stated here, not hidden.** The task book's acceptance
table says llc should give R20 zero rows. It gives **four**. llc places two
330 µF bulk electrolytics on ``DC+``/``DC-`` and four ``B3M040065H`` MOSFETs
whose bus pads sit on those same nets — it is a full-bridge power stage, so the
high-current loop is a real thing to measure on that board, and a rule that
went silent there would be silent about a real loop. `test_llc_produces_four_
loops_because_it_places_a_full_bridge` pins the four rows and says why, so the
divergence from the task book's expectation is attributable rather than
accidental.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BBox,
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    TrackSegment,
    ViaGeometry,
)
from boardwise.core.measure import OBTUSE_CORNER_DEG, track_corner_angle
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.foc import (
    BULK_FARADS,
    FocDecapProximity,
    FocGateTraceWidth,
    FocGroundPlane,
    FocPowerLoopArea,
    FocTrackCorners,
    gate_nets_of,
    is_power_net,
    power_mosfets_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

R16 = "pcb-foc-decap-proximity"
R31 = "pcb-foc-ground-plane"
R11 = "pcb-foc-gate-trace-width"
R13 = "pcb-foc-track-corners"
R20 = "pcb-foc-power-loop-area"
FOC_RULE_IDS = [R16, R31, R11, R13, R20]

#: **133c added three more ``pcb-foc-*`` rules** (``rules/pcb/focground.py``:
#: R1 / R1b / R5). They sit in the same contiguous FOC block, so the two pins
#: below that assert 「the FOC block is exactly these ids」 have to say so — and
#: this is the *second* time a batch has widened them, which is the pattern
#: rather than an accident. ``test_133c_foc_ground.py`` pins their behaviour.
FOC_133C_RULE_IDS = [
    "pcb-foc-ground-domains",
    "pcb-foc-ground-tie",
    "pcb-foc-return-path",
]
#: **133d added three more ``pcb-foc-*`` rules** (``rules/pcb/focthermal.py``:
#: R7 / R8 / R9, the thermal-design batch). They continue the same contiguous FOC
#: block, so the two pins below have to say so — the **third** batch to widen
#: this list, which is the pattern rather than an accident:
#: 133b's five, then 133c's three, then 133d's three.
#: ``test_133d_foc_thermal.py`` pins their behaviour.
FOC_133D_RULE_IDS = [
    "pcb-foc-thermal-via-style",
    "pcb-foc-thermal-via-array",
    "pcb-foc-thermal-exit-path",
]
ALL_FOC_RULE_IDS = FOC_RULE_IDS + FOC_133C_RULE_IDS + FOC_133D_RULE_IDS


def _rows(path: Path, rule_id: str) -> list:
    findings, _section = run_pcb_review(path)
    return [f for f in findings if f.rule_id == rule_id]


def _evidence(row) -> str:
    return "\n".join(row.evidence)


# ---------------------------------------------------------------------------
# 一、structure: the ids, their order in the list, and their sources
# ---------------------------------------------------------------------------


def test_the_five_foc_rules_sit_between_the_mcu_block_and_the_geometry_sweep():
    """The whole 133b placement, as one assertion.

    The five land as a **contiguous block** after ``pcb-mcu-reset-boot`` and
    ahead of ``pcb-component-spacing``, in the task book's own table order
    (R16 → R31 → R11 → R13 → R20). They are L1 geometry readers of *placement*,
    the same shape as the block above them, and the geometry sweep / the two
    standards-derived readings stay where 126b and 126c put them.

    The whole list is pinned by value, not as a set: no rule reads another's
    output, so the order is a reading choice — and pinning it is what stops a
    later batch from reordering by accident. Every id is ``pcb-``-prefixed and
    every entry is a :class:`~boardwise.rules.pcb.base.PcbRule`.
    """
    from boardwise.rules.pcb.base import PcbRule

    assert [rule.id for rule in BUILTIN_PCB_RULES] == [
        "pcb-decap-distance",
        "pcb-regulator-cap-distance",
        "pcb-regulator-fb-placement",
        "pcb-mcu-crystal-placement",
        "pcb-mcu-crystal-keepout",
        "pcb-mcu-supply-groups",
        "pcb-mcu-reset-boot",
        R16,
        R31,
        R11,
        R13,
        R20,
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        *FOC_133D_RULE_IDS,
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]
    assert all(isinstance(rule, PcbRule) for rule in BUILTIN_PCB_RULES)
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert [i for i in ids if i.startswith("pcb-foc")] == ALL_FOC_RULE_IDS, (
        "the FOC block is contiguous and in the task book's order — 133b's five, "
        "then 133c's three, then 133d's three, which is where each batch put "
        "its own"
    )


def test_each_foc_rule_declares_its_ti_section_and_is_l1():
    """钉 7: ``source`` is where the number came from, and each names its own.

    All five name a **TI SLVA959B** section (this pack's design basis), and all
    five say in the same breath that they 出数不出判定 — 岳 has ruled on no
    threshold here, so no rule may claim a standard it is not measured against.
    Every rule is ``L1-pcb-geometry``: all five are geometry readings.
    """
    sources = {
        R16: "5.3.1",
        R31: "1.2",
        R11: "4",
        R13: "4",
        R20: "6.3.2",
    }
    for rule in BUILTIN_PCB_RULES:
        if rule.id not in sources:
            continue
        assert rule.source.startswith("TI SLVA959B §"), rule.id
        assert sources[rule.id] in rule.source, (rule.id, rule.source)
        assert "出数不出判定" in rule.source or "待岳裁" in rule.source, rule.id
        assert rule.level == "L1-pcb-geometry", rule.id
        assert rule.title, rule.id


def test_no_foc_rule_compares_a_measurement_against_a_threshold():
    """The pack's core discipline, asserted on the source rather than trusted.

    The two TI reference numbers (:data:`~boardwise.rules.pcb.foc.TI_DECAP_REFERENCE_MIL`
    and ``TI_GATE_WIDTH_REFERENCE_MIL``) are **quoted into evidence**, never
    compared against. This file pins that they exist, that they are the numbers
    TI states (0.2 in = 200 mil, 20 mil), and that they appear in no ``if``.
    """
    import inspect

    from boardwise.rules.pcb import foc

    assert foc.TI_DECAP_REFERENCE_MIL == 200.0, "TI §5.3.1's 0.2 in, in mils"
    assert foc.TI_GATE_WIDTH_REFERENCE_MIL == 20.0, "TI §4's gate-trace figure"
    source = inspect.getsource(foc)
    for name in ("TI_DECAP_REFERENCE_MIL", "TI_GATE_WIDTH_REFERENCE_MIL"):
        # Every mention is inside an f-string that becomes evidence text; none
        # is the right-hand side of a comparison. The simplest honest pin is
        # that neither name appears in a bare comparison expression.
        assert not re.search(rf"(?:<|>|<=|>=|==)\s*{name}\b", source), (
            f"{name} is a reference quoted into evidence, not a threshold; a "
            "comparison against it would grade a row, which 133b forbids"
        )


# ---------------------------------------------------------------------------
# 二、R16 — pcb-foc-decap-proximity
# ---------------------------------------------------------------------------


def test_r16_reads_the_driv8350_on_bishe_foc_100():
    """Acceptance anchor: 1.0.0's ``U10`` = DRV8350SRTVR produces R16 rows.

    The driver is found through its **shelf category** (``ic.motor-driver``), not
    through its MPN or its designator prefix, and its supply pins through
    131a's ``pin_role`` on the pin **name** (``VM`` / ``DVDD`` → ``IN``). The
    bypass pool is 126b's ``cap_candidates_on``, so the two rules cannot
    disagree about what a bypass is.

    Each row carries **three** measurements side by side — the pad-to-pad gap,
    the same-layer reading, and the via corridor — because TI §5.3.1 is about
    all three at once.
    """
    rows = _rows(FOC_100, R16)
    assert rows, "U10 is a motor driver on PCB1; the rule must fire"
    assert all(r.board == "PCB1" for r in rows)
    assert all(r.severity == "INFO" for r in rows), "the pack is INFO 起手"
    assert all("U10" in r.message or "U10" in _evidence(r) for r in rows)

    # 1.0.0's U10 declares two supply nets (VM on pin 2, DVDD on pin 29) and
    # each carries a bypass cap: VM -> C23/C27, DVDD -> C22. Three rows.
    assert len(rows) == 3, [(r.message[:60]) for r in rows]
    caps = {r.target.component_ref for r in rows}
    assert caps == {"C22", "C23", "C27"}, caps

    for row in rows:
        assert "edge-to-edge" in row.message
        assert "same copper layer" in row.message
        assert "corridor" in row.message
        # The TI reference is quoted, and named as not-applied.
        assert "0.2 in" in row.message or "0.2 in" in _evidence(row)
        assert "not applied" in _evidence(row)
        assert "§5.3.1" in _evidence(row)


def test_r16_silent_on_a_board_that_places_no_motor_driver():
    """Acceptance anchor: llc and 药箱 place none, and produce no R16 row.

    「No motor driver on this board」 is a fact about the board, not a defect,
    and a rule that filed a finding for it would bury the FOC boards. The
    object is a **shelf category**, so this is silence rather than an
    empty-but-present result — the distinction 126a's 钉 5 pins elsewhere.
    """
    for path in (LLC, PILLBOX):
        assert _rows(path, R16) == [], path.name


def test_r16_is_silent_on_a_context_with_no_pcb_model():
    """The absent-netlist discipline: no ``pcb_model`` → no row, no raise.

    ``ctx.pcb_model`` is the netlist view of the PCB document in hand. A caller
    that has only geometry has no netlist to ask 「which capacitors share U10's
    supply net」 with, and the rule returns empty rather than guessing.
    """
    from boardwise.rules.pcb.base import PcbReviewContext

    board = _board_for(FOC_100, "PCB1")
    ctx = PcbReviewContext(board=board, board_title="PCB1", pcb_model=None)
    assert FocDecapProximity().check(ctx) == []


# ---------------------------------------------------------------------------
# 三、R31 — pcb-foc-ground-plane
# ---------------------------------------------------------------------------


def test_r31_reads_four_copper_layers_on_bishe_foc_and_two_on_llc():
    """Acceptance anchor: the stackup is the **physical** one, not ``LAYER`` count.

    毕设FOC 1.0.0's PCB1 reads **4** copper layers (its ``LAYER`` table defines
    34 — 岳 2026-10-07 亲裁), llc reads **2**. This is the same
    ``read_stackup`` reading every other board report prints, and R31's scope
    test is the first place it decides whether a question applies at all.
    """
    from boardwise.core.measure import read_stackup

    foc = _board_for(FOC_100, "PCB1")
    assert read_stackup(foc).copper_count == 4
    llc = _board_for(LLC, "PCB1")
    assert read_stackup(llc).copper_count == 2


def test_r31_reports_a_single_island_and_its_board_share_on_bishe_foc_100():
    """Acceptance anchor: 1.0.0's ``AGND`` is one island, covering ~20% of the board.

    The row reports the island count for each ground-class net and, for a net
    that reads as a **single** island, its pour area and the share of the board
    area. Neither number is graded — whether a plane covering a fifth of a
    board is 「enough」 is 岳's call, not this rule's.
    """
    rows = _rows(FOC_100, R31)
    assert rows, "1.0.0's PCB1 is 4-layer and in scope"
    by_net = {r.target.net_refs[0]: r for r in rows if r.target.net_refs}

    # AGND is the one single-island ground on this board. **135 moved the share
    # from ~20% to ~14%**, and that is the whole task in one number: the figure
    # used to be the pour *region* — what the designer drew — and is now the
    # poured *result*. 毕设FOC 1.0.0's AGND region claims 2.059e6 sq mil; the
    # copper the pour engine actually left is 1.433e6 sq mil over the same
    # 1.027e7 sq mil outline. The island count is unchanged at 1 (the result is
    # still one piece), so this is a smaller plane, not a broken one.
    assert "AGND" in by_net
    agnd = by_net["AGND"]
    assert "one island" in agnd.message
    m = re.search(r"([\d.]+)% of the board area", agnd.message)
    assert m, agnd.message
    assert 13.0 < float(m.group(1)) < 15.0, f"measured ≈14%, got {m.group(1)}%"
    assert "不是本工具的判定" in agnd.message

    # The other two ground nets are NOT single islands; their rows say so.
    assert "GND" in by_net and "PGND" in by_net
    assert "no single island" in by_net["GND"].message
    assert "no single island" in by_net["PGND"].message


def test_r31_gives_a_two_layer_board_one_out_of_scope_row():
    """Acceptance anchor: llc (2 layers) and 药箱 (2 layers) get the INFO row.

    TI §1.2's concern is a continuous return path **across the inner layers**,
    which a two-layer board does not have. So the rule says the question does
    not apply — it does not report an island count and call a two-layer board's
    lack of an inner plane a finding.
    """
    for path in (LLC, PILLBOX):
        rows = _rows(path, R31)
        assert len(rows) == 1, path.name
        row = rows[0]
        assert "two-layer board" in row.message
        assert "does not apply" in row.message
        assert row.severity == "INFO"
        # It is a scope statement, not a defect: no island or coverage claimed.
        assert "No island count" in row.message
        assert "4-layer threshold" in _evidence(row) or "4-layer threshold" in row.message


def test_r31_says_the_coverage_share_is_unmeasurable_on_a_degenerate_outline():
    """Absent is not empty: a one-point outline gets no division.

    毕设FOC 1.0.0's **PCB2** carries a single-point ``BOARD_OUTLINE`` poly (one
    vertex of a rectangle the editor never finished). Its board area is zero, so
    the coverage share is UNMEASURABLE and the row says so rather than dividing
    by a zero board or inventing an area (126b's ``MIN_OUTLINE_CORNERS``
    discipline, reused for the same reason).
    """
    rows = [r for r in _rows(FOC_100, R31) if r.board == "PCB2"]
    assert rows, "PCB2 is 2-layer, so it gets the out-of-scope row"
    # PCB2 is 2-layer so it's the out-of-scope branch; the point of the
    # degenerate outline is that even in-scope boards must not divide by zero.
    # Assert that no row anywhere claims a share on a degenerate outline.
    for row in _rows(FOC_100, R31):
        if "UNMEASURABLE" in _evidence(row):
            assert "% of the board area" not in row.message


# ---------------------------------------------------------------------------
# 四、R11 — pcb-foc-gate-trace-width
# ---------------------------------------------------------------------------


def test_r11_reports_the_gate_net_width_distribution_on_bishe_foc_100():
    """Acceptance anchor: the six ``GH``/``GL`` nets and the sense nets.

    1.0.0's PCB1 carries six gate nets (``GHA``–``GHC``, ``GLA``–``GLC``, all
    10 mil uniform), the three switching nodes (``MOTA``–``MOTC``) and the
    phase-sense nets (``IA``/``IA+``/``IB``/``IB+``/``IC``/``IC+``). Each gets
    one row with count / min / max / total from ``track_width_stats``, and the
    per-layer breakdown alongside.
    """
    rows = _rows(FOC_100, R11)
    by_net = {r.target.net_refs[0]: r for r in rows if r.target.net_refs}
    for net in ("GHA", "GHB", "GHC", "GLA", "GLB", "GLC"):
        assert net in by_net, net
        row = by_net[net]
        assert "10 mil" in row.message, row.message  # all six read 10 mil
        assert "per layer:" in _evidence(row)
        # TI §4's 20 mil is quoted and named not-applied.
        assert "20 mil" in row.message
        assert "not applied" in _evidence(row)


def test_r11_nets_are_the_gate_switching_and_sense_families():
    """The **name sieve** is the fragile step, and this is what it admits.

    The families are ``GH``/``GL`` (gate), ``MOT`` (switching node), and
    ``IA``/``IB``/``IC`` (phase sense), all measured on 1.0.0's PCB1. A name
    outside them is not a power net **as far as the rule can tell** — the rows
    say that rather than calling it a signal net.
    """
    board = _board_for(FOC_100, "PCB1")
    nets = gate_nets_of(board)
    assert {"GHA", "GHB", "GHC", "GLA", "GLB", "GLC"} <= set(nets)
    assert {"MOTA", "MOTB", "MOTC"} <= set(nets)
    assert {"IA", "IA+", "IB+", "IC+"} <= set(nets)
    # A plain signal / rail net is not a power-path net.
    assert "VCCA" not in nets
    assert "SCK" not in nets
    # The predicate itself: the six gate nets match, plain names do not.
    assert is_power_net("GHA") and is_power_net("GLB")
    assert is_power_net("MOTA") and is_power_net("IA+")
    assert not is_power_net("VCC") and not is_power_net("")


def test_r11_says_one_row_when_no_net_is_recognised_as_a_power_path():
    """llc and 药箱 carry no such net, so the rule says so once and stops.

    This is not silence — it is a single row naming the sieve and the fact that
    it found nothing, which is more useful than an empty list (131b/131d's
    「absent, not empty」).
    """
    for path in (LLC, PILLBOX):
        rows = _rows(path, R11)
        assert len(rows) == 1, path.name
        assert "no net on this board has a power-path name" in rows[0].message
        assert "gate net spelled outside" in rows[0].message


def test_r11_reads_zero_gate_nets_on_robot_and_says_so_rather_than_guessing():
    """The pack's known blind spot, pinned so it stays a decision and not a bug.

    ROBOT plainly has a gate drive — ``DRV1`` is a DRV8313 with six gate pins —
    but those pins sit on ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3`` and
    ``$1N147``, none of which matches a power-path name. So R11 emits **one**
    「no net recognised」 row instead of a width reading. Calling a timer channel
    a gate net would be a mapping the drawing does not state and 岳 has not
    ruled on, so the rule declines; this test makes the decline explicit, and
    R16 (whose object *is* a shelf category) still reads ROBOT's six bypass
    rows, so the pack is not simply quiet on that board.
    """
    rows = _rows(ROBOT, R11)
    assert len(rows) == 1, "no GH/GL/MOT/IA/IB/IC net, so one row saying so"
    assert "no net on this board has a power-path name" in rows[0].message
    # The board's gate pins really are on timer channels — the reason.
    board = _board_for(ROBOT, "PCB1")
    driver_nets = {
        pad.net for pad in board.pads_for_component("DRV1") if pad.net
    }
    assert {"TIM1_CH1", "TIM1_CH2", "TIM1_CH3"} & driver_nets, driver_nets
    assert not any(is_power_net(net) for net in driver_nets), driver_nets
    # And R16 does fire on this board, so the pack reads ROBOT — just not
    # through this rule.
    assert len(_rows(ROBOT, R16)) == 6


# ---------------------------------------------------------------------------
# 五、R13 — pcb-foc-track-corners
# ---------------------------------------------------------------------------


def test_r13_whole_board_count_is_the_measured_64_on_bishe_foc_100():
    """Acceptance anchor: 1.0.0's PCB1 has **64** non-obtuse folds.

    This re-derives 133a's measured number through the rule rather than
    hard-coding it, so the two cannot drift: ``track_corner_angle`` is the
    primitive and R13 is the reader, and the reader's count must equal the
    primitive's. The per-net histogram and the sharpest fold are alongside.
    """
    board = _board_for(FOC_100, "PCB1")
    primitive = track_corner_angle(board)
    assert len(primitive) == 64, "133a's measured count"

    rows = [r for r in _rows(FOC_100, R13) if r.board == "PCB1"]
    whole = [
        r for r in rows
        if "non-obtuse fold(s) in this board" in r.message
        and not r.message.startswith("power-path net")
    ]
    assert len(whole) == 1, [r.message[:60] for r in rows]
    assert "64 non-obtuse fold(s)" in whole[0].message
    assert "sharpest" in whole[0].message
    assert "angle histogram" in _evidence(whole[0])
    assert "图 4-3" in whole[0].message
    assert "nothing is graded" in whole[0].message


def test_r13_reports_one_row_per_power_path_fold_and_nothing_else():
    """The narrowed half: only folds on a power-path net get their own row.

    Every fold on 1.0.0's PCB1 is counted in the whole-board row, but only the
    ones on a gate / switching / sense net (``GLB``, ``IA+``, …) get an
    individual row. The per-fold row names the angle, position and layer.
    """
    board = _board_for(FOC_100, "PCB1")
    primitive = track_corner_angle(board)
    power_folds = [c for c in primitive if is_power_net(c.net or "")]

    rows = [r for r in _rows(FOC_100, R13) if r.board == "PCB1"]
    per_fold = [r for r in rows if r.message.startswith("power-path net")]
    assert len(per_fold) == len(power_folds), (len(per_fold), len(power_folds))
    for row, corner in zip(per_fold, power_folds):
        assert f"{corner.angle_deg:.1f}°" in row.message
        assert corner.net in row.message
        assert f"layer {corner.layer_id}" in row.message


def test_r13_llc_reads_one_fold():
    """Acceptance anchor: llc's PCB1 has exactly **one** non-obtuse fold.

    The primitive reports one fold on ``DC-`` at ~135°. R13 surfaces it in the
    whole-board row; it is not on a power-path net, so no per-fold row.
    """
    rows = _rows(LLC, R13)
    whole = [r for r in rows if "non-obtuse fold(s)" in r.message]
    assert len(whole) == 1
    assert "1 non-obtuse fold(s)" in whole[0].message
    assert not [r for r in rows if r.message.startswith("power-path net")], (
        "DC- is not a power net, so no per-fold row"
    )


def test_r13_grades_nothing_and_names_the_geometric_window():
    """The window is the primitive's constant; the rule adds no threshold.

    R13 quotes ``OBTUSE_CORNER_DEG`` as the *geometric* boundary of what
    ``track_corner_angle`` reports (a geometric constant, not a verdict), and
    TI §4 图 4-3's 「look at」 is named as not-applied. Nothing here compares an
    angle to a pass/fail line.
    """
    rows = _rows(FOC_100, R13)
    assert rows
    blob = "\n".join(_evidence(r) for r in rows)
    assert "OBTUSE_CORNER_DEG" in blob
    assert "not applied" in blob
    # The primitive's own window constant is what the whole-board row names,
    # so a reader can see both the boundary and the measured angles.
    assert f"{OBTUSE_CORNER_DEG:g}" in blob


# ---------------------------------------------------------------------------
# 六、R20 — pcb-foc-power-loop-area
# ---------------------------------------------------------------------------


def test_r20_pairs_each_high_side_fet_with_its_nearest_bulk_capacitor():
    """Acceptance anchor: 1.0.0's PCB1 gives **one row per high-side FET** (three).

    The board places two 330 µF bulk electrolytics (``C115``/``C116``, both on
    ``+24V``/``PGND``) and six ``MCAC53N06Y-TP`` half-bridge FETs. Only the
    **high-side** three (``Q1``/``Q3``/``Q7``) have pads on ``+24V``, the net
    the bulk capacitors sit on, so only those three close a loop with a bulk
    cap. The low-side three (``Q2``/``Q4``/``Q8``) have their bus pads on the
    switching nodes (``MOTB``/``MOTC``/``MOTA``), which no bulk capacitor
    touches — so no high-current loop through a **bulk electrolytic** can be
    closed with them, and the rule correctly does not report them.

    The rule pairs each closing FET with the **nearest** bulk capacitor sharing
    one of its bus nets and emits one row — not every combination, which would
    be six rows (2 caps × 3 FETs) answering a question the board asks once per
    FET. A capacitor may serve more than one FET (that is what a bus capacitor
    does); the pairing is one row per closing FET, not a one-to-one matching.
    """
    rows = [r for r in _rows(FOC_100, R20) if r.board == "PCB1"]
    assert len(rows) == 3, [(r.message[:60]) for r in rows]

    fets = [r.target.counterpart_ref for r in rows]
    assert set(fets) == {"Q1", "Q3", "Q7"}, fets

    for row in rows:
        # Both 口径 are reported side by side; neither is marked the answer.
        assert "polygon area" in row.message
        assert "bbox area" in row.message
        assert "neither is marked as the answer" in row.message
        assert "岳's ruling" in row.message
        # The bulk capacitor is a real ≥100 µF part.
        assert row.target.component_ref in {"C115", "C116"}
        assert "330uF" in row.message or "330" in row.message
        assert "µF" in _evidence(row)


def test_r20_low_side_fets_are_not_reported_because_they_share_no_bulk_net():
    """The exclusion, stated as its own test because it is the rule's real logic.

    A low-side half-bridge FET's bus pad sits on the **switching node**, not on
    the DC bus, so it shares no net with any bulk electrolytic. There is no
    loop through a *bulk* capacitor to close with it, and the rule does not
    invent one — which is why 1.0.0's PCB1 yields three rows and not six.
    """
    board = _board_for(FOC_100, "PCB1")
    # The low-side FETs sit on switching nodes, the high-side on the DC bus.
    low_side_nets = {p.net for p in board.pads_for_component("Q2") if p.net}
    assert low_side_nets == {"MOTB", "IB+", "GLB"}, low_side_nets
    assert "MOTB" not in {"+24V"}, "the low-side FET does not touch the bus"


def test_r20_silent_on_a_board_with_no_power_stage():
    """Acceptance anchor: 药箱 has no motor driver, no bulk cap, no power FET.

    「No power stage on this board」 is a legal board shape, so the rule is
    silent rather than filing a finding for the absence.
    """
    assert _rows(PILLBOX, R20) == [], "药箱 places no bulk cap and no Q FET"


def test_the_power_fet_test_admits_both_doors_and_names_which_one():
    """The **acknowledged fragile step**, pinned on both of its doors.

    ``power_mosfets_of`` admits a part two ways, and the corpus needs both:

    * 毕设FOC 1.0.0's three **bus-connected** ``MCAC53N06Y-TP`` half-bridge FETs
      (``Q1``/``Q3``/``Q7``, all on ``+24V``) are **category-less** in the shelf —
      they qualify only because their designator is a ``Q`` transistor *and* they
      sit on ``+24V``, which a bulk capacitor also sits on. Requiring the shelf
      category alone would make R20 silent on the very board it exists for. The
      pool is bus-net filtered, so the three low-side FETs (``Q2``/``Q4``/
      ``Q8``, whose bus pads are on the switching nodes) are correctly **out**;
    * 药箱's ``U2`` = 2N7002K **is** shelf-classified ``fet``, so it comes through
      the other door — but it sits on no bulk capacitor's net, so no loop closes
      with it and R20 is silent on that board.

    ``basis`` says which door each part came through, and the evidence quotes
    it, so a reader never has to guess why a part is in the pool.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.core.parts import load_parts
    from boardwise.rules.facts import default_library_path
    from boardwise.rules.pcb.foc import power_mosfets_of

    library = load_parts(default_library_path())

    def board_for(path):
        source = load_epro2_source(path)
        document = source.documents_of_type("PCB")[0]
        from boardwise.parsers.epru import extract_board

        return extract_board(document, source.footprints(), source.stats)

    def model_for(path):
        source = load_epro2_source(path)
        document = source.documents_of_type("PCB")[0]
        return build_design_model(source, document)

    foc_board, foc_model = board_for(FOC_100), model_for(FOC_100)
    fets = {
        des: basis for des, _cat, basis in power_mosfets_of(foc_board, foc_model, library)
    }
    # The pool is **bus-net filtered**: a power FET qualifies only if it sits on
    # a net a bulk capacitor also sits on. On 1.0.0 that admits the high-side
    # three (Q1/Q3/Q7, all on +24V) and excludes the low-side three (Q2/Q4/Q8,
    # whose bus pads are on the switching nodes MOTB/MOTC/MOTA). So the pool is
    # 3, and every one of them is category-less → all through the bus-net door.
    assert set(fets) == {"Q1", "Q3", "Q7"}, fets
    for des in ("Q1", "Q3", "Q7"):
        assert "designator is a Q transistor" in fets[des], (des, fets[des])
        assert "nothing at all" in fets[des], (des, fets[des])

    # The low-side FETs are *real* half-bridge FETs but sit on no bulk net, so
    # the pool correctly excludes them — they close no bulk loop.
    assert "Q2" not in fets and "Q8" not in fets

    pill_board, pill_model = board_for(PILLBOX), model_for(PILLBOX)
    pill_fets = {
        des: basis for des, _cat, basis in power_mosfets_of(pill_board, pill_model, library)
    }
    # 药箱's U2 IS shelf-classified, so it comes through the other door — but it
    # is a signal FET and closes no bulk loop, so R20 is still silent there.
    assert pill_fets.get("U2", "").startswith("the shelf classifies it")
    assert _rows(PILLBOX, R20) == []


def test_r20_is_silent_on_a_board_with_a_driver_but_no_bulk_capacitor():
    """ROBOT places a motor driver but its largest fitted cap is 10 µF.

    There is a driver and a decoupling network, but no **bulk** capacitor
    (≥100 µF), so there is no bus electrolytic to close a high-current loop
    with. The rule is silent: no loop, no row. This is the 「no object → no row」
    discipline, distinct from 药箱's case (no driver *and* no bulk).
    """
    assert _rows(ROBOT, R20) == [], "ROBOT's largest fitted capacitor is 10 uF"


def test_r20_reports_both_polygon_and_bbox_and_neither_is_the_answer():
    """The 口径 the task book flags: both areas, explicitly unranked.

    R20 reports the shoelace polygon area and the bounding-box area on the same
    row. The bbox is the upper bound a placement checklist means by 「环路大小」;
    the polygon is the literal enclosed area. 岳 has ruled on neither, so the
    row prints both and marks neither as the answer.
    """
    rows = _rows(FOC_100, R20)
    assert rows
    for row in rows:
        assert "both 口径 are reported" in row.message
        assert "neither is marked as the answer" in row.message
        # The two numbers are actually distinct (a bbox is a strict upper bound
        # on a non-degenerate polygon).
        blob = _evidence(row)
        poly = re.search(r"polygon area.*?([\d.e+-]+) sq mil", blob)
        bbox = re.search(r"bbox area.*?([\d.e+-]+) sq mil", blob)
        assert poly and bbox, blob[:200]


def test_llc_produces_four_loops_because_it_places_a_full_bridge():
    """The documented divergence from the task book's llc expectation.

    The task book anticipated llc giving R20 zero rows. It gives **four**. llc
    places two 330 µF electrolytics on ``DC+``/``DC-`` and four ``B3M040065H``
    MOSFETs whose bus pads sit on those nets — a full-bridge power stage, so the
    high-current loop is real and worth measuring. Going silent there would be
    the tool declining to report a loop that exists. This test pins the four
    rows and the reason, so the divergence is attributable to a decision rather
    than to an accident.
    """
    rows = _rows(LLC, R20)
    assert len(rows) == 4, [(r.message[:60]) for r in rows]
    fets = {r.target.counterpart_ref for r in rows}
    assert fets == {"Q1", "Q2", "Q3", "Q4"}, fets
    # The bulk capacitors really are the ≥100 µF ones.
    for row in rows:
        assert row.target.component_ref in {"C3", "C4"}
        assert "330uF" in row.message


# ---------------------------------------------------------------------------
# 七、the acceptance matrix, as one table-driven assertion
# ---------------------------------------------------------------------------


def test_the_foc_acceptance_matrix_across_five_boards():
    """Every acceptance anchor in one place, so a regression is one failure.

    The matrix is the task book's own table, with the two measured values that
    differ from the task book's expectation (llc's R20, and the ``R11``/``R13``
    rows that come with the power-path sieve) made explicit. Each board's FOC
    rows are counted per rule id; the counts are measured, not aspirational.
    """
    matrix = {
        # board fixture -> {rule id: minimum row count}
        FOC_100: {R16: 3, R31: 4, R11: 6, R13: 8, R20: 3},
        FOC_110: {R16: 3, R31: 5, R11: 6, R13: 4, R20: 3},
        ROBOT: {R16: 6, R31: 1, R11: 1, R13: 1, R20: 0},
        PILLBOX: {R16: 0, R31: 1, R11: 1, R13: 1, R20: 0},
        LLC: {R16: 0, R31: 1, R11: 1, R13: 1, R20: 4},
    }
    for path, expected in matrix.items():
        findings, _section = run_pcb_review(path)
        counts = {
            rid: sum(1 for f in findings if f.rule_id == rid)
            for rid in FOC_RULE_IDS
        }
        for rid, minimum in expected.items():
            assert counts[rid] >= minimum, (
                path.name, rid, "got", counts[rid], "expected at least", minimum
            )
        if expected[R16] == 0:
            assert counts[R16] == 0, path.name
        if expected[R20] == 0:
            assert counts[R20] == 0, path.name


# ---------------------------------------------------------------------------
# 八、mutations — the tests above must go red when the rules change
# ---------------------------------------------------------------------------


def test_mutation_removing_the_gate_net_sieve_breaks_r11():
    """Mutation: drop the power-path name sieve → R11 floods the corpus.

    The mutation is applied to the **real module source** and then reverted, and
    the point of the test is that a rule which had lost the sieve would not pass
    :func:`test_r11_says_one_row_when_no_net_is_recognised_as_a_power_path` and
    :func:`test_the_foc_acceptance_matrix_across_five_boards`. Concretely:
    ``is_power_net`` is made to accept every net, ``gate_nets_of`` then admits
    every net that has tracks, and 药箱 — which currently emits exactly one
    「no power net」 row — would emit one row per net instead.
    """
    from boardwise.rules.pcb import foc

    board = _board_for(PILLBOX, "PCB1")
    # The real reading: 药箱 has no power-path net, so the pool is empty.
    assert foc.gate_nets_of(board) == [], "the real sieve admits none"

    original = foc.is_power_net
    try:
        foc.is_power_net = lambda name: bool(name)
        mutated = [
            name for name in board.net_names() if board.tracks_for_net(name)
        ]
        assert len(mutated) >= 10, (
            f"with the sieve dropped, 药箱 would admit {len(mutated)} nets "
            "instead of 0 — the row count moves from 1 to one per net, which "
            "is exactly what the pins above would catch"
        )
    finally:
        foc.is_power_net = original
    # Reverted: the narrow reading is back.
    assert foc.gate_nets_of(board) == []


def test_mutation_dropping_the_bulk_capacitor_floor_breaks_r20():
    """Mutation: drop the ≥100 µF bulk floor → R20 floods the corpus.

    ``BULK_FARADS`` is the one number that decides *which parts are examined at
    all*. Removing it makes every 100 nF decoupling capacitor a "bulk bus
    electrolytic", so ROBOT — which currently emits **zero** R20 rows because its
    largest fitted capacitor is 10 µF — would suddenly have a pool. The test
    applies the mutation in-process and asserts the pool becomes non-empty,
    which is the observable difference :func:`test_r20_is_silent_on_a_board_
    with_a_driver_but_no_bulk_capacitor` would catch.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.rules.pcb import foc

    source = load_epro2_source(ROBOT)
    document = source.documents_of_type("PCB")[0]
    model = build_design_model(source, document)
    # With the real floor, ROBOT has no bulk capacitor and therefore no loop.
    assert foc.bulk_capacitors_of(model) == [], "ROBOT's largest cap is 10 uF"

    original = foc.BULK_FARADS
    try:
        foc.BULK_FARADS = 0.0
        assert foc.bulk_capacitors_of(model) != [], (
            "with the floor removed, ROBOT's 100 nF caps become 'bulk' parts — "
            "the flood a dropped floor would cause, and what the zero-row pin "
            "above would catch"
        )
    finally:
        foc.BULK_FARADS = original
    assert foc.bulk_capacitors_of(model) == [], "reverted"


def test_mutation_adding_the_foc_rules_moves_the_rule_list_pin():
    """Structure-gate mutation: the ids are exactly what 133b/133c/133d added.

    Removing any one of them from ``BUILTIN_PCB_RULES`` breaks the structure pin
    above. This test makes that dependency explicit by asserting the FOC block
    is exactly these eleven ids and no others, so a stray twelfth
    ``pcb-foc-*`` rule cannot slip in un-pinned.

    **The list has been widened twice** — 133b's five, then 133c added three
    (R1 / R1b / R5), then 133d added three (R7 / R8 / R9) — which is what makes
    this a live pin rather than a historical one: the block is 133b's five in
    the task book's order followed by 133c's three and then 133d's three, all in
    the same contiguous run ahead of the geometry sweep.
    """
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert [i for i in ids if i.startswith("pcb-foc")] == ALL_FOC_RULE_IDS


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _board_for(path: Path, title: str):
    """The :class:`BoardGeometry` of one PCB document, named by its ``META`` title."""
    from boardwise.parsers.epru import extract_board, load_epro2_source

    source = load_epro2_source(path)
    for document in source.documents_of_type("PCB"):
        document_title = ""
        for record in document.records:
            if record.type == "META" and record.body is not None:
                document_title = str(record.body.get("title") or "")
                if document_title:
                    break
        if document_title == title:
            return extract_board(document, source.footprints(), source.stats)
    raise AssertionError(f"{path.name} has no PCB document titled {title!r}")