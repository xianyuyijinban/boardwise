"""The page compiler: several modules in, one placed page out (056 sec.2).

The layer above 053's single-drawing compiler, and the offline half of 052 route
stage D. Where `engines/drawcompiler.py` turns *one* circuit and *one* grammar
into a drawing, this module takes the same two documents with a **module split**
and produces a **page**: every module compiled on its own, the resulting frames
placed in a reading order, and the nets the modules share connected across their
boundaries.

The data flow, in the order it runs (056 sec.6 asks for this picture):

    CircuitSpec + PresentationSpec (modules, flow, page box)
      -> 1. the page's own reference checks   (a part in no module, a flow edge
                                              naming no module, a cyclic flow …)
      -> 2. per module: the module-local view of both documents
      -> 3. per module: drawcompiler.compile()      <-- the single-module path,
                                                         *called*, never forked
      -> 4. per variant: ports  (how each module states each shared net)
      -> 5. per variant: frames (each module's extent, a rigid body)
      -> 6. per variant: placement (flow-respecting order, grid shape, gaps)
      -> 7. per variant: the cross-module wires (the `mainPath` edges)
      -> 8. per variant: the gate — readability.check on the merged drawing and
                              readability.check_page on the page
      -> 9. layered ranking, 3-8 geometry-distinct candidates

**Four decisions worth stating** (each of them is a place where the obvious
alternative is worse):

* **The module compile is a call.** Each module is compiled by handing
  `drawcompiler.compile` a *module-local view* of the two documents: the circuit
  restricted to the module's parts (a shared net keeps its id and class and keeps
  the members that are inside), and a presentation with exactly one module, the
  module's own grammar and the module's own side preferences. Nothing in the
  single-module pipeline is special-cased for a page, and the module's own
  `CompileResult` is kept in the answer (`PageCompileResult.modules`) so a reader
  can see what each group's drawing was and what it cost.
* **A module's frame is a rigid body, and the page's placement moves it.** A
  module is compiled *without* a page (`page_box=None`), so its drawing defines
  its own frame; the page then translates the whole thing onto its slot. That is
  what makes "the module gap is a page constant" checkable, and it is why a lock
  inside a module is honoured *inside that module* (the page translates the lock
  with the module rather than pretending the engineer placed a part on a page
  that did not exist when the lock was written — 057 owns page-level locks).
* **The page's own expression rule is decided per net, and it rewrites the module
  drawings where it has to.** The join between two modules happens by *name* in
  an editor whose netlist is project-level (054 C7, measured). So for every net
  that spans modules the page states it the same way everywhere: a label at each
  end, a flag at each end, or — for a whole `mainPath` edge between two adjacent
  modules, and only then — one wire from port to port. A module that already drew
  a flag (or a label) for that net has it *replaced*, not duplicated: a net that
  is a wire on one side and a name on the other is a drawing whose reader cannot
  tell whether the two are one connection at all, and `readability.check_page`
  refuses it.
* **No arrangement is invented.** Candidates are grid shapes over orders that
  respect the presentation's flow (a topological order derived deterministically,
  name order when no flow is stated), each module using its own ranked best
  drawing and, on the second generation, its runner-up. Frames are placed on the
  compilation lattice, aligned to the page's top-left corner; the flow is a soft
  reading aid, and an arrangement that fights it loses on the ranking rather than
  being refused.

**The four failure categories** are 053 sec.4's vocabulary, read at page scale,
and a page-level failure names the module it belongs to:

=========================  ==================================================
``facts-missing``          a flow edge or a module names something the circuit
                           does not have, a module states no grammar, a part has
                           no profile
``circuit-invalid``        a module's own connections contradict its grammar —
                           reported against **that module**, and the modules that
                           are fine are not blamed for it
``layout-unsat``           the page geometry cannot be produced: a shared net's
                           ports are not on one lattice, a `mainPath` wire has no
                           legal route
``presentation-poor``      the intent cannot be honoured: the page is smaller than
                           the smallest arrangement (measured, with the size it
                           needed), a keep-out sits on a module, a `mainPath` edge
                           that cannot be a wire, a part in no module or in two
=========================  ==================================================

Every refusal carries a measured number and an action that changes the answer —
a page that does not fit says what it needed, a keep-out conflict names the box,
a main-path edge that could not be wired names the edge and why. None of them
says "no solution".

**Guards** (the same list 053 sec.7 fixes for the module compiler): offline only
— no bridge, no connector, no editor, no rules; no total score anywhere (the
layers of :func:`page_layered_key` are compared in order and never summed); no
scenario-specific constant (the tile grid, the gaps and the thresholds are
budget constants); and no CLI action, bridge action or user-visible document —
this is an internal engine and its preview is a file an operator opens.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from boardwise.core.circuitspec import (
    CircuitSpec,
    SpecNet,
    SpecNoConnect,
    SpecOpenInterface,
)
from boardwise.core.layoutplan import (
    LayoutEvidence,
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core.pagelayoutplan import (
    PAGE_PORT_FLAG,
    PAGE_PORT_LABEL,
    PAGE_PORT_WIRE,
    PageLayoutPlan,
    PageModule,
    PagePort,
)
from boardwise.core.presentationspec import (
    DirectWiringObligation,
    FlowEdge,
    PresentationModule,
    PresentationPath,
    PresentationSpec,
    UserLock,
)
from boardwise.core.symbolprofile import (
    Box,
    SymbolPose,
    SymbolProfile,
    check_box,
    flag_glyph_box,
    flag_glyph_kind,
)
from boardwise.core.geometry import transform_point

from . import drawcompiler, readability
from .grammar.base import (
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
    GrammarFailure,
)

__all__ = [
    "FRAME_PADDING",
    "GAP_LADDER",
    "KIND_PAGE_LOCK_CONFLICT",
    "KIND_PAGE_LOCK_CONTRADICTION",
    "PAGE_COMPILER_NAME",
    "PageCandidate",
    "PageCompileBudget",
    "PageCompileResult",
    "PageRejection",
    "compile_page",
    "page_layered_key",
    "wants_page",
]

#: What a caller writes into the page's notes and its evidence. The compiler is
#: the page's author; the *checker* names stay what they are
#: (`readability.CHECKER_NAME`, `readability.PAGE_CHECKER_NAME`).
PAGE_COMPILER_NAME = "boardwise-pagecompiler/1"

#: Clear space between the arrangement and the page's edge — the same constant the
#: module compiler uses for its own anchoring, because "inside the sheet" has to
#: mean one thing.
PAGE_MARGIN = drawcompiler.PAGE_MARGIN

#: The clear space two module frames must keep. Taken from the checker
#: (`readability.PAGE_MODULE_GAP`) rather than re-stated, so the number the page
#: places with and the number the page domain refuses with cannot drift.
MODULE_GAP = readability.PAGE_MODULE_GAP

#: How far a module's frame reaches beyond its own drawing. A frame is a rigid
#: body and the page keeps bodies apart; this is the room its own annotation
#: allowance is measured with, so a neighbouring module's flag stem or label box
#: does not land on it. It is a budget constant, not a magic number, and it
#: enters the page document as part of the stated frame.
FRAME_PADDING = 20.0

#: The radius of the box put around a foreign pin tip, label anchor or flag
#: anchor, so a wire step cannot slip *between* two lattice nodes and land on one.
BLOCKED_POINT_RADIUS = 1.0

#: How far past the two modules a page wire's search may look. A corridor rather
#: than the whole sheet: a wire between two modules stays in their neighbourhood,
#: and a search over every lattice node of an A4 page spends its time proving that
#: a route does not exist.
PAGE_SEARCH_MARGIN = 60.0

#: The gap ladder: multipliers of :data:`MODULE_GAP` the placement is tried at, so
#: a crowded page can be given more room without ever squeezing text (the same
#: idea as the module compiler's spacing ladder).
GAP_LADDER: tuple[float, ...] = (1.0, 1.6)

#: The two page-lock refusals (057 sec.3). Page-compiler kinds, not checker
#: kinds: a lock that cannot be honoured is decided while the frames are being
#: placed, before there is a page for `readability.check_page` to read — and the
#: nine's own `user-lock-violated` still re-checks every honoured lock on the
#: merged drawing, independently.
#:
#: ``page-lock-contradiction`` — two page locks in one module ask for two
#: different module origins (the module's own drawing puts the two parts at a
#: distance the two lock points do not have).
#: ``page-lock-conflict`` — the origin a lock derives puts the module's frame off
#: the page, on a keep-out, on another locked module, or leaves the unlocked
#: modules no room.
KIND_PAGE_LOCK_CONTRADICTION = "page-lock-contradiction"
KIND_PAGE_LOCK_CONFLICT = "page-lock-conflict"


def wants_page(presentation_spec: PresentationSpec) -> bool:
    """Does this presentation ask for a *page* rather than a single drawing?

    057 sec.1's rule ("PresentationSpec 有 modules[] 即走页级"), read so that the
    single-module documents that exist keep their path: 053/054's specs group
    their parts into **one** module and have always been compiled as one
    drawing (the divider fixture 054 lands is exactly that). What only a page can
    mean is: two or more modules, a module-level ``flow``, a module that states
    its own grammar, or a lock measured on the page. Any one of them routes the
    document to :func:`compile_page`; none of them keeps it on
    `drawcompiler.compile`, whose output is then byte-for-byte what it was.
    """
    return (
        len(presentation_spec.modules) >= 2
        or bool(presentation_spec.flow)
        or any(module.grammar_ref for module in presentation_spec.modules)
        or bool(presentation_spec.page_locks())
    )


class PageCompileError(ValueError):
    """The page compiler was called wrongly — a programming error, not bad input.

    Input problems never raise: they come back as a
    :class:`PageCompileResult` whose `failures` carry one of 053 sec.4's four
    categories with a reason and an action.
    """


@dataclass
class PageCompileBudget:
    """What the page may use, and how hard it may try.

    ``page_box`` is the sheet the page must fit in. Unlike the module compiler it
    is **required**: a page-level compile is a statement about a sheet (the
    placements, the gaps and the keep-outs are all absolute), and a page without
    one would have nothing to be outside of.

    ``module_budget`` is the budget every module compile runs under. Its
    ``page_box`` and ``keepouts`` are *overridden* to "no page, no keep-outs": a
    module's drawing defines its own frame, and the page's keep-outs are the page
    layer's business (the module compiler would clip its search to a region the
    page has not placed it in yet).
    """

    page_box: Box | None = None
    keepouts: tuple[Box, ...] = ()
    grid: float = drawcompiler.GRID
    min_candidates: int = 3
    max_candidates: int = 8
    #: How many (order, grid shape, ladder rung, module-generation) variants the
    #: finite search builds. The variants are generated in a fixed order, so two
    #: runs of one input search the same points in the same sequence.
    max_variants: int = 24
    module_gap: float = MODULE_GAP
    frame_padding: float = FRAME_PADDING
    gap_ladder: tuple[float, ...] = GAP_LADDER
    module_budget: drawcompiler.CompileBudget = field(
        default_factory=drawcompiler.CompileBudget
    )
    #: 057 sec.2: may the arrangement be *moved* off the keep-outs, as a rigid
    #: body, when its anchored position lands on one? Off by default, and the
    #: default is 056's contract: a keep-out is a reserved region the anchored
    #: arrangement must not touch (056 scene 6 refuses exactly that). A page drawn
    #: onto a sheet that already holds a drawing is the other reading: the
    #: keep-outs are the census of what is there (`drawapply.census_keepouts`),
    #: and the new drawing belongs in the room that is left — so `draw plan` on a
    #: live page turns this on. Nothing is squeezed either way: the frames, gaps
    #: and texts stay what they are, only the arrangement's translation changes.
    relocate_around_keepouts: bool = False


@dataclass
class PageRejection:
    """A variant that lost — so "why is there no page" stays answerable."""

    variant: str
    reason: str
    failure: GrammarFailure | None = None
    violations: list[str] = field(default_factory=list)
    #: The area this variant needed, when the reason was "it does not fit" —
    #: carried structurally so the refusal can report the *smallest* measured
    #: need rather than whichever variant happened to be tried first.
    need: tuple[float, float] | None = None
    #: The page-domain violation kind that caused the refusal, when one did. The
    #: two kinds a caller can act on (a keep-out on a module, a `mainPath` edge
    #: that cannot be a wire) are reported ahead of a generic geometry refusal,
    #: and this is how the no-candidate answer tells them apart.
    kind: str = ""


@dataclass
class PageCandidate:
    """One legal page, with the numbers the ranking was made from."""

    page: PageLayoutPlan
    metrics: dict[str, float]
    reasons: dict[str, list[str]]
    key: tuple[Any, ...]
    findings: list[str] = field(default_factory=list)

    def describe_key(self) -> str:
        """``legality=0, findings=0, backflow=0, …`` — the layers, in order."""
        names = (
            "legality", "findings", "backflow", "crossings", "bends",
            "cross_wire_length", "area",
        )
        return ", ".join(f"{name}={value:g}" for name, value in zip(names, self.key))


@dataclass
class PageCompileResult:
    """The compiler's whole answer: pages, refusals, and what each module cost.

    ``pages`` is what a caller draws or lands (3-8 geometry-distinct pages, best
    first); ``failures`` is why there is none, in 053 sec.4's categories, each
    naming the module it belongs to where one does; ``rejected`` is the audit
    trail of the variants that were built and lost; and ``modules`` keeps every
    module's own `CompileResult`, because "which group is the problem" is the
    first question a page-level refusal raises.
    """

    pages: list[PageLayoutPlan] = field(default_factory=list)
    ranked: list[PageCandidate] = field(default_factory=list)
    failures: list[GrammarFailure] = field(default_factory=list)
    rejected: list[PageRejection] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    modules: dict[str, drawcompiler.CompileResult] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """At least one legal page came out."""
        return bool(self.pages)

    def best(self) -> PageLayoutPlan | None:
        return self.pages[0] if self.pages else None

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
            line = f"[{item.category}] {item.subject}: {item.detail}"
            if item.action:
                line += f" — try: {item.action}"
            lines.append(line)
        return "\n".join(lines)


def page_layered_key(
    legality: int,
    findings: int,
    backflow: float,
    crossings: float,
    bends: float,
    cross_wire_length: float,
    compactness: float,
) -> tuple[int, int, float, float, float, float, float]:
    """The page ranking key: four layers, compared in order and never summed.

    052 sec.6 and 053 sec.7 forbid a total, and the page adds two metrics that
    have to land in the right layer rather than in a score:

    1. **legality** — the page domain's hard violations (0 for a candidate, kept
       in the key so the layer exists rather than being implicit);
    2. **circuit expression** — how well the page reads as the circuit's flow: the
       modules' grammar findings, then the **backflow length** (how far the
       connections run against the page's reading direction). A drawing whose
       signal walks backwards costs readability, but it is still a drawing of the
       right circuit, so it may not be bought back by a shorter wire *nor* allowed
       to outrank a broken relation;
    3. **readability** — crossings, bends, then the length of the wires that cross
       a module boundary;
    4. **compactness** — the area the module frames occupy.

    The label/line consistency of 056 sec.3 is **not** here: a page that mixes a
    wire with a name for one net is a hard violation, not a soft metric, because
    it is ambiguous rather than merely ugly.
    """
    return (
        int(legality),
        int(findings),
        float(backflow),
        float(crossings),
        float(bends),
        float(cross_wire_length),
        float(compactness),
    )


def _check_budget(budget: PageCompileBudget) -> None:
    if budget.page_box is None:
        raise PageCompileError(
            "budget.page_box is required: a page-level compile places modules on a "
            "sheet, and a page with no sheet has nothing to fit, no margin to keep "
            "and no keep-out frame to test against"
        )
    check_box(budget.page_box, "budget.page_box", PageCompileError)
    if (
        budget.page_box[2] - budget.page_box[0] <= 0
        or budget.page_box[3] - budget.page_box[1] <= 0
    ):
        raise PageCompileError(
            f"budget.page_box {budget.page_box!r} encloses no area"
        )
    for index, item in enumerate(budget.keepouts):
        if check_box(item, f"budget.keepouts[{index}]", PageCompileError) is None:
            raise PageCompileError(
                f"budget.keepouts[{index}] is not a box — an absent keep-out is one "
                "the caller should not have listed"
            )
    if isinstance(budget.grid, bool) or not isinstance(budget.grid, (int, float)):
        raise PageCompileError(f"grid must be a number, got {budget.grid!r}")
    if budget.grid <= 0:
        raise PageCompileError(f"grid must be positive, got {budget.grid!r}")
    if budget.max_candidates < 1:
        raise PageCompileError(
            f"budget.max_candidates is {budget.max_candidates!r}; a budget that "
            "allows no candidate cannot answer"
        )
    if budget.max_variants < 1:
        raise PageCompileError(
            f"budget.max_variants is {budget.max_variants!r}; the search is finite "
            "and its size has to be positive"
        )
    if not budget.gap_ladder:
        raise PageCompileError(
            "budget.gap_ladder is empty — the ladder is the whole reason a page can "
            "be retried with more room between its modules"
        )
    for value in budget.gap_ladder:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise PageCompileError(
                f"budget.gap_ladder holds {value!r}; every rung is a positive "
                "multiplier of the module gap"
            )
    for value, where in (
        (budget.module_gap, "module_gap"), (budget.frame_padding, "frame_padding"),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise PageCompileError(
                f"budget.{where} must be a non-negative number of canvas units, "
                f"got {value!r}"
            )
    if not isinstance(budget.module_budget, drawcompiler.CompileBudget):
        raise PageCompileError(
            "budget.module_budget must be a drawcompiler.CompileBudget — the module "
            "compile runs the single-module pipeline with it"
        )


# ---------------------------------------------------------------- the entry


def compile_page(
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    profiles: Mapping[str, SymbolProfile] | None = None,
    budget: PageCompileBudget | None = None,
) -> PageCompileResult:
    """Compile a page, or say why there is none.

    The stages are in the module docstring: the page's own reference checks, then
    one call to :func:`boardwise.engines.drawcompiler.compile` per module, then
    the variant search (ports, frames, placement, cross-module wires), then the
    gate (the merged drawing against the nine, the page against its own domain)
    and the layered ranking.
    """
    for value, expected in (
        (circuit_spec, CircuitSpec),
        (presentation_spec, PresentationSpec),
    ):
        if not isinstance(value, expected):
            raise PageCompileError(
                f"{expected.__name__} expected, got {type(value).__name__}"
            )
    budget = budget or PageCompileBudget()
    _check_budget(budget)
    book = drawcompiler.profile_book(profiles)

    result = PageCompileResult()
    result.notes.append(
        f"{PAGE_COMPILER_NAME}: lattice {budget.grid:g} units, module gap "
        f"{budget.module_gap:g} (ladder "
        + ", ".join(f"{value:g}x" for value in budget.gap_ladder)
        + f"), frame padding {budget.frame_padding:g}"
    )

    # 1. the page's own facts: who owns which part, where the flow points, and
    #    whether every page lock names a placed part at a point of this page.
    blockers = _reference_failures(circuit_spec, presentation_spec)
    blockers.extend(_page_lock_failures(circuit_spec, presentation_spec, budget))
    if blockers:
        result.failures = blockers
        return result

    # 2. every module, compiled by the single-module pipeline (a call).
    ctx = _Context(
        circuit=circuit_spec,
        presentation=presentation_spec,
        book=book,
        budget=budget,
        modules=list(presentation_spec.modules),
        results={},
        views={},
        nets_by_module=_nets_by_module(circuit_spec, presentation_spec),
    )
    failures = _compile_modules(ctx, result)
    if failures:
        result.failures = failures
        return result

    # 3. the variant search: orders x grid shapes x gap rungs x generations.
    orders = _placement_orders(ctx)
    seen: set[str] = set()
    for variant in _variants(orders, len(ctx.modules), budget):
        page, failure, violations, need, kind = _assemble(ctx, variant)
        if page is None:
            result.rejected.append(PageRejection(
                variant=variant.label,
                reason=failure.detail if failure is not None else "no legal page",
                failure=failure,
                violations=violations,
                need=need,
                kind=kind,
            ))
            continue
        digest = page.page_geometry_sha256()
        if digest in seen:
            # Two variants with the same page are one page: the digest is over
            # the module frames, origins and ports *and* the merged drawing, so
            # it says exactly this (052 sec.4's "预览绑定具体计划" rule, at page
            # scale).
            result.rejected.append(PageRejection(
                variant=variant.label,
                reason="the same page as an earlier variant",
            ))
            continue
        seen.add(digest)
        result.ranked.append(_measure(page))

    if not result.ranked:
        result.failures = _no_candidate_failures(result)
        return result

    result.ranked.sort(key=lambda item: item.key)
    result.pages = [
        item.page for item in result.ranked[: budget.max_candidates]
    ]
    result.notes.append(
        f"{len(result.pages)} legal page(s) from "
        f"{len(result.pages) + len(result.rejected)} variant(s) built; the gate "
        "was the independent readability checker (the nine on the merged drawing, "
        "the page domain on the frames), and the ranking compares its layers "
        "without summing them"
    )
    return result


def _measure(page: PageLayoutPlan) -> PageCandidate:
    """One gated page -> the numbers the ranking compares."""
    metrics = dict(page.page_evidence.soft_metrics)
    reasons = {key: [value] for key, value in page.page_evidence.soft_reasons.items()}
    findings = list(page.plan.evidence.grammar_findings)
    return PageCandidate(
        page=page,
        metrics=metrics,
        reasons=reasons,
        findings=findings,
        key=page_layered_key(
            len(page.plan.evidence.hard_violations)
            + len(page.page_evidence.hard_violations),
            len(findings),
            metrics.get("page_backflow_length", 0.0),
            metrics.get("page_crossings", 0.0),
            metrics.get("page_bends", 0.0),
            metrics.get("page_cross_module_wire_length", 0.0),
            metrics.get("page_area", 0.0),
        ),
    )


# ------------------------------------------------------ stage 1: the page's facts


def _reference_failures(
    circuit_spec: CircuitSpec, presentation_spec: PresentationSpec
) -> list[GrammarFailure]:
    """The page-level facts neither document can check about itself.

    Four questions, and each has one right answer:

    * which module owns each part — **the page has no reading of "no module" or
      "two modules"**: this layer compiles groups and places their frames, so a
      part that belongs to none has no frame that has to hold it, and a part in
      two would be drawn twice. Both are `presentation-poor`: the *intent* is what
      does not say where the part goes (053B pins the same vocabulary for a part
      claimed by two modules, and two layers may not disagree about one
      condition);
    * that a module's parts exist in the circuit — `facts-missing`;
    * that a flow edge names modules the page has, and that the flow is a partial
      order rather than a cycle — a cycle has no reading order, which is what the
      placement needs from it;
    * that every module resolves to a grammar — the module's own or the
      document's, `facts-missing` when neither is stated.
    """
    out: list[GrammarFailure] = []
    parts = set(circuit_spec.part_ids())
    modules = list(presentation_spec.modules)
    if not modules:
        return [GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject="PresentationSpec.modules",
            detail=(
                "the presentation declares no module — the page layer compiles "
                "groups and places their frames, so a page with no group is a page "
                "with no unit of placement"
            ),
            action=(
                "group the circuit's parts into PresentationSpec.modules[] entries "
                "(each part in exactly one), or compile it as a single drawing with "
                "the single-module compiler"
            ),
        )]

    for module in modules:
        unknown = sorted(part_id for part_id in module.parts if part_id not in parts)
        if unknown:
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=f"modules[{module.id}]",
                detail=(
                    f"module {module.id!r} groups {', '.join(unknown)}, which "
                    "CircuitSpec.parts does not declare — the module groups a part "
                    "that does not exist"
                ),
                action=(
                    "add the part to CircuitSpec.parts[] (or fix the id), or remove "
                    "it from the module"
                ),
            ))

    claims: dict[str, list[str]] = {}
    for module in modules:
        for part_id in module.parts:
            claims.setdefault(part_id, []).append(module.id)
    for part_id in sorted(claims):
        owners = claims[part_id]
        if len(owners) < 2:
            continue
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=part_id,
            detail=(
                f"{part_id} is claimed by modules "
                + " and ".join(repr(name) for name in owners)
                + " — a part belongs to one group on a page, and two frames "
                "claiming it would draw it twice"
            ),
            action=(
                f"list {part_id} in exactly one PresentationSpec.modules[] entry"
            ),
        ))
    for part_id in sorted(parts):
        if part_id in claims:
            continue
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=part_id,
            detail=(
                f"{part_id} belongs to no module — the page compiles module by "
                "module, so a part outside every group is a part the page never "
                "draws"
            ),
            action=(
                "add it to the module it belongs to, or drop it from the circuit "
                "if the page should not draw it"
            ),
        ))

    module_ids = {module.id for module in modules}
    for index, edge in enumerate(presentation_spec.flow):
        for name in (edge.from_module, edge.to_module):
            if name in module_ids:
                continue
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=f"flow[{index}]",
                detail=(
                    f"the flow edge {edge.from_module!r} -> {edge.to_module!r} names "
                    f"module {name!r}, which the presentation does not declare "
                    f"({', '.join(sorted(module_ids))})"
                ),
                action=(
                    "fix the module id — a flow edge orders two groups the page has"
                ),
            ))
    cycle = _flow_cycle(presentation_spec.flow, module_ids)
    if cycle:
        out.append(GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject="PresentationSpec.flow",
            detail=(
                "the flow is cyclic ("
                + ", ".join(cycle)
                + ") — the placement orders the modules by it, and a cycle has no "
                "reading order"
            ),
            action=(
                "remove the edge that closes the loop, or state the return path as "
                "a feedback path rather than as flow — a page is read along a "
                "partial order"
            ),
        ))

    for module in modules:
        grammar = module.grammar_ref or presentation_spec.grammar_ref
        if grammar:
            continue
        out.append(GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            subject=f"modules[{module.id}]",
            detail=(
                f"module {module.id!r} states no grammar and the document states "
                "none either, so nothing says what this group's drawing must make "
                "visible"
            ),
            action=(
                "set modules[].grammarRef for this group, or set the document's "
                "grammarRef if every module follows the same grammar"
            ),
        ))
    return out


def _lock_name(lock: UserLock) -> str:
    """How a refusal names a lock: the path an author finds it under."""
    scope = "page" if lock.is_page else "module"
    return f"presentationSpec.userLocks[{lock.part_id}@{scope}]"


def _page_lock_failures(
    circuit_spec: CircuitSpec,
    presentation_spec: PresentationSpec,
    budget: PageCompileBudget,
) -> list[GrammarFailure]:
    """The facts about a page lock that no arrangement can change (057 sec.3).

    A page lock names a part (it has to exist and sit in a module — the lock
    moves *that module*) and a point (it has to be on the page: "锁点必须落页内").
    Both are input facts, checked once, before any module is compiled; what a
    lock does to a particular arrangement is the placement's question.
    """
    out: list[GrammarFailure] = []
    parts = set(circuit_spec.part_ids())
    page = budget.page_box
    assert page is not None  # `_check_budget` refuses a page without one
    for lock in presentation_spec.page_locks():
        name = _lock_name(lock)
        if lock.part_id not in parts:
            out.append(GrammarFailure(
                category=FAILURE_FACTS_MISSING,
                subject=name,
                detail=(
                    f"the page lock names {lock.part_id}, which CircuitSpec.parts "
                    "does not declare — a lock moves a part's module, and there is "
                    "no part to move"
                ),
                action="fix the lock's partId, or drop the lock",
            ))
            continue
        if not presentation_spec.modules_of_part(lock.part_id):
            # The part-in-no-module refusal of `_reference_failures` names it
            # already; a second line here would be the same fact twice.
            continue
        if not (
            page[0] - 1e-6 <= lock.x <= page[2] + 1e-6
            and page[1] - 1e-6 <= lock.y <= page[3] + 1e-6
        ):
            out.append(GrammarFailure(
                category=FAILURE_PRESENTATION_POOR,
                subject=name,
                detail=(
                    f"the page lock puts {lock.part_id} at "
                    f"{_point_text((lock.x, lock.y))}, which is outside the page "
                    f"{page[0]:g},{page[1]:g}–{page[2]:g},{page[3]:g} — a lock point "
                    "is a point of the page (057 sec.3)"
                ),
                action=(
                    "move the lock point onto the page, or state the page the lock "
                    "was measured on (--page-box)"
                ),
            ))
    return out


def _flow_cycle(
    flow: Sequence[FlowEdge], module_ids: Iterable[str]
) -> list[str]:
    """The modules left over when the flow's own order cannot be built.

    Kahn's algorithm, deterministically: what remains unprocessed is exactly the
    set that is on or behind a cycle, and naming it is more useful than naming
    one edge of it (which edge closed the loop is a judgement the reader makes).
    """
    nodes = sorted(module_ids)
    edges = [
        (edge.from_module, edge.to_module) for edge in flow
        if edge.from_module in set(nodes) and edge.to_module in set(nodes)
    ]
    remaining = {name: 0 for name in nodes}
    for _source, target in edges:
        remaining[target] += 1
    queue = sorted(name for name in nodes if remaining[name] == 0)
    processed: list[str] = []
    while queue:
        here = queue.pop(0)
        processed.append(here)
        for source, target in edges:
            if source != here:
                continue
            remaining[target] -= 1
            if remaining[target] == 0:
                queue.append(target)
                queue.sort()
    if len(processed) == len(nodes):
        return []
    return sorted(set(nodes) - set(processed))


# ------------------------------------------- stage 2: the module-local views


@dataclass
class _Context:
    """Everything a variant needs, built once per compile."""

    circuit: CircuitSpec
    presentation: PresentationSpec
    book: dict[str, SymbolProfile]
    budget: PageCompileBudget
    modules: list[PresentationModule]
    #: module id -> its own `CompileResult` (the single-module pipeline's answer).
    results: dict[str, drawcompiler.CompileResult]
    #: module id -> the module-local view of both documents it was compiled from.
    views: dict[str, tuple[CircuitSpec, PresentationSpec]]
    #: net id -> the modules that have members of it, sorted.
    nets_by_module: dict[str, tuple[str, ...]]

    def module(self, module_id: str) -> PresentationModule | None:
        for item in self.modules:
            if item.id == module_id:
                return item
        return None

    def shared_nets(self, module_id: str) -> list[str]:
        """The nets this module states to the page, sorted (spans two modules)."""
        return sorted(
            net_id for net_id, modules in self.nets_by_module.items()
            if module_id in modules and len(modules) > 1
        )

    def module_local_net(self, module_id: str, net_id: str) -> SpecNet | None:
        """The net as the module's own drawing sees it (its members only)."""
        return self.views[module_id][0].net(net_id)


