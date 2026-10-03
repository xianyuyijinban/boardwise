"""097：`_annotation_allowance` 的估算修正，外加 096 留下的两处死参清理。

096 修锚点吸附时实测出来的遗留（`evidence/096/README.md` §三、`mutation_M2.txt`）：
「1170×825 明明装得下却被报放不下」有**两处**贡献，格外吸 1~2.5 单位（096 已修）
和估算估短（本批）。096 那次是 `ceil(331/5)*5 - 331 = 4` 的 4 单位增量恰好盖住
了估算的缺口——运气不是修复：位移落在格点上时同一张图仍会被拒。

097 的实测（`evidence/097/allowance_probe.py` / `bound_sweep.py`，257 张 plan 逐张
对表）：

* 旧估算只有**网名**一项（`stub + 最宽网名 + TEXT_GAP`），它盖住了旗标/标签那一类
  外伸（实测最长 36），却**完全不管器件自己的位号与值文字**；
* 文字是画在器件框的某一**侧**的，落到左侧时它越过器件左边界
  `TEXT_GAP + 该行文字宽度`——岳样板上那颗 `SMCJ28CA`（宽 62）在器件左侧，
  于是整幅图的真实外伸是 **70**，而旧估算说 **66**，差的就是这 4 单位；
* 两项各管一类对象，谁也盖不住谁（旧项在一张图上短 4~12，新项在 45 张图上短 7），
  所以修法是**取较大者**而不是相加：`max(stub + 最宽网名 + TEXT_GAP,
  TEXT_GAP + 最宽文字 − 该器件离图左边界的偏移)`。

本文件钉住的就是上面这张表能变成断言的部分：

1. 096 那张图现在**不靠运气**：左边正好贴住页边（不短也不虚），而且把吸附关掉
   （`_snap_inside` 置为恒等）也一样——吸附补 0 单位这件事本身就是断言；
2. 同一批声明页面的场景里，估算不再把任何一张能装下的图顶到页边外；装不下的
   那些仍被拒，且拒的理由是**真实的尺寸**（本文件独立量一次，不看估算）；
3. 两项分量各自都还在：网名分量在一张网名比文字宽的图上正是生效的那一项；
4. 位号/值文字只有**一处**定义（`_part_lines`），锚点留位与文字落点读的是同一份；
5. 死参清理（`readability.check_page(high_fanout=...)`、`pagecompiler._is_bus` 的
   第二个形参、`readability.PAGE_HIGH_FANOUT`）摘干净了，而**同名还活着的那两处**
   （`CompileBudget.high_fanout`、`LabelPolicy.high_fanout`）一个字节没动。
"""

from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

import test_053b_drawcompiler as b053
import test_088_power_entry as s088
import test_088b_followups as s088b

from boardwise.core.presentationspec import LabelPolicy, PresentationSpec
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines import readability

PAGE = (0.0, 0.0, 1170.0, 825.0)
NARROW = (0.0, 0.0, 200.0, 150.0)
INNER = (PAGE[0] + dc.PAGE_MARGIN, PAGE[1] + dc.PAGE_MARGIN,
         PAGE[2] - dc.PAGE_MARGIN, PAGE[3] - dc.PAGE_MARGIN)


@pytest.fixture
def unsnapped(monkeypatch):
    """Take the lattice snap out of the picture, leaving the estimate alone.

    `_snap_inside` only ever moves the drawing **inwards** (096), so with it
    neutralised "the drawing is still inside the margin" is a statement about the
    estimate and nothing else — which is the whole point of this batch.
    """
    monkeypatch.setattr(
        dc, "_snap_inside", lambda value, grid, residue, inside: value
    )


def drawn_box(plan):
    """The box the finished drawing occupies, by the page compiler's own reader."""
    return pc._module_frame(plan, s088.library(), 0.0)


# ------------------------------------------------------------------ 1. 不靠运气


