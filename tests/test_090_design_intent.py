"""090 A1: the DesignIntent contract, its persistence discipline, and its wiring.

The batch's claim, in four testable halves:

* **the contract** — three sections plus `intentVersion`, a closed schema, an
  optional field that is *not written* when it says nothing, provenance on every
  entry with the draft default visible, and a digest over the normal form;
* **the questions** — a rail with no voltage declaration is a **reported slot**,
  never a refusal, and a bidirectional current-sense signal with no closure
  declaration gets a **hint** (the ROBOT ctrl FOC bias hole, A1's own wiring);
* **the persistence discipline** — regeneration adds the slots the drawing now
  owes, an answer already written survives **byte for byte**, an object that
  disappeared is marked `stale` and never deleted (052 §2.2's accident closed by
  construction);
* **the wiring** — `checkup` reports an `intent` section whose `intent-missing`
  lines name the slot, the file and the key; the exit code does **not** move;
  `design-intent.md` becomes the contract's view; and the shipped ctrl FOC
  contract points at the F1 bias case's slot.

Offline throughout: fixtures are read as files, no bridge, no network. The
user-level landing spot (`~/.boardwise/design-intent/`) is redirected through
`BOARDWISE_HOME`, the same convention `core/config.py` uses — a test never
touches the real home, and a real home never changes what a test sees.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import designintent as di
from boardwise.core.architecture import (
    INTENT_FILE_NAME,
    TODO,
    generate_architecture,
    parse_intent,
)
from boardwise.core.circuitspec import weakest_provenance
from boardwise.core.model import Net
from boardwise.core.parts import load_parts
from boardwise.engines.checkup import (
    INTENT_HINT_CLOSURE,
    INTENT_MISSING,
    intent_hint_line,
    intent_missing_line,
)
from boardwise.parsers.schematic import build_project_model

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
GOLDEN = FIXTURES / "ch340_golden.epro2"
SHELF = Path("blocklib/parts.json")
FOC_CONTRACT = Path("blocklib/intents/robot-ctrl-foc.intent.json")


@pytest.fixture(scope="module")
def robot():
    return build_project_model(ROBOT)


@pytest.fixture(scope="module")
def slots(robot):
    """The architecture's own enumeration — the only source of slot ids."""
    return generate_architecture(robot, library=load_parts(SHELF)).section["slots"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty `BOARDWISE_HOME`, so the default landing spot is a temp directory."""
    root = tmp_path / "home"
    monkeypatch.setenv("BOARDWISE_HOME", str(root))
    return root


def _contract(**overrides) -> di.DesignIntent:
    """A small authored contract: two rails, one chain, one block, one decision."""
    payload = {
        "intentVersion": 1,
        "requirements": {
            "rails": [
                {"net": "+12V", "targetVoltage": "12V", "role": "bus",
                 "provenance": "user_stated"},
            ],
            "signals": [
                {"net": "U+", "kind": "current-sense", "polarity": "bidirectional",
                 "reference": "GND", "provenance": "user_stated"},
            ],
            "buses": [],
        },
        "blocks": [{"id": "senseU", "kind": "current-sense", "parts": ["R4"],
                    "provenance": "ai_asserted"}],
        "decisions": [{"subject": "R4", "decision": "0.1R 直采", "provenance": "user_stated"}],
    }
    payload.update(overrides)
    return di.DesignIntent.from_dict(payload)


def _regenerated(document: di.DesignIntent, slots) -> str:
    """The tool-written text of one regeneration (the canonical form on disk)."""
    return di.render_json(di.merge(document, slots)[0])


def _fill(text: str, needle: str, addition: str) -> str:
    """Fill one value the way a person does: edit the JSON text."""
    assert needle in text, needle
    return text.replace(needle, f"{needle}\n        {addition}", 1)


# ------------------------------------------------------------------ the contract


def test_the_document_round_trips_byte_for_byte():
    """The normal form is one shape, and reading it back does not move a byte."""
    first = _regenerated(_contract(), generate_architecture(build_project_model(ROBOT)).section["slots"])
    assert di.render_json(di.parse_json(first)) == first
    payload = di.parse_json(first).to_jsonable()
    assert payload["intentVersion"] == di.INTENT_VERSION
    assert set(payload) == {"intentVersion", "requirements", "blocks", "decisions"}
    assert set(payload["requirements"]) == {"rails", "signals", "buses"}


def test_the_schema_is_closed_and_names_the_offending_key():
    """Every refusal names the path: a model writes these documents."""
    cases = [
        ({"intentVersion": 1, "extra": []}, "unknown key(s) extra"),
        ({"intentVersion": 1, "requirements": {"raisl": []}}, "unknown key(s) raisl"),
        (
            {"intentVersion": 1, "requirements": {"rails": [{"net": "x", "voltage": "1V",
                                                             "voltagge": "2V"}]}},
            "unknown key(s) voltagge",
        ),
        ({"intentVersion": 1, "blocks": [{"id": "a", "partz": []}]}, "unknown key(s) partz"),
        ({"intentVersion": 1, "decisions": [{"decision": "d"}]}, "subject is required"),
        ({"intentVersion": 1, "requirements": {"rails": [{"net": "x"}, {"net": "x"}]}},
         "twice"),
    ]
    for payload, expected in cases:
        with pytest.raises(di.DesignIntentError) as excinfo:
            di.DesignIntent.from_dict(payload)
        assert expected in str(excinfo.value), expected


def test_a_section_that_is_absent_is_empty_not_an_error():
    """A person writing the first contract writes one section and stops."""
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [{"net": "+12V"}]},
    })
    assert document.blocks == [] and document.decisions == []
    assert document.to_jsonable()["blocks"] == []
    # The writer still writes the normal form: three sections, always.
    written = json.loads(di.render_json(document))
    assert set(written) == {"intentVersion", "requirements", "blocks", "decisions"}
    assert set(written["requirements"]) == {"rails", "signals", "buses"}


def test_a_stated_version_this_build_does_not_read_is_refused():
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.DesignIntent.from_dict({"intentVersion": 2})
    assert "intentVersion is 2" in str(excinfo.value)
    assert "regenerate" in str(excinfo.value)


def test_an_optional_field_is_not_written_when_it_says_nothing():
    """A slot with no answer is **absent**, never empty (090 §一, rule 1)."""
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [{"net": "+12V"}]},
    })
    row = document.rails[0].to_jsonable()
    assert set(row) == {"net", "provenance"} == set(row)
    assert row["provenance"] == di.DEFAULT_PROVENANCE, "the unstated basis is shown, not implied"
    # ... and the answer, once written, is written.
    document.rails[0].slots["targetVoltage"] = "12V"
    assert document.rails[0].to_jsonable()["targetVoltage"] == "12V"


def test_a_value_is_a_string_and_a_number_is_refused():
    """046/048's rule: what was written on the part is not read as a quantity."""
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.DesignIntent.from_dict({
            "intentVersion": 1,
            "requirements": {"rails": [{"net": "+12V", "targetVoltage": 12}]},
        })
    assert "must be a string" in str(excinfo.value)


def test_the_digest_is_over_the_normal_form():
    """A re-indented file hashes the same; a changed fact does not."""
    document = _contract()
    compact = json.dumps(document.to_jsonable(), ensure_ascii=False)
    assert di.intent_sha256(di.parse_json(compact)) == document.sha256()
    changed = _contract()
    changed.rails[0].slots["targetVoltage"] = "13V"
    assert changed.sha256() != document.sha256()
    regraded = _contract()
    regraded.blocks[0].provenance = "user_stated"
    assert regraded.sha256() != document.sha256(), "a provenance change is a fact change"


# ----------------------------------------------------------------- provenance


def test_an_entry_without_a_stated_basis_is_a_visible_draft():
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [{"net": "+12V", "targetVoltage": "12V"}]},
    })
    assert document.rails[0].provenance == di.PROVENANCE_AI
    assert document.provenance == di.PROVENANCE_AI
    assert document.draft is True
    assert "ai_asserted" in document.draft_reasons[0]


