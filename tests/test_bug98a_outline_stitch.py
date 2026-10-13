"""bug98-A: a board frame that arrives as **many** ``BOARD_OUTLINE`` records.

The field report behind this fix: a 98-part board whose outline is a
rounded rectangle the editor stored as **16 independent** ``BOARD_OUTLINE``
polylines (four corner arcs plus twelve edge pieces). The parser kept only the
**first** record — a single arc on the left edge, 11 points — and the board-frame
half of ``pcb-component-spacing`` measured every part against that fragment, so
98 「part hangs off the board」 ERRORs buried the report's real findings. The
frame was never read as a frame.

What this file pins, all through the ``parse_epru_text`` text route (no real
board container is committed — R4):

* **all** ``BOARD_OUTLINE`` records are collected (none falls through as an
  ordinary non-copper ``POLY``), stitched end to end and read as one ring;
* the stitched frame makes the field shape report **nothing** about parts
  hanging off the board, and the demo part that really is off the board is
  exactly **one** ERROR — under the rule id that now names the question,
  ``pcb-component-off-board``;
* the first-segment-only reading (the pre-fix answer) still reproduces the
  field report's ERROR storm — the mechanism of the bug, pinned so the fix
  cannot silently regress into it;
* records that do **not** close a ring are disclosed (``outline_fragments``) and
  produce no finding at all, rather than a fragment being passed off as the
  frame;
* a single-record outline is byte-for-byte what it always was.

The synthetic board is text, and the rule is run directly on the parsed
``BoardGeometry`` — no editor, no daemon, no fixture file.
"""

from __future__ import annotations

import json
import math

import pytest

