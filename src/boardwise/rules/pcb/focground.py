"""FOC ground-system rules — task 133c (R1 / R1b / R5).

133a landed ``return_path_projection``, 133b landed the five quick wins; 133c is
the batch that reads the **ground system** of a power-driver board: whether the
power ground and the logic ground are physically separated, how they are joined
if they are, and what the return path under the gate / switching / sense nets
looks like. Three rules, one file, all ``INFO`` — 岳 has ruled on no threshold in
this pack, so every row is a measurement.

* :class:`FocGroundDomains` (``pcb-foc-ground-domains``, **R1**) — split the
  board's ground-class nets into a **power domain** (``PGND`` and family) and a
  **logic/analog domain** (``GND`` / ``AGND`` / ``DGND`` and family), pair every
  power net against every logic net, and report for each pair whether their
  copper **meets on a shared layer** (which is a direct copper connection) and
  what each side's ``pour_connectivity`` island count is.
* :class:`FocGroundTie` (``pcb-foc-ground-tie``, **R1b**) — 岳's 2026-10-08
  ruling on the single-point tie: if the two domains are connected at all, the
  connection should be **exactly one 0 Ω resistor**, and that resistor should sit
  near the power-stage bulk electrolytic. Four outcomes, all reported:
  **one 0R** (with its distance to the nearest bulk cap), **several / non-zero /
  directly-copper-connected** (an account of what is actually there), **not
  connected at all** (an INFO row — 岳: 「要么不连，要么单点」 both count), and
  **a 0 Ω part that sits inside one domain** (a jumper, not the tie).
* :class:`FocReturnPath` (``pcb-foc-return-path``, **R5**) — the return-path
  projection of every gate / switching-node / sense net onto its adjacent
  reference layer, summarised per net, with **PLANE-layer semantics**: a
  reference layer whose ``layer_type == "PLANE"`` is read as
  *constructively fully covered* (岳's ruling — a plane's splitting lives in the
  board outline and the negative-plane setup, neither of which is in this
  model), while a ``SIGNAL``-type reference layer goes through the POUR data.

**Why PLANE is constructive coverage, and where that reading comes from.** 岳's
ruling for this batch, and it is the load-bearing one: on 毕设FOC 1.0.0's PCB1 the
inner layers 15 and 16 are ``PLANE`` by ``layerType``, and **neither carries a
single pour polygon** — 131f's reader only ingests ``fill`` / ``poly`` / ``pour``
kinds, and a plane's copper is expressed by the layer's *type* rather than by a
pour region. Read literally, every power net on that board would report
``none`` on every layer — which is a statement about the *model*, not about the
board: the copper is there, the model just does not carry a polygon for it.
So :func:`return_path_cover` maps a ``PLANE`` reference layer to
``covered-by-construction`` and says so in the evidence, rather than reporting a
gap the drawing does not have. A ``SIGNAL`` reference layer with no pour under
the footprint still reports ``none`` — that one *is* a gap in the data.

**The ground-domain word list, and that it is a name test.** A net has no shelf
category and no pin role that says 「this is the power ground」, so the domain is
decided by the net **name** — the same fragile step 133b's power-net sieve is,
and the same reason :data:`GROUND_DOMAIN_POWER_PREFIXES` and
:data:`GROUND_DOMAIN_LOGIC_PREFIXES` are exported rather than hidden. Every row
states **which net was placed in which domain and by which prefix**, so the
classification is auditable rather than silent: a net matching neither family
is not ground-class in the first place and never reaches these rules, and the
R1b row says so when a board has no power domain at all.

**The direct-connection test is a shared-layer overlap, not a plan-view
intersection.** 127a's root cause made this concrete on this very board: six
0.0 mil 「贴脸」 pairs on 毕设FOC were all top-side parts × bottom-side parts,
whose pads the parser used to place on the same layer. 127b fixed pad copper to
follow the component's own face, so :func:`boardwise.core.measure.net_clearance`'s
``overlapping`` flag now means a genuine planar short. The rule reads
``overlapping and shared_layer_ids`` — a cross-layer pair whose plan-view
footprints intersect is ordinary routing on a four-layer board, not a short, and
127b's own note on ``ClearanceResult.shared_layer_ids`` says exactly that.

**Zero R is read from the drawing's value field, never from the MPN.**
:func:`boardwise.core.values.parse_resistance_ohms` parses the board grammar
(``0R``, ``0Ω``, ``0R01``, bare ``0``), and a part whose value is unreadable is
**UNKNOWN, not zero** — a resistor the drawing does not describe is not a 0 Ω
tie, and claiming one would invent the very single point 岳's ruling is about.

**A 0 Ω tie must actually bridge the two domains.** The test is structural and
comes from the netlist view (``ctx.pcb_model``): a part is a tie candidate when it
is a **resistor** (designator family ``R``, or a shelf category / value parse
that says resistance), its parsed value is exactly 0 Ω, and **two of its pins
land on nets belonging to different ground domains**. A 0 Ω part whose both pins
sit inside one domain is not a tie at all — it is a jumper — and the row says so
rather than counting it as the single point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry
from ...core.measure import (
    ClearanceResult,
    net_clearance,
    pour_connectivity,
    reference_layer_for,
    return_path_projection,
)
from ...core.model import is_ground_net
from ...core.values import parse_resistance_ohms
from ..facts import default_library_path
from ...core.parts import load_parts
from .base import PcbReviewContext, PcbRule
from .distance import _mil, _measurement
from .foc import (
    POWER_NET_PREFIXES,
    _fallback_gap,
    _motor_drivers,
    _pairing_gap,
    bulk_capacitors_of,
    is_power_net,
    power_mosfets_of,
)

__all__ = [
    "EXPLICIT_ZERO_OHM_SPELLINGS",
    "GROUND_DOMAIN_LOGIC_PREFIXES",
    "GROUND_DOMAIN_POWER_PREFIXES",
    "PLANE_LAYER_TYPE",
    "RESISTOR_DESIGNATOR",
    "GroundDomainSplit",
    "FocGroundDomains",
    "FocGroundTie",
    "FocReturnPath",
    "RESISTOR_CATEGORIES",
    "all_zero_ohm_parts_of",
    "bridging_parts_of",
    "domain_of",
    "return_path_cover",
    "split_ground_domains",
    "zero_ohm_resistors_of",
]


#: The net-name prefixes that put a ground-class net in the **power** domain.
#:
#: **This is a name test and it is the fragile step the module docstring
#: declares.** Measured on the corpus: 毕设FOC 1.0.0's PCB1 carries exactly one
#: power-domain ground (``PGND``), 1.1.0's PCB1 the same, ROBOT and 药箱 carry
#: **none** — so R1/R1b are structurally silent on those two boards and say so
#: with one INFO row rather than filing a finding about a missing domain.
#: ``POWER_GROUND_PREFIXES`` in :mod:`boardwise.core.model` is deliberately
#: narrower (``PGND`` only) and this list widens it to the ``P``-prefix family,
#: which is where a naming convention puts a power ground. A board that spells it
#: ``POWER_GND`` or ``EARTH`` lands in neither family: that is **UNKNOWN** here,
#: not 「logic ground」, and the R1b row reports the unrecognised ground nets by
#: name so the gap is visible.
GROUND_DOMAIN_POWER_PREFIXES: tuple[str, ...] = ("PGND", "P_GND", "POWER_GND", "EARTH")

#: The net-name prefixes that put a ground-class net in the **logic / analog**
#: domain. Everything :func:`boardwise.core.model.is_ground_net` recognises
#: minus the power family — ``GND`` / ``AGND`` / ``DGND`` / ``EGND`` / ``SGND`` /
#: ``VSS``, which is the corpus's own ground vocabulary
#: (:data:`boardwise.core.model.GROUND_NET_PREFIXES`).
GROUND_DOMAIN_LOGIC_PREFIXES: tuple[str, ...] = (
    "GND",
    "AGND",
    "DGND",
    "EGND",
    "SGND",
    "VSS",
)

#: The ``LAYER`` ``layerType`` that makes a reference layer a **plane**.
#:
#: 岳's 2026-10-08 ruling for 133c: a projection onto a plane layer reads as
#: **constructively fully covered** and the evidence says 「plane 层，分割不在
#: 模型内」, because a plane's copper is the layer itself and its splitting lives
#: in the board outline and the negative-plane setup — neither of which this
#: geometry model carries. Measured: 毕设FOC 1.0.0's PCB1 declares layers 15 and
#: 16 as ``PLANE`` and **neither has a single pour polygon**, so without this
#: rule every power net on that board would report a gap that exists only in the
#: model. ROBOT's layer 16 is ``SIGNAL``, which is why the same board's
#: bottom-layer traces still go through the POUR data.
PLANE_LAYER_TYPE = "PLANE"

#: A designator whose letter says 「resistor」 — **half** the 0 Ω tie test, the
#: same two-door shape 133b's :func:`~boardwise.rules.pcb.foc.power_mosfets_of`
#: uses for a power FET.
RESISTOR_DESIGNATOR = re.compile(r"^R\d")

#: The shelf categories that make a part a resistor. Measured on the corpus
#: these are sparse (the shelf classifies far more parts as ``resistor``-family
#: than 133b's ``fet`` family, but a fitted 0603 0 Ω is often catalogue-less),
#: which is exactly why the designator door exists beside it.
RESISTOR_CATEGORIES: frozenset[str] = frozenset(
    {"resistor", "resistors", "chip-resistor", "res", "r"}
)

#: 岳 2026-10-08's tie form. A resistor parses to **exactly** 0 Ω — not 「near
#: zero」 and not 「a small value」. This is the oracle ruling's own figure, and
#: unlike TI's numbers it is a **stated requirement**: 岳 ruled that the single
#: point 「必须经恰好一颗 0R」. The rule still reports every outcome rather than
#: raising on a violation, in keeping with the pack's INFO discipline.
ZERO_OHMS = 0.0


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


def domain_of(net: str) -> str:
    """Which ground domain this net name puts it in: ``power`` / ``logic`` / ``""``.

    ``""`` means the name is not ground-class **for this rule's word list** —
    which is not the same as 「not ground」, and the callers say so rather than
    quietly filing it under the logic side.
    """
    upper = _upper(net)
    if not upper:
        return ""
    if any(upper.startswith(p) for p in GROUND_DOMAIN_POWER_PREFIXES):
        return "power"
    if any(upper.startswith(p) for p in GROUND_DOMAIN_LOGIC_PREFIXES):
        return "logic"
    return ""


@dataclass(frozen=True)
class GroundDomainSplit:
    """One board's ground nets, sorted into the two domains, with the evidence.

    ``power`` / ``logic`` hold net names; ``unclassified`` holds ground-class
    names (by :func:`boardwise.core.model.is_ground_net`) that this rule's word
    list does not place in either domain. ``unclassified`` is **not** an error —
    it is the honest 「this drawing spells its ground something this word list
    does not carry」, and R1b reports it by name.
    """

    power: tuple[str, ...] = ()
    logic: tuple[str, ...] = ()
    unclassified: tuple[str, ...] = ()

    @property
    def has_power(self) -> bool:
        return bool(self.power)


def split_ground_domains(board: BoardGeometry) -> GroundDomainSplit:
    """Split this board's ground-class nets into the power and logic domains.

    The ground-class sieve is :func:`boardwise.core.model.is_ground_net` (the
    corpus's own vocabulary, shared with 133b's R31 and 133a's
    ``_ground_pours_on``), and the two-domain split is
    :func:`domain_of`'s word list above. Both are **name** tests and the rows
    state each net's domain and the prefix that placed it there.
    """
    power: list[str] = []
    logic: list[str] = []
    unclassified: list[str] = []
    for net in sorted(board.net_names()):
        if not is_ground_net(net):
            continue
        side = domain_of(net)
        if side == "power":
            power.append(net)
        elif side == "logic":
            logic.append(net)
        else:
            unclassified.append(net)
    return GroundDomainSplit(
        power=tuple(power), logic=tuple(logic), unclassified=tuple(unclassified)
    )


def _domain_evidence(split: GroundDomainSplit) -> list[str]:
    """The classification evidence every R1/R1b row carries verbatim.

    「域名分类证据写进每条 finding（哪个网被判进哪个域，不许静默）」 — this is
    that list, and no row may be filed without it.
    """
    lines = [
        "ground-domain classification (**net-name test**, the fragile step this "
        "rule declares): ground-class sieve is "
        "core.model.is_ground_net (GND / AGND / DGND / EGND / SGND / PGND / "
        "VSS by prefix), and the two-domain split reads this rule's own word "
        "lists",
        "power domain ("
        + ", ".join(repr(p) for p in GROUND_DOMAIN_POWER_PREFIXES)
        + " family): "
        + (", ".join(f"{n!r}" for n in split.power) or "(none)"),
        "logic/analog domain ("
        + ", ".join(repr(p) for p in GROUND_DOMAIN_LOGIC_PREFIXES)
        + " family): "
        + (", ".join(f"{n!r}" for n in split.logic) or "(none)"),
    ]
    if split.unclassified:
        lines.append(
            "ground-class by is_ground_net but placed in **neither** domain by "
            "this word list (UNKNOWN, not 「logic」): "
            + ", ".join(f"{n!r}" for n in split.unclassified)
        )
    return lines


def _island_summary(board: BoardGeometry, net: str) -> str:
    """``'3 islands (18 pour region(s))'`` — R1's per-domain island reading.

    Read by :func:`boardwise.core.measure.pour_connectivity`, so the count is
    **physical** (131f landed POUR parsing, so the union-find sees the real pour
    regions) rather than a count of pour records, which would count overlapping
    regions as separate islands.
    """
    connectivity = pour_connectivity(board, net)
    return (
        f"{connectivity.island_count} copper island(s) over "
        f"{len(board.pours_for_net(net))} pour region(s), pour area "
        f"{board.net(net).pour_area:.4g} sq mil"
    )


def _shared_layers(board: BoardGeometry, layer_id: int | None) -> str:
    """The layer's own ``layerType``, quoted so a PLANE reading is checkable."""
    if layer_id is None:
        return "(no layer)"
    info = board.layer(layer_id)
    return f"layer {layer_id} = {info!s}" if info is not None else f"layer {layer_id}"


