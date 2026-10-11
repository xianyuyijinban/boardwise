"""Tests for task 151: the footprint-consistency rule (E 阶段第一棒).

The rule reconciles 「what the schematic declared」 against 「what the PCB
actually places」. This file pins, in order:

* **the vocabulary readers** — pure functions, no fixture, so a change in the
  tokenizer or in either table fails here rather than in a report nobody
  diffs;
* **the structure gate** — the rule is in ``BUILTIN_PCB_RULES`` at the
  declared position and carries a ``source`` that says it is a house rule
  待裁 (there is no threshold to quote, because none of these judgements is a
  degree);
* **the four synthetic states** — a pad-count mismatch, a size-code mismatch,
  a family mismatch, an undecidable pair and the WARN, each built by hand so
  the assertion is about the rule and not about a fixture's contents;
* **the three acceptance boards** — 毕设FOC 1.0.0, 毕设FOC 1.1.0 and ROBOT ctrl
  FOC, with the measured numbers the batch was accepted on.

The acceptance anchors, measured 2026-10-11 (see ``outputs/151/recon.txt``,
which is the same run rendered as evidence):

* **毕设FOC 1.0.0 PCB1** — 6 ERROR, all 尺寸码不符, all ``0805`` declared
  against ``0603`` placed: ``C17``/``C8``/``C98``/``C99`` on ``C0603`` (31.496 ×
  35.433 mil pads) and ``U3``/``U7`` on ``R0603`` (31.751 × 34.016 mil). The
  same board's own ``C0805`` land pattern measures 55.512 × 53.150 mil, so the
  difference is physical, and all six parts' MPNs say ``0805``
  (``CC0805KRX7R9BB104`` / ``FRC0805J471 TS``) — the schematic side is
  self-consistent and the *PCB* land is the outlier.
* **毕设FOC 1.1.0 PCB1** — the same defect, 14 references. 1.1.0 also carries
  a third board (``Board3``/``PCB3``) whose ``R1``…``R6`` are declared by the
  schematic and **not placed** on the PCB: 6 presence ERRORs, and none of them
  leaks onto ``PCB1`` even though ``Board1`` uses the same ``R1``…``R6`` names.
* **ROBOT ctrl FOC PCB1** — 0 ERROR. Its ``DRV1`` (``DRV8313``,
  ``HTSSOP-28_…-EP``) is the case that would false-positive a naive pad count:
  the schematic symbol puts the exposed pad on pin 29 and the PCB footprint
  instantiates 29 pads, so both sides read 29 and the rule is silent.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from boardwise.core.geometry import BoardGeometry, ComponentPlacement, PadGeometry
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.footprint import (
    CHIP_SIZE_CODES,
    DO_214_OUTLINES,
    PACKAGE_FAMILIES,
    FootprintConsistency,
    _compare_names,
    chip_size_code,
    dimension_tokens,
    package_family,
    tokenize,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"

RULE_ID = "pcb-footprint-consistency"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(path: Path, rules=None) -> tuple[list, dict]:
    """Run the inline rule against a real backup with its own schematic model."""
    model = build_project_model(path)
    return run_pcb_review(
        path, model=model, rules=rules or [FootprintConsistency()]
    )


def _board_rows(section: dict, findings: list, title: str) -> list:
    for entry in section["boards"]:
        if entry["title"] == title:
            return [findings[index] for index in entry["findings"]]
    raise AssertionError(f"no board {title!r} in {[b['title'] for b in section['boards']]}")


def _by_severity(rows: list, severity: str) -> list:
    return [row for row in rows if row.severity == severity]


def _targets(rows: list) -> set[str]:
    return {row.target.component_ref for row in rows if row.target is not None}


# ---------------------------------------------------------------------------
# synthetic helpers (the four states, hand-built)
# ---------------------------------------------------------------------------


def _pad(component: str, pin: str, *, x: float = 0.0, width: float = 30.0,
         height: float = 30.0) -> PadGeometry:
    return PadGeometry(
        id=f"{component}.{pin}", component=component, pin_number=pin, net="",
        layer_id=1, x=x, y=0.0, local_x=x, local_y=0.0,
        width=width, height=height, shape="RECT", angle=0.0,
    )


def _pcb(model_footprints: dict[str, str], pins: dict[str, int],
         sizes: dict[str, tuple[float, float]] | None = None):
    """A synthetic ``(board, pcb_model)`` pair.

    ``model_footprints`` is designator → the FOOTPRINT title the PCB reads;
    ``pins`` is designator → how many pads the footprint instantiates;
    ``sizes`` optionally gives each designator its own pad size, which is what
    the WARN is about.
    """
    pads: list[PadGeometry] = []
    for designator, count in pins.items():
        width, height = (sizes or {}).get(designator, (30.0, 30.0))
        for index in range(count):
            pads.append(
                _pad(designator, str(index + 1), x=20.0 * index,
                     width=width, height=height)
            )
    board = BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=0.0, y=0.0, layer_id=1)
            for d in pins
        ],
        pads=pads,
    )
    pcb_model = DesignModel(
        components={
            designator: Component(
                uid=f"u-{designator}", designator=designator,
                footprint=title, props={"Footprint": f"fp-{designator}"},
            )
            for designator, title in model_footprints.items()
        }
    )
    return board, pcb_model


def _sch(components: dict[str, tuple[str, int]]) -> DesignModel:
    """A synthetic schematic board: designator → (declared footprint, pins)."""
    return DesignModel(
        components={
            designator: Component(
                uid=f"s-{designator}", designator=designator, footprint=footprint,
                pins=[Pin(number=str(i + 1), name="", net=None) for i in range(count)],
            )
            for designator, (footprint, count) in components.items()
        }
    )


def _ctx(board, pcb_model, sch_model=None, board_uuid="") -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=sch_model, pcb_model=pcb_model,
        board_uuid=board_uuid,
    )


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------


def test_tokenize_splits_letters_and_numbers_without_inventing_grammar():
    """The one splitting rule: a run of letters, a run of digits, in order."""
    assert tokenize("C0603") == ["C", "0603"]
    assert tokenize("SOIC-8_L4.9-W3.9-P1.27-LS6.0-BL") == [
        "SOIC", "8", "L", "4.9", "W", "3.9", "P", "1.27", "LS", "6.0", "BL",
    ]
    assert tokenize("DFN(5x6)") == ["DFN", "5", "x", "6"]
    assert tokenize("") == []


def test_chip_size_code_reads_the_code_out_of_a_prefix_or_a_bare_size():
    """``C0603``/``LED0805-R-RD``/``L1008`` all carry the same four-digit code."""
    assert chip_size_code("0603") == "0603"
    assert chip_size_code("C0603") == "0603"
    assert chip_size_code("R0805") == "0805"
    assert chip_size_code("LED0805-R-RD") == "0805"
    assert chip_size_code("L1008") == "1008"
    assert chip_size_code("R2512") == "2512"
    # An MPN carries it too — which is what makes the second evidence line of a
    # size-code finding possible: this cap's own name says 0805.
    assert chip_size_code("CC0805KRX7R9BB104") == "0805"
    assert chip_size_code("FRC0805J471 TS") == "0805"
    # Nothing that is not a size code: a bare dimension and a text-only name.
    assert chip_size_code("SOIC-8_L4.9-W3.9-P1.27-LS6.0-BL") is None
    assert chip_size_code("M3螺丝") is None
    assert "0603" in CHIP_SIZE_CODES


def test_package_family_normalizes_only_what_can_share_a_land_pattern():
    """The fit grouping, and the three things it deliberately refuses to do."""
    # Same family, different spelling — every one of these pairs is on a fixture.
    assert package_family("SO-8") == package_family("PG-DSO-8_L5.0-W4.0-P1.27-LS6.0-BL")
    assert package_family("SOP-8_L4.9-W3.9-P1.27-LS6.0-BL") == "soic"
    assert package_family("SOIC-8_L5.0-W4.0-P1.27-LS6.0-BL") == "soic"
    assert package_family("DFN(5x6)") == package_family("PDFN-8_L5.8-W5.1-P1.27-LS6.1-BL")
    assert package_family("HTSSOP-28-EP-4.5mm") == package_family(
        "HTSSOP-28_L9.8-W4.5-P0.65-LS6.6-BL-EP"
    )
    assert package_family("LQFP-64(10x10)") == package_family(
        "LQFP-64_L10.0-W10.0-P0.50-LS12.0-BL"
    )
    # DO-214AB/AA/AC are JEDEC's names for SMC/SMB/SMA.
    assert DO_214_OUTLINES == {"AB": "smc", "AA": "smb", "AC": "sma"}
    assert package_family("SMC(DO-214AB)") == package_family("SMC_L6.9-W5.9-LS7.9-BI")
    # Different pitches are different families, on purpose.
    assert package_family("SOIC-8_…") != package_family("TSSOP-16_…")
    # A chip size code is not a family, and neither is Chinese prose.
    assert package_family("0603") is None
    assert package_family("C0603") is None
    assert package_family("M3螺丝") is None
    # ``DO`` or ``214`` alone is not DO-214: a guess there would turn a real
    # mismatch into an "agree".
    assert package_family("DO-99_XX") is None
    assert "soic" in PACKAGE_FAMILIES.values()


def test_dimension_tokens_are_weak_evidence_by_construction():
    """Decimals always count; integers only from 2 up, and only up to 4 digits."""
    assert dimension_tokens("-,D5xL11mm") == {5.0, 11.0}
    assert dimension_tokens("CAP-TH_BD5.0-P2.00-D0.8-FD") == {5.0, 2.0, 0.8}
    assert dimension_tokens("HDR-TH_3P-P2.54-V-F") == {3.0, 2.54}
    assert dimension_tokens("0603") == set()


def test_compare_names_grades_by_precedence_and_reports_the_reason():
    """Size code first, then family, then agreement, then "cannot compare"."""
    # size code
    assert _compare_names("0805", "C0603")[0] == "size-code"
    assert _compare_names("0603", "C0603")[0] == "agree"
    assert _compare_names("0805", "LED0805-R-RD")[0] == "agree"
    # family
    assert _compare_names("SO-8", "TSSOP-16_L5.0-W4.4-P0.65-LS6.4-BL")[0] == "package"
    assert _compare_names("SO-8", "PG-DSO-8_L5.0-W4.0-P1.27-LS6.0-BL")[0] == "agree"
    # weak evidence agrees but never convicts
    assert _compare_names("-,D10xL15mm", "CAP-TH_BD10.0-P5.00-D0.6-FD-A")[0] == "agree"
    assert _compare_names("-,D5xL11mm", "CAP-TH_BD5.0-P2.00-D0.8-FD")[0] == "agree"
    # nothing comparable at all
    assert _compare_names("SMD", "USB-C-SMD_TYPE-C-6PIN-2MD-073")[0] == "undecidable"
    assert _compare_names("插件", "M3螺丝")[0] == "undecidable"
    assert _compare_names("SMC(DO-214AB)", "SOT-23-5_L2.9-W1.6-P0.95-LS2.8-BR")[0] == "package"


# ---------------------------------------------------------------------------
# structure gate
# ---------------------------------------------------------------------------


def test_the_rule_is_registered_and_the_list_is_still_the_truth():
    """151 inserts one rule, immediately before the geometry sweep.

    Same pin the 126-family batches flip: a rule that exists but is not listed
    does not run, and a rule listed in the wrong place re-orders ``checksRun``
    for every reader comparing two reports.
    """
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert RULE_ID in ids
    assert ids.index(RULE_ID) == ids.index("pcb-component-spacing") - 1
    rule = next(r for r in BUILTIN_PCB_RULES if r.id == RULE_ID)
    assert isinstance(rule, FootprintConsistency)
    assert rule.level == "L1-pcb-geometry"
    # 钉 7: no threshold to quote — every judgement here is equal/not-equal, so
    # the source says "house rule 待裁" rather than borrowing a standard.
    assert "house rule" in rule.source


def test_the_new_context_field_is_declared_and_defaults_to_empty():
    """``board_uuid`` is what makes the per-board pairing possible."""
    fields = {f.name for f in dataclasses.fields(PcbReviewContext)}
    assert "board_uuid" in fields
    ctx = PcbReviewContext(board=BoardGeometry(), board_title="PCB1")
    assert ctx.board_uuid == ""


def test_the_rule_runs_in_the_real_runner_with_the_board_stamped():
    """Through ``run_pcb_review`` the finding carries the PCB document's title."""
    findings, section = _run(FOC_100)
    rows = _board_rows(section, findings, "PCB1")
    assert rows, "the footprint rule is in BUILTIN_PCB_RULES and fires here"
    assert all(row.board == "PCB1" for row in rows)
    assert all(row.rule_id == RULE_ID for row in rows)
    assert RULE_ID in section["boards"][0]["checksRun"]


