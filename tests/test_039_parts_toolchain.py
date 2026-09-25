"""039: the parts toolchain (`missing` / `show` / `add`) and the verified gate.

Three things are pinned here, in the order they matter:

* **The gate.** An entry whose `facts_verified` is false must not drive a rule,
  must say *why* in the message ("candidate", "unverified"), and must be
  invisible for every entry that predates the field — the 94 on the real shelf
  keep their exact bytes and their exact behavior.
* **The tools.** `missing` states what the shelf owes and never fails on a
  non-empty list; `show` is a full dump with "did you mean" when the query
  misses; `add` appends a candidate without rewriting one byte before it.
* **The write discipline.** `add` leaves a `.tmp` backup and re-parses with the
  real validator, and rolls back when the result would not load.

The real shelf (`blocklib/parts.json`) is read-only everywhere in this file; every
write test runs against a synthetic shelf in `tmp_path`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import (
    PartEntry,
    PartError,
    PartLibrary,
    entry_from_json,
    entry_to_json,
    library_from_json,
    load_parts,
    save_parts,
)
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.facts import LdoDropout, NcAndMustConnect, SupplyOnKnownDomain

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
#: A real .epro2 whose U-prefix parts are all on the shelf (STM32G431RBT6,
#: SN65HVD230DR, CH340N, TLE5012BE1000, ...) — the board `missing` was built for.
BOARD = ROOT / "tests" / "fixtures" / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
#: The 038 folder-format fixture: .eprj3, two U-prefix parts, no MPNs on them.
EPRJ3 = ROOT / "tests" / "fixtures" / "eprj3_synth"

PROV = "test datasheet, p.1, http://example.com/ds.pdf"

#: Every key in the vocabulary, each in the shape `core/parts.py` validates.
#: Only a part that has all seven is "judgeable" under `missing`'s counting rule,
#: which is what makes the all-clear line reachable in a test.
ALL_FACTS: dict = {
    "supply_pins": [
        {"pins": ["1"], "name": "VCC", "v_operating": [2.9, 5.5], "provenance": PROV}
    ],
    "required_caps": [{"pin": "1", "value": "100nF", "provenance": PROV}],
    "nc_pins": {"pins": ["2"], "provenance": PROV},
    "must_connect": [{"pin": "3", "to": "GND", "provenance": PROV}],
    "pull_required": [
        {"pin": "4", "to": "GND", "expected_value": "5.1kΩ", "provenance": PROV}
    ],
    "led": {"vf_v": [1.8, 2.2], "if_max_ma": 20.0, "provenance": PROV},
    "ldo": {
        "dropout_max_mv": 400.0,
        "condition": "Iout=500mA",
        "provenance": PROV,
    },
}


def _entry(
    key: str = "ic.supply.test",
    *,
    mpn: str = "SUPPLY1",
    lcsc: str = "C1",
    category: str = "ic.ldo",
    facts: dict | None = None,
    facts_verified: bool = True,
) -> PartEntry:
    return PartEntry(
        key=key,
        mpn=mpn,
        lcsc=lcsc,
        manufacturer="ACME",
        deviceUuid="dev-1",
        libraryUuid="0819f05c4eef4c71ace90d822a990e87",
        footprint_name="SOT-23-5",
        category=category,
        facts=facts,
        facts_verified=facts_verified,
    )


def _shelf(tmp_path: Path, *entries: PartEntry, name: str = "shelf.json") -> Path:
    path = tmp_path / name
    save_parts(PartLibrary(parts=list(entries)), path)
    return path


def _model(net: str = "+5V") -> DesignModel:
    """One U1 whose only pin sits on a net the domain table knows."""
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1",
        designator="U1",
        mpn="SUPPLY1",
        lcsc_part="C1",
        pins=[Pin("1", "VCC", net)],
    )
    model.nets = {net: Net(net, [("U1", "1")])}
    return model


def _states(rule, model) -> dict[str, list]:
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for outcome in rule.outcomes(model):
        grouped[outcome.state].append(outcome)
    return grouped


# --------------------------------------------------------------- the gate


def test_a_candidate_entry_does_not_drive_a_rule_and_says_why():
    """The whole point: facts nobody verified change no verdict, and the row
    names the reason rather than pretending the file is empty."""
    rule = SupplyOnKnownDomain(
        library=PartLibrary(parts=[_entry(facts=ALL_FACTS, facts_verified=False)])
    )
    states = _states(rule, _model())
    assert states["OK"] == [] and states["VIOLATION"] == []
    (unknown,) = states["UNKNOWN"]
    assert "candidate entry" in unknown.message
    assert "facts_verified is false" in unknown.message
    assert "facts_verified to true" in unknown.missing_fact


def test_the_same_entry_verified_decides_the_rule():
    """The other half: flip the flag and the very same facts drive it. Without
    this, the test above would pass on a rule that never decides anything."""
    rule = SupplyOnKnownDomain(
        library=PartLibrary(parts=[_entry(facts=ALL_FACTS, facts_verified=True)])
    )
    states = _states(rule, _model())
    assert states["UNKNOWN"] == []
    assert [outcome.state for outcome in states["OK"]] == ["OK"]


def test_a_candidate_is_unclassified_even_when_the_file_names_a_category():
    """`category: ic.ldo` plus unverified facts is *not* an LDO as far as the
    rules are concerned — there is no partial trust, and the one choke point
    (`_category_state`) is what makes that true for every rule at once."""
    entry = _entry(facts=ALL_FACTS, facts_verified=False)
    assert entry.category == "ic.ldo"
    (unknown,) = _states(LdoDropout(library=PartLibrary(parts=[entry])), _model())[
        "UNKNOWN"
    ]
    assert "unverified" in unknown.message
    assert "facts_verified is false" in unknown.message


def test_a_candidate_that_records_nothing_is_told_apart_from_one_that_claims():
    """Two candidates, two different rows: "no facts" and "a claim nobody
    vouched for" are different work orders, and the message says which."""
    claimed = _entry(facts=ALL_FACTS, facts_verified=False)
    empty = _entry(facts=None, facts_verified=False)
    messages = {}
    for name, entry in (("claimed", claimed), ("empty", empty)):
        rule = SupplyOnKnownDomain(library=PartLibrary(parts=[entry]))
        (unknown,) = _states(rule, _model())["UNKNOWN"]
        messages[name] = unknown.message
    assert "claims facts nobody has verified" in messages["claimed"]
    assert "no facts and is itself unverified" in messages["empty"]


