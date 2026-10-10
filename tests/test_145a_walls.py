"""145a: the three walls 144 measured, and the vocabulary one they exposed.

Three things are pinned here, one per task of the batch:

* **T1** — `flyback_uc3845.circuit.json` prints 岳's short mark for the
  transformer (`EE16_3+3_V02`) instead of the 98-character rationale, and the
  rationale is kept in the spec's own comment field (`params.note`). The long
  string was a 622-unit text bar that squeezed the wiring channel beside T1
  (144 root cause 2).
* **T2** — the flyback grammar states the secondary feedback chain by
  `left-of` + `near` and **not** by a row: 岳's own hand-drawn page puts the
  divider in a column, and a row puts the tap run through the ground pad's flag
  lane (144 root cause 3).
* **T3** — a pin that is going to carry a flag has its lead's lane reserved
  **before** any wire is routed, and a wire of another net treats that lane as a
  wall (`_Router.reserved`, honoured by `_wall`, `_span_free` and
  `_vertex_clear`). This is the capability 144's refusal showed was missing: the
  wires were laid first, so the flag had nowhere left to hang.

Plus the vocabulary wall the two of them uncovered: `SEC_GND` was not a ground
name to `core.model.is_ground_net`, so `drawapply.flag_kind` refused to hang the
ground glyph 岳's own page draws on that net.
"""

from __future__ import annotations

import pathlib

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.model import GROUND_NET_SUFFIX_WORDS, is_ground_net
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply, drawcompiler as dc, readability
from boardwise.engines.grammar.base import LEFT_OF, NEAR, RIGHT_OF, SAME_ROW
from boardwise.engines import grammar
from boardwise.engines.router import _Router

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
FLYBACK = SPECS / "flyback_uc3845.circuit.json"
FLYBACK_PRESENTATION = SPECS / "flyback_uc3845.presentation.json"
FLYBACK_LIBRARY = SPECS / "flyback_uc3845.library.json"
LOCKS_144 = ROOT / "outputs" / "144" / "presentation_144.json"


def _library(path: pathlib.Path):
    return drawapply.load_library(path)


def _compile_locked():
    circuit = CircuitSpec.load(FLYBACK)
    presentation = PresentationSpec.load(LOCKS_144)
    book = _library(FLYBACK_LIBRARY)
    return circuit, presentation, book, dc.compile(
        circuit, presentation, book, dc.CompileBudget()
    )


# -------------------------------------------------------------------------- T1


def test_the_transformer_prints_the_short_mark_and_keeps_its_rationale():
    """T1: 岳手绘页印的值 + 选型依据挪进 spec 的注释性字段。

    The value used to *be* the rationale — 98 characters of it — and the compiler
    prints a part's value as one line, so that string became a 622-unit text bar
    on the page. `CircuitSpec` is closed (`_check_keys`), so the home for prose
    is its existing free-form string map `params`; nothing renders it, which is
    exactly what a comment field is for.
    """
    circuit = CircuitSpec.load(FLYBACK)
    part = circuit.part("T1")
    assert part.value == "EE16_3+3_V02", (
        "T1's value is the short mark 岳's own page prints (145a T1); a long "
        f"value is a text bar that squeezes the wiring channel, got {part.value!r}"
    )
    assert len(part.value) <= 16, part.value
    note = part.params.get("note", "")
    assert "749118105" in note and "18.9:1" in note, (
        "the part actually fitted and its selection rationale must survive "
        f"somewhere; params.note is {note!r}"
    )
    # And the printed line is short in the units the layout measures.
    assert dc.text_width(part.value) < 100.0, dc.text_width(part.value)


def test_no_other_part_of_the_spec_prints_a_document_string():
    """A value is a mark, not a paragraph — the same rule for every part."""
    circuit = CircuitSpec.load(FLYBACK)
    for part in circuit.parts:
        if not part.value:
            continue
        assert len(part.value) <= 32, (part.id, part.value)
        assert dc.text_width(part.value) < 200.0, (part.id, part.value)


