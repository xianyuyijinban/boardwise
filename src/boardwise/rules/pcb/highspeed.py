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
from ...core.highspeed import (
    BREAK_BOUNDARY,
    BREAK_GAP,
    DIFFPAIR_SKEW_MIL,
    GROUND_VIA_RADIUS_MIL,
    STATUS_MEASURED,
    DiffPair,
    DiffPairReading,
    TrackCoverage,
    ViaGroundReading,
    ground_vias,
    high_speed_nets,
    identify_diff_pairs,
    measure_diff_pair,
    measure_track_coverage,
    measure_via_ground,
)
from .base import PcbReviewContext, PcbRule

__all__ = [
    "DiffPairInventory",
    "SOURCE_LABELS",
    "CrossSplit",
    "CROSS_SPLIT_RULE_ID",
    "BREAK_LABELS",
    "GroundViaCompanion",
    "GROUND_VIA_RULE_ID",
    "DiffPairSkew",
    "DIFFPAIR_SKEW_RULE_ID",
    "DiffPairViaParity",
    "DIFFPAIR_VIA_PARITY_RULE_ID",
]

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


#: The rule id 200B lands. Severity ``WARN`` throughout: a split under a
#: high-speed trace is a real return-path discontinuity (TI SPRAAR7F), but the
#: threshold is a **house rule** and the goods are still being tuned, so the row
#: is a warning a reviewer acts on and never an ``ERROR`` that decides a build.
CROSS_SPLIT_RULE_ID = "pcb-hs-cross-split"

#: How each break kind reads in a row. The word is the **category** the task
#: book names (200B §1.2), kept as its own token so a reader (or a downstream
#: consumer) can tell 「no copper at all」 from 「the copper changed owner」.
BREAK_LABELS: dict[str, str] = {
    BREAK_GAP: "gap（无有效铺铜覆盖）",
    BREAK_BOUNDARY: "boundary（覆盖铜换了 pour 对象）",
}


class CrossSplit(PcbRule):
    """One ``WARN`` per high-speed track that crosses a reference-plane split.

    The measurement is :func:`boardwise.core.highspeed.measure_track_coverage`;
    this class decides *which* tracks to ask about
    (:func:`boardwise.core.highspeed.high_speed_nets`, computed **once** per
    run) and turns each track's breaks into one row. A track gets **at most one
    finding**, and that row lists every break it has — a segment that leaves
    and re-enters the copper is one defect with two coordinates, not two rows a
    reader has to reassemble.

    **Silence is not a clean bill of health.** The rule says nothing when the
    reference layer is a ``PLANE`` (the file carries no split geometry for it),
    when the layer has no reference at all, when the reference layer carries no
    ground pour, when nothing covers the segment, or for a zero-length segment.
    Those are five different absences, and the evidence document for 200B
    records the same sentence: **未测，不是平面完整**. Only a measured segment
    with at least one break produces a row.

    **House-rule boundary (200B, iterable).** No threshold is applied — the
    judgement is 「is there copper, and is it the same pour」, both read off the
    geometry. Which nets count as high-speed is the token sieve in
    ``core.highspeed``; widening or narrowing it moves this rule's input and is
    a reading decision, not a measurement change.
    """

    id = CROSS_SPLIT_RULE_ID
    title = "高速线跨参考层分割"
    level = "L1-pcb-geometry"
    source = "boardwise 屋规（200B，可迭代）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        nets = set(high_speed_nets(board))
        if not nets:
            return []
        findings: list[Finding] = []
        for track in board.tracks:
            if track.net not in nets:
                continue
            coverage = measure_track_coverage(board, track)
            if coverage.status != STATUS_MEASURED or not coverage.breaks:
                continue
            findings.append(self._row(board, coverage))
        return findings

    def _layer_name(self, board: BoardGeometry, layer_id: int | None) -> str:
        if layer_id is None:
            return "无"
        info = board.layers.get(layer_id)
        return f"{info.name}（{info.layer_id}）" if info is not None else str(layer_id)

    def _row(self, board: BoardGeometry, coverage: TrackCoverage) -> Finding:
        signal = self._layer_name(board, coverage.layer_id)
        reference = self._layer_name(board, coverage.reference_layer_id)
        kinds = sorted({item.kind for item in coverage.breaks})
        message = (
            f"高速线 {coverage.net} 的走线 {coverage.track_id} 在信号层 {signal} 的"
            f"参考层 {reference} 上跨分割"
            f"（{'、'.join(BREAK_LABELS.get(kind, kind) for kind in kinds)}），"
            f"共 {len(coverage.breaks)} 处断点。判据为屋规（200B，可迭代）："
            "沿段中线求参考层地类有效铺铜的覆盖区间，无铜为 gap、相邻覆盖换了 "
            "pour 对象为 boundary；不设距离阈值，参考层为 PLANE 时未测。"
        )
        evidence = [
            f"走线 {coverage.track_id}: 网 {coverage.net} @ 信号层 {signal} → 参考层 {reference}",
        ]
        for item in coverage.breaks:
            evidence.append(
                f"{BREAK_LABELS.get(item.kind, item.kind)} @ "
                f"({item.at.x:.1f}, {item.at.y:.1f}) mil，"
                f"段参数 {item.start:.4f}→{item.end:.4f}"
            )
        covered = ", ".join(
            f"pour#{sorted(run.pours)} [{run.start:.4f}→{run.end:.4f}]"
            for run in coverage.runs
        )
        evidence.append(f"覆盖区间（board.pours 对象序号）：{covered}")
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[coverage.net] if coverage.net else []),
        )


