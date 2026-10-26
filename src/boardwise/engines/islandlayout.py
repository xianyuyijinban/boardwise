"""One island's **local picture** — the 520k/520l shape, and nothing wired to it.

`docs/multi-island-design.md` §5 gives this stage one job: "每岛布局（复用
chain+shelf），每岛出一个内嵌小图".  This module is the second half of that sentence
only — it computes an island's local drawing, and since 536 it **is** the stage
`drawcompiler` calls for a declared island page: `_try_island_variants` builds
the blocks here, packs them, and hands the packed `LayoutPlan` to the gate.  It
is **not** a multi-group assembler — it does not decide which islands belong to
which group, it does not place two groups on one sheet, and it does not own the
partition (520j's `islands` does); a page of several groups is the later
assembler's job, and `drawcompiler` refuses one until it exists.

Why it is not `chain+shelf` (route P1, measured in
``evidence/520k/probes/10_p1_feasibility.py``): that solver is driven by a
`GrammarResult`, and a `_Context` cannot be built for a fragment of a flyback
without fabricating one — `_prepare` reads `binding.bindings` for the chain, the
slot kinds and the accepted poses, and the flyback grammar refuses a fragment
(113's five-module split).  Filtering the *whole page's* real context down to one
island is the honest alternative, and it was measured: it raises
``KeyError`` for four of the five islands at ``drawcompiler.py:5083``
(``_pin_direction`` -> ``poses[part_id]``), because a branch's anchor is a chain
part of the *whole page* — D1 hangs on T1, C11 on R7, R7 on D3, C10 on R5.  The
one island that survives (`bridge`) is two chain parts with no branches at all.

So this is route **P2**: a small local placer.  It does exactly four things, and
each is stated as a rule rather than tuned per island:

1. **every part stands beside the pin it serves.**  The island's **anchor** — the
   3-pin-or-more part its own signal nets touch most often (`anchor_of`, `DESIGN`
   §1.1) — sits at the local origin; every other part hangs off the pin it shares
   with the part nearer the anchor, at ``tip(served pin) + that pin's own outward
   direction * lead``, posed so its own serving pin points back at that pin
   (`place_service_tree`, §1.3-§1.4).  The two pins are coaxial, so the link
   between them is a straight stub.  Parts of one library symbol on one side of
   one father make a **row** and are laid out at a derived pitch (`pack_rows`,
   §3).  This replaced 520k/520n's hub-and-ring, which is the shape 岳 threw out
   on 2026-10-20: 「不是摆一个环让它看起来很紧凑，根本不是给人类看的东西」.
2. **wire this island's segment of every net — crossing or not.**  A net with two
   pins or more *here* is drawn as a Manhattan polyline, whatever the net does
   elsewhere.  This is 岳's second ruling (2026-10-20) read the right way round:
   按段算, not 按网算.
3. **name the crossing segments at their boundary.**  Every crossing net gets
   **exactly one** stub + name in this island (§:func:`_add_boundary_names`), at
   the end of the segment that faces outward.  Two islands naming the same net are
   one net — that is `岛间名字接`, and it is also how a three-island net merges.
   Since 530A the name is a **flag** for a rail/ground net and a **label** for a
   signal (S-16: 「地/电源一律旗标，不拉母线」), and one flag may gather the island's
   several pins of that rail — 岳 2026-10-20: 「一个旗标可汇聚多个就近引脚」.  A net
   with one pin and no second end anywhere is named the same way, with a lint in
   the block's own notes (岳's ruling of the same day; :meth:`IslandNet.single_pin`).
4. **text beside the part, always level.**  A part's reference goes **above** its
   own box, its value **below**, both left-aligned and never rotated (S-20), with
   no direction search: S-21's two ways out of a collision — hide the value, or
   print it past its row's outward end — are :func:`_add_texts`' whole repertoire.
   Since **532** the first of those two is **gated by the part's kind** (岳
   2026-10-21): a resistor's, capacitor's, inductor's or IC's value is never hidden
   and its part has to be moved instead — `VALUE_ALWAYS_PRINTED`,
   :func:`value_may_be_hidden`.
   Since 530B the boxes are measured with the render's own ruler
   (`core.textmetrics.render_width`).

**The rule these four exist to carry** (岳 2026-10-20, second ruling):

    跨岛网在本岛的那一段，用导线连起来（这是「岛内地线连」）；
    岛与岛之间那一跳，用标签接（这是「岛间名字接」）。
    一条网既在岛内走线、又在岛间挂名，两件事不矛盾。

520k read that per **net** and emptied three of the five flyback islands — the
`secondary` island held `D3.1 → C11 → C13` of `SEC_12V` as a plain short wire and
drew none of it.  Read per **segment** it is the opposite: the wire is this
island's own piece, the name is the jump, and `SEC_12V` doing both is the normal
case rather than a conflict.

What it does **not** do: it does not pack islands onto a page (520m — the channel
between two blocks is where the boundary names reach), it does not run the hard
gate, and it does not decide the partition (520j's `islands` does).  A block is a
local frame — :meth:`IslandBlock.translated` is how a packer moves it — and the
parts and labels it emits are ordinary `LayoutPart` / `LayoutLabel`s so that the
same preview, checker and landing step can consume them later.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable, Mapping, Sequence

from ..core.circuitspec import CircuitSpec
from ..core.islands import LayoutIsland, cross_island_nets
from ..core.layoutplan import (
    LayoutJunction,
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from ..core.partkind import (
    KIND_CAPACITOR,
    KIND_IC,
    KIND_INDUCTOR,
    KIND_RESISTOR,
    PartDeclarations,
    classify_part,
)
from ..core.presentationspec import PresentationSpec
from ..core.symbolprofile import (
    Box,
    FLAG_GLYPH_KIND_GND,
    FLAG_GLYPH_ROTATION_OFFSETS,
    SymbolPose,
    SymbolProfile,
    flag_glyph_box,
    flag_glyph_kind,
    pose_box,
)
from ..core.textmetrics import (
    CANVAS_TEXT_UNITS,
    DESIGNATOR_GROWTH,
    TEXT_ROW_HEIGHT,
    flag_name_box,
    pin_rows,
    render_width,
    symbol_rows,
    wire_name_box,
)
#: 540B1: the ground-domain word list moved to the shared vocabulary
#: (`core/netdomains.py`), the same import `drawcompiler` makes of it, for the
#: same reason: an island page and a single-module page of one document must
#: not name the same ground two ways — and neither engine imports the rules
#: layer to do it.
from ..core.netdomains import domain_of

__all__ = [
    "ISLAND_LAYOUT_KIND",
    "ISLAND_PAGE_KIND",
    "ISLAND_SLOTS",
    "IslandBlock",
    "IslandBudget",
    "IslandNet",
    "IslandPin",
    "IslandSubgraph",
    "PackedPage",
    "PageBudget",
    "island_blocks",
    "island_page",
    "island_subgraph",
    "island_subgraphs",
    "layout_island",
    "pack_islands",
]

#: Identifies the artefact a probe writes next to a block's SVG.
ISLAND_LAYOUT_KIND = "boardwise-island-layout/1"

#: Identifies a plan made of several islands packed onto one page (520m), so a
#: file on disk says which of the two this module produced.
ISLAND_PAGE_KIND = "boardwise-island-page/1"

#: The id an island derived by **clustering** carries (`draw islands propose` /
#: `draw islands apply`, task 530E).  `evidence/523/DESIGN.md` §5.4 fixes the id
#: as ``auto-<n>`` — assigned by the clusters' own order, never by a hash or a
#: clock, so a specification's diff shows decisions rather than noise.
#:
#: The prefix is load-bearing at **compile** time and that is 岳's ruling read as
#: a rule (§5.6 L3): an island whose id still says ``auto-`` is a partition that
#: came out of a geometry, so the drawing is legal — S-14's 「箱数 = 名字数」 is
#: about **net** names, not island titles, and most of the golden board's own
#: islands have no title — but the page says out loud where the partition came
#: from.  :func:`derived_cluster_note` is that sentence.
AUTO_ISLAND_PREFIX = "auto-"


def derived_cluster_note(island_id: str) -> str:
    """The sentence a page carries for one island whose partition is geometric.

    Spelled the same in the block's own notes (through :func:`layout_island`) and
    in the `LayoutEvidence` the compiler writes (`drawcompiler._try_island_variants`),
    so a reader who greps either place finds the same words; and spelled *once*
    here rather than twice for the reason every shared sentence in this repository
    lives in one place.
    """
    return (
        f"islands derived by clustering, unnamed ({island_id}): the partition is "
        "geometric, not semantic"
    )


def island_name_note(island_id: str, name: str) -> str:
    """The sentence a page carries for one island the document **named** (530F).

    `islands[]` now holds the name (`core.islands.LayoutIsland.name`), so the one
    document a reader of the partition has open can say what a block is called
    instead of leaving it in the apply report and the design intent (530E's
    deviation 2, closed here).  The note exists for the same reason
    :func:`derived_cluster_note` does: a block, a page plan and a compile result
    are three places a reader may look, and one sentence spelled once keeps them
    from disagreeing.  It says out loud that the name is a **label** — nothing in
    this module reads it, and S-14 counts net names, not island titles.
    """
    return (
        f"island {island_id} is named {name!r}: the name is the document's own "
        "label for the block and no rule in the layout reads it"
    )

#: The pin's own outward direction, in the symbol's frame — the four words
#: `SymbolPin.direction` is written in.
_PIN_AXIS: dict[str, tuple[float, float]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "up": (0.0, 1.0),
    "down": (0.0, -1.0),
}


@dataclass(frozen=True)
class IslandBudget:
    """What the local placer may use.  Every number is a local-frame unit."""

    #: The lattice the origins are snapped to, so two island blocks can be
    #: aligned by a packer without re-snapping (`drawcompiler.GRID`'s value).
    grid: float = 5.0
    #: The tip-to-tip **gap a served part is asked to leave** at the pin it serves
    #: (S-04; `evidence/523/DESIGN.md` §1.3).  16 is the golden board's own median
    #: (`FOC_ANATOMY`: two-pin part to the pin it serves, 16.5 over 34 parts), and
    #: the plausible range is what S-04's own outliers bracket, 2..30.
    #:
    #: The *placement distance* is not this number: it is
    #: ``max(pin_gap, the two pins' drawn leads + one grid step)``, snapped up, so
    #: two long pins can never be laid tip to tip (S-13's 「生成器不主动把脚对脚
    #: 顶在一起」).  This is the floor that expression may not go below.
    pin_gap: float = 16.0
    #: The clear space between two parts of one row, along the row (`DESIGN` §3.2).
    #: 2 rather than 0 or 10 because that is what the golden board's own resistor
    #: row measures (`FOC_ANATOMY`: centre pitch 10, body span 8) — the pitch is
    #: derived from the parts' own extents, and this is only the net gap added.
    row_gap: float = 2.0
    #: How many steps a part may be pushed **outward along its own service axis**
    #: when the place it wants is taken by another part (`DESIGN` §1.4).  Same
    #: precedent as :attr:`text_rungs`: 「第一级被占了第二级是空的」, and the count
    #: is bounded because a part that has walked three channels out is no longer
    #: beside the pin it serves — it is a part in the middle of nowhere, which is
    #: the shape this batch exists to remove.
    slot_rungs: int = 3
    #: One routing channel: the step between the detours a wire may take.
    channel: float = 32.0
    #: How far a boundary stub runs out of its pin before the name starts.  The
    #: page compiler's own `drawcompiler.STUB`, so an island's stub and a page's
    #: stub are the same length of drawn line.  `DESIGN` §6.3 keeps it at 30 — it
    #: is inside the measured band (P-06: the golden board's label stubs are
    #: 22–54) and it is the same number the page compiler uses.
    stub: float = 30.0
    #: How far a part's text block sits off its own extent.
    text_gap: float = 8.0
    #: How many distances each side of a part is tried at before giving up and
    #: drawing the text on the outward side anyway.  `drawcompiler`'s
    #: `TEXT_ESCALATION_STEPS` for the same reason it has one: on a busy local
    #: picture the first rung of a side is occupied while the second is free, and
    #: one rung is how `C6`'s value came to be printed over the `PGND` name.
    text_rungs: int = 3
    #: One text row's height (the render's own row pitch).
    text_row: float = CANVAS_TEXT_UNITS
    #: The flag symbol a **ground** net is looked up under, and the prefix a rail's
    #: own ref is built from — `drawcompiler.CompileBudget`'s two words, spelled
    #: with the same defaults because one document must not name one net two ways
    #: (S-16 + 173/C): the flyback's `PGND`/`SEC_GND`/`HVDC`/`SEC_12V` take the same
    #: four symbols here as they do on a single-module page.
    #:
    #: ``gnd_flag=""`` is 178's own switch for 「this drawing names no ground with a
    #: flag」 and it means exactly that here too — the empty ref is the budget's
    #: statement about the drawing, not a missing entry in the library, so a ground
    #: falls back to a label **silently** rather than reporting a missing symbol.
    gnd_flag: str = "PWR-GND"
    power_flag_prefix: str = "PWR-"

    def __post_init__(self) -> None:
        """Refuse non-finite/negative geometry before the placer consumes it.

        This is a value object shared by the page and independent-island paths.
        Validating here keeps a zero grid, a negative channel or a fractional
        rung count from becoming a low-level arithmetic/range failure later.
        """
        for name in ("grid", "channel", "text_row"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"IslandBudget.{name} must be finite and > 0")
        for name in ("pin_gap", "row_gap", "stub", "text_gap"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"IslandBudget.{name} must be finite and >= 0")
        for name in ("slot_rungs", "text_rungs"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"IslandBudget.{name} must be an integer >= 0")
        for name in ("gnd_flag", "power_flag_prefix"):
            if not isinstance(getattr(self, name), str):
                raise ValueError(f"IslandBudget.{name} must be a string")


@dataclass(frozen=True)
class IslandPin:
    """One pin, as the island sees it: its part, and this spec's pin token."""

    part_id: str
    pin: str

    def __str__(self) -> str:
        return f"{self.part_id}.{self.pin}"


@dataclass(frozen=True)
class IslandNet:
    """One net as it lands in **one** island: the pins of it that are here.

    ``crossing`` is 520j's judgement, carried rather than re-decided: the net's
    pins span two or more islands, so this island holds only one **segment** of
    it.

    **岳's second ruling (2026-10-20, this batch) is what ``crossing`` means for
    the drawing**, and it is a rule about *segments*, not about *nets*:

        跨岛网在本岛的那一段，用导线连起来（这是「岛内地线连」）；
        岛与岛之间那一跳，用标签接（这是「岛间名字接」）。

    Read per-net, that sentence empties the drawing — a crossing net would be
    "not drawn here", which is what 520k did, and it left the flyback's
    `secondary` island with no wire at all even though `D3.1 → C11 → C13` is a
    plain short wire sitting inside it.  Read per-segment, a crossing net is
    wired here **and** named here: the wire is the island's own segment, the name
    is the jump to the next island, and the two are not in competition.

    So :attr:`wired` is "two pins or more **in this island**", crossing or not,
    and :attr:`named` is "this island holds one end of a net that goes elsewhere".
    A one-pin crossing segment is named and not wired — which is the whole of
    520E's mechanism, applied at the island's own boundary.
    """

    net_id: str
    pins: tuple[IslandPin, ...]
    crossing: bool = False

    @property
    def wired(self) -> bool:
        """Does this island draw this net's own segment as wire?"""
        return len(self.pins) >= 2

    @property
    def named(self) -> bool:
        """Does this island put the net's name at its own segment's boundary?"""
        return self.crossing

    @property
    def single_pin(self) -> bool:
        """Is this the **whole** net: one member, and no second end anywhere?

        ``crossing`` is false exactly when the island holding this pin is the only
        one that holds any of it, so "one pin here and not crossing" is "one
        member in the document" — the flyback's `GATE` (`Q1.1`) and `VFB_NF`
        (`R10.1`), whose other end is a controller that is not in the
        `.circuit.json` at all.

        It is a different question from :attr:`wired` (which counts pins *here*),
        and 岳's ruling of 2026-10-20 is what it is asked for: such a pin is
        **named** and the page carries a lint, rather than the pin being read as
        `required-pin-not-connected` and the whole drawing refused (S-17; the
        precedent is board-A's `NRST`, one 48-unit stub with one label and no
        second pin anywhere).  A drawing whose only sin is naming a reserved pin
        is a drawing, not a defect.
        """
        return len(self.pins) == 1 and not self.crossing


@dataclass(frozen=True)
class IslandSubgraph:
    """One island's subgraph: its parts, and every net that touches it."""

    island_id: str
    role: str
    parts: tuple[str, ...]
    nets: tuple[IslandNet, ...]
    #: 536: the group (a module's drawing) this island is a child of, empty for a
    #: legacy island list that states none.  Carried so `layout_island` can stamp
    #: the block without re-reading the presentation.
    group: str = ""

    @property
    def internal_nets(self) -> tuple[IslandNet, ...]:
        """Nets whose every pin is in this island — 520j's ``island-internal``."""
        return tuple(net for net in self.nets if not net.crossing)

    @property
    def crossing_nets(self) -> tuple[IslandNet, ...]:
        """Nets that reach this island and go on to another — 岳's 「跨岛段」."""
        return tuple(net for net in self.nets if net.crossing)

    @property
    def wired_nets(self) -> tuple[IslandNet, ...]:
        """The nets whose island-internal segment becomes wire."""
        return tuple(net for net in self.nets if net.wired)

    @property
    def named_nets(self) -> tuple[IslandNet, ...]:
        """The nets that get one boundary name — every crossing segment."""
        return self.crossing_nets

    @property
    def single_pin_nets(self) -> tuple[IslandNet, ...]:
        """The nets whose only member in the whole document is in this island.

        Named as well as :attr:`named_nets` (岳 2026-10-20, §7.3): a one-pin net
        gets its own name at its own pin plus a lint, so the pin stops reading as
        an unconnected member.  Kept as its own property rather than folded into
        :attr:`named_nets` because the two carry different accounts — a crossing
        name is 岳's 「岛间名字接」 and needs no lint, while this one is a statement
        about a net that goes nowhere.
        """
        return tuple(net for net in self.nets if net.single_pin)

    #: 520k's name for :attr:`wired_nets`, kept so the previous batch's readers
    #: still resolve; the meaning changed with 岳's second ruling, which is why
    #: the property that used to say "not crossing" now says nothing about it.
    @property
    def drawn_nets(self) -> tuple[IslandNet, ...]:
        return self.wired_nets
    def degree(self, part_id: str) -> int:
        """How many of this island's nets touch this part (crossing ones included)."""
        return sum(
            1 for net in self.nets if any(pin.part_id == part_id for pin in net.pins)
        )

    def anchor(self) -> str:
        """The island's hub: the part its nets touch most often.

        Ties go to the subgraph's own order, which is the spec's order, so the
        choice is a function of the documents and not of a dictionary walk.  On
        the flyback this picks Q1 / D3 / U4 / T1 / R10 by itself — the switch,
        the rectifier, the error amplifier, the transformer and the controller's
        own network — with no per-island table anywhere in this module.
        """
        best = ""
        best_degree = -1
        for part_id in self.parts:
            here = self.degree(part_id)
            if here > best_degree:
                best, best_degree = part_id, here
        return best

    def bfs_order(self, anchor: str) -> list[str]:
        """The other parts, breadth-first from ``anchor`` over the island's nets.

        Ties break on the subgraph's own order, so the walk is a function of the
        documents — and since 530B it is also the **order the service tree is
        placed in**, which is why the guarantee matters: a part's father is always
        walked before the part.  Parts no net reaches are appended in spec order
        rather than dropped: an island is a place, and a part the island declares
        sits in it even when this circuit wires it to nothing here.
        """
        reached: list[str] = [anchor]
        seen = {anchor}
        frontier = [anchor]
        while frontier:
            following: list[str] = []
            for part_id in frontier:
                for net in self.nets:
                    if not any(pin.part_id == part_id for pin in net.pins):
                        continue
                    for pin in net.pins:
                        if pin.part_id in seen:
                            continue
                        seen.add(pin.part_id)
                        following.append(pin.part_id)
                        reached.append(pin.part_id)
            frontier = following
        reached.extend(part for part in self.parts if part not in seen)
        return reached[1:]

    def parent_pin(self, child: str, anchor: str, order: Sequence[str]) -> IslandPin | None:
        """The pin of ``child`` that links it toward the anchor — its pose is read off it.

        The first net (in the island's own order) that joins this part to a part
        nearer the anchor on the breadth-first walk.  Since 530B the placer derives
        the same pin with the **class ordering** `DESIGN` §1.2 asks for
        (`_service_for`: a rail or a ground first, then the locally smallest net),
        so this method is `IslandSubgraph`'s own statement of the relationship rather
        than the placer's chooser — kept because §13 leaves `IslandSubgraph` alone.
        """
        depth = {part: index for index, part in enumerate((anchor, *order))}
        here = depth.get(child, len(depth))
        for net in self.nets:
            mine = [pin for pin in net.pins if pin.part_id == child]
            if not mine:
                continue
            closer = [
                pin for pin in net.pins
                if pin.part_id != child and depth.get(pin.part_id, len(depth)) < here
            ]
            if closer:
                return mine[0]
        return None


# --------------------------------------------------------------- the subgraphs


def island_subgraphs(
    circuit: CircuitSpec, presentation: PresentationSpec
) -> list[IslandSubgraph]:
    """Every declared island as a subgraph, crossing nets flagged once for all.

    `cross_island_nets` is the whole page's question (a net is crossing when its
    pins span two islands), so it is asked once here and handed to each island
    rather than re-derived per island — where every net would look internal.
    """
    islands = presentation.effective_islands()
    crossing = set(cross_island_nets(circuit, islands))
    return [island_subgraph(circuit, island, crossing) for island in islands]


def island_subgraph(
    circuit: CircuitSpec, island: LayoutIsland, crossing: Iterable[str] = ()
) -> IslandSubgraph:
    """One island's parts and the nets that reach them.

    A net is listed when at least one of its pins sits on a part this island
    owns; its ``pins`` are **only** those inside the island, because that is all
    the island can draw.  The island's own net order is the circuit's, so the
    picture does not depend on how the spec happened to spell the partition.
    """
    owned = set(island.parts)
    crossing_set = {str(name) for name in crossing}
    nets: list[IslandNet] = []
    for net in circuit.nets:
        here = tuple(
            IslandPin(part_id=member.partition(".")[0], pin=member.partition(".")[2])
            for member in net.members
            if member.partition(".")[0] in owned
        )
        if here:
            nets.append(IslandNet(
                net_id=net.id, pins=here, crossing=net.id in crossing_set,
            ))
    return IslandSubgraph(
        island_id=island.id,
        role=island.role,
        parts=tuple(island.parts),
        nets=tuple(nets),
        # 536: an archipelago island's group travels with its subgraph, so the
        # block (and then the page plan) can state which drawing this is a piece
        # of.  A legacy island states none and nothing is invented.
        group=getattr(island, "group", "") or "",
    )


# ------------------------------------------------------- what the placer reads


@dataclass(frozen=True)
class IslandFacts:
    """One island's electrical picture, folded once for the placer to read.

    `IslandSubgraph` is the shape (parts, nets, which net crosses); this is the
    same document asked the questions §1 and §2 of `evidence/523/DESIGN.md` ask —
    per part, per net, and with each net's own class word.  It holds no geometry
    and no decision: everything here is read off the two documents, so the same
    circuit and the same library give the same facts on every run.
    """

    island_id: str
    #: The island's parts, in the spec's own order.
    parts: tuple[str, ...]
    #: ``part id -> the pins of it this island's nets hold``.
    part_pins: Mapping[str, tuple[IslandPin, ...]]
    #: ``net id -> the pins of it that are here`` (`IslandNet.pins`).
    net_pins_here: Mapping[str, tuple[IslandPin, ...]]
    #: ``part id -> the nets of this island that touch it``, in the circuit's order.
    part_nets: Mapping[str, tuple[str, ...]]
    #: ``net id -> its class word`` — `SpecNet.cls`, the document's own answer, so
    #: 「这是不是一条电源网」 is read rather than guessed from the net's spelling
    #: (`DESIGN` §2.1: 生成器手里有文档，正则只会比文档更容易错).
    cls_of: Mapping[str, str]
    #: ``part id -> how many pins its library symbol has``.
    pin_count: Mapping[str, int]
    #: The nets this island holds **two or more pins** of (`IslandNet.wired`) —
    #: `DESIGN` §1.5's 「本地网」.  A net whose only pin here is a crossing
    #: segment's single pin is not one: there is nothing to draw and nobody to
    #: serve.  Not to be confused with 「every pin of the net is in this island」,
    #: which is a different question and the wrong one (520k's, which emptied the
    #: flyback's `secondary`).
    local_nets: frozenset[str]

    def signal_hits(self, part_id: str) -> int:
        """How many of this island's **signal** nets touch this part (`DESIGN` §1.1).

        「这个岛是干什么的」 is what the island's signals say; a rail or a ground is
        a bus that happens to pass through, so counting it would make the anchor
        the part with the most power pins rather than the part the island is
        about.  Crossing signals count: this island holds their segment, and that
        segment is the reason the part is in this island rather than another.
        """
        return sum(
            1 for net_id in self.part_nets.get(part_id, ())
            if self.cls_of.get(net_id) not in ("power", "gnd")
        )


def _facts(subgraph: IslandSubgraph, circuit: CircuitSpec, book: Mapping[str, SymbolProfile]) -> IslandFacts:
    """Fold a subgraph into the questions the placer asks (`DESIGN` §13)."""
    part_pins: dict[str, list[IslandPin]] = {}
    part_nets: dict[str, list[str]] = {}
    for net in subgraph.nets:
        for pin in net.pins:
            part_pins.setdefault(pin.part_id, []).append(pin)
        for part_id in sorted({pin.part_id for pin in net.pins}):
            part_nets.setdefault(part_id, []).append(net.net_id)
    return IslandFacts(
        island_id=subgraph.island_id,
        parts=tuple(subgraph.parts),
        part_pins={key: tuple(value) for key, value in part_pins.items()},
        net_pins_here={net.net_id: net.pins for net in subgraph.nets},
        part_nets={key: tuple(value) for key, value in part_nets.items()},
        cls_of={net.id: net.cls for net in circuit.nets},
        pin_count={
            part_id: len(book[circuit.part(part_id).symbol_ref].pins)
            for part_id in subgraph.parts
        },
        local_nets=frozenset(net.net_id for net in subgraph.nets if net.wired),
    )


#: A pin count at or above which a part can hold an island together — an IC, a
#: connector, a transformer, an optocoupler.  `DESIGN` §1.1 and the FOC anatomy
#: probe both take 3, and the reason is the same in both places: a two-pin part
#: has one thing to serve and nothing to serve it with.
ANCHOR_MIN_PINS = 3


