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
    "DrawPlanError",
    "HALF_GRID",
    "SOURCE_BASIS",
    "all_satisfied",
    "canvas_census",
    "census_digest",
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
) -> ChangePlan:
    """One compiled drawing, as the plan a human authorises (054 §四.1).

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
    for label in layout.labels:
        covered = any(flag.net == label.net for flag in built.flags)
        if covered:
            built.notes.append(
                f"net {label.net}: the label the compiler drew is not placed separately — "
                "the rail flag carries the same name in the editor's netlist"
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
            module=f"{presentation.grammar_ref} ({len(built.parts)} part(s); nets {module_line})",
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


def _wire_problems(plan: ChangePlan, geometry: Any) -> list[str]:
    """Each planned wire's own endpoints, under the net it belongs to.

    A *lenient* reading on purpose, and the module says so: the host is free to
    split a polyline or to merge two collinear ones (measured: what comes back is
    a point list, not the segments that were sent — pit 26), and neither changes
    where the wire reaches. What must hold is that both ends of every planned wire
    are vertices of that net's own wiring on the page, and that the net's total
    length did not shrink. The netlist leg is the acceptance's main judgement;
    this one says "the drawn thing is on the canvas".
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
    for wire in plan.change.draw_wires:
        have = vertices.get(wire.net, set())
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
    for net, wanted in sorted(planned_length.items()):
        have = lengths.get(net, 0.0)
        if have + HALF_GRID < wanted:
            problems.append(
                f"net {net}: the plan draws {wanted:g} units of wire and the page holds "
                f"{have:g} — a segment did not land"
            )
    return problems