def test_the_gate_is_enforced_on_the_object_not_only_in_the_loader():
    """A hand-built entry cannot be a hole either: the invariant lives on
    `PartEntry` itself, so no construction route reads facts a rule may not."""
    entry = _entry(facts=ALL_FACTS, facts_verified=False)
    assert entry.facts is None
    assert entry.candidate_facts == ALL_FACTS
    # ... and a verified entry is untouched.
    kept = _entry(facts=ALL_FACTS)
    assert kept.facts == ALL_FACTS and kept.candidate_facts is None


def test_an_entry_without_the_flag_round_trips_without_gaining_one():
    """The 94-entry shape: no `facts_verified` in the file, none in the output,
    and the facts still there. `true` is the default, never a written claim."""
    entry = _entry(facts={"nc_pins": {"pins": ["2"], "provenance": PROV}})
    raw = entry_to_json(entry)
    assert "facts_verified" not in raw
    back = entry_from_json(raw)
    assert back.facts_verified is True
    assert back.facts == entry.facts
    assert entry_to_json(back) == raw


def test_a_candidate_may_omit_the_uuid_pair_but_a_verified_entry_may_not():
    """`parts add` is offline and the uuid pair comes from the bridge, so a
    candidate is allowed to be unplaceable yet — and nothing else is."""
    candidate = {
        "key": "candidate.x",
        "lcsc": "C1",
        "facts_verified": False,
        "provenance": {"kind": "manual-curation"},
    }
    entry = entry_from_json(candidate)
    assert entry.deviceUuid == "" and entry.libraryUuid == ""
    verified = {k: v for k, v in candidate.items() if k != "facts_verified"}
    with pytest.raises(PartError, match="deviceUuid"):
        entry_from_json(verified)


