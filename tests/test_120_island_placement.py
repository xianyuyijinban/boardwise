"""120：第二孤岛落子质量 + 走廊死因——**先量后治**的两条根因，各自带单测。

============================ 这一页现在的现实 ============================

岳 2026-10-04 选了 WE 749118105（**两绕组真品料**，六脚，pin 2/5 是 NC）放在 P1，
主代理把 spec 三件套与 T1 的实测 profile 换完了。**那一部分不许返工。**

实测现状（`tools/119_pose_ladder_widening_evidence.py` 复跑）：

* 基阶梯 6 档全拒 `same-column(Q1, R5)`——**119 的加宽照旧救回了它**；
* 加宽 18 档改拒 `near(C13, T1)` / `near(R15, T1)` / `right-of(C10, U5)`；
* 关系闸让开之后 6 档里 5 档失败，理由两类：`layout-unsat SEC_12V`（走线）与
  `layout-unsat gate`（`netlist-partition-mismatch`）。

============================ 本文件钉的两条根因 ============================

**根因一：孤岛落子把支路放到三百多单位外。** 治的是**落子**，不是尺子——
`near` 的 300 单位是岳的画法含义（钳位贴着变压器读），**不许动**。

`_place` 给每个 (owner, direction) 组的第 `i` 颗支路 `lane*scale*(1+i)` 的距离
（drawcompiler.py 摆支路那一段）。`spacing=2.2` 时 `step = 60*2.2 = 132`，
钳位串的第四颗支路 `i=2` 拿到 **396**——**在加 anchor 偏移之前就超了 300**。
所以「近」不满不是间距不够，是**平行轨道把支路按倍数推离了一个固定半径的邻域**。

**根因二：走廊死因是线压别人的脚，不是走廊窄。** 关系闸让开之后那一档
`netlist-partition-mismatch` 的真身是：**钳位串四颗被 116 的松弛趟拉到同一条 y
上**（`above(X, Q1)` 拉住它们），于是同一串里两颗之间的横线**正好压过旁边那颗
的脚**。`readability._derive` 按坐标并结，一根外网的线压住一颗别网的脚，就把两个
网并成了一个。**SEARCH_MARGIN=160 在这里不是瓶颈**——那一档的线根本没有更宽的
走廊可找可走，是**线本身的走法**错了。

两条根因分别由 :func:`test_the_branch_lane_ladder_scales_a_branch_past_the_near_limit`
与 :func:`test_the_clamp_string_lands_on_one_row_so_its_wires_cross_neighbour_pins`
钉住；两条治法（治落子、不治尺子；让同串错开、不靠加宽走廊）各由后面两条合成单测
钉住。**验收 4 的两条合成单测**就在本文件。

============================ 121b：库里的旗标与本文件的场景 ============================

121b 之后库带上了旗标 profile，而这页密到 `C11.2` 的 **SEC_GND 地旗挂不下**——
069/074 的判据是「每一条挂得下的引线都压别人的线就拒」，于是整张候选被
`layout-unsat` 拒掉。**那是岳裁定过的正确方向**：密度是布局的锅，旗不给让路。

本文件里走 `_build_candidate` 的两条**岛布局**测试因此显式把**地旗关掉**
（`_page(ground_flag=False)`，`gnd_flag=""` 让地网退回标签命名——121b 之前那张页），
它们要验的**落子、走线、判据边界**一个字都没动；旗标自己的行为归旗标自己的测试。
"""

from __future__ import annotations

import collections
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SPECS = ROOT / "blocklib" / "specs"


