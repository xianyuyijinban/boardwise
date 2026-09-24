"""035: `patch-pin` — one pin's connection repaired (connect / disconnect / reconnect).

Four layers, and each one is a claim the task book makes:

* the **rule** puts a structured target only on the rows a repair can act on
  (NC-on-a-net, must_connect dangling, must_connect on the wrong net) and never
  on UNKNOWN / free-text / mode-tagged rows;
* the **plan** carries the pin, the two nets and either an attachment (what comes
  off) or a connection (what goes on), and refuses the shapes that cannot be
  executed;
* the **engine** proves an attachment on the canvas or refuses by name — a T, two
  candidates, a flag, a net label (no delete capability on this host), nothing;
* the **apply flow** writes only what the plan promised, judges the range by
  identity (never by counts — the editor merges touching wires) and lets the
  project's own netlist decide, with the idempotence probe being the rule's own
  per-pin judgement.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.changeplan import (
    ADD_COMPONENT_KIND,
    COMPONENT_VALUE_KIND,
    PATCH_PIN_KIND,
    ChangePlan,
    ChangePlanError,
    PlanAttachment,
    PlanSource,
    patch_pin_plan,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines import patchpin
from boardwise.rules import facts as facts_rules


# --------------------------------------------------------------------------
# fixtures: a small board and a shelf that states the two obligations
# --------------------------------------------------------------------------

PROV = "test fixture"


def _library() -> PartLibrary:
    ldo = PartEntry(
        key="ic.rt9013_33gb", value="", mpn="RT9013-33GB", lcsc="C47773",
        category="ic.ldo",
        facts={
            "nc_pins": {"pins": ["4"], "provenance": PROV},
            "must_connect": [{"pin": "5", "to": "NET_OUT", "provenance": PROV}],
        },
    )
    prose = PartEntry(
        key="ic.ch340g", value="", mpn="CH340G", lcsc="C14267", category="ic.uart",
        facts={
            "nc_pins": {"pins": ["13"], "provenance": PROV},
            "must_connect": [
                {"pin": "7", "to": "external 12MHz crystal network", "provenance": PROV},
                {"pin": "8", "to": "NET_TX", "mode": "5V", "provenance": PROV},
            ],
        },
    )
    return PartLibrary(parts=[ldo, prose])


def _model(*, pin_net: dict[str, str], nets: dict[str, list[tuple[str, str]]] | None) -> DesignModel:
    """A two-part board: U3 (the LDO whose pins the shelf speaks about) and U9
    (some other part that shares the nets, so a group can have more than one
    member — which is exactly what the outside-scope check is about)."""
    model = DesignModel()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin(str(n), str(n), pin_net.get(str(n))) for n in (1, 2, 3, 4, 5)],
    )
    model.components["U9"] = Component(
        uid="u9", designator="U9", value="IC",
        pins=[Pin(str(n), str(n), None) for n in (1, 2)],
    )
    for name, members in (nets or {}).items():
        model.nets[name] = Net(name, list(members))
        for designator, pin in members:
            for item in model.components[designator].pins:
                if item.number == pin:
                    item.net = name
    return model


def _ruling(model: DesignModel, pin: str):
    lib = _library()
    entry = lib.parts[0]
    return facts_rules.pin_ruling(model.components["U3"], entry, model, pin)


# --------------------------------------------------------------------------
# 1. the rule puts a target only where a repair can act
# --------------------------------------------------------------------------


def test_an_nc_pin_on_a_net_is_a_disconnect_with_a_target():
    # "Sits on a net" means it *shares* one (035, measured on the machine: a pin
    # alone on a single-member auto-net is disconnected, whatever the net is
    # called) — so the fixture gives the net another member.
    model = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    ruling = _ruling(model, "4")
    assert ruling.state == "VIOLATION"
    assert ruling.target is not None
    assert ruling.target.component_ref == "U3"
    assert ruling.target.pin_refs == ["4"]
    assert ruling.target.net_refs == ["NET4"]
    assert ruling.target.expected_before == "NET4"
    assert ruling.target.suggested_after == "", "空串 = 断开（035 §1，写进文档）"
    # ...and the rule's own findings carry that target.
    findings = facts_rules.NcAndMustConnect(library=_library()).check(model)
    assert [f.target for f in findings] == [ruling.target]


def test_a_dangling_must_connect_pin_is_a_connect_with_a_target():
    # The target net has to *exist* in the netlist for the obligation to be
    # machine-judgeable (that is the rule's own condition); the pin is the part
    # that is missing from it.
    model = _model(pin_net={}, nets={"NET_OUT": [("U9", "1")]})
    ruling = _ruling(model, "5")
    assert ruling.state == "VIOLATION"
    assert ruling.target is not None
    assert ruling.target.net_refs == ["NET_OUT"], "dangling: only the target net is named"
    assert ruling.target.expected_before == ""
    assert ruling.target.suggested_after == "NET_OUT"


def test_a_must_connect_pin_on_the_wrong_net_is_a_reconnect_with_both_ends():
    model = _model(pin_net={"5": "NET_OTHER"}, nets={"NET_OTHER": [("U3", "5")], "NET_OUT": []})
    ruling = _ruling(model, "5")
    assert ruling.state == "VIOLATION"
    assert ruling.target is not None
    assert ruling.target.net_refs == ["NET_OTHER", "NET_OUT"], (
        "current first, target last — a plan has to name what it is leaving as well as where "
        "it is going"
    )
    assert ruling.target.expected_before == "NET_OTHER"
    assert ruling.target.suggested_after == "NET_OUT"


def test_a_satisfied_must_connect_pin_rules_ok_so_a_connect_probe_can_say_done():
    """The connect form's "already done" state (035 §3's idempotence rule).

    A repeat run of a connect plan asks exactly this question, and the answer has
    to come from the same function that produced the finding — a satisfied
    `must_connect` pin rules OK, which is what lets apply answer
    `already_applied` instead of drawing the same wire twice.
    """
    model = _model(pin_net={"5": "NET_OUT"}, nets={"NET_OUT": [("U3", "5")]})
    ruling = _ruling(model, "5")
    assert ruling.state == "OK"
    assert ruling.target is None, "an OK pin has nothing to repair"


def test_free_text_mode_tagged_and_unstated_obligations_carry_no_target():
    # free text: CH340G pin 7 (the entry lives in the same synthetic shelf).
    prose_entry = _library().parts[1]
    model = _model(pin_net={"7": None}, nets={})
    model.components["U1"] = Component(
        uid="u1", designator="U1", value="", mpn="CH340G", lcsc_part="C14267",
        pins=[Pin(str(n), str(n), None) for n in (7, 8, 13)],
    )
    prose = facts_rules.pin_ruling(model.components["U1"], prose_entry, model, "7")
    assert prose.state == "UNKNOWN" and prose.target is None
    assert "free text" in prose.missing_fact
    # mode-tagged (pin 8, mode=5V) is not this rule's question at all.
    tagged = facts_rules.pin_ruling(model.components["U1"], prose_entry, model, "8")
    assert tagged.state == "UNKNOWN" and tagged.target is None
    assert "no nc_pins / must_connect obligation" in tagged.message
    # no obligation on the pin at all.
    none = facts_rules.pin_ruling(model.components["U1"], prose_entry, model, "2")
    assert none.state == "UNKNOWN" and none.target is None
    # and the OK cases are not findings, so they have nothing to repair.
    ok = _ruling(_model(pin_net={}, nets={}), "4")
    assert ok.state == "OK" and ok.target is None


# --------------------------------------------------------------------------
# 2. the plan: three forms, and the shapes it refuses
# --------------------------------------------------------------------------


def _source() -> PlanSource:
    return PlanSource(input_sha256="a" * 64, page_uuid="page-1")


def test_the_three_forms_round_trip_through_json():
    disconnect = patch_pin_plan(
        _source(), designator="U3", pin="4", before_net="NET4", after_net="",
        attachment=PlanAttachment(kind="wire", primitive_id="w1", detail="端点落在脚上",
                                  at=(10.0, 20.0)),
    )
    connect = patch_pin_plan(
        _source(), designator="U3", pin="5", before_net="", after_net="NET_OUT",
        connection="wire", connection_detail="to the NET_OUT segment", to=(5.0, 6.0),
    )
    reconnect = patch_pin_plan(
        _source(), designator="U3", pin="5", before_net="NET_OTHER", after_net="NET_OUT",
        connection="power-flag", connection_detail="a Power flag on the pin",
        attachment=PlanAttachment(kind="wire", primitive_id="w2", detail="端点落在脚上",
                                  at=(1.0, 2.0)),
    )
    for plan in (disconnect, connect, reconnect):
        assert plan.change.kind == PATCH_PIN_KIND
        back = ChangePlan.from_jsonable(plan.to_jsonable())
        assert back.target.pin == plan.target.pin
        assert back.change.before_net == plan.change.before_net
        assert back.change.after_net == plan.change.after_net
        assert [item.kind for item in back.change.connections] == [
            item.kind for item in plan.change.connections
        ]
        assert (back.change.attachment.primitive_id if back.change.attachment else "") == (
            plan.change.attachment.primitive_id if plan.change.attachment else ""
        )
    payload = disconnect.to_jsonable()
    assert payload["target"]["pin"] == "4"
    assert payload["change"]["beforeNet"] == "NET4" and payload["change"]["afterNet"] == ""
    assert payload["change"]["attachment"]["kind"] == "wire"


def test_the_old_two_kinds_serialise_exactly_as_they_always_did():
    """016/029's JSON is a contract; 035 adds keys only to its own kind."""
    from boardwise.core.changeplan import PlanPart, add_component_plan, component_value_plan

    value = component_value_plan(_source(), designator="U3", before="1k", after="2k")
    assert set(value.to_jsonable()["change"]) == {"kind", "before", "after"}
    assert set(value.to_jsonable()["target"]) == {"primitiveId", "designator", "expectedValue"}
    added = add_component_plan(
        _source(), anchor="U1", designator="C1", part=PlanPart(lcsc="C1525", value="0.1uF"),
        connections=[], x=1.0, y=2.0, recipe_source="operator:C1525",
    )
    assert set(added.to_jsonable()["change"]) == {
        "kind", "part", "connections", "recipeSource",
    }
    assert "pin" not in added.to_jsonable()["target"]


