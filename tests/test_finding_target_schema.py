"""The structured `target` of a finding, and the plan schema of the five M3 kinds.

029-a left one thing un-pinned: `checkup`'s ``report.json`` carries each finding
through ``dataclasses.asdict`` (``cli._finding_payload``, called from the report
assembly at ``cli.py:2827``; `review --json` does the same in
`engines.review.render_json`), so the structured :class:`FindingTarget` that 016
added rode along inside that `asdict` with **no schema test of its own**. What
`asdict` happened to do was the contract by accident — one field added to the
dataclass, or one `Optional` introduced, and every consumer of the report
(`edit plan --report`, `review-mark`, a friend's script) would learn about it by
breaking.

**Everything asserted here is the shape as it is today.** It is pinned, not
blessed: if a key moves, a type changes, or a `None` appears where the target
now carries an empty string, these tests are meant to go red, and the change is
meant to go back to the main agent for a ruling. Nothing here "fixes" the shape.

It is a widening, not a first pass: 029-d added one such test for the
`add-component` kind through `render_json`
(`test_029a_addcomponent.py::test_the_report_target_schema_is_explicit`). This
file covers all five M3 kinds, both report paths (`checkup`'s payload and
`review --json`), the "nothing to repair" and "nothing filled in" edges, and the
plan-side `to_jsonable` key sets — which that one test does not reach.

Two things the file deliberately does not pretend:

* the three rule-driven kinds are produced by their **real** rules (016's
  injected fixture, and hand-built shelf entries that state 029's and 035's
  facts), so the pinned keys are the ones a live report really carries;
* ``insert-subcircuit`` and ``move-block`` have **no driving rule** — 036 and 037
  take the request itself as the entry point, so no rule writes a finding for
  them. Their rows in the table below are a stand-in instance, and the test that
  uses them says so. `FindingTarget` is one dataclass for every kind, so the
  serializer's shape is the same question everywhere; only the plan-side targets
  differ per kind, which the second half of this file pins.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.changeplan import (
    CONNECTION_WIRE,
    ChangePlan,
    PlanAttachment,
    PlanConnection,
    PlanIsland,
    PlanMove,
    PlanPart,
    PlanSource,
    add_component_plan,
    component_value_plan,
    insert_subcircuit_plan,
    move_block_plan,
    patch_pin_plan,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary, load_parts
from boardwise.engines.review import render_json
from boardwise.rules import facts as facts_rules
from boardwise.rules.base import Finding, FindingTarget
from boardwise.rules.decap import DecapRequiredCaps
from boardwise.rules.params import ValueMpnMatch

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
#: 016's own contradiction: U3 reads 4.7k on the board and its MPN decodes as 1k.
VALUE_MPN_BOARD = ROOT / "reviewsets" / "injected" / "value-mpn-mismatch.epro2"

PROV = "test fixture, p.1, http://example.com/ds.pdf"

#: The finding side of the schema. One shape for every kind — this is the whole
#: point of the assertions below, so it is written once and read by all of them.
FINDING_KEYS = {
    "rule_id", "severity", "message", "level", "evidence", "target", "board", "refs",
}
TARGET_KEYS = {
    "component_ref", "primitive_id", "pin_refs", "net_refs",
    "expected_before", "suggested_after",
}
# 126a §钉 3 added two PCB-side keys to the same dataclass: ``counterpart_ref``
# (a layout rule judges a *pair*) and ``measurement`` (a layout rule's evidence
# is a number read off the board). They are **widening, not reinterpretation**:
# every schematic rule leaves both at their neutral value, so the six keys above
# keep the meaning they had and none of the assertions below had to change what
# they mean — only which keys the target is expected to carry. The pin moved
# from "six keys" to "these eight keys, of which the last two are PCB's", which
# is the same pin with the 126a amendment written into it.
PCB_TARGET_KEYS = {"counterpart_ref", "measurement"}
ALL_TARGET_KEYS = TARGET_KEYS | PCB_TARGET_KEYS


# --------------------------------------------------------------------------
# one finding per M3 change kind
# --------------------------------------------------------------------------


def _component_value_finding() -> Finding:
    """016's kind: `param-value-mpn-match` on its own injected fixture."""
    model, _geometry = cli._load_model(VALUE_MPN_BOARD, view="schematic")
    findings = ValueMpnMatch(library=load_parts(SHELF)).check(model)
    targeted = [item for item in findings if item.target is not None]
    assert targeted, "the fixture is 016's own contradiction; the rule must still act on it"
    return targeted[0]


