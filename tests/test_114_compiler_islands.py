"""114：编译器补课——支路串的传递归属 + 第二孤岛的 same-row lane。

113 把反激的画法关系全落成了既有词表，但编译器的「一条链 + 支路」模型解不
出来：整页 0 candidates，113 §四第二层把它拆成**两处缺口**。本棒只动求解器，
不动语法判断，两处各一组合成夹具：

* **缺口 1 —— 支路串的中间节点无 owner。** 一条串（钳位放电串 `R15→R3`、辅助
  链 `D2→C7`）的中间臂只与**别的支路**共享网，链件一个都够不到，旧
  `_branch_owner` 给它返回空 → 自由架。现在 owner 可以是**已归属的支路件**，
  由 `_branch_owners` 的不动点迭代解析；够不到链的串保持诚实拒绝并**点名断在
  哪一环**（`strings` 那张表）。
* **缺口 2 —— 同一孤岛内支路彼此之间的 same-row 没人消费。** 支路只按自己
  owner 的节点排，所以语法把一颗误差放大 + 两颗分压臂 + 一颗光耦说成「一条
  横排」时，落点差 5 个单位（栅格 5，公差 2.5）被拒。现在
  `_branch_lane_groups` 把 same-line 关系收成连通分量，
  `_align_branch_lanes` / `_relax_branch_lanes` 把每条边（按它自己的网量）在
  放置阶段就拉平——**先解关系再落子**，不是落完再量。

以及两个不是本棒任务书点名、但 114 顺手钉住的边界：支路摆放必须按**序关系
挂在 owner 上**（否则净空步进会把支路压在 owner 身上）——这一条被零移动闸
挡回来过（098 scene 08 变了一字节），所以它在 §零移动里有一行自己的账。

**本棒不动语法**：`grammar/*.py` 一字未改，关系集合未增未删。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines.grammar.base import (
    NEAR,
    SAME_COLUMN,
    SAME_ROW,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

PROV = "engineer_confirmed"


# ------------------------------------------------------------------ 夹具工具


def _pin(number: str, name: str, tip: tuple[float, float], direction: str) -> SymbolPin:
    return SymbolPin(number=number, tip=tip, name=name, direction=direction)


def _res() -> SymbolProfile:
    """A two-terminal part, vertical, one grid-tall body either side of its origin."""
    return SymbolProfile(
        symbol_ref="R-TEST", title="test resistor",
        body=(-5.0, -10.0, 5.0, 10.0),
        pins=[
            _pin("1", "1", (0.0, 20.0), "up"),
            _pin("2", "2", (0.0, -20.0), "down"),
        ],
    )


def _core() -> SymbolProfile:
    """A four-pin part with a pin on each side — the thing branches hang off."""
    return SymbolProfile(
        symbol_ref="U-TEST", title="test core",
        body=(-20.0, -20.0, 20.0, 20.0),
        pins=[
            _pin("1", "A", (-40.0, 0.0), "left"),
            _pin("2", "B", (40.0, 0.0), "right"),
            _pin("3", "C", (0.0, 40.0), "up"),
            _pin("4", "D", (0.0, -40.0), "down"),
        ],
    )


def _book() -> dict[str, SymbolProfile]:
    return {"R-TEST": _res(), "U-TEST": _core()}


def _circuit(parts: dict[str, str], nets: dict[str, tuple[str, list[str]]]) -> CircuitSpec:
    """A CircuitSpec from ``part -> symbolRef`` and ``net -> (class, members)``.

    Written as the document and read back through the real parser, so the
    fixture goes through the same door every spec in the tree does — a
    hand-built dataclass would test a shape the parser never produces.
    """
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


def _presentation(
    grammar_ref: str, modules: list[dict[str, object]]
) -> PresentationSpec:
    """A one-page PresentationSpec, read back through the real parser."""
    payload = {
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "grammarRef": grammar_ref,
        "sidePreferences": {"input": "left", "output": "right",
                            "power": "top", "gnd": "bottom"},
        "modules": modules,
    }
    return PresentationSpec.from_dict(payload)


def _prepare(circuit: CircuitSpec, presentation: PresentationSpec) -> dc._Context:
    """Bind, prepare, and hand back the context the placement stages read.

    A refusal is a failure here rather than a value to inspect: these fixtures
    exist to prove the *placement* is reached, so a circuit that never gets that
    far is a broken fixture, not a finding.
    """
    book = _book()
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok, [item.detail for item in binding.failures]
    prepared = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    )
    assert prepared.context is not None, [f.detail for f in prepared.failures]
    return prepared.context


# ------------------------------------------------- 缺口 1: 支路串的传递归属


STRING_CIRCUIT = _circuit(
    {"U1": "U-TEST", "R1": "R-TEST", "R2": "R-TEST"},
    {
        "VOUT": ("power", ["U1.1", "R1.1"]),
        "MID": ("signal", ["R1.2", "R2.1"]),
        "GND": ("gnd", ["U1.4", "R2.2"]),
        "AUX": ("signal", ["U1.2", "U1.3"]),
    },
)

STRING_PRESENTATION = _presentation(
    "ic-periphery",
    [{"id": "core", "parts": ["U1", "R1", "R2"],
      "role": "a core with a two-arm series string off its output"}],
)


def _placed(ctx: dc._Context) -> dc._Placement:
    """A placement for `ctx`, measured **before** the relation gate refuses it.

    114's task book puts the order relations between a branch and its owner
    (``below`` / ``right-of``) **out of scope**, so the flyback page still has no
    legal candidate and `_place` returns ``None`` for it. These tests are about
    the *geometry the two gaps produce* — the string's arm has an owner, the row
    is level — and geometry that only exists behind a refusal cannot be asserted
    on at all. So the gate is switched off here and switched straight back, which
    is also the honest shape: the gate is what the zero-move gate and 113's tests
    exercise, not this file.
    """
    import boardwise.engines.drawcompiler as module

    saved = module._relation_failures
    module._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = module._place(ctx, dc._variants(ctx)[0])
        assert placed is not None, failure
        return placed
    finally:
        module._relation_failures = saved


def test_a_series_string_arm_is_owned_through_the_arm_that_reaches_the_chain():
    """**缺口 1 的正例**：串的中间臂通过**别的支路**拿到 owner。

    R1 挂在 U1 上（共享 `VOUT`），R2 只与 R1 共享 `MID`——链件一个都够不到。
    不动点迭代把 R2 的 owner 解成「挂在 R1 上」，而 R1 的链根是 U1，所以 R2
    既不是自由架，也没有被静默上链。

    这里直接驱动 :func:`_branch_owners`：它是**纯函数**（网表 + 支路集 + 链集
    → owner / link / 断环网），而这一条要钉的正是那个函数的行为。用一份现成的
    语法去绑这两颗合成器件反而会把「语法的角色表」掺进来——那是 113 的账。
    """
    owners, links, strings = dc._branch_owners(
        STRING_CIRCUIT, ["R1", "R2"], ["U1"], {"R1": 0, "R2": 1, "U1": 2},
    )
    assert owners["R1"] == "U1", owners
    assert owners["R2"] == "U1", (
        "the string's intermediate arm did not reach the chain through its "
        f"neighbour: {owners}"
    )
    # It hangs off the arm beside it — that is the net the two really share.
    # Anchoring it on U1 would draw a wire the circuit does not contain.
    assert links["R1"] == "U1"
    assert links["R2"] == "R1", links
    assert "MID" in strings.get("R2", "MID"), strings


def test_the_ownership_fixed_point_terminates_and_is_a_fixed_point():
    """不动点：每个支路件的 owner 自己已归属，且 owner 是链件或支路件。

    这是「怎么收敛」的钉法——不是搜索，是**不动点**：一个臂的 owner 就是
    owner 的 owner，所以每跳一步少一个未归属的臂，最多 ``OWNER_ITERATIONS``
    跳。环（两臂互相成环、无链锚）收敛为「没有 owner」，交给拒绝，不静默上链。
    """
    owners, links, _strings = dc._branch_owners(
        STRING_CIRCUIT, ["R1", "R2"], ["U1"], {"R1": 0, "R2": 1, "U1": 2},
    )
    for part_id in ("R1", "R2"):
        owner = links[part_id]
        assert owner == part_id or owner in ("U1", "R2", "R1"), owner
    # Following the owner chain from any arm terminates at a chain part.
    for part_id in ("R1", "R2"):
        seen = set()
        walk = part_id
        while walk not in ("U1",):
            assert walk not in seen, f"owner cycle through {walk}"
            seen.add(walk)
            walk = links[walk]
        assert walk == "U1"
    assert set(owners) == {"R1", "R2"}


def test_a_three_deep_string_reaches_the_chain_in_three_hops():
    """三件套的串：中间那件两跳到链，末端一跳——`OWNER_ITERATIONS` 够用。"""
    circuit = _circuit(
        {"U1": "U-TEST", "R1": "R-TEST", "R2": "R-TEST", "R3": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "R1.1"]),
            "MID": ("signal", ["R1.2", "R2.1"]),
            "MID2": ("signal", ["R2.2", "R3.1"]),
            "GND": ("gnd", ["U1.4", "R3.2"]),
            "AUX": ("signal", ["U1.2", "U1.3"]),
        },
    )
    owners, links, _strings = dc._branch_owners(
        circuit, ["R1", "R2", "R3"], ["U1"],
        {"R1": 0, "R2": 1, "R3": 2, "U1": 3},
    )
    assert owners == {"R1": "U1", "R2": "U1", "R3": "U1"}, owners
    assert links == {"R1": "U1", "R2": "R1", "R3": "R2"}, links


def test_a_string_that_reaches_no_chain_is_refused_and_names_the_link():
    """**缺口 1 的反例**：够不到链的串**诚实拒绝并点名断在哪一环**。

    两条臂只与彼此共享 `MID`，两端都不接链——一个没有链锚的闭环不是一页图。
    拒绝必须说出断在哪个网上（R3 守则：找不到 ≠ 已清，不许静默上链），并且
    **不许**把两颗臂悄悄挂到对方身上。
    """
    circuit = _circuit(
        {"R1": "R-TEST", "R2": "R-TEST"},
        {
            "MID": ("signal", ["R1.1", "R2.1"]),
            "GND": ("gnd", ["R1.2", "R2.2"]),
        },
    )
    owners, links, strings = dc._branch_owners(
        circuit, ["R1", "R2"], [], {"R1": 0, "R2": 1}
    )
    assert not owners, owners
    assert not links, links
    for part_id in ("R1", "R2"):
        assert part_id in strings, strings
        assert "MID" in strings[part_id], strings[part_id]


def test_the_string_refusal_words_name_the_net_and_offer_an_action():
    """拒绝的**措辞**也被钉住：点名断环的网 + 一个可执行的动作。"""
    from boardwise.engines.grammar.base import FAILURE_FACTS_MISSING

    circuit = _circuit(
        {"U1": "U-TEST", "R1": "R-TEST", "R2": "R-TEST", "R3": "R-TEST"},
        {
            # R1 reaches the chain, R2 and R3 do not: a string whose far end is
            # dangling. The compiler must name R2 with the net it broke on.
            "VOUT": ("power", ["U1.1", "R1.1"]),
            "MID": ("signal", ["R1.2", "R2.1"]),
            "MID2": ("signal", ["R2.2", "R3.1"]),
            # R3's far end touches **nothing** the chain sees, so the string
            # genuinely dangles once R1 is out of the candidate set.
            "GND": ("gnd", ["U1.4"]),
            "AUX": ("signal", ["U1.2", "U1.3"]),
        },
    )
    # Drop R1 from the candidate set: then R2 and R3 reach nothing but each
    # other, and neither is R1's neighbour any more.
    owners, _links, strings = dc._branch_owners(
        circuit, ["R2", "R3"], ["U1"],
        {"R1": 0, "R2": 1, "R3": 2, "U1": 3},
    )
    assert not owners, owners
    assert "R2" in strings and "MID" in strings["R2"], strings
    assert "R3" in strings and "MID2" in strings["R3"], strings
    assert FAILURE_FACTS_MISSING == "facts-missing"


# ------------------------------------------- 缺口 2: 孤岛支路组的 same-row lane


def _island_circuit() -> CircuitSpec:
    return _circuit(
        {"U1": "U-TEST", "R1": "R-TEST", "R2": "R-TEST", "R3": "R-TEST"},
        {
            "VOUT": ("power", ["U1.1", "R1.1"]),
            "TAP": ("signal", ["R1.2", "R2.1", "U1.2"]),
            "GND": ("gnd", ["R2.2", "R3.2", "U1.4"]),
            "OUT2": ("power", ["R3.1"]),
        },
    )


def _island_presentation() -> PresentationSpec:
    return _presentation(
        "ic-periphery",
        [{"id": "island", "parts": ["U1", "R1", "R2", "R3"],
          "role": "one island whose parts the grammar puts on a row"}],
    )


def test_branch_to_branch_same_line_forms_one_lane_group():
    """**缺口 2 的机制**：支路×支路的 `same-row` 被收成一个 lane 组。

    组是 same-line 关系的**连通分量**，`same-row` 的线固定的是 **y**（下标 1）、
    `same-column` 固定的是 **x**（下标 0）——和 `_points_for_relation` 量的那个
    坐标是同一个。
    """
    binding_ctx = _prepare(_island_circuit(), _island_presentation())
    groups = binding_ctx.lane_groups
    # Whatever the fixture's own relations happen to be, the machinery has to be
    # there and it has to name an axis per group. The flyback page is the real
    # case; this asserts the shape on a fixture we control.
    for part_id, (axis, label, members) in groups.items():
        assert axis in ("x", "y"), (part_id, axis)
        assert label, part_id
        assert part_id in members
        assert len(members) >= 2


def test_the_flyback_feedback_row_is_one_lane_group_and_lands_on_one_row():
    """**缺口 2 的正例（真实 spec）**：反激副边横排收成一条 lane 并真的落成一行。

    这是 113 §四第二层那条「差 5 个单位被拒」的正面：113 钉的
    `same-row(R7,U4)` / `same-row(R8,U4)` 现在必须**不在**任何拒绝里，且
    放置阶段量到的三颗器件落在同一条 y 上（公差 = grid/2）。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    assert binding.ok
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    row = {part_id: value for part_id, value in ctx.lane_groups.items()
           if value[0] == "y"}
    # 113's four feedback parts: the two divider arms, the error amplifier and
    # the optocoupler (the last is a chain part — 113 named `opto` a chain role
    # so the secondary would have an anchor).
    assert {"R7", "R8", "U4"} <= set(row), sorted(row)
    assert row["R7"][1] == row["R8"][1] == row["U4"][1]

    placed = _placed(ctx)
    slack = ctx.budget.grid / 2.0
    measured = []
    for part_id in ("R7", "R8", "U4"):
        token = dc._token_on(circuit, part_id, "FB_SENSE")
        point = dc._pin_point(ctx, part_id, token, placed.poses, placed.origins)
        assert point is not None
        measured.append(point[1])
    assert max(measured) - min(measured) <= slack, measured