@pytest.mark.parametrize(
    "change, why",
    [
        ({"beforeNet": "NET4", "afterNet": ""}, "离开网却没有 attachment"),
        ({"beforeNet": "", "afterNet": "NET2", "connections": []}, "afterNet 非空却没有连接"),
        ({"beforeNet": "X", "afterNet": "X"}, "前后网相同"),
        ({"beforeNet": "", "afterNet": "NET2",
          "connections": [{"pin": "5", "net": "GND", "kind": "wire", "to": [1, 2]}]},
         "连接网与 afterNet 不一致"),
        ({"beforeNet": "NET4", "afterNet": "",
          "attachment": {"kind": "text", "primitiveId": "x"}}, "attachment.kind 不认识"),
        ({"beforeNet": "NET4", "afterNet": "",
          "attachment": {"kind": "wire"}}, "attachment 没有 primitiveId"),
        ({"beforeNet": "", "afterNet": "", "connections": []}, "什么都没变"),
    ],
)
def test_the_plan_refuses_shapes_it_cannot_execute(change, why):
    payload = {
        "planVersion": 1,
        "source": {"inputSha256": "a" * 64},
        "target": {"designator": "U3", "pin": "4"},
        "change": {"kind": "patch-pin", **change},
        "preconditions": [],
        "expectedPostcondition": [],
    }
    with pytest.raises(ChangePlanError):
        ChangePlan.from_jsonable(payload)


def test_a_patch_pin_plan_without_a_pin_is_refused():
    payload = {
        "planVersion": 1,
        "source": {"inputSha256": "a" * 64},
        "target": {"designator": "U3"},
        "change": {"kind": "patch-pin", "beforeNet": "", "afterNet": "NET2",
                   "connections": [{"pin": "5", "net": "NET2", "kind": "wire", "to": [1, 2]}]},
        "preconditions": [],
        "expectedPostcondition": [],
    }
    with pytest.raises(ChangePlanError, match="target.pin"):
        ChangePlan.from_jsonable(payload)


# --------------------------------------------------------------------------
# 3. the engine: an attachment is proven on the canvas or refused by name
# --------------------------------------------------------------------------


def _wire(primitive_id: str, net: str, points: list[tuple[float, float]]) -> dict:
    flat = [c for pair in points for c in pair]
    return {"primitiveId": primitive_id, "state": {"Line": flat, "Net": net}}


def _geometry(*, wires=(), netlabels=(), flags=(), components=()) -> dict:
    return {
        "components": [
            {"primitiveId": f"p-{name}", "state": {"Designator": name, "X": x, "Y": y}}
            for name, x, y in components
        ] + [
            {"primitiveId": f"f-{index}",
             "state": {"ComponentType": "netflag", "Net": net, "X": x, "Y": y}}
            for index, (net, x, y) in enumerate(flags)
        ],
        "wires": list(wires),
        "netlabels": [
            {"state": {**{"Net": net}, "X": x, "Y": y}} for net, x, y in netlabels
        ],
        "meta": {"available": {"netlabels": bool(netlabels)}},
    }


PIN_AT = (100.0, 200.0)


def test_an_attachment_is_a_wire_whose_endpoint_lands_on_the_pin():
    geometry = _geometry(wires=[
        _wire("w-1", "NET4", [(100.0, 200.0), (160.0, 200.0)]),
        _wire("w-2", "GND", [(100.0, 260.0), (160.0, 260.0)]),
    ])
    found = patchpin.attachment_on_pin(geometry, PIN_AT)
    assert found.kind == "wire" and found.primitive_id == "w-1"
    assert found.at == PIN_AT
    assert "endpoint" in found.detail


@pytest.mark.parametrize(
    "geometry, keyword",
    [
        # a wire passing through the pin mid-segment: deleting it would take away
        # whatever else it carries.
        (_geometry(wires=[_wire("w-t", "NET4", [(60.0, 200.0), (160.0, 200.0)])]),
         "T-shape"),
        # two candidates: we cannot tell which one the repair means.
        (_geometry(wires=[
            _wire("w-a", "NET4", [(100.0, 200.0), (160.0, 200.0)]),
            _wire("w-b", "GND", [(100.0, 200.0), (100.0, 260.0)]),
        ]), "2 wires end on it"),
        # a net label: real attachment, no way to delete one on this host.
        (_geometry(netlabels=[("NET4", 100.0, 200.0)]),
         "no net-label primitive"),
        # a net flag: an attachment, but not one this slice recognises.
        (_geometry(flags=[("GND", 100.0, 200.0)]), "net flag"),
        # nothing recognisable at all.
        (_geometry(), "nothing recognisable"),
    ],
)
def test_an_attachment_that_cannot_be_proven_is_refused_by_name(geometry, keyword):
    with pytest.raises(patchpin.AttachmentRefused) as caught:
        patchpin.attachment_on_pin(geometry, PIN_AT)
    assert keyword in str(caught.value)


