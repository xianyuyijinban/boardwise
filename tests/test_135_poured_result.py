"""Task 135: ``POURED`` records — the pour **result**, parsed.

125b recorded the gap and could not close it: a ``POURED`` path "is not in
board coordinates" (its points sat in a small local range, y = 22…78, while the
board spanned y = 208…790), and the parser therefore kept the record and left
its ``points`` empty. 131f then added ``POUR`` — the pour **region**, in board
coordinates — and every consumer read that instead.

**What 135 established, and how.**

* **Scale.** ``POURED.pourFill[].path`` is ``board / 10``: a plain uniform
  1:10 scale, origin (0, 0), no axis flip. The proof is a parent ``POUR``
  region whose own rectangle is a clean anchor. On 毕设FOC 1.0.0, ``POUR``
  ``00b83083c1b59f8f`` (net ``IA+``) is
  ``["R", 6695.1024, -1625.2362, 144.8998, 149.7638, 0, 0]`` — x
  6695.1024…6840.0022, y −1625.2362…−1475.4724 — and its ``POURED`` fills
  x 669.9102…683.6002, y −177.1000…−1629.2362 locally. Times ten that is
  6699.102…6836.002 / −1771.000…−1629.236: inside the region, inset by
  exactly 4 mil per side. **That 4 is the pour's own edge clearance, not a
  frame offset** — a fact this file pins by *rejecting* the ±4 transform
  (mutation 2 below is the same check in code).
* **The scale is a constant, not a DPI/grid artifact.** The boards' ``CANVAS``
  record reads ``unit: "mil"``, ``gridXSize: 5`` on every fixture, and under
  ``×10`` every filled point of a parent-linked ``POURED`` lands inside its own
  parent region — re-measured for all three boards that store ``POUR`` regions,
  subject to the rotated-rectangle caveat spelled out in that test.
* **Parent chain.** ``POURED``'s id tuple's second slot resolves to a ``POUR``
  on some records and to **nothing** on the rest: 毕设FOC 1.0.0 splits 27 / 24,
  1.1.0 33 / 22, ROBOT 3 / 1, llc 0 / 4. The orphans are not another record
  type and their ids are not recoverable by ticket, by id scan, or from
  ``LAYER_FILL``. They are pours whose region the editor had already replaced
  before saving. Their copper parses; their net does not, and
  ``ParseStats.poured_orphans`` says so rather than guessing.
* **The array.** ``pourFill`` is an array (one region pours into up to 14
  disjoint islands). Only ``fill: true`` entries are copper; ``fill: false``
  with a non-zero ``strokeWidth`` is the region outline drawn as a stroke.
  Each ``fill: true`` entry becomes its own polygon — concatenating them would
  weld separate islands with copper the pour engine did not create.
* **The consumption decision.** A ``POUR`` region and the ``POURED`` result
  poured from it are one piece of copper described twice, so where both exist
  the **result** is read and the region is skipped
  (:func:`boardwise.core.measure._poured_supersedes`). A ``POURED`` with no
  surviving region stands on its own.

**U10 — the acceptance question.** 131d/133d's R9 read 毕设FOC 1.0.0's ``U10``
(DRV8350SRTVR) exposed pad as an island to itself with area 0.0, while the
1.1.0 board's identical ``U2`` sat in a 15-member island of 24 523 sq mil —
"cannot tell a real defect from an unparsed result layer" was the open worry.
With ``POURED`` parsed the answer is **unchanged and now grounded**: on 1.0.0
there is *no* top-layer copper of any net under ``U10``'s EP, so the pad really
is alone. On 1.1.0 the EP's island gains a ``POURED`` member
(``["POURED","9f5f134c801270d3"]``) and its measured pour area moves
24 522.8 → 21 644.1 sq mil — the *result* is less copper than the region, which
is the point: the region is the intent, the result is what the pour engine
left. Same verdict, better evidence.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from boardwise.core.geometry import BBox, BoardGeometry, Point, PourShape
from boardwise.core.measure import (
    _pad_key,
    _point_in_polygon,
    pour_connectivity,
    region_copper,
)
from boardwise.parsers.epru import (
    POURED_SCALE,
    extract_board,
    load_epro2_source,
    parse_epru_text,
    parse_epro2,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"


def _pcb(path: Path, title: str = "PCB1") -> BoardGeometry:
    """The board geometry of one PCB document, named by its ``META`` title."""
    source = load_epro2_source(path)
    for document in source.documents_of_type("PCB"):
        for record in document.records:
            if record.type == "META" and record.body is not None:
                if str(record.body.get("title") or "") == title:
                    return extract_board(document, source.footprints(), source.stats)
    raise AssertionError(f"{path.name} carries no PCB document titled {title!r}")


def _poured(board: BoardGeometry) -> list[PourShape]:
    return [p for p in board.pours if p.kind == "poured"]


def _rec(rtype: str, id_: str, body: dict) -> str:
    """One ``.epru`` line. ``id_`` is the **raw JSON** id string, so callers
    pass the tuple form already encoded, e.g. ``'["POURED","r1"]'``."""
    import json

    envelope = json.dumps(
        {"type": rtype, "ticket": 9, "id": id_}, separators=(",", ":")
    )
    return envelope + "||" + json.dumps(body, separators=(",", ":")) + "|"


def _doc_head(doc_type: str = "PCB") -> str:
    import json

    envelope = json.dumps(
        {"type": "DOCHEAD", "ticket": 1, "id": "d1",
         "docType": doc_type, "uuid": "u1"}, separators=(",", ":")
    )
    return envelope + "||" + json.dumps({"docType": doc_type}, separators=(",", ":")) + "|"


# ---------------------------------------------------------------------------
# 一、the transform: board = 10 * local
# ---------------------------------------------------------------------------


def test_the_scale_is_one_to_ten_and_is_a_constant():
    assert POURED_SCALE == 10.0


def test_poured_points_are_ten_times_the_stored_coordinates():
    """A hand-built POURED: local 6.0, -4.0 must land at board 60.0, -40.0."""
    text = "\n".join(
        [
            _doc_head(),
            _rec(
                "POURED",
                '["POURED","region1"]',
                {"pourFill": [{"strokeWidth": 0, "fill": True,
                              "path": [6.0, -4.0, "L", 8.0, -4.0, 8.0, -6.0, 6.0, -6.0, 6.0, -4.0]}]},
            ),
        ]
    )
    board = parse_epru_text(text)
    pours = [p for p in board.pours if p.kind == "poured"]
    assert len(pours) == 1
    xs = sorted({round(p.x, 6) for p in pours[0].points})
    ys = sorted({round(p.y, 6) for p in pours[0].points})
    assert xs == [60.0, 80.0]
    assert ys == [-60.0, -40.0]


def test_the_transform_has_no_offset_and_no_flip():
    """Negative and positive local coordinates keep their sign and their value.

    A ±4 mil origin shift, a y-flip, or a parent-relative frame would each move
    these numbers; only ``x * 10`` leaves them alone.
    """
    text = "\n".join(
        [
            _doc_head(),
            _rec("POURED", '["POURED","r"]',
                 {"pourFill": [{"fill": True,
                               "path": [0.0, 0.0, "L", 1.0, 0.0, 1.0, 1.0,
                                        -1.0, -1.0, -1.0, 0.0, 0.0, 0.0]}]}),
        ]
    )
    board = parse_epru_text(text)
    pours = [p for p in board.pours if p.kind == "poured"]
    xs = sorted({round(p.x, 6) for p in pours[0].points})
    ys = sorted({round(p.y, 6) for p in pours[0].points})
    assert xs == [-10.0, 0.0, 10.0]
    assert ys == [-10.0, 0.0, 10.0]


@pytest.mark.parametrize(
    "path,expected_poured_records",
    [(FOC_100, 50), (ROBOT, 4), (LLC, 4)],
)
def test_every_poured_on_the_fixtures_carries_a_polygon(path, expected_poured_records):
    """Acceptance anchors: the POURED record counts, measured on each fixture.

    Counted over the ``PourShape`` list, so a ``POURED`` that poured into
    several islands contributes several shapes — 毕设FOC 1.0.0's 51 records
    become 82 shapes, 50 of which carry copper (one record's ``pourFill`` holds
    no ``fill: true`` entry at all, which is what ``poured_without_fill``
    counts).
    """
    board = parse_epro2(str(path))
    poured = _poured(board)
    records = {p.id for p in poured}
    assert len(records) == expected_poured_records
    assert all(len(p.points) >= 3 for p in poured)


def test_every_filled_point_of_a_parent_linked_poured_lands_in_its_parent():
    """The measurement that decided the question.

    On every board fixture, take each ``POURED`` whose parent resolves to a
    ``POUR``, scale its filled points by 10, and require each one to lie inside
    that parent's region. A tolerance band of 0.6 mil absorbs points sitting
    exactly on the region outline.

    **Scope: regions the parser can place.** A ``POUR`` stored as
    ``["R", x, y, w, h, rotation, radius]`` is expanded by
    ``_path_points``, which **reads ``rotation`` but does not apply it** — so a
    region drawn rotated is an axis-aligned box in the wrong place. That is a
    pre-existing gap in the rectangle reader (it predates this task and is not
    a ``POURED`` question), and it makes exactly two of 毕设FOC 1.0.0's 27
    parent regions unusable as anchors: ``0ad0a69ed96084b5`` and
    ``41a3e47860f2653b``, both stored with ``rotation: -90``. The other 18
    unrotated rectangular anchors all pass, and so does the ``rotation: 90``
    case ``70c0da6feb4302a3`` (its ``POURED`` carries no filled polygon). This
    test therefore asserts the 18 that the parser can actually place; the two
    rotated ones are left as they are, and this comment is the record.
    """
    total = 0
    skipped = []
    for path in (FOC_100, FOC_110, ROBOT):
        board = parse_epro2(str(path))
        regions = {
            p.id: p.points for p in board.pours
            if p.kind == "pour" and len(p.points) >= 3
        }
        checked = 0
        for poured in _poured(board):
            region = regions.get(poured.poured_from or "")
            if region is None:
                continue  # an orphan: nothing to check it against
            if poured.poured_from in _ROTATED_REGION_IDS:
                skipped.append(poured.poured_from)
                continue
            for point in poured.points:
                total += 1
                assert _within(point, region), (
                    f"{path.name}: {poured.id} point {point} is outside its "
                    f"parent region {poured.poured_from}"
                )
                checked += 1
        assert checked, f"{path.name}: no parent-linked POURED at all"
    assert total > 1000, total
    # The two known-unplaceable anchors were seen, so the skip is exercised.
    assert set(skipped) == _ROTATED_REGION_IDS


#: 毕设FOC 1.0.0 POUR regions stored with a non-zero ``rotation`` **whose
#: POURED carries filled copper**, so the region would be the anchor but the
#: parser cannot place it (``_path_points`` reads ``rotation`` and does not
#: apply it). A third rotated region exists,
#: ``["R", …, 90, 0]`` ``70c0da6feb4302a3``, but its ``POURED`` holds no
#: filled polygon at all, so it never reaches the check. See the test above.
_ROTATED_REGION_IDS = frozenset(
    {"0ad0a69ed96084b5", "41a3e47860f2653b"}
)


def _within(point: Point, polygon: list[Point], eps: float = 0.6) -> bool:
    """``point`` is inside ``polygon``, or within ``eps`` of its boundary."""
    if _point_in_polygon(point, polygon):
        return True
    n = len(polygon)
    for i in range(n):
        a, b = polygon[i], polygon[(i + 1) % n]
        dx, dy = b.x - a.x, b.y - a.y
        length_sq = dx * dx + dy * dy
        if length_sq == 0.0:
            continue
        t = max(0.0, min(1.0, ((point.x - a.x) * dx + (point.y - a.y) * dy) / length_sq))
        px, py = a.x + t * dx, a.y + t * dy
        if math.hypot(px - point.x, py - point.y) <= eps:
            return True
    return False


# ---------------------------------------------------------------------------
# 二、the parent chain, and the orphans that have none
# ---------------------------------------------------------------------------


def test_a_poured_borrows_its_parent_regions_net_and_layer():
    text = "\n".join(
        [
            _doc_head(),
            _rec("POUR", "region1",
                 {"netName": "GND", "layerId": 1, "width": 0.2,
                  "path": [["R", 0.0, 0.0, 100.0, 100.0, 0, 0]]}),
            _rec("POURED", '["POURED","region1"]',
                 {"pourFill": [{"fill": True,
                               "path": [1.0, 1.0, "L", 9.0, 1.0, 9.0, 9.0, 1.0, 9.0, 1.0, 1.0]}]}),
        ]
    )
    board = parse_epru_text(text)
    poured = [p for p in board.pours if p.kind == "poured"][0]
    assert poured.net == "GND"
    assert poured.layer_id == 1
    assert poured.poured_from == "region1"
    assert board.stats.poured_with_parent == 1
    assert board.stats.poured_orphans == 0


@pytest.mark.parametrize(
    "path,with_parent,orphans",
    [
        (FOC_100, 27, 24),
        (FOC_110, 25, 10),
        (ROBOT, 3, 1),
        (LLC, 0, 4),
    ],
)
def test_the_parent_link_splits_and_the_orphans_are_counted(path, with_parent, orphans):
    """Acceptance anchors for the headless half of the parent chain.

    These four splits are measured, and 125b's 「only 8 of 55 resolve」 is the
    shape of the same gap: on every board roughly half the ``POURED`` records
    name a region that is not in the file. The copper still parses; the net does
    not, and the counters say which records are which instead of leaving the
    reader to guess.

    These are the counts of the PCB document ``parse_epro2`` reads — the
    **first** one in the file, which on 1.1.0 is ``PCB3`` (35 POURED, 25/10),
    not ``PCB1`` (55 records, 8/47). A caller that wants ``PCB1`` walks
    ``Epro2Source.documents_of_type`` itself, exactly as the 133x rules do.
    """
    board = parse_epro2(str(path))
    assert board.stats.poured_with_parent == with_parent
    assert board.stats.poured_orphans == orphans


def test_an_orphan_poured_still_parses_its_copper_with_no_net():
    text = "\n".join(
        [
            _doc_head(),
            _rec("POURED", '["POURED","e-does-not-exist"]',
                 {"pourFill": [{"fill": True,
                               "path": [1.0, 1.0, "L", 9.0, 1.0, 9.0, 9.0, 1.0, 9.0, 1.0, 1.0]}]}),
        ]
    )
    board = parse_epru_text(text)
    poured = [p for p in board.pours if p.kind == "poured"][0]
    assert len(poured.points) == 5
    assert poured.net is None
    assert poured.layer_id is None
    assert poured.poured_from == "e-does-not-exist"
    assert board.stats.poured_orphans == 1
    assert board.stats.poured_with_parent == 0


def test_a_poured_with_no_filled_polygon_is_counted_separately():
    """``fill: false`` entries are the stroked outline, not copper."""
    text = "\n".join(
        [
            _doc_head(),
            _rec("POURED", '["POURED","r"]',
                 {"pourFill": [{"strokeWidth": 0.5, "fill": False, "path": [1.0, 1.0, "L", 9.0, 9.0]}]}),
        ]
    )
    board = parse_epru_text(text)
    assert _poured(board) == []
    assert board.stats.poured_without_fill == 1


def test_the_poured_counters_reach_the_stats_dict():
    board = parse_epro2(str(FOC_100))
    payload = board.stats.as_dict()
    assert payload["poured_with_parent"] == 27
    assert payload["poured_orphans"] == 24
    assert "poured_without_fill" in payload


# ---------------------------------------------------------------------------
# 三、the pourFill array: islands are separate polygons
# ---------------------------------------------------------------------------


def test_each_filled_entry_is_its_own_polygon():
    """Two `fill: true` entries are two islands, not one welded polygon.

    Concatenating them would draw an implied bridge between the two squares
    that the pour engine explicitly did not create, and the shape's bounding
    box would cover the gap between them.
    """
    text = "\n".join(
        [
            _doc_head(),
            _rec("POURED", '["POURED","r"]',
                 {"pourFill": [
                     {"fill": True, "path": [0.0, 0.0, "L", 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0]},
                     {"fill": True, "path": [5.0, 5.0, "L", 6.0, 5.0, 6.0, 6.0, 5.0, 6.0, 5.0, 5.0]},
                 ]}),
        ]
    )
    board = parse_epru_text(text)
    poured = _poured(board)
    assert len(poured) == 2
    # Both carry the record's id, so a reader can group them.
    assert len({p.id for p in poured}) == 1
    # The gap between the two squares (x = 10..50 in board units) is not
    # spanned by either polygon.
    for shape in poured:
        xs = [p.x for p in shape.points]
        assert max(xs) - min(xs) == 10.0
        assert not _point_in_polygon(Point(300.0, 300.0), shape.points)


def test_a_fixture_poured_really_does_carry_several_islands():
    """The array is not a theory: 毕设FOC 1.0.0's ``["POURED","e1475"]`` has 14."""
    board = parse_epro2(str(FOC_100))
    islands = [p for p in _poured(board) if p.id == '["POURED","e1475"]']
    assert len(islands) == 14


