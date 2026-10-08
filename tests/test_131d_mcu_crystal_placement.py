"""Task 131d: the OSC pin-role fix, and ``pcb-mcu-crystal-placement``.

The task came in two halves, and the first one is a **fix to a landed
module**: :mod:`boardwise.core.pinrole` read every oscillator pin as a supply
pin. ``PH0-OSC_IN`` splits on the hyphen (131a's ``_SEPARATORS``) into
``PH0-OSC`` + ``IN``, the ``IN`` half is a table hit, and an MCU's
crystal oscillator was handed to ``pcb-regulator-cap-distance`` as a
**regulator input**. The first group of tests here is therefore about a
classifier's word list: the four oscillator spellings the fixtures carry
(``OSC_IN``, ``OSC_OUT``, ``OSC32_IN``, ``OSC32_OUT``) and their hyphenated
port-pin forms, each of which used to resolve to ``IN`` / ``OUT`` and must
now resolve to nothing.

The second half is the new rule. 131a landed the pin names, 131b read them as
``IN`` / ``OUT`` on a regulator and 131c read them as ``FB``; 131d reads a
**microcontroller's** oscillator network, which is a different object again —
the pins are not a supply, the net carries a crystal rather than a rail, and
the parts that matter are a load capacitor and a frequency reference rather
than a bypass and a divider.

Three groups:

* **the fix** — :func:`~boardwise.core.pinrole.pin_role` on oscillator names,
  and the reason an MCU on the two acceptance boards produces **no** false
  positive from 131b as a result;
* **the rule on the acceptance boards** — 毕设FOC 1.0.0's ``X1`` / ``C25`` /
  ``C26`` and ROBOT's ``X2`` / ``C2`` / ``C3``, including ROBOT's ``C3``
  (both terminals on ``OSC-OUT``) being **excluded** rather than counted;
* **structure and edges** — the rule is in ``BUILTIN_PCB_RULES`` in the
  declared order, the load-capacitance **three-column** row, the 药箱 and llc
  controls, and a synthetic board built for the case no fixture carries
  (an oscillator network with no crystal on it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.pinrole import PIN_ROLES, pin_role
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES
from boardwise.rules.pcb.crystal import (
    CRYSTAL_NAME_HINT,
    MCU_CATEGORIES,
    PARASITIC_CAP_FARADS,
    McuCrystalPlacement,
    is_crystal_member,
    oscillator_pins_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"


# --------------------------------------------------------------------------
# 零、the OSC misjudgement, fixed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        # The four spellings the fixtures actually carry, bare:
        "OSC_IN", "OSC_OUT", "OSC32_IN", "OSC32_OUT",
        # ... and the port-pin forms STM32 symbols use (``-`` separated, so
        # 131a's ``_SEPARATORS`` split them and the ``IN``/``OUT`` half hit
        # the power table). This is the exact misjudgement the task reports:
        # ``PH0-OSC_IN`` resolved to ``IN`` and would have been filed as a
        # regulator input capacitor question.
        "PH0-OSC_IN", "PH1-OSC_OUT", "PF0-OSC_IN", "PF1-OSC_OUT",
        "PC14-OSC32_IN", "PC15-OSC32_OUT", "PD0-OSC_IN", "PD1-OSC_OUT",
        # case / separator insensitivity, because ``_normalise`` is what the
        # classifier promises: a lower-case or space-separated spelling must
        # reach the same answer as the canonical one.
        "osc_in", "osc out", "OSC-IN", "OSC32-in",
        # a crystal pin on the *other* side of the loop reads ``OSC1`` /
        # ``OSC2`` (毕设FOC X1, 药箱 X1, ROBOT X2) — never a role either.
        "OSC1", "OSC2",
    ],
)
def test_oscillator_pins_carry_no_supply_role(name):
    """An oscillator pin is not a supply pin, and the classifier now says so.

    Before 131d the hyphenated spellings resolved through the token scan
    (``PH0-OSC`` / ``IN``) to ``IN`` and ``OUT``. A rule that asks for
    ``pin_role(...) == "IN"`` — which is exactly what
    :class:`~boardwise.rules.pcb.regulator.RegulatorCapDistance` does — would
    have put a decoupling question on ``PF0-OSC_IN``.
    """
    assert pin_role(name) is None


def test_the_oscillator_fix_is_a_substring_short_circuit_not_a_table_entry():
    """The fix is a short-circuit, and it had to be one.

    ``-`` is **not** in :data:`~boardwise.core.pinrole._SEPARATORS`, so
    ``PF0-OSC_IN`` splits only on the underscore and the token the table would
    have to refuse is the whole ``PF0-OSC`` — one entry per STM32 port pin.
    :data:`~boardwise.core.pinrole._OSC_SUBSTRING` is checked before both
    tables instead, which is why it cannot live in ``_NOT_A_ROLE`` and why
    this test reaches for the module private rather than the table.
    """
    from boardwise.core import pinrole

    assert pinrole._OSC_SUBSTRING == "OSC"
    # The family is deliberately **not** enumerated in either table — a
    # per-port-pin list would be a maintenance trap and the substring is the
    # shape the family has.
    assert "OSC" not in pinrole._NOT_A_ROLE
    assert not [name for name in pinrole._WHOLE_NAME if "OSC" in name]
    assert "OSC_IN" not in pinrole._NOT_A_ROLE
    # The short-circuit runs before the whole-name table: `OSC_IN` would
    # otherwise be split into `OSC` + `IN` and resolve as a supply input.
    assert pinrole._SEPARATORS.split("OSC_IN") == ["OSC", "IN"]
    # And the fix never returns a role outside the declared set.
    assert all(
        pin_role(name) in PIN_ROLES
        for name in ("PH0-OSC_IN", "OSC_IN", "OSC32_OUT", "PF1-OSC_OUT")
        if pin_role(name)
    )


def test_the_fix_costs_a_hypothetical_oscillator_enable_and_that_is_stated():
    """The one thing the substring over-refuses, pinned so it stays a choice.

    ``OSC_EN`` / ``RCC_OSC_IN`` (CubeMX's own spelling, see
    :func:`boardwise.core.pintable.port_pin_of`) resolve to nothing. That is
    the safe direction — an absent role never puts a supply rule on a pin —
    and the module docstring says so. Pinning it here is what makes the
    trade-off visible instead of incidental.
    """
    assert pin_role("RCC_OSC_IN") is None
    assert pin_role("OSC_EN") is None
    # The other half of the trade: no ordinary supply name lost its role.
    assert pin_role("VIN") == "IN"
    assert pin_role("VCC") == "IN"
    assert pin_role("VOUT") == "OUT"


def test_the_power_roles_around_the_oscillator_still_read():
    """The fix is additive: no supply name lost its role.

    A blocklist that swept in ``IN`` / ``OUT`` would silence 131b as well, and
    131b's own fixture assertions would catch it — this pins the boundary
    locally so the two are not coupled by accident.
    """
    assert pin_role("VIN") == "IN"
    assert pin_role("VOUT") == "OUT"
    assert pin_role("VCC") == "IN"
    assert pin_role("GND/ADJ") == "GND"
    assert pin_role("EN/UVLO") == "EN"


@pytest.mark.parametrize(
    "designator, expected",
    [
        ("U1", [("8", "PC14-OSC32_IN"), ("9", "PC15-OSC32_OUT"),
                ("12", "PH0-OSC_IN"), ("13", "PH1-OSC_OUT")]),
        # ROBOT's STM32G431RBT6 spells its ports PF0/PF1.
    ],
)
def test_osc_names_on_the_fixture_are_the_ones_the_fix_covers(
    designator, expected
):
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    model = build_design_model(load_epro2_source(FOC_100))
    component = model.components[designator]
    assert [
        (pin.number, pin.name) for pin in component.pins if "OSC" in (pin.name or "")
    ] == expected


def test_an_mcu_no_longer_produces_a_regulator_cap_row():
    """The observable consequence of the fix, on the real board.

    131b examines ``ic.ldo`` / ``ic.buck`` parts only, and the STM32 is
    ``ic.mcu``, so it was never the rule's object — this is here to pin that
    the *fix* changed nothing on 131b's side, and that the reason an MCU
    could have been misjudged is a shared predicate, not a shared rule.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.core.parts import find_facts, load_parts
    from boardwise.rules.facts import default_library_path
    from boardwise.rules.pcb.regulator import REGULATOR_CATEGORIES

    library = load_parts(default_library_path())
    model = build_design_model(load_epro2_source(FOC_100))
    mcu = model.components["U1"]
    entry = find_facts(library, mpn=str(mcu.mpn or ""))
    assert (entry.category if entry else "") == "ic.mcu"
    assert (entry.category if entry else "") not in REGULATOR_CATEGORIES


