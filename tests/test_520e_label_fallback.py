"""520E：连不上的网降级成名字，并且**记账**。

岳的裁决（本批的立项理由）：

    什么时候打网络标签不是纯算法决定的，应该由算法反馈模型决定。
    长得像经典拓扑不等于它一定每个引脚靠导线相接，布局接近拓扑即可。

所以 `_expression_style` 那条「`direct-wire` 义务永不降级」不再是一条**整页**
判决：per net 先试长走线，连不上就把这条网的表达降级成「每脚一个 name」
（`_label_for`，落图侧走 057 sec.4 那条现成的 name stub），并且记一笔
`CompileResult.label_fallbacks`。这一条是**反馈模型**的另一半——没有它，
降级就是一次悄悄替换。

本文件钉四件事，按风险从大到小：

1. **降级真的发生了，而且只降级那一条网**（`_connect_net` 强制失败的夹具）；
2. **记账可机读**：`label_fallbacks` 的字段、`summarize_label_fallbacks()`
   的形状、plan note 的 `downgrade:` 标记，以及「条数对得上」这条不变量；
3. **降级之后还是被拒时，拒绝理由要把两件事都说出来**（长线没出路 + 名字也没
   出路）——这是「只有 label 分支也失败才拒绝整页」那句话的可读形式；
4. **一个只在确定失败时短路的新守卫**（`_unenterable_goal`）与搜索逐字同意：
   它说「进不去」的那些目标点，`route` 也必须返回 `None`。

夹具复用 088 的电源入口页（它有两条实体轨、一条 `directWiringObligations`），
因为它是仓库里最小的、**已知能编译出来**的、带直连义务的页面。
"""

from __future__ import annotations

import pytest

import test_088_power_entry as t088

from boardwise import cli
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability
from boardwise.engines.router import _Router


# --------------------------------------------------------------- 夹具


def _forced(net: str, reason: str = "forced by 520E's own test"):
    """A `_connect_net` that cannot wire `net`, answered the way the real one is.

    The real `_connect_net` returns :class:`dc._Unrouted` now, so a stub that
    returned a bare `None` would be testing a shape no caller produces.
    """
    real = dc._connect_net

    def failing(ctx, router, expression, blocked, existing=()):
        if expression.net == net:
            return dc._Unrouted(stage="trunk", reason=reason)
        return real(ctx, router, expression, blocked, existing)

    return failing, real


def _compiled_forcing(net: str):
    """The 088 inlet page, compiled with `net`'s wiring forced to fail."""
    failing, real = _forced(net)
    circuit = t088.inlet_circuit()
    presentation = t088.inlet_presentation(side="right")
    dc._connect_net = failing
    try:
        result = dc.compile(circuit, presentation, t088.library(),
                            dc.CompileBudget())
    finally:
        dc._connect_net = real
    return result


def _wire_segments(plan, net: str):
    return [item for item in plan.segments if item.net == net]


def _labels(plan, net: str):
    return [item for item in plan.labels if item.net == net]


# ---------------------------------------------- 1. 降级发生，且只降级那一条网


def test_a_promised_net_that_cannot_be_wired_is_named_and_recorded():
    """本批的核心：一条 `direct-wire` 义务连不上，整页不再因此被拒。

    断言四件事：页面仍然出候选、那条网**没有**导线、它每个引脚上有一个 name、
    降级在 `label_fallbacks` 里点名。旧行为下第一条断言就是红的（`_connect_net`
    为这条网返回空 ⇒ 编译器直接 `GrammarFailure` 整页）。
    """
    result = _compiled_forcing(t088.RAIL)

    assert result.ok, result.render_failures()
    plan = result.candidates[0]
    assert _wire_segments(plan, t088.RAIL) == [], (
        "the forced failure must leave this net with no conductor of its own"
    )
    assert len(_labels(plan, t088.RAIL)) == 4, (
        "one name per pin: the 088 inlet rail has CN1.1, D1.1, C115.1, C116.1"
    )
    assert [item.net for item in result.label_fallbacks] == [t088.RAIL]


