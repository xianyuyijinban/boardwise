"""104 / B4a: the three core-correctness defects the external audit filed as #11, #6 and #2.

Each test below was run against the shipped byte *before* anything was changed;
the docstring records the reading it replaced, with the numbers, so a change
that reintroduces the defect fails here rather than in a report nobody re-runs.

* **#11** ``core/compare.py`` — ``reconcile_names`` rebuilt its ``DesignModel``
  with ``components``/``nets`` only, so ``duplicate_designators``,
  ``cross_page_designators`` and ``unproven_nets`` fell back to their empty
  defaults: ``unproven_pages()`` answered ``None``, which reads as "proven", and
  the rules written to *refuse to conclude* on those facts concluded instead.
* **#6** ``rules/archclosure.py`` — ``arch-sense-bias-closure`` took
  ``shunts[0]``, i.e. whichever resistor-to-ground the **netlist happened to
  list first**. The same board with ``nets['U+']`` permuted flipped between
  ``ERROR`` (the 0.1 Ω shunt first) and a pass/``WARN`` (a 100 kΩ bleed-down
  first), and the row named the wrong part as the shunt.
* **#2** ``core/compare.py`` — ``plan_membership_renames`` approved a rename
  because the target name was being vacated, then deleted the renaming net's
  *own* entry later in the same pass, leaving the approval pointing at an
  occupied name: two nets welded into one under a name one of them never had.

``tests/test_094_sense_bias.py``'s own F1 board and shelf build the #6 shapes:
the defect is in that rule, against that arithmetic, and a hand-rolled copy of
the shelf would be a second, drifting definition of "power-class rail".
"""

from __future__ import annotations

import copy

from boardwise.core import designintent as di
from boardwise.core.compare import plan_membership_renames, reconcile_names
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.draw import _reconcile_derived_names
from boardwise.rules.archclosure import ArchSenseBiasClosure
from boardwise.rules.unproven import UNPROVEN_BY_NAME, unproven_nets
from tests.test_094_sense_bias import SHELF as SENSE_SHELF
from tests.test_094_sense_bias import _chain, _model_of, _part

PROV = "user_stated"


# ---------------------------------------------------------------------------
# small builders
# ---------------------------------------------------------------------------


def _model(*nets: tuple[str, list[tuple[str, str]]]) -> DesignModel:
    return DesignModel(
        nets={name: Net(name=name, pins=list(pins)) for name, pins in nets}
    )


def _nets(model: DesignModel) -> dict[str, set[tuple[str, str]]]:
    return {name: set(net.pins) for name, net in model.nets.items()}


def _sense_board(
    *, order: list[tuple[str, str]], rs: str = "10k", blocks=()
) -> tuple[DesignModel, object]:
    """F1's shape (094 §二) plus the audit's bleed-down, in ``order``.

    ``order`` is the two resistor-to-ground parts in the order the **netlist**
    lists them on ``nets['U+']`` — the only thing #6's two shapes differ in.
    ``rs`` is the series resistor that carries the bias onto the chain, so
    ``R_th = 1k‖1k + rs`` (500 Ω + rs) is the number the verdict turns on.
    """
    components = {
        "U8": _part("U8", mpn="AMS1117-3.3", pins=[("3", "+12V"), ("2", "VCC")]),
        "R10": _part("R10", value="1k", pins=[("1", "VCC"), ("2", "VCC/2")]),
        "R16": _part("R16", value="1k", pins=[("2", "VCC/2"), ("1", "GND")]),
        "R17": _part("R17", value=rs, pins=[("1", "VCC/2"), ("2", "U+")]),
        "U1": _part("U1", mpn="STM32G431RBT6", pins=[("21", "PA7", "U+")]),
    }
    ground = [("R16", "1")]
    u_plus = [("R17", "2"), ("U1", "21")]
    for designator, value in order:
        components[designator] = _part(
            designator, value=value, pins=[("2", "U+"), ("1", "GND")]
        )
        ground.append((designator, "1"))
        u_plus.append((designator, "2"))
    model = _model_of(
        components,
        {
            "+12V": [("U8", "3")],
            "VCC": [("U8", "2"), ("R10", "1")],
            "VCC/2": [("R10", "2"), ("R16", "2"), ("R17", "1")],
            "GND": ground,
            "U+": u_plus,
        },
    )
    return model, _intent(_chain("U+"), blocks=blocks)


