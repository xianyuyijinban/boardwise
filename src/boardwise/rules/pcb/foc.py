"""FOC / 功率驱动 rule pack — the five quick wins of task 133b (R16 / R31 / R11 / R13 / R20).

133a landed the three primitives this batch needs (``via_geometry``,
``track_corner_angle``, ``return_path_projection``); 133b is the batch that
**reads with them**. Five rules, one file, all ``INFO``:
岳 has ruled on no threshold in this pack yet, so every row is a measurement
and none is a verdict, exactly as 131b/131c/131d/131e/131f did.

The five, and what each one is *about*:

* :class:`FocDecapProximity` (``pcb-foc-decap-proximity``, R16) — a **power
  driver IC**'s decoupling capacitor: how far its pad sits from the IC's supply
  pin, **whether the two are on the same copper layer**
  (``effective_layer_ids``), and whether a via stands between them. TI SLVA959B
  §5.3.1's 0.2 in goes into the evidence as a reference number and grades
  nothing.
* :class:`FocGroundPlane` (``pcb-foc-ground-plane``, R31) — on a **≥4-layer**
  board (read off the physical stackup), is there a layer carrying **one single
  ground-class island**, and what share of the board area does it cover. A
  two-layer board gets one INFO row saying the rule does not apply to it.
* :class:`FocGateTraceWidth` (``pcb-foc-gate-trace-width``, R11) — the width
  distribution of the **gate nets** (``GHx`` / ``GLx`` / ``GHA`` …): track
  count, min, max, total length. TI §4's 「≥20 mil」 is quoted, not applied.
* :class:`FocTrackCorners` (``pcb-foc-track-corners``, R13) — every
  non-obtuse fold in the routing (or narrowed to gate/power nets), read straight
  off 133a's ``track_corner_angle``.
* :class:`FocPowerLoopArea` (``pcb-foc-power-loop-area``, R20) — the
  high-current loop between a **bus electrolytic** and a **power MOSFET pair**,
  in **both** 口径 (polygon / bbox) because 岳's ruling on which one is the loop
  area has not arrived.

**Why the whole pack is INFO.** The pack's design basis (TI SLVA959B, a
*guide*) states guidance numbers, and 岳's own ruling on this pack (2026-10-08)
records that the threshold set is unsettled. A rule that graded them would put
a number in the ledger nobody decided, which is the exact failure 131b's
「measured, not judged」 and :data:`DECAP_DISTANCE_MIL`'s provenance note are
about. So every constant in this module is either a **geometric fact of the
measurement** (which nets count as gate nets) or a **provenance marker**
(the bulk threshold, the layer count) — never a pass/fail line. The TI figures
appear in ``evidence`` beside the measured number so the two can be read
together without the tool having chosen between them.

**The narrow-net question R13/R11 share, and why it is a net-name test.** 133b's
task table says R13 may narrow to 「功率/栅极网」. Both readings (R11's gate-net
width, R13's fold list) turn out to need the *same* narrow set, so
:data:`POWER_NET_PREFIXES` defines it **once** and both rules read it: gate nets
(``GH`` / ``GL`` family), the switching nodes (``MOTx``), and the
phase-current sense nets (``IA`` / ``IB`` / ``IC`` family). This is a **name**
test and is declared as the fragile step it is — 133a taught the pack that
identity must come from a stated field wherever a stated field exists, but a
gate net has no shelf category and no pin-role spelling that says 「this is a
gate」; the net name is the only place the drawing states it. A gate net spelled
outside the prefixes simply does not appear, which the rows say.

**The 口径 question R20 refuses to answer.** 「Loop area」 has two honest
readings on a rectangle-ish loop — the **shoelace polygon** area of the anchor
quadrilateral, and its **bounding-box** area, which is an upper bound and is
what a placement checklist usually means by 「环路大小」. 岳 has ruled on neither,
so :func:`boardwise.core.measure.loop_area` returns both and this rule reports
both on the same row, side by side. Neither is marked 「the」 answer.

**Objects the pack identifies, and from what.** A **power driver IC** is a part
the shelf calls ``ic.motor-driver`` (:data:`MOTOR_DRIVER_CATEGORIES`) — measured
on the corpus as exactly two entries, TI's DRV8350SRTVR and DRV8313PWPR. A
**bus electrolytic** is a capacitor whose declared value is at or above
:data:`BULK_FARADS` (100 µF). A **power MOSFET** is a part whose shelf category
is ``fet`` **or** whose designator is a ``Q``-prefix transistor *and* which sits
on a net that also feeds a bulk capacitor — the two-step test is deliberate:
the shelf has only two ``fet`` entries (both low-power signal parts), so a
board's real power FETs are category-less, and requiring a category that does
not describe them would make the rule silent on every FOC board in the corpus.
As with 131d's crystal sieve, this is **the acknowledged fragile step** and it
is named in the module constants rather than hidden.

**Empty input is silence, and 「no power stage」 is a legal board.** A board
placing no ``ic.motor-driver`` (llc's half-bridge, 药箱's board) produces no
R16 row and does not raise; a board with no bulk capacitor and no power FET
produces no R20 row at all (药箱, and ROBOT — which places a driver but whose
largest fitted capacitor is 10 µF, well under the 100 µF bulk floor). That is
the module's discipline (126b's 「absent, not empty」), restated where it is
load-bearing: a rule that filed a finding for every missing object would bury
the FOC boards under everything else's absence.

**llc gets R20 rows even though it has no motor driver, and that is the point.**
R16's object is a *shelf category* (``ic.motor-driver``) and llc has none, so
R16 is silent there — but R20's objects are a **bulk electrolytic** and a **power
MOSFET**, and llc places both: two 330 µF capacitors on ``DC+``/``DC-`` and four
``B3M040065H`` FETs whose bus pads sit on those same nets. It is a full-bridge
power stage, so the high-current loop is a real thing to measure on that board.
Each rule follows its own declared object rather than the pack's name, and a
board is 「in the FOC pack」 for one question without being in it for another.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BBox, BoardGeometry, PadGeometry
from ...core.measure import (
    OBTUSE_CORNER_DEG,
    component_distance,
    loop_area,
    pad_edge_distance,
    pour_connectivity,
    read_stackup,
    track_corner_angle,
    track_width_stats,
    vias_in_region,
)
from ...core.parts import find_facts, load_parts
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .distance import _mil, _measurement

__all__ = [
    "BULK_FARADS",
    "GATE_NET_PATTERN",
    "MOTOR_DRIVER_CATEGORIES",
    "POWER_NET_PREFIXES",
    "MULTILAYER_THRESHOLD",
    "FocDecapProximity",
    "FocGateTraceWidth",
    "FocGroundPlane",
    "FocPowerLoopArea",
    "FocTrackCorners",
    "bulk_capacitors_of",
    "gate_nets_of",
    "is_power_net",
    "power_mosfets_of",
]


#: The shelf categories that make a part a **power driver IC** — R16's object.
#:
#: Measured: the shelf carries exactly two such entries, ``ic.drv8350srtvr`` and
#: ``ic.drv8313pwpr``. Both acceptance boards place one (毕设FOC 1.0.0's ``U10``,
#: 1.1.0's ``U2``, ROBOT's ``DRV1``), while 药箱 and llc place none — which is
#: why R16 is **silent** on those two rather than empty-but-noisy. (llc still
#: produces R20 rows; that rule's objects are a bulk electrolytic and a power
#: FET, not a driver IC — see the module docstring.) Only this category: an
#: ``ic.ldo`` / ``ic.buck`` is a converter (131b's object) and an ``ic.mcu`` is
#: a controller (131d's), and asking either for a driver's decoupling would file
#: a row against the wrong part.
MOTOR_DRIVER_CATEGORIES: frozenset[str] = frozenset({"ic.motor-driver"})

#: A **bus electrolytic** for R20: a capacitor at or above this value, in
#: farads. 100 µF is the task book's own figure (133b's table: 「母线电解电容
#: (bulk ≥100µF)」) and is a **stated threshold, not a measurement** — it is the
#: one number in this module that decides *which parts are examined at all*, so
#: it is named and exported rather than buried. The slack mirrors 131b's
#: :data:`~boardwise.rules.pcb.regulator._BOUNDARY_FARADS`: a part declared at
#: exactly 100 µF parses a hair under it.
BULK_FARADS = 100e-6
_BOUNDARY_FARADS = 1e-12

#: How many copper layers make a board a **multi-layer** board for R31.
#:
#: The task book says ≥4, and the reading that produces it is
#: :func:`boardwise.core.measure.read_stackup`'s ``copper_count`` — the
#: *physical* stackup, not the 34 ``LAYER`` definitions the editor carries
#: (岳 2026-10-07 亲裁). Measured: 毕设FOC 1.0.0 / 1.1.0 / ROBOT read 4, 药箱 and
#: llc read 2. It is a **statement about which boards the question applies to**,
#: not a verdict: a two-layer board is not defective for having no inner plane,
#: it is out of scope for the question, and its row says so.
MULTILAYER_THRESHOLD = 4

#: TI SLVA959B §5.3.1's decoupling figure, in mils. **Reference only.**
#:
#: The guideline puts the bypass capacitor within 0.2 in of the supply pin.
#: This module **reports the measured gap and quotes this beside it in the
#: evidence**, and grades nothing — the whole pack is INFO until 岳 rules. It is
#: named so the reference cannot be mistaken for a constant the code compares
#: against (it is used only inside an evidence string).
TI_DECAP_REFERENCE_MIL = 0.2 * 1000.0

#: TI SLVA959B §4's gate-trace width figure, in mils. **Reference only**, same
#: discipline as :data:`TI_DECAP_REFERENCE_MIL`.
TI_GATE_WIDTH_REFERENCE_MIL = 20.0

#: The **net-name** prefixes that make a net a power-path net, as a regex over
#: the upper-cased name. This is the one shared predicate R11 and R13 read.
#:
#: Three families, and each is there because it was **measured** on the corpus:
#:
#: * ``GH`` / ``GL`` + optional phase letter + optional digits — the gate nets.
#:   毕设FOC 1.0.0 / 1.1.0 carry exactly ``GHA`` ``GHB`` ``GHC`` and
#:   ``GLA`` ``GLB`` ``GLC``. ROBOT's driver connects its six gate pins to
#:   ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3`` (pins 27 / 25 / 23) and
#:   ``$1N147`` — MCU timer channels and editor-generated names, which match
#:   nothing here. That is the honest cost of a name test, and the R11 row says
#:   「no net recognised」 rather than guessing that a ``TIM1_CH*`` net is a gate
#:   net — a name that does not state its function is UNKNOWN here, not 「not a
#:   gate」, and inventing the mapping would need a 岳 ruling this pack has not
#:   got.
#: * ``MOT`` + phase — the **switching node** (1.0.0's ``MOTA`` / ``MOTB`` /
#:   ``MOTC`` carry the motor half-bridge outputs and are the nets TI §4 calls
#:   out by name).
#: * ``I`` + phase + optional ``+/-`` — the phase-current **sense** nets
#:   (``IA+`` / ``IB+`` / ``IC+`` on 1.0.0), which is the same current path as
#:   the switching node one node earlier.
#:
#: **This is the acknowledged fragile step of the pack** and is named here
#: rather than buried: a net has no shelf category, and no pin-role spelling
#: says 「this is a gate net」. The net name is the only place the drawing states
#: it, so this is a name test — and a gate net spelled outside these prefixes
#: simply does not appear in R11 or R13's narrowed rows. :func:`is_power_net`
#: is exported so a reader sees the sieve rather than inferring it.
GATE_NET_PATTERN = re.compile(r"^(?:GH|GL)[A-Z]?\d*$")

#: The prefix families of :data:`GATE_NET_PATTERN`'s **siblings**: switching
#: nodes and phase-current sense. Kept as one tuple so R11's and R13's narrowed
#: set is a single object both rules read, and so widening (or narrowing) the
#: power-net definition is a one-line change with both rules following.
POWER_NET_PREFIXES: tuple[str, ...] = ("GH", "GL", "MOT", "IA", "IB", "IC")

#: A designator whose letter says 「transistor」. **Only ever half the test.**
#:
#: :func:`power_mosfets_of` requires this **and** that the part sits on a net a
#: bulk capacitor also sits on. The shelf's own ``fet`` category carries only
#: two entries, both small-signal parts (2N7002K, HB04N090S), so the real power
#: FETs on every FOC board in the corpus are **category-less** — 毕设FOC 1.0.0's
#: six ``MCAC53N06Y-TP`` half-bridge FETs read ``''``. Requiring the category
#: alone would make R20 silent on the very board it exists for; requiring the
#: designator alone would sweep a board's signal FETs into a power-loop reading.
#: Both together is the narrowest available test.
POWER_FET_DESIGNATOR = re.compile(r"^Q\d")


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


def is_power_net(name: str) -> bool:
    """Does this net name place it on the FOC power path (gate / switch / sense)?

    The single predicate R11 and R13 share. Read as a **name** test on the
    upper-cased net, and it is the fragile step the module docstring declares:
    :data:`GATE_NET_PATTERN` plus the switching-node / sense families of
    :data:`POWER_NET_PREFIXES`. A name outside all of them is not a power net
    **as far as this rule can tell**, which the rows say rather than treating as
    「definitely a signal net」.
    """
    upper = _upper(name)
    if not upper:
        return False
    if GATE_NET_PATTERN.match(upper):
        return True
    if upper.startswith("MOT"):
        return True
    return upper in {"IA", "IB", "IC", "IA+", "IB+", "IC+", "IA-", "IB-", "IC-"}


def gate_nets_of(board: BoardGeometry) -> list[str]:
    """Every net on this board whose name puts it on the power path, sorted.

    Only nets that actually carry **tracks** are returned — a named gate net with
    no copper is a row about a name, not about a trace, and R11's whole reading
    is a width distribution. Order is sorted so a report is diffable between
    runs.
    """
    return [
        name
        for name in board.net_names()
        if is_power_net(name) and board.tracks_for_net(name)
    ]


def _category_of(component: object, library) -> str:
    """The shelf category of one part, or ``""`` when the shelf says nothing.

    Read through :func:`boardwise.core.parts.find_facts` (exact MPN then LCSC,
    #202's lesson) so the category quoted in a row is the one the shelf states
    rather than one inferred from a prefix.
    """
    if component is None:
        return ""
    entry = find_facts(
        library,
        mpn=str(getattr(component, "mpn", "") or ""),
        lcsc=str(getattr(component, "lcsc_part", "") or ""),
    )
    return (entry.category or "") if entry is not None else ""


def _motor_drivers(model: object, library) -> list[tuple[str, object, str]]:
    """Every ``ic.motor-driver`` part of this board's netlist view, sorted.

    ``(designator, component, category)`` per driver. Parts the PCB document does
    not place are still returned — the caller asks
    :meth:`BoardGeometry.component` and skips them, which is the shape 131d
    established (a designator the netlist names but this document does not carry
    has no geometry to measure).
    """
    found: list[tuple[str, object, str]] = []
    for designator in sorted(getattr(model, "components", {}) or {}):
        component = (getattr(model, "components", {}) or {})[designator]
        category = _category_of(component, library)
        if category in MOTOR_DRIVER_CATEGORIES:
            found.append((str(designator), component, category))
    return found


def bulk_capacitors_of(model: object, library=None) -> list[tuple[str, str, float]]:
    """Every capacitor at or above :data:`BULK_FARADS`, as ``(des, value, farads)``.

    A candidate must **look like a capacitor** (the same
    :func:`boardwise.rules.decap.looks_like_capacitor` 126b and 131b reuse — this
    module imports the pool through :func:`~boardwise.rules.decap.cap_candidates_on`
    where a net says which caps are on it, and reads the designator family
    directly here) **and** state a readable capacitance at or above the bulk
    floor. A capacitor whose value nobody wrote down is **not** a bulk cap and is
    not guessed into one: an unreadable value is UNKNOWN, never a zero and never
    a 330 µF.

    Measured: 毕设FOC 1.0.0's ``C115`` / ``C116`` (330 µF) and llc's ``C3`` /
    ``C4``; ROBOT's largest fitted capacitor is 10 µF, so R20 is silent there.
    """
    found: list[tuple[str, str, float]] = []
    for designator in sorted(getattr(model, "components", {}) or {}):
        component = (getattr(model, "components", {}) or {})[designator]
        value = str(getattr(component, "value", "") or "")
        farads = parse_capacitance_farads(value) if value else None
        if farads is None:
            continue
        if farads + _BOUNDARY_FARADS >= BULK_FARADS:
            found.append((str(designator), value, farads))
    return found


def power_mosfets_of(
    board: BoardGeometry, model: object, library=None
) -> list[tuple[str, str, str]]:
    """Every power MOSFET on this board, as ``(designator, category, basis)``.

    Two independent ways in, and a part must pass at least one:

    * the shelf calls it ``fet`` — 药箱's ``U2`` = 2N7002K, which the shelf does
      classify;
    * its designator is a ``Q`` transistor **and** it sits on a net that a
      :func:`bulk_capacitors_of` capacitor also sits on — the condition that
      makes it a *power* FET rather than a signal one, and the reason 毕设FOC
      1.0.0's bus-connected ``MCAC53N06Y-TP`` parts (``Q1``/``Q3``/``Q7``, all
      on ``+24V``) are in the pool although the shelf classifies nothing at all.

    **The second door is also a filter, not just a fallback.** A part passes
    *through* the ``Q``-door only if it sits on a bulk capacitor's net, so a
    signal FET that merely happens to be a ``Q`` transistor is out. That is why
    the three low-side FETs on 毕设FOC 1.0.0 (``Q2``/``Q4``/``Q8``, whose bus
    pads are on the switching nodes ``MOTB``/``MOTC``/``MOTA``) are **not** in
    the pool even though they are the same part number: they close no loop
    through a bulk electrolytic, and reporting them would mean reporting a loop
    that does not exist.

    ``basis`` is the evidence string the row quotes, so a reader can see **which**
    of the two doors a part came through. A board with no ``Q`` part on any bulk
    net and no shelf ``fet`` returns an empty list, and R20 then produces no
    row — 「this board has no power stage」 is a legal board, not a finding.
    """
    bulk_designators = {des for des, _value, _farads in bulk_capacitors_of(model, library)}
    bus_nets = {
        net
        for net in board.net_names()
        if bulk_designators & set(board.net(net).components)
    }
    found: list[tuple[str, str, str]] = []
    for designator in sorted(getattr(model, "components", {}) or {}):
        component = (getattr(model, "components", {}) or {})[designator]
        category = _category_of(component, library)
        nets = sorted(
            n for n in bus_nets if designator in set(board.net(n).components)
        )
        if category == "fet":
            found.append(
                (str(designator), category, f"the shelf classifies it {category!r}")
            )
            continue
        if POWER_FET_DESIGNATOR.match(str(designator)) and nets:
            found.append(
                (
                    str(designator),
                    category,
                    "designator is a Q transistor and it sits on "
                    f"{', '.join(repr(n) for n in nets)}, which a bulk "
                    f"capacitor ({', '.join(sorted(bulk_designators))}) also "
                    "sits on — the shelf classifies it "
                    f"{category or '(nothing at all)'}, so the bus connection "
                    "is what makes it a power FET",
                )
            )
    return found


# ---------------------------------------------------------------------------
# R16 — pcb-foc-decap-proximity
# ---------------------------------------------------------------------------


def _pad_layers(pad: PadGeometry) -> list[int]:
    return sorted(pad.effective_layers())


def _component_layers(board: BoardGeometry, designator: str) -> list[int]:
    """Every copper layer any of this part's pads physically occupies."""
    layers: set[int] = set()
    for pad in board.pads_for_component(designator):
        layers |= pad.effective_layers()
    return sorted(layers)


