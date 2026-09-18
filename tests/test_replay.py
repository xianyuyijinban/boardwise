"""006b: golden-layout replay, the measured sheet frame, and the annotation lint.

Pure and offline — no bridge, no editor. The golden fixture is the same
``ch340_golden.epro2`` the rest of the suite uses, which is what makes the
central assertion possible: replaying the *human's* geometry must pass the
five hard constraints with **zero** violations. Every false row this test
suite found on the way there (19 box overlaps, 6 cross-net shorts, 13 floating
endpoints) was a defect in the *model*, not in the drawing — the same
"violations here mean fix the transform, not the geometry" rule the task
states.
"""

from __future__ import annotations

import pytest

from boardwise.engines import layout as L
from boardwise.engines.generate import strip_dangling_nets
from boardwise.engines.replay import (
    OFFSET_GRID,
    build_replay_plan,
    place_offset,
    sheet_frame_from_bbox,
    sheet_frame_from_geometry,
)
from boardwise.parsers.schematic import (
    _chain_segments,
    build_pin_offsets,
    build_schematic_model,
    collect_page_layout,
    collect_symbol_bodies,
)

GOLDEN = "tests/fixtures/ch340_golden.epro2"


@pytest.fixture(scope="module")
def page():
    return collect_page_layout(GOLDEN)


@pytest.fixture(scope="module")
def bodies():
    return collect_symbol_bodies(GOLDEN)


@pytest.fixture(scope="module")
def model():
    return strip_dangling_nets(build_schematic_model(GOLDEN))


@pytest.fixture(scope="module")
def offsets():
    return build_pin_offsets(GOLDEN)


@pytest.fixture(scope="module")
def frame(page):
    return sheet_frame_from_geometry(
        {}, declared=page.sheet_attrs, origin=page.sheet_origin
    )


# --------------------------------------------------------------------------
# layout extraction
# --------------------------------------------------------------------------


def test_page_layout_reads_the_humans_geometry(page):
    assert len(page.parts) == 17
    assert len(page.flags) == 17
    kinds = {}
    for flag in page.flags:
        kinds.setdefault((flag.kind, flag.net), 0)
        kinds[(flag.kind, flag.net)] += 1
    assert kinds == {("Ground", "GND"): 12, ("Power", "+5V"): 3, ("Power", "VCC"): 2}


def test_only_wire_groups_become_runs(page):
    """33 WIRE heads own 33 groups; the leftover 7 groups are symbol graphics.

    The rule (documented in the parser) is "the next LINE after a WIRE head
    owns that group", corroborated by every NET attribute's parentId being one
    of those groups. Replaying a symbol's pin-lead graphics as a wire would be
    an invisible corruption, so the count is pinned here.
    """
    groups = {wire.group for wire in page.wires}
    assert len(groups) == 33
    assert len(page.wires) == 45, "a few wires branch and split into runs"
    for wire in page.wires:
        assert len(wire.points) >= 2
        for a, b in zip(wire.points, wire.points[1:]):
            assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9, (wire.group, a, b)


def test_visible_labels_are_only_the_named_ones(page):
    nets = sorted(label.net for label in page.labels)
    assert nets == ["D+", "D+", "D+", "D-", "D-", "D-", "RX", "RX", "TX", "TX"]


def test_sheet_declaration_is_carried(page):
    assert page.sheet_attrs["Page Size"] == "A4"
    assert page.sheet_attrs["Width"] == "1170"
    assert page.sheet_attrs["Height"] == "825"
    assert page.sheet_origin == (0.0, 0.0)


