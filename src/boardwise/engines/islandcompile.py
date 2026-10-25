"""One island's **independent** compile: a local picture, judged locally (538B).

`docs/drawing-archipelago-route.md` splits the archipelago work into a partition,
an assembly and a page.  This module is the smallest useful step before any of
them: it compiles **one declared island** as its own drawing, with its own local
gate, and says so.  It is the block-level counterpart of `drawcompiler.compile`,
not a second compiler:

* the projection is the existing one — `islandlayout.island_subgraph` (a single
  island) or `islandlayout.island_subgraphs` (a batch), so a net that reaches two
  islands is marked **crossing** here exactly as it is on the page;
* the layout is `islandlayout.layout_island` — the same local placer the island
  page calls per block — and the plan is `IslandBlock.plan(source=...)` with the
  **original whole document's** two hashes, so a local plan is not a second fact
  source with a second digest;
* the identity check is `archipelago.validate_archipelago_island_plan` (538A),
  which is the declared partition narrowed to this island;
* the gate is `readability.check(scope=ReadabilityScope(parts=…))` plus
  `drawcompiler.island_gate_violations` and `readability.soft_floor_violations`.
  The scope is what makes the *whole specification* judge a **local** picture
  without reporting the parts this island does not draw (538A measured 4 / 3
  false `required-pin-not-connected` findings on the real LDO split).

**What it does not do.**  It never calls `island_page`, `pack_islands` or the
whole-page compiler; it passes no `page_box`, no keep-outs and no grammar
checker; it places no second island and reserves no channel.  So a result that is
`ok` is that island's own reading — not a packed page, not an assembly, not a
landing or visual acceptance, and specifically **not** `draw compile ok=true`.

**A refusal carries no candidate.**  A failed island's result has ``block=None``
and ``plan=None``: a rejected local picture is recorded as a `GrammarFailure`
(053 §4's four categories, with the hard-kind dispatch
`drawcompiler.GATE_REFUSAL_KINDS` gives every other gate) and nothing else, so a
caller cannot adopt an evidence-`pass`-looking plan the island was refused for.
Missing facts — a part with no profile — are that shape too rather than a
`KeyError` escaping the placer.

**A raising stage refuses that island only.**  The pipeline has three stages,
and each one's own exceptions are shaped as *this island's* refusal instead of
ending a batch: the placer (`layout`), the plan and its scoped identity
(`plan/identity`), and the readability checker (`readability`).  Only the
exceptions those stages are named to raise are caught — `ValueError` (which
`ArchipelagoError` and `ReadabilityError` are) and the `KeyError` of a missing
lookup; a `TypeError` or a bug in this module still escapes, because a refusal
is a statement about the island, not a blanket for broken code.  The refusal's
detail names the island, the stage and the original exception, and its category
is read off that stage: a partition the plan does not carry is
`presentation-poor` (the category `drawcompiler` uses for the same check), a
missing lookup or an unreadable checker input is `facts-missing`, and a stage
that could not produce the picture at all is `layout-unsat`.  The whole
document's `validate_archipelago` stays **outside** this per-island handling: a
presentation that does not add up refuses the whole batch before any layout.

**No variant ladder.**  The same input compiles to the same picture and the same
evidence; there is nothing to retry here.  The explicit single-island recompile
(:func:`recompile_island`, 538C) is the one way to ask again, and it says so:
with an unchanged request it recompiles the **same** input (not a new variant);
with a new :class:`~boardwise.engines.islandlayout.IslandBudget` it changes that
one input and reuses the rest.  It recomputes only the named island, leaves every
other result object exactly as it was, and never retries on its own — a failure
recompiles to the same failure.  :class:`IslandCompileResult` keeps the frozen
:class:`IslandCompileRequest` of its original inputs and budget so that call needs
no parallel copy of them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Mapping

from ..core.archipelago import (
    ArchipelagoError,
    validate_archipelago,
    validate_archipelago_island_plan,
)
from ..core.circuitspec import CircuitSpec
from ..core.islands import cross_island_nets
from ..core.layoutplan import LayoutEvidence, LayoutPlan, LayoutSource
from ..core.presentationspec import PresentationSpec
from ..core.symbolprofile import SymbolProfile
from . import islandlayout, readability
from .grammar.base import (
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
    GrammarFailure,
)

__all__ = [
    "ISLAND_COMPILER_NAME",
    "IslandCompileRequest",
    "IslandCompileResult",
    "compile_island",
    "compile_islands",
    "recompile_island",
]

#: What an island compile's evidence is from — beside `readability.CHECKER_NAME`,
#: which stays the checker's own name rather than this module's.
ISLAND_COMPILER_NAME = "boardwise-island-compile/1"

#: The stages a raised failure is reported with.  Where the island stopped is
#: part of the refusal: before any plan existed (`layout`), with a plan whose
#: declared partition did not hold (`plan/identity`), or at the checker itself
#: (`readability`).  A reader (and 538C's recompile) needs the stage, not just
#: "it failed".
_STAGE_LAYOUT = "layout"
_STAGE_PLAN = "plan/identity"
_STAGE_READABILITY = "readability"


@dataclass(frozen=True)
class IslandCompileRequest:
    """The original input references plus their compile-time content fingerprint.

    Public through :class:`IslandCompileResult`: recompile need not keep a
    parallel copy.  The dataclass is frozen, but the circuit, presentation and
    profile mapping it references are not deep-copied or made immutable.  The
    fingerprint is what lets recompile disclose such a later mutation instead of
    falsely claiming that the input is unchanged.
    """

    circuit: CircuitSpec
    presentation: PresentationSpec
    island_id: str
    profiles: Mapping[str, SymbolProfile]
    budget: islandlayout.IslandBudget | None = None
    input_fingerprint: str | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True)
class IslandCompileResult:
    """One island's compile: a candidate when it passed, a refusal when it did not.

    The two shapes are exclusive and checked in :meth:`__post_init__`:

    * **accepted** — ``block``, ``plan`` and ``gate`` are all present and
      ``refusal is None``;
    * **refused** — ``block`` and ``plan`` are both ``None`` and ``refusal`` is a
      `GrammarFailure`.  ``gate`` may still be present: it is the reading the
      refusal was made from, kept as evidence, never as a candidate.

    :attr:`ok` is derived from that shape, not from ``gate.ok``: the gate's own
    ``ok`` is "no hard violation at all", while a delivered island may carry the
    host-printed rows the delivery policy tolerates
    (`drawcompiler.island_gate_violations`).
    """

    island_id: str
    block: islandlayout.IslandBlock | None = None
    plan: LayoutPlan | None = None
    gate: readability.CheckResult | None = None
    refusal: GrammarFailure | None = None
    #: The violations the island was delivered **with**, one per host-printed row.
    tolerated: tuple[readability.HardViolation, ...] = ()
    notes: tuple[str, ...] = ()
    #: Original input references, budget and content fingerprint for 538C/539.
    request: IslandCompileRequest | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if self.refusal is None:
            missing = [
                name
                for name in ("block", "plan", "gate")
                if getattr(self, name) is None
            ]
            if missing:
                raise ValueError(
                    f"island {self.island_id!r}: an accepted result must carry "
                    f"{', '.join(missing)} — ok=True is a whole result, and a "
                    "success missing its candidate is a claim nobody can read"
                )
            return
        if not isinstance(self.refusal, GrammarFailure):
            raise ValueError(
                f"island {self.island_id!r}: refusal must be a GrammarFailure, "
                f"got {type(self.refusal).__name__}"
            )
        for name in ("block", "plan"):
            if getattr(self, name) is not None:
                raise ValueError(
                    f"island {self.island_id!r}: a refused result carries no "
                    f"{name} — a candidate the island was refused for must not be "
                    "adoptable, and the refusal is the whole record"
                )

    @property
    def ok(self) -> bool:
        """This island's local reading passed — nothing about the page."""
        return self.refusal is None


