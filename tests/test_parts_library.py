"""The curated library's contract: schema, the value gate, the vocabulary.

Task 008b's discipline lives here in test form, and each test names the failure
it prevents:

* ``330mΩ`` must never match ``33Ω`` — the #202 regression, where a part
  number's digits were read as a resistance;
* the SI prefix is case-sensitive, because ``mΩ`` and ``MΩ`` are nine decades
  apart and lowercasing is how that gets lost;
* a declared field is read as a **whole field**, and an ambiguous one fails
  closed instead of matching whatever number happens to be inside it;
* a size word maps to a library name **only** through the explicit table.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from boardwise.core.parts import (
    CATEGORY_TO_PREFIX,
    FOOTPRINT_ALIASES,
    PartEntry,
    PartError,
    PartLibrary,
    PartProvenance,
    category_of,
    entry_from_json,
    entry_to_json,
    expand_footprint_words,
    footprint_matches,
    library_from_json,
    library_to_json,
    load_parts,
    looks_like_library_uuid,
    make_key,
    package_slug,
    parse_resistance_field,
    quantities_in_description,
    quantity_slug,
    resistance_query,
    save_parts,
)

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "blocklib" / "parts.json"


def entry(**overrides) -> PartEntry:
    body = dict(
        key="res.5k1_0402",
        lcsc="C25905",
        deviceUuid="ef1f93374e0c4079b48a2d1a3cec8f6b",
        libraryUuid="0819f05c4eef4c71ace90d822a990e87",
    )
    body.update(overrides)
    return PartEntry(**body)


# --------------------------------------------------------------------------
# the value gate (#202)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,ohms",
    [
        ("5.1kΩ", Decimal("5100")),
        ("10kΩ 0402", Decimal("10000")),
        ("330mΩ", Decimal("0.330")),
        ("0.33Ω", Decimal("0.33")),
        ("33Ω", Decimal("33")),
        ("330MΩ", Decimal("330000000")),
        ("5mΩ", Decimal("0.005")),
        ("5MΩ", Decimal("5000000")),
        ("33Ω电阻", Decimal("33")),
        ("4.7 ohm", Decimal("4.7")),
    ],
)
def test_an_explicit_resistance_query_is_one_number(text, ohms):
    query = resistance_query(text)
    assert query.active is True
    assert query.ohms == ohms


@pytest.mark.parametrize(
    "text",
    [
        "1/2Ω",     # a fraction: the numeric tail must not become 2Ω
        "1,000Ω",   # thousands separator: must not become 0Ω
        "3e3ohm",   # scientific notation: not supported, so not a match
        "1uohm",    # an unsupported prefix triggers rejection, not a fuzzy fallback
        "0.33Ω~1Ω", # a range: two values is ambiguous
        "10Ω 22Ω",  # two requests at once is ambiguous
    ],
)
def test_a_malformed_or_ambiguous_resistance_fails_closed(text):
    query = resistance_query(text)
    assert query.active is True
    assert query.ohms is None


@pytest.mark.parametrize("text", ["10k", "4R7", "0402", "CH340N", "330m", ""])
def test_a_query_without_a_unit_is_fuzzy_not_gated(text):
    query = resistance_query(text)
    assert query.active is False
    assert query.ohms is None


def test_the_si_prefix_is_case_sensitive_by_construction():
    """`m` is milli and `M` is mega; lowercasing the query is the bug."""
    assert resistance_query("5mΩ").ohms == Decimal("0.005")
    assert resistance_query("5MΩ").ohms == Decimal("5000000")
    assert resistance_query("5mΩ").ohms != resistance_query("5MΩ").ohms


def test_330_milliohm_is_not_33_ohm_and_not_a_substring_match():
    """#202 verbatim: `330mΩ` IS `0.33Ω`, and is nothing like `33Ω`."""
    assert resistance_query("330mΩ").ohms == resistance_query("0.33Ω").ohms
    assert resistance_query("330mΩ").ohms != resistance_query("33Ω").ohms
    assert resistance_query("330mΩ").ohms != resistance_query("330MΩ").ohms


