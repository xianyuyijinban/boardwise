"""039 批①b: the two `decap-required-caps` blind spots, pinned on both sides.

Both were found by curating real boards (批①), and both are about a *state* the
rule was reporting wrongly — not about a missing capability:

* **"a capacitor is there, its value was never written"** used to read as "no
  capacitor at all". The thesis board's C34 (C-prefixed, footprint `0603`, no
  value, no MPN, no C-number, `Name` attribute null) sits between the REF2033's
  VIN and AGND, and the rule said ``missing`` — a statement about the board that
  is false. Split: a cap-shaped part is a candidate with an unreadable value
  (``unreadable`` → UNKNOWN, naming the part), and only a net with no capacitor
  at all says ``missing``.
* **a capacitor with both terminals on one net** counted as a grounded
  decoupling candidate. The thesis board's C115 (`330uF`, both terminals AGND)
  "satisfied" the CH340N's VCC requirement on AGND. A candidate must now
  **bridge** the net to a different ground net, and a capacitor drawn closed on
  itself gets its own WARN.
* **and the boundary that keeps the second fix honest**: when the protected pin's
  own net *is* a ground net, this rule decides nothing — UNKNOWN, with the board
  fact named. The rule must not answer "a supply pin sits on a ground net" by
  measuring capacitors against it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.engines.addcomponent import probe_already_applied
from boardwise.rules.base import OUTCOME_STATES
from boardwise.rules.decap import (
    DecapRequiredCaps,
    _looks_like_capacitor,
    cap_candidates_on,
    decide_required_cap,
    looks_like_capacitor,
    same_net_capacitors_on,
)

PROV = "test datasheet, p.1, http://example.com/ds.pdf"
ROOT = Path(__file__).resolve().parents[1]
FOC_BOARD = ROOT / "tests" / "fixtures" / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
SHELF = ROOT / "blocklib" / "parts.json"


def _ic_entry(key: str = "ic.test", mpn: str = "TEST1", pins=("1",)) -> PartEntry:
    """One IC that requires 0.1uF on each pin it is given."""
    return PartEntry(
        key=key,
        mpn=mpn,
        lcsc="C1",
        category="ic.ldo",
        facts={
            "supply_pins": [
                {"pins": [pins[0]], "name": "VIN", "v_operating": [2.2, 5.5],
                 "provenance": PROV}
            ],
            "required_caps": [
                {"pin": pin, "value": "0.1uF", "provenance": PROV} for pin in pins
            ],
        },
    )


def _library(*entries: PartEntry) -> PartLibrary:
    return PartLibrary(parts=list(entries))


def _model(
    *,
    ic_nets=("RAIL",),
    caps=(),
    extra_parts=(),
) -> DesignModel:
    """A one-IC board: `U1` requiring 0.1uF on each of `ic_nets`, plus inventory.

    ``caps`` are ``(designator, value, mpn, lcsc, footprint, net_a, net_b)`` —
    every capacitor is a two-pin part, so a test can write the same net twice and
    mean what it says.
    """
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1",
        designator="U1",
        mpn="TEST1",
        lcsc_part="C1",
        pins=[Pin(str(i + 1), "VIN", net) for i, net in enumerate(ic_nets)],
    )
    net_pins: dict[str, list[tuple[str, str]]] = {}
    for i, net in enumerate(ic_nets):
        net_pins.setdefault(net, []).append(("U1", str(i + 1)))
    for designator, value, mpn, lcsc, footprint, net_a, net_b in caps:
        model.components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            value=value,
            mpn=mpn,
            lcsc_part=lcsc,
            footprint=footprint,
            pins=[Pin("1", "A", net_a), Pin("2", "B", net_b)],
        )
        net_pins.setdefault(net_a, []).append((designator, "1"))
        net_pins.setdefault(net_b, []).append((designator, "2"))
    for designator, footprint, net in extra_parts:
        model.components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            footprint=footprint,
            pins=[Pin("1", "A", net), Pin("2", "B", "GND")],
        )
        net_pins.setdefault(net, []).append((designator, "1"))
        net_pins.setdefault("GND", []).append((designator, "2"))
    model.nets = {
        name: Net(name, [(d, p) for d, p in sorted(pins)])
        for name, pins in net_pins.items()
    }
    return model


def _states(rule, model) -> dict[str, list]:
    """Outcome states for one model — or per board, for a project (040b)."""
    boards = getattr(model, "boards", None) or [model]
    grouped: dict[str, list] = {state: [] for state in OUTCOME_STATES}
    for board_model in boards:
        for outcome in rule.outcomes(board_model):
            grouped[outcome.state].append(outcome)
    return grouped


def _rows(rule, model):
    return rule._rows(model)  # noqa: SLF001 - the severity is half the claim


# ------------------------------------------------- the capacitor predicate


def test_a_cap_shaped_part_with_no_value_is_still_a_capacitor():
    """The C34 shape: `C7`, footprint `0603`, and nothing else to go on."""
    assert looks_like_capacitor("C7", "", "", "", None, footprint="0603")
    assert _looks_like_capacitor(
        Component(uid="c7", designator="C7", footprint="0603"), None
    )


def test_the_chip_size_route_needs_the_c_designator_and_a_size_only_footprint():
    """Neither signal alone: the golden board's lesson (a resistor wearing `U`)
    is why designator and shape are a conjunction, and why the footprint must be
    *only* a chip size."""
    assert not looks_like_capacitor("U1", "", "CH340G", "", None, footprint="0603")
    assert not looks_like_capacitor("R7", "", "", "", None, footprint="0603")
    assert not looks_like_capacitor("C7", "", "", "", None, footprint="SOT-23-5")
    assert not looks_like_capacitor("C7", "", "", "", None, footprint="")
    # A value or a decodable MPN code are still the stronger routes.
    assert looks_like_capacitor("C7", "100nF", "", "", None, footprint="SOT-23-5")
    assert looks_like_capacitor("C5", "", "CL10A225KA8NNNC", "", None)
    # ... and an MPN code alone still never claims a capacitor: the golden
    # board's U1 CH340G decodes as "34 pF" (existing test, kept here as the
    # neighbouring negative).
    assert not looks_like_capacitor("X1", "", "CL10A225KA8NNNC", "", None)


def test_a_cap_shaped_part_is_the_same_judgement_with_and_without_a_shelf():
    """apply's probe (no library in hand) and the rule (shelf in hand) must not
    disagree about what a capacitor is."""
    entry = PartEntry(key="cap.c7", mpn="", lcsc="C7", category="capacitor")
    library = _library(entry)
    assert looks_like_capacitor("C7", "", "", "", None, footprint="0603")
    assert looks_like_capacitor("C7", "", "", "", library, footprint="0603")


# ------------------------------- blind spot 1: unreadable is not "missing"


def test_a_capacitor_whose_value_is_not_declared_is_unreadable_not_missing():
    model = _model(
        caps=[("C34", "", "", "", "0603", "RAIL", "GND")],
    )
    states = _states(DecapRequiredCaps(library=_library(_ic_entry())), model)
    assert states["VIOLATION"] == []
    (unknown,) = states["UNKNOWN"]
    assert unknown.subject == "U1 pin1"
    assert "a capacitor is present" in unknown.message
    assert "C34" in unknown.message
    assert "cannot be checked" in unknown.message
    assert "C34" in unknown.missing_fact
    # ... and nothing on this board claims the capacitor is not there.
    assert "no grounded capacitor" not in unknown.message


def test_a_net_with_no_capacitor_at_all_still_says_missing():
    """The other half of the split — otherwise `unreadable` would have replaced
    the real finding instead of separating from it."""
    model = _model(extra_parts=[("R1", "0603", "RAIL")])
    states = _states(DecapRequiredCaps(library=_library(_ic_entry())), model)
    (violation,) = states["VIOLATION"]
    assert violation.subject == "U1 pin1"
    assert "no grounded capacitor found" in violation.message


def test_a_declared_value_and_a_decodable_mpn_are_unaffected():
    model = _model(
        caps=[
            ("C5", "2.2uF", "", "", "0603", "RAIL", "GND"),
            ("C9", "", "CL10A225KA8NNNC", "", "0603", "OTHER", "GND"),
        ],
        ic_nets=("RAIL",),
    )
    states = _states(DecapRequiredCaps(library=_library(_ic_entry())), model)
    assert [o.subject for o in states["OK"]] == ["U1 pin1"]
    assert "C5" in states["OK"][0].message


def test_the_decision_states_are_still_the_five_the_docstring_names():
    """`decide_required_cap` is the single decision both callers use; the fix
    changed what is *in* the inventory, not the states themselves."""
    from boardwise.rules.decap import CapCandidate

    unreadable = CapCandidate(designator="C34", footprint="0603", grounded=True)
    readable = CapCandidate(designator="C5", value="2.2uF", grounded=True)
    assert decide_required_cap("0.1uF", []).state == "missing"
    assert decide_required_cap("0.1uF", [unreadable]).state == "unreadable"
    assert decide_required_cap("0.1uF", [readable]).state == "satisfied"
    assert decide_required_cap("10uF", [readable]).state == "too_small"
    assert decide_required_cap("nonsense", [readable]).state == "unparseable"


# ------------------------- blind spot 2: a candidate must bridge two nets


def test_a_capacitor_from_the_rail_to_a_signal_net_is_not_a_decoupling_path():
    model = _model(caps=[("C4", "1uF", "", "", "0603", "RAIL", "NET2")])
    states = _states(DecapRequiredCaps(library=_library(_ic_entry())), model)
    assert [o.subject for o in states["VIOLATION"]] == ["U1 pin1"]
    assert "no grounded capacitor found" in states["VIOLATION"][0].message


def test_a_capacitor_with_both_terminals_on_the_rail_is_not_a_candidate():
    """The C115 shape, and the row that names it."""
    model = _model(caps=[("C115", "330uF", "", "", "0603", "RAIL", "RAIL")])
    rows = _rows(DecapRequiredCaps(library=_library(_ic_entry())), model)
    by_subject: dict[str, list] = {}
    for row in rows:
        by_subject.setdefault(row[0].subject, []).append(row)
    # No OK: the phantom is not a candidate, so the requirement is unmet.
    assert "OK" not in {row[0].state for row in by_subject["U1 pin1"]}
    assert any(
        "no grounded capacitor found" in row[0].message for row in by_subject["U1 pin1"]
    )
    # And the phantom gets its own WARN, which is the signal that it exists.
    (phantom,) = by_subject["C115"]
    outcome, severity = phantom[0], phantom[1]
    assert outcome.state == "VIOLATION" and severity == "WARN"
    assert "both terminals are on net 'RAIL'" in outcome.message
    assert "bridges nothing" in outcome.message
    assert "C115 @ RAIL (both terminals)" in outcome.evidence


def test_the_phantom_row_is_emitted_once_per_capacitor():
    """Two ICs sharing a rail examine the same net; the capacitor is still one
    fact about the board, so it is one row."""
    model = _model(
        ic_nets=("RAIL", "RAIL"),
        caps=[("C115", "330uF", "", "", "0603", "RAIL", "RAIL")],
    )
    lib = _library(_ic_entry(pins=("1", "2")))
    rows = _rows(DecapRequiredCaps(library=lib), model)
    phantom_rows = [row[0] for row in rows if row[0].subject == "C115"]
    assert len(phantom_rows) == 1


def test_cap_candidates_on_requires_a_bridge_and_same_net_sees_the_phantom():
    model = _model(caps=[("C115", "330uF", "", "", "0603", "RAIL", "RAIL")])
    assert cap_candidates_on(model, "RAIL") == []
    assert [c.designator for c in same_net_capacitors_on(model, "RAIL")] == ["C115"]


def test_applies_probe_agrees_the_phantom_does_not_satisfy():
    """`edit apply`'s idempotence probe calls the same two functions; if it
    disagreed, it would refuse to place a capacitor that is actually needed."""
    model = _model(caps=[("C115", "330uF", "", "", "0603", "RAIL", "RAIL")])
    decision = probe_already_applied(model, "RAIL", "0.1uF")
    assert not decision.satisfied
    assert decision.state == "missing"
    # ... and with a real bridging capacitor the probe agrees it is done.
    model = _model(caps=[("C5", "2.2uF", "", "", "0603", "RAIL", "GND")])
    assert probe_already_applied(model, "RAIL", "0.1uF").satisfied


def test_the_bridge_requirement_is_observable_in_the_inventory_itself():
    """Why the bridge lives in `cap_candidates_on` and not in the rule's row
    logic: a probe can point at **any** net, including a ground one, and a
    grounded-twice capacitor never satisfies anything.

    On the board this batch was measured on, the rule's own path never reaches
    this case — the ground-net boundary answers first — so this is the one place
    the requirement is observable on its own. A mutation of `_bridges_to_ground`
    back to "has a ground pin" turns exactly this test red.
    """
    model = _model(
        ic_nets=("AGND",),
        caps=[("C1", "330uF", "", "", "0603", "AGND", "AGND")],
    )
    assert cap_candidates_on(model, "AGND") == []
    assert [c.designator for c in same_net_capacitors_on(model, "AGND")] == ["C1"]
    decision = probe_already_applied(model, "AGND", "0.1uF")
    assert not decision.satisfied
    assert decision.state == "missing"


# -------------------- the boundary: a supply pin sitting on a ground net


def test_a_supply_pin_on_a_ground_net_is_unknown_and_named():
    """The thesis board's U5 pin5 shape. The rule used to answer OK here — the
    ground net is full of "grounded" capacitors. It must not decide at all, and
    it must say what it sees."""
    model = _model(
        ic_nets=("AGND",),
        caps=[("C115", "330uF", "", "", "0603", "AGND", "AGND")],
    )
    states = _states(DecapRequiredCaps(library=_library(_ic_entry())), model)
    assert states["OK"] == []
    assert states["VIOLATION"] == []
    (unknown,) = states["UNKNOWN"]
    assert unknown.subject == "U1 pin1"
    assert "ground net 'AGND'" in unknown.message
    assert "connectivity question" in unknown.message
    assert "AGND" in unknown.missing_fact


def test_the_ground_net_boundary_emits_no_phantom_row_for_that_net():
    """The boundary comes first: where the rule does not judge, it does not
    report capacitors either. Documented because the 批①b task book asked for a
    phantom WARN and this is the one place it is deliberately silent — the
    measured shape on that board is a *netlist* oddity (the PCB view of the same
    project has every one of those capacitors between +24V and PGND)."""
    model = _model(
        ic_nets=("AGND",),
        caps=[("C115", "330uF", "", "", "0603", "AGND", "AGND")],
    )
    rows = _rows(DecapRequiredCaps(library=_library(_ic_entry())), model)
    assert [o.subject for o, _ in rows] == ["U1 pin1"]


# ---------------------------------------------- the real board, end to end


def test_the_thesis_board_now_says_what_is_actually_there(capsys):
    """The board both blind spots were measured on, read for real.

    Two of its rows moved when 040 fixed the parser, and the moves are the
    point of the test: the CH340N's VCC pin used to read as sitting on the
    ground net 'AGND' (that reading *was* the page-welding bug, 039d), so the
    rule could only name the boundary; it now reads VCC and finds the 2.2uF cap
    that is really there. The REF2033's VIN still has a capacitor whose value
    was never filled in (UNKNOWN, named) instead of "no grounded capacitor
    found" — that blind spot is untouched, and so is the board's one real
    violation.
    """
    from boardwise.core.parts import load_parts

    model, _ = cli._load_model(FOC_BOARD, view="schematic")
    states = _states(DecapRequiredCaps(library=load_parts(SHELF)), model)
    unknown = {o.subject: o for o in states["UNKNOWN"]}
    ok = {o.subject: o for o in states["OK"]}
    assert "U5 pin5" in ok, "040: the CH340N's VCC pin is on VCC now, not AGND"
    assert "VCC" in ok["U5 pin5"].message and "C36" in ok["U5 pin5"].message
    assert "U5 pin5" not in unknown
    assert "U9 pin4" in unknown
    assert "C34" in unknown["U9 pin4"].message
    assert "cannot be checked" in unknown["U9 pin4"].message
    assert not any(
        "no grounded capacitor" in o.message and "C34" in o.message
        for o in states["VIOLATION"]
    )
    # The board's one real violation is untouched by either fix.
    assert [o.subject for o in states["VIOLATION"]] == ["U11 pin5"]
