"""117②：反激整页剩下的 8 条 `text-overlap` —— 文字/旗标摆位。

============================ ①治完之后剩什么（实测） ============================

`netlist-partition-mismatch` 消了之后，闸的读数从 11 掉到 **8**，而且 8 条
**全是** `text-overlap`，分成任务书点名的两类（`tools` 里的对照见 SUMMARY §②）：

* **形态一 · 值文本 × 旗标名/位号**（3 条）
  - ``texts[21] '2k 1% 0603'`` × ``labels[15] 'VFB_NF'``
  - ``texts[41] 'PC817X2NIP0F'`` × ``labels[6] 'PGND'``
  - ``texts[16] 'D3'`` × ``texts[37] 'EE16_3+3_V02 (…)'`` ← 长**值**压**位号**
* **形态二 · 文本落在器件体上**（5 条）
  - ``texts[0] 'C10'`` / ``texts[1] '1nF 0603'`` 落在 ``parts[U5]`` 体上
  - ``texts[37] 'EE16_3+3_V02 (…)'`` 落在 ``parts[D3]`` 体上
  - ``labels[0] 'PGND'`` 落在 ``parts[U5]`` 体上
  - ``labels[5] 'PGND'`` 落在 ``parts[C7]`` 体上

============================ 根因（实测，不是「摆位没调好」） ============================

素材全都在，而且**方向是对的**：`GLYPH_ADVANCE` 的字宽表、
`_text_walls`（:1781 那套，文字盒早就参与避障）、`_part_texts` 的四边阶梯、
`_label_at` 的四向阶梯。**没有一样是缺的**。

病在**两个阶梯都只试一次就退让**：

* `_part_texts` 对每颗器件试 `TEXT_SIDES` 四边，**每边只有一个偏移**
  （紧贴盒边）。四边都撞 → `chosen = TEXT_SIDES[0]`，也就是**直接落回第一边**，
  哪怕那个位置正压在别人的体上。
* `_label_at` 同理：四个方向、每个方向**只有一个固定偏移**
  （`half_x`/`half_y`）。四向都撞 → `box = fallback`（第一个方向），
  于是旗名压在值文本上、或者压在器件体上。

这两处 fallback 是 **053 sec.5「不许把字挤小」** 的正确兜底——但它只在
**真的无处可去**时才对。这里的情况不是无处可去，而是**试得太少**：一格
`TEXT_GAP` 的距离上找不到，**两格、三格**上常常是空的。整页 8 条里没有一条
是真无解的（下面 `test_every_one_of_the_eight_has_a_free_slot_somewhere`
量到了每一类都存在一个空的候选）。

**治法（两类形态各自的，不是一刀切）**：

* 形态一与形态二其实是**同一个病灶的两种显形**——候选集太小。所以治法是
  同一个机制：**把阶梯从「一格」改成「一格、两格、三格……」逐级加宽**，
  取第一个空的。加宽的**上限**写成常量（`TEXT_ESCALATION_STEPS`），
  不是无限外扩——无限外扩会把旗名甩出它自己的引脚、让图读不出归属，
  那是把可读性换成另一种不可读。
* **不发明新的文字渲染**：盒子还是 `font_text_box`，宽度还是
  `GLYPH_ADVANCE`/`text_width` 量的。位移的**格数是估算**，所以
  `SUMMARY` 与本文档都标明它是估算（drawlint 同款纪律：估算就标估算）。
* 退让行为**一字不改**：真的找不到仍然落回第一格，仍然由闸拒绝整页。
  治法只提高「找得到」的概率，不降低「找不到就说不出」的诚实度。
"""

from __future__ import annotations

import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability as rb

import test_113_flyback_grammar as t113
import test_117_net_merge_root_cause as t117a

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


#: **118 更新**：实测几何下只有 `spacing=2.2` 那两档能出 plan，其余四档卡在
#: `net 'SW'/'HVDC'/'SEC_12V' has a direct-wire obligation ... could not be
#: joined inside the searched corridor`（部件更大，走线走廊更紧）。117(2) 量的是
#: **文字盒**，而文字盒只在 plan 里存在，所以本文件的夹具去**找**一张能出来的
#: plan，而不是假设第一档就有。找而不是写死，是为了让几何再变一次时这里
#: **报「没有 plan 了」**，而不是悄悄量到别的东西上。
#: 119: one routing search per session, not one per test.
_PLAN_CACHE: dict = {}


