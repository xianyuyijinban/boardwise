"""The intent proposer (109 A4): one `DesignIntent` document -> one `PresentationSpec` draft.

Today the grammars read the contract **one clause at a time** — 095's three sources
for a `power-entry` branch order, 098's three for an `ic-periphery` core — so a
reader who wants to see "what would this contract draw" has to run every grammar
and reassemble the answers. This module does the opposite: it reads the contract
**once** and writes down a whole draft of the presentation — the module list, the
flow and the roles — so a model or an engineer gets one picture to edit instead of
a rule book to satisfy.

**A draft is a proposal.** It goes through the *same* closed schema as a
hand-written spec (:class:`~boardwise.core.presentationspec.PresentationSpec`), it
loads and validates there, and the existing compiler still judges it: this module
writes, it does not decide correctness. Two consequences it takes seriously:

* **Nothing is guessed to fill a hole.** A kind outside the declared table, a core
  two sources disagree about, a flow direction no role table entry decides — each
  is left empty and *named* in the report ("找不到 ≠ 已清", R3). A proposal that
  filled them in would be a second opinion nobody asked for.
* **Where the existing readers already conclude something, the draft writes their
  conclusion** (the branch order): the value is taken from the consumption path
  itself, so "the proposer does not move the drawing" holds by construction —
  what is written is what the reader derived, and where it derives nothing the
  field stays empty and its own three sources carry on.

The four rules, and what each one reads:

1. **The module list** — `blocks[].id` -> `module.id`, `blocks[].parts` ->
   `module.parts`, `blocks[].kind` -> `module.grammar_ref` through
   :data:`KIND_GRAMMARS`, a **closed, declared table** whose members come from two
   sources that already exist: the grammar registry (`GRAMMARS` — a kind spelled
   exactly as a grammar name states that grammar) and the contract's own kind
   vocabulary (`designintent.KIND_CURRENT_SENSE`, whose block is the shape
   `ic-periphery` draws: a shunt hanging off the core's own pin, 098 §四.10). A
   kind outside the table is **not guessed**: the module is kept, `grammarRef` is
   empty, and the report says so — a person or a model fills it in. `module.role`
   is the contract's own word for the block (`kind`), falling back to the block's
   id when it states none: the field is required by the schema, and inventing a
   role word would be this module's own claim.
2. **The core** — the same source order 098 §一 uses: `modules[].core` (absent
   here: the draft *is* the product) -> the intent's declaration (the unique part
   of a block's parts above two pins) -> the structure (the unique strict pin-count
   maximum of the group). **A conflict is not adjudicated**: the field is left
   empty and both originals are quoted in the module's notes, in 098's own wording
   — the one fact a grammar cannot derive is not this module's to pick either.
   It is written only into a module whose grammar is `ic-periphery`: that is the
   grammar that reads `core`, and a key nobody reads would be an intent nobody
   honours (the schema is closed for exactly that reason).
3. **The flow** — adjacency from the parts the blocks *share a net* with (two
   groups with parts on one net are a candidate edge, and the net is quoted as the
   evidence), and **direction only from** :data:`KIND_FLOW_ROLES`, the declared
   kind role table: a `source` feeds a `sink`, and nothing else is a direction.
   A candidate whose direction no entry decides is reported `underdetermined` with
   both kinds and the reason — never guessed. `mainPath` (056 §1's one edge the
   page may draw as a whole wire) is marked only when **two** things are decidable
   at once: the flow is a single chain through every group, and every edge of that
   chain crosses **exactly one** net which is not a ground — the crossing is what
   the whole-wire exception names, and a mark on the wrong net is a refusal rather
   than a downgrade (096). Otherwise nothing is marked and the report says which
   half failed.
4. **The roles (bulk/TVS)** — `modules[].branch_order` for a `power-entry` module,
   and its value is the branch order the **existing reader** (`power_entry`)
   concludes from the very same contract: the contract's own clamping claims
   (`decisions[]`/`blocks[].kind`, the same `CLAMP_TOKENS` list, imported rather
   than copied) move a branch, the draft writes the moved order; when the contract
   states nothing the claim is already the designator order, the field stays empty
   and the grammar's own three sources carry on. That is rule 4's "声明了才抄":
   *what* is the TVS is a fact about values and packages, and 053 §6 forbids
   reading it here or in a grammar — the contract says it, and this module only
   writes down what its readers made of it.

**What this module deliberately does not do** (the task book's three boundaries):
the page compiler still reads no contract (057's page path is untouched — a page's
module boundaries and page-level flow are the page document's business), the CLI
still takes an **explicit** `--intent PATH` (the user-level default
`<home>/design-intent/<uuid>.json` needs a projectUuid, and this command runs
before anything names a project), and **no page-level flow wiring** is proposed
(a module's cross-module connection is the page compiler's routing, not a draft's
business). The draft carries modules and `flow` and nothing else — `labelPolicy`,
`portRoles`, `mainPaths` and `userLocks` are not proposed: they are statements
about a drawing this document has not seen.

Offline, deterministic, text in and text out: no network, no clock, no editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Sequence

from ..core.circuitspec import CircuitSpec, SpecNet
from ..core.designintent import (
    KIND_CURRENT_SENSE,
    DesignIntent,
    IntentBlock,
    IntentDecision,
    IntentSource,
)
from ..core.presentationspec import (
    GRAMMARS,
    FlowEdge,
    PresentationModule,
    PresentationSpec,
)
from .grammar import grammar_for
from .grammar import ic_periphery
from .grammar import power_entry
from .grammar.base import pins_of_part

__all__ = [
    "FLOW_ROLES",
    "FLOW_SINK",
    "FLOW_SOURCE",
    "KIND_FLOW_ROLES",
    "KIND_GRAMMARS",
    "ModuleDraft",
    "Proposal",
    "ProposalError",
    "propose",
]


class ProposalError(ValueError):
    """The caller handed the proposer something it cannot read.

    Input problems are never exceptions — an unreadable *contract* is the CLI's
    to refuse, and a document that states something strange comes back as a
    report row. This is for a programming error at the call site: a contract that
    is neither a `DesignIntent` nor an `IntentSource`.
    """


# ---------------------------------------------------------------- vocabularies

#: The two ends a group may stand at in the flow. Deliberately only two: a table
#: of richer roles (regulator / bridge / …) would be this module's own theory of
#: electricity, and the direction it derives is a claim about the board.
FLOW_SOURCE = "source"
FLOW_SINK = "sink"
FLOW_ROLES: tuple[str, ...] = (FLOW_SOURCE, FLOW_SINK)

#: **kind -> grammar**, closed. Two sources, and no member beyond them:
#:
#: * the five grammar names of the registry — a kind spelled exactly as a grammar
#:   name states the idiom the group is drawn in, and `GRAMMARS` is the closed
#:   list (a grammar is a promise about what will be visible, so a name outside it
#:   is refused rather than replaced with a generic layout);
#: * the contract's own named kind, `current-sense` — 098's `ic-periphery` is the
#:   grammar whose shape that block has (a shunt hanging off one of the core's own
#:   pins, with the core read from `blocks[].parts`), and it is the one kind the
#:   contract vocabulary names (`designintent.KIND_CURRENT_SENSE`).
#:
#: Everything else is **unmapped on purpose**: a kind the table does not carry
#: (a `buck`, a `gate-drive`, a word this build has never seen) is a drawing idiom
#: nobody has written a grammar for yet, and a proposal that picked the nearest
#: one would be promising a drawing the compiler cannot keep.
KIND_GRAMMARS: dict[str, str] = {
    **{name: name for name in GRAMMARS},
    KIND_CURRENT_SENSE: ic_periphery.NAME,
}

#: **kind -> its end in the flow**, closed and deliberately smaller than the table
#: above. Mapping a kind to a *drawing* is a claim about the idiom; mapping it to a
#: *direction* is a claim about the board, and this module states only the two the
#: repository already states elsewhere: the inlet feeds the board (`power-entry`,
#: the kind the shipped contract's `inlet` names, and the grammar whose entry the
#: supply enters at), and a sense chain is where the flow arrives (the contract's
#: one named kind, whose `feeds` point at somebody else's pin). Two groups whose
#: kinds give no direction are reported `underdetermined` — which group feeds which
#: is exactly the fact a later reader has to be told.
KIND_FLOW_ROLES: dict[str, str] = {
    power_entry.NAME: FLOW_SOURCE,
    KIND_CURRENT_SENSE: FLOW_SINK,
}

#: What a block's own keys were read for, and which of them no consumer reads.
_BLOCK_KEYS = ("id", "parts", "kind", "provenance")
_BLOCK_UNUSED = ("requires", "feeds")

#: The decision keys the drawing side reads, and the one it does not.
_DECISION_KEYS = ("subject", "decision", "rationale", "provenance")
_DECISION_UNUSED = ("value",)

#: The status of a block row in the report.
STATUS_MODULE = "module"
STATUS_UNMAPPED = "unmapped-kind"
STATUS_NO_KIND = "no-kind"
STATUS_NO_PARTS = "no-parts"
STATUS_NO_ID = "no-id"
STATUS_DUPLICATE_ID = "duplicate-id"


# ------------------------------------------------------------------- results


@dataclass
class ModuleDraft:
    """One block's module, with what the proposal read for it and wrote into it."""

    block_id: str
    kind: str
    module: PresentationModule | None
    status: str = STATUS_MODULE
    notes: list[str] = field(default_factory=list)