def test_the_netlabel_refusal_names_the_missing_capability():
    with pytest.raises(patchpin.AttachmentRefused) as caught:
        patchpin.attachment_on_pin(_geometry(netlabels=[("NET4", 100.0, 200.0)]), PIN_AT)
    message = str(caught.value)
    assert "sch_PrimitiveNetLabel: absent" in message
    assert "本机没有删 netlabel 的能力" in message, "裁决 1 的原话要留在文案里"


# --------------------------------------------------------------------------
# 4. the judgements apply leans on
# --------------------------------------------------------------------------


def test_outside_scope_differences_are_empty_for_the_pins_own_move_only():
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    after = _model(pin_net={"4": "GND"}, nets={"GND": [("U3", "4")],
                                               "NET4": [("U9", "1")]})
    assert patchpin.outside_scope_differences(before, after, designator="U3", pin="4") == []


def test_outside_scope_differences_name_a_pin_that_lost_its_company():
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    after = _model(pin_net={}, nets={"NET4": [("U9", "1")]})
    problems = patchpin.outside_scope_differences(before, after, designator="U3", pin="4")
    assert problems == [], "the repaired pin left; the others kept their company"

    # ...but a wire that also carried another pin shows up as an accident.
    broken = _model(pin_net={}, nets={})
    problems = patchpin.outside_scope_differences(before, broken, designator="U3", pin="4")
    assert any("U9.1" in problem for problem in problems)


def test_readback_verdict_answers_each_form():
    connect = _model(pin_net={"5": "NET_OUT"}, nets={"NET_OUT": [("U3", "5")]})
    assert patchpin.readback_verdict(
        connect, designator="U3", pin="5", before_net="", after_net="NET_OUT") == ""
    wrong = _model(pin_net={"5": "NET_OTHER"}, nets={"NET_OTHER": [("U3", "5")]})
    assert "not on the promised" in patchpin.readback_verdict(
        wrong, designator="U3", pin="5", before_net="", after_net="NET_OUT")

    alone = _model(pin_net={"4": "NET12"}, nets={"NET12": [("U3", "4")]})
    assert patchpin.readback_verdict(
        alone, designator="U3", pin="4", before_net="NET4", after_net="") == "", (
        "a pin alone on its (auto-named) net *is* disconnected — the name is not evidence, "
        "because the editor reuses and renames those nets freely"
    )
    still = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    assert "still connected" in patchpin.readback_verdict(
        still, designator="U3", pin="4", before_net="NET4", after_net="")
    assert "U9.1" in patchpin.readback_verdict(
        still, designator="U3", pin="4", before_net="NET4", after_net="")


# --------------------------------------------------------------------------
# 5. the CLI flow: plan from a report, then apply, with a fake bridge
# --------------------------------------------------------------------------

def _geometry_before() -> dict:
    """The pin sits at (100, 200); a wire of NET4 ends exactly on it."""
    return _geometry(wires=[_wire("w-attach", "NET4", [(100.0, 200.0), (160.0, 200.0)])],
                     components=[("U3", 90.0, 190.0)])


def _geometry_after() -> dict:
    """The attachment is gone (its id is no longer on the page); other wiring stays."""
    return _geometry(wires=[_wire("w-untouched", "GND", [(100.0, 260.0), (200.0, 260.0)])],
                     components=[("U3", 90.0, 190.0)])


class _BridgeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class _FakeBridge:
    def __init__(self, *, delete_reply=None, delete_fails=False, live_nets=None):
        #: `{pin: netName}` for U3 as the **editor's own netlist** would report it
        #: ("" = on an unnamed net). Default: the repaired shape — pin 4 alone.
        #: A **list** is a sequence of readings, consumed one per `sch.netlist`
        #: call (the last one keeps answering): the live netlist is the reading
        #: that changes as the writes land, so a test that walks a whole repair
        #: tells it the before and the after state.
        if isinstance(live_nets, list):
            self.live_readings = list(live_nets) or [{}]
        else:
            self.live_readings = [{"4": ""} if live_nets is None else live_nets]
        self.live_reads = 0
        # Two views of the same page: the first `sch.geometry` read answers with
        # `before`, every later one with `after`. Tests that build a plan first
        # (which also reads the geometry) reset `reads` before the apply, so the
        # flow sees the page as it is *before* its own writes.
        self.geometry = [_geometry_before(), _geometry_after()]
        self.reads = 0
        self.calls = []
        self.writes = []
        self.delete_reply = delete_reply or {
            "deleted": ["w-attach"], "notFound": [], "failed": [],
        }
        self.delete_fails = delete_fails

    async def call(self, action, params=None, **route):
        params = params or {}
        self.calls.append(action)
        if action == "doc.list":
            return {"active": {"uuid": "page-1", "type": "page"},
                    "projects": [{"projectUuid": "proj-1", "focused": True}]}
        if action == "sys.identity":
            return {"consistent": True, "consistentBasis": "project-uuid"}
        if action == "sch.geometry":
            self.reads += 1
            return self.geometry[0] if self.reads == 1 else self.geometry[1]
        if action == "sch.component_pins":
            return {
                "primitiveId": params.get("primitiveId"), "returned": 2,
                "pins": [
                    {"X": 100.0, "Y": 200.0, "PinNumber": "4", "PinName": "NC",
                     "Rotation": 0, "PinLength": 10},
                    {"X": 120.0, "Y": 200.0, "PinNumber": "5", "PinName": "VOUT",
                     "Rotation": 0, "PinLength": 10},
                ],
            }
        if action == "sch.netlist":
            # 035 round 3: the live netlist is the fresh pin-membership reading.
            # The fake answers names, exactly like the host (`pinInfoMap[pin].net`).
            reading = self.live_readings[
                min(self.live_reads, len(self.live_readings) - 1)
            ]
            self.live_reads += 1
            return {
                "text": json.dumps({
                    "components": {
                        "gge2": {
                            "props": {"Designator": "U3"},
                            "pinInfoMap": {
                                number: {"net": net}
                                for number, net in (reading or {}).items()
                            },
                        }
                    }
                })
            }
        if action == "sch.delete_primitives":
            self.writes.append((action, params))
            if self.delete_fails:
                raise _BridgeError("CONNECTOR_ERROR", "the editor refused the delete")
            return self.delete_reply
        if action == "sch.doc.save":
            self.writes.append((action, params))
            return {"saved": True}
        if action == "sys.get_project_file":
            return {"fileType": "epro2", "data": "", "bytes": 0}
        if action == "sch.place_wire":
            self.writes.append((action, params))
            return {"uuid": "w-new", "net": params.get("net")}
        raise AssertionError(f"the flow called {action}, which this fake does not answer")

    async def close(self):
        return None


def _stub_bridge(monkeypatch, bridge):
    class _Client:
        @staticmethod
        async def open(*_args, **_kwargs):
            return bridge

    monkeypatch.setattr(cli, "_open_cli", lambda args: (_Client, _BridgeError, 61190, "tok"))


def _stub_models(monkeypatch, sequence):
    models = list(sequence)

    async def _live(call, notes):
        return models.pop(0) if models else None

    monkeypatch.setattr(cli, "_live_project_model", _live)


