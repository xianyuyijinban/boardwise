"""Layout islands: the blocks a page is **laid out in** (520j).

`docs/multi-island-design.md` is this module's spec. 岳's ruling (2026-10-20)
is one sentence — **岛内地线连，岛间名字接** — and everything here exists to
make that sentence decidable *before* anything is drawn.

**Two things are called an "island" in this repository, and they are not the
same thing.** A *net-island* is a set of pins one net joins (the sense
`moveblock.islands` and `cli.py`'s read-back use; 069 sec.2). A *layout-island*
— the one this module is about — is a group of parts the page is arranged in:
one place, one local wiring picture, its own ground. The design doc's §2 names
the split, and this module only implements the second:

* **the carrier is an `islands[]` key** on the presentation spec, read by
  the layout layer and by nothing else. In the original 520j reading,
  `PresentationSpec.modules` keeps its grammar-binding meaning and is not reused
  for this. The opt-in 536 archipelago reading is different: it explicitly makes
  each declared island a child of one module, without changing the legacy path.
* **the default is one implicit island holding everything.** A spec that says
  no `islands` behaves exactly as it did before this key existed — same
  published JSON, same digest, same plan, byte for byte. Multi-island layout is
  switched on by *declaring* islands and by nothing else.

**Cross-island elements get their own island.** A transformer and an
optocoupler have pins on both sides of the barrier, so no single island can hold
one and stay honest about what that island *is*: put the transformer in the
primary island and "the primary island is the parts on the primary ground"
becomes false, and the crossing nets it carries (`HVDC`, `SW` in the flyback
case) stop being crossing nets at all. So the part that *is* the barrier is
declared as an island of its own with :data:`ISLAND_ROLE_BRIDGE` — one island
per barrier part, or one island holding them all, and the caller decides. The
role table below is 岳's §7.1 list with `bridge` standing for 「变压器（跨岛
元素）」 widened to every part that spans the barrier.

**What this module does not do**: it does not decide the islands (they are
stated in the spec; the grammar-derived source is a later batch), it does not
draw anything, and it does not read a coordinate. The two facts it computes —
"which island owns this part" and "which nets cross between islands" — are the
inputs 520k/520l consume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .circuitspec import CircuitSpec

__all__ = [
    "ARCHIPELAGO_KEYS",
    "ARCHIPELAGO_KINDS",
    "ARCHIPELAGO_SIDES",
    "IMPLICIT_ISLAND_ID",
    "ISLAND_ROLE_BRIDGE",
    "ISLAND_ROLES",
    "IslandError",
    "LayoutIsland",
    "cross_island_nets",
    "declared_part_ids",
    "implicit_island",
    "island_of_part",
    "part_island_map",
    "parse_islands",
    "validate_archipelago_structure",
]

#: The island roles this build knows. 岳's ruling of 2026-10-20 (design doc §7.1)
#: names five: 正边 / 副边 / 反馈 / 变压器（跨岛元素）/ 控制器 + 去耦 — written
#: here as ``primary`` / ``secondary`` / ``feedback`` / ``bridge`` / ``control``.
#:
#: The vocabulary is **closed on purpose**, the way `presentationspec.GRAMMARS`
#: is: the role is what a later batch derives an island *from* ("grammar 按 role
#: 推导"), so a role this build does not know is a promise nobody can keep
#: rather than a free-text note. It is optional for the same reason `role` is
#: optional everywhere else in this repo — ``""`` means "not stated", and a spec
#: that states no role binds nothing.
ISLAND_ROLES: tuple[str, ...] = (
    "primary", "secondary", "feedback", "bridge", "control",
)

#: The role of an island that holds a **cross-island element** — a part whose
#: own pins sit in two domains (the flyback's transformer and its optocoupler).
#: See the module docstring for why such a part gets an island of its own.
ISLAND_ROLE_BRIDGE = "bridge"

#: The id of the implicit island an `islands`-less spec is read as. It is not a
#: legal id for a *declared* island: a spec that means "one block" says nothing,
#: and one that writes this id would be describing the default as a decision.
IMPLICIT_ISLAND_ID = "all"

#: The four keys 536 puts on an **archipelago** island (`docs/drawing-archipelago-route.md`
#: §2.2): which group it is a child of, which part it hangs off, what it is for, and
#: (optionally) the side of its group it is drawn on.  A list that states any of them
#: on any entry is read as an archipelago, and then every entry has to state the
#: first three — the two readings do not mix (see :func:`parse_islands`).
ARCHIPELAGO_KEYS: tuple[str, ...] = ("group", "owner", "kind", "side")

#: The closed vocabulary of a child island's ``kind`` (§2.2).  Closed for the same
#: reason :data:`ISLAND_ROLES` is: the kind is what a later assembler arranges the
#: island *by* (a decoupling island is placed against its owner's rail, a clock
#: island beside its pins), and a word this build does not know is a promise about
#: placement nobody can keep.
ARCHIPELAGO_KINDS: tuple[str, ...] = (
    "core", "decoupling", "bulk", "clock", "programming",
)

#: The sides a child island may be stated on (§2.2).  Same four the spec's
#: `sidePreferences` name, and optional: omitted means "no island-level
#: preference", which is not the same as "the default" and is not written as one.
ARCHIPELAGO_SIDES: tuple[str, ...] = ("left", "right", "top", "bottom")

#: The keys one `islands[]` entry may state.  ``name`` is 530F's addition and is
#: optional like ``role``: the judge names what it accepts, and an island nothing
#: named writes nothing (see :class:`LayoutIsland`).  The four archipelago keys are
#: 536's addition and are optional in the *schema* (an old island states none of
#: them) but mandatory *as a set* once any entry states one — refusal rather than
#: filling-in, because a group or an owner nobody stated is not a default.
_ISLAND_KEYS = ("id", "parts", "role", "name", *ARCHIPELAGO_KEYS)


class IslandError(ValueError):
    """The `islands` list is not one this build can read.

    Separate from :class:`boardwise.core.presentationspec.PresentationSpecError`
    so this module can be read (and, later, driven by the grammar) without
    importing the spec parser; the spec's boundary translates it, and its own
    error stays the one a caller of :meth:`PresentationSpec.from_dict` sees.
    """


@dataclass
class LayoutIsland:
    """One block the page is arranged in: its parts, and what the block is for.

    ``parts`` is *this island's* part ids — every part of the circuit the
    document places in this block, and (by the partition rule below) at most one
    island names any given part.

    ``role`` is one of :data:`ISLAND_ROLES` or ``""`` for "not stated". It is
    the machine-readable half of the block's meaning: the same word a structure
    pass will later use to *derive* islands from a circuit, so a declared island
    always wins over a derived one (「手写覆盖推导」).

    ``name`` is what a person calls the block — 530F, additive, ``""`` for "not
    stated". It exists because `draw islands propose`/`apply` ask a model for one
    (`DESIGN` §5.4: `verdict: accept` must state a `name`) and, before this field,
    the answer had nowhere to go: the judged name was written into
    `DesignIntent.blocks[].kind` and the apply report, so the *spec's* own
    `islands[]` — the one document a reader of the partition has open — could not
    say what any block was called (530E's deviation 2). It is a label, not a rule:
    nothing in the layout reads it, S-14 counts **net** names and not island
    titles, and a document that states none reads back exactly as it did before
    the field existed.

    ``group`` / ``owner`` / ``kind`` / ``side`` are 536's archipelago fields, all
    optional and all ``""`` for "not stated" (see :data:`ARCHIPELAGO_KEYS`).  They
    describe an island as a **child of a group** rather than as a block of the
    page: ``group`` is the module whose drawing it is a piece of, ``owner`` the
    part of that module's core island its picture hangs off, ``kind`` what the
    piece is for, and ``side`` where on its group it is drawn.  A list that states
    any of them is read as an archipelago and checked by
    :func:`validate_archipelago_structure`; a list that states none of them is the
    520j reading, byte for byte, and none of these fields is ever inferred.
    """

    id: str
    parts: list[str] = field(default_factory=list)
    role: str = ""
    name: str = ""
    group: str = ""
    owner: str = ""
    kind: str = ""
    side: str = ""

    @property
    def is_bridge(self) -> bool:
        """Does this island hold a cross-island element? (see the docstring)"""
        return self.role == ISLAND_ROLE_BRIDGE


def declared_part_ids(part_groups: Iterable[Sequence[str]]) -> list[str]:
    """Every part the document names, in first-mention order, without repeats.

    The reference set for the partition rule: a presentation spec carries its
    parts in its modules, and *that* is what "a part of this spec" means — the
    spec knows nothing about a circuit (the CircuitSpec is a separate document),
    so an id no module mentions is an id this document cannot place.
    """
    out: list[str] = []
    seen: set[str] = set()
    for parts in part_groups:
        for part in parts:
            if part not in seen:
                seen.add(part)
                out.append(part)
    return out


def implicit_island(part_ids: Sequence[str]) -> LayoutIsland:
    """The single island an `islands`-less spec is read as (safety invariant).

    Every part, one block, no role. Downstream code asks
    :meth:`PresentationSpec.effective_islands` instead of testing for `None`, so
    the single-island case is a *shape*, not a special case each consumer has to
    remember — the failure this avoids is one consumer forgetting and laying out
    a spec it thought was multi-island.
    """
    return LayoutIsland(id=IMPLICIT_ISLAND_ID, parts=list(part_ids))


def part_island_map(islands: Sequence[LayoutIsland]) -> dict[str, str]:
    """``part id -> island id``. Last writer wins; the parser refuses overlaps."""
    return {part: island.id for island in islands for part in island.parts}


def island_of_part(islands: Sequence[LayoutIsland], part_id: str) -> str | None:
    """The island that owns this part, or ``None`` when no island names it."""
    for island in islands:
        if part_id in island.parts:
            return island.id
    return None


def cross_island_nets(
    circuit: CircuitSpec, islands: Sequence[LayoutIsland]
) -> list[str]:
    """The nets whose pins sit in **two or more islands**, in netlist order.

    This is 岳's 「岛间名字接」 rule's trigger, and the design doc's §4 states it:
    a net's pins span ≥2 islands → the net is expressed by a name at each end; a
    net whose pins all sit in one island → it is drawn as wire. The netlist
    decides it, not a budget: every pin of the net is looked up through the
    island that owns its part, and a net that touches two different islands is
    in the answer.

    A pin whose part no island names contributes nothing — the island documents
    partition the *spec's* parts, while a circuit may carry parts the spec never
    mentions, and inventing an island for them here would be a second partition.
    (A declaration that is *wrong* — a part in two islands, or one the spec does
    not have — is refused at parse time, where the document's own facts live.)

    Returned as a list rather than a set so the caller gets the netlist's own
    order: 520l puts one stub per crossing net at each end, and a stable order
    is what makes its accounting readable.
    """
    owner = part_island_map(islands)
    out: list[str] = []
    for net in circuit.nets:
        reached: set[str] = set()
        for member in net.members:
            island_id = owner.get(member.partition(".")[0])
            if island_id is not None:
                reached.add(island_id)
        if len(reached) > 1:
            out.append(net.id)
    return out


def parse_islands(
    value: Any,
    declared: Sequence[str],
    where: str = "islands",
    *,
    modules: Sequence[Any] | None = None,
) -> list[LayoutIsland] | None:
    """Read an `islands` list, or ``None`` when the document states none.

    ``declared`` is the reference set from :func:`declared_part_ids`. Four things
    are refused rather than repaired, and each is a fact this document can
    decide on its own:

    1. **a part in two islands** — the drawing would have two answers to where
       it goes, and picking one is a silent choice about the engineer's intent;
    2. **a part in no island** — the block it belongs to is unstated, and a
       layout layer that assumed "the others" would be inventing a partition;
    3. **a part the spec does not have** — an island naming it is a statement
       about somebody else's circuit (the same split `_module_branch_order`
       keeps: whether the *circuit* declares the part is the grammar's reading,
       not this document's);
    4. **two islands with one id** — an id is how everything downstream names a
       block, so a repeat names two different things at once.

    A present-but-empty list is refused too: the way to say "one block" is to
    say nothing (that is the implicit island), and `[]` in a document carrying
    parts would otherwise be an undeclared second reading of the same thing.

    **Archipelago islands (536).** A list is read as an archipelago when any raw
    entry states one of :data:`ARCHIPELAGO_KEYS` — the document itself says which
    reading it is, and the two do not mix: in that mode every entry states
    ``group``, ``owner`` and ``kind`` (``side`` is optional), and
    :func:`validate_archipelago_structure` decides the group-level facts (one
    module per part, islands ⊆ their group, one core island per group, owner in
    the core island, …). ``modules`` is what that check needs, and it is
    **keyword-only** so the legacy call sites (and the legacy reading) are
    untouched: with no archipelago key present this function does exactly what it
    did before 536, whatever was or was not passed.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise IslandError(
            f"{where} must be a JSON list of islands, got "
            f"{type(value).__name__} — a spec with no islands states none at "
            "all and is read as the single implicit island"
        )
    if not value:
        raise IslandError(
            f"{where} is empty — a spec with no islands states none at all "
            "(omit the key: the default is the single implicit island); an "
            "empty list would place every part of this spec in no island"
        )

    archipelago = any(
        isinstance(item, dict) and any(key in item for key in ARCHIPELAGO_KEYS)
        for item in value
    )

    islands: list[LayoutIsland] = []
    seen_ids: set[str] = set()
    known = set(declared)
    for index, item in enumerate(value):
        spot = f"{where}[{index}]"
        body = _object(item, spot)
        _check_keys(body, _ISLAND_KEYS, spot)
        island_id = _text(body.get("id"), f"{spot}.id", required=True)
        if island_id == IMPLICIT_ISLAND_ID:
            raise IslandError(
                f"{spot}.id is {island_id!r}, which is the id of the implicit "
                "island a spec states by saying nothing — writing it down "
                "describes the default as if it were a decision, so a declared "
                "island takes an id of its own"
            )
        if island_id in seen_ids:
            raise IslandError(
                f"{spot}.id is {island_id!r}, already used — an island id is how "
                "everything downstream names one block, and two blocks under one "
                "name are two different things answering to the same word"
            )
        seen_ids.add(island_id)
        parts = _text_list(body.get("parts"), f"{spot}.parts")
        if not parts:
            raise IslandError(
                f"{spot}.parts is empty — an island with no parts is a caption, "
                "not a block the layout can place"
            )
        for part_index, part_id in enumerate(parts):
            if part_id not in known:
                raise IslandError(
                    f"{spot}.parts[{part_index}] is {part_id!r}, which this spec "
                    "does not have — an island is stated over the spec's own "
                    "parts (its modules' part ids), and one naming anything else "
                    "is a statement about another document"
                )
        group = owner = kind = side = ""
        if archipelago:
            group, owner, kind, side = _archipelago_fields(body, spot, where)
        islands.append(LayoutIsland(
            id=island_id,
            parts=parts,
            role=_role(body.get("role"), f"{spot}.role"),
            name=_text(body.get("name"), f"{spot}.name"),
            group=group,
            owner=owner,
            kind=kind,
            side=side,
        ))

    if archipelago:
        # The group-level reading. `modules` is None only for a caller that does
        # not hold a spec (this module stays importable on its own); such a
        # caller cannot have decided that an archipelago is what it wants, and
        # guessing the groups from the islands' own `group` fields would drop the
        # half of §2.3 that says the module's parts *are* its child islands.
        if modules is None:
            raise IslandError(
                f"{where} is an archipelago (an entry states "
                f"{', '.join(ARCHIPELAGO_KEYS)}) but no modules were passed — a "
                "child island's group, owner and core are facts about the "
                "modules, so this list cannot be checked on the islands alone: "
                "pass modules= to read it"
            )
        validate_archipelago_structure(modules, islands, where=where)
        return islands

    owner = part_island_map(islands)
    claimed = [part for part in declared if part in owner]
    for part_id in claimed:
        if sum(1 for island in islands if part_id in island.parts) > 1:
            holders = [island.id for island in islands if part_id in island.parts]
            raise IslandError(
                f"{where}: part {part_id!r} is in {len(holders)} islands "
                f"({', '.join(holders)}) — every part sits in exactly one block, "
                "and two answers about where it goes is a question the layout "
                "cannot ask back"
            )
    unplaced = [part for part in declared if part not in owner]
    if unplaced:
        raise IslandError(
            f"{where}: part(s) {', '.join(unplaced)} are in no island — every "
            "part the spec names sits in exactly one block; a part left out "
            "would be laid out against the partition with nobody having said "
            "where"
        )
    return islands


# --------------------------------------------------------------- archipelago
#
# 536's second reading: a list of *child islands*, each one a piece of a module's
# drawing. The schema half (`group`/`owner`/`kind`/`side`) is parsed above; the
# half below is the **structure** — the facts that no single entry can decide,
# because they are relations between entries and between an entry and its group.
# It is public (`__all__`) because `core.archipelago` reuses it: the parser asks
# it once at the document boundary, and the assembler asks the same function
# again on the islands it is actually about to lay out, so there is one reading
# and not two that can drift apart.


def validate_archipelago_structure(
    modules: Sequence[Any], islands: Sequence[Any], where: str = "islands"
) -> None:
    """Refuse an archipelago whose island/group structure is not the §2.3 one.

    ``modules`` and ``islands`` are read **structurally**, not by type: an object
    with ``id`` / ``parts`` / ``core`` attributes (a
    :class:`boardwise.core.presentationspec.PresentationModule`) or a mapping with
    the same keys (a decoded document) both work.  That keeps this module free of
    the spec module (importing it back would be a cycle) and lets the later
    assembler pass either.

    The hard rules, all decided from the two documents alone:

    * **one module per part, one island per part** — including a repeat *inside*
      one entry's own ``parts``: a designator written twice is still two answers
      about where it goes;
    * **an island id is never** :data:`IMPLICIT_ISLAND_ID` — that id belongs to
      the island a spec states by saying nothing, so a declared island writing it
      describes the default as a decision (the parser refuses it as well, so a
      spec built in memory is held to the same rule);
    * **an island's group is a module** and **its parts are that module's parts**
      (islands ⊆ group): an island holding another group's part is a statement
      about somebody else's drawing;
    * **a module's parts are exactly its child islands' union**, without repeats:
      the island is the placement unit, so the group's part list and its child
      islands cannot disagree;
    * **exactly one ``kind: core`` island per group**, and the module's ``core``
      part is in it: the core island is what the group is arranged around, and
      "which one" is a decision, not a scan;
    * **every island's ``owner`` is in its group's core island** — a satellite
      hangs off the core part, so an owner outside it names a connection picture
      that does not exist;
    * **``kind`` and ``side`` are closed vocabularies** (:data:`ARCHIPELAGO_KINDS`
      / :data:`ARCHIPELAGO_SIDES`), and ``side`` may be omitted.

    Not decided here: whether a satellite *shares a net* with its owner, whether a
    decoupling island holds a signal net, and whether the netlist is one a
    grammar can draw.  Those are readings of the circuit, and the circuit is not
    an argument of this function (`core.archipelago` asks them where it holds
    both documents).
    """
    module_parts: dict[str, list[str]] = {}
    module_core: dict[str, str] = {}
    modules_of_part: dict[str, list[str]] = {}
    for module in modules:
        module_id = str(_field(module, "id") or "").strip()
        if not module_id:
            raise IslandError(
                f"{where}: a module states no id — an island's group is named by "
                "a module id, so a module without one cannot be a group"
            )
        if module_id in module_parts:
            raise IslandError(
                f"{where}: more than one module is named {module_id!r} — a group "
                "is one module, and two under one name make 'island.group' name "
                "two different documents"
            )
        parts = [str(part) for part in (_field(module, "parts", ()) or ())]
        if not parts:
            raise IslandError(
                f"{where}: module {module_id!r} names no parts — its child "
                "islands are a partition of its parts, and a group with none has "
                "nothing to place"
            )
        repeated = _repeats(parts)
        if repeated:
            raise IslandError(
                f"{where}: module {module_id!r}.parts repeats part(s) "
                f"{', '.join(repeated)} — a part sits in exactly one place inside "
                "its group, and a repeat is a second answer in one list"
            )
        for part_id in parts:
            modules_of_part.setdefault(part_id, []).append(module_id)
        module_parts[module_id] = parts
        module_core[module_id] = str(_field(module, "core") or "").strip()

    for part_id, holders in modules_of_part.items():
        if len(holders) > 1:
            raise IslandError(
                f"{where}: part {part_id!r} is claimed by more than one module "
                f"({', '.join(holders)}) — every part sits in exactly one group, "
                "and the layout has no way to ask which group was meant"
            )

    island_parts: dict[str, list[str]] = {}
    island_group: dict[str, str] = {}
    island_owner: dict[str, str] = {}
    island_kind: dict[str, str] = {}
    islands_of_part: dict[str, list[str]] = {}
    for island in islands:
        island_id = str(_field(island, "id") or "").strip()
        if not island_id:
            raise IslandError(f"{where}: an island states no id")
        if island_id == IMPLICIT_ISLAND_ID:
            raise IslandError(
                f"{where}: island id {island_id!r} is the id of the implicit "
                "island a spec states by saying nothing — writing it down "
                "describes the default as if it were a decision, so a declared "
                "island takes an id of its own (the parser refuses this too; a "
                "hand-written spec reaches this check without it)"
            )
        if island_id in island_parts:
            raise IslandError(
                f"{where}: island id {island_id!r} is used twice — an island id is "
                "how everything downstream names one block"
            )
        parts = [str(part) for part in (_field(island, "parts", ()) or ())]
        if not parts:
            raise IslandError(
                f"{where}: island {island_id!r} has no parts — an island with no "
                "parts is a caption, not a placement unit"
            )
        repeated = _repeats(parts)
        if repeated:
            raise IslandError(
                f"{where}: island {island_id!r}.parts repeats part(s) "
                f"{', '.join(repeated)} — one island names a part once: a repeat "
                "inside one island is still two answers about where it sits"
            )
        group = str(_field(island, "group") or "").strip()
        if not group:
            raise IslandError(
                f"{where}: island {island_id!r} states no group — an archipelago "
                "island is a child of a module's drawing, and the group is which "
                "module that is (state group, owner and kind; side is optional)"
            )
        if group not in module_parts:
            raise IslandError(
                f"{where}: island {island_id!r} states group {group!r}, which is "
                f"not a module (the groups are {', '.join(module_parts) or 'none'}) "
                "— an island groups a module's parts, and a group that does not "
                "exist places nothing"
            )
        owner = str(_field(island, "owner") or "").strip()
        if not owner:
            raise IslandError(
                f"{where}: island {island_id!r} states no owner — the owner is the "
                "core part this island's picture hangs off (state group, owner and "
                "kind; side is optional)"
            )
        kind = str(_field(island, "kind") or "").strip()
        if kind not in ARCHIPELAGO_KINDS:
            raise IslandError(
                f"{where}: island {island_id!r} states kind {kind!r}; one child "
                f"island's kind is one of {', '.join(ARCHIPELAGO_KINDS)} — the kind "
                "is what the island is placed *as*, so an unknown one is a promise "
                "nobody keeps"
            )
        side = str(_field(island, "side") or "").strip()
        if side and side not in ARCHIPELAGO_SIDES:
            raise IslandError(
                f"{where}: island {island_id!r} states side {side!r}; one of "
                f"{', '.join(ARCHIPELAGO_SIDES)}, or omit it — omitting means 'no "
                "island-level side preference', which is not a fifth side"
            )
        foreign = [part_id for part_id in parts if part_id not in module_parts[group]]
        if foreign:
            raise IslandError(
                f"{where}: island {island_id!r} holds part(s) "
                f"{', '.join(foreign)} that module {group!r} does not claim "
                f"({', '.join(module_parts[group])}) — an island is a partition of "
                "its own group, and a part from outside it is a statement about "
                "another group's drawing"
            )
        for part_id in parts:
            islands_of_part.setdefault(part_id, []).append(island_id)
        island_parts[island_id] = parts
        island_group[island_id] = group
        island_owner[island_id] = owner
        island_kind[island_id] = kind

    for part_id, holders in islands_of_part.items():
        if len(holders) > 1:
            raise IslandError(
                f"{where}: part {part_id!r} appears in more than one island "
                f"({', '.join(holders)}) — every part sits in exactly one island, "
                "and two answers about where it goes is a question the layout "
                "cannot ask back"
            )

    for module_id, parts in module_parts.items():
        kids = [
            island_id for island_id in island_parts
            if island_group[island_id] == module_id
        ]
        if not kids:
            raise IslandError(
                f"{where}: module {module_id!r} has no child island — a group the "
                "page arranges is laid out as its child islands, so a module with "
                "no child island would be a group with nowhere to go"
            )
        union = [part_id for island_id in kids for part_id in island_parts[island_id]]
        repeated = _repeats(union)
        if repeated:
            # Already caught as 'more than one island'; kept so this rule reads as
            # the module-level statement §2.3 makes (the union has no repeats).
            raise IslandError(
                f"{where}: module {module_id!r}: its child islands repeat part(s) "
                f"{', '.join(repeated)} — the union of a group's child islands is "
                "a partition, not a bag"
            )
        unplaced = [part_id for part_id in parts if part_id not in set(union)]
        if unplaced:
            raise IslandError(
                f"{where}: module {module_id!r}.parts holds part(s) "
                f"{', '.join(unplaced)} that no child island places — the child "
                "islands' union is the module's part list, verbatim; a part left "
                "out would be laid out against the partition with nobody having "
                "said where"
            )
        cores = [island_id for island_id in kids if island_kind[island_id] == "core"]
        if len(cores) != 1:
            raise IslandError(
                f"{where}: module {module_id!r} has {len(cores)} core island(s) "
                f"({', '.join(cores) or 'none'}); exactly one child island of a "
                "group is kind 'core' — the core island holds the part the group "
                "is arranged around"
            )
        core_island = cores[0]
        core_parts = island_parts[core_island]
        core_part = module_core[module_id]
        if not core_part:
            raise IslandError(
                f"{where}: module {module_id!r} states no core — a group is laid "
                f"out around one part, and its core island {core_island!r} holds "
                "it (state core on the module)"
            )
        if core_part not in core_parts:
            raise IslandError(
                f"{where}: module {module_id!r}.core {core_part!r} is not in its "
                f"core island {core_island!r} — the core island holds the part its "
                "group is arranged around, so the two statements must agree"
            )
        for island_id in kids:
            if island_owner[island_id] not in core_parts:
                raise IslandError(
                    f"{where}: island {island_id!r} states owner "
                    f"{island_owner[island_id]!r}, which is not in the core island "
                    f"{core_island!r} of group {module_id!r} — an island's owner is "
                    "the core part its connection picture hangs off, and an owner "
                    "outside the core island names a picture that does not exist"
                )


# ------------------------------------------------------------------ helpers
#
# Small local readers rather than imports from `presentationspec`: the islands
# are parsed by that module's boundary, so importing it back would be a cycle.
# The refusals keep the same shape and the same word ("path names itself") so a
# reader of one module's errors can read the other's.


def _field(item: Any, name: str, default: Any = "") -> Any:
    """One field of a module or island, read from a mapping or an object.

    See :func:`validate_archipelago_structure`: the structure check is reused by
    `core.archipelago`, which may hold decoded documents or dataclasses.
    """
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _repeats(items: Sequence[str]) -> list[str]:
    """The values that occur more than once, in first-repeat order."""
    seen: set[str] = set()
    repeated: list[str] = []
    for item in items:
        if item in seen and item not in repeated:
            repeated.append(item)
        seen.add(item)
    return repeated


def _side(value: Any, where: str) -> str:
    """An island's stated side, or ``""`` for "not stated"."""
    if value is None or value == "":
        return ""
    side = _text(value, where, required=True)
    if side not in ARCHIPELAGO_SIDES:
        raise IslandError(
            f"{where} is {side!r}; one of {', '.join(ARCHIPELAGO_SIDES)}, or omit "
            "it — an island states the side of its group it is drawn on, and "
            "omitting it means no preference rather than a default"
        )
    return side


def _kind(value: Any, where: str) -> str:
    """An island's stated kind, which the archipelago reading requires."""
    if value is None or value == "":
        raise IslandError(
            f"{where} is required and missing — an archipelago island states "
            f"group, owner and kind (side is optional), and the kind is one of "
            f"{', '.join(ARCHIPELAGO_KINDS)}"
        )
    kind = _text(value, where, required=True)
    if kind not in ARCHIPELAGO_KINDS:
        raise IslandError(
            f"{where} is {kind!r}; one child island's kind is one of "
            f"{', '.join(ARCHIPELAGO_KINDS)} — the kind is what the island is "
            "placed *as*, so an unknown one is a promise nobody keeps"
        )
    return kind


def _archipelago_fields(
    body: dict[str, Any], spot: str, where: str
) -> tuple[str, str, str, str]:
    """The four archipelago keys of one raw entry: group, owner, kind, side.

    Called only in the archipelago reading. A raw entry that states *none* of the
    four is the mixed case and is refused as such: the document chose the
    archipelago reading by stating one elsewhere, so an old-style entry here is
    an island with no group, owner or kind, and inventing them would be the
    parser deciding the partition.
    """
    if not any(key in body for key in ARCHIPELAGO_KEYS):
        raise IslandError(
            f"{spot} states none of {', '.join(ARCHIPELAGO_KEYS)} — {where} is read "
            "as an archipelago because another entry states one of them, and a "
            "document does not mix the two readings: state group, owner and kind "
            "on every island (side is optional), or state none of the four anywhere"
        )
    missing = [key for key in ("group", "owner", "kind") if key not in body]
    if missing:
        raise IslandError(
            f"{spot}.{missing[0]} is required and missing — an archipelago island "
            "states group (its module), owner (the core part its picture hangs off) "
            "and kind (what it is for), and none of the three has a default that "
            "would not be the parser deciding the partition"
        )
    group = _text(body.get("group"), f"{spot}.group", required=True)
    owner = _text(body.get("owner"), f"{spot}.owner", required=True)
    kind = _kind(body.get("kind"), f"{spot}.kind")
    side = _side(body.get("side"), f"{spot}.side")
    return group, owner, kind, side


def _role(value: Any, where: str) -> str:
    """An island's stated role, or ``""`` for "not stated"."""
    if value is None or value == "":
        return ""
    role = _text(value, where, required=True)
    if role not in ISLAND_ROLES:
        raise IslandError(
            f"{where} is {role!r}; this build knows {', '.join(ISLAND_ROLES)} — "
            "the role is what a layout derives an island *from*, so an unknown "
            "one is a promise nobody can keep; state one of them or state none"
        )
    return role


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IslandError(
            f"{where} must be a JSON object, got {type(value).__name__}"
        )
    return value


def _text(value: Any, where: str, required: bool = False) -> str:
    if value is None:
        if required:
            raise IslandError(f"{where} is required and missing")
        return ""
    if not isinstance(value, str):
        raise IslandError(f"{where} must be a string, got {value!r}")
    if required and not value.strip():
        raise IslandError(f"{where} is empty")
    return value.strip()


def _text_list(value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise IslandError(f"{where} must be a list, got {value!r}")
    return [
        _text(item, f"{where}[{index}]", required=True)
        for index, item in enumerate(value)
    ]


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise IslandError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: "
            f"{', '.join(allowed)} — the schema is closed on purpose: a key this "
            "build does not read would otherwise be an intent nobody honours"
        )
