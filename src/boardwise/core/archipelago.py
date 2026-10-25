"""The archipelago contract, read against the circuit and the plan (536).

`docs/drawing-archipelago-route.md` splits 536 into three readings, and this is
the one that needs a second document:

* **schema** — ``group`` / ``owner`` / ``kind`` / ``side`` on an ``islands[]``
  entry, parsed at the document boundary (`islands.parse_islands`) and
  surfaced as :attr:`PresentationSpec.is_archipelago`;
* **structure** — one group per part, islands ⊆ their group, one core island per
  group, every owner inside it: `islands.validate_archipelago_structure`, shared
  with the parser so there is one reading and not two that can drift;
* **the circuit-reading half, which lives here** — whether a satellite touches
  its owner, whether a decoupling island holds a signal, whether the
  presentation places exactly the circuit's parts, and whether a plan's stamped
  partition is the declared one.

Separate module because `islands.py` never sees a netlist, and the plan check is
a fact about two documents that no parser can decide.  Nothing here lays
anything out, reads a coordinate, parses a note, or writes a second netlist.
All three functions share one shape: **legacy is not an error** — a spec stating
none of the four keys is the 520j reading and passes untouched.
"""

from __future__ import annotations

from typing import Sequence

from .circuitspec import CircuitSpec
from .islands import IslandError, LayoutIsland, validate_archipelago_structure
from .layoutplan import LayoutPlan
from .presentationspec import PresentationSpec

__all__ = [
    "ArchipelagoError",
    "derive_archipelago_ports",
    "validate_archipelago",
    "validate_archipelago_island_plan",
    "validate_archipelago_plan",
]

#: Kinds that exist to hold a supply: no signal net, and a shared power net (§2.3).
_RAIL_KINDS = frozenset({"decoupling", "bulk"})


class ArchipelagoError(ValueError):
    """The archipelago contract is broken, and this build says who and why.

    A ``ValueError`` like every refusal in this document layer, so ``except
    ValueError`` around a compile still works.  Separate from :class:`IslandError`
    because an island list decides its own structure, while this error may be a
    relation between the list, the circuit and the plan.
    """


def validate_archipelago(
    circuit: CircuitSpec, presentation: PresentationSpec
) -> None:
    """Refuse an archipelago whose islands do not sit on the circuit's nets.

    In decision order: legacy passes; the structure pass runs (its
    :class:`IslandError` re-raised as :class:`ArchipelagoError`); the circuit's
    parts and the presentation's module parts must be one set; every non-core
    island shares a net with its ``owner``; and a ``decoupling`` / ``bulk`` island
    holds no ``signal`` net and shares a ``power`` net with that owner.  Multiple
    groups are allowed — §2.3's rules are per module.
    """
    if not presentation.is_archipelago:
        return
    islands = _structure(presentation)
    _require_same_parts(circuit, presentation)
    nets_of_part = _nets_of_part(circuit)
    net_by_id = {net.id: net for net in circuit.nets}
    for island in islands:
        if island.kind == "core":
            continue
        island_nets = set().union(
            *(nets_of_part.get(part, set()) for part in island.parts)
        )
        shared = island_nets & nets_of_part.get(island.owner, set())
        if not shared:
            raise ArchipelagoError(
                f"island {island.id} shares no net with its owner "
                f"{island.owner} — a child island is a picture hung off its "
                "owner, and a picture attached to nothing is not part of that "
                "group's drawing (§2.3)"
            )
        if island.kind in _RAIL_KINDS:
            signals = sorted(
                net for net in island_nets if net_by_id[net].cls == "signal")
            if signals:
                raise ArchipelagoError(
                    f"island {island.id} kind {island.kind} may not hold signal "
                    f"net(s) {', '.join(signals)} — a {island.kind} island holds a "
                    "supply, and a signal net inside it makes it a second drawing "
                    "of the owner's picture (§2.3)"
                )
            if not any(net_by_id[net].cls == "power" for net in shared):
                raise ArchipelagoError(
                    f"island {island.id} kind {island.kind} shares no power net "
                    f"with owner {island.owner} — a {island.kind} island decouples "
                    "the owner's rail, so the two must be on one power net, not "
                    "merely near each other (§2.3)"
                )


