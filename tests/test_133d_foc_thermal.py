"""Task 133d: the three FOC thermal-design rules — ``rules/pcb/focthermal.py``.

133a landed the ``via_geometry`` queries, 133b the five quick wins, 133c the
ground system; 133d reads the **thermal design** of a power driver's exposed
pad. Three rules, all ``INFO``:

* **R7 ``pcb-foc-thermal-via-style``** — the vias standing in the pad's
  projection, with each one's layer span (so a via that does not reach every
  copper layer shows up as an abnormal *form*), plus the two clauses the model
  cannot read, reported UNKNOWN with the reason.
* **R8 ``pcb-foc-thermal-via-array``** — the count, the hole/pad-diameter
  distribution against TI's reference figures (8 mil / 20 mil, quoted and
  **not applied**), and the pitch distribution.
* **R9 ``pcb-foc-thermal-exit-path``** — the pad's projection inventoried by
  ``region_copper``, then the island that owns the pad (and, separately, the
  islands that own its vias), with island area and layer span.

**The three measured answers the task book asks for.**

* **The EP pad is identifiable, and by shape.** 毕设FOC 1.0.0's ``U10``
  (DRV8350SRTVR, WQFN-32): pad ``e9`` / pin 33, net ``GND``, **126 × 126 mil
  = 15 876 sq mil** against the next-largest pad's **339** — a **46.8×**
  ratio. The 1.1.0 board's ``U2`` is identical. ROBOT's ``DRV1`` (DRV8313PWPR,
  HTSSOP-28): pin 29, 244.094 × 108.268 = **26 428** against 920.6 — **28.7×**.
* **The two §2.4 clauses the task book told us to investigate are NOT
  readable, and that is measured rather than assumed.** 「阻焊覆盖」: every
  ``VIA`` record carries ``topSolderExpansion`` / ``bottomSolderExpansion``
  keys and **every value is ``None``** (all 244 vias on 1.0.0, all 138 on the
  1.1.0 PCB1, all 196 on ROBOT), and no pad record carries a mask field at
  all. 「直连 vs relief」: the document's ``RULE`` records *do* carry
  ``mulPad.connType`` — ``'DIVERGENCE'`` in the ``DEFAULT`` rule, ``'DIRECT'``
  in the ``NORMAL`` one — but that is **one board-wide default**, not a
  property of any pad that is actually there. So R7 reports the default *as a
  default* and marks the per-pad question UNKNOWN. Pinning this is the point of
  the batch's 先调查 clause: an UNKNOWN that is asserted cannot be quietly
  filled in later.
* **The two boards with the same driver answer R9 differently, and that is the
  headline.** 1.0.0's ``U10``: the pad is in island 42 **alone** (area **0.0**,
  one layer) and each of the four thermal vias is in **its own single-member
  island** (27/28/29/30) — five separate pieces of copper in one 126 × 126 mil
  footprint, and no large plane under this pad in this model. The 1.1.0
  board's ``U2``: the pad and all four vias are in **island 9** — 15 members,
  **24 523 sq mil** of pour, layers 1/2/15/16 — a continuous exit. ROBOT's
  ``DRV1``: island 0, 289 members, **7 494 300 sq mil**. A rule that collapsed
  the pad's island and the vias' islands into one verdict would have to call
  1.0.0 「continuous」, and it is not.
"""

from __future__ import annotations

import re
from pathlib import Path

