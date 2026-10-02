"""091 A2a: the params contradiction's **direction**, decided by the design intent.

052 §2.1's finding names two repairs and picks neither, because which field is the
wrong one is a design decision — and 048 measured 17 parts whose *MPN column* was
the wrong field, so "write the MPN's decoded value back" is not a safe default.
A1 (`DesignIntent`, `b21089a`) gave that decision a home; this batch lets the
`param-value-mpn-match` rule **consume** it. The claims, in four testable halves:

* **schema** — `decisions[]` gains one *optional* key, `value`: the machine-readable
  quantity the prose states (a rule comparing two strings cannot read a number out
  of a sentence). Absent when unstated, refused when unknown, `intentVersion`
  unchanged, and the shipped ctrl FOC contract carries the design's own `0.1Ω`;
* **three states, one producer** — with the design's value the message says
  **改料号/重选件** and names the answer's provenance (`user_stated` states,
  `ai_asserted` asks — 052 §4); without one it names both repairs again and adds an
  `intent-missing` line pointing at `decisions[].value`; with no contract at all it
  is byte-for-byte the sentence 052 wrote. All three come out of one helper, and the
  module's own text formatting of the old template happens in exactly one place;
* **the verdict does not move** — severity, the four states, evidence and the
  finding's target are identical in all three states (an intent is a direction, and
  grading by intent is A3's);
* **the seams** — `rules` reads the contract through `core` (the layer table allows
  nothing else), `run_review(model, intent=…)` hands it to the one rule that reads
  one, a reading that names no contract gets `BUILTIN_RULES` **itself**, and the real
  ctrl FOC export with its shipped contract takes the `user_stated` direction.

Offline throughout: fixtures are read as files, no bridge, no network.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from boardwise.core import designintent as di
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.core.parts import PartLibrary, load_parts
from boardwise.engines.review import BUILTIN_RULES, INTENT_RULES, _rules_for, run_review
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.base import FindingTarget
from boardwise.rules.params import (
    INTENT_MISSING,
    MPN_REPAIR_DIRECTIONS,
    ValueMpnMatch,
    repair_directions,
)

FIXTURES = Path(__file__).parent / "fixtures"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SHELF = Path("blocklib/parts.json")
FOC_CONTRACT = Path("blocklib/intents/robot-ctrl-foc.intent.json")
PARAMS_SOURCE = Path("src/boardwise/rules/params.py")

#: The contradiction shape 052 §1 measured: the **design value** is 0.1 Ω and the
#: part number on the board is a 100 Ω one. `RK73H1JTTD1000F` is an E-96 code with
#: its tolerance letter (so the reading is anchored and the rule may accuse, 071
#: §1 C) and the two sides are 1000x apart — far above the 3x resistor tolerance.
BOARD_VALUE = "0.1Ω"
BOARD_MPN = "RK73H1JTTD1000F"
DESIGN_VALUE = "0.1Ω"
#: How the rule quotes the MPN's decoded quantity (``_human_value``): 100 Ω.
MPN_VALUE = "100"

#: The MPN the real ctrl FOC board's R4 is given in the witness below, so that the
#: board shows the contradiction its shipped contract has an answer for.
WITNESS_MPN = "RK73H1JTTD1002F"


def _conflict_model() -> DesignModel:
    """One resistor whose value field and part number disagree."""
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value=BOARD_VALUE, mpn=BOARD_MPN,
        pins=[Pin("1", "A", "VCC")],
    )
    return model


def _contract(
    *,
    subject: str = "R1",
    decision: str = "0.1Ω 直采，不加放大器",
    value: str = DESIGN_VALUE,
    provenance: str = "user_stated",
) -> di.DesignIntent:
    """A minimal contract: one decision, and nothing else the rule reads."""
    entry: dict[str, object] = {
        "subject": subject, "decision": decision, "provenance": provenance,
    }
    if value:
        entry["value"] = value
    return di.DesignIntent.from_dict({"intentVersion": 1, "decisions": [entry]})


def _source(document: di.DesignIntent, path: str = "mem://contract.json") -> di.IntentSource:
    return di.IntentSource(document=document, path=path)


def _rule(intent: di.IntentSource | None = None) -> ValueMpnMatch:
    """The rule with an **empty** shelf: kind comes from the value, as it may."""
    return ValueMpnMatch(library=PartLibrary(parts=[]), intent=intent)


def _violation(intent: di.IntentSource | None = None) -> object:
    findings = _rule(intent).check(_conflict_model())
    assert [f.rule_id for f in findings] == ["param-value-mpn-match"]
    return findings[0]


# ---------------------------------------------------------------------------
# the fixture is the shape the batch is about
# ---------------------------------------------------------------------------


def test_the_fixture_is_a_contradiction_and_a_warn():
    """No contract, no intent: the 052 row exactly as it has always been."""
    finding = _violation()
    assert finding.severity == "WARN"
    assert "board value 0.1 Ω contradicts its MPN" in finding.message
    assert f"({BOARD_MPN!r} decodes to 100 Ω)" in finding.message
    assert finding.target == FindingTarget(
        component_ref="R1", expected_before=BOARD_VALUE, suggested_after="",
    )


# ---------------------------------------------------------------------------
# three states, one producer
# ---------------------------------------------------------------------------


def test_no_contract_is_the_sentence_052_wrote_byte_for_byte():
    """A reading that names no intent must not change at all.

    The suffix is compared against the template itself, so a *new* sentence in
    this branch (an added clause, a re-worded direction) fails here rather than
    passing as "still contains both repairs".
    """
    old = MPN_REPAIR_DIRECTIONS.format(mpn_value=MPN_VALUE, board_value=BOARD_VALUE)
    assert repair_directions(
        "R1", mpn_value=MPN_VALUE, board_value=BOARD_VALUE, board_quantity=0.1,
        kind="resistor", intent=None,
    ) == old
    finding = _violation()
    assert finding.message.endswith(old)
    for word in ("intent-missing", "修复方向由设计意图决定（052 §2.1）"):
        assert word not in finding.message, word


def test_user_stated_decision_points_at_the_part_number():
    """The engineer's own decision: the Value is the design, so the MPN goes."""
    finding = _violation(_source(_contract()))
    assert "按设计决策应改料号" in finding.message
    assert "AI 草稿" not in finding.message, "a stated decision is not a draft"
    assert "provenance user_stated" in finding.message
    assert "出处 mem://contract.json" in finding.message, "the file is named"
    assert f"decisions[subject='R1'].value = {DESIGN_VALUE}" in finding.message
    assert f"把 Value 改成 MPN 解码值 {MPN_VALUE} 会把电路改错" in finding.message
    assert INTENT_MISSING not in finding.message


