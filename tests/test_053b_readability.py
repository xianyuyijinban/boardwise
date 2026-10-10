"""053 阶段 B 第一波：独立可读性检查器（`engines/readability.py`）。

这一批只做**检查器**：编译器还不存在，语法 checker 是另一批的活。测试要钉住
的是 052 §6 的硬约束真的能**独立**检出负例——尤其是 053 §五 场景 11 的三类
故意错误（短路 / 错脚 / NC 被接）和"文字压字"。用例全部是**手写字面量**
（最小 CircuitSpec + LayoutPlan），不建夹具文件：这份合约说的是"检查器从
图纸和两份 spec 能读到什么"，夹具反而会把生成器的行为绑进来。

每个硬约束都有正例（通过）和负例（检出且 kind/对象正确）。正例的基座是一张
分压图：R1 上、R2 下、`MID` 抽头（带 junction 和标签）、`VIN`/`GND` 电源符号。
负例都在这张图上只改动一处，所以"多出来的那条违规"就能直接归因到那处改动。

`grammar_findings` 本批恒空，靠注入参数接语法 checker——两条测试分别钉住
"不注入就恒空"和"注入后原样存回、四个输入确实是那四个"。

坐标容差见模块 docstring：`PRECISION` = 6 位小数、`TOL` = 1e-6 canvas unit，
坐标相等按精确相等处理（整数网格世界），容差只用来吸掉旋转带来的浮点噪声。
"""

from __future__ import annotations

import ast
from collections import namedtuple
from pathlib import Path

import pytest

from boardwise.core.circuitspec import (
    CircuitSpec,
    SpecNet,
    SpecNoConnect,
    SpecOpenInterface,
    SpecPart,
)
from boardwise.core.layoutplan import (
    LayoutJunction,
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutText,
)
from boardwise.core.presentationspec import (
    PresentationModule,
    PresentationSpec,
    UserLock,
)
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile
from boardwise.engines import layout as layout_engine
from boardwise.engines import readability
from boardwise.engines.readability import (
    CHECKER_NAME,
    DEFAULT_GRID,
    HARD_KINDS,
    KIND_DANGLING_WIRE_END,
    KIND_NC_PIN_CONNECTED,
    KIND_NETLIST_PARTITION,
    KIND_OUT_OF_PAGE,
    KIND_REQUIRED_PIN_NOT_CONNECTED,
    KIND_TEXT_OVERLAP,
    KIND_UNDECLARED_JUNCTION,
    KIND_USER_LOCK_VIOLATED,
    KIND_WIRE_ON_PIN_LINE,
    KIND_WIRE_THROUGH_BODY,
    PRECISION,
    TOL,
    UNMEASURED,
    ReadabilityError,
    check,
    derive_netlist,
)

#: The target page. Everything in the base case sits inside it.
PAGE = (0.0, 0.0, 1000.0, 800.0)

#: The column the two resistors stand on. Not 0: a symbol's body box reaches
#: half its width to the left of its origin, and a page starts at x = 0.
COL = 100.0

RESISTOR = "R-VERT"
IC = "IC-3P"
HASH = "a" * 64

_KEEP = object()


# --------------------------------------------------------------- the fixtures


def _resistor_profile() -> SymbolProfile:
    """A vertical two-pin resistor: tips 50 units above and below the body.

    Handwritten rather than parsed: the checker's contract is "given a profile,
    the pin tips are where the pose puts them", and a parser fixture would drag
    the parser's behaviour into this batch's tests.
    """
    return SymbolProfile(
        symbol_ref=RESISTOR,
        title="Resistor, vertical",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(0.0, 50.0), name="1", direction="up"),
            SymbolPin(number="2", tip=(0.0, -50.0), name="2", direction="down"),
        ],
    )


def _ic_profile() -> SymbolProfile:
    """An asymmetric three-pin symbol: mirroring has to move pins 1 and 2."""
    return SymbolProfile(
        symbol_ref=IC,
        title="Three-pin block",
        body=(-20.0, -20.0, 20.0, 20.0),
        pins=[
            SymbolPin(number="1", tip=(-50.0, 0.0), name="IN", direction="left"),
            SymbolPin(number="2", tip=(50.0, 0.0), name="OUT", direction="right"),
            SymbolPin(number="3", tip=(0.0, -50.0), name="GND", direction="down"),
        ],
    )


def _parts() -> list[LayoutPart]:
    return [
        LayoutPart(
            part_id="R1", symbol_ref=RESISTOR, symbol_hash=HASH,
            x=COL, y=400.0, rotation=0.0, mirror=False, reference="R1",
        ),
        LayoutPart(
            part_id="R2", symbol_ref=RESISTOR, symbol_hash=HASH,
            x=COL, y=200.0, rotation=0.0, mirror=False, reference="R2",
        ),
    ]


def _segments() -> list[LayoutSegment]:
    """R1.2 -> R2.1, plus the tap that tees into it at (COL, 300)."""
    return [
        LayoutSegment(net="MID", points=[(COL, 350.0), (COL, 250.0)]),
        LayoutSegment(net="MID", points=[(COL, 300.0), (COL + 100.0, 300.0)]),
    ]


def _junctions() -> list[LayoutJunction]:
    return [LayoutJunction(net="MID", x=COL, y=300.0)]


def _labels() -> list[LayoutLabel]:
    return [
        LayoutLabel(
            net="MID", text="MID", x=COL + 100.0, y=300.0,
            bbox=(COL + 100.0, 300.0, COL + 130.0, 320.0),
        )
    ]


def _power_symbols() -> list[LayoutPowerSymbol]:
    return [
        LayoutPowerSymbol(
            symbol_ref="PWR-VIN", symbol_hash=HASH, net="VIN", x=COL, y=450.0
        ),
        LayoutPowerSymbol(
            symbol_ref="PWR-GND", symbol_hash=HASH, net="GND", x=COL, y=150.0
        ),
    ]


def _texts() -> list[LayoutText]:
    return [
        LayoutText(
            kind="reference", text="R1", part_id="R1",
            bbox=(COL + 20.0, 430.0, COL + 40.0, 450.0),
        ),
        LayoutText(
            kind="reference", text="R2", part_id="R2",
            bbox=(COL + 20.0, 230.0, COL + 40.0, 250.0),
        ),
        LayoutText(
            kind="value", text="10k", part_id="R1",
            bbox=(COL + 15.0, 405.0, COL + 45.0, 415.0),
        ),
    ]


def _circuit(*, nets=None, nc=None, parts=None) -> CircuitSpec:
    return CircuitSpec(
        parts=parts if parts is not None else [
            SpecPart(id="R1", symbol_ref=RESISTOR, value="10k"),
            SpecPart(id="R2", symbol_ref=RESISTOR, value="10k"),
        ],
        nets=nets if nets is not None else [
            SpecNet(id="VIN", cls="power", members=["R1.1"]),
            SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
            SpecNet(id="GND", cls="gnd", members=["R2.2"]),
        ],
        nc=nc if nc is not None else [],
    )