def test_the_weakest_entry_sets_the_documents_tier():
    """052 §4, one ranking: the grammar's table, reused (core/circuitspec.py)."""
    document = _contract()
    assert document.provenance == di.PROVENANCE_AI, "the ai_asserted block weakens the whole document"
    assert document.draft is True
    assert di.weakest_provenance is weakest_provenance, (
        "one ranking rule for the repo: the contract does not re-implement it"
    )
    assert weakest_provenance("user_stated", "ai_asserted") == "ai_asserted"
    assert weakest_provenance("verified_recipe", "user_stated") == "user_stated", (
        "the engineer's own word ranks above a recipe"
    )
    assert weakest_provenance("", "user_stated") == "", "an unstated fact is the weakest"
    document.blocks[0].provenance = di.PROVENANCE_USER_STATED
    assert document.provenance == di.PROVENANCE_USER_STATED, (
        "with the AI's block graded by a person, the weakest entry is the user's"
    )
    assert document.draft is False


def test_an_unknown_provenance_token_is_refused_with_the_three_allowed():
    with pytest.raises(di.DesignIntentError) as excinfo:
        di.DesignIntent.from_dict({
            "intentVersion": 1,
            "requirements": {"rails": [{"net": "+12V", "provenance": "guessed"}]},
        })
    message = str(excinfo.value)
    assert "guessed" in message
    for kind in di.PROVENANCE_KINDS:
        assert kind in message