def _nets_by_module(
    circuit_spec: CircuitSpec, presentation_spec: PresentationSpec
) -> dict[str, tuple[str, ...]]:
    """``net id -> the modules owning members of it``, sorted (the page's scoping).

    The same derivation `readability.check_page` makes: a net is shared when two
    modules have members of it, and the page may not be told otherwise — the
    shared-net list is *derived* from the circuit (056 sec.1: "声明会撒谎，推导
    不会").
    """
    out: dict[str, tuple[str, ...]] = {}
    for net in circuit_spec.nets:
        owners = {member.partition(".")[0] for member in net.members}
        out[net.id] = tuple(sorted(
            module.id for module in presentation_spec.modules
            if owners & set(module.parts)
        ))
    return out


def _module_view(
    circuit_spec: CircuitSpec, presentation_spec: PresentationSpec, module: PresentationModule
) -> tuple[CircuitSpec, PresentationSpec]:
    """The module-local view of both documents, as a *filtered* pair.

    The circuit keeps the module's parts and, for every net, the members that are
    inside: a shared net keeps its id and its class and loses the members that
    belong to other modules, which is exactly what "this drawing only draws these
    parts" means. The presentation keeps one module (this one), the module's own
    grammar and side preferences, and the page-wide facts that still make sense
    inside one group — its port roles, its wiring obligations, its locks.

    An obligation is kept **only for a net this module has two or more members
    of**: "a local topology is wired" (052 sec.5) is a statement about a local
    connection, and a module holding one pin of a shared net has none to protect.
    The cross-module connection of that net is the page's own decision
    (:func:`_net_style`), and the obligation does not decide it — a page-level
    wire is what the `mainPath` mark asks for.

    Filtering is not optional: the grammar binders scope themselves by
    `presentation.modules` (053 sec.3), so a module compiled with the page's whole
    module list would see the chain it is drawing as *split across modules* and
    refuse.
    """
    part_ids = set(module.parts)
    parts = [part for part in circuit_spec.parts if part.id in part_ids]
    nets: list[SpecNet] = []
    for net in circuit_spec.nets:
        members = [member for member in net.members
                   if member.partition(".")[0] in part_ids]
        if not members:
            continue
        nets.append(SpecNet(
            id=net.id,
            cls=net.cls,
            members=members,
            provenance=net.provenance,
            member_provenance={
                member: label for member, label in net.member_provenance.items()
                if member in members
            },
            scope=net.scope,
        ))
    net_ids = {net.id for net in nets}
    sub_circuit = CircuitSpec(
        parts=parts,
        nets=nets,
        nc=[
            SpecNoConnect(pin=item.pin, provenance=item.provenance)
            for item in circuit_spec.nc
            if item.pin.partition(".")[0] in part_ids
        ],
        open_interfaces=[
            SpecOpenInterface(
                net=item.net, direction=item.direction, role=item.role,
                provenance=item.provenance,
            )
            for item in circuit_spec.open_interfaces
            if item.net in net_ids
        ],
        operating_conditions=dict(circuit_spec.operating_conditions),
    )
    sub_presentation = PresentationSpec(
        modules=[PresentationModule(
            id=module.id, parts=list(module.parts), role=module.role,
        )],
        main_paths=_module_paths(presentation_spec.main_paths, part_ids, net_ids),
        feedback_paths=_module_paths(
            presentation_spec.feedback_paths, part_ids, net_ids
        ),
        port_roles={
            net_id: role for net_id, role in presentation_spec.port_roles.items()
            if net_id in net_ids
        },
        grammar_ref=module.grammar_ref or presentation_spec.grammar_ref,
        direct_wiring_obligations=[
            DirectWiringObligation(
                nets=[
                    net_id for net_id in item.nets
                    if net_id in net_ids and len(sub_circuit.net(net_id).members) > 1
                ],
                note=item.note,
            )
            for item in presentation_spec.direct_wiring_obligations
            if any(net_id in net_ids for net_id in item.nets)
        ],
        label_policy=presentation_spec.label_policy,
        side_preferences=presentation_spec.sides_for_module(module),
        # Module locks only: a page lock is measured on a page the module
        # compile does not have, and it is honoured by the placement (the
        # module's origin), never by bending the module's own drawing (057 sec.3).
        user_locks=[
            lock for lock in presentation_spec.user_locks
            if lock.part_id in part_ids and not lock.is_page
        ],
    )
    return sub_circuit, sub_presentation