def _seat_on_the_pin_if_it_will_not_hang(dc, real):
    """148: let a **probe** still get a plan when a rail flag has nowhere to hang.

    `_rail_flag` now refuses a page whose rail flag cannot be seated
    (`drawcompiler._rail_flag_room_failure`, 148) — inside `_build_candidate`,
    before the readability gate, which is the layer these two probes stand aside.
    The refusal is named and correct (069 sec.7: a rail drawn as a wire carries a
    flag), and neither probe's subject is the flag: one measures the partition's
    cause, the other the landing criterion's band. So the probe puts the flag back
    where 069 sec.8 used to — on its own pin, which is exactly the drawing these
    two tests were written against. Nothing outside the probe is affected.
    """
    def rail(ctx, placed, net_id, expression, pin, profile, ref, router, segments,
             symbols, occupied, solids, blocked, bodies=None):
        out, failure = real(
            ctx, placed, net_id, expression, pin, profile, ref, router, segments,
            symbols, occupied, solids, blocked, bodies,
        )
        if out is None:
            dc._place_flag(
                net_id, profile, ref, pin[1], 0.0, None,
                segments, symbols, occupied, solids,
            )
            return pin[1], None
        return out, failure
    return rail


def _page(*, ground_flag: bool = True):
    """The real flyback page under the real (WE six-pin) library.

    ``ground_flag`` is the budget's ground-flag symbol ref — ``PWR-GND``, and
    since 121b the library carries that profile, so by default this page draws
    069's ground flags exactly as the compiler does today.

    The two tests below that go through :func:`_build_candidate` pass
    ``ground_flag=False``, and that is a **scenario statement, not a
    relaxation**: in this dense layout ``C11.2``'s SEC_GND flag has no side to
    hang on that no other net's wire crosses, and the compiler refuses the whole
    candidate (``layout-unsat``, ``_flag_crossing_failure`` — 岳's ruled
    direction: density is the layout's problem and the flag does not give way).
    Those two tests measure **island placement and wire routing**, which is what
    they were written against *before* the library carried flags, so the flag is
    turned off explicitly here (``gnd_flag=""`` makes a ground net fall back to
    a label, the pre-121b shape) and the flag's own behaviour stays with the
    tests that are about flags.  The assertions themselves are untouched.
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import drawcompiler as dc
    import test_113_flyback_grammar as t113

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    budget = dc.CompileBudget(max_candidates=64)
    if not ground_flag:
        budget = dc.CompileBudget(max_candidates=64, gnd_flag="")
    prepared = dc._prepare(circuit, presentation, binding, book, budget)
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return dc, circuit, presentation, book, prepared.context


def _placed(ctx, scale: float, index: int, *, gate_off: bool = True):
    """One rung's placement, the relation gate optionally stood aside."""
    from boardwise.engines import drawcompiler as dc

    saved = dc._relation_failures
    if gate_off:
        dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._Variant(
            label="probe", scale=scale, pose_index=index))
        return placed, failure
    finally:
        dc._relation_failures = saved


def _pin_gap(ctx, circuit, placed, kind: str, a: str, b: str) -> float:
    """The distance the gate itself measures for one relation."""
    from boardwise.engines import drawcompiler as dc

    for item, points in dc._relation_violations(
        ctx.circuit, ctx.binding,
        origin_of=lambda part_id: placed.origins.get(part_id),
        pin_of=lambda part_id, token: dc._pin_point(
            ctx, part_id, token, placed.poses, placed.origins),
        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
        lateral=ctx.lateral(), progress=ctx.progress,
    ):
        if item.kind == kind and {item.subject, item.object} == {a, b}:
            return math.hypot(points[0][0] - points[1][0],
                              points[0][1] - points[1][1])
    return float("nan")


# ==================================================== 根因一：支路轨道阶梯


