"""What copper lies **under** a microcontroller's crystal (task 131f).

The MCU package's earlier sticks all read the crystal from *outside*: 131d
(:mod:`boardwise.rules.pcb.crystal`) measured the crystal's pads against the
MCU's oscillator pins and its two load capacitors, every number a **distance
along the board**. This stick looks at the same crystal from the other side —
straight **down through the board** — and asks one question: what copper is
underneath it.

**Why the question exists.** A crystal oscillator is sensitive to copper and
stray capacitance in its vicinity; the usual house practice is a keepout ring of
no copper, no plane, on every layer under and around the crystal and its load
capacitors. Nothing in this repository stated that practice, and this module
does not invent a rule from it: 岳 has ruled no keepout radius, and a rule that
guessed one would put a threshold in the ledger that nobody decided. So the
rule does what 131b–131e all did — **it reports the measurement and withholds
the judgement**: the rows enumerate the copper under each layer and the evidence
states plainly that a keepout decision is 待裁.

**Why the module could not exist before this stick.** The board's *plane*
copper was invisible to every consumer. ``POUR`` records — the pour **region**
as the editor holds it, carrying its own ``netName`` and ``layerId`` in board
coordinates — were counted in ``stats.unconsumed_types`` and dropped: 27 on
毕设FOC 1.0.0, 3 on ROBOT, 4 on 药箱. 131f's first step parses them into
``kind="pour"`` polygons, and the inventory below is the first reader of them.
Without that, the honest answer on 1.0.0 would have been 「nothing on the bottom
layer」 while an ``AGND`` plane 500 square mils wide sits exactly under ``X1`` —
the kind of wrong silence a rule must never produce.

**The measurement, and the seam that makes it not-a-verdict.** The region is
the crystal's **own pad bbox**, expanded by :data:`CRYSTAL_REGION_MARGIN_MIL` on
every side, and
:func:`boardwise.core.measure.region_copper` inventories what is inside it
layer by layer. :data:`CRYSTAL_REGION_MARGIN_MIL` is **a default, not a
measurement** — no document in the corpus states a crystal keepout radius, so
the constant is named, exported, and quoted next to every row as 待裁. It is the
one number in this module the tool did not read off anything.

**No verdict, no threshold, every row ``INFO``** — the seam 131b through 131e
all left open, unchanged here.
"""

from __future__ import annotations

from ..base import Finding, FindingTarget
from ...core.geometry import BBox, BoardGeometry
from ...core.measure import pad_corners, read_stackup, region_copper
from ...core.parts import load_parts
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .crystal import _mcu_oscillators, is_crystal_member

__all__ = [
    "CRYSTAL_REGION_MARGIN_MIL",
    "McuCrystalKeepout",
    "crystal_region",
    "crystal_designators",
]


#: How far the crystal's keepout region is grown beyond its own pad bbox, in
#: mils, on **every** side.
#:
#: **A default, not a measurement, and 待裁.** No document in the corpus states a
#: crystal keepout radius, so this constant is the module's one chosen number and
#: it is named, exported and quoted on every row rather than buried in the
#: geometry. It is deliberately **modest** (0.25 mm): large enough that the
#: copper actually sitting under the part is inside the region whatever the
#: pad-to-edge convention, small enough that it does not manufacture a finding
#: on a board whose plane merely comes near. A later batch that gets a ruling
#: replaces this constant and nothing else — the region is the only place it is
#: read.
CRYSTAL_REGION_MARGIN_MIL = 9.84


def crystal_region(board: BoardGeometry, designator: str) -> BBox | None:
    """The keepout region of one placed crystal: its pad bbox plus the margin.

    The bbox is built from :func:`~boardwise.core.measure.pad_corners` of
    **every** pad the crystal places, not from its placement point: the four
    pads are what the board actually has copper there, and a crystal rotated
    90° has a different footprint box than one at 0° even though its origin is
    the same point.

    ``None`` when the crystal is not placed on this PCB document, or places no
    pad with a usable corner set — the same "absent geometry is not an error"
    discipline every other measure reader honours.
    """
    corners: list = []
    for pad in board.pads_for_component(designator):
        corners.extend(pad_corners(pad))
    box = BBox.from_points(corners)
    if box is None:
        return None
    margin = CRYSTAL_REGION_MARGIN_MIL
    return BBox(
        box.min_x - margin,
        box.min_y - margin,
        box.max_x + margin,
        box.max_y + margin,
    )


