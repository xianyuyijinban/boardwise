"""C：``crossView.autoNetAliases`` —— 自动网的**候选**别名（2026-10-30）。

用户实报的形状：设计自己的网表叫 ``NET34``，同一脚在 PCB/编辑器网表里叫
``$1N436``。两侧都是编辑器生成的自动名，谁都不说明这个网**是什么**，所以本棒
只在**脚集合完全相等**且两侧名不同时记一条候选，别的什么都不做：

* ``{schematicNet, pcbNet, members, status: "candidate", evidence}``，``members``
  是两侧共有的去重 ``REF.pin`` 列表，``evidence.basis = "same-pin-members"`；
* **全等**，不是子集/超集：少一脚就不是同一组脚；
* 桶必须**一一对应**：任一侧有两个自动网落在同一脚集合里，整桶不出别名；
* 显式命名的网不参与（名字带意图，两个不同的名字不是这个问题）；
* 只在 ``checked: true`` 且真有别名时加这个键；无别名不加空数组，
  ``candidateMappings`` / ``status`` / 全部 ``checked: false`` 形状逐字不变。

边界（本文件同时钉住）：不实现编辑器内部派生名（``$1N{序号}`` 的编号稀疏且会
变，归档原理图里没有派生规则），真实 ``$1N436`` 只有用户 oracle 一句话、**不是
这里的实测读数**，所以下面全部是**合成**模型（匿名位号 ``U9``/``R9``），不碰任何
真实工程；别名也不改写 ``Net.name`` 或任何规则消息。
"""

from __future__ import annotations

import copy
import json
from typing import Any

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import (
    CROSS_VIEW_ALIAS_EVIDENCE,
    cross_view_section,
)
from boardwise.engines.reviewread import review_read_section

#: 一条别名的键与顺序（契约逐字）。
ALIAS_KEYS = ["schematicNet", "pcbNet", "members", "status", "evidence"]

#: 537C 的映射形状：本棒不得改动它。
MAPPING_KEYS = ["pcbPin", "pcbNet", "pcbMembers", "schematicCandidates", "evidence"]

#: 537C 的同名映射证据：本棒不得改动它。
MAPPING_EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "archiveSchematic",
    "basis": "same-net-name",
}


def _model(
    parts: dict[str, list[str]],
    nets: dict[str, list[tuple[str, str]]] | None = None,
) -> DesignModel:
    """A ``DesignModel``: pin numbers per designator, then ``name -> members``."""
    model = DesignModel()
    for designator, numbers in parts.items():
        model.components[designator] = Component(
            uid=f"uid-{designator}",
            designator=designator,
            pins=[Pin(number=number, name=f"n{number}") for number in numbers],
        )
    for name, members in (nets or {}).items():
        model.nets[name] = Net(name=name, pins=list(members))
    return model


_RAIL = [("U9", "1"), ("U9", "2"), ("R9", "1")]


def _pair(
    schematic_nets: dict[str, list[tuple[str, str]]],
    pcb_nets: dict[str, list[tuple[str, str]]],
) -> tuple[DesignModel, DesignModel]:
    """Two views over the same anonymous parts, each with its own nets."""
    parts = {"U9": ["1", "2", "3"], "R9": ["1", "2"]}
    return _model(parts, schematic_nets), _model(parts, pcb_nets)


# --------------------------------------------------------------------------
# 1. 全等脚集合 → candidate
# --------------------------------------------------------------------------


def test_equal_pin_sets_across_auto_names_yield_candidate():
    """``NET34``（原理图）与 ``$1N436``（PCB）脚集合全等 → 一条候选别名。

    这对名字是**用户实报**的形状，不是本文件的实测读数；这里用合成模型复现
    形状本身，不声称从任何真实归档里读到了 436。
    """
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": list(_RAIL)})
    section = cross_view_section(schematic, pcb)

    assert section["checked"] is True
    assert list(section["autoNetAliases"][0]) == ALIAS_KEYS
    assert section["autoNetAliases"] == [{
        "schematicNet": "NET34",
        "pcbNet": "$1N436",
        "members": ["R9.1", "U9.1", "U9.2"],
        "status": "candidate",
        "evidence": {
            "pcb": "archivePcb",
            "schematic": "archiveSchematic",
            "basis": "same-pin-members",
            "note": "候选别名：同一脚集合，不是确认同一网",
        },
    }]