def _presentation(*, locks=None, modules=None) -> PresentationSpec:
    return PresentationSpec(
        modules=modules if modules is not None else [
            PresentationModule(id="main", parts=["R1", "R2"], role="divider")
        ],
        grammar_ref="voltage-divider",
        user_locks=locks if locks is not None else [],
    )


_Case = namedtuple("_Case", "plan circuit presentation profiles page_box")


def _case(
    *,
    parts=_KEEP,
    segments=_KEEP,
    junctions=_KEEP,
    labels=_KEEP,
    power_symbols=_KEEP,
    texts=_KEEP,
    circuit=_KEEP,
    presentation=_KEEP,
    profiles=_KEEP,
    page_box=_KEEP,
) -> _Case:
    """The base divider, with any single list replaced (``None`` empties it)."""
    plan = LayoutPlan(
        # The two source digests are opaque to the checker (see "what it does
        # not check") but the schema requires them, and a plan no compiler
        # could emit is not the input this checker is pinned against.
        source=LayoutSource(circuit_sha256=HASH, presentation_sha256=HASH),
        parts=_parts() if parts is _KEEP else parts,
        segments=_segments() if segments is _KEEP else segments,
        junctions=_junctions() if junctions is _KEEP else junctions,
        labels=_labels() if labels is _KEEP else labels,
        power_symbols=(
            _power_symbols() if power_symbols is _KEEP else power_symbols
        ),
        texts=_texts() if texts is _KEEP else texts,
    )
    return _Case(
        plan=plan,
        circuit=_circuit() if circuit is _KEEP else circuit,
        presentation=_presentation() if presentation is _KEEP else presentation,
        profiles=(
            {RESISTOR: _resistor_profile()} if profiles is _KEEP else profiles
        ),
        page_box=PAGE if page_box is _KEEP else page_box,
    )


def _run(case: _Case):
    return check(
        case.plan, case.circuit, case.presentation, case.profiles,
        page_box=case.page_box,
    )


def _of(result, kind):
    return [item for item in result.hard_violations if item.kind == kind]


def _kinds(result) -> list[str]:
    return [item.kind for item in result.hard_violations]


# ------------------------------------------------ the contract and its shape


def test_the_hard_kinds_are_the_eleven_the_contract_names():
    """The vocabulary itself: eleven constraints, one kind each, fixed order.

    147 added `wire-on-pin-line` and `text-on-wire` — the two classes 岳 caught by
    eye on a page every gate called clean (`outputs/147/FINDINGS.md`): a wire
    lying *along* a symbol's own lead, and a conductor printed through a text row.
    `wire-through-body`'s box could not see the first (a line is not a box) and
    `text-overlap` never looked at a conductor at all.
    """
    assert HARD_KINDS == (
        "netlist-partition-mismatch",
        "dangling-wire-end",
        "undeclared-junction",
        "wire-through-body",
        "wire-on-pin-line",
        "text-overlap",
        "text-on-wire",
        "out-of-page",
        "user-lock-violated",
        "nc-pin-connected",
        "required-pin-not-connected",
    )
    assert CHECKER_NAME.startswith("boardwise-readability/")


def test_the_comparison_rules_are_the_documented_ones():
    """Exact equality on an integer grid, with the grid slack of one lattice step."""
    assert TOL == 10.0 ** -PRECISION
    assert TOL == 1e-6
    assert DEFAULT_GRID == layout_engine.GRID
    assert UNMEASURED < 0.0, "the sentinel must not be a real distance or ratio"


def test_the_checker_reaches_the_package_only_through_core():
    """Independence is architectural: no generator, no rules, no cli.

    The checker's whole claim is that it judges a drawing without the
    compiler's insides (052 §8). That is only true while its imports say so, so
    the imports are the test — a future "just read the plan the generator kept"
    shortcut fails here before it fails in review.
    """
    source = Path(readability.__file__).read_text(encoding="utf-8")
    imported: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    in_package = [name for name in imported if name.split(".")[0] == "boardwise"]
    assert in_package, "the checker is expected to import core through the package"
    assert all(name.startswith("boardwise.core.") for name in in_package), in_package


def test_the_base_divider_passes_every_hard_constraint():
    result = _run(_case())
    assert result.hard_violations == []
    assert result.ok
    assert result.grammar_findings == []


def test_the_plan_the_checker_reads_is_one_the_schema_accepts():
    """The literals above are not a private dialect: re-read them through the schema.

    A tester can hand-build a plan the reader would refuse (`symbolHash` is a
    64-hex digest there), and then the checker would be pinned against inputs no
    compiler can produce.
    """
    case = _case()
    reloaded = LayoutPlan.from_dict(case.plan.to_jsonable())
    result = check(
        reloaded, case.circuit, case.presentation, case.profiles,
        page_box=case.page_box,
    )
    assert result.ok
    assert [item.render() for item in result.hard_violations] == []


# ------------------------------------------------------------------- grammar


def test_grammar_findings_are_empty_without_an_injected_checker():
    """The grammar layer is another batch: nothing here may produce findings.

    Asserted on a plan that *does* have hard violations, so "empty because
    nothing ran" cannot be confused with "empty because all is well".
    """
    case = _case(junctions=[])
    result = _run(case)
    assert result.hard_violations
    assert result.grammar_findings == []


def test_the_injected_grammar_checker_gets_the_four_inputs_and_stores_findings():
    """The injection point: same four inputs, findings kept verbatim."""
    case = _case()
    seen: list[tuple] = []

    def grammar_checker(plan, circuit, presentation, profiles):
        seen.append((plan, circuit, presentation, profiles))
        return ["tap-not-visible: MID"]

    result = check(
        case.plan, case.circuit, case.presentation, case.profiles,
        grammar_checker=grammar_checker, page_box=case.page_box,
    )
    assert result.grammar_findings == ["tap-not-visible: MID"]
    assert len(seen) == 1
    plan, circuit, presentation, profiles = seen[0]
    assert plan is case.plan
    assert circuit is case.circuit
    assert presentation is case.presentation
    assert profiles == case.profiles

    # A checker with nothing to say returns nothing, and `None` is not a finding.
    assert check(
        case.plan, case.circuit, case.presentation, case.profiles,
        grammar_checker=lambda *_: None, page_box=case.page_box,
    ).grammar_findings == []


# --------------------------------------------- 1. the derived netlist is the spec


def test_a_short_is_detected_as_a_merged_node():
    """Scenario 11's "短路": a stray wire joins GND onto the MID node."""
    case = _case(segments=_segments() + [
        LayoutSegment(net="GND", points=[(COL, 150.0), (COL, 250.0)]),
    ])
    result = _run(case)
    found = _of(result, KIND_NETLIST_PARTITION)
    assert len(found) == 1
    assert found[0].objects == (
        "pins[R1.2]", "pins[R2.1]", "pins[R2.2]",
    )
    assert "'GND'" in found[0].evidence and "'MID'" in found[0].evidence


