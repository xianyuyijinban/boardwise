"""527D3 — the tier gate, one reader at a time (`core.partkind.declared_category`).

**What this batch is about.** 527D's red team measured (H3) that ``entry.category``
had fourteen direct readers across ``rules/`` and ``core/``, so a machine-granted
class — exactly what ``parts classify --from … --quote …`` writes — could still
drive every conclusion rule in the harness. 527D3 gives those readers one
choke point (:func:`boardwise.core.partkind.declared_category`) and one way to
say *why* they may not read a class
(:func:`boardwise.core.partkind.category_verdict`, whose ``gated`` answer is the
load-bearing half).

**The one shape this file exists to catch.** ``declared_category`` answers
``None`` both for 「a class this rule may not act on」 and for 「no class at all」,
so a reader that tests it directly — or that folds it into its own 「no entry →
skip」 path — makes a real MCU whose class merely nobody signed vanish from the
MCU rules with the silence a mounting screw gets. That is **worse** than the raw
``entry.category`` read it replaced, and every parametrised case below asserts the
opposite: the gated part comes back *somewhere* (a gated list, a fourth return
slot, a disclosure line, an UNKNOWN row) rather than nowhere.

The four things the batch's task book asks for are the four groups below: ① the
entry's four states, ② every changed read point's two states with the
not-silent half, ③ the H5 isomorphism (a draft is blocked even where a
machine-granted class is allowed), ④ ``category_provenance`` is not a second
tier, and ⑤ the end-to-end shape on one board: a conclusion rule turns into a
免责 row while a number rule's product is byte-identical.
"""

from __future__ import annotations

import dataclasses

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.partkind import (
    CATEGORY_ABSENT,
    CATEGORY_ACCEPTED,
    CATEGORY_GATED,
    category_verdict,
    declared_category,
)
from boardwise.core.parts import (
    FACTS_TRUST_CANDIDATE,
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_VERIFIED,
    PartEntry,
    PartLibrary,
    resolve_component_facts,
)

# ---------------------------------------------------------------------------
# fixtures — one shelf, three tiers; one board, one subject per read point
# ---------------------------------------------------------------------------

_MPN = "ACME-PART-1"


def _entry(category: str, tier: str = FACTS_TRUST_VERIFIED, **kwargs) -> PartEntry:
    return PartEntry(
        key=f"{category}.{tier}",
        mpn=_MPN,
        lcsc="",
        category=category,
        category_trust=tier,
        **kwargs,
    )


def _shelf(category: str, tier: str, **kwargs) -> PartLibrary:
    return PartLibrary(parts=[_entry(category, tier, **kwargs)])


def _board(designator: str = "U1", pins: tuple[Pin, ...] = ()) -> DesignModel:
    """One part, resolvable through the device-name step of 186's identity chain."""
    component = Component(
        uid=designator.lower(),
        designator=designator,
        lcsc_part="",
        mpn="",
        props={"device_name": _MPN},
        pins=list(pins),
    )
    nets: dict[str, Net] = {}
    for pin in component.pins:
        if pin.net:
            nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                (designator, pin.number)
            )
    return DesignModel(components={designator: component}, nets=nets)


class _PlacedBoard:
    """The minimum a PCB rule asks of geometry: 「is this designator placed」.

    527D3 fix (红队 S8): ``nets`` is what ``pcb/foc.power_mosfets_of``'s
    ``Q``-plus-bus door reads (``net_names()`` / ``net(name).components``). The
    fixture used to answer ``net_names() == []`` and had no ``net()`` at all, so
    that door could **never** open here — which meant the S3 double-listing (one
    designator in ``found`` *and* in ``gated``) could not be reached by this
    file's probes. A fixture that cannot produce the bug cannot prove it absent.
    """

    def __init__(self, placed: tuple[str, ...], nets=None) -> None:
        self._placed = set(placed)
        self._nets = {
            str(name): [str(des) for des in members]
            for name, members in (nets or {}).items()
        }

    def component(self, designator: str):
        return object() if designator in self._placed else None

    def net_names(self) -> list[str]:
        return sorted(self._nets)

    def net(self, name: str):
        return _PlacedNet(self._nets.get(str(name), []))


