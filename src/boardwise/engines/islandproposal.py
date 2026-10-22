"""Mixed islands: declare what is declared, propose the rest, judge it, then write.

`evidence/523/DESIGN.md` §5 is this module's contract, and 岳's second ruling of
2026-10-20 is the sentence it carries:

    岛的来源 → 混合：`islands[]` 声明优先；未声明的部分按「锚=≥3 脚器件、
    离所有锚 >120 自成岛」自动聚类；自动聚类出的岛交给 AI 做语义判断。

**Why this is two commands and not a compiler feature.**  `core/islands.py`'s
`parse_islands` refuses a document in which some part sits in no island (its
`:294-301`), and that invariant is 520j's and is not re-opened here.  So "declare
half of it, cluster the rest" is not a document the layout layer can be handed —
and it must not become one *at compile time* either, because then "what this
document draws" would depend on "what this compilation happened to compute", and
`geometry_sha256` would move for a derivation that is in no file.  岳's words are
「手写覆盖推导」: a derivation counts as covering something only once it is
**written down**.  Hence:

    ① draw islands propose  → a *proposal document* (JSON, diffable, in git)
    ② a human or an AI fills its `judgement[]`
    ③ draw islands apply    → the six gates, then an explicit write
    ④ draw compile          → reads the `islands[]` of ③ and nothing else

Running ③ is the only thing that ever changes a drawing, so a spec that never sees
it compiles **exactly** as it did before this module existed — which is the same
guarantee `drawcompiler`'s island guard gives from the other side.

**What the clustering is, and what it is not.**  It is a *proposal generator*, not
an authority.  522 measured the rule this implements on the golden board: of 34
two-pin parts, 26 (76%) have their serving IC as their nearest IC, and the eight
exceptions all sit in the empty transition band between two islands
(`FOC_ANATOMY` §exceptions).  76% is exactly why step ② exists — not to make the
model smarter, but because this step is wrong about a quarter of the time and
wrong in the places a geometry cannot tell apart.  §5.3's rule is also one step
*stricter* than 522's: a part joins its nearest anchor only if it **shares a local
net** with it or is within `TIGHT_GAP` of it, and a part on a net with some other
anchor goes to *that* anchor even when that one is further away.

**The three rules that keep the model honest** are §5.4's, and all three are about
what it may not do: it may only **accept / split / merge**, at the grain of a whole
cluster or a whole group of parts; it may not add a part, drop a part or cross a
declared island; and every judgement needs a `reason` citing at least one name the
proposal actually printed (521's citation rule, transplanted: 「不许说提案没说的事」).
Everything a judgement fails is handled by §5.6's four levels — and the last of
them is the point of the whole design: an island nobody named is still a **legal**
drawing, it only has to say so.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..core.circuitspec import CircuitSpec
from ..core.designintent import DEFAULT_PROVENANCE, DesignIntent, IntentBlock
from ..core.islands import (
    ISLAND_ROLES,
    IMPLICIT_ISLAND_ID,
    LayoutIsland,
    declared_part_ids,
)
from ..core.presentationspec import PresentationSpec
from ..core.symbolprofile import Box, SymbolProfile
from . import islandlayout as il

__all__ = [
    "ANCHOR_MIN_PINS",
    "APPLY_GATE_CONSERVATION",
    "ATTACH_MAX_GAP",
    "ATTACH_MAX_GAP_NET",
    "TIGHT_GAP",
    "ApplyResult",
    "Cluster",
    "DeclaredIslands",
    "IslandsProposalError",
    "IslandsProposal",
    "NAME_MAX_CHARS",
    "PROPOSAL_VERSION",
    "VERDICTS",
    "apply_judgement",
    "build_proposal",
    "cluster_unplaced",
    "read_declared",
    "render_proposal",
    "write_proposal",
]

#: The version of the proposal document's shape.
PROPOSAL_VERSION = 1

#: The four constants `DESIGN` §5.3 says must come from the 522 anatomy probe
#: (`evidence/522/probes/10_foc_anatomy.py:39-50`), whose own comments say why each
#: one has the value it has.  Named here rather than inline so a reader who wants to
#: re-measure one knows which probe measured it — and `ANCHOR_MIN_PINS` is read from
#: the layout module rather than restated, because 522's "an IC or a connector" rule
#: is already what picks an island's centre (`DESIGN` §1.1).
ANCHOR_MIN_PINS = il.ANCHOR_MIN_PINS
ATTACH_MAX_GAP = 120.0
TIGHT_GAP = 40.0
ATTACH_MAX_GAP_NET = 200.0

#: The three verdicts a judgement may state (§5.4).  Closed on purpose, exactly
#: like `ISLAND_ROLES`: a word this build does not know is a promise nobody can
#: keep, and §5.6's fallback is the answer to one, not a guess.
VERDICTS: tuple[str, ...] = ("accept", "split", "merge")

#: The `reason`'s companion: a short name, so it reads in a report column.  Twelve
#: is the design's own number and it counts characters — 「副边整流与输出滤波」 is nine.
NAME_MAX_CHARS = 12

#: Gate 3's number, so a report can name the one rejection that is the whole
#: document's rather than one entry's (§5.5).
APPLY_GATE_CONSERVATION = 3

#: What `declaredBy` says on a cluster this module proposed.  Spelled out rather
#: than implied, because §5.4 asks for it on every work order: 「这一簇的来源，永远写出来」.
DECLARED_BY_CLUSTERING = "clustering"


class IslandsProposalError(ValueError):
    """The proposal, the judgement or the presentation document cannot be read."""


# ------------------------------------------------------------------ the reading


@dataclass(frozen=True)
class DeclaredIslands:
    """What a presentation document says about islands, read **leniently**.

    `parse_islands` is strict on purpose: a document in which some part sits in no
    island is refused, because a layout layer handed one would have to invent the
    missing half.  This reader is the half that *proposes* that half, so it asks
    every question `parse_islands` asks **except** the completeness one — in the one
    place where "some part is in no island yet" is the normal state of the world
    rather than a defect.

    Nothing here is a second reading of the document: ``parts`` is the modules'
    part list (`declared_part_ids`, the same reference set), ``islands`` are the
    declared islands in document order, and ``complete`` is whether the declaration
    already covers every part — the case in which there is nothing to propose and
    the document needs no further step.
    """

    islands: tuple[LayoutIsland, ...]
    parts: tuple[str, ...]
    complete: bool

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(island.id for island in self.islands)

    def owner(self) -> dict[str, str]:
        """``part id -> island id`` for the declared islands."""
        return {
            part_id: island.id
            for island in self.islands
            for part_id in island.parts
        }


def read_declared(payload: Any, where: str = "$") -> DeclaredIslands:
    """Read a presentation document's modules and `islands[]`, leniently.

    Refused here — each is a fact this document decides on its own, and each is the
    same refusal `parse_islands` makes: a part in two declared islands, an island
    naming a part the modules do not have, an island with no parts, two islands
    under one id, the implicit island's id written down, an unknown key, a role this
    build does not know.  **Not** refused: a part in no island — that is what the
    proposal is for.
    """
    if not isinstance(payload, dict):
        raise IslandsProposalError(
            f"{where} must be a JSON object, got {type(payload).__name__}"
        )
    modules = payload.get("modules") or []
    if not isinstance(modules, list):
        raise IslandsProposalError(f"{where}.modules must be a list")
    groups: list[Sequence[str]] = []
    for index, module in enumerate(modules):
        if not isinstance(module, dict):
            raise IslandsProposalError(f"{where}.modules[{index}] must be an object")
        members = module.get("parts") or []
        if not isinstance(members, list):
            raise IslandsProposalError(f"{where}.modules[{index}].parts must be a list")
        groups.append([str(part) for part in members])
    parts = tuple(declared_part_ids(groups))

    value = payload.get("islands")
    if value is None:
        # No `islands` key at all: the document states no islands, so every part
        # of it is unplaced.  "Complete" here would mean "there is nothing to
        # propose", and that is true only when there are no parts either.
        return DeclaredIslands((), parts, not parts)
    if not isinstance(value, list):
        raise IslandsProposalError(
            f"{where}.islands must be a JSON list of islands, got "
            f"{type(value).__name__} — a spec that states no islands states none "
            "at all"
        )
    islands: list[LayoutIsland] = []
    seen_ids: set[str] = set()
    known = set(parts)
    for index, item in enumerate(value):
        spot = f"{where}.islands[{index}]"
        if not isinstance(item, dict):
            raise IslandsProposalError(f"{spot} must be a JSON object")
        unknown = sorted(set(item) - {"id", "parts", "role", "name"})
        if unknown:
            raise IslandsProposalError(
                f"{spot}: unknown key(s) {', '.join(unknown)}; allowed: id, parts, "
                "role, name — the schema is closed on purpose"
            )
        island_id = str(item.get("id") or "").strip()
        if not island_id:
            raise IslandsProposalError(f"{spot}.id is required and missing")
        if island_id == IMPLICIT_ISLAND_ID:
            raise IslandsProposalError(
                f"{spot}.id is {island_id!r}, which is the id of the implicit island "
                "a spec states by saying nothing"
            )
        if island_id in seen_ids:
            raise IslandsProposalError(
                f"{spot}.id is {island_id!r}, already used — an island id is how "
                "everything downstream names one block"
            )
        seen_ids.add(island_id)
        members = item.get("parts")
        if not isinstance(members, list) or not members:
            raise IslandsProposalError(
                f"{spot}.parts must be a non-empty list — an island with no parts "
                "is a caption, not a block the layout can place"
            )
        for part_index, part_id in enumerate(members):
            if str(part_id) not in known:
                raise IslandsProposalError(
                    f"{spot}.parts[{part_index}] is {part_id!r}, which this spec "
                    "does not have — an island is stated over the spec's own parts"
                )
        role = str(item.get("role") or "").strip()
        if role and role not in ISLAND_ROLES:
            raise IslandsProposalError(
                f"{spot}.role is {role!r}; this build knows "
                f"{', '.join(ISLAND_ROLES)} — state one of them or state none"
            )
        islands.append(LayoutIsland(
            id=island_id, parts=[str(part) for part in members], role=role,
            name=str(item.get("name") or "").strip(),
        ))
    owner: dict[str, str] = {}
    for island in islands:
        for part_id in island.parts:
            if part_id in owner:
                raise IslandsProposalError(
                    f"{where}.islands: part {part_id!r} is in both {owner[part_id]!r} "
                    f"and {island.id!r} — every part sits in exactly one block"
                )
            owner[part_id] = island.id
    return DeclaredIslands(
        islands=tuple(islands), parts=parts,
        complete=all(part_id in owner for part_id in parts),
    )


# ----------------------------------------------------------------- the clusters


@dataclass(frozen=True)
class Cluster:
    """One proposed island: its parts, the anchor they hang on, and why.

    ``anchor`` is the ≥3-pin part the cluster is arranged around — or, for a
    cluster that has none, the part that is its own fallback centre (`DESIGN` §1.1's
    third rule: with no candidate the anchor falls back to the busiest part).  It is
    the first half of the key the ``auto-<n>`` ids are handed out in.
    """

    island_id: str
    parts: tuple[str, ...]
    anchor: str
    evidence: Mapping[str, Any]


def _pin_count(
    circuit: CircuitSpec, part_id: str, book: Mapping[str, SymbolProfile]
) -> int:
    return len(book[circuit.part(part_id).symbol_ref].pins)


def _shares_a_net(circuit: CircuitSpec, first: str, second: str) -> list[str]:
    """The nets both parts have a pin on, in the netlist's own order."""
    out: list[str] = []
    for net in circuit.nets:
        holders = {member.partition(".")[0] for member in net.members}
        if first in holders and second in holders:
            out.append(net.id)
    return out