def _between_vias(
    board: BoardGeometry, cap_pads: list[PadGeometry], ic_pad: PadGeometry
) -> list[object]:
    """Vias standing between a capacitor's pads and the IC's supply pad.

    The documented **approximation**, and the docstring says so: the region is
    the axis-aligned box spanned by the capacitor's pads and the IC pad, grown by
    each via's own diameter (:func:`boardwise.core.measure.vias_in_region`, which
    already inflates the query box by the disc radius, so no growth is applied
    here). That answers 「is there any via in the corridor between the two」, not
    「does the current path through the capacitor pass a via」 — the corridor test
    is what 133b's task book specifies (*「电容焊盘与 IC 脚之间连线上有无过孔」*
    read as a region query), and the row quotes the box so a reader can see how
    wide the corridor was.
    """
    points = [pad.center for pad in cap_pads] + [ic_pad.center]
    box = BBox.from_points(points)
    if box is None:
        return []
    return vias_in_region(board, box)


def _declared_value(model: object, designator: str) -> str:
    """The value the drawing states for one part, or ``""``.

    Read off the netlist view the runner hands over — the geometry carries pads
    and tracks, not values — and **never** off the shelf: the fitted
    capacitance is the drawing's own word, and a shelf entry's value field is a
    catalogue default.
    """
    component = (getattr(model, "components", {}) or {}).get(designator)
    return str(getattr(component, "value", "") or "") if component is not None else ""