class _PlacedNet:
    """Just the one attribute ``power_mosfets_of`` reads off a net."""

    def __init__(self, components: list[str]) -> None:
        self.components = list(components)


_LDO_FACTS = {
    "supply_pins": [{"pins": ["1"]}],
    "required_caps": [{"pin": "2"}],
    # 527D3 fix (红队 S8): a **record**, not a bare float. `ldo_output_voltage_facts`
    # wants `{"volts": …, "provenance": …}` and returns None for anything else, so
    # the bare `3.3` this used to hold produced no KNOWN domain at **any** tier —
    # `_probe_power_domains`'s signed/machine assertions were passing vacuously.
    "ldo": {"fixed_output": {"volts": 3.3, "provenance": "ds.pdf, p.3"}},
}

#: 527D3 fix (红队 S8): the cap half of the decap probe's board. A second MPN, so
#: the two shelf entries resolve by different identity chains.
_CAP_LCSC = "C999"


def _decap_board(tier: str):
    """``(model, shelf)`` for the DECAP-1 read point: an LDO and one capacitor.

    The capacitor is the S1 shape: its **value is not on the board** and its
    designator is not C-shaped evidence by itself (no MPN code, no chip-size
    footprint), so route 1 and route 3 of ``looks_like_capacitor`` both fail and
    the shelf's class is the only thing that could carry it. Exactly one shelf
    entry names it, at the tier handed in.
    """
    ic = PartEntry(
        key="ic.ldo.probe",
        mpn="ACME-LDO-PROBE",
        lcsc="",
        category="ic.ldo",
        facts={"required_caps": [{"pin": "2", "value": "100nF"}]},
    )
    cap = PartEntry(
        key="capacitor.probe",
        mpn="",
        lcsc=_CAP_LCSC,
        category="capacitor",
        category_trust=tier,
    )
    shelf = PartLibrary(parts=[ic, cap])
    u1 = Component(
        uid="u1",
        designator="U1",
        lcsc_part="",
        mpn="ACME-LDO-PROBE",
        props={},
        pins=[Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "DECAP")],
    )
    c9 = Component(
        uid="c9",
        designator="C9",
        lcsc_part=_CAP_LCSC,
        mpn="",
        props={},
        pins=[Pin("1", "1", "DECAP"), Pin("2", "2", "GND")],
    )
    nets = {
        "+5V": Net(name="+5V", pins=[("U1", "1")]),
        "DECAP": Net(name="DECAP", pins=[("U1", "2"), ("C9", "1")]),
        "GND": Net(name="GND", pins=[("C9", "2")]),
    }
    return DesignModel(components={"U1": u1, "C9": c9}, nets=nets), shelf


def _mosfet_board() -> DesignModel:
    """``Q1`` on the bulk capacitor's net, ``Q2`` off it — 毕设FOC 1.0.0's shape.

    Both are the **same part number**, so the shelf answers about both with one
    entry; ``Q1`` is on ``+24V`` (where ``C115`` sits) and ``Q2`` is on a
    switching node, which is the pair S3 is about (the netlist-order fixture in
    the red team's report).
    """
    components = {
        "C115": Component(
            uid="c115", designator="C115", lcsc_part="", mpn="", props={},
            value="330uF",
        )
    }
    for designator, net in (("Q1", "+24V"), ("Q2", "MOTB")):
        components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            lcsc_part="",
            mpn=_MPN,
            props={"device_name": _MPN},
            pins=[Pin("1", "D", net), Pin("2", "S", "GND")],
        )
    nets = {
        "+24V": Net(name="+24V", pins=[("C115", "1"), ("Q1", "1")]),
        "MOTB": Net(name="MOTB", pins=[("Q2", "1")]),
        "GND": Net(name="GND", pins=[("Q1", "2"), ("Q2", "2")]),
    }
    return DesignModel(components=components, nets=nets)


class _StubRule:
    """Enough of a ``FactsRule`` for :func:`_opamp_output`'s two questions."""

    REQUIRES_HUMAN_VERIFIED = True

    def __init__(self, library: PartLibrary) -> None:
        self.library = library

    def entry_for(self, comp):
        entry, _matched = resolve_component_facts(self.library, comp)
        return entry


