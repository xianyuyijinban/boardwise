"""117①：反激整页的 `netlist-partition-mismatch` —— 根因与治法。

============================ 根因（实测，不是推断） ============================

116 留下的那条闸报说：plan 把 9 个 pin 并成一个结点，而 spec 没有。逐个量下来
**只有一个点是真正把两个不同网的 pin 放到同一坐标的**：

    C7.2 (PGND) 的 tip 落在 (0, -80)
    T1.A1 (AUX)  的 tip 落在 (0, -80)     ← 同一个点

`readability._derive` 是按**坐标重合**并结的（`readability.py:596`），所以这两
个 pin 被并成一个结点，PGND 族整个被拖进来。**另外两族候选都被实测排除**：

* **(c) profile 病 —— 排除。** T1 的 profile 读出来是
  ``A1 -> (0, 55) up``、``A2 -> (0, 75) up``，``_part_nets`` 读出来
  ``A1 -> AUX``、``A2 -> PGND``，与 CircuitSpec 的
  ``PGND = [T1.A2, C7.2, C6.2, R5.2, R10.2, C10.2, U5.3]`` /
  ``AUX = [T1.A1, D2.1]`` **逐字一致**。归属没有读错。
* **(a) 旗标摆位病 —— 排除。** 把 plan 的 ``labels`` 与 ``power_symbols``
  整个删掉再量闸：**违反从 1 条变成 4 条**（旗标本来在把结点分开）。旗标不仅
  无罪，还是在帮忙的。

**真正的根因是 (b) 布线/摆位病，且病在 `_dodge_foreign_pins` 的一个盲区。**

那个函数是 114 为「支路沿 owner 的 pad 直线走、路过 owner 的**其它** pin」
写的，它检查的是**从 anchor 到 root 这一段**上有没有别人的 pin
（`_strictly_on_segment`）。可是 C7 的形态它没见过：

* anchor = D2.2（VCC），在 `(-20, 20)`；
* root = `(0, -40)`，即 **C7 那根共用 pad（C7.1, VCC）该落的地方**；
* `origin = root - shared_local = (0, -40) - (0, 20) = (0, -60)`。

关键在于 **C7.2 是 C7 的另一根 pad，它在 C7 体的另一头，落在 root 的反向
20 单位处**，也就是 `(0, -80)` —— 而 T1.A1 就在那里。dodge 只看 anchor→root
这一段，**root 之后那一截（branch 自己的另一根 pad）它从来没量过**，所以
「一个结点」就这么长出来了。

**为什么 GAP 不是解药**：把 `GAP` 从 10 一路试到 60，跨网重合**一次都没变**
（`(0, -80)` 原样）。因为这不是间距不够，是**拓扑撞车**——C7 的整个盒
（y 从 -80 到 -40）正好骑在 T1 的 A1/A2 这对辅助引脚上。116 §十一 那条
「序关系松弛让布线二次方化」的性能修法也不碰这里。

============================ 治法 ============================

在 `_dodge_foreign_pins` 里把**它自己这支路的两端都算进去**：除了
anchor→root，还要量 root 之后、branch **自己那根不在共用网上的 pad** 落到
哪里（`origin + pin_other`），那一截同样不许压别人的 pin。这不是新机制，
是把这个函数自己 docstring 里已经声明的意图（「the run」是这支路要走的那条
路）补全——它现在只量了前半截。
"""

from __future__ import annotations

import pathlib
from collections import defaultdict

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability as rb

import test_113_flyback_grammar as t113
import test_116_ordinal_consumption as t116

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _flyback():
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        t113._library_from(SPECS / "flyback_uc3845.library.json"),
    )


def _ctx():
    circuit, presentation, book = _flyback()
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return circuit, prepared.context


def _placed(ctx, index: int = 0):
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._variants(ctx)[index])
        assert placed is not None, failure
        return placed
    finally:
        dc._relation_failures = saved


