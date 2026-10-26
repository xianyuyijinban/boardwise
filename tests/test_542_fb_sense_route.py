"""542-V1: the feedback island's `FB_SENSE` must not be drawn inside a frame.

201H's page passed every gate with one reading nobody had turned into a test:
`FB_SENSE` left `R8.1`, ran to ``y = 360`` and then **91 units across `U4`'s own
body frame**, 0.5 unit inside its lower edge — and the `SEC_GND` boundary stub
that `_add_boundary_names` draws *after* the wiring fell across that run at
``x = 610`` with no junction dot.  A reader sees the TL431's reference line
shorted to ground, which is the worst kind of misread this page can produce.

Why the machine was green.  `islandlayout._crosses` measures a body crossing
with ``margin = 1.0`` — "a wire that touches a body's edge is a clearance
opinion" — so a run 0.5 unit *inside* the frame is not a crossing: key 1 of
`_route` reads 0, the candidate stays tier 1, and no note is written.  Among the
tier-1 candidates of that link it was also the shortest (180 against 241 for the
first channel below the part), so it won on key 12 as well.

The three tests below are the readings that were missing, and they are geometry
and netlist assertions rather than a count of hard violations:

* **inside a frame** — no `FB_SENSE` run lies inside any body box of its island,
  measured with ``margin = 0`` so 0.5 unit counts (the visual defect exactly as
  the 201H report measured it: 「整段落在框内 0.5 单位」);
* **no true crossing** — the page's own S-11 reading is zero, and the pair 542
  named is gone by name, not merely by index;
* **still the same net** — the page compiles, the delivery account is empty, and
  `FB_SENSE`'s drawn chain still ends on the tips of `R7.2`, `R8.1` and `U4.1`,
  i.e. the fix moved a conductor and not a connection.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"

#: The link the 201H page drew along `U4`'s frame, in the island's own frame:
#: `R8.1` at (100, 0) and `U4.1` at (-55, 5), the anchor `U4` at the origin.
FB_SENSE_PINS = ("R7.2", "R8.1", "U4.1")


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
    """The real page, through the compiler entry 201H used (one candidate)."""
    circuit, presentation, book = _inputs()
    result = dc.compile(
        circuit, presentation, book, dc.CompileBudget(max_candidates=64),
    )
    assert result.ok, [item.detail for item in result.failures]
    assert len(result.candidates) == 1, len(result.candidates)
    return result.candidates[0], circuit, presentation, book


def _bodies(plan, circuit, book) -> dict[str, tuple[float, float, float, float]]:
    """Every placed part's drawn body, in the plan's own coordinates."""
    out = {}
    for part in plan.parts:
        profile = book[circuit.part(part.part_id).symbol_ref]
        box = il.pose_box(
            profile.body, rotation=part.rotation, mirror=part.mirror,
            ox=part.x, oy=part.y,
        )
        if box is not None:
            out[part.part_id] = box
    return out


def test_the_edge_band_the_one_unit_margin_cannot_see() -> None:
    """The measurement the defect needed, stated on its own.

    `U4`'s body is 31 units tall and 91 wide.  A run 0.5 unit inside its lower
    edge, and a run exactly on it, are both ``_crosses``'s *no* (margin 1.0, the
    `wire-through-body` doctrine) and both this module's *yes* for S-10's 「不贴
    框」.  If this stops being true, the tests below stop measuring what they say
    they measure.
    """
    u4 = (-45.5, -15.5, 45.5, 15.5)
    inside = ((100.0, 15.0), (-55.0, 15.0))
    edge = ((100.0, 15.5), (-55.0, 15.5))
    for run in (inside, edge):
        assert not il._crosses(*run, u4), (
            "the 1-unit margin must still read this as no body crossing"
        )
        assert il._hugs(*run, u4), f"{run} is drawn in/on the frame"
    # One channel off the frame is the channel the router is allowed to take.
    assert not il._hugs((100.0, 45.5), (-55.0, 45.5), u4)
    # And a run that really goes through the interior is key 1's business, not
    # this one's: "hugging" must never be able to rank a body crossing.
    assert il._crosses((0.0, -20.0), (0.0, 20.0), u4)
    assert not il._hugs((0.0, -20.0), (0.0, 20.0), u4)


def test_fb_sense_is_not_drawn_on_or_inside_any_frame_of_its_island(page) -> None:
    """S-10 on the real page: no `FB_SENSE` run on or in a placed body.

    Read with :func:`boardwise.engines.islandlayout._hugs`, so a run hugging the
    inside of a frame *and* one lying on its edge are the same finding — that is
    what 201H's report measured and what the 1.0 margin let through.
    """
    plan, circuit, _presentation, book = page
    bodies = _bodies(plan, circuit, book)
    assert "U4" in bodies, sorted(bodies)
    hits = []
    for segment in plan.segments:
        if segment.net != "FB_SENSE":
            continue
        for start, end in zip(segment.points, segment.points[1:]):
            for part_id, box in bodies.items():
                if il._hugs(start, end, box):
                    hits.append((segment.points, part_id, box))
    assert not hits, [
        f"FB_SENSE is drawn on/inside {part_id}'s frame at {box} — run {points}"
        for points, part_id, box in hits
    ]


def test_fb_sense_and_sec_gnd_cross_nowhere_on_the_page(page) -> None:
    """S-11 on the page: `crossings` is 0, and the two nets 542 named are clear.

    The crossing 201H shipped was between `FB_SENSE`'s horizontal run and the
    vertical `SEC_GND` stub drawn at the island's boundary, and the plan had one
    junction, so no dot sat on it: a true crossing with no shared vertex, i.e.
    the reader's "the reference is shorted to ground".
    """
    plan, circuit, presentation, book = page
    assert rb._crossings(plan) == [], [
        (plan.segments[left].net, plan.segments[right].net, point)
        for left, right, point in rb._crossings(plan)
    ]
    checked = rb.check(plan, circuit, presentation, book)
    assert checked.soft_metrics["crossings"] == 0, checked.soft_metrics["crossings"]
    for left, right, point in rb._crossings(plan):
        names = {plan.segments[left].net, plan.segments[right].net}
        assert names != {"FB_SENSE", "SEC_GND"}, (names, point)


def test_the_page_still_compiles_and_fb_sense_is_still_one_net(page) -> None:
    """The fix has to move a conductor, not a connection.

    `dc.compile` returned one candidate (the fixture), the delivery account is
    empty, and the drawn `FB_SENSE` chain still ends on exactly the three pin
    tips the source netlist gives it — so a routing change cannot pass this file
    by cutting the net in two.
    """
    plan, circuit, presentation, book = page
    checked = rb.check(plan, circuit, presentation, book)
    refusing, tolerated = dc.island_gate_violations(checked.hard_violations)
    assert not refusing, [item.render() for item in refusing]
    assert tolerated == [], [item.render() for item in tolerated]

    poses = {
        part.part_id: il.SymbolPose(rotation=float(part.rotation),
                                    mirror=part.mirror)
        for part in plan.parts
    }
    origins = {part.part_id: (part.x, part.y) for part in plan.parts}
    tips = il._tips(book, circuit, poses, origins)
    expected = {tips[pin] for pin in (il.IslandPin(*name.split("."))
                                      for name in FB_SENSE_PINS)}
    drawn = {tuple(point)
             for segment in plan.segments if segment.net == "FB_SENSE"
             for point in (segment.points[0], segment.points[-1])}
    assert drawn == expected, (sorted(drawn), sorted(expected))
