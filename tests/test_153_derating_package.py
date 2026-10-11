"""Tests for task 153: the derating physical-layer rule (E 阶段第三棒).

The rule answers one question per resistor: **does the package it is actually
placed in survive the voltage across it** (and, as a second reading, the power
P = U²/R that voltage implies). This file pins, in order:

* **the vocabulary readers** — the package-limit table and its citations, the
  size-code mapping, the "is this a resistor / how many ohms" doors, and the
  series-string finder. Pure functions, no fixture, so a change in any of them
  fails here rather than in a report nobody diffs;
* **the structure gate** — the rule is in ``BUILTIN_PCB_RULES`` after
  ``pcb-silk-designator``, at ``L2-facts`` (its limits are datasheet columns,
  not distances) and with a ``source`` that says the derating judgement is a
  house rule 待裁;
* **the synthetic states** — over-voltage, over-power, within-limit, the two
  series-split states (split within limit → no finding; split over limit → one
  finding carrying the *shared* voltage), an unpriced series end, an unknown
  package, a 0 Ω jumper, an unpriced net, and the intent contract's two voltage
  slots — each built by hand so the assertion is about the rule and not about a
  fixture's contents;
* **the three acceptance boards** — 毕设FOC 1.0.0, 毕设FOC 1.1.0 and ROBOT ctrl
  FOC, with the measured numbers the batch was accepted on;
* **岳's flyback spec** — ``blocklib/specs/flyback_uc3845.circuit.json``, whose
  ``R3``/``R15`` are two ``75k 1% 0603`` in series between ``HVDC`` and
  ``CLAMP``. This is the live sample for 「串联分压不误报」: with the spec's own
  ``operatingConditions.inputVoltage`` (311 V) as the only priced rail the rule
  files **no verdict whatsoever** (the string's far end ``CLAMP`` has no stated
  voltage, so the string total is unreadable and no part is accused), and when
  the engineer prices ``CLAMP`` at 150 V the two parts are judged against the
  **split** 80.5 V — never against the whole string's 161 V, and never against
  the 311 V a naive tool would book against one 0603.

The acceptance anchors, measured 2026-10-11 (see ``outputs/153/recon.txt``,
which is the same run rendered as evidence):

* **all three boards: 0 WARN / 0 ERROR.** That is the honest reading of the
  data, not a skipped check: every one of their resistors sits between nets
  whose voltages nobody states (measured counts per board below), and the ones
  whose two ends *are* priced are the GND↔PGND ties at 0 V. The rule says so in
  its per-board summary, naming the unpriced nets and pointing at 139's
  ``intent-missing`` list — the UNKNOWN discipline rather than a guess.
* **flyback spec**: 0 verdicts as-is; 2 WARN (R3, R15) at 80.5 V once ``CLAMP``
  is priced at 150 V.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.designintent import DesignIntent, IntentRail
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.derating import (
    CHIP_RESISTOR_LIMITS,
    METRIC_SIZE_ALIASES,
    SOURCES,
    ChipLimit,
    DeratingPackage,
    ResistiveEdge,
    _is_resistor,
    _looks_like_ohms,
    chip_limit,
    resistance_ohms_of,
    series_strings,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SPEC = Path(__file__).resolve().parents[1] / "blocklib" / "specs" / "flyback_uc3845.circuit.json"
SPEC_LIBRARY = SPEC.with_name("flyback_uc3845.library.json")

RULE_ID = "pcb-derating-package"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(path: Path, rules=None):
    model = build_project_model(path)
    return run_pcb_review(path, model=model, rules=rules or [DeratingPackage()])


def _board_rows(section: dict, findings: list, title: str) -> list:
    for entry in section["boards"]:
        if entry["title"] == title:
            return [findings[index] for index in entry["findings"]]
    raise AssertionError(f"no board {title!r}")


def _by_severity(rows: list, severity: str) -> list:
    return [row for row in rows if row.severity == severity]


def _ctx(
    *,
    parts: dict[str, tuple[str, str, str]],
    nets: dict[str, list[tuple[str, str]]],
    rails: dict[str, str] | None = None,
    title: str = "SYNTH",
) -> PcbReviewContext:
    """A synthetic context: ``(value, footprint, Type)`` per designator + nets.

    ``nets`` is net name → ``[(designator, pin_number), …]``. The same model is
    handed to both views (a synthesis of a board whose schematic and PCB
    declarations agree), which is what makes the assertions about the rule
    rather than about a fixture.
    """
    components = {
        designator: Component(
            uid=designator, designator=designator, value=value, footprint=footprint,
            props={"Type": type_word} if type_word else {},
            pins=[Pin(number=pin, name=pin) for _d, pin in members],
        )
        for designator, (value, footprint, type_word) in parts.items()
        for members in [
            [(d, p) for group in nets.values() for d, p in group if d == designator]
        ]
    }
    model = DesignModel(
        components=components,
        nets={
            name: Net(name=name, pins=[tuple(member) for member in members])
            for name, members in nets.items()
        },
    )
    intent = None
    if rails:
        intent = DesignIntent(
            rails=[
                IntentRail(net=net, slots={"voltage": volts}, provenance="user_stated")
                for net, volts in rails.items()
            ]
        )
    return PcbReviewContext(
        board=None, board_title=title, model=model, intent=intent, pcb_model=model,
    )


def _messages(rows: list) -> str:
    return " || ".join(f"{row.severity}:{row.message}" for row in rows)


# ---------------------------------------------------------------------------
# the package table and its citations
# ---------------------------------------------------------------------------


def test_every_limit_carries_a_citation_that_exists():
    """No number without a source, and no source without a table entry.

    每档至少一条出处，且出处键都在 :data:`SOURCES` 里——「先查可靠出处再定表」
    这条纪律的机械闸：一个拍脑袋的数字（哪怕值对）在这里就红了。
    """
    assert CHIP_RESISTOR_LIMITS, "the table is the rule's whole physics"
    for code, limit in CHIP_RESISTOR_LIMITS.items():
        assert limit.sources, f"size code {code} has no citation"
        for key in limit.sources:
            assert key in SOURCES, f"{code} cites unknown source {key!r}"
        assert limit.volts > 0.0 and limit.watts > 0.0
        assert SOURCES[key].startswith(("Yageo", "Viking", "Cinetech", "Vishay"))


def test_the_four_common_sizes_match_the_published_columns():
    """0603 / 0805 / 1206 / 2512 —— 手册上的那一栏，逐档钉死。

    Numbers as published by the cited datasheets (Yageo AC series Table 2 for the
    working voltage, the POWER RATING list for the watts): 0603 = 50 V / 0.1 W,
    0805 = 150 V / 0.125 W, 1206 = 200 V / 0.25 W, 2512 = 200 V / 1 W. The
    **conservative** take is visible in the 1210 row, where Yageo says 1/2 W and
    Viking says 1/3 W and the table keeps 1/3 W, and in the 0603 voltage, where
    Vishay's thin-film 75 V does not raise the厚膜 50 V floor.
    """
    assert CHIP_RESISTOR_LIMITS["0603"].volts == 50.0
    assert CHIP_RESISTOR_LIMITS["0603"].watts == 0.1
    assert CHIP_RESISTOR_LIMITS["0805"].volts == 150.0
    assert CHIP_RESISTOR_LIMITS["0805"].watts == 0.125
    assert CHIP_RESISTOR_LIMITS["1206"].volts == 200.0
    assert CHIP_RESISTOR_LIMITS["1206"].watts == 0.25
    assert CHIP_RESISTOR_LIMITS["2512"].volts == 200.0
    assert CHIP_RESISTOR_LIMITS["2512"].watts == 1.0
    # The conservative direction on the one disagreement between two sources.
    assert CHIP_RESISTOR_LIMITS["1210"].watts == pytest.approx(1.0 / 3.0)
    assert set(CHIP_RESISTOR_LIMITS["1210"].sources) == {"yageo-ac", "viking-rt"}
    # 0603 keeps the厚膜 floor of 50 V even though Vishay's thin film says 75 V.
    assert "vishay-mcx" in CHIP_RESISTOR_LIMITS["0603"].sources


def test_the_limit_line_and_citation_are_readable_evidence():
    limit = CHIP_RESISTOR_LIMITS["0805"]
    assert limit.line().startswith("150 V max working voltage, 0.125 W rated power")
    assert "yageo-ac" in limit.line()
    assert "datasheet.live" in limit.citation() or "yageo" in limit.citation()


def test_chip_limit_maps_the_names_that_actually_appear():
    """``R0603``/``C0805``/metric spellings → the imperial size code of the table."""
    assert chip_limit("R0603") == ("0603", CHIP_RESISTOR_LIMITS["0603"])
    assert chip_limit("C0805")[0] == "0805"
    assert chip_limit("LED0805-R-RD")[0] == "0805"
    assert chip_limit("R1206")[0] == "1206"
    assert chip_limit("L2512")[0] == "2512"
    # The metric spellings of the same physical sizes.
    assert chip_limit("R1608")[0] == "0603"
    assert chip_limit("C2012")[0] == "0805"
    assert chip_limit("R3216")[0] == "1206"
    assert chip_limit("C3225")[0] == "1210"
    assert METRIC_SIZE_ALIASES["1608"] == "0603"
    # No size code, or a size code with no published column → no verdict.
    assert chip_limit("RES-TH-17K8") is None
    assert chip_limit("") is None
    assert chip_limit("CAP-TH_BD5.0-P2.00-D0.8-FD") is None
    # 2016 (metric 2.0×1.6 mm) has no imperial twin and is deliberately not mapped.
    assert "2016" not in METRIC_SIZE_ALIASES
    assert chip_limit("L2016") is None


def test_the_source_table_names_each_document_with_its_url():
    for key, text in SOURCES.items():
        assert "http" in text, f"{key} must be checkable, not a claim"
        assert len(text) > 120, f"{key} must name the table it came from"


# ---------------------------------------------------------------------------
# the two doors: is this a resistor, and how many ohms
# ---------------------------------------------------------------------------


def test_ohm_notation_recognises_the_spellings_the_decoder_refuses() -> None:
    """``0R`` is an ohm spelling even though the value decoder returns None.

    Measured: ``parse_resistance_ohms('0R')`` is ``None`` while ``'1R5'``,
    ``'R5'``, ``'0R01'`` parse — and 毕设FOC's 0 Ω ground ties are written
    ``0R``. The rule recognises the *notation* and refuses to decode it (no
    second value grammar inside a rule), which is why the part is still judged
    on the voltage path and its power row reads UNKNOWN.
    """
    assert _looks_like_ohms("0R") is True
    assert _looks_like_ohms("0R01") is True
    assert _looks_like_ohms("10K") is True
    assert _looks_like_ohms("5mΩ") is True
    assert _looks_like_ohms("75k 1% 0603") is False  # needs the Type door
    assert _looks_like_ohms("4N60 (600V 4A NMOS)") is False
    assert _looks_like_ohms("") is False
    # The value-equals-footprint noise (151's model-layer seam, mirrored here).
    assert _looks_like_ohms("R0603", "R0603") is False
    assert _looks_like_ohms("R1206", "R0603") is True


def test_resistance_reader_needs_the_type_door_for_a_messy_value_field() -> None:
    """``75k 1% 0603`` reads 75 kΩ only when the library says it is a resistor.

    The token fallback is the flyback spec's own value spelling; it is gated on
    the library's ``Type`` so that a value field full of numbers on a part nobody
    declared a resistor (``4N60 (600V 4A NMOS)``) is never mined for a value.
    """
    assert resistance_ohms_of("75k 1% 0603", "R0603", "薄膜电阻") == 75000.0
    assert resistance_ohms_of("75k 1% 0603", "R0603", "") is None
    assert resistance_ohms_of("1R 1% 0603", "R0603", "电阻") == 1.0
    assert resistance_ohms_of("10k 0603", "R0603", "电阻") == 10000.0
    assert resistance_ohms_of("10K", "R0603", "") == 10000.0
    assert resistance_ohms_of("0R", "R0603", "电阻") is None  # notation, not a decode
    assert resistance_ohms_of("4N60 (600V 4A NMOS)", "TO251", "NMOS") is None
    # A token that is a package size is a size, not a value (core.values' own list).
    assert resistance_ohms_of("0603", "R0603", "电阻") is None
    # The value field holding the footprint name is model-layer noise, not 0.0603 Ω.
    assert resistance_ohms_of("R0603", "R0603", "") is None
    # Two candidate numbers is not one reading — refused rather than guessed.
    assert resistance_ohms_of("10k 22k 0603", "R0603", "电阻") is None


def test_the_resistor_doors_are_declarations_not_naming_conventions() -> None:
    assert _is_resistor("10K", "R0603", "") == (True, "值字段是欧姆的写法（'10K'）")
    assert _is_resistor("75k 1% 0603", "R0603", "薄膜电阻")[0] is True
    assert "Type" in _is_resistor("75k 1% 0603", "R0603", "薄膜电阻")[1]
    assert _is_resistor("4N60 (600V 4A NMOS)", "TO251", "NMOS")[0] is False
    assert _is_resistor("", "", "")[0] is False
    # An ``R``-named part with nothing electrical said about it is NOT a resistor.
    assert _is_resistor("", "R0603", "")[0] is False


# ---------------------------------------------------------------------------
# the series-string finder (岳's 反面案例, mechanically)
# ---------------------------------------------------------------------------


def _edges(*specs) -> list[ResistiveEdge]:
    return [ResistiveEdge(designator=d, net_a=a, net_b=b, ohms=o) for d, a, b, o in specs]


def test_two_equal_resistors_in_series_are_one_string():
    edges = _edges(
        ("R3", "CLAMP", "CLAMP_B", 75000.0),
        ("R15", "CLAMP_B", "HVDC", 75000.0),
    )
    members = {
        "CLAMP": frozenset({"C5", "D1", "R3"}),
        "CLAMP_B": frozenset({"R3", "R15"}),
        "HVDC": frozenset({"C5", "R15", "T1"}),
    }
    strings = series_strings(edges, members)
    assert len(strings) == 1
    string = strings[0]
    assert set(string.designators()) == {"R3", "R15"}
    assert set(string.ends) == {"CLAMP", "HVDC"}
    assert string.total is None and string.share == {}  # filled by _split, not here


def test_a_third_part_on_the_tap_breaks_the_string():
    """抽头上有第三个器件就不是分压问题了——本规则不猜（宁可不认）。"""
    edges = _edges(
        ("R3", "CLAMP", "TAP", 1000.0),
        ("R15", "TAP", "GND", 1000.0),
    )
    members = {
        "CLAMP": frozenset({"R3", "C1"}),
        "TAP": frozenset({"R3", "R15", "U1"}),  # U1 also hangs on the tap
        "GND": frozenset({"R15", "C2"}),
    }
    assert series_strings(edges, members) == []


def test_a_three_deep_string_is_found_and_a_cycle_is_not():
    edges = _edges(
        ("R1", "A", "B", 1000.0),
        ("R2", "B", "C", 2000.0),
        ("R3", "C", "D", 3000.0),
    )
    members = {
        "A": frozenset({"R1", "X"}),
        "B": frozenset({"R1", "R2"}),
        "C": frozenset({"R2", "R3"}),
        "D": frozenset({"R3", "Y"}),
    }
    strings = series_strings(edges, members)
    assert len(strings) == 1
    assert set(strings[0].designators()) == {"R1", "R2", "R3"}
    assert set(strings[0].ends) == {"A", "D"}
    # A single resistor is not a string (it is judged on its own two nets)…
    assert series_strings(_edges(("R1", "A", "B", 1000.0)), {}) == []
    # …and a closed loop of resistors has no free end, so it is not a divider.
    loop = _edges(
        ("R1", "A", "B", 1000.0), ("R2", "B", "C", 1000.0), ("R3", "C", "A", 1000.0)
    )
    loop_members = {
        "A": frozenset({"R1", "R3"}),
        "B": frozenset({"R1", "R2"}),
        "C": frozenset({"R2", "R3"}),
    }
    assert series_strings(loop, loop_members) == []


# ---------------------------------------------------------------------------
# the structure gate
# ---------------------------------------------------------------------------


def test_the_rule_is_registered_where_153_says_and_is_a_house_rule():
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert RULE_ID in ids
    assert ids.index(RULE_ID) == ids.index("pcb-silk-designator") + 1
    rule = next(rule for rule in BUILTIN_PCB_RULES if rule.id == RULE_ID)
    assert isinstance(rule, DeratingPackage)
    assert rule.level == "L2-facts"
    assert "house rule" in rule.source and "待裁" in rule.source
    assert "不套降额系数" in rule.source
    assert rule.title


# ---------------------------------------------------------------------------
# synthetic states: the verdict ladder
# ---------------------------------------------------------------------------


def test_a_0603_across_300_v_is_a_warn_with_both_numbers():
    """The headline state: the package column is below the voltage it carries."""
    ctx = _ctx(
        parts={"R1": ("100kΩ", "R0603", "薄膜电阻")},
        nets={"HVDC": [("R1", "1")], "PGND": [("R1", "2")]},
        rails={"HVDC": "300V"},
    )
    rows = DeratingPackage().check(ctx)
    warns = _by_severity(rows, "WARN")
    assert len(warns) == 1
    message = warns[0].message
    assert "封装耐压不足" in message
    assert "300 V" in message and "50 V" in message and "0603" in message
    assert warns[0].target.component_ref == "R1"
    assert set(warns[0].target.net_refs) == {"HVDC", "PGND"}
    evidence = "\n".join(warns[0].evidence)
    assert "yageo-ac" in evidence and "Max. Working Voltage" in evidence
    assert "不套降额系数" in evidence
    # P = 300²/100k = 0.9 W > 0.1 W, so the power row is reported beside it.
    assert "P = U²/R = 0.9 W" in evidence
    # One defect, one finding: the second comparison stays in the evidence.
    assert len([row for row in warns if row.target.component_ref == "R1"]) == 1


def test_within_the_package_column_nothing_is_reported():
    """150 V across a 1206 (200 V / 0.25 W): 1.5 W… is over, so pick a large R."""
    ctx = _ctx(
        parts={"R1": ("1MΩ", "R1206", "薄膜电阻")},
        nets={"HVDC": [("R1", "1")], "PGND": [("R1", "2")]},
        rails={"HVDC": "150V"},
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    assert _by_severity(rows, "ERROR") == []
    assert _by_severity(rows, "INFO"), "the board reading is still filed"


def test_the_limit_exactly_reached_is_not_over_the_limit():
    """``>`` and not ``>=``: 50 V across a 0603 is the column, not a violation."""
    ctx = _ctx(
        parts={"R1": ("1MΩ", "R0603", "薄膜电阻")},
        nets={"HVDC": [("R1", "1")], "PGND": [("R1", "2")]},
        rails={"HVDC": "50V"},
    )
    assert _by_severity(DeratingPackage().check(ctx), "WARN") == []


def test_power_alone_can_be_the_finding():
    """A 0603 100 Ω on a 24 V rail: the package voltage is fine, the watts are not."""
    ctx = _ctx(
        parts={"R1": ("100Ω", "R0603", "薄膜电阻")},
        nets={"+24V": [("R1", "1")], "PGND": [("R1", "2")]},
        rails={"+24V": "24V"},
    )
    rows = DeratingPackage().check(ctx)
    warns = _by_severity(rows, "WARN")
    assert len(warns) == 1
    assert "封装功率不足" in warns[0].message
    assert "5.76 W" in warns[0].message and "0.1 W" in warns[0].message
    evidence = "\n".join(warns[0].evidence)
    assert "24 V ≤ 该封装档的最大工作电压 50 V（未越限）" in evidence


def test_a_grounded_resistor_pair_is_not_a_derating_question():
    """GND↔PGND is 0 V: two ground nets, no difference to derate (127b's ruling)."""
    ctx = _ctx(
        parts={"R48": ("0R", "R1206", "薄膜电阻")},
        nets={"GND": [("R48", "1")], "PGND": [("R48", "2")]},
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    summary = _by_severity(rows, "INFO")[-1]
    # 0R is the notation the decoder refuses → judged on voltage, no power row.
    assert "阻值读不出" in "\n".join(summary.evidence)


def test_a_zero_ohm_jumper_is_named_and_not_judged():
    ctx = _ctx(
        parts={"R8": ("0Ω", "R0603", "薄膜电阻")},
        nets={"+24V": [("R8", "1")], "PGND": [("R8", "2")]},
        rails={"+24V": "24V"},
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    assert "0 Ω 跳线" in "\n".join(_by_severity(rows, "INFO")[-1].evidence)


def test_an_unpriced_net_leaves_the_part_unknown_and_names_the_net():
    ctx = _ctx(
        parts={"R1": ("100kΩ", "R0603", "薄膜电阻")},
        nets={"+24V": [("R1", "1")], "FB": [("R1", "2")]},
        rails={"+24V": "24V"},
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    evidence = "\n".join(_by_severity(rows, "INFO")[-1].evidence)
    assert "'FB'" in evidence and "requirements.rails[net=…].voltage" in evidence


def test_a_package_with_no_published_column_is_not_judged():
    """A through-hole resistor has no size code → no verdict (UNKNOWN, named)."""
    ctx = _ctx(
        parts={"R7": ("17.8kΩ", "RES-TH-17K8", "薄膜电阻")},
        nets={"HVDC": [("R7", "1")], "PGND": [("R7", "2")]},
        rails={"HVDC": "300V"},
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    assert "封装档认不出" in "\n".join(_by_severity(rows, "INFO")[-1].evidence)


def test_the_contract_supplies_a_rail_voltage_and_wins():
    """139's double read: either slot prices the rail, and the rule reads it."""
    for slot in ("voltage", "targetVoltage"):
        model = DesignModel(
            components={
                "R1": Component(
                    uid="R1", designator="R1", value="100kΩ", footprint="R0603",
                    props={"Type": "薄膜电阻"},
                    pins=[Pin(number="1", name="1"), Pin(number="2", name="2")],
                )
            },
            nets={
                "HVDC": Net(name="HVDC", pins=[("R1", "1")]),
                "PGND": Net(name="PGND", pins=[("R1", "2")]),
            },
        )
        intent = DesignIntent(
            rails=[
                IntentRail(net="HVDC", slots={slot: "300V"}, provenance="user_stated")
            ]
        )
        ctx = PcbReviewContext(
            board=None, board_title="SYNTH", model=model, intent=intent, pcb_model=model,
        )
        rows = DeratingPackage().check(ctx)
        warns = _by_severity(rows, "WARN")
        assert len(warns) == 1, slot
        assert "300 V" in warns[0].message
        assert slot in "\n".join(warns[0].evidence)


# ---------------------------------------------------------------------------
# synthetic states: the series split
# ---------------------------------------------------------------------------


def _series_ctx(rails: dict[str, str], *, ohms: tuple[str, str] = ("75kΩ", "75kΩ"),
                footprint: str = "R0603") -> PcbReviewContext:
    """Two resistors in series between ``HVDC`` and ``CLAMP`` (the flyback shape)."""
    return _ctx(
        parts={
            "R3": (ohms[0], footprint, "薄膜电阻"),
            "R15": (ohms[1], footprint, "薄膜电阻"),
            "C5": ("1nF", "C0603", "无极性电容"),
            "T1": ("XFMR", "EE16", ""),
        },
        nets={
            "HVDC": [("C5", "2"), ("R15", "2"), ("T1", "1")],
            "CLAMP": [("C5", "1"), ("R3", "1")],
            "CLAMP_B": [("R3", "2"), ("R15", "1")],
        },
        rails=rails,
    )


def test_a_series_split_that_fits_is_not_reported_as_a_defect():
    """Two 0805 in series across 200 V: 100 V each < 150 V → no finding at all.

    This is 岳's 反面案例 in its cleanest form: the *string* is above a single
    0805's column, and a tool that booked the string's voltage against one part
    would file a false WARN. The rule files only the INFO reading that says it
    recognised and split the string.
    """
    ctx = _series_ctx(
        {"HVDC": "300V", "CLAMP": "100V"}, footprint="R0805", ohms=("1MΩ", "1MΩ")
    )
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    readings = [row for row in rows if "串联电阻串" in row.message]
    assert len(readings) == 1
    assert "100 V" in readings[0].message
    assert "R3 100 V" in readings[0].message and "R15 100 V" in readings[0].message
    assert "串两端" in readings[0].message and "200 V" in readings[0].message


def test_a_series_split_over_the_column_reports_the_share_not_the_string():
    """Two 0603 in series across 200 V → each WARNs at **100 V**, never at 200 V."""
    ctx = _series_ctx({"HVDC": "300V", "CLAMP": "100V"})
    rows = DeratingPackage().check(ctx)
    warns = _by_severity(rows, "WARN")
    assert {row.target.component_ref for row in warns} == {"R3", "R15"}
    for row in warns:
        assert "100 V" in row.message
        assert "200 V" not in row.message, "the string total must not be booked here"
        assert "串联串" in row.message
        assert row.target.counterpart_ref in {"R3", "R15"}
        evidence = "\n".join(row.evidence)
        assert "串联分压" in evidence
        assert "R3+R15" in evidence or "R15+R3" in evidence


def test_an_unpriced_series_end_yields_no_verdict_and_says_why():
    """The flyback as-is: ``CLAMP`` has no stated voltage → nothing is accused."""
    ctx = _series_ctx({"HVDC": "311V"})
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    readings = [row for row in rows if "串联电阻串" in row.message]
    assert len(readings) == 1
    assert "电压分不下来" in readings[0].message
    evidence = "\n".join(readings[0].evidence)
    assert "'CLAMP'" in evidence and "没有价" in evidence
    assert "311 V" in evidence


def test_unequal_resistors_split_by_resistance_not_by_count():
    """75 kΩ + 25 kΩ across 200 V → 150 V / 50 V (proportional, not averaged).

    The second half is the boundary pin too: R15's 50 V is exactly the 0603
    column, so it is *not* over it, while an 「average the string」 reading would
    have put 100 V on each part and reported both.
    """
    ctx = _series_ctx({"HVDC": "300V", "CLAMP": "100V"}, ohms=("75kΩ", "25kΩ"))
    rows = DeratingPackage().check(ctx)
    warns = {row.target.component_ref: row for row in _by_severity(rows, "WARN")}
    assert set(warns) == {"R3"}
    assert "150 V" in warns["R3"].message


def test_the_part_s_own_two_nets_win_over_the_split():
    """A declared fact beats a computed share, and the string is still named.

    三个网的价都写着时，每颗按**自己两个脚**的价判——HVDC 300 V / CLAMP_B 250 V
    给 R15 的是 50 V（不越限），而按阻值分下来会是 100 V（越限）：本规则报的是
    前者，因为两个网的声明是事实、份额是算出来的。R3 的 150 V（CLAMP 100 V ↔
    CLAMP_B 250 V）同样压过它的分压份额 100 V。
    """
    ctx = _series_ctx({"HVDC": "300V", "CLAMP": "100V", "CLAMP_B": "250V"})
    rows = DeratingPackage().check(ctx)
    warns = {row.target.component_ref: row for row in _by_severity(rows, "WARN")}
    assert set(warns) == {"R3"}, "R15's own two nets give 50 V, not the split's 100 V"
    assert "150 V" in warns["R3"].message
    assert "100 V" not in warns["R3"].message.split("，而")[-1]
    evidence = "\n".join(warns["R3"].evidence)
    assert "'CLAMP' = 100 V" in evidence and "'CLAMP_B' = 250 V" in evidence
    assert "串联分压" in evidence, "the structure is still named in the evidence"


# ---------------------------------------------------------------------------
# the three acceptance boards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        # (board, findings) — measured 2026-10-11, see outputs/153/recon.txt
        (FOC_100, [("PCB1", 38, 2, 36), ("PCB2", 3, 0, 3)]),
        (FOC_110, [("PCB3", 3, 0, 3), ("PCB1", 34, 2, 32), ("PCB2", 4, 0, 4)]),
        (ROBOT, [("PCB1", 13, 0, 13)]),
    ],
)
def test_the_three_acceptance_boards_have_no_derating_verdict(
    path: Path, expected: list[tuple[str, int, int, int]]
) -> None:
    """0 WARN / 0 ERROR on all three — and the counts that say why.

    ``(title, resistors recognised, parts with both ends priced, parts with a
    missing end)``. The zero is the honest reading: no resistor on these 24 V
    boards carries a priced rail difference, and the parts whose two ends are
    priced are the ground ties at 0 V. The per-board summary names the unpriced
    nets instead of guessing a voltage.
    """
    findings, section = _run(path)
    rows = {entry["title"]: _board_rows(section, findings, entry["title"])
            for entry in section["boards"]}
    assert [entry["title"] for entry in section["boards"]] == [
        title for title, _r, _p, _u in expected
    ]
    for title, resistors, priced, unpriced in expected:
        board_rows = rows[title]
        assert _by_severity(board_rows, "ERROR") == [], title
        assert _by_severity(board_rows, "WARN") == [], title
        assert len(board_rows) == 1, "the board reading is the only row"
        summary = board_rows[0]
        assert summary.severity == "INFO"
        assert f"认出 {resistors} 颗电阻" in summary.message
        assert f"两脚都有价的 {priced} 颗" in summary.message
        evidence = "\n".join(summary.evidence)
        if unpriced:
            assert f"没有价的 {unpriced} 颗" in evidence
            assert "requirements.rails[net=…].voltage" in evidence


def test_the_board_summary_quotes_the_sources_and_the_discipline() -> None:
    findings, section = _run(ROBOT)
    summary = _by_severity(_board_rows(section, findings, "PCB1"), "INFO")[0]
    evidence = "\n".join(summary.evidence)
    assert "Yageo AC series" in evidence
    assert "Viking" in evidence
    assert "不发明降额标准" in evidence
    assert "0 Ω 跳线" in evidence  # ROBOT's R8 is a real 0 Ω part
    assert "两个视图的 Value 字段不一致" in evidence


def test_a_board_with_no_resistors_at_all_still_reports_its_reading() -> None:
    """Silence is not a reading: a board with no resistors says 「认出 0 颗」."""
    ctx = _ctx(parts={"U1": ("", "SOT-23", "")}, nets={"A": [("U1", "1")]})
    rows = DeratingPackage().check(ctx)
    assert len(rows) == 1
    assert rows[0].severity == "INFO"
    assert "认出 0 颗电阻" in rows[0].message


def test_llc_carries_two_real_three_deep_series_strings() -> None:
    """llc is the extra live sample: two **three-deep** strings, and no verdict.

    ``R10+R9+R8`` (110 kΩ each, ``DC-`` → ``DCVN``) and ``R5+R6+R7`` (``DC+`` →
    ``DCVP``) are llc's own dividers. Neither end of either string has a stated
    voltage (llc prices no rail at all), so the split cannot be computed and the
    rule grades nothing — it files the two readings and the board summary. Pinned
    because this is a *real* board where the structure exists without a voltage
    to divide, i.e. the UNKNOWN half of the series logic.
    """
    llc = FIXTURES / "llc_board.epro2"
    findings, section = _run(llc)
    rows = _board_rows(section, findings, "PCB1")
    assert _by_severity(rows, "WARN") == []
    strings = sorted(row.message for row in rows if "串联电阻串" in row.message)
    assert len(strings) == 2
    assert any("R10" in text and "R9" in text and "R8" in text for text in strings)
    assert any("R5" in text and "R6" in text and "R7" in text for text in strings)
    summary = _by_severity(rows, "INFO")[-1]
    assert "认出 10 颗电阻" in summary.message
    assert "串联串 2 条" in summary.message


def test_a_context_without_a_netlist_files_nothing() -> None:
    ctx = PcbReviewContext(board=None, board_title="NONE", model=None, pcb_model=None)
    assert DeratingPackage().check(ctx) == []


# ---------------------------------------------------------------------------
# 岳's flyback spec: the live 「串联分压不误报」 sample
# ---------------------------------------------------------------------------


def _spec_input_volts(spec: dict) -> str:
    """The voltage the spec's own ``operatingConditions.inputVoltage`` states."""
    import re

    raw = str((spec.get("operatingConditions") or {}).get("inputVoltage") or "")
    found = re.search(r"[+-]?\d+(?:\.\d+)?\s*V", raw)
    assert found is not None, raw
    return found.group(0)


def _spec_ctx(priced: dict[str, str], title: str) -> PcbReviewContext:
    """The flyback spec as a context: the spec's own parts/nets, both views equal.

    ``Type`` comes from the spec's own symbol library (``flyback_uc3845.library.json``
    — each profile's title starts with the part's kind, ``Resistor 0603`` …), so
    「这是电阻」 is a declaration in the spec's files rather than something this
    test invented. The PCB view is the same model because a spec has no PCB
    document of its own; the physical package is the ``symbolRef`` (``R0603``).
    """
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    library = json.loads(SPEC_LIBRARY.read_text(encoding="utf-8"))
    titles = {
        str(profile.get("symbolRef")): str(profile.get("title") or "").splitlines()[0]
        for profile in library.get("profiles") or []
    }
    pins_of: dict[str, set[str]] = {}
    for net in spec["nets"]:
        for member in net["members"]:
            designator, _dot, pin = str(member).partition(".")
            pins_of.setdefault(designator, set()).add(pin)
    components = {
        str(part["id"]): Component(
            uid=str(part["id"]),
            designator=str(part["id"]),
            value=str(part.get("value") or ""),
            footprint=str(part.get("symbolRef") or ""),
            props={"Type": titles.get(str(part.get("symbolRef") or ""), "")},
            pins=[
                Pin(number=pin, name=pin)
                for pin in sorted(pins_of.get(str(part["id"]), {"1", "2"}))
            ],
        )
        for part in spec["parts"]
    }
    nets = {
        str(net["id"]): Net(
            name=str(net["id"]),
            pins=[tuple(str(member).split(".", 1)) for member in net["members"]],
        )
        for net in spec["nets"]
    }
    model = DesignModel(components=components, nets=nets)
    intent = DesignIntent(
        rails=[
            IntentRail(net=net, slots={"voltage": volts}, provenance="user_stated")
            for net, volts in priced.items()
        ]
    )
    return PcbReviewContext(
        board=None, board_title=title, model=model, intent=intent, pcb_model=model,
    )


def test_the_flyback_sample_as_is_files_no_verdict_about_R3_and_R15() -> None:
    """岳点名的反面案例，活样本：**零 verdict**。

    The spec's operating conditions price ``HVDC`` at 311 V and nothing prices
    ``CLAMP``, so the series string's total is unreadable. The rule recognises
    the string, says the voltage cannot be split and **names the rail to price** —
    and never books 311 V against a single 0603.
    """
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    ctx = _spec_ctx({"HVDC": _spec_input_volts(spec)}, "flyback spec")
    rows = DeratingPackage().check(ctx)
    assert _by_severity(rows, "WARN") == []
    assert _by_severity(rows, "ERROR") == []
    readings = [row for row in rows if "串联电阻串" in row.message]
    assert len(readings) == 1
    assert "R15" in readings[0].message and "R3" in readings[0].message
    evidence = "\n".join(readings[0].evidence)
    assert "'CLAMP'" in evidence
    assert "没有价" in evidence
    assert "311 V" in evidence
    # The parts themselves are named as unpriced in the board reading too.
    summary = _by_severity(rows, "INFO")[-1]
    assert "CLAMP_B" in "\n".join(summary.evidence)


def test_the_flyback_sample_judges_the_split_when_CLAMP_is_priced() -> None:
    """Price ``CLAMP`` at 150 V and the two 0603 are judged against **80.5 V**.

    The string total is 161 V (311 − 150) and each 75 kΩ part carries half. Both
    parts are over the 0603 column (50 V) so both WARN — with the number the part
    actually carries. The assertions that matter are the absent ones: neither
    message contains ``311`` or ``161``, i.e. the whole-string voltage is never
    booked against one part (the naive reading the batch exists to avoid).
    """
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    ctx = _spec_ctx(
        {"HVDC": _spec_input_volts(spec), "CLAMP": "150V"}, "flyback spec"
    )
    rows = DeratingPackage().check(ctx)
    warns = {row.target.component_ref: row for row in _by_severity(rows, "WARN")}
    assert set(warns) == {"R3", "R15"}
    for row in warns.values():
        assert "80.5 V" in row.message
        assert "311" not in row.message and "161" not in row.message
        assert "R0603" in row.message and "0603" in row.message
        evidence = "\n".join(row.evidence)
        assert "串联分压" in evidence
        assert "0.0864 W" in evidence  # 80.5²/75k, the power row beside it
    # The split reading itself is filed as INFO, and it carries both shares.
    readings = [row for row in rows if "串联电阻串" in row.message]
    assert len(readings) == 1
    assert "161 V" in readings[0].message
    assert "R3 80.5 V" in readings[0].message
    assert "R15 80.5 V" in readings[0].message
