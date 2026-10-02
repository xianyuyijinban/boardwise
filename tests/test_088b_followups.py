"""088b：电源入口跟进批 —— 底轨出处符号（裁决②）+ 声明式支路顺序（裁决③）。

088 落账（`967bb17`）后复验，画出来的图和岳样板有三处可见偏差，岳 2026-10-02 逐条裁决
（原文 `tasks/088b-power-entry-deltas-DRAFT.md` 末尾「裁决结果」）：

1. **旗位置：保持现状**（挂入口侧轨脚）——本批零代码改动，只把 088 钉的那两条
   「今天是这样」注释转成「2026-10-02 岳裁决确认保持」；
2. **底轨加一个接地符号**：实体线保留，位置 = 底轨**远端**（背向连接器那端）、竖直、
   有且只有一个；
3. **支路顺序声明化**：TVS 必须最靠入口，顺序由 `PresentationSpec.modules[].branchOrder`
   声明，语法不看位号/值/封装（053 §6 红线不动）。

本文件的分工，一句话一条：

1. **出处符号的机制**（§一）：`gnd-outlet` 这条新义务由**语法**发，且**无条件**——每次
   绑定都发（2026-10-02 岳裁决②，主代理复验裁定收回"声明模块才发"的门控：岳的样板本来
   就不声明模块，门控等于没执行裁决）。义务名字是 net，编译器按 `sidePreferences.input`
   找出「远端」并把符号挂在那只轨脚上（竖直，`rot ∈ {0,180}`）。053b/056 的既有 39 张
   场景仍连这条 kind 都见不到（别的语法不发）；
2. **顺序**（§二）：`branchOrder` 是文档的声明，语法把它落成相邻支路之间的约束链；
   缺省 = 088 现状（位号序），**部分声明按位号序补齐**（实测理由在
   `test_a_partial_declaration_...`）。链用的是 `adjacent` 而不是 `left-of`/`right-of`：
   实测 `right-of(D1, C115)` 在本语法 input=right 的图上一律 0 候选（编译器的 rank
   读法与支路挂靠方向耦合，见 `test_...` 与交卷报告），`adjacent` 是同一句「这两条相邻、
   前一条更靠入口」在两种朝向下都成立的写法；
3. **校验三态**（§三.4）：未知位号 / 重复位号由 spec 层报错点名（`branchOrder` 的位号必须
   在本模块 `parts` 里），位号不是本模块 shunt（入口、或跨别的网的件）由语法
   `circuit-invalid` 点名；
4. **场景**（§三）：样板、镜像、缺省回归、多支路唯一性、页级实测、spec 封闭性。

CircuitSpec / PresentationSpec 全部手写字面量，符号库直接复用 088 的 `library()`：
两条轨、三颗支路、连接器形状只许有一处定义，多一份就是第二个画法定义。
"""

from __future__ import annotations

import json

import pytest

import test_053b_drawcompiler as b053
import test_088_power_entry as base088

from boardwise.core.presentationspec import (
    PRESENTATION_SPEC_VERSION,
    PresentationSpec,
    PresentationSpecError,
)
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines.grammar import power_entry
from boardwise.engines.grammar.base import (
    ADJACENT,
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    GND_OUTLET,
    LEFT_OF,
    NEAR,
    OBLIGATION_KINDS,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_ROW,
    UNIFORM_GND,
)

RAIL = base088.RAIL
GND = base088.GND
PROV = base088.PROV
SAMPLE_BRANCHES = ("D1", "C115", "C116")
FOUR = ("D1", "C115", "C116", "C117")


# ------------------------------------------------------------------ 夹具复用


def library():
    """088 的符号库，原样：本批不新增任何形状。"""
    return base088.library()


def inlet_circuit(**overrides):
    return base088.inlet_circuit(**overrides)


def compile_module(circuit_spec, presentation_spec, *, budget=None):
    return base088.compile_module(circuit_spec, presentation_spec, budget=budget)


def bind(circuit_spec, presentation_spec):
    return base088.bind(circuit_spec, presentation_spec)


def best(circuit_spec, presentation_spec):
    return base088.best(circuit_spec, presentation_spec)


def clean(plan, circuit_spec, presentation_spec) -> None:
    base088.clean(plan, circuit_spec, presentation_spec)


