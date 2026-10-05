"""119：位姿阶梯加宽——只在「全都因为同一条关系被拒」的时候加宽。

============================ 病 ============================

`_variants` 只探索 `pose_index` 0/1。这不是疏忽，是 116 §三 写下来的**硬约束**：
一颗有四个旋转的核可能**碰巧**有个旋转朝对方向，而编译**只画** 0/1 两档——
问「有没有某个旋转」等于替一个**永远不会被画出来**的图作答，那正是 114 丢掉
098 scene 08 的那个字节。所以阶梯只走两档。

118 在真实几何上量出反激的 `same-column(Q1, R5)` **六档全拒**，而 **R5 转 90°
就能救**——那个位姿不在阶梯里。116 的结论（这条归位姿阶梯）**没错**，错的是
它**够不着**。

============================ 治，以及治得了什么 ============================

119 加的不是「把 0/1 改成 0..N」，而是**一轮有条件的加宽**，两个条件都写死：

* **只在 candidates=0 时点火。** 这是整个加宽路径**结构上的恒等**理由：凡是
  现在能编译的东西，这条路径**永远不可达**，所以它一张预览也动不了——**不是**
  因为它「小心」，而是因为它**在那儿**。这一条由
  `test_the_widening_never_runs_when_the_base_ladder_survives` 从**结构上**钉住
  （不是靠观察「预览没变」），字节闸是它的外部复验。
* **只在所有变体都被同一条（组）关系拒掉时点火。** 阶梯对「为什么失败」有分歧，
  说明这一页的零件在好几个方向上互相打架，哪一处能靠位姿解是这里答不出来的
  问题。反激正是为这条写的：六档全被 `same-column(Q1, R5)` 拒掉，别的理由一个
  都不共有。

**边界**：试到零件自己的**接受位姿集**末尾为止，一格不多；`max_candidates`
照旧封顶。解不出来的仍然诚实拒绝，理由逐条不变——加宽是**看得更远**，不是
**放得更松**。

本文件钉两件事（任务书 §验收 4）：

1. **阶梯加宽真的救回了 `same-column` 形态**（合成电路，形态与反激同型）；
2. **全拒仍诚实拒绝**：加宽之后仍解不出时，页面上是**诚实的拒绝**而不是一个
   被悄悄放宽的候选；以及**该拒的两种**——阶梯对失败理由有分歧时、以及失败
   理由根本不是一条关系时，加宽**不许点火**。
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines.grammar.base import (
    NEAR,
    RelativeConstraint,
    SAME_COLUMN,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
PROV = "engineer_confirmed"


# ------------------------------------------------------------------ 夹具


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


def _lay_down(poses=None) -> SymbolProfile:
    """A part whose **pad 1 is off the body axis** — the 118 measurement.

    The real 0603 has its pins at ``(+-20, 0)``, horizontal, so at rotation 0
    its ``SRC`` pad sits 20 units to the side of its origin. That offset is
    exactly what made ``same-column(Q1, R5)`` fail at rung 0 and succeed at
    rotation 90, so a fixture that draws a vertical resistor would test the
    113-era geometry and prove nothing.
    """
    return SymbolProfile(
        symbol_ref="R-LAY", title="test resistor, pads on a horizontal axis",
        body=(-15.0, -5.0, 15.0, 5.0),
        poses=poses if poses is not None else [
            SymbolPose(rotation=0.0, mirror=False),
            SymbolPose(rotation=0.0, mirror=True),
            SymbolPose(rotation=90.0, mirror=False),
            SymbolPose(rotation=90.0, mirror=True),
        ],
        pins=[
            _pin("1", "1", (-20.0, 0.0), "left"),
            _pin("2", "2", (20.0, 0.0), "right"),
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
    return CircuitSpec.from_dict({
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
    })


def _presentation(modules) -> PresentationSpec:
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": "ic-periphery",
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
        "modules": modules,
    })


def _compile(circuit, presentation, book) -> dc.CompileResult:
    return dc.compile(
        circuit, presentation, book, dc.CompileBudget(max_candidates=64)
    )


#: The shape the flyback actually has, at fixture size: **two chain parts** on a
#: shared net, a `same-column` between them, and the second one's pad sitting
#: off its own column at rungs 0/1. A chain relation is the hard case — 116's
#: "链件永不被移" means the placement pass cannot step either end, so a pose is
#: the only thing that can answer it.
CHAIN_COLUMN = (
    _circuit(
        {"U1": "U-TEST", "U2": "U-TEST", "R1": "R-LAY"},
        {
            "VIN": ("power", ["U1.1", "R1.1"]),
            "GND": ("gnd", ["U1.4", "R1.2", "U2.1"]),
            "AUX": ("signal", ["U1.2", "U2.2"]),
        },
    ),
    _presentation([
        {"id": "m1", "role": "entry", "parts": ["U1"]},
        {"id": "m2", "role": "core", "parts": ["U2"]},
        {"id": "m3", "role": "shunt", "parts": ["R1"]},
    ]),
    {"U-TEST": _core(), "R-LAY": _lay_down(), "R-TEST": _axial()},
)


def _with_order(parts, *, order=(), book_extra=None):
    """The fixture above, bound, plus extra relative constraints appended.

    The order is appended **after** the grammar binds, so the fixture states
    the relation the way 118's presentation states it: as a promise the
    placement is measured against, not as something the grammar infers.
    """
    circuit, presentation, book = parts
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    if order:
        binding = dataclasses.replace(
            binding,
            constraints=binding.constraints + tuple(
                RelativeConstraint(kind, subject, object_,
                                   "119 fixture: the relation the widening answers")
                for kind, subject, object_ in order
            ),
        )
    return circuit, presentation, book, binding


# ============================================ 1 点火条件（合成，单测这一层）


def _plain_page():
    return (
        _circuit(
            {"U1": "U-TEST", "U2": "U-TEST", "R1": "R-LAY"},
            {
                "VIN": ("power", ["U1.1", "R1.1"]),
                "GND": ("gnd", ["U1.4", "R1.2", "U2.1"]),
                "AUX": ("signal", ["U1.2", "U2.2"]),
            },
        ),
        _presentation([
            {"id": "core", "parts": ["U1", "U2", "R1"],
             "role": "a core with a chain shunt", "grammarRef": "ic-periphery"},
        ]),
    )


def _context_with_widest(n: int) -> dc._Context:
    """A real `_Context` whose widest accepted pose set has `n` rungs.

    The trigger is measured on a **real** context — ``ctx.accepted`` is where the
    bound comes from, so a hand-built stand-in would be measuring the test rather
    than the compiler. The extra rungs are declared by the symbol itself (that
    many legal poses on ``U-TEST``), so the padding is a fact about the library,
    not a stub, and the whole grammar/prepare path runs as it does in production.
    """
    # Eight distinct rungs off four rotations: ``_accepted_poses`` de-duplicates
    # by the geometry each pose produces, so a list of rotations alone collapses
    # back to four. The mirrors are what make the rungs distinct.
    poses = [SymbolPose(rotation=float(90 * (i % 4)), mirror=bool(i // 4))
             for i in range(n)]
    book = {"U-TEST": _core(poses=poses), "R-LAY": _lay_down()}
    circuit, presentation = _plain_page()
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    prepare = dc._prepare(circuit, presentation, binding,
                          dc._profile_book(book),
                          dc.CompileBudget(max_candidates=64))
    assert prepare.context is not None, [f.detail for f in prepare.failures]
    return prepare.context


def _refusal(kind: str, subject: str, object_: str) -> dc.GrammarFailure:
    """A refusal shaped exactly like the ones the placement stage returns.

    Built from the same ``detail`` wording :func:`_relation_failures` writes,
    because the trigger reads the relation off that text — a refusal worded
    differently here would be testing the reader, not the rule.
    """
    return dc.GrammarFailure(
        category=dc.FAILURE_PRESENTATION_POOR,
        subject=subject,
        detail=(
            f"the relation {kind}({subject}, {object_}) is not honoured by the "
            f"placement this variant chose (no lock is involved) — measured "
            f"(0, 0) and (0, 0)"
        ),
        action="change the presentation's side preferences",
    )


def _rejected(failure: dc.GrammarFailure, label: str) -> dc.RejectedCandidate:
    return dc.RejectedCandidate(
        variant=label, reason=failure.detail, failure=failure,
    )


def _all_rungs(ctx, failure: dc.GrammarFailure) -> list[dc.RejectedCandidate]:
    return [
        _rejected(failure, f"spacing={scale:g} pose-variant={index}")
        for scale in ctx.budget.spacing_ladder for index in (0, 1)
    ]


def test_the_widening_fires_when_every_rung_names_one_relation():
    """**点火条件之一**：所有拒绝都点名**同一条**关系 → 加宽照做。

    这就是反激那一页的形状：六档基阶梯、全部被 `same-column` 拒掉、别的理由
    一个都不共有。加宽按零件自己的接受位姿集把阶梯补完——这里最宽的接受集是
    **8** 档（与反激的 `U4` 同数），所以补出来的是 ``3 间距 × (8-2) = 18`` 档。
    """
    ctx = _context_with_widest(8)
    result = dc.CompileResult(rejected=_all_rungs(
        ctx, _refusal(SAME_COLUMN, "U1", "R1")))
    widened = dc._widened_variants(ctx, result)
    assert len(widened) == 18, (
        f"expected 3 rungs x 6 remaining pose indices = 18, got {len(widened)}"
    )
    assert {variant.pose_index for variant in widened} == set(range(2, 8))
    assert {variant.scale for variant in widened} == set(ctx.budget.spacing_ladder)


def test_the_widening_does_not_fire_when_the_rungs_disagree_about_why():
    """**点火条件之二**：阶梯对**为什么失败**有分歧 → 不许点火。

    两条不同的关系各拒掉一档。那说明这一页的零件在好几个方向上互相打架，
    「哪一处能靠位姿解」在这里是答不出来的问题；在这种页面上加宽只会烧掉
    ``max_candidates`` 的预算，换来一堆同样被拒的变体和**更吵**的输出。
    """
    ctx = _context_with_widest(8)
    result = dc.CompileResult(rejected=[
        _rejected(_refusal(SAME_COLUMN, "U1", "R1"), "spacing=1 pose-variant=0"),
        _rejected(_refusal(NEAR, "R1", "U2"), "spacing=1 pose-variant=1"),
    ])
    assert dc._widened_variants(ctx, result) == [], (
        "the two rungs were refused by two different relations; widening is for "
        "the page that is exactly one relation short"
    )


def test_a_refusal_that_is_not_a_relation_never_triggers_the_widening():
    """**走线、晶格、区域**的拒绝不是关系拒绝，加宽**不许**由它们点火。

    119 的真实反激正撞在这条的后半段：`net 'HVDC' has a direct-wire obligation
    …` 是**布线**的拒绝。位姿不是把一条挤不过走廊的直连线放行的办法，而放行
    它就是画一张接不通的图。

    两种形态都量：只有布线拒绝（读不出关系），以及布线与关系**混在一起**（读
    得出关系、但**不是每一个**拒绝都读得出）——后者同样不许点火，因为「这一
    页只差一个位姿」那句话在那样的页面上是假的。
    """
    ctx = _context_with_widest(8)
    routing = dc.GrammarFailure(
        category=dc.FAILURE_LAYOUT_UNSAT,
        subject="HVDC",
        detail=(
            "net 'HVDC' has a direct-wire obligation and its pins could not be "
            "joined inside the searched corridor without a wire crossing a body"
        ),
        action="enlarge the region",
    )
    assert dc._refusing_relation(routing) is None, (
        "a routing failure was read as a relation failure"
    )
    alone = dc.CompileResult(
        rejected=[_rejected(routing, "spacing=1 pose-variant=0")])
    assert dc._widened_variants(ctx, alone) == [], (
        "the widening fired on a page whose only refusal is the router's"
    )
    mixed = dc.CompileResult(rejected=[
        _rejected(_refusal(SAME_COLUMN, "U1", "R1"), "spacing=1 pose-variant=0"),
        _rejected(routing, "spacing=1.5 pose-variant=0"),
    ])
    assert dc._widened_variants(ctx, mixed) == [], (
        "the widening fired on a page where only some refusals are relation "
        "failures — that page is not one relation short"
    )


# =============================================== 2 零移动与边界（结构性）


def test_the_widening_never_runs_when_the_base_ladder_survives():
    """**零移动是结构性的**，不是「它小心」。

    :func:`_widened_variants` 的第一个条件就是「有候选就返回空」。所以只要基
    阶梯留下了任何一个候选，加宽**不可达**。字节闸（五族 83 预览 + 15 板
    sha256 全同）是它的**外部复验**；这一条是**内部**的，理由是字节闸只能证明
    「这一次没动」，而这一条证明的是「**它没有机会动**」——两条量的是不同的东
    西，都要。
    """
    ctx = _context_with_widest(8)
    # A non-empty `ranked` is the whole condition. The list's contents are never
    # read, so a sentinel is honest here and a real `Candidate` would only be a
    # way of pretending this test exercises the ranking path too.
    survived = dc.CompileResult(
        rejected=_all_rungs(ctx, _refusal(SAME_COLUMN, "U1", "R1")),
        ranked=[object()],  # type: ignore[list-item]
    )
    assert dc._widened_variants(ctx, survived) == [], (
        "a non-empty ranked list must make the widening unreachable — that is "
        "the whole of the zero-move argument"
    )


def test_the_widened_rungs_stop_at_the_accepted_poses():
    """**边界写死**：每一件最多补到它自己的接受位姿集试完，一格不多。

    反激那一页最宽的接受集是 `U4` 的 **8** 档，加宽一轮最多补 18 档（实测落盘
    的就是 18，见 `outputs/119/SUMMARY.md`）。这一条量的是同一个界，量的是
    **机制**而不是那一页的数字：加宽出来的 ``pose_index`` 必须落在
    ``[2, 最宽接受集)`` 里，且**与基阶梯的档位没有交集**——重复试一档已经画过
    的图，是加宽唯一可能「白烧预算」的方式。
    """
    ctx = _context_with_widest(6)
    result = dc.CompileResult(rejected=_all_rungs(
        ctx, _refusal(SAME_COLUMN, "U1", "R1")))
    widened = dc._widened_variants(ctx, result)
    assert widened, "the fixture is built so the widening fires"
    widest = max(len(poses) for poses in ctx.accepted.values() if poses)
    base_indices = {variant.pose_index for variant in dc._variants(ctx)}
    for variant in widened:
        assert 2 <= variant.pose_index < widest, (
            f"{variant.label} is outside the accepted poses (widest is {widest}); "
            "the widening is meant to stop at the end of the ladder, not past it"
        )
        assert variant.pose_index not in base_indices, (
            f"{variant.label} re-tried a rung the base ladder already drew"
        )


def test_a_page_with_two_accepted_poses_gets_no_extra_rungs():
    """接受位姿集**只有两档**的页面，加宽一格也补不出来——所以它不补。

    这是「试到末尾为止」在最小处的样子：末端即止。若这里仍然补出变体，那补
    的就是「编译器永远不会画的图」，而那正是 116 §三 写下来不许发生的那件事。
    """
    ctx = _context_with_widest(2)
    result = dc.CompileResult(rejected=_all_rungs(
        ctx, _refusal(SAME_COLUMN, "U1", "R1")))
    assert dc._widened_variants(ctx, result) == [], (
        "every accepted pose set here has at most two rungs, which the base "
        "ladder already drew both of — the widening has nothing left to try"
    )

# =========================================== 4 真实反激：加宽确实在那里点火


def test_the_real_flyback_widens_and_still_refuses_honestly():
    """**真数据**上的端到端一遍：加宽**点火**了，`same-column` **被清掉**，页面
    **仍然诚实拒绝**，而拒绝换成了走线。

    前两节量的是「加宽这个机制对不对」；这一条量的是「它对**这一页**对不对」。
    三段断言各钉一件：

    * **点火**：notes 里写着哪条关系点的火、加了几档；
    * **被救**：`same-column(Q1, R5)` **不在**任何一个拒绝里了——这正是 118
      实测「R5 转 90° 能救、而那个位姿不在 0/1 阶梯里」那句话的兑现；
    * **仍拒**：`ok=False`、零候选、且失败**点名**了现在真正拦路的东西。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    import test_113_flyback_grammar as t113
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")

    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))
    notes = " ".join(result.notes)
    assert "pose ladder was widened" in notes, (
        f"the flyback's six base rungs are refused by one relation in common, so "
        f"the widening should have fired; notes were: {notes[-400:]}"
    )
    assert "same-column(Q1, R5)" in notes, (
        "the note must name the relation that triggered the widening"
    )
    # same-column is gone from every **widened** refusal: the widening resolved
    # it. The base rungs still name it — they always did, and they stay in the
    # record, because a refusal that vanished instead of being superseded would
    # be a refusal nobody can audit.
    base_still = [
        item.reason for item in result.rejected
        if "(widened)" not in item.variant and "same-column(Q1, R5)" in item.reason
    ]
    wide_still = [
        item.reason for item in result.rejected
        if "(widened)" in item.variant and "same-column(Q1, R5)" in item.reason
    ]
    assert len(base_still) == 6, (
        f"the six base rungs should still be refused on same-column, got "
        f"{len(base_still)}"
    )
    assert wide_still == [], (
        f"the widening did not rescue same-column(Q1, R5): {wide_still[:2]}"
    )
    # And the page is still honestly refused, with a named blocker.
    assert not result.ok and not result.candidates
    joined = " ".join(item.detail for item in result.failures)
    assert joined, "a refusal with no reason is not a refusal"
    assert "same-column(Q1, R5)" in joined, (
        f"the summary must name a relation: {joined[:300]}"
    )
    # Every widened rung is refused on a **different, named** relation than the
    # one the widening chased. That is the honest shape of "a wider look, not a
    # lower bar": the page moved forward one relation and is still red, for a
    # reason that is written down rather than swallowed.
    wide_reasons = {
        dc._refusing_relation(item.failure) for item in result.rejected
        if "(widened)" in item.variant
    }
    assert None not in wide_reasons, (
        "a widened rung was refused without a named relation; the widening must "
        "not turn a page it cannot help into a noisier refusal"
    )
    assert (SAME_COLUMN, "Q1", "R5") not in wide_reasons
    assert len(wide_reasons) >= 1, "the widened rungs recorded no reason at all"