@pytest.mark.parametrize(
    "text,expected",
    [
        ("330mΩ", Decimal("0.330")),
        ("0.33Ω", Decimal("0.33")),
        ("33Ω", Decimal("33")),
        ("5.1kΩ", Decimal("5100")),
        ("5.1kΩ ±1%", None),               # not a *pure* field...
        ("0805W8F330LT5E", None),          # ...and a part number is never one
        ("C52548", None),
        ("472M 1KV", None),
        ("", None),
    ],
)
def test_a_declared_field_is_read_as_a_whole_field(text, expected):
    assert parse_resistance_field(text) == expected


@pytest.mark.parametrize("text,expected", [("5k1", Decimal("5100")), ("4R7", Decimal("4.7"))])
def test_the_schematic_shorthand_is_opt_in(text, expected):
    """`5k1`/`4R7` are only read where the caller says so — a curated value, never
    a catalog description or an MPN."""
    assert parse_resistance_field(text, shorthand=True) == expected
    assert parse_resistance_field(text) is None


def test_a_field_with_a_qualifier_is_read_only_when_it_holds_one_quantity():
    """A real catalog writes `5.1kΩ ±1%`; refusing that makes the gate useless."""
    assert quantities_in_description("5.1kΩ ±1%") == {Decimal("5100")}
    assert quantities_in_description("no unit here") == set()
    # A range never yields one usable value, whichever way it is punctuated:
    # the separator-adjacent one is dropped (count mismatch) or both are kept
    # (two values) — and either way the caller refuses to pick a number.
    assert quantities_in_description("0.33Ω~1Ω") is None
    assert quantities_in_description("0.33Ω to 1Ω") == {Decimal("0.33"), Decimal("1")}
    assert quantities_in_description("1/2Ω") is None      # a unit with no quantity


def test_the_entry_resistance_comes_from_a_named_field_never_from_the_part_number():
    named = entry(params={"Resistance": "5.1kΩ ±1%"})
    assert named.resistance() == Decimal("5100")
    # A part number that happens to contain `330` declares nothing.
    from_number = entry(value="", mpn="0805W8F330LT5E", params={})
    assert from_number.resistance() is None
    # The curated `value` field is an explicit declaration, so shorthand applies.
    assert entry(value="5k1").resistance() == Decimal("5100")


# --------------------------------------------------------------------------
# the footprint vocabulary table
# --------------------------------------------------------------------------


def test_a_size_word_maps_only_through_the_table():
    assert expand_footprint_words(["0402"], []).names == (
        "R0402", "C0402", "L0402", "LED0402",
    )
    # A category word disambiguates within the table, nothing more.
    assert expand_footprint_words(["0402"], ["cap"]).names == ("C0402",)
    assert expand_footprint_words(["0402"], ["电阻"]).names == ("R0402",)
    # A library-shaped word that is already in the table passes through.
    assert expand_footprint_words(["R0402"], []).names == ("R0402",)


def test_a_word_outside_the_table_is_not_mapped():
    """The negative half: no table entry means no mapping, not a guess."""
    for word in ("9999", "0201", "abcdef", "QFN-64"):
        expanded = expand_footprint_words([word], [])
        assert expanded.names == (), word
    assert expand_footprint_words(["9999"], []).unmapped == ("9999",)
    # A word that is not size-shaped at all is simply not a footprint word.
    assert expand_footprint_words(["ch340n"], []).unmapped == ()


def test_the_table_is_the_only_mapping_and_it_is_explicit():
    assert FOOTPRINT_ALIASES["0402"] == ("R0402", "C0402", "L0402", "LED0402")
    assert set(CATEGORY_TO_PREFIX) >= {"res", "cap", "ind", "led", "电阻", "电容"}


