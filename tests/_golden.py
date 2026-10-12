"""159: the golden board, parsed and **solved once per test session**.

**Why this file exists.** ``generate_plan`` on the golden CH340G board is a grid
search, not a lookup: every placement attempt routs the whole sheet
(:data:`boardwise.engines.generate.WIDTH_ATTEMPTS` of them, 141), and one call
measures at 45-60 s. Six modules were each paying it for themselves — four with
a module-scoped fixture or a module-level list cache (test_generate,
test_layout, test_137, test_143e) and two with **no cache at all**
(test_136, whose five call sites made it the slowest file in the suite at 304 s;
test_engine_boundary, four cases). Counted at the call sites, those modules spent
**15 solves** on a single fact; after this file, 14 of the 15 are one solve (the
15th is test_generate's deliberate purity rebuild — see below).

**Why sharing is safe** (159's isolation check; measurements and the greps
behind it are in ``outputs/159/perf_evidence.md``):

* the engines are **read-only over their inputs**. ``layout.route_nets`` /
  ``plan_placement`` / ``_choose_geometry`` / ``validate_full`` and
  ``replay.build_replay_plan`` write to no model, no offsets dict and no list
  they were handed — every ``append`` in them is on a container they built
  themselves, and a grep for an assignment to a parameter finds none;
  ``generate_plan`` is documented pure (no bridge, no editor, no I/O);
* the two writers in the pipeline are named and avoidable:
  ``generate.strip_dangling_nets`` mutates the model in place — and is a
  **no-op on this fixture**, whose parser leaves no single-member net (13 nets,
  none with fewer than 2 pins, measured) — and ``draw.run_draw``'s verdict
  mutates the *candidate* it parsed from the editor, never the golden model;
* the one plan-level writer is the **chooser**: ``replay_or_solver`` appends its
  "which engine ran, and why" note to ``plan.notes``. So plans are handed out
  **read-only by convention**, and a caller that writes to one takes
  :func:`golden_plan_copy` (a deepcopy, measured at ~2 ms — six orders of
  magnitude below the solve it avoids).

Net effect: the model and the offsets are the one cached object, the plan is the
one cached object, and a caller that needs to write takes a copy. The one thing
a caller must not do is treat what it gets as its own: these objects are shared,
so a write to one is a write to everybody's, and the tests above are the ones
that would fail if that ever became untrue (``test_generate.test_plan_is_stable``
compares the shared plan against a fresh solve).
"""

from __future__ import annotations

import copy
import functools
from pathlib import Path

