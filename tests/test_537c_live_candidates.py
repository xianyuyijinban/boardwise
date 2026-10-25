"""537C3b3：用**实时**同名网的真实成员为 crossView 候选补引脚名。

537C1 的候选（``schematicCandidates``）是**归档**读数：``checkup --file`` 同时读
导出的原理图与 PCB，按网名逐字相等取成员。537C3b3 要补的是另一半：编辑器的实时
网表里，**同名 pcbNet** 的真实成员是谁、每个成员在实时元件上叫什么引脚名。

原会话的实测事实是这个模块存在的理由：归档 mapping 的 ``pcbPin`` 是 ``U9.11``，
而实时同名网 ``FOC_EN`` 的实际成员是 ``U9.33``（引脚名 ``PB11``）。**pin number
会不同**，所以给旧 ``schematicCandidates`` 里那些归档 ref 贴实时引脚名是错的：
名字属于另一个物理脚。正确做法是用实时网表为这条网**重新生成**候选成员
（``liveSchematicCandidates``），并把归档候选原样留着，两侧出处分开。

本模块还钉住三件事：

* 没有证据绑定（netlist artifact 缺 ``file`` / ``sha256``）就不生成候选——
  宁可 ``ValueError``，也不产出无出处的「实时候选」；
* 实时同名网不在 / 空 → ``status='missing'``；实时网含重复位号或成员脚在当前
  网表里精确解析不出 → ``status='unavailable'``，且**不给部分确定的列表**；
* 身份未核实（``identity_verified=False``）只做剥离：旧 live 字段一个不留，
  归档的 ``checked`` / ``status`` / ``lonely`` / ``schematicCandidates`` /
  ``evidence`` 全保，也不需要 live model。

``crossView.status`` 永远是 ``suspected``：实时网表成功也只证明「实时侧有这些
成员」，不证明归档差异是哪一侧的问题；本模块不写 ``confirmed``。

全部合成数据匿名（``U9`` / ``R11`` / ``FOC_EN``），不涉及任何真实工程。
"""

from __future__ import annotations

import copy
import json

import pytest

from boardwise.core.candidate import candidate_from_netlist
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import (
    cross_view_section,
    enrich_cross_view_live_candidates,
)

#: 537C1 的映射形状 + 537C3b3 在**归档 evidence 之后**追加的两个键。
ARCHIVE_MAPPING_KEYS = [
    "pcbPin", "pcbNet", "pcbMembers", "schematicCandidates", "evidence",
]
LIVE_MAPPING_KEYS = ARCHIVE_MAPPING_KEYS + [
    "liveSchematicCandidates", "liveCandidateEvidence",
]

#: 归档侧 evidence：与 537C1 逐字一致，不因本棒改动。
ARCHIVE_EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "archiveSchematic",
    "basis": "same-net-name",
}

#: 实时侧 evidence 的固定四段（``netlist`` 由调用方传入，逐次深拷贝）。
LIVE_EVIDENCE_FIXED = {
    "pcb": "archivePcb",
    "schematic": "liveSchematic",
    "basis": "same-net-name",
}

#: 一份合法的实时网表 evidence 绑定。
ARTIFACT = {
    "file": "live-netlist-Schematic1-a1b2c3d4.txt",
    "sha256": "a" * 64,
    "netlistType": "EasyEDA",
}


# --------------------------------------------------------------------------
# anonymous synthesised inputs
# --------------------------------------------------------------------------


def _live(
    parts: dict[str, dict[str, str]],
    nets: dict[str, list[tuple[str, str]]],
    *,
    duplicates: tuple[str, ...] = (),
) -> DesignModel:
    """A live-side model: ``designator -> {pin number: pin name}``, then nets."""
    model = DesignModel()
    for designator, pins in parts.items():
        model.components[designator] = Component(
            uid=f"uid-{designator}",
            designator=designator,
            pins=[Pin(number=number, name=name) for number, name in pins.items()],
        )
    for name, members in nets.items():
        model.nets[name] = Net(name=name, pins=list(members))
    model.duplicate_designators.extend(duplicates)
    return model


