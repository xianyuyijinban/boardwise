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

import pytest

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

# ======================= 4 真实反激：520A2 之后加宽**不再**点火（前提没了）


def test_the_real_flyback_widens_and_still_refuses_honestly():
    """**真数据**上的端到端一遍——**520A2 重钉**：加宽**不再点火**，页面仍然诚实
    拒绝，而拒绝现在停在**布线**层。

    函数名是 119 时代的历史名字，留着是为了 node id 稳定；它现在钉的是反面：
    加宽**不许**悄悄点火。

    **改动前的读数**（119 写这条时的世界）：六个基础档**全部**被**同一条**
    `same-column(Q1, R5)` 拒掉 → 加宽点火、补 18 档（3 间距 × 6 剩余位姿）、
    `same-column` 被清掉、页面仍拒且摘要点名 `same-column`。

    **改动后的读数（520A2）**：链件可沿**横跨链**的方向 walk，六档的拒绝**不再
    同因**——实测 2 档过关系闸、死在布线（`net 'HVDC'` / `net 'SEC_12V'` 的
    `direct-wire obligation`），4 档各点名一条不同的关系（`left-of(R8, U4)`、
    `right-of(C10, U5)`、`near(C13, T1)`）。加宽的条件正是「每一条拒绝都点名
    同一条关系」，它现在**不成立**，于是 `_widened_variants` 返回 `[]`、一档
    都不补。这不是覆盖丢失：机制本身仍由本文件上半段的合成单测钉着。

    **520E 的读数**：那 2 档也过了布线层——连不上的直连义务现在被**降级成名字并
    记账**（`label_fallbacks` = `HVDC`、`SEC_12V`），2 档改死在**可读性闸**
    （`13` / `14` 条硬违反），另外 4 档仍各点名一条关系——所以「不同因」这个读数
    **没变**，变的是那 2 档的**去处**。加宽依旧不点火，理由依旧成立。

    **535 的读数（2026-10-23，实测驱动）**：那 2 档的**去处又换了一层**。第二层
    修复（530A：地/电源一律旗标）让连不上的 `SEC_GND` 走**旗标**降级，而这页的
    `SEC_GND` 一面旗标都挂不上（席位阶梯四个方向全被占），于是 2 档停在 **069
    sec.1 的旗标席位阶梯**自己的那句话上；降级账本从两条变成**三条**
    （`HVDC`、`SEC_12V`、`SEC_GND`），真载入器下 `named` 另加 `FB_SENSE`
    （531 的事）。「6 档、其中 2 档过关系闸、其余 4 档各点名一条关系、加宽不点火」
    这些读数**一条没变**——变的是那 2 档死在**哪一层**，以及地进了降级名单。
    这也**不是**把一条闸放宽：这 2 档在 520E 下也是被拒的，535 之后同样被拒，
    只是拒绝的人从可读性闸换成了「地自己的旗标挂不上」。

    前两节量的是「加宽这个机制对不对」；这一条量的是「它对**这一页**现在对不对」。

    **530F 重钉（改账簿，按任务书工作项 2）**：反激这份**文档**在 520m 之后声明了
    `islands`，于是它编译走的是**岛路**（`drawcompiler.compile` 的
    `multi_island`）。岛路上加宽轮**结构上不存在**——那一页由构造只有一个图，
    没有链可以重新摆姿态——所以「这一页有没有点火」在岛路上问的是一个**没有
    执行者**的问题。这一条于是改成钉**岛路实际形态**：这份文档编译出来是什么，
    以及它**没有**阶梯的痕迹。加宽对这个文档的历史读数（不点火 / 6 档基阶梯 /
    2 档过关系闸死在旗标席位阶梯 / 其余 4 档各点名一条关系）一条都没丢——它们搬到
    紧邻的 `test_the_single_module_flyback_still_shows_the_widening_reading`，
    用**剥掉 islands 的同一份文档**量。病历不许伪造，但也得量在真跑的那条路上。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    # 岛路那半用**产品的那把尺子**（`SymbolProfile.from_dict`，与
    # `draw compile --profiles` 同源）：手搓 loader 丢掉 `$.texts` 与引脚
    # `length`，量出来的岛页不是 `draw compile` 会画的那一张（530C/530D 记过
    # 这件事）。加宽那半继续用 119 时代的手搓尺子，因为它的历史读数就是那把尺子
    # 量出来的——两半各用各的，理由写在各自那一行上。
    import test_551a_failure_rounds as t551a
    book = t551a._flyback_library_real()

    result = dc.compile(circuit, presentation, book,
                        dc.CompileBudget(max_candidates=64))
    notes = " ".join(result.notes)
    # 1) 岛路上没有阶梯，也就没有加宽——两种说法都是同一个结构事实的两面。
    assert "pose ladder was widened" not in notes, (
        "the widening fired on a document that declares islands: the island page "
        "has one drawing by construction and no chain to re-pose, so a note about "
        f"a ladder here means the page left the island path — notes: {notes[-400:]}"
    )
    assert "constructive variant" not in notes, (
        "the island page builds no constructive ladder at all; a rung count here "
        f"means the single-module path ran — notes: {notes[-400:]}"
    )
    assert any("island" in note.lower() for note in result.notes), (
        f"the page must say it is a page of islands — notes: {notes[-400:]}"
    )
    # 2) 这份文档在岛路上的实际判决：delivered（530F 的交付口径）。
    #    **531 重钉**：530F 时这一页交付时带**一条**被点名容忍的主机行
    #    （`LED_K` 的名字行压 `R7`）；531 把 `R7` 挪开了，所以容忍账现在是**空**的
    #    —— 交付与否（本测试真正的主语）没变，变的是账本。
    assert result.ok and result.candidates, (
        "the island page must be delivered under 530F's gate policy; a refusal "
        f"here means the policy or the page moved — failures: "
        f"{[item.detail[:200] for item in result.failures]}"
    )
    # **532 重钉**：账本又变了，而这一次变的是**哪一类**行。532 之前这条断言写的是
    # 「账本是空的」（531 把 `R7` 挪开，`LED_K` 的名字行不再压件）；现在这一页带
    # **三**条被点名的容忍行，全部是变压器自己的引脚文字（`T1` 的 `2`/`5`）压在
    # `T1` 自己的值行上——`readability` 在这批之前**根本看不见**引脚名/号
    # （`textmetrics.pin_rows` / `KIND_PIN_TEXT_PRESSED`）。交付与否（本测试真正
    # 的主语）仍然没变：`ok=True`、1 候选。
    # **201H 重钉**：账本又空了，而这次变的是**值行本身**。S-21 的第一出路把
    # 变压器值行藏掉——它压在自己的引脚名/号上，两行同属一个符号，任何摆位都
    # 分不开（`islandlayout._clear_text_rows` 的 own-pin 半边），那三条
    # `pin-text-press` 随之消失。交付与否（本测试真正的主语）没变：`ok=True`、
    # 1 候选；532 的 cap=3 也没动，只是账上没有行可记。
    tolerated = [note for note in result.notes if note.startswith("tolerated: ")]
    assert tolerated == [], (
        "201H: the transformer's value row is hidden by S-21's first way out, so "
        f"this page delivers with an empty account: {tolerated}"
    )
    # 3) 单模块那条路（同一个模块、剥掉 islands）仍按老读数跑。
    _assert_single_module_widening_reading(
        circuit, presentation, book,
        named=("HVDC", "SEC_12V", "SEC_GND", "FB_SENSE"),
    )


#: 069 sec.1's own words when a ground's flag has nowhere to go.  It is the layer
#: the rungs that get past the relation gate stop on since 535 (530A: an unjoinable
#: ground is expressed by a flag, and a pad whose flag nobody could hang is refused
#: rather than drawn on top of the wiring).
FLAG_LADDER_PHRASE = "is named by a flag of its own"


def _assert_single_module_widening_reading(
    circuit, presentation, book, *, named: tuple[str, ...] = ("HVDC", "SEC_12V", "SEC_GND"),
) -> None:
    """119 的历史读数，量在**它真正会跑的那条路**上（530F 剥岛夹具）。

    Extracted so both the re-pinned test above and the standalone one below read
    the same numbers: the widening's trigger is gone, six base rungs are built, two
    of them get past the relation gate and die at the ground's own flag-seat ladder
    (:data:`FLAG_LADDER_PHRASE`) with the downgraded nets beside them, and the other
    four each name a relation of their own.  Nothing here was re-measured — it is the
    same page measured where the ladder actually runs.

    ``named`` is the one number the two callers do **not** share, and 531 is why:
    this test's own hand-made library has no `$.texts`, so nothing about its routing
    changed, while the caller that hands the **real** profile book
    (`SymbolProfile.from_dict`, table above) now measures the rows the host really
    prints and cannot join a second long wire (`FB_SENSE`).  A caller states which
    book it is measuring rather than one expectation being loosened for both — and
    the parameter is called ``named`` rather than ``downgraded`` because the body
    already computes a ``downgraded`` of its own from the rungs' own fallbacks.

    **535 (2026-10-23)**: the rung-level reading moved a layer (the ground's flag
    ladder, not the readability gate) and both books' ``named`` grew `SEC_GND` —
    the unjoinable ground, which 530A expresses as a flag and only as a flag.  The
    numbers are in the callers' own docstrings.
    """
    single = dataclasses.replace(presentation, islands=None)
    result = dc.compile(circuit, single, book, dc.CompileBudget(max_candidates=64))
    notes = " ".join(result.notes)
    # 1) 不点火，且 notes 说清基础阶梯建了几档。
    assert "pose ladder was widened" not in notes, (
        "the widening fired on the flyback again: under 520A2 the six base rungs "
        "no longer agree on one relation, which is exactly the widening's "
        f"precondition, so it must not run — notes: {notes[-400:]}"
    )
    assert "6 constructive variant" in notes, (
        "the notes must say how many constructive rungs were built and refused; "
        f"a different count means the ladder was re-pinned — {notes[-400:]}"
    )

    base = [
        item for item in result.rejected
        if "(widened)" not in item.variant and item.variant != "topology-search"
    ]
    assert len(base) == 6, (
        f"the base ladder is 6 rungs under 520A2 (24 before it), got {len(base)}"
    )
    assert not [item for item in result.rejected if "(widened)" in item.variant], (
        "a widened rung was built even though the widening's precondition (every "
        "refusal names the same relation) no longer holds — re-measure"
    )

    # 2) 前提消失，按实测的两种去处量：过关系闸 / 各点名一条关系。
    #
    # **520E 重钉**：过关系闸的那两档现在死在**可读性闸**（不再是布线的直连
    # 义务——那条义务连不上时被降级成名字了）。所以这里量的是「两档过关系闸、
    # 死在闸上」，且它们就是**记账降级**的那两档：把降级与「过关系闸」绑在一起
    # 才是本批的断言，只数「2 档死在闸上」会漏掉降级悄悄消失这种情况。
    #
    # **535 重钉（2026-10-23，实测驱动）**：那两档的**去处又换了一层**——第二层
    # 修复（530A：地/电源一律旗标）让连不上的 `SEC_GND` 走 `_label_fallback` 的
    # **旗标**分支，而这页的 `SEC_GND` 一面旗标都挂不上（`_seat_wire_flags` 的
    # 席位阶梯四个方向全被占），于是两档死在 **069 sec.1 的旗标席位阶梯**自己的
    # 那句话上。断言的**主语没变**（「过关系闸的那两档 = 记账降级的那两档」），
    # 换的是「它们死在哪一层」和降级账本上多出来的那条 `SEC_GND`。
    past_the_relation_gate = [
        item for item in base if FLAG_LADDER_PHRASE in item.reason
    ]
    assert len(past_the_relation_gate) == 2, (
        "520A2 measured two of the six base rungs passing the relation gate; under "
        f"535 both die at the ground's own flag-seat ladder; got "
        f"{len(past_the_relation_gate)} — re-measure before trusting the rest of "
        "this test"
    )
    assert sorted(
        {item.variant for item in past_the_relation_gate}
    ) == ["spacing=1 pose-variant=0", "spacing=1.5 pose-variant=0"]
    downgraded = sorted(
        {fb.net for item in past_the_relation_gate for fb in item.label_fallbacks}
    )
    assert downgraded == ["HVDC", "SEC_12V", "SEC_GND"], (
        "the two rungs that get past the relation gate are the ones the router "
        "cannot wire — and 520E names those nets instead, including since 535 the "
        f"unjoinable ground: {downgraded}"
    )
    relations = {
        dc._refusing_relation(item.failure) for item in base
        if dc._refusing_relation(item.failure) is not None
    }
    assert len(relations) >= 3, (
        "the base rungs agreeing on a single relation is the widening's trigger "
        "coming back — the refusals named relations "
        f"{sorted(relations)} (expected at least left-of(R8, U4), "
        "right-of(C10, U5), near(C13, T1))"
    )

    # 3) 页面仍被诚实拒绝，且摘要点名**现在**真正拦路的那一层。
    #
    # **535 重钉**：摘要第一条 = 最小档（`spacing=1 pose-variant=0`）的拒因，
    # 也就是 069 sec.1 旗标席位阶梯那句（520E 时这里是可读性闸）。降级那一句
    # 仍然**追加**在同一段拒绝里（而且现在点三条网）——这就是本批那两个断言：
    # 「拒绝换了层」与「降级真的被记了」是两件事。
    assert not result.ok and not result.candidates
    joined = " ".join(item.detail for item in result.failures)
    assert joined, "a refusal with no reason is not a refusal"
    assert FLAG_LADDER_PHRASE in joined and "069 sec.1" in joined, (
        "the summary must name the layer the page now stops on (535 moved it from "
        f"the readability gate to the ground's own flag-seat ladder): {joined[:300]}"
    )
    assert "the name had nowhere to go either" in joined, (
        "and the downgrade clause must still be appended to that refusal, not "
        f"replaced by it: {joined[:400]}"
    )
    assert [item.net for item in result.label_fallbacks] == list(named), (
        "and the page's own account of what it named instead must be visible "
        f"beside it: {[f.net for f in result.label_fallbacks]}"
    )


def test_the_single_module_flyback_still_shows_the_widening_reading():
    """530F: 119 的历史读数量在**加宽真的会跑的那条路**上（剥岛夹具）。

    See `DESIGN` §9.3: the widening's guard lives behind
    `drawcompiler.compile`'s ``if not multi_island:``, so a flyback that declares
    islands never reaches it.  Taking the declaration off the fixture — and not
    adding a compiler switch, which would give the product a branch that exists for
    tests only — is what keeps this measurement a measurement.  The numbers are
    `_assert_single_module_widening_reading`'s; this test exists separately so the
    reading is still named in `pytest -v` after the re-pin above.  It is the one
    caller on 119's **hand-made** library (the caller above hands the real book),
    so its ``named`` is the three-net set — `HVDC`, `SEC_12V` and, since 535, the
    unjoinable ground `SEC_GND`; the real book adds `FB_SENSE` (531).
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    import test_113_flyback_grammar as t113
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    _assert_single_module_widening_reading(circuit, presentation, book)


