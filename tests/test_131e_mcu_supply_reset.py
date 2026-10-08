"""Task 131e: ``pcb-mcu-supply-groups`` and ``pcb-mcu-reset-boot``.

The MCU package's fourth and fifth rules, and the two that finish the object
131b–131d were walking towards. All four read the same part (an ``ic.mcu`` on
one PCB document, through ``ctx.pcb_model``) and the same netlist, and each
answers the question the previous one could not: the regulator's own supply
caps (131b), the regulator's divider (131c), the MCU's oscillator loop (131d),
and here the MCU's **supply nets** and its **reset/boot strapping**.

Three groups, plus the structure gate:

* **一、grouping** — supply pins fold **by net** and a per-pin row does not
  exist, because on an LQFP the pin pitch (19.7 mil) is smaller than the part
  that has to sit next to it (a 0603 capacitor is 55 mil wide), so a per-pin
  threshold is unsatisfiable rather than merely strict. Also the two bypass-pool
  readings (a non-ground net uses the shared ``cap_candidates_on`` predicate; a
  **ground** net needs the two-sided swap, without which 1.0.0's ``GND`` group
  would report nothing found while ``C1`` sits 33.5 mil away), the ``VCAP``
  exclusion, and the three supply names 131a's table declines.
* **二、the acceptance boards** — every number pinned is **measured**, taken from
  these fixtures and not from the task book, and the two anchors the task
  highlights get a test each: 1.0.0's capacitor-less ``VREF`` net and ROBOT's
  empty ``NRST`` net.
* **三、structure and edges** — both rules in ``BUILTIN_PCB_RULES`` in the
  declared order, house-rule ``source`` with **no** distance constant (131e's
  「INFO 无阈值，工具出数」), the 药箱 and llc controls, and two synthetic cases
  no fixture carries (a ground group whose bypass is on the other side of the
  net, and a boot strap nobody fitted).
"""

from __future__ import annotations

