"""520A2：链件**可侧向走**（A1/A2）与 baseline 按「最紧那一**档间距**」量（A3）。

520A 的只读诊断（``evidence/520a/relations.md``）把「反激整页 24 档全死在关系闸」
拆成三处必须先做的手术，本文件钉的就是**接缝**，不是数字：

* **A1**（``_honour_bound_orders`` 的 `fixed` 集合）：链件不是「不许动」，而是
  **可以横着走、不能顺着链走**。反激的 ``right-of(D3, T1)`` 两端都是链件，
  在改动前**没有任何一档**能碰它，这是整页零候选的直接机制。
* **A2**（``_order_step`` 的 ``allowed_axis``）：A1 的配套刹车。没有它，链件会
  顺着链轴被推走，链立刻不再是一条线，下一个链件×链件的关系（``below(R5, Q1)``）
  当场破——A1 与 A2 是同一件事的两半，所以两条各钉一条本文件都写。
* **A3**（``_order_baseline``）：116 把「最紧那一档破的关系」量在**第一档**上，
  而第一档既是间距也是位姿。``right-of(C10, U5)`` 恰恰在第一档的排版上**成立**、
  在其余每一档上破，于是它从来没进过 baseline，那一趟**被禁止读它**——
  24 档里有 21 档点名的是这条。A3 把量法从「最紧那一档」改成
  「最紧那一**档间距**（它画的所有位姿）」，并且**只加不减**。

三条断言都量落点／量集合，不量某个函数的返回值；三条都有对应的变异验证
（见 ``evidence/520a2/report.md`` 的验收 5）。
"""

from __future__ import annotations

import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines.grammar.base import BELOW

SPECS = pathlib.Path(__file__).resolve().parents[1] / "blocklib" / "specs"


def _flyback():
    """The real three documents, loaded the way this repo loads them."""
    import test_113_flyback_grammar as t113

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    prepared = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


def _rung_zero(ctx):
    """The tightest rung, as a layout and as a placement, gate switched off."""
    variant = dc._variants(ctx)[0]
    origins, poses, _residue = dc._chain_and_shelf_layout(ctx, variant)
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, variant)
    finally:
        dc._relation_failures = saved
    assert placed is not None, failure
    return variant, origins, poses, placed


def _broken(ctx, origins, poses):
    return {
        (item.kind, item.subject, item.object)
        for item in dc._bound_orders(ctx, origins, poses, None)
    }


# ==================================================== A1：链件可以横着走


def test_a_relation_between_two_chain_parts_is_walked_across_the_chain():
    """**A1**：``right-of(D3, T1)`` —— 两端都是**链件**的横向序关系。

    构造阶梯把 ``[T1, D3, Q1, R5, U5]`` 钉在同一根竖线上（``ctx.progress`` 是
    ``(0, -1)``，五件的 x 全是 0），而 ``right-of`` 量的是 x。改动前 ``fixed``
    含整条链，所以两端都「不许动」，这一条**永远**没机会被满足——520A 实测它
    在 24/24 档上都破。

    断言两件事：这条关系在**过闸之前**确实是破的（否则这条测试量不到东西），
    过闸之后**成立**（`D3` 的 x 真的比 `T1` 大过容差）。两件都量落点。
    """
    ctx = _flyback()
    assert {"D3", "T1"} <= set(ctx.chain), (
        "this test is about a pair of **chain** members; the fixture changed "
        f"which parts form the chain: {ctx.chain}"
    )
    _variant, origins, poses, placed = _rung_zero(ctx)
    assert ("right-of", "D3", "T1") in _broken(ctx, origins, poses), (
        "right-of(D3, T1) already holds before the pass on this rung, so this "
        "test would pass without A1 measuring anything — re-measure the fixture"
    )
    slack = ctx.budget.grid / 2.0
    assert (placed.origins["D3"][0]
            > placed.origins["T1"][0] + slack), (
        f"A1 did not walk a chain part across the chain: D3 at "
        f"{placed.origins['D3']}, T1 at {placed.origins['T1']}, slack {slack} — "
        "two chain members can never satisfy a lateral order if neither may walk"
    )


# ============================================== A2：链件不许顺着链走


