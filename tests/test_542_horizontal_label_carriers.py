"""542-B1: a boundary **label** must be printed horizontally (S-20).

S-20 (`docs/schematic-style-spec.md`) says every word on the drawing reads
horizontally.  The landed page broke it four times, and the defect is not a
typography setting: the name's own box carries no orientation, so what the host
prints is decided by the **wire the label hangs on**.

Measured on the page before this batch (`.tmp_542/labels-before.json`, twelve
labels: eight flat, four upright, none missing a carrier):

==========  ======  =============  ==============
net         part    anchor         carrier
==========  ======  =============  ==============
LED_A       R9      (380, 550)     vertical stub
LED_K       U4      (495, 416)     vertical stub
LED_K       U5      (535, 208)     vertical stub
VFB_NF      R10     (80, 550)      vertical stub
==========  ======  =============  ==============

The three nets are `feedback`'s two LED rails and `control`'s divider tap; their
pins point up or down, so `_stub_directions` offered the pin's own escape first
and the vertical stub that came out of it is what the host turned into
``rotate(-90)`` text.

**What the host reads, and why the anchor is not the measurement.**  A label is a
name on a **wire**, and `core.textmetrics.wire_name_box` (the model `readability`
grades and the render measured) anchors the name at the midpoint of the wire's
**longest straight run** and rows it along that run.  A carrier with a `94`-unit
vertical leg and a `94`-unit horizontal one therefore still prints upright,
because `max` keeps the **first** run — measured on this batch's own first
attempt, `LED_K` at `U4`.  So every reading below is taken from `wire_name_box`
on the label's own segment, never from "the anchor sits on a horizontal run".

**The mechanism.**  ``islandlayout._name_one_net`` keeps its old answer first
(pass 0, the full compass, unchanged) and adds a **repair** for labels only:

* pass 1 — a horizontal-only pass, consulted **only when pass 0's answer came out
  vertical**;
* if that finds nothing clear, a **bent** carrier: the vertical leg runs on to a
  clean corner and the name hangs on a horizontal leg whose length starts at the
  vertical span plus one grid step (so it is strictly the longer run) and is
  checked by `wire_name_box` itself;
* a **flag** is a library symbol, not a word: it has one pass and its compass is
  untouched.

The tests below are the readings:

* **the carriers** — all twelve labels' `wire_name_box` rows are wider than they
  are tall, i.e. the host prints them flat; the four old offenders are named, and
  the equal-length case that fooled the first attempt is pinned as its own test;
* **the first leg** — a bent carrier may not be built on a leg the search itself
  did not call clear; with that leg falsified, the label stays upright **and** the
  island says so in a note;
* **the connections** — twelve named wires, same ``(net, part)`` anchors, all
  **44** source pin feet still endpoints of a run of their own net;
* **the page's other readings** — no diagonal run, at most two bends per segment,
  no crossing between two nets, ten unchanged rail flags.

**What these tests are not.**  ``_name_one_net`` is still a preference-ordered
search, not a global guarantee: an island whose only clear ways out are vertical
— with no clean corner to bend at — keeps a rotated name and a note saying so.  So
nothing here claims 「all layouts are horizontal」.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from boardwise.core import textmetrics as tm
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: Every label the page carries, as ``(net, part whose pin it hangs on)``.
LABELS = (
    ("SW", "D1"),
    ("GATE", "Q1"),
    ("SEC_SW", "D3"),
    ("LED_A", "R9"),
    ("LED_K", "U4"),
    ("SW", "T1"),
    ("COMP", "U5"),
    ("SEC_SW", "T1"),
    ("LED_A", "U5"),
    ("LED_K", "U5"),
    ("COMP", "C10"),
    ("VFB_NF", "R10"),
)

#: The four labels that were upright before this batch: the anchor they had, and
#: the anchor the flat carrier puts them at now.  A label is a name hanging past
#: its stub, so flattening it **must** move it.
OLD_VERTICAL = (
    ("LED_A", "R9", (380.0, 380.0), (373.0, 350.0)),
    ("LED_K", "U4", (495.0, 246.0), (515.0, 310.0)),
    ("LED_K", "U5", (535.0, 38.0), (520.0, 25.0)),
    ("VFB_NF", "R10", (80.0, 380.0), (58.0, 350.0)),
)

#: The page's ten rail flags, as ``(net, rotation)``: S-20 is a rule about words,
#: so this batch must not redraw a symbol.
FLAGS = (
    ("HVDC", 0.0),
    ("PGND", 0.0),
    ("SEC_12V", 0.0),
    ("SEC_GND", 0.0),
    ("SEC_12V", 0.0),
    ("SEC_GND", 0.0),
    ("HVDC", 0.0),
    ("PGND", 0.0),
    ("SEC_GND", 0.0),
    ("PGND", 180.0),
)

#: How many pin feet the source netlist states on this document.
SOURCE_PIN_FEET = 44

#: The page's printed rows — unchanged by this batch, pinned so "flat labels"
#: cannot be bought by dropping a part's text.
PAGE_ROWS = 37


def _library(stem: str) -> dict[str, SymbolProfile]:
    payload = json.loads((SPECS / f"{stem}.library.json").read_text(encoding="utf-8"))
    book: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        profile = SymbolProfile.from_dict(entry)
        book[profile.symbol_ref] = profile
    return book


def _inputs():
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        _library("flyback_uc3845"),
    )


@pytest.fixture(scope="module")
def page():
    """The real page, through the compiler entry the landed page used."""
    circuit, presentation, book = _inputs()
    result = dc.compile(
        circuit, presentation, book, dc.CompileBudget(max_candidates=64),
    )
    assert result.ok, [item.detail for item in result.failures]
    assert len(result.candidates) == 1, len(result.candidates)
    return result.candidates[0], circuit, book


# --------------------------------------------------------------- the readings


def _is_horizontal(a, b) -> bool:
    return abs(a[1] - b[1]) <= 1e-9 and abs(a[0] - b[0]) > 1e-9


def _is_vertical(a, b) -> bool:
    return abs(a[0] - b[0]) <= 1e-9 and abs(a[1] - b[1]) > 1e-9


def _carrier(plan, label):
    """The one segment this label hangs on, and the row the **host** prints for it.

    The label's anchor is an end of its own net's wire — that is what makes the
    name join the wire at all — and the host rows the name along that wire's
    longest straight run: `wire_name_box`, the same function `readability` grades.
    """
    segments = [
        segment for segment in plan.segments
        if segment.net == label.net
        and (tuple(segment.points[-1]) == (label.x, label.y)
             or tuple(segment.points[0]) == (label.x, label.y))
    ]
    assert len(segments) == 1, (
        label.net, label.part_id, (label.x, label.y),
        [segment.points for segment in plan.segments if segment.net == label.net],
    )
    points = [tuple(point) for point in segments[0].points]
    row = tm.wire_name_box(points, label.net)
    assert row is not None, (label.net, points)
    return points, row


def _flat(points) -> bool:
    """Does the host print this label flat?  Read off the **run**, not the box.

    The reading is `core.textmetrics`' own: `_straight_runs` is the splitter
    `wire_name_box` uses (collinear touching pieces merged), the longest run is the
    one `max(..., key=len)` keeps, and `dy == 0` is the flat case.  It is computed
    here from `textmetrics` and `math.dist` on purpose — asking
    `islandlayout._longest_run` would let the code under test mark its own
    homework, and it would not notice the day that helper drifted from the host.

    The text box's *shape* is not a substitute either: on a vertical run the box is
    ``ROW``-by-``width``, which is "wider than tall" for any name shorter than the
    row height — see `test_a_short_name_on_a_vertical_run_is_not_flat`.
    """
    runs = tm._straight_runs([tuple(point) for point in points])
    if not runs:
        return False
    a, b = max(runs, key=lambda run: math.dist(run[0], run[1]))
    return abs(a[1] - b[1]) <= 1e-9


def _pins(plan, circuit, book) -> dict[str, tuple[float, float]]:
    poses = {
        part.part_id: il.SymbolPose(
            rotation=float(part.rotation), mirror=bool(part.mirror),
        )
        for part in plan.parts
    }
    origins = {part.part_id: (part.x, part.y) for part in plan.parts}
    return il._tips(book, circuit, poses, origins)


def _endpoints(plan) -> dict[str, set[tuple[float, float]]]:
    out: dict[str, set[tuple[float, float]]] = {}
    for segment in plan.segments:
        out.setdefault(segment.net, set()).add(tuple(segment.points[0]))
        out.setdefault(segment.net, set()).add(tuple(segment.points[-1]))
    return out


# ------------------------------------------------------------------- the tests


def test_every_label_on_the_page_is_printed_horizontally(page) -> None:
    """S-20 read off the host's own ruler: twelve labels, twelve flat rows."""
    plan, _circuit, _book = page

    assert len(plan.labels) == len(LABELS), [
        (label.net, label.part_id) for label in plan.labels
    ]
    assert sorted((label.net, label.part_id) for label in plan.labels) == sorted(LABELS)

    upright = []
    for label in sorted(plan.labels, key=lambda item: (item.net, item.part_id)):
        points, row = _carrier(plan, label)
        if not _flat(points):
            upright.append((
                label.net, label.part_id, (label.x, label.y), points, row,
            ))
    assert upright == [], (
        "labels the host still prints rotated (S-20 requires horizontal words): "
        f"{upright}"
    )