def test_the_downgrade_records_what_was_promised_why_and_what_is_given_up():
    """记账的四段：哪条网、当初为什么许它一根线、路由给的失败原文、放弃了什么。"""
    result = _compiled_forcing(t088.RAIL)
    [fallback] = result.label_fallbacks

    assert fallback.net == t088.RAIL
    assert fallback.promised == "wire"
    assert fallback.members == ("C115.1", "C116.1", "CN1.1", "D1.1")
    assert "direct-wire obligation" in fallback.role, fallback.role
    assert "forced by 520E" in fallback.reason
    assert fallback.stage == "trunk"
    assert "name" in fallback.gave_up


def test_the_downgrade_is_declared_on_the_plan_with_the_shared_marker():
    """`DOWNGRADE_NOTE_PREFIX` 那一条：`drawapply` 靠它把降级搬进 `downgrades`。

    这条同时也是「不许悄悄替换」的守卫：note 的条数必须与 `label_fallbacks`
    的条数相同——两个地方各记一份，多一条少一条都说明有一半没跟上。
    """
    result = _compiled_forcing(t088.RAIL)
    plan = result.candidates[0]
    marked = [
        note for note in plan.notes
        if note.startswith(dc.DOWNGRADE_NOTE_PREFIX)
    ]
    assert len(marked) == len(result.label_fallbacks) == 1, marked
    assert f"net {t088.RAIL}:" in marked[0]
    assert "promised as a **wire**" in marked[0]


def test_only_the_net_that_failed_is_downgraded_and_the_other_rail_is_still_wired():
    """两条轨都是 `direct-wire` 义务，只有一条连不上——另一条必须照旧是导线。

    没有这条断言，「降级」可以退化成「把所有义务网都换成名字」而测试照样绿。
    """
    result = _compiled_forcing(t088.RAIL)
    plan = result.candidates[0]

    assert [item.net for item in result.label_fallbacks] == [t088.RAIL]
    assert _wire_segments(plan, t088.GND), (
        "the ground is an obligation too, and it was not forced to fail"
    )
    assert _labels(plan, t088.GND) == []


def test_the_named_net_is_still_one_node_in_the_netlists_own_terms():
    """降级不改变电气结论：名字是离线模型的导体（053 的净表推导）。

    这条不是装饰——它是「布局接近拓扑即可」这句话的可验证内容：图弱了，
    网表没弱。
    """
    result = _compiled_forcing(t088.RAIL)
    plan = result.candidates[0]
    circuit = t088.inlet_circuit()
    derived = readability.derive_netlist(plan, t088.library())
    groups = {derived.group_of(member) for member in circuit.net(t088.RAIL).members}
    assert len(groups) == 1, "the names are the netlist's conductors"


# ------------------------------------------------------- 2. 机读的审计入口


def test_the_record_has_its_own_entry_point_beside_the_failure_rounds():
    """`summarize_label_fallbacks()`：给调用方数「这页有几条网是被名字表达的」。

    与 `summarize_failure_rounds` 并列的独立入口，不是让人 grep `notes`。
    """
    result = _compiled_forcing(t088.RAIL)
    summarised = result.summarize_label_fallbacks()

    assert [item["net"] for item in summarised] == [t088.RAIL]
    assert set(summarised[0]) == {
        "net", "members", "promised", "role", "stage", "reason", "gaveUp",
    }
    assert summarised[0]["stage"] == "trunk"
    assert summarised[0]["members"] == ["C115.1", "C116.1", "CN1.1", "D1.1"]


def test_a_result_that_recorded_nothing_summarises_to_nothing():
    """空就是空：手搓的 `CompileResult` 不许凭空造出一条降级来。"""
    assert dc.CompileResult().summarize_label_fallbacks() == []
    assert dc.CompileResult().label_fallbacks == []


def test_the_cli_prints_one_line_per_named_net_and_the_same_count():
    """CLI 的摘要行：条数与 `--json` 的 `labelFallbacks` 同源，所以不许各说各话。"""
    result = _compiled_forcing(t088.RAIL)
    lines = cli._draw_label_fallback_lines(result)

    assert len(lines) == 2, lines
    assert lines[0].startswith("  labels: 1 net(s) are expressed by name")
    assert t088.RAIL in lines[1]
    assert "trunk" in lines[1]


def test_the_cli_says_nothing_when_no_net_was_downgraded():
    """一条都没降级时打印空标题会读成「悄悄降级了 0 条」，所以什么都不打。"""
    assert cli._draw_label_fallback_lines(dc.CompileResult()) == []


# ------------------------------------- 3. 降级之后仍然被拒：两种表达都说清