def _tiers() -> tuple[str, ...]:
    return (FACTS_TRUST_VERIFIED, FACTS_TRUST_MACHINE, FACTS_TRUST_CANDIDATE)


# ---------------------------------------------------------------------------
# ① the entry's four states
# ---------------------------------------------------------------------------


def test_the_entry_answers_four_states_and_none_is_not_no_class():
    """``declared_category``'s docstring, asserted state by state."""
    signed = _entry("ic.mcu", FACTS_TRUST_VERIFIED)
    machine = _entry("ic.mcu", FACTS_TRUST_MACHINE)
    draft = _entry("ic.mcu", FACTS_TRUST_CANDIDATE)
    uncategorised = _entry("", FACTS_TRUST_VERIFIED)

    # A human signed it: every caller reads it, whatever its own tier question is.
    assert declared_category(signed, allow_machine=False) == "ic.mcu"
    assert declared_category(signed, allow_machine=True) == "ic.mcu"

    # The machine tier: a number rule reads it, a conclusion rule may not.
    assert declared_category(machine, allow_machine=True) == "ic.mcu"
    assert declared_category(machine, allow_machine=False) is None

    # A draft: nothing reads it at any tier (the sweep's H5).
    assert declared_category(draft, allow_machine=True) is None
    assert declared_category(draft, allow_machine=False) is None

    # No entry, and an entry with no class, are the same answer — and it is the
    # 「not my subject」 one, not the 「gated」 one.
    assert declared_category(None, allow_machine=False) is None
    assert declared_category(None, allow_machine=True) is None
    assert declared_category(uncategorised, allow_machine=False) is None
    assert declared_category(uncategorised, allow_machine=True) is None


def test_the_three_outcomes_separate_the_two_none_answers():
    """``category_verdict`` is what keeps 「gated」 from reading as 「absent」."""
    categories = frozenset({"ic.mcu"})
    other = _entry("ic.ldo", FACTS_TRUST_MACHINE)

    assert (
        category_verdict(_entry("ic.mcu"), categories, allow_machine=False)
        == CATEGORY_ACCEPTED
    )
    assert (
        category_verdict(_entry("ic.mcu", FACTS_TRUST_MACHINE), categories,
                         allow_machine=True)
        == CATEGORY_ACCEPTED
    )
    assert (
        category_verdict(_entry("ic.mcu", FACTS_TRUST_MACHINE), categories,
                         allow_machine=False)
        == CATEGORY_GATED
    )
    assert (
        category_verdict(_entry("ic.mcu", FACTS_TRUST_CANDIDATE), categories,
                         allow_machine=True)
        == CATEGORY_GATED
    )
    assert category_verdict(other, categories, allow_machine=False) == CATEGORY_ABSENT
    assert category_verdict(None, categories, allow_machine=False) == CATEGORY_ABSENT
    assert (
        category_verdict(_entry(""), categories, allow_machine=False)
        == CATEGORY_ABSENT
    )


# ---------------------------------------------------------------------------
# ② every changed read point, in two states, and never silent
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Probe:
    """One read point's answer at one tier.

    ``subject`` — the part came back as this reader's subject (the rule may act);
    ``gated`` — it came back *gated*, i.e. the reader knows the shelf named a
    class this tier may not read; ``disclosed`` — the caller has a sentence to
    print about it. A reader that answers ``False`` to both has folded the two
    ``None`` answers together, which is the bug this batch exists to close.
    """

    subject: bool = False
    gated: bool = False
    disclosed: str = ""


@dataclasses.dataclass(frozen=True)
class ReadPoint:
    name: str
    #: True when the reader's own tier question is the *number* one, so a
    #: machine-granted class is expected to come back as a subject rather than
    #: gated (522's line, stated per rule as ``allow_machine``).
    allow_machine: bool
    probe: object  # callable(tier) -> Probe


def _mcu_pins() -> tuple[Pin, ...]:
    return (
        Pin("1", "VDD", "+3V3"),
        Pin("2", "NRST", "NRST"),
        Pin("3", "BOOT0", "BOOT0"),
        Pin("4", "PF0-OSC_IN", "OSC1"),
    )