def test_the_four_anchors_that_were_vertical_are_named_and_flat(page) -> None:
    """The four old offenders, by net, part and anchor — not merely by count."""
    plan, _circuit, _book = page
    at = {(label.net, label.part_id): (label.x, label.y) for label in plan.labels}
    by_key = {(label.net, label.part_id): label for label in plan.labels}
    for net, part, old_anchor, new_anchor in OLD_VERTICAL:
        key = (net, part)
        assert key in at, f"{key}: the label this batch had to flatten is gone"
        assert at[key] != old_anchor, (
            f"{net}'s label at {old_anchor} (on {part}) did not move, so it cannot "
            "have changed carrier — it was upright before this batch"
        )
        assert at[key] == new_anchor, (key, at[key], new_anchor)
        points, row = _carrier(plan, by_key[key])
        assert _flat(points), (
            f"{net}'s label at {new_anchor} (on {part}) is still rowed upright: "
            f"path {points}, host row {row}"
        )


def test_a_horizontal_leg_as_long_as_the_vertical_one_is_not_flat(page) -> None:
    """The equal-length trap, pinned on the ruler that decides it.

    This batch's first attempt gave `LED_K` at `U4` a `94`-unit vertical leg and a
    `94`-unit horizontal one, and the anchor sat on the horizontal leg — so a
    reading taken at the anchor said "flat".  The host still printed it upright,
    because `wire_name_box` rows the name along the **longest** run and `max`
    keeps the first of two equals.  The counterexample is stated on synthetic
    points (no net, no page coordinate), and the page's own two-leg carriers are
    then required to be **strictly** longer on the horizontal leg.
    """
    equal = [(0.0, 0.0), (0.0, 94.0), (94.0, 94.0)]
    assert not _flat(equal), (
        "a 94/94 carrier must still read upright — `max` keeps the vertical run; "
        f"if this is flat the host rule has changed: {tm.wire_name_box(equal, 'EQUAL')}"
    )
    longer = [(0.0, 0.0), (0.0, 94.0), (104.0, 94.0)]
    assert _flat(longer), (longer, tm.wire_name_box(longer, "LONGER"))

    plan, _circuit, _book = page
    bent = []
    for label in plan.labels:
        points, _row = _carrier(plan, label)
        if len(points) <= 2:
            continue
        vertical = sum(
            abs(b[1] - a[1]) for a, b in zip(points, points[1:]) if _is_vertical(a, b)
        )
        horizontal = sum(
            abs(b[0] - a[0]) for a, b in zip(points, points[1:]) if _is_horizontal(a, b)
        )
        assert horizontal > vertical, (label.net, label.part_id, points)
        bent.append((label.net, label.part_id, horizontal, vertical))
    assert bent, "no two-leg carrier on this page — the rule above is untested"


