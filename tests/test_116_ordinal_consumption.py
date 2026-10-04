"""116：编译器收官——摆放阶段消费**全部**已绑定序关系。

113 的语法、114 的求解器与孤岛 lane、115① 的支路×owner 保守接管、115② 的
pin token 同尺都已就位。本棒**只动求解器**，`grammar/*.py` 一字不改。

115 申报节剩下的四条闸报是**同一类根因**：摆放阶段不消费「支路×非 owner 链件
/ 支路×支路 / 链件×链件横向」的序关系。

============================ 116 的消费机制 ============================

新的一趟**有界松弛** `_honour_bound_orders`，接在 114 的 lane 松弛之后、
全部落子之后，对**每一个已落子变体**跑：

* **只看已经违反的关系**。一条已经成立的序关系不触发任何位移——这是本棒
  零字节变化的结构性保证，见 ``test_the_pass_is_a_no_op_when_every_order_holds``。
* **位姿优先**（115① 的硬课）：可移动的一侧若有一个**接受位姿**已经照着
  这条关系说，就**让位姿阶梯自己去试**，本趟不代答。
* **以已落子的一侧为基准**（114 lane levelling 的「placed side is the
  reference」范式）：链件与锁件永不被移动；两端都活时低 rank 的一侧留下。
* **轮数写死** `ORDER_RELAX_ROUNDS`。解不出 → 诚实拒绝，关系闸照旧点名关系
  与**两个实测点**，绝不静默放行。

**最硬的闸**：既有五语法编译输出逐字节不变（83 预览 + 15 板 sha256 全同）。
结构性理由由 ``test_the_five_existing_grammars_never_place_a_violating_variant``
钉住：五个既有语法里，**带着违反关系的落子一个也没有**——带着违反的
全是已被拒的变体，所以本趟在它们身上是恒等的。
"""

from __future__ import annotations

import dataclasses
import json
import math
import pathlib
import subprocess

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines.grammar.base import (
    ABOVE,
    RIGHT_OF,
    RelativeConstraint,
    SAME_COLUMN,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

PROV = "engineer_confirmed"


# ------------------------------------------------------------------ 夹具工具


def _pin(number: str, name: str, tip, direction: str) -> SymbolPin:
    return SymbolPin(number=number, tip=tip, name=name, direction=direction)


def _axial() -> SymbolProfile:
    """A two-pad part whose pads sit on the body axis, as 0603 and 0805 do."""
    return SymbolProfile(
        symbol_ref="R-TEST", title="test resistor",
        body=(-5.0, -10.0, 5.0, 10.0),
        poses=[SymbolPose(rotation=0.0, mirror=False)],
        pins=[
            _pin("1", "1", (0.0, 20.0), "up"),
            _pin("2", "2", (0.0, -20.0), "down"),
        ],
    )


def _core(*, poses=None) -> SymbolProfile:
    """A core with four accepted poses by default, so a pose can say an order."""
    return SymbolProfile(
        symbol_ref="U-TEST", title="test core",
        body=(-20.0, -20.0, 20.0, 20.0),
        poses=poses if poses is not None else [
            SymbolPose(rotation=0.0, mirror=False),
            SymbolPose(rotation=90.0, mirror=False),
            SymbolPose(rotation=180.0, mirror=False),
            SymbolPose(rotation=270.0, mirror=False),
        ],
        pins=[
            _pin("1", "A", (0.0, 40.0), "up"),
            _pin("2", "B", (40.0, 0.0), "right"),
            _pin("3", "C", (-40.0, 0.0), "left"),
            _pin("4", "D", (0.0, -40.0), "down"),
        ],
    )


def _circuit(parts, nets) -> CircuitSpec:
    payload = {
        "kind": "boardwise-circuit-spec",
        "specVersion": 1,
        "parts": [
            {"id": part_id, "symbolRef": symbol, "provenance": PROV}
            for part_id, symbol in sorted(parts.items())
        ],
        "nets": [
            {"id": net_id, "class": cls, "members": list(members),
             "provenance": PROV}
            for net_id, (cls, members) in sorted(nets.items())
        ],
    }
    return CircuitSpec.from_dict(payload)


def _presentation(modules) -> PresentationSpec:
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": "ic-periphery",
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
        "modules": modules,
    })