# ----------------------------------------------------------- the questions


def test_a_rail_without_a_voltage_declaration_is_reported_not_refused(slots):
    """090 §一: the validator reports the slot; reading the document still works."""
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [{"net": "+12V", "role": "bus"}]},
    })
    facts = di.validate(document, slots)
    rows = [row for row in facts["missing"] if row["object"] == "+12V"
            and row["key"] == "targetVoltage"]
    assert len(rows) == 1, "the slot is named, not the document refused"
    row = rows[0]
    assert row["required"] is True
    assert row["write"] == "requirements.rails[net=+12V].targetVoltage"
    assert row["id"].endswith("/intent:+12V/targetVoltage")
    assert row["where"] == "轨 `+12V`"
    assert "缺" not in row["label"] and row["label"], "the Chinese gloss travels with the slot"


def test_a_bidirectional_current_sense_signal_without_a_closure_gets_a_hint(slots):
    """The F1 shape: bidirectional phase current, no bias/reference declared.

    A hint, never a refusal (090 §一) — and it names the statement to write.
    """
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"signals": [
            {"net": "U+", "kind": "current-sense", "polarity": "bidirectional"},
        ]},
    })
    hints = di.validate(document, slots)["hints"]
    assert [hint["object"] for hint in hints] == ["U+"]
    hint = hints[0]
    assert hint["token"] == INTENT_HINT_CLOSURE
    assert hint["missing"] == 'requires: ["bias-reference"]'
    assert hint["write"].startswith("requirements.signals[net=U+].requires")
    assert "偏置" in hint["why"]


def test_a_closure_declaration_silences_the_hint_wherever_it_is_written(slots):
    """`requires` on the signal or on the block that realises the chain — both count.

    A1 checks the declaration's **existence**; tying it to one chain is A3's rule.
    """
    on_signal = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"signals": [
            {"net": "U+", "kind": "current-sense", "polarity": "bidirectional",
             "requires": ["bias-reference"]},
        ]},
    })
    assert di.validate(on_signal, slots)["hints"] == []
    on_block = _contract()
    on_block.blocks[0].requires = ["bias-reference"]
    assert di.validate(on_block, slots)["hints"] == []


def test_the_closure_question_is_only_asked_of_bidirectional_current_sense(slots):
    for signal in (
        {"net": "U+", "kind": "current-sense", "polarity": "unipolar"},
        {"net": "U+", "kind": "pwm", "polarity": "bidirectional"},
        {"net": "U+"},
    ):
        document = di.DesignIntent.from_dict({
            "intentVersion": 1, "requirements": {"signals": [signal]},
        })
        assert di.validate(document, slots)["hints"] == [], signal


# ------------------------------------------------------- the merge discipline


def test_a_filled_value_survives_regeneration_byte_for_byte(robot):
    """The 052 §2.2 regression pin: fill `targetVoltage: 3.3V` → regenerate.

    The value comes back as itself, the slots the drawing still owes are `TODO`,
    and **every line the answered document had is still a line of the new one** —
    only insertions were made (the new entries carry the separating comma; an
    entry that was last in its array can therefore never be touched).
    """
    architecture = generate_architecture(build_project_model(ROBOT)).section["slots"]
    first = _regenerated(di.DesignIntent(), architecture)
    filled = _fill(first, '"net": "+12V",', '"targetVoltage": "3.3V",')
    assert filled != first

    document = di.parse_json(filled)
    merged, facts = di.merge(document, architecture)
    text = di.render_json(merged)

    assert text.count('"targetVoltage": "3.3V"') == 1, "the answer came back as itself"
    assert di.parse_json(text).entry("rails", "+12V").value("targetVoltage") == "3.3V"
    assert all(line in text.splitlines() for line in filled.splitlines()), (
        "regeneration only inserts: every answered line is unchanged"
    )
    assert facts["filled"] == 1
    rail_slots = [entry for entry in merged.rails if entry.net == "+12V"][0]
    # The rest of that object's slots are still owed — the answer did not make the
    # object look complete.
    assert rail_slots.value("voltage") == "" and rail_slots.value("peakCurrent") == ""
    assert {row["key"] for row in facts["missing"] if row["object"] == "+12V"} >= {
        "voltage", "source", "continuousCurrent", "peakCurrent", "operatingCases",
    }