def group(branches=("D1", "C115", "C116"), *, module_id: str = "inlet",
          parts=None, order=None, grammar_ref: str = "power-entry") -> dict:
    """一个被声明的模块：本批的两条声明都挂在这里。

    `parts` = 模块的成员（`branchOrder` 的 spec 层校验拿它当「本模块自己的件」）；
    `order` = 从入口端往远的支路位号（`branchOrder`）。
    """
    body: dict = {
        "id": module_id,
        "parts": list(parts if parts is not None else ("CN1", *branches)),
        "role": "the 24 V inlet",
        "grammarRef": grammar_ref,
    }
    if order is not None:
        body["branchOrder"] = list(order)
    return body


def declared(*, side: str = "right", order=("D1", "C115", "C116"),
             branches=("D1", "C115", "C116"), parts=None, **overrides):
    """岳样板的**模块**：088 的 presentation + 一个被声明的 inlet 模块。"""
    modules = overrides.pop("modules", [group(branches, order=order, parts=parts)])
    return base088.inlet_presentation(side=side, modules=modules, **overrides)


def undeclared(*, side: str = "right", **overrides):
    """088 现状的那份：不声明任何模块（088 的模块级场景用的就是它）。"""
    return base088.inlet_presentation(side=side, **overrides)


def sample(*, side: str = "right", order=("D1", "C115", "C116"),
           branches=SAMPLE_BRANCHES, values=None):
    return (
        inlet_circuit(shunts=branches, values=values),
        declared(side=side, order=order, branches=branches),
    )


# ------------------------------------------------------------------- 读图助手


def near(first, second, tolerance: float = 1e-6) -> bool:
    return (
        abs(first[0] - second[0]) <= tolerance
        and abs(first[1] - second[1]) <= tolerance
    )


def symbols_for(plan, net_id: str) -> list:
    return [item for item in plan.power_symbols if item.net == net_id]


def pin(plan, member: str):
    point = b053.pin_point(plan, member, library())
    assert point is not None, f"{member} is not placed by this plan"
    return point


def attached_to(plan, symbol, member: str) -> bool:
    """Is this symbol reached by a wire of its own net that also touches `member`?"""
    anchor = (symbol.x, symbol.y)
    point = pin(plan, member)
    for segment in plan.segments:
        if segment.net != symbol.net:
            continue
        points = list(segment.points)
        if any(near(item, anchor) for item in points) and any(
            near(item, point) for item in points
        ):
            return True
    return False


def from_the_inlet(plan, part_ids, *, side: str = "right") -> list[str]:
    """The branches read from the inlet end outwards (nearest the inlet first)."""
    where = {part_id: pin(plan, f"{part_id}.1")[0] for part_id in part_ids}
    return sorted(where, key=lambda part_id: where[part_id], reverse=side == "right")


def farthest_branch(plan, part_ids) -> str:
    """The branch furthest from the inlet — the rail's far end."""
    entry = pin(plan, "CN1.1")[0]
    return max(part_ids, key=lambda part_id: abs(pin(plan, f"{part_id}.1")[0] - entry))


def relation_pairs(result):
    return [(item.kind, item.subject, item.object) for item in result.constraints]


def page_pair(*, order=("C115",)):
    """088 的页级电路 + 一个把 inlet 声明成模块的 presentation（可带 `branchOrder`）。

    页级场景的**唯一出处**：`tests/` 的页级测试与 `tools/088b_previews.py` 都用它，
    免得预览画的是另一张没人测过的页面。
    """
    payload = base088._page_presentation().to_jsonable()
    payload["modules"][0]["branchOrder"] = list(order)
    return base088._page_circuit(), PresentationSpec.from_dict(payload)


# ====================================================== 1. 出处符号的机制（§一）


def test_the_outlet_is_stated_on_every_bind_and_not_gated_on_a_declaration():
    """`gnd-outlet` **无条件**发：2026-10-02 岳裁决② + 主代理复验裁定。

    本批第一版把它门控在"声明了模块"上（好让 088 的图一动不动）；裁定收回该门控——
    岳的样板本来就不声明模块，门控等于没执行裁决。所以声明模块、只声明模块不写顺序、
    以及什么都不声明，三种情形发的是同一条义务。
    """
    for presentation_spec in (undeclared(), declared(), declared(order=None)):
        result = bind(inlet_circuit(), presentation_spec)
        assert result.ok, result.failures
        kinds = [(item.kind, item.nets) for item in result.obligations]
        assert [nets for kind, nets in kinds if kind == GND_OUTLET] == [(GND,)]
        assert [item for item in kinds if item[0] != GND_OUTLET] == [
            (DIRECT_WIRE, (RAIL,)),
            (DIRECT_WIRE, (GND,)),
            (UNIFORM_GND, (GND,)),
            (OWNED_BRANCH, (RAIL,)),
        ]
        reason = next(
            item.reason for item in result.obligations if item.kind == GND_OUTLET
        )
        assert "unconditional" in reason