def test_the_stub_verdict_covers_every_leg_of_the_path() -> None:
    """`_stub_leg_hits` judges the **whole** path, not just its last leg.

    This is the measuring instrument review point 2 turns on: the bent carrier's
    first leg is the stub the search already drew, and the repair may only extend
    it if *that* leg is clean.  The two legs below are separated so that an
    obstacle can touch one and not the other, and the verdict is then read for the
    whole path and for each leg alone.  Synthetic points on purpose — no net and no
    page coordinate — so what is pinned is the rule, not this document.
    """
    first = ((0.0, 0.0), (0.0, 40.0))
    second = ((0.0, 40.0), (60.0, 40.0))
    on_first_only = (0.0, 20.0)          # the second leg runs at y = 40
    on_second_only = (30.0, 40.0)        # the first leg runs at x = 0

    def hits(legs, far, *, tips=(), runs=(), bodies=()):
        return il._stub_leg_hits(
            list(legs), far,
            foreign_runs=list(runs), foreign_tips=list(tips),
            own_runs=[], hard_boxes=list(bodies), others=[], texts=[],
        )

    clean = hits([first, second], second[1])
    assert not any(clean), clean

    # A foreign pin tip on the **first** leg: the whole path is refused, the second
    # leg on its own is not, and the first leg on its own is — so a check that
    # looked only at the last leg would wave this carrier through.
    only_first_leg = hits([first], first[1], tips=[("X.1", on_first_only)])
    assert only_first_leg[1] is True, only_first_leg
    only_second_leg = hits([second], second[1], tips=[("X.1", on_first_only)])
    assert not any(only_second_leg), (
        "the fixture is wrong: that tip must not touch the second leg"
    )
    whole = hits([first, second], second[1], tips=[("X.1", on_first_only)])
    assert whole[1] is True, whole

    # The same statement for a body the first leg runs through.
    body = (-2.0, 15.0, 2.0, 25.0)
    assert hits([first], first[1], bodies=[body])[3] is True
    assert not any(hits([second], second[1], bodies=[body]))
    assert hits([first, second], second[1], bodies=[body])[3] is True

    # And an obstacle on the second leg is seen from the whole path too.
    assert hits([first, second], second[1], tips=[("X.1", on_second_only)])[1] is True


