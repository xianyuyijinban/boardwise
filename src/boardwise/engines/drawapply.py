"""`draw-module`: landing a compiled drawing on a page (054 stage C1).

The step the drawing compiler cannot take on its own. `compile()` (053 stage B)
produces a `LayoutPlan` **offline**: which symbol, at which pose, at which point,
with which wires — but no designators (a CircuitSpec id is not a number), no
library device (a symbol ref is not an orderable part), and no page. This module
supplies exactly those three, offline and pure, and hands the result to the
contract `boardwise edit` already uses: a `ChangePlan` of kind ``draw-module``.

Four decisions, each with a reason that is a measurement rather than a taste:

* **A designator is allocated from the page's *and* the project's pool.** Measured
  on 2026-09-25 (036b): the host honours a requested ``R2`` only when nothing in
  the *project* has it, and it renames the part **mid-run** when it does not — the
  plan's own postconditions then stop holding and a correct circuit is reported as
  `verification_disagrees`. So :func:`module_plan` allocates from
  `addcomponent.designator_pool` (page ∪ export) and apply re-checks that the
  numbers are still free.
* **The plan's expected pins are *offsets*, not page points.** The editor's own
  pin reading is the acceptance's third protection ("放置后回读实际引脚位置与 plan
  期望比对，不相信 API 返回值"), and an offset is the thing the plan and the placed
  part can be compared on without assuming the editor landed the part exactly
  where it was asked to. The tolerance is half a lattice step.
* **The profile geometry table is a guard, not a comment.** A plan is compiled
  against `SymbolProfile` geometry; if the library's geometry changed underneath
  it, every pin tip moves and no read-back can tell that from a routing bug. The
  plan therefore carries ``symbolRef -> geometry_hash`` and apply recomputes it
  **before** the first write (:func:`library_problems`).
* **A net label the host cannot place is a declared downgrade.** `place_netlabel`
  is measured unusable on this host (029), so a label the plan drew becomes a
  wire-carried net name and :func:`module_plan` says so in
  ``change.downgrades``. Silently dropping it would be a plan whose drawing is not
  the drawing that was authorised.

Nothing here talks to the bridge. The geometry and netlist shapes it reads are
`sch.geometry` / `sch.netlist` dumps the CLI fetches; the shapes it *writes* are
the ones 029/036/037 measured.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core.changeplan import (
    DRAW_FLAG_GROUND,
    DRAW_FLAG_POWER,
    DRAW_GRID,
    DRAW_MODULE_KIND,
    DRAW_VALUE_KEY,
    ChangePlan,
    PlanChange,
    PlanDrawBaseline,
    PlanDrawFlag,
    PlanDrawPart,
    PlanDrawPin,
    PlanDrawWire,
    PlanIsland,
    PlanSource,
    PlanTarget,
    resolve_on_page,
)
from ..core.circuitspec import CircuitSpec
from ..core.geometry import transform_point
from ..core import textmetrics
from ..core.layoutplan import DOWNGRADE_NOTE_PREFIX, LayoutPart, LayoutPlan
from ..core.model import is_ground_net
from ..core.presentationspec import PresentationSpec
from ..core.symbolprofile import SymbolProfile, SymbolPose, role_siblings
from . import addcomponent

__all__ = [
    "CENSUS_CLEARANCE",
    "CENSUS_FALLBACK_HALF",
    "GEOMETRY_SECTIONS",
    "DiscardSelection",
    "DrawPlanError",
    "HALF_GRID",
    "LABEL_STUB_LENGTH",
    "SOURCE_BASIS",
    "all_satisfied",
    "canvas_census",
    "census_changes",
    "census_digest",
    "census_items",
    "census_keepouts",
    "census_phrase",
    "discard_selection",
    "designator_problems",
    "expected_pin_points",
    "flag_kind",
    "guard_problems",
    "islands_from_circuit",
    "library_problems",
    "live_islands",
    "module_plan",
    "net_name_problems",
    "netlabel_items",
    "plan_pins",
    "placement_problems",
    "posed_pin_offsets",
    "postcondition_problems",
    "profile_table",
    "source_digest",
    "value_problems",
]

#: The deviation a pin read-back may show and still be the plan's pin: half a
#: lattice step (054 §一 protection 3 says "容差半格"). The lattice is 029's and
#: the compiler's 5 units (`addcomponent.LANDING_GRID`), so this is 2.5.
HALF_GRID = DRAW_GRID / 2.0

#: The rail-flag convention 053B's compiler writes with
#: (`drawcompiler.CompileBudget.gnd_flag` / `.power_flag_prefix`, whose defaults
#: these are). Read here rather than imported from the compiler because a plan is
#: applied against the symbols it carries, not against whatever the compiler's
#: defaults are on the day of the run — see :func:`flag_kind`.
FLAG_SYMBOL_GROUND = "PWR-GND"
FLAG_SYMBOL_POWER_PREFIX = "PWR-"

#: How long the named stub is that stands in for a label this host cannot place
#: (057 sec.4): two lattice steps out of the label's anchor, towards its text box,
#: so it stays inside the room the compiler reserved for the label. Drawn where no
#: planned wire of the net already reaches the anchor — always on the page path, and
#: on a single-module plan for a net that has a name and no conductor at all (145d:
#: GATE/VFB_NF's shape). See :func:`module_plan`'s ``label_stubs``.
LABEL_STUB_LENGTH = 2 * DRAW_GRID

#: The lengths a stub's far end is tried at, in order (099d): the preferred one
#: first (:data:`LABEL_STUB_LENGTH`, or the text box's own reach when that is
#: shorter — the rung 057 measured), then the lattice rungs a blocked stub steps
#: back to or out along before the drawing is refused.
LABEL_STUB_LENGTHS: tuple[float, ...] = (
    2 * DRAW_GRID, DRAW_GRID, 3 * DRAW_GRID, 4 * DRAW_GRID, 6 * DRAW_GRID,
    8 * DRAW_GRID,
)

#: The four runs a stub can leave its anchor along, before the preferred one.
_LABEL_STUB_DIRECTIONS: tuple[tuple[float, float], ...] = (
    (1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0),
)

#: The perpendicular steps a **bent** stub is tried at (099f), before the same
#: length ladder runs out along the label's own side. A straight run is blocked
#: when a foreign conductor sits one lattice step from the pin — 099e's RXD: the
#: V3 route's corner (285,720) hugged the pin tip at (290,720) for its whole
#: outward run — and the shape that gets out of there is the one a human draws:
#: **one step aside, then out to where the label's box is** (069 sec.10's flag
#: lead shape). Tried after every straight rung, so a drawing that had a clear
#: straight stub keeps it to the byte.
LABEL_STUB_STEPS: tuple[float, ...] = (DRAW_GRID, 2 * DRAW_GRID)


@dataclass(frozen=True)
class _StubRun:
    """One candidate run for a label's name stub (099d straight, 099f bent).

    ``points`` is the polyline the stub would be drawn as, anchor first; ``side``
    is the direction of its last leg (the label's own side), ``shape`` spells the
    rung out for the refusal text ("left 10" / "up 5 then left 10") and
    ``family`` is the coarser name one refusal line is written per ("straight
    left" / "bent up then left") — a refusal lists one line per family, not one
    per length rung.
    """

    points: tuple[tuple[float, float], ...]
    side: tuple[float, float]
    shape: str
    family: str

#: What the plan's ``source.inputSha256`` is a digest **of**. Spelled out because
#: a digest whose basis is not written down is a number nobody can reproduce.
SOURCE_BASIS = (
    "sha256 of the canonical JSON {circuitSha256, presentationSha256, "
    "layoutSha256, candidate, profiles} — every input this drawing was built "
    "from, in one string"
)


class DrawPlanError(ValueError):
    """The drawing cannot become an executable plan.

    One class for every way in: the CLI turns it into exit 5 with the message
    printed, and each message names what is missing and what would fix it —
    "cannot draw" alone sends the reader back to the specs with nothing to
    compare against.
    """


# --------------------------------------------------------------------- inputs


def load_library(path: str | Path) -> dict[str, SymbolProfile]:
    """Read a 054 library document: the `SymbolProfile`s a drawing is compiled with.

    Three shapes, because the three are the ones that exist on this machine and
    inventing a fourth would mean forcing an export through a conversion:

    * ``{"profiles": [<SymbolProfile>, …]}`` — the document this batch defines
      and `docs/architecture.md` describes;
    * a bare list of profiles (a dump of a library read);
    * a mapping ``symbolRef -> <SymbolProfile>``, where the key is allowed to
      supply ``symbolRef`` when the profile itself omits it.

    Every profile goes through `SymbolProfile.from_dict`, so the schema's own
    refusals (a pose outside the finite set, two pins on one tip, an unknown key)
    are the reader's refusals — the same ones the compiler would raise, at the
    same place, rather than a second validator written here.
    """
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise DrawPlanError(f"{source}: cannot be read ({exc})") from exc
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise DrawPlanError(f"{source}: is not JSON ({exc})") from exc
    entries: list[tuple[str, Any]]
    if isinstance(payload, dict) and "profiles" in payload:
        raw = payload["profiles"]
        if not isinstance(raw, list) or not raw:
            raise DrawPlanError(
                f"{source}: profiles must be a non-empty list of SymbolProfile objects, "
                f"got {raw!r}"
            )
        entries = [("", item) for item in raw]
    elif isinstance(payload, list):
        if not payload:
            raise DrawPlanError(f"{source}: the library is empty")
        entries = [("", item) for item in payload]
    elif isinstance(payload, dict):
        if not payload:
            raise DrawPlanError(f"{source}: the library is empty")
        entries = [(str(key), item) for key, item in payload.items()]
    else:
        raise DrawPlanError(
            f"{source}: a library is a `{{\"profiles\": […]}}` document, a list of "
            f"SymbolProfile objects or a symbolRef -> SymbolProfile mapping, got "
            f"{type(payload).__name__}"
        )
    book: dict[str, SymbolProfile] = {}
    for key, item in entries:
        if not isinstance(item, dict):
            raise DrawPlanError(
                f"{source}: every library entry must be an object, got {item!r}"
            )
        body = dict(item)
        if key and not body.get("symbolRef"):
            body["symbolRef"] = key
        try:
            profile = SymbolProfile.from_dict(body)
        except ValueError as exc:
            raise DrawPlanError(f"{source}: {exc}") from exc
        if profile.symbol_ref in book:
            raise DrawPlanError(
                f"{source}: {profile.symbol_ref!r} is described twice — one symbol has "
                "one geometry, and two entries would make the geometry guard a coin toss"
            )
        book[profile.symbol_ref] = profile
    return book


def profile_table(profiles: Mapping[str, SymbolProfile]) -> list[tuple[str, str]]:
    """``[(symbolRef, geometryHash)]``, sorted — the plan's library guard.

    Written into the plan so apply can re-compute it from the profiles document
    it is handed and refuse a library that moved underneath the drawing. The
    mapping is checked the way `drawcompiler._profile_book` checks it (a book
    keyed by anything but the symbol it describes is the silent wrong-symbol
    failure), but a plain mapping is accepted here because this function is also
    the guard's *reader*.
    """
    if not isinstance(profiles, Mapping):
        raise DrawPlanError(
            "profiles must be a mapping symbolRef -> SymbolProfile, got "
            f"{type(profiles).__name__}"
        )
    out: list[tuple[str, str]] = []
    for key, profile in profiles.items():
        if not isinstance(profile, SymbolProfile):
            raise DrawPlanError(
                f"profiles[{key!r}] is {type(profile).__name__}, expected a SymbolProfile"
            )
        if str(key) != profile.symbol_ref:
            raise DrawPlanError(
                f"profiles[{key!r}] holds the profile of {profile.symbol_ref!r} — a "
                "library is keyed by the symbol it describes"
            )
        out.append((profile.symbol_ref, profile.geometry_hash()))
    return sorted(out)


def source_digest(
    circuit_sha256: str,
    presentation_sha256: str,
    layout_sha256: str,
    candidate: int,
    profile_hashes: Sequence[tuple[str, str]],
) -> str:
    """The plan's own input digest: everything it was built from, in one string.

    Same convention as `core.changeplan.sha256_of`: the plan's ``inputSha256``
    answers "is what this plan was built against still what I have", and for a
    compiled drawing that is three documents plus the candidate index plus the
    library geometry. See :data:`SOURCE_BASIS` for the exact payload.
    """
    payload = json.dumps(
        {
            "circuitSha256": circuit_sha256,
            "presentationSha256": presentation_sha256,
            "layoutSha256": layout_sha256,
            "candidate": int(candidate),
            "profiles": [[ref, digest] for ref, digest in profile_hashes],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def posed_pin_offsets(
    profile: SymbolProfile, rotation: float, mirror: bool
) -> dict[str, tuple[float, float]]:
    """This symbol's pin tips as offsets from its origin, under a pose.

    One ruler for the reading and the writing: `core.geometry.transform_point`
    (mirror, then CCW rotation), which is the transform the readability checker
    derives the plan's netlist with and the one 053B's compiler posed the
    geometry with. A second transform here would be a second ruler for the same
    drawing.
    """
    pose = SymbolPose(rotation=int(rotation), mirror=bool(mirror))
    out: dict[str, tuple[float, float]] = {}
    for pin in profile.pins:
        x, y = transform_point(
            pin.tip[0], pin.tip[1], rotation=pose.rotation, mirror=pose.mirror,
            ox=0.0, oy=0.0,
        )
        out[str(pin.number)] = (round(x, 6), round(y, 6))
    return out


def expected_pin_points(part: PlanDrawPart) -> dict[str, tuple[float, float]]:
    """``pinNumber -> (x, y)`` in page coordinates, from a plan part's own offsets."""
    return {
        pin.number: (round(part.x + pin.dx, 6), round(part.y + pin.dy, 6))
        for pin in part.pins
    }


def flag_kind(net: str, symbol_ref: str = "") -> str:
    """Which `sch.place_power` kind a rail net takes, or ``''``.

    Two judgements, in this order, because either one alone is wrong on a real
    drawing:

    1. **the net's name**, through `addcomponent.power_flag_kind` — which defers
       the ground half to `layout._net_kind` and through it to
       `core.model.is_ground_net`, the single place a name is called ground;
    2. **the symbol the drawing actually used**, when the name is not one the
       host's vocabulary recognises. Measured fact, not a taste:
       `power_flag_kind('VIN')` answers ``''`` (its regex knows ``+5V``, ``VCC``,
       ``VDD``, ``V5`` — not ``VIN``), while 053B's compiler writes a
       ``PWR-<net>`` flag for every rail by the `CompileBudget` convention. So a
       plan that drew ``PWR-VIN`` on a ``power``-class net is executable, and
       refusing it here would refuse every input rail this repo draws. The
       convention is :data:`FLAG_SYMBOL_GROUND` / :data:`FLAG_SYMBOL_POWER_PREFIX`:
       a symbol is a ground flag when the name it carries is a ground name
       (``PWR-GND``, ``PWR-PGND``) and a supply flag otherwise.

    A name and a symbol that disagree (a ground-named net drawn with a power
    symbol) raise rather than pick one: the flag's kind is what the editor's
    netlist carries (029-d), so picking would misname the net on the board.

    143d: that rule was only applied where **both** judgements spoke, so it was
    silent exactly where an unrecognised name meets a symbol that says *ground* —
    `flag_kind("VIN5", "PWR-GND")` answered ``Ground``, and apply put a ground flag
    on a rail. "Not in the host's vocabulary" is not a licence for the symbol to
    say anything: a ground symbol on a net whose name is not a ground name is the
    same disagreement as the one above, and the second half of this function
    refuses it. The cross-check is `is_ground_net` — the one place this repo calls
    a name ground — rather than a second reading of the symbol's text.
    """
    by_name = str(addcomponent.power_flag_kind(net) or "")
    reference = (symbol_ref or "").upper()
    if reference == FLAG_SYMBOL_GROUND or (
        reference.startswith(FLAG_SYMBOL_POWER_PREFIX)
        # `PWR-<X>`: a flag for X, so the symbol is a ground flag exactly when the
        # name it carries is one (`PWR-GND`, and `PWR-PGND` / `PWR-AGND` the same
        # way — the ground vocabulary is not this function's to re-state).
        and is_ground_net(reference[len(FLAG_SYMBOL_POWER_PREFIX):])
    ):
        by_symbol = DRAW_FLAG_GROUND
    elif reference.startswith(FLAG_SYMBOL_POWER_PREFIX):
        by_symbol = DRAW_FLAG_POWER
    else:
        by_symbol = ""
    if by_name and by_symbol and by_name != by_symbol:
        raise DrawPlanError(
            f"net {net!r} is a {by_name} name but the drawing places a {symbol_ref!r} "
            f"symbol (a {by_symbol} flag by this repo's convention) — a flag's kind is "
            "what the editor's netlist carries, so the two have to agree"
        )
    if by_symbol == DRAW_FLAG_GROUND and not is_ground_net(net):
        raise DrawPlanError(
            f"net {net!r} is not a ground name, but the drawing places a "
            f"{symbol_ref!r} symbol — which is a {DRAW_FLAG_GROUND} flag by this repo's "
            "convention (053B writes `PWR-GND` for a ground and `PWR-<net>` for a "
            "rail). The name is not one the host's flag vocabulary recognises, so the "
            "symbol is the only thing saying what this flag is, and a ground flag on "
            f"net {net!r} would put that net on ground in the editor's own netlist "
            "(029-d): either draw the rail's own `PWR-{net}` symbol or say what this "
            "net is"
        )
    return by_name or by_symbol


# ------------------------------------------------------------ designators


def is_designator(name: str) -> bool:
    """Is this string a *designator*, by the allocator's own rule (143d)?

    ``<letters><digits>`` — the shape `addcomponent.allocate_designator` can
    produce and the shape every reader in this repo matches on
    (`addcomponent.component_origins`, `primitive_id_of`, `discard_selection`'s
    designator leg). The rule is *not* re-stated here: it is the allocator's own
    regex, imported the way `addcomponent.power_flag_kind` imports
    `layout._net_kind` — a second copy of "what a designator is" is how the
    allocator and its readers drift apart, and 143d is exactly a case of one
    reader (the allocator) having a rule the other (<--keep-names>) did not share.

    Needed because `--keep-names` lands a **spec id** as a designator, and a spec
    id is only checked for being non-empty, dot-free and unique
    (`core.circuitspec`) — nothing about it is a number. ``C10?`` in particular is
    the editor's own notation for "not numbered yet", so a part placed under it
    lands on the page and then cannot be read back by anything: the pin read-back
    reports `C10? is not on the page` after two parts are already down.
    """
    return bool(addcomponent._DESIGNATOR_RE.match(name or ""))


def _pool_match(names: Iterable[str], designator: str) -> str:
    """The name in ``names`` that ``designator`` collides with, or ``''`` (143d).

    Collision is judged the way the **allocator** judges occupancy rather than by
    string equality: `addcomponent.allocate_designator` folds the prefix, so a
    page's ``c10`` occupies ``C10``'s number, and `discard_selection` matches a
    page designator case-insensitively (`row["designator"].upper()`), so ``C10``
    beside a page's ``c10`` is one designator with two spellings: a rename mid-run
    *and* a name two readers would each resolve to the same primitive. The check
    this replaces was ``designator in used`` — case-sensitive, so exactly that pair
    went through.
    """
    match = addcomponent._DESIGNATOR_RE.match((designator or "").strip())
    if not match:
        # Not a designator at all: there is no prefix/number to fold, so only an
        # exact match is a collision.
        return designator if designator in list(names) else ""
    wanted = (match.group(1).upper(), int(match.group(2)))
    for name in names:
        other = addcomponent._DESIGNATOR_RE.match((name or "").strip())
        if other and (other.group(1).upper(), int(other.group(2))) == wanted:
            return str(name)
    return ""


def _prefix_of(spec_id: str, profile: SymbolProfile) -> str:
    """The designator prefix a part lands under.

    The spec id's own leading letters when it has any (``R1`` -> ``R``), because
    that is what the design says this part *is*; otherwise the symbol ref's
    leading letters (``R0402`` -> ``R``); otherwise empty, which the caller
    refuses — a part with no prefix cannot be numbered, and inventing one would
    put a resistor under ``U``.
    """
    letters = "".join(character for character in spec_id if character.isalpha())
    if letters:
        return letters.upper()
    ref_letters = "".join(character for character in profile.symbol_ref if character.isalpha())
    return ref_letters.upper()


def assign_designators(
    parts: Sequence[LayoutPart],
    profiles: Mapping[str, SymbolProfile],
    pool: Iterable[str],
    *,
    keep_names: bool = False,
) -> list[tuple[str, str, str]]:
    """``[(partId, prefix, designator)]`` for a drawing, from the pool it avoids.

    The lowest free number per prefix, in plan order, with each allocation added
    to the pool as it is made — two resistors never get one number. The pool is
    `addcomponent.designator_pool`'s answer at the caller's boundary: the page's
    designators **and** the project export's (036b), because the host renames a
    collision mid-run.

    ``keep_names`` (121c, 岳-ruled 2026-10-06) lands every part under its **spec
    id** rather than a freshly allocated number: the ids are the designators the
    engineer reads (``C10`` is ``C10``, not a renumbered ``C3``), and a compiled
    drawing that renumbers them is a drawing nobody can match against the plan
    they approved. It is a *checked* preservation, not an override, and the checks
    are the allocation's own two (143d): the name must **be** a designator
    (:func:`is_designator` — a spec id is only checked for being non-empty,
    dot-free and unique, and ``C10?`` is the editor's "not numbered yet") and it
    must be **free** (a name already in the pool is refused by name, since the host
    would rename it mid-run, 036b). Both refusals are plan-time, naming the part:
    the alternative — a plan whose designators no reader can match — lands the
    parts, fails the pin read-back and leaves half a drawing on the page. A drawing
    that does not want it passes ``keep_names=False`` and gets exactly the old
    numbering.
    """
    used = [name for name in pool]
    out: list[tuple[str, str, str]] = []
    for part in parts:
        profile = profiles.get(part.symbol_ref)
        if profile is None:
            raise DrawPlanError(
                f"part {part.part_id!r} is drawn with symbol {part.symbol_ref!r}, which "
                "the library does not describe"
            )
        prefix = _prefix_of(part.part_id, profile)
        if not prefix:
            raise DrawPlanError(
                f"part {part.part_id!r} (symbol {part.symbol_ref!r}) has no designator "
                "prefix — neither the spec id nor the symbol ref carries one, and a part "
                "cannot be numbered without one"
            )
        if keep_names:
            designator = part.part_id
            # 143d: the two checks a kept name needs, and they are the *same two*
            # the allocator applies to a name it hands out — a kept name is an
            # allocation the spec made instead, so it gets the allocation's rules.
            # (1) it is a designator at all; (2) it is free. Without (1) the run
            # compiles a plan whose designators no reader can match, writes the
            # parts and dies in the pin read-back with a half-landed page.
            if not is_designator(designator):
                raise DrawPlanError(
                    f"part {part.part_id!r} was told to keep its spec id as its "
                    f"designator, but {designator!r} is not a designator — the shape is "
                    "<letters><number> (`R7`, `C10`), which is what "
                    "`addcomponent.allocate_designator` produces and what every reader "
                    "in this repo matches on. A `?`-suffixed name is the editor's own "
                    "'not numbered yet', so a part landed under one cannot be read back "
                    "(the pin read-back reports it missing *after* the parts are placed). "
                    "Give the spec part a designator-shaped id, or drop --keep-names"
                )
            taken = _pool_match(used, designator)
            if taken:
                raise DrawPlanError(
                    f"part {part.part_id!r} was told to keep its spec id as its "
                    f"designator, but {taken} is already on the page or in the "
                    "project export — a kept name that collides is a rename mid-run "
                    "(036b); free the name or drop --keep-names"
                )
            used.append(designator)
            out.append((part.part_id, prefix, designator))
            continue
        designator = addcomponent.allocate_designator(used, prefix)
        used.append(designator)
        out.append((part.part_id, prefix, designator))
    return out


def designator_problems(plan: ChangePlan, pool: Iterable[str]) -> list[str]:
    """Are the plan's numbers still the ones this pool allocates?

    The plan-time question is `module_plan`'s ("which numbers are free?"); this is
    apply's ("are they *still* free, and are they still the ones the pool gives?").
    A human who placed an ``R1`` by hand makes the second answer differ, and a run
    that wrote the plan's numbers anyway would be a run with two ``R1``s (or, worse,
    a part silently renamed mid-run, 036b).

    A **kept-name** plan (121c, ``change.keepNames``) is asked the first question
    only: its designators are the engineer's spec ids, which the pool would never
    *allocate*, so the allocation leg would reject every one of them for the wrong
    reason. What still has to hold is that the name is free — a kept ``C10`` that
    something else already owns is the same rename mid-run. 143d added the other
    half of the same question: a kept name also has to *be* a designator
    (:func:`is_designator`), because a plan whose designators no reader can match is
    a plan that lands half a drawing and then cannot find its own parts.
    """
    pool_list = [name for name in pool]
    problems: list[str] = []
    for part in plan.change.draw_parts:
        if plan.change.draw_keep_names and not is_designator(part.designator):
            problems.append(
                f"{part.designator} is this kept-name plan's designator for "
                f"{part.spec_id}, and it is not a designator (<letters><number>): no "
                "reader in this repo can match it, so the run would place the part and "
                "then fail to read it back — re-plan without --keep-names, or give the "
                "spec part a designator-shaped id"
            )
            continue
        taken = _pool_match(pool_list, part.designator)
        if taken:
            problems.append(
                f"{part.designator} ({part.value}) is already on the page or in the "
                "project export — the plan's number was taken between plan and apply"
            )
    if problems:
        return problems
    if plan.change.draw_keep_names:
        return problems
    for part in plan.change.draw_parts:
        allocated = addcomponent.allocate_designator(pool_list, part.prefix)
        if allocated != part.designator:
            problems.append(
                f"the pool now allocates {allocated} for prefix {part.prefix!r}, but the "
                f"plan says {part.designator} — the page's numbering moved under the plan"
            )
            return problems
        pool_list.append(part.designator)
    return problems


# ------------------------------------------------------------------ the plan


@dataclass
class _Built:
    """What :func:`module_plan` collected while walking the layout."""

    parts: list[PlanDrawPart] = field(default_factory=list)
    wires: list[PlanDrawWire] = field(default_factory=list)
    flags: list[PlanDrawFlag] = field(default_factory=list)
    downgrades: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: 146 — ``spec id -> the boxes the host draws on that part``, as
    #: ``(what it is, box)``: its drawn body plus its own reference/value rows. A
    #: name stub is checked against *these* as well, because the row the host
    #: prints on the stub can land on the symbol the stub belongs to even when
    #: every foreign object is clear (:func:`_name_row_clash`).
    label_owner: dict[str, list[tuple[str, tuple[float, float, float, float]]]] = (
        field(default_factory=dict)
    )



def islands_from_circuit(
    circuit: CircuitSpec,
    designators: Mapping[str, str],
    profiles: Mapping[str, SymbolProfile] | None = None,
) -> list[PlanIsland]:
    """The netlist expectation: every placed pin and the pins it is one with.

    Built from the **CircuitSpec's nets**, mapped onto the designators the plan
    allocated. Membership, never names: an auto-named net is renumbered by the
    editor whenever the wiring changes (measured 035/036), so "these pins are
    one" is the fact the acceptance can compare (037's main judgement shape).

    The mates list **includes the pin itself** — the island *is* that set — and a
    net whose only member is one pin yields a one-element island, which is a true
    statement about a rail carried by a flag.

    **The role-sibling pins are part of the expectation (143 F2).** 060 sec.2
    rules that a role carried on several pins is *one node inside the symbol*, so
    a spec that puts one of them on a net puts the role there — and the compiler
    draws the rest of them on that net, on their own stubs under the same name.
    121's plan-time expectation used to be read off ``net.members`` alone, so the
    plan declared a smaller net than the drawing it came from: `draw apply`'s
    read-back then reported *"U1.2 is on net 'Net2' with ['U1.2', 'U1.4'] …
    but the plan says ['U1.2']"* — a correct drawing judged a disagreement by its
    own plan, exit 3, never saved (the measured AMS1117 double-`VOUT` shape).
    Passing ``profiles`` (the same ``symbolRef -> SymbolProfile`` book the plan was
    built from) adds them, with the two exceptions the compiler's own
    ``_sibling_members`` and readability's ``_role_node_expectations`` apply: a
    pin listed in ``nc[]`` stays off the net, and a pin the spec puts on *another*
    net is left to the `circuit-invalid` refusal rather than silently joined.
    All three now read the one definition, ``core.symbolprofile.role_siblings``.

    Without ``profiles`` the answer is what it always was (the spec's own
    members), so a caller holding only the circuit is unchanged.
    """
    islands: list[PlanIsland] = []
    book = dict(profiles or {})
    for net in circuit.nets:
        spelled = sorted(
            member for member in net.members
            if member.partition(".")[0] in designators
        )
        members = sorted(
            _designator_pin(
                designators, member
            )
            for member in _role_siblings_of_net(circuit, book, net, spelled)
        )
        for member in members:
            islands.append(PlanIsland(pin=member, mates=list(members)))
    return islands


def _designator_pin(designators: Mapping[str, str], member: str) -> str:
    """``<specId>.<pin>`` -> ``<designator>.<pin>`` for the plan's own spelling."""
    part_id, _, pin = member.partition(".")
    return f"{designators[part_id]}.{pin}"


def _named_pin(designators: Mapping[str, str], spelling: str) -> str:
    """The same translation for a sentence, tolerant of a bare pin or ``""``."""
    part_id, _, pin = spelling.partition(".")
    if not pin:
        return spelling
    return f"{designators.get(part_id, part_id)}.{pin}"


def _role_siblings_of_net(
    circuit: CircuitSpec,
    profiles: Mapping[str, SymbolProfile],
    net: Any,
    members: Sequence[str],
) -> list[str]:
    """``members`` plus the role-sibling pins the drawing puts on this net too.

    The rule and both exceptions are `drawcompiler._sibling_members`' own (and
    `readability._role_node_expectations`'): a pin in ``nc[]`` is an explicit
    no-connect and stays off the net, and a pin the spec itself puts on another
    net is the one-role-two-nets contradiction the grammar refuses — nothing is
    invented for it. The spelling of the exceptions is the **spec's**
    (``<partId>.<pin>``, which is what ``nc[]`` entries and ``net.members``
    carry; `grammar.base.nc_pins_of` reads them the same way).
    """
    declared = {member: item.id for item in circuit.nets for member in item.members}
    nc = {item.pin for item in circuit.nc}
    out: list[str] = list(members)
    for member in members:
        part_id, _, token = member.partition(".")
        part = circuit.part(part_id)
        profile = profiles.get(part.symbol_ref) if part is not None else None
        if profile is None:
            continue
        for pin in role_siblings(profile, token):
            spelling = pin.number or pin.name
            if not spelling or f"{part_id}.{spelling}" in nc:
                continue
            here = declared.get(f"{part_id}.{spelling}", declared.get(f"{part_id}.{pin.name}", ""))
            if here and here != net.id:
                continue
            sibling = f"{part_id}.{spelling}"
            if sibling not in out:
                out.append(sibling)
    return sorted(out)


def net_name_problems(layout: LayoutPlan) -> list[str]:
    """Does the drawing claim one conductor is two nets? (143 F5)

    A `LayoutPlan` states net names two ways: **declared** (a `LayoutLabel` or a
    `LayoutPowerSymbol` says "this point is net X") and **claimed** (a
    `LayoutSegment` carries ``net``, and 029-b measured that the host's wire
    carries its own name — which is why `sch.place_wire` is handed exactly this
    string at apply time). Both are statements about the same canvas, so where a
    segment touches a conductor on which another name is declared, one of the two
    is wrong: a node has one name.

    Neither judge the compiler runs sees this: `readability` derives the netlist
    from the **declared** names only (052 sec.4 says so in as many words) and
    `check_grammar` does not read ``segment.net`` at all. Measured 2026-10-10
    (143d): renaming a TAP segment to ``VIN`` in a compiled divider came back
    **hard=0, grammar=0** — a drawing the compiler would have produced happily, and
    one whose landing puts those pins on VIN.

    Connectivity is the same rule `readability._derive` uses (a vertex of one wire
    on another's span is a tee, 054's measured editor behaviour), read here over
    segments and name anchors — pins carry no name of their own, so they are not
    anchors and cannot create a name conflict. Measured against every layout
    document this repo has recorded (847 of them, 10 941 segments, 2026-10-10):
    **zero** conflicts, so the rule refuses a drawing that was edited and not one
    the compiler wrote.
    """
    segments = [segment for segment in layout.segments if len(segment.points) >= 2]
    points = [
        [(float(point[0]), float(point[1])) for point in segment.points]
        for segment in segments
    ]
    anchors: list[tuple[str, tuple[float, float]]] = [
        (str(label.net), (float(label.x), float(label.y)))
        for label in layout.labels if label.net
    ] + [
        (str(symbol.net), (float(symbol.x), float(symbol.y)))
        for symbol in layout.power_symbols if symbol.net
    ]
    parent = list(range(len(segments) + len(anchors)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    for index, own in enumerate(points):
        for other in range(index + 1, len(points)):
            if any(_on_polyline(point, points[other]) for point in own) or any(
                _on_polyline(point, own) for point in points[other]
            ):
                union(index, other)
    for offset, (_net, point) in enumerate(anchors):
        for index, own in enumerate(points):
            if _on_polyline(point, own):
                union(len(segments) + offset, index)

    names: dict[int, set[str]] = {}
    members: dict[int, list[str]] = {}
    for index, segment in enumerate(segments):
        root = find(index)
        names.setdefault(root, set()).add(str(segment.net or ""))
        members.setdefault(root, []).append(
            f"segments[{index}] (net {segment.net!r})"
        )
    for offset, (net, point) in enumerate(anchors):
        root = find(len(segments) + offset)
        names.setdefault(root, set()).add(net)
        members.setdefault(root, []).append(f"the name {net!r} at ({point[0]:g}, {point[1]:g})")

    problems: list[str] = []
    for root, found in names.items():
        claimed = sorted(name for name in found if name)
        if len(claimed) < 2:
            continue
        problems.append(
            "the drawing claims one conductor as "
            + " and ".join(repr(name) for name in claimed)
            + " — "
            + ", ".join(members[root])
            + " meet at a point (this host joins a wire's vertex that lands on "
            "another wire, 054), and a node has one name. `sch.place_wire` is handed "
            "the segment's own net (029-b: a wire's net *is* its name on the canvas), "
            "so whichever of these is not the node's real name lands as the net of a "
            "conductor it does not belong to; nothing else checks it (143 F5: the "
            "readability netlist reads declared names only, 052 sec.4, and "
            "`check_grammar` does not read `segment.net`)"
        )
    return problems


def module_plan(
    layout: LayoutPlan,
    circuit: CircuitSpec,
    presentation: PresentationSpec,
    profiles: Mapping[str, SymbolProfile],
    *,
    candidate_index: int = 0,
    lcsc_by_part: Mapping[str, str] | None = None,
    values_by_part: Mapping[str, str] | None = None,
    pool: Iterable[str] = (),
    baseline: PlanDrawBaseline | None = None,
    baseline_findings: Sequence[str] = (),
    notes: Sequence[str] = (),
    label_stubs: bool = False,
    module_label: str = "",
    keep_names: bool = False,
) -> ChangePlan:
    """One compiled drawing, as the plan a human authorises (054 §四.1).

    Two 057 keywords, and the same reading of a label on either path:

    * ``label_stubs`` — a label this host cannot place is otherwise carried by
      the wire of its net; a page states a shared net with a label at a *pin tip*
      (056's port), and a pin no wire of that net reaches would land on an
      unnamed net, so the two modules' same-named nets would never merge in the
      editor's project-wide netlist (G4). With it, such a label becomes a short
      stub wire carrying the name (:data:`LABEL_STUB_LENGTH`, towards the label's
      own text box) — declared in ``downgrades`` like every other landing
      adaptation. 145d: a **single-module** plan stakes the same stub for a net
      that has a name and *no conductor at all* (GATE/VFB_NF's shape: one pin, one
      label, no wire), which the page path already covers — what it may not do is
      claim the wire carries the name while drawing none;
    * ``module_label`` — how the plan's target names what it draws (a page names
      its modules; the default is the presentation's grammar, as 054 wrote it).

    145d, the last thing every plan does to its wires: a run another wire of the
    same net already covers is dropped, and the wires a flag attaches inside of are
    cut at that point — so no wire end is stated that the host's own collinear merge
    (pit 32) will not keep as a vertex. See :func:`_drop_covered_runs` and
    :func:`_cut_at_flag_attachments`.

    The three things the layout cannot know are settled here, in this order:
    the **recipe** (a symbol ref is not a part: every part needs an LCSC number and
    a value, or the plan is refused naming the parts), the **numbers** (allocated
    from ``pool``, see `assign_designators`; ``keep_names`` lands each part under
    its spec id when the pool is free of it — 121c) and the **flags** (a rail's symbol ref
    becomes the connector's own ``Ground``/``Power`` vocabulary, and a non-rail
    with a flag is refused rather than quietly drawn as something else).

    The library is checked twice on the way out, because two different things can
    be wrong: a symbol the library does not have at all (refused by name), and a
    symbol whose geometry differs from the one the layout was compiled against
    (refused with both hashes). Both are silent failures in the editor — the
    drawing simply comes out with its pins somewhere else.
    """
    if not isinstance(layout, LayoutPlan):
        raise DrawPlanError(f"layout must be a LayoutPlan, got {type(layout).__name__}")
    if not layout.parts:
        raise DrawPlanError(
            "the layout has no parts — a drawing with no parts is not a compilation of "
            "any circuit"
        )
    if not layout.source.circuit_sha256 or not layout.source.presentation_sha256:
        raise DrawPlanError(
            "the layout carries no source digests — a plan that cannot say which specs "
            "it was compiled from cannot be judged stale (053 sec.2)"
        )
    # 143 F5: the drawing's own names, read before anything is built from them.
    # A segment's `net` is not read by either judge the compiler runs
    # (`readability.derive_netlist` states netlist names from labels/symbols by
    # design, 052 sec.4, and `check_grammar` never reads it), while **apply writes
    # it straight onto the canvas** (`sch.place_wire`'s net, 029-b) — so a segment
    # renamed by hand compiles to hard=0 / grammar=0 and lands as a wire carrying a
    # name its own node does not have. This is the check that closes it, at the one
    # place a LayoutPlan becomes executable.
    name_problems = net_name_problems(layout)
    if name_problems:
        raise DrawPlanError("; ".join(name_problems))
    book = {str(key): value for key, value in dict(profiles).items()}
    table = profile_table(book)
    known = {ref for ref, _digest in table}
    lcsc = {str(key): str(value) for key, value in dict(lcsc_by_part or {}).items()}
    values = {str(key): str(value) for key, value in dict(values_by_part or {}).items()}

    built = _Built(notes=list(notes))
    # 143 F1: a degradation the *compiler* had to make is a degradation the
    # reader authorising this plan is entitled to see. `_build_candidate` marks
    # those notes with `DOWNGRADE_NOTE_PREFIX` (the one spelling both modules
    # import), and they are copied into `downgrades` — the list `draw plan`
    # prints as `downgrade:` — with the marker dropped. Notes that are not marked
    # describe the drawing and stay notes.
    built.downgrades.extend(
        note[len(DOWNGRADE_NOTE_PREFIX):]
        for note in layout.notes
        if note.startswith(DOWNGRADE_NOTE_PREFIX)
    )
    for ref in sorted({part.symbol_ref for part in layout.parts}):
        if ref not in known:
            # The compiler already refuses a library gap; this is the check that
            # the *plan* is not built from a different book than the layout was.
            raise DrawPlanError(
                f"the layout is drawn with symbol {ref!r}, which the library handed to "
                f"this plan does not describe (it holds {', '.join(sorted(known))}) — "
                "compile and land against the same library"
            )
        profile = book[ref]
        digest = profile.geometry_hash()
        recorded = {part.symbol_hash for part in layout.parts if part.symbol_ref == ref}
        if any(item != digest for item in recorded):
            raise DrawPlanError(
                f"the layout was compiled against a {ref!r} whose geometry hashes to "
                f"{sorted(recorded)[0]!r}, but the library here hashes it to {digest!r} "
                "— the pins would land somewhere nobody laid out"
            )

    assignments = assign_designators(
        list(layout.parts), book, pool, keep_names=keep_names
    )
    for part, (part_id, prefix, designator) in zip(layout.parts, assignments):
        profile = book[part.symbol_ref]
        spec_part = circuit.part(part_id)
        if spec_part is None:
            raise DrawPlanError(
                f"the layout places {part_id!r}, which the circuit spec does not "
                "declare — the two documents disagree"
            )
        number = lcsc.get(part_id) or spec_part.lcsc
        if not number:
            raise DrawPlanError(
                f"{part_id} has no LCSC number: the circuit spec states none and no "
                f"`--lcsc {part_id}=Cxxxxx` was given. A compiled drawing places library "
                "devices, and an unverified part is never placed silently (029 §二.2)"
            )
        value = values.get(part_id) or spec_part.value
        if not value:
            raise DrawPlanError(
                f"{part_id} has no value: the circuit spec states none and no "
                f"`--value {part_id}=10k` was given — the value is what the read-back "
                "and the human reviewing the plan compare"
            )
        built.parts.append(PlanDrawPart(
            spec_id=part_id,
            designator=designator,
            prefix=prefix,
            lcsc=number,
            value=value,
            # 055 G2: the design value is what lands in the editor's own `Value`
            # attribute. The CircuitSpec's value *is* the design intent — the MPN
            # is a part number, not a value — so a plan that only recorded it would
            # leave the placed part with the library device's name and an empty
            # Value (measured 054 C3), and every value-reading rule would have to
            # fall back to the MPN's EIA code.
            value_key=DRAW_VALUE_KEY,
            footprint=spec_part.params.get("footprint", "") if spec_part.params else "",
            symbol_ref=part.symbol_ref,
            symbol_hash=profile.geometry_hash(),
            x=part.x,
            y=part.y,
            rotation=part.rotation,
            mirror=part.mirror,
            pins=[
                PlanDrawPin(number=pin, dx=offset[0], dy=offset[1])
                for pin, offset in sorted(
                    posed_pin_offsets(profile, part.rotation, part.mirror).items()
                )
            ],
        ))

    tips = {
        item.spec_id: expected_pin_points(item) for item in built.parts
    }

    def pin_at(point: tuple[float, float]) -> str:
        """``<specId>.<pin>`` when a point is exactly one of the plan's pin tips."""
        for spec_id, table_for_part in sorted(tips.items()):
            for number, spot in sorted(table_for_part.items()):
                if abs(spot[0] - point[0]) < 1e-6 and abs(spot[1] - point[1]) < 1e-6:
                    return f"{spec_id}.{number}"
        return ""

    for segment in layout.segments:
        if len(segment.points) < 2:
            raise DrawPlanError(
                f"net {segment.net!r} has a segment with {len(segment.points)} point(s) "
                "— a segment is at least two, or it draws nothing"
            )
        built.wires.append(PlanDrawWire(
            net=segment.net,
            points=[(point[0], point[1]) for point in segment.points],
            from_pin=pin_at(segment.points[0]),
        ))

    for symbol in layout.power_symbols:
        kind = flag_kind(symbol.net, symbol.symbol_ref)
        if not kind:
            raise DrawPlanError(
                f"the drawing places a {symbol.symbol_ref!r} flag on net {symbol.net!r}, "
                "which is neither a ground nor a supply name and is not one of this "
                "repo's rail-flag symbols — this host's flag vocabulary cannot name that "
                "net (029-d), and a flag of the wrong kind would misname the net in the "
                "editor's own netlist"
            )
        built.flags.append(PlanDrawFlag(
            net=symbol.net,
            kind=kind,
            symbol_ref=symbol.symbol_ref,
            symbol_hash=symbol.symbol_hash,
            x=symbol.x,
            y=symbol.y,
            rotation=symbol.rotation,
            on_pin=pin_at((symbol.x, symbol.y)),
        ))
        if symbol.symbol_hash:
            if symbol.symbol_ref not in known:
                raise DrawPlanError(
                    f"the drawing places a {symbol.symbol_ref!r} flag, which the library "
                    "handed to this plan does not describe — the flag's geometry would "
                    "be unverifiable at apply time"
                )
            expected = dict(table)[symbol.symbol_ref]
            if symbol.symbol_hash != expected:
                raise DrawPlanError(
                    f"the {symbol.symbol_ref!r} flag the drawing places was laid out "
                    f"against a symbol hashing to {symbol.symbol_hash!r}, but the library "
                    f"here hashes it to {expected!r}"
                )

    # 143 F3, the same namespace as the postconditions: `on_pin` is a spec id by
    # contract, and the note that lists it is read beside designators.
    designator_of = {part.spec_id: part.designator for part in built.parts}
    on_pins = {
        (_named_pin(designator_of, flag.on_pin) or flag.net)
        for flag in built.flags if flag.on_pin
    }
    #: What a name stub may not touch (099d): every placed part's drawn body and
    #: every one of its pins, computed once for the whole label pass. A stub is a
    #: wire, so a foreign pin under it is a connection and a foreign body under it
    #: is `readability`'s wire-through-body — neither is re-checked after this
    #: layer, which is why the check lives here.
    stub_bodies: dict[str, tuple[float, float, float, float]] = {}
    for part in built.parts:
        profile = profiles.get(part.symbol_ref)
        if profile is None or profile.body is None:
            continue
        pose = SymbolPose(rotation=int(part.rotation) % 360, mirror=part.mirror)
        x0, y0, x1, y1 = profile.body
        corners = [
            transform_point(cx, cy, rotation=pose.rotation, mirror=pose.mirror,
                            ox=part.x, oy=part.y)
            for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        ]
        stub_bodies[part.designator] = (
            min(point[0] for point in corners), min(point[1] for point in corners),
            max(point[0] for point in corners), max(point[1] for point in corners),
        )
    stub_pins: list[tuple[str, str, tuple[float, float]]] = [
        (part.designator, number, point)
        for part in built.parts
        for number, point in expected_pin_points(part).items()
    ]
    #: 146: the part each label names a pin of — its drawn body and its own text
    #: rows. Passed to the stub chooser because the **name the host draws** on the
    #: stub can land on that part even when every foreign object is clear: the run
    #: is checked against other nets and other parts, the glyphs were not checked
    #: against the symbol they belong to.
    for text in layout.texts:
        if text.part_id and text.bbox:
            built.label_owner.setdefault(text.part_id, []).append(
                (f"{text.kind} text {text.text!r} of {text.part_id}", text.bbox)
            )
    for part_id, owner in built.label_owner.items():
        body = stub_bodies.get(designator_of.get(part_id, part_id))
        if body is not None:
            owner.append((f"the drawn body of {part_id}", body))
    for label in layout.labels:
        covered = any(flag.net == label.net for flag in built.flags)
        if covered:
            built.notes.append(
                f"net {label.net}: the label the compiler drew is not placed separately — "
                "the rail flag carries the same name in the editor's netlist"
            )
            continue
        anchor = (label.x, label.y)
        carried = any(
            wire.net == label.net and _on_polyline(anchor, wire.points)
            for wire in built.wires
        )
        # 145d: a net that carries a name and **no conductor at all** is stubbed on
        # a single-module plan too, not only on the page path (057 sec.4). GATE
        # (Q1.1) and VFB_NF (R10.1) are the measured shape: one pin, one label, no
        # wire of the net anywhere — and the branch below used to *state* that the
        # wire carries the name while drawing no wire, so the editor's netlist held
        # neither the name nor the pin (`netlist_after_apply.json`: GATE and VFB_NF
        # appear zero times, 145c sec.5.3). `bare` is that fact and nothing wider: a
        # net that already has a conductor keeps exactly the behaviour it had (the
        # label's anchor is on one of its wires, or 057's own `label_stubs` decides).
        bare = not any(wire.net == label.net for wire in built.wires)
        if (label_stubs or bare) and not carried:
            stub, blockers = _place_label_stub(
                label, built, stub_bodies, stub_pins,
            )
            if stub is None:
                # 099d: a stub that lands on another net is a short in this host's
                # netlist (measured: the V3 wire merged into RXD and the live
                # netlist read the two as one). Drawing it anyway is exactly the
                # silent failure this refusal replaces.
                raise DrawPlanError(
                    f"net {label.net}: the label at ({label.x:g}, {label.y:g}) has no "
                    "free name stub (057 sec.4) — a stub that lands on or crosses "
                    "another net's conductor shorts the two in this host's netlist "
                    "(099d, measured on the CH340 page), so no run was drawn; every "
                    "candidate is blocked: " + "; ".join(blockers)
                )
            length = sum(
                math.dist(head, tail)
                for head, tail in zip(stub, stub[1:])
            )
            drawn = " → ".join(f"({point[0]:g}, {point[1]:g})" for point in stub)
            bent_note = (
                ""
                if len(stub) == 2 else
                " (bent: one lattice step aside first, 099f — every straight run "
                "out of this pin was blocked, and this puts the name back on the "
                "side the label's box is on)"
            )
            built.wires.append(PlanDrawWire(
                net=label.net,
                points=[anchor, *stub[1:]],
                from_pin=pin_at(anchor),
                purpose="name stub (057: stands in for a label this host cannot place)",
            ))
            built.downgrades.append(
                f"net {label.net}: the compiler drew a net label at "
                f"({label.x:g}, {label.y:g}), and this host cannot place one "
                "(`sch.place_netlabel` is measured unusable, 029); no planned wire of "
                f"{label.net} reaches that point, so a {length:g}-unit stub "
                f"{drawn} carries the "
                "name instead — without it the pin would sit on an unnamed net and the "
                "page's same-named nets would never merge in the editor's project-wide "
                "netlist (057 sec.4)" + bent_note
            )
            continue
        # 145d: the two cases that reach here are *checked* ones, and the sentence
        # says which it is. `carried` means a planned wire of this net runs through
        # the label's own anchor — the name is on that conductor. The other case is
        # a net that keeps conductors elsewhere and a label whose anchor none of
        # them reaches: the name is on those wires, and this anchor is *not* stubbed
        # (that is what `bare` above decides for the no-conductor-at-all one), so
        # the sentence must not promise a stub the plan does not draw.
        built.downgrades.append(
            f"net {label.net}: the compiler drew a net label at "
            f"({label.x:g}, {label.y:g}), and this host cannot place one "
            "(`sch.place_netlabel` is measured unusable, 029) — "
            + (
                f"a planned wire of {label.net} runs through that point, and the net is "
                "named on that conductor (`sch.place_wire` net=…), so the netlist "
                "carries the name while the canvas shows the wire without a label text"
                if carried else
                f"other planned wire(s) of {label.net} carry the name "
                "(`sch.place_wire` net=…), so the netlist carries it, while this "
                "anchor itself draws nothing: no wire of the net reaches it and "
                "this plan does not stub it (a net with conductors keeps the "
                "behaviour it had — 145d)"
            )
        )
    # 145d, after every wire the plan will draw is known (the label stubs above
    # included): drop the runs another wire of the same net already covers, then cut
    # the wires a flag attaches inside of, so every wire end the plan states is a
    # vertex the page keeps.
    _drop_covered_runs(built)
    _cut_at_flag_attachments(built, pin_at)
    if layout.junctions:
        built.notes.append(
            f"{len(layout.junctions)} junction(s) are expected where the drawing tees; "
            "the editor draws those itself, and `sch.geometry` has no junction section, "
            "so this batch does not claim to verify them"
        )
    if layout.texts:
        built.notes.append(
            f"{len(layout.texts)} text box(es) in the layout are the editor's own "
            "annotations (designator and value are drawn by the host when a part is "
            "placed); C1 places no text primitive, so the drawn text is the host's"
        )
    if on_pins:
        built.notes.append(
            "flags sit on pins: " + ", ".join(sorted(on_pins))
        )

    islands = islands_from_circuit(
        circuit,
        {item.spec_id: item.designator for item in built.parts},
        book,
    )
    if not islands:
        raise DrawPlanError(
            "the circuit spec declares no nets with a pin of a placed part — there is "
            "nothing for the live netlist to be compared against, and 037's main "
            "judgement would have nothing to say"
        )
    placeholders = sorted({member for island in islands for member in island.mates})
    declared = {
        f"{item.designator}.{pin.number}" for item in built.parts for pin in item.pins
    }
    missing = [member for member in placeholders if member not in declared]
    if missing:
        # A spec member the pin table does not carry is a fact about the *library*
        # (a pin number the profile does not have), and it would make an island
        # expectation apply can never satisfy.
        raise DrawPlanError(
            "the circuit spec connects pin(s) the library symbol does not carry: "
            + ", ".join(sorted(missing))
            + " — the drawing would have a net with a member that does not exist"
        )

    digest = source_digest(
        layout.source.circuit_sha256,
        layout.source.presentation_sha256,
        layout.geometry_sha256(),
        candidate_index,
        table,
    )
    recorded = baseline or PlanDrawBaseline()
    if baseline_findings:
        # A plan that carries the findings it was built against has read them —
        # said here rather than left to the caller, because "no baseline was read"
        # and "the baseline was empty" are different claims (036's rule) and only
        # this flag tells apply which one it is holding.
        recorded.findings_read = True
    module_line = ", ".join(sorted(net.id for net in circuit.nets))
    return ChangePlan(
        source=PlanSource(
            input_sha256=digest,
            page_uuid=(baseline.page_uuid if baseline is not None else ""),
        ),
        target=PlanTarget(
            module=f"{module_label or presentation.grammar_ref} "
            f"({len(built.parts)} part(s); nets {module_line})",
        ),
        change=PlanChange(
            kind=DRAW_MODULE_KIND,
            candidate=int(candidate_index),
            layout_sha256=layout.geometry_sha256(),
            circuit_sha256=layout.source.circuit_sha256,
            presentation_sha256=layout.source.presentation_sha256,
            profile_hashes=table,
            draw_parts=built.parts,
            draw_wires=built.wires,
            draw_flags=built.flags,
            islands=islands,
            draw_baseline=recorded,
            draw_downgrades=built.downgrades,
            draw_notes=built.notes,
            baseline_findings=[str(item) for item in baseline_findings],
            draw_keep_names=bool(keep_names),
        ),
        preconditions=_preconditions(built, baseline, baseline_findings),
        expected_postcondition=_postconditions(built, islands),
    )


def _label_stub(label: Any) -> tuple[float, float]:
    """The far end of a label's name stub: out of the anchor, towards its text.

    The direction is the one the compiler put the text box in (the anchor is the
    electrical point, the box is where the room was reserved), read off the box's
    centre along its dominant axis; the length is :data:`LABEL_STUB_LENGTH`, or
    the box's own reach in that direction when that is shorter — never less than
    one lattice step, and always a whole number of them, so the stub's end stays
    on the lattice the anchor is on.

    099d: this is the **preferred** candidate only. A stub that lands on or
    crosses another net's conductor is a short in this host's netlist (measured:
    the V3 wire merged into RXD), so :func:`_place_label_stub` tries the other
    directions, the other lengths and 099f's bent runs, and refuses the drawing
    when none is free.
    """
    run = _label_stub_candidates(label)[0]
    return run.points[-1]


def _label_stub_candidates(label: Any) -> list[_StubRun]:
    """The runs a label's name stub is tried as, preferred and simplest first.

    Three rungs, and the order is the whole point of it:

    1. **straight, preferred first** — the label's own text side at
       :data:`LABEL_STUB_LENGTH` (or the box's reach when that is shorter), then
       the same length along the rest of the compass, then the
       :data:`LABEL_STUB_LENGTHS` rungs in all four directions. A drawing whose
       stub was free before lands on exactly the point 057 gave it (099d's
       zero-movement rule);
    2. **bent, towards the label** (099f) — one perpendicular step out
       (:data:`LABEL_STUB_STEPS`) and then the same length ladder along the
       preferred side, for the case a straight run cannot get out at all: 099e's
       RXD had a foreign wire one lattice step from its pin, every straight rung
       landed on it, and the only free straight run left pointed *into* the
       symbol. The bent run is the shape a human draws there (069 sec.10's flag
       lead), and it puts the name back on the side the label's box is on;
    3. nothing else: a stub that can take none of them is refused, never drawn
       across another net's conductor.

    Each segment of a bent run is checked on its own — a two-segment run that is
    clear at the corner and blocked on the far leg is blocked, not half-drawn.
    """
    x, y = float(label.x), float(label.y)
    box = label.bbox
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    dx, dy = cx - x, cy - y
    if abs(dx) >= abs(dy) and abs(dx) > 1e-9:
        preferred = (1.0 if dx > 0 else -1.0, 0.0)
        reach = (box[2] - x) if dx > 0 else (x - box[0])
    elif abs(dy) > 1e-9:
        preferred = (0.0, 1.0 if dy > 0 else -1.0)
        reach = (box[3] - y) if dy > 0 else (y - box[1])
    else:
        preferred, reach = (0.0, 1.0), LABEL_STUB_LENGTH
    shortest = max(DRAW_GRID, (min(LABEL_STUB_LENGTH, max(DRAW_GRID, reach))
                               // DRAW_GRID) * DRAW_GRID)
    lengths: list[float] = []
    for rung in (shortest, *LABEL_STUB_LENGTHS):
        if rung not in lengths:
            lengths.append(rung)
    directions = [preferred] + [
        item for item in _LABEL_STUB_DIRECTIONS if item != preferred
    ]
    anchor = (x, y)
    out: list[_StubRun] = []
    # The label's own side, straight — 057's rung, and the *first* candidate, so
    # a drawing whose stub was free lands on exactly the point 057 gave it.
    for length in lengths:
        far = (round(x + preferred[0] * length, 6),
               round(y + preferred[1] * length, 6))
        out.append(_StubRun(
            points=(anchor, far), side=preferred,
            shape=f"{_direction_text(preferred)} {length:g}",
            family=f"straight {_direction_text(preferred)}",
        ))
    # Then the bent runs, before any straight run that would carry the name to
    # another side of the pin (099f): "aside one step, then out to the label" is
    # where the label's box is, and 099e measured what the alternative looks
    # like — a 5-unit stub into the symbol, with the host drawing the name over
    # its own edge.
    across = (0.0, 1.0) if preferred[0] != 0.0 else (1.0, 0.0)
    for step in LABEL_STUB_STEPS:
        for sign in (1.0, -1.0):
            corner = (round(x + across[0] * sign * step, 6),
                      round(y + across[1] * sign * step, 6))
            for length in lengths:
                far = (round(corner[0] + preferred[0] * length, 6),
                       round(corner[1] + preferred[1] * length, 6))
                step_side = _direction_text((across[0] * sign, across[1] * sign))
                out.append(_StubRun(
                    points=(anchor, corner, far), side=preferred,
                    shape=(
                        f"{step_side} {step:g} then "
                        f"{_direction_text(preferred)} {length:g}"
                    ),
                    family=f"bent {step_side} then {_direction_text(preferred)}",
                ))
    # Only then the rest of the compass: a stub on another side of the pin still
    # names the net, which is what the stub is for.
    for length in lengths:
        for direction in directions[1:]:
            far = (round(x + direction[0] * length, 6),
                   round(y + direction[1] * length, 6))
            out.append(_StubRun(
                points=(anchor, far), side=direction,
                shape=f"{_direction_text(direction)} {length:g}",
                family=f"straight {_direction_text(direction)}",
            ))
    return out


def _stub_inside_body(
    start: tuple[float, float],
    end: tuple[float, float],
    body: tuple[float, float, float, float],
) -> bool:
    """Does the run pass **through** the box, rather than touch its outline?

    `readability`'s own ruler for a wire against a part: strictly interior on both
    axes, so a run along a body's edge (or starting on it) is not a crossing.
    """
    x0, y0, x1, y1 = body
    lo_x, hi_x = sorted((start[0], end[0]))
    lo_y, hi_y = sorted((start[1], end[1]))
    return hi_x > x0 and lo_x < x1 and hi_y > y0 and lo_y < y1


def _label_stub_blocked(
    label: Any,
    start: tuple[float, float],
    end: tuple[float, float],
    built: "_Built",
    bodies: Mapping[str, tuple[float, float, float, float]],
    pins: Sequence[tuple[str, str, tuple[float, float]]],
) -> str | None:
    """Why this stub run may not be drawn, or ``None`` when it is free.

    074's ruler for a lead, plus the *touching* cases 074 leaves to the router: a
    name stub exists only to carry a net's name, so **crossing** a foreign wire and
    **landing** on one are the same defect here — the editor merges either into one
    node (099c's measured short: the V3 route's corner sat on the RXD stub's span,
    and the live netlist joined V3 into RXD). Own net's wires and own anchor are
    not obstacles: a stub may share a point with its own net, that is a junction.

    Parts are checked as their drawn bodies (strict interior, the readability
    ruler) and as their **pin points**: a run through a foreign pin is a
    connection to that net, whichever machine drew it.
    """
    net = label.net
    for wire in built.wires:
        if wire.net == net:
            continue
        for a, b in zip(wire.points, wire.points[1:]):
            crossing = _segment_crossing(start, end, a, b)
            if crossing is not None:
                return (
                    f"it crosses net {wire.net}'s wire {_point_pair(a, b)} at "
                    f"{_point_pair(crossing, crossing)}"
                )
            if _on_polyline(end, [a, b]) or _on_polyline(start, [a, b]):
                return (
                    f"it lands on net {wire.net}'s wire {_point_pair(a, b)}"
                )
            for point in (a, b):
                if _on_polyline(point, [start, end]):
                    return (
                        f"it runs through net {wire.net}'s wire end "
                        f"{_point_pair(point, point)}"
                    )
    for part_id, pin, point in pins:
        if _near(point, start, 1e-6):
            continue
        if _on_polyline(point, [start, end]):
            return f"it runs through {part_id}.{pin}'s pin at {_point_pair(point, point)}"
    for part_id, body in bodies.items():
        if _stub_inside_body(start, end, body):
            return (
                f"it runs through the drawn body of {part_id} "
                f"{_point_pair((body[0], body[1]), (body[2], body[3]))}"
            )
    return None


def _name_row_clash(
    label: Any,
    run: "_StubRun",
    own: Sequence[tuple[str, tuple[float, float, float, float]]],
) -> str | None:
    """Does the run's own net-name row land on the part it names? (146)

    ``own`` is the part's drawn body and its own text rows, as
    ``(what, box)``. The host does not let this layer place a wire's net name —
    it anchors the text at the midpoint of the run's longest straight piece,
    start-anchored, so a short stub's name overhangs the stub's far end and a
    stub that leaves a pin *towards* its own symbol prints the name across that
    symbol. Measured on the 145e render: `Q1`'s GATE stub is 10 units long, the
    host draws `GATE` from (165, 540) to (192.2, 550), and Q1's own body starts
    at x = 180 — 12.2 x 10 units of glyph on the transistor
    (`outputs/145e/render_P1.svg`, the one defect of 岳's 146 round that the
    landed page shows and the compiler could not see).

    The rule is the *name row*, not the run: the run is already checked against
    every foreign body and pin by :func:`_label_stub_blocked`, and a stub whose
    conductor is free can still print its name over the part it belongs to. A
    candidate that clashes is not refused — the ladder tries the next rung, and a
    longer stub moves the row's start away from the symbol.
    """
    if not own:
        return None
    box = textmetrics.wire_name_box([tuple(run.points[0]), *run.points[1:]],
                                    str(label.net))
    if box is None:
        return None
    for what, other in own:
        if (
            min(box[2], other[2]) - max(box[0], other[0]) > 0.0
            and min(box[3], other[3]) - max(box[1], other[1]) > 0.0
        ):
            return (
                f"the host draws the name {label.net!r} in "
                f"{_box_text(box)} and that row lands on {what} "
                f"{_box_text(other)} — the stub's own conductor is free, the "
                "glyphs are not (146)"
            )
    return None


def _box_text(box: tuple[float, float, float, float]) -> str:
    return f"({box[0]:g}, {box[1]:g})-({box[2]:g}, {box[3]:g})"


def _place_label_stub(
    label: Any,
    built: "_Built",
    bodies: Mapping[str, tuple[float, float, float, float]],
    pins: Sequence[tuple[str, str, tuple[float, float]]],
) -> tuple[tuple[tuple[float, float], ...] | None, list[str]]:
    """The first free stub run (anchor first), or ``(None, blockers)``.

    Every *segment* of a candidate is checked on its own (099f): a bent run that
    is clear at its corner and blocked on its far leg is blocked, never half
    drawn, and a straight run is the one-segment case of the same walk.

    ``built.label_owner`` is the part this label names a pin of — its drawn body
    and its own text rows — checked as the **name row** the host will draw (146,
    :func:`_name_row_clash`): a stub whose conductor is free of every foreign
    object can still print its name over its own symbol.

    ``blockers`` names what stopped each rung's preferred run — one line per
    shape (the four straight directions, then the two bends towards the label) —
    so "it could not be drawn" arrives with the geometry that made it so
    (053 sec.4's four categories, at page scale).
    """
    start = (float(label.x), float(label.y))
    blockers: list[str] = []
    seen_shape: set[str] = set()
    clear: list["_StubRun"] = []
    for run in _label_stub_candidates(label):
        reason = None
        for head, tail in zip(run.points, run.points[1:]):
            reason = _label_stub_blocked(label, head, tail, built, bodies, pins)
            if reason is not None:
                break
        if reason is None:
            clear.append(run)
        elif run.family not in seen_shape:
            seen_shape.add(run.family)
            far = run.points[-1]
            blockers.append(
                f"{run.shape} ({_point_pair(far, far)}): {reason}"
            )
    # 146: among the runs whose **conductor** is free, prefer one whose net-name
    # row is free too — the host prints the name at the run's own midpoint and a
    # short stub towards its own symbol puts the glyphs on that symbol (Q1's GATE
    # at 10 units: 12.2 x 10 units of `GATE` on the transistor, 145e). A clash is
    # a *worse drawing*, not a short, so a page where every clear run clashes
    # keeps the run the pre-146 code chose rather than refusing the plan: the
    # CH340 page's RXD pin sits 9.5 units from U1's body and had exactly that.
    own = built.label_owner.get(label.part_id, ())
    for run in clear:
        if _name_row_clash(label, run, own) is None:
            return run.points, blockers
    if clear:
        first = clear[0]
        far = first.points[-1]
        clash = _name_row_clash(label, first, own) or ""
        blockers.append(f"{first.shape} ({_point_pair(far, far)}): {clash}")
        return first.points, blockers
    return None, blockers


def _direction_text(direction: tuple[float, float]) -> str:
    return {
        (1.0, 0.0): "right", (0.0, 1.0): "up", (-1.0, 0.0): "left",
        (0.0, -1.0): "down",
    }.get(direction, f"{direction[0]:g},{direction[1]:g}")


def _point_pair(a: tuple[float, float], b: tuple[float, float]) -> str:
    return f"({a[0]:g}, {a[1]:g})-({b[0]:g}, {b[1]:g})"


def _segment_crossing(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> tuple[float, float] | None:
    """Where the two runs cross **through** each other, or ``None``.

    :func:`boardwise.engines.drawcompiler._proper_crossing`'s ruler (074's), stated
    here because this layer is a different module: strictly interior to both runs,
    so a shared endpoint, a tee and a collinear overlap are *not* crossings — the
    caller tests those separately, because for a name stub they are connections.
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
    return (round(a[0] + t * (b[0] - a[0]), 6), round(a[1] + t * (b[1] - a[1]), 6))


# ------------------------------------- 145d: the plan's own vertices are real ones
#
# Two adaptations a plan makes to the geometry the compiler drew, both about one
# measured fact: **the host merges collinear wires and keeps a vertex only where a
# run ends or something other than a straight run attaches** (pit 32 — touching wires
# come back as one primitive; measured again on 145c's landed page, where the SEC_12V
# flag's lead `(280,760) → (280,785)` was absorbed into the trunk it overlaps: the
# merged primitive lists the vertices 710/785/790 and *not* 760).
#
# The canvas leg asks exactly one thing of each planned wire (`_wire_problems`): that
# both of its ends are vertices of the page's own wiring for that net. So the plan may
# not promise a run the page will not hold, nor an end the host will merge away.
#
# * a run **another wire of the same net already covers** is not drawn: it adds no
#   conductor the page does not already have, and the host absorbs it (145c measured);
# * the points a **flag** attaches at — its own anchor, and the far end of its lead —
#   become genuine vertices by cutting the wire they land inside of in two (two wires,
#   one net, connected at the cut). Measured: the page keeps a node where a flag
#   attaches (145c's `(280,785)` survives the merge while `(280,760)`, attached to
#   nothing, does not), so the cut is a vertex the read-back finds.


def _covers(wire: PlanDrawWire, other: PlanDrawWire) -> bool:
    """Does ``other``'s polyline pass through **every** point of ``wire``?"""
    if len(other.points) < 2:
        return False
    return all(_on_polyline(point, other.points) for point in wire.points)


def _drop_covered_runs(built: "_Built") -> None:
    """145d: a planned run another wire of the same net already covers is dropped.

    Its geometry is already on the page, so dropping it draws nothing away — while
    keeping it would add a wire whose ends the host is measured not to keep: 145c's
    `SEC_12V (280,760) → (280,785)` was drawn on top of the rail's own run and came
    back merged into it, so `(280,760)` was no vertex of the page and the canvas leg
    refused the landing over a run that had drawn nothing at all.

    A flag's anchor is a conductor (the flag is placed *on* the wire that reaches
    it), so a drop may not take the last wire under one: such a wire is kept and the
    reason is said out loud. Two wires that cover each other (identical runs) drop
    the later one, never both.
    """
    wires = built.wires
    doomed: list[int] = []
    for index, wire in enumerate(wires):
        for other_index, other in enumerate(wires):
            if other_index == index or other.net != wire.net:
                continue
            if not _covers(wire, other):
                continue
            if other_index > index and _covers(other, wire):
                # Identical runs: the earlier one is the run, the later is the copy.
                continue
            doomed.append(index)
            break
    if doomed:
        anchors = [
            (flag.net, (round(flag.x, 6), round(flag.y, 6)))
            for flag in built.flags if flag.net and not flag.on_pin
        ]
        for index in list(doomed):
            wire = wires[index]
            under = [
                (net, spot) for net, spot in anchors
                if net == wire.net and _on_polyline(spot, wire.points)
            ]
            if not under:
                continue
            carried_elsewhere = all(
                any(
                    other_index != index and other_index not in doomed
                    and other.net == net
                    and _on_polyline(spot, other.points)
                    for other_index, other in enumerate(wires)
                )
                for net, spot in under
            )
            if carried_elsewhere:
                continue
            doomed.remove(index)
            built.notes.append(
                f"net {wire.net}: the run {_point_pair(wire.points[0], wire.points[-1])} "
                "is covered by another wire of the same net, but a flag of this net "
                "anchors on it and nowhere else — it is kept rather than dropped "
                "(145d: a flag is placed on the wire that reaches it)"
            )
        for index in sorted(doomed, reverse=True):
            wire = wires.pop(index)
            built.downgrades.append(
                f"net {wire.net}: the planned run "
                f"{_point_pair(wire.points[0], wire.points[-1])} is already covered by "
                "another wire of the same net, so it draws no conductor the page does "
                "not already have — and this host merges collinear wires, so its ends "
                "would not be vertices of the page (measured 145c: this very run "
                "vanished into the rail it overlaps); it is not drawn (145d)"
            )


def _strictly_inside(
    point: tuple[float, float], points: Sequence[tuple[float, float]]
) -> bool:
    """Is `point` on one of the polyline's segments, strictly between its ends?"""
    for start, end in zip(points, points[1:]):
        if _near(point, start, 1e-6) or _near(point, end, 1e-6):
            continue
        if _on_polyline(point, [start, end]):
            return True
    return False


def _cut_polyline(
    wire: PlanDrawWire,
    cuts: Sequence[tuple[float, float]],
    pin_at,
) -> list[PlanDrawWire]:
    """The wire as two or more pieces, cut at each point strictly inside a segment.

    The pieces carry the same net and share the cut point, so the drawing they
    describe is the drawing the wire described — the cut only names the point
    (145d: a vertex the read-back can find). ``from_pin`` is recomputed per piece,
    because a cut may land on one of the plan's own pin tips, and ``purpose`` is
    the run's: the first piece keeps it.
    """
    expanded: list[tuple[float, float]] = [wire.points[0]]
    cut_flags: list[bool] = [False]
    for start, end in zip(wire.points, wire.points[1:]):
        for point in sorted(
            (cut for cut in cuts if _strictly_inside(cut, [start, end])),
            key=lambda cut: math.dist(start, cut),
        ):
            expanded.append(point)
            cut_flags.append(True)
        expanded.append(end)
        cut_flags.append(False)
    pieces: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = [expanded[0]]
    for point, is_cut in zip(expanded[1:], cut_flags[1:]):
        current.append(point)
        if is_cut:
            pieces.append(current)
            current = [point]
    if current:
        pieces.append(current)
    return [
        PlanDrawWire(
            net=wire.net,
            points=points,
            from_pin=(wire.from_pin if index == 0 else pin_at(points[0])),
            purpose=(wire.purpose if index == 0 else ""),
        )
        for index, points in enumerate(pieces)
    ]


def _cut_at_flag_attachments(built: "_Built", pin_at) -> None:
    """145d: make every point a flag attaches at a vertex of the plan's own wires.

    Two points per flag: its **anchor** (where the flag stands) and the far end of
    its **lead** (the run the compiler drew out to that anchor) — the second only
    when the lead survives :func:`_drop_covered_runs`, i.e. when it is a real run
    perpendicular to the wire it leaves. Either point may land *inside* another wire
    of the net (the rail the flag hangs off, or the branch the lead leaves), and
    then the wire it lands inside is cut in two there, so the plan states the point
    the page will hold as a node (two wires, one net, connected — the same thing the
    compiler's own `junctions` list promises for a wire tee, 053 sec.2 constraint 3).
    """
    attachments: dict[str, set[tuple[float, float]]] = {}
    for flag in built.flags:
        if not flag.net:
            continue
        spot = (round(flag.x, 6), round(flag.y, 6))
        attachments.setdefault(flag.net, set()).add(spot)
        for wire in built.wires:
            if wire.net != flag.net or len(wire.points) < 2:
                continue
            if _near(wire.points[0], spot, 1e-6):
                attachments[flag.net].add(wire.points[-1])
            elif _near(wire.points[-1], spot, 1e-6):
                attachments[flag.net].add(wire.points[0])
    out: list[PlanDrawWire] = []
    for wire in built.wires:
        cuts = [
            spot for spot in sorted(attachments.get(wire.net, ()))
            if _strictly_inside(spot, wire.points)
        ]
        if not cuts:
            out.append(wire)
            continue
        out.extend(_cut_polyline(wire, cuts, pin_at))
        built.downgrades.append(
            f"net {wire.net}: the wire "
            f"{_point_pair(wire.points[0], wire.points[-1])} is cut at "
            + ", ".join(_point_pair(spot, spot) for spot in cuts)
            + " — a flag of this net attaches there, and this host merges collinear "
            "neighbours, keeping a node only where something attaches (measured 145c: "
            "the flag's own anchor `(280, 785)` survived that merge while the bare run "
            "end `(280, 760)` did not); the pieces are one net, connected at the cut "
            "(145d)"
        )
    built.wires = out


def _preconditions(
    built: _Built,
    baseline: PlanDrawBaseline | None,
    baseline_findings: Sequence[str],
) -> list[str]:
    """What apply re-checks before the first write, in the order it checks it."""
    lines = [
        "the circuit, presentation and layout digests are unchanged "
        "(the plan carries all three)",
        "every library symbol the drawing names still hashes to the plan's "
        "geometry table",
        "the designators " + ", ".join(item.designator for item in built.parts)
        + " are still free in the page *and* the project export",
    ]
    if baseline is not None and baseline.digest:
        lines.append(
            f"page {baseline.page_uuid or '(the page the plan lands on)'} still holds "
            f"exactly the census the plan was built against "
            f"({census_phrase(baseline)}; digest {baseline.digest[:12]}…)"
        )
    else:
        lines.append(
            "the page the plan lands on is empty — this plan records no census, so the "
            "landing has to be a fresh page (a page bound at plan time carries its own "
            "census instead)"
        )
    if baseline_findings:
        lines.append(
            f"the project reports the {len(baseline_findings)} finding(s) the plan "
            "recorded, and no more"
        )
    return lines


def _postconditions(built: _Built, islands: Sequence[PlanIsland]) -> list[str]:
    """Done, as a list a human reads and apply re-checks leg by leg.

    **One namespace: the designator (143 F3).** ``PlanDrawWire.from_pin`` and
    ``PlanDrawFlag.on_pin`` are ``<specId>.<pin>`` by contract — the read-back
    resolves that end through the placed part, so the plan's own field has to be
    the plan's own id (`changeplan.PlanDrawWire`'s docstring) — but the sentence
    a human reads is about a drawing, where the part is called by its
    **designator** and the next line ("``R3`` (10k, R0402) is on the page …") says
    so. Printed raw, the list read *"a wire carrying net VIN … starting on R1.1"*
    beside "R3 (10k, R0402) is on the page": `R1.1` does not exist on that page
    (121c's delivered plan carries the same shape — spec ids ``C10/C11/C13``
    landed as ``C1/C2/C3``). The field keeps the spec id; only the sentence is
    translated, through the plan's own ``spec_id -> designator`` table.
    """
    table = {item.spec_id: item.designator for item in built.parts}

    def named(spelling: str) -> str:
        """``<specId>.<pin>`` in the namespace the rest of the sentence uses."""
        return _named_pin(table, spelling)

    lines = [
        f"{item.designator} ({item.value}, {item.symbol_ref}) is on the page at "
        f"({item.x:g}, {item.y:g}) rotation {item.rotation:g}"
        + (" mirrored" if item.mirror else "")
        + ", its pins read back at "
        + ", ".join(f"{pin.number}=({pin.dx:+g}, {pin.dy:+g})" for pin in item.pins)
        + f" from its origin (tolerance {HALF_GRID:g} units, half a lattice step)"
        for item in built.parts
    ]
    lines.extend(
        f"{item.designator} carries {item.value_key}={item.value!r} on the page, read "
        "back through the editor's own attribute channel "
        "(sch.set_component_attribute)"
        for item in built.parts
        if item.value_key
    )
    lines.extend(
        f"a wire carrying net {item.net} is on the page from "
        f"({item.points[0][0]:g}, {item.points[0][1]:g}) to "
        f"({item.points[-1][0]:g}, {item.points[-1][1]:g})"
        + (f", starting on {named(item.from_pin)}" if item.from_pin else "")
        + (f" ({len(item.points)} point(s))" if len(item.points) > 2 else "")
        for item in built.wires
    )
    lines.extend(
        f"a {item.kind} flag named {item.net} is on the page at "
        f"({item.x:g}, {item.y:g})"
        + (f", on {named(item.on_pin)}" if item.on_pin else "")
        for item in built.flags
    )
    groups: dict[tuple[str, ...], list[str]] = {}
    for island in islands:
        groups.setdefault(tuple(island.mates), []).append(island.pin)
    lines.extend(
        "the editor's own netlist holds " + " + ".join(members) + " as one net "
        "(membership, not the name it auto-numbers)"
        for members in sorted(groups)
    )
    lines.append(
        "no finding the project reported before the run is joined by a new one "
        "(the set may shrink, never grow — 036's rule)"
    )
    return lines


# --------------------------------------------------------------- the guards


def census_phrase(census: PlanDrawBaseline) -> str:
    """A census in words: what a report prints and a refusal quotes.

    One function so every place that speaks about a census (the C5 refusals, the
    plan's preconditions, the apply report) names the same fields — 143d's defect
    was precisely a census that spoke about three of its five counters, and a
    printout that leaves a counter out is a reader told the guard looked at less
    than it did.
    """
    return (
        f"{len(census.components)} part(s), {census.wire_count} wire(s), "
        f"{census.netflag_count} flag(s), {census.netlabel_count} label(s), "
        f"{census.unnumbered_count} part(s) with no usable designator and "
        f"{census.pin_count} pin(s)"
    )


def _section_count(geometry: Any, key: str) -> int:
    """How many entries a `sch.geometry` section carries (0 for an absent one)."""
    items = geometry.get(key) if isinstance(geometry, dict) else None
    return len(items) if isinstance(items, list) else 0


def canvas_census(geometry: Any) -> PlanDrawBaseline:
    """The page's primitive census, from a `sch.geometry` dump (the C5 guard).

    Designators, wire count, flag count, label count and the count of parts the
    page holds without a usable designator (`R5?`): every kind of primitive a hand
    edit changes that a compiled drawing has an opinion about. `addcomponent`'s
    readers are reused rather than re-written — they already know that a flag is a
    component with ``ComponentType: netflag`` and an empty designator (which is why
    the designator set cannot see it) and that a ``?``-suffixed designator is a part
    the editor has not numbered.

    143d: the census counted `components` and `wires` and stopped, and the section
    it did not count was invisible to the digest — the same coin has two sides, so
    both are paid here. A *section* the dump carries but the census ignores is a
    change no guard can see (`netlabels`, `pins`; see :data:`GEOMETRY_SECTIONS`);
    a *part the designator set deliberately drops* (``R5?``, 036b's occupancy
    reading) is the same blindness inside a section the census does read, and it is
    why ``unnumbered_count`` exists rather than the count being folded into
    ``components`` — the designator set keeps 036's meaning, and the count carries
    the fact.
    """
    components = sorted(addcomponent.component_origins(geometry))
    counts = {key: _section_count(geometry, key) for key in GEOMETRY_SECTIONS}
    unnumbered = _unnumbered_part_count(geometry)
    census = PlanDrawBaseline(
        components=components,
        wire_count=int(counts["wires"]),
        netflag_count=addcomponent.netflag_count(geometry),
        netlabel_count=int(counts["netlabels"]),
        pin_count=int(counts["pins"]),
        unnumbered_count=int(unnumbered),
    )
    census.digest = census_digest(census)
    return census


def _unnumbered_part_count(geometry: Any) -> int:
    """Parts the page holds that no designator can speak for (`R5?`, or none).

    Exactly the components `addcomponent.component_origins` drops and that
    are not something else with a reason to have no designator: the sheet (the page,
    not a part) and net flags (counted by `addcomponent.netflag_count`). "Dropped"
    is asked of that reader's own answer — a name it does not carry is a part it
    could not speak for, whatever the reason it had (no name, a ``?`` name, no
    position in the dump) — rather than by re-stating its rule here, so the two
    cannot drift.

    Measured 2026-10-10 (143d): a page with an un-numbered part added by hand came
    back with the same `components` list *and* the same digest as the page without
    it, so C5 reported "the page is the one the plan was built against" while a part
    sat on it.
    """
    if not isinstance(geometry, dict):
        return 0
    spoken = addcomponent.component_origins(geometry)
    count = 0
    for entry in geometry.get("components") or []:
        state = _state(entry)
        kind = _text(state.get("ComponentType")) or "part"
        if kind in ("sheet", "netflag"):
            continue
        other = state.get("OtherProperty")
        other = other if isinstance(other, dict) else {}
        name = _text(state.get("Designator")) or _text(other.get("Designator"))
        if not name or name not in spoken:
            count += 1
    return count


def census_digest(census: PlanDrawBaseline) -> str:
    """One string for a census, so a report can quote it and a guard can compare.

    Every counter in :class:`PlanDrawBaseline` is in the payload. A counter left
    out is a change the digest cannot see, which is the whole failure 143d reports
    (labels and un-numbered parts both had no entry in this dictionary).
    """
    payload = json.dumps(
        {
            "components": sorted(census.components),
            "wireCount": int(census.wire_count),
            "netflagCount": int(census.netflag_count),
            "netlabelCount": int(census.netlabel_count),
            "pinCount": int(census.pin_count),
            "unnumberedCount": int(census.unnumbered_count),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def library_problems(
    plan: ChangePlan, profiles: Mapping[str, SymbolProfile] | None
) -> list[str]:
    """C6's pre-write leg: does the library still hash to the plan's table?

    The editor's library geometry is **not readable** through the bridge
    catalogue (`lib.symbol.get` returns metadata and its own declaration says "no
    geometry"), so the geometry this can check before any write is the profiles
    document the drawing was compiled from. That is a real guard and not a
    formality: a library file that moved (a symbol re-drawn, a pin added) makes
    every pin tip land somewhere else, silently. The editor-side half of the same
    question is answered *after* placement by the pin read-back, which is the only
    measurement that exists for it.

    ``None`` means the caller has no profiles document to hand over; that is
    reported as a problem-free "not checked" — never as a pass — by the caller.
    """
    if profiles is None:
        return []
    problems: list[str] = []
    try:
        current = dict(profile_table(profiles))
    except DrawPlanError as exc:
        return [f"the profiles document cannot be read: {exc}"]
    for ref, digest in plan.change.profile_hashes:
        if ref not in current:
            problems.append(
                f"{ref} is missing from the profiles document — the library this plan "
                "was compiled against is not the library it is being applied to"
            )
        elif current[ref] != digest:
            problems.append(
                f"{ref} hashes to {current[ref]!r} now, but the plan was compiled "
                f"against {digest!r} — the symbol's geometry changed, so every pin tip "
                "would land somewhere nobody laid out (054 C6)"
            )
    return problems


def guard_problems(
    plan: ChangePlan,
    *,
    circuit_sha256: str = "",
    presentation_sha256: str = "",
    layout_sha256: str = "",
    profiles: Mapping[str, SymbolProfile] | None = None,
    page_uuid: str = "",
    geometry: Any = None,
    expect_census: str = "",
    plan_census: bool = True,
) -> list[str]:
    """Every guard 054 §四.1 names, as problems (empty list = all clear).

    One function so the order and the wording cannot drift between the plan-time
    print and the apply-time refusal:

    1. **the three digests** — the circuit spec, the presentation spec and the
       layout's own geometry (`LayoutPlan.geometry_sha256`). A caller that has no
       file to re-digest passes an empty string and gets no problem from that leg
       *plus* a caller-side "not checked" line; it never silently passes;
    2. **the library table** — see :func:`library_problems`;
    3. **the page** — the plan's page uuid against the one the caller resolved;
    4. **the census** — "someone changed the canvas by hand" (C5), the guard a
       local edit never needed. Two ways in, and they are the same comparison:
       the plan's own recorded census (a plan bound to a page at plan time, the
       ``plan_census`` leg) or ``expect_census``, the digest a previous run's
       report quoted — an **explicit demand**, which is checked whenever a
       geometry was handed over. An unbound plan with neither is not silently
       unguarded: the landing then has to be a *fresh* page, which apply checks by
       reading it.

    ``plan_census=False`` defers the recorded-baseline leg, and apply does exactly
    that for its first pass: the plan's own postconditions have to be read first,
    because a page whose primitives *are* this drawing is not a page somebody
    changed, and refusing it would make a repeat apply (054 C4) impossible. The
    caller's ``expect_census`` is not deferred — it is a demand, not an inference.
    """
    problems: list[str] = []
    for label, stated, current in (
        ("circuitSha256", plan.change.circuit_sha256, circuit_sha256),
        ("presentationSha256", plan.change.presentation_sha256, presentation_sha256),
        ("layoutSha256", plan.change.layout_sha256, layout_sha256),
    ):
        if not current:
            continue
        if current != stated:
            problems.append(
                f"{label}: the plan was compiled against {stated!r} and the file now "
                f"hashes to {current!r} — recompile the drawing (054 §一 protection 1)"
            )
    problems.extend(library_problems(plan, profiles))
    if page_uuid and plan.source.page_uuid and page_uuid != plan.source.page_uuid:
        problems.append(
            f"the plan lands on page {plan.source.page_uuid}, but the run resolved page "
            f"{page_uuid} — a drawing must not land on a page nobody authorised"
        )
    if geometry is not None:
        now = canvas_census(geometry)
        if plan_census and plan.change.draw_baseline.digest:
            if now.digest != plan.change.draw_baseline.digest:
                problems.append(
                    "the page's primitives are not the ones the plan was built against: "
                    f"the plan recorded {census_phrase(plan.change.draw_baseline)} "
                    f"({plan.change.draw_baseline.digest[:12]}…), the page now has "
                    f"{census_phrase(now)} ({now.digest[:12]}…) — somebody changed "
                    "the canvas after the plan was made (054 C5)"
                )
        if expect_census and now.digest != expect_census:
            problems.append(
                "the page's primitives are not the ones this run was told to expect: "
                f"expected {expect_census[:12]}…, the page holds "
                f"{census_phrase(now)} ({now.digest[:12]}…) — somebody changed the "
                "canvas since the run that quoted that digest (054 C5)"
            )
    return problems


# --------------------------------------------------------- postconditions


def plan_pins(plan: ChangePlan) -> list[tuple[str, str]]:
    """Every ``(designator, pin)`` the plan places, in plan order."""
    out: list[tuple[str, str]] = []
    for part in plan.change.draw_parts:
        for pin in part.pins:
            out.append((part.designator, pin.number))
    return out


def _near(left: tuple[float, float], right: tuple[float, float], tol: float) -> bool:
    return abs(left[0] - right[0]) <= tol and abs(left[1] - right[1]) <= tol


def placement_problems(
    plan: ChangePlan,
    *,
    geometry: Any,
    pins: Mapping[tuple[str, str], tuple[float, float]],
) -> list[str]:
    """C1's protection 3, on its own: are the **parts** where the plan put them?

    Separate from :func:`postcondition_problems` because it runs in the middle of
    the run: after the parts are placed and their pins read back, and **before**
    any wire is drawn. The full canvas leg would fail there by construction (its
    wire half has nothing to find yet), and a check that is red until the next
    step is a check nobody can act on.
    """
    return _part_problems(plan, geometry, pins)


def value_problems(plan: ChangePlan, geometry: Any) -> list[str]:
    """Is every value the plan **writes** the value the page now states? (055 G2)

    The comparison the write needs and the plan's own postconditions promise:
    the design value goes into the editor's attribute channel, and the only
    honest way to say it landed is to read the part back. The reader is
    :func:`~boardwise.core.changeplan.resolve_on_page` — the same
    ``state.Designator || state.OtherProperty.Designator`` resolution and the
    same ``OtherProperty.Value`` precedence the 016 edit path reads, because
    ``OtherProperty`` *is* the channel ``sch.set_component_attribute`` writes and
    comparing against anywhere else would compare against a copy that cannot
    change.

    Three facts, three answers:

    * a part the plan does not claim a write for (``value_key`` empty) is not
      judged — that is what an empty key means, and it is how a pre-055 plan
      stays executable;
    * a part that is not on the page is **not** reported here: the parts leg owns
      "it did not land", and saying it twice would make one fault look like two;
    * a part that is there but states another value (or states no ``Value`` at
      all, which is a different fact and is said as such) is the problem this leg
      exists for.

    The comparison is exact, deliberately: the channel stores the string it was
    given and the connector's own ``applied`` is defined as an exact match against
    the same map, so a different string is a different value here. A drawing that
    needs ``4.7k`` == ``4.7kΩ`` semantics would be a *tolerance* decision, and
    this batch does not make it.
    """
    problems: list[str] = []
    for part in plan.change.draw_parts:
        if not part.value_key or not part.value:
            continue
        found = resolve_on_page(geometry, part.designator)
        if found.ambiguous:
            problems.append(
                f"{part.designator} resolves to {found.matching} primitives on the "
                f"page, so which one carries {part.value_key}={part.value!r} cannot "
                "be stated (the plan places one part per designator)"
            )
            continue
        component = found.component
        if component is None:
            continue
        if not component.value_key:
            problems.append(
                f"{part.designator} is on the page but states no {part.value_key} at "
                f"all, and the plan writes {part.value!r} into it — 'the value is "
                "empty' and 'the primitive has no such key' are different facts"
            )
            continue
        if component.value != part.value:
            problems.append(
                f"{part.designator}.{part.value_key} reads {component.value!r} on the "
                f"page and the plan writes {part.value!r} "
                f"(read from {component.value_key}) — the value did not land "
                "(055 G2: the design value is written through "
                "sch.set_component_attribute and read back)"
            )
    return problems


def postcondition_problems(
    plan: ChangePlan,
    *,
    live: Mapping[tuple[str, str], str] | None = None,
    geometry: Any = None,
    pins: Mapping[tuple[str, str], tuple[float, float]] | None = None,
    flags_before: int | None = None,
) -> dict[str, list[str]]:
    """Is what the plan promised actually on the page? Both legs, 036's shape.

    ``{"live": [...], "canvas": [...]}`` — the same dict
    `engines.subcircuit.postcondition_problems` returns, for the same reason
    (029/035/036's flow reads one of them per leg and
    `all_satisfied` is what decides), so apply can reuse the flow's shape
    verbatim and "already done" cannot disagree with "done":

    * **live** — the editor's own netlist (`sch.netlist`), pin by pin: for every
      pin the plan places, the other pins it is one net with. **Membership, never
      names**: an auto-numbered net name changes whenever the wiring changes
      (measured 035/036). This is the acceptance's main judgement (037);
    * **canvas** — `sch.geometry` plus the placed parts' own pin read-back: is
      each part at its planned point and pose, does each expected pin sit within
      half a lattice step of its expected offset (that is
      :func:`placement_problems`), is each planned wire's own endpoints on the
      page under that net, does every part the plan claims a value write for
      state that value (that is :func:`value_problems`, 055 G2), and (when the
      caller read the page before the writes) did exactly the promised number of
      flags appear.
    """
    state: dict[str, list[str]] = {"live": [], "canvas": []}
    if live is not None:
        state["live"].extend(_live_problems(plan, live))
    if geometry is not None:
        state["canvas"].extend(_part_problems(plan, geometry, pins or {}))
        state["canvas"].extend(_wire_problems(plan, geometry))
        state["canvas"].extend(value_problems(plan, geometry))
        if flags_before is not None:
            expected = len(plan.change.draw_flags)
            now = addcomponent.netflag_count(geometry)
            if now - flags_before != expected:
                state["canvas"].append(
                    f"the page carries {now - flags_before:+d} flag(s) more than before "
                    f"the run, and the plan places {expected} "
                    + (
                        "— a flag that did not land leaves a rail unconnected"
                        if now - flags_before < expected
                        else "— something else added a flag"
                    )
                )
    return state


def all_satisfied(state: Mapping[str, list[str]]) -> bool:
    """Both legs empty, the way `subcircuit.all_satisfied` reads the same dict."""
    return not state.get("live") and not state.get("canvas")


def _live_problems(
    plan: ChangePlan, live: Mapping[tuple[str, str], str]
) -> list[str]:
    """The netlist leg: **the plan's own pins**, grouped as the plan says.

    Membership, never names (035 round 4): an auto-named net is renumbered
    whenever the wiring changes, so "which pins are together" is the fact.

    The comparison is scoped to the plan's own pins, and **that scoping is a
    measurement, not a convenience** (054 C7, 2026-09-28): the editor's netlist is
    **project-wide**, so two pages that name a net ``VIN`` share one net — landing
    the divider on a second page made the running page's netlist answer ``R4.1 is
    on net 'VIN' with ['R1.1', 'R4.1']``, where ``R1.1`` sits on another page.
    The exact-membership reading then refused a drawing that was wired exactly as
    planned, and it would refuse every second module whose nets are named the way
    the first one's are. So:

    * **inside the plan's pins, the partition must be exact** — two of the
      module's pins that were supposed to be on different nets and now share one
      is a short, and a planned mate that did not join is a missing wire;
    * **company from outside the plan is reported, not judged** — it is what the
      name means in a flat multi-page project, and whether that is wanted is a
      naming decision (052's labelPolicy), which this batch does not make.
    """
    planned = {f"{designator}.{pin}" for designator, pin in plan_pins(plan)}
    island_of: dict[str, set[str]] = {}
    for name in {net for net in live.values() if net}:
        island_of[name] = {
            f"{designator}.{pin}"
            for (designator, pin), net in live.items()
            if net == name
        }
    problems: list[str] = []
    for island in plan.change.islands:
        designator, _sep, pin = island.pin.partition(".")
        name = live.get((designator, pin))
        if name is None:
            problems.append(
                f"{island.pin} is not in the editor's netlist at all "
                "(the part or the pin did not land)"
            )
            continue
        members = island_of.get(name, set())
        inside = sorted(member for member in members if member in planned)
        wanted = sorted(island.mates)
        if inside != wanted:
            problems.append(
                f"{island.pin} is on net {name!r} with {inside or 'nothing'} among this "
                f"plan's pins, but the plan says {wanted}"
            )
    return problems


def live_islands(
    plan: ChangePlan, live: Mapping[tuple[str, str], str]
) -> list[dict]:
    """Every planned pin, its live net name and who else is on it (054's evidence).

    ``others`` is the project-wide company :func:`_live_problems` deliberately
    does not judge: pins outside this plan that the editor puts on the same net,
    which in a flat multi-page project is what a shared net *name* means.
    """
    planned = {f"{designator}.{pin}" for designator, pin in plan_pins(plan)}
    island_of: dict[str, set[str]] = {}
    for name in {net for net in live.values() if net}:
        island_of[name] = {
            f"{designator}.{pin}"
            for (designator, pin), net in live.items()
            if net == name
        }
    rows: list[dict] = []
    for island in plan.change.islands:
        designator, _sep, pin = island.pin.partition(".")
        name = live.get((designator, pin), "")
        members = island_of.get(name, set())
        rows.append({
            "pin": island.pin,
            "net": name,
            "mates": sorted(island.mates),
            "others": sorted(member for member in members if member not in planned),
        })
    return rows


def _part_problems(
    plan: ChangePlan,
    geometry: Any,
    pins: Mapping[tuple[str, str], tuple[float, float]],
) -> list[str]:
    """The parts and their pins: where they are, and where the editor says they are."""
    problems: list[str] = []
    origins = addcomponent.component_origins(geometry)
    for part in plan.change.draw_parts:
        spot = origins.get(part.designator)
        if spot is None:
            problems.append(
                f"{part.designator} is not on the page "
                f"(the plan places it at ({part.x:g}, {part.y:g}))"
            )
            continue
        if not _near(spot, (part.x, part.y), HALF_GRID):
            problems.append(
                f"{part.designator} is at ({spot[0]:g}, {spot[1]:g}) and the plan puts "
                f"it at ({part.x:g}, {part.y:g}) — further apart than the "
                f"{HALF_GRID:g}-unit tolerance"
            )
        read_for_part = {
            number: point
            for (designator, number), point in pins.items()
            if designator == part.designator
        }
        if part.pins and not read_for_part:
            problems.append(
                f"{part.designator}'s pin coordinates were not read back, so its "
                f"{len(part.pins)} pin(s) could not be compared with the plan"
            )
            continue
        for pin in part.pins:
            read = read_for_part.get(pin.number)
            if read is None:
                problems.append(
                    f"{part.designator} reports no pin {pin.number}, but the plan's "
                    f"{part.symbol_ref} has one"
                )
                continue
            want = (round(spot[0] + pin.dx, 6), round(spot[1] + pin.dy, 6))
            if not _near(read, want, HALF_GRID):
                problems.append(
                    f"{part.designator}.{pin.number} reads back at "
                    f"({read[0]:g}, {read[1]:g}) but the plan expects "
                    f"({want[0]:g}, {want[1]:g}) — off by "
                    f"({read[0] - want[0]:+.1f}, {read[1] - want[1]:+.1f}) units, more "
                    f"than the {HALF_GRID:g}-unit tolerance: the library symbol on this "
                    "host is not the one the drawing was laid out with (054 C6)"
                )
    return problems


def unnamed_nets(plan: ChangePlan) -> set[str]:
    """The nets this plan's wires are drawn **without a name** for (069 sec.9).

    A net the plan states with a flag carries its name on the flag; naming its wires
    too prints the name twice, which is what 岳 sent the landed page back for
    (「有了旗标就不要反复标注网络标识了。看着很乱啊」). `draw apply` therefore places
    those wires unnamed — which is exactly what a hand-drawn rail looks like to the
    editor (岳's own P22: its wires answer ``Net: ""`` while its flags carry the
    names, and the netlist still joins them by geometry).

    The two places that read a landed wire back — the canvas leg and the discard —
    therefore match those wires by **geometry**: the page has no name to match them
    by, and the netlist leg is what says which net they are on.
    """
    return {item.net for item in plan.change.draw_flags if item.net}


def _wire_problems(plan: ChangePlan, geometry: Any) -> list[str]:
    """Each planned wire's own endpoints, under the net it belongs to.

    A *lenient* reading on purpose, and the module says so: the host is free to
    split a polyline or to merge two collinear ones (measured: what comes back is
    a point list, not the segments that were sent — pit 26), and neither changes
    where the wire reaches. What must hold is that both ends of every planned wire
    are vertices of that net's own wiring on the page, and that the net's total
    length did not shrink. The netlist leg is the acceptance's main judgement;
    this one says "the drawn thing is on the canvas".

    A net in :func:`unnamed_nets` has no name on the page to be found under (069
    sec.9), so its wires' ends are measured against the page's wiring as a whole and
    its length against the plan's total — *which* net those wires belong to is the
    netlist leg's judgement, and the ends still have to be on the canvas.
    """
    vertices: dict[str, set[tuple[float, float]]] = {}
    lengths: dict[str, float] = {}
    for x, y, net in addcomponent.wire_vertices(geometry):
        vertices.setdefault(net, set()).add((round(x, 6), round(y, 6)))
    for entry in (geometry or {}).get("wires") or []:
        state = entry.get("state") or {}
        net = str(state.get("Net") or "")
        line = state.get("Line") or state.get("Points") or []
        if not isinstance(line, (list, tuple)) or len(line) < 4:
            continue
        if isinstance(line[0], (list, tuple)):
            pairs = [(float(pair[0]), float(pair[1])) for pair in line]
        else:
            pairs = [
                (float(line[index]), float(line[index + 1]))
                for index in range(0, len(line) - 1, 2)
            ]
        total = 0.0
        for index in range(1, len(pairs)):
            total += abs(pairs[index][0] - pairs[index - 1][0]) + abs(
                pairs[index][1] - pairs[index - 1][1]
            )
        lengths[net] = lengths.get(net, 0.0) + total
    problems: list[str] = []
    planned_length: dict[str, float] = {}
    unnamed = unnamed_nets(plan)
    everywhere = {spot for spots in vertices.values() for spot in spots}
    for wire in plan.change.draw_wires:
        have = vertices.get(wire.net, set())
        if not have and wire.net in unnamed:
            have = everywhere
        for end in (wire.points[0], wire.points[-1]):
            spot = (round(end[0], 6), round(end[1], 6))
            if spot not in have:
                problems.append(
                    f"net {wire.net}: no wire vertex at ({end[0]:g}, {end[1]:g}) on the "
                    "page, but the plan draws a wire reaching it"
                )
        planned_length[wire.net] = planned_length.get(wire.net, 0.0) + sum(
            abs(wire.points[index][0] - wire.points[index - 1][0])
            + abs(wire.points[index][1] - wire.points[index - 1][1])
            for index in range(1, len(wire.points))
        )
    # The unnamed wires (069 sec.9) cannot be counted per net — the page holds them
    # under no name — so their lengths are compared as one bucket. They are still
    # counted: a segment that did not land is exactly as visible here.
    unnamed_wanted = sum(
        value for net, value in planned_length.items() if net in unnamed
    )
    if unnamed_wanted and lengths.get("", 0.0) + HALF_GRID < unnamed_wanted:
        problems.append(
            f"the plan draws {unnamed_wanted:g} units of unnamed wire (nets "
            + ", ".join(sorted(net for net in planned_length if net in unnamed))
            + f") and the page holds {lengths.get('', 0.0):g} — a segment did not land"
        )
    for net, wanted in sorted(planned_length.items()):
        if net in unnamed:
            continue
        have = lengths.get(net, 0.0)
        if have + HALF_GRID < wanted:
            problems.append(
                f"net {net}: the plan draws {wanted:g} units of wire and the page holds "
                f"{have:g} — a segment did not land"
            )
    return problems


# ------------------------------------------ 057: the page that is already there
#
# Three questions a drawing landed on a *non-empty* page has to answer, and one a
# drawing taken *off* a page does:
#
# * what is already on the page, item by item (:func:`census_items`) — the
#   054 census counts designators, wires and flags, which is enough to notice a
#   page changed but not to say *what* changed, and 057 sec.2's acceptance is
#   "既有图元零改动 — 数量、坐标、值逐项";
# * where the new drawing may not go (:func:`census_keepouts`) — every existing
#   primitive becomes a keep-out the page compiler plans around;
# * did the landing leave everything it did not draw exactly as it was
#   (:func:`census_changes`);
# * which primitives on the page *are* this plan's, and only those
#   (:func:`discard_selection`, 057 sec.5).

#: The clear space kept around every existing primitive when it becomes a
#: keep-out: one lattice step. A module frame already carries its own padding
#: (`pagecompiler.FRAME_PADDING`), so this only has to make a zero-width wire a
#: box with area — the keep-out rule is "shares area", and a line has none.
CENSUS_CLEARANCE = DRAW_GRID

#: The half-size of the box an existing component gets when the page could not
#: measure it (`sch.geometry` reports a component's extent only when asked by id,
#: `bboxIds`). Ten lattice steps each way is the size of a small IC with its pin
#: stubs; the note that goes with it says the box is an assumption, not a reading.
CENSUS_FALLBACK_HALF = 10 * DRAW_GRID

#: The primitive sections a `sch.geometry` dump is contracted to carry — the same
#: four `bridge/protocol.py`'s `sch.geometry` promises and
#: `engines.draw.geometry_fingerprint` counts. Named once, here, because the census
#: is the reader that has to see **every** one of them: 143d found the census
#: reading `components` and `wires` only, so a page that gained a `netlabels`
#: entry (or a `pins` one) had a byte-identical census and a C5 guard that said
#: "nobody touched this page" over a page somebody had touched. Measured on this
#: host (3.2.186, and every recorded dump — 142 of them, `pins` and `netlabels`
#: always empty): the two sections come back empty today, so this is insurance
#: against a host that fills them rather than a live refusal — but a guard that
#: covers three of four contracted sections is a guard whose "checked" is a claim
#: it cannot support, which is the whole defect 143d reports.
GEOMETRY_SECTIONS: tuple[str, ...] = ("components", "wires", "pins", "netlabels")


def _state(entry: Any) -> dict[str, Any]:
    state = (entry or {}).get("state") if isinstance(entry, dict) else None
    return state if isinstance(state, dict) else {}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _line_points(state: Mapping[str, Any]) -> list[tuple[float, float]]:
    """A wire's point list, in either shape the host has been seen to send."""
    line = state.get("Line") or state.get("Points") or state.get("points") or []
    if not isinstance(line, (list, tuple)) or not line:
        return []
    out: list[tuple[float, float]] = []
    if isinstance(line[0], (list, tuple)):
        for pair in line:
            if len(pair) >= 2 and _num(pair[0]) is not None and _num(pair[1]) is not None:
                out.append((float(pair[0]), float(pair[1])))
        return out
    coords = list(line)
    for index in range(0, len(coords) - 1, 2):
        x, y = _num(coords[index]), _num(coords[index + 1])
        if x is not None and y is not None:
            out.append((x, y))
    return out


def netlabel_items(geometry: Any) -> list[dict[str, Any]]:
    """Every net label the page reports, one row each (143d), with its identity.

    The section is one `sch.geometry` is contracted to carry (`netlabels`, and the
    one `addcomponent.net_label_names`, `patchpin` and `moveblock` already read),
    and the two shapes it arrives in are both handled: the flat one
    (``state.Net`` / ``state.Text`` / ``state.Name``) and the nested one
    (``state.Label.{Net,Text}``) that `addcomponent.net_label_names` carries a
    branch for. ``net`` is what the label *states*, ``text`` what it prints —
    they differ when a label shows one name and carries another, and a census
    that read only one of them would call that edit no change.

    Rows are keyed by the page's own primitive id, like every other census row.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(geometry, dict):
        return rows
    for entry in geometry.get("netlabels") or []:
        state = _state(entry)
        label = state.get("Label")
        label = label if isinstance(label, dict) else {}
        net = _text(state.get("Net")) or _text(state.get("Name")) or _text(label.get("Net"))
        text = _text(state.get("Text")) or _text(label.get("Text"))
        rows.append({
            "id": str((entry or {}).get("primitiveId") or state.get("PrimitiveId") or ""),
            "kind": "netlabel",
            "net": net,
            "text": text,
            "x": _num(state.get("X")),
            "y": _num(state.get("Y")),
            "rotation": _num(state.get("Rotation")),
        })
    return rows


def census_items(geometry: Any) -> list[dict[str, Any]]:
    """Every primitive the page holds, one row each, with its identity fields.

    The rows are what "zero change" is judged on: a part's designator, value,
    LCSC number, origin and pose; a flag's net and origin; a wire's net and its
    point list; a net label's net, text, origin and angle. Keyed by the page's own
    primitive id — the one identity the host keeps stable across reads. The sheet
    (the drawing frame) is the page, not an item on it, and is left out.

    Every section :data:`GEOMETRY_SECTIONS` names has a branch here. It did not
    until 143d: the ``netlabels`` section had none, so this function's own
    promise ("every primitive … one row each") was false for exactly the kind of
    edit 057 sec.2's "既有图元零改动" is meant to catch — a label somebody added,
    moved or renamed was a change with no row to be seen as one. The ``pins``
    section is deliberately not a row (a pin is drawn by the component that owns
    it and is counted with it, in `census_keepouts`' measured box); it is counted
    in the digest by :func:`canvas_census`, which is where "did anything on this
    page move" is answered.
    """
    rows: list[dict[str, Any]] = []
    if not isinstance(geometry, dict):
        return rows
    for entry in geometry.get("components") or []:
        state = _state(entry)
        kind = _text(state.get("ComponentType")) or "part"
        if kind == "sheet":
            continue
        other = state.get("OtherProperty")
        other = other if isinstance(other, dict) else {}
        rows.append({
            "id": str((entry or {}).get("primitiveId") or state.get("PrimitiveId") or ""),
            "kind": "netflag" if kind == "netflag" else "part",
            "designator": _text(state.get("Designator")) or _text(other.get("Designator")),
            "value": _text(other.get("Value")) if "Value" in other else _text(state.get("Value")),
            "lcsc": _text(state.get("SupplierId")),
            "net": _text(state.get("Net")),
            "x": _num(state.get("X")),
            "y": _num(state.get("Y")),
            "rotation": _num(state.get("Rotation")),
            "mirror": bool(state.get("Mirror")),
        })
    for entry in geometry.get("wires") or []:
        state = _state(entry)
        rows.append({
            "id": str((entry or {}).get("primitiveId") or state.get("PrimitiveId") or ""),
            "kind": "wire",
            "net": _text(state.get("Net")),
            "points": [list(point) for point in _line_points(state)],
        })
    rows.extend(netlabel_items(geometry))
    return sorted(rows, key=lambda row: (row["kind"], row["id"]))


def census_keepouts(
    geometry: Any,
    *,
    clearance: float = CENSUS_CLEARANCE,
    fallback_half: float = CENSUS_FALLBACK_HALF,
) -> tuple[list[tuple[float, float, float, float]], list[str], list[str]]:
    """Every existing primitive as a keep-out: ``(boxes, labels, notes)`` (057 sec.2).

    ``labels[i]`` says which primitive ``boxes[i]`` came from, so a refusal that
    names ``keepouts[3]`` can be read back as "the existing R5". A component's or a
    label's box is its **measured** extent from the dump's ``bboxes`` map (the
    caller asks for it with ``bboxIds``); one the page did not measure gets a
    :data:`CENSUS_FALLBACK_HALF` box around its origin and a note saying so — an
    assumed box is a weaker keep-out, and the reader has to know which ones are.
    A wire is one box per segment. Every box is grown by ``clearance``.

    "Every existing primitive" is :func:`census_items`' own list, so a kind that
    function gains a row for becomes a keep-out in the same commit — 143d found a
    label could be drawn over because it was never a row.
    """
    boxes: list[tuple[float, float, float, float]] = []
    labels: list[str] = []
    notes: list[str] = []
    if not isinstance(geometry, dict):
        return boxes, labels, notes
    raw = geometry.get("bboxes")
    measured = raw if isinstance(raw, dict) else {}
    unmeasured: list[str] = []
    for row in census_items(geometry):
        if row["kind"] == "wire":
            points = [tuple(point) for point in row["points"]]
            for start, end in zip(points, points[1:]):
                boxes.append((
                    min(start[0], end[0]) - clearance, min(start[1], end[1]) - clearance,
                    max(start[0], end[0]) + clearance, max(start[1], end[1]) + clearance,
                ))
                labels.append(
                    f"existing wire {row['id']}" + (f" ({row['net']})" if row["net"] else "")
                )
            continue
        if row["kind"] == "netlabel":
            # 143d: a label is a name printed on the canvas and a keep-out like any
            # other primitive the page holds (057 sec.2: "每一个已存在图元都成为
            # keep-out"). Without this branch the page compiler could put a module
            # frame straight on top of somebody's label either.
            name = f"{row['net'] or 'netlabel'} label"
        else:
            name = row["designator"] or (
                f"{row['net']} flag" if row["kind"] == "netflag" and row["net"] else row["kind"]
            )
        box = measured.get(row["id"])
        values = (
            [_num(box.get(key)) for key in ("minX", "minY", "maxX", "maxY")]
            if isinstance(box, dict) else [None]
        )
        if None not in values:
            x0, y0, x1, y1 = (float(value) for value in values)  # type: ignore[arg-type]
            box_value = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        elif row["x"] is not None and row["y"] is not None:
            box_value = (
                row["x"] - fallback_half, row["y"] - fallback_half,
                row["x"] + fallback_half, row["y"] + fallback_half,
            )
            unmeasured.append(name)
        else:
            unmeasured.append(f"{name} (no position either — not a keep-out)")
            continue
        boxes.append((
            box_value[0] - clearance, box_value[1] - clearance,
            box_value[2] + clearance, box_value[3] + clearance,
        ))
        labels.append(f"existing {name} {row['id']}")
    if unmeasured:
        notes.append(
            f"{len(unmeasured)} existing primitive(s) had no measured extent, so each "
            f"is kept out with an assumed ±{fallback_half:g} box around its origin: "
            + ", ".join(sorted(unmeasured))
        )
    return boxes, labels, notes


def _stable_net(row: Mapping[str, Any]) -> str:
    """A wire's net as an identity: an editor-generated name is not one.

    Measured 2026-09-25 (036, pit 25): the host renumbers an auto net
    (``NET3`` → ``NET4``, ``$1N5`` …) when wiring changes *elsewhere*, so a wire
    nobody touched can come back with another auto name. A *named* net carries
    intent and stays in the comparison — the same rule the findings signature
    applies (`cli._finding_signature`).
    """
    from ..rules.facts import is_auto_net

    net = row.get("net") or ""
    return "(auto)" if row.get("kind") == "wire" and is_auto_net(net) else net


def _identity(row: Mapping[str, Any]) -> tuple:
    if row["kind"] == "wire":
        return ("wire", _stable_net(row), tuple(tuple(point) for point in row["points"]))
    if row["kind"] == "netlabel":
        # 143d: what a label *is* = the net it states, the text it prints and where
        # it prints it. The two name fields are compared separately because a label
        # that shows one name and carries another is a change worth a line, and the
        # auto-net exemption is a *wire* rule (a label's name is a declaration, not
        # an editor-generated net id).
        return ("netlabel", row["net"], row["text"], row["x"], row["y"], row["rotation"])
    return (
        row["kind"], row["designator"], row["value"], row["lcsc"], row["net"],
        row["x"], row["y"], row["rotation"], row["mirror"],
    )


def census_changes(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    ignore_ids: Iterable[str] = (),
) -> list[str]:
    """What happened to the primitives that were on the page before (057 sec.2).

    Every row of ``before`` — except ``ignore_ids``, the ones the run itself was
    meant to touch (a discard's own targets) — must still be on the page, with
    the same identity fields (designator, value, LCSC number, net, origin, pose;
    a wire's net and point list; a label's net, text and pose — 143d). A row that
    is gone or that changed is one line. New rows are not judged here: what a run
    *adds* is the range check's business, and this function is the one that says
    "and nothing else moved".

    "Every row" is only as wide as :func:`census_items`; the two are one pair, and
    143d's hole was a kind of primitive that reached one of them and not the other.
    """
    skip = set(ignore_ids)
    now = {row["id"]: row for row in after if row.get("id")}
    problems: list[str] = []
    for row in before:
        ident = row.get("id") or ""
        if not ident or ident in skip:
            continue
        name = row.get("designator") or (
            f"{row.get('net')} {row['kind']}" if row.get("net") else row["kind"]
        )
        found = now.get(ident)
        if found is None:
            problems.append(f"existing {name} ({ident}) is no longer on the page")
            continue
        if _identity(found) != _identity(row):
            fields = [
                key for key in ("designator", "value", "lcsc", "net", "text", "x", "y",
                                "rotation", "mirror", "points")
                if (
                    _stable_net(row) != _stable_net(found) if key == "net"
                    else row.get(key) != found.get(key)
                )
            ]
            problems.append(
                f"existing {name} ({ident}) changed: "
                + ", ".join(f"{key} {row.get(key)!r} → {found.get(key)!r}" for key in fields)
            )
    return problems


@dataclass
class DiscardSelection:
    """Which primitives on the page are this plan's, and whether that is certain.

    ``parts``/``flags``/``wires`` are ``(primitive id, what)`` pairs the discard
    may delete. ``mismatches`` are the reasons the whole batch is refused — one
    is enough (057 sec.5: "任何一件身份不符 → 整批拒删"). ``absent`` are the
    plan's items the page does not hold at all, which is not a mismatch: a second
    discard finds everything absent (its idempotence).
    """

    parts: list[tuple[str, str]] = field(default_factory=list)
    flags: list[tuple[str, str]] = field(default_factory=list)
    wires: list[tuple[str, str]] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)

    @property
    def ids(self) -> list[str]:
        """Every id to delete, lines before parts (057 sec.5's order)."""
        return [ident for ident, _what in self.wires + self.flags + self.parts]

    @property
    def empty(self) -> bool:
        return not (self.parts or self.flags or self.wires)


def _on_polyline(point: tuple[float, float], points: Sequence[tuple[float, float]]) -> bool:
    """Is `point` a vertex of the polyline or on one of its segments?"""
    if len(points) == 1:
        return _near(point, points[0], 1e-6)
    for start, end in zip(points, points[1:]):
        if (
            min(start[0], end[0]) - 1e-6 <= point[0] <= max(start[0], end[0]) + 1e-6
            and min(start[1], end[1]) - 1e-6 <= point[1] <= max(start[1], end[1]) + 1e-6
            and abs(
                (end[0] - start[0]) * (point[1] - start[1])
                - (end[1] - start[1]) * (point[0] - start[0])
            ) <= 1e-6
        ):
            return True
    return False


def discard_selection(plan: ChangePlan, geometry: Any) -> DiscardSelection:
    """The plan's own primitives on the page, identity checked (057 sec.5).

    Three identity legs for a part, and all three must hold before it may be
    deleted: the **designator** (exactly one component answers to it), the
    **position** (its origin within half a lattice step of the plan's), and the
    **value** — the `Value` the plan wrote (055 G2), or, for a plan that claims no
    value write, the LCSC number the part was placed from. A part whose
    designator the plan left empty (a page document discarded without its plan)
    is found **by position** instead, and then its designator prefix stands in
    for the designator leg.

    A flag is the plan's when exactly one net flag, of the plan's net, sits on the
    plan's point. A wire is the plan's when it carries the plan's net and **every**
    point it reports lies on the plan's own wiring of that net; a wire that
    touches the plan's wiring and reaches beyond it has been merged by the host
    with somebody else's (pit 32: touching wires become one primitive), and
    deleting it would delete their wire too — a mismatch, never a partial delete.
    """
    selection = DiscardSelection()
    rows = census_items(geometry)
    part_rows = [row for row in rows if row["kind"] == "part"]
    flag_rows = [row for row in rows if row["kind"] == "netflag"]
    wire_rows = [row for row in rows if row["kind"] == "wire"]

    for part in plan.change.draw_parts:
        spot = (part.x, part.y)
        if part.designator:
            named = [
                row for row in part_rows
                if row["designator"].upper() == part.designator.upper()
            ]
            label = part.designator
        else:
            named = [
                row for row in part_rows
                if row["x"] is not None and row["y"] is not None
                and _near((row["x"], row["y"]), spot, HALF_GRID)
                and row["designator"].upper().startswith(part.prefix.upper())
            ]
            label = f"{part.spec_id} (found by position ({spot[0]:g}, {spot[1]:g}))"
        if not named:
            selection.absent.append(f"part {label}")
            continue
        if len(named) > 1:
            selection.mismatches.append(
                f"part {label}: {len(named)} components answer to it "
                f"({', '.join(row['id'] for row in named)}) — which one is the plan's "
                "cannot be stated"
            )
            continue
        row = named[0]
        legs: list[str] = []
        if (
            row["x"] is None or row["y"] is None
            or not _near((row["x"], row["y"]), spot, HALF_GRID)
        ):
            legs.append(
                f"it is at ({row['x']}, {row['y']}), the plan put it at "
                f"({spot[0]:g}, {spot[1]:g})"
            )
        if part.value_key and part.value:
            if row["value"] != part.value:
                legs.append(f"its Value is {row['value']!r}, the plan wrote {part.value!r}")
        elif part.lcsc and row["lcsc"]:
            if row["lcsc"] != part.lcsc:
                legs.append(f"it was placed from {row['lcsc']}, the plan places {part.lcsc}")
        else:
            legs.append(
                "the plan claims no value write and the page reports no LCSC number, "
                "so the part's third identity leg cannot be read"
            )
        if legs:
            selection.mismatches.append(
                f"part {label} ({row['designator'] or 'no designator'}, {row['id']}): "
                + "; ".join(legs)
            )
            continue
        selection.parts.append((row["id"], row["designator"]))
        selection.matched.append(f"part {row['designator']} ({row['id']})")

    for flag in plan.change.draw_flags:
        spot = (flag.x, flag.y)
        here = [
            row for row in flag_rows
            if row["x"] is not None and row["y"] is not None
            and _near((row["x"], row["y"]), spot, HALF_GRID)
        ]
        label = f"{flag.kind} flag {flag.net} at ({spot[0]:g}, {spot[1]:g})"
        if not here:
            selection.absent.append(label)
            continue
        mine = [row for row in here if row["net"] == flag.net]
        if len(here) > 1 or not mine:
            selection.mismatches.append(
                f"{label}: the page has "
                + ", ".join(f"a {row['net'] or '(no net)'} flag {row['id']}" for row in here)
                + " there"
            )
            continue
        selection.flags.append((mine[0]["id"], flag.net))
        selection.matched.append(f"flag {flag.net} ({mine[0]['id']})")

    planned: dict[str, list[list[tuple[float, float]]]] = {}
    for wire in plan.change.draw_wires:
        planned.setdefault(wire.net, []).append(
            [(float(point[0]), float(point[1])) for point in wire.points]
        )
    unnamed = unnamed_nets(plan)
    for net, polylines in sorted(planned.items()):
        mine: list[dict[str, Any]] = []
        for row in wire_rows:
            # 069 sec.9: a flagged net's wires are drawn *unnamed*, so the page holds
            # them under no name (or under the host's own auto name) — they are the
            # plan's when their geometry lies on the plan's wiring, and the "touches
            # the plan's wiring and reaches beyond it" test below is what still
            # refuses a wire the host merged with somebody else's.
            if row["net"] != net and not (net in unnamed and not row["net"]):
                continue
            points = [(float(point[0]), float(point[1])) for point in row["points"]]
            on = [any(_on_polyline(point, line) for line in polylines) for point in points]
            if not any(on):
                continue
            if not all(on):
                stray = [point for point, hit in zip(points, on) if not hit]
                selection.mismatches.append(
                    f"wire {row['id']} ({net}) reaches the plan's wiring and also "
                    + ", ".join(f"({x:g}, {y:g})" for x, y in stray[:3])
                    + ", which the plan never drew — the host merged it with another "
                    "wire (pit 32), and deleting it would delete that wire too"
                )
                continue
            mine.append(row)
            selection.wires.append((row["id"], net))
            selection.matched.append(f"wire {net} ({row['id']})")
        for line in polylines:
            reached = [
                end for end in (line[0], line[-1])
                if any(
                    _near(end, (float(point[0]), float(point[1])), 1e-6)
                    for row in mine for point in row["points"]
                )
            ]
            if len(reached) < 2:
                selection.absent.append(
                    f"wire {net} ({line[0][0]:g}, {line[0][1]:g}) → "
                    f"({line[-1][0]:g}, {line[-1][1]:g})"
                )
    return selection