def test_the_same_outlet_reaches_the_plan_with_and_without_a_declared_group():
    """无条件在图上也成立：声明模块与不声明模块，画出的都是恰一个端口符号。"""
    for presentation_spec in (undeclared(), declared()):
        circuit_spec = inlet_circuit()
        plan = best(circuit_spec, presentation_spec)
        (outlet,) = symbols_for(plan, GND)
        assert outlet.symbol_ref == "PWR-GND"
        assert outlet.rotation in (0.0, 180.0)


def test_the_new_kind_is_registered_and_documented():
    """新义务 kind 的三步：词汇表定义、注册面、编译器消费侧（088 §四的流程）。"""
    assert GND_OUTLET == "gnd-outlet"
    assert OBLIGATION_KINDS[-1] == GND_OUTLET
    assert GND_OUTLET in power_entry.__doc__
    reason = next(
        item.reason
        for item in bind(inlet_circuit(), declared()).obligations
        if item.kind == GND_OUTLET
    )
    assert "088b sec.1" in reason and GND in reason


def test_scene_1_the_sample_states_exactly_one_upright_outlet_at_the_rail_far_end():
    """§三.1：样板 + branchOrder → 出处符号恰一个、在远端脚、竖直；可读性零硬违规。"""
    circuit_spec, presentation_spec = sample(side="right")
    plan = best(circuit_spec, presentation_spec)

    (outlet,) = symbols_for(plan, GND)
    assert outlet.symbol_ref == "PWR-GND"
    assert outlet.rotation in (0.0, 180.0), outlet.rotation
    far = farthest_branch(plan, SAMPLE_BRANCHES)
    assert far == "C116"
    assert attached_to(plan, outlet, "C116.2"), (
        "the outlet hangs off the rail's far end — 背向入口那端"
    )
    assert not attached_to(plan, outlet, "CN1.2")
    clean(plan, circuit_spec, presentation_spec)
    assert plan.labels == []


def test_the_far_end_is_read_from_the_input_side_not_written_down_as_a_member():
    """「远端」是 `sidePreferences.input` 读出来的：同一句声明在两种朝向下都对。"""
    for side, expected in (("right", -1.0), ("left", 1.0)):
        circuit_spec, presentation_spec = sample(side=side)
        plan = best(circuit_spec, presentation_spec)
        (outlet,) = symbols_for(plan, GND)
        assert attached_to(plan, outlet, "C116.2")
        # 远端在入口的**反方向**：entry 在最右时符号在最左，反之亦然。
        assert (outlet.x - pin(plan, "CN1.1")[0]) * expected > 0, side


def test_the_outlet_leaves_the_rail_one_conductor_and_the_ground_one_style():
    """出处符号是挂在轨上的一个符号，不是把轨拆成旗点：每位成员脚仍在线上。"""
    circuit_spec, presentation_spec = sample(side="right")
    plan = best(circuit_spec, presentation_spec)

    gnd_wires = [item for item in plan.segments if item.net == GND]
    assert gnd_wires
    for member in ("CN1.2", "D1.2", "C115.2", "C116.2"):
        assert base088.touches(gnd_wires, pin(plan, member)), member
    assert plan.labels == []
    assert plan.evidence.grammar_findings == []


def test_scene_2_the_mirror_moves_the_outlet_and_keeps_the_declared_order():
    """§三.2：input=left 时顺序与符号位置同步镜像。"""
    for side in ("right", "left"):
        circuit_spec, presentation_spec = sample(side=side)
        plan = best(circuit_spec, presentation_spec)
        assert from_the_inlet(plan, SAMPLE_BRANCHES, side=side) == [
            "D1", "C115", "C116"
        ], side
        (outlet,) = symbols_for(plan, GND)
        assert attached_to(plan, outlet, "C116.2"), side
        clean(plan, circuit_spec, presentation_spec)


def test_scene_5_four_branches_keep_one_outlet_and_the_entry_side_rail_flag():
    """§三.5：支路数弹性不改变「一个符号」；+24V 旗仍在入口侧（裁决①）。"""
    circuit_spec, presentation_spec = sample(order=FOUR, branches=FOUR)
    plan = best(circuit_spec, presentation_spec)

    assert len(symbols_for(plan, GND)) == 1
    (flag,) = symbols_for(plan, RAIL)
    assert attached_to(plan, flag, "CN1.1")
    (outlet,) = symbols_for(plan, GND)
    assert attached_to(plan, outlet, "C117.2")
    assert from_the_inlet(plan, FOUR, side="right") == list(FOUR)
    clean(plan, circuit_spec, presentation_spec)


