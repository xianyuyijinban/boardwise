"""The drawing compiler: two specs and a library in, LayoutPlans out (053 stage B).

The third element of 052 sec.4's three-layer picture, and the one that puts
coordinates on a drawing. Its inputs are the three stage-A contracts plus the
library, and it *computes* what nobody is allowed to assert:

    CircuitSpec      what the circuit is           (meaning, no coordinates)
    PresentationSpec how it should read           (intent; one coordinate slot,
                                                   userLocks)
    SymbolProfile    where each symbol's pins are (geometry, from a file)
        -> LayoutPlan    the drawing, as data      (053 sec.2's third contract)

Four stages, in the order 053 sec.4 fixes them:

1. **bind** (:func:`boardwise.engines.grammar.bind`) — the grammar answers "given
   that this is a voltage divider, what must the drawing make visible?". A
   refusal is passed through **verbatim**: its `facts-missing` /
   `circuit-invalid` category is the grammar layer's finding, and re-labelling it
   here would hide which layer decided.
2. **semantic layout** — roles become *relative* positions: a chain order along
   one axis (from `above`/`below`/`left-of`/`right-of`/`adjacent`), the chain's
   column or row, and a lane for everything that hangs off a chain node (`near`
   plus the same-line and tap kinds). Nothing in this stage is a coordinate; it
   produces a rank and a lane per part.
3. **geometric layout** — ranks become canvas points through the *real* symbols:
   each part's pose is chosen from the finite legal set so its pins face the way
   the stage above requires, the pitches come from the symbols' own pin spans plus
   a wiring channel, everything is placed on a lattice, and **body boxes and text
   boxes participate in avoidance**. Text boxes come from the font metrics
   (:func:`font_text_box`), never from a character count — the gap
   `engines/layout.py` documents at its `LABEL_CHAR_WIDTH` estimate.
4. **routing** — orthogonal, trunk first, fewest crossings. A net whose points
   are collinear *is* its trunk and is drawn as one straight wire; anything else
   goes through a lattice search whose obstacles are foreign bodies, text boxes,
   keep-outs, foreign pin tips, foreign net anchors and other nets' wire
   vertices (:class:`_Router`). A foreign wire's *interior* may be crossed
   perpendicularly — measured editor behaviour, and why a crossing is a soft
   metric and not a connection. A wire end always lands on a pin tip, a junction,
   a label or a flag: never in mid-air.

Then the candidates are **gated** and **ranked**:

* candidates = the variants (finite poses x grid ladder, stable tie-break) whose
  plan passes :func:`boardwise.engines.readability.check` with **zero hard
  violations**. That checker is a separate module working from the plan and the
  specs alone (052 sec.8) — this module never grades its own output;
* ranking is layered (:func:`layered_key`): legality, then circuit expression
  (grammar findings), then readability (crossings, bends, wire length), then
  compactness. Layers are compared in order and never summed, so no amount of
  "fewer millimetres" can buy back a broken relation (052 sec.6, 053 sec.7);
* at most `budget.max_candidates` candidates come out — 8 by default, and the
  ceiling is structural rather than a promise: the finite search stops after
  that many variants and one variant yields at most one plan. **There is no
  lower bound.** A variant the gate refuses is gone, not repaired, so one or two
  candidates is an ordinary success (074's zero-crossing rule costs scene 08e
  its third). `budget.min_candidates` (3 by default) is carried and handed down
  to each module budget and **nothing reads it**: it is not a floor, and it is
  not validated either. Zero is never a quiet empty list — it is a refusal that
  names itself (the four categories below). Each surviving candidate carries its
  evidence (`LayoutEvidence`: checker name, hard violations, grammar findings,
  raw soft metrics with a reason each) and the plan's two source digests.

**The four failure categories** (053 sec.4). The first two belong to the grammar
layer and travel through unchanged; the last two are computed here:

=========================  ==================================================
``facts-missing``          a fact the compiler needs was not stated: a document
                           naming a part or net the circuit does not declare, a
                           part whose `symbolRef` has no profile with pins
``circuit-invalid``        the connections contradict the grammar's topology
``layout-unsat``           no legal layout inside this budget: the region is
                           smaller than the smallest legal drawing, a locked
                           part sits outside it, no legal pose puts a symbol's
                           pins on the required axis, a pin tip is not on the
                           compilation lattice, or a net is unroutable
``presentation-poor``      the intent contradicts itself: a lock that fights a
                           grammar relation or a pose the symbol does not
                           declare, a part claimed by two modules
=========================  ==================================================

A finite search that finds nothing says so: every `layout-unsat` message names
what was searched inside the budget, with an action that changes the answer.
None of them say "no solution".

**Guards this module is written under** (053 sec.7):

* offline only — no bridge, no connector, no editor, no rules;
* label policy is hard-coded: a net the grammar promised to wire is wired, and
  only a cross-module net or a high-fan-out net may be expressed as a label or a
  flag. A promise is never quietly downgraded to a name;
* no global law: the axis, the direction of the chain and the side everything
  hangs from come from `sidePreferences` and the grammar's own constraint kinds
  (which read the same preferences), never from a constant like "inputs are on
  the left";
* no total score anywhere: raw soft metrics with one reason each, and
  :func:`layered_key` is a tuple compared lexicographically;
* tool surface: this module adds no CLI action, no bridge action and no
  user-visible document. It is an internal engine, and the preview it renders
  (`engines/svgpreview.py`) is a file an operator opens, not an editor action.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from heapq import heappop, heappush
from typing import Any

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.designintent import DesignIntent, IntentSource
from boardwise.core.geometry import transform_point
from boardwise.core.layoutplan import (
    DOWNGRADE_NOTE_PREFIX,
    LayoutEvidence,
    LayoutJunction,
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core import textmetrics
from boardwise.core.presentationspec import LABEL_LABEL, PresentationSpec
from boardwise.core.symbolprofile import (
    FLAG_GLYPH_KIND_GND,
    FLAG_GLYPH_ROTATION_OFFSETS,
    PIN_LINE_OVERLAP,
    Box,
    SymbolPin,
    SymbolPose,
    SymbolProfile,
    check_box,
    flag_glyph_box,
    flag_glyph_kind,
    pose_box,
    role_siblings,
)

from . import readability
from .grammar import bind as bind_grammar
#: The lattice search and the geometry helpers it is defined in terms of, moved
#: to `engines/router.py` (112) so the interactive draw flows can route on the
#: same walls the compiler routes on. A copy would be a second opinion about
#: where a body begins, and the two would drift; this import is the seam. The
#: one helper that did **not** move is `_compress` — the router never calls it
#: (`route` returns lattice nodes), while every segment this module emits goes
#: through it and `pagecompiler` uses it under the name `compress_path`.
from .router import (
    CROSS_COST,
    TURN_COST,
    _Router,
    _close,
    _collinear_overlap,
    _key,
    _on_polyline,
    _rounded,
    _segment_hits_box,
    _strictly_on_segment,
)

#: The two costs still live on this module's namespace: they were public here
#: since 053 (`drawcompiler.TURN_COST`), and a name that vanishes because its
#: definition moved is a silent break for any caller that read it off this
#: module rather than off the router. Nothing here *uses* them — the router does
#: — so they are re-exported, not imported for their own sake.
from .grammar.base import (
    ABOVE,
    ADJACENT,
    BELOW,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
    GND_OUTLET,
    HORIZONTAL_TAP,
    LEFT_OF,
    NEAR,
    NET_ROLES,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_COLUMN,
    SAME_ROW,
    UNIFORM_GND,
    VERTICAL_TAP,
    VISIBLE_TAP,
    GrammarFailure,
    GrammarResult,
    nc_pins_of,
)
from .readability import CHECKER_NAME, DEFAULT_GRID, derive_netlist

__all__ = [
    "BRANCH_ROLES",
    "CHAIN_ROLES",
    "COMPILER_NAME",
    "Candidate",
    "CompileBudget",
    "CompileError",
    "CompileResult",
    "GrammarFinding",
    "KIND_BINDING_UNPLACED",
    "KIND_OBLIGATION_MISSING",
    "KIND_RELATION_BROKEN",
    "RejectedCandidate",
    "SIDE_ROLES",
    "check_grammar",
    "compile",
    "compress_path",
    "flag_rotation",
    "font_text_box",
    "lattice_router",
    "layered_key",
    "one_bend_route",
    "profile_book",
    "rank_key",
    "span_free",
    "text_width",
    "wire_junctions",
]


#: What a caller writes into ``LayoutEvidence.checker``. The *evidence* itself
#: is the readability checker's output, so this names the compiler as the plan's
#: author and stays separate from `readability.CHECKER_NAME`.
COMPILER_NAME = "boardwise-drawcompiler/1"

#: The compilation lattice, in canvas units — the same one `engines/layout.py`
#: measures and `readability.DEFAULT_GRID` treats as "the same column or row".
GRID = DEFAULT_GRID

#: A sheet, when the caller states a region: the A4-landscape calibration
#: `engines/layout.py` uses (calibration constants, not format facts).
#: ``CompileBudget.page_box = None`` means "no page was stated": the drawing is
#: then compiled in a frame of its own, and the page half of the readability
#: contract is *not evaluated* rather than guessed.
DEFAULT_PAGE: Box = (0.0, 0.0, 1169.0, 826.0)

#: Clear space between the drawing and the region's edge.
PAGE_MARGIN = 20.0

#: The wiring channel between two chain parts: the wire between their facing pin
#: tips, wide enough for a tee and a junction dot.
CHANNEL = 40.0

#: How far a branch hangs off the node it belongs to (base value; grown by the
#: spacing ladder, and by whatever the real boxes need).
LANE = 60.0

#: Where a **decoupling capacitor** hangs when its node's symbol carries a role on
#: pads the body separates (069 sec.11, 岳 on the landed page: 「右侧的旗标和电容离
#: 器件太远了贴近一点」). His own AMS1117 hangs C1/C2 off pin 4's short rail 15–25
#: units down, and that is the spacing the drawing is read at; a symbol whose pads all
#: leave one side keeps the ordinary lane (the branch then has room the flags need).
DECAP_LANE = 20.0

#: How far past the branch roots the tap stub runs: where the tap's label goes.
STUB = 30.0

#: How far a flag's anchor sits from the pin it names, when the lead wire fits.
FLAG_LEAD = 30.0

#: How far the short **vertical bend** runs when a flag's lead would be horizontal
#: (069 sec.7, 岳: 「旗标一定要竖直摆放不能平放」): his own drawing turns 20 units up
#: from VIN's stub to the flag, and 30 from the left VOUT pad. A flag is never laid
#: on its side, so a horizontal lead turns by this much and the flag hangs at the
#: end of the turn.
FLAG_JOG = 25.0

#: The margin a flag keeps between its whole box — glyph **and** the name row the
#: host prints — and anything else. 069 sec.8 (岳: 「3V3的旗标标识和5V的导线重合了」)
#: is about *touching*, so the box the placement keeps free is the glyph, that row
#: and this clearance.
#:
#: 148 removed the two constants that used to sit here (`FLAG_TEXT_NEAR` /
#: `FLAG_TEXT_REACH`, a band 6–16 units above the anchor). They were a **second
#: model** of where the host prints a flag's name; 147 measured the real one
#: (`core.textmetrics.flag_name_box`: the ten units immediately past the glyph, on
#: the far side of the connection) and put it in the readability gate. Two models
#: disagree wherever the glyph is not ten units tall, and the compiler reserved a
#: band that ended ten units short of the row the gate refuses a conductor inside
#: — measured on `test/P1`, where SW's run went through the HVDC flag's name row
#: in exactly that gap (`_flag_box`).
FLAG_CLEARANCE = 5.0

#: How far a **duplicate pad across the body** is brought out before its own flag
#: goes on (069 sec.1). 岳's hand-drawn AMS1117 brings a far pad out 40-60 units
#: and puts the flag on the end of that stub instead of running a wire over the
#: part to its twin; the same number is 069 sec.3's ceiling, beyond which a power
#: pin's reach is a long run rather than a stub.
SIBLING_LEAD = 50.0

#: 145a: how many lattice steps of a label's first stub rung are reserved for it
#: before any wire is routed (:func:`_reserve_label_stubs`). Two steps is
#: `drawapply.LABEL_STUB_LENGTH` — the page layer's own first rung for a name stub
#: (057/099d) — so the lane promised here is the run that layer draws first. A
#: shorter rung (the label box's own reach, when that is shorter) is a subset of
#: it, and `tests/test_145a_walls.py` pins the two constants equal so they cannot
#: drift apart.
LABEL_LANE_STEPS = 2

#: Minimum gap between two boxes that must not touch.
GAP = 20.0

#: Text metrics: cap height, line step, gap from a part's box.
TEXT_SIZE = 9.0
TEXT_LINE_STEP = 14.0
TEXT_GAP = 8.0

#: The height of one row of the **host's** own part text (146). The host draws a
#: placed part's designator and value in one 10-unit row anchored at the row's
#: lower-left corner — measured on `test/P1`'s 145e render, where every one of
#: the 38 rows occupies exactly ``anchor .. anchor + 10`` in canvas units (the
#: render draws them at 7.15 px, and the canvas unit comes out at
#: `drawlint.CANVAS_TEXT_UNITS`). The compiler's own :data:`TEXT_SIZE` is the
#: cap height it reserves with; this is the box the host actually paints, which
#: is what routing has to avoid.
TEXT_ROW_HEIGHT = 10.0

#: How many :data:`TEXT_GAP` rungs a text box or a flag name may be stepped
#: **outward** before the placement gives up and falls back (117②).
#:
#: Both side ladders used to try a single offset per direction and then fall
#: back to the first one, which is how the flyback ended up with eight
#: `text-overlap`s in a page where every one of the eight had a free slot a
#: second rung out (measured — `test_every_one_of_the_eight_has_a_free_slot_somewhere`).
#: The bound is what keeps the cure from becoming a different disease: a flag
#: name that has wandered :data:`TEXT_GAP` * 4 = 32 units from its own pin is
#: still that pin's name, and one that has wandered across the page is not.
#: **The rung count is an estimate** — the box is still `font_text_box` and the
#: width is still the `GLYPH_ADVANCE` sum, but how far it has to go is counted
#: rather than measured, so it is stated as a constant rather than derived.
TEXT_ESCALATION_STEPS = 4

#: Member count above which a *rail* may be drawn with flags instead of a wire.
#: 053 sec.7: labels wait for "high fan-out"; three is where a rail stops being
#: a local connection and becomes a bus.
HIGH_FANOUT = 3

#: How far apart two parts may be and still read as one local group — what the
#: grammar's `near` relation is measured against.
NEAR_LIMIT = 300.0

#: The corridor a net's search may use, beyond the net's own bounding box.
SEARCH_MARGIN = 160.0

#: The roles that bind a **chain** element: the series line the drawing is read
#: along. Verbatim from 053 sec.3's three tables (`upper_arm`/`lower_arm` the
#: divider's arms, `series` the RC's element, `core` the regulator), plus this
#: batch's `middle_arm` for the multi-tap ladder and 088's `entry` — the power
#: inlet, which is the one part the two rails run to and from. A role that is in
#: neither tuple is treated structurally: bound to a part, it would get no slot
#: of its own and land on the free shelf, which is why 088's `entry` had to be
#: named here rather than left to fall through.
CHAIN_ROLES: tuple[str, ...] = (
    "upper_arm", "lower_arm", "middle_arm", "series", "core", "entry",
    # flyback (113): the transformer's **primary** chain, read left to right
    # from the bus through the switch to the sense. These are the parts the
    # drawing is read *along*, so they are chain elements rather than
    # branches — the same kind of addition 088 made for `entry`. Only the
    # primary half is here: the secondary is laid out by the relations the
    # grammar states about it (the feedback row, the isolation crossing), and
    # naming it as a chain as well would give the compiler two chains and no
    # way to say which one the page is read along.
    "transformer", "switch", "sense", "sec-D", "opto",
)

#: The roles that bind an element **hanging off** a chain node (053 sec.3:
#: 并联支路 / 多 C 并联 / 电容各归所属节点 / NR 电容), plus this batch's
#: `tap_branch`. Both tuples are the grammar's published role vocabulary, not
#: per-scenario constants: a role in neither is treated structurally. 098's
#: `bridge` is the same kind of addition `entry` was to :data:`CHAIN_ROLES`: a
#: part across two of its core's own pins still *hangs off* the pin the drawing
#: reads it from (the crystal off XI, its other pin reaching XO), and a role
#: named in neither tuple would be laid on the free shelf instead of at the pin
#: it belongs to.
BRANCH_ROLES: tuple[str, ...] = (
    "tap_branch",
    "shunt",
    "bridge",
    "in_caps",
    "out_caps",
    "aux_branch",
    # flyback (113): everything that hangs off the primary chain's nodes. Each
    # is named for the same reason 098 named `bridge` — a role left out of
    # both tuples is bound to a part and would land on the free shelf instead
    # of at the node it belongs to, which for a power stage is the difference
    # between a drawing and a scatter of parts.
    "clamp-R", "clamp-C", "clamp-D",       # the leakage clamp
    "sec-D", "output-caps",                # the secondary rectifier and filter
    "feedback-divider", "error-amp", "opto",  # the feedback chain
    "compensation", "aux-D", "aux-C",      # loop gain and the aux supply
)

#: Which `sidePreferences` entry a branch role is read against (052 sec.4's side
#: vocabulary). A branch whose role names a side goes on **that** side when the
#: presentation states it (060 sec.1: the measured AMS1117 leaves VIN and VOUT on
#: one side, which is what put an LDO's input and output capacitors on top of each
#: other); when the presentation states nothing, the side is only the grammar's
#: default *reading order* and the branch follows the pin it hangs off — the
#: symbol's own geometry decides. A role that names no side (`aux_branch`,
#: `tap_branch`, `shunt`) is never moved by a side preference: an EN/NR branch
#: hangs off the pin it serves, and the RC's shunt states its own line
#: (`same-row` with its series element, checked before this).
SIDE_ROLES: dict[str, str] = {"in_caps": "input", "out_caps": "output"}

#: The sides a text block may be put on, in the order they are tried.
TEXT_SIDES: tuple[str, ...] = ("right", "left", "above", "below")

#: Object prefixes for findings, matching the readability checker's own spelling
#: so a report line reads the same in both layers.
LOCK_PREFIX = "presentationSpec.userLocks"


class CompileError(ValueError):
    """The compiler was called wrongly — a programming error, not bad input.

    Input problems never raise: they come back as a :class:`CompileResult` whose
    `failures` carry one of 053 sec.4's four categories, each with a reason and
    (where one exists) an action. A model writes the inputs, and "invalid" alone
    sends it back with nothing to compare against.
    """


# ---------------------------------------------------------------- text metrics
#
# A per-glyph advance table, in canvas units at :data:`TEXT_SIZE`. A *table*
# rather than a per-character constant, because the readability contract
# measures text overlap against these boxes: a count cannot tell "iii" from
# "MMM", and the box a part's value occupies has to be the box it draws. The
# proportions are the usual single-stroke EDA font's (digits uniform and wide,
# `I`/`i`/`l` narrow, `M`/`W`/`m`/`w` wide); the absolute scale keeps the cap
# height at TEXT_SIZE and the average near the 6 units/char the repo measured
# for net-name bands, so an existing drawing does not get a surprise.

GLYPH_ADVANCE: dict[str, float] = {
    **{digit: 7.0 for digit in "0123456789"},
    "I": 3.5, "J": 6.5, "M": 9.5, "W": 9.5,
    "i": 3.5, "j": 3.5, "l": 3.5,
    "f": 5.5, "r": 5.5, "t": 5.5,
    "m": 9.5, "w": 9.5,
    ".": 3.0, ",": 3.0, ":": 3.0, ";": 3.0, "'": 3.0, "!": 3.5,
    "-": 6.0, "+": 6.0, "=": 6.0, "*": 6.5,
    "(": 4.0, ")": 4.0, "[": 4.0, "]": 4.0, "{": 4.5, "}": 4.5,
    "/": 5.0, "\\": 5.0, "|": 3.5, "_": 7.0,
    "#": 8.0, "$": 7.0, "%": 9.0, "&": 8.5, "@": 10.0,
    " ": 4.5, "\u00b0": 5.0, "\u03bc": 8.0, "\u03a9": 9.0,
}

#: Anything not in the table — an unnamed uppercase or lower-case letter, a
#: non-ASCII character. Wide on purpose: over-estimating a box makes the drawing
#: keep more room, under-estimating makes it overlap.
TEXT_ADVANCE_FALLBACK = 8.0


def text_width(text: str, *, size: float = TEXT_SIZE) -> float:
    """The advance width of `text`, in canvas units, from the glyph table.

    Scales linearly with `size`, so a caller that changes the size moves every
    box consistently — the property a character-count estimate cannot have.
    """
    if size <= 0:
        raise CompileError(f"text size must be positive, got {size!r}")
    scale = size / TEXT_SIZE
    total = 0.0
    for character in text:
        total += GLYPH_ADVANCE.get(character, TEXT_ADVANCE_FALLBACK)
    return round(total * scale, 6)


def font_text_box(text: str, *, x: float, y: float, size: float = TEXT_SIZE) -> Box:
    """The box `text` occupies when centred on ``(x, y)``.

    The one ruler for every text this compiler places: label boxes,
    reference/value boxes, and the boxes the readability checker tests for
    overlap. Text too long for the room it has is *not* squeezed — the candidate
    is refused instead (053 sec.5 scenario 10).
    """
    width = text_width(text, size=size)
    half = size / 2.0
    return (x - width / 2.0, y - half, x + width / 2.0, y + half)


# ------------------------------------------------------------------ contracts


@dataclass
class CompileBudget:
    """What the compiler may use, and how hard it may try.

    ``page_box`` is the region the drawing must fit in (canvas units). ``None``
    means the caller states no page and the compiled drawing defines its own
    frame (the readability contract's page half is then not evaluated, which is
    its own rule for "no page given").

    ``spacing_ladder`` is 053 sec.4's "网格阶梯": the multipliers the chain pitch
    and the branch lanes are scaled by. Its floor is the geometric minimum
    (bodies, pins and the wiring channel), so "did not fit" can never be repaired
    by squeezing text.
    """

    page_box: Box | None = None
    keepouts: tuple[Box, ...] = ()
    grid: float = GRID
    min_candidates: int = 3
    max_candidates: int = 8
    spacing_ladder: tuple[float, ...] = (1.0, 1.5, 2.2)
    channel: float = CHANNEL
    lane: float = LANE
    stub: float = STUB
    high_fanout: int = HIGH_FANOUT
    near_limit: float = NEAR_LIMIT
    #: Symbol refs for rail flags: the ground flag, and the prefix a rail's flag
    #: is looked up under (net ``VIN`` -> symbol ``PWR-VIN``). A flag the library
    #: does not carry is written as a net label instead — the same kind of name
    #: in the netlist, and `uniform-gnd` is what refuses a drawing that mixes
    #: the two styles.
    gnd_flag: str = "PWR-GND"
    power_flag_prefix: str = "PWR-"


@dataclass(frozen=True)
class GrammarFinding:
    """One grammar-layer finding about a *plan* (053 sec.2's grammar checker).

    The companion of :class:`~boardwise.engines.readability.HardViolation`: the
    same shape (kind, objects, evidence), for the other half of the contract. It
    is computed from the plan and the specs, never from this compiler's own
    bookkeeping, which is what makes "抽头可见 / 支路归属 / 电容归侧" checkable
    by the layer that owns the promise.
    """

    kind: str
    objects: tuple[str, ...]
    detail: str

    def render(self) -> str:
        """One line, the shape ``LayoutEvidence.grammar_findings`` holds."""
        return f"[{self.kind}] {' + '.join(self.objects)}: {self.detail}"


KIND_BINDING_UNPLACED = "grammar-binding-unplaced"
KIND_RELATION_BROKEN = "grammar-relation-broken"
KIND_OBLIGATION_MISSING = "grammar-obligation-missing"


@dataclass
class RejectedCandidate:
    """A variant that lost — so "why is there no candidate" stays answerable."""

    variant: str
    reason: str
    violations: list[str] = field(default_factory=list)
    failure: GrammarFailure | None = None


@dataclass
class Candidate:
    """One legal plan, with the numbers the ranking was made from."""

    plan: LayoutPlan
    findings: list[GrammarFinding]
    metrics: dict[str, float]
    reasons: dict[str, list[str]]
    key: tuple[Any, ...]

    def describe_key(self) -> str:
        """``legality=0, findings=0, crossings=0, …`` — the layers, in order."""
        names = ("legality", "findings", "crossings", "bends", "wire_length",
                 "compactness")
        return ", ".join(f"{name}={value:g}" for name, value in zip(names, self.key))


@dataclass
class CompileResult:
    """The compiler's whole answer: candidates, refusals, and what it tried.

    ``candidates`` is what the caller draws: at least one and at most
    ``budget.max_candidates`` (8 by default) legal plans, best first. Fewer is
    normal output, not a defect — every variant the gate refused is simply not
    in the list; ``failures`` is why nothing could be drawn, in 053 sec.4's four
    categories; ``rejected`` is the audit trail of the variants that were built
    and lost. A refusal is never an empty success: a result with no candidate
    and no failure would be the "invalid spec" answer the contract exists to
    avoid, and the compiler's own zero-candidate path refuses that by naming a
    reason even when it has none to name.
    """

    candidates: list[LayoutPlan] = field(default_factory=list)
    ranked: list[Candidate] = field(default_factory=list)
    failures: list[GrammarFailure] = field(default_factory=list)
    rejected: list[RejectedCandidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    grammar: GrammarResult | None = None

    @property
    def ok(self) -> bool:
        """At least one legal plan came out."""
        return bool(self.candidates)

    def best(self) -> LayoutPlan | None:
        return self.candidates[0] if self.candidates else None

    def categories(self) -> list[str]:
        """The distinct failure categories, in 053 sec.4's order."""
        order = ("facts-missing", "circuit-invalid", "layout-unsat",
                 "presentation-poor")
        found = {item.category for item in self.failures}
        return [name for name in order if name in found]

    def render_failures(self) -> str:
        """One line per failure: ``[category] detail — try: action``."""
        lines = []
        for item in self.failures:
            line = f"[{item.category}] {item.detail}"
            if item.action:
                line += f" — try: {item.action}"
            lines.append(line)
        return "\n".join(lines)


# --------------------------------------------------------------------- entry


def compile(  # noqa: A001 - the name 053 sec.4 fixes for the entry point
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | None = None,
    budget: CompileBudget | None = None,
    *,
    intent: IntentSource | DesignIntent | None = None,
) -> CompileResult:
    """Compile a drawing, or say why there is none.

    The four stages, the gate and the layered ranking are in the module
    docstring. A refusal returns ``candidates == []`` with the reasons in
    ``failures`` — ``ok`` is then False, ``best()`` is None, ``failures`` is
    never empty, and each entry carries a category, the measured detail and an
    action, so zero candidates is a named ``layout-unsat``-or-worse answer
    rather than a silent empty table; a success returns 1 to
    ``budget.max_candidates`` plans (8 by default), best first, each with its
    evidence filled in and its source digests pinned. Two is a success, not a
    shortfall: the gate removes variants and nothing promises a minimum.

    ``intent`` is the `DesignIntent` the grammar may read (095 A4), keyword-only
    and ``None`` by default: today it is consumed by `power-entry` alone, for the
    branch order a presentation had to restate until 095. It travels into **both**
    reads of the grammar — the binding that produces the constraints and the
    independent checker that grades the finished plan against them
    (:func:`check_grammar`) — because a checker that re-bound without it would
    grade the plan against a different order than the one it was drawn with. A
    library, by contrast, stays a construction input: it is the same for every
    call on a pair of documents, while a contract is a document of its own. None
    is a drawing that reads no contract, byte-for-byte the one this compiler made
    before the batch.
    """
    for value, expected in (
        (circuit_spec, CircuitSpec),
        (presentation_spec, PresentationSpec),
    ):
        if not isinstance(value, expected):
            raise CompileError(
                f"{expected.__name__} expected, got {type(value).__name__}"
            )
    if intent is not None and not isinstance(intent, (IntentSource, DesignIntent)):
        raise CompileError(
            f"intent must be an IntentSource or a DesignIntent, got "
            f"{type(intent).__name__} — a contract the grammar cannot read is not "
            "the same drawing as no contract, and this one would be silently "
            "ignored"
        )
    budget = budget or CompileBudget()
    _check_budget(budget)
    book = _profile_book(profiles)

    result = CompileResult()
    result.notes.append(
        f"{COMPILER_NAME}: lattice {budget.grid:g} units; spacing ladder "
        + ", ".join(f"{value:g}x" for value in budget.spacing_ladder)
    )

    # 1. the two documents must agree before any geometry is attempted.
    blockers = _reference_failures(circuit_spec, presentation_spec)
    if blockers:
        result.failures = blockers
        return result

    # 2. bind; a refusal travels through verbatim. The contract travels with it
    #    (095 A4): the order a decision states is a binding, not a decoration.
    binding = bind_grammar(circuit_spec, presentation_spec, book, intent=intent)
    result.grammar = binding
    if not binding.ok:
        result.failures = list(binding.failures)
        result.notes.append(
            "the grammar refused this circuit, so no geometry was attempted: "
            + "; ".join(item.detail for item in binding.failures[:3])
        )
        return result

    # 3. the library has to describe every part that must be placed.
    missing = _library_failures(circuit_spec, book)
    if missing:
        result.failures = missing
        return result

    # 4. semantics: roles and relations -> ranks and lanes.
    prepare = _prepare(
        circuit_spec, presentation_spec, binding, book, budget, intent=intent
    )
    if prepare.failures:
        result.failures = prepare.failures
        return result
    ctx = prepare.context
    assert ctx is not None

    # 5. geometry: variants -> plans -> the hard gate.
    seen: set[str] = set()
    _try_variants(ctx, _variants(ctx), result, seen, circuit_spec,
                  presentation_spec, book, budget, intent)

    # 119: the pose ladder, widened. This runs **only** when the ladder just tried
    # produced no candidate at all, and only for the one situation a wider ladder
    # can answer — see :func:`_widened_variants` for both halves of that claim
    # and for why it is structurally the identity on every input that compiles.
    widened = _widened_variants(ctx, result)
    if widened:
        result.notes.append(
            f"no candidate from the {len(result.rejected)} base variant(s); every "
            f"one of them was refused by the same relation "
            f"({_widening_blocker_label(result)}), so the pose ladder was widened "
            f"to the {len(widened)} variant(s) its accepted poses still hold"
        )
        _try_variants(ctx, widened, result, seen, circuit_spec,
                      presentation_spec, book, budget, intent)

    if not result.ranked:
        result.failures = _no_candidate_failures(result, budget)
        return result

    result.ranked.sort(key=lambda item: item.key)
    result.candidates = [item.plan for item in result.ranked]
    result.notes.append(
        f"{len(result.candidates)} legal candidate(s) from "
        f"{len(result.candidates) + len(result.rejected)} variant(s) built; "
        "the gate was the independent readability checker, and the ranking "
        "compares its layers without summing them"
    )
    return result


# -------------------------------------------------------------------- budget


def _check_budget(budget: CompileBudget) -> None:
    if isinstance(budget.grid, bool) or not isinstance(budget.grid, (int, float)):
        raise CompileError(f"grid must be a number, got {budget.grid!r}")
    if budget.grid <= 0:
        raise CompileError(f"grid must be positive, got {budget.grid!r}")
    if budget.page_box is not None:
        check_box(budget.page_box, "budget.page_box", CompileError)
    for index, item in enumerate(budget.keepouts):
        if check_box(item, f"budget.keepouts[{index}]", CompileError) is None:
            raise CompileError(
                f"budget.keepouts[{index}] is not a box — an absent keep-out is "
                "one the caller should not have listed"
            )
    if not budget.spacing_ladder:
        raise CompileError(
            "budget.spacing_ladder is empty — the ladder is the whole reason a "
            "candidate can be refused for space and retried with more room"
        )
    for value in budget.spacing_ladder:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise CompileError(
                f"budget.spacing_ladder holds {value!r}; every rung is a positive "
                "multiplier of the geometric minimum"
            )
    if budget.max_candidates < 1:
        raise CompileError(
            f"budget.max_candidates is {budget.max_candidates!r}; a budget that "
            "allows no candidate cannot answer"
        )


def _profile_book(
    profiles: Mapping[str, SymbolProfile] | None,
) -> dict[str, SymbolProfile]:
    """``symbolRef -> SymbolProfile``, refusing a mapping that disagrees with itself.

    The same rule `readability._profile_map` applies, for the same reason: a
    part checked against the wrong symbol's pins is the worst failure mode this
    pipeline has, and it is silent.
    """
    if profiles is None:
        return {}
    if not isinstance(profiles, Mapping):
        raise CompileError(
            "profiles must be a mapping symbolRef -> SymbolProfile (or None), got "
            f"{type(profiles).__name__}"
        )
    book: dict[str, SymbolProfile] = {}
    for key, profile in profiles.items():
        if not isinstance(profile, SymbolProfile):
            raise CompileError(
                f"profiles[{key!r}] is {type(profile).__name__}, expected a "
                "SymbolProfile"
            )
        if str(key) != profile.symbol_ref:
            raise CompileError(
                f"profiles[{key!r}] holds the profile of {profile.symbol_ref!r} — a "
                "library is keyed by the symbol it describes"
            )
        book[str(key)] = profile
    return book


# ----------------------------------------------- stage 0: cross-document facts


def _reference_failures(
    circuit_spec: CircuitSpec, presentation_spec: PresentationSpec
) -> list[GrammarFailure]:
    """The cross-document checks neither stage-A contract can make itself.

    Both documents are closed schemas, so neither can say "this id exists": a
    module's `parts`, a `mainPaths` step, a `portRoles` key, an
    `directWiringObligations` net or a `userLocks[*].partId` may all name
    something the circuit does not declare. The presentation spec's own
    docstring puts that cross-check here, on the compiler.

    Two readings are kept apart: a reference to nothing is `facts-missing` (the
    named element is missing from the circuit), while a part claimed by two
    modules is `presentation-poor` — the intent does not say which group owns it.
    """
    out: list[GrammarFailure] = []
    parts = set(circuit_spec.part_ids())
    nets = set(circuit_spec.net_ids())

    for module in presentation_spec.modules:
        unknown = sorted(part_id for part_id in module.parts if part_id not in parts)
        if unknown:
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=module.id,
                detail=(
                    f"PresentationSpec.modules[{module.id}].parts names "
                    f"{', '.join(unknown)}, which CircuitSpec.parts does not "
                    "declare — the module groups a part that does not exist, so "
                    "nothing tells the layout what it holds"
                ),
                action=(
                    "add the part to CircuitSpec.parts[] (or fix the id), or "
                    "remove it from the module"
                ),
            ))
    claims: dict[str, list[str]] = {}
    for module in presentation_spec.modules:
        for part_id in module.parts:
            claims.setdefault(part_id, []).append(module.id)
    for part_id in sorted(claims):
        if len(claims[part_id]) < 2:
            continue
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=part_id,
            detail=(
                f"{part_id} is claimed by modules "
                + " and ".join(repr(name) for name in claims[part_id])
                + " — a part belongs to one group, and which one is exactly what "
                  "decides where its branches hang"
            ),
            action=(
                f"list {part_id} in exactly one PresentationSpec.modules[] entry, "
                "or drop the module split if the page is one group"
            ),
        ))

    for path in (*presentation_spec.main_paths, *presentation_spec.feedback_paths):
        for step in path.chain:
            kind, _, name = step.partition(":")
            known = parts if kind == "part" else nets if kind == "net" else set()
            if name in known:
                continue
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=path.id or "path",
                detail=(
                    f"PresentationSpec path {path.id or '(no id)'} walks {step!r}, "
                    f"but the circuit declares no {kind} {name!r}"
                ),
                action=(
                    f"declare {kind} {name!r} in the CircuitSpec, or fix the step — "
                    "a path is a claim about the drawing the reader will follow"
                ),
            ))
    for net_id in sorted(presentation_spec.port_roles):
        if net_id in nets:
            continue
        out.append(GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            subject=net_id,
            detail=(
                f"PresentationSpec.portRoles names {net_id!r}, which is not one of "
                "the circuit's nets"
            ),
            action="fix the port's net id, or declare the net in CircuitSpec.nets",
        ))
    for obligation in presentation_spec.direct_wiring_obligations:
        unknown = sorted(net_id for net_id in obligation.nets if net_id not in nets)
        if unknown:
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=obligation.nets[0],
                detail=(
                    "PresentationSpec.directWiringObligations names "
                    f"{', '.join(unknown)}, which the circuit does not declare"
                ),
                action=(
                    "fix the net ids — an obligation protects a local topology, and "
                    "it can only protect a net the circuit has"
                ),
            ))
    for lock in presentation_spec.user_locks:
        if lock.part_id in parts:
            continue
        out.append(GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            subject=lock.part_id,
            detail=(
                f"{LOCK_PREFIX}[{lock.part_id}] locks a part the CircuitSpec does "
                "not declare — the lock has nothing to hold"
            ),
            action="fix the locked part id, or drop the lock",
        ))
    return out


def _library_failures(
    circuit_spec: CircuitSpec, book: Mapping[str, SymbolProfile]
) -> list[GrammarFailure]:
    """Parts whose symbol the library does not describe with any pin (053 sec.2).

    Without the profile there is no tip, no body box and no legal pose, so the
    geometry cannot be computed at all — and a plan that skipped the part would
    be a drawing of a different circuit. The action names the two legitimate
    repairs and the one that is forbidden: never renumber pins to fit.
    """
    missing: list[str] = []
    for part in sorted(circuit_spec.parts, key=lambda item: item.id):
        profile = book.get(part.symbol_ref)
        if profile is None or not profile.pins:
            missing.append(f"{part.id}({part.symbol_ref or 'no symbolRef'})")
    if not missing:
        return []
    more = f", … (+{len(missing) - 8} more)" if len(missing) > 8 else ""
    return [GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=missing[0].split("(")[0],
        detail=(
            f"{', '.join(missing[:8])}{more} have no SymbolProfile with pins, so "
            "their geometry — tip, pose, body — cannot be computed"
        ),
        action=(
            "build the profile (symbolprofile.from_parsed_symbol over the symbol's "
            "SYMBOL document, or a library export), or choose a compatible symbol "
            "whose pin mapping has been verified — renumbering pins to fit the "
            "layout is forbidden (053 sec.2)"
        ),
    )]


# ------------------------------------------------- stage 2: semantic layout


@dataclass(frozen=True)
class _Slot:
    """One part's place in the *relative* layout — still not a coordinate.

    ``rank`` is the order along the chain axis (0 = the power/input-most, which
    is what the grammar's `above`/`below`/`left-of`/`right-of` kinds mean). A
    chain part sits on the line itself; a branch part carries three facts that
    decide its geometry — none of them a constant:

    * ``basis`` — where its offset from the owner's pin runs: ``side`` along the
      side the grammar states for it (060 sec.1: "the input capacitor belongs on
      the input side"), ``line`` along the line a same-line kind names (053
      sec.3's RC shunt: "the shunt's out-side pin lands on the trunk row"),
      ``tap`` along the tap direction, ``pin`` along the owner's own pin
      direction (the LDO's EN/NR branches), ``across`` perpendicular to the chain
      (the default when nothing says);
    * ``sign`` — which way, from the rank order, so `left-of` puts the input
      capacitor on the left without this module knowing what a capacitor is;
    * ``other_net`` — the net the branch does *not* share with its owner, whose
      class and side preference say which way its body leaves the line.
    """

    part_id: str
    role: str
    kind: str
    axis: str
    rank: int
    owner: str = ""
    shared_net: str = ""
    other_net: str = ""
    pin_shared: str = ""
    pin_other: str = ""
    basis: str = ""
    sign: int = 1
    offset_axis: str = ""
    #: True when `sign` came from an order kind. False means the sign is resolved
    #: at placement time from the geometry (see :func:`_branch_basis`).
    sign_from_order: bool = True


@dataclass
class _Context:
    """Everything the geometry stages need, computed once per compilation."""

    circuit: CircuitSpec
    presentation: PresentationSpec
    binding: GrammarResult
    book: dict[str, SymbolProfile]
    budget: CompileBudget
    axis: str
    progress: tuple[float, float]
    chain_net_rank: dict[str, int]
    slots: dict[str, _Slot]
    chain: list[str]
    accepted: dict[str, list[SymbolPose]]
    body_dirs: dict[str, tuple[float, float]]
    #: The contract this compilation reads (095 A4), carried so the gate can
    #: re-bind the grammar with the same input the constraints came from.
    intent: IntentSource | DesignIntent | None = None
    #: ``part id -> (line axis, group label, group members)`` for the branches
    #: the grammar asked to share a line with **each other** (114 §四 second gap).
    #: Empty for every circuit whose same-line relations are all chain-to-branch,
    #: which is all five grammars before this batch — see outputs/114/SUMMARY.md.
    lane_groups: dict[str, tuple[str, str, list[str]]] = field(
        default_factory=dict
    )
    #: ``lane label -> that group's same-line edges`` as
    #: ``(subject, object, the net the pair is measured on)``; ``""`` for a pair
    #: that shares no net, which :func:`_points_for_relation` measures between
    #: the two origins instead. See :func:`_branch_lane_edges`.
    lane_edges: dict[str, list[tuple[str, str, str]]] = field(
        default_factory=dict
    )

    def profile(self, part_id: str) -> SymbolProfile:
        part = self.circuit.part(part_id)
        assert part is not None, part_id
        profile = self.book.get(part.symbol_ref)
        assert profile is not None, part.symbol_ref
        return profile

    def locked(self, part_id: str):
        for lock in self.presentation.user_locks:
            if lock.part_id == part_id:
                return lock
        return None

    def lateral(self) -> tuple[float, float]:
        """The axis perpendicular to the chain, which the line coordinate is on."""
        return (-self.progress[1], self.progress[0])


@dataclass
class _Prepare:
    context: _Context | None = None
    failures: list[GrammarFailure] = field(default_factory=list)


def _axis(binding: GrammarResult) -> str:
    """Which axis the chain runs on, from the relations the grammar stated.

    A relation is not a coordinate (053 sec.4), but it is a direction, and the
    two same-line kinds are the strongest statement about which axis the drawing
    is read along. A tie means the grammar said nothing about the axis at all:
    the presentation's own defaults put the supply above the ground, so the chain
    is drawn vertically — the one place a default is used, and it is the
    presentation's default rather than a law of this module.
    """
    votes = {"v": 0, "h": 0}
    for item in binding.constraints:
        if item.kind == SAME_COLUMN:
            votes["v"] += 2
        elif item.kind == SAME_ROW:
            votes["h"] += 2
        elif item.kind in (ABOVE, BELOW):
            votes["v"] += 1
        elif item.kind in (LEFT_OF, RIGHT_OF):
            votes["h"] += 1
    if votes["v"] == votes["h"]:
        return "v"
    return "h" if votes["h"] > votes["v"] else "v"


def _side_vector(presentation_spec: PresentationSpec, role: str) -> tuple[float, float]:
    """The unit vector of a side preference (``power: top`` -> up).

    The presentation's own default is used when the spec removed the entry: the
    contract states defaults (input left / output right / power top / gnd
    bottom), so a spec with an empty `sidePreferences` still compiles the book's
    drawing rather than an arbitrary one.
    """
    side = presentation_spec.side_for(role) or {
        "power": "top", "gnd": "bottom", "input": "left", "output": "right",
    }.get(role, "bottom")
    return {
        "top": (0.0, 1.0),
        "bottom": (0.0, -1.0),
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
    }.get(side, (0.0, -1.0))


def _progress(presentation_spec: PresentationSpec, axis: str) -> tuple[float, float]:
    """The direction rank *increases* in: away from the power/input end.

    ``power`` and ``input`` come from `sidePreferences`, so a spec that puts
    power at the bottom gets a ladder drawn bottom-up instead of a column with
    the wrong end at the top. The direction is the *negative* of the side vector
    — rank 0 sits at the power/input end, and rank grows as the drawing moves away
    from it. A spec whose side preference is perpendicular to the axis (power on
    the left of a vertical chain) has no answer here, and the book's default
    direction is used: down a column, right along a row.
    """
    if axis == "v":
        side = _side_vector(presentation_spec, "power")
        if side[1] != 0.0:
            return (0.0, -side[1])
        return (0.0, -1.0)
    side = _side_vector(presentation_spec, "input")
    if side[0] != 0.0:
        return (-side[0], 0.0)
    return (1.0, 0.0)


def _part_roles(binding: GrammarResult) -> dict[str, str]:
    """``part id -> its first bound role`` (net roles excluded)."""
    out: dict[str, str] = {}
    for item in binding.bindings:
        if item.role in NET_ROLES:
            continue
        out.setdefault(item.part_id, item.role)
    return out


def _part_nets(circuit_spec: CircuitSpec, part_id: str) -> dict[str, str]:
    """``spec pin token -> net id`` for this part (see `grammar.base.pins_of_part`)."""
    out: dict[str, str] = {}
    for net in circuit_spec.nets:
        for member in net.members:
            owner, _, pin = member.partition(".")
            if owner == part_id and pin:
                out[pin] = net.id
    return out


def _rank_edges(binding: GrammarResult) -> list[tuple[str, str]]:
    """``(before, after)`` pairs, with `before` nearer the power/input end.

    Each order kind is read through its own definition in `grammar/base.py`:
    `above` is "nearer the power end than object", `below` "nearer the ground
    end", `left-of`/`right-of` the horizontal spelling of the same idea. None of
    them is a coordinate, and none of them is re-decided here.
    """
    edges: list[tuple[str, str]] = []
    for item in binding.constraints:
        if item.kind == ABOVE:
            edges.append((item.subject, item.object))
        elif item.kind == BELOW:
            edges.append((item.object, item.subject))
        elif item.kind == LEFT_OF:
            edges.append((item.subject, item.object))
        elif item.kind == RIGHT_OF:
            edges.append((item.object, item.subject))
        elif item.kind == ADJACENT:
            edges.append((item.subject, item.object))
    return edges


def _ranks(edges: Sequence[tuple[str, str]], part_ids: Iterable[str]) -> dict[str, int]:
    """The chain order, by a Kahn walk with a stable tie-break (the part id).

    Two runs of one input therefore give the same ranks, and a part with no order
    relation lands at rank 0 rather than at a rank invented for it. A cycle — a
    presentation that contradicts itself — is broken by taking what is left in
    order instead of looping: reporting a contradiction is the grammar layer's
    job, and this stage must not hang on one.
    """
    nodes = sorted(set(part_ids) | {name for pair in edges for name in pair})
    indegree = {node: 0 for node in nodes}
    followers: dict[str, list[str]] = {node: [] for node in nodes}
    for before, after in edges:
        if before == after:
            continue
        followers[before].append(after)
        indegree[after] += 1
    ready = sorted(node for node in nodes if indegree[node] == 0)
    order: list[str] = []
    while len(order) < len(nodes):
        if not ready:
            ready = sorted(node for node in nodes if node not in order)
        node = ready.pop(0)
        if node in order:
            continue
        order.append(node)
        for follower in sorted(followers[node]):
            indegree[follower] -= 1
            if indegree[follower] <= 0 and follower not in order:
                ready.append(follower)
        ready.sort()
    return {node: index for index, node in enumerate(order)}


def _chain_net_ranks(binding: GrammarResult) -> dict[str, int]:
    """``net -> its position in the chain``, from the `direct-wire` obligations.

    The obligations are the grammar's statement of electrical order (053 sec.3:
    "in→upper→tap→lower→gnd 全链直连"), which is the one place the order of the
    *nets* is written down. Obligations are read in the order the grammar emitted
    them and a net already ranked keeps its rank, so the RC's two obligations
    (`in→out`, `out→gnd`) give `in=0, out=1, gnd=2` instead of ranking `gnd`
    beside `out`.
    """
    ranks: dict[str, int] = {}
    for item in binding.obligations:
        if item.kind != DIRECT_WIRE:
            continue
        previous: int | None = None
        for net in item.nets:
            if net in ranks:
                previous = ranks[net]
                continue
            previous = 0 if previous is None else previous + 1
            ranks[net] = previous
    return ranks


def _prepare(
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    binding: GrammarResult,
    book: dict[str, SymbolProfile],
    budget: CompileBudget,
    *,
    intent: IntentSource | DesignIntent | None = None,
) -> _Prepare:
    """Stages 2 and 3's inputs: axis, ranks, lanes, poses, lock legality."""
    axis = _axis(binding)
    progress = _progress(presentation_spec, axis)
    chain_net_rank = _chain_net_ranks(binding)
    part_roles = _part_roles(binding)
    edges = _rank_edges(binding)
    ranks = _ranks(edges, list(part_roles))
    in_edges = {name for pair in edges for name in pair}

    chain_roles = {
        part_id for part_id, role in part_roles.items() if role in CHAIN_ROLES
    }
    chain_ids = sorted(
        chain_roles, key=lambda part_id: (ranks.get(part_id, 0), part_id)
    )

    slots: dict[str, _Slot] = {}
    for part_id in chain_ids:
        slots[part_id] = _Slot(
            part_id=part_id, role=part_roles.get(part_id, ""), kind="chain",
            axis=axis, rank=ranks.get(part_id, 0),
        )

    order_failures: list[GrammarFailure] = []
    candidates: list[tuple[str, str, bool]] = []
    for item in binding.bindings:
        if item.role in NET_ROLES or item.part_id in slots:
            continue
        nets = _part_nets(circuit_spec, item.part_id)
        if not nets:
            continue
        classes = {
            net.cls for net in circuit_spec.nets if net.id in set(nets.values())
        }
        candidates.append((
            item.part_id, item.role,
            item.role in BRANCH_ROLES or (len(nets) == 2 and "gnd" in classes),
        ))

    owners, links, strings = _branch_owners(
        circuit_spec, [part_id for part_id, _, _ in candidates], chain_ids, ranks,
    )
    for part_id, role, is_branch in candidates:
        if not is_branch:
            continue
        owner = owners.get(part_id, "")
        if not owner:
            if part_id in strings:
                order_failures.append(GrammarFailure(
                    category=FAILURE_FACTS_MISSING,
                    subject=part_id,
                    detail=(
                        f"{part_id} is bound as {role!r} but its series string on "
                        f"net {strings[part_id]} reaches no chain part, so the node "
                        "it belongs to cannot be read off the page: the arms of the "
                        "string share only each other, and no end of it is anchored"
                    ),
                    action=(
                        "check the CircuitSpec connections of this series string "
                        "(its first arm must sit on a node some chain part also "
                        "touches), or the module split it is bound through"
                    ),
                ))
            continue
        slot = _branch_slot(
            circuit_spec, presentation_spec, binding, part_id, role,
            links[part_id], axis, ranks,
        )
        if slot is None:
            order_failures.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=part_id,
                detail=(
                    f"{part_id} is bound as {role!r} but shares no net with "
                    f"{links[part_id]}, so which node it belongs to cannot be read "
                    "from the circuit"
                ),
                action=(
                    "check the CircuitSpec connections of this branch (one end "
                    "on the node it decouples), or the module split it is bound "
                    "through"
                ),
            ))
            continue
        slots[part_id] = slot

    for part in circuit_spec.parts:
        if part.id in slots:
            continue
        slots[part.id] = _Slot(
            part_id=part.id, role=part_roles.get(part.id, ""), kind="free",
            axis=axis, rank=ranks.get(part.id, 0) + 1000,
        )

    lanes = _branch_lane_groups(binding, slots)
    ctx = _Context(
        circuit=circuit_spec, presentation=presentation_spec, binding=binding,
        book=book, budget=budget, axis=axis, progress=progress,
        chain_net_rank=chain_net_rank, slots=slots, chain=chain_ids,
        accepted={}, body_dirs={}, intent=intent,
        lane_groups=lanes,
        lane_edges=_branch_lane_edges(circuit_spec, binding, lanes),
    )
    failures = list(order_failures)
    for part_id in sorted(slots):
        slot = slots[part_id]
        if slot.kind == "branch":
            ctx.body_dirs[part_id] = _branch_body_direction(ctx, slot)
        poses, problem = _accepted_poses(ctx, slot)
        if problem is not None:
            failures.append(problem)
        ctx.accepted[part_id] = poses
    failures.extend(_lock_pose_failures(ctx))
    return _Prepare(context=ctx, failures=failures)


#: How many times the same-line relaxation may re-level a group before the stage
#: stops trying. A row of branches converges in two rounds (chain anchor, then
#: the branches hanging off it); the bound only matters for a group whose
#: relations cannot all be true at once, and then it is the *refusal* that has to
#: come out — the relation checker measures it and names the pair, which is a
#: better answer than a half-relaxed group.
LANE_RELAX_ROUNDS = 4

#: Bounds :func:`_honour_bound_orders` (116).  Same shape and same reason as
#: :data:`LANE_RELAX_ROUNDS`: a page whose bound orders are jointly satisfiable
#: converges in a couple of rounds (the real flyback does), and a page whose
#: orders fight each other runs out of rounds and the relation checker names the
#: pair with its two measured points.  It is a "give up and say so" bound, not a
#: modelling limit.
ORDER_RELAX_ROUNDS = 6


def _branch_owner(
    circuit_spec: CircuitSpec,
    part_id: str,
    chain_ids: Sequence[str],
    ranks: Mapping[str, int],
) -> str:
    """The part a branch hangs off: the chain part, or another branch, it reaches.

    A branch usually shares a net with a **chain** part, and that is the whole
    answer. The other case is a **series string** of branches: a leakage clamp's
    discharge path and an auxiliary winding's rectifier both hang off the same
    node, and the string's *intermediate* arm sits on a node no chain part ever
    touches (the flyback's `CLAMP_B` is shared by R3 and R15 and by neither T1 nor
    Q1). Such an arm is still owned — by the arm beside it, which does reach the
    chain. :func:`_branch_owners` resolves that by iterating ownership to a fixed
    point, so this function asks only the first question: "which chain part do we
    share a net with?", and the iteration above it walks the string.

    When it shares a net with two chain parts (the divider's tap belongs to both
    arms), the answer is the one nearer the power end — the branch hangs off the
    junction where the tap leaves, and the tie-break is the rank order the
    grammar already stated.

    A candidate that shares **only a ground** with this branch is the weaker
    claim, and it is ranked after any candidate that shares a node of its own:
    the flyback's C10 touches the primary ground (T1, R5) *and* the compensation
    node (U5), and a branch belongs to the node it decouples, not to the rail they
    all share. :func:`_shared_nets` states that rule for the net; applying it here
    as well is what keeps the owner and the anchor from being chosen by two
    different criteria.

    The rule is about **the shared node only** — it does not reach the branch's
    own pins, so a part with more than two nets is still anchored on whichever of
    its nets the owner shares, and the rank order still decides between two
    candidates of equal standing.
    """
    here = set(_part_nets(circuit_spec, part_id).values())
    candidates = [
        other for other in chain_ids
        if other != part_id and here & set(_part_nets(circuit_spec, other).values())
    ]
    if not candidates:
        return ""

    candidates.sort(key=lambda name: (ranks.get(name, 0), name))
    return candidates[0]


def _is_ground(circuit_spec: CircuitSpec, net_id: str) -> bool:
    """Is this net a ground-class net? A net the spec does not describe is not."""
    net = circuit_spec.net(net_id)
    return net is not None and net.cls == "gnd"


#: How far ownership may be carried from one branch to the next before the walk
#: gives up. A string is short by construction (a clamp, a rail), so the bound is
#: a safety stop against a presentation that wired every part to every part, not
#: a modelling limit: 114 §四 reports the real strings as two and three deep.
OWNER_ITERATIONS = 8


def _branch_owners(
    circuit_spec: CircuitSpec,
    branches: Sequence[str],
    chain_ids: Sequence[str],
    ranks: Mapping[str, int],
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """``(chain owner, the arm it hangs off, the string it broke on)``, fixed point.

    A branch that shares a net with a chain part is owned by it in one step. One
    that shares only with **other branches** is owned through them: the clamp's
    R3 reaches the chain through R15, so R15 is resolved first and R3 inherits.
    That is a fixed point, not a search — an arm's owner is its owner — so the
    iteration is monotone (an arm is only ever added, never re-pointed) and it
    terminates in at most one step per hop. :data:`OWNER_ITERATIONS` is the stop
    for the degenerate case where a presentation wires branches in a cycle, which
    the task book requires be **refused, not silently attached**: a cycle of
    branches with no chain anchor is a closed ring, not a page, and a branch
    inside one is left without an owner so :func:`_branch_slot` refuses it by
    name.

    ``links`` is the arm each branch **hangs off** — the chain part for a direct
    branch, and the neighbouring arm for one that reaches the chain through a
    string. It is what a branch's slot anchors on, because that is the net the two
    really share: the clamp's R3 hangs off R15 on `CLAMP_B`, not off T1, and
    anchoring it on T1 would be a wire the circuit does not contain.

    The fixed point runs over **all** branches, not only over the ones the chain
    could not place, because a chain part that shares nothing but a ground is a
    weaker claim than a branch that shares the branch's own node. The flyback's
    C7 is the case: it touches the primary ground (which the transformer shares
    with everything) and the auxiliary rail (which only the aux rectifier
    touches), and it belongs under the rectifier. A branch-to-branch edge on a
    non-ground net therefore **outranks** a chain claim, and a ground-only edge
    never creates one.
    """
    nets = {part_id: set(_part_nets(circuit_spec, part_id).values())
            for part_id in branches}
    owner: dict[str, str] = {}
    links: dict[str, str] = {}
    for part_id in branches:
        found = _branch_owner(circuit_spec, part_id, chain_ids, ranks)
        if found:
            owner[part_id] = found
            links[part_id] = found
    strings: dict[str, str] = {}
    for part_id in branches:
        if part_id in owner:
            continue
        here = nets[part_id]
        peers = sorted(
            other for other in branches
            if other != part_id and here & nets[other]
        )
        if peers:
            strings[part_id] = ",".join(sorted(here & nets[peers[0]]))
    for _ in range(OWNER_ITERATIONS):
        progressed = False
        for part_id in sorted(branches):
            if part_id in owner:
                continue
            here = nets[part_id]
            reachable = sorted(
                other for other in branches
                if other != part_id and other in owner and here & nets[other]
            )
            if not reachable:
                continue
            reachable.sort(key=lambda name: (ranks.get(name, 0), name))
            owner[part_id] = owner[reachable[0]]
            links[part_id] = reachable[0]
            progressed = True
        if not progressed:
            break
    # A branch that a **branch peer** claims on a node of its own outranks a chain
    # part it shared **only a ground** with — and only that. A chain part the
    # branch already reaches on a node of its own keeps it (the secondary's
    # reservoir hangs off the rectifier's output, not off its sibling's), so the
    # flyback's C7 moves onto the aux rectifier while C11 and C13 stay on D3.
    for _ in range(OWNER_ITERATIONS):
        progressed = False
        for part_id in sorted(branches):
            here = nets[part_id]
            current = links.get(part_id, "")
            if not current or current in chain_ids:
                shared = here & nets.get(
                    current, set(_part_nets(circuit_spec, current).values())
                )
                if any(not _is_ground(circuit_spec, net) for net in shared):
                    continue
            better = sorted(
                other for other in branches
                if other != part_id and other in owner
                and any(not _is_ground(circuit_spec, net)
                        for net in here & nets[other])
            )
            if not better:
                continue
            better.sort(key=lambda name: (ranks.get(name, 0), name))
            if current == better[0]:
                continue
            links[part_id] = better[0]
            owner[part_id] = owner[better[0]]
            progressed = True
        if not progressed:
            break
    for part_id in branches:
        if part_id not in owner and part_id not in strings:
            # A branch sharing a net with nothing at all, chain or branch.
            here = nets[part_id]
            if here:
                strings[part_id] = ",".join(sorted(here))
    return owner, links, strings


def _branch_slot(
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    binding: GrammarResult,
    part_id: str,
    role: str,
    owner: str,
    axis: str,
    ranks: Mapping[str, int],
) -> _Slot | None:
    """One branch's lane: which pin is on the line, where the offset runs, which way."""
    nets = _part_nets(circuit_spec, part_id)
    owner_nets = set(_part_nets(circuit_spec, owner).values())
    shared = _shared_nets(circuit_spec, nets, owner_nets)
    if not shared:
        return None
    shared_net = shared[0]
    others = sorted(net for net in set(nets.values()) if net != shared_net)
    other_net = others[0] if others else ""
    pins_here = sorted(pin for pin, net in nets.items() if net == shared_net)
    pins_there = sorted(pin for pin, net in nets.items() if net == other_net)
    basis, offset_axis, sign, from_order = _branch_basis(
        circuit_spec, presentation_spec, binding, part_id, role, owner, shared_net,
        axis, ranks,
    )
    return _Slot(
        part_id=part_id, role=role, kind="branch", axis=axis,
        rank=ranks.get(part_id, ranks.get(owner, 0)),
        owner=owner, shared_net=shared_net, other_net=other_net,
        pin_shared=pins_here[0] if pins_here else "",
        pin_other=pins_there[0] if pins_there else "",
        basis=basis, sign=sign, offset_axis=offset_axis, sign_from_order=from_order,
    )


def _branch_lane_groups(
    binding: GrammarResult, slots: Mapping[str, _Slot]
) -> dict[str, tuple[str, str, list[str]]]:
    """Groups of parts the grammar asked to share a line, and the axis each runs on.

    A `same-row` / `same-column` the grammar states **between two branches** is
    a statement about the page that nothing used to consume: each branch was
    placed from its own owner's pin, so two of them the grammar had put on one
    row came out wherever their two owners' pins happened to fall. The flyback's
    feedback chain is exactly this (裁决 e): a divider arm, the error amplifier
    and the optocoupler are all in one island, and the grammar asks for one row.

    A group is a **connected component** of the same-line relation, and the axis
    is the line's own coordinate: a `same-row` group is aligned by its *y*, a
    `same-column` group by its *x*. Three kinds of member are allowed, and the
    distinction is the conservative one:

    * **branch–branch** (the flyback's divider arms and error amplifier) — both
      are placed from their own owner, and the pass puts them on one line;
    * **chain–branch** (the flyback's optocoupler, which 113 named in
      :data:`CHAIN_ROLES` so the secondary would have an anchor) — the chain part
      keeps its origin, because the chain is the page's spine and moving it would
      move every other relation with it; only the branch is moved, onto the
      chain member's line. So the pass can satisfy a `same-row` the grammar
      stated between the secondary's rectifier and the optocoupler;
    * a part asked for **two different lines** (a `same-row` *and* a
      `same-column`) has no single lane, so it is left out of every group and the
      relation checker reports it by name — a pass that guessed which line meant
      would hide the contradiction.

    Chain-to-chain `same-row` / `same-column` is **not** handled here: the chain
    is already laid on its own axis, and a same-line pair of two chain parts
    would be a statement about the chain's own pitch, which is a different
    question than the one this function answers.
    """
    same: dict[str, str] = {}
    members: dict[str, str] = {}
    for item in binding.constraints:
        if item.kind not in (SAME_ROW, SAME_COLUMN):
            continue
        here, there = item.subject, item.object
        if here not in slots or there not in slots:
            continue
        if slots[here].kind == "free" or slots[there].kind == "free":
            continue
        if slots[here].kind == "chain" and slots[there].kind == "chain":
            continue
        axis = "y" if item.kind == SAME_ROW else "x"
        for part_id in (here, there):
            if same.setdefault(part_id, axis) != axis:
                same[part_id] = ""
                members.pop(part_id, None)
    # connected components over the surviving same-line pairs
    parent: dict[str, str] = {part_id: part_id for part_id in same}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for item in binding.constraints:
        if item.kind not in (SAME_ROW, SAME_COLUMN):
            continue
        here, there = item.subject, item.object
        if here not in same or there not in same:
            continue
        if not same[here] or not same[there]:
            continue
        a, b = find(here), find(there)
        if a != b:
            parent[min(a, b)] = min(a, b)
            parent[max(a, b)] = min(a, b)
    groups: dict[str, list[str]] = {}
    for part_id in sorted(same):
        if not same[part_id]:
            continue
        groups.setdefault(find(part_id), []).append(part_id)
    out: dict[str, tuple[str, str, list[str]]] = {}
    for root, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        label = f"{'row' if same[group[0]] == 'y' else 'column'}:" + "+".join(group)
        for part_id in group:
            out[part_id] = (same[part_id], label, group)
    return out


def _branch_lane_edges(
    circuit_spec: CircuitSpec,
    binding: GrammarResult,
    lanes: Mapping[str, tuple[str, str, list[str]]],
) -> dict[str, list[tuple[str, str, str]]]:
    """``lane label -> that group's same-line edges``, as ``(a, b, measured net)``.

    The net is resolved here exactly the way :func:`_points_for_relation`
    resolves it — the first net the pair has in common, and ``""`` when they
    share none, which is the case the relation is measured between **origins** on.
    Carrying it with the edge is what lets the placement level a group whose
    members are measured on *different pins* of different pairs: the flyback's
    U4 is asked to share a row with the divider through its ``FB_SENSE`` pad and
    with the optocoupler through its ``LED_K`` pad, and those two pads are 40
    units apart in the symbol, so "the row" is not one number the group can all
    be snapped to. It is a set of edges, and each is levelled on its own net.
    """
    out: dict[str, list[tuple[str, str, str]]] = {}
    for item in binding.constraints:
        if item.kind not in (SAME_ROW, SAME_COLUMN):
            continue
        here, there = item.subject, item.object
        lane_here = lanes.get(here)
        lane_there = lanes.get(there)
        if lane_here is None or lane_there is None:
            continue
        if lane_here[1] != lane_there[1]:
            continue
        common = sorted(
            set(_part_nets(circuit_spec, here).values())
            & set(_part_nets(circuit_spec, there).values())
        )
        out.setdefault(lane_here[1], []).append(
            (here, there, common[0] if common else "")
        )
    return out


def _shared_nets(
    circuit_spec: CircuitSpec, nets: Mapping[str, str], owner_nets: set[str]
) -> list[str]:
    """Which net a branch shares with its owner — the node it hangs off.

    A branch usually shares exactly one, but a decoupling capacitor's ground is
    shared with *every* branch on the same IC, so the return is not evidence of
    belonging. The rule therefore prefers a shared net that is not ground: a
    branch hangs off the node it decouples, and only falls back to a shared
    ground when that is all the two parts have in common.
    """
    common = sorted(net for net in set(nets.values()) if net in owner_nets)
    if not common:
        return []
    non_return = [
        net for net in common
        if (circuit_spec.net(net) is None or circuit_spec.net(net).cls != "gnd")
    ]
    return non_return or common


def _branch_basis(
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    binding: GrammarResult,
    part_id: str,
    role: str,
    owner: str,
    shared_net: str,
    axis: str,
    ranks: Mapping[str, int],
) -> tuple[str, str, int, bool]:
    """``(basis, offset axis, sign, sign came from an order kind)``.

    Read in the order the grammar states things, strongest first: a same-line kind
    with the owner (the branch's shared pin lands on that line — the RC shunt's
    own statement, and the one 053 sec.3 draws as "the trunk is one row"); the tap
    kind (the stub's axis); the **side** the grammar reads for this branch's role
    (060 sec.1: an LDO's input capacitor belongs on the side the input is read on,
    wherever the presentation put it — the measured AMS1117 leaves VIN *and* VOUT
    down one side, which is what stacked an LDO's two capacitors on one); and last
    the owner's own pin direction, resolved at placement time.

    The owner's pose is what makes a stated side reachable: a pin that escapes
    *away* from its branch's side is refused (`_stated_sides_are_reachable`), so a
    side the symbol's pins leave perpendicular to is honoured by a bend at the pin
    tip rather than by a wire doubling back through the body.

    The sign only comes from the rank order when an order kind says which end of
    the chain the branch belongs at. Without one, the rank of a part nothing
    orders is arbitrary, and :func:`_place` resolves the direction from the
    geometry instead: beyond the owner's shared pin, away from its other end.
    """
    sign = 1 if ranks.get(part_id, 0) >= ranks.get(owner, 0) else -1
    ordered = any(
        item.kind in (ABOVE, BELOW, LEFT_OF, RIGHT_OF, ADJACENT)
        and {part_id, owner} == {item.subject, item.object}
        for item in binding.constraints
    )
    for item in binding.constraints:
        if item.kind in (SAME_ROW, SAME_COLUMN) and {part_id, owner} == {
            item.subject, item.object
        }:
            line_axis = "h" if item.kind == SAME_ROW else "v"
            if line_axis == axis:
                return ("line", "x" if line_axis == "h" else "y", sign, ordered)
            return ("across", "x" if axis == "v" else "y", sign, ordered)
    # An **order kind stated between this branch and its owner** says which side
    # of the owner it goes on, and that is stronger evidence than the owner's own
    # pin direction: the flyback's auxiliary reservoir is a capacitor whose pad
    # leaves sideways, so reading the pin put it *above* the aux rectifier, while
    # the grammar's own `below(C7, D2)` puts it under. The basis becomes
    # ``order`` — an explicit axis and sign, never a guess — and the relation
    # checker then measures the same pair the same way, so the two agree.
    #
    # Only the **owner's own pin** is bypassed. An order kind between a branch and
    # some *other* part is a statement about the page the placement does not own
    # (that is what the relation checker is for), and acting on it here would be
    # the compiler drawing a relation the chain never asked for.
    for item in binding.constraints:
        if item.kind not in (HORIZONTAL_TAP, VERTICAL_TAP):
            continue
        pair = {item.subject, item.object}
        if len(pair) != 2:
            continue
        if all(
            shared_net in set(_part_nets(circuit_spec, name).values()) for name in pair
        ):
            # The tap leaves the junction of these two; the branch hangs on the
            # stub's axis. Which *side* the tap leaves is not stated by the
            # grammar, so it leaves on the positive side of the line.
            return ("tap", "x" if item.kind == HORIZONTAL_TAP else "y", 1, False)
    side = _side_basis(binding, role, part_id, owner)
    if side is not None:
        return side
    return ("pin", "", 1, ordered)


def _side_basis(
    binding: GrammarResult,
    role: str,
    part_id: str,
    owner: str,
) -> tuple[str, str, int, bool] | None:
    """The ``side`` basis for this branch, when its role has a side to read.

    The role must name a `sidePreferences` entry (:data:`SIDE_ROLES`): an EN/NR
    branch or a tap branch has no side that speaks about it, so nothing moves
    them off the pin they serve.

    The axis and sign come from the `left-of`/`right-of`/`above`/`below` kind the
    grammar paired this branch with, read through `grammar/base.py`'s own
    definitions ("left-of — subject on the power side when that side is the left
    one") and through which end of the pair the branch is. That kind is the
    presentation's `sidePreferences` entry for the role — the stated one, or
    053 sec.3's default reading order ("in 左 core 中 out 右") when the document
    states none, which is what the grammar's `_side_kind(side, default)` resolves.
    """
    if not SIDE_ROLES.get(role):
        return None
    for item in binding.constraints:
        if item.kind not in (ABOVE, BELOW, LEFT_OF, RIGHT_OF):
            continue
        if {part_id, owner} != {item.subject, item.object}:
            continue
        own = item.subject == part_id
        if item.kind in (LEFT_OF, RIGHT_OF):
            left = item.kind == LEFT_OF
            return ("side", "x", -1 if left == own else 1, True)
        above = item.kind == ABOVE
        return ("side", "y", 1 if above == own else -1, True)
    return None


def _branch_body_direction(ctx: _Context, slot: _Slot) -> tuple[float, float]:
    """Which way a branch's body leaves the line: toward its other net's side.

    The side is the presentation's own `sidePreferences` entry for the class of
    the net the branch does not share (so ground on top hangs the branches
    upward without this module knowing anything about grounds), and a net with no
    preference falls back to the ground side — the book's default, and named here
    rather than assumed.
    """
    net = ctx.circuit.net(slot.other_net)
    role = net.cls if net is not None and net.cls in ("power", "gnd") else "gnd"
    return _side_vector(ctx.presentation, role)


# ------------------------------------------------------- poses for the parts


def _pin_of_token(profile: SymbolProfile, token: str) -> SymbolPin | None:
    """The profile pin a spec token names: by number first, then by name.

    The same rule `grammar.base.profile_pin_for` applies, and for the same
    reason: a spec writes ``<partId>.<pin>`` with whatever token the symbol uses.
    """
    if not token:
        return None
    found = profile.pin(token)
    if found is not None:
        return found
    for pin in profile.pins:
        if pin.name == token:
            return pin
    return None


def _posed_tip(pin: SymbolPin, pose: SymbolPose) -> tuple[float, float]:
    """The pin's tip relative to the part's origin, under this pose."""
    return _rounded(transform_point(
        pin.tip[0], pin.tip[1], rotation=pose.rotation, mirror=pose.mirror,
        ox=0.0, oy=0.0,
    ))




def _accepted_poses(
    ctx: _Context, slot: _Slot
) -> tuple[list[SymbolPose], GrammarFailure | None]:
    """The legal poses that put this part's pins where its relations need them.

    This is where "换符号" (053 sec.5 scenario 2) is won: the requirement is
    stated in terms of *nets and directions*, so a symbol whose pins run the
    other way is rotated into the requirement instead of being special-cased.

    * a **chain** part: the pins on the chain's nets lie on one line parallel to
      the chain axis, in the order the chain names (the earlier net nearer the
      power end);
    * a **branch** part: its two pins lie along the body direction, with the
      shared pin at the end nearer the line.

    Every pose that satisfies the requirement is kept, de-duplicated by the
    geometry it produces (a symmetric two-pin part has four legal poses and one
    geometry), so the ladder has something to vary and nothing pointless to try.
    """
    profile = ctx.profile(slot.part_id)
    accepted: list[SymbolPose] = []
    seen: set[tuple] = set()
    for pose in profile.poses:
        if not _pose_satisfies(ctx, slot, profile, pose):
            continue
        key = tuple(
            (pin.number, _posed_tip(pin, pose)) for pin in profile.pins
        )
        if key in seen:
            continue
        seen.add(key)
        accepted.append(pose)
    if accepted:
        return accepted, None
    return [], GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject=slot.part_id,
        detail=(
            f"no legal pose of {profile.symbol_ref!r} puts {slot.part_id}'s pins "
            f"where the drawing needs them ("
            + ("chain axis / pin order" if slot.kind == "chain" else "body direction")
            + "); the symbol's declared poses are "
            + ", ".join(pose.label() for pose in profile.poses)
        ),
        action=(
            "widen SymbolProfile.poses for this symbol, or choose a compatible "
            "symbol whose pins face the required direction — never renumber pins "
            "to fit the layout (053 sec.2)"
        ),
    )


def _pose_satisfies(
    ctx: _Context, slot: _Slot, profile: SymbolProfile, pose: SymbolPose
) -> bool:
    """Does this pose put the pins where the relations need them?"""
    if slot.kind == "chain":
        if not _stated_sides_are_reachable(ctx, slot.part_id, pose):
            return False
        order = _chain_pin_pairs(ctx, slot.part_id)
        if order is None:
            return True
        for power_token, ground_token in order:
            power_pin = _pin_of_token(profile, power_token)
            ground_pin = _pin_of_token(profile, ground_token)
            if power_pin is None or ground_pin is None:
                return True
            tips = (_posed_tip(power_pin, pose), _posed_tip(ground_pin, pose))
            if not _on_one_line(tips, ctx.progress):
                continue
            if _dot(tips[0], ctx.progress) < _dot(tips[1], ctx.progress):
                return True
        return False
    if not slot.pin_shared or not slot.pin_other:
        return True
    # A part with **more than two pins** is not a two-terminal element: the rule
    # below ("the two pins lie along the body direction") is a statement about a
    # resistor or a capacitor, where the two pads *are* the part. A three-pin
    # device's pads are on three sides, and no rotation makes an arbitrary two of
    # them collinear with the body — the flyback's TL431 hangs its compensation
    # off the optocoupler's cathode and its `REF` pad is a third direction. So the
    # body-direction rule is applied to the two-terminal parts it was written for
    # (a pin count of two, or a profile that declared no body at all), and the
    # other parts are left to the relations, which are what place them.
    if len(profile.pins) > 2:
        return True
    body = ctx.body_dirs.get(slot.part_id)
    if body is None:
        return True
    shared = _pin_of_token(profile, slot.pin_shared)
    other = _pin_of_token(profile, slot.pin_other)
    if shared is None or other is None:
        return True
    tips = (_posed_tip(shared, pose), _posed_tip(other, pose))
    if not _on_one_line(tips, body):
        return False
    return _dot(tips[0], body) < _dot(tips[1], body)


def _branch_side_direction(slot: _Slot) -> tuple[float, float]:
    """The page direction a ``side`` branch's offset runs in (see `_branch_basis`)."""
    if slot.offset_axis == "x":
        return (float(slot.sign), 0.0)
    return (0.0, float(slot.sign))


def _stated_sides_are_reachable(
    ctx: _Context, owner_id: str, pose: SymbolPose
) -> bool:
    """Can every branch that names a side leave its own pin without doubling back?

    060 sec.1: a branch goes on the side the grammar states for it, and the pin it
    hangs off must not escape the *other* way — a wire from a pin that points away
    from its own branch has to double back through the body the pin belongs to.
    The owner's pose is refused instead of the drawing being bent, which keeps
    053 sec.5's refusals honest: a symbol whose supply pins all leave one side
    still cannot honour "input left, output right" (no legal pose — the shape
    054 C3 measured), while a side the pins leave *perpendicular* to is fine (the
    measured AMS1117's output below its own left-hand VOUT pin).
    """
    for other in ctx.slots.values():
        if (
            other.kind != "branch"
            or other.owner != owner_id
            or other.basis != "side"
        ):
            continue
        direction = _pin_direction(
            ctx, owner_id, _shared_token(ctx, other), {owner_id: pose},
        )
        if direction is None:
            continue
        want = _branch_side_direction(other)
        if direction[0] * want[0] + direction[1] * want[1] < 0.0:
            return False
    return True


def _chain_pin_pairs(
    ctx: _Context, part_id: str
) -> list[tuple[str, str]] | None:
    """``(pin on the earlier net, pin on the later net)`` pairs, every combination.

    Only the nets the `direct-wire` obligations place *on the chain* count. A pin
    on a net the chain does not name (the LDO's ground, the NR pin) is left
    unconstrained here: where it goes is the symbol's own business, and forcing
    it onto the axis would be this module inventing an arrangement.

    More than one pair is the normal case for a symbol that carries a role on
    several pins (060 sec.2: the measured AMS1117's VOUT is on both sides of the
    body). The pose is accepted when **any** of the pairs lies on the chain in
    order — the pins are one node inside the symbol, so the drawing may run the
    chain through whichever of them the symbol's own geometry allows and wire the
    rest as the same node. Without this the chain's pin was chosen by pin id
    alone, and the pair it picked first (VIN with the *far* VOUT) is not collinear
    in any pose: a drawing with both output pins connected was refused as
    "no legal pose" (055 G1's shape, measured again in 060 sec.2).
    """
    nets = _chain_nets(ctx, part_id)
    ranked = sorted(
        ((ctx.chain_net_rank[net], pin) for pin, net in nets.items()
         if net in ctx.chain_net_rank),
        key=lambda item: (item[0], item[1]),
    )
    if len(ranked) < 2 or ranked[0][0] == ranked[-1][0]:
        return None
    earlier = [pin for rank, pin in ranked if rank == ranked[0][0]]
    later = [pin for rank, pin in ranked if rank == ranked[-1][0]]
    return [(power, ground) for power in earlier for ground in later]


def _chain_nets(ctx: _Context, part_id: str) -> dict[str, str]:
    """``spec pin token -> net`` for one part, a role's other pins included.

    The same rule the net's own points get in :func:`_sibling_members` (060
    sec.2), applied where the *chain* reads the symbol: a role carried on several
    pins is one node, so the chain may run through whichever of them the symbol's
    geometry allows. Reading only the spec's own members here is what kept a
    circuit that wires the far VOUT pin from ever finding a legal pose.
    """
    nets = dict(_part_nets(ctx.circuit, part_id))
    part = ctx.circuit.part(part_id)
    profile = ctx.book.get(part.symbol_ref) if part is not None else None
    if profile is None:
        return nets
    nc = nc_pins_of(ctx.circuit, part_id)
    for token, net_id in sorted(nets.items()):
        for pin in role_siblings(profile, token):
            spelling = pin.number or pin.name
            if not spelling or spelling in nc:
                continue
            here = nets.get(spelling, nets.get(pin.name, ""))
            if here and here != net_id:
                continue
            nets.setdefault(spelling, net_id)
    return nets


def _on_one_line(
    tips: Sequence[tuple[float, float]], direction: tuple[float, float]
) -> bool:
    """Are both points on one line parallel to `direction` (within half a lattice)?"""
    lateral = (-direction[1], direction[0])
    return abs(_dot(tips[0], lateral) - _dot(tips[1], lateral)) <= GRID / 2.0


def _dot(point: tuple[float, float], direction: tuple[float, float]) -> float:
    return point[0] * direction[0] + point[1] * direction[1]


def _lock_pose_failures(ctx: _Context) -> list[GrammarFailure]:
    """A lock whose rotation the symbol cannot be drawn in is reported, not bent.

    053 sec.5 scenario 12: the engineer's decision is the one input the compiler
    may not quietly ignore, and a rotation the symbol cannot be drawn in is a
    conflict between the lock and the library — `presentation-poor`, because the
    intent is what has to change, with both repairs named.

    **A lock names a rotation, and only a rotation.** :class:`UserLock` carries
    no mirror, so the rotation counts when the symbol declares it *either* way
    round: the mirrored-only symbol is a pose the compiler can draw the lock in,
    and :func:`_locked_pose` picks it (the unmirrored pose when there is one).
    The old test asked only ``allows(rotation, False)`` and then printed the
    symbol's own pose list, which contains the mirrored pose it had just called
    impossible — "locks the part at rotation 90°, which 'R0402' does not allow
    (its poses are 0, 90+mirror)" contradicted itself on one line. What is left
    here is the honest refusal: no pose of that rotation exists at all.
    """
    out: list[GrammarFailure] = []
    for lock in ctx.presentation.user_locks:
        profile = ctx.book.get(_symbol_ref(ctx, lock.part_id))
        if profile is None:
            continue
        if (
            profile.allows(lock.rotation, False)
            or profile.allows(lock.rotation, True)
        ):
            continue
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=lock.part_id,
            detail=(
                f"{LOCK_PREFIX}[{lock.part_id}] locks the part at rotation "
                f"{lock.rotation:g}°, which {profile.symbol_ref!r} does not allow "
                "in either mirroring (its poses are "
                + ", ".join(pose.label() for pose in profile.poses)
                + ")"
            ),
            action=(
                f"relax {LOCK_PREFIX}[{lock.part_id}].rotation to one of the "
                "symbol's poses, or use a symbol that allows the locked "
                "orientation — the lock is honoured exactly or reported, never "
                "snapped (a lock names a rotation; the mirroring is this "
                "compiler's to choose)"
            ),
        ))
    return out


def _symbol_ref(ctx: _Context, part_id: str) -> str:
    part = ctx.circuit.part(part_id)
    return part.symbol_ref if part is not None else ""


# ------------------------------------------------ stage 3: geometric layout


@dataclass
class _Placement:
    """Where each part's origin is, and the pose it is drawn in."""

    origins: dict[str, tuple[float, float]]
    poses: dict[str, SymbolPose]
    residue: tuple[float, float] = (0.0, 0.0)


def _part_box(
    profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float] = (0.0, 0.0)
) -> Box:
    """The box a part occupies: its drawn extent and every pin tip.

    Both halves matter and neither is optional. The body box is what a wire may
    not cross and what text may not land on; the pin tips are where the wires
    arrive. A profile with no body still has tips, and a profile with no tips
    would not have been accepted into the library.
    """
    xs: list[float] = []
    ys: list[float] = []
    if profile.body is not None:
        box = _body_box(profile, pose, origin)
        xs.extend([box[0], box[2]])
        ys.extend([box[1], box[3]])
    for pin in profile.pins:
        point = _posed(pin.tip, pose, origin)
        xs.append(point[0])
        ys.append(point[1])
    if not xs:
        return (origin[0], origin[1], origin[0], origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


#: How thick a pin's drawn line reserves room against a *neighbouring* text
#: (099b). A pin is a stroke, not a rectangle, and one unit is the thinnest
#: extent this compiler's lattice names (:data:`GRID` is five).
PIN_TEXT_WALL = 1.0


def _text_walls(
    profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float]
) -> list[Box]:
    """What a *neighbouring* text must avoid of this part (099b).

    Its drawn body, plus each pin as the segment that pin is drawn as — never the
    box around them: :func:`_part_box` bounds the pin *tips*, and the corners of
    that box are not drawn anywhere. Measured on the 099 CH340 sample: 1.5 units
    of such a corner decided which side the core's own value went to, which in
    turn pushed the core's four pin labels onto the symbol, which the readability
    contract (rightly) refused.

    A pin whose drawn length the profile does not state is an extent nobody
    measured, so the **whole part box** stands in for it (052 sec.4: an unstated
    extent is not a measured zero) — a library that does not say how long its
    pins are keeps the older, stricter reading, box and all.
    """
    body = _body_box(profile, pose, origin)
    walls: list[Box] = [body] if body is not None else []
    half = PIN_TEXT_WALL / 2.0
    for pin in profile.pins:
        if pin.length is None:
            return [_part_box(profile, pose, origin)]
        local = {
            "left": (-1.0, 0.0), "right": (1.0, 0.0),
            "up": (0.0, 1.0), "down": (0.0, -1.0),
        }.get(pin.direction)
        if local is None:
            # No outward direction (a zero-length or interior pin) draws nothing
            # outside the body, so there is nothing to reserve for.
            continue
        inner = (pin.tip[0] - local[0] * pin.length,
                 pin.tip[1] - local[1] * pin.length)
        here = _posed(pin.tip, pose, origin)
        there = _posed(inner, pose, origin)
        walls.append((
            min(here[0], there[0]) - half, min(here[1], there[1]) - half,
            max(here[0], there[0]) + half, max(here[1], there[1]) + half,
        ))
    return walls


def _pin_walls(
    profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float]
) -> list[Box]:
    """Each pin's drawn lead as a thin box: the obstacle a wire may not run along.

    The lead is the segment from the tip that pin draws *inward*, and
    :data:`PIN_TEXT_WALL` is the same thickness `_text_walls` reserves against a
    neighbouring text — a pin is a stroke, not a rectangle. A wire arriving at the
    tip from outside, or perpendicular to the lead, only touches this box's end;
    one that reaches the tip from inside, or doubles back over the lead, crosses
    it and is refused. That is exactly `readability`'s `wire-on-pin-line`, and the
    two have to agree: a route this search calls clear must be clear to the layer
    that grades it.

    A pin whose drawn length the profile does not state reserves nothing: an
    unstated extent is not a measured one (052 sec.4), and the whole-part box is
    already in the obstacles.
    """
    inward = {
        "left": (1.0, 0.0), "right": (-1.0, 0.0),
        "up": (0.0, -1.0), "down": (0.0, 1.0),
    }
    half = PIN_TEXT_WALL / 2.0
    out: list[Box] = []
    for pin in profile.pins:
        if pin.length is None or pin.direction not in inward:
            continue
        dx, dy = inward[pin.direction]
        tip = _posed(pin.tip, pose, origin)
        inner = _posed(
            (pin.tip[0] + dx * pin.length, pin.tip[1] + dy * pin.length), pose, origin
        )
        # The box is the lead from :data:`PIN_LINE_OVERLAP` inward: thick across,
        # and **not a hair past the tip**. Two things follow, and both are
        # measured rather than assumed. A wire that arrives at the tip from
        # outside runs along the lead's own axis, so any overshoot past the tip
        # refuses it; and a wall that *starts* at the tip covers the lattice node
        # every wire has to arrive at, which cost the whole HVDC trunk
        # ("its pins could not be joined inside the searched corridor"). The
        # landing the tip keeps is exactly the length `readability`'s
        # `wire-on-pin-line` tolerates, so the two agree by construction.
        start = (
            tip[0] + dx * PIN_LINE_OVERLAP, tip[1] + dy * PIN_LINE_OVERLAP,
        )
        if (inner[0] - start[0]) * dx + (inner[1] - start[1]) * dy <= 0:
            continue  # a lead shorter than the landing reserves nothing
        across = (abs(dy), abs(dx))
        x0, x1 = sorted((start[0], inner[0]))
        y0, y1 = sorted((start[1], inner[1]))
        out.append((
            x0 - across[0] * half, y0 - across[1] * half,
            x1 + across[0] * half, y1 + across[1] * half,
        ))
    return out


def _body_box(
    profile: SymbolProfile, pose: SymbolPose, origin: tuple[float, float]
) -> Box | None:
    """The box a symbol's **drawn body** occupies, transformed and re-bounded.

    Exactly what `readability`'s `wire-through-body` constraint tests: a wire may
    only reach a part through that part's own pin, and a pin tip is outside this
    box by construction. The routing obstacles use *this* box rather than
    :func:`_part_box`, because a wire leaving a pin tip has to travel between the
    tip and the body it belongs to — bounding the tips as obstacles would forbid
    every part's own escape.

    147: the fold is :func:`~boardwise.core.symbolprofile.pose_box` — the same one
    `readability` and `pagecompiler` call, so the obstacle the router avoids and
    the box the checker tests cannot be two rectangles.
    """
    return pose_box(
        profile.body,
        rotation=pose.rotation, mirror=pose.mirror, ox=origin[0], oy=origin[1],
    )


def _role_spans_body(ctx: _Context, part_id: str) -> bool:
    """Does any one role of this part sit on pads the body separates? (069 sec.11)

    The shape 岳 drew: his AMS1117 carries VOUT twice, once down each side, and the
    drawing that reads right for it hangs the output capacitor off the far pad 15–25
    units down rather than at the spacing ladder's first rung. A symbol whose pads all
    leave one side has no such pair and keeps the ordinary lane.
    """
    profile = ctx.profile(part_id)
    if profile.body is None:
        return False
    box = profile.body
    centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    by_name: dict[str, list[tuple[float, float]]] = {}
    for pin in profile.pins:
        name = pin.name or pin.number
        if not name:
            continue
        by_name.setdefault(name, []).append(
            (pin.tip[0] - centre[0], pin.tip[1] - centre[1])
        )
    for offsets in by_name.values():
        if len(offsets) < 2:
            continue
        for index, first in enumerate(offsets):
            for second in offsets[index + 1:]:
                if _dot(first, second) < 0.0:
                    return True
    return False


def _posed(
    local: tuple[float, float], pose: SymbolPose, origin: tuple[float, float]
) -> tuple[float, float]:
    """A symbol-local point in page coordinates, through the part's pose.

    One call site for the whole compiler, and it is the *same* transform the
    readability checker derives the netlist with (`core.geometry.transform_point`
    — mirror, then CCW rotation, then the origin): two transforms would be two
    rulers for the same drawing.
    """
    return _rounded(transform_point(
        local[0], local[1], rotation=pose.rotation, mirror=pose.mirror,
        ox=origin[0], oy=origin[1],
    ))


def _extent(box: Box, direction: tuple[float, float]) -> tuple[float, float]:
    """``(how far the box reaches along +direction, along -direction)``.

    The two halves of a part's span, measured from the *origin* the pins and
    corners were placed from — which is how the chain pitch is computed without a
    single magic number: the room two neighbours need is what each one actually
    draws.
    """
    corners = ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))
    along = max(_dot(corner, direction) for corner in corners)
    against = max(-_dot(corner, direction) for corner in corners)
    return (along, against)


def _snap(value: float, grid: float, residue: float) -> float:
    """`value` on the compilation lattice (which may be offset by a lock)."""
    return round((value - residue) / grid) * grid + residue


def _snap_inside(value: float, grid: float, residue: float, inside: int) -> float:
    """`value` on the lattice, rounded **towards the page's inside** (096).

    ``inside`` is the direction a larger displacement moves the drawing in:
    ``+1`` for a displacement anchored on the drawing's left or bottom edge
    (bigger moves it right / up), ``-1`` for its right or top edge. That is the
    same rule said the other way round — the left and bottom edges round with
    ``ceil``, the right and top with ``floor`` — because "towards the inside" is
    a property of the edge the anchor was computed from, not of the axis.

    The distinction from :func:`_snap` is the whole point here: the rounding is
    this compiler's convenience and the page edge is the author's constraint, so
    a displacement computed to put the drawing just inside the margin must not
    be rounded *out* of it. Rounding to the nearest lattice point can land half
    a step outside — the defect 096 fixes, measured as a 岳 sample that the
    compiler fitted to a 1170x825 sheet and then refused as too small.
    """
    steps = (value - residue) / grid
    return (math.ceil(steps) if inside > 0 else math.floor(steps)) * grid + residue




def _lattice_residue(
    points: Sequence[tuple[float, float]], grid: float
) -> tuple[float, float] | None:
    """The lattice offset every pin tip shares, or ``None`` when they disagree.

    The points handed in are each part's pin tips under its own pose with the
    origin at ``(0, 0)`` (:func:`_place` builds them that way), so this measures
    the **symbols' own pin pitches** modulo the grid. It runs before any lock is
    applied and no lock coordinate enters it: the residue decides which offset
    the *unlocked* origins are snapped onto, and a locked part keeps its own
    locked coordinates on top of that, so a lock never has to share the residue
    and can never be what this refusal is about.

    The docstring used to claim the reverse — "the compiler then compiles on the
    lattice the locks put the tips on", "two locks on different residues cannot
    both be honoured … and that is reported" — and :func:`_place` repeated it in
    the refusal text, which named locks a spec need not contain at all (143's
    witness: a spec with `userLocks: []`, refused by "the locked positions put
    tips on different residues"). The measurement is right and the words are now
    the measurement's own. A lock-residue check is *not* implemented here and is
    not claimed: this refusal is about the symbols.
    """
    residue: list[float | None] = [None, None]
    for point in points:
        for axis in (0, 1):
            value = point[axis] % grid
            if residue[axis] is None:
                residue[axis] = value
                continue
            base = residue[axis]
            assert base is not None
            if any(_close(value + shift, base) for shift in (-grid, 0.0, grid)):
                continue
            return None
    return (residue[0] or 0.0, residue[1] or 0.0)


def _locked_pose(
    ctx: _Context, part_id: str, accepted: Sequence[SymbolPose]
) -> SymbolPose | None:
    """The pose a lock pins this part to, or ``None`` when it pins none.

    A lock names a **rotation** (there is no mirror field to name, and
    :func:`_lock_pose_failures` refuses only a rotation the symbol cannot be
    drawn in *at all*), so the pose returned is of that rotation: the
    **unmirrored** one when the accepted set has it, otherwise the mirrored one,
    because the mirroring is an engineering decision the lock did not state and
    the compiler is free to reach the rotation the way the symbol's geometry
    allows.

    When **no** accepted pose has that rotation the lock is still obeyed: the
    symbol's own declared pose of that rotation is used, and the relation the
    placement then breaks is reported by :func:`_relation_failures` — the
    `presentation-poor` conflict between the lock and the grammar, naming the
    lock and the relation (053 sec.5 scenario 12: honoured exactly or reported,
    never silently snapped).

    That second half is what the compiler was missing. The pose used to be
    ``accepted[min(variant.pose_index, len-1)]`` — a single global index, with
    the lock's rotation checked by :func:`_lock_pose_failures` and then never
    read. A lock whose rotation sat past index 1 of its own accepted set (the
    real flyback's ``C6``, whose ``90`` is index 2) could therefore never be
    drawn: every variant drew the pose at the base rungs, the gate refused each
    one for violating the lock, and the input was reported as a *compiler-side
    geometry problem* — while the pose the lock asked for sat in the compiler's
    own accepted set the whole time. The 121c locks passed only because they
    were copied off a plan whose poses were ``accepted[0]`` by construction.
    """
    lock = ctx.locked(part_id)
    if lock is None:
        return None
    for source in (accepted, ctx.profile(part_id).poses):
        unmirrored = [pose for pose in source if not pose.mirror]
        mirrored = [pose for pose in source if pose.mirror]
        for pose in (*unmirrored, *mirrored):
            if pose.rotation == lock.rotation:
                return pose
    return None


def _place(
    ctx: _Context, variant: _Variant
) -> tuple[_Placement | None, GrammarFailure | None]:
    """Ranks and lanes -> origins, through the real symbols.

    The chain is laid on one line with a pitch per neighbouring pair taken from
    the two parts' own extents plus a wiring channel, scaled by the ladder rung;
    every branch is placed from the owner's pin it shares a net with; a free part
    (one the grammar bound to nothing) goes on a shelf past the chain so the
    drawing still shows it. Locked parts take their lock exactly — place *and*
    rotation (:func:`_locked_pose`) — and the chain is translated so the unlocked
    parts keep their relations to it.
    """
    poses: dict[str, SymbolPose] = {}
    for part_id, accepted in ctx.accepted.items():
        # `_prepare` records a refusal for every slot whose accepted set is
        # empty and `compile` returns on it, so this is an invariant of the
        # stage rather than a case to handle: say so here instead of indexing
        # `accepted[-1]` (the latent IndexError 143 dug up, one line away from
        # the real defect).
        assert accepted, part_id
        pinned = _locked_pose(ctx, part_id, accepted)
        poses[part_id] = (
            pinned if pinned is not None
            else accepted[min(variant.pose_index, len(accepted) - 1)]
        )
    boxes = {
        part_id: _part_box(ctx.profile(part_id), poses[part_id])
        for part_id in ctx.slots
    }
    lattice_points: list[tuple[float, float]] = []
    for part_id, box in boxes.items():
        profile = ctx.profile(part_id)
        for pin in profile.pins:
            lattice_points.append(_posed(pin.tip, poses[part_id], (0.0, 0.0)))
    residue = _lattice_residue(lattice_points, ctx.budget.grid)
    if residue is None:
        return None, GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject="lattice",
            detail=(
                "the parts' pin tips do not share one compilation lattice of "
                f"{ctx.budget.grid:g} units, so a grid search cannot reach them "
                "all: these symbols' own pin pitches disagree modulo the grid "
                "(measured on each symbol's pins with its origin at (0, 0), so "
                "no lock is part of this measurement)"
            ),
            action=(
                "lower budget.grid to a divisor of the pin-tip coordinates "
                "involved, or use symbols whose pins land on one lattice — the "
                "compiler searches a lattice and moves parts to it, so a pin "
                "that is not on any shared lattice cannot be reached"
            ),
        )

    progress = ctx.progress
    origins: dict[str, tuple[float, float]] = {}
    axial = 0.0
    previous: str | None = None
    for part_id in ctx.chain:
        if previous is not None:
            ahead = _extent(boxes[previous], progress)[0]
            behind = _extent(boxes[part_id], (-progress[0], -progress[1]))[0]
            pitch = ahead + behind + ctx.budget.channel * variant.scale
            axial += _snap(pitch, ctx.budget.grid, 0.0)
        origins[part_id] = (progress[0] * axial, progress[1] * axial)
        previous = part_id

    _park_unordered_chain(ctx, origins, boxes, variant)

    anchor_delta: tuple[float, float] | None = None
    for part_id in ctx.chain:
        lock = ctx.locked(part_id)
        if lock is None:
            continue
        ideal = origins[part_id]
        delta = (lock.x - ideal[0], lock.y - ideal[1])
        if anchor_delta is None:
            anchor_delta = delta
        origins[part_id] = (lock.x, lock.y)
    if anchor_delta is not None:
        for part_id in ctx.chain:
            if ctx.locked(part_id) is not None:
                continue
            origins[part_id] = (
                origins[part_id][0] + anchor_delta[0],
                origins[part_id][1] + anchor_delta[1],
            )

    counts: dict[tuple[str, tuple[float, float]], int] = {}
    branch_ids = _branch_order(ctx)
    for part_id in branch_ids:
        lock = ctx.locked(part_id)
        if lock is not None:
            origins[part_id] = (lock.x, lock.y)
            continue
        slot = ctx.slots[part_id]
        owner = slot.owner
        direction = _branch_offset_direction(ctx, slot, poses, origins)
        key = (owner, direction)
        index = counts.get(key, 0)
        counts[key] = index + 1
        anchor = _branch_anchor(ctx, slot, poses, origins)
        clearance = _extent(boxes[part_id], (-direction[0], -direction[1]))[0] + GAP
        step = ctx.budget.lane * variant.scale
        lane = step
        floor = clearance
        if slot.role == "out_caps" and _role_spans_body(ctx, owner):
            # 069 sec.11: 岳's own decoupling spacing — the capacitor hangs 15–25 off
            # the pad it decouples (his P22), not at the ladder's first rung. An
            # absolute number, deliberately outside the ladder: a rung would stretch
            # a hand-measured 20 into 30, and the band is what makes it read right.
            # The floor only keeps the branch clear of the anchor; the capacitor's own
            # pin length is what then reaches the pad, so "box extent + GAP" — which
            # measures the box, not the pin — must not push it back out.
            lane = DECAP_LANE
            floor = GAP
        distance = max(lane + step * index, floor)
        root = (
            anchor[0] + direction[0] * _snap(distance, ctx.budget.grid, 0.0),
            anchor[1] + direction[1] * _snap(distance, ctx.budget.grid, 0.0),
        )
        shared = _pin_local(ctx, part_id, slot.pin_shared, poses)
        root = _dodge_foreign_pins(
            ctx, part_id, slot, anchor, root, poses, origins,
        )
        if shared is None:
            origins[part_id] = root
        else:
            origins[part_id] = (root[0] - shared[0], root[1] - shared[1])

    _align_branch_lanes(ctx, origins, poses, residue)

    shelf_y = axial if ctx.chain else 0.0
    shelf_x = 0.0
    for part_id in sorted(ctx.slots):
        if ctx.slots[part_id].kind != "free" or part_id in origins:
            continue
        lock = ctx.locked(part_id)
        if lock is not None:
            origins[part_id] = (lock.x, lock.y)
            continue
        width = boxes[part_id][2] - boxes[part_id][0]
        origins[part_id] = (
            shelf_x - boxes[part_id][0],
            shelf_y - boxes[part_id][3] - ctx.budget.channel * variant.scale,
        )
        shelf_x += width + ctx.budget.channel

    for part_id in sorted(origins):
        lock = ctx.locked(part_id)
        if lock is not None:
            continue
        origins[part_id] = (
            _snap(origins[part_id][0], ctx.budget.grid, residue[0]),
            _snap(origins[part_id][1], ctx.budget.grid, residue[1]),
        )
    # 116: after the lattice snap, so a step this pass takes is already on the
    # same lattice the gate measures and the final snap cannot undo it. Runs
    # before _anchor_to_page so the page anchor is chosen around the honoured
    # orders, not around the ones the pass is about to fix.
    #
    # The baseline is the set the **tightest** rung breaks, measured from the
    # same origins this rung reached before the pass ran. It is computed once
    # and cached on the context, so every rung is filtered by the *same*
    # statement of "what the base layout cannot do" — the pass then consumes a
    # relation the base layout also broke, and leaves the ladder to judge the
    # ones only the wide rungs broke.
    baseline = getattr(ctx, "_order_baseline", None)
    if baseline is None:
        baseline = frozenset(
            (item.kind, item.subject, item.object)
            for item in _bound_orders(ctx, origins, poses, None)
        )
        setattr(ctx, "_order_baseline", baseline)
    _honour_bound_orders(ctx, origins, poses, variant.pose_index, baseline)
    _anchor_to_page(ctx, origins, poses, residue)
    placed = _Placement(origins=origins, poses=poses, residue=residue)
    conflict = _relation_failures(ctx, placed)
    if conflict:
        return None, conflict[0]
    return placed, None


def _anchor_to_page(
    ctx: _Context,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    residue: tuple[float, float],
) -> None:
    """Move the whole drawing to the page's top-left corner, in place.

    The frame question this settles: a keep-out is an absolute box, and a stated
    page is an absolute region, so the drawing has to be *placed* in the page's
    frame rather than translated into it afterwards. Anchoring here means the
    local frame and the final plan are the same frame, and a keep-out means what
    its coordinates say — for the text placement, for the routing and for the
    readability check alike.

    Both displacements are snapped **towards the page's inside** (096): the
    margin is the author's constraint and the lattice is this compiler's
    convenience, so the rounding may not be the thing that puts the drawing
    outside. Rounding to the nearer lattice point can move it outwards by up to
    half a step, which is what made the margin the anchor had just left and the
    margin `_overflow` measures differ — measured on a 岳 sample stated on a
    1170x825 sheet, the left edge landed 5 units left of the margin and the page
    was refused as too small while the same circuit without a stated page drew
    fine. `_overflow`'s 1e-6 is not loosened to hide that: the edge is the edge.

    The rounding was one of two contributions, and 096 found it was covering the
    smaller one: the allowance above is an estimate (`_annotation_allowance`)
    and it was 4 units short of what that sample actually draws on its left, so
    with the displacement left exact on the lattice the drawing still landed
    outside — the inward snap's 4 units happened to cover the gap, which is luck
    and not a fix. 097 measured the estimate against the finished drawings and
    found the missing term (a part's own reference/value text on the part's left
    side, which the net-name estimate never counted), so the two contributions
    are now *both* right: the allowance no longer needs the snap to cover it, and
    a displacement that lands exactly on the lattice still leaves the drawing
    inside the margin (pinned by `tests/test_097_annotation_allowance.py`).
    `_overflow`'s 1e-6 is not loosened either way: the edge is the edge.

    Skipped when a part is locked, because a lock's coordinates are the
    engineer's: the drawing then stays exactly where the lock put it (053 sec.5
    scenario 12), and the page check reports an overflow if the lock is outside.
    """
    page = ctx.budget.page_box
    if page is None or ctx.presentation.user_locks:
        return
    placed = {
        part_id: _part_box(ctx.profile(part_id), poses[part_id], origin)
        for part_id, origin in origins.items()
    }
    if not placed:
        return
    side, vertical = _annotation_allowance(ctx, placed)
    dx = page[0] + PAGE_MARGIN + side - min(box[0] for box in placed.values())
    dy = page[3] - PAGE_MARGIN - vertical - max(box[3] for box in placed.values())
    # `dx` is anchored on the drawing's left edge and `dy` on its top edge, so a
    # *larger* dx moves the drawing right (inwards) and a *smaller* dy moves it
    # down (inwards) — see :func:`_snap_inside` for the other two edges.
    dx = _snap_inside(dx, ctx.budget.grid, residue[0], inside=1)
    dy = _snap_inside(dy, ctx.budget.grid, residue[1], inside=-1)
    for part_id in origins:
        origins[part_id] = (origins[part_id][0] + dx, origins[part_id][1] + dy)


def _annotation_allowance(
    ctx: _Context, placed: Mapping[str, Box]
) -> tuple[float, float]:
    """``(sideways, vertical)`` room the annotations need beyond the parts.

    The anchor has to leave space for what it is about to draw, and two kinds of
    annotation reach past the outermost part box:

    * a **net's name** — a flag's lead and its glyph extend past the pin a rail
      ends on, and a tap's stub plus the label at its end extend sideways. A
      label's box is ``TEXT_GAP + the name's width`` wide off its anchor and the
      stub is ``budget.stub`` long, which is the first term;
    * a **part's own text** — the reference and the value are put on a *side* of
      the part's box, and when that side is the left one the line reaches
      ``TEXT_GAP + its own width`` past the part's left edge. Relative to the
      drawing's left edge (which is what ``dx`` is anchored on) that is
      ``TEXT_GAP + width - (this part's left - the drawing's left)``, so a wide
      value on the leftmost part is the worst case and the second term. 096
      measured exactly that: the leftmost part's ``SMCJ28CA`` printed on its
      left made the drawing 70 units wide of the parts where the net-name term
      says 66, and the 4-unit gap was what a page was refused over.

    The answer is the **larger** of the two, not their sum: they describe two
    different objects, and each is an upper bound only for its own kind — 097
    measured all four preview families plan by plan (257 plans,
    `evidence/097/bound_sweep.py`), and while the net-name term alone was short
    on 23 of them (all with a text at the left edge) and the text term alone on
    45 (all with a flag there), no plan was short of both. Both are estimates
    still — they are read off the same font metrics the placement prints with,
    and anything the placement then does differently (a text pushed to its
    second side, a flag standing on 069 sec.1's longer reach) is caught by the
    measured overflow check on the finished plan rather than predicted here.

    ``vertical`` keeps its old shape and that is deliberate: ``FLAG_LEAD`` plus
    the glyph is the *ordinary* flag, while the flag ladder is adaptive — a lead
    may go out to :data:`SIBLING_LEAD` (069 sec.1's reaching form) or further
    along the rungs before it fits, so there is no ceiling to state. Measured
    over the same 257 plans, every plan compiled against a stated page needed at
    most 53 vertical units (the estimate is 56); the one plan needing more (68)
    was compiled with no page at all, where the anchor does not run. That half is
    therefore the finish line's own to measure, and it is reported as a leftover
    rather than padded with a number nothing derives.

    ``placed`` is ``part id -> the box that part occupies``
    (:func:`_part_box`, pin tips included); it is the same per-part box the text
    placement uses, so the two cannot measure different drawings.
    """
    glyph = max(
        (
            profile.body[3] - profile.body[1]
            for profile in ctx.book.values()
            if profile.body is not None and not profile.pins
        ),
        default=0.0,
    )
    widest = max((text_width(net.id) for net in ctx.circuit.nets), default=0.0)
    left = min(box[0] for box in placed.values()) if placed else 0.0
    text = max(
        (
            TEXT_GAP + text_width(line) - (box[0] - left)
            for part_id, box in placed.items()
            for _kind, line in _part_lines(ctx, part_id)
        ),
        default=0.0,
    )
    return (
        max(ctx.budget.stub + widest + TEXT_GAP, text),
        FLAG_LEAD + glyph + TEXT_GAP,
    )


def _branch_anchor(
    ctx: _Context,
    slot: _Slot,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float]:
    """The point on the shared net a branch leaves from.

    Two answers, and which one is right follows from the basis:

    * ``tap`` — the branch hangs on the tap *stub*, and the stub leaves the
      junction between the two chain parts that share the net, so the anchor is
      that junction (the midpoint of their pins on the net). Anchoring it on the
      owner's own pin instead would hang the branch beside the upper arm rather
      than off the tap, which is the difference 053 sec.3's "抽点中点" names;
    * everything else — the owner's pin on the shared net, as
      :func:`_shared_token` reads it: one pin when the role has one, and the pin
      across the body from the input branch when the role has several (065
      sec.1). The RC shunt's root then lands on the trunk row exactly as its
      `same-row` says, and the LDO's input capacitor lands on the input rail —
      its output capacitor on the other one.
    """
    if slot.basis == "tap":
        junction = _tap_junction(ctx, slot.shared_net, poses, origins)
        if junction is not None:
            return junction
    anchor = _pin_point(ctx, slot.owner, _shared_token(ctx, slot), poses, origins)
    if anchor is not None:
        return anchor
    return origins.get(slot.owner, (0.0, 0.0))


def _branch_order(ctx: _Context) -> list[str]:
    """The order branches are placed in: an owner before everything it owns.

    A branch hangs off its owner's **pin**, so the owner has to have an origin
    first. When the owner is a chain part that was already true, and the old sort
    by owner id happened to be safe by accident; with the transitive ownership of
    114 a branch's owner can be another branch, so the order is stated instead of
    being stumbled into: a Kahn walk over "is owned by", with the same stable
    tie-break the rest of this module uses (rank, then part id), and a cycle —
    a presentation whose two branches own each other — broken the way
    :func:`_ranks` breaks one: by taking what is left, in order, so the stage
    reports a relation conflict rather than hanging on a contradictory document.
    """
    branches = {
        part_id for part_id, slot in ctx.slots.items() if slot.kind == "branch"
    }
    pending = sorted(
        branches, key=lambda part_id: (ctx.slots[part_id].rank, part_id),
    )
    ordered: list[str] = []
    waiting = {part_id: set() for part_id in branches}
    for part_id in branches:
        owner = ctx.slots[part_id].owner
        if owner in branches:
            waiting[part_id].add(owner)
    remaining = list(pending)
    while remaining:
        ready = [part_id for part_id in remaining if not waiting[part_id]]
        if not ready:
            ready = [remaining[0]]
            remaining.remove(ready[0])
            for part_id in remaining:
                waiting[part_id].discard(ready[0])
            ordered.append(ready[0])
            continue
        for part_id in ready:
            remaining.remove(part_id)
            ordered.append(part_id)
        for part_id in remaining:
            waiting[part_id].difference_update(ready)
    return ordered


def _dodge_foreign_pins(
    ctx: _Context,
    part_id: str,
    slot: _Slot,
    anchor: tuple[float, float],
    root: tuple[float, float],
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float]:
    """Step a branch's root sideways until its run misses every foreign pin.

    A branch is placed by walking straight out of its owner's pin, and the run it
    asks for is the straight line between that pin and where the branch lands. When
    the owner has **another pin on the way**, the run passes over it, and the
    readability contract refuses that outright: a wire vertex on a foreign pin tip
    is a connection the CircuitSpec never declared, and the checker names it
    (``netlist-partition-mismatch``). The flyback's auxiliary rectifier is the case
    — the transformer's two auxiliary pins both leave upward, 20 units apart, and
    the rectifier hung off the first one walked straight across the second.

    The dodge is the smallest one that clears the obstacles: the root moves
    **perpendicular to the run**, away from the owner's own body, by
    :data:`GAP` plus the clearance the obstacle itself needs. It is deliberately
    local — it moves this branch, never the owner (whose origin the chain already
    fixed) and never another branch — so it cannot undo a placement that a
    relation already decided, and the sideways leg it asks for is a leg the router
    then has to find, which it will: the run is no longer collinear with the
    owner's pin, so it is an elbow rather than a pass-through.

    With no foreign pin on the run the root comes back unchanged, which is the case
    for every circuit the five existing grammars compile.

    **The run this measures is the whole of the branch, not the leg to its shared
    pad** (117①). The first version read the leg ``anchor -> root``, which is the
    stretch the *shared* pad travels, and left the branch's **other** pad
    unmeasured — the geometry the flyback's ``C7`` is: its shared pad is dodged to
    ``root = (0, -40)``, its origin becomes ``(0, -60)``, and its ``PGND`` pad then
    lands on ``(0, -80)``, which is exactly where ``T1.A1`` (``AUX``) sits. One
    coordinate, two nets, and the plan has invented the connection. The
    transformer's two auxiliary pins leave upward 20 units apart, so the branch
    lands squarely across the pair.

    It is a **topological** collision, not a tight one, which is why widening
    :data:`GAP` does not touch it (measured 10 → 60, the coincidence never moved)
    and why the fix has to *see* the second pad rather than push harder. So the
    segment measured is ``anchor -> the branch's farthest pin``, with every one of
    this branch's own pins excluded from the obstacle set — it cannot dodge itself.
    """
    leg = (root[0] - anchor[0], root[1] - anchor[1])
    if _close(leg[0], 0.0) and _close(leg[1], 0.0):
        return root
    across = (-leg[1], leg[0])
    span = abs(across[0]) + abs(across[1])
    if span <= 0.0:
        return root
    unit = (across[0] / span, across[1] / span)
    index = 0 if unit[0] != 0.0 else 1
    own = set(_part_nets(ctx.circuit, part_id).values())
    # How far past `root` this branch's own body reaches — the half the first
    # version never read. `root` is where the **shared** pad lands, and the
    # stored origin is `root - shared_local`, so the other pad's tip is at
    # `root + (other_local - shared_local)`: the *difference* of the two local
    # tips, not the other tip itself. Measured on the drawn tips rather than
    # derived from the body box, because the two pads need not be symmetric and
    # the box would over-reserve.
    shared_local = _pin_local(ctx, part_id, slot.pin_shared, poses)
    other_local = _pin_local(ctx, part_id, slot.pin_other, poses)
    if other_local is None:
        other_local = shared_local
    trail = None
    if shared_local is not None and other_local is not None:
        trail = (other_local[0] - shared_local[0],
                 other_local[1] - shared_local[1])
    def _blockers_between(start, end, skip: str) -> int:
        """Foreign pin tips lying on the stretch ``start -> end``.

        ``skip`` is this branch's own id, so the branch never counts itself: the
        pads it is about to place are its own, not obstacles.
        """
        found = 0
        for other in sorted(ctx.slots):
            if other == skip or other not in origins:
                continue
            pins_of = _part_nets(ctx.circuit, other)
            for pin in ctx.profile(other).pins:
                # Per **pin**, not per part: a branch's owner shares this run's net
                # on the one pin the branch hangs off, and its *other* pins sit on
                # other nets — those are exactly the ones a straight run walks
                # over. The flyback's transformer is the case: the aux rectifier
                # hangs off its ``AUX`` pin and the run crosses its ``PGND`` pin
                # 20 units along.
                if (pins_of.get(pin.number) or pins_of.get(pin.name, "")) in own:
                    continue
                point = _pin_point(ctx, other, pin.number, poses, origins)
                if point is None:
                    continue
                if _on_polyline(point, (start, end)):
                    found += 1
        return found

    # The leg: anchor -> root, the stretch the **shared** pad travels. A foreign
    # pin here is 114's original case.
    # 120: the escape **side** is decided before either leg is tested, not
    # inside the first one. It used to be computed inside ``if blockers:`` while
    # the **trail** walk below read it — so a branch whose anchor->root leg was
    # clear but whose trail was not reached this function with ``sign`` unbound
    # and raised ``UnboundLocalError`` instead of reporting a placement it could
    # not fix. That is 053 sec.4's "a refusal without a reason": the compiler
    # crashed instead of saying anything. Whether the leg has blockers is not a
    # statement about which side is clear, so the two questions are now separate.
    owner_centre = _body_centre(ctx, slot.owner, poses, origins)
    sign = 1.0
    if owner_centre is not None:
        to_centre = (
            owner_centre[0] - anchor[0], owner_centre[1] - anchor[1],
        )
        if abs(to_centre[0]) * abs(unit[0]) + abs(to_centre[1]) * abs(unit[1]) > 0.0:
            sign = -1.0 if (
                to_centre[0] * unit[0] + to_centre[1] * unit[1]
            ) > 0.0 else 1.0

    blockers = _blockers_between(anchor, root, part_id)
    if blockers:
        # Away from the owner's own body: the run starts at the owner's pin, so
        # the clear side is the one the owner's centre is not on.
        step = _snap(GAP + ctx.budget.channel * 0.0, ctx.budget.grid, 0.0)
        if step <= 0.0:
            step = ctx.budget.grid
        shifted = list(root)
        shifted[index] = root[index] + unit[index] * sign * step
        root = (shifted[0], shifted[1])

    # The trail: the stretch **past** the root, where this branch's other pad
    # lands (117①). Re-measured at the root the dodge just produced, not at the
    # one it was handed — the two are different points, and a dodge that moves
    # the branch sideways can *create* a trail collision it never looked at.
    if trail is not None:
        far = (root[0] + trail[0], root[1] + trail[1])
        if _blockers_between(root, far, part_id):
            # The trail is along the run, so the escape is the same axis the leg
            # used: step the root further out along its own direction until the
            # trail is clear. `step` is one whole :data:`GAP` ladder rung, and the
            # walk is bounded by the part's own extent plus that clearance, so a
            # branch that cannot be cleared is left where it is and the gate
            # reports it — never silently parked somewhere arbitrary.
            step = _snap(GAP, ctx.budget.grid, 0.0) or ctx.budget.grid
            reach = _snap(
                _extent(_part_box(ctx.profile(part_id), poses[part_id]),
                        (unit[0], unit[1]))[1] + GAP,
                ctx.budget.grid, 0.0,
            )
            walked = 0.0
            while walked <= reach + step:
                walked += step
                away = list(root)
                away[index] = root[index] + unit[index] * sign * walked
                candidate = (away[0], away[1])
                if not _blockers_between(
                        candidate, (candidate[0] + trail[0],
                                    candidate[1] + trail[1]), part_id):
                    return candidate
            return root
    return root


def _body_centre(
    ctx: _Context, part_id: str,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """A part's body centre in page coordinates, or ``None`` when it has no body."""
    profile = ctx.book.get(_symbol_ref(ctx, part_id))
    if profile is None or profile.body is None:
        return None
    local = (
        (profile.body[0] + profile.body[2]) / 2.0,
        (profile.body[1] + profile.body[3]) / 2.0,
    )
    point = _posed(local, poses[part_id], origins[part_id])
    return point


def _park_unordered_chain(
    ctx: _Context,
    origins: dict[str, tuple[float, float]],
    boxes: Mapping[str, Box],
    variant: _Variant,
) -> None:
    """Move a chain part the grammar never ordered **beside** its partner.

    The chain is drawn along one axis, and a chain part's place on it comes from
    the order relations between chain parts. A chain part with **no** order
    relation to any other chain part therefore has no place on that axis at all —
    the rank walk gives it one by its part id, which is an accident of the
    alphabet and not a statement about the circuit. The flyback's secondary
    rectifier is the case: the grammar says `near(D3, T1)` and nothing else, and
    the walk put D3 at the head of the chain, so the rectifier sat *above* the
    transformer with its winding pin facing back into it, and the winding could
    not be wired at all.

    What the grammar did say is `near`, so that is what this honours: the part
    takes its partner's position **along the chain's own axis** and is offset
    **laterally** by one clear channel. That is what `near` means for a part on a
    spine — beside, not before — and it leaves every rank the order relations
    established untouched, because this part had none of its own.

    The direction of the lateral offset is the conservative one: the side an
    order kind between the two names when the grammar stated one, and otherwise
    the positive side of the lateral axis — the tie-break the rest of this module
    uses. It only chooses a side, and the relation checker measures the result
    either way, so a tie-break is a tie-break and is not dressed up as a reading.
    With no partner at all the part is left where the rank walk put it, rather
    than have a position invented for it.
    """
    for part_id in ctx.chain:
        if ctx.locked(part_id) is not None:
            continue
        if _has_chain_order(ctx, part_id):
            continue
        partner = _chain_near_partner(ctx, part_id)
        if partner is None or partner not in origins:
            continue
        lateral = ctx.lateral()
        index = 0 if lateral[0] != 0.0 else 1
        axial = 1 - index
        # Half of each box, measured from the partner's own origin, so the
        # offset clears both bodies without a constant of its own.
        distance = _snap(
            _extent(boxes[partner], lateral)[0]
            + _extent(boxes[part_id], lateral)[0]
            + ctx.budget.channel * variant.scale,
            ctx.budget.grid, 0.0,
        )
        sign = _near_side_sign(ctx, part_id, partner)
        shifted = list(origins[part_id])
        shifted[axial] = origins[partner][axial]
        shifted[index] = origins[partner][index] + sign * distance
        origins[part_id] = (shifted[0], shifted[1])


def _near_side_sign(ctx: _Context, part_id: str, partner: str) -> float:
    """Which side of its `near` partner an unordered chain part is drawn on.

    The side an order kind between the two states, when the grammar stated one;
    otherwise the positive side of the lateral axis.
    """
    for item in ctx.binding.constraints:
        if {item.subject, item.object} != {part_id, partner}:
            continue
        if item.kind == LEFT_OF:
            return -1.0 if item.subject == part_id else 1.0
        if item.kind == RIGHT_OF:
            return 1.0 if item.subject == part_id else -1.0
    return 1.0


def _has_chain_order(ctx: _Context, part_id: str) -> bool:
    """Does any order kind place this part against another chain part?"""
    return any(
        item.kind in (ABOVE, BELOW, LEFT_OF, RIGHT_OF, ADJACENT)
        and part_id in (item.subject, item.object)
        and item.subject in ctx.chain and item.object in ctx.chain
        for item in ctx.binding.constraints
    )


def _chain_near_partner(ctx: _Context, part_id: str) -> str | None:
    """The chain part this one is `near`, when the grammar said so and only so."""
    found: list[str] = []
    for item in ctx.binding.constraints:
        if item.kind != NEAR:
            continue
        pair = {item.subject, item.object}
        if part_id not in pair:
            continue
        other = (pair - {part_id}).pop()
        if other in ctx.chain:
            found.append(other)
    return min(found) if found else None


def _align_branch_lanes(
    ctx: _Context,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    residue: tuple[float, float],
) -> None:
    """Put every branch of a same-line group **on** the line, not near it.

    The group was placed per-owner first (each branch off its own owner's pin,
    which is what puts a divider arm beside the rectifier), and this pass makes
    the grammar's statement true: the members of a `same-row` group end up with
    one **y**, of a `same-column` group with one **x**.

    The three design choices are the conservative ones, each for a stated reason:

    * **the anchor** is a **fixed** member when the group has one — a chain part,
      which the page's spine must not move, or a locked part, which the engineer
      placed. With none, the anchor is the member with the smallest rank (ties by
      part id) — the group keeps the place the page's own read gave it instead of
      drifting toward the group's own centroid, which a later relation could undo;
    * every other member is shifted **only along the line's own axis**, so the
      perpendicular offset from its own owner survives exactly as measured and only
      the line coordinate is replaced. This is what keeps the group's parts near
      what they hang off, which `near` is also measuring;
    * the shift is applied **once**, from the pre-shift origins. A second pass
      would let the first shift decide the second, and the members would end up a
      lane apart — the very thing this pass exists to remove.

    A locked member is never moved and a chain member is never moved: a lock is
    the engineer's coordinate and the chain is the page's spine, and the relation
    checker reports a conflict against the lock (053 sec.5 scenario 12) rather
    than the compiler overriding either. A group of only fixed members does
    nothing at all.
    """
    groups: dict[str, list[str]] = {}
    axes: dict[str, str] = {}
    for part_id, (axis, label, members) in sorted(ctx.lane_groups.items()):
        groups.setdefault(label, members)
        axes[label] = axis
    for label in sorted(groups):
        # `axis` is the *coordinate* the line fixes: a `same-row` group shares one
        # **y** (index 1), a `same-column` group one **x** (index 0).
        index = 1 if axes[label] == "y" else 0
        present = [
            part_id for part_id in groups[label] if part_id in origins
        ]
        movable = sorted(
            (
                part_id for part_id in present
                if ctx.locked(part_id) is None
                and ctx.slots[part_id].kind == "branch"
            ),
            key=lambda part_id: (ctx.slots[part_id].rank, part_id),
        )
        fixed = [
            part_id for part_id in present
            if part_id not in movable
        ]
        if not movable or not (fixed or len(movable) > 1):
            continue
        before = {part_id: origins[part_id] for part_id in present}
        # The group is aligned by **relaxation over its own same-line edges**, not
        # against one anchor pin, because a member can be related to two different
        # group-mates on two different nets and the two relations are measured on
        # two *different pins* of that member: the flyback's U4 is asked to share a
        # row with the divider (through its ``FB_SENSE`` pad) **and** with the
        # optocoupler (through its ``LED_K`` pad), and those pads sit 40 units
        # apart in the symbol. So there is no single "the row" to align to; there
        # is a set of edges, and the pass makes each edge's two measured points
        # level in turn, taking the already-placed side of each edge as the
        # reference.
        #
        # A **fixed** member (chain or locked) is the reference whenever the edge
        # touches it — the page's spine does not move. Among two free members the
        # lower rank keeps its place and the other moves, so the iteration is
        # deterministic and terminates: each step strictly reduces the set of
        # unlevelled edges.
        _relax_branch_lanes(ctx, present, movable, index, origins, poses)


def _relax_branch_lanes(
    ctx: _Context,
    present: Sequence[str],
    movable: Sequence[str],
    index: int,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
) -> None:
    """Level a same-line group by relaxing over **its own edges**.

    Each edge is one grammar relation, measured on one net, between one pair of
    parts. The pass walks the edges and makes each one's two measured points
    level, taking the side that must not move as the reference:

    * a **fixed** member (a chain part or a locked one) always wins the reference;
    * otherwise the member with the **lower rank** keeps its place and the other
      moves, so the direction of every shift is decided by the grammar's own
      order rather than by iteration order.

    The walk is repeated until no edge moves a part by a whole lattice step,
    bounded by :data:`LANE_RELAX_ROUNDS`. It terminates because a group whose
    edges form a cycle of *moves* would need every member to move at once, and
    the round bound turns that into "the group's relations are not jointly
    satisfiable by translation alone" — reported by the relation checker with
    the measurement, not silently half-applied. The bound is generous (a real
    feedback row converges in two rounds) so that a group which *is* satisfiable
    is never cut off.

    Only the line coordinate is touched. The perpendicular offset from each
    part's own owner survives exactly as the per-owner placement measured it,
    which is what keeps the `near` relations and the wiring routes true.
    """
    edges = ctx.lane_edges.get(_label_of(ctx, present), [])
    if not edges:
        return
    settled = set(_fixed_of(ctx, present, movable))
    fixed_edges = [
        edge for edge in edges
        if (edge[0] in settled) or (edge[1] in settled)
    ]
    free_edges = [edge for edge in edges if edge not in fixed_edges]
    for _round in range(LANE_RELAX_ROUNDS):
        moved = False
        # The edges that touch a fixed member run first: a chain part is the
        # page's spine, so the line it implies is the one the group is hung on,
        # and the branches hanging off that part follow it rather than the other
        # way round. Walking them in the other order would let a branch set the
        # line and then drag the part the chain already placed off it.
        for here, there, shared in fixed_edges + free_edges:
            if here not in origins or there not in origins:
                continue
            here_fixed = here in settled
            there_fixed = there in settled
            if here_fixed and there_fixed:
                continue
            if here_fixed or (not there_fixed and _keeps(ctx, here, there)):
                reference, moving = here, there
            else:
                reference, moving = there, here
            target = _lane_coordinate(ctx, reference, shared, index, origins, poses)
            current = _lane_coordinate(ctx, moving, shared, index, origins, poses)
            if target is None or current is None:
                continue
            delta = _snap(target - current, ctx.budget.grid, 0.0)
            if not delta:
                # Already level: this end of the edge is now a reference too, so
                # a later edge touching it will not drag it off the line it has
                # just been put on.
                settled.add(moving)
                continue
            origin = origins[moving]
            shifted = list(origin)
            shifted[index] = origin[index] + delta
            origins[moving] = (shifted[0], shifted[1])
            settled.add(moving)
            moved = True
        if not moved:
            return


def _label_of(ctx: _Context, present: Sequence[str]) -> str:
    """The lane label shared by the group's members (``""`` when mixed)."""
    for part_id in present:
        lane = ctx.lane_groups.get(part_id)
        if lane is not None:
            return lane[1]
    return ""


def _fixed_of(
    ctx: _Context, present: Sequence[str], movable: Sequence[str]
) -> set[str]:
    """The group's members that must not move: its chain parts and its locks."""
    return {
        part_id for part_id in present
        if part_id not in movable
    }


def _keeps(ctx: _Context, here: str, there: str) -> bool:
    """Does `here` keep its place (and `there` move) when both are free?"""
    return (ctx.slots[here].rank, here) <= (ctx.slots[there].rank, there)


def _lane_coordinate(
    ctx: _Context, part_id: str, shared_net: str, index: int,
    origins: Mapping[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
) -> float | None:
    """The line coordinate of a branch, measured **as the checker measures it**.

    Not the origin: :func:`_points_for_relation` measures a same-line kind
    between the two parts' **pins on the net they share** when they share one, and
    between the two **origins** when they do not. So the coordinate is read from
    the pin on `shared_net` when one is named, and from the origin when it is
    ``""`` — the same two cases, in the same order, or the pass would satisfy
    itself and leave the gate still refusing, which is the 113 symptom again.
    """
    if shared_net:
        token = _token_on(ctx.circuit, part_id, shared_net)
        if token:
            point = _pin_point(ctx, part_id, token, poses, origins)
            if point is not None:
                return point[index]
    origin = origins.get(part_id)
    return None if origin is None else origin[index]


# ----------------------------------- 116: every bound order, not just the owner's


def _honour_bound_orders(
    ctx: _Context,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    pose_index: int = 0,
    baseline: frozenset[tuple[str, str, str]] | None = None,
) -> None:
    """Consume **every** bound order the placement breaks, not only the owner's.

    113 bound all of them. 115① consumed the ones between a branch and its
    **owner**; 114's lane pass consumed the same-line ones between branches of
    one group. What nobody consumed is everything else the grammar said, and
    all four of 115's remaining gate reports are one root cause: this stage did
    not read them.

    The pass walks the **whole** constraint list rather than the owner's, and
    for each order the placement currently breaks, moves the movable side along
    the axis that order names until the relation checker stops reporting it.
    Three design choices, each for a stated reason:

    * **only a relation the tightest layout already breaks** moves anything.
      This is the rule that makes the 83 shipped previews byte-identical, and
      it is worth stating in full because the obvious weaker version is wrong.

      The obvious rule — "move whatever this variant breaks" — is **not** a
      no-op on the existing grammars, and measuring that is how this one was
      arrived at. In 098 the wide rungs break ``near(C1, U1)`` (that sheet
      really is too narrow at spacing 1.5 and 2.2), so a pass that reads every
      broken relation drags ``C1`` in and **rescues three rungs the compiler
      had correctly refused**: 098 goes from 1 candidate to 3 and three
      previews move. That is the pass papering over the spacing ladder's own
      answer, which is a decision, not a defect.

      The distinction that holds: a relation the **tightest** rung already
      keeps is the ladder saying "this page has no room", and a relation every
      rung breaks is a **placement** failure the grammar stated and this stage
      never read. All three of the flyback's ``C10``-against-``U5`` relations
      are broken at ``spacing=1 pose-variant=0`` as well as at every wider
      rung, while 098's ``near(C1, U1)`` holds there. So the pass is the
      identity on all five existing grammars and still consumes the four on
      the page that needs them.
    * **pose first** — 115①'s hard lesson, in the form 115 had to be rewritten
      to learn it. If the movable side has a **pose the ladder actually
      explores** whose pad already points the relation's way, the pose ladder
      is left to find it. A variant *is* one rung of that ladder (053 sec.4),
      so answering for it redraws a variant whose poses the search has not
      exhausted; that is the byte 098 scene 08 lost in 114, and it is why
      ``same-column(Q1, R5)`` — a relation between two **chain** parts, which
      nothing may move — is reported as pose-solvable rather than moved.
    * **the placed side is the reference** — 114's lane paradigm. A chain part
      is the page's spine and a lock is the engineer's own coordinate; neither
      moves. When both ends are free the lower rank keeps its place, so every
      shift's direction comes from the grammar's own order rather than from
      iteration order.

    The walk is bounded by :data:`ORDER_RELAX_ROUNDS`. Running out of rounds is
    not a silent pass: whatever is still broken stays where it is and the
    relation checker reports it with the two measured points it would have
    reported anyway — the honest refusal 115 kept.
    """
    fixed = {
        part_id for part_id in ctx.slots
        if ctx.locked(part_id) is not None or part_id in ctx.chain
    }
    for _round in range(ORDER_RELAX_ROUNDS):
        moved = False
        for item in _bound_orders(ctx, origins, poses, baseline):
            here, there = item.subject, item.object
            if here not in origins or there not in origins:
                continue
            here_fixed, there_fixed = here in fixed, there in fixed
            if here_fixed and there_fixed:
                continue
            if here_fixed or (not there_fixed and _keeps(ctx, here, there)):
                reference, walking = here, there
            else:
                reference, walking = there, here
            if _pose_can_say(ctx, item, walking, reference, poses, origins,
                             pose_index):
                continue
            if _order_step(ctx, item, walking, reference, origins, poses):
                moved = True
        if not moved:
            return


def _bound_orders(
    ctx: _Context,
    origins: Mapping[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
    baseline: frozenset[tuple[str, str, str]] | None = None,
) -> list[Any]:
    """The bound relations this placement **breaks**, in a stable order.

    "Breaks" is measured with :func:`_relation_violations` — the one ruler the
    placement stage, the gate and the preview layer all read — so a pair listed
    here is exactly a pair that would be refused. Which two points a kind is
    measured between is :func:`_points_for_relation`'s and is not restated.

    Only the kinds this pass can act on are listed; an obligation, a tap or an
    ``adjacent`` is another subsystem's business and 116 does not touch it.

    `baseline` is the set the **tightest** rung breaks (see
    :func:`_honour_bound_orders`). A relation outside it is the spacing ladder
    reporting that the page has no room, and this pass leaves it to the ladder;
    that filter is what makes the pass the identity on the five existing
    grammars. ``None`` means no filter, which is what a caller with no base
    rung to compare against wants.
    """
    out: list[Any] = []
    for item, _points in _relation_violations(
        ctx.circuit, ctx.binding,
        origin_of=lambda part_id: origins.get(part_id),
        pin_of=lambda part_id, token: _pin_point(
            ctx, part_id, token, poses, origins),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=ctx.lateral(), progress=ctx.progress,
    ):
        if item.kind not in (ABOVE, BELOW, LEFT_OF, RIGHT_OF, SAME_ROW,
                             SAME_COLUMN, NEAR):
            continue
        if baseline is not None and (item.kind, item.subject, item.object) not in baseline:
            continue
        out.append(item)
    out.sort(key=lambda item: (item.kind, item.subject, item.object))
    return out


def _order_step(
    ctx: _Context,
    item: Any,
    walking: str,
    reference: str,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
) -> bool:
    """Move ``walking`` one whole step onto the side ``item`` names.

    Returns whether the coordinate actually moved. The step is measured on the
    **same two points the checker measures the pair on** — the shared net's pin
    when the pair shares one, the origin when it does not — so a single walk
    clears the tolerance by construction and the pass never satisfies itself
    against a different ruler than the gate uses. 114's
    :func:`_lane_coordinate` is that one measurement, reused rather than
    restated.
    """
    shared = _shared_net_of(ctx, walking, reference)
    if item.kind == NEAR:
        return _order_step_near(ctx, shared, walking, reference, origins, poses)
    if item.kind in (SAME_ROW, SAME_COLUMN):
        # A same-line kind asks for **equality**, not a side, so there is no
        # sign to step past: the walk is a snap onto the reference's own
        # coordinate. The axis is the coordinate the line fixes — a
        # `same-column` shares one **x** (index 0), a `same-row` one **y** —
        # the same reading 114's lane pass uses.
        index = 0 if item.kind == SAME_COLUMN else 1
        current = _lane_coordinate(ctx, walking, shared, index, origins, poses)
        target = _lane_coordinate(ctx, reference, shared, index, origins, poses)
        if current is None or target is None:
            return False
        if abs(current - target) <= ctx.budget.grid / 2.0:
            return False
        return _shift_origin(ctx, walking, index, current, target, origins)
    index, sign = _order_asks(item.kind, walking == item.subject)
    # An **order** kind is measured between the two **origins** — never on
    # pins. That is :func:`_points_for_relation`'s own split, and reading the
    # pins here would move the part by its own pad offset: the 116 draft's
    # first bug, which stepped ``C1`` off the shared net's pad instead of off
    # the body and reported a move the checker never saw.
    current = origins[walking][index]
    target = origins[reference][index]
    if current is None or target is None:
        return False
    if (current - target) * sign > ctx.budget.grid / 2.0:
        # Already **past** the reference on the side this order names: the
        # checker reads `ax > bx + slack` for an order kind, so anything past
        # `grid / 2` already holds and the pair is broken on something else.
        # A gap that only *reaches* the reference is still broken — that is the
        # `right-of(C1, U1)` case, both measured pins sitting on x = 0.
        return False
    # One **whole lattice step** onto the far side of the reference, not
    # `grid / 2`: `_snap` rounds halves to even, so half a step would land back
    # on the reference and the walk would report a move it did not make. A whole
    # step clears the checker's tolerance by construction.
    #
    # The delta is taken **on the measured coordinate** and applied to the
    # **origin**, because those are two different points when the pair shares a
    # net: `_lane_coordinate` reads a pin, the layout stores an origin. Writing
    # the pin's absolute coordinate into the origin's slot would move the part
    # by its own pin offset — the 116 draft's first bug, which put ``C1`` 60
    # units the wrong way on a pair whose pins sat on the body axis.
    #
    # 120: **where it lands keeps the part's own room, not just "past the
    # reference".** An order kind states a *side* (``above`` is a side, not a
    # coordinate), so landing every part on ``target + sign*grid`` satisfies any
    # number of them by stacking them on one line — which is exactly what the
    # flyback's clamp string did: four branches, four ``above(X, Q1)`` relations,
    # one shared reference, and **four parts at the same y**. Their own horizontal
    # wires then ran straight through a neighbour's pin, and
    # ``readability._derive`` (which unions by coordinate) merged two nets into
    # one — a ``netlist-partition-mismatch`` that has nothing to do with the
    # order being satisfied.
    #
    # So the wanted coordinate is the side the order names **plus whatever room
    # this part already had from the ones that went before it**: the distance it
    # is being asked to keep clear by. A part moving alone is unaffected (its
    # own separation is measured from the reference), and a part arriving second
    # lands one lane further out, so the group reads as a group instead of a
    # stack. Nothing is asked to be *exactly* anywhere: the checker reads a side
    # with ``grid/2`` of slack, and this keeps a whole lattice step of it.
    #
    # The extra room is only spent when **somebody is already there**: the target
    # this walk names is a whole coordinate, and if another part already sits on
    # it, landing on it too is what stacks the group. If nobody is there, the
    # part takes the plain step, which is the identity on every page where the
    # order kinds do not compete for one coordinate — that is what keeps this
    # pass byte-for-byte identical on the five shipped grammars (measured, see
    # outputs/120/SUMMARY.md: 83/83 with this condition, 74/83 without it).
    wanted = target + sign * ctx.budget.grid
    if _contended_landing(ctx, origins, walking, index, target):
        # Somebody is already standing where this order would put me. An order
        # kind states a *side*, not a coordinate, so landing on the same point
        # as the part that arrived first is not what it asked for — and it is
        # actively harmful: two parts on one row wire to each other along a line
        # that runs over a neighbour's pin, and ``readability._derive`` (which
        # unions by coordinate) then merges two nets. The flyback's clamp string
        # is the case: four branches, four ``above(X, Q1)`` relations, one shared
        # reference, and all four on one y. Keeping this part the room it already
        # had turns the stack back into a group; the order still holds, because
        # it states a side and the checker reads it with ``grid/2`` of slack.
        wanted = target + sign * (abs(current - target) + ctx.budget.grid)
    return _shift_origin(ctx, walking, index, current, wanted, origins)


def _contended_landing(
    ctx: _Context,
    origins: Mapping[str, tuple[float, float]],
    walking: str,
    index: int,
    target: float,
) -> bool:
    """Is another part already on the coordinate this order walk lands on?

    120. Read off the **current** layout, at the moment of the walk, rather than
    off the binding: what matters is whether the landing spot is *occupied now*,
    which is a question about the drawing in progress. Two parts on one coordinate
    is the whole failure — the one that made the clamp string's wires short two
    nets — so a page where nothing else is there is untouched, which is what keeps
    the pass the identity on the five shipped grammars (83/83 byte-identical;
    see outputs/120/SUMMARY.md).
    """
    for other, here in origins.items():
        if other == walking:
            continue
        if abs(here[index] - target) <= ctx.budget.grid / 2.0:
            return True
    return False


def _shift_origin(
    ctx: _Context,
    part_id: str,
    index: int,
    measured_now: float,
    measured_wanted: float,
    origins: dict[str, tuple[float, float]],
) -> bool:
    """Move a part's **origin** by the delta its measured coordinate needs.

    The step is worked out on whatever the gate measures — a pin on the shared
    net, or the origin when the pair shares none — and applied to the origin,
    which is the only thing the layout stores. The two differ by the part's own
    pin offset, so the delta is the quantity that transfers.
    """
    delta = measured_wanted - measured_now
    if not delta:
        return False
    origin = origins[part_id]
    shifted = list(origin)
    shifted[index] = origin[index] + _snap(delta, ctx.budget.grid, 0.0)
    if shifted[index] == origin[index]:
        return False
    origins[part_id] = (shifted[0], shifted[1])
    return True


def _order_step_near(
    ctx: _Context,
    shared: str,
    walking: str,
    reference: str,
    origins: dict[str, tuple[float, float]],
    poses: Mapping[str, SymbolPose],
) -> bool:
    """Trim a ``near`` down to its budget, on the axis that separates the pair.

    ``near`` states a **distance**, not a side, so there is no sign to take from
    the grammar. What it does say is *how close* — ``near_limit`` — and that
    budget is the whole of what this pass is allowed to spend. The move takes
    the excess over the limit off the separating axis and stops: not a creep of
    one lattice step, which could never close the flyback's 62-unit overshoot
    inside :data:`ORDER_RELAX_ROUNDS` rounds, and not a slide onto the
    reference, which satisfies the relation and destroys the drawing.

    Which side moves is decided by the caller, on 114's rule: the chain and the
    lock never move, and of two free parts the lower rank keeps its place. So a
    ``near`` between two branches of one string pulls the **later** arm toward
    the earlier one, and the earlier arm's own ``near`` to its owner is left
    alone — which is the point: the string closes without either arm leaving
    what it hangs off.

    Bounded by the round count like every other step: a pair still too far apart
    after :data:`ORDER_RELAX_ROUNDS` rounds is left broken and is reported with
    its two measured points, which is the same honest refusal 114 gave the
    branch string.
    """
    here_x = _lane_coordinate(ctx, walking, shared, 0, origins, poses)
    there_x = _lane_coordinate(ctx, reference, shared, 0, origins, poses)
    here_y = _lane_coordinate(ctx, walking, shared, 1, origins, poses)
    there_y = _lane_coordinate(ctx, reference, shared, 1, origins, poses)
    if None in (here_x, there_x, here_y, there_y):
        return False
    index = 0 if abs(here_x - there_x) >= abs(here_y - there_y) else 1
    mine, theirs = (here_x, there_x) if index == 0 else (here_y, there_y)
    # ``near`` is a **two-dimensional** distance, so the excess is taken off the
    # distance and not off the separating axis. Reading it off the axis is the
    # 116 draft's fourth bug and it moved two more previews: with 098's
    # ``near(C2, U1)`` the two measured points are 60 apart on y and 400 on x,
    # the axis rule subtracted ``near_limit`` from the x gap and dragged a
    # capacitor 60 units along y — a coordinate ``near`` never asked about —
    # and it fired even where the true distance already held.
    excess = math.hypot(here_x - there_x, here_y - there_y) - ctx.budget.near_limit
    if excess <= 0.0:
        return False
    # 120: one whole lattice step of the limit is spent **before** the trim, for
    # the same reason 119 measured on this same pair (``near(C10, U5)``): the move
    # is applied to an origin and then snapped onto the compilation lattice, so a
    # trim that lands exactly on the limit lands up to half a step outside it —
    # and the gate measures ``near`` with **no** tolerance
    # (``_relation_holds``: ``hypot <= near_limit``), so 0.167 is a violation, not
    # a rounding artefact. Spending the step up front makes the trim clear the
    # limit *after* the snap instead of before it.
    #
    # A whole ``grid``, not ``grid/2``: the relaxation pass may take a step of its
    # own on this pair afterwards (the ``above``/``near`` family both name it),
    # and two half-steps are a whole one. Byte cost measured: none — 83/83
    # identical (see outputs/120/SUMMARY.md).
    excess += ctx.budget.grid
    # Only as far as the limit asks, never onto the reference. ``near`` is a
    # **distance with a budget**, not an equality: sliding the walking side all
    # the way onto the reference satisfies it and destroys the drawing — the
    # 116 draft's second bug, which stacked 088's ``D1`` and ``C117`` on the
    # page origin (x -445 -> -50, -345 -> -5, 345 -> 5, 445 -> 50) and moved
    # twelve of the 83 previews. The move therefore takes the excess off the
    # separating axis and stops, which is the smallest answer that is true and
    # leaves every other distance alone.
    if mine == theirs:
        return False
    # ``sign`` points **at** the reference: ``-1`` when this side's coordinate
    # is the larger one. The move is then ``+ sign * excess`` — toward the
    # reference by exactly the overshoot. It reads ``mine + sign * excess`` and
    # not the other way round; the 116 draft's third bug had it reversed, which
    # walked 088's ``D1`` and the flyback's ``R15`` steadily *away* from what
    # they were supposed to hug — ``R15`` -455 -> -550 -> -740 -> -1120 — and
    # ran the round budget out with a pair 200,000 units apart.
    sign = -1.0 if mine > theirs else 1.0
    return _shift_origin(ctx, walking, index, mine, mine + sign * excess, origins)


def _order_asks(kind: str, own: bool) -> tuple[int, float]:
    """``(axis, sign)`` that tells **the checker** this side wants for ``kind``.

    Read straight off :func:`_relation_holds` rather than off a hand-written
    table, so this can never disagree with the ruler that will judge the move.
    Concretely: put the walking side one step in each direction along the
    order's axis and ask the checker which one it accepts.

    There is already a function shaped like this in the module,
    :func:`_order_wanted`, and 116 did **not** call it, for a reason worth
    recording. That function is 115(1)'s, and its hand-written table disagreed
    with the checker — see its own docstring for the measured table. 117③
    repaired the table, so the two now agree on all four kinds; this function is
    kept as the **independent** reading of the checker, which is the property
    worth having: a test can assert the two agree, and either one drifting from
    :func:`_relation_holds` is then a caught regression rather than a latent
    disagreement.
    """
    axis = 0 if kind in (LEFT_OF, RIGHT_OF) else 1
    origin = (0.0, 0.0)
    for sign in (1.0, -1.0):
        probe = [0.0, 0.0]
        probe[axis] = sign * 10.0
        points = (tuple(probe), origin) if own else (origin, tuple(probe))
        if _relation_holds(
            kind, points, grid=1.0, near_limit=300.0,
            lateral=(0.0, 1.0), progress=(1.0, 0.0),
        ):
            return axis, sign
    return axis, 1.0


def _shared_net_of(ctx: _Context, here: str, there: str) -> str:
    """The net this pair is measured on, or ``""`` when they share none.

    The same first net :func:`_points_for_relation` picks, so the coordinate
    this pass moves is the coordinate the gate measures.
    """
    common = sorted(
        set(_part_nets(ctx.circuit, here).values())
        & set(_part_nets(ctx.circuit, there).values())
    )
    return common[0] if common else ""


def _pose_can_say(
    ctx: _Context,
    item: Any,
    walking: str,
    reference: str,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
    pose_index: int = 0,
) -> bool:
    """Would the pose ladder place this pair correctly under some pose?

    The pose-first gate, and the whole of 115①'s lesson as it applies here. It
    asks the **accepted** pose set — the poses :func:`_accepted_poses` already
    filtered to the legal ones — so "some pose exists" means "some pose this
    compiler would actually draw", the same ruler 115① reads.

    **An order kind cannot be answered by re-posing a part, and that is the
    correction this function exists to record.** A first version tried it
    anyway: it put each end under each accepted pose, re-measured the relation,
    and asked the checker. That can never succeed, and the reason is structural
    rather than a slip — :func:`_points_for_relation` measures an order kind
    between the two **origins**, and a pose moves pins, not origins. All eight
    of 098's ``U1`` poses measured identically and the gate answered "no pose
    can say this", so the pass moved four branches onto ``U1``'s own column
    (``C1`` 290 -> -5, ``C2`` 170 -> -5, ``C4`` -170 -> 5, ``X1`` 230 -> -5)
    and moved three of the 83 previews.

    So the question is not "would this pose satisfy the relation" but **"would
    the placement under this pose put the pair on the right side"** — and the
    placement follows the owner's **pin direction**, which is what
    :func:`_branch_offset_direction` reads. That is 115①'s own
    :func:`_a_pose_says` criterion, generalised from the owner's poses to either
    end's. In 098 the ``pose-variant=1`` rungs mirror ``U1``, so *all* of
    ``left-of(C1,U1)``, ``left-of(C2,U1)``, ``right-of(C4,U1)`` and
    ``left-of(X1,U1)`` point away from what ``U1``'s pads say; the unmirrored
    poses say all four, the pose ladder was about to find them on its own, and
    answering first is exactly the byte 114 lost and 115 had to be rewritten to
    avoid.

    A same-line or ``near`` kind *is* measured on pins, so those two keep the
    direct test; only the order kinds need this reading.
    """
    if item.kind in (SAME_ROW, SAME_COLUMN, NEAR):
        rungs = {0, pose_index}
        for posing in (walking, reference):
            accepted = ctx.accepted.get(posing, ())
            for rung in sorted(rungs):
                if rung >= len(accepted):
                    continue
                points = _points_under(
                    ctx, item, posing, accepted[rung], poses, origins)
                if _relation_holds(
                    item.kind, points,
                    grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
                    lateral=ctx.lateral(), progress=ctx.progress,
                ):
                    return True
        return False
    return _a_pin_pose_says(ctx, item, walking, reference, pose_index)


def _a_pin_pose_says(
    ctx: _Context,
    item: Any,
    walking: str,
    reference: str,
    pose_index: int,
) -> bool:
    """Does some pose the **ladder actually explores** point this order's way?

    The generalisation of 115①'s :func:`_a_pose_says` from "the owner's poses"
    to "either end's poses", and it asks the same thing: does that symbol's
    **own pad** already leave in the direction the relation names. If it does,
    the per-owner placement (which follows the pad, not the relation) would have
    put the part on the right side, so the pose ladder has an answer coming and
    this pass must not pre-empt it.

    **Only the poses in the ladder's own rungs count** (``pose_index`` 0 and 1,
    the two :func:`_variants` generates). A first version asked the whole
    accepted set, and a core with four rotations has one that happens to point
    the relation's way while the compilation only ever draws rungs 0 and 1 —
    so the gate stood aside on the flyback's real ``right-of(C1, U1)`` and the
    pass left the branch exactly where the grammar said it must not be. The
    question is not "does some rotation exist" but "does a rotation this
    compiler is going to draw exist".

    The pad asked about is the one the placement follows — see
    :func:`_order_probe_pads` for why it is never the walking part's own pads
    and never a chain reference's.
    """
    index, sign = _order_asks(item.kind, walking == item.subject)
    rungs = {0, pose_index}
    for posing, token in _order_probe_pads(ctx, item, walking, reference):
        poses = ctx.accepted.get(posing, ())
        for rung in sorted(rungs):
            if rung >= len(poses):
                continue
            direction = _pin_direction(ctx, posing, token, {posing: poses[rung]})
            if direction is not None and direction[index] * sign > 0.0:
                return True
    return False


def _order_probe_pads(
    ctx: _Context,
    item: Any,
    walking: str,
    reference: str,
) -> list[tuple[str, str]]:
    """The ``(part, pad)`` pairs a pose could speak this order through.

    Two sources, both of them pads that actually **drive a placement**:

    * the walking part's **owner's** shared pad — what
      :func:`_branch_offset_direction` reads to decide which way that branch
      goes, which is 115①'s own subject;
    * the shared net's pad **on the walking part itself**, when the walking
      part is itself a branch that another part hangs off — the same
      "a branch is placed from its owner's pad" statement one level down.

    Two things are deliberately **not** asked, and both were bugs in the
    versions before this one:

    * the walking part's own pads, when it is placed from its owner. ``C10``'s
      pad 2 leaves upward, so ``below(C10, U5)`` read as "a pose already says
      it" and ``C10`` never moved — while ``C10``'s placement is decided by
      ``T1``'s pad, not its own. Asking a part whether it points the right way
      says nothing about where the compiler will put it.
    * the **reference's** pads, when the reference is a chain part. ``U5``'s
      ``COMP`` pad leaves downward and so "said" ``below(C10, U5)`` — but
      ``U5`` is on the page's spine and no pose of it will ever put ``C10``
      anywhere. A chain part's pose is fixed by the variant, not chosen to
      satisfy a branch's order, and asking it concedes the one thing 114 lost
      098 scene 08 over.
    """
    pads: list[tuple[str, str]] = []
    slot = ctx.slots.get(walking)
    if slot is None:
        return pads
    if slot.owner:
        token = _shared_token(ctx, slot)
        if token:
            pads.append((slot.owner, token))
    if slot.kind == "branch" and slot.owner:
        owner_slot = ctx.slots.get(slot.owner)
        if owner_slot is not None and owner_slot.kind == "branch":
            shared = _shared_net_of(ctx, walking, reference)
            token = _token_on(ctx.circuit, walking, shared) if shared else ""
            if token:
                pads.append((walking, token))
    return pads


def _points_under(
    ctx: _Context,
    item: Any,
    posing: str,
    pose: SymbolPose,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The two measured points of ``item`` with ``posing`` under one pose.

    Every other part keeps the pose the current variant drew: the question is
    whether turning *this one* part to that pose would satisfy the relation,
    not whether a whole re-search would. ``posing`` is whichever end of the
    pair the caller is trying, which is why the two ends are both worth asking
    — see :func:`_pose_can_say`.
    """
    shared = _shared_net_of(ctx, item.subject, item.object)
    under = dict(poses)
    under[posing] = pose
    here = _pin_point(
        ctx, item.subject, _token_on(ctx.circuit, item.subject, shared),
        under, origins)
    there = _pin_point(
        ctx, item.object, _token_on(ctx.circuit, item.object, shared),
        under, origins)
    if item.kind in (SAME_ROW, SAME_COLUMN, NEAR) and here and there:
        return (here, there)
    return (origins[item.subject], origins[item.object])


def _tap_junction(
    ctx: _Context,
    net_id: str,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """Where a tap net leaves the chain: the midpoint of the chain pins on it.

    Every *chain* part whose pin sits on this net brackets the tap, and the tap
    leaves between the two extreme ones — the junction the drawing shows, and the
    point the stub has to start from.
    """
    points: list[tuple[float, float]] = []
    for part_id in ctx.chain:
        token = _token_on(ctx.circuit, part_id, net_id)
        if not token:
            continue
        point = _pin_point(ctx, part_id, token, poses, origins)
        if point is not None:
            points.append(point)
    if len(points) < 2:
        return points[0] if points else None
    axis = "y" if ctx.axis == "v" else "x"
    ordered = sorted(points, key=lambda point: point[1] if axis == "y" else point[0])
    first, last = ordered[0], ordered[-1]
    return _rounded(((first[0] + last[0]) / 2.0, (first[1] + last[1]) / 2.0))


def _shared_token(ctx: _Context, slot: _Slot) -> str:
    """The owner's spec pin token on the net this branch shares.

    Which of several pins, when the role is carried on more than one (060 sec.2),
    is a question about the *picture* and not only about the node: the pin the
    branch hangs on is the side of the symbol the branch is drawn on. 065 sec.1
    reads the pin itself — an output branch hangs on the pin that lies across the
    body from the pin its input sibling hangs on, so an LDO's two capacitors land
    one on each side of the core instead of both under its left-hand VOUT pad
    (岳, on the E1 render: "C1 放左边、C2 放右边，不行吗？"). A symbol whose pins
    of that role all sit on one side has no opposite pin and keeps 060's answer.
    """
    opposite = _opposite_side_token(ctx, slot)
    if opposite:
        return opposite
    owner_nets = _part_nets(ctx.circuit, slot.owner)
    for pin, net in sorted(owner_nets.items()):
        if net == slot.shared_net:
            return pin
    return ""


def _opposite_side_token(ctx: _Context, slot: _Slot) -> str:
    """The owner's pin on this branch's net that lies across the body, or ``""``.

    Only an **output** branch asks: the reference is the pin the same owner's
    *input* branch hangs on, and a candidate is opposite when the two pin tips,
    measured from the body's centre, point away from each other — the dot product
    of the two offsets is negative. Strictly negative, so a pin leaving a
    perpendicular side is not called opposite: two supply pins at right angles to
    each other state no pair of sides to separate.

    Reading this in the symbol's own frame is what makes it answerable before a
    pose is chosen (the placement stage asks :func:`_shared_token` while it is
    still accepting poses): a pose is a rotation or a mirror about the part's
    origin, and both keep dot products, so "across the body" means the same thing
    in every pose the symbol may be drawn in.

    The candidates are the owner's pins on the shared net as :func:`_chain_nets`
    reads it — the spec's own members **and** a role's other pins, minus the ones
    the spec lists in ``nc[]`` — because a duplicate pad the spec left unwritten
    is still a pin the drawing may hang the branch on (060 sec.2 wires it either
    way). The most clearly opposite pin wins, by the smallest dot product, so the
    answer does not depend on pin ids when several lie over there.
    """
    if SIDE_ROLES.get(slot.role) != "output":
        return ""
    reference = _input_sibling_token(ctx, slot)
    profile = ctx.book.get(_symbol_ref(ctx, slot.owner))
    if not reference or profile is None or profile.body is None:
        return ""
    anchor = _pin_of_token(profile, reference)
    if anchor is None:
        return ""
    box = profile.body
    centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    ahead = (anchor.tip[0] - centre[0], anchor.tip[1] - centre[1])
    found = ""
    best = 0.0
    for pin, net in sorted(_chain_nets(ctx, slot.owner).items()):
        if net != slot.shared_net or pin == reference:
            continue
        candidate = _pin_of_token(profile, pin)
        if candidate is None:
            continue
        side = (candidate.tip[0] - centre[0], candidate.tip[1] - centre[1])
        dot = ahead[0] * side[0] + ahead[1] * side[1]
        if dot < best:
            found, best = pin, dot
    return found


def _input_sibling_token(ctx: _Context, slot: _Slot) -> str:
    """The pin the owner's own **input** branch hangs on — 065's reference side.

    The input branch is the branch of the same owner whose role names the
    ``input`` side preference (`in_caps`), and its pin is read by
    :func:`_shared_token` itself — which asks this question only for an output
    role, so the two cannot recurse. Branches are read in part-id order, so a
    module with several input capacitors answers the same way every time.
    """
    others = sorted(
        (
            item for item in ctx.slots.values()
            if item.kind == "branch"
            and item.owner == slot.owner
            and item.part_id != slot.part_id
            and SIDE_ROLES.get(item.role) == "input"
        ),
        key=lambda item: item.part_id,
    )
    for other in others:
        token = _shared_token(ctx, other)
        if token:
            return token
    return ""


def _pin_local(
    ctx: _Context, part_id: str, token: str, poses: Mapping[str, SymbolPose]
) -> tuple[float, float] | None:
    """A pin's tip relative to its part's origin, under the part's pose."""
    profile = ctx.profile(part_id)
    pin = _pin_of_token(profile, token)
    if pin is None:
        return None
    return _posed_tip(pin, poses[part_id])


def _pin_point(
    ctx: _Context,
    part_id: str,
    token: str,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """A pin's tip in page coordinates, or ``None`` when the symbol has no such pin."""
    local = _pin_local(ctx, part_id, token, poses)
    if local is None or part_id not in origins:
        return None
    origin = origins[part_id]
    return _rounded((origin[0] + local[0], origin[1] + local[1]))


def _branch_offset_direction(
    ctx: _Context,
    slot: _Slot,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float]:
    """Which way the offset from the owner's pin runs — see :class:`_Slot`.

    ``side``/``line``/``tap``/``order`` carry their own axis (the side the grammar
    states, the line a same-line kind names, the stub's axis, the direction an
    order kind between the branch and its owner names); ``pin`` reads the owner's
    own pin direction from its profile under its chosen pose (which is why the
    pose choice comes first); ``across`` is perpendicular to the chain.
    """
    if slot.basis in ("side", "line", "tap", "order"):
        if slot.basis == "line" and not slot.sign_from_order:
            resolved = _beyond_owner(ctx, slot, poses, origins)
            if resolved is not None:
                return resolved
        sign = float(slot.sign)
        if slot.offset_axis == "x":
            return (sign, 0.0)
        return (0.0, sign)
    if slot.basis == "pin":
        direction = _pin_direction(
            ctx, slot.owner, _shared_token(ctx, slot), poses,
        )
        if direction is not None:
            stated = _order_direction(ctx, slot)
            if stated is not None:
                return stated
            return direction
    lateral = ctx.lateral()
    sign = float(slot.sign)
    return (lateral[0] * sign, lateral[1] * sign)


def _order_direction(ctx: _Context, slot: _Slot) -> tuple[float, float] | None:
    """The direction an **order kind** names, when the owner's symbol cannot say it.

    The owner's own pin says which way *that pad* escapes; an order kind between
    the branch and its owner says which **side of the owner** the branch belongs
    on. The two normally agree and then this returns ``None`` — the pin
    direction stands and not one coordinate moves. They disagree when the pad
    leaves perpendicular to where the branch has to go: the measured AMS1117
    shape (054 C3) and the flyback's aux reservoir, whose pad leaves sideways so
    the branch lands above the rectifier while the grammar's own
    ``below(C7, D2)`` says under.

    **The gate, and why 114's version had none** (115, after 114's retreat).
    114 gave every order kind between a branch and its owner a basis, and that
    is what moved 098 scene 08 by one byte. 115 measured why: the compiler's
    variants include a **pose ladder** (053 sec.4's finite search), so a symbol
    whose pads face the wrong way under one pose may well face the right way
    under the next. Acting on the order kind regardless of that is not
    "respecting the grammar", it is silently redrawing a *variant* whose pose
    the search has not exhausted — which is exactly the byte 098 scene 08 lost,
    and it took 114's whole sheet with it (the mirrored ``U1`` moved every
    branch on it, and the refusal text with it).

    So the criterion is: **the owner's symbol has no legal pose whose pad already
    points the relation's way** (:func:`_a_pose_says`, which reads the same
    accepted pose set the placement will draw from — "some pose exists" means
    "some pose this compiler would actually draw"). What is left is the real
    disease: the flyback's ``D2`` has one accepted pose, its pad leaves upward,
    ``below(C7, D2)`` says down, no rotation supplies it, and the relation is
    otherwise unsatisfiable. ``below(C11, D3)`` and ``below(C13, D3)`` are
    already said by ``D3``'s pose and stay untouched.

    A first draft stated the gate twice — once on the *current* pin direction and
    once on the pose set. The first was dead: :func:`_a_pose_says` iterates the
    accepted poses, and the current one is among them, so it already stands aside
    in every case the first would have. It is gone rather than shipped as a guard
    that cannot fire.

    The test is on the **sign of the direction alone**: that is the whole of
    what the branch's offset can change — the checker measures the two origins
    for an order kind (never the pins), and the offset is what puts this origin
    on that side of the owner's. A direction silent on the axis the relation is
    about (zero) does not contradict it and is left alone.
    """
    relations = [
        item for item in ctx.binding.constraints
        if item.kind in (ABOVE, BELOW, LEFT_OF, RIGHT_OF)
        and {slot.part_id, slot.owner} == {item.subject, item.object}
    ]
    if not relations:
        return None
    token = _shared_token(ctx, slot)
    for item in relations:
        wanted = _order_wanted(item.kind, item.subject == slot.part_id)
        if _a_pose_says(ctx, slot, token, wanted):
            continue
        return (wanted[1], 0.0) if wanted[0] == 0 else (0.0, wanted[1])
    return None


def _order_wanted(kind: str, own: bool) -> tuple[int, float]:
    """``(axis index, sign)`` an order kind asks of its subject.

    ``own`` says which end of the pair the branch is — the caller passes
    ``item.subject == slot.part_id``, so ``own`` is "the branch is the subject".
    One function for both ends so the two can never be computed inconsistently.

    **Both factors of the table were wrong, and 117③ is the fix** (116 §四
    measured it; see :func:`_order_asks` for the checker-derived twin). The
    checker's own definitions are ``left-of`` → ``subject.x < object.x - slack``,
    ``right-of`` → ``>``, ``above`` → ``subject.y > object.y + slack``,
    ``below`` → ``<``, so the **subject** is asked for ``-x / +x / +y / -y`` and
    the object for the mirror. The table used to be ``+x / -x / -y / +y``: the
    object factor was inverted on all four kinds and the sign factor on the two
    horizontal ones, which cancelled on the two vertical ones — which is why
    115①'s only real case, the vertical ``below(C7, D2)``, read correct and the
    disagreement stayed latent. The two tables now agree on all four kinds.
    """
    index = 0 if kind in (LEFT_OF, RIGHT_OF) else 1
    negative = kind in (LEFT_OF, BELOW)
    return index, (1.0 if own else -1.0) * (-1.0 if negative else 1.0)


def _a_pose_says(
    ctx: _Context, slot: _Slot, token: str, wanted: tuple[int, float]
) -> bool:
    """Is some legal pose of the owner already pointing the order's way?

    The whole of gate 2. It asks the owner's **accepted** pose set — the poses
    :func:`_accepted_poses` already filtered to the legal ones, so "some pose
    exists" means "some pose this compiler would actually draw", not "some
    rotation of the symbol exists in the abstract".
    """
    index, sign = wanted
    for pose in ctx.accepted.get(slot.owner, ()):
        direction = _pin_direction(ctx, slot.owner, token, {slot.owner: pose})
        if direction is not None and direction[index] * sign > 0.0:
            return True
    return False


def _beyond_owner(
    ctx: _Context,
    slot: _Slot,
    poses: Mapping[str, SymbolPose],
    origins: Mapping[str, tuple[float, float]],
) -> tuple[float, float] | None:
    """Which way along the line a same-line branch goes, from the geometry.

    The branch hangs beyond the owner's shared pin, on the far side from the
    points the owner's own chain uses: an RC shunt belongs past the output end of
    the series element, not back underneath it (which would also put the wire
    through the part). The reference points are the *other* chain parts' pins on
    the shared net, plus the owner's pins on its other chain nets — a statement
    about the pins the chain actually uses, so it needs no constant and survives a
    symbol change.
    """
    axis = slot.offset_axis
    if axis not in ("x", "y"):
        return None
    index = 0 if axis == "x" else 1
    shared = _pin_point(ctx, slot.owner, _shared_token(ctx, slot), poses, origins)
    if shared is None:
        return None
    references: list[tuple[float, float]] = []
    owner_nets = _part_nets(ctx.circuit, slot.owner)
    for part_id in ctx.chain:
        if part_id == slot.owner:
            for pin, net in sorted(owner_nets.items()):
                if net == slot.shared_net or net not in ctx.chain_net_rank:
                    continue
                point = _pin_point(ctx, part_id, pin, poses, origins)
                if point is not None:
                    references.append(point)
            continue
        token = _token_on(ctx.circuit, part_id, slot.shared_net)
        if not token:
            continue
        point = _pin_point(ctx, part_id, token, poses, origins)
        if point is not None:
            references.append(point)
    if not references:
        return None
    nearest = min(references, key=lambda point: abs(point[index] - shared[index]))
    sign = 1.0 if shared[index] >= nearest[index] else -1.0
    return (sign, 0.0) if axis == "x" else (0.0, sign)


def _pin_direction(
    ctx: _Context,
    part_id: str,
    token: str,
    poses: Mapping[str, SymbolPose],
) -> tuple[float, float] | None:
    """The page direction a pin points in: which way its escape leaves the body.

    The profile states the pin's direction in symbol-local terms (and says
    whether that came from the file or from the body box); the pose turns it into
    a page direction, and this is the only place that does. A pin the profile
    cannot orient falls back to the direction of its own tip from the part's
    origin, which is a fact about the placed geometry rather than a guess.
    """
    profile = ctx.profile(part_id)
    pin = _pin_of_token(profile, token)
    if pin is None:
        return None
    local = {
        "left": (-1.0, 0.0), "right": (1.0, 0.0),
        "up": (0.0, 1.0), "down": (0.0, -1.0),
    }.get(pin.direction)
    pose = poses[part_id]
    if local is None:
        tip = _posed_tip(pin, pose)
        magnitude = math.hypot(tip[0], tip[1])
        if magnitude <= 1e-9:
            return None
        local = (tip[0] / magnitude, tip[1] / magnitude)
    directed = _posed((local[0], local[1]), pose, (0.0, 0.0))
    if abs(directed[0]) >= abs(directed[1]):
        return (math.copysign(1.0, directed[0]), 0.0)
    return (0.0, math.copysign(1.0, directed[1]))


# ------------------------------------------------------ relation verification


def _relation_failures(ctx: _Context, placed: _Placement) -> list[GrammarFailure]:
    """Relations the placement could not keep — a lock's doing, or the symbol's shape.

    A lock the engineer set is honoured *exactly* (never snapped, never moved),
    so when honouring it breaks a relation the conflict is between the lock and
    the grammar — `presentation-poor`, naming the lock, the relation and the
    action that resolves it. 053 sec.5 scenario 12: "报告冲突+可选动作，不静默忽略
    锁定". The measurement itself is shared with :func:`check_grammar` (one ruler
    for the word "relation" in both layers).

    With no lock involved this is **a refusal, not a bug report** (055 G1): the
    placement stage tries a variant and refuses it when a relation would break,
    so "our own placement broke it" is the rejection reason. When the measurement
    can say *why* — the pin the branch hangs off does not sit on the side the
    relation asks for, which is the measured single-sided AMS1117 (054 C3, pit
    33) — the failure names that pin instead, because "change the side
    preferences or use another symbol" is then an answer the reader can act on.
    """
    out: list[GrammarFailure] = []
    for item, points in _relation_violations(
        ctx.circuit, ctx.binding,
        origin_of=lambda part_id: placed.origins.get(part_id),
        pin_of=lambda part_id, token: _pin_point(
            ctx, part_id, token, placed.poses, placed.origins
        ),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=ctx.lateral(), progress=ctx.progress,
    ):
        locked = sorted(
            part_id for part_id in (item.subject, item.object)
            if ctx.locked(part_id) is not None
        )
        if locked:
            where = (
                "the lock(s) "
                + ", ".join(f"{LOCK_PREFIX}[{part_id}]" for part_id in locked)
            )
            action = (
                "move or drop the lock that conflicts (the other relations put "
                f"{item.subject} and {item.object} where they are), or change the "
                "presentation's side preferences if the whole drawing is meant to "
                "run the other way"
            )
        else:
            shape = _pin_side_note(ctx, item, placed)
            where = shape or (
                "the placement this variant chose (no lock is involved) — "
                f"{item.object} and {item.subject} are not where the relation asks"
            )
            action = (
                "change the presentation's side preferences so the drawing runs "
                "the way this symbol's pins actually leave it, or use a symbol "
                "whose pin leaves on the side the relation asks for (053 sec.2 "
                "forbids renumbering pins to fit the layout); if a legal drawing "
                "is expected from this symbol as it is, report the run — a "
                "compiler that refuses every variant has not found a legal "
                "drawing, not proven that none exists"
            )
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=locked[0] if locked else item.subject,
            detail=(
                f"the relation {item.kind}({item.subject}, {item.object}) is not "
                f"honoured by {where}: measured {_point_text(points[0])} and "
                f"{_point_text(points[1])}, and the constraint's own reason is "
                f"{item.reason!r}"
            ),
            action=action,
        ))
    return out


def _pin_side_note(ctx: _Context, item: Any, placed: _Placement) -> str:
    """Why this symbol's own pin geometry is what breaks the relation, or ``""``.

    Measured, never guessed: the relation has to be an order kind, the two parts
    have to share a net, and the object's **own pin on that net** — the pin a
    branch hangs off — has to sit on the wrong side of the object's origin for
    the relation. That is the shape of the symbol this repo measured (AMS1117
    drawn with VIN/VOUT/GND down one side and a duplicate VOUT on the other, 054
    C3): with the connected pin directly above or below the origin, every branch
    that hangs off it lands on the wrong side of the core, and the drawing is
    refused rather than bent (053 sec.2's "禁止换脚号迁就版式").

    The comparison uses :func:`_relation_holds` — the same ruler that decided the
    relation is broken — so the note cannot disagree with the measurement it
    explains.
    """
    if item.kind not in (ABOVE, BELOW, LEFT_OF, RIGHT_OF):
        return ""
    origin = placed.origins.get(item.object)
    if origin is None:
        return ""
    shared = sorted(
        set(_part_nets(ctx.circuit, item.subject).values())
        & set(_part_nets(ctx.circuit, item.object).values())
    )
    if not shared:
        return ""
    token = _token_on(ctx.circuit, item.object, shared[0])
    pin = _pin_point(ctx, item.object, token, placed.poses, placed.origins)
    if not token or pin is None:
        return ""
    if _relation_holds(
        item.kind, (pin, origin), grid=ctx.budget.grid,
        near_limit=ctx.budget.near_limit, lateral=ctx.lateral(),
        progress=ctx.progress,
    ):
        return ""
    return (
        f"the shape of {item.object}'s own symbol — the pin the branch hangs off, "
        f"{item.object}.{token} on net {shared[0]}, sits at {_point_text(pin)}, which "
        f"is not {_side_word(item.kind)} {item.object}'s origin "
        f"{_point_text(origin)}, so the branch this symbol allows lands on the "
        "wrong side of it"
    )


def _side_word(kind: str) -> str:
    return {
        LEFT_OF: "to the left of",
        RIGHT_OF: "to the right of",
        ABOVE: "above",
        BELOW: "below",
    }[kind]


def _point_text(point: tuple[float, float]) -> str:
    return f"({point[0]:g}, {point[1]:g})"


# ------------------------------------------- stage 3b: how each net is shown


@dataclass(frozen=True)
class _Expression:
    """How one net is expressed on the page, and the promise that decided it.

    ``style`` is one of three, and the choice is the hard-coded label policy of
    053 sec.7 rather than a preference:

    * ``wire`` — the grammar promised this net as a wire (a `direct-wire`
      obligation, or a local topology: `labelPolicy.local` may only be `wire`),
      or it is a short power rail. It is drawn;
    * ``flag`` — a ground, or a rail with more members than `high_fanout`: every
      member gets the *same* flag (that is what `uniform-gnd` means) and the flags
      join by name in the netlist;
    * ``label`` — a net that crosses a module boundary or has high fan-out, where
      `labelPolicy` allows a name instead of a wire.

    ``detached`` is empty for every net but the one shape 069 sec.2 rules on: a
    role whose pads leave the body on **opposite sides**. Those pads are not
    joined by a wire — each is brought out on its own stub and given the same
    flag — so they are listed here, the wire is drawn through the rest, and
    ``pivot`` names the pad of that rest which states the net's own name. A
    detached pad and the wired cluster are one node in the spec and two islands
    on the page, and only a name on each of them makes the drawing say what the
    spec means (the readability checker derives the netlist from the flags).
    """

    net: str
    style: str
    points: tuple[tuple[str, tuple[float, float]], ...]
    reason: str
    detached: tuple[str, ...] = ()
    pivot: str = ""


def _obligation_nets(ctx: _Context) -> set[str]:
    """The nets the grammar (or the presentation) promised to draw as wires."""
    out: set[str] = set()
    for item in ctx.binding.obligations:
        if item.kind == DIRECT_WIRE:
            out.update(item.nets)
    for item in ctx.presentation.direct_wiring_obligations:
        out.update(item.nets)
    return out


def _net_modules(ctx: _Context, net_id: str) -> list[str]:
    """The declared modules the net's parts sit in, sorted.

    The scoping question `labelPolicy.crossModule` asks: a net inside one module
    is a local topology, and one that spans two is exactly the case a label may
    stand in for.
    """
    net = ctx.circuit.net(net_id)
    if net is None or not ctx.presentation.modules:
        return []
    owners = {member.partition(".")[0] for member in net.members}
    found: set[str] = set()
    for module in ctx.presentation.modules:
        if owners & set(module.parts):
            found.add(module.id)
    return sorted(found)


def _expressions(ctx: _Context, placed: _Placement) -> dict[str, _Expression]:
    """Every net's expression, decided before anything is drawn."""
    obligated = _obligation_nets(ctx)
    out: dict[str, _Expression] = {}
    for net in sorted(ctx.circuit.nets, key=lambda item: item.id):
        points: list[tuple[str, tuple[float, float]]] = []
        for member in sorted(set(net.members) | _sibling_members(ctx, net)):
            part_id, _, token = member.partition(".")
            point = _pin_point(ctx, part_id, token, placed.poses, placed.origins)
            if point is not None:
                points.append((member, point))
        if not points:
            continue
        style, reason = _expression_style(ctx, net.id, net.cls, len(points), obligated)
        detached: tuple[str, ...] = ()
        pivot = ""
        if style == "wire" and _sibling_name_form(ctx, net.id, net.cls):
            detached, pivot = _detached_pins(ctx, net.id, points)
        out[net.id] = _Expression(
            net=net.id, style=style, points=tuple(points), reason=reason,
            detached=detached, pivot=pivot,
        )
    return out


def _power_needs_flag(
    ctx: _Context, net_id: str, symbols: Sequence[LayoutPowerSymbol]
) -> bool:
    """Is this a rail the plan states without a flag of its own? (069 sec.7)

    The ruling: every power net is stated by a power flag inside the module it
    supplies — 岳, finding the 5 V rail on the landed page named by text alone
    (「只有文本没有旗 = 缺陷」). A rail drawn as a *wire* has no flag of its own (053
    sec.7 draws what is local, and this is the one case text was standing in for),
    so the compiler supplies one. Everything else is left exactly as it is: a bus
    expressed by flags at every pin, a single-pin rail, and 069 sec.1's far pad
    brought out to its own flag all already carry one.
    """
    net = ctx.circuit.net(net_id)
    if net is None or net.cls != "power":
        return False
    return not any(symbol.net == net_id for symbol in symbols)


def _power_flag_pin(
    ctx: _Context, expression: _Expression
) -> tuple[str, tuple[float, float]] | None:
    """The pin a rail's own flag goes on: the core's, or the first point there is.

    Which pin is a question about the picture, and a rail belongs to the part it
    *supplies*: 岳 hangs his input flag on VIN itself. The chain's own pin is that
    part's pin, so it wins; a rail whose parts are all branches (nothing it
    supplies) takes its first point by member id, which is the same answer on
    every run.
    """
    ordered = sorted(expression.points)
    for member, point in ordered:
        slot = ctx.slots.get(member.partition(".")[0])
        if slot is not None and slot.kind == "chain":
            return member, point
    return ordered[0] if ordered else None


def _gnd_outlet_nets(ctx: _Context) -> set[str]:
    """The nets their grammar stated an outlet symbol for (088b sec.1).

    Read from the obligations, like every other promise the compiler keeps: the
    grammar decides *that* a group's ground is stated by a symbol of its own, the
    compiler decides where the rail's far end is on the drawing it is making.
    """
    out: set[str] = set()
    for item in ctx.binding.obligations:
        if item.kind == GND_OUTLET:
            out.update(item.nets)
    return out


def _gnd_outlet_pin(
    ctx: _Context, expression: _Expression
) -> tuple[str, tuple[float, float]] | None:
    """The pin the ground's outlet hangs off: the rail's **far** end.

    岳 2026-10-02: the outlet stands at the end away from the inlet — his own
    sheet has the connector on one end and the ground's mark on the other, and
    the flag of the supply rail on the inlet's end (088b sec.1). Which end that
    is comes from `sidePreferences.input` and from the axis the rail actually
    runs along, so the same statement draws the mirrored picture when the inlet
    moves: a rail that runs along x takes its far end on the side the input does
    *not* enter from (unstated or a vertical preference reads as the book's
    default, the input on the left), and a rail that runs along y takes it the
    same way top/bottom. Ties — a rail whose members share the extreme
    coordinate, or a net of one member — are broken by member id, the stable
    tie-break the rest of this package uses.
    """
    points = sorted(expression.points)
    if not points:
        return None
    side = ctx.presentation.side_for("input") or "left"
    xs = [point[0] for _, point in points]
    ys = [point[1] for _, point in points]
    if max(xs) - min(xs) >= max(ys) - min(ys):
        farther = max if side != "right" else min
        at = farther(xs)
        for member, point in points:
            if _close(point[0], at):
                return member, point
    else:
        farther = max if side == "bottom" else min
        at = farther(ys)
        for member, point in points:
            if _close(point[1], at):
                return member, point
    return points[0]


def _sibling_name_form(ctx: _Context, net_id: str, cls: str) -> str:
    """How 069 sec.1 names the pads of a net it splits: ``"flag"`` or ``"label"``.

    A rail is named by its power flag and a ground by the ground flag — the kinds
    the net already has, which is 053 sec.7's own "one style throughout" read for
    a net of that class — and every other net by a label, which no library has to
    carry. ``""`` is the answer for a rail whose flag symbol the library does not
    carry: the two islands 069 makes are joined by a name and nothing else, so
    such a net keeps 060 sec.2's wire rather than being split into halves nothing
    could state.
    """
    if cls in ("power", "gnd"):
        return "flag" if _flag_plan(ctx, net_id, cls)[0] is not None else ""
    return "label"


def _detached_pins(
    ctx: _Context,
    net_id: str,
    points: Sequence[tuple[str, tuple[float, float]]],
) -> tuple[tuple[str, ...], str]:
    """``(pads named at their own stub, the pad that keeps the wire)`` — 069 sec.2.

    The ruling, from 岳's hand drawing: *「相隔较远的两根同属性引脚不要相连，
    引出来打网络标签即可」* — two pads of one role that the body itself separates
    are not joined by a wire. "相隔较远" is 065's own reading of the shape, the
    dot product of the two pads' offsets from the body's centre: they leave the
    body on opposite sides. Each such pad is brought out on a short stub and
    given the same flag, and the net is joined by *name* — 060 sec.2's electrical
    obligation is unchanged, only the form it is drawn in (out of scope: the
    compiler's grammar, the netlist and the readability partition all still see
    one node).

    Which pad keeps the wire is a question about the picture: the one the rest of
    the net already hangs off. 065 sec.1 puts the output capacitor on the pad
    across from the input pin, so the near pad is the one with somewhere to go
    and the far one has nothing but its own name. A net with no other member at
    all has no such anchor: both pads are named and no wire is drawn between them,
    which is 岳's own answer for the pair on its own.

    Pads of one role on **one** side are never touched: they are a short jumper
    apart, and 060 sec.2's wire between them stays exactly as it was.
    """
    by_part: dict[str, list[tuple[str, tuple[float, float]]]] = {}
    for member, point in points:
        by_part.setdefault(member.partition(".")[0], []).append((member, point))
    detached: list[str] = []
    pivot = ""
    for part_id in sorted(by_part):
        entries = by_part[part_id]
        if len(entries) < 2:
            continue
        offsets = _body_offsets(ctx, part_id, [item[0] for item in entries])
        if len(offsets) < 2:
            continue
        across = {
            member for member, _ in entries
            if member.partition(".")[2] in offsets
            and any(
                other != member and other.partition(".")[2] in offsets
                and _dot(
                    offsets[member.partition(".")[2]], offsets[other.partition(".")[2]]
                ) < 0.0
                for other, _ in entries
            )
        }
        if not across:
            # Every pad of this role leaves the body the same way (or at right
            # angles): there is no pair the part sits between, so 060 sec.2's own
            # drawing stands, wire and all.
            continue
        others = [item for item in points if item[0].partition(".")[0] != part_id]
        if not others:
            detached.extend(sorted(across))
            continue
        keeper, _ = min(
            entries,
            key=lambda item: (
                min(
                    math.hypot(item[1][0] - other[0], item[1][1] - other[1])
                    for _, other in others
                ),
                item[0],
            ),
        )
        keeper_token = keeper.partition(".")[2]
        if keeper_token not in offsets:
            continue
        far = [
            member for member in sorted(across)
            if member != keeper
            and _dot(
                offsets[member.partition(".")[2]], offsets[keeper_token]
            ) < 0.0
        ]
        if not far:
            continue
        detached.extend(far)
        pivot = keeper
    return tuple(detached), pivot


def _body_offsets(
    ctx: _Context, part_id: str, members: Sequence[str]
) -> dict[str, tuple[float, float]]:
    """``pin token -> its tip seen from the body's centre``, in symbol terms.

    Read in the symbol's own frame, exactly as :func:`_opposite_side_token` does:
    a pose is a rotation and a mirror about the part's origin, and both keep dot
    products, so "across the body" is the same statement in every pose the symbol
    may be drawn in.
    """
    profile = ctx.profile(part_id)
    if profile.body is None:
        return {}
    box = profile.body
    centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
    out: dict[str, tuple[float, float]] = {}
    for member in members:
        token = member.partition(".")[2]
        pin = _pin_of_token(profile, token)
        if pin is not None:
            out[token] = (pin.tip[0] - centre[0], pin.tip[1] - centre[1])
    return out


def _sibling_members(ctx: _Context, net: Any) -> set[str]:
    """Pins this net is on although the spec did not spell them out (060 sec.2).

    The ruling: a role's several pins are **one node inside the symbol**, so a
    spec that puts one of them on a net puts the role there, and the drawing
    expresses the rest of them as well — wired to it, or (069 sec.2, when the body
    separates them) brought out on their own stub under the same flag. Two
    exceptions, both the spec's own words:

    * a pin listed in ``nc[]`` is an explicit no-connect and stays off the net
      ("nc 降为显式例外");
    * a pin the spec puts on *another* net is the contradiction the grammar
      refuses as `circuit-invalid` (one role, two nets) — nothing is invented for
      it here, because inventing a connection would hide the refusal.

    The rule itself is `core.symbolprofile.role_siblings`, so the readability
    checker's own expectation of this node is computed from the same definition.
    """
    extra: set[str] = set()
    for member in sorted(net.members):
        part_id, _, token = member.partition(".")
        part = ctx.circuit.part(part_id)
        profile = ctx.book.get(part.symbol_ref) if part is not None else None
        if profile is None:
            continue
        nc = nc_pins_of(ctx.circuit, part_id)
        declared = _part_nets(ctx.circuit, part_id)
        for pin in role_siblings(profile, token):
            spelling = pin.number or pin.name
            if not spelling or spelling in nc:
                continue
            here = declared.get(spelling, declared.get(pin.name, ""))
            if here and here != net.id:
                continue
            extra.add(f"{part_id}.{spelling}")
    return extra - set(net.members)


def _expression_style(
    ctx: _Context, net_id: str, cls: str, count: int, obligated: set[str]
) -> tuple[str, str]:
    """``(style, why)`` for one net — the policy of 053 sec.7, spelled out.

    The order of the questions is the order of the priorities: a promise first
    (a `direct-wire` obligation is never downgraded to a name), then the net's
    own class, then the label policy the presentation states.
    """
    modules = _net_modules(ctx, net_id)
    policy = ctx.presentation.label_policy
    if count == 1:
        if cls in ("power", "gnd") or net_id in obligated:
            return (
                "flag",
                "a single-pin net is named by its flag at the pin: a rail or a "
                "ground end is a name, and one pin has nothing to be wired to",
            )
        return (
            "label",
            "a single-pin net has no partner on the page; it is named by a label "
            "at the pin, which is what an open interface is",
        )
    if net_id in obligated:
        return (
            "wire",
            "the grammar's direct-wire obligation (or the presentation's "
            "directWiringObligations) promises this net as a wire — 053 sec.7: a "
            "local topology is drawn, and a promise is never downgraded to a name",
        )
    if cls == "gnd":
        return (
            "flag",
            "ground is expressed one way throughout (053 sec.3's uniform-gnd): "
            "every member of this net gets the same flag",
        )
    if cls == "power":
        if count > ctx.budget.high_fanout:
            return (
                "flag",
                f"a rail with {count} members is a bus, not a local connection: "
                f"above {ctx.budget.high_fanout} members it is expressed with its "
                "flag at every pin (053 sec.7: labels wait for high fan-out)",
            )
        return (
            "wire",
            f"a rail with {count} members is a local connection, so it is wired "
            "rather than named",
        )
    if len(modules) > 1 and policy.cross_module == LABEL_LABEL:
        return (
            "label",
            "this net crosses the module boundary between "
            + " and ".join(modules)
            + " and labelPolicy.crossModule is 'label' (053 sec.7)",
        )
    if count > ctx.budget.high_fanout and policy.high_fanout == LABEL_LABEL:
        return (
            "label",
            f"this net has {count} members, above the high-fan-out threshold "
            f"({ctx.budget.high_fanout}), and labelPolicy.highFanout is 'label'",
        )
    return (
        "wire",
        "a local signal topology is drawn as a wire (labelPolicy.local is 'wire' "
        "by contract, 053 sec.2/7)",
    )


# --------------------------------------------------------------- annotations


def _overlaps(left: Box, right: Box) -> bool:
    """Do two boxes share area? Strict, so touching edges are not an overlap."""
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > 0.0
        and min(left[3], right[3]) - max(left[1], right[1]) > 0.0
    )


def _line_boxes(part: Box, lines: Sequence[str], side: str, rung: int = 1) -> list[Box]:
    """Where a part's text lines go when put on `side` of its box, ``rung`` out.

    One line per string, stacked in reading order; the block is centred on the
    part's own centre along the side it takes, and offset off the box by
    :data:`TEXT_GAP` per ``rung`` (117②). Both lines of a part's text stay
    together on one side: a reference on one side and a value on the other reads
    as two unrelated texts.
    """
    width = max(text_width(line) for line in lines)
    height = len(lines) * TEXT_LINE_STEP
    cx = (part[0] + part[2]) / 2.0
    cy = (part[1] + part[3]) / 2.0
    gap = TEXT_GAP * rung
    out: list[Box] = []
    for index, line in enumerate(lines):
        if side == "right":
            x = part[2] + gap + text_width(line) / 2.0
            y = cy + height / 2.0 - TEXT_LINE_STEP * (index + 0.5)
        elif side == "left":
            x = part[0] - gap - text_width(line) / 2.0
            y = cy + height / 2.0 - TEXT_LINE_STEP * (index + 0.5)
        elif side == "above":
            x = cx - width / 2.0 + text_width(line) / 2.0
            y = part[3] + gap + height - TEXT_LINE_STEP * (index + 0.5)
        else:
            x = cx - width / 2.0 + text_width(line) / 2.0
            y = part[1] - gap - height + TEXT_LINE_STEP * (index + 0.5)
        out.append(font_text_box(line, x=x, y=y))
    return out


def _part_lines(ctx: _Context, part_id: str) -> tuple[tuple[str, str], ...]:
    """``(kind, text)`` for every line a part prints: reference, then value.

    The one home for "what a part's text says" (097): the placement prints these
    lines (:func:`_part_texts`) and the anchor reserves room for them
    (:func:`_annotation_allowance`) — a second copy would let the reserved width
    and the printed width disagree, which is the whole of 096's 4-unit shortfall.
    A part with no value prints one line; the reference is its own spec id.
    """
    part = ctx.circuit.part(part_id)
    if part is not None and part.value:
        return (("reference", part_id), ("value", part.value))
    return (("reference", part_id),)


def _declared_rows(
    ctx: _Context,
    part_id: str,
    profile: SymbolProfile,
    pose: SymbolPose,
    origin: tuple[float, float],
) -> list[tuple[str, str, Box]]:
    """``(kind, text, box)`` at the anchors this **symbol** declares (146).

    The compiler used to invent a side for a part's reference and value
    (:func:`_part_texts`'s ladder below) while the host draws them where the
    symbol's own text items sit — a fixed per-symbol anchor that moves with the
    pose and is *not* a free choice. The two models disagreed about most of the
    page (measured 2026-10-10 on `test/P1`: R3's value is drawn at
    ``(50, 665)``, not the compiler's ``(88, 668)``; T1's at ``(180, 670)``, not
    ``(248, 694)``), and the disagreement was not academic: the *fictional* box
    is what `_span_free` refuses wires against, so C11's straight drop onto the
    SEC_12V rail was bent sideways by the compiler's imagined C13 value row
    (probe: ``span_free (500,640)->(500,710)`` blocked by box
    ``(448, 648.5, 517.5, 657.5)``, which the host draws nowhere).

    The anchors come from :attr:`SymbolProfile.texts` — the schema always had
    the slot (:class:`SymbolText`: "one piece of text the symbol itself places");
    what was missing was the measurement, which the 145e render supplies. The
    anchor is the drawn row's **lower-left corner** and the row is
    :data:`TEXT_ROW_HEIGHT` tall.

    147 re-measured *where* the anchor sits, because 146 put it through the
    part's pose and the host does not: the offset is from the part's **origin in
    the page frame** (see the comment at the fold below and
    `outputs/147/20_text_row_pose.txt`). Two profiles' anchors were restated in
    that frame (``C0603W``, ``SMD-4-PC817``, both measured off the one placed
    part that has them), and the quarter-turn part C13 is now modelled where it
    is drawn rather than 25 units away.

    The width is the **render's** own ruler
    (:func:`boardwise.core.textmetrics.render_width`, the same table `drawlint`
    measures the landed page with), because these rows are the host's own text:
    a box that claims to be where the host paints has to be the host's box. The
    compiler's own :func:`text_width` is deliberately wider — it reserves room
    for the text *this compiler* places — and using it here measures
    `17.8k 1% TH` + `4.7k 1% 0603` (R7's and R8's value rows) as 73 + 78 units
    with 13 units of overlap, where the host draws them 57.8 + 61.1 units apart
    and the whole page was refused as `text-overlap` for a collision no reader
    can see.

    An empty list means the symbol declares no row — every symbol profile
    written before 146 — and the caller keeps the old ladder, so a library
    without measurements compiles exactly as it did.
    """
    out: list[tuple[str, str, Box]] = []
    for declared in profile.texts:
        if declared.x is None or declared.y is None:
            continue
        if declared.kind == "reference":
            text = part_id
        elif declared.kind == "value":
            part = ctx.circuit.part(part_id)
            text = part.value if part is not None else ""
        else:
            continue
        if not text:
            continue
        # 147: the anchor is an offset from the part's **origin in the page
        # frame** — the host does not turn a part's text rows with the pose. Three
        # pose families on the landed page say so (`outputs/147/20_text_row_pose.txt`,
        # 33 rows of 19 parts): R10 at rot 180 is drawn at `(740, 425)`, the
        # unrotated anchor, where a turned anchor puts it at `(760, 415)`; U5 at
        # rot 180 likewise; C13 at rot 90 mirrored at `(435, 660)` where turning
        # says `(410, 670)`. 146 modelled the turn and flagged the quarter-turn
        # case as an extrapolation; the measurement says the whole turn is absent.
        anchor = (origin[0] + declared.x, origin[1] + declared.y)
        width = textmetrics.render_width(text)
        out.append((
            declared.kind,
            text,
            (anchor[0], anchor[1], anchor[0] + width,
             anchor[1] + TEXT_ROW_HEIGHT),
        ))
    return out


def _part_texts(
    ctx: _Context, placed: _Placement, occupied: list[Box], walls: list[Box]
) -> list[LayoutText]:
    """The reference and value of every placed part, at the anchor it draws at.

    A part whose symbol declares its own text anchors (146,
    :func:`_declared_rows`) gets exactly those rows: the host draws them there
    whatever the compiler wants, so the honest model is to *read* them and let
    the router route around them — they go into `occupied` and `walls` like
    every other text, and the readability checker then measures the page the
    host will actually draw.

    A part whose symbol declares nothing keeps the old behavior, and the
    docstring below still describes it.

    The rest of this comment is the pre-146 contract for the fallback path.
    `occupied` is the list of boxes already on the page (part extents, keep-outs
    and earlier texts) and is extended as the texts land. The side ladder is
    tried in order and the first free one wins; when no side is free the text is
    placed anyway at the first side, and the hard gate then refuses the whole
    candidate — text is never shrunk to fit (053 sec.5 scenario 10).

    **What decides a side is `walls`, not `occupied`** (099b): keep-outs, the
    *drawn body* of every other part, and the texts placed so far — plus, for
    this part's own text, its own full extent (`box`). A part's `_part_box`
    includes its pin tips, and a pin tip is not something that is drawn: reading
    it as a wall let 1.5 units of empty bounding-box corner push a core's
    reference onto the side where its own pin labels had to go (measured on the
    099 CH340 sample, where that one unit decided the whole page). The part's own
    extent keeps the old strictness for its own text, which is the reason the
    tips were put in `occupied` at all ("so a value never prints across its own
    pins").
    """
    out: list[LayoutText] = []
    for part_id in sorted(placed.origins):
        profile = ctx.profile(part_id)
        box = _part_box(profile, placed.poses[part_id], placed.origins[part_id])
        declared = _declared_rows(
            ctx, part_id, profile, placed.poses[part_id], placed.origins[part_id]
        )
        if declared:
            for kind, text, item in declared:
                occupied.append(item)
                walls.append(item)
                out.append(LayoutText(
                    kind=kind,
                    text=text,
                    bbox=item,
                    part_id=part_id,
                    x=(item[0] + item[2]) / 2.0,
                    y=(item[1] + item[3]) / 2.0,
                ))
            continue
        lines = list(_part_lines(ctx, part_id))
        blocked = [*walls, box]
        chosen = None
        # Each side is tried at :data:`TEXT_ESCALATION_STEPS` distances, not one
        # (117②). A single rung is often occupied while the second is free — the
        # flyback's 385-unit `EE16_3+3_V02 (…)` value is the measured case, its
        # own designator sitting on it. Falling back to `TEXT_SIDES[0]` is still
        # the honest last resort: the gate refuses the candidate rather than the
        # text being squeezed (053 sec.5 scenario 10).
        for rung in range(1, TEXT_ESCALATION_STEPS + 1):
            for side in TEXT_SIDES:
                boxes = _line_boxes(box, [text for _, text in lines], side, rung)
                if all(
                    not _overlaps(candidate, other)
                    for candidate in boxes for other in blocked
                ):
                    chosen = boxes
                    break
            if chosen is not None:
                break
        if chosen is None:
            chosen = _line_boxes(box, [text for _, text in lines], TEXT_SIDES[0])
        for (kind, text), item in zip(lines, chosen):
            occupied.append(item)
            walls.append(item)
            out.append(LayoutText(
                kind=kind,
                text=text,
                bbox=item,
                part_id=part_id,
                x=(item[0] + item[2]) / 2.0,
                y=(item[1] + item[3]) / 2.0,
            ))
    return out


def _label_for(
    ctx: _Context,
    net_id: str,
    part_id: str,
    token: str,
    point: tuple[float, float],
    placed: _Placement,
    occupied: list[Box],
) -> LayoutLabel:
    """A label on a pin tip, its box put where it collides with nothing.

    The pin's own escape direction is the preferred way out, which is what keeps
    a label off the part it names. The label carries the pin's **owner** — the
    part this label names a pin of — so the readability contract can tell a
    label printed over the edge of its own symbol (that symbol's own text) from
    one printed over somebody else's (099b, `LayoutLabel.part_id`).
    """
    direction = _pin_direction(ctx, part_id, token, placed.poses)
    if direction is None:
        direction = ctx.lateral()
    return _label_at(net_id, point, direction, occupied, part_id=part_id)


def _label_at(
    net_id: str,
    point: tuple[float, float],
    preferred: tuple[float, float],
    occupied: list[Box],
    *,
    part_id: str = "",
) -> LayoutLabel:
    """A label whose *anchor* is fixed and whose *box* moves around it.

    The anchor is the electrical fact — a label joins the node it touches, so it
    stays where it is; the box is typography, so it is tried in four directions
    and the first free one wins. Both live in `LayoutLabel` for exactly this
    reason, and the box is the font-metric box for the net's name.

    **A box that collides with everything falls back to the preferred direction**
    (099b) — the side the pin itself escapes by — and never to a box centred on
    the anchor. The centred box always straddles the symbol it names, and on a
    compact symbol (a pin tip less than half a label-width from the drawn body)
    it is the *only* placement that does; the outward one at least reads as a
    label beside its pin, and the readability contract exempts the overlap it
    may have with that one symbol (its own). The centred path stays written down
    as unreachable: reaching it would mean the four directions were never built.

    **Each direction is tried at :data:`TEXT_ESCALATION_STEPS` distances, not
    one** (117②). One offset is a single rung of :data:`TEXT_GAP`, and a long
    net name beside a dense cluster routinely has that rung occupied while the
    second and third are free — so the first version fell back into a collision
    the checker then refused. Widening the search is the cure; the bound is
    what stops a name being flung off the pin that gives it meaning.
    """
    box = None
    fallback = None
    half_x = text_width(net_id) / 2.0 + TEXT_GAP
    half_y = TEXT_SIZE / 2.0 + TEXT_GAP
    for candidate_direction in _directions(preferred):
        for rung in range(1, TEXT_ESCALATION_STEPS + 1):
            reach = rung - 1
            if candidate_direction[0] != 0.0:
                offset = (candidate_direction[0] * half_x * rung, 0.0)
            else:
                offset = (0.0, candidate_direction[1] * half_y * rung)
            candidate = font_text_box(
                net_id, x=point[0] + offset[0], y=point[1] + offset[1]
            )
            if fallback is None:
                fallback = candidate
            if all(not _overlaps(candidate, other) for other in occupied):
                box = candidate
                break
        if box is not None:
            break
    if box is None:
        box = fallback if fallback is not None else font_text_box(
            net_id, x=point[0], y=point[1] + TEXT_SIZE / 2.0 + TEXT_GAP
        )
    occupied.append(box)
    return LayoutLabel(
        net=net_id, text=net_id, bbox=box, x=point[0], y=point[1], part_id=part_id,
    )


def _directions(preferred: tuple[float, float]) -> list[tuple[float, float]]:
    """The preferred direction first, then the rest of the compass."""
    all_directions = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
    ordered = [preferred] + [
        item for item in all_directions if item != preferred
    ]
    return ordered


def _tap_stub(
    ctx: _Context,
    placed: _Placement,
    expression: _Expression,
    router: _Router,
    segments: list[LayoutSegment],
    labels: list[LayoutLabel],
    occupied: list[Box],
    solids: list[Box],
    blocked: set[tuple[float, float]],
) -> str:
    """Draw a tap's stub and put its label at the end — 053 sec.3's "直接可见".

    The stub leaves the junction between the two chain arms and runs along the
    axis the grammar's `horizontal-tap`/`vertical-tap` names, past every branch
    root that hangs on the same node, so the tap can be read *and* named without
    following a wire into another module. The label is the net's own name; the
    junction the stub tees into is declared by :func:`_junctions`.

    Returns a note: what was drawn, or why not — a tap that could not be stubbed
    is not hidden, it comes back as a grammar finding on the plan.
    """
    axis = _tap_axis_by_net(ctx.circuit, ctx.binding).get(expression.net, "x")
    junction = _tap_junction(ctx, expression.net, placed.poses, placed.origins)
    if junction is None:
        return "no junction found on the chain, so no stub was drawn"
    reach = ctx.budget.stub
    for member, point in expression.points:
        part_id, _, _token = member.partition(".")
        if ctx.slots.get(part_id) is not None and ctx.slots[part_id].kind == "chain":
            continue
        distance = (point[0] - junction[0]) if axis == "x" else (point[1] - junction[1])
        if distance > 0.0:
            reach = max(reach, distance + ctx.budget.stub)
    for sign in (1.0, -1.0):
        direction = (sign, 0.0) if axis == "x" else (0.0, sign)
        end = _rounded((
            junction[0] + direction[0] * reach,
            junction[1] + direction[1] * reach,
        ))
        if not _span_free(router, junction, end, blocked - {_key(junction)}):
            continue
        segments.append(LayoutSegment(net=expression.net, points=[junction, end]))
        label = _label_at(expression.net, end, direction, occupied)
        labels.append(label)
        solids.append(label.bbox)
        horizontal = "right" if sign > 0 else "left"
        vertical = "up" if sign > 0 else "down"
        return (
            f"tap stub {reach:g} units "
            f"{horizontal if axis == 'x' else vertical} with the net's label at "
            "its end (053 sec.3: 抽头直接可见)"
        )
    return (
        "no free direction for the tap stub: both sides of the junction are "
        "blocked, so the tap stays unnamed (a grammar finding on this plan)"
    )


def _flag_rotation(direction: tuple[float, float], kind: str) -> float:
    """The rotation the **editor** is given so the flag **stands upright**.

    069 sec.7 — 岳, reading the landed P23 page: 「旗标一定要竖直摆放不能平放影响观感」
    — so this answers **0 or 180** and nothing else, and 053B's compass (which
    turned a flag sideways for a horizontal lead) is retired. His own AMS1117
    drawing is the same statement: every ``Power-VCC`` there is 0 and every ground
    0 or 180, because every flag is reached by a *vertical* run — a horizontal
    stub turns a short way up or down first (:func:`_flag_anchor`).

    Which of the two is still 064's table, unchanged: at rotation 0 a ground's
    bars hang *below* their connection point (``Ground-GND``, ``BBOX (-10, 0, 10,
    -19)``) and a rail's bar stands *above* its own (``Power-VCC`` / ``Power-5V``,
    ``(-5, 10, 5, 0)``), so the number that hangs the glyph *away* along
    ``direction`` is the ground's 180 and the rail's 0 — the family offset
    (:data:`~boardwise.core.symbolprofile.FLAG_GLYPH_ROTATION_OFFSETS`) added to a
    base of 0 for an upward hang and 180 for a downward one. That shared offset is
    the point: the box ``flag_glyph_box`` reserves comes from the *same* number, so
    a rotation that turned a different amount would reserve room on the wrong side
    of the glyph (060's bug, both families; 064's fix, both families).

    ``direction`` is therefore the way the glyph must hang — ``+y`` up, ``-y``
    down. The compiler's own placement only ever passes those two (a horizontal
    lead is bent first). A horizontal one is still answered, because the page layer
    calls this for a port on a vertical module boundary: there the family's
    natural hang is the answer — a rail lifts, a ground hangs down.
    """
    if direction[1] != 0.0:
        up = direction[1] > 0.0
    else:
        up = kind != FLAG_GLYPH_KIND_GND
    base = 0.0 if up else 180.0
    return (base + FLAG_GLYPH_ROTATION_OFFSETS[kind]) % 360.0


def _flag_plan(
    ctx: _Context, net_id: str, cls: str
) -> tuple[SymbolProfile | None, str]:
    """``(flag profile, symbol ref)`` — the library's rail/ground flag for this net.

    The ref is derived from the net, not from a scenario: the ground flag is the
    budget's `gnd_flag`, a rail's is `power_flag_prefix` + the net id. A library
    that does not carry it is not a failure — the net falls back to being
    *wired* (:func:`_flag_wire_fallback`), which is what this host can express;
    `uniform-gnd` is what checks that one net does not end up mixing two styles.

    The docstring used to end "the net is then expressed with a label", and that
    sentence was the F1 defect written down as a design: this host cannot place a
    netlabel (029), so a label-only expression left a multi-pin net with **no
    conductor on the canvas** while the plan's own verdict said `pass`.
    """
    ref = ctx.budget.gnd_flag if cls == "gnd" else f"{ctx.budget.power_flag_prefix}{net_id}"
    return (ctx.book.get(ref), ref)


def _net_class(ctx: _Context, net_id: str) -> str:
    """The CircuitSpec's class for a net (``""`` when the net is unknown)."""
    net = ctx.circuit.net(net_id)
    return net.cls if net is not None else ""


def _missing_flag_symbol(ctx: _Context, net_id: str) -> bool:
    """Is this net a flag-style net whose flag symbol the library does not carry?

    Read through :func:`_flag_plan`, so the answer is the same one the flag
    expression and 069 sec.6's rail-flag pass use: `gnd_flag` for a ground and
    `power_flag_prefix + net` for a rail.
    """
    profile, _ref = _flag_plan(ctx, net_id, _net_class(ctx, net_id) or "gnd")
    return profile is None


def _flag_wire_fallback(
    ctx: _Context, net_id: str, expression: _Expression
) -> tuple[_Expression, str]:
    """The wire expression for a flag net the library has no symbol for (143 F1).

    The fallback is a **wire**, not a label, and the difference is not cosmetic:
    a label is a conductor in this compiler's offline model (that is how
    `readability.derive_netlist` reads the plan) but the host has no way to place
    one — 029 measured `sch.place_netlabel` unusable, and `draw apply` writes
    `draw_wires` and `draw_flags` and nothing else. A multi-pin net drawn as
    labels alone is therefore a net the editor sees as several unnamed islands:
    the plan's verdict reads `pass`, `drawapply._postconditions` promises "the
    editor's own netlist holds these pins as one net", and no landing can ever
    satisfy it. 121c's delivered plan is exactly this — `PGND` with 5 members and
    0 segments, 0 flags (143's F1 witness, measured on the artifact).

    A wire carries the net's own name in this host (`sch.place_wire` net=…,
    029-c), so the netlist gets the name and the pins are one node. The
    expression keeps `detached`/`pivot`, so 069 sec.2's split form still applies
    (the rest of the net is wired; the pads the body separates are named at their
    own stubs).

    The note it returns carries :data:`DOWNGRADE_NOTE_PREFIX`, which is how the
    degradation reaches the change plan's ``downgrades`` list — the reader who
    authorises the plan is told they did not get a flag.
    """
    cls = _net_class(ctx, net_id) or "gnd"
    _profile, ref = _flag_plan(ctx, net_id, cls)
    downgraded = _Expression(
        net=expression.net,
        style="wire",
        points=expression.points,
        reason=(
            f"the library carries no flag symbol {ref!r} for this {cls}-class"
            f" net, so it is drawn as a wire instead: the wire states the net's "
            "name in the editor's own netlist (`sch.place_wire` net=…), which is "
            "the only expression this host can carry out, and a label would name "
            "the net nowhere (029)"
        ),
        detached=expression.detached,
        pivot=expression.pivot,
    )
    note = (
        DOWNGRADE_NOTE_PREFIX
        + f"net {net_id}: its class says it is expressed by a flag, and the "
        f"library carries no flag symbol {ref!r} — the net is drawn as a wire "
        f"instead, with the net's name on the wire itself, and it keeps "
        f"{len(expression.points)} pin(s). The drawing you are authorising has "
        "no flag for this net"
    )
    return downgraded, note


def _compress(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Collapse collinear runs, so a wire's vertices are its bends.

    Not cosmetic: the readability checker treats a *vertex* of one wire lying
    inside another wire's span as a tee that needs a junction, while a proper
    crossing is not a connection at all. Compressing the straight runs is what
    makes a perpendicular crossing a crossing rather than an accidental join.
    """
    out: list[tuple[float, float]] = []
    for point in points:
        point = _rounded(point)
        if out and _key(out[-1]) == _key(point):
            continue
        out.append(point)
    changed = True
    while changed and len(out) > 2:
        changed = False
        trimmed: list[tuple[float, float]] = [out[0]]
        for index in range(1, len(out) - 1):
            before, here, after = trimmed[-1], out[index], out[index + 1]
            same_axis = (
                _close(before[0], here[0]) and _close(here[0], after[0])
            ) or (_close(before[1], here[1]) and _close(here[1], after[1]))
            if same_axis:
                changed = True
                continue
            trimmed.append(here)
        trimmed.append(out[-1])
        out = trimmed
    return out


# ------------------------------------------------------- stage 3c: the plan


@dataclass(frozen=True)
class _Variant:
    """One point of the finite search: a ladder rung and a pose index."""

    label: str
    scale: float
    pose_index: int


def _variants(ctx: _Context) -> list[_Variant]:
    """The finite search space: ``grid ladder x finite poses``, stably ordered.

    The ladder is the outer loop because room is what fixes a crowded drawing,
    and a pose is only ever varied when the accepted set really has more than one
    geometry. The product is truncated at `budget.max_candidates` in a fixed
    order, so two runs of one input search the same points in the same sequence.
    """
    choices = max(
        (1, *(len(poses) for poses in ctx.accepted.values() if poses))
    )
    variants: list[_Variant] = []
    for scale in ctx.budget.spacing_ladder:
        for index in range(min(choices, 2)):
            variants.append(_Variant(
                label=f"spacing={scale:g} pose-variant={index}",
                scale=float(scale),
                pose_index=index,
            ))
            if len(variants) >= ctx.budget.max_candidates:
                return variants
    return variants


def _try_variants(
    ctx: _Context,
    variants: Sequence[_Variant],
    result: CompileResult,
    seen: set[str],
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    book: Mapping[str, SymbolProfile],
    budget: CompileBudget,
    intent: Any,
) -> None:
    """Build each variant, gate it, and record it — one variant, one verdict.

    Factored out of :func:`compile` by 119 so the widened round runs the **same**
    code over its own variants: a second copy of this loop would be a second set
    of rules for what counts as a candidate, and 119's whole claim is that the
    widened round is the same compiler on a wider ladder, not a different one.

    147b stops the ladder at a **rung boundary** when more room cannot change the
    answer — see :func:`_rung_reproduces`. The one precondition that matters is
    "no candidate has been found yet", so every input this compiler can already
    draw searches exactly the variants it searched before.
    """
    previous_rung: dict[int, tuple] = {}
    this_rung: dict[int, tuple] = {}
    scale: float | None = None
    rungs_done = 0
    for variant in variants:
        if scale is not None and variant.scale != scale:
            rungs_done += 1
            if not result.ranked and _rung_reproduces(previous_rung, this_rung):
                result.notes.append(
                    f"the spacing ladder stopped at rung {variant.scale:g}x: the "
                    f"{rungs_done} rung(s) built were refused exactly alike "
                    f"({_rung_summary(this_rung)}) and more room does not move a "
                    "conflict that is structural (147b), so the rung(s) after "
                    f"{scale:g}x were not built — `not found inside the budget` "
                    "stays the claim this compiler makes"
                )
                return
            previous_rung, this_rung = this_rung, {}
        scale = variant.scale
        built, failure, violations = _build_candidate(ctx, variant)
        if built is None:
            this_rung[variant.pose_index] = _refusal_signature(violations, failure)
            result.rejected.append(RejectedCandidate(
                variant=variant.label,
                reason=failure.detail if failure is not None else "no legal layout",
                violations=violations,
                failure=failure,
            ))
            continue
        plan = built.plan
        digest = plan.geometry_sha256()
        if digest in seen:
            # Two variants with the same geometry are one drawing: a symbol whose
            # legal poses produce identical pins has only one picture, and the
            # plan's own geometry digest is what says so (052 sec.4).
            this_rung[variant.pose_index] = ("same-geometry",)
            result.rejected.append(RejectedCandidate(
                variant=variant.label,
                reason="the same geometry as an earlier variant",
            ))
            continue
        seen.add(digest)
        findings = check_grammar(
            plan, circuit_spec, presentation_spec, book, budget=budget, intent=intent
        )
        plan.evidence = LayoutEvidence(
            checker=CHECKER_NAME,
            hard_violations=[
                item.render() for item in built.checked.hard_violations
            ],
            grammar_findings=[item.render() for item in findings],
            soft_metrics=dict(built.checked.soft_metrics),
            soft_reasons={
                key: " | ".join(value)
                for key, value in built.checked.soft_reasons.items()
            },
            notes=[f"candidate from {COMPILER_NAME} variant {variant.label}"],
        )
        result.ranked.append(_measure(plan, findings, ctx))


#: The prefix of every signature that may stop the spacing ladder (147b): a
#: refusal by the **readability gate**. Every other answer — "no path inside the
#: region", "no legal pose", a relation the ladder has not tried yet — is one that
#: more room *can* change, so the ladder keeps walking those to its end.
GATE_SIGNATURE = "gate"


def _refusal_signature(
    violations: Sequence[str], failure: GrammarFailure | None
) -> tuple:
    """What one variant was refused for, with the coordinates taken out (147b).

    ``violations`` are the gate's rendered lines (``[kind] objects: evidence``);
    the signature keeps ``[kind] objects`` and drops the evidence, because the
    evidence carries the coordinates the spacing ladder moves on purpose. Two rungs
    that refuse the *same objects for the same reason* are the same structural
    conflict; two that merely agree on the kind are not — that is the difference
    between "this wire crosses that flag" and "these drawings are crowded
    differently".

    A non-gate refusal is ``(category, subject)``, which never satisfies
    :func:`_rung_reproduces` (see :data:`GATE_SIGNATURE`): the ladder may not stop
    on a reason more room can fix.
    """
    if violations:
        return (
            GATE_SIGNATURE,
            tuple(sorted(line.split(": ", 1)[0] for line in violations)),
        )
    if failure is not None:
        return (failure.category, failure.subject or "")
    return ("", "")


def _rung_reproduces(
    previous: dict[int, tuple], current: dict[int, tuple]
) -> bool:
    """Did this rung refuse **every** pose exactly as the rung before it did?

    Three conditions, each load-bearing:

    * the two rungs cover the same poses — a rung that did not get to build a pose
      it has no verdict for says nothing about that pose;
    * every verdict is a **gate** refusal (:data:`GATE_SIGNATURE`). Room is the
      ladder's own remedy for a routing or lattice refusal and for nothing else,
      so those keep their full walk;
    * the per-pose signatures are equal. A rung that refuses *fewer* things than
      the one before it is a rung where room helped, and the ladder must go on.

    The caller adds the fourth condition, and it is the strongest one: no
    candidate has been found yet. So a ladder that has drawn something is never
    cut short, and every input this compiler can already draw searches exactly the
    variants it searched before 147b.
    """
    if not previous or not current or set(previous) != set(current):
        return False
    if any(signature[0] != GATE_SIGNATURE for signature in current.values()):
        return False
    return all(current[pose] == previous[pose] for pose in current)


def _rung_summary(rung: dict[int, tuple]) -> str:
    """The refusal kinds this rung repeated, for the note the reader sees."""
    kinds = sorted({
        head.split("] ", 1)[0].lstrip("[")
        for _kind, heads in rung.values()
        for head in heads
    })
    return ", ".join(kinds) if kinds else "no violation named"


#: The relation kinds a widening can answer, and the only ones it is allowed to
#: be triggered by.  A refusal that is **not** one of these — a routing failure, a
#: lattice failure, a readability refusal — is some other subsystem's answer, and
#: a pose the ladder has not drawn yet is not a way to overrule it.
WIDENABLE_KINDS: tuple[str, ...] = (
    ABOVE, BELOW, LEFT_OF, RIGHT_OF, SAME_ROW, SAME_COLUMN, NEAR,
)


def _refusing_relation(failure: GrammarFailure | None) -> tuple[str, str, str] | None:
    """The ``(kind, subject, object)`` a placement refusal names, or ``None``.

    Read off the failure's own ``detail`` rather than a new predicate, so what
    triggers the widening is exactly the text the compiler already shows the
    reader. A refusal this cannot read — the router, the lattice, the region —
    returns ``None`` and therefore never triggers it.
    """
    if failure is None or failure.category != FAILURE_PRESENTATION_POOR:
        return None
    detail = failure.detail
    marker = "the relation "
    start = detail.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = detail.find("(", start)
    close = detail.find(")", end + 1)
    if end < 0 or close < 0:
        return None
    kind = detail[start:end]
    if kind not in WIDENABLE_KINDS:
        return None
    subject, _, obj = detail[end + 1:close].partition(", ")
    return (kind, subject.strip(), obj.strip())


def _widening_blocker_label(result: CompileResult) -> str:
    """The one relation every base refusal named, for the note the reader sees."""
    named = {
        relation for relation in (
            _refusing_relation(item.failure) for item in result.rejected
        ) if relation is not None
    }
    if not named:
        return "a relation this pass cannot name"
    first = sorted(named)[0]
    return f"{first[0]}({first[1]}, {first[2]})"


def _widened_variants(
    ctx: _Context, result: CompileResult
) -> list[_Variant]:
    """The pose ladder past rung 1 — for one situation only, and never beyond.

    :func:`_variants` explores ``pose_index`` 0 and 1.  That is a deliberate
    bound, and 116 §三 wrote down why it must not be widened on sight: a core with
    four rotations may have one that happens to satisfy a relation while the
    compilation only ever draws rungs 0 and 1, so a pass that consulted the whole
    accepted set stood aside for a drawing that was never going to be made.  The
    question is not "does some rotation exist" but "does a rotation **this
    compiler is going to draw** exist".

    119's answer is that the two rungs and the rest of the set are different
    questions, and the second one is only worth asking when the first has
    already failed the whole input.  The condition, in full:

    * **no candidate survived.** This is what makes the path **structurally the
      identity on every input that compiles** — the widened round is unreachable
      unless the base ladder produced nothing, so every drawing this compiler
      can already make is byte-for-byte what it was before.  That is the whole
      of the zero-move argument, and it is a property of *where* the call sits,
      not of what the call does, so it does not depend on the shape of any
      particular input.
    * **every refusal names the same relation.** If the rungs disagree about why
      they failed, the page is not "one rung short" — it is a page whose parts
      fight each other in several ways at once, and which of those a rotation
      fixes is a question with no answer here.  The flyback is the case this was
      written for: all six rungs were refused by ``same-column(Q1, R5)`` and
      nothing else in common, and 118 measured that ``R5`` at rotation 90 puts its
      ``SRC`` pad back in ``Q1``'s column — a pose the ladder was never going to
      draw.

    The search itself is bounded the way the rest of the compiler's search is:
    by the parts' own **accepted** pose sets, to the end.  A part whose accepted
    set is exhausted adds no rungs, and ``budget.max_candidates`` caps the round
    as it caps the base one.  A page that no accepted pose can satisfy is still
    refused, with every refusal's own reason — the widening is a wider look, not a
    lower bar.
    """
    if result.ranked or not result.rejected:
        return []
    named = [
        relation for relation in (
            _refusing_relation(item.failure) for item in result.rejected
        ) if relation is not None
    ]
    # Every refusal has to be a relation refusal, and they all have to be the
    # same one.  A single unnamed refusal among them means the page failed for
    # more than one reason, which is the case this deliberately does not answer.
    if len(named) != len(result.rejected) or not named:
        return []
    if len(set(named)) != 1:
        return []
    widest = max(
        (1, *(len(poses) for poses in ctx.accepted.values() if poses))
    )
    variants: list[_Variant] = []
    for scale in ctx.budget.spacing_ladder:
        for index in range(2, widest):
            variants.append(_Variant(
                label=f"spacing={scale:g} pose-variant={index} (widened)",
                scale=float(scale),
                pose_index=index,
            ))
            if len(variants) >= ctx.budget.max_candidates:
                return variants
    return variants


def _farthest_pair(
    points: Sequence[tuple[float, float]]
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The two points furthest apart, with a stable tie-break by coordinates."""
    best = (points[0], points[-1])
    distance = -1.0
    for index, first in enumerate(points):
        for second in points[index + 1:]:
            gap = math.hypot(first[0] - second[0], first[1] - second[1])
            if gap > distance + 1e-9:
                distance = gap
                best = (first, second)
    return best


def _collinear(points: Sequence[tuple[float, float]]) -> bool:
    """Are all the points on one horizontal or vertical line?"""
    xs = {round(point[0], 6) for point in points}
    ys = {round(point[1], 6) for point in points}
    return len(xs) == 1 or len(ys) == 1


def _extreme(
    points: Sequence[tuple[float, float]]
) -> tuple[tuple[float, float], tuple[float, float]]:
    """The two ends of a collinear run."""
    xs = {round(point[0], 6) for point in points}
    if len(xs) == 1:
        ordered = sorted(points, key=lambda point: point[1])
    else:
        ordered = sorted(points, key=lambda point: point[0])
    return (ordered[0], ordered[-1])


def _span_free(
    router: _Router,
    start: tuple[float, float],
    end: tuple[float, float],
    blocked: set[tuple[float, float]],
    boxes: Sequence[Box] | None = None,
    *,
    wire: bool = True,
) -> bool:
    """Can this one straight wire be drawn as it is, ends and all?

    The trunk shortcut's guard: no obstacle box crossed, no foreign wire run
    along, and no foreign anchor *inside* the span — a foreign pin or label on a
    wire is a connection, and a foreign wire vertex on it is a tee that needs a
    junction the caller would have to declare.

    ``wire`` says whether this run is an **ordinary wire** (the windings, the
    trunks) or a **flag's own lead**. 145a's reserved lanes are about the former:
    the reservation pass promises a pad its lead *before* the wires are laid, and
    the wires are what has to route around it (:func:`_lead_lane_reservations`).
    A flag's own lead is not asked about reservations, because the reservation
    pass and the placement ask this function the *same* question and a
    reservation is not something the drawing can see: by the time a flag is
    placed, its lane is free of wires. Gating only one of the two on
    reservations made them ask different questions (the stricter search skips a
    rung the looser one takes), and 053b's AMS1117 scenes measured the cost —
    two flags pushed onto each other's glyph and refused by the gate.
    """
    if _key(start) == _key(end):
        return False
    # ``boxes`` is for 069 sec.11's false-positive class: a flag's *lead* must not
    # cross a part body, but a text box is typography — the gate has no "wire over
    # text" rule, and treating a text as a wall is what pushed a clean flag position
    # aside because its short lead grazed the core's own value annotation by 1.5
    # units. Line routing keeps the default (every box).
    for box in router.boxes if boxes is None else boxes:
        if _segment_hits_box(start, end, box):
            return False
    for foreign in router.edges:
        if _collinear_overlap(start, end, foreign[0], foreign[1]):
            return False
    for point in blocked:
        if _strictly_on_segment(point, start, end):
            return False
    # 145a: a lane another net's flag has reserved is a wall for an ordinary wire
    # — the shortcut paths (this test and `_elbow_route`) are tried *before* the
    # lattice search, so a reservation the search honours is worthless unless
    # they honour it as well. A flag's own lead (`wire=False`) meets the lanes
    # only while the reservation pass is deciding them (`reserve_strict`), where
    # two leads must not be promised the same crossing; at placement time a lead
    # through a *foreign* reserved lane is harmless (see `_flag_room`). 148 tried
    # gating leads on reservations here as well, to stop two flag leads crossing
    # each other; measured, it refuses six of 053b's own scenes (`08b`, `08e`, the
    # roles, the pads-a-body-separates pair and the plain-label one), so the
    # exemption stays and the crossing between two *leads* is answered where it is
    # drawn instead.
    if (wire or router.reserve_strict) and _reserved_hits(router, start, end):
        return False
    return True


def _reserved_hits(
    router: _Router, start: tuple[float, float], end: tuple[float, float]
) -> bool:
    """Does this run stand on or cross a lane reserved for another net's flag?

    The nodes of the run, not its ends only: a wire that *crosses* a reserved
    lane cuts the lead the flag will be drawn along, which is 074's defect ("a
    flag lead through another net's conductor is read as a short"), so the whole
    span is walled, not just the endpoints. ``router.reserved`` is empty for
    every caller that reserves nothing, so this costs one truth test there.
    """
    if not router.reserved:
        return False
    exempt = router.reserved_exempt
    length = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    steps = max(1, int(round(length / router.grid)))
    for index in range(steps + 1):
        ratio = index / steps
        owner = router.reserved.get(_key(_rounded((
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
        ))))
        if owner is not None and owner != exempt:
            return True
    return False


def _lattice_nodes(
    router: _Router, start: tuple[float, float], end: tuple[float, float]
) -> set[tuple[float, float]]:
    """Every lattice node of the straight run ``start``-``end`` (ends included)."""
    out = {_key(_rounded(start)), _key(_rounded(end))}
    length = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    steps = max(1, int(round(length / router.grid)))
    for index in range(steps + 1):
        ratio = index / steps
        out.add(_key(_rounded((
            start[0] + (end[0] - start[0]) * ratio,
            start[1] + (end[1] - start[1]) * ratio,
        ))))
    return out


def _nodes_in_box(router: _Router, box: Box) -> set[tuple[float, float]]:
    """Every lattice node inside ``box`` (its interior and its edges)."""
    out: set[tuple[float, float]] = set()
    first_x = math.ceil((box[0] - router.residue[0]) / router.grid - 1e-9)
    last_x = math.floor((box[2] - router.residue[0]) / router.grid + 1e-9)
    first_y = math.ceil((box[1] - router.residue[1]) / router.grid - 1e-9)
    last_y = math.floor((box[3] - router.residue[1]) / router.grid + 1e-9)
    for index_x in range(first_x, last_x + 1):
        for index_y in range(first_y, last_y + 1):
            out.add(router.point((index_x, index_y)))
    return out


def _set_foreign_edges(
    router: _Router, segments: Sequence[LayoutSegment], net_id: str
) -> None:
    """``router.edges`` = every wire but this net's own, with the net it belongs to.

    This net's own runs are left out, so the lead a flag hangs off is never in its
    own way, and every other run lands in ``edges`` and ``edge_nets`` together so
    the two lists cannot drift (074's refusal names the foreign net, and a name
    pointing at the wrong run would be worse than no name at all).

    147 adds ``router.own_edges``: the same walk over the runs this call *skips*.
    They are what a flag's own rail looks like, and a flag may not be hung with
    its glyph across one — `drawcompiler._flag_room` asks.
    """
    router.edges = []
    router.edge_nets = []
    router.own_edges = []
    for segment in segments:
        for start, end in zip(segment.points, segment.points[1:]):
            if segment.net == net_id:
                router.own_edges.append((start, end))
                continue
            router.edges.append((start, end))
            router.edge_nets.append(segment.net)


def _proper_crossing(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """Where two segments cross *through* each other, or ``None``.

    ``readability._proper_crossing``'s own ruler, in this module's tolerance: the
    crossing has to be strictly interior to **both** runs, so a shared endpoint, a
    tee (either end landing on the other's span) and a collinear overlap are all
    excluded — each of them is something else, and the tee is the declared
    junction 053 sec.2 puts a dot on.
    """
    ab_len = math.hypot(b[0] - a[0], b[1] - a[1])
    cd_len = math.hypot(d[0] - c[0], d[1] - c[1])
    if ab_len <= 1e-6 or cd_len <= 1e-6:
        return None
    abc = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    abd = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0])
    cda = (d[0] - c[0]) * (a[1] - c[1]) - (d[1] - c[1]) * (a[0] - c[0])
    cdb = (d[0] - c[0]) * (b[1] - c[1]) - (d[1] - c[1]) * (b[0] - c[0])
    eps_ab = 1e-6 * ab_len
    eps_cd = 1e-6 * cd_len
    if not (
        ((abc > eps_ab and abd < -eps_ab) or (abc < -eps_ab and abd > eps_ab))
        and ((cda > eps_cd and cdb < -eps_cd) or (cda < -eps_cd and cdb > eps_cd))
    ):
        return None
    denominator = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if abs(denominator) <= 1e-6:
        return None
    t = (
        (c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])
    ) / denominator
    return _rounded((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))


def _foreign_crossing(
    router: _Router,
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[tuple[float, float], str, tuple[tuple[float, float], tuple[float, float]]] | None:
    """``(point, foreign net, foreign run)`` for the first wire this run cuts through.

    ``router.edges`` is every wire but the one being drawn, so the run a flag hangs
    off is never in its own way. A crossing *through* a foreign wire is not a
    connection in the editor's model (054 C7's measured behaviour, which is why the
    gate counts crossings as a soft metric) — but it is not nothing either: for a
    **flag's** lead it is 074's defect, an unmissable picture of "this name is
    hung on that net" (岳, on the landed P23: 「第一眼以为5V和3V3的旗标短接在一块了」).
    """
    for index, foreign in enumerate(router.edges):
        point = _proper_crossing(start, end, foreign[0], foreign[1])
        if point is None:
            continue
        net = (
            router.edge_nets[index]
            if len(router.edge_nets) == len(router.edges)
            else ""
        )
        return point, net, foreign
    return None


def _lead_crossing(
    router: _Router, lead: Sequence[tuple[float, float]]
) -> str | None:
    """The first foreign wire this lead runs *through*, described, or ``None``.

    Every sub-segment of the lead, not just its ends: 069 sec.10's own shape is a
    run out and then a turn, and it is precisely the **turn** that crossed the
    rail on the page 岳 rejected (measured on E1: the run (110, 730)-(60, 730) is
    clear, the run (60, 730)-(60, 755) goes through the 5V0 rail (50, 740)-(110,
    740) at (60, 740)). A lead that *ends* on a foreign wire is not this rule's
    business: an anchor there is refused by ``_vertex_clear``/``blocked`` before
    this is asked, and the answer is "that point is a connection", never "draw it
    anyway".
    """
    for start, end in zip(lead, lead[1:]):
        hit = _foreign_crossing(router, start, end)
        if hit is None:
            continue
        point, net, foreign = hit
        name = f"net {net}'s wire " if net else "the wire "
        return (
            f"its run {_point_text(start)}-{_point_text(end)} crosses {name}"
            f"{_point_text(foreign[0])}-{_point_text(foreign[1])} at "
            f"{_point_text(point)}"
        )
    return None


def _geometry_nodes(
    router: _Router, segments: Sequence[LayoutSegment]
) -> list[tuple[float, float]]:
    """Every lattice node the net's own wires already pass through.

    The attachment targets: a branch hangs on the nearest point of its net's
    wiring, and the junction the caller then declares is exactly the tee the
    readability checker looks for.
    """
    out: list[tuple[float, float]] = []
    for segment in segments:
        for start, end in zip(segment.points, segment.points[1:]):
            steps = int(
                round(
                    max(abs(end[0] - start[0]), abs(end[1] - start[1]))
                    / router.grid
                )
            )
            for step in range(steps + 1):
                ratio = step / steps if steps else 0.0
                out.append(_rounded((
                    start[0] + (end[0] - start[0]) * ratio,
                    start[1] + (end[1] - start[1]) * ratio,
                )))
    return out


def _connect_net(
    ctx: _Context,
    router: _Router,
    expression: _Expression,
    blocked: set[tuple[float, float]],
    existing: Sequence[LayoutSegment] = (),
) -> tuple[list[LayoutSegment], str] | None:
    """Wire one net: trunk first, then the search, then the attachments.

    "主干优先" (053 sec.4): the trunk is the line the *chain* runs along, so when
    the net has two or more chain pins the trunk is drawn between the extreme
    ones and every other pin (a branch root, a tap's own pin) is attached to it.
    Only a net with no chain pins falls back to the longest hop as its trunk.

    ``existing`` is what this net already has on the page — a tap's stub, drawn
    before the trunk so its label marks the node — and a pin that already lies on
    that geometry is left alone rather than reached a second time along the same
    line.

    A pad in ``expression.detached`` is not part of this wire at all (069 sec.2:
    it carries its own flag instead of a run over the body), so the trunk and the
    attachments are computed from the rest.

    Returns ``None`` when the net could not be drawn inside the corridor (the
    caller falls back to a name, or refuses the candidate — never to a wire that
    pretends to connect something it does not).
    """
    points = sorted({
        _key(point) for member, point in expression.points
        if member not in expression.detached
    })
    if not points:
        # 069 sec.2: every pad of this net is a far duplicate, so each one is
        # named at its own stub and there is nothing left for a wire to join.
        return [], "no wire: every pin of this net is named at its own stub"
    if len(points) == 1:
        return [], "one pin: nothing to wire"
    chain_points = sorted({
        _key(point) for member, point in expression.points
        if member not in expression.detached
        and ctx.slots.get(member.partition(".")[0]) is not None
        and ctx.slots[member.partition(".")[0]].kind == "chain"
    })
    if not existing and _collinear(points):
        start, end = _extreme(points)
        if _span_free(router, start, end, blocked):
            return (
                [LayoutSegment(net=expression.net, points=[start, end])],
                "collinear trunk: one straight wire, no bend",
            )
    trunk = _extreme(chain_points) if len(chain_points) >= 2 else _farthest_pair(points)
    segments = list(existing)
    elbow = _elbow_route(router, trunk[0], trunk[1], blocked)
    if elbow is not None:
        segments.append(LayoutSegment(net=expression.net, points=elbow))
    else:
        path = router.route(trunk[0], trunk[1])
        if path is None:
            return None
        segments.append(LayoutSegment(net=expression.net, points=_compress(path)))
    for point in sorted(points, key=lambda item: (-_distance_to(segments, item), item)):
        if _on_geometry(segments, point):
            continue
        attached = _attach(router, point, segments, blocked, expression.net)
        if attached is None:
            return None
        segments.append(attached)
    return segments, (
        "trunk along the chain's own pins, then every other pin attached"
        if len(chain_points) >= 2
        else "trunk between the two farthest pins, then L-attachments"
    )


def _elbow_route(
    router: _Router,
    start: tuple[float, float],
    end: tuple[float, float],
    blocked: set[tuple[float, float]],
) -> list[tuple[float, float]] | None:
    """A one-bend orthogonal path, when one exists — the cheapest wire there is.

    Two L-shapes are possible; the first free one wins, in a fixed order. This is
    tried before the search because it is both cheaper to find and better to look
    at (one bend rather than whatever the search happens to return), and the
    search is then only used where the drawing really is crowded.
    """
    if _key(start) == _key(end):
        return None
    for corner in ((end[0], start[1]), (start[0], end[1])):
        if _key(corner) == _key(start) or _key(corner) == _key(end):
            straight = [start, end]
            if _span_free(router, start, end, blocked):
                return straight
            continue
        if not _span_free(router, start, corner, blocked):
            continue
        if not _span_free(router, corner, end, blocked):
            continue
        if not _vertex_clear(router, corner):
            continue
        return [start, corner, end]
    return None


def _vertex_clear(router: _Router, point: tuple[float, float]) -> bool:
    """Is this point outside every foreign wire's span?

    A vertex of one wire lying inside another's span *joins* them in the editor's
    model (that is why a tee needs a junction), so our own corner may not land
    there — the readability contract's first constraint would report it, and the
    plan would be a drawing of a different circuit.

    145a's reserved lanes are **not** asked about here, and they do not need to
    be: every caller reaches a corner through :func:`_span_free` on the two legs
    that meet there, and that test counts the run's **endpoints**, so a corner
    standing on a reserved lane is refused as a leg. (It is also why a *flag's*
    lead is left alone by the reservations — see :func:`_span_free`'s ``wire``.)
    """
    return router.crossing_at(point) is None


def _attach(
    router: _Router,
    point: tuple[float, float],
    segments: Sequence[LayoutSegment],
    blocked: set[tuple[float, float]],
    net_id: str,
) -> LayoutSegment | None:
    """Reach one pin from the net's own wiring: an elbow if one fits, else search.

    The nearest wiring node is tried first, so a branch hangs off the closest point
    of its node (052 sec.5: a branch reads as owned by the node it decouples), and
    the search is only spent when no single-bend path is free.
    """
    targets = _geometry_nodes(router, segments)
    if not targets:
        return None
    for target in _nearest_first(point, targets):
        elbow = _elbow_route(router, point, target, blocked)
        if elbow is not None and len(elbow) >= 2:
            return LayoutSegment(net=net_id, points=elbow)
    path = router.route(point, point, targets=targets)
    if path is None:
        return None
    compressed = _compress(path)
    if len(compressed) < 2:
        return None
    return LayoutSegment(net=net_id, points=compressed)


def _nearest_first(
    point: tuple[float, float], targets: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    return sorted(
        set(targets),
        key=lambda target: (math.hypot(target[0] - point[0], target[1] - point[1]),
                            target),
    )



def _on_geometry(segments: Sequence[LayoutSegment], point: tuple[float, float]) -> bool:
    return any(_on_polyline(point, segment.points) for segment in segments)


def _distance_to(segments: Sequence[LayoutSegment], point: tuple[float, float]) -> float:
    best = math.inf
    for segment in segments:
        for start, end in zip(segment.points, segment.points[1:]):
            best = min(best, _distance_to_segment(point, start, end))
    return best


def _distance_to_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    if length <= 0.0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    ratio = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length
    ratio = min(1.0, max(0.0, ratio))
    return math.hypot(point[0] - (start[0] + dx * ratio), point[1] - (start[1] + dy * ratio))


def _net_order(ctx: _Context, expressions: Mapping[str, _Expression]) -> list[str]:
    """The order nets are drawn in: promised trunks first, then the big ones.

    "主干优先" (053 sec.4): the wires the grammar promised are laid before
    anything else, so the rest of the drawing routes around the topology the
    reader is meant to see rather than the other way round.
    """
    promised: list[str] = []
    for item in ctx.binding.obligations:
        if item.kind == DIRECT_WIRE:
            for net in item.nets:
                if net in expressions and net not in promised:
                    promised.append(net)
    for item in ctx.presentation.direct_wiring_obligations:
        for net in item.nets:
            if net in expressions and net not in promised:
                promised.append(net)
    rest = sorted(
        (net for net in expressions if net not in promised),
        key=lambda net: (-len(expressions[net].points), net),
    )
    return promised + rest


def _blocked_points(
    ctx: _Context,
    placed: _Placement,
    current: str,
    labels: Sequence[LayoutLabel],
    symbols: Sequence[LayoutPowerSymbol],
    segments: Sequence[LayoutSegment],
) -> set[tuple[float, float]]:
    """The points no wire of `current` may touch.

    Every one of them is a connection in the editor's own model: a foreign pin
    tip (including a pin the spec never mentions, which would be an invented
    connection), an explicit NC pin, a foreign label's or flag's anchor, and a
    foreign wire's vertex. A wire vertex landing on any of them joins two nets
    that the CircuitSpec keeps apart, which is the short the readability contract
    refuses.
    """
    out: set[tuple[float, float]] = set()
    members = set()
    net = ctx.circuit.net(current)
    if net is not None:
        members = set(net.members)
    for part_id in placed.origins:
        profile = ctx.profile(part_id)
        for pin in profile.pins:
            member = f"{part_id}.{pin.number}"
            also = f"{part_id}.{pin.name}" if pin.name else ""
            if member in members or (also and also in members):
                continue
            point = _pin_point(ctx, part_id, pin.number, placed.poses, placed.origins)
            if point is not None:
                out.add(_key(point))
    for label in labels:
        if label.net != current:
            out.add(_key((label.x, label.y)))
    for symbol in symbols:
        if symbol.net != current:
            out.add(_key((symbol.x, symbol.y)))
    for segment in segments:
        if segment.net == current:
            continue
        for point in segment.points:
            out.add(_key(point))
    return out


def _search_bounds(
    ctx: _Context, boxes: Sequence[Box], points: Sequence[tuple[float, float]]
) -> Box:
    """The corridor one router may use: the drawing plus a margin, inside the page."""
    xs = [box[0] for box in boxes] + [point[0] for point in points]
    ys = [box[1] for box in boxes] + [point[1] for point in points]
    xs += [box[2] for box in boxes]
    ys += [box[3] for box in boxes]
    left = min(xs) - SEARCH_MARGIN
    right = max(xs) + SEARCH_MARGIN
    bottom = min(ys) - SEARCH_MARGIN
    top = max(ys) + SEARCH_MARGIN
    page = ctx.budget.page_box
    if page is not None:
        left = max(left, page[0] + ctx.budget.grid / 2.0)
        right = min(right, page[2] - ctx.budget.grid / 2.0)
        bottom = max(bottom, page[1] + ctx.budget.grid / 2.0)
        top = min(top, page[3] - ctx.budget.grid / 2.0)
    return (left, bottom, right, top)


@dataclass
class _Built:
    """A plan that passed the gate, with the gate's own result kept for evidence."""

    plan: LayoutPlan
    checked: readability.CheckResult


def _build_candidate(
    ctx: _Context, variant: _Variant
) -> tuple[_Built | None, GrammarFailure | None, list[str]]:
    """One variant -> one plan, gated by the independent readability checker.

    Every refusal here is a *measured* one: the region the drawing needs, the pin
    a wire could not reach, the box the text landed on. None of them is "tried
    and gave up silently" — the candidate is dropped with its reason, and
    :func:`compile` reports the first one when no candidate survives.
    """
    placed, failure = _place(ctx, variant)
    if placed is None:
        return None, failure, []

    parts: list[LayoutPart] = []
    # Two obstacle sets, because they answer two different questions: `occupied`
    # is what *text* must avoid (a part's whole extent, tips included, so a value
    # never prints across its own pins), while `solids` is what a *wire* may not
    # cross (the drawn body only — a wire has to be able to leave its own pin tip
    # and travel to the part it belongs to; the checker's rule is the body).
    occupied: list[Box] = list(ctx.budget.keepouts)
    solids: list[Box] = list(ctx.budget.keepouts)
    #: What a *text* must avoid of the parts placed here (099b): what each of
    #: them is **drawn as** — its body and the segments its pins are drawn as —
    #: never the box around them. `_part_box` bounds the pin tips too, and
    #: reading that box as a wall let an empty bounding-box corner decide a side
    #: by 1.5 units (the 099 CH340 measurement). `_part_texts` adds each part's
    #: own full extent for its own text, so a value never prints across its own
    #: pins; a profile that states no pin length keeps the whole box (`_text_walls`).
    text_walls: list[Box] = list(ctx.budget.keepouts)
    #: The *conductors* a flag's own lead may not cross: the keep-outs and the parts'
    #: bodies, without the text boxes (`router.boxes` keeps those, so ordinary wiring
    #: still avoids them). 069 sec.11: a text is typography, and treating it as a wall
    #: pushed a clean flag position aside for grazing the core's own value by 1.5.
    bodies: list[Box] = list(ctx.budget.keepouts)
    for part_id in sorted(placed.origins):
        profile = ctx.profile(part_id)
        pose = placed.poses[part_id]
        origin = placed.origins[part_id]
        parts.append(LayoutPart(
            part_id=part_id,
            symbol_ref=profile.symbol_ref,
            symbol_hash=profile.geometry_hash(),
            x=origin[0],
            y=origin[1],
            rotation=float(pose.rotation),
            mirror=pose.mirror,
            reference=part_id,
        ))
        occupied.append(_part_box(profile, pose, origin))
        body = _body_box(profile, pose, origin)
        if body is not None:
            solids.append(body)
            bodies.append(body)
        text_walls.extend(_text_walls(profile, pose, origin))
        # 147: every pin's drawn lead is an obstacle for the router as well.
        # `_text_walls` already builds those boxes ("each pin as the segment that
        # pin is drawn as — never the box around them"); the router only ever got
        # the body box, so a wire could be routed *along* a pin's line and hide it
        # (岳, `test/P1`: the HVDC run covers 15 of T1.1's 20 drawn units and SW 5
        # of T1.3's — `outputs/147/17_wire_on_lines_146.txt`). `readability`'s
        # `wire-on-pin-line` measures the same lines against the plan, so this is
        # the obstacle table catching up with the gate rather than a new rule.
        solids.extend(_pin_walls(profile, pose, origin))

    texts = _part_texts(ctx, placed, occupied, text_walls)
    for text in texts:
        solids.append(text.bbox)
    # 148: a flag's own **lead** may not cross a text row either. `bodies` is what
    # `_flag_anchor` tests a lead against, and 069 sec.11 kept it to part bodies
    # and keep-outs because the gate had no "a wire printed through a text row"
    # rule then. 147 added one (`readability`'s `text-on-wire`, the same 10 units
    # `drawlint` L1 measures), so the obstacle table has to catch up the way it did
    # for the pin lines: measured on `test/P1`, `C6.2`'s ground stub ran 25 units
    # up from its pin straight through `C6`'s own value row (`100pF 0603 C0G`).
    bodies.extend(text.bbox for text in texts)
    early = _region_failure(ctx, occupied)
    if early is not None:
        # The parts and their text already need more room than the region has:
        # report *that*, rather than describing the wiring failure the clipped
        # search would hit first. 053 sec.5 scenario 10: 空间不足 + 可选动作, and
        # the text is never squeezed to make it fit.
        return None, early, []
    expressions = _expressions(ctx, placed)
    tap_nets = _tap_axis_by_net(ctx.circuit, ctx.binding)
    labels: list[LayoutLabel] = []
    symbols: list[LayoutPowerSymbol] = []
    segments: list[LayoutSegment] = []
    notes: list[str] = []
    router = _Router(
        grid=ctx.budget.grid,
        residue=placed.residue,
        boxes=solids,
        bounds=_search_bounds(
            ctx, occupied,
            [point for expression in expressions.values()
             for _, point in expression.points],
        ),
    )
    #: Nets the class says are flags but the library carries no symbol for, so
    #: they are drawn as wires instead (143 F1). They are remembered because the
    #: wire path's own "could not route it" answer is a *label*, and for these
    #: nets that answer is forbidden: a label is a conductor only in this
    #: compiler's offline model — 029 measured that this host cannot place a
    #: netlabel at all, and `draw apply` writes wires and flags, nothing else.
    #: A label-only net is therefore a net with **no conductor on the canvas**.
    flag_downgraded: set[str] = set()
    order = _net_order(ctx, expressions)
    # 145a T3: every lead the plan will draw — a flag's, a label's name stub — is
    # promised its lane *before* the first wire is drawn, so the wires the rest of
    # this loop lays down route around it instead of taking it and leaving the
    # lead to be refused. See :func:`_lead_lane_reservations`.
    #
    # 148 adds the **flag itself** to that promise, for the nets whose flag hangs
    # off the rail this loop routes (069 sec.7, 088b): the seat is decided there
    # and returned as a box no wire may enter — the reservation alone only keeps
    # *foreign* wires off, and a rail running through its own pennant is the same
    # defect 岳 saw on `test/P1`. `flag_walls` is therefore part of `router.boxes`
    # from here on, and `solids` (what a *flag* may not land on) is not: a flag's
    # own seat must not turn that flag away from itself.
    _lead_lane_reservations(
        ctx, placed, expressions, order, router, occupied, solids, bodies,
    )
    router.boxes = [*solids, *router.flag_walls]
    for net_id in order:
        expression = expressions[net_id]
        if (
            expression.style == "flag"
            # A one-pin net has nothing to conduct: its content *is* its name, so
            # the label fallback below stays what it is. The invariant this
            # guards is "a net with more than one pin has a conductor".
            and len(expression.points) > 1
            and _missing_flag_symbol(ctx, net_id)
        ):
            expression, downgrade_note = _flag_wire_fallback(
                ctx, net_id, expression
            )
            # Written back, because the passes after the loop (069 sec.7's rail
            # flag, the 088b ground outlet) read `expressions[net_id]` — a local
            # rebinding alone would hang a flag on a net this pass no longer
            # draws as one (143's second report names that shape).
            expressions[net_id] = expression
            flag_downgraded.add(net_id)
            notes.append(downgrade_note)
        router.reserved_exempt = net_id
        _set_foreign_edges(router, segments, net_id)
        blocked = _blocked_points(
            ctx, placed, net_id, labels, symbols, segments,
        )
        # The search knows the same walls the straight-run tests do. Without this
        # the lattice router only avoids boxes and foreign wire runs, and happily
        # routes a wire *through* a foreign pin tip — which is a connection in the
        # editor's model, so the drawing is refused by the checker as an
        # undeclared short instead of being routed around the pin (measured on
        # 060 sec.1's capacitor placement, where a wire from the output pin has to
        # pass the ground pin ten units away).
        router.blocked = blocked
        if expression.style == "wire" and net_id in tap_nets:
            # The stub goes down *before* the trunk: it leaves the junction and
            # reaches past every branch root on this node, so the trunk's own
            # attachments then find the roots already on a wire instead of
            # drawing a second, overlapping run to reach them.
            note = _tap_stub(
                ctx, placed, expression, router, segments, labels, occupied, solids,
                blocked,
            )
            notes.append(f"net {net_id}: {note}")
        if expression.style == "wire":
            drawn = _connect_net(
                ctx, router, expression, blocked,
                [item for item in segments if item.net == net_id],
            )
            obligated = net_id in _obligation_nets(ctx)
            if drawn is None:
                if obligated:
                    return None, GrammarFailure(
                        category=FAILURE_LAYOUT_UNSAT,
                        subject=net_id,
                        detail=(
                            f"net {net_id!r} has a direct-wire obligation and its "
                            "pins could not be joined inside the searched "
                            "corridor without a wire crossing a body, a text box "
                            "or a foreign connection — the promise is not "
                            "downgraded to a label"
                        ),
                        action=(
                            "enlarge the region (or lower budget.spacing_ladder's "
                            "first rung is already the geometric minimum), move "
                            "the keep-out that blocks the corridor, or drop the "
                            "direct-wire obligation if a label is acceptable here"
                        ),
                    ), []
                if net_id in flag_downgraded and len(expression.points) > 1:
                    # 143 F1: this net was a flag net the library carries no
                    # symbol for, and it cannot be wired either. A label is the
                    # one answer 053 sec.7 forbids here — `sch.place_netlabel` is
                    # measured unusable (029), so the label would name the net
                    # nowhere: the plan would print a verdict of `pass` for a
                    # multi-pin net with zero conductors, and `draw apply`'s live
                    # netlist leg could never satisfy it. Refused, naming the net
                    # and both repairs.
                    return None, GrammarFailure(
                        category=FAILURE_LAYOUT_UNSAT,
                        subject=net_id,
                        detail=(
                            f"net {net_id!r} is a flag-style net (its class is "
                            f"{_net_class(ctx, net_id)!r}) whose flag symbol the "
                            "library does not carry, so it falls back to being "
                            f"wired — and its {len(expression.points)} pins could "
                            "not be joined inside the searched corridor either. "
                            "The only remaining expression is a label, and this "
                            "host cannot place one (`sch.place_netlabel` is "
                            "measured unusable, 029): the net would be drawn with "
                            "no conductor at all (143 F1)"
                        ),
                        action=(
                            "add the flag symbol to the library (budget.gnd_flag / "
                            "power_flag_prefix name it), or enlarge the region / "
                            "move the keep-out that blocks the corridor, or lower "
                            "budget.spacing_ladder's first rung if the two ends can "
                            "be brought closer — a multi-pin net is never left "
                            "with a name and no conductor"
                        ),
                    ), []
                expression = _Expression(
                    net=expression.net, style="label", points=expression.points,
                    reason=(
                        "the net could not be wired inside the corridor, and no "
                        "obligation promises it as a wire, so it is named by a "
                        "label at each of its pins"
                    ),
                )
                notes.append(f"net {net_id}: wired route not found; labelled instead")
            else:
                drawn_segments, why = drawn
                segments = [
                    item for item in segments if item.net != net_id
                ] + list(drawn_segments)
                if drawn_segments:
                    notes.append(f"net {net_id}: {why}")
        if expression.style == "wire" and expression.detached:
            # 069 sec.2: the far pad is named where it stands, and the wired
            # cluster gets the same name — the two islands are one node in the
            # spec, and only a name on each of them says so.
            net = ctx.circuit.net(net_id)
            cls = net.cls if net is not None else "power"
            named = _sibling_name_form(ctx, net_id, cls)
            profile, ref = _flag_plan(ctx, net_id, cls)
            far = [
                (member, point) for member, point in expression.points
                if member in expression.detached
            ]
            near = [
                (member, point) for member, point in expression.points
                if member == expression.pivot
            ]
            for member, point in far:
                if named == "flag":
                    failure = _flag_pins(
                        ctx, placed, net_id, profile, ref, [(member, point)],
                        router, segments, symbols, occupied, solids, blocked,
                        bodies, stub=True,
                    )
                    if failure is not None:
                        return None, failure, []
                    continue
                failure = _stub_label(
                    ctx, placed, net_id, member, point, router, segments,
                    labels, occupied, solids, blocked,
                )
                if failure is not None:
                    return None, failure, []
            for member, point in near:
                if named == "flag":
                    failure = _flag_pins(
                        ctx, placed, net_id, profile, ref, [(member, point)],
                        router, segments, symbols, occupied, solids, blocked,
                        bodies,
                    )
                    if failure is not None:
                        return None, failure, []
                    continue
                failure = _stub_label(
                    ctx, placed, net_id, member, point, router, segments,
                    labels, occupied, solids, blocked,
                )
                if failure is not None:
                    return None, failure, []
            notes.append(
                f"net {net_id}: " + ", ".join(expression.detached)
                + " sit on the far side of their own body from "
                + (expression.pivot or "the rest of the net")
                + f", so each is brought out on a stub and named by its own "
                f"{named} instead of being wired across the part (069 sec.2)"
            )
        if expression.style == "label":
            for member, point in expression.points:
                part_id, _, token = member.partition(".")
                label = _label_for(
                    ctx, net_id, part_id, token, point, placed, occupied,
                )
                labels.append(label)
                solids.append(label.bbox)
        if expression.style == "flag":
            net = ctx.circuit.net(net_id)
            cls = net.cls if net is not None else "gnd"
            profile, ref = _flag_plan(ctx, net_id, cls)
            if profile is None:
                notes.append(
                    f"net {net_id}: the library carries no flag symbol {ref!r}, so "
                    "the net is named by labels at its pins (one style throughout)"
                )
                for member, point in expression.points:
                    part_id, _, token = member.partition(".")
                    label = _label_for(
                        ctx, net_id, part_id, token, point, placed, occupied,
                    )
                    labels.append(label)
                    solids.append(label.bbox)
                continue
            failure = _flag_pins(
                ctx, placed, net_id, profile, ref, expression.points,
                router, segments, symbols, occupied, solids, blocked, bodies,
            )
            if failure is not None:
                return None, failure, []
        router.boxes = [*solids, *router.flag_walls]

    # 069 sec.7's own supply, *after* every net is routed: 岳 read the landed P23
    # page and asked why its 5 V rail had no flag (「P23 5V部分为什么不给旗标？」), so
    # a rail drawn as a wire carries one — hung off the rail by a short vertical run
    # (:func:`_rail_flag`), at the pin the rail supplies. Placed last on purpose:
    # those runs are obstacles for the router, and put in the per-net loop they
    # cost one 053B scenario 4 s → 40 s of search (measured) without changing a
    # single drawing.
    for net_id in order:
        expression = expressions[net_id]
        if expression.style != "wire" or not _power_needs_flag(ctx, net_id, symbols):
            continue
        profile, ref = _flag_plan(ctx, net_id, "power")
        pin = _power_flag_pin(ctx, expression)
        if profile is None or pin is None:
            continue
        router.reserved_exempt = net_id
        _set_foreign_edges(router, segments, net_id)
        blocked = _blocked_points(ctx, placed, net_id, labels, symbols, segments)
        router.blocked = blocked
        anchor, failure = _rail_flag(
            ctx, placed, net_id, expression, pin, profile, ref, router, segments,
            symbols, occupied, solids, blocked, bodies,
        )
        if failure is not None:
            return None, failure, []
        notes.append(
            f"net {net_id}: a power net carries its own flag — hung at "
            f"{_point_text(anchor)} by a {FLAG_JOG:g}-unit vertical run off the "
            f"rail its pin {pin[0]} supplies (069 sec.7); a rail named by text "
            "alone would be found by chasing names"
        )
        router.boxes = [*solids, *router.flag_walls]

    # 088b sec.1: a declared group's ground rail is *stated* by exactly one
    # outlet symbol of its own, hung at the rail's far end (背向入口那端). The
    # obligation names the net and nothing else: which end is "far" is read from
    # `sidePreferences.input`, so the symbol mirrors with the drawing instead of
    # being a second coordinate. Placed after every net for the same measured
    # reason the rail flags above are — the run is an obstacle for whatever
    # follows it. A net the plan already states with a symbol of its own, or one
    # not drawn as a wire, is left exactly as it is: the promise is "stated by
    # exactly one symbol", and a bus of flags already states it.
    for net_id in order:
        if net_id not in _gnd_outlet_nets(ctx):
            continue
        expression = expressions[net_id]
        net = ctx.circuit.net(net_id)
        cls = net.cls if net is not None else "gnd"
        if expression.style != "wire" or any(
            symbol.net == net_id for symbol in symbols
        ):
            continue
        profile, ref = _flag_plan(ctx, net_id, cls)
        pin = _gnd_outlet_pin(ctx, expression)
        if profile is None or pin is None:
            continue
        router.reserved_exempt = net_id
        _set_foreign_edges(router, segments, net_id)
        blocked = _blocked_points(ctx, placed, net_id, labels, symbols, segments)
        router.blocked = blocked
        failure = _flag_pins(
            ctx, placed, net_id, profile, ref, [pin], router, segments,
            symbols, occupied, solids, blocked, bodies,
        )
        if failure is not None:
            return None, failure, []
        notes.append(
            f"net {net_id}: the group states its return with one outlet symbol — "
            f"hung at the rail's far end off the pin {pin[0]} "
            f"(sidePreferences.input={ctx.presentation.side_for('input') or 'left'}"
            " puts that end away from the inlet, 088b sec.1); the rail stays one "
            "conductor, and the symbol says where the return leaves the group"
        )
        router.boxes = [*solids, *router.flag_walls]

    junctions = _junctions(segments)
    plan_notes = [
        f"compiled by {COMPILER_NAME}: {variant.label}; "
        f"axis {'column' if ctx.axis == 'v' else 'row'}, "
        f"grid {ctx.budget.grid:g}",
        "references are the CircuitSpec's own ids: an offline plan has not "
        "landed, so the designator is assigned when it does",
        *notes,
    ]

    def assemble() -> LayoutPlan:
        return LayoutPlan(
            source=LayoutSource(
                circuit_sha256=ctx.circuit.sha256(),
                presentation_sha256=ctx.presentation.sha256(),
            ),
            parts=parts,
            segments=segments,
            junctions=_junctions(segments),
            labels=labels,
            power_symbols=symbols,
            texts=texts,
            notes=plan_notes,
        )

    plan = assemble()
    overflow = _overflow(ctx, plan)
    if overflow is not None:
        return None, overflow, []

    def grade(layout: LayoutPlan) -> readability.CheckResult:
        return readability.check(
            layout,
            ctx.circuit,
            ctx.presentation,
            ctx.book,
            # 095 A4: the checker re-binds the grammar, so it reads the same three
            # documents the constraints came from — the contract included. Without
            # it a plan whose order came from a decision would be graded against
            # the designator order it was deliberately not drawn with.
            grammar_checker=partial(check_grammar, intent=ctx.intent),
            page_box=ctx.budget.page_box,
            keepouts=ctx.budget.keepouts,
            grid=ctx.budget.grid,
        )

    checked = grade(plan)
    # 148: a wire's **name row** is drawn by the host at the midpoint of the wire's
    # longest run (`core.textmetrics.wire_name_box`), so where it lands is a
    # property of the geometry the compiler just wrote — and only the gate can say
    # whether it landed on a part, on another row or across a conductor. The
    # escape ladder answers exactly that, one row at a time, re-grading after each
    # round.
    escaped = 0
    for _round in range(NAME_ESCAPE_ROUNDS):
        if not checked.hard_violations:
            break
        offenders = _named_rows_in(checked.hard_violations)
        if not offenders:
            break
        moved = _escape_named_rows(
            ctx, placed, readability._placed_parts(plan, ctx.book), expressions,
            router, segments, offenders, labels, symbols, assemble,
        )
        if not moved:
            break
        escaped += moved
        plan = assemble()
        overflow = _overflow(ctx, plan)
        if overflow is not None:
            return None, overflow, []
        checked = grade(plan)
    if escaped:
        plan_notes.append(
            f"{escaped} wire run(s) were moved aside so their own net's name row "
            "could be printed where nothing is (148: the host prints that row at "
            "the midpoint of the wire's longest run, so the run is the only lever)"
        )
    if checked.hard_violations:
        return (
            None,
            _gate_failure(ctx, variant, checked.hard_violations),
            [item.render() for item in checked.hard_violations],
        )
    return _Built(plan=plan, checked=checked), None, []


#: 148: how many times the name-row escape ladder may move a run and re-grade the
#: page. Each round is a full `readability.check`, and each round moves at most one
#: run per offending row; four is enough for the pages this repo draws (the flyback
#: row needs two) and small enough that a page which cannot be repaired is refused
#: inside the ordinary budget rather than searched forever.
NAME_ESCAPE_ROUNDS = 4

#: The distances the escape ladder pushes a run aside, in grid steps. Small steps
#: first (a row that clears a body by one step is the smallest change), and far
#: enough out to make the pushed run the **longest** one of its wire — which is
#: what moves the name onto a different run altogether, and the only answer for a
#: short stub whose row overhangs its far end (`CS_FILT` on `test/P1`).
NAME_ESCAPE_STEPS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 8, 10, 12, 14, 16, 20, 24)

#: How many pushes of the ladder are *graded* for one row in one round. Each one
#: is a full check of the two row rules (`_row_offences`), so the count is what
#: keeps a page that cannot be repaired from costing a search; the ladder is
#: ordered nearest-first, so the answers that matter are at its head.
NAME_ESCAPE_TRIES = 12


def _named_rows_in(violations: Sequence[readability.HardViolation]) -> set[int]:
    """The segments whose **own name row** one of these violations is about.

    The gate names every object it reports, and a wire's name row is named
    ``segments[i]`` — the row *is* a property of that run (`readability.
    _named_wire_rows`), so the object that carries the index is the wire the
    escape ladder has to move. Two kinds qualify:

    * ``text-overlap`` — the row landed on a text, on a part's drawn extent or on
      another row. Either side of the pair may be the row, so both are read.
    * ``text-on-wire`` — a conductor was printed through the row. The row is
      always the violation's **first** object here; the second is the conductor
      that crossed it, and moving *that* wire is not this pass's business (the
      conductor's own row is the one the host prints).
    """
    out: set[int] = set()
    for item in violations:
        if item.kind == readability.KIND_TEXT_OVERLAP:
            names = item.objects
        elif item.kind == readability.KIND_TEXT_ON_WIRE:
            names = item.objects[:1]
        else:
            continue
        for name in names:
            index = _segment_index(name)
            if index is not None:
                out.add(index)
    return out


def _segment_index(name: str) -> int | None:
    """``"segments[12]"`` -> ``12``; anything else -> ``None``."""
    if not name.startswith("segments[") or not name.endswith("]"):
        return None
    try:
        return int(name[len("segments["):-1])
    except ValueError:
        return None


def _escape_deltas(grid: float) -> list[float]:
    """The ladder: one grid step out, both ways, then farther and farther."""
    out: list[float] = []
    for step in NAME_ESCAPE_STEPS:
        out.append(step * grid)
        out.append(-step * grid)
    return out


def _escape_run(
    points: Sequence[tuple[float, float]],
    delta: float,
    pads: Sequence[tuple[float, float]] = (),
    net_wiring: Sequence[Sequence[tuple[float, float]]] = (),
):
    """``points`` with its **longest run** pushed ``delta`` units aside.

    The run is the one the host prints the name along, and its midpoint is the
    name's anchor, so pushing the run is the only way to move the row: the
    compiler does not place that text.

    **A pad keeps its place; anything else the run reaches slides with it.** The
    run's two ends are polyline vertices, and each is one of two things: a **pad**
    (a pin the net must still touch — it stays, and a short leg is added to reach
    the pushed run) or a **point on the net's own other wiring** (a tee — it
    slides along with the run, so no leg is added). The second rule is what keeps
    the drawing from carrying a leg that the host **merges**: measured while
    landing 148 on P1, pushing `CLAMP`'s `C5.1` stub aside left a leg running
    *along* the net's own trunk, the host merged the two into one wire, and the
    page then had no vertex where the plan says one is — `draw apply`'s canvas
    postcondition failed (`net CLAMP: no wire vertex at (20, 740) on the page`).
    Sliding the tee to the pushed run's own row gives `(40,740)->(40,750)->(20,750)`
    instead: two legs, no merge, every vertex on the page.

    The result is compressed (collinear middles and touching duplicates dropped),
    for the same reason: a redundant vertex is a vertex the host does not draw.

    ``None`` when there is nothing to push (a one-point wire, a diagonal run,
    ``delta`` of zero). A push large enough makes the pushed run the longest one,
    which moves the row onto it: that is the ladder's far end and the answer for a
    stub too short to overhang anywhere clean.
    """
    if len(points) < 2 or not delta:
        return None
    index = max(
        range(len(points) - 1),
        key=lambda i: math.hypot(
            points[i + 1][0] - points[i][0], points[i + 1][1] - points[i][1]
        ),
    )
    start, end = points[index], points[index + 1]
    if _close(start[1], end[1]):
        bend = ((start[0], start[1] + delta), (end[0], end[1] + delta))
    elif _close(start[0], end[0]):
        bend = ((start[0] + delta, start[1]), (end[0] + delta, end[1]))
    else:
        return None

    def held(point: tuple[float, float]) -> bool:
        return any(_close_point(point, pad) for pad in pads)

    def slides(point: tuple[float, float], to: tuple[float, float]) -> bool:
        """May this end move with the run, or must a leg be added to reach it?

        A tee may slide only onto a point the net's **own other wiring** still
        passes through — otherwise the net is left in two pieces. Measured: the
        `FB_SENSE` stub whose far end tees into the trunk at the trunk's *end*
        point has nowhere to slide to on the uphill side, so only the downhill
        push is a candidate.
        """
        on_wiring = any(_on_polyline(to, list(piece)) for piece in net_wiring)
        if not on_wiring:
            return False
        # A **pad** may slide only when the net's own wiring already reaches it —
        # the far pad of 069 sec.2's sibling pair, whose pin is the trunk's own
        # end: the stub then exists to join the *near* pad to the net, and any
        # point of the trunk does. A pad the net's other wiring does not reach
        # never moves: the pin is where the pin is (`CS_FILT`, `CLAMP`'s `C5.1`).
        return not held(point) or any(
            _on_polyline(point, list(piece)) for piece in net_wiring
        )

    head = list(points[:index + 1])
    tail = list(points[index + 1:])
    head = head[:-1] + [bend[0]] if slides(start, bend[0]) else head + [bend[0]]
    tail = [bend[1]] + tail[1:] if slides(end, bend[1]) else [bend[1], *tail]
    out = _compress([*head, *tail])
    if len(out) < 2:
        return None
    # Last guard against the host's own merge: an end that the net's wiring
    # already reaches, whose neighbour would be swallowed by that same wiring, is
    # dropped — the wire then ends *on* the other run, which is where the host
    # would have put it anyway. Measured on the landed P1 plan: `FB_SENSE`'s stub
    # to `R8.1` ended with a leg running down `R7.2`'s trunk, and the page came
    # back without the vertex between them (`draw apply`'s canvas leg).
    for end_first in (True, False):
        if len(out) < 3:
            break
        tip = out[0] if end_first else out[-1]
        near = out[1] if end_first else out[-2]
        for piece in net_wiring:
            points = list(piece)
            if not _on_polyline(tip, points):
                continue
            if any(
                _strictly_on_segment(near, a, b)
                for a, b in zip(points, points[1:])
            ):
                out = out[1:] if end_first else out[:-1]
                break
    out = _compress(out)
    return out if len(out) >= 2 else None


def _close_point(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return _close(left[0], right[0]) and _close(left[1], right[1])


def _row_offences(
    plan: LayoutPlan,
    placed: Sequence[Any],
    profile_map: Mapping[str, SymbolProfile],
    index: int,
) -> tuple[int, int]:
    """``(violations about segment ``index``'s own name row, all row violations)``.

    Both halves are the gate's **own** functions (`readability._check_text` and
    `_check_text_on_wire`) run over a candidate plan, not a second model of them:
    the row the ladder is trying to clear has to be judged by the same ruler that
    refused the page, or the ladder optimises against a rule nobody measures.
    """
    name = f"segments[{index}]"
    own = 0
    total = 0
    for item in readability._check_text(plan, placed, profile_map):
        total += 1
        if name in item.objects:
            own += 1
    for item in readability._check_text_on_wire(plan, profile_map):
        total += 1
        if item.objects[0] == name:
            own += 1
    return own, total


def _escape_named_rows(
    ctx: _Context,
    placement: _Placement,
    drawn: Sequence[Any],
    expressions: Mapping[str, _Expression],
    router: _Router,
    segments: list[LayoutSegment],
    offenders: Sequence[int],
    labels: Sequence[LayoutLabel],
    symbols: Sequence[LayoutPowerSymbol],
    assemble: Callable[[], LayoutPlan],
) -> int:
    """Move each offending run aside until **its own row** clears.

    The ladder tries one push at a time and asks the gate's two row rules about
    each candidate (`_row_offences`): the first push whose row has no violation
    left and adds none elsewhere wins; failing that, the push that leaves the
    fewest is taken, so a stubborn row gets closer each round instead of standing
    still. A row that cannot be cleared at all is left exactly where it was —
    the caller re-grades and refuses with the gate's own line, which is the honest
    answer to a wire with no room for its name.

    Legality is checked first and cheaply (`_polyline_legal`): a push that would
    put the wire through a body, along another net's run or on a foreign
    connection is not a candidate at all.

    ``placement`` is the compiler's own placement (the pin geometry
    `_blocked_points` reads) and ``drawn`` is `readability._placed_parts`' answer
    for the same plan — the two halves of one page, each in the shape the routine
    that needs it takes.
    """
    profile_map = ctx.book
    moved = 0
    for index in sorted(offenders):
        if not 0 <= index < len(segments):
            continue
        segment = segments[index]
        if not segment.net:
            continue
        baseline = _row_offences(assemble(), drawn, profile_map, index)
        others = [item for position, item in enumerate(segments) if position != index]
        blocked = _blocked_points(
            ctx, placement, segment.net, labels, symbols, others,
        )
        pads = [point for _member, point in expressions[segment.net].points]
        best: tuple[list[tuple[float, float]], tuple[int, int]] | None = None
        chosen: list[tuple[float, float]] | None = None
        tried = 0
        for delta in _escape_deltas(ctx.budget.grid):
            points = _escape_run(
                list(segment.points), delta, pads,
                [item.points for item in others if item.net == segment.net],
            )
            if points is None:
                continue
            if not _polyline_legal(
                router, points, blocked, others, segment.net, segment.points, pads,
            ):
                continue
            segments[index] = LayoutSegment(net=segment.net, points=points)
            got = _row_offences(assemble(), drawn, profile_map, index)
            segments[index] = segment
            tried += 1
            if got[0] == 0 and got[1] <= baseline[1]:
                chosen = points
                break
            if got[0] < baseline[0] and (best is None or got[0] < best[1][0]):
                best = (points, got)
            if tried >= NAME_ESCAPE_TRIES:
                break
        if chosen is None and best is not None:
            chosen = best[0]
        if chosen is not None:
            segments[index] = LayoutSegment(net=segment.net, points=chosen)
            moved += 1
    return moved


def _polyline_legal(
    router: _Router,
    points: Sequence[tuple[float, float]],
    blocked: set[tuple[float, float]],
    others: Sequence[LayoutSegment],
    net_id: str,
    was: Sequence[tuple[float, float]],
    pads: Sequence[tuple[float, float]],
) -> bool:
    """May this wire be drawn as it is, with the net it belongs to still one node?

    The same questions the router asks of a step — no obstacle box entered (parts,
    text rows, pin lines, every flag's reserved box), no running along another
    net's run, no point of ours on one of them and no foreign connection *inside*
    one of ours — applied to a whole polyline. 148 adds the last of those: a leg
    that carries a foreign pin tip or wire vertex through its **interior** is a
    joint in the editor's model, which is an undeclared short, and the router's
    own search never has to ask it because it only ever steps between lattice
    nodes.

    And it adds the question a *move* makes possible and a route never does: does
    the net stay connected? Every vertex of this net's own wiring — and every
    **pad** of it — that lay on the run being moved has to lie on the moved one
    too. Measured on 144's lock table, where pushing `CLAMP`'s trunk aside left
    `C5.1` standing on nothing: that pad had no stub of its own, it simply lay on
    the trunk, so only the pad list can see it go (`required-pin-not-connected`
    on `C5.1`, and the net split in two).
    """
    for start, end in zip(points, points[1:]):
        if _key(start) == _key(end):
            return False
        for box in router.boxes:
            if _segment_hits_box(start, end, box):
                return False
        for point in blocked:
            if _strictly_on_segment(point, start, end):
                return False
        for other in others:
            if other.net == net_id:
                continue
            for a, b in zip(other.points, other.points[1:]):
                if _collinear_overlap(start, end, a, b):
                    return False
    for point in points[1:-1]:
        for other in others:
            if other.net == net_id:
                continue
            for a, b in zip(other.points, other.points[1:]):
                if _strictly_on_segment(point, a, b):
                    return False
    for point in points[1:]:
        if _key(point) in blocked:
            return False
    for other in others:
        if other.net != net_id:
            continue
        for point in other.points:
            if _on_polyline(point, points):
                continue
            # A vertex of this net's own wirinG is **lost** only when it *teed
            # into the run being moved* — inside one of its legs, not at a shared
            # end. A boundary point is still a vertex of `other` and still
            # connected; a tee is left standing on nothing (measured on 144's lock
            # table, where moving `CLAMP`'s trunk left `C5`'s stub ending in air).
            if any(
                _strictly_on_segment(point, a, b)
                for a, b in zip(was, was[1:])
            ):
                return False
    for point in pads:
        if not _on_polyline(point, was) or _on_polyline(point, points):
            continue
        # A pad the moved run no longer reaches is still connected when the net's
        # **own other wiring** passes through it (069 sec.2's far pad is the
        # trunk's end): the net is one node either way, and `_escape_run` only
        # lets such a pad go when it is.
        if any(
            _on_polyline(point, list(other.points))
            for other in others
            if other.net == net_id
        ):
            continue
        return False
    return True


#: Where a hard readability violation's own kind sends the refusal (053 sec.4).
#:
#: The gate is one mechanism — every plan the checker throws out is refused here
#: — but the four categories are about **what has to change**, and the checker's
#: own line says which of them that is: a `user-lock-violated` line is the
#: engineer's intent contradicting the drawing, a `required-pin-not-connected`
#: line is a pin the circuit names that the symbol does not carry. Calling both
#: of them "a compiler-side geometry problem, not a spec problem" (the old
#: hard-coded wording) points the reader at the region, the ladder and the
#: symbol set — while the same failure printed, one line above, the spec object
#: that is actually wrong. That is the "万能兜底" 143 dug up, and the fix is the
#: dispatch itself, not a longer sentence: the kind is already in hand (it is
#: what builds the evidence line), so it costs no extra measurement.
#:
#: Kinds **not** named here stay `layout-unsat` with the gate's own action, and
#: that is deliberate: a wire through a body, an overlapping text, a drawing that
#: leaves the page, a dangling end, an undeclared junction, a keep-out conflict
#: and a net the drawing partitions are the compiler's own drawing choices, and
#: the region / ladder / symbol set are exactly the knobs it searches for them.
GATE_REFUSAL_KINDS: dict[str, str] = {
    readability.KIND_USER_LOCK_VIOLATED: FAILURE_PRESENTATION_POOR,
    readability.KIND_REQUIRED_PIN_NOT_CONNECTED: FAILURE_FACTS_MISSING,
    readability.KIND_NC_PIN_CONNECTED: FAILURE_CIRCUIT_INVALID,
}


def _named_lock(ctx: _Context, objects: Sequence[str]) -> Any:
    """The lock a violation's objects name, if one is named."""
    for lock in ctx.presentation.user_locks:
        marker = f"[{lock.part_id}]"
        if any(marker in item for item in objects):
            return lock
    return None


def _gate_failure(
    ctx: _Context, variant: _Variant, violations: Sequence[Any]
) -> GrammarFailure:
    """The refusal for a plan the readability gate threw out,归口 by kind.

    One refusal per variant, carrying the checker's own line as the detail — the
    same evidence the reader sees either way. What the dispatch changes is the
    **category**, the **subject** and the **action**, so the four categories keep
    meaning what 053 sec.4 says they mean and the action names the repair that
    actually changes the answer.
    """
    first = violations[0]
    count = len(violations)
    head = (
        f"{variant.label}: the independent readability checker refused "
        f"{count} hard violation(s) — {first.render()}"
    )
    category = GATE_REFUSAL_KINDS.get(first.kind, FAILURE_LAYOUT_UNSAT)
    if category == FAILURE_PRESENTATION_POOR:
        lock = _named_lock(ctx, first.objects)
        subject = lock.part_id if lock is not None else (first.objects[0] if first.objects else "gate")
        named = f"{LOCK_PREFIX}[{subject}]"
        return GrammarFailure(
            category=category,
            subject=subject,
            detail=(
                f"{head} — the drawing the compiler placed contradicts {named}, "
                "and the lock is the input it may not quietly ignore"
            ),
            action=(
                f"honour {named} or change it: the engineer's lock is drawn "
                "exactly or named here. Editing the region, the ladder or the "
                "symbol set cannot fix it — the drawing is refused because it "
                "breaks the lock, not because it does not fit"
            ),
        )
    if category == FAILURE_FACTS_MISSING:
        subject = first.objects[-1] if first.objects else "gate"
        return GrammarFailure(
            category=category,
            subject=subject,
            detail=f"{head} — the circuit names a pin the drawing has no tip for",
            action=(
                "fix the side the checker's line names: a net in the CircuitSpec "
                "listing a pin the symbol does not carry, or a symbol whose "
                "profile is missing that pin. No region, ladder or symbol-set "
                "change can draw a pin that is not there (`facts-missing`, 053 "
                "sec.4)"
            ),
        )
    if category == FAILURE_CIRCUIT_INVALID:
        subject = first.objects[-1] if first.objects else "gate"
        return GrammarFailure(
            category=category,
            subject=subject,
            detail=(
                f"{head} — the drawing connects a pin the circuit declares "
                "unconnected, so the two documents contradict each other"
            ),
            action=(
                "connect or release the pin: drop it from the net the drawing "
                "wires it to, or drop its no-connect declaration — the "
                "contradiction is between the documents, not inside this "
                "compiler's search"
            ),
        )
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject="gate",
        detail=head,
        action=(
            "this is a compiler-side geometry problem, not a spec problem: "
            "the region, the ladder or the symbol set has to change before "
            "this variant can be drawn"
        ),
    )


def _overflow(ctx: _Context, plan: LayoutPlan) -> GrammarFailure | None:
    """Does the finished drawing leave the stated region (margins included)?

    Measured on the *placed* plan, so the answer is about the picture that exists
    rather than about a prediction: the boxes are the parts, the text, the labels
    and the wires, in the same frame the readability checker will judge them in.
    A drawing that does not fit is refused with the size it needed — and the text
    sizes in it are the font metrics, never a squeezed variant (053 sec.5
    scenario 10).
    """
    page = ctx.budget.page_box
    if page is None:
        return None
    box = _plan_bbox(ctx, plan)
    inner = (
        page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
        page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
    )
    if (
        box[0] >= inner[0] - 1e-6 and box[1] >= inner[1] - 1e-6
        and box[2] <= inner[2] + 1e-6 and box[3] <= inner[3] + 1e-6
    ):
        return None
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject="region",
        detail=(
            "the smallest legal layout of this circuit is "
            f"{box[2] - box[0]:g} x {box[3] - box[1]:g} canvas units, and the "
            f"stated region is {page[2] - page[0]:g} x {page[3] - page[1]:g} with "
            f"a {PAGE_MARGIN:g}-unit margin on each side — the text is not squeezed "
            "to fit and the pitches are already at the geometric minimum"
        ),
        action=(
            f"enlarge the region to at least "
            f"{box[2] - box[0] + 2 * PAGE_MARGIN:g} x "
            f"{box[3] - box[1] + 2 * PAGE_MARGIN:g} canvas units, move the "
            "keep-out that takes the room, or move the lock that pushes the "
            "drawing out of it"
        ),
    )


def _region_failure(ctx: _Context, boxes: Sequence[Box]) -> GrammarFailure | None:
    """Is the stated region already too small for the parts and their text?

    Measured before routing on purpose: a search clipped to a region that cannot
    hold the drawing fails for a reason that reads like a wiring problem, and the
    honest answer is the space one (053 sec.5 scenario 10). The numbers are the
    smallest legal area of the *placed* boxes, so the action can name a size —
    and the text sizes are the font metrics, never a squeezed variant.
    """
    page = ctx.budget.page_box
    if page is None or not boxes:
        return None
    width = max(box[2] for box in boxes) - min(box[0] for box in boxes)
    height = max(box[3] for box in boxes) - min(box[1] for box in boxes)
    available_w = (page[2] - page[0]) - 2 * PAGE_MARGIN
    available_h = (page[3] - page[1]) - 2 * PAGE_MARGIN
    if width <= available_w + 1e-6 and height <= available_h + 1e-6:
        return None
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject="region",
        detail=(
            "the smallest legal layout of this circuit is at least "
            f"{width:g} x {height:g} canvas units (parts and their text, at the "
            "font-metric size and the symbols' own pin spans), and the stated "
            f"region is {page[2] - page[0]:g} x {page[3] - page[1]:g} with a "
            f"{PAGE_MARGIN:g}-unit margin on each side — the text is not squeezed "
            "to fit and the pitches are already at the geometric minimum"
        ),
        action=(
            f"enlarge the region to at least "
            f"{width + 2 * PAGE_MARGIN:g} x {height + 2 * PAGE_MARGIN:g} canvas "
            "units, move the keep-out that takes the room, or move the lock that "
            "pushes the drawing out of it"
        ),
    )


def _flag_anchor(
    router: _Router,
    point: tuple[float, float],
    direction: tuple[float, float],
    blocked: set[tuple[float, float]],
    *,
    leads: Sequence[float] = (),
    fits: Callable[[tuple[float, float], float], bool] | None = None,
    up: bool = True,
    boxes: Sequence[Box] | None = None,
    crossings: list[str] | None = None,
) -> tuple[tuple[float, float], tuple[tuple[float, float], ...] | None, float]:
    """Where a flag's anchor goes, the lead that reaches it, and which way it hangs.

    Returns ``(anchor, lead, hang)``: ``lead`` is the straight run from the point to
    the anchor (``None`` when the flag sits *on* the point — a legal placement,
    since the flag's own anchor is a conductor there), and ``hang`` is ``+1``/``-1``,
    the vertical :func:`_flag_rotation` turns into 0 or 180.

    A flag is placed *on* the wire that reaches it (that is what makes the editor
    see the connection). A **vertical** lead is the whole story and the glyph hangs
    further out along it. A **horizontal** one is 岳's own shape (069 sec.10): the run
    leaves the pin, runs out ``length`` and then turns ``jog`` units **up** (a rail)
    or down (a ground), and the flag stands at the end of that turn — his own VIN
    comes out 40 units and turns 20 up, his left VOUT pad 60 out and 30 up, which is
    what keeps a pad's flag from being read as shorted to the rail's pin ten units
    away. The run is *bent*, and the page layer accepts a bent lead as long as every
    point of it lies on the net's own wiring (`pagecompiler._is_lead`).

    148: **every reach is tried with the turn before any reach is tried without
    one.** The unturned run — a flag standing in its own pad's row — is the
    degenerate form of 069 sec.10's shape, and it is the form 074 sec.3 rejects on
    the duplicate-VOUT pad (there the flag's name row lies across the input rail).
    It used to be the *last* rung of the nearest length rather than of the whole
    ladder, so a pad whose turn was blocked by one text row settled for the
    unturned run and 岳's rule was lost. A vertical run has nowhere to turn and
    keeps its single round.

    ``leads`` are lengths to try before the default ladder, and ``fits`` is how a
    stub that has to *reach* somewhere is chosen (069 sec.1's far pad): the lead may
    be clear while the flag's own box at its end lands on a neighbouring part, on a
    foreign wire or outside the page, and the pad it names is then brought out
    elsewhere instead — **nearest first** (069 sec.11: 近位真的被占才许走远), then
    farther, and only when nothing anywhere fits does the flag end on its pin.

    074 adds one more refusal to that ladder, and it is the last word: a lead that
    cuts **through another net's wire** is not drawn. 岳 read the landed page and
    said it plainly (「第一眼以为5V和3V3的旗标短接在一块了」) — an electrician's
    first reading of "this name hangs across that rail" is a short, and a drawing
    whose first reading is a short is wrong however the netlist came out. So a rung
    that everything else accepted is refused, the ladder goes on to the next shape
    (farther out, the other way up/down, another escape direction — the caller's
    loop), and every refusal is appended to ``crossings`` so the caller can report
    the measured reason when *no* rung survives instead of drawing a short or a
    flag standing on its own pin. A rung the box test already refused is not
    recorded: it was never a candidate, and the crossing on it proves nothing.
    """
    lengths: list[float] = []
    for length in (
        *leads, FLAG_LEAD, router.grid * 2.0,
        2.0 * FLAG_LEAD, 4.0 * FLAG_LEAD, 0.0,
    ):
        if length not in lengths:
            lengths.append(length)
    natural = 1.0 if up else -1.0
    if direction[1] != 0.0:
        # A vertical run has nowhere to turn: the flag hangs at its end.
        rounds: list[tuple[tuple[float, ...], tuple[float, ...]]] = [
            ((math.copysign(1.0, direction[1]),), (0.0,)),
        ]
    else:
        # 069 sec.10's shape is a run out **and a turn**, and the turn is what puts
        # the flag past the conductor the pad's own row runs into — 074 sec.3, on
        # the duplicate-VOUT pad: level with its pad the flag's name row lies
        # across the input rail, and the run that only *reaches* it is not the
        # drawing. So every reach is tried with 岳's own jog first (his 20, then a
        # shorter one), and the unturned run — a flag in its pad's own row — is
        # the ladder's last resort rather than its cheapest form (148).
        rounds = [
            ((natural, -natural), (FLAG_JOG, FLAG_JOG / 2.0)),
            ((natural, -natural), (0.0,)),
        ]
    for hangs, jogs in rounds:
        for length in lengths:
            corner = _rounded((
                point[0] + direction[0] * length,
                point[1] + direction[1] * length,
            ))
            if _close(length, 0.0):
                return corner, None, natural
            for hang in hangs:
                for jog in jogs:
                    anchor = corner if _close(jog, 0.0) else _rounded(
                        (corner[0], corner[1] + hang * jog)
                    )
                    lead = (_rounded(point), corner) if _close(jog, 0.0) else (
                        _rounded(point), corner, anchor
                    )
                    # The anchor is a conductor of its own: a flag placed on a *foreign*
                    # pin tip or inside a foreign wire's span would join two nets the spec
                    # keeps apart (measured: a rail's flag run 10 units up landed exactly
                    # on the pin above it). `_span_free` guards the run's interior; the far
                    # end needs its own test, which is also what `_vertex_clear` means for
                    # a wire vertex.
                    if _key(anchor) in blocked or not _vertex_clear(router, anchor):
                        continue
                    if not _span_free(router, point, corner, blocked, boxes, wire=False):
                        continue
                    if not _close(jog, 0.0):
                        if not _vertex_clear(router, corner):
                            continue
                        if not _span_free(
                            router, corner, anchor, blocked, boxes, wire=False
                        ):
                            continue
                    if fits is not None and not fits(anchor, hang):
                        continue
                    # 074: the last word, and only over rungs that pass everything
                    # else — see the docstring. Recorded, never drawn.
                    crossed = _lead_crossing(router, lead)
                    if crossed is not None:
                        if crossings is not None:
                            crossings.append(crossed)
                        continue
                    return anchor, lead, hang
    return _rounded(point), None, natural


def _inside(box: Box, outer: Box) -> bool:
    """Is this box within ``outer``? The same tolerance the overflow check uses."""
    return (
        box[0] >= outer[0] - 1e-6 and box[1] >= outer[1] - 1e-6
        and box[2] <= outer[2] + 1e-6 and box[3] <= outer[3] + 1e-6
    )


def _flag_box(
    profile: SymbolProfile,
    rotation: float,
    anchor: tuple[float, float],
    net_id: str,
    margin: float = FLAG_CLEARANCE,
) -> Box:
    """Everything one flag occupies: its glyph, its name text, and a margin.

    069 sec.8 — 岳, on the landed P23 page: 「3V3的旗标标识和5V的导线重合了」. The glyph
    box alone is **not** the flag: the host prints the net's name beside it, so a
    flag that keeps only its glyph clear still touches its neighbours. This is the
    box the placement keeps free of foreign wiring: the glyph, that line, and the
    clearance.

    **148: the name row is the host's measured one** (`core.textmetrics.
    flag_name_box`), not a second model of it. 146 modelled the row as a band
    6–16 units above the anchor (the two constants that used to sit beside
    :data:`FLAG_CLEARANCE`); 147 measured where the host actually prints it — the
    ten units immediately past the **glyph**, on the far side of the connection —
    and put *that* box in the readability gate. The two agree only where the glyph
    is ten units tall, so for a flag whose glyph hangs below its anchor the
    compiler reserved a band that ended ten units short of the row the gate
    (rightly) refuses a conductor inside. Measured on `test/P1` after 148's flag
    work: the HVDC flag's name row is `(115.8, 725.5)-(144.2, 735.5)` while the
    box reserved for it stopped at 731.5, and SW's run at `y=730` went straight
    through the difference. One model for the drawing and the gate is the whole of
    the fix.
    """
    glyph = flag_glyph_box(profile, rotation=rotation, anchor=anchor)
    if glyph is None:
        glyph = (anchor[0], anchor[1], anchor[0], anchor[1])
    # A **ground** flag prints no name at all: the symbol is its own name, and the
    # gate says so (`readability._flag_name_row` returns nothing for the ground
    # family). Reserving a row it never prints is a box larger than the one the
    # checker grades, and 148 measured the cost — a `GND` pad the drawing could
    # have flagged was refused for want of room that does not exist.
    text = None
    if flag_glyph_kind(profile) != FLAG_GLYPH_KIND_GND:
        text = textmetrics.flag_name_box(
            glyph, anchor, net_id, axis_up=glyph[3] > anchor[1],
        )
    if text is None:
        text = glyph
    return (
        min(glyph[0], text[0]) - margin,
        min(glyph[1], text[1]) - margin,
        max(glyph[2], text[2]) + margin,
        max(glyph[3], text[3]) + margin,
    )


def _flag_room(
    router: _Router,
    solids: Sequence[Box],
    inner: Box | None,
    blocked: set[tuple[float, float]],
) -> Callable[[Box, Box], bool]:
    """Is this box free of everything the drawing has already put down?

    Four questions, the first three of which the placement already asked about its
    glyph and the last of which is 145a's:

    * does it land on a part or a text box, or leave the page;
    * does it swallow a **foreign connection** — another net's pin tip, flag anchor
      or wire vertex (a flag on one of those joins two nets the spec keeps apart);
    * does it **touch a foreign net's wire**? ``router.edges`` is every wire but this
      net's own, so the rail the flag hangs from is not in its own way, while the
      neighbouring rail 岳 found a glyph grazing is;
    * when the caller is the **reservation pass**
      (``router.reserve_strict``, :func:`_lead_lane_reservations`), does it sit on
      a lane another net's flag already holds? Two flags may not swallow each
      other's lane, and the pass that *decides* the lanes has to be able to see
      that while there is still a choice — a pad whose first shape collides with
      a lane already spoken for is then brought out another way instead of losing
      its lane entirely (measured: without this, `C13.2` and `T1.6` got no lane
      at all on 144's own arrangement, and the flag gate refused the page).

      The **placement** pass deliberately asks the original question. A
      reservation is not something the drawing can see — by the time a flag is
      drawn, the lane it was promised is free of wires — and a flag that lands on
      *another* reserved lane is harmless: it takes a rung its box is free at, and
      the other lane is simply wasted. Asking both passes the strict question
      instead made them reach **different rungs** (the strict one skips a rung the
      loose one takes), and 053b's AMS1117 scenes measured the cost: a rail flag
      pushed off its rung onto its neighbour's glyph, two flags overlapping,
      refused by the gate.
    """
    def free(tight: Box, held: Box) -> bool:
        """``tight`` touches nothing; ``held`` (margin grown) touches no conductor.

        069 sec.11: a part's *annotation* is not a conductor and carries no
        "don't come near" rule — only a true overlap is wrong there (`_check_text` is
        text-on-text, and the gate has no wire-over-text rule), so the box that meets
        the solids is the tight one. Wires, pins, flag anchors and the page edge keep
        the margin: that is 069 sec.8's 「不许贴上」, and it is about the drawing's
        conductors.
        """
        if any(_overlaps(tight, solid) for solid in solids):
            return False
        if inner is not None and not _inside(held, inner):
            return False
        for start, end in router.edges:
            if _segment_hits_box(start, end, held):
                return False
        # 147: the flag's **own** net's runs too. ``router.edges`` skips them so a
        # lead is never in its own way — but the glyph a flag stands in is not a
        # lead, and 岳's `SEC_12V` flag on `test/P1` had its own trunk turning
        # inside the pennant (three 5-unit overlaps, `outputs/147/
        # 17_wire_on_lines_146.txt`). A rail that must pass a flag now passes
        # *beside* it, and `readability`'s `wire-through-body` measures the same
        # box against the same runs.
        for start, end in router.own_edges:
            if _segment_hits_box(start, end, held):
                return False
        for point in blocked:
            if held[0] <= point[0] <= held[2] and held[1] <= point[1] <= held[3]:
                return False
        # 145a: the **reservation pass** may not swallow a lane another flag has
        # already been promised — see the docstring. The placement pass asks the
        # original question, because by then the lane it was promised is free of
        # wires; asking both made them ask different questions and 053b's
        # AMS1117 scenes measured the cost (two flags pushed onto each other's
        # glyph, refused by the gate).
        if router.reserve_strict and router.reserved:
            for cell in _nodes_in_box(router, held):
                owner = router.reserved.get(cell)
                if owner is not None and owner != router.reserved_exempt:
                    return False
        return True

    return free


def _place_flag(
    net_id: str,
    profile: SymbolProfile,
    ref: str,
    anchor: tuple[float, float],
    rotation: float,
    lead: Sequence[tuple[float, float]] | None,
    segments: list[LayoutSegment],
    symbols: list[LayoutPowerSymbol],
    occupied: list[Box],
    solids: list[Box],
) -> None:
    """Record one flag: the symbol, the lead that reaches it, and the box it takes."""
    symbols.append(LayoutPowerSymbol(
        symbol_ref=ref,
        symbol_hash=profile.geometry_hash(),
        net=net_id,
        x=anchor[0],
        y=anchor[1],
        rotation=rotation,
    ))
    if lead is not None:
        segments.append(LayoutSegment(net=net_id, points=list(lead)))
    glyph = flag_glyph_box(
        profile, rotation=rotation, anchor=anchor,
    ) or (anchor[0], anchor[1], anchor[0], anchor[1])
    occupied.append(glyph)
    solids.append(glyph)


def _flag_crossing_failure(
    net_id: str,
    pin: tuple[float, float],
    crossings: Sequence[str],
    subject: str,
) -> GrammarFailure:
    """The refusal 074 states when every lead a name could hang on crosses a wire.

    ``crossings`` is the ladder's own measurement: each entry names the run that
    crossed, the foreign net it crossed and the point they met at, so the report
    says *which* conductor is in the way instead of "no legal placement" — 053
    sec.5 scenario 10's rule, and the reason the whole rung list is kept rather
    than the last one (a report that names one obstacle is actionable; one that
    names none is a puzzle).

    It is a ``layout-unsat`` and not a downgrade on purpose: the alternative the
    ladder would otherwise take — 069 sec.8's flag standing on its own pin — is the
    form 岳 rejected on the landed page (「第一眼以为5V和3V3的旗标短接在一块了」), and
    silently producing *that* is what this batch exists to stop. Nothing here adds
    a junction to make a crossing look intended, either: a dot on a foreign wire
    would join two nets the CircuitSpec keeps apart.
    """
    more = (
        "" if len(crossings) == 1
        else f" — {len(crossings)} rung(s) were measured, the first one above"
    )
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject=net_id,
        detail=(
            f"{subject}: no flag for net {net_id!r} at {_point_text(pin)} can be "
            "hung here — every lead that fits inside the region crosses another "
            "net's wire, and a flag lead through another net's conductor is read "
            "as a short before anything else (岳, on the landed page: "
            "「第一眼以为5V和3V3的旗标短接在一块了」). Measured: "
            + crossings[0] + more
        ),
        action=(
            "move the part whose run is named above — or the run itself — so this "
            "pin has a side to hang its flag on that no other net crosses, or "
            "enlarge the region so the lead can reach around it; the drawing is "
            "refused rather than hung across another net's wire, and no junction is "
            "welded on to make a crossing look intended"
        ),
    )


def _rail_flag(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    expression: _Expression,
    pin: tuple[str, tuple[float, float]],
    profile: SymbolProfile,
    ref: str,
    router: _Router,
    segments: list[LayoutSegment],
    symbols: list[LayoutPowerSymbol],
    occupied: list[Box],
    solids: list[Box],
    blocked: set[tuple[float, float]],
    bodies: Sequence[Box] | None = None,
) -> tuple[tuple[float, float] | None, GrammarFailure | None]:
    """Hang a rail's own flag from the rail, by a short **vertical** run.

    069 sec.7, from 岳's own hand: a rail that is drawn as a wire says nothing in
    the one way he reads a rail (「P23 5V部分为什么不给旗标？」), so its flag hangs a
    short vertical run off the rail and stands upright — his VIN, out along the
    rail and then up to the flag. The run is the only line this adds, and it is a
    straight two-point one, which is also what lets the page layer drop it cleanly
    if it re-states this net at a module boundary.

    **148: the seat is not decided here.** It was decided and reserved by
    :func:`_seat_wire_flags` before the first wire — which is what makes the rail
    route *around* the flag instead of under it — and this call replays that one
    decision (`router.flag_seats`). Two readers of one decision is the same rule
    145a pinned for a flag's lead (:func:`_flag_pin_lead`), for the same measured
    reason: on `test/P1` the wires were laid first and the HVDC flag ended up
    standing on `T1.1`'s own pin, its name row printed across the SW run.

    A seat the reservation pass could not take — the lane would have swallowed a
    foreign pin tip, or another flag already held it — is decided **here**, with
    the wiring on the page, by the same ladder 145a uses for a lead
    (:func:`_flag_pin_lead`). What never happens is 069 sec.8's flag standing on
    its own pin: ``lead is None`` is returned as a refusal that names the pin
    (:func:`_rail_flag_room_failure`), because that shape is the one 岳 read as a
    short.
    """
    seat = router.flag_seats.get((net_id, pin[0]))
    if seat is None:
        anchor, rotation, lead, failure = _rail_flag_seat(
            ctx, placed, net_id, pin[0], pin[1], profile, router, blocked,
            solids, bodies,
        )
        if lead is None:
            return None, failure
        seat = (anchor, rotation, lead)
    anchor, rotation, lead = seat
    _place_flag(
        net_id, profile, ref, anchor, rotation, lead,
        segments, symbols, occupied, solids,
    )
    return anchor, None


def _wire_flag_seats(
    ctx: _Context,
    expressions: Mapping[str, _Expression],
    net_order: Sequence[str],
) -> list[tuple[str, str, tuple[float, float], SymbolProfile, str, str]]:
    """Every flag a **wire-style** net will carry: ``(net, member, pin, profile, ref, cls)``.

    148: the flags the wiring has not been drawn for yet. Two shapes, and they
    are the two the per-net loop cannot place before the wires exist:

    * **069 sec.7's rail flag** — a power rail drawn as a wire carries one of its
      own, hung off the rail at the pin that supplies it (the same pin
      :func:`_power_flag_pin` picks for the placement);
    * **088b sec.1's ground outlet** — a declared group states its return with
      one symbol of its own, at the rail's far end (:func:`_gnd_outlet_pin`).

    Both are decided by the **expression alone**, which is the whole point: the
    pin is a property of the circuit, not of the route, so the flag's seat can be
    chosen and reserved before a single wire is laid. Reading them out here means
    the reservation pass and the placement loop agree about *which* flags are
    coming without either of them having to guess.
    """
    out: list[tuple[str, str, tuple[float, float], SymbolProfile, str, str, bool]] = []
    outlets = _gnd_outlet_nets(ctx)
    for net_id in net_order:
        expression = expressions[net_id]
        if expression.style != "wire":
            continue
        net = ctx.circuit.net(net_id)
        cls = net.cls if net is not None else "gnd"
        # A net whose flag symbols the library does not carry is drawn as a wire
        # with no flag at all (`_flag_wire_fallback`), so there is nothing to make
        # room for; and a net whose far pads are named by their own flags already
        # carries a symbol by the time the rail flag would be asked for.
        if expression.detached:
            continue
        wanted: list[tuple[str, tuple[float, float], str, bool]] = []
        if _power_needs_flag(ctx, net_id, ()):
            pin = _power_flag_pin(ctx, expression)
            if pin is not None:
                # 069 sec.7's rail flag: a vertical run off the rail (:func:`_rail_flag_seat`).
                wanted.append((pin[0], pin[1], "power", True))
        if net_id in outlets:
            pin = _gnd_outlet_pin(ctx, expression)
            if pin is not None:
                # 088b sec.1's outlet: an ordinary flag lead (:func:`_flag_pin_lead`).
                wanted.append((pin[0], pin[1], cls, False))
        for member, point, want_cls, vertical in wanted:
            profile, ref = _flag_plan(ctx, net_id, want_cls)
            if profile is None:
                continue
            out.append((net_id, member, point, profile, ref, want_cls, vertical))
    return out


def _rail_flag_room_failure(
    net_id: str,
    member: str,
    point: tuple[float, float],
    blocked_by: str,
) -> GrammarFailure:
    """074/148: the refusal when a rail's own flag has nowhere legal to stand.

    The alternative the ladder used to take — put the symbol on the pin anyway —
    is the form 岳 rejected on the landed page: standing there the glyph opens
    towards the run that leaves the pin and the name row lands across a foreign
    wire (`outputs/147/FINDINGS.md` sec.0.3, the HVDC flag on `T1.1`). 148 does
    not draw it: the drawing is refused, the pin and the obstacle are named, and
    the action says which two things can be moved.
    """
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject=net_id,
        detail=(
            f"net {net_id!r} is a rail drawn as a wire and every power flag on "
            f"it must be stated (069 sec.7), but no legal place to hang one was "
            f"found at the pin that supplies it, {member} at {_point_text(point)}: "
            f"{blocked_by}. The flag is not drawn on the pin instead — a flag "
            "standing on its own pin opens its glyph across the run that leaves "
            "the pin and prints its name row over whatever is beside it, which is "
            "the shape 岳 read as a short on the landed page"
        ),
        action=(
            "enlarge the region, move the neighbouring part the message names, or "
            "move the pin's own run so the flag has a side to hang on; a rail with "
            "a flag nobody could hang is refused rather than drawn on top of the "
            "wiring"
        ),
    )


def _flag_on_pin_refusal(
    net_id: str, member: str, point: tuple[float, float]
) -> GrammarFailure:
    """148: the pad's flag has nowhere legal to hang, and it is not put on the pin.

    069 sec.8's last resort used to be "stand on the pin": a legal placement in
    the editor's model (the anchor is a conductor) and better than a pad with no
    name at all. 148 removes it, for the reason 岳 gave on the landed page — a
    flag standing on its own pin opens its glyph towards the wire that leaves the
    pin, and the host prints its name row in the band just past the glyph, so the
    name lands across that wire. That is the HVDC flag on `T1.1`
    (`outputs/147/FINDINGS.md` sec.0.3, the page lint's first ERROR). The
    alternative — refuse — is the honest answer to a pin the drawing really has
    no room beside, and it names the pad.
    """
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject=net_id,
        detail=(
            f"net {net_id!r} is named by a flag of its own on {member} at "
            f"{_point_text(point)} (069 sec.1), and no lead fits anywhere around "
            "that pad: every direction the ladder tries — the pad's own escape "
            "side first, then up, down and both across — lands the flag's glyph, "
            "its name row and their clearance on a part, a text row, another "
            "net's wire or the page's edge. The flag is not drawn on the pin "
            "instead: standing there its glyph opens across the run that leaves "
            "the pin and its name row prints over whatever is beside it, which is "
            "the shape 岳 read as a short on the landed page"
        ),
        action=(
            "enlarge the region, move the neighbouring part that crowds this pad, "
            "or move the pad's own run — a pad whose flag nobody could hang is "
            "refused rather than drawn on top of the wiring"
        ),
    )


def _rail_flag_seat(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    member: str,
    point: tuple[float, float],
    profile: SymbolProfile,
    router: _Router,
    blocked: set[tuple[float, float]],
    solids: Sequence[Box],
    bodies: Sequence[Box] | None = None,
) -> tuple[tuple[float, float], float, tuple[tuple[float, float], ...] | None,
           GrammarFailure | None]:
    """Where a rail's own flag stands: ``(anchor, rotation, lead, failure)``.

    069 sec.7 first, and 069 sec.10 second. The first shape the ladder reaches for
    is a **straight vertical run** off the rail — 岳's own VIN, and the one the page
    layer can drop cleanly when it re-states the net at a module boundary — hung
    :data:`FLAG_JOG` out, then :data:`FLAG_LEAD`, then the grid's own step and the
    two long reaches, a rail lifting and a ground hanging, each way round tried.

    Only when no straight run fits at all does the **bent** lead come out
    (:func:`_flag_pin_lead`): the run leaves the pin, travels out and turns up —
    岳's other hand-drawn shape (069 sec.10). It is a second choice because the
    turn is a shape the page layer has to keep rather than drop, and because a
    drawing that can state its rail with one straight run should.

    The run starts at the **pin**, not somewhere along the rail: the rail does not
    exist yet when the seat is taken (148 decides it before the first wire so the
    rail can route *around* it), and inventing a point on a wire nobody has drawn
    is how a reservation and the flag it reserved for come to disagree.

    ``lead is None`` is a refusal — never 069 sec.8's flag standing on its own pin,
    which is the shape 岳 read as a short on the landed page.
    """
    family = flag_glyph_kind(profile)
    natural = 1.0 if family != FLAG_GLYPH_KIND_GND else -1.0
    inner = None
    if ctx.budget.page_box is not None:
        page = ctx.budget.page_box
        inner = (
            page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
            page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
        )
    room = _flag_room(router, solids, inner, blocked)
    crossings: list[str] = []
    for hang in (natural, -natural):
        def fits(anchor: tuple[float, float], _hang: float = hang) -> bool:
            rotation = _flag_rotation((0.0, _hang), family)
            return room(
                _flag_box(profile, rotation, anchor, net_id, margin=0.0),
                _flag_box(profile, rotation, anchor, net_id),
            )

        anchor, lead, placed_hang = _flag_anchor(
            router, point, (0.0, hang), blocked,
            leads=(FLAG_JOG,), fits=fits, up=natural > 0.0, boxes=bodies,
            crossings=crossings,
        )
        if lead is not None:
            return (
                anchor, _flag_rotation((0.0, placed_hang), family), lead, None,
            )
    anchor, lead, hang, more = _flag_pin_lead(
        ctx, placed, net_id, profile, member, point, router, blocked, solids, bodies,
    )
    crossings.extend(more)
    if lead is not None:
        return anchor, _flag_rotation((0.0, hang), family), lead, None
    if crossings:
        return (
            point, 0.0, None,
            _flag_crossing_failure(
                net_id, point, crossings,
                f"the rail's own flag hangs at {member} (069 sec.7)",
            ),
        )
    return (
        point, 0.0, None,
        _rail_flag_room_failure(
            net_id, member, point,
            "every reach every ladder tries — a straight vertical run at 25, 30, "
            "the grid's step and the two long ones, up and down, then a run out "
            "along the pin's own side with a turn, and then the other three "
            "directions — lands the glyph, its name row and their clearance on a "
            "part, a text row, another net's wire or the page's edge",
        ),
    )


def _seat_wire_flags(
    ctx: _Context,
    placed: _Placement,
    expressions: Mapping[str, _Expression],
    net_order: Sequence[str],
    router: _Router,
    solids: Sequence[Box],
    bodies: Sequence[Box] | None,
    tips: set[tuple[float, float]],
    taken: dict[tuple[float, float], str],
) -> list[Box]:
    """148: decide and reserve every **wire-style** net's own flag, before any wire.

    The wall 145a's lane pass left standing: a rail flag hangs off the rail the
    compiler is *about to* route, so there was no lead to reserve in advance and
    the flag was placed after every wire — and on `test/P1` the wires had taken
    the only room beside it (`outputs/147b/FINDINGS.md` sec.1.3: nine scenes
    refused because a conductor ran through a flag's glyph or its name row).

    So the seat is decided here, on a page with no wires on it, and two things
    follow for the routing:

    * the lead and the flag's whole box are **reserved** (:func:`_take_lane`), so
      another net's wire may not take the lane the flag will be drawn on;
    * the flag's box is returned as an **obstacle** for every wire of every net,
      this one included — a reservation only keeps foreign wires off, and the
      rail a flag hangs from is exactly the run that used to cut through its own
      pennant (`outputs/147/FINDINGS.md` sec.0.2b).

    A seat that cannot be taken — the lead would swallow a foreign pin tip, or
    another flag already holds the lane — is **not** reserved: the flag is then
    placed by the ordinary ladder after the wires, exactly as it was before this
    pass existed. Nothing is taken away.
    """
    walls: list[Box] = []
    for net_id, member, point, profile, _ref, _cls, vertical in _wire_flag_seats(
        ctx, expressions, net_order
    ):
        # A rail flag reaches for 069 sec.7's straight vertical run first and only
        # then for the bent lead (:func:`_rail_flag_seat`); an outlet is placed by
        # the ordinary ladder (:func:`_flag_pin_lead`), which is where 088b puts it.
        blocked = _blocked_points(ctx, placed, net_id, [], [], [])
        router.reserved_exempt = net_id
        if vertical:
            anchor, rotation, lead, _failure = _rail_flag_seat(
                ctx, placed, net_id, member, point, profile, router, blocked,
                solids, bodies,
            )
        else:
            anchor, lead, hang, _crossings = _flag_pin_lead(
                ctx, placed, net_id, profile, member, point, router, blocked,
                solids, bodies,
            )
            rotation = _flag_rotation((0.0, hang), flag_glyph_kind(profile))
        if lead is None:
            continue
        cells: set[tuple[float, float]] = set()
        for start, end in zip(lead, lead[1:]):
            cells |= _lattice_nodes(router, start, end)
        cells.add(_key(anchor))
        box = _flag_box(profile, rotation, anchor, net_id, margin=0.0)
        cells |= _nodes_in_box(router, box)
        if not _take_lane(taken, cells, tips, {_key(point)}, net_id):
            continue
        router.flag_seats[(net_id, member)] = (anchor, rotation, lead)
        walls.append(box)
    return walls


def _lead_lane_reservations(
    ctx: _Context,
    placed: _Placement,
    expressions: Mapping[str, _Expression],
    net_order: Sequence[str],
    router: _Router,
    occupied: Sequence[Box],
    solids: Sequence[Box],
    bodies: Sequence[Box] | None,
) -> list[Box]:
    """145a T3: promise every **lead the plan will draw** its lane, before any wire.

    The wall this answers was measured on 144's flyback page: the wires are drawn
    first and the flags last, so by the time a ground pad asks for its flag the
    lane it would hang on is already taken. `T1.6`'s lead had to cut `SEC_12V`'s
    trunk and `R8.2`'s had seventeen refusals; refusing the page was the honest
    answer to a question that should never have been asked — the compiler knows
    which pins are going to be flagged *before* it routes anything.

    Three kinds of lead are reserved, and they are the same kind of thing: a run
    the finished drawing will carry, which the wiring must not take first.

    * a **flag's lead** — asked of :func:`_flag_pin_lead`, the *same* function the
      placement calls, so the lane promised here is the lane drawn there. The
      answer's nodes — the lead and the flag's own box (glyph, name text, 069
      sec.8's clearance) — are reserved.
    * a **label's name stub** (:func:`_label_stub_lane`) — the compiler already
      decides the label's box side (:func:`_label_at`), and the page layer draws
      the stub out that side (057/099d). Reserving its first rung keeps a wire
      from taking it: measured on the CH340 page, where `V3`'s wire had to move
      off the flag it used to cut and landed in the row `D+`'s stub leaves on,
      which pushed that stub 5 units *into* the symbol — the shape 099e measured
      as unreadable.
    * since 148, a **wire-style net's own flag** — 069 sec.7's rail flag and
      088b's ground outlet, whose seats are decided and reserved here by
      :func:`_seat_wire_flags`, because the rails they hang off are exactly what
      this pass runs before (:func:`_wire_flag_seats`).

    Everything goes into ``router.reserved`` against the net that owns it, and
    every wire of another net then treats those nodes as walls
    (``_Router._wall``, :func:`_span_free`, :func:`_vertex_clear`). A reservation
    that would stand on some part's pin tip, or that another net has already
    spoken for, is **not** taken: the lead is then drawn exactly as it was before
    this pass existed, and refused with 074's measurement if it truly does not
    fit. Nothing is taken away — the lane only ever adds room.

    Fills ``router.flag_walls``, which the caller folds into ``router.boxes``: the
    whole extent of every flag seated here, the box no wire of **any** net may
    enter. A reservation keeps *other* nets off a lane; this keeps a flag's own
    rail off its pennant too, which is the half 147 measured on `test/P1`.
    """
    # Every pin tip on the page. A reserved node that is one of them would wall
    # off a connection some wire has to make, which is worse than the crowded
    # flag this pass exists to avoid.
    tips: set[tuple[float, float]] = set()
    for part_id in placed.origins:
        profile = ctx.profile(part_id)
        for pin in profile.pins:
            point = _pin_point(
                ctx, part_id, pin.number, placed.poses, placed.origins
            )
            if point is not None:
                tips.add(_key(point))
    taken: dict[tuple[float, float], str] = {}
    router.reserved = taken
    #: The strict question: while the lanes are being decided, a flag's box may
    #: not swallow a lane another flag already holds (`_flag_room`). Cleared
    #: again below, so the placement asks the original question.
    router.reserve_strict = True
    for net_id in net_order:
        expression = expressions[net_id]
        if expression.style == "label":
            _reserve_label_stubs(
                ctx, placed, net_id, expression, router, occupied, tips, taken,
            )
            continue
        if expression.style != "flag":
            continue
        cls = _net_class(ctx, net_id) or "gnd"
        profile, _ref = _flag_plan(ctx, net_id, cls)
        if profile is None:
            continue
        family = flag_glyph_kind(profile)
        blocked = _blocked_points(ctx, placed, net_id, [], [], [])
        # This net's own pads are not obstacles: a lane starts *on* the pad it
        # names, and one flag's box may legitimately reach a sibling pad of the
        # same net. Only some **other** part's pin tip may not be reserved.
        own = {_key(point) for _member, point in expression.points}
        # This net's own reservations must not turn its own pads away, and a pad
        # of this net may not be blocked by its own earlier lane.
        router.reserved_exempt = net_id
        for member, point in expression.points:
            anchor, lead, hang, _crossings = _flag_pin_lead(
                ctx, placed, net_id, profile, member, point, router, blocked,
                solids, bodies,
            )
            if lead is None:
                continue
            cells: set[tuple[float, float]] = set()
            for start, end in zip(lead, lead[1:]):
                cells |= _lattice_nodes(router, start, end)
            cells.add(_key(anchor))
            cells |= _nodes_in_box(
                router,
                _flag_box(
                    profile, _flag_rotation((0.0, hang), family), anchor, net_id
                ),
            )
            _take_lane(taken, cells, tips, own, net_id)
    router.flag_walls = _seat_wire_flags(
        ctx, placed, expressions, net_order, router, solids, bodies, tips, taken,
    )
    router.reserved_exempt = ""
    router.reserve_strict = False



def _reserve_label_stubs(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    expression: _Expression,
    router: _Router,
    occupied: Sequence[Box],
    tips: set[tuple[float, float]],
    taken: dict[tuple[float, float], str],
) -> None:
    """Reserve the first rung of every stub this label net will be named by.

    One cell run per pin, from the pin out along the side the label's own box is
    on — the same side :func:`_label_stub_lane` reads off the box the compiler
    just chose, and the side the page layer's stub leaves on (:func:`_label_at`
    / `drawapply._label_stub_candidates`). The length is
    :data:`LABEL_LANE_STEPS` lattice steps, which is the page layer's own first
    rung (:data:`drawapply.LABEL_STUB_LENGTH`, 2 steps): reserving the first rung
    is enough, because a wire that would have taken it is what pushes the stub
    off the label's side in the first place.
    """
    router.reserved_exempt = net_id
    reach = LABEL_LANE_STEPS * router.grid
    for member, point in expression.points:
        part_id, _, token = member.partition(".")
        # `_label_at` *appends* the box it chooses to the list it is given, so it
        # is handed a copy: the real placement must see the same list it would
        # have seen without this pass.
        label = _label_for(
            ctx, net_id, part_id, token, point, placed, list(occupied)
        )
        direction = _label_stub_lane(label, point)
        far = _rounded((
            point[0] + direction[0] * reach, point[1] + direction[1] * reach,
        ))
        _take_lane(
            taken, _lattice_nodes(router, point, far), tips,
            {_key(point)}, net_id,
        )


def _label_stub_lane(
    label: LayoutLabel, point: tuple[float, float]
) -> tuple[float, float]:
    """The way a label's name stub leaves its pin: towards its own box.

    `drawapply._label_stub_candidates`'s own reading of the same two facts (the
    anchor and the box's centre, along the dominant axis), so the lane reserved
    here is the run the page layer draws first.
    """
    box = label.bbox
    centre_x = (box[0] + box[2]) / 2.0
    centre_y = (box[1] + box[3]) / 2.0
    dx, dy = centre_x - point[0], centre_y - point[1]
    if abs(dx) >= abs(dy) and abs(dx) > 1e-9:
        return (1.0 if dx > 0 else -1.0, 0.0)
    if abs(dy) > 1e-9:
        return (0.0, 1.0 if dy > 0 else -1.0)
    return (0.0, 1.0)


def _take_lane(
    taken: dict[tuple[float, float], str],
    cells: set[tuple[float, float]],
    tips: set[tuple[float, float]],
    own: set[tuple[float, float]],
    net_id: str,
) -> bool:
    """Promise these cells to `net_id`, unless someone else needs them.

    Two refusals, both deliberate: a cell that is a **foreign pin tip** (the lane
    would wall off a connection some wire has to make), and a cell another net has
    already been promised. Either way the lead is simply drawn the way it was
    before this pass existed.
    """
    if (cells & tips) - own:
        return False
    if any(taken.get(cell, net_id) != net_id for cell in cells):
        return False
    for cell in cells:
        taken[cell] = net_id
    return True


def _flag_pins(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    profile: SymbolProfile,
    ref: str,
    members: Sequence[tuple[str, tuple[float, float]]],
    router: _Router,
    segments: list[LayoutSegment],
    symbols: list[LayoutPowerSymbol],
    occupied: list[Box],
    solids: list[Box],
    blocked: set[tuple[float, float]],
    bodies: Sequence[Box] | None = None,
    *,
    stub: bool = False,
) -> GrammarFailure | None:
    """Put this net's flag on each of ``members``, on a lead out of its own pin.

    One flag per pin, all of them stating the same net: that is what makes a
    flag-joined net what 岳 drew — the pad, a short stub, the flag's name (069
    sec.1). Every flag stands upright (069 sec.7, see :func:`_flag_anchor`).

    ``stub`` is the reaching form: 069 sec.1's 40–60 for a pad brought out to its
    own flag. Every flag's whole box — glyph, its name text and a margin, 069
    sec.8 — is kept off everything the drawing has already put down: a part, a
    text, the page's edge, and **another net's wire**. Where the nearest lead does
    not fit, the ladder reaches shorter and then farther.

    The search itself lives in :func:`_flag_pin_lead`, because 145a's
    reservation pass has to ask the **same** question before any wire is drawn —
    two copies of "which lead this pin would take" is exactly how a reservation
    and the flag it reserved for would come to disagree. A seat that pass *took*
    (148's wire-style nets) is replayed from ``router.flag_seats``.

    Returns the refusal when there is nothing legal to draw. 074's ``layout-unsat``
    names the crossing when the pin's every lead cuts another net's wire
    (:func:`_flag_crossing_failure`); since 148 the *other* empty-handed answer —
    069 sec.8's flag standing on its own pin — is a refusal too
    (:func:`_flag_on_pin_refusal`), because a flag standing on its pin opens its
    glyph across the run that leaves the pin and prints its name row over whatever
    is beside it, which is the shape 岳 read as a short on the landed page.
    """
    family = flag_glyph_kind(profile)
    for member, point in members:
        seat = router.flag_seats.get((net_id, member))
        if seat is None:
            anchor, lead, hang, crossings = _flag_pin_lead(
                ctx, placed, net_id, profile, member, point, router, blocked,
                solids, bodies, stub=stub,
            )
            if lead is None:
                if crossings:
                    # 074: this pad's flag could have hung 岳's way anywhere it
                    # fitted — and every one of those leads cut another net's wire.
                    return _flag_crossing_failure(
                        net_id, point, crossings,
                        f"{member} is named by a flag of its own (069 sec.1)",
                    )
                return _flag_on_pin_refusal(net_id, member, point)
            seat = (anchor, _flag_rotation((0.0, hang), family), lead)
        anchor, rotation, lead = seat
        _place_flag(
            net_id, profile, ref, anchor, rotation, lead,
            segments, symbols, occupied, solids,
        )
    return None


def _flag_pin_lead(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    profile: SymbolProfile,
    member: str,
    point: tuple[float, float],
    router: _Router,
    blocked: set[tuple[float, float]],
    solids: Sequence[Box],
    bodies: Sequence[Box] | None = None,
    *,
    stub: bool = False,
) -> tuple[
    tuple[float, float],
    tuple[tuple[float, float], ...] | None,
    float,
    list[str],
]:
    """The lead this pin's flag would be drawn on: ``(anchor, lead, hang, crossings)``.

    The pin's own escape side first, then every other direction: 069 sec.8's 换侧 is
    about the picture, not about the symbol — a pad whose own side is crowded
    (the measured AMS1117 with its input capacitor ten units away, its rail ten
    above) still has room *below*, and a lead that leaves a pin tip in another
    direction is a legal wire. ``lead`` is ``None`` when no direction fits at all,
    and then ``crossings`` holds 074's measurement of every rung that fitted
    everywhere else but cut another net's wire.
    """
    inner = None
    if ctx.budget.page_box is not None:
        page = ctx.budget.page_box
        # The page edge is this check's business only where the *pad* is on the
        # page at all. A module compiled in its own frame carries coordinates the
        # page box does not contain (measured: 056's `pwr` module puts `C2.2` at
        # `(20, -35)`), and bounding a flag by a region its own pad is outside of
        # refuses every rung — which is not "the flag hangs off the page", it is
        # "this frame is not the page's".
        if _inside((point[0], point[1], point[0], point[1]), page):
            inner = (
                page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
                page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
            )
    family = flag_glyph_kind(profile)
    natural = family != FLAG_GLYPH_KIND_GND
    room = _flag_room(router, solids, inner, blocked)
    part_id, _, token = member.partition(".")
    escape = _pin_direction(
        ctx, part_id, token, placed.poses,
    ) or (0.0, -1.0)

    def fits(anchor: tuple[float, float], _hang: float) -> bool:
        rotation = _flag_rotation((0.0, _hang), family)
        return room(
            _flag_box(profile, rotation, anchor, net_id, margin=0.0),
            _flag_box(profile, rotation, anchor, net_id),
        )

    crossings: list[str] = []
    for direction in [
        escape,
        *(
            other for other in
            ((0.0, 1.0), (0.0, -1.0), (-1.0, 0.0), (1.0, 0.0))
            if other != escape
        ),
    ]:
        anchor, lead, hang = _flag_anchor(
            router, point, direction, blocked,
            # 069 sec.1's band is 40-60 and :data:`SIBLING_LEAD` is its
            # middle, so 40 is the **second** rung of a far pad's own ladder:
            # a shape that fits it without giving up the 50 is drawn 岳's 40
            # out rather than the nearer :data:`FLAG_LEAD` (measured 082 on
            # 053b's duplicate-VOUT shape — the 40 rung turns **half** a jog
            # down instead of a whole one, and that half turn is what clears
            # C1's own annotation; the 50 stays first, so every drawing that
            # reached 50 still does, E1 included), and a shape with no room
            # at 40 still lands on the nearer rung. The label half
            # (:func:`_stub_label`) keeps 069's single rung: a label box is
            # one text line, not a glyph plus a name, and 074 measured all
            # six of its calls answered by the pad's own direction.
            leads=(SIBLING_LEAD, 40.0) if stub else (),
            fits=fits,
            up=natural,
            boxes=bodies,
            crossings=crossings,
        )
        if lead is not None:
            return anchor, lead, hang, crossings
    return _rounded(point), None, natural, crossings


def _stub_label(
    ctx: _Context,
    placed: _Placement,
    net_id: str,
    member: str,
    point: tuple[float, float],
    router: _Router,
    segments: list[LayoutSegment],
    labels: list[LayoutLabel],
    occupied: list[Box],
    solids: list[Box],
    blocked: set[tuple[float, float]],
) -> GrammarFailure | None:
    """069 sec.1's other half: a **label** where a rail would have had a flag.

    A net that is neither a rail nor a ground has no flag in anyone's library —
    its name on the page is a label (`sch.place_netlabel`'s job, which this host
    cannot do yet, pit 9: the plan's label is carried by the wire's own net name
    instead). The form is the same as the rail half: the pad is brought out on a
    short stub and the name is put at the end of it. The pad that kept the wire
    is brought out the same way, so its cluster is named too — a label on the pin
    itself would land in the part's own annotation.

    074 treats this stub exactly as it treats a flag's lead: the run is the same
    line doing the same job (「这个网从这里出去」), so a run that crosses another
    net's wire is refused the same way and the candidate reported as 074's
    ``layout-unsat`` when no stub survives. The stub's own ladder is climbed to its
    end first — 069 sec.1 brings the pad out *its own way*, and the rungs it has are
    074 sec.3's distance ladder and the turn. A ladder that left on another side
    would be 074 sec.3's 换逃逸方向, and it is not added here: no offline drawing asks
    for it (measured: the pad's own direction answers all six stub calls the
    twenty-four scenarios and the E1 shapes make), and a pad whose own side is
    sealed is the loud ``layout-unsat`` rather than a stub pointing somewhere the
    symbol does not.
    """
    part_id, _, token = member.partition(".")
    direction = _pin_direction(
        ctx, part_id, token, placed.poses,
    ) or (0.0, -1.0)
    crossings: list[str] = []
    anchor, lead, _hang = _flag_anchor(
        router, point, direction, blocked,
        leads=(SIBLING_LEAD,),
        fits=lambda here, _hang: _label_fits(ctx, net_id, here),
        crossings=crossings,
    )
    if lead is None and crossings:
        return _flag_crossing_failure(
            net_id, point, crossings,
            f"{member} is named by a net label of its own (069 sec.1)",
        )
    if lead is not None:
        segments.append(LayoutSegment(net=net_id, points=list(lead)))
    label = _label_for(ctx, net_id, part_id, token, anchor, placed, occupied)
    labels.append(label)
    solids.append(label.bbox)
    return None


def _label_fits(ctx: _Context, net_id: str, anchor: tuple[float, float]) -> bool:
    """Can this net's label sit at this anchor and still be on the page?

    A label's *box* is typography that moves around its anchor, but every one of
    the four placements stays within one text width sideways or one line step
    vertically of it. Requiring that much room inside the page margin is what
    keeps 069's label stub from pushing the drawing out of the region — the same
    guard the flag half gets from its glyph box.
    """
    page = ctx.budget.page_box
    if page is None:
        return True
    inner = (
        page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
        page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
    )
    across = text_width(net_id) + TEXT_GAP
    along = TEXT_SIZE + TEXT_GAP
    return (
        inner[0] + across <= anchor[0] <= inner[2] - across
        and inner[1] + along <= anchor[1] <= inner[3] - along
    )


def _junctions(segments: Sequence[LayoutSegment]) -> list[LayoutJunction]:
    """Every wire vertex that tees into another wire's span.

    053 sec.2's constraint 3 is exactly this rule, and it is applied here to the
    compiler's own output so the drawing *starts* with the dots the editor would
    draw. Two wires that cross, or meet end to end, are not tees and get no dot.
    """
    out: list[LayoutJunction] = []
    seen: set[tuple[float, float]] = set()
    for index, segment in enumerate(segments):
        for point in segment.points:
            for other_index, other in enumerate(segments):
                if other_index == index:
                    continue
                if _key(point) == _key(other.points[0]) or _key(point) == _key(
                    other.points[-1]
                ):
                    continue
                if not _on_polyline(point, other.points):
                    continue
                if _key(point) in seen:
                    continue
                seen.add(_key(point))
                out.append(LayoutJunction(
                    net=segment.net, x=point[0], y=point[1],
                ))
    return out


# ------------------------------------------- the primitives a page layer reuses
#
# The page-level compiler (056) draws the wires that cross a module boundary with
# the *same* lattice search, the same one-bend shortcut and the same junction rule
# a module's own drawing uses — reusing them rather than growing a second
# implementation, because two searches would eventually disagree about what a
# legal wire is and the disagreement would show up as a drawing the checker
# refuses. The names below are those objects under public names; nothing here
# computes anything, so an existing compile cannot be affected by their presence.
#: The orthogonal lattice search, with its obstacle, blocked-point and
#: foreign-edge rules (056 sec.2's page router is this one).
lattice_router = _Router
#: The one-bend shortcut tried before the search.
one_bend_route = _elbow_route
#: "Can this straight wire be drawn as it is?" — boxes, foreign runs, foreign
#: anchors all considered.
span_free = _span_free
#: Collapse collinear runs, so a wire's vertices are its bends.
compress_path = _compress
#: Every wire vertex that tees into another wire's span — the dots the plan must
#: declare.
wire_junctions = _junctions
#: The rotation the editor is given for a flag (so its glyph hangs away from the
#: pin it names) — the escape direction **and the flag's own family**, see
#: :func:`_flag_rotation`.
flag_rotation = _flag_rotation
#: The box a flag's glyph occupies at that rotation — the one box the compiler's
#: occupancy, the page compiler's extents and the SVG preview all reserve.
flag_box = flag_glyph_box
#: ``symbolRef -> SymbolProfile``, with the refusal of a book that disagrees with
#: itself: a part checked against the wrong symbol's pins is the one silent
#: failure mode this pipeline refuses to have.
profile_book = _profile_book


def _plan_bbox(ctx: _Context, plan: LayoutPlan) -> Box:
    """The box the drawing occupies: parts, text, wires, labels and flags.

    Used for the region check (a plan whose own extent does not fit the region
    is refused with the numbers, rather than reported one object at a time) and
    for the compactness layer of the ranking.
    """
    boxes: list[Box] = []
    for part in plan.parts:
        profile = ctx.book.get(part.symbol_ref)
        if profile is not None:
            boxes.append(_part_box(
                profile, SymbolPose(int(part.rotation), part.mirror),
                (part.x, part.y),
            ))
        else:
            boxes.append((part.x, part.y, part.x, part.y))
    for text in plan.texts:
        boxes.append(text.bbox)
    for label in plan.labels:
        boxes.append(label.bbox)
        boxes.append((label.x, label.y, label.x, label.y))
    for symbol in plan.power_symbols:
        profile = ctx.book.get(symbol.symbol_ref)
        if profile is not None:
            boxes.append(
                flag_glyph_box(
                    profile, rotation=symbol.rotation,
                    anchor=(symbol.x, symbol.y),
                )
                or (symbol.x, symbol.y, symbol.x, symbol.y)
            )
        else:
            boxes.append((symbol.x, symbol.y, symbol.x, symbol.y))
    for segment in plan.segments:
        boxes.append(_bounds(segment.points))
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _bounds(points: Sequence[tuple[float, float]]) -> Box:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------------ gating and ranking


def layered_key(
    legality: int,
    findings: int,
    crossings: float,
    bends: float,
    wire_length: float,
    compactness: float,
) -> tuple[int, int, float, float, float, float]:
    """The ranking key: four layers, compared in order and never summed.

    052 sec.6 and 053 sec.7 forbid a total: a single number would let "fewer
    millimetres of wire" buy back a broken relation or a hidden tap. The layers
    are, in order:

    1. **legality** — hard violations (always 0 for a candidate, kept in the key
       so the layer exists rather than being implicit);
    2. **circuit expression** — grammar findings: an unkept relation or a tap
       nobody can see outranks any cosmetic difference;
    3. **readability** — crossings, then bends, then wire length, each its own
       element so a win on one can never pay for a loss on the previous;
    4. **compactness** — the drawing's own area.

    A tuple of numbers compared lexicographically *is* that rule: earlier
    elements dominate, and nothing is ever added across layers.
    """
    return (
        int(legality),
        int(findings),
        float(crossings),
        float(bends),
        float(wire_length),
        float(compactness),
    )


def _measure(
    plan: LayoutPlan,
    findings: Sequence[GrammarFinding],
    ctx: _Context,
) -> Candidate:
    """One gated plan -> the numbers the ranking compares."""
    metrics = dict(plan.evidence.soft_metrics)
    reasons = {key: [value] for key, value in plan.evidence.soft_reasons.items()}
    return Candidate(
        plan=plan,
        findings=list(findings),
        metrics=metrics,
        reasons=reasons,
        key=rank_key(plan, findings, ctx),
    )


def rank_key(
    plan: LayoutPlan,
    findings: Sequence[GrammarFinding],
    ctx: _Context,
) -> tuple:
    """The ranking key of a finished plan (see :func:`layered_key`).

    One implementation for the compiler's own ranking and for a caller that kept a
    plan aside and wants to compare it: two keys would eventually disagree about
    the same plan, and the ranking is part of the contract (053 sec.7's layers).
    """
    box = _plan_bbox(ctx, plan)
    metrics = plan.evidence.soft_metrics
    return layered_key(
        len(plan.evidence.hard_violations),
        len(findings),
        metrics.get("crossings", 0.0),
        metrics.get("bends", 0.0),
        metrics.get("wire_length", 0.0),
        (box[2] - box[0]) * (box[3] - box[1]),
    )


def _no_candidate_failures(
    result: CompileResult, budget: CompileBudget | None = None
) -> list[GrammarFailure]:
    """Why no candidate survived — the first variant's own measured reason.

    The first variant is the smallest rung of the ladder, so its measurement is
    the one that says how much room the circuit actually needs. The failure says
    that N variants were tried *inside the budget*: a finite search that found
    nothing never claims there is no solution (053 sec.4).

    147b: when the ladder stopped at a rung boundary because the next rung was
    refused exactly like the one before it, the sentence says **that** too — how
    many rungs were built out of the ladder's own list, and that the rest were
    skipped on purpose rather than run. A reader who only saw "2 variant(s) were
    built" would take it for the whole search.
    """
    failures = [item.failure for item in result.rejected if item.failure is not None]
    if not failures:
        return [GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject="",
            detail=(
                "no variant produced a plan, and none recorded a reason (report "
                "this: a refusal without a reason is what 053 sec.4 forbids)"
            ),
            action="report this run; the compiler is expected to name its reason",
        )]
    first = failures[0]
    tried = len(result.rejected)
    stopped = _ladder_stopped(result, budget)
    return [GrammarFailure(
        category=first.category,
        subject=first.subject,
        detail=(
            f"{first.detail} — {tried} variant(s) were built and refused inside "
            "the budget (a finite search says 'not found inside the budget', "
            "never 'no solution')" + stopped
        ),
        action=first.action,
    )]


def _ladder_stopped(
    result: CompileResult, budget: CompileBudget | None
) -> str:
    """The clause naming a spacing ladder that 147b cut short, or ``""``.

    Derived from the ladder's own list against the rungs the refusals name: a
    variant's label is ``spacing=<scale> pose-variant=<i>``, so the number of
    distinct ``spacing=`` entries among the rejections is how much of the ladder
    was actually built. Fewer than the budget asked for means
    :func:`_rung_reproduces` stopped it, and the note in ``result.notes`` names
    the kinds that were repeated.
    """
    if budget is None or not budget.spacing_ladder:
        return ""
    built = {item.variant.split(" pose", 1)[0] for item in result.rejected}
    if len(built) >= len(budget.spacing_ladder):
        return ""
    return (
        f"; the spacing ladder was stopped early (147b) — {len(built)} of "
        f"{len(budget.spacing_ladder)} rung(s) were built and the rest skipped, "
        "because a rung refused exactly like the one before it is not fixed by "
        "more room (the note above names the kinds that repeated)"
    )


# ------------------------------------------------- the grammar checker (plan)


def check_grammar(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
    *,
    budget: CompileBudget | None = None,
    intent: IntentSource | DesignIntent | None = None,
) -> list[GrammarFinding]:
    """The drawing grammar's half of the readability contract, over a plan.

    This is what `readability.check`'s ``grammar_checker`` hook takes: it works
    from the plan and the two specs alone (053 sec.2's "独立" requirement) and
    re-binds the grammar rather than reading anything the compiler kept. It
    answers the three questions a plan can be wrong about even when its netlist
    is right:

    * are the grammar's **relations** kept — is the divider's pair on one column,
      is the capacitor on the side of the node it serves;
    * are the **obligations** visible — is the promised chain wired rather than
      named, is the tap a stub with a label, does the branch read as owned by its
      node, is the ground expressed one way throughout;
    * is every **bound part** placed at all (a role bound to nothing on the page
      is a finding, not a silent omission).

    ``intent`` is the contract the compiling bind read (095 A4). Independence is
    about *the compiler's output*, not about its inputs: the checker re-binds the
    same grammar over the same three documents, so a plan whose branch order came
    from a decision is graded against that order rather than against the
    designator default the plan was deliberately not drawn with. Passing none is
    the pre-095 reading, unchanged.

    Findings are values, never exceptions: a plan that fails all three carries
    three lines in its evidence.
    """
    book = _checker_book(profiles)
    out: list[GrammarFinding] = []
    binding = bind_grammar(circuit_spec, presentation_spec, book, intent=intent)
    if not binding.ok:
        return [GrammarFinding(
            kind=KIND_BINDING_UNPLACED,
            objects=("circuitSpec",),
            detail=(
                "the grammar refuses this circuit ("
                + "; ".join(item.detail for item in binding.failures[:2])
                + "), so no plan can express what the grammar promises"
            ),
        )]

    for item in binding.bindings:
        if item.role in NET_ROLES:
            continue
        part = layout_plan.part(item.part_id)
        if part is None:
            out.append(GrammarFinding(
                kind=KIND_BINDING_UNPLACED,
                objects=(f"parts[{item.part_id}]",),
                detail=(
                    f"{item.part_id} is bound to the role {item.role!r} by the "
                    "grammar but is not placed in the plan"
                ),
            ))
        elif part.symbol_ref not in book:
            out.append(GrammarFinding(
                kind=KIND_BINDING_UNPLACED,
                objects=(f"parts[{item.part_id}]",),
                detail=(
                    f"the plan draws {item.part_id} with symbol "
                    f"{part.symbol_ref!r}, for which no profile was supplied, so "
                    "its pins cannot be read and none of its relations can be "
                    "checked"
                ),
            ))

    axis = _axis(binding)
    progress = _progress(presentation_spec, axis)
    settings = budget or CompileBudget()
    for item, points in _relation_violations(
        circuit_spec, binding,
        origin_of=lambda part_id: _plan_origin(layout_plan, part_id),
        pin_of=lambda part_id, token: _plan_pin(layout_plan, book, part_id, token),
        grid=settings.grid, near_limit=settings.near_limit,
        lateral=(-progress[1], progress[0]), progress=progress,
    ):
        out.append(GrammarFinding(
            kind=KIND_RELATION_BROKEN,
            objects=(f"parts[{item.subject}]", f"parts[{item.object}]"),
            detail=(
                f"the relation {item.kind} between {item.subject} and "
                f"{item.object} is not kept by the plan: the two points measured "
                f"are {_point_text(points[0])} and {_point_text(points[1])}; the "
                f"grammar's own reason is {item.reason!r}"
            ),
        ))

    out.extend(_obligation_findings(
        layout_plan, circuit_spec, binding, book, settings,
    ))
    out.extend(_power_flag_findings(layout_plan, circuit_spec))
    return out


def _power_flag_findings(
    layout_plan: LayoutPlan, circuit_spec: CircuitSpec
) -> list[GrammarFinding]:
    """069 sec.7: a rail the plan draws carries a power flag of its own.

    岳 read the landed P23 page and asked why its 5 V input rail had none: the net
    was stated by a text label and nothing else. The compiler supplies that flag
    (:func:`_build_candidate`); this is the check over the finished plan, and it
    reports the cases the compiler could not supply — a library with no flag
    symbol for the net, or a rail no flag could be reached from. A rail nothing is
    placed for is out of scope: there is no drawing to mark.
    """
    placed = {part.part_id for part in layout_plan.parts}
    flagged = {symbol.net for symbol in layout_plan.power_symbols if symbol.net}
    out: list[GrammarFinding] = []
    for net in circuit_spec.nets:
        if net.cls != "power" or net.id in flagged:
            continue
        if not any(member.partition(".")[0] in placed for member in net.members):
            continue
        out.append(GrammarFinding(
            kind=KIND_OBLIGATION_MISSING,
            objects=(f"circuitSpec.nets[{net.id}]",),
            detail=(
                f"power net {net.id!r} is drawn without a power flag — a rail is "
                "named by its own flag at the pin it supplies, and text alone "
                "leaves the reader chasing a name (069 sec.7)"
            ),
        ))
    return out


def _checker_book(
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile]
) -> dict[str, SymbolProfile]:
    """Normalise the caller's profiles to ``symbolRef -> SymbolProfile``.

    Both spellings are accepted because both are natural at a call site (the
    readability checker hands a mapping; a caller exploring a library has an
    iterable). Unlike the compiler's own library check this does **not** raise:
    a checker that raised on a weird profile would turn a plan's finding into a
    crash.
    """
    if isinstance(profiles, Mapping):
        return {
            str(key): value for key, value in profiles.items()
            if isinstance(value, SymbolProfile)
        }
    out: dict[str, SymbolProfile] = {}
    for profile in profiles:
        if isinstance(profile, SymbolProfile):
            out[profile.symbol_ref] = profile
    return out


def _plan_origin(
    layout_plan: LayoutPlan, part_id: str
) -> tuple[float, float] | None:
    part = layout_plan.part(part_id)
    if part is None:
        return None
    return (part.x, part.y)


def _plan_pin(
    layout_plan: LayoutPlan,
    book: Mapping[str, SymbolProfile],
    part_id: str,
    token: str,
) -> tuple[float, float] | None:
    part = layout_plan.part(part_id)
    if part is None:
        return None
    profile = book.get(part.symbol_ref)
    if profile is None:
        return None
    pin = _pin_of_token(profile, token)
    if pin is None:
        return None
    return _posed(
        pin.tip, SymbolPose(int(part.rotation), part.mirror), (part.x, part.y)
    )


def _relation_violations(
    circuit_spec: CircuitSpec,
    binding: GrammarResult,
    *,
    origin_of: Any,
    pin_of: Any,
    grid: float,
    near_limit: float,
    lateral: tuple[float, float],
    progress: tuple[float, float],
) -> list[tuple[Any, tuple[tuple[float, float], tuple[float, float]]]]:
    """Every relation the given points do not keep.

    One implementation for both layers: the placement stage uses it to find a
    lock that fights a relation (before anything is drawn) and
    :func:`check_grammar` uses it on the finished plan. Two copies would be two
    rulers for the same word.
    """
    out = []
    for item in binding.constraints:
        points = _points_for_relation(
            circuit_spec, item, origin_of=origin_of, pin_of=pin_of,
        )
        if points is None:
            continue
        if _relation_holds(
            item.kind, points, grid=grid, near_limit=near_limit,
            lateral=lateral, progress=progress,
        ):
            continue
        out.append((item, points))
    return out


def _points_for_relation(
    circuit_spec: CircuitSpec,
    item: Any,
    *,
    origin_of: Any,
    pin_of: Any,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """The two points a relation is measured between.

    Origins by default. Two kinds are measured between the two parts' **pins on
    the net they share**, when there is one, because that is what those kinds
    say: the RC shunt's out-side pin lands on the trunk row (053 sec.3), not its
    whole body, and a branch is "near" the node it hangs off — the pins are the
    connection, and the body follows within the branch's own span. Measuring whole
    parts there would refuse a readable branch (and, for `near`, refuse a wide
    spacing ladder for no electrical reason), while measuring pins for an order
    kind would let a long pin hide a wrong order.
    """
    if item.kind in (SAME_ROW, SAME_COLUMN, HORIZONTAL_TAP, VERTICAL_TAP, NEAR):
        common = sorted(
            set(_part_nets(circuit_spec, item.subject).values())
            & set(_part_nets(circuit_spec, item.object).values())
        )
        if common:
            here = pin_of(
                item.subject, _token_on(circuit_spec, item.subject, common[0])
            )
            there = pin_of(
                item.object, _token_on(circuit_spec, item.object, common[0])
            )
            if here is not None and there is not None:
                return (here, there)
    here = origin_of(item.subject)
    there = origin_of(item.object)
    if here is None or there is None:
        return None
    return (here, there)


def _token_on(circuit_spec: CircuitSpec, part_id: str, net: str) -> str:
    for pin, here in sorted(_part_nets(circuit_spec, part_id).items()):
        if here == net:
            return pin
    return ""


def _relation_holds(
    kind: str,
    points: tuple[tuple[float, float], tuple[float, float]],
    *,
    grid: float,
    near_limit: float,
    lateral: tuple[float, float],
    progress: tuple[float, float],
) -> bool:
    """Does one relation hold between two points?

    Every kind is read through `grammar/base.py`'s own definition, and the grid
    tolerance is the readability checker's "same column or row" slack — the same
    number all three layers use, so a relation this compiler keeps is never
    reported broken by the layer that measures the finished plan.

    **The two tap kinds are measured here too (143 F4).** They used to fall
    through to ``return True`` — "every point pair keeps `horizontal-tap`" — which
    made the ruler's own claim ("every relation the given points do not keep")
    false for two of the ten published kinds, while
    :func:`_points_for_relation` already handed this function the pair the kinds
    are about: the two arms' pins on the shared net, i.e. the two ends that meet
    at the junction the stub leaves from. The stub leaves **horizontally** for
    `horizontal-tap`, so that junction stands on a vertical line and the two pins
    are in one column (`vertical-tap`: one row). Anything else means the two arms
    of the tap do not meet on one line, and the pair is reported by the same
    refusal path as every other broken relation.

    A kind this ruler **does not know** is not satisfied either. The ten kinds of
    ``CONSTRAINT_KINDS`` are all answered above; the old ``return True`` tail made
    a future eleventh kind a relation the compiler would silently bless, which is
    the failure 053 sec.5 scenario 12 names ("报告冲突，不静默忽略"). An unknown
    kind now fails here and is reported with its own kind and reason, which is how
    the gap gets noticed.
    """
    (ax, ay), (bx, by) = points
    slack = grid / 2.0
    if kind == SAME_COLUMN:
        return abs(ax - bx) <= slack
    if kind == SAME_ROW:
        return abs(ay - by) <= slack
    if kind == HORIZONTAL_TAP:
        # The stub leaves horizontally, so the junction it leaves from is on a
        # vertical line: the two arm pins the tap sits between share a column.
        return abs(ax - bx) <= slack
    if kind == VERTICAL_TAP:
        # The mirror: a horizontal chain, the stub leaves downward/upward, and
        # the two arm pins share a row.
        return abs(ay - by) <= slack
    if kind == ABOVE:
        return ay > by + slack
    if kind == BELOW:
        return ay < by - slack
    if kind == LEFT_OF:
        return ax < bx - slack
    if kind == RIGHT_OF:
        return ax > bx + slack
    if kind == ADJACENT:
        gap = (ax - bx, ay - by)
        return abs(_dot(gap, lateral)) <= slack and not _close(
            _dot(gap, progress), 0.0
        )
    if kind == NEAR:
        return math.hypot(ax - bx, ay - by) <= near_limit
    return False


# --------------------------------------------------- the obligations, checked


def _obligation_findings(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    binding: GrammarResult,
    book: Mapping[str, SymbolProfile],
    settings: CompileBudget,
) -> list[GrammarFinding]:
    """What the grammar promised to make visible, checked against the picture.

    Four obligations, four questions, all answered from the plan: is the chain a
    wire; is the tap a labelled stub; does the branch touch its own node and stay
    near it; is one ground expressed one way.
    """
    out: list[GrammarFinding] = []
    derived = derive_netlist(layout_plan, book) if book else None
    tap_axis = _tap_axis_by_net(circuit_spec, binding)
    for item in binding.obligations:
        if item.kind == DIRECT_WIRE:
            for net_id in item.nets:
                finding = _direct_wire_finding(
                    layout_plan, circuit_spec, book, derived, net_id,
                )
                if finding is not None:
                    out.append(finding)
        elif item.kind == VISIBLE_TAP:
            for net_id in item.nets:
                finding = _visible_tap_finding(
                    layout_plan, net_id, tap_axis.get(net_id, "x"), settings,
                )
                if finding is not None:
                    out.append(finding)
        elif item.kind == OWNED_BRANCH:
            for net_id in item.nets:
                out.extend(_owned_branch_findings(
                    layout_plan, circuit_spec, binding, book, net_id, settings,
                ))
        elif item.kind == UNIFORM_GND:
            for net_id in item.nets:
                finding = _uniform_gnd_finding(layout_plan, circuit_spec, net_id)
                if finding is not None:
                    out.append(finding)
        elif item.kind == GND_OUTLET:
            for net_id in item.nets:
                finding = _gnd_outlet_finding(layout_plan, net_id)
                if finding is not None:
                    out.append(finding)
    return out


def _tap_axis_by_net(
    circuit_spec: CircuitSpec, binding: GrammarResult
) -> dict[str, str]:
    """``net -> the axis its stub leaves on``, from the tap kinds.

    The grammar fixes the axis (`horizontal-tap` / `vertical-tap`) on the pair of
    parts the tap sits between; the tap net is the one they share, and that is how
    the obligation's net is tied back to the relation that describes it.
    """
    out: dict[str, str] = {}
    for item in binding.constraints:
        if item.kind not in (HORIZONTAL_TAP, VERTICAL_TAP):
            continue
        common = sorted(
            set(_part_nets(circuit_spec, item.subject).values())
            & set(_part_nets(circuit_spec, item.object).values())
        )
        for net_id in common:
            out.setdefault(net_id, "x" if item.kind == HORIZONTAL_TAP else "y")
    return out


def _net_member_points(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    book: Mapping[str, SymbolProfile],
    net_id: str,
) -> list[tuple[str, tuple[float, float]]]:
    """``(member, page point)`` for every pin of this net the plan can show."""
    net = circuit_spec.net(net_id)
    if net is None:
        return []
    out: list[tuple[str, tuple[float, float]]] = []
    for member in net.members:
        part_id, _, token = member.partition(".")
        point = _plan_pin(layout_plan, book, part_id, token)
        if point is not None:
            out.append((member, point))
    return out


def _direct_wire_finding(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    book: Mapping[str, SymbolProfile],
    derived: Any,
    net_id: str,
) -> GrammarFinding | None:
    """Is this promised net drawn as a wire rather than named?

    069 sec.3 changes the *form* the promise may be kept in and not the promise:
    a net whose pads a part separates (its role on both sides of the body) is
    drawn pad by pad — a stub and the same flag at each of them — and then no one
    segment reaches two of its declared pins. That is 岳's own drawing of the
    case, so it counts as kept when the net is *named* on the page and every one
    of its declared pins is brought out on a wire: the chain is then visible at
    every pin, which is what "not found by chasing names" means. A net with a
    bare pin, or with nothing stating its name anywhere, still fails — the
    complaint the obligation exists to make.
    """
    points = _net_member_points(layout_plan, circuit_spec, book, net_id)
    if not points:
        return None
    if len(points) >= 2:
        for segment in layout_plan.segments:
            if sum(
                1 for _, point in points if _on_polyline(point, segment.points)
            ) >= 2:
                return None
        named = any(
            symbol.net == net_id for symbol in layout_plan.power_symbols
        ) or any(label.net == net_id for label in layout_plan.labels)
        if named and all(
            any(_on_polyline(point, segment.points) for segment in layout_plan.segments)
            for _, point in points
        ):
            return None
        return GrammarFinding(
            kind=KIND_OBLIGATION_MISSING,
            objects=(f"circuitSpec.nets[{net_id}]",),
            detail=(
                f"net {net_id!r} is promised as a direct wire, but no segment "
                f"reaches two of its {len(points)} pins and the net is not "
                "brought out at every pin under its own name either — the chain "
                "has to be found by chasing names"
            ),
        )
    member, point = points[0]
    touches_wire = any(
        _on_polyline(point, segment.points) for segment in layout_plan.segments
    )
    touches_flag = any(
        _close(symbol.x, point[0]) and _close(symbol.y, point[1])
        for symbol in layout_plan.power_symbols
    )
    if touches_wire or touches_flag:
        return None
    where = (
        "attached only to a label (a name)"
        if derived is not None and member in derived.wired_pins
        else "attached to nothing"
    )
    return GrammarFinding(
        kind=KIND_OBLIGATION_MISSING,
        objects=(f"circuitSpec.nets[{net_id}]", f"pins[{member}]"),
        detail=(
            f"net {net_id!r} is promised as a direct wire, but its only pin "
            f"{member} is {where} — the end of the chain would have to be found "
            "by chasing it"
        ),
    )


def _visible_tap_finding(
    layout_plan: LayoutPlan,
    net_id: str,
    axis: str,
    settings: CompileBudget,
) -> GrammarFinding | None:
    """Is the tap a labelled stub on the axis the grammar states?"""
    labels = [label for label in layout_plan.labels if label.net == net_id]
    if not labels:
        return GrammarFinding(
            kind=KIND_OBLIGATION_MISSING,
            objects=(f"circuitSpec.nets[{net_id}]",),
            detail=(
                f"the tap net {net_id!r} carries no label, so the tap is only "
                "readable as the junction between two arms"
            ),
        )
    for label in labels:
        anchor = (label.x, label.y)
        for segment in layout_plan.segments:
            if not _on_polyline(anchor, segment.points):
                continue
            for start, end in zip(segment.points, segment.points[1:]):
                if axis == "x":
                    length = abs(end[0] - start[0])
                    aligned = _close(start[1], end[1]) and length > 0
                else:
                    length = abs(end[1] - start[1])
                    aligned = _close(start[0], end[0]) and length > 0
                if aligned and length >= settings.stub / 2.0:
                    return None
    return GrammarFinding(
        kind=KIND_OBLIGATION_MISSING,
        objects=(f"circuitSpec.nets[{net_id}]",),
        detail=(
            f"the tap net {net_id!r} is labelled, but no "
            f"{'horizontal' if axis == 'x' else 'vertical'} stub of at least "
            f"{settings.stub / 2.0:g} units carries that label off the chain, so "
            "the tap is absorbed by the junction (053 sec.3: 抽头直接可见)"
        ),
    )


def _owned_branch_findings(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    binding: GrammarResult,
    book: Mapping[str, SymbolProfile],
    net_id: str,
    settings: CompileBudget,
) -> list[GrammarFinding]:
    """Does each branch on this node read as owned by it: attached, and near."""
    out: list[GrammarFinding] = []
    seen: set[str] = set()
    for item in binding.bindings:
        if item.role not in BRANCH_ROLES or item.part_id in seen:
            continue
        nets = set(_part_nets(circuit_spec, item.part_id).values())
        if net_id not in nets:
            continue
        seen.add(item.part_id)
        token = _token_on(circuit_spec, item.part_id, net_id)
        point = _plan_pin(layout_plan, book, item.part_id, token)
        if point is None:
            continue
        attached = False
        nearest = math.inf
        for segment in layout_plan.segments:
            if _on_polyline(point, segment.points):
                attached = True
            nearest = min(nearest, _distance_to_polyline(point, segment.points))
        for symbol in layout_plan.power_symbols:
            if _close(point[0], symbol.x) and _close(point[1], symbol.y):
                attached = True
            nearest = min(nearest, math.hypot(
                point[0] - symbol.x, point[1] - symbol.y
            ))
        if not attached:
            out.append(GrammarFinding(
                kind=KIND_OBLIGATION_MISSING,
                objects=(
                    f"pins[{item.part_id}.{token}]",
                    f"circuitSpec.nets[{net_id}]",
                ),
                detail=(
                    f"the branch {item.part_id} sits on {net_id} but its pin "
                    "touches no wire and no flag of that net, so it does not read "
                    "as owned by the node it belongs to"
                ),
            ))
        elif nearest > settings.near_limit:
            out.append(GrammarFinding(
                kind=KIND_OBLIGATION_MISSING,
                objects=(f"parts[{item.part_id}]", f"circuitSpec.nets[{net_id}]"),
                detail=(
                    f"the branch {item.part_id} is {nearest:g} units from "
                    f"{net_id}'s wiring, beyond the {settings.near_limit:g}-unit "
                    "local-group limit, so it reads as a separate circuit (052 "
                    "sec.5: 不跨模块)"
                ),
            ))
    return out


def _distance_to_polyline(
    point: tuple[float, float], points: Sequence[tuple[float, float]]
) -> float:
    best = math.inf
    for start, end in zip(points, points[1:]):
        best = min(best, _distance_to_segment(point, start, end))
    return best


def _uniform_gnd_finding(
    layout_plan: LayoutPlan, circuit_spec: CircuitSpec, net_id: str
) -> GrammarFinding | None:
    """Is this ground expressed one way throughout — one symbol, or one label?"""
    net = circuit_spec.net(net_id)
    if net is None or net.cls != "gnd":
        return None
    styles = {
        f"flag:{symbol.symbol_ref}"
        for symbol in layout_plan.power_symbols
        if symbol.net == net_id
    }
    if any(label.net == net_id for label in layout_plan.labels):
        styles.add("label")
    if len(styles) > 1:
        return GrammarFinding(
            kind=KIND_OBLIGATION_MISSING,
            objects=(f"circuitSpec.nets[{net_id}]",),
            detail=(
                f"net {net_id!r} is expressed in more than one style ("
                + ", ".join(sorted(styles))
                + ") — 053 sec.3: 地表达统一（同符号或同标签不混用）"
            ),
        )
    return None


def _gnd_outlet_finding(
    layout_plan: LayoutPlan, net_id: str
) -> GrammarFinding | None:
    """Is this group's return stated by **exactly one** outlet symbol? (088b)

    The promise is a count, not a coordinate: the grammar says the group's ground
    is stated by one symbol of its own and the compiler says where it goes, so
    what the finished plan can be checked against is "one" — a ground with two
    marks reads as two returns (岳: 「真实体现得很乱」, the reading 088b answers),
    and a ground with none reads as a bare conductor named by nothing at all.
    """
    symbols = [
        symbol for symbol in layout_plan.power_symbols if symbol.net == net_id
    ]
    if len(symbols) == 1:
        return None
    return GrammarFinding(
        kind=KIND_OBLIGATION_MISSING,
        objects=(f"circuitSpec.nets[{net_id}]",),
        detail=(
            f"net {net_id!r} carries {len(symbols)} outlet symbol(s); the group "
            "states its return with exactly one, hung at the rail's far end — "
            "088b sec.1 (岳 2026-10-02: 「底轨要有一个、且只要一个出处符号」)"
        ),
    )