@dataclass
class Proposal:
    """A draft presentation, and the report that says how it was read.

    ``spec`` is the draft itself — the document a caller prints, writes or hands
    to the compiler. ``report`` is the same run as data: the two declared tables,
    one row per module with the notes that explain it, the flow's edges and its
    undetermined candidates, what was read out of every contract element, and the
    list of everything that was **not** used. ``ok`` is "the draft has a module":
    a proposal with no module is a refusal (there is nothing to draw), and the
    report says which blocks could not become one and why.
    """

    spec: PresentationSpec
    report: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    drafts: list[ModuleDraft] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.spec.modules)


# ---------------------------------------------------------------------- entry


def propose(
    intent: DesignIntent | IntentSource,
    circuit: CircuitSpec | None = None,
    *,
    path: str = "",
    circuit_path: str = "",
) -> Proposal:
    """Turn this contract into a draft presentation, with the netlist when there is one.

    ``intent`` may be a bare document or the :class:`IntentSource` carrier 094 put
    in `core` (a document *and* the file it came from — every question this
    report answers is answered by path). ``circuit`` is **optional and absent by
    default**: the document alone decides the module list and the roles, while the
    netlist decides the three facts a document cannot (which groups share a net,
    which part is a group's core, which parts hang between the rails) — without it
    those three stay empty and the report names the missing input rather than
    guessing (`R3`).

    Nothing raises on a well-formed contract: an element the proposal cannot use
    comes back in the report.
    """
    document, source_path = _document(intent, path)
    notes: list[str] = []
    drafts, skipped = _drafts(document)
    spec = PresentationSpec(
        modules=[draft.module for draft in drafts if draft.module is not None]
    )
    _propose_cores(drafts, document, circuit, source_path)
    _propose_branch_order(drafts, spec, circuit, intent, circuit_path, notes)
    spec.flow, undetermined, main_note = _propose_flow(drafts, circuit)
    reads, unread = _readings(document, drafts, skipped)
    report: dict[str, Any] = {
        "command": "propose",
        "contract": source_path,
        "circuit": str(circuit_path or ""),
        "kindGrammars": dict(KIND_GRAMMARS),
        "kindFlowRoles": dict(KIND_FLOW_ROLES),
        "modules": [_module_row(draft) for draft in drafts if draft.module is not None],
        "unmapped": [
            draft.block_id for draft in drafts if draft.status != STATUS_MODULE
        ],
        "skipped": skipped,
        "flow": {
            "edges": [
                {
                    "from": edge.from_module,
                    "to": edge.to_module,
                    "mainPath": edge.main_path,
                }
                for edge in spec.flow
            ],
            "undetermined": undetermined,
            "mainPath": main_note,
        },
        "reads": reads,
        "unread": unread,
        "notes": list(notes),
    }
    return Proposal(spec=spec, report=report, notes=notes, drafts=drafts)


