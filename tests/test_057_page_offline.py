"""057 stage C2b, the offline half: page locks, keep-out relocation, the census
functions, discard's identity check, the three 056 leftovers.

What the fake editor cannot decide is decided here, on the engines directly:

1. **page locks** (057 sec.3) — the locked part is on its lock point in *every*
   candidate, each generation deriving its own origin; a lock that cannot hold is
   `presentation-poor` naming the lock(s); a page lock and a module lock on one
   part coexist;
2. **relocation** (057 sec.2) — census keep-outs move the arrangement as a rigid
   body; with the switch off, 056's refusal is unchanged (scene 6's contract);
3. **the census** — every existing primitive a keep-out (measured, or an assumed
   box that says so), and "nothing else moved" judged field by field;
4. **discard's identity** — designator + position + value, a merged wire is never
   a partial delete, a page document is found by position;
5. **the leftovers** — the divider's signal-driven top (O1), the page router's
   memo being answer-for-answer the module router (O2, with the scene-7 time),
   the Greek mu decoupling hint.

The 053B / 056 hard invariants are the existing batteries' (their scene hashes
are pinned there); this file adds the O2 equivalence proof on top of them.
"""

from __future__ import annotations

import dataclasses
import json
import time

import pytest

import test_053b_drawcompiler as b053
import test_056_pagecompiler as m056

from boardwise.core.changeplan import (
    DRAW_MODULE_KIND,
    ChangePlan,
    PlanChange,
    PlanDrawFlag,
    PlanDrawPart,
    PlanDrawWire,
)
from boardwise.core.layoutplan import LayoutLabel
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.presentationspec import (
    LOCK_SCOPE_PAGE,
    PresentationSpec,
    PresentationSpecError,
)
from boardwise.engines import drawapply, drawcompiler, pagecompiler, readability
from boardwise.engines.generate import _decoupling_next_to_host

PROV = "verified_recipe"


def _with_locks(presentation: PresentationSpec, locks: list[dict]) -> PresentationSpec:
    payload = presentation.to_jsonable()
    payload["userLocks"] = locks
    return PresentationSpec.from_dict(payload)


def _scene1(locks: list[dict] | None = None):
    scene = m056.scenes()[1]
    presentation = (
        _with_locks(scene.presentation, locks) if locks is not None else scene.presentation
    )
    return scene, presentation


# ------------------------------------------------------- the lock's schema


def test_a_page_lock_states_its_scope_and_no_rotation():
    presentation = _with_locks(
        m056.scenes()[1].presentation,
        [{"partId": "R1", "x": 600, "y": 500, "scope": "page"}],
    )
    (lock,) = presentation.user_locks
    assert lock.is_page and lock.scope == LOCK_SCOPE_PAGE
    assert presentation.to_jsonable()["userLocks"] == [
        {"partId": "R1", "x": 600.0, "y": 500.0, "scope": "page"}
    ]
    assert presentation.page_locks() == [lock]


def test_a_module_lock_serialises_exactly_as_before_so_digests_do_not_move():
    payload = m056.scenes()[1].presentation.to_jsonable()
    payload["userLocks"] = [{"partId": "R1", "x": 0, "y": 0, "rotation": 90}]
    spec = PresentationSpec.from_dict(payload)
    assert spec.to_jsonable()["userLocks"] == [
        {"partId": "R1", "x": 0.0, "y": 0.0, "rotation": 90.0}
    ], "no `scope` key on a module lock: a pre-057 spec keeps its digest"


@pytest.mark.parametrize(
    "locks, fragment",
    [
        ([{"partId": "R1", "x": 1, "y": 2, "rotation": 90, "scope": "page"}], "rotation"),
        ([{"partId": "R1", "x": 1, "y": 2, "scope": "sheet"}], "scope"),
        ([{"partId": "R1", "x": 1, "y": 2, "scope": "page"},
          {"partId": "R1", "x": 3, "y": 4, "scope": "page"}], "already locked on the page"),
        ([{"partId": "R1", "x": 1, "y": 2},
          {"partId": "R1", "x": 3, "y": 4}], "already locked"),
    ],
    ids=["page-lock-with-rotation", "unknown-scope", "two-page-locks", "two-module-locks"],
)
def test_the_lock_schema_refuses_what_cannot_be_meant(locks, fragment):
    with pytest.raises(PresentationSpecError) as caught:
        _with_locks(m056.scenes()[1].presentation, locks)
    assert fragment in str(caught.value)