def _intent(*signals, blocks=(), path: str = "mem://104.json") -> di.IntentSource:
    return di.IntentSource(
        document=di.DesignIntent(signals=list(signals), blocks=list(blocks)), path=path
    )


def _sense_block(parts, *, kind: str = "current-sense", block_id: str = "senseU"):
    return di.IntentBlock(id=block_id, kind=kind, parts=list(parts), provenance=PROV)


def _sense_row(model: DesignModel, intent):
    """The one row this chain produces."""
    rows = ArchSenseBiasClosure(library=SENSE_SHELF, intent=intent)._rows(model)
    assert len(rows) == 1, [row[0].message for row in rows]
    return rows[0]


#: The audit's two carriers: the 0.1 Ω phase shunt and a 100 kΩ bleed-down, on
#: one chain. ``Rsh``/``Rbleed`` are the names the rows then have to get right.
SHUNT = ("Rsh", "100mΩ")
BLEED = ("Rbleed", "100k")
SHUNT_FIRST = [SHUNT, BLEED]
BLEED_FIRST = [BLEED, SHUNT]


# ---------------------------------------------------------------------------
# #11: the safety metadata rides along, verbatim
# ---------------------------------------------------------------------------


def test_11_the_three_safety_fields_survive_a_reconcile_verbatim():
    """The audit's before/after table, as an assertion.

    BEFORE: ``dup=['R1'] cross={'R2': ['p1', 'p2']} unproven={'+5V': ('pa', 'pb')}``
    → ``repeated_designators() == ['R1', 'R2']``, ``unproven_pages('+5V') == ('pa', 'pb')``.
    AFTER (before this batch): ``dup=[] cross={} unproven={}`` →
    ``repeated_designators() == []``, ``unproven_pages('+5V') is None``.
    """
    golden = _model(("N1", [("a", "1"), ("a", "2")]))
    candidate = _model(("N1", [("a", "1"), ("a", "2")]))
    candidate.duplicate_designators = ["R1"]
    candidate.cross_page_designators = {"R2": ["p1", "p2"]}
    candidate.unproven_nets = {"+5V": ("pa", "pb")}

    out = reconcile_names(candidate, golden)

    assert out.duplicate_designators == ["R1"]
    assert out.cross_page_designators == {"R2": ["p1", "p2"]}
    assert out.unproven_nets == {"+5V": ("pa", "pb")}
    assert out.repeated_designators() == ["R1", "R2"]
    assert out.unproven_pages("+5V") == ("pa", "pb")
    # A net nobody reported as welded stays unanswered, so the reading is not
    # "everything is unproven" either.
    assert out.unproven_pages("N1") is None
    # The rest of the model is still the reconciled one, and the input is not
    # the thing that comes back (the application stays immutable).
    assert _nets(out) == {"N1": {("a", "1"), ("a", "2")}}
    assert out is not candidate and out.nets is not candidate.nets
    # Copies, not aliases: a caller that mutates the result cannot reach back
    # into the model it handed over.
    out.duplicate_designators.append("R9")
    out.cross_page_designators["R2"].append("p3")
    assert candidate.duplicate_designators == ["R1"]
    assert candidate.cross_page_designators == {"R2": ["p1", "p2"]}


def test_11_an_empty_tuple_of_pages_is_still_an_answer_after_a_reconcile():
    """``()`` is "more than one page, ids unavailable" — ``None`` is "proven".

    The model's own docstring makes that distinction load-bearing, so it is the
    one an accidental rebuild is most likely to erase: an empty tuple is falsy,
    and a rebuild that filtered empties would turn a refusal back into a pass.
    """
    golden = _model(("N1", [("a", "1"), ("a", "2")]))
    candidate = _model(("N1", [("a", "1"), ("a", "2")]))
    candidate.unproven_nets = {"VCC": ()}

    out = reconcile_names(candidate, golden)

    assert out.unproven_nets == {"VCC": ()}
    assert out.unproven_pages("VCC") == ()
    assert out.unproven_pages("VCC") is not None
    assert unproven_nets(out, ("VCC",)) == [("VCC", ())]