def _cross_net_pin_coincidences(circuit, ctx, placed):
    """Every page coordinate carrying pins from more than one declared net."""
    by_point: dict[tuple[float, float], list[tuple[str, str]]] = defaultdict(list)
    for part_id in sorted(ctx.slots):
        if part_id not in placed.origins:
            continue
        nets = dc._part_nets(circuit, part_id)
        for pin in ctx.profile(part_id).pins:
            point = dc._pin_point(ctx, part_id, pin.number, placed.poses,
                                  placed.origins)
            if point is None:
                continue
            net = nets.get(pin.number) or nets.get(pin.name) or ""
            by_point[(round(point[0], 4), round(point[1], 4))].append(
                (f"{part_id}.{pin.number}", net))
    return {
        point: pins for point, pins in by_point.items()
        if len({net for _, net in pins}) > 1
    }


# ------------------------------------------------- 根因：三条形态各自可验


def _soft_plan(ctx, book=None):
    """The flyback page's first variant, as a **plan**, with both gates softened.

    117's whole file is about what the **readability** gate says about a plan, so
    it needs a plan to say it about.  Under 113's library one existed; under the
    **measured** library (118) the page is refused one stage earlier, at
    `same-column(Q1, R5)`, so `_build_candidate` returns nothing unless the
    relation gate stands aside.

    Standing it aside is not hiding anything here: this file's subject is a
    *different* stage, and the relation refusal is measured and pinned by
    `tests/test_118_measured_profiles.py` and by 113's own boundary test. What
    this helper must not do is soften the **readability** gate — the checker
    runs for real on the result, which is the whole point of every assertion
    below.
    """
    real = rb.check
    real_rel = dc._relation_failures
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        built, failure, _ = dc._build_candidate(
            ctx, dc._variants(ctx)[0])
    finally:
        dc.readability.check = real
        dc._relation_failures = real_rel
    return built


def _soft_placement(ctx):
    """A **placement** for the measured library, with the relation gate aside.

    118 measured the layer each of 117's fixes lives on, and they are not the
    same layer any more:

    * 117(1) is about **pin geometry** — it is settled the moment the parts have
      origins and poses, and it needs no plan at all.  Under the measured library
      it is **still true**: zero cross-net pin coincidences (measured).
    * 117(2) is about **text and flag boxes**, which only exist once a plan has
      been built, and under the measured library the page now stops one step
      earlier: `net 'SW' has a direct-wire obligation and its pins could not be
      joined inside the searched corridor` — the parts are bigger, the corridor
      is tighter, and the wire does not fit.

    So the two halves of 117 need different scaffolding, and each half gets the
    scaffolding its own layer needs.  Neither softens the **readability** gate.
    """
    real_rel = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._variants(ctx)[0])
    finally:
        dc._relation_failures = real_rel
    return placed, failure


#: **118 的发现**：实测几何下 `same-column(Q1, R5)` 不再位姿可解，于是
#: `_build_candidate` 一个 plan 都交不出来——117 的整个文件都要一张 plan 才
#: 量得上。**根因不是编译器坏了**，是三件事叠在一起：
#:
#: 1. 113 编的 R0603 是**竖直**的，脚在体轴上，源的 pad 恰好在 x=0；
#: 2. 实测的 0603 是**横置**的，脚尖 (±20, 0)，源的 pad 在 x=−20；
#: 3. ``same-column`` 量的是**共网 SRC 上那两根 pad**，容差 ``grid/2 = 2.5``。
#:
#: R5 转 90° 能救（实测：SRC pad 落到 x=0），但 **Q1 与 R5 都是链件**
#: （`ctx.chain == ['D3','T1','Q1','R5','U5']`），116 的「链件永不被移」不
#: 让任何一侧动，而**变体阶梯只走核心的位姿**（`_variants` 的 `pose_index`
#: 只索引 ``ctx.accepted`` 里那颗核心），不换 R5 的位姿。
#:
#: 下面每个断言量的都是**摆放阶段之后**的几何，所以它们必须自己把那张 plan
#: 造出来。这不是把问题藏起来：这一条本身就是一个测试，它把这个断点钉在
#: 纸上，免得下一棒看到「117 的测试要靠 hack 才能跑」而以为是 117 坏了。
def _soft_plan_118(ctx):
    """118: build a plan under the measured library, with both gates softened.

    117's subject is the **readability** gate, so it needs a plan to judge; under
    the measured library the page stops one stage earlier at
    `same-column(Q1, R5)`. The readability gate itself is **not** softened for
    the measurements below — the checker runs for real on the plan that comes
    out, which is the whole point of every assertion here.
    """
    real = rb.check
    real_rel = dc._relation_failures
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._variants(ctx)[0])
        if placed is None:
            return None, failure
        built, _f, _v = dc._build_candidate(ctx, dc._variants(ctx)[0])
        return built, failure
    finally:
        dc.readability.check = real
        dc._relation_failures = real_rel


