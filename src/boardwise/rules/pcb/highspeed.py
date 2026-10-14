"""差分对清单 — ``pcb-hs-diffpair-inventory`` (182).

The high-speed family's first rule, and deliberately its smallest: it **lists**
the differential pairs the board declares or its net names imply, one ``INFO``
row each, and judges none of them. It exists so that 182's data layer — the
``NET`` record's declaration read into
:class:`~boardwise.core.geometry.NetMeta`, KiCad's netclasses read into the same
place, and :func:`~boardwise.core.highspeed.identify_diff_pairs` over both — is
proved end to end through the real runner rather than only by unit tests.

**What it does not do** (0.6.0's scope, listed so a reader does not mistake
silence for a clean board): no length matching, no skew, no crossing a plane
split, no return-via question, no 3W spacing, no impedance, and no
classification of a net as USB / DDR / PCIe by name. A board with a badly
routed pair gets the same one-line inventory as a perfect one.

**Zero findings when there is no pair**, and not even an ``INFO``: an empty
inventory is not a finding about the board, it is the absence of an answer, and
a row per board saying 「no pairs」 would be noise on every fixture that has
none. A board that *does* have pairs gets one row per pair — the group name,
both net names and where the pairing came from — so a reviewer can compare the
list against what they drew.

**Severity ``INFO``** follows the repository's own convention for this kind of
row: a measurement / inventory is not a defect (see ``McuSupplyGroups`` and the
FOC pack, all ``INFO``). A declared pair whose declaration cannot be read as a
pair (one net, three nets, nobody declared positive) produces **no** row here —
:func:`~boardwise.core.highspeed.identify_diff_pairs` drops it, and reporting
such a declaration is 0.6.0's rule.
"""

from __future__ import annotations

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry
from ...core.highspeed import DiffPair, identify_diff_pairs
from .base import PcbReviewContext, PcbRule

__all__ = ["DiffPairInventory", "SOURCE_LABELS"]

#: How each evidence source reads in a row, so a reviewer can tell a declaration
#: from a guess at a glance.
SOURCE_LABELS: dict[str, str] = {
    "declared": "编辑器声明",
    "heuristic": "网名启发式",
}


class DiffPairInventory(PcbRule):
    """One ``INFO`` per differential pair: the two nets, the group and the source."""

    id = "pcb-hs-diffpair-inventory"
    title = "差分对清单"
    level = "L1-pcb-geometry"
    source = "boardwise highspeed scaffold（182）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        return [self._row(board, pair) for pair in identify_diff_pairs(board)]

    def _row(self, board: BoardGeometry, pair: DiffPair) -> Finding:
        label = SOURCE_LABELS.get(pair.source, pair.source)
        message = (
            f"差分对 {pair.group}（{label}）：{pair.positive} / {pair.negative}。"
            "本行是清单：182 只报「有哪些差分对、凭什么认出来的」，"
            "等长、跨分割、阻抗等审查不在本规则内（0.6.0）。"
        )
        evidence = [f"{pair.group}: 正 {pair.positive} / 负 {pair.negative}（{pair.source}）"]
        if pair.source == "declared":
            # The flag is quoted verbatim: on 毕设FOC 1.0.0 the file declares
            # `D-` the positive net of `DP1`, and a reader who sees the row
            # should be able to see that it is the file's statement, not this
            # rule's reading of the names.
            flags = "，".join(
                f"{name} isPositiveNet={board.net_meta[name].diff_positive}"
                for name in (pair.positive, pair.negative)
                if name in board.net_meta
            )
            evidence.append(f"NET 记录 differentialName={pair.group}；{flags}")
        else:
            evidence.append(
                f"KiCad MatchDpSuffix：{pair.positive} 的互补名 {pair.negative} 在网表内"
            )
        missing = [name for name in (pair.positive, pair.negative) if name not in board.nets]
        if missing:
            # A declaration can name a net the board carries no copper for; the
            # row says so rather than letting a reader assume it was routed.
            evidence.append(f"{'、'.join(missing)} 在板上没有铜（本行读的是声明，不是布线）")
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[pair.positive, pair.negative]),
        )