# ------------------------------------------------------------------- the API


def compile_island(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    island_id: str,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: islandlayout.IslandBudget | None = None,
) -> IslandCompileResult:
    """Compile **one** declared island as its own drawing.

    The whole archipelago contract is checked first
    (:func:`boardwise.core.archipelago.validate_archipelago`), so a presentation
    that does not add up is refused before anything is laid out.  An ``island_id``
    the presentation does not declare is an input error
    (:class:`ArchipelagoError`), never checked against a guess.

    One island's picture uses the single-island projection **with the crossing
    set computed from the whole partition** (`cross_island_nets`): a batch and a
    single compile of the same island must not disagree about which nets cross.
    """
    return _compile(
        circuit,
        presentation,
        profiles,
        budget=budget,
        island_ids=(island_id,),
    )[0]


def compile_islands(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: islandlayout.IslandBudget | None = None,
) -> list[IslandCompileResult]:
    """Compile every declared island, in `effective_islands()` order.

    The order is the document's: it is what the partition says, not what a
    dictionary walk or a size sort would say.  One island's local failure does
    not stop the others — a result is per island — but the **whole** contract is
    still checked once before the first layout.
    """
    return _compile(
        circuit, presentation, profiles, budget=budget, island_ids=None
    )


def recompile_island(
    result: IslandCompileResult,
    *,
    budget: islandlayout.IslandBudget | None = None,
) -> IslandCompileResult:
    """Recompile **one** result's island from the inputs it was built with (538C).

    This is the local-rollback lever: after a batch, a caller may ask for one
    island again — its own circuit, presentation, island id and profiles, read
    off the result's frozen :attr:`IslandCompileResult.request` — and nothing
    else is recompiled.  There is no implicit retry, no loop and no whole-page
    recomputation, and the old result (and every other result) is left exactly
    as it was; the answer is a **new** result object.

    ``budget=None`` reuses ``request.budget``.  The request also carries the
    original content fingerprint: if the mutable circuit, presentation or profile
    mapping has since changed, the notes disclose that current content is being
    compiled instead of claiming an unchanged retry.  An explicitly supplied
    budget equal by value to the original is likewise unchanged; a different
    :class:`~boardwise.engines.islandlayout.IslandBudget` replaces that one input.

    A refused result recompiles to the **same** refusal (same category, detail
    and action) with no candidate: repeating a failure is not how it becomes a
    success.  The recompile's provenance goes to the result's ``notes``; the
    plan's ``LayoutEvidence`` is left untouched, so a successful recompile of the
    same input keeps the original evidence byte for byte.
    """
    if not isinstance(result, IslandCompileResult):
        raise TypeError(
            "recompile_island takes an IslandCompileResult — the original "
            "circuit, presentation, island id, profiles and budget live on its "
            f"request, got {type(result).__name__}"
        )
    request = result.request
    if request is None:
        raise ValueError(
            f"island {result.island_id!r}: recompile_island needs the result's "
            "request, which records the original circuit, presentation, island "
            "id, profiles and budget; this result carries none, so there is "
            "nothing to recompile from — compile it with compile_island/"
            "compile_islands first"
        )
    if budget is not None and not isinstance(budget, islandlayout.IslandBudget):
        raise TypeError(
            "budget must be an IslandBudget or None, got "
            f"{type(budget).__name__}"
        )
    original_effective_budget = (
        request.budget
        if request.budget is not None
        else islandlayout.IslandBudget()
    )
    # budget=None in the original request means the default IslandBudget, so an
    # explicitly supplied default is equal input too — not a manufactured change.
    budget_changed = budget is not None and budget != original_effective_budget
    effective = budget if budget_changed else request.budget
    fingerprint_known = request.input_fingerprint is not None
    references_changed = fingerprint_known and (
        request.input_fingerprint
        != _input_fingerprint(request.circuit, request.presentation, request.profiles)
    )
    fresh = compile_island(
        request.circuit,
        request.presentation,
        request.island_id,
        request.profiles,
        budget=effective,
    )
    if not budget_changed and fingerprint_known and not references_changed:
        line = (
            f"island {request.island_id!r}: recompiled from this result's own "
            "request with unchanged input (same circuit, presentation, island "
            "id, profiles and budget) — this is not a new variant; the answer "
            "changes only with a changed budget, a different profile set or a "
            "changed specification/island, not with another call"
        )
    elif budget_changed and fingerprint_known and not references_changed:
        line = (
            f"island {request.island_id!r}: recompiled from this result's own "
            "request with a changed budget (the new IslandBudget replaced the "
            "request's budget; circuit, presentation, island id and profiles "
            "were reused unchanged) — a different input, not a retry"
        )
    else:
        changes = []
        if budget_changed:
            changes.append("budget")
        if not fingerprint_known:
            changes.append("the original request has no content fingerprint")
        elif references_changed:
            changes.append("circuit/presentation/profiles content changed")
        line = (
            f"island {request.island_id!r}: recompiled the current request "
            f"objects with disclosed input change ({'; '.join(changes)}) — the "
            "frozen request holds references, not snapshots, so this is not a "
            "claim of unchanged input or a retry of the old picture"
        )
    return replace(fresh, notes=(*fresh.notes, line))


