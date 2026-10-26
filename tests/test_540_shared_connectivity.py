"""540B2: one shared pin-connectivity reading for review and pin repair.

The five cases are the frozen pre-B2 oracle, recorded here rather than read from
an ignored evidence file: auto net, named net, shared net, no net and the host's
``$57N2`` spelling.  Public compatibility is by object identity, not a second
implementation with merely similar answers.

Section 3 (540B fix) pins the authority question those five cannot see, because
each of them hands in the model's own component: a component the model does not
(or no longer) holds must be judged on **its own pins**, and the ruling's repair
target must name the same net as its verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core import connectivity
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry
from boardwise.engines import patchpin
from boardwise.rules import facts

from test_540_shared_naming import PACKAGE, _in_package_imports
import test_owner_rules

ROOT = Path(__file__).resolve().parents[1]


def _model(net_name, members):
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1",
        designator="U1",
        pins=[Pin("2", "2", None), Pin("3", "3", None)],
    )
    model.components["R1"] = Component(
        uid="r1", designator="R1", pins=[Pin("1", "1", None)]
    )
    for name, pins in members.items():
        model.nets[name] = Net(name, list(pins))
        for designator, number in pins:
            for item in model.components[designator].pins:
                if item.number == number:
                    item.net = name
    return model


def test_historical_import_surfaces_are_the_same_callables():
    assert facts.nc_violation is connectivity.nc_violation
    assert facts.pin_dangles is connectivity.pin_dangles
    assert facts.pin_company is connectivity.pin_company
    assert patchpin.pin_net is connectivity.pin_net


def test_the_shared_module_imports_only_shared_model_and_vocabulary():
    assert _in_package_imports(PACKAGE / "core" / "connectivity.py") == {
        "core/model.py", "core/netdomains.py",
    }


def test_owner_manifest_has_no_legacy_edges_after_b3():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["batch"] == "540B6"
    assert data["modules"]["core/connectivity.py"] == "shared"
    assert test_owner_rules.LEGACY_EDGES == frozenset()


CASES = [
    (
        "1-auto-net",
        "NET7",
        {"NET7": [("U1", "2")]},
        "2",
        "NET7",
        (False, "touches no net (alone on 'NET7')"),
        (True, "touches no net (alone on 'NET7')"),
        [],
        "",
    ),
    (
        "2-named-net",
        "NCNET",
        {"NCNET": [("U1", "2")]},
        "2",
        "NCNET",
        (True, "sits alone on the named net 'NCNET'"),
        (False, "sits alone on the named net 'NCNET'"),
        [],
        "U1 pin2 is still connected — it sits alone on the named net 'NCNET'",
    ),
    (
        "3-shared-net",
        "SIG",
        {"SIG": [("U1", "3"), ("R1", "1")]},
        "3",
        "SIG",
        (True, "sits on net 'SIG' with R1.1"),
        (False, "sits on net 'SIG' with R1.1"),
        [("R1", "1")],
        "U1 pin3 is still connected — it sits on net 'SIG' with R1.1",
    ),
    (
        "4-no-net",
        None,
        {},
        "2",
        None,
        (False, "touches no net"),
        (True, "touches no net"),
        [],
        "",
    ),
    (
        "5-host-auto-net",
        "$57N2",
        {"$57N2": [("U1", "2")]},
        "2",
        "$57N2",
        (False, "touches no net (alone on '$57N2')"),
        (True, "touches no net (alone on '$57N2')"),
        [],
        "",
    ),
]


@pytest.mark.parametrize(
    "case_id, net_name, members, pin, expected_net, nc, dangles, company, readback",
    CASES,
    ids=[case[0] for case in CASES],
)
def test_frozen_nc_and_readback_behaviour(
    case_id, net_name, members, pin, expected_net, nc, dangles, company, readback
):
    model = _model(net_name, members)
    component = model.components["U1"]
    assert connectivity.pin_net(model, "U1", pin) == expected_net
    assert connectivity.nc_violation(model, component, pin) == nc
    assert facts.nc_violation(model, component, pin) == nc
    assert connectivity.pin_dangles(model, component, pin) == dangles
    assert facts.pin_dangles(model, component, pin) == dangles
    assert connectivity.pin_company(model, component, pin) == company
    assert facts.pin_company(model, component, pin) == company
    assert patchpin.readback_verdict(
        model, designator="U1", pin=pin, before_net="OLD", after_net=""
    ) == readback


# ---------------------------------------------------------------------------
# 3. B2 fix: the component the caller holds is the authority
#
# The first cut of the move read the pin's net back off `model.components`,
# keyed by designator.  Every frozen case above hands in the model's own object,
# so all five passed while a component the model did not (or no longer) held
# answered 「touches no net」 — a **declared-NC false pass**.  These four cases
# are that gap: detached, key-mismatched, a stale copy, and the attached
# control that must keep the frozen answer.
# ---------------------------------------------------------------------------


def _nc_entry(pin: str = "1"):
    """A shelf entry declaring ``pin`` not-connected (the NC obligation)."""
    return PartEntry(key="U1", facts={"nc_pins": {"pins": [pin]}})


def _nc_board():
    """``GND`` shared by U1.1 and C1.2, plus a U1 object the model does not own."""
    model = DesignModel()
    model.nets["GND"] = Net("GND", [("U1", "1"), ("C1", "2")])
    held = Component(uid="u1", designator="U1", pins=[Pin("1", "1", "GND")])
    return model, held


def _nc_ruling(model, comp, pin="1", net="GND"):
    ruling = facts.pin_ruling(comp, _nc_entry(pin), model, pin)
    assert ruling.state == facts.PIN_VIOLATION
    # The judgement and the repair target must name the *same* net: the one the
    # component handed in actually sits on.
    assert ruling.target.expected_before == connectivity.component_net(comp, pin) == net
    assert ruling.target.net_refs == [net]
    return ruling


def test_facts_pin_net_is_the_shared_reading_not_a_second_copy():
    """Delegation, checked by identity: one implementation, not a lookalike."""
    assert facts._pin_net is connectivity.component_net
    assert facts.component_net is connectivity.component_net
    assert connectivity.__all__[:2] == ["component_net", "pin_net"]


def test_a_detached_component_answers_about_its_own_pins():
    model, held = _nc_board()
    assert "U1" not in model.components
    assert connectivity.component_net(held, "1") == "GND"
    # The model alone cannot answer, which is why the caller's object decides.
    assert connectivity.pin_net(model, "U1", "1") is None
    assert connectivity.pin_company(model, held, "1") == [("C1", "2")]
    assert connectivity.nc_violation(model, held, "1") == (
        True, "sits on net 'GND' with C1.2"
    )
    assert connectivity.pin_dangles(model, held, "1") == (
        False, "sits on net 'GND' with C1.2"
    )
    ruling = _nc_ruling(model, held)
    assert "GND" in ruling.message


def test_a_component_under_a_different_key_still_answers_about_itself():
    model, held = _nc_board()
    model.components["U1X"] = held  # the dict key is not the designator
    assert connectivity.pin_net(model, "U1", "1") is None
    assert connectivity.nc_violation(model, held, "1")[0] is True
    assert connectivity.pin_company(model, held, "1") == [("C1", "2")]
    _nc_ruling(model, held)


def test_a_stale_copy_is_judged_on_its_own_pins_not_the_models():
    model, held = _nc_board()  # the copy under judgement says GND
    model.components["U1"] = Component(
        uid="u1", designator="U1", pins=[Pin("1", "1", "OLD")]
    )
    assert connectivity.pin_net(model, "U1", "1") == "OLD"  # the model disagrees
    assert connectivity.nc_violation(model, held, "1") == (
        True, "sits on net 'GND' with C1.2"
    )
    ruling = _nc_ruling(model, held)
    # A repair built from this ruling must not be told to leave OLD: that net is
    # not what the judged object sits on, and the frozen verdict proves it.
    assert "OLD" not in ruling.message
    assert ruling.target.expected_before == "GND"


def test_an_attached_component_keeps_the_frozen_answer_and_one_net():
    model = _model("SIG", {"SIG": [("U1", "3"), ("R1", "1")]})
    component = model.components["U1"]
    assert (
        connectivity.pin_net(model, "U1", "3")
        == connectivity.component_net(component, "3")
        == "SIG"
    )
    assert connectivity.nc_violation(model, component, "3") == (
        True, "sits on net 'SIG' with R1.1"
    )
    ruling = _nc_ruling(model, component, "3", net="SIG")
    assert ruling.target.expected_before == "SIG"