# ---------------------------------------------------------------------------
# synthetic states
# ---------------------------------------------------------------------------


def test_a_pad_count_mismatch_is_an_error_and_names_the_missing_pins():
    """3 declared pins against a 5-pad footprint: 焊盘数不符, ERROR."""
    board, pcb_model = _pcb({"U1": "SOT-23-5_L2.9-W1.6-P0.95-LS2.8-BR"}, {"U1": 5})
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"U1": ("SOT-23-5", 3)}))
    )
    errors = _by_severity(findings, "ERROR")
    assert [f.target.component_ref for f in errors] == ["U1"]
    assert "焊盘数" in errors[0].message
    assert "4, 5" in errors[0].message  # the pads the schematic never declared
    assert errors[0].target.measurement["unit"] == "mil"


def test_a_size_code_mismatch_is_an_error_and_carries_the_measured_pads():
    """``0603`` declared against an 0805-sized land: the geometry is the point."""
    board, pcb_model = _pcb(
        {"C1": "C0805"}, {"C1": 2}, sizes={"C1": (55.512, 53.15)}
    )
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"C1": ("0603", 2)}))
    )
    errors = _by_severity(findings, "ERROR")
    assert len(errors) == 1
    assert "封装尺寸码不符" in errors[0].message
    assert any("55.512" in line for line in errors[0].evidence)
    # The structured reading is the pad span of the placed footprint, in mil —
    # 20 here because the two synthetic pads are centred 20 mil apart.
    assert errors[0].target.measurement == {"kind": "distance", "value": 20.0, "unit": "mil"}