# --------------------------------------------------------------- the pipeline


def _compile(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
    *,
    budget: islandlayout.IslandBudget | None,
    island_ids: tuple[str, ...] | None,
) -> list[IslandCompileResult]:
    """Shared implementation for one island and for the batch."""
    _require_inputs(circuit, presentation, profiles)

    # 1) The document's own contract, once, **before** any layout: a batch
    #    refused here lays out nothing, and neither does a single island.
    validate_archipelago(circuit, presentation)
    islands = list(presentation.effective_islands())
    by_id = {island.id: island for island in islands}
    book = {str(ref): profile for ref, profile in profiles.items()}

    if island_ids is None:
        order = [island.id for island in islands]
    else:
        order = []
        for island_id in island_ids:
            if not isinstance(island_id, str) or not island_id:
                raise ArchipelagoError(
                    f"island id must be a non-empty string, got {island_id!r} — an "
                    "island compile is named by the island it draws (§2.2)"
                )
            if island_id not in by_id:
                raise ArchipelagoError(
                    f"the presentation declares no island {island_id!r} — it "
                    f"declares {', '.join(sorted(by_id))}; an independent island "
                    "compile is named by the island it draws, and an unknown id "
                    "has no partition to lay out (§2.2)"
                )
            order.append(island_id)

    # 2) The projection.  A batch asks once for every island's subgraph through
    #    `island_subgraphs`; one island asks `island_subgraph` with the crossing
    #    set the whole partition states — never with crossing=(), which would
    #    read every crossing net as internal (and drop its boundary name).
    subgraphs = _subgraphs(circuit, presentation, islands, order)

    return [
        _compile_one(
            circuit, presentation, island_id, subgraphs[island_id], book,
            profiles, budget, len(islands),
        )
        for island_id in order
    ]


