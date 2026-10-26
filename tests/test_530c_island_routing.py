"""530C: the island's own wiring — S-09, S-11, the two filters, and the name row.

The batch's contract is ``evidence/523/DESIGN.md`` §6.1 (three keys and a hard
ceiling), §6.2 (two promises promoted from scoring to filtering, each relaxation
accounted), §6.3 (the stub band), §6.5 item 2 (the stub's direction and the row
the **host** prints) and §9.1's F group.  This file measures each clause:

**F. wiring** — no diagonal (S-08); no foreign body crossed and no foreign pin
tip run over (T1); no segment with more than two bends, and a link that cannot
be routed inside that ceiling is *cut and named* rather than drawn badly (S-09);
most links are one straight run (S-09's own statistics); true crossings counted
as crossings and collinear overlaps not counted as them (S-11).

**H. the switch** — the **work item 3 finding**: a wire's net name is not
something the host decides to print, it is something the *landing* asks for.  An
EasyEDA Pro wire primitive carries a ``Net`` property and an ``ATTR key="NET"``
child with ``keyVisible: false, valueVisible: true``; the editor prints the row
when that value is not empty.  ``sch.place_wire`` takes ``net`` as an optional
parameter, so ``draw apply`` chooses per wire, and it already does — for the nets
a power flag names (``drawapply.unnamed_nets``, 069 sec.9).  530D landed 岳's ruling
A on top of that switch (`docs/schematic-style-spec.md` §七.5): a wire carries a name
exactly when the wire **is** the label, so the three tests at the end of this file
pin the switch, the per-wire rule the landing reads and the row model it drives,
offline and without the bridge.

**What is *not* here, and why** — `DESIGN` §6.3's 20-55 stub band.  It was
implemented, run and taken back out: clamping the stub ladder to ``stub_max = 55``
took the real page's hard violations 8 → 9 and its area/part 2.99x → 3.14x, past
the budget `test_520n` guards, because `bridge` is a two-part island with eight
crossing names that need the far rung.  The reading is pinned in
``test_the_boundary_stub_ladder_is_the_designs_and_its_band_is_the_gap`` with the
measurement written down; a test that asserted "20 ≤ stub ≤ 55" would be a test
that had to be given a lie to pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.changeplan import ChangePlan, PlanChange, PlanDrawFlag, PlanDrawWire
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawapply
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"


def _library(stem: str) -> dict[str, SymbolProfile]:
    payload = json.loads(
        (SPECS / f"{stem}.library.json").read_text(encoding="utf-8")
    )
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


def _flyback() -> tuple[CircuitSpec, PresentationSpec, dict[str, SymbolProfile]]:
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


def _page():
    circuit, presentation, book = _flyback()
    return il.island_page(circuit, presentation, book), circuit, presentation, book


def _bends(points) -> int:
    return max(0, len(points) - 2)


# ----------------------------------------------------- F: wiring (S-08 - S-13)


def test_no_segment_is_diagonal_on_a_placed_island() -> None:
    """S-08, hard: a diagonal is *impossible*, not merely penalised.

    ``_tidy`` refuses a candidate the moment a segment is not axis-aligned
    (`Oblique > Manhattan` in `docs/schematic-style-spec.md`), so this is a check
    that the refusal is still wired in rather than a check that nobody happened
    to draw one.
    """
    page, _circuit, _presentation, _book = _page()
    plan = page.plan()
    assert plan.segments, "the fixture drew no wire, so this measures nothing"
    for segment in plan.segments:
        for a, b in zip(segment.points, segment.points[1:]):
            assert abs(a[0] - b[0]) < 1e-9 or abs(a[1] - b[1]) < 1e-9, (
                f"{segment.net} has the oblique run {a} -> {b}"
            )
    assert il._tidy([(0.0, 0.0), (10.0, 10.0)]) is None


def _field(**overrides) -> il._Field:
    base = dict(extents=(), bodies=(), pins=(), leads=())
    base.update(overrides)
    return il._Field(**base)


def test_a_pin_tip_a_link_can_avoid_is_avoided() -> None:
    """T1: "runs over a foreign pin tip" is a **filter**, not a fine.

    Hand-built: the direct L through ``(100, 0)`` runs over a foreign pin tip at
    ``(50, 0)`` — the editor joins what it touches, so that candidate is a short.
    The other L is longer and has no other fault, and before 530C the tip hit was
    only the *second* key, i.e. beatable.  Now it is a tier.
    """
    field = _field(pins=(("R9.2", (50.0, 0.0)),))
    routed = il._route((0.0, 0.0), (100.0, 50.0), field, detours=(60.0,))
    assert routed is not None
    path, tier, complaints = routed
    assert tier == 1, complaints
    assert complaints == []
    assert not any(
        il._on_run(a, b, (50.0, 0.0)) for a, b in zip(path, path[1:])
    ), f"{path} still runs over the foreign pin tip"


def test_a_pin_tip_no_candidate_can_avoid_is_a_tier_three_route_and_is_named() -> None:
    """§6.2: the relaxation is *accounted*, with the pin named.

    Both pins sit on one line and the foreign tip is between them, so every
    Manhattan candidate of this family is the same run.  The route is returned
    (a local picture with a wire in it says more than one with a gap), the tier
    says which promise was dropped, and the complaint says **which** pin.
    """
    field = _field(pins=(("R9.2", (50.0, 0.0)),))
    routed = il._route((0.0, 0.0), (100.0, 0.0), field, detours=())
    assert routed is not None
    path, tier, complaints = routed
    assert tier == 3, (tier, complaints)
    assert any("R9.2" in text for text in complaints), complaints
    assert any("short" in text for text in complaints), complaints
    assert path == [(0.0, 0.0), (100.0, 0.0)]


def test_a_foreign_conductor_a_vertex_lands_on_is_a_tier_two_route_and_is_named() -> None:
    """§6.2's middle tier, and it names the net whose conductor it lands on.

    A foreign run lies across both L-shapes' corners; the route that has to be
    taken lands a vertex on it.  T2 (no body crossed, no pin tip run over, but a
    conductor joined) is exactly that state, and the note has to be readable:
    ``_wire_net`` writes it into `IslandBlock.notes`.
    """
    foreign = [("CLAMP_B", [(50.0, 0.0), (50.0, 100.0)])]
    # The vertical is 50, so both L-shapes put a corner on CLAMP_B's run.
    routed = il._route(
        (0.0, 0.0), (100.0, 50.0), _field(), detours=(),
        foreign=foreign,
    )
    assert routed is not None
    path, tier, complaints = routed
    assert tier == 1, (path, tier, complaints)
    # With a detour the corner can be moved off the run: T1 again.
    routed = il._route(
        (0.0, 0.0), (50.0, 50.0), _field(), detours=(), foreign=foreign,
    )
    assert routed is not None
    _path, tier, complaints = routed
    assert tier == 2, (tier, complaints)
    assert any("CLAMP_B" in text for text in complaints), complaints


def test_true_crossings_are_counted_and_collinear_runs_are_not() -> None:
    """S-11's predicate, which had no enforcer at all before this batch.

    ``_run_overlap`` reads only collinear runs, so two nets crossing at right
    angles cost nothing; ``_true_crossing`` is the reading that was missing, and
    the three cases below are the three that have to be told apart: a real cross
    (yes), two runs lying on each other (no — that is an overlap), and a meeting
    at an end point (no — that is a T, and a T is `landing`/`pin_hits`).
    """
    assert il._true_crossing((0.0, 0.0), (10.0, 0.0), (5.0, -5.0), (5.0, 5.0))
    assert not il._true_crossing((0.0, 0.0), (10.0, 0.0), (0.0, 0.0), (10.0, 0.0))
    assert not il._true_crossing((0.0, 0.0), (10.0, 0.0), (10.0, 0.0), (10.0, 5.0))
    assert not il._true_crossing((0.0, 0.0), (10.0, 0.0), (5.0, 0.0), (5.0, 5.0))


def test_no_drawn_segment_bends_more_than_twice() -> None:
    """S-09's hard ceiling, read off the real page.

    ``ROUTE_MAX_BENDS`` is 2 and the family is built so no candidate can exceed
    it (an L bends once, a Z twice) — so the ceiling is a construction invariant
    here, and this is the assertion that keeps it one.
    """
    page, _circuit, _presentation, _book = _page()
    plan = page.plan()
    worst = max(_bends(segment.points) for segment in plan.segments)
    assert worst <= il.ROUTE_MAX_BENDS, worst
    assert il._bends([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (2.0, 1.0), (2.0, 2.0)]) == 3


def test_more_than_two_bends_is_refused_and_the_link_is_cut_with_a_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S-09's degradation: 「超过改用标签切断」 — cut, not drawn badly.

    The ceiling is enforced by ``_bends``, so this lies to ``_bends`` and every
    candidate in the family is refused.  What must happen then is ``DESIGN``
    §4 criterion 3: the link is **not drawn**, and the island says so at both
    ends — a page that drew it anyway would be a page whose ceiling is a comment.
    """
    page, circuit, presentation, book = _page()
    before = len(page.plan().segments)
    monkeypatch.setattr(il, "_bends", lambda _path: il.ROUTE_MAX_BENDS + 1)
    cut = il.island_page(circuit, presentation, book)
    plan = cut.plan()
    assert len(plan.segments) < before, "the ceiling refused nothing"
    notes = [note for block in cut.blocks for note in block.notes]
    assert any("bend ceiling" in note for note in notes), notes
    assert any("not drawn" in note for note in notes), notes
    assert any("cut apart" in note for note in notes), notes


