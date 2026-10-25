"""538A — 显式 readability scope 与 scoped 岛身份回验（生产聚焦）。

本文件固定 538A 这一棒的两条契约：

1. `readability.check` 的**显式**部件 scope：默认 `None` 是整页语义，行为与
   `CheckResult` 形状都不变；给了 scope 时只跳过「岛外**且**未放置」的两类项
   （`required-pin-not-connected` 的 `placed_part is None`、`user-lock-violated`
   的 `part is None`）。岛内缺件、岛外件被错误画入、锁坐标不符都仍按原规则检查。
2. `core.archipelago.validate_archipelago_island_plan`：对**同一** presentation
   先跑同一结构检查，expected 只取该岛的 parts；缺本岛件、画入岛外件、重复、
   空/错 group/island 与未知 island 都拒绝，且岛外件的文案说的是「该岛之外」，
   不谎称 presentation 未声明。原 `validate_archipelago_plan` 的全量语义不变。

真实输入：`tests/test_536_archipelago_schema.py` 的 `_ldo_real_spec` 与
`LDO_TWO_ISLANDS`（rail_core = U1 / rail_decoupling = C1, C2），库与电路都来自既
有 LDO helper，不手写第三套 profile。局部 plan 由 `island_subgraph` +
`layout_island` 产出，与本棒之后要用的投影是同一条路径。

契约：`tasks/538_island_compile.md` §2/§3-538A；`docs/drawing-archipelago-route.md`
§2.2/§2.3。仍然只到块级离线：不含编译 API、不含页级 pack、不碰 bridge/画布。
"""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, fields

import pytest

from boardwise.core.archipelago import (
    ArchipelagoError,
    validate_archipelago_island_plan,
    validate_archipelago_plan,
)
from boardwise.core.layoutplan import LayoutPart, LayoutPlan
from boardwise.core.presentationspec import PresentationSpec, UserLock
from boardwise.engines import readability
from boardwise.engines.islandlayout import island_subgraph, layout_island

from test_536_archipelago_schema import LDO_TWO_ISLANDS, _ldo_real_spec

CORE = "rail_core"
DECOUPLING = "rail_decoupling"
CORE_PARTS = frozenset({"U1"})
DECOUPLING_PARTS = frozenset({"C1", "C2"})


# --------------------------------------------------------------------- inputs


@pytest.fixture(scope="module")
def ldo():
    """The measured LDO circuit, its two-island archipelago spec, its profiles."""
    return _ldo_real_spec(LDO_TWO_ISLANDS)


@pytest.fixture(scope="module")
def local_plans(ldo):
    """Each island's own picture, through the same subgraph/layout projection."""
    circuit, spec, profiles = ldo
    islands = {island.id: island for island in spec.islands or ()}
    return {
        island_id: layout_island(
            circuit, island_subgraph(circuit, islands[island_id]), profiles
        ).plan()
        for island_id in (CORE, DECOUPLING)
    }


def _scope(*parts: str) -> readability.ReadabilityScope:
    return readability.ReadabilityScope(parts=frozenset(parts))


def _required_pins(result: readability.CheckResult) -> list[str]:
    """The pins a `required-pin-not-connected` finding names, sorted."""
    out: list[str] = []
    for violation in result.hard_violations:
        if violation.kind != readability.KIND_REQUIRED_PIN_NOT_CONNECTED:
            continue
        for name in violation.objects:
            if name.startswith("pins[") and name.endswith("]"):
                out.append(name[len("pins["):-1])
    return sorted(out)


def _kinds(result: readability.CheckResult) -> list[str]:
    return [violation.kind for violation in result.hard_violations]


def _locked(ldo, locks) -> PresentationSpec:
    """A copy of the LDO spec carrying exactly `locks` (a fresh spec per call)."""
    _, spec, _ = ldo
    locked = copy.deepcopy(spec)
    locked.user_locks = list(locks)
    return locked


# ------------------------------------------------- 1. the unscoped baseline


@pytest.mark.parametrize("island_id, expected_pins", [
    (CORE, ["C1.1", "C1.2", "C2.1", "C2.2"]),
    (DECOUPLING, ["U1.1", "U1.2", "U1.3"]),
])
def test_a_local_plan_unscoped_reports_the_other_islands_pins(
    ldo, local_plans, island_id, expected_pins
):
    """The measured 4 / 3 false positives, pinned as strings, not as a count.

    This is the pre-state the scope exists for: one island's plan graded against
    the whole specification reports every declared member whose part this island
    does not place.  `rail_core` (U1) owes C1/C2's four members, `rail_decoupling`
    (C1, C2) owes U1's three — 4 and 3, exactly as the read-only probe measured.
    """
    circuit, spec, profiles = ldo
    result = readability.check(local_plans[island_id], circuit, spec, profiles)
    assert _required_pins(result) == expected_pins
    assert len(expected_pins) in (3, 4) and len(result.hard_violations) == len(expected_pins)
    assert set(_kinds(result)) == {readability.KIND_REQUIRED_PIN_NOT_CONNECTED}