def test_one_part_may_carry_a_module_lock_and_a_page_lock():
    spec = _with_locks(
        m056.scenes()[1].presentation,
        [{"partId": "R1", "x": 0, "y": 0, "rotation": 0},
         {"partId": "R1", "x": 600, "y": 500, "scope": "page"}],
    )
    assert [lock.scope for lock in spec.user_locks] == ["module", "page"]


# ----------------------------------------------------------- page locks


def test_a_page_lock_puts_the_part_on_its_point_in_every_candidate():
    scene, presentation = _scene1([{"partId": "R1", "x": 600, "y": 500, "scope": "page"}])
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), scene.budget)
    assert result.ok, result.render_failures()
    for page in result.pages:
        part = page.plan.part("R1")
        assert (part.x, part.y) == (600.0, 500.0)
        sense = page.module("sense")
        local = result.modules["sense"].candidates
        # origin = P − L(generation): the module moved, the part did not.
        assert any(
            sense.origin == (600.0 - item.part("R1").x, 500.0 - item.part("R1").y)
            for item in local
        )
        drawing, domain = m056.recheck(page, dataclasses.replace(scene, presentation=presentation))
        assert not drawing.hard_violations and not domain.hard_violations


def test_the_nine_recheck_every_page_lock_independently():
    """`user-lock-violated` is re-run on the merged drawing with the page lock as is."""
    scene, presentation = _scene1([{"partId": "R1", "x": 600, "y": 500, "scope": "page"}])
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), scene.budget)
    page = result.pages[0]
    moved = dataclasses.replace(page.plan.part("R1"), x=605.0)
    page.plan.parts = [moved if item.part_id == "R1" else item for item in page.plan.parts]
    view = pagecompiler._page_presentation_view(
        pagecompiler._Context(
            circuit=scene.circuit, presentation=presentation, book=m056.library(),
            budget=scene.budget, modules=list(presentation.modules), results={},
            views={}, nets_by_module={},
        ),
        {module.id: module.origin for module in page.modules},
        page.plan,
    )
    checked = readability.check(
        page.plan, scene.circuit, view, m056.library(), page_box=scene.budget.page_box,
    )
    assert any(item.kind == readability.KIND_USER_LOCK_VIOLATED for item in checked.hard_violations)


def test_two_page_locks_that_disagree_name_both_locks():
    scene, presentation = _scene1([
        {"partId": "R1", "x": 600, "y": 500, "scope": "page"},
        {"partId": "R2", "x": 600, "y": 500, "scope": "page"},
    ])
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), scene.budget)
    assert not result.ok
    assert result.categories() == ["presentation-poor"]
    first = result.failures[0]
    assert "userLocks[R1@page]" in first.subject and "userLocks[R2@page]" in first.subject
    assert first.action


@pytest.mark.parametrize(
    "locks, fragment",
    [
        ([{"partId": "R1", "x": 3000, "y": 500, "scope": "page"}], "outside the page"),
        ([{"partId": "U1", "x": 25, "y": 25, "scope": "page"}], "leaves the page"),
        ([{"partId": "U1", "x": 300, "y": 400, "scope": "page"},
          {"partId": "R1", "x": 320, "y": 420, "scope": "page"}], "module gap"),
    ],
    ids=["point-off-the-page", "frame-off-the-page", "locked-frames-collide"],
)
def test_a_lock_that_cannot_hold_is_presentation_poor_naming_the_lock(locks, fragment):
    scene, presentation = _scene1(locks)
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), scene.budget)
    assert not result.ok
    assert "presentation-poor" in result.categories()
    rendered = result.render_failures()
    assert fragment in rendered
    for lock in locks:
        assert f"userLocks[{lock['partId']}@page]" in rendered


