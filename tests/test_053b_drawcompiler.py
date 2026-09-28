"""053 阶段 B：画法编译器（`engines/drawcompiler.py`）+ SVG 离线预览。

这一批实现 053 §四 的离线编译管线，并把 §五 的 12 个场景逐条跑通。测试的分工：

1. **12 场景逐个**（§五 表逐字）：每个场景一个测试，断言的是 053 §五 "预期" 那一列
   说的东西（竖排同轴、抽头可见、支路归属、地表达统一、空间不足报告…），不是断言
   某组坐标——坐标是编译器的产物，断言坐标等于把一次输出钉成规范；
2. **纪律**（052 §8 逐字）：CircuitSpec / PresentationSpec **全部手写 JSON**（本文件
   内的 helper 构造，不建夹具文件、绝不喂参考图坐标）；预期网络由测试**独立指定**
   （每个场景自带 `expected_groups`，不与编译器共享任何数据结构）；成功率分母
   **含拒绝**（`test_all_twelve_scenarios_denominator_includes_refusals`）；
3. **负例由独立检查器检出**（§六）：场景 11/12 的错法先由编译器拒绝，再把"错在图上"
   的版本交给 `readability.check`——它只看 LayoutPlan + 两份 spec，检不到就说明这一
   批的独立性是假的；
4. **无逐例调坐标**（§六 code review 级）：`test_no_scenario_specific_constants_in_the
   _module` 扫编译器源码，禁止场景号/位号/器件值出现在语法表与编译器里。

场景 10/11/12 的"预期"是**拒绝**，所以成功判据不是"12 个都出图"，而是"该出图的出图、
该拒绝的拒绝、且拒绝带四分类里正确的那一类 + 可选动作"。

本文件不跑真机：全程离线，不 import connector / cli / rules。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutPlan
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core import symbolprofile
from boardwise.core.symbolprofile import (
    SymbolPin,
    SymbolPose,
    SymbolProfile,
    flag_glyph_box,
)
from boardwise.engines import drawcompiler as dc
from boardwise.engines import readability
from boardwise.engines import svgpreview

PROV = "verified_recipe"
UNIT = 5.0  # the compilation lattice, for reading coordinates back


# --------------------------------------------------------------- 器件库夹具
#
# Hand-written profiles: this batch judges *compilation*, so the library is a set
# of plain pin spans. A parser fixture would drag the parser's behaviour in, and a
# browser/editor round trip is exactly what 053 sec.1 says this batch does not do.


def _pins(rows: tuple[tuple[str, tuple[float, float], str], ...]) -> list[SymbolPin]:
    return [
        SymbolPin(number=number, tip=tip, name=number, direction=direction)
        for number, tip, direction in rows
    ]


def resistor(ref: str = "R0402") -> SymbolProfile:
    """A vertical two-pin resistor: tips 50 units above and below the body."""
    return SymbolProfile(
        symbol_ref=ref, title="Resistor", body=(-10.0, -20.0, 10.0, 20.0),
        pins=_pins((("1", (0.0, 50.0), "up"), ("2", (0.0, -50.0), "down"))),
    )


def resistor_axial(ref: str = "R-AXIAL") -> SymbolProfile:
    """The same part drawn the other way round: pins on the horizontal axis."""
    return SymbolProfile(
        symbol_ref=ref, title="Resistor, axial", body=(-20.0, -10.0, 20.0, 10.0),
        pins=_pins((("1", (-50.0, 0.0), "left"), ("2", (50.0, 0.0), "right"))),
    )


def capacitor(ref: str = "C0402") -> SymbolProfile:
    return SymbolProfile(
        symbol_ref=ref, title="Capacitor", body=(-8.0, -12.0, 8.0, 12.0),
        pins=_pins((("1", (0.0, 40.0), "up"), ("2", (0.0, -40.0), "down"))),
    )


def capacitor_axial(ref: str = "C0805") -> SymbolProfile:
    return SymbolProfile(
        symbol_ref=ref, title="Capacitor, axial", body=(-12.0, -8.0, 12.0, 8.0),
        pins=_pins((("1", (-40.0, 0.0), "left"), ("2", (40.0, 0.0), "right"))),
    )


def regulator(ref: str = "AMS1117-3.3", *, aux: bool = False) -> SymbolProfile:
    """A three-pin regulator, plus EN and NR when asked (053 sec.3's variants)."""
    pins = [
        SymbolPin(number="3", tip=(-60.0, 0.0), name="VIN", direction="left",
                  electrical_role="VIN", role_source="pin-name"),
        SymbolPin(number="2", tip=(60.0, 0.0), name="VOUT", direction="right",
                  electrical_role="VOUT", role_source="pin-name"),
        SymbolPin(number="1", tip=(0.0, -60.0), name="GND", direction="down",
                  electrical_role="GND", role_source="pin-name"),
    ]
    if aux:
        pins.extend([
            SymbolPin(number="4", tip=(-60.0, -20.0), name="EN", direction="left"),
            SymbolPin(number="5", tip=(60.0, -20.0), name="NR", direction="right"),
        ])
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-40.0, -30.0, 40.0, 30.0), pins=pins,
    )


def flag(ref: str) -> SymbolProfile:
    """A rail/ground flag: a glyph box, no pins (it is placed on a wire end)."""
    return SymbolProfile(
        symbol_ref=ref, title=ref, body=(-6.0, 0.0, 6.0, 18.0), pins=[],
    )


def ams1117_duplicate_vout(ref: str = "AMS1117-3.3-C6186") -> SymbolProfile:
    """The **measured** AMS1117 shape (054 C3, LCSC C6186): VOUT appears twice.

    GND/VOUT/VIN sit down the left side, ten units apart, and a second VOUT hangs
    off the right — the geometry that made `ldo`'s "in left, out right" rule
    unsatisfiable and that 055 G1 fixed the grammar half of (a duplicated role
    pin is not "the spec states no connection"). The tips are the ones
    `sch.component_pins` reported for C6186; the body is that run's measured bbox.
    """
    rows = (
        ("1", "GND", (-45.0, 10.0), "left"),
        ("2", "VOUT", (-45.0, 0.0), "left"),
        ("3", "VIN", (-45.0, -10.0), "left"),
        ("4", "VOUT", (45.0, 0.0), "right"),
    )
    return SymbolProfile(
        symbol_ref=ref, title=f"{ref} (measured)", body=(-35.5, -20.5, 35.5, 20.5),
        pins=[
            SymbolPin(number=number, name=role, tip=tip, direction=direction,
                      direction_source="body-box", electrical_role=role,
                      role_source="pin-name")
            for number, role, tip, direction in rows
        ],
    )


def library(**overrides: SymbolProfile) -> dict[str, SymbolProfile]:
    """The default book: every symbol the scenarios use, flags included.

    Complete on purpose — a test that means to prove *one* fact should not also
    trip the library-gap refusal, which has its own test.
    """
    book = {
        "R0402": resistor(), "R-AXIAL": resistor_axial(),
        "C0402": capacitor(), "C0805": capacitor_axial(),
        "AMS1117-3.3": regulator(), "AMS1117-ADJ": regulator("AMS1117-ADJ", aux=True),
        "AMS1117-3.3-C6186": ams1117_duplicate_vout(),
    }
    for name in ("PWR-GND", "PWR-VIN", "PWR-OUT", "PWR-VIN5", "PWR-3V3"):
        book[name] = flag(name)
    book.update(overrides)
    return book


# ------------------------------------------------------------- 手写 spec 构造


def part(part_id: str, symbol: str, value: str = "") -> dict:
    return {"id": part_id, "symbolRef": symbol, "value": value, "provenance": PROV}


def net(net_id: str, cls: str, members: list[str]) -> dict:
    return {"id": net_id, "class": cls, "members": list(members), "provenance": PROV}


def circuit(parts: list[dict], nets: list[dict], nc: list[str] | None = None) -> CircuitSpec:
    payload: dict = {"parts": parts, "nets": nets}
    if nc:
        payload["nc"] = list(nc)
    return CircuitSpec.from_dict(payload)


def presentation(grammar: str, **overrides) -> PresentationSpec:
    payload: dict = {"grammarRef": grammar}
    payload.update(overrides)
    return PresentationSpec.from_dict(payload)


def module(module_id: str, parts: list[str], role: str) -> dict:
    return {"id": module_id, "parts": list(parts), "role": role}


# ------------------------------------------------------------------- 12 场景


@dataclass(frozen=True)
class Scene:
    """One of 053 sec.5's twelve cases, with what it is supposed to show."""

    number: int
    title: str
    circuit: CircuitSpec
    presentation: PresentationSpec
    budget: dc.CompileBudget = field(default_factory=dc.CompileBudget)
    #: The part groups the drawing must end up with, stated here and compared
    #: against the *checker's* derivation — never against the compiler's own idea.
    expect_candidates: bool = True
    expect_category: str = ""
    #: Independent expectation of the net partition: (net id, sorted members).
    expected_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    module_parts: tuple[str, ...] = ()


def divider_circuit(*, values: tuple[str, str] = ("10k", "10k"),
                    symbols: tuple[str, str] = ("R0402", "R0402"),
                    ids: tuple[str, str] = ("R1", "R2")) -> CircuitSpec:
    return circuit(
        [part(ids[0], symbols[0], values[0]), part(ids[1], symbols[1], values[1])],
        [
            net("VIN", "power", [f"{ids[0]}.1"]),
            net("TAP", "signal", [f"{ids[0]}.2", f"{ids[1]}.1"]),
            net("GND", "gnd", [f"{ids[1]}.2"]),
        ],
    )


def divider_presentation(parts: tuple[str, ...] = ("R1", "R2"), **overrides):
    payload = {
        "modules": [module("divider", list(parts), "divider")],
        "portRoles": {"VIN": "input", "TAP": "output"},
        "directWiringObligations": [{"nets": ["VIN", "TAP", "GND"],
                                     "note": "the whole ladder is wired"}],
    }
    payload.update(overrides)
    return presentation("voltage-divider", **payload)


def ladder_circuit() -> CircuitSpec:
    """A three-arm ladder with two taps and one parallel branch (multi-tap)."""
    return circuit(
        [part("R1", "R0402", "10k"), part("R2", "R0402", "4k7"),
         part("R3", "R0402", "1k"), part("C1", "C0402", "100n")],
        [
            net("VIN", "power", ["R1.1"]),
            net("TAP1", "signal", ["R1.2", "R2.1", "C1.1"]),
            net("TAP2", "signal", ["R2.2", "R3.1"]),
            net("GND", "gnd", ["R3.2", "C1.2"]),
        ],
    )