def _prepare(circuit, presentation, book, *, order=()) -> dc._Context:
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    if order:
        binding = dataclasses.replace(
            binding,
            constraints=binding.constraints + tuple(
                RelativeConstraint(kind, subject, object_,
                                   "116 fixture: the order kind under test")
                for kind, subject, object_ in order
            ),
        )
    prepared = dc._prepare(
        circuit, presentation, binding, book,
        dc.CompileBudget(max_candidates=8),
    )
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


def _placed(ctx, index: int = 0):
    """A placement for `ctx`, the relation gate switched off, straight back."""
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._variants(ctx)[index])
        assert placed is not None, failure
        return placed
    finally:
        dc._relation_failures = saved


def _placed_without_pass(ctx, index: int = 0):
    """The same rung with 116's pass switched off — the "before" side.

    A fresh context each time, so the pass's cached baseline cannot leak from
    one placement into the other; the two must be the same circuit, not the
    same object. The relation gate is off as well, or the placement would
    refuse before returning — which is the whole point of measuring the
    "before": it is a layout the grammar rejects, and we want its coordinates.
    """
    fresh = _rebuild(ctx)
    saved_pass = dc._honour_bound_orders
    saved_gate = dc._relation_failures
    dc._honour_bound_orders = lambda *a, **k: None
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(fresh, dc._variants(fresh)[index])
        assert placed is not None, failure
        return placed.origins
    finally:
        dc._honour_bound_orders = saved_pass
        dc._relation_failures = saved_gate


def _rebuild(ctx):
    """A second `_Context` over the same inputs, so a cache cannot be shared."""
    binding = dc.bind_grammar(ctx.circuit, ctx.presentation, ctx.book)
    prepared = dc._prepare(
        ctx.circuit, ctx.presentation, binding, ctx.book,
        dc.CompileBudget(max_candidates=8),
    )
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


def _sample098_context():
    """098's own sample circuit — the grammar whose byte output must not move.

    The mirrored ``pose-variant=1`` rung is the one that makes this the
    sharpest case for 116's pose gate: every order on it is broken, and every
    one of them is answerable by a pose the ladder is about to try.
    """
    import importlib
    scenarios = importlib.import_module("test_098_ic_periphery")
    circuit, presentation = scenarios.sample()
    book = scenarios.library()
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    )
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


#: A branch whose **owner** is the core, but the grammar states an order naming
#: the core on the *other* axis, so nothing the owner's own pad said can answer
#: it. This is the ``right-of(C10, U5)`` shape. ``U2`` is a second core on the
#: ground net so the page is not a single isolated part.
CROSS_CIRCUIT = _circuit(
    {"U1": "U-TEST", "U2": "U-TEST", "C1": "R-TEST"},
    {
        "VOUT": ("power", ["U1.1", "C1.1"]),
        "GND": ("gnd", ["U1.4", "C1.2", "U2.1"]),
        "AUX": ("signal", ["U1.2", "U2.2"]),
    },
)
CROSS_PRESENTATION = _presentation([
    {"id": "core", "parts": ["U1", "U2", "C1"],
     "role": "a core with a hanging branch", "grammarRef": "ic-periphery"},
])
CROSS_BOOK = {"U-TEST": _core(), "R-TEST": _axial()}


# ------------------------------------------- 形态一：支路 × 别链件的序关系


def test_a_branch_order_naming_the_other_axis_is_honoured():
    """**形态一**：`right-of(C1, U1)` —— 支路 × owner，但要求的是**横向**。

    默认摆放让 `C1` 沿 `U1.1` 竖着走（那根 pad 朝上），落点 x 与 `U1` 相同，
    于是 `right-of(C1, U1)`（要 x 更大）被违反。116 那一趟把它挪到右边。

    断言落点：`C1.x > U1.x + grid/2`，量的落点不是某个函数的返回值。
    """
    ctx = _prepare(CROSS_CIRCUIT, CROSS_PRESENTATION, CROSS_BOOK,
                   order=((RIGHT_OF, "C1", "U1"),))
    placed = _placed(ctx)
    here = placed.origins["C1"]
    there = placed.origins["U1"]
    slack = ctx.budget.grid / 2.0
    assert here[0] > there[0] + slack, (
        f"right-of(C1, U1) is not honoured: C1 at {here}, U1 at {there}, "
        f"slack {slack}"
    )


