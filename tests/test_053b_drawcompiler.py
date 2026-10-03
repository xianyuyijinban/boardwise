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

import ast
import inspect
import math
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


def ams1117_duplicate_vout_flipped(ref: str = "AMS1117-3.3-C6186-M") -> SymbolProfile:
    """The measured AMS1117 turned round: its single-sided pins on the **right**.

    Same shape, same duplicate VOUT, mirrored in x — nothing about this regulator
    is written into the rule 065 sec.1 adds, so the answer has to come out
    mirrored too (the output branch on the *left* pad). The body box is symmetric
    in x, so only the tips and the escape directions move.
    """
    base = ams1117_duplicate_vout(ref)
    across = {"left": "right", "right": "left", "up": "down", "down": "up"}
    return SymbolProfile(
        symbol_ref=ref, title=f"{base.title} (flipped in x)", body=base.body,
        pins=[
            SymbolPin(
                number=pin.number, name=pin.name,
                tip=(-pin.tip[0], pin.tip[1]),
                direction=across.get(pin.direction, pin.direction),
                direction_source=pin.direction_source,
                electrical_role=pin.electrical_role, role_source=pin.role_source,
            )
            for pin in base.pins
        ],
    )


def regulator_two_vout_one_side(
    ref: str = "LDO-2VOUT-ONE-SIDE",
) -> SymbolProfile:
    """A regulator whose VOUT is carried on two pads leaving the **same** side.

    The counterpart of the measured AMS1117 for 069: here the two pads the symbol
    duplicates are neighbours on one side, so nothing separates them and 060
    sec.2's short jumper is the whole story (岳's rule is about pads that are
    "相隔较远"). Built from the plain three-pin regulator so the *only* difference
    to the symbols the other tests use is where the second VOUT pad sits.
    """
    base = regulator(ref)
    return SymbolProfile(
        symbol_ref=ref, title=f"{ref} (two pads, one side)", body=base.body,
        pins=[
            *base.pins,
            SymbolPin(number="4", tip=(60.0, -20.0), name="VOUT", direction="right",
                      electrical_role="VOUT", role_source="pin-name"),
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
        "LDO-2VOUT-ONE-SIDE": regulator_two_vout_one_side(),
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


def pin_point(
    plan: LayoutPlan, member: str, book: dict | None = None
) -> tuple[float, float] | None:
    """Where the plan puts a spec pin, through the profile and the plan's pose.

    ``book`` names which library to read the symbol from, for the tests that
    compile against a symbol the default book does not carry (065's flipped
    regulator); the default is the module's own book.
    """
    part_id, _, token = member.partition(".")
    placed = plan.part(part_id)
    if placed is None:
        return None
    profile = (book or library()).get(placed.symbol_ref)
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


def test_a_flag_stands_upright_and_its_glyph_hangs_away_from_the_pin():
    """069 sec.7 + 060 sec.3 + 064: 旗标只许竖直，字形仍朝外、仍按家分。

    岳 read the landed P23 page and refused a flag lying on its side
    (「旗标一定要竖直摆放不能平放影响观感」): his own AMS1117 has every
    ``Power-VCC`` at 0 and every ground at 0 or 180, because every flag there is
    reached by a vertical run. So the compass 053B/064 shared is retired —
    ``flag_rotation`` answers **0 or 180** for every direction — while the truth
    behind it is kept: the glyph hangs *away* from the pin it names (060 sec.3),
    and it does so **per family**, because ``Ground-GND`` carries
    ``BBOX (-10, 0, 10, -19)`` — bars *below* the connection — and ``Power-*`` a
    bar *above* it (064's live probe).

    Two things are checked per direction, and neither implies the other: the
    number is one of the two upright ones, and the box the drawing reserves for
    that number hangs on the far side of the anchor (straight up or down, never
    sideways). A vertical lead hangs the glyph further out along itself; a
    horizontal one — which the page layer passes for a port on a vertical module
    boundary, the compiler having bent its own — hangs it the family's natural
    way, a rail up and a ground down.
    """
    for ref, kind in (("PWR-GND", "gnd"), ("PWR-VIN", "rail")):
        profile = flag(ref)
        assert symbolprofile.flag_glyph_kind(profile) == kind, ref
        for direction in ((0.0, 1.0), (0.0, -1.0), (-1.0, 0.0), (1.0, 0.0)):
            rotation = dc.flag_rotation(direction, kind)
            assert rotation in (0.0, 180.0), (
                f"a {kind} flag escaping {direction} is asked for rotation "
                f"{rotation} — 069 sec.7 draws flags upright and nothing else"
            )
            box = flag_glyph_box(profile, rotation=rotation, anchor=(0.0, 0.0))
            assert box is not None
            centre = ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
            assert abs(centre[0]) < 1e-6, (
                f"the {kind} glyph box {box} is not centred on its anchor's column: "
                f"an upright flag hangs straight up or straight down of the point "
                "it names"
            )
            hang = (
                direction[1] if direction[1] != 0.0
                else (1.0 if kind == "rail" else -1.0)
            )
            assert centre[1] * hang > 0.0, (
                f"the {kind} glyph box {box} hangs on the same side of the anchor as "
                f"the pin it names (escaping {direction}) — 060 sec.3's whole point, "
                "and 064's per-family half of it"
            )


def test_the_two_flag_families_are_exactly_half_a_turn_apart():
    """064: one number per family, 180 apart — the compass cannot be uniform.

    ``Ground-*``'s bars hang below its connection and ``Power-*``'s bar sits
    above it, so for the same *vertical* escape the two families want rotations
    that differ by exactly half a turn. Stated as its own test because the whole
    of 060's bug was one compass answering for both, and a later "simplification"
    that folds the two tables back together would have to break this line first.

    Only vertical escapes are listed (069 sec.7): a horizontal one is bent into a
    vertical before it reaches this function, and the page layer, which passes one
    for a vertical module boundary, gets each family's own natural hang — the same
    number for both, which is the *boxes* telling them apart and not the digits.
    """
    for direction in ((0.0, 1.0), (0.0, -1.0)):
        ground = dc.flag_rotation(direction, "gnd")
        rail = dc.flag_rotation(direction, "rail")
        assert (ground - rail) % 360.0 == 180.0, (direction, ground, rail)
    for direction in ((-1.0, 0.0), (1.0, 0.0)):
        ground = dc.flag_rotation(direction, "gnd")
        rail = dc.flag_rotation(direction, "rail")
        assert ground in (0.0, 180.0) and rail in (0.0, 180.0), (direction, ground, rail)
        assert ground == 0.0 and rail == 0.0, (
            "a horizontal escape is answered with the family's natural hang — a "
            "ground's bars below, a rail's bar above — which is the same number for "
            "both families because their glyphs are mirror images"
        )


def test_the_flag_family_is_read_off_the_symbols_own_name():
    """064 sec.1: ``flag_glyph_kind`` — the one place a flag's family is decided.

    The glyph box cannot answer it. Every library this repo ships states the same
    *convention* box ``(-6, 0, 6, 18)`` for a ground and a rail flag, so offline
    the name is all that is left — and the names are the measured ones: the
    editor's own library titles its flags ``Ground-GND`` / ``Power-VCC`` /
    ``Power-5V`` (family prefix, then the net), and this repo's books spell the
    pair ``PWR-GND`` / ``PWR-<net>``. Both spellings are judged by
    ``core.model.is_ground_net``, the one place a name is called ground.
    """
    for ref, kind in (
        ("PWR-GND", "gnd"),
        ("PWR-GNDA", "gnd"),
        ("PWR-VSS", "gnd"),
        ("Ground-GND", "gnd"),
        ("GND", "gnd"),
        ("PWR-VIN", "rail"),
        ("PWR-3V3", "rail"),
        ("PWR-5V0", "rail"),
        ("Power-VCC", "rail"),
        ("Power-5V", "rail"),
    ):
        assert symbolprofile.flag_glyph_kind(flag(ref)) == kind, ref
    # A profile that carries only a title is judged the same way (a parsed symbol
    # may reach the book without a ref), and a name that is no ground name is a
    # rail — the flag the editor's own library draws with a bar above it.
    titled = SymbolProfile(
        symbol_ref="", title="Power-SENSE", body=(-6.0, 0.0, 6.0, 18.0),
    )
    assert symbolprofile.flag_glyph_kind(titled) == "rail"


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


def test_a_rail_flag_below_its_pin_is_drawn_hanging_the_other_way():
    """064: the same scenario's rail flag, which 060 had turned upside down.

    The divider's ``VIN`` flag leaves its pin **upwards**, so its glyph has to
    hang upwards too — and the rail family's natural pose makes that rotation
    ``0`` (053B's mapping), while 060 handed the editor ``180``: 060 sec.3's
    uniform flip was read off the ground family alone (its ``BBOX`` hangs the
    other way) and the E1 page that verified it carries GND flags only.

    The box is asserted beside the number on purpose: it must stay *above* the
    anchor exactly as it did under 060 (the reservations did not move — only the
    number handed to the editor did), which is what makes this batch's scenario
    declaration a rotation-only change.
    """
    scene = scenes()[1]
    result, plan = best_of(scene)
    assert result.ok
    rails = [item for item in plan.power_symbols if item.net == "VIN"]
    assert rails, "the ladder's rail is named by a flag"
    book = library()
    for symbol in rails:
        assert symbol.rotation == 0.0, (
            f"a rail flag anchored above its pin is drawn at 0 (the Power-* family's "
            f"own pose), not {symbol.rotation} — 060's uniform 180 turned every rail "
            "flag upside down (064 sec.2)"
        )
        box = flag_glyph_box(
            book[symbol.symbol_ref], rotation=symbol.rotation,
            anchor=(symbol.x, symbol.y),
        )
        assert box is not None
        assert box[1] >= symbol.y - 1e-6, (
            f"the glyph box {box} starts above the anchor row {symbol.y}: a rail flag "
            "above its pin hangs its bar upwards (064)"
        )
        assert box[3] > symbol.y, "the box occupies the rows over the anchor"


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


def test_an_output_branch_hangs_on_the_pad_across_the_body_from_the_input():
    """065 sec.1: 分侧的参照物是**脚**——输出电容挂与输入脚异侧的那只 VOUT 脚。

    The measured AMS1117 carries VOUT twice, one pad down each side, and 060
    hung the output branch on the first pin by id — the left-hand one, the same
    side 060 had just sent the input capacitor to. On the E1 render that put both
    capacitors under the core's left edge (岳: "C1 放左边、C2 放右边，不行吗？
    这样看着真的好怪，也好挤呀"). The output branch now hangs on the *pad across the
    body* from the pin the input branch hangs on, so the input capacitor leaves
    on the input side and the output capacitor on the other one.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    core = plan.part("U1")
    near, far = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    in_tip, out_tip = pin_point(plan, "C1.1"), pin_point(plan, "C2.1")
    assert core is not None
    assert None not in (near, far, in_tip, out_tip)
    # The premises this test is about: the two VOUT pads are on opposite sides of
    # the body, and the input capacitor hangs off the left-hand VIN pin.
    assert near[0] < core.x < far[0], (near, far, core.x)
    assert in_tip[0] < core.x, (in_tip, core.x)
    # 065: the output branch hangs below the *far* pad (the module asks for the
    # output side "bottom"), not below the near one — and the two capacitors
    # therefore leave the core on opposite sides. Both halves are asserted: a
    # branch that merely drifted to another lane would pass a side test alone.
    assert out_tip[0] == far[0] and out_tip[1] < far[1], (
        f"the output capacitor hangs below the far VOUT pad at {far} (065 sec.1), "
        f"not at {out_tip}"
    )
    assert out_tip[0] > core.x > in_tip[0], (
        f"input capacitor left ({in_tip[0]:g}), output capacitor right "
        f"({out_tip[0]:g}) of the core at {core.x:g}"
    )
    # 060 sec.2's shorting duty survives the move: the pad the branch no longer
    # hangs on is still on the net, and every pin of both capacitors is wired. A
    # pad whose own corner has no room left for a flag by 069 sec.8 carries one on
    # its tip instead — which is a conductor, so the pin is connected either way.
    for member in ("U1.2", "U1.4", "C1.1", "C2.1"):
        tip = pin_point(plan, member)
        assert on_a_wire(plan, tip) or _flag_on(plan, tip), member
    assert readability.check(
        plan, spec, presentation, library(), page_box=page,
    ).hard_violations == []


def test_the_pad_across_the_body_follows_the_symbol_not_a_constant_side():
    """065 sec.1 reads the input *pin*, so turning the symbol round turns the answer.

    The same measured AMS1117 with its single-sided pins mirrored into the right
    half: VIN is now the right-hand pin, and the pad across the body from it is
    the **left** VOUT. An implementation that simply preferred one side (the
    right-hand pad, the higher pin id) would put both capacitors on one side
    again — this is the case that tells the two rules apart.

    074 changed one thing about this drawing: on the default spacing ladder (1x,
    1.5x, 2.2x) the pad across the body has no side left to hang its own flag on
    that no other net crosses — the rail runs at y=745 ten units above the pad row
    and the VIN and GND pins seal the other three sides, so the ladder is exhausted
    and the compiler refuses the shape by name instead of drawing the lead that
    used to cut the rail (see
    :func:`test_a_pad_whose_every_side_is_sealed_is_layout_unsat_and_names_the_conductor`).
    One rung more room (3.5x as well as 2.2x) and the same circuit draws with no
    crossing at all, which is the drawing this test is about: 074 refuses a
    defective picture, never the circuit.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    ref = "AMS1117-3.3-C6186-M"
    book = library(**{ref: ams1117_duplicate_vout_flipped(ref)})
    spec = circuit(
        [part("U1", ref, "AMS1117-3.3"), part("C1", "C0805", "10u"),
         part("C2", "C0805", "22u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "U1.4", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )
    presentation = ldo_presentation(
        sidePreferences={"input": "right", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(
        spec, presentation, book,
        dc.CompileBudget(page_box=page, spacing_ladder=(2.2, 3.5)),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    core = plan.part("U1")
    in_pin = pin_point(plan, "U1.3", book)
    pads = [pin_point(plan, "U1.2", book), pin_point(plan, "U1.4", book)]
    in_tip, out_tip = pin_point(plan, "C1.1", book), pin_point(plan, "C2.1", book)
    assert core is not None
    assert None not in (*pads, in_pin, in_tip, out_tip)
    # "Across the body" is read off the drawing: the VOUT pad on the far side of
    # the core from the input pin (065 sec.1's own question, as an axis test).
    across = [
        pad for pad in pads if (pad[0] - core.x) * (in_pin[0] - core.x) < 0
    ]
    assert len(across) == 1, (
        f"the mirrored symbol puts exactly one VOUT pad on the far side of the body "
        f"from VIN: pads {pads} against the input pin at {in_pin}"
    )
    far = across[0]
    near = [pad for pad in pads if pad != far][0]
    assert far[0] < core.x < in_pin[0], (far, core.x, in_pin)
    assert out_tip[0] == far[0], (
        f"the output capacitor hangs below the pad across the body at {far}, not "
        f"at {out_tip} — the reference is the input pin, wherever the symbol puts it"
    )
    assert in_tip[0] > core.x > out_tip[0], (
        f"the mirrored symbol mirrors the drawing: input at {in_tip[0]:g}, output "
        f"at {out_tip[0]:g}, core at {core.x:g}"
    )


def test_a_pad_whose_every_side_is_sealed_is_layout_unsat_and_names_the_conductor():
    """074 sec.3/4 的编译级实例：梯子穷尽 → layout-unsat，报实测原因与建议动作.

    The mirrored AMS1117 is the offline shape where 074's ladder really is
    exhausted: the rail runs ten units above the pad row, and the VIN pin, the
    GND pin and the core's own body seal the other three sides, so on the
    **roomier 2.2 ladder** every lead that pad's flag could hang on cuts the rail
    or lands on a conductor. 岳 read that drawing and refused the form (「第一眼
    以为5V和3V3的旗标短接在一块了」), so the compiler has one honest answer left —
    and it must *say* it: which run, which conductor, where they met, and what to
    move. A silent "no candidate" would send the caller looking for a bug in the
    compiler, and a junction welded on to make the crossing look intended would
    join two nets the spec keeps apart.

    **097 corrected one thing this test used to claim by accident.** It said the
    failure was the *default* ladder's, and asserted `not result.ok` on the
    strength of it. Measured (`evidence/097/sealed_pad_probe.py`): the two narrow
    variants were never refused by 074 at all — they were refused by `_overflow`,
    because the anchor's estimate counted only net names (`stub + widest net +
    TEXT_GAP` = 64.5) while U1's own `AMS1117-3.3` printed on U1's left reaches
    76.5 past the drawing's left edge, which put the drawing 9.5 units outside the
    margin. 097 measures the text too (see `tests/test_097_annotation_allowance.py`),
    so those two variants are now drawn — with 岳's own bent lead, right along the
    pad row and then down, which crosses nothing — and 074's refusal is what is
    left on the ladder it was written for. Both halves are pinned here: the
    crossing refusal and its wording, and the fact that the refusal is now the
    ladder's and not a sheet-margin artefact.

    The same circuit draws cleanly on a roomier ladder too (see
    :func:`test_the_pad_across_the_body_follows_the_symbol_not_a_constant_side`):
    this is 074 refusing a defective picture, never the circuit.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    ref = "AMS1117-3.3-C6186-M"
    book = library(**{ref: ams1117_duplicate_vout_flipped(ref)})
    spec = circuit(
        [part("U1", ref, "AMS1117-3.3"), part("C1", "C0805", "10u"),
         part("C2", "C0805", "22u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "U1.4", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )
    presentation = ldo_presentation(
        sidePreferences={"input": "right", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, book, dc.CompileBudget(page_box=page))
    assert result.ok, (
        "the default ladder used to refuse this shape only because the anchor's "
        "estimate pushed it 9.5 units outside the margin (097): with the estimate "
        f"measuring the text, nothing should refuse it — {render(result)}"
    )
    assert {
        item.failure.category for item in result.rejected if item.failure is not None
    } == {dc.FAILURE_LAYOUT_UNSAT}, [
        (item.variant, item.reason) for item in result.rejected
    ]
    measured = [
        item.failure for item in result.rejected
        if item.failure is not None
        and item.failure.category == dc.FAILURE_LAYOUT_UNSAT
        and "crosses net" in item.failure.detail
    ]
    assert measured, (
        "no variant says which conductor the pad's lead would have crossed: "
        f"{[(item.variant, item.reason) for item in result.rejected]}"
    )
    failure = measured[0]
    assert "U1.2 is named by a flag of its own" in failure.detail or (
        "U1.4 is named by a flag of its own" in failure.detail
    ), f"the refusal does not name the pad: {failure.detail}"
    assert " at (" in failure.detail, failure.detail
    assert failure.action and "junction" in failure.action, failure.action


def test_a_single_sided_role_and_an_nc_pad_keep_060s_own_pin():
    """065 sec.1's floor: 单侧符号零变化，`nc[]` 仍把那只脚撤出候选。

    Two shapes where nothing may move. A role whose pins are all on one side has
    no pad to cross to — the branch hangs on the only pin there is, as 060 left
    it. And a duplicate pad the spec lists in ``nc[]`` is not a candidate at all:
    it was withdrawn by the spec, and moving the branch onto a pad the engineer
    marked no-connect would undo 060 sec.2's exception rather than apply 065.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    # (a) the plain three-pin regulator: one VOUT pin, on the right.
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    core = plan.part("U1")
    vout, out_tip = pin_point(plan, "U1.2"), pin_point(plan, "C2.1")
    assert core is not None and vout is not None and out_tip is not None
    assert out_tip[1] == vout[1] and out_tip[0] > vout[0], (
        f"the output branch leaves its own pin at {vout} on that pin's row, as it "
        f"did before 065 — it reads {out_tip} (060 sec.1, unchanged)"
    )

    # (b) the duplicate pad written into nc[] stays withdrawn.
    spec = _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    near, far = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    out_tip = pin_point(plan, "C2.1")
    assert None not in (near, far, out_tip)
    assert out_tip[0] == near[0] and out_tip[1] < near[1], (
        f"the output capacitor stays under the pad the spec wired at {near}, not "
        f"under the nc[] pad at {far} (its rail pin reads {out_tip})"
    )
    assert not on_a_wire(plan, far), "an explicit nc[] is still a no-connect"
    assert on_a_wire(plan, near)


def test_a_roles_other_pins_are_wired_as_one_node_and_nc_is_the_exception():
    """060 sec.2: 重复脚默认都接上，`nc[]` 是显式例外（岳裁决 a 方案）.

    A role's several pins are one node inside the symbol, so bringing one of them
    onto a net brings the role: the picture must show the pad connected, not an
    empty pin beside a connected one (059's 岳: "有一个 VOUT 空悬（负责散热的大引脚）").
    The spec does not have to spell the duplicate out; listing it in ``nc[]`` still
    keeps it off, because that is a stated decision rather than an omission.

    069 sec.2 changed the *form* this duty is drawn in and not the duty: on the
    measured AMS1117 the duplicate pad sits across the body, so it is now brought
    out on its own stub to its own flag rather than joined by a run over the part.
    What is asserted here is therefore "connected", which both forms satisfy.
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


def _runs_through(segment, point) -> bool:
    """Does this one wire run pass through the point?"""
    return any(
        _on_segment(point, start, end)
        for start, end in zip(segment.points, segment.points[1:])
    )


def _joined_by_a_wire(plan: LayoutPlan, first, second) -> bool:
    """Is there **one** wire run carrying both points? (069's question exactly.)"""
    return any(
        _runs_through(segment, first) and _runs_through(segment, second)
        for segment in plan.segments
    )


def _flag_on(plan: LayoutPlan, point) -> bool:
    """Does a flag stand exactly on this point?

    069 sec.8's last resort: a flag whose whole box has nowhere clear to go (a
    crowded corner of the module) stands on its own pin, whose tip is a conductor —
    the pin is then connected by the flag itself, with no stub.
    """
    return any(
        abs(symbol.x - point[0]) < 1e-6 and abs(symbol.y - point[1]) < 1e-6
        for symbol in plan.power_symbols
    )


def _ldo_pair_circuit(*, out_members: list[str]) -> CircuitSpec:
    """The measured AMS1117 with a **single** input capacitor and no output one.

    One part per net keeps 069's question on the pads themselves: with nothing
    else on the output rail, "which pad keeps the wire" has no second answer.
    """
    return circuit(
        [part("U1", "AMS1117-3.3-C6186", "AMS1117-3.3"), part("C1", "C0805", "10u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", out_members),
            net("GND", "gnd", ["U1.1", "C1.2"]),
        ],
    )


def test_pads_a_body_separates_are_named_by_their_own_flags_and_not_wired():
    """069 sec.2： 相隔较远的两根同属性脚不连实体线，各引短线打同名旗标。

    岳's hand drawing of U1 is the ground truth: his AMS1117 carries VOUT on both
    sides, and each of those pads leaves the body on its **own** short stub into
    its own rail flag — there is no wire over the part joining them (his P22:
    pin 2 out to the left flag, pin 4's own short rail on the right). The net is
    joined by *name*, which is 060 sec.2's electrical obligation kept in the form
    an engineer actually draws.

    The hard claims: no single wire run touches both pads; each pad has one flag
    of the same net at the end of its own stub, inside 岳's 40-60 range (never
    further); the pads are still one node in the checker's own derivation; and the
    grammar's `direct-wire` promise is not reported as broken by this form.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _ldo_pair_circuit(out_members=["U1.2", "U1.4"])
    presentation = ldo_presentation(parts=("U1", "C1"))
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]

    near, far = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    assert near is not None and far is not None
    assert not _joined_by_a_wire(plan, near, far), (
        f"the two VOUT pads at {near} and {far} are joined by a wire run — 069 "
        f"forbids the run; segments read {[s.points for s in plan.segments]}"
    )

    flags = [symbol for symbol in plan.power_symbols if symbol.net == "3V3"]
    assert len(flags) == 2, (
        f"one same-named flag per pad is what joins this net by name; the plan "
        f"carries {[(s.net, s.x, s.y) for s in plan.power_symbols]}"
    )
    assert {symbol.symbol_ref for symbol in flags} == {"PWR-3V3"}
    for member, tip in (("U1.2", near), ("U1.4", far)):
        mine = [
            symbol for symbol in flags
            if _joined_by_a_wire(plan, tip, (symbol.x, symbol.y))
        ]
        assert len(mine) == 1, (
            f"{member} at {tip} must reach exactly one of the two flags of its own "
            f"net; the plan gives it {[(s.x, s.y) for s in mine]}"
        )
        reach = math.hypot(mine[0].x - tip[0], mine[0].y - tip[1])
        assert 10.0 <= reach <= 60.0, (
            f"{member}'s flag is {reach:g} units away — 岳's stub is a short lead "
            "(40-60), never a long run"
        )

    derived = readability.derive_netlist(plan, library())
    assert derived.group_of("U1.2") == derived.group_of("U1.4") == ("U1.2", "U1.4"), (
        "the two pads are one node in the spec and have to be one node in the "
        f"drawing — the checker reads {derived.groups}"
    )
    checked = readability.check(plan, spec, presentation, library(), page_box=page)
    assert checked.hard_violations == [], [v.render() for v in checked.hard_violations]
    assert not [
        finding for finding in plan.evidence.grammar_findings
        if "3V3" in finding
    ], plan.evidence.grammar_findings


def test_a_far_pad_is_named_where_it_stands_and_the_rest_keeps_its_wire():
    """069 sec.2 on the E1 shape: 只有离得远的那只脚改旗标，其余照旧接线。

    The measured AMS1117 with its output capacitor on the far pad (065 sec.1 hangs
    it across from the input pin). Here the net *does* have another member, so one
    pad keeps the wire (the one the capacitor already hangs off) and the pad
    across the body is named at its own stub. The claim that matters for the
    picture is the one 岳 sent the batch back for: the run over the top of the
    part is gone — no wire touches both pads — while the capacitor's branch and
    the net's identity are exactly what they were.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    core = plan.part("U1")
    near, far = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    out_tip = pin_point(plan, "C2.1")
    assert core is not None and None not in (near, far, out_tip)
    assert near[0] < core.x < far[0], (near, far, core.x)

    assert not _joined_by_a_wire(plan, near, far), (
        f"pin 2 at {near} and pin 4 at {far} are still joined by a run over the "
        f"part (069 sec.2 forbids it): {[s.points for s in plan.segments]}"
    )
    # The pad the output capacitor hangs off keeps its wiring, both to the
    # capacitor and to the net's own name.
    assert _joined_by_a_wire(plan, far, out_tip), (
        f"the capacitor at {out_tip} must stay wired to the pad it hangs on ({far})"
    )
    flags = [symbol for symbol in plan.power_symbols if symbol.net == "3V3"]
    named = {
        member for member, tip in (("U1.2", near), ("U1.4", far))
        if any(_joined_by_a_wire(plan, tip, (s.x, s.y)) for s in flags)
        or _flag_on(plan, tip)
    }
    assert named == {"U1.2", "U1.4"}, (
        "both islands of this net state its name — the far pad on its own stub (or, "
        "when nothing clear is left around it, on its own tip: 069 sec.8's last "
        f"resort) and the wired cluster at the pad that kept the wire; named={named}"
    )
    derived = readability.derive_netlist(plan, library())
    assert len(set(derived.group_of(pin) for pin in ("U1.2", "U1.4", "C2.1"))) == 1, (
        f"3V3 is one node in the spec: {derived.groups}"
    )
    assert readability.check(
        plan, spec, presentation, library(), page_box=page,
    ).hard_violations == []


def test_a_far_pads_flag_stands_a_stub_clear_of_the_rails_own_flag():
    """069 sec.10 的旗标半边：远侧脚的旗必须与输入轨的旗明显分家，不是同一列的两个字形。

    岳 on the landed v4 page: 「不行，现在第一眼以为5V和3V3的旗标短接在一块了，这个
    必须改」. The two glyphs that read as one were the far pad's 3V3 and the input
    rail's own VIN5, stacked on the same column — the pad's own gate was only ten
    units above its twin. The claim was horizontal in that drawing and it is a
    *measured gap*: the rail's flag hangs straight off its pin, so the whole
    separation was the far pad's stub running a full :data:`SIBLING_LEAD` away.

    074 keeps the claim and changes the direction it is met in. The stub that used
    to carry the flag **up** (a whole sibling lead sideways, then a turn over the
    rail) cut the rail on the way — the very form 岳 rejected — so the ladder
    refuses that turn, and on this pad's own side of the rail the only clear place
    for a whole flag box (glyph + the name the host prints + 069 sec.8's clearance)
    is 30 units out and 25 **down**, away from the rail. So what is asserted here is
    what 岳 actually asked for: the pad's flag hangs on the rail-free side of the
    rail, and two whole flag boxes do not touch. Measured cause of the shorter
    stub: the 50-unit rungs are refused by the gate (the turn crosses the rail at
    (135, 740)) and by 069 sec.8's box (hanging down at (135, 705) collides with
    C1's own annotation text at x≤133) — 069's ladder then lands on
    :data:`FLAG_LEAD`.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    book = library()

    far = pin_point(plan, "U1.2")
    assert far is not None, "premise: the pad across the body has a tip"
    rail_y = pin_point(plan, "U1.3")[1]
    on_the_rail = [symbol for symbol in plan.power_symbols if symbol.net == "VIN5"]
    assert len(on_the_rail) == 1, (
        "the input rail states itself with one flag at the pin it supplies "
        f"(069 sec.7): {[(s.net, s.x, s.y) for s in plan.power_symbols]}"
    )
    rail_flag = on_the_rail[0]
    mine = [
        symbol for symbol in plan.power_symbols
        if symbol.net == "3V3" and _joined_by_a_wire(plan, far, (symbol.x, symbol.y))
    ]
    assert len(mine) == 1, (
        f"the far pad at {far} reaches exactly one 3V3 flag of its own; "
        f"the plan gives it {[(s.x, s.y) for s in mine]}"
    )
    flag = mine[0]

    assert (flag.y > rail_y) == (far[1] > rail_y), (
        f"the far pad's flag at ({flag.x:g}, {flag.y:g}) came out on the other side "
        f"of the input rail (y={rail_y:g}) from the pad it names at {far} — the run "
        "that reaches it would have to cross the rail to get there (074 sec.3)"
    )
    assert _lead_crossings(plan) == [], (
        "the pad's own run cuts another net's wire: " + "; ".join(_lead_crossings(plan))
    )

    far_box = dc._flag_box(book[flag.symbol_ref], flag.rotation, (flag.x, flag.y), flag.net)
    rail_box = dc._flag_box(
        book[rail_flag.symbol_ref], rail_flag.rotation, (rail_flag.x, rail_flag.y),
        rail_flag.net,
    )
    assert (
        far_box[2] < rail_box[0] or rail_box[2] < far_box[0]
        or far_box[3] < rail_box[1] or rail_box[3] < far_box[1]
    ), (
        f"the far pad's flag box {far_box} and the rail's {rail_box} overlap — two "
        "whole flag boxes (glyph + name + clearance) are what 岳 reads as one symbol"
    )


def test_a_free_pad_takes_the_near_stub_and_its_capacitor_hugs_the_pad():
    """069 sec.11：近位空着时旗就落最近的净档上，输出电容贴回那只脚 15–25。

    岳 after the v4 render: 「右侧的旗标和电容离器件太远了贴近一点」. The avoidance
    ladder had walked the far pad's flag out to the fourth rung and stretched the
    capacitor's own drop to a full lane while the near slots were empty — the ladder
    is 就近优先, and it may only walk away when the near slot is *taken*.

    The numbers are his own, measured off P22: the far pad's stub is his 40–60 band
    where that band fits, and never the ladder's 60/120 rungs; the flag at its end is
    no more than 60 from the pad it names; the output capacitor hangs 15–25 off the
    pad it decouples; and every flag stays upright (069 sec.7).

    **082 restored the band's floor to 40 on this shape** by giving a far pad's own
    ladder the low end of 069 sec.1's 40–60 band as a second rung
    (:func:`~boardwise.engines.drawcompiler._flag_pins`), where 074 had dropped it to
    :data:`FLAG_LEAD` (30). The geometry is measured, not chosen, and the reason the
    50 could not simply be reached is still the two refusals 074 recorded: the upward
    turn crosses the input rail at (135, 740), which 074 refuses by name, and a whole
    25-unit jog down at (135, 705) lands on C1's own annotation (which reaches x=133).
    **The 40 rung is refused by neither, because its turn is half a jog (12.5) down**:
    measured anchor (145, 717.5) for a pad at (185, 730) — horizontal reach 40,
    straight 41.9 — with the other five flags on the page unmoved and all
    twenty-four offline scenarios byte-identical. The 50 stays the first rung, so the
    page-level E1 landing keeps 岳's 50 (see the v6 render), and a shape with no room
    at 40 still lands on the nearer 30.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]

    far, near = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    cap = pin_point(plan, "C2.1")
    assert None not in (far, near, cap), (far, near, cap)

    stub = [
        symbol for symbol in plan.power_symbols
        if symbol.net == "3V3" and _joined_by_a_wire(plan, far, (symbol.x, symbol.y))
    ]
    assert len(stub) == 1, f"the far pad is named on its own stub; got {stub}"
    reach = abs(stub[0].x - far[0])
    assert 40.0 - 1e-6 <= reach <= 60.0, (
        f"the far pad's flag is {reach:g} horizontal units out — 岳's 40-60 band, and "
        f"082 measured 40 exactly (the half-jog turn at (145, 717.5)); the near slots "
        f"are what the ladder must take first (nothing between {far} and it), and "
        "069's own rungs stop at 60/120 only when everything nearer is taken"
    )
    straight = math.hypot(stub[0].x - far[0], stub[0].y - far[1])
    assert straight <= 60.0, (
        f"the far pad's flag stands {straight:g} units off the pad it names — 069 "
        "sec.11 keeps a flagged pad within reach of it (≤60)"
    )

    # The rail's own flag at the pad that kept the wire: near, and never beyond 60.
    kept = pin_point(plan, "U1.4")
    assert _joined_by_a_wire(plan, kept, cap), (
        f"the capacitor at {cap} must stay wired to the pad it decouples ({kept})"
    )
    hang = math.dist(cap, kept)
    assert 15.0 <= hang <= 25.0, (
        f"the output capacitor's pin is {hang:g} units from the pad it decouples — "
        "岳's own AMS1117 hangs it 15-25 down the short rail (069 sec.11), and 60 was "
        "what the ladder stretched it to before"
    )
    for symbol in plan.power_symbols:
        off = math.hypot(symbol.x - kept[0], symbol.y - kept[1])
        if symbol.net != "3V3":
            continue
        assert off <= 60.0 or (symbol.x, symbol.y) == (stub[0].x, stub[0].y), (
            f"a flagged pad is {off:g} units from its own pin — 069 sec.11's ceiling "
            "is 60, and only the far pad's own stub may be the one that reaches"
        )

    assert {symbol.rotation for symbol in plan.power_symbols} <= {0.0, 180.0}, (
        "069 sec.7: every flag stands upright — "
        f"{[(s.net, s.rotation) for s in plan.power_symbols]}"
    )


def test_a_parts_own_annotation_does_not_push_its_flag_away():
    """069 sec.11 的另一半：器件自己的位号/值文字不是旗标的障碍物。

    The second thing that had walked the flags out on the v4 page was the flag *box*
    itself: it was held a whole clearance (:data:`dc.FLAG_CLEARANCE`) away from every
    solid, and a part's annotation — the reference and value text the host prints
    beside the symbol — counted as one. A rail's flag that merely grazed that text was
    therefore pushed to a farther rung of the ladder. The annotation is not a
    conductor: 069 sec.8's 「不许贴上」 is about the drawing's conductors (another net's
    wire, a foreign pin tip), and all that is wrong at a text box is a true overlap
    (``_check_text`` is text-on-text).

    Measured on 053b's own LDO scene (the same call the 064 audit makes): the rail's
    flag takes 岳's short run — his own are 20 and 30 — and the annotation beside it
    does not move it out to the ladder's 60.
    """
    scene = scenes()[8]
    plan = compile_scene(scene).best()
    assert plan is not None, "premise: 053b scene 8 draws"
    rail = [symbol for symbol in plan.power_symbols if symbol.net == "VIN5"]
    assert len(rail) == 1, (
        f"the input rail carries one flag (069 sec.7): {plan.power_symbols}"
    )
    lead = _flag_lead(plan, rail[0])
    assert lead is not None and len(lead) == 2, (
        f"the rail's flag is reached by one straight vertical run (lead read: {lead})"
    )
    run = abs(lead[1][1] - lead[0][1])
    assert 20.0 <= run <= 40.0, (
        f"the rail's flag hangs {run:g} units off the rail — 岳's short run is 20-40, "
        "and 60 is the rung the flag box landed on while a part's own annotation text "
        "was treated as an obstacle (069 sec.11)"
    )


def test_duplicate_pads_on_one_side_keep_060s_short_jumper():
    """069 的边界：同侧重复脚仍走 060 sec.2 的实体短接，不给每只脚各打一颗旗。

    岳's rule is about pads that are 相隔较远 — far apart. Two neighbouring pads on
    one side of the body are a short jumper apart, and that jumper is what 060
    sec.2 drew and what stays: nothing here is "the far side", so the split must
    not fire. The claims are complementary on purpose: one wire run carrying both
    pads, and at most the *rail's* own flag (069 sec.7) rather than one per pad.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = circuit(
        [part("U1", "LDO-2VOUT-ONE-SIDE", "LDO"), part("C1", "C0805", "10u"),
         part("C2", "C0805", "22u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "power", ["U1.2", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )
    result = dc.compile(spec, ldo_presentation(), library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    posts = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    assert None not in posts
    assert _joined_by_a_wire(plan, *posts), (
        f"two pads of one role on one side are a short jumper apart and stay "
        f"wired (060 sec.2): {[s.points for s in plan.segments]}"
    )
    flags = [symbol for symbol in plan.power_symbols if symbol.net == "3V3"]
    assert len(flags) <= 1, (
        "the pads are on one side, so 069 sec.2 must not fire: no per-pad flag, at "
        f"most the rail's own (069 sec.7) — {[(s.x, s.y) for s in flags]}"
    )
    assert readability.check(
        plan, spec, ldo_presentation(), library(), page_box=page,
    ).hard_violations == []


def test_a_single_sided_role_and_an_nc_pad_are_left_exactly_as_060_drew_them():
    """069 的下界：单侧符号（RT9013 形状）不分脚，`nc[]` 的脚既不连线也不挂旗。

    Two shapes the new rule may not touch. A role with a single pin has no second
    pad to be far from, and a pad the spec writes into ``nc[]`` is withdrawn —
    060 sec.2's explicit exception, which 069 does not reopen. Both are measured
    the same way: the drawing's own netlist still says what the spec says, the net
    is one wire (069 sec.2 detached nothing), and the withdrawn pad carries no flag
    of the net it was withdrawn from.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    # (a) one VOUT pin, on the right: the RT9013 shape of 057's gap list.
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    vout, out_tip = pin_point(plan, "U1.2"), pin_point(plan, "C2.1")
    assert _joined_by_a_wire(plan, vout, out_tip), (
        "the output rail is still drawn as the wire 060 sec.2 left — one pin per "
        "role means nothing is detached (069 sec.2)"
    )
    assert len([s for s in plan.power_symbols if s.net == "3V3"]) == 1, (
        "and the rail carries exactly its own flag (069 sec.7), not one per pin: "
        f"{[(s.net, s.x, s.y) for s in plan.power_symbols]}"
    )

    # (b) the duplicate pad written into nc[]: off the net, and no flag on it.
    spec = _duplicate_vout_circuit(out_members=["U1.2", "C2.1"], nc=["U1.4"])
    presentation = ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    quiet = pin_point(plan, "U1.4")
    assert not on_a_wire(plan, quiet), "an explicit nc[] is still a no-connect"
    assert not [
        symbol for symbol in plan.power_symbols
        if symbol.net == "3V3"
        and math.hypot(symbol.x - quiet[0], symbol.y - quiet[1]) <= 60.0
    ], "069 must not bring a pad the spec withdrew out under a flag of its own"


def test_a_net_that_is_no_rail_or_ground_is_named_with_its_own_label():
    """069 sec.1's other half：非电源网用 netlabel，不借电源旗的形。

    岳's rule spells the name by the net's own kind ("该网已有旗标种类则沿用——电源网用
    电源旗、地网用地旗、其它网用 netlabel"). A signal the symbol carries on two pads
    the body separates is therefore brought out pad by pad and named by a label at
    the end of each stub — and no PWR-* symbol may appear on it, even though the
    library happens to carry a flag under this net's name. The electrical claim is
    the same as the rail case: one node, joined by the name.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = circuit(
        [part("U1", "AMS1117-3.3-C6186", "AMS1117-3.3"), part("C1", "C0805", "10u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "signal", ["U1.2", "U1.4"]),
            net("GND", "gnd", ["U1.1", "C1.2"]),
        ],
    )
    presentation = ldo_presentation(parts=("U1", "C1"))
    result = dc.compile(spec, presentation, library(), dc.CompileBudget(page_box=page))
    assert result.ok, render(result)
    plan = result.candidates[0]
    near, far = pin_point(plan, "U1.2"), pin_point(plan, "U1.4")
    assert None not in (near, far)
    assert not _joined_by_a_wire(plan, near, far), (
        "the run over the part is gone for a signal too: "
        f"{[s.points for s in plan.segments]}"
    )
    assert not [symbol for symbol in plan.power_symbols if symbol.net == "3V3"], (
        "a net that is neither a rail nor a ground is named by a label, never by a "
        f"PWR-* flag: {[(s.net, s.symbol_ref) for s in plan.power_symbols]}"
    )
    labels = [label for label in plan.labels if label.net == "3V3"]
    assert len(labels) == 2, (
        f"one label of the same net per pad: {[(l.net, l.x, l.y) for l in plan.labels]}"
    )
    for member, tip in (("U1.2", near), ("U1.4", far)):
        mine = [
            label for label in labels
            if _joined_by_a_wire(plan, tip, (label.x, label.y))
        ]
        assert len(mine) == 1, (
            f"{member} at {tip} must reach one of its own net's labels on its own "
            f"stub; the plan gives it {[(l.x, l.y) for l in mine]}"
        )
    derived = readability.derive_netlist(plan, library())
    assert derived.group_of("U1.2") == derived.group_of("U1.4"), (
        f"the two pads are one node in the spec: {derived.groups}"
    )
    assert readability.check(
        plan, spec, presentation, library(), page_box=page,
    ).hard_violations == []


def _flag_lead(plan: LayoutPlan, symbol) -> list[tuple[float, float]] | None:
    """The wire run that reaches this flag, from its pin to the anchor (or None)."""
    for segment in plan.segments:
        if segment.net != symbol.net or len(segment.points) < 2:
            continue
        last = segment.points[-1]
        if abs(last[0] - symbol.x) < 1e-6 and abs(last[1] - symbol.y) < 1e-6:
            return [tuple(point) for point in segment.points]
    return None


def test_a_rail_drawn_as_a_wire_carries_its_own_flag():
    """069 sec.7：电源网必须有电源旗，只有文本没有旗 = 缺陷（岳看 P23 的裁决）.

    岳 read the landed P23 page and asked why its 5 V rail had no flag at all: the
    net was drawn as a wire and stated by a text label, so nothing on the page said
    "power" in the one way the drawing says it. The compiler now supplies the flag
    — at the pin the rail *supplies* (the core's own pin on it), on 069 sec.1's stub
    — which is exactly the shape of his own VIN: a short run out of the pin and the
    rail's name on the end of it.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    vout_pin = pin_point(plan, "U1.3")
    flags = [symbol for symbol in plan.power_symbols if symbol.net == "VIN5"]
    assert len(flags) == 1, (
        "the input rail is drawn as a wire and carries its own flag — "
        f"{[(s.net, s.x, s.y) for s in plan.power_symbols]}"
    )
    lead = _flag_lead(plan, flags[0])
    assert lead is not None and len(lead) >= 2, (
        "the flag is reached by a lead from the pin it names, not dropped on the "
        f"wire (plan wires: {[s.points for s in plan.segments]})"
    )
    assert lead[0] == vout_pin, (
        f"VIN5's flag is hung on {lead[0]}, not on the core's own pin {vout_pin} — "
        "a rail belongs to the part it supplies (069 sec.7)"
    )
    assert flags[0].rotation in (0.0, 180.0)
    assert readability.check(
        plan, ldo_circuit(), ldo_presentation(), library(), page_box=page,
    ).hard_violations == []


def test_a_rail_the_plan_draws_without_a_flag_is_reported():
    """069 sec.7's other half: 检出——plan 上漏了旗，检查器要点名那条网。

    The compiler supplies the flag; this is what happens when it cannot (a library
    without the net's flag symbol, or a rail no flag could be reached from). The
    statement is checked on a plan that *has* been drawn and then had the flag
    taken away, so the finding is about the picture and not about the compiler's
    intentions.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    assert any(symbol.net == "VIN5" for symbol in plan.power_symbols), "premise"
    plan.power_symbols = [
        symbol for symbol in plan.power_symbols if symbol.net != "VIN5"
    ]
    findings = dc.check_grammar(
        plan, ldo_circuit(), ldo_presentation(), library(),
    )
    named = [item for item in findings if "VIN5" in item.detail]
    assert named, (
        "a power net drawn without a power flag is a finding — "
        f"the checker reported {[item.detail for item in findings]}"
    )
    assert "power flag" in named[0].detail and named[0].kind == dc.KIND_OBLIGATION_MISSING


def test_a_rail_flag_stands_upright_on_a_short_vertical_run():
    """069 sec.7：旗标一律竖直（rot ∈ {0,180}），rail 的旗挂在一小段竖线端。

    岳 refused the flat flag on the landed page and pointed at his own drawing for
    the rule: every ``Power-VCC`` in it is 0 and every ground 0 or 180, because
    each flag is reached by a *vertical* run — his VIN comes out along the rail and
    turns 20 units up to the flag. His other half is 「P23 5V部分为什么不给旗标？」:
    the rail has a flag at all.

    Measured on a circuit whose input rail is drawn as a wire: the rail's flag
    hangs off the rail by one short vertical run (20–40, his 20 and 30), and the
    glyph points away from the rail along it — 0 when the run goes up, 180 when the
    only room is below. No flag in the plan is 90 or 270.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]

    assert plan.power_symbols, "premise: this drawing carries flags"
    for symbol in plan.power_symbols:
        assert symbol.rotation in (0.0, 180.0), (
            f"{symbol.net}'s flag is drawn at {symbol.rotation} — 069 sec.7 puts "
            "every flag upright, and 90/270 is the flat flag 岳 refused"
        )

    # ... and on a drawing whose power pins escape *horizontally*, which is where
    # the retired compass laid a flag on its side (VIN to the left, pin 4 to the
    # right on the measured AMS1117: their flags were 90/270 before 069 sec.7).
    sideways = dc.compile(
        _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"]),
        ldo_presentation(
            sidePreferences={"input": "left", "output": "bottom"},
            modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
            portRoles={"VIN5": "input", "3V3": "output"},
        ),
        library(), dc.CompileBudget(page_box=page),
    )
    assert sideways.ok, render(sideways)
    for symbol in sideways.candidates[0].power_symbols:
        assert symbol.rotation in (0.0, 180.0), (
            f"{symbol.net}'s flag is drawn at {symbol.rotation} on a drawing whose "
            "pins escape horizontally — the compass that answered 90/270 there is "
            "what 岳 refused"
        )

    flags = [symbol for symbol in plan.power_symbols if symbol.net == "VIN5"]
    assert len(flags) == 1, (
        "the input rail carries its own flag (069 sec.7) — "
        f"{[(s.net, s.x, s.y, s.rotation) for s in plan.power_symbols]}"
    )
    lead = _flag_lead(plan, flags[0])
    assert lead is not None and len(lead) == 2, (
        f"VIN5's flag is reached by one straight run (lead read: {lead}) — a bent "
        "polyline here is also what the page layer cannot drop cleanly when it "
        "re-states a net at a module boundary"
    )
    assert abs(lead[1][0] - lead[0][0]) < 1e-6, (
        f"VIN5's flag hangs on a vertical line: {lead}"
    )
    run = abs(lead[1][1] - lead[0][1])
    assert 20.0 <= run <= 4.0 * dc.FLAG_LEAD, (
        f"VIN5's flag is {run:g} units off the rail — 岳's run is 20-40 (his own are "
        "20 and 30), and 069 sec.8 lets it reach *farther* when the short run would "
        "leave the flag's box touching a neighbouring wire"
    )
    assert (lead[1][1] > lead[0][1]) == (flags[0].rotation == 0.0), (
        f"a rail's glyph hangs away along its run: run {lead}, rotation "
        f"{flags[0].rotation} (069 sec.7 + 064's family table)"
    )
    wiring = {
        tuple(point) for segment in plan.segments if segment.net == "VIN5"
        for point in segment.points
    }
    assert lead[0] in wiring, (
        f"the run starts on the rail itself at {lead[0]}, not in mid-air "
        f"(the net's own points are {sorted(wiring)})"
    )


def test_a_flags_whole_box_keeps_clear_of_the_other_nets_wires():
    """069 sec.8：旗标整盒（glyph + 名文字 + margin）不得贴上别网导线。

    岳 on the landed page: 「3V3的旗标标识和5V的导线重合了」 — the flag's glyph grazed a
    neighbouring rail and the name the host prints with it was squeezed against the
    next net's vertical run. The anchor-only test 069 v2 added cannot see either: the
    box a flag occupies is its glyph **and** that name line (the host prints it just
    above the anchor), grown by a margin.

    Measured on a drawing whose module has room for it: *no* flag's box touches any
    other net's wire. On a drawing whose corner is crowded (the measured AMS1117 with
    its input capacitor ten units from its own pins) some flag has nowhere clear to
    stand — and then 069 sec.8's last resort applies: it stands **on its own pin**
    (a conductor), never in mid-air and never moved off the net it names.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    book = library()
    for symbol in plan.power_symbols:
        box = dc._flag_box(
            book[symbol.symbol_ref], symbol.rotation, (symbol.x, symbol.y), symbol.net,
        )
        for segment in plan.segments:
            if segment.net == symbol.net:
                continue
            for start, end in zip(segment.points, segment.points[1:]):
                assert not dc._segment_hits_box(start, end, box), (
                    f"{symbol.net}'s flag at ({symbol.x:g}, {symbol.y:g}) puts its own "
                    f"box {box} on {segment.net}'s wire {start}→{end} — 岳's 「旗标标识"
                    "和导线重合」"
                )

    crowded = dc.compile(
        _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"]),
        ldo_presentation(
            sidePreferences={"input": "left", "output": "bottom"},
            modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
            portRoles={"VIN5": "input", "3V3": "output"},
        ),
        library(), dc.CompileBudget(page_box=page),
    )
    assert crowded.ok, render(crowded)
    tight = crowded.candidates[0]
    tips = {
        pin_point(tight, member)
        for member in ("U1.1", "U1.2", "U1.3", "U1.4", "C1.1", "C1.2", "C2.1", "C2.2")
    }
    for symbol in tight.power_symbols:
        box = dc._flag_box(
            book[symbol.symbol_ref], symbol.rotation, (symbol.x, symbol.y), symbol.net,
        )
        touching = [
            segment.net for segment in tight.segments if segment.net != symbol.net
            and any(
                dc._segment_hits_box(start, end, box)
                for start, end in zip(segment.points, segment.points[1:])
            )
        ]
        if touching:
            assert (symbol.x, symbol.y) in tips, (
                f"{symbol.net}'s flag at ({symbol.x:g}, {symbol.y:g}) still touches "
                f"{touching} and does not stand on a pin — a crowded corner may only "
                "end with the flag on its own pin (069 sec.8)"
            )


# --------------------------------------- 074 旗引线不得穿越别网导体（硬规则）


def _same_point(left, right) -> bool:
    return abs(left[0] - right[0]) < 1e-6 and abs(left[1] - right[1]) < 1e-6


def _e1_presentation() -> PresentationSpec:
    """The module shape E1 lands: the measured AMS1117 with its own capacitors."""
    return ldo_presentation(
        sidePreferences={"input": "left", "output": "bottom"},
        modules=[module("pwr", ["U1", "C1", "C2"], "regulator")],
        portRoles={"VIN5": "input", "3V3": "output"},
    )


def _flag_lead_runs(plan: LayoutPlan) -> list[tuple[str, list[tuple[float, float]]]]:
    """Every run that exists only to carry a name: a flag's lead (074's own case).

    A run is a flag's lead when its far end is a flag's anchor, and `_place_flag`
    is the only thing that writes one — so this is the set 074 sec.2 hardens.
    """
    anchors = [(symbol.x, symbol.y) for symbol in plan.power_symbols]
    out = []
    for segment in plan.segments:
        if len(segment.points) < 2:
            continue
        if any(_same_point(tuple(segment.points[-1]), anchor) for anchor in anchors):
            out.append((segment.net, [tuple(point) for point in segment.points]))
    return out


def _lead_crossings(plan: LayoutPlan) -> list[str]:
    """Every place a flag lead **cuts through** another net's wire, described.

    The ruler is the compiler's own (`drawcompiler._proper_crossing`): strictly
    interior to both runs. The check is written out here rather than taken from the
    module's answer, because the claim is about the *drawing* and not about the
    compiler's opinion of it (053 sec.6).
    """
    out = []
    for net, points in _flag_lead_runs(plan):
        for start, end in zip(points, points[1:]):
            for segment in plan.segments:
                if segment.net == net:
                    continue
                for other_start, other_end in zip(segment.points, segment.points[1:]):
                    point = dc._proper_crossing(start, end, other_start, other_end)
                    if point is not None:
                        out.append(
                            f"{net} run {start}→{end} cuts {segment.net} "
                            f"({other_start[0]:g}, {other_start[1]:g})→"
                            f"({other_end[0]:g}, {other_end[1]:g}) at {point}"
                        )
    return out


def _stub_run(plan: LayoutPlan, net_id: str) -> tuple[list[tuple[float, float]], object]:
    """The one run of ``net_id`` that ends on one of its own labels, and the label."""
    anchors = [(label.net, label.x, label.y) for label in plan.labels]
    for segment in plan.segments:
        if segment.net != net_id or len(segment.points) < 2:
            continue
        last = tuple(segment.points[-1])
        for anchor_net, x, y in anchors:
            if anchor_net == net_id and _same_point(last, (x, y)):
                return [tuple(point) for point in segment.points], (x, y)
    raise AssertionError(
        f"no run of {net_id} reaches a label of its own: "
        f"{[s.points for s in plan.segments]} / "
        f"{[(l.net, l.x, l.y) for l in plan.labels]}"
    )


def _side_of(value: float, rail_y: float) -> int:
    return 1 if value > rail_y else (-1 if value < rail_y else 0)


def test_a_pads_flag_lead_never_cuts_through_another_nets_wire():
    """074：旗引线穿越别网导体 = 硬拒；梯子必须找到零穿越解（岳 P23 裁决）.

    岳 read the landed P23 page and said it in one line: 「不行，现在第一眼以为5V和
    3V3的旗标短接在一块了，这个必须改」. The measured form was pin 2's 3V3 flag — a
    run out of the pad and a turn up, and the **turn** went through the input rail at
    (135, 740). No junction dot, so the netlist was right, and the picture still read
    as a short: 「一眼不读成衔接」 is the requirement, and an electrician's first
    reading is the one that counts.

    The pad's own ladder answers it (069 sec.3, 074 sec.3): the crossing turns are
    refused one at a time and the flag ends up hanging on the pad's own side of the
    rail, where no conductor is across it. Two claims: **no** flag lead of **any**
    candidate cuts another net's wire, and the pad's flag is still a lead — never
    069 sec.8's flag standing on its own pin, which is the form 岳 rejected.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    result = dc.compile(
        spec, _e1_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]

    for candidate in result.candidates:
        assert _lead_crossings(candidate) == [], (
            f"a flag lead of {candidate.geometry_sha256()[:12]} cuts through another "
            f"net's wire — 岳 reads that as a short: {_lead_crossings(candidate)}"
        )

    near = pin_point(plan, "U1.2")
    rail_y = pin_point(plan, "U1.3")[1]
    assert near is not None
    mine = [
        symbol for symbol in plan.power_symbols
        if symbol.net == "3V3" and _joined_by_a_wire(plan, near, (symbol.x, symbol.y))
    ]
    assert len(mine) == 1, (
        "069 sec.1: the pad across the body is named by a flag at the end of its own "
        f"run — the plan gives it {[(s.x, s.y) for s in mine]}"
    )
    flag = mine[0]
    lead = _flag_lead(plan, flag)
    assert lead is not None and len(lead) >= 2, (
        f"3V3's flag at ({flag.x:g}, {flag.y:g}) is not reached by a run of its own "
        f"(plan wires: {[s.points for s in plan.segments]})"
    )
    assert flag.rotation in (0.0, 180.0), (
        f"the flag stands at {flag.rotation} — 069 sec.7 allows 0 or 180 only"
    )
    assert _side_of(flag.y, rail_y) == _side_of(near[1], rail_y), (
        f"pin 2's flag hangs at y={flag.y:g} while the pad is at y={near[1]:g} and the "
        f"input rail runs at y={rail_y:g} — 074 sec.3 hangs the flag on the side with "
        "no rail across it, never over one"
    )
    assert abs(flag.y - rail_y) > abs(near[1] - rail_y), (
        f"pin 2's flag at ({flag.x:g}, {flag.y:g}) is no farther from the rail "
        f"(y={rail_y:g}) than the pad itself — the run only reaches, it does not "
        "climb past the conductor it must avoid"
    )


def test_a_pads_label_stub_never_cuts_through_another_nets_wire():
    """074 sec.2：069① 的 netlabel stub 与旗引线同一把尺——穿越同样硬拒。

    The same pad, the same crossing, the same drawing — the only difference is the
    name form: a **signal** is named by a label (069 sec.1), so the run out of the
    pad ends at a label instead of a flag. 074 treats it as the same line doing the
    same job (「这个网从这里出去」), so the same refusal applies and the same ladder
    answers it: the stub still leaves the pad, still runs a sibling lead (40-60),
    and no longer climbs through the rail.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = circuit(
        [part("U1", "AMS1117-3.3-C6186", "AMS1117-3.3"),
         part("C1", "C0805", "10u"), part("C2", "C0805", "22u")],
        [
            net("VIN5", "power", ["U1.3", "C1.1"]),
            net("3V3", "signal", ["U1.2", "U1.4", "C2.1"]),
            net("GND", "gnd", ["U1.1", "C1.2", "C2.2"]),
        ],
    )
    result = dc.compile(
        spec, _e1_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    plan = result.candidates[0]
    for candidate in result.candidates:
        assert _lead_crossings(candidate) == [], (
            f"a stub of {candidate.geometry_sha256()[:12]} cuts through another "
            f"net's wire: {_lead_crossings(candidate)}"
        )

    labels = [label for label in plan.labels if label.net == "3V3"]
    assert len(labels) == 2, (
        f"one label of the same net per pad (069 sec.1): "
        f"{[(l.net, l.x, l.y) for l in plan.labels]}"
    )
    near = pin_point(plan, "U1.2")
    rail_y = pin_point(plan, "U1.3")[1]
    assert near is not None
    stub, anchor = _stub_run(plan, "3V3")
    assert _same_point(stub[0], near), (
        f"the run 074 judges leaves pin 2 at {stub[0]}, and pin 2 is at {near}"
    )
    assert max(abs(stub[-1][0] - stub[0][0]), abs(stub[-1][1] - stub[0][1])) >= (
        dc.SIBLING_LEAD - 1e-6
    ), (
        f"the pad's own run is {stub} — 069 sec.1 gives the pad a sibling lead "
        f"({dc.SIBLING_LEAD:g}) and the label stands at {anchor}"
    )
    assert all(_side_of(point[1], rail_y) == _side_of(near[1], rail_y)
               for point in stub), (
        f"the stub {stub} crosses to the rail's own side (y={rail_y:g}) — the pad is "
        f"at y={near[1]:g} and 074 keeps the run on that side"
    )


def test_the_crossing_ruler_reads_a_cut_and_not_a_join():
    """074 sec.1 的尺子：严格内部穿越才算穿越——共享端点/T 型/共线重叠都不算.

    Cutting through and joining are different pictures and the drawing has different
    words for them: a run that cuts a foreign wire joins nothing (054 C7's measured
    behaviour — which is why the gate keeps counting crossings as a soft metric),
    while a run whose **end** lands on another net's wire is a tee, the junction 053
    sec.2 puts a dot on and the editor makes a connection out of. 074 refuses the
    first for a lead and must never mistake it for the second — otherwise "refuse
    the crossing" quietly becomes "refuse the join", and no junction is welded on to
    make a crossing look intended either.

    The ruler is checked against `readability._proper_crossing`, which the contract
    has used since 053: two rulers for one word drift, and the drift shows up as a
    drawing that is refused on one reading and accepted on the other.
    """
    cases = [
        # a proper cut: strictly interior to both runs
        ((0.0, 0.0), (100.0, 0.0), (50.0, -50.0), (50.0, 50.0)),
        # corners of the same square: still a cut, at an off-grid point
        ((0.0, 0.0), (30.0, 30.0), (0.0, 30.0), (30.0, 0.0)),
        # a tee: one run's end lands inside the other's span
        ((0.0, 0.0), (100.0, 0.0), (50.0, 0.0), (50.0, 50.0)),
        ((0.0, 0.0), (100.0, 0.0), (50.0, 50.0), (50.0, 0.0)),
        # end to end: a shared endpoint
        ((0.0, 0.0), (50.0, 0.0), (50.0, 0.0), (50.0, 50.0)),
        # collinear overlap: two runs along one line
        ((0.0, 0.0), (100.0, 0.0), (50.0, 0.0), (150.0, 0.0)),
        ((0.0, 0.0), (100.0, 0.0), (100.0, 0.0), (150.0, 0.0)),
        # parallel, and a run that stops short
        ((0.0, 0.0), (100.0, 0.0), (0.0, 20.0), (100.0, 20.0)),
        ((0.0, 0.0), (40.0, 0.0), (50.0, -50.0), (50.0, 50.0)),
        # a degenerate run is nothing at all
        ((10.0, 10.0), (10.0, 10.0), (0.0, 10.0), (20.0, 10.0)),
    ]
    for a, b, c, d in cases:
        mine = dc._proper_crossing(a, b, c, d)
        theirs = readability._proper_crossing(a, b, c, d)
        assert (mine is None) == (theirs is None), (
            f"{a}→{b} against {c}→{d}: the compiler reads {mine} and the checker "
            f"reads {theirs} — one word, two rulers"
        )
        if mine is not None:
            assert _same_point(mine, theirs), (mine, theirs)
    assert dc._proper_crossing(*cases[0]) is not None
    assert dc._proper_crossing(*cases[1]) is not None
    for tee in cases[2:]:
        assert dc._proper_crossing(*tee) is None, (
            f"{tee} is a join (a tee, a shared end, an overlap or nothing at all), "
            "not a crossing: 074 refuses a cut, and a joint is the connection the "
            "page is made of"
        )

    # And on a drawing: a lead that starts on its **own** net's wiring is the tee
    # that *is* the connection — 069 sec.7 hangs the rail's flag off the pin the rail
    # supplies, so the run shares its endpoint with the rail's own wire and must not
    # be read as a crossing of anything.
    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    assert _lead_crossings(result.candidates[0]) == [], (
        "a flag lead of the plain LDO drawing is reported as cutting a wire: "
        f"{_lead_crossings(result.candidates[0])}"
    )


def test_a_pad_sealed_on_every_side_is_layout_unsat_with_the_conductor_named():
    """074 sec.3/4：四向都穿越 = 梯子穷尽 → layout-unsat，报实测原因与建议动作.

    The ladder's last word (074 sec.3): distance rungs, the turn, and every side of
    the pad. When every one of them cuts another net's wire there is no drawing to
    make — and the answer is not silence, and not 069 sec.8's flag on its own pin
    (the form 岳 rejected), but a refusal that says **which** run crossed **which**
    conductor **where** and what to move (053 sec.5 scenario 10's rule). A message
    that names no obstacle is a puzzle; a junction welded onto the crossing to make
    it look intended is a short.

    The seals here are four wires five units from the pin — closer than every rung
    the ladder has — so each of the four directions is measured and each one comes
    back crossed.
    """
    pin = (200.0, 200.0)
    router = dc.lattice_router(
        grid=UNIT, residue=(0.0, 0.0), boxes=(), bounds=(0.0, 0.0, 400.0, 400.0),
    )
    router.edges = [
        ((195.0, 150.0), (195.0, 250.0)),  # west of the pin, 5 units out
        ((205.0, 150.0), (205.0, 250.0)),  # east
        ((150.0, 205.0), (250.0, 205.0)),  # north
        ((150.0, 195.0), (250.0, 195.0)),  # south
    ]
    router.edge_nets = ["5V0", "5V0", "GND", "GND"]

    west: list[str] = []
    for direction in ((1.0, 0.0), (0.0, 1.0), (0.0, -1.0), (-1.0, 0.0)):
        crossings: list[str] = []
        anchor, lead, _hang = dc._flag_anchor(
            router, pin, direction, set(),
            leads=(dc.SIBLING_LEAD,), crossings=crossings,
        )
        assert lead is None and anchor == pin, (
            f"the lead out of {pin} towards {direction} was drawn as {lead} — every "
            "rung of it cuts one of the four wires five units away (074 sec.3)"
        )
        assert crossings, f"direction {direction} was refused without a reason"
        if direction == (-1.0, 0.0):
            west = crossings

    failure = dc._flag_crossing_failure(
        "3V3", pin, west, "U1.2 is named by a flag of its own (069 sec.1)",
    )
    assert failure.category == dc.FAILURE_LAYOUT_UNSAT, (
        f"a pad whose every lead crosses a wire is {failure.category}, not a "
        "downgrade: silently drawing it is what this batch exists to stop"
    )
    assert failure.subject == "3V3"
    for piece in (
        "U1.2 is named by a flag of its own (069 sec.1)",
        "its run (200, 200)-(150, 200)",
        "crosses net 5V0's wire (195, 150)-(195, 250) at (195, 200)",
    ):
        assert piece in failure.detail, (
            f"the refusal does not name {piece!r} — 074 sec.4 wants the measured "
            f"reason: {failure.detail}"
        )
    assert failure.action, "a refusal without an action is a puzzle (053 sec.4)"
    assert "junction" in failure.action, (
        "the action has to say the crossing is not repaired with a junction — a dot "
        f"there would join two nets the spec keeps apart: {failure.action}"
    )


def test_a_lead_that_cuts_another_net_refuses_that_variant_and_names_the_run():
    """074 sec.4：拒绝要出现在编译器的答复里，逐变体、带实测原因（不是静默丢弃）.

    The ladder turning down a crossing rung is invisible on its own: a variant that
    loses a pad's flag has to *say so*, or the caller only sees fewer candidates and
    no reason. This is the other half of the drawing claim in
    :func:`test_a_pads_flag_lead_never_cuts_through_another_nets_wire` — the same
    compile, read from the refusal side: some variant is refused as
    ``layout-unsat``, the refusal names the run and the net it crossed, and no
    variant is refused without a name.
    """
    page = (0.0, 0.0, 1170.0, 825.0)
    spec = _duplicate_vout_circuit(out_members=["U1.2", "U1.4", "C2.1"])
    result = dc.compile(
        spec, _e1_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    refused = [
        item for item in result.rejected
        if item.failure is not None
        and item.failure.category == dc.FAILURE_LAYOUT_UNSAT
    ]
    assert refused, (
        "the crossing rung of the E1 shape is refused by the ladder, but the "
        f"compiler's answer says nothing about it: "
        f"{[(item.variant, item.reason) for item in result.rejected]}"
    )
    for item in refused:
        assert "crosses net" in item.failure.detail and " at (" in item.failure.detail, (
            f"variant {item.variant} was refused as layout-unsat without naming the "
            f"conductor it crossed: {item.failure.detail}"
        )
        assert item.failure.action
    assert any("VIN5" in item.failure.detail for item in refused), (
        "the measured crossing on this shape is the input rail VIN5 being cut by pin "
        f"2's own run: {[item.failure.detail for item in refused]}"
    )


def test_every_statement_of_the_074_refusal_fits_its_own_signature():
    """074 的拒绝只有一个构造器：三处调用都必须与签名对得上.

    The batch adds one refusal and three call sites — a pad's flag, the rail's flag,
    a stub's label. One of them passed the pin as ``(member, point)`` *and* the two
    halves separately, which only a page where a rail's every run is crossed would
    have reached: no offline scenario has one, so no drawing test could see it, and
    the failure would have been a `TypeError` where a refusal belongs. A refusal
    that cannot be built is no refusal at all, so the calls are checked against the
    signature the way the compiler itself would bind them.
    """
    source = Path(dc.__file__).read_text(encoding="utf-8")
    calls = [
        node for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "_flag_crossing_failure"
    ]
    assert len(calls) >= 3, (
        "premise: the pad's flag, the rail's flag and the label's stub each state "
        f"this refusal — the module calls it {len(calls)} time(s)"
    )
    expected = len(inspect.signature(dc._flag_crossing_failure).parameters)
    for node in calls:
        assert len(node.args) == expected and not node.keywords, (
            f"line {node.lineno} of {Path(dc.__file__).name} passes "
            f"{len(node.args)} argument(s) to _flag_crossing_failure, whose "
            f"signature takes {expected} — the refusal cannot be built there"
        )


def test_only_a_leads_run_is_gated_and_ordinary_wiring_still_crosses():
    """074 sec.2 的范围：只有旗引线/stub 硬化，普通信号布线维持 crossings 软指标.

    Crossing is how a dense schematic is drawn: a few wires with nowhere else to go
    pass over each other, and the contract counts them (`readability`'s soft metric)
    instead of forbidding them. 074 changes that for one thing only — the run that
    exists to carry a **name** — because that is the run 岳 read as a short. So the
    router's own answer is compared against the gate's: the same geometry is a legal
    wire and an illegal lead.
    """
    router = dc.lattice_router(
        grid=UNIT, residue=(0.0, 0.0), boxes=(), bounds=(0.0, 0.0, 400.0, 400.0),
    )
    router.edges = [((100.0, 100.0), (100.0, 300.0))]
    router.edge_nets = ["GND"]
    run = [(50.0, 200.0), (250.0, 200.0)]
    assert dc.one_bend_route(router, run[0], run[1], set()) == run, (
        "ordinary wiring no longer crosses another net's wire — 074 hardens a flag's "
        "lead, and widening that to the router would refuse drawings 岳 never "
        "complained about"
    )
    assert dc._lead_crossing(router, run) is not None, (
        "the very same geometry, judged as a lead, is refused (074 sec.1)"
    )

    page = (0.0, 0.0, 1170.0, 825.0)
    result = dc.compile(
        ldo_circuit(), ldo_presentation(), library(), dc.CompileBudget(page_box=page),
    )
    assert result.ok, render(result)
    metrics = result.candidates[0].evidence.soft_metrics
    assert "crossings" in metrics, (
        "crossings must stay a counted soft metric of every drawing — the gate's "
        f"layers are {sorted(metrics)}"
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

    074 costs this shape one of the three variants it used to offer: on that
    variant the GND pad's own flag has no side left to hang on that no other net
    crosses, so the ladder refuses the variant by name instead of drawing the lead
    that cut a neighbour. Two drawings remain, and neither of them carries a flag
    lead through another net's conductor.
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
    assert len(result.candidates) >= 2, render(result)
    plan = result.candidates[0]
    assert plan.part("U1") is not None and plan.part("C2") is not None
    assert _lead_crossings(plan) == [], _lead_crossings(plan)
    for item in result.rejected:
        if item.failure is not None:
            assert item.failure.category == dc.FAILURE_LAYOUT_UNSAT
            assert "crosses net" in item.failure.detail, item.failure.detail
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
