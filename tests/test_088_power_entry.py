"""088：第四种画法语法 `power-entry`——电源入口模块（离线半）。

这一批只做离线半：语法 + 编译器接入 + 场景 + SVG 预览（预览生成器在
`tools/088_previews.py`，真机落图归 089）。测试的分工，一句话一条：

1. **事实通道**：`SpecOpenInterface.part`（088 §一.2）是可选的——旧文档逐字节不变、
   哈希不动、schema 封闭性不破、spec_version 不升；
2. **绑定判据**（§一）：rail/gnd 按 class、entry 按文档里那条事实（**不是**拓扑推导）、
   shunt 是其余每颗跨两轨的两脚件；缺事实 → `facts-missing` 点名去写哪儿，
   连接对不上 → `circuit-invalid` 点名哪颗；
3. **约束与义务**（§二）：`same-row`（入口侧的轨脚落在轨线上）、`left-of`/`right-of`
   （由 `sidePreferences.input` 驱动，**不新增 kind**）、`near`；义务 = 两条实体轨
   （一轨一条 `direct-wire`，见测试里的实测说明）+ `uniform-gnd` + `owned-branch`；
4. **场景**（§五）：岳样板、镜像、最小、多支路、两类拒绝、长文字、窄区域、
   页级集成——每个场景一条测试，断言的是场景表"期望"那一列；
5. **实测记录**：两处**跨模块不一致**（页级 mainPath 与可读性检查器对"宽轨"的判断、
   以及有页面时锚点吸附越过页边）在本文件里各钉一条测试，名字写清
   "今天是这样、原因已测量、修法属公共路径"——它们不是本批的契约，是本批的实测。

CircuitSpec / PresentationSpec / SymbolProfile 全部手写字面量，不建夹具文件；符号库
里除入口连接器、TVS、体格电解三颗本批新增形状外，直接复用 053B 的 `library()`
（同一颗 0402 只有一个定义）。
"""

from __future__ import annotations

import json
import re

import pytest

import test_053b_drawcompiler as b053

from boardwise.core.circuitspec import (
    CIRCUIT_SPEC_VERSION,
    CircuitSpec,
    CircuitSpecError,
)
from boardwise.core.presentationspec import (
    GRAMMARS,
    PresentationSpec,
    PresentationSpecError,
)
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import grammar
from boardwise.engines import pagecompiler as pc
from boardwise.engines import readability
from boardwise.engines.grammar import base
from boardwise.engines.grammar.base import (
    DIRECT_WIRE,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    GND_OUTLET,
    LEFT_OF,
    NEAR,
    OWNED_BRANCH,
    RIGHT_OF,
    SAME_ROW,
    UNIFORM_GND,
    DrawingGrammar,
)

PROV = "verified_recipe"
AI = "ai_asserted"

#: 岳样板的两条轨。轨名写成电压声明形态（`+24V`）是 011c / 坑 40 的命名约定：
#: 容值与分压电阻共处的输入轨用声明名，规则才不当它是未声明网。
RAIL = "+24V"
GND = "GND"


# --------------------------------------------------------------- 器件库夹具


def connector(ref: str = "XT30PW-M") -> SymbolProfile:
    """入口连接器（XT30PW-M，两脚）：两脚在左侧竖排 80，体在脚右边。

    这个"脚朝画内、两脚竖跨两轨"的形状是本语法的关键几何：入口终结两条轨的
    输入端，本体不进支路区。脚跨距 80 与 `C0402`/`CAP-TH` 的 ±40 一致，所以
    两条轨在图上正好是两条行。
    """
    return SymbolProfile(
        symbol_ref=ref, title="2-pin power inlet",
        body=(-30.0, -50.0, 30.0, 50.0),
        pins=b053._pins((("1", (-50.0, 40.0), "left"),
                         ("2", (-50.0, -40.0), "left"))),
    )


def electrolytic(ref: str = "CAP-TH_BD10.0-P5.00") -> SymbolProfile:
    """330uF 体格电解（THT BD10）：脚 ±40，体比 0402 大一圈（§五.8 的"大体格"）。

    值**故意写成 ASCII 的 `330uF`**：`tests/` 里的字符串是 011d 那张语料
    （`_corpus_tokens`）的取材面，而它的 071 §1C 不变量只认它自己列的两种拼法
    （`pF|nF|uF|MF` 与中缀记法），写 `NNNµF`（微符号 + F）会给那张语料多出一个
    合不上模式的令牌——那是既有断言，本批不动它，改自己的写法。
    """
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-15.0, -25.0, 15.0, 25.0),
        pins=b053._pins((("1", (0.0, 40.0), "up"), ("2", (0.0, -40.0), "down"))),
    )