def _subgraphs(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    islands: list,
    order: list[str],
) -> dict[str, islandlayout.IslandSubgraph]:
    """``island_id → its subgraph``, through the projection that batch uses.

    A batch is exactly `island_subgraphs` (the page path's own projection, one
    crossing pass for all islands).  A single compile narrows that to one island
    but must still read the crossing set off the **whole** partition.
    """
    if order == [island.id for island in islands]:
        return {
            subgraph.island_id: subgraph
            for subgraph in islandlayout.island_subgraphs(circuit, presentation)
        }
    by_id = {island.id: island for island in islands}
    crossing = set(cross_island_nets(circuit, islands))
    return {
        island_id: islandlayout.island_subgraph(
            circuit, by_id[island_id], crossing
        )
        for island_id in order
    }


def _compile_one(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    island_id: str,
    subgraph: islandlayout.IslandSubgraph,
    book: dict[str, SymbolProfile],
    profiles: Mapping[str, SymbolProfile],
    budget: islandlayout.IslandBudget | None,
    island_count: int,
) -> IslandCompileResult:
    """One island, end to end, with every failure shaped as a refusal."""
    request = IslandCompileRequest(
        circuit=circuit,
        presentation=presentation,
        island_id=island_id,
        profiles=profiles,
        budget=budget,
        input_fingerprint=_input_fingerprint(circuit, presentation, profiles),
    )

    # The profile mapping is one public input, and both layout's whole-document
    # decap scan and readability's profile normalizer may read entries outside
    # this island.  Reject every invalid value before either stage can throw an
    # AttributeError; a genuinely absent profile remains island-local below.
    invalid_profiles = [
        f"symbol {ref!r} has {type(profile).__name__}, expected SymbolProfile"
        for ref, profile in sorted(book.items())
        if not isinstance(profile, SymbolProfile)
    ]
    if invalid_profiles:
        return IslandCompileResult(
            island_id=island_id,
            refusal=_facts_missing_refusal(island_id, invalid_profiles),
            request=request,
        )

    unknown_locks = sorted({
        lock.part_id
        for lock in presentation.user_locks
        if circuit.part(lock.part_id) is None
    })
    if unknown_locks:
        return IslandCompileResult(
            island_id=island_id,
            refusal=_unknown_lock_refusal(island_id, unknown_locks),
            request=request,
        )

    missing = _missing_profiles(circuit, subgraph, book)
    if missing:
        return IslandCompileResult(
            island_id=island_id,
            refusal=_facts_missing_refusal(island_id, missing),
            request=request,
        )

    # A page lock is absolute page geometry, never block-local geometry.  A
    # module lock is measurable here only when one island is the whole module;
    # otherwise the independent block has no module frame to judge it in.
    module_locks = [
        lock.part_id
        for lock in presentation.user_locks
        if not lock.is_page and lock.part_id in subgraph.parts
    ]
    if island_count > 1 and module_locks:
        return IslandCompileResult(
            island_id=island_id,
            refusal=_module_frame_refusal(island_id, module_locks),
            request=request,
        )

    # 1) The layout.  The placer is the first stage that can raise about **this
    #    island** — a pose that does not fit, a fan-out, a lookup that finds
    #    nothing — so its exceptions become this island's refusal.  Only the
    #    shapes the placer is named to raise are caught (`ValueError` and the
    #    `KeyError` of a missing lookup); a `TypeError` is a bug and escapes.
    try:
        block = islandlayout.layout_island(
            circuit, subgraph, book, budget=budget
        )
    except (ValueError, KeyError) as exc:
        return _stage_refusal(island_id, _STAGE_LAYOUT, exc, request)

    # 2) The plan and its identity.  The plan is stamped with the **original
    #    whole document's** two hashes, and 538A's scoped check says the plan
    #    draws exactly the partition the presentation declares for this island.
    try:
        plan = block.plan(
            source=LayoutSource(
                circuit_sha256=circuit.sha256(),
                presentation_sha256=presentation.sha256(),
            )
        )
        validate_archipelago_island_plan(plan, presentation, island_id)
    except (ValueError, KeyError) as exc:
        return _stage_refusal(island_id, _STAGE_PLAN, exc, request)

    from .drawcompiler import (
        GATE_REFUSAL_KINDS,
        island_gate_tolerance_notes,
        island_gate_violations,
    )

    # 3) The local gate.  A checker that cannot read the picture at all (a
    #    placed symbol no profile describes, an unreadable scope) is a fact hole
    #    for this island, not an exception that ends a batch.
    try:
        checked = readability.check(
            plan,
            circuit,
            presentation,
            book,
            # The whole specification judges this local picture; the scope names
            # the parts this island **is**, so the parts it does not draw are not
            # reported as missing connections (538A).
            scope=readability.ReadabilityScope(
                parts=frozenset(subgraph.parts),
                check_page_locks=False,
                check_module_locks=island_count == 1,
            ),
            # The placer and the alignment metric must use the same lattice;
            # budget=None means IslandBudget's defaults inside layout_island.
            grid=(budget or islandlayout.IslandBudget()).grid,
        )
    except (readability.ReadabilityError, KeyError) as exc:
        return _stage_refusal(island_id, _STAGE_READABILITY, exc, request)
    refusing, tolerated = island_gate_violations(checked.hard_violations)
    soft_floor = readability.soft_floor_violations(plan, checked.soft_metrics, book)

    # A hard refusal is the primary failure even when the same picture also
    # breaches the style floor; otherwise the soft metric would hide the more
    # specific lock/facts/circuit category and action.
    if refusing:
        return IslandCompileResult(
            island_id=island_id,
            gate=checked,
            tolerated=tuple(tolerated),
            refusal=_gate_refusal(island_id, refusing, GATE_REFUSAL_KINDS),
            request=request,
        )
    if soft_floor:
        return IslandCompileResult(
            island_id=island_id,
            gate=checked,
            tolerated=tuple(tolerated),
            refusal=_soft_floor_refusal(island_id, soft_floor),
            request=request,
        )

    tolerance_lines = island_gate_tolerance_notes(tolerated)
    block.notes.extend(tolerance_lines)
    plan.evidence = _evidence(
        island_id, island_count, block, checked, tolerance_lines
    )
    return IslandCompileResult(
        island_id=island_id,
        block=block,
        plan=plan,
        gate=checked,
        tolerated=tuple(tolerated),
        notes=(
            f"island {island_id!r}: local checks passed; ok=True covers this "
            "island only — no page, assembly, landing or visual acceptance is "
            "claimed",
            *tolerance_lines,
        ),
        request=request,
    )