#: The rule id 200C1 lands. ``WARN`` throughout, like 200B and for the same
#: reason: the radius is a **house rule** the task book calls tunable, and a
#: via without a companion is a routing decision an engineer can defend.
GROUND_VIA_RULE_ID = "pcb-hs-via-ground-companion"


class GroundViaCompanion(PcbRule):
    """One ``WARN`` per high-speed via with no ground via within the radius.

    The question is deliberately narrow (200C1 §1.4): **is there a ground-class
    via centre within** :data:`~boardwise.core.highspeed.GROUND_VIA_RADIUS_MIL`
    **of this high-speed via centre** — a radius test, nothing more. It does
    **not** ask whether that ground via bridges the same reference pair the
    signal via leaves (``ViaGeometry.unused_inner_layers`` is read by no rule
    here), does not require a return-via **array**, does not count stitching
    pitch, and says nothing about stub length or impedance. A board this rule is
    silent on can still have every one of those defects, and the evidence
    document for 200C1 says so in the same words: **未测，不是没有问题**.

    **What counts as a subject.** Only vias whose net is in
    :func:`boardwise.core.highspeed.high_speed_nets` — 182's pairs plus 200B's
    name/netclass sieve, computed **once per run** — and only against vias whose
    net :func:`boardwise.core.model.is_ground_net` calls ground, sieved **once
    per run** by :func:`boardwise.core.highspeed.ground_vias`. Both sets are
    name readings, not proofs: widening either moves this rule's input and is a
    reading decision, not a measurement change.

    **Silence is not a clean bill of health.** No high-speed net, no
    high-speed via, or a ground via inside the radius all produce no row. The
    last one is the only 「pass」 — and it is a pass about **this radius only**
    (see :data:`GROUND_VIA_RADIUS_MIL`).
    """

    id = GROUND_VIA_RULE_ID
    title = "高速过孔伴随地孔"
    level = "L1-pcb-geometry"
    source = "boardwise 屋规（200C1，可迭代）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        nets = set(high_speed_nets(board))
        if not nets:
            return []
        ground = ground_vias(board)
        findings: list[Finding] = []
        for via in board.vias:
            if via.net not in nets:
                continue
            reading = measure_via_ground(via, ground)
            distance = reading.nearest_distance_mil
            if distance is not None and distance <= GROUND_VIA_RADIUS_MIL:
                continue
            findings.append(self._row(reading))
        return findings

    def _row(self, reading: ViaGroundReading) -> Finding:
        at = f"({reading.at.x:.1f}, {reading.at.y:.1f}) mil"
        if reading.nearest_distance_mil is None or reading.nearest_via_id is None:
            nearest = "板上没有任何 GND 类过孔，无法测量伴随"
            nearest_evidence = "最近地孔：无（板上 GND 类过孔数为 0）"
        else:
            nearest = (
                f"最近地孔 {reading.nearest_via_id} 距离 {reading.nearest_distance_mil:.2f} mil"
            )
            nearest_evidence = (
                f"最近地孔 {reading.nearest_via_id} @ {reading.nearest_distance_mil:.2f} mil"
            )
        message = (
            f"高速过孔 {reading.via_id}（网 {reading.net} @ {at}）没有伴随地孔："
            f"{nearest}，超过阈值 {GROUND_VIA_RADIUS_MIL:.1f} mil。"
            "判据为屋规（200C1，可迭代）：只比过孔中心到最近 GND 类过孔中心的距离，"
            "不判该地孔是否跨接同一参考层，也不做回流孔阵列、stub 或阻抗。"
        )
        evidence = [
            f"信号过孔 {reading.via_id}: 网 {reading.net} @ {at}",
            f"阈值 {GROUND_VIA_RADIUS_MIL:.1f} mil（中心距，含边界静默）",
            nearest_evidence,
        ]
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[reading.net] if reading.net else []),
        )


