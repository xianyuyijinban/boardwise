"""054 stage C1: the compiled drawing as a plan, a guard and a postcondition.

Four things are pinned here, and each one is a claim the task book makes:

1. **the plan is the drawing** — `module_plan` turns one `LayoutPlan` candidate
   into a `draw-module` `ChangePlan` whose parts, wires, flags, islands and
   expected pin offsets are the layout's, and whose JSON round-trips;
2. **it is deterministic** — the same three inputs produce byte-identical plan
   JSON, twice (054 §四.3's "同输入逐字节同 plan");
3. **the guards refuse** — the three digests, the library geometry table, the
   page identity and the primitive census (054 §四.1), each with its own test and
   each with "nothing is written" left to the CLI's tests;
4. **the postconditions are 036-shaped** — one function, two legs, read before
   the writes and after them (`engines.subcircuit`'s contract, so "already done"
   and "done" cannot disagree), and the pin read-back is a real comparison with a
   half-lattice-step tolerance rather than a formality.

The specs are the hand-written fixtures under `tests/fixtures/drawapply/`: a
2-resistor divider and a 7-entry symbol library, written as JSON rather than
built in-process because the two CLI commands take files and the file path is
part of what is being tested.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.changeplan import (
    DRAW_FLAG_GROUND,
    DRAW_FLAG_POWER,
    DRAW_GRID,
    DRAW_MODULE_KIND,
    ChangePlan,
    ChangePlanError,
)
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutPlan
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawapply, drawcompiler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawapply"
CIRCUIT = FIXTURES / "divider.circuit.json"
PRESENTATION = FIXTURES / "divider.presentation.json"
LIBRARY = FIXTURES / "library.json"
PAGE_BOX = (0.0, -1000.0, 1200.0, 0.0)
LCSC = {"R1": "C25744", "R2": "C25744"}


# ------------------------------------------------------------------ fixtures


@pytest.fixture(scope="module")
def circuit() -> CircuitSpec:
    return CircuitSpec.load(CIRCUIT)


@pytest.fixture(scope="module")
def presentation() -> PresentationSpec:
    return PresentationSpec.load(PRESENTATION)


@pytest.fixture(scope="module")
def profiles() -> dict[str, SymbolProfile]:
    return drawapply.load_library(LIBRARY)


@pytest.fixture(scope="module")
def compiled(circuit, presentation, profiles):
    return drawcompiler.compile(
        circuit, presentation, profiles, drawcompiler.CompileBudget(page_box=PAGE_BOX)
    )


@pytest.fixture()
def plan(compiled, circuit, presentation, profiles) -> ChangePlan:
    return drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles,
        lcsc_by_part=LCSC,
        notes=["plan built by the test"],
    )


def _live(*components) -> dict[tuple[str, str], str]:
    """A live-netlist reading, in `patchpin.live_pin_nets`' own shape."""
    out: dict[tuple[str, str], str] = {}
    for designator, pins in components:
        for pin, net in pins.items():
            out[(designator, pin)] = net
    return out


def _geometry(*, components, wires=(), netflags=(), bboxes=None) -> dict:
    """A `sch.geometry` dump in the shape 3.2.186 sends (036's helper's shape)."""
    return {
        "components": [
            {"primitiveId": f"p-{name}",
             "state": {"Designator": name, "X": x, "Y": y, "ComponentType": "part",
                       "Rotation": rotation, "Mirror": mirror}}
            for name, x, y, rotation, mirror in components
        ]
        + [{"primitiveId": "sheet-1",
            "state": {"ComponentType": "sheet", "Designator": "", "X": 0, "Y": 0}}]
        + [
            {"primitiveId": f"flag-{index}",
             "state": {"ComponentType": "netflag", "Designator": None, "Net": net,
                       "X": x, "Y": y}}
            for index, (net, x, y) in enumerate(netflags)
        ],
        "wires": [
            {"primitiveId": primitive_id,
             "state": {"Line": [c for pair in points for c in pair], "Net": net}}
            for primitive_id, net, points in wires
        ],
        "netlabels": [],
        "bboxes": {"sheet-1": {"minX": 0, "minY": -1000, "maxX": 1200, "maxY": 0},
                   **(bboxes or {})},
        "meta": {"available": {"components": True, "wires": True, "bboxes": True}},
    }