def test_a_new_object_arrives_as_a_todo_entry_and_moves_no_existing_line():
    """Regeneration = the enumeration's owed slots, added as TODO entries."""
    board = build_project_model(ROBOT)
    before = generate_architecture(board).section["slots"]
    document = di.parse_json(_regenerated(_contract(), before))
    filled = _fill(di.render_json(document), '"net": "+12V",', '"targetVoltage": "12V",')

    # The drawing moves: a new rail appears (a net whose name parses, with a
    # supply pin on it).
    board.nets["+5V"] = Net("+5V", [("U1", "1"), ("C1", "1")])
    after = generate_architecture(board).section["slots"]
    merged, facts = di.merge(di.parse_json(filled), after)
    text = di.render_json(merged)

    assert "rails:+5V" in facts["added"], facts["added"]
    entry = merged.entry("rails", "+5V")
    assert entry is not None, "the new rail has an entry (its slots are all TODO)"
    assert all(entry.value(key) == "" for key in di.RAIL_SLOT_KEYS)
    assert all(line in text.splitlines() for line in filled.splitlines())
    assert '"net": "+5V"' in text
    # The new entry is in front of its section, so not one existing line moved.
    assert text.index('"net": "+5V"') < text.index('"net": "+12V"')


def test_a_vanished_object_is_marked_stale_and_never_deleted(slots):
    """The other half: an object the drawing no longer has keeps its answer + a mark."""
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [
            {"net": "+24V", "targetVoltage": "24V", "provenance": "user_stated"},
        ]},
    })
    merged, facts = di.merge(document, slots)
    entry = merged.entry("rails", "+24V")
    assert entry is not None and entry.stale is True
    assert entry.value("targetVoltage") == "24V", "the recorded answer survives the mark"
    assert facts["stale"] == ["rails:+24V"]
    assert facts["staleEntries"] == [{"section": "rails", "object": "+24V"}]
    assert "stale" not in json.dumps({"+12V": None})  # (a guard against a typo'd constant)
    assert any(item["object"] == "+24V" for item in facts["missing"]) is False, (
        "an object the drawing does not have owes no slot"
    )
    # Regenerating again neither re-reports the mark nor drops the entry.
    again, facts2 = di.merge(merged, slots)
    assert facts2["stale"] == [], "the mark is a transition, not a permanent complaint"
    assert again.entry("rails", "+24V").stale is True
    assert again.entry("rails", "+24V").value("targetVoltage") == "24V"


def test_an_answer_the_enumeration_no_longer_asks_for_is_reported_not_removed(slots):
    """A question that stopped being asked is still a fact somebody wrote down.

    The schema's slot vocabulary is **per section**, the enumeration's questions
    are per *object*: `range` is a signal slot, and only the analog chains are
    asked for it. An answer on a control chain is a fact the contract keeps and
    the report names — never one a regeneration silently drops.
    """
    document = _contract()
    document.signals.append(
        di.IntentSignal(net="FOC_EN", kind="enable", slots={"range": "0..3.3V"},
                        provenance=di.PROVENANCE_USER_STATED)
    )
    merged, facts = di.merge(document, slots)
    assert merged.entry("signals", "FOC_EN").value("range") == "0..3.3V", "kept"
    assert any(
        row["object"] == "FOC_EN" and row["key"] == "range" for row in facts["extras"]
    ), facts["extras"]
    assert all(
        row["key"] != "range"
        for row in facts["missing"] if row["object"] == "FOC_EN"
    ), "a slot nobody asks for is not owed"


def test_the_merge_is_pure_and_idempotent(slots):
    original = di.render_json(_contract())
    document = di.parse_json(original)
    merged, _facts = di.merge(document, slots)
    assert di.render_json(document) == original, "the merge never mutates its input"
    assert di.render_json(di.merge(merged, slots)[0]) == di.render_json(merged)