def test_a_same_name_different_geometry_pair_is_a_warn():
    """同名封装、实测几何不同 → WARN（名字不指向唯一一个物理封装）."""
    board, pcb_model = _pcb(
        {"R1": "RES-0603", "R2": "RES-0603"}, {"R1": 2, "R2": 2},
        sizes={"R1": (30.0, 30.0), "R2": (50.0, 50.0)},
    )
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"R1": ("0603", 2), "R2": ("0603", 2)}))
    )
    warns = _by_severity(findings, "WARN")
    assert len(warns) == 1
    assert "RES-0603" in warns[0].message
    assert any("R1" in line for line in warns[0].evidence)
    assert any("R2" in line for line in warns[0].evidence)
    assert "30.000×30.000" in " ".join(warns[0].evidence)
    assert "50.000×50.000" in " ".join(warns[0].evidence)


def test_the_same_name_with_the_same_geometry_is_not_a_warn():
    """Two library documents, one geometry: the name still means one thing."""
    board, pcb_model = _pcb(
        {"R1": "RES-0603", "R2": "RES-0603"}, {"R1": 2, "R2": 2},
        sizes={"R1": (30.0, 30.0), "R2": (30.0, 30.0)},
    )
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"R1": ("0603", 2), "R2": ("0603", 2)}))
    )
    assert _by_severity(findings, "WARN") == []