def test_evidence_says_candidate_not_confirmed():
    """``status`` 与 ``evidence`` 两处都写候选，且不出现任何 confirmed 字眼。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": list(_RAIL)})
    alias = cross_view_section(schematic, pcb)["autoNetAliases"][0]

    assert alias["status"] == "candidate"
    assert alias["evidence"] == CROSS_VIEW_ALIAS_EVIDENCE
    assert alias["evidence"]["basis"] == "same-pin-members"
    assert "确认" in alias["evidence"]["note"]
    blob = json.dumps(alias, ensure_ascii=False)
    assert "confirmed" not in blob


def test_member_refs_are_deduplicated_and_pin_sorted():
    """同一脚记两遍仍算同一个脚集合；``members`` 去重后按脚号读数排序。"""
    schematic, pcb = _pair(
        {"NET34": [("U9", "10"), ("U9", "2"), ("U9", "2")]},
        {"$1N436": [("U9", "2"), ("U9", "10"), ("U9", "10")]},
    )
    alias = cross_view_section(schematic, pcb)["autoNetAliases"][0]
    assert alias["members"] == ["U9.2", "U9.10"]


# --------------------------------------------------------------------------
# 2. 不该出别名的那几条
# --------------------------------------------------------------------------


def test_empty_net_sets_do_not_alias():
    """两侧都是空脚集合：都不说明什么，不是别名。"""
    schematic, pcb = _pair({"NET34": []}, {"$1N436": []})
    section = cross_view_section(schematic, pcb)
    assert "autoNetAliases" not in section


def test_subset_is_not_an_alias():
    """少一脚就是另一组脚：子集不算全等。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": _RAIL[:2]})
    assert "autoNetAliases" not in cross_view_section(schematic, pcb)


def test_superset_is_not_an_alias():
    """多一脚也不是全等。"""
    schematic, pcb = _pair({"NET34": _RAIL[:2]}, {"$1N436": list(_RAIL)})
    assert "autoNetAliases" not in cross_view_section(schematic, pcb)


def test_duplicate_bucket_on_schematic_side_withholds_whole_bucket():
    """原理图有两个自动网落在同一脚集合：整桶不出别名，不许挑一个。"""
    schematic, pcb = _pair(
        {"NET34": list(_RAIL), "NET35": list(_RAIL)},
        {"$1N436": list(_RAIL)},
    )
    assert "autoNetAliases" not in cross_view_section(schematic, pcb)


def test_duplicate_bucket_on_pcb_side_withholds_whole_bucket():
    """PCB 侧同理：两个自动网同一脚集合，整桶作废。"""
    schematic, pcb = _pair(
        {"NET34": list(_RAIL)},
        {"$1N436": list(_RAIL), "$1N437": list(_RAIL)},
    )
    assert "autoNetAliases" not in cross_view_section(schematic, pcb)


def test_a_second_net_does_not_collide_with_its_own_bucket():
    """另一对全等（但脚不同）照旧出别名——歧义只废自己那一桶。"""
    schematic, pcb = _pair(
        {"NET34": list(_RAIL), "NET36": [("R9", "2")], "NET37": [("R9", "2")]},
        {"$1N436": list(_RAIL)},
    )
    # NET36/NET37 是原理图侧的重复桶，PCB 侧根本没有对应脚集合：两条都不出，
    # NET34 那一桶不受牵连。
    assert [a["schematicNet"] for a in cross_view_section(schematic, pcb)["autoNetAliases"]] == [
        "NET34"
    ]


def test_explicit_names_are_not_aliased():
    """显式命名的网不参与：名字带意图，两个不同的名字不是这个问题。"""
    schematic, pcb = _pair({"ALPHA": list(_RAIL)}, {"$1N436": list(_RAIL)})
    assert "autoNetAliases" not in cross_view_section(schematic, pcb)


def test_same_name_is_not_an_alias():
    """同名网是同名候选（537C 的 ``same-net-name``），不是别名。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"NET34": list(_RAIL)})
    section = cross_view_section(schematic, pcb)
    assert "autoNetAliases" not in section


def test_unchecked_sections_never_carry_the_key():
    """未配对 / 无网表读数：``checked: false`` 的字典逐字不变，不加别名键。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": list(_RAIL)})
    for section in (
        cross_view_section(None, pcb),
        cross_view_section(schematic, None),
    ):
        assert section["checked"] is False
        assert list(section) == ["checked", "reason"]
        assert "autoNetAliases" not in section


