"""Task 162b: six parse-layer truths about ``.epru`` (H1-H6 of 161's triage).

162b is the parser half of 批 A. None of these is a rule; every one is a reading
of the file that was wrong, or absent, and each is pinned here against the real
fixtures (read-only). The measured numbers behind each claim are in the
docstrings, and ``outputs/162b/evidence.md`` carries the probes they came from.

* **H1** — ``_artwork_path`` read an ``ARC``'s **sweep angle** as an x
  coordinate. ``_path_points`` (the copper reader) had it right all along.
* **H2** — a ``SLOT`` hole was described as a circle of the slot's length and
  its second dimension was never read.
* **H3** — a bottom-mounted part's footprint artwork was reported on the **top**
  silkscreen, because the library's own layer id was used as the printed layer.
* **H4** — non-copper polygons (solder-mask openings) were filed with the
  pours: llc's summary said 137 pours where 32 polygons are copper.
* **H5** — ``POUR`` was not in ``KNOWN_RECORD_TYPES``, so every board carrying
  one reported a "format drift" for a record the parser was decoding. ``REGION``
  had the same defect and joins it here.
* **H6** — ``REGION`` records (copper-prohibition areas) were counted as
  unconsumed and dropped. They are now parsed and exposed, with **no** rule
  consuming them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise.core.geometry import MULTI_LAYER_ID, Point
from boardwise.parsers.epru import (
    ARTWORK_RECORD_TYPES,
    _artwork_path,
    _path_points,
    build_board_geometry,
    footprint_artwork,
    load_epro2_source,
    pad_templates,
)

FIXTURES = Path(__file__).parent / "fixtures"

FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
LLC = FIXTURES / "llc_board.epro2"
CASCADE_MAIN = FIXTURES / "级联多电平-主拓扑_2026-09-27.epro2"
SPEED = FIXTURES / "ProPrj_高速电机控制器_2026-09-16.epro2"


def _board(path: Path):
    source = load_epro2_source(path)
    return source, build_board_geometry(source)


def _context(path: Path):
    source = load_epro2_source(path)
    return source, source.pcb_context()


def _raw_artwork_paths(document):
    """Every artwork record's raw ``path`` in one FOOTPRINT document."""
    out = []
    for record in document.records:
        if record.type not in ARTWORK_RECORD_TYPES or not isinstance(record.body, dict):
            continue
        path = record.body.get("path")
        if isinstance(path, list):
            out.append((record.type, record.id, path))
    return out


def _items(path):
    """A ``path``'s raw item list, unwrapped once (FILL wraps its list)."""
    return path[0] if path and isinstance(path[0], list) else path


def _sweeps(items):
    """The numbers that sit immediately after an ``"ARC"`` token."""
    return {
        items[i + 1]
        for i, value in enumerate(items)
        if isinstance(value, str) and value.upper() == "ARC" and i + 1 < len(items)
    }


# ---------------------------------------------------------------------------
# H1 — the ARC sweep is an angle, not a coordinate
# ---------------------------------------------------------------------------


def test_the_arc_probe_from_the_audit_keeps_its_endpoint():
    """The exact probe 161 reproduced: ``_artwork_path`` used to answer (-90, 34.401).

    ``["ARC", <sweep>, x, y]``: the endpoint must survive and the angle must not
    become a coordinate. The old reader dropped the pending start point, then
    paired the sweep with the endpoint's x — the endpoint itself (13.671) fell
    off the end unpaired.
    """
    points, radius, arcs = _artwork_path([28.401, 19.671, "ARC", -90, 34.401, 13.671])
    assert [(p.x, p.y) for p in points] == [(28.401, 19.671), (34.401, 13.671)]
    assert radius is None and arcs == 1