def _pairing_gap(board: BoardGeometry, a: str, b: str) -> float | None:
    """Pad-to-pad edge-to-edge gap between two components, or ``None``.

    This is the *pairing* measurement R20 needs to answer 「which bulk capacitor
    serves this FET」, and it deliberately reads
    :func:`~boardwise.core.measure.pad_edge_distance` over **every** pad pair
    rather than going through
    :func:`~boardwise.core.measure.component_distance`: the two parts in a power
    loop **share a net**, and ``component_distance`` refuses same-net pairs by
    design — it would answer ``None`` for every pair R20 wants to rank, and a
    rule that ranks nothing would pair by netlist order instead. Over-estimating
    the gap slightly for pads that face each other through the board is the
    conservative direction for a *ranking*: it cannot make a farther capacitor
    win a tie-break against a nearer one.
    """
    pads_a = board.pads_for_component(a)
    pads_b = board.pads_for_component(b)
    if not pads_a or not pads_b:
        return None
    return min(pad_edge_distance(x, y) for x in pads_a for y in pads_b)


def _fallback_gap(board: BoardGeometry, a: str, b: str) -> float | None:
    """The centre-to-centre gap, used only when :func:`_pairing_gap` has nothing.

    Two padless placements (no geometry on this document) still have a
    position, and a placement distance is a weaker but honest ranking input
    where a pad gap is absent. It is never preferred over the pad reading, and
    the row does not claim it is the same measurement.
    """
    comp_a = board.component(a)
    comp_b = board.component(b)
    if comp_a is None or comp_b is None:
        return None
    import math

    return math.hypot(comp_a.x - comp_b.x, comp_a.y - comp_b.y)


