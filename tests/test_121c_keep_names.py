"""121c: `keep_names` — a compiled drawing lands under its spec ids.

岳 2026-10-06 (relayed through the 121c task book): a landed flyback page must
read like the plan the engineer signed.  The compiler's own allocation renumbers
every part from the pool (``C10`` came out as ``C3``), which makes the page and
the approved plan two different documents.  The ruling is a small switch —
``--keep-names`` — that lands each part under its **spec id**, refused by name
when that name is not free.

Four claims are pinned, one test class each:

1. the switch is what changes the numbers — identical parts, spec ids off vs on;
2. a kept name that the pool already owns refuses the plan **by name** (the host
   would rename it mid-run, 036b) instead of silently overwriting;
3. `module_plan` records the choice in the plan and the document round-trips it,
   so apply can ask the right designator question;
4. apply's `designator_problems` skips the *allocation* leg for a kept-name plan
   (the pool would never allocate ``C10``) but still refuses a taken name.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.changeplan import (
    DRAW_MODULE_KIND,
    ChangePlan,
    PlanChange,
    PlanDrawPart,
)
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.layoutplan import LayoutPart
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply, drawcompiler

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "drawapply"
CIRCUIT = FIXTURES / "divider.circuit.json"
PRESENTATION = FIXTURES / "divider.presentation.json"
LIBRARY = FIXTURES / "library.json"
PAGE_BOX = (0.0, -1000.0, 1200.0, 0.0)
LCSC = {"R1": "C25744", "R2": "C25744"}


@pytest.fixture(scope="module")
def profiles():
    return drawapply.load_library(LIBRARY)


def _parts(*ids: str) -> list[LayoutPart]:
    """Layout parts under the ids a spec would carry (``R7``, ``R9`` …)."""
    return [LayoutPart(part_id=part_id, symbol_ref="R0402") for part_id in ids]


# ------------------------------------------------------- 1. the switch itself


def test_keep_names_lands_every_part_under_its_spec_id(profiles):
    got = drawapply.assign_designators(
        _parts("R7", "R9"), profiles, [], keep_names=True
    )
    assert got == [("R7", "R", "R7"), ("R9", "R", "R9")]


def test_without_the_switch_the_pool_numbers_the_parts(profiles):
    # The contrast that makes the switch meaningful: the same two parts come out
    # as R1/R2 (the pool's lowest free numbers), which is exactly the renumbering
    # 岳 objected to.
    got = drawapply.assign_designators(
        _parts("R7", "R9"), profiles, [], keep_names=False
    )
    assert got == [("R7", "R", "R1"), ("R9", "R", "R2")]


def test_keep_names_still_derives_the_prefix_from_the_spec_id(profiles):
    got = drawapply.assign_designators(
        _parts("C10"), profiles, [], keep_names=True
    )
    assert got == [("C10", "C", "C10")]


# ------------------------------------------------ 2. a taken name is refused


def test_keep_names_refuses_a_name_the_pool_already_owns(profiles):
    with pytest.raises(drawapply.DrawPlanError) as excinfo:
        drawapply.assign_designators(
            _parts("R7", "R9"), profiles, ["R7"], keep_names=True
        )
    message = str(excinfo.value)
    assert "R7" in message
    assert "keep" in message.lower()


def test_keep_names_is_indifferent_to_names_the_drawing_does_not_use(profiles):
    # A pool that owns R1 (which no spec id claims) does not stop R7/R9.
    got = drawapply.assign_designators(
        _parts("R7", "R9"), profiles, ["R1"], keep_names=True
    )
    assert [item[2] for item in got] == ["R7", "R9"]


# ---------------------------------------- 3. the plan records and round-trips


def _divider_plan(profiles, *, keep_names: bool) -> ChangePlan:
    circuit = CircuitSpec.load(CIRCUIT)
    presentation = PresentationSpec.load(PRESENTATION)
    compiled = drawcompiler.compile(
        circuit, presentation, profiles, drawcompiler.CompileBudget(page_box=PAGE_BOX)
    )
    return drawapply.module_plan(
        compiled.candidates[0], circuit, presentation, profiles,
        lcsc_by_part=LCSC, notes=["121c test"], keep_names=keep_names,
    )


def test_module_plan_keeps_names_and_records_the_flag(profiles):
    plan = _divider_plan(profiles, keep_names=True)
    assert [part.designator for part in plan.change.draw_parts] == ["R1", "R2"]
    assert plan.change.draw_keep_names is True
    assert plan.to_jsonable()["change"].get("keepNames") is True


def test_a_plan_that_kept_no_names_carries_no_key(profiles):
    # The kind-aware rule: a plan that did not use the switch is byte-for-byte
    # the document it always was.
    plan = _divider_plan(profiles, keep_names=False)
    assert plan.change.draw_keep_names is False
    assert "keepNames" not in plan.to_jsonable()["change"]


def test_the_keep_names_choice_round_trips_through_the_document(profiles):
    plan = _divider_plan(profiles, keep_names=True)
    again = ChangePlan.from_jsonable(plan.to_jsonable())
    assert again.change.draw_keep_names is True
    assert again.to_jsonable()["change"].get("keepNames") is True


# -------------------------------- 4. apply's designator guard asks the right thing


def _kept_change(*, keep_names: bool) -> ChangePlan:
    """A one-part plan whose designator is a spec id, not the pool's allocation."""
    return ChangePlan(change=PlanChange(
        kind=DRAW_MODULE_KIND,
        layout_sha256="0" * 64,
        circuit_sha256="1" * 64,
        presentation_sha256="2" * 64,
        draw_keep_names=keep_names,
        draw_parts=[PlanDrawPart(
            spec_id="R7", designator="R7", prefix="R", lcsc="C25744", value="10k",
        )],
    ))


def test_a_kept_plan_is_not_checked_against_the_pools_allocation():
    # pool is empty, so the allocation leg would allocate "R1" and reject "R7"
    # for the wrong reason; a kept-name plan is asked only "is the name free?".
    assert drawapply.designator_problems(_kept_change(keep_names=True), []) == []


def test_an_allocated_plan_still_disagrees_with_the_pool():
    problems = drawapply.designator_problems(_kept_change(keep_names=False), [])
    assert problems and "R1" in problems[0]


def test_a_kept_name_that_is_taken_is_still_refused():
    problems = drawapply.designator_problems(_kept_change(keep_names=True), ["R7"])
    assert problems and "R7" in problems[0]