def test_both_path_readers_agree_on_an_arc_path():
    """The two readers of the same encoding must say the same thing.

    ``_path_points`` is the copper reader and was already right (``index += 2``:
    skip ``"ARC"`` and the sweep, then read the endpoint); ``_artwork_path``
    now reads it the same way instead of disagreeing.
    """
    path = [0.0, 0.0, "L", 10.0, 0.0, "ARC", 90, 20.0, 20.0, "ARC", -45, 25.0, 10.0]
    flat = [(p.x, p.y) for p in _path_points(path)]
    art = [(p.x, p.y) for p in _artwork_path(path)[0]]
    assert flat == art == [(0.0, 0.0), (10.0, 0.0), (20.0, 20.0), (25.0, 10.0)]
    assert _artwork_path(path)[2] == 2, "the arc count is still reported"


def test_the_real_footprint_arc_record_decodes_to_its_endpoint():
    """The same shape is in the fixture, verbatim: footprint ``bb64725a1fd5d4ba``.

    Its ``POLY`` ``e11`` reads ``[28.401, 19.671, "ARC", -90, 34.401, 13.671]``
    on layer 3 (top silk) — the audit's probe is not a synthetic case, it is
    this record.
    """
    source = load_epro2_source(FOC_100)
    raw = None
    for document in source.documents_of_type("FOOTPRINT"):
        if document.uuid != "bb64725a1fd5d4ba":
            continue
        for rtype, rid, path in _raw_artwork_paths(document):
            if rid == "e11":
                raw = (rtype, path)
    assert raw is not None, "the fixture still carries that footprint"
    assert raw[0] == "POLY"
    assert _items(raw[1]) == [28.401, 19.671, "ARC", -90, 34.401, 13.671]

    (template,) = [t for t in footprint_artwork(
        next(d for d in source.documents_of_type("FOOTPRINT") if d.uuid == "bb64725a1fd5d4ba")
    ) if t.id == "e11"]
    assert [(p.x, p.y) for p in template.points] == [(28.401, 19.671), (34.401, 13.671)]
    assert template.arc_count == 1

    # And end to end, through a **placed** footprint: C1 carries another arc
    # polygon (``45007c2a…``), so the same two-vertex reading can be checked
    # against the board transform rather than only in footprint-local space.
    board = build_board_geometry(source)
    placement = board.component("C1")
    (placed_template,) = [t for t in footprint_artwork(
        next(d for d in source.documents_of_type("FOOTPRINT") if d.uuid == placement.footprint)
    ) if t.id == "e11"]
    assert placed_template.arc_count == 1
    shape = next(
        s for s in board.silk_shapes
        if s.id == "e11" and s.component == "C1" and s.layer_kind == "TOP_SILK"
    )
    expected = [placement.transform(p.x, p.y) for p in placed_template.points]
    assert [(round(p.x, 6), round(p.y, 6)) for p in shape.points] == [
        (round(p.x, 6), round(p.y, 6)) for p in expected
    ]
    assert shape.arc_count == 1


def test_no_artwork_vertex_is_an_arc_sweep_angle():
    """The independent oracle that needs no reference decoder.

    A sweep is an angle; the numbers around it are coordinates. So **no decoded
    vertex may equal a number that follows an ``"ARC"`` token** — which is
    exactly what the old reader produced. Checked over every artwork record with
    an arc in every ``.epro2`` fixture: 596 records, 0 violations after the fix
    (the old reader put the sweep in a coordinate on all of them, since it
    consumed the number unconditionally).
    """
    checked = 0
    for path in sorted(FIXTURES.glob("*.epro2")):
        source = load_epro2_source(path)
        for document in source.documents_of_type("FOOTPRINT"):
            for _rtype, rid, raw in _raw_artwork_paths(document):
                sweeps = _sweeps(_items(raw))
                if not sweeps:
                    continue
                checked += 1
                points = _artwork_path(raw)[0]
                offenders = [
                    (p.x, p.y) for p in points if p.x in sweeps or p.y in sweeps
                ]
                assert not offenders, (
                    f"{path.name} artwork {rid} decoded a sweep angle as a "
                    f"coordinate: {offenders} (sweeps {sorted(sweeps)})"
                )
    assert checked >= 500, f"the arc corpus moved: only {checked} records seen"