def _anchor_candidates(facts: IslandFacts, subgraph: IslandSubgraph) -> list[str]:
    """The island's part(s) that could be its anchor, best first (`DESIGN` §1.1).

    The key is ``(signal nets of this island that touch it, every net that touches
    it, its pin count)``, all descending, with the part id ascending as the last
    word — so a tie is broken by the spec's own spelling rather than by a
    dictionary walk, the same discipline :meth:`IslandSubgraph.anchor` states.

    * the first term is 「这个岛是干什么的」: the island's own **signal** nets decide
      the centre (see :meth:`IslandFacts.signal_hits`);
    * the second reuses :meth:`IslandSubgraph.anchor`'s own count — every net,
      crossing ones included — rather than inventing a second degree;
    * the third prefers the 64-pin MCU to the 3-pin regulator;
    * the fourth is determinism.

    Returns **every** candidate, not only the winner: a second candidate is a
    satellite centre rather than a reason to split the island (`DESIGN` §1.1's
    「不因为两个候选不共享岛内信号网就把声明岛拆开」).
    """
    scored: list[tuple[int, int, int, str]] = []
    for part_id in facts.parts:
        pins = facts.pin_count.get(part_id, 0)
        if pins < ANCHOR_MIN_PINS:
            continue
        scored.append((
            -facts.signal_hits(part_id), -subgraph.degree(part_id), -pins, part_id,
        ))
    scored.sort()
    return [item[3] for item in scored]


def anchor_of(facts: IslandFacts, subgraph: IslandSubgraph) -> str:
    """The island's centre: its busiest 3-pin-or-more part (`DESIGN` §1.1).

    An island with no such part — the flyback's `secondary` is `D3` + two output
    capacitors, all two-pin — falls back to :meth:`IslandSubgraph.anchor`, which
    is the previous rule (most nets, ties to the spec's order).  The fallback is
    written down rather than reached by accident: two two-pin parts still need a
    centre to be placed around, and "no candidate" is a fact about the island, not
    a failure.
    """
    candidates = _anchor_candidates(facts, subgraph)
    return candidates[0] if candidates else subgraph.anchor()


# ---------------------------------------------------------------- the service


@dataclass(frozen=True)
class _Service:
    """Whose pin a part stands beside, and which of its own pins does the standing."""

    net_id: str
    parent: str
    parent_pin: IslandPin
    own_pin: IslandPin


def _document_decaps(
    circuit: CircuitSpec, book: Mapping[str, SymbolProfile]
) -> dict[str, tuple[str, str]]:
    """``part id -> (its power net, its ground net)`` for every rail-return part.

    `DESIGN` §2.1's criterion, and it is mechanical on purpose:

    * **exactly two pins**, and
    * **one of them on a `power` net and the other on a `gnd` net** — read off
      `SpecNet.cls`, never off the net's spelling.

    Three things are deliberately *not* asked.  It does not ask whether the part
    is a capacitor: the criterion is geometric (which pin it stands beside), the
    placement does not depend on the part's dielectric, and asking would drag the
    part-kind gate into the placer for nothing.  It does not ask the net names.
    And a part with three or more pins is not one of these however it is wired —
    it is an anchor candidate, not something to be placed beside another part.

    Asked over the **whole circuit** rather than over one island, because
    `DESIGN` §2.3 asks a page-level question too: 「这条轨上全文档有没有一只去耦」
    is not something one island can answer about itself.
    """
    member_net = {
        member: net.id for net in circuit.nets for member in net.members
    }
    cls_of = {net.id: net.cls for net in circuit.nets}
    out: dict[str, tuple[str, str]] = {}
    for part in circuit.parts:
        profile = book.get(part.symbol_ref)
        if profile is None or len(profile.pins) != 2:
            continue
        nets = [
            member_net.get(f"{part.id}.{pin.number}") for pin in profile.pins
        ]
        rails = [net for net in nets if net is not None and cls_of.get(net) == "power"]
        grounds = [net for net in nets if net is not None and cls_of.get(net) == "gnd"]
        if len(rails) == 1 and len(grounds) == 1:
            out[part.id] = (rails[0], grounds[0])
    return out


def _decaps(
    facts: IslandFacts, book: Mapping[str, SymbolProfile], circuit: CircuitSpec
) -> dict[str, tuple[str, str]]:
    """The rail-return parts **this island** holds (see :func:`_document_decaps`)."""
    owned = set(facts.parts)
    return {
        part_id: value
        for part_id, value in _document_decaps(circuit, book).items()
        if part_id in owned
    }


def _service_for(
    part_id: str,
    *,
    facts: IslandFacts,
    index: Mapping[str, int],
    decaps: Mapping[str, tuple[str, str]],
) -> _Service | None:
    """The pin this part stands beside, or ``None`` for a part that serves nobody.

    The net is chosen by `DESIGN` §1.2's table, read against the parts **nearer
    the anchor** (the same "nearer" `IslandSubgraph.bfs_order` measures):

    1. a `power`/`gnd` net first — that is 「这条器件服务的是供电脚」;
    2. then **the net with the fewest pins here**: a two-pin net binds this part
       to one neighbour, while a five-pin rail would tie it to the part at the far
       end of the island;
    3. then the net id, so the answer is a function of the documents.

    A **decoupling part** is the one case the table is overruled for, and by a
    more specific rule (`DESIGN` §2.2): it serves the **power** pin.  Both of its
    nets are `power`/`gnd`, so the general table would hand it whichever of the
    two is locally smaller — often the ground — and a capacitor standing beside a
    ground pin is a part that has been placed next to the return rather than next
    to the rail it decouples.

    ``None`` means this island holds no two-pin net joining this part to anything
    nearer the anchor: `DESIGN` §1.5's 「外来件」, which §1.6 places as a centre of
    its own rather than as somebody's satellite.
    """
    nets = [net_id for net_id in facts.part_nets.get(part_id, ()) if net_id in facts.local_nets]
    if part_id in decaps:
        nets = [net_id for net_id in nets if net_id == decaps[part_id][0]]
    here = index[part_id]
    best: tuple[tuple[int, int, str], _Service] | None = None
    for net_id in nets:
        pins = facts.net_pins_here[net_id]
        mine = [pin for pin in pins if pin.part_id == part_id]
        closer = [
            pin for pin in pins
            if pin.part_id != part_id and index.get(pin.part_id, here) < here
        ]
        if not mine or not closer:
            continue
        closer.sort(key=lambda pin: (index[pin.part_id], pin.part_id, pin.pin))
        cls = facts.cls_of.get(net_id, "")
        key = (0 if cls in ("power", "gnd") else 1, len(pins), net_id)
        if best is None or key < best[0]:
            best = (key, _Service(
                net_id=net_id, parent=closer[0].part_id,
                parent_pin=closer[0], own_pin=mine[0],
            ))
    return None if best is None else best[1]


def row_group(service: _Service, part_id: str, *, book: Mapping[str, SymbolProfile], circuit: CircuitSpec) -> tuple[str, str, str]:
    """``(the library symbol, the part served, the served pin's direction word)``.

    `DESIGN` §3.1's equivalence class for 「同规格同功能的器件等距成排」, and the
    strongest evidence for it is a row of **four different resistors**: board-A's
    `R9/R11/R12/R13` sit at a constant pitch while carrying four different values
    on four different nets.  **`value` is deliberately not in this key** — put it
    in and that row falls apart, which is exactly the failure the design records.
    The direction word is the served pin's, i.e. 「同一个功能边」.
    """
    symbol_ref = book[circuit.part(part_id).symbol_ref].symbol_ref
    parent_profile = book[circuit.part(service.parent).symbol_ref]
    pin = parent_profile.pin(service.parent_pin.pin)
    return (symbol_ref, service.parent, pin.direction if pin is not None else "")


def pack_rows(
    groups: Mapping[tuple[str, str, str], Sequence[str]],
    *,
    spans: Mapping[str, float],
    names: Mapping[str, float],
    budget: IslandBudget,
    values: Mapping[str, float] = {},
    reaches: Mapping[str, tuple[float, float]] = {},
) -> dict[tuple[str, str, str], float]:
    """The pitch each row is laid out on — `DESIGN` §3.2's formula, and its 531/532 halves.

    ``row_pitch = snap_up(max(body_span, refdes width, value row width, left reach + right reach), grid) + row_gap``

    Three inputs and all are measured, not tuned: the widest part's own box across
    the row, the widest reference designator, and — since 531 — the widest **value
    row**.  The first two are 530B's and the third is what the batch before it
    could not see, because the row's text was a fiction: the host draws a part's
    designator above it and its value below it in a row as wide as the string, and
    two parts of one row print those rows **level** with each other.  A pitch
    narrower than the widest of them is therefore not a tight drawing, it is two
    values printed over each other — measured on the landed page,
    `evidence/531/raw/host_rows_before.txt`: `R19`'s `10k 0603` `(130,275)-(159.4,285)`
    over `R20`'s `1R 1% 0603` `(142,275)-(181.3,285)`, and `R15`'s `75k 1% 0603`
    `(108,400)-(149.7,410)` over `C11`'s `1nF/1kV` `(130,395)-(156.6,405)`.

    S-21 still exists and is still used, but it is now the *second* answer rather
    than the first: 「节距 < 2 倍器件框宽时值隐藏或移到外侧」 — where the pitch can
    be widened, the value is printed; where the parts are not a row at all and the
    rows still collide, the value is hidden (`_clear_text_rows`).  The golden
    board's own pitch of 10 is not copied: its library parts are 8 wide and it
    still produced three text collisions at that pitch (`FOC_ANATOMY`). S-06 asks
    for 「等距」, and equal spacing is what :func:`place_service_tree` does with this
    number; the number itself is a derived lower bound.

    532 adds the fourth term, ``reaches``, and it is the one that makes the pitch
    answer the question rather than approximate it. The first three terms are about
    **sizes**; a row's room is about **where it is**. `R0603` at rot 90 prints its
    value row from ``+7`` to ``+48.7`` of its own origin, so a pitch of
    ``snap_up(41.7) + row_gap`` still laid the next part's body over the last units
    of that string (`evidence/532/raw/`: `text-overlap texts[11] + parts[C5]`,
    `texts[13] + parts[R5]`) — and S-21's answer to that is *not* to hide the value
    of a resistor (`VALUE_ALWAYS_PRINTED`), so the pitch is where it has to be
    answered. The two extents are separate numbers because the row is not centred:
    the pitch is what holds one member's right-hand reach beside the next one's
    left-hand reach.
    """
    extents = row_group_extents(
        groups, spans=spans, names=names, values=values, reaches=reaches,
    )
    return {
        key: row_pitch(
            body_span=extents[key][0], name_w=extents[key][1],
            value_w=extents[key][2],
            draw_span=extents[key][3] + extents[key][4],
            budget=budget,
        )
        for key in groups
    }


def row_pitch(
    *,
    body_span: float,
    name_w: float = 0.0,
    value_w: float = 0.0,
    draw_span: float,
    budget: IslandBudget,
) -> float:
    """`DESIGN` §3.2's pitch, in the one form every caller computes it with.

    ``snap_up(max(the part's box, its refdes, its value row, its own drawing's
    reach), grid) + row_gap`` — four measured terms and no fifth.  It is a function
    rather than an expression because two callers need it with different inputs:
    :func:`pack_rows` for one row's own members, and `place_service_tree.pair_pitch`
    for **two** rows laid next to each other. 531 replaced an inline copy of this
    arithmetic with :func:`pack_rows` for exactly this reason, and 532 needs the
    same number for a pair, so the expression itself moved down here.
    """
    # 534 R1: **the pitch is a fact about the geometry, not about the strings.**
    # Until 534 the widest *value row* was one of the terms, so a 9-unit-wide
    # resistor carrying 「1k 1% 0805」 was laid out on a
    # ``snap_up(41.7) + row_gap`` pitch (measured: five 0603 parts of one row took
    # 41.7 units of pitch each, `evidence/534/quality/REPORT.md` S-2/R1) — the
    # *string* decided how far apart the *parts* stood, in every row, including
    # the rows whose text is not printed beside the neighbour at all.
    #
    # What the room a row needs actually depends on is **where the row is**
    # (`draw_span`, the 532 term: the host prints a row at the symbol's declared
    # offset, so the string may reach past the part's own body or lie inside it),
    # and that is still paid here. The *string's width* on top of that is a rent
    # two **adjacent** rows owe each other, not a property of one row:
    # :func:`row_text_rent` charges it in :func:`row_pair_pitch`, and where even
    # that is not enough the value is *moved* by the ladder / the row walk rather
    # than the pitch being widened for the whole island. ``name_w``/``value_w``
    # stay in the signature because every caller has them and the pair step is
    # written in terms of the same four extents; they no longer reach the number.
    del name_w, value_w
    return _snap_up(max(body_span, draw_span), budget.grid) + budget.row_gap


def row_text_rent(*, name_w: float, value_w: float, budget: IslandBudget) -> float:
    """What two rows lying **side by side** owe each other for their text (534 R1).

    The width terms :func:`row_pitch` no longer charges, charged where they are
    true: between one row's right-hand text and the next row's left-hand text.
    It is a *pair* number — a row on its own has nothing to collide with, and
    charging every row for it is what made one wide value widen a whole island.
    """
    widest = max(name_w, value_w)
    if widest <= 0.0:
        return 0.0
    return _snap_up(widest, budget.grid) + budget.row_gap


def row_pair_pitch(
    extents: Mapping[tuple[str, str, str], tuple[float, float, float, float, float]],
    left_key: tuple[str, str, str],
    right_key: tuple[str, str, str],
    *,
    budget: IslandBudget,
) -> float:
    """The step between **two rows laid next to each other** (§3.2, 532).

    Two row groups are two sets of parts and the two parts that come out adjacent
    are one from each, so the step has to hold one group's right-hand reach beside
    the other's left-hand reach — in **both** arrangements, because which group's
    member is the earlier one in the ladder is decided per part. A group's own pitch
    (:func:`pack_rows`) cannot answer that: it holds its own reaches together, and
    on the flyback's `primary` island that made the step between `R3`'s row group
    and `C5`'s ten units short (48.7 + 4.5 = 53.2 against the 48.7 + 8.5 = 57.2 the
    two really need — `evidence/532/raw/`).
    """
    body = extents[left_key]
    other = extents[right_key]
    # 534 R1: the two rows' own geometry first (`reaches` already carries where
    # each row sits), then the text rent for the one arrangement the reaches
    # cannot see — the *string* of one row starting before the next row's last
    # units. Taking the larger keeps the 532 guarantee (a pair never overlaps)
    # while the single-row pitch (`pack_rows`) no longer pays it.
    return max(
        row_pitch(
            body_span=max(body[0], other[0]),
            draw_span=max(body[3] + other[4], other[3] + body[4]),
            budget=budget,
        ),
        row_text_rent(
            name_w=max(body[1], other[1]),
            value_w=max(body[2], other[2]),
            budget=budget,
        ),
    )


def row_group_extents(
    groups: Mapping[tuple[str, str, str], Sequence[str]],
    *,
    spans: Mapping[str, float],
    names: Mapping[str, float],
    values: Mapping[str, float],
    reaches: Mapping[str, tuple[float, float]],
) -> dict[tuple[str, str, str], tuple[float, float, float, float, float]]:
    """Per row group: ``(body span, refdes, value, left reach, right reach)``.

    The five numbers a pitch is made of, read once so that the *pair* step
    (`pair_pitch`) and the row's own step (`pack_rows`) cannot drift apart.
    """
    out: dict[tuple[str, str, str], tuple[float, float, float, float, float]] = {}
    for key, members in groups.items():
        out[key] = (
            max((spans[part_id] for part_id in members), default=0.0),
            max((names[part_id] for part_id in members), default=0.0),
            max((values.get(part_id, 0.0) for part_id in members), default=0.0),
            max((reaches.get(part_id, (0.0, 0.0))[0] for part_id in members),
                default=0.0),
            max((reaches.get(part_id, (0.0, 0.0))[1] for part_id in members),
                default=0.0),
        )
    return out


@dataclass
class _Placement:
    """What :func:`place_service_tree` decided, and what it has to say about it."""

    origins: dict[str, tuple[float, float]]
    poses: dict[str, SymbolPose]
    #: ``part id -> (its row group, that row's pitch, the row's members)``.
    rows: dict[str, tuple[tuple[str, str, str], float, tuple[str, ...]]]
    #: ``part id -> why its **value** row is not drawn`` (S-21's first way out).
    #:
    #: 531: the host draws a part's designator and value at the symbol's own
    #: declared anchor, so the placement cannot move a row — it can only move the
    #: **part**. `_clear_text_rows` tries that first (along the part's own row
    #: axis, then out along its service axis) and a value that is still on top of
    #: something goes into this map with its reason. A reference designator is
    #: never in here: a part with no designator is not a schematic, so a pressed
    #: reference is a page the gate refuses, and the note says which one.
    hidden_values: dict[str, str]
    notes: list[str]


def place_service_tree(
    facts: IslandFacts,
    subgraph: IslandSubgraph,
    anchor: str,
    *,
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    budget: IslandBudget,
) -> _Placement:
    """Every part beside the pin it serves — the replacement for the ring (`DESIGN` §1.3-§1.4).

    Three steps, in this order, because each one needs the one before it:

    1. **the service tree.**  For every part other than the anchor, which pin it
       stands beside (and whether it stands beside any) — decided from the nets
       alone by :func:`_service_for`, so it does not depend on a single
       coordinate.  Parts the island wires to nothing local are `DESIGN` §1.5's
       「外来件」 and become **centres of their own**, laid out on a row (§1.6:
       a name-only island reads as 「两个中心并排、各自带着自己的跨岛名」 rather
       than as a scatter).
    2. **the poses.**  A served part's serving pin is turned to face the pin it
       serves (``wanted = -d``, `_facing_pose`'s native use), so the two pins are
       coaxial and the link between them is one straight stub.
    3. **the origins.**  ``tip(served pin) + d * lead``, plus a slot along the row
       axis; ``lead`` is :func:`_lead`'s and never lets two pins butt (S-13).
       A slot is only ever taken **along the pin's own outward axis or along its
       own row**: a part that has wandered to the other side of the pin, or out of
       its row, is a part that is no longer beside anything, and that is the
       invariant this whole function exists to keep.

    The row pitch comes last and from the poses, because §3.2's span is measured
    on the **posed** part.  Nothing here is iterated: one pass, then the answer.
    """
    order = subgraph.bfs_order(anchor)
    index = {part_id: position for position, part_id in enumerate((anchor, *order))}
    decaps = _decaps(facts, book, circuit)
    services = {
        part_id: _service_for(part_id, facts=facts, index=index, decaps=decaps)
        for part_id in order
    }
    origins: dict[str, tuple[float, float]] = {anchor: (0.0, 0.0)}
    poses: dict[str, SymbolPose] = {
        anchor: _anchor_pose(book[circuit.part(anchor).symbol_ref]),
    }
    notes: list[str] = []

    # -- 1. the centres: the anchor, plus every part that serves nobody.  Ordered
    # by pin count descending then part id (`DESIGN` §1.6's own row), laid on one
    # axis with a channel between neighbours, then shifted so the anchor holds the
    # local origin — the anchor is a centre **and** the frame's pole.
    centres = [anchor, *(part_id for part_id in order if services[part_id] is None)]
    centres.sort(key=lambda part_id: (-facts.pin_count.get(part_id, 0), part_id))
    if len(centres) > 1:
        for part_id in centres:
            profile = book[circuit.part(part_id).symbol_ref]
            poses[part_id] = (poses[anchor] if part_id == anchor
                              else _anchor_pose(profile))
        boxes = {
            part_id: _part_box(
                book[circuit.part(part_id).symbol_ref], poses[part_id], (0.0, 0.0),
            )
            for part_id in centres
        }
        xs = {centres[0]: 0.0}
        for position in range(1, len(centres)):
            previous, part_id = centres[position - 1], centres[position]
            width = ((boxes[previous][2] - boxes[previous][0])
                     + (boxes[part_id][2] - boxes[part_id][0])) / 2.0
            # Two stubs, not one channel: each centre's pins carry their **names**
            # out of their own tips, and a stub is `budget.stub` long, so two
            # centres whose pin-tip zones are one channel apart put their crowns in
            # the same space.  `DESIGN` §1.6 says 「行距 = channel」 and that is what
            # this was measured against: on the flyback's `bridge` island —
            # `T1`(6 pins) and `U5`(4 pins), eight one-pin crossing nets between
            # them — the 35 units a channel leaves made every name pick a
            # compromise, and the compromises were electrical (`wire-through-body`
            # on a flag, a stub over `T1.5` which the spec never mentions).  The
            # pitch is therefore the two stubs the names need, and it is derived
            # from the budget rather than tuned.
            pitch = _snap_up(width + 2.0 * budget.stub, budget.grid)
            xs[part_id] = xs[previous] + pitch
        shift = xs[anchor]
        for part_id in centres:
            origins[part_id] = (_snap(xs[part_id] - shift, budget.grid), 0.0)
        if len(centres) > 2:
            notes.append(
                f"island {facts.island_id!r} has {len(centres)} 3-pin-or-more "
                "parts that serve nobody here, so they are laid out as centres of "
                "their own, one channel apart (DESIGN §1.6: a name-only island is "
                "「两个中心并排、各自带着自己的跨岛名」, not a scatter)"
            )

    # -- 2. every served part's pose: its serving pin faces the pin it serves.
    for part_id in order:
        service = services[part_id]
        if service is None:
            continue
        parent_profile = book[circuit.part(service.parent).symbol_ref]
        d = _pin_outward(parent_profile, service.parent_pin.pin, poses[service.parent])
        poses[part_id] = _facing_pose(
            book[circuit.part(part_id).symbol_ref], service.own_pin.pin,
            (-d[0], -d[1]),
        )

    # -- 2b. the rows, and the pitch each one is laid out on (§3).
    groups: dict[tuple[str, str, str], list[str]] = {}
    for part_id in order:
        service = services[part_id]
        if service is None:
            continue
        key = row_group(service, part_id, book=book, circuit=circuit)
        groups.setdefault(key, []).append(part_id)
    spans: dict[str, float] = {}
    names: dict[str, float] = {}
    #: ``part id -> how wide the value row the host prints for it measures`` (531).
    #: The string is the **drawn** one, not the spec's value: for four of the
    #: flyback's nineteen parts the host prints its own device name
    #: (`SymbolProfile.value_row`), and reserving the spec string's width is what
    #: made the gate report collisions no reader can see.
    values: dict[str, float] = {}
    #: ``part id -> how far the part's own drawing reaches **along its row's axis**,
    #: on each side of its origin`` (532). Different from :data:`values`, which is a
    #: string's width: a row sits at the symbol's declared offset from the part's
    #: origin, so the room it needs is where it *is*, not how wide it is.
    reaches: dict[str, tuple[float, float]] = {}
    for part_id in order:
        profile = book[circuit.part(part_id).symbol_ref]
        # 531: the row a part prints is the **allocated** designator's width, not
        # the spec id's — the pool renames `C5` to `C11` and `R4` to `R19` on the
        # way to the page (`addcomponent.allocate_designator`), and the measured
        # bound is one extra character. Reserving the spec id's width alone is what
        # put the landed `R19` and `R20` rows 12 units apart with a 13-unit
        # designator each (`evidence/531/raw/host_rows_before.txt`: `R19`'s row
        # `(130,275)-(143.11,285)` over `R20`'s `(142,275)-(155.11,285)`).
        names[part_id] = render_width(part_id) + DESIGNATOR_GROWTH
        values[part_id] = max(
            (
                render_width(text)
                for kind, text, _box in symbol_rows(
                    profile, (0.0, 0.0), reference=part_id,
                    value=circuit.part(part_id).value, pose=poses[part_id],
                )
                if kind == "value"
            ),
            default=0.0,
        )
        service = services[part_id]
        if service is None:
            spans[part_id] = 0.0
            continue
        parent_profile = book[circuit.part(service.parent).symbol_ref]
        d = _pin_outward(parent_profile, service.parent_pin.pin, poses[service.parent])
        axis = (-d[1], d[0])
        box = _part_box(profile, poses[part_id], (0.0, 0.0))
        spans[part_id] = max(
            abs(box[2] - box[0]) * abs(axis[0]) + abs(box[3] - box[1]) * abs(axis[1]),
            0.0,
        )
        # 532: and how far the part's **own drawing** reaches along that axis, on
        # each side of its origin.  A row is not centred on its part — the host
        # prints it at the symbol's declared offset, which on the flyback's `R0603`
        # at rot 90 puts the value row from `+7` to `+48.7` of the origin — so a
        # pitch that only reserved the string's *width* still laid the next part's
        # body over the last units of that string (`evidence/532/raw/`:
        # `text-overlap texts[11] + parts[C5]`).  The two extents are kept apart
        # rather than folded into one span: the pitch has to hold one member's
        # right-hand reach beside the next one's left-hand reach, and those are
        # different numbers.
        corners = [
            (box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3]),
        ]
        corners.extend(
            corner
            for _kind, _text, row in symbol_rows(
                profile, (0.0, 0.0), reference=part_id,
                value=circuit.part(part_id).value, pose=poses[part_id],
            )
            for corner in (
                (row[0], row[1]), (row[0], row[3]), (row[2], row[1]), (row[2], row[3]),
            )
        )
        along = [axis[0] * corner[0] + axis[1] * corner[1] for corner in corners]
        reaches[part_id] = (max(0.0, -min(along)), max(0.0, max(along)))
    pitch_of = pack_rows(
        groups, spans=spans, names=names, values=values, reaches=reaches,
        budget=budget,
    )
    #: ``group -> (widest body span, widest refdes, widest value)``, and
    #: ``group -> (left reach, right reach)`` — the two halves `pair_pitch` needs.
    extents = row_group_extents(
        groups, spans=spans, names=names, values=values, reaches=reaches,
    )

    def pair_pitch(left_key, right_key) -> float:
        """The step between **two** rows laid next to each other (§3.2, 532).

        Two groups are two different sets of parts, and the two parts that end up
        adjacent are one from each: the step has to hold one group's right-hand
        reach beside the other's left-hand reach — in both arrangements, because
        which one is the earlier member of the ladder is decided per part. Each
        group's own pitch (`pack_rows`) cannot answer that: it holds its *own*
        reaches together, and on the flyback's `primary` island that made the step
        between `R3`'s row and `C5`'s row short (48.7 + 4.5 = 53.2 against the
        48.7 + 8.5 = 57.2 the two really need — `evidence/532/raw/`).
        """
        return row_pair_pitch(extents, left_key, right_key, budget=budget)

    # The slots of one served pin, in the order they are laid along the row:
    # `DESIGN` §1.4 sorts by (row group, value, part id), with two additions and
    # both are about keeping the row usable rather than about taste.
    #
    # * **the decoupling parts first**, because the ladder only ever walks *away*
    #   from the pin and S-05 caps a decoupling part's distance at 30 — the second
    #   member of a row is already ``pitch`` units off the pin's own axis;
    # * **the widest part before the narrower ones**, because each step is as wide
    #   as the two parts in it, so taking the widest step first leaves every later
    #   member as close to the pin as the row allows.  On the flyback's `secondary`
    #   this is the difference between its two decoupling parts standing 26.9 and
    #   32.0 from the pin they serve, i.e. between passing S-05 and failing it.
    slots: dict[IslandPin, list[str]] = {}
    for part_id in order:
        service = services[part_id]
        if service is None:
            continue
        slots.setdefault(service.parent_pin, []).append(part_id)
    for pins in slots.values():
        pins.sort(key=lambda part_id: (
            0 if part_id in decaps else 1,
            -spans[part_id],
            row_group(services[part_id], part_id, book=book, circuit=circuit),
            circuit.part(part_id).value, part_id,
        ))

    # -- 3. the origins, in breadth-first order so a part's father is always placed.
    #
    # 531: the **anchor's own box is seeded here too**, and that is a measurable
    # fix rather than a tidy-up. `order` is the anchor-less BFS order, so the loop
    # below only ever seeded the parts that serve nobody, and the anchor — which
    # serves nobody either but is not in `order` — was never in the set a served
    # part has to avoid. On the flyback's `secondary` island (`D3` + two
    # capacitors) that put `C11` 60 units left of `D3` with its 88-unit value row
    # straight across `D3`'s drawn body: `readability` reports it as
    # `[text-overlap] texts[18] + parts[D3]` the moment the text model stops being
    # fictional (`evidence/531/raw/...`), because the row the host prints was never
    # measured against the part it lands on.
    placed_boxes: dict[str, Box] = {}
    for part_id in (anchor, *order):
        profile = book[circuit.part(part_id).symbol_ref]
        if services.get(part_id) is None:
            placed_boxes[part_id] = _part_box(
                profile, poses[part_id], origins[part_id],
            )

    rows: dict[str, tuple[tuple[str, str, str], float, tuple[str, ...]]] = {}
    for part_id in order:
        service = services[part_id]
        if service is None:
            continue
        profile = book[circuit.part(part_id).symbol_ref]
        key = row_group(service, part_id, book=book, circuit=circuit)
        members = tuple(groups[key])
        rows[part_id] = (key, pitch_of[key], members)
        parent_profile = book[circuit.part(service.parent).symbol_ref]
        anchor_pose = poses[service.parent]
        d = _pin_outward(parent_profile, service.parent_pin.pin, anchor_pose)
        tip = _posed_point(
            parent_profile.pin(service.parent_pin.pin).tip
            if parent_profile.pin(service.parent_pin.pin) is not None else (0.0, 0.0),
            anchor_pose, origins[service.parent],
        )
        lead, lead_note = _lead(
            parent_profile, service.parent_pin.pin, profile, service.own_pin.pin, budget,
        )
        # 532: and the lead has to clear the part's **own rows** as well.  A row is
        # printed at the symbol's declared offset, and the offset can point back
        # toward the pin the part serves: the flyback's 220uF SMD at rot 90 mirrored
        # prints its 52-unit value row from `-5` to `+47.4` of its own origin, i.e.
        # 7 units **past** `D3.1`'s tip — and that row then lies across the only
        # corridor the net's other links have to reach that tip, which no route can
        # avoid without crossing a body (`evidence/532/raw/`: the same page refused
        # as `text-on-wire texts[21]/[19] + segments[17]` every way it was routed).
        # S-21 forbids hiding a capacitor's value, so the part stands further out —
        # the number this adds is the row's own reach, which is what makes the row
        # clear of the pin rather than a taste for roominess.
        held_lead = max(
            (
                -(d[0] * corner[0] + d[1] * corner[1])
                for _kind, _text, row in symbol_rows(
                    profile, (0.0, 0.0), reference=part_id,
                    value=circuit.part(part_id).value, pose=poses[part_id],
                )
                for corner in (
                    (row[0], row[1]), (row[0], row[3]),
                    (row[2], row[1]), (row[2], row[3]),
                )
            ),
            default=0.0,
        )
        if held_lead > 0.0:
            lead = max(
                lead,
                _snap_up(held_lead + budget.grid, budget.grid),
            )
        if lead_note and lead_note not in notes:
            notes.append(lead_note)
        axis = (-d[1], d[0])
        ladder = slots[service.parent_pin]
        position = ladder.index(part_id)
        # One home for the step between two members of a row: the row's own §3.2
        # pitch (`pack_rows`), taken at the wider of the two neighbours' rows.
        # 531 replaced the inline copy of the formula with the function itself —
        # the two expressions were the same arithmetic written twice, which is how
        # the pitch stopped being a fact about the drawing.
        offset = 0.0
        for earlier in ladder[:position]:
            keys = (
                row_group(services[earlier], earlier, book=book, circuit=circuit),
                row_group(services[part_id], part_id, book=book, circuit=circuit),
            )
            if part_id in decaps or earlier in decaps:
                # S-05 caps a **decoupling part** at 30 units from the supply pin
                # it serves, tip to tip, so two decaps on one pin cannot simply be
                # pushed apart: the second one's distance grows with the offset
                # (`C13` measured `sqrt(10^2 + 27^2) = 28.8` at a 27-unit offset),
                # and a pitch widened to fit the 52-unit value row a 220uF SMD asks
                # for puts it at **57.9** — S-05 breached by 28. 531 answered that
                # with S-21's first way out (the value goes); 532 answers it with
                # the second (`岳 2026-10-21`: a capacitor's value is never hidden),
                # so the step is the pair's own §3.2 pitch and the walk below is
                # what takes the second decap clear of the first one's **rows**.
                offset += pair_pitch(keys[0], keys[1])
                continue
            offset += pair_pitch(keys[0], keys[1])
        # …and then the second decap is walked out along its own row until the rows
        # it prints are clear of the first one's **body**. S-05's own arithmetic is
        # why this needs a walk rather than a pitch: the offset adds in quadrature
        # (`C13` measured `sqrt(10^2 + 27^2) = 28.8` at 27), so S-05's 30 leaves the
        # offset at 28.3 — and a 220uF SMD electrolytic is 41 units tall, so the
        # second decap's designator row is still printed across it. The row the pair
        # needs is ~45 units (measured on the drawing), i.e. **S-05 breached by about
        # 15 for the second decap of a pair**, and that is the trade this module
        # takes rather than refuse the whole page: `readability` counts a designator
        # printed on a neighbour's body as a hard `text-overlap` (a `texts[i]` box is
        # never a host-printed row), while S-05 is a placement reading a reader can
        # judge from the picture. Both numbers are in the island's notes and in
        # `evidence/531/report.md` §6 — this is a finding for 岳, not a silent
        # widening of a spec.
        if position and any(member in decaps for member in ladder):
            while offset < DECAP_ROW_CAP:
                trial = (
                    _snap(tip[0] + d[0] * lead, budget.grid) + axis[0] * sign * offset,
                    _snap(tip[1] + d[1] * lead, budget.grid) + axis[1] * sign * offset,
                )
                if not _rows_pressed(book, circuit, part_id, poses, origins, trial,
                                     placed_boxes):
                    break
                offset += budget.grid
        sign = _row_sign(
            profile, poses[part_id], (tip[0] + d[0] * lead, tip[1] + d[1] * lead),
            axis, placed_boxes.values(),
        )
        # The **base** is snapped, the **walk along the row is not**: `DESIGN` §1.4
        # snaps an origin to the lattice so a packer can align the block, but a
        # row's pitch is `snap_up(max(body span, refdes width), grid) + row_gap`
        # (§3.2) and that number is not a lattice multiple, so snapping each rung
        # of the ladder would round the pitch away (12 → 10 on `R0603`, measured) and
        # S-06 would not hold of the drawing.  The block's own offset is still
        # snapped by the packer; what is not snapped is the spacing *inside* a row.
        def place_at(distance: float) -> tuple[tuple[float, float], Box]:
            here = (
                _snap(tip[0] + d[0] * distance, budget.grid) + axis[0] * sign * offset,
                _snap(tip[1] + d[1] * distance, budget.grid) + axis[1] * sign * offset,
            )
            return here, _part_box(profile, poses[part_id], here)

        for rung in range(0, budget.slot_rungs + 1):
            candidate, box = place_at(lead + rung * budget.channel)
            if not any(_overlaps(box, other) for other in placed_boxes.values()):
                break
        else:
            notes.append(
                f"{part_id}: every rung of {service.parent}.{service.parent_pin.pin}'s "
                f"slot is taken, so it is drawn {budget.slot_rungs} channels out "
                "anyway and a reader must not expect it to read as beside that pin"
            )
        # 531: and then the rows — the host's own text is 8-30 units off every
        # origin, so a part can clear every **body** and still print its designator
        # across the neighbour (`evidence/531/report.md` §2). This second walk is
        # finer and **capped**: `budget.grid` steps, and no candidate may take the
        # part's served pin further than :data:`ROW_LEAD_CAP` units from the pin it
        # serves. That cap is S-05's own acceptance number, borrowed rather than
        # invented, and it is what keeps the row walk from trading a legibility
        # finding for a **placement** one: the first version walked whole channels
        # with no ceiling and took the flyback's `C13` from 28.8 to **79.7** units
        # off `D3.1`, i.e. past the cap S-05 exists to enforce (`evidence/531/
        # report.md` §5). A part that cannot clear inside the cap keeps its place
        # and its value goes instead — S-21's first way out, which is the trade this
        # module is allowed to make.
        origins[part_id] = candidate
        placed_boxes[part_id] = box

    # -- 4. the host's own text rows, which the placement just packed parts onto.
    # 530B spaced the parts for their **pins**; the host prints a row of text 8-30
    # units off every part's origin as well, and the placement never looked at
    # them. That is the measured defect 531 is for (`evidence/531/report.md` §2).
    hidden_values, row_notes = _clear_text_rows(
        book, circuit, services, [anchor, *order], origins, poses, placed_boxes,
        budget,
    )
    for note in row_notes:
        if note not in notes:
            notes.append(note)
    return _Placement(
        origins=origins, poses=poses, rows=rows, hidden_values=hidden_values,
        notes=notes,
    )