def test_ai_asserted_decision_asks_rather_than_tells():
    """052 §4: a guess may ride along as a hint, never as a ruler."""
    finding = _violation(_source(_contract(provenance="ai_asserted")))
    assert "AI 草稿认为应改料号，请确认" in finding.message
    assert "按设计决策应改料号" not in finding.message
    assert "ai_asserted 是草稿（052 §4），确认前不要照改" in finding.message
    assert "provenance ai_asserted" in finding.message


def test_a_contract_without_that_designator_lists_both_repairs_and_names_the_key():
    """No decision at all: still undecided — so both repairs, plus where to answer."""
    finding = _violation(_source(di.DesignIntent(), path="mem://empty.json"))
    assert MPN_REPAIR_DIRECTIONS.format(
        mpn_value=MPN_VALUE, board_value=BOARD_VALUE
    ) in finding.message
    assert INTENT_MISSING in finding.message
    assert "`decisions[].value` 没声明" in finding.message
    assert "写进 `mem://empty.json` 的 `decisions[subject='R1'].value`" in finding.message
    assert "（decisions[] 里还没有这个位号）" in finding.message
    assert "方向由设计决策定" in finding.message


def test_a_decision_without_a_machine_value_is_the_same_missing_answer():
    """Prose is not a number: a decision that states no `value` decides nothing."""
    finding = _violation(_source(_contract(value=""), path="mem://prose.json"))
    assert INTENT_MISSING in finding.message
    assert "（已有决策正文，缺的是机读值；provenance user_stated）" in finding.message
    assert "按设计决策应改料号" not in finding.message


