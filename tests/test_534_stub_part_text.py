"""534 r23 — a stub's name row **and** its conductor may not print inside page text.

The defect, measured on the fresh CH343 plan (`.tmp_534/final-plan-current-r1/`): the
`DSR` stub at `H1.6` was the pre-534 `right 10` rung, and the host printed its name
row `[550,435,565.09,445]` through `H1`'s reference row `[553,437.5,568,446.5]`
(interior depth 7.5). Three reasons, all in `drawapply`:

1. `_name_row_clash` (146) *saw* that row — `built.label_owner` is built from
   `layout.texts` — but a clash was only a **demotion**, and when every clear rung
   clashed the caller kept the pre-534 fallback, i.e. put the clashing rung back;
2. the hard list (`label_boxes`, 534 r19) held the layout's *label* boxes only, so
   a part's reference/value row could never refuse a candidate;
3. `_label_stub_blocked` knew bodies, pins and foreign wires — a stub whose
   **conductor** ran through a part's value row was free.

This file pins the three cures: the hard list is the page's whole typography (part
texts + flag name rows), it floors both halves of a candidate (row and conductor),
and a generic **near-length stagger** gives a sealed pin a legal shape without a
net/part/coordinate branch.
"""

from __future__ import annotations

import json
import math
import pathlib
import subprocess
import sys

import pytest

from boardwise.core import textmetrics
from boardwise.core.layoutplan import LayoutPlan
from boardwise.engines import drawapply

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
PY = r"C:\Python314\python.exe"
SITE = r"E:\boardwise\.venv\Lib\site-packages"


class _Built(drawapply._Built):
    """A `_Built` with the two fields the stub chooser reads, nothing else."""


def _ink(layout: LayoutPlan, built=None, profiles=None, subject=None):
    return drawapply._hard_ink_boxes(
        layout, profiles or {}, built or _Built(), subject=subject,
    )


# ------------------------------------------------------- 1. the hard ink list


def test_the_hard_list_is_the_pages_whole_typography():
    """Every `layout.texts` row and every label box, not just the ones we placed."""
    from boardwise.core.layoutplan import LayoutLabel, LayoutText

    layout = LayoutPlan(
        texts=[
            LayoutText(part_id="H1", kind="reference", text="H1",
                       x=560.5, y=442.0, bbox=(553.0, 437.5, 568.0, 446.5)),
            LayoutText(part_id="H1", kind="value", text="2x5P-2.54",
                       x=583.0, y=428.0, bbox=(553.0, 423.5, 613.0, 432.5)),
        ],
        labels=[LayoutLabel(net="DSR", text="DSR", x=545.0, y=435.0,
                            bbox=(613.0, 430.5, 637.0, 439.5), part_id="H1")],
    )
    ink = _ink(layout)
    boxes = [box for _what, box in ink]
    assert (553.0, 437.5, 568.0, 446.5) in boxes, "H1's reference row is not hard ink"
    assert (553.0, 423.5, 613.0, 432.5) in boxes, "H1's value row is not hard ink"
    assert (613.0, 430.5, 637.0, 439.5) in boxes, "the label box left the list"
    assert len(ink) == 3
    subject = layout.labels[0]
    assert len(_ink(layout, subject=subject)) == 2


# --------------------------------------------- 2. the conductor half of the floor


def test_a_conductor_through_text_is_refused_and_a_touch_is_not():
    """Ink over ink is a defect; a shared boundary is two readable statements."""
    ink = [("the value text '2x5P-2.54' of H1", (553.0, 423.5, 613.0, 432.5))]
    through = drawapply._run_through_ink([(560.0, 440.0), (560.0, 415.0)], ink)
    assert through is not None and "runs" in through and "through" in through, through
    touching = drawapply._run_through_ink([(553.0, 432.5), (613.0, 432.5)], ink)
    assert touching is None, "a conductor along the row's boundary is legal"
    clear = drawapply._run_through_ink([(560.0, 435.0), (600.0, 435.0)], ink)
    assert clear is None


def test_the_chord_measures_the_interior_and_never_a_boundary():
    box = (0.0, 0.0, 10.0, 10.0)
    assert drawapply._segment_box_chord((5.0, -5.0), (5.0, 15.0), box) == pytest.approx(10.0)
    assert drawapply._segment_box_chord((0.0, 0.0), (0.0, 10.0), box) == 0.0
    assert drawapply._segment_box_chord((-5.0, 10.0), (15.0, 10.0), box) == 0.0


# ------------------------------------------------- 3. the generic stagger family