def test_the_enumeration_is_the_architectures_own(slots):
    """Reuse, not a second opinion: the contract's objects are the skeleton's."""
    groups = di.reuse_slots(slots)
    architecture = generate_architecture(build_project_model(ROBOT), library=load_parts(SHELF)).section
    assert set(groups[di.SECTION_RAILS]) == {rail["net"] for rail in architecture["chains"]["rails"]}
    chains = {chain["net"] for chain in architecture["chains"]["analog"]} | {
        chain["net"] for chain in architecture["chains"]["control"]
    }
    assert set(groups[di.SECTION_SIGNALS]) == chains
    assert set(groups[di.SECTION_BUSES]) == {
        family["family"] for family in architecture["chains"]["bus"]
    }
    # Every enumerated slot landed somewhere, and its key is one the architecture
    # declared (no key of this module's own invention).
    placed = sum(len(records) for section in groups.values() for records in section.values())
    asserted = [slot for slot in slots if slot["sectionKind"] != "intent"]
    assert placed >= len(asserted)
    known = set(di.RAIL_SLOT_KEYS) | set(di.SIGNAL_SLOT_KEYS) | set(di.BUS_SLOT_KEYS)
    for section in groups.values():
        for records in section.values():
            for record in records:
                assert record["key"] in known, record


def test_a_slot_record_from_a_future_batch_is_reported_not_dropped():
    """`unmapped` exists so a slot nobody counts cannot hide."""
    groups, unmapped = di.classify_slots([
        {"sectionKind": "power", "object": "V1", "key": "voltage", "id": "p/b/power:V1/voltage"},
        {"sectionKind": "future", "object": "V1", "key": "shielding", "id": "p/b/future:V1/shielding"},
    ])
    assert list(groups[di.SECTION_RAILS]) == ["V1"]
    assert [slot["key"] for slot in unmapped] == ["shielding"]


# ------------------------------------------------------------ the human view


def test_the_markdown_view_is_the_table_the_053_channel_already_reads(slots):
    """The view is not a second channel: `parse_intent` reads it as it always did."""
    document, _facts = di.merge(_contract(), slots)
    view = di.render_markdown(document, slots, contract_file="contract.json")
    parsed = parse_intent(view)
    assert set(parsed) == {slot["id"] for slot in slots}, (
        "one row per slot (the view groups them by object, which is the same set)"
    )
    assert len(parsed) == len(slots)
    assert view.splitlines()[0] == f"# 设计意图（{INTENT_FILE_NAME}）"
    assert "JSON 是源" in view and "手填无效" in view
    filled = {key: record for key, record in parsed.items() if record["value"]}
    assert len(filled) == 3, "U+ range/polarity/reference and +12V targetVoltage… "
    row = next(record for key, record in parsed.items() if key.endswith("/analog:U+/polarity"))
    assert row["value"] == "bidirectional" and row["source"] == "user_stated"
    todo = [record for record in parsed.values() if record["value"] == ""]
    assert todo and all(record["signature"].startswith("sha256:") for record in todo)
    assert TODO in view


def test_the_markdown_view_does_not_invent_slot_ids_for_vanished_objects(slots):
    """An orphan is prose: a row would invent an id and `parse_intent` would read it."""
    document = di.DesignIntent.from_dict({
        "intentVersion": 1,
        "requirements": {"rails": [{"net": "GHOST", "targetVoltage": "9V"}]},
    })
    merged, _facts = di.merge(document, slots)
    view = di.render_markdown(merged, slots, contract_file="contract.json")
    assert "GHOST" in view and "不删只标" in view
    assert not any("/rail" in line or "/GHOST/" in line for line in view.splitlines())


# ------------------------------------------------------------ the landing spot


def test_the_default_landing_spot_follows_the_project_uuid_and_the_home(home, slots):
    path = di.default_contract_path("file-abc123")
    assert path == home / di.CONTRACT_DIR_NAME / "file-abc123.json"
    # A project uuid with a path separator in it must not invent a directory level.
    assert di.default_contract_path("a/b").name == "ab.json"
    assert di.default_contract_path("").name == "project.json"


def test_a_contract_that_cannot_be_read_is_a_note_and_never_an_overwrite(
    tmp_path, capsys, home
):
    broken = tmp_path / "broken.json"
    broken.write_text('{"intentVersion": 1, "requirements": {', encoding="utf-8")
    before = broken.read_bytes()
    code = cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF), "--intent", str(broken),
    ])
    out = capsys.readouterr().out
    assert code == 3, "073: this board's verdict is incomplete → 3 (unchanged by A1)"
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["intent"]["contract"]["present"] is False
    assert report["intent"]["contract"]["readError"]
    assert report["intent"]["totals"]["slots"] > 0, "the slots still come from the drawing"
    assert broken.read_bytes() == before, "a file this build cannot read is not one it overwrites"
    assert "读不了" in out