def crystal_designators(model: object, board: BoardGeometry, library) -> list[str]:
    """Every crystal the board places, found the way 131d found it.

    The crystal set is **not** re-derived here: 131d's
    :func:`~boardwise.rules.pcb.crystal.is_crystal_member` is the one sieve (a
    part's value naming a frequency, or its footprint naming the crystal
    package — the shelf states no crystal category, so that two-signal match is
    the acknowledged fragile step), and this rule asks it for the same answer
    rather than adding a second, subtly different way of recognising a crystal.

    The walk reuses 131d's own :func:`~boardwise.rules.pcb.crystal.
    _mcu_oscillators` — the same reader ``pcb-mcu-crystal-placement`` uses, over
    the same exact-MPN-then-LCSC shelf lookup, so the three rules cannot
    disagree about which parts are MCUs or which of their nets are oscillator
    nets. ``_mcu_oscillators`` and the shelf lookup it wraps are private to
    :mod:`boardwise.rules.pcb.crystal` and imported across the package rather
    than copied: this rule is a second reader of that one answer, which is the
    same discipline :mod:`boardwise.rules.pcb.mcureset` follows in importing
    131d's ``MCU_CATEGORIES``.
    """
    found: list[str] = []
    nets = getattr(model, "nets", {}) or {}
    components = getattr(model, "components", {}) or {}
    for osc in _mcu_oscillators(model, library):
        for net in sorted(osc.pins_by_net):
            net_obj = nets.get(net)
            for owner, _pin in (getattr(net_obj, "pins", None) or []):
                designator = str(owner)
                if designator in found:
                    continue
                if designator not in components:
                    continue
                if not is_crystal_member(model, designator):
                    continue
                if board.component(designator) is None:
                    continue  # named by the netlist, not carried by this document
                found.append(designator)
    return sorted(found)


def _spelled(item) -> str:
    """One inventory row as the ledger reads it: ``kind id @ net``."""
    text = f"{item.element_kind} {item.element_id}"
    if item.pour_kind:
        text += f" (kind={item.pour_kind})"
    return f"{text} @ {item.net or '(no net)'}"