# ------------------------------------------------------- the refusal factories


def _stage_refusal(
    island_id: str,
    stage: str,
    exc: BaseException,
    request: IslandCompileRequest,
) -> IslandCompileResult:
    """A stage raised: this island's refusal, naming the stage and the original.

    The category is what has to change, read off **where** the pipeline stopped:

    * ``plan/identity`` raising `ArchipelagoError` — the plan's declared
      partition is not the presentation's.  That is the presentation's own
      statement, so it is `presentation-poor`, the category `drawcompiler` uses
      for the same check;
    * a `KeyError`, or a checker that cannot read the picture at all
      (`ReadabilityError` at ``readability``) — a fact nobody stated, so
      `facts-missing`;
    * anything else the placer or the plan stage raised — this island's picture
      could not be produced, so `layout-unsat`.

    ``block``/``plan`` are absent by construction (the default), so a refused
    island never leaves a candidate behind, and ``gate`` is ``None`` because no
    reading exists for a stage that raised before or during the check.
    """
    original = f"{type(exc).__name__}: {exc}"
    if stage == _STAGE_PLAN and isinstance(exc, ArchipelagoError):
        category = FAILURE_PRESENTATION_POOR
        detail = (
            f"island {island_id!r}: the {stage} stage refused the drawn plan — "
            f"{original}; the plan's declared partition is what the presentation "
            "states for this island, so the presentation (or the plan laid out "
            "from it) is what has to change"
        )
        action = (
            "correct this island's declared partition — its `parts`, `group` or "
            "`island` — or the plan that was laid out from it; never re-stamp a "
            "part to make the identity check pass"
        )
    elif isinstance(exc, KeyError):
        category = FAILURE_FACTS_MISSING
        detail = (
            f"island {island_id!r}: the {stage} stage looked up a fact that is "
            f"not there — {original}; nothing was planned or judged from a guess"
        )
        action = (
            "state the fact the lookup names — a symbol profile for every part "
            "this island declares, or the declared net — then compile the island "
            "again"
        )
    elif stage == _STAGE_READABILITY and isinstance(
        exc, readability.ReadabilityError
    ):
        category = FAILURE_FACTS_MISSING
        detail = (
            f"island {island_id!r}: the {stage} stage could not judge the local "
            f"picture at all — {original}; the checker refused to report 'no "
            "violations' on inputs it cannot read"
        )
        action = (
            "supply the fact the checker names — a profile for every placed "
            "symbol, and a plan whose parts it can read — then compile the island "
            "again; nothing was accepted in the meantime"
        )
    else:
        category = FAILURE_LAYOUT_UNSAT
        detail = (
            f"island {island_id!r}: the {stage} stage failed before this island "
            f"could be read — {original}; the island's own picture is what could "
            "not be produced, and no candidate exists to adopt"
        )
        action = (
            "fix what this island's own parts or profile state — its declared "
            "parts, their symbols or the local budget; the other islands are "
            "compiled independently, and no retry was attempted"
        )
    return IslandCompileResult(
        island_id=island_id,
        refusal=GrammarFailure(
            category=category,
            subject=island_id,
            detail=detail,
            action=action,
        ),
        request=request,
    )


