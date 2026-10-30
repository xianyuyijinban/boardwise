"""差分对识别 — 声明优先，其次 KiCad 的网名启发式 (task 182).

This is the **架子** of the high-speed family: it answers one question — *which
nets does this board pair up as differential pairs* — and nothing else. No
impedance, no length matching, no crossing-a-split check, no classification of a
net as USB / DDR / PCIe by name. Those are 0.6.0's rules
(``outputs/highspeed_rules_survey/README.md``); 182 only gives them a place to
stand: two facts per pair (which nets, and on what evidence).

Two sources, in this order:

1. **The editor's own declaration.** An EasyEDA Pro PCB document writes, per
   net, a ``NET`` record whose ``differentialName`` / ``isPositiveNet`` name the
   group and the polarity; :func:`boardwise.parsers.epru.collect_pcb_context`
   reads them into :class:`~boardwise.core.geometry.NetMeta`. A group of exactly
   two nets, one of them declared positive, is a pair — reported as
   ``source="declared"``. A declaration that cannot be read as a pair (one net,
   three nets, or no member declared positive) is **not** reported here and its
   nets take no part in the heuristic: 182 does not invent the missing half, and
   0.6.0's rule owns 「声明残缺」 as a finding of its own. Measured on the
   fixtures: 毕设FOC 1.0.0's ``PCB1`` declares ``D+/D-`` as ``DP1`` and
   ``CAN_H/CAN_L`` as ``DP2``.
2. **KiCad's suffix heuristic**, for the host that has no per-net field —
   :func:`match_dp_suffix` is a faithful port of KiCad's own
   ``DRC_ENGINE::MatchDpSuffix`` (``pcbnew/drc/drc_engine.cpp``; see the
   function's docstring for the algorithm and its source). A pair is reported
   only when the complement name **exists in the board's net table**, which is
   what keeps ``GND`` and a lone ``FOO_P`` from becoming pairs.

A net is paired **at most once**: every net named by a declaration is excluded
from the heuristic, so the two mechanisms cannot both claim a net and cannot
disagree about it. The result is deterministic — declared pairs in group-name
order, then heuristic pairs in base-name order.

Pure functions, no state, one pass over the net table: 182's rules need an
answer, not an engine.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .geometry import BoardGeometry, Point, PourShape, TrackSegment, ViaGeometry
from .measure import (
    WidthStats,
    _poured_supersedes,
    point_in_polygon,
    reference_layer_for,
    track_width_stats,
)
from .model import is_ground_net

__all__ = [
    "DiffPair",
    "identify_diff_pairs",
    "match_dp_suffix",
    "HIGH_SPEED_NAME_TOKENS",
    "is_high_speed_net_name",
    "high_speed_nets",
    "CoverageRun",
    "SplitBreak",
    "TrackCoverage",
    "measure_track_coverage",
    "STATUS_MEASURED",
    "STATUS_NO_REFERENCE",
    "STATUS_PLANE",
    "STATUS_NO_GROUND_POUR",
    "STATUS_NO_COVERAGE",
    "STATUS_ZERO_LENGTH",
    "GROUND_VIA_RADIUS_MIL",
    "ViaGroundReading",
    "ground_vias",
    "measure_via_ground",
    "DIFFPAIR_SKEW_MIL",
    "DiffPairReading",
    "measure_diff_pair",
]


@dataclass(frozen=True)
class DiffPair:
    """One differential pair: two nets, and the evidence that paired them.

    ``group`` is the name the two nets share: the editor's declared group name
    (``"DP1"``) for a declared pair, or the base name the suffix rule computed
    (``"USB_D"`` for ``USB_D+`` / ``USB_D-``) for a heuristic one — KiCad's own
    ``aBaseDpName``, kept verbatim, so it may end in the separator the file used
    (``"A1_"`` for ``A1_P``/``A1_N``).

    ``positive`` / ``negative`` are the two net names in the roles the evidence
    gives them — **not** a claim about the physics: on the 毕设FOC 1.0.0 fixture
    the file declares ``D-`` the positive net of ``DP1``, and this dataclass
    reports exactly that (see :class:`~boardwise.core.geometry.NetMeta`).

    ``source`` is ``"declared"`` or ``"heuristic"`` and is deliberately part of
    the record rather than of the group name: a rule that trusts declarations
    must be able to tell which of its rows came from one.
    """

    group: str
    positive: str
    negative: str
    source: str


#: The polarity characters KiCad's rule looks for, and what each one's
#: complement is. **Upper case only**, like KiCad's own comparison (``'N'`` /
#: ``'P'``): a net called ``usb_d-`` is not paired by this rule, and saying so
#: is more honest than guessing at a case rule KiCad does not have.
_COMPLEMENTS: dict[str, tuple[str, int]] = {
    "+": ("-", 1),
    "-": ("+", -1),
    "N": ("P", -1),
    "P": ("N", 1),
}


def match_dp_suffix(name: str) -> tuple[str, str, int] | None:
    """KiCad's ``MatchDpSuffix``: ``(base, complement, polarity)``, or ``None``.

    A direct port of ``DRC_ENGINE::MatchDpSuffix``
    ([``pcbnew/drc/drc_engine.cpp``](https://gitlab.com/kicad/code/kicad/-/raw/master/pcbnew/drc/drc_engine.cpp),
    read 2026-10-13), which is the rule KiCad itself pairs differential nets
    with when a board states no netclass pair. Its algorithm, character by
    character:

    * scan the name **from the end**; skip digits and ``_`` (they are the
      net's own numbering, not its polarity);
    * the first character that is not one of those decides: ``+`` / ``P`` mean
      「this net is the positive one」 (polarity ``+1``), ``-`` / ``N`` mean
      negated (``-1``); anything else means 「not a polarity suffix」 and the
      name yields nothing;
    * the complement's name is the base (everything before the polarity
      character, *including* the digits and underscores skipped on the way)
      plus the complement character plus the skipped tail — so ``FOO_P3``
      complements ``FOO_N3``, and ``A1_P`` complements ``A1_N``.

    ``base`` is KiCad's ``aBaseDpName`` (the polarity character and the skipped
    tail removed); it is returned because the caller needs a name for the pair
    and KiCad's own choice is the one to keep.

    ``None`` means 「this name carries no polarity suffix」 — the caller then has
    no pair to look up, and the answer is a fact about the name, not about the
    board.
    """
    skipped = 0
    for char in reversed(name):
        if "0" <= char <= "9" or char == "_":
            skipped += 1
            continue
        found = _COMPLEMENTS.get(char)
        if found is None:
            return None
        complement_char, polarity = found
        # `skipped` counts the tail *after* the polarity character; KiCad's
        # `count` also counts the polarity character itself, which is why the
        # base stops one character short of it.
        base = name[: len(name) - skipped - 1]
        tail = name[len(name) - skipped:] if skipped else ""
        return base, base + complement_char + tail, polarity
    return None


def _declared_members(board: BoardGeometry) -> dict[str, list[str]]:
    """``group → the net names that declare it``, in net-name order (declared only)."""
    groups: dict[str, list[str]] = {}
    for name, meta in board.net_meta.items():
        if meta.diff_pair:
            groups.setdefault(meta.diff_pair, []).append(name)
    return {group: sorted(names) for group, names in groups.items()}


def _declared_pair(board: BoardGeometry, group: str, names: list[str]) -> DiffPair | None:
    """The declared pair ``group`` reads as, or ``None`` when it does not read as one.

    Two nets and exactly one of them declared positive is the whole test. A
    group of another size (1, 3, …) and a group whose members declare no single
    positive net (nobody says so, or both do) are both **not** reported: the
    first is 0.6.0's 「声明残缺」, the second is a contradiction this module
    refuses to resolve by guessing. Neither is silently folded into the
    heuristic — those nets are declared, and are excluded there.
    """
    if len(names) != 2:
        return None
    positive = [
        name for name in names if board.net_meta[name].diff_positive is True
    ]
    if len(positive) != 1:
        return None
    other = names[0] if names[1] == positive[0] else names[1]
    return DiffPair(group=group, positive=positive[0], negative=other, source="declared")


def identify_diff_pairs(board: BoardGeometry) -> list[DiffPair]:
    """Every differential pair the board declares or its net names imply (182).

    Declared pairs first (group name order), then heuristic ones (base name
    order). The heuristic walks the board's own net table — the nets that
    actually carry copper (:attr:`BoardGeometry.nets`), not the file's net list
    — because a pair is only a pair if both nets are on the board: that is
    KiCad's own existence test (``aBoard->FindNet( coupledNetName )``) and what
    keeps a lone ``FOO_P`` from pairing with a name nothing carries.

    Each net is returned in at most one pair. ``source`` says which of the two
    mechanisms produced it; see the module docstring for why a declaration that
    does not read as a pair is dropped rather than repaired.
    """
    pairs: list[DiffPair] = []
    declared = _declared_members(board)
    taken: set[str] = set()
    for group in sorted(declared):
        names = declared[group]
        taken.update(names)
        pair = _declared_pair(board, group, names)
        if pair is not None:
            pairs.append(pair)

    used = set(taken)
    for name in sorted(board.nets):
        if name in used:
            continue
        found = match_dp_suffix(name)
        if found is None:
            continue
        base, complement, polarity = found
        if complement not in board.nets or complement in used:
            continue
        used.add(name)
        used.add(complement)
        positive, negative = (name, complement) if polarity > 0 else (complement, name)
        pairs.append(DiffPair(group=base, positive=positive, negative=negative, source="heuristic"))
    return pairs


# ---------------------------------------------------------------------------
# 200B: the high-speed net set and the reference-layer coverage measurement
# ---------------------------------------------------------------------------

#: The name tokens this house rule (200B) reads as 「high-speed」. Applied to a
#: net name's **tokens** (`[A-Za-z0-9]+` runs of the upper-cased name) and to a
#: netclass name, each token matched by **prefix**: `USB_D+` → `USB`, `DDR3_DQ0`
#: → `DDR3`, `SPI1_SCK` → `SCK`. A token rule rather than a whole-name prefix
#: because real boards write `SPI1_SCK` and `DDR3_*`, and a whole-name test would
#: miss every one of them. The list is the task book's (200B §1.1); it is a
#: **candidate** set like :func:`boardwise.core.model.is_ground_net`'s names —
#: a net it does not recognise is 「not known to be high-speed」, never
#: 「not high-speed」, and nothing here invents a user-facing configuration.
HIGH_SPEED_NAME_TOKENS: tuple[str, ...] = (
    "CLK", "SCK", "USB", "ETH", "RGMII", "PCIE", "DDR", "DQS", "MIPI", "HDMI", "LVDS",
)

_TOKEN_SPLIT = re.compile(r"[^A-Za-z0-9]+")


def is_high_speed_net_name(name: str | None) -> bool:
    """Does this net (or netclass) name carry one of the high-speed tokens?

    Token-prefix matching, upper case only — the same 「do not normalise what
    the file wrote」 discipline :func:`match_dp_suffix` follows. ``None`` and an
    empty name are never high-speed.
    """
    if not name:
        return False
    for token in _TOKEN_SPLIT.split(name.upper()):
        if token and any(token.startswith(word) for word in HIGH_SPEED_NAME_TOKENS):
            return True
    return False


def high_speed_nets(board: BoardGeometry) -> list[str]:
    """The board's high-speed nets, sorted: 182's diff pairs ∪ the name/netclass sieve.

    182's members come first-class because a differential pair *is* the
    canonical high-speed net (`identify_diff_pairs` already answers which nets
    the board declares or its names imply); the sieve then adds the
    single-ended nets whose name says CLK / USB / DDR / … . Both readings are
    **names**, not proofs: the set says 「this net is in the family 200B
    measures」, not 「this net must be routed as high-speed」.

    Computed **once per rule run** by the rule that consumes it (200B §1.1),
    and only over nets that carry copper (:attr:`BoardGeometry.nets`) — a name
    in the file's net list with no copper on the board is not a subject.
    """
    nets: set[str] = set()
    for pair in identify_diff_pairs(board):
        nets.add(pair.positive)
        nets.add(pair.negative)
    for name in board.nets:
        if is_high_speed_net_name(name):
            nets.add(name)
    for name, meta in board.net_meta.items():
        if name in board.nets and meta.net_class and is_high_speed_net_name(meta.net_class):
            nets.add(name)
    return sorted(nets)


#: :attr:`TrackCoverage.status` — the segment was measured against real copper.
STATUS_MEASURED = "measured"
#: The segment's layer has no adjacent copper layer in the stackup.
STATUS_NO_REFERENCE = "no-reference"
#: The reference layer is a **PLANE**: no split geometry to read. This is
#: 「未测」, never 「平面完整」 — see :func:`measure_track_coverage`.
STATUS_PLANE = "plane"
#: The reference layer carries no ground-class pour polygon at all.
STATUS_NO_GROUND_POUR = "no-ground-pour"
#: There is ground copper on the reference layer, but none of it is under this
#: segment — no coverage interval exists, so there is no gap to report.
STATUS_NO_COVERAGE = "no-coverage"
#: A zero-length segment has no extent to divide into intervals.
STATUS_ZERO_LENGTH = "zero-length"

#: Break kinds in :attr:`TrackCoverage.breaks`.
BREAK_GAP = "gap"
BREAK_BOUNDARY = "boundary"

#: Parametric tolerance for 「two split points are the same point」.
_PARAM_EPS = 1e-12


@dataclass(frozen=True)
class CoverageRun:
    """One maximal interval of the segment that ground copper covers.

    ``start`` / ``end`` are **parametric** positions along the segment
    (``0.0`` at :attr:`TrackSegment.start`, ``1.0`` at its end); ``pours`` is
    the set of :attr:`BoardGeometry.pours` **object ordinals** covering it.
    Ordinals rather than record ids on purpose — a record id is evidence, an
    ordinal is identity (200B §1.3).
    """

    start: float
    end: float
    pours: frozenset[int]


@dataclass(frozen=True)
class SplitBreak:
    """One discontinuity along a segment: a gap or a pour boundary.

    ``at`` is the **board coordinate** (mils) of the break — the middle of a
    gap, or the junction between two covered runs — so a reader can put a
    marker on the canvas without re-deriving the parameter. ``before`` /
    ``after`` are the pour ordinals on each side (empty on the side a gap has
    no copper on).
    """

    kind: str
    start: float
    end: float
    at: Point
    before: tuple[int, ...] = ()
    after: tuple[int, ...] = ()


@dataclass
class TrackCoverage:
    """What one high-speed track sees on its adjacent reference layer (200B).

    ``status`` says **whether the question could be asked** at all, and that
    distinction is the point of the record: a ``PLANE`` reference layer, a
    missing neighbour, a reference layer with no ground pour and a segment
    nothing covers are four different 「not measured / nothing to measure」
    answers, and none of them is 「no split」. Only
    :data:`STATUS_MEASURED` with a non-empty ``breaks`` is a defect claim.
    """

    track_id: str = ""
    net: str | None = None
    layer_id: int | None = None
    reference_layer_id: int | None = None
    status: str = STATUS_MEASURED
    runs: list[CoverageRun] = field(default_factory=list)
    breaks: list[SplitBreak] = field(default_factory=list)


def _ground_pour_shapes(
    board: BoardGeometry, layer_id: int
) -> list[tuple[int, PourShape, list[list[Point]]]]:
    """Ground pour shapes on one layer as ``(ordinal, pour, rings)``.

    Same sieve as :func:`boardwise.core.measure._ground_pours_on` — copper
    kinds only, ground-class net names only, and a ``POUR`` region that a
    ``POURED`` result supersedes dropped — plus what that helper cannot give a
    split test: the **rings** (outline first, then voids), falling back to
    ``[points]`` for a hand-built shape that carries none (200B §1.3).
    """
    superseded = _poured_supersedes(board)
    out: list[tuple[int, PourShape, list[list[Point]]]] = []
    for ordinal, pour in enumerate(board.pours):
        if pour.kind not in ("fill", "poly", "pour", "poured") or len(pour.points) < 3:
            continue
        if pour.kind != "poured" and pour.id in superseded:
            continue
        if pour.layer_id != layer_id or not pour.net or not is_ground_net(pour.net):
            continue
        rings = [ring for ring in pour.rings if len(ring) >= 3] or [pour.points]
        out.append((ordinal, pour, rings))
    return out


def _edge_params(a: Point, b: Point, ring: list[Point]) -> list[float]:
    """Parameters ``t ∈ (0, 1)`` where segment ``a→b`` crosses ``ring``'s edges.

    Exact line/segment intersection — no sampling: every crossing becomes a
    split point, which is what makes the intervals exact (200B §1.4). Edges
    that are collinear with the segment contribute nothing (their endpoints
    arrive through the neighbouring edges).
    """
    ts: list[float] = []
    dx, dy = b.x - a.x, b.y - a.y
    count = len(ring)
    for index in range(count):
        p = ring[index]
        q = ring[(index + 1) % count]
        ex, ey = q.x - p.x, q.y - p.y
        det = ex * dy - dx * ey
        if abs(det) < 1e-12:
            continue
        wx, wy = p.x - a.x, p.y - a.y
        t = (ex * wy - wx * ey) / det
        u = (dx * wy - wx * dy) / det
        if not (-1e-9 <= u <= 1.0 + 1e-9):
            continue
        if _PARAM_EPS < t < 1.0 - _PARAM_EPS:
            ts.append(t)
    return ts


def _covering_pours(
    point: Point, pours: list[tuple[int, PourShape, list[list[Point]]]]
) -> frozenset[int]:
    """Ordinals of the ground pours whose **effective** copper holds ``point``.

    Effective copper is the outline **minus its voids** — a point inside a void
    (a clearance cut for another net, a keepout) is not covered, which is what
    a segment passing over a pour's slot has to see. The midpoint test is the
    only containment test here (200B §1.4): the intervals are already exact,
    so one midpoint per interval decides it.
    """
    covering: set[int] = set()
    for ordinal, _pour, rings in pours:
        if not point_in_polygon(point, rings[0]):
            continue
        if any(point_in_polygon(point, void) for void in rings[1:]):
            continue
        covering.add(ordinal)
    return frozenset(covering)


def _at(a: Point, b: Point, t: float) -> Point:
    return Point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)


def measure_track_coverage(board: BoardGeometry, track: TrackSegment) -> TrackCoverage:
    """Measure one track's copper coverage on its adjacent reference layer.

    The measurement, in the order it asks its questions:

    1. **Which layer** — :func:`boardwise.core.measure.reference_layer_for`,
       the physical neighbour (top of the stackup preferred). No neighbour →
       :data:`STATUS_NO_REFERENCE`, silent.
    2. **Is it a plane** — a ``PLANE`` reference layer has no split geometry in
       the file (the copper is the layer), so the answer is
       :data:`STATUS_PLANE`: **未测**, and a caller must not read it as 「the
       plane is whole」. Split *detection* on planes needs geometry this file
       does not carry (islands of a plane layer), which is 200B's stated
       boundary, not a claim.
    3. **Is there ground copper to read** — no ground-class pour on that layer
       → :data:`STATUS_NO_GROUND_POUR`, silent.
    4. **Where is the copper** — the segment is cut at every exact crossing of
       every ring edge (outline and voids, §1.4), each interval's midpoint is
       tested against outline-minus-voids, and the covered intervals become
       :class:`CoverageRun` rows. Nothing covered anywhere → the whole segment
       is outside the pour: :data:`STATUS_NO_COVERAGE`, silent — a segment the
       plane was never meant to sit under is not a gap (200B §1.3).

    What is reported (only when at least one interval is covered):
    :data:`BREAK_GAP` for every uncovered interval, and :data:`BREAK_BOUNDARY`
    at every junction between two covered intervals that share **no** pour
    ordinal — the copper changes from one pour (or net) to another, so the
    return current must jump. Two covered intervals sharing a pour are one
    piece of copper seen through a void and are **not** a break.

    The four-corner :func:`boardwise.core.measure.return_path_projection` is
    deliberately **not** reused: its corner mask answers 「how much of the
    footprint is over copper」, not 「where along the line does it stop」, and a
    split running diagonally under a segment can leave all four corners outside
    while the middle is covered (200B §1.4).
    """
    coverage = TrackCoverage(
        track_id=track.id, net=track.net, layer_id=track.layer_id
    )
    a, b = track.start, track.end
    if track.length <= 1e-9:
        coverage.status = STATUS_ZERO_LENGTH
        return coverage

    reference = reference_layer_for(board, track.layer_id)
    coverage.reference_layer_id = reference
    if reference is None:
        coverage.status = STATUS_NO_REFERENCE
        return coverage
    info = board.layers.get(reference)
    if info is not None and info.layer_type == "PLANE":
        coverage.status = STATUS_PLANE
        return coverage

    pours = _ground_pour_shapes(board, reference)
    if not pours:
        coverage.status = STATUS_NO_GROUND_POUR
        return coverage

    params = {0.0, 1.0}
    for _ordinal, _pour, rings in pours:
        for ring in rings:
            params.update(_edge_params(a, b, ring))
    ordered = sorted(params)

    intervals: list[tuple[float, float, frozenset[int]]] = []
    for low, high in zip(ordered, ordered[1:]):
        if high - low <= _PARAM_EPS:
            continue
        mid = (low + high) / 2.0
        intervals.append((low, high, _covering_pours(_at(a, b, mid), pours)))

    if not any(cover for _low, _high, cover in intervals):
        coverage.status = STATUS_NO_COVERAGE
        return coverage

    # Merge adjacent covered intervals into runs, for the run table and for
    # the gap walk below.
    runs: list[CoverageRun] = []
    current: CoverageRun | None = None
    for low, high, cover in intervals:
        if not cover:
            if current is not None:
                runs.append(current)
                current = None
            continue
        if current is not None and current.end >= low - _PARAM_EPS:
            current = CoverageRun(current.start, high, current.pours | cover)
        else:
            if current is not None:
                runs.append(current)
            current = CoverageRun(low, high, cover)
    if current is not None:
        runs.append(current)
    coverage.runs = runs

    breaks: list[SplitBreak] = []
    # Boundaries: two **adjacent** covered intervals whose pour sets share no
    # object. Read on the raw intervals (not the merged runs) so the two sides
    # are the copper immediately left and right of the junction: a run that
    # widens from pour A to A∪B and narrows back to B is one continuous piece
    # of copper and files nothing.
    for previous, following in zip(intervals, intervals[1:]):
        if not previous[2] or not following[2]:
            continue
        if following[0] - previous[1] > _PARAM_EPS:
            continue  # an uncovered stretch between them: that is a gap
        if previous[2] & following[2]:
            continue
        breaks.append(
            SplitBreak(
                kind=BREAK_BOUNDARY,
                start=previous[1],
                end=following[0],
                at=_at(a, b, following[0]),
                before=tuple(sorted(previous[2])),
                after=tuple(sorted(following[2])),
            )
        )

    # Gaps: every uncovered stretch inside the covered extent (before the
    # first run and after the last are 「the pour ends here」, not a split
    # through the return path — the segment's own ends are its pads).
    for previous, following in zip(runs, runs[1:]):
        if following.start - previous.end > _PARAM_EPS:
            breaks.append(
                SplitBreak(
                    kind=BREAK_GAP,
                    start=previous.end,
                    end=following.start,
                    at=_at(a, b, (previous.end + following.start) / 2.0),
                    before=tuple(sorted(previous.pours)),
                    after=tuple(sorted(following.pours)),
                )
            )

    breaks.sort(key=lambda item: item.start)
    coverage.breaks = breaks
    coverage.status = STATUS_MEASURED
    return coverage


# ---------------------------------------------------------------------------
# 200C1 — 换层伴随地孔 (the ground via next to a high-speed via)
# ---------------------------------------------------------------------------

#: The house rule's radius, in mils: a high-speed via counts as accompanied when
#: a ground-class via's **centre** lies within this distance of its centre.
#: **A house rule, not a standard** (200C1 §1.2): 50.0 mil ≈ 1.27 mm is the
#: spacing our own boards and the flyback golden board keep, and the task book
#: says it is tunable. The comparison is inclusive — exactly 50.0 mil is
#: accompanied — because a boundary that flips on floating-point noise is worse
#: than one that rounds in the engineer's favour.
GROUND_VIA_RADIUS_MIL = 50.0


@dataclass(frozen=True)
class ViaGroundReading:
    """What one high-speed via sees: the nearest ground via and how far it is.

    ``nearest_via_id`` / ``nearest_distance_mil`` are ``None`` together when the
    board has **no ground-class via at all** — the reading says 「no ground via
    to measure against」 rather than a distance of infinity, so a row built from
    it can state the absence instead of inventing a number.

    ``at`` is the high-speed via's own centre (mils), kept in the record so a
    reader can put a marker on the canvas without looking the via up again.
    """

    via_id: str
    net: str | None
    at: Point
    nearest_via_id: str | None = None
    nearest_distance_mil: float | None = None


def ground_vias(board: BoardGeometry) -> list[ViaGeometry]:
    """The board's ground-class vias, in board order.

    The sieve is :func:`boardwise.core.model.is_ground_net` on ``via.net`` — the
    same candidate-name reading the pour side uses — and each via is asked
    **once** here so a caller that walks every high-speed via does not re-ask
    per pair (200C1 §1.1). Vias with no net name are never ground: a via the
    file does not attribute is 「not known to be ground」.
    """
    return [via for via in board.vias if is_ground_net(via.net)]


def measure_via_ground(via: ViaGeometry, ground: list[ViaGeometry]) -> ViaGroundReading:
    """The nearest ground via to ``via``, by centre-to-centre Euclid in mils.

    One pass over ``ground`` with a deterministic tie-break (**distance, then
    via id**) so two runs — and two rule implementations — cannot disagree
    about *which* ground via a row names. The distance is measured between
    **centres**, not between copper edges: 200C1 asks 「is there a return via
    near this signal via」, and annulus-to-annulus would need a via size
    comparison this reading does not make.
    """
    best: tuple[float, str] | None = None
    best_via: ViaGeometry | None = None
    for other in ground:
        distance = math.hypot(other.x - via.x, other.y - via.y)
        key = (distance, other.id)
        if best is None or key < best:
            best = key
            best_via = other
    if best is None or best_via is None:
        return ViaGroundReading(via_id=via.id, net=via.net, at=via.center)
    return ViaGroundReading(
        via_id=via.id,
        net=via.net,
        at=via.center,
        nearest_via_id=best_via.id,
        nearest_distance_mil=best[0],
    )


# ---------------------------------------------------------------------------
# 200C2 — 差分对内 (length skew and via parity inside a pair)
# ---------------------------------------------------------------------------

#: The house rule's skew limit, in mils: a pair whose two nets' **total** track
#: lengths differ by more than this is out of tolerance. **A house rule, not a
#: standard** (200C2 §1.2): every interface has its own budget (USB 2.0 is far
#: looser than PCIe), the fixtures carry no interface class this reading could
#: consult, and the task book calls the number tunable. The comparison is
#: **strict** — exactly 5.0 mil is silent, 5.1 mil warns — because the number is
#: the boundary of 「等长」 as this house writes it, and a pair measured exactly
#: at the limit has not crossed it.
DIFFPAIR_SKEW_MIL = 5.0


@dataclass(frozen=True)
class DiffPairReading:
    """What one differential pair measures: length, layers and vias (200C2).

    The three facts are kept **separate** because they are separate questions
    and the rules answer them separately (§1.2 / §1.3): a pair can be exactly
    equal in length and still hop layers on one side only, and it can be
    out of tolerance while both sides use the same via count.

    **Lengths.** ``positive_length_mil`` / ``negative_length_mil`` are the
    sums :func:`boardwise.core.measure.track_width_stats` reports for each net —
    that function is the repository's one length reading, and 200C2 does not
    write a second one. ``per_layer`` is its ``per_layer`` table flattened to
    ``(layer_id, total_length)`` pairs sorted by layer id, so the record is
    order-independent and hashable.

    **Layers.** ``*_unlayered_tracks`` counts the tracks the file gave no layer
    to. They are inside the length totals (``track_width_stats`` counts them)
    but they have no home in ``per_layer``, so a pair with any of them on either
    side is **not comparable by layer set** — :attr:`layers_comparable` says so
    and :attr:`layer_sets_differ` refuses to answer — rather than being read as
    「one side uses a different stack」 (§1.4).

    **Vias.** ``*_vias`` is :attr:`~boardwise.core.geometry.NetGeometry.via_count`
    verbatim: the number of vias the file attributes to that net, of any type.
    """

    group: str
    source: str
    positive: str
    negative: str
    positive_length_mil: float
    negative_length_mil: float
    positive_per_layer: tuple[tuple[int, float], ...] = ()
    negative_per_layer: tuple[tuple[int, float], ...] = ()
    positive_tracks: int = 0
    negative_tracks: int = 0
    positive_unlayered_tracks: int = 0
    negative_unlayered_tracks: int = 0
    positive_vias: int = 0
    negative_vias: int = 0

    @property
    def skew_mil(self) -> float:
        """Absolute difference of the two total track lengths, in mils."""
        return abs(self.positive_length_mil - self.negative_length_mil)

    @property
    def measurable(self) -> bool:
        """Both nets carry at least one track: the pair can be judged at all.

        §1.4's first boundary. One side unrouted is 「not yet a pair of lengths」
        — a length difference against zero copper would be a number about the
        router's progress, not about skew — so the pair produces no finding.
        """
        return self.positive_tracks > 0 and self.negative_tracks > 0

    @property
    def layers_comparable(self) -> bool:
        """Neither side has a track the file gave no layer to (§1.4)."""
        return not self.positive_unlayered_tracks and not self.negative_unlayered_tracks

    @property
    def positive_layer_ids(self) -> frozenset[int]:
        return frozenset(layer_id for layer_id, _length in self.positive_per_layer)

    @property
    def negative_layer_ids(self) -> frozenset[int]:
        return frozenset(layer_id for layer_id, _length in self.negative_per_layer)

    @property
    def layer_sets_differ(self) -> bool:
        """Do the two sides use different sets of layers — **only** when readable.

        ``False`` when :attr:`layers_comparable` is false: silence here is
        「未测」, and a caller that read it as 「same layers」 would be claiming
        a comparison the copper did not support.
        """
        if not self.layers_comparable:
            return False
        return self.positive_layer_ids != self.negative_layer_ids


def _per_layer_table(stats: WidthStats) -> tuple[tuple[int, float], ...]:
    return tuple(
        (layer_id, stats.per_layer[layer_id].total_length)
        for layer_id in sorted(stats.per_layer)
    )


def measure_diff_pair(board: BoardGeometry, pair: DiffPair) -> DiffPairReading:
    """Read one differential pair's length, per-layer and via facts (200C2).

    Every number comes from an existing reading: the two length totals and the
    per-layer tables from :func:`boardwise.core.measure.track_width_stats`, the
    via counts from :attr:`~boardwise.core.geometry.NetGeometry.via_count`. The
    only thing this function does itself is subtract, sort and count — which is
    the whole point of §1.1 (one length algorithm in the repository, not two).

    A net the board carries no copper for reads as zeros (``track_width_stats``
    returns an empty record for an unknown net), so :attr:`DiffPairReading.measurable`
    is ``False`` and no judgement follows.
    """
    positive = track_width_stats(board, pair.positive)
    negative = track_width_stats(board, pair.negative)
    return DiffPairReading(
        group=pair.group,
        source=pair.source,
        positive=pair.positive,
        negative=pair.negative,
        positive_length_mil=positive.total_length,
        negative_length_mil=negative.total_length,
        positive_per_layer=_per_layer_table(positive),
        negative_per_layer=_per_layer_table(negative),
        positive_tracks=positive.track_count,
        negative_tracks=negative.track_count,
        positive_unlayered_tracks=positive.track_count
        - sum(entry.track_count for entry in positive.per_layer.values()),
        negative_unlayered_tracks=negative.track_count
        - sum(entry.track_count for entry in negative.per_layer.values()),
        positive_vias=board.net(pair.positive).via_count,
        negative_vias=board.net(pair.negative).via_count,
    )