def _document(
    intent: DesignIntent | IntentSource, path: str
) -> tuple[DesignIntent, str]:
    """``(document, its path)`` — both spellings a caller reaches naturally.

    The carrier is preferred over a bare document because it knows the file the
    questions have to point at; a bare document is what a test or an in-memory
    caller has, and its path is then whatever the caller says (empty means "no
    file" — the report says so rather than inventing a name).
    """
    if isinstance(intent, IntentSource):
        return intent.document, str(intent.path or path or "")
    if isinstance(intent, DesignIntent):
        return intent, str(path or "")
    raise ProposalError(
        f"intent must be an IntentSource or a DesignIntent, got "
        f"{type(intent).__name__} — a contract this module cannot read is not one "
        "it may propose from"
    )


# ------------------------------------------------------------ 1. the modules


def _drafts(document: DesignIntent) -> tuple[list[ModuleDraft], list[dict[str, str]]]:
    """One draft per block that can become a module, and why the others cannot.

    A block that states no parts **cannot** become a module: the schema refuses a
    group with no parts ("a module with no parts is a caption, not a group the
    layout can place"), and quietly dropping the block would be the silent loss
    R3 exists against — so it is named. A repeated id is refused by the schema for
    the same reason ("one id is one module"): the first block is written, the later
    one is named as the collision it is.
    """
    drafts: list[ModuleDraft] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for block in document.blocks:
        block_id = str(block.id or "").strip()
        if not block_id:
            skipped.append({
                "block": block.id, "status": STATUS_NO_ID,
                "why": "the block states no id — a module names itself, and an empty "
                       "id names nothing (the schema refuses it)",
            })
            continue
        if block_id in seen:
            skipped.append({
                "block": block_id, "status": STATUS_DUPLICATE_ID,
                "why": "this id is already a module (one id is one module, the "
                       "schema's own rule) — the later block is not written",
            })
            continue
        if not block.parts:
            skipped.append({
                "block": block_id, "status": STATUS_NO_PARTS,
                "why": "the block states no parts, so it cannot become a module (a "
                       "group with no parts is a caption, and the schema refuses "
                       "it) — write the parts it is made of and propose again",
            })
            continue
        seen.add(block_id)
        grammar = KIND_GRAMMARS.get(block.kind, "")
        draft = ModuleDraft(
            block_id=block_id,
            kind=block.kind,
            module=PresentationModule(
                id=block_id,
                parts=list(block.parts),
                # The schema requires a role and refuses an empty one; the
                # contract's own word for the block is its `kind`, and a block
                # that states none is written under its own id rather than under
                # a role word this module invented.
                role=block.kind or block_id,
                grammar_ref=grammar,
            ),
        )
        if not block.kind:
            draft.status = STATUS_NO_KIND
            draft.notes.append(
                "the block states no kind, so no grammar is proposed: grammarRef "
                "stays empty (the module inherits the document's, and the document "
                "states none) — a person or a model writes the idiom in"
            )
        elif not grammar:
            draft.status = STATUS_UNMAPPED
            draft.notes.append(
                f"kind {block.kind!r} is not in the kind -> grammar table "
                f"({', '.join(sorted(KIND_GRAMMARS))}) — the module is kept with "
                "grammarRef empty and named here: a kind outside the declared table "
                "is never guessed (the nearest grammar would promise a drawing "
                "nobody wrote)"
            )
        drafts.append(draft)
    return drafts, skipped