def _unknown_lock_refusal(island_id: str, part_ids: list[str]) -> GrammarFailure:
    """A lock must name a declared part; scope is not permission to drop it."""
    subject = f"presentationSpec.userLocks[{part_ids[0]}]"
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=subject,
        detail=(
            f"island {island_id!r}: userLocks name undeclared part(s) "
            f"{', '.join(part_ids)}; no scoped or independent compile may skip "
            "a lock whose subject the circuit does not declare"
        ),
        action=(
            "declare the locked part in CircuitSpec or remove/correct the lock, "
            "then compile again; no layout candidate was produced"
        ),
    )


def _module_frame_refusal(island_id: str, part_ids: list[str]) -> GrammarFailure:
    """A multi-island block is not automatically the module drawing's frame."""
    subject = f"presentationSpec.userLocks[{part_ids[0]}]"
    return GrammarFailure(
        category=FAILURE_PRESENTATION_POOR,
        subject=subject,
        detail=(
            f"island {island_id!r}: module-scoped userLocks for "
            f"{', '.join(part_ids)} need the module drawing's coordinate frame; "
            "this is one independent block of a multi-island module, so comparing "
            "them with block-local coordinates would judge the wrong frame"
        ),
        action=(
            "evaluate these locks in the assembled module/page compiler, or state "
            "a single-island module; the independent island is refused rather "
            "than silently ignoring or reinterpreting the locks"
        ),
    )