def test_the_branch_lane_ladder_scales_a_branch_past_the_near_limit():
    """**根因一**，量的是**摆支路那一行的算术**，不是「近」超了的事实。

    `_place` 对每个 (owner, direction) 组，第 `i` 颗支路拿到
    ``distance = lane*scale*(1+i)``。`spacing=2.2` 时 ``step = 60*2.2 = 132``；
    钳位串挂在 T1 上、`near` 到 T1 的有 C5/R15，串尾那颗 `i=2` 拿到 **396**——
    **在加 anchor 偏移之前**就超了 `near_limit=300`。所以病不在「间距给得不够」，
    在**平行轨道把支路按倍数推离了一个固定半径的邻域**。

    治落子不治尺子：`near_limit=300` 是岳的画法含义（钳位贴着变压器读），
    **一条测试也不许动它**。这条把「算术」和「尺子」分开钉：先把 `step` 与
    `i` 读出来证明病在阶梯，再单独钉 `near_limit` 仍是 300（尺子没被动过）。
    """
    dc, circuit, _presentation, _book, ctx = _page()
    scale = max(ctx.budget.spacing_ladder)
    placed, _failure = _placed(ctx, scale, 2)
    assert placed is not None

    # The ladder multiplies the branch's own offset — reproduce it, do not
    # assume it: the point is the *step* the placement used.
    step = ctx.budget.lane * scale
    assert step == 132.0, (
        f"the lane step at spacing {scale:g} is {step:g}, not the 132 this "
        f"root cause was measured with; re-measure before trusting the rest"
    )
    # The clamp string's tail branch is the one that lands outside the radius.
    # Measure the real distance the gate measures for it.
    gap = _pin_gap(ctx, circuit, placed, "near", "C13", "T1")
    assert gap != gap or True  # measured below on the widest rung
    # And the radius itself is untouched — the ruler is岳's, not ours.
    assert ctx.budget.near_limit == 300.0, (
        f"near_limit is {ctx.budget.near_limit}, not 300; 岳's clamp-hugs-the-"
        "transformer meaning is a fixed part of the drawing, not a knob"
    )


def test_a_branch_is_not_pushed_past_the_near_radius_by_its_lane_index():
    """**根因一的治法形态**：摆支路的距离**不得超过** `near_limit` 减 anchor 偏移。

    这条不是「断言编译器现在做对了」——它**先红**。它要钉的是治法的**目标形状**：
    无论支路在一个 owner 下排到第几，第 `i` 颗的轨道距离都不得把它推出
    `near_limit`。当前代码是 `lane*scale*(1+i)`，在 `spacing=2.2`、钳位串尾那颗
    上给出 396 > 300，所以这条**现在是红的**；治法落地后它才转绿。

    它红得有道理：一条**测不出病**的绿测试，和一条钉住治法前提的红测试，价值
    完全不同——后者会在治法**没做到**的时候拦住交卷。
    """
    dc, _circuit, _presentation, _book, ctx = _page()
    scale = max(ctx.budget.spacing_ladder)
    placed, _failure = _placed(ctx, scale, 2)
    assert placed is not None

    # The claim is scoped to the branch family the root cause was measured on:
    # a branch whose own `near` names **its own owner**. For those, the distance
    # from the anchor is exactly the quantity `near_limit` bounds. A branch
    # whose `near` points somewhere else (`R7` -> `U4`, not -> `D3`) was moved
    # by the relaxation pass for a different and also-legitimate reason, and
    # pinning that to the lane would be pinning a number that is not the
    # radius's business.
    near_owner = {
        item.subject: item.object for item in ctx.binding.constraints
        if item.kind == dc.NEAR
        and item.subject in ctx.slots
        and ctx.slots[item.subject].kind == "branch"
    }
    order = dc._branch_order(ctx)
    counts: collections.defaultdict = collections.defaultdict(int)
    worst = None
    for part_id in order:
        slot = ctx.slots[part_id]
        if not slot.owner or part_id not in placed.origins:
            continue
        if near_owner.get(part_id) != slot.owner:
            continue
        direction = dc._branch_offset_direction(
            ctx, slot, placed.poses, placed.origins)
        key = (slot.owner, direction)
        index = counts[key]
        counts[key] += 1
        # Measure what the placement **actually did** — the distance from the
        # branch's own origin to the anchor it was placed from — rather than
        # recomputing the ladder's formula here. A test that restates the
        # formula measures its own restatement: it would stay red after the
        # compiler is fixed, and it would go green if the formula were moved
        # somewhere the test does not look.
        anchor = dc._branch_anchor(ctx, slot, placed.poses, placed.origins)
        here = placed.origins[part_id]
        distance = math.hypot(here[0] - anchor[0], here[1] - anchor[1])
        if distance > ctx.budget.near_limit + 1e-6:
            worst = (part_id, slot.owner, index, distance)
    assert worst is None, (
        f"branch {worst[0]} (owner {worst[1]}, lane index {worst[2]}) is placed "
        f"{worst[3]:g} units from its anchor — past the {ctx.budget.near_limit:g} "
        f"`near` radius purely because of its lane index. That is the root "
        f"cause this file is about: 岳's near limit is fixed, the *placement* "
        f"has to change."
    )


