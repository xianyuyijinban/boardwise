"""`boardwise edit` (task 016): plan / preview / apply, and the `target` the
review report grew.

Three things are pinned here, each where it lives:

* **the report's new field** — `Finding.target` is threaded from the one rule
  that fills it, `param-value-mpn-match`, and the *other* fourteen rules are
  unchanged because `findings_from` still takes pairs. The suggested value must
  survive a round trip through the value parsers, or a repair would write a
  value the rule cannot read back;
* **the plan** — the ChangePlan schema, what it refuses, and the offline
  preview that compares it against the snapshot's sha256;
* **the command** — `edit apply` against a **stub daemon**: no socket, no
  editor. The stub is faithful where it matters (the attribute write updates
  what the next `sch.geometry` reports, so a broken read-back cannot pass) and
  it is what lets the four protections be asserted as *counts*: a refused
  precondition must mean **zero** writes, an applied change exactly one, with
  exactly one key.

The eval-harness regression also lives here: `render_json`/`Finding` gained a
field, and pairing must keep reading only `evidence` and `message`.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from boardwise.bridge.protocol import BridgeError, ErrorCodes
from boardwise.cli import (
    EDIT_COMMANDS,
    EDIT_WRITE_KEY,
    REPAIRABLE_RULES,
    UNKNOWN_OUTCOME_CODES,
    _cmd_edit_apply,
    _cmd_edit_plan,
    _cmd_edit_preview,
    _edit_post_review,
    build_parser,
    same_board_value,
)
from boardwise.core.annotations import annotations_from_json
from boardwise.core.changeplan import (
    COMPONENT_VALUE_KIND,
    ChangePlan,
    ChangePlanError,
    PlanSource,
    component_value_plan,
    resolve_on_page,
    sha256_of,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartLibrary
from boardwise.engines.review import render_json
from boardwise.engines.review_eval import evaluate_annotations
from boardwise.parsers.schematic import build_schematic_model
from boardwise.rules.base import Finding, FindingTarget, Rule
from boardwise.rules.params import ValueMpnMatch, _human_value
from boardwise.rules.values import (
    decode_eia_3digit,
    parse_capacitance_farads,
)
from boardwise.rules.connectivity import parse_resistance_ohms

ROOT = Path(__file__).resolve().parents[1]
INJECTED = ROOT / "reviewsets" / "injected"
#: The injected board: U3 is 4.7kΩ against an MPN that decodes to 1k — the
#: one fixture defect this slice can repair.
MISMATCH = INJECTED / "value-mpn-mismatch.epro2"
#: The same board with the oracle's corrections applied (U3 = 1kΩ, so the rule
#: says OK) — the "after the change" snapshot the re-review is tested against.
FIXED = INJECTED / "fixed-base.epro2"
DUPLICATE = INJECTED / "duplicate-designator.epro2"
#: The connector version `edit plan` stamps on a plan: the in-repo manifest's
#: own version, read rather than pinned so a bump cannot leave this test
#: asserting last release's number.
CONNECTOR_MANIFEST_VERSION = json.loads(
    (ROOT / "connector" / "extension.json").read_text(encoding="utf-8")
)["version"]

#: Measured from the fixture's own SCH_PAGE document head; the plan must carry
#: the file's page, not a guess.
FIXTURE_PAGE_UUID = "6e27da4006bdba32"
FIXTURE_HOST_VERSION = "3.2.149.88089769"


def _plan_args(*extra: str):
    return build_parser().parse_args(["edit", "plan", *extra])


def _preview_args(*extra: str):
    return build_parser().parse_args(["edit", "preview", *extra])


def _apply_args(*extra: str):
    return build_parser().parse_args(["edit", "apply", *extra])


def _write_plan(tmp_path: Path, snapshot: Path = MISMATCH, *extra: str):
    """Run `edit plan` against the fixture and return its exit code + file."""
    out = tmp_path / "plan.json"
    code = _cmd_edit_plan(
        _plan_args(
            "--file", str(snapshot), "--rule", "param-value-mpn-match",
            "--designator", "U3", "-o", str(out), *extra,
        )
    )
    return code, out


def _plan_payload(*, before="4.7kΩ", after="1k", kind=COMPONENT_VALUE_KIND,
                  sha="a" * 64, **overrides) -> dict:
    payload = {
        "planVersion": 1,
        "source": {
            "inputSha256": sha, "projectUuid": "", "pageUuid": FIXTURE_PAGE_UUID,
            "hostVersion": FIXTURE_HOST_VERSION, "connectorVersion": "0.4.10",
        },
        "target": {"primitiveId": "", "designator": "U3", "expectedValue": before},
        "change": {"kind": kind, "before": before, "after": after},
        "preconditions": ["pageUuid still focused", "designator resolves", f"Value is still {before}"],
        "expectedPostcondition": [f"Value reads back as {after}", "target review finding is resolved"],
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# 1-4: the plan, from the fixture
# --------------------------------------------------------------------------


def test_plan_states_every_field_of_the_schema(tmp_path, capsys):
    code, path = _write_plan(tmp_path)
    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(path.read_text(encoding="utf-8"))
    # The hash is computed independently of `sha256_of` on purpose: a
    # self-consistent helper would agree with itself about a wrong file.
    assert payload["source"]["inputSha256"] == hashlib.sha256(
        MISMATCH.read_bytes()
    ).hexdigest()
    assert payload["planVersion"] == 1
    assert payload["source"]["pageUuid"] == FIXTURE_PAGE_UUID
    assert payload["source"]["hostVersion"] == FIXTURE_HOST_VERSION
    assert payload["source"]["connectorVersion"] == CONNECTOR_MANIFEST_VERSION
    # Measured: a .epro2 carries no project uuid, and the plan says so instead
    # of inventing one.
    assert payload["source"]["projectUuid"] == ""
    assert payload["target"] == {
        "primitiveId": "", "designator": "U3", "expectedValue": "4.7kΩ",
    }
    assert payload["change"] == {
        "kind": "component-value", "before": "4.7kΩ", "after": "1k",
    }
    assert payload["preconditions"] == [
        f"pageUuid {FIXTURE_PAGE_UUID} is still the focused page",
        "designator U3 still resolves on the page",
        "Value is still 4.7kΩ",
    ]
    assert payload["expectedPostcondition"] == [
        "Value reads back as 1k", "target review finding is resolved",
    ]
    assert "projectUuid is empty" in out, "the downgrade is stated, not silent"


def test_after_overrides_the_findings_own_suggestion(tmp_path):
    code, path = _write_plan(tmp_path, MISMATCH, "--after", "2.2k")
    assert code == 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["change"] == {
        "kind": "component-value", "before": "4.7kΩ", "after": "2.2k",
    }


def test_an_unknown_rule_is_refused_with_the_known_ids(tmp_path, capsys):
    code = _cmd_edit_plan(
        _plan_args("--file", str(MISMATCH), "--rule", "no-such-rule",
                   "--designator", "U3")
    )
    err = capsys.readouterr().err
    assert code == 5, err
    assert "no rule with id 'no-such-rule'" in err
    assert "param-value-mpn-match" in err, "the known ids are the fix"


def test_a_rule_without_a_target_is_refused_by_name(tmp_path, capsys):
    code = _cmd_edit_plan(
        _plan_args("--file", str(MISMATCH), "--rule", "param-led-current",
                   "--designator", "U3")
    )
    err = capsys.readouterr().err
    assert code == 5, err
    assert "param-led-current" in err
    assert "该规则不支持自动修改" in err
    # 029-a grew the table: `decap-required-caps` is repairable now (it adds a
    # part, so its plan needs a report and a live page rather than this offline
    # path). The assertion keeps its point — the table is the contract, and a
    # rule that is not in it is refused by name above.
    assert REPAIRABLE_RULES == {
        "param-value-mpn-match": "component-value",
        "decap-required-caps": "add-component",
    }


def test_a_designator_with_no_violation_says_so_with_the_outcomes(tmp_path, capsys):
    code = _cmd_edit_plan(
        _plan_args("--file", str(MISMATCH), "--rule", "param-value-mpn-match",
                   "--designator", "R24")
    )
    err = capsys.readouterr().err
    assert code == 5, err
    assert "no VIOLATION for R24" in err
    assert "UNKNOWN: R24" in err, "the rule's own reason for its silence"


def test_a_duplicate_designator_is_refused_rather_than_guessed(tmp_path, capsys):
    # duplicate-designator.epro2 carries R24 twice (011c's CONN-1 shape).
    code = _cmd_edit_plan(
        _plan_args("--file", str(DUPLICATE), "--rule", "param-value-mpn-match",
                   "--designator", "R24")
    )
    err = capsys.readouterr().err
    assert code == 5, err
    assert "duplicate designator" in err
    assert "不猜是哪一块" in err


def test_a_designator_that_is_not_in_the_file_is_refused(tmp_path, capsys):
    code = _cmd_edit_plan(
        _plan_args("--file", str(MISMATCH), "--rule", "param-value-mpn-match",
                   "--designator", "U9")
    )
    assert code == 5
    assert "no component with designator 'U9'" in capsys.readouterr().err


def test_a_plan_that_changes_nothing_is_refused(tmp_path, capsys):
    code, _ = _write_plan(tmp_path, MISMATCH, "--after", "4.7kΩ")
    assert code == 5
    assert "equals the current value" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 5: the finding's target, threaded from the one rule that produces it
# --------------------------------------------------------------------------


def test_the_violation_row_carries_a_target_and_the_other_rows_do_not():
    model = build_schematic_model(str(MISMATCH))
    rule = ValueMpnMatch()
    findings = rule.check(model)

    assert len(findings) == 1, "only U3 violates"
    target = findings[0].target
    assert target is not None
    assert target.component_ref == "U3"
    assert target.expected_before == "4.7kΩ"
    assert target.suggested_after == "1k"
    # Empty by construction, not by oversight: the primitiveId only exists on
    # the editor's canvas (§2.3), and a value change touches no connection.
    assert target.primitive_id == ""
    assert target.pin_refs == [] and target.net_refs == []

    # The suggestion closes the loop the rule itself measures: it parses back
    # to the MPN's decoded quantity inside the rule's own tolerance.
    decoded = decode_eia_3digit("102", 1.0)
    assert decoded == 1000.0
    assert abs(parse_resistance_ohms(target.suggested_after) - decoded) <= 1e-3 * decoded

    # OK/UNKNOWN rows produce no finding at all, exactly as before: every other
    # subject in the four-state table stays silent.
    states = {outcome.subject: outcome.state for outcome in rule.outcomes(model)}
    assert states["U3"] == "VIOLATION"
    assert states["R24"] == "UNKNOWN" and states["C6"] == "OK"
    assert [f.rule_id for f in findings] == ["param-value-mpn-match"]


def test_every_suggested_value_round_trips_through_its_own_parser():
    """The whole EIA code space, both kinds: a suggestion the parser cannot
    read back would make the repair loop unable to close."""
    for mantissa in range(10, 100):
        for exponent in range(10):
            code = f"{mantissa}{exponent}"
            for kind, base, parser in (
                ("resistor", 1.0, parse_resistance_ohms),
                ("capacitor", 1e-12, parse_capacitance_farads),
            ):
                decoded = decode_eia_3digit(code, base)
                text = _human_value(decoded, kind)
                read = parser(text)
                assert read is not None, (kind, code, text)
                assert abs(read - decoded) <= 1e-3 * decoded, (
                    kind, code, text, decoded, read
                )


def test_a_hand_built_model_threads_one_target_per_contradiction():
    """No library and no fixture: the rule's own arithmetic decides the
    suggestion, for both kinds and their two different tolerances."""
    model = DesignModel()
    for designator, value, mpn in (
        ("R1", "4.7k", "FRC0805J102 TS"),   # 4700 vs 1000 = 4.7x: a resistor
        ("C1", "100nF", "CC0805J102"),      # 100 nF vs 1 nF = 100x: a capacitor
        ("R2", "1k", "FRC0805J102 TS"),     # agrees with its MPN: no finding
    ):
        model.components[designator] = Component(
            uid=designator, designator=designator, value=value, mpn=mpn,
        )
    rule = ValueMpnMatch(library=PartLibrary(parts=[]))
    targets = {finding.target.component_ref: finding.target
               for finding in rule.check(model)}
    assert set(targets) == {"R1", "C1"}
    assert targets["R1"].expected_before == "4.7k"
    assert targets["R1"].suggested_after == "1k"
    assert targets["C1"].expected_before == "100nF"
    assert targets["C1"].suggested_after == "1nF"
    assert {o.subject: o.state for o in rule.outcomes(model)} == {
        "R1": "VIOLATION", "C1": "VIOLATION", "R2": "OK",
    }


# --------------------------------------------------------------------------
# 6: the plan's own validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda p: p["source"].__setitem__("inputSha256", "abc"), "64 hex"),
        (lambda p: p["source"].__setitem__("inputSha256", "z" * 64), "64 hex"),
        (lambda p: p["change"].__setitem__("kind", "patch-pin"), "patch-pin"),
        (lambda p: p["change"].__setitem__("after", p["change"]["before"]), "changes nothing"),
        (lambda p: p.__setitem__("planVersion", 2), "planVersion"),
        (lambda p: p["change"].__setitem__("after", ""), "empty"),
        (lambda p: p["target"].__setitem__("designator", "  "), "designator"),
        (lambda p: p.__setitem__("source", []), "source must be a JSON object"),
        (lambda p: p.__setitem__("preconditions", "nope"), "list of strings"),
    ],
)
def test_a_plan_this_build_cannot_execute_is_refused(mutate, expected):
    payload = _plan_payload()
    mutate(payload)
    with pytest.raises(ChangePlanError) as excinfo:
        ChangePlan.from_jsonable(payload)
    assert expected in str(excinfo.value)


def test_a_bad_kind_says_which_m3_follow_up_owns_it():
    with pytest.raises(ChangePlanError) as excinfo:
        ChangePlan.from_jsonable(_plan_payload(kind="move-block"))
    assert "moving a functional block" in str(excinfo.value)


def test_a_valid_plan_round_trips_through_json(tmp_path):
    payload = _plan_payload()
    plan = ChangePlan.from_jsonable(payload)
    path = tmp_path / "p.json"
    plan.dump(path)
    assert ChangePlan.load(path).to_jsonable() == payload


def test_a_missing_plan_file_is_refused_not_ignored(tmp_path):
    with pytest.raises(ChangePlanError) as excinfo:
        ChangePlan.load(tmp_path / "nope.json")
    assert "cannot be read" in str(excinfo.value)


def test_component_value_plan_states_the_page_guard_it_actually_has():
    with_page = component_value_plan(
        PlanSource(input_sha256="a" * 64, page_uuid="page-1"),
        designator="U3", before="4.7k", after="1k",
    )
    assert with_page.preconditions[0] == "pageUuid page-1 is still the focused page"

    without_page = component_value_plan(
        PlanSource(input_sha256="a" * 64),
        designator="U3", before="4.7k", after="1k",
    )
    assert "no page guard" in without_page.preconditions[0], (
        "a plan with no pageUuid must not claim a guard it does not have"
    )


# --------------------------------------------------------------------------
# 7-8: preview
# --------------------------------------------------------------------------


def test_preview_prints_the_diff_and_the_finding_it_would_silence(tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    capsys.readouterr()
    report = tmp_path / "preview.json"
    code = _cmd_edit_preview(
        _preview_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "U3.Value: 4.7kΩ → 1k" in out
    assert "resolves (1 finding(s) from param-value-mpn-match)" in out
    assert "no geometric diff by construction" in out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["snapshot"] == "fresh"
    assert payload["diff"] == {
        "designator": "U3", "key": "Value", "from": "4.7kΩ", "to": "1k",
    }
    assert payload["resolves"][0]["rule_id"] == "param-value-mpn-match"


def test_preview_refuses_a_stale_snapshot_with_exit_4(tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    stale = tmp_path / "changed.epro2"
    stale.write_bytes(MISMATCH.read_bytes() + b"\n")
    capsys.readouterr()
    code = _cmd_edit_preview(_preview_args(str(plan), "--file", str(stale)))
    err = capsys.readouterr().err
    assert code == 4, err
    assert "快照已失效" in err
    assert sha256_of(stale) != sha256_of(MISMATCH)


def test_preview_refuses_a_target_whose_value_moved(tmp_path, capsys):
    """The sha matches, the designator resolves, the value does not — the
    second half of protection 1, which the hash alone cannot see."""
    code, plan = _write_plan(tmp_path)
    assert code == 0
    payload = json.loads(plan.read_text(encoding="utf-8"))
    payload["source"]["inputSha256"] = sha256_of(FIXED)
    plan.write_text(json.dumps(payload), encoding="utf-8")
    capsys.readouterr()
    code = _cmd_edit_preview(_preview_args(str(plan), "--file", str(FIXED)))
    err = capsys.readouterr().err
    assert code == 4, err
    assert "前置条件失败" in err
    assert "'1kΩ'" in err and "'4.7kΩ'" in err, "both values are quoted"


def test_preview_without_file_refuses_because_it_cannot_check(tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    capsys.readouterr()
    code = _cmd_edit_preview(_preview_args(str(plan)))
    err = capsys.readouterr().err
    assert code == 5, err
    assert "--file is required" in err


# --------------------------------------------------------------------------
# 9-10: apply, against a stub daemon
# --------------------------------------------------------------------------


class _StubEditor:
    """A daemon stub that behaves like a page holding one component.

    Faithful where it matters: ``sch.set_component_attribute`` really updates
    the value the next ``sch.geometry`` reports, so the independent read-back is
    testing something. Anything outside the four actions 016 uses is a bug in
    the caller, not something to answer politely.
    """

    PAGE = FIXTURE_PAGE_UUID
    PRIMITIVE = "pid-u3"
    PROJECT = "proj-1"
    PROJECT_NAME = "test"

    def __init__(self, *, value="4.7kΩ", designator="U3", page=PAGE,
                 primitive=True, value_key=True, extra_keys=None,
                 applied=True, clobbered=None, write_error=None,
                 save_error=None, geometry_error=None, identity=None,
                 identity_error=None):
        self.value = value
        self.designator = designator
        self.page = page
        self.primitive = primitive
        self.value_key = value_key
        self.other = dict(extra_keys or {})
        if value_key:
            self.other["Value"] = value
        self.applied = applied
        self.clobbered = clobbered
        self.write_error = write_error
        self.save_error = save_error
        self.geometry_error = geometry_error
        # `None` means "the editor's two layers agree" — the answer a healthy
        # host gives. A dict replaces it whole (the disagreement / undecidable
        # shapes), an error makes the call fail (an old connector).
        self.identity = identity
        self.identity_error = identity_error
        self.calls = []
        self.params = []
        self.targets: list[dict] = []

    def _identity(self):
        if self.identity is not None:
            return self.identity
        if self.identity_error is not None:
            raise self.identity_error
        project = {
            "projectUuid": self.PROJECT, "name": self.PROJECT_NAME,
            "friendlyName": self.PROJECT_NAME,
        }
        return {
            "focusedProject": dict(project),
            "activeDocument": {
                "uuid": self.page, "type": "page", "tabId": "tab-1",
                "projectUuid": self.PROJECT,
                "project": {
                    **project,
                    "source": "dmt_SelectControl.getCurrentDocumentInfo "
                              "(parentProjectUuid)",
                },
                "source": "dmt_SelectControl.getCurrentDocumentInfo",
            },
            "consistent": True,
            "consistentBasis": "project-uuid",
            "pageUuid": self.page,
            "readOnly": True,
        }

    def _geometry(self):
        state = {"Designator": self.designator}
        if self.other:
            state["OtherProperty"] = dict(self.other)
        return {
            "components": [
                {
                    "primitiveId": self.PRIMITIVE if self.primitive else None,
                    "state": state,
                }
            ],
            "meta": {"available": {"components": True}},
        }

    async def call(self, action, params=None, *, target_project=None, target_instance=None):
        params = params or {}
        self.calls.append(action)
        self.params.append(params)
        # 029-a: `edit`'s flows pass the 023 window hint on every call, so the
        # stub mirrors `BridgeClient.call`'s signature — recording it, because a
        # hint that silently vanishes is exactly the failure 2c spent a batch on.
        self.targets.append({"action": action, "project": target_project, "instance": target_instance})
        if action == "doc.list":
            return {
                "active": {"uuid": self.page, "type": "page"},
                "projects": [{"projectUuid": "proj-1", "focused": True}],
            }
        if action == "sys.identity":
            return self._identity()
        if action == "sch.geometry":
            if self.geometry_error is not None:
                raise self.geometry_error
            return self._geometry()
        if action == "sch.set_component_attribute":
            if self.write_error is not None:
                raise self.write_error
            before = dict(self.other)
            self.other[params["key"]] = params["value"]
            self.value = params["value"]
            payload = {
                "primitiveId": params["primitiveId"],
                "attributes": {params["key"]: params["value"]},
                "mergedKeys": sorted(self.other),
                "applied": self.applied,
                "wrote": True,
                "otherPropertyBefore": before,
                "otherPropertyAfter": dict(self.other),
            }
            if self.clobbered:
                payload["clobberedOtherKeys"] = list(self.clobbered)
            return payload
        if action == "sch.doc.save":
            if self.save_error is not None:
                raise self.save_error
            return {"saved": True}
        raise AssertionError(f"unexpected action {action!r}")

    # The write calls, as a count — the assertion the protections are made of.
    def writes(self):
        return [p for a, p in zip(self.calls, self.params)
                if a == "sch.set_component_attribute"]

    def saves(self):
        return [a for a in self.calls if a == "sch.doc.save"]

    async def close(self):
        pass


@pytest.fixture
def stub_daemon(monkeypatch):
    def install(daemon):
        class Client:
            @classmethod
            async def open(cls, uri, token, role, client=""):
                assert role == "cli"
                return daemon

        monkeypatch.setattr(
            "boardwise.cli._open_cli",
            lambda args: (Client, BridgeError, 61190, "token"),
        )
        return daemon

    return install


def _stale_snapshot(tmp_path: Path, snapshot: Path = MISMATCH) -> Path:
    """A copy of the fixture whose mtime is *older* than the apply run.

    os.utime into the past is how "the editor's save never rewrote this file"
    is simulated without waiting for a clock.
    """
    copy = tmp_path / "stale.epro2"
    copy.write_bytes(snapshot.read_bytes())
    stamp = 1_000_000.0
    os.utime(copy, (stamp, stamp))
    return copy


def _fresh_snapshot(tmp_path: Path, snapshot: Path = FIXED) -> Path:
    """A snapshot written *after* the apply run starts — the save landed."""
    copy = tmp_path / "fresh.epro2"
    copy.write_bytes(snapshot.read_bytes())
    future = 2_000_000_000.0
    os.utime(copy, (future, future))
    return copy


def test_apply_refuses_a_precondition_mismatch_with_zero_writes(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    # Somebody changed the board by hand after the plan was written.
    daemon = stub_daemon(_StubEditor(value="2.2kΩ"))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 4, out
    assert daemon.writes() == [], "a broken precondition must write nothing"
    assert daemon.saves() == []
    assert daemon.calls == ["doc.list", "sys.identity", "sch.geometry"], (
        "nothing but the precondition reads happened"
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["reason"] == "stale_before"
    assert payload["write"]["calls"] == 0
    assert payload["resolved"]["primitiveId"] == _StubEditor.PRIMITIVE
    assert "旧快照失效" in out


def test_apply_recognises_a_value_that_is_already_there(stub_daemon, tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(value="1k"))
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 0, out
    assert daemon.writes() == [], "already_applied must not write again"
    assert daemon.saves() == []
    assert "already_applied" in out


def test_apply_writes_once_reads_back_saves_and_re_reviews(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(value="4.7kΩ", extra_keys={"Tolerance": "1%"}))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(
            str(plan), "--file", str(_fresh_snapshot(tmp_path)),
            "--json", str(report),
        )
    )
    out = capsys.readouterr().out
    assert code == 0, out

    # Exactly one write, and the only key in it is Value (protection 2).
    writes = daemon.writes()
    assert len(writes) == 1
    assert writes[0]["key"] == EDIT_WRITE_KEY
    assert writes[0]["value"] == "1k"
    assert writes[0]["primitiveId"] == _StubEditor.PRIMITIVE
    assert writes[0]["pageUuid"] == FIXTURE_PAGE_UUID
    assert [a for a in daemon.calls if a == "sch.geometry"] == [
        "sch.geometry", "sch.geometry",
    ], "one read before the write and one after"
    assert daemon.saves() == ["sch.doc.save"], "saved exactly once"

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["outcome"] == "applied"
    assert payload["ok"] is True and payload["exitCode"] == 0
    assert payload["projectUuid"] == "proj-1"
    assert payload["page"] == {"uuid": FIXTURE_PAGE_UUID, "guard": "enforced"}
    assert payload["resolved"] == {
        "designator": "U3", "primitiveId": _StubEditor.PRIMITIVE,
        "value": "4.7kΩ", "valueKey": "OtherProperty.Value",
    }
    assert payload["write"]["clobberedOtherKeys"] == []
    assert payload["write"]["mergedKeys"] == ["Tolerance", "Value"]
    assert payload["verification"]["observed"] == "1k"
    assert payload["verification"]["matched"] is True
    assert payload["save"] == {"ok": True, "answered": {"saved": True}}
    assert payload["persistence"] == "saved_unverified"
    assert payload["postReview"]["state"] == "resolved"
    assert payload["postReview"]["value"] == "1kΩ"
    assert [step["action"] for step in payload["steps"]] == [
        "doc.list", "sys.identity", "sch.geometry", "sch.set_component_attribute",
        "sch.geometry", "sch.doc.save",
    ]
    assert all(step["ok"] for step in payload["steps"])


def test_apply_leaves_a_stale_file_unreviewed_rather_than_calling_it_resolved(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    stub_daemon(_StubEditor())
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(_stale_snapshot(tmp_path)))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "re-review: unknown" in out
    assert "保存未落盘或落盘延迟" in out


def test_apply_reports_a_write_whose_outcome_is_unknown_without_retrying(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(write_error=BridgeError(
        ErrorCodes.TIMEOUT, "the connector did not answer in time"
    )))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 3, out
    assert len(daemon.writes()) == 1, "the write is never re-issued"
    assert daemon.calls == ["doc.list", "sys.identity", "sch.geometry",
                            "sch.set_component_attribute", "sch.geometry"], (
        "unknown -> read the page back, then stop"
    )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["outcome"] == "unknown"
    assert payload["reason"] == "write_unknown"
    assert payload["verification"]["afterUnknownWrite"] is True
    assert daemon.saves() == [], "an unknown write is not followed by a save"
    assert "Nothing was retried" in out


def test_apply_fails_when_the_independent_readback_disagrees(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor())
    # A page that accepts the write but does not hold it: the action's own
    # read-back is the only thing that lies, and the independent geometry read
    # is what catches it.
    original = daemon.call

    async def _lying(action, params=None, **hint):
        data = await original(action, params, **hint)
        if action == "sch.set_component_attribute":
            daemon.other["Value"] = daemon.value = "4.7kΩ"
        return data

    daemon.call = _lying
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 2, out
    assert "DID NOT MATCH" in out
    assert daemon.saves() == [], "a change that did not land is not saved"


def test_apply_reports_clobbered_keys_loudly(stub_daemon, tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    stub_daemon(_StubEditor(clobbered=["Tolerance"]))
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "clobbered other keys: ['Tolerance']" in out


def test_apply_survives_the_actions_own_optimism_being_wrong(
    stub_daemon, tmp_path, capsys
):
    """`applied: false` with the value really on the page is a note, not a
    failure: the independent read-back is the authority (§四 protection 3)."""
    code, plan = _write_plan(tmp_path)
    assert code == 0
    stub_daemon(_StubEditor(applied=False))
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "the action's own read-back does not confirm the write" in out
    assert "matched" in out


def test_apply_refuses_a_page_that_states_no_value(stub_daemon, tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(value_key=False, extra_keys={"Tolerance": "1%"}))
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 4, out
    assert "states no Value" in out
    assert daemon.writes() == []


def test_apply_refuses_a_focused_page_that_is_not_the_plans(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(page="another-page"))
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 4, out
    assert daemon.calls == ["doc.list"]
    assert "page_mismatch" in out
    assert daemon.writes() == []


def test_apply_without_a_page_uuid_says_the_guard_is_gone(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    payload = json.loads(plan.read_text(encoding="utf-8"))
    payload["source"]["pageUuid"] = ""
    payload["preconditions"] = [
        "the page the editor has focused is the plan's page", "designator U3 still resolves on the page",
        "Value is still 4.7kΩ",
    ]
    plan.write_text(json.dumps(payload), encoding="utf-8")
    daemon = stub_daemon(_StubEditor())
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "pageUuid guard unavailable, focused page used" in out
    assert "doc.list" not in daemon.calls, "no page to confirm with doc.list"
    assert daemon.calls[:2] == ["sys.identity", "sch.geometry"], (
        "the identity check still runs and still precedes the page read"
    )
    assert "pageUuid" not in daemon.writes()[0], (
        "an empty pageUuid is omitted, not sent as an empty guard"
    )
    assert json.loads(report.read_text(encoding="utf-8"))["page"] == {
        "uuid": "", "guard": "unavailable",
    }


# --------------------------------------------------------------------------
# the two identity layers (018 §B2): the guard that runs before any read
# --------------------------------------------------------------------------


def _identity_disagreement() -> dict:
    """`sys.identity` as the machine reported it on 2026-09-21: `doc.list`
    names one project as focused while the document in front belongs to
    another, and the connector says so instead of picking a winner."""
    return {
        "focusedProject": {
            "projectUuid": "uuid-alpha", "name": "proj-alpha",
            "friendlyName": "proj-alpha",
        },
        "activeDocument": {
            "uuid": FIXTURE_PAGE_UUID, "type": "page", "tabId": "tab-9",
            "projectUuid": "uuid-beta",
            "project": {
                "projectUuid": "uuid-beta", "name": "proj-beta",
                "friendlyName": "proj-beta",
                "source": "dmt_SelectControl.getCurrentDocumentInfo "
                          "(parentProjectUuid)",
            },
            "source": "dmt_SelectControl.getCurrentDocumentInfo",
        },
        "consistent": False,
        "consistentBasis": "project-uuid",
        "pageUuid": FIXTURE_PAGE_UUID,
        "readOnly": True,
    }


def _identity_undecidable() -> dict:
    """`consistent: null` — nothing is focused, so the comparison cannot be
    made at all. Never the same thing as "the comparison passed"."""
    return {
        "focusedProject": None,
        "activeDocument": None,
        "consistent": None,
        "consistentBasis": "no-active-document",
        "pageUuid": None,
        "readOnly": True,
    }


def test_apply_asks_the_identity_layers_before_reading_the_page(
    stub_daemon, tmp_path, capsys
):
    """Agreement is not a note: the flow continues unchanged."""
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor())
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert daemon.calls[:3] == ["doc.list", "sys.identity", "sch.geometry"], (
        "the identity check sits between the page guard and the page read"
    )
    assert len(daemon.writes()) == 1, "an agreeing editor is still written to"
    assert "身份核查" not in out, "agreement is the silence, not a note"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["identity"] == {
        "consistent": True,
        "consistentBasis": "project-uuid",
        "focusedProject": {
            "projectUuid": "proj-1", "name": "test", "friendlyName": "test",
        },
        "activeDocument": {
            "uuid": FIXTURE_PAGE_UUID, "type": "page", "tabId": "tab-1",
            "projectUuid": "proj-1",
            "project": {
                "projectUuid": "proj-1", "name": "test", "friendlyName": "test",
                "source": "dmt_SelectControl.getCurrentDocumentInfo "
                          "(parentProjectUuid)",
            },
            "source": "dmt_SelectControl.getCurrentDocumentInfo",
        },
    }
    assert [step["action"] for step in payload["steps"]][1] == "sys.identity"
    assert payload["steps"][1]["ok"] is True


def test_apply_refuses_when_the_two_identity_layers_disagree(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(identity=_identity_disagreement()))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 4, out
    assert daemon.writes() == [], "a disagreement is a precondition failure: zero writes"
    assert daemon.saves() == []
    assert daemon.calls == ["doc.list", "sys.identity"], (
        "the refusal lands before the page is read, and nothing else was asked"
    )
    # Both layers, each by name and by uuid: the operator has to see which way
    # round they are, not just that something is wrong.
    for text in ("proj-alpha", "uuid-alpha", "proj-beta", "uuid-beta"):
        assert text in out, text
    assert FIXTURE_PAGE_UUID in out, "the active document is named too"
    assert "焦点不一致，请先切换工程再执行" in out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["reason"] == "focus_inconsistent"
    assert payload["exitCode"] == 4
    assert payload["write"]["calls"] == 0
    assert payload["identity"]["consistent"] is False
    assert payload["identity"]["consistentBasis"] == "project-uuid"


def test_apply_degrades_to_the_geometry_guard_when_identity_is_undecidable(
    stub_daemon, tmp_path, capsys
):
    """`consistent: null` means the check could not run — a note, not a refusal."""
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(identity=_identity_undecidable()))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "身份核查无法判定" in out
    assert "no-active-document" in out, "the basis is named, not guessed"
    assert len(daemon.writes()) == 1, "the write still happens, guarded by geometry"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["identity"]["consistent"] is None
    assert payload["identity"]["consistentBasis"] == "no-active-document"


def test_apply_degrades_when_the_connector_does_not_know_sys_identity(
    stub_daemon, tmp_path, capsys
):
    """An old connector (0.4.10) answers UNKNOWN_ACTION — the write must not be
    refused for that; the geometry guard is what protects it."""
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor(identity_error=BridgeError(
        ErrorCodes.UNKNOWN_ACTION, "unknown action 'sys.identity'"
    )))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "身份核查不可用" in out
    assert "UNKNOWN_ACTION" in out
    assert len(daemon.writes()) == 1, "a missing action is not a failed check"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["identity"] == {
        "consistent": None, "consistentBasis": "unavailable",
    }
    assert payload["steps"][1]["action"] == "sys.identity"
    assert payload["steps"][1]["ok"] is False


def test_apply_refuses_an_ambiguous_designator_on_the_page(
    stub_daemon, tmp_path, capsys
):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    daemon = stub_daemon(_StubEditor())
    single = daemon._geometry()
    original = daemon.call

    async def _two(action, params=None, **hint):
        # `**hint`: the flows pass the 023 window hint (029-a) and this wrapper
        # has to forward it, or the stub change would look like a flow bug.
        data = await original(action, params, **hint)
        if action == "sch.geometry":
            data = {"components": single["components"] * 2, "meta": data["meta"]}
        return data

    daemon.call = _two
    capsys.readouterr()
    code = _cmd_edit_apply(_apply_args(str(plan), "--file", str(MISMATCH)))
    out = capsys.readouterr().out
    assert code == 4, out
    assert "target_ambiguous" in out
    assert daemon.writes() == []


def test_apply_reports_a_refused_save_as_not_persisted(stub_daemon, tmp_path, capsys):
    code, plan = _write_plan(tmp_path)
    assert code == 0
    stub_daemon(_StubEditor(save_error=BridgeError(
        ErrorCodes.CONNECTOR_ERROR, "the editor refused to save"
    )))
    report = tmp_path / "apply.json"
    capsys.readouterr()
    code = _cmd_edit_apply(
        _apply_args(str(plan), "--file", str(MISMATCH), "--json", str(report))
    )
    out = capsys.readouterr().out
    assert code == 2, out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["persistence"] == "placed", (
        "the change is on the canvas only; it is not persisted"
    )
    assert payload["save"]["ok"] is False
    assert payload["reason"] == "save_refused"


def test_apply_is_a_usage_error_when_the_plan_is_broken(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"planVersion": 3}), encoding="utf-8")
    code = _cmd_edit_apply(_apply_args(str(bad)))
    assert code == 5
    assert "planVersion" in capsys.readouterr().err


def test_edit_is_reachable_from_the_parser():
    assert set(EDIT_COMMANDS) == {"plan", "preview", "apply"}
    assert build_parser().parse_args(
        ["edit", "plan", "--file", "x", "--rule", "r", "--designator", "U3"]
    ).edit_command == "plan"


def test_the_unknown_outcome_codes_are_the_bridges_codes():
    """The pair that decides "read back, never retry" is the bridge's, not a
    second copy of it that could drift."""
    assert UNKNOWN_OUTCOME_CODES == {ErrorCodes.TIMEOUT, ErrorCodes.DISCONNECTED}


# --------------------------------------------------------------------------
# step 7 on its own, and the value comparison
# --------------------------------------------------------------------------


def test_post_review_resolves_when_the_rule_has_nothing_left_to_say(tmp_path):
    snapshot = _fresh_snapshot(tmp_path)
    result = _edit_post_review(
        str(snapshot), started=0.0, rule_id="param-value-mpn-match",
        designator="U3", view="schematic",
    )
    assert result["state"] == "resolved"
    assert result["findings"] == []
    assert result["value"] == "1kΩ"
    assert any(item["state"] == "OK" for item in result["outcomes"])


def test_post_review_still_present_after_an_unchanged_board(tmp_path):
    snapshot = _fresh_snapshot(tmp_path, MISMATCH)
    result = _edit_post_review(
        str(snapshot), started=0.0, rule_id="param-value-mpn-match",
        designator="U3", view="schematic",
    )
    assert result["state"] == "still_present"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["rule_id"] == "param-value-mpn-match"
    assert any(item["state"] == "VIOLATION" for item in result["outcomes"])


def test_post_review_without_a_file_claims_nothing():
    result = _edit_post_review(
        None, started=0.0, rule_id="param-value-mpn-match", designator="U3",
        view="schematic",
    )
    assert result["state"] == "unknown"
    assert "not claimed" in result["reason"]


def test_same_board_value_separates_a_spelling_from_a_change():
    assert same_board_value("1k", "1k") == (True, "identical")
    assert same_board_value("4.7kΩ", "4.7k") == (True, "same resistance")
    assert same_board_value("100nF", "0.1uF") == (True, "same capacitance")
    assert same_board_value("4.7k", "2.2k")[0] is False
    assert same_board_value("", "1k")[0] is False
    assert same_board_value("1k", "100nF")[0] is False


def test_resolve_on_page_reads_what_the_connector_writes():
    geometry = {
        "components": [
            {"primitiveId": "p1", "state": {"Designator": "U3",
                                            "OtherProperty": {"Value": "4.7kΩ"}}},
            {"primitiveId": "p2", "state": {"Designator": "U3"}},
        ]
    }
    lookup = resolve_on_page(geometry, "u3")
    assert lookup.matching == 2 and lookup.ambiguous
    assert lookup.component.primitive_id == "p1"
    assert lookup.component.value == "4.7kΩ"
    assert lookup.component.value_key == "OtherProperty.Value"
    assert resolve_on_page(geometry, "U9").component is None


# --------------------------------------------------------------------------
# regression: the new field must not touch the 011e/014/015 baseline
# --------------------------------------------------------------------------


class _TargetRule(Rule):
    """One WARN whose evidence and message are configurable, so the same
    finding can be tested with and without a structured target."""

    id = "target-only"
    title = "test rule"
    level = "test"
    source = "house rule"

    def __init__(self, *, target: FindingTarget | None = None,
                 evidence=("nothing here names a component",)) -> None:
        self._target = target
        self._evidence = list(evidence)

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            Finding(
                rule_id=self.id, severity="WARN", level=self.level,
                message="something is wrong on this board",
                evidence=self._evidence,
                target=self._target,
            )
        ]


def _annotated_model() -> DesignModel:
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1", value="widget",
        pins=[Pin("1", "VCC", "VCC")],
    )
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    return model


def _annotation_set():
    return annotations_from_json(
        {
            "schema": "boardwise-review-annotations/1",
            "board": "toy",
            "source": "tests/fixtures/toy.epro2",
            "items": [
                {"ref": "U1", "rule_hint": "target-only", "kind": "defect",
                 "severity": "WARN", "note": "the oracle's record"},
            ],
        },
        "<test>",
    )


def _metrics(evaluation, rule_id):
    return next(m for m in evaluation.metrics if m.rule_id == rule_id)


def test_a_target_does_not_enter_the_eval_pairing():
    """Pairing reads ``evidence`` and ``message`` only — a structured target
    that names a defect is **not** a detection, and no denominator may grow
    because a rule learned to say what it means (016 §五 regression)."""
    unseen = evaluate_annotations(
        _annotation_set(), _annotated_model(),
        [_TargetRule(target=FindingTarget(component_ref="U1"))],
    )
    metrics = _metrics(unseen, "target-only")
    assert metrics.defects_hinted == 1
    assert metrics.detected == 0
    assert metrics.fp_unexplained == 1

    # Positive control: the same finding with U1 in its *evidence* is the
    # detection, so what the test measures is the field, not a dead harness.
    seen = evaluate_annotations(
        _annotation_set(), _annotated_model(),
        [_TargetRule(evidence=["U1 pin1 @ VCC"])],
    )
    assert _metrics(seen, "target-only").detected == 1


def test_the_report_states_a_target_and_stays_compatible():
    payload = json.loads(render_json([
        Finding(
            rule_id="param-value-mpn-match", severity="WARN", level="L2",
            message="U3: board value 4700 Ω contradicts its MPN",
            evidence=["U3 value '4.7kΩ'"],
            target=FindingTarget(
                component_ref="U3", expected_before="4.7kΩ",
                suggested_after="1k",
            ),
        ),
        Finding(rule_id="x", severity="INFO", level="L1", message="m"),
    ]))
    first, second = payload["findings"]
    assert first["target"]["component_ref"] == "U3"
    assert first["refs"] == ["U3"], "refs still read evidence, not the target"
    # Every finding keeps the old keys, and a rule that says nothing new gets
    # `target: null` rather than a missing key.
    for key in ("rule_id", "severity", "message", "level", "evidence", "refs", "target"):
        assert key in second
    assert second["target"] is None