def _facts_missing_refusal(island_id: str, missing: list[str]) -> GrammarFailure:
    """A missing/invalid profile is a fact hole, not a crash in the placer."""
    return GrammarFailure(
        category=FAILURE_FACTS_MISSING,
        subject=island_id,
        detail=(
            f"island {island_id!r}: the profile set has no usable SymbolProfile "
            f"for {'; '.join(missing)} — the local placer needs each part's "
            "measured symbol, and a dict/None/guess is not that measurement"
        ),
        action=(
            "add or correct the symbol profile(s) in the profile set (the library "
            "the parts were measured with), or correct the part's symbolRef — the "
            "island is not laid out until every declared part has a valid profile"
        ),
    )


def _gate_refusal(
    island_id: str,
    violations: list[readability.HardViolation],
    kinds: Mapping[str, str],
) -> GrammarFailure:
    """053 §4's four categories, dispatched by the hard kind (the shared table).

    The category is what has to change, so it is read off the checker's own line
    instead of a single "the drawing was refused" sentence: a lock is the
    engineer's intent, an unconnected required pin is a missing fact, an NC pin
    that got wired is an invalid circuit, and everything else is this island's
    own geometry.
    """
    first = violations[0]
    count = len(violations)
    head = (
        f"island {island_id!r}: the independent readability checker refused "
        f"{count} hard violation(s) — {first.render()}"
    )
    category = kinds.get(first.kind, FAILURE_LAYOUT_UNSAT)
    if category == FAILURE_PRESENTATION_POOR:
        subject = first.objects[0] if first.objects else island_id
        detail = (
            f"{head} — the local picture contradicts the engineer's lock, and the "
            "lock is the input this island may not quietly ignore"
        )
        action = (
            "honour the lock or change it: the island is refused because it "
            "breaks the lock, not because the drawing does not fit"
        )
    elif category == FAILURE_FACTS_MISSING:
        subject = first.objects[-1] if first.objects else island_id
        detail = (
            f"{head} — the circuit names a pin the drawn symbols have no tip for"
        )
        action = (
            "fix the side the checker's line names: a CircuitSpec net listing a "
            "pin the symbol does not carry, or a profile missing that pin"
        )
    elif category == FAILURE_CIRCUIT_INVALID:
        subject = island_id
        detail = f"{head} — the local picture connects an explicit NC pin"
        action = (
            "remove the conductor from the NC pin, or stop declaring that pin NC "
            "— the island may not draw a connection the circuit forbids"
        )
    else:
        subject = island_id
        detail = (
            f"{head} — the local picture itself is what has to move: this island "
            "compiles on its own, so the finding belongs to it and not to a page"
        )
        action = (
            "move this island's parts or wires — a wider pitch, a different row "
            "or a lower bend count; no page-level lever can fix a local finding"
        )
    return GrammarFailure(
        category=category, subject=subject, detail=detail, action=action
    )


def _soft_floor_refusal(island_id: str, breaches: list[str]) -> GrammarFailure:
    """The style spec's soft numbers are a floor here too (534 R5), per island."""
    return GrammarFailure(
        category=FAILURE_LAYOUT_UNSAT,
        subject=island_id,
        detail=(
            f"island {island_id!r}: the local picture is over the style spec's "
            f"soft floor in {len(breaches)} place(s): " + "; ".join(breaches[:3])
        ),
        action=(
            "move this island's parts or wires — a wider pitch or a lower bend "
            "count is the same lever the page-level floor uses"
        ),
    )


# ------------------------------------------------------------- the evidence