def _report_file(tmp_path, *, before="NET4", after="", pin="4", designator="U3"):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"findings": [{
        "rule_id": "conn-nc-and-must-connect", "severity": "ERROR",
        "message": f"{designator} pin{pin} is declared NC but sits on net {before!r}",
        "target": {"component_ref": designator, "pin_refs": [pin],
                   "net_refs": [n for n in (before, after) if n],
                   "expected_before": before, "suggested_after": after},
    }], "source": {"pageUuid": "page-1"}}), encoding="utf-8")
    return report


def _snapshot(tmp_path):
    snap = tmp_path / "snap.epro2"
    snap.write_bytes(b"x")
    return snap


def test_the_plan_names_the_attachment_the_canvas_proves(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    report = _report_file(tmp_path)
    out = tmp_path / "plan.json"

    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(report), "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "disconnect U3 pin4 NET4 → (no net)" in printed
    assert "w-attach" in printed, "the plan names the primitive it will delete"
    plan = ChangePlan.load(out)
    assert plan.change.kind == PATCH_PIN_KIND
    assert plan.target.pin == "4"
    assert plan.change.before_net == "NET4" and plan.change.after_net == ""
    assert plan.change.attachment is not None
    assert plan.change.attachment.primitive_id == "w-attach"
    assert plan.change.attachment.at == (100.0, 200.0)
    assert plan.change.connections == []


def test_the_plan_refuses_when_the_pin_sits_mid_segment(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge()
    bridge.geometry = [
        _geometry(wires=[_wire("w-through", "NET4", [(60.0, 200.0), (160.0, 200.0)])],
                  components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[_wire("w-through", "NET4", [(60.0, 200.0), (160.0, 200.0)])],
                  components=[("U3", 90.0, 190.0)]),
    ]
    _stub_bridge(monkeypatch, bridge)
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "T-shape" in err, "分不清该删哪一个就拒绝，不许猜（035 §2.2）"


def test_the_plan_refuses_a_netlabel_attachment_and_says_why(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge()
    bridge.geometry = [
        _geometry(netlabels=[("NET4", 100.0, 200.0)], components=[("U3", 90.0, 190.0)]),
        _geometry(netlabels=[("NET4", 100.0, 200.0)], components=[("U3", 90.0, 190.0)]),
    ]
    _stub_bridge(monkeypatch, bridge)
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "sch_PrimitiveNetLabel: absent" in err and "本机没有删 netlabel 的能力" in err


def test_apply_deletes_the_attachment_and_lets_the_netlist_decide(monkeypatch, tmp_path, capsys):
    # The live netlist tells the probe the pin's state *before* the run (still on
    # NET4 with U3.2) and the verification its state *after* — the reading that
    # changes as the write lands (035 round 3).
    bridge = _FakeBridge(live_nets=[{"4": "NET4", "2": "NET4"}, {"4": "", "2": ""}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    after = _model(pin_net={"4": "NET12"}, nets={"NET12": [("U3", "4")],
                                                "NET4": [("U9", "1")]})
    _stub_models(monkeypatch, [before, after, after])
    bridge.reads = 0

    async def _review(*_args, **_kwargs):
        return {"state": "resolved", "reason": "the rule reports U3 pin4 as satisfied"}

    monkeypatch.setattr(cli, "_edit_post_review_pin", _review)
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [action for action, _ in bridge.writes] == ["sch.delete_primitives", "sch.doc.save"], (
        "one delete, then the save — a pure disconnect writes nothing else"
    )
    assert bridge.writes[0][1]["primitiveIds"] == ["w-attach"]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["form"] == "disconnect"
    assert report["range"]["attachmentGone"] is True
    assert report["range"]["wiresVanished"] == ["w-attach"], (
        "delete 路径的范围检查以画布身份级差异为准（导出对删除不重算，实测）"
    )
    assert report["verification"]["ok"] is True
    assert report["verification"]["liveOk"] is True and report["verification"]["canvasOk"] is True
    assert report["verification"]["liveNet"] == ""
    assert report["verification"]["exportNetlist"] == "attached (accident report only)"
    assert report["idempotence"]["state"] == "VIOLATION"


def test_apply_refuses_a_plan_whose_pin_moved_on(monkeypatch, tmp_path, capsys):
    """A stale plan is exit 4 with no write — the re-read protection (016 §3)."""
    bridge = _FakeBridge(live_nets=[{"4": "NET_ELSEWHERE"}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    # The pin is already off NET4 (someone got there first) — but `_model` builds
    # it as NC-on-NET4-still... so the stale case is "the plan says NET4, the
    # board says something else".
    moved = _model(pin_net={"4": "NET_ELSEWHERE"},
                   nets={"NET_ELSEWHERE": [("U3", "4"), ("U9", "2")],
                         "NET4": [("U9", "1")]})
    _stub_models(monkeypatch, [moved])
    bridge.reads = 0
    code = cli.main(["edit", "apply", str(out)])
    captured = capsys.readouterr()
    assert code == 4
    assert "stale_before" in (captured.out + captured.err), (
        "改前重读：脚当前网必须 == before_net"
    )
    assert "快照已失效" in (captured.out + captured.err)
    assert bridge.writes == [], "nothing was written"


def test_apply_is_idempotent_when_the_rule_already_reports_ok(monkeypatch, tmp_path, capsys):
    """A repeat run answers already_applied with zero writes (029's rule, 030 §③'s order).

    The probe is the rule's own per-pin judgement, and it runs **before** the
    stale/attachment checks: after a successful disconnect the pin is no longer on
    `NET4` and the attachment is gone, so those checks would answer
    `stale_before`/`attachment_missing` for work that is *finished*. The pin here
    is the shelf's NC pin (U3 = C47773, nc_pins ["4"]) and it touches nothing —
    which is exactly what the rule asks for.
    """
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    healed = _model(pin_net={}, nets={"NET_OUT": [("U9", "1")]})
    # pin 4 belongs to no net at all: the NC obligation is satisfied.
    healed.components["U3"].pins[3].net = None
    healed.nets.pop("NET4", None)
    _stub_models(monkeypatch, [healed])
    bridge.reads = 0

    code = cli.main(["edit", "apply", str(out)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed
    assert "idempotent" in printed
    assert bridge.writes == [], "a repeat run writes nothing at all"


# --------------------------------------------------------------------------
# 6. 035 round-2 ruling A: one NC judgement, three shapes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin_net, nets, state, keyword",
    [
        # shares its net with another pin: connected, whatever the net is called.
        ({"4": "NET4"}, {"NET4": [("U3", "4"), ("U9", "1")]}, "VIOLATION", "with U9.1"),
        # alone on an editor-numbered net: that is the shape a *repaired* pin has
        # (measured on the machine: deleting the wire left it alone on NET6).
        ({"4": "NET7"}, {"NET7": [("U3", "4")]}, "OK", "alone on 'NET7'"),
        # alone on a net somebody named: naming is intent, so still a violation.
        ({"4": "NCNET"}, {"NCNET": [("U3", "4")]}, "VIOLATION", "named net 'NCNET'"),
        # alone with no net at all: the offline shape of "touches nothing".
        ({"4": None}, {}, "OK", "touches no net"),
    ],
)
def test_the_nc_judgement_is_one_function_with_three_shapes(pin_net, nets, state, keyword):
    ruling = _ruling(_model(pin_net=pin_net, nets=nets), "4")
    assert ruling.state == state, ruling.message
    assert keyword in ruling.message
    if state == "VIOLATION":
        assert ruling.target is not None and ruling.target.suggested_after == ""
    else:
        assert ruling.target is None


def test_the_repair_readback_reads_connected_the_same_way_as_the_rule():
    """The two must never disagree about the same board (round-2 ruling A)."""
    alone_auto = _model(pin_net={"4": "NET9"}, nets={"NET9": [("U3", "4")]})
    assert patchpin.readback_verdict(
        alone_auto, designator="U3", pin="4", before_net="NET4", after_net="") == "", (
        "a single-member auto net is the repaired shape"
    )
    alone_named = _model(pin_net={"4": "GND"}, nets={"GND": [("U3", "4")]})
    assert "named net" in patchpin.readback_verdict(
        alone_named, designator="U3", pin="4", before_net="NET4", after_net=""
    ), "a named net with one member is still a connection"
    shared = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    assert "still connected" in patchpin.readback_verdict(
        shared, designator="U3", pin="4", before_net="NET4", after_net="")
    # ...and the rule agrees with each of those three readings.
    lib = _library()
    entry = lib.parts[0]
    for model, expected in ((alone_auto, "OK"), (alone_named, "VIOLATION"),
                            (shared, "VIOLATION")):
        assert facts_rules.pin_ruling(model.components["U3"], entry, model, "4").state == expected


def test_a_must_connect_pin_is_judged_by_its_target_name_not_by_company():
    """The other direction is untouched: `net == target`, and nothing about names."""
    alone_on_target = _model(pin_net={"5": "NET_OUT"}, nets={"NET_OUT": [("U3", "5")]})
    assert _ruling(alone_on_target, "5").state == "OK"
    on_the_wrong_named_net = _model(
        pin_net={"5": "GND"}, nets={"GND": [("U3", "5")], "NET_OUT": [("U9", "1")]}
    )
    assert _ruling(on_the_wrong_named_net, "5").state == "VIOLATION"


# --------------------------------------------------------------------------
# 7. 035 round-3 ruling: the two tightenings and the two-leg verdict
# --------------------------------------------------------------------------


def test_a_must_connect_pin_that_reaches_nothing_is_the_connect_form():
    """Ruling A's reading, mirrored (035 round 3, measured on the machine).

    The export gives a pin that reaches nothing a single-member **auto** net — a
    dangling U3 pin5 exports as ``NET5 [('U3','5')]``. A must_connect judgement
    that only compared names called that a *reconnect* ("sits on 'NET5'") and
    asked for a removal with nothing to remove: the plan refused with "nothing
    recognisable attaches the pin", so the connect form could not run at all.
    Alone on a net somebody **named** is still somewhere, and stays a reconnect.
    """
    dangling = _model(pin_net={"5": "NET9"},
                      nets={"NET9": [("U3", "5")], "NET_OUT": [("U9", "1")]})
    ruling = _ruling(dangling, "5")
    assert ruling.state == "VIOLATION"
    assert ruling.target.expected_before == "", "the connect form's empty string"
    assert ruling.target.suggested_after == "NET_OUT"
    assert ruling.target.net_refs == ["NET_OUT"], "nothing is being left behind"
    assert "touches no net" in ruling.message

    alone_on_named = _model(
        pin_net={"5": "GND"}, nets={"GND": [("U3", "5")], "NET_OUT": [("U9", "1")]}
    )
    reconnect = _ruling(alone_on_named, "5")
    assert reconnect.state == "VIOLATION"
    assert reconnect.target.expected_before == "GND" and reconnect.target.suggested_after == "NET_OUT"


def test_the_two_directions_cannot_disagree_about_the_same_pin():
    """One reading, two questions (`pin_dangles` is `nc_violation` inverted)."""
    for model in (
        _model(pin_net={"5": "NET9"}, nets={"NET9": [("U3", "5")]}),
        _model(pin_net={"5": "GND"}, nets={"GND": [("U3", "5")]}),
        _model(pin_net={"5": "GND"}, nets={"GND": [("U3", "5"), ("U9", "1")]}),
        _model(pin_net={}, nets={}),
    ):
        connected, how = facts_rules.nc_violation(model, model.components["U3"], "5")
        dangles, how2 = facts_rules.pin_dangles(model, model.components["U3"], "5")
        assert dangles is (not connected) and how == how2


def test_the_plan_refuses_a_connect_whose_target_is_an_editor_named_net(
    monkeypatch, tmp_path, capsys
):
    """收紧一: a connect/reconnect target must be a net a **person** named.

    An editor-generated name (`NET9`) means nobody named that net — joining an
    anonymous net is a strange repair to begin with, and the acceptance leg reads
    the live netlist *by name*, so it could not tell that net from any other.
    """
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path, before="", after="NET9", pin="5")),
    ])
    captured = capsys.readouterr()
    assert code == 5
    assert "收紧一" in captured.err and "用户命名网" in captured.err
    assert "NET9" in captured.err, "the refusal names the net it refused"
    assert not (tmp_path / "plan.json").exists()


def test_apply_judges_unknown_when_the_live_netlist_disagrees(
    monkeypatch, tmp_path, capsys
):
    """双证缺一 = unknown, never success (035 round 3).

    The canvas leg says the pin is free (the attachment is gone, nothing else
    touches it) but the editor's own netlist still gives it a name — the two legs
    disagree, so the state of the pin cannot be stated.
    """
    bridge = _FakeBridge(live_nets=[{"4": "NET4", "2": "NET4"}, {"4": "GND"}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    _stub_models(monkeypatch, [before])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    captured = capsys.readouterr()
    printed = captured.out + captured.err
    assert code == 3, printed
    assert "verification_disagrees" in printed
    assert [action for action, _ in bridge.writes] == ["sch.delete_primitives"], (
        "the delete was issued, but nothing was saved on a disagreement"
    )
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["verification"]["liveNet"] == "GND"
    assert report["verification"]["liveOk"] is False
    assert report["verification"]["canvasOk"] is True, "the canvas leg alone is happy"
    assert report["verification"]["ok"] is False


def test_apply_judges_unknown_when_the_canvas_still_touches_the_pin(
    monkeypatch, tmp_path, capsys
):
    """The other leg of the same pair: the live netlist says the pin is off every
    net, but a wire still ends on it — 双证缺一，不判成功。"""
    bridge = _FakeBridge(live_nets=[{"4": "NET4", "2": "NET4"}, {"4": "", "2": ""}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    bridge.geometry = [
        _geometry_before(),
        # the promised attachment is gone, but another wire now ends on the pin
        _geometry(wires=[
            _wire("w-untouched", "GND", [(100.0, 260.0), (200.0, 260.0)]),
            _wire("w-fresh", "NET4", [(100.0, 200.0), (160.0, 200.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    _stub_models(monkeypatch, [before])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    captured = capsys.readouterr()
    printed = captured.out + captured.err
    assert code == 3, printed
    assert "verification_disagrees" in printed
    assert [action for action, _ in bridge.writes] == ["sch.delete_primitives"]
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["verification"]["liveNet"] == ""
    assert report["verification"]["liveOk"] is True
    assert report["range"]["wireEndpointsOnPin"] == ["w-fresh"]
    assert report["verification"]["canvasOk"] is False
    assert report["verification"]["ok"] is False


def test_the_delete_path_range_check_is_the_canvas_identity_difference(
    monkeypatch, tmp_path, capsys
):
    """收紧二: on the delete path the range is judged on the canvas.

    The project export does not recompute for a deletion (measured 035 round 3: it
    kept reporting the deleted wire's pins as joined at 0 s, after a save, 30 s
    later and after a page switch), so "the export shows no out-of-scope change"
    would pass vacuously there. What is fresh is the canvas: **exactly** the
    promised primitive may be gone. Here a second wire disappeared too.
    """
    bridge = _FakeBridge(live_nets=[{"4": "NET4", "2": "NET4"}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    bridge.geometry = [
        _geometry(wires=[
            _wire("w-attach", "NET4", [(100.0, 200.0), (160.0, 200.0)]),
            _wire("w-untouched", "GND", [(100.0, 260.0), (200.0, 260.0)]),
            _wire("w-elsewhere", "GND", [(400.0, 400.0), (460.0, 400.0)]),
        ], components=[("U3", 90.0, 190.0)]),
        # both `w-attach` and `w-elsewhere` are gone: the plan authorised one
        _geometry(wires=[_wire("w-untouched", "GND", [(100.0, 260.0), (200.0, 260.0)])],
                  components=[("U3", 90.0, 190.0)]),
    ]
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    _stub_models(monkeypatch, [before])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    captured = capsys.readouterr()
    printed = captured.out + captured.err
    assert code == 2, printed
    assert "range_canvas_diff" in printed
    assert [action for action, _ in bridge.writes] == ["sch.delete_primitives"], (
        "an out-of-scope change stops the run before the save"
    )
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["range"]["wiresVanished"] == ["w-attach", "w-elsewhere"]
    assert report["range"]["wiresAppeared"] == []


# --------------------------------------------------------------------------
# 8. 035 round 3, measured: a delete leaves the export stale, so the re-review
#    reads the editor's own netlist instead
# --------------------------------------------------------------------------


def test_the_live_netlist_is_overlaid_on_the_exported_model():
    """The overlay is `sch.netlist`'s reading on the export's identity."""
    stale = _model(
        pin_net={"2": "NET4", "4": "NET4"},
        nets={"NET4": [("U3", "2"), ("U3", "4")], "GND": [("U9", "1")]},
    )
    fresh = patchpin.overlay_live_nets(stale, {
        ("U3", "2"): "", ("U3", "4"): "", ("U9", "1"): "VOUT_3V3",
    })
    assert patchpin.pin_net(fresh, "U3", "4") is None, "the live empty reading wins"
    assert fresh.nets["NET4"].pins == [], "the stale membership is gone"
    assert fresh.nets["VOUT_3V3"].pins == [("U9", "1")], "a rename moves the pin"
    assert "GND" in fresh.nets, "a name the export knew stays; only membership is fresh"
    assert facts_rules.pin_ruling(
        fresh.components["U3"], _library().parts[0], fresh, "4"
    ).state == "OK", "the rule now sees the pin as the editor does"


def test_a_pin_the_live_netlist_does_not_report_keeps_the_exported_reading():
    stale = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    fresh = patchpin.overlay_live_nets(stale, {("U9", "1"): "NET4"})
    assert patchpin.pin_net(fresh, "U3", "4") == "NET4", (
        "no live answer for that pin: the export's reading stands rather than being invented"
    )


def test_the_re_review_reads_the_live_netlist_after_a_delete(monkeypatch, tmp_path, capsys):
    """Measured 2026-09-24 on the machine: a deletion does not recompute the export.

    The real run made this exact shape: the disconnect verified on **both** legs
    (`live ''`, `canvas ok`, the promised wire the only one gone) and saved — and
    then the re-review, built on the export, answered `still_present` because the
    export went on joining U3.2 and U3.4. So where a run removed something, the
    re-review's connectivity comes from the editor's own netlist.
    """
    bridge = _FakeBridge(
        live_nets=[{"4": "NET4", "2": "NET4"}, {"4": "", "2": ""}, {"4": "", "2": ""}]
    )
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"4": "NET4"}, nets={"NET4": [("U3", "4"), ("U9", "1")]})
    stale = _model(pin_net={"2": "NET4", "4": "NET4"},
                   nets={"NET4": [("U3", "2"), ("U3", "4")]})
    _stub_models(monkeypatch, [before, stale, stale, stale])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert [action for action, _ in bridge.writes] == [
        "sch.delete_primitives", "sch.doc.save",
    ]
    post = json.loads(result.read_text(encoding="utf-8"))["postReview"]
    assert post["connectivity"] == "sch.netlist (live) over the export"
    assert post["state"] == "resolved", post
    assert post["value"] is None


def test_a_repeat_run_of_a_disconnect_is_already_applied_over_a_stale_export(
    monkeypatch, tmp_path, capsys
):
    """Measured on the real machine: the export had not caught up with a delete.

    The probe reads the pin's state to answer "is this already done?" — on the
    export it saw the removed wire's two pins still joined, called the finished
    repair a violation, and the run then refused it as `stale_before` (exit 4,
    measured 2026-09-24). A repeat run must answer `already_applied` with zero
    writes, so the delete path's probe reads the editor's own netlist.
    """
    bridge = _FakeBridge(live_nets=[{"4": "NET4", "2": "GND"}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    stale = _model(pin_net={"2": "NET4", "4": "NET4"},
                   nets={"NET4": [("U3", "2"), ("U3", "4")]})
    _stub_models(monkeypatch, [stale])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "already_applied" in printed and "idempotent" in printed
    assert bridge.writes == [], "a repeat run writes nothing at all"
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["observedVia"] == "sch.netlist (live) over the export"
    assert report["idempotence"]["state"] == "OK"


def test_a_connect_only_run_re_reviews_on_the_export(monkeypatch, tmp_path, capsys):
    """The other half of the split (029's measurement): a **create** does make the
    editor recompute, so a connect keeps the export as its re-review source.

    The live reading here is the measured one for a dangling pin: the editor
    numbers it (`NET3`), which the connect form has to accept as "reaches nothing"
    rather than refuse as `stale_before`.
    """
    bridge = _FakeBridge(live_nets={"5": "NET_OUT"})
    _stub_bridge(monkeypatch, bridge)
    # The probe is the rule's own per-pin judgement, and it reads the shelf — whose
    # real entry for C47773 states nc_pins but no must_connect. Pin 5's obligation
    # is the fixture's own (035 §4: this one fact is invented for the test), so the
    # rule instance gets the fixture's shelf injected (FactsRule's own door).
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[_wire("w-gnd", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[
            _wire("w-gnd", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
            _wire("w-new", "NET_OUT", [(120.0, 200.0), (100.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path, before="", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"5": "NET3"},
                    nets={"NET3": [("U3", "5")], "NET_OUT": [("U9", "1")]})
    after = _model(pin_net={"5": "NET_OUT"}, nets={"NET_OUT": [("U3", "5"), ("U9", "1")]})
    _stub_models(monkeypatch, [before, after, after, after])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["observedNet"] == "NET3", (
        "the live reading of a dangling pin is an editor-numbered net — and the "
        "connect form's precondition is still satisfied"
    )
    assert report["outcome"] == "applied"
    post = report["postReview"]
    assert post["connectivity"] == "project export"
    assert post["state"] == "resolved", post


def test_a_connect_form_is_stale_when_the_pin_reaches_a_named_net(
    monkeypatch, tmp_path, capsys
):
    """The other side of the same reading: alone on a net somebody **named** is
    somewhere, so the plan's "reaches nothing" no longer holds."""
    bridge = _FakeBridge(live_nets=[{"5": "GND"}])
    _stub_bridge(monkeypatch, bridge)
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[_wire("w-gnd", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[_wire("w-gnd", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path, before="", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"5": "GND"},
                    nets={"GND": [("U3", "5")], "NET_OUT": [("U9", "1")]})
    _stub_models(monkeypatch, [before])
    bridge.reads = 0

    code = cli.main(["edit", "apply", str(out)])
    captured = capsys.readouterr()
    assert code == 4
    assert "stale_before" in (captured.out + captured.err)
    assert bridge.writes == [], "nothing was written"


# --------------------------------------------------------------------------
# 9. the two instruments must not be mixed inside one judgement
# --------------------------------------------------------------------------


def test_the_outside_scope_check_compares_the_export_with_itself(monkeypatch, tmp_path, capsys):
    """The live overlay is the **probe's** reading; the out-of-scope comparison
    compares the export with itself (035 三轮：create 路径维持导出核对).

    Measured 2026-09-24 on a reconnect: with the live overlay on the *before* side
    and the export on the after side, the run reported six phantom differences
    (pins the live netlist simply reports as unnamed — `""` — lose their exported
    membership, so they look like pins that lost company) and stopped a repair
    whose live and canvas legs were both green.
    """
    bridge = _FakeBridge(
        live_nets=[{"5": "VIN", "1": ""}, {"5": "NET_OUT"}, {"5": "NET_OUT"}],
        delete_reply={"deleted": ["w-attach5"], "notFound": [], "failed": []},
    )
    _stub_bridge(monkeypatch, bridge)
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[
            _wire("w-attach5", "VIN", [(120.0, 200.0), (200.0, 200.0)]),
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
            _wire("w-new", "NET_OUT", [(120.0, 200.0), (100.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path, before="VIN", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"1": "VIN", "5": "VIN"},
                    nets={"VIN": [("U3", "1"), ("U3", "5")], "NET_OUT": [("U9", "1")]})
    after = _model(pin_net={"1": "VIN", "5": "NET_OUT"},
                   nets={"VIN": [("U3", "1")], "NET_OUT": [("U3", "5"), ("U9", "1")]})
    _stub_models(monkeypatch, [before, after, after, after])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["form"] == "reconnect"
    assert report["observedVia"] == "sch.netlist (live) over the export"
    assert report["verification"]["outsideScope"] == [], (
        "U3.1 keeps its exported net on both sides; only the probe reads live"
    )
    assert report["verification"]["liveOk"] is True
    assert report["verification"]["canvasOk"] is True
    assert [action for action, _ in bridge.writes] == [
        "sch.delete_primitives", "sch.place_wire", "sch.doc.save",
    ]


# --------------------------------------------------------------------------
# 10. 035 round 4: "导出新鲜当且仅当本 run 无删除" — the split, both ways, and
#     the `--pin` selector for a report that carries several findings
# --------------------------------------------------------------------------


def _two_finding_report(
    tmp_path, *, first_pin="4", second_pin="5", before="VIN", after="NET_OUT"
):
    """A report with two findings for one designator under one rule — measured:
    one scratch part yields `U3 pin4` (NC) and `U3 pin5` (must_connect)."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"findings": [
        {
            "rule_id": "conn-nc-and-must-connect", "severity": "ERROR",
            "message": f"U3 pin{first_pin} is declared NC but sits on net 'NET4'",
            "target": {"component_ref": "U3", "pin_refs": [first_pin],
                       "net_refs": ["NET4"], "expected_before": "NET4",
                       "suggested_after": ""},
        },
        {
            "rule_id": "conn-nc-and-must-connect", "severity": "ERROR",
            "message": f"U3 pin{second_pin} must connect to net 'NET_OUT'",
            "target": {"component_ref": "U3", "pin_refs": [second_pin],
                       "net_refs": [before, after], "expected_before": before,
                       "suggested_after": after},
        },
    ]}), encoding="utf-8")
    return report


def test_plan_refuses_to_pick_between_two_findings_for_one_designator(
    monkeypatch, tmp_path, capsys
):
    """Measured 2026-09-24: the real report carried `U3 pin4` and `U3 pin5`.

    The old selector took the first match, so asking to repair pin5 planned a
    *disconnect of pin4* — the run then refused with "nothing recognisable
    attaches the pin", which reads as a fixture problem and is actually a
    selector that guessed.
    """
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_two_finding_report(tmp_path)),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "2 conn-nc-and-must-connect findings for U3" in err
    assert "4" in err and "5" in err, "the refusal names the candidate pins"
    assert "--pin" in err
    assert "不许挑第一条" in err


def test_plan_with_pin_repairs_the_pin_the_caller_named(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    bridge.geometry = [
        _geometry(wires=[_wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[_wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "5",
        "--report", str(_two_finding_report(tmp_path, before="")), "-o", str(out),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    plan = ChangePlan.load(out)
    assert plan.target.pin == "5", "pin 5's finding, not the first one in the file"
    assert plan.change.before_net == "" and plan.change.after_net == "NET_OUT"
    assert plan.change.attachment is None, "the connect form has nothing to remove"


def test_plan_with_a_pin_the_report_does_not_carry_refuses(monkeypatch, tmp_path, capsys):
    bridge = _FakeBridge()
    _stub_bridge(monkeypatch, bridge)
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "9",
        "--report", str(_two_finding_report(tmp_path)),
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "pin9" in err and "no conn-nc-and-must-connect finding matches that pin" in err


def test_pin_without_a_report_is_refused_not_ignored(monkeypatch, tmp_path, capsys):
    """`--pin` selects among a report's findings; the `--file` path never sees one."""
    _stub_bridge(monkeypatch, _FakeBridge())
    code = cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "5",
    ])
    err = capsys.readouterr().err
    assert code == 5
    assert "--pin selects one of a **report's** findings" in err


def test_a_delete_run_is_judged_on_the_canvas_and_the_live_netlist(monkeypatch, tmp_path, capsys):
    """035 round 4: 导出新鲜当且仅当本 run 无删除.

    This is the offline shape of the real phantom: the exports say another pin
    joined the net (measured on the machine, the export reported
    `GND = [U3.1, U3.2, U3.5]` after a reconnect whose live netlist read
    `U3 {1:'', 2:'GND', 5:'GND'}`). A reconnect **deletes**, so the export is not
    the instrument and must not be able to block the repair: the canvas identity
    and the live netlist are.
    """
    bridge = _FakeBridge(
        live_nets=[{"5": "VIN"}, {"5": "NET_OUT"}, {"5": "NET_OUT"}],
        delete_reply={"deleted": ["w-attach5"], "notFound": [], "failed": []},
    )
    _stub_bridge(monkeypatch, bridge)
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[
            _wire("w-attach5", "VIN", [(120.0, 200.0), (200.0, 200.0)]),
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
            _wire("w-new", "NET_OUT", [(120.0, 200.0), (100.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "5",
        "--report", str(_report_file(tmp_path, before="VIN", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"1": "VIN", "5": "VIN"},
                    nets={"VIN": [("U3", "1"), ("U3", "5")], "NET_OUT": [("U9", "1")]})
    # ...and the export's own "after" is the phantom: it says U3.9 joined the net.
    phantom = _model(pin_net={"1": "NET_OUT", "5": "NET_OUT"},
                     nets={"NET_OUT": [("U3", "1"), ("U3", "5"), ("U9", "1")]})
    _stub_models(monkeypatch, [before, phantom, phantom, phantom])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["verification"]["outsideScope"] == [], (
        "the export is not asked to pass judgement on a run that deleted something"
    )
    assert "canvas identity" in report["verification"]["outsideScopeBasis"]
    assert report["verification"]["exportNetlist"] == "attached (accident report only)"
    assert report["verification"]["exportNet"] == "NET_OUT", "still attached as evidence"
    assert [action for action, _ in bridge.writes] == [
        "sch.delete_primitives", "sch.place_wire", "sch.doc.save",
    ]


def test_a_create_only_run_still_judges_the_export_out_of_scope(monkeypatch, tmp_path, capsys):
    """The other half: a pure create is where the export **is** fresh (029)."""
    bridge = _FakeBridge(live_nets={"5": "NET_OUT"})
    _stub_bridge(monkeypatch, bridge)
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[_wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)])],
                  components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
            _wire("w-new", "NET_OUT", [(120.0, 200.0), (100.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "5",
        "--report", str(_report_file(tmp_path, before="", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"5": "NET3"},
                    nets={"NET3": [("U3", "5")], "NET_OUT": [("U9", "1")]})
    # the export's own after did something out of scope: U9.1 lost its company
    stray = _model(pin_net={"5": "NET_OUT"}, nets={"NET_OUT": [("U3", "5")]})
    _stub_models(monkeypatch, [before, stray])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    captured = capsys.readouterr()
    assert code == 2, captured.out + captured.err
    assert "outside_scope" in (captured.out + captured.err)
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["verification"]["outsideScope"], "the export's difference is the verdict"
    assert "project export" in report["verification"]["outsideScopeBasis"]
    assert report["verification"]["exportNetlist"].startswith("judged")
    assert "sch.doc.save" not in [action for action, _ in bridge.writes]


def test_a_free_text_must_connect_target_is_unknown_even_when_the_pin_dangles():
    """The dangles branch must not preempt the free-text answer (035 四轮回归).

    `must_connect` targets can be prose ("external 12MHz crystal network"); that is
    UNKNOWN however the pin currently sits — including when it reaches nothing,
    which is the branch added this round.
    """
    prose = _library().parts[1]  # CH340G: pin 7 -> free text, pin 8 -> NET_TX
    model = DesignModel()
    model.components["U5"] = Component(
        uid="u5", designator="U5", value="", mpn="CH340G", lcsc_part="C14267",
        pins=[Pin(str(n), str(n), None) for n in (4, 7, 8)],
    )
    model.nets["NET_TX"] = Net("NET_TX", [("U9", "1")])
    ruling = facts_rules.pin_ruling(model.components["U5"], prose, model, "7")
    assert ruling.state == "UNKNOWN"
    assert "free text" in ruling.message
    assert ruling.target is None, "an unjudgeable obligation gets no plan"
    # ...and the same pin on a named net is still UNKNOWN, not a reconnect.
    model.components["U5"].pins[1].net = "GND"
    model.nets["GND"] = Net("GND", [("U5", "7")])
    assert facts_rules.pin_ruling(model.components["U5"], prose, model, "7").state == "UNKNOWN"


def test_the_editors_internal_net_name_is_auto_and_means_nothing():
    """Measured 2026-09-24: one unnamed wire, two spellings.

    The export called that net `NET3`; `sch.netlist` called the same net `$57N2`.
    A judgement that only treated `NET\\d+` as nameless would read `$57N2` as
    somebody's chosen name — an NC pin alone on it would be a violation forever,
    and a plan built on the export would answer `stale_before` for a board that
    had not moved.
    """
    assert facts_rules.is_auto_net("$57N2") and facts_rules.is_auto_net("NET12")
    assert facts_rules.is_auto_net("net7"), "the export's casing varies"
    assert not facts_rules.is_auto_net("GND") and not facts_rules.is_auto_net("NET_OUT")
    assert not facts_rules.is_auto_net("") and not facts_rules.is_auto_net(None)

    alone = _model(pin_net={"4": "$57N2"}, nets={"$57N2": [("U3", "4")]})
    ruling = _ruling(alone, "4")
    assert ruling.state == "OK", "alone on the editor's own name is still alone"
    assert "touches no net" in ruling.message


def test_two_auto_spellings_are_one_island_for_the_stale_check(monkeypatch, tmp_path, capsys):
    """The reconnect fixture exactly as measured: the plan's `before_net` came from
    the export (`NET3`), the live netlist reports the same island as `$57N2`, and
    the run has to proceed — `stale_before` there is a false alarm (measured)."""
    bridge = _FakeBridge(
        live_nets=[{"5": "$57N2"}, {"5": "NET_OUT"}, {"5": "NET_OUT"}],
        delete_reply={"deleted": ["w-attach5"], "notFound": [], "failed": []},
    )
    _stub_bridge(monkeypatch, bridge)
    rule = next(item for item in cli.BUILTIN_RULES if item.id == "conn-nc-and-must-connect")
    monkeypatch.setattr(rule, "_library", _library())
    bridge.geometry = [
        _geometry(wires=[
            _wire("w-attach5", "NET3", [(120.0, 200.0), (200.0, 200.0)]),
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
        _geometry(wires=[
            _wire("w-out", "NET_OUT", [(100.0, 140.0), (160.0, 140.0)]),
            _wire("w-new", "NET_OUT", [(120.0, 200.0), (100.0, 140.0)]),
        ], components=[("U3", 90.0, 190.0)]),
    ]
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3", "--pin", "5",
        "--report", str(_report_file(tmp_path, before="NET3", after="NET_OUT", pin="5")),
        "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"1": "NET3", "5": "NET3"},
                    nets={"NET3": [("U3", "1"), ("U3", "5")], "NET_OUT": [("U9", "1")]})
    after = _model(pin_net={"1": "NET3", "5": "NET_OUT"},
                   nets={"NET3": [("U3", "1")], "NET_OUT": [("U3", "5"), ("U9", "1")]})
    _stub_models(monkeypatch, [before, after, after, after])
    bridge.reads = 0
    result = tmp_path / "apply.json"

    code = cli.main(["edit", "apply", str(out), "--json", str(result)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    report = json.loads(result.read_text(encoding="utf-8"))
    assert report["observedNet"] == "$57N2", "the live spelling of the plan's 'NET3'"
    assert report["verification"]["liveOk"] is True
    assert "sch.doc.save" in [action for action, _ in bridge.writes]


def test_a_named_before_net_is_still_compared_by_name(monkeypatch, tmp_path, capsys):
    """The widening stops at auto names: `GND` is somebody's word, so a move off it
    is still `stale_before`."""
    bridge = _FakeBridge(live_nets=[{"4": "VCC"}])
    _stub_bridge(monkeypatch, bridge)
    out = tmp_path / "plan.json"
    assert cli.main([
        "edit", "plan", "--file", str(_snapshot(tmp_path)),
        "--rule", "conn-nc-and-must-connect", "--designator", "U3",
        "--report", str(_report_file(tmp_path)), "-o", str(out),
    ]) == 0
    capsys.readouterr()
    before = _model(pin_net={"4": "VCC"}, nets={"VCC": [("U3", "4"), ("U9", "2")]})
    _stub_models(monkeypatch, [before])
    bridge.reads = 0

    code = cli.main(["edit", "apply", str(out)])
    captured = capsys.readouterr()
    assert code == 4
    assert "stale_before" in (captured.out + captured.err)
    assert bridge.writes == []