#: The rule ids 200C2 lands, in the order they are registered. Both read the
#: same :class:`~boardwise.core.highspeed.DiffPairReading`, and neither reads
#: the other's output: :data:`DIFFPAIR_SKEW_RULE_ID` is a ``WARN`` (a length
#: budget is something a reviewer must act on), :data:`DIFFPAIR_VIA_PARITY_RULE_ID`
#: an ``INFO`` (a via count is a fact about the routing, not a defect by itself).
DIFFPAIR_SKEW_RULE_ID = "pcb-hs-diffpair-skew"
DIFFPAIR_VIA_PARITY_RULE_ID = "pcb-hs-diffpair-via-parity"


class DiffPairSkew(PcbRule):
    """One ``WARN`` per differential pair that is out of tolerance (200C2 A3).

    Two facts per pair, and the row lists **both** whichever one fired (§1.2):

    1. **Skew** — ``|L+ − L−| > DIFFPAIR_SKEW_MIL`` (5.0 mil, house rule,
       strict: 5.0 is silent). The lengths are
       :func:`boardwise.core.measure.track_width_stats`' totals; this rule does
       not add a second length algorithm.
    2. **Layer set** — the two sides' effective layer id sets differ. A pair
       that leaves the top layer on one side only has a return-path asymmetry
       a total length cannot show, and a pair whose sides use the same set of
       layers can still be badly skewed (and vice versa) — which is why the row
       states both readings rather than the one that fired.

    **At most one row per pair**, with every fact in it; a pair with both
    defects is one defect with two causes, not two rows a reader has to
    reassemble.

    **Silence is not a clean bill of health** (§1.4). No differential pair, a
    pair with no track on either net, a pair with no copper on one net, and a
    pair within 5.0 mil whose layers match all produce no row. A pair whose
    layer sets cannot be compared (a track the file gave no layer to, on either
    side) is a **narrower** silence: only the layer judgement is withheld —
    that case is **未测**, never 「same layers」 — while the length reading keeps
    working, so a >5.0 mil skew on such a pair still files its ``WARN`` (the
    row says the layer set is 未测 instead of claiming it matches). Nothing here
    reads impedance, Tpd, equal-length groups, 3W, stub or A1/A2 (§1.5).
    """

    id = DIFFPAIR_SKEW_RULE_ID
    title = "差分对内长度/层偏差"
    level = "L1-pcb-geometry"
    source = "boardwise 屋规（200C2，可迭代）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        findings: list[Finding] = []
        for pair in identify_diff_pairs(board):
            reading = measure_diff_pair(board, pair)
            if not reading.measurable:
                continue
            skew_hit = reading.skew_mil > DIFFPAIR_SKEW_MIL
            if not skew_hit and not reading.layer_sets_differ:
                continue
            findings.append(self._row(board, reading, skew_hit))
        return findings

    def _layer_name(self, board: BoardGeometry, layer_id: int) -> str:
        info = board.layers.get(layer_id)
        return f"{info.name}({layer_id})" if info is not None else str(layer_id)

    def _layer_set_text(self, board: BoardGeometry, reading: DiffPairReading) -> str:
        if not reading.layers_comparable:
            sides = [
                f"{name} {count} 段"
                for name, count in (
                    (reading.positive, reading.positive_unlayered_tracks),
                    (reading.negative, reading.negative_unlayered_tracks),
                )
                if count
            ]
            return f"层集合未测（{'、'.join(sides)} track 无层，不判差异）"
        positive = "、".join(
            self._layer_name(board, layer_id)
            for layer_id in sorted(reading.positive_layer_ids)
        )
        negative = "、".join(
            self._layer_name(board, layer_id)
            for layer_id in sorted(reading.negative_layer_ids)
        )
        verdict = "不同" if reading.layer_sets_differ else "相同"
        return f"层集合{verdict}（正 {positive or '无'} / 负 {negative or '无'}）"

    def _row(
        self, board: BoardGeometry, reading: DiffPairReading, skew_hit: bool
    ) -> Finding:
        label = SOURCE_LABELS.get(reading.source, reading.source)
        if skew_hit:
            skew_text = (
                f"超阈值（长度差 {reading.skew_mil:.2f} mil > "
                f"{DIFFPAIR_SKEW_MIL:.1f} mil）"
            )
        else:
            skew_text = (
                f"长度差 {reading.skew_mil:.2f} mil ≤ 阈值 {DIFFPAIR_SKEW_MIL:.1f} mil"
            )
        layer_text = self._layer_set_text(board, reading)
        message = (
            f"差分对 {reading.group}（{label}）对内不一致："
            f"{reading.positive} {reading.positive_length_mil:.2f} mil / "
            f"{reading.negative} {reading.negative_length_mil:.2f} mil，"
            f"{skew_text}；{layer_text}。"
            "判据为屋规（200C2，可迭代）：总长差 > 5.0 mil 或两侧有效层 id 集合不同；"
            "不判阻抗、Tpd、等长组、3W 或 stub。"
        )
        evidence = [
            f"{reading.group}: 正 {reading.positive} / 负 {reading.negative}"
            f"（{reading.source}）",
            f"总 track 长度：正 {reading.positive_length_mil:.3f} mil / "
            f"负 {reading.negative_length_mil:.3f} mil，绝对差 "
            f"{reading.skew_mil:.3f} mil（阈值 {DIFFPAIR_SKEW_MIL:.1f} mil，"
            "超过才 WARN）",
        ]
        for name, table, unlayered in (
            (reading.positive, reading.positive_per_layer, reading.positive_unlayered_tracks),
            (reading.negative, reading.negative_per_layer, reading.negative_unlayered_tracks),
        ):
            per_layer = "、".join(
                f"{self._layer_name(board, layer_id)} {length:.3f} mil"
                for layer_id, length in table
            )
            evidence.append(
                f"{name} 逐层长度：{per_layer or '无'}；"
                f"未分层 track {unlayered} 段"
            )
        evidence.append(
            f"过孔数：正 {reading.positive_vias} / 负 {reading.negative_vias}"
        )
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[reading.positive, reading.negative]),
        )