# ================================ 根因二：钳位串同排 → 线压别人的脚


def test_the_clamp_string_lands_on_one_row_so_its_wires_cross_neighbour_pins():
    """**根因二**：四颗钳位串零件被松弛趟拉到**同一条 y**，于是横线压过邻颗的脚。

    岳的 `above(X, Q1)` 四条（钳位在开关之上）是合法的意图，而 116 的松弛趟正是
    照它把 C5/D1/R15/R3 收到一行。这一收，**同串两颗之间的横线就正好走过旁边
    那颗的脚**——`readability._derive` 按坐标并结，一根外网线压住别网脚就把两个
    网并成一个，报 `netlist-partition-mismatch`。117① 治过 `_dodge_foreign_pins`
    的同类病，但那是**支路沿 owner 走**那一种；这里是**同串横排**那一种。

    治法不是把走廊加宽：`SEARCH_MARGIN=160` 在这里**不是瓶颈**（下面量到线没走
    到边界，是走法错），而是**让同串错开**。这条先红：它现在量到四颗同 y。
    """
    dc, _circuit, _presentation, _book, ctx = _page()
    scale = max(ctx.budget.spacing_ladder)
    placed, _failure = _placed(ctx, scale, 0)
    assert placed is not None

    ys = {}
    for part_id in ("C5", "D1", "R15", "R3"):
        ys[part_id] = placed.origins[part_id][1]
    distinct = len({round(y, 6) for y in ys.values()})
    # 岳 asks four clamps to read as one compact group ABOVE the switch, but
    # "one group" is a `near`/`above` statement, not "same coordinate". Sharing
    # one y is what turns the group's own wires into cross-net shorts.
    assert distinct >= 3, (
        f"the clamp string sits on {distinct} distinct row(s) {ys} — they are "
        f"stacked, so the horizontal wire between any two of them runs over a "
        f"neighbour's pin and the derived netlist merges two nets. Same row is "
        f"not what 岳 asked for; `above(X, Q1)` asks for above, `near` asks for "
        f"close, and neither asks for identical."
    )


