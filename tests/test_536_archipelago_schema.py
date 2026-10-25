"""536 — 岛群 schema、plan 身份与 hard 校验的生产聚焦测试。

覆盖加性 schema 与旧 digest、IslandBlock/LayoutPart 身份持久化、编译前置拒绝、
pagecompiler 防丢岛、普通/page 两条 ChangePlan 构造路径，以及 page apply 在连接编辑器前的
partition 回验。红阶段记录见 `tasks/536_archipelago_schema.md`；这里断言的是当前生产契约，
不是临时参考实现。

仍然只到 A 层：不测子岛独立排版、核心+卫星组内装配、多群页级 pack、真机或全量库。
契约：`docs/drawing-archipelago-route.md` §2.2 / §2.3 / §5；最小例
`docs/examples/archipelago_min/`。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.islands import IMPLICIT_ISLAND_ID
from boardwise.core.layoutplan import LayoutPart, LayoutPlan, LayoutSource
from boardwise.core.presentationspec import PresentationSpec, PresentationSpecError

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "archipelago_min"
CIRCUIT = EXAMPLES / "mcu_cluster.circuit.json"
PRESENTATION = EXAMPLES / "mcu_cluster.presentation.draft.json"

#: §2.2：前三个必填，`side` 省略 = 未声明岛级偏好（不写 `auto`）。
IDENTITY_FIELDS = ("group", "owner", "kind", "side")
REQUIRED_FIELDS = ("group", "owner", "kind")

#: §7 的四个子岛，逐字对照：(parts, group, owner, kind, side)。
EXPECTED_ISLANDS: dict[str, tuple[list[str], str, str, str, str]] = {
    "mcu_core": (["U1"], "mcu_cluster", "U1", "core", ""),
    "mcu_decoupling": (["C1", "C2"], "mcu_cluster", "U1", "decoupling", "left"),
    "mcu_clock": (["Y1", "C3", "C4"], "mcu_cluster", "U1", "clock", "right"),
    "mcu_swd": (["H1"], "mcu_cluster", "U1", "programming", "top"),
}

#: 一个**没有**任何新字段的旧反激表现：兼容路径的参照物。
LEGACY_FLYBACK = {
    "kind": "boardwise-presentation-spec", "specVersion": 1, "grammarRef": "flyback",
    "modules": [{"id": "flyback", "role": "legacy flyback", "parts": ["Q1", "T1", "D3"]}],
    "islands": [{"id": "primary", "parts": ["Q1"], "role": "primary"},
                {"id": "bridge", "parts": ["T1"], "role": "bridge"},
                {"id": "secondary", "parts": ["D3"], "role": "secondary"}],
}


@pytest.fixture()
def circuit() -> CircuitSpec:
    return CircuitSpec.load(CIRCUIT)


@pytest.fixture()
def archipelago() -> dict:
    return json.loads(PRESENTATION.read_text(encoding="utf-8"))


@pytest.fixture()
def arch_spec() -> PresentationSpec:
    return PresentationSpec.load(PRESENTATION)


@pytest.fixture()
def legacy_spec() -> PresentationSpec:
    return PresentationSpec.from_dict({
        "kind": "boardwise-presentation-spec", "specVersion": 1,
        "grammarRef": "ic-periphery",
        "modules": [{"id": "mcu_cluster", "role": "legacy MCU", "grammarRef": "ic-periphery",
                     "parts": ["U1", "C1", "C2", "Y1", "C3", "C4", "H1"]}],
    })


def _archipelago_module():
    """The 536 module, imported where it is used (see the docstring's first rule)."""
    from boardwise.core import archipelago

    return archipelago


def _stated(island, name: str) -> str:
    """A field's stated value; an omitted `side` reads as "not stated" either way."""
    value = getattr(island, name, "")
    return "" if value is None else value


def _islands(spec: PresentationSpec) -> dict[str, object]:
    return {island.id: island for island in spec.islands or []}


def _identity_plan(spec: PresentationSpec, overrides=None) -> LayoutPlan:
    """One stamped `LayoutPart` per declared part; ``overrides`` builds wrong identities."""
    overrides, islands, parts = overrides or {}, spec.islands or [], []
    for module in spec.modules:
        for part_id in module.parts:
            island = next(item for item in islands if part_id in item.parts)
            group, island_id = overrides.get(part_id, (island.group, island.id))
            parts.append(LayoutPart(part_id=part_id, symbol_ref="GENERIC",
                                    group=group, island=island_id))
    return LayoutPlan(source=LayoutSource(presentation_sha256=spec.sha256()), parts=parts)


def _block(island_id: str, part_id: str, *, group: str = ""):
    from boardwise.engines.islandlayout import IslandBlock

    options = {"group": group} if group else {}
    return IslandBlock(island_id=island_id, role="control", anchor=part_id,
                       parts=[LayoutPart(part_id=part_id)], **options)


# ---------------------------------------------------------------------------
# A real three-piece set: blocklib/specs/ch340_serial.* read, never re-typed.
#
# The example above is the minimal `mcu_cluster`; this is the opposite witness —
# a measured library (CH340G, 12 MHz crystal, 22 pF and 100 nF capacitors) whose
# profiles carry real pin tips, so a compile here exercises the geometry rather
# than a stub.  Two island splits of the same module are the two shapes 536 has
# to keep straight: one island (the module is one picture) and two (core plus
# one satellite), which is the first shape a group can actually assemble.
# ---------------------------------------------------------------------------

SPECS = Path(__file__).resolve().parents[1] / "blocklib" / "specs"
CH340_CIRCUIT = SPECS / "ch340_serial.circuit.json"
CH340_PRESENTATION = SPECS / "ch340_serial.presentation.json"
CH340_LIBRARY = SPECS / "ch340_serial.library.json"
SERIAL_PARTS = ("U1", "X1", "C1", "C2", "C3", "C4")

#: (parts, role, kind, side); `side` "" is an island that states no side.
SERIAL_SINGLE_ISLANDS: dict[str, tuple[list[str], str, str, str]] = {
    "serial_core": (list(SERIAL_PARTS), "control", "core", ""),
}
LDO_TWO_ISLANDS: dict[str, tuple[list[str], str, str, str]] = {
    "rail_core": (["U1"], "control", "core", ""),
    "rail_decoupling": (["C1", "C2"], "secondary", "decoupling", "left"),
}


def _ch340_real_spec(islands: dict[str, tuple[list[str], str, str, str]]):
    """(circuit, spec, profiles) from the CH340 set, with `islands` declared.

    The presentation's top-level ``grammarRef`` / ``sidePreferences`` /
    ``portRoles`` are kept verbatim.  Only the module-level ``grammarRef`` is
    dropped so this one-group example does not get routed to the ordinary
    pagecompiler (`wants_page`): the child islands belong to drawcompiler's
    island path.  The library goes through
    `drawapply.load_library`, so these tests draw with the measured profiles and
    not with a hand-written substitute (the profiles' `source` fields say when
    and on which page each was measured).
    """
    from boardwise.engines import drawapply

    circuit = CircuitSpec.load(CH340_CIRCUIT)
    profiles = drawapply.load_library(CH340_LIBRARY)
    raw = json.loads(CH340_PRESENTATION.read_text(encoding="utf-8"))
    for module in raw["modules"]:
        module.pop("grammarRef", None)
    raw["islands"] = [
        {
            "id": island_id,
            "parts": list(parts),
            "role": role,
            "group": "serial",
            "owner": "U1",
            "kind": kind,
            **({"side": side} if side else {}),
        }
        for island_id, (parts, role, kind, side) in islands.items()
    ]
    return circuit, PresentationSpec.from_dict(raw), profiles


def _ldo_real_spec(islands: dict[str, tuple[list[str], str, str, str]]):
    """The existing LDO grammar/profile helpers, with an archipelago partition.

    The direct-wire obligation is deliberately removed: the decoupling island is
    a separate picture and its rails cross by flags, not by one whole-module wire.
    """
    from test_053b_drawcompiler import ldo_circuit, ldo_presentation, library

    circuit = ldo_circuit()
    raw = ldo_presentation().to_jsonable()
    raw.pop("directWiringObligations", None)
    raw["modules"][0]["core"] = "U1"
    raw["islands"] = [
        {
            "id": island_id,
            "parts": list(parts),
            "role": role,
            "group": "rail",
            "owner": "U1",
            "kind": kind,
            **({"side": side} if side else {}),
        }
        for island_id, (parts, role, kind, side) in islands.items()
    ]
    return circuit, PresentationSpec.from_dict(raw), library()


def test_minimal_draft_loads_as_archipelago(arch_spec):
    """The example draft is the archipelago shape, and its four islands read back."""
    assert arch_spec.is_archipelago is True
    islands = _islands(arch_spec)
    assert sorted(islands) == sorted(EXPECTED_ISLANDS)
    for island_id, (parts, group, owner, kind, side) in EXPECTED_ISLANDS.items():
        island = islands[island_id]
        assert list(island.parts) == parts
        assert (_stated(island, "group"), _stated(island, "owner")) == (group, owner)
        assert (_stated(island, "kind"), _stated(island, "side")) == (kind, side)


def test_archipelago_round_trip_keeps_fields_and_digest(arch_spec):
    """Serialise -> read back: the four keys survive and the digest is unchanged."""
    payload = arch_spec.to_jsonable()
    for entry in payload["islands"]:
        assert set(entry) >= {"id", "parts", *REQUIRED_FIELDS}
    restored = PresentationSpec.from_dict(copy.deepcopy(payload))
    assert restored.is_archipelago is True
    assert restored.to_jsonable() == payload
    assert restored.sha256() == arch_spec.sha256()


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_island_missing_identity_field_is_refused(archipelago, field):
    """`group` / `owner` / `kind` are mandatory once the spec is archipelago."""
    del archipelago["islands"][1][field]
    with pytest.raises(PresentationSpecError):
        PresentationSpec.from_dict(archipelago)


def test_mixed_new_and_old_islands_are_refused(archipelago):
    """A spec may not state an archipelago island and an old-style one together."""
    for field in IDENTITY_FIELDS:
        archipelago["islands"][3].pop(field)
    with pytest.raises(PresentationSpecError):
        PresentationSpec.from_dict(archipelago)


def test_legacy_flyback_islands_serialise_without_new_keys():
    """Old islands stay byte-shaped as before: no `group`/`owner`/`kind`/`side`."""
    spec = PresentationSpec.from_dict(copy.deepcopy(LEGACY_FLYBACK))
    assert spec.is_archipelago is False
    islands = spec.to_jsonable()["islands"]
    assert [entry["id"] for entry in islands] == ["primary", "bridge", "secondary"]
    for entry in islands:
        assert set(entry) == {"id", "parts", "role"}
        assert not set(IDENTITY_FIELDS) & set(entry)


def test_layout_part_identity_round_trips(circuit, arch_spec):
    """`group` / `island` are machine-readable fields, not notes or coordinates."""
    plan = LayoutPlan(source=LayoutSource(
        circuit_sha256=circuit.sha256(), presentation_sha256=arch_spec.sha256()), parts=[
        LayoutPart(part_id="U1", symbol_ref="GENERIC-MCU-6", symbol_hash="0" * 64,
                   group="mcu_cluster", island="mcu_core")])
    entry = plan.to_jsonable()["parts"][0]
    restored = LayoutPlan.from_dict(copy.deepcopy(plan.to_jsonable()))
    assert (entry["group"], entry["island"]) == ("mcu_cluster", "mcu_core")
    assert (restored.parts[0].group, restored.parts[0].island) == ("mcu_cluster", "mcu_core")
    assert restored.geometry_sha256() == plan.geometry_sha256()


def test_legacy_part_payload_has_no_identity_keys():
    """An unstamped part's payload says nothing new — old plans keep their bytes."""
    plan = LayoutPlan(parts=[LayoutPart(part_id="U1", symbol_ref="GENERIC-MCU-6")])
    assert not {"group", "island"} & set(plan.to_jsonable()["parts"][0])


def test_packed_page_stamps_archipelago_block():
    """Every part of an archipelago block carries its block's group and island."""
    from boardwise.engines.islandlayout import PackedPage

    plan = PackedPage(blocks=[_block("mcu_core", "U1", group="mcu_cluster")]).plan()
    assert (plan.parts[0].group, plan.parts[0].island) == ("mcu_cluster", "mcu_core")
    entry = plan.to_jsonable()["parts"][0]
    assert (entry["group"], entry["island"]) == ("mcu_cluster", "mcu_core")


def test_legacy_block_stamps_nothing():
    """A block that states no group produces no identity keys at all."""
    from boardwise.engines.islandlayout import PackedPage

    plan = PackedPage(blocks=[_block("all", "U1")]).plan()
    assert not {"group", "island"} & set(plan.to_jsonable()["parts"][0])
    assert not getattr(plan.parts[0], "group", "")


def test_translated_block_keeps_identity():
    """`translated` is a rigid move: the group and every part's identity travel."""
    source = _block("mcu_core", "U1", group="mcu_cluster")
    source.parts = [LayoutPart(part_id="U1", group="mcu_cluster", island="mcu_core")]
    moved = source.translated(80.0, -40.0)
    part = moved.parts[0]
    assert moved.group == "mcu_cluster"
    assert (part.group, part.island) == ("mcu_cluster", "mcu_core")
    assert (part.x, part.y) == (80.0, -40.0)


def test_archipelago_plan_is_accepted(circuit, arch_spec):
    """The minimal example's declared partition validates, as a plan and as specs."""
    module = _archipelago_module()
    assert issubclass(module.ArchipelagoError, ValueError)
    module.validate_archipelago(circuit, arch_spec)
    module.validate_archipelago_plan(_identity_plan(arch_spec), arch_spec)


@pytest.mark.parametrize("label, overrides", [
    ("missing-island", {"U1": ("mcu_cluster", "")}),
    ("wrong-group", {"U1": ("not_a_group", "mcu_core")}),
    ("wrong-island", {"C1": ("mcu_cluster", "mcu_core")}),
])
def test_plan_with_wrong_identity_is_refused(arch_spec, label, overrides):
    """The plan's partition must equal the declaration exactly — no notes, no guessing."""
    module = _archipelago_module()
    with pytest.raises(module.ArchipelagoError):
        module.validate_archipelago_plan(_identity_plan(arch_spec, overrides), arch_spec)


def test_plan_with_extra_part_is_refused(arch_spec):
    """A part the presentation never placed has no island, so the plan is not exact."""
    module = _archipelago_module()
    plan = _identity_plan(arch_spec)
    plan.parts.append(LayoutPart(part_id="X9", symbol_ref="GENERIC",
                                 group="mcu_cluster", island="mcu_core"))
    with pytest.raises(module.ArchipelagoError):
        module.validate_archipelago_plan(plan, arch_spec)


def test_legacy_spec_needs_no_stamping(circuit, legacy_spec):
    """A legacy presentation passes both validators with an unstamped plan."""
    module = _archipelago_module()
    module.validate_archipelago(circuit, legacy_spec)
    plan = LayoutPlan(parts=[LayoutPart(part_id=part_id, symbol_ref="GENERIC")
                            for part_id in legacy_spec.declared_part_ids()])
    module.validate_archipelago_plan(plan, legacy_spec)


def test_compile_refuses_broken_archipelago_netlist_before_binding(circuit, arch_spec):
    """H1 on no net: a named netlist violation, refused before bind/library."""
    from boardwise.engines import drawcompiler

    payload = copy.deepcopy(circuit.to_jsonable())
    for net in payload["nets"]:
        net["members"] = [m for m in net["members"] if not m.startswith("H1.")]
    result = drawcompiler.compile(CircuitSpec.from_dict(payload), arch_spec, profiles={})
    assert result.candidates == []
    assert result.best() is None
    assert "shares no net" in result.render_failures()
    # No grammar bound and no library read: never a grammar/missing-profile answer.
    assert result.grammar is None


def test_module_plan_checks_partition_for_non_page_layouts(circuit, arch_spec):
    """The ordinary LayoutPlan -> ChangePlan path has the same hard guard."""
    from boardwise.engines import drawapply

    plan = _identity_plan(arch_spec, {"H1": ("mcu_cluster", "mcu_core")})
    plan.source.circuit_sha256 = circuit.sha256()  # not a missing-source refusal
    with pytest.raises(drawapply.DrawPlanError, match="archipelago|partition"):
        drawapply.module_plan(plan, circuit, arch_spec, {})


def test_draw_plan_from_page_refuses_mismatched_plan(monkeypatch, circuit, arch_spec):
    """A page plan whose identity disagrees with the spec never reaches drawapply."""
    from boardwise import cli
    from boardwise.engines import drawapply

    def _must_not_run(*args, **kwargs):
        raise AssertionError(
            "drawapply.module_plan ran on a plan whose identities contradict the spec")

    monkeypatch.setattr(drawapply, "module_plan", _must_not_run)
    plan = _identity_plan(arch_spec, {"H1": ("mcu_cluster", "mcu_core")})
    with pytest.raises(drawapply.DrawPlanError):
        cli._draw_plan_from_page(SimpleNamespace(plan=plan, modules=[]),
                                 circuit, arch_spec, {})


def test_page_apply_checks_partition_before_opening_the_bridge(monkeypatch, circuit, arch_spec):
    """A mismatched page is refused before stale checks or any editor connection."""
    from boardwise import cli
    from boardwise.core.pagelayoutplan import PageLayoutPlan

    plan = _identity_plan(arch_spec, {"H1": ("mcu_cluster", "mcu_core")})
    plan.source.circuit_sha256 = circuit.sha256()  # not a stale-source refusal
    page = SimpleNamespace(plan=plan, modules=[])
    monkeypatch.setattr(PageLayoutPlan, "load", classmethod(lambda cls, path: page))
    monkeypatch.setattr(cli, "_draw_inputs", lambda args: (circuit, arch_spec, {}))
    monkeypatch.setattr(cli, "_draw_new_page_conflict", lambda args, page: "")
    opened = []
    monkeypatch.setattr(cli, "_open_cli", lambda args: opened.append(True))
    seen = {}

    def _render(report, args):
        seen.update(report)
        return report["exitCode"]

    monkeypatch.setattr(cli, "_render_draw_apply", _render)
    args = SimpleNamespace(
        plan="unused", circuit="c", presentation="p", profiles="l",
        page="P1", new_page=False,
    )
    assert cli._cmd_draw_apply_page(args) == 4
    assert seen["reason"] == "archipelago_partition"
    assert opened == []


def test_compile_refuses_multi_group_archipelago_until_assembler(circuit, archipelago):
    """Two groups need the later group assembler; direct compile may not flatten them."""
    raw = copy.deepcopy(archipelago)
    raw["modules"][0]["parts"].remove("H1")
    raw["modules"].append({
        "id": "swd_group", "parts": ["H1"], "role": "separate SWD group", "core": "H1",
    })
    swd = next(item for item in raw["islands"] if item["id"] == "mcu_swd")
    swd.update(group="swd_group", owner="H1", kind="core")
    spec = PresentationSpec.from_dict(raw)
    from boardwise.engines import drawcompiler

    result = drawcompiler.compile(circuit, spec, profiles={})
    text = result.render_failures()
    assert result.candidates == [] and result.grammar is None
    assert "multi-group" in text or "group assembler" in text


def test_pagecompiler_refuses_archipelago_instead_of_dropping_islands(circuit, arch_spec):
    """The ordinary module page path does not carry islands, so it must refuse."""
    from boardwise.engines import pagecompiler

    result = pagecompiler.compile_page(circuit, arch_spec, profiles={})
    text = result.render_failures()
    assert result.pages == []
    assert "archipelago" in text and "island" in text


def test_read_declared_still_refuses_new_fields(archipelago):
    """`draw islands propose` must not silently strip identity fields (§2.2)."""
    from boardwise.engines import islandproposal

    with pytest.raises(islandproposal.IslandsProposalError):
        islandproposal.read_declared(archipelago)


def test_partial_archipelago_cannot_be_serialised(arch_spec):
    """A half-stamped spec is refused when written, not read back as a worse file.

    `to_jsonable` runs the same structure pass `from_dict` does, so a document
    whose second island lost its `owner` never becomes JSON its own reader would
    reject — the refusal names the field rather than the symptom (053's digest
    contract means nothing is silently repaired here).
    """
    arch_spec.islands[1].owner = ""
    with pytest.raises(PresentationSpecError, match="owner"):
        arch_spec.to_jsonable()


def test_handwritten_reserved_id_is_refused_by_shared_structure(circuit, arch_spec):
    """`all` is the implicit island's id; a written island may not claim it.

    A hand-built spec reaches the structure pass without the parser's own guard,
    so the shared check (`validate_archipelago_structure`) is where the reserved
    id is refused — through `validate_archipelago`'s translation into the
    archipelago error.
    """
    arch_spec.islands[0].id = IMPLICIT_ISLAND_ID
    module = _archipelago_module()
    with pytest.raises(module.ArchipelagoError, match="implicit island"):
        module.validate_archipelago(circuit, arch_spec)


def test_plan_with_missing_part_is_refused(arch_spec):
    """A plan that drops a declared part is not the declared partition."""
    module = _archipelago_module()
    plan = _identity_plan(arch_spec)
    del plan.parts[0]
    with pytest.raises(module.ArchipelagoError, match="places no part"):
        module.validate_archipelago_plan(plan, arch_spec)


def test_plan_with_duplicate_part_is_refused(arch_spec):
    """Adding a second entry for a part it already places is two answers, not a fix."""
    module = _archipelago_module()
    plan = _identity_plan(arch_spec)
    plan.parts.append(copy.deepcopy(plan.parts[0]))
    with pytest.raises(module.ArchipelagoError, match="twice"):
        module.validate_archipelago_plan(plan, arch_spec)


def test_identity_changes_geometry_digest(arch_spec):
    """The island a part sits in is part of the picture, so it moves the digest.

    Two plans identical but for one part's island are different drawings: a
    preview bound to the first must not survive re-checking as the second.
    """
    plan = _identity_plan(arch_spec)
    moved = copy.deepcopy(plan)
    moved.parts[0].island = "different"
    assert moved.geometry_sha256() != plan.geometry_sha256()


def test_single_island_real_compile_carries_the_declared_identity():
    """One declared island is still an archipelago: its plan states the island.

    A single declared island keeps the ordinary grammar/placement path (the
    island page's local placer is a different drawing); `_build_one_variant`
    stamps that one island on every part and checks it before the gate, so the
    layout does not have to change just because ownership became explicit.
    """
    from boardwise.engines import drawcompiler

    circuit, spec, profiles = _ch340_real_spec(SERIAL_SINGLE_ISLANDS)
    result = drawcompiler.compile(circuit, spec, profiles=profiles)
    assert result.ok and result.candidates, result.render_failures()
    plan = result.best()
    stamped = {part.part_id: (part.group, part.island) for part in plan.parts}
    assert stamped == {
        part_id: ("serial", "serial_core") for part_id in SERIAL_PARTS
    }, result.render_failures()
    _archipelago_module().validate_archipelago_plan(plan, spec)


def test_two_island_real_compile_becomes_a_change_plan():
    """Core plus one satellite compiles to a stamped page, then to a plan.

    This is the successful main path end to end on the real library: the page
    path stamps every part from its block, the partition validates, and
    `module_plan` turns the compiled drawing into three drawable parts.
    """
    from boardwise.engines import drawapply, drawcompiler

    circuit, spec, profiles = _ldo_real_spec(LDO_TWO_ISLANDS)
    result = drawcompiler.compile(circuit, spec, profiles=profiles)
    assert result.ok and result.candidates, result.render_failures()
    plan = result.best()
    _archipelago_module().validate_archipelago_plan(plan, spec)
    change = drawapply.module_plan(
        plan, circuit, spec, profiles,
        lcsc_by_part={"U1": "C6186", "C1": "C15850", "C2": "C000002"},
    )
    assert len(change.change.draw_parts) == 3


def test_island_subgraph_keeps_the_group(circuit, arch_spec):
    """The island's group travels with its subgraph, not only with the block."""
    from boardwise.engines.islandlayout import island_subgraph

    island = arch_spec.islands[0]
    assert island.id == "mcu_core"
    assert island_subgraph(circuit, island).group == "mcu_cluster"


def test_block_plan_stamps_identity():
    """`IslandBlock.plan` states the block's group and island on every part.

    `PackedPage.plan` already stamps, but the block is where the identity comes
    from — a block plan that drops it means every reader of a single island's
    own picture (`svgpreview`, `readability`) sees an anonymous drawing.
    """
    block = _block("mcu_core", "U1", group="mcu_cluster")
    plan = block.plan()
    part = plan.parts[0]
    assert (part.group, part.island) == ("mcu_cluster", "mcu_core")
    entry = plan.to_jsonable()["parts"][0]
    assert (entry["group"], entry["island"]) == ("mcu_cluster", "mcu_core")


def test_packed_page_refuses_to_overwrite_a_parts_identity():
    """A part already stamped differently is a contradiction, not something to fix.

    The packer's stamp is the block's answer; silently replacing a part's stated
    group/island would launder the contradiction into a plan that validates and
    draw the wrong picture (§2.3: never re-stamp a part to make the page pass).
    """
    from boardwise.engines.islandlayout import PackedPage

    block = _block("mcu_core", "U1", group="mcu_cluster")
    block.parts = [LayoutPart(part_id="U1", group="other_group", island="other_island")]
    with pytest.raises(ValueError, match="identity|group|island"):
        PackedPage(blocks=[block]).plan()


def test_compiler_turns_a_stamping_conflict_into_a_rejection(monkeypatch, circuit, arch_spec):
    """A conflict raised while page.plan is built becomes a named compile refusal."""
    from boardwise.engines import drawcompiler, islandlayout

    block = _block("mcu_core", "U1", group="mcu_cluster")
    block.parts = [LayoutPart(part_id="U1", group="other_group", island="other_island")]
    page = islandlayout.PackedPage(blocks=[block])
    monkeypatch.setattr(islandlayout, "island_page", lambda *args, **kwargs: page)
    result = drawcompiler.CompileResult()
    drawcompiler._try_island_variants(
        SimpleNamespace(), result, set(), circuit, arch_spec, {},
        drawcompiler.CompileBudget(), None,
    )
    assert result.candidates == []
    assert result.failures and "identity" in result.render_failures()
    assert result.rejected and "island-page" in result.rejected[0].variant