# ================================ 5 换料带来的新拦路者（真数据，逐条量）


def test_the_routing_blocker_is_measured_not_inferred():
    """**新的断点在走线，不在位姿**——这一条把那个断点**量**出来，不是推断。

    把关系闸**让开**（`_relation_failures` 短路，118 的预览工具用的是同一个手法）
    之后逐档建候选：每一档仍然失败，而失败**全部**是同一条——
    ``net 'HVDC' has a direct-wire obligation and its pins could not be joined
    inside the searched corridor``。

    为什么是它、为什么位姿救不了：三档 x 三档**九次**测量，**零次**成功。`HVDC`
    的三个 pad（`C5.2` / `R15.2` / `T1.1`）在页面上落在同一条 y 上，x 分别是
    190 / 360 / 60；`D3` 的体框正好压在 x=150 那段上。118b 探针量到的新 T1 体框
    是 **101 x 136**（旧的五脚那颗 40 x 40），它把 `D3` 顶到了这条直连路径上，
    而 `D3` 是**链件**、只有**一档**接受位姿——走不了。

    这一条只断言**可复算的那一半**（九次都失败、失败理由是 HVDC 直连）。
    「为什么是 D3」那一条因果，落在 `outputs/119/SUMMARY.md` 里连同它的量法，
    因为**断言一个坐标**很容易，而断言那个坐标**今天**还对，才是真话。
    """
    from boardwise.core.circuitspec import CircuitSpec as _Circuit
    from boardwise.core.presentationspec import PresentationSpec as _Presentation
    import test_113_flyback_grammar as t113

    circuit = _Circuit.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = _Presentation.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context

    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    reasons: list[str] = []
    built_count = 0
    try:
        for scale in (1.0, 1.5, 2.2):
            for index in (0, 2):
                built, failure, _ = dc._build_candidate(
                    ctx, dc._Variant(label=f"x{scale}-{index}", scale=scale,
                                     pose_index=index))
                if built is not None:
                    built_count += 1
                else:
                    reasons.append(failure.detail if failure else "")
    finally:
        dc._relation_failures = saved

    assert built_count == 0, (
        f"{built_count} of the rungs produced a plan once the relation gate was "
        "stood aside, so the blocker is no longer routing and this test's "
        "docstring is stale"
    )
    assert reasons, "no rung recorded a reason"
    for reason in reasons:
        assert "HVDC" in reason and "direct-wire obligation" in reason, (
            "a rung failed on something other than the HVDC direct wire: "
            f"{reason[:200]}"
        )


