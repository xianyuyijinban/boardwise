"""Tests for the v2 part-library facts extension (task 011b)."""

from __future__ import annotations

import pytest

from boardwise.core.parts import (
    CATEGORY_VOCABULARY,
    PartError,
    entry_from_json,
    find_facts,
    library_from_json,
    load_parts,
)


def _base_entry(**overrides) -> dict:
    body = {
        "key": "ic.toy",
        "value": "",
        "mpn": "TOY-1",
        "lcsc": "C1234567",
        "manufacturer": "Toy Corp",
        "deviceUuid": "f809d2f6af2d4c2eb58795bc97ecb0d8",
        "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
        "footprint_name": "SOP-16_L9.9-W3.9-P1.27-LS6.0-BL",
        "footprint_name_verified": None,
        "params": {},
        "datasheetUrl": "",
        "datasheetPdfUrl": "",
        "basic": None,
        "provenance": {"kind": "catalog-select", "source": "test", "designators": [], "note": ""},
        "notes": [],
    }
    body.update(overrides)
    return body


DS = "Toy datasheet rev 1, p.4 sec.2, https://example.com/toy.pdf"


def _library(parts: list[dict]) -> dict:
    return {"kind": "boardwise-part-library", "version": 2, "sources": [], "notes": [], "parts": parts}


# --------------------------------------------------------------------------
# category
# --------------------------------------------------------------------------


def test_a_category_outside_the_vocabulary_is_rejected():
    body = _base_entry(category="resister")  # deliberate misspelling
    with pytest.raises(PartError, match="category"):
        entry_from_json(body, "<test>")


def test_every_vocabulary_word_is_accepted():
    for word in sorted(CATEGORY_VOCABULARY):
        entry = entry_from_json(_base_entry(key=f"ic.toy_{word}", category=word), "<test>")
        assert entry.category == word


def test_category_is_optional_and_stays_empty():
    entry = entry_from_json(_base_entry(), "<test>")
    assert entry.category == ""


# --------------------------------------------------------------------------
# facts structure
# --------------------------------------------------------------------------