def test_no_scope_is_the_whole_page_and_the_result_shape_is_unchanged(
    ldo, local_plans
):
    """`scope=None` is byte-for-byte the old call — and `CheckResult` gains nothing."""
    circuit, spec, profiles = ldo
    plan = local_plans[CORE]
    default = readability.check(plan, circuit, spec, profiles)
    explicit = readability.check(plan, circuit, spec, profiles, scope=None)
    assert default.hard_violations == explicit.hard_violations
    assert len(default.hard_violations) == 4
    assert [field.name for field in fields(readability.CheckResult)] == [
        "hard_violations", "grammar_findings", "soft_metrics", "soft_reasons",
    ]
    # The scope is keyword-only: a fifth positional argument is not a scope.
    with pytest.raises(TypeError):
        readability.check(plan, circuit, spec, profiles, _scope("U1"))


# ----------------------------------------------------- 2. the scoped reading


@pytest.mark.parametrize("island_id, parts", [
    (CORE, CORE_PARTS),
    (DECOUPLING, DECOUPLING_PARTS),
])
def test_the_scope_drops_the_outside_unplaced_pins_and_creates_no_finding(
    ldo, local_plans, island_id, parts
):
    """In island, nothing is wrong: the outside omissions are the scope's own, and
    the partition is *not* reported — the drawing does state its own nodes."""
    circuit, spec, profiles = ldo
    result = readability.check(
        local_plans[island_id], circuit, spec, profiles,
        scope=readability.ReadabilityScope(parts=parts),
    )
    assert result.hard_violations == []
    assert readability.KIND_NETLIST_PARTITION not in _kinds(result)


def test_the_scope_still_reports_a_missing_part_inside_it(ldo, local_plans):
    """A part the scope names but the plan does not place is a finding, as before."""
    circuit, spec, profiles = ldo
    result = readability.check(
        local_plans[CORE], circuit, spec, profiles, scope=_scope("U1", "C1"),
    )
    assert _required_pins(result) == ["C1.1", "C1.2"]
    assert set(_kinds(result)) == {readability.KIND_REQUIRED_PIN_NOT_CONNECTED}


def test_a_part_outside_the_scope_that_was_drawn_in_is_still_checked(
    ldo, local_plans
):
    """The scope is not "ignore this part": an outside part drawn in owes its pins."""
    circuit, spec, profiles = ldo
    plan = copy.deepcopy(local_plans[DECOUPLING])
    plan.parts.append(LayoutPart(
        part_id="U1", symbol_ref=circuit.part("U1").symbol_ref,
        x=1000.0, y=1000.0,
    ))
    result = readability.check(
        plan, circuit, spec, profiles,
        scope=readability.ReadabilityScope(parts=DECOUPLING_PARTS),
    )
    assert _required_pins(result) == ["U1.1", "U1.2", "U1.3"]


# ------------------------------------------------------- 3. user locks, scoped


def test_an_outside_unplaced_lock_is_skipped_but_an_inside_one_is_not(
    ldo, local_plans
):
    """Exactly the two branches: `part is None` outside the scope; the rest stays."""
    circuit, _, profiles = ldo
    plan = local_plans[CORE]
    u1 = plan.part("U1")
    spec = _locked(ldo, [
        UserLock("C1", 0.0, 0.0, 0.0),          # outside, never placed here
        UserLock("U1", u1.x + 10.0, u1.y, u1.rotation),  # inside, moved
    ])

    whole = readability.check(plan, circuit, spec, profiles)
    assert {v.objects[0] for v in whole.hard_violations
            if v.kind == readability.KIND_USER_LOCK_VIOLATED} == {
        "presentationSpec.userLocks[C1]", "presentationSpec.userLocks[U1]",
    }

    scoped = readability.check(
        plan, circuit, spec, profiles, scope=readability.ReadabilityScope(parts=CORE_PARTS),
    )
    assert _kinds(scoped) == [readability.KIND_USER_LOCK_VIOLATED]
    assert scoped.hard_violations[0].objects[0] == "presentationSpec.userLocks[U1]"


def test_a_lock_inside_the_scope_is_still_compared_to_the_coordinate(
    ldo, local_plans
):
    """Exact is honoured; one unit off is reported — the scope changes neither."""
    circuit, _, profiles = ldo
    plan = local_plans[CORE]
    u1 = plan.part("U1")
    scope = readability.ReadabilityScope(parts=CORE_PARTS)

    exact = _locked(ldo, [UserLock("U1", u1.x, u1.y, u1.rotation)])
    assert readability.check(plan, circuit, exact, profiles, scope=scope).hard_violations == []

    off = _locked(ldo, [UserLock("U1", u1.x + 1.0, u1.y, u1.rotation)])
    result = readability.check(plan, circuit, off, profiles, scope=scope)
    assert _kinds(result) == [readability.KIND_USER_LOCK_VIOLATED]


# ------------------------------------------------------- 4. scope, as a value