def _refusal_forcing_every_net():
    """The inlet page with every net's wiring forced to fail **and no room left**.

    The downgrade alone does not refuse this page — measured: with both rails
    named and nothing else changed it still compiles, which is the point of the
    ruling. So the page is made unwinnable the honest way: a keep-out that covers
    the sheet, which the labels cannot avoid either (a label with every direction
    blocked falls back to its pin's own side and overlaps — `_label_at`'s 099b
    rule). That is the case the ruling leaves standing:「只有 label 分支也失败才
    真正拒绝整页」.
    """
    real = dc._connect_net

    def failing(ctx, router, expression, blocked, existing=()):
        return dc._Unrouted(
            stage="trunk", reason=f"forced by 520E's own test ({expression.net})",
        )

    circuit = t088.inlet_circuit()
    presentation = t088.inlet_presentation(side="right")
    dc._connect_net = failing
    try:
        return dc.compile(circuit, presentation, t088.library(),
                          dc.CompileBudget(keepouts=[(-400.0, -400.0, 400.0, 400.0)]))
    finally:
        dc._connect_net = real


def test_a_refusal_after_a_downgrade_says_neither_the_wire_nor_the_name_had_room():
    """拒绝理由要说清「长线和名字都没有出路」。

    这是 520E 里唯一还能拒整页的形状，所以它必须自己说清楚：先说了长线被放弃、
    再说名字也没地方放。少了后半句，读者会把这条拒绝读成一次普通的拥挤抱怨，
    而恰恰在这种情况下降级最不该是隐形的。

    **535 重钉（2026-10-23，实测驱动）**：这一页最后那句「拒绝保留闸自己的第一行」
    里的**第一行换了层**，而这一条真正的主语（降级那一句是**追加**、不是替换）
    没变：

    * **旧读数**（520E 写下这条时）：`GND` 走的是**网络标签**降级，页面继续往下
      走到可读性闸才被拒，于是拒绝原文是
      `the independent readability checker refused …`；
    * **新读数**（第二层修复之后）：`GND` 走 `_label_fallback` 的**旗标**分支
      （530A：地只能是旗标，不许网络标签），而这一页整张被 keepout 盖住，
      `GND` 一面旗标都挂不上——`_seat_wire_flags` 的席位阶梯四个方向全被占，
      于是拒绝原文变成 069 sec.1 那句
      `net 'GND' is named by a flag of its own on C115.2 …`。
      这不是「绕过了一条闸」，而是**同一个事实的诚实出口**：这页画不出来，
      而这一次说清楚画不出来的是**地的那面旗标**——旧路子在页面上留下一堆
      没有实体相连的网络标签，正是 530A 禁掉的那种画法。

    所以断言钉「拒绝原文在前、降级从句在后」这个**形状**，并且逐字说出这一页
    现在被哪一层拒（旧文写死 `the independent readability checker refused`，
    那正是 535 之前的那一层）。
    """
    result = _refusal_forcing_every_net()

    assert not result.ok
    assert [item.net for item in result.label_fallbacks] == [
        t088.RAIL, t088.GND,
    ], "the downgrades must survive the refusal, one record per net"
    detail = " ".join(item.detail for item in result.failures)
    assert "the name had nowhere to go either" in detail, detail[:400]
    assert "2 net(s)" in detail
    assert t088.RAIL in detail and t088.GND in detail
    assert "neither the long wire nor the name has a way out" in detail
    # The refusal keeps the gate's own first line, so a reader still sees *why*
    # the drawing was refused — the clause is added to it, not in place of it.
    # 535: that first line is the 069 sec.1 flag-seat ladder's own refusal of this
    # page's ground (see the docstring — the layer moved, the shape did not).
    assert detail.startswith(
        f"net '{t088.GND}' is named by a flag of its own"
    ), detail[:400]
    assert "069 sec.1" in detail
    assert detail.index("and the name had nowhere to go either") > detail.index(
        "069 sec.1"
    ), "the downgrade clause is appended after the refusal, never instead of it"


