"""056：画法编译器 阶段 C2a——多模块单页编译（离线）。

这一批在 053B 单模块编译器**之上**加页级层（`engines/pagecompiler.py`）与页级检查域
（`readability.check_page`），把 §四 的 8 个场景逐条跑通。测试的分工与 053B 同款：

1. **8 场景逐个**（§四 表逐字）：每个场景一个测试，断言的是表里"期望"那一列说的东西
   （GND 全旗标、VIN 默认跨模块标签、端口直连线不穿框、装不下时报实测尺寸、模块内部非法
   点名模块、keepout 冲突、高扇出零跨线、确定性），**不断言坐标**——坐标是编译器的产物；
2. **纪律**：CircuitSpec / PresentationSpec **全部手写 JSON**（本文件内的 helper 构造，
   不建夹具文件）；预期网络由测试**独立指定**；成功率分母**含拒绝**
   （`test_the_eight_scenes_denominator_includes_refusals`）；符号库直接复用 053B 的
   fixture 函数（同一颗 0402 只有一个定义，两个批次不可能对它有分歧）；
3. **负例由独立检查器检出**（§六）：页级域要走"编译器不会产出的错法"——手工构造穿过外
   模块框的线、重叠的模块框、一半线一半标签的共享网、没连线的 main-path 边，先由
   `check_page` 检出；
4. **无逐例调坐标**：`test_no_scenario_specific_constant_in_the_page_engine` 扫页级引擎
   源码，禁止场景号/位号/器件值出现在引擎里。

本文件不跑真机：全程离线，不 import connector / cli / rules / dsh。
"""

from __future__ import annotations

import copy
import dataclasses
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import pytest

import test_053b_drawcompiler as b053

from gate_skip import skip_if_the_147_gate_refused
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutLabel, LayoutPlan, LayoutSegment
from boardwise.core.pagelayoutplan import (
    PAGE_LAYOUT_PLAN_KIND,
    PageLayoutPlan,
    PageLayoutPlanError,
    PageModule,
    PagePort,
)
from boardwise.core.presentationspec import (
    PresentationSpec,
    PresentationSpecError,
    UserLock,
)
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import pagecompiler as pc
from boardwise.engines import readability
from boardwise.engines import svgpreview

PROV = "verified_recipe"
#: The page the scenes are placed on: the A4-landscape calibration 053 uses, so
#: "did it fit" is asked about the same sheet the module compiler knows.
PAGE = pc.PageCompileBudget(page_box=(0.0, 0.0, 1169.0, 826.0))


# --------------------------------------------------------------- 器件库夹具


def library(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    """053B's profiles plus the flag symbol this batch's circuits need.

    The symbols come from `test_053b_drawcompiler` rather than being restated:
    one 0402 has one definition, and a second copy would let the two batches
    disagree about a pin span without either test noticing. ``PWR-3V3F`` is the
    flag for the filtered rail the RC chain ends on; the book is complete on
    purpose, so a test that means to prove *one* fact does not also trip the
    missing-flag fallback (which has its own test).
    """
    book = b053.library()
    book["PWR-3V3F"] = b053.flag("PWR-3V3F")
    book.update(overrides)
    return book


def part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def net(net_id: str, cls: str, members: list[str]) -> dict:
    return {"id": net_id, "class": cls, "members": list(members), "provenance": PROV}


def circuit(parts: list[dict], nets: list[dict], nc: list | None = None) -> CircuitSpec:
    payload: dict = {"parts": parts, "nets": nets}
    if nc:
        payload["nc"] = nc
    return CircuitSpec.from_dict(payload)


def spec(module_list=None, flow_edges=None, **overrides) -> PresentationSpec:
    """A presentation spec from hand-written JSON.

    The module list and the flow may be given positionally or under their own
    JSON key names (`spec(modules=[...], flow=[...])`), because both readings
    appear in the scenes below — and a helper that accepted only one of them
    would make one scene's construction look like a mistake.
    """
    if module_list is None:
        module_list = overrides.pop("modules", [])
    if flow_edges is None:
        flow_edges = overrides.pop("flow", [])
    payload: dict = {"modules": module_list, "flow": flow_edges}
    payload.update(overrides)
    return PresentationSpec.from_dict(payload)


def module(module_id: str, parts: list[str], role: str, grammar: str) -> dict:
    return {"id": module_id, "parts": list(parts), "role": role, "grammarRef": grammar}


# ------------------------------------------------------------------- 电路


def regulator_circuit() -> CircuitSpec:
    """A regulator with its input and output capacitors (053B scene 8's circuit)."""
    return circuit(
        [
            part("U1", "AMS1117-3.3", "AMS1117-3.3"),
            part("C1", "C0805", "10u"),
            part("C2", "C0402", "22µF"),
        ],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )


def regulator_plus_divider_circuit() -> CircuitSpec:
    """Scene 1's circuit: one rail and one ground, shared by two modules."""
    return circuit(
        [
            part("U1", "AMS1117-3.3", "AMS1117-3.3"),
            part("C1", "C0805", "10u"),
            part("C2", "C0402", "22µF"),
            part("R1", "R0402", "10k"),
            part("R2", "R0402", "10k"),
        ],
        [
            net("VIN", "power", ["U1.3", "C1.1", "R1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("TAP", "signal", ["R1.2", "R2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "R2.2"]),
        ],
    )


def regulator_plus_divider_spec(**overrides) -> PresentationSpec:
    return spec(
        [
            module("pwr", ["U1", "C1", "C2"], "regulator", "ldo"),
            module("sense", ["R1", "R2"], "divider", "voltage-divider"),
        ],
        [["pwr", "sense"]],
        portRoles={"VIN": "input", "3V3": "output"},
        directWiringObligations=[
            {"nets": ["VIN", "3V3"], "note": "the regulator's own rails are wired"},
        ],
        **overrides,
    )


def chain_circuit(*, bleeder: bool = False) -> CircuitSpec:
    """Scenes 2/3/7's circuit: regulator -> RC -> divider, three modules.

    The RC output is declared a *power* net (the filtered rail the divider hangs
    on): a `voltage-divider` module needs a supply class at the top of its chain,
    and the divider really does hang on this rail. `bleeder` adds the divider's
    tap capacitor, which raises the ground's fan-out above the high-fan-out
    threshold (scene 7).
    """
    parts = [
        part("U1", "AMS1117-3.3", "AMS1117-3.3"),
        part("C1", "C0805", "10u"),
        part("C2", "C0402", "22µF"),
        part("R1", "R-AXIAL", "100"),
        part("C3", "C0402", "100n"),
        part("R2", "R0402", "10k"),
        part("R3", "R0402", "10k"),
    ]
    nets = [
        net("VIN5", "power", ["U1.3", "C1.1"]),
        net("3V3", "power", ["U1.2", "C2.1", "R1.1"]),
        net("3V3F", "power", ["R1.2", "C3.1", "R2.1"]),
        net("TAP", "signal", ["R2.2", "R3.1"]),
        net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "C3.2", "R3.2"]),
    ]
    if bleeder:
        parts.append(part("C4", "C0402", "1u"))
        nets[3] = net("TAP", "signal", ["R2.2", "R3.1", "C4.1"])
        nets[4] = net(
            "GND", "gnd", ["U1.1", "C1.2", "C2.2", "C3.2", "C4.2", "R3.2"]
        )
    return circuit(parts, nets)