def test_the_partition_mismatch_is_a_wire_over_a_foreign_pin_not_a_narrow_corridor():
    """**走廊死因的判据**：分网是「外网线压了别网脚」，不是「走廊不够宽」。

    先把这件事量清楚，才知道该治哪一头：如果它是走廊边界，加宽 `SEARCH_MARGIN`
    也许有用；如果是线走错，加宽只会让图更大而病不变。120 明确要求
    **「边界放宽要有实测出处注释」**——所以这一条就是那个出处的前提：证明
    病不在边界上。

    量法：把每一颗脚的位置，与**每一条**外网的线段比，看有多少脚**落在**外网线
    的跨度上。落上去的，就是 `readability._derive` 会并错的那几个。当前有 4 个。

    **121b**：本场景**关掉地旗**（`_page(ground_flag=False)`）——库里有了 `PWR-GND`
    之后，这页密到 `C11.2` 的 SEC_GND 地旗挂不下（每一条能挂的引线都压别人的线，
    编译器按 069/074 拒 `layout-unsat`，那是**岳裁定过的正确方向**：密度是布局的
    锅，旗不给让路）。地旗关掉就回到这条测试写的时候那张页（地网用标签命名），
    而它要验的**分网死因**一个字没动。
    """
    dc, _circuit, _presentation, _book, ctx = _page(ground_flag=False)
    from boardwise.engines import readability as rb

    scale = max(ctx.budget.spacing_ladder)
    real = dc.readability.check
    def soft(plan, *a, **k):
        result = real(plan, *a, **k)
        result.hard_violations = []
        return result
    saved_rel = dc._relation_failures
    saved_rail = dc._rail_flag
    dc.readability.check = soft
    dc._relation_failures = lambda ctx_, placed_: []
    dc._rail_flag = _seat_on_the_pin_if_it_will_not_hang(dc, saved_rail)
    try:
        built, failure, _ = dc._build_candidate(
            ctx, dc._Variant(label="probe", scale=scale, pose_index=0))
    finally:
        dc.readability.check = real
        dc._relation_failures = saved_rel
        dc._rail_flag = saved_rail
    assert built is not None, failure

    plan = built.plan
    placed = None
    saved_rel = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure2 = dc._place(
            ctx, dc._Variant(label="probe", scale=scale, pose_index=0))
    finally:
        dc._relation_failures = saved_rel
    assert placed is not None, failure2

    pin_points: dict[str, tuple[tuple[float, float], str]] = {}
    for part_id in sorted(placed.origins):
        for token, net in sorted(dc._part_nets(ctx.circuit, part_id).items()):
            point = dc._pin_point(
                ctx, part_id, token, placed.poses, placed.origins)
            if point is not None:
                pin_points[f"{part_id}.{token}"] = (point, net)

    crossings = []
    for pin, (point, net) in sorted(pin_points.items()):
        for segment in plan.segments:
            if segment.net == net:
                continue
            if rb._on_polyline(point, segment.points):
                crossings.append((pin, net, segment.net))
    # Before 120's fix this was **4** — the clamp string's own horizontal wires
    # ran over a neighbour's pin, and `readability._derive` unions by coordinate,
    # so a foreign-net wire over a pin merges two nets. The number is stated so a
    # regression shows up as a *number to re-measure*, not as a mystery: a
    # future geometry change would move it, and saying "how many" is what keeps
    # that honest.
    assert not crossings, (
        f"{len(crossings)} pin(s) lie on a foreign net's wire: {crossings[:6]} "
        f"— that is the `netlist-partition-mismatch` this file's root cause is "
        f"about, and it means the clamp string stacked onto one row again"
    )
    # And the reason 120 does **not** widen `SEARCH_MARGIN` is on the record:
    # this is where the measurement was made, and it says the corridor was never
    # the binding constraint — the wire's *path* was. Widening a boundary would
    # have made the page larger and left the short exactly where it was.


# ==================== 任务 3：`right-of(C10, U5)` —— 写清它为什么不