def test_a_page_lock_on_a_keepout_is_the_locks_conflict():
    scene, presentation = _scene1([{"partId": "R1", "x": 600, "y": 500, "scope": "page"}])
    budget = dataclasses.replace(scene.budget, keepouts=((550.0, 450.0, 650.0, 550.0),))
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), budget)
    assert not result.ok
    assert "userLocks[R1@page]" in result.failures[0].subject
    assert "keepouts[0]" in result.failures[0].detail


def test_a_page_lock_and_a_module_lock_on_one_part_both_hold():
    """The module lock arranges the part in its module; the page lock pins it."""
    scene, _ = _scene1()
    local = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), scene.budget
    ).modules["sense"].candidates[0].part("R1")
    scene, presentation = _scene1([
        {"partId": "R1", "x": local.x, "y": local.y, "rotation": local.rotation},
        {"partId": "R1", "x": 700, "y": 450, "scope": "page"},
    ])
    result = pagecompiler.compile_page(scene.circuit, presentation, m056.library(), scene.budget)
    assert result.ok, result.render_failures()
    for page in result.pages:
        part = page.plan.part("R1")
        assert (part.x, part.y) == (700.0, 450.0)


def test_the_module_compile_never_sees_a_page_lock():
    scene, presentation = _scene1([{"partId": "R1", "x": 600, "y": 500, "scope": "page"}])
    sense = presentation.module("sense")
    _circuit, view = pagecompiler._module_view(scene.circuit, presentation, sense)
    assert view.user_locks == []


# ------------------------------------------------------------ relocation


def test_relocation_moves_the_arrangement_off_the_census_as_a_rigid_body():
    scene = m056.scenes()[2]
    keepout = (0.0, 500.0, 420.0, 826.0)
    budget = dataclasses.replace(
        scene.budget, keepouts=(keepout,), relocate_around_keepouts=True,
    )
    result = pagecompiler.compile_page(scene.circuit, scene.presentation, m056.library(), budget)
    assert result.ok, result.render_failures()
    reference = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), scene.budget
    )
    for page in result.pages:
        for module in page.modules:
            frame = module.frame
            assert not (min(frame[2], keepout[2]) - max(frame[0], keepout[0]) > 0
                        and min(frame[3], keepout[3]) - max(frame[1], keepout[1]) > 0)
    # Rigid: the frames keep their sizes and their relative placement.
    moved, anchored = result.pages[0], reference.pages[0]
    sizes = lambda page: {  # noqa: E731
        module.id: (module.frame[2] - module.frame[0], module.frame[3] - module.frame[1])
        for module in page.modules
    }
    assert sizes(moved) == sizes(anchored)


def test_without_the_switch_a_keepout_keeps_its_056_meaning():
    scene = m056.scenes()[2]
    budget = dataclasses.replace(scene.budget, keepouts=((0.0, 500.0, 420.0, 826.0),))
    result = pagecompiler.compile_page(scene.circuit, scene.presentation, m056.library(), budget)
    assert not result.ok
    assert result.categories() == ["presentation-poor"]
    assert "keepouts[0]" in result.failures[0].subject


def test_scene_6_is_refused_with_or_without_relocation():
    """056 scene 6's keep-out covers every position the chain could take."""
    scene = m056.scenes()[6]
    for relocate in (False, True):
        budget = dataclasses.replace(scene.budget, relocate_around_keepouts=relocate)
        result = pagecompiler.compile_page(
            scene.circuit, scene.presentation, m056.library(), budget,
        )
        assert not result.ok and result.categories() == ["presentation-poor"]


# ------------------------------------------------------------- the census


