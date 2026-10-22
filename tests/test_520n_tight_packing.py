"""520n：把岛打包**收紧到岳的密度**。

岳看了 520m 的整页（1489 × 681）之后裁定：「解耦程度远高于我，而且离得太远了」，
并给出他自己那张 `反激辅助电源` 的实测校准：

    31 件，整页 859 x 271；相邻器件最近距离 中位 43、min 24、p90 62、max 92

**并且他明说那道 ~160 的正边↔副边缝是「顺手排的，原理图没这么多规矩」——不是
安规约束。** 520m 把列间缝当隔离屏障钉成 220，那条前提就此作废。

本批把两个旋钮都收紧：岛内环距 `IslandBudget.min_pitch` 130 → 70、
`clearance` 45 → 24；岛间 `PageBudget` 120/220/40 → 40/80/20。
实测整页 1445×681 → **956×426**，area/part 6.90x 岳的 → **2.85x**。

下面钉六件事，每条都对着**实测数字**或**岳的规矩**，不是对着实现：

1. **密度**：area/part ≤ 3.0x 岳的（他 7509，我们 21435）；
2. **间距**：NN（中心距）中位 ≤ 80、NN（净空）中位 ≤ 40；
3. **读感没被收坏**：正边整体在变压器左边、副边整体在变压器右边、control 在
   primary 上方、feedback 在 bridge 上方；
4. **电学规矩没被收坏**：19 件全在页上、没有一根导线跨岛、没有短路/穿体；
5. **代价被记下来**：硬违反 ≤ 24、其中 `text-overlap` ≤ 12——收紧的代价是
   **主机自印网名行**压到别根导线上（`text-on-wire` 1 → 9），不是文字压文字
   （9 → 11）；这两条一起钉，免得以后悄悄变贵；
6. **那道缝不再是硬约束**：`PageBudget.barrier` 不许被调回隔离屏障的量级。

**为什么用上限而不是等值**：这些是**预算型**看护（同 `test_116` 的 40 秒），
量的是"有没有变得比岳要的更松/更贵"，不是"今天恰好是这个数"。
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: 岳自己那张 `反激辅助电源`（2026-10-20 他量的）。绝对尺寸比不得——他 31 件、
#: 我们 19 件——所以这里的每一道闸比的都是**密度与间距**。
YUE_PARTS = 31
YUE_SIZE = (859.0, 271.0)
YUE_AREA_PER_PART = YUE_SIZE[0] * YUE_SIZE[1] / YUE_PARTS
YUE_NN_MEDIAN = 43.0


def _library(stem: str) -> dict[str, SymbolProfile]:
    payload = json.loads((SPECS / f"{stem}.library.json").read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


def _flyback() -> tuple[CircuitSpec, PresentationSpec, dict[str, SymbolProfile]]:
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


def _page() -> il.PackedPage:
    circuit, presentation, book = _flyback()
    return il.island_page(circuit, presentation, book)


def _p90(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]


def _nn(plan, book: dict[str, SymbolProfile]) -> dict[str, dict[str, float]]:
    """min/median/p90/max of each part's nearest neighbour, centre and edge."""
    import statistics
    from boardwise.core.symbolprofile import pose_box

    origins = [(part.part_id, part.x, part.y) for part in plan.parts]
    boxes = {
        part.part_id: pose_box(book[part.symbol_ref].body, rotation=part.rotation,
                               mirror=part.mirror, ox=part.x, oy=part.y)
        for part in plan.parts
    }
    out: dict[str, dict[str, float]] = {}
    for kind in ("centre", "edge"):
        values: list[float] = []
        for name, x, y in origins:
            if kind == "centre":
                values.append(min(
                    ((x - ox) ** 2 + (y - oy) ** 2) ** 0.5
                    for other, ox, oy in origins if other != name
                ))
                continue
            here = boxes[name]
            if here is None:
                continue
            gaps = []
            for other, _ox, _oy in origins:
                there = boxes[other]
                if other == name or there is None:
                    continue
                dx = max(here[0] - there[2], there[0] - here[2], 0.0)
                dy = max(here[1] - there[3], there[1] - here[3], 0.0)
                gaps.append((dx * dx + dy * dy) ** 0.5)
            if gaps:
                values.append(min(gaps))
        out[kind] = {
            "min": min(values), "median": statistics.median(values),
            "p90": _p90(values), "max": max(values),
        }
    return out


