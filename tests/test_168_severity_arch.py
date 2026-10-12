"""168 — the severity architecture ruling, pinned.

岳's two rulings, and the boundary each one may not cross:

1. **A human's page is observed, not gated.** ``draw lint``'s L8 already reports
   a sideways flag (163b) — 168 changes the *level*, not the report: 90/270 are
   INFO and no longer drive the exit code, while an odd tilt that is not a quarter
   turn (45°, say) keeps its ERROR. The split can only ever *narrow* the exit
   code. This is safe for the generator because ``draw lint`` never judges a
   generated page: ``drawcompiler`` writes only 0/180, and a landed page's flag
   orientation is checked against the plan's own rotations by ``draw apply``'s
   旗标朝向核对.
2. **The replay path gets the foreign-wire ruler, at observation level.** 163a
   hung ``LABEL_ON_FOREIGN_WIRE`` only on the solver/terminal path, whose ruler
   knows anchors and not glyphs, so the replay answered silence for the same
   defect class. It is now measured on the **glyph boxes the replayed page really
   draws** and written to ``plan.notes`` as an INFO observation — never into
   ``plan.violations``, because that list *is* the gate
   (``layout.blocking_violations``), and the solver's own row stays blocking.

The regression this file mainly guards: **the solver's blocking is not relaxed**
by any of the above.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli as cli_module
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines import drawlint, layout, replay
from boardwise.engines.generate import strip_dangling_nets
from boardwise.parsers.schematic import (
    build_pin_offsets,
    build_schematic_model,
    collect_page_layout,
    collect_symbol_bodies,
)

GOLDEN = str(Path(__file__).resolve().parent / "fixtures" / "ch340_golden.epro2")


# --------------------------------------------------------------------------
# 1. L8: a sideways flag is reported, at INFO, and the exit code stays green
# --------------------------------------------------------------------------


def _flag_snapshot(rotation: float) -> dict:
    return {
        "components": [
            {"primitiveId": "sheet1",
             "state": {"PrimitiveType": "Component", "ComponentType": "sheet"}},
            {"primitiveId": "flag-1",
             "state": {"PrimitiveType": "Component", "ComponentType": "netflag",
                       "PrimitiveId": "flag-1", "X": 80, "Y": 745,
                       "Rotation": rotation, "Net": "GND"}},
        ],
        "wires": [], "pins": [], "netlabels": [],
        "bboxes": {"sheet1": {"minX": 0, "minY": 0, "maxX": 1170, "maxY": 825}},
    }


def _l8(findings) -> list[drawlint.LintFinding]:
    return [f for f in findings if f.predicate == "L8-flag-orientation"]


def test_the_vertical_set_is_untouched_and_the_sideways_set_is_a_quarter_turn():
    """横放仍要报: the set the gate spares is unchanged; 90/270 are its fallback."""
    assert drawlint.FLAG_VERTICAL_ROTATIONS == frozenset({0, 180})
    assert drawlint.FLAG_SIDEWAYS_ROTATIONS == frozenset({90, 270})


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_sideways_flag_is_reported_at_info(rotation):
    hits = _l8(drawlint.run_lint(_flag_snapshot(rotation)))
    assert len(hits) == 1, rotation
    assert hits[0].severity == "INFO"


@pytest.mark.parametrize("rotation", [0, 180, 360])
def test_a_vertical_flag_is_never_reported(rotation):
    assert _l8(drawlint.run_lint(_flag_snapshot(rotation))) == []


def test_an_odd_tilt_is_still_an_error():
    """The split narrows the exit code, it does not widen it: 45° is not 横放."""
    hits = _l8(drawlint.run_lint(_flag_snapshot(45)))
    assert len(hits) == 1
    assert hits[0].severity == "ERROR"


def _lint_replay(tmp_path: Path, snapshot: dict):
    """`draw lint --snapshot` on a captured page — the return code as a shell sees it."""
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(snapshot), encoding="utf-8")
    report_path = tmp_path / "report.json"
    args = cli_module.build_parser().parse_args([
        "draw", "lint", "--snapshot", str(snap), "--json", str(report_path),
    ])
    code = cli_module._cmd_draw_lint(args)
    return code, json.loads(report_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("rotation", [90, 270])
def test_a_sideways_flag_no_longer_turns_the_exit_code_red(tmp_path, rotation):
    """The acceptance line: the finding is in the report, the exit code is 0."""
    code, report = _lint_replay(tmp_path, _flag_snapshot(rotation))
    assert code == 0, report
    assert report["counts"]["ERROR"] == 0
    assert report["counts"]["INFO"] >= 1
    assert report["exitCode"] == 0
    assert any(
        f["predicate"] == "L8-flag-orientation" and f["severity"] == "INFO"
        for f in report["findings"]
    ), report["findings"]


def test_an_odd_tilt_still_turns_the_exit_code_red(tmp_path):
    """The other half: the ERROR path this ruling did not touch still exits 1."""
    code, report = _lint_replay(tmp_path, _flag_snapshot(45))
    assert code == 1, report
    assert report["counts"]["ERROR"] >= 1
    assert report["exitCode"] == 1


# --------------------------------------------------------------------------
# 2. the solver path: a name on a foreign wire is still blocking
# --------------------------------------------------------------------------


def _two_crossing_nets():
    """A's wire runs east; B's crosses it at A's own attach point."""
    model = DesignModel(
        components={
            "U1": Component(uid="u", designator="U1", pins=[
                Pin(number="1", name="1", net="A"),
            ]),
            "U2": Component(uid="u2", designator="U2", pins=[
                Pin(number="1", name="1", net="B"),
                Pin(number="2", name="2", net="B"),
            ]),
        },
        nets={
            "A": Net(name="A", pins=[("U1", "1")]),
            "B": Net(name="B", pins=[("U2", "1"), ("U2", "2")]),
        },
    )
    routes = [
        layout.RoutedNet(net="A", polylines=[[(0.0, 0.0), (100.0, 0.0)]], kind="port"),
        layout.RoutedNet(net="B", polylines=[[(50.0, -30.0), (50.0, 30.0)]], kind="port"),
    ]
    return model, routes