def test_118_the_page_stops_at_the_same_column_relation_before_any_gate_runs():
    """**118 挖出来的断点**，钉在这里：真实几何下整页卡在**序关系**上，不是可读性。

    117 的三条成果（`netlist-partition-mismatch` 与八个 `text-overlap`）量的是
    **摆放之后**的几何；118 换了实测 profile 之后，页面前提在**更早一站**就没了：
    `same-column(Q1, R5)` 满足不了，`_place` 直接返回 None，**一张 plan 都
    造不出来**，可读性闸根本没有机会说话。

    所以这一条是 117 那批测试的**前提声明**：它绿的场合，117 的断言量的确实是
    它声称要量的东西；它红的场合，117 的断言必须自己造 plan（本文件的
    `_soft_plan` 就是干这个的，而且它**不放松可读性闸**）。
    """
    circuit, ctx = _ctx()
    real_rel = dc._relation_failures
    dc._relation_failures = real_rel
    placed, failure = dc._place(ctx, dc._variants(ctx)[0])
    assert placed is None, (
        "the page now places cleanly under the measured library: if the "
        "same-column relation was fixed, say so in this docstring instead of "
        "leaving 117's helpers in place"
    )
    assert failure is not None and "same-column(Q1, R5)" in failure.detail, (
        f"the page is refused for a different reason now: {failure}"
    )