# --------------------------------------------------------------------------
# 一、the rule: recognition helpers
# --------------------------------------------------------------------------


def test_oscillator_pins_are_read_off_the_pin_name_not_the_net():
    """131a landed the names; this is the first rule to read ``*OSC*`` in one.

    The predicate is a substring test on the **pin name** — ``PH0-OSC_IN``,
    ``PF0-OSC_IN``, ``OSC32_IN`` and the crystal's own ``OSC1`` / ``OSC2`` all
    carry it, and a pin named ``IN`` does not. Reading it off the net name
    instead would make the rule unable to say *which pin* it means.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    model = build_design_model(load_epro2_source(ROBOT))
    pins = oscillator_pins_of(model.components["U1"])
    assert [(p.number, p.name, p.net) for p in pins] == [
        ("3", "PC14-OSC32_IN", None),
        ("4", "PC15-OSC32_OUT", None),
        ("5", "PF0-OSC_IN", "OSC-IN"),
        ("6", "PF1-OSC_OUT", "OSC-OUT"),
    ]


def test_a_pin_named_in_is_not_an_oscillator_pin():
    assert oscillator_pins_of(_fake_component([("1", "IN", "OSC-IN")])) == []


def test_crystal_recognition_is_the_documented_fragile_sieve():
    """The shelf has no crystal category, so recognition is a sieve.

    131a's lesson is the one being applied: a part's identity must come from
    a stated field, not from pattern-matching an MPN. But a crystal *has* no
    stated field here — ``blocklib/parts.json`` classifies 14 categories and
    none of them is a crystal, and both crystals on the acceptance boards
    carry an **empty** ``category``. So this rule falls back to the two
    signals that survive: the part's own ``value`` spelling a frequency
    (``25MHz``) and the footprint naming the crystal family (``3225``). The
    helper is exported and its two hints are named constants so the
    fragility is visible in the report rather than buried in a regex.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    model = build_design_model(load_epro2_source(ROBOT))
    x2 = model.components["X2"]
    assert is_crystal_member(model, "X2") is True
    assert (x2.value or "").strip() in CRYSTAL_NAME_HINT or "MHz" in (x2.value or "")
    # A capacitor is not a crystal, and neither is the MCU.
    assert is_crystal_member(model, "C2") is False
    assert is_crystal_member(model, "U1") is False