# ---------------------------------------------------------------------------
# R1 — pcb-foc-ground-domains
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainPairReading:
    """One (power net, logic net) pair: does their copper meet, and how near."""

    power: str
    logic: str
    clearance: ClearanceResult | None = None

    @property
    def directly_connected(self) -> bool:
        """Same-layer copper overlap — a direct copper connection.

        ``overlapping`` alone is not enough, and neither is ``distance == 0``:
        127a's root cause on this very board was top-side parts × bottom-side
        parts whose pads the parser once placed on one layer, and a cross-layer
        pair whose plan-view footprints meet is ordinary four-layer routing. So
        the test is ``overlapping and shared_layer_ids``, which is exactly what
        127b's layer-attribution fix makes trustworthy.
        """
        return bool(
            self.clearance is not None
            and self.clearance.overlapping
            and self.clearance.shared_layer_ids
        )


class FocGroundDomains(PcbRule):
    """R1: may the power ground and the logic ground touch in copper at all?

    TI SLVA959B §1.3.1 asks for the power ground and the signal/analog ground to
    be **physically separated** — the mechanism the guideline actually backs is
    the isolation itself plus a star point, and everything about the *form* of
    the join (a 0 Ω resistor, and where it sits) is 岳's 2026-10-08 engineering
    convention, recorded as such in :class:`FocGroundTie`'s ``source``.

    One row per **(power net, logic net)** pair. Each row states:

    1. **the classification evidence** — every ground net, its domain, and the
       prefix family that put it there (:func:`_domain_evidence`);
    2. **whether the two nets' copper meets on a shared layer** — read through
       :func:`boardwise.core.measure.net_clearance`'s ``overlapping`` flag
       combined with ``shared_layer_ids``, the reading 127b made trustworthy;
       when they do meet, the row **names the layers, the two elements, and the
       position** so the contact is findable on the board;
    3. **each side's island count** off :func:`pour_connectivity` — the physical
       island reading 131f made possible, reported per domain so 「PGND is one
       plane and GND is 46 fragments」 is a sentence this row can carry.

    **No verdict.** 「Isolation holds」 is reported as an INFO row and 「the two
    domains touch here」 is reported as an INFO row too: 岳 has ruled that the
    pack measures, and which of the two a given board should be is his call.
    """

    id = "pcb-foc-ground-domains"
    title = "Power ground vs logic ground: do the two domains touch in copper, and how many islands does each side carry?"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §1.3.1（物理隔离；出数不出判定，阈值待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        split = split_ground_domains(board)
        if not split.has_power:
            return [self._no_power_domain(board, split)]
        if not split.logic:
            return [self._no_logic_domain(board, split)]
        readings = [
            DomainPairReading(power=power, logic=logic,
                              clearance=net_clearance(board, power, logic))
            for power in split.power
            for logic in split.logic
        ]
        return [self._one_pair(board, split, reading) for reading in readings]

    def _no_power_domain(self, board: BoardGeometry, split: GroundDomainSplit) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{board.name or 'this PCB document'} carries "
                f"{len(split.logic) + len(split.unclassified)} ground-class "
                "net(s) and **no power-domain ground**: no net name matches "
                + ", ".join(repr(p) for p in GROUND_DOMAIN_POWER_PREFIXES)
                + ". R1 asks whether two ground domains touch in copper, and "
                "with one domain there is nothing to compare — so **no pair is "
                "reported** rather than a pair against a domain that is not "
                "there (「absent, not empty」)"
            ),
            evidence=[
                *_domain_evidence(split),
                "this is the measured state of ROBOT ctrl FOC and 智能药箱: "
                "both carry a single ``GND`` and no power ground at all",
                "a board that spells its power ground ``EARTH_GND`` or similar "
                "outside this word list would land here too — the row names the "
                "logic nets it did find so the gap is visible rather than silent",
            ],
            target=FindingTarget(),
        )

    def _no_logic_domain(self, board: BoardGeometry, split: GroundDomainSplit) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                "this board carries a power-domain ground ("
                + ", ".join(split.power)
                + ") and **no logic/analog-domain ground**, so R1 has no pair to "
                "read and no clearance is claimed"
            ),
            evidence=_domain_evidence(split),
            target=FindingTarget(net_refs=list(split.power)),
        )

    def _one_pair(
        self,
        board: BoardGeometry,
        split: GroundDomainSplit,
        reading: DomainPairReading,
    ) -> Finding:
        result = reading.clearance
        connected = reading.directly_connected
        islands = (
            f"power side {reading.power!r}: {_island_summary(board, reading.power)}; "
            f"logic side {reading.logic!r}: {_island_summary(board, reading.logic)}"
        )
        if result is None:
            verdict = (
                f"the clearance between {reading.power!r} and {reading.logic!r} is "
                "**unmeasurable** rather than zero: net_clearance returns None when "
                "one net carries no measurable shape, or when the pair's only "
                "relationship is a shape sitting inside a foreign pour's outer "
                "outline (the pour's clearance voids are not in this model). "
                "Neither 「they touch」 nor 「they are apart」 is claimed for this pair"
            )
            measurement = None
        elif connected:
            verdict = (
                f"**{reading.power!r} and {reading.logic!r} share copper on "
                f"layer(s) {result.shared_layer_ids}** — {result.element_a} "
                f"({result.element_a}) against {result.element_b}: a direct "
                "copper connection between the two ground domains, measured at "
                f"{_mil(result.distance):.1f} mil"
            )
            measurement = _measurement("distance", result.distance)
        elif result.distance <= 0.0:
            shared = result.shared_layer_ids or "none — a cross-layer pair, " \
                "whose distance is a plan-view projection and not a surface gap"
            verdict = (
                f"{reading.power!r} and {reading.logic!r} read distance "
                f"{result.distance!r} but **not overlapping** on any shared "
                f"layer (shared layers: {shared}). No copper connection is "
                "claimed, and no clearance violation is claimed either"
            )
            measurement = _measurement("distance", result.distance)
        else:
            verdict = (
                f"**no direct copper connection** between {reading.power!r} and "
                f"{reading.logic!r}: nearest copper pair is "
                f"{_mil(result.distance):.1f} mil edge-to-edge "
                f"({result.element_a} ↔ {result.element_b}) on shared "
                f"{_shared_layers(board, (result.shared_layer_ids or [None])[0])}"
                + (
                    f" / {', '.join(str(l) for l in result.shared_layer_ids[1:])}"
                    if len(result.shared_layer_ids) > 1
                    else ""
                )
                + " — the isolation TI §1.3.1 asks for **holds by this "
                "measurement**, stated as a number and not as a verdict"
            )
            measurement = _measurement("distance", result.distance)

        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"ground domain pair {reading.power!r} (power) ↔ "
                f"{reading.logic!r} (logic): " + verdict + " — INFO 出数，"
                "本行不出判定"
            ),
            evidence=[
                *_domain_evidence(split),
                islands,
                f"clearance read by core.measure.net_clearance between "
                f"{reading.power!r} and {reading.logic!r}"
                + (
                    ""
                    if result is None
                    else f": distance {result.distance!r}, overlapping="
                    f"{result.overlapping!r}, shared_layer_ids="
                    f"{result.shared_layer_ids}"
                ),
                "the direct-connection test is ``overlapping and "
                "shared_layer_ids`` — **both**. 127a established on this very "
                "board that its six 0.0 mil 「贴脸」 pairs were all top-side × "
                "bottom-side parts whose pads the parser placed on one layer; "
                "127b fixed pad copper to follow the component's own face, so a "
                "cross-layer pair whose plan-view footprints meet is ordinary "
                "four-layer routing and is **not** read as a short here",
                "island counts read by core.measure.pour_connectivity — 131f "
                "landed POUR parsing, so this is the physical island count over "
                "the real pour regions rather than a count of pour records",
                "TI SLVA959B §1.3.1 backs the physical isolation and the star "
                "point; the *form* of the join (0 Ω, placement) is 岳's "
                "2026-10-08 engineering convention and is R1b's subject, not "
                "this row's",
            ],
            target=FindingTarget(
                net_refs=[reading.power, reading.logic],
                measurement=measurement,
            ),
        )