def _module_row(draft: ModuleDraft) -> dict[str, Any]:
    """One module as the report writes it: what was written, and every note."""
    module = draft.module
    assert module is not None
    return {
        "id": module.id,
        "block": draft.block_id,
        "kind": draft.kind,
        "grammarRef": module.grammar_ref,
        "role": module.role,
        "core": module.core,
        "branchOrder": list(module.branch_order),
        "status": draft.status,
        "notes": list(draft.notes),
    }


# --------------------------------------------------------------- 2. the core


@dataclass(frozen=True)
class _CoreReading:
    """What the two sources of the core came to, and how to say it."""

    part: str
    originals: tuple[str, ...]
    conflict: bool
    note: str


def _propose_cores(
    drafts: Sequence[ModuleDraft],
    document: DesignIntent,
    circuit: CircuitSpec | None,
    path: str,
) -> None:
    """Write each module's core, or say why nothing was written (098 §一's two sources)."""
    for draft in drafts:
        module = draft.module
        if module is None:
            continue
        if circuit is None:
            draft.notes.append(
                "no core proposed: the pin counts a core is read from are the "
                "netlist's, and no circuit was given (`--circuit`) — nothing is "
                "guessed"
            )
            continue
        reading = _core_reading(circuit, document, tuple(module.parts), path)
        if module.grammar_ref != ic_periphery.NAME:
            # `core` is the ic-periphery fact (098 §一): a module drawn by another
            # grammar never reads it, and a key nobody reads is an intent nobody
            # honours. The reading is still reported — it is a fact about the
            # group, and a reader may want it where the module is edited.
            if reading.originals:
                draft.notes.append(
                    f"{reading.note} — not written: modules[].core is an "
                    f"{ic_periphery.NAME} fact and this module's grammar is "
                    f"{module.grammar_ref or 'unstated'}"
                )
            continue
        module.core = reading.part
        draft.notes.append(reading.note)


def _core_reading(
    circuit: CircuitSpec,
    document: DesignIntent,
    scope_parts: tuple[str, ...],
    path: str,
) -> _CoreReading:
    """The core from the intent's declaration and the partition, or a named conflict.

    The same reading 098 §一's grammar makes, over the same group, so the two
    cannot say different things about the same document: the intent's claim is
    "the block's parts name exactly one part above two pins", the partition's is
    "the unique strict pin-count maximum of this group", and when they name
    different parts neither is picked — the two originals are quoted in 098's own
    wording and a person decides (A3a R1's rule, on the drawing side).
    """
    claims = _intent_core_claims(circuit, document.blocks, scope_parts, path)
    structural, structural_text = _structural_core(circuit, scope_parts)
    originals: list[str] = [
        text for part_id in sorted(claims) for text in claims[part_id]
    ]
    if structural:
        originals.append(f"the partition: {structural_text}")
    found = sorted(set(claims) | ({structural} if structural else set()))
    if len(found) == 1:
        return _CoreReading(
            part=found[0],
            originals=tuple(originals),
            conflict=False,
            note=(
                f"core {found[0]!r}: every source that speaks agrees — "
                + "; ".join(originals)
            ),
        )
    if not found:
        return _CoreReading(
            part="", originals=(), conflict=False,
            note=(
                "no core proposed: neither the contract's blocks[] nor the "
                "partition names a single multi-pin part of this group (098 §一: "
                "a tie, or no part above two pins, is not a core — it is the case "
                "the declaration channel exists for, `modules[].core` or a "
                "`blocks[]` whose parts name exactly one of them)"
            ),
        )
    return _CoreReading(
        part="", originals=tuple(originals), conflict=True,
        note=(
            "the sources of this core disagree: " + "; ".join(originals) + ". Which "
            "part the drawing is arranged around is one fact, stated once — this "
            "proposal does not rank one source above another (098 §一, the same "
            "rule the grammar applies), so the field is left empty and a person "
            "says which of them is wrong"
        ),
    )


