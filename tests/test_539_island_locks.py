"""539 — independent-island locks keep their coordinate-frame contract.

A block is not a page, and one block of a multi-island module is not necessarily
that module's drawing.  These tests pin the fail-closed behaviour for those two
cases without changing the ordinary whole-page or single-island lock checks.
"""

from __future__ import annotations

import copy

import pytest

from boardwise.core.presentationspec import UserLock
from boardwise.engines import readability
from boardwise.engines.islandcompile import compile_island, compile_islands

from test_536_archipelago_schema import LDO_TWO_ISLANDS, _ldo_real_spec

CORE = "rail_core"
DECOUPLING = "rail_decoupling"
CORE_PARTS = frozenset({"U1"})
LDO_SINGLE = {
    "rail_all": (["U1", "C1", "C2"], "control", "core", ""),
}


@pytest.fixture(scope="module")
def ldo():
    return _ldo_real_spec(LDO_TWO_ISLANDS)


@pytest.fixture(scope="module")
def single_ldo():
    return _ldo_real_spec(LDO_SINGLE)


def _locked(spec, *locks):
    out = copy.deepcopy(spec)
    out.user_locks = list(locks)
    return out


def _lock_violations(result):
    return [
        violation
        for violation in result.hard_violations
        if violation.kind == readability.KIND_USER_LOCK_VIOLATED
    ]


def test_page_lock_at_page_coordinates_is_not_a_block_local_violation(ldo):
    circuit, spec, profiles = ldo
    locked = _locked(spec, UserLock("U1", 600.0, 500.0, scope="page"))

    result = compile_island(circuit, locked, CORE, profiles)

    assert result.ok is True, result.refusal
    assert _lock_violations(result.gate) == []
    assert "page-scoped user locks were not evaluated" in "\n".join(
        result.plan.evidence.notes
    )


def test_page_lock_matching_block_coordinates_still_is_not_a_page_check(ldo):
    """Coincidence with local (0, 0) must not masquerade as page verification."""
    circuit, spec, profiles = ldo
    baseline = compile_island(circuit, spec, CORE, profiles)
    u1 = baseline.plan.part("U1")
    locked = _locked(
        spec, UserLock("U1", u1.x, u1.y, u1.rotation, scope="page")
    )

    result = compile_island(circuit, locked, CORE, profiles)

    assert result.ok is True, result.refusal
    assert _lock_violations(result.gate) == []
    assert "page-scoped user locks were not evaluated" in "\n".join(
        result.plan.evidence.notes
    )


def test_single_island_module_lock_keeps_exact_and_mismatch_semantics(single_ldo):
    circuit, spec, profiles = single_ldo
    island_id = next(iter(LDO_SINGLE))
    baseline = compile_island(circuit, spec, island_id, profiles)
    assert baseline.ok is True, baseline.refusal
    u1 = baseline.plan.part("U1")

    exact = _locked(spec, UserLock("U1", u1.x, u1.y, u1.rotation))
    accepted = compile_island(circuit, exact, island_id, profiles)
    assert accepted.ok is True, accepted.refusal

    moved = _locked(spec, UserLock("U1", u1.x + 10.0, u1.y, u1.rotation))
    refused = compile_island(circuit, moved, island_id, profiles)
    assert refused.ok is False
    assert refused.refusal.category == "presentation-poor"
    assert "user-lock-violated" in refused.refusal.detail
    assert refused.block is None and refused.plan is None


@pytest.mark.parametrize(
    "locked_part, refused_island",
    [("U1", CORE), ("C1", DECOUPLING)],
)
def test_multi_island_module_lock_requires_the_module_frame(
    ldo, locked_part, refused_island
):
    circuit, spec, profiles = ldo
    baseline = {
        result.island_id: result
        for result in compile_islands(circuit, spec, profiles)
    }
    part = baseline[refused_island].plan.part(locked_part)
    locked = _locked(
        spec, UserLock(locked_part, part.x, part.y, part.rotation)
    )

    results = {
        result.island_id: result
        for result in compile_islands(circuit, locked, profiles)
    }

    refused = results[refused_island]
    assert refused.ok is False
    assert refused.refusal.category == "presentation-poor"
    assert "module drawing's coordinate frame" in refused.refusal.detail
    assert refused.block is None and refused.plan is None
    other_island = DECOUPLING if refused_island == CORE else CORE
    assert results[other_island].ok is True, results[other_island].refusal
    assert not all(result.ok for result in results.values())


def test_undeclared_lock_part_is_facts_missing_for_single_and_batch(ldo):
    circuit, spec, profiles = ldo
    locked = _locked(spec, UserLock("U9", 10.0, 10.0))

    single = compile_island(circuit, locked, CORE, profiles)
    batch = compile_islands(circuit, locked, profiles)

    for result in [single, *batch]:
        assert result.ok is False
        assert result.refusal.category == "facts-missing"
        assert "U9" in result.refusal.detail
        assert result.block is None and result.plan is None


def test_scope_and_frame_switches_cannot_hide_an_undeclared_lock_part(ldo):
    circuit, spec, profiles = ldo
    plan = compile_island(circuit, spec, CORE, profiles).plan
    locked = _locked(spec, UserLock("U9", 10.0, 10.0, scope="page"))

    checked = readability.check(
        plan,
        circuit,
        locked,
        profiles,
        scope=readability.ReadabilityScope(
            parts=CORE_PARTS,
            check_page_locks=False,
            check_module_locks=False,
        ),
    )

    violations = _lock_violations(checked)
    assert len(violations) == 1
    assert "circuit declares no such part" in violations[0].evidence


def test_default_scoped_and_unscoped_checks_still_check_both_lock_frames(ldo):
    circuit, spec, profiles = ldo
    plan = compile_island(circuit, spec, CORE, profiles).plan
    u1 = plan.part("U1")
    locked = _locked(
        spec,
        UserLock("U1", u1.x + 1.0, u1.y, u1.rotation),
        UserLock("U1", u1.x + 2.0, u1.y, scope="page"),
    )

    for scope in (None, readability.ReadabilityScope(parts=CORE_PARTS)):
        checked = readability.check(
            plan, circuit, locked, profiles, scope=scope
        )
        assert len(_lock_violations(checked)) == 2