def _page_matching(plan: ChangePlan) -> dict:
    """A page that *is* the plan: every part, every wire, every flag."""
    components = [
        (part.designator, part.x, part.y, part.rotation, part.mirror)
        for part in plan.change.draw_parts
    ]
    wires = [
        (f"w-{index}", wire.net, wire.points)
        for index, wire in enumerate(plan.change.draw_wires)
    ]
    netflags = [(flag.net, flag.x, flag.y) for flag in plan.change.draw_flags]
    return _geometry(components=components, wires=wires, netflags=netflags)


def _pins_from_plan(plan: ChangePlan) -> dict[tuple[str, str], tuple[float, float]]:
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for part in plan.change.draw_parts:
        for pin in part.pins:
            out[(part.designator, pin.number)] = (part.x + pin.dx, part.y + pin.dy)
    return out


# ------------------------------------------------------- 1. the plan is it


def test_the_plan_is_the_layouts_parts_wires_and_flags(plan: ChangePlan) -> None:
    assert plan.change.kind == DRAW_MODULE_KIND
    assert [part.spec_id for part in plan.change.draw_parts] == ["R1", "R2"]
    assert all(part.value == "10k" for part in plan.change.draw_parts)
    assert {part.lcsc for part in plan.change.draw_parts} == {"C25744"}
    assert [wire.net for wire in plan.change.draw_wires] == ["VIN", "TAP", "TAP", "GND"]
    assert [(flag.net, flag.kind) for flag in plan.change.draw_flags] == [
        ("VIN", DRAW_FLAG_POWER), ("GND", DRAW_FLAG_GROUND),
    ]
    # The compiler's own convention: rails are drawn as flags, a signal net's
    # stub carries a label — which this host cannot place (029), so the plan
    # declares the downgrade instead of dropping it silently.
    assert any("TAP" in line and "place_netlabel" in line for line in plan.change.draw_downgrades)