# ------------------------------------------------------- the vocabulary wall


def test_a_ground_word_at_the_end_of_a_compound_name_is_a_ground_name():
    """145a: `SEC_GND` **is** a ground name — the vocabulary only missed it.

    `core.model.is_ground_net` is "the one place this repo calls a name ground"
    (143d), and `drawapply.flag_kind` reads it to refuse a ground glyph on a name
    that is not one. The prefix rule alone called the flyback's secondary-side
    return `SEC_GND` a rail-looking name and refused the ground flag 岳's own
    page draws there — so the *vocabulary* grew, not the check.
    """
    for name in ("SEC_GND", "ISO_GND", "SEC_VSS", "sec_gnd", "CHASSIS_PGND"):
        assert is_ground_net(name), name
    # The prefix rule and every existing negative are unchanged.
    for name in ("GND", "AGND", "PGND", "SGND", "VSS", "GNDA"):
        assert is_ground_net(name), name
    # `GNDX_RAIL` is ground by the **prefix** rule (it starts with GND) — the
    # suffix rule neither adds nor removes it.
    assert is_ground_net("GNDX_RAIL")
    for name in ("VM", "+24V", "VCC", "VEE", "VEE-5V", "-5V", "3V3", "RX",
                 "SEC_12V", "HVDC", "SEC_SW", "SECGND", "", None):
        assert not is_ground_net(name), name
    # The suffix words are the ground words, not a second list that can drift.
    assert set(GROUND_NET_SUFFIX_WORDS) == {
        "GND", "AGND", "DGND", "PGND", "EGND", "SGND", "VSS",
    }


def test_the_ground_glyph_is_allowed_on_the_secondary_return():
    """`drawapply.flag_kind` agrees: a ground symbol on `SEC_GND` is legal."""
    assert drawapply.flag_kind("SEC_GND", "PWR-GND") == drawapply.DRAW_FLAG_GROUND
    # And the disagreement 143d exists to catch is still caught: a rail name
    # with a ground glyph is refused.
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.flag_kind("VIN5", "PWR-GND")


# -------------------------------------------------------------------------- T2


def test_the_feedback_chain_states_order_and_hug_not_a_row():
    """T2: 反馈副边成链由 `left-of` + `near` 声明，**行**不再声明。

    岳手绘的活页上分压器是竖排（R7 压在 R8 上）；合成一行既与手绘相反，又把
    FB_SENSE 的抽头绕线赶到行下、压死 R8.2 的旗引线通道（144 量到 17 处拒因）。
    """
    circuit = CircuitSpec.load(FLYBACK)
    presentation = PresentationSpec.load(FLYBACK_PRESENTATION)
    book = _library(FLYBACK_LIBRARY)
    result = grammar.bind(circuit, presentation, book)
    assert result.ok, [item.detail for item in result.failures]
    assert not [item for item in result.constraints if item.kind == SAME_ROW], (
        "the flyback states no row at all after 145a T2"
    )
    pairs = {(item.kind, item.subject, item.object) for item in result.constraints}
    for part_id in ("R7", "R8", "U5"):
        assert (NEAR, part_id, "U4") in pairs, (part_id, sorted(pairs))
    # The divider arms carry the order; the opto's own left-of comes from the
    # band-crossing relation (its subject is U5 too, so one entry covers both).
    for part_id in ("R7", "R8", "U5"):
        assert (LEFT_OF, part_id, "U4") in pairs, (part_id, sorted(pairs))
    assert (RIGHT_OF, "R7", "U4") not in pairs
    assert (RIGHT_OF, "R8", "U4") not in pairs