def ladder_presentation():
    return presentation(
        "voltage-divider",
        modules=[module("ladder", ["R1", "R2", "R3", "C1"], "resistor ladder")],
        portRoles={"VIN": "input"},
        directWiringObligations=[{"nets": ["VIN", "TAP1", "TAP2", "GND"],
                                  "note": "the ladder is one wired chain"}],
    )


def rc_circuit(*, series_symbol: str = "R-AXIAL",
               shunt_symbols: tuple[str, ...] = ("C0402",),
               values: tuple[str, ...] = ()) -> CircuitSpec:
    parts = [part("R1", series_symbol, "100")]
    out_members = ["R1.2"]
    gnd_members: list[str] = []
    for index, symbol in enumerate(shunt_symbols):
        shunt_id = f"C{index + 1}"
        value = values[index] if index < len(values) else "100n"
        parts.append(part(shunt_id, symbol, value))
        out_members.append(f"{shunt_id}.1")
        gnd_members.append(f"{shunt_id}.2")
    return circuit(
        parts,
        [
            net("VIN", "power", ["R1.1"]),
            net("OUT", "signal", out_members),
            net("GND", "gnd", gnd_members),
        ],
    )


def rc_presentation(shunts: tuple[str, ...] = ("C1",)):
    return presentation(
        "rc-lowpass",
        modules=[module("filter", ["R1", *shunts], "low-pass")],
        portRoles={"OUT": "output"},
        directWiringObligations=[{"nets": ["VIN", "OUT", "GND"],
                                  "note": "trunk and branch are wired"}],
    )


def ldo_circuit(*, aux: bool = False, symbol: str = "AMS1117-3.3") -> CircuitSpec:
    """053 sec.5 scenarios 8/9's circuit, with an output capacitor that passes facts.

    The output cap is **22µF**, not 100nF (055 G3): this repo's facts require an
    AMS1117's output to carry at least 22µF, so the example circuit is compliant
    rather than a circuit its own `decap-required-caps` rule has to warn about —
    which also matters live, where `draw apply` refuses to save a drawing that
    adds a finding (036's rule). The value's box is unchanged (`22µF` and `100n`
    have the same advance width in the compiler's glyph table), so the geometry
    the scenarios pin does not move.
    """
    parts = [
        part("U1", symbol, symbol),
        part("C1", "C0805", "10u"),
        part("C2", "C0402", "22µF"),
    ]
    nets = [
        net("VIN5", "power", ["U1.3", "C1.1"]),
        net("3V3", "power", ["U1.2", "C2.1"]),
        net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
    ]
    if aux:
        parts.extend([part("R2", "R0402", "10k"), part("C3", "C0402", "10n")])
        nets.append(net("EN", "signal", ["U1.4", "R2.1"]))
        nets.append(net("NR", "signal", ["U1.5", "C3.1"]))
        nets[2] = net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "R2.2", "C3.2"])
    return circuit(parts, nets)


def ldo_presentation(parts: tuple[str, ...] = ("U1", "C1", "C2"), **overrides):
    payload = {
        "modules": [module("rail", list(parts), "regulator and its decoupling")],
        "portRoles": {"VIN5": "input", "3V3": "output"},
        "directWiringObligations": [{"nets": ["VIN5", "3V3"],
                                     "note": "in→core→out is wired"}],
    }
    payload.update(overrides)
    return presentation("ldo", **payload)


def scenes() -> dict[int, Scene]:
    """The twelve, freshly built (so no test can perturb another's inputs)."""
    narrow = dc.CompileBudget(page_box=(0.0, 0.0, 240.0, 300.0))
    return {
        1: Scene(
            1, "divider, standard symbols",
            divider_circuit(), divider_presentation(),
            expected_groups=(
                ("VIN", ("R1.1",)), ("TAP", ("R1.2", "R2.1")), ("GND", ("R2.2",)),
            ),
            module_parts=("R1", "R2"),
        ),
        2: Scene(
            2, "divider, one arm drawn with the axial symbol",
            divider_circuit(symbols=("R-AXIAL", "R0402")), divider_presentation(),
            expected_groups=(
                ("VIN", ("R1.1",)), ("TAP", ("R1.2", "R2.1")), ("GND", ("R2.2",)),
            ),
            module_parts=("R1", "R2"),
        ),
        3: Scene(
            3, "divider, long reference and long value text",
            divider_circuit(values=("1.00Meg", "1.00Meg"), ids=("R123456", "R2")),
            divider_presentation(parts=("R123456", "R2")),
            expected_groups=(
                ("VIN", ("R123456.1",)), ("TAP", ("R123456.2", "R2.1")),
                ("GND", ("R2.2",)),
            ),
            module_parts=("R123456", "R2"),
        ),
        4: Scene(
            4, "divider, multi-tap ladder with a parallel branch",
            ladder_circuit(), ladder_presentation(),
            expected_groups=(
                ("VIN", ("R1.1",)),
                ("TAP1", ("C1.1", "R1.2", "R2.1")),
                ("TAP2", ("R2.2", "R3.1")),
                ("GND", ("C1.2", "R3.2")),
            ),
            module_parts=("R1", "R2", "R3", "C1"),
        ),
        5: Scene(
            5, "RC low-pass, standard",
            rc_circuit(), rc_presentation(),
            expected_groups=(
                ("VIN", ("R1.1",)), ("OUT", ("C1.1", "R1.2")),
                ("GND", ("C1.2",)),
            ),
            module_parts=("R1", "C1"),
        ),
        6: Scene(
            6, "RC low-pass, shunt drawn with the axial symbol",
            rc_circuit(shunt_symbols=("C0805",)), rc_presentation(),
            expected_groups=(
                ("VIN", ("R1.1",)), ("OUT", ("C1.1", "R1.2")),
                ("GND", ("C1.2",)),
            ),
            module_parts=("R1", "C1"),
        ),
        7: Scene(
            7, "RC low-pass with two capacitors and long values",
            rc_circuit(shunt_symbols=("C0402", "C0805"),
                       values=("100nF/50V", "2.2uF/16V")),
            rc_presentation(shunts=("C1", "C2")),
            expected_groups=(
                ("VIN", ("R1.1",)), ("OUT", ("C1.1", "C2.1", "R1.2")),
                ("GND", ("C1.2", "C2.2")),
            ),
            module_parts=("R1", "C1", "C2"),
        ),
        8: Scene(
            8, "LDO, AMS1117 with input and output capacitors",
            ldo_circuit(), ldo_presentation(),
            expected_groups=(
                ("VIN5", ("C1.1", "U1.3")), ("3V3", ("C2.1", "U1.2")),
                ("GND", ("C1.2", "C2.2", "U1.1")),
            ),
            module_parts=("U1", "C1", "C2"),
        ),
        9: Scene(
            9, "LDO with EN and NR branches",
            ldo_circuit(aux=True, symbol="AMS1117-ADJ"),
            ldo_presentation(parts=("U1", "C1", "C2", "R2", "C3")),
            expected_groups=(
                ("VIN5", ("C1.1", "U1.3")), ("3V3", ("C2.1", "U1.2")),
                ("GND", ("C1.2", "C2.2", "C3.2", "R2.2", "U1.1")),
                ("EN", ("R2.1", "U1.4")), ("NR", ("C3.1", "U1.5")),
            ),
            module_parts=("U1", "C1", "C2", "R2", "C3"),
        ),
        10: Scene(
            10, "divider in a region too small for it",
            ladder_circuit(), ladder_presentation(), narrow,
            expect_candidates=False, expect_category="layout-unsat",
        ),
        11: Scene(
            11, "deliberate short: both arms across rail and ground",
            circuit(
                [part("R1", "R0402", "10k"), part("R2", "R0402", "10k")],
                [
                    net("VIN", "power", ["R1.1", "R2.1"]),
                    net("GND", "gnd", ["R1.2", "R2.2"]),
                ],
            ),
            presentation(
                "voltage-divider",
                modules=[module("divider", ["R1", "R2"], "divider")],
                portRoles={"VIN": "input"},
                directWiringObligations=[{"nets": ["VIN", "GND"],
                                          "note": "the chain is wired"}],
            ),
            expect_candidates=False, expect_category="circuit-invalid",
        ),
        12: Scene(
            12, "userLocks that fight the grammar",
            divider_circuit(),
            divider_presentation(userLocks=[
                {"partId": "R1", "x": 200.0, "y": 500.0, "rotation": 0},
                {"partId": "R2", "x": 400.0, "y": 200.0, "rotation": 0},
            ]),
            expect_candidates=False, expect_category="presentation-poor",
        ),
    }


# --------------------------------------------------------------- 公共小工具


def compile_scene(scene: Scene) -> dc.CompileResult:
    return dc.compile(scene.circuit, scene.presentation, library(), scene.budget)


def recheck(plan: LayoutPlan, scene: Scene) -> readability.CheckResult:
    """The independent layer, run on the finished plan (no compiler state)."""
    return readability.check(
        plan, scene.circuit, scene.presentation, library(),
        page_box=scene.budget.page_box, keepouts=scene.budget.keepouts,
    )


def derived_groups(plan: LayoutPlan, scene: Scene) -> tuple[tuple[str, ...], ...]:
    """The net partition read off the *drawing* by the checker's own derivation."""
    derived = readability.derive_netlist(plan, library())
    return derived.groups


def plan_net_names(plan: LayoutPlan) -> dict[str, set[str]]:
    """``member pin -> the names the drawing states on its node``."""
    names: dict[str, set[str]] = {}
    for label in plan.labels:
        names.setdefault(label.net, set()).add(label.text)
    for symbol in plan.power_symbols:
        names.setdefault(symbol.net, set()).add(symbol.net)
    return names


def anchors_with(plan: LayoutPlan, net_id: str) -> list[tuple[float, float]]:
    """Every place the drawing states this net: label anchors and flag anchors."""
    out = [(label.x, label.y) for label in plan.labels if label.net == net_id]
    out.extend(
        (symbol.x, symbol.y) for symbol in plan.power_symbols if symbol.net == net_id
    )
    return out


def pin_point(plan: LayoutPlan, member: str) -> tuple[float, float] | None:
    """Where the plan puts a spec pin, through the profile and the plan's pose."""
    part_id, _, token = member.partition(".")
    placed = plan.part(part_id)
    if placed is None:
        return None
    profile = library().get(placed.symbol_ref)
    if profile is None:
        return None
    pin = profile.pin(token)
    if pin is None:
        for candidate in profile.pins:
            if candidate.name == token:
                pin = candidate
                break
    if pin is None:
        return None
    from boardwise.core.geometry import transform_point

    return transform_point(
        pin.tip[0], pin.tip[1], rotation=placed.rotation, mirror=placed.mirror,
        ox=placed.x, oy=placed.y,
    )