def derive_archipelago_ports(
    circuit: CircuitSpec, presentation: PresentationSpec
) -> tuple[dict[str, set[str]], set[str]]:
    """``net.members → part → island``: the ports, and the nets that stay inside.

    For an archipelago the contract is checked **first**:
    :func:`validate_archipelago` runs before any net is read, so a structure or
    part-coverage breach — including a repeated part — is refused here and not
    last-wins'd away by the ``part → island`` table.

    The islands are then the only input on the presentation side, read through
    :meth:`PresentationSpec.effective_islands` (an islands-less spec is the single
    implicit island: no ports, every net that touches it is internal; a net that
    touches no declared island is skipped).  No handwritten ``ports`` is
    read and the schema has none (§2.1).  A net reaching two or more islands is a
    port of **each** island it touches (「岛间名字接」); one that stays inside an
    island is ``internal``.  Every declared island appears in the answer, even one
    no net crosses.

    A member whose part is in no island is read two ways, because the two
    readings ask different questions:

    * **archipelago** — refused (:class:`ArchipelagoError`): every circuit part is
      in exactly one island, so an unplaced pin is a partition that dropped it;
    * **legacy** — skipped, exactly as :func:`boardwise.core.islands.cross_island_nets`
      does: the island documents partition the *spec's* parts while a circuit may
      carry parts the spec never mentions, and inventing an island for them here
      would be a second partition.  A net that touches no declared island at all
      is skipped too — it is not evidence that anything stays inside.
    """
    archipelago = presentation.is_archipelago
    if archipelago:
        validate_archipelago(circuit, presentation)
    islands = presentation.effective_islands()
    ports: dict[str, set[str]] = {island.id: set() for island in islands}
    owner = {part: island.id for island in islands for part in island.parts}
    internal: set[str] = set()
    for net in circuit.nets:
        touched: list[str] = []
        for member in net.members:
            island_id = owner.get(member.split(".", 1)[0])
            if island_id is None:
                if archipelago:
                    raise ArchipelagoError(
                        f"net {net.id} member {member}: its part is in no island "
                        "— ports are derived through the partition, so a pin it "
                        "does not place has no island to be a port of (§2.1)"
                    )
                continue
            if island_id not in touched:
                touched.append(island_id)
        if not touched:
            # Legacy only (an archipelago places every part): a net no declared
            # island touches says nothing about what stays inside one.
            continue
        if len(touched) < 2:
            internal.add(net.id)
            continue
        for island_id in touched:
            ports[island_id].add(net.id)
    return ports, internal


def validate_archipelago_plan(
    plan: LayoutPlan, presentation: PresentationSpec
) -> None:
    """Refuse a plan whose stamped partition is not the declared one.

    Legacy passes (an unstamped plan is the 520j plan, byte for byte).  For an
    archipelago the structure is checked first, then the islands become the
    expected ``part → (group, island)`` table and are compared with
    ``plan.parts`` **exactly**: a part the plan lacks, one it adds, one twice, and
    an empty / wrong group or island are all refused.  Nothing is corrected —
    identity is not filled in, and not read out of ``notes`` or coordinates.
    """
    if not presentation.is_archipelago:
        return
    islands = _structure(presentation)
    _compare_partition(plan, _expected_partition(islands))


def validate_archipelago_island_plan(
    plan: LayoutPlan, presentation: PresentationSpec, island_id: str
) -> None:
    """Refuse a plan that is not exactly **one** declared island's own picture (538A).

    The same reading as :func:`validate_archipelago_plan`, over a smaller expected
    set: the original presentation's structure runs first (through the same
    :func:`_structure`, so a broken island list is refused for the same reason and
    in the same words), then the expected ``part → (group, island)`` table holds
    only ``island_id``'s parts and the comparison is the *same* comparator — a
    missing part, a part from another island, a duplicate, and an empty / wrong
    group or island are all refused here too, not by a second, near-copy of the
    rules.

    Two sentences differ on purpose, because a smaller expectation asks a smaller
    question: a part this plan places but the island does not own is reported as
    **outside this island** (the presentation *does* declare it — elsewhere), never
    as a part the presentation lacks.  An unknown ``island_id`` is refused by name
    rather than checked against an empty expectation, which would report every
    part in the plan as stray.

    This is a **block-level** answer (§3-538A): it says one island's local picture
    carries that island's partition and nothing else.  It does not say the island
    compiles, assembles, packs, or may be drawn.
    """
    if not presentation.is_archipelago:
        raise ArchipelagoError(
            f"the presentation declares no archipelago island {island_id!r} — an "
            "island plan is one island of an archipelago, and a presentation that "
            "states no island identity has none to scope a plan to (§2.2)"
        )
    islands = _structure(presentation)
    island = next((item for item in islands if item.id == island_id), None)
    if island is None:
        raise ArchipelagoError(
            f"the presentation declares no island {island_id!r} — it declares "
            f"{', '.join(sorted(item.id for item in islands))}; an island plan is "
            "named by the island it draws, and an unknown id would grade the plan "
            "against a partition nobody stated (§2.2)"
        )
    _compare_partition(plan, _expected_partition([island]), island_id=island.id)


# ----------------------------------------------------------------- helpers


def _expected_partition(
    islands: Sequence[LayoutIsland],
) -> dict[str, tuple[str, str]]:
    """The declared partition as ``part id → (group, island id)``.

    The one place a plan's expectation is built.  :func:`validate_archipelago_plan`
    hands it **every** island; :func:`validate_archipelago_island_plan` hands it
    the one island it scopes to — the difference between the two readings is the
    input to this function, not a second table beside it.
    """
    expected: dict[str, tuple[str, str]] = {}
    for island in islands:
        for part_id in island.parts:
            expected[part_id] = (island.group, island.id)
    return expected