def _module_paths(
    paths: Sequence[PresentationPath], part_ids: set[str], net_ids: set[str]
) -> list[PresentationPath]:
    """Paths cut down to the steps this module holds (a path may span modules).

    A step outside the module is dropped rather than passed on: the module
    compiler checks every path step against its own circuit, and a step naming
    another module's part would come back as `facts-missing` about a part the
    module legitimately does not draw.
    """
    out: list[PresentationPath] = []
    for path in paths:
        chain = [
            step for step in path.chain
            if (step.partition(":")[2] in part_ids
                if step.startswith("part:") else step.partition(":")[2] in net_ids)
        ]
        if not chain:
            continue
        out.append(PresentationPath(id=path.id, chain=chain, note=path.note))
    return out


def _compile_modules(
    ctx: _Context, result: PageCompileResult
) -> list[GrammarFailure]:
    """Compile every module with a call into the single-module pipeline.

    A module that cannot be drawn is reported **against that module** and the
    modules that are fine are not blamed (056 sec.5): the failure carries the
    module's own category — its grammar's `circuit-invalid`, or the geometry
    pipeline's `layout-unsat` — with the module named in the subject and in the
    first line of the detail.
    """
    module_budget = ctx.budget.module_budget
    failures: list[GrammarFailure] = []
    for module in ctx.modules:
        sub_circuit, sub_presentation = _module_view(
            ctx.circuit, ctx.presentation, module
        )
        ctx.views[module.id] = (sub_circuit, sub_presentation)
        compiled = drawcompiler.compile(
            sub_circuit,
            sub_presentation,
            ctx.book,
            _module_budget_for(module_budget, ctx.budget),
        )
        ctx.results[module.id] = compiled
        result.modules[module.id] = compiled
        if compiled.ok:
            continue
        first = compiled.failures[0] if compiled.failures else None
        grammar = module.grammar_ref or ctx.presentation.grammar_ref
        failures.append(GrammarFailure(
            category=first.category if first is not None else FAILURE_LAYOUT_UNSAT,
            subject=f"modules[{module.id}]",
            detail=(
                f"module {module.id!r} (grammar {grammar!r}) could not be drawn: "
                + (first.detail if first is not None else "no reason was recorded")
                + f" [{compiled.categories() or 'no category'} · "
                f"{len(compiled.failures)} failure(s), {len(compiled.rejected)} "
                "variant(s) refused inside the module]"
            ),
            action=(
                first.action if first is not None and first.action else
                "fix this module's own circuit or presentation; the other modules "
                "are not involved in this refusal"
            ),
        ))
    return failures


def _module_budget_for(
    module_budget: drawcompiler.CompileBudget, page_budget: PageCompileBudget
) -> drawcompiler.CompileBudget:
    """The module compile's budget: the caller's, with the page taken out of it.

    A module is compiled *without* a page and *without* keep-outs. It has to be:
    the module's frame is what the page places, so the module's drawing must
    define its own extent — compiled against the sheet it would be anchored to
    the sheet's corner, every module on top of every other. The grid is the
    page's, because the placement and the cross-module wires run on that lattice.
    """
    return drawcompiler.CompileBudget(
        page_box=None,
        keepouts=(),
        grid=page_budget.grid,
        min_candidates=module_budget.min_candidates,
        max_candidates=module_budget.max_candidates,
        spacing_ladder=module_budget.spacing_ladder,
        channel=module_budget.channel,
        lane=module_budget.lane,
        stub=module_budget.stub,
        high_fanout=module_budget.high_fanout,
        near_limit=module_budget.near_limit,
        gnd_flag=module_budget.gnd_flag,
        power_flag_prefix=module_budget.power_flag_prefix,
    )


# ------------------------------------------------ stage 3: orders and variants


def _placement_orders(ctx: _Context) -> list[tuple[str, ...]]:
    """The module sequences the page may be placed in, deterministically.

    Every sequence that respects the flow (056 sec.2: "flow 给出偏序，不做全排列
    爆炸"), enumerated in a fixed order and cut at :data:`MAX_ORDERS`; a page that
    states no flow is read in module-name order, which is the fallback the task
    book fixes ("无 flow 边时按模块名排序兜底").
    """
    names = sorted(module.id for module in ctx.modules)
    edges = [
        (edge.from_module, edge.to_module) for edge in ctx.presentation.flow
        if edge.from_module in set(names) and edge.to_module in set(names)
    ]
    if not edges:
        return [tuple(names)]
    out: list[tuple[str, ...]] = []

    def walk(done: tuple[str, ...], left: tuple[str, ...]) -> None:
        if len(out) >= MAX_ORDERS:
            return
        if not left:
            out.append(done)
            return
        for name in left:
            blocked = any(
                target == name and source in left for source, target in edges
            )
            if blocked:
                continue
            walk(done + (name,), tuple(item for item in left if item != name))
            if len(out) >= MAX_ORDERS:
                return

    walk((), tuple(names))
    return out or [tuple(names)]


#: How many topological orders of the flow are enumerated. Six is far more than
#: the 3-8 candidate window needs, and the cut keeps a page with many modules from
#: enumerating factorially many orders (056 sec.2's "不做全排列爆炸").
MAX_ORDERS = 6


@dataclass(frozen=True)
class _Variant:
    """One point of the finite page search."""

    generation: int
    order: tuple[str, ...]
    columns: int
    rung: float

    @property
    def label(self) -> str:
        return (
            f"generation={self.generation} columns={self.columns} "
            f"gap={self.rung:g}x order={'/'.join(self.order)}"
        )


def _variants(
    orders: Sequence[tuple[str, ...]], count: int, budget: PageCompileBudget
) -> list[_Variant]:
    """The finite search space, in a fixed order and cut at `max_variants`.

    Generation is the outer loop: the first variants use every module's own best
    drawing, and the second generation uses each module's runner-up, so "the page
    needs a different module drawing" is reachable without a product over
    modules. Columns then run from one to the module count (a stack, a row, and
    everything between), and the gap ladder gives a crowded page more room.
    """
    variants: list[_Variant] = []
    for generation in (0, 1):
        for order in orders:
            for columns in range(1, count + 1):
                for rung in budget.gap_ladder:
                    variants.append(_Variant(
                        generation=generation, order=order, columns=columns,
                        rung=float(rung),
                    ))
                    if len(variants) >= budget.max_variants:
                        return variants
    return variants


# --------------------------------------------- stage 4: ports, frames, places


@dataclass
class _Assembled:
    """One module assembled for one variant: its ports and the box it occupies."""

    module: PresentationModule
    #: The module's own drawing, with the page's port work applied to it. All
    #: coordinates are still module-local; the placement translates it.
    plan: LayoutPlan
    #: The digest of the module's own compiled drawing *before* the page
    #: re-expressed its boundary nets — what the page document records as the
    #: internal plan it came from.
    internal_sha256: str
    ports: list[PagePort]
    frame: Box


def _assemble(
    ctx: _Context, variant: _Variant
) -> tuple[
    PageLayoutPlan | None, GrammarFailure | None, list[str],
    tuple[float, float] | None, str,
]:
    """One variant -> one gated page, or the measured reason there is none."""
    index = {name: position for position, name in enumerate(variant.order)}
    assembled: list[_Assembled] = []
    sources: dict[str, LayoutPlan] = {}
    for module in ctx.modules:
        candidates = ctx.results[module.id].candidates
        source = candidates[min(variant.generation, len(candidates) - 1)]
        sources[module.id] = source
        plan = _copy_plan(source)
        ports, failure = _module_ports(ctx, module, plan, variant, index)
        if failure is not None:
            return None, failure, [], None, ""
        assembled.append(_Assembled(
            module=module,
            plan=plan,
            internal_sha256=source.geometry_sha256(),
            ports=ports,
            frame=_module_frame(plan, ctx.book, ctx.budget.frame_padding),
        ))
    by_id = {item.module.id: item for item in assembled}

    locked, failure = _lock_origins(ctx, variant, sources)
    if failure is not None:
        return None, failure, [], None, KIND_PAGE_LOCK_CONTRADICTION

    offsets, placed_frames, failure, need, kind = _place(
        assembled, variant, ctx.budget, locked
    )
    if failure is not None:
        return None, failure, [], need, kind

    drawn = _merge(by_id, variant.order, offsets)
    wired = _wire_shared_nets(ctx, variant, index, by_id, drawn, placed_frames)
    if isinstance(wired, GrammarFailure):
        return None, wired, [], None, ""
    drawn = wired

    merged = LayoutPlan(
        source=LayoutSource(
            circuit_sha256=ctx.circuit.sha256(),
            presentation_sha256=ctx.presentation.sha256(),
        ),
        parts=drawn.parts,
        segments=drawn.segments,
        junctions=drawcompiler.wire_junctions(drawn.segments),
        labels=drawn.labels,
        power_symbols=drawn.symbols,
        texts=drawn.texts,
        notes=[
            f"merged by {PAGE_COMPILER_NAME} from {len(assembled)} module "
            "drawing(s), each compiled by the single-module compiler",
            "module origins are the page's placement; the frames are in the page "
            "document, not in the drawing the editor sees",
            "the page states each net that spans modules the same way at every "
            "end: a label, a flag, or one whole wire on a main-path edge",
        ],
    )
    page = PageLayoutPlan(
        plan=merged,
        modules=[
            PageModule(
                id=item.module.id,
                grammar_ref=(
                    item.module.grammar_ref or ctx.presentation.grammar_ref
                ),
                parts=list(item.module.parts),
                origin=offsets[item.module.id],
                frame=placed_frames[item.module.id],
                internal_geometry_sha256=item.internal_sha256,
                ports=sorted(
                    drawn.ports[item.module.id], key=lambda port: port.net
                ),
            )
            for item in assembled
        ],
        flow=list(ctx.presentation.flow),
        page_box=ctx.budget.page_box,
        notes=[
            f"{PAGE_COMPILER_NAME} variant {variant.label}",
            "one port per shared net per module; ports are the points at which a "
            "module states a net to the page (a label's anchor, a flag's anchor, "
            "or a whole cross-module wire's end)",
        ],
    )
    return _gate(ctx, variant, page, assembled, offsets)