def test_the_board_s_arc_artwork_is_instantiated():
    """Counted on 毕设FOC 1.0.0: 66 arc-bearing artwork records → 184 silk shapes.

    Before the fix these all existed too — with a wrong vertex each — so what
    this pins is that the corpus is real and large, not the fix itself (the two
    tests above do that).
    """
    source, board = _context(FOC_100)
    records = 0
    for document in source.documents_of_type("FOOTPRINT"):
        for _rtype, _rid, raw in _raw_artwork_paths(document):
            if _sweeps(_items(raw)):
                records += 1
    assert records == 66
    shapes = [s for s in board.silk_shapes if s.arc_count]
    assert len(shapes) == 184
    assert all(len(s.points) == len(s.local_points) for s in shapes)


# ---------------------------------------------------------------------------
# H2 — a slot hole is not a circle
# ---------------------------------------------------------------------------


def test_a_slot_pad_carries_two_dimensions_and_no_diameter():
    """``SLOT`` means two extents; ``hole_diameter`` stops claiming a circle.

    llc's ``CN1`` mounts a connector whose three visible slots read
    86.62 x 47.24 mil locally — the honest description is a rectangle, and
    before 162b the parser published 86.62 as the hole's *diameter* and never
    read 47.24 at all.
    """
    _source, context = _context(LLC)
    slots = [p for p in context.pads if p.hole_type == "SLOT"]
    assert slots, "llc places slot-hole pads"
    for pad in slots:
        assert pad.hole_diameter is None, "a slot has no diameter"
        assert pad.hole_width is not None and pad.hole_height is not None
        assert pad.hole_width >= pad.hole_height, "width is the long axis"
        assert pad.has_hole is True
        assert pad.is_smd is False
    cn1 = [p for p in slots if p.component == "CN1"]
    assert cn1, "measured: CN1 is where llc's slots are"
    assert all(p.hole_width == pytest.approx(86.62, abs=0.02) for p in cn1)
    assert all(p.hole_height == pytest.approx(47.24, abs=0.02) for p in cn1)


def test_a_slot_is_still_a_plated_barrel():
    """The through-hole reading must not have narrowed with ``hole_diameter``.

    A slot pad's barrel is as continuous as a round one's, so it must occupy the
    same copper set as any other barrel on the board — on llc that is the
    physical stackup (``LAYER_PHYS``), not the editor's 32-layer ``LAYER``
    table, and it is the same set a round through-hole pad gets. This is the
    check that would have caught a naive "``hole_diameter`` is None ⇒ SMD"
    reading.
    """
    _source, context = _context(LLC)
    slot_instances = [p for p in context.pads if p.hole_type == "SLOT"]
    assert slot_instances
    barriques = {tuple(p.effective_layer_ids) for p in slot_instances}
    assert len(barriques) == 1, f"every slot is the same barrel: {barriques}"
    (slot_layers,) = barriques
    assert len(slot_layers) > 1, "a barrel spans more than one copper layer"

    round_barrels = {
        tuple(p.effective_layer_ids)
        for p in context.pads
        if p.hole_type == "ROUND" and p.layer_id == MULTI_LAYER_ID
    }
    assert round_barrels == {slot_layers}, (
        "a slot barrel and a round barrel occupy the same copper"
    )