def test_the_real_shelf_learns_nothing_about_the_gate():
    """Read-only pin on the shipped shelf: every entry parses, none gains a
    field, and every one serialises back to the object in the file — so the
    entries written before `facts_verified` existed are untouched by it."""
    raw = json.loads(SHELF.read_text(encoding="utf-8"))
    library = library_from_json(raw, str(SHELF))
    assert len(library.parts) == len(raw["parts"])
    by_key = {part.key: part for part in library.parts}
    gated = []
    for original in raw["parts"]:
        part = by_key[original["key"]]
        assert part.facts_verified is (original.get("facts_verified") is not False)
        if original.get("facts_verified") is False:
            gated.append(original["key"])
        assert entry_to_json(part) == original
    # The one gated entry is a deliberate curation hold, never an accident:
    assert gated in ([], ["ic.ref2033aiddcr"])


# ------------------------------------------------------------ parts missing


def test_missing_lists_every_u_part_with_what_the_shelf_is_missing(capsys):
    """The intake list itself: one block per U-prefix part, the missing keys
    named in table order, and the identity the rules will look up."""
    code = cli.main(["parts", "missing", "--file", str(BOARD), "--library", str(SHELF)])
    out = capsys.readouterr().out
    assert code == 0
    # A curated part and an uncurated one, both on the same board.
    assert "U6 CH340N [ic.ch340n] category=ic.usb-uart facts=3 missing=4" in out
    assert "present: must_connect, required_caps, supply_pins" in out
    assert "missing: nc_pins, led, ldo, pull_required" in out
    assert "U7 TLE5012BE1000 [ic.tle5012be1000] category=- facts=0 missing=7" in out
    assert "missing: supply_pins, required_caps, nc_pins, must_connect" in out
    assert "with missing facts" in out and "exit 0" in out