def on_a_wire(plan: LayoutPlan, point: tuple[float, float]) -> bool:
    for segment in plan.segments:
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


def text_for(plan: LayoutPlan, value: str) -> list:
    return [text for text in plan.texts if text.text == value]


def best_of(scene: Scene) -> tuple[dc.CompileResult, LayoutPlan]:
    result = compile_scene(scene)
    assert result.ok, render(result)
    return result, result.candidates[0]


def render(result: dc.CompileResult) -> str:
    return "\n".join(result.notes) + "\n" + result.render_failures()


def assert_independently_clean(plan: LayoutPlan, scene: Scene) -> readability.CheckResult:
    """Zero hard violations, and the net partition the scene expected.

    The expected partition is written per scenario and compared against the
    checker's own derivation — the discipline of 052 sec.8 ("预期网络独立指定").
    """
    checked = recheck(plan, scene)
    assert checked.hard_violations == [], [v.render() for v in checked.hard_violations]
    if scene.expected_groups:
        derived = readability.derive_netlist(plan, library())
        for net_id, members in scene.expected_groups:
            groups = {derived.group_of(member) for member in members}
            assert len(groups) == 1, (
                f"net {net_id} should be one node in the drawing, the derivation "
                f"found {len(groups)}: {sorted(groups)}"
            )
            assert groups.pop() == tuple(sorted(members)), net_id
    return checked


def assert_schema_round_trip(plan: LayoutPlan) -> None:
    """A plan that cannot be read back is not a plan: schema + digests must hold."""
    payload = plan.to_jsonable()
    again = LayoutPlan.from_dict(payload)
    assert again.geometry_sha256() == plan.geometry_sha256()
    assert len(payload["geometrySha256"]) == 64
    for entry in payload["parts"]:
        assert re.fullmatch(r"[0-9a-f]{64}", entry["symbolHash"])
    assert re.fullmatch(r"[0-9a-f]{64}", payload["source"]["circuitSha256"])
    assert re.fullmatch(r"[0-9a-f]{64}", payload["source"]["presentationSha256"])

# ------------------------------------------------------------------ 场景 1–3


def test_scene_01_divider_standard_is_drawn_as_a_column_with_a_visible_tap():
    """053 sec.5 scenario 1: 竖排同轴、抽头可见、零硬违规."""
    scene = scenes()[1]
    result, plan = best_of(scene)

    assert 3 <= len(result.candidates) <= 8, render(result)
    assert_independently_clean(plan, scene)
    assert_schema_round_trip(plan)

    upper, lower = plan.part("R1"), plan.part("R2")
    assert upper is not None and lower is not None
    assert upper.x == lower.x, "the two arms share one column (053 sec.3 同轴)"
    assert upper.y > lower.y, "the upper arm is nearer the power end"

    # The tap is visible: a labelled stub, not just a junction (053 sec.3 直接可见).
    taps = [label for label in plan.labels if label.net == "TAP"]
    assert taps, "the tap net carries a label"
    assert on_a_wire(plan, (taps[0].x, taps[0].y)), "the label sits on a wire end"
    assert plan.junctions, "the stub tees into the chain, so a junction is declared"

    # The two ends are named by flags, and each is attached to its pin by a wire.
    assert {symbol.net for symbol in plan.power_symbols} == {"VIN", "GND"}
    for member, net_id in (("R1.1", "VIN"), ("R2.2", "GND")):
        point = pin_point(plan, member)
        assert point is not None
        assert any(
            abs(point[0] - anchor[0]) < 1e-6 and abs(point[1] - anchor[1]) < 1e-6
            for anchor in anchors_with(plan, net_id)
        ) or on_a_wire(plan, point), member


def test_scene_02_divider_with_the_axial_symbol_keeps_the_relations_not_the_coordinates():
    """053 sec.5 scenario 2: 同语法成立，坐标不同关系不变."""
    scene = scenes()[2]
    result, plan = best_of(scene)

    assert_independently_clean(plan, scene)
    upper, lower = plan.part("R1"), plan.part("R2")
    assert upper is not None and lower is not None
    assert upper.x == lower.x and upper.y > lower.y
    # The axial symbol's pins run horizontally, so the compiler had to turn it;
    # scenario 1's plan had both parts at 0 degrees, which is the "coordinates
    # differ, relation does not" claim of the table.
    assert upper.rotation in (90.0, 270.0), (
        f"an axial symbol used as a vertical arm must be rotated, got "
        f"{upper.rotation}"
    )
    assert lower.rotation == 0.0
    reference = best_of(scenes()[1])[1]
    assert (upper.rotation, upper.x, upper.y) != (
        reference.part("R1").rotation, reference.part("R1").x, reference.part("R1").y
    )


def test_scene_03_long_text_is_measured_by_font_metrics_and_never_overlaps():
    """053 sec.5 scenario 3: 文字 bbox 参与避让，不压字."""
    scene = scenes()[3]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    long_ref = text_for(plan, "R123456")
    long_value = text_for(plan, "1.00Meg")
    assert long_ref and long_value, "both long texts are on the page"
    for text in (*long_ref, *long_value):
        width = text.bbox[2] - text.bbox[0]
        assert width == pytest.approx(dc.text_width(text.text), abs=1e-6), text.text
        # The gap engines/layout.py documented at LABEL_CHAR_WIDTH: a box from a
        # character *count* would be 6 units per character, and these strings do
        # not have that width.
        assert width != pytest.approx(6.0 * len(text.text), abs=0.5) or all(
            character in "iIl1.," for character in text.text
        )


# ------------------------------------------------------------------ 场景 4–7


def test_scene_04_multi_tap_ladder_has_every_tap_visible_and_the_branch_owned():
    """053 sec.5 scenario 4: 变体成立，每抽头可见."""
    scene = scenes()[4]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    arms = [plan.part(name) for name in ("R1", "R2", "R3")]
    assert all(arm is not None for arm in arms)
    assert len({arm.x for arm in arms}) == 1, "the ladder is one column"
    assert arms[0].y > arms[1].y > arms[2].y

    for tap in ("TAP1", "TAP2"):
        labels = [label for label in plan.labels if label.net == tap]
        assert labels, tap
        assert on_a_wire(plan, (labels[0].x, labels[0].y)), tap

    # The parallel branch hangs on TAP1 and reads as owned by it: its pin is on
    # TAP1's own wiring, and it is close to the arm the tap leaves.
    branch_pin = pin_point(plan, "C1.1")
    assert branch_pin is not None
    assert on_a_wire(plan, branch_pin), "the branch pin touches its node's wire"
    upper = plan.part("R1")
    assert abs(branch_pin[0] - upper.x) <= 300.0
    owned = [f for f in result.ranked[0].findings if f.kind == dc.KIND_OBLIGATION_MISSING]
    assert owned == [], [f.render() for f in owned]


def test_scene_05_rc_trunk_is_one_row_and_the_branch_belongs_to_the_output():
    """053 sec.5 scenario 5: 主干直连、支路归属 out."""
    scene = scenes()[5]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    series, shunt = plan.part("R1"), plan.part("C1")
    assert series is not None and shunt is not None
    out_pin = pin_point(plan, "R1.2")
    trunk_pin = pin_point(plan, "C1.1")
    gnd_pin = pin_point(plan, "C1.2")
    assert out_pin is not None and trunk_pin is not None and gnd_pin is not None
    assert out_pin[1] == trunk_pin[1], "the shunt's out-side pin lands on the row"
    assert gnd_pin[1] < trunk_pin[1], "and its body hangs below, toward ground"
    assert trunk_pin[0] > out_pin[0], "the branch is beyond the output end"
    # The trunk is one wire, so the series pin and the shunt pin fall on one
    # segment: 主干直连.
    assert any(
        _on_segment(out_pin, segment.points[0], segment.points[-1])
        and _on_segment(trunk_pin, segment.points[0], segment.points[-1])
        for segment in plan.segments
    ), "OUT is drawn as a single wire from the series element to the shunt"


def test_scene_06_rc_with_the_axial_shunt_rotates_it_instead_of_special_casing():
    """053 sec.5 scenario 6: RC 换符号朝向."""
    scene = scenes()[6]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    shunt = plan.part("C1")
    assert shunt is not None
    assert shunt.rotation in (90.0, 270.0), (
        f"an axial capacitor used as a vertical shunt must be rotated, got "
        f"{shunt.rotation}"
    )
    out_pin = pin_point(plan, "R1.2")
    trunk_pin = pin_point(plan, "C1.1")
    gnd_pin = pin_point(plan, "C1.2")
    assert out_pin[1] == trunk_pin[1] and gnd_pin[1] < trunk_pin[1]


def test_scene_07_two_shunts_and_long_values_stay_owned_and_legible():
    """053 sec.5 scenario 7: 支路群归属清晰不压字."""
    scene = scenes()[7]
    result, plan = best_of(scene)
    checked = assert_independently_clean(plan, scene)
    assert checked.soft_metrics["min_text_gap"] > 0.0, "no two text boxes touch"

    row = pin_point(plan, "R1.2")[1]
    roots = [pin_point(plan, member) for member in ("C1.1", "C2.1")]
    assert all(root is not None and root[1] == row for root in roots)
    assert len({root[0] for root in roots}) == 2, "the two branches sit at their own x"
    for value in ("100nF/50V", "2.2uF/16V"):
        assert text_for(plan, value), value


# ------------------------------------------------------------------ 场景 8–9


def test_scene_08_ldo_puts_each_capacitor_on_its_own_side_and_one_ground_style():
    """053 sec.5 scenario 8: 电容各归各侧、地表达统一."""
    scene = scenes()[8]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    core = plan.part("U1")
    in_cap, out_cap = plan.part("C1"), plan.part("C2")
    assert core is not None and in_cap is not None and out_cap is not None
    assert in_cap.x < core.x < out_cap.x, "in cap left, out cap right (053 sec.3)"

    # Each capacitor's rail-side pin is on its rail: the input rail at the core's
    # VIN row, the output rail at its VOUT row.
    vin = pin_point(plan, "U1.3")
    vout = pin_point(plan, "U1.2")
    assert pin_point(plan, "C1.1")[1] == vin[1]
    assert pin_point(plan, "C2.1")[1] == vout[1]
    for member, net_id in (("U1.3", "VIN5"), ("C1.1", "VIN5"), ("U1.2", "3V3"),
                           ("C2.1", "3V3")):
        assert on_a_wire(plan, pin_point(plan, member)), member

    # 地表达统一：one style, one symbol, for every ground pin.
    ground_flags = [s for s in plan.power_symbols if s.net == "GND"]
    assert len(ground_flags) == 3
    assert len({s.symbol_ref for s in ground_flags}) == 1
    assert not [label for label in plan.labels if label.net == "GND"]