def test_the_flags_are_flagged_in_the_connector_own_vocabulary(plan: ChangePlan) -> None:
    # `power_flag_kind('VIN')` answers '' on this host (its regex knows +5V/VCC/
    # VDD, not VIN), so the kind comes from the `PWR-` symbol the compiler wrote —
    # and that is exactly why a VIN flag is executable at all.
    assert drawapply.flag_kind("VIN", "PWR-VIN") == DRAW_FLAG_POWER
    assert drawapply.flag_kind("GND", "PWR-GND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("GND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("SIG", "PWR-SIG") == DRAW_FLAG_POWER
    assert drawapply.flag_kind("SIG", "") == ""
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.flag_kind("GND", "PWR-5V")


def test_the_expected_pins_are_offsets_and_they_are_posed(plan: ChangePlan) -> None:
    """A part's pins are compared as *offsets*, because that survives placement."""
    for part in plan.change.draw_parts:
        assert sorted(pin.number for pin in part.pins) == ["1", "2"]
        assert {(pin.dx, pin.dy) for pin in part.pins} == {(0.0, 50.0), (0.0, -50.0)}
    # The expected page points are the offsets applied to the origin.
    points = drawapply.expected_pin_points(plan.change.draw_parts[0])
    assert points["1"] == (plan.change.draw_parts[0].x, plan.change.draw_parts[0].y + 50.0)
    # A rotated part's offsets move with its pose: the same profile, drawn at 90°.
    profile = drawapply.load_library(LIBRARY)["R-AXIAL"]
    assert drawapply.posed_pin_offsets(profile, 0, False)["2"] == (50.0, 0.0)
    assert drawapply.posed_pin_offsets(profile, 90, False)["2"] == (0.0, 50.0)


def test_the_islands_are_the_circuits_own_net_partition(plan: ChangePlan) -> None:
    """Membership, never names: 037's reading, in `PlanIsland`'s shape."""
    by_pin = {island.pin: island.mates for island in plan.change.islands}
    assert by_pin["R1.2"] == ["R1.2", "R2.1"], "TAP joins the two resistors"
    assert by_pin["R2.1"] == ["R1.2", "R2.1"]
    assert by_pin["R1.1"] == ["R1.1"], "a rail on one pin is a one-pin island"
    assert by_pin["R2.2"] == ["R2.2"]
    assert not any(pin.startswith("X") for pin in by_pin)


def test_the_plan_round_trips_through_its_own_schema(plan: ChangePlan, tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    plan.dump(path)
    back = ChangePlan.load(path)
    assert back.change.kind == DRAW_MODULE_KIND
    assert back.to_jsonable() == plan.to_jsonable()
    assert back.change.draw_parts[0].pins == plan.change.draw_parts[0].pins
    assert back.change.profile_hashes == plan.change.profile_hashes
    assert back.source.input_sha256 == plan.source.input_sha256
    # The other kinds' documents are untouched by the new one: a component-value
    # plan still serialises exactly the five keys it always did (016's rule).
    from boardwise.core.changeplan import COMPONENT_VALUE_KIND, component_value_plan, sha256_of

    old = component_value_plan(
        source=type(plan.source)(input_sha256=sha256_of(CIRCUIT)), designator="R1",
        before="10k", after="4k7",
    )
    assert set(old.to_jsonable()["change"]) == {"kind", "before", "after"}
    assert old.to_jsonable()["change"]["kind"] == COMPONENT_VALUE_KIND


def test_the_source_digest_covers_every_input(compiled, plan: ChangePlan) -> None:
    layout = compiled.candidates[0]
    assert plan.source.input_sha256 == drawapply.source_digest(
        layout.source.circuit_sha256, layout.source.presentation_sha256,
        layout.geometry_sha256(), 0, plan.change.profile_hashes,
    )
    # …and it moves when any one of them moves.
    assert plan.source.input_sha256 != drawapply.source_digest(
        layout.source.circuit_sha256, layout.source.presentation_sha256,
        layout.geometry_sha256(), 1, plan.change.profile_hashes,
    )


def test_the_plan_is_byte_identical_twice(compiled, circuit, presentation, profiles) -> None:
    """054 §四.3: the same inputs to the same bytes, not merely equivalent plans."""
    first = drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles, lcsc_by_part=LCSC,
    )
    second = drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles, lcsc_by_part=LCSC,
    )
    assert json.dumps(first.to_jsonable(), sort_keys=True) == json.dumps(
        second.to_jsonable(), sort_keys=True
    )


# ------------------------------------------------------- 2. the designators


def test_designators_come_from_the_pool_the_caller_hands_over(compiled, circuit, presentation, profiles) -> None:
    plan = drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles,
        lcsc_by_part=LCSC, pool=["R1", "C7"],
    )
    assert [part.designator for part in plan.change.draw_parts] == ["R2", "R3"]
    assert [part.prefix for part in plan.change.draw_parts] == ["R", "R"]


def test_the_prefix_is_the_spec_ids_own_letters(compiled, circuit, presentation, profiles) -> None:
    """A part drawn with a symbol named nothing like its role keeps its own letter."""
    assert drawapply._prefix_of("C12", profiles["R0402"]) == "C"
    assert drawapply._prefix_of("1", profiles["R0402"]) == "R", "no letters -> the symbol's"
    assert drawapply._prefix_of("1", SymbolProfile(symbol_ref="1234")) == ""


def test_a_taken_designator_stops_the_plan_before_any_write(plan: ChangePlan, compiled,
                                                            circuit, presentation,
                                                            profiles) -> None:
    """The C5-shaped refusal, one number wide: the pool moved under the plan."""
    assert drawapply.designator_problems(plan, ["R9"]) == []
    problems = drawapply.designator_problems(plan, ["R1", "R9"])
    assert problems and "R1" in problems[0]
    # A plan built against a busier page holds higher numbers, and a pool that has
    # since emptied allocates the *lowest* free ones — so the plan's numbers are no
    # longer the pool's, and a run that wrote them anyway would be a run with two
    # numbering conventions (036b's mid-run rename is the measured failure).
    crowded = drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles,
        lcsc_by_part=LCSC, pool=["R1", "R2"],
    )
    assert [part.designator for part in crowded.change.draw_parts] == ["R3", "R4"]
    freed = drawapply.designator_problems(crowded, [])
    assert freed and "the pool now allocates R1" in freed[0]


