"""143d: the names a drawing carries into a plan — kept designators, `segment.net`,
and what a flag's symbol says.

Three holes, one theme: a name that was written down and then read by nobody.

1. **`--keep-names` landed an unvalidated spec id as a designator** (hole 4). A
   spec id is only checked for being non-empty, dot-free and unique; nothing makes
   it a *designator*. ``C10?`` is the editor's own "not numbered yet", so the plan
   compiled, the parts were placed, the values written — and the pin read-back then
   reported ``C10? is not on the page`` (exit 3, no save, half a drawing on the
   canvas that only `draw discard` can clean up).
2. **a segment's `net` was read by neither judge and written by apply** (F5).
   `readability` derives the netlist from *declared* names only (052 sec.4 says so)
   and `check_grammar` never reads ``segment.net``, while `sch.place_wire` is handed
   exactly that string (029-b: a wire's net *is* its name on the canvas). Renaming a
   TAP segment to ``VIN`` in a compiled divider came back hard=0 / grammar=0.
3. **a flag's `symbolRef` and the flag's kind were never compared where the name was
   unknown** (F6). ``power_flag_kind('VIN5')`` answers ``''`` — the host's rail
   vocabulary does not know that name — so the kind came entirely from the symbol,
   and ``PWR-GND`` on ``VIN5`` answered ``Ground``: apply would put a ground flag on
   a supply rail, which is what the editor's netlist then carries (029-d).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.changeplan import (
    DRAW_FLAG_GROUND,
    DRAW_FLAG_POWER,
    DRAW_MODULE_KIND,
    ChangePlan,
    PlanChange,
    PlanDrawPart,
)
from boardwise.core.layoutplan import (
    LayoutLabel,
    LayoutPart,
    LayoutPlan,
    LayoutPowerSymbol,
    LayoutSegment,
    LayoutSource,
    LayoutTarget,
)
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawapply"
CIRCUIT = FIXTURES / "divider.circuit.json"
PRESENTATION = FIXTURES / "divider.presentation.json"
LIBRARY = FIXTURES / "library.json"
PROFILES = drawapply.load_library(LIBRARY)


# ------------------------------------------------- hole 4: kept designators


def _parts(*ids: str) -> list[LayoutPart]:
    return [LayoutPart(part_id=part_id, symbol_ref="R0402") for part_id in ids]


def test_a_kept_name_must_be_a_designator():
    """The witness: `C10?` compiled, landed two parts, then could not be read back."""
    with pytest.raises(drawapply.DrawPlanError) as excinfo:
        drawapply.assign_designators(_parts("C10?", "R2"), PROFILES, [], keep_names=True)
    message = str(excinfo.value)
    assert "C10?" in message and "not a designator" in message
    assert "keep" in message.lower() and "--keep-names" in message


@pytest.mark.parametrize(
    "spec_id",
    ["C10?", "C10 ?", "R7 ", "R", "R/C", "1R", "R1.2", "Ｒ1"],
    ids=["question", "space", "trailing-space", "no-number", "slash", "digit-first",
         "dotted", "full-width"],
)
def test_every_shape_that_is_not_a_designator_is_refused(spec_id):
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.assign_designators(_parts(spec_id), PROFILES, [], keep_names=True)


def test_the_designator_shapes_the_allocator_produces_are_accepted():
    got = drawapply.assign_designators(_parts("R7", "C10", "U2"), PROFILES, [],
                                       keep_names=True)
    assert [item[2] for item in got] == ["R7", "C10", "U2"]
    for name in ("R7", "C10", "U2", "TP1", "J12"):
        assert drawapply.is_designator(name)
    for name in ("C10?", "", "R1.2", "R 1", "R", "1R"):
        assert not drawapply.is_designator(name)


def test_is_designator_is_the_allocators_own_rule():
    """One ruler: the check is `addcomponent._DESIGNATOR_RE`, not a second copy of it."""
    from boardwise.engines import addcomponent

    for name in ("R7", "C10", "R1", "c10", "R07", "C10?", "", "X", "1R", "R1a"):
        assert drawapply.is_designator(name) == bool(
            addcomponent._DESIGNATOR_RE.match(name)
        ), name


def test_a_kept_name_that_collides_only_in_case_is_refused():
    """The allocator folds the prefix; `discard_selection` folds the whole name.

    A page's ``c10`` and a kept ``C10`` are one designator with two spellings — a
    rename mid-run (036b) *and* a name two readers resolve to the same primitive.
    The check this replaces was ``designator in used``, which let exactly that pair
    through.
    """
    with pytest.raises(drawapply.DrawPlanError) as excinfo:
        drawapply.assign_designators(_parts("c10"), PROFILES, ["C10"], keep_names=True)
    assert "C10" in str(excinfo.value)
    # And the same rule at apply time, where the pool is read off the live page.
    kept = ChangePlan(change=PlanChange(
        kind=DRAW_MODULE_KIND,
        draw_keep_names=True,
        draw_parts=[PlanDrawPart(spec_id="C10", designator="C10", prefix="C",
                                 lcsc="C25744", value="10n")],
    ))
    assert drawapply.designator_problems(kept, []) == []
    problems = drawapply.designator_problems(kept, ["c10"])
    assert problems and "C10" in problems[0]


def test_apply_refuses_a_kept_plan_whose_designator_is_not_one():
    """The same check on the other side of the plan document: a hand-edited one."""
    kept = ChangePlan(change=PlanChange(
        kind=DRAW_MODULE_KIND,
        draw_keep_names=True,
        draw_parts=[PlanDrawPart(spec_id="C10?", designator="C10?", prefix="C",
                                 lcsc="C25744", value="10n")],
    ))
    problems = drawapply.designator_problems(kept, [])
    assert problems and "not a designator" in problems[0]


def test_an_allocated_plan_is_untouched_by_the_new_check():
    """`--keep-names` off is exactly the old numbering (121c's own contrast)."""
    got = drawapply.assign_designators(_parts("C10?"), PROFILES, [], keep_names=False)
    assert got == [("C10?", "C", "C1")], "the allocator never produced a bad name"


# ------------------------------------------------------- F5: segment.net


def _ladder(second_segment_net: str = "TAP1") -> LayoutPlan:
    """The divider's own TAP wiring, as the compiler laid it out (053B).

    Two segments tee at (0, -70) and a label at (120, -80) declares the node
    ``TAP1``. The second segment is the one the hole renames.
    """
    return LayoutPlan(
        source=LayoutSource(circuit_sha256="a" * 64, presentation_sha256="b" * 64),
        target=LayoutTarget(),
        parts=[LayoutPart(part_id="R1", symbol_ref="R0402")],
        segments=[
            LayoutSegment(net="VIN", points=[(0.0, 50.0), (0.0, 80.0)]),
            LayoutSegment(net="TAP1", points=[(0.0, -80.0), (120.0, -80.0)]),
            LayoutSegment(net=second_segment_net, points=[(0.0, -110.0), (0.0, -50.0)]),
        ],
        labels=[LayoutLabel(
            net="TAP1", text="TAP1", bbox=(104.0, -88.0, 136.0, -72.0),
            x=120.0, y=-80.0,
        )],
    )


def test_the_drawings_own_names_agree_on_a_compiled_layout():
    assert drawapply.net_name_problems(_ladder()) == []


def test_a_segment_renamed_to_another_net_is_refused():
    """The witness: hard=0 and grammar=0, and `sch.place_wire` would write ``VIN``."""
    problems = drawapply.net_name_problems(_ladder("VIN"))
    assert problems, "the renamed segment is on a node declared TAP1"
    assert "claims one conductor as 'TAP1' and 'VIN'" in problems[0]
    assert "segments[2] (net 'VIN')" in problems[0]


def test_module_plan_refuses_that_drawing():
    """The check runs at the one place a LayoutPlan becomes executable."""
    circuit = CircuitSpec.load(CIRCUIT)
    presentation = PresentationSpec.load(PRESENTATION)
    with pytest.raises(drawapply.DrawPlanError) as excinfo:
        drawapply.module_plan(
            _ladder("VIN"), circuit, presentation, PROFILES,
            lcsc_by_part={"R1": "C25744"}, values_by_part={"R1": "10k"},
        )
    assert "claims one conductor" in str(excinfo.value)


def test_a_label_on_another_nets_wire_is_the_same_conflict():
    """The other spelling: the *declared* name is the one that moved."""
    layout = _ladder()
    layout.labels = [LayoutLabel(
        net="GND", text="GND", bbox=(104.0, -88.0, 136.0, -72.0), x=120.0, y=-80.0,
    )]
    problems = drawapply.net_name_problems(layout)
    assert problems and "'GND'" in problems[0] and "'TAP1'" in problems[0]


def test_a_power_symbol_on_another_nets_wire_is_the_same_conflict():
    layout = _ladder()
    layout.power_symbols = [LayoutPowerSymbol(
        symbol_ref="PWR-GND", net="GND", x=0.0, y=-80.0,
    )]
    problems = drawapply.net_name_problems(layout)
    assert problems and "'GND'" in problems[0]


def test_segments_that_merely_cross_stay_two_nodes():
    """054's measured editor rule: a crossing is not a tee, a vertex on a span is."""
    layout = _ladder()
    layout.segments = [
        LayoutSegment(net="TAP1", points=[(0.0, -80.0), (120.0, -80.0)]),
        LayoutSegment(net="VIN", points=[(60.0, -120.0), (60.0, -40.0)]),
    ]
    layout.labels = []
    assert drawapply.net_name_problems(layout) == [], (
        "an interior crossing joins nothing in this host (054)"
    )


def test_a_single_segment_node_keeps_its_own_name():
    """No anchors, one segment: nothing to disagree with."""
    layout = _ladder()
    layout.labels = []
    layout.segments = [LayoutSegment(net="TAP1", points=[(0.0, -80.0), (120.0, -80.0)])]
    assert drawapply.net_name_problems(layout) == []


# -------------------------------- F5 again, on the document a human can edit


def _plan_document(*, flag_net: str, wire_net: str, flag_at=(0.0, 0.0)) -> dict:
    """A minimal draw-module document (the shape a hand-written plan.json has)."""
    return {
        "planVersion": 1,
        "source": {"inputSha256": "0" * 64},
        "target": {"module": "143d plan-level name rule"},
        "change": {
            "kind": DRAW_MODULE_KIND,
            "layoutSha256": "1" * 64,
            "circuitSha256": "2" * 64,
            "presentationSha256": "3" * 64,
            "profiles": [{"symbolRef": "R0402", "geometryHash": "4" * 64}],
            "parts": [{
                "specId": "R1", "designator": "R1", "prefix": "R", "lcsc": "C25744",
                "value": "10k", "symbolRef": "R0402", "symbolHash": "4" * 64,
                "x": 100.0, "y": 100.0, "pins": [{"number": "1", "dx": 0.0, "dy": 50.0}],
            }],
            "wires": [{"net": wire_net, "points": [[0.0, 0.0], [0.0, 80.0]]}],
            "flags": [{"net": flag_net, "kind": DRAW_FLAG_GROUND,
                       "x": flag_at[0], "y": flag_at[1]}],
        },
    }


def test_a_flag_that_stands_on_another_nets_wire_is_refused_by_the_schema():
    """The same disease from the other door: a plan.json no LayoutPlan was behind.

    `draw apply <plan.json>` never sees `net_name_problems` (that reads a
    `LayoutPlan`), so the document reader has to carry the rule too — and it is the
    document a human can hand-edit, which is F5's own trigger surface.
    """
    from boardwise.core.changeplan import ChangePlan

    with pytest.raises(Exception) as excinfo:
        ChangePlan.from_jsonable(_plan_document(flag_net="GND", wire_net="VIN"))
    message = str(excinfo.value)
    assert "GND" in message and "VIN" in message


def test_a_flag_on_its_own_nets_wire_is_accepted():
    from boardwise.core.changeplan import ChangePlan

    plan = ChangePlan.from_jsonable(_plan_document(flag_net="GND", wire_net="GND"))
    assert [flag.net for flag in plan.change.draw_flags] == ["GND"]


def test_a_flag_away_from_the_wire_is_accepted():
    """Only a flag *standing on* the wire claims the same conductor."""
    from boardwise.core.changeplan import ChangePlan

    plan = ChangePlan.from_jsonable(
        _plan_document(flag_net="GND", wire_net="VIN", flag_at=(50.0, 50.0))
    )
    assert [flag.net for flag in plan.change.draw_flags] == ["GND"]


# ------------------------------------------------------- F6: flag symbols


def test_a_name_the_host_does_not_know_takes_its_kind_from_its_own_symbol():
    """The measured fact this stays compatible with: `power_flag_kind('VIN')` is `''`."""
    assert drawapply.flag_kind("VIN", "PWR-VIN") == DRAW_FLAG_POWER
    assert drawapply.flag_kind("VIN5", "PWR-VIN5") == DRAW_FLAG_POWER


def test_a_ground_symbol_on_a_supply_name_is_refused():
    """The witness: it used to answer `Ground`, and apply put a ground flag on a rail."""
    with pytest.raises(drawapply.DrawPlanError) as excinfo:
        drawapply.flag_kind("VIN5", "PWR-GND")
    message = str(excinfo.value)
    assert "VIN5" in message and "PWR-GND" in message
    assert "ground" in message


def test_a_ground_symbol_on_a_signal_name_is_refused_too():
    """The same conflict one net over: a net that is not a rail at all."""
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.flag_kind("TAP", "PWR-GND")


def test_a_power_prefixed_ground_symbol_reads_as_a_ground_flag():
    """`PWR-PGND` is the power prefix carrying a ground name; the name decides."""
    assert drawapply.flag_kind("PGND", "PWR-PGND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("PGND", "PWR-GND") == DRAW_FLAG_GROUND
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.flag_kind("VIN5", "PWR-PGND")


def test_the_kind_the_name_gives_is_still_the_kind_returned():
    assert drawapply.flag_kind("GND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("GND", "PWR-GND") == DRAW_FLAG_GROUND
    assert drawapply.flag_kind("SIG", "PWR-SIG") == DRAW_FLAG_POWER
    assert drawapply.flag_kind("SIG", "") == ""
    with pytest.raises(drawapply.DrawPlanError):
        drawapply.flag_kind("GND", "PWR-5V")