from boardwise.core.model import DesignModel
from boardwise.engines import layout
from boardwise.engines.generate import (
    ActionPlan,
    canvas_pin_offsets,
    generate_plan,
    normalise_strategy,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import build_pin_offsets, build_schematic_model

#: The golden fixture, by **absolute** path: half the suite loads it through a
#: relative ``tests/fixtures/...`` string (which silently depends on pytest's
#: working directory being the repo root) and half through ``Path(__file__)``.
#: One spelling, and it is the one that cannot break under ``-q`` from another
#: cwd.
GOLDEN = str(Path(__file__).resolve().parent / "fixtures" / "ch340_golden.epro2")


@functools.cache
def golden_model():
    """The golden board's model — parsed once for the whole session.

    ``strip_dangling_nets`` runs on it, which is how four of the modules that
    used to pay for their own copy built the board (136, test_137,
    test_engine_boundary, test_replay) while test_generate, test_layout and
    test_143e took the raw parse. The two are the same board *here*: this
    fixture's parser leaves no single-member net (13 nets, none with fewer than
    two pins, measured), so the strip is a no-op. It stays in the chain because
    the contract those call sites relied on is "the model the solver sees has no
    dangling nets", not "the parser happens to leave none" — and it is
    idempotent, so a consumer that strips again (``run_draw`` does, on whatever
    model it is handed) cannot change anything.

    Read-only by convention — see the module docstring.
    """
    return strip_dangling_nets(build_schematic_model(GOLDEN))


@functools.cache
def golden_file_offsets() -> dict[str, dict[str, tuple[float, float]]]:
    """The same offsets as the parser hands them over, **file space**.

    Kept as a second name rather than folded into :func:`golden_offsets`
    because the two callers that need it say "file space" in their signature:
    ``build_replay_plan`` and ``replay_or_solver`` both take ``offsets_file``.
    The two dicts are equal by 010c's identity — ``canvas_pin_offsets`` is a
    named checkpoint, not a conversion — so this costs one dict build and keeps
    every call site reading in its own coordinate space.
    """
    return build_pin_offsets(GOLDEN)


@functools.cache
def golden_offsets() -> dict[str, dict[str, tuple[float, float]]]:
    """The golden board's symbol pin offsets, in canvas space.

    ``canvas_pin_offsets`` is an identity (010c) and is kept named as the
    boundary a coordinate guard can point at, so callers get the same values
    whether they think in file space (:func:`golden_file_offsets`) or canvas
    space. Read-only by convention: the engines never write into an offsets
    dict.
    """
    return canvas_pin_offsets(golden_file_offsets())


@functools.cache
def _golden_plan_for(policy: str) -> ActionPlan:
    """The solve itself, keyed on the **normalised** policy name.

    The two-level split is the whole point of the indirection: ``functools.cache``
    keys on the arguments *as passed*, so normalising inside a single cached
    function would still file ``None`` and ``"auto"`` as two entries — measured:
    ``golden_plan("auto")`` after ``golden_plan()`` cost a second 59 s solve
    instead of hitting. Here ``None`` and ``"auto"`` both arrive as ``"auto"``
    and there is exactly one solve for that policy.
    """
    return generate_plan(golden_model(), golden_offsets(), policy)


def golden_plan(strategy: str | None = None) -> ActionPlan:
    """The golden board's solver plan — one solve, shared by every consumer.

    ``strategy`` keys the cache, so the strategy table (006b/143e) gets one plan
    per policy it asks about and no more: ``None`` (what the tests here pass) and
    ``"auto"`` (what the draw flow spells out through ``replay_or_solver``) are
    the *same policy* and share one entry — see :func:`_golden_plan_for` for why
    that has to be two functions. An unknown spelling normalises to ``auto``,
    which is also what ``generate_plan`` would have done with it.

    **Read-only by convention**; a caller that writes to the plan takes
    :func:`golden_plan_copy`.
    """
    return _golden_plan_for(normalise_strategy(strategy))


def golden_plan_copy(strategy: str | None = None) -> ActionPlan:
    """A **private copy** of :func:`golden_plan`, for a caller that mutates it.

    The chooser appends to ``plan.notes`` and the draw flow rewrites
    ``plan.pin_positions`` / ``plan.wires`` when it snaps drifted endpoints, so
    those two callers must not be handed the shared object. The copy is cheap
    (measured ~2 ms against a 45-65 s solve), which is what makes "share the
    solve, copy the plan" the whole of this module's design.
    """
    return copy.deepcopy(golden_plan(strategy))


@functools.cache
def golden_routes() -> tuple[list[layout.RoutedNet], list[layout.Violation]]:
    """The router's own answer for the golden page: ``(routes, violations)``.

    This is exactly ``layout.route_nets(golden, plan.pin_positions,
    plan.geometry)`` — the call 136 makes to read the router's
    ``SEPARATION_GIVEN_UP`` disclosures off the router itself rather than out of
    the plan's merged violation list. The inputs are the plan's own pins and
    geometry, the function is pure, so re-running it is re-measuring one answer.

    The returned lists are the router's, not the plan's (``generate_plan`` keeps
    copies), so nothing here aliases the cached plan.
    """
    plan = golden_plan()
    return layout.route_nets(golden_model(), plan.pin_positions, plan.geometry)


def solver_plan_or_cache(
    model: DesignModel,
    offsets: dict[str, dict[str, tuple[float, float]]],
    strategy: str | None = None,
) -> ActionPlan:
    """``generate_plan``, served from the session cache for the golden board.

    Signature-compatible with ``boardwise.engines.generate.generate_plan`` so a
    test module can patch it in where the *solver* is not its subject.
    ``test_engine_boundary`` is the case: its four solver cases differ only in
    which branch of the chooser runs and in the note that branch appends, and
    the chooser hands the solver the same model and offsets every time — so one
    real solve answers all four, and three of the four stop being a minute of
    grid search each.

    The first call goes through the **real** generator (the module still fails
    loudly if the golden board stops solving), every caller gets its own copy
    (``replay_or_solver`` appends to ``plan.notes``), and anything that is not
    the golden board's own inputs falls through to the real generator untouched.

    "The golden board's own inputs" is decided **by value**, not by identity:
    ``BoardModel`` is a dataclass (0.04 ms to compare, measured) and one parse
    of the same fixture equals another, so a caller that insists on its own
    ``build_schematic_model(GOLDEN)`` still hits the cache. Only equality can
    produce a false hit, and an equal model and equal offsets *are* the same
    solver question — the same relation ``test_generate.test_plan_is_stable``
    asserts the plan against.
    """
    if model == golden_model() and offsets == golden_offsets():
        return golden_plan_copy(strategy)
    return generate_plan(model, offsets, strategy)