def test_crystal_sieve_also_accepts_the_3225_footprint_alone():
    """A crystal whose value nobody wrote down is still a crystal.

    The two hints are an ``or``, so a part carrying the ``3225`` package name
    is recognised on the footprint alone. This is the fallback the docstring
    declares fragile, and it is a *second* route rather than a broadened
    first one — a design that lost the value string still gets its crystal
    examined.
    """
    model = _model_with(
        {"X1": ("", "X32258MOB4SI", "CRYSTAL-SMD_4P-L3.2-W2.5-BL")},
        {"OSC-IN": [("X1", "1")], "OSC-OUT": [("X1", "3")]},
    )
    assert is_crystal_member(model, "X1") is True
    # The MPN is **not** one of the two hints, and deliberately so: 131a's
    # whole argument is that identity comes from a stated field, and the shelf
    # says nothing about this part. A value and a footprint that say nothing
    # leave the part unrecognised — 「narrower reading」, not a guess.
    model2 = _model_with(
        {"X1": ("", "CRYSTAL-SMD_4P-L3.2-W2.5-BL", "")},
        {"OSC-IN": [("X1", "1")], "OSC-OUT": [("X1", "3")]},
    )
    assert is_crystal_member(model2, "X1") is False


# --------------------------------------------------------------------------
# 一、the rule on the acceptance boards
# --------------------------------------------------------------------------