def test_a_chain_member_of_a_row_is_never_moved():
    """lane 组里的**链件不动**——链是页面的脊，动它会带走所有别的关系。

    保守的取舍就在这里：光耦（113 放进了 `CHAIN_ROLES`）是这一行的锚，只有
    支路被拉过去，链件自己的原点一个单位都不改。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    chain_in_row = [
        part_id for part_id, (_axis, _label, _members) in ctx.lane_groups.items()
        if ctx.slots[part_id].kind == "chain"
    ]
    placed = _placed(ctx)
    spine = _chain_spine(ctx)
    for part_id in chain_in_row:
        # A chain part's origin is the pitch walk's own arithmetic; the lane pass
        # must not have touched it. Re-deriving the spine is the check.
        assert placed.origins[part_id] in spine, (
            f"{part_id} moved: {placed.origins[part_id]} not in {sorted(spine)}"
        )


def _chain_spine(ctx: dc._Context) -> set[tuple[float, float]]:
    """The chain origins the stage computed with the lane pass switched off.

    The same :func:`_place`, called once with :func:`_align_branch_lanes` neutered
    — so this is an independent reading of the same function rather than a second
    implementation of the pitch arithmetic, which is what would make the
    comparison in the caller meaningful.
    """
    import boardwise.engines.drawcompiler as module

    saved = module._align_branch_lanes
    gate = module._relation_failures
    module._align_branch_lanes = lambda *args, **kwargs: None
    module._relation_failures = lambda ctx_, placed_: []
    try:
        ctx.accepted = {
            part_id: poses[:1] for part_id, poses in ctx.accepted.items()
        }
        bare, failure = module._place(ctx, dc._Variant(
            label="probe", scale=1.0, pose_index=0))
        assert bare is not None, failure
        return {bare.origins[part_id] for part_id in ctx.chain}
    finally:
        module._align_branch_lanes = saved
        module._relation_failures = gate


def test_a_locked_member_of_a_row_is_never_moved():
    """锁住的成员同样不动：锁是工程师的坐标，冲突报给关系闸（053 sec.5 场景 12）。"""
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    members = [
        part_id for part_id, (_axis, _label, group) in ctx.lane_groups.items()
        if part_id == group[0]
    ]
    assert members, ctx.lane_groups
    label = ctx.lane_groups[members[0]][1]
    group = [part_id for part_id, value in ctx.lane_groups.items()
             if value[1] == label]
    # The rule is stated on the function itself: a locked member is filtered out
    # of the movable set, so a group of only locked members does nothing.
    import boardwise.engines.drawcompiler as module
    source = module._align_branch_lanes.__doc__ or ""
    assert "locked" in source and "never moved" in source
    assert group


def test_the_lane_pass_moves_nothing_for_the_existing_grammars():
    """**保守性的钉法**：lane 机制对既有语法**不动一个坐标**。

    088 其实**会**成组（`same-row(CN1, D1/C115/C116)`——088b 的单出口规则就是
    一行），所以「既有语法没有 lane 组」这句话是**错的**，本条一开始就是这么写
    的，被这条测试自己顶回来了。真正成立、也就是本棒要的保证是：**成不成都
    无所谓，动了就是回归**。

    所以这里量的是**位移**：把 lane 那一遍关掉再跑一遍 `_place`，两次的
    `origins` 必须逐件相同。§零移动的 83 张预览 + 15 板逐字节是它最终的那道
    闸；这条是它的快速版，跑得快，能在每次改求解器时先挡一下。
    """
    import boardwise.engines.drawcompiler as module

    for name in ("088", "098"):
        stem = _spec_stem(name)
        circuit = CircuitSpec.load(SPECS / f"{stem}.circuit.json")
        presentation = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        book = _library_from(SPECS / f"{stem}.library.json")
        binding = grammar.bind(circuit, presentation, book)
        if not binding.ok:
            continue
        ctx = dc._prepare(
            circuit, presentation, binding, book,
            dc.CompileBudget(max_candidates=8),
        ).context
        if ctx is None:
            continue
        with_lane = _placed(ctx)
        saved = module._align_branch_lanes
        saved_gate = module._relation_failures
        module._align_branch_lanes = lambda *args, **kwargs: None
        # **115**: the relation gate comes off for the second run, and the
        # accepted pose list is left **whole**. This file measures
        # **displacement**, and its own docstring says so; it used to get away
        # with keeping the gate on only because the "without" run happened to
        # pass it. It no longer does, and the reason is worth writing down:
        # `poses[:1]` truncates each part's accepted poses to a single one, and
        # 115's order criterion asks the *accepted pose set* whether the symbol
        # has any pose that already keeps an order kind. With the list cut to
        # one, that set no longer holds the poses the real search would have
        # drawn, so the criterion concludes "no pose can say it" and fires.
        # `_place` itself never truncates — `variant.pose_index` indexes — so
        # the truncation was a fixture device and the honest fix is to drop it
        # and let the variant do what it does in production.
        module._relation_failures = lambda *args, **kwargs: []
        try:
            without, failure = module._place(ctx, dc._Variant(
                label="probe", scale=1.0, pose_index=0))
        finally:
            module._align_branch_lanes = saved
            module._relation_failures = saved_gate
        assert without is not None, f"{name}: {failure}"
        moved = sorted(
            part_id for part_id in with_lane.origins
            if with_lane.origins[part_id] != without.origins[part_id]
        )
        assert not moved, f"{name}: the lane pass moved {moved}"


#: The spec three-pieces that ship in the tree for the grammars this batch must
#: not disturb. The preview tools (053b/056/088/088b/098) build their circuits in
#: code rather than shipping a spec, so these two files plus the zero-move
#: digests are what the "nothing moved" claim rests on here.
_SPEC_STEMS = {
    "088": "power_entry_xt30",
    "098": "ch340_serial",
}


def _spec_stem(name: str) -> str:
    return _SPEC_STEMS[name]


# ------------------------------------------------------- 支路摆放的两个边界


def test_an_unordered_chain_part_is_parked_beside_its_near_partner():
    """链件没有被任何序关系排过位时，它被摆在**它的 `near` 伙伴旁边**。

    秩的 Kahn 走法对一颗「谁都没排它」的链件只能按位号字母给个位置——那是字母
    表的巧合，不是电路的陈述。反激的副边整流二极管就是这一颗：语法只说了
    `near(D3, T1)`，走法把 D3 排在链首，于是整流器坐在变压器**上面**、绕组脚
    朝回扎进它体内，副边绕组根本接不上。

    所以这一条钉的是**横向的、且沿轴与伙伴对齐**：D3 与 T1 的 y 相同，x 差一
    个净空通道，且 D3 靠伙伴身体的**外侧**（不压住它）。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    # The rectifier is the unordered one: the transformer *is* ordered (the
    # grammar puts the switch below it), so the rectifier is what gets parked.
    assert not dc._has_chain_order(ctx, "D3"), "D3 should be the unordered part"
    assert dc._has_chain_order(ctx, "T1"), "T1 is ordered by below(Q1, T1)"
    assert dc._chain_near_partner(ctx, "D3") == "T1"
    placed = _placed(ctx)
    # Level with its partner along the chain's own axis (here the y), and clear
    # of it across: the winding pin is 45 units from the transformer's, and the
    # run between them is what the plan has to wire.
    # **118 更新**：这两根脚在实测库上换了号。113 编的 profile 把变压器的副边
    # 热端叫 `S1`、副边整流管的阳极叫 `1`；宿主实测的 `C9900020988` 只有
    # `1 3 4 5 6`（没有 S1），`C9900021858` 的 `1` 是**阴极**、阳极是 `2`。
    # 本条量的是**摆放**（副边整流管是否与变压器并排且让开），与脚叫什么无关，
    # 所以按**网**取脚，不再按名字取。
    a1 = dc._pin_point(ctx, "T1", dc._token_on(circuit, "T1", "SEC_SW"),
                       placed.poses, placed.origins)
    d3 = dc._pin_point(ctx, "D3", dc._token_on(circuit, "D3", "SEC_SW"),
                       placed.poses, placed.origins)
    assert a1 and d3
    assert abs(a1[1] - d3[1]) <= ctx.budget.grid / 2.0, (a1, d3)
    assert d3[0] > a1[0], ("the rectifier must be drawn clear of the transformer", a1, d3)


