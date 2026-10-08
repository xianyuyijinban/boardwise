"""136: wire-to-wire spacing — the gap in the gate, and the router's silence.

**Why this exists.** The complaint behind 136 is "the AI's schematic has the
parts and the wires all piled in one block". 134 traced it and found the hole:
`validate_full` re-checks twelve violation classes and *not one* of them is
about two nets' wires running alongside each other. So the router's separation
was a construction-time preference and nothing ever re-measured the result —
two wires five units apart passed the gate in silence.

This module covers both halves, because one without the other leaves the same
complaint standing:

1. the **gate** gains `WIRE_TOO_CLOSE` (`layout.validate_full`), measured on the
   finished geometry against `layout.WIRE_CLEARANCE`;
2. the **router** stops dropping its separation preference silently — a net that
   only routes after the retry says so, as `SEPARATION_GIVEN_UP` and in the
   plan's notes.

The ruler is measured, not chosen: replaying the golden CH340G page, the
tightest gap between two nets' parallel wires is exactly 10.0 units. A drawing
that reads worse than the human's own page is the thing worth reporting, and a
drawing that reads no worse is not.
"""

from __future__ import annotations

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import layout
from boardwise.engines.generate import (
    canvas_pin_offsets,
    generate_plan,
    strip_dangling_nets,
)
from boardwise.parsers.schematic import (
    build_pin_offsets,
    build_schematic_model,
    collect_page_layout,
    collect_symbol_bodies,
)

GOLDEN = "tests/fixtures/ch340_golden.epro2"


# --------------------------------------------------------------------------
# helpers: a model and routes the test states outright
# --------------------------------------------------------------------------


def _component(designator: str, pins: dict[str, str]) -> Component:
    return Component(
        uid=designator,
        designator=designator,
        pins=[Pin(number=number, name=number, net=net) for number, net in pins.items()],
    )


def _two_net_model() -> DesignModel:
    """Two one-pair nets on two boxes, far enough apart that placement is clean."""
    return DesignModel(
        components={
            "U1": _component("U1", {"1": "AAA", "2": "AAA"}),
            "U2": _component("U2", {"1": "BBB", "2": "BBB"}),
        },
        nets={
            "AAA": Net(name="AAA", pins=[("U1", "1"), ("U1", "2")]),
            "BBB": Net(name="BBB", pins=[("U2", "1"), ("U2", "2")]),
        },
    )


def _validate(model: DesignModel, routes: list[layout.RoutedNet]) -> list[layout.Violation]:
    """Run the gate over hand-built routes, with no placements to trip over.

    The spacing question is about wires alone, so the boxes are left empty and
    every other code is filtered out by the caller: what is under test here is
    whether `WIRE_TOO_CLOSE` fires, not the whole five-constraint gate.
    """
    return layout.validate_full(model, [], routes, {})


def _too_close(violations: list[layout.Violation]) -> list[layout.Violation]:
    return [v for v in violations if v.code == "WIRE_TOO_CLOSE"]


def _route(net: str, *polylines: list[tuple[float, float]]) -> layout.RoutedNet:
    return layout.RoutedNet(
        net=net, polylines=[list(p) for p in polylines], attach=(0.0, 0.0), kind="port"
    )


# --------------------------------------------------------------------------
# 1. the shape test: what the ruler fires on and what it deliberately does not
# --------------------------------------------------------------------------


def test_parallel_wires_closer_than_the_clearance_are_reported():
    """The case the whole task is about: 5 units apart, running side by side."""
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(0.0, 5.0), (200.0, 5.0)]),
    ]
    hits = _too_close(_validate(model, routes))
    assert len(hits) == 1, [v.render() for v in hits]
    assert "AAA" in hits[0].subject and "BBB" in hits[0].subject


def test_wires_exactly_at_the_clearance_are_not_reported():
    """The threshold is exclusive, so a page routed at the measured pitch passes.

    The golden page's own tightest gap is exactly `WIRE_CLEARANCE`; a
    ``>=`` comparison would put 19 rows on a board that is clean by the
    human's own standard, which is the "report only real anomalies" line.
    """
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(0.0, layout.WIRE_CLEARANCE), (200.0, layout.WIRE_CLEARANCE)]),
    ]
    assert _too_close(_validate(model, routes)) == []


def test_vertical_parallel_wires_are_measured_too():
    """The ruler is orientation-blind: a vertical pair is the same complaint."""
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (0.0, 200.0)]),
        _route("BBB", [(5.0, 0.0), (5.0, 200.0)]),
    ]
    assert len(_too_close(_validate(model, routes))) == 1


def test_a_perpendicular_crossing_is_not_reported():
    """Crossing is a legal form: the editor continues both wires unconnected.

    Reporting it would drown the real findings in the most ordinary shape a
    schematic has — and `CROSS_NET_SHORT` already covers the illegal version
    of a crossing, a wire *endpoint* landing on a stranger's wire.
    """
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(100.0, -100.0), (100.0, 100.0)]),
    ]
    assert _too_close(_validate(model, routes)) == []