def _mapping(
    *,
    pcb_pin: str = "U9.11",
    pcb_net: str = "FOC_EN",
    pcb_members: tuple[str, ...] = ("R11.1", "U9.11"),
    candidates: tuple[str, ...] = ("R11.1", "U9.11"),
) -> dict:
    return {
        "pcbPin": pcb_pin,
        "pcbNet": pcb_net,
        "pcbMembers": list(pcb_members),
        "schematicCandidates": list(candidates),
        "evidence": dict(ARCHIVE_EVIDENCE),
    }


def _section(*mappings: dict, status: bool = True) -> dict:
    section: dict = {
        "checked": True,
        "minPins": 3,
        "lonely": [
            {
                "designator": mapping["pcbPin"].split(".")[0],
                "pin": mapping["pcbPin"].split(".")[1],
                "schematicNet": "NET7",
                "schematicMembers": 1,
                "pcbNet": mapping["pcbNet"],
                "pcbMembers": len(mapping["pcbMembers"]),
            }
            for mapping in mappings
        ],
        "candidateMappings": [dict(mapping) for mapping in mappings],
    }
    if status:
        section["status"] = "suspected"
    return section


def _enrich(cross_view: dict, model: object = None, *, verified: bool = True) -> dict:
    return enrich_cross_view_live_candidates(
        cross_view,
        model,
        netlist_artifact=ARTIFACT,
        identity_verified=verified,
    )


class _Exploding:
    """A live model that must not even be peeked at."""

    @property
    def nets(self):
        raise AssertionError("identity 未核实时不该读 live model")

    @property
    def components(self):
        raise AssertionError("identity 未核实时不该读 live model")

    def repeated_designators(self):
        raise AssertionError("identity 未核实时不该读 live model")


# --------------------------------------------------------------------------
# 0. the archive side has a different pin: the live net is the source
# --------------------------------------------------------------------------


def test_live_members_beat_the_archive_pin_number():
    """归档 mapping 说 ``U9.11``，实时同名网的真实成员是 ``U9.33`` / ``PB11``."""
    live = _live(
        {"U9": {"11": "PA1", "33": "PB11"}, "R11": {"1": "", "2": ""}},
        {"FOC_EN": [("U9", "33"), ("R11", "1")]},
    )
    archive = _section(_mapping())
    out = _enrich(copy.deepcopy(archive), live)

    mapping = out["candidateMappings"][0]
    assert mapping["liveSchematicCandidates"] == [
        {"pin": "R11.1", "pinName": ""},
        {"pin": "U9.33", "pinName": "PB11"},
    ]
    assert all(
        candidate["pin"] != "U9.11" for candidate in mapping["liveSchematicCandidates"]
    ), "旧归档 ref 不得被贴实时引脚名：名字属于另一个物理脚"
    # the archive reading is still there, untouched
    assert mapping["pcbPin"] == "U9.11"
    assert mapping["pcbNet"] == "FOC_EN"
    assert mapping["schematicCandidates"] == ["R11.1", "U9.11"]
    assert mapping["evidence"] == ARCHIVE_EVIDENCE


def test_the_live_field_names_are_exactly_the_contract():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]
    assert list(mapping) == LIVE_MAPPING_KEYS
    for candidate in mapping["liveSchematicCandidates"]:
        assert list(candidate) == ["pin", "pinName"]


def test_live_evidence_names_both_sides_and_binds_the_netlist():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]
    evidence = mapping["liveCandidateEvidence"]

    assert evidence["status"] == "ok"
    assert {key: evidence[key] for key in LIVE_EVIDENCE_FIXED} == LIVE_EVIDENCE_FIXED
    assert evidence["schematic"] == "liveSchematic"
    assert evidence["netlist"] == ARTIFACT


@pytest.mark.parametrize(
    ("pcb_net", "pin", "pin_name"),
    [
        ("FOC_EN", "33", "PB11"),
        ("NSLEEP", "35", "PB13"),
        ("NRESET", "36", "PB14"),
        ("VBUS", "37", "PB15"),
    ],
    ids=["foc-en", "nsleep", "nreset", "vbus"],
)
def test_each_live_net_role_maps_to_its_own_pin_and_name(pcb_net, pin, pin_name):
    """同名网、实时 pin number、pinName 三者一一对应，不从归档抄。"""
    live = _live(
        {"U9": {"11": "PA1", pin: pin_name, "40": "PC0"}},
        {name: [("U9", number)]
         for name, number in [("FOC_EN", "33"), ("NSLEEP", "35"),
                              ("NRESET", "36"), ("VBUS", "37")]},
    )
    mapping = _section(_mapping(pcb_net=pcb_net))["candidateMappings"][0]
    out = _enrich(_section(mapping), live)["candidateMappings"][0]

    assert out["liveSchematicCandidates"] == [{"pin": f"U9.{pin}", "pinName": pin_name}]
    assert out["liveCandidateEvidence"]["status"] == "ok"