def test_scene_09_ldo_aux_branches_hang_off_their_own_core_pin():
    """053 sec.5 scenario 9: EN / NR 支路成立."""
    scene = scenes()[9]
    result, plan = best_of(scene)
    assert_independently_clean(plan, scene)

    core = plan.part("U1")
    en_pin = pin_point(plan, "U1.4")
    nr_pin = pin_point(plan, "U1.5")
    en_branch = pin_point(plan, "R2.1")
    nr_branch = pin_point(plan, "C3.1")
    assert all(
        item is not None
        for item in (core, en_pin, nr_pin, en_branch, nr_branch)
    )
    assert en_branch[1] == en_pin[1] and en_branch[0] < en_pin[0], (
        "the EN pull-down hangs off the EN pin, on the side that pin points to"
    )
    assert nr_branch[1] == nr_pin[1] and nr_branch[0] > nr_pin[0]
    assert on_a_wire(plan, en_branch) and on_a_wire(plan, nr_branch)


def test_a_flag_is_rotated_so_its_glyph_hangs_away_from_the_pin():
    """060 sec.3: the ground symbol hangs *below* its connection, so the compass flips.

    The library's own ``Ground-GND`` symbol carries ``BBOX (-10, 0, 10, -19)``:
    its connection sits at the top of the stem and the bars run below it (read out
    of an export's own SYMBOL documents — `tools/060_flag_glyph_evidence.py`). A
    flag anchored *below* its pin is therefore drawn at rotation ``0``, not
    ``180``, and the box the drawing reserves — the glyph hanging away from the
    pin — is on the far side of the anchor from it.

    Nothing offline pinned this number: 054-059 passed every test with the whole
    compass 180 out and landed every GND flag upside down.
    """
    profile = flag("PWR-GND")
    anchor = (0.0, 0.0)
    for direction, rotation in (
        ((0.0, 1.0), 180.0),
        ((-1.0, 0.0), 270.0),
        ((0.0, -1.0), 0.0),
        ((1.0, 0.0), 90.0),
    ):
        assert dc.flag_rotation(direction) == rotation, direction
        box = flag_glyph_box(profile, rotation=rotation, anchor=anchor)
        assert box is not None
        centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
        away = (
            (centre[0] - anchor[0]) * direction[0]
            + (centre[1] - anchor[1]) * direction[1]
        )
        assert away > 0.0, (
            f"the glyph box {box} hangs on the same side of {anchor} as the pin "
            f"it names (escaping {direction}) — 060 sec.3's whole point"
        )


def test_a_ground_flag_below_its_pin_is_drawn_hanging_in_the_preview():
    """The plan's rotation and the preview agree, and both say "hanging".

    Two assertions, catching two different things:

    * a ground flag whose pin escapes **downwards** carries rotation ``0`` — the
      number the editor is given, and the one 054-059 got wrong;
    * the preview draws that flag's glyph **below its anchor dot**, with the dot
      on the glyph's top edge — the connection at the stem's tip, the bars
      hanging. Before 060 the preview drew the box from the plan's rotation
      directly, which at the corrected number would have put the glyph *over* the
      wire instead of under it (`core.symbolprofile.flag_glyph_box` is the one
      place the two now share).
    """
    scene = scenes()[1]
    result, plan = best_of(scene)
    assert result.ok
    ground = [item for item in plan.power_symbols if item.net == "GND"]
    assert ground, "the ladder's ground is named by a flag"
    book = library()
    for symbol in ground:
        assert symbol.rotation == 0.0, (
            f"a GND flag anchored below its pin is drawn at 0, not "
            f"{symbol.rotation} (060 sec.3)"
        )
        box = flag_glyph_box(
            book[symbol.symbol_ref], rotation=symbol.rotation,
            anchor=(symbol.x, symbol.y),
        )
        assert box is not None
        assert box[3] <= symbol.y + 1e-6, (
            f"the glyph box {box} starts below the anchor row {symbol.y}: a flag "
            "below its pin hangs its bars downwards (060 sec.3)"
        )
        assert box[1] < symbol.y, "the box occupies the rows under the anchor"

    root = ElementTree.fromstring(svgpreview.render_svg(plan, book))
    circles = [
        item for item in root.iter()
        if item.tag.endswith("circle") and item.get("fill") == "#b45309"
    ]
    rects = [
        item for item in root.iter()
        if item.tag.endswith("rect") and item.get("stroke") == "#b45309"
    ]
    assert len(circles) == len(plan.power_symbols) > len(ground)
    assert len(rects) == len(plan.power_symbols)
    # A glyph whose top edge lands on an anchor dot is one hanging *below* its
    # connection ("bars below the stem's tip"); a rail flag points the other way
    # and its box's top edge is not at the dot's row. Exactly the ground flags
    # must match — one per ground flag, which is the E1 picture's own case.
    hanging = [
        rect for rect in rects
        if any(
            abs(float(rect.get("x")) + float(rect.get("width")) / 2.0
                - float(circle.get("cx"))) < 1e-6
            and abs(float(rect.get("y")) - float(circle.get("cy"))) < 1e-6
            for circle in circles
        )
    ]
    assert len(hanging) == len(ground), (
        f"{len(hanging)} flag glyph(s) start at their anchor dot and hang below "
        f"it; every one of the {len(ground)} ground flag(s) must (060 sec.3)"
    )
    for rect in hanging:
        assert float(rect.get("height")) > 0.0