# ================================ 5 换料带来的新拦路者（真数据，逐条量）


# ================================ 5 119 的断点，作为**记录**保留（120 换料之后）


def _xree_era() -> bool:
    """Is the page still on 119's seven-pin XREE part?

    120 换了料（WE 749118105，六脚两绕组），所以这个文件最后两条**量的是
    119 那一页**，不再是当前这一页。它们不删——删掉等于把 119 挖出来的病从
    记录里擦掉，而那正是 118 当年不肯做的事——而是**先问一句现在是不是那一页**：
    不是的话就 `skip`，并把「119 量到了什么、120 换料后它变成什么」写进 skip
    的理由里，让缺口在 `pytest -rs` 里看得见。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    ref = next(part.symbol_ref for part in circuit.parts if part.id == "T1")
    return ref == "XFMR-XREE16-050624"


def _skip_if_not_xree() -> None:
    if _xree_era():
        return
    pytest.skip(
        "119 record: this measurement was taken on the seven-pin XREE16-050624 "
        "(C49118510) that 119 put on the page. 120 replaced it with WE 749118105 "
        "(C17189451, six pins, two windings) — 岳's call, and the page it "
        "compiles is not the page this file measured. 119's finding is kept "
        "here as a record rather than deleted: on the XREE part the 24 rungs "
        "(3 spacings x 8 pose indices) ALL failed with both gates stood aside, "
        "every one of them on `net 'HVDC' has a direct-wire obligation`, because "
        "that part's measured body was 101x136 and it pushed the chain's D3 onto "
        "the direct path between HVDC's three pads. On the WE part the body is "
        "41x44 and 120 measured a different set of blockers (see "
        "tests/test_120_island_placement.py and outputs/120/SUMMARY.md). The "
        "number below is therefore a statement about a part that is no longer on "
        "the page — which is exactly what a record is."
    )


def test_the_routing_blocker_is_measured_not_inferred():
    """**119 的断点，作为记录**：XREE 那颗料下，24 档全灭于 `HVDC` 直连。

    量法（当时）：把关系闸**让开**（`_relation_failures` 短路，118 的预览工具用的是
    同一个手法）之后逐档建候选——3 间距 × 8 位姿 = 24 档，**零次**成功，理由**全部**
    是 `net 'HVDC' has a direct-wire obligation and its pins could not be joined
    inside the searched corridor`。

    **120 更新**：这一页已经换料，所以这条**先问是不是 119 那一页**。不是就 skip，
    并把当时量到的东西整段写进理由——不删，是因为删掉一条测过的断点，和把一条没
    测过的断点写成结论，是同一种谎。
    """
    _skip_if_not_xree()
    from boardwise.core.presentationspec import PresentationSpec
    import test_113_flyback_grammar as t113

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
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
        for scale in ctx.budget.spacing_ladder:
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
    """**119 的因果，作为记录**：XREE 的体框把 `D3` 顶到了 `HVDC` 那一行。

    两行就写完 119 反复量到的那件事：118b 探针给 XREE 的体框是**实测 bbox**
    **101 × 136**；按同一批脚尖推出的体内端下界是 **90 × 100**。体框换成下界、
    **脚一根不动**，`HVDC` 的直连立刻通得过去。

    **120 更新**：同 119 的换料。WE 那颗的体框是 41 × 44，比 119 那颗小得多，
    而 120 在它上面量到的病是**别的**两条（孤岛落子把支路按 `lane*scale*(1+i)`
    推出 `near` 半径、钳位串被松弛趟叠到一行）。所以这条同样先问是不是 119 那一页。
    """
    _skip_if_not_xree()
    from boardwise.core.presentationspec import PresentationSpec
    import test_113_flyback_grammar as t113

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")

    inward = {"left": (1.0, 0.0), "right": (-1.0, 0.0),
              "up": (0.0, -1.0), "down": (0.0, 1.0)}
    profile = book["XFMR-XREE16-050624"]
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
        (
            by_number[pin.number]["tip"][0]
            + inward[by_number[pin.number]["direction"]][0]
            * by_number[pin.number]["length"],
            by_number[pin.number]["tip"][1]
            + inward[by_number[pin.number]["direction"]][1]
            * by_number[pin.number]["length"],
        )
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