# --------------------------------------------------------------------------
# 1. ordering, dedup, and only the named net
# --------------------------------------------------------------------------


def test_live_members_are_deduped_and_sorted_like_a_person_reads():
    live = _live(
        {"U9": {"1": "PA0", "2": "PA1", "9": "PA8", "10": "PA9"},
         "R9": {"2": ""}},
        {"FOC_EN": [("U9", "10"), ("U9", "9"), ("U9", "9"), ("R9", "2"), ("U9", "2")]},
    )
    candidates = _enrich(_section(_mapping()), live)["candidateMappings"][0][
        "liveSchematicCandidates"
    ]
    assert [c["pin"] for c in candidates] == ["R9.2", "U9.2", "U9.9", "U9.10"]


def test_candidates_come_only_from_the_named_live_net():
    live = _live(
        {"U9": {"1": "PA0", "33": "PB11"}, "R9": {"1": ""}},
        {"FOC_EN": [("U9", "33")], "OTHER": [("U9", "1"), ("R9", "1")]},
    )
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]
    assert mapping["liveSchematicCandidates"] == [{"pin": "U9.33", "pinName": "PB11"}]


# --------------------------------------------------------------------------
# 2. missing / empty live net: a stated absence, never a fallback
# --------------------------------------------------------------------------


def test_a_missing_live_net_is_missing_not_a_guess():
    live = _live({"U9": {"33": "PB11"}}, {"OTHER": [("U9", "33")]})
    mapping = _enrich(_section(_mapping(pcb_net="FOC_EN")), live)["candidateMappings"][0]

    assert mapping["liveSchematicCandidates"] == []
    evidence = mapping["liveCandidateEvidence"]
    assert evidence["status"] == "missing"
    assert "FOC_EN" in evidence["reason"]
    assert evidence["netlist"] == ARTIFACT
    # neither archive candidates nor PCB members are promoted into live candidates
    assert mapping["schematicCandidates"] == ["R11.1", "U9.11"]


def test_an_empty_live_net_is_missing_too():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": []})
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]

    assert mapping["liveSchematicCandidates"] == []
    assert mapping["liveCandidateEvidence"]["status"] == "missing"
    assert "FOC_EN" in mapping["liveCandidateEvidence"]["reason"]


def test_missing_and_ok_mappings_live_side_by_side():
    live = _live(
        {"U9": {"33": "PB11", "35": "PB13"}},
        {"FOC_EN": [("U9", "33")]},
    )
    out = _enrich(
        _section(_mapping(pcb_net="FOC_EN"), _mapping(pcb_pin="U9.35", pcb_net="NSLEEP")),
        live,
    )
    statuses = [m["liveCandidateEvidence"]["status"] for m in out["candidateMappings"]]
    assert statuses == ["ok", "missing"]


# --------------------------------------------------------------------------
# 3. ambiguity: repeated designators / unresolvable pins — no partial list
# --------------------------------------------------------------------------


