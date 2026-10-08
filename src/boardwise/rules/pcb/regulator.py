"""Regulator input/output capacitor **placement**, read pin-role-wise (task 131b).

``pcb-decap-distance`` (126b) asks one question per **IC** and per **supply
net**: is a high-frequency capacitor near the chip? This module asks a
narrower and, for the power path, a more useful question — for every
**regulator** in the shelf's ``ic.ldo`` / ``ic.buck`` classes, for its
**VIN** pin and for its **VOUT** pin separately, how far is the nearest
capacitor of each pool on *that pin's own net*?

**Pins, not nets.** The two rules' object of study is different, and the
difference is the whole point. 126b pools by net, which is the right question
for 「this chip is fed by ``+5V``, is there a bypass cap anywhere on
``+5V``?」 — and the wrong question for a regulator, because on 毕设FOC 1.0.0 the
net ``+5V`` is simultaneously U5's **input** (U5.1 = ``VIN``), U6's **input**
(U6.1 = ``VIN``) and U11's **output** (U11 is the ``LM5164`` buck whose output
rail is ``+5V``). A net-pooled reading therefore hands U5 the capacitors that
belong to U6's input stage and calls the sum U5's decoupling. This rule reads
:func:`boardwise.core.pinrole.pin_role` on each pin's real name (131a landed
the names on the PCB-side model), keeps the ``IN`` pins as one side and the
``OUT`` pins as the other, and searches **each side's own net**. A pin whose
name declares neither role is recorded as UNKNOWN with the name that said so
— the rule does not promote an unrecognised pin to a side, because a wrong
side produces a finding about a pin the rule never meant.

**Pools are this package's own definition, not 126b's.** 岳裁定 ③ (2026-10-08):
a capacitor below :data:`HF_POOL_FARADS` (1 µF) is a **high-frequency bypass**;
a capacitor at or above it is **energy storage**. This is deliberately *not*
:data:`boardwise.rules.pcb.distance.BULK_FARADS` (10 µF) with the band between
them left unassigned — 裁定 ③ assigns that band to storage, so a ``2.2uF`` part
is storage here where 126b calls it neither pool. A capacitance nobody wrote
down is UNKNOWN and lands in **neither** pool: an unreadable value is not
evidence that a part bypasses anything, which is the same argument
:func:`boardwise.rules.decap.decide_required_cap` makes.

**This stick sets no threshold.** Every row it emits is an ``INFO``
measurement: the nearest capacitor of each pool and its edge-to-edge gap,
with the pad pair that produced the number. There is no ``*_DISTANCE_MIL``
constant here on purpose — the two numbers 126b uses are house rules awaiting
岳's ruling, and inventing a third one silently would make the ledger say a
threshold existed when none does. **The seam is left open**: a future batch
that gets a ruling adds a ``REGULATOR_CAP_DISTANCE_MIL`` constant and turns
the measured rows into WARNs at that line, which is why
:data:`HF_POOL_FARADS` and the pool helper live here rather than inside
:func:`_one_pool`.

**Empty input never raises.** A model with no ``ic.ldo`` / ``ic.buck`` part
produces no findings at all — measured on 毕设FOC's 2026-09-17 export (the
three-document 1.1.0 fixture) and on ``llc_board.epro2``. A pool with no
capacitor, and a side whose pin declares no role, are both single INFO rows
that name the designator, the side and the pool.

**Which model the rule reads: ``ctx.pcb_model``, and why (131c).** The rule is
handed :attr:`~boardwise.rules.pcb.base.PcbReviewContext.pcb_model` — the
netlist view of **the PCB document it is running on**, built per document by
:func:`boardwise.engines.pcbreview.run_pcb_review`. Two facts force that:

* **The two views name nets differently.** 131b's callers passed
  :func:`boardwise.cli._load_model`'s default, the *schematic* view, and that
  is a different set of names for the same wires: on 毕设FOC 1.0.0 U5's output
  is ``$1N66612`` in the PCB view and ``NET11`` in the schematic one, U6's is
  ``$1N66627`` / ``NET3``. A rule asking 「which capacitors sit on U5's output
  net」 has to ask it in the view it measures geometry in, or it measures the
  wrong net and calls the pool empty. The real ``checkup`` reproduced exactly
  that: U5's VOUT storage pool read *empty* (the parts are on ``$1N66612``) and
  its VIN storage nearest read *C93 @ 521.2 mil*, a part that belongs to
  neither reading once the names line up.
* **The PCB view is per document.** :func:`boardwise.parsers.epro2_model.
  build_design_model` with no document argument reads the backup's *first* PCB
  document only. On the 1.1.0 export that is ``PCB3`` (33 components), which
  places none of the three regulators the schematic names — so a first-document
  model is blind to ``PCB1`` (105 components), where all three sit. The
  runner now scopes the model to the document in hand, which is what the
  ``pcb_model`` field exists for; a caller that hands this rule a context with
  ``pcb_model=None`` gets silence, not a wrong answer.

``ctx.model`` — the schematic view — is deliberately **not** read here. The
established PCB rules (``pcb-decap-distance``, the IPC pair) keep it, because
their questions were established over the schematic netlist; this one needs
the geometry's own names.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry
from ...core.measure import component_distance
from ...core.parts import find_facts, load_parts
from ...core.pinrole import pin_role
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .distance import _board_models, _mil, _measurement

__all__ = [
    "HF_POOL_FARADS",
    "POOL_HF",
    "POOL_STORAGE",
    "REGULATOR_CATEGORIES",
    "SIDE_INPUT",
    "SIDE_OUTPUT",
    "RegulatorCapDistance",
    "regulator_role",
]


#: The shelf categories this rule examines. **Only** these two — a
#: ``ic.motor-driver``, a ``ic.reference`` (毕设FOC's ``U20`` = REF2033) and a
#: ``ic.opamp`` are not regulators, and asking a voltage reference for an input
#: capacitor would file a finding against a part that has no input stage.
#:
#: A part the shelf classifies nothing at all is **not** examined. The shelf is
#: the only place a part's *function* is stated (127b's
#: :func:`~boardwise.rules.pcb.distance.classify_device` measures this: 87 of the
#: 109 curated entries carry no category at all), so a category-less part is an
#: UNKNOWN rather than something to guess — guessing here would mean
#: pattern-matching ``LM``/``LDO``/``1117`` out of an MPN, which is the failure
#: mode 131a's ``pin_role`` was written to avoid.
REGULATOR_CATEGORIES: frozenset[str] = frozenset({"ic.ldo", "ic.buck"})

#: The **storage floor** in farads: a capacitor at or above this is energy
#: storage, one below it is a high-frequency bypass.
#:
#: **source: 岳裁定 ③ (2026-10-08)** — the power pack's own definition, not a
#: standard and not 126b's :data:`~boardwise.rules.pcb.distance.BULK_FARADS`.
#: 裁定 ③ is explicit that there is **no unassigned middle band**: ``1uF <= c``
#: is storage whatever its size, because 「储能与高频旁路的分界」 is a property
#: of the *loop* and 1 µF is where the board draws it. The fixture confirms the
#: band is real and populated — ``C89`` (4.7 µF), ``C5``/``C11``/``C101``/
#: ``C64`` (2.2 µF) — so a definition that left it out would silently drop four
#: real capacitors from every pool.
HF_POOL_FARADS = 1e-6

#: Slack for the single boundary comparison, in farads — one picofarad.
#:
#: Not decoration, and the **direction** matters:
#: :func:`boardwise.core.values.parse_capacitance_farads("10uF")` returns
#: ``9.999999999999999e-06``, which is *below* ``10e-06``, so a part declared
#: exactly at the floor can land a hair under it and be filed as HF bypass
#: instead of storage. The comparison is therefore ``farads + eps >= floor``
#: with **no** tolerance on the far side: a capacitor declared at 0.9999 µF is
#: genuinely below the floor and must not be rounded up into the storage pool.
#: 1e-12 F is a picofarad, four orders below the smallest value any real drawing
#: states, and it is the same trick and the same number
#: :func:`boardwise.rules.pcb.distance.capacitor_role` uses (127b).
_BOUNDARY_FARADS = 1e-12

POOL_HF = "hf"
POOL_STORAGE = "storage"

#: The two sides a regulator's pins are read into. The values are the
#: :func:`boardwise.core.pinrole.pin_role` roles, so the label on a finding and
#: the reading that produced it cannot drift apart.
SIDE_INPUT = "IN"
SIDE_OUTPUT = "out"  # the *label* on a report row; the pin role is ``OUT``

_SIDE_LABELS = {SIDE_INPUT: "VIN", SIDE_OUTPUT: "VOUT"}
_POOL_LABELS = {
    POOL_HF: "high-frequency bypass",
    POOL_STORAGE: "energy storage",
}


@dataclass(frozen=True)
class RegulatorReading:
    """One regulator as this rule established it, and why."""

    designator: str = ""
    component: object = None
    #: The board's own model (a multi-board project has one per board), which is
    #: also the model ``cap_candidates_on`` must be asked about.
    board_model: object = None
    #: The shelf category that made it a regulator — quoted in every finding.
    category: str = ""
    #: ``{side: [nets]}`` — the pins whose name declared that side, grouped by
    #: the net each sits on.
    nets_by_side: dict[str, list[str]] = None
    #: ``[pin name]`` for the pins that declared no role. Evidence, never a side.
    unclassified_pin_names: tuple[str, ...] = ()


def regulator_role(candidate: object, model: object) -> str:
    """Which pool one :class:`~boardwise.rules.decap.CapCandidate` is in.

    Read off the **board model's own Component** (``component.value``) through
    :func:`boardwise.core.values.parse_capacitance_farads`, never off a package
    name and never guessed — 裁定 ③ makes the pool a function of the value the
    drawing states. Returns :data:`POOL_HF` below the floor, :data:`POOL_STORAGE`
    at or above it, and ``""`` for a value nobody wrote down (the UNKNOWN case:
    in neither pool, and reported as such rather than silently assigned).
    """
    designator = str(getattr(candidate, "designator", "") or "")
    comp = (getattr(model, "components", {}) or {}).get(designator)
    declared = str(getattr(comp, "value", "") or "") if comp is not None else ""
    farads = parse_capacitance_farads(declared) if declared else None
    if farads is None:
        return ""
    if farads + _BOUNDARY_FARADS >= HF_POOL_FARADS:
        return POOL_STORAGE
    return POOL_HF


def _pool_reason(candidate: object, model: object) -> str:
    """The evidence string for one candidate's pool assignment."""
    designator = str(getattr(candidate, "designator", "") or "")
    comp = (getattr(model, "components", {}) or {}).get(designator)
    declared = str(getattr(comp, "value", "") or "") if comp is not None else ""
    farads = parse_capacitance_farads(declared) if declared else None
    if farads is None:
        return (
            f"candidate {designator}: the schematic states no readable "
            f"capacitance (value {declared!r}) — UNKNOWN, in neither pool"
        )
    if farads + _BOUNDARY_FARADS >= HF_POOL_FARADS:
        return (
            f"candidate {designator}: declared {declared!r} = "
            f"{farads * 1e6:g} µF >= {HF_POOL_FARADS * 1e6:g} µF — "
            f"{_POOL_LABELS[POOL_STORAGE]} pool (岳裁定 ③, the middle band is "
            f"assigned to storage, not left undecided)"
        )
    return (
        f"candidate {designator}: declared {declared!r} = "
        f"{farads * 1e6:g} µF < {HF_POOL_FARADS * 1e6:g} µF — "
        f"{_POOL_LABELS[POOL_HF]} pool"
    )



