"""The golden-corrections sidecar: applied, reported, and never silent.

§G.3 of the task book: the fixture `ch340_golden.epro2` is evidence and must
not be edited — even where it is known to be wrong (U3's `1kΩ` is 岳翔宇's own
long-standing mistake; the correct value is 2.2kΩ 0805). Corrections therefore
live in `<fixture stem>.overrides.json`, and the properties worth pinning are
that they actually reach the model, that the provenance travels with them, and
that a sidecar naming a designator the board does not have is reported rather
than ignored.
"""

from __future__ import annotations

import json

import pytest

from boardwise.core.model import Component, DesignModel
from boardwise.core.overrides import (
    apply_overrides,
    load_overrides,
    sidecar_path_for,
)


def test_sidecar_sits_beside_the_fixture_without_touching_it(tmp_path):
    golden = tmp_path / "ch340_golden.epro2"
    assert sidecar_path_for(golden) == tmp_path / "ch340_golden.overrides.json"
    # naming the sidecar must not create or move anything
    assert not golden.exists()


def test_missing_sidecar_is_not_an_error(tmp_path):
    applied = load_overrides(tmp_path / "nothing.overrides.json")
    assert not applied.active
    assert applied.items == []


def test_a_bad_sidecar_says_so_instead_of_being_ignored(tmp_path):
    bad = tmp_path / "x.overrides.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not readable JSON"):
        load_overrides(bad)


def test_overrides_reach_the_model_and_carry_their_provenance(tmp_path):
    sidecar = tmp_path / "g.overrides.json"
    sidecar.write_text(json.dumps({
        "components": {
            "U3": {
                "value": "2.2kΩ",
                "expect_footprint": "0805",
                "provenance": "岳翔宇 2026-09-15: 黄金的 1kΩ 是人为错误",
            },
            "R24": {
                "place_device_uuid": "aaaa",
                "place_library_uuid": "bbbb",
                "provenance": "must be a real 0402",
            },
        }
    }, ensure_ascii=False), encoding="utf-8")

    applied = load_overrides(sidecar)
    assert applied.active
    assert len(applied.items) == 2

    model = DesignModel()
    model.components["U3"] = Component(uid="u3", designator="U3", value="1kΩ")
    model.components["R24"] = Component(uid="r24", designator="R24", value="5.1K")

    lines = apply_overrides(model, applied)

    assert model.components["U3"].value == "2.2kΩ"
    assert model.components["U3"].props["expect_footprint"] == "0805"
    assert model.components["R24"].props["place_device_uuid"] == "aaaa"
    assert model.components["R24"].props["place_library_uuid"] == "bbbb"
    # the report must show the old value *and* the authority for the change
    assert any("1kΩ" in line and "2.2kΩ" in line for line in lines)
    assert any("岳翔宇 2026-09-15" in line for line in lines)


def test_a_sidecar_naming_an_absent_designator_is_reported(tmp_path):
    sidecar = tmp_path / "g.overrides.json"
    sidecar.write_text(json.dumps({
        "components": {"U99": {"value": "x", "provenance": "typo"}},
    }), encoding="utf-8")

    applied = load_overrides(sidecar)
    model = DesignModel()
    lines = apply_overrides(model, applied)

    assert applied.unknown == ["U99"]
    assert lines == [], "nothing was applied, so nothing is claimed"


def test_empty_fields_are_not_treated_as_corrections(tmp_path):
    sidecar = tmp_path / "g.overrides.json"
    sidecar.write_text(json.dumps({
        "components": {"U3": {"value": "", "lcsc": None, "provenance": "no-op"}},
    }), encoding="utf-8")

    applied = load_overrides(sidecar)
    assert applied.items[0].fields == {}, "an empty string is not a correction"