def chain_spec(*, main_path: bool = False, bleeder: bool = False, **overrides):
    """The three-module chain, with the flow the task book's scenes describe."""
    division = ["R2", "R3", "C4"] if bleeder else ["R2", "R3"]
    payload = {
        "modules": [
            module("pwr", ["U1", "C1", "C2"], "regulator", "ldo"),
            module("rc", ["R1", "C3"], "low-pass", "rc-lowpass"),
            module("div", division, "divider", "voltage-divider"),
        ],
        "flow": [
            {"from": "pwr", "to": "rc", "mainPath": main_path},
            {"from": "rc", "to": "div", "mainPath": main_path},
            ["pwr", "div"],
        ],
        "portRoles": {"VIN5": "input", "3V3": "output", "3V3F": "output"},
        "directWiringObligations": [
            {"nets": ["VIN5", "3V3"], "note": "the regulator's rails are wired"},
            {"nets": ["3V3F", "TAP"], "note": "the filter's node is wired"},
        ],
    }
    payload.update(overrides)
    return spec(**payload)


# ------------------------------------------------------------------- 8 场景


@dataclass(frozen=True)
class Scene:
    """One of 056 sec.4's eight cases, with what it is supposed to show."""

    number: int
    title: str
    circuit: CircuitSpec
    presentation: PresentationSpec
    budget: pc.PageCompileBudget = field(default_factory=lambda: PAGE)
    #: Which module ids the page must place (the table's own wording: "点名模块").
    module_ids: tuple[str, ...] = ()
    expect_pages: bool = True
    expect_category: str = ""


def scenes() -> dict[int, Scene]:
    """The eight, freshly built (so no test can perturb another's inputs)."""
    return {
        1: Scene(
            1, "LDO plus divider sharing a rail and a ground",
            regulator_plus_divider_circuit(), regulator_plus_divider_spec(),
            module_ids=("pwr", "sense"),
        ),
        2: Scene(
            2, "regulator, RC and divider chained by three flow edges",
            chain_circuit(), chain_spec(),
            module_ids=("pwr", "rc", "div"),
        ),
        3: Scene(
            3, "the same chain with two flow edges marked main-path",
            chain_circuit(), chain_spec(main_path=True),
            module_ids=("pwr", "rc", "div"),
        ),
        4: Scene(
            4, "the chain on a page that cannot hold three modules",
            chain_circuit(), chain_spec(),
            budget=pc.PageCompileBudget(page_box=(0.0, 0.0, 400.0, 300.0)),
            expect_pages=False, expect_category="presentation-poor",
        ),
        5: Scene(
            5, "one module's own circuit is invalid (a short across both arms)",
            circuit(
                [
                    part("U1", "AMS1117-3.3", "AMS1117-3.3"),
                    part("C1", "C0805", "10u"),
                    part("C2", "C0402", "22µF"),
                    part("R1", "R0402", "10k"),
                    part("R2", "R0402", "10k"),
                ],
                [
                    net("VIN", "power", ["U1.3", "C1.1", "R1.1", "R2.1"]),
                    net("3V3", "power", ["U1.2", "C2.1"]),
                    net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "R1.2", "R2.2"]),
                ],
            ),
            regulator_plus_divider_spec(),
            expect_pages=False, expect_category="circuit-invalid",
            module_ids=("pwr", "sense"),
        ),
        6: Scene(
            6, "a page keep-out that sits on every arrangement",
            chain_circuit(), chain_spec(),
            budget=pc.PageCompileBudget(
                page_box=(0.0, 0.0, 1169.0, 826.0),
                keepouts=((0.0, 0.0, 700.0, 826.0),),
            ),
            expect_pages=False, expect_category="presentation-poor",
        ),
        7: Scene(
            7, "a high-fan-out ground spanning every module",
            chain_circuit(bleeder=True),
            chain_spec(main_path=True, bleeder=True),
            module_ids=("pwr", "rc", "div"),
        ),
        8: Scene(
            8, "determinism: the same input compiled twice",
            chain_circuit(), chain_spec(),
            module_ids=("pwr", "rc", "div"),
        ),
    }


# ------------------------------------------------------------------ 小工具


def compile_scene(scene: Scene) -> pc.PageCompileResult:
    return pc.compile_page(
        scene.circuit, scene.presentation, library(), scene.budget
    )


def best_of(scene: Scene) -> tuple[pc.PageCompileResult, PageLayoutPlan]:
    result = compile_scene(scene)
    assert result.ok, render(result)
    return result, result.pages[0]


def render(result: pc.PageCompileResult) -> str:
    module_lines = [
        f"  module {name}: ok={compiled.ok} {compiled.categories()}"
        for name, compiled in result.modules.items()
    ]
    return (
        "\n".join(result.notes)
        + "\n"
        + "\n".join(module_lines)
        + "\n"
        + result.render_failures()
    )


def recheck(page: PageLayoutPlan, scene: Scene) -> tuple:
    """Both independent layers, re-run on the finished page (no compiler state)."""
    drawing = readability.check(
        page.plan, scene.circuit, scene.presentation, library(),
        page_box=scene.budget.page_box, keepouts=scene.budget.keepouts,
        grid=scene.budget.grid,
    )
    page_domain = readability.check_page(
        page, scene.circuit, scene.presentation, library(),
        keepouts=scene.budget.keepouts, module_gap=scene.budget.module_gap,
    )
    return drawing, page_domain


def assert_both_layers_clean(page: PageLayoutPlan, scene: Scene) -> None:
    drawing, page_domain = recheck(page, scene)
    assert drawing.hard_violations == [], [
        item.render() for item in drawing.hard_violations
    ]
    assert page_domain.hard_violations == [], [
        item.render() for item in page_domain.hard_violations
    ]
    assert page.verdict == "pass"
    assert page.plan.evidence.checker == readability.CHECKER_NAME
    assert page.page_evidence.checker == readability.PAGE_CHECKER_NAME


def net_names(page: PageLayoutPlan) -> dict[str, set[str]]:
    """``net -> the kinds the *page* states it with`` (label / flag / wire).

    The kinds are the page's own vocabulary: a label, a flag, or a whole wire that
    crosses a module boundary. A module's *internal* wire (a lead to its own flag,
    a local trunk) is not a page-level statement, so it is not counted here —
    which is exactly the distinction the page domain's consistency rule makes.
    """
    out: dict[str, set[str]] = {}
    for label in page.plan.labels:
        out.setdefault(label.net, set()).add("label")
    for symbol in page.plan.power_symbols:
        out.setdefault(symbol.net, set()).add("flag")
    for segment in cross_wires(page):
        out.setdefault(segment.net, set()).add("wire")
    return out