def _copy_plan(plan: LayoutPlan) -> LayoutPlan:
    """A working copy of a module's drawing.

    The page re-expresses a module's boundary net on the way to the page (a flag
    becomes a label, a label gives way to a whole wire), and it must not touch the
    `CompileResult` the caller may still be holding: the module compile's answer
    is evidence about one group, and the page's edits are the page's.
    """
    return LayoutPlan(
        source=LayoutSource(
            circuit_sha256=plan.source.circuit_sha256,
            presentation_sha256=plan.source.presentation_sha256,
        ),
        parts=[
            LayoutPart(
                part_id=item.part_id, symbol_ref=item.symbol_ref,
                symbol_hash=item.symbol_hash, x=item.x, y=item.y,
                rotation=item.rotation, mirror=item.mirror, reference=item.reference,
            )
            for item in plan.parts
        ],
        segments=[
            LayoutSegment(net=item.net, points=list(item.points))
            for item in plan.segments
        ],
        junctions=[],
        labels=[
            LayoutLabel(
                net=item.net, text=item.text, bbox=item.bbox, x=item.x, y=item.y,
                rotation=item.rotation,
            )
            for item in plan.labels
        ],
        power_symbols=[
            LayoutPowerSymbol(
                symbol_ref=item.symbol_ref, symbol_hash=item.symbol_hash,
                net=item.net, x=item.x, y=item.y, rotation=item.rotation,
            )
            for item in plan.power_symbols
        ],
        texts=[
            LayoutText(
                kind=item.kind, text=item.text, bbox=item.bbox,
                part_id=item.part_id, x=item.x, y=item.y, rotation=item.rotation,
            )
            for item in plan.texts
        ],
        notes=list(plan.notes),
    )


# ----------------------------------------------------------- stage 4a: ports


def _module_ports(
    ctx: _Context,
    module: PresentationModule,
    plan: LayoutPlan,
    variant: _Variant,
    index: Mapping[str, int],
) -> tuple[list[PagePort], GrammarFailure | None]:
    """How this module states each shared net to the page.

    One port per shared net, and the port is what the *page* needs: the point at
    which the module's own drawing carries that net (a pin tip, a label's anchor,
    a flag's anchor), plus the kind of statement the page decided for the net
    globally. Where the module's drawing already says something of the other kind
    for that net, the page rewrites it at the same point — see the module
    docstring's third decision.
    """
    occupied = _module_boxes(plan, ctx.book)
    pins = _pin_points(plan, ctx.book)
    out: list[PagePort] = []
    for net_id in ctx.shared_nets(module.id):
        style, reason = _net_style(ctx, variant, net_id, index)
        plan.notes.append(f"net {net_id}: {reason}")
        direction = _port_direction(
            index[module.id], variant.columns, len(variant.order),
            _has_later_partner(ctx, net_id, module.id, index),
        )
        local = ctx.views[module.id][0].net(net_id)
        point = _port_point(
            local.members if local is not None else (), pins, direction
        )
        if point is None:
            return [], GrammarFailure(
                category=FAILURE_LAYOUT_UNSAT,
                subject=f"modules[{module.id}]",
                detail=(
                    f"module {module.id!r} holds net {net_id!r} but its drawing has "
                    "no placed pin of that net, so the page has nothing to state the "
                    "net at"
                ),
                action=(
                    "report this run: a module that draws a net without its pins is "
                    "a compiler defect"
                ),
            )
        port, failure = _port(
            ctx, module, plan, net_id, style, point, direction, occupied, pins
        )
        if failure is not None:
            return [], failure
        assert port is not None
        # Which module this port talks to. One partner when the net reaches exactly
        # two modules (the case a page-level connection is drawn for); empty when
        # it reaches more, because then there is no single other side and a
        # fabricated one would be a fact the page cannot support.
        owners = ctx.nets_by_module[net_id]
        partner = (
            next((name for name in owners if name != module.id), "")
            if len(owners) == 2
            else ""
        )
        out.append(PagePort(
            module=port.module, net=port.net, kind=port.kind, x=port.x, y=port.y,
            partner=partner,
        ))
    return sorted(out, key=lambda item: item.net), None


def _net_style(
    ctx: _Context, variant: _Variant, net_id: str, index: Mapping[str, int]
) -> tuple[str, str]:
    """``(label | flag | wire, why)`` for one shared net, for this arrangement.

    The questions are 056 sec.2's, with 069 sec.7's edit to the first one:

    1. a **bus** — a ground, and now *any* power net — is expressed by its flag at
       every end (053 sec.7: it may never grow into a page-wide wire tree). 岳
       reads a rail by its flag (「P23 5V部分为什么不给旗标？」: a rail the page states
       by text alone is the defect), and the fan-out threshold that used to let a
       small rail be named is gone. The one exception is the edge the presentation
       itself marks `mainPath`: that mark asks for **one run** between the two
       modules, which is 056 sec.2's contract and cannot be kept by a flag at each
       end — so a main-path *rail* is still a whole wire when the modules are
       adjacent (and is refused and named when they are not, 056 sec.3). A
       main-path mark on a *ground* is still refused the same way: a ground is
       never a wire.
    2. a net shared by exactly two modules, with a `mainPath` edge between them,
       and the two modules adjacent on this page, is a **whole wire** — the one
       case where the connection is drawn end to end;
    3. otherwise the two ends are **named**, and the page's own consistency rule
       makes them both labels or both flags.
    """
    net = ctx.circuit.net(net_id)
    modules = ctx.nets_by_module[net_id]
    main_path = len(modules) == 2 and bool(_main_path_edges(ctx, set(modules)))
    if net is not None and _is_bus(net, ctx.budget.module_budget.high_fanout):
        if not (main_path and net.cls == "power"):
            profile, ref = _flag_profile(ctx, net)
            if profile is None:
                return (
                    PAGE_PORT_LABEL,
                    f"the library carries no flag symbol {ref!r}, so this bus is "
                    "named by labels at both ends (one style throughout)",
                )
            return (
                PAGE_PORT_FLAG,
                f"a bus of {len(net.members)} member(s) is expressed by its flag at "
                "every end (053 sec.7: it may never become a page-wide wire tree; "
                "069 sec.7: a rail is a bus at any fan-out)",
            )
    if main_path:
        if _adjacent(index[modules[0]], index[modules[1]], variant.columns, len(index)):
            return (
                PAGE_PORT_WIRE,
                f"the presentation marks the edge {modules[0]} -> {modules[1]} "
                "main-path and the two modules are adjacent, so the connection is "
                "one wire from port to port (056 sec.2)",
            )
        return (
            PAGE_PORT_LABEL,
            f"the edge {modules[0]} -> {modules[1]} is marked main-path but the two "
            "modules are not adjacent in this arrangement, so it is named; the "
            "variant is refused by the page checker rather than downgraded quietly",
        )
    return (
        PAGE_PORT_LABEL,
        "a net that crosses a module boundary is named at each end "
        "(labelPolicy.crossModule is 'label')",
    )


def _port(
    ctx: _Context,
    module: PresentationModule,
    plan: LayoutPlan,
    net_id: str,
    style: str,
    point: tuple[float, float],
    direction: tuple[float, float],
    occupied: list[Box],
    pins: Mapping[str, tuple[float, float]],
) -> tuple[PagePort | None, GrammarFailure | None]:
    """State one net on the page, rewriting the module's own statement if needed.

    ``point`` is the port's conductor (a pin tip of one of the net's members).
    Whenever the module's current statement has to give way, the page's new one is
    put at a point the module's wiring still holds *afterwards* — never at a flag's
    anchor or a tap stub's end whose wire the rewrite takes away, because a name
    that touches no conductor is a name that connects nothing.
    """
    tips = {_round(candidate) for candidate in pins.values()}
    labels = [item for item in plan.labels if item.net == net_id]
    symbols = [item for item in plan.power_symbols if item.net == net_id]

    if style in (PAGE_PORT_WIRE, PAGE_PORT_FLAG):
        stray = [
            item for item in labels if _round((item.x, item.y)) not in tips
        ]
        if stray:
            return None, GrammarFailure(
                category=FAILURE_PRESENTATION_POOR,
                subject=f"modules[{module.id}]",
                detail=(
                    f"net {net_id!r} is stated inside module {module.id!r} at "
                    f"{_point_text((stray[0].x, stray[0].y))}, which is not one of "
                    "the net's pin tips — the statement sits at the end of the "
                    "module's own wire (a tap stub), so restating the boundary "
                    "connection there would either drop the wire the grammar "
                    "promises or leave a wire the name no longer holds"
                ),
                action=(
                    "drop the mainPath mark for this edge (a name is then the "
                    "connection), or restate this module's own tap so its label is "
                    "not the only thing holding its stub — the page neither "
                    "downgrades a main-path edge quietly nor drops a promised wire"
                ),
            )

    if style == PAGE_PORT_WIRE:
        _drop_statements(plan, net_id)
        return PagePort(
            module=module.id, net=net_id, kind=PAGE_PORT_WIRE,
            x=point[0], y=point[1],
        ), None

    if style == PAGE_PORT_LABEL:
        if labels:
            anchor = _extreme_anchor([(item.x, item.y) for item in labels], direction)
            return PagePort(
                module=module.id, net=net_id, kind=PAGE_PORT_LABEL,
                x=anchor[0], y=anchor[1],
            ), None
        if symbols:
            _drop_statements(plan, net_id)
        label = _add_label(plan, net_id, point, direction, occupied)
        return PagePort(
            module=module.id, net=net_id, kind=PAGE_PORT_LABEL,
            x=label.x, y=label.y,
        ), None

    # PAGE_PORT_FLAG
    if symbols:
        anchor = _extreme_anchor([(item.x, item.y) for item in symbols], direction)
        return PagePort(
            module=module.id, net=net_id, kind=PAGE_PORT_FLAG,
            x=anchor[0], y=anchor[1],
        ), None
    symbol, failure = _add_flag(ctx, plan, net_id, point, direction, occupied)
    if failure is not None:
        return None, failure
    assert symbol is not None
    return PagePort(
        module=module.id, net=net_id, kind=PAGE_PORT_FLAG,
        x=symbol.x, y=symbol.y,
    ), None


def _add_label(
    plan: LayoutPlan,
    net_id: str,
    point: tuple[float, float],
    preferred: tuple[float, float],
    occupied: list[Box],
) -> LayoutLabel:
    """State a net with a label at `point`, and put it in the drawing.

    The label is appended to the module's own plan, because that is what the page
    lands: the port table is the page's record, and the *drawing* has to carry the
    label or the name is a fact of the document and not of the page.
    """
    box = _label_box(net_id, point, preferred, occupied)
    occupied.append(box)
    label = LayoutLabel(
        net=net_id, text=net_id, bbox=box, x=point[0], y=point[1],
    )
    plan.labels.append(label)
    return label


def _add_flag(
    ctx: _Context,
    plan: LayoutPlan,
    net_id: str,
    point: tuple[float, float],
    direction: tuple[float, float],
    occupied: list[Box],
) -> tuple[LayoutPowerSymbol | None, GrammarFailure | None]:
    """A rail/ground flag at `point`, or the reason the library has none."""
    net = ctx.circuit.net(net_id)
    profile, ref = _flag_profile(ctx, net)
    if profile is None:
        return None, GrammarFailure(
            category=FAILURE_FACTS_MISSING,
            subject=net_id,
            detail=(
                f"net {net_id!r} is expressed with a flag, and the library carries "
                f"no symbol {ref!r} with pins to place"
            ),
            action=(
                f"add {ref!r} to the SymbolProfile book, or state "
                "labelPolicy.highFanout as 'label' and let the net be named by "
                "labels at both ends"
            ),
        )
    rotation = drawcompiler.flag_rotation(direction, flag_glyph_kind(profile))
    symbol = LayoutPowerSymbol(
        symbol_ref=profile.symbol_ref,
        symbol_hash=profile.geometry_hash(),
        net=net_id,
        x=point[0], y=point[1],
        rotation=rotation,
    )
    glyph = _glyph_box(profile, rotation, point)
    if glyph is not None:
        occupied.append(glyph)
    plan.power_symbols.append(symbol)
    return symbol, None


def _drop_statements(plan: LayoutPlan, net_id: str) -> None:
    """Remove every name this module states for the net, and the leads to them.

    Only the *boundary* statement goes: the wires the module drew for that net
    stay (they carry the module's own local topology, which may itself be a
    promise). A lead wire drawn solely to reach a removed anchor would then be a
    wire end in mid-air, so a two-point segment that ends at a removed anchor is
    removed with it — the page checker's `dangling-wire-end` is what catches a
    mistake here, which is why the removal is done by point rather than by hope.

    A *stub* (the tap's, whose label is dropped with it) is removed the same way,
    which is exactly why the callers refuse a rewrite when the dropped name is the
    only thing holding that wire (see `_port`).
    """
    anchors = {
        _round((item.x, item.y)) for item in plan.labels if item.net == net_id
    } | {
        _round((item.x, item.y)) for item in plan.power_symbols if item.net == net_id
    }
    plan.labels = [item for item in plan.labels if item.net != net_id]
    plan.power_symbols = [item for item in plan.power_symbols if item.net != net_id]
    for anchor in anchors:
        plan.segments = [
            item for item in plan.segments
            if not (
                item.net == net_id
                and anchor in {_round(item.points[0]), _round(item.points[-1])}
                and _is_lead(item.points, anchor)
            )
        ]