def test_a_branch_goes_to_the_side_the_grammar_reads_for_it():
    """060 sec.1: 电容各归所属节点的**那一侧** — the measured symbol's single side is not it.

    The live E1 render (059) put an LDO's input and output capacitors on top of
    each other down one side, because the branch followed the core's own pin and
    the measured AMS1117 leaves VIN *and* VOUT on the left. With the module
    stating its sides, the input capacitor belongs on the input side and the
    output capacitor on the output side — and both still have to reach their own
    pin, which is what the placement and the router have to arrange together.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(
        spec, presentation, library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    core = plan.part("U1")
    in_cap, out_cap = plan.part("C1"), plan.part("C2")
    assert core is not None and in_cap is not None and out_cap is not None
    assert in_cap.x < core.x, (
        f"the input capacitor is on the input side (left of {core.x:g}), not at "
        f"{in_cap.x:g} (060 sec.1)"
    )
    # The decisive fact is *which way* the branch leaves its pin. A capacitor
    # hanging below its pin shares the pin's column; one pushed sideways off the
    # pin (the old reading, and the live E1 render's two-caps-one-side) sits a
    # lane away in x. Both the position and the column are asserted, so a
    # placement that merely drifts downwards cannot pass this test.
    vout_tip, out_tip = pin_point(plan, "U1.2"), pin_point(plan, "C2.1")
    assert vout_tip is not None and out_tip is not None
    assert out_cap.y < core.y, (
        f"the output capacitor is on the output side (below {core.y:g}), not at "
        f"{out_cap.y:g} (060 sec.1)"
    )
    assert out_tip[0] == vout_tip[0] and out_tip[1] < vout_tip[1], (
        f"the output capacitor hangs below its own VOUT pin at {vout_tip}, not "
        f"sideways off it (its rail pin reads {out_tip}) — 060 sec.1"
    )
    # Both capacitors are wired to the pins they serve, and the input rail is not
    # routed through the core's body to get there.
    assert on_a_wire(plan, pin_point(plan, "C1.1"))
    assert on_a_wire(plan, pin_point(plan, "C2.1"))
    assert on_a_wire(plan, pin_point(plan, "U1.3"))
    assert on_a_wire(plan, pin_point(plan, "U1.2"))
    assert readability.check(
        plan, spec, presentation, library(), page_box=page,
    ).hard_violations == []


def test_a_roles_other_pins_are_wired_as_one_node_and_nc_is_the_exception():
    """060 sec.2: 重复脚默认都接上，`nc[]` 是显式例外（岳裁决 a 方案）.

    A role's several pins are one node inside the symbol, so wiring one of them
    wires the role: the picture must show the pad connected, not an empty pin
    beside a wired one (059's 岳: "有一个 VOUT 空悬（负责散热的大引脚）"). The spec
    does not have to spell the duplicate out; listing it in ``nc[]`` still keeps
    it off, because that is a stated decision rather than an omission.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    presentation = ldo_presentation()
    default = dc.compile(
        _duplicate_vout_circuit(out_members=["U1.2", "C2.1"]),
        presentation, library(), dc.CompileBudget(page_box=page),
    )
    assert default.ok, render(default)
    plan = default.candidates[0]
    drawn = readability.derive_netlist(plan, library())
    u1_2, u1_4 = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    assert u1_2 is not None and u1_4 is not None
    assert on_a_wire(plan, u1_4), (
        "the duplicate VOUT pad is wired by default (060 sec.2) — an empty pad "
        "beside a wired one is the shape 059 was sent back for"
    )
    assert drawn.group_of("U1.2") == drawn.group_of("U1.4"), (
        "the two VOUT pins are one node in the drawing"
    )

    explicit = dc.compile(
        _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"]),
        presentation, library(), dc.CompileBudget(page_box=page),
    )
    assert explicit.ok, render(explicit)
    quiet = explicit.candidates[0]
    assert not on_a_wire(quiet, pin_point(quiet, "U1.4")), (
        "an explicit nc[] is still an explicit no-connect (岳裁决: nc 降为显式例外)"
    )
    # The rule the checker grades this node against is the same one the compiler
    # wires it with, and it says which pins are "the same role".
    profile = library()["AMS1117-3.3-C6186"]
    assert {pin.number for pin in symbolprofile.role_siblings(profile, "2")} == {
        pin.number for pin in profile.pins
        if pin.name == "VOUT" and pin.number != "2"
    }


def _duplicate_vout_circuit(*, out_members: list[str],
                            nc: list[str] | None = None) -> CircuitSpec:
    """The measured AMS1117 shape: which of its two VOUT pins the circuit uses."""
    return circuit(
        [
            part("U1", "AMS1117-3.3-C6186", "AMS1117-3.3"),
            part("C1", "C0805", "10u"),
            part("C2", "C0805", "22u"),
        ],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", out_members),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
        nc,
    )


def test_scene_08b_the_ams1117_duplicate_vout_never_reads_as_a_compiler_bug():
    """055 G1: the measured AMS1117 (VOUT twice) must bind, then draw or refuse by name.

    055 G1's rule is that a role is a **set of pins** and each of the three forms
    has to end in a drawing or in a refusal that names its reason. Before 055 G1
    the first and third came back `facts-missing` ("the CircuitSpec states no
    connection") and the second said "a compiler bug — report it".

    060 sec.1/2 moved two of the three: a capacitor goes to the side the grammar
    reads for it (so the symbol's single-sided pin set no longer decides the
    drawing), and a role's other pins are wired as the same node (so "both wired"
    is not a duplicate statement but the default shape). The far pad with the near
    pin NC'd still has no legal pose — 坑 33's geometry, and the refusal names it.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    cases: dict[str, tuple[list[str], list[str] | None, str]] = {
        # (members of 3V3, nc[], the only category a refusal may use — "" means
        # this form must draw, which is what 060 sec.1/2 changed for two of them)
        "duplicate wired, original nc": (["U1.4", "C2.1"], ["U1.2"], "layout-unsat"),
        "original wired, duplicate nc": (["U1.2", "C2.1"], ["U1.4"], ""),
        "both wired to one net": (["U1.2", "U1.4", "C2.1"], None, ""),
    }
    for name, (members, nc, category) in cases.items():
        spec = _duplicate_vout_circuit(out_members=members, nc=nc)
        result = dc.compile(
            spec, ldo_presentation(), library(), dc.CompileBudget(page_box=page),
        )
        text = render(result)
        assert "compiler bug" not in text, (name, text)
        assert "neither a net member nor an explicit nc" not in text, (name, text)
        assert result.grammar is not None and result.grammar.ok, (
            name, "the grammar binds a duplicated role pin", text,
        )
        assert result.grammar.net_of("out") == "3V3", (name, text)
        if result.candidates:
            # The picture, when one comes out, places the core it bound.
            assert category == "", (name, "this form draws nowadays", text)
            assert result.candidates[0].part("U1") is not None, name
        else:
            assert category, (name, "this form must draw", text)
            assert result.categories() == [category], (name, text)
            assert all(item.detail and item.action for item in result.failures), name
    # One of the two shapes 055 G1 documented as a refusal still refuses, and by
    # the same route: the far VOUT pad on the net with the near pin NC'd has no
    # pose that puts VIN and that pad on one line (坑 33's geometry, untouched).
    # The other one draws now: 060 sec.1 sends an LDO's capacitor to the side the
    # grammar reads for it instead of to the core's own pin line, so the
    # single-sided pin set stops deciding this drawing. What must not come back
    # is an unnamed or self-accusing refusal.
    shape = None
    for members, nc in (
        (["U1.2", "C2.1"], ["U1.4"]),      # the original VOUT, down the left side
        (["U1.4", "C2.1"], ["U1.2"]),      # the duplicate, on the right
    ):
        result = dc.compile(
            _duplicate_vout_circuit(out_members=members, nc=nc),
            ldo_presentation(), library(), dc.CompileBudget(page_box=page),
        )
        text = render(result)
        assert "compiler bug" not in text, (members, text)
        assert "neither a net member nor an explicit nc" not in text, (members, text)
        if result.candidates:
            assert result.candidates[0].part("U1") is not None, (members, text)
            continue
        (failure,) = result.failures
        shape = failure
    assert shape is not None, "the far-pad shape still has no legal pose"
    assert "no legal pose" in shape.detail and "AMS1117-3.3-C6186" in shape.detail
    assert shape.action, "a refusal always carries what to change"


def test_scene_08c_a_duplicated_role_pin_nc_is_recorded_as_handled():
    """055 G1 (b): the pin written into `nc[]` is a decision, not a gap."""
    spec = _duplicate_vout_circuit(out_members=["U1.4", "C2.1"], nc=["U1.2"])
    result = dc.compile(
        spec, ldo_presentation(), library(),
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    core = result.grammar.bindings_for("core")[0]
    assert "VOUT→spec pin 4 (matched by number)" in core.evidence
    assert "pin(s) 2 are listed in nc[]" in core.evidence
    assert "explicit no-connect, not a missing fact" in core.evidence


def test_scene_08d_every_duplicate_pin_nc_is_a_named_circuit_invalid_refusal():
    """The one shape NC cannot save: a role with no pin anywhere, named pin by pin."""
    spec = _duplicate_vout_circuit(out_members=["C2.1"], nc=["U1.2", "U1.4"])
    result = dc.compile(
        spec, ldo_presentation(), library(),
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.candidates == []
    assert result.categories() == ["circuit-invalid"]
    (failure,) = result.failures
    assert "every VOUT pin" in failure.detail and "2, 4" in failure.detail
    assert "<U1.2>" in failure.action and "<U1.4>" in failure.action


def test_scene_08e_the_same_circuit_draws_once_the_sides_match_the_symbol():
    """The refusal above is about the **sides**, not about the pin mapping.

    The same circuit — the measured AMS1117 with its left VOUT wired — draws as
    soon as the presentation states the side this symbol's pins actually leave
    on (053 sec.3: the grammar follows `sidePreferences`). That is the input-side
    fix the LDO's real-machine run recorded, and stating it is what turns "no
    legal layout" into a drawing rather than into a bent symbol.
    """
    spec = _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"])
    scene = Scene(
        8, "the measured AMS1117, sides stated", spec,
        ldo_presentation(sidePreferences={"input": "left", "output": "bottom"}),
    )
    result = dc.compile(
        spec, scene.presentation, library(),
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, render(result)
    assert len(result.candidates) >= 3, render(result)
    plan = result.candidates[0]
    assert plan.part("U1") is not None and plan.part("C2") is not None
    assert_independently_clean(plan, scene)


# ---------------------------------------------------------------- 场景 10–12


def _mutate(
    plan: LayoutPlan,
    *,
    segments: list | None = None,
    labels: list | None = None,
    power_symbols: list | None = None,
) -> LayoutPlan:
    """A copy of `plan` with one list replaced — how the negative cases are built.

    Scenario 11 is about a *drawing* that is wrong, so the deliberate mistake is
    made on the compiled plan (never on the compiler): the independent checker
    then has to see it working from the plan alone.
    """
    return LayoutPlan(
        source=plan.source,
        target=plan.target,
        parts=list(plan.parts),
        segments=list(segments if segments is not None else plan.segments),
        junctions=list(plan.junctions),
        labels=list(labels if labels is not None else plan.labels),
        power_symbols=list(
            power_symbols if power_symbols is not None else plan.power_symbols
        ),
        texts=list(plan.texts),
        notes=list(plan.notes),
    )


def _shorted(plan: LayoutPlan) -> LayoutPlan:
    """The divider with a wire from its tap node down to the ground pin.

    A one-wire change, which is the point: the checker has to see that the tap's
    node and ground are now one node without being told.
    """
    from boardwise.core.layoutplan import LayoutSegment

    tap = [label for label in plan.labels if label.net == "TAP"][0]
    ground = pin_point(plan, "R2.2")
    assert ground is not None
    junction = (tap.x, tap.y)
    elbow = (ground[0], tap.y)
    return _mutate(plan, segments=[
        *plan.segments,
        LayoutSegment(net="GND", points=[junction, elbow, ground]),
    ])


def _reached_for_the_wrong_pin(plan: LayoutPlan) -> LayoutPlan:
    """The divider's tap wire rerouted to the *lower* arm's ground pin.

    The membership is what changes: TAP ends up holding one pin, and the other
    pin it should have is now on the ground node.
    """
    from boardwise.core.layoutplan import LayoutSegment

    upper = pin_point(plan, "R1.2")
    wrong = pin_point(plan, "R2.2")
    assert upper is not None and wrong is not None
    detour = wrong[0] + 30.0
    segments = [segment for segment in plan.segments if segment.net != "TAP"]
    return _mutate(plan, segments=[
        *segments,
        LayoutSegment(net="TAP", points=[
            upper, (upper[0], upper[1] - 10.0), (detour, upper[1] - 10.0),
            (detour, wrong[1]), wrong,
        ]),
    ])


def _with_a_wire_on(plan: LayoutPlan, net_id: str, member: str) -> LayoutPlan:
    """The same plan, plus a wire hanging off one pin (used for the NC case)."""
    from boardwise.core.layoutplan import LayoutSegment

    point = pin_point(plan, member)
    assert point is not None
    return _mutate(plan, segments=[
        *plan.segments,
        LayoutSegment(net=net_id, points=[point, (point[0] - 40.0, point[1])]),
    ])


def test_scene_10_a_region_too_small_is_reported_with_an_action_not_squeezed():
    """053 sec.5 scenario 10: 报告空间不足 + 可选动作，不许硬挤压字."""
    scene = scenes()[10]
    result = compile_scene(scene)

    assert result.candidates == []
    assert result.categories() == ["layout-unsat"]
    (failure,) = result.failures
    assert failure.action, "a space failure has to say what would fix it"
    text = failure.detail + " " + failure.action
    assert "canvas units" in text and re.search(r"\d+(\.\d+)? x \d+", text), text
    assert "not squeezed" in failure.detail
    assert "enlarge the region" in failure.action
    assert result.rejected and all(item.reason for item in result.rejected)


def test_scene_11a_a_short_is_refused_and_a_shorted_drawing_is_caught():
    """053 sec.5 scenario 11 (短路): 编译器拒绝，独立检查器检出."""
    scene = scenes()[11]
    result = compile_scene(scene)

    assert result.candidates == []
    assert "circuit-invalid" in result.categories()
    assert all(failure.action for failure in result.failures)
    assert any(
        "parallel" in failure.detail for failure in result.failures
    ), render(result)

    healthy_scene = scenes()[1]
    healthy = best_of(healthy_scene)[1]
    caught = readability.check(
        _shorted(healthy), healthy_scene.circuit, healthy_scene.presentation,
        library(),
    )
    assert any(
        item.kind == readability.KIND_NETLIST_PARTITION
        for item in caught.hard_violations
    ), [item.render() for item in caught.hard_violations]


def test_scene_11b_a_pin_on_the_wrong_net_is_refused_and_a_wrong_pin_wire_is_caught():
    """053 sec.5 scenario 11 (错脚): 编译器拒绝，独立检查器检出."""
    wrong = circuit(
        [part("R1", "R0402", "10k"), part("R2", "R0402", "10k")],
        [
            net("VIN", "power", ["R1.1"]),
            net("TAP", "signal", ["R1.2"]),
            net("GND", "gnd", ["R2.1", "R2.2"]),
        ],
    )
    result = dc.compile(wrong, divider_presentation(), library())
    assert result.candidates == []
    assert "circuit-invalid" in result.categories()
    assert all(failure.action for failure in result.failures)

    healthy = best_of(scenes()[1])[1]
    caught = readability.check(
        _reached_for_the_wrong_pin(healthy), scenes()[1].circuit,
        scenes()[1].presentation, library(),
    )
    assert any(
        item.kind == readability.KIND_NETLIST_PARTITION
        for item in caught.hard_violations
    ), [item.render() for item in caught.hard_violations]


def test_scene_11c_an_nc_pin_is_left_alone_and_a_wire_on_it_is_caught():
    """053 sec.5 scenario 11 (NC 被接): 编译器不接，检查器检出被接的版本."""
    nc_circuit = circuit(
        [part("U1", "AMS1117-ADJ", "AMS1117-ADJ"), part("C1", "C0805", "10u"),
         part("C2", "C0402", "100n"), part("C3", "C0402", "10n")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2", "C3.2"]),
            net("NR", "signal", ["U1.5", "C3.1"]),
        ],
        nc=["U1.4"],
    )
    scene = Scene(
        11, "nc pin left alone", nc_circuit,
        ldo_presentation(parts=("U1", "C1", "C2", "C3")),
        expected_groups=(
            ("VIN5", ("C1.1", "U1.3")), ("3V3", ("C2.1", "U1.2")),
            ("GND", ("C1.2", "C2.2", "C3.2", "U1.1")), ("NR", ("C3.1", "U1.5")),
        ),
    )
    result = compile_scene(scene)
    assert result.ok, render(result)
    plan = result.candidates[0]
    assert_independently_clean(plan, scene)

    en_pin = pin_point(plan, "U1.4")
    assert en_pin is not None
    assert not on_a_wire(plan, en_pin), "an explicit NC pin is left unwired"

    caught = readability.check(
        _with_a_wire_on(plan, "EN", "U1.4"), nc_circuit, scene.presentation,
        library(),
    )
    assert any(
        item.kind == readability.KIND_NC_PIN_CONNECTED
        for item in caught.hard_violations
    ), [item.render() for item in caught.hard_violations]


def test_scene_12_a_lock_that_fights_the_grammar_is_reported_with_an_action():
    """053 sec.5 scenario 12: 报告冲突+可选动作，不静默忽略锁定."""
    scene = scenes()[12]
    result = compile_scene(scene)

    assert result.candidates == []
    assert result.categories() == ["presentation-poor"]
    (failure,) = result.failures
    assert "userLocks" in failure.detail
    assert "same-column" in failure.detail, (
        "the reported conflict is the relation the locks break"
    )
    assert failure.action and "lock" in failure.action

    # The one repair the contract forbids is silence: a plan that simply ignores
    # the locks is caught by the independent checker, so "no candidate" is not the
    # same as "nobody would have noticed".
    unlocked = scenes()[1]
    ignored = best_of(unlocked)[1]
    caught = readability.check(
        ignored, unlocked.circuit, scene.presentation, library(),
    )
    assert any(
        item.kind == readability.KIND_USER_LOCK_VIOLATED
        for item in caught.hard_violations
    ), [item.render() for item in caught.hard_violations]


def test_scene_12b_a_lock_in_a_pose_the_symbol_does_not_declare_is_a_conflict():
    """053 sec.5 scenario 12 (第二种冲突): 符号没有那个姿态，锁定被报告而非归一."""
    one_pose = SymbolProfile(
        symbol_ref="R0402", title="resistor with a single declared pose",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
        poses=[SymbolPose(rotation=0, mirror=False)],
    )
    locked = dc.compile(
        scenes()[1].circuit,
        divider_presentation(userLocks=[
            {"partId": "R1", "x": 100.0, "y": 500.0, "rotation": 90},
        ]),
        library(**{"R0402": one_pose}),
    )
    assert locked.candidates == []
    assert locked.categories() == ["presentation-poor"]
    assert any("rotation" in failure.detail for failure in locked.failures)
    assert all("9" in failure.detail or "pose" in failure.detail
               or "rotation" in failure.detail for failure in locked.failures)
    assert all(failure.action for failure in locked.failures)


def test_a_lock_the_grammar_agrees_with_is_honoured_exactly():
    """The other half of scenario 12: a *consistent* lock is placed, not moved."""
    scene = scenes()[1]
    locked = dc.compile(
        scene.circuit,
        divider_presentation(userLocks=[
            {"partId": "R1", "x": 305.0, "y": 505.0, "rotation": 0},
        ]),
        library(),
    )
    assert locked.ok, render(locked)
    plan = locked.candidates[0]
    upper = plan.part("R1")
    assert (upper.x, upper.y, upper.rotation) == (305.0, 505.0, 0.0)
    assert readability.check(
        plan, scene.circuit, scene.presentation, library(),
    ).hard_violations == []
    assert plan.part("R2").x == 305.0, "the column follows the lock"

# --------------------------------------------------------- 纪律 / 出口 / 守卫


def test_all_twelve_scenarios_and_the_denominator_includes_refusals():
    """053 sec.5's table, run as one list; the rate counts rejections (052 sec.8)."""
    table = scenes()
    assert sorted(table) == list(range(1, 13))
    produced: list[int] = []
    refused: list[int] = []
    for number in sorted(table):
        scene = table[number]
        result = compile_scene(scene)
        if scene.expect_candidates:
            assert result.ok, f"scene {number}: {render(result)}"
            for plan in result.candidates:
                # Every candidate is a legal drawing: a variant the checker refused
                # is reported, never handed out (053 sec.6 "合格输出硬违规为零").
                assert plan.evidence.hard_violations == [], number
                assert plan.evidence.verdict == "pass", number
                assert readability.check(
                    plan, scene.circuit, scene.presentation, library(),
                ).hard_violations == [], number
            plan = result.candidates[0]
            assert_independently_clean(plan, scene)
            assert len(result.candidates) <= 8
            produced.append(number)
        else:
            assert not result.ok, f"scene {number} should be refused"
            assert scene.expect_category in result.categories(), (
                f"scene {number}: {result.categories()} "
                f"(expected {scene.expect_category})"
            )
            assert all(failure.action for failure in result.failures), number
            refused.append(number)
    # 9 draw, 3 are refused (10, 11, 12) — and the rate is over all twelve, so a
    # compiler that refused everything could not look perfect.
    assert len(produced) == 9 and len(refused) == 3, (produced, refused)
    assert len(produced) / len(table) == 0.75


def test_the_twelve_titles_are_the_table_from_the_task_book():
    """The scenario list is a contract, so its numbers and subjects are pinned."""
    titles = {number: scene.title for number, scene in scenes().items()}
    for number, keywords in {
        1: "divider", 2: "axial", 3: "long", 4: "multi-tap",
        5: "RC", 6: "axial", 7: "two capacitors", 8: "AMS1117",
        9: "EN and NR", 10: "too small", 11: "short", 12: "userLocks",
    }.items():
        assert keywords in titles[number], (number, titles[number])


def test_the_ranking_is_layered_and_never_summed():
    """053 sec.7: 分层排序无跨层抵消 — a later layer can never buy an earlier one."""
    # A hidden tap (findings=1) must lose to any number of crossings.
    assert dc.layered_key(0, 0, 99.0, 99.0, 9999.0, 10 ** 6) < dc.layered_key(
        0, 1, 0.0, 0.0, 0.0, 0.0
    )
    # A hard violation outranks every soft metric together.
    assert dc.layered_key(1, 0, 0.0, 0.0, 0.0, 0.0) > dc.layered_key(
        0, 3, 0.0, 0.0, 0.0, 0.0
    ) or dc.layered_key(1, 0, 0.0, 0.0, 0.0, 0.0) > dc.layered_key(
        0, 0, 0.0, 0.0, 0.0, 0.0
    )
    # Each layer is its own element, in the order legality -> expression ->
    # readability -> compactness.
    assert dc.layered_key(0, 1, 2.0, 3.0, 4.0, 5.0) > dc.layered_key(
        0, 0, 9.0, 9.0, 9.0, 9.0
    )


def test_candidates_are_ranked_in_the_layered_order_and_scores_have_no_total():
    """The result's own keys are sorted, and evidence keeps raw values + reasons."""
    scene = scenes()[4]
    result = compile_scene(scene)
    assert result.ok, render(result)
    keys = [candidate.key for candidate in result.ranked]
    assert keys == sorted(keys)
    assert all(len(key) == 6 for key in keys)
    assert result.candidates == [candidate.plan for candidate in result.ranked]

    best = result.ranked[0]
    assert best.metrics, "raw soft metrics are kept"
    assert set(best.reasons) <= set(best.metrics), (
        "a reason without a value is not a reason (052 sec.6)"
    )
    assert "score" not in best.metrics and "total" not in best.metrics
    plan = best.plan
    assert plan.evidence.checker == readability.CHECKER_NAME
    assert plan.evidence.hard_violations == []
    assert plan.evidence.verdict == "pass"
    for key, value in plan.evidence.soft_metrics.items():
        assert isinstance(value, float), key


def test_compiling_twice_gives_byte_identical_plans():
    """A compiler whose output moves between runs cannot be reviewed or diffed."""
    scene = scenes()[7]
    first = compile_scene(scene)
    second = compile_scene(scene)
    assert first.ok and second.ok
    assert [plan.geometry_sha256() for plan in first.candidates] == [
        plan.geometry_sha256() for plan in second.candidates
    ]
    assert first.candidates[0].to_jsonable() == second.candidates[0].to_jsonable()


def test_the_rendered_preview_is_byte_identical_across_two_compiles():
    """Determinism carried all the way to the file a reviewer opens.

    `outputs/053b_preview/` is regenerated from these scenarios by
    `tools/053b_previews.py`, so the previews are only worth reviewing if a
    second compile of the same input renders the *same bytes*: otherwise the
    picture is a snapshot of one run rather than of the revision, and two reviews
    of one drawing would be looking at different files. Same input, same SVG
    text — for the ranked best and for the runner-up, so the tie-break that
    picked it is covered too.
    """
    scene = scenes()[7]
    first = compile_scene(scene)
    second = compile_scene(scene)
    assert first.ok and second.ok

    def preview(result: dc.CompileResult, index: int) -> str:
        return svgpreview.render_svg(
            result.candidates[index], library(),
            page_box=scene.budget.page_box, keepouts=scene.budget.keepouts,
            title=f"053b scene {scene.number}: {scene.title}",
        )

    assert preview(first, 0) == preview(second, 0)
    assert preview(first, 1) == preview(second, 1)
    assert preview(first, 0).startswith("<svg")


def test_text_boxes_come_from_font_metrics_not_from_a_character_count():
    """053 sec.4: 文字 bbox 参与避障（不靠字符数估算）— the layout.py:1055 gap."""
    narrow = dc.text_width("iiiiii")
    wide = dc.text_width("MMMMMM")
    assert narrow < 6.0 * 6 < wide, (narrow, wide)
    # The font-metric box scales with the size, which a count cannot do.
    assert dc.text_width("1.00Meg", size=18.0) == pytest.approx(
        2.0 * dc.text_width("1.00Meg"), abs=1e-6
    )
    box = dc.font_text_box("1.00Meg", x=100.0, y=200.0)
    assert box[2] - box[0] == pytest.approx(dc.text_width("1.00Meg"), abs=1e-6)
    assert box[3] - box[1] == pytest.approx(dc.TEXT_SIZE, abs=1e-6)


def test_text_participates_in_avoidance_and_a_keepout_can_push_it():
    """A keep-out where a value would land makes the text move (never shrink).

    A stated page is used so the drawing is anchored to the page rather than to
    its own content: the keep-out is then an absolute box the *same* drawing would
    put the value in, which is what makes the move observable.
    """
    scene = scenes()[1]
    page = (0.0, 0.0, 1200.0, 900.0)
    baseline = dc.compile(
        scene.circuit, scene.presentation, library(),
        dc.CompileBudget(page_box=page),
    )
    assert baseline.ok, render(baseline)
    value_box = text_for(baseline.candidates[0], "10k")[0].bbox
    blocked = dc.CompileBudget(page_box=page, keepouts=(value_box,))
    pushed = dc.compile(scene.circuit, scene.presentation, library(), blocked)
    assert pushed.ok, render(pushed)
    plan = pushed.candidates[0]
    assert readability.check(
        plan, scene.circuit, scene.presentation, library(),
        page_box=page, keepouts=(value_box,),
    ).hard_violations == []
    moved = text_for(plan, "10k")
    assert moved, "the value is still drawn"
    for text in moved:
        assert not _overlaps(text.bbox, value_box), (
            "the text moved out of the keep-out rather than being squeezed"
        )
        assert text.bbox[2] - text.bbox[0] == pytest.approx(
            dc.text_width(text.text), abs=1e-6
        )
    assert plan.evidence.soft_reasons, "the evidence keeps a reason per metric"


def _overlaps(left, right) -> bool:
    return (
        min(left[2], right[2]) - max(left[0], right[0]) > 1e-6
        and min(left[3], right[3]) - max(left[1], right[1]) > 1e-6
    )


def test_the_router_searches_around_an_obstacle_instead_of_through_it():
    """A wall between the two ends costs a bend and is never crossed.

    The search is exercised directly and deterministically here, on a wall the
    router is handed rather than one a compiler run happens to produce. The
    integration path — a keep-out the whole drawing has to route around and still
    pass the independent checker — is the next test; what *this* one pins is the
    search itself: a route exists, it is orthogonal, it never enters the
    obstacle, and it has a bend.
    """
    router = dc._Router(
        grid=5.0, residue=(0.0, 0.0), boxes=[(-10.0, -10.0, 10.0, 10.0)],
        bounds=(-200.0, -200.0, 200.0, 200.0),
    )
    path = router.route((-100.0, 0.0), (100.0, 0.0))
    assert path is not None, "a route exists around the box"
    assert path[0] == (-100.0, 0.0) and path[-1] == (100.0, 0.0)
    compressed = dc._compress(path)
    assert len(compressed) > 2, "the straight line is blocked, so there is a bend"
    bends = sum(
        1
        for before, corner, after in zip(compressed, compressed[1:], compressed[2:])
        if (corner[0] - before[0]) * (after[1] - before[1])
        != (corner[1] - before[1]) * (after[0] - before[0])
    )
    assert bends >= 1
    for start, end in zip(compressed, compressed[1:]):
        for point in (start, end):
            assert not _inside(point, (-10.0, -10.0, 10.0, 10.0))
        # orthogonal, and never crossing the box's interior
        assert _close_zero(start[0] - end[0]) or _close_zero(start[1] - end[1])
        assert not _segment_hits_box(start, end, (-10.0, -10.0, 10.0, 10.0))


def test_a_wire_detours_around_a_keep_out_instead_of_refusing_the_drawing():
    """A keep-out between the two ends of a promised net is gone around.

    The integration counterpart of the search above, and the drawing that used to
    be impossible to produce: while the checker measured a wire's *bounding box*
    against a keep-out, an L-shaped detour around one still reported as "inside"
    it, so the gate refused every variant and the compiler reported
    `layout-unsat` for a circuit it could perfectly well have drawn. With the
    wire measured sub-segment by sub-segment, the detour is a legal drawing.

    The keep-out is put between the two pins of the divider's promised tap net —
    the box's *bounding box* is what the old rule looked at, so the assertions
    below that every sub-segment misses it while the box covers it are exactly
    the regression.
    """
    scene = scenes()[1]
    health = best_of(scene)[1]
    lower = pin_point(health, "R2.1")
    upper = pin_point(health, "R1.2")
    assert lower is not None and upper is not None
    blocker = (lower[0] - 10.0, lower[1] + 10.0, lower[0] + 10.0, upper[1] - 10.0)
    result = dc.compile(
        scene.circuit, scene.presentation, library(),
        dc.CompileBudget(keepouts=(blocker,)),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]

    drawn = [segment for segment in plan.segments if segment.net == "TAP"]
    assert len(drawn) == 1, "the promised net is one wire, never downgraded to a name"
    points = drawn[0].points
    assert (points[0], points[-1]) in ((lower, upper), (upper, lower)), points
    for start, end in zip(points, points[1:]):
        assert not _segment_hits_box(start, end, blocker), (start, end)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    box = (min(xs), min(ys), max(xs), max(ys))
    assert _overlaps(box, blocker), (
        "the detour's bounding box still covers the keep-out, which is why the "
        f"old box rule refused this drawing: box {box}, keep-out {blocker}"
    )
    assert readability.check(
        plan, scene.circuit, scene.presentation, library(),
        keepouts=(blocker,),
    ).hard_violations == []


def _close_zero(value: float) -> bool:
    return abs(value) < 1e-9


def _segment_hits_box(start, end, box) -> bool:
    """The checker's own interior test, re-stated here so the test is independent."""
    left, bottom, right, top = (
        box[0] + 1e-6, box[1] + 1e-6, box[2] - 1e-6, box[3] - 1e-6,
    )
    if right <= left or top <= bottom:
        return False
    dx, dy = end[0] - start[0], end[1] - start[1]
    low, high = 0.0, 1.0
    for p, q in (
        (-dx, start[0] - left), (dx, right - start[0]),
        (-dy, start[1] - bottom), (dy, top - start[1]),
    ):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            if ratio > high:
                return False
            low = max(low, ratio)
        else:
            if ratio < low:
                return False
            high = min(high, ratio)
    return high - low > 1e-6


def test_no_wire_crosses_a_body_or_a_text_box_in_any_scenario():
    """053 sec.4's avoidance, checked geometrically on every plan that comes out."""
    for number, scene in sorted(scenes().items()):
        result = compile_scene(scene)
        if not result.ok:
            continue
        plan = result.candidates[0]
        obstacles = []
        for part in plan.parts:
            profile = library().get(part.symbol_ref)
            if profile is not None and profile.body is not None:
                obstacles.append(_transformed_body(profile, part))
        obstacles.extend(text.bbox for text in plan.texts)
        obstacles.extend(label.bbox for label in plan.labels)
        for segment in plan.segments:
            for start, end in zip(segment.points, segment.points[1:]):
                for box in obstacles:
                    assert not _segment_hits_box(start, end, box), (
                        f"scene {number}: {segment.net} runs through a box "
                        f"{box} between {start} and {end}"
                    )


def _transformed_body(profile, part) -> tuple[float, float, float, float]:
    from boardwise.core.geometry import transform_point

    x0, y0, x1, y1 = profile.body
    corners = [
        transform_point(
            corner[0], corner[1], rotation=part.rotation, mirror=part.mirror,
            ox=part.x, oy=part.y,
        )
        for corner in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    ]
    xs = [point[0] for point in corners]
    ys = [point[1] for point in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def _inside(point, box) -> bool:
    return (
        box[0] - 1e-6 < point[0] < box[2] + 1e-6
        and box[1] - 1e-6 < point[1] < box[3] + 1e-6
    )


def test_a_library_without_the_flag_symbols_names_the_rails_with_labels():
    """The fallback is a style, not a failure: one net, one way of naming it.

    The flag ref is derived from the net (`PWR-GND`, `PWR-<net>`), so a library
    that does not carry it is answered with labels — and `uniform-gnd` is what
    checks the drawing does not mix the two styles.
    """
    scene = scenes()[1]
    sparse = {"R0402": resistor()}
    result = dc.compile(scene.circuit, scene.presentation, sparse)
    assert result.ok, render(result)
    plan = result.candidates[0]
    assert plan.power_symbols == []
    assert {label.net for label in plan.labels} == {"VIN", "TAP", "GND"}
    checked = readability.check(
        plan, scene.circuit, scene.presentation, sparse,
    )
    assert checked.hard_violations == []
    findings = dc.check_grammar(plan, scene.circuit, scene.presentation, sparse)
    assert not [f for f in findings if f.kind == dc.KIND_RELATION_BROKEN]


def test_the_library_gap_is_a_facts_missing_refusal_with_both_repairs():
    """053 sec.2: 库符号不合适 → 换兼容符号或报告能力边界，禁止换脚号迁就版式."""
    scene = scenes()[1]
    nothing = dc.compile(scene.circuit, scene.presentation, {})
    assert nothing.candidates == []
    assert nothing.categories() == ["facts-missing"]
    (failure,) = nothing.failures
    assert "R0402" in failure.detail and "no SymbolProfile" in failure.detail
    assert "compatible symbol" in failure.action
    assert "renumbering" in failure.action, "the forbidden repair is named"

    # A library that carries the symbol is enough for the same circuit.
    assert dc.compile(scene.circuit, scene.presentation, {"R0402": resistor()}).ok


def test_a_part_with_no_profile_is_facts_missing_and_names_the_repair():
    """A grammar that binds by pin roles cannot judge a part it cannot see."""
    scene = scenes()[8]
    result = dc.compile(
        scene.circuit, scene.presentation, {"C0805": capacitor_axial()}
    )
    assert result.candidates == []
    assert "facts-missing" in result.categories()
    joined = " ".join(failure.detail for failure in result.failures)
    assert "AMS1117-3.3" in joined
    assert all(failure.action for failure in result.failures)
    actions = " ".join(failure.action for failure in result.failures)
    assert "compatible symbol" in actions or "library export" in actions


def test_a_presentation_that_names_a_part_the_circuit_does_not_have_is_refused():
    scene = scenes()[1]
    broken = divider_presentation(parts=("R1", "R9"))
    result = dc.compile(scene.circuit, broken, library())
    assert result.candidates == []
    assert result.categories() == ["facts-missing"]
    assert "R9" in result.failures[0].detail
    assert result.failures[0].action


def test_a_part_claimed_by_two_modules_is_presentation_poor():
    """053 sec.4's presentation-poor: the intent does not say which group owns it."""
    scene = scenes()[1]
    confused = presentation(
        "voltage-divider",
        modules=[module("a", ["R1"], "top arm"), module("b", ["R1", "R2"], "rest")],
    )
    result = dc.compile(scene.circuit, confused, library())
    assert result.candidates == []
    assert result.categories() == ["presentation-poor"]
    assert "R1" in result.failures[0].detail
    assert result.failures[0].action


def test_a_facts_missing_refusal_from_the_grammar_layer_passes_through_verbatim():
    """The two grammar categories travel unchanged, with the grammar's own action."""
    scene = scenes()[1]
    no_rail = circuit(
        [part("R1", "R0402", "10k"), part("R2", "R0402", "10k")],
        [
            net("VIN", "signal", ["R1.1"]),
            net("TAP", "signal", ["R1.2", "R2.1"]),
            net("GND", "signal", ["R2.2"]),
        ],
    )
    result = dc.compile(no_rail, scene.presentation, library())
    assert result.candidates == []
    assert result.categories() == ["facts-missing"]
    assert any("class 'gnd'" in failure.detail for failure in result.failures)
    assert any("nets[].class" in failure.action for failure in result.failures)
    assert result.grammar is not None and not result.grammar.ok


def test_a_keep_out_over_a_body_is_refused_rather_than_drawn_through():
    """A part cannot dodge a keep-out, so the plan is refused — never returned.

    This is the case the hard gate exists for: the parts' own geometry already
    satisfies everything the compiler checks by construction, so only the
    *independent* layer can see that a body sits inside a reserved region. A
    compiler that skipped the gate would hand this plan out (and claim an empty
    violation list in its evidence); the plan's evidence is therefore filled from
    the checker's own output rather than from an assumption.
    """
    scene = scenes()[1]
    health = best_of(scene)[1]
    upper = health.part("R1")
    profile = library()[upper.symbol_ref]
    body = _transformed_body(profile, upper)
    result = dc.compile(
        scene.circuit, scene.presentation, library(),
        dc.CompileBudget(keepouts=(body,)),
    )
    assert result.candidates == []
    assert result.categories() == ["layout-unsat"]
    assert all(failure.action for failure in result.failures)
    assert result.rejected, "the refusals keep what was tried"
    assert any(
        readability.KIND_OUT_OF_PAGE in " ".join(item.violations)
        for item in result.rejected
    ), [item.violations for item in result.rejected]


def test_an_obligated_net_that_cannot_be_wired_is_layout_unsat_never_a_label():
    """A promised net with no route inside the budget: refused, and *measured*.

    The case 053 sec.4's `layout-unsat` exists for on the routing side, built by
    trapping one end: a small keep-out is put around a pin of the net the
    `direct-wire` obligation promises, with the pin's own part left outside it.
    Every wire has to land exactly on that tip, so every route enters the
    reserved region — and the promise forbids answering with a name instead.

    What the refusal owes (053 sec.4): the category, the *measured* reason
    ("could not be joined inside the searched corridor"), the wording of a finite
    search ("not found inside the budget", never "no solution"), and an action
    that changes the answer — here the keep-out, or the obligation itself.
    """
    scene = scenes()[1]
    health = best_of(scene)[1]
    trapped_pin = pin_point(health, "R1.2")
    assert trapped_pin is not None
    trap = (
        trapped_pin[0] - 5.0, trapped_pin[1] - 5.0,
        trapped_pin[0] + 5.0, trapped_pin[1] + 5.0,
    )
    result = dc.compile(
        scene.circuit, scene.presentation, library(),
        dc.CompileBudget(keepouts=(trap,)),
    )

    assert result.candidates == []
    assert result.categories() == ["layout-unsat"]
    (failure,) = result.failures
    assert failure.subject == "TAP", failure.subject
    assert "direct-wire obligation" in failure.detail
    assert "could not be joined inside the searched corridor" in failure.detail
    assert "not found inside the budget" in failure.detail, failure.detail
    assert "move the keep-out" in failure.action
    assert "direct-wire obligation" in failure.action

    # The accounting the twelve-scene table uses: every variant the ladder built
    # is recorded as refused, each with its own reason and category, and none of
    # them claims there is no solution. This is a *thirteenth*, standalone case —
    # adding it to `scenes()` would move the table's 9 produced / 3 refused.
    assert len(result.rejected) == len(dc.CompileBudget().spacing_ladder)
    assert all(item.failure is not None for item in result.rejected)
    assert {item.failure.category for item in result.rejected} == {"layout-unsat"}
    assert all(item.reason for item in result.rejected)
    assert sorted(scenes()) == list(range(1, 13))


def test_every_candidate_carries_the_checkers_own_verdict():
    """Evidence is copied from the gate, not assumed: no violation reaches a plan."""
    for number, scene in sorted(scenes().items()):
        result = compile_scene(scene)
        for plan in result.candidates:
            assert plan.evidence.checker == readability.CHECKER_NAME
            assert plan.evidence.hard_violations == []
            assert plan.evidence.soft_metrics, number
            # The document's own derived verdict must agree.
            assert LayoutPlan.from_dict(plan.to_jsonable()).evidence.verdict == "pass"


def test_check_grammar_reports_a_binding_the_plan_does_not_place():
    """The grammar checker works from the plan: no part, no relation, one finding."""
    scene = scenes()[1]
    plan = best_of(scene)[1]
    trimmed = LayoutPlan(
        source=plan.source, target=plan.target,
        parts=[part_ for part_ in plan.parts if part_.part_id != "R2"],
        segments=[s for s in plan.segments if s.net != "TAP"],
        junctions=list(plan.junctions), labels=list(plan.labels),
        power_symbols=list(plan.power_symbols), texts=list(plan.texts),
    )
    findings = dc.check_grammar(
        trimmed, scene.circuit, scene.presentation, library()
    )
    kinds = {finding.kind for finding in findings}
    assert dc.KIND_BINDING_UNPLACED in kinds
    assert any("R2" in finding.objects[0] for finding in findings
               if finding.kind == dc.KIND_BINDING_UNPLACED)


def test_check_grammar_reports_a_broken_relation_and_a_hidden_tap():
    """A plan that moves one arm off the column, and one whose tap is unnamed."""
    scene = scenes()[1]
    plan = best_of(scene)[1]
    moved = LayoutPlan(
        source=plan.source, target=plan.target,
        parts=[
            part_ if part_.part_id != "R2" else
            type(part_)(part_id="R2", symbol_ref=part_.symbol_ref,
                        symbol_hash=part_.symbol_hash, x=part_.x + 200.0,
                        y=part_.y, rotation=0.0, mirror=False, reference="R2")
            for part_ in plan.parts
        ],
        segments=list(plan.segments), junctions=list(plan.junctions),
        labels=[label for label in plan.labels if label.net != "TAP"],
        power_symbols=list(plan.power_symbols), texts=list(plan.texts),
    )
    findings = dc.check_grammar(moved, scene.circuit, scene.presentation, library())
    kinds = {finding.kind for finding in findings}
    assert dc.KIND_RELATION_BROKEN in kinds
    assert dc.KIND_OBLIGATION_MISSING in kinds


def test_no_scenario_specific_constant_in_the_grammar_tables_or_the_compiler():
    """053 sec.6: 无逐例调坐标 — no R1/C1/10k/1.00Meg anywhere in the engine."""
    forbidden = {
        "R1", "R2", "R3", "C1", "C2", "C3", "U1", "10k", "100n", "1.00Meg",
        "AMS1117", "R123456", "scene", "scenario",
    }
    source = Path(dc.__file__).read_text(encoding="utf-8")
    for name in ("voltage_divider", "rc_lowpass", "ldo", "base"):
        module = Path(dc.__file__).parent / "grammar" / f"{name}.py"
        source += module.read_text(encoding="utf-8")
    hits = sorted(
        name for name in forbidden
        if re.search(rf'"{re.escape(name)}"', source)
    )
    assert hits == [], (
        "a scenario's own names appear in the engine; the tables must be about "
        f"roles and relations, not about one example: {hits}"
    )


def test_previews_render_and_are_valid_svg_that_names_the_plan_it_shows():
    """The offline preview: stdlib only, valid XML, and bound to the geometry."""
    scene = scenes()[4]
    plan = best_of(scene)[1]
    svg = svgpreview.render_svg(plan, library(), title="scene 4 preview")
    root = ElementTree.fromstring(svg)
    assert root.tag.endswith("svg")
    assert plan.geometry_sha256()[:12] in svg
    assert "boardwise-plan-preview" in svg
    # The picture names what it draws: the parts' references and the tap labels,
    # which is what a reviewer reads it for.
    for text in ("R1", "R2", "C1", "TAP1", "TAP2"):
        assert text in svg, text


def test_preview_writer_puts_the_file_where_it_says(tmp_path):
    scene = scenes()[8]
    plan = best_of(scene)[1]
    target = svgpreview.write_preview(
        tmp_path / "053b_scene08_cand1.svg", plan, library(), title="scene 8",
    )
    assert target.exists() and target.read_text(encoding="utf-8").startswith("<svg")


def test_the_compiler_imports_nothing_above_its_layer():
    """engines may use core and the standard library — never connector or cli."""
    source = Path(dc.__file__).read_text(encoding="utf-8")
    imported = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", source, re.M))
    forbidden = {
        name for name in imported
        if name.startswith(("boardwise.cli", "boardwise.connectors", "boardwise.rules",
                            "boardwise.bridge", "boardwise.parsers"))
    }
    assert forbidden == set(), forbidden