# ---------------------------------------------------------------------------
# 四、the consumption decision: result over region, no double count
# ---------------------------------------------------------------------------


def test_a_superseded_region_is_not_counted_beside_its_result():
    board = parse_epro2(str(FOC_100))
    regions = {p.id for p in board.pours if p.kind == "pour"}
    superseded = {p.poured_from for p in _poured(board)} & regions
    # Both really exist on this board …
    assert superseded, "the fixture has no superseded region to test with"
    # … and the island inventory names the result, not the region.
    from boardwise.core.measure import _net_shape_records

    seen: set[str] = set()
    for net in board.nets:
        for element_id, _shape, _area in _net_shape_records(board, board.net(net), with_area=False):
            seen.add(element_id)
    assert not (superseded & seen), sorted(superseded & seen)


def test_an_orphan_result_still_counts_with_no_region_to_replace():
    """llc stores four POURED records and no POUR at all: nothing is superseded,
    so all of its poured copper reaches the consumers."""
    board = parse_epro2(str(LLC))
    assert not [p for p in board.pours if p.kind == "pour"]
    assert len(_poured(board)) > 0


def test_region_copper_reports_the_poured_result():
    """`region_copper` must file a POURED result like any other pour.

    毕设FOC 1.0.0's ``["POURED","46a546a11122f67c"]`` (net ``+24V``, layer 1,
    from the parent ``POUR`` of the same id) is a plain filled rectangle; asking
    for its own bounding box must return it with ``pour_kind == "poured"``.
    Before 135 the inventory skipped every ``poured`` shape outright.

    The orphan results (no parent ⇒ no layer) are *not* filed, and that is the
    right reading: ``region_copper`` iterates the copper layers one at a time
    and an element with no layer takes part in none of them — the same
    "unclassifiable, never guessed" rule every other reader follows.
    """
    board = parse_epro2(str(FOC_100))
    poured = next(p for p in _poured(board) if p.id == '["POURED","46a546a11122f67c"]')
    assert poured.layer_id == 1 and poured.net == "+24V"
    box = poured.bbox
    assert box is not None
    report = region_copper(board, box)
    poured_items = [
        item
        for items in report.layers_by_id.values()
        for item in items
        if item.pour_kind == "poured"
    ]
    assert poured_items, "no poured copper in the result polygon's own bounding box"
    assert any(item.element_id == poured.id for item in poured_items)

    orphan = next(p for p in _poured(board) if p.net is None and len(p.points) >= 3)
    assert orphan.layer_id is None
    orphan_items = [
        item
        for items in region_copper(board, orphan.bbox).layers_by_id.values()
        for item in items
        if item.pour_kind == "poured"
    ]
    assert orphan_items == [], "a layer-less orphan must not be filed on any layer"