def test_a_round_hole_keeps_exactly_the_diameter_it_always_had():
    """Narrowing, not deprecation: every non-slot hole is unchanged.

    Measured over the fixture set's FOOTPRINT documents: 1164 ``PAD`` records
    declare ``holeType`` ``ROUND`` — 101 of them with ``width == height == 0``
    (the editor's "no hole" placeholder, read as SMD by the old ``... or None``
    and by this reader alike), 1054 with a positive diameter, and 9 whose two
    extents **differ** (USB shield / mounting holes: llc's ``e1`` is
    78.7402 x 59.0551, 毕设FOC 1.0.0 has four at 126 x 118.1102). The file still
    calls those nine ``ROUND``, so the diameter stays the value it always was
    and the two extents are published beside it.
    """
    _source, context = _context(LLC)
    rounds = [p for p in context.pads if p.hole_type == "ROUND"]
    assert rounds
    for pad in rounds:
        assert pad.hole_diameter == pad.hole_width
        assert pad.has_hole and not pad.is_smd
    square = [p for p in rounds if p.hole_width == p.hole_height]
    assert square and all(p.hole_diameter == p.hole_height for p in square)

    # The record-level reading of the one asymmetric ROUND pad in llc's library.
    source = load_epro2_source(LLC)
    asymmetric = [
        template
        for document in source.documents_of_type("FOOTPRINT")
        for template in pad_templates(document)
        if template.hole_type == "ROUND"
        and template.hole_height is not None
        and template.hole_width != template.hole_height
    ]
    assert len(asymmetric) == 1, "llc carries exactly one such pad"
    (template,) = asymmetric
    assert (template.hole_width, template.hole_height) == (78.7402, 59.0551)
    assert template.hole_diameter == 78.7402, "the file says ROUND; width is the diameter"
    assert template.has_hole


def test_the_fixture_set_carries_exactly_141_slot_pad_records():
    """161's headline number, re-measured at the record level (not per placement).

    Through the parser's own reader (``pad_templates``): **141** ``PAD`` records
    across every fixture's FOOTPRINT documents declare ``SLOT``, and 1063
    declare ``ROUND`` with a positive diameter. The 101 ``ROUND`` records with
    ``width == height == 0`` are counted in the previous test's docstring and
    are not holes at all, which is why they are absent here.
    """
    slots = rounds = placeholders = 0
    for path in sorted(FIXTURES.glob("*.epro2")):
        source = load_epro2_source(path)
        for document in source.documents_of_type("FOOTPRINT"):
            for record in document.records:
                if record.type != "PAD" or not isinstance(record.body, dict):
                    continue
                hole = record.body.get("hole")
                if not isinstance(hole, dict) or str(hole.get("holeType")) != "ROUND":
                    continue
                if not hole.get("width"):
                    placeholders += 1
            for template in pad_templates(document):
                if template.hole_type == "SLOT":
                    slots += 1
                elif template.hole_type == "ROUND":
                    rounds += 1
    assert (slots, rounds, placeholders) == (141, 1063, 101)


# ---------------------------------------------------------------------------
# H3 — legend goes on the face the part is mounted on
# ---------------------------------------------------------------------------


def test_a_bottom_placement_s_silk_is_bottom_silk():
    """127b's correction for pads, applied to the footprint's legend (llc).

    12 of llc's 47 placements sit on layer 2, and their footprint silk (layer 3
    in the library) prints on the **bottom** silkscreen. The library's own
    spelling stays auditable in ``declared_layer_kind``.
    """
    _source, context = _context(LLC)
    bottom_ids = {c.id for c in context.placements if c.layer_id == 2}
    top_ids = {c.id for c in context.placements if c.layer_id == 1}
    assert len(bottom_ids) == 12 and len(top_ids) == 35

    bottom_silk = [s for s in context.silk_shapes if s.component_id in bottom_ids and s.is_silk]
    top_silk = [s for s in context.silk_shapes if s.component_id in top_ids and s.is_silk]
    assert len(bottom_silk) == 64
    assert len(top_silk) == 157
    assert {s.layer_kind for s in bottom_silk} == {"BOT_SILK"}
    assert {s.declared_layer_kind for s in bottom_silk} == {"TOP_SILK"}
    assert {s.effective_layer_id for s in bottom_silk} == {4}
    assert {s.layer_kind for s in top_silk} == {"TOP_SILK"}
    assert {s.declared_layer_kind for s in top_silk} == {"TOP_SILK"}