def _add_component_finding() -> Finding:
    """029's kind: `decap-required-caps` — an IC whose shelf entry requires a cap."""
    entry = PartEntry(
        key="ic.test", mpn="TEST1", lcsc="C1", category="ic.ldo",
        facts={
            "supply_pins": [
                {"pins": ["1"], "name": "VIN", "v_operating": [2.2, 5.5], "provenance": PROV}
            ],
            "required_caps": [{"pin": "1", "value": "0.1uF", "provenance": PROV}],
        },
    )
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1", value="", mpn="TEST1", lcsc_part="C1",
        pins=[Pin("1", "1", "RAIL"), Pin("2", "2", "GND")],
    )
    model.nets["RAIL"] = Net("RAIL", [("U1", "1")])
    model.nets["GND"] = Net("GND", [("U1", "2")])
    findings = DecapRequiredCaps(library=PartLibrary(parts=[entry])).check(model)
    targeted = [item for item in findings if item.target is not None]
    assert targeted, "a missing required capacitor is what this rule reports"
    return targeted[0]


def _patch_pin_finding() -> Finding:
    """035's kind: `conn-nc-and-must-connect` — an NC pin sharing a net."""
    entry = PartEntry(
        key="ic.rt9013_33gb", mpn="RT9013-33GB", lcsc="C47773", category="ic.ldo",
        facts={
            "nc_pins": {"pins": ["4"], "provenance": PROV},
            "must_connect": [{"pin": "5", "to": "NET_OUT", "provenance": PROV}],
        },
    )
    model = DesignModel()
    model.components["U3"] = Component(
        uid="u3", designator="U3", value="", mpn="RT9013-33GB", lcsc_part="C47773",
        pins=[Pin(str(n), str(n), "NET4" if n == 4 else None) for n in (1, 2, 3, 4, 5)],
    )
    model.components["U9"] = Component(
        uid="u9", designator="U9", value="IC",
        pins=[Pin("1", "1", "NET4"), Pin("2", "2", None)],
    )
    model.nets["NET4"] = Net("NET4", [("U3", "4"), ("U9", "1")])
    findings = facts_rules.NcAndMustConnect(library=PartLibrary(parts=[entry])).check(model)
    targeted = [item for item in findings if item.target is not None and item.target.pin_refs == ["4"]]
    assert targeted, "an NC pin that shares a net is the rule's disconnect shape"
    return targeted[0]


def _stand_in_finding(kind: str) -> Finding:
    """036 / 037 have no driving rule, so this instance is a stand-in, not output.

    Both slices take the *request* as the entry point (`edit plan --insert`,
    `--move`): there is no finding to repair, and no rule writes one for them
    (036's and 037's 入口裁决). The row exists so that all five M3 kinds appear in
    the table below; what it pins is the serializer's shape for a target, which
    is kind-independent because `FindingTarget` is one dataclass.
    """
    return Finding(
        rule_id=f"<{kind}: no driving rule>",
        severity="WARN",
        message=f"stand-in for {kind}: no rule reports this kind",
        level="L2",
        evidence=[],
        target=FindingTarget(
            component_ref="U1", pin_refs=["5"], net_refs=["NET1"],
            expected_before="NET1", suggested_after="GND",
        ),
    )


#: kind -> the finding that kind's schema is pinned on.
KIND_FINDINGS = {
    "component-value": _component_value_finding,
    "add-component": _add_component_finding,
    "patch-pin": _patch_pin_finding,
    "insert-subcircuit": lambda: _stand_in_finding("insert-subcircuit"),
    "move-block": lambda: _stand_in_finding("move-block"),
}