def test_chain_segments_splits_a_branch_and_keeps_a_straight_run():
    straight = [((0.0, 0.0), (10.0, 0.0)), ((10.0, 0.0), (20.0, 0.0))]
    assert _chain_segments(straight) == [[(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]]

    tee = [
        ((0.0, 0.0), (10.0, 0.0)),
        ((10.0, 0.0), (20.0, 0.0)),
        ((10.0, 0.0), (10.0, -10.0)),
    ]
    runs = _chain_segments(tee)
    assert len(runs) == 2, "a branch cannot be one polyline"
    assert sum(len(run) - 1 for run in runs) == 3, "every segment is used exactly once"


def test_chain_segments_drops_zero_length_placeholders():
    assert _chain_segments([((5.0, 5.0), (5.0, 5.0))]) == []


# --------------------------------------------------------------------------
# symbol bodies and part boxes
# --------------------------------------------------------------------------


def test_symbol_bodies_are_measured_rectangles(bodies):
    assert bodies["0bbdf9b626f3f7d7"] == (-30.0, -45.0, 30.0, 45.0)  # CH340G
    assert bodies["a4bda4074602a77a"] == (-20.0, -20.0, 20.0, 20.0)  # crystal
    # a passive draws its plates and leads as POLYs; the body still exists
    assert bodies["01346f7ca9e26bb1"] == (-5.0, -8.0, 5.0, 8.0)


def test_body_boxes_do_not_overlap_on_the_human_board(page, bodies, offsets):
    """The measured drawn extents are what a human sees; a pin-extent box
    instead reports the human's own decoupling capacitors as overlapping the
    chip (19 rows measured)."""
    boxes = [L_bbox(part, offsets, bodies) for part in page.parts]
    boxes = [b for b in boxes if b is not None]
    pairs = [
        (boxes[i], boxes[j])
        for i in range(len(boxes))
        for j in range(i + 1, len(boxes))
        if boxes[i].intersects(boxes[j])
    ]
    assert pairs == []


def L_bbox(part, offsets, bodies):
    from boardwise.engines.replay import part_box

    return part_box(part, offsets.get(part.designator, {}), bodies)


def test_a_rotated_part_is_bounded_where_it_sits(page, bodies, offsets):
    """Rotation is applied to the box, not just the origin: a 90-degree part
    swaps its width and height."""
    from boardwise.engines.replay import part_box

    cap = next(p for p in page.parts if p.designator == "C9")  # rotation 90
    box = part_box(cap, offsets[cap.designator], bodies)
    assert box is not None
    body = bodies[cap.symbol_uuid]
    assert round((box.x1 - box.x0), 3) == round((body[3] - body[1]), 3)
    assert round((box.y1 - box.y0), 3) == round((body[2] - body[0]), 3)


# --------------------------------------------------------------------------
# the sheet frame
# --------------------------------------------------------------------------


def test_frame_prefers_a_measured_bbox_over_the_declared_size():
    geo = {
        "components": [{"primitiveId": "s1", "state": {"ComponentType": "sheet"}}],
        "bboxes": {"s1": {"minX": 0.0, "minY": 0.0, "maxX": 1170.0, "maxY": 825.0}},
    }
    frame = sheet_frame_from_geometry(geo, declared={"Width": "999", "Height": "999"})
    assert frame.provenance == "measured"
    assert (frame.bbox.x1, frame.bbox.y1) == (1170.0, 825.0)


def test_frame_falls_back_to_the_declared_size_with_provenance():
    frame = sheet_frame_from_geometry(
        {}, declared={"Width": "1170", "Height": "825"}, origin=(0.0, 0.0)
    )
    assert frame.provenance == "declared-size"
    assert frame.notes, "the provenance downgrade is reported, never silent"


def test_frame_refuses_to_invent_a_page():
    assert sheet_frame_from_geometry({}, declared=None) is None
    assert sheet_frame_from_geometry({}, declared={"Width": "0", "Height": "0"}) is None


def test_title_block_is_the_bottom_right_ratio_rect():
    frame = sheet_frame_from_bbox(L.Rect(0.0, 0.0, 1170.0, 825.0))
    assert frame.title_block.x0 == pytest.approx(1170 * 0.4)
    assert frame.title_block.y0 == pytest.approx(825 * 0.76)
    assert (frame.title_block.x1, frame.title_block.y1) == (1170.0, 825.0)


# --------------------------------------------------------------------------
# the offset
# --------------------------------------------------------------------------


def test_offset_centres_the_content_and_clears_the_title_block():
    frame = sheet_frame_from_bbox(L.Rect(0.0, 0.0, 1170.0, 825.0))
    content = L.Rect(100.0, 500.0, 400.0, 640.0)
    (dx, dy), notes = place_offset(content, frame)
    moved = L.Rect(content.x0 + dx, content.y0 + dy, content.x1 + dx, content.y1 + dy)
    assert dx % OFFSET_GRID == 0 and dy % OFFSET_GRID == 0, "pins stay on the lattice"
    assert not moved.intersects(frame.title_block)
    assert frame.drawable.x0 <= moved.x0 and moved.x1 <= frame.drawable.x1
    assert frame.drawable.y0 <= moved.y0 and moved.y1 <= frame.drawable.y1


def test_offset_says_why_it_deviated_from_plain_centring():
    frame = sheet_frame_from_bbox(L.Rect(0.0, 0.0, 1170.0, 825.0))
    # content that fills the whole drawing area: no offset can clear the
    # title block, so the note has to say so instead of silently clamping
    whole = L.Rect(0.0, 0.0, 1160.0, 815.0)
    _offset, notes = place_offset(whole, frame)
    assert notes, "a clamped / shifted offset must not be silent"


# --------------------------------------------------------------------------
# the replay plan
# --------------------------------------------------------------------------


def test_replay_of_the_human_board_has_zero_violations(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    assert plan.violations == [], [v.render() for v in plan.violations]
    assert len(plan.placements) == 17
    assert len(plan.net_names) == 27, "17 flags + 10 labels"
    assert plan.nc_pins, "NC pins are listed explicitly"


def test_replay_keeps_rotation_and_mirror_verbatim(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    golden = {p.designator: p for p in page.parts}
    for step in plan.placements:
        source = golden[step.designator]
        assert step.rotation == source.rotation
        assert step.mirror == source.mirror


def test_every_replayed_pin_tip_lands_on_its_own_wire(page, bodies, model, offsets, frame):
    """The transform invariant: a replayed part's *rotated* pin tip must sit
    exactly on a replayed wire endpoint (or on one of its wires). This is the
    check that catches a sign / rotation-convention slip — the bug this
    project has hit twice (once in file->canvas y, once clockwise vs
    counter-clockwise)."""
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    segments = [
        L.Segment(a[0], a[1], b[0], b[1], "")
        for wire in plan.wires
        for a, b in zip(wire.points, wire.points[1:])
    ]
    connected = 0
    for (designator, number), tip in plan.pin_positions.items():
        component = model.components.get(designator)
        if component is None:
            continue
        pin = next((p for p in component.pins if p.number == number), None)
        if pin is None or not pin.net:
            continue
        assert any(L._point_on_segment(tip, seg) for seg in segments), (
            f"{designator}.{number} tip {tip} is on no wire"
        )
        connected += 1
    assert connected >= 20, "the golden board has plenty of connected pins"


def test_replay_pin_tips_exist_for_every_symbol_pin(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    assert len(plan.pin_positions) >= 17 * 2


def test_replay_names_signals_with_text_and_rails_with_flags(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    by_kind: dict[str, int] = {}
    for step in plan.net_names:
        by_kind[step.kind] = by_kind.get(step.kind, 0) + 1
    # The default strategy is `text`: rails keep their flags, signals are drawn
    # as decorative text (the native label API cannot work on this host).
    assert by_kind == {"Ground": 12, "Power": 5, "text": 10}
    assert "port" not in by_kind, "岳翔宇's rule: signal nets never use ports"
    assert "label" not in by_kind, "labels need a v4 host; the default is text"
    assert len(plan.decorative_names) == 10
    assert all(step.decorative for step in plan.decorative_names)


def test_replay_strategy_switch_changes_only_signal_naming(page, bodies, model, offsets, frame):
    def plan_for(strategy):
        return build_replay_plan(model, page, frame, offsets, bodies, strategy=strategy)

    wire_plan = plan_for("wire")
    assert not [n for n in wire_plan.net_names if n.kind in ("text", "label", "port")]
    assert {n.kind for n in wire_plan.net_names} == {"Ground", "Power"}, (
        "rails are flagged regardless of the signal policy"
    )

    label_plan = plan_for("label")
    assert len([n for n in label_plan.net_names if n.kind == "label"]) == 10
    assert not label_plan.decorative_names

    none_plan = plan_for("none")
    assert not [n for n in none_plan.net_names if n.kind in ("text", "label", "port")]

    # The strategy is carried on the plan so the report can state it.
    assert wire_plan.naming_strategy == "wire"
    assert label_plan.naming_strategy == "label"


def test_labels_sit_on_the_goldens_own_anchors(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    labels = {step.net for step in plan.net_names if step.kind == "text"}
    assert labels == {"RX", "TX", "D+", "D-"}
    # and the wires the labels name keep the human's own names
    named_wires = {wire.net for wire in plan.wires if wire.net}
    assert named_wires == {"RX", "TX", "D+", "D-"}


def test_replay_refuses_nothing_but_reports_what_it_could_not_do(page, bodies, model, offsets, frame):
    plan = build_replay_plan(model, page, frame, offsets, bodies)
    joined = " | ".join(plan.notes)
    assert "page offset" in joined
    assert "carry no net name in the source" in joined


def test_replay_without_bodies_still_bounds_parts(page, model, offsets, frame):
    """No measured bodies -> pin extents; the plan still builds and is honest
    about the weaker box."""
    plan = build_replay_plan(model, page, frame, offsets, None)
    assert len(plan.placements) == 17
    assert plan.geometry


# --------------------------------------------------------------------------
# the endpoint overhang tolerance
# --------------------------------------------------------------------------


def _synthetic_two_pin_model():
    from boardwise.core.model import Component, DesignModel, Net, Pin

    model = DesignModel()
    model.components["U1"] = Component(
        uid="d1",
        designator="U1",
        pins=[
            Pin(number="1", name="", net="A"),
            Pin(number="2", name="", net="A"),
            Pin(number="3", name="", net="A"),
        ],
    )
    model.nets["A"] = Net(name="A", pins=[("U1", "1"), ("U1", "2"), ("U1", "3")])
    return model


def _placement(designator, x, y, bbox=None):
    from boardwise.engines.layout import Placement

    return Placement(designator=designator, x=x, y=y, bbox=bbox)


def test_a_short_overhang_past_a_junction_is_not_a_floating_end():
    """Measured: one VCC leg runs 4 units past its junction on the golden
    page. A 4-unit overhang is legal; a 40-unit dangling end is not."""
    model = _synthetic_two_pin_model()
    pins = {
        ("U1", "1"): (0.0, 0.0),
        ("U1", "2"): (50.0, -40.0),
        ("U1", "3"): (100.0, 40.0),
    }
    # every real end terminates: a pin tip at (0,0), a pin at (50,-40), a pin
    # at (100,40). Only the free end of the first polyline can be a violation.
    for overhang, expect_clean in ((54.0, True), (90.0, False)):
        routes = [
            L.RoutedNet(
                net="A",
                polylines=[
                    [(0.0, 0.0), (50.0, 0.0), (overhang, 0.0)],
                    [(50.0, 0.0), (50.0, -40.0)],
                    [(50.0, 0.0), (100.0, 40.0)],
                ],
                kind="wire",
            )
        ]
        codes = [
            v.code
            for v in L.validate_full(model, [_placement("U1", 0, 0)], routes, pins)
            if v.code == "ENDPOINT_NOT_TERMINAL"
        ]
        if expect_clean:
            assert codes == [], "a 4-unit overhang is the human's own drawing"
        else:
            assert codes, "a 40-unit dangling end is a real floating end"


def test_an_annotated_wire_end_is_a_terminal():
    model = _synthetic_two_pin_model()
    pins = {("U1", "1"): (0.0, 0.0)}
    routes = [
        L.RoutedNet(net="A", polylines=[[(0.0, 0.0), (-40.0, 0.0)]], kind="wire"),
    ]
    without = L.validate_full(model, [_placement("U1", 0, 0)], routes, pins)
    assert any(v.code == "ENDPOINT_NOT_TERMINAL" for v in without)
    with_label = L.validate_full(
        model, [_placement("U1", 0, 0)], routes, pins, annotation_points=[(-40.0, 0.0)]
    )
    assert not any(v.code == "ENDPOINT_NOT_TERMINAL" for v in with_label)


def test_the_frame_override_moves_the_sheet_edge():
    model = _synthetic_two_pin_model()
    pins = {("U1", "1"): (0.0, 0.0), ("U1", "2"): (100.0, 0.0)}
    placement = [_placement("U1", 0, 0, bbox=L.Rect(0.0, 0.0, 100.0, 20.0))]
    wide = L.validate_full(model, placement, [], pins)
    assert [v.code for v in wide if v.code == "OUT_OF_SHEET"] == []
    tight = L.validate_full(
        model, placement, [], pins, frame=L.Rect(200.0, 200.0, 300.0, 300.0)
    )
    assert any(v.code == "OUT_OF_SHEET" for v in tight)


# --------------------------------------------------------------------------
# the annotation lint
# --------------------------------------------------------------------------


class _Step:
    def __init__(self, net, x, y, kind="label"):
        self.net = net
        self.x = x
        self.y = y
        self.kind = kind


def test_lint_flags_a_name_that_floats_off_its_wire():
    routes = [L.RoutedNet(net="A", polylines=[[(0.0, 0.0), (50.0, 0.0)]])]
    violations = L.lint_annotations([], routes, [_Step("A", 30.0, 30.0)])
    assert [v.code for v in violations] == ["LABEL_FLOATS"]


def test_lint_flags_stacked_names():
    routes = [L.RoutedNet(net="A", polylines=[[(0.0, 0.0), (50.0, 0.0)]])]
    violations = L.lint_annotations(
        [], routes, [_Step("A", 10.0, 0.0), _Step("A", 12.0, 0.0)]
    )
    assert any(v.code == "LABEL_OVERLAP" for v in violations)


def test_lint_flags_a_name_on_a_foreign_part():
    routes = [L.RoutedNet(net="A", polylines=[[(0.0, 0.0), (50.0, 0.0)]])]
    other = [_placement("R9", 0, 0, bbox=L.Rect(20.0, -20.0, 45.0, 20.0))]
    violations = L.lint_annotations(other, routes, [_Step("A", 30.0, 0.0)])
    assert any(v.code == "LABEL_ON_COMPONENT" for v in violations)
    forgiven = L.lint_annotations(
        other, routes, [_Step("A", 30.0, 0.0)], members_by_net={"A": {"R9"}}
    )
    assert not any(v.code == "LABEL_ON_COMPONENT" for v in forgiven)


def test_lint_flags_a_name_inside_the_title_block():
    routes = [L.RoutedNet(net="A", polylines=[[(900.0, 700.0), (950.0, 700.0)]])]
    violations = L.lint_annotations(
        [], routes, [_Step("A", 920.0, 700.0)], L.Rect(468.0, 627.0, 1170.0, 825.0)
    )
    assert any(v.code == "LABEL_ON_TITLE_BLOCK" for v in violations)


def test_lint_report_tallies_by_code():
    violations = [
        L.Violation("X", "a", "b"),
        L.Violation("X", "c", "d"),
        L.Violation("Y", "e", "f"),
    ]
    lines = L.lint_report(violations)
    assert lines[-1] == "layout lint: 3 violation(s) — X x2, Y x1"
    assert L.lint_report([]) == ["layout lint: 0 violations"]


# --------------------------------------------------------------------------
# the CLI lint command
# --------------------------------------------------------------------------


def test_lint_cli_is_clean_on_the_golden_board(capsys):
    from argparse import Namespace

    from boardwise.cli import _cmd_lint

    code = _cmd_lint(
        Namespace(from_file=GOLDEN, plan="replay", json=False)
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "plan source: golden replay" in out
    assert "naming: text" in out, "the naming policy is stated, not implied"
    assert "drawn as TEXT" in out, (
        "the report must say the signal names are decorative text"
    )
    assert "layout lint: 0 violations" in out


def test_lint_cli_reports_the_strategy_it_linted_under(capsys):
    from argparse import Namespace

    from boardwise.cli import _cmd_lint

    code = _cmd_lint(Namespace(from_file=GOLDEN, plan="replay", json=True, naming="wire"))
    out = capsys.readouterr().out
    assert code == 0
    import json as _json

    payload = _json.loads(out)
    assert payload["naming"] == "wire"
    assert payload["decorative_names"] == 0, "the wire strategy places no text"
    assert payload["net_names"] > 0, "rails are still flagged"


@pytest.mark.parametrize("strategy", ["wire", "text", "label", "none"])
def test_the_goldens_geometry_lints_clean_under_every_strategy(strategy):
    """The human's geometry is not a function of our naming policy.

    Under ``wire``/``none`` no annotation primitive is placed, so a validator
    that derives its legal wire terminals *only* from the plan's naming steps
    reports the golden label anchors as unterminated ends. Those anchors are
    where the human drew the wire to be named — a geometric fact. Every
    strategy must replay the golden page with zero violations.
    """
    from argparse import Namespace

    from boardwise.cli import _cmd_lint

    code = _cmd_lint(Namespace(from_file=GOLDEN, plan="replay", json=True, naming=strategy))
    assert code == 0, f"golden replay under --naming {strategy} reported violations"


def test_lint_cli_can_lint_the_solver_plan_too(capsys):
    from argparse import Namespace

    from boardwise.cli import _cmd_lint

    code = _cmd_lint(Namespace(from_file=GOLDEN, plan="solver", json=True))
    out = capsys.readouterr().out
    assert '"source": "generic solver"' in out
    assert code in (0, 1)