from boardwise.core.geometry import BoardGeometry, Point
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES
from boardwise.parsers.epru import (
    OUTLINE_STITCH_TOLERANCE_MIL,
    _stitch_outline,
    parse_epru_text,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.distance import BoardOffEdge, ComponentSpacing

OFF_BOARD_RULE_ID = "pcb-component-off-board"

# ---------------------------------------------------------------------------
# the synthetic board, as .epru text
# ---------------------------------------------------------------------------


def _line(type_: str, id_: str, body: dict) -> str:
    envelope = json.dumps({"type": type_, "ticket": 1, "id": id_}, separators=(",", ":"))
    return envelope + "||" + json.dumps(body, separators=(",", ":")) + "|"


def _arc_path(cx: float, cy: float, r: float, deg0: float, deg1: float, steps: int = 10):
    """One corner arc as a **flattened** polyline of ``steps + 1`` points.

    Flattened because that is how the editor writes these on the field board —
    the parser's ``_path_points`` reads the record's own vertices (it does not
    subdivide ``ARC`` commands), and the report's first segment carried 11
    points, i.e. a discretised arc. 10 sub-arcs => 11 points, the same shape.
    """
    values: list[float] = []
    for k in range(steps + 1):
        angle = math.radians(deg0 + (deg1 - deg0) * k / steps)
        values += [round(cx + r * math.cos(angle), 6), round(cy + r * math.sin(angle), 6)]
    flat: list[object] = []
    for index in range(len(values) // 2):
        flat += [values[2 * index], values[2 * index + 1], "L"]
    return flat[:-1]  # drop the trailing "L"


def _edge(x0: float, y0: float, x1: float, y1: float):
    return [x0, y0, "L", x1, y1]


#: The board: 2000 x 1200 mil, corner radius 150.
_W, _H, _R = 2000.0, 1200.0, 150.0


def rounded_rect_segments() -> list[list[object]]:
    """The field shape: a rounded rectangle split into **16** polylines.

    Four corner arcs (:func:`_arc_path`, 11 points each) plus twelve straight
    edges (four pieces per long side, two per short side). Every join is an
    exact shared vertex — the editor's own storage — so the ring is closed by
    endpoint identity, not by tolerance.
    """
    right = _W - _R          # 1850
    bottom = -_H + _R        # -1050
    return [
        # TR corner, then down the right edge, BR corner...
        _arc_path(right, -_R, _R, 90, 0),
        _edge(_W, -_R, _W, -_H / 2),                    # (2000,-150) -> (2000,-600)
        _edge(_W, -_H / 2, _W, bottom),                 # (2000,-600) -> (2000,-1050)
        _arc_path(right, bottom, _R, 0, -90),
        # bottom edge, right to left, in four pieces
        _edge(right, -_H, 1425.0, -_H),
        _edge(1425.0, -_H, 1000.0, -_H),
        _edge(1000.0, -_H, 575.0, -_H),
        _edge(575.0, -_H, _R, -_H),
        _arc_path(_R, bottom, _R, -90, -180),
        _edge(0.0, bottom, 0.0, -_H / 2),               # (0,-1050) -> (0,-600)
        _edge(0.0, -_H / 2, 0.0, -_R),                  # (0,-600) -> (0,-150)
        _arc_path(_R, -_R, _R, 180, 90),
        # top edge, left to right, in four pieces
        _edge(_R, 0.0, 575.0, 0.0),
        _edge(575.0, 0.0, 1000.0, 0.0),
        _edge(1000.0, 0.0, 1425.0, 0.0),
        _edge(1425.0, 0.0, right, 0.0),
    ]


def _distinct_vertices(segments) -> set[tuple[float, float]]:
    return {
        (round(float(path[index]), 6), round(float(path[index + 1]), 6))
        for path in segments
        for index in range(0, len(path) - 1, 3)
    }


def board_text(*, drawn_segments=None, parts: int = 98, off_board: bool = False) -> str:
    """The synthetic board as ``.epru`` text.

    ``drawn_segments`` overrides the outline records (used for the fragment and
    single-record shapes); ``parts`` is the 98-pad grid; ``off_board`` adds one
    part that really is past the frame.
    """
    segments = rounded_rect_segments() if drawn_segments is None else drawn_segments
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
    for index, path in enumerate(segments):
        lines.append(_line("POLY", f"outline{index}", {
            "polyType": "BOARD_OUTLINE", "layerId": 11, "netName": "", "path": path,
        }))
    columns, rows, pitch = 14, 7, 100.0
    placed = 0
    for column in range(columns):
        for row in range(rows):
            if placed >= parts:
                break
            x = 200.0 + pitch * column
            y = -200.0 - pitch * row
            placed += 1
            lines += _component("c", x, y, f"R{placed - 1}")
    if off_board:
        lines += _component("cz", 2200.0, -600.0, "RZ")
    return "\n".join(lines)


def _component(prefix: str, x: float, y: float, designator: str) -> list[str]:
    return [
        _line("COMPONENT", prefix, {"x": x, "y": y, "angle": 0, "layerId": 1}),
        _line("ATTR", prefix + "d", {"parentId": prefix, "key": "Designator", "value": designator}),
        _line("ATTR", prefix + "f", {"parentId": prefix, "key": "Footprint", "value": "fp1"}),
    ]


def _parse(**kwargs) -> BoardGeometry:
    return parse_epru_text(board_text(**kwargs))


def _off_board(board: BoardGeometry):
    return BoardOffEdge().check(PcbReviewContext(board=board))


def _spacing(board: BoardGeometry):
    return ComponentSpacing().check(PcbReviewContext(board=board))


# ---------------------------------------------------------------------------
# 1. the parser: every record is collected, and they stitch into one ring
# ---------------------------------------------------------------------------


def test_every_board_outline_record_is_kept_and_none_falls_through_as_a_poly():
    """The second-and-later outline records used to land in ``non_copper_shapes``.

    Before bug98-A only the first ``BOARD_OUTLINE`` record was consumed (and
    ``continue``d past the shape construction); the rest fell through and were
    filed as ordinary non-copper ``POLY`` shapes. All sixteen are outline
    records, so all sixteen are consumed and none is a shape.
    """
    board = _parse()
    # 审计 325-e：只断言 non_copper_shapes 是恒真的——合成文档没定义 layer 11，
    # _carries_copper 对未知层答 True，落空会进 pours。两壶都要断言才算数。
    assert board.non_copper_shapes == []
    assert board.pours == []


def test_the_sixteen_segments_stitch_into_one_closed_ring():
    """The frame is the **whole** ring: every drawn vertex, one segment count.

    The ring carries exactly the distinct vertices of the sixteen polylines
    (adjacent joins share a point, which the stitcher drops once), and the
    disclosure says how it was built: 16 records, closed.
    """
    segments = rounded_rect_segments()
    assert len(segments) == 16
    board = _parse()
    outline = board.outline
    assert outline is not None
    assert outline.segments == 16
    assert outline.closed is True
    assert board.outline_fragments == 0
    assert len(outline.points) == len(_distinct_vertices(segments))
    ring = {(round(p.x, 6), round(p.y, 6)) for p in outline.points}
    assert ring == _distinct_vertices(segments)
    # It really is the board's frame, not a fragment: the bbox is the full board.
    box = outline.bbox
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == (0.0, -_H, _W, 0.0)


def test_a_single_record_outline_is_byte_for_byte_unchanged():
    """One ``BOARD_OUTLINE`` record keeps its own points — the old behaviour.

    The ``["R", x, y, w, h, rot, radius]`` rectangle is the shape every existing
    fixture uses, and bug98-A must not reshape it: four corners, in order, and
    ``segments == 1``. It is closed by construction (the editor stores a
    rectangle as four corners and no closing vertex), so ``closed`` is True even
    though its first and last points differ.
    """
    rectangle = ["R", 0, 0, 1000, 500, 0, 0]
    board = _parse(drawn_segments=[rectangle], parts=2)
    outline = board.outline
    assert outline is not None
    assert [(p.x, p.y) for p in outline.points] == [
        (0.0, 0.0), (1000.0, 0.0), (1000.0, -500.0), (0.0, -500.0),
    ]
    assert outline.segments == 1
    assert outline.closed is True
    assert board.outline_fragments == 0


def test_a_degenerate_one_point_outline_keeps_its_single_segment_reading():
    """毕设FOC PCB2's one-vertex outline is still read as a (degenerate) record.

    Single-record behaviour is preserved byte for byte: the point is the
    outline's own, ``segments == 1`` and ``closed`` is False because a point is
    not a ring. Whether it is a *usable* frame is ``MIN_OUTLINE_CORNERS``'s
    question, and the board-frame rule stays silent — see the test below.
    """
    board = _parse(drawn_segments=[[17.4999, 27.5]], parts=2)
    outline = board.outline
    assert outline is not None
    assert [(p.x, p.y) for p in outline.points] == [(17.4999, 27.5)]
    assert outline.segments == 1
    assert outline.closed is False
    assert _off_board(board) == []


# ---------------------------------------------------------------------------
# 2. the field shape: no part is off the board any more
# ---------------------------------------------------------------------------


def test_the_field_shape_reports_no_part_off_the_board():
    """The regression this whole batch exists for.

    Before the fix, the parser kept the first outline record — an arc on the
    left edge — and the board-frame half measured all 98 parts against it. After
    the fix the stitched frame reports nothing about parts off the board, and
    nothing about spacing either (the grid of 40-mil pads sits 60 mil apart).
    """
    board = _parse()
    assert len(board.pads) == 98
    assert _off_board(board) == []
    assert _spacing(board) == []


def test_the_first_segment_alone_reproduces_the_reading_then_the_guard_refuses():
    """The bug's mechanism, pinned: one open arc used to storm; the guard now reads ``closed``.

    ``_stitch_outline`` on a single open record returns that record's own points
    (the pre-fix reading, byte for byte) — with ``closed=False``, which the old
    guard never looked at. The rule's silence condition now consumes exactly
    that flag: an open arc is not a frame, and the 98-row flood cannot be
    produced by this shape anymore. (The storm half of the pair is history —
    commit message; the live assertion is the refusal.)
    """
    segments = rounded_rect_segments()
    # `segments[0]` is the top-right arc; `segments[9]` is the bottom-left one.
    single_arc = [("arc-only", _as_points(segments[0]), False)]
    outline, fragments = _stitch_outline(single_arc)
    assert outline is not None and fragments == 0
    assert len(outline.points) == 11
    assert outline.closed is False, "一段弧不闭环——这正是旧护栏漏看的信号"

    board = _parse(parts=98)
    board.outline = outline
    assert _off_board(board) == [], "开放弧不许再制造 98 条误报"


def test_a_part_really_off_the_board_is_exactly_one_error_under_the_new_rule():
    """One real defect makes one row — not a hundred — and it is ERROR.

    The part at x = 2200 has a 40-mil pad, so its right edge is at 2220 — 220
    mil past the frame's right edge at 2000; the other 98 are inside. The row
    names the new rule id and keeps the message the old combined rule produced.
    """
    board = _parse(off_board=True)
    findings = _off_board(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == OFF_BOARD_RULE_ID
    assert finding.severity == "ERROR"
    assert finding.target.component_ref == "RZ"
    assert finding.target.measurement == {"kind": "distance", "value": 220.0, "unit": "mil"}
    assert "past the board outline" in finding.message
    # The spacing half is untouched by the off-board part (it is 660 mil clear).
    assert _spacing(board) == []


# ---------------------------------------------------------------------------
# 3. records that do not close a ring are disclosed, never guessed
# ---------------------------------------------------------------------------


def test_fragments_that_do_not_close_are_disclosed_and_file_nothing():
    """An open chain is 「the frame did not read」, said out loud.

    Drop one of the sixteen records and the remaining fifteen are an open chain
    with no closed ring: ``outline`` is ``None``, ``outline_fragments`` states
    how many records were there, and the board-frame rule files no ERROR at all
    — a frame that did not read is not evidence about a part.
    """
    segments = rounded_rect_segments()
    board = _parse(drawn_segments=segments[:-1], parts=98)
    assert board.outline is None
    assert board.outline_fragments == 15
    assert _off_board(board) == []
    # The spacing half still runs — a collision needs no frame (the grid is clean).
    assert _spacing(board) == []


def test_two_disjoint_fragments_are_disclosed_the_same_way():
    """Disjoint pieces (no chain at all) are ``None`` + the count, not a guess."""
    segments = rounded_rect_segments()
    board = _parse(drawn_segments=[segments[1], segments[5]], parts=2)
    assert board.outline is None
    assert board.outline_fragments == 2
    assert _off_board(board) == []


def test_an_open_polyline_inside_the_ring_is_left_out_of_the_frame():
    """Only the **longest closed** ring is the frame; a stray fragment is not.

    A disjoint open piece is added beside the full sixteen-segment frame. The
    frame still stitches into a closed ring and is chosen (the open piece cannot
    close), so the outline is the board again and the part inside it stays
    inside.
    """
    segments = rounded_rect_segments() + [[1500.0, -300.0, "L", 1600.0, -300.0]]
    board = _parse(drawn_segments=segments, parts=98)
    outline = board.outline
    assert outline is not None and outline.closed is True
    assert outline.segments == 17
    assert _off_board(board) == []


# ---------------------------------------------------------------------------
# 4. the split rule: registered, and the old rule is spacing only
# ---------------------------------------------------------------------------


def test_the_new_rule_is_registered_right_after_the_spacing_rule():
    """The list is the truth (126a): a rule that is not listed does not run."""
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert OFF_BOARD_RULE_ID in ids
    assert ids.index(OFF_BOARD_RULE_ID) == ids.index("pcb-component-spacing") + 1


def test_the_spacing_rule_no_longer_files_the_board_frame_error():
    """The split is the point: the board-frame ERROR moved out of ``spacing``.

    Run on the board with a really-off-the-board part, ``ComponentSpacing``
    says nothing (that part is 660 mil clear of everything) while
    ``BoardOffEdge`` files the one ERROR. Before the split both questions were
    one rule id, and that is what buried the report.
    """
    board = _parse(off_board=True)
    assert _spacing(board) == []
    assert [f.rule_id for f in _off_board(board)] == [OFF_BOARD_RULE_ID]


def test_the_stitch_tolerance_is_a_stated_small_number():
    """The join tolerance is documented and small: 1 mil — 20x the arc chord
    error (0.05 mil) and a quarter of the 4-mil pour clearance (审计 325-a3
    订正：原注释把方向写反了）。"""
    assert OUTLINE_STITCH_TOLERANCE_MIL == 1.0


def _as_points(path) -> list[Point]:
    """The points of one raw outline path, via the parser's own reader."""
    from boardwise.parsers.epru import _path_points

    return _path_points(path)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------------------
# 4. the report layer: 「没跑」必须写在 boards[] 上（主代理收口件）
# ---------------------------------------------------------------------------


def test_a_fragmented_unstitched_outline_is_disclosed_on_the_board_entry():
    """bug98 的报告层收口：拼不成闭环 → boards[].outlineNote 点名段数与「未运行」。"""
    from boardwise.engines.pcbreview import _board_entry

    board = _parse(drawn_segments=rounded_rect_segments()[:-1])
    assert board.outline is None and board.outline_fragments == 15  # 前提
    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "15" in note and "未运行" in note, note


def test_a_well_stitched_outline_carries_no_note():
    """有好板框的板不带此键——报告形状对它们逐字节不变。"""
    from boardwise.engines.pcbreview import _board_entry

    board = _parse()
    assert board.outline is not None
    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    assert "outlineNote" not in entry


# ---------------------------------------------------------------------------
# 5. the audit's shapes (325): not-closed singles, leftovers, welds, tolerance
# ---------------------------------------------------------------------------


def test_a_single_open_polyline_is_not_a_frame_and_the_rule_stays_silent():
    """审计 325-a1：单段**开放**折线不是框——护栏必须消费 ``closed``。

    现场板的另一半形状：如果编辑器把圆角矩形存成**一条**不闭环的 11 点弧，
    旧护栏（点数 >= 3）照样放行、全板误报。现在 BoardOffEdge 的沉默条件里
    有 ``not outline.closed``。
    """
    open_arc = _arc_path(_R, -_R, _R, 180, 90)  # 一条角落弧，起点≠终点
    board = _parse(drawn_segments=[open_arc])
    assert board.outline is not None and board.outline.closed is False
    assert _off_board(board) == []
    from boardwise.engines.pcbreview import _board_entry

    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "未闭环" in note and "未运行" in note, note


def test_a_loose_segment_is_counted_not_dropped():
    """审计 325-a2：成了环但有一段没入环——fragments 必须如实计 1。"""
    square = [  # 一个自闭的方框（四条边按端点成环）
        _edge(0.0, 0.0, 500.0, 0.0),
        _edge(500.0, 0.0, 500.0, -500.0),
        _edge(500.0, -500.0, 0.0, -500.0),
        _edge(0.0, -500.0, 0.0, 0.0),
    ]
    loose = [_edge(1500.0, 0.0, 1600.0, 0.0)]  # 游离碎段，接不上任何环
    board = _parse(drawn_segments=square + loose, parts=2)
    assert board.outline is not None and board.outline.closed is True
    assert board.outline_fragments == 1, "没入环的那段必须被数出来"
    from boardwise.engines.pcbreview import _board_entry

    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "未入环" in note and "照跑" in note, note


def test_a_welded_figure_eight_carries_a_weld_disclosure():
    """审计 325-a2 的焊接案：两块板的开段被容差焊成一个环——焊缝必须被点名。

    顶点捏合的 8 字没有任何「真交叉」，几何拒收看不住它（`_is_simple_ring`
    只拒真交叉）；诚实的答案是环照算、但 `tolerance_welds` 记非逐字焊缝的
    数量，报告的 outlineNote 把它说成人工核项。
    """
    panel_a = [
        _edge(0.0, 0.0, 400.0, 0.0),
        _edge(400.0, 0.0, 400.0, -400.0),
        _edge(400.0, -400.0, 0.0, -400.0),
        _edge(0.0, -400.0, 0.0, 0.0),
    ]
    panel_b = [
        _edge(400.5, 0.0, 800.5, 0.0),
        _edge(800.5, 0.0, 800.5, -400.0),
        _edge(800.5, -400.0, 400.5, -400.0),
        _edge(400.5, -400.0, 400.5, 0.0),
    ]
    board = _parse(drawn_segments=panel_a + panel_b, parts=2)
    outline = board.outline
    assert outline is not None and outline.closed is True
    assert outline.tolerance_welds >= 1, "0.5 mil 的焊缝必须被记数"
    from boardwise.engines.pcbreview import _board_entry

    entry = _board_entry(
        title="B1", board=board, board_uuid="", checks_run=[], finding_indexes=[],
    )
    note = entry.get("outlineNote", "")
    assert "容差焊缝" in note and "人工核" in note, note


def test_the_tolerance_actually_welds_a_sub_mil_gap():
    """容差路径的正面覆盖（审计 325-e：之前零覆盖）：0.5 mil 缝隙焊得上。"""
    square = [
        _edge(0.0, 0.0, 500.0, 0.0),
        _edge(500.0, 0.0, 500.5, -500.0),       # 与下一条端点差 0.5 mil
        _edge(500.0, -500.0, 0.0, -500.0),
        _edge(0.0, -500.0, 0.0, 0.0),
    ]
    board = _parse(drawn_segments=square, parts=2)
    assert board.outline is not None and board.outline.closed is True
    assert board.outline_fragments == 0


def test_a_gap_beyond_the_tolerance_does_not_weld():
    """容差之外不焊：2 mil 缝隙拼不成环 → 显性「拼不出」。"""
    square = [
        _edge(0.0, 0.0, 500.0, 0.0),
        _edge(502.0, 0.0, 502.0, -500.0),       # 与上一条端点差 2 mil
        _edge(502.0, -500.0, 0.0, -500.0),
        _edge(0.0, -500.0, 0.0, 0.0),
    ]
    board = _parse(drawn_segments=square, parts=2)
    assert board.outline is None
    assert board.outline_fragments == 4
    assert _off_board(board) == []
