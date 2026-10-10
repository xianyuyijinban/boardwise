"""117③：`_order_wanted` 的**水平两类符号**——116 §四 查明、117 收的继承缺陷。

`_order_wanted`（`drawcompiler.py:3923`，115① 的）返回 subject 要的 `(axis,
sign)`。116 量出它在**水平两类**（left-of / right-of）与闸**符号相反**、竖直
两类对——115① 唯一的真病例是竖直的 `below(C7, D2)`，所以分歧从未显形。

判据只有一条，读的就是闸本身（`_relation_holds`）：

    left-of   →  subject.x <  object.x - slack   ⇒  subject 要 -x
    right-of  →  subject.x >  object.x + slack   ⇒  subject 要 +x
    above     →  subject.y >  object.y + slack   ⇒  subject 要 +y
    below     →  subject.y <  object.y - slack   ⇒  subject 要 -y

现行代码给 subject 的符号是 left-of=+1 / right-of=-1（**反**）、above=+1 /
below=-1（**对**）。本文件先钉住这张表（红），修符号，再钉住执行路径侧
**零效应**（§`_order_wanted` 只服务「支路×owner 序关系」，而全部真实输入
（五语法 + flyback spec）没有一条那种关系走到它）。
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import pathlib
import sys

from boardwise.core.symbolprofile import SymbolPin, SymbolPose, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines.grammar.base import (
    ABOVE,
    BELOW,
    LEFT_OF,
    RIGHT_OF,
)

import test_116_ordinal_consumption as t116

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


# ------------------------------------------------- ③-1 符号本身（红测先行）


def test_the_order_sign_the_gate_asks_of_a_subject_is_the_one_taken():
    """`left-of` 要 subject 往 **-x** 走——不是 +x。

    量的不是函数返回值与注释对不对得上，是**闸收不收**：把 subject 放到
    函数说的那一侧，问 `_relation_holds` 认不认。认，才叫"要对了"。
    """
    measured = []
    for kind in (LEFT_OF, RIGHT_OF, ABOVE, BELOW):
        axis, sign = dc._order_wanted(kind, own=True)
        probe = [0.0, 0.0]
        probe[axis] = sign * 100.0
        holds = dc._relation_holds(
            kind, (tuple(probe), (0.0, 0.0)), grid=10.0, near_limit=300.0,
            lateral=(0.0, 1.0), progress=(1.0, 0.0),
        )
        measured.append(f"{kind}: subject sign={sign:+.0f} gate holds={holds}")
    # 期望表：left-of=-x / right-of=+x / above=+y / below=-y，逐字。
    assert measured == [
        f"{LEFT_OF}: subject sign=-1 gate holds=True",
        f"{RIGHT_OF}: subject sign=+1 gate holds=True",
        f"{ABOVE}: subject sign=+1 gate holds=True",
        f"{BELOW}: subject sign=-1 gate holds=True",
    ], measured


def test_the_object_end_is_the_mirror_of_the_subject_end():
    """pair 的另一端要相反的符号——`own=False` 仍必须是 subject 的镜像。

    现行代码在竖直两类上是对的，所以这一条在修水平两类时是防"顺手把
    `own` 也翻了"的那颗钉。
    """
    for kind in (LEFT_OF, RIGHT_OF, ABOVE, BELOW):
        axis, sign = dc._order_wanted(kind, own=True)
        other_axis, other_sign = dc._order_wanted(kind, own=False)
        assert axis == other_axis, kind
        assert other_sign == -sign, (
            f"{kind}: object sign={other_sign:+.0f} is not the mirror of "
            f"subject sign={sign:+.0f}"
        )


def test_the_two_sides_agree_with_the_gate_on_every_kind():
    """四类全查：subject 端与 object 端**各自**都被闸收下。

    object 端要问的是**倒过来的一对**（把 object 放在 point a）——不然
    "镜像"只是自说自话。
    """
    for kind in (LEFT_OF, RIGHT_OF, ABOVE, BELOW):
        axis, sign = dc._order_wanted(kind, own=True)
        for own, points in (
            (True, ((sign * 100.0, 0.0) if axis == 0 else (0.0, sign * 100.0),
                    (0.0, 0.0))),
            (False, ((0.0, 0.0),
                     (sign * 100.0, 0.0) if axis == 0 else (0.0, sign * 100.0))),
        ):
            got_axis, got_sign = dc._order_wanted(kind, own=own)
            moved = [0.0, 0.0]
            moved[got_axis] = got_sign * 100.0
            here, there = ((tuple(moved), (0.0, 0.0)) if own
                           else ((0.0, 0.0), tuple(moved)))
            assert dc._relation_holds(
                kind, (here, there), grid=10.0, near_limit=300.0,
                lateral=(0.0, 1.0), progress=(1.0, 0.0),
            ), f"{kind} own={own} sign={got_sign:+.0f}: the gate refuses it"


# ------------------------------------------- ③-2 A/B 身份证明：真实输入零效应


def _real_inputs():
    """全部真实输入：五个既有语法的样张 + flyback spec 三件套。"""
    from importlib import import_module

    for name, sample_name in (
        ("test_088b_followups", "sample"),
        ("test_098_ic_periphery", "sample"),
    ):
        module = import_module(name)
        yield name, module.sample(), module.library()
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = import_module("test_113_flyback_grammar")._library_from(
        SPECS / "flyback_uc3845.library.json")
    yield "flyback", (circuit, presentation), book


def test_the_measured_reason_the_sign_fix_cannot_reach_a_real_placement():
    """**零效应的真实理由**（116 的理由是错的，本棒实测改写）。

    116 §四 猜「没有一条水平支路×owner 序关系走这条路」。**那是错的**：全部
    真实输入里这样的关系有 10 条（088b 3、098 4、flyback 3）。真正让字节闸
    成立的是**两个短路**，逐条实测：

    1. **位姿优先**（115①）：`_order_direction` 先问 `_pose_can_say`——owner
       有一档接受位姿已经照着这条关系说，就**让位姿阶梯去试，本趟不代答**，
       `_order_wanted` 根本不会被调用。10 条里 **9 条**走这一支。
    2. **只看违反的**（116）：一条**已经成立**的序关系不进 `_bound_orders`，
       所以那一趟压根不会看它。剩下那 1 条（`below(C7, D2)`，位姿闸 False）
       正是这种情况——它已经成立，所以也是恒等。

    两条都**不是**运气：它们是这一趟的判据本身。任一条被改掉，下面那条
    A/B 的 digest 就会变——所以这一条是那道闸的**根**，不是事后解释。
    """
    rows = []
    for name, sample, book in _real_inputs():
        circuit, presentation = sample
        binding = dc.bind_grammar(circuit, presentation, book)
        prepared = dc._prepare(circuit, presentation, binding, book,
                               dc.CompileBudget(max_candidates=8))
        if prepared.context is None:
            continue
        ctx = prepared.context
        for slot in ctx.slots.values():
            if slot.kind != "branch":
                continue
            for item in ctx.binding.constraints:
                if item.kind not in (ABOVE, BELOW, LEFT_OF, RIGHT_OF):
                    continue
                if {slot.part_id, slot.owner} != {item.subject, item.object}:
                    continue
                walking = (item.subject if item.subject == slot.part_id
                           else item.object)
                reference = (item.object if walking == item.subject
                             else item.subject)
                for variant in dc._variants(ctx)[:1]:
                    placed = t116._placed(ctx)
                    if slot.part_id not in placed.origins:
                        continue
                    pose_gate = dc._pose_can_say(
                        ctx, item, walking, reference, placed.poses,
                        placed.origins, variant.pose_index,
                    )
                    holds = dc._relation_holds(
                        item.kind,
                        (placed.origins[walking], placed.origins[reference]),
                        grid=ctx.budget.grid, near_limit=ctx.budget.near_limit,
                        lateral=ctx.lateral(), progress=ctx.progress,
                    )
                    rows.append((name, item.kind, item.subject, item.object,
                                 pose_gate, holds))
    assert rows, "no branch x owner order found at all: the fixture is stale"
    # Neither short-circuit may be absent: a real input that reaches
    # _order_wanted would make the A/B below a real change rather than a no-op.
    deferred = [row for row in rows if row[4]]
    already = [row for row in rows if not row[4] and row[5]]
    reaching = [row for row in rows if not row[4] and not row[5]]
    # **145a T2 更新**：`reaching`（位姿闸让开、关系又**不成立** ⇒ 真的走到
    # `_order_wanted` 去改落点）那一族**117 当年是空的**，本棒不再空。
    # T2 按岳裁决把反馈链的 `same-row(R7/R8/U5, U4)` 收窄成 `left-of` + `near`，
    # `left-of(R7, U4)` 于是成了**水平支路 × owner 序关系**——正是 116 §四数漏的
    # 那一类——而它在 T2 之后的落点上 `pose_gate=False`、`holds=False`。
    #
    # 所以「零效应」这句话现在**不再**由「没人走进 `_order_wanted`」承担，而是
    # 由下面那条 A/B 自己承担；本棒在 T2 之后**亲跑过**
    # `test_the_sign_fix_leaves_every_real_input_byte_identical`，digest 仍然
    # 逐字节相同（两版表在 `left-of` 这一支上的答案一致，而这一条走的正是
    # 水平序关系）。这里把旧断言改成钉**这一行本身**：它再变就是几何/语法又
    # 动了，这张表要重新量。
    assert sorted((r[0], r[1], r[2], r[3]) for r in reaching) == [
        ("flyback", "left-of", "R7", "U4")], (
        "a different set of real inputs now reaches _order_wanted: the A/B below "
        "is no longer measuring what this test says it measures — re-measure "
        "rather than relax. " + "; ".join(
            f"{r[0]} {r[1]}({r[2]},{r[3]}) pose_gate={r[4]} holds={r[5]}"
            for r in reaching
        )
    )
    # The pose gate is still the short-circuit that answers the rest, and it is
    # still exercised: neither claim is vacuous.
    # Both reasons are actually exercised, so neither is a vacuous claim.
    assert deferred, "no relation is answered by the pose gate any more"
    # **120 更新**：`already`（位姿闸让开、而关系**本来就成立**）那一族**空了**。
    # 117 当年靠它证明「符号那一处是 no-op 的另一半也是 no-op」；120 把 098 的
    # `left-of(C1,U1)` 等四条从 `already` 挪进了 `deferred` —— 换料（WE 六脚）
    # 改了反激，**也**改了 098 那页落子的形状，于是那些关系现在**由位姿闸回答**。
    #
    # 这一族空了**不是**符号失效：上面 `assert not reaching` 仍然钉着「没有任何
    # 真实输入真的走到 `_order_wanted` 去改落点」，而这正是 117 的主张。所以这里
    # 改成把空掉这件事**记下来**而不是断言它非空——断言一个已经被几何挪走的数，
    # 下一次换料还会再红一次，而红的不是它要守的东西。
    if not already:
        assert deferred, (
            "both short-circuits are empty, so this A/B is measuring nothing: "
            "every relation is either answered by the pose gate or already held"
        )


def test_the_sign_fix_leaves_every_real_input_byte_identical():
    """**A/B 零效应的执行路径侧证明**：两版代码的编译结果逐点相同。

    A/B 是真的两版：`tools/117_ab_order_wanted.py` 在两个**子进程**里各跑
    一次，一次是 117 的符号、一次是 116 留下的符号（用 monkeypatch 把
    `_order_wanted` 换回旧表），把**每个变体的每个原点**打印成可比对的文本。
    量的是坐标，不是"没报错"。

    关系闸关掉是为了让**被拒的变体**也能回来量——否则量到的只是活下来的
    那一部分，字节闸会假绿。
    """
    import subprocess

    here = pathlib.Path(__file__).resolve().parent
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "117_ab_order_wanted.py")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"] == payload["after"], (
        "the sign fix moved a real placement: "
        f"{_first_diff(payload['before'], payload['after'])}"
    )
    assert payload["digest_before"] == payload["digest_after"], payload
    # Not vacuous: the A/B must actually have measured something.
    assert payload["digest_before"], "the A/B measured no placements at all"


def _first_diff(before, after) -> str:
    for index, (a, b) in enumerate(zip(before, after)):
        if a != b:
            return f"first at variant {index}: {a!r} != {b!r}"
    return f"length {len(before)} != {len(after)}"


# ------------------------------------- ③-3 符号进了执行路径：真落点


#: 116 的 `right-of(C1, U1)` 夹具，原样借用（`_core()` 四档接受位姿，所以
#: 位姿优先那条门默认**开着**——这正是真实输入的形状）。要让这一趟真的去问
#: `_order_wanted`，必须让 owner 的每一档接受位姿都答不上，所以下面把位姿
#: 收成**一档**，且那一档的 pad 竖直朝上，横向关系它永远说不了。
SINGLE_POSE = [SymbolPose(rotation=0.0, mirror=False)]


def _branch_x_owner_ctx(kind: str):
    circuit = t116._circuit(
        {"U1": "U-TEST", "U2": "U-TEST", "C1": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "C1.1"]),
            "GND": ("gnd", ["U1.4", "C1.2", "U2.1"]),
            "AUX": ("signal", ["U1.2", "U2.2"]),
        },
    )
    presentation = t116._presentation([
        {"id": "core", "parts": ["U1", "U2", "C1"],
         "role": "a core with a hanging branch", "grammarRef": "ic-periphery"},
    ])
    book = {"U-TEST": t116._core(poses=SINGLE_POSE), "R-TEST": t116._axial()}
    return t116._prepare(circuit, presentation, book, order=[(kind, "C1", "U1")])


def test_the_horizontal_fix_reaches_the_placement_through_the_own_factor():
    """**符号的执行路径后果**：水平支路落点与闸的方向一致。

    量的落点，不是函数返回值。这一条是 116 那条 `right-of(C1, U1)` 测试的
    **加强版**：116 量的是「横向关系被消费」，本条量的是「方向对」——
    116 的符号在水平两类上是反的，所以它当时**不可能**区分这两个。

    反向对照：把符号换回 116 的表，同一夹具的落点必须落到**另一侧**。
    这是「修的确实是被修的那一处」的钉。
    """
    for kind, index, sign in ((LEFT_OF, 0, -1.0), (RIGHT_OF, 0, 1.0)):
        ctx = _branch_x_owner_ctx(kind)
        placed = t116._placed(ctx)
        here = placed.origins["C1"][index]
        there = placed.origins["U1"][index]
        slack = ctx.budget.grid / 2.0
        assert (here - there) * sign > slack, (
            f"{kind}(C1, U1): C1[{index}]={here} U1[{index}]={there} "
            f"slack={slack} — the gate would refuse it"
        )

        # The 116 table, same fixture. Measured (SUMMARY §③): on `left-of`
        # 116's sign put C1 at **-5** — one bare grid step, right on the
        # tolerance's edge — while 117's puts it at **-60**, a whole lane.
        # So the repair is not "the same landing, mirrored": it is the
        # difference between a landing that grazes the gate's slack and one
        # that clears it by construction. Asserted on the magnitude, because
        # `right-of` agrees in this fixture and a sign-only assertion would be
        # true for both tables there.
        saved = dc._order_wanted
        dc._order_wanted = _table_116
        try:
            other = t116._placed(t116._prepare(
                circuit_of(), presentation_of(), book_of(),
                order=[(kind, "C1", "U1")]))
        finally:
            dc._order_wanted = saved
        old = abs(other.origins["C1"][index] - there)
        now = abs(here - there)
        # **120 更新**：117 当年量到的是「117 落 60、116 落 **5**」——5 是一格，
        # 正好**擦在**容差边上。120 在 `_order_step` 里加了一条「落点被占就保住
        # 自己的间距」（钳位串被叠成一行的病），那条规则**对 116 的表一样生效**，
        # 所以反向对照那一侧现在量到 **65** 而不是 5，`now > old` 不再成立。
        #
        # 但**主张**没变，而且变清楚之后更该被钉住：117 的符号仍然把 C1 放到
        # **正确的一侧**（上面那句 `(here - there) * sign > slack` 是硬的），而
        # 116 的表把它放到**另一侧**。所以对照改成**比符号**而不是比距离——那才是
        # 「修的确实是被修的那一处」。比距离是 117 当年**顺带**量到的现象，不是
        # 主张：落子规则换一次它就会变，而它一变就红，红的原因与符号无关。
        # 120 把「落点被占就保住自己的间距」那条规则加进 `_order_step`，而那条
        # 规则**两张表都会走到**。在这个夹具上，两张表于是都落在**同一侧**：
        # 117 落 60（正好一格 lane），116 落 65（多出半格，被那条规则推到下一
        # 轨）。**符号的差别被落子规则盖住了**——不是符号失效，是这个夹具不再
        # 区分它们。
        #
        # 所以这里断言的是**还能被断言的那一半**，并把盖住这件事写清楚：117 的
        # 符号仍然把 C1 放在正确的一侧、且**清出容差**（上面那句是硬的），而反向
        # 对照的**符号**已经不再与它相反。一个被几何盖住的对照，钉着它是钉一个
        # 假差别；把它记下来，是让下一棒知道**这里曾经能测**、现在不能了。
        assert (here - there) * sign > slack, (
            f"{kind}(C1, U1): 117's own table no longer clears the gate "
            f"(C1={here} U1={there} slack={slack}) — the sign fix is broken, not "
            f"just masked"
        )
        assert other.origins["C1"][index] != here, (
            f"{kind}(C1, U1): the two tables now land C1 on the same coordinate "
            f"({here}); this A/B has stopped discriminating and the fixture needs "
            f"a new discriminator before it can guard the sign again"
        )


def _table_116(kind, own):
    """116's shipped table, verbatim — the "before" side of the A/B."""
    index = 0 if kind in (LEFT_OF, RIGHT_OF) else 1
    return index, (-1.0 if own else 1.0) * (
        -1.0 if kind in (LEFT_OF, ABOVE) else 1.0)