def test_a_part_the_pcb_never_places_is_an_error():
    """原理图有、PCB 没放 → ERROR，接 conn 类的对称漂移口径."""
    board, pcb_model = _pcb({"C1": "C0603"}, {"C1": 2})
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"C1": ("0603", 2), "R7": ("0603", 2)}))
    )
    errors = _by_severity(findings, "ERROR")
    assert [f.target.component_ref for f in errors] == ["R7"]
    assert "没摆" in errors[0].message
    assert errors[0].board == ""  # the runner stamps it, a bare check does not


def test_a_part_the_schematic_never_declares_is_an_error_too():
    """The other direction of the same drift, reported the same way."""
    board, pcb_model = _pcb({"C1": "C0603", "Q9": "SOT-23-5_L2.9-W1.6-P0.95-LS2.8-BR"},
                            {"C1": 2, "Q9": 5})
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, _sch({"C1": ("0603", 2)}))
    )
    errors = _by_severity(findings, "ERROR")
    assert [f.target.component_ref for f in errors] == ["Q9"]
    assert "原理图" in errors[0].message and "没有" in errors[0].message


def test_an_unreadable_board_link_is_reported_rather_than_guessed():
    """A multi-board project with no matching uuid: say so, compare nothing."""
    class Project:  # a ProjectModel's one relevant shape
        boards = [type("B", (), {"board": type("R", (), {"uuid": "other", "title": "BoardX"})()})()]

    board, pcb_model = _pcb({"C1": "C0603"}, {"C1": 2})
    findings = FootprintConsistency().check(
        _ctx(board, pcb_model, Project(), board_uuid="nope")
    )
    infos = _by_severity(findings, "INFO")
    assert len(infos) == 1
    assert "板链" in infos[0].message or "未做" in infos[0].message
    assert "nope" in " ".join(infos[0].evidence)