def library(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    """053B 的库 + 本批三颗形状 + 两条轨的旗标（库完整，免得测试顺带踩缺旗回退）。"""
    book = b053.library()
    for profile in (
        connector(), electrolytic(), b053.flag("PWR-+24V"), b053.flag("PWR-V24"),
    ):
        book[profile.symbol_ref] = profile
    book.update(overrides)
    return book


# ------------------------------------------------------------- 手写 spec 构造


BRANCH: dict[str, tuple[str, str]] = {
    "D1": ("CAP-TH_BD10.0-P5.00", "SMCJ28CA"),
    "C115": ("CAP-TH_BD10.0-P5.00", "330uF"),
    "C116": ("CAP-TH_BD10.0-P5.00", "330uF"),
    "C117": ("CAP-TH_BD10.0-P5.00", "330uF"),
}


def part(part_id: str, symbol: str, value: str = "", provenance: str = PROV) -> dict:
    return {
        "id": part_id, "symbolRef": symbol, "value": value, "provenance": provenance,
    }


def net(net_id: str, cls: str, members: list[str], provenance: str = PROV) -> dict:
    return {
        "id": net_id, "class": cls, "members": list(members), "provenance": provenance,
    }


def circuit(parts: list[dict], nets: list[dict], interfaces=None, nc=None) -> CircuitSpec:
    payload: dict = {"parts": parts, "nets": nets}
    if interfaces is not None:
        payload["openInterfaces"] = list(interfaces)
    if nc:
        payload["nc"] = list(nc)
    return CircuitSpec.from_dict(payload)


def presentation(grammar_ref: str = "power-entry", **overrides) -> PresentationSpec:
    payload: dict = {"grammarRef": grammar_ref}
    payload.update(overrides)
    return PresentationSpec.from_dict(payload)


def inlet_circuit(
    shunts: tuple[str, ...] = ("D1", "C115", "C116"),
    *,
    rail: str = RAIL,
    gnd: str = GND,
    part_field: str | None = "CN1",
    interface: bool = True,
    conn_symbol: str = "XT30PW-M",
    values: dict[str, str] | None = None,
    provenance: str = PROV,
    entry_provenance: str = PROV,
) -> CircuitSpec:
    """岳样板那条电路：连接器 + N 条两脚支路，rail↔gnd 全并联。"""
    parts = [part("CN1", conn_symbol, conn_symbol, entry_provenance)]
    rail_members = ["CN1.1"]
    gnd_members = ["CN1.2"]
    for part_id in shunts:
        symbol, value = BRANCH[part_id]
        parts.append(part(part_id, symbol, (values or {}).get(part_id, value)))
        rail_members.append(f"{part_id}.1")
        gnd_members.append(f"{part_id}.2")
    interfaces = None
    if interface:
        entry: dict = {
            "net": rail, "direction": "input", "role": "rail", "provenance": PROV,
        }
        if part_field is not None:
            entry["part"] = part_field
        interfaces = [entry]
    return circuit(
        parts,
        [net(rail, "power", rail_members), net(gnd, "gnd", gnd_members)],
        interfaces=interfaces,
    )


def inlet_presentation(*, side: str = "right", rail: str = RAIL, gnd: str = GND,
                       **overrides) -> PresentationSpec:
    payload: dict = {
        "sidePreferences": {"input": side},
        "directWiringObligations": [
            {"nets": [rail, gnd], "note": "the rails are solid conductors"},
        ],
    }
    payload.update(overrides)
    return presentation(**payload)


def compile_module(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec,
                   *, budget: dc.CompileBudget | None = None):
    return dc.compile(
        circuit_spec, presentation_spec, library(),
        budget if budget is not None else dc.CompileBudget(),
    )


def bind(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    return grammar.grammar_for("power-entry").bind(circuit_spec, presentation_spec)


def best(circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    result = compile_module(circuit_spec, presentation_spec)
    assert result.ok, result.render_failures()
    return result.best()


def rows(plan, circuit_spec: CircuitSpec) -> dict[str, float]:
    """``member -> y`` for every pin the plan places (read through the profile)."""
    out: dict[str, float] = {}
    for spec_net in circuit_spec.nets:
        for member in spec_net.members:
            point = b053.pin_point(plan, member, library())
            if point is not None:
                out[member] = point[1]
    return out


def one_row(plan, circuit_spec: CircuitSpec, members: list[str]) -> float:
    """The y all these pins share, or an assertion failure."""
    where = rows(plan, circuit_spec)
    values = sorted({where[member] for member in members})
    assert len(values) == 1, f"{members} are not one row: {values}"
    return values[0]


def wire_for(plan, net_id: str) -> list:
    """Every wire segment the plan draws for this net."""
    return [item for item in plan.segments if item.net == net_id]


def touches(segments, point: tuple[float, float]) -> bool:
    """Is this point on any of these segments (endpoint or interior)?"""
    for item in segments:
        points = item.points
        for first, second in zip(points, points[1:]):
            if _on_segment(point, first, second):
                return True
    return False


def _on_segment(point, start, end) -> bool:
    (x, y), (x1, y1), (x2, y2) = point, start, end
    if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) > 1e-6:
        return False
    return (
        min(x1, x2) - 1e-6 <= x <= max(x1, x2) + 1e-6
        and min(y1, y2) - 1e-6 <= y <= max(y1, y2) + 1e-6
    )


def checked(plan, circuit_spec: CircuitSpec, presentation_spec: PresentationSpec):
    return readability.check(
        plan, circuit_spec, presentation_spec, library(),
        page_box=None, keepouts=(),
    )


def clean(plan, circuit_spec: CircuitSpec, presentation_spec: PresentationSpec) -> None:
    result = checked(plan, circuit_spec, presentation_spec)
    assert result.hard_violations == [], [
        item.render() for item in result.hard_violations
    ]


# ============================================================ 1. 事实通道（§一.2）


def test_the_part_field_is_optional_and_an_old_document_round_trips_byte_for_byte():
    """缺省不写出：旧文档的规范 JSON 里根本没有这个键，哈希因此不动。"""
    spec = inlet_circuit(part_field=None)
    payload = spec.to_jsonable()

    assert set(payload["openInterfaces"][0]) == {
        "net", "direction", "role", "provenance",
    }
    assert json.dumps(payload, sort_keys=True) == json.dumps(
        CircuitSpec.from_dict(payload).to_jsonable(), sort_keys=True
    )
    assert CircuitSpec.from_dict(payload).sha256() == spec.sha256()


def test_a_stated_part_survives_the_round_trip_and_changes_the_digest():
    spec = inlet_circuit()
    payload = spec.to_jsonable()

    assert payload["openInterfaces"][0]["part"] == "CN1"
    again = CircuitSpec.from_dict(payload)
    assert again.sha256() == spec.sha256()
    assert again.open_interfaces[0].part == "CN1"
    assert spec.sha256() != inlet_circuit(part_field=None).sha256()


def test_the_spec_version_is_not_bumped_by_an_optional_addition():
    """纯可选增量：升版本会把老文档一次全打回（088 §一.2）。"""
    assert CIRCUIT_SPEC_VERSION == 1


def test_the_interface_schema_is_still_closed_and_names_the_key_it_refuses():
    payload = inlet_circuit().to_jsonable()
    payload["openInterfaces"][0]["connector"] = "CN1"

    with pytest.raises(CircuitSpecError) as caught:
        CircuitSpec.from_dict(payload)

    assert "connector" in str(caught.value)


# ============================================================ 2. 注册与发现性（§三）


def test_power_entry_is_registered_on_every_face_a_grammar_must_be():
    assert "power-entry" in grammar.NAMES
    assert grammar.NAMES == tuple(grammar._CLASSES)
    assert grammar.NAMES == tuple(grammar.ROLES_BY_GRAMMAR)
    assert grammar.NAMES == GRAMMARS
    instance = grammar.grammar_for("power-entry")
    assert isinstance(instance, DrawingGrammar)
    assert instance.name == "power-entry"
    assert grammar.ROLES_BY_GRAMMAR["power-entry"] == ("entry", "shunt", "rail", "gnd")


def test_the_spec_literal_and_the_implementation_name_are_one_string():
    """`GRAMMARS` 的字面量与实现名同串，查表就不可能半匹配（053 §三）。"""
    assert "power-entry" in GRAMMARS
    spec = presentation()
    assert spec.grammar_ref == "power-entry"
    assert spec.grammar_ref in grammar.NAMES

    with pytest.raises(PresentationSpecError):
        presentation("power_entry")  # 拼法不一致就不是同一个字面量


def test_the_grammar_module_carries_no_scenario_specific_constant():
    """053 §六：语法表里不许出现场景专用常量（位号/值/封装名一个都不许）。

    查的是**代码里的字符串**：docstring（模块的、函数的）是给人读的说明，举例不
    算常量，所以走 `ast` 取非 docstring 的 `Constant` 节点，而不是拿文本 grep 一遍。
    """
    import ast
    import pathlib

    source = pathlib.Path(grammar.power_entry.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", [])
        if body and isinstance(body[0], ast.Expr) and isinstance(
            body[0].value, ast.Constant
        ):
            docstrings.add(id(body[0].value))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    comments = [line for line in source.splitlines() if line.strip().startswith("#")]
    for token in ("CN1", "C115", "C116", "330uF", "SMCJ", "XT30", "R0402", "+24V"):
        assert not any(token in value for value in literals), token
        assert not any(token in line for line in comments), token
    for value in literals:
        assert not re.search(r"scene\s*\d", value, re.IGNORECASE), value


# ============================================================ 3. 绑定判据（§一）


def test_the_rail_and_the_ground_are_read_from_the_classes_and_the_roles_bind():
    result = bind(inlet_circuit(), inlet_presentation())

    assert result.ok, result.failures
    bound = {item.role: item.part_id for item in result.bindings}
    assert bound["rail"] == RAIL
    assert bound["gnd"] == GND
    assert bound["entry"] == "CN1"
    assert sorted(
        item.part_id for item in result.bindings if item.role == "shunt"
    ) == ["C115", "C116", "D1"]
    assert base.is_net_role("rail") and not base.is_net_role("entry")
    assert base.NET_ROLES[-1] == "rail"


def test_the_entry_is_the_part_the_document_names_not_the_one_topology_suggests():
    """并联支路与连接器同构（都是跨两轨的两脚件），所以这条事实只能由文档给。"""
    topology_only = bind(inlet_circuit(interface=False), inlet_presentation())
    assert topology_only.ok is False
    assert [item.category for item in topology_only.failures] == [
        FAILURE_FACTS_MISSING
    ]

    # 换一条事实，入口就换人：文档说是谁就是谁，语法不去猜"连接器长什么样"。
    for named in ("CN1", "D1", "C115"):
        result = bind(inlet_circuit(part_field=named), inlet_presentation())
        assert result.ok is True
        bound = {item.role: item.part_id for item in result.bindings}
        assert bound["entry"] == named
        assert named not in [
            item.part_id for item in result.bindings if item.role == "shunt"
        ]


def test_every_other_two_terminal_part_across_the_two_rails_is_a_shunt():
    result = bind(
        inlet_circuit(shunts=("D1", "C115", "C116", "C117")), inlet_presentation()
    )
    shunts = sorted(
        item.part_id for item in result.bindings if item.role == "shunt"
    )
    assert shunts == ["C115", "C116", "C117", "D1"]


def test_a_part_that_is_not_across_both_rails_is_never_a_shunt():
    """TVS 与体电容同构、封装备注不读，但"跨 rail↔gnd"这条结构判据要真的成立。"""
    spec = circuit(
        [part("CN1", "XT30PW-M"), part("C1", "C0402"), part("R9", "R0402")],
        [
            net(RAIL, "power", ["CN1.1", "C1.1"]),
            net("SENSE", "signal", ["R9.1"]),
            net(GND, "gnd", ["CN1.2", "C1.2", "R9.2"]),
        ],
        interfaces=[{"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"}],
    )
    result = bind(spec, inlet_presentation())

    assert result.ok is True
    assert [item.part_id for item in result.bindings if item.role == "shunt"] == ["C1"]


def test_the_row_and_the_end_relations_follow_the_input_side_preference():
    """mirror 由 sidePreferences 驱动（不是场景常量）：只换 kind，不换关系。"""
    right = bind(inlet_circuit(), inlet_presentation(side="right"))
    left = bind(inlet_circuit(), inlet_presentation(side="left"))

    def kinds(result):
        found: dict[tuple[str, str], str] = {}
        for item in result.constraints:
            found[(item.subject, item.object)] = item.kind
        return found

    (for_right, for_left) = (kinds(right), kinds(left))
    for shunt in ("D1", "C115", "C116"):
        assert for_right[("CN1", shunt)] == RIGHT_OF
        assert for_left[("CN1", shunt)] == LEFT_OF
    assert "at-end" not in base.CONSTRAINT_KINDS


def test_the_constraints_are_the_row_the_end_and_the_local_group():
    result = bind(inlet_circuit(shunts=("C115",)), inlet_presentation(side="right"))

    pairs = [(item.kind, item.subject, item.object) for item in result.constraints]
    assert pairs == [
        (SAME_ROW, "CN1", "C115"),
        (RIGHT_OF, "CN1", "C115"),
        (NEAR, "C115", "CN1"),
    ]
    row = result.constraints[0]
    assert RAIL in row.reason and "1" in row.reason
    assert "088 sec.2" in row.reason


def test_the_obligations_are_the_two_rails_one_ground_and_the_owned_branches():
    result = bind(inlet_circuit(), inlet_presentation())

    assert [(item.kind, item.nets) for item in result.obligations] == [
        (DIRECT_WIRE, (RAIL,)),
        (DIRECT_WIRE, (GND,)),
        (UNIFORM_GND, (GND,)),
        (OWNED_BRANCH, (RAIL,)),
        # 2026-10-02 岳裁决②（无条件）：底轨要有且只要一个 GND 出处符号。第五条义务
        # 由 088b 加，且**不再**门控于"是否声明了模块"——本条断言随之更新。
        (GND_OUTLET, (GND,)),
    ]
    assert "solid conductor" in result.obligations[0].reason
    assert "unconditional" in result.obligations[-1].reason


def test_the_weakest_provenance_travels_into_the_evidence():
    """052 §4：草稿态要看得见——最弱依据一路带进 evidence。"""
    spec = inlet_circuit(entry_provenance=AI)
    result = bind(spec, inlet_presentation())

    entry = next(item for item in result.bindings if item.role == "entry")
    assert "provenance=ai_asserted" in entry.evidence
    assert base.weakest_provenance(AI, PROV) == base.PROVENANCE_AI


def test_bind_is_deterministic_byte_for_byte():
    spec, pres = inlet_circuit(), inlet_presentation()
    first, second = bind(spec, pres), bind(
        CircuitSpec.from_dict(spec.to_jsonable()),
        PresentationSpec.from_dict(pres.to_jsonable()),
    )

    assert first == second
    assert json.dumps(first.to_jsonable(), sort_keys=True) == json.dumps(
        second.to_jsonable(), sort_keys=True
    )


# ============================================================ 4. 拒绝与措辞（§一/§五）


@pytest.mark.parametrize("interface,part_field", [(False, None), (True, None)])
def test_which_connector_feeds_the_rail_is_the_pinned_facts_missing_wording(
    interface, part_field
):
    result = bind(inlet_circuit(interface=interface, part_field=part_field),
                  inlet_presentation())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_FACTS_MISSING
    assert failure.subject == RAIL
    assert "state it in openInterfaces[].part" in failure.action
    assert RAIL in failure.action
    assert "parallel branch" in failure.detail


def test_an_inlet_that_does_not_exist_is_circuit_invalid_and_names_it():
    result = bind(inlet_circuit(part_field="CN9"), inlet_presentation())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "CN9"
    assert "does not declare" in failure.detail
    assert "CN1" in failure.detail


def test_an_inlet_that_is_not_across_both_rails_is_circuit_invalid():
    """连接器只接到轨上、没接到地：点名它实际连着谁，并给可执行动作。"""
    spec = circuit(
        [part("CN1", "XT30PW-M"), part("C1", "C0402")],
        [
            net(RAIL, "power", ["CN1.1", "C1.1"]),
            net(GND, "gnd", ["C1.2"]),
        ],
        interfaces=[{"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"}],
    )
    result = bind(spec, inlet_presentation())

    assert result.ok is False
    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert failure.subject == "CN1"
    assert "two-terminal part across" in failure.detail
    assert "1→" + RAIL in failure.detail
    assert "nets[].members" in failure.action


def test_an_inlet_across_the_rail_and_a_signal_net_is_circuit_invalid():
    spec = circuit(
        [part("CN1", "XT30PW-M"), part("C1", "C0402")],
        [
            net(RAIL, "power", ["CN1.1", "C1.1"]),
            net("SENSE", "signal", ["CN1.2"]),
            net(GND, "gnd", ["C1.2"]),
        ],
        interfaces=[{"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"}],
    )
    result = bind(spec, inlet_presentation())

    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "2→SENSE" in failure.detail


def test_two_stated_inlets_on_one_rail_are_circuit_invalid():
    spec = inlet_circuit(shunts=("C115",))
    spec = CircuitSpec.from_dict({
        **spec.to_jsonable(),
        "openInterfaces": [
            {"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"},
            {"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "C115"},
        ],
    })
    result = bind(spec, inlet_presentation())

    (failure,) = result.failures
    assert failure.category == FAILURE_CIRCUIT_INVALID
    assert "one rail has one inlet" in failure.detail


def test_a_missing_class_is_facts_missing_one_per_class():
    no_gnd = circuit(
        [part("CN1", "XT30PW-M"), part("C1", "C0402")],
        [net(RAIL, "power", ["CN1.1", "C1.1"]),
         net("RET", "signal", ["CN1.2", "C1.2"])],
        interfaces=[{"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"}],
    )
    no_power = circuit(
        [part("CN1", "XT30PW-M"), part("C1", "C0402")],
        [net("VIN", "signal", ["CN1.1", "C1.1"]),
         net("RET", "gnd", ["CN1.2", "C1.2"])],
        interfaces=[{"net": "VIN", "direction": "input", "role": "rail",
                     "provenance": PROV, "part": "CN1"}],
    )

    for spec, word, action in (
        (no_gnd, "no net of class 'gnd'", "nets[].class"),
        (no_power, "no net of class 'power'", "nets[].class"),
    ):
        result = bind(spec, inlet_presentation())
        assert result.ok is False
        (failure,) = result.failures
        assert failure.category == FAILURE_FACTS_MISSING
        assert word in failure.detail
        assert action in failure.action


def test_only_a_direction_that_means_the_supply_enters_here_counts():
    """`load`/`output` 是同一条模块的另一端，不是喂给它的一端。"""
    spec = inlet_circuit(interface=False)
    spec = CircuitSpec.from_dict({
        **spec.to_jsonable(),
        "openInterfaces": [
            {"net": RAIL, "direction": "load", "role": "rail", "provenance": PROV, "part": "CN1"},
        ],
    })
    result = bind(spec, inlet_presentation())

    assert result.ok is False
    assert result.failures[0].category == FAILURE_FACTS_MISSING


# ============================================================ 5. 场景（§五）


def test_scene_1_the_sample_compiles_into_two_solid_rails_and_hanging_branches():
    """岳样板：三支路下垂，两条轨各一条实体横线，位号/容值不压线。"""
    spec, pres = inlet_circuit(), inlet_presentation(side="right")
    plan = best(spec, pres)

    rail_row = one_row(plan, spec, [f"{item}.1" for item in ("CN1", "D1", "C115",
                                                             "C116")])
    gnd_row = one_row(plan, spec, [f"{item}.2" for item in ("CN1", "D1", "C115",
                                                            "C116")])
    assert rail_row > gnd_row
    assert len(wire_for(plan, RAIL)) >= 1
    assert len(wire_for(plan, GND)) >= 1
    assert plan.labels == []
    clean(plan, spec, pres)

    again = dc.LayoutPlan.from_dict(plan.to_jsonable())
    assert again.geometry_sha256() == plan.geometry_sha256()


def test_scene_1_the_rail_is_a_solid_wire_and_still_carries_its_069_flag():
    """§二 的实测结论：`direct-wire` 义务在 `_expression_style` 里先于 class 被问，
    所以电源网默认的那条"高扇出即总线"规则压不过它——两条轨都是实体线；同时
    069 §7 的"电源网要自带旗"照常出，端头旗挂在入口侧的轨脚上。

    **2026-10-02 岳裁决①确认保持**：088 §七 自报的第一处与样板偏差（样板把 +24V 旗挂在
    轨远端）**不改**——旗继续挂入口侧轨脚，理由与位置都留在本测试里；088b 把这条注释从
    「待裁决」转成「裁决确认」，这一半的断言未动。

    **2026-10-02 岳裁决②（无条件）**：底轨要有一个、且只要一个 GND 出处符号——本条原先
    断言「底轨没有符号」（那是 088 自报的第二处偏差、钉的"今天是这样、待裁决"）。裁决到
    了，断言随之改成它该有的样子：恰一个 `PWR-GND`、挂在本网离入口最远的那只脚上、竖直。
    无条件，所以这份不声明模块的 088 夹具同样出符号（门控方案经实测后被主代理否决）。"""
    spec, pres = inlet_circuit(), inlet_presentation(side="right")
    plan = best(spec, pres)

    flags = [item for item in plan.power_symbols if item.net == RAIL]
    assert len(flags) == 1
    assert plan.labels == []

    # 轨线本体：每个成员脚都落在本网画出的线上（不是各自一个旗点靠名字合并）。
    rail_wires = wire_for(plan, RAIL)
    for member in ("CN1.1", "D1.1", "C115.1", "C116.1"):
        point = b053.pin_point(plan, member, library())
        assert point is not None
        assert touches(rail_wires, point), member
    assert sum(_length(item.points) for item in rail_wires) > 100.0

    # 回来那条也必须是线（`owning` 的旗不是"地表达统一"的替代品），**并且**线上有且
    # 只有一个出处符号：2026-10-02 岳裁决②（无条件）。
    gnd_wires = wire_for(plan, GND)
    for member in ("CN1.2", "D1.2", "C115.2", "C116.2"):
        assert touches(gnd_wires, b053.pin_point(plan, member, library())), member
    (outlet,) = [item for item in plan.power_symbols if item.net == GND]
    assert outlet.symbol_ref == "PWR-GND"
    assert outlet.rotation in (0.0, 180.0), outlet.rotation
    entry_pin = b053.pin_point(plan, "CN1.2", library())
    far = max(
        ("D1.2", "C115.2", "C116.2"),
        key=lambda member: abs(
            b053.pin_point(plan, member, library())[0] - entry_pin[0]
        ),
    )
    far_pin = b053.pin_point(plan, far, library())
    # 符号由那只远端脚的引线接上：该网有一段线同时碰到脚和符号锚点。
    assert any(
        touches([segment], (outlet.x, outlet.y)) and touches([segment], far_pin)
        for segment in gnd_wires
    ), far
    assert abs(outlet.x - far_pin[0]) < abs(outlet.x - entry_pin[0]), (
        "the outlet hangs at the rail's far end, not at the inlet"
    )


def test_scene_1_the_inlet_terminates_the_rails_at_the_input_end():
    """入口在轨的输入端端头：所有支路都在它的同一侧，它是那条行的最后一个脚。"""
    spec, pres = inlet_circuit(), inlet_presentation(side="right")
    plan = best(spec, pres)

    where = rows(plan, spec)
    entry = b053.pin_point(plan, "CN1.1", library())
    others = [b053.pin_point(plan, f"{item}.1", library())
              for item in ("D1", "C115", "C116")]
    assert entry[0] > max(point[0] for point in others)
    assert entry[1] == where["CN1.1"]

    mirrored = best(*((inlet_circuit(), inlet_presentation(side="left"))))
    mirrored_entry = b053.pin_point(mirrored, "CN1.1", library())
    mirrored_others = [b053.pin_point(mirrored, f"{item}.1", library())
                       for item in ("D1", "C115", "C116")]
    assert mirrored_entry[0] < min(point[0] for point in mirrored_others)


def _length(points) -> float:
    return sum(
        abs(second[0] - first[0]) + abs(second[1] - first[1])
        for first, second in zip(points, points[1:])
    )


def test_scene_2_the_input_on_the_left_is_the_same_drawing_turned_round():
    right, left = (best(inlet_circuit(), inlet_presentation(side="right")),
                   best(inlet_circuit(), inlet_presentation(side="left")))

    for plan in (right, left):
        assert len(wire_for(plan, RAIL)) >= 1
        assert len(wire_for(plan, GND)) >= 1

    right_entry = b053.pin_point(right, "CN1.1", library())
    left_entry = b053.pin_point(left, "CN1.1", library())
    right_branches = [b053.pin_point(right, f"{item}.1", library())[0]
                      for item in ("D1", "C115", "C116")]
    left_branches = [b053.pin_point(left, f"{item}.1", library())[0]
                     for item in ("D1", "C115", "C116")]
    assert right_entry[0] > max(right_branches)
    assert left_entry[0] < min(left_branches)
    # 反转的是左右，不是上下：两条轨的先后不变。
    assert b053.pin_point(right, "CN1.1", library())[1] > b053.pin_point(
        right, "CN1.2", library())[1]
    assert b053.pin_point(left, "CN1.1", library())[1] > b053.pin_point(
        left, "CN1.2", library())[1]


def test_scene_3_the_minimal_inlet_is_one_connector_and_one_capacitor():
    spec, pres = inlet_circuit(shunts=("C115",)), inlet_presentation()
    result = compile_module(spec, pres)

    assert result.ok and len(result.candidates) >= 1
    plan = result.best()
    assert len(plan.parts) == 2
    assert one_row(plan, spec, ["CN1.1", "C115.1"])
    clean(plan, spec, pres)


def test_scene_4_four_branches_keep_both_rails_straight():
    members = ("CN1", "D1", "C115", "C116", "C117")
    spec, pres = inlet_circuit(shunts=members[1:]), inlet_presentation()
    plan = best(spec, pres)

    one_row(plan, spec, [f"{item}.1" for item in members])
    one_row(plan, spec, [f"{item}.2" for item in members])
    clean(plan, spec, pres)


def test_scene_8_long_values_and_a_big_electrolytic_stay_off_the_wires():
    spec = inlet_circuit(values={"C115": "330uF/35V", "C116": "330uF/35V"})
    pres = inlet_presentation()
    plan = best(spec, pres)

    assert {item.text for item in plan.texts} >= {"330uF/35V", "SMCJ28CA"}
    clean(plan, spec, pres)
    one_row(plan, spec, ["CN1.1", "D1.1", "C115.1", "C116.1"])


def test_scene_9_a_narrow_sheet_is_refused_with_the_measured_size_and_an_action():
    spec, pres = inlet_circuit(), inlet_presentation()
    result = compile_module(
        spec, pres, budget=dc.CompileBudget(page_box=(0.0, 0.0, 200.0, 150.0))
    )

    assert result.ok is False
    assert result.rejected, "a refusal has to say which variants were built and lost"
    (failure,) = [item for item in result.failures
                  if item.category == dc.FAILURE_LAYOUT_UNSAT]
    assert "canvas units" in failure.detail
    assert "200 x 150" in failure.detail
    assert "enlarge the region" in failure.action


def _page_circuit() -> CircuitSpec:
    return CircuitSpec.from_dict({
        "parts": [
            {"id": "CN1", "symbolRef": "XT30PW-M", "value": "XT30PW-M"},
            {"id": "C115", "symbolRef": "CAP-TH_BD10.0-P5.00", "value": "330uF"},
            {"id": "R1", "symbolRef": "R0402", "value": "10k"},
            {"id": "R2", "symbolRef": "R0402", "value": "10k"},
        ],
        "nets": [
            {"id": RAIL, "class": "power", "members": ["CN1.1", "C115.1", "R1.1"]},
            {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"]},
            {"id": GND, "class": "gnd", "members": ["CN1.2", "C115.2", "R2.2"]},
        ],
        "openInterfaces": [
            {"net": RAIL, "direction": "input", "role": "rail", "provenance": PROV, "part": "CN1"},
        ],
    })


def _page_presentation(*, main_path: bool = True) -> PresentationSpec:
    return PresentationSpec.from_dict({
        "modules": [
            {"id": "inlet", "parts": ["CN1", "C115"], "grammarRef": "power-entry",
             "role": "the 24 V inlet and its bulk capacitor"},
            {"id": "sense", "parts": ["R1", "R2"], "grammarRef": "voltage-divider",
             "role": "a divider on the rail"},
        ],
        "flow": [{"from": "inlet", "to": "sense", "mainPath": main_path}],
        "sidePreferences": {"input": "right"},
    })


PAGE_BOX = (0.0, 0.0, 1169.0, 826.0)


def test_scene_10_a_page_keeps_the_main_path_rail_as_one_wire_and_flags_the_ground():
    """§五.10：rail 标 mainPath 时实体线保留、GND 跨模块仍走旗（069 v3 不回归）。"""
    result = pc.compile_page(
        _page_circuit(), _page_presentation(), library(),
        pc.PageCompileBudget(page_box=PAGE_BOX),
    )

    assert result.ok, "\n".join(item.render() for item in result.failures)
    page = result.pages[0]
    kinds = page.port_kinds()
    assert kinds[RAIL] == {pc.PAGE_PORT_WIRE}
    assert kinds[GND] == {pc.PAGE_PORT_FLAG}
    assert {item.module for item in page.module("inlet").ports
            if item.net == RAIL} == {"inlet"}
    assert any(
        segment.net == RAIL and len(segment.points) >= 2
        for segment in page.plan.segments
    )
    assert page.verdict != "fail"


def test_scene_10_the_page_slices_each_module_and_carries_the_fact_with_it():
    """页级编译把电路按模块切片（`_module_view`）：切片必须带着 openInterfaces 的
    `part`，否则入口模块一进页就报 facts-missing——这就是编译侧那一处改动的用处。"""
    circuit_spec, presentation_spec = _page_circuit(), _page_presentation()
    module = presentation_spec.module("inlet")
    local_circuit, _local_presentation = pc._module_view(
        circuit_spec, presentation_spec, module
    )

    (interface,) = local_circuit.open_interfaces
    assert interface.part == "CN1"
    assert interface.net == RAIL
    assert local_circuit.part("CN1") is not None
    assert local_circuit.net(GND) is None or GND not in [
        item.net for item in local_circuit.open_interfaces
    ]


def test_a_main_path_mark_on_a_wide_rail_is_refused_while_the_compiler_draws_it():
    """实测到的跨模块不一致（不是本批契约，留给裁决）：

    `pagecompiler._net_style` 认 069 v3 的例外——mainPath 标在电源轨上时画整条线；
    但 `readability._check_main_paths` 的"可连线"判据用的是它自己那份 `_is_bus`
    （power 且成员数 > 3 即总线），于是**同一个网**一个画线、一个拒绝。岳样板那条
    轨有 4 个成员（连接器 + TVS + 2 电容 + 分压），一标 mainPath 整页就 0 候选；
    把轨缩到 3 个成员就过（上一条测试）。
    """
    spec = CircuitSpec.from_dict({
        **_page_circuit().to_jsonable(),
        "parts": [*_page_circuit().to_jsonable()["parts"],
                  {"id": "D1", "symbolRef": "CAP-TH_BD10.0-P5.00",
                   "value": "SMCJ28CA"}],
        "nets": [
            {"id": RAIL, "class": "power",
             "members": ["CN1.1", "D1.1", "C115.1", "R1.1"]},
            {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"]},
            {"id": GND, "class": "gnd",
             "members": ["CN1.2", "D1.2", "C115.2", "R2.2"]},
        ],
    })
    presentation_spec = PresentationSpec.from_dict({
        **_page_presentation().to_jsonable(),
        "modules": [
            {"id": "inlet", "parts": ["CN1", "D1", "C115"],
             "grammarRef": "power-entry", "role": "the inlet"},
            {"id": "sense", "parts": ["R1", "R2"],
             "grammarRef": "voltage-divider", "role": "a divider on the rail"},
        ],
    })
    result = pc.compile_page(
        spec, presentation_spec, library(), pc.PageCompileBudget(page_box=PAGE_BOX)
    )

    assert result.ok is False
    assert any(
        "no wire joins the two modules" in item.detail for item in result.failures
    )
    assert all(module.ok for module in result.modules.values()), (
        "两个模块各自都能编译，拒绝发生在页级"
    )


def test_a_stated_sheet_can_refuse_a_drawing_whose_snap_lands_outside_the_margin():
    """实测到的第二处公共路径问题（同样留给裁决，不在本批改）：

    `_anchor_to_page` 先按页边留出 `PAGE_MARGIN` 再把锚点吸到格点上，而
    `_overflow` 用的是 1e-6 容差——吸附最多能往外顶半格（2.5 单位），于是一张
    1130×785 能装下的 413×133 图被报成"放不下"。实测：岳样板在 1170×825 上
    box[0] = 18 < 20（页边 20），0 候选；同一条电路不声明页面（`page_box=None`）
    或换成 input=left 都能编译。
    """
    spec, pres = inlet_circuit(), inlet_presentation()
    stated = compile_module(
        spec, pres, budget=dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0))
    )
    unstated = compile_module(spec, pres)

    assert unstated.ok
    if stated.ok:
        pytest.skip("the anchoring snap no longer escapes the margin")
    (failure,) = [item for item in stated.failures
                  if item.category == dc.FAILURE_LAYOUT_UNSAT]
    assert "1170 x 825" in failure.detail
    assert "1170 x 825" in failure.detail and "margin" in failure.detail