def _regulator_readings(model: object, library=None) -> list[RegulatorReading]:
    """Every ``ic.ldo`` / ``ic.buck`` part, per board, with its pin roles read.

    The shelf is read once through :func:`boardwise.core.parts.load_parts` /
    :func:`~boardwise.core.parts.find_facts` — the same exact-match lookup
    (#202's lesson: MPN, then C-number, never a prefix match) that
    :func:`boardwise.rules.pcb.distance.device_facts` uses, asked directly so the
    category read here is the one this rule's evidence quotes.

    Sides come from :func:`boardwise.core.pinrole.pin_role` on each pin's
    **name**. A ground pin, an enable pin and an unconnected ``NC`` all resolve
    to a role that is neither ``IN`` nor ``OUT``, which is the correct answer:
    only the two supply pins carry a capacitor-pool question.
    """
    if library is None:
        try:
            library = load_parts(default_library_path())
        except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
            library = None
    readings: list[RegulatorReading] = []
    for _title, board_model in _board_models(model):
        components = getattr(board_model, "components", {}) or {}
        for designator in sorted(components):
            component = components[designator]
            entry = (
                find_facts(
                    library,
                    mpn=str(getattr(component, "mpn", "") or ""),
                    lcsc=str(getattr(component, "lcsc_part", "") or ""),
                )
                if library is not None
                else None
            )
            category = (entry.category or "") if entry is not None else ""
            if category not in REGULATOR_CATEGORIES:
                continue
            nets_by_side: dict[str, list[str]] = {
                SIDE_INPUT: [],
                SIDE_OUTPUT: [],
            }
            unclassified: list[str] = []
            for pin in getattr(component, "pins", ()) or ():
                name = str(getattr(pin, "name", "") or "")
                role = pin_role(name)
                if role == "IN":
                    side = SIDE_INPUT
                elif role == "OUT":
                    side = SIDE_OUTPUT
                else:
                    unclassified.append(name or f"pin {getattr(pin, 'number', '?')!r}")
                    continue
                net = str(getattr(pin, "net", "") or "")
                if net and net not in nets_by_side[side]:
                    nets_by_side[side].append(net)
            readings.append(
                RegulatorReading(
                    designator=str(designator),
                    component=component,
                    board_model=board_model,
                    category=category,
                    nets_by_side=nets_by_side,
                    unclassified_pin_names=tuple(unclassified),
                )
            )
    return readings


