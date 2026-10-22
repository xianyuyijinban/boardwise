"""530F: the island page's **delivery policy** — what it may carry, and why.

================================ the question ================================

`DESIGN` §9.4's acceptance anchor for this batch is "zero hard violations" on the
real flyback island page, with 岳's ruling 2 (`§14.2`) naming the fallback: when
the drawing provably cannot get there, the page is delivered with the electrical
side at zero and a **bounded, named** count of the rows the *editor* prints.

This file pins the policy (`drawcompiler.ISLAND_GATE_TOLERATED_LIMITS` and
`drawcompiler.island_gate_violations`) as a rule, not as a relaxed constant:

1. **the electrical kinds never pass**, whatever the objects are;
2. a `text-on-wire` row the **host** prints is tolerated up to ten and named one
   by one — eleven is a refusal, and it takes all eleven with it;
3. `text-overlap` is tolerated only when the *text* is a host-printed row (the
   measured, layout-unsolvable residual 530D §3.3 proved) and only one of them —
   a box this compiler placed is the compiler's to move, so it stays hard;
4. end to end: the real flyback island page is delivered, and the one tolerated
   finding is named in `result.notes` **and** in the candidate's own evidence;
5. end to end: a `wire-through-body` on the same page still refuses it — the
   policy cannot be a way to deliver a drawing whose connectivity is wrong.

Nothing here touches the editor.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import SymbolProfile  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import readability  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"

#: The kinds 岳's ruling 2 names as the electrical side, plus the rest of the
#: eleven that are the same kind of fact (a drawing whose connectivity is not the
#: netlist's) — never a row the host prints.
ELECTRICAL_KINDS = (
    readability.KIND_WIRE_THROUGH_BODY,
    readability.KIND_NETLIST_PARTITION,
    readability.KIND_UNDECLARED_JUNCTION,
    readability.KIND_REQUIRED_PIN_NOT_CONNECTED,
    readability.KIND_NC_PIN_CONNECTED,
    readability.KIND_DANGLING_WIRE_END,
    readability.KIND_WIRE_ON_PIN_LINE,
    readability.KIND_OUT_OF_PAGE,
    readability.KIND_USER_LOCK_VIOLATED,
)


def _violation(kind: str, first: str, second: str = "parts[R7]") -> readability.HardViolation:
    return readability.HardViolation(
        kind=kind, objects=(first, second), evidence=f"synthetic {kind} for 530F",
    )


# ------------------------------------------------------------ 1 the electrical side


def test_every_electrical_kind_still_refuses_the_page():
    """岳's five names and the rest of the eleven: hard, whatever the objects.

    The objects are deliberately the **most forgiving** pair that exists — a host
    row (`segments[3]`) against a part — so the failure this test catches is a
    policy that tolerated by *object* alone instead of by kind **and** object.
    """
    violations = [_violation(kind, "segments[3]") for kind in ELECTRICAL_KINDS]
    refusing, tolerated = dc.island_gate_violations(violations)
    assert tolerated == []
    assert [item.kind for item in refusing] == list(ELECTRICAL_KINDS)


def test_the_keepout_conflict_is_refused_before_this_policy_is_asked():
    """S-01's other half is the packer's, not the gate's — stated as a fact here.

    `_try_island_variants` refuses a page whose blocks are still inside a keep-out
    **before** `readability.check` runs, so no entry in the policy can ever cover
    it.  This asserts the shape of that: the keep-out is not a readability kind at
    all, so a policy keyed on kinds cannot accidentally learn to tolerate it.
    """
    assert "keep-out" not in " ".join(readability.HARD_KINDS)
    assert readability.KIND_OUT_OF_PAGE in ELECTRICAL_KINDS, (
        "the half of S-01 the *gate* does own ('something leaves the page, or "
        "enters a keep-out region') is `out-of-page`, and it is in the hard set"
    )


# ------------------------------------------------- 2/3 the tolerated classes, bounded


def test_ten_host_rows_pass_and_eleven_refuse():
    """`text-on-wire` ≤ 10 — 520n's own ceiling, read as a bound (岳 ruling 2)."""
    ten = [_violation(readability.KIND_TEXT_ON_WIRE, f"segments[{i}]") for i in range(10)]
    refusing, tolerated = dc.island_gate_violations(ten)
    assert refusing == []
    assert len(tolerated) == 10

    eleven = [
        _violation(readability.KIND_TEXT_ON_WIRE, f"segments[{i}]") for i in range(11)
    ]
    refusing, tolerated = dc.island_gate_violations(eleven)
    assert tolerated == [], (
        "a class over its cap takes **every one of its lines** with it — the cap "
        "bounds a class, it does not ration it"
    )
    assert len(refusing) == 11