def cluster_unplaced(
    circuit: CircuitSpec,
    declared: DeclaredIslands,
    book: Mapping[str, SymbolProfile],
    *,
    budget: il.IslandBudget | None = None,
) -> tuple[list[Cluster], list[str]]:
    """`DESIGN` §5.3's rule, asked once: which undeclared parts hang on what.

    Returns the clusters in the order they are numbered, and the ids of the parts
    the rule **cannot place** — a part the modules name that the circuit or the
    library does not have.  Those are reported, never quietly dropped and never
    given an invented island (R3: 找不到 ≠ 已清).

    The rule, in the design's own words:

    ```
    U       = the parts no declared island names
    anchors = {p ∈ U : pins(p) ≥ ANCHOR_MIN_PINS}
    for p in U \\ anchors:
        a = the anchor nearest to p          (measured on `probe_boxes`' boxes)
        if a and gap ≤ ATTACH_MAX_GAP and (p shares a net with a or gap ≤ TIGHT_GAP):
            → a's island
        elif the nearest anchor p shares a net with is within ATTACH_MAX_GAP_NET:
            → that anchor's island            # 「共网」 widens 120 to 200
        else:
            → an island of its own
    ```

    Both extra clauses are 522's own correction, and `DESIGN` §10-3 records why the
    plain "nearest anchor within 120" is not enough alone: the probe measured that
    rule at 76% accurate with every one of its eight errors sitting in a transition
    band, and 「与锚共一条信号网」 is the audit criterion that probe itself used to
    decide which island a part was **really** in.
    """
    owner = declared.owner()
    unplaced = [part_id for part_id in declared.parts if part_id not in owner]
    known_parts = {str(part.id) for part in circuit.parts}
    placeable: list[str] = []
    unknown: list[str] = []
    for part_id in unplaced:
        part = circuit.part(part_id) if part_id in known_parts else None
        if part is None or part.symbol_ref not in book:
            unknown.append(part_id)
        else:
            placeable.append(part_id)

    boxes: dict[str, Box] = {}
    if placeable:
        boxes = il.probe_boxes(
            circuit, placeable, book,
            anchor_min_pins=ANCHOR_MIN_PINS, orphan_gap=ATTACH_MAX_GAP,
            budget=budget,
        )

    pins = {part_id: _pin_count(circuit, part_id, book) for part_id in placeable}
    anchors = sorted(
        (part_id for part_id in placeable if pins[part_id] >= ANCHOR_MIN_PINS),
        key=lambda part_id: (-pins[part_id], part_id),
    )

    attached: dict[str, str] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for part_id in placeable:
        if part_id in anchors:
            continue
        nearest: tuple[float, str] | None = None
        for anchor in anchors:
            gap = il.box_gap(boxes[part_id], boxes[anchor])
            if nearest is None or (gap, anchor) < nearest:
                nearest = (gap, anchor)
        shared: list[tuple[float, str, list[str]]] = []
        for anchor in anchors:
            nets = _shares_a_net(circuit, part_id, anchor)
            if nets:
                shared.append((il.box_gap(boxes[part_id], boxes[anchor]), anchor, nets))
        shared.sort(key=lambda item: (item[0], item[1]))
        net_best = shared[0] if shared else None

        if nearest is not None and nearest[0] <= ATTACH_MAX_GAP and (
            (net_best is not None and net_best[1] == nearest[1])
            or nearest[0] <= TIGHT_GAP
        ):
            gap, anchor = nearest
            nets = next((item[2] for item in shared if item[1] == anchor), [])
            attached[part_id] = anchor
            evidence[part_id] = {
                "anchor": anchor,
                "why": (
                    f"nearest anchor {anchor} is {gap:g} units away (within "
                    f"ATTACH_MAX_GAP {ATTACH_MAX_GAP:g}) and "
                    + (
                        "shares the local net(s) " + "/".join(nets)
                        if nets else
                        f"is within TIGHT_GAP {TIGHT_GAP:g}"
                    )
                ),
            }
        elif net_best is not None and net_best[0] <= ATTACH_MAX_GAP_NET:
            gap, anchor, nets = net_best
            attached[part_id] = anchor
            evidence[part_id] = {
                "anchor": anchor,
                "why": (
                    "the nearest anchor is "
                    + (f"{nearest[1]} at {nearest[0]:g} units" if nearest else "none")
                    + f", but {part_id} shares {'/'.join(nets)} with {anchor} "
                    f"{gap:g} units away (within ATTACH_MAX_GAP_NET "
                    f"{ATTACH_MAX_GAP_NET:g})"
                ),
            }
        else:
            evidence[part_id] = {
                "anchor": part_id,
                "why": (
                    "no anchor within ATTACH_MAX_GAP "
                    f"{ATTACH_MAX_GAP:g} units (nearest: "
                    + (f"{nearest[1]} at {nearest[0]:g}" if nearest else "none")
                    + ") and no anchor sharing a net within ATTACH_MAX_GAP_NET "
                    f"{ATTACH_MAX_GAP_NET:g}, so it is an island of its own"
                ),
            }

    groups: dict[str, list[str]] = {anchor: [anchor] for anchor in anchors}
    for part_id in placeable:
        if part_id in anchors:
            continue
        anchor = attached.get(part_id)
        if anchor is None:
            groups[part_id] = [part_id]
        else:
            groups[anchor].append(part_id)

    # §5.4's deterministic ids: clusters sorted by (their anchor, their smallest
    # part), numbered from 1.  No hash and no clock — the id a proposal hands out
    # has to be the id `apply` writes, or every diff is noise.
    ordered = sorted(
        ((anchor, tuple(sorted(dict.fromkeys(parts)))) for anchor, parts in groups.items()),
        key=lambda item: (item[0], min(item[1])),
    )
    clusters: list[Cluster] = []
    for position, (anchor, parts) in enumerate(ordered, start=1):
        why = [evidence[part_id]["why"] for part_id in parts if part_id in evidence]
        if not why:
            why = [
                f"{anchor} is an anchor ({pins[anchor]} pins) and no part hangs on it"
            ]
        clusters.append(Cluster(
            island_id=f"{il.AUTO_ISLAND_PREFIX}{position}",
            parts=parts,
            anchor=anchor,
            evidence={
                "anchorCandidate": anchor,
                "gapToNearestOtherCluster": _nearest_other(boxes, parts, placeable),
                "why": "; ".join(why),
            },
        ))
    return clusters, unknown