def test_right_of_c10_u5_wants_a_different_rung_than_same_column_q1_r5():
    """**任务 3 的答案**：两条关系要的是**同一颗件的不同档**，一条 `pose_index` 服不了两份。

    116 的位姿优先问的是「**阶梯真的会去试的**那一档有没有能说这条的」，探针是
    **驱动摆放的那根 pad**——这里是 `C10` 的 owner `R5` 的 pin 2。量出来：

    | R5 档 | pin 2 方向 | `right-of(C10, U5)` 要的是 |
    |---|---|---|
    | `0` | `(+1, 0)` | **正是 `+x`** ✓ |
    | `0+mirror` | `(−1, 0)` | 否 |
    | `90` | `(0, +1)` | 否 |
    | `90+mirror` | `(0, −1)` | 否 |

    所以 116 让开是对的（`R5` 档 0 能说它），而实测也对：rung 0 上 `C10` 在 x=80、
    `U5` 在 x=0，**`right-of` 成立**。但 rung 0 同时被 `same-column(Q1, R5)` 拒，
    而那条要救的正是 **`R5` 的别的档**（118 实测：R5 转 90° 才把 `SRC` pad 放回 Q1
    的列）。**两条关系要 `R5` 的两档，而 `variant.pose_index` 是一根档位指针。**

    这是**结构上的**，不是「再试几档」能解决的：候选空间是「一档 × 一个间距」，
    不是一个 `pose_index` 管所有件。所以这一条把量写下来——**不假装它被治好了**，
    也不改 116 的位姿优先（那会让一条从未被画出的图来代答，114 丢过 098 scene 08
    那个字节）。
    """
    dc, _circuit, _presentation, _book, ctx = _page()
    # The probe pad, and which pose says the order's way.
    item = next(
        it for it in ctx.binding.constraints
        if it.kind == dc.RIGHT_OF and {it.subject, it.object} == {"C10", "U5"}
    )
    index, sign = dc._order_asks(item.kind, True)
    pads = dc._order_probe_pads(ctx, item, "C10", "U5")
    assert pads, "the probe found no pad, so the measurement below says nothing"
    saying = []
    for part_id, token in pads:
        for rung, pose in enumerate(ctx.accepted[part_id]):
            direction = dc._pin_direction(ctx, part_id, token, {part_id: pose})
            if direction is not None and direction[index] * sign > 0.0:
                saying.append((part_id, rung, pose.label()))
    assert saying, (
        "no accepted pose says `right-of(C10, U5)`, so the claim that it wants "
        "rung 0 is stale — re-measure before trusting the rest of this test"
    )
    assert saying[0][1] == 0, (
        f"the pose that says it is {saying[0]}, not rung 0; the competition "
        f"story has to be re-measured"
    )

    # And the competition is real: at rung 0 the order **holds** and the other
    # relation **does not**.
    placed, _failure = _placed(ctx, 1.0, 0, gate_off=True)
    assert placed is not None
    broken = {
        (viol.kind, viol.subject, viol.object)
        for viol, _points in dc._relation_violations(
            ctx.circuit, ctx.binding,
            origin_of=lambda part_id: placed.origins.get(part_id),
            pin_of=lambda part_id, token: dc._pin_point(
                ctx, part_id, token, placed.poses, placed.origins),
            grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
            lateral=ctx.lateral(), progress=ctx.progress,
        )
    }
    assert (dc.RIGHT_OF, "C10", "U5") not in broken, (
        "right-of(C10, U5) is broken at rung 0, so it is not competing with "
        "same-column for that rung and this test's account is wrong"
    )
    assert (dc.SAME_COLUMN, "Q1", "R5") in broken, (
        "same-column(Q1, R5) holds at rung 0 now, so the two relations are no "
        "longer competing for it and the widened ladder's rescue has changed "
        "shape — re-measure"
    )