def test_a_repeated_designator_makes_the_mapping_unavailable():
    live = _live(
        {"U9": {"33": "PB11"}, "R9": {"1": ""}},
        {"FOC_EN": [("U9", "33"), ("R9", "1")]},
        duplicates=("U9",),
    )
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]

    assert mapping["liveSchematicCandidates"] == [], "重复位号不得给部分确定的列表"
    evidence = mapping["liveCandidateEvidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["ambiguousDesignators"] == ["U9"]


def test_a_repeated_name_off_this_net_does_not_poison_another_mapping():
    live = _live(
        {"U9": {"33": "PB11", "35": "PB13"}, "R9": {"1": ""}},
        {"FOC_EN": [("U9", "33")], "NRESET": [("R9", "1")]},
        duplicates=("R9",),
    )
    out = _enrich(
        _section(_mapping(pcb_net="FOC_EN"), _mapping(pcb_pin="U9.35", pcb_net="NRESET")),
        live,
    )
    first, second = out["candidateMappings"]
    assert first["liveCandidateEvidence"]["status"] == "ok"
    assert first["liveSchematicCandidates"] == [{"pin": "U9.33", "pinName": "PB11"}]
    assert second["liveCandidateEvidence"]["status"] == "unavailable"
    assert second["liveCandidateEvidence"]["ambiguousDesignators"] == ["R9"]
    assert second["liveSchematicCandidates"] == []


def test_an_unresolvable_member_pin_is_unavailable():
    live = _live({"U9": {"1": "PA0"}}, {"FOC_EN": [("U9", "33")]})
    mapping = _enrich(_section(_mapping()), live)["candidateMappings"][0]

    assert mapping["liveSchematicCandidates"] == []
    evidence = mapping["liveCandidateEvidence"]
    assert evidence["status"] == "unavailable"
    assert evidence["unresolvedPins"] == ["U9.33"]


def test_an_unknown_designator_is_unresolved_not_dropped():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33"), ("R7", "1")]})
    evidence = _enrich(_section(_mapping()), live)["candidateMappings"][0][
        "liveCandidateEvidence"
    ]
    assert evidence["status"] == "unavailable"
    assert evidence["unresolvedPins"] == ["R7.1"]


def test_ambiguous_and_unresolved_are_both_reported_when_both_apply():
    live = _live(
        {"U9": {"33": "PB11"}},
        {"FOC_EN": [("U9", "33"), ("R7", "1")]},
        duplicates=("U9",),
    )
    evidence = _enrich(_section(_mapping()), live)["candidateMappings"][0][
        "liveCandidateEvidence"
    ]
    assert evidence["status"] == "unavailable"
    assert evidence["ambiguousDesignators"] == ["U9"]
    assert evidence["unresolvedPins"] == ["R7.1"]


def test_a_repeated_name_is_ambiguous_even_when_its_pin_does_not_resolve():
    """Ambiguity belongs to the name being on the net, not to the pin reading."""
    live = _live(
        {"U9": {"1": "PA0"}},
        {"FOC_EN": [("U9", "33")]},
        duplicates=("U9",),
    )
    evidence = _enrich(_section(_mapping()), live)["candidateMappings"][0][
        "liveCandidateEvidence"
    ]
    assert evidence["status"] == "unavailable"
    assert evidence["ambiguousDesignators"] == ["U9"]
    assert evidence["unresolvedPins"] == ["U9.33"]


# --------------------------------------------------------------------------
# 4. identity not verified: strip the live half, keep every archive byte
# --------------------------------------------------------------------------


def test_unverified_identity_strips_old_live_fields_without_a_model():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    archive = _section(_mapping())
    verified = _enrich(copy.deepcopy(archive), live)
    assert verified["candidateMappings"][0]["liveSchematicCandidates"]

    stripped = enrich_cross_view_live_candidates(
        verified, _Exploding(), netlist_artifact=ARTIFACT, identity_verified=False
    )
    for mapping in stripped["candidateMappings"]:
        assert "liveSchematicCandidates" not in mapping
        assert "liveCandidateEvidence" not in mapping
    assert stripped == archive, "未核实身份只做剥离，归档读数逐字段原样"


def test_verified_then_unverified_does_not_leave_a_stale_live_half():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    once = _enrich(_section(_mapping()), live)
    twice = enrich_cross_view_live_candidates(
        once, None, netlist_artifact=None, identity_verified=False
    )
    assert "liveSchematicCandidates" not in json.dumps(twice)


# --------------------------------------------------------------------------
# 5. nothing to enrich: empty / unchecked sections come back as they are
# --------------------------------------------------------------------------


def test_an_empty_lonely_section_is_returned_unchanged():
    section = {"checked": True, "minPins": 3, "lonely": []}
    out = _enrich(section, _Exploding())
    assert out == section
    assert "status" not in out and "candidateMappings" not in out


def test_an_unchecked_section_is_returned_unchanged():
    section = {"checked": False, "reason": "该 PCB 档未能与原理图板配对"}
    out = _enrich(section, _Exploding())
    assert out == section
    assert "status" not in out
    assert "confirmed" not in json.dumps(out)


def test_lonely_rows_without_mappings_get_no_invented_live_keys():
    """``candidateMappings`` 不存在就没有可补的映射，也不凭空加。"""
    section = {
        "checked": True, "minPins": 3, "status": "suspected",
        "lonely": [{"designator": "U9", "pin": "11", "schematicNet": "NET7",
                    "schematicMembers": 1, "pcbNet": "FOC_EN", "pcbMembers": 2}],
    }
    out = _enrich(section, _Exploding())
    assert out == section


# --------------------------------------------------------------------------
# 6. suspected stays suspected; the archive mapping is never rewritten
# --------------------------------------------------------------------------


def test_the_section_stays_suspected_and_never_confirmed():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    out = _enrich(_section(_mapping()), live)
    assert out["status"] == "suspected"
    assert "confirmed" not in json.dumps(out)


def test_a_cross_view_section_from_c1_keeps_its_archive_mapping():
    """Integration with 537C1's own output: archive fields compare equal."""
    schematic = DesignModel()
    schematic.components["U9"] = Component(
        uid="uid-U9", designator="U9",
        pins=[Pin(number=str(n), name=f"n{n}") for n in (1, 2, 3, 11)],
    )
    schematic.components["R11"] = Component(
        uid="uid-R11", designator="R11",
        pins=[Pin(number="1", name="n1"), Pin(number="2", name="n2")],
    )
    schematic.nets["NET7"] = Net(name="NET7", pins=[("U9", "11")])
    schematic.nets["FOC_EN"] = Net(name="FOC_EN", pins=[("R11", "1")])
    pcb = DesignModel()
    for designator, numbers in {"U9": ["1", "2", "3", "11"], "R11": ["1", "2"]}.items():
        pcb.components[designator] = Component(
            uid=f"uid-{designator}", designator=designator,
            pins=[Pin(number=n, name=f"n{n}") for n in numbers],
        )
    pcb.nets["FOC_EN"] = Net(name="FOC_EN", pins=[("R11", "1"), ("U9", "11")])

    section = cross_view_section(schematic, pcb)
    assert section["status"] == "suspected"
    archive_mapping = copy.deepcopy(section["candidateMappings"][0])
    assert archive_mapping["pcbPin"] == "U9.11"

    live = _live(
        {"U9": {"1": "PA0", "11": "PA1", "33": "PB11"}, "R11": {"1": "", "2": ""}},
        {"FOC_EN": [("U9", "33"), ("R11", "1")]},
    )
    out = _enrich(section, live)
    mapping = out["candidateMappings"][0]

    for key, value in archive_mapping.items():
        assert mapping[key] == value
    assert mapping["liveSchematicCandidates"] == [
        {"pin": "R11.1", "pinName": ""},
        {"pin": "U9.33", "pinName": "PB11"},
    ]
    assert out["status"] == "suspected"
    # the input section is untouched by the enrichment
    assert section["candidateMappings"] == [archive_mapping]


# --------------------------------------------------------------------------
# 7. purity: no mutation, no aliasing, repeated calls replace
# --------------------------------------------------------------------------


def test_the_inputs_are_not_mutated_and_the_result_does_not_alias():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    section = _section(_mapping())
    artifact = copy.deepcopy(ARTIFACT)
    snapshot = copy.deepcopy(section)

    out = _enrich(section, live)
    assert section == snapshot
    assert artifact == ARTIFACT

    mapping = out["candidateMappings"][0]
    assert mapping is not section["candidateMappings"][0]
    assert mapping["evidence"] is not section["candidateMappings"][0]["evidence"]
    evidence = mapping["liveCandidateEvidence"]
    assert evidence["netlist"] is not artifact
    assert evidence["netlist"] == artifact

    # mutating the result may not reach back into the inputs
    evidence["netlist"]["file"] = "tampered"
    assert artifact["file"] == ARTIFACT["file"]

    out["candidateMappings"][0]["pcbPin"] = "U9.99"
    assert section["candidateMappings"][0]["pcbPin"] == "U9.11"


def test_a_second_call_replaces_the_first_live_half():
    first = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    second = _live({"U9": {"35": "PB13"}}, {"FOC_EN": [("U9", "35")]})
    section = _enrich(_section(_mapping()), first)
    again = _enrich(section, second)

    mapping = again["candidateMappings"][0]
    assert mapping["liveSchematicCandidates"] == [{"pin": "U9.35", "pinName": "PB13"}]
    assert "PB11" not in json.dumps(again)
    assert mapping["pcbPin"] == "U9.11"


# --------------------------------------------------------------------------
# 8. bad inputs are refused, not guessed
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [
        None,
        {},
        {"file": "", "sha256": "a" * 64},
        {"file": "x.txt", "sha256": ""},
        {"file": "x.txt"},
        {"sha256": "a" * 64},
        "x.txt",
    ],
    ids=["none", "empty", "no-file", "no-digest", "missing-digest", "missing-file", "not-a-dict"],
)
def test_a_candidate_without_evidence_binding_is_refused(artifact):
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    with pytest.raises(ValueError):
        enrich_cross_view_live_candidates(
            _section(_mapping()), live,
            netlist_artifact=artifact, identity_verified=True,
        )