def test_a_split_net_is_detected():
    """The same constraint from the other side: a declared node drawn apart."""
    case = _case(
        segments=[LayoutSegment(net="MID", points=[(COL, 350.0), (200.0, 350.0)])],
        junctions=[],
        labels=[LayoutLabel(
            net="MID", text="MID", x=200.0, y=350.0,
            bbox=(200.0, 350.0, 230.0, 370.0),
        )],
    )
    result = _run(case)
    found = _of(result, KIND_NETLIST_PARTITION)
    assert len(found) == 1
    assert found[0].objects[0] == "circuitSpec.nets[MID]"
    assert set(found[0].objects) >= {"pins[R1.2]", "pins[R2.1]"}
    assert "separate node" in found[0].evidence


def test_a_pin_the_spec_never_mentions_may_not_be_wired_in():
    """An undeclared connection is a connection the spec did not make.

    One finding, and only one: the diagram is otherwise the base case, so the
    count pins exactly the "spec says nothing ≠ the drawing may join it" rule.
    """
    case = _case(circuit=_circuit(nets=[
        SpecNet(id="VIN", cls="power", members=["R1.1"]),
        SpecNet(id="MID", cls="signal", members=["R1.2"]),
        SpecNet(id="GND", cls="gnd", members=["R2.2"]),
    ]))
    result = _run(case)
    found = _of(result, KIND_NETLIST_PARTITION)
    assert [item.objects for item in found] == [
        ("pins[R1.2]", "pins[R2.1]"),
    ]
    assert "unmentioned" in found[0].evidence
    assert len(result.hard_violations) == 1


def test_the_netlist_is_read_from_geometry_not_from_the_segment_net_ids():
    """Segment `net` strings are decoration: a mislabelled wire still passes.

    The partition is the fact (052 §4); a plan that names its wire "GND" while
    wiring it between the divider's two resistors is electrically the MID wire,
    and the checker must not invent a violation from the label alone.
    """
    case = _case(segments=[
        LayoutSegment(net="GND", points=[(COL, 350.0), (COL, 250.0)]),
        LayoutSegment(net="GND", points=[(COL, 300.0), (COL + 100.0, 300.0)]),
    ])
    assert _run(case).hard_violations == []


def test_derive_netlist_joins_by_wire_label_and_power_symbol():
    """The derivation's three joining rules, read directly."""
    plan = LayoutPlan(
        parts=[
            LayoutPart(part_id="R1", symbol_ref=RESISTOR, x=COL, y=400.0),
            LayoutPart(part_id="R2", symbol_ref=RESISTOR, x=COL, y=600.0),
        ],
        segments=[
            # R1's lower pin to a labelled stub far away ...
            LayoutSegment(net="M", points=[(COL, 350.0), (COL + 100.0, 350.0)]),
            # ... and R2's upper pin to a stub carrying the same name.
            LayoutSegment(net="M", points=[(COL, 650.0), (COL + 100.0, 650.0)]),
        ],
        labels=[
            LayoutLabel(net="M", text="M", x=COL + 100.0, y=350.0,
                        bbox=(COL + 100.0, 350.0, COL + 130.0, 370.0)),
            LayoutLabel(net="M", text="M", x=COL + 100.0, y=650.0,
                        bbox=(COL + 100.0, 650.0, COL + 130.0, 670.0)),
        ],
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-VIN", net="VIN", x=COL, y=450.0),
        ],
    )
    net = derive_netlist(plan, {RESISTOR: _resistor_profile()})
    assert net.group_of("R1.2") == ("R1.2", "R2.1")
    assert net.group_of("R1.1") == ("R1.1",)
    assert net.pin_points["R1.1"] == (COL, 450.0)
    assert {"R1.1", "R1.2", "R2.1"} <= net.wired_pins
    assert "R2.2" not in net.wired_pins


def test_a_rotated_part_puts_its_pin_where_the_pose_says():
    """A pin tip is a *local* coordinate: the pose has to move it."""
    rotated = [LayoutPart(
        part_id="R1", symbol_ref=RESISTOR, x=COL, y=400.0, rotation=90.0,
    )]
    circuit = _circuit(
        parts=[SpecPart(id="R1", symbol_ref=RESISTOR, value="10k")],
        nets=[
            SpecNet(id="VIN", cls="power", members=["R1.1"]),
            SpecNet(id="GND", cls="gnd", members=["R1.2"]),
        ],
    )
    correct = _case(
        parts=rotated,
        segments=[],
        junctions=[],
        labels=[],
        texts=[],
        circuit=circuit,
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-VIN", net="VIN", x=COL - 50.0, y=400.0),
            LayoutPowerSymbol(symbol_ref="PWR-GND", net="GND", x=COL + 50.0, y=400.0),
        ],
    )
    assert _run(correct).hard_violations == []

    # The unrotated tips are 50 units away on the y axis: a plan that forgot the
    # rotation leaves R1.1 with nothing on it, and the check says so.
    forgotten = _case(
        parts=rotated,
        segments=[],
        junctions=[],
        labels=[],
        texts=[],
        circuit=circuit,
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-VIN", net="VIN", x=COL, y=450.0),
            LayoutPowerSymbol(symbol_ref="PWR-GND", net="GND", x=COL, y=350.0),
        ],
    )
    found = _of(_run(forgotten), KIND_REQUIRED_PIN_NOT_CONNECTED)
    assert [item.objects for item in found] == [
        ("circuitSpec.nets[VIN]", "pins[R1.1]"),
        ("circuitSpec.nets[GND]", "pins[R1.2]"),
    ]


def test_a_mirrored_part_moves_a_left_pin_to_the_right():
    mirrored = [LayoutPart(
        part_id="U1", symbol_ref=IC, x=COL, y=400.0, mirror=True,
    )]
    circuit = CircuitSpec(
        parts=[SpecPart(id="U1", symbol_ref=IC)],
        nets=[
            SpecNet(id="IN", cls="signal", members=["U1.1"]),
            SpecNet(id="OUT", cls="signal", members=["U1.2"]),
            SpecNet(id="GND", cls="gnd", members=["U1.3"]),
        ],
    )
    right = _case(
        parts=mirrored, segments=[], junctions=[], labels=[], texts=[],
        circuit=circuit, profiles={IC: _ic_profile()},
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="P", net="IN", x=COL + 50.0, y=400.0),
            LayoutPowerSymbol(symbol_ref="P", net="OUT", x=COL - 50.0, y=400.0),
            LayoutPowerSymbol(symbol_ref="P", net="GND", x=COL, y=350.0),
        ],
    )
    assert _run(right).hard_violations == []

    wrong = _case(
        parts=mirrored, segments=[], junctions=[], labels=[], texts=[],
        circuit=circuit, profiles={IC: _ic_profile()},
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="P", net="IN", x=COL - 50.0, y=400.0),
            LayoutPowerSymbol(symbol_ref="P", net="OUT", x=COL + 50.0, y=400.0),
            LayoutPowerSymbol(symbol_ref="P", net="GND", x=COL, y=350.0),
        ],
    )
    # Both flags land on the *unmirrored* tips, so each pin is wired to the
    # other pin's net. The partition cannot see it — every node still holds one
    # pin — which is exactly why the naming half of constraint 1 exists.
    found = _of(_run(wrong), KIND_NETLIST_PARTITION)
    assert [item.objects for item in found] == [
        ("circuitSpec.nets[IN]", "pins[U1.1]"),
        ("circuitSpec.nets[OUT]", "pins[U1.2]"),
    ]
    assert "states the net name(s) 'OUT'" in found[0].evidence