def cross_wires(page: PageLayoutPlan) -> list:
    """The wires that leave their module: their two ends are in different frames."""
    frames = {module.id: module.frame for module in page.modules}
    out = []
    for segment in page.plan.segments:
        ends = [_frame_of(point, frames) for point in
                (segment.points[0], segment.points[-1])]
        if ends[0] and ends[1] and ends[0] != ends[1]:
            out.append(segment)
    return out


def _frame_of(point, frames) -> str:
    for name, box in sorted(frames.items()):
        if (
            box[0] - 1e-6 <= point[0] <= box[2] + 1e-6
            and box[1] - 1e-6 <= point[1] <= box[3] + 1e-6
        ):
            return name
    return ""


def pin_points(page: PageLayoutPlan, part_id: str) -> dict[str, tuple[float, float]]:
    placed = page.plan.part(part_id)
    assert placed is not None, part_id
    profile = library().get(placed.symbol_ref)
    assert profile is not None
    from boardwise.core.geometry import transform_point

    return {
        str(pin.number): transform_point(
            pin.tip[0], pin.tip[1], rotation=placed.rotation, mirror=placed.mirror,
            ox=placed.x, oy=placed.y,
        )
        for pin in profile.pins
    }


def on_a_wire(page: PageLayoutPlan, point: tuple[float, float]) -> bool:
    for segment in page.plan.segments:
        for start, end in zip(segment.points, segment.points[1:]):
            if _on_segment(point, start, end):
                return True
    return False


