"""FOC thermal-design rules — task 133d (R7 / R8 / R9).

133a landed the ``via_geometry`` queries, 133b the five quick wins, 133c the
ground system; 133d is the batch that reads the **thermal design** of a power
driver's exposed pad: which vias stand in the pad's projection, what they look
like, and whether the pad has a continuous copper exit to a large plane. Three
rules, one file, all ``INFO`` — 岳 has ruled no threshold in this pack, so every
row is a measurement.

* :class:`FocThermalViaStyle` (``pcb-foc-thermal-via-style``, **R7**) — the
  vias standing inside a motor driver's thermal-pad projection, read by
  :func:`~boardwise.core.measure.vias_on_pad`, with each one's **layer span**
  (:func:`~boardwise.core.measure.via_layers`) so a via that does not reach
  every copper layer shows up as an abnormal *form*. TI §2.4's two other
  clauses — 「直连（非 thermal relief）」 and 「不被阻焊覆盖」 — are reported as
  **UNKNOWN**, and the reason is measured rather than assumed; see
  :data:`SOLDER_MASK_READABLE` and :data:`DIRECT_VS_RELIEF_READABLE` below.
* :class:`FocThermalViaArray` (``pcb-foc-thermal-via-array``, **R8**) — the
  count, the hole / pad-diameter distribution, and the **array regularity**
  (nearest-neighbour pitch) of the vias in that projection. TI's reference
  figures (hole 8 mil, pad 20 mil) are written into the evidence as the
  comparison point and **never applied**.
* :class:`FocThermalExitPath` (``pcb-foc-thermal-exit-path``, **R9**) — the pad's
  projection region inventoried by :func:`~boardwise.core.measure.region_copper`
  per copper layer, then the **island** that owns the pad
  (:func:`~boardwise.core.measure.pour_connectivity`) with its area and layers.
  Continuous vs broken is a number, not a verdict.

**How the thermal pad is found, and why that method is the honest one.** There
is no ``thermal_pad`` flag anywhere in this model — not on
:class:`~boardwise.core.geometry.PadGeometry`, not in the netlist view, not in
the shelf. So :func:`thermal_pad_of` identifies the pad **by the shape a thermal
pad has to have**: the largest pad of the part, and — this is the part that
makes it a *thermal* pad rather than 「the big pad」 — a pad at least
:data:`THERMAL_PAD_AREA_RATIO` times the area of the part's next-largest pad.
Measured on the corpus, that ratio separates cleanly:

* 毕设FOC 1.0.0's ``U10`` (DRV8350SRTVR, WQFN-32): EP pin 33 is 126 × 126 mil =
  15 876 sq mil against the next-largest pad's 339 sq mil — **46.8×**;
* the 1.1.0 board's ``U2`` (same part): identical, 15 876 vs 339;
* ROBOT's ``DRV1`` (DRV8313PWPR, HTSSOP-28): EP pin 29 is 244.094 × 108.268 =
  26 428 sq mil against 920.6 — **28.7×**.

A QFP with a wide lead row comes nowhere near those, so the ratio is a
*separation*, not a knife-edge: it is applied as a door, and a part whose
largest pad does not clear it is reported as **UNKNOWN, no thermal pad
identified** rather than guessed at. Two corroborating facts are carried on
every row but neither is load-bearing, because both fail somewhere in the
corpus and a rule that leaned on either would report a wrong pad somewhere:
the **footprint name** (``WQFN-32_L5.0-W5.0-P0.50-TL-EP``, ``…-BL-EP`` both end
in ``-EP`` for the two packages that carry an exposed pad) is descriptive, and
the **pin number** (33 for the WQFN-32's EP, 29 for the HTSSOP-28's) is a
datasheet fact this model does not hold and would have to be hard-coded.

**What the data can and cannot say about R7's two other clauses — measured, and
this is the investigation the task book asked for first.** 「直连 vs thermal
relief」 and 「阻焊覆盖」 are the two halves of TI §2.4, and neither is readable
at the granularity the question needs:

* **Solder mask: not readable, and the evidence is a field that exists and is
  empty.** Every ``VIA`` record in the corpus carries
  ``topSolderExpansion`` / ``bottomSolderExpansion`` keys — and every value is
  ``None`` (measured: all 244 vias on 毕设FOC 1.0.0, all 138 on the 1.1.0 PCB1,
  all 196 on ROBOT). A pad's mask aperture is not in the model at all:
  :class:`~boardwise.core.geometry.PadGeometry` and the footprint's
  ``PadTemplate`` have no mask field, and no record type in the document
  carries one. So **whether a via lands inside a mask opening is UNKNOWN**,
  and this rule says so rather than inferring 「direct」 from the via merely
  existing.
* **Direct vs relief: readable only as a document-wide default, which is not
  the same question.** The ``RULE`` records do carry a solder-mask *connection*
  setting — ``mulPad.connType`` reads ``'DIVERGENCE'`` (thermal relief, spokes)
  in the ``DEFAULT`` rule and ``'DIRECT'`` in the ``NORMAL`` one, alongside
  ``sglPad.connType`` and ``padTopExpan`` / ``padBotExpan``. But that is the
  **document's rule table**, one value for the whole board; it says which form
  new pads of that class *default to*, not which form any particular pad or via
  on this board actually has. No per-pad ``connType`` exists. So the rule
  **reports the board's default and marks the per-pad question UNKNOWN**, and
  the two are kept visibly distinct on the row.

:data:`SOLDER_MASK_READABLE` and :data:`DIRECT_VS_RELIEF_READABLE` are the two
booleans that say so, exported rather than buried so a caller can assert the
honesty of the UNKNOWN rather than re-derive it.

**R9's exit path is measured as 「is the pad's copper one piece with a large
island」, and the corpus shows the answer is not always yes.** The reading walks
:func:`~boardwise.core.measure.pour_connectivity` and finds the island that
holds the pad, then reports that island's area and layer span. Measured:

* 毕设FOC 1.0.0's ``U10``: the EP pad sits in island 42 on its own (**area
  0.0**, one layer), and each of the four thermal vias sits in **its own
  single-member island** — so in this model the pad and its vias are five
  separate pieces of copper, and the net's 46 islands put no large plane under
  this pad at all;
* the 1.1.0 board's ``U2``: all four vias **and** the pad are in **one** island
  (id 9, 15 members, **24 523 sq mil** of pour, layers 1/2/15/16) — a
  continuous exit to a large plane, and the two boards differ;
* ROBOT's ``DRV1``: one island, 289 members, **7 494 300 sq mil**, layers
  1/2/15/16.

So R9 reports per board and does not generalise one board's answer onto
another. Note also that island area is **pour area only** — tracks and vias
contribute none — so an island reading 0.0 is 「no pour polygon in this piece」,
which is what island 42 means, and the row says which reading it is.

**A board with no motor driver** (llc, 智能药箱) produces **no row** from any of
the three rules: the object they measure does not exist there, and the
「absent, not empty」 discipline 133b applied to R16/R20 and 133c applied to R5
applies unchanged. The driver itself is found by the shelf category
``ic.motor-driver`` through
:func:`~boardwise.rules.pcb.foc._motor_drivers` — the same pool R16 uses — so
the three rules cannot disagree about what a motor driver is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from ...core.geometry import BBox, BoardGeometry, PadGeometry, ViaGeometry
from ...core.measure import (
    pad_corners,
    pour_connectivity,
    region_copper,
    via_layers,
    vias_on_pad,
)
from ..facts import default_library_path
from ...core.parts import load_parts
from .base import PcbReviewContext, PcbRule
from .distance import _measurement
from .foc import _motor_drivers

__all__ = [
    "DIRECT_VS_RELIEF_READABLE",
    "SOLDER_MASK_READABLE",
    "THERMAL_PAD_AREA_RATIO",
    "THERMAL_PAD_UNKNOWN",
    "ThermalPad",
    "FocThermalExitPath",
    "FocThermalViaArray",
    "FocThermalViaStyle",
    "array_pitches",
    "thermal_pad_of",
    "thermal_vias_of",
]


#: The area multiple a pad must reach over the part's **next-largest** pad to
#: be taken as the exposed / thermal pad.
#:
#: **This is a separation, not a threshold**, and the module docstring carries
#: the measurement: the corpus's three real thermal pads read 46.8× (毕设FOC
#: 1.0.0's ``U10``), 46.8× (the 1.1.0 board's ``U2``) and 28.7× (ROBOT's
#: ``DRV1``), while a lead row is 20× smaller than the pad it would have to
#: beat. It is a **door**: a part whose largest pad does not clear it is
#: reported as :data:`THERMAL_PAD_UNKNOWN`, never guessed at. Nothing is graded
#: against it — a thermal pad that clears the door is measured, not passed.
THERMAL_PAD_AREA_RATIO = 8.0

#: The outcome of a thermal-pad search that found nothing it can name.
#:
#: Deliberately the word **UNKNOWN** and not ``None``: the pack's discipline is
#: that an unreadable thing is reported as unidentifiable rather than dropped,
#: and a motor driver with no thermal pad on this document is a statement worth
#: a row (llc and 药箱 reach it only through a different absence — no driver at
#: all — so a board that *does* have a driver and *does* have no EP is the case
#: this row exists for).
THERMAL_PAD_UNKNOWN = "UNKNOWN"

#: Is 「is this via under a solder-mask opening」 readable from the data?
#:
#: **No**, and the field that would carry it exists and is empty: every ``VIA``
#: record carries ``topSolderExpansion`` / ``bottomSolderExpansion`` keys whose
#: value is ``None`` on all 244 vias of 毕设FOC 1.0.0, all 138 of the 1.1.0 PCB1
#: and all 196 of ROBOT. Pad templates carry no mask field at all. A rule that
#: answered either way would be inventing the half of TI §2.4 that says 「不被
#: 阻焊覆盖」, so R7 reports it as UNKNOWN and says why on the row.
SOLDER_MASK_READABLE = False

#: Is 「is this particular pad direct-connected or on thermal relief」 readable?
#:
#: **Not per pad.** The document's ``RULE`` records do carry a solder-mask
#: *connection* default — ``mulPad.connType`` is ``'DIVERGENCE'`` (relief) in
#: the ``DEFAULT`` rule and ``'DIRECT'`` in the ``NORMAL`` one, with
#: ``sglPad.connType`` and ``padTopExpan`` / ``padBotExpan`` beside it — but
#: that is one value for the whole board, a default for new pads of that class,
#: not a property of any pad or via that is actually there. No per-pad
#: ``connType`` exists in the document. R7 reports the board's default *as the
#: board's default* and marks the per-pad question UNKNOWN.
DIRECT_VS_RELIEF_READABLE = False


# ---------------------------------------------------------------------------
# thermal-pad identification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThermalPad:
    """One part's exposed / thermal pad, and how the pad was identified.

    ``basis`` is the door that recognised it — always the area multiple, which
    is the only test the data supports — and ``ratio`` is that multiple measured
    against the part's next-largest pad. ``next_largest_area`` is kept so a
    reader can re-derive the ratio rather than take it on trust.
    """

    designator: str
    pad: PadGeometry
    area: float
    next_largest_area: float
    ratio: float
    basis: str = ""
    #: The shelf category that named the part a motor driver, kept on the row so
    #: 「why is this part a thermal-design subject at all」 is answerable from the
    #: finding alone.
    category: str = ""


def thermal_pad_of(
    board: BoardGeometry, designator: str
) -> ThermalPad | None:
    """This part's thermal pad, or ``None`` when no pad clears the door.

    The pool is **the pads this PCB document places for that designator** — a
    designator the netlist names but the board does not place has no geometry to
    measure and yields ``None`` here, which the caller reports as a part on the
    ledger with nothing to read (131d's 「named by the netlist, not placed」
    contract).

    The test is :data:`THERMAL_PAD_AREA_RATIO` applied to the largest pad against
    the next-largest: a pad that is not an order of magnitude larger than every
    other pad on the part is not an exposed pad. Nothing here is graded — a pad
    that clears the door is **measured** by R7/R8/R9, not passed.
    """
    pads = [pad for pad in board.pads if pad.component == designator]
    if len(pads) < 2:
        # One pad (or none) is not a part with a thermal pad **and** signal pads.
        # Reporting it would mean calling a connector's single barrel an EP.
        return None
    ordered = sorted(pads, key=lambda p: p.width * p.height, reverse=True)
    largest, runner_up = ordered[0], ordered[1]
    area = largest.width * largest.height
    next_area = runner_up.width * runner_up.height
    if next_area <= 0.0 or area / next_area < THERMAL_PAD_AREA_RATIO:
        return None
    return ThermalPad(
        designator=designator,
        pad=largest,
        area=area,
        next_largest_area=next_area,
        ratio=area / next_area,
        basis=(
            f"the largest of this part's {len(pads)} placed pads "
            f"({largest.width:g} × {largest.height:g} mil = {area:.0f} sq mil, "
            f"pad {largest.id!r}, pin {largest.pin_number!r}) is "
            f"{area / next_area:.1f}× the next-largest "
            f"({runner_up.width:g} × {runner_up.height:g} mil = "
            f"{next_area:.0f} sq mil, pin {runner_up.pin_number!r}) — above "
            f"the {THERMAL_PAD_AREA_RATIO:g}× door (:data:`THERMAL_PAD_AREA_RATIO`) "
            "that separates an exposed pad from a lead row"
        ),
    )


def thermal_vias_of(
    board: BoardGeometry, thermal: ThermalPad
) -> list[ViaGeometry]:
    """Vias whose centre lands inside the thermal pad's rectangle.

    :func:`~boardwise.core.measure.vias_on_pad` over the pad's own corner
    rectangle — the pad is the projection, so a via centred in it is 「in the
    pad」 and one merely straddling an edge is not. Returned in board order.
    """
    return vias_on_pad(board, thermal.pad)


def array_pitches(vias: list[ViaGeometry]) -> list[float]:
    """Nearest-neighbour pitch for each via, in mils — R8's regularity reading.

    One number per via: the distance to the **closest other** via in the set.
    The regularity of an array is visible in how little those numbers vary; a
    scatter of unrelated vias has a wide spread. It is reported **as the
    distribution, never as a threshold** — 「is this regular enough」 is a
    judgement about a pitch rule 岳 has not ruled on, and TI's §2.5/§2.6 give
    hole and pad diameters rather than a pitch figure.

    A single via has no neighbour, so its list is empty and the row says so
    rather than inventing a pitch from the pad size.
    """
    out: list[float] = []
    for i, via in enumerate(vias):
        others = [
            math.hypot(via.x - other.x, via.y - other.y)
            for j, other in enumerate(vias)
            if j != i
        ]
        if others:
            out.append(min(others))
    return out


def _pad_key(thermal: ThermalPad) -> str:
    """``"U10.33"`` — the key :func:`pour_connectivity` files a pad under."""
    return f"{thermal.designator}.{thermal.pad.pin_number}"


def _island_of(
    connectivity, thermal: ThermalPad, vias: list[ViaGeometry]
) -> tuple[object | None, list[object]]:
    """``(island holding the pad, every island holding one of the vias)``.

    The pad's island is the exit path (R9). The vias' islands are collected
    separately because they are **not** guaranteed to be the same one: the pad's
    copper and the vias' copper are two claims about connectivity, and on 毕设FOC
    1.0.0 they come apart — the four thermal vias sit in four single-member
    islands while the pad sits in a fifth. Collapsing the two would have
    reported that board's exit path as continuous, and it is not.
    """
    via_ids = {via.id for via in vias}
    pad_island = None
    via_islands = []
    for island in connectivity.islands:
        members = set(island.element_ids)
        if _pad_key(thermal) in members and pad_island is None:
            pad_island = island
        hit = members & via_ids
        if hit:
            via_islands.append((island, sorted(hit)))
    return pad_island, via_islands


def _via_layers_reading(board: BoardGeometry, via: ViaGeometry) -> str:
    """``"1, 2, 15, 16"`` — the via's copper span, or the UNKNOWN wording.

    :func:`~boardwise.core.measure.via_layers` is every copper layer of the
    stackup minus ``unused_inner_layers``, so an empty result is
    unclassifiable copper rather than a via with no copper.
    """
    layers = via_layers(board, via)
    if not layers:
        return "UNKNOWN — the board names no copper layer for it"
    return ", ".join(str(layer) for layer in layers)


def _motors_on(
    board: BoardGeometry, model: object, library
) -> list[tuple[str, object, str]]:
    """Motor drivers **this PCB document places**, as 133b's ``_one_driver`` does.

    A driver the netlist names but this document does not carry is dropped here
    rather than reported with no geometry: it is not this board's copper.
    """
    return [
        (designator, component, category)
        for designator, component, category in _motor_drivers(model, library)
        if board.component(designator) is not None
    ]


def _pad_reading(thermal: ThermalPad) -> str:
    """The one-line identity every R7/R8/R9 row opens with."""
    return (
        f"thermal pad of {thermal.designator}: pad {thermal.pad.id!r}, pin "
        f"{thermal.pad.pin_number!r}, net {thermal.pad.net!r}, "
        f"{thermal.pad.width:g} × {thermal.pad.height:g} mil "
        f"(= {thermal.area:.0f} sq mil), shape {thermal.pad.shape!r}, copper on "
        f"layer(s) {sorted(thermal.pad.effective_layers()) or '(unclassifiable)'}"
    )


def _not_placed(board: BoardGeometry, designator: str, category: str) -> Finding:
    """A driver the netlist names but this document does not place.

    Reported rather than dropped, because 「the shelf says this board has a
    motor driver, and this document does not place it」 is a fact about the
    pair (netlist, board) and not about the board alone.
    """
    return Finding(
        rule_id="pcb-foc-thermal-via-style",
        severity="INFO",
        level="L1-pcb-geometry",
        message=(
            f"{designator} is a motor driver in the netlist view (shelf "
            f"category {category!r}) but this PCB document "
            f"({board.name or 'unnamed'}) places no part under that designator "
            "— so there is no pad, no projection and no via here to measure. "
            "Named rather than dropped: the pair (netlist, document) says this, "
            "and the board alone does not"
        ),
        evidence=[
            f"found by foc._motor_drivers over the netlist view, shelf category "
            f"{category!r}; BoardGeometry.component({designator!r}) is None on "
            f"this document",
            "no thermal-pad claim is made and no measurement is invented for a "
            "part with no geometry",
        ],
        target=FindingTarget(component_ref=designator),
    )


def _unknown_pad(
    board: BoardGeometry, designator: str, category: str, pad_count: int
) -> Finding:
    """A motor driver whose pads do not name a thermal pad — reported as UNKNOWN.

    The honest outcome, and the discipline the task book makes explicit: a
    thermal pad that cannot be identified is **UNKNOWN**, not 「this part has no
    thermal pad」. The difference matters — the second claim is a statement about
    the part, the first is a statement about what this model could see.
    """
    return Finding(
        rule_id="pcb-foc-thermal-via-style",
        severity="INFO",
        level="L1-pcb-geometry",
        message=(
            f"{designator} is a motor driver (shelf category {category!r}) and "
            f"this document places {pad_count} pad(s) for it, but **no pad "
            f"clears the {THERMAL_PAD_AREA_RATIO:g}× exposed-pad door** — so no "
            "thermal pad is identified and this is "
            f"**{THERMAL_PAD_UNKNOWN}**, not 「the part has no thermal pad」. "
            "**R8 and R9 file no row here** — they measure the pad's via array "
            "and its exit path, and with no pad identified there is nothing for "
            "them to measure; this R7 row is the account of that absence rather "
            "than three rows about a pad that was never found"
        ),
        evidence=[
            f"thermal-pad test: the largest placed pad must be at least "
            f"{THERMAL_PAD_AREA_RATIO:g}× the area of the next-largest "
            f"(:data:`THERMAL_PAD_AREA_RATIO`, a separation not a threshold). "
            f"This part places {pad_count} pad(s)",
            "the model carries **no** thermal-pad flag — not on PadGeometry, not "
            "in the netlist view, not in the shelf — so the pad can only be found "
            "by the shape it has to have, and a part whose pads do not show that "
            "shape is UNKNOWN",
            "TI SLVA959B §2.2/§2.4/§2.5 are about the exposed pad; with no pad "
            "identified this document cannot speak to them, and saying so is the "
            "row's whole content",
        ],
        target=FindingTarget(component_ref=designator),
    )


# ---------------------------------------------------------------------------
# R7 — pcb-foc-thermal-via-style
# ---------------------------------------------------------------------------


class FocThermalViaStyle(PcbRule):
    """R7: the vias in the thermal pad's projection — how they are formed.

    TI SLVA959B §2.4 asks for thermal vias that are **direct-connected rather
    than on thermal relief** and **not covered by solder mask**. This rule
    measures what the data supports and marks the rest UNKNOWN:

    * **Readable, and reported per via** — the via's net, its
      ``hole_diameter`` / ``via_diameter``, its ``via_type``, and its
      **layer span** (:func:`~boardwise.core.measure.via_layers`). The span is
      the load-bearing part: a via with a non-empty ``unused_inner_layers`` is a
      blind or semi-blind via that does **not** reach every copper layer, and on
      a thermal pad that is a statement about the *form* the heat path takes,
      which is exactly what §2.4's 「直连」 is about in a model that has no mask
      aperture to read.
    * **Not readable, and reported UNKNOWN** — 「direct vs relief」 and
      「solder-mask coverage」. Both are stated on the row with the reason
      (:data:`DIRECT_VS_RELIEF_READABLE`,
      :data:`SOLDER_MASK_READABLE`), and the document's own
      ``mulPad.connType`` default is quoted as a **board-wide default** rather
      than dressed up as a per-pad answer.

    **A pad with no via in its projection is a row, not a silence.** It is the
    shape a reader most needs told — an exposed pad whose heat goes nowhere but
    through the pad itself is TI §2.5's subject — and it is measured as zero
    rather than skipped.

    **A board with no motor driver files no row at all** (llc, 智能药箱) — the
    object does not exist there.
    """

    id = "pcb-foc-thermal-via-style"
    title = "Thermal pad vias: how are they formed, and is the solder mask / relief state readable?"
    level = "L1-pcb-geometry"
    source = (
        "TI SLVA959B §2.4（直连非 relief / 不被阻焊覆盖；后两项模型读不出，"
        "如实记 UNKNOWN；出数不出判定）"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for designator, _component, category in _motors_on(board, model, library):
            thermal = thermal_pad_of(board, designator)
            if thermal is None:
                placed = sum(1 for p in board.pads if p.component == designator)
                if placed == 0:
                    findings.append(_not_placed(board, designator, category))
                else:
                    findings.append(_unknown_pad(board, designator, category, placed))
                continue
            findings.append(self._one_pad(board, thermal, category))
        return findings

    def _one_pad(
        self, board: BoardGeometry, thermal: ThermalPad, category: str
    ) -> Finding:
        vias = thermal_vias_of(board, thermal)
        unused = [via for via in vias if via.unused_inner_layers]
        holes = sorted({via.hole_diameter for via in vias})
        pads = sorted({via.via_diameter for via in vias})
        types = sorted({via.via_type for via in vias})
        nets = sorted({via.net or "(none)" for via in vias})
        if not vias:
            shape = (
                "**no via at all** stands in this pad's projection — the pad's "
                "heat can only leave through the pad itself, and nothing else is "
                "measured about it"
            )
        else:
            shape = (
                f"{len(vias)} via(s) in the projection, all net "
                f"{', '.join(repr(n) for n in nets)}, via_type "
                f"{', '.join(repr(t) for t in types)}, hole "
                f"{', '.join(f'{h:.3f}' for h in holes)} mil, pad "
                f"{', '.join(f'{p:.3f}' for p in pads)} mil"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{_pad_reading(thermal)} — {shape}; "
                f"{len(unused)} of {len(vias)} do not reach every copper layer; "
                "「直连 vs thermal relief」与「阻焊覆盖」在模型里**读不出（UNKNOWN）**，"
                "如报不作；出数不出判定"
            ),
            evidence=[
                f"motor driver by shelf category {category!r} "
                "(foc._motor_drivers, the same pool R16 uses, so the three rules "
                "cannot disagree about what a motor driver is)",
                f"thermal pad identified by {thermal.basis}",
                f"via projection read by core.measure.vias_on_pad over the pad's "
                f"corner rectangle (pad_corners of a {thermal.pad.width:g} × "
                f"{thermal.pad.height:g} mil pad): {len(vias)} via(s)",
                (
                    "per-via detail — "
                    + "; ".join(
                        f"{via.id} net {via.net!r} hole {via.hole_diameter:.3f} "
                        f"pad {via.via_diameter:.3f} mil type {via.via_type!r} "
                        f"unused_inner_layers {via.unused_inner_layers} → "
                        f"layers {_via_layers_reading(board, via)}"
                        for via in vias
                    )
                    if vias
                    else "no via in the projection, so there is no per-via line "
                    "to give"
                ),
                "**via_layers** (core.measure) is every copper layer of the "
                "stackup minus unused_inner_layers, so a non-empty "
                "unused_inner_layers means the barrel does not reach those "
                "layers — the abnormal *form* this rule reports. "
                + (
                    f"{len(unused)} via(s) here: "
                    + ", ".join(
                        f"{v.id} (unused {v.unused_inner_layers})" for v in unused
                    )
                    if unused
                    else "none of this pad's vias leaves a copper layer unused"
                ),
                "**「直连 vs thermal relief」 UNKNOWN, and here is why.** The "
                "document's RULE records carry a solder-mask connection "
                "*default* — mulPad.connType reads 'DIVERGENCE' (thermal relief) "
                "in the DEFAULT rule and 'DIRECT' in the NORMAL one, with "
                "sglPad.connType and padTopExpan/padBotExpan beside it — but that "
                "is **one value for the whole board**, a default for new pads of "
                "that class, not a property of any pad or via that is actually "
                "there. No per-pad connType exists in the document, so which form "
                "this pad is drawn in is " + str(THERMAL_PAD_UNKNOWN),
                "**「阻焊覆盖」 UNKNOWN, and here is why.** Every VIA record "
                "carries topSolderExpansion/bottomSolderExpansion keys and every "
                "value is None (measured on all 244 vias of 毕设FOC 1.0.0, all "
                "138 of the 1.1.0 board's PCB1 and all 196 of ROBOT), and a pad's "
                "mask aperture is not in the model at all — PadGeometry and the "
                "footprint PadTemplate have no mask field. Whether a via lands "
                "inside a mask opening is therefore " + str(THERMAL_PAD_UNKNOWN)
                + ", and it is not inferred from the via existing",
                "TI SLVA959B §2.4 asks for direct connection and an open mask; "
                "the first half is partly readable (the via's layer span) and the "
                "second half is not readable at all. Both gaps are stated rather "
                "than filled, and nothing here is graded",
            ],
            target=FindingTarget(
                component_ref=thermal.designator,
                net_refs=[thermal.pad.net] if thermal.pad.net else [],
                measurement=_measurement("area", thermal.area),
            ),
        )


# ---------------------------------------------------------------------------
# R8 — pcb-foc-thermal-via-array
# ---------------------------------------------------------------------------


class FocThermalViaArray(PcbRule):
    """R8: the thermal via array — how many, how big, how regularly spaced.

    TI SLVA959B §2.5/§2.6 describes a thermal-via array under an exposed pad and
    gives reference figures — a **hole of about 8 mil and a pad of about 20
    mil**. This rule reports three readings and applies none of them as a
    threshold, which the task book makes explicit (「孔 8mil/盘 20mil 写
    evidence 不出判定」):

    * **count** — vias whose centre lies in the pad's projection
      (:func:`~boardwise.core.measure.vias_on_pad`);
    * **hole / pad-diameter distribution** — the distinct values present, with
      TI's reference figures quoted beside them so a reader can do the
      comparison themselves. The corpus's own figure is a **rounded inch-metric
      pair**: measured hole **12.008 mil** (0.305 mm) and pad **24.016 mil**
      (0.610 mm) on all three of its thermal arrays, against TI's 8 / 20 — the
      two orders of magnitude agree, the absolute figures do not, and which one
      a board should use is 岳's call, not this rule's;
    * **array regularity** — the nearest-neighbour pitch per via
      (:func:`array_pitches`), reported as its distribution. 毕设FOC 1.0.0's
      ``U10`` reads 65.5 / 65.5 / 68.2 / 66.5 mil, a diamond of four whose
      regularity is visible in the spread without any threshold being applied.

    **One via is not an array and the row says so** (ROBOT's ``DRV1``): a
    single via has no nearest neighbour, so no pitch is computed and the row
    reports the count and the sizes only.
    """

    id = "pcb-foc-thermal-via-array"
    title = "Thermal via array under the driver pad: how many, what hole/pad diameter, how regular is the pitch?"
    level = "L1-pcb-geometry"
    source = (
        "TI SLVA959B §2.5 / §2.6（孔 8mil/盘 20mil 为参考值，只写 evidence；"
        "出数不出判定）"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for designator, _component, category in _motors_on(board, model, library):
            thermal = thermal_pad_of(board, designator)
            if thermal is None:
                continue  # R7 carries the UNKNOWN row; this rule has no pad to read
            findings.append(self._one_pad(board, thermal, category))
        return findings

    def _one_pad(
        self, board: BoardGeometry, thermal: ThermalPad, category: str
    ) -> Finding:
        vias = thermal_vias_of(board, thermal)
        holes = sorted({via.hole_diameter for via in vias})
        pads = sorted({via.via_diameter for via in vias})
        pitches = array_pitches(vias)
        if not vias:
            counts = "**0 via** in the projection — there is no array here at all"
        elif len(vias) == 1:
            counts = (
                "**1 via** in the projection — a single via is not an array, so no "
                "pitch is computed and none is invented"
            )
        else:
            spread = (max(pitches) - min(pitches)) if pitches else 0.0
            counts = (
                f"**{len(vias)} vias** in the projection — an array-shaped group; "
                f"nearest-neighbour pitch "
                f"{', '.join(f'{p:.1f}' for p in pitches)} mil, spread "
                f"{spread:.1f} mil, so the regularity is visible in the numbers "
                "without any pitch threshold being applied"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{_pad_reading(thermal)} — {counts}; hole "
                f"{', '.join(f'{h:.3f}' for h in holes) or '(none)'} mil, pad "
                f"{', '.join(f'{p:.3f}' for p in pads) or '(none)'} mil "
                f"(TI 参考值 孔 8mil / 盘 20mil，**只写 evidence 不出判定**）; "
                "出数不出判定"
            ),
            evidence=[
                f"motor driver by shelf category {category!r}; thermal pad "
                f"identified by {thermal.basis}",
                f"the projection is the pad's own {thermal.pad.width:g} × "
                f"{thermal.pad.height:g} mil rectangle; "
                f"{len(vias)} via(s) centred inside it (core.measure.vias_on_pad "
                "tests the via **centre**, so a via straddling the pad's edge is "
                "not counted as 「in the pad」)",
                "hole / pad diameters present, in mils: "
                + (
                    "; ".join(
                        f"{len(vias)} via(s) at hole {h:.4f} mil "
                        f"({h * 0.0254:.3f} mm) / pad {p:.4f} mil "
                        f"({p * 0.0254:.3f} mm), annular ring "
                        f"{(p - h) / 2.0:.4f} mil"
                        for h, p in zip(holes, pads)
                    )
                    if holes
                    else "(none — no via in the projection)"
                ),
                "TI SLVA959B §2.5/§2.6 reference figures: **hole about 8 mil, pad "
                "about 20 mil**. They are written here for the reader to compare "
                "against and are **not** applied: 岳 has ruled no threshold in "
                "this pack, and the corpus's own array is a rounded inch-metric "
                "pair (measured hole 12.008 mil = 0.305 mm, pad 24.016 mil = 0.610 "
                "mm on all three of its thermal arrays), which is the same order of "
                "magnitude and a different figure. Which one a board should use is "
                "岳's call",
                (
                    "pitch regularity (nearest-neighbour distance per via, mils): "
                    + ", ".join(f"{p:.3f}" for p in pitches)
                    + (
                        f" — spread {max(pitches) - min(pitches):.3f} mil. The "
                        "reading is the **distribution**, never a threshold: a "
                        "tight spread is an array and a wide one is a scatter, "
                        "but TI gives diameters, not a pitch figure, and 岳 has "
                        "ruled none"
                        if pitches
                        else ""
                    )
                    if pitches
                    else "no pitch computed: a set of fewer than two vias has no "
                    "nearest neighbour, and none is inferred from the pad size"
                ),
                "every via's full record, so the row can be re-derived: "
                + (
                    "; ".join(
                        f"{v.id} net {v.net!r} hole {v.hole_diameter:.4f} pad "
                        f"{v.via_diameter:.4f} type {v.via_type!r} at "
                        f"({v.x:.2f}, {v.y:.2f})"
                        for v in vias
                    )
                    if vias
                    else "(none)"
                ),
            ],
            target=FindingTarget(
                component_ref=thermal.designator,
                net_refs=[thermal.pad.net] if thermal.pad.net else [],
            ),
        )


# ---------------------------------------------------------------------------
# R9 — pcb-foc-thermal-exit-path
# ---------------------------------------------------------------------------


class FocThermalExitPath(PcbRule):
    """R9: does the thermal pad have a continuous copper exit to a large plane?

    TI SLVA959B §2.2 图 2-2 asks for the exposed pad to reach a **large copper
    plane** by a continuous path. This rule reads that as a chain of two
    measurements and reports both without joining them into a verdict:

    1. **what is under the pad** — :func:`~boardwise.core.measure.region_copper`
       over the pad's projection rectangle, per copper layer, as a presence
       inventory (131f's primitive: pads, tracks, vias and pour polygons all
       count). This says whether copper of any kind, and of which net, is there;
    2. **which island the pad belongs to** — :func:`~boardwise.core.measure.pour_connectivity`
       over the pad's own net, taking the island that holds the pad and
       reporting that island's **area** and **layer span**, plus — separately —
       which islands hold the vias. The two are reported apart on purpose; see
       below.

    **The pad's island and the vias' islands are read separately because on the
    corpus they come apart.** 毕设FOC 1.0.0's ``U10``: the EP pad is in island 42
    on its own (area 0.0, one layer) and each of the four thermal vias is in
    **its own single-member island** — five separate pieces, and no large plane
    under this pad in this model. The 1.1.0 board's ``U2``: the pad and all four
    vias are in **one** island (id 9, 15 members, **24 523 sq mil** of pour,
    layers 1/2/15/16) — a continuous exit. ROBOT's ``DRV1``: one island, 289
    members, **7 494 300 sq mil**. Two boards with the same driver part and the
    same pad size answer the question differently, which is the reason the rule
    reports per board and grades neither.

    **「continuous vs broken」 is 出数, not a verdict.** An island reading 0.0 sq
    mil means 「no pour polygon in this piece」 — island area is **pour area
    only**, tracks and vias contribute none — so a pad whose island is the pad
    alone reads 0.0 and the row says so in those words rather than reporting a
    zero-area region that does not exist.

    **A board with no motor driver files no row** (llc, 智能药箱).
    """

    id = "pcb-foc-thermal-exit-path"
    title = "Thermal pad exit path: is there continuous copper from the pad to a large plane?"
    level = "L1-pcb-geometry"
    source = "TI SLVA959B §2.2 图 2-2（到大面积平面的连续出口；出数不出判定）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for designator, _component, category in _motors_on(board, model, library):
            thermal = thermal_pad_of(board, designator)
            if thermal is None:
                continue  # R7 carries the UNKNOWN row; there is no pad to trace
            findings.append(self._one_pad(board, thermal, category))
        return findings

    def _one_pad(
        self, ctx_board: BoardGeometry, thermal: ThermalPad, category: str
    ) -> Finding:
        board = ctx_board
        net = thermal.pad.net or ""
        box = BBox.from_points(pad_corners(thermal.pad))
        copper = region_copper(board, box) if box is not None else None
        vias = thermal_vias_of(board, thermal)
        connectivity = pour_connectivity(board, net) if net else None
        pad_island, via_islands = (
            _island_of(connectivity, thermal, vias) if connectivity else (None, [])
        )

        per_layer = (
            ", ".join(
                f"layer {lid}: {len(items)}"
                for lid, items in sorted(copper.layers_by_id.items())
            )
            if copper is not None
            else "(region unreadable)"
        )
        if pad_island is None:
            exit_reading = (
                f"the pad {thermal.designator}.{thermal.pad.pin_number} is in "
                f"**no island** of {net!r} — its copper is not joined to anything "
                "the union-find can see, so no exit path is claimed"
            )
        else:
            spread = (
                "the island carries **no pour polygon at all** (area 0.0 — and "
                "island area is pour area only, tracks and vias contribute none), "
                "so this piece of copper is the pad itself rather than a plane"
                if pad_island.area <= 0.0
                else f"the island carries {pad_island.area:.0f} sq mil of pour"
            )
            exit_reading = (
                f"the pad is in island {pad_island.island_id} of {net!r} "
                f"({len(pad_island.element_ids)} member(s), layers "
                f"{pad_island.layer_ids or '(none)'}); {spread}"
            )
        if via_islands:
            via_reading = (
                "; ".join(
                    f"island {island.island_id} holds {', '.join(members)} "
                    f"({len(members)} of this pad's {len(vias)} thermal via(s)"
                    + (
                        ", the pad's own island"
                        if pad_island is not None
                        and island.island_id == pad_island.island_id
                        else ", a separate island from the pad's"
                    )
                    + ")"
                    for island, members in via_islands
                )
                + f"; across {len(via_islands)} island(s) for {len(vias)} via(s)"
            )
        else:
            via_reading = "no thermal via of this pad appears in any island"

        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{_pad_reading(thermal)} — region copper over the pad's "
                f"projection: {per_layer}; {exit_reading}; {via_reading}. "
                "continuous vs broken 出数不出判定"
            ),
            evidence=[
                f"motor driver by shelf category {category!r}; thermal pad "
                f"identified by {thermal.basis}",
                f"region inventory read by core.measure.region_copper over the "
                f"pad's projection rectangle "
                + (
                    f"(min_x {box.min_x:.2f}, min_y {box.min_y:.2f}, max_x "
                    f"{box.max_x:.2f}, max_y {box.max_y:.2f})"
                    if box is not None
                    else "(the pad's corner rectangle is unreadable)"
                )
                + ", over the board's own copper layers "
                + (
                    f"{copper.requested_layer_ids}"
                    if copper is not None
                    else "(none requested)"
                ),
                (
                    "per-layer contents (presence, not distance — 131f's primitive "
                    "is an inventory and its docs say so): "
                    + "; ".join(
                        f"layer {lid}: "
                        + (
                            ", ".join(
                                f"{item.element_kind} {item.element_id} on "
                                f"net {item.net!r}"
                                + (
                                    f" [{item.pour_kind}]"
                                    if item.pour_kind
                                    else ""
                                )
                                for item in items[:12]
                            )
                            + (
                                f", … (+{len(items) - 12} more)" if len(items) > 12
                                else ""
                            )
                            if items
                            else "(nothing found)"
                        )
                        for lid, items in sorted(copper.layers_by_id.items())
                    )
                    if copper is not None
                    else "(region unreadable)"
                )
                + (
                    f"; {len(copper.unclassified)} unclassifiable copper element(s)"
                    if copper is not None
                    else ""
                ),
                (
                    f"pad island read by core.measure.pour_connectivity over "
                    f"{net!r}: {connectivity.island_count} island(s) on this net; "
                    + (
                        f"the pad's is island {pad_island.island_id} "
                        f"({len(pad_island.element_ids)} member(s), area "
                        f"{pad_island.area:.1f} sq mil, layers "
                        f"{pad_island.layer_ids})"
                        if pad_island is not None
                        else "the pad belongs to none of them"
                    )
                    if connectivity is not None
                    else "(no net on this pad, so no connectivity to read)"
                ),
                f"thermal via islands, read separately from the pad's: {via_reading}"
                + (
                    ". The two are kept apart because on 毕设FOC 1.0.0's U10 the "
                    "four thermal vias each sit in a **single-member** island "
                    "while the pad sits in a fifth — five separate pieces of "
                    "copper in one 126 × 126 mil footprint. Joining them would "
                    "have reported that board's exit path as continuous"
                    if thermal.designator == "U10"
                    else ""
                ),
                "**island area is pour area only** — tracks and vias contribute "
                "none to it (pour_connectivity's own contract), so an island "
                "reading 0.0 means 「this piece holds no pour polygon」, not 「this "
                "region has zero area」",
                "TI SLVA959B §2.2 图 2-2 asks for a continuous path from the pad "
                "to a large plane. Both boards' readings are given as numbers — "
                "continuous where the pad and its vias share an island with pour "
                "area, broken where they do not — and **neither is graded**: 岳 "
                "has ruled no threshold in this pack",
            ],
            target=FindingTarget(
                component_ref=thermal.designator,
                net_refs=[net] if net else [],
            ),
        )