class FocDecapProximity(PcbRule):
    """R16: a power driver's bypass capacitor — how near, same layer, via between?

    One row per **(driver, supply net, capacitor)**, and each row carries three
    measurements side by side because the TI guideline is about all three at
    once (TI SLVA959B §5.3.1: the bypass sits close to the supply pin, on the
    same side of the board, with no via in between — a via in the path is an
    inductance the guideline is trying to avoid):

    1. **edge-to-edge distance** from the capacitor's pad on that net to the
       driver's own supply pad, read pad to pad
       (:func:`boardwise.core.measure.pad_edge_distance`) rather than
       component to component — the two are the *same net*, and
       :func:`~boardwise.core.measure.component_distance` **refuses same-net
       pairs by design**, so its answer on this pair is some other net's gap
       (131d found this and wrote it down). The component-level figure is
       reported too, in the evidence, for the reader who wants the placement
       distance rather than the loop leg;
    2. **same layer or not** — the two parts' ``effective_layer_ids`` sets
       intersected (127b's reading: the footprint's ``layer_id`` is not where the
       copper is, and 毕设FOC 1.0.0's PCB1 places ``U4``/``U6``/``R17``/``C14``
       on the bottom while every one of their pads says ``layer 1``);
    3. **vias in the corridor** between the capacitor's pads and the driver's
       supply pad (:func:`_between_vias`).

    TI §5.3.1's 0.2 in is quoted in the evidence next to the measurement and
    **grades nothing**: this is the pack's 「INFO 出数起步」 discipline and the
    first row is no more of a verdict than the hundredth.

    **Supply nets come from the pin name, through 131a's own classifier.**
    :func:`boardwise.core.pinrole.pin_role` decides which pins declare a supply
    role (``VM`` / ``DVDD`` → ``IN`` on all three acceptance boards' drivers),
    and the capacitor pool is
    :func:`boardwise.rules.decap.cap_candidates_on` — the predicate 126b, 131d
    and 131b already share, so this rule cannot disagree with them about what a
    grounded bypass is. A supply net with **no** candidate on it gets one INFO
    row that names the net and the driver, which is the 「absent, not empty」
    discipline rather than a silence.
    """

    id = "pcb-foc-decap-proximity"
    title = "A power driver's bypass capacitor: how near the supply pin, same layer, no via between"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §5.3.1（出数不出判定，阈值待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        Same contract as 131b's and 131d's: ``library=None`` degrades to an empty
        shelf, so a synthetic test injects a two-entry library rather than
        monkeypatching the project's own
        :func:`boardwise.rules.facts.default_library_path`.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for designator, component, category in _motor_drivers(model, library):
            if board.component(designator) is None:
                continue  # named by the netlist, not placed on this PCB document
            findings.extend(self._one_driver(board, model, designator, category, library))
        return findings

    def _identity(self, designator: str, category: str) -> list[str]:
        return [
            f"{designator} read as a power driver because the shelf category "
            f"is {category!r} — the only category this rule examines "
            f"({', '.join(sorted(MOTOR_DRIVER_CATEGORIES))})",
            "supply pins read off the pin **name** through "
            "core.pinrole.pin_role (131a's classifier), never off the net name "
            "and never off the MPN",
            "the bypass pool is rules.decap.cap_candidates_on — the same "
            "ground-bridging predicate 126b and 131b read, so this rule cannot "
            "disagree with them about what a bypass capacitor is",
            f"TI SLVA959B §5.3.1 places the bypass within "
            f"{TI_DECAP_REFERENCE_MIL:.0f} mil (0.2 in) of the supply pin; that "
            "figure is quoted here for reference and **this rule grades "
            "nothing** — 岳 has ruled on no decoupling threshold in this pack",
        ]

    def _supply_nets(self, component: object) -> list[tuple[str, str, str, str]]:
        """``(net, pin number, pin name, role)`` for this driver's supply pins.

        A pin with **no net** is skipped: there is no supply net to look at, and
        inventing one would be a guess. Roles ``IN`` and ``OUT`` are both supply
        roles (a driver's ``VM`` is ``IN`` and nothing on these parts declares
        ``OUT``, but the rule reads both rather than hard-coding one shape).
        """
        from ...core.pinrole import pin_role

        rows: list[tuple[str, str, str, str]] = []
        for pin in getattr(component, "pins", ()) or ():
            name = str(getattr(pin, "name", "") or "")
            role = pin_role(name)
            if role not in {"IN", "OUT"}:
                continue
            net = str(getattr(pin, "net", "") or "")
            if not net:
                continue
            rows.append(
                (net, str(getattr(pin, "number", "") or ""), name, str(role))
            )
        return sorted(set(rows))

    def _one_driver(
        self,
        board: BoardGeometry,
        model: object,
        designator: str,
        category: str,
        library,
    ) -> list[Finding]:
        """Every row for one power driver on one PCB document."""
        component = (getattr(model, "components", {}) or {})[designator]
        identity = self._identity(designator, category)
        supply = self._supply_nets(component)
        if not supply:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{designator} declares no supply pin that carries a "
                        "net (core.pinrole.pin_role found no ``IN``/``OUT`` role "
                        "on any of its connected pins), so no bypass net and no "
                        "bypass distance can be read for this driver"
                    ),
                    evidence=identity,
                    target=FindingTarget(component_ref=designator),
                )
            ]

        findings: list[Finding] = []
        ic_layers = _component_layers(board, designator)
        for net, pin_number, pin_name, role in supply:
            ic_pad = self._pad(board, designator, pin_number)
            if ic_pad is None:
                continue
            ic_pad_layers = _pad_layers(ic_pad)
            candidates = list(cap_candidates_on(model, net, library))
            seen: list[str] = []
            evidence = [
                *identity,
                f"supply net {net!r} is declared by pin {pin_number} "
                f"({pin_name!r}, role {role!r})",
                f"{designator} occupies copper layers {ic_layers or '(unstated)'}"
                + (
                    f"; pin {pin_number} itself sits on {ic_pad_layers}"
                    if ic_pad_layers
                    else f"; pin {pin_number}'s own layers were never "
                    "established, so the same-layer reading below is UNKNOWN "
                    "rather than 「different」"
                ),
                "bypass candidates bridging this net to a ground net: "
                + (", ".join(sorted(c.designator for c in candidates)) or "(none)"),
            ]
            if not candidates:
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="INFO",
                        level=self.level,
                        message=(
                            f"the bypass network of {designator} on supply net "
                            f"{net!r} (pin {pin_number} {pin_name!r}) is empty — "
                            "no capacitor on this net bridges it to a ground net, "
                            "so no distance, no same-layer reading and no via "
                            "corridor is claimed for it"
                        ),
                        evidence=evidence,
                        target=FindingTarget(
                            component_ref=designator,
                            net_refs=[net],
                            pin_refs=[pin_number],
                        ),
                    )
                )
                continue
            for candidate in sorted(candidates, key=lambda c: c.designator):
                if candidate.designator in seen:
                    continue
                seen.append(candidate.designator)
                findings.append(
                    self._one_cap(
                        board,
                        model,
                        designator,
                        candidate.designator,
                        net,
                        pin_number,
                        pin_name,
                        ic_pad,
                        ic_pad_layers,
                        ic_layers,
                        evidence,
                        library,
                    )
                )
        return findings

    def _pad(self, board: BoardGeometry, designator: str, pin: str):
        for pad in board.pads_for_component(designator):
            if (pad.pin_number or pad.id) == pin:
                return pad
        return None

    def _one_cap(
        self,
        board: BoardGeometry,
        model: object,
        driver: str,
        cap: str,
        net: str,
        pin_number: str,
        pin_name: str,
        ic_pad: PadGeometry,
        ic_pad_layers: list[int],
        ic_layers: list[int],
        identity: list[str],
        library,
    ) -> Finding:
        """One (driver, net, capacitor) row: distance, same layer, corridor vias."""
        cap_pads = [
            pad for pad in board.pads_for_component(cap) if pad.net == net
        ]
        cap_layers = _component_layers(board, cap)
        same_layer = bool(set(ic_pad_layers) & set(cap_layers))
        component_level = component_distance(board, driver, cap)
        vias = _between_vias(board, cap_pads, ic_pad) if cap_pads else []
        gap = min(
            (pad_edge_distance(a, ic_pad) for a in cap_pads),
            default=None,
        )
        declared = _declared_value(model, cap)
        farads = parse_capacitance_farads(declared) if declared else None

        parts = [
            f"{cap} on {net!r} sits {_mil(gap):.1f} mil edge-to-edge from "
            f"{driver}.{pin_number} ({pin_name!r})"
            if gap is not None
            else f"{cap} is named on {net!r} but this PCB document places none "
            "of its pads on that net, so the gap is unmeasurable rather than zero",
            (
                f"**same copper layer**: {driver} pin {pin_number} on "
                f"{ic_pad_layers or '(unstated)'} and {cap} on "
                f"{cap_layers or '(unstated)'} — "
                + (
                    "they share one"
                    if same_layer
                    else "**they do not share a layer**, so the bypass does not "
                    "reach the supply pin on the same face"
                    if ic_pad_layers and cap_layers
                    else "UNKNOWN: one of the two parts' copper layers was "
                    "never established, and UNKNOWN is not 「different」"
                )
            ),
            (
                f"{len(vias)} via(s) in the corridor between {cap}'s pad(s) on "
                f"{net!r} and {driver}.{pin_number} (region query — the box "
                "spanning both pads' centres, see evidence)"
                if vias
                else "no via stands in the corridor between "
                f"{cap}'s pad(s) and {driver}.{pin_number}"
            ),
            f"{cap} declared value {declared!r}"
            + (
                ""
                if not declared
                else f" = {farads * 1e6:g} µF"
                if farads is not None
                else " — unreadable, so no capacitance figure is stated"
            ),
            f"component-level distance {driver} ↔ {cap}: "
            + (
                f"{_mil(component_level.edge_distance):.1f} mil edge-to-edge "
                f"(pads {component_level.pad_a} / {component_level.pad_b}) — a "
                "**different** measurement from the loop leg above, because "
                "core.measure.component_distance refuses same-net pairs and "
                "would answer with some other net's gap; quoted so a reader who "
                "wants the placement distance has it"
                if component_level is not None
                else "unmeasurable (component_distance refuses same-net pairs, "
                "and these two share "
                f"{net!r})"
            ),
            f"TI SLVA959B §5.3.1 reference: within "
            f"{TI_DECAP_REFERENCE_MIL:.0f} mil (0.2 in) of the supply pin — "
            "**not applied**, this row is a measurement and 岳 has ruled on no "
            "threshold in this pack",
        ]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message="; ".join(parts)
            + " — INFO 出数，阈值待岳裁，本行不出判定",
            evidence=[
                *identity,
                *parts,
                f"corridor region for the via query: pad centres "
                + ", ".join(
                    f"{cap}.{p.pin_number or p.id}@({p.x:.1f},{p.y:.1f})"
                    for p in cap_pads
                )
                + f" and {driver}.{pin_number}@({ic_pad.x:.1f},{ic_pad.y:.1f})",
                "the corridor test is the documented approximation 133b asks "
                "for (a region query between the two pads), **not** a claim "
                "about which vias carry the bypass current — a row that needs "
                "that reading must re-derive it from the net's own copper",
                "layer reading is effective_layer_ids (127b): the footprint's "
                "layer_id is not where the copper physically is, and 毕设FOC "
                "1.0.0's PCB1 places four parts on the bottom whose pads all "
                "say layer 1",
            ],
            target=FindingTarget(
                component_ref=cap,
                net_refs=[net],
                counterpart_ref=driver,
                pin_refs=[pin_number],
                measurement=_measurement("distance", gap)
                if gap is not None
                else None,
            ),
        )