def _nearest_other(
    boxes: Mapping[str, Box], parts: Sequence[str], placeable: Sequence[str]
) -> float | None:
    """The smallest gap from this cluster to any part outside it, or ``None``.

    `DESIGN` §5.4's `gapToNearestOtherCluster`: the one distance that says how
    **separable** the cluster is.  "These two groups are 300 units apart" and "these
    two groups overlap" are different proposals even when the parts in them read the
    same, and this is the number the model is asked to weigh.

    ``None`` when there is nothing outside — one cluster is a page with no
    neighbour, and a zero would read as "touching".
    """
    mine = set(parts)
    outside = [part_id for part_id in placeable if part_id not in mine]
    if not outside:
        return None
    best: float | None = None
    for part_id in parts:
        for other in outside:
            gap = il.box_gap(boxes[part_id], boxes[other])
            if best is None or gap < best:
                best = gap
    return None if best is None else round(best, 3)


# ---------------------------------------------------------------- the proposal


@dataclass(frozen=True)
class IslandsProposal:
    """The proposed document, plus the two things a caller has to know about it.

    ``document`` is what goes to disk (and into git); ``clusters`` and
    ``unresolved`` are the same facts in Python, so a probe or a report does not
    have to parse its own JSON back.
    """

    document: dict[str, Any]
    clusters: tuple[Cluster, ...]
    unresolved: tuple[str, ...]
    declared: DeclaredIslands

    @property
    def empty(self) -> bool:
        """Is there nothing to judge — is the declaration already complete?"""
        return not self.clusters