# --------------------------------------------------------------------------
# 1. the report: the finding and its target, as serialised
# --------------------------------------------------------------------------


def test_the_report_finding_carries_the_dataclass_fields_plus_refs():
    """`refs` is the one derived key; everything else is the dataclass, verbatim.

    `asdict` is why the target is here at all (029-a's leftover): the payload is
    the dataclass plus `finding_refs`, so this test is the pin on that
    arrangement rather than on a hand-written mapping that does not exist.
    """
    payload = cli._finding_payload(_component_value_finding())
    assert set(payload) == FINDING_KEYS
    assert set(payload) == set(Finding.__dataclass_fields__) | {"refs"}
    assert isinstance(payload["refs"], list)


@pytest.mark.parametrize("kind", sorted(KIND_FINDINGS))
def test_the_target_section_is_the_same_six_keys_for_every_m3_kind(kind):
    """One shape, five kinds — and an empty field is an empty value, never absent.

    A target that dropped its empty keys would serialise differently per kind
    (016 fills two of the six, 035 fills three), and every consumer would have to
    treat a missing key and an empty one as the same thing. The keys are pinned
    as *always present*.

    126a: eight keys now — the six, plus ``counterpart_ref``/``measurement``,
    which the schematic rules of these five kinds leave neutral. Renamed from
    ``..._six_keys_...`` because "six" stopped being the truth; the assertion is
    otherwise unchanged.
    """
    payload = cli._finding_payload(KIND_FINDINGS[kind]())
    assert set(payload["target"]) == ALL_TARGET_KEYS


@pytest.mark.parametrize("kind", sorted(KIND_FINDINGS))
def test_the_target_values_have_the_types_a_report_reader_gets(kind):
    target = cli._finding_payload(KIND_FINDINGS[kind]())["target"]
    for key in ("component_ref", "primitive_id", "expected_before", "suggested_after"):
        assert isinstance(target[key], str), key
    for key in ("pin_refs", "net_refs"):
        assert isinstance(target[key], list) and all(
            isinstance(item, str) for item in target[key]
        ), key
    # 126a: ``counterpart_ref`` is another string; ``measurement`` is the one
    # key allowed to be ``None``, and only it — it is what distinguishes "this
    # rule measures" from "this rule does not".
    assert isinstance(target["counterpart_ref"], str)
    assert target["measurement"] is None
    assert None not in [
        target[key] for key in TARGET_KEYS
    ], (
        "no None noise inside the six original keys: an unknown field is an empty "
        "string / empty list (the shape 016 wrote) and a reader must not have to "
        "handle both"
    )


@pytest.mark.parametrize("kind", sorted({"component-value", "add-component", "patch-pin"}))
def test_the_real_rules_fill_the_target_of_their_own_kind(kind):
    """The pinned shape is what the rules actually emit, not only what a test built."""
    target = cli._finding_payload(KIND_FINDINGS[kind]())["target"]
    assert target["component_ref"], "a repairable finding names the part it is about"
    assert target["primitive_id"] == "", (
        "offline the live primitive id does not exist yet (016 sec.2.3); apply resolves it"
    )


def test_the_contradiction_kind_states_no_repair_direction():
    """052 §2.1: one kind's target is deliberately empty where it used to advise.

    `param-value-mpn-match` finds that the board's value and the MPN disagree.
    Until 052 the target carried the MPN's decoded value as `suggested_after`,
    which reads as "write this" — and 048 ruled that on 17 parts the *MPN* was
    the wrong field. The value is an empty string today, and the two candidate
    repairs are named in the message instead; the schema is unchanged, since an
    empty string is the shape 016 wrote for "nothing here".
    """
    target = cli._finding_payload(_component_value_finding())["target"]
    assert target["expected_before"] == "4.7kΩ"
    assert target["suggested_after"] == ""
    assert isinstance(target["suggested_after"], str)