def test_the_pass_is_a_no_op_when_every_order_already_holds():
    """**空触发**：不带任何追加序关系时，一个坐标都不许动。

    这是 83 张预览逐字节不变的那一半保证：116 的趟只对**已经违反**的关系
    起作用，关系本来就成立时它是恒等的。
    """
    ctx = _prepare(CROSS_CIRCUIT, CROSS_PRESENTATION, CROSS_BOOK)
    placed = _placed(ctx)
    saved = dc._honour_bound_orders
    dc._honour_bound_orders = lambda *a, **k: None
    try:
        bare, failure = dc._place(ctx, dc._variants(ctx)[0])
    finally:
        dc._honour_bound_orders = saved
    assert bare is not None, failure
    assert bare.origins == placed.origins


# --------------------------------------------- 形态二：链件 × 链件的横向


def test_a_same_column_between_two_chain_parts_is_left_to_the_poses():
    """**形态二**：`same-column(U1, R1)` —— 链件 × 链件的横向。

    链件永不被移动（114 的硬规则），所以这一条**只能**由位姿阶梯去试。116
    的趟读到「可移动的一侧没有一个接受位姿能说」且两端都不活，就**不动**，
    把决定权交回位姿阶梯。断言落点仍然成立（合成件的中轴件任何位姿同列）。
    """
    circuit = _circuit(
        {"U1": "U-TEST", "U2": "U-TEST", "R1": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "R1.1"]),
            "GND": ("gnd", ["U1.4", "R1.2", "U2.1"]),
            "AUX": ("signal", ["U1.2", "U2.2"]),
        },
    )
    presentation = _presentation([
        {"id": "core", "parts": ["U1", "U2", "R1"],
         "role": "a core with a chain shunt", "grammarRef": "ic-periphery"},
    ])
    ctx = _prepare(circuit, presentation,
                   {"U-TEST": _core(), "R-TEST": _axial()},
                   order=((SAME_COLUMN, "U1", "R1"),))
    placed = _placed(ctx)
    slack = ctx.budget.grid / 2.0
    assert abs(placed.origins["U1"][0] - placed.origins["R1"][0]) <= slack, (
        f"same-column(U1, R1) does not hold: {placed.origins}"
    )


# ----------------------------------------- 形态三：支路 × 支路（near）——真反激


def _flyback_book():
    """The flyback symbol book, loaded the one way this module loads it."""
    book: dict[str, SymbolProfile] = {}
    payload = json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8"))
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                _pin(str(p["number"]), str(p.get("name", "")),
                     (float(p["tip"][0]), float(p["tip"][1])),
                     str(p.get("direction", "")))
                for p in entry["pins"]
            ],
        )
    return book


def _flyback_context():
    """The real flyback page's context, the acceptance target for all four."""
    book = _flyback_book()
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                          dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


def test_a_near_between_two_branches_of_one_string_is_pulled_in():
    """**形态三**：`near(R15, R3)` —— 支路 × 支路（钳位串内部，真反激）。

    114 让每个臂挂在**自己的 owner** 上（`R15` 挂 `T1`、`R3` 挂 `C5`），所以
    串里两只支路各摆各的；spacing=2.2 那档量出 gap 320 > near_limit 300 就
    拒绝。116 那一趟把两只都活着的一对拉近：低 rank 的 `R15` 留下，`R3` 朝它
    走。断言量的是共网 `CLAMP_B` 上两根 pad 的间距。
    """
    ctx = _flyback_context()
    placed = _placed(ctx, 4)  # spacing=2.2 pose=0, the near(R15, R3) variant
    here = dc._pin_point(
        ctx, "R15", dc._token_on(ctx.circuit, "R15", "CLAMP_B"),
        placed.poses, placed.origins)
    there = dc._pin_point(
        ctx, "R3", dc._token_on(ctx.circuit, "R3", "CLAMP_B"),
        placed.poses, placed.origins)
    gap = ((here[0] - there[0]) ** 2 + (here[1] - there[1]) ** 2) ** 0.5
    assert gap <= ctx.budget.near_limit, (
        f"near(R15, R3) is not honoured: measured {here} and {there}, "
        f"gap {gap:g} > near_limit {ctx.budget.near_limit:g}"
    )


