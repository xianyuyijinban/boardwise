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

* **the carrier is a new `islands[]` key** on the presentation spec, read by
  the layout layer and by nothing else. `PresentationSpec.modules` keeps its
  meaning (a grammar-binding scope) and is not reused for this — 113's
  five-module split was refused precisely because a fragment is not a whole
  flyback, and that refusal is not re-opened here.
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

#: The keys one `islands[]` entry may state.  ``name`` is 530F's addition and is
#: optional like ``role``: the judge names what it accepts, and an island nothing
#: named writes nothing (see :class:`LayoutIsland`).
_ISLAND_KEYS = ("id", "parts", "role", "name")


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
    """

    id: str
    parts: list[str] = field(default_factory=list)
    role: str = ""
    name: str = ""

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
    value: Any, declared: Sequence[str], where: str = "islands"
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
        islands.append(LayoutIsland(
            id=island_id,
            parts=parts,
            role=_role(body.get("role"), f"{spot}.role"),
            name=_text(body.get("name"), f"{spot}.name"),
        ))

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


# ------------------------------------------------------------------ helpers
#
# Small local readers rather than imports from `presentationspec`: the islands
# are parsed by that module's boundary, so importing it back would be a cycle.
# The refusals keep the same shape and the same word ("path names itself") so a
# reader of one module's errors can read the other's.


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
