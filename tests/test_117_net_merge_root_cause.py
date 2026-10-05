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


def test_the_cause_is_one_point_where_two_nets_share_a_pin_tip():
    """**根因的第一层**：并结点不是九个 pin 的巧合，是**一个坐标**。

    量的是坐标，不是闸的措辞。这条是整件事的地基。

    **修好之后**这个坐标上已经没有任何跨网 pin 了（`{}`）——所以本条把
    「病态」与「治法」写在同一处：把 dodge 关掉（回到 116 的读法），重合点
    精确回到 `(0, -80)`，打开它就归零。**同一段代码、同一份夹具，两侧都
    量**，所以这不是「修完再补一个说明」，而是一条可复算的对照。
    """
    circuit, ctx = _ctx()
    saved = dc._dodge_foreign_pins
    # The "before" side: 116's reading, which measures only the leg.
    dc._dodge_foreign_pins = (
        lambda ctx_, pid, slot, anchor, root, poses, origins: root)
    try:
        before = _cross_net_pin_coincidences(circuit, ctx, _placed(ctx))
    finally:
        dc._dodge_foreign_pins = saved
    assert list(before) == [(0.0, -80.0)], (
        f"the root-cause shape moved: {before} — re-measure before trusting "
        "the rest of this file"
    )
    (point, pins), = before.items()
    assert {name for name, _ in pins} == {"C7.2", "T1.A1"}, pins
    # And the two are on the nets the gate named.
    assert dict(pins) == {"C7.2": "PGND", "T1.A1": "AUX"}, pins

    after = _cross_net_pin_coincidences(circuit, ctx, _placed(ctx))
    assert not after, (
        f"the fix left a cross-net coincidence behind: {after}"
    )


def test_the_profile_is_not_the_disease_so_c_is_ruled_out():
    """**排除候选 (c)**：T1 的 A1/A2 归属与 CircuitSpec 逐字一致。

    把 profile 读出来的归属和 spec 声明的并排比。两者一致 = profile 没病，
    这条测试就是防止「以后有人改 profile 而以为是修根因」。
    """
    circuit, ctx = _ctx()
    # What the compiler reads off the profile...
    read = dc._part_nets(circuit, "T1")
    assert read["A1"] == "AUX", read
    assert read["A2"] == "PGND", read
    # ...and the two profile pins are 20 apart, both leaving upward, so the
    # pair is real geometry rather than a duplicated entry.
    by_number = {pin.number: pin for pin in ctx.profile("T1").pins}
    assert by_number["A1"].direction == "up"
    assert by_number["A2"].direction == "up"
    assert by_number["A2"].tip[1] - by_number["A1"].tip[1] == 20.0
    # The spec says the same thing, in the spec's own words.
    declared = {net.id: list(net.members) for net in circuit.nets}
    assert "T1.A1" in declared["AUX"], declared["AUX"]
    assert "T1.A2" in declared["PGND"], declared["PGND"]
    assert "D2.1" in declared["AUX"]


def test_the_flags_are_not_the_disease_so_a_is_ruled_out():
    """**排除候选 (a)**：删光旗标与电源符号，违反**变多**不是变少。

    116 猜「旗标摆位病」。实测反过来了：`lbl13 'AUX'` 正好落在 (0, -80)，
    它把 `pin:T1.A1` 和 `lbl12/13` 并在一起，**反而**把 AUX 从 PGND 簇里
    拉出来一点。删掉它，剩下的段自己把更多 pin 接到一起。
    """
    import dataclasses

    circuit, presentation, book = _flyback()
    real = rb.check
    dc.readability = __import__(
        "boardwise.engines.drawcompiler", fromlist=["readability"]).readability
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    try:
        built, _, _ = dc._build_candidate(
            _ctx()[1], dc._variants(_ctx()[1])[0])
    finally:
        dc.readability.check = real
    assert built is not None
    plan = built.plan

    def partition_mismatches(this):
        checked = real(this, circuit, presentation, book,
                       page_box=_ctx()[1].budget.page_box,
                       keepouts=_ctx()[1].budget.keepouts,
                       grid=_ctx()[1].budget.grid)
        return [item for item in checked.hard_violations
                if item.kind == rb.KIND_NETLIST_PARTITION]

    with_flags = len(partition_mismatches(plan))
    without = len(partition_mismatches(
        dataclasses.replace(plan, labels=[], power_symbols=[])))
    assert without > with_flags, (
        f"removing the flags changed the mismatch count {with_flags} -> "
        f"{without}: candidate (a) is no longer ruled out, re-measure"
    )


def _soft(real, plan, *args, **kwargs):
    result = real(plan, *args, **kwargs)
    result.hard_violations = []
    return result


