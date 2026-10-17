"""192A-1：底层器件的封装局部坐标要翻转（``ComponentPlacement.transform``）。

**洞**：``transform`` 只做了一次 CCW 旋转，``layer_id == 2``（贴在底面）的器件
封装局部坐标从未翻转 —— 底层器件的每一只焊盘都落在「没翻转的那一面」的位置上。
底层的走线/过孔是按**真实**位置画的，所以这不是一个看不出来的偏差：探针
``.tmp_hole_1/probe_pad3.py`` 以「同网铜端点落在焊盘中心」为独立 oracle，毕设FOC
底层 U4/U6 的 24 只可见焊盘里，现状 **0** 只落在同网铜端点上，翻转后 **11** 只。

**oracle 为什么是独立的**：同网走线/过孔是宿主自己画的铜，与我们的 parser 无关；
一只焊盘的中心应当落在它自己那条网的铜上，这是布线的定义，不是我们对文件的猜测。

**翻的是哪个轴、在旋转前还是旋转后，是量出来的**（任务书给的 ``mirror_x ∘ CCW``
只是**待核对**的候选）。以全部 epro2 夹具的底层焊盘对拍「不翻转／局部 y 翻转／
旋转后镜像 x」三种读法，独立 oracle 给出：局部 y 翻转在**每一只焊盘上都不更差**
（端点命中 54→69，逐焊盘无一失手；净空余量 −4049.5 mil → +2731.3 mil，62 只两种
读法位置不同的焊盘里 31 只支持它、**0** 只支持不翻转），而 ``mirror_x ∘ CCW`` 反而
比不翻转更差（49 命中、16 只焊盘变坏）。所以本文件钉的是**局部 y 翻转**这条读法。

**这条测试钉的是不变量，不是某个数**：逐板比较「不翻转（旧行为）」与「本代码」的
命中数，本代码在任何一块板、任何一个 PCB 文档上都不许更差，全库合计必须严格更好，
且没有任何一只焊盘是「不翻转更好」。
"""

from __future__ import annotations

import math
from pathlib import Path

from boardwise.core.geometry import BoardGeometry, Point
from boardwise.parsers.epru import extract_board, load_epro2_source

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: 焊盘中心落在同网铜端点上算「命中」的半径（mil）。铜端点与焊盘中心本来就不是
#: 同一个数（端点画到焊盘边缘也合法），5 mil 只用来把「同一面」和「另一面」分开：
#: 两种读法的差是封装宽度的两倍，量级在几十到几百 mil。
HIT_MIL = 5.0
#: 两种读法给出**不同**点的焊盘才带信息（``local_y == 0`` 时局部 y 翻转是恒等）。
DIFFER_MIL = 0.001


def _boards() -> list[tuple[str, BoardGeometry]]:
    """One entry per **PCB document**, named ``<file>#<doc index>``.

    Per document, not :func:`build_board_geometry`'s single one: a backup may
    hold several boards and the defect is visible on whichever carries the
    flipped parts (毕设FOC's 2026-09-17 backup has three — the two-component one,
    the 4-layer one and a 291-record stub — and the bottom parts U4/U6 live on
    the second).
    """
    out: list[tuple[str, BoardGeometry]] = []
    for path in sorted(FIXTURES.glob("*.epro2")):
        source = load_epro2_source(path)
        for index, document in enumerate(source.documents_of_type("PCB")):
            board = extract_board(
                document, source.footprints(), source.stats, source.footprint_artwork()
            )
            out.append((f"{path.name}#{index}", board))
    return out


def _bottom_pads(board: BoardGeometry):
    """``(pad, comp)`` for every bottom-face pad the two readings place differently."""
    by_id = {comp.id: comp for comp in board.components}
    for pad in board.pads:
        comp = by_id.get(pad.component_id)
        if comp is None or comp.layer_id != 2 or not pad.net:
            continue
        if pad.local_x is None or abs(pad.local_y) <= DIFFER_MIL:
            continue
        yield pad, comp


def _nearest_same_net_copper(board: BoardGeometry, net: str, x: float, y: float) -> float:
    """Distance from ``(x, y)`` to the closest endpoint of ``net``'s copper."""
    best = math.inf
    for track in board.tracks:
        if track.net != net:
            continue
        for point in (track.start, track.end):
            best = min(best, math.hypot(point.x - x, point.y - y))
    for via in board.vias:
        if via.net != net:
            continue
        best = min(best, math.hypot(via.x - x, via.y - y))
    return best