def _stated_partition(plan: LayoutPlan) -> dict[str, tuple[str, str]]:
    """The partition the plan itself states, with "two answers" refused first."""
    stated: dict[str, tuple[str, str]] = {}
    for entry in plan.parts:
        if entry.part_id in stated:
            # The same sentence for both readings: one part, one island — a scoped
            # plan repeating a part is not a smaller problem than a page doing it.
            raise ArchipelagoError(
                f"the plan places part {entry.part_id} twice — a part sits in "
                "exactly one island, so two entries for it are two answers about "
                "where it goes (§2.3)"
            )
        stated[entry.part_id] = (entry.group, entry.island)
    return stated


def _compare_partition(
    plan: LayoutPlan,
    expected: dict[str, tuple[str, str]],
    *,
    island_id: str = "",
) -> None:
    """Compare a plan's stated partition with `expected`, exactly.

    ``island_id`` empty is the whole-page reading: every message is the one 536
    wrote, verbatim, because that behaviour and its error semantics are a
    contract.  A stated ``island_id`` is the scoped reading: missing and extra are
    told apart by saying *which island* the plan is supposed to be, and the extra
    sentence names the part as **outside this island** — the presentation does
    declare it, and claiming otherwise would be a false statement about the
    document.  Every other branch is shared, so the two readings cannot drift.
    """
    stated = _stated_partition(plan)
    missing = sorted(set(expected) - set(stated))
    if missing:
        if island_id:
            raise ArchipelagoError(
                f"the plan places no part {', '.join(missing)} — the presentation "
                f"declares it in island {island_id!r}, and an island plan carries "
                "that island's own parts (§2.3)"
            )
        raise ArchipelagoError(
            f"the plan places no part {', '.join(missing)} — the presentation "
            "declares an island for it, so the plan does not carry the declared "
            "partition (§2.3)"
        )
    extra = sorted(set(stated) - set(expected))
    if extra:
        if island_id:
            raise ArchipelagoError(
                f"the plan places part(s) {', '.join(extra)} outside island "
                f"{island_id!r} — the presentation declares them in another "
                "island, and one island's plan is that island's own picture; a "
                "part another island owns is not this drawing's (§2.3)"
            )
        raise ArchipelagoError(
            f"the plan places part(s) {', '.join(extra)} the presentation does "
            "not declare — an archipelago plan names each part's declared island, "
            "and an undeclared part has none to name (§2.3)"
        )
    for part_id, (group, island) in stated.items():
        want = expected[part_id]
        if (group, island) != want:
            if island_id:
                raise ArchipelagoError(
                    f"the plan places part {part_id} as group {group!r}, island "
                    f"{island!r}; island {island_id!r} declares group {want[0]!r}, "
                    f"island {want[1]!r} — an island plan's identity is the "
                    "declared one, verbatim; an empty value is 'not stated', not "
                    "'anywhere' (§2.3)"
                )
            raise ArchipelagoError(
                f"the plan places part {part_id} as group {group!r}, island "
                f"{island!r}; the presentation declares group {want[0]!r}, "
                f"island {want[1]!r} — the plan's partition is the declared one, "
                "verbatim; an empty value is 'not stated', not 'anywhere' (§2.3)"
            )


def _structure(presentation: PresentationSpec) -> Sequence[LayoutIsland]:
    """The declared islands after the structure pass; ``IslandError`` translated.

    The parser asks this once at the document boundary; it is asked again here on
    the islands a caller holds — one reading, used twice.
    """
    try:
        validate_archipelago_structure(
            presentation.modules, presentation.islands or ()
        )
    except IslandError as exc:
        raise ArchipelagoError(str(exc)) from exc
    return list(presentation.islands or ())


def _require_same_parts(
    circuit: CircuitSpec, presentation: PresentationSpec
) -> None:
    """The circuit's parts and the presentation's module parts are one set."""
    circuit_parts = set(circuit.part_ids())
    declared = set(presentation.declared_part_ids())
    stray = sorted(declared - circuit_parts)
    if stray:
        raise ArchipelagoError(
            f"the presentation names part(s) {', '.join(stray)} the circuit does "
            "not have — an archipelago places the circuit's own parts, and a spec "
            "naming another board's part draws a component that is not there (§2.1)"
        )
    unplaced = sorted(circuit_parts - declared)
    if unplaced:
        raise ArchipelagoError(
            f"the circuit has part(s) {', '.join(unplaced)} the presentation does "
            "not place — one left out would be laid out against the partition with "
            "nobody having said where (§2.3)"
        )


def _nets_of_part(circuit: CircuitSpec) -> dict[str, set[str]]:
    """``part id → the net ids its pins sit on``, from the circuit alone."""
    out: dict[str, set[str]] = {part: set() for part in circuit.part_ids()}
    for net in circuit.nets:
        for member in net.members:
            out.setdefault(member.split(".", 1)[0], set()).add(net.id)
    return out
