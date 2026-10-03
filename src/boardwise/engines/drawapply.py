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
from ..core.layoutplan import LayoutPart, LayoutPlan
from ..core.presentationspec import PresentationSpec
from ..core.symbolprofile import SymbolProfile, SymbolPose
from . import addcomponent

__all__ = [
    "CENSUS_CLEARANCE",
    "CENSUS_FALLBACK_HALF",
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
    "discard_selection",
    "designator_problems",
    "expected_pin_points",
    "flag_kind",
    "guard_problems",
    "islands_from_circuit",
    "library_problems",
    "live_islands",
    "module_plan",
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
#: so it stays inside the room the compiler reserved for the label. Only drawn on
#: the page path, and only where no planned wire of the net already reaches the
#: anchor — see :func:`module_plan`'s ``label_stubs``.
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
       convention is :data:`FLAG_SYMBOL_GROUND` / :data:`FLAG_SYMBOL_POWER_PREFIX`.

    A name and a symbol that disagree (a ground-named net drawn with a power
    symbol) raise rather than pick one: the flag's kind is what the editor's
    netlist carries (029-d), so picking would misname the net on the board.
    """
    by_name = str(addcomponent.power_flag_kind(net) or "")
    reference = (symbol_ref or "").upper()
    if reference == FLAG_SYMBOL_GROUND:
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
    return by_name or by_symbol


# ------------------------------------------------------------ designators


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
) -> list[tuple[str, str, str]]:
    """``[(partId, prefix, designator)]`` for a drawing, from the pool it avoids.

    The lowest free number per prefix, in plan order, with each allocation added
    to the pool as it is made — two resistors never get one number. The pool is
    `addcomponent.designator_pool`'s answer at the caller's boundary: the page's
    designators **and** the project export's (036b), because the host renames a
    collision mid-run.
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
    """
    pool_list = [name for name in pool]
    wanted = [part.designator for part in plan.change.draw_parts]
    problems: list[str] = []
    for part in plan.change.draw_parts:
        if part.designator in pool_list:
            problems.append(
                f"{part.designator} ({part.value}) is already on the page or in the "
                "project export — the plan's number was taken between plan and apply"
            )
    if problems:
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



def islands_from_circuit(
    circuit: CircuitSpec, designators: Mapping[str, str]
) -> list[PlanIsland]:
    """The netlist expectation: every placed pin and the pins it is one with.

    Built from the **CircuitSpec's nets**, mapped onto the designators the plan
    allocated. Membership, never names: an auto-named net is renumbered by the
    editor whenever the wiring changes (measured 035/036), so "these pins are
    one" is the fact the acceptance can compare (037's main judgement shape).

    The mates list **includes the pin itself** — the island *is* that set — and a
    net whose only member is one pin yields a one-element island, which is a true
    statement about a rail carried by a flag.
    """
    islands: list[PlanIsland] = []
    for net in circuit.nets:
        members = sorted(
            f"{designators[member.partition('.')[0]]}.{member.partition('.')[2]}"
            for member in net.members
            if member.partition(".")[0] in designators
        )
        for member in members:
            islands.append(PlanIsland(pin=member, mates=list(members)))
    return islands


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
) -> ChangePlan:
    """One compiled drawing, as the plan a human authorises (054 §四.1).

    Two 057 keywords, both off by default so a single-module plan is built
    exactly as before:

    * ``label_stubs`` — a label this host cannot place is otherwise carried by
      the wire of its net; a page states a shared net with a label at a *pin tip*
      (056's port), and a pin no wire of that net reaches would land on an
      unnamed net, so the two modules' same-named nets would never merge in the
      editor's project-wide netlist (G4). With it, such a label becomes a short
      stub wire carrying the name (:data:`LABEL_STUB_LENGTH`, towards the label's
      own text box) — declared in ``downgrades`` like every other landing
      adaptation;
    * ``module_label`` — how the plan's target names what it draws (a page names
      its modules; the default is the presentation's grammar, as 054 wrote it).

    The three things the layout cannot know are settled here, in this order:
    the **recipe** (a symbol ref is not a part: every part needs an LCSC number and
    a value, or the plan is refused naming the parts), the **numbers** (allocated
    from ``pool``, see `assign_designators`) and the **flags** (a rail's symbol ref
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
    book = {str(key): value for key, value in dict(profiles).items()}
    table = profile_table(book)
    known = {ref for ref, _digest in table}
    lcsc = {str(key): str(value) for key, value in dict(lcsc_by_part or {}).items()}
    values = {str(key): str(value) for key, value in dict(values_by_part or {}).items()}

    built = _Built(notes=list(notes))
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

    assignments = assign_designators(list(layout.parts), book, pool)
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

    on_pins = {
        (flag.on_pin or flag.net) for flag in built.flags if flag.on_pin
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
        if label_stubs and not carried:
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
            length = math.dist(anchor, stub)
            built.wires.append(PlanDrawWire(
                net=label.net,
                points=[anchor, stub],
                from_pin=pin_at(anchor),
                purpose="name stub (057: stands in for a label this host cannot place)",
            ))
            built.downgrades.append(
                f"net {label.net}: the compiler drew a net label at "
                f"({label.x:g}, {label.y:g}), and this host cannot place one "
                "(`sch.place_netlabel` is measured unusable, 029); no planned wire of "
                f"{label.net} reaches that point, so a {length:g}-unit stub "
                f"({label.x:g}, {label.y:g}) → ({stub[0]:g}, {stub[1]:g}) carries the "
                "name instead — without it the pin would sit on an unnamed net and the "
                "page's same-named nets would never merge in the editor's project-wide "
                "netlist (057 sec.4)"
            )
            continue
        built.downgrades.append(
            f"net {label.net}: the compiler drew a net label at "
            f"({label.x:g}, {label.y:g}), and this host cannot place one "
            "(`sch.place_netlabel` is measured unusable, 029) — the net is named on the "
            "wire itself instead (`sch.place_wire` net=…), so the netlist carries the "
            "name while the canvas shows the stub without its label text"
        )
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

    islands = islands_from_circuit(circuit, {item.spec_id: item.designator for item in built.parts})
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
    directions and lengths and refuses the drawing when none is free.
    """
    far, _direction, _length = _label_stub_candidates(label)[0]
    return far


def _label_stub_candidates(
    label: Any,
) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """``(far end, direction, length)`` for a label's stub, preferred first.

    The ladder is 099d's: the preferred run (the label's own text side, at
    :data:`LABEL_STUB_LENGTH` or the box's reach when that is shorter) first, so
    a drawing that was free before lands on exactly the same point; then the same
    length along the rest of the compass; then — the stub still blocked — the
    :data:`LABEL_STUB_LENGTHS` rungs again in all four directions. A stub that can
    take none of them is refused, never drawn across a foreign conductor.
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
    out: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    for length in lengths:
        for direction in directions:
            out.append((
                (round(x + direction[0] * length, 6),
                 round(y + direction[1] * length, 6)),
                direction,
                length,
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


def _place_label_stub(
    label: Any,
    built: "_Built",
    bodies: Mapping[str, tuple[float, float, float, float]],
    pins: Sequence[tuple[str, str, tuple[float, float]]],
) -> tuple[tuple[float, float] | None, list[str]]:
    """The first free stub far end, or ``(None, blockers)``.

    ``blockers`` names what stopped each *direction*'s preferred run — the four
    lines a refusal quotes — so "it could not be drawn" arrives with the geometry
    that made it so (053 sec.4's four categories, at page scale).
    """
    start = (float(label.x), float(label.y))
    blockers: list[str] = []
    seen_direction: set[tuple[float, float]] = set()
    for end, direction, _length in _label_stub_candidates(label):
        reason = _label_stub_blocked(label, start, end, built, bodies, pins)
        if reason is None:
            return end, blockers
        if direction not in seen_direction:
            seen_direction.add(direction)
            blockers.append(f"{_direction_text(direction)} ({_point_pair(end, end)}): {reason}")
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
            f"exactly the census the plan was built against ({len(baseline.components)} "
            f"part(s), {baseline.wire_count} wire(s), {baseline.netflag_count} flag(s); "
            f"digest {baseline.digest[:12]}…)"
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
    """Done, as a list a human reads and apply re-checks leg by leg."""
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
        + (f", starting on {item.from_pin}" if item.from_pin else "")
        + (f" ({len(item.points)} point(s))" if len(item.points) > 2 else "")
        for item in built.wires
    )
    lines.extend(
        f"a {item.kind} flag named {item.net} is on the page at "
        f"({item.x:g}, {item.y:g})"
        + (f", on {item.on_pin}" if item.on_pin else "")
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


def canvas_census(geometry: Any) -> PlanDrawBaseline:
    """The page's primitive census, from a `sch.geometry` dump (the C5 guard).

    Designators, wire count and flag count: the three things a hand edit changes
    that a compiled drawing has an opinion about. `addcomponent`'s readers are
    reused rather than re-written — they already know that a flag is a component
    with ``ComponentType: netflag`` and an empty designator (which is why the
    designator set cannot see it) and that a ``?``-suffixed designator is a part
    the editor has not numbered.
    """
    components = sorted(addcomponent.component_origins(geometry))
    wires = geometry.get("wires") if isinstance(geometry, dict) else None
    wire_count = len(wires or [])
    netflag_count = addcomponent.netflag_count(geometry)
    census = PlanDrawBaseline(
        components=components,
        wire_count=int(wire_count),
        netflag_count=int(netflag_count),
    )
    census.digest = census_digest(census)
    return census


def census_digest(census: PlanDrawBaseline) -> str:
    """One string for a census, so a report can quote it and a guard can compare."""
    payload = json.dumps(
        {
            "components": sorted(census.components),
            "wireCount": int(census.wire_count),
            "netflagCount": int(census.netflag_count),
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
                    f"the plan recorded {len(plan.change.draw_baseline.components)} "
                    f"part(s), {plan.change.draw_baseline.wire_count} wire(s) and "
                    f"{plan.change.draw_baseline.netflag_count} flag(s) "
                    f"({plan.change.draw_baseline.digest[:12]}…), the page now has "
                    f"{len(now.components)} part(s), {now.wire_count} wire(s) and "
                    f"{now.netflag_count} flag(s) ({now.digest[:12]}…) — somebody changed "
                    "the canvas after the plan was made (054 C5)"
                )
        if expect_census and now.digest != expect_census:
            problems.append(
                "the page's primitives are not the ones this run was told to expect: "
                f"expected {expect_census[:12]}…, the page holds "
                f"{len(now.components)} part(s), {now.wire_count} wire(s) and "
                f"{now.netflag_count} flag(s) ({now.digest[:12]}…) — somebody changed the "
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


def census_items(geometry: Any) -> list[dict[str, Any]]:
    """Every primitive the page holds, one row each, with its identity fields.

    The rows are what "zero change" is judged on: a part's designator, value,
    LCSC number, origin and pose; a flag's net and origin; a wire's net and its
    point list. Keyed by the page's own primitive id — the one identity the host
    keeps stable across reads. The sheet (the drawing frame) is the page, not an
    item on it, and is left out.
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
    return sorted(rows, key=lambda row: (row["kind"], row["id"]))


def census_keepouts(
    geometry: Any,
    *,
    clearance: float = CENSUS_CLEARANCE,
    fallback_half: float = CENSUS_FALLBACK_HALF,
) -> tuple[list[tuple[float, float, float, float]], list[str], list[str]]:
    """Every existing primitive as a keep-out: ``(boxes, labels, notes)`` (057 sec.2).

    ``labels[i]`` says which primitive ``boxes[i]`` came from, so a refusal that
    names ``keepouts[3]`` can be read back as "the existing R5". A component's box
    is its **measured** extent from the dump's ``bboxes`` map (the caller asks for
    it with ``bboxIds``); a component the page did not measure gets a
    :data:`CENSUS_FALLBACK_HALF` box around its origin and a note saying so — an
    assumed box is a weaker keep-out, and the reader has to know which ones are.
    A wire is one box per segment. Every box is grown by ``clearance``.
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
            f"{len(unmeasured)} existing component(s) had no measured extent, so each "
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
    a wire's net and point list). A row that is gone or that changed is one line.
    New rows are not judged here: what a run *adds* is the range check's
    business, and this function is the one that says "and nothing else moved".
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
                key for key in ("designator", "value", "lcsc", "net", "x", "y",
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