def test_the_dodge_measures_the_run_and_not_the_trail_that_causes_it():
    """**根因的第二层（病在 `_dodge_foreign_pins` 的盲区）**。

    这条把「病在哪一行」钉死。C7 的共用 pad 被 dodged 到 `root`，而
    `origin = root - shared_local`，**branch 自己那根不在共用网上的 pad
    （C7.2）因此落在 root 之后 `other_local - shared_local` 那一段上**——
    正是 T1.A1 所在。

    两侧都量：**dodge 关掉**时（116 的读法）C7.2 精确落在 T1.A1 上；
    **dodge 打开**时它被推开。量的三个坐标都是编译器自己的输出，不是复述。
    """
    circuit, ctx = _ctx()
    saved = dc._dodge_foreign_pins
    dc._dodge_foreign_pins = (
        lambda ctx_, pid, slot, anchor, root, poses, origins: root)
    try:
        before = _placed(ctx)
    finally:
        dc._dodge_foreign_pins = saved
    after = _placed(ctx)

    slot = ctx.slots["C7"]
    shared_local = dc._pin_local(ctx, "C7", slot.pin_shared, before.poses)
    other_local = dc._pin_local(ctx, "C7", slot.pin_other, before.poses)
    trail = (other_local[0] - shared_local[0], other_local[1] - shared_local[1])
    # The trail is a real 40-unit stretch, not a degenerate one.
    assert trail != (0.0, 0.0), trail

    # Before: the other pad's tip sits exactly on T1.A1.
    tip_before = dc._pin_point(ctx, "C7", slot.pin_other, before.poses,
                               before.origins)
    a1_before = dc._pin_point(ctx, "T1", "A1", before.poses, before.origins)
    assert tip_before == a1_before == (0.0, -80.0), (
        f"the root-cause shape moved: C7.{slot.pin_other} at {tip_before}, "
        f"T1.A1 at {a1_before}"
    )
    # After: it is off that pin.
    tip_after = dc._pin_point(ctx, "C7", slot.pin_other, after.poses,
                              after.origins)
    a1_after = dc._pin_point(ctx, "T1", "A1", after.poses, after.origins)
    assert tip_after != a1_after, (tip_after, a1_after)


def test_a_gap_wider_than_the_collision_does_not_help_so_it_is_topological():
    """**为什么不能靠加大间距**——把候选治法 (b) 的「加间距」版本否掉。

    跨网 pin 重合是**拓扑**的，不是间距的：在 116 的读法（dodge 关掉）下把
    `GAP` 从 10 一路加到 60，重合点**一次都没变过**。所以治法必须是「量到那
    后半截」，不是「把它推得更远」。

    两侧都断言：before 侧对间距免疫（本条要证的），after 侧对间距也免疫
    （治法没有偷偷退化成加间距）。
    """
    circuit, ctx = _ctx()
    saved_gap, saved_dodge = dc.GAP, dc._dodge_foreign_pins
    dc._dodge_foreign_pins = (
        lambda ctx_, pid, slot, anchor, root, poses, origins: root)
    try:
        for gap in (10.0, 20.0, 40.0, 60.0):
            dc.GAP = gap
            before = _cross_net_pin_coincidences(circuit, ctx, _placed(ctx))
            assert list(before) == [(0.0, -80.0)], (
                f"GAP={gap}: the coincidence moved to {list(before)} — it was "
                "never a spacing problem, so this guard needs re-measuring"
            )
    finally:
        dc._dodge_foreign_pins = saved_dodge
    try:
        for gap in (10.0, 20.0, 40.0, 60.0):
            dc.GAP = gap
            after = _cross_net_pin_coincidences(circuit, ctx, _placed(ctx))
            assert not after, (
                f"GAP={gap}: the fix is spacing-sensitive at {after} — it is "
                "pushing harder rather than measuring the trail"
            )
    finally:
        dc.GAP = saved_gap


# ------------------------------------------------------------------ 治法


def test_the_trail_past_the_root_carries_no_foreign_pin():
    """**治法生效**：C7 的另一根 pad 不再落在别人的 pin 上。

    治法是让 `_dodge_foreign_pins` 把 branch 自己那根不在共用网上的 pad 也
    算进「这条路」，于是它把 C7 挪开，跨网重合点归零。
    """
    circuit, ctx = _ctx()
    bad = _cross_net_pin_coincidences(circuit, ctx, _placed(ctx))
    assert not bad, (
        "the AUX hot end is still geometrically inside the PGND cluster: "
        f"{ {k: v for k, v in bad.items()} }"
    )


def test_the_readability_gate_no_longer_reports_a_partition_mismatch():
    """**闸的读数**：整条 `netlist-partition-mismatch` 消失。

    用真正的 checker（`readability.check`）量，不是自己数点。
    """
    import dataclasses

    circuit, presentation, book = _flyback()
    ctx = _ctx()[1]
    real = rb.check
    dc.readability.check = lambda plan, *a, **k: _soft(real, plan, *a, **k)
    try:
        built, _, _ = dc._build_candidate(ctx, dc._variants(ctx)[0])
    finally:
        dc.readability.check = real
    assert built is not None
    checked = real(built.plan, circuit, presentation, book,
                   page_box=ctx.budget.page_box, keepouts=ctx.budget.keepouts,
                   grid=ctx.budget.grid)
    kinds = sorted({item.kind for item in checked.hard_violations})
    assert rb.KIND_NETLIST_PARTITION not in kinds, kinds


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