def _own_rows(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    part_id: str,
    poses: Mapping[str, SymbolPose],
    origin: tuple[float, float],
) -> list[Box]:
    """The rows the host prints for this part at ``origin`` (531)."""
    return [
        box
        for _kind, _text, box in symbol_rows(
            book[circuit.part(part_id).symbol_ref], origin,
            reference=part_id, value=circuit.part(part_id).value,
            pose=poses[part_id],
        )
    ]


def _rows_pressed(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    part_id: str,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
    candidate: tuple[float, float],
    placed_boxes: Mapping[str, Box],
) -> bool:
    """Would this part's own rows, placed here, land on a part already placed?

    Both halves of one promise, and both are the host's to draw and not this
    module's to move: a part's rows may not land on another part's extent, and —
    the half 530B never had — they may not land on another part's **rows**. The
    second half is the whole defect this batch is about: the landed page printed
    `R15`'s `75k 1% 0603` across `C11`'s `1nF/1kV` with 22 units between the two
    origins (`evidence/531/raw/host_rows_before.txt`).

    532 makes the second half **do something**, which is the fix for the one
    collision 531 could not place its way out of: with the category rule (S-21)
    the 220uF decap keeps its value row, so the 100nF decap beside it has to walk
    past it — and that walk only exists if the rows of the parts already placed are
    part of what a candidate is tested against. Until 532 `placed_boxes` held
    **bodies** alone, so the docstring's second promise was written but never
    tested; `evidence/532/raw/` has the before/after on the real page.

    Only the parts **already placed** are consulted, in the order the caller placed
    them: the rows are committed in that order, so a part that has not been placed
    yet cannot press this one. The one caller is the decap pair's row walk, which is
    the only place a part may still move after its slot was chosen.
    """
    mine = _own_rows(book, circuit, part_id, poses, candidate)
    for row in mine:
        for owner, other in placed_boxes.items():
            if owner != part_id and _overlaps(row, other):
                return True
        for owner in placed_boxes:
            if owner == part_id or owner not in origins:
                continue
            for placed_row in _own_rows(book, circuit, owner, poses, origins[owner]):
                if _overlaps(row, placed_row):
                    return True
    return False


def _clear_text_rows(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    services: Mapping[str, "_Service | None"],
    ring: Sequence[str],
    origins: Mapping[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    placed_boxes: Mapping[str, Box],
    budget: IslandBudget,
) -> tuple[dict[str, str], list[str]]:
    """Hide the values whose own row the host would print over a neighbour (S-21).

    A part's designator and value are drawn by the host at the symbol's own anchor,
    so when two of them land on each other the placement has exactly two levers:
    **move the part**, or **do not print the value**. 531 tried the move first and
    measured it out: walking a part along its own row axis up to `slot_rungs` grid
    steps — `DESIGN` §1.4's legal move — takes the two pins of the link it owns out
    of coaxiality, and the router then draws that link **along the pin's own line**.
    On the flyback's `primary` island, three such moves (R4 by −10 in x, R5 by +3,
    R3 by (+2, −15)) turned the page's *only* remaining finding into
    ``[wire-on-pin-line] segments[4] + parts[D1].1`` — an **electrical** violation,
    which nothing in this drawing may trade a legibility finding for. The
    measurement is reproduced in `evidence/531/report.md` §5.

    So the lever this module actually uses is S-21's **first** way out, which was
    always the primary one: 「值应隐藏」 — a value whose row lands on a neighbour's
    row or on a foreign body is not drawn, and the reason names the box it would
    have been printed in. The geometry is fixed where it can be *placed* right
    instead: the row pitch now fits the designator the page will print, and the
    anchor's own body is in the set a served part has to avoid — both measured,
    both in `place_service_tree`.

    A **reference** is never hidden (a part with no designator is not a
    schematic): it stays printed and the note says so in full, so the gate refuses
    that page and a reader is never handed a drawing with two designators in one
    place.

    Since 532 the **category** decides the value half too (S-21, 岳 2026-10-21):
    a resistor, capacitor, inductor or IC keeps its value row whatever the
    neighbours do — its part has to be moved by the placement instead, or the page
    is refused — while every other kind may lose its value.  :func:`value_may_be_hidden`
    is the reading and it quotes its own basis into the note.  The flag this
    function returns is what the landing step turns into the host's own
    ``valueVisible``: before 532 the value was only *omitted from the plan's text
    list*, and the host printed it anyway (`evidence/532/report.md` §1).

    The order is `(anchor, then the island's parts by id)`, fixed: the rows are
    committed one at a time and a later row may not land on an earlier one, so the
    order is part of the result rather than a detail of it.
    """
    rows: dict[str, list[tuple[str, str, Box]]] = {}

    def rows_of(part_id: str) -> list[tuple[str, str, Box]]:
        profile = book[circuit.part(part_id).symbol_ref]
        return symbol_rows(
            profile, origins[part_id],
            reference=part_id, value=circuit.part(part_id).value,
            pose=poses[part_id],
        )

    def own_pin_boxes(part_id: str) -> list[Box]:
        """The pin name/number rows this part's **own** symbol prints (201H).

        Measured where the host draws them (:func:`textmetrics.pin_rows`), and
        asked because a value row can be pressed by its own symbol's pin
        typography — the half :func:`foreign` cannot see, since it deliberately
        holds only the *other* parts' bodies and rows.

        The measured case: `T1`'s `EE16_3+3_V02` is 50.27 units wide and its top
        edge sits on the axis of pins 2/5, so it prints through `pinName[2]`,
        `pinName[5]` and `pinNumber[5]` — three `pin-text-press` rows the gate
        sees, and no placement of this drawing can clear them, because both rows
        are drawn at the symbol's own offsets.  A symbol that declares no pin
        text table returns nothing and this is a no-op for it.
        """
        profile = book[circuit.part(part_id).symbol_ref]
        return [
            box for _kind, _text, box in pin_rows(
                profile, origins[part_id], pose=poses[part_id],
            )
        ]

    def foreign(part_id: str) -> list[Box]:
        """What this part's rows may not touch: foreign **bodies** and foreign rows.

        The bodies, not `_part_box`'s pin-inclusive extent, and that is the gate's
        own reading rather than a looser one: `readability` reports a text over the
        ``drawn extent of parts[…]``, which is the symbol's body
        (`_PlacedPart.body`). Using the pin-inclusive box here hides values no
        reader would see a problem with — measured on this batch's own synthetic row
        fixture, whose parts have 100-unit pin spans 22 units apart: two of three
        values were dropped for being "on" a neighbour's *pins*.
        """
        out: list[Box] = []
        for owner, _box in placed_boxes.items():
            if owner == part_id:
                continue
            body = pose_box(
                book[circuit.part(owner).symbol_ref].body,
                rotation=poses[owner].rotation, mirror=poses[owner].mirror,
                ox=origins[owner][0], oy=origins[owner][1],
            )
            if body is not None:
                out.append(body)
        out.extend(
            box for owner, entry in rows.items() if owner != part_id
            for _kind, _text, box in entry
        )
        return out

    hidden: dict[str, str] = {}
    notes: list[str] = []
    for part_id in ring:
        mine = rows_of(part_id)
        pins = own_pin_boxes(part_id)
        may_hide, basis = value_may_be_hidden(book, circuit, part_id)
        for kind, text, box in mine:
            foreign_hit = any(_overlaps(box, other) for other in foreign(part_id))
            # 201H: a value row can also be pressed by its **own** symbol's pin
            # typography, which `foreign` excludes by construction. Both rows ride
            # the same part, so this is the one collision no placement can answer
            # and S-21's first way out is the only lever left.
            pin_hits = (
                [row for row in pins if _overlaps(box, row)]
                if kind == "value" else []
            )
            if not foreign_hit and not pin_hits:
                continue
            printed = (
                f"({box[0]:g}, {box[1]:g})-({box[2]:g}, {box[3]:g})"
            )
            if kind == "value" and may_hide:
                if pin_hits and foreign_hit:
                    where = (
                        "and that lands on this part's own pin name/number row(s) "
                        "**and** on a neighbour's own row or on a foreign body"
                    )
                elif pin_hits:
                    where = (
                        "and that lands on this part's **own** pin name/number "
                        "row(s) — both rows are drawn at the symbol's own offsets, "
                        "so no placement of this part can separate them"
                    )
                else:
                    where = (
                        "and that lands on a neighbour's own row or on a foreign body"
                    )
                hidden[part_id] = (
                    f"the host prints it at {printed} {where} — S-21's first way "
                    "out of a collision is to hide the value rather than print it "
                    "through the neighbour"
                    + (
                        f" (the row's pitch is {budget.row_gap:g} + the parts' own "
                        "spans, and this part's neighbours leave no room for it)"
                        if foreign_hit else
                        " (moving the part cannot help: both rows ride the same "
                        "symbol)"
                    )
                )
            elif kind == "value":
                where = (
                    "this part's own pin name/number row(s) and a neighbour"
                    if pin_hits and foreign_hit else
                    "this part's own pin name/number row(s)"
                    if pin_hits else "a neighbour"
                )
                notes.append(
                    f"{part_id}: its value row {text!r} at {printed} is on {where}, "
                    f"and S-21 will not hide it — {basis} — so "
                    + (
                        "the gate is what refuses this page: no placement can "
                        "separate two rows of one symbol, and the value stays "
                        "printed through its own pin typography"
                        if pin_hits and not foreign_hit else
                        "the placement is the only lever left and the gate is what "
                        "refuses this page if the placement did not take it "
                        "(S-21: 拥挤时只能挪器件加距)"
                    )
                )
            else:
                notes.append(
                    f"{part_id}: its reference row at {printed} is on a neighbour, "
                    "and a reference designator is never hidden — the page is "
                    "refused by the gate rather than drawn with two designators in "
                    "one place"
                )
        rows[part_id] = [
            (kind, text, box) for kind, text, box in mine
            if not (kind == "value" and part_id in hidden)
        ]
    return hidden, notes


def _union(boxes: Sequence[Box]) -> Box:
    """The smallest box holding every one of ``boxes`` (an empty list is a point)."""
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )


def _lead(
    served: SymbolProfile,
    served_pin: str,
    part: SymbolProfile,
    part_pin: str,
    budget: IslandBudget,
) -> tuple[float, str]:
    """How far out along ``d`` the served part's origin sits, and a note if unpinned.

    `DESIGN` §1.3's own expression, with the two floors it needs:

        lead = snap_up(max(budget.pin_gap,
                           pin_len(served) + pin_len(part) + budget.grid,
                           |part's own pin tip| + budget.grid), grid)

    * ``pin_len(served) + pin_len(part) + grid`` is §1.3's own term, and it is the
      one that stops two **drawn** pins from being laid tip to tip: the two leads
      plus a lattice step is the least room that leaves a stub between them (S-13's
      「生成器**不主动**把器件脚对脚顶在一起」);
    * ``|the served pin's tip| + grid`` is the correction this batch's own fixture
      forced.  A pin is drawn from its symbol's origin out to its tip, and the two
      are not the same number: `R0603`'s tip is **20** units out with a ``length``
      of 10, and a transformer's pins are 40 with a ``length`` of 20.  A lead that
      ignores the reach puts the served part's own tip *past* the tip it serves —
      and on a symbol whose reach exceeds its drawn lead, **inside** the part it
      serves, which is a pin tip in another part's body (`wire-through-body`).
      The floor is written as "the stub is at least a lattice step", which is the
      same statement without naming a symbol.

    A library that states no length is **not** guessed at: the grid step stands in
    for it and the block says so, which is the honest form of "this profile does
    not tell us".
    """
    first, second = _pin_length(served, served_pin), _pin_length(part, part_pin)
    missing = [
        name for name, value in ((served.symbol_ref, first), (part.symbol_ref, second))
        if value is None
    ]
    total = (first or budget.grid) + (second or budget.grid) + budget.grid
    reach = _pin_reach(part, part_pin) + budget.grid
    lead = _snap_up(max(budget.pin_gap, total, reach), budget.grid)
    note = ""
    if missing:
        note = (
            f"pin length is not stated for {', '.join(missing)}, so one grid step "
            f"stands in for it in the lead of {part.symbol_ref} beside "
            f"{served.symbol_ref}.{served_pin} — the distance is a floor, not a "
            "measurement"
        )
    return lead, note


def _pin_length(profile: SymbolProfile, pin_number: str) -> float | None:
    """``SymbolPin.length`` or ``None`` when the profile does not state it."""
    pin = profile.pin(pin_number)
    if pin is None or pin.length is None:
        return None
    return float(pin.length)


def _pin_reach(profile: SymbolProfile, pin_number: str) -> float:
    """How far this pin's **tip** sits from its symbol's own origin.

    The number that places a part, where :func:`_pin_length` is the number that
    keeps two pins from butting.  They are not the same measurement and a library
    may state both: `R0603`'s tip is 20 out with a drawn lead of 10.
    """
    pin = profile.pin(pin_number)
    if pin is None:
        return 0.0
    return math.hypot(pin.tip[0], pin.tip[1])


def _row_sign(
    profile: SymbolProfile,
    pose: SymbolPose,
    origin: tuple[float, float],
    axis: tuple[float, float],
    placed: Iterable[Box],
) -> float:
    """Which way along ``axis`` this part's row grows (`DESIGN` §1.4).

    The side that makes the drawing smaller: the candidate box is folded into the
    union of what is already placed and the two perimeters are compared; a tie
    goes to ``+``.  It is a decided rule rather than a taste because the two sides
    are otherwise indistinguishable from one part's own point of view, and
    "which side" has to be the same answer on every run.
    """
    others = list(placed)
    scores: list[float] = []
    for sign in (1.0, -1.0):
        box = _part_box(profile, pose, (
            origin[0] + axis[0] * sign, origin[1] + axis[1] * sign,
        ))
        merged = _union([*others, box])
        scores.append((merged[2] - merged[0]) + (merged[3] - merged[1]))
    return 1.0 if scores[0] <= scores[1] else -1.0


def _island_radius(
    origins: Mapping[str, tuple[float, float]],
    extents: Mapping[str, Box],
    anchor: str,
    budget: IslandBudget,
) -> float:
    """How big the island is: the farthest corner of any part's box from the hub.

    The ring that used to answer this is gone (530B), and `_detours` still needs a
    number for its fallback channel — 「a detour that is not outside everything is
    not a way around anything」 — so the number is now the island's own extent plus
    one channel.  `DESIGN` §6.4 asks for 「件框到锚的最大距离 + clearance」; the
    clearance knob went with the ring (§13), so the channel stands in, which is the
    same guarantee by a knob that is still on the drawing.

    ``IslandBlock.ring_radius`` keeps the name and carries this (see its field).
    """
    if not extents:
        return 0.0
    pole = origins[anchor]
    reach = 0.0
    for box in extents.values():
        for corner in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
            reach = max(reach, math.hypot(corner[0] - pole[0], corner[1] - pole[1]))
    if reach <= 0.0:
        return 0.0
    return _snap_up(reach + budget.channel, budget.grid)


def _account_decap(
    facts: IslandFacts,
    subgraph: IslandSubgraph,
    anchor: str,
    placement: _Placement,
    circuit: CircuitSpec,
    book: Mapping[str, SymbolProfile],
    block: IslandBlock,
    budget: IslandBudget,
) -> None:
    """What S-05 owes the drawing: the distance, and the rails nobody decouples.

    Two accounts, and neither of them is a refusal — `DESIGN` §2.2/§2.3:

    * **the distance, written down.**  S-05 says 「去耦电容贴供电脚 ≤ 30」 and does
      not say whether that is measured box to box or tip to tip; the two readings
      differ by tens of units on a wide symbol, and 521 §i records what happens
      when a number is quoted without its reading (「43/24 是哪种」).  So the number
      here is the **tip-to-tip** one and it says so.
    * **the missing decoupling, named.**  「IC 每条电源网至少 1 只」 is a statement
      about a rail the anchor is supplied by, and about the whole document, not
      only this island — and it is accounted rather than enforced, because the
      golden board itself has three decoupling parts beyond 60 units
      (`FOC_ANATOMY`) and the flyback's own `SEC_12V` is supplied by a two-pin
      rectifier rather than by any IC's supply pin.  A rule that asked the placer
      to answer for a part that does not exist would be the 520E mistake again:
      the drawing would have to pretend something is there.
    """
    document = _document_decaps(circuit, book)
    owned = set(facts.parts)
    index = {
        part_id: position
        for position, part_id in enumerate((anchor, *subgraph.bfs_order(anchor)))
    }
    decoupled: set[str] = set()
    for part_id in sorted(part_id for part_id in document if part_id in owned):
        rail, ground = document[part_id]
        if part_id not in placement.origins:
            continue
        service = _service_for(
            part_id, facts=facts, index=index,
            decaps={name: value for name, value in document.items() if name in owned},
        )
        if service is None:
            continue
        profile = book[circuit.part(part_id).symbol_ref]
        own = [
            pin for pin in facts.net_pins_here.get(rail, ())
            if pin.part_id == part_id
        ]
        if not own:
            continue
        decoupled.add(rail)
        parent_profile = book[circuit.part(service.parent).symbol_ref]
        own_tip = _posed_point(
            _pin_tip(profile, own[0].pin), placement.poses[part_id],
            placement.origins[part_id],
        )
        parent_tip = _posed_point(
            _pin_tip(parent_profile, service.parent_pin.pin),
            placement.poses[service.parent], placement.origins[service.parent],
        )
        distance = math.hypot(own_tip[0] - parent_tip[0], own_tip[1] - parent_tip[1])
        block.notes.append(
            f"decap {part_id}: its {rail} pin ({own[0]}) stands {distance:g} from "
            f"the pin it serves, {service.parent_pin} on {service.net_id}"
            f" (measured tip to tip; S-05 asks ≤ 30), and its {ground} pin is the "
            "outward one, so that rail's flag follows it"
        )
    for net_id in sorted(facts.local_nets):
        if facts.cls_of.get(net_id) != "power":
            continue
        pins = facts.net_pins_here.get(net_id, ())
        if not any(pin.part_id == anchor for pin in pins):
            continue
        if net_id in decoupled:
            continue
        elsewhere = sorted(
            part_id for part_id, value in document.items()
            if value[0] == net_id and part_id not in owned
        )
        if elsewhere:
            block.notes.append(
                f"decap-missing: rail {net_id} — the anchor {anchor} is supplied "
                f"by it and this island holds no decoupling part for it (S-05's "
                f"「IC 每条电源网至少 1 只」); elsewhere in the document it is "
                f"decoupled by {', '.join(elsewhere)}.  Accounted, not refused: "
                "which island a part belongs to is 岳's partition, not this "
                "placer's to change"
            )
        else:
            block.notes.append(
                f"decap-missing: rail {net_id} — the anchor {anchor} is supplied "
                "by it and the document holds no decoupling part for it anywhere "
                "(S-05's 「IC 每条电源网至少 1 只」).  Accounted, not refused: "
                "whether the board should have that capacitor is the review line's "
                "question (rules/params/decap), not the placer's"
            )


