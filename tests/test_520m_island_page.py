"""520m：五个岛打包进整页，并接进 `compile`。

本批两件事，各有各的"不变"要钉：

1. **打包**（`islandlayout.pack_islands`）：五个 `IslandBlock` 只被
   `translated()` 整块挪动，岛间留通道。位置由 **role** 决定
   （`primary` 左 / `bridge` 中 / `secondary` 右 / `control` 在 primary 上方 /
   `feedback` 在 bridge 上方），下面按**实测坐标**逐条量：左在左、右在右、
   上在上，且**任意两岛的 bbox 不相交**。
2. **接线**（`drawcompiler.compile` 第 5 步的一处 guard）：声明了多个岛的
   presentation 走岛路（`_try_island_variants`），其余一律走原路。
   这里的"不变"是本批最硬的一条：**不写 `islands` 的 spec 编译输出逐字节相同**
   ——`ch340_serial` / `power_entry_xt30` 的 `draw compile` 结果（json / log /
   page.json / SVG）都在 `evidence/520m/` 里 A/B 过；测试里钉的是它的**结构性
   理由**：`effective_islands()` 对不写 `islands` 的文档返回**一个**隐式岛，而
   页面编译器的模块视图**不携带** `islands`（`pagecompiler._module_view`），
   所以那两条路都到不了岛路。

**为什么 `required-pin-not-connected` 从 178 掉到 2**：岛级图上每个岛只有自己的
器件，闸按整页电路去问"每个网的每只脚接上了吗"，于是别的岛的 178 只脚全报缺件。
打包之后 19 件全在同一页，只剩两条网真的没有第二只脚——`GATE`(`Q1.1`) 与
`VFB_NF`(`R10.1`)，它们的那一头是**不在 spec 里**的 UC3845。这两条是岳要裁的
口径，不是打包没缝上。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.islands import IMPLICIT_ISLAND_ID
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _library(stem: str) -> dict[str, SymbolProfile]:
    """The library sidecar through the real reader — `SymbolProfile.from_dict`."""
    payload = json.loads(
        (SPECS / f"{stem}.library.json").read_text(encoding="utf-8")
    )
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


# --------------------------------------------------------------- the packing


def _fingerprint(block: il.IslandBlock) -> list[float]:
    """Every coordinate a block draws, in a fixed order, as plain floats.

    A fingerprint rather than a JSON comparison because the way back
    (`translated(-dx, -dy)`) is a floating-point round trip: `+285` then `-285`
    gives `70.4322094240838` where the original had `70.43220942408377`.  The
    invariant being tested is "nothing was recomputed", not "IEEE addition is
    associative", so the numbers are compared to ``1e-9`` and the *shape* (which
    objects are there, in which order, with which fields) is compared exactly.
    """
    out: list[float] = []
    for part in sorted(block.parts, key=lambda item: item.part_id):
        out.extend([part.x, part.y, part.rotation, float(part.mirror)])
    for segment in block.segments:
        out.append(len(segment.points))
        for point in segment.points:
            out.extend(point)
    for label in block.labels:
        out.extend([label.x, label.y, *label.bbox])
    for text in block.texts:
        out.extend([*text.bbox])
    for junction in block.junctions:
        out.extend([junction.x, junction.y])
    return out


def test_the_packed_page_is_five_rigid_blocks_and_nothing_was_recomputed():
    """打包只挪整块：每岛的内部几何与它单独布局时**一样**（到 1e-9）。

    这是"刚体块"的定义，也是 520m 唯一被允许做的事。做法是把每个块按偏移的逆
    挪回来，再和自己单独布局的那一块比指纹。
    """
    circuit, presentation, book = _flyback()
    alone = {
        block.island_id: block
        for block in il.island_blocks(circuit, presentation, book)
    }
    page = _page()
    assert len(page.blocks) == 5
    for block in page.blocks:
        dx, dy = page.offsets[block.island_id]
        back = block.translated(-dx, -dy)
        original = alone[block.island_id]
        assert _fingerprint(back) == pytest.approx(
            _fingerprint(original), abs=1e-9
        ), (
            f"{block.island_id} changed inside the packing — the packer may only "
            "translate a block, never recompute one"
        )
        assert [part.part_id for part in back.parts] == [
            part.part_id for part in original.parts
        ]


def test_the_page_reads_primary_left_bridge_middle_secondary_right():
    """岳的规矩，按**实测坐标**量，不按槽位表量。

    三列各自完全在自己的 x 区间里；`control` 整个在 `primary` 之上、
    `feedback` 整个在 `bridge` 之上。这四条一起说"正边左 / 变压器中 / 副边右"
    这句话在几何上成立。
    """
    page = _page()
    box = {block.island_id: block.bbox() for block in page.blocks}

    assert box["primary"][2] < box["bridge"][0], (
        f"primary's extent {box['primary']} is not wholly left of bridge's "
        f"{box['bridge']}"
    )
    assert box["bridge"][2] < box["secondary"][0], (
        f"bridge's extent {box['bridge']} is not wholly left of secondary's "
        f"{box['secondary']}"
    )
    assert box["control"][1] > box["primary"][3], (
        "control is not wholly above primary — 岳 asked for it near primary"
    )
    assert box["feedback"][1] > box["bridge"][3], (
        "feedback is not wholly above bridge — 岳 asked for it near U5, and U5 "
        "is the upper of the bridge's two parts"
    )


def test_no_two_island_blocks_overlap_on_the_page():
    """任意两岛的 bbox 不相交——通道是真的留出来了，不是恰好错开。"""
    page = _page()
    boxes = [(block.island_id, block.bbox()) for block in page.blocks]
    for index, (name, first) in enumerate(boxes):
        for other_name, second in boxes[index + 1:]:
            assert not (
                first[0] < second[2] and second[0] < first[2]
                and first[1] < second[3] and second[1] < first[3]
            ), f"{name} {first} overlaps {other_name} {second}"


def test_every_circuit_part_is_on_the_page_and_no_wire_joins_two_islands():
    """19 件全在页上；没有一根导线跨岛（岳：岛间不画任何跨线）。"""
    circuit, presentation, book = _flyback()
    page = _page()
    plan = page.plan()

    placed = {part.part_id for part in plan.parts}
    assert placed == set(circuit.part_ids()), (
        "the packed page must hold every part of the circuit — that is what "
        "makes the per-island 'part is not placed' findings go away"
    )

    ends = {
        block.island_id: {
            point for segment in block.segments for point in segment.points
        }
        for block in page.blocks
    }
    for name, points in ends.items():
        for other, other_points in ends.items():
            if other == name:
                continue
            shared = {point for point in points if point in other_points}
            assert not shared, (
                f"islands {name} and {other} share the wire point(s) {shared} — "
                "the two islands are joined by a conductor, which 岳's rule "
                "forbids (the jump is a name, not a wire)"
            )


# ------------------------------------------------------------------- the gate


def test_the_two_nets_whose_other_end_is_not_in_the_spec_are_named_not_refused():
    """整页闸：岛级那 178 条"别的岛的器件不在这张图上"全没了，剩下的一条也不是它。

    `GATE`(`Q1.1`) 与 `VFB_NF`(`R10.1`) 这两条网在全电路里**各只有一只脚**，
    另一头是不在 `.circuit.json` 里的 UC3845。520m/520n 把这件事记成"两条
    `required-pin-not-connected`，要岳裁"——**岳 2026-10-20 裁了**：挂名 + lint，
    不判废（`evidence/523/DESIGN.md` §7.3/§14.1，先例是 board-A 的 `NRST`）。

    所以 530A 之后这条测试量的是裁决的**落地**，不再是那个悬着的问题：

    * 闸里 `required-pin-not-connected` **一条都没有**（悬空脚不再是这张图的读数）；
    * 两条网各有一个**同名标签**挂在它们那只脚上（`plan.labels`）；
    * 岛上记了 `island-single-name` 这条 lint，口径写在纸上而不是藏在代码里。

    这条**必须**和 520l 的岛级读数一起看：岛级 `required-pin-not-connected`
    是 178，打包后是 2，530A 之后是 0——差别全在这三行。
    """
    circuit, presentation, book = _flyback()
    page = _page()
    plan = page.plan()
    checked = rb.check(plan, circuit, presentation, book)
    pin = [
        item for item in checked.hard_violations
        if item.kind == "required-pin-not-connected"
    ]
    assert not pin, (
        "a one-pin net is named now, so nothing is left unconnected: "
        + "; ".join(item.render() for item in pin)
    )
    named = sorted(label.text for label in plan.labels)
    assert "GATE" in named and "VFB_NF" in named, (
        f"the two half-nets must be named at their own pin, got {named}"
    )
    lint = [note for note in plan.notes if "island-single-name" in note]
    assert len(lint) == 2, (
        f"each one-pin net owes one lint; got {lint}"
    )
    assert not [
        item for item in checked.hard_violations
        if item.kind == "netlist-partition-mismatch"
    ], (
        "a crossing net's partition does not match — the same-name labels in "
        "each island are what is supposed to join them"
    )


# ------------------------------------------------------- the compile wiring


def test_a_presentation_without_islands_gets_one_implicit_island():
    """不写 `islands` 的文档对外是**一个**岛——所以 guard 对它恒等。

    这是"单岛路径不许动"的**结构性**理由，不是"这两个 spec 恰好没事"：
    guard 比的是 `len(effective_islands()) > 1`，而 `effective_islands()` 对
    不写这个键的文档返回 :func:`implicit_island`（一个，装下全部）。
    """
    for stem in ("ch340_serial", "power_entry_xt30"):
        presentation = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        islands = presentation.effective_islands()
        assert len(islands) == 1, f"{stem} states no islands yet reports {islands}"
        assert islands[0].id == IMPLICIT_ISLAND_ID
        assert len(islands[0].parts) == len(presentation.declared_part_ids())


def test_the_page_compilers_module_view_never_carries_islands():
    """页面编译器的模块视图不携带 `islands`，所以页路到不了岛路。

    `_module_view` 是**过滤**出来的一份 presentation：它给的是模块自己那一组
    器件与网。若它把整页的 `islands` 抄过去，每个模块都会看到一个"多岛"文档，
    guard 当场在页路里点火——那是本批最危险的失败模式。这里直接量它。
    """
    from boardwise.engines import pagecompiler

    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json"
    )
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    assert len(presentation.effective_islands()) > 1, (
        "the fixture must be a multi-island document or this test proves nothing"
    )
    _sub_circuit, sub_presentation = pagecompiler._module_view(
        circuit, presentation, presentation.modules[0]
    )
    assert sub_presentation.islands is None
    assert len(sub_presentation.effective_islands()) == 1


def test_the_flyback_takes_the_island_path_and_says_so():
    """反激走岛路：`result.notes` 里有点名的页号，且**只有一个页**被建出来。

    这条同时钉住 guard 的方向：如果 `> 1` 被改成永不成立，`result.notes` 里就
    没有 `boardwise-island-page/1`，这里当场红。

    **530F 重钉**：岛路建出来的是**一个页**，而这一页的判决在 530F 之后从
    「被拒」变成**交付**（交付口径见 `drawcompiler.ISLAND_GATE_TOLERATED_LIMITS`
    与 `tests/test_530f_gate_tolerance.py`）。所以这里量的是「只有一个页」这件
    事的**两种**形态：交付时是 1 个 candidate 且 0 条拒绝，被拒时是 0 个 candidate
    且 1 条拒绝——**「7 个 variant」永远不成立**，那才是这条测试的题材。
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(circuit, presentation, book)
    notes = " ".join(result.notes)
    assert "boardwise-island-page/1" in notes, (
        "the flyback did not take the island path — the guard at compile's step 5 "
        f"did not fire; notes were {result.notes}"
    )
    assert len(result.candidates) + len(result.rejected) == 1, (
        "the island path builds exactly one page — one candidate or one refusal, "
        "never a ladder of variants — got candidates "
        f"{len(result.candidates)} and rejected "
        f"{[item.variant for item in result.rejected]}"
    )
    if result.candidates:
        # 530F: delivered.  The page's own account travels with it.
        plan = result.candidates[0]
        assert "island page" in " ".join(plan.evidence.notes), (
            "a delivered island page's own evidence must say which page it is"
        )
        assert not result.rejected, "a delivered page was not refused"
    else:
        assert len(result.rejected) == 1 and "island-page" in result.rejected[0].variant
        assert result.failures, (
            "a page that was refused must say why (053 sec.4)"
        )


def test_a_single_island_document_is_untouched_by_the_island_path():
    """单岛的整页编译：输出与接线前**逐字节相同**的那一条，在代码里钉住它的形状。

    `evidence/520m/` 里有 A/B 的 sha256（json / log / page.json / SVG 全同）。
    测试不能去读 `evidence/`，所以这里钉的是等价的、可重复的东西：同一次编译
    跑两遍给出同一份 candidate 摘要，且**没有**任何岛页的痕迹。
    """
    presentation = PresentationSpec.load(SPECS / "ch340_serial.presentation.json")
    circuit = CircuitSpec.load(SPECS / "ch340_serial.circuit.json")
    book = _library("ch340_serial")
    first = dc.compile(circuit, presentation, book)
    second = dc.compile(circuit, presentation, book)
    assert "boardwise-island-page/1" not in " ".join(first.notes)
    assert [item.plan.geometry_sha256() for item in first.ranked] == [
        item.plan.geometry_sha256() for item in second.ranked
    ]