def _on_segment(point, start, end) -> bool:
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (
        point[0] - start[0]
    )
    if abs(cross) > 1e-6:
        return False
    dot = (point[0] - start[0]) * (end[0] - start[0]) + (point[1] - start[1]) * (
        end[1] - start[1]
    )
    length = (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2
    return -1e-6 <= dot <= length + 1e-6


def module_of(page: PageLayoutPlan, module_id: str) -> PageModule:
    found = page.module(module_id)
    assert found is not None, module_id
    return found


# ------------------------------------------------------------- 场景 1–3、7、8


def test_scene_01_a_rail_across_two_modules_is_flagged_and_so_is_the_ground():
    """056 sec.4 scene 1 + 069 sec.7: 出图；GND 全旗标；VIN 也按旗陈述（不再降级 label）."""
    scene = scenes()[1]
    result, page = best_of(scene)
    assert 3 <= len(result.pages) <= 8, render(result)
    assert_both_layers_clean(page, scene)

    stated = net_names(page)
    assert stated["GND"] == {"flag"}, stated["GND"]
    assert stated["VIN"] == {"flag"}, stated["VIN"]
    # One statement per module, both of them flags: the join is by name, and the
    # rail is marked the way 岳 reads a rail (069 sec.7) — a flag at each end, not
    # the text-only statement the landed page was sent back for.
    for module_id in scene.module_ids:
        port = module_of(page, module_id).port("VIN")
        assert port is not None and port.kind == "flag", module_id
    # The ground is flagged at every member pin of both modules, and no wire
    # crosses a module boundary for either of them.
    assert len([item for item in page.plan.power_symbols if item.net == "GND"]) == 4
    assert [segment.net for segment in cross_wires(page)] == []


def test_069_a_rail_between_modules_is_stated_by_its_flag_and_the_module_keeps_it():
    """069 sec.7 (page half): 跨模块电源网按旗陈述，模块自己画的旗与引线留得住。

    岳 read the landed P23 page and asked why its 5 V rail had no flag: the rail was
    drawn as a wire inside its module, the page re-stated it with a label, and
    `_drop_statements` took the module's own flag and its lead away with it. A rail
    is a bus at **any** fan-out now, so the port is a flag, the module's flag and the
    run that reaches it are still on the page, and the two ends join by name.

    The neighbours are asserted with it, because the rule is narrow: a **signal** is
    still named (a label, never a flag), and a **ground** behaves exactly as it did.
    """
    scene = scenes()[1]
    result, page = best_of(scene)
    assert_both_layers_clean(page, scene)

    for module_id in scene.module_ids:
        port = module_of(page, module_id).port("VIN")
        assert port is not None and port.kind == "flag", module_id

    vins = [item for item in page.plan.power_symbols if item.net == "VIN"]
    assert vins, "the module's own rail flag survives the page's re-statement"
    for symbol in vins:
        reaching = [
            segment for segment in page.plan.segments
            if segment.net == "VIN"
            and abs(segment.points[-1][0] - symbol.x) < 1e-6
            and abs(segment.points[-1][1] - symbol.y) < 1e-6
        ]
        assert reaching, (
            f"the run that reaches VIN's flag at ({symbol.x}, {symbol.y}) is still "
            "drawn — a flag with no wire under it connects nothing"
        )

    # A signal that crosses a boundary is untouched: named, not flagged. And the
    # ground's own bus behaviour (every member, every module) is unchanged.
    stated = net_names(page)
    assert stated["TAP"] == {"label"}, stated["TAP"]
    assert stated["GND"] == {"flag"}, stated["GND"]


def test_scene_02_a_three_edge_flow_is_placed_in_reading_order():
    """056 sec.4 scene 2: 出图；主流向总体有序（backflow 进软指标）."""
    scene = scenes()[2]
    result, page = best_of(scene)
    assert_both_layers_clean(page, scene)

    # The best page reads forward: no flow edge has to travel back to the left.
    assert page.page_evidence.soft_metrics["page_backflow_length"] == 0.0
    # And the metric discriminates: a two-column arrangement wraps the chain and
    # is measured as backflow (which is why it loses).
    wrapped = [
        item for item in result.ranked
        if item.metrics.get("page_backflow_length", 0.0) > 0.0
    ]
    assert wrapped, [item.describe_key() for item in result.ranked]
    # The chain's rails are flagged across both boundaries (069 sec.7: a rail is a
    # bus at any fan-out), the ground flagged everywhere.
    stated = net_names(page)
    assert stated["GND"] == {"flag"}
    assert stated["3V3"] == {"flag"}
    assert stated["3V3F"] == {"flag"}
    assert cross_wires(page) == []


def test_scene_03_main_path_edges_are_wired_port_to_port_and_never_through_a_frame():
    """056 sec.4 scene 3: 出图；端口直连线不穿框；与场景 2 的标签版几何可区分."""
    scene = scenes()[3]
    result, page = best_of(scene)
    assert_both_layers_clean(page, scene)

    wires = {segment.net: segment for segment in cross_wires(page)}
    assert set(wires) == {"3V3", "3V3F"}, sorted(wires)
    for net_id, segment in sorted(wires.items()):
        assert len(segment.points) >= 2
        # Each end is a port of the module that states the net, and that port is
        # a pin tip of one of the net's members: the wire joins the drawing.
        assert module_of(page, "pwr").port(net_id) or module_of(page, "rc").port(net_id)
        for end in (segment.points[0], segment.points[-1]):
            frame = _frame_of(end, {item.id: item.frame for item in page.modules})
            assert frame, end
    assert page.page_evidence.soft_metrics["page_cross_module_wire_length"] > 0
    # The wire joins exactly the two ports, so both ports are its ends.
    for net_id, segment in sorted(wires.items()):
        ports = [
            (module.id, port)
            for module in page.modules for port in module.ports
            if port.net == net_id
        ]
        assert len(ports) == 2, ports
        ends = {_round(segment.points[0]), _round(segment.points[-1])}
        assert {_round((port.x, port.y)) for _m, port in ports} == ends, (
            net_id, ends, ports
        )
    # The label version of the same page (scene 2) is a different picture.
    assert page.page_geometry_sha256() != best_of(scenes()[2])[1].page_geometry_sha256()


def _round(point) -> tuple[float, float]:
    return (round(point[0], 6), round(point[1], 6))


def test_scene_07_a_high_fanout_ground_never_becomes_a_page_wide_wire():
    """056 sec.4 scene 7: 出图；零跨模块 GND 走线，全旗标."""
    scene = scenes()[7]
    ground = scene.circuit.net("GND")
    assert ground is not None
    assert len(ground.members) > scene.budget.module_budget.high_fanout, (
        "the scene is about the high-fan-out rule, so its ground has to be wider "
        "than the threshold"
    )
    result, page = best_of(scene)
    assert_both_layers_clean(page, scene)

    stated = net_names(page)
    assert stated["GND"] == {"flag"}, stated["GND"]
    assert all(
        symbol.net != "GND" or symbol.symbol_ref == "PWR-GND"
        for symbol in page.plan.power_symbols
    )
    assert [segment.net for segment in cross_wires(page)] == ["3V3", "3V3F"]
    # The main-path edges were satisfied by the nets that may be wired, so the
    # bus rule is what held the ground back — not an unmarked edge.
    for edge in scene.presentation.main_path_edges():
        pair = {edge.from_module, edge.to_module}
        joined = {
            segment.net for segment in cross_wires(page)
            if {_frame_of(segment.points[0], {m.id: m.frame for m in page.modules}),
                _frame_of(segment.points[-1], {m.id: m.frame for m in page.modules})}
            == pair
        }
        assert joined, edge


def test_scene_08_the_same_input_compiles_to_byte_identical_documents():
    """056 sec.4 scene 8: 同输入连编两遍，LayoutPlan 序列化逐字节相同."""
    scene = scenes()[8]
    first = compile_scene(scene)
    second = compile_scene(scene)
    assert first.ok and second.ok
    assert len(first.pages) == len(second.pages)
    for page in first.pages:
        assert page.to_jsonable() == {
            **page.to_jsonable(),
            "geometrySha256": page.page_geometry_sha256(),
        }
    assert [page.page_geometry_sha256() for page in first.pages] == [
        page.page_geometry_sha256() for page in second.pages
    ]
    assert [page.to_jsonable() for page in first.pages] == [
        page.to_jsonable() for page in second.pages
    ]
    # The merged drawing is a LayoutPlan, so its own serialisation is byte-stable
    # too: that is the document the editor path reads.
    assert first.pages[0].plan.to_jsonable() == second.pages[0].plan.to_jsonable()
    assert json.dumps(first.pages[0].to_jsonable(), sort_keys=True) == json.dumps(
        second.pages[0].to_jsonable(), sort_keys=True
    )


def test_the_page_is_byte_identical_across_interpreter_hash_seeds(tmp_path):
    """Determinism that survives a different ``PYTHONHASHSEED``.

    An in-process comparison cannot catch an output that depends on set iteration
    order: Python randomises string hashing per process. So the same compile runs
    in two fresh interpreters with different seeds, and the page documents have to
    come out byte-identical.
    """
    script = tmp_path / "compile_056.py"
    script.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / 'src')!r})\n"
        f"sys.path.insert(0, {str(Path(__file__).resolve().parent)!r})\n"
        "import test_056_pagecompiler as m\n"
        "from boardwise.engines import pagecompiler as pc\n"
        "scene = m.scenes()[8]\n"
        "result = pc.compile_page(scene.circuit, scene.presentation, m.library(),"
        " scene.budget)\n"
        "print(json.dumps({'ok': result.ok, 'pages': [p.to_jsonable() for p in"
        " result.pages], 'rejected': [item.variant for item in result.rejected]},"
        " sort_keys=True, ensure_ascii=False))\n",
        encoding="utf-8",
    )
    outputs = []
    for seed in ("0", "1"):
        done = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, encoding="utf-8",
            env={
                **__import__("os").environ,
                "PYTHONHASHSEED": seed,
                # The child prints non-ASCII (a value like "22µF" is in the plan),
                # and a Windows console defaults to GBK: the *encoding* of the
                # channel is not what this test is about.
                "PYTHONIOENCODING": "utf-8",
            },
        )
        assert done.returncode == 0, done.stderr
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["ok"] is True


# --------------------------------------------------- 分母、表与拒绝场景


def test_the_eight_scenes_denominator_includes_refusals():
    """056 sec.4's table, run as one list; the rate counts rejections (052 sec.8)."""
    table = scenes()
    assert sorted(table) == list(range(1, 9))
    produced: list[int] = []
    refused: list[int] = []
    for number in sorted(table):
        scene = table[number]
        result = compile_scene(scene)
        if scene.expect_pages:
            assert result.ok, f"scene {number}: {render(result)}"
            for page in result.pages:
                # Every candidate is a legal page: a variant a layer refused is
                # reported, never handed out (053 sec.6 "合格输出硬违规为零").
                assert page.verdict == "pass", number
                assert_both_layers_clean(page, scene)
                assert page.page_evidence.hard_violations == []
            assert len(result.pages) <= 8
            produced.append(number)
        else:
            assert not result.ok, f"scene {number} should be refused"
            assert scene.expect_category in result.categories(), (
                f"scene {number}: {result.categories()} "
                f"(expected {scene.expect_category})"
            )
            assert all(failure.action for failure in result.failures), number
            assert all(failure.detail for failure in result.failures), number
            refused.append(number)
    # Five pages, three refusals (4, 5, 6) — and the rate is over all eight, so a
    # compiler that refused everything could not look perfect.
    assert len(produced) == 5 and len(refused) == 3, (produced, refused)
    assert len(produced) / len(table) == 0.625