def test_the_two_report_paths_agree_finding_for_finding():
    """`checkup`'s payload and `review --json`'s must be the same document.

    Two spellings would let `review-mark` and the report disagree about the shape
    they both read; this is the assertion that keeps "reused on purpose"
    (`cli._finding_payload`'s docstring) true as the dataclass changes.
    """
    finding = _patch_pin_finding()
    from_json = json.loads(render_json([finding]))["findings"][0]
    assert cli._finding_payload(finding) == from_json


def test_a_finding_with_no_target_carries_the_key_as_null():
    """The other rules' shape: the slot is there, and it says "nothing to repair".

    `edit plan` refuses a finding whose target is missing (`None`); it must be
    able to tell that apart from a target that exists and is empty.
    """
    payload = cli._finding_payload(
        Finding(rule_id="decap-required-caps", severity="WARN", message="m", level="L2")
    )
    assert "target" in payload and payload["target"] is None
    assert set(payload) == FINDING_KEYS, "the key set does not depend on the target"


def test_an_empty_target_still_serialises_all_six_keys():
    """The eight keys of 126a, and the two new ones at their neutral value.

    126a adds ``counterpart_ref: ""`` and ``measurement: None``, so this pin
    moved from six keys to eight; the original six keep their values exactly.
    """
    payload = cli._finding_payload(
        Finding(rule_id="r", severity="WARN", message="m", level="L2", target=FindingTarget())
    )
    assert payload["target"] == {
        "component_ref": "", "primitive_id": "", "pin_refs": [], "net_refs": [],
        "expected_before": "", "suggested_after": "",
        "counterpart_ref": "", "measurement": None,
    }


def test_a_pcb_measurement_target_round_trips_its_shape():
    """126a pins the *shape* of the new keys without any rule filling them yet.

    126b/126c are the rules that write a measurement; this is the pin that says
    what one is allowed to look like, so a rule that invents a fifth spelling
    goes red here rather than into a report. `measurement` is a plain mapping
    (the dataclass carries no nested type of its own), so what is pinned is: it
    survives `asdict`, it is a dict, and the keys it carries are the documented
    ones.
    """
    payload = cli._finding_payload(Finding(
        rule_id="pcb-decap-distance", severity="WARN", message="m", level="L2",
        board="PCB1",
        target=FindingTarget(
            component_ref="U1", counterpart_ref="C7",
            measurement={"kind": "distance", "value": 180.0, "unit": "mil"},
        ),
    ))
    target = payload["target"]
    assert target["counterpart_ref"] == "C7"
    assert target["measurement"] == {
        "kind": "distance", "value": 180.0, "unit": "mil",
    }
    # A measurement that names the layers it was read on says so.
    payload = cli._finding_payload(Finding(
        rule_id="pcb-track-ampacity", severity="WARN", message="m", level="L2",
        target=FindingTarget(measurement={
            "kind": "width", "value": 12.0, "unit": "mil", "layer_ids": [15],
        }),
    ))
    assert payload["target"]["measurement"]["layer_ids"] == [15]


def test_the_serialised_finding_carries_no_private_keys():
    """`asdict` would carry a leading-underscore field straight into report.json.

    There is none today, and the point of pinning it is that a future private
    field — a cache, a resolved flag — must not reach a report as a key a reader
    has no business seeing.
    """
    def leaks(payload: object, where: str = "") -> list[str]:
        if isinstance(payload, dict):
            found = [
                f"{where}.{key}" if where else key
                for key in payload
                if key.startswith("_")
            ]
            for key, value in payload.items():
                found.extend(leaks(value, f"{where}.{key}"))
            return found
        if isinstance(payload, list):
            return [leak for item in payload for leak in leaks(item, where)]
        return []

    for kind in sorted(KIND_FINDINGS):
        assert leaks(cli._finding_payload(KIND_FINDINGS[kind]())) == []
        assert leaks(cli._finding_payload(
            Finding(rule_id="r", severity="WARN", message="m", level="L2")
        )) == []