# ----------------------------------------- 形态四：无接受位姿时接管而非代答


def test_a_pose_that_already_says_the_order_is_not_answered_for():
    """**位姿优先（115① 的硬课）**，在真正会触发的形态上量。

    098 样板那一档正是它：``pose-variant=1`` 把 ``U1`` 镜像了，于是
    ``left-of(C1, U1)`` 落在 `C1` 的**右边**——关系**确实违反**，趟看得见。
    但 ``U1`` 有一个**位姿阶梯真的会去试**的接受位姿（未镜像那档），它那根
    pad 就朝左。趟读到「位姿阶梯有话说」，就让位，一个坐标都不代答。

    断言量的就是这件事本身：镜像档上 `C1` 仍在 `U1` 的右边（关系确实违反，
    所以这不是「关系本来就成立」的空断言），而**关掉这一趟**之后它会被拖到
    `U1` 自己的列上——那一支反向的断言把判据钉住。
    """
    ctx = _sample098_context()
    placed = _placed(ctx, 1)  # pose-variant=1, the mirrored rung
    unhelped = _placed_without_pass(ctx, 1)

    slack = ctx.budget.grid / 2.0
    assert placed.origins["C1"][0] > placed.origins["U1"][0] + slack, (
        "left-of(C1, U1) holds on the mirrored rung, so this test is measuring "
        "nothing: the order was never broken and the pass never saw it"
    )
    # The pass stood aside, so the part is exactly where the placement alone
    # put it. On this rung the pose gate is what says so — the unmirrored pose
    # the ladder is about to try already points left-of(C1, U1) the right way,
    # so answering for it here is the 098-scene-08 regression. (The byte pin
    # `test_098_scene08_refusal_is_byte_identical_to_the_recorded_baseline`
    # and mutation M2 are what hold that gate down; this test holds the
    # observable consequence here.)
    assert placed.origins == unhelped, (
        "the pass moved a branch on a rung the pose ladder is about to fix: "
        f"{placed.origins} vs {unhelped}"
    )


def test_the_chain_spine_is_never_moved_by_the_pass():
    """链件永不被这一趟移动（114 的硬规则），而是被测出来。

    098 样板里 ``U1`` 是链件。镜像档上四条 ``left-of``/``right-of`` 全部违反，
    正是最想挪动「参照侧」的时候——但链件是页面的脊，挪它会带走所有别的
    关系。断言量的是 ``U1`` 自己：一趟前后逐字不动。
    """
    ctx = _sample098_context()
    placed = _placed(ctx, 1)
    bare_spine = _placed_without_pass(ctx, 1)
    assert placed.origins["U1"] == bare_spine["U1"], (
        f"the chain spine moved: {placed.origins['U1']} vs {bare_spine['U1']}"
    )
    # And the orders really were broken, so this is not a vacuous assertion.
    assert placed.origins["C1"][0] > placed.origins["U1"][0] + ctx.budget.grid / 2.0


