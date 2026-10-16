"""perf-02A: the three memoisation changes — what each must reuse, and what
each must **not** hand back stale.

Three changes, one shape: the same input must produce the same output, and the
input changing must produce a new answer. So each change gets a pair of tests:
one that proves the work is *not* being done again, and one that proves a
changed input is read again.

* **C1** — ``core.parts.load_parts`` is memoised per process. The pair is
  "one parse for three reads" and "a rewritten shelf is read again". The second
  one is the load-bearing half and it is why the key is the file's **content
  digest** rather than ``(st_mtime_ns, size)``: measured on this machine
  (``outputs/perf02A/units.json``), 2000 same-size rewrites of one path produced
  only **784 distinct ``st_mtime_ns`` values** — 1216 of 1999 consecutive
  rewrites carried their predecessor's timestamp. ``test_every_rewrite_is_seen``
  loops the write/read pair so a stat-keyed memo fails it essentially always,
  not 62 % of the time.
* **C2** — ``core.measure.read_stackup`` is memoised on the board. The pair is
  "the same object comes back" and "a board that grew a pad / swapped its
  stackup is read again". The board cache also gets a test that it stays out of
  ``__eq__`` and ``repr`` — the pollution class this repository has been bitten
  by.
* **C3** — ``layout._box_cell_union`` replaces ``classify``'s per-box linear
  scan. The pair is a direct equivalence test against the scan it replaced
  (including the duplicate-designator quirk) and two end-to-end routing scenes
  whose wires must still go **around** the boxes, pinned as digests taken from
  the zero-flip census (``outputs/perf02A/census_before.json``).

Nothing here asserts a wall-clock number: timings live in
``outputs/perf02A/``, where they can be re-measured, and a test that pins a
duration is a test that fails on a busier machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core import parts as parts_module
from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    PadGeometry,
    StackupEntry,
    TrackSegment,
    Point,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary, load_parts, save_parts
from boardwise.core.measure import read_stackup
from boardwise.engines import layout

GRID = layout.GRID


# ---------------------------------------------------------------------------
# C1 — load_parts
# ---------------------------------------------------------------------------


def _shelf(path: Path, *keys: str) -> Path:
    save_parts(
        PartLibrary(
            parts=[
                PartEntry(
                    key=key,
                    value=key,
                    mpn=key.upper(),
                    lcsc=f"C{index + 1}",
                    manufacturer="ACME",
                    deviceUuid=f"dev-{index}",
                    libraryUuid="0819f05c4eef4c71ace90d822a990e87",
                    footprint_name="SOT-23-5",
                )
                for index, key in enumerate(keys)
            ]
        ),
        path,
    )
    return path


@pytest.fixture
def parse_counter(monkeypatch):
    """Count real parses: ``load_parts`` calls ``library_from_json`` by name."""
    calls = {"n": 0}
    real = parts_module.library_from_json

    def counted(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(parts_module, "library_from_json", counted)
    return calls


def test_a_shelf_is_parsed_once_and_every_reader_gets_the_same_object(
    tmp_path, parse_counter
):
    """The whole point: 296-312 reads inside one ``run_pcb_review`` = one parse."""
    shelf = _shelf(tmp_path / "shelf.json", "ic.one")
    first = load_parts(shelf)
    second = load_parts(shelf)
    third = load_parts(str(shelf))  # same file, spelled differently
    assert parse_counter["n"] == 1
    assert first is second is third
    assert [p.key for p in first.parts] == ["ic.one"]


def test_every_rewrite_is_seen_even_when_the_clock_tick_does_not_move(
    tmp_path, parse_counter
):
    """A rewritten shelf must never come back from the memo.

    Each round rewrites the same path with a **different** key of the same byte
    length, then reads it: the clock tick may or may not have moved, the answer
    must. This is the test a ``(mtime, size)`` key fails — see the module
    docstring for the measured collision rate.
    """
    shelf = tmp_path / "shelf.json"
    seen: list[str] = []
    for round_number in range(20):
        key = f"ic.rewrite{round_number:02d}"
        _shelf(shelf, key)
        loaded = load_parts(shelf)
        assert [p.key for p in loaded.parts] == [key], f"round {round_number} went stale"
        seen.append(key)
    assert parse_counter["n"] == 20
    assert len(set(seen)) == 20


def test_a_shelf_that_appears_after_a_missing_read_is_read(tmp_path):
    """``parts add`` on a path with no shelf yet: missing is empty, not cached."""
    shelf = tmp_path / "new" / "shelf.json"
    assert load_parts(shelf).parts == []
    _shelf(shelf, "ic.fresh")
    assert [p.key for p in load_parts(shelf).parts] == ["ic.fresh"]


def test_a_shelf_that_is_not_json_still_refuses_and_is_not_memoised(tmp_path):
    """The error path is untouched, and a refusal must not poison the memo."""
    from boardwise.core.parts import PartError

    shelf = tmp_path / "shelf.json"
    shelf.write_text("{ not json at all", encoding="utf-8")
    with pytest.raises(PartError):
        load_parts(shelf)
    with pytest.raises(PartError):
        load_parts(shelf)
    _shelf(shelf, "ic.after")
    assert [p.key for p in load_parts(shelf).parts] == ["ic.after"]


def test_a_shelf_written_through_save_parts_is_read_back_whole(tmp_path):
    """The one writer in the code base: append, save, re-read.

    ``boardwise parts add`` loads the shelf, appends an entry and saves it, then
    re-reads to let the validator decide whether the write landed. The memo must
    not short-circuit that re-read into the object it just mutated.
    """
    shelf = _shelf(tmp_path / "shelf.json", "ic.one")
    library = load_parts(shelf)
    library.parts.append(
        PartEntry(
            key="ic.two",
            value="two",
            mpn="TWO",
            lcsc="C2",
            manufacturer="ACME",
            deviceUuid="dev-2",
            libraryUuid="0819f05c4eef4c71ace90d822a990e87",
            footprint_name="SOT-23-5",
        )
    )
    library.parts.sort(key=lambda p: p.key)
    save_parts(library, shelf)
    assert [p.key for p in load_parts(shelf).parts] == ["ic.one", "ic.two"]
    assert json.loads(shelf.read_text(encoding="utf-8"))["parts"][-1]["key"] == "ic.two"


# ---------------------------------------------------------------------------
# C2 — read_stackup
# ---------------------------------------------------------------------------


def _board(*, with_stackup: bool = True) -> BoardGeometry:
    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        15: LayerInfo(15, "Inner1", "SIGNAL"),
        361: LayerInfo(361, "Dielectric1", "SUBSTRATE"),
    }
    stackup = (
        [
            StackupEntry(1, 1000, "outer copper", 1.378),
            StackupEntry(361, 1001, "core", 8.283),
            StackupEntry(2, 9000, "outer copper", 1.378),
        ]
        if with_stackup
        else []
    )
    return BoardGeometry(
        layers=layers,
        stackup=stackup,
        pads=[PadGeometry(id="p1", net="A", footprint_layer_id=1)],
        tracks=[
            TrackSegment(
                id="t1", net="A", layer_id=15, start=Point(0, 0), end=Point(10, 0), width=5
            )
        ],
    )


def test_read_stackup_is_read_once_and_says_the_same_thing_as_a_fresh_board():
    board = _board()
    first = read_stackup(board)
    second = read_stackup(board)
    assert first is second
    fresh = read_stackup(_board())
    assert first == fresh
    assert [li.layer_id for li in first.copper_layers] == [1, 2]
    assert first.used_copper_layer_ids == [1, 15]


def test_a_board_that_grew_a_pad_is_read_again():
    board = _board()
    assert read_stackup(board).used_copper_layer_ids == [1, 15]
    board.pads.append(PadGeometry(id="p2", net="B", footprint_layer_id=2))
    assert read_stackup(board).used_copper_layer_ids == [1, 2, 15]


def test_a_board_whose_stackup_was_replaced_is_read_again():
    board = _board()
    assert read_stackup(board).copper_count == 2
    board.stackup = []
    # Without LAYER_PHYS the LAYER table is the truth: 1, 2 and 15 are copper.
    assert read_stackup(board).copper_count == 3
    board.layers[16] = LayerInfo(16, "Inner2", "SIGNAL")
    assert read_stackup(board).used_copper_layer_ids == [1, 15]


def test_the_board_cache_stays_out_of_equality_and_repr():
    """A cache is not part of what a board *is* (the pollution class to avoid)."""
    read = _board()
    untouched = _board()
    read_stackup(read)
    assert read == untouched
    assert repr(read) == repr(untouched)
    assert "_stackup_cache" not in repr(read)


# ---------------------------------------------------------------------------
# C3 — the box-cell union
# ---------------------------------------------------------------------------


def _box(designator: str, x0: float, y0: float, x1: float, y1: float) -> layout.Placement:
    return layout.Placement(designator, x0, y0, layout.Rect(x0, y0, x1, y1))


def _cells(rect: layout.Rect) -> set[tuple[int, int]]:
    return {
        (i, j)
        for i in range(int(rect.x0 / GRID), int(rect.x1 / GRID) + 1)
        for j in range(int(rect.y0 / GRID), int(rect.y1 / GRID) + 1)
    }


def test_the_union_answers_exactly_what_the_per_box_scan_answered():
    """Equivalence, cell by cell, over a region that covers every box and more."""
    placements = [
        _box("U1", 100.0, 100.0, 160.0, 160.0),
        _box("U2", 350.0, 80.0, 500.0, 400.0),
        _box("U3", 700.0, 100.0, 760.0, 160.0),
    ]
    boxes = [_cells(p.bbox) for p in placements]
    union = layout._box_cell_union(placements)
    assert union == set().union(*boxes)
    for i in range(20, 160):
        for j in range(15, 85):
            scan = any((i, j) in cells for cells in boxes)
            assert ((i, j) in union) is scan, (i, j)


def test_the_union_keeps_the_one_box_per_designator_quirk():
    """Two placements, one designator: the **later** box is the one that counts."""
    first = _box("U1", 100.0, 100.0, 160.0, 160.0)
    second = _box("U1", 700.0, 700.0, 760.0, 760.0)
    union = layout._box_cell_union([first, second])
    assert union == _cells(second.bbox)
    assert (int(first.x / GRID), int(first.y / GRID)) not in union


def test_a_boxless_placement_contributes_nothing():
    union = layout._box_cell_union(
        [layout.Placement("U1", 0.0, 0.0, None), _box("U2", 100.0, 100.0, 110.0, 110.0)]
    )
    assert union == _cells(layout.Rect(100.0, 100.0, 110.0, 110.0))


def _scene(*boxes) -> tuple[DesignModel, dict, list[layout.Placement]]:
    """Components whose pins sit on the y-midpoint of their east and west edges."""
    model = DesignModel()
    placements: list[layout.Placement] = []
    pins: dict[tuple[str, str], tuple[float, float]] = {}
    for designator, x0, y0, x1, y1 in boxes:
        model.components[designator] = Component(
            uid=designator.lower(),
            designator=designator,
            pins=[Pin("1", "A", None), Pin("2", "B", None)],
        )
        pins[(designator, "1")] = (x1, (y0 + y1) / 2.0)
        pins[(designator, "2")] = (x0, (y0 + y1) / 2.0)
        placements.append(_box(designator, x0, y0, x1, y1))
    return model, pins, placements


def _polylines(routes) -> list[list[list[float]]]:
    return [
        [[p[0], p[1]] for line in route.polylines for p in line]
        for route in sorted(routes, key=lambda r: r.net)
    ]


def test_a_wire_still_goes_around_the_box_between_its_two_pins():
    """The box is an obstacle, and the *only* thing between these two pins.

    Pinned from the zero-flip census (``outputs/perf02A/census_before.json``,
    scene ``detour``), which is the same answer the per-box scan gave: the wire
    leaves U1's east edge, drops to ``y = 75`` — under the wall, which spans
    ``y = 80..400`` — crosses, and comes back up to U5. A router that stopped
    treating box cells as blocked would head straight across at ``y = 130``.
    """
    model, pins, placements = _scene(
        ("U1", 100.0, 100.0, 160.0, 160.0),
        ("U5", 700.0, 100.0, 760.0, 160.0),
        ("U3", 350.0, 80.0, 500.0, 400.0),
    )
    model.nets["N1"] = Net("N1", [("U1", "1"), ("U5", "2")])
    routes, violations = layout.route_nets(model, pins, placements)
    assert violations == []
    assert _polylines(routes) == [
        [[160.0, 130.0], [170.0, 130.0], [170.0, 75.0], [505.0, 75.0],
         [505.0, 130.0], [700.0, 130.0]]
    ]
    wall = _cells(placements[2].bbox)
    for line in _polylines(routes):
        for point in line:
            assert layout._cell((point[0], point[1])) not in wall


def test_a_wire_threads_a_maze_of_boxes_by_the_whole_set_not_by_one_of_them():
    """Several walls: the answer depends on *every* box, not on the first one.

    Also pinned from the census (scene ``maze``). This is the scene that
    separates "the union of all the boxes" from "the first box I happened to
    see" — the two disagree here, and only the union's answer is the one the
    shipped router gave before the change.
    """
    model, pins, placements = _scene(
        ("U1", 100.0, 100.0, 160.0, 160.0),
        ("U6", 900.0, 600.0, 960.0, 660.0),
        ("U2", 300.0, 100.0, 460.0, 700.0),
        ("U3", 600.0, 300.0, 760.0, 700.0),
        ("U4", 300.0, 300.0, 460.0, 500.0),
    )
    model.nets["N1"] = Net("N1", [("U1", "1"), ("U6", "1")])
    routes, violations = layout.route_nets(model, pins, placements)
    assert violations == []
    points = [[p[0], p[1]] for line in _polylines(routes) for p in line]
    assert points[0] == [160.0, 130.0] and points[-1] == [960.0, 630.0]
    # Every other point must stand **outside** every box. The first and last are
    # the two pin tips, which sit inside their own box; a router answering "is
    # this cell in a box?" from one box instead of the whole set cuts straight
    # through U2/U3/U4 and lands interior points inside them.
    blocked = layout._box_cell_union(placements)
    for line in _polylines(routes):
        for point in line[1:-1]:
            assert layout._cell((point[0], point[1])) not in blocked, point