def test_a_walk_along_the_chain_axis_is_refused_when_the_caller_says_so():
    """**A2**：``allowed_axis`` 挡住「顺着链轴被推走」。

    A1 只放宽了一条轴。这条测试把**同一对器件、同一把尺子**放进一个**故意破**
    的落点里（把 `R5` 挪到 `Q1` 上方，于是 ``below(R5, Q1)`` 是破的），然后问
    `_order_step` 两次：

    * ``allowed_axis`` = 横向（链件的合法方向）→ **不动**，返回 False；
    * ``allowed_axis`` = None（自由件）→ 顺着链轴动，破的关系被满足。

    两次的差别就是 A2 的全部内容：没有这道闸，A1 一放开，链件就会顺着链轴被
    推走，链不再是一条线（520A 的 experiment C 实测 ``below(R5, Q1)`` 冒出来）。
    """
    ctx = _flyback()
    variant, origins, poses, _placed = _rung_zero(ctx)
    across = dc._across_axis(ctx)
    along = 1 - across
    r5, q1 = origins["R5"], origins["Q1"]
    # A placement where `below(R5, Q1)` is genuinely broken, so the walk has
    # something to do: `R5` on the far side of `Q1` from the one `below` names.
    broken_origins = dict(origins)
    broken_origins["R5"] = (r5[across], q1[along] + 2 * ctx.budget.grid)
    item = next(
        constraint for constraint in ctx.binding.constraints
        if (constraint.kind, constraint.subject, constraint.object)
        == (BELOW, "R5", "Q1")
    )
    assert item is not None, "the fixture no longer states below(R5, Q1)"

    refused = dict(broken_origins)
    assert dc._order_step(
        ctx, item, "R5", "Q1", refused, poses, allowed_axis=across
    ) is False, (
        "the walk moved a chain part along the chain: A2's axis guard is not "
        "holding, and A1 then costs the page its chain line"
    )
    assert refused == broken_origins, (
        f"a refused walk still moved something: {refused} vs {broken_origins}"
    )

    allowed = dict(broken_origins)
    assert dc._order_step(
        ctx, item, "R5", "Q1", allowed, poses, allowed_axis=None
    ) is True, (
        "the same walk with no axis restriction did nothing, so this test is "
        "not measuring the guard — it is measuring a relation that cannot move"
    )
    assert allowed["R5"][along] != broken_origins["R5"][along], (
        "the unrestricted walk reported a move it did not make"
    )
    assert allowed["R5"][across] == broken_origins["R5"][across], (
        "a `below` walk moved the across-chain coordinate as well"
    )


# ================================ A3：baseline 量「最紧那一档间距」而不是一档


def test_right_of_c10_u5_enters_the_baseline_the_pass_reads():
    """**A3**：``right-of(C10, U5)`` 必须进 baseline，否则那一趟读不到它。

    116 的 baseline 是**第一档**（``spacing=1 pose-variant=0``）的排版破的关系。
    520A 实测：``right-of(C10, U5)`` 在**那一档上成立**、在其余每一档上破，
    所以它从来没进过这个集合，那一趟被禁止消费它——24 档里 21 档点名的是它。

    断言三件，都量集合：

    * 第一档的排版确实**不破**它（否则这条测试的前提不成立）；
    * 于是 116 的读法里**没有**它；
    * 而 ``_order_baseline`` 里有它。
    """
    ctx = _flyback()
    variant = dc._variants(ctx)[0]
    origins, poses, _residue = dc._chain_and_shelf_layout(ctx, variant)
    reading = ("right-of", "C10", "U5")
    assert reading not in _broken(ctx, origins, poses), (
        "right-of(C10, U5) now breaks on the tightest rung's own layout, so the "
        "gap A3 exists to close is somewhere else — re-measure before trusting "
        "this test"
    )
    baseline = dc._order_baseline(ctx, origins, poses)
    assert reading in baseline, (
        f"right-of(C10, U5) is not in the baseline the pass reads ({sorted(baseline)}), "
        "so the pass is forbidden to consume it on the rungs that break it"
    )


def test_the_baseline_is_116s_set_widened_by_the_tightest_pitch_only():
    """**A3 的第二半**：只加不减，而且加的是**最紧那一档间距**的量。

    * **不减**：116 自己的读法（提出问题那一档的排版）仍然在集合里——直接调
      ``_place_chain_and_shelf`` 的调用方（测试与批工具会这么调）看到的集合
      比改动前只多不少；
    * **只加最紧那一档间距**：加进来的那部分，正是 ``spacing=<ladder[0]>``
      这一档间距在位姿 0/1 上排版破的关系，``right-of(C10, U5)`` 在其中。
    """
    ctx = _flyback()
    variant = dc._variants(ctx)[0]
    origins, poses, _residue = dc._chain_and_shelf_layout(ctx, variant)
    baseline = dc._order_baseline(ctx, origins, poses)
    asking_rung = _broken(ctx, origins, poses)
    assert asking_rung <= baseline, (
        f"the baseline dropped relations the asking rung breaks: "
        f"{sorted(asking_rung - baseline)}"
    )
    tightest = min(ctx.budget.spacing_ladder)
    pitch = set()
    for other in dc._variants(ctx):
        if other.scale != tightest:
            continue
        layout = dc._chain_and_shelf_layout(ctx, other)
        if isinstance(layout, dc.GrammarFailure):
            continue
        pitch |= _broken(ctx, layout[0], layout[1])
    assert baseline == asking_rung | pitch, (
        f"the baseline is neither 116's set nor a subset of it: "
        f"extra={sorted(baseline - (asking_rung | pitch))}"
    )
    assert ("right-of", "C10", "U5") in pitch, (
        "the relation A3 exists for is not in the tightest pitch's own reading"
    )


if __name__ == "__main__":  # pragma: no cover - a convenience for a manual run
    raise SystemExit(pytest.main([__file__, "-q"]))