def build_proposal(
    circuit: CircuitSpec,
    payload: Any,
    book: Mapping[str, SymbolProfile],
    *,
    budget: il.IslandBudget | None = None,
    declared_blocks: Iterable[str] = (),
    where: str = "$",
) -> IslandsProposal:
    """The proposal document: what is declared, and one work order per cluster.

    §5.4's transport decisions, all three made for the reason it gives:

    * **no coordinates.**  A work order asks a question about *semantics* — is this
      one thing, what is it called, what role does it play — and a coordinate in the
      document is an invitation to answer a geometric question instead;
    * **only facts** in ``parts`` (library symbol, value, pin count): everything
      else about a part is the model's to read elsewhere, and a field nobody asked
      about is a field nobody can be held to;
    * **the evidence is printed** — ``anchorCandidate``, ``gapToNearestOtherCluster``,
      ``why`` — because §5.4's contract is that the model may **refute** the
      proposal, and a proposal without its reasons cannot be refuted.
    """
    declared = read_declared(payload, where)
    clusters, unknown = cluster_unplaced(circuit, declared, book, budget=budget)
    owner = declared.owner()
    for cluster in clusters:
        for part_id in cluster.parts:
            owner[part_id] = cluster.island_id

    tickets: list[dict[str, Any]] = []
    for cluster in clusters:
        members = set(cluster.parts)
        local: list[str] = []
        crossing: list[str] = []
        for net in circuit.nets:
            here = [
                member for member in net.members
                if member.partition(".")[0] in members
            ]
            if not here:
                continue
            if len(here) >= 2:
                local.append(net.id)
            if len(here) != len(net.members):
                crossing.append(net.id)
        neighbours: dict[str, list[str]] = {}
        for net in circuit.nets:
            if net.id not in crossing:
                continue
            for island_id in sorted({
                owner[member.partition(".")[0]]
                for member in net.members
                if owner.get(member.partition(".")[0]) not in (None, cluster.island_id)
            }):
                neighbours.setdefault(island_id, [])
                if net.id not in neighbours[island_id]:
                    neighbours[island_id].append(net.id)
        classes = {
            net.id: net.cls for net in circuit.nets
            if net.id in set(local) | set(crossing)
        }
        tickets.append({
            "islandId": cluster.island_id,
            "parts": [
                {
                    "id": part_id,
                    "symbolRef": circuit.part(part_id).symbol_ref,
                    "value": circuit.part(part_id).value,
                    "pins": _pin_count(circuit, part_id, book),
                }
                for part_id in cluster.parts
            ],
            "localNets": local,
            "netClasses": classes,
            "crossingNets": crossing,
            "neighbours": [
                {"islandId": island_id, "nets": neighbours[island_id]}
                for island_id in sorted(neighbours)
            ],
            "evidence": dict(cluster.evidence),
            "declaredBy": DECLARED_BY_CLUSTERING,
        })

    notes: list[str] = []
    if declared.complete:
        notes.append(
            "islands[] already names every part of this spec, so there is nothing "
            "to propose: 岳's 「声明优先」 means the declaration is copied into this "
            "document verbatim and no cluster is invented"
        )
    if unknown:
        notes.append(
            "no island is proposed for "
            + ", ".join(sorted(unknown))
            + ": the circuit or the library does not have them, and a part that "
            "cannot be measured is reported rather than guessed at (R3)"
        )
    if tickets:
        notes.append(
            f"{len(tickets)} cluster(s) came out of the geometry.  The rule is "
            "522's, measured at 76% on the golden board (26 of 34 two-pin parts "
            "have their serving IC as their nearest IC), and 76% is why every "
            "cluster is a question for a judgement rather than a decision"
        )
    document = {
        "proposalVersion": PROPOSAL_VERSION,
        "declared": [
            {"id": island.id, "role": island.role, "parts": list(island.parts)}
            for island in declared.islands
        ],
        "declaredBlocks": sorted(str(item) for item in declared_blocks),
        "unresolved": sorted(unknown),
        "clusters": tickets,
        "judgement": [],
        "notes": notes,
    }
    return IslandsProposal(
        document=document, clusters=tuple(clusters),
        unresolved=tuple(sorted(unknown)), declared=declared,
    )