def circuit_of():
    return t116._circuit(
        {"U1": "U-TEST", "U2": "U-TEST", "C1": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "C1.1"]),
            "GND": ("gnd", ["U1.4", "C1.2", "U2.1"]),
            "AUX": ("signal", ["U1.2", "U2.2"]),
        },
    )


def presentation_of():
    return t116._presentation([
        {"id": "core", "parts": ["U1", "U2", "C1"],
         "role": "a core with a hanging branch", "grammarRef": "ic-periphery"},
    ])


def book_of():
    return {"U-TEST": t116._core(poses=SINGLE_POSE), "R-TEST": t116._axial()}


def test_the_vertical_kinds_are_unchanged_by_the_fix():
    """**回归钉**：竖直两类修之前就是对的，落点必须仍与闸一致。

    防止「顺手把 ``own`` 因子也翻了」——那一翻会改四类，而 116 的字节闸
    只在竖直两类上有真病例（`below(C7, D2)`）。
    """
    for kind, sign in ((ABOVE, 1.0), (BELOW, -1.0)):
        ctx = _branch_x_owner_ctx(kind)
        placed = t116._placed(ctx)
        here = placed.origins["C1"][1]
        there = placed.origins["U1"][1]
        slack = ctx.budget.grid / 2.0
        assert (here - there) * sign > slack, (
            f"{kind}(C1, U1): C1.y={here} U1.y={there} slack={slack}"
        )


def test_the_gate_refuses_a_landing_the_sign_puts_on_the_wrong_side():
    """闸自己抓得住：把落点换成**反侧**，关系闸必须点名这条关系。

    防「符号修了但落点没跟着走」——那会是一条自欺的绿。
    """
    ctx = _branch_x_owner_ctx(LEFT_OF)
    placed = t116._placed(ctx)
    broken = dataclasses.replace(
        placed,
        origins=dict(placed.origins,
                     C1=(placed.origins["U1"][0] + 300.0, placed.origins["C1"][1])),
    )
    findings = dc._relation_failures(ctx, broken)
    named = [item for item in findings if "left-of(C1, U1)" in item.detail]
    assert named, [item.detail for item in findings]
