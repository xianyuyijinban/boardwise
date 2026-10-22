"""520j：多岛布局的**数据层**（`docs/multi-island-design.md` 的地基）。

这一批只做地基：`islands[]` 读得进、校验得住、跨岛网集合算得出。**不改布局、
不改编译流程、不改 grammar**——所以下面几乎每条测试量的都是"拒绝"和一个
**不变**：

1. **反激 spec 的 `islands` 读得进**（5 个岛、19 件一个不少一个不多、T1 在
   `bridge` 岛）。`modules` 一个字不动——`islands` 是新键，与 `modules`（语法
   绑定的作用域）是两回事（设计文档 §2）。
2. **校验四条各有一条红**：属两岛 / 不属于任何岛 / 岛里有 spec 没有的 part /
   岛 id 重复。四条的共同点：这份文档自己就能判，判不了的要留给持有两份文档的
   那一层（`circuit`/`grammar`），所以这里一条都不越界。
3. **跨岛网集合与手推的对照**：反激 9 条——`HVDC`、`SW`、`PGND`、`COMP`、
   `SEC_SW`、`SEC_12V`、`SEC_GND`、`LED_A`、`LED_K`。期望值在测试里**照网表
   手写一遍**（`_HAND_CROSSINGS`），不从被测函数读回来。
4. **隐式岛 = 安全闸**：不写 `islands` 的 spec（`ch340_serial`、
   `power_entry_xt30`）对外是**一个岛装下全部**，且它们的 spec 摘要与**编译出
   的 plan 摘要与 520j 之前逐字节相同**——三个摘要都在这里钉死，值在改动**之前**
   由 `evidence/520j/probes/probe_baseline.py` 量下（`probe_baseline.before.txt`）。
   这是本批唯一一条"行为完全不变"的硬证据：只加了一个键，凡不写这个键的
   spec，digest 与 plan 都还是原来那一个。

**T1 为什么自成一岛**（`role: "bridge"`，不是塞进正边岛）：变压器与光耦的脚
本来就横跨两族地，塞进任何一岛都会让那个岛的定义失真——"正边岛 = 一次侧地上的
器件"当场不成立；更要紧的是它带的两条网（`HVDC`、`SW`）会**不再是跨岛网**，
「岛间名字接」的触发条件就漏了。把跨岛元素本身声明成一个岛，规则才是干净的：
每个 part 恰属一岛，跨岛网 = 引脚落在 ≥2 岛上的网。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.islands import (
    IMPLICIT_ISLAND_ID,
    ISLAND_ROLES,
    LayoutIsland,
    cross_island_nets,
)
from boardwise.core.presentationspec import PresentationSpec, PresentationSpecError

from gate_skip import skip_if_the_147_gate_refused

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _json_sha(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


#: 改动**之前**（520j 的代码未落）由 `evidence/520j/probes/probe_baseline.py`
#: 量下的两套摘要，见 `evidence/520j/probe_baseline.before.txt`。不写 `islands`
#: 的 spec 必须一模一样——本批加的是键，不是行为。
_BEFORE_520J = {
    "ch340_serial.presentation": (
        "4ab8aee132bce116672ce77a3bacf37516c87b54fd0846e3f09433eaa54f5cce"
    ),
    "ch340_serial.plan.geometry": (
        "977a5b94570d4333387e9b471d56ec8684b2e27d3637184213c1d417f526fc4b"
    ),
    # 530D 重量的一个摘要：ch340 的 plan json 从 637f142e… 变成 e9d20740…。
    # 几何摘要（上面那行）**没变**，变的只有 evidence 里的 occupied_ratio /
    # whitespace_ratio —— 岳 2026-10-21 裁定 A 把导线网名从页面上拿掉之后，
    # `readability` 不再把这些「宿主印的网名行」当文字框（30 个框 → 25 个），
    # 而这两个软指标数的正是框。plan 的**几何**与 spec 摘要仍逐字节相同，
    # 这条测试要证的「本批加的是键、不写这个键的 spec 一律原样」没有被推翻。
    "ch340_serial.plan.json": (
        "e9d207403acfbdfa786b0017c4ef45d5983643b2d1ee1834a0c591c13f199965"
    ),
    "power_entry_xt30.presentation": (
        "e80a85727474ec54dafc3997be45cd0b74133636a38d83299d82557214cfe048"
    ),
    "power_entry_xt30.plan.geometry": (
        "0160195c8a30062c08baae8e267398197f30133d81bb6190320dcf46ac9f0a44"
    ),
    "power_entry_xt30.plan.json": (
        "020979158dffb85df580938770cc667e7355f91db54ee73a6eb5d7ad1c2231f4"
    ),
}


def _spec_payload(*, islands, parts=("R1", "R2")) -> dict:
    """A minimal valid spec, with whatever `islands` the case wants to state."""
    body: dict = {
        "kind": "boardwise-presentation-spec",
        "specVersion": 1,
        "modules": [{"id": "main", "parts": list(parts), "role": "divider"}],
        "grammarRef": "voltage-divider",
    }
    if islands is not None:
        body["islands"] = islands
    return body


# ==================================================== 1. 反激 spec 的 islands


def test_the_flyback_states_five_islands_and_the_transformer_has_one_of_its_own():
    """验收 1：几个岛、各岛几件、T1 落在哪。"""
    spec = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    assert spec.islands is not None, "反激是本批唯一声明了 islands 的 spec"
    assert [(island.id, island.role, len(island.parts)) for island in spec.islands] == [
        ("primary", "primary", 8),
        ("secondary", "secondary", 3),
        ("feedback", "feedback", 4),
        ("bridge", "bridge", 2),
        ("control", "control", 2),
    ]
    # T1（变压器）与 U5（光耦）的脚都横跨两族地，所以都落在 bridge 岛——
    # 这正是「跨岛元素自成一岛」这条裁定的形状。
    assert spec.island_of_part("T1") == "bridge"
    assert spec.island_of_part("U5") == "bridge"
    assert spec.island_of_part("Q1") == "primary"
    assert spec.island_of_part("D3") == "secondary"
    assert spec.island_of_part("U4") == "feedback"
    assert spec.island_of_part("C10") == "control"
    assert {island.role for island in spec.islands} <= set(ISLAND_ROLES)


def test_the_island_partition_covers_the_core_exactly_once():
    """19 件一个不少一个不多：`islands` 与 `modules[*].parts` 是同一套 part。"""
    spec = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    module_parts = spec.declared_part_ids()
    island_parts = [part for island in spec.islands for part in island.parts]
    assert len(module_parts) == 19
    assert sorted(island_parts) == sorted(module_parts)
    # 语法作用域一个 part 都没动：`islands` 是新键，`modules` 还是原来那一组
    assert spec.modules[0].parts == [
        "T1", "Q1", "R3", "R15", "C5", "D1", "R5", "R4", "C6", "D3",
        "C11", "C13", "R7", "R8", "U4", "R9", "U5", "R10", "C10",
    ]


def test_declared_islands_round_trip_and_are_written_only_when_stated():
    """写出来能读回去；没写的 spec 里没有这个键（digest 才可能不变）。"""
    spec = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    written = spec.to_jsonable()
    assert written["islands"] == [
        {"id": "primary", "role": "primary", "parts": ["Q1", "R5", "R4", "C6", "R3", "R15", "C5", "D1"]},
        {"id": "secondary", "role": "secondary", "parts": ["D3", "C11", "C13"]},
        {"id": "feedback", "role": "feedback", "parts": ["R7", "R8", "U4", "R9"]},
        {"id": "bridge", "role": "bridge", "parts": ["T1", "U5"]},
        {"id": "control", "role": "control", "parts": ["R10", "C10"]},
    ]
    assert PresentationSpec.from_dict(written) == spec
    assert "islands" not in PresentationSpec.from_dict(_spec_payload(islands=None)).to_jsonable()
    # 没有 role 的岛写出时不带 role 键，读回是 ""
    bare = PresentationSpec.from_dict(
        _spec_payload(islands=[{"id": "a", "parts": ["R1", "R2"]}])
    )
    assert bare.to_jsonable()["islands"] == [
        {"id": "a", "parts": ["R1", "R2"]},
    ]
    assert PresentationSpec.from_dict(bare.to_jsonable()) == bare


def test_declaring_islands_changes_the_digest_and_declaring_none_does_not():
    """一个键的两种后果，各钉一条：声明了要进摘要，不声明就不进。"""
    plain = PresentationSpec.from_dict(_spec_payload(islands=None))
    declared = PresentationSpec.from_dict(
        _spec_payload(islands=[{"id": "a", "parts": ["R1", "R2"]}])
    )
    assert declared.sha256() != plain.sha256()
    assert plain.sha256() == PresentationSpec.from_dict(
        _spec_payload(islands=None)
    ).sha256()


# ============================================================ 2. 校验四条红


def test_a_part_in_two_islands_is_refused():
    with pytest.raises(PresentationSpecError, match="exactly one block"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1"]},
            {"id": "b", "parts": ["R1", "R2"]},
        ]))


def test_a_part_in_no_island_is_refused():
    with pytest.raises(PresentationSpecError, match="are in no island"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1"]},
        ]))


def test_an_island_naming_a_part_the_spec_does_not_have_is_refused():
    with pytest.raises(PresentationSpecError, match=r"islands\[0\]\.parts\[2\] is 'R9'"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1", "R2", "R9"]},
        ]))


def test_two_islands_with_one_id_are_refused():
    with pytest.raises(PresentationSpecError, match="already used"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1"]},
            {"id": "a", "parts": ["R2"]},
        ]))


def test_the_shapes_that_are_not_an_island_list_are_refused():
    """`[]` / 不是列表 / 空 parts / 未知 role / 未知键 / 坐标键，各一条拒绝。"""
    with pytest.raises(PresentationSpecError, match="islands is empty"):
        PresentationSpec.from_dict(_spec_payload(islands=[]))
    with pytest.raises(PresentationSpecError, match="must be a JSON list"):
        PresentationSpec.from_dict(_spec_payload(islands={"id": "a"}))
    with pytest.raises(PresentationSpecError, match=r"islands\[0\]\.parts is empty"):
        PresentationSpec.from_dict(_spec_payload(islands=[{"id": "a", "parts": []}]))
    with pytest.raises(PresentationSpecError, match=r"islands\[0\]\.role is 'core'"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1", "R2"], "role": "core"},
        ]))
    with pytest.raises(PresentationSpecError, match="unknown key"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1", "R2"], "note": "not a key of an island"},
        ]))
    # 隐式岛的 id 是"什么都不说"的名字，写下来是把默认值当决定，所以拒绝
    with pytest.raises(PresentationSpecError, match="implicit island"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": IMPLICIT_ISLAND_ID, "parts": ["R1", "R2"]},
        ]))
    # 坐标闸盖到新键上：岛屿里出现坐标键照样在解析前被拒（052 §4）
    with pytest.raises(PresentationSpecError, match="coordinate"):
        PresentationSpec.from_dict(_spec_payload(islands=[
            {"id": "a", "parts": ["R1", "R2"], "x": 10},
        ]))


# ======================================================== 3. 跨岛网集合


#: 照反激网表**手推**一遍：网 -> 它的脚落在哪些岛上（岛名来自 spec 的 islands，
#: 但这一列是人按 110 plan 的 M3~M7 分法推的，不是从被测函数读回来的）。
_HAND_CROSSINGS: dict[str, set[str]] = {
    "HVDC": {"primary", "bridge"},           # C5 R15 在正边，T1 在桥
    "SW": {"primary", "bridge"},             # D1 Q1 在正边，T1 在桥
    "PGND": {"primary", "control", "bridge"},  # C6 R5 正边，C10 R10 控制器，U5 桥
    "COMP": {"control", "bridge"},           # C10 控制器，U5 桥
    "SEC_SW": {"secondary", "bridge"},       # D3 副边，T1 桥
    "SEC_12V": {"secondary", "feedback"},    # D3 C11 C13 副边，R7 R9 反馈
    "SEC_GND": {"secondary", "feedback", "bridge"},  # C11 C13 / R8 U4 / T1
    "LED_A": {"feedback", "bridge"},         # R9 反馈，U5 桥
    "LED_K": {"feedback", "bridge"},         # U4 反馈，U5 桥
}

#: 全在一岛内的网（一条都不该进跨岛集合）——这是反向的那一半。
_HAND_INTRA: dict[str, str] = {
    "CLAMP": "primary", "CLAMP_B": "primary", "SRC": "primary",
    "CS_FILT": "primary", "GATE": "primary",
    "VFB_NF": "control",
    "FB_SENSE": "feedback",
}


def test_the_cross_island_nets_are_the_nine_the_netlist_says():
    """验收 3：算出来的 9 条 = 手推的 9 条，且 HVDC/SEC_12V/SEC_GND/PGND 都在。"""
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    spec = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    computed = cross_island_nets(circuit, spec.islands)
    assert set(computed) == set(_HAND_CROSSINGS), computed
    assert len(computed) == 9
    assert computed == [net.id for net in circuit.nets
                        if net.id in _HAND_CROSSINGS], "顺序是网表自己的顺序"
    assert {"HVDC", "SEC_12V", "SEC_GND", "PGND"} <= set(computed)
    assert not (set(computed) & set(_HAND_INTRA))
    # 两边逐网对：函数算出来的岛集合，与手写的那一格逐字相同
    for net_id, islands in _HAND_CROSSINGS.items():
        reached = {spec.island_of_part(member.partition(".")[0])
                   for member in circuit.net(net_id).members}
        assert reached == islands, net_id
    for net_id, island_id in _HAND_INTRA.items():
        reached = {spec.island_of_part(member.partition(".")[0])
                   for member in circuit.net(net_id).members}
        assert reached == {island_id}, net_id


def test_an_implicit_island_has_no_crossing_nets_at_all():
    """隐式岛只有一个，任何网都不可能跨两个岛——多岛布局的触发器是哑的。"""
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    spec = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    one = [LayoutIsland(id=IMPLICIT_ISLAND_ID, parts=spec.declared_part_ids())]
    assert cross_island_nets(circuit, one) == []


def test_a_net_reaches_exactly_the_islands_that_own_its_pins():
    """两个岛、每岛一件：只有同时被两岛认领的网才跨岛，其余不参与。

    这是 `cross_island_nets` 的判定口径本身——按**脚所属的 part 落在哪个岛**判，
    不是按网名、不是按数量、也不是按岛有没有 part。
    """
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    partial = [LayoutIsland(id="a", parts=["Q1"]), LayoutIsland(id="b", parts=["D1"])]
    # SW 的脚在 D1/Q1/T1 上 -> 够到 a 与 b -> 跨岛；HVDC 的脚一个都没被认领 -> 不算
    assert cross_island_nets(circuit, partial) == ["SW"]
    # 只认领 Q1 时，没有任何一条网够得到两个岛
    assert cross_island_nets(circuit, [LayoutIsland(id="a", parts=["Q1"])]) == []


# ======================================================== 4. 隐式岛的安全闸


def test_a_spec_that_states_no_islands_is_one_island_holding_everything():
    """验收 4 的形状那一半：不写 islands -> 一个岛装下全部（下游不判 None）。"""
    for stem in ("ch340_serial", "power_entry_xt30"):
        spec = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        assert spec.islands is None, stem
        effective = spec.effective_islands()
        assert len(effective) == 1
        assert effective[0].id == IMPLICIT_ISLAND_ID
        assert effective[0].role == ""
        assert effective[0].parts == spec.declared_part_ids()
        assert "islands" not in spec.to_jsonable()
        # 每个 part 都问得到岛，且都是那一个
        for part_id in spec.declared_part_ids():
            assert spec.island_of_part(part_id) == IMPLICIT_ISLAND_ID


def test_the_two_shipping_specs_hash_and_compile_to_what_they_did_before_520j():
    """验收 4 的硬那一半：摘要 + **编译出的 plan** 与 520j 之前逐字节相同。

    三个摘要（spec / plan geometry / plan json）都是改动前量的
    （`evidence/520j/probe_baseline.before.txt`）。plan json 里也带着
    `source.presentationSha256`，所以它证明的不只是几何没动，而是这份 spec 的
    摘要也没动——本批加的是键，凡不写这个键的 spec 一律原样。
    """
    import boardwise.engines.drawcompiler as dc
    from boardwise.engines.drawapply import load_library

    for stem, plan_sha_key, json_sha_key in (
        ("ch340_serial", "ch340_serial.plan.geometry", "ch340_serial.plan.json"),
        ("power_entry_xt30", "power_entry_xt30.plan.geometry",
         "power_entry_xt30.plan.json"),
    ):
        spec = PresentationSpec.load(SPECS / f"{stem}.presentation.json")
        assert spec.sha256() == _BEFORE_520J[f"{stem}.presentation"], stem
        circuit = CircuitSpec.load(SPECS / f"{stem}.circuit.json")
        result = dc.compile(
            circuit, spec, load_library(SPECS / f"{stem}.library.json"),
            dc.CompileBudget(page_box=(0.0, 0.0, 1170.0, 825.0)),
        )
        skip_if_the_147_gate_refused(result, f"520j, the {stem} shipping spec")
        assert result.ok and result.candidates, result.render_failures()
        plan = result.candidates[0]
        assert plan.geometry_sha256() == _BEFORE_520J[plan_sha_key], stem
        assert _json_sha(plan.to_jsonable()) == _BEFORE_520J[json_sha_key], stem
        assert plan.source.presentation_sha256 == _BEFORE_520J[f"{stem}.presentation"]