def test_most_wires_are_a_single_straight_run() -> None:
    """S-09's statistics: 66 % straight on the golden board, ≥ 50 % here.

    A proportion, not an equality — the target is "a reader can follow the
    wires", and one detour is not a failure.  Read on the real document.
    """
    page, _circuit, _presentation, _book = _page()
    plan = page.plan()
    straight = sum(1 for segment in plan.segments if _bends(segment.points) == 0)
    assert straight / len(plan.segments) >= 0.5, (straight, len(plan.segments))


def test_true_crossings_stay_under_the_pages_own_budget() -> None:
    """S-11, with the design's target and this batch's reading both written down.

    `DESIGN` §9.1 #22 asks for ≤ 2 % of segments, which on a 39-segment island
    page means **zero** crossings.  530C takes the count from 3 to 2 (the key
    that ranks crossings was missing entirely before it) and does not reach zero:
    the two left are between links that are pin-to-pin straight lines with no
    alternative in this family.  So the budget is pinned at this batch's own
    reading and the gap is reported, rather than the number written to look like
    the target.
    """
    page, circuit, presentation, book = _page()
    plan = page.plan()
    checked = rb.check(plan, circuit, presentation, book)
    crossings = checked.soft_metrics["crossings"]
    assert crossings <= 2.0, crossings
    assert crossings / len(plan.segments) > 0.02, (
        "the design's 2 % target is now met — raise this to an assertion on 0"
    )