def test_a_host_row_over_a_part_is_tolerated_once_and_twice_refuses():
    """`text-overlap` on a host row: the measured residual, capped at one.

    530D §3.3 measured this class on the real page and found no layout-side answer
    (rungs 5 and 6 change the victim *and* break the 3.0× area budget), so one is
    tolerated.  Two is not: a second one is a page whose placement had room it did
    not use, which is a different finding.
    """
    one = _violation(readability.KIND_TEXT_OVERLAP, "segments[26]", "parts[R7]")
    refusing, tolerated = dc.island_gate_violations([one])
    assert refusing == []
    assert tolerated == [one]

    refusing, tolerated = dc.island_gate_violations([one, one])
    assert tolerated == []
    assert len(refusing) == 2


def test_a_text_overlap_between_boxes_this_compiler_placed_stays_hard():
    """The clause that makes the policy an accounting rule rather than a number.

    A `LayoutText`, a `LayoutLabel` and a flag's own glyph are boxes this generator
    positions; the page can move them, so the page has to.  Only the two rows the
    editor prints (`readability.is_host_printed_row`) are outside its reach.
    """
    ours = [
        _violation(readability.KIND_TEXT_OVERLAP, "texts[16]", "powerSymbols[2] name"),
        _violation(readability.KIND_TEXT_OVERLAP, "texts[3]", "texts[21]"),
        _violation(readability.KIND_TEXT_OVERLAP, "labels[4]", "parts[C11]"),
    ]
    # One at a time first: with the cap at one, a **single** box we placed would
    # slip through if the clause were keyed on the kind alone — and three at once
    # would not, because three is over the cap whatever the clause says.  So the
    # counting test cannot stand in for this one.
    for item in ours:
        refusing, tolerated = dc.island_gate_violations([item])
        assert tolerated == [], item.objects
        assert refusing == [item], item.objects
    refusing, tolerated = dc.island_gate_violations(ours)
    assert tolerated == []
    assert len(refusing) == 3

    # ... and a flag's own **name row** is a host row, while its glyph is not.
    assert readability.is_host_printed_row("powerSymbols[2] name")
    assert not readability.is_host_printed_row("powerSymbols[2]")
    assert readability.is_host_printed_row("segments[0]")
    assert not readability.is_host_printed_row("texts[0]")
    assert not readability.is_host_printed_row("labels[0]")


def test_the_tolerance_notes_name_every_tolerated_finding_verbatim():
    """"不许静默" — a tolerance nobody can enumerate is a gate that stopped looking."""
    two = [
        _violation(readability.KIND_TEXT_ON_WIRE, "segments[1]", "segments[2]"),
        _violation(readability.KIND_TEXT_OVERLAP, "segments[26]", "parts[R7]"),
    ]
    lines = dc.island_gate_tolerance_notes(two)
    assert len(lines) == 3, lines
    assert "text-on-wire 1" in lines[0] and "text-overlap 1" in lines[0]
    for item in two:
        assert f"tolerated: {item.render()}" in lines
    assert dc.island_gate_tolerance_notes([]) == [], (
        "a page with nothing tolerated says nothing: the header line is the "
        "account of a finding, not a banner"
    )


# ------------------------------------------------------------------ 4 end to end


def _flyback():
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json")
    payload = json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
    )
    book = {
        entry["symbolRef"]: SymbolProfile.from_dict(entry)
        for entry in payload["profiles"]
    }
    return circuit, presentation, book