def test_the_sample_096_only_fitted_by_luck_lands_exactly_on_its_margin():
    """096 的实案：岳样板在 1170×825 上装得下，而且左边**正好**贴住页边.

    "正好"是两侧都钉住：短了 `_overflow` 会拒（或贴不住），虚了左边会落得更靠内。

    注意这条**单独不能**证明"不靠运气"：096 靠 `ceil` 补的 4 单位恰好也落在这里
    （`evidence/097/displacement_probe.txt` 的旧估算那一栏写着 `snap added +4`），
    所以吸附开着时这个等式对"估算对"和"估算短 4 而吸附补 4"是同一张图。
    真正把运气摘掉的是下面那条：把吸附关掉，它必须**还是**这个数。
    """
    result = s088.compile_module(
        s088.inlet_circuit(), s088.inlet_presentation(),
        budget=dc.CompileBudget(page_box=PAGE),
    )

    assert result.ok, result.render_failures()
    assert result.candidates
    for plan in result.candidates:
        box = drawn_box(plan)
        assert box[0] == pytest.approx(INNER[0], abs=1e-6), box
        assert box[1] >= INNER[1] - 1e-6, box
        assert box[2] <= INNER[2] + 1e-6 and box[3] <= INNER[3] + 1e-6, box


def test_the_snap_is_no_longer_load_bearing_for_that_fit(unsnapped):
    """把吸附关掉，同一张图仍然有候选、左边仍然正好贴住页边.

    这是 096 `mutation_M2.txt` 里"no snap at all (exact displacement) → 仍被拒"
    那一行的反面：当时关掉吸附复现了缺陷（估算短 4 单位，谁也没补），现在关掉吸附
    结论不变——补那 4 单位的是估算自己。
    """
    result = s088.compile_module(
        s088.inlet_circuit(), s088.inlet_presentation(),
        budget=dc.CompileBudget(page_box=PAGE),
    )

    assert result.ok, result.render_failures()
    assert result.candidates
    for plan in result.candidates:
        box = drawn_box(plan)
        assert box[0] == pytest.approx(INNER[0], abs=1e-6), box
        assert box[1] >= INNER[1] - 1e-6, box
        assert box[3] <= INNER[3] + 1e-6, box


# ------------------------------------------- 2. 能装下的不再被顶出去（逐张对表）


def _stated(scene_circuit, scene_presentation, page):
    return s088.compile_module(
        scene_circuit, scene_presentation, budget=dc.CompileBudget(page_box=page)
    )


#: 声明了页面、且**装得下**的场景：每一张的每一条候选都必须落在页边内。
FITTING = [
    ("088_scene1_sample",
     lambda: _stated(s088.inlet_circuit(), s088.inlet_presentation(), PAGE)),
    ("088_scene2_mirror",
     lambda: _stated(s088.inlet_circuit(),
                     s088.inlet_presentation(side="left"), PAGE)),
    ("088_scene3_minimal",
     lambda: _stated(s088.inlet_circuit(shunts=("C115",)),
                     s088.inlet_presentation(), PAGE)),
    ("088_scene4_four_branches",
     lambda: _stated(s088.inlet_circuit(shunts=("D1", "C115", "C116", "C117")),
                     s088.inlet_presentation(), PAGE)),
    ("088_scene8_long_text",
     lambda: _stated(s088.inlet_circuit(
         values={"C115": "330uF/35V", "C116": "330uF/35V"}),
         s088.inlet_presentation(), PAGE)),
    ("088b_scene1_declared", lambda: _stated(*s088b.sample(side="right"), PAGE)),
    ("088b_scene2_mirror_declared",
     lambda: _stated(*s088b.sample(side="left"), PAGE)),
    ("088b_scene4_four_declared",
     lambda: _stated(*s088b.sample(order=s088b.FOUR, branches=s088b.FOUR), PAGE)),
    ("088b_scene6_long_values",
     lambda: _stated(*s088b.sample(
         values={"C115": "330uF/35V", "C116": "330uF/35V"}), PAGE)),
]