def _probe_mcureset(tier: str) -> Probe:
    from boardwise.rules.pcb.mcureset import _read_mcus

    readings, gated = _read_mcus(_board(pins=_mcu_pins()), _shelf("ic.mcu", tier))
    return Probe(
        subject=bool(readings),
        gated=bool(gated),
        disclosed=f"{len(gated)} gated",
    )


def _probe_mcusupply(tier: str) -> Probe:
    from boardwise.rules.pcb.mcusupply import _read_mcus

    readings, gated = _read_mcus(_board(pins=_mcu_pins()), _shelf("ic.mcu", tier))
    return Probe(bool(readings), bool(gated), f"{len(gated)} gated")


def _probe_crystal(tier: str) -> Probe:
    from boardwise.rules.pcb.crystal import _mcu_oscillators

    readings, gated = _mcu_oscillators(_board(pins=_mcu_pins()), _shelf("ic.mcu", tier))
    return Probe(bool(readings), bool(gated), f"{len(gated)} gated")


def _probe_crystalkeepout(tier: str) -> Probe:
    from boardwise.rules.pcb.crystalkeepout import crystal_designators

    model = _board(pins=_mcu_pins())
    found, gated = crystal_designators(
        model, _PlacedBoard(("X1",)), _shelf("ic.mcu", tier)
    )
    return Probe(
        subject=bool(gated) or found is not None,
        gated=bool(gated),
        disclosed="；".join(str(getattr(osc, "designator", "")) for osc in gated),
    )


def _probe_regulator(tier: str) -> Probe:
    from boardwise.rules.pcb.regulator import _regulator_readings

    readings, gated = _regulator_readings(
        _board(pins=(Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "+3V3"))),
        _shelf("ic.ldo", tier),
    )
    return Probe(bool(readings), bool(gated), f"{len(gated)} gated")


def _probe_fbplacement(tier: str) -> Probe:
    from boardwise.rules.pcb.fbplacement import fb_dividers

    model = _board(pins=(Pin("1", "VIN", "+5V"), Pin("2", "FB", "FBTAP")))
    _dividers, gated = fb_dividers(model, _shelf("ic.ldo", tier))
    return Probe(bool(gated), bool(gated), f"{len(gated)} gated")


def _probe_motor_drivers(tier: str) -> Probe:
    from boardwise.rules.pcb.foc import _motor_drivers

    drivers, gated = _motor_drivers(_board(), _shelf("ic.motor-driver", tier))
    return Probe(bool(drivers), bool(gated), f"{len(gated)} gated")


def _probe_power_mosfets(tier: str) -> Probe:
    """``pcb/foc.power_mosfets_of`` — and the S3 invariant, empirically.

    **The fixture carries the netlist** (527D3 fix, 红队 S8): ``Q1`` sits on the
    bulk capacitor's net and ``Q2`` does not, so the class door's refusal and the
    ``Q``-plus-bus door are both live on one board. ``gated`` is therefore not
    「the second list is non-empty」 but 「the second list is a coherent
    disclosure」: a designator the reading *did* measure must not also be disclaimed
    as 「没有量」, because that is one report contradicting itself about one part
    (S3, measured on the red team's real fixture). Reverting the fix puts ``Q1``
    in both lists and this goes False.
    """
    from boardwise.rules.pcb.foc import power_mosfets_of

    board = _PlacedBoard(
        ("Q1", "Q2", "C115"), nets={"+24V": ("C115", "Q1"), "MOTB": ("Q2",)}
    )
    fets, gated = power_mosfets_of(board, _mosfet_board(), _shelf("fet", tier))
    measured = {designator for designator, _category, _basis in fets}
    disclaimed = {designator for designator, _category, _tier in gated}
    return Probe(
        subject=bool(fets),
        gated=bool(gated) and not (measured & disclaimed),
        disclosed=(
            f"found={sorted(measured)}；gated={sorted(disclaimed)}"
            f"；IN BOTH={sorted(measured & disclaimed)}"
        ),
    )


def _probe_looks_like_resistor(tier: str) -> Probe:
    from boardwise.rules.pcb.focground import _looks_like_resistor

    model = _board("U7")
    looks, _basis, gated = _looks_like_resistor(
        "U7", "0R", model, _shelf("resistor", tier)
    )
    return Probe(looks, bool(gated), gated)