def test_body_and_marking_carry_the_placement_face():
    """The layers whose id cannot express a face still get one (from the part).

    ``COMPONENT_SHAPE`` (48) / ``COMPONENT_MARKING`` (49) / ``PIN_SOLDERING``
    (50) / ``PIN_FLOATING`` (51) have no ``BOT_*`` counterpart in the layer
    table of any fixture, so their **kind** must not be renamed — the silk
    rule's body filter compares it verbatim — and their **face** comes from the
    placement. That is the same number the rule derives from
    ``placement.layer_id`` on its own, which is the point: one fact, one value.
    """
    _source, context = _context(LLC)
    by_id = {c.id: c for c in context.placements}
    checked = 0
    for shape in context.silk_shapes:
        if shape.declared_layer_kind not in (
            "COMPONENT_SHAPE", "COMPONENT_MARKING", "PIN_SOLDERING", "PIN_FLOATING"
        ):
            continue
        placement = by_id[shape.component_id]
        assert shape.layer_kind == shape.declared_layer_kind, "no such layer to rename to"
        assert shape.effective_layer_id == shape.layer_id
        assert shape.face == placement.layer_id, (
            f"{shape.component} {shape.id}: face {shape.face} vs placement "
            f"layer {placement.layer_id}"
        )
        checked += 1
    assert checked > 100, f"expected the per-placement artwork corpus, saw {checked}"


def test_board_level_annotations_get_no_face():
    """A ``DOCUMENT`` layer primitive is not printed on either face.

    Measured: llc carries 62 such primitives (design notes drawn on the
    document layer), 级联多电平-主拓扑 95. Claiming a face for them would be a
    guess about the document, not a reading of it.
    """
    total = 0
    for path in (LLC, CASCADE_MAIN, FOC_100):
        _source, context = _context(path)
        annotations = [s for s in context.silk_shapes if s.declared_layer_kind == "DOCUMENT"]
        assert annotations, f"{path.name} carries document-layer artwork"
        assert {s.face for s in annotations} == {None}
        total += len(annotations)
    assert total == 62 + 95 + 67


def test_the_footprint_s_print_mark_flips_with_the_part():
    """The same correction reaches ``silk_texts`` (the ``+`` / ``-`` marks).

    A footprint's printed text is instantiated per placement like its shapes, so
    a bottom part's ``+`` is printed on the bottom silkscreen — and the rule that
    asks "is this mark on the same face as the designator" reads
    ``text.layer_kind``.

    **No fixture can show this on a board**: on every ``.epro2`` here, the
    footprints that carry ``STRING`` marks (llc's 6, 毕设FOC 1.0.0's 9, DCDC's 8)
    are library footprints with **no placement** (such a mark is instantiated
    only when its footprint is placed — verified: those documents' uuids are not
    among the board's ``COMPONENT.Footprint`` values). So the reading is pinned
    against :func:`build_silk` directly, with the same layer table the real
    documents carry.
    """
    from boardwise.core.geometry import (
        ComponentPlacement,
        LayerInfo,
        ParseStats,
    )
    from boardwise.parsers.epru import ArtworkTemplate, build_silk

    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        3: LayerInfo(3, "Top Silkscreen Layer", "TOP_SILK"),
        4: LayerInfo(4, "Bottom Silkscreen Layer", "BOT_SILK"),
    }
    template = ArtworkTemplate(id="s1", kind="text", layer_id=3, text="+")
    bottom = ComponentPlacement(id="c1", designator="D1", footprint="FP", layer_id=2)
    top = ComponentPlacement(id="c2", designator="D2", footprint="FP", layer_id=1)

    _shapes, texts = build_silk([bottom], {"FP": [template]}, layers, ParseStats())
    assert len(texts) == 1
    assert texts[0].layer_kind == "BOT_SILK"
    assert texts[0].declared_layer_kind == "TOP_SILK"
    assert texts[0].layer_id == 3, "the library's own id is kept"

    _shapes, texts = build_silk([top], {"FP": [template]}, layers, ParseStats())
    assert texts[0].layer_kind == "TOP_SILK"
    assert texts[0].declared_layer_kind == "TOP_SILK"


