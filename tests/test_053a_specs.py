"""053 阶段 A 的三份数据合同 + SymbolProfile（任务书 §二 全部小节）。

这一批不实现编译器、不实现可读性检查器，只把"电路的**含义**""该怎样被**读**"
"工具算出的**图**"和"一个库符号的**几何**"钉成可校验的数据形状。测试要钉住的
是形状背后的**拒绝**，因为模型入口的纪律全靠它们：

1. **坐标只有一个合法入口**（052 §4）。`PresentationSpec.userLocks` 是工程师的
   决定，其余任何地方出现 `x`/`y`/`rotation`/`wirePoints`/`connectorAction` 一律
   **直接拒绝而不清洗**——不清洗意味着报错里必须能读到那个键的路径。
2. **依据三态，缺席不是已核实**（052 §4）。`ai_asserted` 与"什么都没说"都让整份
   spec 变成草稿 `draft`；写成 `draft: false` 想把它按回去，是拒绝而不是忽略。
3. **"没给连接"≠ NC**。只有显式 `nc` 才是否定，反过来 NC 的脚不许同时挂在网上。
4. **每段文字都有 bbox**（053 §二 LayoutPlan）。文字条目缺框是 schema 级别的拒绝，
   因为可读性合同正是用这些框量遮挡的。
5. **解析器没给的字段就留空并说明**（本任务书 §范围 4）。`from_parsed_symbol` 只
   映射 `SymbolDetail` 已有的几何：脚朝向是**推导**出来的、并且每个脚自己标注来源
   （`direction_source`），文字框则一个都不编——profile 的 `texts` 是空的，理由写在
   `notes` 里。两个脚共用一个 tip 直接拒绝，那是"禁止换脚号迁就版式"的检测入口。

SymbolProfile 的最小用例是**手写字面量**（`_ParsedSymbol`），不建夹具文件：这份合约
说的是"解析器给我的东西长什么样"，用夹具反而把解析器的行为绑进来了。
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from boardwise.core.circuitspec import (
    AUTO_NET_PREFIX,
    CircuitSpec,
    CircuitSpecError,
    spec_sha256,
)
from boardwise.core.layoutplan import (
    EVIDENCE_VERDICT_FAIL,
    EVIDENCE_VERDICT_NOT_RUN,
    EVIDENCE_VERDICT_PASS,
    LayoutEvidence,
    LayoutPlan,
    LayoutPlanError,
)
from boardwise.core.presentationspec import (
    PresentationSpec,
    PresentationSpecError,
    presentation_sha256,
)
from boardwise.core.symbolprofile import (
    DEFAULT_POSES,
    DIRECTION_SOURCE_BODY,
    POSES_SOURCE_UNRESTRICTED,
    SymbolProfile,
    SymbolProfileError,
    from_parsed_symbol,
)

HEX = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64


# --------------------------------------------------------------- CircuitSpec


def _divider_spec(**overrides):
    """A division-by-two divider, stated so that every fact is confirmed."""
    payload = {
        "parts": [
            {"id": "R1", "symbolRef": "R0402", "value": "10k",
             "provenance": "verified_recipe"},
            {"id": "R2", "symbolRef": "R0402", "value": "10k",
             "provenance": "verified_recipe"},
            {"id": "J1", "symbolRef": "CONN-2P",
             "provenance": "engineer_confirmed"},
        ],
        "nets": [
            {"id": "VIN", "class": "power", "members": ["R1.1", "J1.1"],
             "provenance": "verified_recipe", "scope": "project"},
            {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"],
             "provenance": "verified_recipe", "scope": "page"},
            {"id": "GND", "class": "gnd", "members": ["R2.2", "J1.2"],
             "provenance": "verified_recipe", "scope": "project"},
        ],
    }
    payload.update(overrides)
    return payload


def test_the_three_provenance_states_are_read_and_only_the_confirmed_ones_are_not_drafts():
    spec = CircuitSpec.from_dict(_divider_spec())
    assert [part.provenance for part in spec.parts] == [
        "verified_recipe", "verified_recipe", "engineer_confirmed",
    ]
    assert spec.draft is False
    assert spec.draft_reasons == []

    ai = CircuitSpec.from_dict({
        "parts": [{"id": "R1", "symbolRef": "R0402", "provenance": "ai_asserted"}],
        "nets": [{"id": "TAP", "class": "signal", "members": ["R1.1"],
                  "provenance": "ai_asserted"}],
    })
    assert ai.draft is True
    assert len(ai.draft_reasons) == 2
    assert any("part R1" in line for line in ai.draft_reasons)
    assert any("net TAP" in line for line in ai.draft_reasons)

    # 一个词面量以外的依据是拒绝，不是"当成已核实"。
    with pytest.raises(CircuitSpecError, match="provenance"):
        CircuitSpec.from_dict({
            "parts": [{"id": "R1", "symbolRef": "R0402",
                       "provenance": "looks-right-to-me"}],
        })
    with_parts = CircuitSpec.from_dict({
        "parts": [{"id": "R1", "symbolRef": "R0402", "provenance": "engineer_confirmed"}],
    })
    assert with_parts.draft is False


def test_a_fact_that_says_nothing_is_a_draft_and_cannot_be_talked_out_of_it():
    """缺席不是已核实：不写 provenance 本身就是"未确认"，草稿标记按不下去。"""
    unlabelled = CircuitSpec.from_dict({"parts": [{"id": "R1", "symbolRef": "R0402"}]})
    assert unlabelled.draft is True
    assert "no confirmed basis" in unlabelled.draft_reasons[0]

    with pytest.raises(CircuitSpecError, match=r"\$\.draft is false but this spec is a draft"):
        CircuitSpec.from_dict({
            "parts": [{"id": "R1", "symbolRef": "R0402"}],
            "draft": False,
        })
    # 反过来保守地自认草稿是允许的，而且往返读回一致。
    conservative = CircuitSpec.from_dict(_divider_spec(draft=True))
    assert conservative.draft is False  # 计算值来自事实，而不是声明
    assert CircuitSpec.from_dict(conservative.to_jsonable()) == conservative


def test_pairwise_connections_normalise_into_one_net_with_many_members():
    """糖只作输入，规范化后是一网多成员：两段 pairwise 合成一个三脚网。"""
    spec = CircuitSpec.from_dict({
        "parts": [
            {"id": "R1", "symbolRef": "R0402", "provenance": "engineer_confirmed"},
            {"id": "R2", "symbolRef": "R0402", "provenance": "engineer_confirmed"},
            {"id": "C1", "symbolRef": "C0402", "provenance": "engineer_confirmed"},
        ],
        "connections": [
            {"from": "R1.2", "to": "R2.1", "provenance": "engineer_confirmed"},
            {"from": "R1.2", "to": "C1.1", "provenance": "engineer_confirmed"},
        ],
    })
    assert len(spec.nets) == 1
    net = spec.nets[0]
    assert net.members == ["C1.1", "R1.2", "R2.1"]
    assert net.id.startswith(AUTO_NET_PREFIX)
    assert net.cls == "signal"      # 未声明的默认，写在常量里
    assert net.scope == ""          # 未声明就是未声明，不等于 page
    assert net.provenance == "engineer_confirmed"
    # 规范形式里没有 connections 这个键，糖已经不存在了。
    assert "connections" not in spec.to_jsonable()
    assert CircuitSpec.from_dict(spec.to_jsonable()) == spec


def test_sugar_extends_a_declared_net_and_records_the_member_labels():
    spec = CircuitSpec.from_dict(_divider_spec(
        parts=_divider_spec()["parts"] + [
            {"id": "U1", "symbolRef": "IC-8", "provenance": "engineer_confirmed"},
        ],
        connections=[{"from": "U1.1", "to": "R1.2", "provenance": "ai_asserted"}],
    ))
    tap = spec.net("TAP")
    assert tap.members == ["R1.2", "R2.1", "U1.1"]   # 糖把新脚并进了已声明的网
    # 网比它最弱的事实更"已确认"是不允许的：接进来的是 AI 断言，整条网降级。
    assert tap.provenance == "ai_asserted"
    assert spec.draft is True
    assert CircuitSpec.from_dict(spec.to_jsonable()) == spec


def test_a_connection_that_would_merge_two_named_nets_is_refused():
    with pytest.raises(CircuitSpecError, match="would merge"):
        CircuitSpec.from_dict(_divider_spec(connections=[
            {"from": "R1.1", "to": "R2.2"},
        ]))
    # 间接合并同样拒绝：两段糖各自"合法"，连起来把两个已命名的网焊成一个。
    with pytest.raises(CircuitSpecError, match="would merge"):
        CircuitSpec.from_dict(_divider_spec(
            parts=_divider_spec()["parts"] + [
                {"id": "U1", "symbolRef": "IC-8", "provenance": "engineer_confirmed"},
            ],
            connections=[
                {"from": "U1.1", "to": "R1.1"},
                {"from": "U1.2", "to": "R2.2"},
                {"from": "U1.1", "to": "U1.2"},
            ],
        ))


def test_a_pin_on_two_nets_is_refused():
    with pytest.raises(CircuitSpecError, match="is a member of both"):
        CircuitSpec.from_dict(_divider_spec(nets=[
            {"id": "VIN", "class": "power", "members": ["R1.1"]},
            {"id": "TAP", "class": "signal", "members": ["R1.1"]},
        ]))


def test_an_nc_pin_that_is_also_a_net_member_is_refused():
    with pytest.raises(CircuitSpecError, match="NC is explicit"):
        CircuitSpec.from_dict(_divider_spec(nc=[{"pin": "R1.1"}]))
    # 显式的 NC 是合法的，并且带自己的依据（J1.3 没在任何网上）。
    ok = CircuitSpec.from_dict(_divider_spec(nc=[
        {"pin": "J1.3", "provenance": "engineer_confirmed"},
    ]))
    assert ok.nc[0].pin == "J1.3"
    assert ok.draft is False
    # 只写脚号的简写是书上的写法，但它没说出处 → 草稿。
    shorthand = CircuitSpec.from_dict(_divider_spec(nc=["J1.3"]))
    assert shorthand.nc[0].provenance == ""
    assert shorthand.draft is True
    with pytest.raises(CircuitSpecError, match="twice"):
        CircuitSpec.from_dict(_divider_spec(nc=["J1.3", {"pin": "J1.3"}]))


def test_an_unmentioned_pin_is_not_nc():
    """没给连接 ≠ NC：两种事实分开存，谁也不能代替谁。"""
    spec = CircuitSpec.from_dict(_divider_spec(parts=[
        {"id": "R1", "symbolRef": "R0402", "provenance": "verified_recipe"},
    ], nets=[{"id": "TAP", "class": "signal", "members": ["R1.1"],
              "provenance": "verified_recipe"}]))
    assert spec.nc == []
    assert spec.net_of_pin("R1.2") is None      # 只是没提，不是 NC


def test_a_member_of_a_part_that_does_not_exist_is_refused():
    with pytest.raises(CircuitSpecError, match="does not declare"):
        CircuitSpec.from_dict(_divider_spec(nc=[{"pin": "R9.1"}]))
    with pytest.raises(CircuitSpecError, match="does not declare"):
        CircuitSpec.from_dict(_divider_spec(connections=[{"from": "R1.1", "to": "R9.2"}]))
    with pytest.raises(CircuitSpecError, match="connection to nothing"):
        CircuitSpec.from_dict(_divider_spec(nets=[
            {"id": "VIN", "class": "power", "members": ["NOPE.1"]},
        ]))


def test_a_circuit_spec_refuses_any_coordinate_at_all():
    """含义层不接受坐标：x/y 与 wirePoints 一样是拒绝，报错要点出路径。"""
    with pytest.raises(CircuitSpecError, match=r"parts\[0\]\.x is a coordinate-shaped key"):
        CircuitSpec.from_dict(_divider_spec(parts=[
            {"id": "R1", "symbolRef": "R0402", "x": 100},
        ]))
    with pytest.raises(CircuitSpecError, match=r"parts\[0\]\.params\.rotation"):
        CircuitSpec.from_dict(_divider_spec(parts=[
            {"id": "R1", "symbolRef": "R0402", "params": {"rotation": "90"}},
        ]))
    with pytest.raises(CircuitSpecError, match="wirePoints"):
        CircuitSpec.from_dict(_divider_spec(connections=[
            {"from": "R1.1", "to": "R2.2", "wirePoints": [[0, 0], [10, 10]]},
        ]))


def test_the_schema_is_closed_and_the_version_is_read():
    with pytest.raises(CircuitSpecError, match="unknown key"):
        CircuitSpec.from_dict(_divider_spec(notes=["hand-written"]))
    with pytest.raises(CircuitSpecError, match="specVersion"):
        CircuitSpec.from_dict(_divider_spec(specVersion=2))
    with pytest.raises(CircuitSpecError, match="expected one of"):
        CircuitSpec.from_dict(_divider_spec(nets=[
            {"id": "VIN", "class": "supply", "members": ["R1.1"]},
        ]))
    with pytest.raises(CircuitSpecError, match="must be a string"):
        CircuitSpec.from_dict(_divider_spec(parts=[
            {"id": "R1", "symbolRef": "R0402", "params": {"tolerance": 1}},
        ]))


def test_the_spec_hash_is_over_the_normal_form_not_the_file_layout():
    spec = CircuitSpec.from_dict(_divider_spec())
    reordered = CircuitSpec.from_dict(json.loads(json.dumps(_divider_spec())))
    assert spec_sha256(spec) == spec.sha256() == spec_sha256(reordered)
    changed = CircuitSpec.from_dict(_divider_spec(parts=[
        {"id": "R1", "symbolRef": "R0402", "value": "20k",
         "provenance": "verified_recipe"},
    ] + _divider_spec()["parts"][1:]))
    assert spec_sha256(changed) != spec_sha256(spec)


def test_a_spec_loads_and_dumps_through_a_file(tmp_path):
    path = tmp_path / "divider.circuitspec.json"
    CircuitSpec.from_dict(_divider_spec()).dump(path)
    assert CircuitSpec.load(path) == CircuitSpec.from_dict(_divider_spec())
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(CircuitSpecError, match="is not JSON"):
        CircuitSpec.load(bad)
    missing = tmp_path / "nope.json"
    with pytest.raises(CircuitSpecError, match="cannot be read"):
        CircuitSpec.load(missing)


# ----------------------------------------------------------- PresentationSpec


def _presentation(**overrides):
    payload = {
        "modules": [{"id": "m-divider", "parts": ["R1", "R2"],
                     "role": "voltage divider"}],
        "mainPaths": [{"id": "main",
                       "chain": ["net:VIN", "part:R1", "net:TAP", "part:R2",
                                 "net:GND"]}],
        "portRoles": {"VIN": "input", "TAP": "output"},
        "grammarRef": "voltage-divider",
        "directWiringObligations": [{"nets": ["TAP"], "note": "the tap is a stub"}],
        "labelPolicy": {"local": "wire", "crossModule": "label", "highFanout": "label"},
        "sidePreferences": {"input": "left", "power": "top"},
        "userLocks": [{"partId": "J1", "x": 320.0, "y": 200.0, "rotation": 0}],
    }
    payload.update(overrides)
    return payload


def test_a_presentation_spec_round_trips_with_its_lock_the_only_coordinate():
    spec = PresentationSpec.from_dict(_presentation())
    assert spec.grammar_ref == "voltage-divider"
    assert spec.locked_part_ids() == ["J1"]
    assert spec.user_locks[0].x == 320.0
    assert spec.side_for("power") == "top"
    assert spec.side_for("gnd") == "bottom"        # 缺省值补齐
    assert spec.label_policy.local == "wire"
    assert PresentationSpec.from_dict(spec.to_jsonable()) == spec
    assert presentation_sha256(spec) == spec.sha256()
    # 规范形式里唯一的坐标就是那把锁。
    written = json.dumps(spec.to_jsonable())
    assert written.count('"x"') == 1 and '"rotation"' in written
    assert '"wirePoints"' not in written


@pytest.mark.parametrize("spot", [
    {"modules": [{"id": "m", "parts": [{"id": "R1", "x": 10}], "role": "r"}]},
    {"userLocks": [{"partId": "R1", "x": 1, "y": 2, "rotation": 0,
                    "wirePoints": [[0, 0], [1, 1]]}]},
    {"directWiringObligations": [{"nets": ["TAP"], "points": [[0, 0]]}]},
    {"mainPaths": [{"id": "p", "chain": ["net:VIN"], "connectorAction": "createWire"}]},
])
def test_a_coordinate_shaped_key_is_refused_wherever_it_appears(spot):
    """schema 直接拒绝，不清洗：模型入口不接受原始坐标/wire points/connector 动作。"""
    with pytest.raises(PresentationSpecError, match="coordinate"):
        PresentationSpec.from_dict(_presentation(**spot))


def test_the_coordinate_refusal_names_the_path_it_found():
    with pytest.raises(PresentationSpecError, match=r"\$\.modules\[0\]\.parts\[0\]\.x"):
        PresentationSpec.from_dict(_presentation(modules=[
            {"id": "m", "parts": [{"id": "R1", "x": 10}], "role": "r"},
        ]))


def test_the_label_policy_hard_codes_the_local_wire_rule():
    """053 §七：局部直连义务优先，跨模块/高扇出才许标签。"""
    with pytest.raises(PresentationSpecError, match="key local topology"):
        PresentationSpec.from_dict(_presentation(labelPolicy={"local": "label"}))
    # 外侧两种情形收紧成 wire 是允许的（更严的选择）。
    strict = PresentationSpec.from_dict(_presentation(
        labelPolicy={"crossModule": "wire", "highFanout": "wire"},
    ))
    assert strict.label_policy.cross_module == "wire"
    assert strict.label_policy.high_fanout == "wire"
    with pytest.raises(PresentationSpecError, match="labelPolicy.highFanout"):
        PresentationSpec.from_dict(_presentation(labelPolicy={"highFanout": "netlabel"}))


def test_an_unknown_grammar_is_refused_rather_than_replaced_by_a_generic_layout():
    for grammar in ("voltage-divider", "rc-lowpass", "ldo", ""):
        assert PresentationSpec.from_dict(_presentation(grammarRef=grammar)).grammar_ref == grammar
    with pytest.raises(PresentationSpecError, match="grammarRef"):
        PresentationSpec.from_dict(_presentation(grammarRef="buck-converter"))


def test_locks_are_unique_and_must_name_a_pose_the_symbols_are_drawn_in():
    with pytest.raises(PresentationSpecError, match="already locked"):
        PresentationSpec.from_dict(_presentation(userLocks=[
            {"partId": "J1", "x": 0, "y": 0, "rotation": 0},
            {"partId": "J1", "x": 10, "y": 0, "rotation": 0},
        ]))
    with pytest.raises(PresentationSpecError, match="rotation"):
        PresentationSpec.from_dict(_presentation(userLocks=[
            {"partId": "J1", "x": 0, "y": 0, "rotation": 45},
        ]))
    with pytest.raises(PresentationSpecError, match="partId"):
        PresentationSpec.from_dict(_presentation(userLocks=[{"x": 0, "y": 0}]))


def test_path_steps_are_typed_and_a_chain_visits_an_element_once():
    with pytest.raises(PresentationSpecError, match="a path step names what it is"):
        PresentationSpec.from_dict(_presentation(mainPaths=[
            {"id": "main", "chain": ["VIN", "part:R1"]},
        ]))
    with pytest.raises(PresentationSpecError, match="twice"):
        PresentationSpec.from_dict(_presentation(mainPaths=[
            {"id": "main", "chain": ["part:R1", "net:TAP", "part:R1"]},
        ]))
    with pytest.raises(PresentationSpecError, match="chain is empty"):
        PresentationSpec.from_dict(_presentation(mainPaths=[{"id": "main"}]))


def test_a_feedback_path_is_declared_the_same_way_as_a_main_path():
    spec = PresentationSpec.from_dict(_presentation(feedbackPaths=[
        {"id": "fb", "chain": ["net:OUT", "part:R3", "net:FB"], "note": "kept visible"},
    ]))
    assert spec.feedback_paths[0].chain[0] == "net:OUT"


def test_the_port_role_vocabulary_is_shared_with_the_circuit_spec():
    with pytest.raises(PresentationSpecError, match="portRoles"):
        PresentationSpec.from_dict(_presentation(portRoles={"VIN": "sink"}))
    # 同一个词表：openInterfaces.direction 也认这五个词。
    spec = PresentationSpec.from_dict(_presentation(
        portRoles={key: value for key, value in [
            ("VIN", "source"), ("VOUT", "load"), ("FB", "feedback"),
            ("IN", "input"), ("OUT", "output"),
        ]},
    ))
    assert spec.port_roles["FB"] == "feedback"


# -------------------------------------------------------------- SymbolProfile


@dataclasses.dataclass
class _ParsedSymbol:
    """`SymbolDetail` 的形状，手写字面量——不建夹具文件（见本文件开头）。

    字段名与 `parsers.schematic.SymbolDetail` 逐字一致：`from_parsed_symbol`
    只按这些名字读，这也是这一批对解析器的**全部**依赖。
    """

    uuid: str
    title: str = ""
    offsets: dict = dataclasses.field(default_factory=dict)
    pin_names: dict = dataclasses.field(default_factory=dict)
    pin_types: dict = dataclasses.field(default_factory=dict)
    body: tuple | None = None


def _minimal_symbol() -> _ParsedSymbol:
    return _ParsedSymbol(
        uuid="sym-min",
        title="MIN",
        offsets={"1": (-30.0, 0.0), "2": (30.0, 0.0), "10": (30.0, -10.0),
                 "3": (0.0, 0.0)},
        pin_names={"1": "VIN", "2": "GND", "10": "OUT", "3": ""},
        pin_types={"1": "Power", "2": "Undefined", "10": "Output", "3": "Undefined"},
        body=(-20.0, -15.0, 20.0, 15.0),
    )


def test_a_minimal_parsed_symbol_becomes_a_profile_with_derived_directions():
    profile = from_parsed_symbol(_minimal_symbol())
    assert profile.symbol_ref == "sym-min"
    assert profile.title == "MIN"
    assert profile.body == (-20.0, -15.0, 20.0, 15.0)
    # 脚号按自然序（1 < 2 < 10）：文件里的顺序是格式噪声，049 已实测同一符号
    # 在两种容器里给出的顺序不同。
    assert profile.pin_numbers() == ["1", "2", "3", "10"]
    left, right, inside, rightten = profile.pins
    assert left.tip == (-30.0, 0.0)
    assert left.direction == "left" and left.direction_source == DIRECTION_SOURCE_BODY
    assert right.direction == "right"
    assert rightten.direction == "right"
    # 落在 body 里（或 body 上）的脚：几何没给出朝向，就不给朝向、也不给来源。
    assert inside.direction == "" and inside.direction_source == ""
    # 电气角色来自引脚名，且出处标明；名字不在表里就不猜。
    assert left.electrical_role == "VIN" and left.role_source == "pin-name"
    assert right.electrical_role == "GND"
    assert rightten.electrical_role == "OUT"
    assert inside.electrical_role == "" and inside.role_source == ""
    assert left.pin_type == "Power"        # 符号自己写的类型，原样带出
    assert left.length is None             # 解析器没给长度，就留 None


def test_the_profile_admits_what_the_parser_does_not_give():
    profile = from_parsed_symbol(_minimal_symbol())
    assert profile.texts == []                       # 不编文字框
    assert "Text" in profile.notes[0].capitalize() or "texts" in profile.notes[1]
    assert profile.pose_source == POSES_SOURCE_UNRESTRICTED
    assert len(profile.poses) == len(DEFAULT_POSES) == 8
    assert profile.allows(90) and profile.allows(270, mirror=True)
    assert not profile.allows(45)
    assert any("length" in note for note in profile.notes)


def test_two_pins_sharing_a_tip_are_refused_at_extraction_and_on_reload():
    """053 §二：这是"禁止换脚号迁就版式"的检测入口——换脚号是禁止的修法。"""
    symbol = _minimal_symbol()
    symbol.offsets["4"] = (-30.0, 0.0)
    symbol.pin_names["4"] = "VIN2"
    with pytest.raises(SymbolProfileError, match="share the tip"):
        from_parsed_symbol(symbol)

    profile = from_parsed_symbol(_minimal_symbol())
    payload = profile.to_jsonable()
    payload["pins"].append({"number": "4", "tip": [-30.0, 0.0], "name": "VIN2"})
    with pytest.raises(SymbolProfileError, match="share the tip"):
        SymbolProfile.from_dict(payload)


def test_the_geometry_hash_covers_pins_and_not_the_role_table_or_pin_order():
    profile = from_parsed_symbol(_minimal_symbol())
    baseline = profile.geometry_hash()
    assert baseline == hashlib.sha256(profile.canonical_json().encode("utf-8")).hexdigest()

    # 同样的几何、脚列表换个顺序：同一个符号，还是同一个哈希。
    payload = profile.to_jsonable()
    payload["pins"] = list(reversed(payload["pins"]))
    assert SymbolProfile.from_dict(payload).geometry_hash() == baseline

    # 角色推断换了说法但几何没动 → 哈希不变（更好的名字表不该让计划失效）。
    payload = profile.to_jsonable()
    payload["pins"][0]["electricalRole"] = "GND"
    payload["pins"][0]["roleSource"] = "pin-name"
    assert SymbolProfile.from_dict(payload).geometry_hash() == baseline

    # 几何真的动了 → 哈希必须变。
    payload = profile.to_jsonable()
    payload["pins"][0]["tip"] = [-31.0, 0.0]
    assert SymbolProfile.from_dict(payload).geometry_hash() != baseline
    payload = profile.to_jsonable()
    payload["body"] = [-21.0, -15.0, 20.0, 15.0]
    assert SymbolProfile.from_dict(payload).geometry_hash() != baseline


def test_a_profile_round_trips_and_a_narrowed_pose_set_must_say_so():
    profile = from_parsed_symbol(_minimal_symbol())
    payload = profile.to_jsonable()
    assert SymbolProfile.from_dict(payload) == profile

    narrowed = dict(payload, poses=[{"rotation": 0, "mirror": False},
                                    {"rotation": 180, "mirror": False}],
                    poseSource="declared")
    reloaded = SymbolProfile.from_dict(narrowed)
    assert len(reloaded.poses) == 2 and not reloaded.allows(90)
    # 声明"无限制"却不能与给出的集合对上，是拒绝而不是照抄。
    with pytest.raises(SymbolProfileError, match="narrows the set"):
        SymbolProfile.from_dict(dict(narrowed, poseSource=POSES_SOURCE_UNRESTRICTED))
    with pytest.raises(SymbolProfileError, match="poseSource"):
        SymbolProfile.from_dict(dict(narrowed, poseSource="library"))
    with pytest.raises(SymbolProfileError, match="cannot be placed"):
        SymbolProfile.from_dict(dict(payload, poses=[]))
    with pytest.raises(SymbolProfileError, match="rotation"):
        SymbolProfile.from_dict(dict(payload, poses=[{"rotation": 45}]))


def test_an_object_that_is_not_a_parsed_symbol_is_refused_by_name():
    with pytest.raises(SymbolProfileError, match="offsets"):
        from_parsed_symbol({"offsets": {"1": (0.0, 0.0)}})
    with pytest.raises(SymbolProfileError, match="no uuid"):
        from_parsed_symbol(_ParsedSymbol(uuid="", offsets={"1": (0.0, 0.0)}))


# ---------------------------------------------------------------- LayoutPlan


def _layout(**overrides):
    payload = {
        "source": {"circuitSha256": HEX, "presentationSha256": DIGEST_B},
        "target": {"projectUuid": "proj-1", "pageUuid": "page-1",
                   "hostVersion": "3.2.186", "connectorVersion": "0.9.0"},
        "parts": [
            {"partId": "R1", "reference": "R101", "symbolRef": "R0402",
             "symbolHash": DIGEST_C, "x": 100.0, "y": 200.0, "rotation": 90,
             "mirror": False},
            {"partId": "R2", "reference": "R102", "symbolRef": "R0402",
             "symbolHash": DIGEST_C, "x": 100.0, "y": 260.0, "rotation": 270,
             "mirror": False},
        ],
        "segments": [
            {"net": "VIN", "points": [[100.0, 200.0], [100.0, 180.0]]},
            {"net": "TAP", "points": [[100.0, 240.0], [140.0, 240.0]]},
        ],
        "junctions": [{"net": "TAP", "x": 100.0, "y": 240.0}],
        "labels": [{"net": "TAP", "text": "TAP", "x": 145.0, "y": 240.0,
                    "rotation": 0, "bbox": [140.0, 235.0, 175.0, 245.0]}],
        "powerSymbols": [{"symbolRef": "GND", "symbolHash": DIGEST_C, "net": "GND",
                          "x": 100.0, "y": 280.0, "rotation": 0}],
        "texts": [
            {"kind": "reference", "text": "R101", "partId": "R1", "x": 90.0,
             "y": 195.0, "bbox": [80.0, 190.0, 99.0, 200.0]},
            {"kind": "value", "text": "10k", "partId": "R1", "x": 90.0, "y": 205.0,
             "bbox": [80.0, 200.0, 99.0, 210.0]},
        ],
    }
    payload.update(overrides)
    return payload


def test_a_layout_plan_round_trips_and_binds_itself_by_geometry():
    plan = LayoutPlan.from_dict(_layout())
    digest = plan.geometry_sha256()
    assert len(digest) == 64
    written = plan.to_jsonable()
    assert written["geometrySha256"] == digest
    assert written["verdict"] == EVIDENCE_VERDICT_NOT_RUN
    assert LayoutPlan.from_dict(written) == plan
    assert plan.part("R1").reference == "R101"
    # 标签和普通文字一起读：可读性合同的文字互不遮挡要同时看这两份。
    assert [label for label, _box in plan.all_text_boxes()] == [
        "texts[reference]'R101'", "texts[value]'10k'", "labels[TAP]'TAP'",
    ]


def test_geometry_digest_ignores_the_evidence_and_follows_the_picture():
    plan = LayoutPlan.from_dict(_layout())
    checked = LayoutPlan.from_dict(_layout(evidence={
        "checker": "engines.readability",
        "hardViolations": [],
        "softMetrics": {"crossings": 0.0},
        "softReasons": {"crossings": "no crossing in this candidate"},
    }))
    assert checked.geometry_sha256() == plan.geometry_sha256()
    moved = LayoutPlan.from_dict(_layout(parts=[
        {"partId": "R1", "reference": "R101", "symbolRef": "R0402",
         "symbolHash": DIGEST_C, "x": 100.0, "y": 205.0, "rotation": 0},
        _layout()["parts"][1],
    ]))
    assert moved.geometry_sha256() != plan.geometry_sha256()


def test_every_piece_of_text_must_carry_the_box_it_occupies():
    """053 §二：每段文字都有 bbox——缺框是 schema 级拒绝，不是"以后算"。"""
    with pytest.raises(LayoutPlanError, match=r"texts\[0\]\.bbox is missing"):
        LayoutPlan.from_dict(_layout(texts=[
            {"kind": "reference", "text": "R101", "partId": "R1"},
        ]))
    with pytest.raises(LayoutPlanError, match=r"labels\[0\]\.bbox is missing"):
        LayoutPlan.from_dict(_layout(labels=[
            {"net": "TAP", "text": "TAP", "x": 0.0, "y": 0.0},
        ]))
    with pytest.raises(LayoutPlanError, match="below minX"):
        LayoutPlan.from_dict(_layout(texts=[
            {"kind": "reference", "text": "R101", "bbox": [10.0, 10.0, 5.0, 20.0]},
        ]))


def test_the_verdict_is_computed_from_the_evidence_rather_than_stated():
    assert LayoutEvidence().verdict == EVIDENCE_VERDICT_NOT_RUN
    passing = LayoutEvidence(checker="engines.readability")
    assert passing.verdict == EVIDENCE_VERDICT_PASS
    failing = LayoutEvidence(checker="engines.readability",
                             hard_violations=["wire end off pin"])
    assert failing.verdict == EVIDENCE_VERDICT_FAIL

    plan = LayoutPlan.from_dict(_layout(evidence={"checker": "engines.readability",
                                                  "hardViolations": ["pins clash"]}))
    written = plan.to_jsonable()
    assert written["verdict"] == EVIDENCE_VERDICT_FAIL
    with pytest.raises(LayoutPlanError, match="verdict is computed"):
        LayoutPlan.from_dict(dict(written, verdict="pass"))
    with pytest.raises(LayoutPlanError, match="geometrySha256"):
        LayoutPlan.from_dict(dict(written, geometrySha256=DIGEST_B))


def test_a_soft_metric_keeps_its_value_and_the_reason_for_it():
    """052 §六：保留原始指标和具体原因，不能只报 aesthetics=4.2。"""
    plan = LayoutPlan.from_dict(_layout(evidence={
        "checker": "engines.readability",
        "softMetrics": {"bends": 3.0, "wireLength": 41.5},
        "softReasons": {"bends": "the tap detours around the value text"},
    }))
    assert plan.evidence.soft_metrics["bends"] == 3.0
    assert "detours" in plan.evidence.soft_reasons["bends"]
    with pytest.raises(LayoutPlanError, match="not in evidence.softMetrics"):
        LayoutPlan.from_dict(_layout(evidence={
            "softMetrics": {"bends": 3.0},
            "softReasons": {"crossings": "not a metric above"},
        }))
    with pytest.raises(LayoutPlanError, match="must be a number"):
        LayoutPlan.from_dict(_layout(evidence={"softMetrics": {"bends": "three"}}))


def test_a_plan_refuses_the_shapes_a_checker_could_not_trust():
    with pytest.raises(LayoutPlanError, match="circuitSha256 must be 64 hex"):
        LayoutPlan.from_dict(_layout(source={"circuitSha256": "short",
                                             "presentationSha256": DIGEST_B}))
    with pytest.raises(LayoutPlanError, match="parts is empty"):
        LayoutPlan.from_dict(_layout(parts=[]))
    with pytest.raises(LayoutPlanError, match="already placed"):
        LayoutPlan.from_dict(_layout(parts=_layout()["parts"] * 2))
    with pytest.raises(LayoutPlanError, match="already used by"):
        LayoutPlan.from_dict(_layout(parts=[
            dict(_layout()["parts"][0], partId="R9"),
            _layout()["parts"][0],
        ]))
    with pytest.raises(LayoutPlanError, match="symbolHash must be 64 hex"):
        LayoutPlan.from_dict(_layout(parts=[
            dict(_layout()["parts"][0], symbolHash=""),
        ]))
    with pytest.raises(LayoutPlanError, match="zero-length"):
        LayoutPlan.from_dict(_layout(segments=[
            {"net": "TAP", "points": [[100.0, 240.0], [100.0, 240.0]]},
        ]))
    with pytest.raises(LayoutPlanError, match="planVersion"):
        LayoutPlan.from_dict(_layout(planVersion=9))
    with pytest.raises(LayoutPlanError, match="unknown key"):
        LayoutPlan.from_dict(_layout(preview="preview.svg"))
    # 离线计划没有活页面可绑：快照摘要为空是"还没绑"，不是缺一项守卫。
    offline = LayoutPlan.from_dict(_layout(target={}))
    assert offline.target.snapshot_sha256 == ""
    assert offline.target.page_uuid == ""