def test_wires_that_only_approach_without_running_along_each_other_are_not_reported():
    """Two runs that pass near each other but never overlap are not a pair.

    Their projections come arbitrarily close and they are still not running
    side by side: this is a bend geometry. On the golden page this exclusion
    is the difference between 19 real findings and 86 rows mostly about
    corners.
    """
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (50.0, 0.0)]),
        _route("BBB", [(60.0, 5.0), (60.0, 200.0)]),
    ]
    assert _too_close(_validate(model, routes)) == []


def test_two_nets_touching_end_to_end_are_a_connection_not_a_spacing_fault():
    """Wires that meet end to end are how a net is drawn, not a near miss."""
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (50.0, 0.0)]),
        _route("BBB", [(50.0, 0.0), (50.0, 200.0)]),
    ]
    assert _too_close(_validate(model, routes)) == []


def test_a_single_net_running_against_itself_is_not_reported():
    """Same net: two branches of one net may legitimately run beside each other."""
    model = _two_net_model()
    routes = [_route("AAA", [(0.0, 0.0), (200.0, 0.0)], [(0.0, 5.0), (200.0, 5.0)])]
    assert _too_close(_validate(model, routes)) == []


def test_the_finding_reports_the_gap_and_how_long_the_run_is():
    """The report has to be actionable: how close, and over what stretch."""
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(0.0, 5.0), (200.0, 5.0)]),
    ]
    detail = _too_close(_validate(model, routes))[0].detail
    assert "5 apart" in detail
    assert "200 units" in detail


# --------------------------------------------------------------------------
# 2. parallel_gap: the ruler as a function, so its shape is pinned directly
# --------------------------------------------------------------------------


def _seg(x0, y0, x1, y1, net="N"):
    return layout.Segment(x0, y0, x1, y1, net)


def test_parallel_gap_answers_gap_and_shared_run():
    measured = layout.parallel_gap(_seg(0, 0, 100, 0), _seg(30, 7, 90, 7))
    assert measured == (7.0, 60.0)


def test_parallel_gap_declines_a_perpendicular_pair():
    assert layout.parallel_gap(_seg(0, 0, 100, 0), _seg(50, -50, 50, 50)) is None


def test_parallel_gap_declines_a_pair_that_only_touches_end_to_end():
    assert layout.parallel_gap(_seg(0, 0, 50, 0), _seg(50, 0, 50, 100)) is None


def test_parallel_gap_declines_a_pair_that_never_overlaps():
    """Adjacent runs: close in projection, no shared stretch, so no answer."""
    assert layout.parallel_gap(_seg(0, 0, 40, 0), _seg(50, 5, 50, 200)) is None


# --------------------------------------------------------------------------
# 3. the router half: giving up separation is said out loud, not silently
# --------------------------------------------------------------------------


def test_the_router_reports_when_it_routes_without_separation():
    """The fallback retry is the silent path 136 is about — now it is not silent.

    On the golden board three nets can only route after the retry drops the
    separation inflation. The routing is still accepted — connectivity outranks
    aesthetics, and that ordering is unchanged — but the cost is stated.
    """
    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
    geometry = generate_plan(golden, offsets)
    _routes, routing_violations = layout.route_nets(
        golden, geometry.pin_positions, geometry.geometry
    )
    given_up = [v for v in routing_violations if v.code == "SEPARATION_GIVEN_UP"]
    assert given_up, "the golden board does exercise the fallback"
    for row in given_up:
        assert row.subject.startswith("net ")
        assert "without the separation inflation" in row.detail


def test_the_plan_notes_say_when_separation_was_given_up():
    """The note is the user-facing half: it lands in the plan, not just the gate."""
    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    offsets = canvas_pin_offsets(build_pin_offsets(GOLDEN))
    plan = generate_plan(golden, offsets)
    assert any("separation inflation" in note for note in plan.notes), plan.notes
    assert any(v.code == "SEPARATION_GIVEN_UP" for v in plan.violations)


def test_a_clean_routing_gains_no_separation_note():
    """The note has to mean something: it is absent when nothing was given up.

    A note that always fires is a note nobody reads. Two isolated one-pair nets
    each route on their first attempt, so there is nothing to disclose.
    """
    model = _two_net_model()
    offsets = {
        "U1": {"1": (0.0, 0.0), "2": (0.0, 100.0)},
        "U2": {"1": (400.0, 0.0), "2": (400.0, 100.0)},
    }
    plan = generate_plan(model, offsets)
    assert not [v for v in plan.violations if v.code == "SEPARATION_GIVEN_UP"], [
        v.render() for v in plan.violations
    ]
    assert not [n for n in plan.notes if "separation inflation" in n], plan.notes


# --------------------------------------------------------------------------
# 5. reported, not fatal: the ruler must not be able to stop a correct board
# --------------------------------------------------------------------------