def test_the_real_flyback_island_page_is_delivered_with_the_transformer_s_pin_text():
    """§9.4's acceptance anchor: `ok=True`, and **every** tolerated row named.

    When 530F landed this page it delivered with exactly one tolerated row — the
    `LED_K` label wire's own name row over `R7`, the residual 530C's router could not
    clear. 531 removed it by moving `R7`, not by widening the policy: the placement
    now measures the rows the **host** prints a part's designator and value in
    (`core.textmetrics.symbol_rows`) and gives them a pitch that fits, so the row has
    somewhere clear to be. The account read **empty** for one batch.

    532 re-pinned the reading and the sentence behind it is the policy's own: the
    checker can now see a part's **pin name and number** (`textmetrics.pin_rows`),
    so this page carries three rows it could not see before — the transformer's own
    typography over its own value row — and 530F's rule is what they are carried
    by. The acceptance anchor ("`ok=True`, every tolerated row named, the hard half
    empty") is unchanged; what moved is which rows there are to name.
    """
    circuit, presentation, book = _flyback()
    result = dc.compile(circuit, presentation, book, dc.CompileBudget(max_candidates=64))
    assert result.ok and result.candidates, (
        "the island page must be delivered under 530F's policy; failures: "
        f"{[item.detail[:300] for item in result.failures]}"
    )
    plan = result.candidates[0]
    assert plan.evidence.hard_violations == [], (
        "a delivered page's evidence states no hard violation — the tolerated "
        f"rows belong to the account, not to the hard half: "
        f"{plan.evidence.hard_violations}"
    )
    tolerated = [line for line in result.notes if line.startswith("tolerated: ")]
    assert len(tolerated) == 3, (
        "532: exactly the transformer's three pin-text rows, one line each — "
        f"{tolerated}"
    )
    assert all("[pin-text-press]" in line for line in tolerated), tolerated
    assert all("parts[T1]" in line for line in tolerated), tolerated
    assert not [
        line for line in plan.evidence.notes
        if line.startswith("tolerated: ") and "[pin-text-press]" not in line
    ], plan.evidence.notes
    assert len([
        line for line in plan.evidence.notes if line.startswith("tolerated: ")
    ]) == 3, plan.evidence.notes
    # The electrical side is empty, and the policy is what says so rather than the
    # page happening to have none.
    checked = readability.check(plan, circuit, presentation, book)
    refusing, tolerated_readings = dc.island_gate_violations(checked.hard_violations)
    assert refusing == [], refusing
    assert [item.kind for item in tolerated_readings] == ["pin-text-press"] * 3, (
        [item.render() for item in tolerated_readings]
    )


def test_a_wire_through_a_body_still_refuses_the_same_page(monkeypatch):
    """The policy cannot deliver a drawing whose connectivity is wrong.

    The real island page is clean on the electrical side, so the finding is
    injected: one `wire-through-body`, attached to the page the compiler is about
    to grade.  If this passes, `ok=True` above means what it says.
    """
    circuit, presentation, book = _flyback()
    real_check = readability.check

    def _with_a_body_hit(plan, *args, **kwargs):
        checked = real_check(plan, *args, **kwargs)
        checked.hard_violations.append(
            readability.HardViolation(
                kind=readability.KIND_WIRE_THROUGH_BODY,
                objects=("segments[0]", "parts[R7]"),
                evidence="injected by 530F to prove the electrical side is hard",
            )
        )
        return checked

    monkeypatch.setattr(readability, "check", _with_a_body_hit)
    result = dc.compile(circuit, presentation, book, dc.CompileBudget(max_candidates=64))
    assert not result.ok and not result.candidates
    joined = " ".join(item.detail for item in result.failures)
    assert "wire-through-body" in joined, joined[:300]
    assert "the island page was refused by the readability checker" in joined
    assert not [line for line in result.notes if line.startswith("tolerated: ")], (
        "a refused page tolerates nothing — the account belongs to a delivered one"
    )

def test_a_page_over_the_cap_is_refused_with_its_own_numbers(monkeypatch):
    """Eleven host rows refuse the page, and the refusal says how many."""
    circuit, presentation, book = _flyback()
    real_check = readability.check

    def _with_eleven_rows(plan, *args, **kwargs):
        checked = real_check(plan, *args, **kwargs)
        checked.hard_violations = [
            readability.HardViolation(
                kind=readability.KIND_TEXT_ON_WIRE,
                objects=(f"segments[{index}]", "segments[0]"),
                evidence="injected by 530F: one host row over the cap",
            )
            for index in range(11)
        ]
        return checked

    monkeypatch.setattr(readability, "check", _with_eleven_rows)
    result = dc.compile(circuit, presentation, book, dc.CompileBudget(max_candidates=64))
    assert not result.ok and not result.candidates
    reasons = " ".join(item.reason for item in result.rejected)
    assert "refused 11 hard violation(s)" in reasons, reasons[:400]
    assert len(result.rejected[0].violations) == 11, result.rejected[0].violations[:3]


# -------------------------------------------------- 5 the island's own name (530F)


def test_an_islands_name_round_trips_through_the_spec():
    """`LayoutIsland.name` is additive: stated writes it, unstated reads back `""`."""
    from boardwise.core import islands as islands_mod

    declared = ["Q1", "R5", "D3"]
    payload = [
        {"id": "primary", "parts": ["Q1", "R5"], "role": "primary", "name": "power stage"},
        {"id": "secondary", "parts": ["D3"]},
    ]
    read = islands_mod.parse_islands(payload, declared)
    assert [island.name for island in read] == ["power stage", ""], (
        "a name is read; an island that states none reads back empty"
    )
    assert read[0].role == "primary" and read[1].role == ""

    # unknown keys are still refused — `name` is an allowed key, not a hole
    with pytest.raises(islands_mod.IslandError):
        islands_mod.parse_islands(
            [{"id": "primary", "parts": ["Q1"], "label": "x"}], ["Q1"],
        )