# ---------------------------------------------------------------------------
# R1b — pcb-foc-ground-tie
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TieReading:
    """One **bridging part** between the two ground domains, and what it is.

    A bridging part is any placed component whose netlist view puts two of its
    pins on nets in **different** ground domains. That is deliberately broader
    than 「a 0 Ω resistor」: 岳's ruling distinguishes *exactly one 0 Ω* (the
    desired single point) from *several connecting parts or a direct copper
    link* (the account of what is actually there), and 毕设FOC 1.0.0's ``R48``
    / ``R49`` (both 10 kΩ, one bridging ``GND``↔``PGND`` and the other
    ``AGND``↔``PGND``) exist to make the second branch reachable. A pool of only
    0 Ω parts would report this board as 「not connected at all」 and silently drop
    the two resistors that do the joining.

    ``ohms`` is ``None`` when the drawing states no readable resistance — the
    part is still a bridging part and is still on the ledger, but it is
    **UNKNOWN** whether it is a 0 Ω, never quietly zero.
    """

    designator: str
    value: str
    ohms: float | None = None
    pin_a: str = ""
    net_a: str = ""
    pin_b: str = ""
    net_b: str = ""
    basis: str = ""

    @property
    def is_zero_ohm(self) -> bool:
        """Exactly 0 Ω — 岳's stated single-point form.

        ``None`` (an unreadable value) is **not** zero: an unstated value is
        UNKNOWN and must not be counted as the single point.
        """
        return self.ohms == ZERO_OHMS and self.ohms is not None


def _looks_like_resistor(designator: str, value: str, model: object, library) -> tuple[bool, str]:
    """Is this part a resistor, and which door said so.

    Two doors, exactly as 133b's :func:`~boardwise.rules.pcb.foc.power_mosfets_of`
    has it: the designator family, and the shelf category. The shelf is thin on
    fitted passives (the corpus's 0 Ω resistors are mostly catalogue-less), so
    requiring the category alone would make R1b blind exactly where it exists to
    look; requiring the designator alone would sweep an ``R``-prefixed part into
    a tie reading. Both together is the narrowest available test.

    **``library=None`` means no shelf**, which is this module's stated contract
    (131b/131d's wording) and is honoured by passing
    :data:`boardwise.core.parts.PartLibrary`'s empty form down rather than
    ``None``: :func:`~boardwise.core.parts.find_facts` dereferences its argument,
    so handing it ``None`` would raise rather than degrade, and a caller who
    took the docstring at its word would crash instead of getting a narrower
    answer.
    """
    from ...core.parts import PartLibrary, find_facts

    component = (getattr(model, "components", {}) or {}).get(designator)
    category = ""
    if component is not None:
        entry = find_facts(
            library if library is not None else PartLibrary(),
            mpn=str(getattr(component, "mpn", "") or ""),
            lcsc=str(getattr(component, "lcsc_part", "") or ""),
        )
        category = (entry.category or "") if entry is not None else ""
    by_designator = bool(RESISTOR_DESIGNATOR.match(designator))
    by_category = category.lower() in RESISTOR_CATEGORIES
    doors = []
    if by_designator:
        doors.append("its designator is an R transistor")
    if by_category:
        doors.append(f"the shelf classifies it {category!r}")
    return (by_designator or by_category), " and ".join(doors) or "(neither door)"


#: The 0 Ω spellings :func:`boardwise.core.values.parse_resistance_ohms`
#: declines, kept here rather than added to ``core`` because 133c's scope is the
#: three rules and not the shared value grammar.
#:
#: Measured, and the gap is specific: ``0R`` — the spelling boards actually use
#: for a zero-ohm link, and one of the two the task book names (「value 解析为
#: 0Ω/0R」) — reads ``None`` from the shared parser, because its leading-``R``
#: branch (``R010`` → 0.01 Ω) claims the leading ``R`` and the remaining ``0``
#: is not a digit run it can read. ``0`` / ``0.0`` / ``0Ω`` / ``0R0`` / ``R0``
#: / ``0 ohm`` all parse correctly, so this is a narrow gap in one spelling, not
#: a general failure.
#:
#: Handling it here rather than in ``core`` keeps the change inside 133c's own
#: module and is stated on the row: a part recognised through
#: :data:`EXPLICIT_ZERO_OHM_SPELLINGS` says so in its evidence, so a reader can
#: see it was read by this rule's fallback and not by the shared grammar.
EXPLICIT_ZERO_OHM_SPELLINGS: frozenset[str] = frozenset(
    {"0R", "0r", "0R0", "0r0", "0.0R", "0.0r", "0ohm", "0Ohm", "0OHM"}
)