@pytest.mark.parametrize("name,build", FITTING, ids=[item[0] for item in FITTING])
def test_no_scene_that_fits_is_pushed_outside_its_margin(unsnapped, name, build):
    """估算不短：每一张**装得下**的图，关掉吸附后每一条候选都还在页边内.

    这就是"估短"的直接反面。旧估算在这一批里有 23 张 plan 实测越界（`bound_sweep`
    的 `old estimate short on 23 plan(s)`），修后为 0——断言不是"看起来更好"，
    是同一批场景逐条量出来的。
    """
    result = build()

    assert result.ok, f"{name}: {result.render_failures()}"
    assert result.candidates
    for plan in result.candidates:
        box = drawn_box(plan)
        assert box[0] >= INNER[0] - 1e-6, (name, box)
        assert box[1] >= INNER[1] - 1e-6, (name, box)
        assert box[2] <= INNER[2] + 1e-6, (name, box)
        assert box[3] <= INNER[3] + 1e-6, (name, box)


def test_the_scene_that_really_is_too_small_is_still_refused_for_its_size(unsnapped):
    """反面对照：088 scene9（200×150）装不下，仍然被拒——拒的理由是尺寸.

    尺寸这一半由本测试**独立量**（同一条电路不声明页面时的图形框），不看估算：
    宽度 416 + 两侧页边 40 = 456 > 200，所以这里的"放不下"是真的放不下，
    不是估算又短了一截。
    """
    result = s088.compile_module(
        s088.inlet_circuit(), s088.inlet_presentation(),
        budget=dc.CompileBudget(page_box=NARROW),
    )
    free = s088.compile_module(s088.inlet_circuit(), s088.inlet_presentation())

    assert not result.ok
    assert result.categories() == [dc.FAILURE_LAYOUT_UNSAT], result.render_failures()
    assert free.ok
    box = drawn_box(free.best())
    width = box[2] - box[0]
    height = box[3] - box[1]
    assert width + 2 * dc.PAGE_MARGIN > NARROW[2] - NARROW[0], (width, box)
    assert height + 2 * dc.PAGE_MARGIN > NARROW[3] - NARROW[1], (height, box)


# --------------------------------------------------- 3. 两项分量各自都还在


def test_the_net_name_term_is_still_the_one_that_binds_on_a_narrow_text_scene(
    unsnapped,
):
    """网名分量没有被文字分量**替换**掉：这一张图上生效的正是它.

    053b scene3 —— 位号 `R123456`、值 `1.00Meg` 的两个器件把文字都画在右边
    （实测外伸 0），于是该留的位就是网名那一项；本测试从**电路自己的网名**重算
    这一项（`stub + 最宽网名 + TEXT_GAP` = 62），并钉住左边界就落在
    `页边 + 这一项`上——两项若被相加、或网名项被删掉，这里都不是这个数。
    """
    scene = b053.scenes()[3]
    result = dc.compile(
        scene.circuit, scene.presentation, b053.library(),
        replace(scene.budget, page_box=PAGE),
    )

    assert result.ok, result.render_failures()
    assert result.candidates
    widest = max(dc.text_width(net.id) for net in scene.circuit.nets)
    net_term = dc.STUB + widest + dc.TEXT_GAP
    widest_text = max(
        dc.text_width(line)
        for part in scene.circuit.parts
        for _kind, line in dc._part_lines(_ContextStub(scene.circuit), part.id)
    )
    assert net_term > dc.TEXT_GAP + widest_text, (
        "该场景的文字分量应当**小于**网名分量，否则它证明不了网名项还在："
        f"net={net_term:g} text={dc.TEXT_GAP + widest_text:g}"
    )
    for plan in result.candidates:
        box = drawn_box(plan)
        assert box[0] == pytest.approx(INNER[0] + net_term, abs=1e-6), box


class _ContextStub:
    """The one attribute `_part_lines` reads (`ctx.circuit`) — nothing else.

    The real `_Context` is built inside `compile` and is not addressable from a
    test; `_part_lines` is a pure reader of the circuit spec, so a stub that
    carries it is the honest way to call it directly.
    """

    def __init__(self, circuit_spec):
        self.circuit = circuit_spec