# ------------------------------------------------------------- 3. the guards


def test_the_guard_passes_a_page_that_is_the_plan(plan: ChangePlan, profiles) -> None:
    assert drawapply.guard_problems(
        plan,
        circuit_sha256=plan.change.circuit_sha256,
        presentation_sha256=plan.change.presentation_sha256,
        layout_sha256=plan.change.layout_sha256,
        profiles=profiles,
        page_uuid=plan.source.page_uuid,
        geometry=_page_matching(plan),
    ) == []


def test_the_guard_refuses_a_changed_circuit_digest(plan: ChangePlan) -> None:
    problems = drawapply.guard_problems(plan, circuit_sha256="0" * 64)
    assert problems and "circuitSha256" in problems[0]


def test_the_guard_refuses_a_changed_presentation_and_layout_digest(plan: ChangePlan) -> None:
    problems = drawapply.guard_problems(plan, presentation_sha256="1" * 64)
    assert problems and "presentationSha256" in problems[0]
    problems = drawapply.guard_problems(plan, layout_sha256="2" * 64)
    assert problems and "layoutSha256" in problems[0]


def test_the_guard_skips_a_digest_it_was_not_given_and_says_so(plan: ChangePlan) -> None:
    """An unchecked leg is not a pass: the caller's report carries `checked`."""
    assert drawapply.guard_problems(plan) == []


def test_the_guard_refuses_a_library_whose_geometry_moved(plan: ChangePlan, profiles) -> None:
    """C6's pre-write leg: the same symbol, drawn differently (a profile edit)."""
    moved = dict(profiles)
    original = moved["R0402"]
    moved["R0402"] = SymbolProfile(
        symbol_ref="R0402", title=original.title,
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[type(pin)(number=pin.number, tip=(pin.tip[0], pin.tip[1] * 2),
                        name=pin.name, direction=pin.direction)
              for pin in original.pins],
    )
    assert moved["R0402"].geometry_hash() != original.geometry_hash()
    problems = drawapply.library_problems(plan, moved)
    assert problems and "R0402" in problems[0] and "geometry changed" in problems[0]


def test_the_guard_refuses_a_library_missing_a_symbol(plan: ChangePlan, profiles) -> None:
    partial = {"PWR-GND": profiles["PWR-GND"]}
    problems = drawapply.library_problems(plan, partial)
    assert any("R0402" in item and "missing" in item for item in problems)


def test_the_guard_refuses_nothing_without_a_profiles_document(plan: ChangePlan) -> None:
    """`None` is "not checked" — the CLI reports that, it is not a clean bill."""
    assert drawapply.library_problems(plan, None) == []


def test_the_guard_refuses_a_canvas_somebody_else_changed(plan: ChangePlan) -> None:
    """C5: a hand edit shows up as a census that is no longer the plan's."""
    page = _page_matching(plan)
    census = drawapply.canvas_census(page)
    bound = drawapply.module_plan(
        _layout(plan), CircuitSpec.load(CIRCUIT), PresentationSpec.load(PRESENTATION),
        drawapply.load_library(LIBRARY), lcsc_by_part=LCSC,
        baseline=type(plan.change.draw_baseline)(
            page_uuid="page-1", components=census.components,
            wire_count=census.wire_count, netflag_count=census.netflag_count,
            digest=census.digest,
        ),
    )
    assert drawapply.guard_problems(bound, page_uuid="page-1", geometry=page) == []
    touched = json.loads(json.dumps(page))
    touched["components"].append(
        {"primitiveId": "p-extra",
         "state": {"Designator": "R7", "X": 300, "Y": -300, "ComponentType": "part"}}
    )
    problems = drawapply.guard_problems(bound, page_uuid="page-1", geometry=touched)
    assert problems and "054 C5" in problems[0]