def test_a_near_beyond_its_limit_is_trimmed_on_the_separating_axis():
    """``near`` 的超出量取自**二维距离**，不是坐标差。

    `near` 是带预算的距离，不是相等。把支路沿**它与参照分得最开的那根轴**
    挪动，挪掉的量是**真实距离**超出 `near_limit` 的部分——不是那条轴上差值
    超出预算的部分。后者在两点横向远、纵向近时会沿一根 ``near`` 根本没问的
    坐标把器件拖走（116 初稿的第四个 bug），并且会在真实距离本来就够时照样
    触发。

    用的是真反激的 ``near(C10, U5)``：它是唯一一个**在基线档也违反**的
    ``near``，所以这一趟真的会对它动手（098 那些只���宽档违反的 ``near``
    被基线过滤掉了，这也是零字节变化的一部分）。
    """
    ctx = _flyback_context()
    placed = _placed(ctx, 0)
    unhelped = _placed_without_pass(ctx, 0)
    # The pair really was outside its limit before the pass, so this is not a
    # vacuous assertion: the pass had work to do here.
    assert unhelped["C10"] != placed.origins["C10"], (
        f"the pass moved nothing, so there is no trim to measure: "
        f"{unhelped} vs {placed.origins}"
    )
    for item in ctx.binding.constraints:
        if item.kind != dc.NEAR or {item.subject, item.object} != {"C10", "U5"}:
            continue
        points = dc._points_for_relation(
            ctx.circuit, item,
            origin_of=lambda part_id: placed.origins.get(part_id),
            pin_of=lambda part_id, token: dc._pin_point(
                ctx, part_id, token, placed.poses, placed.origins),
        )
        assert points is not None
        gap = math.hypot(points[0][0] - points[1][0], points[0][1] - points[1][1])
        assert gap <= ctx.budget.near_limit, (
            f"near(C10, U5) is still outside its limit after the pass: "
            f"measured {points[0]} and {points[1]}, gap {gap:g}"
        )


def test_no_accepted_pose_says_it_so_the_pass_takes_over():
    """**无位姿可救时接管**（C7 形态的横向版）：趟自己挪。

    owner 只有一个接受位姿、那个位姿**违反**序关系，于是趟把支路挪过去。
    断言落点：`C1.x > U1.x + grid/2`。
    """
    circuit = _circuit(
        {"U1": "U-TEST", "C1": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "C1.1"]),
            "GND": ("gnd", ["U1.4", "C1.2"]),
            "AUX": ("signal", ["U1.2", "U1.3"]),
        },
    )
    presentation = _presentation([
        {"id": "core", "parts": ["U1", "C1"],
         "role": "a core with a hanging branch", "grammarRef": "ic-periphery"},
    ])
    book = {
        "U-TEST": _core(poses=[SymbolPose(rotation=0.0, mirror=False)]),
        "R-TEST": _axial(),
    }
    ctx = _prepare(circuit, presentation, book, order=((RIGHT_OF, "C1", "U1"),))
    placed = _placed(ctx)
    here = placed.origins["C1"]
    there = placed.origins["U1"]
    slack = ctx.budget.grid / 2.0
    assert here[0] > there[0] + slack, (
        f"right-of(C1, U1) is not honoured and no pose could say it: "
        f"C1 at {here}, U1 at {there}"
    )


def test_the_step_is_worked_out_on_the_pin_and_applied_to_the_origin():
    """步长在**被量的那一点**上算，位移落在**原点**上——两者不是同一个点。

    :func:`_points_for_relation` 给同网关系量的��那根 pad，而布局存的是**原点**。
    两者差着该器件自己的 pad 偏移：把 pad 的绝对坐标写进原点的槽位，器件就会
    按自己的偏移量移动，而不是按闸要求的量移动。

    真反激的 ``C10`` 量在 ``COMP`` 的 pad 上，它的 pad 本地偏移是
    ``(0, -20)``——正好差一格，于是这一条能看见这个区别。断言落点：
    `C10` 确实到了 ``below(C10, U5)`` 要求的下方，而**不是** ��一格。
    """
    ctx = _flyback_context()
    placed = _placed(ctx, 0)
    slack = ctx.budget.grid / 2.0
    assert placed.origins["C10"][1] < placed.origins["U5"][1] - slack, (
        f"below(C10, U5) is not honoured: {placed.origins}"
    )
    token = dc._token_on(ctx.circuit, "C10", "COMP")
    offset = dc._pin_local(ctx, "C10", token, placed.poses)
    assert offset != (0.0, 0.0), (
        "this fixture is only meaningful while C10's measured pad is off its "
        f"own origin, and it is at {offset}"
    )
    # The origin is where the relation is read, and it is a whole step clear
    # of U5 — not a step plus the pad's own offset.
    gap = placed.origins["U5"][1] - placed.origins["C10"][1]
    assert gap == pytest.approx(ctx.budget.grid, abs=slack), (
        f"C10 landed {gap:g} below U5, one pad offset away from the step the "
        f"pass is supposed to take: {placed.origins}"
    )