# ------------------------------------------------------------ 2. dangling ends


def test_a_wire_end_in_mid_air_is_detected():
    """The tap is one step too long: its end lands on nothing.

    The label moves onto the tap's *span* rather than its end, which is what
    makes this case about the end and not about the label.
    """
    case = _case(
        segments=[
            LayoutSegment(net="MID", points=[(COL, 350.0), (COL, 250.0)]),
            LayoutSegment(net="MID", points=[(COL, 300.0), (COL + 100.0, 300.0)]),
        ],
        labels=[LayoutLabel(
            net="MID", text="MID", x=COL + 50.0, y=300.0,
            bbox=(COL + 50.0, 300.0, COL + 80.0, 320.0),
        )],
    )
    result = _run(case)
    found = _of(result, KIND_DANGLING_WIRE_END)
    assert [item.objects for item in found] == [("segments[1]",)]
    assert "end (200, 300)" in found[0].evidence
    assert len(result.hard_violations) == 1


def test_a_wire_end_on_a_power_symbol_is_not_dangling():
    """A wire may end on a real thing — a pin, a label, a flag or another wire."""
    case = _case(
        segments=_segments() + [
            LayoutSegment(net="VIN", points=[(COL, 450.0), (COL + 100.0, 450.0)]),
            LayoutSegment(net="VIN", points=[(COL, 450.0), (COL - 100.0, 450.0)]),
        ],
        power_symbols=_power_symbols() + [
            LayoutPowerSymbol(
                symbol_ref="PWR-VIN", net="VIN", x=COL + 100.0, y=450.0
            ),
            LayoutPowerSymbol(
                symbol_ref="PWR-VIN", net="VIN", x=COL - 100.0, y=450.0
            ),
        ],
    )
    assert _run(case).hard_violations == []


def test_an_open_interface_wire_still_needs_something_at_its_end():
    """052 §6 excuses the *net*, not a bare wire end.

    An open interface is a legitimate dangling net — but on paper it is a port,
    so the wire has to be named by the label (or port symbol) at its end. The
    finding says so, and the labelled version of the same wire passes.
    """
    circuit = _circuit(
        nets=[
            SpecNet(id="VIN", cls="power", members=["R1.1"]),
            SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
            SpecNet(id="GND", cls="gnd", members=["R2.2"]),
        ],
    )
    circuit.open_interfaces = [
        SpecOpenInterface(
            net="VIN", direction="input", role="IN", provenance="engineer_confirmed",
        )
    ]
    wire = LayoutSegment(net="VIN", points=[(COL, 450.0), (COL, 550.0)])

    bare = _run(_case(circuit=circuit, segments=_segments() + [wire]))
    found = _of(bare, KIND_DANGLING_WIRE_END)
    assert [item.objects for item in found] == [("segments[2]",)]
    assert "has to be named by a label or port at its end" in found[0].evidence

    labelled = _run(_case(
        circuit=circuit,
        segments=_segments() + [wire],
        labels=_labels() + [LayoutLabel(
            net="VIN", text="VIN", x=COL, y=550.0,
            bbox=(COL, 550.0, COL + 30.0, 570.0),
        )],
    ))
    assert labelled.hard_violations == []


# ------------------------------------------------------------- 3. junctions


def test_a_tee_without_a_declared_junction_is_detected():
    """Scenario: the tap lands mid-span and nothing says so."""
    result = _run(_case(junctions=[]))
    found = _of(result, KIND_UNDECLARED_JUNCTION)
    assert len(found) == 1
    assert set(found[0].objects) == {"segments[1]", "segments[0]"}
    assert "no junction is declared" in found[0].evidence
    assert len(result.hard_violations) == 1


def test_two_wires_that_cross_need_no_junction():
    """A plain crossing is not a connection, so it is not a missing dot.

    It is also the soft metric's unit: one crossing, counted with its point.
    """
    case = _case(
        segments=_segments() + [
            LayoutSegment(net="A", points=[(300.0, 100.0), (300.0, 600.0)]),
            LayoutSegment(net="B", points=[(200.0, 400.0), (400.0, 400.0)]),
        ],
        labels=_labels() + [
            LayoutLabel(net="A", text="A", x=300.0, y=100.0,
                        bbox=(300.0, 100.0, 330.0, 120.0)),
            LayoutLabel(net="A", text="A", x=300.0, y=600.0,
                        bbox=(300.0, 600.0, 330.0, 620.0)),
            LayoutLabel(net="B", text="B", x=200.0, y=400.0,
                        bbox=(200.0, 400.0, 230.0, 420.0)),
            LayoutLabel(net="B", text="B", x=400.0, y=400.0,
                        bbox=(400.0, 400.0, 430.0, 420.0)),
        ],
    )
    result = _run(case)
    assert result.hard_violations == []
    assert result.soft_metrics["crossings"] == 1.0
    assert result.soft_reasons["crossings"] == [
        "segments[2] x segments[3] at (300, 400)"
    ]


# ---------------------------------------------------------------- 4. bodies


def test_a_wire_crossing_a_foreign_body_is_detected():
    """Two findings since 147b, and they are different statements about one wire.

    The first is this test's subject (constraint 4). The second is that the same
    wire's **net name row** lands on `R2`: 147 modelled the row the host prints a
    named wire's name in (`_named_wire_rows`), and the fixture draws `X` from
    (0, 200) to (200, 200), i.e. straight through `R2`'s body — so the row the host
    anchors at that wire's midpoint, (100, 200)-(106.67, 210), is printed on the
    part as well. That is not a new rule catching the old fixture out: a drawing
    that runs a named wire through a body puts the name on the body, and the two
    lines each say which. The old expectation (`exactly one`) measured only the
    wire because the checker had no row model at all.
    """
    case = _case(
        segments=_segments() + [
            LayoutSegment(net="X", points=[(0.0, 200.0), (200.0, 200.0)]),
        ],
        labels=_labels() + [
            LayoutLabel(net="X", text="X", x=0.0, y=200.0,
                        bbox=(0.0, 200.0, 30.0, 220.0)),
            LayoutLabel(net="X", text="X", x=200.0, y=200.0,
                        bbox=(200.0, 200.0, 230.0, 220.0)),
        ],
    )
    result = _run(case)
    found = _of(result, KIND_WIRE_THROUGH_BODY)
    assert [item.objects for item in found] == [("segments[2]", "parts[R2]")]
    assert "may only reach a part through that part's own pin" in found[0].evidence
    rows = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in rows] == [("segments[2]", "parts[R2]")]
    assert "lands on the drawn extent of parts[R2]" in rows[0].evidence
    assert len(result.hard_violations) == 2, _kinds(result)