def test_the_scope_is_frozen_and_names_something(ldo, local_plans):
    """A scope is a value; an empty one would be the whole page with omissions allowed."""
    circuit, spec, profiles = ldo
    plan = local_plans[CORE]
    scope = readability.ReadabilityScope(parts=CORE_PARTS)
    with pytest.raises(FrozenInstanceError):
        scope.parts = frozenset()
    with pytest.raises(readability.ReadabilityError):
        readability.check(plan, circuit, spec, profiles,
                          scope=readability.ReadabilityScope(parts=frozenset()))
    with pytest.raises(readability.ReadabilityError):
        readability.check(plan, circuit, spec, profiles, scope=CORE_PARTS)


# ------------------------------------- 5. scoped identity: the shared comparator


@pytest.mark.parametrize("island_id", [CORE, DECOUPLING])
def test_the_scoped_identity_accepts_the_islands_own_plan(
    ldo, local_plans, island_id
):
    """The local picture each island draws is exactly that island's partition."""
    _, spec, _ = ldo
    validate_archipelago_island_plan(local_plans[island_id], spec, island_id)


def test_the_scoped_identity_refuses_a_missing_island_part(ldo, local_plans):
    _, spec, _ = ldo
    plan = copy.deepcopy(local_plans[DECOUPLING])
    plan.parts = [part for part in plan.parts if part.part_id != "C2"]
    with pytest.raises(ArchipelagoError, match="places no part C2"):
        validate_archipelago_island_plan(plan, spec, DECOUPLING)


def test_the_scoped_identity_refuses_a_part_from_another_island(ldo, local_plans):
    """The wording says "outside this island", and does not deny the declaration."""
    _, spec, _ = ldo
    plan = copy.deepcopy(local_plans[DECOUPLING])
    plan.parts.append(LayoutPart(
        part_id="U1", symbol_ref="AMS1117-3.3", group="rail", island=CORE,
    ))
    with pytest.raises(ArchipelagoError) as refusal:
        validate_archipelago_island_plan(plan, spec, DECOUPLING)
    message = str(refusal.value)
    assert "outside island" in message and DECOUPLING in message
    assert "presentation does not declare" not in message


def test_the_scoped_identity_refuses_a_duplicate_part(ldo, local_plans):
    _, spec, _ = ldo
    plan = copy.deepcopy(local_plans[DECOUPLING])
    plan.parts.append(copy.deepcopy(plan.parts[0]))
    with pytest.raises(ArchipelagoError, match="twice"):
        validate_archipelago_island_plan(plan, spec, DECOUPLING)


@pytest.mark.parametrize("stated", [
    ("rail", ""),              # empty island: "not stated" is not "anywhere"
    ("", DECOUPLING),          # empty group
    ("rail", CORE),            # the other island's id
    ("another_group", DECOUPLING),
])
def test_the_scoped_identity_refuses_a_wrong_group_or_island(
    ldo, local_plans, stated
):
    _, spec, _ = ldo
    plan = copy.deepcopy(local_plans[DECOUPLING])
    for part in plan.parts:
        if part.part_id == "C1":
            part.group, part.island = stated
    with pytest.raises(ArchipelagoError):
        validate_archipelago_island_plan(plan, spec, DECOUPLING)


@pytest.mark.parametrize("island_id", ["no_such_island", "", "all"])
def test_the_scoped_identity_refuses_an_unknown_island(ldo, local_plans, island_id):
    """An id nobody declared is refused by name, never checked against a guess."""
    _, spec, _ = ldo
    with pytest.raises(ArchipelagoError, match="declares no island"):
        validate_archipelago_island_plan(local_plans[CORE], spec, island_id)


def test_the_scoped_identity_refuses_a_legacy_presentation(ldo, local_plans):
    """A legacy spec states no island identity, so it has no island plan to check."""
    _, spec, _ = ldo
    legacy = PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec", "specVersion": 1,
        "grammarRef": "ldo",
        "modules": [{"id": "rail", "role": "regulator", "parts": ["U1", "C1", "C2"]}],
    })
    with pytest.raises(ArchipelagoError, match="no archipelago island"):
        validate_archipelago_island_plan(local_plans[CORE], legacy, CORE)


# ------------------------------- 6. the whole-page validator, still whole-page


@pytest.mark.parametrize("island_id", [CORE, DECOUPLING])
def test_the_whole_page_validator_still_refuses_a_local_plan(
    ldo, local_plans, island_id
):
    """538A adds a scoped reading; it does not make the full one accept one island."""
    _, spec, _ = ldo
    with pytest.raises(ArchipelagoError, match="places no part"):
        validate_archipelago_plan(local_plans[island_id], spec)


def test_the_whole_page_validator_accepts_the_declared_partition(ldo, local_plans):
    """The two local plans together are the full partition, and that still passes."""
    _, spec, _ = ldo
    plan = LayoutPlan(parts=[
        copy.deepcopy(part)
        for island_id in (CORE, DECOUPLING)
        for part in local_plans[island_id].parts
    ])
    validate_archipelago_plan(plan, spec)