# -------------------------------------------------- 既有语法零位移（结构钉）


def test_the_pass_moves_nothing_for_the_five_existing_grammars():
    """**零字节变化的结构性理由**，收进一个断言。

    116 的趟只对**最紧那一档也违反**的关系起作用。五个既有语法里，没有一条
    关系在 ``spacing=1 pose-variant=0`` 上违反——所以趟在它们身上恒等，83 张
    预览逐字节不变不是运气，是这条。

    这一版的断言量的是**位移**，不是「有没有带着违反的落子」：后者的说法是
    错的（一个落子可以被摆放阶段接受、随后被可读性闸拒掉，它照样带着违反，
    088 的 ``near(D1, CN1)`` 与 098 的 ``near(C1, U1)`` 就是这样），拿它当判据
    会把 114/115 记过的形状重新判成回归。位移才是这件事本身。

    覆盖面用 `tools/116_coverage.py`：它把五个预览生成器各自跑一遍，记下每
    一个 ``_place`` 落子。本测试逐个变体比较「趟开着」与「趟关掉」两套落子
    的原点表。
    """
    probe = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"),
         str(ROOT / "tools" / "116_no_move.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    assert probe.returncode == 0, probe.stdout[-3000:] + probe.stderr[-3000:]
    report = json.loads(
        (ROOT / "outputs" / "116" / "no_move.json").read_text(encoding="utf-8"))
    checked = 0
    for family, entries in sorted(report.items()):
        for entry in entries:
            checked += 1
            assert entry["moved"] == [], (
                f"{family} {entry['variant']}: the pass moved "
                f"{entry['moved']} on a circuit whose tightest rung keeps every "
                f"relation — the 83 previews cannot stay byte-identical"
            )
    assert checked > 100, f"only {checked} placements were checked"


# ----------------------------------------- 098 scene 08 回归钉（承 115）


def test_098_scene08_refusal_is_byte_identical_to_the_recorded_baseline():
    """098 scene 08 承 115 的回归钉：逐字节回到 `cd23f7d0…`。"""
    import hashlib
    out = ROOT / "outputs" / "116" / "previews" / "098"
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"),
         str(ROOT / "tools" / "098_previews.py"), str(out)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    target = out / "098_scene08_narrow_refused.txt"
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    assert digest == "cd23f7d01655411dafe3c103fb748da09b90adcb3772bef1feaf2a46b94bbb81", (
        f"098 scene 08 moved: {digest}"
    )


# ------------------------------------------------ 性能看护（116 收尾，红测先行）


def test_the_flyback_page_compiles_within_its_time_budget():
    """**看护测试**：反激整页编译必须**秒级**完成。

    116 交付后实测的一条性能病：`_honour_bound_orders` 本身只花 0.02s
    （`perf_profile_before.txt`：`router.route` 占 432.4s / 432.6s，
    `_place` 整条 0.072s），但它挪动的那几颗器件让**布线**的两条网走了
    98s 与 39s 才找到路——Dijkstra 在找到之前把走廊搜了个遍。反激整页编译
    从 0.02s 变成 173s，`tests/test_113_flyback_grammar.py` 整个文件从
    0.25s 变成 23 分钟。

    **这条断言量的就是那件事本身**，而且它必须**红过**：修之前它是红的
    （见 `outputs/116/perf_budget_red.txt`）。10 秒的额度是任务书定的，
    留了一倍多的余量——快不是这次的目标，**不再病态**才是。

    计时用 `time.perf_counter` 量这一条测试**自己**的编译调用，不是量整个
    测试文件——别的测试的快慢与它无关。
    """
    import time

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = _flyback_book()
    started = time.perf_counter()
    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))
    elapsed = time.perf_counter() - started
    assert elapsed <= FLYBACK_COMPILE_BUDGET_SECONDS, (
        f"the flyback page took {elapsed:.1f}s, over its "
        f"{FLYBACK_COMPILE_BUDGET_SECONDS:g}s budget — see "
        f"outputs/116/SUMMARY.md for the profile that says where it went"
    )
    # The result is the one 116's other tests pin; the budget must not be met
    # by compiling less.
    assert not result.ok, "if the flyback now compiles, this test is stale"