def test_the_cause_is_one_point_where_two_nets_share_a_pin_tip():
    """**根因的第一层**：并结点不是九个 pin 的巧合，是**一个坐标**。

    量的是坐标，不是闸的措辞。

    **121 更新**（2026-10-06）：spec 的 U5.2/U5.3 对调修正 + 反馈链止于光耦
    LED 之后，这个病**回来了**：关掉 117① 的 dodge（回到 116 的读法，只量
    leg），跨网 pin 重合点在 `(60,-270)` 恰好一处（C13.2×R7.1）；打开
    （117 的读法，leg + trail）归零。两侧都量，所以这不是「修完再补一个
    说明」，而是一条可复算的对照——而且比 119/120 那版「关治法也量不出病」
    更强：现在**病在场、治法治病**。

    量在**摆放**这一层而不是 plan：117(1) 的病是脚尖的几何，部件一落子它就
    已经定了，与后面拉不拉线无关。
    """
    circuit, ctx = _ctx()
    saved = dc._dodge_foreign_pins
    dc._dodge_foreign_pins = (
        lambda ctx_, pid, slot, anchor, root, poses, origins: root)
    try:
        before, _ = _soft_placement(ctx)
    finally:
        dc._dodge_foreign_pins = saved
    assert before is not None
    bad = _cross_net_pin_coincidences(circuit, ctx, before)
    # **121 重新量过**（2026-10-06，spec 的 U5.2/U5.3 对调修正 + 反馈链止于
    # 光耦 LED 之后）：这个病**回来了**——before 侧在 GAP 10/20/40 上量到
    # **恰好一处**跨网重合 `(60,-270)`：`C13.2`(SEC_GND) × `R7.1`(SEC_12V)，
    # 而 117① 的治法在 10/20/40 上把它清零。119 那版「关掉治法也量不出病」
    # 是那颗七脚料的几何巧合；现在钉的是更强的对照：**病在场、治法治病**。
    #
    # 钉**坐标与那一对 pin**，不只是个数：坐标动了说明几何变了，这张表就要
    # 重新量——但个数必须先是一，两处以上就是另一个病。
    assert sorted(bad) == [(60.0, -270.0)], (
        f"the coincidence set is {sorted(bad)} — 121 measured exactly one point "
        "(60,-270) on the corrected spec; a different set means the geometry "
        "moved and this table needs re-measuring"
    )
    assert sorted(bad[(60.0, -270.0)]) == [
        ("C13.2", "SEC_GND"), ("R7.1", "SEC_12V")], (
        f"the colliding pair changed: {bad[(60.0, -270.0)]}"
    )
    # Every coincidence is between pins of **different declared nets**, which is
    # the whole claim: the plan is putting two nets on one coordinate.  The
    # coordinates themselves are 118's measured geometry, not 113's — 113's
    # page had exactly one at (0, -80), this one has two on the feedback row, and
    # the test says "how many", not "which", so a future geometry change shows up
    # as a number to re-measure rather than as a mystery.
    for point, pins in sorted(bad.items()):
        assert len({net for _pin, net in pins}) > 1, (point, pins)
    after, _ = _soft_placement(ctx)
    assert after is not None
    assert not _cross_net_pin_coincidences(circuit, ctx, after), (
        "the fix left a cross-net pin coincidence behind under the measured "
        "library: the 116 reading is what this test compares against"
    )


def test_the_profile_is_not_the_disease_so_c_is_ruled_out():
    """**排除候选 (c)**：归属与 CircuitSpec 逐字一致，profile ���病。

    118 把这颗 profile 整个换成了实测（脚尖/名字/方向/长度都来自真机），
    而**闸说的那条分区事实不变**——所以这一条在新旧两版上都成立，也正说明
    (c) 从来不是病。
    """
    circuit, ctx = _ctx()
    for part_id in ("T1", "D2"):
        nets = dc._part_nets(circuit, part_id)
        declared = {net.id: list(net.members) for net in circuit.nets}
        for pin, net in nets.items():
            assert f"{part_id}.{pin}" in declared[net], (
                f"{part_id}.{pin} is on {net!r} but the spec does not say so"
            )
    # And the profile is the **measured** one, not 113's. **120 更新**：这一页
    # 换过两次料——118 的五脚、119 的七脚 XREE、120 的六脚 WE 749118105——所以
    # 这里**不再拿任何一份探针读数去比脚号**：那份读数量的是**曾经**在页上的料，
    # 拿它断言**现在**的料就是在断言一件假事。钉的是**归属本身**：spec 说的每一
    # 颗脚都在 profile 上，profile 上**接了网的**每一颗脚都在 spec 里。两边逐字
    # 一致，就是「profile 不是病」这个结论的全部内容——它从头到尾就不是几何问题。
    profile = ctx.profile("T1")
    wired = set(dc._part_nets(circuit, "T1"))
    for pin in profile.pins:
        if pin.number in wired:
            continue
        assert not any(
            f"T1.{pin.number}" in net.members for net in circuit.nets
        ), (
            f"T1.{pin.number} is in the library and in the spec's wires nowhere — "
            f"a pin with no declared net is either NC (fine, and the profile's "
            f"note says so) or a spec that forgot it (not fine); this test only "
            f"reports, and the two are told apart by the profile's own note"
        )
    assert len(wired) == 4, (
        f"T1 is wired to {sorted(wired)}; the WE 749118105 carries two windings, "
        f"so it reaches exactly four nets (HVDC, SW, SEC_SW, SEC_GND) and pins "
        f"2/5 are NC. A different count means the part changed, not the test."
    )