# ================================================= 2. 声明式顺序（§二/§三.3/4）


def test_the_declared_order_becomes_a_chain_between_neighbours():
    """§二：按声明顺序在相邻支路间发约束链；entry↔shunt 的既有约束一条不少。"""
    result = bind(inlet_circuit(), declared())
    pairs = relation_pairs(result)

    assert pairs[-2:] == [
        (ADJACENT, "D1", "C115"),
        (ADJACENT, "C115", "C116"),
    ]
    for shunt in SAMPLE_BRANCHES:
        assert (SAME_ROW, "CN1", shunt) in pairs
        assert (RIGHT_OF, "CN1", shunt) in pairs
        assert (NEAR, shunt, "CN1") in pairs
    chained = next(
        item for item in result.constraints
        if item.kind == ADJACENT and item.subject == "D1"
    )
    assert "branchOrder" in chained.reason and "D1" in chained.reason
    # side=left 是同一句话的镜像（链的 kind 不是被 side 决定的）。
    left = relation_pairs(bind(inlet_circuit(), declared(side="left")))
    assert (LEFT_OF, "CN1", "C116") in left
    assert (ADJACENT, "D1", "C115") in left


def test_the_order_is_read_from_the_document_and_not_from_the_designator():
    """同一张电路，两种声明顺序 → 两张不同的排法：顺序来自文档，不是位号字典序。"""
    for order in (("D1", "C115", "C116"), ("C116", "D1", "C115"), ("C116",)):
        circuit_spec, presentation_spec = sample(order=order)
        plan = best(circuit_spec, presentation_spec)
        expected = list(order) if len(order) == 3 else ["C116", "C115", "D1"]
        assert from_the_inlet(plan, SAMPLE_BRANCHES, side="right") == expected, order


def test_a_partial_declaration_keeps_the_stated_prefix_and_fills_the_rest():
    """§二留的二选一：**补齐**而不是拒绝（实测后钉的理由见下）。"""
    circuit_spec, presentation_spec = sample(order=("C116",))
    result = bind(circuit_spec, presentation_spec)
    plan = best(circuit_spec, presentation_spec)

    assert relation_pairs(result)[-2:] == [
        (ADJACENT, "C116", "C115"),
        (ADJACENT, "C115", "D1"),
    ]
    assert from_the_inlet(plan, SAMPLE_BRANCHES, side="right") == [
        "C116", "C115", "D1"
    ]
    # 补齐写在证据里，所以「文档定了哪几条、哪几条按默认」是看得见的。
    evidence = next(
        item.evidence for item in result.bindings if item.part_id == "C116"
    )
    assert "branchOrder states C116 from the inlet outwards" in evidence
    assert "drawn after them in designator order: C115, D1" in evidence


def test_a_partial_declaration_is_completed_where_a_full_one_says_what_it_means():
    """为什么补齐：整条缺省就是位号序，部分声明是同一句话的截断（同 `flow` 的读法）。

    实测支持：补齐后的相邻链与完整声明发的是同一个 kind、同一套 reason 结构，图上
    「声明的在前、其余按位号」逐位可验；反过来若拒绝，一条已经能画出来、且已经说出
    关键那一半的文档会停摆，而停摆并不比默认序更不容易误导。
    """
    partial = best(*sample(order=("C116",)))
    whole = best(*sample(order=("C116", "C115", "D1")))
    assert from_the_inlet(partial, SAMPLE_BRANCHES, side="right") == from_the_inlet(
        whole, SAMPLE_BRANCHES, side="right"
    )