def render_proposal(proposal: Mapping[str, Any]) -> str:
    """The proposal as text — two-space indent, LF, insertion-order keys.

    The file is meant to be read and **diffed** (§5.2), so it is written by the same
    rule every other document in this repository is: the bytes are a pure function
    of the content, with no clock and no path in them.
    """
    return json.dumps(proposal, ensure_ascii=False, indent=2) + "\n"


def write_proposal(proposal: Mapping[str, Any], path: str | Path) -> None:
    """Write the proposal document (see :func:`render_proposal`)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_proposal(proposal), encoding="utf-8", newline="\n")


# -------------------------------------------------------------- the judgement
#
# §5.5's six gates in its own order, and §5.6's four levels.  The shape of the code
# follows the shape of the rules: gates 1, 2, 4, 5 and 6 ask about **one** entry and
# their answer is "this entry falls back"; gate 3 asks about the whole document and
# its answer is "nothing is written".


@dataclass
class _Entry:
    """One cluster resolved into what it contributes, or why it could not be."""

    island_id: str
    #: The cluster's own parts — the reference set gate 3 conserves, so this never
    #: changes once the proposal has been read.
    parts: list[str]
    #: The several islands a `split` asked for, in the order it asked for them.
    split_groups: list[tuple[str, list[str]]] | None = None
    #: The island a `merge` asked this one into, or ``None``.
    merged_into: str | None = None
    role: str = ""
    name: str = ""
    verdict: str = ""
    reason: str = ""
    gate: int | None = None
    why: str = ""

    def resolved(self) -> list[tuple[str, list[str]]]:
        """The islands this entry contributes, id and parts, in write order."""
        if self.merged_into is not None:
            return []
        if self.split_groups is not None:
            return list(self.split_groups)
        return [(self.island_id, list(self.parts))]


@dataclass(frozen=True)
class ApplyResult:
    """What a judgement did, and what the caller is asked to write down.

    ``written`` is false exactly when gate 3 refused the whole document (§5.6 L2):
    the spec and the intent are then untouched, which is what makes "nothing ran"
    and "it ran and was refused" the same document rather than two.
    """

    written: bool
    islands: tuple[LayoutIsland, ...]
    report: dict[str, Any]

    @property
    def derived(self) -> list[str]:
        """The islands whose id still says the partition came from a geometry."""
        return [
            island.id for island in self.islands
            if island.id.startswith(il.AUTO_ISLAND_PREFIX)
        ]


@dataclass(frozen=True)
class JudgedApplication:
    """The documents a judged proposal produces, ready to be written.

    ``spec`` is ``None`` when gate 3 refused the document; when it is not, it is the
    whole presentation spec **already read back through its own schema**, so a caller
    cannot write a partition this build would refuse to load.
    """

    result: ApplyResult
    spec: PresentationSpec | None
    intent: DesignIntent | None

    @property
    def payload(self) -> dict[str, Any] | None:
        return None if self.spec is None else self.spec.to_jsonable()


def _tokens(ticket: Mapping[str, Any]) -> set[str]:
    """Every name the proposal printed beside ``islandId`` — gate 5's dictionary.

    §5.5 gate 5: 「`reason` 非空且引用了至少一个提案里给出的名字（网名 / part id /
    `neighbours[].islandId`）」.  It cannot stop a model from talking nonsense and was
    never meant to; what it stops is a judgement written without reading the work
    order, which 521 measured to be the expensive case.
    """
    out: set[str] = {str(ticket.get("islandId", ""))}
    for name in ("localNets", "crossingNets"):
        out.update(str(item) for item in ticket.get(name) or ())
    for part in ticket.get("parts") or ():
        if isinstance(part, Mapping):
            out.add(str(part.get("id", "")))
    for item in ticket.get("neighbours") or ():
        if isinstance(item, Mapping):
            out.add(str(item.get("islandId", "")))
    evidence = ticket.get("evidence")
    if isinstance(evidence, Mapping):
        out.add(str(evidence.get("anchorCandidate", "")))
    return {token for token in out if token}


def _groups(value: Any) -> list[list[str]]:
    """``[['a','b'], ['c']]`` from anything list-shaped, else ``[]``.

    §5.4's `split` is 「切成哪几组 part id」 and `mergeWith` is 「并进哪个岛 id」; both
    are lists *of* things, so a flat list of strings is read as one group — which is
    what a person writing a small judgement means by ``"split": ["C11", "C13"]``.
    """
    if not isinstance(value, list) or not value:
        return []
    if all(isinstance(item, str) for item in value):
        return [[str(item) for item in value]]
    out: list[list[str]] = []
    for item in value:
        if isinstance(item, str):
            out.append([item])
        elif isinstance(item, list) and all(isinstance(part, str) for part in item):
            out.append([str(part) for part in item])
        else:
            return []
    return out


def apply_judgement(
    proposal: Mapping[str, Any],
    declared: DeclaredIslands,
    judgement: Sequence[Mapping[str, Any]],
) -> ApplyResult:
    """Run §5.5's six gates over one judgement and answer with what to write.

    The fallback is §5.6's, and it is the design's most important promise: a
    judgement that fails a gate falls back to the **geometric cluster as it was** —
    an ``auto-<n>`` island, no role, no name.  Nothing is guessed and nothing is
    lost: the cluster was already a legal partition, and the drawing it makes is one
    that says out loud that it was derived.
    """
    tickets = [ticket for ticket in proposal.get("clusters") or ()]
    order: list[str] = []
    by_id: dict[str, Mapping[str, Any]] = {}
    for ticket in tickets:
        island_id = str(ticket.get("islandId", ""))
        if island_id in by_id:
            raise IslandsProposalError(
                "the proposal states one islandId twice — a work order's id is how a "
                "judgement names it, so two orders under one name cannot both be "
                "answered"
            )
        by_id[island_id] = ticket
        order.append(island_id)

    counts: dict[str, int] = {}
    for entry in judgement:
        key = str(entry.get("islandId", "")) if isinstance(entry, Mapping) else ""
        counts[key] = counts.get(key, 0) + 1

    declared_ids = set(declared.ids)
    resolved: dict[str, _Entry] = {
        island_id: _Entry(
            island_id=island_id,
            parts=[
                str(part["id"]) for part in by_id[island_id].get("parts") or ()
            ],
        )
        for island_id in order
    }
    report: list[dict[str, Any]] = []

    for entry in judgement:
        if not isinstance(entry, Mapping):
            raise IslandsProposalError(
                "every judgement entry must be a JSON object; one of them is "
                f"{type(entry).__name__}"
            )
        island_id = str(entry.get("islandId", ""))
        target = resolved.get(island_id)
        record: dict[str, Any] = {"islandId": island_id}

        def fall(level: str, gate: int | None, why: str) -> None:
            record["gate"] = gate
            record["fallback"] = level
            record["why"] = why
            if target is not None and gate is not None:
                target.gate, target.why = gate, why
            report.append(record)

        # -- gate 1: an id this proposal printed, answered exactly once.
        if island_id not in by_id:
            fall("rejected", 1, (
                "no cluster in this proposal has this islandId; a judgement is an "
                "answer to a work order, and there is no work order here"
            ))
            continue
        if counts.get(island_id, 0) != 1:
            fall("rejected", 1, (
                f"this islandId appears {counts.get(island_id, 0)} times in the "
                "judgement — a work order is answered once"
            ))
            continue

        # -- gate 2: a verdict this build knows, with the keys it needs.
        verdict = str(entry.get("verdict", ""))
        if verdict not in VERDICTS:
            fall("L0", 2, (
                f"verdict {verdict!r} is not one of {', '.join(VERDICTS)} — the "
                "model's whole vocabulary is accept/split/merge (§5.4)"
            ))
            continue
        if verdict == "accept" and not str(entry.get("name") or "").strip():
            fall("L0", 2, "verdict 'accept' needs a `name` (§5.4)")
            continue
        if verdict == "split" and not _groups(entry.get("split")):
            fall("L0", 2, "verdict 'split' needs a non-empty `split` list of part groups")
            continue
        if verdict == "merge" and not _groups(entry.get("mergeWith")):
            fall("L0", 2, "verdict 'merge' needs `mergeWith`: the island to merge into")
            continue

        # -- gate 4: the role vocabulary, and a name that fits a report column.
        role = str(entry.get("role") or "").strip()
        if role not in ("", *ISLAND_ROLES):
            fall("L0", 4, (
                f"role {role!r} is not one of {', '.join(ISLAND_ROLES)} — an unknown "
                "role is a promise nobody can keep (§5.4)"
            ))
            continue
        name = str(entry.get("name") or "").strip()
        if len(name) > NAME_MAX_CHARS:
            fall("L0", 4, (
                f"name is {len(name)} characters, over the {NAME_MAX_CHARS}-character "
                "column this report prints (§5.4)"
            ))
            continue
        if verdict != "accept" and name:
            fall("L0", 4, (
                "a `name` answers `accept` and nothing else: a split makes several "
                "islands and one name would name them all (§5.4)"
            ))
            continue

        # -- gate 5: a reason, citing something this work order printed.
        reason = str(entry.get("reason") or "").strip()
        if not reason:
            fall("L0", 5, "no `reason` — a judgement without a reason is not one (§5.4)")
            continue
        tokens = _tokens(by_id[island_id])
        if not any(token in reason for token in tokens):
            fall("L0", 5, (
                "the `reason` cites none of the names this work order printed ("
                + ", ".join(sorted(tokens)[:6])
                + ", …) — 521's citation rule: a judgement may not say what the "
                "proposal did not (§5.5)"
            ))
            continue

        # -- gate 6: never across a declared island.  声明优先 is 岳's first word.
        if verdict == "merge":
            targets = _groups(entry.get("mergeWith"))[0]
            crossing = [item for item in targets if item in declared_ids]
            if crossing:
                fall("L0", 6, (
                    f"`mergeWith` names the declared island {', '.join(crossing)} — a "
                    "proposal may rearrange what it proposed and may not reach into "
                    "what the document declared (§5.5 gate 6)"
                ))
                continue
            strangers = [item for item in targets if item not in by_id]
            if strangers:
                fall("L0", 2, (
                    f"`mergeWith` names {', '.join(strangers)}, which is not a cluster "
                    "of this proposal"
                ))
                continue

        target.verdict = verdict
        target.reason = reason
        if verdict == "accept":
            # The role is written only for `accept`: a split makes several islands
            # and one role would be a claim about all of them, which is the guess
            # §5.6 forbids.
            target.role = role
            target.name = name
        elif verdict == "split":
            target.split_groups = [
                (f"{island_id}-{index}", sorted(group))
                for index, group in enumerate(_groups(entry.get("split")), start=1)
            ]
        else:
            target.merged_into = ""  # filled in once every target has been read
            target.name = name
        report.append(record | {
            "verdict": verdict, "role": role, "name": name, "gate": None,
        })

    # -- merges, read as a graph: "A merges into B" is an edge, and a chain is
    # followed to its end.  A cycle is refused rather than followed, because a cycle
    # has no island to merge into — that is a fact about the judgement, not a taste.
    edges: dict[str, str] = {}
    for island_id, entry in resolved.items():
        if entry.verdict != "merge":
            continue
        for item in judgement:
            if (isinstance(item, Mapping)
                    and str(item.get("islandId", "")) == island_id
                    and str(item.get("verdict", "")) == "merge"):
                edges[island_id] = _groups(item.get("mergeWith"))[0][0]
                break

    def ultimate(island_id: str) -> str | None:
        seen: list[str] = []
        current = island_id
        while current in edges:
            if current in seen:
                return None
            seen.append(current)
            current = edges[current]
        return current if current in resolved else None

    for island_id in sorted(edges):
        entry = resolved[island_id]
        host_id = ultimate(island_id)
        if host_id is None:
            entry.verdict, entry.merged_into, entry.split_groups = "", None, None
            entry.role, entry.name = "", ""
            entry.gate = 2
            entry.why = (
                "the `mergeWith` edges form a cycle (" + " → ".join(sorted(edges))
                + "), which has no island to merge into"
            )
            report.append({
                "islandId": island_id, "gate": 2, "fallback": "L0", "why": entry.why,
            })
            continue
        host = resolved[host_id]
        if host is not island_id:
            host.parts = sorted(set(host.parts) | set(entry.parts))
        entry.merged_into = host_id

    # -- gate 3: conservation, over the whole document.  The one rejection that
    # takes everything with it, because if the parts do not add up then nothing else
    # the judgement says can be checked against anything.
    wanted = {part_id for entry in resolved.values() for part_id in entry.parts}
    produced: list[str] = []
    for island_id in order:
        for _, group in resolved[island_id].resolved():
            produced.extend(group)
    if sorted(produced) != sorted(wanted):
        trouble: list[str] = []
        missing = sorted(wanted - set(produced))
        extra = sorted({item for item in produced if item not in wanted})
        doubled = sorted({item for item in produced if produced.count(item) > 1})
        if missing:
            trouble.append("missing " + ", ".join(missing))
        if extra:
            trouble.append("unknown " + ", ".join(extra))
        if doubled:
            trouble.append("named twice " + ", ".join(doubled))
        why = (
            "the judgement does not conserve the parts the proposal proposed ("
            + "; ".join(trouble)
            + ") — 件守恒 is the one fact anybody can check, so a judgement that "
            "breaks it takes the whole proposal down with it (§5.6 L2)"
        )
        return ApplyResult(
            written=False,
            islands=declared.islands,
            report={
                "proposalVersion": proposal.get("proposalVersion", PROPOSAL_VERSION),
                "applied": False,
                "gate": APPLY_GATE_CONSERVATION,
                "why": why,
                "entries": report,
                "islands": [],
                "derived": [],
            },
        )

    islands: list[LayoutIsland] = list(declared.islands)
    written: list[dict[str, Any]] = []
    for island_id in order:
        entry = resolved[island_id]
        for group_id, group in entry.resolved():
            if not group:
                continue
            islands.append(LayoutIsland(
                id=group_id, parts=group, role=entry.role, name=entry.name,
            ))
            written.append({
                "islandId": group_id,
                "fromCluster": island_id,
                "verdict": entry.verdict or "L0",
                "role": entry.role,
                "name": entry.name,
                "parts": list(group),
                "reason": entry.reason or entry.why,
            })
    return ApplyResult(
        written=True,
        islands=tuple(islands),
        report={
            "proposalVersion": proposal.get("proposalVersion", PROPOSAL_VERSION),
            "applied": True,
            "gate": None,
            "why": "",
            "entries": report,
            "islands": written,
            "derived": [
                item["islandId"] for item in written
                if item["islandId"].startswith(il.AUTO_ISLAND_PREFIX)
            ],
        },
    )


def apply_proposal(
    proposal: Mapping[str, Any],
    payload: Any,
    *,
    intent: DesignIntent | None = None,
    where: str = "$",
) -> JudgedApplication:
    """Read a judged proposal and answer with the documents to write.

    The whole write is one step: the declared islands are copied **verbatim**
    (声明优先), the judged clusters are appended, and the result goes back through
    `PresentationSpec.from_dict` before anybody is handed it.  The document's own
    closed schema is therefore the last check — a partition this module produced but
    this build cannot read is a bug here, not a refusal the user has to debug.
    """
    declared = read_declared(payload, where)
    judgement = proposal.get("judgement") or []
    if isinstance(judgement, Mapping):
        judgement = [judgement]
    if not isinstance(judgement, list):
        raise IslandsProposalError(
            f"{where}: the proposal's `judgement` must be a list of judgements"
        )
    result = apply_judgement(
        proposal, declared, [item for item in judgement if isinstance(item, Mapping)],
    )
    if not result.written:
        return JudgedApplication(result=result, spec=None, intent=intent)
    body = dict(payload)
    body["islands"] = [
        {"id": island.id, "parts": list(island.parts), "role": island.role,
         "name": island.name}
        for island in result.islands
    ]
    spec = PresentationSpec.from_dict(body)
    return JudgedApplication(
        result=result, spec=spec, intent=_intent_with_blocks(intent, result),
    )


def _intent_with_blocks(
    intent: DesignIntent | None, result: ApplyResult
) -> DesignIntent | None:
    """The design intent with one `blocks[]` entry per written cluster.

    §5.4's晋级 rule: 「判断落 `DesignIntent.blocks[]`，`provenance = "ai_asserted"`」,
    于是整份意图文档**自动变草稿** (`DesignIntent.draft`'s weakest-rule reading) —
    模型的话不会被当成人的话, and the layout that ate an AI's judgement says so.

    ``blocks[].parts`` is where this lands because that field is already 「这一块由哪些件
    实现」, exactly the grain of this proposal.  The name the judgement gave goes to
    ``kind``: the closed block schema's only free-text slot.  See the batch's report
    for why the island's own schema (`core/islands.py`'s ``id``/``parts``/``role``) is
    not widened for it — that module is 「不动」 in `DESIGN` §8.2.
    """
    if intent is None:
        return None
    blocks = list(intent.blocks)
    index = {block.id: position for position, block in enumerate(blocks)}
    for item in result.report.get("islands", ()):
        block = IntentBlock(
            id=str(item["islandId"]),
            kind=str(item.get("name") or ""),
            parts=[str(part) for part in item["parts"]],
            provenance=DEFAULT_PROVENANCE,
        )
        if block.id in index:
            blocks[index[block.id]] = block
        else:
            index[block.id] = len(blocks)
            blocks.append(block)
    return replace(intent, blocks=blocks)