def _geometry(**extra):
    base = {
        "components": [
            {"primitiveId": "sheet", "state": {"ComponentType": "sheet", "X": 0, "Y": 0}},
            {"primitiveId": "c1", "state": {
                "ComponentType": "part", "Designator": "R5", "X": 100, "Y": 200,
                "Rotation": 0, "Mirror": False, "SupplierId": "C25744",
                "OtherProperty": {"Value": "10k"}}},
            {"primitiveId": "c2", "state": {
                "ComponentType": "part", "Designator": "U3", "X": 400, "Y": 400,
                "Rotation": 90, "Mirror": False}},
            {"primitiveId": "f1", "state": {
                "ComponentType": "netflag", "Net": "GND", "X": 100, "Y": 100}},
        ],
        "wires": [{"primitiveId": "w1", "state": {"Line": [100, 250, 100, 300, 150, 300],
                                                  "Net": "SIG"}}],
        "bboxes": {"sheet": {"minX": 0, "minY": 0, "maxX": 1169, "maxY": 826},
                   "c1": {"minX": 90, "minY": 150, "maxX": 110, "maxY": 250}},
    }
    base.update(extra)
    return base


def test_every_existing_primitive_becomes_a_named_keepout():
    boxes, labels, notes = drawapply.census_keepouts(_geometry())
    assert len(boxes) == len(labels) == 5  # R5, U3, the flag, two wire segments
    measured = boxes[labels.index("existing R5 c1")]
    assert measured == (85.0, 145.0, 115.0, 255.0), "the measured box, grown one step"
    assumed = boxes[labels.index("existing U3 c2")]
    assert assumed == (345.0, 345.0, 455.0, 455.0)
    assert any("U3" in line and "assumed" in line for line in notes)
    assert not any("sheet" in label for label in labels)
    segment = boxes[labels.index("existing wire w1 (SIG)")]
    assert segment[2] - segment[0] > 0, "a wire is a box with area once it has clearance"


def test_census_changes_sees_every_field_and_ignores_only_what_it_is_told():
    before = drawapply.census_items(_geometry())
    assert drawapply.census_changes(before, before) == []
    moved = _geometry()
    moved["components"][1]["state"]["X"] = 105
    moved["components"][1]["state"]["OtherProperty"] = {"Value": "12k"}
    moved["wires"][0]["state"]["Line"] = [100, 250, 100, 300, 160, 300]
    del moved["components"][3]
    changes = drawapply.census_changes(before, drawapply.census_items(moved))
    text = " | ".join(changes)
    assert "R5 (c1) changed" in text and "x 100.0 → 105.0" in text and "value" in text
    assert "(w1) changed" in text and "points" in text
    assert "(f1) is no longer on the page" in text
    assert drawapply.census_changes(
        before, drawapply.census_items(moved), ignore_ids={"c1", "w1", "f1"},
    ) == []


def test_an_auto_net_renumbered_elsewhere_is_not_a_change_but_a_renamed_net_is():
    """Pit 25: the host renumbers auto nets when wiring changes somewhere else."""
    auto = _geometry()
    auto["wires"][0]["state"]["Net"] = "$1N5"
    before = drawapply.census_items(auto)
    renumbered = _geometry()
    renumbered["wires"][0]["state"]["Net"] = "$1N9"
    assert drawapply.census_changes(before, drawapply.census_items(renumbered)) == []
    renamed = _geometry()
    renamed["wires"][0]["state"]["Net"] = "OTHER"
    assert drawapply.census_changes(
        drawapply.census_items(_geometry()), drawapply.census_items(renamed),
    )


# --------------------------------------------------------- discard identity


def _plan(parts=(), wires=(), flags=()) -> ChangePlan:
    plan = ChangePlan()
    plan.change = PlanChange(
        kind=DRAW_MODULE_KIND, draw_parts=list(parts), draw_wires=list(wires),
        draw_flags=list(flags),
    )
    return plan


def _part(designator="R5", x=100.0, y=200.0, value="10k", prefix="R", spec="R1"):
    return PlanDrawPart(spec_id=spec, designator=designator, prefix=prefix,
                        lcsc="C25744", value=value, value_key="Value", x=x, y=y)