# --------------------------------------------------------------------------
# 2. the plan side: `to_jsonable` per kind
# --------------------------------------------------------------------------

SOURCE = PlanSource(input_sha256="a" * 64, page_uuid="page-1")


def _plans() -> dict[str, ChangePlan]:
    """One plan per kind, built by the real builder that owns that kind."""
    return {
        "component-value": component_value_plan(
            SOURCE, designator="U3", before="4.7k", after="1k",
        ),
        "add-component": add_component_plan(
            SOURCE, anchor="U1", designator="C7",
            part=PlanPart(lcsc="C1525", value="0.1uF"),
            connections=[
                PlanConnection("1", "VCC", kind=CONNECTION_WIRE, detail="d", to=(5.0, 0.0)),
                PlanConnection("2", "GND", kind=CONNECTION_WIRE, detail="d", to=(0.0, 5.0)),
            ],
            x=0.0, y=-5.0, recipe_source="operator:C1525",
            connection=CONNECTION_WIRE, connection_detail="d",
        ),
        "patch-pin": patch_pin_plan(
            SOURCE, designator="U3", pin="5", before_net="", after_net="GND",
            connection=CONNECTION_WIRE, connection_detail="d", to=(5.0, 0.0),
        ),
        "insert-subcircuit": insert_subcircuit_plan(
            SOURCE, template="divider",
            parts=[
                PlanPart(designator="R1", role="r1", lcsc="C7250", value="1k", x=0.0, y=0.0),
                PlanPart(designator="R3", role="r2", lcsc="C7250", value="2k", x=0.0, y=5.0),
            ],
            connections=[
                PlanConnection("1", "N", kind=CONNECTION_WIRE, detail="d",
                               designator="R1", to=(0.0, 0.0)),
            ],
            anchor_net="N", before_net="",
        ),
        "move-block": move_block_plan(
            SOURCE, moves=[PlanMove("U1", "p-U1", (0.0, 0.0), 0.0, (100.0, 0.0))],
            wire_ops=[], islands=[PlanIsland("U1.1", ["U2.1"])],
            designators=["U1"], dx=100.0, dy=0.0,
        ),
    }


#: The exact key sets `to_jsonable` produces per kind, as measured on this build.
#: `component-value` is 016's frozen three-key target; every other kind adds its
#: own keys and never removes one of the three.
PLAN_KEYS = {
    "plan": {"planVersion", "source", "target", "change", "preconditions",
             "expectedPostcondition"},
    "target": {
        "component-value": {"primitiveId", "designator", "expectedValue"},
        "add-component": {
            "primitiveId", "designator", "expectedValue", "anchor",
            "assignedDesignator", "x", "y", "connection", "connectionDetail",
        },
        "patch-pin": {"primitiveId", "designator", "expectedValue", "pin"},
        "insert-subcircuit": {
            "primitiveId", "designator", "expectedValue", "anchor", "anchorNet",
            "pin", "x", "y",
        },
        "move-block": {
            "primitiveId", "designator", "expectedValue", "designators", "dx", "dy",
        },
    },
    "change": {
        "component-value": {"kind", "before", "after"},
        "add-component": {"kind", "part", "connections", "recipeSource"},
        "patch-pin": {"kind", "beforeNet", "afterNet", "connections"},
        "insert-subcircuit": {
            "kind", "template", "parts", "connections", "beforeNet", "baselineFindings",
        },
        "move-block": {"kind", "moves", "wireOps", "islands", "baselineFindings"},
    },
}


@pytest.mark.parametrize("kind", sorted(PLAN_KEYS["change"]))
def test_the_plan_key_sets_are_what_this_build_emits(kind):
    payload = _plans()[kind].to_jsonable()
    assert set(payload) == PLAN_KEYS["plan"]
    assert set(payload["target"]) == PLAN_KEYS["target"][kind]
    assert set(payload["change"]) == PLAN_KEYS["change"][kind]
    assert payload["change"]["kind"] == kind