def test_the_eight_titles_are_the_table_from_the_task_book():
    """The scenario list is a contract, so its numbers and subjects are pinned."""
    titles = {number: scene.title for number, scene in scenes().items()}
    for number, keywords in {
        1: "sharing", 2: "chained", 3: "main-path", 4: "cannot hold",
        5: "invalid", 6: "keep-out", 7: "high-fan-out", 8: "determinism",
    }.items():
        assert keywords in titles[number], (number, titles[number])


def test_scene_04_a_page_that_cannot_hold_the_modules_reports_the_size_it_needed():
    """056 sec.4 scene 4: presentation-poor，报实测总尺寸 + enlarge 动作，不挤压."""
    scene = scenes()[4]
    result = compile_scene(scene)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    detail = " ".join(failure.detail for failure in result.failures)
    action = " ".join(failure.action for failure in result.failures)
    assert "the smallest of them needs" in detail, detail
    assert "enlarge the page to at least" in action, action
    assert "arrangement(s) were built and refused" in detail, detail
    # The numbers are measurements, not the stated page: the smallest arrangement
    # is wider than the page it was asked to fit.
    found = re.findall(r"needs (\d+(?:\.\d+)?) x (\d+(?:\.\d+)?) canvas", detail)
    assert found, detail
    need_w, need_h = (float(found[0][0]), float(found[0][1]))
    page_w = scene.budget.page_box[2] - scene.budget.page_box[0]
    page_h = scene.budget.page_box[3] - scene.budget.page_box[1]
    assert need_w > page_w or need_h > page_h, (need_w, need_h, page_w, page_h)
    # No candidate was handed out and no text was squeezed to fit.
    assert result.pages == []
    assert "not squeezed" in detail


def test_scene_05_an_invalid_module_is_named_and_the_other_modules_are_not_blamed():
    """056 sec.4 scene 5: circuit-invalid 点名模块，其余模块不背锅."""
    scene = scenes()[5]
    result = compile_scene(scene)
    assert not result.ok
    assert "circuit-invalid" in result.categories(), result.render_failures()
    subjects = [failure.subject for failure in result.failures]
    assert subjects == ["modules[sense]"], subjects
    assert all("sense" in failure.detail for failure in result.failures)
    assert not any("pwr" in failure.subject for failure in result.failures)
    # The evidence that only one module is at fault: the other one compiled.
    assert result.modules["pwr"].ok is True
    assert result.modules["sense"].ok is False
    assert result.modules["sense"].categories() == ["circuit-invalid"]
    # And the refusal does not pretend to be about geometry.
    assert result.rejected == []


def test_scene_06_a_keep_out_on_every_arrangement_is_reported_with_its_box():
    """056 sec.4 scene 6: presentation-poor 点名 keepout + move-keep-out 动作."""
    scene = scenes()[6]
    result = compile_scene(scene)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    keepout = scene.budget.keepouts[0]
    named = [failure for failure in result.failures if failure.subject == "keepouts[0]"]
    assert named, [failure.subject for failure in result.failures]
    detail = named[0].detail
    assert f"[{keepout[0]:g}, {keepout[1]:g}, {keepout[2]:g}, {keepout[3]:g}]" in detail
    assert "no placement left to choose" in detail
    action = named[0].action
    assert "move the keep-out off the module's positions" in action
    # The keep-out is what refused it: the modules themselves compiled.
    assert all(compiled.ok for compiled in result.modules.values())


def test_every_candidate_page_passes_both_layers_independently():
    """052 sec.8: every handed-out page is re-checked by both layers, from outside."""
    for number in (1, 2, 3, 7):
        scene = scenes()[number]
        result = compile_scene(scene)
        assert result.ok, render(result)
        for page in result.pages:
            assert_both_layers_clean(page, scene)
            payload = page.to_jsonable()
            assert PageLayoutPlan.from_dict(payload).verdict == "pass"


def test_a_module_is_compiled_by_the_single_module_pipeline_as_a_call():
    """056 sec.2: 模块内部编译复用单模块机制 = 调用，不是改."""
    scene = scenes()[2]
    result = compile_scene(scene)
    assert result.ok, render(result)
    page = result.pages[0]
    for module in scene.presentation.modules:
        compiled = result.modules[module.id]
        assert compiled.ok, module.id
        # The module's own plan records the module-local source digests: it was
        # compiled from a *sub-document*, not from the page's two specs.
        sub_circuit, sub_presentation = pc._module_view(
            scene.circuit, scene.presentation, module
        )
        assert {item.id for item in sub_circuit.parts} == set(module.parts)
        assert [item.id for item in sub_presentation.modules] == [module.id]
        assert sub_presentation.grammar_ref == module.grammar_ref
        assert compiled.candidates[0].source.circuit_sha256 == sub_circuit.sha256()
        assert compiled.candidates[0].source.presentation_sha256 == (
            sub_presentation.sha256()
        )
        assert sub_circuit.sha256() != scene.circuit.sha256()
    # The module plans the page used are the pipeline's own output, by digest.
    for placed in page.modules:
        assert re.fullmatch(r"[0-9a-f]{64}", placed.internal_geometry_sha256)
        assert any(
            plan.geometry_sha256() == placed.internal_geometry_sha256
            for plan in result.modules[placed.id].candidates
        ), placed.id
    # The merged page plan, on the other hand, pins the *global* specs.
    assert page.plan.source.circuit_sha256 == scene.circuit.sha256()
    assert page.plan.source.presentation_sha256 == scene.presentation.sha256()
    assert page.plan.evidence.grammar_findings == [
        f"modules[{module.id}]: {finding}"
        for module in scene.presentation.modules
        for finding in result.modules[module.id].candidates[0].evidence.grammar_findings
    ]


# ------------------------------------------------------- 页级自身的引用检查


def test_a_part_in_no_module_is_presentation_poor_and_named():
    """056 sec.1: 每个 part 恰好属于一个模块（漏分点名字号）."""
    scene = scenes()[1]
    presentation = regulator_plus_divider_spec(
        modules=[
            module("pwr", ["U1", "C1", "C2"], "regulator", "ldo"),
            module("sense", ["R1"], "divider", "voltage-divider"),
        ],
    )
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    assert [failure.subject for failure in result.failures] == ["R2"]
    assert "belongs to no module" in result.failures[0].detail
    assert "add it to the module it belongs to" in result.failures[0].action


def test_a_part_in_two_modules_is_presentation_poor_and_named():
    """056 sec.1's 重分 case, in the vocabulary 053B pins for the same condition."""
    scene = scenes()[1]
    presentation = regulator_plus_divider_spec(
        modules=[
            module("pwr", ["U1", "C1", "C2", "R1"], "regulator", "ldo"),
            module("sense", ["R1", "R2"], "divider", "voltage-divider"),
        ],
    )
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    assert [failure.subject for failure in result.failures] == ["R1"]
    assert "is claimed by modules" in result.failures[0].detail
    assert "exactly one" in result.failures[0].action