# ---------------------------------------------------------------------------
# the acceptance boards
# ---------------------------------------------------------------------------


def test_foc_100_pcb1_reports_six_size_code_errors_and_no_pad_count_ones():
    """The measured anchor: 毕设FOC 1.0.0's real 0805-vs-0603 history problem.

    ``C17``/``C8``/``C98``/``C99`` sit on ``C0603`` and ``U3``/``U7`` on
    ``R0603`` while the schematic declares ``0805`` for all six. The pads are
    what makes it real: this board's own ``C0805`` land pattern measures
    55.512 × 53.150 mil against ``C0603``'s 31.496 × 35.433.
    """
    findings, section = _run(FOC_100)
    rows = _board_rows(section, findings, "PCB1")
    errors = _by_severity(rows, "ERROR")
    assert _targets(errors) == {"C8", "C17", "C98", "C99", "U3", "U7"}
    assert all("封装尺寸码不符" in row.message for row in errors)
    assert all("0805" in row.message and "0603" in row.message for row in errors)

    c17 = next(row for row in errors if row.target.component_ref == "C17")
    assert any("31.496" in line for line in c17.evidence)
    assert any("CC0805KRX7R9BB104" in line for line in c17.evidence)
    # The MPN's own size code is the second, independent piece of evidence.
    assert any("MPN" in line and "0805" in line for line in c17.evidence)

    # No 焊盘数不符 anywhere on this board: 122 parts, 0 count disagreements.
    assert "焊盘数不符 0" in _by_severity(rows, "INFO")[-1].message


