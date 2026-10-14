"""bug98-B: a board frame drawn as a **line** — 16 closed stroked pieces.

The field report behind this fix (岳's 复测 of bug98-A, 2026-10-14): a 98-part
board still reported all 98 parts as 「器件出板框」 after bug98-A landed. The
frame is not 16 polylines there — it is a **drawn line**, and the editor stores
each *piece* of that line as the closed outline of the piece (two offset walls
plus two round end caps). Every one of the 16 rings is closed, so bug98-A's
split put all sixteen in ``closed_rings``, nothing was stitched, and
``max(perimeter)`` handed one piece to the off-board rule as the board.

What this file pins, all through the ``parse_epru_text`` text route on a
**synthetic** board (no real board container is committed — R4, and the field
archive is 岳's product board and stays read-only):

* the pieces' **centre lines** are read and joined into the designed frame,
  which keeps the board's **curvature**: the corner arcs stay arcs, not their
  chords (a chord across a 150-mil corner cuts 44 mil off the board — measured
  below, and the flat reader ``_path_points`` really does produce those chords);
* every piece reads on its own, with its endpoints landing on the designed
  joins to within a tenth of a mil;
* the rule reports **nothing** for the parts inside that frame, and exactly one
  ERROR for a part that really is past it (the reading is not a mute);
* a piece that is **not** a stroke (a three-ended malformed one) makes the whole
  capsule reading abstain, and then bug98-B's guardrail fires: the frame falls
  back to one piece, ``pcb-component-off-board`` files **one WARN** naming the
  counts, and no per-part ERROR is filed against that fragment;
* the shapes that are not strokes at all — a closed rectangle, a many-sided
  circle — are refused rather than read as capsules.

The board is 2000 x 1200 mil with 150-mil rounded corners (the same design
``test_bug98a_outline_stitch`` uses, now stored the way the field board stores
it: **stroked** pieces, every vertex written through ``ARC`` commands).
"""

from __future__ import annotations

import json
import math

import pytest