def _findings(path: Path, rule_id: str) -> list:
    from boardwise.engines.pcbreview import run_pcb_review

    findings, _section = run_pcb_review(path)
    return [f for f in findings if f.rule_id == rule_id]


def test_foc_100_xtal_rows_are_the_measured_ones():
    """毕设FOC 1.0.0, ``PCB1``: the reference anchor for the whole rule.

    ``X1`` is the 25 MHz crystal on ``OSC-IN``/``OSC-OUT``, ``C25`` and
    ``C26`` are its two 30 pF load capacitors, and every number below was
    read off this fixture rather than assumed.
    """
    rows = _findings(FOC_100, "pcb-mcu-crystal-placement")
    assert rows, "the rule is in BUILTIN_PCB_RULES and fires on 毕设FOC 1.0.0"
    assert all(row.severity == "INFO" for row in rows)
    assert all(row.level == "L1-pcb-geometry" for row in rows)
    assert {row.board for row in rows} == {"PCB1"}
    text = "\n".join(f"{row.message}\n{' | '.join(row.evidence)}" for row in rows)
    assert "X1" in text
    # The crystal's own value is quoted, so a reader knows *which frequency*
    # the three columns are about.
    assert "25MHz" in text, "the crystal's declared frequency"
    # Both load capacitors are measured, and neither is excluded.
    assert "C25" in text and "C26" in text


def test_foc_100_load_capacitance_row_carries_the_three_columns():
    """规格 CL / 实测容值 / 串联等效 CL — all three, on the real board.

    1.0.0's ``X1`` states ``Load Capacitance: 20pF`` in the shelf and carries
    two 30 pF capacitors, so the equivalent is ``30/2 + 5pF = 20pF`` — which
    **matches the spec**. The row is a measurement and says so: the rule does
    not grade the match, because 岳 owns the judgement. The load-bearing part
    of the test is that all three numbers are present and are the right ones.
    """
    rows = [
        row
        for row in _findings(FOC_100, "pcb-mcu-crystal-placement")
        if any("串联等效" in item for item in row.evidence)
    ]
    assert rows, "a load-capacitance row must state the series-equivalent column"
    blob = "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}" for row in rows
    )
    assert "20pF" in blob, "the spec CL from the shelf's params"
    assert "30pF" in blob, "the as-declared capacitance of C25/C26"
    assert "5pF" in blob, "the parasitic allowance is named, not implied"
    assert PARASITIC_CAP_FARADS == 5e-12
    # The rule must not have graded it: 「合格」/「不合格」 are not its words.
    assert "合格" not in blob and "不合格" not in blob


def test_robot_100nF_load_capacitor_is_a_visible_row_not_a_hidden_one():
    """ROBOT: 100 nF against a 12 pF spec is three orders of magnitude out.

    The task is explicit that this must be 「显眼行出账」: the row exists, it
    quotes the declared value, the spec and the equivalent, and it does not
    bury the gap in a footnote. ``C2`` bridges ``OSC-IN`` to ``GND`` so it is
    a load-capacitor candidate; the rule reports the numbers and leaves the
    verdict to a human, exactly as the task asks.
    """
    rows = _findings(ROBOT, "pcb-mcu-crystal-placement")
    assert rows
    blob = "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}" for row in rows
    )
    assert "X2" in blob and "8MHz" in blob
    assert "12pF" in blob, "the spec CL of X32258MOB4SI"
    assert "100nF" in blob, "C2's as-declared value"
    assert "C3" in blob, "C3 must be named — as an exclusion, not as a load cap"
    # C3 is named as an **exclusion**, with the reason, and never as a
    # bridging candidate. The candidate list is a single evidence line, so it
    # is matched as a line rather than by a substring over the whole blob
    # (the net member list legitimately names C3 — that is the fact the
    # exclusion is derived from).
    candidate_lines = [
        item
        for row in rows
        for item in row.evidence
        if item.startswith("load-capacitor candidates bridging")
    ]
    assert candidate_lines
    for item in candidate_lines:
        listed = item.split("bridging", 1)[1].rsplit(":", 1)[-1]
        candidates = {name.strip() for name in listed.split(",") if name.strip()}
        assert "C3" not in candidates, (
            f"the bridging predicate is what excludes C3 (both terminals on one "
            f"net); without it C3 would be read as a load capacitor. candidates: "
            f"{candidates}"
        )
    # ... and C3 is *absent* from the list it would have joined. The row for
    # ``OSC-IN`` names ``C2``; the row for ``OSC-OUT`` names nobody, because
    # C3 bridges nothing. That absence is the measured shape of the exclusion.
    on_out = [
        item.split("bridging", 1)[1].rsplit(":", 1)[-1]
        for item in candidate_lines
        if "'OSC-OUT'" in item
    ]
    assert on_out and all(
        name.strip() in {"", "(none)"} for name in on_out
    ), on_out
    exclusion_lines = [
        item
        for row in rows
        for item in row.evidence
        if item.startswith("excluded — C3")
    ]
    assert exclusion_lines, "C3's exclusion must be stated with its reason"
    assert "both" in exclusion_lines[0] and "OSC-OUT" in exclusion_lines[0]