def test_missing_is_a_report_so_a_non_empty_list_is_still_exit_0(capsys, tmp_path):
    """Exit 0 with work outstanding is the contract, not an oversight: the list
    is information, and a build that failed on it would be ignored."""
    shelf = _shelf(tmp_path, _entry(mpn="STM32G431RBRT6", lcsc="C0", facts=None))
    code = cli.main(
        ["parts", "missing", "--file", str(BOARD), "--library", str(shelf)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "no shelf entry" in out


def test_missing_reads_the_folder_format_too(capsys):
    """038's .eprj3 tier-A read is reused as-is: a project with no MPNs is
    still a valid answer (two U parts, both owed)."""
    code = cli.main(["parts", "missing", "--file", str(EPRJ3), "--library", str(SHELF)])
    out = capsys.readouterr().out
    assert code == 0
    assert "U1 (no MPN, no C-number) [no shelf entry]" in out
    assert "2 U-prefix part(s), 2 with missing facts" in out


def test_missing_input_that_cannot_be_read_is_exit_2(capsys, tmp_path):
    """The one failure mode: an input the command cannot read at all."""
    missing_file = tmp_path / "nope.epro2"
    assert (
        cli.main(
            ["parts", "missing", "--file", str(missing_file), "--library", str(SHELF)]
        )
        == 2
    )
    assert "cannot read" in capsys.readouterr().err
    local_project = ROOT / "tests" / "fixtures" / "CH340G.eprj2"
    assert (
        cli.main(
            ["parts", "missing", "--file", str(local_project), "--library", str(SHELF)]
        )
        == 2
    )


def test_missing_writes_the_machine_report(capsys, tmp_path):
    report_path = tmp_path / "missing.json"
    code = cli.main(
        [
            "parts", "missing", "--file", str(BOARD),
            "--library", str(SHELF), "--json", str(report_path),
        ]
    )
    capsys.readouterr()
    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["command"] == "parts-missing"
    assert report["ok"] is True
    assert report["library"] == str(SHELF)
    assert report["fullyJudgeable"] is False
    assert report["vocabulary"] == [
        "supply_pins", "required_caps", "nc_pins", "must_connect", "led", "ldo",
        "pull_required",
    ]
    row = next(r for r in report["parts"] if r["designator"] == "U6")
    assert row["mpn"] == "CH340N"
    assert row["shelfKey"] == "ic.ch340n"
    assert row["onShelf"] is True
    assert row["factsVerified"] is True
    assert row["unverified"] is False
    # The contract, whatever the shipped shelf happens to hold: `missing` is the
    # vocabulary minus what that entry records, in vocabulary order.
    assert row["missing"] == [
        key for key in report["vocabulary"] if key not in row["factsPresent"]
    ]
    assert "supply_pins" in row["factsPresent"]
    assert row["datasheetUrl"].startswith("http")


def test_missing_matches_the_board_the_way_the_rules_do(capsys, tmp_path):
    """A candidate whose MPN is not on the board but whose C-number is still
    answers for that board part — the same MPN-then-C-number order the rules
    use, so the list and the verdicts can never disagree about identity."""
    shelf = _shelf(
        tmp_path,
        _entry(
            key="candidate.stm32g431rbfake",
            mpn="STM32G431RB-FAKE",
            lcsc="C431633",
            facts=None,
            facts_verified=False,
        ),
    )
    code = cli.main(
        ["parts", "missing", "--file", str(BOARD), "--library", str(shelf)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "U1 STM32G431RBT6 [candidate.stm32g431rbfake]" in out
    assert "facts_verified=false (candidate" in out
    assert "missing: supply_pins" in out


def test_missing_says_all_clear_when_nothing_is_owed(capsys, tmp_path):
    """The all-clear line, reachable only when every U part carries every key —
    the golden board's three U parts, each fully recorded."""
    shelf = _shelf(
        tmp_path,
        _entry(key="ic.ch340g", mpn="CH340G", lcsc="C14267", facts=ALL_FACTS),
        _entry(key="res.470_0805", mpn="FRC0805J471 TS", lcsc="C2907329",
               category="resistor", facts=ALL_FACTS),
        _entry(key="ic.rt9013_33gb", mpn="RT9013-33GB", lcsc="C47773", facts=ALL_FACTS),
    )
    code = cli.main(
        [
            "parts", "missing", "--file", str(ROOT / "tests/fixtures/ch340_golden.epro2"),
            "--library", str(shelf),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "全部可查" in out
    assert "3 U-prefix part(s) are judgeable" in out
    assert "missing=0" in out


# --------------------------------------------------------------- parts show


def test_show_dumps_identity_facts_provenance_and_the_gate(capsys, tmp_path):
    shelf = _shelf(
        tmp_path,
        _entry(key="ic.ch340n", mpn="CH340N", lcsc="C2977777", facts=ALL_FACTS),
    )
    code = cli.main(["parts", "show", "ic.ch340n", "--library", str(shelf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "CH340N — ic.ch340n" in out
    assert "gate: facts_verified = true" in out
    assert "facts (7):" in out
    assert "ldo:" in out and "dropout_max_mv" in out
    assert "kind: " in out


def test_show_marks_a_candidate_and_says_the_rules_hold_it_back(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(facts=ALL_FACTS, facts_verified=False))
    code = cli.main(["parts", "show", "SUPPLY1", "--library", str(shelf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "gate: facts_verified = false" in out
    assert "no rule acts on them" in out
    # The claim is still printed in full — that is what there is to review.
    assert "dropout_max_mv" in out


def test_show_folds_case_only_after_the_exact_steps(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(mpn="SUPPLY1"))
    assert cli.main(["parts", "show", "supply1", "--library", str(shelf)]) == 0
    assert "SUPPLY1 — ic.supply.test" in capsys.readouterr().out


def test_show_that_finds_nothing_offers_neighbours(capsys, tmp_path):
    """A dead end is the one thing a lookup may not be: the miss has to name
    what is close, capped at five so the answer stays readable."""
    shelf = _shelf(
        tmp_path,
        *[
            _entry(key=f"ic.lm{index}00", mpn=f"LM{index}00", lcsc=f"C{index}00")
            for index in range(1, 8)
        ],
    )
    code = cli.main(["parts", "show", "lm", "--library", str(shelf)])
    err = capsys.readouterr().err
    assert code == 2
    assert "no entry for 'lm'" in err
    assert "did you mean:" in err
    assert err.count("\n  ic.lm") == 5


def test_show_writes_the_machine_shape(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(facts=ALL_FACTS, facts_verified=False))
    report_path = tmp_path / "show.json"
    code = cli.main(
        ["parts", "show", "SUPPLY1", "--library", str(shelf), "--json", str(report_path)]
    )
    capsys.readouterr()
    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    entry_json = report["entry"]
    assert report["command"] == "parts-show"
    assert entry_json["key"] == "ic.supply.test"
    assert entry_json["factsVerified"] is False
    # `facts` is the claim in the file; `factsDriving` says a rule may not act.
    assert entry_json["facts"] == ALL_FACTS
    assert entry_json["factsDriving"] is False


# ---------------------------------------------------------------- parts add


def test_add_appends_a_candidate_and_keeps_every_existing_byte(capsys, tmp_path):
    """The write discipline, measured: the file grows by one entry and not one
    earlier byte moves — no re-serialisation of the 94 already on the shelf."""
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    before = shelf.read_bytes()
    code = cli.main(
        ["parts", "add", "TPL2981-30DBVR", "--lcsc", "C9900000001", "--library", str(shelf)]
    )
    out = capsys.readouterr().out
    assert code == 0
    after = shelf.read_bytes()
    tag = b"    }\r\n  ]\r\n}\r\n" if b"\r\n" in before else b"    }\n  ]\n}\n"
    assert before.endswith(tag) and after.endswith(tag)
    seam = len(before) - len(tag)
    assert after[:seam] == before[:seam]
    assert after[seam:].startswith(b"    },")
    assert len(after) > len(before)

    library = load_parts(shelf)
    assert [part.key for part in library.parts] == [
        "candidate.tpl2981_30dbvr",
        "ic.first",
    ]
    # ... appending is a document edit, so the file keeps the new entry last
    # even though the loaded library is key-sorted.
    assert json.loads(shelf.read_text(encoding="utf-8"))["parts"][-1]["key"] == (
        "candidate.tpl2981_30dbvr"
    )
    candidate = library.get("candidate.tpl2981_30dbvr")
    assert candidate is not None
    assert candidate.facts_verified is False
    assert candidate.facts is None and candidate.candidate_facts is None
    assert candidate.category == ""
    assert candidate.provenance.kind == "manual-curation"
    assert candidate.deviceUuid == "" and candidate.libraryUuid == ""
    assert "facts_verified is false" in candidate.notes[0]
    assert "curate the facts, then flip the flag" in out
    assert "next: boardwise parts show candidate.tpl2981_30dbvr" in out


def test_add_refuses_a_duplicate_mpn_and_points_at_show(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    before = shelf.read_bytes()
    code = cli.main(["parts", "add", "first", "--lcsc", "C999", "--library", str(shelf)])
    err = capsys.readouterr().err
    assert code == 2
    assert "already on the shelf as ic.first" in err
    assert "parts show ic.first" in err
    assert shelf.read_bytes() == before


def test_add_refuses_a_duplicate_c_number(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    code = cli.main(["parts", "add", "OTHER", "--lcsc", "c100", "--library", str(shelf)])
    assert code == 2
    # Case-insensitive on purpose: a C-number differing only in case is the same
    # part, and two entries for one part is the duplicate this guard exists for.
    assert "lcsc 'c100' is already on the shelf" in capsys.readouterr().err


def test_add_takes_an_explicit_key_and_refuses_a_taken_one(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    assert (
        cli.main(
            ["parts", "add", "OTHER", "--lcsc", "C200", "--key", "ic.first",
             "--library", str(shelf)]
        )
        == 2
    )
    assert "is taken by FIRST" in capsys.readouterr().err
    assert (
        cli.main(
            ["parts", "add", "OTHER", "--lcsc", "C200", "--key", "ic.other",
             "--library", str(shelf)]
        )
        == 0
    )
    assert load_parts(shelf).parts[-1].key == "ic.other"


def test_add_then_show_and_missing_agree_about_the_candidate(capsys, tmp_path):
    """The pipeline's two ends meet: `add` scaffolds, `show` reports the shut
    gate, and `missing` still counts the part as owed."""
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    assert (
        cli.main(
            ["parts", "add", "STM32G431RBT6", "--lcsc", "C431633", "--library", str(shelf)]
        )
        == 0
    )
    capsys.readouterr()
    assert cli.main(["parts", "show", "candidate.stm32g431rbt6", "--library", str(shelf)]) == 0
    assert "gate: facts_verified = false" in capsys.readouterr().out
    code = cli.main(["parts", "missing", "--file", str(BOARD), "--library", str(shelf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "U1 STM32G431RBT6 [candidate.stm32g431rbt6]" in out


def test_add_creates_the_shelf_when_there_is_none_yet(capsys, tmp_path):
    shelf = tmp_path / "new" / "shelf.json"
    code = cli.main(["parts", "add", "FRESH1", "--lcsc", "C1", "--library", str(shelf)])
    assert code == 0
    assert "backup" not in capsys.readouterr().out
    assert [part.key for part in load_parts(shelf).parts] == ["candidate.fresh1"]


def test_add_rolls_back_when_the_result_would_not_load(capsys, tmp_path, monkeypatch):
    """A write the validator refuses is not a write: the bytes go back, and the
    command fails rather than leaving a shelf nothing can read."""
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    before = shelf.read_bytes()

    from boardwise.core import parts as parts_module

    def refuse(path):
        raise PartError(f"{path}: refused by the stub validator")

    monkeypatch.setattr(parts_module, "load_parts", refuse)
    code = cli.main(["parts", "add", "OTHER", "--lcsc", "C200", "--library", str(shelf)])
    err = capsys.readouterr().err
    assert code == 2
    assert "rolled back" in err
    assert shelf.read_bytes() == before


def test_add_writes_the_machine_result(capsys, tmp_path):
    shelf = _shelf(tmp_path, _entry(key="ic.first", mpn="FIRST", lcsc="C100"))
    report_path = tmp_path / "add.json"
    code = cli.main(
        ["parts", "add", "OTHER", "--lcsc", "C200", "--library", str(shelf),
         "--json", str(report_path)]
    )
    capsys.readouterr()
    assert code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["command"] == "parts-add"
    assert report["key"] == "candidate.other"
    assert report["factsVerified"] is False
    assert report["entriesOnShelf"] == 2
    assert report["backup"] == str(shelf.with_suffix(".json.tmp"))


def test_nc_and_must_connect_reports_the_gate_too(capsys, tmp_path):
    """The other rule family that runs through `_category_state`: same gate,
    same sentence, and a `missing_fact` that asks for the review."""
    entry = _entry(
        key="ic.uart.test",
        mpn="SUPPLY1",
        facts={"nc_pins": {"pins": ["1"], "provenance": PROV}},
        facts_verified=False,
    )
    rules = NcAndMustConnect(library=PartLibrary(parts=[entry]))
    (unknown,) = _states(rules, _model())["UNKNOWN"]
    assert "facts_verified is false" in unknown.message
    assert "facts_verified to true" in unknown.missing_fact