def test_the_guard_refuses_a_canvas_that_is_not_the_expected_census(plan: ChangePlan) -> None:
    """The same guard with the digest a previous run's report quoted."""
    page = _page_matching(plan)
    digest = drawapply.canvas_census(page).digest
    assert drawapply.guard_problems(plan, geometry=page, expect_census=digest) == []
    problems = drawapply.guard_problems(plan, geometry=page, expect_census="3" * 64)
    assert problems and "expected" in problems[0]


def test_the_guard_refuses_a_page_that_is_not_the_plans(plan: ChangePlan) -> None:
    bound = drawapply.module_plan(
        _layout(plan), CircuitSpec.load(CIRCUIT), PresentationSpec.load(PRESENTATION),
        drawapply.load_library(LIBRARY), lcsc_by_part=LCSC,
        baseline=type(plan.change.draw_baseline)(page_uuid="page-1"),
    )
    assert bound.source.page_uuid == "page-1"
    problems = drawapply.guard_problems(bound, page_uuid="page-2")
    assert problems and "page-1" in problems[0] and "page-2" in problems[0]


def test_the_census_is_the_pages_own_census(plan: ChangePlan) -> None:
    page = _page_matching(plan)
    census = drawapply.canvas_census(page)
    assert census.components == ["R1", "R2"]
    assert census.wire_count == len(plan.change.draw_wires)
    assert census.netflag_count == len(plan.change.draw_flags)
    assert census.digest == drawapply.census_digest(census)
    # A flag has no designator (ComponentType netflag), which is why the
    # designator set cannot see it and the count exists.
    assert "R1" in census.components and census.netflag_count == 2


def _layout(plan: ChangePlan) -> LayoutPlan:
    """The layout a built plan came from — recovered from the plan itself.

    The tests that need a *bound* plan want the same drawing with a baseline, and
    rebuilding the layout from the fixture is one compile; taking it from the
    already-built plan keeps the two identical by construction.
    """
    profiles = drawapply.load_library(LIBRARY)
    compiled = drawcompiler.compile(
        CircuitSpec.load(CIRCUIT), PresentationSpec.load(PRESENTATION), profiles,
        drawcompiler.CompileBudget(page_box=PAGE_BOX),
    )
    return compiled.candidates[plan.change.candidate]


# ------------------------------------------------------- 4. postconditions


def test_the_postconditions_hold_for_a_page_that_is_the_plan(plan: ChangePlan) -> None:
    page = _page_matching(plan)
    state = drawapply.postcondition_problems(
        plan,
        live=_live(("R1", {"1": "VIN", "2": "TAP"}), ("R2", {"1": "TAP", "2": "GND"})),
        geometry=page,
        pins=_pins_from_plan(plan),
    )
    assert set(state) == {"live", "canvas"}, "036's shape, leg by leg"
    assert state == {"live": [], "canvas": []}
    assert drawapply.all_satisfied(state)


def test_the_postcondition_shape_is_the_one_036_reads(plan: ChangePlan) -> None:
    """`all_satisfied` reads the same dict `subcircuit`'s does — the flows share it."""
    from boardwise.engines import subcircuit

    broken = {"live": ["a"], "canvas": []}
    assert drawapply.all_satisfied(broken) is False
    assert subcircuit.all_satisfied(broken) is False
    assert drawapply.all_satisfied({"live": [], "canvas": []}) is True
    assert drawapply.all_satisfied({}) is True


def test_the_netlist_leg_is_membership_not_names(plan: ChangePlan) -> None:
    """The editor's auto names are meaningless; which pins are together is not."""
    live = _live(("R1", {"1": "$57N1", "2": "$57N2"}),
                 ("R2", {"1": "$57N2", "2": "$57N3"}))
    state = drawapply.postcondition_problems(plan, live=live)
    assert state["live"] == [], "two auto-named islands, the same partition"
    split = _live(("R1", {"1": "VIN", "2": "TAP"}), ("R2", {"1": "OTHER", "2": "GND"}))
    state = drawapply.postcondition_problems(plan, live=split)
    assert state["live"] and "R1.2" in state["live"][0]