# --------------------------------------------------------------------------
# 3. 旧读数不变：candidateMappings / status / 行形状
# --------------------------------------------------------------------------


def _suspected_pair() -> tuple[DesignModel, DesignModel]:
    """537C 的原始形状：U9.1 在原理图里孤零零，PCB 的 ALPHA 有伴。"""
    schematic = _model(
        {"U9": ["1", "2", "3", "4"], "R9": ["1", "2"]},
        {
            "NET7": [("U9", "1")],
            "ALPHA": [("R9", "1"), ("U9", "3")],
            "BETA": [("U9", "2"), ("R9", "2")],
        },
    )
    pcb = _model(
        {"U9": ["1", "2", "3", "4"], "R9": ["1", "2"]},
        {
            "ALPHA": [("R9", "1"), ("U9", "1"), ("U9", "3")],
            "BETA": [("U9", "2"), ("R9", "2")],
        },
    )
    return schematic, pcb


def test_candidate_mappings_and_status_unchanged_when_no_alias():
    """没有自动网别名时，537C 那一半逐字段不变，也不冒空数组。"""
    schematic, pcb = _suspected_pair()
    section = cross_view_section(schematic, pcb)

    assert list(section) == [
        "checked", "minPins", "lonely", "status", "candidateMappings",
    ]
    assert section["status"] == "suspected"
    assert list(section["candidateMappings"][0]) == MAPPING_KEYS
    assert section["candidateMappings"][0]["evidence"] == MAPPING_EVIDENCE


def test_alias_is_additive_beside_existing_mappings():
    """有别名时只多一个键；lonely 行与映射一字不动。"""
    schematic, pcb = _suspected_pair()
    schematic.nets["NET34"] = Net(name="NET34", pins=[("U9", "4")])
    pcb.nets["$1N436"] = Net(name="$1N436", pins=[("U9", "4")])
    plain = cross_view_section(*_suspected_pair())
    section = cross_view_section(schematic, pcb)

    assert list(section) == list(plain) + ["autoNetAliases"]
    assert section["lonely"] == plain["lonely"]
    assert section["candidateMappings"] == plain["candidateMappings"]
    assert section["status"] == plain["status"]
    assert [a["schematicNet"] for a in section["autoNetAliases"]] == ["NET34"]


def test_agreed_views_keep_the_bare_shape():
    """两视图一致（lonely 空）：仍是 ``{checked, minPins, lonely}``。"""
    parts = {"U9": ["1", "2"], "R9": ["1", "2"]}
    nets = {"ALPHA": [("U9", "1"), ("R9", "1")]}
    section = cross_view_section(_model(parts, nets), _model(parts, nets))
    assert list(section) == ["checked", "minPins", "lonely"]
    assert section["lonely"] == []


def test_net_names_are_not_rewritten():
    """别名是披露，不是改名：两侧 ``Net.name`` 与键名调用前后逐字不变。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": list(_RAIL)})
    before = (copy.deepcopy(sorted(schematic.nets)), copy.deepcopy(sorted(pcb.nets)))
    cross_view_section(schematic, pcb)
    after = (sorted(schematic.nets), sorted(pcb.nets))
    assert after == before
    assert schematic.nets["NET34"].name == "NET34"
    assert pcb.nets["$1N436"].name == "$1N436"


# --------------------------------------------------------------------------
# 4. review-read 原样读到双名与成员
# --------------------------------------------------------------------------


def test_review_read_returns_names_and_members_verbatim():
    """``review-read crossView`` 原样读出双名与成员，不翻译、不改写。"""
    schematic, pcb = _pair({"NET34": list(_RAIL)}, {"$1N436": list(_RAIL)})
    cross_view = cross_view_section(schematic, pcb)
    report: dict[str, Any] = {
        "pcb_review": {"boards": [{"title": "SYNTH-B1", "crossView": cross_view}]},
    }
    payload = review_read_section(report, "crossView")
    boards = payload["boards"]

    assert boards[0]["crossView"] == cross_view
    alias = boards[0]["crossView"]["autoNetAliases"][0]
    assert (alias["schematicNet"], alias["pcbNet"]) == ("NET34", "$1N436")
    assert alias["members"] == ["R9.1", "U9.1", "U9.2"]
