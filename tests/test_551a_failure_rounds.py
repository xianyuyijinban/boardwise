"""551A：零候选报告的分轮失败——拓扑轮的拒因不许被阶梯的第一条遮住。

============================ 病 ============================

`_no_candidate_failures` 只把 ``result.rejected`` 里**第一个**带 failure 的变体
端上 ``failures``。反激（去锁 presentation）实测：阶梯的 14 个变体全被
`same-column(Q1, R5)` 拒，随后拓扑搜索被 `net 'SEC_12V' … rail drawn as a wire`
拒——报告只有 `same-column`，拓扑轮那条**完全不可见**。岳点过这是「一个结论
多个出口」的同族毛病，这次被遮住的是**失败原因**。

============================ 治 ============================

``failures`` 是**摘要**（第一条拒因，所有既有消费方的读法）——一个字不改。
旁边加 ``failure_rounds``：每个搜索轮（base / widened / topology）自己的**第一条**
拒因，按编译器到达各轮的顺序排。``summarize_failure_rounds()`` 把它渲染成
``{round, category, detail}`` 字典列表给报告读；手工构造的 result（没有
rounds）回退到摘要 failures 本身，每个记 ``round="first"``——旧形状可复现。

本文件钉四件事：

1. **形状**（纯数据层）：round 词表、非法 round 拒收、``_variant_round`` 的标签
   判读、``summarize_failure_rounds`` 的两条路径；
2. **装配**（单测 `_failure_rounds` 对一个真实 rejected 列表）：每轮一条、按
   轮序、乱序的 rejected 也不影响轮序；
3. **端到端**（真数据，反激整页）：``failures`` 仍只有**第一条**（向后兼容钉），
   ``failure_rounds`` **两轮**齐、每轮点名自己那条——**拓扑轮的 rail 拒因在列表里**。
   （520A2 之前是三轮；加宽轮的前提被那批改动修掉之后它不点火，所以这一页现在
   只跑 base + topology。见该测试自己的 docstring。）
4. **CLI 合同**：``draw compile --json-path`` 的载荷带 ``failureRounds``，
   摘要 ``failures`` 键的形状不变。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines.grammar.base import GrammarFailure

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


# ---------------------------------------------------------------- 1 形状层


def _failure(detail: str, category: str = dc.FAILURE_LAYOUT_UNSAT) -> GrammarFailure:
    return GrammarFailure(category=category, detail=detail)


def test_failure_round_names_are_the_three_search_rounds():
    """551A 的轮词表只有编译器真的会跑的三轮，再没有一个能被手拼进来。"""
    assert dc.FAILURE_ROUNDS == ("base", "widened", "topology")
    for name in dc.FAILURE_ROUNDS:
        dc.FailureRound(round=name, failure=_failure("x"))
    with pytest.raises(dc.CompileError):
        dc.FailureRound(round="bogus", failure=_failure("x"))


def test_variant_round_reads_the_labels_the_compiler_writes():
    """标签判读：201B 的 topology-search、119 的 (widened)、053 的裸阶梯。

    一个不认识任何轮的标签落在 base——和每条阶梯档位同一个缺省，而不是被猜。
    """
    assert dc._variant_round("topology-search") == "topology"
    assert dc._variant_round("spacing=1 pose-variant=2 (widened)") == "widened"
    assert dc._variant_round("spacing=2.2 pose-variant=1") == "base"
    assert dc._variant_round("hand-built") == "base"


def test_summarize_failure_rounds_falls_back_to_the_summary_failures():
    """手工构造的 result（无 rounds）回退到 failures 本身——旧形状可复现。"""
    first = _failure("the first refusal", dc.FAILURE_PRESENTATION_POOR)
    result = dc.CompileResult(failures=[first, _failure("the second")])
    assert result.summarize_failure_rounds() == [
        {"round": "first", "category": first.category, "detail": first.detail},
        {"round": "first", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "the second"},
    ]


def test_summarize_failure_rounds_renders_the_rounds_when_present():
    """rounds 在场时是报告要的 {round, category, detail}，不是别的。"""
    result = dc.CompileResult(failure_rounds=[
        dc.FailureRound(round="base", failure=_failure("ladder reason")),
        dc.FailureRound(round="topology", failure=_failure("search reason")),
    ])
    assert result.summarize_failure_rounds() == [
        {"round": "base", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "ladder reason"},
        {"round": "topology", "category": dc.FAILURE_LAYOUT_UNSAT,
         "detail": "search reason"},
    ]


# ---------------------------------------------------------------- 2 装配层


def test_failure_rounds_take_the_first_refusal_of_each_round_in_round_order():
    """每个轮取它**第一条**拒因；rejected 乱序不改变轮序。

    rejected 是一条扁平的追加日志（阶梯档位 → 加宽档位 → 拓扑，按发生顺序），
    所以同一轮的第二条拒因被跳过，三轮的顺序由 FAILURE_ROUNDS 定而不是由
    rejected 的出现顺序定。
    """
    rejected = [
        # widened first in the list — the round order must not follow it
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=2 (widened)",
            reason="widened reason", failure=_failure("widened reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=3 (widened)",
            reason="second widened", failure=_failure("second widened"),
        ),
        dc.RejectedCandidate(
            variant="topology-search",
            reason="search reason", failure=_failure("search reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=0",
            reason="ladder reason", failure=_failure("ladder reason"),
        ),
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=1",
            reason="second ladder", failure=_failure("second ladder"),
        ),
        # a variant with no failure of its own (same-geometry rejections) is
        # not a round's answer and names no round
        dc.RejectedCandidate(
            variant="spacing=1.5 pose-variant=0",
            reason="the same geometry as an earlier variant",
        ),
    ]
    result = dc.CompileResult(rejected=rejected)
    rounds = dc._failure_rounds(result)
    assert [(item.round, item.failure.detail) for item in rounds] == [
        ("base", "ladder reason"),
        ("widened", "widened reason"),
        ("topology", "search reason"),
    ]


def test_a_round_with_no_recorded_refusal_is_absent_not_invented():
    """没有 failure 的轮不出场——列表里每一条都是读者还没被给过的原因。"""
    result = dc.CompileResult(rejected=[
        dc.RejectedCandidate(
            variant="spacing=1 pose-variant=0", reason="x",
            failure=_failure("ladder reason"),
        ),
        dc.RejectedCandidate(
            variant="topology-search", reason="y",
        ),
    ])
    rounds = dc._failure_rounds(result)
    assert [item.round for item in rounds] == ["base"]


# ---------------------------------------------------------------- 3 端到端


def _flyback_library() -> dict:
    import test_113_flyback_grammar as t113
    return t113._library_from(SPECS / "flyback_uc3845.library.json")


def _single_module(spec: PresentationSpec) -> PresentationSpec:
    """The same document with `islands` taken off — `DESIGN` §9.3's fixture swap.

    551A's subject is the **rounds** a zero-candidate report can name.  Since 520m,
    a presentation that declares islands compiles through `_try_island_variants`,
    where neither the ladder nor the widening nor the topology round runs at all
    (`drawcompiler.compile`'s `if not multi_island:`): the island page has one
    drawing by construction and no chain to re-pose.  Measuring "which rounds are
    visible" on that page measures rounds that structurally do not happen.  Taking
    the declaration off the fixture — and not adding a compiler switch, which would
    give the product a branch that exists for tests only — puts the document back
    on the path these assertions are about.
    """
    import dataclasses
    return dataclasses.replace(spec, islands=None)


def _flyback_library_real() -> dict:
    """**产品路径的那把尺子**：`SymbolProfile.from_dict`，与 `draw compile --profiles` 同源。

    520C 抓到过一件事：`test_113._library_from` 是**手搓** `SymbolProfile(...)`，
    它丢掉了 `$.texts`（19 个 profile 里 13 个有文字锚点）、每颗引脚的 `length`
    （36/36 都有）**和 `$.poses`**（520D 给 T1 声明的四旋转、不许镜像）。用那把
    尺子量出来的反激判决跟 `draw compile` **不一样**：手搓尺子下 T1 还有 8 个
    姿态、拓扑轮死在另一处，真尺子下 T1 只剩 4 个不镜像的旋转。本测试量的是
    「哪几轮的拒因对读者可见」，那是产品契约，所以这里用真尺子。
    **手搓 loader 是已知债，另立题。**
    """
    payload = json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
    )
    return {
        entry["symbolRef"]: SymbolProfile.from_dict(entry)
        for entry in payload["profiles"]
    }



def test_the_topology_refusal_is_visible_beside_the_ladder_refusal():
    """**551A 的正题**：阶梯被 A 拒、拓扑被 B 拒——两条原因都在列表里。

    **520A2 重钉**：反激整页（去锁 presentation，120 后的形态）的拒因链**少了一轮**。

    * **改动前**（551A 写这条时的世界）：三轮——阶梯 6 档全被
      `same-column(Q1, R5)` 拒 → 加宽轮被 `right-of(D3, T1)` 拒 → 拓扑轮被
      `net 'SEC_12V' … rail drawn as a wire` 拒。
    * **改动后（520A2）**：**两轮**——`base`（`net 'HVDC' … direct-wire
      obligation`）+ `topology`（`net 'SEC_12V' …`）。加宽轮**不再存在**：它的
      前提「六个基础档的每一条拒绝都点名同一条关系」被本次改动修掉了（现在
      2 档过关系闸、死在布线，4 档各点名一条不同的关系）。
    * **再改（520B2，尺子换成真的才量得出来）**：拓扑轮**不再死在旗标层**——
      rail 席位阶梯放宽成「供电脚优先 → 本网其余脚、就近优先」之后，`SEC_12V`
      的旗标落在 `R7.1`（lead `((75,140),(45,140),(45,127.5))`，总长 42.5）。
      但**用真载入器**（`SymbolProfile.from_dict`，与 `draw compile --profiles`
      同源）量，这一轮死在**关系闸** `right-of(C11, T1)`（"not honoured by
      the shape of T1's own symbol — T1.6 on net SEC_GND"），可读性闸仍未跑。
      **手搓 loader 下曾经读到「走到可读性闸、24 条违反」，那是坏尺子的读数**：
      `test_113._library_from` 手搓 `SymbolProfile(...)`，丢掉 `$.texts`
      （19 个里 13 个有）和每颗引脚的 `length`（36/36 有）。本测试从 520B2 起
      改用真尺子，因为「哪几轮的拒因对读者可见」是**产品契约**。
    * **再改（520D）**：那条关系拒因是**姿态病不是形状病**。拓扑搜索给 T1 选了
      镜像姿态，副边 4/5/6 从 `(+40,·)` 翻到 `(-40,·)`，T1.6 于是落在 origin
      左边；而 T1 在**未镜像**的姿态下满足这条关系。520D 把
      `XFMR-WE-749118105` 的 `poses` 声明成「四旋转、`mirror=false`」——那个
      姿态**不再被提供**，不是在闸口被拒。**旧数字**：`right-of(C11, T1)` 消失，
      拓扑轮走到**可读性闸**，`34` 条硬违反
      （`wire-on-pin-line` 4 + `text-overlap` 29 + `text-on-wire` 1），归口
      从 `presentation-poor` 变成 `layout-unsat`。`ok`/`candidates`/`rejected`
      与轮集合都没变（`False`/`0`/`7`，`base`+`topology`）。
    * **再改（520G）**：`_pin_walls` 把引线方向当符号自己的坐标读，转过姿态的
      引脚**一条引线都没预留**，于是 `wire-on-pin-line` 有 4 条可拒。520G 换成
      pose 之后的方向，这一轮从 `4 + 29 + 1` 变成 `26 + 3` = **29** 条，那一类
      归零（下面既有新条数、也有「一条都不许再有」的不变量两条断言）。
    * **再改（534 r22，本测试现在的形状）**：终局重落座 `_reseat_crossed_labels` 在
      **全页导体铺完**之后、可读性闸**之前**跑：把被外网导线穿过的 label box 沿自己的
      16 档梯子重落座，铺不满就按「有限梯子是拒绝不是许可」具名拒绝。此页拓扑轮的
      `CLAMP`（anchor `(60, 180)`）逐档无座——另两枚 `CLAMP` 载体、`C11`/`100nF 0603`
      的文字盒与器件体占住其余方向，独剩的方向又被 `HVDC` 整高穿过（chord 9）——于是
      这一轮在**重落座**处拒绝（subject `labels[9]`），`violations` 为空。**这不是闸没拒，
      是闸没跑**：换层前后的画面摘要逐字相同（`1b3031e27f33bf54`，A/B 见
      `test_the_reseat_layer_does_not_hide_the_readability_rows`），被测的仍是同一张图，
      换的只是先开口的那个人。

    轮词表本身仍是三轮（`FAILURE_ROUNDS`，由本文件形状层的
    `test_failure_round_names_are_the_three_search_rounds` 钉着）——这里量的是
    **这一页实际跑到哪几轮**。旧报告只显示第一条；现在 ``failure_rounds``
    两轮齐，且拓扑轮那条**逐字可见**。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = _single_module(
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    )
    result = dc.compile(
        circuit, presentation, _flyback_library_real(),
        dc.CompileBudget(max_candidates=64),
    )
    assert not result.ok and not result.candidates

    # 向后兼容钉：摘要 failures 还是**第一条**——但第一条又换了一层。
    # 520A2 那版这里是「走线的直连义务」；**520E 之后那一层不存在了**：
    # 连不上的直连义务被降级成名字并记账，于是第一条是 `base` 轮自己的拒因，
    # 并且带着降级那一句。断言按新事实写，同时钉住 520E 自己的账本——「拒绝换了
    # 层」与「降级真的被记了」是两件事。
    #
    # **535 重钉（2026-10-23，实测驱动）**：`base` 轮的拒因又换了一层——第二层
    # 修复（530A：地/电源一律旗标）让连不上的 `SEC_GND` 走**旗标**降级，而这页的
    # `SEC_GND` 一面旗标都挂不上（`_seat_wire_flags` 的席位阶梯四个方向全被占），
    # 于是第一条是 **069 sec.1 旗标席位阶梯**自己的那句话（520E 时这里是可读性闸）。
    # 页面照旧被诚实拒绝，降级从句照旧追加在后——只是拒绝的人换了。
    assert len(result.failures) == 1
    assert "is named by a flag of its own" in result.failures[0].detail and (
        "069 sec.1" in result.failures[0].detail
    ), (
        "the summary failures still lead with the **first** refusal; since 535 "
        "that refusal is the ground's own flag-seat ladder "
        f"(069 sec.1) — {result.failures[0].detail[:200]}"
    )
    assert "the name had nowhere to go either" in result.failures[0].detail, (
        "a refusal that follows a downgrade owes both halves: "
        f"{result.failures[0].detail[:400]}"
    )
    # **531 重钉**: the account grew a third net, and that is the same fact as this
    # batch's subject arriving on the *single-module* path.  This fixture strips
    # `islands`, so it runs `placement.py`, whose `_pin_text_term` measures the rows
    # the host prints (`textmetrics.symbol_rows`) — and since 531 those rows are the
    # real ones, including the **pose**-qualified anchors and the strings the host
    # actually draws (`120uF/25V-SMT` is 52 units where the spec's value string is
    # 88.6). The router's `occupied` boxes therefore changed, and `FB_SENSE` is a
    # second link it can no longer join, so 520E's rule names it too.  The rule
    # itself — 「连不上就降级成名字并记账」 — is unchanged; the drawing underneath it
    # got more accurate.
    #
    # **535 重钉**: 账本再长一条 `SEC_GND`——这一批的题落在**这一页**上的样子：
    # 530A 之下一条连不上的地只能是旗标，这页的旗标挂不上，于是它既进了降级名单、
    # 又是整页被拒的那条理由。顺序是 `rejected` 的跑序（`_rejected_label_fallbacks`
    # 每条网取第一次见到的那一笔），真载入器下 `SEC_GND` 落在 `FB_SENSE` 之前。
    assert [item.net for item in result.label_fallbacks] == [
        "HVDC", "SEC_12V", "SEC_GND", "FB_SENSE",
    ], (
        "520E's account: every net the router cannot join is named and "
        f"recorded: {[f.net for f in result.label_fallbacks]}"
    )

    # 新的：两轮各一条，拓扑轮的拒因不再是被遮住的那个。
    by_round = {item.round: item.failure for item in result.failure_rounds}
    assert set(by_round) == {"base", "topology"}, (
        "the flyback runs two rounds under 520A2 (the widened round's "
        "precondition is gone); three rounds again means the widening came back "
        f"— got {sorted(by_round)}"
    )
    # **520E 重钉**：`base` 轮的第一条拒因不再是「布线的直连义务」——那条义务
    # 连不上时现在被降级成名字并记账，这一轮于是由**下游的闸**来拒（520E 时可读性
    # 闸，**535 起是地自己的旗标席位阶梯**，见上）。`HVDC` 仍然出现在这条拒因里，
    # 但它是**降级名单**里的名字，不再是义务被拒的主体——两者都断言，免得「换了层」
    # 被读成「HVDC 消失了」。
    assert "HVDC" in by_round["base"].detail and "SEC_12V" in by_round["base"].detail
    assert "SEC_GND" in by_round["base"].detail, (
        "since 535 the ground is one of the nets this page names instead of "
        f"wiring: {by_round['base'].detail[:300]}"
    )
    # **535 重钉**：这一轮不再死在可读性闸上（见上），死在 069 sec.1 的旗标席位
    # 阶梯自己的那句话上——拒绝仍然是**编译器自己**的，带着它自己的主体与修法。
    assert "is named by a flag of its own" in by_round["base"].detail, (
        "535 moved the base round to the ground's own flag-seat ladder — got "
        f"{by_round['base'].detail[:200]}"
    )
    assert "the name had nowhere to go either" in by_round["base"].detail
    # **520D 重钉（T1 不许镜像）**：拓扑轮**不再死在关系闸**。
    # 520B2 读到的那条 `right-of(C11, T1)` 是**姿态问题不是形状问题**——
    # 拓扑搜索给 T1 选了镜像姿态，副边 4/5/6 从 (+40,·) 翻到 (-40,·)，于是
    # T1.6 落在 origin 左边，而 T1 自己的形状在**未镜像**的姿态下是满足这条
    # 关系的。520D 把 `XFMR-WE-749118105` 的 `poses` 声明成「四旋转、
    # mirror=false」（选出来的姿态根本不存在，不是在闸口拒绝），那一轮于是
    # 走到**可读性闸**：34 条硬违反（`wire-on-pin-line` 4 +
    # `text-overlap` 29 + `text-on-wire` 1），归口 `layout-unsat`。
    #
    # 反向钉：这句 `not in` 就是那条关系拒因**已经不在了**的证据——把
    # library 的 `poses` 摘回去，它会立刻变红。
    assert "right-of(C11, T1)" not in by_round["topology"].detail, (
        "520D declared T1's poses un-mirrored, so the topology search can no "
        "longer pick the pose that broke right-of(C11, T1); a refusal naming "
        "that relation again means the mirror came back — got "
        f"{by_round['topology'].detail[:200]}"
    )
    # **520G 重钉（34 → 29）**：`_pin_walls` 把引线方向当成符号自己的坐标读，
    # 于是**转过姿态的引脚一条引线都没预留**（实测：两条引线的 profile 在
    # rot 0 出 2 个盒、90/180/270 出 0 个；T1 的六条引线在它被摆的那个四分之一
    # 转上出 0 个）。520G 把方向换成 pose 之后的那个，那一轮于是从
    # `wire-on-pin-line` 4 + `text-overlap` 29 + `text-on-wire` 1 变成
    # `text-overlap` 26 + `text-on-wire` 3，合计 **29**。断言不写成「把 34
    # 换成 29」就完事：条数之外再钉住那条**不变量**——这一轮的违规里不许再有
    # 任何一条 `wire-on-pin-line`（把修复回滚，下面两句一起变红）。
    #
    # **530F 重钉（29 → 21）**：520D 的裁定 A（导线一律不印网名）之后，
    # `readability._named_wire_rows` 只给「它就是标签」的那根导线建模名字行，
    # 于是上一版里由**主机自印的 8 行**贡献的那 8 条读数整批消失：29 − 8 = 21
    # （530D 在真岛页上量到的同一件事，8 → 1 是那一页的投影）。这不是本条断言
    # 被放宽：`wire-on-pin-line` 的不变量在上面，这里数的仍是**同一张图**在
    # 同一层次的同一个读数，只是闸不再为没人会看见的字记账。
    topology_variant = next(
        item for item in result.rejected if item.variant == "topology-search"
    )
    # **534 r22 重钉（换层：可读性闸 → 终局重落座）**：`_reseat_crossed_labels`
    # 在全页导体铺完之后、可读性闸之前跑，因此这一轮**没到闸**。下面三句钉的是
    # 同一层的因果事实，不是数字：
    #   1. 主体是**具体那枚 label**（`labels[9]`），不是 `gate`；
    #   2. 它点名的图元与理由（`CLAMP`、`HVDC`、精确 box、梯子铺不满）；
    #   3. `violations` 为空是**原因**——「在 reseat 处就拒」，不是「闸放行」。
    # 26 条读数与 520G 的 `wire-on-pin-line` 不变量搬到 A/B 伴生测试里（关掉具名
    # 出口才量得到），那里它们**非空**；把那条不变量留在这里会是真空通过。
    assert by_round["topology"].subject == "labels[9]", (
        "534 r22 moved this round's first refusal to the final re-seat, which "
        "names the label it could not seat: the subject is the label, not the "
        f"gate — got {by_round['topology'].subject}"
    )
    assert (
        "the label 'CLAMP'" in by_round["topology"].detail
        and "no seat on its own ladder clears" in by_round["topology"].detail
        and "a HVDC run" in by_round["topology"].detail
        and "runs through [39.25, 163, 80.75, 172]" in by_round["topology"].detail
    ), (
        "the re-seat refusal owes its own subject and its own reason: the label, "
        "the net whose conductor cut the box, the exact box, and the exhausted "
        f"ladder — got {by_round['topology'].detail[:300]}"
    )
    assert not topology_variant.violations, (
        "534 r22 refuses this round at the final re-seat, **before** the "
        "readability gate runs; an empty violation list is the cause that row "
        "names. Rows here would mean the gate ran first and the re-seat row is "
        f"no longer the first refusal — got {len(topology_variant.violations)}"
    )
    assert by_round["topology"].category == dc.FAILURE_LAYOUT_UNSAT, (
        "GATE_REFUSAL_KINDS maps none of the hard kinds this gate hit, so the "
        "refusal is layout-unsat — the relation gate's presentation-poor is "
        f"gone — got {by_round['topology'].category}"
    )

    # summarize 是报告的读法：round 名逐条在场。
    summary = result.summarize_failure_rounds()
    assert [item["round"] for item in summary] == ["base", "topology"]
    # 520E: `base`'s detail still names HVDC — as one of the nets the compiler
    # **named instead of wiring**, which is what the reader needs to know.
    assert "HVDC" in summary[0]["detail"] and "SEC_12V" in summary[0]["detail"]
    # 520G: the base round's 25 -> 24 — the one `wire-on-pin-line` (SEC_SW along
    # `T1.4`) is gone and the other 24 are the same page, so both rounds' counts
    # move by that one class and no other.
    #
    # **530F 重钉（24 → 22 / 29 → 21）**: 520D's ruling A took the net name off the
    # conductor, so `readability._named_wire_rows` models a name row only for the
    # wire that **is** the label.  Two of the base round's rows and eight of the
    # topology round's were rows the host prints over conductors nobody will read
    # a name on; the counts move by exactly those, and by nothing else (the
    # `wire-on-pin-line` invariant below still holds in both rounds).
    # **531 重钉（22 → 23 / 21 → 22）**：两条计数各 +1，因为这一页的**文字行**
    # 换成了宿主真正画的那一行（`core.textmetrics.symbol_rows`：量出来的 pose 锚点 +
    # 宿主真画的值字符串）——路由与摆放读的就是这些盒子，所以同一张图的互压读数
    # 会动。`wire-on-pin-line` 的不变量（上面与下面两条）仍然成立，轮集合也仍然是
    # `base` + `topology`：变的只有闸数出来的行数，不是哪一层在拒。
    #
    # **532 重钉（23 → 29 / 22 → 27）**：`readability` 现在把**引脚名/号**也算进
    # 它读的文字（`textmetrics.pin_rows`，量出来的每符号表），这份真库里有三个符号
    # 会印它们（`SOT23-3-TL431`、`XFMR-WE-749118105`、`SMD-4-PC817`），所以同一张
    # 图多出若干条互压读数。两条不变量一个字没动：`wire-on-pin-line` 仍为 0，
    # 轮集合仍是 `base` + `topology`，**每一层的拒因还是同一层**——变的是闸数出来
    # 的行，不是谁在拒。数字逐条在 `evidence/532/raw/`。
    #
    # **535 重钉（29 → base 不再是可读性闸 / 27 → 26）**：`base` 轮换了层（069
    # sec.1 旗标席位阶梯，上面已逐条说明），所以第一句不再是闸的计数，而是闸的
    # **那层**自己的主体与句号；`topology` 轮当时仍在可读性闸上。
    # **534 r22 重钉（topology 轮也不再以闸的计数开头 / 26 是「条数 + 构成」）**：
    # 终局重落座先开口，于是 `topology` 的摘要行是它自己的主体与句号（正文已钉）。
    # 26 条读数搬进 A/B 伴生测试，那里的**实测构成**是 `text-overlap` **26** +
    # `text-on-wire` **0**——旧注释写的「`text-overlap` 24 + `text-on-wire` 2」
    # 与本树实测不符（数字被钉住、组合从未被钉）。`wire-on-pin-line` 为 0 这条
    # 不变量**只在闸跑过的那一态才有内容**，所以在伴生测试里断言，不在这里——
    # 留在这里会随着 `violations` 变空而**真空通过**。
    assert "is named by a flag of its own" in summary[0]["detail"], (
        "the base round's summary row is now the ground's own flag-seat ladder "
        f"(535) — got {summary[0]['detail'][:200]}"
    )
    assert "no seat on its own ladder clears" in summary[1]["detail"], (
        "534 r22: the topology round's summary row is the final re-seat's own "
        f"sentence now, not the gate's count — got {summary[1]['detail'][:200]}"
    )
    for item in summary:
        assert "wire-on-pin-line" not in item["detail"], (
            "520G reserves every pin's lead at every pose; neither round's leading "
            f"refusal may be that class again — got {item['detail'][:200]}"
        )


def test_the_reseat_layer_does_not_hide_the_readability_rows(monkeypatch):
    """**534 r22 的 A/B 伴生钉**：关掉具名出口，26 条读数与 520G 不变量必须还在。

    534 r22 让终局重落座 ``_reseat_crossed_labels`` 成为这一轮的第一个开口人：它在这页的
    `CLAMP`（anchor `(60, 180)`）上 16 档全无座，于是**在可读性闸之前**具名拒绝，
    `topology-search` 的 `violations` 因此为空。上面那条测试钉的是**新的**第一个开口人；
    这一条钉的是**被它挡在后面的那一层仍然活着**——否则「26 条读数」与「
    `wire-on-pin-line` 为 0」两条历史不变量会随着 `violations` 变空而**真空通过**，
    等于测试缩小了覆盖面却宣称重钉。

    量法：只在这一条测试里把 `_reseat_crossed_labels` 换成恒 `None`（≈ 534 r22 之前的
    行为：仍穿透的 box 交给闸去判），其余一切照旧——同一个 fixture、同一把真尺子、
    同一个 `CompileBudget`。这不是产品开关：monkeypatch 在测试结束自动还原，
    别的测试看不到它。

    换层前后的画面是同一张：进入该 pass 瞬间的 (labels, segments, solids) 摘要两态
    都是 `1b3031e27f33bf54`（.tmp_534/topology-failure-review-r1/probe3.json），
    所以这里量到的 26 条就是「如果没有更早报拒，这一页会给读者看的读数」。
    """
    monkeypatch.setattr(dc, "_reseat_crossed_labels", lambda *args, **kwargs: None)
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = _single_module(
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    )
    result = dc.compile(
        circuit, presentation, _flyback_library_real(),
        dc.CompileBudget(max_candidates=64),
    )
    assert not result.ok and not result.candidates

    by_round = {item.round: item.failure for item in result.failure_rounds}
    # 关掉重落座不改变轮集合：仍是 base + topology（换的只是谁先开口）。
    assert set(by_round) == {"base", "topology"}, (
        f"the rounds are the same picture — got {sorted(by_round)}"
    )
    assert "the independent readability checker refused 26 hard violation" in (
        by_round["topology"].detail
    ), (
        "with the re-seat out of the way the topology round must reach the "
        "readability gate again — 26 hard violations, the same page the reseat "
        f"pass refused — got {by_round['topology'].detail[:200]}"
    )
    assert by_round["topology"].category == dc.FAILURE_LAYOUT_UNSAT

    topology_variant = next(
        item for item in result.rejected if item.variant == "topology-search"
    )
    assert len(topology_variant.violations) == 26, (
        "the count the gate's sentence states and the rows it kept are the same "
        "reading — 26 rows on the worktree tree (534 r22 measured; 535 was 26 too) "
        f"— got {len(topology_variant.violations)}"
    )
    # **不变量（520G）：这一轮的不许再有 `wire-on-pin-line`。**
    # 它在主测试里已经量不到（那一轮没跑到闸），所以这一句是它唯一的证人：
    # 摘掉 520G 的 pose 方向修复，这里会立刻出现 `wire-on-pin-line` 行。
    assert not [
        line for line in topology_variant.violations if "wire-on-pin-line" in line
    ], (
        "520G reserves each pin's drawn lead at every pose, so the topology round "
        "cannot run a wire along one again; a `wire-on-pin-line` here means the "
        f"turned poses stopped reserving — got {topology_variant.violations[:3]}"
    )
    # **26 的构成也钉住**（旧注释曾写「24 + text-on-wire 2」，实测不符）：
    # 这一页闸读出来的 26 条**全是** `text-overlap`，没有一条 `text-on-wire`。
    # 只钉条数会把「组合变了但总数凑巧相等」读成同一张图。
    kinds = {
        "text-overlap": sum("text-overlap" in line for line in topology_variant.violations),
        "text-on-wire": sum("[text-on-wire]" in line for line in topology_variant.violations),
    }
    assert kinds == {"text-overlap": 26, "text-on-wire": 0}, (
        "the 26 rows are all `text-overlap` on this page; a `text-on-wire` row "
        f"means the picture moved — got {kinds}"
    )


def test_a_hand_built_result_json_round_trips_are_report_ready():
    """``--json-path`` 载荷经 json.dumps 的那一手是纯数据，不炸。"""
    result = dc.CompileResult(failure_rounds=[
        dc.FailureRound(round="base", failure=_failure("d1")),
    ])
    payload = {"failureRounds": result.summarize_failure_rounds()}
    assert json.loads(json.dumps(payload))["failureRounds"] == [
        {"round": "base", "category": dc.FAILURE_LAYOUT_UNSAT, "detail": "d1"},
    ]


# ---------------------------------------------------------------- 4 CLI 合同


def test_draw_compile_json_payload_carries_failure_rounds(tmp_path):
    """``draw compile --json-path``：``failureRounds`` 在场，``failures`` 原样。

    窄页上的分压器（053 场景 10 的形状）在 CLI 里离线拒绝：`layout-unsat`、
    变体逐条建齐。钉的是载荷键的**形状**：新键是 list[{round,category,detail}]、
    旧键的字段集 (category, detail, action) 一个不少。
    """
    from boardwise import cli

    fixtures = pathlib.Path(__file__).resolve().parent / "fixtures" / "drawapply"
    report = tmp_path / "compile.json"
    code = cli.main([
        "draw", "compile",
        "--circuit", str(fixtures / "divider.circuit.json"),
        "--presentation", str(fixtures / "divider.presentation.json"),
        "--profiles", str(fixtures / "library.json"),
        "--page-box", "0,0,240,300",
        "--out", str(tmp_path / "out"),
        "--json", str(report),
    ])
    assert code == 5, "the narrow page refuses; the payload is the refusal's"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert isinstance(payload["failureRounds"], list)
    assert payload["failureRounds"], (
        "a refusal with no round rows would leave the second exit invisible "
        "again — this is the key the report reads"
    )
    for item in payload["failureRounds"]:
        assert set(item) == {"round", "category", "detail"}
        assert item["round"] in (*dc.FAILURE_ROUNDS, "first")
    for item in payload["failures"]:
        assert {"category", "detail", "action"} <= set(item)