def test_a_document_without_a_counterpart_layer_keeps_the_kind_and_the_face():
    """The rename happens only when the document defines the other layer.

    A footprint drawn on a top layer of a file that defines no bottom silk keeps
    its kind — there is no id to name it with — and still reports the physical
    ``face``, so a reader is never told the part is on the wrong side.
    """
    from boardwise.core.geometry import ComponentPlacement, LayerInfo, ParseStats
    from boardwise.parsers.epru import ArtworkTemplate, build_silk

    layers = {
        1: LayerInfo(1, "Top Layer", "TOP"),
        2: LayerInfo(2, "Bottom Layer", "BOTTOM"),
        3: LayerInfo(3, "Top Silkscreen Layer", "TOP_SILK"),
    }
    template = ArtworkTemplate(id="p1", kind="poly", layer_id=3, points=[Point(0.0, 0.0)])
    bottom = ComponentPlacement(id="c1", designator="D1", footprint="FP", layer_id=2)
    shapes, _texts = build_silk([bottom], {"FP": [template]}, layers, ParseStats())
    assert len(shapes) == 1
    assert shapes[0].layer_kind == "TOP_SILK"
    assert shapes[0].effective_layer_id == 3
    assert shapes[0].face == 2


# ---------------------------------------------------------------------------
# H4 — a pour is copper
# ---------------------------------------------------------------------------


def test_only_copper_polygons_are_pours():
    """llc: 137 polygons, of which **32** are copper and 105 are mask openings.

    The 105 are ``POLY`` records on layer 6 (``BOT_SOLDER_MASK``) — a mask
    opening, not copper. They used to be filed with the pours, which is what
    made the summary claim 137.
    """
    _source, context = _context(LLC)
    assert len(context.pours) == 32
    assert len(context.non_copper_shapes) == 105
    assert {s.layer_id for s in context.non_copper_shapes} == {6}
    assert {s.kind for s in context.non_copper_shapes} == {"poly"}
    assert {s.net for s in context.non_copper_shapes} == {None}
    # Nothing non-copper is left in the pours.
    kinds = {(s.layer_id, context.layers[s.layer_id].layer_type) for s in context.pours
             if s.layer_id is not None}
    assert kinds == {(1, "TOP"), (2, "BOTTOM")}
    orphan = [s for s in context.pours if s.layer_id is None]
    assert len(orphan) == 7, "a POURED whose parent is gone keeps its unknown layer"


def test_a_multi_layer_fill_is_copper():
    """Layer 12 (``MULTI``) is copper on every layer, not artwork.

    级联多电平-主拓扑 carries 3 such ``FILL`` records and 56 mask ``POLY``
    records; only the mask ones leave the pours. Reading the layer's own type
    (``MULTI``) rather than the id keeps a renumbered document working.
    """
    _source, context = _context(CASCADE_MAIN)
    assert len(context.non_copper_shapes) == 56
    multi = [s for s in context.pours if s.layer_id == MULTI_LAYER_ID]
    assert len(multi) == 3
    assert {context.layers[MULTI_LAYER_ID].layer_type for _ in multi} == {"MULTI"}


def test_the_summary_counts_copper_pours():
    """``summary()`` is where the 137 came from, so it is where the fix shows."""
    _source, board = _board(LLC)
    summary = board.summary()
    assert summary["pours"] == 32
    assert summary["non_copper_shapes"] == 105