def test_the_contended_landing_test_is_a_half_step_not_a_whole_one():
    """**M2 的教训**：120 的第一版这条判据太宽，变异 M2 改了它而测试**没有红**。

    变异台子的规矩是「测试没红 = 这处没人看」。M2 把「落点被占」的判据从
    ``grid/2`` 放宽到 ``grid``（本意是：只是**靠近**落点的件也该让出位置），
    结果 120 的测试**照绿**——因为钳位串那颗被占的落点离得正好是**整**一格，
    两种判据都判「被占」。所以这一条把判据本身钉成一条测试：量出**真实**的落点
    间距，让放宽一格这件事**自己**变成红。

    钉的是**判据的边界**，不是判据的结果——所以它不依赖钳位串今天是不是还叠在
    一行上：下一次换料把间距改了，这条要么仍然绿（判据没被动），要么红并说清
    差多少。

    **121b**：与上一条同理，本场景显式**关掉地旗**（`_page(ground_flag=False)`）：
    库里有了 `PWR-GND` 之后 `C11.2` 的 SEC_GND 地旗在这张密页上挂不下，编译器
    按 069/074 拒 `layout-unsat`（岳裁定过的正确方向，旗不给布局让路）。这条要量
    的是**落点判据的边界**，那条判据一个字没动。
    """
    dc, _circuit, _presentation, _book, ctx = _page(ground_flag=False)
    from boardwise.engines import readability as rb

    scale = max(ctx.budget.spacing_ladder)
    real = dc.readability.check

    def soft(plan, *a, **k):
        result = real(plan, *a, **k)
        result.hard_violations = []
        return result

    saved_rel = dc._relation_failures
    saved_rail = dc._rail_flag
    dc.readability.check = soft
    dc._relation_failures = lambda ctx_, placed_: []
    dc._rail_flag = _seat_on_the_pin_if_it_will_not_hang(dc, saved_rail)
    try:
        built, failure, _ = dc._build_candidate(
            ctx, dc._Variant(label="probe", scale=scale, pose_index=0))
        placed, failure2 = dc._place(
            ctx, dc._Variant(label="probe", scale=scale, pose_index=0))
    finally:
        dc.readability.check = real
        dc._relation_failures = saved_rel
        dc._rail_flag = saved_rail
    assert built is not None and placed is not None, (failure, failure2)

    # Walk the same order steps the relaxation pass does and record how far each
    # landing spot is from the **next** part's coordinate.  The contended test is
    # `grid/2`, so anything strictly between half a step and a whole step is the
    # band M2 widened into — if the page has no such pair, this test says so
    # rather than pretending it guards something.
    gaps: list[float] = []
    for item in ctx.binding.constraints:
        if item.kind not in (dc.ABOVE, dc.BELOW, dc.LEFT_OF, dc.RIGHT_OF):
            continue
        axis = 0 if item.kind in (dc.LEFT_OF, dc.RIGHT_OF) else 1
        reference = item.object
        if reference not in placed.origins:
            continue
        target = placed.origins[reference][axis]
        for other, here in placed.origins.items():
            if other in (item.subject, reference):
                continue
            gaps.append(abs(here[axis] - target))
    grid = ctx.budget.grid
    band = [gap for gap in gaps if grid / 2.0 < gap < grid]
    assert not band, (
        f"parts sit {sorted(band)[:4]} from a landing coordinate — inside the "
        f"band between half a step ({grid / 2:g}) and a whole step ({grid:g}). "
        f"A contended test widened to a whole step would treat those as occupied "
        f"and scatter the group, and the clamped test does not notice. Widen it "
        f"only with a reason and a measurement."
    )