def _value_ohms(component: object) -> tuple[str, float | None]:
    """``(value text, ohms)`` for one part, ``ohms`` ``None`` when unreadable.

    Read from the drawing's own value field, never the MPN (133b's discipline).
    ``None`` is **UNKNOWN** and is never rounded to zero.

    One addition over
    :func:`boardwise.core.values.parse_resistance_ohms`: the exact 0 Ω
    spellings that parser declines (:data:`EXPLICIT_ZERO_OHM_SPELLINGS`, ``0R``
    above all) are recognised here, because 「恰好一颗 0R」 is the whole subject
    of 岳's ruling and the spelling its own name uses is one the shared grammar
    would refuse. The list is **exactly zero** — nothing near zero is admitted,
    because 「near zero」 is not a 0 Ω and admitting it would invent single
    points. A part outside the list still goes through the shared parser, so a
    10 kΩ reads 10000 Ω and an unreadable value still reads ``None``.
    """
    value = str(getattr(component, "value", "") or "")
    if not value:
        return value, None
    ohms = parse_resistance_ohms(value)
    if ohms is None and value.strip() in EXPLICIT_ZERO_OHM_SPELLINGS:
        ohms = ZERO_OHMS
    return value, ohms


def all_zero_ohm_parts_of(model: object, library=None) -> list[TieReading]:
    """Every part on this board whose value parses to **exactly 0 Ω**.

    Scanned with **no domain filter**, because two different questions need it:
    R1b wants the ones that bridge the two ground domains (岳's single point),
    and it also wants to say 「this 0 Ω part exists but sits inside one domain,
    so it is not the tie」. One scan serves both, and the domain test lives in
    :func:`bridging_parts_of` where it belongs.

    A part whose value is unreadable is **UNKNOWN** and is not returned: an
    unstated value is not a 0 Ω, and claiming one would invent the very single
    point 岳's ruling is about.
    """
    found: list[TieReading] = []
    for designator in sorted(getattr(model, "components", {}) or {}):
        component = (getattr(model, "components", {}) or {})[designator]
        value, ohms = _value_ohms(component)
        if ohms is None or ohms != ZERO_OHMS:
            continue
        looks, basis = _looks_like_resistor(str(designator), value, model, library)
        pins = sorted(
            getattr(component, "pins", ()) or (),
            key=lambda p: str(getattr(p, "number", "") or ""),
        )
        grounded = [
            pin for pin in pins if domain_of(str(getattr(pin, "net", "") or ""))
        ]
        pin_a = grounded[0] if len(grounded) > 0 else (pins[0] if pins else None)
        pin_b = grounded[1] if len(grounded) > 1 else (pins[1] if len(pins) > 1 else None)
        found.append(
            TieReading(
                designator=str(designator),
                value=value,
                ohms=ohms,
                pin_a=str(getattr(pin_a, "number", "") or "") if pin_a else "",
                net_a=str(getattr(pin_a, "net", "") or "") if pin_a else "",
                pin_b=str(getattr(pin_b, "number", "") or "") if pin_b else "",
                net_b=str(getattr(pin_b, "net", "") or "") if pin_b else "",
                basis=basis if looks else f"its value {value!r} parses to 0 Ω",
            )
        )
    return found


def bridging_parts_of(model: object, library=None) -> list[TieReading]:
    """Every part whose two pins land on nets in **different** ground domains.

    The pool is **structural, not value-based**: a part qualifies when its
    netlist view puts one pin on a power-domain ground net and another on a
    logic/analog-domain ground net. It is deliberately broader than 「a 0 Ω
    resistor」 because 岳's ruling has three branches — exactly one 0 Ω, several
    connecting parts or a direct copper link, or not connected at all — and a
    pool of only 0 Ω parts cannot see the middle one: it would report 毕设FOC
    1.0.0 as 「not connected」 while its ``R48`` (10 kΩ, ``GND``↔``PGND``) and
    ``R49`` (10 kΩ, ``AGND``↔``PGND``) sit there doing the joining.

    The part's resistance is parsed when the drawing wrote one down and is
    ``None`` otherwise; ``None`` means UNKNOWN and is never a reason to drop the
    part, because the part bridges the domains whatever its value is or is not.
    A resistor's resistance is parsed through
    :func:`boardwise.core.values.parse_resistance_ohms`; a non-resistor
    (whatever bridges two grounds) carries ``None`` and says so.

    Read off the netlist view (``ctx.pcb_model``), which is what makes 「two pins
    in two domains」 a statement about the drawing's own connectivity rather than
    a geometric guess.
    """
    found: list[TieReading] = []
    for designator in sorted(getattr(model, "components", {}) or {}):
        component = (getattr(model, "components", {}) or {})[designator]
        pins = sorted(
            getattr(component, "pins", ()) or (),
            key=lambda p: str(getattr(p, "number", "") or ""),
        )
        # The first two pins that resolve to a ground domain, in pin order.
        grounded: list[tuple[object, str, str]] = []
        for pin in pins:
            net = str(getattr(pin, "net", "") or "")
            side = domain_of(net)
            if side:
                grounded.append((pin, net, side))
            if len(grounded) == 2:
                break
        if len(grounded) != 2:
            continue
        (pin_a, net_a, side_a), (pin_b, net_b, side_b) = grounded
        if side_a == side_b:
            continue  # both pins in one domain: not a cross-domain bridge
        value, ohms = _value_ohms(component)
        looks, basis = _looks_like_resistor(str(designator), value, model, library)
        if looks:
            reading = f"recognised as a resistor because {basis}"
        elif ohms is not None:
            reading = (
                f"its stated value {value!r} parses to {ohms:g} Ω through "
                "core.values.parse_resistance_ohms, though its designator is "
                "not an R transistor"
            )
        else:
            reading = (
                f"it is not a resistor by designator or shelf and states no "
                f"readable resistance (value {value or '(unstated)'!r}) — it is "
                "on the ledger as a bridging part with its value UNKNOWN"
            )
        found.append(
            TieReading(
                designator=str(designator),
                value=value,
                ohms=ohms if looks else ohms,
                pin_a=str(getattr(pin_a, "number", "") or ""),
                net_a=net_a,
                pin_b=str(getattr(pin_b, "number", "") or ""),
                net_b=net_b,
                basis=reading,
            )
        )
    return found


def zero_ohm_resistors_of(model: object, library=None) -> list[TieReading]:
    """The subset of :func:`bridging_parts_of` that is a **0 Ω single point**.

    Kept as its own name because it is exactly what 岳's ruling names, and R1b's
    row quotes it. A bridging part whose resistance is unreadable, or parses to
    anything but 0, is **not** in here — UNKNOWN is not zero, and a 10 kΩ part
    is not the single point however convenient it would be to call it one.
    """
    return [part for part in bridging_parts_of(model, library) if part.is_zero_ohm]