def test_a_fact_without_provenance_is_rejected():
    facts = {"ldo": {"dropout_max_mv": 400, "condition": "Iout=500mA", "provenance": ""}}
    with pytest.raises(PartError, match="provenance"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_provenance_must_cite_a_page_or_section_not_just_a_url():
    facts = {"ldo": {"dropout_max_mv": 400, "condition": "x",
                     "provenance": "https://example.com/toy.pdf"}}
    with pytest.raises(PartError, match="page, section"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_provenance_must_cite_a_url():
    facts = {"ldo": {"dropout_max_mv": 400, "condition": "x",
                     "provenance": "Toy datasheet rev 1, p.4"}}
    with pytest.raises(PartError, match="URL"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_an_unknown_fact_kind_is_rejected():
    facts = {"crystal_requirements": {"provenance": DS}}
    with pytest.raises(PartError, match="unknown key"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_an_unknown_key_inside_a_fact_is_rejected():
    facts = {"ldo": {"dropout_max_mv": 400, "condition": "x", "provenance": DS,
                     "dropout_typ_mv": 250}}
    with pytest.raises(PartError, match="dropout_typ_mv"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_ranges_must_be_pairs_of_numbers():
    for bad in ([1.0], [1.0, 2.0, 3.0], ["1", "2"], [True, 2.0], [5.0, 1.0]):
        facts = {"supply_pins": [{"pins": ["1"], "name": "VIN",
                                  "v_operating": bad, "provenance": DS}]}
        with pytest.raises(PartError, match="range"):
            entry_from_json(_base_entry(facts=facts), "<test>")


def test_a_one_sided_range_may_use_null_for_the_unstated_bound():
    # Measured: the RT9013 datasheet gives a 6V upper abs-max and no lower
    # one. An invented 0 would be a claim; null is its absence.
    facts = {"supply_pins": [{"pins": ["1"], "name": "VIN",
                              "v_abs_max": [None, 6.0], "provenance": DS}]}
    entry = entry_from_json(_base_entry(facts=facts), "<test>")
    assert entry.facts["supply_pins"][0]["v_abs_max"] == [None, 6.0]


def test_pin_numbers_must_be_strings():
    facts = {"nc_pins": {"pins": [4], "provenance": DS}}
    with pytest.raises(PartError, match="pin number"):
        entry_from_json(_base_entry(facts=facts), "<test>")


def test_facts_round_trip_through_json():
    facts = {
        "supply_pins": [{"pins": ["1"], "name": "VIN",
                         "v_operating": [2.2, 5.5], "provenance": DS}],
        "nc_pins": {"pins": ["4"], "provenance": DS},
        "ldo": {"dropout_max_mv": 400, "condition": "Iout=500mA", "provenance": DS},
    }
    entry = entry_from_json(_base_entry(facts=facts, category="ic.ldo"), "<test>")
    reloaded = entry_from_json(entry_to := __import__("boardwise.core.parts", fromlist=["entry_to_json"]).entry_to_json(entry), "<rt>")
    assert reloaded.facts == facts
    assert reloaded.category == "ic.ldo"


def test_an_entry_without_facts_writes_no_category_or_facts_keys():
    from boardwise.core.parts import entry_to_json

    body = entry_to_json(entry_from_json(_base_entry(), "<test>"))
    assert "category" not in body and "facts" not in body


# --------------------------------------------------------------------------
# find_facts: exact identity only
# --------------------------------------------------------------------------


def _shelf() -> object:
    parts = [
        _base_entry(key="ic.rt9013_33gb", mpn="RT9013-33GB", lcsc="C47773",
                    facts={"ldo": {"dropout_max_mv": 400, "condition": "Iout=500mA",
                                   "provenance": DS}}),
        _base_entry(key="ic.ch340g", mpn="CH340G", lcsc="C14267"),
    ]
    return library_from_json(_library(parts), "<test>")


def test_find_facts_hits_by_mpn_then_by_lcsc():
    library = _shelf()
    assert find_facts(library, mpn="RT9013-33GB").key == "ic.rt9013_33gb"
    assert find_facts(library, mpn="CH340G").key == "ic.ch340g"
    assert find_facts(library, lcsc="C14267").key == "ic.ch340g"
    assert find_facts(library, mpn="RT9013-33GB", lcsc="C14267").key == "ic.rt9013_33gb"


def test_find_facts_returns_none_and_never_matches_fuzzily():
    library = _shelf()
    assert find_facts(library, mpn="RT9013") is None  # prefix, not exact
    assert find_facts(library, mpn="rt9013-33gb") is None  # case-folded
    assert find_facts(library, lcsc="C4777") is None  # truncated C-number
    assert find_facts(library, mpn="TOY-9") is None
    assert find_facts(library) is None


# --------------------------------------------------------------------------
# the committed library file
# --------------------------------------------------------------------------


def test_the_committed_library_is_v2_with_its_curated_fact_entries():
    library = load_parts("blocklib/parts.json")
    assert library.version == 2
    # 011d added the golden board's LED (C51933293) as a catalog-select entry.
    # 042's re-harvest took the shelf from 94 to 109 entries: the 15 parts the
    # pre-042 parser could not see on ROBOT and the 高速板 (both boards' own PCB
    # lists them) reached the harvest, and three slugs became ambiguous, so the
    # entries sharing them now carry their C-number.
    assert len(library.parts) == 109
    with_facts = sorted(p.key for p in library.parts if p.facts is not None)
    with_category = sorted(p.key for p in library.parts if p.category)
    # 011d sec.1/2 added a fourth: the Type-C receptacle (oracle-approved
    # category + the CC pull_required facts) -- and a fifth, the LED.
    # 039 wave 1 added five more (CH340N, SN65HVD230DR, TLV9062IDR, MPU-6050,
    # REF2033AIDDCR). REF2033 came through one round **gated** (`facts_verified:
    # false`, because the decap rule misread its board); 039 批①b fixed the rule
    # and flipped it, so the category list and the facts list agree again.
    #
    # ``ic.ams1117_3_3`` is spelled ``ic.ams1117_3_3.c6186`` since 042's
    # re-harvest: the shelf now holds that listing *and* ``.c369933`` — two LCSC
    # listings of one MPN. Both carry the curated datasheet facts, because the
    # facts are properties of the part number: the second listing was frozen
    # facts-less for one round, which is what moved the two severity rows in
    # `test_040b_boards`, and the sidecar mirror put them back.
    assert with_facts == [
        "conn.type_c_16pin_2md_073", "ic.ams1117_3_3.c369933",
        "ic.ams1117_3_3.c6186", "ic.ch340g",
        "ic.ch340n", "ic.mpu_6050", "ic.ref2033aiddcr", "ic.rt9013_33gb",
        "ic.sn65hvd230dr", "ic.tlv9062idr", "led.emerald_green_0603",
    ]
    assert with_category == with_facts
    # The two harvested entries gained keys; the 90 others are untouched.
    rt = find_facts(library, mpn="RT9013-33GB")
    assert rt.facts["ldo"]["dropout_max_mv"] == 400
    assert rt.facts["ldo"]["condition"]
    assert "p.3" in rt.facts["ldo"]["provenance"]
    ch = find_facts(library, lcsc="C14267")
    assert ch.category == "ic.usb-uart"
    assert {p["pin"] for p in ch.facts["required_caps"]} == {"4", "16"}
    # 011d sec.2: the CH340G records carry their mode tags, and the V3 pin's
    # 3.3V-mode obligation (tie to VCC) is recorded next to its 5V-mode cap.
    assert [r["mode"] for r in ch.facts["supply_pins"]] == ["5V", "3.3V"]
    v3_caps = [c for c in ch.facts["required_caps"] if c["pin"] == "4"]
    assert [c["mode"] for c in v3_caps] == ["5V"]
    v3_ties = [m for m in ch.facts["must_connect"] if m["pin"] == "4"]
    assert [(m["to"], m["mode"]) for m in v3_ties] == [("VCC", "3.3V")]
    usb = find_facts(library, lcsc="C2765186")
    assert usb.category == "connector"
    assert [(p["pin"], p["to"], p["expected_value"])
            for p in usb.facts["pull_required"]] == [
        ("4", "GND", "5.1k"), ("10", "GND", "5.1k"),
    ]
    # 039 wave 1 in detail: the SOP-8 CH340N is not the SOP-16 CH340G -- its VCC
    # is pin 5, its 3.3V-mode floor is 3.1V (the C/N/K/E/X/B group), and it needs
    # no crystal (an internal clock generator), which is why no must_connect
    # names one.
    n = find_facts(library, mpn="CH340N")
    assert {p["pin"] for p in n.facts["required_caps"]} == {"5", "8"}
    assert n.facts["supply_pins"][1]["v_operating"] == [3.1, 3.6]
    assert all("crystal" not in m["to"] for m in n.facts["must_connect"])
    # ... and the entry that was gated for one round now drives, with the same
    # facts it was held with (the flip is the absence of the flag, which is what
    # `entry_to_json` writes).
    ref = find_facts(library, mpn="REF2033AIDDCR")
    assert ref.category == "ic.reference"
    assert ref.facts_verified is True and ref.candidate_facts is None
    assert {k for k in ref.facts} == {"supply_pins", "required_caps"}
    assert ref.facts["required_caps"][0]["pin"] == "4"
    assert "p.23 sec.11" in ref.facts["required_caps"][0]["provenance"]


def test_facts_mode_tags_survive_the_loader_and_gating():
    """011d sec.2: an optional mode tag on supply_pins / required_caps /
    must_connect records -- present means mode-scoped, absent means
    unconditional; the round-trip must not turn absent into null."""
    body = {
        "kind": "boardwise-part-library",
        "version": 2,
        "parts": [{
            "key": "ic.ch340g", "value": "CH340G", "mpn": "CH340G",
            "lcsc": "C14267",
            "deviceUuid": "f809d2f6af2d4c2eb58795bc97ecb0d8",
            "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
            "category": "ic.usb-uart",
            "facts": {
                "supply_pins": [
                    {"pins": ["16"], "name": "VCC",
                     "v_operating": [4.0, 5.3], "mode": "5V",
                     "provenance": "manual, p.5, http://x/ds.pdf"},
                    {"pins": ["16"], "name": "VCC",
                     "v_operating": [2.9, 3.6],
                     "provenance": "manual, p.5, http://x/ds.pdf"},
                ],
                "required_caps": [
                    {"pin": "4", "value": "0.1uF", "mode": "5V",
                     "provenance": "manual, p.3, http://x/ds.pdf"},
                ],
                "must_connect": [
                    {"pin": "4", "to": "VCC", "mode": "3.3V",
                     "provenance": "manual, p.3, http://x/ds.pdf"},
                ],
            },
        }],
    }
    entry = entry_from_json(body["parts"][0], "<t>")
    supply = entry.facts["supply_pins"]
    assert [r.get("mode") for r in supply] == ["5V", None]
    assert entry.facts["required_caps"][0]["mode"] == "5V"
    assert entry.facts["must_connect"][0]["mode"] == "3.3V"


def test_facts_pull_required_is_whitelisted_and_provenance_gated():
    """011d sec.2: pull_required records carry pin / to / expected_value and
    the same hard provenance gate as every other fact."""
    base = {
        "key": "conn.type_c", "value": "TYPE-C", "mpn": "TYPE-C",
        "lcsc": "C2765186",
        "deviceUuid": "f809d2f6af2d4c2eb58795bc97ecb0d8",
        "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
        "category": "connector",
    }
    good = {**base, "facts": {"pull_required": [{
        "pin": "4", "to": "GND", "expected_value": "5.1k",
        "provenance": "ST AN5225 Table 6, http://x/ds.pdf",
    }]}}
    assert entry_from_json(good, "<t>").facts["pull_required"][0][
        "expected_value"] == "5.1k"
    # Missing provenance: rejected, exactly like every other fact.
    bad = {**base, "facts": {"pull_required": [{
        "pin": "4", "to": "GND", "expected_value": "5.1k",
    }]}}
    with pytest.raises(PartError, match="provenance"):
        entry_from_json(bad, "<t>")
    # A pull record without an expected value is refused: "some resistor"
    # is not a checkable claim.
    no_value = {**base, "facts": {"pull_required": [{
        "pin": "4", "to": "GND",
        "provenance": "ST AN5225 Table 6, http://x/ds.pdf",
    }]}}
    with pytest.raises(PartError, match="expected_value"):
        entry_from_json(no_value, "<t>")