def test_the_spec_writes_the_name_only_when_one_is_stated():
    """The dump's half: the same optional-key rule `role` follows."""
    from boardwise.core import islands as islands_mod

    everything = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json"
    ).to_jsonable()
    whole = everything["islands"]
    named, unnamed = whole[0], whole[1]
    named = dict(named, name="power stage")
    unnamed = {key: value for key, value in unnamed.items() if key != "name"}
    spec = PresentationSpec.from_dict(
        dict(everything, islands=[named, unnamed, *whole[2:]])
    )
    assert spec.effective_islands()[0].name == "power stage"
    written = spec.to_jsonable()["islands"]
    assert written[0]["name"] == "power stage"
    assert "name" not in written[1], (
        "a name nobody stated is not written — the same rule `role` follows"
    )
    again = PresentationSpec.from_dict(spec.to_jsonable())
    assert again.effective_islands()[0].name == "power stage"
    assert again.effective_islands()[1].name == ""


def test_draw_islands_apply_writes_the_accepted_name_into_the_spec():
    """530E's deviation 2, closed: the judged name reaches `islands[]`."""
    from boardwise.engines import islandproposal as ip

    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    # Two islands stay declared (and one of them is already named — 声明优先), the
    # other nine parts are proposed for: the proposal only ever covers undeclared
    # parts, and `parse_islands` refuses a document that leaves one out.
    payload["islands"] = [
        {"id": "primary", "role": "primary",
         "parts": ["Q1", "R5", "R4", "C6", "R3", "R15", "C5", "D1"]},
        {"id": "bridge", "role": "bridge", "parts": ["T1", "U5"], "name": "isolation"},
    ]
    proposal = {
        "proposalVersion": 1,
        "clusters": [{
            "islandId": "auto-1",
            "parts": [{"id": part} for part in
                      ["D3", "C11", "C13", "R7", "R8", "U4", "R9", "R10", "C10"]],
            "localNets": ["SEC_12V", "SEC_GND", "FB_SENSE"],
            "crossingNets": ["LED_A"],
            "evidence": {"anchorCandidate": "D3"},
        }],
        "judgement": [{
            "islandId": "auto-1", "verdict": "accept", "role": "secondary",
            "name": "rectifier", "reason": "D3 C11 C13 SEC_12V",
        }],
    }
    application = ip.apply_proposal(proposal, payload)
    assert application.result.written, application.result.report
    names = {island.id: island.name for island in application.spec.effective_islands()}
    assert names == {"primary": "", "bridge": "isolation", "auto-1": "rectifier"}, names
    written = application.spec.to_jsonable()["islands"]
    assert {item.get("name") for item in written if "name" in item} == {
        "isolation", "rectifier",
    }, written
    assert "name" not in written[0], (
        "the unnamed island writes no `name` key — the same rule `role` follows"
    )
    # the CLI's own report carries the same name — the third place it is readable
    reported = {item["islandId"]: item["name"]
                for item in application.result.report["islands"]}
    assert reported["auto-1"] == "rectifier"


def test_the_island_page_notes_report_the_name_it_was_given():
    """A block, a page plan and a compile result: one sentence, three places."""
    from boardwise.engines import islandlayout as il

    payload = json.loads(
        (SPECS / "flyback_uc3845.presentation.json").read_text(encoding="utf-8")
    )
    for island in payload["islands"]:
        if island["id"] == "bridge":
            island["name"] = "isolation"
    spec = PresentationSpec.from_dict(payload)
    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    payload = json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8")
    )
    book = {
        entry["symbolRef"]: SymbolProfile.from_dict(entry)
        for entry in payload["profiles"]
    }
    page = il.island_page(circuit, spec, book)
    notes = page.plan().notes
    assert any(il.island_name_note("bridge", "isolation") in note for note in notes), (
        [note for note in notes if "named" in note]
    )
    assert any(note.startswith("[bridge]") and "named" in note for note in notes), (
        "the note must be carried up with its island's id, like every other block "
        f"note — got {[note for note in notes if note.startswith('[')][:6]}"
    )
    assert not any(
        note.startswith("[primary]") and "is named '" in note for note in notes
    ), "an island the document did not name gets no name note"


if __name__ == "__main__":  # pragma: no cover - convenience only
    raise SystemExit(pytest.main([__file__, "-q"]))