from boardwise.core.geometry import BoardGeometry, Point
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, _board_entry
from boardwise.parsers.epru import (
    OUTLINE_CAPSULE_MIN_STEP_MIL,
    OUTLINE_CAPSULE_MIN_STEP_RATIO,
    OUTLINE_STITCH_TOLERANCE_MIL,
    _capsule_centerline,
    _path_points,
    _ring_points,
    _stitch_outline,
    parse_epru_text,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.distance import BoardOffEdge

OFF_BOARD_RULE_ID = "pcb-component-off-board"

# ---------------------------------------------------------------------------
# the synthetic board: a rounded rectangle stored as stroked pieces
# ---------------------------------------------------------------------------

_W, _H, _R = 2000.0, 1200.0, 150.0
#: The record's own ``width`` field. The editor offsets a stroke's walls by a
#: quarter of it (measured on the field board: ``width`` 10, walls at +-2.5),
#: which is all this fixture needs to know about the semantics.
_WIDTH = 10.0
_HALF = _WIDTH / 4.0


def _u(deg: float) -> tuple[float, float]:
    """The unit vector at ``deg``, in the board's -y frame."""
    angle = math.radians(deg)
    return (math.cos(angle), math.sin(angle))


def _add(center, vec, scale: float = 1.0):
    return (center[0] + vec[0] * scale, center[1] + vec[1] * scale)


def _sweep(center, start, end) -> float:
    """The signed sweep of the arc about ``center`` that runs start -> end."""
    first = (start[0] - center[0], start[1] - center[1])
    second = (end[0] - center[0], end[1] - center[1])
    return math.degrees(
        math.atan2(
            first[0] * second[1] - first[1] * second[0],
            first[0] * second[0] + first[1] * second[1],
        )
    )


def _cap_sweep(start, tip, center) -> float:
    """The 180-degree sweep whose arc runs from ``start`` around through ``tip``.

    A semicircle through two antipodal points has one centre whichever way it is
    drawn, so the *sign* is the whole question: one route wraps around the tip
    (the cap the editor draws) and the mirrored one crosses the piece.
    """
    entry = (start[0] - center[0], start[1] - center[1])
    to_tip = (tip[0] - center[0], tip[1] - center[1])
    return 180.0 if entry[0] * to_tip[1] - entry[1] * to_tip[0] > 0 else -180.0


def _arc_piece_path(center, radius, deg0, deg1, half=_HALF):
    """One **arc** piece of the frame, as the editor writes a stroked arc.

    Outer wall (radius + half), the cap at the far end, the inner wall back, the
    cap at the near end, closing on the first point. Both walls and both caps
    are ``ARC`` commands — the field board's own storage — so this fixture also
    pins that the parser expands arcs rather than reading their end points.
    """
    outer0 = _add(center, _u(deg0), radius + half)
    outer1 = _add(center, _u(deg1), radius + half)
    inner1 = _add(center, _u(deg1), radius - half)
    inner0 = _add(center, _u(deg0), radius - half)
    end1 = _add(center, _u(deg1), radius)
    end0 = _add(center, _u(deg0), radius)
    tip1 = _add(end1, _u(deg1), half)
    tip0 = _add(end0, _u(deg0), -half)
    return [
        outer0[0], outer0[1],
        "ARC", _sweep(center, outer0, outer1), outer1[0], outer1[1],
        "ARC", _cap_sweep(outer1, tip1, end1), inner1[0], inner1[1],
        "ARC", _sweep(center, inner1, inner0), inner0[0], inner0[1],
        "ARC", _cap_sweep(inner0, tip0, end0), outer0[0], outer0[1],
    ]


def _line_piece_path(a, b, half=_HALF):
    """One straight piece of the frame, as the editor writes a stroked line."""
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    left = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
    outer_a = _add(a, left, half)
    outer_b = _add(b, left, half)
    inner_b = _add(b, left, -half)
    inner_a = _add(a, left, -half)
    tip_b = _add(b, ((b[0] - a[0]) / length, (b[1] - a[1]) / length), half)
    tip_a = _add(a, (-(b[0] - a[0]) / length, -(b[1] - a[1]) / length), half)
    return [
        outer_a[0], outer_a[1], "L", outer_b[0], outer_b[1],
        "ARC", _cap_sweep(outer_b, tip_b, b), inner_b[0], inner_b[1],
        "L", inner_a[0], inner_a[1],
        "ARC", _cap_sweep(inner_a, tip_a, a), outer_a[0], outer_a[1],
    ]


#: The 16 pieces, in file order: four corner arcs then the sides, each side in
#: three pieces. ``(kind, ...)`` is the *design* — the same rounded rectangle
#: ``rounded_rect_segments`` draws in test_bug98a — and the tests below compare
#: the parser's answer back against it.
_PIECES: list[tuple] = [
    ("arc", (1850.0, -150.0), _R, 90.0, 0.0),
    ("line", (2000.0, -150.0), (2000.0, -450.0)),
    ("line", (2000.0, -450.0), (2000.0, -750.0)),
    ("line", (2000.0, -750.0), (2000.0, -1050.0)),
    ("arc", (1850.0, -1050.0), _R, 0.0, -90.0),
    ("line", (1850.0, -1200.0), (1283.333333333, -1200.0)),
    ("line", (1283.333333333, -1200.0), (716.666666667, -1200.0)),
    ("line", (716.666666667, -1200.0), (150.0, -1200.0)),
    ("arc", (150.0, -1050.0), _R, -90.0, -180.0),
    ("line", (0.0, -1050.0), (0.0, -750.0)),
    ("line", (0.0, -750.0), (0.0, -450.0)),
    ("line", (0.0, -450.0), (0.0, -150.0)),
    ("arc", (150.0, -150.0), _R, 180.0, 90.0),
    ("line", (150.0, 0.0), (716.666666667, 0.0)),
    ("line", (716.666666667, 0.0), (1283.333333333, 0.0)),
    ("line", (1283.333333333, 0.0), (1850.0, 0.0)),
]


def piece_path(piece) -> list:
    """The outline path the editor stores for one designed piece.

    A ``("path", <raw path>)`` entry passes its path straight through — that is
    how the malformed piece below replaces one designed record.
    """
    if piece[0] == "path":
        return piece[1]
    if piece[0] == "arc":
        return _arc_piece_path(piece[1], piece[2], piece[3], piece[4])
    return _line_piece_path(piece[1], piece[2])


def piece_ends(piece) -> tuple[tuple[float, float], tuple[float, float]]:
    """The designed centre line's two ends, in mils."""
    if piece[0] == "arc":
        _kind, center, radius, deg0, deg1 = piece
        return (_add(center, _u(deg0), radius), _add(center, _u(deg1), radius))
    return (piece[1], piece[2])


def piece_middle(piece) -> tuple[float, float]:
    """A point strictly **inside** the piece's centre line, away from its ends."""
    if piece[0] == "arc":
        _kind, center, radius, deg0, deg1 = piece
        return _add(center, _u((deg0 + deg1) / 2.0), radius)
    _kind, start, end = piece
    return ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)