def _pin_tip(profile: SymbolProfile, pin_number: str) -> tuple[float, float]:
    """A pin's symbol-local tip, or the symbol's own origin for a pin it lacks."""
    pin = profile.pin(pin_number)
    return (0.0, 0.0) if pin is None else (pin.tip[0], pin.tip[1])


# ------------------------------------------------------ the proposal probe (530E)
#
# `evidence/523/DESIGN.md` §5.3.1's one admitted chicken-and-egg: automatic
# clustering needs the **gap between two parts' boxes**, a gap needs geometry, and
# geometry needs a partition.  The design refuses to iterate, so this is one pass
# whose whole product is a box per part — and its product **never reaches a
# drawing**.  It is asked for by `engines.islandproposal` and by nothing else;
# `draw compile` cannot reach it (see §5.2's two-stage rule).

#: How far along its own row a probe placement may walk before it is put down on
#: top of something after all.  `IslandBudget.slot_rungs` is the *drawing*'s bound
#: and it is deliberately short — a part three channels out is no longer beside the
#: pin it serves — but this placement is never drawn, and the one number it produces
#: is a **gap**: two probe boxes sharing space measure zero, which would read as
#: "these two parts touch" for parts that have nothing to do with each other.  So
#: the probe keeps walking, and this is only a termination bound.
_PROBE_LADDER = 32


def probe_boxes(
    circuit: CircuitSpec,
    parts: Sequence[str],
    profiles: Mapping[str, SymbolProfile],
    *,
    anchor_min_pins: int,
    orphan_gap: float,
    budget: IslandBudget | None = None,
) -> dict[str, Box]:
    """A throwaway placement of ``parts``, measured only to compare distances.

    `DESIGN` §5.3.1's four steps, in its own order:

    1. **the anchors** — the parts with ``anchor_min_pins`` pins or more (`ANCHOR_MIN_PINS`
       in the design, taken from the FOC anatomy probe) — by pin count descending then
       part id, on one row, each in its profile's own first pose;
    2. **every other part** beside the pin of a part it **shares a net** with.  The
       service table of §1.2 is *not* asked here: that table needs a "nearer the
       anchor" order and this probe has no anchor.  The parent is the nearest
       already-placed part sharing a net, and the distance is :func:`_lead`'s;
    3. **a part no placed part shares a net with** is laid at the end of the row,
       ``orphan_gap`` from the last thing placed — it belongs to nobody yet, which
       is the fact the clustering is about;
    4. **nothing else.**  No wire, no text, no flag, no name, no row, no decoupling
       part: only :func:`_part_box`.

    **Two additions to §5.3.1, and both are about the one measurement this
    function exists to produce.**  §5.3.1 says "行距 ``channel``", and a flat
    32-unit pitch would make two wide anchors' boxes overlap on the probe's own
    row — an overlap makes :func:`box_gap` zero, so every part would measure as
    equidistant from every anchor.  The pitch here is therefore the two boxes'
    own widths plus one channel.  For the same reason a part whose wanted place
    is **taken** walks outward along its own service axis in ``budget.channel``
    rungs — the same bounded ladder :func:`place_service_tree` uses — before it is
    put down anyway.  Neither addition is a decision about the page: the whole
    product is thrown away by its caller.

    **Determinism**: every step reads the two documents and the library, and every
    tie is broken by a part id or a pin number, so the same inputs give the same
    boxes on every run — which is what lets the proposal document be compared byte
    for byte (task 530E's item 2).
    """
    budget = budget or IslandBudget()
    book = {str(key): value for key, value in profiles.items()}

    def profile_of(part_id: str) -> SymbolProfile:
        return book[circuit.part(part_id).symbol_ref]

    nets_of_pin: dict[str, list[str]] = {}
    for net in circuit.nets:
        for member in net.members:
            nets_of_pin.setdefault(str(member), []).append(net.id)

    def nets_of(part_id: str) -> list[str]:
        """The nets this part is on, in the circuit's own order, no repeats."""
        out: list[str] = []
        for pin in profile_of(part_id).pins:
            for net_id in nets_of_pin.get(f"{part_id}.{pin.number}", ()):
                if net_id not in out:
                    out.append(net_id)
        return out

    def pins_on(part_id: str, net_id: str) -> list[str]:
        return [
            str(pin.number) for pin in profile_of(part_id).pins
            if net_id in nets_of_pin.get(f"{part_id}.{pin.number}", ())
        ]

    order = [str(part_id) for part_id in parts]
    pin_count = {part_id: len(profile_of(part_id).pins) for part_id in order}
    anchors = sorted(
        (part_id for part_id in order if pin_count[part_id] >= anchor_min_pins),
        key=lambda part_id: (-pin_count[part_id], part_id),
    )

    origins: dict[str, tuple[float, float]] = {}
    poses: dict[str, SymbolPose] = {}
    boxes: dict[str, Box] = {}
    cursor = 0.0
    for position, part_id in enumerate(anchors):
        profile = profile_of(part_id)
        pose = _anchor_pose(profile)
        home = _part_box(profile, pose, (0.0, 0.0))
        x = 0.0 if position == 0 else cursor + budget.channel - home[0]
        origin = (_snap(x, budget.grid), 0.0)
        origins[part_id], poses[part_id] = origin, pose
        boxes[part_id] = _part_box(profile, pose, origin)
        cursor = boxes[part_id][2]

    def beside(part_id: str, parent: str):
        """Where this part stands beside ``parent``, or ``None`` if they share no net.

        The shared net is the first one in the circuit's order and the two pins are
        the lowest-numbered of each part on it, so the answer is a function of the
        documents rather than of the order a dictionary happens to walk.
        """
        common = [net_id for net_id in nets_of(part_id) if net_id in nets_of(parent)]
        if not common:
            return None
        net_id = common[0]
        parent_profile, profile = profile_of(parent), profile_of(part_id)
        parent_pin = sorted(pins_on(parent, net_id))[0]
        own_pin = sorted(pins_on(part_id, net_id))[0]
        d = _pin_outward(parent_profile, parent_pin, poses[parent])
        tip = _posed_point(
            _pin_tip(parent_profile, parent_pin), poses[parent], origins[parent],
        )
        lead, _ = _lead(parent_profile, parent_pin, profile, own_pin, budget)
        pose = _facing_pose(profile, own_pin, (-d[0], -d[1]))
        origin = (
            _snap(tip[0] + d[0] * lead, budget.grid),
            _snap(tip[1] + d[1] * lead, budget.grid),
        )
        return d, pose, origin

    for part_id in order:
        if part_id in origins:
            continue
        profile = profile_of(part_id)
        candidates = []
        for parent in order:
            if parent not in origins:
                continue
            found = beside(part_id, parent)
            if found is None:
                continue
            d, pose, origin = found
            box = _part_box(profile, pose, origin)
            candidates.append((box_gap(box, boxes[parent]), origin, parent, d, pose, box))
        if candidates:
            candidates.sort(key=lambda item: (
                item[0], item[1], item[2], item[4].rotation, item[4].mirror,
            ))
            _, base, _, d, pose, _ = candidates[0]
            # A taken place is resolved **along the row, not along the service
            # axis**: `DESIGN` §1.4's invariant for the real placer is exactly this
            # pair of moves (「只许沿着自己的服务轴 d 外移、或沿着自己那一排的
            # row_axis 平移」), and a probe that walked parts *outward* would push each
            # later sibling of one pin a little further from that pin — which is the
            # distance this whole function exists to measure.  The rungs alternate
            # sides, so the picture grows evenly instead of leaning one way.
            axis = (-d[1], d[0])
            for rung in range(0, _PROBE_LADDER + 1):
                step = 0.0 if rung == 0 else (1.0 if rung % 2 else -1.0) * (
                    (rung + 1) // 2
                ) * budget.channel
                origin = (
                    _snap(base[0] + axis[0] * step, budget.grid),
                    _snap(base[1] + axis[1] * step, budget.grid),
                )
                box = _part_box(profile, pose, origin)
                if not any(_overlaps(box, other) for other in boxes.values()):
                    break
            origins[part_id], poses[part_id] = origin, pose
            boxes[part_id] = _part_box(profile, pose, origin)
        else:
            pose = _anchor_pose(profile)
            home = _part_box(profile, pose, (0.0, 0.0))
            origin = (_snap(cursor + orphan_gap - home[0], budget.grid), 0.0)
            origins[part_id], poses[part_id] = origin, pose
            boxes[part_id] = _part_box(profile, pose, origin)
        cursor = max(cursor, boxes[part_id][2])
    return boxes


# ------------------------------------------------------------------ the block


def _parts_with_identity(block: "IslandBlock") -> list[LayoutPart]:
    """One block's parts, stamped with the block's own group and island (536).

    :meth:`IslandBlock.plan` and :meth:`PackedPage.plan` are two readings of the
    **same** picture, so the identity has to be stated by one function rather
    than twice: a page plan that stamped and a block plan that did not would
    describe two different drawings from one block.  Three rules, in this order:

    * a block that states **no group** — every island this module drew before
      536, and every legacy island list — hands its parts back **verbatim**.  No
      field is filled in, so its bytes and its `geometry_sha256` are unchanged.
    * a block that states a group stamps ``block.group`` and ``block.island_id``
      on every part it carries: the plan is the machine-readable statement
      `core.archipelago.validate_archipelago_plan` reads, so the identity cannot
      stop at the block.
    * a part that already states a **different** group or island is a
      contradiction, and it is refused here rather than overwritten.  Silently
      re-stamping it would launder the contradiction into a plan that validates
      and draws the wrong picture (`docs/drawing-archipelago-route.md` §2.3:
      never re-stamp a part to make the page pass).

    Nothing else moves: coordinates, notes and `bbox` are untouched.
    """
    if not block.group:
        return list(block.parts)
    parts: list[LayoutPart] = []
    for item in block.parts:
        if item.group and item.group != block.group:
            raise ValueError(
                f"part {item.part_id} states group {item.group!r} but island "
                f"block {block.island_id!r} is in group {block.group!r}: a part's "
                "identity is not something a page rewrites"
            )
        if item.island and item.island != block.island_id:
            raise ValueError(
                f"part {item.part_id} states island {item.island!r} but sits in "
                f"island block {block.island_id!r} (group {block.group!r}): a "
                "part's identity is not something a page rewrites"
            )
        parts.append(replace(item, group=block.group, island=block.island_id))
    return parts


@dataclass
class IslandBlock:
    """One island drawn in a frame of its own: the anchor at the local origin.

    The block is a *picture*, not a page: the anchor sits at ``(0, 0)`` and every
    other part is placed beside the pin it serves (`place_service_tree`, 530B).
    520m packs the blocks by moving each one whole (:meth:`translated`), which is
    what makes the island a rigid block and the space between islands a channel
    520l can run its stubs through.
    """

    island_id: str
    role: str
    anchor: str
    parts: list[LayoutPart] = field(default_factory=list)
    segments: list[LayoutSegment] = field(default_factory=list)
    junctions: list[LayoutJunction] = field(default_factory=list)
    #: One per crossing segment: the net's name at the boundary of this island's
    #: own piece of it.  Same text in two islands is one net (that is 岳's 「岛间
    #: 名字接」), so a three-island net carries three names and no extra wiring.
    #:
    #: Since 530A a **ground or rail** crossing segment is not in this list: S-16
    #: (「地/电源一律旗标」) sends it to :attr:`power_symbols` instead.  What is left
    #: here is the signal/other half — 岳's 「网络标签只许跨岛信号边界」.
    labels: list[LayoutLabel] = field(default_factory=list)
    #: The rail/ground **flags** this island hangs, one per crossing (or one-pin)
    #: net of the `power`/`gnd` class (S-16, 530A).
    #:
    #: One flag per net here, never one per pin: 岳's ruling of 2026-10-20 reads
    #: S-16's 「每个消费点各插一个」 at the granularity of the *connected blob* —
    #: 「一个旗标可汇聚多个就近引脚」, the golden board's own habit (board-A's `GND`
    #: is 48 pins under 34 flags) — so an island's several pins of one rail are one
    #: flag at the end of the island's own wire, not a flag per pin and never a
    #: bus.  That is also why the number here is `len(subgraph.crossing_nets of
    #: that class) + len(single-pin power/gnd nets)` and not a pin count.
    #:
    #: Additive field (`default_factory=list`): every construction point that
    #: predates 530A stays legal, and a block with no flags behaves as it always
    #: did in :meth:`translated`, :meth:`bbox` and :meth:`plan`.
    power_symbols: list[LayoutPowerSymbol] = field(default_factory=list)
    #: The page box each entry of :attr:`power_symbols` occupies — its glyph, and
    #: for a rail also the name row the host prints beside it (the composition
    #: `drawcompiler._flag_box` makes; the two functions that must agree on it are
    #: `core.textmetrics.flag_name_box` and `readability._flag_name_row`, which
    #: both read the same measured rule).
    #:
    #: Stored rather than recomputed because the two readers that need it —
    #: :meth:`bbox` (the packer, `S-01`'s keep-out arithmetic) and
    #: `readability._check_bodies` — run **without the library**, and a block that
    #: does not carry its own flags' extents would let the next island be packed on
    #: top of a flag.  Parallel to :attr:`power_symbols`, same order, one entry
    #: each: `LayoutPowerSymbol` (core, unchanged since 143c) carries no box of its
    #: own, and a second model of "where a flag is drawn" is exactly what
    #: `core.textmetrics` exists to prevent.
    power_boxes: list[Box] = field(default_factory=list)
    texts: list[LayoutText] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: How big this island is, in the block's own frame: the farthest corner of
    #: any part's box from the anchor, plus one channel (`_island_radius`).
    #:
    #: The **name is 520k's and the number no longer is.**  520k/520n put the
    #: island's parts on a ring and this was that ring's radius; 530B places each
    #: part beside the pin it serves, so there is no ring and no radius to report.
    #: `_detours` still needs one number for its fallback channel — 「a detour that
    #: is not outside everything is not a way around anything」 — and this is it.
    #: Kept under its old name so :meth:`translated` and every construction point
    #: keep their signatures (`DESIGN` §8.2).
    ring_radius: float = 0.0
    order: list[str] = field(default_factory=list)
    #: 536: the group (a module's drawing) this island is a child of, empty for a
    #: legacy island.  :meth:`PackedPage.plan` reads it to stamp every part of
    #: this block with ``group`` and ``island``; an empty group stamps nothing,
    #: which is why an old island page keeps its parts' bytes and its digest.
    group: str = ""

    def translated(self, dx: float, dy: float) -> IslandBlock:
        """This block moved whole — every part, wire, junction, name and text box.

        Every list moves by the same ``(dx, dy)`` and nothing is recomputed: that
        is what "rigid block" means here, and it is why 520m can place an island
        with one call instead of re-running this module's placer per island.
        """
        return IslandBlock(
            island_id=self.island_id,
            role=self.role,
            anchor=self.anchor,
            parts=[
                LayoutPart(
                    part_id=item.part_id, symbol_ref=item.symbol_ref,
                    symbol_hash=item.symbol_hash, x=item.x + dx, y=item.y + dy,
                    rotation=item.rotation, mirror=item.mirror,
                    reference=item.reference, value_visible=item.value_visible,
                    # 536: the move is rigid, and ownership is part of what
                    # travels — copied verbatim, never filled in here (a part
                    # that states no island is one this path did not place, and
                    # stamping it would invent an identity it never had).
                    group=item.group, island=item.island,
                )
                for item in self.parts
            ],
            segments=[
                LayoutSegment(
                    net=item.net,
                    points=[(x + dx, y + dy) for x, y in item.points],
                )
                for item in self.segments
            ],
            junctions=[
                LayoutJunction(net=item.net, x=item.x + dx, y=item.y + dy)
                for item in self.junctions
            ],
            labels=[
                LayoutLabel(
                    net=item.net, text=item.text,
                    bbox=(
                        item.bbox[0] + dx, item.bbox[1] + dy,
                        item.bbox[2] + dx, item.bbox[3] + dy,
                    ),
                    x=item.x + dx, y=item.y + dy, rotation=item.rotation,
                    part_id=item.part_id,
                )
                for item in self.labels
            ],
            texts=[
                LayoutText(
                    kind=item.kind, text=item.text,
                    bbox=(
                        item.bbox[0] + dx, item.bbox[1] + dy,
                        item.bbox[2] + dx, item.bbox[3] + dy,
                    ),
                    part_id=item.part_id,
                    x=None if item.x is None else item.x + dx,
                    y=None if item.y is None else item.y + dy,
                    rotation=item.rotation,
                )
                for item in self.texts
            ],
            power_symbols=[
                LayoutPowerSymbol(
                    symbol_ref=item.symbol_ref, symbol_hash=item.symbol_hash,
                    net=item.net, x=item.x + dx, y=item.y + dy,
                    rotation=item.rotation,
                )
                for item in self.power_symbols
            ],
            power_boxes=[
                (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
                for box in self.power_boxes
            ],
            notes=list(self.notes),
            ring_radius=self.ring_radius,
            order=list(self.order),
            # 536: the block's group moves with the block.
            group=self.group,
        )

    def bbox(self) -> Box:
        """Everything the block draws, bounded — the shape a packer places.

        The names are in it, and they have to be: a boundary name sticks out
        past every part, and a packer that measured only the parts and the wires
        would lay the next island on top of it.

        Since 530A the **flags** are in it too, through :attr:`power_boxes`, and
        for the same reason: a glyph hangs off the end of a boundary stub, so it
        sticks out past everything else the block draws.  520m's `S-01` rule —
        nothing enters the title block — is decided from this box, so a flag
        missing here is a flag that can be packed into the title block.
        """
        boxes: list[Box] = [text.bbox for text in self.texts]
        boxes.extend(label.bbox for label in self.labels)
        boxes.extend(tuple(box) for box in self.power_boxes)
        for part in self.parts:
            boxes.append((part.x, part.y, part.x, part.y))
        for segment in self.segments:
            boxes.extend((x, y, x, y) for x, y in segment.points)
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes),
        )

    def plan(self, *, source: LayoutSource | None = None) -> LayoutPlan:
        """The block as an ordinary `LayoutPlan`, so the existing readers work.

        `svgpreview.render_svg`, `readability.check` and the landing step all take
        a `LayoutPlan`, and a local picture that was its own type would need a
        second copy of each.  This is the whole of the conversion.

        536: the parts go through :func:`_parts_with_identity` — the same stamp
        the page plan makes, from the same block — so a single island's own
        picture states its group and island instead of coming out anonymous.  A
        block with no group still emits its parts verbatim (bytes and digest
        unchanged).
        """
        return LayoutPlan(
            source=source or LayoutSource(),
            parts=_parts_with_identity(self),
            segments=list(self.segments),
            junctions=list(self.junctions),
            labels=list(self.labels),
            power_symbols=list(self.power_symbols),
            texts=list(self.texts),
            notes=[ISLAND_LAYOUT_KIND, *self.notes],
        )


def island_blocks(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: IslandBudget | None = None,
) -> list[IslandBlock]:
    """Every island of a presentation, each in its own local frame.

    530F: the document's own `name` for an island travels with it.  It is looked
    up here rather than inside :func:`layout_island` because the local picture is a
    function of a *subgraph* (id, role, parts) and the name is not one — the layout
    never reads it, so nothing below this line is allowed to start.  What the name
    does here is exactly one thing: become a note on the block, which the page plan
    and the compile result both carry up (`PackedPage.plan`).
    """
    book = {str(key): value for key, value in profiles.items()}
    names = {
        island.id: island.name
        for island in presentation.effective_islands()
        if island.name
    }
    blocks: list[IslandBlock] = []
    for subgraph in island_subgraphs(circuit, presentation):
        block = layout_island(circuit, subgraph, book, budget=budget)
        name = names.get(subgraph.island_id)
        if name:
            block.notes.insert(0, island_name_note(subgraph.island_id, name))
        blocks.append(block)
    return blocks


# ------------------------------------------------------------- the page (520m)


#: ``role -> (column, row)`` for the classic flyback page.  Row 0 is the **top**
#: row, row 1 the bottom one, and the columns run left to right.
#:
#: 岳's ruling (2026-10-20) fixes the three that matter and this table is where
#: it is written down:
#:
#:     primary（HVDC 输入）在**左**  /  bridge（T1 + U5，跨隔离界）在**中间**
#:     secondary（D3 + 输出电容）在**右**  /  feedback 靠近 bridge 的 U5 那一侧
#:     control 靠近 primary
#:
#: The two rows are what makes the last two sentences true *and* keeps the first
#: three readable.  The bottom row is the power stage, left to right — 正边 /
#: 变压器 / 副边 — which is the picture 岳 asks to be recognisable at a glance.
#: The top row holds the two blocks that belong to a neighbour rather than to the
#: chain: `control` sits directly above `primary` (it is the controller's own
#: network), and `feedback` sits directly above `bridge`, which is where `U5` is
#: — the optocoupler is the upper of the bridge's two parts, so "靠近 U5 那一侧"
#: is the bridge's **top** side, and that is exactly where `feedback` lands.
ISLAND_SLOTS: tuple[tuple[str, int, int], ...] = (
    ("primary", 0, 1),
    ("control", 0, 0),
    ("bridge", 1, 1),
    ("feedback", 1, 0),
    ("secondary", 2, 1),
)


#: ``S-01``'s blank band as a fraction of the sheet's height — the default of
#: :attr:`PageBudget.bottom_blank`, stated here as well because the compiler's
#: refusal text quotes it (`drawcompiler._try_island_variants`).  岳's own pages
#: bracket it: the flyback's content sits in the top third of its 1170x825 sheet
#: and the golden FOC page's lowest part is 288 of 1170 units up (24.6% clear),
#: so 「图下方留 ~15% 空白」 is the round number both satisfy.
BOTTOM_BLANK = 0.15


@dataclass(frozen=True)
class PageBudget:
    """What the page packer may use: the channels, and the lattice."""

    #: The lattice every island's **offset** is snapped to, so a part that was on
    #: the local lattice stays on the page's own (`drawcompiler.GRID`'s value).
    grid: float = 5.0
    #: The gap between the two rows of one column — an ordinary wiring channel.
    channel: float = 40.0
    #: The gap **between columns**.  520m made this 220 and called it the
    #: isolation barrier; 520n takes that back, because 岳 says the barrier idea
    #: was his own habit and not a rule of the drawing — 「正边↔副边之间那道 ~160
    #: 的缝他明说：顺手排的，原理图没这么多规矩」.  So the seam is now only "enough
    #: that two clusters still read as two clusters", and it is deliberately
    #: slightly wider than :attr:`channel` for that reason alone — not because a
    #: page is required to have an isolation gap, and **not** as an electrical
    #: constraint.  Measured cost of leaving 220 in place: page area/part
    #: 6.90x 岳's instead of 4.91x, for nothing.
    barrier: float = 80.0
    #: Blank space around the whole page.
    margin: float = 20.0
    #: The sheet the page must fit, or ``None`` for "the drawing defines its own
    #: frame" — the same convention `compiler.CompileBudget.page_box` uses.
    page_box: Box | None = None
    #: ``S-01``'s second half: the fraction of the sheet's **height** that stays
    #: blank below the drawing.  岳's own pages are the two measurements this
    #: number brackets — the flyback's content sits in the top third of its sheet
    #: (``evidence/521``: y 519…790 of 825), and the golden FOC page's lowest part
    #: is 288 units above the bottom of a 1170-unit sheet, i.e. 24.6% clear.  The
    #: rule is stated as "about 15%" (`docs/schematic-style-spec.md` S-01) and 0.15
    #: is the round number both pages satisfy.  A budget with no ``page_box`` has
    #: no sheet height to take a fraction of, so this is **not** evaluated then:
    #: the flyback island page as packed without a sheet is byte-identical to what
    #: it was before this field existed.
    bottom_blank: float = BOTTOM_BLANK
    #: ``S-01``'s first half: page-coordinate rectangles the drawing may not
    #: enter — in practice the sheet's title block (`core.pageframe` derives it).
    #: The packer's repair is to **lift** the whole page above them (see
    #: :func:`pack_islands`), because the keep-outs a page states are the bottom
    #: corners and the islands are packed upward from the sheet's bottom.
    keepouts: tuple[Box, ...] = ()