def test_the_boundary_stub_ladder_is_the_designs_and_its_band_is_the_gap() -> None:
    """`DESIGN` §6.3's band, and the measurement that kept it out.

    The ladder is ``stub + step * channel`` for ``slot_rungs`` steps — 30, 62, 94
    with the shipped budget.  §6.3 asks for that ladder to be clamped into
    ``[stub_min, stub_max] = [20, 55]``; clamping it was run on this document and
    the page went 8 → 9 hard violations and 2.99x → **3.14x** area/part, past the
    budget `test_520n` guards.  `bridge` is the reason: two parts, eight crossing
    names, and only the far rung clears them.

    So what is asserted is the ladder that ships and the fact that a rung above
    the band is **reached and reported** — never that the band holds.
    """
    page, _circuit, _presentation, _book = _page()
    budget = il.IslandBudget()
    ladder = tuple(
        budget.stub + step * budget.channel for step in range(budget.slot_rungs)
    )
    assert ladder[0] == 30.0, ladder
    lengths = {
        round(
            sum(abs(a[0] - b[0]) + abs(a[1] - b[1])
                for a, b in zip(segment.points, segment.points[1:])),
            6,
        )
        for segment in page.plan().segments
    }
    assert lengths & set(ladder), (sorted(lengths), ladder)
    assert max(lengths) > 55.0, "no stub reaches past §6.3's band any more"