def test_spacing_findings_are_advisory_and_everything_else_is_not():
    """只出数不判死: a readability finding does not block drawing a valid plan.

    The distinction is the difference between a gate and a taste. Every other
    code means the drawing is *wrong* (a wire through a part, two nets
    shorted, an end connecting to nothing) and must stop execution. These two
    mean the drawing is *correct but hard to read*, and the ruler behind them
    is a house rule whose number is still pending confirmation — so they are
    reported and counted without refusing the board.
    """
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(0.0, 5.0), (200.0, 5.0)]),
    ]
    hits = _too_close(_validate(model, routes))
    assert hits, "precondition: the finding exists"
    assert layout.blocking_violations(hits) == []


def test_a_real_defect_still_blocks():
    """The exemption is narrow: it covers the two new codes and nothing else.

    The synthetic routes trip other codes as well (their ends are not pin tips
    — this fixture has no placements), which is itself the point: none of
    those are excused either.
    """
    model = _two_net_model()
    routes = [
        _route("AAA", [(0.0, 0.0), (200.0, 0.0)]),
        _route("BBB", [(0.0, 5.0), (200.0, 5.0)]),
    ]
    violations = _validate(model, routes)
    blocked = {v.code for v in layout.blocking_violations(violations)}
    assert "WIRE_TOO_CLOSE" not in blocked
    assert {"ENDPOINT_NOT_TERMINAL"} <= blocked, blocked
    assert layout.ADVISORY_VIOLATION_CODES.isdisjoint(blocked), blocked


def test_the_advisory_codes_are_exactly_the_two_new_ones():
    """A closed list, so widening it later is a deliberate act."""
    assert layout.ADVISORY_VIOLATION_CODES == {"WIRE_TOO_CLOSE", "SEPARATION_GIVEN_UP"}


def test_the_draw_gate_executes_a_plan_whose_only_findings_are_advisory():
    """End to end: a too-tight drawing still gets drawn, and says so.

    This is the acceptance line for 「只出数不判死」. Before 136's advisory
    split, adding the check turned the golden solver drawing into 52 self-check
    violations and ``run_draw`` refused it outright — the new check silently
    became the strictest gate in the pipeline.
    """
    from boardwise.engines.draw import print_self_check

    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    plan = generate_plan(golden, canvas_pin_offsets(build_pin_offsets(GOLDEN)))
    assert _too_close(plan.violations), "precondition: the finding exists"
    assert print_self_check(plan) == [], print_self_check(plan)


def test_the_lint_report_still_counts_and_names_the_advisory_rows():
    """Advisory is not silent: the tally has to carry them."""
    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    plan = generate_plan(golden, canvas_pin_offsets(build_pin_offsets(GOLDEN)))
    report = layout.lint_report(plan.violations)
    tally = report[-1]
    assert "WIRE_TOO_CLOSE" in tally and "SEPARATION_GIVEN_UP" in tally


# --------------------------------------------------------------------------
# 4. the golden board: the ruler against the human's own page, and the
#    solver's page — the measurement 136 was opened for
# --------------------------------------------------------------------------


def test_the_humans_own_page_is_clean_under_this_ruler():
    """The reference *drawing* is clean: the replay of the human's own geometry.

    This is the load-bearing calibration, and it is why `WIRE_CLEARANCE` is 10
    and not 5. Every pair of nets' parallel wires on the golden page sits at
    10 units or more — the human's own routing pitch — so the ruler is set
    where the reference passes, and what it reports is drawings that read
    *worse* than the human's.
    """
    from boardwise.engines.replay import build_replay_plan, sheet_frame_from_geometry

    page = collect_page_layout(GOLDEN)
    model = strip_dangling_nets(build_schematic_model(GOLDEN))
    frame = sheet_frame_from_geometry(
        {}, declared=page.sheet_attrs, origin=page.sheet_origin
    )
    plan = build_replay_plan(
        model, page, frame, build_pin_offsets(GOLDEN), collect_symbol_bodies(GOLDEN)
    )
    assert _too_close(plan.violations) == [], [
        v.render() for v in _too_close(plan.violations)
    ][:5]


def test_the_solver_drawing_reports_the_pairs_it_actually_runs_too_close():
    """The blind spot, measured: what the gate used to pass in silence.

    Before 136 this board produced **zero** spacing findings no matter how the
    wires were drawn — 49 pairs of different nets running 5 units apart, over
    runs as long as 285 units. The count is pinned because it is the finding
    that 134 filed this task for; a change in it is a change in the router's
    output, which other tests will notice loudly.
    """
    golden = strip_dangling_nets(build_schematic_model(GOLDEN))
    plan = generate_plan(golden, canvas_pin_offsets(build_pin_offsets(GOLDEN)))
    hits = _too_close(plan.violations)
    assert len(hits) == 49, len(hits)
    # every one of them is the same real shape: adjacent grid lanes, 5 apart
    for row in hits:
        assert "run 5 apart" in row.detail
