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

from dataclasses import dataclass

from .geometry import BoardGeometry

__all__ = ["DiffPair", "identify_diff_pairs", "match_dp_suffix"]


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