@dataclass
class PackedPage:
    """The five islands as one page: rigid blocks, and the channels between them.

    Every block here has already been moved whole (:meth:`IslandBlock.translated`)
    and **nothing inside one was recomputed** — that is what makes an island a
    rigid block, and it is also why the page cannot accidentally wire two islands
    together: the only thing that changed between a block's local frame and this
    page is one ``(dx, dy)`` per island.
    """

    blocks: list[IslandBlock] = field(default_factory=list)
    offsets: dict[str, tuple[float, float]] = field(default_factory=dict)
    slots: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: ``column -> (x0, x1, width)``, left to right.
    columns: list[tuple[float, float, float]] = field(default_factory=list)
    #: ``column -> (gap, the two row heights)``, so a reader can check the spacing.
    gaps: dict[int, float] = field(default_factory=dict)
    #: The keep-outs the packer was handed, echoed back so a reader (and the
    #: compiler's refusal text) can check the packing against the same boxes
    #: without keeping a second copy of the budget.
    keepouts: tuple[Box, ...] = ()
    #: The y the drawing was packed **up** from: `PageBudget.margin`, unless a
    #: keep-out or the bottom blank band raised it.  A reader that wants to know
    #: why the page sits where it does reads this, not the margin.
    floor: float = 0.0
    #: ``island id -> the keep-out it is still inside``, and it is empty by
    #: construction — the floor clears every keep-out that shares the drawing's
    #: x-range before anything is placed.  It is computed anyway, because an empty
    #: list that nothing ever checks is how a rule stops being enforced: the
    #: compiler refuses a page that has one (`drawcompiler._try_island_variants`),
    #: and the packing test forces one.
    keepout_conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def bbox(self) -> Box:
        """Everything the page draws, bounded — the block `bbox`es, unioned."""
        boxes = [block.bbox() for block in self.blocks]
        if not boxes:
            return (0.0, 0.0, 0.0, 0.0)
        return (
            min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes),
        )

    def plan(self, *, source: LayoutSource | None = None) -> LayoutPlan:
        """The page as one ordinary `LayoutPlan` — the whole point of the batch.

        Every island's parts, wires, junctions, names, flags and text boxes, in one
        document, so the *existing* readability checker, preview writer and
        landing step can consume the page without knowing that islands exist.

        The flags are the half 530A added here: every block has carried its own
        since :meth:`IslandBlock.plan`, but *this* is the conversion the compiler
        and the landing step actually read (`drawcompiler._try_island_variants`,
        `drawapply.module_plan`), so a block-level `power_symbols` that stopped
        here would be a flag drawn nowhere — and, worse, one `readability` never
        measured, since the gate is handed this plan too.
        """
        parts: list[LayoutPart] = []
        segments: list[LayoutSegment] = []
        junctions: list[LayoutJunction] = []
        labels: list[LayoutLabel] = []
        power_symbols: list[LayoutPowerSymbol] = []
        texts: list[LayoutText] = []
        for block in self.blocks:
            # 536: an archipelago block states which group it belongs to, and then
            # every part it carries is stamped with that group and this island —
            # the plan is the machine-readable statement the archipelago check
            # reads, so the identity cannot stop at the block.  The stamp is
            # `_parts_with_identity`'s, the same one `IslandBlock.plan` makes, and
            # a block with no group (every island page this module drew before
            # 536) still extends its parts **as they are**: no field is filled in,
            # so its bytes and its digest are unchanged.
            parts.extend(_parts_with_identity(block))
            segments.extend(block.segments)
            junctions.extend(block.junctions)
            labels.extend(block.labels)
            power_symbols.extend(block.power_symbols)
            texts.extend(block.texts)
        #: The blocks' own accounts, carried up with the island named on each line.
        #: A block is where a downgrade happens (`_add_boundary_names`'s "no clear
        #: way out", `_route`'s "no clear Manhattan route", 530A's
        #: `island-single-name` lint), and this plan is what the gate, the landing
        #: step and the report read — so a note that stopped at the block would be
        #: a downgrade nobody outside this module can read about, which is the one
        #: thing 520E's accounting discipline forbids.  `geometry_sha256` excludes
        #: notes (052 sec.4), so carrying them changes no picture and no digest.
        notes: list[str] = [ISLAND_PAGE_KIND, *self.notes]
        for block in self.blocks:
            notes.extend(f"[{block.island_id}] {note}" for note in block.notes)
        return LayoutPlan(
            source=source or LayoutSource(),
            parts=parts,
            segments=segments,
            junctions=junctions,
            labels=labels,
            power_symbols=power_symbols,
            texts=texts,
            notes=notes,
        )


def pack_islands(
    blocks: Sequence[IslandBlock], *, budget: PageBudget | None = None
) -> PackedPage:
    """Put the islands on one page as rigid blocks, with a channel between them.

    Three rules, in the order they are decided:

    1. **which column and row** — :data:`ISLAND_SLOTS`, by the island's `role`.
       An island whose role the table does not name (a spec that declares islands
       without roles, or a role this batch does not know) gets a column of its own
       to the right of the named ones, in the bottom row, in the order the blocks
       arrive — a place on the page, rather than being dropped or being laid on
       top of a block that *is* placed.
    2. **how wide the page is** — a column is as wide as its widest block, and the
       gaps between columns are :attr:`PageBudget.barrier`.
       Rows inside a column are separated by :attr:`PageBudget.channel`.
    3. **where in the column** — horizontally centred, **bottom-aligned** in the
       bottom row and **top-aligned** in the top row.  Aligning the two rows to
       the page's own edges is what makes the top row read as a row; centring
       horizontally is what stops a narrow block (the flyback's `control` is 79
       units wide against `primary`'s 475) from looking like a mistake.
    4. **how high the page's bottom is** — the **floor** (:func:`_page_floor`), the
       y the bottom row is packed *up from*.  It is :attr:`PageBudget.margin`
       unless the sheet says otherwise, and the two things that raise it are
       ``S-01``'s halves: the bottom blank band (a fraction of the stated sheet's
       height) and the **title-block keep-out** — the whole page is lifted above
       every keep-out that shares the drawing's x-range, which is the repair the
       rule calls for, because the keep-outs a page states are the *bottom* corners
       and content that cannot be lifted clear of one cannot be placed on that
       sheet at all.  A floor that leaves no room is therefore reported (the
       keep-out it cleared, the band it honoured, and the page it no longer fits)
       rather than quietly drawn over — the compiler refuses such a page
       (`drawcompiler._try_island_variants`).

    The result carries its own numbers (`columns`, `gaps`, `offsets`, `floor`,
    `keepouts`) so a reader can check the spacing without re-deriving a single
    block's size.
    """
    budget = budget or PageBudget()
    slots = _page_slots(blocks)
    columns: dict[int, list[IslandBlock]] = {}
    for block in blocks:
        columns.setdefault(slots[block.island_id][0], []).append(block)
    order = sorted(columns)

    widths: dict[int, float] = {}
    for column in order:
        widths[column] = max(
            block.bbox()[2] - block.bbox()[0] for block in columns[column]
        )

    x0: dict[int, float] = {}
    gaps: dict[int, float] = {}
    cursor = budget.margin
    for index, column in enumerate(order):
        x0[column] = cursor
        cursor += widths[column]
        if index + 1 < len(order):
            gaps[column] = budget.barrier
            cursor += budget.barrier

    heights: dict[tuple[int, int], float] = {}
    for block in blocks:
        column, row = slots[block.island_id]
        box = block.bbox()
        heights[(column, row)] = box[3] - box[1]

    column_height: dict[int, float] = {}
    for column in order:
        top = max(
            (heights[(column, row)] for (_c, row) in heights
             if _c == column and row == 0),
            default=0.0,
        )
        bottom = max(
            (heights[(column, row)] for (_c, row) in heights
             if _c == column and row == 1),
            default=0.0,
        )
        column_height[column] = top + bottom + (budget.channel if top else 0.0)
    body = max(column_height.values()) if column_height else 0.0
    floor, floor_account = _page_floor(budget, x0, widths, order)
    page_top = floor + body

    page = PackedPage(slots=slots, keepouts=tuple(budget.keepouts), floor=floor)
    for block in blocks:
        column, row = slots[block.island_id]
        box = block.bbox()
        centre = (box[0] + box[2]) / 2.0
        dx = _snap(x0[column] + widths[column] / 2.0 - centre, budget.grid)
        if row == 1:
            # **Up**, not nearest: the floor is a bound the bottom row may not go
            # below, and `_snap` rounds to the nearest lattice point — a floor of
            # 190 with a block whose bottom is at 66.5 off the lattice lands the
            # block 1.5 units *inside* the title block it was lifted to clear.
            dy = _snap_up(floor - box[1], budget.grid)
        else:
            dy = _snap(page_top - box[3], budget.grid)
        moved = block.translated(dx, dy)
        page.blocks.append(moved)
        page.offsets[block.island_id] = (dx, dy)

    for index, column in enumerate(order):
        page.columns.append((
            x0[column], x0[column] + widths[column], widths[column],
        ))
        del index

    for block in page.blocks:
        box = block.bbox()
        for index, keep in enumerate(budget.keepouts):
            if _overlaps(box, keep):
                page.keepout_conflicts.append(
                    f"island {block.island_id!r} at "
                    f"({box[0]:g}, {box[1]:g})-({box[2]:g}, {box[3]:g}) is inside "
                    f"keep-out keepouts[{index}] "
                    f"({keep[0]:g}, {keep[1]:g})-({keep[2]:g}, {keep[3]:g})"
                )

    page.notes.append(
        f"{ISLAND_PAGE_KIND}: {len(page.blocks)} island block(s) in "
        f"{len(order)} column(s); channel {budget.channel:g} between rows, "
        f"{budget.barrier:g} between columns; "
        f"page {cursor + budget.margin - budget.margin:g} x {body:g} before margins"
    )
    page.notes.extend(floor_account)
    for block in page.blocks:
        dx, dy = page.offsets[block.island_id]
        page.notes.append(
            f"island {block.island_id!r} (role {block.role or '-'}) at "
            f"({dx:g}, {dy:g}) — moved whole, nothing inside recomputed"
        )
    page.notes.append(
        "no wire joins two islands: the crossing nets are expressed by their "
        "own name in each island (岳: 岛内地线连，岛间名字接)"
    )
    page.notes.extend(
        f"keep-out conflict: {line}" for line in page.keepout_conflicts
    )
    if budget.page_box is not None:
        box = page.bbox()
        fits = (
            budget.page_box[0] <= box[0] and box[2] <= budget.page_box[2]
            and budget.page_box[1] <= box[1] and box[3] <= budget.page_box[3]
        )
        page.notes.append(
            f"page_box {budget.page_box}: the drawing "
            f"{'fits' if fits else 'does NOT fit'} "
            f"(drawing extent {tuple(round(v, 1) for v in box)})"
        )
    return page


def _page_floor(
    budget: PageBudget,
    x0: Mapping[int, float],
    widths: Mapping[int, float],
    order: Sequence[int],
) -> tuple[float, list[str]]:
    """The y the bottom row is packed up from, and the account of how it was set.

    Three things can raise the floor above :attr:`PageBudget.margin`, and each is
    ``S-01``'s own sentence read one clause at a time:

    * **the stated sheet's blank band** — ``bottom_blank`` of the sheet's height,
      the 「整图下方留白」 half.  It needs a sheet to take a fraction of, so a
      budget with no ``page_box`` is left alone: the drawing defines its own frame
      and there is no page height to be 15% of.
    * **the keep-outs that share the drawing's x-range** — the drawing is lifted
      above the highest of them, which is 「内容不进入标题栏矩形」.  The x-test is
      what keeps a keep-out in a corner the blocks never reach from costing page
      height: a bottom-left title block on a page whose islands are packed to the
      right lifts nothing.
    * both at once, in which case the higher wins — the two rules are independent,
      not alternatives.

    Returns the floor and the note lines that explain it.  The account is emitted
    only when the floor is **not** the plain margin, so a page with no sheet (every
    island page before this batch) keeps the note list it had.
    """
    floor = budget.margin
    account: list[str] = []
    if order:
        left = min(x0[column] for column in order)
        right = max(x0[column] + widths[column] for column in order)
    else:
        left = right = budget.margin
    covered = [
        keep for keep in budget.keepouts
        if keep[0] < right and left < keep[2]
    ]
    if budget.page_box is not None and budget.bottom_blank > 0:
        height = budget.page_box[3] - budget.page_box[1]
        band = budget.bottom_blank * height
        if budget.page_box[1] + band > floor:
            floor = budget.page_box[1] + band
            account.append(
                f"S-01 blank band: the sheet is {height:g} tall, so the drawing "
                f"starts at y={floor:g} — {budget.bottom_blank:.0%} of the sheet "
                "is left blank below it"
            )
    if covered:
        top = max(keep[3] for keep in covered)
        if top > floor:
            floor = top
        accounted = ", ".join(
            f"({keep[0]:g}, {keep[1]:g})-({keep[2]:g}, {keep[3]:g})"
            for keep in covered
        )
        account.append(
            f"S-01 keep-out: {len(covered)} keep-out box(es) share the drawing's "
            f"x-range {left:g}..{right:g} — {accounted} — so the drawing is packed "
            f"up from y={floor:g}, above every one of them"
        )
    return floor, account


def _page_slots(
    blocks: Sequence[IslandBlock],
) -> dict[str, tuple[int, int]]:
    """``island id -> (column, row)``, named roles first and the rest to the right.

    The first block of a column is the one that sets its row order; a **second**
    block whose role claims a slot another block already holds is moved to a
    column of its own rather than sharing one, because two islands in one slot is
    two pictures printed on each other.  A spec with two `primary` islands is
    wrong in a way 520j's parser already refuses (one part, one island), but a
    spec with two islands of one *role* is not, and this must not silently
    overlap them.
    """
    known = {role: (column, row) for role, column, row in ISLAND_SLOTS}
    out: dict[str, tuple[int, int]] = {}
    taken: set[tuple[int, int]] = set()
    next_column = 0
    for role, column, row in ISLAND_SLOTS:
        del role
        next_column = max(next_column, column + 1)
    for block in blocks:
        slot = known.get(block.role)
        if slot is not None and slot not in taken:
            out[block.island_id] = slot
            taken.add(slot)
    for block in blocks:
        if block.island_id in out:
            continue
        out[block.island_id] = (next_column, 1)
        next_column += 1
    return out


def island_page(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: IslandBudget | None = None,
    page_budget: PageBudget | None = None,
) -> PackedPage:
    """The whole multi-island page: layout every island, then pack them."""
    return pack_islands(
        island_blocks(circuit, presentation, profiles, budget=budget),
        budget=page_budget,
    )


# ----------------------------------------------------------------- the placer


def layout_island(
    circuit: CircuitSpec,
    subgraph: IslandSubgraph,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: IslandBudget | None = None,
) -> IslandBlock:
    """One island's local picture: every part beside the pin it serves, then wired.

    Three steps and one rule.  The anchor (a 3-pin-or-more part, `DESIGN` §1.1)
    sits at the local origin; every other part hangs off the pin it shares with the
    part nearer the anchor (:func:`place_service_tree`); the island's own segments
    of its nets are then wired between the pins they actually join.  The anchor
    choice is made from the island's own signal nets, so a busier two-pin part
    cannot take the centre from the IC the island is about.

    A thin island is not refused and not special-cased: an island with one part is
    an anchor with nothing beside it, and an island whose every net crosses is a
    set of one-pin segments — every one of which still gets its own **name**, which
    is what makes it a place on the page rather than a pile of symbols.
    """
    budget = budget or IslandBudget()
    book = {str(key): value for key, value in profiles.items()}

    facts = _facts(subgraph, circuit, book)
    anchor = anchor_of(facts, subgraph)
    placement = place_service_tree(
        facts, subgraph, anchor, book=book, circuit=circuit, budget=budget,
    )
    origins = placement.origins
    poses = placement.poses
    ring = [anchor, *subgraph.bfs_order(anchor)]

    extents = {
        part_id: _part_box(book[circuit.part(part_id).symbol_ref],
                           poses[part_id], origins[part_id])
        for part_id in ring
    }
    obstacles = [
        pose_box(book[circuit.part(part_id).symbol_ref].body,
                 rotation=poses[part_id].rotation, mirror=poses[part_id].mirror,
                 ox=origins[part_id][0], oy=origins[part_id][1])
        for part_id in ring
    ]
    obstacles = [box for box in obstacles if box is not None]
    radius = _island_radius(origins, extents, anchor, budget)

    block = IslandBlock(
        island_id=subgraph.island_id, role=subgraph.role, anchor=anchor,
        ring_radius=radius, order=list(subgraph.bfs_order(anchor)),
        # 536: which group's drawing this island is a piece of (empty for a
        # legacy island list that states none).
        group=subgraph.group,
    )
    block.notes.extend(placement.notes)
    # 530E, `DESIGN` §5.6 L3: an island the clustering derived is **drawn** (a
    # partition is not refused for being unnamed) and the page says where it came
    # from.  The note lives here rather than in the compiler so the block, the page
    # plan and the compile result all carry the same sentence.
    if subgraph.island_id.startswith(AUTO_ISLAND_PREFIX):
        block.notes.append(derived_cluster_note(subgraph.island_id))
    for part_id in sorted(ring):
        part = circuit.part(part_id)
        profile = book[part.symbol_ref]
        block.parts.append(LayoutPart(
            part_id=part_id, symbol_ref=part.symbol_ref,
            symbol_hash=profile.geometry_hash(),
            x=origins[part_id][0], y=origins[part_id][1],
            rotation=float(poses[part_id].rotation), mirror=poses[part_id].mirror,
            reference=part_id,
        ))

    tips = _tips(book, circuit, poses, origins)
    # 531: the parts' own rows are read **before** the routing, not after it. The
    # rows are a function of the origins and poses alone, so they are known here —
    # and the router has to know them: a conductor printed through a part's own
    # designator is `text-on-wire` with a ``texts[i]`` first, which 530F made a
    # hard refusal, and a router that only learns about the rows afterwards cannot
    # undo it (`evidence/531/report.md` §5).
    part_rows = {
        part_id: [
            (kind, text, box)
            for kind, text, box in symbol_rows(
                book[circuit.part(part_id).symbol_ref], origins[part_id],
                reference=part_id, value=circuit.part(part_id).value,
                pose=poses[part_id],
            )
        ]
        for part_id in ring
    }
    field = _field(
        book, circuit, poses, origins, extents, tips,
        rows=[box for rows in part_rows.values() for _k, _t, box in rows],
    )
    drawn: list[tuple[str, list[tuple[float, float]]]] = []
    for index, net in enumerate(subgraph.wired_nets):
        _wire_net(net, tips, field, radius, budget, block, index, drawn)

    # The parts' own rows take their side first, and the boundary names dodge
    # them.  The other order was measured and it does not fit: on the flyback's
    # `primary` island the `PGND` name sits at `C6.2`'s tip, which is the very
    # side `C6`'s own value wants, and a two-row value block has nowhere else
    # within reach of its part — while a one-word name has six ways out.  The
    # name's *anchor* does not move either way (it is the segment's boundary end
    # and that is the electrical fact); only its text box does.
    _add_texts(block, ring, circuit, book, origins, poses, obstacles, budget,
               hidden_values=placement.hidden_values)
    _add_boundary_names(
        block, subgraph, tips, poses, book, circuit, field, extents, budget, drawn,
    )
    _drop_pressed_texts(block, circuit, book)
    _account_decap(facts, subgraph, anchor, placement, circuit, book, block, budget)

    wired = len(subgraph.wired_nets)
    crossing = len(subgraph.crossing_nets)
    named = len(block.labels)
    flagged = len(block.power_symbols)
    lonely = len(subgraph.single_pin_nets)
    wired_internal = sum(1 for net in subgraph.wired_nets if not net.crossing)
    block.notes.append(
        f"island {subgraph.island_id!r} ({subgraph.role or 'no role'}): "
        f"{len(subgraph.parts)} part(s), anchor {anchor} at the local origin, "
        f"island reach {radius:g}; "
        f"{wired} net(s) wired here ({wired_internal} internal + "
        f"{wired - wired_internal} crossing segment(s)), "
        f"{named} label(s) and {flagged} rail/ground flag(s) drawn at the "
        f"{crossing} crossing net(s)"
        + (f" and the {lonely} one-pin net(s)" if lonely else "")
    )
    if not subgraph.wired_nets:
        block.notes.append(
            f"island {subgraph.island_id!r} holds no two pins of any one net, so "
            "no wire is drawn here: every net reaching it is a one-pin crossing "
            "segment, and 岳's 「岛内那一段」 is that single pin.  The name at each "
            "of those pins is the whole of what this island contributes."
        )
    return block


# --------------------------------------------------------------------- poses


def _posed_vector(
    vector: tuple[float, float], rotation: float, mirror: bool
) -> tuple[float, float]:
    """A symbol-local *direction* through a pose — `geometry.transform_point`'s fold.

    The same rotation-then-mirror order that function measured (189A2), without
    its origin term and its rounding: a direction has no origin, and rounding a
    unit vector is a second convention waiting to disagree with the first.
    """
    rad = math.radians(rotation)
    cos_v, sin_v = math.cos(rad), math.sin(rad)
    x = vector[0] * cos_v - vector[1] * sin_v
    if mirror:
        x = -x
    return (x, vector[0] * sin_v + vector[1] * cos_v)


def _pin_outward(profile: SymbolProfile, pin_number: str, pose: SymbolPose) -> tuple[float, float]:
    """Which way this pin points once the symbol is posed (a unit vector)."""
    pin = profile.pin(pin_number)
    if pin is None:
        return (0.0, -1.0)
    axis = _PIN_AXIS.get(pin.direction)
    if axis is None:
        length = math.hypot(pin.tip[0], pin.tip[1])
        axis = (pin.tip[0] / length, pin.tip[1] / length) if length else (0.0, -1.0)
    return _posed_vector(axis, pose.rotation, pose.mirror)


def _facing_pose(
    profile: SymbolProfile, pin_number: str, wanted: tuple[float, float]
) -> SymbolPose:
    """The legal pose whose ``pin_number`` points most nearly along ``wanted``.

    Ties go to the profile's own pose order, so the same documents give the same
    picture.  A part with no pin to turn (`pin_number` not in the profile) takes
    the pose that leaves the most pins pointing outward — a passive the island
    wires to nothing here still gets a sane orientation rather than the first
    rung by accident.
    """
    best: SymbolPose | None = None
    best_score = -math.inf
    for pose in profile.poses:
        if pin_number and profile.pin(pin_number) is not None:
            outward = _pin_outward(profile, pin_number, pose)
        elif profile.pins:
            outward = (
                sum(_pin_outward(profile, pin.number, pose)[0] for pin in profile.pins),
                sum(_pin_outward(profile, pin.number, pose)[1] for pin in profile.pins),
            )
            length = math.hypot(*outward) or 1.0
            outward = (outward[0] / length, outward[1] / length)
        else:
            outward = (0.0, -1.0)
        score = outward[0] * wanted[0] + outward[1] * wanted[1]
        if score > best_score + 1e-12:
            best, best_score = pose, score
    return best if best is not None else SymbolPose()


def _anchor_pose(profile: SymbolProfile) -> SymbolPose:
    """The hub's pose: the profile's own first legal one.

    The hub is the part the ring is arranged *around*, so there is no direction
    for it to face; taking the profile's own first pose keeps the choice out of
    this module.
    """
    return profile.poses[0] if profile.poses else SymbolPose()


# -------------------------------------------------------------------- geometry


def _snap(value: float, grid: float) -> float:
    """``value`` on the compilation lattice, nearest — not the ladder's floor."""
    return round(value / grid) * grid if grid > 0 else value