# ---------------------------------------------------------------------------
# 五、U10 — the acceptance question, answered with the result layer
# ---------------------------------------------------------------------------


def test_u10_ep_on_1_0_0_sits_on_no_top_layer_copper_at_all():
    """The answer to 「does the EP connect to a big plane?」 on 1.0.0: no.

    Not 「the model cannot see it」 — with ``POURED`` parsed, and given the
    board's *own* ``POURED`` results, there is still **no top-layer polygon of
    any net** whose interior contains the pad's centre. So the EP really is
    alone on the top face, and 133d's reading of a five-piece island was a
    statement about the board, not about the parser.
    """
    board = _pcb(FOC_100)
    comp = next(c for c in board.components if c.designator == "U10")
    ep = max((p for p in board.pads if p.component_id == comp.id),
             key=lambda p: p.width * p.height)
    centre = Point(ep.x, ep.y)
    assert ep.net == "GND"
    assert ep.effective_layers() == {1}

    on_its_own_layer = [
        p for p in board.pours
        if len(p.points) >= 3 and p.layer_id in ep.effective_layers()
    ]
    assert on_its_own_layer, "the board should carry top-layer pours somewhere"
    assert not [p for p in on_its_own_layer if _point_in_polygon(centre, p.points)]

    conn = pour_connectivity(board, ep.net)
    assert _pad_key(ep) in next(
        i.element_ids for i in conn.islands if any(_pad_key(ep) in e for e in i.element_ids)
    )