def test_a_wire_between_its_own_two_pins_may_enter_its_own_body():
    """"非两端器件" is the rule: the part at a segment's end is not a violation.

    That exemption is about the **wire** (constraint 4), and it still holds: the
    segment itself is reported by nothing here. What 147 added is a second
    statement about the same run — the host prints this wire's name (`MID`) in a
    row anchored at the wire's own midpoint, and that midpoint is inside `R1`, so
    the row is printed on the part. The old expectation (`no violations at all`)
    was written before the checker modelled a wire's own name; a wire that enters
    its own body legally can still put its name on the body, and that reading is
    the finding below.
    """
    file = _case(
        parts=[LayoutPart(
            part_id="R1", symbol_ref=RESISTOR, x=COL, y=400.0, reference="R1",
        )],
        segments=[LayoutSegment(net="MID", points=[(COL, 450.0), (COL, 350.0)])],
        junctions=[],
        labels=[],
        power_symbols=[],
        texts=[],
        circuit=CircuitSpec(
            parts=[SpecPart(id="R1", symbol_ref=RESISTOR, value="10k")],
            nets=[SpecNet(id="MID", cls="signal", members=["R1.1", "R1.2"])],
        ),
    )
    # The wire runs from tip to tip *through* the drawn body: legal, because
    # both of the segment's ends are this part's own pins.
    result = _run(file)
    assert _of(result, KIND_WIRE_THROUGH_BODY) == []
    assert _of(result, KIND_WIRE_ON_PIN_LINE) == []
    rows = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in rows] == [("segments[0]", "parts[R1]")]
    assert "'MID'" in rows[0].evidence, (
        "the row the host prints a wire's own name in is anchored at the wire's "
        "midpoint, which here is the middle of the part"
    )
    assert len(result.hard_violations) == 1, _kinds(result)


# ------------------------------------------------------------------ 5. text


def test_two_overlapping_text_boxes_are_detected():
    case = _case(texts=[
        LayoutText(kind="reference", text="R1", part_id="R1",
                   bbox=(COL + 20.0, 430.0, COL + 40.0, 450.0)),
        LayoutText(kind="value", text="10k", part_id="R1",
                   bbox=(COL + 30.0, 435.0, COL + 60.0, 455.0)),
    ])
    result = _run(case)
    found = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in found] == [("texts[0]", "texts[1]")]
    assert "'10k'" in found[0].evidence


def test_a_label_printed_over_a_value_is_detected():
    """A label is text: the two lists are one set of boxes."""
    texts = _texts()
    texts[2] = LayoutText(
        kind="value", text="10k", part_id="R1",
        bbox=(COL + 100.0, 300.0, COL + 130.0, 320.0),
    )
    result = _run(_case(texts=texts))
    found = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in found] == [("texts[2]", "labels[0]")]


def test_a_foreign_text_on_a_part_body_is_detected():
    case = _case(texts=[
        LayoutText(kind="note", text="keep out", part_id="R1",
                   bbox=(COL - 5.0, 190.0, COL + 5.0, 210.0)),
    ])
    result = _run(case)
    found = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in found] == [("texts[0]", "parts[R2]")]


def test_a_symbols_own_text_inside_its_own_body_is_not_reported():
    """A symbol draws its designator inside its own extent; that is not overlap."""
    case = _case(
        parts=[LayoutPart(
            part_id="R1", symbol_ref=RESISTOR, x=COL, y=400.0, reference="R1",
        )],
        segments=[],
        junctions=[],
        labels=[],
        power_symbols=[LayoutPowerSymbol(
            symbol_ref="PWR-VIN", net="VIN", x=COL, y=450.0,
        )],
        texts=[LayoutText(kind="reference", text="R1", part_id="R1",
                          bbox=(COL - 5.0, 395.0, COL + 5.0, 405.0))],
        circuit=CircuitSpec(
            parts=[SpecPart(id="R1", symbol_ref=RESISTOR, value="10k")],
            nets=[SpecNet(id="VIN", cls="power", members=["R1.1"])],
        ),
    )
    assert _run(case).hard_violations == []


# ------------------------------------------------------------ 6. page/keep-out


def test_something_leaving_the_page_is_detected():
    case = _case(page_box=(0.0, 0.0, 1000.0, 300.0))
    result = _run(case)
    found = _of(result, KIND_OUT_OF_PAGE)
    assert ("parts[R1]",) in [item.objects for item in found]
    assert any("leaves the page" in item.evidence for item in found)


def test_a_keep_out_region_is_respected():
    case = _case()
    result = check(
        case.plan, case.circuit, case.presentation, case.profiles,
        page_box=PAGE, keepouts=[(COL - 20.0, 180.0, COL + 20.0, 220.0)],
    )
    found = _of(result, KIND_OUT_OF_PAGE)
    assert [item.objects for item in found] == [("parts[R2]",)]
    assert "keepouts[0]" in found[0].evidence


def _detour_segments() -> list[LayoutSegment]:
    """The base divider with its tap redrawn as an L-shaped detour.

    One wire out of the junction on the chain, right, down and back to R2.1's
    tip — still one node, still named by the label (which sits mid-span on the
    horizontal run). What it adds is a *bounding box* far bigger than the line:
    the box sweeps the whole rectangle between the two runs, which is what the
    three keep-out cases below are about.
    """
    return [
        _segments()[0],
        LayoutSegment(net="MID", points=[
            (COL, 300.0), (COL + 300.0, 300.0),
            (COL + 300.0, 250.0), (COL, 250.0),
        ]),
    ]


def _bounds_of(points) -> tuple[float, float, float, float]:
    """The bounding box of a polyline, restated here so the cases stay independent."""
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _check_with_keepouts(keepouts: list) -> readability.CheckResult:
    """The detour case, checked against the given keep-outs and nothing else."""
    case = _case(segments=_detour_segments())
    return check(
        case.plan, case.circuit, case.presentation, case.profiles,
        page_box=PAGE, keepouts=keepouts,
    )


def test_a_wire_that_detours_around_a_keep_out_is_not_inside_it():
    """An L whose bounding box covers the keep-out while both runs pass it by.

    The bounding box of a polyline is not the polyline. Measuring the box would
    report this wire as "inside" a region it never entered — and it would make
    "route around a keep-out" unsatisfiable, because an L-shaped detour's box
    *always* covers whatever it went around. The wire half of constraint 6 is
    therefore measured per sub-segment, with constraint 4's own clip test.
    """
    keep = (COL + 100.0, 255.0, COL + 200.0, 295.0)
    left, bottom, right, top = _bounds_of(_detour_segments()[1].points)
    assert left < keep[0] and right > keep[2] and bottom < keep[1] and top > keep[3], (
        "the case is only worth checking while the bounding box really does "
        f"cover the keep-out: box {(left, bottom, right, top)}, keep-out {keep}"
    )
    assert _check_with_keepouts([keep]).hard_violations == []