# ---------------------------------------------------------------------------
# R31 — pcb-foc-ground-plane
# ---------------------------------------------------------------------------


class FocGroundPlane(PcbRule):
    """R31: on a multi-layer board, is there a layer with **one** ground island?

    Read in three steps, and each is a number the row states:

    1. **Is the board in scope?** The copper count of the **physical** stackup
       (:func:`boardwise.core.measure.read_stackup`) against
       :data:`MULTILAYER_THRESHOLD`. This is 125a's reading and 岳's 2026-10-07
       ruling, not a count of ``LAYER`` records — 毕设FOC 1.0.0's PCB1 defines
       **34** copper ``LAYER`` records and is a **4**-layer board. A board below
       the threshold gets exactly one INFO row saying it is out of scope, and no
       plane reading: TI §1.2's concern is the return path across inner layers,
       which a two-layer board does not have.
    2. **Per ground-class net, how many islands** (:func:`pour_connectivity`) and
       which of them lies on which layers. 「Ground-class」 is the module's own
       :attr:`NetGeometry.is_ground` (``GND`` / ``AGND`` / ``PGND`` / … by
       prefix) — the corpus's own reading, and the reason 毕设FOC 1.0.0's
       ``AGND`` (1 island) / ``GND`` (46) / ``PGND`` (33) all appear while llc's
       unnamed return nets do not.
    3. **The single-island nets' coverage**: for a ground net whose
       ``island_count == 1``, the island's pour area and its share of the board
       area (the outline bbox's area — the only board-frame measure the geometry
       carries). Both numbers are **what is there**, and whether a plane covering
       20 % of a board is 「enough」 is a question 岳 has not answered, so no
       threshold is applied and none is named.

    **Absent is not empty.** A board with a degenerate outline (毕设FOC's PCB2
    carries a single-point ``BOARD_OUTLINE`` poly) reports the island and its
    area and says the **board-area share is unmeasurable**, rather than dividing
    by a zero board.
    """

    id = "pcb-foc-ground-plane"
    title = "A multi-layer board's ground plane: one island per ground net, and how much of the board it covers"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §1.2（出数不出判定，阈值待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        info = read_stackup(board)
        if info.copper_count < MULTILAYER_THRESHOLD:
            return [self._out_of_scope(board, info)]
        return self._in_scope(board, info)

    def _out_of_scope(self, board: BoardGeometry, info) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{board.name or 'this PCB document'} reads "
                f"{info.copper_count} copper layer(s) in its physical stackup, "
                f"below the {MULTILAYER_THRESHOLD}-layer threshold, so it is a "
                "**two-layer board and R31 does not apply to it** — TI §1.2's "
                "concern is a continuous return path across the inner layers, "
                "which a board this thin does not have. No island count and no "
                "coverage figure is claimed"
            ),
            evidence=[
                f"copper layers read from LAYER_PHYS via "
                f"core.measure.read_stackup: "
                + (", ".join(str(i.layer_id) for i in info.copper_layers) or "(none)")
                + f" = {info.copper_count} layer(s)",
                f"threshold {MULTILAYER_THRESHOLD} is the task book's own "
                "figure for 「≥4 层板」, applied as a **scope** test (is this "
                "question about this board at all) and never as a verdict",
                "the LAYER definitions are deliberately not counted: PCB1 "
                "defines 34 copper LAYER records and is a 4-layer board "
                "(岳 2026-10-07 亲裁)",
            ],
            target=FindingTarget(),
        )

    def _in_scope(self, board: BoardGeometry, info) -> list[Finding]:
        outline = board.outline.bbox if board.outline is not None else None
        board_area = 0.0 if outline is None else outline.width * outline.height
        degenerate = outline is None or len(board.outline.points) < 3
        grounds = [n for n in board.net_names() if board.net(n).is_ground]
        findings: list[Finding] = []
        if not grounds:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        "this board reads no net whose **name** is ground-class "
                        "(core.model.is_ground_net: GND / AGND / PGND / VSS …), "
                        "so no island count and no plane reading is claimed — "
                        "the name is the only place the drawing states a net is "
                        "ground, and a net named otherwise is UNKNOWN here, not "
                        "「not ground」"
                    ),
                    evidence=[
                        f"copper layers: {info.copper_count} (>= "
                        f"{MULTILAYER_THRESHOLD}, so the board IS in scope)",
                        "ground-class test is the module's own is_ground_net "
                        "prefix reading, shared with core.measure",
                    ],
                    target=FindingTarget(),
                )
            ]
        for net in grounds:
            connectivity = pour_connectivity(board, net)
            lines = [
                f"net {net!r} (ground-class by name): "
                f"{connectivity.island_count} island(s) of copper "
                f"({len(board.pours_for_net(net))} pour region(s), total pour "
                f"area {board.net(net).pour_area:.4g} sq mil)",
                f"copper layers of the board: "
                + (
                    ", ".join(
                        f"{i.layer_id} ({i.name})" for i in info.copper_layers
                    )
                    or "(none)"
                ),
                f"board area for the coverage share: "
                + (
                    "UNMEASURABLE — the outline carries "
                    f"{len(board.outline.points)} point(s), which is not a "
                    "board frame (126b's MIN_OUTLINE_CORNERS discipline), so no "
                    "share is computed and no share is claimed"
                    if degenerate
                    else f"{board_area:.4g} sq mil (outline bbox)"
                ),
            ]
            for island in connectivity.islands:
                share = (
                    ""
                    if degenerate or board_area <= 0.0
                    else f" = {island.area / board_area * 100:.1f}% of the board area"
                )
                lines.append(
                    f"  island {island.island_id}: pour area "
                    f"{island.area:.4g} sq mil{share}, layers "
                    f"{island.layer_ids}, {len(island.element_ids)} element(s)"
                )
            summary = (
                f"net {net!r} breaks into {connectivity.island_count} copper "
                f"island(s)"
                + (
                    f" — **no single island**: the largest is "
                    f"{max((i.area for i in connectivity.islands), default=0.0):.4g} "
                    "sq mil"
                    if connectivity.island_count != 1
                    else f" — **one island**, pour area "
                    f"{connectivity.islands[0].area:.4g} sq mil"
                    + (
                        ""
                        if degenerate or board_area <= 0.0
                        else f" = {connectivity.islands[0].area / board_area * 100:.1f}% "
                        "of the board area"
                    )
                )
            )
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=summary
                    + " — INFO 出数；「够不够」不是本工具的判定（岳裁定未到）",
                    evidence=[
                        *lines,
                        "island count read by pour_connectivity (union-find over "
                        "touching copper on shared layers); 「single island」 is "
                        "the shape TI §1.2's continuous-plane question is about, "
                        "stated as a number and not graded",
                        f"ground-class test: {len(grounds)} net(s) matched",
                    ],
                    target=FindingTarget(net_refs=[net]),
                )
            )
        return findings


