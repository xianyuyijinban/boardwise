"""What copper lies **under** a microcontroller's crystal (task 131f).

The MCU package's earlier sticks all read the crystal from *outside*: 131d
(:mod:`boardwise.rules.pcb.crystal`) measured the crystal's pads against the
MCU's oscillator pins and its two load capacitors, every number a **distance
along the board**. This stick looks at the same crystal from the other side —
straight **down through the board** — and asks one question: what copper is
underneath it.

**Why the question exists.** A crystal oscillator is sensitive to copper and
stray capacitance in its vicinity; the usual house practice is a keepout ring of
no copper of *other nets*, on every layer under and around the crystal and its
load capacitors. The rule found that practice **unruled** for as long as 岳 had
not spoken, and reported the inventory with the judgement withheld; his
**2026-10-11** ruling supplies the judgement:
**「以内 INFO、以外 WARN」** — copper that is the crystal's **own** (its pads, and
tracks/vias on the nets those pads sit on) keeps its ``INFO`` measurement, and
**foreign-net copper inside the keepout region is a ``WARN``**. Measured on the
corpus that line is sharp and small: 毕设FOC 1.0.0's PCB1 carries an ``AGND``
pour under ``X1`` (the case this module has measured since 131f) and 1.1.0's
PCB1 carries ``IA+`` / ``IB+`` tracks under its own ``X1`` — the phase-current
sense pair routed under the crystal — while ROBOT's ``X2``, 药箱's ``X1`` and
llc's (no crystal at all) stay ``INFO``.

**The reading, and the alternative it rejects** (stated because it is a real
choice, not a detail): 「foreign net」 is judged by the copper's **net**, read
off the same inventory the row prints. The stricter reading — 「no copper at all
inside the region」 — would file a WARN against the crystal's own escaping
tracks and its own ground stitching, i.e. against copper the part cannot exist
without, and the looser one — 「any non-pad copper」 — would do the same. The
net reading keeps the crystal's own copper as INFO and still catches exactly
what the keepout is about: **someone else's** copper — a plane or a trace of
another net — under the part. An element whose net the model does not state is
**UNKNOWN** and is named in the evidence rather than graded either way.

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
the constant is named, exported, and quoted next to every row — and 岳's
2026-10-11 ruling **kept its value** (9.84 mil) while making the presence of a
foreign net inside it a graded thing.

**The verdict, and where it does not reach.** A layer carrying foreign copper is
``WARN``; a layer carrying only the crystal's own copper, or nothing, is
``INFO``. Nothing about *which* layer the crystal sits on is claimed, and the
margin is still a default rather than a datasheet figure: a board whose keepout
should be wider is a board this rule under-reports, which the row says.
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
    "CRYSTAL_KEEPOUT_RULING",
    "CRYSTAL_REGION_MARGIN_MIL",
    "McuCrystalKeepout",
    "crystal_region",
    "crystal_designators",
]


#: How far the crystal's keepout region is grown beyond its own pad bbox, in
#: mils, on **every** side.
#:
#: **A default, not a measurement — but a graded one since 2026-10-11.** No
#: document in the corpus states a crystal keepout radius, so this constant is
#: the module's one chosen number and it is named, exported and quoted on every
#: row rather than buried in the geometry. It is deliberately **modest**
#: (0.25 mm): large enough that the copper actually sitting under the part is
#: inside the region whatever the pad-to-edge convention, small enough that it
#: does not manufacture a finding on a board whose plane merely comes near.
#: 岳's 2026-10-11 ruling **kept the number and made it grade**
#: (:data:`CRYSTAL_KEEPOUT_RULING`): foreign-net copper inside the region is a
#: WARN, the crystal's own copper is INFO, and a later batch that gets a real
#: keepout radius replaces this constant and nothing else — the region is the
#: only place it is read.
CRYSTAL_REGION_MARGIN_MIL = 9.84

#: The ruling that turns the inventory into a verdict — 岳 **2026-10-11 裁**.
#:
#: 「晶振净空（焊盘外扩 9.84 mil）以内 INFO、以外 WARN」, read the way this module
#: reads it: **the crystal's own copper** (its pads and the tracks/vias on the
#: nets those pads sit on) keeps the INFO measurement, and **another net's
#: copper** inside the region is the WARN. Quoted on every row, so a reader can
#: act on the row without reading this file.
CRYSTAL_KEEPOUT_RULING = (
    "岳 2026-10-11 裁：晶振净空区（焊盘外扩 9.84 mil）内 **info = 晶振自身铜（其"
    "焊盘、以及其焊盘所在网上的走线/过孔）**，**warn = 别网铜（铺铜/走线/过孔/别的"
    "器件的焊盘）**；空层与只有自身铜的层仍是 INFO 测量行"
)


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

    **The verdict (岳 2026-10-11).** A layer whose region carries copper **on a
    net the crystal's own pads do not sit on** is a ``WARN`` — that is the
    keepout breach the module has been measuring since 131f (1.0.0's ``AGND``
    pour under ``X1``, 1.1.0's ``IA+``/``IB+`` tracks under its own ``X1``). The
    crystal's own copper (its pads, and tracks/vias on the nets those pads sit
    on) leaves the row an ``INFO`` measurement, as does an empty layer: the part
    cannot exist without its own connections, and filing against them would make
    every crystal on every board a finding. An element whose net the inventory
    cannot state is named as UNKNOWN and graded neither way. See
    :data:`CRYSTAL_KEEPOUT_RULING`.

    ``llc_board.epro2`` produces nothing at all, because it places no part the
    shelf calls an MCU and therefore no crystal — the same silence 131d and 131e
    already established for that board.
    """

    id = "pcb-mcu-crystal-keepout"
    title = "What copper lies under each MCU's crystal, layer by layer"
    level = "L1-pcb-geometry"
    source = (
        "house rule（岳 2026-10-11 裁：净空区内**别网铜** WARN、晶振自身铜与空层 "
        "INFO；外扩值 9.84 mil 沿用既有建议值）"
    )

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
            # 岳 2026-10-11: 「以内」 is judged by **net** — the nets this
            # crystal's own pads sit on are its own copper, and anything else in
            # the region is foreign. Read off the board's own pads rather than
            # off the netlist view, so the identity of the crystal's copper is the
            # copper the region query actually sees.
            own_nets = frozenset(
                str(pad.net)
                for pad in board.pads_for_component(crystal)
                if getattr(pad, "net", None)
            )
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
                "states a crystal keepout radius); 岳 2026-10-11 裁 **kept the "
                "value** and made foreign-net copper inside the region grade",
                "read through core.measure.region_copper, which answers 「what "
                "is inside this rectangle」 and **not** 「how far is it from "
                "this pad」: a shape sitting inside a pour's outline has an "
                "unmeasurable capsule distance in the clearance engine "
                "(math.inf, 125b's documented blind spot), so the inventory uses "
                "point-in-box / polygon-overlap semantics instead",
                CRYSTAL_KEEPOUT_RULING,
                "the crystal's own nets — the nets its own pads sit on — are "
                + (
                    ", ".join(repr(n) for n in own_nets)
                    if own_nets
                    else "(none stated by this document's pads)"
                )
                + "; copper on those nets is the crystal's own and stays an "
                "INFO measurement, as 岳's ruling has it. A plate or trace of "
                "**another** net inside the region is the keepout breach the "
                "ruling makes a WARN",
            ]
            for layer_id in layers:
                findings.append(
                    self._layer_row(
                        board, crystal, region, layer_id, identity, own_nets
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
        own_nets: frozenset[str],
    ) -> Finding:
        """One copper layer's account of what sits under one crystal.

        The severity is 岳's 2026-10-11 ruling: ``WARN`` when the region carries
        copper on a net the crystal's own pads do not sit on (「以外 WARN」),
        ``INFO`` when it carries only the crystal's own copper or nothing at all
        (「以内 INFO」). Elements whose net the inventory cannot state are counted
        separately and graded neither way — UNKNOWN is not a breach.
        """
        report = region_copper(board, region, [layer_id])
        items = report.layers_by_id.get(layer_id, [])
        layer_name = board.layer_name(layer_id) or f"layer {layer_id}"
        foreign = [
            item for item in items
            if item.net is not None and str(item.net) not in own_nets
        ]
        unstated = [item for item in items if item.net is None]
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
            )
        else:
            message = (
                f"{crystal}'s region carries **no** copper on {layer_name} — "
                "an empty layer is half the keepout answer, so it is printed "
                "rather than skipped"
            )
        if foreign:
            message += (
                f" — **WARN**：其中 {len(foreign)} 件是**别网铜**（"
                + ", ".join(
                    f"{item.element_kind} {item.element_id} @ {item.net}"
                    for item in foreign
                )
                + f"），落在晶振净空区（外扩 {CRYSTAL_REGION_MARGIN_MIL} mil）内；"
                "岳 2026-10-11 裁：以外 WARN"
            )
        else:
            message += (
                f" — 区内没有别网铜（晶振自身网："
                + (", ".join(repr(n) for n in sorted(own_nets)) or "(无)")
                + f"；网不明的件 {len(unstated)} 件按 UNKNOWN 不计判定）；"
                "岳 2026-10-11 裁：以内 INFO，本行维持测量"
            )
        if unstated:
            message += (
                f"；另有 {len(unstated)} 件**网不明**的铜（"
                + ", ".join(
                    f"{item.element_kind} {item.element_id}" for item in unstated
                )
                + "），UNKNOWN 不作判定"
            )
        return Finding(
            rule_id=self.id,
            severity="WARN" if foreign else "INFO",
            level=self.level,
            message=message,
            evidence=[
                *identity,
                f"layer {layer_id} ({layer_name}) asked on its own, as 131f's "
                f"per-layer contract requires: {len(items)} element(s)",
                f"elements found on this layer: {listed if items else '(none)'}",
                "the ruling's two sides, applied to this layer: foreign-net "
                f"copper = {len(foreign)} element(s) → "
                f"{'WARN' if foreign else 'none'}; the crystal's own-net copper "
                f"and unstated-net elements are not graded",
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