def _is_lead(points: Sequence[tuple[float, float]], anchor: tuple[float, float]) -> bool:
    """Is this segment just a flag's lead — a run to the anchor, straight or bent?

    A lead is what `_flag_anchor` draws: the pin, at most one corner, and the
    anchor. 069 sec.10 made the corner the normal shape (岳's own VIN runs out 40 and
    turns 20 up, his left VOUT pad 60 then 30), so a bent lead counts — what still
    does not is a longer polyline that merely *ends* at the anchor: that is the
    module's own wiring, and removing it would take a local topology with it.
    """
    at_anchor = [
        index for index, point in enumerate(points)
        if _round(point) == _round(anchor)
    ]
    if not at_anchor:
        return False
    if len(points) <= 3:
        return True
    return False


def _flag_profile(
    ctx: _Context, net: SpecNet | None
) -> tuple[SymbolProfile | None, str]:
    """``(flag profile, symbol ref)`` — the library's flag for this net.

    The ref is derived from the net, never from a scenario: the ground flag is the
    module budget's `gnd_flag`, a rail's is `power_flag_prefix` + the net id. The
    same rule the module compiler applies, so a page and the drawings on it cannot
    disagree about which symbol means "VIN".
    """
    cls = net.cls if net is not None else "gnd"
    net_id = net.id if net is not None else ""
    ref = (
        ctx.budget.module_budget.gnd_flag
        if cls == "gnd"
        else f"{ctx.budget.module_budget.power_flag_prefix}{net_id}"
    )
    profile = ctx.book.get(ref)
    if profile is None:
        return None, ref
    return profile, ref


# ------------------------------------------------------ stage 4b: frames


def _module_frame(plan: LayoutPlan, book: Mapping[str, SymbolProfile], padding: float) -> Box:
    """The box a module occupies on the page: its own drawing, plus padding.

    The rules are the module compiler's own (`_plan_bbox`): parts including their
    pin tips, texts, labels with their boxes and anchors, flags with their glyphs,
    and the wires — everything a reader sees. Nothing here *verifies* the module's
    drawing (the module's own gate did that); the frame is the rigid body the page
    places, and `readability.check_page` verifies the stated frame against the
    geometry rather than trusting this computation.
    """
    boxes: list[Box] = []
    for part in plan.parts:
        profile = book.get(part.symbol_ref)
        if profile is None:
            boxes.append((part.x, part.y, part.x, part.y))
            continue
        boxes.append(_part_extent(profile, part))
    for text in plan.texts:
        boxes.append(text.bbox)
    for label in plan.labels:
        boxes.append(label.bbox)
        boxes.append((label.x, label.y, label.x, label.y))
    for symbol in plan.power_symbols:
        boxes.append((symbol.x, symbol.y, symbol.x, symbol.y))
        profile = book.get(symbol.symbol_ref)
        if profile is not None:
            glyph = _glyph_box(profile, symbol.rotation, (symbol.x, symbol.y))
            if glyph is not None:
                boxes.append(glyph)
    for segment in plan.segments:
        boxes.append(_bounds(segment.points))
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    frame = (
        min(box[0] for box in boxes), min(box[1] for box in boxes),
        max(box[2] for box in boxes), max(box[3] for box in boxes),
    )
    return (
        frame[0] - padding, frame[1] - padding,
        frame[2] + padding, frame[3] + padding,
    )


def _module_boxes(plan: LayoutPlan, book: Mapping[str, SymbolProfile]) -> list[Box]:
    """The boxes a new label must avoid: what the module's drawing already occupies.

    The same set the module compiler keeps for its own text placement (part
    extents, texts, labels, flags), recomputed for a page-added port because the
    page places the label and it must land in a free spot of *this* module.
    """
    boxes: list[Box] = []
    for part in plan.parts:
        profile = book.get(part.symbol_ref)
        if profile is not None:
            boxes.append(_part_extent(profile, part))
    boxes.extend(text.bbox for text in plan.texts)
    boxes.extend(label.bbox for label in plan.labels)
    boxes.extend(
        (label.x, label.y, label.x, label.y) for label in plan.labels
    )
    for symbol in plan.power_symbols:
        profile = book.get(symbol.symbol_ref)
        if profile is not None:
            glyph = _glyph_box(profile, symbol.rotation, (symbol.x, symbol.y))
            if glyph is not None:
                boxes.append(glyph)
    boxes.extend(_bounds(item.points) for item in plan.segments)
    return boxes


# ----------------------------------------------------- stage 4c: the placement


def _place(
    assembled: Sequence[_Assembled],
    variant: _Variant,
    budget: PageCompileBudget,
    locked: Mapping[str, tuple[tuple[float, float], tuple[UserLock, ...]]] | None = None,
) -> tuple[
    dict[str, tuple[float, float]], dict[str, Box], GrammarFailure | None,
    tuple[float, float] | None, str,
]:
    """Frames on the page's grid, flow order respected, gaps kept.

    The arrangement is anchored to the page's top-left corner (the same anchoring
    the module compiler applies to its own drawing), because a keep-out and a page
    are absolute boxes and a page that floated would make them meaningless. Inside
    that anchor the variant chooses the grid shape: modules fill the rows
    left to right, top to bottom, in the flow order, and each row/column is as
    wide/tall as the widest/tallest frame in it.

    The gap the *layout* keeps is one lattice step wider than the gap the checker
    enforces, because every module's offset is snapped to the compilation lattice
    (a module's pin tips have to stay on one lattice for the cross-module wires to
    exist at all) and snapping can move two frames up to a step closer together.

    Two 057 additions, each a no-op when it does not apply (so a page with no page
    lock and no relocation is placed exactly as 056 placed it):

    * **page locks** (``locked``: module -> the origin its locks derive): a locked
      module sits at that origin, exactly (never snapped — the locked part has to
      land *on* the lock point), and the unlocked modules are arranged in the
      variant's grid shape around it: the locked frames are obstacles, kept a
      module gap away;
    * **relocation around keep-outs** (``budget.relocate_around_keepouts``): an
      arrangement whose anchored position lands on a keep-out is translated, as a
      rigid body, to the nearest lattice position where it does not
      (:func:`_relocate`). When there is none it stays where the anchor put it,
      and the gate refuses it with 056's own `page-keepout-conflict` — the
      refusal a caller reads is the same one, now meaning "nowhere on the page".
    """
    page = budget.page_box
    assert page is not None  # `_check_budget` refuses a page without one
    inner = (
        page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
        page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
    )
    relocate = budget.relocate_around_keepouts and bool(budget.keepouts)
    if not locked:
        offsets, frames, failure, need = _arrange(
            assembled, variant.order, variant.columns, variant.rung, budget
        )
        if failure is None and relocate:
            moved = _relocate(offsets, frames, list(budget.keepouts), inner, budget.grid)
            if moved is not None:
                offsets, frames = moved
        return offsets, frames, failure, need, ""

    by_id = {item.module.id: item for item in assembled}
    offsets = {}
    frames = {}
    for name in sorted(locked):
        origin, _locks = locked[name]
        frame = by_id[name].frame
        offsets[name] = origin
        frames[name] = (
            frame[0] + origin[0], frame[1] + origin[1],
            frame[2] + origin[0], frame[3] + origin[1],
        )
    failure = _locked_frame_failure(frames, locked, inner, budget)
    if failure is not None:
        return offsets, frames, failure, None, KIND_PAGE_LOCK_CONFLICT

    free = [item for item in assembled if item.module.id not in locked]
    if free:
        order = tuple(name for name in variant.order if name not in locked)
        free_offsets, free_frames, failure, need = _arrange(
            free, order, min(variant.columns, len(order)), variant.rung, budget
        )
        if failure is not None:
            return offsets, frames, failure, need, ""
        walls = [
            _grow(box, budget.module_gap + budget.grid)
            for _name, box in sorted(frames.items())
        ]
        obstacles = walls + (list(budget.keepouts) if relocate else [])
        moved = _relocate(free_offsets, free_frames, obstacles, inner, budget.grid)
        if moved is None:
            names = sorted({
                name for name, box in frames.items()
                for placed in free_frames.values()
                if _overlaps(_grow(box, budget.module_gap), placed)
            }) or sorted(frames)
            return offsets, frames, _lock_failure(
                [lock for name in names for lock in locked[name][1]],
                (
                    f"{variant.label}: the unlocked module(s) "
                    + ", ".join(sorted(free_frames))
                    + " find no position on the page that keeps a "
                    f"{budget.module_gap:g}-unit gap from the locked module(s) "
                    + ", ".join(names)
                    + (" and stays clear of the keep-outs" if relocate else "")
                    + " — the locks leave no room for the rest of the page"
                ),
                "move the lock point so the locked module leaves room for the "
                "others, state a larger page, or lock the other modules too",
            ), None, KIND_PAGE_LOCK_CONFLICT
        free_offsets, free_frames = moved
        offsets.update(free_offsets)
        frames.update(free_frames)
    occupied = _union(frames.values())
    need = (
        occupied[2] - occupied[0] + 2 * PAGE_MARGIN,
        occupied[3] - occupied[1] + 2 * PAGE_MARGIN,
    )
    return offsets, frames, None, need, ""


def _arrange(
    assembled: Sequence[_Assembled],
    order: Sequence[str],
    columns_wanted: int,
    rung: float,
    budget: PageCompileBudget,
) -> tuple[
    dict[str, tuple[float, float]], dict[str, Box], GrammarFailure | None,
    tuple[float, float] | None,
]:
    """056's grid arrangement of `assembled` in `order`, anchored top-left.

    Split out of :func:`_place` unchanged, so the modules a page lock does not
    pin are arranged exactly the way every module was before 057.
    """
    columns = max(1, min(columns_wanted, len(order)))
    rows = math.ceil(len(order) / columns)
    gap = rung * budget.module_gap + budget.grid
    by_id = {item.module.id: item for item in assembled}
    widths: list[float] = []
    heights: list[float] = []
    for column in range(columns):
        members = [order[position] for position in range(len(order))
                   if position % columns == column]
        widths.append(max(
            by_id[name].frame[2] - by_id[name].frame[0] for name in members
        ))
    for row in range(rows):
        members = [order[position] for position in range(len(order))
                   if position // columns == row]
        heights.append(max(
            by_id[name].frame[3] - by_id[name].frame[1] for name in members
        ))
    page = budget.page_box
    assert page is not None  # `_check_budget` refuses a page without one
    left = page[0] + PAGE_MARGIN
    top = page[3] - PAGE_MARGIN
    offsets: dict[str, tuple[float, float]] = {}
    frames: dict[str, Box] = {}
    for position, name in enumerate(order):
        row, column = divmod(position, columns)
        slot_left = left + sum(widths[:column]) + gap * column
        slot_top = top - sum(heights[:row]) - gap * row
        frame = by_id[name].frame
        dx = _snap(slot_left - frame[0], budget.grid)
        dy = _snap(slot_top - frame[3], budget.grid)
        offsets[name] = (dx, dy)
        frames[name] = (
            frame[0] + dx, frame[1] + dy, frame[2] + dx, frame[3] + dy,
        )
    inner = (
        page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
        page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
    )
    offsets, frames = _pull_inside(offsets, frames, inner, budget.grid)
    occupied = _union(frames.values())
    need = (
        occupied[2] - occupied[0] + 2 * PAGE_MARGIN,
        occupied[3] - occupied[1] + 2 * PAGE_MARGIN,
    )
    if (
        occupied[0] < inner[0] - 1e-6 or occupied[1] < inner[1] - 1e-6
        or occupied[2] > inner[2] + 1e-6 or occupied[3] > inner[3] + 1e-6
    ):
        return offsets, frames, GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject="page",
            detail=(
                f"the arrangement of {len(order)} module(s) in {columns} column(s) "
                f"occupies {occupied[2] - occupied[0]:g} x "
                f"{occupied[3] - occupied[1]:g} canvas units, and the stated page "
                f"is {page[2] - page[0]:g} x {page[3] - page[1]:g} with a "
                f"{PAGE_MARGIN:g}-unit margin on each side — the modules are rigid "
                "bodies and the page is not squeezed: no text is shrunk and no gap "
                "is narrowed to make it fit"
            ),
            action=(
                f"enlarge the page to at least {need[0]:g} x {need[1]:g} canvas "
                "units, or move the keep-out that takes the room, or split the page"
            ),
        ), need
    return offsets, frames, None, need


def _lock_origins(
    ctx: _Context, variant: _Variant, sources: Mapping[str, LayoutPlan]
) -> tuple[
    dict[str, tuple[tuple[float, float], tuple[UserLock, ...]]], GrammarFailure | None
]:
    """``module -> (origin, locks)`` for every module a page lock pins (057 sec.3).

    For this variant's generation the module's own drawing puts the locked part
    at L (module-local); the page puts the module at ``P − L``, so the part lands
    on the lock point P in every candidate — different generations, different
    origins, which is the lock doing its job (it constrains the part, not the
    frame). Two locks in one module that derive two origins cannot both hold in
    this generation: that is a contradiction, named with both locks.
    """
    owner: dict[str, str] = {}
    for module in ctx.modules:
        for part_id in module.parts:
            owner[part_id] = module.id
    derived: dict[str, list[tuple[tuple[float, float], UserLock]]] = {}
    for lock in ctx.presentation.page_locks():
        module_id = owner.get(lock.part_id)
        if module_id is None:
            continue
        part = sources[module_id].part(lock.part_id)
        if part is None:
            continue
        origin = (round(lock.x - part.x, 6), round(lock.y - part.y, 6))
        derived.setdefault(module_id, []).append((origin, lock))
    out: dict[str, tuple[tuple[float, float], tuple[UserLock, ...]]] = {}
    for module_id in sorted(derived):
        rows = derived[module_id]
        first_origin, first_lock = rows[0]
        for origin, lock in rows[1:]:
            if abs(origin[0] - first_origin[0]) > 1e-6 or abs(
                origin[1] - first_origin[1]
            ) > 1e-6:
                return {}, GrammarFailure(
                    category=FAILURE_PRESENTATION_POOR,
                    subject=f"{_lock_name(first_lock)} + {_lock_name(lock)}",
                    detail=(
                        f"{variant.label}: module {module_id!r} is pinned by two page "
                        f"locks that disagree — {first_lock.part_id} at "
                        f"{_point_text((first_lock.x, first_lock.y))} puts the "
                        f"module's origin at {_point_text(first_origin)}, "
                        f"{lock.part_id} at {_point_text((lock.x, lock.y))} puts it "
                        f"at {_point_text(origin)}: the module's own drawing keeps "
                        "the two parts at a distance the two lock points do not have"
                    ),
                    action=(
                        "keep one of the two page locks, or move a lock point so "
                        "the two agree with the module's drawing (or lock the "
                        "module's inner arrangement with module locks too)"
                    ),
                )
        out[module_id] = (first_origin, tuple(lock for _origin, lock in rows))
    return out, None