def test_the_divider_is_not_pulled_onto_the_error_amplifiers_row():
    """The narrowed relations produce no row lane group, so R7 may stand above R8.

    114 folded a `same-row` group into a `y` lane group and moved the branch onto
    the row. With no row stated, there is no such group — which is what lets the
    divider be drawn as 岳 drew it.
    """
    circuit = CircuitSpec.load(FLYBACK)
    presentation = PresentationSpec.load(FLYBACK_PRESENTATION)
    book = _library(FLYBACK_LIBRARY)
    binding = grammar.bind(circuit, presentation, book)
    ctx = dc._prepare(
        circuit, presentation, binding, book, dc.CompileBudget(max_candidates=8)
    ).context
    assert ctx is not None
    assert not [value for value in ctx.lane_groups.values() if value[0] == "y"], (
        f"a row group is still formed: {ctx.lane_groups}"
    )


# -------------------------------------------------------------------------- T3


def _router(**overrides) -> _Router:
    options = dict(
        grid=5.0, residue=(0.0, 0.0), boxes=[], bounds=(0.0, 0.0, 200.0, 200.0)
    )
    options.update(overrides)
    return _Router(**options)


def test_a_reserved_lane_is_a_wall_for_another_nets_wire():
    """T3: `router.reserved` blocks the search, and the reserved net is exempt."""
    router = _router()
    # A wall at x=100 that spans only the middle of the corridor: the route has
    # to leave the corridor and come back, which is exactly what a reserved lane
    # asks of a foreign wire.
    router.reserved = {(100.0, 60.0 + y * 5.0): "SEC_GND" for y in range(0, 17)}
    path = router.route((50.0, 100.0), (150.0, 100.0))
    assert path is not None, "the search may go around the lane, never fail"
    assert (100.0, 100.0) not in path, "the wire stood on a reserved lane"
    # The net that reserved it may use its own lane.
    router.reserved_exempt = "SEC_GND"
    path = router.route((50.0, 100.0), (150.0, 100.0))
    assert path is not None and (100.0, 100.0) in path, path


def test_a_wire_run_honours_a_reserved_lane_and_a_flag_lead_is_left_alone():
    """`_span_free` is tried *before* the search, so it has to honour the lane —
    and only for the runs the reservation is about.

    145a's reservation promises a pad its **lead**, and the **wires** are what
    has to route around it (see `_span_free`'s own `wire` note: asking the flag's
    lead the same question made the reservation pass and the placement ask
    different questions, and 053b's AMS1117 scenes measured the cost).
    """
    router = _router()
    router.reserved = {(100.0, 100.0): "PGND"}
    # An ordinary wire run may neither cross the lane...
    assert not dc._span_free(router, (50.0, 100.0), (150.0, 100.0), set()), (
        "a straight wire crossing a reserved lane must not be called free"
    )
    # ...nor stand on it: the run's own endpoints are part of the span, which is
    # also why a corner on the lane is refused (through the two legs).
    assert not dc._span_free(router, (100.0, 100.0), (100.0, 95.0), set())
    # A run that avoids the lane is untouched.
    assert dc._span_free(router, (90.0, 100.0), (90.0, 95.0), set()) is True
    # A flag's own lead is not asked about it.
    assert dc._span_free(
        router, (50.0, 100.0), (150.0, 100.0), set(), [], wire=False
    )
    # The net that reserved the lane is exempt for both.
    router.reserved_exempt = "PGND"
    assert dc._span_free(router, (50.0, 100.0), (150.0, 100.0), set())


def test_the_lattice_helpers_agree_with_the_router_grid():
    router = _router()
    nodes = dc._lattice_nodes(router, (0.0, 0.0), (20.0, 0.0))
    assert sorted(nodes) == [(0.0, 0.0), (5.0, 0.0), (10.0, 0.0),
                             (15.0, 0.0), (20.0, 0.0)]
    inside = dc._nodes_in_box(router, (0.0, 0.0, 10.0, 10.0))
    assert inside == {(0.0, 0.0), (5.0, 0.0), (10.0, 0.0), (0.0, 5.0),
                      (5.0, 5.0), (10.0, 5.0), (0.0, 10.0), (5.0, 10.0),
                      (10.0, 10.0)}