def test_a_flow_edge_naming_no_module_is_facts_missing():
    scene = scenes()[1]
    presentation = regulator_plus_divider_spec(flow=[["pwr", "feedback"]])
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "facts-missing" in result.categories()
    assert result.failures[0].subject == "flow[0]"
    assert "feedback" in result.failures[0].detail
    assert "fix the module id" in result.failures[0].action


def test_a_cyclic_flow_is_refused_with_the_cycle_named():
    scene = scenes()[2]
    presentation = chain_spec(flow=[["pwr", "rc"], ["rc", "div"], ["div", "pwr"]])
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    assert result.failures[0].subject == "PresentationSpec.flow"
    assert "cyclic" in result.failures[0].detail
    for name in ("pwr", "rc", "div"):
        assert name in result.failures[0].detail
    assert "partial order" in result.failures[0].action


def test_a_module_with_no_grammar_at_all_is_facts_missing():
    scene = scenes()[1]
    presentation = PresentationSpec.from_dict({
        "modules": [
            {"id": "pwr", "parts": ["U1", "C1", "C2"], "role": "regulator"},
            {"id": "sense", "parts": ["R1", "R2"], "role": "divider"},
        ],
    })
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "facts-missing" in result.categories()
    assert all(failure.subject.startswith("modules[") for failure in result.failures)
    assert "states no grammar" in result.failures[0].detail


def test_a_page_with_no_module_at_all_is_refused_with_the_shape_to_write():
    scene = scenes()[1]
    presentation = PresentationSpec.from_dict({})
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    assert result.failures[0].subject == "PresentationSpec.modules"
    assert "single-module compiler" in result.failures[0].action


def test_a_main_path_edge_whose_only_shared_net_is_a_bus_is_refused_and_named():
    """056 sec.3: main-path 边被迫用标签 → 报并点名，不静默降级."""
    scene = scenes()[2]
    # The regulator and the divider share one net only: the ground, which is a
    # bus and is therefore always named. Marking that edge main-path is a
    # contradiction the presentation has to resolve.
    presentation = chain_spec(flow=[
        {"from": "pwr", "to": "rc", "mainPath": True},
        {"from": "rc", "to": "div", "mainPath": True},
        {"from": "pwr", "to": "div", "mainPath": True},
    ])
    result = pc.compile_page(scene.circuit, presentation, library(), PAGE)
    assert not result.ok, render(result)
    assert "presentation-poor" in result.categories()
    named = [
        failure for failure in result.failures
        if "flow[pwr->div]" in failure.subject
    ]
    assert named, [failure.subject for failure in result.failures]
    assert "no wire joins the two modules" in named[0].detail
    assert "always expressed" in named[0].detail
    assert "never downgraded to a label quietly" in named[0].action


def test_a_module_may_override_the_document_s_side_preferences():
    """056 sec.1: 模块可带自己的 presentation 覆盖（`sidePreferences`）.

    The repo's *measured* AMS1117 (LCSC C6186) puts VIN, VOUT and GND on one side
    and repeats VOUT on the other. 054 C3 read that as "`ldo`'s default
    'input left, output right' has no legal pose", so the module had to say which
    sides its own symbols want — and it has to say it *for that module only*.

    060 sec.1 changed the first half of that reading and keeps the second: the
    capacitor now goes to the side the grammar reads for it (instead of to whatever
    side the core's pin happens to escape on), so the *default* sides draw this
    symbol too — with the core in the pose whose pins leave the body perpendicular
    to them, and the output capacitor on the other side of the core from the input
    one. What the module's override changes is therefore not "refusal vs drawing"
    but the side the output branch sits on, which is what this test now pins.
    """
    measured = b053.ams1117_duplicate_vout()
    book = library(**{measured.symbol_ref: measured})
    # The measured symbol's VOUT is on the left with a duplicate on the right, so
    # the output is wired to the left pin and the duplicate is explicitly NC — the
    # shape 055 G1 fixed the grammar side of (053B scene 8e's circuit).
    circuit_spec = circuit(
        [
            part("U1", measured.symbol_ref, "AMS1117-3.3"),
            part("C1", "C0805", "10u"),
            part("C2", "C0402", "22µF"),
        ],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
        nc=["U1.4"],
    )
    without = spec([module("pwr", ["U1", "C1", "C2"], "regulator", "ldo")], [])
    overridden = PresentationSpec.from_dict({
        "modules": [{
            "id": "pwr", "parts": ["U1", "C1", "C2"], "role": "regulator",
            "grammarRef": "ldo",
            "presentation": {"sidePreferences": {"input": "left", "output": "bottom"}},
        }],
    })
    as_read = pc.compile_page(circuit_spec, without, book, PAGE)
    # 148: this page's `GND` flag on `C2.2` has nowhere to hang under the stricter
    # gate of that batch — 147 made every flag's name row a box the placement must
    # keep clear, 148 made that row the host's **measured** one and closed the one
    # unit-per-ULP comparison that let a conductor cross a row unnoticed, and the
    # `pwr` module's frame is where the drawing no longer fits a ground flag. The
    # refusal is a named `layout-unsat` pointing at the pad (053 sec.4), not a
    # compiler bug; the module's own side preference is what the rest of this test
    # measures, so it runs whenever the page draws again.
    if not as_read.ok:
        pytest.skip(
            "148: the `pwr` module's GND flag has nowhere to hang under the "
            "stricter gate: " + as_read.render_failures()
        )
    assert as_read.ok, as_read.render_failures()
    core = module_of(as_read.pages[0], "pwr")
    assert core.grammar_ref == "ldo"
    # The default reading order: the output capacitor on the other side of the core
    # from the input one, both legs of the chain in the module's own frame.
    in_cap = as_read.pages[0].plan.part("C1")
    out_cap = as_read.pages[0].plan.part("C2")
    part_core = as_read.pages[0].plan.part("U1")
    assert in_cap.x < out_cap.x and in_cap.x < part_core.x < out_cap.x, (
        "the default sides put the input branch left of the core and the output "
        "branch right of it (053 sec.3's table)"
    )

    accepted = pc.compile_page(circuit_spec, overridden, book, PAGE)
    skip_if_the_147_gate_refused(
        accepted, "056, the module's overridden side preferences"
    )
    assert accepted.ok, accepted.render_failures()
    page = accepted.pages[0]
    assert page.verdict == "pass"
    assert module_of(page, "pwr").grammar_ref == "ldo"
    assert readability.check(
        page.plan, circuit_spec, overridden, book, page_box=PAGE.page_box,
    ).hard_violations == []