def _locked_frame_failure(
    frames: Mapping[str, Box],
    locked: Mapping[str, tuple[tuple[float, float], tuple[UserLock, ...]]],
    inner: Box,
    budget: PageCompileBudget,
) -> GrammarFailure | None:
    """Can the locked frames stand where their locks put them? (057 sec.3)

    Three ways they cannot, each naming the lock(s) that caused it — the lock
    takes part in the ranking with no privilege, so a candidate it makes illegal
    is refused rather than bent: a frame off the page, a frame on a keep-out,
    two locked frames closer than the module gap.
    """
    for name in sorted(frames):
        box = frames[name]
        locks = locked[name][1]
        if (
            box[0] < inner[0] - 1e-6 or box[1] < inner[1] - 1e-6
            or box[2] > inner[2] + 1e-6 or box[3] > inner[3] + 1e-6
        ):
            return _lock_failure(
                list(locks),
                (
                    f"the page lock(s) put module {name!r}'s frame at "
                    f"{_box_text(box)}, which leaves the page's usable area "
                    f"{_box_text(inner)} (a {PAGE_MARGIN:g}-unit margin inside the "
                    "sheet) — the module is a rigid body and is not cut to fit"
                ),
                "move the lock point further inside the page, or state a larger page",
            )
        for index, keep in enumerate(budget.keepouts):
            if _overlaps(box, keep):
                return _lock_failure(
                    list(locks),
                    (
                        f"the page lock(s) put module {name!r}'s frame "
                        f"{_box_text(box)} on keepouts[{index}] {_box_text(keep)} — "
                        "a reserved region and a module cannot share the canvas"
                    ),
                    "move the lock point off the keep-out, or move the keep-out",
                )
    names = sorted(frames)
    for position, left in enumerate(names):
        for right in names[position + 1:]:
            if _overlaps(_grow(frames[left], budget.module_gap), frames[right]):
                return _lock_failure(
                    list(locked[left][1]) + list(locked[right][1]),
                    (
                        f"the page locks put module {left!r} at "
                        f"{_box_text(frames[left])} and module {right!r} at "
                        f"{_box_text(frames[right])} — closer than the "
                        f"{budget.module_gap:g}-unit module gap (or on top of each "
                        "other)"
                    ),
                    "move one of the lock points so the two frames keep the module gap",
                )
    return None


def _lock_failure(locks: Sequence[UserLock], detail: str, action: str) -> GrammarFailure:
    names = sorted({_lock_name(lock) for lock in locks})
    return GrammarFailure(
        category=FAILURE_PRESENTATION_POOR,
        subject=" + ".join(names),
        detail=detail,
        action=action,
    )