def test_scene_3_without_a_declaration_the_order_is_088s_and_the_outlet_is_still_there():
    """§三.3 回归钉：缺省 `branchOrder` → 排法与 088 的位号序逐位一致（约束一条不多）；
    同时 2026-10-02 岳裁决②（无条件）的出处符号照出（088 起先的"底轨无符号"是它自报的
    待裁偏差，裁决后改成应有样子，见 `tests/test_088_power_entry.py` 场景 1）。"""
    circuit_spec, presentation_spec = inlet_circuit(), undeclared(side="right")
    result = bind(circuit_spec, presentation_spec)
    plan = best(circuit_spec, presentation_spec)

    assert relation_pairs(result) == [
        (SAME_ROW, "CN1", "C115"), (RIGHT_OF, "CN1", "C115"), (NEAR, "C115", "CN1"),
        (SAME_ROW, "CN1", "C116"), (RIGHT_OF, "CN1", "C116"), (NEAR, "C116", "CN1"),
        (SAME_ROW, "CN1", "D1"), (RIGHT_OF, "CN1", "D1"), (NEAR, "D1", "CN1"),
    ]
    assert [(item.kind, item.nets) for item in result.obligations] == [
        (DIRECT_WIRE, (RAIL,)), (DIRECT_WIRE, (GND,)),
        (UNIFORM_GND, (GND,)), (OWNED_BRANCH, (RAIL,)),
        (GND_OUTLET, (GND,)),
    ]
    (outlet,) = symbols_for(plan, GND)
    assert attached_to(plan, outlet, "D1.2"), "缺省序下 D1 就是离入口最远的那条支路"
    assert outlet.rotation in (0.0, 180.0)
    assert from_the_inlet(plan, SAMPLE_BRANCHES, side="right") == [
        "C115", "C116", "D1"
    ]
    clean(plan, circuit_spec, presentation_spec)


def test_scene_4_the_order_and_the_values_stay_off_the_wires():
    """§五.8 的老场景在新声明下照旧：长文字 + 大体格也不压线、零硬违规。"""
    circuit_spec, presentation_spec = sample(
        values={"C115": "330uF/35V", "C116": "330uF/35V"}
    )
    plan = best(circuit_spec, presentation_spec)

    assert {item.text for item in plan.texts} >= {"330uF/35V", "SMCJ28CA"}
    assert from_the_inlet(plan, SAMPLE_BRANCHES, side="right") == [
        "D1", "C115", "C116"
    ]
    clean(plan, circuit_spec, presentation_spec)


# ============================================================ 3. 校验三态（§三.4）


def test_spec_refuses_a_designator_this_module_does_not_list():
    """未知位号：`branchOrder` 的位号必须在本模块 `parts` 里（spec 层点名）。"""
    with pytest.raises(PresentationSpecError) as caught:
        declared(order=("C9", "D1"))

    message = str(caught.value)
    assert "modules[0].branchOrder[0] is 'C9'" in message
    assert "parts does not list" in message
    assert "CN1, D1, C115, C116" in message


def test_spec_refuses_a_designator_named_twice():
    with pytest.raises(PresentationSpecError) as caught:
        declared(order=("D1", "D1", "C115"))

    assert "already named" in str(caught.value)
    assert "modules[0].branchOrder[1]" in str(caught.value)


def test_the_grammar_refuses_an_order_that_names_the_inlet():
    """位号不是本模块 shunt：入口出现在顺序里 → 语法 `circuit-invalid` 点名它是什么。"""
    result = bind(inlet_circuit(), declared(order=("CN1", "D1")))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "CN1"
    assert "it is the inlet of this module" in failure.detail
    assert "branchOrder" in failure.detail
    assert "modules[inlet].branchOrder" in failure.action


def test_the_grammar_refuses_an_order_that_names_a_part_across_other_nets():
    spec = base088.circuit(
        [base088.part("CN1", "XT30PW-M"), base088.part("D1", "CAP-TH_BD10.0-P5.00",
                                                       "SMCJ28CA"),
         base088.part("R9", "R0402", "10k")],
        [base088.net(RAIL, "power", ["CN1.1", "D1.1", "R9.1"]),
         base088.net("SENSE", "signal", ["R9.2"]),
         base088.net(GND, "gnd", ["CN1.2", "D1.2"])],
        interfaces=[{"net": RAIL, "direction": "input", "role": "rail",
                     "provenance": PROV, "part": "CN1"}],
    )
    result = bind(spec, declared(branches=("D1",), order=("R9", "D1"),
                                 parts=("CN1", "D1", "R9")))

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "R9"
    assert f"not across {RAIL} and {GND}" in failure.detail