def test_11_a_welded_chain_still_refuses_to_conclude_after_a_reconcile():
    """The fail-open, measured on the rule that exists to refuse.

    The per-page merge hands ``reconcile_names`` a model carrying the names it
    welded blind (``cli._merge_schematic_models``), and a model whose net is
    unproven makes ``arch-sense-bias-closure`` file UNKNOWN before it judges
    anything. Before this batch that refusal was erased by the reconcile — the
    same board came back with a VIOLATION, i.e. a conclusion drawn on a net the
    step before had just refused.
    """
    board, intent = _sense_board(order=SHUNT_FIRST)
    board.unproven_nets = {"U+": ("page-a", "page-b")}
    board.duplicate_designators = ["R17"]
    golden = _model_of(copy.deepcopy(board.components), {
        name: list(net.pins) for name, net in board.nets.items()
    })

    reconciled = reconcile_names(board, golden)
    outcome, _severity, _target = _sense_row(reconciled, intent)

    assert reconciled.duplicate_designators == ["R17"]
    assert outcome.state == "UNKNOWN", outcome.message
    assert UNPROVEN_BY_NAME in (outcome.missing_fact or "")
    assert "page-a" in outcome.message and "page-b" in outcome.message


# ---------------------------------------------------------------------------
# #2: an approval that is no longer true is withdrawn
# ---------------------------------------------------------------------------


def _audit_scenario() -> tuple[DesignModel, DesignModel]:
    """The audit's end-to-end input: one candidate net wants a name it must not take.

    Golden ``N1``'s cluster is the candidate's ``N2``, so ``N2`` should take
    ``N1`` — but the candidate already carries a net called ``N1`` (``c.1/c.2``,
    a cluster the golden never named), so #46's rule abandons that rename. The
    candidate's ``W`` is golden ``N2``'s cluster, which the pass-1 plan approved
    because ``N2`` looked like it was vacating. Withdrawing ``N2``'s rename
    leaves ``W``'s approval pointing at a name that is now occupied.
    """
    golden = _model(
        ("N1", [("a", "1"), ("a", "2")]),
        ("N2", [("b", "1"), ("b", "2")]),
        ("KEEP", [("r", "1"), ("r", "2")]),
    )
    candidate = _model(
        ("W", [("b", "1"), ("b", "2")]),
        ("N2", [("a", "1"), ("a", "2")]),
        ("N1", [("c", "1"), ("c", "2")]),
        ("KEEP", [("r", "1"), ("r", "2")]),
    )
    return golden, candidate


def test_2_the_audit_scenario_no_longer_welds_two_nets_into_one():
    """``N2`` came back with four pins: ``b.1, b.2, a.1, a.2`` — one net, two circuits.

    Before this batch: ``plan = {'W': 'N2', 'KEEP': 'KEEP'}`` with one ``skipped``
    line, and ``reconcile_names`` produced a net called ``N2`` holding both
    clusters (the audit's WELD). Both renames must now give way together: the
    second refusal is the one the pass-1 plan never re-checked.
    """
    golden, candidate = _audit_scenario()
    records: list[str] = []

    plan = plan_membership_renames(
        golden.nets, candidate.nets, respect_golden_names=False, skipped=records
    )
    reconciled = reconcile_names(candidate, golden, skipped=[])

    # ``KEEP`` is also in the plan as a self-rename (pass 1 records a candidate
    # cluster that already carries its golden name; it changes nothing). What
    # must not survive is a rename that *moves* a name.
    assert {name: match for name, match in plan.items() if name != match} == {}, plan
    assert records == [
        "rename 'N2' -> 'N1' skipped: the candidate already carries a net called 'N1'",
        "rename 'W' -> 'N2' skipped: the candidate already carries a net called 'N2'",
    ], records
    assert _nets(reconciled) == {
        "W": {("b", "1"), ("b", "2")},
        "N2": {("a", "1"), ("a", "2")},
        "N1": {("c", "1"), ("c", "2")},
        "KEEP": {("r", "1"), ("r", "2")},
    }, _nets(reconciled)
    # The weld itself, stated as the property: no net grew a second cluster.
    assert [name for name, net in reconciled.nets.items() if len(net.pins) > 2] == []