def _part_box(profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float]) -> Box:
    """The box a placed part occupies: its drawn body and every pin tip.

    The same reading `drawcompiler._part_box` makes, and for the same reason: the
    tips are where wires arrive and the body is what text may not land on, so a
    box that held only one of the two would let the ring's spacing be decided by
    half the part.
    """
    xs: list[float] = []
    ys: list[float] = []
    body = pose_box(profile.body, rotation=pose.rotation, mirror=pose.mirror,
                    ox=origin[0], oy=origin[1])
    if body is not None:
        xs.extend([body[0], body[2]])
        ys.extend([body[1], body[3]])
    for pin in profile.pins:
        x, y = _posed_point(pin.tip, pose, origin)
        xs.append(x)
        ys.append(y)
    if not xs:
        return (origin[0], origin[1], origin[0], origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


def _posed_point(
    local: tuple[float, float], pose: SymbolPose, origin: tuple[float, float]
) -> tuple[float, float]:
    """A symbol-local point through a pose — `core.geometry.transform_point` itself."""
    from ..core.geometry import transform_point

    return transform_point(
        local[0], local[1], rotation=pose.rotation, mirror=pose.mirror,
        ox=origin[0], oy=origin[1],
    )


def _snap_up(value: float, grid: float) -> float:
    """``value`` on the lattice, upward — a radius may only grow."""
    if grid <= 0:
        return value
    return math.ceil(value / grid) * grid


# ------------------------------------------------------------------- wiring


def _tips(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> dict[IslandPin, tuple[float, float]]:
    """Every pin of this island, where the pose and the origin put it."""
    out: dict[IslandPin, tuple[float, float]] = {}
    for part_id, origin in origins.items():
        profile = book[circuit.part(part_id).symbol_ref]
        for pin in profile.pins:
            out[IslandPin(part_id=part_id, pin=pin.number)] = _posed_point(
                pin.tip, poses[part_id], origin,
            )
    return out


def _field(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
    extents: Mapping[str, Box],
    tips: Mapping[IslandPin, tuple[float, float]],
    rows: Sequence[Box] = (),
) -> "_Field":
    """Everything a route has to keep away from, measured once.

    Four kinds of thing, and they are not the same obstacle:

    * **bodies** — the drawn extent of a symbol.  A wire through one is the defect
      the readability contract calls `wire-through-body`;
    * **pins** — another net's pin tip.  A wire that runs over one joins two nets
      the schematic keeps apart, whether or not any wire has been drawn there yet
      (measured: `HVDC`'s first route on the flyback's `primary` island ran along
      ``y = -135`` and straight over `R3.2`, which carries `CLAMP_B`);
    * **leads** — the segment a pin draws *inward* from its tip.  A wire that
      doubles back along its own pin's lead hides the pin's own escape and is
      `readability`'s `wire-on-pin-line`.
    * **rows** (531) — the box the host prints a part's own designator or value
      in.  A conductor through one is `text-on-wire` with a ``texts[i]`` as its
      first object, i.e. a box *this compiler placed*, and since 530F that is
      **hard** (`drawcompiler.island_gate_violations`: only a row the host prints
      itself is tolerated).  On the island page the router drew `SEC_12V` straight
      through `C13`'s designator row the moment the rows stopped being fictional
      (`evidence/531/report.md` §5), so the rows are an obstacle here exactly as
      another net's pin tip is.
    """
    pins: list[tuple[str, tuple[float, float]]] = []
    leads: list[tuple[str, tuple[tuple[float, float], tuple[float, float]]]] = []
    for part_id, origin in origins.items():
        profile = book[circuit.part(part_id).symbol_ref]
        pose = poses[part_id]
        for pin in profile.pins:
            tip = tips[IslandPin(part_id=part_id, pin=pin.number)]
            axis = _PIN_AXIS.get(pin.direction)
            if axis is None or not pin.length:
                continue
            inner = _posed_point(
                (pin.tip[0] - axis[0] * pin.length,
                 pin.tip[1] - axis[1] * pin.length),
                pose, origin,
            )
            key = f"{part_id}.{pin.number}"
            pins.append((key, tip))
            leads.append((key, (tip, inner)))
    return _Field(
        extents=tuple((part_id, extents[part_id]) for part_id in origins),
        bodies=tuple(
            box for box in (
                pose_box(book[circuit.part(part_id).symbol_ref].body,
                         rotation=poses[part_id].rotation,
                         mirror=poses[part_id].mirror,
                         ox=origins[part_id][0], oy=origins[part_id][1])
                for part_id in origins
            ) if box is not None
        ),
        pins=tuple(pins),
        leads=tuple(leads),
        rows=tuple(rows),
    )


@dataclass(frozen=True)
class _Field:
    """What a route must not run through — see :func:`_field`."""

    #: ``part id -> the part's whole box`` (body **and** pin tips).  A wire that
    #: runs through another part's pin-tip zone is `readability`'s
    #: ``text-overlap ... lands on the drawn extent of parts[…]``, which is why
    #: the zones are here and not only their bodies.
    extents: tuple[tuple[str, Box], ...]
    bodies: tuple[Box, ...]
    pins: tuple[tuple[str, tuple[float, float]], ...]
    leads: tuple[tuple[str, tuple[tuple[float, float], tuple[float, float]]], ...]
    #: Every row the host will print for a placed part (531), **including the
    #: part's own**: unlike a body, which a wire may not cross at all, a row is
    #: this part's own text and a wire through it is `text-on-wire` whatever part
    #: the wire belongs to.
    rows: tuple[Box, ...] = ()


#: How far a **row-driven** outward nudge may take a served part from the pin it
#: serves (531). The number is S-05's own acceptance cap rather than a new one: a
#: decoupling part must stand within 30 of the supply pin it serves
#: (``schematic-style-spec.md`` S-05, the golden board's 16.5 median with a 30
#: ceiling), and a part pushed further out than that is no longer "beside the pin"
#: in the sense every reading in this module is written in. Measured need: the
#: first version of the row walk used whole `budget.channel` steps with no ceiling
#: and moved the flyback's `C13` from 28.8 to 79.7 units off `D3.1`
#: (`evidence/531/report.md` §5) — the fix for one finding became another.
ROW_LEAD_CAP = 30.0


#: How far apart **two decoupling parts on one pin** may be pushed along their own
#: row (531). S-05 asks for ≤ 30 units from the pin to each of them, and the offset
#: adds in quadrature, so the offset S-05 allows is 28.3 — while the second decap
#: has to clear the first one's **body** (41 units tall for the flyback's 220uF SMD),
#: which needs about 45. This number is therefore a *documented breach of S-05* for
#: exactly one part, taken because the alternative is a page the readability gate
#: refuses: the host prints a part's designator itself, so the only levers are to
#: move the part or to hide a **value** — and a designator is never hidden.
DECAP_ROW_CAP = 45.0


#: The categories whose **value** row S-21 never hides — 「R/C/L/IC 的位号和值
#: 永不隐藏」 (岳 2026-10-21, ``schematic-style-spec.md`` S-21).  A part of one of
#: these kinds that cannot print its value without landing on a neighbour has to
#: be **moved** by the placement, or the page is refused; suppressing the row is
#: not available to it.  Every other kind (a MOSFET, a diode, a switch, a
#: transformer, a connector) may lose its value, and its designator is never
#: hidden whatever kind it is.
VALUE_ALWAYS_PRINTED: frozenset[str] = frozenset({
    KIND_RESISTOR, KIND_CAPACITOR, KIND_INDUCTOR, KIND_IC,
})


def value_may_be_hidden(
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    part_id: str,
) -> tuple[bool, str]:
    """May this part's value row be suppressed? And **by what reading**.

    The category is not invented here: it is
    :func:`~boardwise.core.partkind.classify_part`'s own answer, fed the three
    declarations this module has — the CircuitSpec's ``symbol_ref``/``value``
    (the part's own words, 127b's ``DeviceFacts.text``), the spec's own designator
    and the symbol's pin count (the pin floor's input) — and nothing else.  The
    basis is returned beside the answer so a note can quote it, which is the
    discipline `core/partkind.py` states for every caller.

    A symbol no profile covers is **unknown**, and an unknown kind is not an
    IC: S-21's never-hide list is read as a list, so a part this module cannot
    classify keeps the older behaviour (its value may go).
    """
    profile = book.get(circuit.part(part_id).symbol_ref)
    value = circuit.part(part_id).value
    text = " ".join(
        part for part in (circuit.part(part_id).symbol_ref, value) if part
    )
    kind = classify_part(facts=PartDeclarations(
        designator=part_id,
        text=text,
        pins=len(profile.pins) if profile is not None else None,
    ))
    if kind.kind in VALUE_ALWAYS_PRINTED:
        return False, kind.reason
    return True, kind.reason


def _hide_value_row(block: IslandBlock, part_id: str, text: str, reason: str) -> None:
    """Record that this part's value row is **not printed** — plan and note.

    Both halves are the point.  The note is for a reader of the compile result;
    the ``LayoutPart`` flag is the half that reaches the paper: the landing step
    writes the host's own ``valueVisible`` from it, and 531 measured that without
    that write the host paints the row anyway (`evidence/532/report.md` §1).
    """
    for part in block.parts:
        if part.part_id == part_id:
            part.value_visible = False
            break
    block.notes.append(f"{part_id}: the value {text!r} is not drawn — {reason}")


#: S-09's ceiling: a single link bends at most twice, and a candidate that needs
#: more is **dropped**, not fined (``schematic-style-spec.md``, "单根上限 2 弯；
#: 超过就改用标签切断").  The candidate family below is built so it can never
#: exceed this — an L has one bend and a Z has two — so today the filter is a
#: construction invariant rather than a live decision; it is written out because
#: it is the rule, and the next family that adds a bend has to face it.
ROUTE_MAX_BENDS = 2


def _bends(path: Sequence[tuple[float, float]]) -> int:
    """How many corners this polyline turns at (S-09's own count)."""
    return max(0, len(path) - 2)


def _true_crossing(
    a: tuple[float, float], b: tuple[float, float],
    c: tuple[float, float], d: tuple[float, float],
) -> bool:
    """Do two runs **cross** — perpendicular, and strictly inside both?

    S-11's reading, and deliberately not :func:`_run_overlap`'s.  Two wires that
    run along each other for a stretch read as one conductor (that is
    ``foreign_overlap``); two that cross make a cross and continue through.  A
    meeting **at an endpoint** of either run is neither: it is a T, and a T is
    what the editor draws a junction dot on, which is why that case is scored as
    ``landing``/``pin_hits`` — an electrical reading — and not counted here.
    """
    horizontal = (abs(a[1] - b[1]) < 1e-9, abs(c[1] - d[1]) < 1e-9)
    if horizontal[0] == horizontal[1]:
        return False  # parallel (or collinear): never a crossing
    if horizontal[0]:
        (p, q), (r, s) = (a, b), (c, d)
    else:
        (p, q), (r, s) = (c, d), (a, b)
    y = p[1]
    x_low, x_high = min(p[0], q[0]), max(p[0], q[0])
    y_low, y_high = min(r[1], s[1]), max(r[1], s[1])
    x = r[0]
    return x_low + 1e-9 < x < x_high - 1e-9 and y_low + 1e-9 < y < y_high - 1e-9


def _wire_net(
    net: IslandNet,
    tips: Mapping[IslandPin, tuple[float, float]],
    field: _Field,
    radius: float,
    budget: IslandBudget,
    block: IslandBlock,
    index: int,
    drawn: list[tuple[str, list[tuple[float, float]]]],
) -> None:
    """Draw one island's segment of a net: its pins, chained in ring order.

    The chain runs in the order the pins sit around the hub, so a three-pin net
    is two short links between neighbours rather than one link across the middle.
    Each link is routed by :func:`_route`, and each pin whose chain does not end
    there keeps a junction — a pin the net enters and leaves is a node, and a
    reader has to be able to see that.

    ``index`` is this net's position among the island's wired nets, and it is what
    keeps two nets off one another's channel (:func:`_detours`).  ``drawn`` is
    every link placed so far, this net's own included: the router needs both — its
    own earlier links, so a chain does not double back over itself, and other
    nets', so a vertex does not land on a foreign conductor and join two nets the
    schematic keeps apart.
    """
    pinned = [pin for pin in net.pins if pin in tips]
    if len(pinned) < 2:
        return
    pinned = _chain_order(pinned, tips)
    detours = _detours(radius, budget, index, [*field.bodies, *field.rows])
    links: list[list[tuple[float, float]]] = []
    for position in range(len(pinned) - 1):
        first, second = pinned[position], pinned[position + 1]
        routed = _route(
            tips[first], tips[second], field, detours,
            prior=links,
            foreign=[(name, item) for name, item in drawn if name != net.net_id],
            own=(str(first), str(second)),
            net_id=net.net_id,
        )
        if routed is None:
            block.notes.append(
                f"net {net.net_id}: no Manhattan route between {first} and "
                f"{second} within S-09's {ROUTE_MAX_BENDS}-bend ceiling, so this "
                "link is not drawn: the two pins are cut apart and the reader has "
                f"to take {net.net_id} from the names at {first} and {second} "
                "(the degradation S-07 criterion 3 prescribes, recorded rather "
                "than papered over — this page will read as two nets, and a "
                "crossing name at each end is what makes them one)"
            )
            continue
        path, tier, complaints = routed
        if tier > 1:
            block.notes.append(
                f"net {net.net_id}: the link {first} → {second} is a **tier {tier} "
                "route** — it could not be kept out of every foreign object ("
                + "; ".join(complaints)
                + ").  A tier-3 route in particular can *look* like a short to a "
                "reader, which is why it is named here: T3 exists so a failure can "
                "be diagnosed, not so a page can pass (`DESIGN` §6.2)."
            )
        links.append(path)
        block.segments.append(LayoutSegment(net=net.net_id, points=list(path)))
    drawn.extend((net.net_id, link) for link in links)
    _junction_dots(net, tips, links, block)


def _detours(
    radius: float,
    budget: IslandBudget,
    index: int,
    obstacles: Sequence[Box] = (),
) -> list[float]:
    """The coordinates **this** net's links may bend through.

    Two families, and both are needed.  The **obstacle edges** come first: for
    every body, its four sides pushed out by one channel, which is where a wire
    wants to bend — hugging the part it is going around.  A detour taken from the
    ring's own radius instead is a straight line drawn in the middle of nowhere:
    520l's first run of the flyback's `primary` island sent `PGND` from `C6.2`
    straight down to ``y = -234`` (the ring channel) to get around one 17-unit
    body, and that 194-unit run then boxed `C6` in so tightly that neither its
    reference nor its value had a clear side left.  The **ring channels** stay as
    the fallback for a link whose way out is past everything, offset by the net's
    own position so two nets never share a track — sharing is what made the
    ``undeclared-junction`` 520l's router had to be taught to avoid.

    Duplicates and values inside the drawing are dropped: a detour that is not
    outside everything is not a way around anything.

    532 adds two things, both because a **text row** became an obstacle here. The
    rows are passed in beside the bodies, and every obstacle contributes its **raw
    edges** as well as its edges pushed out by a channel. The raw edge is the
    corridor a wire actually needs: a row is not a solid, and
    `textmetrics.TEXT_WIRE_PENETRATION` measures how deep a conductor goes into it
    — a wire running *along* the row's edge penetrates nothing and is not the
    defect. Measured need: on the flyback's `secondary` island the only way from
    `C13.1` up to `D3.1` that neither crosses a body nor prints through the 220uF's
    value row is a two-bend path through the four units between that row's right
    edge and `D3`'s body, and every channel-pushed candidate misses it
    (`evidence/532/raw/`).
    """
    out: list[float] = []
    for box in obstacles:
        out.extend((box[0], box[1], box[2], box[3]))
        for value in (box[0] - budget.channel, box[2] + budget.channel,
                      box[1] - budget.channel, box[3] + budget.channel):
            out.append(value)
    for step in (1, 2, 3):
        value = radius + budget.channel * (index + step)
        out.extend([value, -value])
    unique: list[float] = []
    for value in out:
        if all(abs(value - seen) > 1e-6 for seen in unique):
            unique.append(value)
    return unique


def _route(
    start: tuple[float, float],
    end: tuple[float, float],
    field: "_Field",
    detours: Sequence[float],
    prior: Sequence[Sequence[tuple[float, float]]] = (),
    foreign: Sequence[tuple[str, Sequence[tuple[float, float]]]] = (),
    own: Sequence[str] = (),
    net_id: str = "",
) -> tuple[list[tuple[float, float]], int, list[str]] | None:
    """The best Manhattan path from ``start`` to ``end``, and what "best" means.

    Two L-shapes and, per detour, two Z-shapes — a candidate family, not a search:
    this is a local picture of two to eight parts, and a router with a grid of its
    own would be a second `router.py` with a second set of rules to keep in step
    with the first.  The candidates are **filtered in three tiers, then ranked
    lexicographically**, and both halves are the design (`DESIGN` §6.1/§6.2).

    **The tiers** (each one relaxes one electrical promise, and each relaxation is
    refused unless there is nothing better):

    * **T1** — no body crossed, no foreign pin tip inside a run, and no vertex of
      this path landing on another net's conductor.  This is the target.
    * **T2** — the third promise relaxed: a vertex may land on a foreign
      conductor.  That is the editor's "the dot joins the nets", so T2 is
      already a *short* the drawing is choosing to draw; it is kept because a
      local picture with a wire in it says more than one with a gap, and it is
      named in the island's notes rather than hidden.
    * **T3** — the pin-tip promise relaxed too, and a body crossing allowed.
      T3 is the failure that must be **diagnosable**: it is reported, never
      silently drawn, and a page that lands one is refused by the readability
      gate (`wire-through-body` is a hard violation, `readability.py`).  T3
      exists so a failure can be read, not so a page can pass.

    **The keys**, in order (lower is better) — thirteen slots, and the list is the
    tuple the loop below actually builds::

        1 (crossings)          # a wire through a part: wire-through-body, S-10
        2 (landing+pin_hits)   # a short — ranked second, not fourth
        3 (true_crossings)     # S-11: perpendicular, interior to both runs
        4 (own_tees)           # a vertex on this net's own earlier link: a
                               # junction `_junction_dots` then has to declare
        5 (extent_hits)        # inside another part's pin-tip zone
        6 (text_hits)          # 531: through a row the *host* prints (a part's
                               # designator/value), i.e. `text-on-wire`
        7 (bends)              # S-09: S-09 has no other enforcer now
        8 (foreign_overlap)    # two nets running along each other, collinear
        9 (lead_overlap)       # doubling back along the pin it starts from
       10 (doubled)            # this net's own earlier links
       11 (grazes)            # 542: drawn on or just inside a body's frame —
                               # S-10's 贴框, which `_crosses`'s margin cannot see
       12 (row_hits)           # the host's own name row, printed over a part
       13 (length)             # and only here does length matter

    Key 3 is the one that was missing: ``foreign_overlap`` reads collinear runs
    only (:func:`_run_overlap` returns ``0.0`` the moment the runs are not
    parallel), so until 530C two nets crossing at right angles cost nothing at
    all.  Key 7 is the other: `bends` used to be represented by `length`, which
    is the same number only when nothing detours.  It sits above
    ``foreign_overlap`` on `DESIGN` §6.1's word, and 530B's warning is why that
    is worth saying out loud — a *straight* stub is what 530B's placement bought
    (bends 25 → 10 came from the placement, not from this router), and a key that
    could trade a straight link for a bent one to avoid a collinear overlap would
    spend it.  Key 7 is above key 8, so it cannot.

    Two keys are 530C's own additions to `DESIGN` §6.1's list, both written down
    here because a key list that grows silently is how a router stops being
    explainable.  **Key 4** is the same-net tee — a legal dot, but one
    :func:`_junction_dots` has to declare, and `bends` outranks `doubled`, so a
    candidate can now win on its bend count *and* bring a tee.  **Key 12** is the
    host's own net-name row: it is the page's commonest legibility finding and it
    is a function of the geometry, so it is choosable here; it sits below every
    electrical key and below `bends`, and above `length` only.

    542 adds one more, **key 11**, between ``doubled`` and ``row_hits``: **a run
    drawn on or just inside a body's frame** — the half of S-10's 「不穿/贴器件画框」
    that :func:`_crosses` cannot see, because its 1-unit margin reads "touching an
    edge" as a clearance opinion (`wire-through-body` has the same tolerance).
    A reader cannot tell 贴框 from 穿框, which is why this is a legibility key and
    not a tier: it sits below every electrical key and below `bends`, so it cannot
    buy a short or a bend, and above `row_hits` and `length`, so extra conductor
    length is the price of leaving the frame.  201H's page needed it: `FB_SENSE`
    won key 1 = 0 at 0.5 unit inside `U4`'s lower edge and was the shortest clean
    candidate (180 against 241 for the first channel below the part).

    ``field.bodies`` are the *bodies*, not `drawcompiler._part_box`'s extent: a
    wire that grazes a pin tip is a clearance opinion, one that runs through a
    body is a defect.  The pin *tips* are obstacles of their own here, for the
    reason in the tiers — they are where the other nets start.

    ``own`` is the two endpoint pins, ``"PART.pin"``; their tips and leads are
    the path's own and are not counted against it.  ``foreign`` is
    ``(net name, path)``: the names are carried so a T2/T3 note can name the net
    whose conductor was crossed instead of saying "something".

    ``None`` is returned only when no candidate is Manhattan (:func:`_tidy`) or
    when every one of them needs more than :data:`ROUTE_MAX_BENDS` bends.
    """
    candidates: list[list[tuple[float, float]]] = [
        [start, (end[0], start[1]), end],
        [start, (start[0], end[1]), end],
    ]
    for detour in detours:
        candidates.append([start, (detour, start[1]), (detour, end[1]), end])
        candidates.append([start, (start[0], detour), (end[0], detour), end])

    mine = {str(key) for key in own}
    mine_parts = {key.partition(".")[0] for key in mine}
    #: Rows the **host** will print on the links already drawn — this net's own
    #: earlier ones and every other net's.  They are obstacles for the row this
    #: candidate will bring with it, for the same reason every other pair of
    #: texts is: two name rows on each other are the `text-overlap` finding
    #: `segments[i] + segments[j]`.
    plotted: list[Box] = []
    for name, other in foreign:
        text = name or net_id
        row = wire_name_box(list(other), text) if text else None
        if row is not None:
            plotted.append(row)
    for other in prior:
        row = wire_name_box(list(other), net_id) if net_id else None
        if row is not None:
            plotted.append(row)
    #: (tier, key, path, complaints) for the best candidate of each tier.
    best: dict[int, tuple[tuple[float, ...], list[tuple[float, float]],
                            list[str]]] = {}
    for path in candidates:
        clean = _tidy(path)
        if clean is None:
            continue
        if _bends(clean) > ROUTE_MAX_BENDS:
            continue  # S-09's ceiling: dropped, not fined
        runs = list(zip(clean, clean[1:]))
        crossings = sum(
            1 for run in runs for box in field.bodies if _crosses(*run, box)
        )
        # A vertex of this path lying *inside* a foreign run is the editor's dot,
        # and on a foreign conductor the two nets become one: a short, and a tier
        # decision.  A vertex on one of this net's **own** earlier links is a dot
        # too, but it is legal — the same net either way — so it is a key and not
        # a tier.  It became a key in 530C: `bends` now outranks `doubled`
        # (DESIGN §6.1), so a same-net tee can win on its bend count, and every
        # such tee is one more junction `_junction_dots` has to declare.
        landed: list[str] = []
        landing = 0
        for vertex in clean:
            for name, other in foreign:
                for index in range(len(other) - 1):
                    if _on_run(other[index], other[index + 1], vertex):
                        landing += 1
                        label = name or "an unnamed net"
                        if label not in landed:
                            landed.append(label)
        own_tees = sum(
            1 for vertex in clean
            for other in prior
            for index in range(len(other) - 1)
            if _on_run(other[index], other[index + 1], vertex)
        )
        hits: list[str] = []
        pin_hits = 0
        for key, tip in field.pins:
            if key in mine:
                continue
            if any(_same(tip, point) for point in (start, end)):
                continue
            if any(_on_run(*run, tip) for run in runs):
                pin_hits += 1
                if key not in hits:
                    hits.append(key)
        true_crossings = sum(
            1 for run in runs
            for _name, other in foreign
            for index in range(len(other) - 1)
            if _true_crossing(*run, other[index], other[index + 1])
        )
        foreign_overlap = sum(
            _run_overlap(*run, other[index], other[index + 1])
            for _name, other in foreign
            for run in runs
            for index in range(len(other) - 1)
        )
        # 530C's key 8 then, key 9 now (542 shifted every slot past `text_hits`),
        # widened in 531 from "this path's own two pins" to **every**
        # lead: `readability`'s `wire-on-pin-line` names any pin of any part, and
        # it is one of the nine **electrical** kinds (530F §2.2), so a wire along a
        # foreign pin's lead is the same defect as one along its own. Measured: on
        # the flyback's `secondary` island the router left `C13.1` by running 10
        # units along that pin's own lead line (`segments[13]`, `evidence/531/
        # report.md` §5), which no reader can tell from the pin being unconnected.
        lead_overlap = sum(
            _run_overlap(*run, lead[0], lead[1])
            for _key, lead in field.leads
            for run in runs
        )
        doubled = sum(
            _run_overlap(*run, other[index], other[index + 1])
            for other in prior
            for run in runs
            for index in range(len(other) - 1)
        )
        extent_hits = sum(
            1 for part_id, box in field.extents
            if part_id not in mine_parts
            and any(_crosses(*run, box) for run in runs)
        )
        # 542: a run drawn **on or just inside a body's frame** — the half of
        # S-10's 「不穿/贴器件画框」 that `_crosses` cannot see, because its
        # 1-unit margin deliberately reads "touching an edge" as a clearance
        # opinion rather than a body crossing.  Measured on 201H's feedback
        # island: `FB_SENSE` left `R8.1`, turned at `y = 15` — a channel the
        # detour ladder takes from `U4`'s own value row, 0.5 unit inside that
        # part's lower edge — and ran 91 units across the frame.  Key 1 read 0,
        # so the candidate was tier 1, and it was also the shortest of the clean
        # ones (180 against 241 for the first channel below the part).  Pushed
        # off that inside channel the router picked the next one, `y = 15.5`,
        # which is the edge itself — the same misread from the other side, and
        # the same reason this key is needed rather than a widened `_crosses`.
        grazes = sum(
            1 for run in runs for box in field.bodies if _hugs(*run, box)
        )
        # 531: a run through a **part's own text row**. A different sentence from
        # `extent_hits` above — a wire in a pin-tip zone is a clearance opinion,
        # while `readability` calls this one `text-on-wire` with a ``texts[i]`` as
        # its first object, a box this compiler placed, which 530F made hard
        # rather than tolerated — **and yet it is a key and not a tier**, for a
        # reason that is a measurement: the row model is exact at rot 0 and
        # *deviant* at other poses (the host re-anchors a rotated part's text; see
        # `textmetrics.symbol_rows`). A tier here would let a row this module may
        # have put in the wrong place outrank an electrical promise — measured, on
        # the flyback's `secondary` island: the model's row for `C13` (a
        # `C0603W`, whose declared anchor is off for its mirrored pose) sat across
        # that pin's own tip, and every candidate that respected it left the pin
        # along its lead — `[wire-on-pin-line] segments[13] + parts[C13].1`, an
        # electrical finding. A row is therefore ranked with the *other* legibility
        # keys, below `bends` and below every electrical one, and the hard part of
        # the promise is kept by the gate refusing the page rather than by the
        # router buying it with a defect.
        text_hits = sum(
            1 for run in runs for box in field.rows if _crosses(*run, box)
        )
        # Key 12, the second-to-last: where the host prints this link's own **net
        # name**.  Like the boundary stub's row (`_name_one_net`) it is a text
        # nobody placed, and `readability` measures it as `segments[i]` — the
        # commonest finding on this page (530B's §6: 7 of its 9 `text-overlap`).
        # It sits below every electrical key and below `bends`, so it can never
        # buy a clear row with a short or a bend: all it can do is pick between
        # routes that are otherwise as good, which is what makes it safe.  Above
        # `length`, because a row printed through a part is worse than 20 extra
        # units of conductor.
        row_hits = 0
        if net_id:
            row = wire_name_box(clean, net_id)
            if row is not None:
                row_hits = (
                    sum(1 for part_id, box in field.extents
                        if part_id not in mine_parts and _overlaps(row, box))
                    + sum(1 for box in plotted if _overlaps(row, box))
                )
        key = (
            crossings, landing + pin_hits, true_crossings, own_tees, extent_hits,
            text_hits,
            _bends(clean), foreign_overlap, lead_overlap, doubled,
            grazes, row_hits, _length(clean),
        )

        complaints: list[str] = []
        if crossings:
            complaints.append(f"it crosses {crossings} part body/ies")
        if text_hits:
            complaints.append(
                f"it is printed through {text_hits} row(s) of a part's own "
                "designator/value, which the readability gate refuses as "
                "`text-on-wire` — a row the *compiler* placed, not one the host did"
            )
        if pin_hits:
            complaints.append(
                "it runs over the pin tip(s) " + ", ".join(hits)
                + " — the editor joins what it touches, so this reads as a short"
            )
        if landed:
            complaints.append(
                "a vertex of it lands on a conductor of "
                + ", ".join(landed)
                + " (the editor draws the dot and the two nets become one)"
            )
        tier = 1 if not (crossings or pin_hits or landing) else (
            2 if not (crossings or pin_hits) else 3
        )
        held = best.get(tier)
        if held is None or key < held[0]:
            best[tier] = (key, clean, complaints)
    if not best:
        return None
    tier = min(best)
    key, path, complaints = best[tier]
    return path, tier, complaints


def _run_overlap(
    a: tuple[float, float], b: tuple[float, float],
    c: tuple[float, float], d: tuple[float, float],
) -> float:
    """How far the run ``a``-``b`` lies **on** the run ``c``-``d``, in units.

    Collinear runs only — a perpendicular crossing shares one point and is not a
    doubling back (`layout`'s own rule: two wires that cross continue through).
    """
    if abs(a[0] - b[0]) < 1e-9 and abs(c[0] - d[0]) < 1e-9:
        if abs(a[0] - c[0]) > 1e-6:
            return 0.0
        low = max(min(a[1], b[1]), min(c[1], d[1]))
        high = min(max(a[1], b[1]), max(c[1], d[1]))
        return max(0.0, high - low)
    if abs(a[1] - b[1]) < 1e-9 and abs(c[1] - d[1]) < 1e-9:
        if abs(a[1] - c[1]) > 1e-6:
            return 0.0
        low = max(min(a[0], b[0]), min(c[0], d[0]))
        high = min(max(a[0], b[0]), max(c[0], d[0]))
        return max(0.0, high - low)
    return 0.0


def _tidy(path: Sequence[tuple[float, float]]) -> list[tuple[float, float]] | None:
    """Drop a bend that is not a bend, and refuse a zero-length wire.

    `LayoutPlan` refuses two equal points in a row and a segment of one point
    (``_segments_from``), so the check is the schema's own rather than a second
    opinion about what a wire is.
    """
    out: list[tuple[float, float]] = []
    for point in path:
        if not out or (abs(point[0] - out[-1][0]) > 1e-9
                       or abs(point[1] - out[-1][1]) > 1e-9):
            out.append(point)
    if len(out) < 2:
        return None
    for index in range(len(out) - 1):
        if (abs(out[index][0] - out[index + 1][0]) > 1e-9
                and abs(out[index][1] - out[index + 1][1]) > 1e-9):
            return None  # not Manhattan: refused rather than emitted
    return out


def _crosses(
    a: tuple[float, float], b: tuple[float, float], box: Box, margin: float = 1.0
) -> bool:
    """Does this axis-aligned run cross the box' interior, by more than ``margin``?

    The same "strictly inside, shared edges are not a crossing" reading
    `layout.validate_full` uses — a wire that touches a body's edge is a
    clearance opinion, one that runs through it is a defect, and the two must not
    be the same test.
    """
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    return (
        box[0] + margin < x1 and x0 < box[2] - margin
        and box[1] + margin < y1 and y0 < box[3] - margin
    )


def _hugs(
    a: tuple[float, float], b: tuple[float, float], box: Box
) -> bool:
    """Is this run drawn **on or inside** the box, short of a real crossing?

    S-10 forbids both halves of 「导线不穿/贴器件画框」, and the two halves are
    not the same measurement: `_crosses` deliberately reads a wire that touches a
    body's edge — or that stays within its 1-unit margin inside it — as a
    clearance opinion rather than a body crossing, because that is what
    ``wire-through-body`` means.  A reader cannot tell the difference: the
    conductor is drawn on the part's own rectangle.  So this predicate is the
    legibility half, and it is a **key** in :func:`_route`, never a tier — it
    must never be able to buy a short or a bend.

    The expansion is one micron, so the band is closed at both ends: exactly on
    an edge is inside, one unit off it is not.  A run that does cross the interior
    is not "hugging" either — it is key 1's body crossing and a tier of its own.
    """
    return (
        not _crosses(a, b, box)
        and _crosses(a, b, box, margin=-1e-6)
    )


def _length(path: Sequence[tuple[float, float]]) -> float:
    return sum(
        abs(path[index + 1][0] - path[index][0])
        + abs(path[index + 1][1] - path[index][1])
        for index in range(len(path) - 1)
    )


def _junction_dots(
    net: IslandNet,
    tips: Mapping[IslandPin, tuple[float, float]],
    links: Sequence[Sequence[tuple[float, float]]],
    block: IslandBlock,
) -> None:
    """A dot where three or more of this net's runs meet at one point.

    Two runs meeting at a pin are that pin's own node and need no dot; a run that
    *passes through* another pin of the same net is a T, and a T without a dot is
    the one thing a reader cannot resolve.  The count is of runs at the point,
    which is what a junction is.

    The points tested used to be the net's pins (530B and before).  530C adds
    every **vertex of every link**: with `bends` ranked as a key of its own
    (`DESIGN` §6.1) one link of a chain can now end on the span of a link the
    chain drew after it — `secondary`'s `SEC_12V` did exactly that, and the page
    came back with an `undeclared-junction`.  A router cannot see a link it has
    not drawn yet, so the tee is *declared* instead, which is the first of the two
    ways out `readability` names ("declare the junction or route to the other
    wire's end") and the true one: three runs of one net do meet there.
    """
    points: list[tuple[float, float]] = []
    for pin in net.pins:
        point = tips.get(pin)
        if point is not None:
            points.append(point)
    for link in links:
        points.extend(link)
    seen: list[tuple[float, float]] = []
    for point in points:
        if not any(_same(point, other) for other in seen):
            seen.append(point)
    for point in seen:
        # **Runs**, not links: a link that bends at the point brings two runs to
        # it.  Counting links read a legitimate chain joint (two links meeting
        # end to end) as two, and a link bending on another link's span as two as
        # well — so the tee went undeclared.  Counting runs gives 2 for the joint
        # and 3 for the tee, which is what "three runs meet here" means.
        meeting = sum(
            1
            for link in links
            for index in range(len(link) - 1)
            if _on_run(link[index], link[index + 1], point)
        )
        if meeting >= 3:
            block.junctions.append(
                LayoutJunction(net=net.net_id, x=point[0], y=point[1])
            )


def _same(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


def _on_run(
    a: tuple[float, float], b: tuple[float, float], point: tuple[float, float]
) -> bool:
    """Does the run ``a``-``b`` pass through ``point`` (its ends included)?"""
    if abs(a[0] - b[0]) < 1e-9:  # vertical
        return abs(point[0] - a[0]) < 1e-6 and min(a[1], b[1]) - 1e-6 <= point[1] <= max(a[1], b[1]) + 1e-6
    if abs(a[1] - b[1]) < 1e-9:  # horizontal
        return abs(point[1] - a[1]) < 1e-6 and min(a[0], b[0]) - 1e-6 <= point[0] <= max(a[0], b[0]) + 1e-6
    return False


# ------------------------------------------------------------ boundary names


def _net_components(
    net: IslandNet,
    tips: Mapping[IslandPin, tuple[float, float]],
    segments: Sequence[LayoutSegment],
) -> list[tuple[list[IslandPin], list[tuple[float, float]]]]:
    """The blobs this net's own drawing makes in this island — S-14's unit.

    「一条网的每个连通分量，恰好一个名字」 (`DESIGN` §7.1).  Before 530D the
    drawing named the **net** once per island (`_add_boundary_names` docstring,
    520l's rule: 「每岛每跨岛网恰好一个名」); the rule this file now follows is
    the finer one, and the two agree everywhere except when a net's own wiring
    inside one island comes apart — in which case S-14 asks for the second name,
    because two blobs are two boxes (a reader who sees one conductor and no name
    has no way to know which net it is).

    Built from what is **drawn**, not from what was planned, because that is what
    a reader and the editor both see: the nodes are the net's pin tips and every
    vertex of its links, and two node sets are joined when a run of this net
    reaches them.  A vertex landing **in the span of** another link is a junction
    the editor draws a dot on, so that joins too (`_junction_dots` declares the
    same points); a true **crossing** joins nothing, which is `_true_crossing`'s
    reading and the editor's.  A link the router refused (S-09's bend ceiling,
    §4 criterion 3) leaves the two pins in two components — and the caller then
    names both, which is what makes a cut link still a place on the page.

    Each blob comes back as its **pins** and the **points** it is drawn at.  The
    name is attached at a pin (`_name_one_net`), and every component of a wired net
    holds at least one, because a link always runs between two of the net's own
    pins; the points are what lets the caller ask "does *this* blob already carry a
    name" without re-reading a drawing that has grown stubs since
    (:func:`_component_is_named`), so they are taken here — before any name is
    placed.

    The whole island's blobs are worked out **once, up front**, for the same reason:
    a stub one name draws must not look like part of another name's blob.
    """
    pinned = [pin for pin in net.pins if pin in tips]
    if not pinned:
        return []
    runs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    points: list[tuple[float, float]] = [tips[pin] for pin in pinned]
    for segment in segments:
        if segment.net != net.net_id:
            continue
        for index in range(len(segment.points) - 1):
            first = (segment.points[index][0], segment.points[index][1])
            second = (segment.points[index + 1][0], segment.points[index + 1][1])
            runs.append((first, second))
            points.extend((first, second))
    unique: list[tuple[float, float]] = []
    for point in points:
        if not any(_same(point, other) for other in unique):
            unique.append(point)

    def seat(point: tuple[float, float]) -> int:
        for index, other in enumerate(unique):
            if _same(point, other):
                return index
        return -1  # unreachable: every point above is in `unique`

    parent = list(range(len(unique)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(first: int, second: int) -> None:
        root_a, root_b = find(first), find(second)
        if root_a != root_b:
            parent[max(root_a, root_b)] = min(root_a, root_b)

    for first, second in runs:
        union(seat(first), seat(second))
    for first, second in runs:
        for index, point in enumerate(unique):
            if _on_run(first, second, point):
                union(index, seat(first))
    groups: dict[int, list[IslandPin]] = {}
    for pin in pinned:
        groups.setdefault(find(seat(tips[pin])), []).append(pin)
    return [
        (groups[key], [point for index, point in enumerate(unique) if find(index) == key])
        for key in sorted(groups)
    ]


def _component_is_named(
    block: IslandBlock,
    net_id: str,
    points: Sequence[tuple[float, float]],
) -> bool:
    """Does this blob already carry a name of its own? (S-14, the other half.)

    「一坨里已有旗标的不再重复挂标签」: exactly one name per blob means a blob
    that already has one must be left alone, whether that name is a flag or a
    label.  The two are told apart by the point they sit on — a name is placed at
    a point of its own blob (`_name_one_net` anchors it at a pin tip or at the
    end of a stub that starts on one), and this is the only way to ask the
    question of the drawing rather than of a second list nobody keeps in step.
    """
    seats = [(item.x, item.y) for item in block.labels if item.net == net_id]
    seats.extend(
        (item.x, item.y) for item in block.power_symbols if item.net == net_id
    )
    for seat in seats:
        # A name stands at the far end of its own stub, so the blob it names is
        # the one the stub starts from: the segment of this net that ends at the
        # name's own point.
        for segment in block.segments:
            if segment.net != net_id or len(segment.points) < 2:
                continue
            first = (segment.points[0][0], segment.points[0][1])
            last = (segment.points[-1][0], segment.points[-1][1])
            if _same(seat, first) or _same(seat, last):
                other = last if _same(seat, first) else first
                if any(_same(other, point) for point in points):
                    return True
    return False


def _chain_order(
    pinned: Sequence[IslandPin],
    tips: Mapping[IslandPin, tuple[float, float]],
) -> list[IslandPin]:
    """A net's pins in this island, walked around the hub.

    The order is the angle of each pin's tip about the island's origin, with the
    pin's own name as the tie-break, so it is a function of the geometry and not
    of a dictionary walk.  Both the wiring (:func:`_wire_net`) and the boundary
    name (:func:`_boundary_pin`) read it, and they must: a name attached to a pin
    that is *not* an end of the chain would land in the middle of the net's own
    wire and read as a T.
    """
    return sorted(
        pinned,
        key=lambda pin: (
            math.atan2(tips[pin][1], tips[pin][0]), str(pin),
        ),
    )


def _boundary_pin(
    net: IslandNet,
    pinned: Sequence[IslandPin],
    tips: Mapping[IslandPin, tuple[float, float]],
) -> IslandPin:
    """Which pin of this island's segment carries the name.

    The end of the segment that reaches **farthest from the hub**, which is the
    end facing outward — the direction the next island is in, once 520m has packed
    the blocks and the gap between them is the channel 520l's names run through.

    A one-pin segment (the whole of a crossing net's presence here is one pin —
    the flyback's `bridge` island is eight of them) has only that pin to answer
    with, and it is the right answer: the pin *is* the island's end of the net.
    """
    if len(pinned) == 1:
        return pinned[0]
    ordered = _chain_order(pinned, tips)
    ends = [ordered[0], ordered[-1]]
    return max(ends, key=lambda pin: (math.hypot(*tips[pin]), str(pin)))


def _boundary_ends(
    net: IslandNet,
    pinned: Sequence[IslandPin],
    tips: Mapping[IslandPin, tuple[float, float]],
) -> list[IslandPin]:
    """The pins a boundary name may be attached to, outward end first (532).

    :func:`_boundary_pin` is the rule — the end of the segment farthest from the
    hub, which is the end facing the next island — and it is the **first**
    candidate here, so a name that can be written where the rule wants it still is.
    The second candidate is the segment's other end, offered only because the
    outward end can be a place with no way out at all (`_name_one_net` measures
    it and says so); a pin that is not an end of the chain is never offered, since
    a name in the middle of a run would sit on top of the conductor it names.
    """
    if len(pinned) <= 1:
        return list(pinned)
    ordered = _chain_order(pinned, tips)
    out = [_boundary_pin(net, pinned, tips)]
    for pin in (ordered[0], ordered[-1]):
        if pin not in out:
            out.append(pin)
    return out


def _unit(vector: tuple[float, float]) -> tuple[float, float]:
    """``vector`` as a unit vector, or straight down when it has no length."""
    length = math.hypot(vector[0], vector[1])
    if length < 1e-9:
        return (0.0, -1.0)
    return (vector[0] / length, vector[1] / length)


def _add_boundary_names(
    block: IslandBlock,
    subgraph: IslandSubgraph,
    tips: Mapping[IslandPin, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    field: _Field,
    extents: Mapping[str, Box],
    budget: IslandBudget,
    drawn: Sequence[tuple[str, list[tuple[float, float]]]] = (),
) -> None:
    """One **name** per crossing blob — a flag for a rail, a label for a signal.

    岳's second ruling (2026-10-20) is the whole of this function: 「跨岛网在本岛
    的那一段，用导线连起来；岛与岛之间那一跳，用标签接」.  The wire is
    :func:`_wire_net`'s, which no longer cares whether a net crosses; what is left
    here is the jump — a stub out of the segment's outward end and the net's own
    name at the end of it, which is 520E's mechanism (`_label_for` / `_label_at`)
    applied at an island's boundary instead of at a page's.

    **Exactly one name per blob, and no more** — S-14's law, 「一条网的每个连通
    分量，恰好一个名字」 (``DESIGN`` §7.1).  A name joins the node it touches, so a
    second name on the same blob would say the same thing twice; and *fewer* than
    one would leave that blob electrically untold — the editor would see a wire
    with a pin on it and no way to know which net it is.  Same text in two islands
    is one net, which is how the segments merge (see the module docstring).

    520l's rule was the same statement at the **net's** grain (「每岛每跨岛网恰好
    一个名」); 530D moves it to the blob's, which is finer and agrees with 520l
    everywhere except when one island's own wiring of a net comes apart.  Then the
    finer rule must give the second name: two blobs are two boxes, and a reader
    looking at the one without a name has nothing to read (`DESIGN` §7.1:
    「改的是规则的适用范围，不是立场」).

    Four things a stub may not do, and all four were found by running the hard
    gate over the first version rather than by looking at it:

    1. **run through a body** — `wire-through-body`;
    2. **run collinear with the segment's own wire at that pin** — the stub and the
       first link then lie on top of each other, and the stub's far end becomes a T
       on the net's own wire: the gate's ``undeclared-junction``, measured on
       `secondary`'s `SEC_GND` and `feedback`'s `SEC_12V`;
    3. **run through a pin-tip zone of another part** — `text-overlap … lands on the
       drawn extent of parts[C13]`, which is the stub crossing the space another
       symbol's own pins occupy;
    4. **land its name on a foreign body, a wire, or a part's own rows** — `_add_texts`
       has already placed those, and this runs after it for exactly that reason.

    The stub is tried along the pin's own escape first (`drawcompiler._label_for`'s
    reason — that is what keeps a name off the part it names), then radially
    outward, then the remaining compass points, and the first one that is clear
    wins.

    **530A: which kind of name.** The rule is S-16 — 「地/电源一律旗标，不拉母线」 —
    read with 岳's own scope note, 「一个旗标可汇聚多个就近引脚」:

    * a ``power``/``gnd`` net becomes a **flag** (:func:`_place_flag`), carrying a
      real library symbol so the editor's own netlist reads the rail's name off
      it, exactly as a single-module page of the same document does;
    * a ``signal``/``other`` net keeps the label it has always had — 「网络标签
      只许跨岛信号边界」;
    * a net whose flag symbol the library does not carry falls back to the label
      **and says so** (one note naming the ref that was looked for), which is
      143 F1's rule: a downgrade nobody can read about is not a downgrade.

    **One flag per blob, not per pin.** An island's several pins of one rail are
    already one blob — :func:`_wire_net` drew them as one chain — and this names
    the blob once, at the end of it.  That is the golden board's own arithmetic
    (board-A `GND`: 48 pins under 34 flags) and it is what keeps a rail from
    becoming a bus.

    **530A: one-pin nets are named too** (:func:`_name_one_net` with
    ``single_pin=True``): 岳's ruling of 2026-10-20 gives a net with one member and
    no second end anywhere the same treatment as a boundary name — a name at the
    pin plus a lint in :attr:`IslandBlock.notes` — instead of leaving the pin to
    be read as `required-pin-not-connected`, which refuses the whole drawing.
    """
    occupied: list[Box] = [tuple(box) for box in field.bodies]
    occupied.extend(_wire_boxes(block))
    occupied.extend(_host_name_boxes(block))
    occupied.extend(tuple(text.bbox) for text in block.texts)
    #: What a **stub** may not run through: a part's body, or a boundary name that
    #: is already on the page.  The second half is why this is not simply
    #: ``field.bodies`` — a flag's glyph is a drawn extent like a body's
    #: (`readability._check_bodies` tests a wire against it the same way), and a
    #: stub that runs through a flag placed one net earlier is the gate's
    #: `wire-through-body` on a name rather than on a part.  The name *box* search
    #: below already used ``occupied``; the stub was measured against the parts
    #: only, which is a hole this batch's tighter drawing found.
    hard_boxes: list[Box] = [tuple(box) for box in field.bodies]
    hard_boxes.extend(tuple(box) for box in block.power_boxes)
    # The grounds **the whole document** spells, which is the question 173/C's
    # flag chooser asks ("does this drawing really have more than one ground?").
    # Asked over the circuit rather than over this island, because it is the
    # document that has one ground family or two — an island carrying only the
    # secondary's ground must still tell `SEC_GND` from `PGND`.
    ground_domains = frozenset(_ground_domains(circuit))
    others = [(part_id, box) for part_id, box in extents.items()]
    own_runs = [
        (segment.points[index], segment.points[index + 1])
        for segment in block.segments
        for index in range(len(segment.points) - 1)
    ]
    #: Every run already on this island — the nets' own wires and the boundary
    #: stubs placed before this one — which a new stub may not **end** on.  A stub
    #: end that lands in the span of another run is a T, and the editor draws the
    #: dot and joins the two nets: `readability`'s `undeclared-junction`, i.e. a
    #: short.  The stub's *body* crossing a run is a different thing (an X, which
    #: the editor does not join), so only the ends are tested here.  The list grows
    #: as names are placed, which is what makes each stub know about the last.
    foreign_runs = [
        (path[index], path[index + 1])
        for name, path in drawn
        for index in range(len(path) - 1)
    ]
    #: 530D: the unit is the **blob**, not the net.  Every net's blobs are worked
    #: out here, from the drawing as it stands **before any name is placed** — so
    #: the stub one name draws cannot make a later blob of the same net look bigger
    #: than it is, nor make it look named (`_component_is_named`).  A single-pin net
    #: has no wiring at all, so its one pin is its one blob and this is 520A's
    #: behaviour unchanged.
    blobs: list[
        tuple[IslandNet, bool, list[IslandPin], list[tuple[float, float]]]
    ] = [
        (net, single_pin, pins, points)
        for net, single_pin in (
            [(item, False) for item in subgraph.named_nets]
            + [(item, True) for item in subgraph.single_pin_nets]
        )
        for pins, points in _net_components(net, tips, block.segments)
    ]
    for net, single_pin, pins, points in blobs:
        if _component_is_named(block, net.net_id, points):
            continue  # 一坨里已有旗标/标签的不再重复挂一个
        # 532: the name is tried at **each end of the segment**, outward first.
        # `_boundary_pin`'s choice is the end facing the next island, and it stays
        # the first candidate; the other end is the island's end of the net just as
        # much, and on the real flyback's `secondary` island the outward end is the
        # one place with **no way out at all** — the module says so in a note and
        # takes the least-damaging direction, which is a conductor printed through
        # the 220uF/100nF value row S-21 forbids it to hide. Trying the other end
        # first is the same search with a different anchor, so the choice is still
        # the router's rather than a new rule's; what the run records is which end
        # it had to settle for and why.
        mark = (len(block.segments), len(block.labels), len(block.power_symbols),
                len(block.power_boxes), len(block.notes), len(occupied),
                len(own_runs), len(hard_boxes), len(foreign_runs))
        clear = False
        for attach in _boundary_ends(net, pins, tips):
            clear = _name_one_net(
                block, net, pins, tips=tips, poses=poses, book=book,
                circuit=circuit, field=field, others=others, budget=budget,
                occupied=occupied, own_runs=own_runs, hard_boxes=hard_boxes,
                foreign_runs=foreign_runs, ground_domains=ground_domains,
                single_pin=single_pin, attach_hint=attach,
            )
            if clear:
                break
            # Everything this attempt appended, put back — the flag's **glyph box**
            # included, and leaving that one out is how this rollback first shipped:
            # `IslandBlock.power_boxes` and `.power_symbols` are two lists written by
            # one call (`_place_flag`), so a truncation that forgets either leaves
            # the block holding a box no symbol owns
            # (`tests/test_530a_island_flags.py::test_the_flag_is_inside_the_blocks_own_box`
            # read the index error, not a wrong number).
            del block.segments[mark[0]:]
            del block.labels[mark[1]:]
            del block.power_symbols[mark[2]:]
            del block.power_boxes[mark[3]:]
            del block.notes[mark[4]:]
            del occupied[mark[5]:]
            del own_runs[mark[6]:]
            del hard_boxes[mark[7]:]
            del foreign_runs[mark[8]:]
        if not clear:
            # No end had a clear way out: put the outward end's own least-damaging
            # answer back, which is the one the module's note is about.
            _name_one_net(
                block, net, pins, tips=tips, poses=poses, book=book,
                circuit=circuit, field=field, others=others, budget=budget,
                occupied=occupied, own_runs=own_runs, hard_boxes=hard_boxes,
                foreign_runs=foreign_runs, ground_domains=ground_domains,
                single_pin=single_pin,
            )

def _name_one_net(
    block: IslandBlock,
    net: IslandNet,
    pins: Sequence[IslandPin],
    *,
    tips: Mapping[IslandPin, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    book: Mapping[str, SymbolProfile],
    circuit: CircuitSpec,
    field: _Field,
    others: Sequence[tuple[str, Box]],
    budget: IslandBudget,
    occupied: list[Box],
    own_runs: list[tuple[tuple[float, float], tuple[float, float]]],
    hard_boxes: list[Box],
    foreign_runs: list[tuple[tuple[float, float], tuple[float, float]]],
    ground_domains: frozenset[str],
    single_pin: bool,
    attach_hint: IslandPin | None = None,
) -> bool:
    """One net's name at this island's own end of it — a flag or a label.

    The search is :func:`_add_boundary_names`' (see its docstring for what a stub
    may not run through); what differs between the two callers is only *which*
    nets reach here and whether a lint is owed:

    * a crossing net is named because it goes somewhere else (岳's 「岛间名字接」);
    * a ``single_pin`` net is named because it goes nowhere at all, and the name
      is the whole of what the drawing can say about the pin — with the lint that
      records it as 岳's ruling, not as an oversight.

    Since 530D ``pins`` is **one blob of the net**, not the whole net: the caller
    walks `_net_components` and calls this once per component (S-14).  For a net
    whose island segment is in one piece — every net on the real flyback today —
    the two are the same list, which is why this batch moves no pin and no stub.

    ``occupied`` and ``own_runs`` are the island's running book of what is already
    drawn; this function appends to both, so the next net sees this one.

    Returns **whether it found a clear way out**: the caller tries the segment's
    ends one at a time (532, :func:`_boundary_ends`) and rolls this call back when
    the answer is no, which is only possible if the answer is stated rather than
    left in a note.
    """
    pinned = [pin for pin in pins if pin in tips]
    if not pinned:
        return True
    attach = attach_hint if attach_hint is not None else _boundary_pin(net, pinned, tips)
    tip = tips[attach]
    profile = book[circuit.part(attach.part_id).symbol_ref]
    own = _pin_outward(profile, attach.pin, poses[attach.part_id])
    outward = _unit(tip)
    candidates = _stub_directions(own, outward)
    spec_net = circuit.net(net.net_id)
    cls = spec_net.cls if spec_net is not None else ""
    flag, ref = _flag_plan(
        net.net_id, cls, book, budget, ground_domains=ground_domains,
    )
    if flag is None and ref:
        block.notes.append(
            f"net {net.net_id} is a {cls} net and this island's boundary name "
            f"for it would be the flag {ref!r}, but the library carries no such "
            "symbol, so it is expressed by a label here (the same downgrade "
            "143 F1 states for a flag net with no symbol: what this host can "
            "draw instead of what the rule asks for)"
        )
    if single_pin:
        block.notes.append(
            f"island-single-name: net {net.net_id} has one pin in the whole "
            f"document ({attach}) and no second end anywhere — it is named at that "
            "pin and reported as a lint rather than refused, because a reserved "
            "connection is not an unconnected one (S-17; 岳 2026-10-20). The "
            "editor's own netlist reads the pin as carrying this name."
        )
    #: Every pin tip that is **not** this net's: a stub that runs over one joins two
    #: nets the schematic keeps apart (the editor's own reading — measured on this
    #: batch's bridge island, where a rail's stub leaving `T1.6` downward ran over
    #: `T1.5`, a pin the spec never mentions, and made it a member of `SEC_GND`).
    mine_pins = {str(pin) for pin in net.pins}
    foreign_tips = [
        (key, point) for key, point in field.pins if key not in mine_pins
    ]
    chosen: tuple[tuple[float, float], tuple[float, float], Box, float] | None = None
    fallback = None
    # A stub is a wire, so the host also prints the net's name at the stub's
    # midpoint — a row nobody placed.  530B *did* check that row and had to take
    # it back: ranked with the electrical keys it moved stubs onto other
    # conductors and produced an `undeclared-junction` in `secondary`, i.e. it
    # traded a legibility finding for an electrical one.  530C puts the row back
    # **last** instead (`DESIGN` §6.5 item 2, read honestly): every electrical and
    # every box-placement key ranks above it, so the row can only choose between
    # ways out that are already equally clean.  The row is the host's, so its
    # position is a function of the stub and of nothing else — which is what makes
    # it a usable last key rather than a second search.
    #: The lengths a boundary stub is tried at, shortest first.  One more channel
    #: each time, and no more than :attr:`IslandBudget.slot_rungs` of them: a name
    #: that cannot be written within a few channels of its own pin is a name that is
    #: being asked to stand in for a wire, which is not what a name is (`DESIGN`
    #: §6.3's band, 20-55, read as "the stub may grow, but not into a wire").
    #:
    #: **530C measured the band and did not land it** (`DESIGN` §6.3's
    #: ``clamp(stub_min, …, stub_max)``, 20-55).  Clamping this ladder to
    #: ``stub_max = 55`` was implemented and run on the real flyback: the page's
    #: hard violations went 8 → 9 and its area/part went 2.99x → **3.14x**, i.e.
    #: past the 3.0x budget `test_520n` guards.  The reason is `bridge`: it is a
    #: two-part 只挂名岛 with eight crossing nets (`DESIGN` §1.6), so eight names
    #: have to stand somewhere and 94 (the third rung) is what clears them.  The
    #: 20-55 band is P-06's reading of the golden board's *label* stubs, and that
    #: board has no such island.  So the band stays unimplemented and is reported
    #: as a gap rather than traded for a budget it blows.
    reaches = tuple(
        budget.stub + step * budget.channel
        for step in range(budget.slot_rungs)
    )
    best: tuple[tuple[float, ...], tuple[tuple[float, float], tuple[float, float], Box, float]] | None = None
    clear: list[
        tuple[tuple[float, ...],
              tuple[tuple[float, float], tuple[float, float], Box, float]]
    ] = []
    for reach in reaches:
        for direction in candidates:
            end = (
                tip[0] + direction[0] * reach,
                tip[1] + direction[1] * reach,
            )
            # A flag occupies its glyph **and** the name row the host prints beside
            # it, and both are things a neighbouring wire or a part's text may not
            # reach into: `readability._check_bodies` tests a wire against a flag's
            # glyph as it tests it against a part's body, and `_text_boxes` measures
            # the row.  So the flag's seat is one box, measured the way the gate
            # measures it, and it is what the search below keeps clear.
            rotation = 0.0
            if flag is None:
                box = _name_box(net.net_id, end, direction, budget)
            else:
                rotation, box = _flag_seat(flag, direction, end, net.net_id)
            # What this stub would cost, ranked the way the drawing ranks things:
            # **electrical first, legibility second.**  A stub end that lands in
            # another run's span is a T — the editor draws the dot and the two nets
            # become one (`undeclared-junction`), which no reader can undo — while a
            # name printed over a conductor is a finding about legibility.  The key
            # is used twice: ``key[:-1]`` all-zero is "this one is clear" and the
            # candidates that answer that are collected; ``key`` in full then picks
            # between them (the host's row first, the stub's own length last), and
            # the **cheapest** candidate overall is kept as the fallback, so an
            # island with no clear way out still gets the least-bad one rather than
            # whichever happened to be first.
            # The row the **host** prints over this stub, when the stub is a wire
            # of an unflagged net (a flagged net's wire is landed unnamed, so it
            # brings no row — `drawapply.unnamed_nets`).  Measured by the same
            # function the gate measures it with, so "clear here" and "clear in
            # `readability`" cannot drift apart.
            row = (
                wire_name_box([tip, end], net.net_id) if flag is None else None
            )
            key = (
                1.0 if any(_on_run(start, stop, end) for start, stop in foreign_runs) else 0.0,
                1.0 if any(
                    _on_run(tip, end, point)
                    for name, point in foreign_tips
                ) else 0.0,
                1.0 if any(_run_overlap(tip, end, s, t) > 0.0 for s, t in own_runs) else 0.0,
                1.0 if any(_crosses(tip, end, body) for body in hard_boxes) else 0.0,
                1.0 if any(_crosses(tip, end, extent, 0.0) for _id, extent in others) else 0.0,
                1.0 if any(_overlaps(box, extent) for _id, extent in others) else 0.0,
                1.0 if any(_crosses(tip, end, other.bbox, 0.0) for other in block.texts) else 0.0,
                float(sum(1 for other in occupied if _overlaps(box, other))),
                float(
                    sum(1 for _id, extent in others if _overlaps(row, extent))
                    + sum(1 for other in occupied if _overlaps(row, other))
                    + sum(1 for other in block.texts if _overlaps(row, other.bbox))
                ) if row is not None else 0.0,
            )
            if best is None or key < best[0]:
                best = (key, (direction, end, box, rotation))
            if not any(key[:-1]):
                # Clear on everything but the host's own row.  Every reach is
                # tried before one of these is taken, and then it is the **best
                # by the full key** — so `row_hits` chooses first and `length`
                # (the last key) breaks its ties, which is what keeps the row
                # from buying itself a longer stub than it needs.  Bounding it to
                # the shortest reach instead was measured: it gives the same page
                # as having no row key at all, because on the flyback no
                # direction at the first rung is clear.
                clear.append((key, (direction, end, box, rotation)))
    if clear:
        chosen = min(clear, key=lambda item: item[0])[1]
    if chosen is None:
        chosen = best[1] if best is not None else (candidates[0], tip, (0.0, 0.0, 0.0, 0.0), 0.0)
        block.notes.append(
            f"net {net.net_id}: no clear way out of {attach} for its boundary "
            "name, so it takes the least-damaging way out instead — ranked "
            "electrical first (a stub that ends on another run would join two "
            "nets) and legibility second — and a reader must not expect the name "
            "to be legible"
        )
    _direction, end, box, rotation = chosen
    block.segments.append(LayoutSegment(net=net.net_id, points=[tip, end]))
    if flag is None:
        block.labels.append(LayoutLabel(
            net=net.net_id, text=net.net_id, bbox=box,
            x=end[0], y=end[1], part_id=attach.part_id,
        ))
    else:
        _place_flag(block, net.net_id, flag, end, rotation, box)
    occupied.append(box)
    own_runs.append((tip, end))
    hard_boxes.append(box)
    foreign_runs.append((tip, end))
    return bool(clear)


# ------------------------------------------------------------- rail flags


def _place_flag(
    block: IslandBlock,
    net_id: str,
    profile: SymbolProfile,
    anchor: tuple[float, float],
    rotation: float,
    box: Box,
) -> None:
    """Record one flag on this block: the symbol itself, and the seat it takes.

    The **lead** is already in ``block.segments`` by the time this runs: it is the
    same stub a label would have hung on, which is what makes the flag's
    connection point a point on this net's own conductor.  That is not a detail —
    `drawapply` reads a landed flag back by geometry (``flag.x/flag.y`` within half
    a lattice step of the plan's own), and a flag whose anchor is on nothing is a
    rail the editor's netlist does not join.

    ``symbol_hash`` is the profile's own, exactly as a part carries it: a flag is a
    library component and a stale glyph is the same problem as a stale part
    (`LayoutPowerSymbol`'s docstring; `drawapply` refuses a mismatch).
    """
    block.power_symbols.append(LayoutPowerSymbol(
        symbol_ref=profile.symbol_ref,
        symbol_hash=profile.geometry_hash(),
        net=net_id,
        x=anchor[0],
        y=anchor[1],
        rotation=rotation,
    ))
    block.power_boxes.append(box)


def _flag_seat(
    profile: SymbolProfile,
    direction: tuple[float, float],
    anchor: tuple[float, float],
    net_id: str,
) -> tuple[float, Box]:
    """``(the rotation to hand the editor, the box the seat occupies)``.

    The composition `drawcompiler._flag_box` makes, in this module's own terms:
    the glyph (`~boardwise.core.symbolprofile.flag_glyph_box`, which is where the
    family offset is applied) plus — for a **rail** — the row the host prints the
    net's name in (`~boardwise.core.textmetrics.flag_name_box`, the same measured
    band `readability._flag_name_row` grades).  A ground flag prints no name at
    all, and 148 measured the cost of reserving a row it never prints: a box
    larger than the one the checker grades refuses a placement that was fine.

    One box for the search in :func:`_name_one_net`, because the gate tests both
    halves against a neighbour: a wire through the glyph is
    ``wire-on-pin-line``/``wire-through-body`` and a text box on the row is
    ``text-overlap``.
    """
    kind = flag_glyph_kind(profile)
    rotation = _flag_rotation(direction, kind)
    glyph = flag_glyph_box(profile, rotation=rotation, anchor=anchor)
    if glyph is None:
        glyph = (anchor[0], anchor[1], anchor[0], anchor[1])
    row = None
    if kind != FLAG_GLYPH_KIND_GND:
        row = flag_name_box(glyph, anchor, net_id, axis_up=glyph[3] > anchor[1])
    if row is None:
        return (rotation, glyph)
    return (rotation, (
        min(glyph[0], row[0]), min(glyph[1], row[1]),
        max(glyph[2], row[2]), max(glyph[3], row[3]),
    ))


def _flag_rotation(direction: tuple[float, float], kind: str) -> float:
    """The rotation the editor is given so a flag **stands upright** — 0 or 180.

    `drawcompiler._flag_rotation`'s rule.  It is written here rather than imported
    because the dependency between this module and the compiler runs one way only
    (`_try_island_variants` imports *this* module, lazily, and 530A may not turn
    that into a module-level cycle).  What keeps the two copies from drifting is
    not this paragraph but two checkable facts:

    * the number that actually decides **which side the glyph hangs** is the shared
      table `~boardwise.core.symbolprofile.FLAG_GLYPH_ROTATION_OFFSETS`, imported
      from core — the same table `flag_glyph_box` folds in, so the rotation handed
      to the editor and the box reserved for the glyph can never describe opposite
      sides (060's bug, both families);
    * `tests/test_530a_island_flags.py` asserts this function and
      `drawcompiler.flag_rotation` agree on all four compass points for both
      families.  If the compiler's rule ever moves, that test goes red, which is
      the whole point of writing a two-branch rule down twice.

    ``direction`` is the way the glyph must hang (``+y`` up, ``-y`` down).  A flag
    on the horizontal axis — reachable here, and not on the compiler's own ladder,
    because a boundary stub may leave along any compass point — takes the family's
    natural hang: a rail lifts, a ground hangs down.
    """
    if direction[1] != 0.0:
        up = direction[1] > 0.0
    else:
        up = kind != FLAG_GLYPH_KIND_GND
    base = 0.0 if up else 180.0
    return (base + FLAG_GLYPH_ROTATION_OFFSETS[kind]) % 360.0


def _ground_domain(net_id: str) -> str:
    """Which ground domain a net's **name** puts it in — `drawcompiler._ground_domain`.

    ``core.netdomains.domain_of`` answers ``power`` / ``logic`` / ``""``, and
    ``""`` is not a domain: it is 「this drawing spells its ground something the
    word list does not carry」 (the flyback's `SEC_GND`, which the *ground*
    vocabulary knows as of 145a but this two-prefix table does not), so such a
    net is keyed by its own name rather than filed under a domain it is not in.
    """
    return domain_of(net_id) or net_id


def _ground_domains(circuit: CircuitSpec) -> set[str]:
    """The distinct ground domains **this document** spells (173/C's own question).

    `drawcompiler._ground_domains` answers it for a `_Context` whose page compiler
    has already stated the set, and falls back to exactly this fold of the
    circuit's own ``gnd`` nets.  The island path has no `_Context` — that is the
    point of this module (see its docstring) — so it always asks the fallback
    question, and it asks it over the **whole** circuit rather than over one
    island: "does this drawing really have more than one ground?" is a question
    about the document, and an island that carries only the secondary's ground
    must still tell `SEC_GND` from `PGND`.
    """
    return {_ground_domain(net.id) for net in circuit.nets if net.cls == "gnd"}


def _flag_ref(
    net_id: str,
    cls: str,
    *,
    book: Mapping[str, SymbolProfile],
    budget: IslandBudget,
    ground_domains: frozenset[str] | set[str],
) -> str:
    """The flag symbol ref a net is looked up under — `drawcompiler._flag_ref`'s rule.

    A rail is named by its own ``power_flag_prefix + net``.  A **ground** takes the
    family's shared symbol (``budget.gnd_flag``) unless the drawing really has more
    than one ground domain, in which case it asks for the flag named after itself.
    The reasoning is not restated here; `drawcompiler._flag_ref`'s docstring is
    where 173/C's 「按网的域选对应旗标族、绝不并地」 is argued, and this function
    exists so that an island page and a single-module page of one document answer
    it the same way.  ``drawcompiler``'s version delegates to a `_Context`; the two
    are pinned equal by `tests/test_530a_island_flags.py`.

    An empty answer is a **statement**, not a gap: ``gnd_flag=""`` is 178's own
    switch for 「this drawing names no ground with a flag」, and the library cannot
    overrule a scenario's statement about itself.
    """
    own = f"{budget.power_flag_prefix}{net_id}"
    if cls != "gnd":
        return own
    gnd_flag = budget.gnd_flag
    if not gnd_flag or own == gnd_flag or len(ground_domains) <= 1:
        return gnd_flag
    return own if book.get(own) is not None else gnd_flag


def _flag_plan(
    net_id: str,
    cls: str,
    book: Mapping[str, SymbolProfile],
    budget: IslandBudget,
    *,
    ground_domains: frozenset[str] | set[str],
) -> tuple[SymbolProfile | None, str]:
    """``(the flag profile this net takes, its ref)`` — ``(None, "")`` for a label.

    `drawcompiler._flag_plan`'s island side.  Two different ``None``\\ s come out of
    it, and the caller has to be able to tell them apart:

    * ``(None, "")`` — this net is not a rail/ground at all, or the budget itself
      says grounds are not flagged here.  It takes a label, silently: that is the
      rule, not a downgrade;
    * ``(None, "<ref>")`` — the rule asked for ``<ref>`` and the library does not
      carry it.  It takes a label **and a note**, which is 143 F1's rule and S-16's
      §7.2.2 in one: a symbol the book does not have is what the drawing state has
      to say out loud, because the alternative (drawing the flag anyway) is not
      something this host can do.
    """
    if cls not in ("power", "gnd"):
        return (None, "")
    ref = _flag_ref(
        net_id, cls, book=book, budget=budget, ground_domains=ground_domains,
    )
    if not ref:
        return (None, "")
    return (book.get(ref), ref)


def _stub_directions(
    own: tuple[float, float], outward: tuple[float, float]
) -> list[tuple[float, float]]:
    """The ways a boundary stub may leave its pin, best first, no repeats.

    Always one of the four compass points, never a diagonal: a stub is a wire, and
    this module draws Manhattan wire only (:func:`_tidy` refuses anything else on
    the links).  The first version passed the pin's escape angle through raw and
    produced a diagonal ``(-0.79, 0.53)`` stub off `R15.2` on the flyback's
    `primary` island — a segment no other part of this drawing, and no reader, is
    measured in.

    The pin's own escape, **snapped** to its dominant axis, is tried first: that is
    the direction the pin is drawn pointing, so a stub along it is the continuation
    an engineer would draw, and it is what keeps the stub off the part's own body.
    Radially outward, snapped, is second — the direction the next island is in.
    Then the remaining compass points, so a crowded corner still has somewhere to
    go.  (`DESIGN` §6.5's 「stub 朝最空象限」 would put a fourth rule in front of
    these; it was implemented and measured on this document — neutral on the gate,
    and it is a rule about where the **host** prints a wire's name, which is 530C's
    subject.  It is not here.)
    """
    compass = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
    ordered = [_axis(_unit(own)), _axis(_unit(outward))]
    ordered.extend(sorted(
        compass,
        key=lambda item: -(item[0] * own[0] + item[1] * own[1]),
    ))
    out: list[tuple[float, float]] = []
    for item in ordered:
        if all(abs(item[0] - seen[0]) > 1e-6 or abs(item[1] - seen[1]) > 1e-6
               for seen in out):
            out.append(item)
    return out


def _axis(direction: tuple[float, float]) -> tuple[float, float]:
    """``direction`` snapped to the compass point it is closest to."""
    if abs(direction[0]) >= abs(direction[1]):
        return (1.0 if direction[0] >= 0.0 else -1.0, 0.0)
    return (0.0, 1.0 if direction[1] >= 0.0 else -1.0)


def _name_box(
    text: str,
    anchor: tuple[float, float],
    direction: tuple[float, float],
    budget: IslandBudget,
) -> Box:
    """The box a boundary name occupies at ``anchor``, just past it along ``direction``.

    The anchor is the stub's end — the electrical fact, since a label joins the
    wire it touches — and the box is typography, so it sits off to the side of the
    anchor rather than centred on it: a name straddling its own stub reads as two
    things crossing.  Measured with the render's ruler, like every other box this
    module emits.
    """
    width = render_width(text)
    gap = budget.text_gap
    row = budget.text_row
    if abs(direction[0]) >= abs(direction[1]):
        cx = anchor[0] + math.copysign(width / 2.0 + gap, direction[0])
        cy = anchor[1]
    else:
        cx = anchor[0]
        cy = anchor[1] + math.copysign(row / 2.0 + gap, direction[1])
    return (cx - width / 2.0, cy - row / 2.0, cx + width / 2.0, cy + row / 2.0)


# --------------------------------------------------------------------- texts


def _drop_pressed_texts(
    block: IslandBlock,
    circuit: CircuitSpec,
    book: Mapping[str, SymbolProfile],
) -> None:
    """S-21's first way out, applied once the names and the wires are on the page.

    The parts' rows are placed before the boundary names (`_add_texts` runs first,
    and for 520l's reason: the names stick out past everything else, so they are
    the ones that have to know), which leaves one hole: a name, a flag, or another
    part's row can land **on** a value that was already placed, and the value has
    no way to have seen it coming.

    531 widened what counts as "on" to the island's **own conductors**. The
    router ranks a part's row among its legibility keys (531's `text_hits`, above
    `bends` and below every electrical key), so it avoids them where it can — but
    a row that no route can be kept off is a row the page cannot deliver with,
    because `readability` calls a conductor through a ``texts[i]`` row
    `text-on-wire` and 530F made every ``texts[i]`` row a **hard** finding. The
    value is the one row S-21 lets go — 「值应隐藏」 — so it goes, and the note
    says so. Measured on the flyback's island page: one row (`C14`'s `100nF 0603`,
    a `C0603W` whose measured rot-0-mirrored anchor hangs its value 18 units below
    the part, straight across the `SEC_12V` run).

    A reference designator is never dropped: a part with no designator is not a
    schematic. Both the drop and its reason are recorded.

    532 adds the other half of S-21's category rule here as well: a value belongs
    to a resistor, capacitor, inductor or IC, it is **not** droppable either
    (`VALUE_ALWAYS_PRINTED`), and what is left is the page's own refusal — which
    is the honest answer for a row no layout can move.  The reason is the reader's
    own (`value_may_be_hidden`), quoted rather than re-argued.
    """
    occupied: list[Box] = [tuple(label.bbox) for label in block.labels]
    occupied.extend(tuple(box) for box in block.power_boxes)
    occupied.extend(
        tuple(text.bbox) for text in block.texts if text.kind == "reference"
    )
    occupied.extend(_wire_boxes(block))
    kept: list[LayoutText] = []
    for text in block.texts:
        if text.kind == "value" and any(
            _overlaps(text.bbox, box) for box in occupied
        ):
            may_hide, basis = value_may_be_hidden(book, circuit, text.part_id)
            if not may_hide:
                block.notes.append(
                    f"{text.part_id}: the value {text.text!r} at "
                    f"({text.bbox[0]:g}, {text.bbox[1]:g})-"
                    f"({text.bbox[2]:g}, {text.bbox[3]:g}) is where something that is "
                    "already on the page (a boundary name, a rail flag, another "
                    "part's row, or one of this island's own conductors) is, and S-21 "
                    f"will not hide it — {basis} — so this page is refused by the "
                    "gate rather than delivered with the row drawn through a "
                    "conductor"
                )
                kept.append(text)
                continue
            _hide_value_row(
                block, text.part_id, text.text,
                "something that is already on the page (a boundary name, a rail "
                "flag, another part's row, or one of this island's own conductors) "
                "is where the host would print it, and S-21's first way out of a "
                "collision is to hide the value rather than print it through the "
                "neighbour",
            )
            continue
        kept.append(text)
    block.texts[:] = kept


def _add_texts(
    block: IslandBlock,
    ring: Sequence[str],
    circuit: CircuitSpec,
    book: Mapping[str, SymbolProfile],
    origins: Mapping[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    bodies: Sequence[Box | None],
    budget: IslandBudget,
    *,
    hidden_values: Mapping[str, str] = {},
) -> None:
    """The **host's own** rows for every part, minus S-21's hidden values.

    There was a search here, and 530B took it out for the right reason: a search
    answers 「where can this go」 while S-20 wants 「where does a reader expect it」.
    531 takes out what 530B put in **its** place, because it was a fiction. A
    part's designator and value are **drawn by the host** when the part is placed
    — `drawapply` says so in one line ("C1 places no text primitive, so the drawn
    text is the host's") — at the symbol's own declared anchor, and this module
    used to invent a band, a rung and a side for every row.

    That was the whole of the 「量尺债」 522 warned about: the invented boxes sat
    50-70 units from where the host prints, so the gate measured a page nobody
    sees, and the collisions 岳 found by eye on the landed render
    (`evidence/530f/530f_page_island.png`: `R15`'s `75k 1% 0603` across `C11`'s
    `1nF/1kV`, and the two resistors beside `R20` printing `R19R20`) never reached
    it. `evidence/531/report.md` §2 is the measurement; §4 is the same page with
    the model corrected.

    So a part's rows here are :func:`boardwise.core.textmetrics.symbol_rows`'
    output — the same one home the single-module path and the placement search use
    — and the module keeps only **S-21's first way out**: a value whose row the
    placement could not clear (`hidden_values`) is not emitted, with its reason
    written into the block's notes. A reference designator is never hidden (a part
    with no designator is not a schematic), so a reference row that is still
    pressed after the placement's own pass is recorded here — where it is, what
    this module's own coarse reserve ran into, and the fact that the **gate** is
    what decides — rather than quietly drawn.

    **That distinction is 201H's second half (201H-b).** The reserve below is
    deliberately coarse: it holds every ring part's body (its **own** included), a
    one-unit wall around every conductor and the host's own conductor-name rows.
    The gate's reading is not that reading — a part's own artwork is not scored at
    all (`readability._check_text` skips the owner's own extent), a conductor only
    counts at `TEXT_WIRE_PENETRATION`, and its bodies are drawn extents rather than
    pin-inclusive boxes. The note used to state the verdict anyway ("the gate will
    refuse this page"), and on the delivered 201H page that sentence was false
    eleven times while the gate said `ok` — a reader (or an agent auditing the
    notes) was told a refusal had been filed and took no action. Now the note names
    the object it actually hit and leaves the verdict to `readability`.
    """
    #: Each obstacle keeps the name a reader needs: "the drawn body of T1" is a
    #: neighbour, "this part's own symbol body" is the host's own artwork, and the
    #: two are not the same sentence. Rows committed earlier in the ring join this
    #: list as they are placed, and a **hidden** value never joins it — a row the
    #: host does not print is not something to dodge (201H's `rows` filter).
    own_bodies: dict[str, Box] = {}
    for owner in ring:
        box = pose_box(
            book[circuit.part(owner).symbol_ref].body,
            rotation=poses[owner].rotation, mirror=poses[owner].mirror,
            ox=origins[owner][0], oy=origins[owner][1],
        )
        if box is not None:
            own_bodies[owner] = box
    obstacles: list[tuple[str, Box]] = [
        (f"the drawn body of {owner}", box) for owner, box in own_bodies.items()
    ]
    obstacles.extend(
        (f"the boundary name {label.text!r}", tuple(label.bbox))
        for label in block.labels
    )
    obstacles.extend(
        ("one of this island's own conductors (the one-unit wall)", box)
        for box in _wire_boxes(block)
    )
    obstacles.extend(
        ("the host's own name row of a conductor", box)
        for box in _host_name_boxes(block)
    )
    for part_id in _ring_order(ring, block.anchor):
        part = circuit.part(part_id)
        profile = book[part.symbol_ref]
        hidden = hidden_values.get(part_id, "")
        own_body = own_bodies.get(part_id)
        if not profile.texts:
            block.notes.append(
                f"{part_id}: its symbol ({part.symbol_ref}) declares no text "
                "anchors, so where the host prints this part's designator and value "
                "is unknown — the readability gate therefore does not measure those "
                "two rows (146/147's measurement is what makes a row knowable, and "
                "531 stopped inventing one)"
            )
        for kind, text, box in symbol_rows(
            profile, origins[part_id], reference=part_id, value=part.value,
            pose=poses[part_id],
        ):
            if kind == "value" and hidden:
                _hide_value_row(block, part_id, text, hidden)
                continue
            diagnosis: list[str] = []
            if own_body is not None and _overlaps(box, own_body):
                diagnosis.append(
                    "this part's own symbol body (the host draws its rows inside "
                    "its own artwork on purpose)"
                )
            diagnosis.extend(
                what for what, other in obstacles
                if what != f"the drawn body of {part_id}" and _overlaps(box, other)
            )
            if diagnosis:
                printed = f"({box[0]:g}, {box[1]:g})-({box[2]:g}, {box[3]:g})"
                block.notes.append(
                    f"{part_id}: its {kind} row {text!r} at {printed} is where the "
                    "host draws it, and this module's own reserve — a coarse box "
                    "test, **not** the gate's reading — has "
                    + " and ".join(dict.fromkeys(diagnosis))
                    + " inside it. That is a diagnosis, not a verdict: "
                    "`readability` decides with its own measurements (a part's "
                    "drawn extent rather than a pin-inclusive box, its own chord "
                    "threshold for a conductor, and a part's own artwork is not a "
                    "finding at all), so this row may well be delivered and the "
                    "gate's answer is what says so. Recorded because the placement "
                    "left it: S-21 lets only a value go, and a reference is never "
                    "hidden"
                )
            block.texts.append(_text(text, kind, part_id, box))
            obstacles.append((f"the {kind} row of {part_id}", box))


def _ring_order(ring: Sequence[str], anchor: str) -> list[str]:
    """The island's parts, the anchor first, then the rest by id — fixed order.

    Fixed so two runs of the same document draw the same picture: the rows are
    committed one at a time and a later row may not land on an earlier one, so the
    order is part of the result rather than a detail of it.
    """
    return [anchor, *sorted(part_id for part_id in ring if part_id != anchor)]



def _text(text: str, kind: str, part_id: str, box: Box) -> LayoutText:
    """One text row as a `LayoutText` — level, and centred on its own box."""
    return LayoutText(
        kind=kind, text=text, part_id=part_id, bbox=box,
        x=(box[0] + box[2]) / 2.0,
        y=(box[1] + box[3]) / 2.0,
    )


def _host_name_boxes(block: IslandBlock) -> list[Box]:
    """Where the **host** prints each wire's own net name (147).

    A conductor's name is not the compiler's to place: EasyEDA Pro anchors it at
    the midpoint of the wire's longest straight run and grows it rightward or
    downward, and `readability` measures that row as text on the canvas like any
    other (`_named_wire_rows`, `core.textmetrics.wire_name_box`).  So every wire
    this module draws brings a text row with it whether this module asked for one
    or not — which is why the part rows and the boundary names have to keep out
    of the way of a row nobody placed.

    The SVG preview does **not** draw these rows (it renders what the plan states,
    and the plan states no text for them), so a reader comparing the preview with
    the landed page sees fewer words in the preview than the editor will print.
    That gap is 147's, not this module's; it is named here so nobody reads the
    preview as the finished page.
    """
    out: list[Box] = []
    for segment in block.segments:
        box = wire_name_box(list(segment.points), segment.net)
        if box is not None:
            out.append(box)
    return out


def _wire_boxes(block: IslandBlock) -> list[Box]:
    """Every run the island has already drawn, as a hair-thin box.

    A wire is a stroke, not a rectangle, and this is the one-unit wall
    `drawcompiler.PIN_TEXT_WALL` reserves for the same reason: a text placed a
    hair off a conductor is legible, one printed through it is not, and the two
    are not the same test.
    """
    out: list[Box] = []
    for segment in block.segments:
        for index in range(len(segment.points) - 1):
            a, b = segment.points[index], segment.points[index + 1]
            out.append((
                min(a[0], b[0]) - 0.5, min(a[1], b[1]) - 0.5,
                max(a[0], b[0]) + 0.5, max(a[1], b[1]) + 0.5,
            ))
    return out


def _overlaps(first: Box, second: Box) -> bool:
    """Strict-inward overlap — a shared edge is not a collision."""
    return (
        first[0] < second[2] and second[0] < first[2]
        and first[1] < second[3] and second[1] < first[3]
    )


def box_gap(first: Box, second: Box) -> float:
    """The shortest distance between two axis-aligned rectangles.

    Zero when they overlap or touch.  This is the *only* measurement the automatic
    clustering compares (`evidence/523/DESIGN.md` §5.3's ``box_gap``): the design
    asks "how far apart are these two parts", and a distance between two boxes is
    the reading that does not depend on where either part's own origin happens to
    be — a wide IC's origin and its edge are tens of units apart, and the parts
    this decides between are exactly the wide ones.

    The two axes are taken separately and combined with Pythagoras, which is the
    standard reading of "the distance between two aligned rectangles": two parts
    diagonal to each other are further apart than two side by side by the same
    margin, which is what a person looking at the board sees.
    """
    dx = max(0.0, first[0] - second[2], second[0] - first[2])
    dy = max(0.0, first[1] - second[3], second[1] - first[3])
    return math.hypot(dx, dy)


def _reach(box: Box, origin: tuple[float, float], direction: tuple[float, float]) -> float:
    """How far the block's own extent reaches from its origin along ``direction``."""
    corners = [
        (box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]),
    ]
    return max(
        (corner[0] - origin[0]) * direction[0] + (corner[1] - origin[1]) * direction[1]
        for corner in corners
    )