def test_the_netlist_leg_judges_the_plans_own_pins_and_reports_the_rest(plan: ChangePlan) -> None:
    """The editor's netlist is **project-wide** (054 C7): a shared net *name* merges
    pages, and the second module would be refused by an exact-membership reading.

    Judged: the plan's own pins' partition. Reported: the company from elsewhere.
    """
    # Another page's R1 lands on the same names — exactly what the live C7 run saw.
    live = _live(
        ("R1", {"1": "VIN", "2": "TAP"}),          # the plan's own two
        ("R2", {"1": "TAP", "2": "GND"}),
        ("R9", {"1": "VIN", "2": "GND"}),          # a part on another page
    )
    state = drawapply.postcondition_problems(plan, live=live)
    assert state["live"] == [], "the module's own pin groups are exactly as planned"
    rows = drawapply.live_islands(plan, live)
    assert [row["others"] for row in rows if row["pin"] == "R1.1"] == [["R9.1"]]
    assert sorted({item for row in rows for item in row["others"]}) == ["R9.1", "R9.2"]
    # …but a short *inside* the plan is still a failure: R1.1 and R1.2 on one net.
    shorted = _live(("R1", {"1": "VIN", "2": "VIN"}), ("R2", {"1": "VIN", "2": "GND"}))
    state = drawapply.postcondition_problems(plan, live=shorted)
    assert state["live"] and "R1.2" in state["live"][0]


def test_a_part_off_its_spot_is_a_canvas_problem(plan: ChangePlan) -> None:
    page = _page_matching(plan)
    page["components"][0]["state"]["X"] += 25.0
    state = drawapply.postcondition_problems(plan, geometry=page, pins=_pins_from_plan(plan))
    assert state["canvas"] and "further apart than" in state["canvas"][0]


def test_a_pin_that_reads_back_off_its_tip_is_a_canvas_problem(plan: ChangePlan) -> None:
    """Protection 3: the API's own answer is compared, never believed."""
    page = _page_matching(plan)
    pins = _pins_from_plan(plan)
    pins[("R1", "1")] = (pins[("R1", "1")][0], pins[("R1", "1")][1] - 20.0)
    state = drawapply.postcondition_problems(plan, geometry=page, pins=pins)
    assert state["canvas"] and "054 C6" in state["canvas"][0]
    # Within half a lattice step it is still the plan's pin.
    near = _pins_from_plan(plan)
    near[("R1", "1")] = (near[("R1", "1")][0], near[("R1", "1")][1] - drawapply.HALF_GRID)
    assert drawapply.postcondition_problems(plan, geometry=page, pins=near)["canvas"] == []


def test_a_missing_wire_endpoint_is_a_canvas_problem(plan: ChangePlan) -> None:
    page = _page_matching(plan)
    page["wires"] = page["wires"][:-1]
    state = drawapply.postcondition_problems(plan, geometry=page, pins=_pins_from_plan(plan))
    assert state["canvas"] and "no wire vertex" in state["canvas"][0]
    assert any("a segment did not land" in item for item in state["canvas"])


def test_the_flag_count_is_part_of_the_canvas_leg(plan: ChangePlan) -> None:
    page = _page_matching(plan)
    page["components"] = [
        item for item in page["components"] if item["primitiveId"] != "flag-0"
    ]
    state = drawapply.postcondition_problems(
        plan, geometry=page, pins=_pins_from_plan(plan), flags_before=0
    )
    assert state["canvas"] and "flag" in state["canvas"][0]


def test_unread_pins_are_reported_rather_than_passed(plan: ChangePlan) -> None:
    state = drawapply.postcondition_problems(plan, geometry=_page_matching(plan), pins={})
    assert state["canvas"] and "not read back" in state["canvas"][0]


# ------------------------------------------------- 5. the refusals say why