def _intent_core_claims(
    circuit: CircuitSpec,
    blocks: Sequence[IntentBlock],
    scope_parts: tuple[str, ...],
    path: str,
) -> dict[str, list[str]]:
    """``part id -> the originals of every block that names it as its core``.

    098's intent source, over this group: a block contributes a claim when exactly
    one of its parts **in scope** is above :data:`ic_periphery.MIN_CORE_PINS`. A
    block that names two of them names a group rather than a core ("which of these
    is the one the others hang off" is exactly what it did not say), and a block
    whose parts are all outside the group is another group's business.
    """
    scope = set(scope_parts)
    claims: dict[str, list[str]] = {}
    for block in blocks:
        multi = [
            part_id for part_id in sorted(set(block.parts))
            if part_id in scope
            and _pin_count(circuit, part_id) > ic_periphery.MIN_CORE_PINS
        ]
        if len(multi) != 1:
            continue
        text = (
            f"intent blocks[id={block.id!r}].parts = {list(block.parts)!r}"
            + (f", kind={block.kind!r}" if block.kind else "")
            + f" (provenance={block.provenance}, "
            + (path if path else "the contract in memory")
            + ")"
        )
        claims.setdefault(multi[0], []).append(text)
    return claims


def _structural_core(
    circuit: CircuitSpec, scope_parts: tuple[str, ...]
) -> tuple[str, str]:
    """``(part id, its original)`` for a unique strict pin-count maximum.

    098's partition source, read the same way and worded the same way: the stated
    pins of what the `CircuitSpec` says about each part (never a symbol's or a
    package's), a maximum strictly above :data:`ic_periphery.MIN_CORE_PINS`, and a
    tie is not an answer.
    """
    counts = {part_id: _pin_count(circuit, part_id) for part_id in sorted(scope_parts)}
    if not counts:
        return "", ""
    best = max(counts.values())
    if best <= ic_periphery.MIN_CORE_PINS:
        return "", ""
    top = sorted(part_id for part_id, count in counts.items() if count == best)
    if len(top) != 1:
        return "", ""
    others = ", ".join(
        f"{part_id}={counts[part_id]}" for part_id in sorted(counts)
        if part_id != top[0]
    )
    return top[0], (
        f"the partition gives {top[0]} {best} stated pins, more than every other "
        f"part here ({others or 'no other part'})"
    )


def _pin_count(circuit: CircuitSpec, part_id: str) -> int:
    """How many pins the spec states for this part (never a symbol's pin count)."""
    return len(pins_of_part(circuit, part_id))


# --------------------------------------------------------- 3. the branch order