def y_stroke_path(center, radius, width=_WIDTH):
    """A **three-ended** malformed piece: a stroked Y.

    The shape a wrong reading has to refuse: its stroke has three caps, so it
    cannot be a segment of one frame (and ``max(perimeter)`` would happily make
    it the board). Walls are straight, caps are round — the editor's own mix.
    """
    half = width / 4.0
    ring: list[float] = []
    tips: list[tuple[float, float]] = []
    corners: list[tuple[float, float]] = []
    for arm in range(3):
        deg = 90.0 + 120.0 * arm
        tip = _add(center, _u(deg), radius)
        left = (-_u(deg)[1], _u(deg)[0])
        tips.append(tip)
        corners.append((_add(tip, left, half), _add(tip, left, -half)))
    for arm in range(3):
        here = corners[arm]
        following = corners[(arm + 1) % 3]
        notch_deg = 90.0 + 120.0 * arm + 60.0
        notch = _add(center, _u(notch_deg), half / math.sin(math.radians(60.0)))
        if arm == 0:
            ring += [here[0][0], here[0][1]]
        ring += [
            "ARC", _cap_sweep(here[0], _add(tips[arm], _u(90.0 + 120.0 * arm), half), tips[arm]),
            here[1][0], here[1][1],
            "L", notch[0], notch[1],
            "L", following[0][0], following[0][1],
        ]
    ring += [corners[0][0][0], corners[0][0][1]]
    return ring


def closed_ring_path(points: list[tuple[float, float]]) -> list:
    """A plain closed polyline path (no arcs) through ``points``."""
    flat: list[object] = []
    for index, point in enumerate(points):
        if index:
            flat.append("L")
        flat += [point[0], point[1]]
    return flat


def _line(type_: str, id_: str, body: dict) -> str:
    envelope = json.dumps({"type": type_, "ticket": 1, "id": id_}, separators=(",", ":"))
    return envelope + "||" + json.dumps(body, separators=(",", ":")) + "|"


def _component(prefix: str, x: float, y: float, designator: str) -> list[str]:
    return [
        _line("COMPONENT", prefix, {"x": x, "y": y, "angle": 0, "layerId": 1}),
        _line("ATTR", prefix + "d", {"parentId": prefix, "key": "Designator", "value": designator}),
        _line("ATTR", prefix + "f", {"parentId": prefix, "key": "Footprint", "value": "fp1"}),
    ]


#: Five parts inside the frame, plus the one the ``off_board`` switch adds past
#: the right edge at x = 2200 (its 40-mil pad reaches 2220, i.e. 220 mil past the
#: frame — the same anchor test_bug98a uses).
_INSIDE = [(400.0, -300.0), (1000.0, -300.0), (1600.0, -300.0), (700.0, -900.0), (1400.0, -900.0)]


def board_text(*, pieces: list | None = None, inside: int = 5, off_board: bool = False) -> str:
    """The synthetic **stroked** frame as ``.epru`` text."""
    paths = [piece_path(piece) for piece in (_PIECES if pieces is None else pieces)]
    lines = [
        _line("DOCHEAD", "h_fp", {"docType": "FOOTPRINT", "uuid": "fp1", "editVersion": "3.2.186"}),
        _line("PAD", "pad1", {
            "num": "1", "layerId": 1, "centerX": 0, "centerY": 0, "padAngle": 0,
            "defaultPad": {"padType": "RECT", "width": 40, "height": 40},
            "hole": None, "plated": True,
        }),
        _line("DOCHEAD", "h_pcb", {"docType": "PCB", "uuid": "pcb1", "editVersion": "3.2.186"}),
        _line("LAYER", '["LAYER",1]', {"layerName": "Top Layer", "layerType": "TOP"}),
        _line("LAYER", '["LAYER",2]', {"layerName": "Bottom Layer", "layerType": "BOTTOM"}),
    ]
    for index, path in enumerate(paths):
        lines.append(_line("POLY", f"outline{index}", {
            "polyType": "BOARD_OUTLINE", "layerId": 11, "netName": "",
            "width": _WIDTH, "path": path,
        }))
    for index, (x, y) in enumerate(_INSIDE[:inside]):
        lines += _component("c", x, y, f"R{index}")
    if off_board:
        lines += _component("cz", 2200.0, -600.0, "RZ")
    return "\n".join(lines)