def test_a_part_prints_its_reference_and_its_value_from_one_definition():
    """位号/值只有一处定义：锚点留位与文字落点读同一份（`_part_lines`）.

    096 的 4 单位缺口就是"预留宽度"和"实际打印宽度"各自算出来的结果；这条测试
    钉住那个可能性不存在了——一条电路的每个器件，`LayoutPlan.texts` 里的行与
    `_part_lines` 说的逐字一致（有值的印两行，没值的只印位号）。
    """
    circuit_spec, presentation_spec = s088.inlet_circuit(), s088.inlet_presentation()
    result = s088.compile_module(circuit_spec, presentation_spec)
    plan = result.best()
    ctx = _ContextStub(circuit_spec)

    printed: dict[str, list[tuple[str, str]]] = {}
    for text in plan.texts:
        printed.setdefault(text.part_id, []).append((text.kind, text.text))
    assert printed, "this scene prints text"
    for part_id, lines in printed.items():
        assert sorted(lines) == sorted(dc._part_lines(ctx, part_id)), part_id

    # 没值的器件只印位号一行：库里那颗 TVS 有值，构造一条没有值的电路来看这一态。
    bare = s088.circuit(
        [s088.part("CN1", "XT30PW-M"), s088.part("C115", "CAP-TH_BD10.0-P5.00")],
        [s088.net(s088.RAIL, "power", ["CN1.1", "C115.1"]),
         s088.net(s088.GND, "gnd", ["CN1.2", "C115.2"])],
        interfaces=[{"net": s088.RAIL, "direction": "input", "role": "rail",
                     "part": "CN1", "provenance": s088.PROV}],
    )
    bare_ctx = _ContextStub(bare)
    assert dc._part_lines(bare_ctx, "C115") == (("reference", "C115"),)
    assert dc._part_lines(ctx, "C115") == (
        ("reference", "C115"), ("value", "330uF"),
    )


# ------------------------------------------------------- 4. 死参清理（二、连带）


def test_the_dead_member_count_parameter_is_gone_from_the_page_checker():
    """`readability.check_page(high_fanout=...)` 摘掉：它只被校验、从没被读过.

    069 sec.7 把成员数阈值从页级撤了（"任何扇出的轨都是总线"），096 又把跨模块那条
    网的线/名判据收进 `main_path_wire`，于是这个形参连同它唯一的默认值常量
    `PAGE_HIGH_FANOUT` 一起没了——留着就是"第二个说法"。
    """
    parameters = inspect.signature(readability.check_page).parameters
    assert "high_fanout" not in parameters
    assert "module_gap" in parameters and "keepouts" in parameters
    assert not hasattr(readability, "PAGE_HIGH_FANOUT")
    assert "PAGE_HIGH_FANOUT" not in readability.__all__
    with pytest.raises(TypeError, match="high_fanout"):
        readability.check_page(None, None, None, {}, high_fanout=3)


def test_the_dead_member_count_parameter_is_gone_from_the_bus_reader():
    """`pagecompiler._is_bus` 的第二个形参（069 v3 遗留）摘掉：判据只看 net 的种类."""
    assert list(inspect.signature(pc._is_bus).parameters) == ["net"]
    assert pc._is_bus(None) is False


def test_the_two_live_high_fanouts_of_the_same_name_are_untouched():
    """同一个名字在三处：只有**该摘的那一处**摘了，另两处是活的，一个字节没动.

    * `CompileBudget.high_fanout` —— 模块级"轨何时用旗标"的阈值，`_net_style` 读它；
    * `LabelPolicy.high_fanout` —— `labelPolicy.highFanout` 的模式词，052 的公开词表。

    它们不是死参，清理不许顺手带走。
    """
    assert dc.CompileBudget().high_fanout == dc.HIGH_FANOUT
    assert LabelPolicy().high_fanout == "label"
    spec = PresentationSpec.from_dict({"labelPolicy": {"highFanout": "wire"}})
    assert spec.label_policy.high_fanout == "wire"
    assert spec.to_jsonable()["labelPolicy"]["highFanout"] == "wire"