def test_a_contract_for_another_designator_does_not_answer_for_this_one():
    """Exact identity only — R2's decision is not R1's (090's own rule)."""
    finding = _violation(_source(_contract(subject="R2"), path="mem://other.json"))
    assert INTENT_MISSING in finding.message
    assert "按设计决策应改料号" not in finding.message


def test_the_decision_value_is_read_by_the_parser_not_compared_as_text():
    """`0.1Ω` and `100mΩ` are one quantity — which is why the real case works.

    The shipped ctrl FOC contract writes the design's value as `0.1Ω` while that
    board's own field says `100mΩ`. A text comparison would call the decision a
    disagreement with the board and print the "Value 字段也要核实" clause; the
    parsers say the two are the same, and the message stays a statement.
    """
    model = _conflict_model()
    model.components["R1"].value = "100mΩ"
    finding = _rule(_source(_contract(value="0.1Ω"))).check(model)[0]
    assert "按设计决策应改料号" in finding.message
    assert "也不一致" not in finding.message


def test_a_decision_that_contradicts_the_board_too_says_so():
    """The direction is the design's, but the board's field is not thereby fine."""
    finding = _violation(_source(_contract(value="1k"), path="mem://off.json"))
    assert "按设计决策应改料号" in finding.message
    assert "也不一致" in finding.message
    assert "Value 字段同样要按设计决策核实" in finding.message


def test_a_decision_value_the_parsers_cannot_read_is_reported_not_guessed():
    finding = _violation(_source(_contract(value="直采免放"), path="mem://odd.json"))
    assert "按设计决策应改料号" in finding.message
    assert "不是本规则能读的量" in finding.message


# ---------------------------------------------------------------------------
# the verdict does not move (A3 is where intent reaches grading)
# ---------------------------------------------------------------------------


def test_the_three_states_differ_in_the_message_and_nothing_else():
    """Severity, state, subject, evidence and target are the same in all three."""
    states = {
        "none": None,
        "user_stated": _source(_contract()),
        "ai_asserted": _source(_contract(provenance="ai_asserted")),
        "no_decision": _source(di.DesignIntent()),
    }
    rows = {name: _violation(intent) for name, intent in states.items()}
    reference = rows["none"]
    for name, finding in rows.items():
        assert finding.severity == reference.severity == "WARN", name
        assert finding.level == reference.level, name
        assert finding.target == reference.target == FindingTarget(
            component_ref="R1", expected_before=BOARD_VALUE, suggested_after="",
        ), name
        outcomes = _rule(states[name]).outcomes(_conflict_model())
        assert [o.state for o in outcomes] == ["VIOLATION"], name
        assert [o.subject for o in outcomes] == ["R1"], name
        assert outcomes[0].evidence == _rule().outcomes(_conflict_model())[0].evidence
        # The contradiction the row states is not softened by knowing a direction.
        assert "board value 0.1 Ω contradicts its MPN" in finding.message, name


def test_the_wording_has_one_producer():
    """Two producers of one sentence is how a wording drifts (052 §2.1's lesson).

    Structural, because "every path goes through the helper" is a claim about the
    *source*: the module formats the 052 template in exactly one place (inside
    `repair_directions`), and the rule's only production path calls the helper.
    """
    source = PARAMS_SOURCE.read_text(encoding="utf-8")
    assert source.count("MPN_REPAIR_DIRECTIONS.format(") == 1, (
        "the 052 sentence must be formatted in one place"
    )
    assert "repair_directions(" in inspect.getsource(ValueMpnMatch._rows)
    assert repair_directions.__module__ == "boardwise.rules.params"


# ---------------------------------------------------------------------------
# the seams: core, the runner, and the real case
# ---------------------------------------------------------------------------