def _parse(**kwargs) -> BoardGeometry:
    return parse_epru_text(board_text(**kwargs))


def _off_board(board: BoardGeometry):
    return BoardOffEdge().check(PcbReviewContext(board=board))


def _inside(point: Point, polygon) -> bool:
    from boardwise.core.measure import point_in_polygon

    return point_in_polygon(point, list(polygon))


# ---------------------------------------------------------------------------
# 1. the parser: sixteen stroked pieces become the designed frame
# ---------------------------------------------------------------------------


def test_the_sixteen_stroked_pieces_stitch_into_the_designed_frame():
    """The frame the drawn line traces, with every record consumed.

    ``segments`` counts all sixteen, ``stitched`` says the ring was assembled by
    welding the pieces' centre lines, nothing was left out, and the bbox is the
    designed board — the fitted arcs of the corners included, which is why it is
    the *frame* and not one piece of it.
    """
    board = _parse()
    outline = board.outline
    assert outline is not None
    assert outline.segments == 16
    assert outline.closed is True
    assert outline.stitched is True
    assert board.outline_fragments == 0
    box = outline.bbox
    assert box is not None
    assert abs(box.min_x - 0.0) <= _HALF
    assert abs(box.max_x - _W) <= _HALF
    assert abs(box.min_y - (-_H)) <= _HALF
    assert abs(box.max_y - 0.0) <= _HALF
    # The parser says how it read it, and the report prints that verbatim.
    assert "中心线" in outline.note and "16" in outline.note


def test_the_frame_keeps_the_corner_arcs_and_not_their_chords():
    """The mechanism: an ``ARC``'s sweep has to be read, not just its end point.

    ``_path_points`` keeps an arc's end point and drops the sweep, so the flat
    reader of one corner piece carries **five** points where an arc-aware reader
    carries the whole fitted arc. Reading the centre line off the flattened ring
    would put the frame on the *chord* across each corner — 44 mil inside the
    board at the middle of a 150-mil corner:

    * the arc's own midpoint has to be **inside** the frame (it is outside a
      chord frame — outside the board, which is the field report's ERROR);
    * and the frame has to pass within half a mil of it, i.e. the frame really
      is the arc there and not a polygon that happens to contain it.
    """
    corner = _PIECES[0]
    path = piece_path(corner)
    flat = _path_points(path)
    drawn = _ring_points(path)
    assert len(flat) == 5, "the flat reader keeps the arc's end points only"
    assert len(drawn) > 100, "the arc-aware reader keeps the fitted arc"

    middle = piece_middle(corner)
    chord_middle = (
        (piece_ends(corner)[0][0] + piece_ends(corner)[1][0]) / 2.0,
        (piece_ends(corner)[0][1] + piece_ends(corner)[1][1]) / 2.0,
    )
    sagitta = math.hypot(middle[0] - chord_middle[0], middle[1] - chord_middle[1])
    assert sagitta > 40.0, "a 90-degree corner of radius 150 has a real sagitta"

    frame = _parse().outline
    assert frame is not None
    assert _inside(Point(*middle), frame.points)
    nearest = min(
        math.hypot(middle[0] - point.x, middle[1] - point.y) for point in frame.points
    )
    assert nearest <= 0.5, "the frame passes through the arc's midpoint, not its chord"