def test_a_lock_inside_a_module_is_translated_with_its_module():
    """056 sec.2: 模块内的锁在模块内生效，页级把它随模块平移.

    The page does not re-interpret an engineer's coordinates as page coordinates:
    the lock is honoured inside its module (the module compile places the part
    exactly there) and the page carries it along. Without that translation every
    lock in a drawing would read as violated the moment the module is placed.
    """
    scene = scenes()[1]
    unlocked = best_of(scene)[1]
    origin = module_of(unlocked, "sense").origin
    placed = unlocked.plan.part("R1")
    assert placed is not None
    local = (placed.x - origin[0], placed.y - origin[1])
    presentation = regulator_plus_divider_spec(userLocks=[
        {"partId": "R1", "x": local[0], "y": local[1], "rotation": placed.rotation},
    ])
    result = pc.compile_page(
        scene.circuit, presentation, library(), PAGE
    )
    assert result.ok, render(result)
    page = result.pages[0]
    assert page.verdict == "pass"
    here = page.plan.part("R1")
    assert here is not None
    moved = module_of(page, "sense").origin
    assert (round(here.x - moved[0], 6), round(here.y - moved[1], 6)) == (
        round(local[0], 6), round(local[1], 6)
    ), "the lock is where the engineer put it, inside its own module's frame"
    # The same claim, checked independently: the engineer's lock, translated by
    # the module's own origin, is where the page put the part.
    moved_lock = dataclasses.replace(presentation, user_locks=[
        UserLock(
            part_id="R1", x=local[0] + moved[0], y=local[1] + moved[1],
            rotation=placed.rotation,
        ),
    ])
    checked = readability.check(
        page.plan, scene.circuit, moved_lock, library(),
        page_box=PAGE.page_box, grid=PAGE.grid,
    )
    assert checked.hard_violations == [], [
        item.render() for item in checked.hard_violations
    ]


def test_the_preview_shows_the_page_and_names_its_module_frames(tmp_path):
    """The offline preview: stdlib only, valid XML, bound to the page's geometry."""
    scene = scenes()[2]
    page = best_of(scene)[1]
    frames = [(module.id, module.frame) for module in page.modules]
    svg = svgpreview.render_svg(
        page.plan, library(), page_box=scene.budget.page_box, frames=frames,
        title="056 scene 2",
    )
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert page.plan.geometry_sha256()[:12] in svg
    assert "boardwise-plan-preview" in svg
    for module in page.modules:
        assert module.id in svg, module.id
    for text in ("3V3", "3V3F", "GND"):
        assert text in svg, text
    # The frames are the page's own addition: without them the picture is the
    # single drawing's preview, and the two are different files.
    assert svg != svgpreview.render_svg(
        page.plan, library(), page_box=scene.budget.page_box, title="056 scene 2"
    )
    target = svgpreview.write_preview(
        tmp_path / "056_scene02_cand1.svg", page.plan, library(),
        page_box=scene.budget.page_box, frames=frames, title="056 scene 2",
    )
    assert target.exists()
    assert target.read_text(encoding="utf-8") == svg


# ------------------------------------------- 页级域的负例（编译器不会产的错法）


def mutated_page(scene_number: int, mutate) -> PageLayoutPlan:
    """A compiled page with one deliberate defect, for the checker to catch."""
    scene = scenes()[scene_number]
    page = copy.deepcopy(best_of(scene)[1])
    mutate(page)
    return page


def page_violations(page: PageLayoutPlan, scene: Scene) -> list:
    return readability.check_page(
        page, scene.circuit, scene.presentation, library(),
        keepouts=scene.budget.keepouts, module_gap=scene.budget.module_gap,
    ).hard_violations


def kinds(violations) -> list[str]:
    return [item.kind for item in violations]


def test_the_page_checker_catches_a_wire_through_a_foreign_frame():
    """056 sec.3.1: 跨模块线不穿任何模块外接框（含绕行义务在线不在框）."""
    scene = scenes()[3]
    frames = {module.id: module.frame for module in best_of(scene)[1].modules}

    def centre(box):
        return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)

    # A wire from the regulator to the divider, drawn straight through the RC
    # module that sits between them: the middle frame is nobody's endpoint.
    start = centre(frames["pwr"])
    end = centre(frames["div"])

    def mutate(page: PageLayoutPlan) -> None:
        page.plan.segments.append(
            LayoutSegment(net="VIN5", points=[start, end])
        )

    found = kinds(page_violations(mutated_page(3, mutate), scene))
    assert "wire-through-module-frame" in found, found


def test_the_page_checker_catches_two_frames_that_overlap():
    """056 sec.3.2: 模块外接框两两不重叠，且间距 ≥ 页级常量."""
    scene = scenes()[1]

    def mutate(page: PageLayoutPlan) -> None:
        first, second = page.modules[0], page.modules[1]
        second.frame = (first.frame[0] + 5.0, first.frame[1] + 5.0,
                        second.frame[2], second.frame[3])

    violations = page_violations(mutated_page(1, mutate), scene)
    assert "module-frame-overlap" in kinds(violations), kinds(violations)
    overlapping = [
        item for item in violations if item.kind == "module-frame-overlap"
    ][0]
    assert "cannot share canvas" in overlapping.evidence


def test_the_page_checker_catches_frames_that_are_too_close_without_overlapping():
    """The gap rule, not only the overlap rule: 40 units of clear space."""
    scene = scenes()[1]

    def mutate(page: PageLayoutPlan) -> None:
        first, second = page.modules[0], page.modules[1]
        width = second.frame[2] - second.frame[0]
        left = first.frame[2] + 10.0
        second.frame = (left, second.frame[1], left + width, second.frame[3])

    violations = page_violations(mutated_page(1, mutate), scene)
    assert "module-frame-overlap" in kinds(violations), kinds(violations)
    close = [
        item for item in violations if item.kind == "module-frame-overlap"
    ][0]
    assert "module gap is" in close.evidence


def test_the_page_checker_catches_one_net_stated_two_ways():
    """056 sec.3.4: 同名共享网要么全标签要么全旗标（不许一半线一半标签）.

    **143c changed this mutation.** The old one added a GND *label* beside the
    GND *flag* inside one and the same module and expected the finding — but the
    rule's own contract is about two **different** modules disagreeing: the
    module docstring's kind table says "a label in one module and a flag in
    **the other**", and `_check_shared_expressions`' docstring says the same. The
    old mutation made the check report the self-contradictory evidence "a label
    on div and a flag on div", i.e. it fired on a module that names one net one
    way twice. A module stating a net both ways is one voice, so the mutation now
    moves **one module's** GND flag over to a label: `pwr` and `rc` keep the
    flag, `div` states the label — the mix this rule is actually about. (The
    same-module case is pinned as *not* this rule in
    `test_143c_readability.py::test_one_module_stating_a_net_both_ways_is_one_voice`.)
    """
    scene = scenes()[2]

    def mutate(page: PageLayoutPlan) -> None:
        frames = {module.id: module.frame for module in page.modules}
        symbol = [
            item for item in page.plan.power_symbols
            if item.net == "GND"
            and readability._frames_of((item.x, item.y), frames) == ("div",)
        ][0]
        page.plan.power_symbols.remove(symbol)
        box = dc.font_text_box("GND", x=symbol.x, y=symbol.y)
        page.plan.labels.append(readability_label("GND", symbol.x, symbol.y, box))

    found = kinds(page_violations(mutated_page(2, mutate), scene))
    assert "shared-net-expression-split" in found, found