def _segment_distance(px: float, py: float, track) -> float:
    """Distance from a point to a track's **body**, not just its endpoints."""
    dx = track.end.x - track.start.x
    dy = track.end.y - track.start.y
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - track.start.x, py - track.start.y)
    t = max(0.0, min(1.0, ((px - track.start.x) * dx + (py - track.start.y) * dy)
                           / (dx * dx + dy * dy)))
    return math.hypot(px - (track.start.x + t * dx), py - (track.start.y + t * dy))


def _copper_margin(board: BoardGeometry, net: str, x: float, y: float) -> float:
    """``d(other net) - d(own net)`` in mil: positive means the pad sits on its own net.

    The second, sharper oracle. A landing radius only says "there is a vertex
    near here"; the margin says **which** net the point is closest to, which is
    the property a pad position has to satisfy and the one a wrong reading
    violates hardest — measured, the unflipped reading's pads sit on average
    65 mil *closer to another net's copper than to their own*.
    """
    same = math.inf
    other = math.inf
    for track in board.tracks:
        distance = _segment_distance(x, y, track)
        if track.net == net:
            same = min(same, distance)
        elif track.net:
            other = min(other, distance)
    for via in board.vias:
        distance = math.hypot(via.x - x, via.y - y)
        if via.net == net:
            same = min(same, distance)
        elif via.net:
            other = min(other, distance)
    return other - same


def _unflipped(comp, local_x: float, local_y: float) -> Point:
    """The 192A-1 defect, kept here as the control: rotate only, never flip."""
    a = math.radians(comp.angle)
    return Point(
        comp.x + local_x * math.cos(a) - local_y * math.sin(a),
        comp.y + local_x * math.sin(a) + local_y * math.cos(a),
    )


def _count_hits(board: BoardGeometry) -> tuple[int, int]:
    """``(hits_now, hits_as_is)`` over the bottom pads of ``board``."""
    now = as_is = 0
    for pad, comp in _bottom_pads(board):
        if _nearest_same_net_copper(board, pad.net, pad.x, pad.y) <= HIT_MIL:
            now += 1
        control = _unflipped(comp, pad.local_x, pad.local_y)
        if _nearest_same_net_copper(board, pad.net, control.x, control.y) <= HIT_MIL:
            as_is += 1
    return now, as_is


def test_bottom_pad_flip_never_loses_a_same_net_landing() -> None:
    """Every fixture: the flip may only add same-net landings, never lose one."""
    worse: list[str] = []
    for name, board in _boards():
        now, as_is = _count_hits(board)
        if now < as_is:
            worse.append(f"{name}: now={now} unflipped={as_is}")
    assert not worse, "翻转之后同网命中反而变少：" + "; ".join(worse)


def test_bottom_pad_flip_lands_where_the_copper_says() -> None:
    """And the flip really is in effect: some board must gain a landing."""
    total_now = total_as_is = 0
    for _name, board in _boards():
        now, as_is = _count_hits(board)
        total_now += now
        total_as_is += as_is
    assert total_now > total_as_is, (
        f"翻转没有生效：全库命中 不翻转={total_as_is} 本代码={total_now}"
    )


def test_no_pad_is_closer_to_its_own_net_without_the_flip() -> None:
    """The sharper oracle: the unflipped reading must not win a single pad.

    Measured on these fixtures: of the pads the two readings place differently,
    31 prefer the flip and **0** prefer the unflipped one, and the summed margin
    goes from negative to positive. A future change that swaps the axis or the
    order (say back to ``mirror_x ∘ CCW``, which scores *worse* than doing
    nothing) trips this line before it can hide behind a landing count.
    """
    better_now = better_control = 0
    total_now = total_control = 0.0
    for _name, board in _boards():
        for pad, comp in _bottom_pads(board):
            control = _unflipped(comp, pad.local_x, pad.local_y)
            margin_now = _copper_margin(board, pad.net, pad.x, pad.y)
            margin_control = _copper_margin(board, pad.net, control.x, control.y)
            if not (math.isfinite(margin_now) or math.isfinite(margin_control)):
                continue
            total_now += margin_now
            total_control += margin_control
            if margin_now > margin_control + 0.5:
                better_now += 1
            elif margin_control > margin_now + 0.5:
                better_control += 1
    assert better_control == 0, f"{better_control} 只焊盘在不翻转时离自己的网更近"
    assert better_now > 0, "翻转一只焊盘都没救回来，读法没生效"
    assert total_now > total_control, (
        f"全库净空余量没有变好：不翻转={total_control:.1f} 本代码={total_now:.1f}"
    )