def _probe_opamp(tier: str) -> Probe:
    from boardwise.rules.archclosure import _opamp_output

    model = _board(pins=(Pin("1", "OUT", "BIAS"),))
    shelf = _shelf("ic.opamp", tier)
    answer = _opamp_output(model, _StubRule(shelf), "BIAS")
    if answer is None:
        return Probe()
    _designator, _name, because, gated = answer
    return Probe(bool(because), bool(gated), gated)


def _probe_railratings(tier: str) -> Probe:
    from boardwise.core.designintent import DesignIntent, IntentSource
    from boardwise.rules.railratings import LdoDissipation

    model = _board(pins=(Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "+3V3")))
    shelf = _shelf("ic.ldo", tier, facts=dict(_LDO_FACTS))
    rule = LdoDissipation(
        library=shelf,
        intent=IntentSource(
            document=DesignIntent(rails=[]), path="mem://527d3-contract.json"
        ),
    )
    rows = rule._rows(model)
    unknown = [outcome for outcome, _severity in rows if outcome.state == "UNKNOWN"]
    # The subject half: this fixture's rule produces a row at every tier — the
    # difference is *why*, and the gated one says so in its missing_fact.
    return Probe(
        subject=bool(rows),
        gated=bool(unknown)
        and any("档位" in (row.missing_fact or "") for row in unknown),
        disclosed="；".join(row.missing_fact or "" for row in unknown),
    )


def _probe_architecture_controller(tier: str) -> Probe:
    from boardwise.core.architecture import gated_classifications, controller_evidence

    model = _board(designator="U3")
    shelf = _shelf("ic.mcu", tier)
    component = model.components["U3"]
    evidence = controller_evidence(component, shelf)
    gated = gated_classifications(model, shelf)
    return Probe(bool(evidence), bool(gated), "；".join(c for _d, c in gated))


def _probe_architecture_rails(tier: str) -> Probe:
    from boardwise.core.architecture import gated_classifications

    model = _board(designator="U5", pins=(Pin("1", "VOUT", "+3V3"),))
    shelf = _shelf("ic.ldo", tier)
    gated = gated_classifications(model, shelf)
    return Probe(bool(gated), bool(gated), "；".join(c for _d, c in gated))


def _probe_power_domains(tier: str) -> Probe:
    """``core/power_domains.infer_net_domains`` — and the KNOWN path for real.

    527D3 fix (红队 S8): the fixture's ``ldo.fixed_output`` is a **record** now
    (see :data:`_LDO_FACTS`), so ``allow_machine=False`` + a signed class really
    does produce a ``KNOWN`` domain. It used to hold a bare float, which
    ``ldo_output_voltage_facts`` refuses — ``guess`` was therefore ``None`` at
    *every* tier and every assertion here was vacuous (the old code even returned
    an all-``False`` :class:`Probe` when the guess was missing, which reads as
    「not a subject, not gated」 and satisfies nothing).
    """
    from boardwise.core.power_domains import infer_net_domains

    model = _board(pins=(Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "RAIL_A")))
    shelf = _shelf("ic.ldo", tier, facts=dict(_LDO_FACTS))
    guesses = infer_net_domains(model, shelf, allow_machine=False)
    guess = guesses.get("RAIL_A")
    if guess is None:
        return Probe()
    return Probe(
        subject=guess.is_known,
        gated=guess.state == "UNKNOWN" and "货架分类" in guess.detail,
        disclosed=guess.detail,
    )