class FocGroundTie(PcbRule):
    """R1b: how the two ground domains join — one 0 Ω, or nothing, or copper.

    **This rule's ``source`` is an oracle ruling, not a TI citation**, and the
    distinction is load-bearing: TI SLVA959B backs **physical isolation and the
    star / single-point** arrangement (§1.3.1), but it says nothing about a **0 Ω
    resistor** or where it should sit. 岳's 2026-10-08 ruling
    (「模数地直接分割 + 单颗 0R 单点接地，0R 近功率电解电容」) supplies both, and
    the row says which half came from where.

    Four outcomes, all ``INFO``, and all of them are reportable shapes:

    * **exactly one 0 Ω tie** — reported with the tie's **distance to the
      nearest power-stage bulk electrolytic** (133b's pool: a capacitor at or
      above :data:`~boardwise.rules.pcb.foc.BULK_FARADS`, 100 µF). The number
      is 出数, not a verdict: 岳 has ruled the *convention* (near the bulk cap)
      but no distance threshold, so the rule states the gap and names the
      capacitor it is nearest without grading it.
    * **several ties, a non-zero bridging resistor, or a direct copper
      connection** — reported as the account of what *is* there. This is the case
      a rule that only looked for 0 Ω parts would miss entirely, and it is not
      hypothetical: 毕设FOC 1.0.0 joins its domains with **two 10 kΩ resistors**
      (``R48`` bridging ``GND``↔``PGND``, ``R49`` bridging ``AGND``↔``PGND``)
      and no 0 Ω at all, so a 0 Ω-only pool would have called that board
      「not connected」 and dropped the two parts doing the joining. The bridging
      pool is therefore **structural** (:func:`bridging_parts_of`), not
      value-based.
    * **not connected at all** — one INFO row. 岳: 「要么不连，要么单点」; a board
      that deliberately isolates its two grounds entirely is compliant, so the
      row reports the absence with the same seriousness as a presence, and says
      which.
    * **a 0 Ω part inside one domain** — one INFO row per part: it is on the
      ledger because a 0 Ω part somewhere on a ground net is the shape a reader
      would otherwise look for and not find, and it is explicitly **not**
      counted toward the single point.

    **The structural tie test** is what makes this a *ground-domain* tie rather
    than a jumper: a part's two pins must land in **different** domains. It is
    applied to **every** part, not only to 0 Ω ones — the value decides which
    branch of 岳's ruling a part falls into, and the domains decide whether it is
    a ground tie at all.

    A board with **no power domain** (ROBOT, 药箱) produces one INFO row saying
    so. That is the measured state of the corpus, and it is the same
    「absent, not empty」 discipline 133b applied to R16 and R20.
    """

    id = "pcb-foc-ground-tie"
    title = "Ground-domain tie: is the single point one 0 Ω resistor, and how near is it to the bulk electrolytic?"
    level = "L1-pcb-geometry"
    source = (
        "oracle ruling（岳 2026-10-08）——TI SLVA959B 只背书物理隔离+星点/单点，"
        "0R 形式与位置是用户工程约定（出数不出判定，阈值待岳裁）"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in (131b/131d's contract).

        ``library=None`` degrades to an empty shelf, so a synthetic test injects
        a library rather than monkeypatching
        :func:`boardwise.rules.facts.default_library_path`.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        split = split_ground_domains(board)
        if not split.has_power:
            return [self._no_power_domain(board, split)]
        if not split.logic:
            return [self._no_logic_domain(board, split)]

        bridges, jumpers = self._partition_ties(model, library)
        ties = [part for part in bridges if part.is_zero_ohm]
        # A bridging part whose resistance is **unreadable** is UNKNOWN, and
        # UNKNOWN is neither 「a 0 Ω tie」 nor 「a non-zero resistor」 — it is a
        # third thing, and it is kept apart from both. Folding it into the
        # non-zero bucket would let a part nobody described outvote a real
        # single 0 Ω, which is exactly the invention this rule forbids.
        non_zero = [
            part for part in bridges
            if part.ohms is not None and not part.is_zero_ohm
        ]
        unknown = [part for part in bridges if part.ohms is None]
        copper = self._direct_copper(board, split)

        findings: list[Finding] = []
        if not bridges and not copper:
            # Neither a part nor copper joins the domains: 岳's 「不连」 branch.
            findings.append(self._not_connected(board, model, library, split))
        if len(ties) == 1 and not copper and not non_zero:
            # Exactly one 0 Ω and nothing else joining the domains — 岳's shape.
            # An UNKNOWN bridge does **not** spoil this: it is reported on its
            # own row rather than being allowed to demote a real single point.
            findings.append(self._one_tie(board, model, library, split, ties[0]))
        if ties or non_zero or copper:
            findings.append(
                self._not_single_point(
                    board, split, ties, non_zero, unknown, jumpers, copper
                )
            )
        for part in unknown:
            findings.append(self._unknown_resistance(board, split, part))
        for jumper in jumpers:
            findings.append(self._jumper(board, split, jumper))
        return findings

    def _partition_ties(
        self, model: object, library
    ) -> tuple[list[TieReading], list[TieReading]]:
        """``(cross-domain bridges, same-domain jumpers)``.

        :func:`bridging_parts_of` already enforces the two-domain test, so every
        part it returns bridges the domains. The jumpers are collected separately
        so a 0 Ω part sitting **inside** one domain is still reported (it is a
        real part on a ground net) without being mistaken for the single point.
        """
        bridges = bridging_parts_of(model, library)
        bridged = {part.designator for part in bridges}
        # A 0 Ω part that did **not** make it into the cross-domain pool is a
        # jumper: it sits somewhere on the board but not across the two domains.
        # It is reported so a reader can see the part was considered, but it is
        # never counted toward the single point.
        jumpers = [
            part
            for part in all_zero_ohm_parts_of(model, library)
            if part.designator not in bridged
        ]
        return bridges, jumpers

    def _direct_copper(
        self, board: BoardGeometry, split: GroundDomainSplit
    ) -> list[Finding]:
        """One finding per power↔logic pair whose copper **meets** on a shared layer.

        Copper connection **is** the thing 岳's ruling forbids in favour of a 0 Ω
        tie, so it has to be on the ledger even when a 0 Ω part also exists: a
        board with both has two answers to the same question and the reader needs
        to see both.
        """
        findings: list[Finding] = []
        for power in split.power:
            for logic in split.logic:
                result = net_clearance(board, power, logic)
                reading = DomainPairReading(power=power, logic=logic, clearance=result)
                if not reading.directly_connected:
                    continue
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="INFO",
                        level=self.level,
                        message=(
                            f"**direct copper connection** between ground "
                            f"domains: {power!r} (power) and {logic!r} (logic) "
                            f"share copper on layer(s) "
                            f"{result.shared_layer_ids} — {result.element_a} ↔ "
                            f"{result.element_b}. This is copper, not a part: "
                            "no 0 Ω tie can be the single point on this board "
                            "while two domains also touch directly"
                        ),
                        evidence=[
                            *_domain_evidence(split),
                            f"net_clearance({power!r}, {logic!r}): distance "
                            f"{result.distance!r}, overlapping="
                            f"{result.overlapping!r}, shared_layer_ids="
                            f"{result.shared_layer_ids}, nearest pair "
                            f"{result.element_a} ↔ {result.element_b}",
                            "power side " + _island_summary(board, power)
                            + "; logic side " + _island_summary(board, logic),
                            "岳 2026-10-08's ruling asks for 分割 + 单点; a "
                            "direct copper connection is not a single point "
                            "however it is drawn. The row reports it and grades "
                            "nothing",
                        ],
                        target=FindingTarget(
                            net_refs=[power, logic],
                            measurement=_measurement("distance", result.distance),
                        ),
                    )
                )
        return findings

    def _bulk_capacitors(self, board: BoardGeometry, model: object, library):
        """``[(designator, value, farads)]`` — 133b's pool, read through here too.

        Imported from :mod:`boardwise.rules.pcb.foc` rather than re-implemented,
        so R1b's 「0R 要靠近功率电解」 measures the same parts R20's high-current
        loop does and the two rules cannot disagree about what a bulk
        electrolytic is.
        """
        out = []
        for designator, value, farads in bulk_capacitors_of(model, library):
            if board.component(designator) is not None:
                out.append((designator, value, farads))
        return out

    def _nearest_bulk(
        self, board: BoardGeometry, tie: str, bulks: list[tuple[str, str, float]]
    ) -> tuple[str, float | None, str]:
        """The bulk capacitor nearest this tie, its gap, and how the gap was read.

        Ranking is by :func:`~boardwise.rules.pcb.foc._pairing_gap` — pad to pad
        — because the tie and the capacitor **do not share a net** here (a tie's
        two pins are in two different domains and the bulk capacitor's return pad
        sits in the power one), so ``component_distance`` is not the refused-same-
        net case here but the pad reading is still the tighter measurement and is
        the one 133b already justified. The centre-to-centre fallback covers a
        padless placement, and the row says which reading it used.
        """
        best: tuple[float, str] | None = None
        for designator, _value, _farads in bulks:
            gap = _pairing_gap(board, tie, designator)
            if gap is None:
                gap = _fallback_gap(board, tie, designator)
            if gap is None:
                continue
            if best is None or (gap, designator) < best:
                best = (gap, designator)
        if best is None:
            return "", None, ""
        gap, designator = best
        reading = (
            "pad-to-pad edge-to-edge"
            if _pairing_gap(board, tie, designator) is not None
            else "centre-to-centre (one of the two parts places no pad on this "
            "document)"
        )
        return designator, gap, reading

    def _no_power_domain(self, board: BoardGeometry, split: GroundDomainSplit) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                "no power-domain ground on this board (no net name matches "
                + ", ".join(repr(p) for p in GROUND_DOMAIN_POWER_PREFIXES)
                + "), so there is no power/logic pair to tie and no 0 Ω "
                "single point to look for — **R1b is silent by construction** "
                "here rather than filing a finding about a domain that is not "
                "there. Measured: ROBOT ctrl FOC and 智能药箱 both read this way"
            ),
            evidence=_domain_evidence(split),
            target=FindingTarget(),
        )

    def _no_logic_domain(self, board: BoardGeometry, split: GroundDomainSplit) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                "this board carries a power-domain ground ("
                + ", ".join(split.power)
                + ") and no logic/analog ground, so no tie and no 0 Ω search is "
                "reported"
            ),
            evidence=_domain_evidence(split),
            target=FindingTarget(net_refs=list(split.power)),
        )

    def _not_connected(
        self,
        board: BoardGeometry,
        model: object,
        library,
        split: GroundDomainSplit,
    ) -> Finding:
        bulks = self._bulk_capacitors(board, model, library)
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                "**the two ground domains are not connected at all** — no part "
                "bridges a power-domain net to a logic-domain net, and "
                "core.measure.net_clearance finds no shared-layer copper overlap "
                "between them. 岳 2026-10-08: 「要么不连，要么单点」 — both are "
                "compliant shapes, so this row reports the shape and grades "
                "nothing"
            ),
            evidence=[
                *_domain_evidence(split),
                "the bridging-part pool was searched and holds no part whose "
                "two pins land in different ground domains; the 0 Ω parts "
                "anywhere on this board are "
                + (
                    ", ".join(
                        f"{r.designator} ({r.value!r}, pins "
                        f"{r.net_a!r}/{r.net_b!r})"
                        for r in all_zero_ohm_parts_of(model, library)
                    )
                    or "(none at all)"
                ),
                "bulk electrolytics on this board (the 0 R proximity pool, "
                f"≥ {100} µF per 133b's floor): "
                + (", ".join(f"{d} ({v})" for d, v, _f in bulks) or "(none)"),
                "TI SLVA959B §1.3.1 backs physical isolation; 岳's 2026-10-08 "
                "ruling adds the two acceptable join forms (none, or a single "
                "0 Ω) and this board takes the first. Neither half of the ruling "
                "is graded here",
            ],
            target=FindingTarget(),
        )

    def _one_tie(
        self,
        board: BoardGeometry,
        model: object,
        library,
        split: GroundDomainSplit,
        tie: TieReading,
    ) -> Finding:
        bulks = self._bulk_capacitors(board, model, library)
        nearest, gap, how = self._nearest_bulk(board, tie.designator, bulks)
        others = [r.designator for r in zero_ohm_resistors_of(model, library)]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"**exactly one 0 Ω single point**: {tie.designator} "
                f"(value {tie.value!r}) bridges {tie.net_a!r} "
                f"({domain_of(tie.net_a)} domain) and {tie.net_b!r} "
                f"({domain_of(tie.net_b)} domain) — this is the shape 岳's "
                f"2026-10-08 ruling asks for. Its distance to the nearest "
                f"power-stage bulk electrolytic"
                + (
                    f" is {_mil(gap):.1f} mil ({nearest}, {how})"
                    if gap is not None and nearest
                    else " is **unmeasurable** — no bulk capacitor is placed on "
                    "this document"
                )
                + "; 出数不出判定, no proximity threshold is in force"
            ),
            evidence=[
                *_domain_evidence(split),
                f"tie part {tie.designator}: value {tie.value!r} parses to "
                f"{tie.ohms!r} Ω through core.values.parse_resistance_ohms — "
                "exactly 0, which is 岳's stated figure, not a near-zero guess",
                f"recognised as a resistor because {tie.basis} — the same "
                "two-door test 133b's power_mosfets_of uses (designator family "
                "**and/or** shelf category), because the corpus's fitted 0 Ω "
                "parts are mostly catalogue-less",
                f"pin {tie.pin_a or '(unstated)'} on {tie.net_a!r} "
                f"({domain_of(tie.net_a) or 'not a ground domain'} domain) and "
                f"pin {tie.pin_b or '(unstated)'} on {tie.net_b!r} "
                f"({domain_of(tie.net_b) or 'not a ground domain'} domain) — "
                "the structural test: a 0 Ω part bridging **different** domains "
                "is a tie; one inside a single domain is a jumper and is "
                "reported separately",
                "every 0 Ω part on this board: "
                + (", ".join(others) or "(none)"),
                "bulk electrolytic pool (≥ 100 µF, 133b's floor, read through "
                "foc.bulk_capacitors_of so this rule and R20 cannot disagree): "
                + (", ".join(f"{d} ({v})" for d, v, _f in bulks) or "(none)"),
                f"nearest bulk capacitor to {tie.designator}: "
                + (
                    f"{nearest}, gap {_mil(gap):.1f} mil, measured {how}"
                    if gap is not None and nearest
                    else "none — the pool is empty or unmeasurable, so no "
                    "distance is claimed"
                ),
                "岳's 2026-10-08 convention is 「0R 近功率电解电容」; TI SLVA959B "
                "§1.3.1 backs only the isolation and the star point, and the "
                "0 Ω form and its position are **the user's engineering "
                "convention, not a TI citation**. No threshold is applied to the "
                "measured gap",
            ],
            target=FindingTarget(
                component_ref=tie.designator,
                net_refs=[tie.net_a, tie.net_b],
                measurement=_measurement("distance", gap) if gap is not None else None,
            ),
        )

    def _not_single_point(
        self,
        board: BoardGeometry,
        split: GroundDomainSplit,
        ties: list[TieReading],
        non_zero: list[TieReading],
        unknown: list[TieReading],
        same_domain: list[TieReading],
        copper: list[Finding],
    ) -> Finding:
        ways = len(ties) + len(non_zero) + len(copper)
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"**not a single point**: the two ground domains are joined "
                f"{ways} way(s) — {len(ties)} 0 Ω resistor(s)"
                + (
                    " (" + ", ".join(
                        f"{t.designator} {t.net_a!r}↔{t.net_b!r}" for t in ties
                    ) + ")"
                    if ties
                    else ""
                )
                + (
                    f", {len(non_zero)} resistor(s) of a **non-zero** value"
                    + (
                        " (" + ", ".join(
                            f"{t.designator} {t.value!r} "
                            f"{t.net_a!r}↔{t.net_b!r}"
                            for t in non_zero
                        ) + ")"
                        if non_zero
                        else ""
                    )
                    if non_zero
                    else ""
                )
                + (
                    f", and {len(copper)} direct copper connection(s) (no part "
                    "at all — the domains touch in copper)"
                    if copper and not ties and not non_zero
                    else (
                        f", and {len(copper)} direct copper connection(s) on top "
                        "of the parts above"
                        if copper
                        else ""
                    )
                )
                + ". 岳's 2026-10-08 ruling asks for **exactly one 0 Ω**; this "
                "board answers differently. Reported as the account of what is "
                "there, not graded"
            ),
            evidence=[
                *_domain_evidence(split),
                "cross-domain **0 Ω** ties (the shape the ruling names): "
                + (
                    "; ".join(
                        f"{t.designator} ({t.value!r}) pin {t.pin_a or '?'} on "
                        f"{t.net_a!r} ↔ pin {t.pin_b or '?'} on {t.net_b!r}"
                        for t in ties
                    )
                    or "(none)"
                ),
                "cross-domain resistors of a **non-zero** value (bridging parts, "
                "but not 岳's single point): "
                + (
                    "; ".join(
                        f"{t.designator} ({t.value!r}"
                        + (
                            f" = {t.ohms:g} Ω"
                            if t.ohms is not None
                            else ", resistance UNKNOWN"
                        )
                        + f") pin {t.pin_a or '?'} on {t.net_a!r} "
                        f"(domain {domain_of(t.net_a)}) ↔ pin {t.pin_b or '?'} "
                        f"on {t.net_b!r} (domain {domain_of(t.net_b)})"
                        for t in non_zero
                    )
                    or "(none)"
                ),
                "cross-domain bridging parts whose resistance is "
                "**UNKNOWN** (kept apart from both branches on purpose — an "
                "unstated value is neither a 0 Ω tie nor a non-zero resistor): "
                + (
                    "; ".join(
                        f"{t.designator} (value {t.value or '(unstated)'!r}) "
                        f"pin {t.pin_a or '?'} on {t.net_a!r} "
                        f"(domain {domain_of(t.net_a)}) ↔ pin {t.pin_b or '?'} "
                        f"on {t.net_b!r} (domain {domain_of(t.net_b)})"
                        for t in unknown
                    )
                    or "(none)"
                ),
                "direct copper connections between the two domains: "
                + (
                    "; ".join(
                        f"{p.message.splitlines()[0]}" for p in copper
                    )
                    or "(none)"
                ),
                "0 Ω parts that do **not** bridge the two domains (jumpers, "
                "not counted toward the single point): "
                + (
                    ", ".join(
                        f"{t.designator} ({t.value!r}, {t.net_a!r}/{t.net_b!r})"
                        for t in same_domain
                    )
                    or "(none)"
                ),
                "「恰好一颗 0R」 is 岳's 2026-10-08 wording; TI SLVA959B §1.3.1 "
                "backs only the isolation and the star point. A non-zero "
                "bridging resistor, several ties, or a copper connection is "
                "reported as the account of what is there, and no severity is "
                "raised over it — 岳 has ruled the convention, not that every "
                "board must already follow it",
                "the bridging pool is **structural** (two pins in two domains, "
                "read off the netlist view) rather than value-based, because a "
                "pool of only 0 Ω parts would report 毕设FOC 1.0.0 as 「not "
                "connected at all」 and drop the two 10 kΩ resistors that "
                "actually join its domains",
                "the pool is focground.bridging_parts_of — every part whose two "
                "pins land in different ground domains, whatever its value is",
                "岳's 2026-10-08 ruling is the single point; the 「0R 要靠近功率"
                "电解电容」 half is 出数 (a distance is measured and reported, no "
                "threshold is applied), and TI SLVA959B §1.3.1 backs only the "
                "isolation and the star point",
            ],
            target=FindingTarget(),
        )

    def _unknown_resistance(
        self, board: BoardGeometry, split: GroundDomainSplit, part: TieReading
    ) -> Finding:
        """A bridging part whose value nobody wrote down — reported, never guessed.

        This is the row the 「UNKNOWN is not zero」 discipline actually needs.
        Without it there are only two honest buckets (0 Ω and non-zero) and an
        unstated part has to be forced into one of them — which would either
        invent a single point 岳's ruling does not license, or silently demote a
        real one. So it gets its own line: the part physically bridges the two
        domains (**that** is a statement about the drawing's connectivity and it
        is a fact), and its resistance is not stated (**that** is UNKNOWN), and
        no branch of the ruling is claimed from it either way.
        """
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{part.designator} bridges the two ground domains "
                f"({part.net_a!r} ↔ {part.net_b!r}) but states **no readable "
                f"resistance** (value {part.value or '(unstated)'!r}) — so it is "
                "UNKNOWN whether it is 岳's single 0 Ω point, and this row "
                "claims neither branch. The **bridge itself is a fact** read off "
                "the netlist view; only the value is unknown"
            ),
            evidence=[
                *_domain_evidence(split),
                f"{part.designator}: value {part.value or '(unstated)'!r} — "
                "core.values.parse_resistance_ohms returns None for it, and "
                "**None is UNKNOWN, never zero**: a part nobody described is not "
                "a 0 Ω tie, and calling it one would invent the very single "
                "point 岳's ruling is about",
                f"pin {part.pin_a or '(unstated)'} on {part.net_a!r} (domain "
                f"{domain_of(part.net_a) or 'none'}), pin {part.pin_b or '(unstated)'} "
                f"on {part.net_b!r} (domain {domain_of(part.net_b) or 'none'}) "
                "— the two-domain test, read off the netlist view rather than "
                "inferred from geometry",
                f"why it is not a resistor reading: {part.basis}",
                "an UNKNOWN bridge does **not** demote a real single 0 Ω on the "
                "same board: 「恰好一颗 0R」 is counted over the 0 Ω parts, and "
                "this part is reported beside them rather than against them",
            ],
            target=FindingTarget(
                component_ref=part.designator,
                net_refs=[part.net_a, part.net_b],
            ),
        )

    def _jumper(
        self, board: BoardGeometry, split: GroundDomainSplit, tie: TieReading
    ) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{tie.designator} (value {tie.value!r}) parses to exactly 0 Ω "
                f"but its two pins sit on {tie.net_a!r} and {tie.net_b!r} "
                f"(domains {domain_of(tie.net_a) or 'none'} / "
                f"{domain_of(tie.net_b) or 'none'}) — **not a ground-domain "
                "tie**, so it is not counted toward the single point 岳's "
                "ruling describes. Reported because a 0 Ω part somewhere on a "
                "ground net is the shape a reader would otherwise look for and "
                "not find"
            ),
            evidence=[
                *_domain_evidence(split),
                f"{tie.designator}: value {tie.value!r} = {tie.ohms!r} Ω; pin "
                f"{tie.pin_a or '(unstated)'} on {tie.net_a!r}, pin "
                f"{tie.pin_b or '(unstated)'} on {tie.net_b!r}",
                f"recognised as a resistor because {tie.basis}",
                "the structural tie test requires the two pins to land in "
                "**different** ground domains; this part's pins do not, so no "
                "single point is claimed from it and no distance to the bulk "
                "capacitor is computed",
            ],
            target=FindingTarget(
                component_ref=tie.designator, net_refs=[tie.net_a, tie.net_b]
            ),
        )