def test_the_copper_consumers_do_not_move():
    """The consumers that already filtered by layer see **no** change.

    Every non-copper polygon on these fixtures has **no net**, so the net index
    (and ``pours_for_net``'s counts in the FOC rules) cannot move; and
    ``region_copper`` files an element only under the copper layers it was asked
    about, so a mask opening was invisible to it before the split as well
    (measured: 786 inventory rows and 7 unclassified entries either way).
    """
    source, board = _board(LLC)
    assert len(board.nets) == 25
    assert all(p.net is None for p in board.non_copper_shapes)
    assert {p.net for p in board.pours if p.net} <= set(board.nets)
    from boardwise.core.measure import read_stackup

    assert read_stackup(board).used_copper_layer_ids == [1, 2]


# ---------------------------------------------------------------------------
# H5 — no false "format drift"
# ---------------------------------------------------------------------------


def test_pour_and_region_are_not_reported_as_drift():
    """``POUR`` (and ``REGION``) were reported as unknown while being consumed.

    高速电机控制器 is the fixture that carries both (46 ``POUR`` records and 6
    ``REGION`` records across its documents) and it reported them in
    ``unknown_types`` — a drift signal that fires on a record the parser decodes
    is worse than no signal. ``POUR`` is also *consumed*, so it cannot appear in
    ``unconsumed_types`` either.
    """
    source, context = _context(SPEED)
    assert source.stats.records_by_type.get("POUR", 0) > 0
    assert source.stats.records_by_type.get("REGION", 0) == 6
    for rtype in ("POUR", "REGION"):
        assert rtype not in source.stats.unknown_types
        assert rtype not in source.stats.unconsumed_types
    assert context.pours, "POUR still reaches the pours"


# ---------------------------------------------------------------------------
# H6 — REGION records are parsed and exposed, and nothing consumes them
# ---------------------------------------------------------------------------


def test_region_records_become_prohibit_regions():
    """The six copper-prohibition regions of 高速电机控制器, field by field.

    Five are circles (centre + radius, up to 148.83 mil) and one is a
    rotated-rectangle form; all sit on copper layer 1 or 2 and declare
    ``prohibitType: ["COPPER"]``.
    """
    _source, context = _context(SPEED)
    regions = context.prohibit_regions
    assert len(regions) == 6
    assert {r.region_type for r in regions} == {"PROHIBIT"}
    assert {r.name for r in regions} == {"PROHIBIT"}
    assert {tuple(r.prohibit_types) for r in regions} == {("COPPER",)}
    assert {r.layer_id for r in regions} == {1, 2}
    circles = [r for r in regions if r.radius is not None]
    rectangles = [r for r in regions if r.radius is None]
    assert len(circles) == 5 and len(rectangles) == 1
    assert all(len(r.points) == 1 for r in circles), "a circle keeps its centre"
    assert all(len(r.points) == 4 for r in rectangles), "a rectangle keeps four corners"
    assert all(r.bbox is not None for r in regions)
    biggest = max(r.radius for r in circles)
    assert biggest == pytest.approx(148.8307)


def test_a_region_is_exposed_on_the_board_and_consumed_by_nothing():
    """``BoardGeometry.prohibit_regions`` mirrors the context, and it is inert.

    Inert is the contract: 162b adds the **reading** of these records and no
    rule may draw a conclusion from them yet. The regression guard is that they
    arrive in a list of their own — not welded onto the pours, the legend or the
    net index — so a consumer that starts using them has to ask for them by
    name.
    """
    source, board = _board(SPEED)
    assert len(board.prohibit_regions) == 6
    assert len(board.prohibit_regions) == len(source.pcb_context().prohibit_regions)
    summary = board.summary()
    assert summary["prohibit_regions"] == 6
    assert summary["pours"] == len(board.pours)
    assert summary["non_copper_shapes"] == len(board.non_copper_shapes)

    region_ids = {r.id for r in board.prohibit_regions}
    assert region_ids.isdisjoint({p.id for p in board.pours})
    assert region_ids.isdisjoint({s.id for s in board.silk_shapes})
    assert region_ids.isdisjoint(set(board.nets))
    assert all(r.prohibit_types == ["COPPER"] for r in board.prohibit_regions)
    assert all(r.bbox is not None for r in board.prohibit_regions)