def test_a_part_without_an_lcsc_refuses_and_names_it(compiled, profiles) -> None:
    payload = json.loads(CIRCUIT.read_text(encoding="utf-8"))
    payload["parts"][0].pop("lcsc")
    stripped = CircuitSpec.from_dict(payload)
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(compiled.candidates[0], stripped, _presentation(), profiles)
    assert "R1" in str(caught.value) and "LCSC" in str(caught.value)
    # …and the refusal names the flag that would fix it.
    assert "--lcsc R1=" in str(caught.value)
    assert drawapply.module_plan(
        compiled.candidates[0], stripped, _presentation(), profiles, lcsc_by_part=LCSC
    ).change.draw_parts[0].lcsc == "C25744"


def _presentation() -> PresentationSpec:
    return PresentationSpec.load(PRESENTATION)


def test_a_part_without_a_value_refuses_and_names_it(compiled, profiles) -> None:
    payload = json.loads(CIRCUIT.read_text(encoding="utf-8"))
    payload["parts"][0].pop("value")
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(
            compiled.candidates[0], CircuitSpec.from_dict(payload), _presentation(),
            profiles, lcsc_by_part=LCSC,
        )
    assert "R1" in str(caught.value) and "value" in str(caught.value)


def test_a_layout_drawn_with_a_symbol_the_library_lacks_refuses(compiled, presentation) -> None:
    thin = {"R0402": drawapply.load_library(LIBRARY)["R0402"]}
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(compiled.candidates[0], _circuit(), presentation, thin,
                              lcsc_by_part=LCSC)
    assert "PWR-VIN" in str(caught.value) or "PWR-GND" in str(caught.value)


def _circuit() -> CircuitSpec:
    return CircuitSpec.load(CIRCUIT)


def test_a_library_that_disagrees_with_the_layout_refuses(compiled, presentation, profiles) -> None:
    """The layout's own symbol hash is the authority; a different geometry is refused.

    The same symbol *name* with a different drawing — a library that moved
    underneath the layout. The keyed-by-symbol check above catches a book whose
    keys and profiles disagree; this catches the quieter one, where the book is
    internally consistent and simply is not the book the layout was compiled from.
    """
    taller = SymbolProfile(
        symbol_ref="R0402", title="Resistor, longer leads",
        body=(-10.0, -20.0, 10.0, 20.0),
        pins=[type(pin)(number=pin.number, tip=(pin.tip[0], pin.tip[1] * 2),
                        name=pin.name, direction=pin.direction)
              for pin in profiles["R0402"].pins],
    )
    swapped = {**profiles, "R0402": taller}
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(compiled.candidates[0], _circuit(), presentation, swapped,
                              lcsc_by_part=LCSC)
    assert "R0402" in str(caught.value) and "hashes" in str(caught.value)


def test_a_book_whose_keys_and_profiles_disagree_refuses(compiled, presentation, profiles) -> None:
    swapped = {**profiles, "R0402": profiles["R-AXIAL"]}
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(compiled.candidates[0], _circuit(), presentation, swapped,
                              lcsc_by_part=LCSC)
    assert "keyed by the symbol it describes" in str(caught.value)


def test_a_plan_around_a_flag_this_host_cannot_name_refuses(plan: ChangePlan, profiles) -> None:
    """A flag is placed by kind, and the kind has to come from somewhere."""
    layout = _layout(plan)
    layout.power_symbols[0].symbol_ref = "FLAG-SIG"
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.module_plan(layout, _circuit(), _presentation(), profiles,
                              lcsc_by_part=LCSC)
    assert "TAP" not in str(caught.value) and "VIN" in str(caught.value)


# ------------------------------------------------------- 6. schema refusals