def test_the_real_page_keeps_the_electrical_violations_at_zero() -> None:
    """§9.1 #18 / the delivery red line: nothing electrical, and the reading is pinned.

    ``wire-through-body``, ``netlist-partition-mismatch``, ``undeclared-junction``
    and ``required-pin-not-connected`` are all **0**; the page's whole hard count
    is 8 and every one of the eight is a text row the host prints (see the switch
    tests below).  530B read 10; 530C reads 8.

    532 adds a third row class to that set: ``pin-text-press``, a symbol's own pin
    name/number against another row of that same symbol. It is the class
    `readability` could not see before this batch — its `_text_boxes` had no pin
    text in it at all — and the page's reading was then **three** rows, all on the
    transformer (`T1`'s `2`/`5`/`5` against `T1`'s own `EE16_3+3_V02`).

    201H takes those three out the only way S-21 leaves: the value row is hidden
    (`islandlayout._clear_text_rows`'s own-pin half), because both rows are drawn
    at the symbol's own offsets and no placement can separate them. So this page
    now reads **zero** hard violations, and the electrical zero is still the point
    of the test.
    """
    page, circuit, presentation, book = _page()
    checked = rb.check(page.plan(), circuit, presentation, book)
    kinds = {item.kind for item in checked.hard_violations}
    assert kinds <= {"text-overlap", "text-on-wire", "pin-text-press"}, sorted(kinds)
    assert kinds == set(), (
        "201H: the transformer's value row is hidden, so the pin-text rows that "
        f"were the page's only hard readings are gone — read {sorted(kinds)}"
    )
    assert len(checked.hard_violations) == 0, len(checked.hard_violations)