from pathlib import Path

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES
from boardwise.rules.pcb.distance import HF_FARADS
from boardwise.rules.pcb.mcusupply import (
    HF_CEILING_FARADS,
    SUPPLY_NAME_EXTRAS,
    SUPPLY_ROLES,
    VCAP_NAME_MARKER,
    McuSupplyGroups,
    bypass_pool,
    ground_group_bypass_pool,
    supply_groups_of,
    vcap_pins_of,
)
from boardwise.rules.pcb.mcureset import (
    BOOT0_NAME_MARKER,
    NRST_NAME_MARKER,
    McuResetBoot,
    boot0_pins_of,
    reset_pins_of,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
PILLBOX = FIXTURES / "ProPrj_智能药箱_2026-09-17.epro2"
LLC = FIXTURES / "llc_board.epro2"


def _findings(path: Path, rule_id: str) -> list:
    from boardwise.engines.pcbreview import run_pcb_review

    findings, _section = run_pcb_review(path)
    return [f for f in findings if f.rule_id == rule_id]


def _blob(rows) -> str:
    return "\n".join(
        f"{row.message}\n{' | '.join(row.evidence)}" for row in rows
    )


def _group_row(rows, net: str):
    """The one supply-group row for ``net``, by the net the row is *about*."""
    matches = [row for row in rows if f"supply group {net!r}" in row.message]
    assert len(matches) == 1, [row.message for row in rows]
    return matches[0]


def _mcu(model_path: Path, designator: str = "U1"):
    return build_model(model_path).components[designator]


def build_model(model_path: Path):
    """The **PCB-document** netlist view, the one the rules are handed.

    ``build_design_model`` reads the backup's first PCB document by default;
    :func:`boardwise.parsers.epro2_model.build_design_model` with an explicit
    document is what the runner does, and for these fixtures the first document
    already carries the MCU under test (毕设FOC 1.0.0 / ROBOT / 药箱 all name
    ``PCB1`` first).
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source

    return build_design_model(load_epro2_source(model_path))


# --------------------------------------------------------------------------
# 一、grouping: by net, never by pin
# --------------------------------------------------------------------------


def test_supply_pins_fold_into_one_group_per_net_not_one_per_pin():
    """The H743's six supply inputs are **one** ``VCC`` group, not six.

    ``VBAT`` (pin 6) and five ``VDD`` pins all sit on net ``VCC``. A per-pin
    reading would print the same bypass six times and imply six requirements
    where the board has one, which is why the grouping key is the net and the
    pin is only the payload.
    """
    groups = supply_groups_of(_mcu(FOC_100))
    vcc = groups["VCC"]
    assert [(p.number, p.name) for p in vcc] == [
        ("6", "VBAT"),
        ("11", "VDD"),
        ("27", "VDD"),
        ("50", "VDD"),
        ("75", "VDD"),
        ("100", "VDD"),
    ]
    # ... and the folding is real: five nets out of fourteen supply pins
    # (6 VCC + 5 GND + 1 AGND + 1 VCCA + 1 VREF).
    assert sorted(groups) == ["AGND", "GND", "VCC", "VCCA", "VREF"]
    assert sum(len(pins) for pins in groups.values()) == 14


def test_the_grouping_key_is_the_net_and_never_the_role():
    """``VBAT`` and ``VDD`` read as the same role **and** share a net.

    That coincidence is what makes the fold invisible rather than lucky: the
    group exists because the board wired the pins together, and a board that
    put a ``VBAT`` on its own net would get its own group — the pinrole decides
    *whether* a pin is a supply at all, the net decides *which* group.
    """
    groups = supply_groups_of(_mcu(FOC_100))
    assert {p.name for p in groups["VCC"]} == {"VBAT", "VDD"}
    assert len({p.role for p in groups["VCC"]}) == 1  # both IN


def test_no_per_pin_row_exists_and_the_rule_says_why():
    """The per-pin reading is refused on purpose, with the geometry recorded.

    LQFP-100 pin pitch 19.7 mil against a 55 mil-wide 0603 capacitor: no
    threshold a reader could set would be satisfiable by a correctly-placed
    part. The evidence line naming this is the pin — without it a reader could
    not tell whether the absence was an oversight or a decision.
    """
    rows = _findings(FOC_100, "pcb-mcu-supply-groups")
    vcc = _group_row(rows, "VCC")
    joined = _blob([vcc])
    assert "19.7 mil" in joined and "55 mil" in joined
    assert "no per-pin row exists" in joined
    # Every group row carries the whole pin list of its group, so the fold is
    # visible in the row itself and not only in the code.
    assert "pin 6 'VBAT'" in vcc.message and "pin 100 'VDD'" in vcc.message


def test_the_roles_that_form_a_group_are_the_three_measured_ones():
    assert SUPPLY_ROLES == frozenset({"IN", "GND", "EP"})
    # `OUT` / `BST` are excluded deliberately — see the constant's docstring.


def test_a_supply_pin_with_no_net_is_dropped_not_given_an_empty_group():
    """An unpopulated supply pin gets no group.

    A symbol declares pins a layout need not fit; a group keyed on ``None``
    would state a bypass requirement against a net that does not exist, which
    is the silent direction.
    """
    component = Component(
        uid="U1",
        designator="U1",
        pins=[Pin("1", "VDD", None), Pin("2", "VSS", None)],
    )
    assert supply_groups_of(component) == {}


# --------------------------------------------------------------------------
# 一 b、the bypass pool: two predicates, chosen by the net's own kind
# --------------------------------------------------------------------------


def test_a_ground_group_is_read_by_the_two_sided_swap():
    """Without the ground branch, 1.0.0's ``GND`` group reports nothing found.

    The shared ``cap_candidates_on`` predicate wants a capacitor whose *other*
    end is a ground net — which cannot be true on a ground net. The swap (one
    terminal here, the other on a **non**-ground net) is what makes the column
    mean anything, and the measured proof is ``C1`` at 33.5 mil.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.core.parts import load_parts
    from boardwise.rules.decap import cap_candidates_on
    from boardwise.rules.facts import default_library_path

    library = load_parts(default_library_path())
    model = build_design_model(load_epro2_source(FOC_100))
    # The shared predicate really is blind here...
    assert cap_candidates_on(model, "GND", library) == []
    # ... and the swap finds the capacitor the task pins.
    assert "C1" in ground_group_bypass_pool(model, "GND", library)
    assert bypass_pool(model, "GND", library) == ground_group_bypass_pool(
        model, "GND", library
    )


def test_a_non_ground_group_uses_the_shared_predicate_verbatim():
    """The two branches are chosen by the net's kind, in one place.

    :func:`bypass_pool` is the only place the choice is made, so a mutation
    there is the whole surface a reader has to check.
    """
    from boardwise.parsers.epro2_model import build_design_model
    from boardwise.parsers.epru import load_epro2_source
    from boardwise.core.parts import load_parts
    from boardwise.rules.decap import cap_candidates_on
    from boardwise.rules.facts import default_library_path

    library = load_parts(default_library_path())
    model = build_design_model(load_epro2_source(FOC_100))
    assert bypass_pool(model, "VCC", library) == [
        candidate.designator
        for candidate in cap_candidates_on(model, "VCC", library)
    ]


def test_the_two_columns_split_at_the_house_1uf_and_not_a_second_literal():
    """131e reuses 126b's ``HF_FARADS`` rather than restating 1 µF.

    Two rules quoting the same number as two literals would eventually
    disagree about which side a 1 µF part falls on, and the disagreement would
    be invisible.
    """
    assert HF_CEILING_FARADS == HF_FARADS == 1e-6


# --------------------------------------------------------------------------
# 一 c、VCAP: named, listed, never grouped
# --------------------------------------------------------------------------


def test_vcap_pins_are_listed_apart_and_never_joined_a_group():
    """H743 pins 48 and 73 are internal-regulator outputs, not supplies.

    ``pin_role('VCAP')`` answers ``None``, so the exclusion is currently a
    fortunate accident — which is why it is made explicit and pinned rather
    than left to the table it happens not to cover.
    """
    mcu = _mcu(FOC_100)
    assert [(p.number, p.net) for p in vcap_pins_of(mcu)] == [
        ("48", "$1N66421"),
        ("73", "$1N74272"),
    ]
    groups = supply_groups_of(mcu)
    assert not {"$1N66421", "$1N74272"} & set(groups)

    rows = _findings(FOC_100, "pcb-mcu-supply-groups")
    vcaps = [r for r in rows if VCAP_NAME_MARKER in r.message]
    assert len(vcaps) == 2
    blob = _blob(vcaps)
    # Each carries its net and the capacitor on it with the declared value.
    assert "$1N66421" in blob and "C1 value 100nF" in blob
    assert "$1N74272" in blob and "C16 value 2.2uF" in blob
    assert "not** a supply group" in blob


def test_robots_no_vcap_pin_produces_no_vcap_row():
    """A part that declares no ``VCAP`` gets no row — silence, not a zero."""
    assert vcap_pins_of(_mcu(ROBOT)) == []
    blob = _blob(_findings(ROBOT, "pcb-mcu-supply-groups"))
    assert "VCAP" not in blob


# --------------------------------------------------------------------------
# 一 d、the three names 131a's table declines
# --------------------------------------------------------------------------


def test_vref_is_a_supply_group_even_though_the_classifier_declines_it():
    """``pin_role('VREF+')`` is ``None``, and the reference net still gets a row.

    131a's table has no ``VREF`` row and ``+`` is in ``_NOT_A_ROLE`` as a bare
    polarity. Reading the role alone would leave 1.0.0's capacitor-less
    reference net **absent** from the ledger — a data gap nobody reports, which
    is the one failure mode this rule exists to avoid.
    """
    from boardwise.core.pinrole import pin_role

    assert pin_role("VREF+") is None, "the measured gap, still open in 131a"
    groups = supply_groups_of(_mcu(FOC_100))
    assert [p.name for p in groups["VREF"]] == ["VREF+"]
    assert groups["VREF"][0].basis == "name-extra", (
        "the row must say the role came from 131e's residue list, not the table"
    )


def test_the_residue_list_holds_no_name_the_classifier_already_answers():
    """Every entry is a real gap, and a redundant one is a maintenance trap.

    An entry that ``pin_role`` already handled would shadow the table and could
    drift from it; this pins that the list stays the residue and nothing more.
    """
    from boardwise.core.pinrole import pin_role

    assert SUPPLY_NAME_EXTRAS == frozenset({"VREF+", "VREF-", "VREF"})
    for name in SUPPLY_NAME_EXTRAS:
        assert pin_role(name) is None, f"{name} is not actually a gap"
    # And the direction that matters: the names 131a *does* answer are not here.
    assert "VDDA" not in SUPPLY_NAME_EXTRAS and pin_role("VDDA") == "IN"
    assert "VCC" not in SUPPLY_NAME_EXTRAS and pin_role("VCC") == "IN"
    assert "GND" not in SUPPLY_NAME_EXTRAS and pin_role("GND") == "GND"


def test_the_row_says_which_route_put_the_pin_in_the_group():
    """A pin whose role came from the residue list is labelled as such."""
    rows = _findings(FOC_100, "pcb-mcu-supply-groups")
    vref = _group_row(rows, "VREF")
    assert "131e's explicit" in _blob([vref])
    # A group whose pins all came from 131a says nothing about the residue.
    assert "131e's explicit" not in _blob([_group_row(rows, "VCC")])


# --------------------------------------------------------------------------
# 二、the acceptance boards: every number measured
# --------------------------------------------------------------------------


def test_foc_100_supply_groups_are_the_measured_ones():
    """毕设FOC 1.0.0 ``PCB1`` — the reference anchor for the whole rule.

    Every figure below was read off this fixture. The distances are
    :func:`~boardwise.core.measure.component_distance` edge-to-edge, which
    refuses same-net pad pairs by design, so 「the gap between the bypass body
    and the MCU body」 is what is printed — the number a placement question is
    actually about.
    """
    rows = _findings(FOC_100, "pcb-mcu-supply-groups")
    expected = {
        # net: (nearest bypass, mil, nearest reservoir, mil)
        "VCC": ("C72", 164.4, "C69", 180.7),
        "GND": ("C1", 33.5, "C16", 74.7),
        "AGND": ("C108", 64.8, "C64", 475.2),
        "VCCA": ("C17", 672.2, "C67", 708.8),
    }
    for net, (bypass, bypass_mil, bulk, bulk_mil) in expected.items():
        message = _group_row(rows, net).message
        assert f"**{bypass}**" in message, net
        assert f"{bypass_mil} mil" in message, net
        assert f"**{bulk}**" in message, net
        assert f"{bulk_mil} mil" in message, net


def test_foc_100_vref_carries_no_capacitor_and_the_row_says_so():
    """**ANCHOR 1** — 1.0.0's ``VREF`` net really has no part on it.

    The members are the H743 itself and the REF2033 (whose own output is
    ``5VA``), so there is nothing to bridge. The task pins this as a **real
    data gap** rather than a tool blind spot, and the rule's job is to make it
    visible: both columns read 「none」 and the pool line says the pool is empty.
    """
    rows = _findings(FOC_100, "pcb-mcu-supply-groups")
    row = _group_row(rows, "VREF")
    assert row.message.count("**none**") == 2
    assert "bypass pool on 'VREF': (none)" in _blob([row])
    # The members are named, so a reader can check the emptiness rather than
    # take it on trust.
    assert "members as the board declares them: U1, U20" in _blob([row])


def test_robot_supply_groups_are_the_measured_ones():
    """ROBOT ctrl FOC ``PCB1`` — the second anchor.

    ``C18`` serves **both** the ``GND`` group and the ``VCC`` group on this
    board (its two terminals sit on exactly those two nets), and 37.8 mil away
    is ``C17`` on ``VCCA``.
    """
    rows = _findings(ROBOT, "pcb-mcu-supply-groups")
    for net, bypass, mil in [("VCC", "C18", 33.4), ("GND", "C18", 33.4),
                             ("VCCA", "C17", 37.8)]:
        message = _group_row(rows, net).message
        assert f"**{bypass}**" in message and f"{mil} mil" in message, net


def test_robot_vssa_net_has_no_capacitor_and_the_row_says_so():
    """**ANCHOR 1b** — ROBOT's ``VSSA`` sits on net ``$1N251``, whose only
    other member is a 0 Ω resistor to ``GND``.

    A single ground reference with no bypass beside it, which is exactly the
    kind of real gap this rule is for; both columns read 「none」.
    """
    rows = _findings(ROBOT, "pcb-mcu-supply-groups")
    row = _group_row(rows, "$1N251")
    assert row.message.count("**none**") == 2
    assert "bypass pool on '$1N251': (none)" in _blob([row])
    assert "R8" in _blob([row]), "the 0 Ω that is there is named"


def test_both_rules_fire_on_pillbox_too():
    """药箱 is the third MCU board; it carries two MCUs and both rules speak."""
    supply = _findings(PILLBOX, "pcb-mcu-supply-groups")
    reset = _findings(PILLBOX, "pcb-mcu-reset-boot")
    assert {r.target.component_ref for r in supply} == {"U1", "U13"}
    assert reset, "药箱's U1 declares both NRST and BOOT0 pins"


# --------------------------------------------------------------------------
# 三、pcb-mcu-reset-boot
# --------------------------------------------------------------------------


def test_reset_pin_is_found_by_name_in_both_spellings():
    """``NRST`` and ``PG10-NRST`` both match; a net-name test would not do.

    The test is on the **pin name**, which is what lets the row say *which*
    pin it means — a net test could not name ``U1.7``.
    """
    assert [(p.number, p.name) for p in reset_pins_of(_mcu(FOC_100))] == [
        ("14", "NRST")
    ]
    assert [(p.number, p.name) for p in reset_pins_of(_mcu(ROBOT))] == [
        ("7", "PG10-NRST")
    ]


def test_the_marker_is_nrst_and_not_reset_so_the_driver_fault_line_stays_out():
    """ROBOT's ``NRESET`` net is the gate driver's fault output, not this pin.

    Pins ``PA5`` / ``PB14`` go out to ``DRV1``. A ``RESET`` substring — or a net
    test — would have swept that signal into a reset audit; the marker is
    ``NRST`` and the test pins why.
    """
    assert NRST_NAME_MARKER == "NRST"
    mcu = _mcu(ROBOT)
    others = [p.name for p in mcu.pins if "NRST" in (p.name or "").upper()]
    assert others == ["PG10-NRST"], "only the reset pin itself"
    # `DRV1` appears in the evidence only as the *reason* the marker is NRST;
    # what must not happen is the driver's fault net being read as this pin's
    # reset, which is asserted structurally below rather than by string absence.
    rows = [
        r for r in _findings(ROBOT, "pcb-mcu-reset-boot") if "NRST" in r.message
    ]
    assert len(rows) == 1
    assert tuple(rows[0].target.net_refs) == ("NRST",)
    assert tuple(rows[0].target.pin_refs) == ("7",)
    # The NRESET net really is the driver's, so the exclusion is not vacuous.
    model = build_model(ROBOT)
    assert {d for d, _p in model.nets["NRESET"].pins} == {"U1", "DRV1"}


def test_robot_reset_net_is_empty_and_says_so_in_those_words():
    """**ANCHOR 2** — ROBOT's ``NRST`` net carries **only the MCU**.

    That is a real board gap (no pull-up, no cap, no button — the part leans on
    its internal pull-up) and it is the case the task pins: a rule that
    reported nothing at all here would look identical to a rule that found
    nothing, so the empty case has to be a row with its own wording.
    """
    rows = [
        r for r in _findings(ROBOT, "pcb-mcu-reset-boot") if "NRST" in r.message
    ]
    assert len(rows) == 1
    message = rows[0].message
    assert "NRST 网上除 U1 外无外部元件（纯内部上拉复位）" in message
    assert "internal pull-up" in message
    assert "NRST'" in _blob(rows)
    assert "members other than U1: (none)" in _blob(rows)


def test_foc_100_reset_net_has_all_three_parts_bucketed_and_placed():
    """1.0.0's reset net is the well-formed case: pull-up, cap, **and** button.

    All three are 600+ mil away, which is the reason this rule prints
    distances and does not judge them — 岳 has ruled on no reset-time, no RC and
    no button distance.
    """
    rows = [
        r for r in _findings(FOC_100, "pcb-mcu-reset-boot") if "NRST" in r.message
    ]
    assert len(rows) == 1
    message = rows[0].message
    assert "pull-up candidate" in message and "R30" in message
    assert "capacitor to ground" in message and "C73" in message
    assert "switch / button" in message and "RST" in message
    # The three measured placements, in the message so a reader sees them
    # without opening the evidence.
    for designator, mil in [("R30", 608.1), ("C73", 638.0), ("RST", 628.8)]:
        assert designator in _blob(rows) and f"{mil}" in _blob(rows)
    assert "no reset-time / RC / button-distance threshold has been ruled on" in message


def test_a_reset_pull_down_is_not_reported_as_a_pull_up():
    """The direction is read, not assumed.

    A resistor on ``NRST`` whose other end is a **ground** net is a pull-down;
    calling it the pull-up the row looks for would invert the circuit's meaning.
    The bucket therefore reports it as 「other」 rather than guessing.
    """
    from boardwise.rules.pcb.mcureset import (
        PART_CAP_TO_GROUND,
        PART_OTHER,
        PART_PULLUP,
        _bucket,
    )

    model = _model_with(
        {"U1": ("", "", "LQFP"), "RUP": ("10K", "", "R0603"),
         "RDN": ("10K", "", "R0603"), "CC": ("100nF", "", "C0603")},
        {
            "NRST": [("U1", "1"), ("RUP", "1"), ("RDN", "1"), ("CC", "1")],
            "VCC": [("RUP", "2")],
            "GND": [("RDN", "2"), ("CC", "2")],
        },
    )
    assert _bucket(model, "RUP", "NRST", None) == PART_PULLUP
    assert _bucket(model, "RDN", "NRST", None) == PART_OTHER, "a pull-down is not a pull-up"
    assert _bucket(model, "CC", "NRST", None) == PART_CAP_TO_GROUND


def test_boot_pin_is_found_by_name_and_the_strap_direction_is_printed():
    """``BOOT0`` / ``PB8-BOOT0`` both match, and the direction is the answer.

    A resistor to ground and a resistor to a supply are different boot modes,
    so 「a resistor is there」 would lose the only thing the row is for.
    """
    assert BOOT0_NAME_MARKER == "BOOT"
    assert [(p.number, p.name) for p in boot0_pins_of(_mcu(FOC_100))] == [
        ("94", "BOOT0")
    ]
    assert [(p.number, p.name) for p in boot0_pins_of(_mcu(ROBOT))] == [
        ("61", "PB8-BOOT0")
    ]

    foc = [
        r for r in _findings(FOC_100, "pcb-mcu-reset-boot") if "BOOT0" in r.message
    ]
    assert len(foc) == 1
    assert "R13 value 10K" in foc[0].message
    assert "other terminals on GND" in foc[0].message
    assert "69.3 mil" in foc[0].message

    robot = [
        r for r in _findings(ROBOT, "pcb-mcu-reset-boot") if "BOOT0" in r.message
    ]
    assert len(robot) == 1
    assert "R3" in robot[0].message and "GND" in robot[0].message
    assert "34.1 mil" in robot[0].message


def test_a_boot_strap_nobody_fitted_is_a_row_not_silence():
    """Synthetic: ``BOOT0`` on a net of its own.

    「No boot resistor anywhere」 and 「nobody looked」 must not read the same,
    so the empty boot net gets its own row saying the strap is left to the
    part's default. No fixture carries this, which is why it is built.
    """
    from boardwise.core.geometry import BoardGeometry, ComponentPlacement
    from boardwise.rules.pcb.base import PcbReviewContext

    model = _model_with(
        {"U1": ("STM32G431RBT6", "STM32G431RBT6", "LQFP64"),
         "C1": ("100nF", "", "C0603")},
        {"VCC": [("U1", "1"), ("C1", "1")], "GND": [("U1", "2"), ("C1", "2")],
         "BOOT0": [("U1", "60")], "NRST": [("U1", "7")]},
        names={("U1", "1"): "VDD", ("U1", "2"): "VSS", ("U1", "60"): "BOOT0",
               ("U1", "7"): "NRST"},
    )
    ctx = PcbReviewContext(
        board=BoardGeometry(
            components=[
                ComponentPlacement(id=d, designator=d) for d in ("U1", "C1")
            ]
        ),
        board_title="PCB1",
        pcb_model=model,
    )
    # `library=None` is the shelfless reading the rules honour; it means no
    # part reads as `ic.mcu`, so the MCU is injected through the model's own
    # MPN lookup instead — see the helper below.
    produced = McuResetBoot().check_with_library(ctx, _shelf_stub())
    boot = [r for r in produced if "BOOT0" in r.message]
    assert len(boot) == 1
    assert "carries **no other member**" in boot[0].message
    assert "internal pull-down" in boot[0].message
    assert "members other than U1: (none)" in _blob(boot)


# --------------------------------------------------------------------------
# 四、structure: the rule list, the house-rule discipline, the controls
# --------------------------------------------------------------------------


def test_both_rules_are_in_builtin_pcb_rules_in_the_declared_order():
    """They are the fourth and fifth MCU-side inserts, inside the house block.

    Both answer *placement* questions about one object (an MCU), so they sit
    with 131b/131c/131d and ahead of the geometry sweep and the two
    standards-derived readings. **131f** later inserted
    ``pcb-mcu-crystal-keepout`` between 131d's rule and these two, which is
    why the list below has one more id than it did when this test was written
    and why the adjacency assertions no longer say 「immediately after 131d」:
    they say the supply pair is a **contiguous block**, which is the property
    this test is actually about.
    """
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert ids == [
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
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]
    assert ids.index("pcb-mcu-reset-boot") == ids.index(
        "pcb-mcu-supply-groups"
    ) + 1
    assert ids.index("pcb-mcu-supply-groups") > ids.index(
        "pcb-mcu-crystal-placement"
    )
    for rule in BUILTIN_PCB_RULES:
        if rule.id in {"pcb-mcu-supply-groups", "pcb-mcu-reset-boot"}:
            assert isinstance(rule, (McuSupplyGroups, McuResetBoot))


def test_both_rules_are_info_with_no_distance_constant():
    """131e's 「INFO 无阈值，工具出数」, as an assertion on both halves.

    岳 has ruled on no supply-bypass distance, no reset-time, no ``NRST`` RC
    and no reset-button distance, so neither module may grow a
    ``*_DISTANCE_MIL`` and every row must be ``INFO``.
    """
    from boardwise.rules.pcb import mcureset, mcusupply

    for rule in (McuSupplyGroups(), McuResetBoot()):
        assert rule.source == "house rule（岳 2026-10 待裁）"
        assert rule.level == "L1-pcb-geometry"
    for module in (mcusupply, mcureset):
        assert not [
            name
            for name in dir(module)
            if name.endswith("_DISTANCE_MIL") or name.endswith("_MIL")
        ], "the rule sets no threshold — 岳 has ruled on none"
    for path in (FOC_100, ROBOT, PILLBOX):
        for rule_id in ("pcb-mcu-supply-groups", "pcb-mcu-reset-boot"):
            rows = _findings(path, rule_id)
            assert rows
            assert {row.severity for row in rows} == {"INFO"}


def test_llc_places_no_mcu_and_produces_silence():
    """llc is the empty-input control, and silence is the contract.

    ``llc_board.epro2`` places no part the shelf calls an MCU, so both rules
    produce **nothing** — not a zero-row placeholder — and adding them did not
    make the llc report non-clean (measured in
    ``test_126b_pcb_distance_rules.py::test_llc_is_clean_under_both_distance_rules``).
    """
    assert _findings(LLC, "pcb-mcu-supply-groups") == []
    assert _findings(LLC, "pcb-mcu-reset-boot") == []


def test_a_context_without_a_pcb_model_is_silent_for_both():
    """131c's contract, kept: no netlist for this document means no answers."""
    from boardwise.core.geometry import BoardGeometry
    from boardwise.rules.pcb.base import PcbReviewContext

    ctx = PcbReviewContext(board=BoardGeometry(), board_title="PCB1")
    assert McuSupplyGroups().check(ctx) == []
    assert McuResetBoot().check(ctx) == []


def test_measurements_are_structured_mil_distances():
    """Both rules carry 125's structured measurement shape where they measured."""
    supply = [
        row
        for row in _findings(ROBOT, "pcb-mcu-supply-groups")
        if row.target.measurement
    ]
    reset = [
        row
        for row in _findings(FOC_100, "pcb-mcu-reset-boot")
        if row.target.measurement
    ]
    assert supply and reset
    for row in supply + reset:
        assert row.target.measurement["unit"] == "mil"
        assert row.target.measurement["kind"] in {"distance", "area"}


# --------------------------------------------------------------------------
# synthetic helpers
# --------------------------------------------------------------------------


def _model_with(parts, nets, names=None):
    """A minimal ``DesignModel`` from ``{designator: (value, mpn, footprint)}``.

    The same shape 131d's test builds, so a synthetic board here reads the way
    one there does — ``nets`` maps a net name to
    ``[(owner designator, pin number)]``, and ``names`` maps
    ``(designator, pin number)`` to a pin **name**, which both of 131e's rules
    read rather than the net.
    """
    names = names or {}
    model = DesignModel()
    for designator, (value, mpn, footprint) in parts.items():
        pins = [
            Pin(pin_number, names.get((designator, pin_number), ""), net)
            for net, members in nets.items()
            for owner, pin_number in members
            if owner == designator
        ]
        pins.sort(key=lambda p: p.number)
        model.components[designator] = Component(
            uid=designator, designator=designator, value=value, mpn=mpn,
            footprint=footprint, pins=pins,
        )
        for pin in pins:
            if pin.net:
                model.nets.setdefault(pin.net, Net(name=pin.net, pins=[]))
                model.nets[pin.net].pins.append((designator, pin.number))
    return model


def _shelf_stub():
    """A one-entry shelf that calls ``STM32G431RBT6`` an ``ic.mcu``.

    Both rules read MCU identity from a **stated field** — 131a's whole
    argument — so a synthetic board has to hand them one rather than relying on
    the project shelf. ``library=None`` is the other honest reading (an empty
    shelf means nothing reads as an MCU, and the rules then stay silent), which
    is why this stub exists rather than the tests monkeypatching
    ``default_library_path``.
    """
    from boardwise.core.parts import PartEntry

    entry = PartEntry(
        key="stub", category="ic.mcu", mpn="STM32G431RBT6", lcsc="C-stub",
        value="STM32G431RBT6", footprint_name="LQFP64", params={}, facts={},
    )
    return SimpleLibrary(entry)


class SimpleLibrary:
    """The smallest object :func:`boardwise.core.parts.find_facts` accepts."""

    def __init__(self, entry):
        self._entry = entry
        self.parts = [entry]

    def get(self, key, default=None):
        return self._entry if key == self._entry.key else default