"""540B3: one shared decap inventory/decision, with review wrappers intact."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from boardwise.core import decap
from boardwise.engines import addcomponent
from boardwise.rules import decap as review_decap

from test_540_shared_naming import PACKAGE, _in_package_imports
import test_owner_rules

ROOT = Path(__file__).resolve().parents[1]


def test_historical_import_surfaces_are_the_same_objects():
    assert review_decap.CapCandidate is decap.CapCandidate
    assert review_decap.CapDecision is decap.CapDecision
    assert review_decap.looks_like_capacitor is decap.looks_like_capacitor
    assert review_decap.candidate_farads is decap.candidate_farads
    assert review_decap.recovered_capacitance is decap.recovered_capacitance
    assert review_decap.recovered_farads is decap.recovered_farads
    assert review_decap.value_source_label is decap.value_source_label
    assert review_decap.cap_candidates_on is decap.cap_candidates_on
    assert review_decap.decide_required_cap is decap.decide_required_cap
    assert review_decap.VALUE_SOURCE_SCHEMATIC == decap.VALUE_SOURCE_SCHEMATIC
    assert review_decap.VALUE_SOURCE_SHELF == decap.VALUE_SOURCE_SHELF
    assert review_decap.VALUE_SOURCE_MPN == decap.VALUE_SOURCE_MPN
    assert review_decap.VALUE_SOURCES_RECOVERED is decap.VALUE_SOURCES_RECOVERED
    assert addcomponent.CapCandidate is decap.CapCandidate
    assert addcomponent.CapDecision is decap.CapDecision
    assert addcomponent.cap_candidates_on is decap.cap_candidates_on
    assert addcomponent.decide_required_cap is decap.decide_required_cap


def test_core_decap_imports_only_shared_modules():
    targets = _in_package_imports(PACKAGE / "core" / "decap.py")
    assert targets == {
        "core/model.py", "core/partkind.py", "core/parts.py", "core/values.py",
    }


def test_owner_manifest_has_no_legacy_edges_after_b3():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["batch"] == "540B6"
    assert data["modules"]["core/decap.py"] == "shared"
    assert test_owner_rules.LEGACY_EDGES == frozenset()


def test_one_decision_serves_review_and_addcomponent():
    candidate = decap.CapCandidate(designator="C1", value="100nF", grounded=True)
    farads = decap.candidate_farads(candidate)
    assert farads is not None
    expected = decap.CapDecision(
        "satisfied",
        required_farads=farads,
        required_text="100nF",
        cap_designator="C1",
        cap_farads=farads,
    )
    component = SimpleNamespace(
        designator="C1", value="100nF", mpn="", lcsc_part="", footprint="",
        props={}, pins=[SimpleNamespace(net="VCC"), SimpleNamespace(net="GND")],
    )
    model = SimpleNamespace(
        components={"C1": component},
        nets={"VCC": SimpleNamespace(pins=[("C1", "1")])},
    )
    assert decap.decide_required_cap("100nF", [candidate]) == expected
    assert review_decap.decide_required_cap(
        "100nF", review_decap.cap_candidates_on(model, "VCC")
    ) == expected
    assert addcomponent.probe_already_applied(model, "VCC", "100nF") == expected
    assert expected.satisfied is True
