"""Revision-3/4 hard constraints, pinned against the layout engine.

Each test names the constraint it pins. The crown test runs the whole
golden board through ``generate_plan`` and demands ZERO violations — that
is the gate the draw flow refuses to execute past.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import p4_replay  # noqa: E402  (tools/ replay of the v1 draw)

from boardwise.core.candidate import candidate_from_geometry  # noqa: E402
from boardwise.core.compare import compare_models, reconcile_names  # noqa: E402
from boardwise.core.model import is_ground_net  # noqa: E402
from boardwise.engines import layout  # noqa: E402
from boardwise.engines.generate import (  # noqa: E402
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import (  # noqa: E402
    build_pin_offsets,
    build_schematic_model,
    collect_part_placements,
    collect_symbol_defs,
)

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ch340_golden.epro2"
GEO_DUMP = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ch340_p1_geometry.json"


_GOLDEN_PLAN_CACHE: dict = {}


def _golden_plan():
    """The golden plan, computed once.

    ``generate_plan`` is a few seconds of grid search on this board and a
    dozen tests read the same plan — recomputing it per test turned a
    seconds-long suite into a minute-long one (measured with
    ``pytest --durations``). The plan is pure, so caching it cannot hide a
    regression; the dedicated stability test still builds it twice.
    """
    if "plan" not in _GOLDEN_PLAN_CACHE:
        golden = build_schematic_model(GOLDEN)
        offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
        _GOLDEN_PLAN_CACHE["plan"] = (golden, offsets, generate_plan(golden, offsets))
    return _GOLDEN_PLAN_CACHE["plan"]


# --------------------------------------------------------------------------
# constraint 1: placement bounds, title block, non-overlap
# --------------------------------------------------------------------------


def test_golden_plan_has_zero_violations():
    """The crown gate: the whole board, all five constraints, clean."""
    _golden, _offsets, plan = _golden_plan()
    assert plan.violations == [], [v.render() for v in plan.violations]


def test_golden_boxes_stay_inside_the_frame_and_clear_of_the_title_block():
    golden, offsets, _plan = _golden_plan()
    _host, order = __import__(
        "boardwise.engines.generate", fromlist=["_layout_order"]
    )._layout_order(golden)
    placements = layout.plan_placement(offsets, order)
    title = layout.Rect(*layout.TITLE_BLOCK)
    for p in placements:
        assert p.bbox is not None
        assert p.bbox.x0 >= layout.FRAME and p.bbox.y0 >= layout.FRAME
        assert p.bbox.x1 <= layout.SHEET_WIDTH - layout.FRAME
        assert p.bbox.y1 <= layout.SHEET_HEIGHT - layout.FRAME
        assert not p.bbox.intersects(title), p.designator


def test_golden_boxes_never_overlap():
    golden, offsets, _plan = _golden_plan()
    _host, order = __import__(
        "boardwise.engines.generate", fromlist=["_layout_order"]
    )._layout_order(golden)
    placements = layout.plan_placement(offsets, order)
    boxes = [p.bbox for p in placements if p.bbox]
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            assert not boxes[i].intersects(boxes[j])


def test_placement_wraps_before_running_off_the_right_edge():
    """A component that does not fit the row wraps to the next one."""
    offsets = {
        "A": {"1": (0.0, 0.0), "2": (1000.0, 0.0)},  # 1040-wide box
        "B": {"1": (0.0, 0.0), "2": (1000.0, 0.0)},
    }
    placements = layout.plan_placement(offsets, ["A", "B"])
    a, b = placements
    assert not a.bbox.intersects(b.bbox)
    assert a.bbox.y1 <= b.bbox.y0, "B must be on a later row: A fills the width"


# --------------------------------------------------------------------------
# constraints 2/3: wire endpoints, Manhattan, box crossings
# --------------------------------------------------------------------------


def test_wire_endpoints_are_exactly_pin_tips():
    _golden, offsets, plan = _golden_plan()
    tips = {
        (place.designator, number): (place.x + dx, place.y + dy)
        for place in plan.geometry
        for number, (dx, dy) in offsets.get(place.designator, {}).items()
    }
    for wire in plan.wires:
        for endpoint in (wire.points[0], wire.points[-1]):
            assert endpoint in set(tips.values()), (
                f"net {wire.net} endpoint {endpoint} is not a pin tip"
            )


def test_every_wire_segment_is_manhattan():
    _golden, _offsets, plan = _golden_plan()
    for wire in plan.wires:
        for (ax, ay), (bx, by) in zip(wire.points, wire.points[1:]):
            assert abs(ax - bx) < 1e-9 or abs(ay - by) < 1e-9, (wire.net, (ax, ay), (bx, by))


def test_wires_never_cross_a_foreign_box():
    _golden, _offsets, plan = _golden_plan()
    through = [v for v in plan.violations if v.code == "WIRE_THROUGH_BOX"]
    assert through == []


# --------------------------------------------------------------------------
# constraints 4/5: annotation attachment and clearance
# --------------------------------------------------------------------------


def test_every_net_annotation_has_an_attach_point_on_its_wire():
    _golden, _offsets, plan = _golden_plan()
    assert plan.net_names, "the golden board has nets to name"
    for step in plan.net_names:
        on_wire = any(
            _point_on_run((step.x, step.y), wire.points) for wire in plan.wires
        )
        assert on_wire, f"net {step.net} annotation at {step.x, step.y} floats"


def test_labels_keep_clearance_from_foreign_boxes():
    _golden, _offsets, plan = _golden_plan()
    close = [v for v in plan.violations if v.code == "LABEL_TOO_CLOSE"]
    assert close == []


def _point_on_run(point, run) -> bool:
    for (ax, ay), (bx, by) in zip(run, run[1:]):
        if abs(ax - bx) < 1e-9:
            if abs(point[0] - ax) < 0.51 and min(ay, by) <= point[1] <= max(ay, by):
                return True
        elif abs(ay - by) < 1e-9:
            if abs(point[1] - ay) < 0.51 and min(ax, bx) <= point[0] <= max(ax, bx):
                return True
    return False


def test_no_cross_net_endpoint_ever_touches_a_foreign_wire():
    _golden, _offsets, plan = _golden_plan()
    shorts = [v for v in plan.violations if v.code == "CROSS_NET_SHORT"]
    assert shorts == []


# --------------------------------------------------------------------------
# revision 4: the geometry path reproduces the golden board per pin
# --------------------------------------------------------------------------


def test_geometry_path_calibration_zero_real_differences():
    golden = build_schematic_model(GOLDEN)
    geo = __import__("json").loads(GEO_DUMP.read_text(encoding="utf-8"))
    all_defs = collect_symbol_defs(GOLDEN)
    symbol_defs = {
        des: all_defs[comp.uid]
        for des, comp in golden.components.items()
        if comp.uid in all_defs
    }
    part_positions = collect_part_placements(GOLDEN)
    candidate = candidate_from_geometry(
        geo, symbol_defs=symbol_defs, part_positions=part_positions
    )
    assert set(candidate.components) == set(golden.components)
    report = compare_models(golden, reconcile_names(candidate, golden))
    real = [
        d for d in report.component_differences
        if d.golden.strip() and d.candidate.strip()
    ]
    assert not real, [d.render() for d in real]
    assert not report.net_differences
    assert not report.pin_differences


def test_strip_dangling_nets_treats_single_member_nets_as_open():
    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    for net in golden.nets.values():
        assert len(net.pins) >= 2, f"net {net.name} still dangles"
    # the pins that lost their dangling net are now openly unconnected
    open_pins = {
        (des, p.number)
        for des, comp in golden.components.items()
        for p in comp.pins
        if p.net is None
    }
    assert ("U1", "10") in open_pins, "U1.10's leftover wire stub is not a connection"


# --------------------------------------------------------------------------
# net role: the layout's ground decision is the model's, and VEE is not ground
# --------------------------------------------------------------------------


def test_the_layout_does_not_keep_its_own_ground_list():
    """One ground list, and it lives in ``core.model`` (M0-P0c).

    The layout used to carry a second regex beside ``is_ground_net``. The two
    had already drifted — the regex lacked SGND/EGND and both listed VEE — so
    this pins the property rather than the spelling: the layout's answer *is*
    the model's answer, name for name. A name where they disagree is a second
    implementation growing back.
    """
    for name in (
        "GND", "gnd", "GNDA", "AGND", "DGND", "PGND", "EGND", "SGND", "VSS",
        "VEE", "vee", "VEE-5V", "-5V", "VM", "+24V", "VCC", "VDD", "3V3", "RX",
    ):
        ground = layout._net_kind(name) == "Ground"
        assert ground == is_ground_net(name), name


def test_vee_is_not_given_a_ground_symbol():
    """A negative supply is not a ground, so the plan must not flag it as one.

    Before M0-P0c a net named VEE was classified ``Ground`` and therefore got a
    ground flag hung off it — a symbol that says "this is 0 V" attached to a
    rail that is not. It is now an ordinary unnamed-role net: wired, named as
    text, flagged by nothing.
    """
    assert layout._net_kind("VEE") == "port"
    assert layout._net_kind("VEE-5V") == "port"


# --------------------------------------------------------------------------
# the P4 quantified bug list: replay of the 2026-09-13 21:51 v1 draw
# --------------------------------------------------------------------------


def test_v1_replay_surfaces_every_defect_class():
    """The validator must count, not vibe: all seven defect classes of the
    drawn P4 page come out of the deterministic v1 replay."""
    golden = build_schematic_model(GOLDEN)
    file_offsets = build_pin_offsets(GOLDEN)
    placements, routes, true_tips = p4_replay.replay_v1(golden, file_offsets)
    violations = layout.validate_full(golden, placements, routes, true_tips)
    codes = {v.code for v in violations}
    assert {"OUT_OF_SHEET", "WIRE_OUT_OF_SHEET", "WIRE_THROUGH_BOX",
            "ENDPOINT_NOT_TERMINAL", "FLAG_NOT_ON_WIRE", "CROSS_NET_SHORT"} <= codes
    # the sign bug is countable: v1's mirrored endpoints are not pin tips
    bad_endpoints = [v for v in violations if v.code == "ENDPOINT_NOT_TERMINAL"]
    assert len(bad_endpoints) >= 10