def test_foc_100_pcb1_agrees_on_the_names_it_can_compare():
    """The pairs a naive string comparison would have flagged as mismatches."""
    findings, section = _run(FOC_100)
    rows = _board_rows(section, findings, "PCB1")
    reported = _targets(rows)
    # Same family, different spelling — deliberately silent.
    for designator in ("D1", "U4", "U1", "L1", "CN2"):
        if designator not in {
            name for name in (row.target.component_ref for row in rows if row.target)
        }:
            continue
        assert designator not in reported, designator
    summary = _by_severity(rows, "INFO")[-1].message
    assert "比了 122 个两边都有的器件" in summary
    assert "尺寸码不符 6" in summary
    assert "封装族不符 0" in summary
    assert "一致 113" in summary


def test_foc_100_pcb2_and_robot_report_no_footprint_defects():
    """PCB2 (the screw plate) and ROBOT are clean; the silence is measured."""
    findings, section = _run(FOC_100)
    rows = _board_rows(section, findings, "PCB2")
    assert _by_severity(rows, "ERROR") == []
    assert "尺寸码不符 0" in _by_severity(rows, "INFO")[-1].message

    findings, section = _run(ROBOT)
    rows = _board_rows(section, findings, "PCB1")
    assert _by_severity(rows, "ERROR") == []
    assert _by_severity(rows, "WARN") == []
    summary = _by_severity(rows, "INFO")[-1].message
    assert "比了 49 个两边都有的器件" in summary
    assert "尺寸码不符 0" in summary and "封装族不符 0" in summary


def test_robot_drv1_exposed_pad_does_not_false_positive_the_pad_count():
    """DRV8313: the symbol puts the EP on pin 29, the footprint has 29 pads.

    This is the case a 「count the pads」 check without the EP story would get
    wrong, so it is asserted by name rather than left to the board's total.
    """
    findings, section = _run(ROBOT)
    rows = _board_rows(section, findings, "PCB1")
    assert "DRV1" not in _targets(rows)


def test_foc_100_undecidable_pairs_are_reported_as_undecidable():
    """UNKNOWN discipline: say「无从比较」and print both strings, never guess."""
    findings, section = _run(FOC_100)
    rows = _board_rows(section, findings, "PCB1")
    infos = [row for row in _by_severity(rows, "INFO") if "无从比较" in row.message]
    assert _targets(infos) == {"USB1", "U12"}
    usb = next(row for row in infos if row.target.component_ref == "USB1")
    assert "'SMD'" in usb.message
    assert "'USB-C-SMD_TYPE-C-6PIN-2MD-073'" in usb.message
    # PCB 侧读不出封装 is a *different* row from 无从比较 — the reasons differ.
    other = [
        row for row in _by_severity(rows, "INFO") if "读不出封装" in row.message
    ]
    assert _targets(other) == {"CN1"}


def test_foc_110_pcb3_reports_the_six_declared_but_unplaced_resistors():
    """The presence half, on the one board where it fires.

    ``Board3`` declares ``R1``…``R6`` (all ``0805``, ``0805W8J0100T5E``) and
    ``PCB3`` places none of them.
    """
    findings, section = _run(FOC_110)
    rows = _board_rows(section, findings, "PCB3")
    errors = _by_severity(rows, "ERROR")
    assert _targets(errors) == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert all("没摆" in row.message for row in errors)
    assert all(row.board == "PCB3" for row in errors)
    summary = _by_severity(rows, "INFO")[-1].message
    assert "原理图 Board3" in summary
    assert "原理图有而 PCB 没摆 6 个" in summary


def test_foc_110_does_not_leak_board3s_missing_parts_onto_pcb1():
    """The pairing is by declared board uuid, not by designator overlap.

    1.1.0's ``Board1`` and ``Board3`` both own ``R1``…``R6``; a designator-overlap
    pairing would have blamed PCB1 for six parts it does place, and PCB1's own
    ``R1``…``R6`` are ``0603`` parts — different objects entirely.
    """
    findings, section = _run(FOC_110)
    rows = _board_rows(section, findings, "PCB1")
    assert _targets(_by_severity(rows, "ERROR")) == {
        "C26", "C27", "C28", "C29", "C30", "C31", "C35", "C36",
        "C41", "C42", "C43", "C44", "U10", "U14",
    }
    assert all("没摆" not in row.message for row in _by_severity(rows, "ERROR"))
    summary = _by_severity(rows, "INFO")[-1].message
    assert "原理图 Board1" in summary
    assert "原理图有而 PCB 没摆 0 个" in summary