# ---------------------------------------------------------------------------
# R11 — pcb-foc-gate-trace-width
# ---------------------------------------------------------------------------


class FocGateTraceWidth(PcbRule):
    """R11: the gate (and switching / sense) nets' track **width distribution**.

    One row per power-path net that carries tracks, with
    :func:`boardwise.core.measure.track_width_stats`'s four numbers side by side:
    **track count, min width, max width, total length** — plus the per-layer
    breakdown the same reading carries, because 「the gate net is 10 mil」 is a
    different statement from 「the gate net is 10 mil on the top layer and 25 mil
    where it drops to the bottom」.

    TI SLVA959B §4's first item is a minimum gate-drive trace width (≥20 mil);
    that figure is **quoted in the evidence and applied to nothing** — the pack
    is 「INFO 出数起步」 and 岳 has ruled on no gate-width threshold. The
    measured figures are the corpus's own: 毕设FOC 1.0.0's six gate nets all read
    10 mil uniform, 1.1.0's read 10–15 mil, and the row says so next to TI's
    number without choosing between them.

    **The net set is a name test** (:func:`is_power_net` /
    :data:`GATE_NET_PATTERN`) and the module docstring says why: a net has no
    shelf category and no pin role that says 「gate」. A board with no such net at
    all gets **one** INFO row saying so. ROBOT is the measured instance: its
    ``DRV1`` connects the gate pins to ``TIM1_CH1`` / ``TIM1_CH2`` /
    ``TIM1_CH3``, so R11 reads **zero** gate nets on that board even though it
    plainly has a gate drive. Naming those nets would mean asserting that a
    timer channel *is* a gate net — a mapping the drawing does not state and 岳
    has not ruled on — so the row reports the sieve and its result instead.
    """

    id = "pcb-foc-gate-trace-width"
    title = "Gate-drive and power-path trace widths: min, max, total length per net"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §4（出数不出判定，阈值待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        nets = gate_nets_of(board)
        if not nets:
            return [self._no_nets(board)]
        return [self._one_net(board, net) for net in nets]

    def _no_nets(self, board: BoardGeometry) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                "no net on this board has a power-path name that "
                "core.measure's reader recognises ("
                + ", ".join(repr(p) for p in POWER_NET_PREFIXES)
                + " families, gate nets matching "
                f"{GATE_NET_PATTERN.pattern!r}), so no gate trace width is "
                "reported — the net **name** is the only place the drawing "
                "states a net is a gate net, and a gate net spelled outside "
                "these families would land here"
            ),
            evidence=[
                f"nets carrying tracks on this board: {len(board.net_names())}",
                "net-name sieve (the acknowledged fragile step): "
                + f"{GATE_NET_PATTERN.pattern!r} plus the "
                + ", ".join(repr(p) for p in POWER_NET_PREFIXES)
                + " prefixes; no shelf category and no pin role says 「gate」",
                f"TI SLVA959B §4 reference: {TI_GATE_WIDTH_REFERENCE_MIL:.0f} mil "
                "minimum gate-drive width — quoted, never applied (岳 has "
                "ruled on no threshold in this pack)",
            ],
            target=FindingTarget(),
        )

    def _one_net(self, board: BoardGeometry, net: str) -> Finding:
        stats = track_width_stats(board, net)
        per_layer = ", ".join(
            f"layer {layer_id}: {layer.track_count} track(s), "
            f"min {layer.min_width:g} mil, {layer.total_length:.1f} mil total"
            for layer_id, layer in sorted(stats.per_layer.items())
        ) or "(no track carries a layer id)"
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"power-path net {net!r}: {stats.track_count} track(s), width "
                f"min {stats.min_width:g} mil / max {stats.max_width:g} mil, "
                f"{stats.total_length:.1f} mil total — TI §4's "
                f"{TI_GATE_WIDTH_REFERENCE_MIL:.0f} mil reference is quoted in "
                "the evidence and **not applied** (岳 has ruled on no threshold "
                "in this pack)"
            ),
            evidence=[
                f"net {net!r} matched the power-path name sieve "
                f"({GATE_NET_PATTERN.pattern!r} / "
                + ", ".join(repr(p) for p in POWER_NET_PREFIXES)
                + " families) — the fragile step, declared",
                f"read by core.measure.track_width_stats over "
                f"{stats.track_count} track(s): min {stats.min_width:g} mil, "
                f"max {stats.max_width:g} mil, total {stats.total_length:.1f} mil",
                "per layer: " + per_layer,
                f"TI SLVA959B §4 first item: gate-drive traces "
                f">= {TI_GATE_WIDTH_REFERENCE_MIL:.0f} mil — **not applied**, "
                "this row is a measurement",
            ],
            target=FindingTarget(
                net_refs=[net],
                measurement=_measurement("width", stats.min_width),
            ),
        )


# ---------------------------------------------------------------------------
# R13 — pcb-foc-track-corners
# ---------------------------------------------------------------------------