def test_every_piece_reads_as_its_own_centre_line():
    """One piece at a time: the endpoints are the joins, the middle is the arc.

    ``_capsule_centerline`` on each of the sixteen **closed stroked rings**: a
    straight piece answers with its two ends, an arc piece with the arc's own
    points (so its middle vertex sits on the designed radius). The endpoints land
    on the designed joins — measured, within a tenth of a mil — which is why the
    frame can be welded with the house 1-mil vertex tolerance.
    """
    for piece in _PIECES:
        ring = _ring_points(piece_path(piece))
        line = _capsule_centerline(ring)
        assert line is not None, piece
        start, end = piece_ends(piece)
        # The ring's own order decides which end the centre line starts at, so
        # the two ends are compared as a pair.
        assert min(
            math.hypot(line[0].x - start[0], line[0].y - start[1]),
            math.hypot(line[0].x - end[0], line[0].y - end[1]),
        ) <= 0.1, piece
        assert min(
            math.hypot(line[-1].x - start[0], line[-1].y - start[1]),
            math.hypot(line[-1].x - end[0], line[-1].y - end[1]),
        ) <= 0.1, piece
        if piece[0] == "arc":
            _kind, center, radius, _deg0, _deg1 = piece
            assert len(line) >= 20, "an arc wall keeps its fitted points"
            for point in line:
                reach = math.hypot(point.x - center[0], point.y - center[1])
                assert abs(reach - radius) <= 0.2, (piece, reach)


def test_a_fragment_out_of_a_stroke_frame_is_not_the_frame():
    """One piece on its own is a piece, and the parser says so (the bug's shape).

    Feeding the sixteen pieces one at a time to ``_stitch_outline`` — the shape
    that has to fail — leaves each ring its own reading: a single closed ring,
    ``stitched`` unset, and a bbox that is a sliver of the board rather than the
    board. That is what ``max(perimeter)`` used to hand the off-board rule.
    """
    piece = _PIECES[5]
    outline, fragments = _stitch_outline([("only", _ring_points(piece_path(piece)), False)])
    assert outline is not None and fragments == 0
    assert outline.segments == 1
    box = outline.bbox
    assert box is not None
    assert box.max_x - box.min_x < 600.0, "one 366-mil piece is not a 2000-mil board"


# ---------------------------------------------------------------------------
# 2. the rule: nothing for the parts inside, one ERROR for the part outside
# ---------------------------------------------------------------------------


def test_the_rule_files_nothing_for_the_parts_inside_the_frame():
    """The regression this batch exists for: no part hangs off a stroked frame."""
    board = _parse(off_board=False)
    assert len(board.components) == 5
    assert board.outline is not None and board.outline.stitched is True
    assert _off_board(board) == []