def test_robot_c3_is_excluded_because_both_ends_share_a_net():
    """The short-circuit form, pinned by the criterion that excludes it.

    ``C3``'s pad 1 and pad 2 are **both** on ``OSC-OUT``. A capacitor whose
    two terminals sit on one net is not a load capacitor across the loop —
    it is a part drawn across a single node. The bridging predicate
    (:func:`boardwise.rules.decap._bridges_to_ground`, the same one 126b and
    131b use) excludes it structurally: both of its ends resolve to the same
    net, so there is no 「other」 net to bridge to.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.rules.decap import cap_candidates_on, same_net_capacitors_on
    from boardwise.core.parts import load_parts
    from boardwise.rules.facts import default_library_path

    library = load_parts(default_library_path())
    model = build_design_model(load_epro2_source(ROBOT))
    c3 = model.components["C3"]
    assert {pin.net for pin in c3.pins} == {"OSC-OUT"}
    assert [c.designator for c in cap_candidates_on(model, "OSC-OUT", library)] == []
    assert [c.designator for c in same_net_capacitors_on(model, "OSC-OUT")] == ["C3"]


def test_robot_osc_rows_measure_the_crystal_to_mcu_osc_pin_pair():
    """The per-pin measurement: crystal pad ↔ the MCU's own oscillator pin.

    The full pad × pin matrix, so all four readings are there:
    ``X2.1`` (OSC-IN) reads **160.2 mil** against ``U1.5`` and **166.2 mil**
    against ``U1.6``; ``X2.3`` (OSC-OUT) reads 88.0 against both. The
    same-net row is the oscillator leg and the cross-net row is the loop seen
    from the other end — both are measurements, neither is a verdict, and the
    row says which is which.
    """
    rows = [
        row
        for row in _findings(ROBOT, "pcb-mcu-crystal-placement")
        if row.target.component_ref == "X2" and row.target.measurement
    ]
    assert len(rows) == 4, [row.message for row in rows]
    blob = "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}\n{row.target.measurement}"
        for row in rows
    )
    assert "160.2" in blob
    assert "166.2" in blob
    assert "OSC-IN" in blob and "OSC-OUT" in blob
    same_net = [row for row in rows if "**same net**" in row.message]
    cross_net = [row for row in rows if "cross-net" in row.message]
    assert len(same_net) == 2 and len(cross_net) == 2


def test_foc_100_osc_rows_measure_the_crystal_to_mcu_osc_pin_pair():
    """The same on 1.0.0: ``X1.1`` reads 162.1 vs ``U1.12``, 162.8 vs ``U1.13``."""
    rows = [
        row
        for row in _findings(FOC_100, "pcb-mcu-crystal-placement")
        if row.target.component_ref == "X1" and row.target.measurement
    ]
    assert len(rows) == 4
    blob = "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}\n{row.target.measurement}"
        for row in rows
    )
    assert "162.1" in blob
    assert "162.8" in blob
    assert "OSC-IN" in blob and "OSC-OUT" in blob


def test_the_component_level_distance_would_have_been_a_different_number():
    """Why pad-to-pad, stated as a measurement rather than as an argument.

    :func:`boardwise.core.measure.component_distance` refuses same-net pad
    pairs, so on 毕设FOC 1.0.0 the ``X1`` ↔ ``U1`` component distance is
    93.2 mil between pads ``3`` (``OSC-OUT``) and ``16`` — **not** an
    oscillator pin. Reading the crystal's placement off that number would be
    reading a ``VCC`` pad.
    """
    from boardwise.core.measure import component_distance
    from boardwise.parsers.epru import extract_board, load_epro2_source

    source = load_epro2_source(FOC_100)
    board = None
    for document in source.documents_of_type("PCB"):
        title = ""
        for record in document.records:
            if record.type == "META" and record.body:
                title = str(record.body.get("title") or "")
        if title == "PCB1":
            board = extract_board(document, source.footprints(), source.stats)
            break
    assert board is not None
    distance = component_distance(board, "X1", "U1")
    assert distance is not None
    assert distance.pad_b == "16"  # not 12 or 13, the OSC pins
    assert round(distance.edge_distance, 1) == 93.2


def test_measurements_are_structured_mil_distances():
    """Every measured row carries 125's structured measurement shape."""
    rows = _findings(ROBOT, "pcb-mcu-crystal-placement")
    with_measurement = [row for row in rows if row.target.measurement]
    assert with_measurement
    for row in with_measurement:
        assert row.target.measurement["unit"] == "mil"
        assert row.target.measurement["kind"] in {"distance", "area"}