def _probe_decap(tier: str) -> Probe:
    """``rules/decap`` — asserted on the **outcome**, not on the gate (红队 S8).

    This read point's tier question is ``allow_machine=True`` (every consumer
    turns 「is a capacitor」 into a capacitance or an inventory count), so a
    machine-granted class is a **subject** here and a draft is not. What the
    probe asserts is what the report has to contain, because the gate's own
    answer is not the thing that broke (S1): a draft-class capacitor stays in
    ``cap_candidates_on`` (the part is inventory), the rule speaks at every tier,
    and the row is never the VIOLATION 「no grounded capacitor found on net
    'DECAP'」 — a false statement about a net that has one, and the exact
    regression the tier gate introduced.
    """
    from boardwise.rules.decap import (
        DecapRequiredCaps,
        cap_candidates_on,
        looks_like_capacitor,
    )

    model, shelf = _decap_board(tier)
    accepted = looks_like_capacitor("C9", "", "", _CAP_LCSC, shelf)
    pool = [candidate.designator for candidate in cap_candidates_on(model, "DECAP", shelf)]
    rows = [
        outcome
        for outcome, _severity in DecapRequiredCaps(library=shelf)._rows(model)
    ]
    violations = [row for row in rows if row.state == "VIOLATION"]
    return Probe(
        subject=bool(pool) and accepted,
        gated=bool(pool) and not accepted and bool(rows) and not violations,
        disclosed="；".join(row.message for row in rows),
    )


def _probe_params_kind(tier: str) -> Probe:
    """``rules/params._kind_of`` — asserted on the row the rule writes (红队 S8).

    ``ValueMpnMatch`` used to answer a gated class with the same ``continue`` a
    mounting screw gets (S5), so the probe asserts the part comes back **as a
    row** at the draft tier while the machine tier still names it a subject. The
    reader's own three-state answer is asked alongside, but it is not what is
    asserted.
    """
    from boardwise.rules.params import ValueMpnMatch, _kind_of

    model = _board()
    component = model.components["U1"]
    shelf = _shelf("resistor", tier)
    entry, _matched = resolve_component_facts(shelf, component)
    kind, gated_reason = _kind_of(component, entry, allow_machine=True)
    rows = [
        outcome
        for outcome, _severity in ValueMpnMatch(library=shelf)._rows(model)
    ]
    return Probe(
        subject=bool(rows),
        gated=bool(gated_reason) and kind is None and bool(rows),
        disclosed=f"kind={kind!r}；gated={gated_reason}；"
        + "；".join(row.message for row in rows),
    )


def _probe_paramspec_ldo_price(tier: str) -> Probe:
    """``rules/paramspec.independent_rail_price`` — the third slot, on the row.

    527D3 fix (红队 S8): the old probe asserted ``gated = volts is None``, which
    is the same statement as ``not subject`` — a tautology that cannot fail
    whatever the reader returns. The thing S5 measured is narrower and testable:
    a **gated neighbour** must reach the caller as a printable reason, i.e.
    ``sel_rail_voltage``'s ``why_not`` has to carry the tier sentence rather than
    the same 「no source names the voltage」 a board with no regulator at all
    gets.
    """
    from boardwise.core.power_domains import infer_net_domains
    from boardwise.rules.paramspec import independent_rail_price, sel_rail_voltage

    model = _board(pins=(Pin("1", "VIN", "+5V"), Pin("2", "VOUT", "RAIL_A")))
    shelf = _shelf(
        "ic.ldo",
        tier,
        facts=dict(_LDO_FACTS),
        params={"Output Voltage": "3.3V"},
    )
    guess_volts, guess_source, gated_reason = independent_rail_price(
        model, shelf, "RAIL_A", subject="U9"
    )
    volts, source, why = sel_rail_voltage(
        None,
        infer_net_domains(model, shelf, allow_machine=True),
        "RAIL_A",
        subject="U9",
        model=model,
        library=shelf,
    )
    return Probe(
        subject=volts is not None,
        gated=bool(gated_reason) and guess_volts is None and "档位" in why,
        disclosed=f"volts={volts!r}；why={why}",
    )


