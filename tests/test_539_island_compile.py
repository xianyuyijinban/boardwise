"""539 — adversarial closure for island input, gate and recompile edges."""

from __future__ import annotations

import copy

import pytest

from boardwise.core.presentationspec import UserLock
from boardwise.engines import islandcompile, islandlayout, readability
from boardwise.engines.islandcompile import compile_island, compile_islands, recompile_island
from boardwise.engines.islandlayout import IslandBudget

from test_536_archipelago_schema import LDO_TWO_ISLANDS, _ldo_real_spec

CORE = "rail_core"
DECOUPLING = "rail_decoupling"
LDO_SINGLE = {
    "rail_all": (["U1", "C1", "C2"], "control", "core", ""),
}


@pytest.fixture(scope="module")
def ldo():
    return _ldo_real_spec(LDO_TWO_ISLANDS)


@pytest.fixture(scope="module")
def single_ldo():
    return _ldo_real_spec(LDO_SINGLE)


@pytest.mark.parametrize("bad_value", [{}, None])
def test_invalid_profile_values_are_structured_facts_failures(ldo, bad_value):
    circuit, spec, profiles = ldo
    bad = dict(profiles)
    bad[circuit.part("C1").symbol_ref] = bad_value

    single = compile_island(circuit, spec, DECOUPLING, bad)
    batch = compile_islands(circuit, spec, bad)

    assert single.ok is False
    assert single.refusal.category == "facts-missing"
    assert type(bad_value).__name__ in single.refusal.detail
    assert single.block is None and single.plan is None
    by_id = {result.island_id: result for result in batch}
    # A malformed profile mapping is a global input error: layout and the checker
    # both read the whole book.  Unlike a missing C1 profile, it must not be
    # silently ignored just because one island does not place C1.
    assert set(by_id) == {CORE, DECOUPLING}
    for result in batch:
        assert result.ok is False
        assert result.refusal.category == "facts-missing"
        assert type(bad_value).__name__ in result.refusal.detail
        assert result.block is None and result.plan is None


def test_hard_refusal_category_precedes_a_simultaneous_soft_floor(
    single_ldo, monkeypatch
):
    circuit, spec, profiles = single_ldo
    island_id = next(iter(LDO_SINGLE))
    baseline = compile_island(circuit, spec, island_id, profiles)
    assert baseline.ok is True, baseline.refusal
    u1 = baseline.plan.part("U1")
    locked = copy.deepcopy(spec)
    locked.user_locks = [UserLock("U1", u1.x + 10.0, u1.y, u1.rotation)]
    monkeypatch.setattr(
        readability,
        "soft_floor_violations",
        lambda *args, **kwargs: ["synthetic soft-floor breach"],
    )

    result = compile_island(circuit, locked, island_id, profiles)

    assert result.ok is False
    assert result.refusal.category == "presentation-poor"
    assert "user-lock-violated" in result.refusal.detail
    assert "soft floor" not in result.refusal.detail


def test_the_checker_receives_the_layout_budget_grid(ldo, monkeypatch):
    circuit, spec, profiles = ldo
    seen = []
    original = readability.check

    def spy(*args, **kwargs):
        seen.append(kwargs.get("grid"))
        return original(*args, **kwargs)

    monkeypatch.setattr(readability, "check", spy)
    result = compile_island(circuit, spec, CORE, profiles, budget=IslandBudget())

    assert result.ok is True, result.refusal
    assert seen == [IslandBudget().grid]


def test_recompile_discloses_mutation_of_the_original_input_objects(ldo):
    circuit, spec, profiles = ldo
    original = compile_island(circuit, spec, CORE, profiles)
    assert original.ok is True, original.refusal
    old_presentation_hash = original.plan.source.presentation_sha256
    # PresentationSpec is mutable by design.  A page lock changes its hash while
    # remaining outside the independent block's own gate.
    spec.user_locks.append(UserLock("U1", 600.0, 500.0, scope="page"))

    again = recompile_island(original)

    assert again.ok is True, again.refusal
    assert again.plan.source.presentation_sha256 == spec.sha256()
    assert again.plan.source.presentation_sha256 != old_presentation_hash
    assert original.plan.source.presentation_sha256 == old_presentation_hash
    notes = "\n".join(again.notes)
    assert "content changed" in notes
    assert "with unchanged input" not in notes


@pytest.mark.parametrize("original_budget", [None, IslandBudget()])
def test_recompile_with_an_equal_budget_is_not_a_changed_input(ldo, original_budget):
    circuit, spec, profiles = ldo
    original = compile_island(
        circuit, spec, CORE, profiles, budget=original_budget
    )

    again = recompile_island(original, budget=IslandBudget())

    assert again.ok is True, again.refusal
    assert again.plan.geometry_sha256() == original.plan.geometry_sha256()
    assert again.request.budget is original.request.budget
    notes = "\n".join(again.notes)
    assert "unchanged input" in notes
    assert "request with a changed budget" not in notes


@pytest.mark.parametrize(
    "name, value",
    [
        ("grid", 0),
        ("grid", float("nan")),
        ("channel", -1),
        ("row_gap", -0.1),
        ("slot_rungs", 1.5),
        ("text_rungs", True),
        ("gnd_flag", None),
    ],
)
def test_island_budget_rejects_values_the_placer_cannot_use(name, value):
    with pytest.raises(ValueError, match=f"IslandBudget.{name}"):
        IslandBudget(**{name: value})


def test_island_budget_keeps_valid_zero_and_empty_flag_choices():
    budget = IslandBudget(
        pin_gap=0,
        row_gap=0,
        stub=0,
        text_gap=0,
        slot_rungs=0,
        text_rungs=0,
        gnd_flag="",
    )
    assert budget.pin_gap == 0
    assert budget.gnd_flag == ""
