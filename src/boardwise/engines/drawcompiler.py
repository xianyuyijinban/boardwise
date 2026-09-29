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
* 3-8 candidates come out, best first, each carrying its evidence
  (`LayoutEvidence`: checker name, hard violations, grammar findings, raw soft
  metrics with a reason each) and the plan's two source digests.

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
from heapq import heappop, heappush
from typing import Any

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.geometry import transform_point
from boardwise.core.layoutplan import (
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
from boardwise.core.presentationspec import LABEL_LABEL, PresentationSpec
from boardwise.core.symbolprofile import (
    FLAG_GLYPH_KIND_GND,
    FLAG_GLYPH_ROTATION_OFFSETS,
    Box,
    SymbolPin,
    SymbolPose,
    SymbolProfile,
    check_box,
    flag_glyph_box,
    flag_glyph_kind,
    role_siblings,
)

from . import readability
from .grammar import bind as bind_grammar
from .grammar.base import (
    ABOVE,
    ADJACENT,
    BELOW,
    DIRECT_WIRE,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
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

#: Where the host prints a flag's own name: a single line **above** the anchor,
#: between these two distances from it. Measured on the landed pages (P22's hand
#: drawing and the v3 page): a rail's name 10 units up, a ground's 15 — the glyph
#: itself hangs up or down from the anchor by 18, so the name is inside that span
#: for a rail and just past it for a ground. And the margin a flag keeps between
#: this whole box and anything else — 069 sec.8 (岳: 「3V3的旗标标识和5V的导线重合了」)
#: is about *touching*, so the box the placement keeps free is the glyph, the name
#: and the clearance.
FLAG_TEXT_NEAR = 6.0
FLAG_TEXT_REACH = 16.0
FLAG_CLEARANCE = 5.0

#: How far a **duplicate pad across the body** is brought out before its own flag
#: goes on (069 sec.1). 岳's hand-drawn AMS1117 brings a far pad out 40-60 units
#: and puts the flag on the end of that stub instead of running a wire over the
#: part to its twin; the same number is 069 sec.3's ceiling, beyond which a power
#: pin's reach is a long run rather than a stub.
SIBLING_LEAD = 50.0

#: Minimum gap between two boxes that must not touch.
GAP = 20.0

#: Text metrics: cap height, line step, gap from a part's box.
TEXT_SIZE = 9.0
TEXT_LINE_STEP = 14.0
TEXT_GAP = 8.0

#: Member count above which a *rail* may be drawn with flags instead of a wire.
#: 053 sec.7: labels wait for "high fan-out"; three is where a rail stops being
#: a local connection and becomes a bus.
HIGH_FANOUT = 3

#: How far apart two parts may be and still read as one local group — what the
#: grammar's `near` relation is measured against.
NEAR_LIMIT = 300.0

#: The corridor a net's search may use, beyond the net's own bounding box.
SEARCH_MARGIN = 160.0

#: Costs in lattice steps: a bend is worth staying straight, and crossing a
#: foreign wire perpendicularly is allowed but not free.
TURN_COST = 0.6
CROSS_COST = 2.0

#: The roles that bind a **chain** element: the series line the drawing is read
#: along. Verbatim from 053 sec.3's three tables (`upper_arm`/`lower_arm` the
#: divider's arms, `series` the RC's element, `core` the regulator), plus this
#: batch's `middle_arm` for the multi-tap ladder.
CHAIN_ROLES: tuple[str, ...] = ("upper_arm", "lower_arm", "middle_arm", "series", "core")

#: The roles that bind an element **hanging off** a chain node (053 sec.3:
#: 并联支路 / 多 C 并联 / 电容各归所属节点 / NR 电容), plus this batch's
#: `tap_branch`. Both tuples are the grammar's published role vocabulary, not
#: per-scenario constants: a role in neither is treated structurally.
BRANCH_ROLES: tuple[str, ...] = (
    "tap_branch",
    "shunt",
    "in_caps",
    "out_caps",
    "aux_branch",
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

    ``candidates`` is what the caller draws (3-8 legal plans, best first);
    ``failures`` is why nothing could be drawn, in 053 sec.4's four categories;
    ``rejected`` is the audit trail of the variants that were built and lost. A
    refusal is never an empty success: a result with no candidate and no failure
    would be the "invalid spec" answer the contract exists to avoid.
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
) -> CompileResult:
    """Compile a drawing, or say why there is none.

    The four stages, the gate and the layered ranking are in the module
    docstring. A refusal returns ``candidates == []`` with the reasons in
    ``failures``; a success returns 3-8 plans, best first, each with its
    evidence filled in and its source digests pinned.
    """
    for value, expected in (
        (circuit_spec, CircuitSpec),
        (presentation_spec, PresentationSpec),
    ):
        if not isinstance(value, expected):
            raise CompileError(
                f"{expected.__name__} expected, got {type(value).__name__}"
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

    # 2. bind; a refusal travels through verbatim.
    binding = bind_grammar(circuit_spec, presentation_spec, book)
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
    prepare = _prepare(circuit_spec, presentation_spec, binding, book, budget)
    if prepare.failures:
        result.failures = prepare.failures
        return result
    ctx = prepare.context
    assert ctx is not None

    # 5. geometry: variants -> plans -> the hard gate.
    seen: set[str] = set()
    for variant in _variants(ctx):
        built, failure, violations = _build_candidate(ctx, variant)
        if built is None:
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
            result.rejected.append(RejectedCandidate(
                variant=variant.label,
                reason="the same geometry as an earlier variant",
            ))
            continue
        seen.add(digest)
        findings = check_grammar(
            plan, circuit_spec, presentation_spec, book, budget=budget
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

    if not result.ranked:
        result.failures = _no_candidate_failures(result)
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
    for item in binding.bindings:
        if item.role in NET_ROLES or item.part_id in slots:
            continue
        nets = _part_nets(circuit_spec, item.part_id)
        if not nets:
            continue
        owner = _branch_owner(circuit_spec, item.part_id, chain_ids, ranks)
        classes = {
            net.cls for net in circuit_spec.nets if net.id in set(nets.values())
        }
        is_branch = item.role in BRANCH_ROLES or (
            owner and len(nets) == 2 and "gnd" in classes
        )
        if not is_branch or not owner:
            continue
        slot = _branch_slot(
            circuit_spec, presentation_spec, binding, item.part_id, item.role,
            owner, axis, ranks,
        )
        if slot is None:
            order_failures.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=item.part_id,
                detail=(
                    f"{item.part_id} is bound as {item.role!r} but shares no net "
                    "with any chain part, so which node it belongs to cannot be "
                    "read from the circuit"
                ),
                action=(
                    "check the CircuitSpec connections of this branch (one end "
                    "on the node it decouples), or the module split it is bound "
                    "through"
                ),
            ))
            continue
        slots[item.part_id] = slot

    for part in circuit_spec.parts:
        if part.id in slots:
            continue
        slots[part.id] = _Slot(
            part_id=part.id, role=part_roles.get(part.id, ""), kind="free",
            axis=axis, rank=ranks.get(part.id, 0) + 1000,
        )

    ctx = _Context(
        circuit=circuit_spec, presentation=presentation_spec, binding=binding,
        book=book, budget=budget, axis=axis, progress=progress,
        chain_net_rank=chain_net_rank, slots=slots, chain=chain_ids,
        accepted={}, body_dirs={},
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


def _branch_owner(
    circuit_spec: CircuitSpec,
    part_id: str,
    chain_ids: Sequence[str],
    ranks: Mapping[str, int],
) -> str:
    """The chain part a branch hangs off: the one it shares a net with.

    When it shares a net with two chain parts (the divider's tap belongs to both
    arms), the answer is the one nearer the power end — the branch hangs off the
    junction where the tap leaves, and the tie-break is the rank order the
    grammar already stated.
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


def _rounded(point: tuple[float, float]) -> tuple[float, float]:
    """Trim float noise from a rotation (``cos(90°)`` is 6.1e-17, not 0)."""
    return (round(point[0], 6), round(point[1], 6))


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
    """A lock whose pose the symbol does not declare is reported, never bent.

    053 sec.5 scenario 12: the engineer's decision is the one input the compiler
    may not quietly ignore, and a rotation the symbol cannot be drawn in is a
    conflict between the lock and the library — `presentation-poor`, because the
    intent is what has to change, with both repairs named.
    """
    out: list[GrammarFailure] = []
    for lock in ctx.presentation.user_locks:
        profile = ctx.book.get(_symbol_ref(ctx, lock.part_id))
        if profile is None:
            continue
        if profile.allows(lock.rotation, False):
            continue
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=lock.part_id,
            detail=(
                f"{LOCK_PREFIX}[{lock.part_id}] locks the part at rotation "
                f"{lock.rotation:g}°, which {profile.symbol_ref!r} does not allow "
                "(its poses are "
                + ", ".join(pose.label() for pose in profile.poses)
                + ")"
            ),
            action=(
                f"relax {LOCK_PREFIX}[{lock.part_id}].rotation to one of the "
                "symbol's poses, or use a symbol that allows the locked "
                "orientation — the lock is honoured exactly or reported, never "
                "snapped"
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
        x0, y0, x1, y1 = profile.body
        for corner in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            point = _posed(corner, pose, origin)
            xs.append(point[0])
            ys.append(point[1])
    for pin in profile.pins:
        point = _posed(pin.tip, pose, origin)
        xs.append(point[0])
        ys.append(point[1])
    if not xs:
        return (origin[0], origin[1], origin[0], origin[1])
    return (min(xs), min(ys), max(xs), max(ys))


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
    """
    if profile.body is None:
        return None
    x0, y0, x1, y1 = profile.body
    corners = [_posed(corner, pose, origin) for corner in
               ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


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


def _close(left: float, right: float, tol: float = 1e-6) -> bool:
    return abs(left - right) <= tol


def _lattice_residue(
    points: Sequence[tuple[float, float]], grid: float
) -> tuple[float, float] | None:
    """The lattice offset every pin tip shares, or ``None`` when they disagree.

    Locks are honoured exactly, so a locked part may sit off the zero-origin
    lattice; the compiler then compiles on the lattice the locks put the tips on
    — as long as *one* lattice fits them all. Two locks on different residues
    cannot both be honoured by a grid search, and that is reported rather than
    silently snapped (a snapped lock is a moved lock).
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


def _place(
    ctx: _Context, variant: _Variant
) -> tuple[_Placement | None, GrammarFailure | None]:
    """Ranks and lanes -> origins, through the real symbols.

    The chain is laid on one line with a pitch per neighbouring pair taken from
    the two parts' own extents plus a wiring channel, scaled by the ladder rung;
    every branch is placed from the owner's pin it shares a net with; a free part
    (one the grammar bound to nothing) goes on a shelf past the chain so the
    drawing still shows it. Locked parts take their lock exactly, and the chain
    is translated so the unlocked parts keep their relations to it.
    """
    poses = {
        part_id: ctx.accepted[part_id][
            min(variant.pose_index, len(ctx.accepted[part_id]) - 1)
        ]
        for part_id in ctx.accepted
    }
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
                "all: the locked positions put tips on different residues"
            ),
            action=(
                "move the locks onto one lattice, or lower budget.grid to a "
                "divisor of the coordinates involved — the compiler searches a "
                "lattice, and it will not snap a locked part to one"
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
    branch_ids = sorted(
        (part_id for part_id in ctx.slots if ctx.slots[part_id].kind == "branch"),
        key=lambda part_id: (
            ctx.slots[part_id].owner, ctx.slots[part_id].rank, part_id,
        ),
    )
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
        distance = max(ctx.budget.lane * variant.scale * (index + 1), clearance)
        root = (
            anchor[0] + direction[0] * _snap(distance, ctx.budget.grid, 0.0),
            anchor[1] + direction[1] * _snap(distance, ctx.budget.grid, 0.0),
        )
        shared = _pin_local(ctx, part_id, slot.pin_shared, poses)
        if shared is None:
            origins[part_id] = root
        else:
            origins[part_id] = (root[0] - shared[0], root[1] - shared[1])

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

    Skipped when a part is locked, because a lock's coordinates are the
    engineer's: the drawing then stays exactly where the lock put it (053 sec.5
    scenario 12), and the page check reports an overflow if the lock is outside.
    """
    page = ctx.budget.page_box
    if page is None or ctx.presentation.user_locks:
        return
    placed = [
        _part_box(ctx.profile(part_id), poses[part_id], origin)
        for part_id, origin in origins.items()
    ]
    if not placed:
        return
    side, vertical = _annotation_allowance(ctx)
    dx = page[0] + PAGE_MARGIN + side - min(box[0] for box in placed)
    dy = page[3] - PAGE_MARGIN - vertical - max(box[3] for box in placed)
    dx = _snap(dx, ctx.budget.grid, residue[0])
    dy = _snap(dy, ctx.budget.grid, residue[1])
    for part_id in origins:
        origins[part_id] = (origins[part_id][0] + dx, origins[part_id][1] + dy)


def _annotation_allowance(ctx: _Context) -> tuple[float, float]:
    """``(sideways, vertical)`` room the annotations need beyond the parts.

    The anchor has to leave space for what it is about to draw: a flag's lead and
    its glyph extend past the pin a rail ends on, and a tap's stub plus the label
    at its end extend sideways. Both are measured from what the library says (the
    pin-less symbols *are* the flags) and from the circuit's own net names, so the
    allowance is about this drawing rather than a fixed border — and anything it
    still gets wrong is caught by the measured overflow check on the finished plan.
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
    return (ctx.budget.stub + widest + TEXT_GAP, FLAG_LEAD + glyph + TEXT_GAP)


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

    ``side``/``line``/``tap`` carry their own axis (the side the grammar states,
    the line a same-line kind names, the stub's axis); ``pin`` reads the owner's
    own pin direction from its profile under its chosen pose (which is why the
    pose choice comes first); ``across`` is perpendicular to the chain.
    """
    if slot.basis in ("side", "line", "tap"):
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
            return direction
    lateral = ctx.lateral()
    sign = float(slot.sign)
    return (lateral[0] * sign, lateral[1] * sign)


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


def _line_boxes(part: Box, lines: Sequence[str], side: str) -> list[Box]:
    """Where a part's text lines go when put on `side` of its box.

    One line per string, stacked in reading order; the block is centred on the
    part's own centre along the side it takes, and offset off the box by
    :data:`TEXT_GAP`. Both lines of a part's text stay together on one side: a
    reference on one side and a value on the other reads as two unrelated texts.
    """
    width = max(text_width(line) for line in lines)
    height = len(lines) * TEXT_LINE_STEP
    cx = (part[0] + part[2]) / 2.0
    cy = (part[1] + part[3]) / 2.0
    out: list[Box] = []
    for index, line in enumerate(lines):
        if side == "right":
            x = part[2] + TEXT_GAP + text_width(line) / 2.0
            y = cy + height / 2.0 - TEXT_LINE_STEP * (index + 0.5)
        elif side == "left":
            x = part[0] - TEXT_GAP - text_width(line) / 2.0
            y = cy + height / 2.0 - TEXT_LINE_STEP * (index + 0.5)
        elif side == "above":
            x = cx - width / 2.0 + text_width(line) / 2.0
            y = part[3] + TEXT_GAP + height - TEXT_LINE_STEP * (index + 0.5)
        else:
            x = cx - width / 2.0 + text_width(line) / 2.0
            y = part[1] - TEXT_GAP - height + TEXT_LINE_STEP * (index + 0.5)
        out.append(font_text_box(line, x=x, y=y))
    return out


def _part_texts(
    ctx: _Context, placed: _Placement, occupied: list[Box]
) -> list[LayoutText]:
    """The reference and value of every placed part, on a side that is free.

    `occupied` is the list of boxes already on the page (part extents, keep-outs
    and earlier texts) and is extended as the texts land. The side ladder is
    tried in order and the first free one wins; when no side is free the text is
    placed anyway at the first side, and the hard gate then refuses the whole
    candidate — text is never shrunk to fit (053 sec.5 scenario 10).
    """
    out: list[LayoutText] = []
    for part_id in sorted(placed.origins):
        part = ctx.circuit.part(part_id)
        profile = ctx.profile(part_id)
        box = _part_box(profile, placed.poses[part_id], placed.origins[part_id])
        lines: list[tuple[str, str]] = [("reference", part_id)]
        if part is not None and part.value:
            lines.append(("value", part.value))
        chosen = None
        for side in TEXT_SIDES:
            boxes = _line_boxes(box, [text for _, text in lines], side)
            if all(
                not _overlaps(candidate, other)
                for candidate in boxes for other in occupied
            ):
                chosen = boxes
                break
        if chosen is None:
            chosen = _line_boxes(box, [text for _, text in lines], TEXT_SIDES[0])
        for (kind, text), item in zip(lines, chosen):
            occupied.append(item)
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
    a label off the part it names.
    """
    direction = _pin_direction(ctx, part_id, token, placed.poses)
    if direction is None:
        direction = ctx.lateral()
    return _label_at(net_id, point, direction, occupied)


def _label_at(
    net_id: str,
    point: tuple[float, float],
    preferred: tuple[float, float],
    occupied: list[Box],
) -> LayoutLabel:
    """A label whose *anchor* is fixed and whose *box* moves around it.

    The anchor is the electrical fact — a label joins the node it touches, so it
    stays where it is; the box is typography, so it is tried in four directions
    and the first free one wins. Both live in `LayoutLabel` for exactly this
    reason, and the box is the font-metric box for the net's name.
    """
    box = None
    for candidate_direction in _directions(preferred):
        half_x = text_width(net_id) / 2.0 + TEXT_GAP
        half_y = TEXT_SIZE / 2.0 + TEXT_GAP
        if candidate_direction[0] != 0.0:
            offset = (candidate_direction[0] * half_x, 0.0)
        else:
            offset = (0.0, candidate_direction[1] * half_y)
        candidate = font_text_box(
            net_id, x=point[0] + offset[0], y=point[1] + offset[1]
        )
        if all(not _overlaps(candidate, other) for other in occupied):
            box = candidate
            break
    if box is None:
        box = font_text_box(
            net_id, x=point[0], y=point[1] + TEXT_SIZE / 2.0 + TEXT_GAP
        )
    occupied.append(box)
    return LayoutLabel(
        net=net_id, text=net_id, bbox=box, x=point[0], y=point[1],
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
    that does not carry it is not a failure — the net is then expressed with a
    label, and `uniform-gnd` is what checks that one net does not end up mixing
    the two styles.
    """
    ref = ctx.budget.gnd_flag if cls == "gnd" else f"{ctx.budget.power_flag_prefix}{net_id}"
    return (ctx.book.get(ref), ref)


def _segment_hits_box(start: tuple[float, float], end: tuple[float, float], box: Box) -> bool:
    """Does the segment have a positive-length run inside the box's interior?

    The slab test the readability checker's own `_clip_to_box` uses (Liang–Barsky
    against the box inset by a hair): a wire lying exactly on an outline, or
    touching only a corner, is not crossing the box.
    """
    left, bottom, right, top = box[0] + 1e-6, box[1] + 1e-6, box[2] - 1e-6, box[3] - 1e-6
    if right <= left or top <= bottom:
        return False
    dx, dy = end[0] - start[0], end[1] - start[1]
    low, high = 0.0, 1.0
    for p, q in (
        (-dx, start[0] - left),
        (dx, right - start[0]),
        (-dy, start[1] - bottom),
        (dy, top - start[1]),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > high:
                return False
            low = max(low, ratio)
        else:
            if ratio < low:
                return False
            high = min(high, ratio)
    return high - low > 1e-6


# -------------------------------------------------------------- the router


def _key(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 6), round(point[1], 6))


def _strictly_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    """Is `point` inside the segment, not at either end (the tee condition)?"""
    if _key(point) == _key(start) or _key(point) == _key(end):
        return False
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )
    if abs(cross) > 1e-6:
        return False
    dot = (point[0] - start[0]) * (end[0] - start[0]) + (point[1] - start[1]) * (
        end[1] - start[1]
    )
    length = (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2
    return 0.0 < dot < length


def _on_polyline(point: tuple[float, float], points: Sequence[tuple[float, float]]) -> bool:
    for start, end in zip(points, points[1:]):
        if _key(point) == _key(start) or _key(point) == _key(end):
            return True
        if _strictly_on_segment(point, start, end):
            return True
    return False


class _Router:
    """Orthogonal obstacle-avoiding search on the compilation lattice.

    The furniture, and why each piece is there:

    * **obstacle boxes** — part extents and text boxes (053 sec.4: "文字 bbox
      参与避障") plus the keep-outs. A step whose segment cuts a box's interior
      is refused, with the checker's own clip test, so a path this search calls
      clear is clear to the layer that grades it;
    * **blocked points** — foreign pin tips, foreign labels and flags, and other
      nets' wire vertices. A wire vertex on any of them is a *connection* in the
      editor's model, which is exactly the short the readability contract
      refuses, so they are walls;
    * **foreign edges** — another net's wire. Its interior may be crossed
      perpendicularly (measured editor behaviour: a plain crossing does not
      join), but never run along, and never turned on: a turn or a parallel run
      would put a vertex of one wire on the other, which does join;
    * **cost** — a step costs one, a bend costs :data:`TURN_COST`, a crossing
      costs :data:`CROSS_COST`. The trunk is tried before any search, so the
      search only ever spends bends on what the trunk cannot reach.
    """

    def __init__(
        self,
        *,
        grid: float,
        residue: tuple[float, float],
        boxes: Sequence[Box],
        bounds: Box,
    ) -> None:
        self.grid = grid
        self.residue = residue
        self.boxes = list(boxes)
        self.bounds = bounds
        self.blocked: set[tuple[float, float]] = set()
        self.edges: list[tuple[tuple[float, float], tuple[float, float]]] = []

    # ------------------------------------------------------------ geometry

    def node(self, point: tuple[float, float]) -> tuple[int, int]:
        return (
            round((point[0] - self.residue[0]) / self.grid),
            round((point[1] - self.residue[1]) / self.grid),
        )

    def point(self, node: tuple[int, int]) -> tuple[float, float]:
        return _rounded((
            self.residue[0] + node[0] * self.grid,
            self.residue[1] + node[1] * self.grid,
        ))

    def add_edge(self, start: tuple[float, float], end: tuple[float, float]) -> None:
        if _key(start) != _key(end):
            self.edges.append((start, end))

    def _in_bounds(self, node: tuple[int, int]) -> bool:
        point = self.point(node)
        return (
            self.bounds[0] - 1e-6 <= point[0] <= self.bounds[2] + 1e-6
            and self.bounds[1] - 1e-6 <= point[1] <= self.bounds[3] + 1e-6
        )

    def _wall(self, node: tuple[int, int]) -> bool:
        point = self.point(node)
        if _key(point) in self.blocked:
            return True
        for box in self.boxes:
            if (
                box[0] - 1e-6 < point[0] < box[2] + 1e-6
                and box[1] - 1e-6 < point[1] < box[3] + 1e-6
            ):
                return True
        return False

    def _step_free(
        self, node: tuple[int, int], other: tuple[int, int]
    ) -> bool:
        start = self.point(node)
        end = self.point(other)
        for box in self.boxes:
            if _segment_hits_box(start, end, box):
                return False
        for foreign in self.edges:
            if _collinear_overlap(start, end, foreign[0], foreign[1]):
                return False
        return True

    def crossing_at(self, point: tuple[float, float]) -> tuple[int, int] | None:
        """Is this point inside a foreign wire's span? (the join condition)"""
        return self._crossing(self.node(point))

    def _crossing(self, node: tuple[int, int]) -> tuple[int, int] | None:
        """The axis of the foreign edge this node lies inside, if any.

        A node inside a foreign wire's span is the one place a crossing can
        happen — and it may only be *crossed*, never turned on or run along,
        which is what the caller's stepping rules enforce from this answer.
        """
        point = self.point(node)
        for start, end in self.edges:
            if _strictly_on_segment(point, start, end):
                return (1, 0) if _close(start[1], end[1]) else (0, 1)
        return None

    # --------------------------------------------------------------- search

    def route(
        self,
        start: tuple[float, float],
        goal: tuple[float, float],
        *,
        targets: Sequence[tuple[float, float]] | None = None,
    ) -> list[tuple[float, float]] | None:
        """A cheapest orthogonal path from `start` to `goal` (or to any target).

        Dijkstra over ``(node, arrival direction)`` so a turn can be priced, with
        the stepping rules above. ``None`` means "not found inside the corridor
        the caller gave", which is what the caller reports — never "no solution".
        """
        goals = {self.node(point) for point in (targets or [goal])}
        start_node = self.node(start)
        if start_node in goals:
            return [self.point(start_node)]
        frontier: list[tuple[float, int, tuple[int, int], int]] = []
        counter = 0
        heappush(frontier, (0.0, counter, start_node, 4))
        best: dict[tuple[tuple[int, int], int], float] = {(start_node, 4): 0.0}
        parent: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
        steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
        while frontier:
            cost, _, node, arrived = heappop(frontier)
            if node in goals:
                return self._unwind((node, arrived), parent, start_node)
            for index, (dx, dy) in enumerate(steps):
                other = (node[0] + dx, node[1] + dy)
                if not self._in_bounds(other) or self._wall(other):
                    continue
                direction = index
                if not self._step_free(node, other):
                    continue
                moving = (1, 0) if dx != 0 else (0, 1)
                here = self._crossing(node)
                if here is not None and here == moving:
                    continue  # running along a foreign wire from inside it
                if here is not None and arrived < 4 and direction != arrived:
                    continue  # a crossing may not be turned on
                there = self._crossing(other)
                if there is not None and there == moving:
                    continue  # entering a foreign wire lengthwise
                total = cost + 1.0
                if arrived < 4 and arrived != direction:
                    total += TURN_COST
                if there is not None:
                    total += CROSS_COST
                state = (other, direction)
                if best.get(state, math.inf) <= total + 1e-9:
                    continue
                best[state] = total
                parent[state] = (node, arrived)
                counter += 1
                heappush(frontier, (total, counter, other, direction))
        return None

    def _unwind(
        self,
        state: tuple[tuple[int, int], int],
        parent: Mapping[tuple[tuple[int, int], int], tuple[tuple[int, int], int]],
        start_node: tuple[int, int],
    ) -> list[tuple[float, float]]:
        nodes = [state[0]]
        while state[0] != start_node:
            state = parent[state]
            nodes.append(state[0])
        nodes.reverse()
        return [self.point(node) for node in nodes]


def _collinear_overlap(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    """Do two segments lie on one line and share more than a point?

    A parallel run along a foreign wire is the case that must not happen: the
    editor joins wires that overlap, and a vertex of one on the other is a short.
    """
    if _close(a[1], b[1]) and _close(c[1], d[1]) and _close(a[1], c[1]):
        low = max(min(a[0], b[0]), min(c[0], d[0]))
        high = min(max(a[0], b[0]), max(c[0], d[0]))
        return high - low > 1e-6
    if _close(a[0], b[0]) and _close(c[0], d[0]) and _close(a[0], c[0]):
        low = max(min(a[1], b[1]), min(c[1], d[1]))
        high = min(max(a[1], b[1]), max(c[1], d[1]))
        return high - low > 1e-6
    return False


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
) -> bool:
    """Can this one straight wire be drawn as it is, ends and all?

    The trunk shortcut's guard: no obstacle box crossed, no foreign wire run
    along, and no foreign anchor *inside* the span — a foreign pin or label on a
    wire is a connection, and a foreign wire vertex on it is a tee that needs a
    junction the caller would have to declare.
    """
    if _key(start) == _key(end):
        return False
    for box in router.boxes:
        if _segment_hits_box(start, end, box):
            return False
    for foreign in router.edges:
        if _collinear_overlap(start, end, foreign[0], foreign[1]):
            return False
    for point in blocked:
        if _strictly_on_segment(point, start, end):
            return False
    return True


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

    texts = _part_texts(ctx, placed, occupied)
    for text in texts:
        solids.append(text.bbox)
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
    for net_id in _net_order(ctx, expressions):
        expression = expressions[net_id]
        router.edges = [
            (start, end)
            for segment in segments if segment.net != net_id
            for start, end in zip(segment.points, segment.points[1:])
        ]
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
                    _flag_pins(
                        ctx, placed, net_id, profile, ref, [(member, point)],
                        router, segments, symbols, occupied, solids, blocked,
                        stub=True,
                    )
                    continue
                _stub_label(
                    ctx, placed, net_id, member, point, router, segments,
                    labels, occupied, solids, blocked,
                )
            for member, point in near:
                if named == "flag":
                    _flag_pins(
                        ctx, placed, net_id, profile, ref, [(member, point)],
                        router, segments, symbols, occupied, solids, blocked,
                    )
                    continue
                _stub_label(
                    ctx, placed, net_id, member, point, router, segments,
                    labels, occupied, solids, blocked,
                )
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
            _flag_pins(
                ctx, placed, net_id, profile, ref, expression.points,
                router, segments, symbols, occupied, solids, blocked,
            )
        router.boxes = solids

    # 069 sec.7's own supply, *after* every net is routed: 岳 read the landed P23
    # page and asked why its 5 V rail had no flag (「P23 5V部分为什么不给旗标？」), so
    # a rail drawn as a wire carries one — hung off the rail by a short vertical run
    # (:func:`_rail_flag`), at the pin the rail supplies. Placed last on purpose:
    # those runs are obstacles for the router, and put in the per-net loop they
    # cost one 053B scenario 4 s → 40 s of search (measured) without changing a
    # single drawing.
    for net_id in _net_order(ctx, expressions):
        expression = expressions[net_id]
        if expression.style != "wire" or not _power_needs_flag(ctx, net_id, symbols):
            continue
        profile, ref = _flag_plan(ctx, net_id, "power")
        pin = _power_flag_pin(ctx, expression)
        if profile is None or pin is None:
            continue
        router.edges = [
            (start, end)
            for segment in segments if segment.net != net_id
            for start, end in zip(segment.points, segment.points[1:])
        ]
        blocked = _blocked_points(ctx, placed, net_id, labels, symbols, segments)
        router.blocked = blocked
        anchor = _rail_flag(
            ctx, net_id, expression, pin, profile, ref, router, segments,
            symbols, occupied, solids, blocked,
        )
        notes.append(
            f"net {net_id}: a power net carries its own flag — hung at "
            f"{_point_text(anchor)} by a {FLAG_JOG:g}-unit vertical run off the "
            f"rail its pin {pin[0]} supplies (069 sec.7); a rail named by text "
            "alone would be found by chasing names"
        )
        router.boxes = solids

    junctions = _junctions(segments)
    plan = LayoutPlan(
        source=LayoutSource(
            circuit_sha256=ctx.circuit.sha256(),
            presentation_sha256=ctx.presentation.sha256(),
        ),
        parts=parts,
        segments=segments,
        junctions=junctions,
        labels=labels,
        power_symbols=symbols,
        texts=texts,
        notes=[
            f"compiled by {COMPILER_NAME}: {variant.label}; "
            f"axis {'column' if ctx.axis == 'v' else 'row'}, "
            f"grid {ctx.budget.grid:g}",
            "references are the CircuitSpec's own ids: an offline plan has not "
            "landed, so the designator is assigned when it does",
            *notes,
        ],
    )
    overflow = _overflow(ctx, plan)
    if overflow is not None:
        return None, overflow, []
    checked = readability.check(
        plan,
        ctx.circuit,
        ctx.presentation,
        ctx.book,
        grammar_checker=check_grammar,
        page_box=ctx.budget.page_box,
        keepouts=ctx.budget.keepouts,
        grid=ctx.budget.grid,
    )
    if checked.hard_violations:
        return None, GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject="gate",
            detail=(
                f"{variant.label}: the independent readability checker refused "
                f"{len(checked.hard_violations)} hard violation(s) — "
                + checked.hard_violations[0].render()
            ),
            action=(
                "this is a compiler-side geometry problem, not a spec problem: "
                "the region, the ladder or the symbol set has to change before "
                "this variant can be drawn"
            ),
        ), [item.render() for item in checked.hard_violations]
    return _Built(plan=plan, checked=checked), None, []


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
) -> tuple[tuple[float, float], tuple[tuple[float, float], ...] | None, float]:
    """Where a flag's anchor goes, the lead that reaches it, and which way it hangs.

    Returns ``(anchor, lead, hang)``: ``lead`` is the straight run from the point to
    the anchor (``None`` when the flag sits *on* the point — a legal placement,
    since the flag's own anchor is a conductor there), and ``hang`` is ``+1``/``-1``,
    the vertical :func:`_flag_rotation` turns into 0 or 180.

    A flag is placed *on* the wire that reaches it (that is what makes the editor
    see the connection). A **vertical** lead is the whole story and the glyph hangs
    further out along it. A **horizontal** one cannot: 069 sec.7 draws flags
    upright, so the glyph rises (a rail, ``up``) or hangs down (a ground) from the
    end of the run — and the run stays *straight*, which matters beyond the picture:
    the page layer recognizes a flag's lead by being a two-point run to its anchor
    (`pagecompiler._is_lead`), so a bent one would be left dangling when a page
    re-states the net. A rail's flag is therefore hung from the rail itself, by a
    vertical run of its own (:func:`_rail_flag`) — which is 岳's own VIN: out along
    the rail, then up to the flag.

    ``leads`` are lengths to try before the default ladder, and ``fits`` is how a
    stub that has to *reach* somewhere is chosen (069 sec.1's far pad): the lead may
    be clear while the flag's own box at its end lands on a neighbouring part, on a
    foreign wire or outside the page, and the pad it names is then brought out
    elsewhere instead — shorter first, then **farther** (069 sec.8: 宁可走远也不许贴上),
    and only when nothing anywhere fits does the flag end on its pin.
    """
    lengths: list[float] = []
    for length in (
        *leads, FLAG_LEAD, router.grid * 2.0,
        2.0 * FLAG_LEAD, 4.0 * FLAG_LEAD, 0.0,
    ):
        if length not in lengths:
            lengths.append(length)
    natural = 1.0 if up else -1.0
    for length in lengths:
        anchor = _rounded((
            point[0] + direction[0] * length,
            point[1] + direction[1] * length,
        ))
        if _close(length, 0.0):
            return anchor, None, natural
        if direction[1] != 0.0:
            hangs: tuple[float, ...] = (math.copysign(1.0, direction[1]),)
        else:
            # A horizontal lead leaves the hang open, so 069 sec.8's 换侧 is a real
            # choice here: the family's own side first (a rail lifts, a ground
            # hangs), then the other one, because a flag that has nowhere to stand
            # on one side of its run may still stand on the other.
            hangs = (natural, -natural)
        for hang in hangs:
            # The anchor is a conductor of its own: a flag placed on a *foreign* pin
            # tip or inside a foreign wire's span would join two nets the spec keeps
            # apart (measured: a rail's flag run 10 units up landed exactly on the pin
            # above it). `_span_free` guards the run's interior; the far end needs its
            # own test, which is also what `_vertex_clear` means for a wire vertex.
            if _key(anchor) in blocked or not _vertex_clear(router, anchor):
                continue
            if not _span_free(router, point, anchor, blocked):
                continue
            if fits is not None and not fits(anchor, hang):
                continue
            return anchor, (_rounded(point), anchor), hang
    return _rounded(point), None, natural


def _inside(box: Box, outer: Box) -> bool:
    """Is this box within ``outer``? The same tolerance the overflow check uses."""
    return (
        box[0] >= outer[0] - 1e-6 and box[1] >= outer[1] - 1e-6
        and box[2] <= outer[2] + 1e-6 and box[3] <= outer[3] + 1e-6
    )


def _flag_box(
    profile: SymbolProfile, rotation: float, anchor: tuple[float, float], net_id: str
) -> Box:
    """Everything one flag occupies: its glyph, its name text, and a margin.

    069 sec.8 — 岳, on the landed P23 page: 「3V3的旗标标识和5V的导线重合了」. The glyph
    box alone is **not** the flag: the host prints the net's name beside it (one line
    *above* the anchor, between :data:`FLAG_TEXT_NEAR` and :data:`FLAG_TEXT_REACH` —
    measured on the landed pages), so a flag that keeps only its glyph clear still
    touches its neighbours. This is the box the placement keeps free of foreign
    wiring: the glyph, that line, and the clearance.
    """
    glyph = flag_glyph_box(profile, rotation=rotation, anchor=anchor)
    if glyph is None:
        glyph = (anchor[0], anchor[1], anchor[0], anchor[1])
    half = text_width(net_id) / 2.0 + 2.0
    text = (
        anchor[0] - half, anchor[1] + FLAG_TEXT_NEAR,
        anchor[0] + half, anchor[1] + FLAG_TEXT_REACH,
    )
    return (
        min(glyph[0], text[0]) - FLAG_CLEARANCE,
        min(glyph[1], text[1]) - FLAG_CLEARANCE,
        max(glyph[2], text[2]) + FLAG_CLEARANCE,
        max(glyph[3], text[3]) + FLAG_CLEARANCE,
    )


def _flag_room(
    router: _Router,
    solids: Sequence[Box],
    inner: Box | None,
    blocked: set[tuple[float, float]],
) -> Callable[[Box], bool]:
    """Is this box free of everything the drawing has already put down?

    Three questions, the first two of which the placement already asked about its
    glyph and the third of which is 069 sec.8's:

    * does it land on a part or a text box, or leave the page;
    * does it swallow a **foreign connection** — another net's pin tip, flag anchor
      or wire vertex (a flag on one of those joins two nets the spec keeps apart);
    * does it **touch a foreign net's wire**? ``router.edges`` is every wire but this
      net's own, so the rail the flag hangs from is not in its own way, while the
      neighbouring rail 岳 found a glyph grazing is.
    """
    def free(box: Box) -> bool:
        if any(_overlaps(box, solid) for solid in solids):
            return False
        if inner is not None and not _inside(box, inner):
            return False
        for start, end in router.edges:
            if _segment_hits_box(start, end, box):
                return False
        for point in blocked:
            if box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]:
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


def _rail_flag(
    ctx: _Context,
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
) -> tuple[float, float]:
    """Hang a rail's own flag from the rail, by a short **vertical** run.

    069 sec.7, from 岳's own hand: a rail that is drawn as a wire says nothing in
    the one way he reads a rail (「P23 5V部分为什么不给旗标？」), so its flag hangs a
    short vertical run off the rail and stands upright — his VIN, out along the
    rail and then up to the flag. The run is the only line this adds, and it is a
    straight two-point one, which is also what lets the page layer drop it cleanly
    if it re-states this net at a module boundary.

    Where along the rail the flag hangs is a question about the room: the run goes
    at 069 sec.1's reach out from the pin first (岳's drawing), then at 069's own
    jog length, then straight off the pin; and either way up (a rail lifts) or
    down. Only when no run fits anywhere does the flag stand *on* the rail itself —
    a legal placement (its anchor is a conductor on the wire) and better than a
    rail with no flag at all.
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
    on_the_rail: tuple[tuple[float, float], float] | None = None
    room = _flag_room(router, solids, inner, blocked)
    # 069 sec.8: 被占就沿轨继续走 — the reaches are tried in 岳's own order (his VIN's
    # 30 out, then a jog's length), and then **farther** along the rail, because a
    # flag that has nowhere to stand still must not end up touching its neighbours.
    for reach in (FLAG_LEAD, FLAG_JOG, 2.0 * FLAG_LEAD, 4.0 * FLAG_LEAD, 0.0):
        attach = _flag_attach_point(expression, pin, segments, reach)
        if _key(attach) in blocked or not _vertex_clear(router, attach):
            # The foot of the run is a conductor too: a point on the rail that is
            # also a foreign pin tip (two nets meeting at a point) would join them.
            continue
        for hang in (natural, -natural):
            def fits(
                anchor: tuple[float, float], _hang: float = hang
            ) -> bool:
                return room(_flag_box(
                    profile, _flag_rotation((0.0, _hang), family), anchor, net_id,
                ))

            anchor, lead, placed_hang = _flag_anchor(
                router, attach, (0.0, hang), blocked,
                leads=(FLAG_JOG,), fits=fits, up=natural > 0.0,
            )
            if lead is not None:
                _place_flag(
                    net_id, profile, ref, anchor,
                    _flag_rotation((0.0, placed_hang), family), lead,
                    segments, symbols, occupied, solids,
                )
                return anchor
            if on_the_rail is None and fits(attach, hang):
                on_the_rail = (attach, _flag_rotation((0.0, hang), family))
    if on_the_rail is not None:
        _place_flag(
            net_id, profile, ref, on_the_rail[0], on_the_rail[1], None,
            segments, symbols, occupied, solids,
        )
        return on_the_rail[0]
    # Nothing fits anywhere: the flag stands on the rail's own pin.
    rotation = _flag_rotation((0.0, natural), family)
    _place_flag(
        net_id, profile, ref, pin[1], rotation, None,
        segments, symbols, occupied, solids,
    )
    return pin[1]


def _flag_attach_point(
    expression: _Expression,
    pin: tuple[str, tuple[float, float]],
    segments: Sequence[LayoutSegment],
    reach: float,
) -> tuple[float, float]:
    """A point ``reach`` along the net's own wiring from this pin, or the pin.

    A rail's flag hangs off the rail, not off a stub drawn over it: the run out is
    the wiring that is already there (岳's VIN again), so the flag's vertical run
    is the only line this adds. When the pin is not an end of any of the net's own
    wires — a single-pin rail, or one the wiring has not reached — the pin is the
    answer and the flag hangs straight off it.
    """
    point = pin[1]
    for segment in segments:
        if segment.net != expression.net or len(segment.points) < 2:
            continue
        points = [_rounded(item) for item in segment.points]
        for index in (0, -1):
            if _close(points[index][0], point[0]) and _close(points[index][1], point[1]):
                return _walk(points, index, reach)
    return point


def _walk(
    points: Sequence[tuple[float, float]], index: int, reach: float
) -> tuple[float, float]:
    """``reach`` units along this polyline, starting at ``points[index]``."""
    step = 1 if index == 0 else -1
    walked = 0.0
    position = index
    while 0 <= position + step < len(points):
        start, end = points[position], points[position + step]
        leg = math.hypot(end[0] - start[0], end[1] - start[1])
        if leg > 0.0 and walked + leg >= reach:
            ratio = (reach - walked) / leg
            return _rounded((
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            ))
        walked += leg
        position += step
    return _rounded(points[index])


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
    *,
    stub: bool = False,
) -> None:
    """Put this net's flag on each of ``members``, on a lead out of its own pin.

    One flag per pin, all of them stating the same net: that is what makes a
    flag-joined net what 岳 drew — the pad, a short stub, the flag's name (069
    sec.1). Every flag stands upright (069 sec.7, see :func:`_flag_anchor`).

    ``stub`` is the reaching form: 069 sec.1's 40–60 for a pad brought out to its
    own flag. Every flag's whole box — glyph, its name text and a margin, 069
    sec.8 — is kept off everything the drawing has already put down: a part, a
    text, the page's edge, and **another net's wire**. Where the nearest lead does
    not fit, the ladder reaches shorter and then farther, and only if nothing
    anywhere fits does the flag end on its own pin.
    """
    inner = None
    if ctx.budget.page_box is not None:
        page = ctx.budget.page_box
        inner = (
            page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
            page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
        )
    family = flag_glyph_kind(profile)
    natural = family != FLAG_GLYPH_KIND_GND
    room = _flag_room(router, solids, inner, blocked)
    for member, point in members:
        part_id, _, token = member.partition(".")
        escape = _pin_direction(
            ctx, part_id, token, placed.poses,
        ) or (0.0, -1.0)

        def fits(anchor: tuple[float, float], _hang: float) -> bool:
            return room(_flag_box(
                profile, _flag_rotation((0.0, _hang), family), anchor, net_id,
            ))

        # The pin's own escape first, then every other direction: 069 sec.8's 换侧 is
        # about the picture, not about the symbol — a pad whose own side is crowded
        # (the measured AMS1117 with its input capacitor ten units away, its rail ten
        # above) still has room *below*, and a lead that leaves a pin tip in another
        # direction is a legal wire.
        hung = False
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
                leads=(SIBLING_LEAD,) if stub else (),
                fits=fits,
                up=natural,
            )
            if lead is None:
                continue  # nothing fits that way — try the next side
            _place_flag(
                net_id, profile, ref, anchor,
                _flag_rotation((0.0, hang), family), lead,
                segments, symbols, occupied, solids,
            )
            hung = True
            break
        if not hung:
            _place_flag(
                net_id, profile, ref, point,
                _flag_rotation((0.0, 1.0 if natural else -1.0), family), None,
                segments, symbols, occupied, solids,
            )


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
) -> None:
    """069 sec.1's other half: a **label** where a rail would have had a flag.

    A net that is neither a rail nor a ground has no flag in anyone's library —
    its name on the page is a label (`sch.place_netlabel`'s job, which this host
    cannot do yet, pit 9: the plan's label is carried by the wire's own net name
    instead). The form is the same as the rail half: the pad is brought out on a
    short stub and the name is put at the end of it. The pad that kept the wire
    is brought out the same way, so its cluster is named too — a label on the pin
    itself would land in the part's own annotation.
    """
    part_id, _, token = member.partition(".")
    direction = _pin_direction(
        ctx, part_id, token, placed.poses,
    ) or (0.0, -1.0)
    anchor, lead, _hang = _flag_anchor(
        router, point, direction, blocked,
        leads=(SIBLING_LEAD,),
        fits=lambda here, _hang: _label_fits(ctx, net_id, here),
    )
    if lead is not None:
        segments.append(LayoutSegment(net=net_id, points=list(lead)))
    label = _label_for(ctx, net_id, part_id, token, anchor, placed, occupied)
    labels.append(label)
    solids.append(label.bbox)


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


def _no_candidate_failures(result: CompileResult) -> list[GrammarFailure]:
    """Why no candidate survived — the first variant's own measured reason.

    The first variant is the smallest rung of the ladder, so its measurement is
    the one that says how much room the circuit actually needs. The failure says
    that N variants were tried *inside the budget*: a finite search that found
    nothing never claims there is no solution (053 sec.4).
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
    return [GrammarFailure(
        category=first.category,
        subject=first.subject,
        detail=(
            f"{first.detail} — {tried} variant(s) were built and refused inside "
            "the budget (a finite search says 'not found inside the budget', "
            "never 'no solution')"
        ),
        action=first.action,
    )]


# ------------------------------------------------- the grammar checker (plan)


def check_grammar(
    layout_plan: LayoutPlan,
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | Iterable[SymbolProfile],
    *,
    budget: CompileBudget | None = None,
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

    Findings are values, never exceptions: a plan that fails all three carries
    three lines in its evidence.
    """
    book = _checker_book(profiles)
    out: list[GrammarFinding] = []
    binding = bind_grammar(circuit_spec, presentation_spec, book)
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
    """
    (ax, ay), (bx, by) = points
    slack = grid / 2.0
    if kind == SAME_COLUMN:
        return abs(ax - bx) <= slack
    if kind == SAME_ROW:
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
    return True


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