def test_no_live_model_while_generating_is_refused():
    with pytest.raises(ValueError):
        _enrich(_section(_mapping()), None)


def test_a_live_model_without_nets_is_refused():
    class _NoNets:
        components: dict = {}

    with pytest.raises(ValueError):
        _enrich(_section(_mapping()), _NoNets())


def test_a_broken_cross_view_shape_is_refused():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    for broken in (None, [], "suspected"):
        with pytest.raises(ValueError):
            _enrich(broken, live)


def test_a_malformed_mapping_is_refused_instead_of_skipped():
    live = _live({"U9": {"33": "PB11"}}, {"FOC_EN": [("U9", "33")]})
    section = _section(_mapping())
    section["candidateMappings"].append("not-a-mapping")
    with pytest.raises(ValueError):
        _enrich(section, live)


# --------------------------------------------------------------------------
# 9. parser: repeated designators are disclosed as consumer ambiguity
# --------------------------------------------------------------------------


def _netlist(entries: list[dict]) -> str:
    return json.dumps({
        "version": "2.0.0",
        "components": {f"gge-{index}": entry for index, entry in enumerate(entries)},
    })


def _entry(designator: str, value: str, pins: dict[str, tuple[str, str]]) -> dict:
    return {
        "props": {"Designator": designator, "Value": value},
        "pinInfoMap": {
            number: {"name": name, "number": number, "net": net}
            for number, (name, net) in pins.items()
        },
    }