# ------------------------------------------------------------ the wiring


def test_checkup_reports_the_intent_section_and_the_exit_code_a_rule_moves(
    tmp_path, capsys, home
):
    """A1's section, and the code 094 A3b's rule moves it to.

    The board's verdict with no contract at all is 3 (incomplete reading); with
    **this** contract it is 1, and the difference is one real finding rather than
    a report: the contract declares `U+` a bidirectional current sense with
    `user_stated` provenance, the export has nothing biasing that node, and
    `arch-sense-bias-closure` files the F1 ERROR. A contract that finds a defect
    is supposed to move the verdict (093's table: a violated `user_stated`
    statement is an ERROR); what A1 promised — and this test still pins — is that
    the *report section* is not a second source of judgement.
    """
    contract = tmp_path / "foc.json"
    contract.write_text(json.dumps(_contract().to_jsonable(), ensure_ascii=False) + "\n",
                        encoding="utf-8")
    before = contract.read_bytes()
    argv = [
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF), "--intent", str(contract),
    ]
    code = cli.main(argv)
    out = capsys.readouterr().out
    assert code == 1, code
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    errors = [
        finding for finding in report["findings"]
        if finding["severity"] == "ERROR"
    ]
    assert [finding["rule_id"] for finding in errors] == ["arch-sense-bias-closure"], (
        "the one ERROR on this board is the contract's own chain being unclosed"
    )
    section = report["intent"]
    assert section["contract"]["present"] is True
    assert section["contract"]["file"] == str(contract)
    assert section["contract"]["intentVersion"] == di.INTENT_VERSION
    assert section["totals"]["slots"] == report["architecture"]["totals"]["slots"]
    assert section["totals"]["filled"] == 3, "U+ polarity/reference and +12V targetVoltage"
    assert section["totals"]["requiredMissing"] < section["totals"]["missing"], (
        "only the required slots carry intent-missing; the rest are still listed"
    )
    assert section["provenance"] == di.PROVENANCE_AI and section["draft"] is True
    # The wording: the token, the slot, the file and the key, in one line. `VCC`
    # is a rail this contract says nothing about, so its voltage declaration is
    # exactly the slot an `intent-missing` row has to name.
    line = next(line for line in section["intentMissing"] if "VCC" in line)
    assert line.startswith(f"{INTENT_MISSING}: ")
    assert "`targetVoltage`" in line and "`requirements.rails[net=VCC].targetVoltage`" in line
    assert str(contract) in line
    assert section["intentMissing"] == [
        intent_missing_line(row, str(contract)) for row in section["required"]
    ]
    assert section["hints"] == [
        {**hint, "line": intent_hint_line(hint, str(contract))}
        for hint in report["intent"]["hints"]
    ]
    # The console says it too ...
    assert f"{INTENT_MISSING}: " in out
    assert "重生成契约" in out
    # ... the human report renders it ...
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "## 设计意图合同（intent）" in markdown
    assert f"### 必填槽没声明（{section['totals']['requiredMissing']}）" in markdown
    assert "`intent-missing`" in markdown and "`facts-missing` 同族" in markdown
    # ... and checkup is a **reader** of the contract: not one byte of it moved.
    assert contract.read_bytes() == before


def test_checkup_without_a_contract_still_names_every_owed_slot(tmp_path, capsys, home):
    code = cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    out = capsys.readouterr().out
    assert code == 3
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    section = report["intent"]
    assert section["contract"]["present"] is False
    assert section["contract"]["file"] == str(
        di.default_contract_path(report["architecture"]["intent"]["projectUuid"])
    ), "the default spot is named even when nothing is there"
    assert section["totals"]["slots"] > 0
    assert section["totals"]["filled"] == 0
    assert section["totals"]["requiredMissing"] > 0
    assert "不存在" in out and "boardwise arch" in section["contract"]["regenerate"]


def test_checkup_reads_a_contract_from_the_user_level_landing_spot(tmp_path, capsys, home):
    """The live convention: no flag, the contract found under `BOARDWISE_HOME`.

    Written by hand here (nothing in a `checkup` run creates it), read by the run
    that finds it, and never touched by either.
    """
    uuid = generate_architecture(build_project_model(ROBOT)).section["intent"]["projectUuid"]
    path = di.default_contract_path(uuid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(di.render_json(_contract()), encoding="utf-8")
    before = path.read_bytes()
    # 1, not 3: the contract declares `U+` a bidirectional current sense, and since
    # 094 A3b `arch-sense-bias-closure` grades that against the drawing — one real
    # ERROR, so the verdict is "errors found" rather than "incomplete reading".
    assert cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ]) == 1
    capsys.readouterr()
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["intent"]["contract"]["present"] is True
    assert report["intent"]["contract"]["file"] == str(path)
    assert report["intent"]["totals"]["filled"] == 3
    assert path.read_bytes() == before, "a run that was not asked to regenerate writes nothing"