READ_POINTS: tuple[ReadPoint, ...] = (
    ReadPoint("pcb/mcureset._read_mcus", False, _probe_mcureset),
    ReadPoint("pcb/mcusupply._read_mcus", False, _probe_mcusupply),
    ReadPoint("pcb/crystal._mcu_oscillators", False, _probe_crystal),
    ReadPoint("pcb/crystalkeepout.crystal_designators", False, _probe_crystalkeepout),
    ReadPoint("pcb/regulator._regulator_readings", False, _probe_regulator),
    ReadPoint("pcb/fbplacement.fb_dividers", False, _probe_fbplacement),
    ReadPoint("pcb/foc._motor_drivers", False, _probe_motor_drivers),
    ReadPoint("pcb/foc.power_mosfets_of", False, _probe_power_mosfets),
    ReadPoint("pcb/focground._looks_like_resistor", False, _probe_looks_like_resistor),
    ReadPoint("archclosure._opamp_output", False, _probe_opamp),
    ReadPoint("railratings.LdoDissipation", True, _probe_railratings),
    ReadPoint("core/architecture.controller_evidence", False,
              _probe_architecture_controller),
    ReadPoint("core/architecture.rails", False, _probe_architecture_rails),
    ReadPoint("core/power_domains.infer_net_domains", False, _probe_power_domains),
    ReadPoint("rules/decap.looks_like_capacitor", True, _probe_decap),
    ReadPoint("rules/params._kind_of", True, _probe_params_kind),
    ReadPoint("rules/paramspec.independent_rail_price", True,
              _probe_paramspec_ldo_price),
)


@pytest.mark.parametrize("point", READ_POINTS, ids=lambda p: p.name)
def test_every_read_point_answers_three_states(point: ReadPoint):
    """The whole batch in one parametrised assertion, per read point.

    * a **signed** class: the reader's subject, and never gated — the human tier's
      behaviour is byte-for-byte what it was before 527D3;
    * a **machine-granted** class: a subject for the read points whose own tier
      question is the number one (``allow_machine``), and **gated with a
      disclosure** for the conclusion ones — never nothing at all;
    * a **draft**: gated for every reader, including the number-tier ones (H5).
    """
    verified = point.probe(FACTS_TRUST_VERIFIED)
    assert not verified.gated, (
        f"{point.name} gated a human-signed class: {verified.disclosed}"
    )

    machine = point.probe(FACTS_TRUST_MACHINE)
    if point.allow_machine:
        assert machine.subject, (
            f"{point.name} dropped a machine-granted class although its tier "
            f"allows it: {machine.disclosed}"
        )
    else:
        assert machine.gated, (
            f"{point.name} silently dropped a machine-granted class — the bug "
            "527D3 exists to close"
        )
        assert machine.disclosed, f"{point.name} gated without saying anything"

    draft = point.probe(FACTS_TRUST_CANDIDATE)
    assert draft.gated, (
        f"{point.name} let a candidate class through (the sweep's H5): a draft "
        "must not open a door the evidence-checked tier had to knock on"
    )


# ---------------------------------------------------------------------------
# ③ the H5 isomorphism, stated where a rule reads it
# ---------------------------------------------------------------------------


def test_a_draft_is_blocked_even_where_the_machine_tier_is_allowed():
    """``candidate`` is weaker than ``machine_verified``, so it must be narrower.

    527D's H5 measured the opposite: writing the gate as 「anything not verified
    and not allow_machine」 left ``candidate`` **more** permissive than the
    evidence-checked tier for the calculation rules. The fix is structural —
    ``declared_category`` refuses a draft before it ever looks at
    ``allow_machine`` — and this asserts it on the entry and on the three
    number-tier readers this batch touches.
    """
    draft = _entry("ic.mcu", FACTS_TRUST_CANDIDATE)
    assert declared_category(draft, allow_machine=True) is None
    assert declared_category(draft, allow_machine=False) is None

    from boardwise.rules.decap import looks_like_capacitor
    from boardwise.rules.params import _kind_of

    model = _board()
    component = model.components["U1"]
    shelf = _shelf("capacitor", FACTS_TRUST_CANDIDATE)
    entry, _matched = resolve_component_facts(shelf, component)
    # 527D3 fix: `_kind_of` answers a 2-tuple now — the kind and the reason it may
    # not be read — and the draft's half is what the *caller* writes a row from.
    kind, gated_reason = _kind_of(component, entry, allow_machine=True)
    assert kind is None
    assert gated_reason, "a gated class must come back with a printable reason"
    assert looks_like_capacitor("U1", "", _MPN, "", shelf) is False


# ---------------------------------------------------------------------------
# ④ 527D2's citation record is not a second tier
# ---------------------------------------------------------------------------