def test_the_near_stagger_is_gated_and_offered_last():
    """The family is the page path's last resort: off by default, after everything."""
    from boardwise.core.layoutplan import LayoutLabel

    label = LayoutLabel(net="DSR", text="DSR", x=545.0, y=435.0,
                        bbox=(613.0, 430.5, 637.0, 439.5), part_id="H1")
    plain = drawapply._label_stub_candidates(label)
    assert plain[0].points[-1] == (555.0, 435.0), "the first rung must not move"
    assert not [run for run in plain if run.family.startswith("near stagger")], (
        "the 099d/099f callers (no strict floor) must keep the old ladder verbatim"
    )
    extended = drawapply._label_stub_candidates(label, near_stagger=True)
    assert extended[: len(plain)] == plain, "the old ladder must precede the new family"
    near = [run for run in extended if run.family.startswith("near stagger")]
    assert near, "no near-length stagger in the page path's ladder"
    assert extended[len(plain):] == near, "the new family must be the last thing offered"
    for run in near:
        points = [tuple(p) for p in run.points]
        runs = [math.dist(a, b) for a, b in zip(points, points[1:])]
        assert len(points) == 4 and runs[2] == max(runs), (
            f"the outward run must own the longest segment so the name reads "
            f"horizontally: {run.shape} {runs}"
        )


# ------------------------------------------------------ 4. the page, compiled