# --------------------------------------------------------------------------
# structure: the rule list, the constants, the controls
# --------------------------------------------------------------------------


def test_the_rule_is_in_builtin_pcb_rules_after_the_regulator_pair():
    """The structure gate. 131d inserts after 131c's rule, before the sweep.

    The MCU oscillator question belongs with the other **placement** readings
    (one regulator's supply caps, the feedback network, one MCU's crystal
    network) rather than appended after the standards-derived IPC pair.
    """
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert "pcb-mcu-crystal-placement" in ids
    assert ids.index("pcb-mcu-crystal-placement") == ids.index(
        "pcb-regulator-fb-placement"
    ) + 1
    assert ids.index("pcb-mcu-crystal-placement") < ids.index(
        "pcb-component-spacing"
    )
    rule = next(
        r for r in BUILTIN_PCB_RULES if r.id == "pcb-mcu-crystal-placement"
    )
    assert isinstance(rule, McuCrystalPlacement)


def test_the_rule_declares_a_house_rule_source_and_no_threshold():
    """钉 7: the source names the house rule, and there is no distance constant.

    The task is explicit that the rows are 「INFO 无阈值，工具出数」, so the
    module must not grow a ``*_DISTANCE_MIL`` of its own.
    """
    from boardwise.rules.pcb import crystal

    rule = McuCrystalPlacement()
    assert rule.source == "house rule（岳 2026-10 待裁）"
    assert rule.level == "L1-pcb-geometry"
    assert not [
        name
        for name in dir(crystal)
        if name.endswith("_DISTANCE_MIL") or name.endswith("_MIL")
    ], "the rule sets no threshold — 岳 has ruled on none"


def test_mcu_categories_is_the_shelfs_own_spelling():
    assert MCU_CATEGORIES == frozenset({"ic.mcu"})


def test_pillbox_produces_rows_and_llc_produces_silence():
    """药箱 is the third oscillator board; llc is the no-MCU control.

    药箱 carries an STM32G431 with a crystal and two 100 nF capacitors on the
    oscillator nets, so the rule must speak. ``llc_board.epro2`` places no
    part the shelf calls an MCU, so the rule is **silent** — and silence, not
    a zero-row placeholder, is the empty-input contract.
    """
    pillbox = _findings(PILLBOX, "pcb-mcu-crystal-placement")
    assert pillbox
    blob = "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}" for row in pillbox
    )
    assert "X1" in blob and "C13" in blob and "C14" in blob
    assert _findings(LLC, "pcb-mcu-crystal-placement") == []


def test_a_context_without_a_pcb_model_is_silent():
    """131c's contract, kept: no netlist for this document means no answers."""
    from boardwise.core.geometry import BoardGeometry
    from boardwise.rules.pcb.base import PcbReviewContext

    ctx = PcbReviewContext(board=BoardGeometry(), board_title="PCB1")
    assert McuCrystalPlacement().check(ctx) == []