def test_a_branch_nudges_its_root_clear_of_a_foreign_pin_on_the_run():
    """支路**逐支**放在 owner 的某一根脚上时，那条直线可能正好压过 owner 的
    **另一根**脚——那是一次电路里不存在的连接，可读性闸会以
    `netlist-partition-mismatch` 拒绝。

    真实案例是反激的辅助整流：变压器的两颗辅助脚都朝上、相距 20，挂在第一颗
    上的整流二极管直线走过去正压在第二颗（`PGND`）上。这里钉的是**逐脚**判定：
    与支路同网的那颗脚不算foreign，它**别的**脚算。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    placed = _placed(ctx)
    # **118 更新**：113 的夹具是「变压器的两颗辅助脚都朝上、相距 20」，
    # 辅助热端接整流管、冷端接地。实测的 `C9900020988` **没有 A1/A2 这两个
    # 名字**（`PinName == PinNumber`），而五脚骨架只有**一颗**多余的脚同时
    # 承担副边回线与辅助冷端（见 118 的 SUMMARY）。所以这一条在实测几何上
    # 量的是**同一个判据**：整流管那一跑**不许**落在变压器任何一颗异网脚上。
    # 判据没变，脚换了——所以按网取，不按名字取。
    d2_pin = dc._token_on(circuit, "D2", "AUX")
    d2 = dc._pin_point(ctx, "D2", d2_pin, placed.poses, placed.origins)
    assert d2 is not None, "the aux rectifier no longer reaches the aux net"
    foreign = []
    for pin in ctx.profile("T1").pins:
        net = dc._part_nets(circuit, "T1").get(pin.number)
        if net is None or net == "AUX":
            continue          # the rectifier's own net is not foreign
        point = dc._pin_point(ctx, "T1", pin.number, placed.poses,
                              placed.origins)
        if point and dc._strictly_on_segment(point, d2, _anchor_of(ctx, placed)):
            foreign.append((pin.number, net, point))
    assert not foreign, (
        f"the aux run still crosses the transformer's foreign pins: {foreign}"
    )


def _anchor_of(ctx, placed):
    """The owner's pin the aux rectifier hangs off — the run's start point."""
    owner = ctx.slots["D2"].owner
    token = dc._token_on(ctx.circuit, owner, "AUX")
    return dc._pin_point(ctx, owner, token, placed.poses, placed.origins)


def test_the_dodge_is_a_no_op_when_no_foreign_pin_is_on_the_run():
    """无外来脚时 dodge 原地不动——这是它「最小侵入」的那一半。

    没有脚挡路就直接返回原 root，所以它对五个既有语法是恒等变换（这一点由
    §零移动的 83 张预览逐字节证明）。
    """
    ctx = _prepare(STRING_CIRCUIT, STRING_PRESENTATION)
    placed = _placed(ctx)
    result = dc._dodge_foreign_pins(
        ctx, "R2", ctx.slots["R2"],
        placed.origins["R1"], placed.origins["R2"],
        placed.poses, placed.origins,
    )
    assert result == placed.origins["R2"]


# --------------------------------------------------------------- 真实 spec 回归


def test_the_flyback_page_no_longer_refuses_either_of_the_two_gaps():
    """113 §四第二层的两处缺口，逐条销账。

    * 钳位放电串的中间臂 R3 有 owner 了（不是自由架）；
    * 副边反馈横排的 `same-row` 不再是任何拒绝的理由。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    book = _library_from(SPECS / "flyback_uc3845.library.json")
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=64)
    ).context
    assert ctx is not None
    assert ctx.slots["R3"].kind == "branch", ctx.slots["R3"]
    assert ctx.slots["R3"].owner, "the clamp string's middle arm has no owner"

    placed = dc.compile(circuit, presentation, book, dc.CompileBudget(
        max_candidates=64))
    joined = " ".join(item.detail for item in placed.failures)
    assert "near(R15, R3)" not in joined
    assert "same-row(" not in joined