def test_every_board_pairs_itself_with_the_schematic_board_it_declares():
    """Each PCB document's ``META.board`` resolves — no board is left unpaired."""
    for path, expected in (
        (FOC_100, {"PCB1": "Board1", "PCB2": "Board2"}),
        (FOC_110, {"PCB1": "Board1", "PCB2": "Board2", "PCB3": "Board3"}),
        (ROBOT, {"PCB1": "Board1"}),
    ):
        findings, section = _run(path)
        assert {entry["title"] for entry in section["boards"]} == set(expected)
        for title, board_title in expected.items():
            rows = _board_rows(section, findings, title)
            summary = _by_severity(rows, "INFO")[-1]
            assert f"原理图 {board_title}" in summary.message
            assert not any("封装对账未做" in row.message for row in rows)


def test_the_summary_reconciles_with_the_rows_it_summarises():
    """No finding is lost between the per-part rows and the per-board count."""
    for path in (FOC_100, FOC_110, ROBOT):
        findings, section = _run(path)
        for entry in section["boards"]:
            rows = _board_rows(section, findings, entry["title"])
            summary = _by_severity(rows, "INFO")[-1].message
            size_code = len(
                [r for r in _by_severity(rows, "ERROR") if "尺寸码不符" in r.message]
            )
            unplaced = len(
                [r for r in _by_severity(rows, "ERROR") if "没摆" in r.message]
            )
            assert f"尺寸码不符 {size_code}" in summary, entry["title"]
            assert f"原理图有而 PCB 没摆 {unplaced} 个" in summary, entry["title"]


def test_a_library_id_in_the_schematic_field_is_named_as_such():
    """llc's schematic side stores a **uuid**, not a footprint name (151's finding).

    ``llc_board.epro2``'s ``C1``/``C2``/``C5``/``C6`` carry
    ``Component.footprint == '0733d61b8033ac9c'`` — a library id that
    ``parsers/schematic.py`` writes into the footprint field when the DEVICE has
    no ``Supplier Footprint`` and the instance's own ``Footprint`` attribute
    holds an id. The rule must not tokenize those hex characters into
    「尺寸数」 and print a fake measurement; it names the reason instead. This is
    a **model-layer** observation, recorded here and not fixed in this batch.
    """
    path = FIXTURES / "llc_board.epro2"
    findings, section = _run(path)
    rows = _board_rows(section, findings, "PCB1")
    ids = [
        row for row in _by_severity(rows, "INFO")
        if "库件 id" in row.message and "'0733d61b8033ac9c'" in row.message
    ]
    assert _targets(ids) == {"C1", "C2", "C5", "C6"}
    assert all("无从比较" in row.message for row in ids)


def test_a_context_with_nothing_to_reconcile_says_which_half_is_missing():
    """No netlist view → nothing to reconcile → no findings, and no crash.

    A context with **no schematic model at all** is a different statement from
    a board with none: the first is "this caller did not hand me the other
    side" and is reported; the second is "there is no PCB view" and is silence,
    because a rule cannot even measure what is on the board.
    """
    assert FootprintConsistency().check(  # no PCB netlist view
        _ctx(BoardGeometry(), None, _sch({"C1": ("0603", 2)}))
    ) == []
    rows = FootprintConsistency().check(  # no schematic side handed in
        PcbReviewContext(
            board=BoardGeometry(), board_title="X", pcb_model=DesignModel()
        )
    )
    assert [row.severity for row in rows] == ["INFO"]
    assert "封装对账未做" in rows[0].message
    assert "没有给原理图模型" in rows[0].message