def test_the_compiler_reserves_the_lead_lanes_before_it_routes(monkeypatch):
    """The reservation pass really runs, and the lane it promises is the lane drawn.

    The two halves are checked against each other: every reserved cell belongs to
    a net whose lead/stub the plan draws, and every drawn ground flag's lead lies
    on cells that same net reserved.
    """
    seen: dict[str, object] = {}
    real = dc._lead_lane_reservations

    def spy(ctx, placed, expressions, order, router, occupied, solids, bodies):
        real(ctx, placed, expressions, order, router, occupied, solids, bodies)
        seen["reserved"] = dict(router.reserved)

    monkeypatch.setattr(dc, "_lead_lane_reservations", spy)
    circuit, presentation, book, result = _compile_locked()
    assert result.ok, [item.detail for item in result.failures]
    reserved = seen["reserved"]
    assert reserved, "the flyback has ten ground pads to flag: nothing was reserved"
    # The flyback's own labels (GATE, VFB_NF) reserve their stubs too — 145a2.
    assert set(reserved.values()) <= {"PGND", "SEC_GND", "GATE", "VFB_NF"}, sorted(
        set(reserved.values())
    )
    assert {"PGND", "SEC_GND"} <= set(reserved.values()), sorted(
        set(reserved.values())
    )
    plan = result.candidates[0]
    drawn = {item.net for item in plan.power_symbols}
    assert drawn == {"PGND", "SEC_GND", "HVDC", "SEC_12V"}, drawn
    # Every drawn ground flag's lead lies on cells its own net reserved.
    leads = [seg for seg in plan.segments if seg.net in ("PGND", "SEC_GND")]
    assert len(leads) >= 10, len(leads)
    for segment in leads:
        for start, end in zip(segment.points, segment.points[1:]):
            for node in dc._lattice_nodes(_router(), start, end):
                owner = reserved.get(node)
                assert owner == segment.net, (
                    f"{segment.net}'s lead passes through {node}, reserved for "
                    f"{owner!r} — the lane promised and the lane drawn disagree"
                )


def test_the_delivered_lock_table_compiles_with_every_ground_flag():
    """The 145a acceptance anchor, as a test: ok, 15→ the compiler's own count, 0
    hard readability violations.

    The count is the compiler's policy, measured rather than assumed: `PGND` and
    `SEC_GND` are ground-class nets, each named by a flag at every pin (069
    sec.1) — **ten** flags. `SEC_12V` is a rail, and the secondary chain's
    `direct-wire` obligation is stated *before* the class's high-fan-out rule
    (`_expression_style`), so it is drawn as a wire carrying one rail flag (069
    sec.7); `HVDC` likewise. That is twelve flags in all — 岳's own page carries
    exactly one `SEC_12V` flag, so the per-pin count 144 predicted for it was an
    analysis slip, not a target.
    """
    circuit, presentation, book, result = _compile_locked()
    assert result.ok, [item.detail for item in result.failures]
    plan = result.candidates[0]
    counts: dict[str, int] = {}
    for symbol in plan.power_symbols:
        counts[symbol.net] = counts.get(symbol.net, 0) + 1
    assert counts == {"PGND": 5, "SEC_GND": 5, "HVDC": 1, "SEC_12V": 1}, counts
    checked = readability.check(
        plan, circuit, presentation, book, page_box=None,
        grid=dc.CompileBudget().grid,
    )
    assert not checked.hard_violations, [
        item.render() for item in checked.hard_violations
    ]
    # No flag lead runs through a foreign net's conductor (074's defect).
    flag_nets = {"PGND", "SEC_GND"}
    for segment in plan.segments:
        if segment.net not in flag_nets:
            continue
        for start, end in zip(segment.points, segment.points[1:]):
            for other in plan.segments:
                if other.net == segment.net:
                    continue
                for a, b in zip(other.points, other.points[1:]):
                    assert dc._proper_crossing(start, end, a, b) is None, (
                        f"{segment.net}'s flag lead crosses net {other.net}'s "
                        f"wire at {dc._proper_crossing(start, end, a, b)}"
                    )