def _plan_payload(plan: ChangePlan) -> dict:
    return json.loads(json.dumps(plan.to_jsonable()))


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda p: p["change"].pop("layoutSha256"), "layoutSha256"),
        (lambda p: p["change"].__setitem__("circuitSha256", "nope"), "circuitSha256"),
        (lambda p: p["change"].__setitem__("profiles", []), "profiles"),
        (lambda p: p["change"]["parts"][0].__setitem__("lcsc", ""), "lcsc"),
        (lambda p: p["change"]["parts"][0].pop("pins"), "pins"),
        (lambda p: p["change"]["parts"][1].__setitem__("designator", "R1"), "already used"),
        (lambda p: p["change"]["parts"][0].__setitem__("rotation", 45), "rotation"),
        (lambda p: p["change"]["wires"][0]["points"].__setitem__(
            1, [p["change"]["wires"][0]["points"][0][0] + 5,
                p["change"]["wires"][0]["points"][0][1] + 5]), "diagonally"),
        (lambda p: p["change"]["wires"][0].__setitem__(
            "fromPin", ["R1.1"] and "R9.1"), "fromPin"),
        (lambda p: p["change"]["flags"][0].__setitem__("kind", "Signal"), "kind"),
        (lambda p: p["change"]["flags"][1].__setitem__("kind", "Power"), "Ground"),
        (lambda p: p["change"]["islands"][0].__setitem__("pin", "R9.1"), "island"),
        (lambda p: p["change"]["baseline"].__setitem__("wireCount", -1), "wireCount"),
        (lambda p: p["change"]["parts"].append(p["change"]["parts"][0]), "specId"),
    ],
)
def test_the_plan_schema_refuses_what_apply_cannot_execute(
    plan: ChangePlan, mutate, needle: str
) -> None:
    payload = _plan_payload(plan)
    mutate(payload)
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert needle in str(caught.value)


def test_the_plan_schema_accepts_the_other_kinds(plan: ChangePlan) -> None:
    """The new kind must not make the old documents unreadable."""
    from boardwise.core.changeplan import MOVE_BLOCK_KIND, SUPPORTED_KINDS

    assert DRAW_MODULE_KIND in SUPPORTED_KINDS
    assert MOVE_BLOCK_KIND in SUPPORTED_KINDS
    payload = _plan_payload(plan)
    payload["change"]["kind"] = "no-such-kind"
    with pytest.raises(ChangePlanError) as caught:
        ChangePlan.from_jsonable(payload)
    assert "this build executes" in str(caught.value)


def test_the_library_reader_refuses_what_the_schema_refuses(tmp_path: Path, profiles) -> None:
    """A malformed library is refused by `SymbolProfile.from_dict`, once."""
    broken = tmp_path / "library.json"
    broken.write_text(json.dumps({"profiles": [
        {"symbolRef": "R0402", "body": [-1, -1, 1, 1],
         "pins": [{"number": "1", "tip": [0, 0]}, {"number": "2", "tip": [0, 0]}]}
    ]}), encoding="utf-8")
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.load_library(broken)
    # A mapping document is the other accepted shape, keyed by symbol.
    mapped = tmp_path / "mapped.json"
    mapped.write_text(json.dumps({
        "R0402": profiles["R0402"].to_jsonable(),
    }), encoding="utf-8")
    assert sorted(drawapply.load_library(mapped)) == ["R0402"]
    duplicated = tmp_path / "dup.json"
    duplicated.write_text(json.dumps({"profiles": [
        profiles["R0402"].to_jsonable(), profiles["R0402"].to_jsonable()
    ]}), encoding="utf-8")
    with pytest.raises(drawapply.DrawPlanError) as caught:
        drawapply.load_library(duplicated)
    assert "twice" in str(caught.value)


def test_the_grid_the_plan_is_built_on_is_the_lattice(plan: ChangePlan) -> None:
    """The plan's own 5-unit lattice, and half of it is the pin tolerance."""
    assert DRAW_GRID == 5.0
    assert drawapply.HALF_GRID == DRAW_GRID / 2.0
    assert drawapply.HALF_GRID == 2.5
    for part in plan.change.draw_parts:
        assert part.x % DRAW_GRID == 0 and part.y % DRAW_GRID == 0
    for wire in plan.change.draw_wires:
        for x, y in wire.points:
            assert x % DRAW_GRID == 0 and y % DRAW_GRID == 0