def test_the_grammar_module_carries_no_designator_or_order_of_its_own():
    """053 §6：顺序来自文档。语法表里除 docstring 外不许出现场景专用常量——
    088 已有那条查本模块全文，这里只把「本批新增的顺序代码」那一段单独钉一次。"""
    import ast
    import pathlib

    source = pathlib.Path(power_entry.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(
                body[0].value, ast.Constant
            ):
                docstrings.add(id(body[0].value))
    literals = [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    for token in ("D1", "C115", "C116", "C117", "SMCJ", "330uF"):
        assert not any(token in value for value in literals), token


# ======================================================= 4. spec 封闭性（§三.7）


def test_an_old_module_round_trips_byte_for_byte_without_the_new_key():
    """缺省不写出：没有 `branchOrder` 的模块逐字节、哈希、版本都不动。"""
    payload = {
        "kind": "boardwise-presentation-spec",
        "specVersion": PRESENTATION_SPEC_VERSION,
        "modules": [{"id": "inlet", "parts": ["CN1", "C115"],
                     "role": "the inlet", "grammarRef": "power-entry"}],
        "grammarRef": "power-entry",
    }
    spec = PresentationSpec.from_dict(payload)

    assert "branchOrder" not in spec.to_jsonable()["modules"][0]
    assert spec.modules[0].branch_order == []
    again = PresentationSpec.from_dict(spec.to_jsonable())
    assert json.dumps(again.to_jsonable(), sort_keys=True) == json.dumps(
        spec.to_jsonable(), sort_keys=True
    )
    assert again.sha256() == spec.sha256()
    assert PRESENTATION_SPEC_VERSION == 1


def test_a_stated_order_survives_the_round_trip_and_changes_the_digest():
    spec = declared(order=("D1", "C115"))
    module = spec.to_jsonable()["modules"][0]

    assert module["branchOrder"] == ["D1", "C115"]
    again = PresentationSpec.from_dict(spec.to_jsonable())
    assert again.modules[0].branch_order == ["D1", "C115"]
    assert again.sha256() == spec.sha256()
    assert again.sha256() != undeclared().sha256()


def test_the_module_schema_is_still_closed_and_names_the_key_it_refuses():
    with pytest.raises(PresentationSpecError) as caught:
        PresentationSpec.from_dict({
            "grammarRef": "power-entry",
            "modules": [{"id": "inlet", "parts": ["CN1"], "role": "the inlet",
                         "branchorder": ["CN1"]}],
        })

    assert "branchorder" in str(caught.value)


# ========================================================== 5. 页级实测（§三.6）


def test_scene_6_at_page_level_the_module_keeps_its_outlet_and_the_page_keeps_flags():
    """§三.6 实测：页级 GND 仍走 069 旗（088 场景 10 钉的就是它），模块自己的出处
    符号跟着模块画进页里；**069 v3 既有行为一行未改**，页级 verdict 不回归。"""
    circuit_spec, presentation_spec = page_pair()

    module = presentation_spec.module("inlet")
    local_circuit, local_presentation = pc._module_view(
        circuit_spec, presentation_spec, module
    )
    local_result = base088.compile_module(local_circuit, local_presentation)
    assert local_result.ok, local_result.render_failures()
    local_outlets = symbols_for(local_result.best(), GND)
    assert len(local_outlets) == 1

    result = pc.compile_page(
        circuit_spec, presentation_spec, library(),
        pc.PageCompileBudget(page_box=base088.PAGE_BOX),
    )
    assert result.ok, "\n".join(item.render() for item in result.failures)
    page = result.pages[0]
    assert page.port_kinds()[GND] == {pc.PAGE_PORT_FLAG}
    assert page.port_kinds()[RAIL] == {pc.PAGE_PORT_WIRE}
    assert page.verdict != "fail"
    # 页上那条地：模块自己的出处符号 + 页在模块边界上的旗，各说各的（实测两个符号，
    # 一个落在 inlet 模块框内、一个是跨模块的边界表达）。
    module_outlets = [
        symbol for symbol in page.plan.power_symbols
        if symbol.net == GND
        and page.module("inlet").frame[1] <= symbol.y <= page.module("inlet").frame[3]
    ]
    assert len(module_outlets) == 1


def test_the_page_slice_carries_the_stated_branch_order_and_the_module_declaration():
    """页级切片要带上 `branchOrder`，否则页里的 inlet 按位号排、独立编的按声明排。"""
    circuit_spec, presentation_spec = sample()
    module = presentation_spec.module("inlet")
    local_circuit, local_presentation = pc._module_view(
        circuit_spec, presentation_spec, module
    )

    assert local_presentation.modules[0].branch_order == ["D1", "C115", "C116"]
    local_result = base088.compile_module(local_circuit, local_presentation)
    assert local_result.ok, local_result.render_failures()
    assert from_the_inlet(local_result.best(), SAMPLE_BRANCHES, side="right") == [
        "D1", "C115", "C116"
    ]
    assert len(symbols_for(local_result.best(), GND)) == 1