# ------------------------------------------------------------------ 1. density


def test_the_page_is_at_岳s_density_not_half_again_as_large():
    """整页密度 ≤ 3.0x 岳的（area/part）。

    520m 是 **6.90x**（整页 1445×681，area/part 51789）。他自己的是 7509。
    这条量的是"每个器件平均占多少面积"，所以 19 件对 31 件不影响它。
    """
    page = _page()
    box = page.bbox()
    area_per_part = (box[2] - box[0]) * (box[3] - box[1]) / len(page.plan().parts)
    ratio = area_per_part / YUE_AREA_PER_PART
    assert ratio <= 3.0, (
        f"the page is {ratio:.2f}x 岳's density (area/part {area_per_part:.0f} vs "
        f"his {YUE_AREA_PER_PART:.0f}); 520n got it to 2.85x and 520m was 6.90x — "
        "loosening past 3.0x is the thing 岳 ruled against"
    )


def test_the_parts_are_as_close_together_as_岳s():
    """相邻器件间距：中心距中位 ≤ 80、净空中位 ≤ 40（岳的中位 43）。

    **两种读法都量**，因为岳给的 43 是哪一种由他说："centre" 是器件原点之间
    （原理图文件里唯一直接存着的量），"edge" 是两个器件外框之间的空白。收紧后
    实测 centre 中位 78 / edge 中位 35；520m 是 103 / 55。
    """
    circuit, presentation, book = _flyback()
    plan = _page().plan()
    stats = _nn(plan, book)
    assert stats["centre"]["median"] <= 80.0, (
        f"centre-to-centre NN median is {stats['centre']['median']:.0f}, over the "
        f"80 budget (岳's sheet is {YUE_NN_MEDIAN:g}; 520m measured 103)"
    )
    assert stats["edge"]["median"] <= 40.0, (
        f"edge-to-edge NN median is {stats['edge']['median']:.0f}, over the 40 "
        f"budget (岳's sheet is {YUE_NN_MEDIAN:g}; 520m measured 55)"
    )


# ------------------------------------------------------------------- 2. 读感


def test_the_tightening_did_not_break_the_reading():
    """正边左 / 变压器中 / 副边右，control 在 primary 上、feedback 在 bridge 上。

    收紧最容易踩的就是这个：块一近，`bbox` 就可能互相插进去，而"整体在左边"
    这句话当场不成立。四条都按**实测坐标**量。
    """
    page = _page()
    box = {block.island_id: block.bbox() for block in page.blocks}
    assert box["primary"][2] < box["bridge"][0]
    assert box["bridge"][2] < box["secondary"][0]
    assert box["control"][1] > box["primary"][3]
    assert box["feedback"][1] > box["bridge"][3]


def test_the_tightening_did_not_break_the_electrical_rules():
    """19 件全在页上；没有一根导线跨岛；没有短路、没有穿体。

    收紧改变了导线之间的间距，短路是这一批最该盯的失败模式（520m 试过两处
    收紧都被回退，都是因为它们换来一条 `undeclared-junction`）。
    """
    circuit, presentation, book = _flyback()
    page = _page()
    plan = page.plan()
    assert {part.part_id for part in plan.parts} == set(circuit.part_ids())

    ends = {
        block.island_id: {
            point for segment in block.segments for point in segment.points
        }
        for block in page.blocks
    }
    for name, points in ends.items():
        for other, other_points in ends.items():
            if other != name:
                assert not (points & other_points)

    checked = rb.check(plan, circuit, presentation, book)
    kinds = collections.Counter(item.kind for item in checked.hard_violations)
    assert kinds["undeclared-junction"] == 0, (
        "the tightening produced a short — two nets joined by a wire vertex"
    )
    assert kinds["wire-through-body"] == 0
    assert kinds["netlist-partition-mismatch"] == 0