def _relocate(
    offsets: Mapping[str, tuple[float, float]],
    frames: Mapping[str, Box],
    obstacles: Sequence[Box],
    inner: Box,
    grid: float,
) -> tuple[dict[str, tuple[float, float]], dict[str, Box]] | None:
    """The nearest lattice translation that takes the frames off every obstacle.

    ``None`` when there is none inside the page; the frames unchanged when they
    were clear already (so an arrangement that fits is left exactly where it was).
    The group moves as one rigid body — a gap, a frame or a text size never
    changes — and the candidate translations are the ones that put the group's
    edge flush against an obstacle's edge (or leave it where it is, or push it to
    the page's own edge), each snapped *away* from the obstacle onto the lattice:
    those are the positions a rigid box can come to rest at. Ties are broken by
    the smallest displacement, then the smallest vertical move, then left before
    right, so two runs pick the same.
    """
    boxes = list(obstacles)
    if not _collides(list(frames.values()), boxes):
        return dict(offsets), dict(frames)
    union = _union(frames.values())
    low_x, high_x = inner[0] - union[0], inner[2] - union[2]
    low_y, high_y = inner[1] - union[1], inner[3] - union[3]
    xs = {0.0}
    ys = {0.0}
    for box in boxes:
        xs.add(math.ceil((box[2] - union[0]) / grid - 1e-9) * grid)
        xs.add(math.floor((box[0] - union[2]) / grid + 1e-9) * grid)
        ys.add(math.ceil((box[3] - union[1]) / grid - 1e-9) * grid)
        ys.add(math.floor((box[1] - union[3]) / grid + 1e-9) * grid)
    xs.add(math.ceil(low_x / grid - 1e-9) * grid)
    xs.add(math.floor(high_x / grid + 1e-9) * grid)
    ys.add(math.ceil(low_y / grid - 1e-9) * grid)
    ys.add(math.floor(high_y / grid + 1e-9) * grid)
    shifts = sorted(
        (
            (dx, dy) for dx in xs for dy in ys
            if low_x - 1e-6 <= dx <= high_x + 1e-6
            and low_y - 1e-6 <= dy <= high_y + 1e-6
        ),
        key=lambda item: (abs(item[0]) + abs(item[1]), abs(item[1]), item[0], item[1]),
    )
    placed = list(frames.items())
    for dx, dy in shifts:
        moved = [
            (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
            for _name, box in placed
        ]
        if _collides(moved, boxes):
            continue
        return (
            {name: (offset[0] + dx, offset[1] + dy) for name, offset in offsets.items()},
            {name: box for (name, _old), box in zip(placed, moved)},
        )
    return None


def _collides(frames: Sequence[Box], obstacles: Sequence[Box]) -> bool:
    """Does any frame share area with any obstacle? (the keep-out rule's own test)"""
    if not frames:
        return False
    union = _union(frames)
    for box in obstacles:
        if not _overlaps(union, box):
            continue
        if any(_overlaps(frame, box) for frame in frames):
            return True
    return False


def _box_text(box: Box) -> str:
    return f"({box[0]:g}, {box[1]:g})–({box[2]:g}, {box[3]:g})"


def _pull_inside(
    offsets: dict[str, tuple[float, float]],
    frames: dict[str, Box],
    inner: Box,
    grid: float,
) -> tuple[dict[str, tuple[float, float]], dict[str, Box]]:
    """Bring an arrangement that snapping pushed out back inside, as a rigid body.

    Every module's offset is snapped to the compilation lattice (its pin tips have
    to stay on one lattice), so an arrangement anchored exactly at the page's
    margin can end up a lattice step outside it. The fix is a translation of the
    whole arrangement — never a change to a gap, a frame or a text size — and it is
    applied only when the arrangement is outside; an arrangement that fits is left
    exactly where the anchoring put it.
    """
    occupied = _union(frames.values())
    dx = 0.0
    dy = 0.0
    if occupied[2] > inner[2] + 1e-6:
        dx = -math.ceil((occupied[2] - inner[2]) / grid) * grid
    elif occupied[0] < inner[0] - 1e-6:
        dx = math.ceil((inner[0] - occupied[0]) / grid) * grid
    if occupied[3] > inner[3] + 1e-6:
        dy = -math.ceil((occupied[3] - inner[3]) / grid) * grid
    elif occupied[1] < inner[1] - 1e-6:
        dy = math.ceil((inner[1] - occupied[1]) / grid) * grid
    if dx == 0.0 and dy == 0.0:
        return offsets, frames
    moved = {
        name: (offset[0] + dx, offset[1] + dy) for name, offset in offsets.items()
    }
    shifted = {
        name: (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
        for name, box in frames.items()
    }
    return moved, shifted


# --------------------------------------------------------- stage 4d: the merge


@dataclass
class _Drawn:
    """The merged page drawing, in *page* coordinates.

    One object for the four lists the page places plus the wire list the page is
    about to add, because everything downstream — the obstacle set a wire is
    routed against, the ports, the plan — has to be in the same coordinate space.
    Mixing a module-local body box into a page-coordinate search is exactly the
    defect that lets a wire cross a part: it was written once and the checker
    caught it, which is the reason the drawing is built before anything reads it.
    """

    parts: list[LayoutPart] = field(default_factory=list)
    segments: list[LayoutSegment] = field(default_factory=list)
    labels: list[LayoutLabel] = field(default_factory=list)
    symbols: list[LayoutPowerSymbol] = field(default_factory=list)
    texts: list[LayoutText] = field(default_factory=list)
    ports: dict[str, list[PagePort]] = field(default_factory=dict)


def _merge(
    by_id: Mapping[str, _Assembled],
    order: Sequence[str],
    offsets: Mapping[str, tuple[float, float]],
) -> _Drawn:
    """Translate every module's drawing onto its slot and concatenate.

    Deterministic in everything: the module order is the placement order, each
    module's own objects keep the module compiler's order, and the page's ports
    are re-stated in page coordinates.
    """
    drawn = _Drawn()
    for name in order:
        item = by_id[name]
        dx, dy = offsets[name]
        for part in item.plan.parts:
            drawn.parts.append(LayoutPart(
                part_id=part.part_id, reference=part.reference,
                symbol_ref=part.symbol_ref, symbol_hash=part.symbol_hash,
                x=part.x + dx, y=part.y + dy, rotation=part.rotation,
                mirror=part.mirror,
            ))
        for segment in item.plan.segments:
            drawn.segments.append(LayoutSegment(
                net=segment.net,
                points=[(x + dx, y + dy) for x, y in segment.points],
            ))
        for label in item.plan.labels:
            drawn.labels.append(LayoutLabel(
                net=label.net, text=label.text,
                bbox=(label.bbox[0] + dx, label.bbox[1] + dy,
                      label.bbox[2] + dx, label.bbox[3] + dy),
                x=label.x + dx, y=label.y + dy, rotation=label.rotation,
            ))
        for symbol in item.plan.power_symbols:
            drawn.symbols.append(LayoutPowerSymbol(
                symbol_ref=symbol.symbol_ref, symbol_hash=symbol.symbol_hash,
                net=symbol.net, x=symbol.x + dx, y=symbol.y + dy,
                rotation=symbol.rotation,
            ))
        for text in item.plan.texts:
            drawn.texts.append(LayoutText(
                kind=text.kind, text=text.text,
                bbox=(text.bbox[0] + dx, text.bbox[1] + dy,
                      text.bbox[2] + dx, text.bbox[3] + dy),
                part_id=text.part_id,
                x=None if text.x is None else text.x + dx,
                y=None if text.y is None else text.y + dy,
                rotation=text.rotation,
            ))
        drawn.ports[name] = [
            PagePort(
                module=port.module, net=port.net, kind=port.kind,
                x=port.x + dx, y=port.y + dy, partner=port.partner,
            )
            for port in item.ports
        ]
    return drawn


# ------------------------------------------------- stage 4e: cross-module wires


def _wire_shared_nets(
    ctx: _Context,
    variant: _Variant,
    index: Mapping[str, int],
    by_id: Mapping[str, _Assembled],
    drawn: _Drawn,
    frames: Mapping[str, Box],
) -> _Drawn | GrammarFailure:
    """Draw every wire the page decided a main-path edge needs, or say why not.

    The ports are the whole geometry problem: a wire runs from one module's port
    (a pin tip of the shared net, inside that module) to the other's, and it may
    not run through any *other* module's frame, any text box, any foreign body or
    any keep-out. Everything else the page draws is a name, so a wire that cannot
    be routed is a main-path edge that cannot be honoured — `presentation-poor`,
    named, never a silent downgrade to a label.
    """
    out = list(drawn.segments)
    for net_id in sorted(ctx.nets_by_module):
        modules = ctx.nets_by_module[net_id]
        style, reason = _net_style(ctx, variant, net_id, index)
        if style != PAGE_PORT_WIRE:
            continue
        assert len(modules) == 2
        ends = {
            name: next(
                (port for port in drawn.ports[name] if port.net == net_id), None
            )
            for name in modules
        }
        if any(port is None for port in ends.values()):
            return GrammarFailure(
                category=FAILURE_LAYOUT_UNSAT,
                subject=net_id,
                detail=(
                    f"net {net_id!r} is a main-path wire but one of "
                    f"{modules[0]} / {modules[1]} has no port for it"
                ),
                action="report this run: the page's own port table is incomplete",
            )
        start = (ends[modules[0]].x, ends[modules[0]].y)
        end = (ends[modules[1]].x, ends[modules[1]].y)
        drawn_segment, failure = _route(
            ctx, net_id, start, end, by_id, frames, out, reason,
            drawn.parts, drawn.labels, drawn.symbols, drawn.texts,
        )
        if failure is not None:
            return failure
        assert drawn_segment is not None
        out.append(drawn_segment)
    drawn.segments = out
    return drawn


def _route(
    ctx: _Context,
    net_id: str,
    start: tuple[float, float],
    end: tuple[float, float],
    by_id: Mapping[str, _Assembled],
    frames: Mapping[str, Box],
    existing: Sequence[LayoutSegment],
    reason: str,
    parts: Sequence[LayoutPart],
    labels: Sequence[LayoutLabel],
    symbols: Sequence[LayoutPowerSymbol],
    texts: Sequence[LayoutText],
) -> tuple[LayoutSegment | None, GrammarFailure | None]:
    """One orthogonal wire between two ports, around everything in the way.

    The search is the module compiler's own (`drawcompiler.lattice_router`): the
    same lattice, the same obstacle rules, the same one-bend shortcut first. The
    obstacles are the page's, in page coordinates — every module frame except the
    two this wire joins, every text box, every foreign part body, the page's
    keep-outs, the foreign pin tips and names — plus the foreign wires, so a page
    wire cannot land on another net's pin, name or wire vertex.
    """
    page = ctx.budget.page_box
    assert page is not None
    grid = ctx.budget.grid
    residue = _lattice_residue([start, end], grid)
    if residue is None:
        return None, GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject=net_id,
            detail=(
                f"the two ends of the main-path connection for net {net_id!r} "
                f"({_point_text(start)} and {_point_text(end)}) are not on one "
                f"compilation lattice of {grid:g} units, so no grid search can "
                "reach both"
            ),
            action=(
                "move the lock that put one module's pins off the page's lattice, "
                "or lower the page budget's grid to a divisor of the coordinates "
                "involved"
            ),
        )
    joined = {_frame_of(start, frames), _frame_of(end, frames)}
    corridor = _corridor(start, end, frames, joined, page)
    boxes: list[Box] = [
        box for name, box in sorted(frames.items()) if name not in joined
    ]
    boxes.extend(text.bbox for text in texts)
    boxes.extend(_foreign_bodies(parts, ctx.book, start, end))
    boxes.extend(ctx.budget.keepouts)
    # Only the obstacles the search can reach: an obstacle outside the corridor is
    # never stepped into, and the per-node cost of this search is the number of
    # boxes it scans (a page with three modules has tens of them).
    boxes = [box for box in boxes if _overlaps(box, corridor)]
    blocked = _foreign_anchors(ctx, parts, labels, symbols, net_id)
    # A foreign pin, name or flag is a wall *and* the space around it is one: the
    # lattice search rejects a step into a walled node, but a step that passes
    # between two nodes would slip through a point obstacle — and a wire over a
    # foreign pin tip is a connection the editor makes, i.e. the short 053 sec.2
    # refuses. A box narrower than one lattice step closes that.
    boxes.extend(
        (point[0] - BLOCKED_POINT_RADIUS, point[1] - BLOCKED_POINT_RADIUS,
         point[0] + BLOCKED_POINT_RADIUS, point[1] + BLOCKED_POINT_RADIUS)
        for point in sorted(blocked)
        if corridor[0] <= point[0] <= corridor[2]
        and corridor[1] <= point[1] <= corridor[3]
    )
    router = _PageRouter(
        grid=grid,
        residue=residue,
        boxes=boxes,
        bounds=corridor,
    )
    router.blocked = set(blocked)
    # Only the foreign wires the corridor holds: a step between two lattice nodes
    # inside the corridor can only run along, turn on or cross a segment that
    # reaches the corridor, so the rest is dead weight for every node's scan
    # (the same filtering the obstacle boxes get above — 057 sec.7.2).
    router.edges = [
        (item.points[index], item.points[index + 1])
        for item in existing if item.net != net_id
        for index in range(len(item.points) - 1)
        if _touches(_bounds(item.points[index:index + 2]), corridor)
    ]
    elbow = drawcompiler.one_bend_route(router, start, end, blocked)
    points = elbow
    if points is None:
        path = router.route(start, end)
        if path is None:
            return None, GrammarFailure(
                category=FAILURE_PRESENTATION_POOR,
                subject=(
                    f"presentationSpec.flow[{_edge_label(ctx, net_id)}]"
                ),
                detail=(
                    f"the main-path edge for net {net_id!r} ({reason}) could not be "
                    "routed: the corridor between the two modules on this page is "
                    "closed by a module frame, a text box, a body, a keep-out or a "
                    "foreign connection, and the edge is not downgraded to a name"
                ),
                action=(
                    "widen the module gap (a larger budget gap ladder rung), move "
                    "the keep-out that closes the corridor, place the two modules "
                    "adjacent in the flow order, or drop the mainPath mark if a "
                    "label is acceptable here"
                ),
            )
        points = drawcompiler.compress_path(path)
    assert points is not None
    # The two ends are the ports, exactly: a wire that stopped a lattice step
    # short of the pin tip would be a wire end in mid-air and a net the editor
    # never joins (the checker's `dangling-wire-end` and the merged netlist both
    # say so).
    points = [start, *points[1:-1], end]
    del by_id
    return LayoutSegment(net=net_id, points=points), None


class _PageRouter(drawcompiler.lattice_router):
    """The module compiler's lattice search, with its per-node answers remembered.

    057 sec.7.2 (the 10–14 s/variant hot spot): profiling scene 7's shape put the
    whole cost in the search's per-step questions — "is this node a wall", "is
    this step free", "is this node inside a foreign wire" — each of which scans
    every obstacle box and every foreign edge, and each of which the Dijkstra asks
    again for every arrival direction of the same node. The answers depend only
    on the node (or the ordered pair of nodes) and on the furniture, which does
    not change once the search starts, so they are remembered. **The rules are the
    parent's own** (this class only caches their answers): the search visits the
    same nodes in the same order and returns the same path, which is why the
    module compiler's router is untouched and the page's wires are unchanged.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._walls: dict[tuple[int, int], bool] = {}
        self._steps: dict[tuple[tuple[int, int], tuple[int, int]], bool] = {}
        self._crossings: dict[tuple[int, int], tuple[int, int] | None] = {}

    def _wall(self, node: tuple[int, int]) -> bool:
        known = self._walls.get(node)
        if known is None:
            known = self._walls[node] = super()._wall(node)
        return known

    def _step_free(self, node: tuple[int, int], other: tuple[int, int]) -> bool:
        key = (node, other)
        known = self._steps.get(key)
        if known is None:
            known = self._steps[key] = super()._step_free(node, other)
        return known

    def _crossing(self, node: tuple[int, int]) -> tuple[int, int] | None:
        if node in self._crossings:
            return self._crossings[node]
        found = self._crossings[node] = super()._crossing(node)
        return found


def _touches(left: Box, right: Box) -> bool:
    """Do two boxes share a point (edges included)? A segment is a thin box."""
    return (
        left[0] <= right[2] + 1e-6 and right[0] <= left[2] + 1e-6
        and left[1] <= right[3] + 1e-6 and right[1] <= left[3] + 1e-6
    )


def _corridor(
    start: tuple[float, float],
    end: tuple[float, float],
    frames: Mapping[str, Box],
    joined: set[str],
    page: Box,
) -> Box:
    """Where a page wire's search may look: around the two modules it joins.

    The page's own version of the module compiler's search corridor. It is not the
    whole sheet: a filter that had to consider every lattice node of an A4 page
    spends its time proving that a route does not exist, and a route between two
    modules stays in their neighbourhood. The corridor is their two frames grown by
    :data:`PAGE_SEARCH_MARGIN` and clipped to the page's inner box, so a wire can
    still detour around a keep-out that sits between the modules — and a wire that
    would have to leave the neighbourhood is one the page would rather refuse (056
    sec.3's "the detour obligation is on the wire", read with 053's corridor).
    """
    boxes = [box for name, box in sorted(frames.items()) if name in joined]
    if not boxes:
        boxes = [_bounds([start, end])]
    grown = _grow(_union(boxes), PAGE_SEARCH_MARGIN)
    inner = (
        page[0] + PAGE_MARGIN, page[1] + PAGE_MARGIN,
        page[2] - PAGE_MARGIN, page[3] - PAGE_MARGIN,
    )
    return (
        max(grown[0], inner[0]), max(grown[1], inner[1]),
        min(grown[2], inner[2]), min(grown[3], inner[3]),
    )


def _grow(box: Box, margin: float) -> Box:
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def _foreign_bodies(
    parts: Sequence[LayoutPart],
    book: Mapping[str, SymbolProfile],
    start: tuple[float, float],
    end: tuple[float, float],
) -> list[Box]:
    """The bodies a wire may not cross: every part's body but its own two ends'.

    The same rule `readability`'s `wire-through-body` applies ("a wire between its
    own two pins may enter its own body"), so the search and the checker agree
    about what a legal wire is — in *page* coordinates, which is where the wire is.
    """
    ends = {_round(start), _round(end)}
    out: list[Box] = []
    for part in parts:
        profile = book.get(part.symbol_ref)
        if profile is None or profile.body is None:
            continue
        tips = {_round(_posed_pin(profile, part, pin)) for pin in profile.pins}
        if ends & tips:
            continue
        body = _body_box(profile, part)
        if body is not None:
            out.append(body)
    return out


def _foreign_anchors(
    ctx: _Context,
    parts: Sequence[LayoutPart],
    labels: Sequence[LayoutLabel],
    symbols: Sequence[LayoutPowerSymbol],
    net_id: str,
) -> set[tuple[float, float]]:
    """Pin tips, label anchors and flag anchors that are **not** this net's.

    A wire vertex landing on one of these is a connection in the editor's model
    (053 sec.2's short), so they are walls to the search. Membership comes from the
    circuit — ``<partId>.<pin>`` on a net the spec declares — rather than from
    guessing at the drawing, so a pin the drawing leaves unnamed is still its own
    node's.
    """
    mine = set(ctx.circuit.net(net_id).members) if ctx.circuit.net(net_id) else set()
    blocked: set[tuple[float, float]] = set()
    for part in parts:
        profile = ctx.book.get(part.symbol_ref)
        if profile is None:
            continue
        for pin in profile.pins:
            if f"{part.part_id}.{pin.number}" in mine:
                continue
            blocked.add(_round(_posed_pin(profile, part, pin)))
    for label in labels:
        if label.net != net_id:
            blocked.add(_round((label.x, label.y)))
    for symbol in symbols:
        if symbol.net != net_id:
            blocked.add(_round((symbol.x, symbol.y)))
    return blocked


# -------------------------------------------------------- stage 5: the gate


def _gate(
    ctx: _Context,
    variant: _Variant,
    page: PageLayoutPlan,
    assembled: Sequence[_Assembled],
    offsets: Mapping[str, tuple[float, float]],
) -> tuple[PageLayoutPlan | None, GrammarFailure | None, list[str], None, str]:
    """Both checkers, in the order that gives the most useful refusal first.

    The page domain runs first because two of its findings have a *nameable* cause
    a caller can act on (a keep-out on a module, a main-path edge that cannot be a
    wire); the nine then judge the merged drawing, where a failure is this
    compiler's own geometry problem. A candidate is a page both layers passed.
    """
    keepouts = list(ctx.budget.keepouts)
    page_check = readability.check_page(
        page,
        ctx.circuit,
        ctx.presentation,
        ctx.book,
        keepouts=keepouts,
        module_gap=ctx.budget.module_gap,
        high_fanout=ctx.budget.module_budget.high_fanout,
    )
    if page_check.hard_violations:
        return None, _page_failure(variant, page_check), [
            item.render() for item in page_check.hard_violations
        ], None, page_check.hard_violations[0].kind
    view = _page_presentation_view(ctx, offsets, page.plan)
    drawing_check = readability.check(
        page.plan,
        ctx.circuit,
        view,
        ctx.book,
        page_box=ctx.budget.page_box,
        keepouts=keepouts,
        grid=ctx.budget.grid,
    )
    if drawing_check.hard_violations:
        return None, GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject="page",
            detail=(
                f"{variant.label}: the independent readability checker refused "
                f"{len(drawing_check.hard_violations)} hard violation(s) on the "
                "merged page drawing — "
                + drawing_check.hard_violations[0].render()
            ),
            action=(
                "this is a page-compiler geometry problem, not a spec problem: the "
                "page box, the gap ladder or the module set has to change before "
                "this arrangement can be drawn"
            ),
        ), [item.render() for item in drawing_check.hard_violations], None, ""
    findings = _module_findings(ctx, variant)
    page.plan.evidence = LayoutEvidence(
        checker=readability.CHECKER_NAME,
        hard_violations=[],
        grammar_findings=findings,
        soft_metrics=dict(drawing_check.soft_metrics),
        soft_reasons={
            key: " | ".join(value)
            for key, value in drawing_check.soft_reasons.items()
        },
        notes=[
            f"the merged page drawing, compiled by {PAGE_COMPILER_NAME}; every "
            "module was drawn by the single-module compiler and then translated",
            f"checked by {readability.CHECKER_NAME} on the merged drawing and by "
            f"{readability.PAGE_CHECKER_NAME} on the page",
            "the grammar findings are the modules' own, each prefixed with the "
            "module it belongs to: a page has no single grammar to bind",
        ],
    )
    page.page_evidence = LayoutEvidence(
        checker=readability.PAGE_CHECKER_NAME,
        hard_violations=[],
        grammar_findings=[],
        soft_metrics=dict(page_check.soft_metrics),
        soft_reasons={
            key: " | ".join(value)
            for key, value in page_check.soft_reasons.items()
        },
        notes=[
            f"page domain checked by {readability.PAGE_CHECKER_NAME}: the eight "
            "page constraints, against the frames the page states",
        ],
    )
    page.notes.append(
        f"page of {len(assembled)} module(s) in "
        f"{max(1, min(variant.columns, len(variant.order)))} column(s): "
        + ", ".join(f"{item.module.id}@{offsets[item.module.id][0]:g}"
                    for item in assembled)
    )
    return page, None, [], None, ""


def _module_findings(ctx: _Context, variant: _Variant) -> list[str]:
    """Every module's own grammar findings, prefixed with the module they belong to.

    The page has no single grammar to bind (a page mixes an LDO with a divider), so
    the expression layer of the ranking reads the findings the *modules* made about
    their own drawings — which is also why a page-level grammar finding would be
    the wrong thing to invent.
    """
    out: list[str] = []
    for module in ctx.modules:
        compiled = ctx.results.get(module.id)
        if compiled is None or not compiled.ok:
            continue
        candidates = compiled.candidates
        plan = candidates[min(variant.generation, len(candidates) - 1)]
        out.extend(
            f"modules[{module.id}]: {finding}"
            for finding in plan.evidence.grammar_findings
        )
    return out


def _page_failure(variant: _Variant, checked: readability.CheckResult) -> GrammarFailure:
    """Map a page-domain violation to one of 053 sec.4's four categories.

    Two of the eight kinds name something the *caller* can change, and they are
    reported as `presentation-poor` with an action: a keep-out sitting on a module,
    and a main-path edge that could not be a wire. The rest (frames overlapping,
    a wire through a frame, one net stated two ways) are this compiler's own
    geometry problems on a page whose input is not contradictory — `layout-unsat`,
    and the action says so.
    """
    first = checked.hard_violations[0]
    rendered = [item.render() for item in checked.hard_violations]
    if first.kind == readability.KIND_PAGE_KEEPOUT_CONFLICT:
        return GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=first.objects[0],
            detail=(
                f"{variant.label}: {first.evidence}. Every arrangement the page "
                "tried puts a module frame there, so there is no placement left to "
                "choose"
            ),
            action=(
                "move the keep-out off the module's positions (make it smaller, or "
                "move it to the margin the modules are not using), state a larger "
                "page, or ungroup the modules so the crowded part is not a rigid "
                "body — the page does not shrink a module's drawing to get out of "
                "the way"
            ),
        )
    if first.kind == readability.KIND_MAIN_PATH_EDGE_NOT_WIRED:
        return GrammarFailure(
            category=FAILURE_PRESENTATION_POOR,
            subject=first.objects[0],
            detail=f"{variant.label}: {first.evidence}",
            action=(
                "drop the mainPath mark for this edge (it is then a name, which the "
                "page states at both ends), place the two modules adjacent in the "
                "flow order, or give the two modules a net that may be wired — a "
                "main-path edge is never downgraded to a label quietly"
            ),
        )
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject="page",
        detail=f"{variant.label}: {first.evidence}",
        action=(
            "this is a page-compiler geometry problem on a consistent input, not a "
            "spec problem: report it, or change the page box, the module gap or the "
            "module set. The full page-domain report is: " + " | ".join(rendered[:3])
        ),
    )


def _page_presentation_view(
    ctx: _Context,
    offsets: Mapping[str, tuple[float, float]],
    merged: LayoutPlan | None = None,
) -> PresentationSpec:
    """The presentation as the *page* reads it: the locks translated with their modules.

    A lock inside a module is honoured inside that module (the module compile
    places the part exactly there, and the page translates the whole frame), so the
    page's version of the lock is the module-local one plus the module's own
    offset. Passing the untranslated locks to the nine would report every lock in
    the drawing as violated — the page would be measuring an engineer's coordinates
    against a frame that did not exist when they were written.

    A **page** lock (057 sec.3) is already in page coordinates and is passed as it
    is — the nine's own `user-lock-violated` then checks, independently of the
    placement that derived the origin, that the part really is on the lock point.
    It pins a position, so its rotation is read from the drawing (the pose is the
    module's, and a module lock on the same part still checks it).
    """
    owner: dict[str, str] = {}
    for module in ctx.modules:
        for part_id in module.parts:
            owner[part_id] = module.id
    locks: list[UserLock] = []
    for lock in ctx.presentation.user_locks:
        if lock.is_page:
            part = merged.part(lock.part_id) if merged is not None else None
            locks.append(UserLock(
                part_id=lock.part_id, x=lock.x, y=lock.y,
                rotation=part.rotation if part is not None else 0.0,
                scope=lock.scope,
            ))
            continue
        dx, dy = offsets.get(owner.get(lock.part_id, ""), (0.0, 0.0))
        locks.append(UserLock(
            part_id=lock.part_id, x=lock.x + dx, y=lock.y + dy,
            rotation=lock.rotation,
        ))
    return dataclasses.replace(ctx.presentation, user_locks=locks)


def _no_candidate_failures(result: PageCompileResult) -> list[GrammarFailure]:
    """Why no variant produced a page — every measured cause a caller can act on.

    A finite search that found nothing says so: the count of variants tried is
    always in the line. Two causes are reported together when both occurred,
    because they are two different things to change: a keep-out sitting on every
    arrangement (move it) and a page smaller than the smallest arrangement (enlarge
    the page). When neither applies, the first variant's own failure is the answer,
    and each one carries its measured numbers and an action.
    """
    with_failure = [item for item in result.rejected if item.failure is not None]
    tried = len(result.rejected)
    if not with_failure:
        return [GrammarFailure(
            category=FAILURE_LAYOUT_UNSAT,
            subject="page",
            detail=(
                f"{tried} variant(s) were built and none produced a page, and none "
                "recorded a reason (report this: a refusal without a reason is what "
                "053 sec.4 forbids)"
            ),
            action="report this run; the page compiler is expected to name its reason",
        )]
    out: list[GrammarFailure] = []
    named: dict[tuple[str, str], PageRejection] = {}
    for item in with_failure:
        if not item.kind:
            continue
        key = (item.kind, item.failure.subject if item.failure else "")
        named.setdefault(key, item)
    # The causes a caller can act on, most concrete first: a keep-out to move, a
    # main-path edge whose mark has to be dropped. Both are measured and named, and
    # reporting only one of them would send the caller back with half the answer.
    for kind in (
        # 057 sec.3: a lock that makes every candidate illegal is named first —
        # it is the input the author wrote to pin the page, so it is the first
        # thing to reconsider ("全部非法 → presentation-poor 点名锁").
        KIND_PAGE_LOCK_CONTRADICTION,
        KIND_PAGE_LOCK_CONFLICT,
        readability.KIND_PAGE_KEEPOUT_CONFLICT,
        readability.KIND_MAIN_PATH_EDGE_NOT_WIRED,
    ):
        for (found, _subject), item in sorted(named.items()):
            if found == kind:
                out.append(_counted(item, tried, "variant(s)"))
    needing = [item for item in with_failure if item.need is not None]
    if needing:
        best = min(needing, key=lambda item: (item.need[0] * item.need[1], item.need))
        assert best.failure is not None and best.need is not None
        out.append(GrammarFailure(
            category=best.failure.category,
            subject=best.failure.subject,
            detail=(
                f"{best.failure.detail} — {tried} arrangement(s) were built and "
                "refused inside the stated page, and the smallest of them needs "
                f"{best.need[0]:g} x {best.need[1]:g} canvas units (a finite search "
                "says 'not found inside the page', never 'no solution')"
            ),
            action=best.failure.action,
        ))
    if not out:
        out.append(_counted(with_failure[0], tried, "variant(s)"))
    return out


def _counted(item: PageRejection, tried: int, noun: str) -> GrammarFailure:
    assert item.failure is not None
    return GrammarFailure(
        category=item.failure.category,
        subject=item.failure.subject,
        detail=(
            f"{item.failure.detail} — {tried} {noun} were built and refused"
        ),
        action=item.failure.action,
    )


# ------------------------------------------------------------------ geometry


def _part_extent(profile: SymbolProfile, part: LayoutPart) -> Box:
    """A placed part's extent: its body and every pin tip (the compiler's rule)."""
    xs: list[float] = []
    ys: list[float] = []
    pose = SymbolPose(int(part.rotation), part.mirror)
    if profile.body is not None:
        x0, y0, x1, y1 = profile.body
        for corner in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            point = transform_point(
                corner[0], corner[1], rotation=pose.rotation, mirror=pose.mirror,
                ox=part.x, oy=part.y,
            )
            xs.append(point[0])
            ys.append(point[1])
    for pin in profile.pins:
        point = _posed_pin(profile, part, pin)
        xs.append(point[0])
        ys.append(point[1])
    if not xs:
        return (part.x, part.y, part.x, part.y)
    return (min(xs), min(ys), max(xs), max(ys))


def _body_box(profile: SymbolProfile, part: LayoutPart) -> Box | None:
    if profile.body is None:
        return None
    x0, y0, x1, y1 = profile.body
    corners = [
        transform_point(x, y, rotation=int(part.rotation), mirror=part.mirror,
                        ox=part.x, oy=part.y)
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _glyph_box(
    profile: SymbolProfile, rotation: float, origin: tuple[float, float]
) -> Box | None:
    """A flag's glyph box: the one box `drawcompiler.flag_box` reserves (060).

    A flag profile states its glyph *away from the pin*; the number in the plan
    is the rotation the editor is given. Deriving the box here from the plan's
    own rotation would put the page's keep-outs on the other side of the flag
    from the glyph the compiler reserved room for.
    """
    return flag_glyph_box(profile, rotation=rotation, anchor=origin)


def _posed_pin(profile: SymbolProfile, part: LayoutPart, pin: Any) -> tuple[float, float]:
    point = transform_point(
        pin.tip[0], pin.tip[1], rotation=int(part.rotation), mirror=part.mirror,
        ox=part.x, oy=part.y,
    )
    return _round(point)


def _pin_points(
    plan: LayoutPlan, book: Mapping[str, SymbolProfile]
) -> dict[str, tuple[float, float]]:
    """``"<partId>.<pin>" -> page (module-local) coordinates`` for every pin."""
    out: dict[str, tuple[float, float]] = {}
    for part in plan.parts:
        profile = book.get(part.symbol_ref)
        if profile is None:
            continue
        for pin in profile.pins:
            out[f"{part.part_id}.{pin.number}"] = _posed_pin(profile, part, pin)
    return out


def _port_point(
    members: Iterable[str],
    pins: Mapping[str, tuple[float, float]],
    direction: tuple[float, float],
) -> tuple[float, float] | None:
    """The member pin tip of this net that faces `direction` (056 sec.2's rule).

    "端口点 = 模块内该共享网已放置的引脚尖端或旗标点": the port is a point at
    which the module's own drawing *already carries the net as a conductor* — a
    pin tip of one of its members. The facing tip is chosen so the label or the
    wire leaves towards the module it talks to; ties break on the member name, so
    two runs pick the same one.

    A flag's own anchor is deliberately not a candidate here: a flag may sit a
    lead-wire's length away from its pin, and a port that has to survive the flag
    being re-stated (as a label, or as a whole wire) has to be a point the net's
    *wiring* still holds afterwards. The flag branch of :func:`_port` reads the
    anchors it keeps directly from the plan.

    The membership comes from the module-local circuit, so a pin the drawing leaves
    unnamed is still known to be (or not to be) this net's.
    """
    wanted = set(members)
    candidates = [
        (point[0], point[1], member)
        for member, point in pins.items()
        if member in wanted
    ]
    if not candidates:
        return None
    axis = 0 if direction[0] != 0 else 1
    sign = direction[0] if axis == 0 else direction[1]
    ranked = sorted(
        candidates, key=lambda item: (-sign * item[axis], item[2], item[0], item[1])
    )
    return _round((ranked[0][0], ranked[0][1]))


def _port_direction(
    position: int, columns: int, count: int, has_later_partner: bool
) -> tuple[float, float]:
    """Which way a module faces: towards the next module the reader reaches.

    The reading order is the placement order (left to right within a row, then the
    next row down), so a module's "onward" side is east while its row has room and
    south when the next module starts the following row. A net that only has
    partners *behind* it faces backwards instead, so its name sits on the side the
    connection comes from.
    """
    columns = max(1, min(columns, count))
    row, column = divmod(position, columns)
    has_next = position + 1 < count
    if not has_later_partner:
        return (-1.0, 0.0) if column == 0 and row > 0 else (0.0, 1.0)
    if has_next and column < columns - 1:
        return (1.0, 0.0)
    if has_next:
        return (0.0, -1.0)
    return (1.0, 0.0)


def _has_later_partner(
    ctx: _Context, net_id: str, module_id: str, index: Mapping[str, int]
) -> bool:
    position = index.get(module_id, 0)
    return any(
        index.get(name, -1) > position for name in ctx.nets_by_module[net_id]
    )


def _main_path_edges(ctx: _Context, pair: set[str]) -> list[FlowEdge]:
    return [
        edge for edge in ctx.presentation.flow
        if edge.main_path and {edge.from_module, edge.to_module} == pair
    ]


def _edge_label(ctx: _Context, net_id: str) -> str:
    """The flow edge a wired net belongs to, for a failure's object name."""
    pair = set(ctx.nets_by_module[net_id])
    edges = _main_path_edges(ctx, pair)
    if not edges:
        return f"{net_id}"
    return f"{edges[0].from_module}->{edges[0].to_module}"


def _is_bus(net: SpecNet | None, high_fanout: int) -> bool:
    """Is this net always expressed by name (053 sec.7)?"""
    if net is None:
        return False
    return net.cls in ("gnd", "power")


def _adjacent(left: int, right: int, columns: int, count: int) -> bool:
    """Are two modules side by side in the grid — east/west or north/south?"""
    columns = max(1, min(columns, count))
    left_row, left_column = divmod(left, columns)
    right_row, right_column = divmod(right, columns)
    return (
        left_row == right_row and abs(left_column - right_column) == 1
    ) or (
        left_column == right_column and abs(left_row - right_row) == 1
    )


def _frame_of(point: tuple[float, float], frames: Mapping[str, Box]) -> str:
    """The module whose frame holds this point (module-id order, "" if none)."""
    for name, box in sorted(frames.items()):
        if (
            box[0] - 1e-6 <= point[0] <= box[2] + 1e-6
            and box[1] - 1e-6 <= point[1] <= box[3] + 1e-6
        ):
            return name
    return ""


def _extreme_anchor(
    points: Sequence[tuple[float, float]], direction: tuple[float, float]
) -> tuple[float, float]:
    """The anchor furthest along `direction`, with a stable tie-break."""
    axis = 0 if direction[0] != 0 else 1
    sign = direction[0] if axis == 0 else direction[1]
    ranked = sorted(points, key=lambda item: (-sign * item[axis], item))
    return _round((ranked[0][0], ranked[0][1]))


def _label_box(
    net_id: str, point: tuple[float, float], preferred: tuple[float, float],
    occupied: Sequence[Box],
) -> Box:
    """Where a page-placed label's box goes: the anchor stays, the box finds room.

    The same rule the module compiler applies to its own labels (the anchor is the
    electrical fact and the box is typography, tried in four directions, with the
    preferred direction first), written here on the public font metrics because the
    page's avoidance list also holds boxes the module compiler never saw — the
    other ports of this page.
    """
    for direction in _directions(preferred):
        half_x = drawcompiler.text_width(net_id) / 2.0 + drawcompiler.TEXT_GAP
        half_y = drawcompiler.TEXT_SIZE / 2.0 + drawcompiler.TEXT_GAP
        offset = (
            (direction[0] * half_x, 0.0) if direction[0] != 0.0
            else (0.0, direction[1] * half_y)
        )
        candidate = drawcompiler.font_text_box(
            net_id, x=point[0] + offset[0], y=point[1] + offset[1]
        )
        if all(not _overlaps(candidate, box) for box in occupied):
            return candidate
    return drawcompiler.font_text_box(
        net_id, x=point[0], y=point[1] + drawcompiler.TEXT_SIZE / 2.0 + drawcompiler.TEXT_GAP
    )


def _directions(preferred: tuple[float, float]) -> list[tuple[float, float]]:
    """The preferred direction first, then the rest of the compass."""
    all_directions = [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
    return [preferred] + [item for item in all_directions if item != preferred]


def _lattice_residue(
    points: Sequence[tuple[float, float]], grid: float
) -> tuple[float, float] | None:
    """The lattice offset every point shares, or ``None`` when they disagree.

    The page's own copy of the module compiler's rule: two port points have to sit
    on one grid before any grid search can join them, and "they do not" is a
    measured refusal rather than a snapped wire.
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
            if any(abs(value + shift - base) <= 1e-6 for shift in (-grid, 0.0, grid)):
                continue
            return None
    return (residue[0] or 0.0, residue[1] or 0.0)


def _snap(value: float, grid: float) -> float:
    return round(value / grid) * grid


def _round(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 6), round(point[1], 6))


def _bounds(points: Sequence[tuple[float, float]]) -> Box:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _union(boxes: Iterable[Box]) -> Box:
    items = list(boxes)
    return (
        min(box[0] for box in items), min(box[1] for box in items),
        max(box[2] for box in items), max(box[3] for box in items),
    )


def _overlaps(left: Box, right: Box) -> bool:
    """Do two boxes share area? Strict, so touching edges are not an overlap."""
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > 1e-6
        and min(left[3], right[3]) - max(left[1], right[1]) > 1e-6
    )


def _point_text(point: tuple[float, float]) -> str:
    return f"({point[0]:g}, {point[1]:g})"