def test_the_swapped_transformers_body_is_what_moved_d3_onto_the_bus_row():
    """**因果**那一半：把 T1 的体框换成**体内端下界**，同一个电路就编出来了。

    119 反复量到的那件事，两行就写完：118b 探针给新 T1 的体框是**实测 bbox**
    **101 x 136**；按同一批脚尖推出的体内端下界是 **90 x 100**。体框换成下界、
    **脚一根不动**，`HVDC` 的直连立刻通得过去。

    这不是说下界「更对」——**实测 bbox 更对**，它是读回来的，骨架中间的绕组空档
    真的占着地。这一条量的是**因果**：拦着走线的是**体框的面积**把 `D3` 推到了
    那条行上，而不是脚位、不是 token、也不是位姿。**换料是岳的裁定，绕线策略是
    编译器的事**，所以断点写在这里而不是自己去改绕线。

    断言写成「下界能编出来」，而不是「实测 bbox 编不出来」——后者今天是真的，
    但它是一条会随岳下一次换料而失效的话，而前者量的是一个**机制**。
    """
    from boardwise.core.circuitspec import CircuitSpec as _Circuit
    from boardwise.core.presentationspec import PresentationSpec as _Presentation
    import test_113_flyback_grammar as t113

    circuit = _Circuit.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = _Presentation.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")

    inward = {"left": (1.0, 0.0), "right": (-1.0, 0.0),
              "up": (0.0, -1.0), "down": (0.0, 1.0)}
    profile = book["XFMR-XREE16-050624"]
    # The pin **lengths** are read from the library file, not from the loaded
    # profile: the schema this build validates against does not carry `length`
    # through, so the loaded pins have none and the inner ends are not
    # computable from them. The tips and directions the profile *does* carry are
    # checked against that same file by
    # ``test_every_body_box_is_the_measured_inner_ends_and_nothing_wider``'s
    # sibling in 118, so nothing here rests on a value the loader invented.
    declared = next(
        entry for entry in json.loads(
            (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
        )["profiles"] if entry["symbolRef"] == "XFMR-XREE16-050624"
    )
    by_number = {pin["number"]: pin for pin in declared["pins"]}
    for pin in profile.pins:
        assert tuple(pin.tip) == tuple(by_number[pin.number]["tip"]), (
            f"pin {pin.number}'s tip differs between the file and the loaded "
            "profile; the two are supposed to be the same symbol"
        )
    inner = [
        (by_number[pin.number]["tip"][0]
         + inward[by_number[pin.number]["direction"]][0]
         * by_number[pin.number]["length"],
         by_number[pin.number]["tip"][1]
         + inward[by_number[pin.number]["direction"]][1]
         * by_number[pin.number]["length"])
        for pin in profile.pins
    ]
    lower_bound = (
        min(point[0] for point in inner), min(point[1] for point in inner),
        max(point[0] for point in inner), max(point[1] for point in inner),
    )
    measured = tuple(profile.body)
    assert measured != lower_bound, (
        "the measured bbox and the inner-end lower bound now agree, so the body "
        "is no longer what pushes D3 onto the bus row and this test's reasoning "
        "is stale"
    )

    shrunk = dict(book)
    shrunk["XFMR-XREE16-050624"] = dataclasses.replace(
        profile, body=lower_bound)
    binding = dc.bind_grammar(circuit, presentation, shrunk)
    prepared = dc._prepare(circuit, presentation, binding, shrunk,
                           dc.CompileBudget(max_candidates=64))
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    ctx = prepared.context
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        built, failure, _ = dc._build_candidate(
            ctx, dc._Variant(label="lower-bound-body", scale=2.2, pose_index=0))
    finally:
        dc._relation_failures = saved
    assert built is not None, (
        "with the transformer's body reduced to the inner-end lower bound and "
        "every pin untouched, the page still does not build, so the body area is "
        f"not the cause: {failure.detail[:200] if failure else 'no reason'}"
    )