# --------------------------------------------------------------------------
# synthetic: the cases no fixture carries
# --------------------------------------------------------------------------


def _model_with(parts, nets, names=None):
    """A minimal ``DesignModel`` from ``{designator: (value, mpn, footprint)}``.

    ``nets`` maps a net name to ``[(owner designator, pin number)]`` — the
    shape :attr:`~boardwise.core.model.Net.pins` itself carries, so a synthetic
    board reads the way a parsed one does. ``names`` maps
    ``(designator, pin number)`` to a pin **name** (the oscillator predicate
    reads names, so a synthetic board has to declare them).
    """
    names = names or {}
    model = DesignModel()
    for designator, (value, mpn, footprint) in parts.items():
        pins = []
        for net, members in nets.items():
            for owner, pin_number in members:
                if owner == designator:
                    pins.append(
                        Pin(
                            pin_number,
                            names.get((designator, pin_number), ""),
                            net,
                        )
                    )
        pins.sort(key=lambda p: p.number)
        model.components[designator] = Component(
            uid=designator, designator=designator, value=value, mpn=mpn,
            footprint=footprint, pins=pins,
        )
        for pin in pins:
            if pin.net and pin.net not in model.nets:
                model.nets[pin.net] = Net(name=pin.net, pins=[])
            if pin.net:
                model.nets[pin.net].pins.append((designator, pin.number))
    return model


def _fake_component(pins):
    from boardwise.core.model import Component, Pin

    return Component(
        uid="U1", designator="U1",
        pins=[Pin(number, name, net) for number, name, net in pins],
    )


def test_an_unused_oscillator_branch_is_skipped_not_guessed():
    """``PC14-OSC32_IN`` has no net on either acceptance board.

    A 32.768 kHz branch nobody populated is not a crystal network and not a
    defect — it is an unpopulated option. The rule says so in one row naming
    the pins, and never invents a crystal for it.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    model = build_design_model(load_epro2_source(FOC_100))
    oscillator = oscillator_pins_of(model.components["U1"])
    unused = [pin for pin in oscillator if not pin.net]
    assert [pin.name for pin in unused] == [
        "PC14-OSC32_IN", "PC15-OSC32_OUT",
    ]


def _board_with(designators, pads=()):
    """A minimal placed board: one ``ComponentPlacement`` per designator.

    The rule skips an MCU the PCB document in hand does not place (131c's
    contract), so a synthetic case that wants the rule to speak has to place
    its part — an empty :class:`BoardGeometry` is the 「no geometry」 answer, not
    a shortcut.
    """
    from boardwise.core.geometry import BoardGeometry, ComponentPlacement

    return BoardGeometry(
        components=[
            ComponentPlacement(id=designator, designator=designator)
            for designator in designators
        ]
    )


def test_an_oscillator_net_with_no_crystal_is_one_info_row():
    """No crystal on the net is a finding, not silence and not a guess.

    Built synthetically because no fixture carries it: the rule found the MCU's
    oscillator pins, found the net, and no member of it is a crystal. The row
    names the net and its members — and it is the sieve that decided, so the
    row says the sieve is what decided it.
    """
    from boardwise.rules.pcb.base import PcbReviewContext

    model = _model_with(
        {"U1": ("STM32G431RBT6", "STM32G431RBT6", "LQFP64")},
        {"OSC-IN": [("U1", "5")], "OSC-OUT": [("U1", "6")]},
        names={("U1", "5"): "PF0-OSC_IN", ("U1", "6"): "PF1-OSC_OUT"},
    )
    ctx = PcbReviewContext(
        board=_board_with(["U1"]), board_title="PCB1", pcb_model=model
    )
    produced = McuCrystalPlacement().check(ctx)
    rows = [
        row
        for row in produced
        if "no member this rule reads as a crystal" in row.message
    ]
    assert rows, [row.message for row in produced]
    # One row per oscillator net — two nets, two rows — and the MCU is the only
    # member of each, which is the fact being reported.
    assert len(rows) == 2
    assert {tuple(row.target.net_refs) for row in rows} == {
        ("OSC-IN",), ("OSC-OUT",)
    }