# ---------------------------------------------------------------------------
# R5 — pcb-foc-return-path
# ---------------------------------------------------------------------------


def _is_plane_layer(board: BoardGeometry, layer_id: int | None) -> bool:
    """Is this reference layer a ``PLANE``-typed one?

    One predicate, read by **both** :func:`return_path_cover`'s counter and
    :meth:`FocReturnPath._one_net`'s gap list, so the two can never disagree:
    a net the counter calls covered-by-construction is not simultaneously
    reported as carrying gaps. That contradiction was real before this helper
    existed and is the reason it is shared rather than written twice.
    """
    if layer_id is None:
        return False
    info = board.layer(layer_id)
    return info is not None and info.layer_type == PLANE_LAYER_TYPE


def return_path_cover(
    board: BoardGeometry, net: str
) -> tuple[dict[str, int], list[str]]:
    """Project one net onto its reference layers, with **PLANE** semantics.

    Returns ``(counts, notes)``. This is 133a's
    :func:`~boardwise.core.measure.return_path_projection` plus exactly one
    addition, and the addition is 岳's ruling for this batch:

    **A reference layer whose ``layerType`` is ``PLANE`` reads as
    ``covered-by-construction``**, because the plane's copper is the layer
    itself and its splitting lives in the board outline and the negative-plane
    setup — neither of which this geometry model carries. Without it, every
    power net on 毕设FOC 1.0.0 would report ``none`` on every layer, which is a
    statement about the *model* and not about the board: measured, layers 15
    and 16 are ``PLANE`` and neither carries a pour polygon at all.

    Every other reference layer goes through the primitive's own POUR reading,
    unchanged. The ``notes`` list carries one line per reference layer the net
    was read on, so the row can say *why* each count came out the way it did.

    The counted statuses are the primitive's own — ``covered`` / ``partial`` /
    ``none`` / ``no_reference_layer`` — plus ``covered-by-construction`` for the
    plane case. No status is added to and none removed.
    """
    report = return_path_projection(board, net)
    counts: dict[str, int] = {}
    notes: list[str] = []
    for row in report.rows:
        layer_id = row.reference_layer_id
        if row.reference_layer_id is None:
            status = "no_reference_layer"
        elif _is_plane_layer(board, layer_id):
            status = "covered-by-construction"
        else:
            status = row.cover_status
        counts[status] = counts.get(status, 0) + 1
    # One note per (layer the net runs on → reference layer) actually seen.
    seen: set[tuple[int | None, int | None]] = set()
    for row in report.rows:
        key = (row.layer_id, row.reference_layer_id)
        if key in seen:
            continue
        seen.add(key)
        if row.reference_layer_id is None:
            notes.append(
                f"traces on layer {row.layer_id} have **no adjacent reference "
                "layer** in the physical stackup, so nothing could be projected "
                "onto them — a statement about the stackup, not about the copper"
            )
            continue
        info = board.layer(row.reference_layer_id)
        if info is not None and info.layer_type == PLANE_LAYER_TYPE:
            notes.append(
                f"traces on layer {row.layer_id} project onto layer "
                f"{row.reference_layer_id} = {info!s} — a **PLANE** layer, read "
                "as 构造性完整覆盖 (covered-by-construction): a plane's splitting "
                "lives in the board outline and the negative-plane setup, neither "
                "of which is in this model, so no gap is claimed for it"
            )
        else:
            notes.append(
                f"traces on layer {row.layer_id} project onto layer "
                f"{row.reference_layer_id} = {info!s} — a "
                f"{info.layer_type if info else '?'} layer, so the reading goes "
                "through the POUR data (131f's region_copper inventory)"
            )
    return counts, notes