def test_a_library_name_matches_exactly_or_by_its_own_suffix():
    assert footprint_matches("C0402", ("C0402",))
    assert footprint_matches("LED0805-R-RD", ("LED0805",))
    assert footprint_matches("c0805", ("C0805",))          # case differs between files
    assert not footprint_matches("R0603", ("R0402",))
    assert not footprint_matches("", ("R0402",))


# --------------------------------------------------------------------------
# shelf labels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("3kΩ", "3k"), ("5.1kΩ", "5k1"), ("100kΩ", "100k"), ("0Ω", "0"),
        ("5mΩ", "5m"), ("41.2kΩ", "41k2"), ("470Ω", "470"),
        ("20pF", "20p"), ("100nF", "100n"), ("1uF", "1u"), ("2.2uF", "2u2"),
        ("1.2nF", "1n2"), ("330uF", "330u"), ("2.2uH", "2u2"),
        ("", ""), ("banana", ""), ("10", ""),
    ],
)
def test_quantity_slugs_use_the_schematic_spelling(value, expected):
    assert quantity_slug(value) == expected


def test_package_slugs_come_from_chip_sizes_only():
    assert package_slug("R0402") == "0402"
    assert package_slug("C0805") == "0805"
    assert package_slug("L1008") == "1008"
    assert package_slug("LQFP-64_L10.0-W10.0-P0.50-LS12.0-BL") == ""
    assert package_slug("SOT-23-3_L2.9-W1.3-P0.95-LS2.4-BR") == ""


def test_the_shelf_category_prefers_the_library_footprint_over_the_designator():
    """Measured: a 3-pin header in one source board carries `Designator = U?`."""
    assert category_of("HDR-TH_3P-P1.27-V-M", "U?") == "conn"
    assert category_of("R0402", "R?") == "res"
    assert category_of("BUZ-TH_BD9.0-P4.00-D0.6-FD", "BUZZER?") == "buzzer"
    # With no footprint to go on, the designator is the fallback...
    assert category_of("", "C?") == "cap"
    # ...and with neither, the label says so instead of guessing.
    assert category_of("", "") == "part"
    assert category_of("FL_002", "J?") == "conn"


def test_make_key_prefers_value_and_package_then_mpn():
    assert make_key(
        category="res", value="5.1kΩ", mpn="0402WGF5101TCE",
        footprint_name="R0402", title="res_0402", lcsc="C25905",
    ) == "res.5k1_0402"
    assert make_key(
        category="ic", value="", mpn="STM32G431RBT6",
        footprint_name="LQFP-64_...", title="stm32g431rbt6", lcsc="C431633",
    ) == "ic.stm32g431rbt6"
    assert make_key(
        category="cap", value="", mpn="", footprint_name="", title="",
        lcsc="C12345",
    ) == "cap.c12345"
    with pytest.raises(PartError):
        make_key(category="part", value="", mpn="", footprint_name="", title="", lcsc="")


# --------------------------------------------------------------------------
# the file
# --------------------------------------------------------------------------


def test_the_committed_library_is_valid_and_addressable():
    library = load_parts(LIBRARY)
    assert library.parts, "the harvested library is empty"
    for part in library.parts:
        assert part.key and part.lcsc and part.deviceUuid and part.libraryUuid
        assert part.provenance.kind == "board-extract"
        assert part.provenance.designators, part.key
    # keys and C-numbers are unique — the loader enforces it, this pins the data
    assert len({p.key for p in library.parts}) == len(library.parts)
    assert len({p.lcsc for p in library.parts}) == len(library.parts)


def test_the_committed_library_marks_what_it_has_not_verified():
    """`unverified` is the honest default, and `verified` is never claimed idly.

    The committed shelf has been through a **live** `--verify` run on the machine
    (2026-09-16: 83 of 85 upgraded), so "every entry is `None`" — which this test
    said before that run — described the artifact's age rather than the rule.
    What the rule is, and what holds in both states:

    * a name is only ever upgraded by asking the library;
    * a claim of `true` requires an identity the library can actually resolve,
      because that chain is the only route to the answer (the schema refuses the
      claim otherwise — see `test_a_claim_of_verification_needs_an_identity`);
    * an entry the library could not answer for stays `None` and says so.
    """
    library = load_parts(LIBRARY)
    assert all(p.footprint_name for p in library.parts)
    for part in library.parts:
        if part.footprint_name_verified is True:
            assert looks_like_library_uuid(part.libraryUuid), part.key