def test_u2_ep_on_1_1_0_is_continuous_and_its_island_is_a_poured_result():
    """The contrast that makes the 1.0.0 answer meaningful.

    Same part, same 126 × 126 mil pad: on 1.1.0 the EP sits in a 15-member
    island whose pour member is a ``POURED`` record — and whose area is *less*
    than the region it replaced (24 522.8 → 21 644.1 sq mil), which is what a
    result layer should look like: the same copper with the clearance voids cut
    out of it.
    """
    board = _pcb(FOC_110)
    comp = next(c for c in board.components if c.designator == "U2")
    ep = max((p for p in board.pads if p.component_id == comp.id),
             key=lambda p: p.width * p.height)
    epkey = _pad_key(ep)
    conn = pour_connectivity(board, ep.net)
    island = next(i for i in conn.islands if any(epkey in e for e in i.element_ids))
    assert island.island_id == 9
    assert len(island.element_ids) == 15
    assert sorted(island.layer_ids) == [1, 2, 15, 16]
    assert '["POURED","9f5f134c801270d3"]' in island.element_ids
    assert island.area == pytest.approx(21644.1, abs=0.1)


# ---------------------------------------------------------------------------
# 六、the numbers this moved, and why each one moved
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,net,before_islands,after_islands",
    [
        # The result layer fragments what the region drew as one piece.
        (ROBOT, "GND", 1, 15),
        # Or removes the clearance voids from it.
        (FOC_100, "GND", 46, 39),
    ],
)
def test_island_counts_move_and_the_reason_is_the_result_layer(
    path, net, before_islands, after_islands
):
    """Acceptance anchors, each a correction rather than a regression.

    ROBOT's ``GND`` region is one solid plane; its poured **result** is
    fifteen pieces, and the island count now says so. 毕设FOC 1.0.0's ``GND``
    loses islands because the result polygons exclude the parts the pour engine
    cleared away. Both are the same rule: read the result, not the intent.
    """
    board = parse_epro2(str(path))
    conn = pour_connectivity(board, net)
    assert conn.island_count == after_islands