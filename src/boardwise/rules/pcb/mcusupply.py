"""An MCU's supply **groups**, by net rather than by pin (task 131e).

131b asked 「the regulator's input capacitor」 and 131c 「the regulator's
feedback divider」: one part, one or two named pins, so a per-pin reading was
the natural shape. An MCU breaks that shape, and the task's reconnaissance
measured why rather than assuming it:

* **A per-pin reading is not merely wrong here, it is unmeasurable.** The H7's
  LQFP-100 pins sit 19.7 mil apart and a 0603 capacitor is 55 mil wide, so
  「the bypass must be within N mil of *this* pin」 has no threshold a reader
  could set that does not fire on every correctly-placed part. 131e therefore
  refuses the per-pin question outright and asks the one a layout can answer:
  **for each supply net the MCU actually uses, how near is the bypass that
  serves that net.**
* **The supply net is the unit, not the pin.** An H743 folds its six supply
  inputs (pins 6/11/27/50/75/100 — ``VBAT`` + five ``VDD``) onto one net
  ``VCC``, and all six are served by the same bypass. A per-pin row would print
  the same capacitor six times and imply six requirements where the board has
  one.

**Which pins form a group, and what is deliberately not a group.** The group
membership is read through :func:`boardwise.core.pinrole.pin_role` — the
131a classifier — asking for :data:`SUPPLY_ROLES` (``IN``, ``GND``, ``EP``).
That is what makes the grouping *measured* rather than guessed: the pin's own
declared name decides, and a name the table does not know simply does not join
a group. ``VBAT`` needs no separate rule — 131a's whole-name table already reads
it as ``IN``, so H743's pin 6 and its pin 11 land in the same ``VCC`` group
because the board put them on the same net, not because a name matched twice.
``VCAP`` is the deliberate exclusion and gets its own rows
(:func:`vcap_pins_of`): it is an internal-regulator output the datasheet requires
a capacitor on, not a supply the MCU is fed from, and folding it into a group
would put a bypass requirement on a node that already *is* one capacitor.

**The bypass pool, and why the two group kinds read it differently.** A bypass is
a capacitor **bridging the group net to a ground-class net**, which is
:func:`boardwise.rules.decap.cap_candidates_on` verbatim — the same predicate
126b / 131b / 131d already use, so the four rules cannot disagree about what a
grounded capacitor is. But that predicate is undefined *on* a ground net: 1.0.0's
``GND`` group and ``AGND`` group are themselves ground-class, and a bypass for a
supply group sits on that group with its **other** end on the non-ground side.
:func:`bypass_pool` therefore picks the predicate by the group's own kind:

* a **non-ground** group (1.0.0's ``VCC``, ``VCCA``, ROBOT's ``VCCA``) uses
  :func:`~boardwise.rules.decap.cap_candidates_on`;
* a **ground-class** group (1.0.0's ``GND``, ``AGND``) is read by
  :func:`ground_group_bypass_pool`, which takes capacitors with **one** terminal
  on this ground net and the other on a *non*-ground net — the same predicate
  with the two sides swapped, and the one that makes 「the ground return has a
  bypass next to it」 mean anything.

Had the rule used only the first predicate it would have reported 1.0.0's ``GND``
group as having **no bypass at all**, while ``C1`` sits 33.5 mil from the H743's
ground pins. A rule that says 「nothing found」 where the answer is 「the nearest
thing is 33.5 mil away」 is the silent direction, so the second predicate exists.

**Two columns, not one verdict.** Every group prints its **nearest high-frequency
bypass** (``< 1 µF``, :data:`~boardwise.rules.pcb.distance.HF_FARADS` — the
ceramic-bypass ceiling 126b already adopted) and its **nearest reservoir**
(``>= 1 µF``) side by side, because the two answer different questions and a
reader needs both before judging either: the bypass bounds the switching loop and
the reservoir holds the rail between load events, and a board with only one of
them is a different board from a board with the other one far away.

**Measured, not judged.** As in 131b, 131c and 131d there is no
``*_DISTANCE_MIL`` constant here and every row is ``INFO``: the 1 µF pool split is
126b's established reading, but *how near* is near has no ruling, and a rule that
invented a threshold would put a number in the ledger nobody decided.

**Empty is a row, not silence.** A group whose pool is empty prints the pool as
empty and says which of the two columns is unstated — that is ROBOT's ``$1N251``
(``VSSA``, whose only other member is a 0 Ω resistor) and 1.0.0's ``VREF``
(whose members are the H743 and the REF2033 and no capacitor whatsoever).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from ...core.measure import component_distance
from ...core.model import is_ground_net
from ...core.parts import find_facts, load_parts
from ...core.pinrole import pin_role
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on, looks_like_capacitor
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .crystal import MCU_CATEGORIES
from .distance import HF_FARADS, _measurement, _mil

__all__ = [
    "HF_CEILING_FARADS",
    "SUPPLY_NAME_EXTRAS",
    "SUPPLY_NAME_MARKER",
    "SUPPLY_ROLES",
    "VCAP_NAME_MARKER",
    "McuSupply",
    "McuSupplyGroups",
    "bypass_pool",
    "ground_group_bypass_pool",
    "supply_groups_of",
    "vcap_pins_of",
]


#: The pin roles that make a pin a member of a **supply group**.
#:
#: Read through :func:`boardwise.core.pinrole.pin_role`, never off the net name
#: and never off a designator prefix. ``IN`` covers ``VCC`` / ``VDD`` / ``VBAT`` /
#: ``VDDA`` and every sibling the 131a table knows; ``GND`` covers ``VSS`` /
#: ``VSSA`` / ``AGND``-style returns, which are a supply group of their own and
#: get the ground-net reading of the bypass pool; ``EP`` covers an exposed pad,
#: which 126b's :func:`~boardwise.rules.pcb.distance.classify_device` already
#: treats as a thermal-tied ground.
#:
#: ``OUT`` and ``BST`` are **excluded** on purpose: an MCU's ``BOOT``-adjacent
#: switch node and a gate driver's bootstrap pin are supplies of *something
#: else*, and 131d already found what happens when a non-supply pin is let into
#: a supply pool (an ``OSC`` pin read as ``IN``).
SUPPLY_ROLES: frozenset[str] = frozenset({"IN", "GND", "EP"})

#: Names that are a **supply** by the datasheet's own spelling even though
#: :func:`boardwise.core.pinrole.pin_role` declines them, and which therefore
#: need the small explicit list rather than a pattern.
#:
#: **Every entry here is a measured gap in 131a's table, and each is stated
#: rather than assumed.** ``VREF+`` is the load: an STM32's reference input is a
#: supply-like node the datasheet asks to be decoupled, 131a's whole-name table
#: has no ``VREF`` row and ``+`` is in ``_NOT_A_ROLE`` as a bare polarity, so
#: ``pin_role('VREF+')`` answers ``None`` and a reference net carrying no
#: capacitor at all (毕设FOC 1.0.0's ``VREF`` — the two members are the H743 and
#: the REF2033) would have been **silently absent** from the ledger. A data gap
#: nobody reports is the one failure mode this rule is written to avoid, and the
#: task pins the case, so it is read here explicitly.
#:
#: ``VDDA``-style names are *not* here: ``pin_role`` already reads those as
#: ``IN``. The list is deliberately the residue, not a second table — an entry
#: that :func:`~boardwise.core.pinrole.pin_role` already answers would be a
#: duplicate that could drift from the table it shadows, and a test pins that
#: none of these three is redundant.
SUPPLY_NAME_EXTRAS: frozenset[str] = frozenset({"VREF+", "VREF-", "VREF"})

#: The substring that makes an entry of :data:`SUPPLY_NAME_EXTRAS` a supply.
#:
#: Read on the **uppercased whole name**, and matched before normalisation strips
#: a trailing polarity: ``VREF+`` and ``VREF-`` are both the reference input and
#: its complement on a dual-supply part, and both are supplies.
SUPPLY_NAME_MARKER = "VREF"


def _supply_role_of(pin_name: str) -> str | None:
    """This pin name's supply role, or ``None``.

    :func:`~boardwise.core.pinrole.pin_role` first — the 131a classifier is the
    authority and 131e does not second-guess it — and then the explicit
    :data:`SUPPLY_NAME_EXTRAS` residue, which is added *only* for names the
    classifier declines and the datasheet calls a supply.

    The returned role for an extra is the literal ``"IN"``, so downstream code
    has one vocabulary; the row's evidence says which of the two routes put the
    pin in the group, because 「the table says so」 and 「131e's explicit residue
    list says so」 are different claims with different maintenance costs.
    """
    role = pin_role(pin_name)
    if role is not None:
        return role
    text = _upper(pin_name)
    if text in SUPPLY_NAME_EXTRAS:
        return "IN"
    return None

#: The value boundary between the two columns, in farads.
#:
#: Re-exported from :data:`boardwise.rules.pcb.distance.HF_FARADS` rather than
#: given a second literal: 126b's split and 131e's split must be the *same*
#: number, or two rules would call the same 1 µF part a bypass in one ledger and
#: a reservoir in the other. 131e reads it as 「bypass is strictly below, reservoir
#: at or above」 — the boundary case is stated, not left to a float comparison.
HF_CEILING_FARADS = HF_FARADS

#: The substring a pin's **name** must carry for it to be an MCU internal-
#: regulator (``VCAP``) pin, listed separately from every supply group.
#:
#: ``pin_role("VCAP")`` answers ``None`` — the name is neither in the table nor a
#: compound — which is *why* it cannot reach a group by accident. That is a
#: fortunate accident rather than the design, so the exclusion is made explicit
#: and pinned: read the name, say what it is, and keep it out of the pool.
VCAP_NAME_MARKER = "VCAP"


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


@dataclass(frozen=True)
class SupplyPin:
    """One MCU pin that joined a supply group, with what put it there.

    ``basis`` is the claim the row makes about that pin — ``"pinrole"`` when
    :func:`boardwise.core.pinrole.pin_role` answered, ``"name-extra"`` when
    :data:`SUPPLY_NAME_EXTRAS` did — and it is carried rather than recomputed so
    the evidence line cannot disagree with the decision that produced it.
    """

    number: str = ""
    name: str = ""
    role: str = ""
    basis: str = ""


@dataclass(frozen=True)
class McuSupply:
    """One MCU and its supply groups, folded **by net**."""

    designator: str = ""
    category: str = ""
    board_model: object = None
    #: ``{net: [SupplyPin, ...]}`` in pin order. One entry per net the MCU
    #: draws power on, which is the unit 131e measures — see the module head for
    #: why it is not the pin.
    groups: dict[str, list[SupplyPin]] = field(default_factory=dict)
    #: ``[(pin number, pin name, net)]`` for the ``VCAP`` pins, which are
    #: reported beside the groups and never inside one.
    vcap_pins: tuple[tuple[str, str, str], ...] = ()

    @property
    def nets(self) -> list[str]:
        return list(self.groups)


def vcap_pins_of(component: object) -> list[object]:
    """This part's pins whose **name** names an internal-regulator output.

    A substring test on the uppercased name, the same shape 131d used for the
    oscillator family and for the same reason: ``VCAP`` is a family spelling, not
    a table entry, and the rule has to be able to say *which pin* it means.
    """
    return [
        pin
        for pin in (getattr(component, "pins", ()) or ())
        if VCAP_NAME_MARKER in _upper(getattr(pin, "name", ""))
    ]


def supply_groups_of(component: object) -> dict[str, list[SupplyPin]]:
    """``{net: [SupplyPin]}`` — this MCU's supply pins folded by their net.

    Every pin whose name :func:`~boardwise.core.pinrole.pin_role` reads as one of
    :data:`SUPPLY_ROLES` joins the group of the net it is **on**. The net is the
    grouping key and the pin is the payload, which is the whole of 131e's
    departure from a per-pin reading: six ``VDD`` pins on one net are one group
    with six members, not six groups each demanding its own capacitor.

    A supply-role pin with **no net at all** is dropped rather than given an
    empty group. An unpopulated supply pin is a thing a symbol declares and a
    layout need not fit (the same reasoning 131d applied to an unpopulated
    32.768 kHz branch), and a group whose only key would be ``None`` would print
    a bypass requirement against a net that does not exist.
    """
    groups: dict[str, list[SupplyPin]] = {}
    for pin in getattr(component, "pins", ()) or ():
        name = str(getattr(pin, "name", "") or "")
        role = _supply_role_of(name)
        if role is None or role not in SUPPLY_ROLES:
            continue
        net = str(getattr(pin, "net", "") or "")
        if not net:
            continue
        groups.setdefault(net, []).append(
            SupplyPin(
                number=str(getattr(pin, "number", "") or ""),
                name=name,
                role=role,
                basis="name-extra" if pin_role(name) is None else "pinrole",
            )
        )
    return groups


def ground_group_bypass_pool(model: object, net: str, library=None) -> list[str]:
    """Capacitors that bypass a **ground-class** supply group.

    The complement of :func:`boardwise.rules.decap.cap_candidates_on` for the
    case that predicate cannot cover. For a ground net the bypass sits with one
    terminal **on this ground net** and the other on a **non-ground** net — the
    same "bridge to the other side" idea with the two sides swapped, and the one
    that makes a ground group's bypass column mean anything.

    Without this, 1.0.0's ``GND`` group would report an empty pool while ``C1``
    sits 33.5 mil from the H743's ground pins: the bypass for a return pin is by
    construction the capacitor whose *other* end is the rail, and the predicate
    126b/131b/131d share looks for a capacitor whose other end is *ground*.

    Only parts that already read as capacitors reach the list, by
    :func:`boardwise.rules.decap.looks_like_capacitor` — the same three-route
    test, so a resistor is not mistaken for a bypass and an unreadable-value
    capacitor is a candidate whose value the row will report as unreadable.
    """
    net_obj = (getattr(model, "nets", {}) or {}).get(net)
    if net_obj is None:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for designator, _pin in (getattr(net_obj, "pins", None) or []):
        owner = str(designator)
        if owner in seen:
            continue
        seen.add(owner)
        component = (getattr(model, "components", {}) or {}).get(owner)
        if component is None:
            continue
        if not looks_like_capacitor(
            component.designator,
            component.value or "",
            component.mpn or "",
            component.lcsc_part or "",
            library,
            footprint=component.footprint or "",
        ):
            continue
        others = {
            pin.net for pin in (getattr(component, "pins", ()) or ())
            if pin.net and pin.net != net
        }
        if any(not is_ground_net(other) for other in others):
            found.append(owner)
    return found


def bypass_pool(model: object, net: str, library=None) -> list[str]:
    """Every capacitor that bypasses ``net``, read by the net's own kind.

    The one place the two predicates are chosen, so a reader (and a mutation)
    only has to look here to see what 「a bypass on this group」 means. The
    ground-class branch is :func:`ground_group_bypass_pool`; everything else is
    :func:`boardwise.rules.decap.cap_candidates_on`, the predicate the other
    three PCB rules already share.
    """
    if is_ground_net(net):
        return ground_group_bypass_pool(model, net, library)
    return [
        candidate.designator for candidate in cap_candidates_on(model, net, library)
    ]


@dataclass(frozen=True)
class _PoolRead:
    """The bypass pool after the split, plus what the two columns cannot hold.

    ``unreadable`` and ``unplaced`` are separated on purpose: a capacitor whose
    value nobody wrote down is **present** and its column is UNKNOWN, while a
    part this PCB document does not place is **not measured**. Reporting the two
    as one list would tell a reader the board is missing a capacitor when the
    truth is that the tool could not read or could not see one.
    """

    bypass: list[tuple[float, str, str]] = field(default_factory=list)
    reservoir: list[tuple[float, str, str]] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)


def _split_pool(board: object, mcu: str, model: object, pool: list[str]) -> _PoolRead:
    """The pool split at :data:`HF_CEILING_FARADS`.

    A part whose value cannot be read is in **neither** column and is reported as
    :attr:`_PoolRead.unreadable`: an unreadable capacitance is UNKNOWN, never a
    zero and never a guess that it is small enough to be a bypass. This is the
    same argument :func:`boardwise.rules.pcb.distance.capacitor_role` makes.
    """
    result = _PoolRead()
    for designator in pool:
        component = (getattr(model, "components", {}) or {}).get(designator)
        distance = component_distance(board, designator, mcu)
        if component is None or distance is None:
            result.unplaced.append(designator)
            continue
        declared = str(getattr(component, "value", "") or "")
        farads = parse_capacitance_farads(declared) if declared else None
        if farads is None:
            result.unreadable.append(designator)
            continue
        row = (_mil(distance.edge_distance), designator, declared)
        if farads < HF_CEILING_FARADS:
            result.bypass.append(row)
        else:
            result.reservoir.append(row)
    result.bypass.sort()
    result.reservoir.sort()
    return result


def _read_mcus(model: object, library) -> list[McuSupply]:
    """Every ``ic.mcu`` part in this PCB document, with its groups read.

    The shelf is read through :func:`boardwise.core.parts.find_facts` (exact MPN
    then LCSC — #202's lesson), the same lookup 131b/131c/131d make, so the
    category the evidence quotes is the one the shelf states and the object set
    is identical across the four MCU rules.
    """
    readings: list[McuSupply] = []
    components = getattr(model, "components", {}) or {}
    for designator in sorted(components):
        component = components[designator]
        entry = find_facts(
            library,
            mpn=str(getattr(component, "mpn", "") or ""),
            lcsc=str(getattr(component, "lcsc_part", "") or ""),
        )
        category = (entry.category or "") if entry is not None else ""
        if category not in MCU_CATEGORIES:
            continue
        vcaps = tuple(
            (
                str(getattr(pin, "number", "") or ""),
                str(getattr(pin, "name", "") or ""),
                str(getattr(pin, "net", "") or ""),
            )
            for pin in vcap_pins_of(component)
            if getattr(pin, "net", "")
        )
        readings.append(
            McuSupply(
                designator=str(designator),
                category=category,
                board_model=model,
                groups=supply_groups_of(component),
                vcap_pins=vcaps,
            )
        )
    return readings


class McuSupplyGroups(PcbRule):
    """An MCU's supply **groups**, each with its nearest bypass and reservoir.

    One pass per MCU on this PCB document, and per **supply net** within it:

    1. the net is named by at least one supply-role pin of a part the shelf
       calls :data:`~boardwise.rules.pcb.crystal.MCU_CATEGORIES`
       (:data:`SUPPLY_ROLES`, read through 131a's ``pin_role``);
    2. the bypass pool is read by the net's own kind — a ground-class net by
       :func:`ground_group_bypass_pool`, anything else by the shared
       :func:`~boardwise.rules.decap.cap_candidates_on` predicate
       (:func:`bypass_pool`);
    3. the pool is split at :data:`HF_CEILING_FARADS` and the **nearest** part of
       each half is measured with
       :func:`~boardwise.core.measure.component_distance`;
    4. the ``VCAP`` pins are reported beside the groups with their own nets and
       capacitors, and are never grouped.

    **No per-pin row exists, and the module head says why** — on an LQFP the pin
    pitch is smaller than the part that has to sit next to it, so a per-pin
    threshold is unsatisfiable rather than merely strict.

    **Measured, not judged**: every row is ``INFO``, no distance threshold is in
    force. A board that places no part the shelf calls an MCU produces nothing,
    and ``llc_board.epro2`` is the standing example.
    """

    id = "pcb-mcu-supply-groups"
    title = "An MCU's supply nets each have a nearby bypass and reservoir"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf — the same contract 131b,
        131c and 131d honour, so a synthetic test can inject a two-entry library
        without monkeypatching the project's own
        :func:`boardwise.rules.facts.default_library_path`. An empty shelf means
        no part reads as an ``ic.mcu``, which this rule then reports as silence:
        MCU identity comes from a stated field (131a's whole argument), and a
        part the shelf has never heard of is UNKNOWN rather than guessed.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for mcu in _read_mcus(model, library):
            if board.component(mcu.designator) is None:
                continue  # no geometry on this PCB document: nothing to measure
            for net in sorted(mcu.groups):
                findings.append(self._one_group(mcu, board, net, library))
            for number, name, net in mcu.vcap_pins:
                findings.append(self._one_vcap(mcu, board, net, number, name, library))
        return findings

    # -- rows -------------------------------------------------------------

    def _identity(self, mcu: McuSupply) -> list[str]:
        """The evidence every row of one MCU's supply ledger carries."""
        return [
            f"{mcu.designator} read as an MCU because the shelf category is "
            f"{mcu.category!r}",
            f"supply-group membership read off the pin **name** through "
            f"core.pinrole.pin_role, asked for roles {sorted(SUPPLY_ROLES)} — "
            "never off the net name and never off a designator prefix; the "
            "grouping key is the **net**, so six supply pins on one net are one "
            "group with six members rather than six requirements",
            "**no per-pin row exists**: the H7's LQFP-100 pins sit 19.7 mil "
            "apart and a 0603 capacitor is 55 mil wide, so a per-pin distance "
            "threshold is unsatisfiable for a correctly-placed part — the "
            "measurement is per supply net, which is the unit a layout can "
            "actually answer for",
        ]

    def _members_of(self, mcu: McuSupply, net: str) -> str:
        net_obj = (getattr(mcu.board_model, "nets", {}) or {}).get(net)
        members = sorted(
            {str(owner) for owner, _pin in (getattr(net_obj, "pins", None) or [])}
        )
        return ", ".join(members) or "(none)"

    def _one_group(
        self, mcu: McuSupply, board: object, net: str, library
    ) -> Finding:
        """One supply group's row: its pins, its bypass column, its reservoir."""
        model = mcu.board_model
        pins = mcu.groups[net]
        ground_kind = is_ground_net(net)
        pool = bypass_pool(model, net, library)
        read = _split_pool(board, mcu.designator, model, pool)
        bypass, reservoir = read.bypass, read.reservoir
        pin_text = ", ".join(f"pin {p.number} {p.name!r} ({p.role})" for p in pins)

        evidence = [
            *self._identity(mcu),
            f"supply group net {net!r}: {len(pins)} pin(s) — {pin_text}",
            f"net {net!r} is a "
            + ("**ground-class** net, so its bypass pool is read by "
               "ground_group_bypass_pool (one terminal here, the other on a "
               "non-ground net — the two-sided swap of the shared predicate, "
               "which cannot see a bypass whose rail side is the ground net's "
               "other terminal)"
               if ground_kind else
               "**non-ground** net, so its bypass pool is "
               "boardwise.rules.decap.cap_candidates_on, the predicate 126b / "
               "131b / 131d already share"),
            f"net {net!r} members as the board declares them: "
            f"{self._members_of(mcu, net)}",
            f"bypass pool on {net!r}: "
            + (", ".join(sorted(pool)) or "(none)"),
            f"distance read with core.measure.component_distance, which refuses "
            f"same-net pad pairs by design — so the number is the gap between "
            f"the bypass body and the MCU body, not between two pads the board "
            f"deliberately wired together",
        ]
        extras = [p for p in pins if p.basis == "name-extra"]
        if extras:
            evidence.append(
                "pins whose role came from 131e's explicit "
                f"{sorted(SUPPLY_NAME_EXTRAS)} list rather than from "
                "core.pinrole.pin_role (which declines these names): "
                + ", ".join(f"pin {p.number} {p.name!r}" for p in extras)
                + " — a measured gap in 131a's table, listed because a "
                "reference net carrying no capacitor would otherwise be "
                "absent from the ledger rather than reported as empty"
            )
        unreadable_note = (
            "candidates whose value nobody wrote down, therefore in **neither** "
            "column (an unreadable capacitance is UNKNOWN, never a zero): "
            + (", ".join(sorted(read.unreadable)) or "(none)")
        )
        unplaced_note = (
            "candidates this PCB document does not place, therefore not "
            "measured at all (an unmeasurable part is not a far one): "
            + (", ".join(sorted(read.unplaced)) or "(none)")
        )
        evidence.append(unreadable_note)
        evidence.append(unplaced_note)

        if bypass:
            near_mil, near_designator, near_value = bypass[0]
            bypass_column = (
                f"**{near_designator}** {near_value} @ {near_mil:.1f} mil"
            )
            bypass_target = near_designator
        else:
            bypass_column = (
                "**none** — the pool holds no capacitor below "
                f"{HF_CEILING_FARADS * 1e6:g} µF that this document places"
            )
            bypass_target = ""

        if reservoir:
            bulk_mil, bulk_designator, bulk_value = reservoir[0]
            reservoir_column = (
                f"**{bulk_designator}** {bulk_value} @ {bulk_mil:.1f} mil"
            )
        else:
            reservoir_column = (
                f"**none** — the pool holds no capacitor at or above "
                f"{HF_CEILING_FARADS * 1e6:g} µF that this document places"
            )

        message = (
            f"{mcu.designator} supply group {net!r} — {len(pins)} pin(s) "
            f"({pin_text}); nearest 高频旁路 (< "
            f"{HF_CEILING_FARADS * 1e6:g} µF): {bypass_column}; nearest 储能池 "
            f"(>= {HF_CEILING_FARADS * 1e6:g} µF): {reservoir_column} — "
            "measurements only, no supply-bypass distance threshold is in force "
            "yet, and 岳 has ruled on none"
        )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(
                component_ref=mcu.designator,
                pin_refs=[p.number for p in pins],
                net_refs=[net],
                counterpart_ref=bypass_target or None,
                measurement=_measurement("distance", bypass[0][0])
                if bypass
                else None,
            ),
        )

    def _one_vcap(
        self,
        mcu: McuSupply,
        board: object,
        net: str,
        number: str,
        name: str,
        library,
    ) -> Finding:
        """One internal-regulator (``VCAP``) pin's row — named, not grouped.

        The datasheet asks for a capacitor here and the net carries one; what
        131e adds is that the pin is **not** a supply pin
        (``pin_role('VCAP')`` is ``None``), so it is neither a group member nor a
        bypass requirement. The row states the net, the pin, and every capacitor
        on that net with its declared value, because 「a capacitor is there」 and
        「a capacitor of the value the datasheet names is there」 are different
        statements and only the second one is a judgement — which this rule
        deliberately does not make, having no spec to check against.
        """
        model = mcu.board_model
        net_obj = (getattr(model, "nets", {}) or {}).get(net)
        members = sorted(
            {str(owner) for owner, _pin in (getattr(net_obj, "pins", None) or [])}
        )
        capacitors: list[str] = []
        for designator in members:
            if designator == mcu.designator:
                continue
            component = (getattr(model, "components", {}) or {}).get(designator)
            if component is None:
                continue
            if not looks_like_capacitor(
                component.designator,
                component.value or "",
                component.mpn or "",
                component.lcsc_part or "",
                library,
                footprint=component.footprint or "",
            ):
                continue
            declared = str(getattr(component, "value", "") or "")
            farads = parse_capacitance_farads(declared) if declared else None
            distance = component_distance(board, designator, mcu.designator)
            placement = (
                "not placed by this PCB document" if distance is None
                else f"{_mil(distance.edge_distance):.1f} mil edge-to-edge"
            )
            capacitors.append(
                f"{designator} value {declared or '(nobody wrote one down)'}"
                + ("" if farads is not None else " — **unreadable**, UNKNOWN")
                + f" ({placement})"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{mcu.designator} pin {number} {name!r} sits on net {net!r}, "
                "which is an internal-regulator output and **not** a supply "
                "group — pin_role answers None for this name, and the "
                "datasheet's capacitor on it is a part of the regulator, not a "
                "bypass this MCU's supply is judged by; the net carries: "
                + ("; ".join(capacitors) if capacitors else "**no capacitor at all**")
            ),
            evidence=[
                *self._identity(mcu),
                f"VCAP pins are listed by name (a substring test on "
                f"{VCAP_NAME_MARKER!r}) and excluded from "
                f"{sorted(SUPPLY_ROLES)} on purpose — measured on 毕设FOC "
                f"1.0.0: pins 48 and 73 read as pin_role -> None, so folding "
                f"them into a group would have created two supply groups out "
                f"of nodes that already are capacitors",
                f"net {net!r} members: {', '.join(members) or '(none)'}",
                f"capacitors found on {net!r}: "
                + ("; ".join(capacitors) if capacitors else "(none)"),
            ],
            target=FindingTarget(
                component_ref=mcu.designator,
                pin_refs=[number],
                net_refs=[net],
            ),
        )