# ------------------------------------------------------------------- 3. 代价


def test_the_cost_of_the_tightening_is_recorded_and_bounded():
    """硬违反 ≤ 24，其中 `text-overlap` ≤ 12；半截网一条都不剩。

    收紧的代价实测**不是**文字压文字（9 → 11），而是**主机自印的网名行压到别根
    导线上**（`text-on-wire` 1 → 9，147 的 `_named_wire_rows`：每根导线中点一行
    网名）。两件事都钉住——只钉 text-overlap 会让真正的代价悄悄溜走。

    **530A 之后这条是上界，不是目标**（523 DESIGN §9.2：这个"代价预算"降级为
    「不得回归」，目标提成零违反，那是 530F 的活）。530A 实测 **13** 条
    = 5 `text-overlap` + 8 `text-on-wire` + **0** `required-pin-not-connected`：
    地/电源的跨岛名从标签改成旗标（S-16）之后，`secondary` 那一坨拥挤跟着走了，
    而最后两条电气违反由岳的 2026-10-20 裁定消掉——单脚网 `GATE`/`VFB_NF`
    **挂名 + lint**，不再当悬空脚判废（落地见
    `test_520m_island_page.py::test_the_two_nets_whose_other_end_is_not_in_the_spec_are_named_not_refused`）。
    """
    circuit, presentation, book = _flyback()
    plan = _page().plan()
    checked = rb.check(plan, circuit, presentation, book)
    kinds = collections.Counter(item.kind for item in checked.hard_violations)
    total = len(checked.hard_violations)
    assert total <= 24, (
        f"{total} hard violations after the tightening (520m was 12, 520n "
        f"measured 22, 530A measures 13); kinds {dict(kinds)} — past 24 the density "
        "is buying more than it is worth"
    )
    assert kinds["text-overlap"] <= 12, (
        f"text-overlap is {kinds['text-overlap']} (520m was 9, 520n measured 11, "
        "530A measures 5)"
    )
    assert kinds["text-on-wire"] <= 10, (
        f"text-on-wire is {kinds['text-on-wire']} (520m was 1, 520n measured 9, "
        "530A measures 8) — this is the tightening's real price: the host's own "
        "wire names landing on neighbouring conductors"
    )
    assert not [
        item for item in checked.hard_violations
        if item.kind == "required-pin-not-connected"
    ], (
        "the two nets whose other end is the UC3845 are named now (岳 2026-10-20), "
        "so no pin is left unconnected and this reading must stay empty"
    )


def test_the_barrier_is_no_longer_a_hard_seam():
    """列间缝不许回到"隔离屏障"的量级——岳说那是他的习惯，不是规矩。

    「正边↔副边之间那道 ~160 的缝他明说：**顺手排的，原理图没这么多规矩**，
    不是安规约束」。520m 把它当硬约束钉成 220，实测为此白付了 area/part
    6.90x → 4.91x 的代价（把 220 收成 80 而岛内不动，硬违反一条没多）。
    """
    budget = il.PageBudget()
    assert budget.barrier <= 100.0, (
        f"PageBudget.barrier is {budget.barrier:g} — 岳 ruled that the gap between "
        "正边 and 副边 is where his hand happened to put it, not an isolation rule; "
        "a seam wider than 100 is that 220 again"
    )
    assert budget.barrier >= budget.channel, (
        "the column seam still has to be at least a channel, or two clusters stop "
        "reading as two clusters"
    )