from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    StackupEntry,
    ViaGeometry,
)
from boardwise.core.parts import PartLibrary
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbRule
from boardwise.rules.pcb.focthermal import (
    DIRECT_VS_RELIEF_READABLE,
    SOLDER_MASK_READABLE,
    THERMAL_PAD_AREA_RATIO,
    THERMAL_PAD_UNKNOWN,
    FocThermalExitPath,
    FocThermalViaArray,
    FocThermalViaStyle,
    array_pitches,
    thermal_pad_of,
    thermal_vias_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"

R7 = "pcb-foc-thermal-via-style"
R8 = "pcb-foc-thermal-via-array"
R9 = "pcb-foc-thermal-exit-path"
RULE_IDS = [R7, R8, R9]

#: An **empty** shelf, not ``None`` — 133c's wording, same reason.
EMPTY_SHELF = PartLibrary()


def _rows(path: Path, rule_id: str) -> list:
    findings, _section = run_pcb_review(path)
    return [f for f in findings if f.rule_id == rule_id]


def _evidence(row) -> str:
    return "\n".join(row.evidence)


def _model_for(path: Path, title: str = "PCB1"):
    """``(board, netlist view)`` for one PCB document, named by its META title."""
    from boardwise.parsers.epro2_model import build_design_model
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
            return (
                extract_board(document, source.footprints(), source.stats),
                build_design_model(source, document),
            )
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


# ---------------------------------------------------------------------------
# 一、structure: the ids, their order, and their sources
# ---------------------------------------------------------------------------


def test_the_three_rules_continue_the_foc_block_after_133c_three():
    """The 133d placement, as one assertion.

    The three land as a **contiguous continuation** of 133c's three — same block,
    same shape (L1 geometry readers), and in the task book's own 133d table order
    (R7 → R8 → R9). The whole list is pinned by value, not as a set.
    """
    assert [rule.id for rule in BUILTIN_PCB_RULES] == [
        "pcb-decap-distance",
        "pcb-regulator-cap-distance",
        "pcb-regulator-fb-placement",
        "pcb-mcu-crystal-placement",
        "pcb-mcu-crystal-keepout",
        "pcb-mcu-supply-groups",
        "pcb-mcu-reset-boot",
        "pcb-foc-decap-proximity",
        "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width",
        "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        R7,
        R8,
        R9,
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]
    assert all(isinstance(rule, PcbRule) for rule in BUILTIN_PCB_RULES)
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert [i for i in ids if i.startswith("pcb-foc")] == [
        "pcb-foc-decap-proximity",
        "pcb-foc-ground-plane",
        "pcb-foc-gate-trace-width",
        "pcb-foc-track-corners",
        "pcb-foc-power-loop-area",
        "pcb-foc-ground-domains",
        "pcb-foc-ground-tie",
        "pcb-foc-return-path",
        R7,
        R8,
        R9,
    ], "the FOC block is contiguous: 133b's five, 133c's three, 133d's three"


def test_each_rule_cites_its_own_ti_section_and_says_it_measures():
    """All three are TI citations (unlike 133c's R1b, which was an oracle ruling).

    133d has no oracle-ruling half: every clause comes from TI SLVA959B, and
    each rule names its own sections so a reader can go look. Each is
    ``L1-pcb-geometry`` and each says in the same breath that it 出数不出判定.
    """
    sections = {R7: "§2.4", R8: "§2.5 / §2.6", R9: "§2.2"}
    for rule_id, section in sections.items():
        rule = next(r for r in BUILTIN_PCB_RULES if r.id == rule_id)
        assert rule.level == "L1-pcb-geometry", rule_id
        assert rule.title, rule_id
        assert rule.source.startswith("TI SLVA959B "), (rule_id, rule.source)
        assert section in rule.source, (rule_id, rule.source)
        assert "出数不出判定" in rule.source, rule_id
    # And none of them claims an oracle ruling, which would be a false citation.
    for rule_id in RULE_IDS:
        rule = next(r for r in BUILTIN_PCB_RULES if r.id == rule_id)
        assert "oracle ruling" not in rule.source, rule_id


def test_no_rule_grades_a_measurement_against_a_threshold():
    """The pack's core discipline, asserted on the source rather than trusted.

    TI's own figures — 8 mil hole, 20 mil pad — are the numbers most likely to
    leak into a comparison, and they are the ones this pins hardest: the module
    must never put a distance, a diameter or an area on either side of a
    relational operator. :data:`THERMAL_PAD_AREA_RATIO` is the one constant that
    does take part in a comparison, and it is a **door** (does this pad get
    identified at all), not a grade — so it is the one name allowed on a
    right-hand side.
    """
    import inspect

    from boardwise.rules.pcb import focthermal

    source = inspect.getsource(focthermal)
    for name in ("BULK_FARADS", "MULTILAYER_THRESHOLD", "OBTUSE_CORNER_DEG"):
        assert not re.search(rf"(?:<|>|<=|>=)\s*[^(\n]*{name}\b", source), (
            f"{name} must not be the right-hand side of a comparison in 133d; "
            "this pack is 出数不出判定 until 岳 rules a threshold"
        )
    # **TI's own figures are the real risk here** — 8 mil hole, 20 mil pad. They
    # must appear only in prose (strings), never as a literal a measurement is
    # compared against. Every conditional line is inspected, so the check cannot
    # pass by a figure being renamed rather than removed.
    conditionals = re.findall(r"^\s*(?:if|elif|while)\b.*$", source, re.M)
    assert conditionals, "the sanity check itself found nothing to inspect"
    for line in conditionals:
        code = line.split("#")[0]
        assert not re.search(
            r"(?:<|>|<=|>=)[^#\n]*\b(?:8|8\.0|20|20\.0)\b", code
        ), f"a TI reference figure heads a comparison: {line.strip()!r}"
    # :data:`THERMAL_PAD_AREA_RATIO` is the one constant that takes part in a
    # comparison, and it is a **door** (does this pad get identified at all),
    # not a grade — so it is the one name allowed on a right-hand side, and
    # asserting its exact form keeps the exemption deliberate.
    assert "area / next_area < THERMAL_PAD_AREA_RATIO" in source, (
        "the door test is the only comparison allowed to name a constant"
    )
    for match in re.finditer(r'severity="([A-Z0-9-]+)"', source):
        assert match.group(1) == "INFO", (
            f"133d emitted severity {match.group(1)!r}; the pack is INFO 起手"
        )


# ---------------------------------------------------------------------------
# 二、the thermal-pad identification, which every one of the three rests on
# ---------------------------------------------------------------------------


def test_the_thermal_pad_is_found_on_every_driver_and_by_shape_alone():
    """Acceptance anchor: the EP of 毕设FOC 1.0.0's ``U10``, measured three ways.

    There is **no** ``thermal_pad`` flag anywhere in the model, so the pad can
    only be found by the shape it has to have. This test pins what that method
    finds on the corpus, and the ratio it produces, so a change to the door shows
    up here rather than as a silently different pad.
    """
    board, _model = _model_for(FOC_100)
    thermal = thermal_pad_of(board, "U10")
    assert thermal is not None, "U10 places a thermal pad"

    assert thermal.pad.id == "e9"
    assert thermal.pad.pin_number == "33"
    assert thermal.pad.net == "GND"
    assert (thermal.pad.width, thermal.pad.height) == (126.0, 126.0)
    assert thermal.area == 15876.0, "126 × 126 mil"
    assert thermal.next_largest_area == 339.0, (
        "the next-largest pad of a WQFN-32 is a 30 × 11.3 mil signal pad"
    )
    assert thermal.ratio == pytest_approx(15876.0 / 339.0)
    assert thermal.ratio > 40.0, (
        "an exposed pad on this corpus is 28.7×–46.8× the next-largest pad; "
        "the 8× door is a separation, not a threshold that could be nudged up to "
        "swallow a lead row"
    )
    assert f"{THERMAL_PAD_AREA_RATIO:g}×" in thermal.basis, (
        "the row quotes the door it applied, so the identification is auditable"
    )


def pytest_approx(value: float, rel: float = 1e-6):
    """A local ``approx`` so this file needs no pytest import for one check."""
    import pytest

    return pytest.approx(value, rel=rel)


def test_the_door_separates_a_thermal_pad_from_a_lead_row_on_every_board():
    """The three real pads across the corpus, each with its own measured ratio.

    毕设FOC 1.0.0's ``U10`` and the 1.1.0 board's ``U2`` are the same part on
    two boards and read identically; ROBOT's ``DRV1`` is a different package
    with a rectangular pad and reads lower but still far above the door. Pinning
    all three is what makes the door's margin a measured fact rather than a
    guess.
    """
    expectations = [
        (FOC_100, "U10", "33", "GND", 15876.0, 339.0),
        (FOC_110, "U2", "33", "GND", 15876.0, 339.0),
        (ROBOT, "DRV1", "29", "GND", 26427.569, 920.554),
    ]
    for path, designator, pin, net, area, next_area in expectations:
        board, _model = _model_for(path)
        thermal = thermal_pad_of(board, designator)
        assert thermal is not None, (path.name, designator)
        assert thermal.pad.pin_number == pin, (path.name, thermal.pad.pin_number)
        assert thermal.pad.net == net, (path.name, thermal.pad.net)
        assert thermal.area == pytest_approx(area, rel=1e-3), (path.name, thermal.area)
        assert thermal.next_largest_area == pytest_approx(next_area, rel=1e-3)
        assert thermal.ratio >= 20.0, (path.name, thermal.ratio)
    assert thermal_pad_of(_model_for(ROBOT)[0], "DRV1").ratio < 46.8, (
        "the HTSSOP-28's pad ratio is genuinely lower than the WQFN-32's, so the "
        "three pads are not one number the door could be tuned around"
    )


def test_a_part_with_no_exposed_pad_is_unknown_not_absent():
    """The honesty door: a motor driver with no EP is UNKNOWN, not 「no EP」.

    Asserted **behaviourally** on a synthetic board, because that is the case the
    corpus cannot carry: all three of its drivers do have an exposed pad. The
    two halves of the claim are told apart deliberately:

    * the **pad** is UNKNOWN — no pad cleared the door, so nothing claims to
      have found a thermal pad, and the row says so with that word;
    * the **board** is not asserted to lack an EP — which is a statement about
      the part, and the model cannot make it.

    R8 and R9 file **no row at all** here, because they have no pad to measure;
    putting a finding about a pad that was never identified would be inventing
    the object the rule is about.
    """
    from boardwise.rules.pcb.focthermal import THERMAL_PAD_UNKNOWN

    board = _synthetic_driver_board(with_thermal_pad=False)
    assert thermal_pad_of(board, "U1") is None, (
        "every pad is 30 × 11.3 mil here, so no pad clears the exposed-pad door"
    )
    assert THERMAL_PAD_UNKNOWN == "UNKNOWN"

    ctx = _ctx_for(board)
    shelf = _driver_shelf()
    style = FocThermalViaStyle().check_with_library(ctx, shelf)
    assert len(style) == 1
    row = style[0]
    assert row.severity == "INFO"
    assert "**no pad clears the" in row.message, (
        "the row must say the pad is unidentified rather than implying there is "
        "none"
    )
    assert THERMAL_PAD_UNKNOWN in row.message
    assert "not 「the part has no thermal pad」" in row.message, (
        "and it must say why the difference matters: the first is a statement "
        "about this model, the second about the part"
    )
    assert "**R8 and R9 file no row here**" in row.message, (
        "the row must tell the reader that R8/R9 will be silent, so the absence "
        "is explained rather than looking like an omission"
    )

    # And the two rules that need a pad are silent rather than guessing.
    assert FocThermalViaArray().check_with_library(ctx, shelf) == []
    assert FocThermalExitPath().check_with_library(ctx, shelf) == []


# ---------------------------------------------------------------------------
# 三、R7 — pcb-foc-thermal-via-style
# ---------------------------------------------------------------------------


def test_r7_reports_u10s_four_vias_with_their_layer_span():
    """Acceptance anchor: 1.0.0's ``U10`` — four vias, all through-hole.

    Measured: four vias centred inside the 126 × 126 mil pad, every one on
    ``GND``, every ``via_type`` ``'NORMAL'``, hole **12.008 mil** and pad
    **24.016 mil** (a rounded inch-metric pair — 0.305 mm / 0.610 mm), and
    **every one reaching all four copper layers** [1, 2, 15, 16] because none
    leaves an inner layer unused. So the 「不贯通」 count is **0**, and the row
    says so rather than reporting zero vias or staying silent.
    """
    rows = [r for r in _rows(FOC_100, R7) if r.board == "PCB1"]
    assert len(rows) == 1, [(r.board, r.message[:70]) for r in rows]
    row = rows[0]
    assert row.severity == "INFO"

    assert "U10" in row.message and "pin '33'" in row.message
    assert "'GND'" in row.message
    assert "4 via(s) in the projection" in row.message
    assert "0 of 4 do not reach every copper layer" in row.message, (
        "all four are through-hole, so the abnormal-form count is zero and is "
        "reported as zero — a zero here is a reading, not a silence"
    )

    ev = _evidence(row)
    assert "12.008" in ev and "24.016" in ev, "hole and pad diameters are quoted"
    assert "1, 2, 15, 16" in ev, "the layer span is per via and quoted"
    assert "none of this pad's vias leaves a copper layer unused" in ev
    assert "vias_on_pad" in ev, "the row names the primitive that read it"
    assert "thermal pad identified by" in ev
    assert "motor driver by shelf category 'ic.motor-driver'" in ev, (
        "the row must say which door made this part a thermal-design subject"
    )


def test_r7_reports_a_single_via_on_robot_and_names_its_type():
    """Acceptance anchor: ROBOT's ``DRV1`` — one via, and it is a ``SUTURE``.

    Measured: one via (``9ce71638bf739fa4``) centred in the 244.094 × 108.268 mil
    EP, ``via_type`` **``'SUTURE'``** where 毕设FOC's are ``'NORMAL'``, hole
    12.008 / pad 24.016 mil, reaching all four copper layers. The rule reports
    the type verbatim rather than normalising it away, because a suture via is a
    different construction and the reader is the one who should know.
    """
    rows = [r for r in _rows(ROBOT, R7) if r.board == "PCB1"]
    assert len(rows) == 1
    row = rows[0]
    assert "DRV1" in row.message
    assert "1 via(s) in the projection" in row.message
    assert "'SUTURE'" in row.message, "the via_type is reported as drawn"
    assert "0 of 1 do not reach every copper layer" in row.message


def test_r7_says_the_two_soldua_readings_are_unknown_and_why():
    """The batch's investigation, pinned so it cannot be quietly filled in.

    「阻焊覆盖」 and 「直连 vs thermal relief」 are the two halves of TI §2.4, and
    **neither is readable at the granularity the question needs**:

    * every ``VIA`` record carries ``topSolderExpansion`` /
      ``bottomSolderExpansion`` keys and every value is ``None`` on the whole
      corpus, and no pad record carries a mask field at all;
    * ``mulPad.connType`` **is** in the document (``'DIVERGENCE'`` in the
      DEFAULT rule, ``'DIRECT'`` in the NORMAL one) but it is one board-wide
      default, not a per-pad property.

    So the row must state both UNKNOWNs, must quote the document default *as a
    default*, and the module's two booleans must say ``False`` so a caller can
    assert the honesty rather than re-derive it.
    """
    assert SOLDER_MASK_READABLE is False
    assert DIRECT_VS_RELIEF_READABLE is False

    for path, designator in ((FOC_100, "U10"), (ROBOT, "DRV1")):
        row = next(r for r in _rows(path, R7) if r.board == "PCB1")
        assert "UNKNOWN" in row.message, (path.name, row.message)
        assert "阻焊覆盖" in row.message or "UNKNOWN" in row.message

        ev = _evidence(row)
        assert "topSolderExpansion/bottomSolderExpansion" in ev, (
            "the solder-mask UNKNOWN must name the field that exists and is empty"
        )
        assert "every value is None" in ev
        assert "PadGeometry and the footprint PadTemplate have no mask field" in ev
        assert "mulPad.connType" in ev, "the relief UNKNOWN must quote what IS there"
        assert "'DIVERGENCE'" in ev and "'DIRECT'" in ev
        assert "**one value for the whole board**" in ev, (
            "the board-wide default must be labelled as such, so a reader cannot "
            "mistake it for this pad's own connection form"
        )
        assert "No per-pad connType exists" in ev


def test_r7_reports_a_pad_with_no_via_at_all_rather_than_silence():
    """Zero vias is a reading, and the shape a reader most needs told.

    TI §2.5's subject is exactly this: an exposed pad whose heat can only leave
    through the pad itself. A rule that skipped it would leave the reader unable
    to tell 「measured, nothing there」 from 「not measured」.
    """
    board = _synthetic_driver_board(with_thermal_pad=True, vias_in_pad=0)
    rule = FocThermalViaStyle()
    findings = rule.check_with_library(_ctx_for(board), _driver_shelf())
    assert len(findings) == 1
    assert "no via at all" in findings[0].message
    assert "0 of 0 do not reach every copper layer" in findings[0].message
    assert "no per-via line" in _evidence(findings[0]), (
        "the per-via evidence line says there is none rather than being empty"
    )


def test_r7_files_no_row_on_a_board_with_no_motor_driver():
    """llc and 智能药箱 have no motor driver at all — **zero rows**, not a crash.

    The object these rules measure does not exist on those boards, and 133b's
    「absent, not empty」 discipline (R16/R20) and 133c's (R5) apply unchanged:
    a rule that filed a finding for each missing thing would bury the FOC
    boards under everything else's absence.
    """
    for path in (LLC, PILLBOX):
        for rule_id in RULE_IDS:
            assert _rows(path, rule_id) == [], (
                path.name,
                rule_id,
                [f.message[:80] for f in _rows(path, rule_id)],
            )


def test_r7_reports_a_blind_via_as_an_abnormal_form():
    """The 「不贯通」 half of R7 is exercised on a synthetic blind via.

    A via with a non-empty ``unused_inner_layers`` does not reach every copper
    layer, and on a thermal pad that is a statement about the form the heat path
    takes — which is what §2.4's 「直连」 means in a model with no mask aperture.
    The corpus has no such via on a thermal pad (all 244 / 138 / 196 are
    through-hole), so this is a synthetic board rather than a corpus claim.
    """
    board = _synthetic_driver_board(with_thermal_pad=True, vias_in_pad=1, blind=True)
    findings = FocThermalViaStyle().check_with_library(_ctx_for(board), _driver_shelf())
    assert len(findings) == 1
    row = findings[0]
    assert "1 of 1 do not reach every copper layer" in row.message
    ev = _evidence(row)
    assert "unused_inner_layers [2]" in ev, "the unused layers are named, not counted"
    assert "the barrel does not reach those layers" in ev


# ---------------------------------------------------------------------------
# 四、R8 — pcb-foc-thermal-via-array
# ---------------------------------------------------------------------------


def test_r8_reports_the_four_via_array_with_its_pitch_distribution():
    """Acceptance anchor: 1.0.0's ``U10`` — a diamond of four.

    Measured coordinates: (6210.00, −1200.00), (6163.26, −1245.86),
    (6260.51, −1245.86), (6210.29, −1292.84) — a **diamond**, and the
    nearest-neighbour pitches read **65.5 / 65.5 / 68.2 / 66.5 mil**, a spread
    of **2.7 mil**. The row reports the distribution and applies no pitch
    threshold, because TI gives diameters and 岳 has ruled none.
    """
    rows = [r for r in _rows(FOC_100, R8) if r.board == "PCB1"]
    assert len(rows) == 1
    row = rows[0]
    assert "U10" in row.message and "pin '33'" in row.message
    assert "**4 vias** in the projection" in row.message
    assert "nearest-neighbour pitch 65.5, 65.5, 68.2, 66.5 mil" in row.message
    assert "spread 2.7 mil" in row.message
    assert "without any pitch threshold being applied" in row.message

    ev = _evidence(row)
    assert "nearest-neighbour distance per via" in ev
    assert "reading is the **distribution**, never a threshold" in ev


def test_r8_quotes_tis_reference_figures_and_does_not_apply_them():
    """The 「写 evidence 不出判定」 clause, pinned.

    TI §2.5/§2.6 give a reference **hole of about 8 mil and pad of about 20
    mil**. The corpus's own array is a rounded inch-metric pair — measured hole
    **12.008 mil** (0.305 mm) and pad **24.016 mil** (0.610 mm) — same order of
    magnitude, different figures. The row must carry both so the reader can do
    the comparison, and must say in the same breath that neither is applied:
    which one a board should use is 岳's call, not this rule's.
    """
    for path in (FOC_100, FOC_110, ROBOT):
        row = next(r for r in _rows(path, R8) if r.board == "PCB1")
        assert "TI 参考值 孔 8mil / 盘 20mil" in row.message, path.name
        assert "**只写 evidence 不出判定**" in row.message
        ev = _evidence(row)
        assert "hole about 8 mil, pad about 20 mil" in ev
        assert "written here for the reader to compare against" in ev
        assert "are **not** applied" in ev
        assert "0.305 mm" in ev and "0.610 mm" in ev, (
            "the measured pair is given in both units so the comparison is real"
        )
        assert "岳's call" in ev


def test_r8_says_a_single_via_is_not_an_array_and_invents_no_pitch():
    """Acceptance anchor: ROBOT's ``DRV1`` — one via, so no pitch at all.

    A set of one has no nearest neighbour, and the honest row says so. Deriving
    a pitch from the pad size instead would be inventing the very regularity the
    rule exists to measure.
    """
    rows = [r for r in _rows(ROBOT, R8) if r.board == "PCB1"]
    assert len(rows) == 1
    row = rows[0]
    assert "**1 via** in the projection" in row.message
    assert "a single via is not an array" in row.message
    assert "no pitch is computed and none is invented" in row.message
    ev = _evidence(row)
    assert "a set of fewer than two vias has no nearest neighbour" in ev
    assert "and none is inferred from the pad size" in ev


def test_r8_reports_a_scatter_as_a_wide_spread_not_a_pass():
    """A set with no regularity is measured as a wide spread, not graded.

    Synthetic: three vias at deliberately uneven pitch. The row must report
    the numbers and say the spread is wide — with **no** 「fail」, no severity
    change and no threshold anywhere.
    """
    board = _synthetic_driver_board(with_thermal_pad=True, vias_in_pad=3, scatter=True)
    findings = FocThermalViaArray().check_with_library(_ctx_for(board), _driver_shelf())
    assert len(findings) == 1
    row = findings[0]
    assert row.severity == "INFO"
    assert "**3 vias** in the projection" in row.message
    assert "nearest-neighbour pitch" in row.message
    assert "without any pitch threshold being applied" in row.message
    assert "spread" in row.message


def test_array_pitches_is_the_nearest_neighbour_of_each_via():
    """The primitive itself, so the rule's reading can be re-derived."""
    vias = [
        ViaGeometry(id="a", x=0.0, y=0.0, hole_diameter=8.0, via_diameter=20.0),
        ViaGeometry(id="b", x=30.0, y=0.0, hole_diameter=8.0, via_diameter=20.0),
        ViaGeometry(id="c", x=30.0, y=40.0, hole_diameter=8.0, via_diameter=20.0),
    ]
    assert array_pitches(vias) == [30.0, 30.0, 40.0], (
        "each via reads its own closest neighbour, not a global spacing"
    )
    assert array_pitches(vias[:1]) == [], "one via has no neighbour and gets none"
    assert array_pitches([]) == []


# ---------------------------------------------------------------------------
# 五、R9 — pcb-foc-thermal-exit-path
# ---------------------------------------------------------------------------


def test_r9_reports_that_100s_pad_and_its_four_vias_are_five_separate_islands():
    """Acceptance anchor: 毕设FOC 1.0.0 — the headline reading of this batch.

    Measured on ``U10``'s 126 × 126 mil EP: the pad is in **island 42 alone**
    (1 member, layers ``[1]``, area **0.0**) and each of the four thermal vias
    is in **its own single-member island** — 27, 28, 29, 30. So in this model
    the pad's copper and its four vias are **five separate pieces**, and the
    ``GND`` net's 46 islands put no pour plane under this pad at all.

    This is the case that decides why the rule keeps the pad's island and the
    vias' islands apart: a rule that joined them would have to call 1.0.0
    「continuous」, and it is not.
    """
    rows = [r for r in _rows(FOC_100, R9) if r.board == "PCB1"]
    assert len(rows) == 1
    row = rows[0]
    assert row.severity == "INFO"
    assert "the pad is in island 42 of 'GND'" in row.message
    assert "1 member(s), layers [1]" in row.message
    assert "**no pour polygon at all** (area 0.0" in row.message
    assert "so this piece of copper is the pad itself rather than a plane" in row.message
    assert "across 4 island(s) for 4 via(s)" in row.message, (
        "each via's island is named and shown to differ from the pad's"
    )
    assert "a separate island from the pad's" in row.message

    ev = _evidence(row)
    assert "region_copper" in ev
    assert "pour_connectivity" in ev
    assert "46 island(s) on this net" in ev, "the whole net's island count is on the row"
    assert "island area is pour area only" in ev, (
        "area 0.0 means 「no pour polygon in this piece」, and the row must say "
        "so rather than reporting a zero-area region that does not exist"
    )
    assert "neither is graded" in ev


def test_r9_reports_the_two_boards_answering_differently():
    """The comparison that makes the rule per-board rather than general.

    毕设FOC 1.0.0's ``U10`` is broken (five single-member islands, 0.0 sq mil).
    The 1.1.0 board's ``U2`` — the **same part, the same 126 × 126 mil pad** —
    is continuous: pad and all four vias in **island 9**, 15 members,
    **24 523 sq mil** of pour, layers 1/2/15/16. Same driver, same pad, opposite
    answer, which is why neither is graded and neither is generalised.
    """
    broken = next(r for r in _rows(FOC_100, R9) if r.board == "PCB1")
    continuous = next(r for r in _rows(FOC_110, R9) if r.board == "PCB1")

    assert "U2" in continuous.message and "pin '33'" in continuous.message
    assert "the pad is in island 9 of 'GND'" in continuous.message
    assert "15 member(s), layers [1, 2, 15, 16]" in continuous.message
    assert "the island carries 24523 sq mil of pour" in continuous.message
    assert "the pad's own island" in continuous.message, (
        "the via that shares the pad's island is said to share it, and the three "
        "that do not are each named as separate"
    )
    assert "across 4 island(s) for 4 via(s)" in continuous.message

    # And the difference is genuinely there, not a wording artefact.
    assert "**no pour polygon at all**" in broken.message
    assert "**no pour polygon at all**" not in continuous.message


def test_r9_reports_robots_single_huge_island():
    """Acceptance anchor: ROBOT's ``DRV1`` — one island, 7 494 300 sq mil.

    Measured: the ``GND`` net on ROBOT reads **1 island** in total, 289 members,
    layers 1/2/15/16, **7 494 300 sq mil** of pour, and the pad's one thermal
    via is inside it. So this board's exit path is continuous and its pour is
    two orders of magnitude larger than the 1.1.0 board's.
    """
    rows = [r for r in _rows(ROBOT, R9) if r.board == "PCB1"]
    assert len(rows) == 1
    row = rows[0]
    assert "the pad is in island 0 of 'GND'" in row.message
    assert "289 member(s), layers [1, 2, 15, 16]" in row.message
    assert "7494300 sq mil of pour" in row.message
    assert "island 0 holds 9ce71638bf739fa4" in row.message
    assert "the pad's own island" in row.message


def test_r9_inventories_the_pad_region_per_layer():
    """``region_copper``'s per-layer presence counts are on the row.

    Measured on 1.0.0's ``U10``: layer 1 holds 5 elements (the pad + the 4
    vias), layers 2/15/16 hold 4 each (the vias alone — the EP is an SMD pad on
    layer 1, which is 127b's own reading and the reason it does not appear on
    the inner layers).
    """
    row = next(r for r in _rows(FOC_100, R9) if r.board == "PCB1")
    assert "region copper over the pad's projection: layer 1: 5, layer 2: 4, layer 15: 4, layer 16: 4" in row.message
    ev = _evidence(row)
    assert "presence, not distance" in ev, (
        "131f's primitive is an inventory and its docs say so; the row must not "
        "present the counts as clearances"
    )
    assert "layer 1: pad U10.33 on net 'GND'" in ev
    assert "0 unclassifiable copper element(s)" in ev


def test_r9_reports_a_pad_that_belongs_to_no_island():
    """A pad with no net, or a net with no island, is reported as such.

    Synthetic: the pad carries no net at all, so there is no connectivity to
    read. The rule must say so and claim **no** exit path — not infer one from
    the region inventory, which is present regardless of nets.
    """
    board = _synthetic_driver_board(with_thermal_pad=True, vias_in_pad=0, pad_net=None)
    findings = FocThermalExitPath().check_with_library(_ctx_for(board), _driver_shelf())
    assert len(findings) == 1
    row = findings[0]
    assert "no net on this pad, so no connectivity to read" in _evidence(row)
    assert "continuous vs broken 出数不出判定" in row.message


# ---------------------------------------------------------------------------
# 六、the three rules agree with each other and with the primitives
# ---------------------------------------------------------------------------


def test_the_three_rules_measure_the_same_pad_by_the_same_door():
    """No rule may pick its own thermal pad.

    133b's and 133c's discipline applied to 133d: all three read
    :func:`thermal_pad_of`, so they cannot disagree about which pad is the
    exposed one. Asserted by re-deriving each row's pad from the module.
    """
    from boardwise.rules.pcb.focthermal import _pad_reading

    for path, designator in ((FOC_100, "U10"), (FOC_110, "U2"), (ROBOT, "DRV1")):
        board, _model = _model_for(path)
        thermal = thermal_pad_of(board, designator)
        assert thermal is not None
        reading = _pad_reading(thermal)
        for rule_id in RULE_IDS:
            rows = [r for r in _rows(path, rule_id) if r.board == "PCB1"]
            assert len(rows) == 1, (path.name, rule_id)
            assert rows[0].message.startswith(reading), (
                path.name,
                rule_id,
                "every rule must open with the same pad identity",
            )


def test_the_thermal_via_count_matches_the_primitive_on_every_board():
    """R7's count, R8's count and :func:`vias_on_pad` must be the same number.

    Three readers of one fact; if two of them disagree the module is measuring
    something other than what it says.
    """
    for path, designator, expected in (
        (FOC_100, "U10", 4),
        (FOC_110, "U2", 4),
        (ROBOT, "DRV1", 1),
    ):
        board, _model = _model_for(path)
        thermal = thermal_pad_of(board, designator)
        vias = thermal_vias_of(board, thermal)
        assert len(vias) == expected, (path.name, len(vias))

        style = next(r for r in _rows(path, R7) if r.board == "PCB1")
        array = next(r for r in _rows(path, R8) if r.board == "PCB1")
        assert f"{expected} via(s) in the projection" in style.message, path.name
        assert f"**{expected} via" in array.message, path.name


def test_the_door_constant_is_a_separation_and_is_exported():
    """:data:`THERMAL_PAD_AREA_RATIO` is public and pinned.

    It is a **door** — does this pad get identified at all — and the module
    exports it so a caller can assert the margin rather than trust it. 8× is
    measured against the corpus's lowest real ratio (ROBOT's 28.7×) with a wide
    gap to where a lead row would fall, and the test on the three boards above
    is what keeps it honest.
    """
    assert THERMAL_PAD_AREA_RATIO == 8.0
    board, _model = _model_for(ROBOT)
    assert thermal_pad_of(board, "DRV1").ratio > 3 * THERMAL_PAD_AREA_RATIO, (
        "the corpus's lowest real ratio clears the door by more than 3×, so the "
        "door could not be nudged up to swallow a lead row without this failing"
    )


# ---------------------------------------------------------------------------
# synthetic board builder (the cases the corpus does not carry)
# ---------------------------------------------------------------------------


def _synthetic_driver_board(
    *,
    with_thermal_pad: bool,
    vias_in_pad: int = 0,
    blind: bool = False,
    scatter: bool = False,
    pad_net: str | None = "GND",
):
    """A two-layer board with one ``U1`` and, optionally, an exposed pad.

    Every case in this file that the corpus cannot carry — no EP, a pad with no
    via, a **blind** via in the pad, a scatter with no regularity, a pad with no
    net — is built here, so the tests do not pretend the corpus covers them.
    """
    layers = {1: LayerInfo(1, "TOP", "SIGNAL"), 2: LayerInfo(2, "BOTTOM", "SIGNAL")}
    stackup = [
        StackupEntry(z_index=0, layer_id=1),
        StackupEntry(z_index=1, layer_id=2),
    ]
    pads: list[PadGeometry] = []
    pads.append(
        PadGeometry(
            id="p1",
            component="U1",
            pin_number="1",
            net="VCC",
            layer_id=1,
            effective_layer_ids=[1],
            x=0.0,
            y=0.0,
            width=30.0,
            height=11.3,
            shape="RECT",
        )
    )
    if with_thermal_pad:
        pads.append(
            PadGeometry(
                id="p2",
                component="U1",
                pin_number="33",
                net=pad_net,
                layer_id=1,
                effective_layer_ids=[1],
                x=20.0,
                y=20.0,
                width=126.0,
                height=126.0,
                shape="RECT",
            )
        )
    vias: list[ViaGeometry] = []
    if scatter:
        # Three vias inside the pad's rectangle (−43..83 in both axes) but at
        # deliberately uneven pitch, so the row has a real spread to report.
        spots = [(20.0, 20.0), (40.0, 20.0), (20.0, 80.0)]
    else:
        spots = [
            (20.0 + 30.0 * i, 20.0 + 30.0 * (i % 2))
            for i in range(max(vias_in_pad, 0))
        ]
    for i in range(vias_in_pad):
        x, y = spots[i]
        vias.append(
            ViaGeometry(
                id=f"v{i}",
                net=pad_net or "GND",
                x=x,
                y=y,
                hole_diameter=12.008,
                via_diameter=24.016,
                via_type="NORMAL",
                unused_inner_layers=[2] if blind else [],
            )
        )
    board = BoardGeometry(
        name="synthetic",
        layers=layers,
        stackup=stackup,
        # The placement is what makes ``BoardGeometry.component("U1")`` resolve,
        # and that is the door the rules use to skip a driver this document does
        # not place. Without it every synthetic case would file nothing and pass
        # for the wrong reason.
        components=[ComponentPlacement(id="c1", designator="U1", footprint="SYNTH-WQFN")],
        pads=pads,
        vias=vias,
        pours=[
            PourShape(id="pour1", net=pad_net or "GND", layer_id=2, kind="pour",
                      points=[Point(-100.0, -100.0), Point(200.0, -100.0),
                              Point(200.0, 200.0), Point(-100.0, 200.0)])
        ] if pad_net else [],
    )
    return board


def _ctx_for(board: BoardGeometry):
    """A :class:`PcbReviewContext` over a synthetic board, with a netlist view.

    The netlist view carries ``U1`` with an MPN the **driver shelf below**
    resolves to ``ic.motor-driver``, which is the only door the rules use to
    decide what a motor driver is. The shelf has to be real rather than empty:
    an empty shelf would leave the part unrecognised and every synthetic case
    would measure nothing, passing for the wrong reason.
    """
    from boardwise.rules.pcb.base import PcbReviewContext

    component = type(
        "_Component",
        (),
        {"mpn": SYNTH_DRIVER_MPN, "lcsc_part": "", "value": SYNTH_DRIVER_MPN,
         "pins": (), "footprint": "SYNTH-WQFN"},
    )()
    model = type("_Model", (), {"components": {"U1": component}})()
    return PcbReviewContext(board=board, pcb_model=model)


#: The MPN the synthetic board's ``U1`` carries, and the shelf that names it.
SYNTH_DRIVER_MPN = "SYNTHDRV-000"


def _driver_shelf():
    """A one-entry shelf classifying :data:`SYNTH_DRIVER_MPN` as a motor driver."""
    from boardwise.core.parts import PartEntry

    return PartLibrary(
        parts=[
            PartEntry(
                key="synthetic:driver",
                value=SYNTH_DRIVER_MPN,
                mpn=SYNTH_DRIVER_MPN,
                category="ic.motor-driver",
            )
        ]
    )