def test_checkup_renders_design_intent_md_from_the_contract(tmp_path, capsys, home):
    """`design-intent.md` keeps its name and becomes the contract's **view**."""
    contract = tmp_path / "foc.json"
    contract.write_text(di.render_json(_contract()), encoding="utf-8")
    # 1 since 094 A3b — see `test_checkup_reports_the_intent_section_and_the_exit_
    # code_a_rule_moves`: this contract's own chain is unclosed on this export.
    assert cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF), "--intent", str(contract),
    ]) == 1
    out = capsys.readouterr().out
    view = (tmp_path / "out" / INTENT_FILE_NAME).read_text(encoding="utf-8")
    assert "由 DesignIntent 合同渲染" in view and "手填无效" in view
    assert str(contract) in view
    # The two views are one fact: the architecture's merged view read the same
    # answers the contract carries (it was fed this very rendering).
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["architecture"]["totals"]["filled"] == report["intent"]["totals"]["filled"] == 3
    assert "已按契约重渲染" in out
    # The 053 §2.2 channel still works on the rendered view (one round trip through
    # `parse_intent`), which is what keeps the two halves from drifting.
    assert parse_intent(view) == parse_intent(
        (tmp_path / "out" / INTENT_FILE_NAME).read_text(encoding="utf-8")
    )


def test_arch_intent_creates_the_contract_then_regenerates_it(tmp_path, capsys, home):
    """`boardwise arch --intent` is the one place a contract is written (090 §二)."""
    contract = tmp_path / "contracts" / "foc.json"
    out = tmp_path / "arch.md"
    argv = [
        "arch", str(ROBOT), "--out", str(out), "--library", str(SHELF),
        "--intent", str(contract),
    ]
    assert cli.main(argv) == 0
    text_out = capsys.readouterr().out
    assert contract.is_file(), "the first --intent run creates it"
    first = contract.read_text(encoding="utf-8")
    document = di.parse_json(first)
    assert document.rails, "the enumeration's rails are the skeleton of the contract"
    assert all(entry.slots == {} for entry in document.rails), "and every slot is TODO"
    assert "本次新增 TODO 条目" in text_out
    assert (tmp_path / INTENT_FILE_NAME).is_file(), "the view lands beside --out"
    assert "JSON 是源" in (tmp_path / INTENT_FILE_NAME).read_text(encoding="utf-8")

    # The engineer answers one rail, and regeneration keeps it.
    filled = _fill(first, '"net": "+12V",', '"targetVoltage": "3.3V",')
    contract.write_text(filled, encoding="utf-8")
    assert cli.main(argv) == 0
    captured = capsys.readouterr()
    second = contract.read_text(encoding="utf-8")
    assert all(line in second.splitlines() for line in filled.splitlines())
    assert second.count('"targetVoltage": "3.3V"') == 1
    assert "设计意图合同已是最新" in captured.err, (
        "nothing left to add: the file is not rewritten"
    )
    assert contract.read_text(encoding="utf-8") == second
    # The answers also reach the two views, which are rendered from the contract.
    assert "3.3V" in (tmp_path / INTENT_FILE_NAME).read_text(encoding="utf-8")
    assert "已填 1" in captured.out


def test_arch_without_intent_writes_nothing_outside_its_own_out(tmp_path, capsys, home):
    """A run that was not asked to regenerate a contract does not create one."""
    out = tmp_path / "arch.md"
    assert cli.main(["arch", str(GOLDEN), "--out", str(out)]) == 0
    capsys.readouterr()
    assert not (home / di.CONTRACT_DIR_NAME).exists()


# ------------------------------------------------------------ ctrl FOC wiring