class McuCrystalKeepout(PcbRule):
    """What copper lies under each MCU's crystal, layer by layer.

    One row per **copper layer**, per crystal:

    1. the crystal is found the way ``pcb-mcu-crystal-placement`` finds it — an
       ``ic.mcu`` part's oscillator net, and a member of that net the documented
       two-signal sieve reads as a frequency reference;
    2. the region is the crystal's pad bbox grown by
       :data:`CRYSTAL_REGION_MARGIN_MIL` on every side
       (:func:`crystal_region`);
    3. each copper layer from :func:`~boardwise.core.measure.read_stackup` is
       asked separately through
       :func:`~boardwise.core.measure.region_copper`, which answers 「what is
       inside this rectangle」 — pads, tracks, vias and pour polygons, each
       filed under the copper it occupies.

    **A layer with copper and a layer without are both rows.** 「Layer 2 carries
    one ``AGND`` plane under this crystal」 and 「layer 2 carries nothing here」
    are the two halves of the keepout question, and printing only the first would
    make a board with a clean bottom look identical to one never measured. The
    empty layers are named with their layer id and their layer name.

    **No verdict.** Every row is ``INFO`` and there is no keepout radius, no
    plane-ban and no allowed-copper number in this module; see the head. The one
    thing the rule asserts is a **measurement**: what is there.

    ``llc_board.epro2`` produces nothing at all, because it places no part the
    shelf calls an MCU and therefore no crystal — the same silence 131d and 131e
    already established for that board.
    """

    id = "pcb-mcu-crystal-keepout"
    title = "What copper lies under each MCU's crystal, layer by layer"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf on the same contract 131b
        through 131e honour. A shelfless crystal is still recognised
        (:func:`~boardwise.rules.pcb.crystal.is_crystal_member` reads the part's
        own words), and a shelfless board has no ``ic.mcu`` part at all, so a
        shelfless run is silent rather than wrong.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        layers = [info.layer_id for info in read_stackup(board).copper_layers]
        if not layers:
            return []
        findings: list[Finding] = []
        for crystal in crystal_designators(model, board, library):
            region = crystal_region(board, crystal)
            if region is None:
                continue
            component = (getattr(model, "components", {}) or {}).get(crystal)
            identity = [
                f"{crystal} recognised as a crystal by 131d's documented "
                f"two-signal sieve (value naming a frequency, or footprint "
                f"naming the crystal package) — the shelf states no crystal "
                f"category, so that step is the acknowledged fragile one; value "
                f"{str(getattr(component, 'value', '') or '')!r}, footprint "
                f"{str(getattr(component, 'footprint', '') or '')!r}",
                f"region = the crystal's own pad bbox "
                f"({region.min_x:.1f}, {region.min_y:.1f}) .. "
                f"({region.max_x:.1f}, {region.max_y:.1f}) mil, grown by "
                f"{CRYSTAL_REGION_MARGIN_MIL} mil on every side — that margin is "
                "a **default, not a measurement** (no document in the corpus "
                "states a crystal keepout radius), so it is 待裁",
                "read through core.measure.region_copper, which answers 「what "
                "is inside this rectangle」 and **not** 「how far is it from "
                "this pad」: a shape sitting inside a pour's outline has an "
                "unmeasurable capsule distance in the clearance engine "
                "(math.inf, 125b's documented blind spot), so the inventory uses "
                "point-in-box / polygon-overlap semantics instead",
                "measured, not judged — no keepout radius, no plane-ban and no "
                "allowed-copper threshold is in force; 岳 has ruled none, so this "
                "row states what copper is there and stops",
            ]
            for layer_id in layers:
                findings.append(
                    self._layer_row(
                        board, crystal, region, layer_id, identity
                    )
                )
        return findings

    def _layer_row(
        self,
        board: BoardGeometry,
        crystal: str,
        region: BBox,
        layer_id: int,
        identity: list[str],
    ) -> Finding:
        """One copper layer's account of what sits under one crystal."""
        report = region_copper(board, region, [layer_id])
        items = report.layers_by_id.get(layer_id, [])
        layer_name = board.layer_name(layer_id) or f"layer {layer_id}"
        others = (
            f"{item.element_kind} {item.element_id} @ {item.net or '(no net)'}"
            for item in report.unclassified
        )
        unclassified_note = (
            [
                f"elements whose copper layers could not be classified and are "
                f"therefore filed under no layer at all: "
                f"{', '.join(others)}"
            ]
            if report.unclassified
            else []
        )
        if items:
            pours = [item for item in items if item.element_kind == "pour"]
            listed = "; ".join(_spelled(item) for item in items)
            message = (
                f"{crystal}'s region carries **{len(items)}** copper element(s) "
                f"on {layer_name}: {listed}"
                + (
                    f" — including {len(pours)} pour region(s) "
                    f"({', '.join(item.net or '(no net)' for item in pours)})"
                    if pours
                    else " — no pour region on this layer inside the region"
                )
                + " — inventory only, no keepout threshold is in force"
            )
        else:
            message = (
                f"{crystal}'s region carries **no** copper on {layer_name} — "
                "an empty layer is half the keepout answer, so it is printed "
                "rather than skipped; inventory only, no keepout threshold is "
                "in force"
            )
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=message,
            evidence=[
                *identity,
                f"layer {layer_id} ({layer_name}) asked on its own, as 131f's "
                f"per-layer contract requires: {len(items)} element(s)",
                f"elements found on this layer: {listed if items else '(none)'}",
                *unclassified_note,
                *(
                    [
                        f"region asked: ({region.min_x:.1f}, {region.min_y:.1f}) "
                        f".. ({region.max_x:.1f}, {region.max_y:.1f}) mil "
                        f"= {region.width:.1f} x {region.height:.1f} mil"
                    ]
                ),
                *(
                    [
                        f"overlap bbox (region ∩ element bbox) in mil: "
                        + "; ".join(
                            f"{item.element_id} "
                            f"({item.overlap_bbox.width:.1f} x "
                            f"{item.overlap_bbox.height:.1f})"
                            for item in items
                            if item.overlap_bbox is not None
                        )
                    ]
                    if any(item.overlap_bbox is not None for item in items)
                    else []
                ),
            ],
            target=FindingTarget(component_ref=crystal),
        )