def test_the_parser_discloses_a_repeated_designator_without_changing_reads():
    text = _netlist([
        _entry("U9", "OLD", {"1": ("PA0", "ALPHA")}),
        _entry("U9", "NEW", {"2": ("PA1", "BETA")}),
        _entry("R9", "1k", {"1": ("", "ALPHA")}),
    ])
    model = candidate_from_netlist(text)

    # the existing readings do not move: last placement wins the component key,
    # both placements still contribute their net members.
    assert model.components["U9"].value == "NEW"
    assert [pin.number for pin in model.components["U9"].pins] == ["2"]
    assert model.nets["ALPHA"].pins == [("U9", "1"), ("R9", "1")]
    assert model.nets["BETA"].pins == [("U9", "2")]
    # and the ambiguity is now visible to a consumer
    assert model.duplicate_designators == ["U9"]
    assert model.repeated_designators() == ["U9"]
    # this is disclosure, not a new same-page defect verdict
    assert model.unproven_nets == {}
    assert model.cross_page_designators == {}


def test_a_clean_netlist_discloses_no_repeated_designator():
    text = _netlist([
        _entry("U9", "MCU", {"1": ("PA0", "ALPHA")}),
        _entry("R9", "1k", {"1": ("", "ALPHA")}),
    ])
    model = candidate_from_netlist(text)
    assert model.duplicate_designators == []
    assert model.repeated_designators() == []


def test_a_repeated_designator_from_the_parser_reaches_the_enrichment():
    """The parser's disclosure and the enrichment's refusal are one story."""
    text = _netlist([
        _entry("U9", "OLD", {"33": ("PB11", "FOC_EN")}),
        _entry("U9", "NEW", {"33": ("PB11", "OTHER")}),
    ])
    model = candidate_from_netlist(text)
    assert model.repeated_designators() == ["U9"]

    evidence = _enrich(_section(_mapping()), model)["candidateMappings"][0][
        "liveCandidateEvidence"
    ]
    assert evidence["status"] == "unavailable"
    assert evidence["ambiguousDesignators"] == ["U9"]