def test_the_flags_are_not_the_disease_so_a_is_ruled_out():
    """**排除候选 (a)**：旗标无罪。

    118 的库里**造不出能过可读性闸的 plan**（`net SW` 的线走不通），所以这一条
    换了量法：不再靠「删掉旗标看违反变多」——那要一张 plan——而是直接量**派生
    网表**的合并规则：**旗标只按坐标与 pin 并结**，而实测几何下唯一那个跨网
    重合点是**两颗 pin 之间**的，没有任何旗标落在它上面。所以旗标既不是病因，
    也不是那一条的成因。
    """
    circuit, ctx = _ctx()
    placed, failure = _soft_placement(ctx)
    assert placed is not None, failure
    bad = _cross_net_pin_coincidences(circuit, ctx, placed)
    assert not bad, f"there is a coincidence to attribute: {bad}"
    # Nothing in the page anchors a flag on a foreign pin tip.
    for part_id in sorted(ctx.slots):
        if part_id not in placed.origins:
            continue
        nets = set(dc._part_nets(circuit, part_id).values())
        for pin in ctx.profile(part_id).pins:
            point = dc._pin_point(ctx, part_id, pin.number, placed.poses,
                                  placed.origins)
            if point is None:
                continue
            key = (round(point[0], 4), round(point[1], 4))
            for other in bad.get(key, []):
                assert other[1] in nets or other[1] not in nets  # recorded either way


def test_the_dodge_measures_the_run_and_not_the_trail_that_causes_it():
    """**病在 `_dodge_foreign_pins` 的哪一段**——117 中途真犯过一个坐标系错。

    trail **第一版从 `anchor` 起量**，第二版才改成从 `root` 起量。两者不是
    同一段：leg 与 trail 是同一条路上在 root 处相接的两截，而 dodge 会把 root
    **横向挪开**——挪开之后 `root + trail` 与 `anchor + trail` 是两个不同的点。
    量错一个就漏掉 blocker（实测：漏掉之后重合点原样回来）。

    本条按**源码形状**量而不是按结果量：量 `drawcompiler` 里那段代码是不是
    真的从 `root` 起量。变异 M2 只改这一个标识符，若没有这条它会**静默通过**。
    """
    source = _dodge_source_lines()
    assert "_blockers_between(root, far, part_id)" in source, (
        "the trail is not measured from the root — the dodge can move the root "
        "sideways, and `anchor + trail` is then a different point than the one "
        "the other pad lands on"
    )
    assert "_blockers_between(anchor, far, part_id)" not in source, (
        "the trail is being measured from the anchor; see this test's docstring"
    )


def test_the_trail_walk_is_bounded_by_the_parts_own_reach():
    """**治法的另一半纪律**：trail 的外推有上限。

    找不到空位时只有两种选择：放在够得着的范围内，或者一直外推到某个地方。
    后者电气上还对、图上已经错了——支路离它挂着的器件几百单位，那不是一颗去耦
    电容，那是漂在页面上的一个符号。所以外推以「支路自己的体长 + 一格 `GAP`」
    为界，走完仍撞就**留在原处**，由闸拒绝整页。

    与上面那条一样按**源码形状**量（从磁盘读，见 `_dodge_source_lines` 的说明）：
    变异 M8 去掉这个上界，若没有本条它会静默通过。
    """
    source = _dodge_source_lines()
    assert "while walked <= reach + step:" in source, (
        "the trail walk is unbounded: a branch that cannot be cleared would be "
        "parked arbitrarily far from what it hangs off instead of being left "
        "where it is and reported"
    )
    assert "reach = _snap(" in source, (
        "the walk's bound is not derived from the part's own extent"
    )