def test_discard_matches_designator_position_and_value():
    selection = drawapply.discard_selection(
        _plan([_part()], [PlanDrawWire(net="SIG", points=[(100, 250), (100, 300), (150, 300)])],
              [PlanDrawFlag(net="GND", kind="Ground", x=100, y=100)]),
        _geometry(),
    )
    assert not selection.mismatches
    assert selection.ids == ["w1", "f1", "c1"], "lines first, then flags, then parts"


@pytest.mark.parametrize(
    "part, fragment",
    [
        (_part(value="4k7"), "its Value is '10k', the plan wrote '4k7'"),
        (_part(x=150.0), "the plan put it at (150, 200)"),
    ],
    ids=["wrong-value", "moved"],
)
def test_discard_refuses_a_part_that_is_not_the_plans(part, fragment):
    selection = drawapply.discard_selection(_plan([part]), _geometry())
    assert selection.parts == []
    assert any(fragment in line for line in selection.mismatches)


def test_discard_never_deletes_a_wire_merged_with_a_foreign_one():
    selection = drawapply.discard_selection(
        _plan(wires=[PlanDrawWire(net="SIG", points=[(100, 250), (100, 300)])]),
        _geometry(),
    )
    assert selection.wires == []
    assert any("merged" in line for line in selection.mismatches)


def test_discard_reports_what_is_not_there_as_absent_not_as_a_mismatch():
    selection = drawapply.discard_selection(
        _plan([_part(designator="R99")],
              [PlanDrawWire(net="OTHER", points=[(0, 0), (0, 10)])],
              [PlanDrawFlag(net="GND", kind="Ground", x=700, y=700)]),
        _geometry(),
    )
    assert selection.empty and not selection.mismatches
    assert len(selection.absent) == 3


def test_a_part_without_a_designator_is_found_by_position_and_prefix():
    selection = drawapply.discard_selection(
        _plan([_part(designator="", spec="R1")]), _geometry(),
    )
    assert selection.parts == [("c1", "R5")]
    wrong_prefix = drawapply.discard_selection(
        _plan([_part(designator="", prefix="C", spec="C1")]), _geometry(),
    )
    assert wrong_prefix.parts == [] and wrong_prefix.absent


# ------------------------------------------------------------- label stubs


def test_a_label_stub_leaves_its_anchor_towards_the_labels_own_text():
    east = LayoutLabel(net="VIN", text="VIN", bbox=(100.0, 95.0, 130.0, 105.0), x=100.0, y=100.0)
    assert drawapply._label_stub(east) == (110.0, 100.0)
    north = LayoutLabel(net="VIN", text="VIN", bbox=(85.0, 100.0, 115.0, 120.0), x=100.0, y=100.0)
    assert drawapply._label_stub(north) == (100.0, 110.0)
    narrow = LayoutLabel(net="V", text="V", bbox=(93.0, 100.0, 107.0, 106.0), x=100.0, y=100.0)
    assert drawapply._label_stub(narrow) == (100.0, 105.0), "never beyond the text box"


# ------------------------------------------------ O1: a signal-driven divider


def _signal_divider(*, declared: bool = True, with_rail: bool = False):
    parts = [b053.part("R1", "R0402", "10k"), b053.part("R2", "R0402", "10k")]
    nets = [
        b053.net("SENSE", "signal", ["R1.1"]),
        b053.net("ADC", "signal", ["R1.2", "R2.1"]),
        b053.net("GND", "gnd", ["R2.2"]),
    ]
    if with_rail:
        parts += [b053.part("R3", "R0402", "10k"), b053.part("R4", "R0402", "10k")]
        nets += [
            b053.net("VIN", "power", ["R3.1"]),
            b053.net("MID", "signal", ["R3.2", "R4.1"]),
        ]
        nets[2] = b053.net("GND", "gnd", ["R2.2", "R4.2"])
    circuit = b053.circuit(parts, nets)
    roles = {"SENSE": "input", "ADC": "output"} if declared else {"ADC": "output"}
    presentation = b053.presentation(
        "voltage-divider",
        modules=[b053.module("d", [part["id"] for part in parts], "divider")],
        portRoles=roles,
    )
    return circuit, presentation