def test_a_sub_segment_that_really_enters_a_keep_out_is_reported_once():
    """The same shape, with the keep-out moved onto one sub-segment.

    Exactly one finding, naming the segment that entered — the per-sub-segment
    rule is strict, not lenient: a detour that really cuts into a keep-out is
    still a wire inside a reserved region, and the evidence says which one and
    where it was measured.
    """
    keep = (COL + 290.0, 260.0, COL + 310.0, 290.0)
    result = _check_with_keepouts([keep])
    found = _of(result, KIND_OUT_OF_PAGE)
    assert [item.objects for item in found] == [("segments[1]",)]
    assert "segments[1]" in found[0].evidence
    assert "keepouts[0]" in found[0].evidence
    assert "runs through keep-out" in found[0].evidence
    assert "near (400, 275)" in found[0].evidence
    assert len(result.hard_violations) == 1, _kinds(result)


def test_a_wire_riding_a_keep_out_edge_is_on_the_border_not_inside_it():
    """The boundary口径 is constraint 4's: a positive-length interior overlap.

    A wire running exactly along a keep-out edge is on the border of the region,
    not in it — the same rule that lets a wire run along a part's outline
    without "crossing" the body. The control below moves the keep-out one unit
    towards the wire, so where the boundary actually is is pinned too: the rule
    is a boundary, not a licence to ignore the region.

    147b: the wire half is unchanged and the *region* half gained one box. The
    host prints a wire's own net name in a row anchored at the wire's longest run's
    midpoint, and here that midpoint (250, 300) is exactly on the keep-out's top
    edge — so the row grows **down into** the band, which the wire beside it only
    rides. The old expectation (`nothing in this region at all`) predates 147
    modelling a wire's own name row; the wire's own finding is still absent, which
    is what the first assertion now says, and the row's is the second.
    """
    on_the_edge = (COL + 150.0, 300.0, COL + 220.0, 330.0)
    one_unit_in = (COL + 150.0, 299.0, COL + 220.0, 330.0)

    def the_wire_in_the_region(result) -> list:
        """The findings about the **wire** entering the region, row findings out.

        A wire's own name row carries the wire's own object name (`segments[1]`),
        so the two are told apart by the evidence's own wording: a sub-segment that
        cuts into the region "runs through keep-out", a box that lies inside it
        "is inside keep-out".
        """
        return [
            item for item in _of(result, KIND_OUT_OF_PAGE)
            if "runs through keep-out" in item.evidence
        ]

    # The *wire* is on the border, so the wire is not in the region — that is this
    # test's subject and it is unchanged. 147 added a second box in that region
    # that the fixture did not have: the host prints this net's name (`MID`) in a
    # row anchored at the longest run's midpoint, (250, 300), and the row grows
    # *down* into the band (250, 300)-(268.33, 310) — inside the keep-out the wire
    # only rides. The row is a text box like any other and a reserved region is
    # reserved against it too, so the finding is reported and named as text.
    assert the_wire_in_the_region(_check_with_keepouts([on_the_edge])) == []
    rows = _of(_check_with_keepouts([on_the_edge]), KIND_OUT_OF_PAGE)
    assert [item.objects for item in rows] == [("segments[1]",)]
    assert "[250, 300, 268.33, 310] is inside keep-out" in rows[0].evidence
    found = the_wire_in_the_region(_check_with_keepouts([one_unit_in]))
    assert [item.objects for item in found] == [("segments[1]",)]
    assert "runs through keep-out" in found[0].evidence


def test_without_a_page_box_the_page_boundary_is_not_judged():
    """The plan carries no page size, so an unstated page is *not* evaluated."""
    assert _run(_case(page_box=None)).hard_violations == []
    assert _run(_case(page_box=(0.0, 0.0, 1000.0, 300.0))).hard_violations


def test_a_page_box_that_is_not_a_box_is_refused():
    case = _case()
    with pytest.raises(ReadabilityError):
        check(
            case.plan, case.circuit, case.presentation, case.profiles,
            page_box=(1000.0, 800.0, 0.0, 0.0),
        )


# ------------------------------------------------------------ 7. user locks


def test_a_lock_the_plan_ignores_is_detected():
    """Scenario 12: a conflicting lock is reported, never silently dropped."""
    case = _case(presentation=_presentation(locks=[UserLock("R2", 50.0, 200.0, 0.0)]))
    result = _run(case)
    found = _of(result, KIND_USER_LOCK_VIOLATED)
    assert [item.objects for item in found] == [
        ("presentationSpec.userLocks[R2]", "parts[R2]"),
    ]
    assert "x: locked 50, placed 100" in found[0].evidence
    assert len(result.hard_violations) == 1


def test_a_lock_on_a_part_the_plan_does_not_place_is_detected():
    case = _case(presentation=_presentation(locks=[UserLock("R9", 0.0, 0.0, 0.0)]))
    found = _of(_run(case), KIND_USER_LOCK_VIOLATED)
    assert [item.objects for item in found] == [("presentationSpec.userLocks[R9]",)]
    assert "does not place" in found[0].evidence


def test_a_lock_on_the_rotation_is_compared_too():
    case = _case(presentation=_presentation(locks=[UserLock("R2", COL, 200.0, 90.0)]))
    found = _of(_run(case), KIND_USER_LOCK_VIOLATED)
    assert "rotation: locked 90, placed 0" in found[0].evidence


def test_a_lock_that_matches_is_not_a_violation():
    case = _case(presentation=_presentation(locks=[UserLock("R1", COL, 400.0, 0.0)]))
    assert _run(case).hard_violations == []


# -------------------------------------------------------------------- 8. NC


def test_an_nc_pin_the_drawing_wires_up_is_detected():
    """Scenario 11: "NC 被接". The stray wire is the only defect *it* adds.

    147b added the second line, and it is about the same stray wire: `MID`'s name
    row is anchored at that wire's midpoint — (100, 200), which is inside `R2` — so
    the name is printed on the part. "The stray wire is the only defect" was true of
    the wire while the checker had no model of a wire's own name; the row is the
    host's typography on top of it, and one drawing can be wrong twice.
    """
    case = _case(
        circuit=_circuit(
            nets=[
                SpecNet(id="VIN", cls="power", members=["R1.1"]),
                SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
            ],
            nc=[SpecNoConnect(pin="R2.2", provenance="engineer_confirmed")],
        ),
        segments=_segments() + [
            LayoutSegment(net="MID", points=[(COL, 150.0), (COL, 250.0)]),
        ],
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-VIN", net="VIN", x=COL, y=450.0),
        ],
    )
    result = _run(case)
    found = _of(result, KIND_NC_PIN_CONNECTED)
    assert [item.objects for item in found] == [
        ("circuitSpec.nc[R2.2]", "pins[R2.2]"),
    ]
    assert "pins[R1.2], pins[R2.1]" in found[0].evidence
    rows = _of(result, KIND_TEXT_OVERLAP)
    assert [item.objects for item in rows] == [("segments[2]", "parts[R2]")]
    assert "'MID'" in rows[0].evidence
    assert len(result.hard_violations) == 2, _kinds(result)