def test_a_tier_two_route_is_written_into_the_islands_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§6.2's accounting, on the page rather than in the router.

    Every relaxation the router took has to be readable in `IslandBlock.notes` —
    a downgrade nobody can find is the 520o failure (「降级被静默」 was one of the
    three death sentences).  The real page needs no relaxed route today, so the
    router is made to report one and the note it writes is the assertion: it
    names the net, it says which tier, and it says what the relaxation means.
    """
    page, circuit, presentation, book = _page()
    assert not [
        note for block in page.blocks for note in block.notes if "route**" in note
    ], "the real page relaxed a route after all — read those notes first"

    original = il._route

    def always_tier_three(*args, **kwargs):
        routed = original(*args, **kwargs)
        if routed is None:
            return None
        path, _tier, complaints = routed
        return path, 3, complaints or ["a test forced this relaxation"]

    monkeypatch.setattr(il, "_route", always_tier_three)
    forced = il.island_page(circuit, presentation, book)
    tiers = [
        note for block in forced.blocks for note in block.notes if "route**" in note
    ]
    assert tiers, "a relaxed route was taken and nothing recorded it"
    nets = {segment.net for segment in forced.plan().segments}
    for note in tiers:
        assert any(f"net {net}:" in note for net in nets), note
        assert "tier 3" in note, note
        assert "not so a page can pass" in note, note


# -------------------------------------- H: the net-name switch (530C, 530D ruled)


def test_the_landing_names_a_wire_only_when_the_wire_is_the_label() -> None:
    """Work item 3's switch, **as 岳 ruled it** (2026-10-21, ruling A).

    530C found that a wire's ``Net`` is ours to write per wire; 530D lands the
    ruling that says what to write.  「名字只住在旗标/标签上」: a net the plan
    flags is named by the flag (069 sec.9) and a net the plan draws with no name
    at all is named by nothing, so both land **unnamed** — what is left named is
    the net the plan draws a label for, because on this host the label *is* a
    named wire (`sch.place_netlabel` is unusable, 029).

    The marker is the wire's own ``purpose``, which is where 057's stub and an
    island's boundary label both say what they are — so this is a set difference
    over the plan and not a count.
    """
    plan = ChangePlan(
        change=PlanChange(
            kind="draw-module",
            draw_wires=[
                PlanDrawWire(net="CLAMP", points=[(0.0, 0.0), (0.0, 10.0)]),
                PlanDrawWire(net="PGND", points=[(10.0, 0.0), (10.0, 10.0)]),
                PlanDrawWire(net="", points=[(20.0, 0.0), (20.0, 10.0)]),
                PlanDrawWire(
                    net="COMP", points=[(30.0, 0.0), (30.0, 10.0)],
                    purpose="name stub (057: stands in for a label this host cannot place)",
                ),
            ],
            draw_flags=[PlanDrawFlag(net="PGND", kind="Ground")],
        ),
    )
    unnamed = drawapply.unnamed_nets(plan)
    assert unnamed == {"CLAMP", "PGND"}, unnamed
    assert drawapply.named_wire_nets(plan) == {"COMP"}
    assert {wire.net for wire in plan.change.draw_wires} == {"CLAMP", "PGND", "", "COMP"}


def test_a_wire_prints_a_name_row_only_where_its_net_has_a_label() -> None:
    """The row model, both ways, on the rule the landing reads.

    ``readability._named_wire_rows`` models the row the host prints over a named
    wire, and since 530D "named" is per **wire**: ``core.layoutplan.
    label_wire_indices`` — the one statement both sides read.  Four plans, one
    difference each: a wire of an island-internal net brings **no** row; the same
    wire with a label at its far end brings one; a wire whose net has a label
    somewhere **else** (the label's anchor is not this segment's end) brings none,
    because this segment is a conductor and not the label; a wire with no net at
    all brings none.
    """
    point = (0.0, 0.0)
    far = (0.0, 40.0)

    def plan(net: str, *, label_at=None) -> object:
        return il.LayoutPlan(
            parts=[],
            segments=[il.LayoutSegment(net=net, points=[point, far])],
            labels=(
                [il.LayoutLabel(
                    net=net, text=net,
                    bbox=(label_at[0], label_at[1], label_at[0] + 20.0,
                          label_at[1] + 10.0),
                    x=label_at[0], y=label_at[1], part_id="",
                )] if label_at and net else []
            ),
        )

    assert rb._named_wire_rows(plan("CLAMP")) == []
    assert len(rb._named_wire_rows(plan("COMP", label_at=(0.0, 40.0)))) == 1
    assert rb._named_wire_rows(plan("COMP", label_at=(200.0, 200.0))) == []
    assert rb._named_wire_rows(plan("")) == []


def test_the_real_page_prints_a_name_only_on_the_wires_that_are_labels() -> None:
    """The same identity on the real document, both directions.

    Every row the gate models is a segment of a net the page labels; no flagged
    net and no island-internal net has one.  The count is what ruling A bought:
    the eight rows of the internal/flagged conductors are gone (8 hard violations
    → 1), and **531 took the last one out by moving `R7`** — the `LED_K` label's own
    row no longer lands on it, because the placement now knows the rows the host
    prints and the anchors it draws them at (`core.textmetrics.symbol_rows`,
    `evidence/531/report.md` §2).  So this page reads **zero** hard violations, and
    the identity assertions above are what this test still owns: a name printed on a
    conductor that is not its own net's label is still the defect 530C removed.
    """
    page, circuit, presentation, book = _page()
    plan = page.plan()
    flagged = {symbol.net for symbol in plan.power_symbols}
    labelled = {label.net for label in plan.labels}
    rows = rb._named_wire_rows(plan)
    assert {row[3] for row in rows} == labelled - flagged
    assert not (flagged & {row[3] for row in rows})
    assert not (rows and ({row[3] for row in rows} - labelled))
    unchecked = rb.check(plan, circuit, presentation, book)
    refusing, tolerated = dc.island_gate_violations(unchecked.hard_violations)
    assert not refusing, [item.render() for item in refusing]
    assert tolerated == [], (
        "201H: the transformer's value row is hidden, so the page carries no "
        f"tolerated row at all — {[item.render() for item in tolerated]}"
    )