def test_o1_a_divider_driven_by_a_declared_signal_port_is_drawn():
    circuit, presentation = _signal_divider()
    result = drawcompiler.compile(circuit, presentation, b053.library())
    assert result.ok, result.render_failures()
    roles = {binding.role: binding.part_id for binding in result.grammar.bindings}
    assert roles["in"] == "SENSE" and roles["upper_arm"] == "R1" and roles["tap"] == "ADC"
    top = next(binding for binding in result.grammar.bindings if binding.role == "in")
    assert "portRoles[SENSE]=input" in top.evidence
    for plan in result.candidates:
        assert any(label.net == "SENSE" for label in plan.labels), (
            "a signal top is a port (a name), never a rail flag"
        )
        assert not any(symbol.net == "SENSE" for symbol in plan.power_symbols)


def test_o1_an_undeclared_signal_top_keeps_the_tables_refusal_word_for_word():
    circuit, presentation = _signal_divider(declared=False)
    result = drawcompiler.compile(circuit, presentation, b053.library())
    assert not result.ok and result.categories() == ["facts-missing"]
    assert "no net of class 'power'" in result.failures[0].detail


def test_o1_the_power_reading_stays_the_first_reading():
    """With a rail chain present, the signal branch is never consulted."""
    from boardwise.engines.grammar import voltage_divider

    circuit, presentation = _signal_divider(with_rail=True)
    bound = voltage_divider.grammar(b053.library()).bind(circuit, presentation)
    roles = {binding.role: binding.part_id for binding in bound.bindings}
    assert roles["in"] == "VIN"


# ----------------------------------------------------- O2: the page router


def _compile_documents(scene):
    result = pagecompiler.compile_page(
        scene.circuit, scene.presentation, m056.library(), scene.budget,
    )
    return [json.dumps(page.to_jsonable(), sort_keys=True) for page in result.pages]


def test_o2_the_page_routers_memo_answers_exactly_as_the_module_router(monkeypatch):
    """Same pages, byte for byte, with the memo taken out (scene 7 routes by search)."""
    scene = m056.scenes()[7]
    with_memo = _compile_documents(scene)
    monkeypatch.setattr(pagecompiler, "_PageRouter", drawcompiler.lattice_router)
    without = _compile_documents(scene)
    assert with_memo == without and with_memo


def test_o2_scene_7s_shape_routes_under_two_seconds_a_variant(monkeypatch):
    scene = m056.scenes()[7]
    original = pagecompiler._assemble
    times: list[float] = []

    def timed(ctx, variant):
        started = time.perf_counter()
        try:
            return original(ctx, variant)
        finally:
            times.append(time.perf_counter() - started)

    monkeypatch.setattr(pagecompiler, "_assemble", timed)
    best = None
    for _attempt in range(2):
        times.clear()
        pagecompiler.compile_page(
            scene.circuit, scene.presentation, m056.library(), scene.budget,
        )
        slowest = max(times)
        best = slowest if best is None else min(best, slowest)
    assert best is not None and best < 2.0, f"slowest variant took {best:.2f} s"


# ------------------------------------------------ the Greek-mu decoupling hint


def test_the_greek_mu_spelling_is_a_decoupling_hint_like_the_micro_sign():
    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1",
                                       pins=[Pin(number="1", name="VCC")])
    for designator, value in (("C1", "22μF"), ("C2", "22µF"), ("R1", "10k")):
        model.components[designator] = Component(
            uid=designator.lower(), designator=designator, value=value,
            pins=[Pin(number="1", name="")],
        )
    model.nets["VCC"] = Net(name="VCC", pins=[("U1", "1"), ("C1", "1"), ("C2", "1"),
                                              ("R1", "1")])
    assert _decoupling_next_to_host(model, "U1") == {"C1", "C2"}