def test_an_nc_pin_carrying_a_power_flag_is_detected():
    case = _case(
        circuit=_circuit(
            nets=[
                SpecNet(id="VIN", cls="power", members=["R1.1"]),
                SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
            ],
            nc=[SpecNoConnect(pin="R2.2", provenance="engineer_confirmed")],
        ),
    )
    found = _of(_run(case), KIND_NC_PIN_CONNECTED)
    assert [item.objects for item in found] == [
        ("circuitSpec.nc[R2.2]", "pins[R2.2]"),
    ]
    assert "power symbol sits on its tip" in found[0].evidence


def test_an_nc_pin_left_alone_is_not_a_violation():
    """An explicit NC pin with nothing on it is the drawing doing its job."""
    case = _case(
        circuit=_circuit(
            nets=[
                SpecNet(id="VIN", cls="power", members=["R1.1"]),
                SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
            ],
            nc=[SpecNoConnect(pin="R2.2", provenance="engineer_confirmed")],
        ),
        power_symbols=[
            LayoutPowerSymbol(symbol_ref="PWR-VIN", net="VIN", x=COL, y=450.0),
        ],
    )
    assert _run(case).hard_violations == []


# --------------------------------------------------------- 9. required pins


def test_a_declared_pin_with_nothing_attached_is_detected():
    case = _case(power_symbols=[
        LayoutPowerSymbol(symbol_ref="PWR-GND", net="GND", x=COL, y=150.0),
    ])
    result = _run(case)
    found = _of(result, KIND_REQUIRED_PIN_NOT_CONNECTED)
    assert [item.objects for item in found] == [
        ("circuitSpec.nets[VIN]", "pins[R1.1]"),
    ]
    assert "nothing is attached" in found[0].evidence
    assert len(result.hard_violations) == 1


def test_a_declared_pin_the_drawing_cannot_show_is_detected():
    """Two flavours of "absent": the symbol has no such pin, the part is unplaced."""
    case = _case(circuit=_circuit(nets=_circuit().nets + [
        SpecNet(id="SPARE", cls="other", members=["R1.3", "R9.1"]),
    ]))
    found = _of(_run(case), KIND_REQUIRED_PIN_NOT_CONNECTED)
    assert [item.objects for item in found] == [
        ("circuitSpec.nets[SPARE]", "pins[R1.3]"),
        ("circuitSpec.nets[SPARE]", "pins[R9.1]"),
    ]
    assert "profile of its symbol 'R-VERT' has no pin 3" in found[0].evidence
    assert "part R9 is not placed" in found[1].evidence


# ------------------------------------------------- 11. the whole scenario, once


def test_scenario_11_all_three_planted_defects_are_caught():
    """053 §五 #11 in one place: short / wrong pin / NC connected.

    Each variant differs from the base case in exactly one place, so the kind
    that appears is the kind that defect produces.
    """
    nc_circuit = _circuit(
        nets=[
            SpecNet(id="VIN", cls="power", members=["R1.1"]),
            SpecNet(id="MID", cls="signal", members=["R1.2", "R2.1"]),
        ],
        nc=[SpecNoConnect(pin="R2.2", provenance="engineer_confirmed")],
    )
    cases = {
        "short": _case(segments=_segments() + [
            LayoutSegment(net="GND", points=[(COL, 150.0), (COL, 250.0)]),
        ]),
        # The wire from R2.1 runs to R1.1 (VIN) instead of R1.2 (MID).
        "wrong-pin": _case(segments=[
            LayoutSegment(net="MID", points=[(COL, 450.0), (COL, 250.0)]),
            LayoutSegment(net="MID", points=[(COL, 300.0), (COL + 100.0, 300.0)]),
        ]),
        "nc-connected": _case(
            circuit=nc_circuit,
            segments=_segments() + [
                LayoutSegment(net="MID", points=[(COL, 150.0), (COL, 250.0)]),
            ],
        ),
    }
    expected = {
        "short": {KIND_NETLIST_PARTITION},
        "wrong-pin": {KIND_NETLIST_PARTITION},
        "nc-connected": {KIND_NC_PIN_CONNECTED},
    }
    for name, case in cases.items():
        result = _run(case)
        assert not result.ok, f"{name}: the checker delivered this plan"
        assert expected[name] <= set(_kinds(result)), (name, _kinds(result))

    # The wrong-pin plan really does name the pin that should have been wired.
    wrong = _run(cases["wrong-pin"])
    named = {path for item in wrong.hard_violations for path in item.objects}
    assert "pins[R1.2]" in named and "pins[R1.1]" in named


# ------------------------------------------------------------------- ordering


def test_two_runs_of_one_plan_give_the_same_findings():
    case = _case(
        junctions=[],
        segments=_segments() + [
            LayoutSegment(net="GND", points=[(COL, 150.0), (COL, 250.0)]),
        ],
    )
    first, second = _run(case), _run(case)
    assert first.hard_violations == second.hard_violations
    assert first.soft_metrics == second.soft_metrics
    assert first.soft_reasons == second.soft_reasons


def test_findings_come_out_in_constraint_order():
    case = _case(
        junctions=[],
        presentation=_presentation(locks=[UserLock("R2", 50.0, 200.0, 0.0)]),
        segments=_segments() + [
            LayoutSegment(net="X", points=[(0.0, 200.0), (200.0, 200.0)]),
        ],
        labels=_labels() + [
            LayoutLabel(net="X", text="X", x=0.0, y=200.0,
                        bbox=(0.0, 200.0, 30.0, 220.0)),
            LayoutLabel(net="X", text="X", x=200.0, y=200.0,
                        bbox=(200.0, 200.0, 230.0, 220.0)),
        ],
    )
    result = _run(case)
    order = [HARD_KINDS.index(item.kind) for item in result.hard_violations]
    assert order == sorted(order), _kinds(result)
    assert len(set(_kinds(result))) >= 3, _kinds(result)


def test_a_finding_renders_as_one_line_for_the_evidence_slot():
    """`LayoutEvidence.hard_violations` is a list of strings: one line each."""
    found = _of(_run(_case(junctions=[])), KIND_UNDECLARED_JUNCTION)[0]
    rendered = found.render()
    assert rendered.startswith("[undeclared-junction] segments[1] + segments[0]:")
    assert "\n" not in rendered


def test_a_non_positive_grid_is_refused():
    case = _case()
    for grid in (0, -5.0, True, "5"):
        with pytest.raises(ReadabilityError):
            check(
                case.plan, case.circuit, case.presentation, case.profiles,
                page_box=PAGE, grid=grid,
            )


# --------------------------------------------------------------- soft metrics


