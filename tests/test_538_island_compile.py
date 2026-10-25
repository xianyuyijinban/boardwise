"""538B1/B2 — 独立子岛编译：成功路径 + 失败路径与批次内隔离。

本文件固定 538B 两棒的契约。§1–§5 是 538B1 的成功面与缺 profile 结构化失败；
§6 是 538B2 的失败路径：布局 / plan+identity / readability 三阶段抛错都要转成
**该岛**的结构化 refusal（无候选），批内其它岛照常编译，且程序错误不被吞掉：

1. `compile_island(circuit, presentation, island_id, profiles, *, budget=None)`
   与 `compile_islands(...)` 共享同一内部实现；batch 按
   `presentation.effective_islands()` 的顺序返回结果。
2. 局部流程 = `layout_island` → `IslandBlock.plan(source=原始整份哈希)` →
   `validate_archipelago_island_plan` → `readability.check(scope=本岛 parts)` →
   `island_gate_violations` + `soft_floor_violations`。不调用 `island_page` /
   `pack_islands` / 整页 compile，不传 `page_box` / `keepouts`，不跑 grammar。
3. 成功 plan 带 `LayoutEvidence`（checker 用 `drawcompiler.CHECKER_NAME`，hard 与
   grammar 均为空，soft metrics/reasons 全保留，notes 明说“独立岛、不是拼好的页、
   grammar/page 层未运行”）。
4. `IslandCompileResult` 冻结且校验不变量：成功必须有 block/plan/gate 且
   refusal=None；失败必须 block=plan=None 且 refusal 非空。`ok` 由完整结果推导，
   不看 `gate.ok`（host 打印行的 tolerated 是允许的）。
5. 缺 profile 是**结构化** `facts-missing` 失败（不是 KeyError），且没有候选
   block/plan；批内其它岛照常成功。
6. 538B2：布局 / plan+identity / readability 阶段抛出的明确 `ValueError`
   （含 `ArchipelagoError` / `ReadabilityError`）与必要 `KeyError` 都变成**该岛**
   的 `GrammarFailure`（detail 带 island/stage/原始异常），block/plan=None；
   批次不中断、顺序不变。`TypeError` 这类程序错误照旧外抛，不冒充 refusal。

§7 是 538C：`recompile_island(result, *, budget=None)` 只重算该结果自己的岛，
沿用其冻结 request；`budget=None` 是**未变输入**（不是新 variant），传入新
`IslandBudget` 才替换这一项。旧结果与批次里其它成功结果逐字不动，没有自动重试；
失败结果重编译仍是同一失败，不产生候选。

真实输入全部复用 `tests/test_536_archipelago_schema.py` 的 `_ldo_real_spec` 与
`LDO_TWO_ISLANDS`（rail_core = U1、rail_decoupling = C1/C2），不手写第三套
profile，也不放宽 536/538A 的任何门槛。

契约：`tasks/538_island_compile.md` §2/§3-538B；`docs/drawing-archipelago-route.md`
§5/§6。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from boardwise.core.archipelago import (
    ArchipelagoError,
    validate_archipelago_island_plan,
)
from boardwise.core.islands import cross_island_nets
from boardwise.core.layoutplan import LayoutSource
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawcompiler, islandcompile, islandlayout, readability
from boardwise.engines.grammar.base import (
    FAILURE_CATEGORIES,
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
)
from boardwise.engines.islandcompile import (
    IslandCompileRequest,
    IslandCompileResult,
    compile_island,
    compile_islands,
    recompile_island,
)

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


@pytest.fixture
def scope_spy(monkeypatch):
    """Every `readability.check` call's kwargs, for the scope/absence checks."""
    seen: list[dict] = []
    original = readability.check

    def spy(*args, **kwargs):
        seen.append(dict(kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(readability, "check", spy)
    return seen


def _missing_c1_profiles(circuit, profiles):
    """The same profile set with C1's symbol removed — a facts hole, not a layout one."""
    symbol = circuit.part("C1").symbol_ref
    return {ref: profile for ref, profile in profiles.items() if ref != symbol}


# ------------------------------------------- 1. one island, its own picture


def test_core_island_compiles_as_its_own_picture(ldo):
    """U1 alone: local ok, its own identity, the original specs' hashes."""
    circuit, spec, profiles = ldo
    result = compile_island(circuit, spec, CORE, profiles)

    assert isinstance(result, IslandCompileResult)
    assert result.island_id == CORE
    assert result.ok is True
    assert result.refusal is None
    assert result.tolerated == ()
    assert result.block is not None and result.plan is not None
    assert result.gate is not None

    # The block is this island's own, not a page.
    assert result.block.island_id == CORE
    assert isinstance(result.block, islandlayout.IslandBlock)
    assert not isinstance(result.block, islandlayout.PackedPage)

    # The plan places exactly this island's parts, stamped with the declared
    # group/island — and it passes 538A's scoped identity check.
    assert {part.part_id for part in result.plan.parts} == set(CORE_PARTS)
    for part in result.plan.parts:
        assert (part.group, part.island) == ("rail", CORE)
    validate_archipelago_island_plan(result.plan, spec, CORE)

    # The source is the **whole** document's digest, not a fabricated sub-spec.
    assert result.plan.source == LayoutSource(
        circuit_sha256=circuit.sha256(),
        presentation_sha256=spec.sha256(),
    )

    # The local gate ran, and it did not have to forgive anything here.
    assert result.gate.hard_violations == []
    assert result.gate.grammar_findings == []
    assert result.gate.ok is True


def test_a_single_island_reads_the_whole_partitions_crossing_nets(ldo):
    """`crossing=()` would make every cross-island rail look internal.

    A single compile must ask the **whole** partition which nets cross (the same
    answer the batch gets), and every crossing net is then named at this island's
    boundary — one flag or one label per crossing, as the page would draw it.
    """
    circuit, spec, profiles = ldo
    crossing = set(cross_island_nets(circuit, spec.effective_islands()))
    assert crossing  # the real LDO split crosses on its rails

    for island_id in (CORE, DECOUPLING):
        result = compile_island(circuit, spec, island_id, profiles)
        assert result.ok is True, result.refusal
        named = {symbol.net for symbol in result.block.power_symbols}
        named |= {label.net for label in result.block.labels}
        assert named == crossing


def test_the_local_plan_round_trips_with_its_source_identity_and_evidence(ldo):
    """to_jsonable → from_dict keeps the whole-spec hashes, identity and evidence."""
    from boardwise.core.layoutplan import LayoutPlan

    circuit, spec, profiles = ldo
    plan = compile_island(circuit, spec, DECOUPLING, profiles).plan
    assert plan is not None

    again = LayoutPlan.from_dict(plan.to_jsonable())
    assert again.source == LayoutSource(
        circuit_sha256=circuit.sha256(),
        presentation_sha256=spec.sha256(),
    )
    assert {
        (part.part_id, part.group, part.island) for part in again.parts
    } == {(part_id, "rail", DECOUPLING) for part_id in DECOUPLING_PARTS}
    assert again.evidence == plan.evidence
    assert again.geometry_sha256() == plan.geometry_sha256()


def test_decoupling_island_compiles_as_its_own_picture(ldo):
    """C1 + C2 alone: the second island is an independent local picture too."""
    circuit, spec, profiles = ldo
    result = compile_island(circuit, spec, DECOUPLING, profiles)

    assert result.ok is True, result.refusal
    assert result.block is not None and result.plan is not None
    assert result.block.island_id == DECOUPLING
    assert {part.part_id for part in result.plan.parts} == set(DECOUPLING_PARTS)
    for part in result.plan.parts:
        assert (part.group, part.island) == ("rail", DECOUPLING)
    validate_archipelago_island_plan(result.plan, spec, DECOUPLING)
    assert result.gate.hard_violations == []
    assert result.plan.source.presentation_sha256 == spec.sha256()


def test_scope_is_exactly_the_islands_own_parts_and_nothing_page_level(
    ldo, scope_spy
):
    """The checker gets the island scope and its layout grid, not page facts.

    No `page_box`, no `keepouts`, no grammar checker: page-level facts need the
    assembly and page context this batch does not have, so passing them here
    would claim a page check that never happened.
    """
    circuit, spec, profiles = ldo
    result = compile_island(circuit, spec, DECOUPLING, profiles)
    assert result.ok is True

    assert len(scope_spy) == 1
    kwargs = scope_spy[0]
    assert set(kwargs) == {"scope", "grid"}
    assert kwargs["grid"] == islandlayout.IslandBudget().grid
    assert kwargs["scope"] == readability.ReadabilityScope(
        parts=DECOUPLING_PARTS,
        check_page_locks=False,
        check_module_locks=False,
    )
    # And the plan really draws only those parts: the scope is not a promise.
    assert {part.part_id for part in result.plan.parts} == set(DECOUPLING_PARTS)


# ------------------------------------------------- 2. the evidence it writes


def test_successful_plan_carries_scoped_layout_evidence(ldo):
    """Checker name, empty hard/grammar, every soft metric + reason preserved."""
    circuit, spec, profiles = ldo
    result = compile_island(circuit, spec, CORE, profiles)
    assert result.ok is True

    evidence = result.plan.evidence
    assert evidence.checker == drawcompiler.CHECKER_NAME
    assert evidence.hard_violations == []
    assert evidence.grammar_findings == []
    assert evidence.soft_metrics  # measured, not empty
    assert evidence.soft_metrics == result.gate.soft_metrics
    assert evidence.soft_reasons == {
        key: " | ".join(value)
        for key, value in result.gate.soft_reasons.items()
    }
    assert set(evidence.soft_reasons) <= set(evidence.soft_metrics)
    assert evidence.verdict == "pass"

    # The notes say out loud what this is and what did **not** run.
    text = "\n".join(evidence.notes)
    assert "independent island compile" in text
    assert "not a packed page" in text
    assert "grammar/page layers did not run" in text
    assert "page_box" in text
    assert "no grammar was executed" in text


def test_a_successful_result_has_no_page_or_pack_below_it(ldo, monkeypatch):
    """`island_page` / `pack_islands` are never called, and no page is produced."""
    circuit, spec, profiles = ldo

    def boom(*args, **kwargs):
        raise AssertionError(
            "independent island compile must not build a page or pack islands"
        )

    monkeypatch.setattr(islandlayout, "island_page", boom)
    monkeypatch.setattr(islandlayout, "pack_islands", boom)

    results = compile_islands(circuit, spec, profiles)
    assert [result.island_id for result in results] == [CORE, DECOUPLING]
    declared = {
        island.id: set(island.parts) for island in spec.effective_islands()
    }
    for result in results:
        assert result.ok is True
        assert not isinstance(result.block, islandlayout.PackedPage)
        # The plan's own notes still say where it came from.
        assert islandlayout.ISLAND_LAYOUT_KIND in result.plan.notes
        # One island's parts, and no other island's.
        assert {part.part_id for part in result.plan.parts} == declared[
            result.island_id
        ]


# ------------------------------ 3. batch order, single-island equality, stability


def test_batch_follows_declared_order_and_matches_single_islands(ldo):
    """Batch = `effective_islands()` order; each result is the single compile."""
    circuit, spec, profiles = ldo
    batch = compile_islands(circuit, spec, profiles)

    assert [result.island_id for result in batch] == [
        island.id for island in spec.effective_islands()
    ]
    assert [result.island_id for result in batch] == [CORE, DECOUPLING]

    for result in batch:
        single = compile_island(circuit, spec, result.island_id, profiles)
        assert result.ok is True and single.ok is True
        assert result.plan.geometry_sha256() == single.plan.geometry_sha256()
        assert result.plan.to_jsonable() == single.plan.to_jsonable()
        assert result.block == single.block
        assert result.plan.evidence == single.plan.evidence


def test_the_same_input_gives_the_same_picture_and_evidence(ldo):
    """No variant ladder: identical input means an identical digest and evidence."""
    circuit, spec, profiles = ldo
    first = compile_island(circuit, spec, CORE, profiles)
    second = compile_island(circuit, spec, CORE, profiles)
    assert first.plan.geometry_sha256() == second.plan.geometry_sha256()
    assert first.plan.evidence == second.plan.evidence
    assert first.plan.to_jsonable() == second.plan.to_jsonable()


def test_batch_results_carry_their_original_request(ldo):
    """The frozen request keeps the inputs and budget 538C will recompile from."""
    from boardwise.engines.islandlayout import IslandBudget

    circuit, spec, profiles = ldo
    budget = IslandBudget()
    result = compile_island(circuit, spec, CORE, profiles, budget=budget)

    assert result.ok is True
    request = result.request
    assert isinstance(request, IslandCompileRequest)
    assert request.circuit is circuit
    assert request.presentation is spec
    assert request.island_id == CORE
    assert request.profiles is profiles
    assert request.budget is budget

    default = compile_island(circuit, spec, CORE, profiles)
    assert default.request.budget is None


# ------------------------------------------------- 4. frozen shape, `ok` truth


def test_a_success_needs_block_plan_and_gate(ldo):
    """The invariant is checked, not documented: an incomplete success is refused."""
    circuit, spec, profiles = ldo
    good = compile_island(circuit, spec, CORE, profiles)
    assert good.ok is True

    for missing in ("block", "plan", "gate"):
        with pytest.raises(ValueError):
            replace(good, **{missing: None})
    with pytest.raises(FrozenInstanceError):
        good.island_id = "another"


def test_a_refusal_never_carries_a_candidate(ldo):
    """A failed island has no block/plan — no half-built candidate to adopt."""
    circuit, spec, profiles = ldo
    failed = compile_island(
        circuit, spec, DECOUPLING, _missing_c1_profiles(circuit, profiles)
    )
    assert failed.ok is False
    assert failed.refusal is not None
    assert failed.block is None and failed.plan is None

    with pytest.raises(ValueError):
        replace(failed, plan=compile_island(circuit, spec, CORE, profiles).plan)
    with pytest.raises(ValueError):
        replace(failed, block=compile_island(circuit, spec, CORE, profiles).block)
    with pytest.raises(ValueError):
        replace(failed, refusal=None)


def test_ok_is_derived_from_the_refusal_not_from_gate_ok(ldo):
    """A tolerated row leaves `gate.ok` False and the island still ok.

    The result's `ok` is this island's own reading: refusing is what decides it,
    and the host-printed rows the delivery policy tolerates are carried, named.
    """
    circuit, spec, profiles = ldo
    good = compile_island(circuit, spec, DECOUPLING, profiles)
    assert good.ok is True

    row = readability.HardViolation(
        kind=readability.KIND_TEXT_ON_WIRE,
        objects=("segments[0]", "texts[0]"),
        evidence="a host-printed wire name crosses a placed row",
    )
    refusing, tolerated = drawcompiler.island_gate_violations([row])
    assert refusing == [] and tolerated == [row]

    gate = readability.CheckResult(
        hard_violations=[row],
        soft_metrics=dict(good.gate.soft_metrics),
        soft_reasons=dict(good.gate.soft_reasons),
    )
    assert gate.ok is False  # the raw checker is not the delivery policy

    carried = replace(good, gate=gate, tolerated=(row,))
    assert carried.ok is True
    assert carried.refusal is None
    assert carried.tolerated == (row,)


# --------------------------------------- 5. missing facts are a structured refusal


def test_a_missing_profile_is_a_facts_missing_refusal_not_a_keyerror(ldo):
    """Lacking C1's profile refuses that island, names the hole, has no candidate."""
    circuit, spec, profiles = ldo
    partial = _missing_c1_profiles(circuit, profiles)

    core, decoupling = compile_islands(circuit, spec, partial)
    assert core.ok is True
    assert decoupling.ok is False
    assert decoupling.block is None and decoupling.plan is None
    assert decoupling.refusal is not None
    assert decoupling.refusal.category == FAILURE_FACTS_MISSING
    assert "C1" in decoupling.refusal.detail
    assert decoupling.refusal.action  # a refusal says what to change
    assert decoupling.gate is None  # the layout never ran for this island

    single = compile_island(circuit, spec, DECOUPLING, partial)
    assert single.ok is False
    assert single.refusal.category == FAILURE_FACTS_MISSING
    assert single.block is None and single.plan is None


def test_the_whole_contract_is_checked_before_any_layout(ldo, monkeypatch):
    """A presentation that drops a circuit part is refused, and nothing is laid out."""
    circuit, spec, profiles = ldo

    def boom(*args, **kwargs):
        raise AssertionError("layout must not run for a refused whole contract")

    monkeypatch.setattr(islandlayout, "layout_island", boom)

    raw = spec.to_jsonable()
    for module in raw["modules"]:
        module["parts"] = [part for part in module["parts"] if part != "C2"]
    for island in raw["islands"]:
        if island["id"] == DECOUPLING:
            island["parts"] = [
                part for part in island["parts"] if part != "C2"
            ]
    broken = PresentationSpec.from_dict(raw)

    with pytest.raises(ArchipelagoError, match="C2"):
        compile_islands(circuit, broken, profiles)
    with pytest.raises(ArchipelagoError, match="C2"):
        compile_island(circuit, broken, CORE, profiles)


def test_an_undeclared_island_is_refused_before_any_layout(ldo, monkeypatch):
    """A name nobody declared is an input error, never checked against a guess."""
    circuit, spec, profiles = ldo

    def boom(*args, **kwargs):
        raise AssertionError("layout must not run for an unknown island")

    monkeypatch.setattr(islandlayout, "layout_island", boom)

    with pytest.raises(ArchipelagoError, match="declares no island"):
        compile_island(circuit, spec, "no_such_island", profiles)


# ---------------------------------- 6. a raising stage refuses that island only


def test_a_layout_exception_refuses_that_island_and_the_batch_continues(
    ldo, monkeypatch
):
    """A placer exception is this island's refusal — not the end of the batch.

    The layout stage has no plan yet, so the refusal may carry no gate: the
    evidence a failed island keeps is the refusal itself, named by island, stage
    and the original exception.  The other island is still compiled, in order.
    """
    circuit, spec, profiles = ldo
    original = islandlayout.layout_island
    laid_out: list[str] = []

    def flaky(circuit_arg, subgraph, profile_arg, *, budget=None):
        laid_out.append(subgraph.island_id)
        if subgraph.island_id == CORE:
            raise readability.ReadabilityError(
                "U1's anchor row leaves no room for its own pin fan-out"
            )
        return original(circuit_arg, subgraph, profile_arg, budget=budget)

    monkeypatch.setattr(islandlayout, "layout_island", flaky)

    results = compile_islands(circuit, spec, profiles)
    assert laid_out == [CORE, DECOUPLING]  # tried once each, no retry
    assert [result.island_id for result in results] == [CORE, DECOUPLING]

    core, decoupling = results
    assert core.ok is False
    assert core.block is None and core.plan is None
    assert core.gate is None  # the layout never produced a reading
    assert core.refusal is not None
    assert core.refusal.category in FAILURE_CATEGORIES
    assert CORE in core.refusal.detail  # which island
    assert "layout" in core.refusal.detail  # which stage
    assert "ReadabilityError" in core.refusal.detail  # what raised
    assert "no room for its own pin fan-out" in core.refusal.detail
    assert core.refusal.action  # a refusal says what to change

    assert decoupling.ok is True, decoupling.refusal
    assert decoupling.plan is not None

    single = compile_island(circuit, spec, CORE, profiles)
    assert single.ok is False
    assert single.block is None and single.plan is None and single.gate is None
    assert single.refusal.category in FAILURE_CATEGORIES
    assert "layout" in single.refusal.detail


def test_a_scoped_identity_error_is_a_presentation_refusal_not_an_escape(
    ldo, monkeypatch
):
    """`ArchipelagoError` from the scoped identity check refuses **that** island.

    The plan's declared partition disagreeing with the presentation is a
    presentation fact (538A's own category), so the refusal is
    `presentation-poor`, carries no candidate, and never escapes the batch.
    """
    circuit, spec, profiles = ldo
    original = islandcompile.validate_archipelago_island_plan
    checked: list[str] = []

    def strict(plan, presentation, island_id):
        checked.append(island_id)
        if island_id == DECOUPLING:
            raise ArchipelagoError(
                "island 'rail_decoupling': the plan draws C9, which the island "
                "does not declare"
            )
        return original(plan, presentation, island_id)

    monkeypatch.setattr(
        islandcompile, "validate_archipelago_island_plan", strict
    )

    results = compile_islands(circuit, spec, profiles)
    assert checked == [CORE, DECOUPLING]
    core, decoupling = results

    assert core.ok is True, core.refusal
    assert decoupling.ok is False
    assert decoupling.block is None and decoupling.plan is None
    assert decoupling.gate is None
    assert decoupling.refusal is not None
    assert decoupling.refusal.category == FAILURE_PRESENTATION_POOR
    assert DECOUPLING in decoupling.refusal.detail
    assert "identity" in decoupling.refusal.detail
    assert "C9" in decoupling.refusal.detail
    assert decoupling.refusal.action

    single = compile_island(circuit, spec, DECOUPLING, profiles)
    assert single.ok is False and single.plan is None
    assert single.refusal.category == FAILURE_PRESENTATION_POOR


def test_an_injected_hard_violation_is_refused_with_its_gate_kept(
    ldo, monkeypatch
):
    """A hard finding goes through the shared kind table, and the gate stays.

    The gate is the reading the refusal was made from: it is evidence, never a
    candidate, so `gate` is kept while `block`/`plan` are not.
    """
    circuit, spec, profiles = ldo
    original = readability.check
    row = readability.HardViolation(
        kind=readability.KIND_NC_PIN_CONNECTED,
        objects=("C1", "pin 2"),
        evidence="the plant's own no-connect pin is wired in this picture",
    )

    def injecting(layout_plan, *args, **kwargs):
        checked = original(layout_plan, *args, **kwargs)
        drawn = {part.part_id for part in layout_plan.parts}
        if drawn & DECOUPLING_PARTS:
            checked.hard_violations.append(row)
        return checked

    monkeypatch.setattr(readability, "check", injecting)

    core, decoupling = compile_islands(circuit, spec, profiles)
    assert core.ok is True
    assert decoupling.ok is False
    assert decoupling.block is None and decoupling.plan is None
    assert decoupling.gate is not None
    assert decoupling.gate.hard_violations == [row]
    assert decoupling.gate.soft_metrics  # the real reading came back with it
    assert decoupling.tolerated == ()
    assert decoupling.refusal.category == FAILURE_CIRCUIT_INVALID
    assert readability.KIND_NC_PIN_CONNECTED in decoupling.refusal.detail


def test_a_soft_floor_breach_refuses_without_leaving_a_pass_looking_plan(
    ldo, monkeypatch
):
    """Over the style spec's soft floor: `layout-unsat`, gate kept, no candidate.

    The hard gate is clean here, so `gate.ok` is True — and the island is still
    refused.  `ok` is the result's, not the gate's, and a refused island leaves
    no plan whose evidence would read `pass` to a caller.
    """
    circuit, spec, profiles = ldo
    original = readability.soft_floor_violations
    breach = (
        "S-09: 7 bends over 2 wires = 3.50 per root, target is <= 1 per root"
    )

    def floored(layout_plan, soft_metrics, profile_map):
        if {part.part_id for part in layout_plan.parts} & DECOUPLING_PARTS:
            return [breach]
        return original(layout_plan, soft_metrics, profile_map)

    monkeypatch.setattr(readability, "soft_floor_violations", floored)

    core, decoupling = compile_islands(circuit, spec, profiles)
    assert core.ok is True
    assert core.plan.evidence.verdict == "pass"

    assert decoupling.ok is False
    assert decoupling.block is None
    assert decoupling.plan is None  # nothing adoptable survives the refusal
    assert decoupling.gate is not None
    assert decoupling.gate.ok is True  # the hard gate was clean; the floor refused
    assert decoupling.refusal.category == FAILURE_LAYOUT_UNSAT
    assert "S-09" in decoupling.refusal.detail


def test_a_readability_exception_is_a_structured_refusal(ldo, monkeypatch):
    """The checker itself raising is a fact hole for **that** island, not a crash.

    `readability.check` raises `ReadabilityError` when it cannot judge the
    inputs at all (a placed part whose symbol no profile describes).  That is a
    missing fact, and it must not escape a batch as an exception.
    """
    circuit, spec, profiles = ldo
    original = readability.check

    def failing(layout_plan, *args, **kwargs):
        drawn = {part.part_id for part in layout_plan.parts}
        if drawn & DECOUPLING_PARTS:
            raise readability.ReadabilityError(
                "the plan names symbol 'C_0603' the profile set does not carry"
            )
        return original(layout_plan, *args, **kwargs)

    monkeypatch.setattr(readability, "check", failing)

    core, decoupling = compile_islands(circuit, spec, profiles)
    assert core.ok is True
    assert decoupling.ok is False
    assert decoupling.block is None and decoupling.plan is None
    assert decoupling.gate is None  # the checker returned no reading at all
    assert decoupling.refusal is not None
    assert decoupling.refusal.category == FAILURE_FACTS_MISSING
    assert "readability" in decoupling.refusal.detail
    assert "ReadabilityError" in decoupling.refusal.detail
    assert "C_0603" in decoupling.refusal.detail
    assert decoupling.refusal.action

    single = compile_island(circuit, spec, DECOUPLING, profiles)
    assert single.ok is False and single.plan is None
    assert single.refusal.category == FAILURE_FACTS_MISSING


def test_two_different_failures_in_one_batch_stay_separate(ldo, monkeypatch):
    """A layout crash on one island and a profile hole on the other, both shaped.

    Neither failure is allowed to take the batch with it, both results keep the
    declared order, and each refusal is its own island's.
    """
    circuit, spec, profiles = ldo
    partial = _missing_c1_profiles(circuit, profiles)
    original = islandlayout.layout_island

    def flaky(circuit_arg, subgraph, profile_arg, *, budget=None):
        if subgraph.island_id == CORE:
            raise readability.ReadabilityError("the anchor pin fan-out collapsed")
        return original(circuit_arg, subgraph, profile_arg, budget=budget)

    monkeypatch.setattr(islandlayout, "layout_island", flaky)

    results = compile_islands(circuit, spec, partial)
    assert [result.island_id for result in results] == [CORE, DECOUPLING]

    core, decoupling = results
    assert core.ok is False and decoupling.ok is False
    assert core.plan is None and decoupling.plan is None
    assert core.block is None and decoupling.block is None
    assert core.refusal.category in FAILURE_CATEGORIES
    assert decoupling.refusal.category == FAILURE_FACTS_MISSING
    assert "C1" in decoupling.refusal.detail
    assert core.refusal.detail != decoupling.refusal.detail


def test_a_programming_error_is_not_swallowed_as_a_refusal(ldo, monkeypatch):
    """Only shaped exceptions become refusals; a `TypeError` is still a bug."""
    circuit, spec, profiles = ldo

    def broken(*args, **kwargs):
        raise TypeError("a bug the island compiler must not report as a refusal")

    monkeypatch.setattr(islandlayout, "layout_island", broken)

    with pytest.raises(TypeError, match="must not report as a refusal"):
        compile_islands(circuit, spec, profiles)


# --------------------- 7. 538C — explicit recompile and local rollback


def _flat_spec(spec: PresentationSpec) -> PresentationSpec:
    """The same islands with none of the archipelago keys: the legacy flat read."""
    raw = spec.to_jsonable()
    for island in raw["islands"]:
        for key in ("group", "owner", "kind", "side"):
            island.pop(key, None)
    return PresentationSpec.from_dict(raw)


def test_recompile_recomputes_only_the_named_island_from_its_own_request(
    ldo, monkeypatch, scope_spy
):
    """One explicit call, one island: the other result is not touched at all.

    Local rollback is "recompile this failed/parked island", not "run the page
    again": the batch's other result keeps its object identity and every field,
    and the recompiled island's digest and evidence are the same input's.
    """
    from boardwise.engines.islandlayout import IslandBudget

    circuit, spec, profiles = ldo
    core, decoupling = compile_islands(circuit, spec, profiles)
    assert core.ok is True and decoupling.ok is True

    core_plan, core_block, core_notes = core.plan, core.block, core.notes
    digest = decoupling.plan.geometry_sha256()
    payload = decoupling.plan.to_jsonable()
    evidence = decoupling.plan.evidence
    old_notes = decoupling.notes

    laid_out: list[tuple[str, object]] = []
    original_layout = islandlayout.layout_island

    def layout_spy(circuit_arg, subgraph, profile_arg, *, budget=None):
        laid_out.append((subgraph.island_id, budget))
        return original_layout(circuit_arg, subgraph, profile_arg, budget=budget)

    checked: list[str] = []
    original_identity = islandcompile.validate_archipelago_island_plan

    def identity_spy(plan, presentation, island_id):
        checked.append(island_id)
        return original_identity(plan, presentation, island_id)

    monkeypatch.setattr(islandlayout, "layout_island", layout_spy)
    monkeypatch.setattr(
        islandcompile, "validate_archipelago_island_plan", identity_spy
    )
    scope_spy.clear()  # forget the batch's own two checks; this is the recompile

    again = recompile_island(decoupling)

    # Exactly the named island, exactly once, with its own frozen request.
    assert laid_out == [(DECOUPLING, None)]
    assert checked == [DECOUPLING]
    assert len(scope_spy) == 1
    assert scope_spy[0]["scope"] == readability.ReadabilityScope(
        parts=DECOUPLING_PARTS,
        check_page_locks=False,
        check_module_locks=False,
    )
    assert isinstance(again, IslandCompileResult)
    assert again is not decoupling
    assert again.island_id == DECOUPLING
    assert again.request.circuit is circuit
    assert again.request.presentation is spec
    assert again.request.profiles is profiles
    assert again.request.island_id == DECOUPLING
    assert again.request.budget is None

    # Same input, same picture and same evidence: no variant ladder.
    assert again.ok is True, again.refusal
    assert again.plan.geometry_sha256() == digest
    assert again.plan.to_jsonable() == payload
    assert again.plan.evidence == evidence
    assert again.plan.evidence.notes == evidence.notes
    assert "unchanged input" in "\n".join(again.notes)
    assert "not a new variant" in "\n".join(again.notes)
    assert "budget" in "\n".join(again.notes)
    assert "profile" in "\n".join(again.notes)
    assert "specification" in "\n".join(again.notes)

    # Local rollback: neither the old result nor the other island moved.
    assert decoupling.plan.geometry_sha256() == digest
    assert decoupling.plan.to_jsonable() == payload
    assert decoupling.plan.evidence == evidence
    assert decoupling.notes == old_notes
    assert core.plan is core_plan
    assert core.block is core_block
    assert core.notes == core_notes


def test_recompile_with_a_new_budget_passes_it_and_names_the_changed_input(
    ldo, monkeypatch
):
    """A new `IslandBudget` is what reaches the placer — and the only input change."""
    from boardwise.engines.islandlayout import IslandBudget

    circuit, spec, profiles = ldo
    original_budget = IslandBudget()
    result = compile_island(circuit, spec, CORE, profiles, budget=original_budget)
    assert result.ok is True

    new_budget = IslandBudget(pin_gap=24.0)
    seen: list[object] = []
    original_layout = islandlayout.layout_island

    def layout_spy(circuit_arg, subgraph, profile_arg, *, budget=None):
        seen.append(budget)
        return original_layout(circuit_arg, subgraph, profile_arg, budget=budget)

    monkeypatch.setattr(islandlayout, "layout_island", layout_spy)

    again = recompile_island(result, budget=new_budget)
    assert seen == [new_budget]
    assert again.request.budget is new_budget
    assert again.request.circuit is result.request.circuit
    assert again.request.presentation is result.request.presentation
    assert again.request.profiles is result.request.profiles
    # The old result keeps its own budget: a recompile is not an edit.
    assert result.request.budget is original_budget

    text = "\n".join(again.notes)
    assert "changed budget" in text
    assert "reused unchanged" in text
    assert "unchanged input" not in text


def test_recompile_needs_the_original_request(ldo):
    """Without the frozen request there is nothing to recompile from."""
    circuit, spec, profiles = ldo
    good = compile_island(circuit, spec, CORE, profiles)
    orphan = replace(good, request=None)
    with pytest.raises(ValueError, match="request"):
        recompile_island(orphan)


@pytest.mark.parametrize("value", [None, "rail_core", 42, object()])
def test_recompile_refuses_anything_but_a_result(value):
    """The type is the input contract, so it is a `TypeError`, not a guess."""
    with pytest.raises(TypeError, match="IslandCompileResult"):
        recompile_island(value)


def test_recompile_of_a_refused_island_repeats_the_same_refusal(
    ldo, monkeypatch
):
    """A facts hole is not retried into a success, and it leaves no candidate.

    The refusal's category, detail and action are the same failure as before —
    only the notes say what was (and was not) changed — and the layout never
    runs, so there is no hidden second attempt behind the explicit call.
    """
    circuit, spec, profiles = ldo
    partial = _missing_c1_profiles(circuit, profiles)
    failed = compile_island(circuit, spec, DECOUPLING, partial)
    assert failed.ok is False
    assert failed.request is not None
    category = failed.refusal.category
    detail = failed.refusal.detail
    action = failed.refusal.action

    def boom(*args, **kwargs):
        raise AssertionError("a facts hole must not reach the layout")

    monkeypatch.setattr(islandlayout, "layout_island", boom)

    again = recompile_island(failed)
    assert again is not failed
    assert again.ok is False
    assert again.refusal is not None
    assert again.refusal.category == category
    assert again.refusal.detail == detail
    assert again.refusal.action == action
    assert again.block is None and again.plan is None
    assert again.gate is None
    assert "unchanged input" in "\n".join(again.notes)
    assert "not a new variant" in "\n".join(again.notes)
    # The refusal that was already recorded is not rewritten.
    assert failed.notes == ()
    assert failed.refusal.detail == detail


def test_a_non_archipelago_presentation_is_refused_before_any_layout(
    ldo, monkeypatch
):
    """A flat island list is not an archipelago; it is refused by name, early."""
    circuit, spec, profiles = ldo
    flat = _flat_spec(spec)
    assert flat.is_archipelago is False

    def boom(*args, **kwargs):
        raise AssertionError(
            "a presentation that declares no archipelago has no island to lay out"
        )

    monkeypatch.setattr(islandlayout, "layout_island", boom)

    with pytest.raises(ArchipelagoError, match="archipelago island"):
        compile_island(circuit, flat, CORE, profiles)
    with pytest.raises(ArchipelagoError, match="archipelago island"):
        compile_islands(circuit, flat, profiles)