class DiffPairViaParity(PcbRule):
    """One ``INFO`` per differential pair whose two sides use different via counts.

    The geometric fact 200C2 A3 asks for next to skew (§1.3): a pair routed
    ``2:1`` through vias has one side spending a transition the other does not,
    which is a stub / return-path question the *count* raises and does not
    answer. It is an ``INFO`` because the count alone is not a defect — plenty
    of pairs legitimately differ — and because the row exists to be read beside
    :class:`DiffPairSkew`'s ``WARN``, not instead of it: **both may fire for the
    same pair**, since they answer different questions.

    **The boundaries are the skew rule's** (§1.4): no pair, or a pair with no
    track on either net, produces nothing. Unlike the skew rule, an *unlayered*
    track does not silence this row — the via count does not depend on layers,
    so nothing is being inferred about the stack here.

    Silence is not a clean bill of health: no vias on either side is equal
    counts, and equal counts say nothing about **where** the vias sit or whether
    the two sides take them together.
    """

    id = DIFFPAIR_VIA_PARITY_RULE_ID
    title = "差分对过孔数不对称"
    level = "L1-pcb-geometry"
    source = "boardwise 屋规（200C2，可迭代）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        findings: list[Finding] = []
        for pair in identify_diff_pairs(board):
            reading = measure_diff_pair(board, pair)
            if not reading.measurable:
                continue
            if reading.positive_vias == reading.negative_vias:
                continue
            findings.append(self._row(board, reading))
        return findings

    def _row(self, board: BoardGeometry, reading: DiffPairReading) -> Finding:
        label = SOURCE_LABELS.get(reading.source, reading.source)
        message = (
            f"差分对 {reading.group}（{label}）两侧过孔数不等："
            f"{reading.positive} {reading.positive_vias} 个 / "
            f"{reading.negative} {reading.negative_vias} 个"
            f"（{reading.positive_vias}:{reading.negative_vias}）。"
            "本行只报计数这一几何事实（屋规 200C2，可迭代），"
            "不判过孔位置是否成对、stub 长度或阻抗；与长度差的 WARN 可并存。"
        )
        evidence = [
            f"{reading.group}: 正 {reading.positive} / 负 {reading.negative}"
            f"（{reading.source}）",
            f"过孔数：正 {reading.positive_vias} / 负 {reading.negative_vias}",
            f"总 track 长度：正 {reading.positive_length_mil:.3f} mil / "
            f"负 {reading.negative_length_mil:.3f} mil",
        ]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[reading.positive, reading.negative]),
        )