def test_soft_metrics_are_raw_values_and_reasons_under_their_own_keys():
    result = _run(_case())
    assert set(result.soft_metrics) == {
        "crossings",
        "bends",
        "wire_length",
        "unaligned_part_pairs",
        "min_text_gap",
        "occupied_ratio",
        "whitespace_ratio",
    }
    assert set(result.soft_reasons) <= set(result.soft_metrics)
    assert all(lines for lines in result.soft_reasons.values())
    assert "score" not in result.soft_metrics, "053 §七: 软指标无总分"


def test_the_base_case_measures_what_it_should():
    result = _run(_case())
    assert result.soft_metrics["crossings"] == 0.0
    assert result.soft_metrics["bends"] == 0.0
    assert result.soft_metrics["wire_length"] == 200.0
    assert result.soft_metrics["unaligned_part_pairs"] == 0.0


def test_bends_are_counted_in_canvas_units_of_wire():
    """A Z-shaped route between the same two pins: two bends, 300 units."""
    case = _case(
        parts=[LayoutPart(
            part_id="R1", symbol_ref=RESISTOR, x=COL, y=400.0, reference="R1",
        )],
        segments=[LayoutSegment(
            net="MID",
            points=[(COL, 450.0), (COL + 100.0, 450.0),
                    (COL + 100.0, 350.0), (COL, 350.0)],
        )],
        junctions=[],
        labels=[],
        power_symbols=[],
        texts=[],
        circuit=CircuitSpec(
            parts=[SpecPart(id="R1", symbol_ref=RESISTOR, value="10k")],
            nets=[SpecNet(id="MID", cls="signal", members=["R1.1", "R1.2"])],
        ),
    )
    result = _run(case)
    assert result.hard_violations == []
    assert result.soft_metrics["bends"] == 2.0
    assert result.soft_metrics["crossings"] == 0.0
    assert result.soft_metrics["wire_length"] == 300.0
    assert result.soft_reasons["bends"] == ["segments[0] (net 'MID'): 2 bend(s)"]


def test_parts_of_one_module_sharing_neither_row_nor_column_are_counted():
    case = _case(
        parts=_parts() + [LayoutPart(
            part_id="R3", symbol_ref=RESISTOR, x=COL + 200.0, y=200.0,
            reference="R3",
        )],
        power_symbols=_power_symbols() + [LayoutPowerSymbol(
            symbol_ref="PWR-VOUT", net="VOUT", x=COL + 200.0, y=250.0,
        )],
        circuit=_circuit(
            parts=[
                SpecPart(id="R1", symbol_ref=RESISTOR, value="10k"),
                SpecPart(id="R2", symbol_ref=RESISTOR, value="10k"),
                SpecPart(id="R3", symbol_ref=RESISTOR, value="10k"),
            ],
            nets=_circuit().nets + [
                SpecNet(id="VOUT", cls="signal", members=["R3.1"]),
            ],
        ),
        presentation=_presentation(modules=[
            PresentationModule(id="main", parts=["R1", "R2", "R3"], role="divider"),
        ]),
    )
    result = _run(case)
    # R3 shares R2's row (dy = 0), so only the R1/R3 pair is unaligned.
    assert result.hard_violations == []
    assert result.soft_metrics["unaligned_part_pairs"] == 1.0
    assert result.soft_reasons["unaligned_part_pairs"] == [
        "modules[main]: parts[R1] and parts[R3] share neither x nor y "
        "(dx=-200, dy=200, grid=5)"
    ]


def test_text_spacing_and_occupancy_are_measured_in_canvas_units():
    result = _run(_case())
    # Closest pair: the R1 designator and its value, 15 units apart.
    assert result.soft_metrics["min_text_gap"] == 15.0
    assert "texts[0] and texts[2]: 15 units apart" in result.soft_reasons[
        "min_text_gap"
    ][0]
    # Two bodies (20x40 each), four text/label boxes, and — since 147 — the two
    # rows the host prints this net's own name in: `MID` is not carried by a power
    # flag, so its two wires each print a name, at (100, 300) growing down (18.33
    # units wide) and at (150, 300) growing right (18.33 units wide). 3300 +
    # 2 x 183.3 = 3666.6 units^2 of 800000. The old expectation counted the boxes
    # the *plan* declares; a wire's own name is a box the plan does not declare and
    # the page still carries, which is what 147 put into this set.
    assert result.soft_metrics["occupied_ratio"] == pytest.approx(3666.6 / 800000.0)
    assert "8 box(es) cover 3666.6 units^2" in result.soft_reasons[
        "whitespace_ratio"
    ][0]
    assert result.soft_metrics["whitespace_ratio"] == pytest.approx(
        1.0 - 3666.6 / 800000.0
    )
    assert "800000 units^2" in result.soft_reasons["whitespace_ratio"][0]


def test_metrics_that_cannot_be_measured_say_so():
    no_page = _run(_case(page_box=None))
    assert no_page.soft_metrics["whitespace_ratio"] == UNMEASURED
    assert "no page_box was given" in no_page.soft_reasons["whitespace_ratio"][0]

    # One text box on the whole canvas, so there is no pair to measure. The wires
    # go too: since 147 every named wire that no power flag names carries a row the
    # host prints (`_named_wire_rows`), and the base case's two `MID` wires would
    # put two more boxes on this page — a gap of 40 between them, which is a
    # measurement of the fixture rather than of "one text and nothing else".
    one_text = _run(_case(segments=[], texts=[
        LayoutText(kind="reference", text="R1", part_id="R1",
                   bbox=(COL + 20.0, 430.0, COL + 40.0, 450.0)),
    ], labels=[]))
    assert one_text.soft_metrics["min_text_gap"] == UNMEASURED
    assert "cannot measure" in one_text.soft_reasons["min_text_gap"][0]


def test_wires_that_merely_touch_are_not_counted_as_crossings():
    """The base case's tee and its shared wire end are not crossings.

    A positive control for the crossing rule: a shared endpoint is a
    connection, not an intersection, so the counter stays at zero and reports
    no reason at all.
    """
    result = _run(_case())
    assert result.soft_metrics["crossings"] == 0.0
    assert "crossings" not in result.soft_reasons


# ------------------------------------------------------------------- refusals


def test_a_part_whose_symbol_has_no_profile_is_refused():
    """A checker that cannot see a part's pins may not report "no violations"."""
    case = _case()
    with pytest.raises(ReadabilityError) as info:
        check(
            case.plan, case.circuit, case.presentation, {}, page_box=PAGE,
        )
    assert "no profile for it was given" in str(info.value)


def test_profiles_may_be_an_iterable_of_profiles():
    case = _case()
    result = check(
        case.plan, case.circuit, case.presentation, [_resistor_profile()],
        page_box=PAGE,
    )
    assert result.ok


def test_a_profile_mapping_under_the_wrong_key_is_refused():
    case = _case()
    with pytest.raises(ReadabilityError) as info:
        check(
            case.plan, case.circuit, case.presentation, {"other": _resistor_profile()},
            page_box=PAGE,
        )
    assert "keyed by the symbol it describes" in str(info.value)