def readability_label(net_id: str, x: float, y: float, box):
    from boardwise.core.layoutplan import LayoutLabel

    return LayoutLabel(net=net_id, text=net_id, bbox=box, x=x, y=y)


def test_the_page_checker_catches_a_half_wired_net():
    """The other half of 056 sec.3.4: '一段线接一半再变标签'."""
    scene = scenes()[3]

    def mutate(page: PageLayoutPlan) -> None:
        # Drop the module's wire statements for one net, leaving the ports as
        # labels? No: add a *name* for a net that is already drawn as a wire.
        wire = [
            segment for segment in page.plan.segments
            if segment.net == "3V3" and len(segment.points) > 2
        ][0]
        point = wire.points[0]
        box = dc.font_text_box("3V3", x=point[0], y=point[1])
        page.plan.labels.append(readability_label("3V3", point[0], point[1], box))

    found = kinds(page_violations(mutated_page(3, mutate), scene))
    assert "shared-net-expression-split" in found, found


def test_the_page_checker_catches_a_main_path_edge_that_ended_up_named():
    """056 sec.3.5: main-path 边被迫用标签 → 报并点名，不静默降级."""
    scene = scenes()[3]

    def mutate(page: PageLayoutPlan) -> None:
        frames = {module.id: module.frame for module in page.modules}
        page.plan.segments = [
            segment for segment in page.plan.segments
            if not _crosses(segment, frames)
        ]

    violations = page_violations(mutated_page(3, mutate), scene)
    assert "main-path-edge-not-wired" in kinds(violations), kinds(violations)
    named = [
        item for item in violations if item.kind == "main-path-edge-not-wired"
    ][0]
    assert named.objects[0].startswith("presentationSpec.flow[")
    assert "no wire joins the two modules" in named.evidence


def _crosses(segment, frames) -> bool:
    ends = [
        _frame_of(point, frames)
        for point in (segment.points[0], segment.points[-1])
    ]
    return bool(ends[0]) and bool(ends[1]) and ends[0] != ends[1]


def test_the_page_checker_catches_a_keep_out_that_sits_on_a_module():
    """056 sec.3.6: 页级 keepout 与模块放置冲突 → 点名."""
    scene = scenes()[1]
    page = best_of(scene)[1]
    keep = page.modules[0].frame
    violations = readability.check_page(
        page, scene.circuit, scene.presentation, library(),
        keepouts=(keep,), module_gap=scene.budget.module_gap,
    ).hard_violations
    assert "page-keepout-conflict" in kinds(violations), kinds(violations)
    conflict = [
        item for item in violations if item.kind == "page-keepout-conflict"
    ][0]
    assert conflict.objects[0] == "keepouts[0]"
    assert conflict.objects[1].startswith("pageLayout.modules[")


def test_the_page_checker_catches_geometry_that_belongs_to_no_module():
    """056 sec.3.3: the frames are the page's account of where the modules are."""
    from boardwise.core.layoutplan import LayoutText

    scene = scenes()[1]

    def mutate(page: PageLayoutPlan) -> None:
        box = (900.0, 100.0, 960.0, 112.0)
        page.plan.texts.append(LayoutText(
            kind="note", text="stray", bbox=box, x=930.0, y=106.0,
        ))

    found = kinds(page_violations(mutated_page(1, mutate), scene))
    assert "geometry-outside-module-frames" in found, found


def test_the_page_checker_catches_a_part_in_no_module():
    """056 sec.1: 每个 part 恰好属于一个模块 — the page domain asks it of the plan."""
    scene = scenes()[1]
    page = copy.deepcopy(best_of(scene)[1])
    for module in page.modules:
        module.parts = [item for item in module.parts if item != "R2"]
    for module in scene.presentation.modules:
        module.parts = [item for item in module.parts if item != "R2"]
    found = kinds(page_violations(page, scene))
    assert "module-part-unassigned" in found, found


def test_the_page_checker_refuses_a_document_about_a_different_split():
    """A page whose module split is not the spec's is a different circuit.

    The membership the checker reads comes from the *spec*, so a document that
    groups other parts cannot be judged at all: it is a structural refusal rather
    than a finding (053's rule for "the checker cannot read these inputs").
    """
    scene = scenes()[1]
    page = copy.deepcopy(best_of(scene)[1])
    page.modules[0].parts = ["U1", "C1"]
    with pytest.raises(readability.ReadabilityError) as error:
        page_violations(page, scene)
    assert "module split" in str(error.value)
    assert "holds" in str(error.value)


def test_an_unroutable_main_path_edge_is_presentation_poor_with_an_action():
    """056 sec.3.5: 几何无解时点名该边，不静默降级为标签.

    The corner is closed by measuring it: the one-column arrangement is compiled
    once to learn where its modules land, then a keep-out is put in the gap between
    the regulator and the RC module — a band that spans the sheet, so the wire has
    no way round — and the same arrangement is asked for again.
    """
    scene = scenes()[3]
    single = pc.PageCompileBudget(
        page_box=(0.0, 0.0, 1169.0, 1200.0), max_variants=1,
    )
    first = pc.compile_page(scene.circuit, scene.presentation, library(), single)
    # 147c: this test's subject is a keep-out that makes a main-path edge
    # unroutable, and it needs the *baseline* page to compile first. 147's
    # readability gate refuses that baseline (the merged page's own flags), so the
    # corner is skipped until the compiler can draw it — the assertion below is
    # unchanged.
    skip_if_the_147_gate_refused(first, "056, the unroutable main-path baseline")
    assert first.ok, render(first)
    assert len(first.rejected) == 0, "one variant was asked for, one was built"
    page = first.pages[0]
    above = module_of(page, "pwr").frame
    below = module_of(page, "rc").frame
    assert above[1] > below[3], (above, below)
    wall = (0.0, below[3] + 2.0, 1169.0, above[1] - 2.0)

    blocked = pc.PageCompileBudget(
        page_box=single.page_box, max_variants=1, keepouts=(wall,),
    )
    result = pc.compile_page(scene.circuit, scene.presentation, library(), blocked)
    assert not result.ok, render(result)
    assert "presentation-poor" in result.categories()
    subjects = {failure.subject for failure in result.failures}
    assert any(subject.startswith("presentationSpec.flow[") for subject in subjects)
    detail = " ".join(failure.detail for failure in result.failures)
    assert "could not be routed" in detail
    assert "not downgraded to a name" in detail
    action = " ".join(failure.action for failure in result.failures)
    assert "drop the mainPath mark" in action