class FocReturnPath(PcbRule):
    """R5: the return-path reference under every gate / switch / sense net.

    岳 2026-10-08 ruling ③: on a multi-layer board the return path is analysed by
    **projection** — a signal trace's return current flows under it, so the
    adjacent reference layer's copper is what makes the trace's own reference
    real. This rule runs :func:`return_path_projection` (133a) over every net
    the power-path name sieve recognises and reports, **per net**, the covered /
    partial / none counts plus where the gaps are.

    **The net set is a name test and it is declared fragile here.** It is the
    same sieve 133b's R11 and R13 read (:func:`is_power_net`,
    :data:`~boardwise.rules.pcb.foc.POWER_NET_PREFIXES`), and 133b already
    measured its cost on the corpus: ROBOT's driver connects its six gate pins
    to ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3``, which match no power-path
    prefix. A net the sieve cannot place is **not** a 「signal net」 here, it is
    UNKNOWN, and it lands in the **未识别清单** — an explicit list of the nets
    that carry tracks and sit on a power-stage part but whose names the sieve
    does not recognise. That list is the point of the row: it is where the
    ROBOT ``TIM1_CH*`` gate nets become visible without the rule pretending to
    know what they are.

    **PLANE layers read as constructive coverage** (岳's ruling for this batch,
    and the reason the 1.0.0 numbers look the way they do): see
    :func:`return_path_cover`. Measured on 毕设FOC 1.0.0's PCB1, whose layers 15
    and 16 are both ``PLANE`` with no pour polygon on either — every power-path
    net reads covered-by-construction on both of its copper layers. On ROBOT, whose
    layer 16 is ``SIGNAL``, the bottom-layer traces go through the POUR data and
    read ``none``.

    **A board with no power-path net at all** (llc, 药箱) produces **no row**
    rather than a row about every net it has — 「absent, not empty」, and a rule
    that filed a finding for each missing thing would bury the FOC boards under
    everything else's absence. The 未识别清单 still appears when the board has a
    power stage but no recognisable name.
    """

    id = "pcb-foc-return-path"
    title = "Gate / switching / sense nets: the reference layer's copper under each trace"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §1.2 / §1.3.1 + 岳裁定③（投影分析；出数不出判定）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass, with the shelf handed in (131b/131d's contract).

        The shelf is needed for the **未识别清单** only: naming the power-stage
        parts (a motor driver, a power FET, a bulk electrolytic) is what lets
        the rule list the nets that sit on one of them without a recognisable
        name. ``library=None`` degrades to an empty shelf and the list falls back
        to designator-family tests, which is the same degradation 133b's rules
        accept.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None:
            return []
        recognised = [
            name
            for name in board.net_names()
            if is_power_net(name) and board.tracks_for_net(name)
        ]
        if not recognised:
            unrecognised = self._unrecognised(board, model, library)
            if not unrecognised:
                return []
            return [self._unrecognised_row(board, unrecognised)]
        findings = [
            self._one_net(board, net) for net in sorted(recognised)
        ]
        unrecognised = self._unrecognised(board, model, library)
        if unrecognised:
            findings.append(self._unrecognised_row(board, unrecognised))
        return findings

    def _power_parts(self, board: BoardGeometry, model: object, library) -> set[str]:
        """Every designator that identifies a **power-stage part** on this board.

        Three doors, each already used by 133b: a shelf ``ic.motor-driver``
        (:func:`~boardwise.rules.pcb.foc._motor_drivers`), a power FET
        (:func:`~boardwise.rules.pcb.foc.power_mosfets_of`), and a bulk
        electrolytic (:func:`~boardwise.rules.pcb.foc.bulk_capacitors_of`). A net
        that sits on one of these and carries tracks but whose **name** the
        power-path sieve does not recognise is exactly the 未识别 case — it is on
        the power stage by placement, and UNKNOWN by name.
        """
        parts: set[str] = set()
        for designator, _component, _category in _motor_drivers(model, library):
            if board.component(designator) is not None:
                parts.add(designator)
        for designator, _category, _basis in power_mosfets_of(board, model, library):
            if board.component(designator) is not None:
                parts.add(designator)
        for designator, _value, _farads in bulk_capacitors_of(model, library):
            if board.component(designator) is not None:
                parts.add(designator)
        return parts

    def _unrecognised(
        self, board: BoardGeometry, model: object, library
    ) -> list[tuple[str, list[str]]]:
        """``[(net, power-stage designators on it)]`` for names the sieve misses.

        Sorted by net so a report is diffable between runs, and each entry names
        **which** power-stage parts put the net on the power stage — so a reader
        can judge the claim rather than take it on trust.
        """
        if model is None:
            return []
        parts = self._power_parts(board, model, library)
        if not parts:
            return []
        rows: list[tuple[str, list[str]]] = []
        for net in board.net_names():
            if is_power_net(net) or not board.tracks_for_net(net):
                continue
            # A **ground** net is excluded on purpose: R1 already has its own
            # word list for what a ground net is called, and a return net sitting
            # on a bulk capacitor is not 「an unrecognised power-path signal」 —
            # it is a ground net, and listing it here would bury the case this
            # list exists for (ROBOT's ``TIM1_CH*`` gate nets) under every
            # return trace on the board.
            if is_ground_net(net):
                continue
            on_net = sorted(parts & set(board.net(net).components))
            if on_net:
                rows.append((net, on_net))
        return rows

    def _unrecognised_row(
        self, board: BoardGeometry, unrecognised: list[tuple[str, list[str]]]
    ) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"**未识别清单**: {len(unrecognised)} net(s) that carry tracks "
                "and sit on a power-stage part but whose **name** this rule's "
                "power-path sieve does not recognise. They are UNKNOWN here, not "
                "「signal nets」 — no projection is claimed for them, and listing "
                "them is how the gap becomes visible instead of silent. Measured "
                "instance: ROBOT ctrl FOC's gate nets are ``TIM1_CH1`` / "
                "``TIM1_CH2`` / ``TIM1_CH3`` (MCU timer channels driving "
                "``DRV1``'s gate pins), which no power-path prefix matches"
            ),
            evidence=[
                "sieve: "
                f"{_upper('GH|GL')} + optional phase letter + optional digits "
                "for gates, plus the "
                + ", ".join(repr(p) for p in POWER_NET_PREFIXES)
                + " prefixes (foc.is_power_net) — a **net-name** test, because "
                "no shelf category and no pin role says 「gate」",
                "power-stage parts that put these nets on the power stage: "
                + (
                    ", ".join(
                        f"{net!r} → {', '.join(des)}"
                        for net, des in unrecognised
                    )
                    or "(none)"
                ),
                "ROBOT's ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3`` are the "
                "measured cost of the name test (133b's R11 docstring records "
                "the same finding): asserting that a timer channel *is* a gate "
                "net needs a 岳 ruling this pack does not have, so the nets are "
                "named and left unclassified",
                "no threshold is applied to any of this rule's readings; the "
                "projection counts are measurements",
            ],
            target=FindingTarget(
                net_refs=[net for net, _des in unrecognised]
            ),
        )

    def _one_net(self, board: BoardGeometry, net: str) -> Finding:
        report = return_path_projection(board, net)
        counts, notes = return_path_cover(board, net)
        # The gap list is filtered by the **same** PLANE reading the counts use,
        # and it has to be: `return_path_projection` classifies a plane row from
        # the POUR data, which is empty by construction on a plane layer, so
        # reading its raw `cover_status` here would report 「7 gaps」 for a net
        # whose own evidence line says 「plane 层，分割不在模型内」. A row that
        # contradicts itself one sentence later is worse than no row.
        gaps = [
            row
            for row in report.rows
            if not _is_plane_layer(board, row.reference_layer_id)
            and row.cover_status in ("none", "partial")
        ]
        gap_lines = [
            f"  gap on trace {row.track_id} (layer {row.layer_id} → reference "
            f"{row.reference_layer_id}): {row.cover_status}, corner mask "
            f"{row.corner_cover_mask}, {row.ground_pour_count} ground pour(s) "
            "under the footprint"
            for row in gaps
        ]
        total = sum(counts.values())
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"return-path projection of {net!r}: "
                + (
                    ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                    or "(nothing projected)"
                )
                + f" over {total} trace(s) — "
                + (
                    f"**{len(gaps)} gap(s)** at "
                    + ", ".join(
                        f"{row.track_id} (layer {row.layer_id}→{row.reference_layer_id})"
                        for row in gaps[:3]
                    )
                    + (", …" if len(gaps) > 3 else "")
                    if gaps
                    else "no gap found on any reference layer"
                )
                + "；出数不出判定"
            ),
            evidence=[
                f"net {net!r} matched the power-path name sieve "
                "(foc.is_power_net) — the fragile step, declared in the module "
                "docstring",
                f"read by core.measure.return_path_projection over "
                f"{total} trace segment(s); counts: "
                + (", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "(none)"),
                *notes,
                (
                    "gaps, each with its own trace and layer:  "
                    + "\n".join(gap_lines)
                    if gap_lines
                    else "no segment on any reference layer read as partial or "
                    "uncovered"
                ),
                "PLANE-layer semantics (岳's ruling for this batch): a "
                "reference layer whose ``layerType`` is ``PLANE`` reads as "
                "构造性完整覆盖, because a plane's splitting lives in the board "
                "outline and the negative-plane setup — neither of which this "
                "geometry model carries. Measured: 毕设FOC 1.0.0's PCB1 declares "
                "layers 15 and 16 as PLANE and neither has a pour polygon, so "
                "without this reading every power net would report a gap that "
                "exists only in the model",
                "TI SLVA959B §1.2 / §1.3.1 back the continuous reference plane; "
                "岳裁定③ asks for the projection analysis. Nothing here is "
                "graded — the counts are measurements and the threshold set in "
                "this pack has not been ruled on",
            ],
            target=FindingTarget(net_refs=[net]),
        )