def test_a_disconnect_plan_adds_exactly_the_attachment_key():
    """`patch-pin`'s one conditional key: what comes off the pin, or nothing.

    035's three forms share this serialiser, so the key set is not fixed by the
    kind alone: a disconnect (something is removed before the connection, if any)
    carries ``attachment``, and a connect / reconnect does not. Pinned on both
    sides, because "the key is silently always present, holding null" and "the
    key is silently gone" are both shape changes a reader would meet at runtime.
    """
    disconnect = patch_pin_plan(
        SOURCE, designator="U3", pin="4", before_net="NET4", after_net="",
        attachment=PlanAttachment(
            kind="wire", primitive_id="w-1", detail="d", at=(1.0, 2.0),
        ),
    ).to_jsonable()["change"]
    assert set(disconnect) == PLAN_KEYS["change"]["patch-pin"] | {"attachment"}

    connect = patch_pin_plan(
        SOURCE, designator="U3", pin="5", before_net="", after_net="GND",
        connection=CONNECTION_WIRE, connection_detail="d", to=(5.0, 0.0),
    ).to_jsonable()["change"]
    assert set(connect) == PLAN_KEYS["change"]["patch-pin"]
    assert "attachment" not in connect


def test_the_five_kinds_share_the_three_keys_every_consumer_reads():
    """`primitiveId` / `designator` / `expectedValue` are on every kind's target.

    016's three keys are what `edit preview`, `edit apply`'s page guard and the
    report all read before they look at anything kind-specific, so a kind that
    dropped one would break the shared half of the contract, not its own.
    """
    for kind, plan in _plans().items():
        assert {"primitiveId", "designator", "expectedValue"} <= set(plan.to_jsonable()["target"]), kind


def test_the_nested_plan_shapes_are_pinned_per_kind():
    """The sub-objects, so a key cannot move inside `part` / `moves` unnoticed."""
    plans = _plans()
    add = plans["add-component"].to_jsonable()["change"]
    assert set(add["part"]) == {"lcsc", "value", "footprint"}
    assert set(add["connections"][0]) == {"pin", "net", "kind", "detail", "to"}

    disconnect = patch_pin_plan(
        SOURCE, designator="U3", pin="4", before_net="NET4", after_net="",
        attachment=PlanAttachment(
            kind="wire", primitive_id="w-1", detail="d", at=(1.0, 2.0),
        ),
    ).to_jsonable()["change"]
    assert set(disconnect["attachment"]) == {"kind", "primitiveId", "detail", "at"}

    insert = plans["insert-subcircuit"].to_jsonable()["change"]
    assert set(insert["parts"][0]) == {
        "designator", "role", "lcsc", "value", "footprint", "x", "y", "rotation",
    }

    move = plans["move-block"].to_jsonable()["change"]
    assert set(move["moves"][0]) == {"designator", "primitiveId", "from", "to"}
    assert set(move["moves"][0]["from"]) == {"x", "y", "rotation"}
    assert set(move["moves"][0]["to"]) == {"x", "y"}
    assert set(move["islands"][0]) == {"pin", "mates"}


def test_a_plan_serialises_without_none_noise_or_private_keys():
    """Same rule as the finding side: empty is empty, and nothing private leaks.

    `to` / `attachment` / `recipients`-style optional keys are *omitted* when
    they have nothing to say (016's round-trip tests depend on it), which is a
    different shape from carrying a `None`; this pins both halves of that.
    """
    def walk(payload: object, where: str) -> list[str]:
        problems: list[str] = []
        if isinstance(payload, dict):
            for key, value in payload.items():
                if key.startswith("_"):
                    problems.append(f"{where}.{key} is private")
                if value is None:
                    problems.append(f"{where}.{key} is None")
                problems.extend(walk(value, f"{where}.{key}"))
        elif isinstance(payload, list):
            for index, item in enumerate(payload):
                problems.extend(walk(item, f"{where}[{index}]"))
        return problems

    for kind, plan in _plans().items():
        assert walk(plan.to_jsonable(), kind) == []