#: The page's whole compile must stay inside this many seconds.
FLYBACK_COMPILE_BUDGET_SECONDS = 10.0


def test_the_router_still_returns_the_cheapest_wire_not_merely_a_wire():
    r"""A\* 必须是**可采纳**的：还是最便宜的那条线，不只是"一条线"。

    性能修法把 `router.Router.route` 从 Dijkstra 换成了 A\*，启发函数是到最近
    目标点的**曼哈顿距离**（一步算 1.0，转弯与穿越只**加**代价，所以它永不高估）。
    可采纳的启发函数保证 A\* 返回的代价与 Dijkstra **相同**——同一条最便宜的线。

    换成不可采纳的启发函数（例如平方距离）A\* 照样终止、照样返回一条线，**只是
    不再是最便宜的**——快而 quietly wrong，是这一类改动最危险的形状，而本文件
    其它测试都测不到它（在这几个电路上恰好仍画出同样的线）。

    所以这里**暴力穷举**一小块走廊，把 A\* 给的路径代价与「所有合法路径的最小
    代价」比。范围小是为了让测试快，形状是真的：同一块走廊、同样的障碍与
    同样的转弯/穿越计价。
    """
    from boardwise.engines import router as rt

    boxes = [(-10.0, 0.0, 10.0, 40.0)]
    r = rt.Router(grid=5.0, residue=(0.0, 0.0), boxes=boxes,
                  bounds=(-60.0, -60.0, 60.0, 60.0))
    # A foreign wire to cross, so CROSS_COST is priced at least once.
    r.add_edge((0.0, -30.0), (40.0, -30.0))
    start, goal = (-40.0, 20.0), (40.0, 20.0)
    path = r.route(start, goal)
    assert path is not None, "the search found nothing on an open board"
    assert _route_cost(r, path) == _cheapest_cost(r, start, goal), (
        "A* returned a wire that is not the cheapest one — the heuristic is "
        "overestimating, so the search is fast and quietly wrong"
    )


def _route_cost(router, path) -> float:
    """Price a path with the router's own cost model (step + turn + crossing)."""
    from boardwise.engines import router as rt

    total = 0.0
    previous = 4
    for index in range(1, len(path)):
        here, before = path[index], path[index - 1]
        if here == before:
            continue
        direction = (0 if here[0] > before[0] else 1) if here[1] == before[1] \
            else (2 if here[0] > before[0] else 3)
        total += 1.0
        if previous < 4 and previous != direction:
            total += rt.TURN_COST
        if router._crossing(router.node(here)) is not None:
            total += rt.CROSS_COST
        previous = direction
    return total


def _cheapest_cost(router, start, goal) -> float:
    """Brute force the cheapest cost over every legal state sequence."""
    import heapq

    from boardwise.engines import router as rt

    goals = {router.node(goal)}
    start_node = router.node(start)
    best = {(start_node, 4): 0.0}
    frontier = [(0.0, 0, start_node, 4)]
    counter = 1
    steps = ((1, 0), (-1, 0), (0, 1), (0, -1))
    while frontier:
        cost, _, node, arrived = heapq.heappop(frontier)
        if best.get((node, arrived), math.inf) < cost - 1e-9:
            continue
        if node in goals:
            return cost
        for index, (dx, dy) in enumerate(steps):
            other = (node[0] + dx, node[1] + dy)
            if not router._in_bounds(other) or router._wall(other):
                continue
            if not router._step_free(node, other):
                continue
            moving = (1, 0) if dx != 0 else (0, 1)
            here = router._crossing(node)
            if here is not None and here == moving:
                continue
            if here is not None and arrived < 4 and index != arrived:
                continue
            there = router._crossing(other)
            if there is not None and there == moving:
                continue
            total = cost + 1.0
            if arrived < 4 and arrived != index:
                total += rt.TURN_COST
            if there is not None:
                total += rt.CROSS_COST
            state = (other, index)
            if best.get(state, math.inf) <= total + 1e-9:
                continue
            best[state] = total
            heapq.heappush(frontier, (total, counter, other, index))
            counter += 1
    raise AssertionError("the brute force found nothing either")