def _evidence(
    island_id: str,
    island_count: int,
    block: islandlayout.IslandBlock,
    checked: readability.CheckResult,
    tolerance_lines: list[str],
) -> LayoutEvidence:
    """What this island's plan states about itself, and what it does not claim.

    ``hard_violations`` is empty because nothing refused it — the tolerated rows
    go to ``notes`` in the gate's own words, so the evidence's derived verdict
    stays ``pass`` and a reader can still enumerate every row it was delivered
    with.  ``grammar_findings`` is empty because no grammar ran, and the notes
    say so rather than leaving an empty list to be read as "the grammar passed".
    """
    return LayoutEvidence(
        checker=readability.CHECKER_NAME,
        hard_violations=[],
        grammar_findings=[],
        soft_metrics=dict(checked.soft_metrics),
        soft_reasons={
            key: " | ".join(value)
            for key, value in checked.soft_reasons.items()
        },
        notes=[
            f"candidate from {ISLAND_COMPILER_NAME} independent island compile: "
            f"island {island_id!r} of {island_count} declared island(s), laid out "
            f"on its own ({len(block.parts)} part(s), "
            f"{len(block.labels)} boundary label(s), "
            f"{len(block.power_symbols)} boundary flag(s))",
            "this is one island's local picture, not a packed page: no other "
            "island was placed, no channel was reserved and no page was assembled",
            "grammar/page layers did not run: grammar_findings is empty because "
            "no grammar was executed, and no page_box, title block or page "
            "keep-out was evaluated — those need the assembly and page context "
            "this batch does not have, so nothing here says the page would pass",
            "page-scoped user locks were not evaluated: their coordinates belong "
            "to the page, not this independent block; multi-island module locks "
            "are refused until the module frame exists rather than reinterpreted",
            *tolerance_lines,
        ],
    )


# ----------------------------------------------------------------- the inputs


def _input_fingerprint(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
) -> str:
    """Fingerprint the values a recompile will read, without snapshotting them.

    Valid profiles use their public geometry hash.  Invalid values are included
    by type/repr so even a refused request cannot later claim its mapping was
    unchanged after being edited.  This digest is provenance only; it is not a
    second LayoutPlan source or geometry identity.
    """
    rows = []
    for key, profile in sorted(profiles.items(), key=lambda item: repr(item[0])):
        if isinstance(profile, SymbolProfile):
            described = (profile.symbol_ref, profile.geometry_hash())
        else:
            described = (type(profile).__name__, repr(profile))
        rows.append((repr(key), described))
    payload = repr((circuit.sha256(), presentation.sha256(), rows)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_inputs(
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
) -> None:
    """Wrong types are refused by name, before anything reads them."""
    for value, expected, name in (
        (circuit, CircuitSpec, "circuit"),
        (presentation, PresentationSpec, "presentation"),
    ):
        if not isinstance(value, expected):
            raise ValueError(
                f"{name} must be a {expected.__name__}, got "
                f"{type(value).__name__}"
            )
    if not isinstance(profiles, Mapping):
        raise ValueError(
            "profiles must be a mapping symbolRef -> SymbolProfile, got "
            f"{type(profiles).__name__}"
        )
    if not presentation.is_archipelago:
        raise ArchipelagoError(
            "the presentation declares no archipelago island — an independent "
            "island compile is one island of a declared archipelago, and a "
            "presentation that states no islands has none to compile on its "
            "own (§2.2)"
        )


def _missing_profiles(
    circuit: CircuitSpec,
    subgraph: islandlayout.IslandSubgraph,
    book: Mapping[str, SymbolProfile],
) -> list[str]:
    """The parts of this island the profile set cannot draw, in island order."""
    missing: list[str] = []
    for part_id in subgraph.parts:
        part = circuit.part(part_id)
        if part is None:
            missing.append(f"{part_id} (the circuit has no such part)")
            continue
        symbol_ref = str(getattr(part, "symbol_ref", "") or "")
        if symbol_ref not in book:
            shown = symbol_ref or "<no symbolRef>"
            missing.append(f"{part_id} (symbol {shown!r})")
            continue
        profile = book[symbol_ref]
        if not isinstance(profile, SymbolProfile):
            missing.append(
                f"{part_id} (symbol {symbol_ref!r} has "
                f"{type(profile).__name__}, expected SymbolProfile)"
            )
    return missing