def test_2_the_draw_path_and_the_calibration_path_still_agree_here():
    """One decision, two applications: neither shell may weld this input.

    The draw path is the ``respect_golden_names=True`` side and returns ``0``
    renames here (a candidate net that already carries a golden name is left
    alone), which is the same *answer* the calibration side now reaches — no
    rename survives that would put two clusters under one name.
    """
    golden, candidate = _audit_scenario()
    drawn = _model(*[(name, list(net.pins)) for name, net in candidate.nets.items()])
    records: list[str] = []

    renamed = _reconcile_derived_names(golden, drawn, skipped=records)

    assert renamed == 0, records
    assert _nets(drawn) == _nets(candidate)
    assert [name for name, net in drawn.nets.items() if len(net.pins) > 2] == []


def test_2_a_cascade_of_withdrawn_approvals_reaches_the_fixed_point():
    """A second-order withdrawal: the re-check has to run until nothing changes.

    ``A`` may take ``B`` because ``B`` is taking ``C``; ``B``'s rename is then
    withdrawn (``C`` is a name the candidate keeps), so ``A``'s approval is
    stranded the moment after it was re-checked. One extra pass sees it; a
    three-deep chain is what makes "re-check once" and "iterate to a fixed
    point" different implementations.
    """
    golden = _model(
        ("A", [("p", "1")]),
        ("B", [("q", "1")]),
        ("C", [("r", "1")]),
    )
    candidate = _model(
        ("A", [("q", "1")]),   # golden B's cluster, and B is vacating
        ("B", [("r", "1")]),   # golden C's cluster, and C is ...
        ("C", [("s", "1")]),   # ... a name the candidate keeps. Rename refused.
    )

    plan = plan_membership_renames(golden.nets, candidate.nets)
    reconciled = reconcile_names(candidate, golden)

    assert plan == {}, plan
    assert _nets(reconciled) == _nets(candidate)


# ---------------------------------------------------------------------------
# #6: the sense shunt is read by role, not by list order
# ---------------------------------------------------------------------------


def test_6_the_same_board_in_two_pin_orders_gives_one_verdict_and_one_evidence_string():
    """The determinism pin: permuting ``nets['U+']`` may not move the row.

    Before this batch the two orders gave ``ERROR``/``VIOLATION`` (0.1 Ω first)
    and ``WARN``/``VIOLATION`` (100 kΩ first, "比值存疑") with two different
    evidence strings, one of which named the bleed-down as the sense shunt.
    """
    first, intent = _sense_board(order=SHUNT_FIRST)
    second, _same = _sense_board(order=BLEED_FIRST)

    outcome_a, severity_a, _t = _sense_row(first, intent)
    outcome_b, severity_b, _t = _sense_row(second, intent)

    assert (outcome_a.state, severity_a) == (outcome_b.state, severity_b)
    assert outcome_a.message == outcome_b.message
    assert list(outcome_a.evidence) == list(outcome_b.evidence)
    # ... and the reading they agree on is the 0.1 Ω one, named as the shunt.
    assert (outcome_a.state, severity_a) == ("VIOLATION", "ERROR")
    shunt_lines = [line for line in outcome_a.evidence if line.startswith("采样电阻")]
    assert shunt_lines == ["采样电阻 Rsh = 0.1Ω @ U+ → GND"], shunt_lines
    assert "采样电阻 Rbleed" not in "\n".join(outcome_a.evidence)
    # The resistor inventory is part of the evidence, so its order is a reading
    # too: designator order, not the netlist's.
    inventory = [line for line in outcome_a.evidence if line.startswith("U+ 成员")][0]
    assert (
        "R17（10kΩ → VCC/2）、Rbleed（100kΩ → GND）、Rsh（0.1Ω → GND）" in inventory
    ), inventory
    assert "成员：R17.2, Rbleed.2, Rsh.2, U1.21" in inventory, inventory