def _propose_branch_order(
    drafts: Sequence[ModuleDraft],
    spec: PresentationSpec,
    circuit: CircuitSpec | None,
    intent: DesignIntent | IntentSource,
    circuit_path: str,
    notes: list[str],
) -> None:
    """Write the order the `power-entry` reader concludes, and nothing of its own.

    Rule 4 asks for the *roles* the contract states (which branch clamps, which one
    is bulk). That question is answered by the consumption path that already
    exists — `power_entry`, which reads the contract's clamping claims and orders
    the branches — so the proposal **asks it** and writes its conclusion down. The
    two can therefore not drift: what the draft states is what the reader derived,
    and a draft that states the designator order stays empty so the reader keeps
    reading the contract itself (095's three sources, unchanged).

    The order is written only when the contract actually **moves** it: the reader
    is handed the draft, which states no order yet, so an unmoved order is the
    designator order — the field stays empty, the grammar's own contract source
    derives the same sequence, and nothing in the drawing changes.
    """
    modules = [draft.module for draft in drafts if draft.module is not None]
    if circuit is None or not any(
        module.grammar_ref == power_entry.NAME for module in modules
    ):
        for draft in drafts:
            if draft.module is not None:
                draft.notes.append(
                    "no branch order proposed: it is a "
                    f"{power_entry.NAME} fact, and this module is drawn by "
                    f"{draft.module.grammar_ref or 'no stated grammar'}"
                    + (
                        "" if circuit is not None
                        else " (and which parts hang between the rails is a reading "
                             "of the netlist, which no `--circuit` gave)"
                    )
                )
        return
    reading = grammar_for(power_entry.NAME).bind(circuit, spec, intent=intent)
    if not reading.ok:
        notes.append(
            f"the {power_entry.NAME} reader refused this draft, so no branchOrder "
            "is written (the draft does not guess): "
            + "; ".join(item.detail for item in reading.failures)
        )
        return
    entries = reading.parts_of("entry")
    order = [item.part_id for item in reading.bindings_for("shunt")]
    if not entries or len(order) < 2:
        # One branch (or none) is an order that says nothing, and the contract
        # cannot move a single branch away from itself.
        return
    owners = spec.modules_of_part(entries[0])
    if len(owners) != 1:
        notes.append(
            f"no branchOrder written: the inlet {entries[0]!r} is in "
            + (f"{len(owners)} modules" if owners else "no module")
            + f" of this draft ({', '.join(owners) or 'none'}), so the order has no "
            "single group to be stated on"
        )
        return
    if order == sorted(order):
        # The contract did not move anything: the reader's own three sources
        # derive this order again, and stating it would add a claim to the sheet
        # that the contract already makes.
        return
    module = spec.module(owners[0])
    assert module is not None
    module.branch_order = order
    for draft in drafts:
        if draft.module is not None and draft.module.id == module.id:
            draft.notes.append(
                f"branchOrder {', '.join(order)}: the contract's own reading of "
                "this group's branches moves them away from the designator order "
                f"({', '.join(sorted(order))}) — the order is written down once, and "
                f"{power_entry.NAME} reads this statement instead of re-deriving it "
                f"({circuit_path or 'the circuit in memory'})"
            )


# ---------------------------------------------------------------- 4. the flow


def _propose_flow(
    drafts: Sequence[ModuleDraft], circuit: CircuitSpec | None
) -> tuple[list[FlowEdge], list[dict[str, Any]], str]:
    """Candidate edges from the nets the groups share, direction from the role table.

    Adjacency is a reading of the netlist and nothing else (056 §1's own rule for
    the page: "声明会撒谎，推导不会"): two groups are candidates when one net has
    members of both, and the net is carried as the evidence. Direction is then read
    from :data:`KIND_FLOW_ROLES` alone — a candidate the table does not decide is
    reported as `underdetermined` with both kinds and the reason, because which
    group feeds which is exactly what the reader of the draft has to be told.
    """
    modules = [draft.module for draft in drafts if draft.module is not None]
    kind_of = {draft.module.id: draft.kind for draft in drafts if draft.module is not None}
    if circuit is None:
        return (
            [], [],
            "no flow proposed: which groups share a net is a reading of the "
            "netlist, and no circuit was given (`--circuit`) — nothing is guessed",
        )
    parts_of = {module.id: set(module.parts) for module in modules}
    edges: list[FlowEdge] = []
    undetermined: list[dict[str, Any]] = []
    for index, first in enumerate(modules):
        for second in modules[index + 1:]:
            shared = sorted(
                net.id for net in circuit.nets
                if _owners(net) & parts_of[first.id] and _owners(net) & parts_of[second.id]
            )
            if not shared:
                continue
            role_first = KIND_FLOW_ROLES.get(kind_of[first.id], "")
            role_second = KIND_FLOW_ROLES.get(kind_of[second.id], "")
            direction = _direction(role_first, role_second)
            if direction == 0:
                undetermined.append({
                    "pair": [first.id, second.id],
                    "kinds": [kind_of[first.id], kind_of[second.id]],
                    "roles": [role_first, role_second],
                    "nets": shared,
                    "why": _undetermined_why(
                        kind_of[first.id], kind_of[second.id], role_first, role_second
                    ),
                })
                continue
            source, target = (
                (first.id, second.id) if direction > 0 else (second.id, first.id)
            )
            edges.append(FlowEdge(from_module=source, to_module=target))
    marked, note = _main_path(edges, modules, kind_of, circuit)
    return marked, undetermined, note


def _owners(net: SpecNet) -> set[str]:
    """The parts with a member on this net."""
    return {member.partition(".")[0] for member in net.members}


def _direction(role_first: str, role_second: str) -> int:
    """``1`` first -> second, ``-1`` second -> first, ``0`` nothing is stated.

    Only a declared `source` feeding a declared `sink` is a direction. A source
    against an unknown kind is one group whose end of the flow nobody stated, and
    two sinks are two groups at the same end — in both cases the drawing may well
    have a direction, and this module is not the document that knows it.
    """
    if role_first == FLOW_SOURCE and role_second == FLOW_SINK:
        return 1
    if role_second == FLOW_SOURCE and role_first == FLOW_SINK:
        return -1
    return 0