def test_a_part_really_off_the_board_is_exactly_one_error():
    """And the reading is not a mute: the part at x = 2200 makes one row.

    40-mil pad, frame edge at 2000 — 220 mil past it, in the same units the
    reading has always reported, under the same rule id.
    """
    board = _parse(off_board=True)
    findings = _off_board(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == OFF_BOARD_RULE_ID
    assert finding.severity == "ERROR"
    assert finding.target is not None
    assert finding.target.component_ref == "RZ"
    assert finding.target.measurement == {"kind": "distance", "value": 220.0, "unit": "mil"}


# ---------------------------------------------------------------------------
# 3. the guardrail: a frame that is a piece of one is loud, not silent
# ---------------------------------------------------------------------------


def test_a_three_ended_piece_makes_the_reading_abstain():
    """A malformed piece is refused on its own, not averaged into a frame."""
    ring = _ring_points(y_stroke_path((1000.0, -600.0), 100.0))
    assert len(ring) > 100
    assert _capsule_centerline(ring) is None


def test_a_frame_that_cannot_be_stitched_files_one_warn_and_no_error():
    """bug98-B's guardrail, end to end on the malformed-piece board.

    One of the sixteen records is a **three-ended** stroked Y: the capsule
    reading refuses it, every piece falls back to bug98-A's reading, and
    ``max(perimeter)`` hands one *piece* to the off-board rule. That piece is not
    the board — the assertion below checks that the frame's own centre is outside
    it, i.e. every part on the board would have been reported off it — so the
    rule must file **one WARN naming the counts** and no per-part ERROR at all.
    """
    poison = _PIECES[:]
    poison[9] = ("path", y_stroke_path((1000.0, -600.0), 100.0))
    board = _parse(pieces=poison)
    outline = board.outline
    assert outline is not None
    assert outline.stitched is False, "the fallback hands a piece of the frame over"
    assert outline.segments == 16
    assert board.outline_fragments == 15
    assert not _inside(Point(1000.0, -300.0), outline.points), (
        "the fallback frame does not contain the board — that is the 98-row storm"
    )

    findings = _off_board(board)
    assert len(findings) == 1
    warning = findings[0]
    assert warning.rule_id == OFF_BOARD_RULE_ID
    assert warning.severity == "WARN"
    assert warning.target is None
    assert "16" in warning.message and "15" in warning.message
    assert "抑制" in warning.message


def test_a_piece_of_a_frame_is_disclosed_as_suppressed_on_the_board_entry():
    """The report says 「suppressed」, and never the old 「照跑」 for that shape."""
    poison = _PIECES[:]
    poison[9] = ("path", y_stroke_path((1000.0, -600.0), 100.0))
    board = _parse(pieces=poison)
    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "抑制" in note and "没跑" in note, note
    assert "照跑" not in note, note


def test_a_stroke_stitched_frame_is_disclosed_on_the_board_entry():
    """A frame that read says so on the report, and carries no weld alarm.

    The joins of a stroked frame are the drawn vertices themselves (0.011 mil
    apart on the field board), so the records' own sentence replaces the
    ``tolerance_welds`` warning a welded ring would carry — 16 inexact-by-design
    joins are not 16 welding hazards. A board with a good frame of the ordinary
    single-record kind still carries no ``outlineNote`` at all.
    """
    board = _parse()
    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "中心线" in note and "16 段全部入环" in note, note
    assert board.outline is not None and board.outline.tolerance_welds == 0


# ---------------------------------------------------------------------------
# 4. shapes that are not strokes are refused, not read as capsules
# ---------------------------------------------------------------------------


def test_a_closed_rectangle_ring_is_not_a_stroke():
    """Four sides of similar length have no cap population to split at."""
    rectangle = [(0.0, 0.0), (600.0, 0.0), (600.0, -10.0), (0.0, -10.0)]
    assert _capsule_centerline(_ring_points(closed_ring_path(rectangle))) is None


def test_a_many_sided_circle_is_not_a_stroke():
    """A circle's steps are all one population: no pair clears the ratio."""
    steps = 36
    circle = [
        (300.0 * math.cos(2 * math.pi * k / steps), -600.0 + 300.0 * math.sin(2 * math.pi * k / steps))
        for k in range(steps)
    ]
    assert _capsule_centerline(_ring_points(closed_ring_path(circle))) is None


def test_a_degenerate_ring_is_not_a_stroke():
    """Fewer than four vertices, or a ring with one wall population, answer None."""
    assert _capsule_centerline([Point(0.0, 0.0), Point(1.0, 0.0)]) is None
    assert _capsule_centerline([]) is None


def test_the_step_ratio_and_the_step_floor_are_stated_numbers():
    """The two constants the split is made of, pinned as measured values.

    ``OUTLINE_CAPSULE_MIN_STEP_RATIO`` = 5: the measured gaps are 229x (the
    field board: 0.118..0.262 cap steps against 60.08..67.5 wall steps) and 59x
    (this file's rounded rectangle: 0.131 against 7.72..7.98) — a rectangle's
    sides sit under 2.
    ``OUTLINE_CAPSULE_MIN_STEP_MIL`` = 0.001: two orders below the four decimals
    this format writes a mil with, so it can only catch a repeated vertex.
    """
    assert OUTLINE_CAPSULE_MIN_STEP_RATIO == 5.0
    assert OUTLINE_CAPSULE_MIN_STEP_MIL == 0.001


def test_the_stitch_tolerance_is_the_house_vertex_tolerance():
    """A centre-line end is the join itself, so the 1-mil tolerance welds it."""
    assert OUTLINE_STITCH_TOLERANCE_MIL == 1.0
    board = _parse()
    assert board.outline is not None and board.outline.tolerance_welds == 0


def test_the_new_rule_is_still_registered_after_the_spacing_rule():
    """bug98-B does not move the rule list (126a's structural gate)."""
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert ids.index(OFF_BOARD_RULE_ID) == ids.index("pcb-component-spacing") + 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