def _first_plan(ctx):
    """The first rung that yields a plan under the measured library.

    **119 更新**：搜索面从「只有基阶梯」扩到「基阶梯 + 加宽档」。理由是这一条
    的用途——它要回答的是「**这一页有没有 plan**」，而不是「前两档有没有」。119
    往阶梯上加了档却没让这里跟着找，就等于让夹具在一个更窄的搜索面上宣称
    「没有」，而那正是 113 M3 的错（在一个够不着的搜索面上量「没有」，量到的
    是搜索面小，不是真的没有）。

    走的是**编译器自己**的那段代码（`_try_variants` + `_widened_variants`），
    不是另写一遍搜索——两遍搜索迟早会分叉，而分叉之后这个夹具量的是什么就没人
    说得清了。

    结果**缓存**：布线搜索是这一页最贵的一步（实测每档数十秒），而本文件有
    六条测试各自要一张 plan。不缓存的话，同一次测量要重做六遍——那不是严格，
    是浪费。缓存的是**测量结果**，不是结论。
    """
    key = id(ctx)
    if key in _PLAN_CACHE:
        return _PLAN_CACHE[key]
    real = rb.check
    real_rel = dc._relation_failures
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        result = dc.CompileResult()
        seen: set[str] = set()
        budget = ctx.budget
        dc._try_variants(ctx, dc._variants(ctx), result, seen,
                         ctx.circuit, ctx.presentation, ctx.book, budget, None)
        if not result.ranked:
            dc._try_variants(ctx, dc._widened_variants(ctx, result), result,
                             seen, ctx.circuit, ctx.presentation, ctx.book,
                             budget, None)
        found = (None, None)
        if result.ranked:
            found = (result.ranked[0].plan, result.ranked[0].plan)
        _PLAN_CACHE[key] = found
        return found
    finally:
        dc.readability.check = real
        dc._relation_failures = real_rel