class RegulatorCapDistance(PcbRule):
    """Are each regulator's input and output capacitors **next to it**?

    One pass per regulator, per **side** (``VIN`` / ``VOUT``), per **pool**
    (:data:`POOL_HF` / :data:`POOL_STORAGE`), producing one ``INFO`` row each:

    * a pool with a measurable capacitor — the **nearest** one, its edge-to-edge
      distance in mils and the pad pair the number came from;
    * a pool with none — a row that names the designator, the side and the
      pool, and lists every candidate on the net that was excluded and why.

    The pool of candidates is :func:`~boardwise.rules.decap.cap_candidates_on`
    on **that side's own net** — the 127b predicate (a capacitor, bridging this
    net to a *different* ground net), so the two rules cannot disagree about
    what a decoupling candidate is. Splitting them into pools is
    :func:`regulator_role`'s job, and 裁定 ③ owns the boundary.

    **Measured, not judged.** See the module docstring: no threshold, every row
    ``INFO``. A board with no regulator in :data:`REGULATOR_CATEGORIES` produces
    nothing at all — and so does a context with no ``pcb_model`` (the schematic
    view is not a substitute, see the module docstring), or one where this PCB
    document places no part the shelf calls a regulator (``PCB2``/``PCB3`` of
    毕设FOC 1.0.0 carry none, and neither does ``llc_board.epro2``).
    """

    id = "pcb-regulator-cap-distance"
    title = "Regulator input/output capacitors sit next to the regulator pin they serve"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf — the same "shelfless
        reading is a narrower one" contract
        :func:`_regulator_readings` already honours, so the synthetic tests can
        inject a two-entry library without monkeypatching the project's own
        :func:`boardwise.rules.facts.default_library_path` (which
        :func:`~boardwise.rules.pcb.distance._supply_nets` shares).
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for reading in _regulator_readings(model, library):
            if board.component(reading.designator) is None:
                continue  # no geometry on this PCB document: nothing to measure
            for side in (SIDE_INPUT, SIDE_OUTPUT):
                nets = list(reading.nets_by_side.get(side) or [])
                if not nets:
                    findings.append(self._no_side(reading, side))
                    continue
                for net in nets:
                    for pool in (POOL_HF, POOL_STORAGE):
                        findings.extend(
                            self._one_pool(reading, board, side, net, pool, library)
                        )
        return findings

    # -- rows -------------------------------------------------------------

    def _identity(self, reading: RegulatorReading) -> list[str]:
        """The evidence every row of one regulator carries."""
        facts = [
            f"{reading.designator} read as a regulator because the shelf "
            f"category is {reading.category!r}"
        ]
        if reading.unclassified_pin_names:
            facts.append(
                "pins whose names declare no supply role (UNKNOWN, and so not "
                f"on either side): {', '.join(reading.unclassified_pin_names)}"
            )
        return facts

    def _no_side(self, reading: RegulatorReading, side: str) -> Finding:
        """The row for a side no pin declared: 「which side, and there is none」."""
        label = _SIDE_LABELS[side]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{reading.designator} declares no pin whose name reads as "
                f"{label}, so its {label} side has no net to measure and "
                f"neither {label} pool is examined — the pin names this rule "
                f"could not classify are in the evidence"
            ),
            evidence=self._identity(reading),
            target=FindingTarget(component_ref=reading.designator),
        )

    def _one_pool(
        self,
        reading: RegulatorReading,
        board: BoardGeometry,
        side: str,
        net: str,
        pool: str,
        library,
    ) -> list[Finding]:
        """The one row for ``(side, net, pool)`` of one regulator."""
        label = _SIDE_LABELS[side]
        pool_label = _POOL_LABELS[pool]
        candidates = list(cap_candidates_on(reading.board_model, net, library))
        members = [
            c
            for c in candidates
            if regulator_role(c, reading.board_model) == pool
        ]
        excluded = [c for c in candidates if c not in members]
        evidence = [
            *self._identity(reading),
            f"{label} net is {net!r} (read from the pin's name, not from a "
            f"netname pattern)",
            f"candidates bridging {net!r} to a ground net: "
            f"{', '.join(sorted(c.designator for c in candidates)) or '(none)'}",
            *[_pool_reason(c, reading.board_model) for c in sorted(
                candidates, key=lambda c: c.designator
            )],
        ]
        measured: list[tuple[str, object]] = []
        for candidate in members:
            if board.component(candidate.designator) is None:
                continue  # named by the netlist, not carried by this PCB document
            distance = component_distance(
                board, reading.designator, candidate.designator
            )
            if distance is None:
                continue  # padless on this board: unmeasurable, not zero
            measured.append((candidate.designator, distance))
        if not measured:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{reading.designator} has no {pool_label} capacitor "
                        f"measurable against its {label} net {net!r} — the "
                        f"{label} {pool_label} pool is empty on this net"
                        + (
                            " (candidates exist but none is placed on this "
                            "PCB document)"
                            if members
                            else " (no capacitor on the net at all)"
                        )
                    ),
                    evidence=evidence,
                    target=FindingTarget(
                        component_ref=reading.designator, net_refs=[net]
                    ),
                )
            ]
        nearest, distance = min(
            measured, key=lambda pair: pair[1].edge_distance
        )
        excluded_names = ", ".join(sorted(c.designator for c in excluded))
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{reading.designator}'s nearest {pool_label} capacitor on "
                    f"its {label} net {net!r} is {nearest} at "
                    f"{_mil(distance.edge_distance):.1f} mil edge-to-edge "
                    f"(pads {distance.pad_a} / {distance.pad_b}) — measurement "
                    f"only, no pool threshold is in force yet"
                ),
                evidence=evidence
                + [
                    f"nearest: {nearest} @ {net} = "
                    f"{_mil(distance.edge_distance):.1f} mil edge-to-edge",
                    f"measured {pool_label} members: "
                    + ", ".join(
                        f"{name}={_mil(distance_.edge_distance):.1f}"
                        for name, distance_ in sorted(
                            measured, key=lambda pair: pair[1].edge_distance
                        )
                    ),
                    (
                        f"excluded from this pool on {net}: {excluded_names}"
                        if excluded_names
                        else f"no capacitor on {net} is excluded from this pool"
                    ),
                ],
                target=FindingTarget(
                    component_ref=reading.designator,
                    net_refs=[net],
                    counterpart_ref=nearest,
                    measurement=_measurement("distance", distance.edge_distance),
                ),
            )
        ]