def test_the_reservation_pass_is_deterministic():
    """Two runs of one input reserve the same cells (053 stage A's rule)."""
    circuit = CircuitSpec.load(FLYBACK)
    presentation = PresentationSpec.load(LOCKS_144)
    book = _library(FLYBACK_LIBRARY)
    binding = grammar.bind(circuit, presentation, book)
    seen = []
    for _ in range(2):
        ctx = dc._prepare(
            circuit, presentation, binding, book, dc.CompileBudget()
        ).context
        placed, _failure = dc._place(ctx, dc._variants(ctx)[0])
        router = _Router(
            grid=ctx.budget.grid, residue=placed.residue, boxes=[], bounds=(
                0.0, 0.0, 1170.0, 825.0,
            ),
        )
        dc._lead_lane_reservations(
            ctx, placed, dc._expressions(ctx, placed),
            dc._net_order(ctx, dc._expressions(ctx, placed)), router,
            list(ctx.budget.keepouts), list(ctx.budget.keepouts), [],
        )
        seen.append(sorted(router.reserved.items()))
    assert seen[0] == seen[1]
    assert seen[0]


# ------------------------------------------------- 145a2: the label-stub lane


def test_a_label_stub_lane_is_reserved_and_the_constants_agree():
    """145a2: a label's name stub is a lead too, and its first rung is reserved.

    `drawapply.LABEL_STUB_LENGTH` is the page layer's first stub rung; the lane
    this pass reserves is that many lattice steps along the side the label's own
    box is on. The two constants are **pinned equal** so they cannot drift: the
    compiler models the run the page layer draws, and a silent disagreement
    would reserve the wrong cells.
    """
    assert dc.LABEL_LANE_STEPS * dc.GRID == drawapply.LABEL_STUB_LENGTH, (
        dc.LABEL_LANE_STEPS, dc.GRID, drawapply.LABEL_STUB_LENGTH
    )


def test_the_ch340_label_stubs_keep_the_label_side(monkeypatch):
    """The page whose 099d/099f reds this fix answers, end to end.

    Every one of the four stubs is a straight 10-unit run towards its own label
    box, no stub touches a foreign conductor, and the wire that used to cut the
    `GND` flag's lead (`V3`) no longer does — the lane reservation is what moved
    it, and the stub it had pushed onto the wrong side came back.
    """
    spec = SPECS / "ch340_serial"
    circuit = CircuitSpec.load(spec.with_suffix(".circuit.json"))
    presentation = PresentationSpec.load(spec.with_suffix(".presentation.json"))
    book = _library(spec.with_suffix(".library.json"))
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
    )
    assert result.ok, [item.detail for item in result.failures]
    plan = drawapply.module_plan(
        result.candidates[0], circuit, presentation, book,
        label_stubs=True, module_label="page serial",
    )
    stubs = {item.net: item.points for item in plan.change.draw_wires if item.purpose}
    assert set(stubs) == {"TXD", "RXD", "D+", "D-"}, stubs
    for net, points in stubs.items():
        assert len(points) == 2, (net, points)
        anchor, far = points
        assert far[1] == anchor[1] and far[0] < anchor[0], (net, points)
        assert anchor[0] - far[0] == drawapply.LABEL_STUB_LENGTH, (net, points)
    # No flag lead on this page is cut by another net's wire (the defect the
    # reroute answers: measured 2 on the old arrangement, 0 now).
    flag_nets = {item.net for item in result.candidates[0].power_symbols}
    for segment in result.candidates[0].segments:
        if segment.net not in flag_nets:
            continue
        for start, end in zip(segment.points, segment.points[1:]):
            for other in result.candidates[0].segments:
                if other.net == segment.net:
                    continue
                for a, b in zip(other.points, other.points[1:]):
                    assert dc._proper_crossing(start, end, a, b) is None, (
                        f"{segment.net}'s flag lead is cut by {other.net} at "
                        f"{dc._proper_crossing(start, end, a, b)}"
                    )