def test_a_short_name_on_a_vertical_run_is_not_flat() -> None:
    """Why the direction is read from the run and not from the text box's shape.

    On a vertical run `wire_name_box` returns a ``ROW``-by-``width`` box, so a
    one-character name comes back *wider than tall* — a shape test would call it
    flat while the host rows it upright.  The run reading is exact for both.
    """
    vertical = [(0.0, 0.0), (0.0, 40.0)]
    row = tm.wire_name_box(vertical, "A")
    assert row is not None
    box_is_wider = (row[2] - row[0]) > (row[3] - row[1])
    assert box_is_wider, (
        "the fixture no longer demonstrates the trap — a short name's vertical row "
        f"must look wider than tall: {row}"
    )
    assert not _flat(vertical), (vertical, row)

    horizontal = [(0.0, 0.0), (40.0, 0.0)]
    row_h = tm.wire_name_box(horizontal, "A")
    assert row_h is not None
    assert _flat(horizontal), (horizontal, row_h)


def _carrier_of(block, label):
    """The one segment of `block` that this label hangs on, as page points."""
    segments = [
        segment for segment in block.segments
        if segment.net == label.net
        and (tuple(segment.points[-1]) == (label.x, label.y)
             or tuple(segment.points[0]) == (label.x, label.y))
    ]
    assert len(segments) == 1, (label.net, label.part_id)
    return [tuple(point) for point in segments[0].points]


def _led_k(page):
    return [
        (block, label)
        for block in page.blocks
        for label in block.labels
        if label.net == "LED_K"
    ]