def test_a_claim_of_verification_needs_an_identity():
    """`verified: true` with an identity the library cannot key is a lie, not data."""
    base = {
        "key": "ic.example",
        "lcsc": "C1",
        "deviceUuid": "a" * 32,
        "footprint_name": "SOP-8",
        "provenance": {"kind": "board-extract", "source": "somewhere.eprj2"},
    }
    # A library *name* where the uuid belongs (the personal-library shape).
    with pytest.raises(PartError, match="cannot have run"):
        entry_from_json({**base, "libraryUuid": "FOC", "footprint_name_verified": True})
    # The same entry unverified is exactly what the harvest writes, and loads.
    entry = entry_from_json(
        {**base, "libraryUuid": "FOC", "footprint_name_verified": None}
    )
    assert entry.footprint_name_verified is None
    # And a resolvable identity may carry the claim.
    assert entry_from_json(
        {**base, "libraryUuid": "b" * 32, "footprint_name_verified": True}
    ).footprint_name_verified is True


def test_the_committed_library_never_writes_a_human_footprint_label():
    """006b's vocabulary rule: the library name (`R0402`), never `0402`."""
    library = load_parts(LIBRARY)
    for part in library.parts:
        assert not part.footprint_name.isdigit(), part.key
        assert part.footprint_name == part.footprint_name.strip()


def test_entry_and_library_round_trip_through_json():
    original = PartLibrary(
        parts=[
            entry(
                params={"Resistance": "5.1kΩ ±1%", "Tolerance": "±1%"},
                datasheetUrl="https://example.invalid/x.html",
                basic=True,
                provenance=PartProvenance(
                    kind="board-extract",
                    source="a.eprj2",
                    designators=["R7@boardA", "R9@boardA"],
                ),
                notes=["a note"],
            )
        ],
        sources=["a.eprj2"],
    )
    once = library_to_json(original)
    twice = library_to_json(library_from_json(once))
    assert once == twice
    assert once["parts"][0]["provenance"]["designators"] == ["R7@boardA", "R9@boardA"]
    assert once["parts"][0]["params"] == {"Resistance": "5.1kΩ ±1%", "Tolerance": "±1%"}


def test_an_unknown_key_is_rejected_rather_than_ignored():
    with pytest.raises(PartError, match="unknown key"):
        entry_from_json({**entry_to_json(entry()), "surprise": 1})
    with pytest.raises(PartError, match="required"):
        entry_from_json({"key": "x.y", "lcsc": "", "deviceUuid": "", "libraryUuid": ""})


def test_a_duplicate_key_or_c_number_is_rejected():
    body = {
        "kind": "boardwise-part-library",
        "version": 1,
        "sources": [],
        "notes": [],
        "parts": [entry_to_json(entry()), entry_to_json(entry(mpn="other"))],
    }
    with pytest.raises(PartError, match="duplicate key"):
        library_from_json(body)
    body["parts"] = [entry_to_json(entry()), entry_to_json(entry(key="res.other"))]
    with pytest.raises(PartError, match="appears under two keys"):
        library_from_json(body)


def test_a_missing_library_is_an_empty_shelf_not_an_error(tmp_path):
    assert load_parts(tmp_path / "absent.json").parts == []


def test_save_and_load_agree(tmp_path):
    library = PartLibrary(parts=[entry()], sources=["a.eprj2"], notes=["n"])
    path = save_parts(library, tmp_path / "parts.json")
    assert save_parts(load_parts(path), tmp_path / "again.json").read_text(encoding="utf-8") == (
        path.read_text(encoding="utf-8")
    )
    assert json.loads(path.read_text(encoding="utf-8"))["kind"] == "boardwise-part-library"