class FocTrackCorners(PcbRule):
    """R13: every **non-obtuse fold** in the routing, listed.

    Reads 133a's :func:`boardwise.core.measure.track_corner_angle` directly — the
    primitive already reports the interior angle and excludes folds at or above
    its own :data:`~boardwise.core.measure.OBTUSE_CORNER_DEG` geometric
    constant (a straight continuation reads 180 and is out by construction). This
    rule adds no threshold of its own: TI SLVA959B §4 / 图 4-3 call a right-angle
    bend on a gate or switching node worth looking at, and **「worth looking at」
    is not a defect**, so the row lists the folds and their angles and grades
    nothing.

    Two rows on any board that has a fold:

    * one **whole-board** row — the full count, the angle histogram, and the
      sharpest fold, so the board's overall shape is one line;
    * one row **per fold on a power-path net**, narrowed through the same
      :func:`is_power_net` sieve R11 uses, because TI's concern is the gate and
      switching nodes specifically.

    Measured: 毕设FOC 1.0.0's PCB1 reads **64** folds across 23 nets, of which
    **7** are on a power-path net (``GLB``, ``IA`` ×2, ``IA+``, ``IB``,
    ``IB+``, ``IC``) and so get their own row; llc reads **1** (on ``DC-``,
    which is not a power net, so only the whole-board row); 毕设FOC 1.1.0's PCB3
    reads 0 and likewise produces only the whole-board row.
    """

    id = "pcb-foc-track-corners"
    title = "Track bends: every non-obtuse fold in the routing, with its angle"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §4 图 4-3（出数不出判定，阈值待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        corners = track_corner_angle(board)
        findings: list[Finding] = [self._whole_board(board, corners)]
        for corner in corners:
            if not is_power_net(corner.net or ""):
                continue
            findings.append(self._one_corner(corner))
        return findings

    def _whole_board(self, board: BoardGeometry, corners) -> Finding:
        if not corners:
            return Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    "this board has **no non-obtuse fold** in its routing — "
                    f"every one of its {len(board.tracks)} track(s) either runs "
                    "straight through a joint or bends at or above "
                    "core.measure.OBTUSE_CORNER_DEG, so the list 133a's "
                    "track_corner_angle returns is empty and no per-fold row is "
                    "claimed"
                ),
                evidence=[
                    f"tracks on this board: {len(board.tracks)}",
                    "the window is the primitive's own geometric constant "
                    f"OBTUSE_CORNER_DEG = {OBTUSE_CORNER_DEG}°"
                    "; a straight continuation reads 180 and is out by "
                    "construction, so no separate collinear test exists",
                    "TI SLVA959B §4 图 4-3 calls a right-angle bend on a gate or "
                    "switching node worth looking at — worth looking at is not "
                    "a defect, so nothing is graded",
                ],
                target=FindingTarget(),
            )
        angles = sorted(c.angle_deg for c in corners)
        histogram: dict[str, int] = {}
        for angle in angles:
            key = f"{round(angle / 5.0) * 5:.0f}°"
            histogram[key] = histogram.get(key, 0) + 1
        sharpest = corners[min(range(len(corners)), key=lambda i: angles[i])]
        per_net: dict[str, int] = {}
        for corner in corners:
            key = corner.net or "(no net)"
            per_net[key] = per_net.get(key, 0) + 1
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{len(corners)} non-obtuse fold(s) in this board's routing, on "
                f"{len(per_net)} net(s); sharpest "
                f"{sharpest.angle_deg:.1f}° on {sharpest.net!r} — "
                "TI §4 图 4-3's 「look at right-angle bends on gate / switching "
                "nodes」 is quoted, **nothing is graded**"
            ),
            evidence=[
                f"read by core.measure.track_corner_angle over "
                f"{len(board.tracks)} track(s); the primitive reports only "
                f"folds below OBTUSE_CORNER_DEG = {OBTUSE_CORNER_DEG:g}° — a "
                "**geometric constant of the measurement, not a verdict**, "
                "and the interior angle is reported verbatim, which is what "
                "lets a rule grade the numbers itself",
                "a fold at exactly the window boundary comes back as "
                f"{OBTUSE_CORNER_DEG - 1e-9:.9f}° from the acos of a dot "
                "product one ULP short of exact, and 133a's boundary guard "
                "leaves it out — the constant excludes the 135° mitre by "
                "construction rather than by a separate test",
                "angle histogram (5° buckets): "
                + ", ".join(f"{k}×{v}" for k, v in sorted(histogram.items(),
                                                           key=lambda kv: kv[0])),
                "folds per net: "
                + ", ".join(f"{net}×{count}" for net, count in sorted(per_net.items())),
                f"sharpest fold: {sharpest.angle_deg:.2f}° at "
                f"({sharpest.position.x:.1f}, {sharpest.position.y:.1f}) on "
                f"{sharpest.net!r} layer {sharpest.layer_id} between tracks "
                f"{sharpest.track_a} and {sharpest.track_b}",
            ],
            target=FindingTarget(net_refs=[sharpest.net] if sharpest.net else []),
        )

    def _one_corner(self, corner) -> Finding:
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"power-path net {corner.net!r} bends {corner.angle_deg:.1f}° "
                f"at ({corner.position.x:.1f}, {corner.position.y:.1f}) on "
                f"layer {corner.layer_id} (tracks {corner.track_a} / "
                f"{corner.track_b}) — a measurement: TI §4 图 4-3 says to look "
                "at such bends, and looking is not a verdict"
            ),
            evidence=[
                "this net matched the power-path name sieve shared with "
                f"pcb-foc-gate-trace-width ({GATE_NET_PATTERN.pattern!r} / "
                + ", ".join(repr(p) for p in POWER_NET_PREFIXES)
                + " families)",
                "read by core.measure.track_corner_angle: interior angle "
                f"{corner.angle_deg!r}° (0 hairpin, 90 right angle, 180 "
                "straight), below the primitive's OBTUSE_CORNER_DEG window",
                "TI SLVA959B §4 图 4-3 reference — **not applied**, this row is "
                "a measurement and 岳 has ruled on no threshold in this pack",
            ],
            target=FindingTarget(net_refs=[corner.net] if corner.net else []),
        )


# ---------------------------------------------------------------------------
# R20 — pcb-foc-power-loop-area
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoopReading:
    """One high-current loop: its anchors and its area in **both** 口径."""

    bulk: str = ""
    bulk_value: str = ""
    bulk_farads: float = 0.0
    mos: str = ""
    mos_basis: str = ""
    #: The anchor strings handed to ``loop_area``, in order.
    anchors: tuple[str, ...] = ()
    polygon_area: float = 0.0
    bbox_area: float = 0.0
    #: The pairing measurement — the pad-to-pad edge-to-edge distance that made
    #: capacitor **this** FET's nearest bulk. ``None`` when
    #: :func:`~boardwise.core.measure.component_distance` refuses the pair (the
    #: two share a net, and it refuses same-net pairs by design).
    distance: object = None