def test_category_provenance_never_changes_the_verdict():
    """``category_provenance`` says *where* a class came from, not *who signed*.

    The tier is ``category_trust`` and nothing else: an entry whose class was
    granted by a machine **and** whose evidence is on the shelf is still a
    machine-granted class, and a hand-signed class with a citation left over from
    an earlier machine run is still hand-signed (522's rule for ``facts_trust``,
    one field over).
    """
    cited = {
        "source": "https://example.invalid/ds.pdf",
        "page": 7,
        "quote": "The device is a microcontroller.",
    }
    categories = frozenset({"ic.mcu"})
    for tier in _tiers():
        without = _entry("ic.mcu", tier)
        with_citation = _entry("ic.mcu", tier, category_provenance=dict(cited))
        for allow in (True, False):
            assert declared_category(without, allow_machine=allow) == declared_category(
                with_citation, allow_machine=allow
            ), (tier, allow)
            assert category_verdict(
                without, categories, allow_machine=allow
            ) == category_verdict(with_citation, categories, allow_machine=allow)


# ---------------------------------------------------------------------------
# ⑤ end to end: one board, a conclusion rule and a number rule
# ---------------------------------------------------------------------------


def _mcu_model() -> DesignModel:
    return _board(
        "U1",
        pins=(
            Pin("1", "VDD", "+3V3"),
            Pin("2", "NRST", "NRST"),
            Pin("3", "BOOT0", "BOOT0"),
        ),
    )


def _pcb_ctx(model: DesignModel):
    from boardwise.rules.pcb.base import PcbReviewContext

    return PcbReviewContext(
        board=_PlacedBoard(("U1",)), board_title="PCB1", pcb_model=model
    )


def _rows(findings) -> list[dict]:
    return [dataclasses.asdict(finding) for finding in findings]


def test_a_conclusion_rule_turns_into_a_disclaimer_and_not_into_silence():
    """The conclusion half of ⑤: 「有结论」 → 「免责 row」, never 「没有这条网」."""
    from boardwise.rules.pcb.mcureset import McuResetBoot

    ctx = _pcb_ctx(_mcu_model())
    verified = McuResetBoot().check_with_library(
        ctx, _shelf("ic.mcu", FACTS_TRUST_VERIFIED), allow_machine=False
    )
    machine = McuResetBoot().check_with_library(
        ctx, _shelf("ic.mcu", FACTS_TRUST_MACHINE), allow_machine=False
    )

    assert verified, "the signed shelf must still produce the reset/boot rows"
    assert machine, "the machine-tier shelf must not go silent"
    assert all("货架把它分类为" in finding.message for finding in machine), (
        [f.message for f in machine]
    )
    assert all("机器核验" in finding.message for finding in machine)
    # …and not one of the real measurements came through.
    assert not any("NRST" in finding.message for finding in machine)


def test_a_number_rule_is_byte_identical_across_the_two_tiers():
    """The number half of ⑤: 522 lets the machine tier name the subject.

    ``pcb-mcu-supply-groups`` states ``allow_machine=True`` (its rows are
    measurements), so the shelf's signature on the *class* is not what its
    numbers rest on — and its product must be bit-for-bit the same under a
    machine-granted class as under a hand-signed one.
    """
    from boardwise.rules.pcb.mcusupply import McuSupplyGroups

    ctx = _pcb_ctx(_mcu_model())
    signed = McuSupplyGroups().check_with_library(
        ctx, _shelf("ic.mcu", FACTS_TRUST_VERIFIED), allow_machine=True
    )
    machine = McuSupplyGroups().check_with_library(
        ctx, _shelf("ic.mcu", FACTS_TRUST_MACHINE), allow_machine=True
    )
    assert signed, "the fixture must produce a row at all"
    assert _rows(machine) == _rows(signed)


def test_the_number_rule_without_its_tier_keyword_is_conservative():
    """The default is the conservative one, and it discloses rather than drops."""
    from boardwise.rules.pcb.mcusupply import McuSupplyGroups

    ctx = _pcb_ctx(_mcu_model())
    machine = McuSupplyGroups().check_with_library(
        ctx, _shelf("ic.mcu", FACTS_TRUST_MACHINE)
    )
    assert machine, "a gated class must still produce its 免责 row"
    assert all("货架把它分类为" in finding.message for finding in machine)