def _undetermined_why(
    kind_first: str, kind_second: str, role_first: str, role_second: str
) -> str:
    """Why the direction of this candidate is not stated anywhere readable."""
    table = ", ".join(
        f"{kind} -> {role}" for kind, role in sorted(KIND_FLOW_ROLES.items())
    )
    for kind, role in ((kind_first, role_first), (kind_second, role_second)):
        if not role:
            return (
                f"kind {kind!r} states no flow role (the role table has {table}), so "
                "no direction between these two groups is stated anywhere this "
                "proposal may read: a guess here would decide which way the board's "
                "flow runs"
            )
    return (
        f"both kinds stand at the same end of the flow ({role_first} and "
        f"{role_second}) — the role table states a direction only from a "
        f"{FLOW_SOURCE!r} to a {FLOW_SINK!r}, and which of the two feeds the other "
        "is not stated"
    )


def _main_path(
    edges: Sequence[FlowEdge],
    modules: Sequence[PresentationModule],
    kind_of: dict[str, str],
    circuit: CircuitSpec,
) -> tuple[list[FlowEdge], str]:
    """Mark the chain's edges `mainPath`, or say which half of the test failed.

    056 §1's `mainPath` asks for **one whole wire** across a module boundary, and
    096's rule is that the mark names *one net* (a ground may never be one). So two
    things have to be decidable before anything is marked:

    * the flow is a **single chain through every group** — one head, no branching,
      no cycle — which is what makes "the edge the reader is meant to follow"
      unique rather than a choice among candidates;
    * every edge of that chain crosses **exactly one** net, and it is not a ground:
      with two shared nets, a whole-wire run could be drawn for the wrong one, and
      the page checker would refuse the mark rather than downgrade it.

    Otherwise every edge keeps ``mainPath: false`` and the note says which half
    failed — a mark on a guessed net is a refusal, not a warning.
    """
    if len(modules) < 2 or len(edges) != len(modules) - 1:
        return list(edges), (
            f"no mainPath: the flow is {len(edges)} edge(s) over {len(modules)} "
            "group(s), not one chain through every group — with a branch (or a gap) "
            "there is no single edge the reader is meant to follow"
        )
    ids = {module.id for module in modules}
    out: dict[str, str] = {}
    incoming: dict[str, int] = {module_id: 0 for module_id in ids}
    for edge in edges:
        if edge.from_module in out or edge.to_module not in ids:
            return list(edges), (
                "no mainPath: the flow branches (a group feeds two, or an edge "
                "leaves the draft's own groups), so no single chain crosses it"
            )
        out[edge.from_module] = edge.to_module
        incoming[edge.to_module] += 1
    heads = sorted(module_id for module_id in ids if incoming[module_id] == 0)
    if len(heads) != 1:
        return list(edges), (
            f"no mainPath: the flow has {len(heads)} head(s) "
            f"({', '.join(heads) or 'none'}) — a chain has exactly one"
        )
    if KIND_FLOW_ROLES.get(kind_of.get(heads[0], ""), "") != FLOW_SOURCE:
        return list(edges), (
            f"no mainPath: the chain's head {heads[0]!r} is not a group whose kind "
            f"says {FLOW_SOURCE!r}, so which end the flow starts at is not stated"
        )
    walk: list[str] = []
    here = heads[0]
    while here and here not in walk:
        walk.append(here)
        here = out.get(here, "")
    if len(walk) != len(modules) or set(walk) != ids:
        return list(edges), (
            "no mainPath: the edges do not visit every group exactly once (a cycle "
            "or a second component), so no single chain crosses the draft"
        )
    by_id = {module.id: module for module in modules}
    classes = {net.id: net.cls for net in circuit.nets}
    crossings: dict[tuple[str, str], list[str]] = {}
    for edge in edges:
        pair = (edge.from_module, edge.to_module)
        shared = sorted(
            net.id for net in circuit.nets
            if _owners(net) & set(by_id[edge.from_module].parts)
            and _owners(net) & set(by_id[edge.to_module].parts)
        )
        crossings[pair] = shared
        if len(shared) != 1 or classes.get(shared[0], "") == "gnd":
            named = ", ".join(shared) if shared else "no net"
            return list(edges), (
                f"no mainPath: the edge {pair[0]} -> {pair[1]} crosses {named} "
                f"({len(shared)} net(s)"
                + (", a ground" if shared and classes.get(shared[0]) == "gnd" else "")
                + ") — the whole-wire exception names one net, and a ground is never "
                "a wire (096), so nothing is marked"
            )
    marked = [replace(edge, main_path=True) for edge in edges]
    through = " -> ".join(walk)
    return marked, (
        "mainPath: the flow is one chain through every group (" + through + "), and "
        "every edge crosses exactly one non-ground net ("
        + "; ".join(f"{pair[0]}->{pair[1]}: {nets[0]}" for pair, nets in crossings.items())
        + ") — the one edge the reader is meant to follow is decidable"
    )