@pytest.fixture(scope="module")
def fresh_plan(tmp_path_factory):
    """The shipped board planned by the CLI exactly as a human would run it."""
    out = tmp_path_factory.mktemp("stub534")
    env = {
        **__import__("os").environ,
        "PYTHONUTF8": "1",
        "PYTHONPATH": f"{ROOT / 'src'};{SITE}",
        "BOARDWISE_HOME": str(out),
    }
    proc = subprocess.run(
        [PY, "-m", "boardwise.cli", "draw", "plan",
         "--circuit", str(SPECS / "ch343_uart.circuit.json"),
         "--presentation", str(SPECS / "ch343_uart.presentation.json"),
         "--profiles", str(SPECS / "ch343_uart.library.json"),
         "--page-box", "0,0,1170,825",
         "-o", str(out / "change-plan.json")],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=900,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads((out / "change-plan.json").read_text(encoding="utf-8")), out


def _ink_of(page_plan, book):
    from boardwise.core.symbolprofile import flag_glyph_box

    texts = [(f"text:{t['kind']}:{t['text']}", tuple(t["bbox"]))
             for t in page_plan["texts"]]
    flags = []
    for symbol in page_plan["powerSymbols"]:
        profile = book.get(symbol["symbolRef"])
        if profile is None:
            continue
        glyph = flag_glyph_box(profile, rotation=symbol["rotation"],
                               anchor=(symbol["x"], symbol["y"]))
        if glyph is None:
            continue
        row = textmetrics.flag_name_box(glyph, (symbol["x"], symbol["y"]),
                                        symbol["net"], axis_up=glyph[3] > symbol["y"])
        if row is not None:
            flags.append((f"flag:{symbol['net']}", tuple(row)))
    return texts + flags


def _audit(plan_doc, home):
    """Every `draw_wires` name row / conductor against every part and flag text."""
    book = drawapply.load_library(SPECS / "ch343_uart.library.json")
    page = json.loads((home / "change-plan.page.json").read_text(encoding="utf-8"))
    page_plan = page["plan"]
    ink = _ink_of(page_plan, book)
    label_nets = {item["net"] for item in page_plan["labels"]}

    def interior(a, b):
        dx = min(a[2], b[2]) - max(a[0], b[0])
        dy = min(a[3], b[3]) - max(a[1], b[1])
        return (dx, dy) if dx > 1e-9 and dy > 1e-9 else None

    rows, overlaps = [], []
    for index, wire in enumerate(plan_doc["change"]["wires"]):
        points = [(float(p[0]), float(p[1])) for p in wire["points"]]
        row = textmetrics.wire_name_row([list(p) for p in points], wire["net"])
        if row is None or wire["net"] not in label_nets:
            continue
        rows.append({"wire": index, "net": wire["net"], "points": points,
                     "axis": row.axis, "box": tuple(row.box)})
        for what, box in ink:
            if interior(row.box, box):
                overlaps.append(("row", wire["net"], index, what, row.box, box))
        for head, tail in zip(points, points[1:]):
            for what, box in ink:
                chord = drawapply._segment_box_chord(head, tail, box)
                if chord > 0.0:
                    overlaps.append(("conductor", wire["net"], index, what, head, tail))
    gaps = {}
    for row in rows:
        gaps.setdefault(row["net"], []).append(row["box"])
    worst = {}
    for net, boxes in gaps.items():
        worst[net] = min(
            (math.hypot(max(0.0, b[0] - a[2], a[0] - b[2]),
                        max(0.0, b[1] - a[3], a[1] - b[3]))
             for i, a in enumerate(boxes) for b in boxes[i + 1:]), default=None)
    pairs = []
    for k, a in enumerate(rows):
        for b in rows[k + 1:]:
            dx = min(a["box"][2], b["box"][2]) - max(a["box"][0], b["box"][0])
            dy = min(a["box"][3], b["box"][3]) - max(a["box"][1], b["box"][1])
            pairs.append((a["net"], b["net"], round(dx, 3), round(dy, 3)))
    return rows, overlaps, worst, ink, pairs


def test_no_wire_name_row_or_conductor_prints_inside_page_text(fresh_plan):
    plan_doc, home = fresh_plan
    rows, overlaps, worst, ink, pairs = _audit(plan_doc, home)
    assert ink, "the page must have text rows to check against"
    assert rows, "the page must print named carriers"
    assert overlaps == [], f"{len(overlaps)} interior overlaps: {overlaps[:4]}"
    assert [row for row in rows if row["axis"] != "h"] == [], (
        "every name row must read horizontally"
    )


def test_the_dsr_stub_on_the_header_is_no_longer_the_overlapping_right_ten(fresh_plan):
    """`H1.6`'s carrier is a stagger now, and its row clears H1's reference row."""
    plan_doc, home = fresh_plan
    rows, _overlaps, _worst, _ink, _pairs = _audit(plan_doc, home)
    on_header = [row for row in rows
                 if any(abs(p[0] - 545.0) < 1e-6 and abs(p[1] - 435.0) < 1e-6
                        for p in row["points"])]
    assert len(on_header) == 1, on_header
    carrier = on_header[0]
    assert carrier["net"] == "DSR"
    assert len(carrier["points"]) > 2, (
        "the straight right-10 rung is the defect; the carrier must be a bent shape"
    )
    reference = (553.0, 437.5, 568.0, 446.5)
    dx = min(carrier["box"][2], reference[2]) - max(carrier["box"][0], reference[0])
    dy = min(carrier["box"][3], reference[3]) - max(carrier["box"][1], reference[1])
    assert not (dx > 1e-9 and dy > 1e-9), (
        f"DSR's row {carrier['box']} still overlaps H1's reference {reference}"
    )


def test_the_same_net_carriers_keep_the_twenty_unit_floor(fresh_plan):
    plan_doc, home = fresh_plan
    _rows, _overlaps, worst, _ink, _pairs = _audit(plan_doc, home)
    for net, gap in worst.items():
        assert gap is None or gap >= 20.0, f"{net}'s two rows are {gap:g} apart"


def test_the_own_label_reservation_is_not_ink_but_every_other_box_stays_hard():
    """534 r24: only the *subject's own* planning box leaves the floor, by identity.

    The plan reserves a box where a netlabel would go; this host cannot place one
    (029), which is why the pass is drawing the stub that carries the name. So the
    subject's reservation is not a second printed text. Every other label box, and
    every part row, stays hard — no net is exempted.
    """
    from boardwise.core.layoutplan import LayoutLabel, LayoutText

    subject = LayoutLabel(net="RI", text="RI", x=525.0, y=740.0,
                          bbox=(505.5, 735.5, 517.0, 744.5), part_id="H1")
    other = LayoutLabel(net="RTS", text="RTS", x=525.0, y=710.0,
                        bbox=(493.0, 705.5, 517.0, 714.5), part_id="H1")
    text = LayoutText(part_id="H1", kind="reference", text="H1",
                      x=560.5, y=442.0, bbox=(553.0, 437.5, 568.0, 446.5))
    layout = LayoutPlan(texts=[text], labels=[subject, other])
    with_subject = _ink(layout, subject=subject)
    assert (505.5, 735.5, 517.0, 744.5) not in [box for _w, box in with_subject], (
        "the subject's own reservation must not be a hard box"
    )
    assert (493.0, 705.5, 517.0, 714.5) in [box for _w, box in with_subject], (
        "another net's label box is still ink"
    )
    assert (553.0, 437.5, 568.0, 446.5) in [box for _w, box in with_subject]
    without = _ink(layout)
    assert len(without) == len(with_subject) + 1, "no other box may be dropped"


def test_the_page_delivers_no_pre_534_or_overlap_fallback(fresh_plan):
    """The acceptance the review set: no rung kept as a `pre-534` fallback."""
    plan_doc, _home = fresh_plan
    notes = plan_doc["change"]["notes"]
    kept = [note for note in notes if "pre-534" in note]
    assert kept == [], f"{len(kept)} pre-534 fallback(s) still delivered: {kept[:2]}"
    assert [note for note in notes if "fallback" in note] == []


def test_no_two_wire_name_rows_overlap(fresh_plan):
    """Every pair of printed name rows is two readable statements, not one."""
    plan_doc, home = fresh_plan
    _rows, _overlaps, _worst, _ink, pairs = _audit(plan_doc, home)
    interior = [pair for pair in pairs if pair[2] > 1e-9 and pair[3] > 1e-9]
    assert interior == [], f"{len(interior)} overlapping name-row pair(s): {interior}"


def test_a_pin_with_no_legal_seat_is_refused_and_not_fallen_back():
    """The strict path answers `None` + reasons instead of keeping a clashing rung."""
    from boardwise.core.layoutplan import LayoutLabel

    label = LayoutLabel(net="RI", text="RI", x=525.0, y=740.0,
                        bbox=(505.5, 735.5, 517.0, 744.5), part_id="H1")
    stub, blockers = drawapply._place_label_stub(
        label, _Built(), {}, [], [("a wall of ink", (0.0, 0.0, 2000.0, 2000.0))],
    )
    assert stub is None, "a pin with no legal seat must not get a stub"
    assert blockers, "the refusal must name why every rung failed"