def test_a_bent_carrier_is_never_built_on_a_leg_that_is_not_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review point 2: the repair may not extend a leg the search refuses.

    `_stub_leg_hits` is the search's own electrical/clearance verdict for a path.
    The patch below is **stateful**, and that is the whole point of the test: the
    **first** time a single leg is asked keeps its real verdict, so pass 0 still has
    the clear upright answer the landed page has; every **re-ask** of that leg is
    refused — which is what pass 1's straight alternatives and the repair's
    first-leg check (`[(tip, corner)]`, the stub the search already drew) both are.  A repair that judged only the second leg would bend out of that
    refused stub and flatten the two `LED_K` names; the asserted outcome is an
    upright name with a note.  The counter proves the veto actually fired (an
    earlier version of this test blocked *every* vertical leg and never reached the
    repair at all, so it proved nothing).
    """
    original = il._stub_leg_hits
    asked: dict[tuple, int] = {}
    fired = {"count": 0}

    def veto_reasked_leg(legs, far, **kwargs):
        """Allow a single leg the **first** time it is asked; refuse any re-ask.

        Keyed on the leg's own endpoints, so `_name_one_net`'s two questions about
        one stub — "is this way out clear?" (pass 0) and "may I bend out of it?"
        (the repair's first-leg check, which re-asks exactly that leg) — get
        different answers.  Straight alternatives are re-asks too (pass 1 walks the
        same pin again), which is what keeps the repair the only remaining route.
        """
        hits = original(legs, far, **kwargs)
        if len(legs) == 1:
            key = (tuple(legs[0][0]), tuple(legs[0][1]))
            asked[key] = asked.get(key, 0) + 1
            if asked[key] > 1:
                fired["count"] += 1
                return (True,) + tuple(hits[1:])
        return hits

    monkeypatch.setattr(il, "_stub_leg_hits", veto_reasked_leg)
    circuit, presentation, book = _inputs()
    patched = il.island_page(circuit, presentation, book)

    labels = _led_k(patched)
    assert len(labels) == 2, [(label.net, label.part_id) for _b, label in labels]
    for block, label in labels:
        points = _carrier_of(block, label)
        assert len(points) <= 2, (
            f"{label.net} at {label.part_id} was bent out of a leg the search "
            f"refused: {points} — a carrier may not launder a finding"
        )
        if not _flat(points):
            assert any(
                label.net in note and "horizontal" in note for note in block.notes
            ), (
                f"{label.net} at {label.part_id} stays upright but the island does "
                f"not say so: {block.notes}"
            )
    assert fired["count"] > 0, (
        "the bent repair never asked for a second vertical leg — this test did not "
        "reach the rule it is about"
    )
    assert asked, "no vertical leg was ever judged"


def test_a_bent_carrier_is_never_taken_when_the_whole_path_is_not_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the same rule: the **second** leg is judged too.

    Here the patch refuses only paths with more than one leg, so every straight
    candidate (one leg) keeps its real verdict and the repair's first-leg check
    passes — but `_stub_cost(path2)` sees two legs and refuses the whole carrier.
    A repair that accepted a bent path on its first leg alone would flatten these
    names; the asserted outcome is again the upright name with the note, and the
    counter proves the second-leg veto fired.
    """
    original = il._stub_leg_hits
    fired = {"count": 0}

    def veto_multi_leg(legs, far, **kwargs):
        hits = original(legs, far, **kwargs)
        if len(legs) > 1:
            fired["count"] += 1
            return (True,) + tuple(hits[1:])
        return hits

    monkeypatch.setattr(il, "_stub_leg_hits", veto_multi_leg)
    circuit, presentation, book = _inputs()
    patched = il.island_page(circuit, presentation, book)

    labels = _led_k(patched)
    assert len(labels) == 2, [(label.net, label.part_id) for _b, label in labels]
    for block, label in labels:
        points = _carrier_of(block, label)
        assert len(points) <= 2, (
            f"{label.net} at {label.part_id} took a two-leg carrier whose second "
            f"leg the search refuses: {points}"
        )
        assert not _flat(points), (label.net, label.part_id, points)
        assert any(
            label.net in note and "horizontal" in note for note in block.notes
        ), (label.net, block.notes)
    assert fired["count"] > 0, (
        "no two-leg path was ever judged — this test did not reach the rule"
    )


def test_no_straight_way_out_is_not_rescued_by_a_bend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review point 3, simplified: a fault everywhere is a note, not a repair.

    With every leg refused, no straight candidate is clear, so the island falls
    back to the least-damaging answer it always had and says so.  What must *not*
    happen is a bend turning that fallback into a flat name: the repair runs only
    on an answer the search called clear, so this page still carries upright
    `LED_K` names with the note, and `_name_one_net` still reports "no clear way
    out" to its caller (which is what makes 532's rollback keep working).
    """
    original = il._stub_leg_hits

    def refused(legs, far, **kwargs):
        return (True,) + tuple(original(legs, far, **kwargs)[1:])

    monkeypatch.setattr(il, "_stub_leg_hits", refused)
    circuit, presentation, book = _inputs()
    page = il.island_page(circuit, presentation, book)      # must still build

    labels = [
        (block, label)
        for block in page.blocks
        for label in block.labels
        if label.net == "LED_K"
    ]
    assert len(labels) == 2, [(label.net, label.part_id) for _b, label in labels]
    for block, label in labels:
        segments = [
            segment for segment in block.segments
            if segment.net == label.net
            and (tuple(segment.points[-1]) == (label.x, label.y)
                 or tuple(segment.points[0]) == (label.x, label.y))
        ]
        assert len(segments) == 1, (label.net, label.part_id)
        points = [tuple(point) for point in segments[0].points]
        assert len(points) <= 2, (
            f"{label.net} at {label.part_id} was rescued by a bend although no "
            f"straight way out was clear: {points}"
        )
        assert any(
            label.net in note and "no clear way out" in note for note in block.notes
        ), block.notes


def test_the_named_wires_and_the_source_feet_are_unchanged(page) -> None:
    """Moving a label's carrier must not move a connection."""
    plan, circuit, book = page
    assert len(plan.labels) == 12
    assert sorted((label.net, label.part_id) for label in plan.labels) == sorted(LABELS)

    tips = _pins(plan, circuit, book)
    ends = _endpoints(plan)
    missing = []
    feet = 0
    for net in circuit.nets:
        for member in net.members:
            feet += 1
            part_id, _, token = member.partition(".")
            point = tips[il.IslandPin(part_id, token)]
            if tuple(point) not in ends.get(net.id, set()):
                missing.append((net.id, member, tuple(point)))
    assert feet == SOURCE_PIN_FEET, feet
    assert missing == [], missing

    assert len(plan.texts) == PAGE_ROWS, len(plan.texts)


def test_flat_words_do_not_buy_a_defect_on_the_page(page) -> None:
    """The page's other readings: no diagonal, <=2 bends, no crossing, same flags."""
    plan, _circuit, _book = page

    for segment in plan.segments:
        points = segment.points
        diagonal = [
            (a, b) for a, b in zip(points, points[1:])
            if abs(a[0] - b[0]) > 1e-9 and abs(a[1] - b[1]) > 1e-9
        ]
        assert diagonal == [], (segment.net, diagonal)
        assert len(points) - 2 <= 2, (segment.net, len(points) - 2, points)

    runs = [
        (segment.net, tuple(a), tuple(b))
        for segment in plan.segments
        for a, b in zip(segment.points, segment.points[1:])
    ]
    crossings = []
    for index, (net, a, b) in enumerate(runs):
        for other_net, c, d in runs[index + 1:]:
            if net == other_net:
                continue
            if _crossing((a, b, c, d)):
                crossings.append((net, other_net, (a, b), (c, d)))
    assert crossings == [], crossings

    assert [
        (flag.net, float(flag.rotation)) for flag in plan.power_symbols
    ] == list(FLAGS)


def _crossing(quad) -> bool:
    """Two perpendicular runs, each meeting the other's **open** interior (X or T)."""
    a, b, c, d = quad
    for first, second in (((a, b), (c, d)), ((c, d), (a, b))):
        (p, q), (r, s) = first, second
        if _is_horizontal(p, q) and _is_vertical(r, s):
            x_lo, x_hi = sorted((p[0], q[0]))
            y_lo, y_hi = sorted((r[1], s[1]))
            if x_lo + 1e-6 < r[0] < x_hi - 1e-6 and y_lo + 1e-6 < p[1] < y_hi - 1e-6:
                return True
    return False