def test_the_ctrl_foc_contract_is_canonical_and_deliberately_unclosed():
    """The shipped contract is what the tool would write, and F1's declaration is missing.

    The ROBOT ctrl FOC export names its rails `+12V` / `VCC` / `VCCA` and its two
    phase-current chains `U+` / `W+` (the design doc's `+24V` / `IU+` / `IW+` are
    the same objects under the live project's names). The contract is written
    with the names **this export has**, so the wiring below points at real slots.
    """
    text = FOC_CONTRACT.read_text(encoding="utf-8")
    document = di.parse_json(text)
    assert di.render_json(document) == text, "the shipped file is canonical"
    assert {rail.net for rail in document.rails} == {"+12V", "VCC", "VCCA"}
    assert all(rail.slots == {} for rail in document.rails), "电压/电流槽先 TODO"
    signals = {signal.net: signal for signal in document.signals}
    assert set(signals) == {"U+", "W+"}
    assert all(
        signal.kind == "current-sense" and signal.polarity == "bidirectional"
        for signal in signals.values()
    )
    assert {block.id for block in document.blocks} >= {"inlet", "senseU"}
    assert not any(
        token in block.requires for block in document.blocks for token in di.BIAS_TOKENS
    ), "F1's closure declaration is exactly what this contract is missing"
    assert document.decisions[0].subject == "R4"
    # The blocks are the AI's own claim, so the document is a draft — and says so.
    assert document.provenance == di.PROVENANCE_AI
    assert document.draft is True, "the ai_asserted blocks weaken the document"


def test_the_report_points_at_the_f1_bias_case(tmp_path, capsys, home):
    """§四's acceptance: the report names F1's slot and the statement it is missing."""
    contract = tmp_path / "foc.intent.json"
    contract.write_text(FOC_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    code = cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF), "--intent", str(contract),
    ])
    out = capsys.readouterr().out
    # 126c moved this assertion off the numeric exit code, and the reason is
    # the difference, not a loosening. What 090 §四 pinned here is **the report
    # naming F1's missing closure slot** — the exit code was incidental, riding
    # on `verdict: incomplete`. Supplying this contract now also reaches the PCB
    # runner, and `pcb-track-ampacity` reads the very same
    # `signals[].range = "±3A"` this test's contract declares and files **6
    # ERRORs** (3 A down 10 mil copper, on three layers, two nets — an overloaded
    # conductor is a safety matter). An ERROR sets `drc_summarise`'s exitCode to
    # 1 and 073's `_exit_code_with_verdict` only ever raises a 0 to 3, so the
    # code is 1 now.
    #
    # So the pin becomes the *verdict*, which is what actually decided the old 3
    # and is unchanged by 126c: unreviewed parts and untriaged warnings are what
    # make this board `incomplete`, and 6 more ERRORs do not alter that. The exit
    # code is asserted alongside it, in the direction 126c moved it, so this test
    # cannot be satisfied by a rule that simply stopped firing.
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["completion"]["verdict"] == "incomplete"
    assert report["summary"]["errorCount"] == 6, (
        "the 126c ampacity ERRORs are the reason the exit code is 1, not 3"
    )
    assert code == 1, "an ERROR keeps its 1; `incomplete` only ever raises a 0 (073)"
    section = report["intent"]
    hints = {hint["object"]: hint for hint in section["hints"]}
    assert set(hints) == {"U+", "W+"}, "both measured phase-current nets are asked"
    hint = hints["U+"]
    assert hint["token"] == INTENT_HINT_CLOSURE
    assert hint["missing"] == 'requires: ["bias-reference"]'
    assert "requirements.signals[net=U+].requires" in hint["write"]
    assert "blocks[id=…].requires" in hint["write"], (
        "the design doc's own home for the closure fact is the block"
    )
    assert hint["write"] in hint["line"] and str(contract) in hint["line"]
    # The F1 chain's slots are the ones the report is talking about: the analog
    # slots of `U+` are enumerated, so the hint is about a real slot, not a name.
    u_plus = [
        slot for slot in report["architecture"]["slots"]
        if slot["object"] == "U+" and slot["sectionKind"] == "analog"
    ]
    assert {(slot["key"], slot["filled"]) for slot in u_plus} >= {
        ("polarity", True), ("reference", True), ("range", True), ("gainStage", False),
        ("consistency", False),
    }
    poly = next(slot for slot in u_plus if slot["key"] == "polarity")
    assert poly["value"] == "bidirectional"
    # ... and the rail whose closure the bias question hangs off is still owed.
    assert any(
        row["object"] == "+12V" and row["key"] == "targetVoltage"
        for row in section["required"]
    )
    assert INTENT_MISSING in out and INTENT_HINT_CLOSURE in out
    assert contract.read_text(encoding="utf-8") == FOC_CONTRACT.read_text(encoding="utf-8")