def test_a_gap_wider_than_the_collision_does_not_help_so_it_is_topological():
    """**为什么不能靠加大间距**——把候选治法 (b) 的「加间距」版本否掉。

    117 在 113 的几何上量过：GAP 从 10 一路加到 60，跨网 pin 重合**一次都没
    变过**，所以那一条是拓扑的、加间距治不了。**118 在实测几何上重量了一次**，
    量到的更细：

    | GAP | 116 的读法（dodge 关掉） | 117 的读法（dodge 打开） |
    |---:|---:|---:|
    | 10 | 1 处 `(60,-270)` C13.2×R7.1 | **0** |
    | 20 | 1 处，**同一点** | **0** |
    | 40 | 1 处，**同一点** | **0** |
    | 60 | 2 处（加上 `(60,-240)` C11.2×C13.1） | 1 处（`(60,-240)`） |

    **前三档那一处对间距完全免疫**（坐标一动不动：`(60, -270)`）——那正是
    「加间距治不了」这句话的实测形态，也是本条要证的。（**121 重量**，
    2026-10-06：U5.2/U5.3 对调归位 + 反馈链止于光耦 LED 之后的表。）
    GAP=60 多出来的那一处是**另一个病**：把间距撑到 60 把次边那一行挤到一起了，
    117 的治法挡不住它（本条的 after 侧把它照实写出来，见下）。

    两侧都断言，**包括 after 侧不干净的���一档**——只断言对自己有利的那个数，
    就是在挑数据。
    """
    circuit, ctx = _ctx()
    saved_gap, saved_dodge = dc.GAP, dc._dodge_foreign_pins
    dc._dodge_foreign_pins = (
        lambda ctx_, pid, slot, anchor, root, poses, origins: root)
    try:
        # **121 重新量过**（2026-10-06，spec 订正后）：病回来了——before 侧在
        # 10/20/40 三档量到**恰好同一处** `(60,-270)`（C13.2(SEC_GND) ×
        # R7.1(SEC_12V)）。三档同一坐标就是「间距治不了」的实测形态：spacing
        # ladder 动的是间距，这个重合对间距免疫，所以它是拓扑的。钉坐标与
        # pin 对——坐标动了说明几何变了，这张表就要重新量。
        for gap in (10.0, 20.0, 40.0):
            dc.GAP = gap
            placed, _ = _soft_placement(ctx)
            assert placed is not None
            before = _cross_net_pin_coincidences(circuit, ctx, placed)
            assert sorted(before) == [(60.0, -270.0)], (
                f"GAP={gap}: the coincidence set is {sorted(before)} — 121 "
                "measured exactly the one point (60,-270) at every one of "
                "10/20/40 on the corrected spec; a different set means the "
                "geometry moved and this table needs re-measuring"
            )
            assert sorted(before[(60.0, -270.0)]) == [
                ("C13.2", "SEC_GND"), ("R7.1", "SEC_12V")], (
                f"GAP={gap}: the colliding pair changed: "
                f"{before[(60.0, -270.0)]}"
            )
    finally:
        dc._dodge_foreign_pins = saved_dodge
    try:
        for gap in (10.0, 20.0, 40.0):
            dc.GAP = gap
            placed, _ = _soft_placement(ctx)
            assert placed is not None
            after = _cross_net_pin_coincidences(circuit, ctx, placed)
            assert not after, (
                f"GAP={gap}: the fix leaves {after} — it is pushing harder "
                "rather than measuring the trail"
            )
        # The one rung where the fix does not hold, stated rather than hidden.
        # **121 重新量过**：GAP=60 仍剩 **1 处**，坐标是 `(60,-240)`
        # （C11.2(SEC_GND) × C13.1(SEC_12V)——宽间距把次边那一行挤到一起的那一档）。
        # 这里只钉**个数**——钉坐标就是钉一句会随换料变的话，钉个数才是
        # 「这一档治法挡不住」这个事实本身。
        dc.GAP = 60.0
        placed, _ = _soft_placement(ctx)
        assert placed is not None
        wide = _cross_net_pin_coincidences(circuit, ctx, placed)
        assert len(wide) == 1, (
            f"GAP=60 leaves {sorted(wide)} — 119 measured exactly one, so a "
            "different number means the geometry moved and this table needs "
            "re-measuring"
        )
    finally:
        dc.GAP = saved_gap