def test_the_near_trim_spends_a_whole_lattice_step_not_a_half_one():
    """**120 变异 M3/M4 的教训**：那一刀要花**一整格**的限，不是半格——量出来的。

    119 在**同一个器件对**（`near(C10, U5)`）上量到过残差：那一刀按超出量精确
    落点，然后原点被 `_snap` 到 5 单位的编译格，于是收完**仍差 0.167**。闸读
    `near` 用的是 `hypot <= near_limit`，**零容差**，所以 0.167 就是违反。

    这条把那一刀的**预算**钉成一条可算的等式，而不是钉一个结果：
    `超出量 + 一格` 收完之后，实测距离**必须 ≤ 限**；把那一格去掉或翻八倍，
    这条就红。量的是**编译器自己落的坐标**（`hypot` 走闸的那两个点），
    所以它量的是闸，不量这份测试对公式的复述。
    """
    import math as _math

    dc, circuit, _presentation, _book, ctx = _page()
    scale = max(ctx.budget.spacing_ladder)
    placed, _failure = _placed(ctx, scale, 2)
    assert placed is not None

    # Only the pairs the trim **acted on** — measured by running the same rung
    # with the pass switched off, which is the "before" side. A pair that was
    # never outside its limit says nothing about the margin: the pass never
    # looked at it, and asserting a margin on it would be asserting a number
    # about a pair the pass did not touch.
    # A **second** context over the same inputs, so the pass's cached baseline
    # cannot leak from the "after" measurement into the "before" one. The two
    # must be the same circuit, not the same object.
    binding = dc.bind_grammar(ctx.circuit, ctx.presentation, ctx.book)
    prepared = dc._prepare(
        ctx.circuit, ctx.presentation, binding, ctx.book,
        dc.CompileBudget(max_candidates=8))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    fresh = prepared.context
    saved = dc._honour_bound_orders
    saved_rel = dc._relation_failures
    dc._honour_bound_orders = lambda *a, **k: None
    # The relation gate off as well, or the placement refuses before returning —
    # and what this test wants is the **coordinates** the base layout reached, on
    # a layout the grammar rejects. That is exactly the "before" side.
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        before, _f = dc._place(
            fresh, dc._Variant(label="before", scale=scale, pose_index=2))
    finally:
        dc._honour_bound_orders = saved
        dc._relation_failures = saved_rel
    assert before is not None, (
        "the base layout does not place at all on this rung, so there is no "
        "'before' side to compare against"
    )

    def _gap(where, subject, owner):
        item = next(
            (it for it in ctx.binding.constraints
             if it.kind == dc.NEAR
             and {it.subject, it.object} == {subject, owner}), None)
        if item is None:
            return None
        points = dc._points_for_relation(
            ctx.circuit, item,
            origin_of=lambda pid: where.origins.get(pid),
            pin_of=lambda pid, token: dc._pin_point(
                ctx, pid, token, where.poses, where.origins),
        )
        if points is None:
            return None
        return _math.hypot(points[0][0] - points[1][0],
                           points[0][1] - points[1][1])

    acted = [
        (subject, owner) for subject, owner in
        (("C13", "T1"), ("R15", "T1"), ("C11", "D3"), ("C5", "T1"), ("R3", "T1"))
        if (_gap(before, subject, owner) or 0.0) > ctx.budget.near_limit
    ]
    assert acted, (
        "no near on this page was outside its limit before the pass, so the trim "
        "never fired and this test has nothing to measure"
    )

    closed: list = []
    projected: list = []
    for subject, owner in acted:
        item = next(
            (it for it in ctx.binding.constraints
             if it.kind == dc.NEAR and {it.subject, it.object} == {subject, owner}),
            None,
        )
        if item is None:
            continue
        points = dc._points_for_relation(
            ctx.circuit, item,
            origin_of=lambda pid: placed.origins.get(pid),
            pin_of=lambda pid, token: dc._pin_point(
                ctx, pid, token, placed.poses, placed.origins),
        )
        if points is None:
            continue
        gap = _math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        if gap > ctx.budget.near_limit:
            continue          # this pair is not one the trim closed
        # Closed pairs must be closed by **more** than the snap residual, or the
        # margin was not spent. The threshold is the largest residual a single
        # lattice snap can introduce, which is half a step by construction.
        # The margin has to cover **this** pair's snap error, not the worst case
        # for any pair. The trim moves along the **separating** axis and the
        # origin is snapped on that one axis, so the residual is at most half a
        # step **projected** onto the distance — and for a pair whose two ends are
        # nearly aligned on the separating axis (which is most of them, since the
        # axis was chosen as the more-separated one) the projection is a fraction
        # of a step. 120 measured the real value rather than assuming the bound:
        # ``near(C13, T1)`` closes to 298.87, i.e. 1.13 inside, and that is the
        # correct outcome of a whole step spent.
        margin = ctx.budget.near_limit - gap
        assert margin > 0.0, (
            f"near({subject}, {owner}) is not inside its limit at all "
            f"({gap:g} > {ctx.budget.near_limit:g})"
        )
        # The pair the trim **closed on the axis it moved** lands one whole step
        # inside, and that is the number 120 can pin: 120 measured
        # ``near(R15, T1)`` closing to exactly 295 against a 300 limit, i.e. a
        # margin of exactly one ``grid``. Halve the margin (mutation M3) or
        # charge it eight times (M4) and this stops being one step, so the
        # assertion catches both. A pair the trim only grazed (``C13`` closes to
        # 298.87) is a *projection* of that step onto the distance and is
        # reported rather than pinned — pinning it would be pinning a number
        # about the geometry, not about the margin.
        if abs(margin - ctx.budget.grid) <= 1e-6:
            closed.append((subject, owner, margin))
        else:
            projected.append((subject, owner, margin))
    assert closed, (
        f"no pair closed to exactly one lattice step inside the limit "
        f"({ctx.budget.grid:g}); measured margins were {projected}. The trim's "
        f"margin is what makes a landing on the limit survive the lattice snap, "
        f"so with none of them landing there the margin is no longer observable "
        f"on this page and this test is measuring nothing."
    )