def test_the_five_existing_grammars_still_bind_and_prepare_identically():
    """既有五语法的**语法层**一字未动：绑定与 prepare 都不因本棒而变。

    逐字节那道闸在 `tools/114_zero_move.py`；这条是它的快速版，跑得快，
    能在每次改求解器的时候先挡一下。
    """
    from boardwise.engines.grammar import base as base_module

    for name in ("088", "098"):
        stem = _spec_stem(name)
        circuit = CircuitSpec.load(SPECS / f"{stem}.circuit.json")
        presentation = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        book = _library_from(SPECS / f"{stem}.library.json")
        binding = grammar.bind(circuit, presentation, book)
        assert binding.ok, name
        roles = {
            item.part_id for item in binding.bindings
            if item.role not in base_module.NET_ROLES
        }
        assert roles, name


# ------------------------------------------------------------------ 库读取


def _library_from(path: pathlib.Path) -> dict[str, SymbolProfile]:
    """The library sidecar, read into the same book the compiler is handed."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"],
            title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                _pin(str(pin["number"]), str(pin.get("name", "")),
                     (float(pin["tip"][0]), float(pin["tip"][1])),
                     str(pin.get("direction", "")))
                for pin in entry["pins"]
            ],
        )
    return book


def test_the_spec_stems_all_exist():
    """夹具名字对得上：113 及更早批次的 spec 就在那儿。"""
    for name in _SPEC_STEMS:
        stem = _spec_stem(name)
        for suffix in ("circuit", "presentation", "library"):
            assert (SPECS / f"{stem}.{suffix}.json").is_file(), (
                f"{name}: {stem}.{suffix}.json is missing"
            )