# ----------------------------------------------------------------- 5. the reads


def _readings(
    document: DesignIntent,
    drafts: Sequence[ModuleDraft],
    skipped: Sequence[dict[str, str]],
) -> tuple[dict[str, Any], list[str]]:
    """What every contract element was read for — and everything that was not used.

    R3 in the report: "找不到 ≠ 已清" applies to a contract the same way it applies
    to a part. An element this proposal could not use (a block that states no
    parts, a decision about a part no module lists, a key no consumer reads, the
    whole `requirements` section) is **named with its path and the reason**, so a
    reader can tell "the proposal used it" from "the proposal never looked", which
    an empty draft cannot.
    """
    written = {draft.block_id for draft in drafts if draft.module is not None}
    blocks: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    unread: list[str] = []
    for block in document.blocks:
        used = f"modules[{block.id}]" if block.id in written else ""
        stated = [key for key in _BLOCK_UNUSED if getattr(block, key, None)]
        blocks.append({
            "id": block.id,
            "used": used,
            "read": list(_BLOCK_KEYS),
            "unused": stated,
        })
        if stated:
            unread.append(
                f"blocks[id={block.id!r}].{'/'.join(stated)}: not read — the drawing "
                "proposal reads " + ", ".join(_BLOCK_KEYS) + "; `requires`/`feeds` "
                "are the closure channel's facts (A3's arch check), and nothing in "
                "the proposal consumes them"
            )
    for item in document.decisions:
        used, why = _decision_use(item, drafts)
        decisions.append({
            "subject": item.subject,
            "used": used,
            "read": list(_DECISION_KEYS),
            "unused": [
                key for key in _DECISION_UNUSED if item.stated_value
            ],
            "why": why,
        })
        if not used:
            unread.append(
                f"decisions[subject={item.subject!r}]: nothing in this proposal reads "
                f"it — {why}"
                + (" (its `value` is the MPN direction's fact, 091's channel)"
                   if item.stated_value else "")
            )
    for row in skipped:
        unread.append(
            f"blocks[id={row['block']!r}]: not written to the draft — {row['why']}"
        )
    unread.append(
        "requirements: the drawing proposal reads `blocks[]` and `decisions[]` only — "
        "`rails`/`signals`/`buses` (and every slot a rail or a chain owes) are the "
        "review channel's facts (090/091/092/093/094), and nothing here reads them"
    )
    reads = {
        "blocks": blocks,
        "decisions": decisions,
        "requirements": {
            "read": False,
            "why": "blocks[] and decisions[] are what a drawing is proposed from; "
                   "requirements[] is read by the review channel",
        },
    }
    return reads, unread


def _decision_use(
    item: IntentDecision, drafts: Sequence[ModuleDraft]
) -> tuple[str, str]:
    """``(what the decision was used for, why not)`` for one decision.

    Two facts are read from a decision, and both are the contract's own words: the
    subject has to be a part of a module (a claim about another group's parts is
    that group's business — 088 §一.3's scope rule), and its prose has to name the
    clamping family for the branch-order reader to take anything from it. The
    **token list is imported** from `power_entry` rather than copied: two
    vocabularies for one reading would drift, and a token this module honours but
    the grammar does not would be a claim nobody draws.
    """
    members = {
        part_id for draft in drafts if draft.module is not None
        for part_id in draft.module.parts
    }
    if item.subject not in members:
        return "", f"no module lists {item.subject!r}"
    if not _names_clamp(item.decision, item.rationale):
        return "", (
            "its prose names no clamping family "
            f"({', '.join(power_entry.CLAMP_TOKENS)}), so the branch-order reader "
            "takes nothing from it (a bulk capacitor that decouples a rail is not a "
            "bleeder — 095 §一.2)"
        )
    return "branch-order claim", ""


def _names_clamp(*texts: str) -> bool:
    """Does this prose name the clamping family (:data:`power_entry.CLAMP_TOKENS`)?

    The vocabulary is `power_entry`'s (imported, never copied); what is here is the
    one containment check, so the report can say which decisions the branch-order
    reader could have taken something from.
    """
    haystack = " ".join(texts).casefold()
    return any(token.casefold() in haystack for token in power_entry.CLAMP_TOKENS)