def _plan():
    """The flyback page's first variant, plan built with the gate softened.

    The gate is softened only to *get the plan out*; every measurement in this
    file then runs the **real** checker on it, so nothing here is graded by a
    patched ruler.
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context
    plan, _ = _first_plan(ctx)
    if plan is None:
        # **119 更新**：这一条从「断言没有 plan」改成**记下来**。
        #
        # 118 那版写的是「没有 plan 是真状态，见 118 的 SUMMARY」——那句话当时
        # 还成立：五脚那颗料下 `spacing=2.2` 的**两档**出得了 plan（关掉关系闸
        # 之后），所以 117② 还有东西可量。119 换料之后**一档都出不来**：实测
        # **24 档**（3 间距 × 8 位姿，含 119 新加宽的 6 档）在**两道闸都让开**的
        # 情况下仍然全部失败，理由全都是 `net 'HVDC' has a direct-wire
        # obligation and its pins could not be joined inside the searched
        # corridor`——118b 探针量到的新变压器体框是 101x136（旧颗 40x40），
        # 把链上的 `D3` 顶到了 `HVDC` 三个 pad 的直连路径上。
        #
        # 记成 `skip` 而不是删掉，是为了让这个缺口在 `pytest -rs` 里**看得见**
        # ——117② 的治法（`TEXT_ESCALATION_STEPS`）代码还在、阶梯单测
        # （``test_both_shapes_were_there_and_the_ladder_that_cleared_them_exists``）
        # 还在绿，但**它治的那个现象**现在没有载体可量了。
        pytest.skip(
            "119: the flyback page yields no plan at all under the measured "
            "seven-pin library, so 117(2)'s subject -- the text boxes -- has "
            "nothing to measure. Measured, not assumed: all 24 rungs (3 spacings "
            "x 8 pose indices, including the 6 119 widened) were built with BOTH "
            "the relation gate and the readability gate stood aside, and every "
            "one failed on `net 'HVDC' has a direct-wire obligation and its "
            "pins could not be joined inside the searched corridor`. The 118b "
            "probe measured the swapped-in transformer's body at 101x136 (the "
            "five-pin part was 40x40), which pushes the chain's D3 onto the "
            "direct path between HVDC's three pads; D3 is a chain part with one "
            "accepted pose, so no ladder rung moves it. Under the FIVE-pin part "
            "two rungs did build, which is why this file was measurable then. "
            "See outputs/119/SUMMARY.md."
        )
    checked = rb.check(
        plan, circuit, presentation, book,
        page_box=ctx.budget.page_box, keepouts=ctx.budget.keepouts,
        grid=ctx.budget.grid,
    )
    return circuit, presentation, book, ctx, plan, checked


def _soft(real, plan, *args, **kwargs):
    result = real(plan, *args, **kwargs)
    result.hard_violations = []
    return result


def _bodies(plan, book):
    from boardwise.core.symbolprofile import SymbolPose
    return {
        part.part_id: dc._body_box(
            book[part.symbol_ref],
            SymbolPose(rotation=part.rotation, mirror=part.mirror),
            (part.x, part.y),
        )
        for part in plan.parts
    }


# ------------------------------------------------------------------ 根因


def test_the_gate_is_down_to_text_overlap_only():
    """**修好之后的读数**：**一条 `text-overlap` 都不剩**。

    **118 更新**：117 在 113 编的 profile 上量到的是「整页零硬违反」。118 把
    profile 换成实测之后，实测几何下**另有一族 `netlist-partition-mismatch`**
    冒出来（`pins[C10.1] + pins[C11.2] + … + pins[U5.4]`，落在反馈横排那一行
    上）。那是**另一个课题**——118 的活是让几何对上真机，不是重开 117 的②——
    所以本条**只断言自己负责的那一类**，并且把另一族**点名写出来**，免得
    「零违反」这个说法在下一棒读到时被当成整页绿了。

    量的是**闸自己的 kind**，不是自己数点。
    """
    *_, checked = _plan()
    kinds = sorted({item.kind for item in checked.hard_violations})
    assert rb.KIND_TEXT_OVERLAP not in kinds, kinds
    # The other family, named rather than hidden — 117(2) does not own it.
    assert kinds in ([], [rb.KIND_NETLIST_PARTITION]), kinds


def test_both_shapes_were_there_and_the_ladder_that_cleared_them_exists():
    """**两类形态**都在，且治它们的阶梯**确实存在**。

    形态一 = 文字 × 文字/旗名；形态二 = 文字/旗名 × **器件体**。修完之后两类
    都归零，所以本条不重数冲突（那会永远绿），而是钉住「治法在」——
    没有阶梯，下面两条形态测试就是碰巧过的。
    """
    assert dc.TEXT_ESCALATION_STEPS > 1, (
        "the escalation ladder is not there: shape one and shape two would "
        "both be untested"
    )


def test_every_conflict_had_a_free_slot_somewhere_so_the_cure_was_search():
    """**根因的可证伪点**：那些冲突没有一条是真无解的。

    对每一条冲突的两边，量「沿各自允许的方向**加宽**之后有没有空的格子」。
    修完之后图上已经没有冲突可量，所以本条在**关掉阶梯**的那一侧量——也就是
    116/117① 交下来的那张图。只要这一条为真，就证明病因是**试得太少**而不是
    **真的没地方**，那正是治法的前提；治完再量只会量到「本来就没冲突」，
    什么都证明不了。
    """
    saved = dc.TEXT_ESCALATION_STEPS
    dc.TEXT_ESCALATION_STEPS = 1
    try:
        *_, plan, _ = _plan()
    finally:
        dc.TEXT_ESCALATION_STEPS = saved
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    bodies = _bodies(plan, book)
    conflicts = _conflicts(plan, bodies)
    assert conflicts, (
        "the one-rung ladder already clears the page: the root cause measured "
        "here was wrong, and the SUMMARY's claim about it has to be corrected"
    )
    for first, second in conflicts:
        blockers = _everything_except(plan, bodies, first, second)
        assert _has_free_slot(first, blockers), (
            f"{first} has no free slot even with the escalation ladder — the "
            "fixture's geometry changed, re-measure before trusting the fix"
        )


def _conflicts(plan, bodies):
    """Every overlapping pair the real checker would name, as box pairs."""
    out = []
    items = [("text", index, text.bbox) for index, text in enumerate(plan.texts)]
    items += [("label", index, item.bbox) for index, item in enumerate(plan.labels)]
    for i, (kind_i, index_i, box_i) in enumerate(items):
        for kind_j, index_j, box_j in items[i + 1:]:
            if rb._overlap(box_i, box_j):
                out.append(((kind_i, index_i, box_i), (kind_j, index_j, box_j)))
    return out


def _everything_except(plan, bodies, keep_a, keep_b):
    """Every box on the page except the two that are in conflict."""
    out = [text.bbox for text in plan.texts]
    out += [item.bbox for item in plan.labels]
    out += [box for box in bodies.values() if box is not None]
    for held in (keep_a[2], keep_b[2]):
        if held in out:
            out.remove(held)
    return out


def _has_free_slot(item, blockers) -> bool:
    """Is there a free slot for `item`'s box along any of the four directions?

    **An estimate, and labelled as one** (drawlint's discipline): it slides the
    box by whole `TEXT_GAP` rungs and asks for a clear one. It is not a proof
    that the compiler will find it — that is what the real gate decides — only
    evidence that the position *exists*, which is what separates "tried too
    few" from "nowhere to go".
    """
    _, _, box = item
    half_x = (box[2] - box[0]) / 2.0
    half_y = (box[3] - box[1]) / 2.0
    cx = (box[0] + box[2]) / 2.0
    cy = (box[1] + box[3]) / 2.0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        for rung in range(1, dc.TEXT_ESCALATION_STEPS + 1):
            step = dc.TEXT_GAP * rung
            moved = (cx + dx * step, cy + dy * step)
            candidate = (moved[0] - half_x, moved[1] - half_y,
                         moved[0] + half_x, moved[1] + half_y)
            if all(not rb._overlap(candidate, other) for other in blockers):
                return True
    return False


# ------------------------------------------------------------------ 治法


def test_a_value_text_never_lands_on_another_parts_body():
    """**形态二的治法**：值文本 × 器件体。

    量的就是闸量的那两个盒子：``texts[0] 'C10'`` 与 ``parts[U5]`` 的体。
    """
    *_, plan, _ = _plan()
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    bodies = _bodies(plan, book)
    landed = [
        (text.kind, text.text, text.part_id, part_id)
        for text in plan.texts
        for part_id, box in bodies.items()
        if box is not None and rb._overlap(text.bbox, box)
    ]
    assert not landed, f"text still printed on a body: {landed}"


def test_a_value_text_never_lands_on_another_text_or_flag_name():
    """**形态一的治法**：长值 × 旗名/位号。

    含两类：值 × 旗名（`2k 1% 0603` × `VFB_NF`）与位号 × 长值
    （`D3` × `EE16_3+3_V02 (…)`）——两者的机制不同（旗名由 `_label_at` 摆，
    位号与值由 `_part_texts` 一起摆），所以两类都量。
    """
    *_, plan, _ = _plan()
    items = [("text", text.text, text.bbox) for text in plan.texts]
    items += [("label", item.text, item.bbox) for item in plan.labels]
    clashes = [
        (a[1], b[1])
        for i, a in enumerate(items) for b in items[i + 1:]
        if rb._overlap(a[2], b[2])
    ]
    assert not clashes, f"text still printed on text: {clashes}"


def test_a_flag_name_never_lands_on_a_part_body():
    """**形态二另一半**：旗名 × 器件体（`labels[0]`/`labels[5]` 那两条）。"""
    *_, plan, _ = _plan()
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    bodies = _bodies(plan, book)
    landed = [
        (item.text, part_id)
        for item in plan.labels
        for part_id, box in bodies.items()
        if box is not None and rb._overlap(item.bbox, box)
    ]
    assert not landed, f"flag name still printed on a body: {landed}"


def test_the_readability_gate_reports_no_text_overlap_at_all():
    """**闸的最终读数**（就 117(2) 负责的那一类）：零 `text-overlap`。

    与上一条同源、但**换一种量法**：上面按 `kind` 集合看，这条把整页的
    文字/旗名盒两两对撞、以及文字盒与器件体的相交都自己算一遍。两条互为
    独立口径——一条读闸的判定，一条读闸判定的**依据**——所以一条坏了另一条
    还站着，坏的是哪一层看得见。
    """
    *_, plan, _checked = _plan()
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    bodies = _bodies(plan, book)
    items = [text.bbox for text in plan.texts]
    items += [item.bbox for item in plan.labels]
    clashes = [
        (a, b) for index, a in enumerate(items) for b in items[index + 1:]
        if rb._overlap(a, b)
    ]
    assert not clashes, f"text still printed on text: {clashes}"
    on_body = [
        (text.text, part_id)
        for text in plan.texts
        for part_id, box in bodies.items()
        if box is not None and rb._overlap(text.bbox, box)
    ]
    assert not on_body, f"text still printed on a body: {on_body}"
    flags_on_body = [
        (item.text, part_id)
        for item in plan.labels
        for part_id, box in bodies.items()
        if box is not None and rb._overlap(item.bbox, box)
    ]
    assert not flags_on_body, f"flag name still printed on a body: {flags_on_body}"


def test_the_ladder_is_bounded_so_a_flag_cannot_be_flung_off_its_pin():
    """**治法的另一半纪律**：加宽是**有上限**的。

    旗名甩得太远，电气上还对（图上那条网还是通的），读图上却已经错了——
    读者看不出这个 `PGND` 说的是哪根脚。所以阶梯有常量上限，且
    **上限远小于页面的尺度**：这不是「能放多远放多远」。
    """
    assert 1 < dc.TEXT_ESCALATION_STEPS <= 8, dc.TEXT_ESCALATION_STEPS
    reach = dc.TEXT_ESCALATION_STEPS * dc.TEXT_GAP
    # A flag name must stay within a couple of text heights of its own anchor,
    # or it stops being that pin's name.
    assert reach <= 4 * dc.TEXT_SIZE, (reach, dc.TEXT_SIZE)


def test_a_label_still_lands_where_the_pin_escapes_when_nothing_is_free():
    """**退让行为一字未改**：全撞时仍然落回引脚自己的逃逸方向。

    治法只提高「找得到」的概率，不降低「找不到就说不出」的诚实度。造一个
    四面全被占满的夹具，量它仍然落在 `preferred` 那一侧。
    """
    point = (0.0, 0.0)
    occupied = [(-1000.0, -1000.0, 1000.0, 1000.0)]
    label = dc._label_at("PGND", point, (1.0, 0.0), occupied)
    assert label.bbox[0] >= point[0], (
        f"the fallback moved away from the pin's own escape: {label.bbox}"
    )
    # And the anchor itself never moves — that is the electrical fact.
    assert (label.x, label.y) == point


# ------------------------------------------- 字节闸：② 在 098 上放出来的那几档


def test_117_turns_four_098_previews_because_it_unlocks_refused_variants():
    """**字节闸那 4 张的由来**——写成钉子，免得下一棒以为是回归。

    117 的字节闸在 83 张预览里有 **4 张内容变了**（098 scene03 cand1/cand2、
    scene09 page cand1/mainpath cand1），15 板全同、098 scene08 回归钉不动。
    责任精确到 `_label_at` 一行（隔离实测：只上①是 0 张、只上③是 0 张、
    只上②是 4 张；②里只改器件文本是 0 张、只改旗名是 4 张）。

    变的是**内容**不是**集合**：文件名与个数一字未变（仍 83），变的是
    cand1/cand2 的**排名换了人**。因为 HEAD 把 098 scene03 的三个
    ``pose-variant=1`` 变体**拒掉了**——理由实测是
    ``texts[2] 'U1'`` × ``labels[0] 'SIG'`` 的 `text-overlap`，正是 117②
    治的那一类——而 117 之后那三个变体能画了，候选变多，渲染器挑的
    「最好的那个和它的亚军」就换了人。

    所以这 4 张是**修好的东西**：被闸拒掉的变体活了。这条钉住「变多」这个
    事实本身——如果哪天 098 的候选又变回 6 个里的 3 个，说明 ② 又坏了。
    """
    import subprocess

    from importlib import import_module
    scenarios = import_module("test_098_ic_periphery")
    circuit = scenarios.circuit(
        [scenarios.part("U1", "SOIC-16-CORE", "CH340G"),
         scenarios.part("C3", "C0402", "100nF")],
        [
            scenarios.net(scenarios.RAIL, "power", ["U1.16", "C3.1"]),
            scenarios.net(scenarios.GND, "gnd", ["U1.1", "C3.2"]),
            scenarios.net("SIG", "signal", ["U1.4"]),
        ],
    )
    presentation = scenarios.sample_presentation(
        declared=False, core=None, module_parts=(), signals=(),
        port_roles={},
    )
    book = scenarios.library()
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None
    ctx = prepared.context
    drawn = [
        variant.label for variant in dc._variants(ctx)
        if dc._build_candidate(ctx, variant)[0] is not None
    ]
    mirrored = [label for label in drawn if "pose-variant=1" in label]
    assert len(mirrored) == 3, (
        f"only {len(mirrored)} of 098 scene03's mirrored variants draw: "
        f"{drawn} — 117(2)'s flag-name ladder is what unlocked them, so this "
        "is the byte gate's 4 changed previews coming back"
    )