def test_the_rule_reads_a_contract_that_lives_in_core():
    """The layer table (006c) leaves `rules` exactly one direction: `core`.

    `IntentSource` is the carrier both `rules` and `engines` need, so it lives in
    `core.designintent` — and this module's own in-package imports must stay inside
    `rules` and `core` (`tests/test_layer_rules.py` enforces the same arrow over
    the whole package). Importing `engines` from a rule, or reading the contract
    file inside one, is the mistake this pins.
    """
    import ast

    import boardwise.rules.params as params

    assert params.IntentSource is di.IntentSource
    layers: set[str] = set()
    for node in ast.walk(ast.parse(PARAMS_SOURCE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            head = (node.module or "").split(".")[0]
            layers.add(head if node.level >= 2 else "(same layer)")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("boardwise."):
                    layers.add(alias.name.split(".")[1])
    assert layers <= {"core", "(same layer)"}, layers
    # ... and the rule reads nothing off the disk: the contract is handed in.
    assert "read_text" not in inspect.getsource(params.ValueMpnMatch)
    assert "open(" not in inspect.getsource(params.ValueMpnMatch)


def test_run_review_hands_the_contract_to_the_rule_that_reads_one():
    """One rule reads an intent; every other rule is the same object as ever.

    The instance carrying the contract is **fresh**: `BUILTIN_RULES` outlives any
    single run, so setting the answer on the shared instance would leak this
    reading's contract into the next reading.

    **092 A2b rewrite**: the "every other rule" half used to test
    `isinstance(rule, ValueMpnMatch)`, because that was the only intent rule when
    this batch was written. Two rail-rating rules joined `INTENT_RULES` in A2b, so
    the test now skips **that table** rather than one name — the same claim
    ("only the rules that read an intent are rebuilt"), stated where the seam
    itself is written down. Each new carrier's own tests are in
    `tests/test_092_rail_ratings.py`.
    """
    assert _rules_for(None) is BUILTIN_RULES, "no contract, no copy"
    contract = _source(_contract())
    rules = _rules_for(contract)
    assert [rule.id for rule in rules] == [rule.id for rule in BUILTIN_RULES]
    carriers = [rule for rule in rules if isinstance(rule, ValueMpnMatch)]
    assert len(carriers) == 1 and carriers[0].intent is contract
    assert carriers[0] is not next(
        rule for rule in BUILTIN_RULES if isinstance(rule, ValueMpnMatch)
    )
    for rule, template in zip(rules, BUILTIN_RULES):
        if isinstance(rule, INTENT_RULES):
            assert rule is not template, rule.id
            continue
        assert rule is template, rule.id
    # ... and the shared instance is still contract-free afterwards.
    assert next(
        rule for rule in BUILTIN_RULES if isinstance(rule, ValueMpnMatch)
    ).intent is None


def test_an_intent_reading_still_says_the_same_things_over_the_whole_board():
    """`run_review(model)` and `run_review(model, intent=None)` agree row for row."""
    model = build_project_model(ROBOT)
    plain = run_review(model)
    explicit = run_review(model, intent=None)
    assert len(plain) == len(explicit) > 0
    assert [
        (f.rule_id, f.severity, f.message, f.target, f.board) for f in plain
    ] == [
        (f.rule_id, f.severity, f.message, f.target, f.board) for f in explicit
    ]


def test_the_ctrl_foc_export_and_its_shipped_contract_take_the_user_stated_direction():
    """The real case (052 §1's own board, and A1's shipped contract).

    The export's R4 is a 0.1 Ω shunt and its MPN agrees, so the contradiction here
    is *injected*: R4 is given a 10 kΩ part number — the same shape 048 measured,
    an MPN column that is the wrong field — and the contract's `decisions[R4]` is
    the engineer's own answer (`value: 0.1Ω`, `user_stated`). The finding must
    therefore point at the **part number**, name the contract as its source, and
    leave the Value alone.

    The same board read without the contract still says what it always said, which
    is the other half of the claim: the direction comes from the intent, and only
    from it.
    """
    model = build_project_model(ROBOT)
    board = model.boards[0]
    assert "R4" in board.components, "the contract's subject is on this board"
    board.components["R4"].mpn = WITNESS_MPN

    contract = di.IntentSource.load(FOC_CONTRACT)
    assert contract.decision("R4").stated_value == "0.1Ω"

    directed = [f for f in run_review(model, intent=contract)
                if f.rule_id == "param-value-mpn-match"]
    assert [f.message.split(":")[0] for f in directed] == ["R4"]
    message = directed[0].message
    assert "按设计决策应改料号" in message
    assert "provenance user_stated" in message
    assert str(FOC_CONTRACT) in message, "the contract that answered is named"
    assert INTENT_MISSING not in message
    assert directed[0].severity == "WARN"

    undirected = [f for f in run_review(model)
                  if f.rule_id == "param-value-mpn-match"]
    assert [f.message.split(":")[0] for f in undirected] == ["R4"]
    assert undirected[0].message.endswith(
        MPN_REPAIR_DIRECTIONS.format(mpn_value="10k", board_value="100mΩ")
    ), "without the contract this board is read exactly as before"


# ---------------------------------------------------------------------------
# the contract's new optional key (schema discipline, rule 1)
# ---------------------------------------------------------------------------


def test_a_decisions_value_is_optional_and_written_only_when_stated():
    stated = _contract()
    assert stated.decisions[0].stated_value == DESIGN_VALUE
    assert stated.to_jsonable()["decisions"][0]["value"] == DESIGN_VALUE
    unstated = _contract(value="")
    assert "value" not in unstated.to_jsonable()["decisions"][0], (
        "an unstated key does not occupy a line"
    )
    assert "value" not in json.dumps(unstated.to_jsonable(), ensure_ascii=False)
    # Round trip and digest: the key is part of the normal form like any other.
    assert di.parse_json(di.render_json(stated)).decisions[0].stated_value == DESIGN_VALUE
    assert stated.sha256() != unstated.sha256()


def test_the_decision_schema_is_still_closed_and_the_version_still_reads():
    assert di.INTENT_VERSION == 1
    payload = _contract().to_jsonable()
    payload["decisions"][0]["machineValue"] = "0.1Ω"
    try:
        di.DesignIntent.from_dict(payload)
    except di.DesignIntentError as exc:
        assert "unknown key(s) machineValue" in str(exc)
        assert "value" in str(exc), "the allowed keys are listed"
    else:  # pragma: no cover - the schema is closed, this never runs
        raise AssertionError("an unknown key in a decision was accepted")
    # A value that is not a string is refused rather than coerced (046/048's
    # defect: a display value read as a quantity).
    bad = _contract().to_jsonable()
    bad["decisions"][0]["value"] = 0.1
    try:
        di.DesignIntent.from_dict(bad)
    except di.DesignIntentError as exc:
        assert "must be a string" in str(exc)
    else:  # pragma: no cover - every value in this contract is text
        raise AssertionError("a numeric decision value was accepted")


def test_the_shipped_contract_carries_the_designs_own_word():
    """§一's second bullet: the ctrl FOC decision and its machine value agree."""
    text = FOC_CONTRACT.read_text(encoding="utf-8")
    document = di.parse_json(text)
    assert di.render_json(document) == text, "the shipped file is canonical"
    decision = document.decisions[0]
    assert (decision.subject, decision.stated_value, decision.provenance) == (
        "R4", "0.1Ω", "user_stated",
    )
    assert "0.1Ω" in decision.decision, "the machine value restates the prose"
    assert "机读值 value：`0.1Ω`" in di.render_markdown(
        document,
        [],
        contract_file=str(FOC_CONTRACT),
    )


def test_the_contract_is_read_with_its_path_and_looked_up_by_identity(tmp_path):
    """`IntentSource` is the reader's carrier: the document *and* where it lives."""
    path = tmp_path / "foc.intent.json"
    path.write_text(FOC_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
    source = di.IntentSource.load(path)
    assert source.path == str(path)
    assert source.decision("R4") is source.document.decisions[0]
    assert source.decision("R5") is None, "exact identity only"
    assert source.document.entry(di.SECTION_DECISIONS, "R4") is source.decision("R4")


def test_the_shelf_is_not_needed_to_take_a_direction():
    """The direction is read off two strings, so an unknown part still gets one."""
    library = load_parts(SHELF) if SHELF.is_file() else PartLibrary(parts=[])
    finding = ValueMpnMatch(
        library=library, intent=_source(_contract()),
    ).check(_conflict_model())[0]
    assert "按设计决策应改料号" in finding.message