def test_6_the_audit_shapes_a_bleed_down_first_is_never_a_pass():
    """The audit's flip, both halves, at the numbers that make it flip.

    ``R_th = 1k‖1k + 500m = 500.5 Ω``: against the real 0.1 Ω shunt that is a
    dead-heat violation, against the 100 kΩ bleed-down it is comfortably inside
    ``R_sense/10`` — which is why the same board read "偏置闭合成立" (``OK``) when
    the bleed was listed first, and ``ERROR`` when it was not.
    """
    first, intent = _sense_board(order=SHUNT_FIRST, rs="500m")
    second, _same = _sense_board(order=BLEED_FIRST, rs="500m")

    outcome_a, severity_a, _t = _sense_row(first, intent)
    outcome_b, severity_b, _t = _sense_row(second, intent)

    assert (outcome_a.state, severity_a) == ("VIOLATION", "ERROR")
    assert (outcome_b.state, severity_b) == ("VIOLATION", "ERROR"), (
        "the bleed-down is not the sense shunt, whatever the netlist lists first"
    )
    assert outcome_a.message == outcome_b.message
    assert "R_sense = 0.1Ω" in outcome_a.message
    assert outcome_a.message != "" and "形同虚设" in outcome_a.message


def test_6_a_declared_sense_part_is_the_one_the_contract_named():
    """The intent channel first: ``blocks[]`` says which part does the job.

    The declaration is quoted in the evidence, so "the contract was read" is a
    line a reader can check rather than a claim about the code path.
    """
    model, intent = _sense_board(
        order=BLEED_FIRST, blocks=[_sense_block(["Rsh", "U1"])]
    )

    outcome, severity, _t = _sense_row(model, intent)

    assert (outcome.state, severity) == ("VIOLATION", "ERROR")
    assert "采样电阻 Rsh = 0.1Ω @ U+ → GND（blocks[id='senseU'].parts 点名）" in (
        outcome.evidence
    )


def test_6_a_declaration_that_contradicts_the_smallest_resistor_is_refused():
    """Declaration vs structure, not decided here.

    The contract names the 100 kΩ bleed-down as this chain's sense part while
    the smallest resistor to ground is the 0.1 Ω shunt. Either reading is
    arguable and the choice is the engineer's, so the rule files UNKNOWN naming
    both numbers and both fixes — it does not pick.
    """
    model, intent = _sense_board(
        order=SHUNT_FIRST, blocks=[_sense_block(["Rbleed"])]
    )

    outcome, severity, _t = _sense_row(model, intent)

    assert outcome.state == "UNKNOWN", outcome.message
    assert "声明与结构矛盾" in outcome.message
    assert "Rbleed（100kΩ）" in outcome.message and "Rsh（0.1Ω）" in outcome.message
    assert "blocks[id='senseU'].parts" in outcome.message
    assert "blocks[id='senseU'].parts" in (outcome.missing_fact or "")
    assert outcome.missing_fact and "0.1Ω" in outcome.missing_fact


def test_6_a_declaration_about_another_part_does_not_hijack_the_shunt():
    """A ``current-sense`` block that names no candidate says nothing about it.

    ``U1`` is on the chain (the ADC pin) but is not a resistor to ground, so the
    declaration does not answer "which resistor is the shunt" — the reading
    falls back to the smallest one, and the block's own parts are not mistaken
    for it.
    """
    model, intent = _sense_board(order=BLEED_FIRST, blocks=[_sense_block(["U1"])])

    outcome, severity, _t = _sense_row(model, intent)

    assert (outcome.state, severity) == ("VIOLATION", "ERROR")
    shunt_lines = [line for line in outcome.evidence if line.startswith("采样电阻")]
    assert shunt_lines == ["采样电阻 Rsh = 0.1Ω @ U+ → GND"], shunt_lines