def test_the_refusal_clause_names_every_downgraded_net_and_keeps_the_verdict():
    """加一句是**加**：category / subject / action 原样保留，只多一段话。"""
    original = dc.GrammarFailure(
        category="layout-unsat", subject="NET", detail="the gate refused it",
        action="make room",
    )
    fallback = dc.LabelFallback(
        net="NET", members=("U1.1", "U2.1"), promised="wire", role="role",
        stage="trunk", reason="reason", gave_up="a conductor", note="downgrade: x",
    )
    after = dc._refusal_after_downgrade(original, [fallback])

    assert after is not None
    assert after.category == original.category
    assert after.subject == original.subject
    assert after.action == original.action
    assert after.detail.startswith(original.detail)
    assert "NET" in after.detail and "1 net(s)" in after.detail
    # Nothing to add ⇒ the failure is handed back untouched, not copied.
    assert dc._refusal_after_downgrade(original, []) is original
    assert dc._refusal_after_downgrade(None, [fallback]) is None


# -------------------------------------------- 4. 进不去的目标点：守卫与搜索一致


def _router(**overrides) -> _Router:
    options = dict(grid=5.0, residue=(0.0, 0.0), boxes=[],
                   bounds=(0.0, 0.0, 200.0, 200.0))
    options.update(overrides)
    return _Router(**options)


def test_the_unenterable_guard_agrees_with_the_search_it_short_circuits():
    """`_unenterable_goal` 只在**搜索必然返回 None** 时说话。

    这条是那个守卫的独立复算：同一条路由请求，guard 说「进不去」，`route` 就
    必须真的一无所获。反例（目标点不在墙里）guard 必须说「去搜」，而搜索必须
    找到路。守卫错一次就是把一根本来画得出来的线换成名字——所以它比这个文件
    里任何一条断言都更该被钉住。
    """
    router = _router()
    # A body that swallows the middle of the page: the goal at (100, 100) is a
    # strict interior point of it, so the search may never stand there.
    router.boxes = [(80.0, 80.0, 120.0, 120.0)]

    refusal = dc._unenterable_goal(router, (10.0, 100.0), [(100.0, 100.0)])
    assert refusal, "a goal strictly inside a box is unenterable"
    assert "(100, 100)" in refusal
    assert router.route((10.0, 100.0), (100.0, 100.0)) is None, (
        "the guard said 'no solution' — the search has to agree"
    )

    # The same lattice, a goal outside the body: the guard must stay silent and
    # the search must find the detour.
    assert dc._unenterable_goal(router, (10.0, 100.0), [(160.0, 100.0)]) == ""
    assert router.route((10.0, 100.0), (160.0, 100.0)) is not None


def test_the_guard_stays_silent_when_the_start_is_already_on_the_goal():
    """`route` 对 start == goal 有它自己的一条捷径，守卫不许把它抢答掉。"""
    router = _router(boxes=[(80.0, 80.0, 120.0, 120.0)])
    assert dc._unenterable_goal(router, (100.0, 100.0), [(100.0, 100.0)]) == ""
    assert router.route((100.0, 100.0), (100.0, 100.0)) is not None


def test_the_guard_stays_silent_when_only_one_of_several_goals_is_enterable():
    """多目标（`_attach` 的形状）：只要**还有**一个进得去的目标，就得照搜不误。"""
    router = _router(boxes=[(80.0, 80.0, 120.0, 120.0)])
    goals = [(100.0, 100.0), (160.0, 100.0)]
    assert dc._unenterable_goal(router, (10.0, 100.0), goals) == ""


@pytest.mark.parametrize("goal", [
    (100.0, 100.0),   # strictly inside the box
    (80.0, 100.0),    # on its edge — and still a wall: `_wall`'s test carries an
                      # 1e-6 tolerance, so the edge belongs to the box
    (60.0, 100.0),    # outside it, on the way in
    (140.0, 100.0),   # outside it, on the way out
    (200.0, 200.0),   # a corner of the lattice
])
def test_the_guard_fires_exactly_when_the_search_would_come_back_empty(goal):
    """守卫与搜索**逐点**一致：它说话的每个点，`route` 都必须一无所获。

    这条比「贴边算不算墙」更有用：贴边与否是 `_wall` 的事（它的 1e-6 容差把盒边
    算进盒内），而守卫不许有自己的第二个口径——它只许继承搜索的那一个。所以这里
    钉的是等价关系本身，而不是我对几何的猜想。
    """
    router = _router(boxes=[(80.0, 80.0, 120.0, 120.0)])
    start = (10.0, 100.0)
    refusal = dc._unenterable_goal(router, start, [goal])
    path = router.route(start, goal)
    assert bool(refusal) == (path is None), (
        f"guard said {refusal!r} but the search returned {path!r}"
    )