def test_the_terminal_check_still_blocks_a_name_on_a_foreign_wire():
    """168 must not be read as permission to relax the solver's own gate."""
    model, routes = _two_crossing_nets()
    hits = layout.annotation_anchor_violations(model, routes, [], [("A", 50.0, 0.0)])
    assert [v.code for v in hits] == ["LABEL_ON_FOREIGN_WIRE"], [v.render() for v in hits]
    assert layout.blocking_violations(hits) == hits, "the solver's row must still block"
    assert "LABEL_ON_FOREIGN_WIRE" not in layout.ADVISORY_VIOLATION_CODES


def test_one_ruler_the_helper_reproduces_the_terminal_check():
    """The extracted ruler answers exactly what the terminal check always did."""
    model, routes = _two_crossing_nets()
    anchors = [("A", 50.0, 0.0)]
    direct = layout.annotation_foreign_wire_contacts(
        routes,
        [(net, x, y, layout.annotation_box(x, y, net)) for net, x, y in anchors],
    )
    via_terminal = [
        v
        for v in layout.annotation_anchor_violations(model, routes, [], anchors)
        if v.code == "LABEL_ON_FOREIGN_WIRE"
    ]
    assert [v.render() for v in direct] == [v.render() for v in via_terminal]
    assert direct, "precondition: the boxes touch B's wire"


def test_the_helper_is_quiet_when_no_name_touches_a_foreign_wire():
    """The negative half, so the check above cannot pass for the wrong reason."""
    _, routes = _two_crossing_nets()
    clear = layout.annotation_foreign_wire_contacts(
        routes, [("A", 10.0, 0.0, layout.annotation_box(10.0, 0.0, "A"))]
    )
    assert clear == []


# --------------------------------------------------------------------------
# 3. the replay path: the same defect, measured on the drawn glyph, observed
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def golden_replay_plan():
    """The golden CH340G page replayed — one build, shared by the two cases."""
    page = collect_page_layout(GOLDEN)
    bodies = collect_symbol_bodies(GOLDEN)
    model = strip_dangling_nets(build_schematic_model(GOLDEN))
    offsets = build_pin_offsets(GOLDEN)
    frame = replay.sheet_frame_from_geometry(
        {}, declared=page.sheet_attrs, origin=page.sheet_origin
    )
    return replay.build_replay_plan(model, page, frame, offsets, bodies)


def test_the_replay_observes_the_golden_pages_name_on_a_foreign_wire(
    golden_replay_plan,
):
    """Measured on the human's own page: the GND flag's glyph touches NET2's wire.

    The row names both nets, the anchor, and the wire — the same shape the
    terminal check writes — and it is an **observation**, so the plan is still a
    clean plan (this board replays with zero violations, pinned since 006b).
    """
    plan = golden_replay_plan
    observed = [n for n in plan.notes if "LABEL_ON_FOREIGN_WIRE" in n]
    assert len(observed) == 1, plan.notes
    line = observed[0]
    assert "INFO" in line, line
    assert "net GND vs net NET2" in line, line
    assert "(182,620)" in line, line
    assert "(94.0, 594.0), (194.0, 594.0)" in line, line


def test_the_replay_observation_is_not_a_violation(golden_replay_plan):
    """It goes to ``notes``; ``violations`` is the gate and must not carry it."""
    plan = golden_replay_plan
    assert [v.code for v in plan.violations] == [], [v.render() for v in plan.violations]
    assert layout.blocking_violations(plan.violations) == []