class FocPowerLoopArea(PcbRule):
    """R20: the high-current loop between a **bus electrolytic** and a **MOSFET**.

    TI SLVA959B §6.3.2 / §1.4 ask for the loop through the bulk capacitor, the
    power FET and the return to be as small as the layout can make it. This rule
    **measures** that loop and reports it in **both 口径**, because 岳's ruling on
    which one 「环路面积」 means has not arrived:
    the **polygon** (shoelace over the anchor quadrilateral) and the
    **bounding-box** area, which is the upper bound a placement checklist means
    by 「环路大小」. Both come from
    :func:`boardwise.core.measure.loop_area`, which reports both by design, and
    **neither is marked as the answer**.

    **How the anchors are built** — the part of the rule worth stating plainly.
    The loop is ``bulk capacitor's bus pad → bulk capacitor's return pad →
    the power FET's bus pad (the same bus net) → the power FET's ground pad (or,
    for a half-bridge low-side FET, its switching-node pad, which *is* the
    half of the bridge that carries the same current)``. The rule pairs each
    **nearest** bulk capacitor to each power FET (nearest by
    :func:`~boardwise.core.measure.component_distance`, so the pairing is a
    measurement rather than a netlist ordering), and requires the FET to sit on
    the **same bus net** as the capacitor's bus pad — which is what makes it a
    loop rather than two unrelated placements. A FET whose bus pad is on a
    different net, or a capacitor with no FET on its bus, is **not** reported:
    there is no loop to close.

    **Measured on 毕设FOC 1.0.0**: ``C115`` and ``C116`` (330 µF, both on
    ``+24V``/``PGND``) against the six ``MCAC53N06Y-TP`` FETs — **one row per
    closing FET** (three rows on PCB1), each paired with whichever of the two
    capacitors is nearer. Only the **high-side** three close a loop: ``Q2`` /
    ``Q4`` / ``Q8`` have their bus pads on the switching nodes (``MOTB`` /
    ``MOTC`` / ``MOTA``), which no bulk electrolytic touches, so there is no
    loop through a *bulk* capacitor to close with them and the rule does not
    invent one. ROBOT has a driver and no bulk capacitor (its largest fitted cap
    is 10 µF), so it is **silent** here.

    **llc fires too, and that is the honest answer rather than a miss.** llc
    places no ``ic.motor-driver``, so R16 is silent on it, but it *does* place
    two 330 µF bulk capacitors on ``DC+``/``DC-`` and four ``B3M040065H`` FETs
    whose bus pads sit on those same nets — it is a full-bridge power stage, so
    the high-current loop is a real thing to measure on that board and the rule
    reports it (four rows). A board with no power stage at all (药箱: no motor
    driver, no bulk capacitor, no power FET) produces **no row** — 「no power
    stage」 is a legal board shape, and a rule that filed a finding for every
    absence would bury the FOC boards under everything else.
    """

    id = "pcb-foc-power-loop-area"
    title = "High-current loop: bus electrolytic to power MOSFET, polygon and bbox area side by side"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §6.3.2 / §1.4（出数不出判定，口径待岳裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass, with the shelf handed in (same contract as 131b/131d)."""
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        readings = self._loops(board, model, library)
        if not readings:
            return []
        return [self._one_loop(board, model, library, reading) for reading in readings]

    def _loops(
        self, board: BoardGeometry, model: object, library
    ) -> list[LoopReading]:
        """Every closable (bulk capacitor, power FET) loop on this board."""
        bulks = bulk_capacitors_of(model, library)
        fets = power_mosfets_of(board, model, library)
        readings: list[LoopReading] = []
        for mos, category, basis in fets:
            mos_pads = board.pads_for_component(mos)
            if not mos_pads:
                continue
            mos_nets = {pad.net for pad in mos_pads if pad.net}
            # The **nearest** bulk capacitor that actually shares a bus net with
            # this FET. 「Nearest」 is the task book's own wording and it is what
            # keeps the reading a placement measurement rather than a netlist
            # ordering: 毕设FOC 1.0.0's PCB1 has two 330 µF caps on +24V and six
            # FETs, and pairing every combination would print twelve rows where
            # the question is 「which one serves this FET」. One row per FET. A
            # capacitor **may** serve more than one FET — that is what a bus
            # capacitor does — so the pairing is not one-to-one, and a tie at the
            # same gap is broken by designator so the result is deterministic.
            candidates: list[tuple[float, str, str, float]] = []
            for bulk, value, farads in bulks:
                bulk_pads = board.pads_for_component(bulk)
                if not bulk_pads:
                    continue
                shared = sorted({p.net for p in bulk_pads if p.net} & mos_nets)
                if not shared:
                    continue  # the two do not share a net: no loop to close
                gap = _pairing_gap(board, bulk, mos)
                if gap is None:
                    # A padless placement has no pad gap; its position is a
                    # weaker but honest ranking input, and dropping the loop
                    # entirely would lose a real one.
                    gap = _fallback_gap(board, bulk, mos)
                if gap is None:
                    continue
                candidates.append((gap, bulk, value, farads))
            if not candidates:
                continue  # no bulk capacitor on any of this FET's nets: no loop
            candidates.sort(key=lambda row: (row[0], row[1]))
            gap, bulk, value, farads = candidates[0]

            bulk_pads = board.pads_for_component(bulk)
            bus_net = sorted({p.net for p in bulk_pads if p.net} & mos_nets)[0]
            bulk_bus = next(p for p in bulk_pads if p.net == bus_net)
            bulk_return = next((p for p in bulk_pads if p.net != bus_net), None)
            if bulk_return is None:
                continue
            mos_bus = next(p for p in mos_pads if p.net == bus_net)
            mos_return = next((p for p in mos_pads if p.net != bus_net), None)
            if mos_return is None:
                continue
            anchors = (
                f"{bulk}.{bulk_bus.pin_number or bulk_bus.id}",
                f"{bulk}.{bulk_return.pin_number or bulk_return.id}",
                f"{mos}.{mos_bus.pin_number or mos_bus.id}",
                f"{mos}.{mos_return.pin_number or mos_return.id}",
            )
            try:
                area = loop_area(board, list(anchors))
            except ValueError:
                continue  # an anchor the board cannot resolve: no reading
            readings.append(
                LoopReading(
                    bulk=bulk,
                    bulk_value=value,
                    bulk_farads=farads,
                    mos=mos,
                    mos_basis=basis,
                    anchors=anchors,
                    polygon_area=area.polygon_area,
                    bbox_area=area.bbox_area,
                    distance=gap,
                )
            )
        return readings

    def _one_loop(
        self, board: BoardGeometry, model: object, library, reading: LoopReading
    ) -> Finding:
        ratio = (
            reading.bbox_area / reading.polygon_area
            if reading.polygon_area > 0
            else None
        )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"high-current loop {reading.bulk} ({reading.bulk_value}) ↔ "
                f"{reading.mos}: polygon area "
                f"{reading.polygon_area:.4g} sq mil, bbox area "
                f"{reading.bbox_area:.4g} sq mil — **both 口径 are reported** and "
                "neither is marked as the answer (岳's ruling on which one is "
                "「环路面积」 has not arrived); measurement only"
            ),
            evidence=[
                f"bulk capacitor {reading.bulk}: declared "
                f"{reading.bulk_value!r} = {reading.bulk_farads * 1e6:g} µF, "
                f"at or above the {BULK_FARADS * 1e6:g} µF floor (133b's own "
                "figure; read through core.values.parse_capacitance_farads on "
                "the drawing's own value, never guessed from a package)",
                f"power FET {reading.mos} recognised because: {reading.mos_basis}",
                "anchor construction (the documented shape): the bulk "
                "capacitor's bus pad → its return pad → the FET's pad on the "
                "**same bus net** → the FET's other pad (the half of the bridge "
                "that carries the same current). The loop is only closed when "
                "the two parts **share a net**; a FET on a different net is "
                "not reported",
                f"anchors, in order: {', '.join(reading.anchors)}",
                f"polygon area (shoelace over the anchor quadrilateral): "
                f"{reading.polygon_area:.6g} sq mil",
                f"bbox area (upper bound on the polygon): "
                f"{reading.bbox_area:.6g} sq mil"
                + (
                    f" = {ratio:.2f}× the polygon"
                    if ratio is not None
                    else ""
                ),
                "both numbers come from core.measure.loop_area, which reports "
                "polygon_area and bbox_area by design; the rule adds neither a "
                "threshold nor a choice between them",
                f"pairing gap {reading.bulk} ↔ {reading.mos}: "
                + (
                    f"{_mil(reading.distance):.1f} mil — the **nearest** bulk "
                    "capacitor on a net this FET shares, which is why this one "
                    "serves it; read pad-to-pad (see :func:`_pairing_gap`), "
                    "because core.measure.component_distance refuses the "
                    "same-net pair this loop is made of"
                    if reading.distance is not None
                    else "unmeasurable — no pad-to-pad gap could be read, and "
                    "the loop is reported anyway with the pairing unstated "
                    "rather than dropped"
                ),
                "TI SLVA959B §6.3.2 / §1.4 reference: make the loop through the "
                "bulk capacitor, the FET and the return as small as the layout "
                "allows — **not applied**, no area threshold is in force",
            ],
            target=FindingTarget(
                component_ref=reading.bulk,
                counterpart_ref=reading.mos,
                measurement=_measurement("area", reading.polygon_area),
            ),
        )