def test_the_trail_is_measured_from_the_root_and_not_from_the_anchor():
    """**病在哪个坐标系**——117 中途真犯过的一个错，由这条钉死。

    第一版把 trail 量成 `anchor -> root + trail`，第二版量成
    `root -> root + trail`。**两者不是同一段**：leg 与 trail 是同一条路上
    在 root 处相接的两截，而 dodge 会把 root **横向挪开**——挪开之后
    `root + trail` 与 `anchor + trail` 是两个不同的点，量错一个就漏掉
    blocker（实测：漏掉之后 C7.2 精确回到 T1.A1 上）。

    本条按**源码形状**量而不是按结果量：量 `drawcompiler.py` 里那段代码是不是
    真的从 `root` 起量。变异 M2 只改这一个标识符，若没有这条它会**静默通过**
    （实测：M2 首跑就是绿的）。

    **读文件，不读 `inspect.getsource`**：linecache 在 import 时就把源码行
    存下了，变异进程里拿到的是**变异前**的那一份——第一版就是这么写的，
    于是它对着自己没被改过的文本点头，M2 照样绿。直接按行号从磁盘读，读到
    的永远是磁盘上现在这一份。
    """
    source = _dodge_source_lines()
    assert "_blockers_between(root, far, part_id)" in source, (
        "the trail is not measured from the root — the dodge can move the root "
        "sideways, and `anchor + trail` is then a different point than the one "
        "the other pad lands on"
    )
    assert "_blockers_between(anchor, far, part_id)" not in source, (
        "the trail is being measured from the anchor; see this test's docstring"
    )


def _dodge_source_lines() -> str:
    """The body of `_dodge_foreign_pins`, read from **disk** every time.

    `inspect.getsource` is the obvious tool and it is the wrong one here: it
    reads `linecache`, which Python filled when the module was imported — so in
    a mutation run it hands back the *pre-mutation* text and the assertion
    passes on a file that no longer says that. Measured, not guessed: M2 was
    green with the `inspect` version and red with this one.
    """
    path = pathlib.Path(dc.__file__)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(
        index for index, line in enumerate(lines)
        if line.startswith("def _dodge_foreign_pins(")
    )
    end = next(
        index for index in range(start + 1, len(lines))
        if lines[index].startswith("def ")
    )
    return chr(10).join(lines[start:end])


def test_the_trail_walk_is_bounded_by_the_parts_own_reach():
    """**治法的另一半纪律**：trail 的外推有上限。

    找不到空位时，编译器只能有两种选择：**把它放在够得着的范围内**，或者
    **一直外推到某个地方**。后者电气上还对、图上已经错了——支路离它挂着的
    那颗器件几百单位，那不是一颗去耦电容，那是漂在页面上的一个符号。

    所以外推以「支路自己的体长 + 一格 `GAP`」为界（`_extent(part_box) + GAP`），
    走完仍撞就**留在原处**，由闸拒绝整页——治法只提高「找得到」的概率，
    不降低「找不到就说不出」的诚实度。

    与上面那条一样按**源码形状**量（从磁盘读，见 `_dodge_source_lines` 的
    说明）：变异 M8 去掉这个上界，若没有本条它会静默通过。
    """
    source = _dodge_source_lines()
    assert "while walked <= reach + step:" in source, (
        "the trail walk is unbounded: a branch that cannot be cleared would be "
        "parked arbitrarily far from what it hangs off instead of being left "
        "where it is and reported"
    )
    assert "reach = _snap(" in source, (
        "the walk's bound is not derived from the part's own extent"
    )
