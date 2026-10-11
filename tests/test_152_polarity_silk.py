"""Tests for task 152: 极性与方向 + 丝印（E 阶段第二棒，两个规则族）。

两个规则共用同一份**新数据**——``BoardGeometry.silk_shapes`` / ``silk_texts``
（152 给几何模型加的字段，由 ``parsers/epru.py`` 从 FOOTPRINT 文档的图元与 PCB
文档的 ``ATTR key=Designator`` / ``STRING`` 记录实例化）。所以本文件按层钉：

* **解析层**——位号记录怎么读（角度约化、``valueVisible``、``parentId`` 归属、
  孤儿记录），封装图元怎么实例化（局部坐标 + 板坐标、CIRCLE 的半径、层的判读）；
* **词汇与几何层**——极性判读词表（成对才认）、双向器件、图元级换脚配对、
  文字盒与焊盘的最小间隙（分离轴）；
* **结构闸**——两条规则在 ``BUILTIN_PCB_RULES`` 里的位置与 ``source`` 的
  house rule（待裁）口径；
* **合成态**——两个族的每个 finding 类别各手搭一例（不依赖夹具）；
* **三块验收板 + llc 的实测锚点**——本批被验收时的那些数。

实测锚点（2026-10-11 量的，证据在 ``outputs/152/recon.txt``）见各测试的注释。
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    PadGeometry,
    SilkShape,
    SilkText,
)
from boardwise.core.model import Component, DesignModel, Pin
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.parsers.epru import (
    PCB_DOC_TYPE,
    load_epro2_source,
    extract_board,
    footprint_artwork,
    layer_kinds,
    silk_texts_of,
)
from boardwise.parsers.schematic import build_project_model
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.polarity import (
    MARK_SNAP_MIL,
    POLARITY_PAIRS,
    PolarityOrientation,
    polarity_of_component,
    polarity_of_library,
    resolve_polarity,
    unpaired_elements,
)
from boardwise.rules.pcb.silk import (
    ADVANCE_BAND,
    NARROW_ADVANCE,
    SilkDesignator,
    pad_polygon,
    polygon_gap,
    text_box,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"

POLARITY_ID = "pcb-polarity-orientation"
SILK_ID = "pcb-silk-designator"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _run(path: Path, rules=None) -> tuple[list, dict]:
    model = build_project_model(path)
    return run_pcb_review(path, model=model, rules=rules or [PolarityOrientation(), SilkDesignator()])


def _rows(section: dict, findings: list, title: str) -> list:
    for entry in section["boards"]:
        if entry["title"] == title:
            return [findings[index] for index in entry["findings"]]
    raise AssertionError(f"no board {title!r} in {[b['title'] for b in section['boards']]}")


def _silk_text(
    component: str,
    text: str,
    x: float,
    y: float,
    *,
    angle: float = 0.0,
    layer_kind: str = "TOP_SILK",
    layer_id: int = 3,
    font_size: float = 45.0,
    visible: bool = True,
    source: str = "designator",
    local_x: float | None = None,
    local_y: float | None = None,
) -> SilkText:
    return SilkText(
        component=component,
        component_id=f"c-{component}",
        text=text,
        source=source,
        x=x,
        y=y,
        local_x=x if local_x is None else local_x,
        local_y=y if local_y is None else local_y,
        angle=angle,
        stored_angle=angle,
        layer_id=layer_id,
        layer_kind=layer_kind,
        font_size=font_size,
        stroke_width=6.0,
        origin="LEFT_BOTTOM",
        visible=visible,
    )


def _silk_shape(
    component: str,
    points: list[tuple[float, float]],
    *,
    layer_kind: str = "TOP_SILK",
    layer_id: int = 3,
    kind: str = "poly",
    radius: float | None = None,
    local: list[tuple[float, float]] | None = None,
) -> SilkShape:
    from boardwise.core.geometry import Point

    return SilkShape(
        id=f"{component}-{kind}",
        component=component,
        component_id=f"c-{component}",
        kind=kind,
        layer_id=layer_id,
        layer_kind=layer_kind,
        points=[Point(*p) for p in points],
        local_points=[Point(*p) for p in (local if local is not None else points)],
        radius=radius,
    )


def _pad(component: str, pin: str, *, local: tuple[float, float], width: float = 30.0,
         height: float = 30.0, shape: str = "RECT") -> PadGeometry:
    """A pad placed at ``local`` with no rotation (board == local when angle is 0)."""
    return PadGeometry(
        id=f"{component}.{pin}", component=component, component_id=f"c-{component}",
        pin_number=pin, net="", layer_id=1, effective_layer_ids=[1],
        x=local[0], y=local[1], local_x=local[0], local_y=local[1],
        width=width, height=height, shape=shape, angle=0.0,
    )


def _ctx(board: BoardGeometry, model=None, pcb_model=None) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title=board.name or "SYNTH", model=model, pcb_model=pcb_model
    )


def _sch(parts: dict[str, tuple[list[tuple[str, str]], dict]]) -> DesignModel:
    """Synthetic schematic: designator → (``[(pin number, pin name)]``, library props).

    The props dict is the same mapping ``ctx.pcb_model`` carries (the DEVICE
    document's attributes verbatim), so one helper builds both sides.
    """
    return DesignModel(
        components={
            designator: Component(
                uid=f"s-{designator}", designator=designator,
                pins=[Pin(number=number, name=name, net=None) for number, name in pins],
            )
            for designator, (pins, _props) in parts.items()
        }
    )


def _pcb_side(parts: dict[str, tuple[list[tuple[str, str]], dict]]) -> DesignModel:
    return DesignModel(
        components={
            designator: Component(
                uid=f"u-{designator}", designator=designator, props=dict(props),
                pins=[
                    Pin(number=number, name=name, net=None) for number, name in _pins
                ],
            )
            for designator, (_pins, props) in parts.items()
        }
    )


# ---------------------------------------------------------------------------
# 1. the parsing layer — how a designator record and footprint artwork are read
# ---------------------------------------------------------------------------


def test_the_designator_text_of_a_real_board_carries_its_own_geometry():
    """A designator is an ``ATTR key=Designator`` record with its own placement.

    Measured on 毕设FOC 1.0.0 ``PCB1``: 122 designator records for 122
    placements, every one on layer 3 (``TOP_SILK``), ``fontSize`` 45,
    ``origin`` ``LEFT_BOTTOM``, 91 of them ``valueVisible``. ``C1``'s record
    stores ``angle`` 810 and reads back as 90° — the raw value accumulates whole
    turns, and the reduction is what makes it an orientation.
    """
    source = load_epro2_source(FOC_100)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())

    designators = [t for t in board.silk_texts if t.source == "designator"]
    assert len(designators) == 122
    assert {t.layer_kind for t in designators} == {"TOP_SILK"}
    assert {t.font_size for t in designators} == {45.0}
    assert {t.origin for t in designators} == {"LEFT_BOTTOM"}
    assert len([t for t in designators if t.visible]) == 91
    assert len([t for t in designators if not t.visible]) == 31

    c1 = board.designator_text("C1")
    assert c1 is not None
    assert (c1.text, c1.stored_angle, c1.angle) == ("C1", 810.0, 90.0)
    assert (c1.x, c1.y) == (4455.0, -1165.0)


def test_the_board_carries_free_text_next_to_the_programming_header():
    """``STRING`` records in the PCB document are the designer's own labels.

    Measured: 毕设FOC 1.0.0 ``PCB1`` has three — ``CLK``/``DIO``/``GND`` at
    ``fontSize`` 40, rotated -88.21° to the connector's axis — and they are
    ``source="board"`` (no designator), which is what keeps them out of the
    silk rule's designator口径.
    """
    source = load_epro2_source(FOC_100)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())
    free = [t for t in board.silk_texts if t.source == "board"]
    assert sorted(t.text for t in free) == ["CLK", "DIO", "GND"]
    assert all(t.component is None and t.font_size == 40.0 for t in free)
    # The angle is stored as ~-88.21 degrees and is reduced mod 360 for reading.
    assert free[0].angle == pytest.approx(271.79, abs=0.01)


def test_footprint_artwork_is_instantiated_in_both_frames():
    """A footprint's silk primitive lands on the board **and** keeps its local frame.

    毕设FOC 1.0.0 ``C1`` sits at (4510, -1145) with angle 0, so the two frames
    coincide; the assertion that matters is that both are populated and that the
    layer id is read through the document's own ``LAYER`` table (id 3 →
    ``TOP_SILK``, 48 → ``COMPONENT_SHAPE``, 49 → ``COMPONENT_MARKING``). The
    marking-layer dot is present and is **not** silkscreen — that distinction is
    what stops the polarity rule treating every footprint's pin-1 dot as a
    printed direction mark.
    """
    source = load_epro2_source(FOC_100)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())

    shapes = board.silk_shapes_for("C1")
    assert shapes, "C1's footprint carries artwork"
    assert all(s.points and s.local_points for s in shapes)
    kinds = {s.layer_kind for s in shapes}
    assert {"TOP_SILK", "COMPONENT_SHAPE", "COMPONENT_MARKING"} <= kinds

    dot = [s for s in shapes if s.layer_kind == "COMPONENT_MARKING"]
    assert len(dot) == 1, "EasyEDA draws exactly one pin-1 mark"
    assert dot[0].radius == pytest.approx(2.361, abs=0.001)
    # The dot is a single centre point plus a radius, not a degenerate polygon.
    assert len(dot[0].points) == 1
    assert len(board.silk_shapes) > 1000, "every placement contributes its artwork"


def test_a_footprint_printed_mark_is_read_as_text_with_its_own_anchor():
    """A ``STRING`` inside a FOOTPRINT document is a printed mark (152).

    The library footprints that carry them on this fixture are unused, so this
    reads the document directly: ``CONN-TH_XT30UPB-M`` prints ``-`` at local
    (-245, -15) and ``+`` at (210, -20), both ``fontSize`` 39.4 — the footprint's
    own declaration of which side is which, and the only thing in the file that
    says "this end is positive" without any convention being applied.
    """
    source = load_epro2_source(FOC_100)
    marks = {}
    for document in source.documents_of_type("FOOTPRINT"):
        for template in footprint_artwork(document):
            if template.kind == "text":
                marks.setdefault(document.uuid, []).append(template)
    carrying = {uuid: sorted(t.text for t in templates) for uuid, templates in marks.items()}
    assert sorted(tuple(sorted(v)) for v in carrying.values()) == [
        ("*", "*"), ("+", "-"), ("+", "-"), ("1", "2", "3"),
    ]
    flat = [(t.text, t.x, t.y, t.font_size) for templates in marks.values() for t in templates]
    assert ("-", -245.0, -15.0, 39.4) in flat
    assert ("+", 210.0, -20.0, 39.4) in flat


def test_an_unparented_designator_record_is_kept_and_named_as_such():
    """ROBOT's ``PCB1`` has 50 designator records for 49 placements.

    The extra one is stamped ``designator-unparented`` rather than dropped: a
    stray record prints a designator with no part behind it, and the silk rule
    reports it. (Measured: it is a **stale duplicate of ``R6``** — the board
    carries two ``R6`` records, one attached to the real component and
    ``valueVisible: true``, one attached to an element id that is not a
    COMPONENT at all and ``valueVisible: false``.)
    """
    source = load_epro2_source(ROBOT)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())
    orphans = [t for t in board.silk_texts if t.source == "designator-unparented"]
    assert len(orphans) == 1
    assert orphans[0].text == "R6"
    assert orphans[0].component is None
    # R6 itself still has its own (visible) record: the orphan does not replace
    # it, which is exactly why dropping it would have been wrong in the other
    # direction — the board prints one R6, the file holds two.
    real = board.designator_text("R6")
    assert real is not None and real.visible is True and real.x == 345.0
    assert len([t for t in board.silk_texts if t.source == "designator"]) == 49


def test_the_silk_reader_omits_nothing_the_copper_walk_needs():
    """``silk_texts_of`` is a second read of the same records, not a rewrite.

    The designator records are also read by the copper walk (as ``ATTR``s that
    name components), so this pins that the legend pass and the placement pass
    agree about what a component is: the same ``parentId`` → designator join,
    the same count.
    """
    source = load_epro2_source(FOC_100)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())
    texts = silk_texts_of(document, board.components, layer_kinds(board.layers))
    designators = [t for t in texts if t.source == "designator"]
    assert {t.component for t in designators} == {
        c.designator for c in board.components
    }


# ---------------------------------------------------------------------------
# 2. vocabulary and geometry
# ---------------------------------------------------------------------------


def test_polarity_is_read_from_paired_symbol_pin_names_only():
    """Three pairings are recognised, and a lone letter is not one of them."""
    def component(pins):
        return Component(
            uid="u", designator="X",
            pins=[Pin(number=n, name=name, net=None) for n, name in pins],
        )

    led = polarity_of_component(component([("1", "+"), ("2", "-")]))
    assert (led.kind, led.plus_pin, led.minus_pin) == ("polarized", "1", "2")
    diode = polarity_of_component(component([("1", "K"), ("2", "A")]))
    assert (diode.kind, diode.plus_pin, diode.minus_pin) == ("diode", "2", "1")
    led_ca = polarity_of_component(component([("1", "C"), ("2", "A")]))
    assert (led_ca.kind, led_ca.plus_pin, led_ca.minus_pin) == ("led", "2", "1")
    # A lone "A" is a letter, not an anode: USB-C's A5/B1A12 pads and the CAN
    # transceiver's "D"/"R" pins must not read as polarised.
    assert polarity_of_component(component([("A5", "CC1"), ("A4B9", "VBUS")])) is None
    assert polarity_of_component(component([("1", "D"), ("2", "R")])) is None
    assert polarity_of_component(component([("1", "1"), ("2", "2")])) is None
    # A longer spelling normalises to the short one.
    assert polarity_of_component(component([("1", "V+"), ("2", "V-")])).plus_pin == "1"
    # The table is exactly these three pairings: a fourth one added without a
    # measured part behind it would be a guess, not a reading.
    assert {frozenset(words) for words, _p, _m, _k in POLARITY_PAIRS} == {
        frozenset(("+", "-")), frozenset(("K", "A")), frozenset(("C", "A")),
    }


def test_the_library_type_word_only_says_that_a_part_has_polarity():
    """``Type``/``Polarity`` give a polarity **claim**, never a pin assignment."""
    assert polarity_of_library({}) is None
    assert polarity_of_library({"Type": "厚膜电阻"}) is None
    polymer = polarity_of_library({"Type": "聚合物"})
    assert polymer is not None and polymer.plus_pin is None and polymer.orientation_sensitive
    bidirectional = polarity_of_library({"Type": "TVS", "Polarity": "双向"})
    assert bidirectional.orientation_sensitive is False


def test_a_bidirectional_device_outranks_its_own_symbol_pin_names():
    """The measured false alarm this rule exists to avoid.

    ``D1``/``D2`` of the two 毕设FOC boards are SMCJ TVS parts whose symbol names
    the pins ``K``/``A`` (as if unidirectional) while the library says
    ``Polarity: 双向``. Reading the symbol alone would file 「极性器件没有方向
    标记」 against a part that has no wrong way round.
    """
    schematic = Component(
        uid="u", designator="D1",
        pins=[Pin(number="1", name="K", net=None), Pin(number="2", name="A", net=None)],
    )
    resolved = resolve_polarity(schematic, {"Type": "TVS", "Polarity": "双向"})
    assert resolved.orientation_sensitive is False
    assert "双向" in resolved.declaration
    # The pin names are still kept as evidence, so a reader sees both facts.
    assert (resolved.plus_pin, resolved.minus_pin) == ("2", "1")

    plain = resolve_polarity(schematic, {"Type": "TVS"})
    assert plain.orientation_sensitive is True


def test_the_pin_swap_test_compares_elements_not_vertices():
    """Why the criterion is element-level: the measured coincidence it dodges.

    On ``C0603`` the pin-1 dot sits at ``(-31.5, -15.75)`` and the silk corner
    at ``(-31.496, -15.748)`` — 0.004 mil apart. A point-set comparison would
    pair them and erase the mark; an element-level one does not, because the dot
    is a ``COMPONENT_MARKING`` circle and the corner is a ``TOP_SILK`` line.
    """
    key_dot = ("COMPONENT_MARKING", "fill")
    key_silk = ("TOP_SILK", "poly")
    elements = [
        (key_silk, -31.496, -15.748, "silk corner", None),
        (key_dot, -31.5, -15.75, "pin-1 dot", None),
    ]
    unpaired = unpaired_elements(elements, (0.0, 0.0))
    assert [entry[3] for entry in unpaired] == ["silk corner", "pin-1 dot"]

    # Two elements that really are each other's 180° image pair up and vanish.
    paired = [
        (key_silk, -40.0, 10.0, "left", None),
        (key_silk, 40.0, -10.0, "right", None),
    ]
    assert unpaired_elements(paired, (0.0, 0.0)) == []
    # The tolerance is the file's own round-off scale, and it is tight on
    # purpose: a sloppily drawn symmetric footprint reads as "has a mark" (a
    # missed defect) rather than the other way round (a false alarm).
    assert MARK_SNAP_MIL == 0.05


def test_the_axis_direction_needs_two_distinct_pads():
    """A direction is only reported when two pads give one."""
    from boardwise.rules.pcb.polarity import axis_direction

    pads = [_pad("X", "1", local=(-40.0, 0.0)), _pad("X", "2", local=(40.0, 0.0))]
    assert axis_direction(pads, None) == pytest.approx((1.0, 0.0))
    assert axis_direction([pads[0]], None) is None
    assert axis_direction([], None) is None


def test_a_text_box_grows_with_the_glyph_model_and_the_character_count():
    """The box is a model, so its width is a parameter — and it says so."""
    text = _silk_text("C1", "C1", 0.0, 0.0, font_size=45.0)
    narrow = text_box(text, ADVANCE_BAND[0])
    wide = text_box(text, ADVANCE_BAND[-1])
    widths = [max(p.x for p in box) - min(p.x for p in box) for box in (narrow, wide)]
    assert widths[0] == pytest.approx(2 * 0.4 * 45.0)
    assert widths[1] == pytest.approx(2 * 0.8 * 45.0)
    # The box rises from the anchor by the font size (origin LEFT_BOTTOM).
    assert min(p.y for p in narrow) == pytest.approx(0.0)
    assert max(p.y for p in narrow) == pytest.approx(45.0)
    assert ADVANCE_BAND[1] == 0.6 and NARROW_ADVANCE == 0.4


def test_polygon_gap_is_exact_for_rotated_rectangles_and_circles():
    """The gap primitive the overlap check rests on, in three shapes."""
    from boardwise.core.geometry import Point

    left = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]
    right = [(10.0, -10.0), (30.0, -10.0), (30.0, 10.0), (10.0, 10.0)]
    assert polygon_gap(left, right) == pytest.approx(0.0)
    shifted = [(15.0, -10.0), (35.0, -10.0), (35.0, 10.0), (15.0, 10.0)]
    assert polygon_gap(left, shifted) == pytest.approx(5.0)
    # A circle is (kind, cx, cy, r) — and an inscribed-circle reading of an
    # elliptical pad is what keeps the check from over-reporting.
    assert polygon_gap(("circle", 15.0, 0.0, 5.0), left) == pytest.approx(0.0)
    assert polygon_gap(("circle", 20.0, 0.0, 5.0), left) == pytest.approx(5.0)
    assert polygon_gap(("circle", 0.0, 0.0, 2.0), left) == pytest.approx(-12.0)

    pad = PadGeometry(id="p", component="X", pin_number="1", x=0.0, y=0.0,
                      width=20.0, height=20.0, shape="ELLIPSE", angle=0.0)
    assert pad_polygon(pad) == ("circle", 0.0, 0.0, 10.0)


# ---------------------------------------------------------------------------
# 3. structure gates
# ---------------------------------------------------------------------------


def test_both_rules_are_registered_at_the_declared_position():
    """The list is the truth (126a): a rule that is not listed does not run.

    152 put its two rules immediately after 151's ``pcb-footprint-consistency``
    (器件检查 ①封装一致 → ②极性/丝印), and **153 appended
    ``pcb-derating-package`` after them** (③降额的物理层) — so the device block
    is four deep and its last member is no longer ``pcb-silk-designator``: the
    geometry sweep starts two positions further along than it did in 152.
    """
    ids = [rule.id for rule in BUILTIN_PCB_RULES]
    assert ids.index(POLARITY_ID) == ids.index("pcb-footprint-consistency") + 1
    assert ids.index(SILK_ID) == ids.index(POLARITY_ID) + 1
    assert ids.index("pcb-derating-package") == ids.index(SILK_ID) + 1
    assert ids.index("pcb-component-spacing") == ids.index(SILK_ID) + 2

    rules = {rule.id: rule for rule in BUILTIN_PCB_RULES}
    for rule_id in (POLARITY_ID, SILK_ID):
        rule = rules[rule_id]
        assert rule.level == "L1-pcb-geometry"
        # 钉 7: a house rule must say it is 待裁 and where its numbers came from.
        assert "house rule" in rule.source and "待裁" in rule.source
        assert "岳" in rule.source


def test_the_two_rules_read_the_new_geometry_fields_without_touching_context():
    """152 adds fields to ``BoardGeometry``, not to ``PcbReviewContext``.

    That is deliberate: the silk shapes are *geometry* (a second instantiated
    population beside ``pads``) and the context is what a rule is handed, so
    nothing about the runner's contract had to change for this batch.
    """
    board = BoardGeometry(source="synthetic")
    assert board.silk_shapes == [] and board.silk_texts == []
    fields = {f.name for f in dataclasses.fields(BoardGeometry)}
    assert {"silk_shapes", "silk_texts"} <= fields
    from boardwise.rules.pcb.base import PcbReviewContext as Ctx

    assert {f.name for f in dataclasses.fields(Ctx)} == {
        "board", "board_title", "model", "intent", "module_of", "pcb_model", "board_uuid",
    }
    assert board.silk_shapes_for("C1") == []
    assert board.designator_text("C1") is None
    # ``summary()`` counts them, so a reader of the JSON sees the new population.
    assert board.summary()["silk_shapes"] == 0 and board.summary()["silk_texts"] == 0


def test_a_pad_only_board_still_parses_without_the_artwork_table():
    """The artwork table is optional, so every pre-152 caller keeps working."""
    source = load_epro2_source(FOC_100)
    document = [d for d in source.documents if d.doc_type == PCB_DOC_TYPE][0]
    board = extract_board(document, source.footprints(), source.stats)
    assert board.pads, "copper still parses"
    assert board.silk_shapes == [], "no artwork table → no artwork, stated not guessed"
    assert board.silk_texts, "the board's own designator records need no footprint"


# ---------------------------------------------------------------------------
# 4. synthetic states — 极性族
# ---------------------------------------------------------------------------


#: A footprint's silkscreen as real footprints draw it: **separate primitives**,
#: not one polygon. The shape matters, because the direction-mark test compares
#: elements — a drawing collapsed into a single closed polygon has only one
#: centroid to compare and would read as "no mark" whatever it looks like.
#: ``PLAIN_SILK`` is two mirror-image halves (swap-invariant → no mark);
#: ``MARKED_SILK`` adds an off-centre bar, which is what a cathode band is.
PLAIN_SILK: list[tuple[str, list[tuple[float, float]]]] = [
    ("X", [(-60.0, -20.0), (-60.0, 20.0)]),
    ("X", [(60.0, -20.0), (60.0, 20.0)]),
]
MARKED_SILK: list[tuple[str, list[tuple[float, float]]]] = PLAIN_SILK + [
    ("X", [(30.0, -25.0), (30.0, 25.0)]),
]


def _polar_board(
    *,
    pads: list[tuple[str, str, tuple[float, float]]],
    silk: list[tuple[str, list[tuple[float, float]]]],
    marks: list[tuple[str, str, float, float]] | None = None,
    mark_radius: float | None = None,
    angle: float = 0.0,
    layer_id: int = 1,
) -> BoardGeometry:
    """A one-part board: pads, silk primitives and (optionally) printed +/− marks."""
    designator = pads[0][0]
    part_pads = [
        PadGeometry(
            id=f"{ref}.{pin}", component=ref, component_id=f"c-{ref}", pin_number=pin,
            net="", layer_id=1, effective_layer_ids=[1],
            x=local[0], y=local[1], local_x=local[0], local_y=local[1],
            width=30.0, height=30.0, shape="RECT", angle=0.0,
        )
        for ref, pin, local in pads
    ]
    shapes: list[SilkShape] = []
    for _ref, points in silk:
        # Every primitive belongs to the one part this board places: the name in
        # the tuple is documentation, not a second component.
        shapes.append(_silk_shape(designator, points))
    if mark_radius is not None:
        shapes.append(
            _silk_shape(designator, [(-20.0, -20.0)], layer_kind="COMPONENT_MARKING",
                        layer_id=49, kind="fill", radius=mark_radius)
        )
    texts: list[SilkText] = []
    for ref, text, x, y in marks or []:
        texts.append(
            SilkText(
                component=ref, component_id=f"c-{ref}", text=text, source="footprint",
                x=x, y=y, local_x=x, local_y=y, angle=0.0, stored_angle=0.0,
                layer_id=3, layer_kind="TOP_SILK", font_size=39.4, stroke_width=8.0,
                origin="LEFT_BOTTOM",
            )
        )
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id=f"c-{designator}", designator=designator, x=0.0, y=0.0,
                               angle=angle, layer_id=layer_id)
        ],
        pads=part_pads,
        silk_shapes=shapes,
        silk_texts=texts,
    )


def test_a_footprint_that_prints_plus_on_the_wrong_pin_is_an_error():
    """The one judgement that needs no convention: two declarations disagree.

    The footprint prints ``+`` next to pad 1 and ``-`` next to pad 2 (its own
    files say so), while the schematic's symbol names pin 1 ``-`` and pin 2
    ``+``. Following the silkscreen would install the part backwards.
    """
    board = _polar_board(
        pads=[("C1", "1", (-40.0, 0.0)), ("C1", "2", (40.0, 0.0))],
        silk=MARKED_SILK,
        marks=[("C1", "+", -45.0, 0.0), ("C1", "-", 45.0, 0.0)],
    )
    parts = {"C1": ([("1", "-"), ("2", "+")], {})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    message = errors[0].message
    assert "丝印极性标记与原理图极性脚不符" in message
    assert "pin 2" in message and "装反" in message
    assert errors[0].target.component_ref == "C1"


def test_the_same_footprint_on_the_right_pin_is_silent():
    """The mirror image of the case above: marks agree with the schematic."""
    board = _polar_board(
        pads=[("C1", "1", (-40.0, 0.0)), ("C1", "2", (40.0, 0.0))],
        silk=MARKED_SILK,
        marks=[("C1", "+", -45.0, 0.0), ("C1", "-", 45.0, 0.0)],
    )
    parts = {"C1": ([("1", "+"), ("2", "-")], {})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    assert [f for f in findings if f.severity in ("ERROR", "WARN")] == []


def test_a_polarised_part_whose_silk_is_swap_invariant_has_no_direction_mark():
    """A symmetric silk drawing cannot tell the two ends apart → ERROR.

    The silk rectangle is centred on the two pads, so rotating the part 180°
    about the pin midpoint leaves the print identical: a board with the part
    fitted either way looks the same.
    """
    board = _polar_board(
        pads=[("D1", "1", (-40.0, 0.0)), ("D1", "2", (40.0, 0.0))],
        silk=PLAIN_SILK,
    )
    parts = {"D1": ([("1", "K"), ("2", "A")], {})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert "没有印刷方向标记" in errors[0].message
    # A mark on the marking layer is **not** silkscreen, so it does not count
    # as a printed direction mark — that is the whole distinction.
    board.silk_shapes.append(
        _silk_shape("D1", [(-40.0, -20.0)], layer_kind="COMPONENT_MARKING",
                    layer_id=49, kind="fill", radius=2.4)
    )
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    assert [f for f in findings if f.severity == "ERROR"], "the dot is not ink"


def test_one_broken_silk_element_is_enough_to_count_as_a_direction_mark():
    """An asymmetric element (a cathode bar) makes the print directional."""
    board = _polar_board(
        pads=[("D1", "1", (-40.0, 0.0)), ("D1", "2", (40.0, 0.0))],
        silk=MARKED_SILK + [("D1", [(30.0, -25.0), (30.0, 25.0)])],
    )
    parts = {"D1": ([("1", "K"), ("2", "A")], {})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    assert [f for f in findings if f.severity == "ERROR"] == []


def test_the_same_footprint_placed_two_ways_is_warned_about():
    """同封装同朝向: two instances of one footprint with different directions."""
    def board_pair(angle_a: float, angle_b: float) -> BoardGeometry:
        components = [
            ComponentPlacement(id="c-A", designator="D1", x=0.0, y=0.0, angle=angle_a, layer_id=1),
            ComponentPlacement(id="c-B", designator="D2", x=200.0, y=0.0, angle=angle_b, layer_id=1),
        ]
        pads = []
        for ref, origin_x, angle in (("D1", 0.0, angle_a), ("D2", 200.0, angle_b)):
            for pin, local in (("1", -40.0), ("2", 40.0)):
                import math

                rad = math.radians(angle)
                pads.append(
                    PadGeometry(
                        id=f"{ref}.{pin}", component=ref, component_id=f"c-{ref}",
                        pin_number=pin, net="", layer_id=1, effective_layer_ids=[1],
                        x=origin_x + local * math.cos(rad), y=local * math.sin(rad),
                        local_x=local, local_y=0.0, width=30.0, height=30.0,
                        shape="RECT", angle=angle,
                    )
                )
        return BoardGeometry(
            source="synthetic", name="SYNTH", components=components, pads=pads,
            silk_shapes=[
                _silk_shape("D1", [(-60.0, -20.0), (60.0, -20.0), (60.0, 20.0), (-60.0, 20.0)]),
                _silk_shape("D2", [(140.0, -20.0), (260.0, -20.0), (260.0, 20.0), (140.0, 20.0)]),
            ],
        )

    parts = {
        "D1": ([("1", "K"), ("2", "A")], {}),
        "D2": ([("1", "K"), ("2", "A")], {}),
    }
    pcb_model = _pcb_side(parts)
    pcb_model.components["D1"].footprint = "SOD-123"
    pcb_model.components["D2"].footprint = "SOD-123"

    same = PolarityOrientation().check(
        _ctx(board_pair(0.0, 0.0), model=_sch(parts), pcb_model=pcb_model)
    )
    assert [f for f in same if f.severity == "WARN"] == []

    mixed = PolarityOrientation().check(
        _ctx(board_pair(0.0, 90.0), model=_sch(parts), pcb_model=pcb_model)
    )
    # 岳 2026-10-11 裁：方向不统一降 INFO（只提醒不算问题）
    infos = [f for f in mixed if f.severity == "INFO" and "方向却有 2 种" in f.message]
    assert len(infos) == 1
    assert "同封装同朝向" in infos[0].message
    assert any("D2" in line for line in infos[0].evidence)
    assert [f for f in mixed if f.severity == "WARN"] == []


def test_a_library_typed_part_without_polarity_pins_is_a_stated_gap():
    """``Type: 聚合物`` says it has polarity; nobody says which pin is +."""
    board = _polar_board(
        pads=[("C1", "1", (-40.0, 0.0)), ("C1", "2", (40.0, 0.0))],
        silk=MARKED_SILK + [("C1", [(30.0, -25.0), (30.0, 25.0)])],
    )
    parts = {"C1": ([("1", "1"), ("2", "2")], {"Type": "聚合物"})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    info = [f for f in findings if f.message.startswith("SYNTH 有 1 颗极性器件")]
    assert info and "没有声明哪只脚是正极" in info[0].message
    assert [f for f in findings if f.severity in ("ERROR", "WARN")] == []


def test_a_board_with_no_polarised_parts_says_zero_rather_than_nothing():
    """「0 颗」 is a reading; a rule that skipped the board would not say it."""
    board = _polar_board(
        pads=[("R1", "1", (-40.0, 0.0)), ("R1", "2", (40.0, 0.0))],
        silk=[("R1", [(-40.0, -20.0), (40.0, -20.0)])],
    )
    parts = {"R1": ([("1", "1"), ("2", "2")], {"Type": "厚膜电阻"})}
    findings = PolarityOrientation().check(
        _ctx(board, model=_sch(parts), pcb_model=_pcb_side(parts))
    )
    assert len(findings) == 1 and findings[0].severity == "INFO"
    assert "0 颗极性器件" in findings[0].message


# ---------------------------------------------------------------------------
# 5. synthetic states — 丝印族
# ---------------------------------------------------------------------------


def _silk_board(
    *,
    texts: list[SilkText],
    pads: list[PadGeometry] | None = None,
    shapes: list[SilkShape] | None = None,
    components: list[ComponentPlacement] | None = None,
) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=components
        or [ComponentPlacement(id=f"c-{t.component}", designator=t.component, layer_id=1)
            for t in texts],
        pads=pads or [],
        silk_shapes=shapes or [],
        silk_texts=texts,
    )


def test_designator_ink_on_a_pad_is_a_warning_only_when_the_narrow_model_hits():
    """Two states of the same geometry: robust overlap → WARN, marginal → INFO."""
    pad = _pad("R1", "1", local=(0.0, 0.0), width=40.0, height=40.0)
    # Anchored so the box's first characters sit well inside the pad.
    over = _silk_board(texts=[_silk_text("R1", "R1", -20.0, -10.0)], pads=[pad])
    findings = SilkDesignator().check(_ctx(over))
    warns = [f for f in findings if f.severity == "WARN"]
    assert len(warns) == 1
    assert "压在焊盘上" in warns[0].message
    assert "R1 pin 1" in warns[0].message
    assert warns[0].target.component_ref == "R1"

    # Far enough that only the widest glyph model reaches the pad.
    near = _silk_board(texts=[_silk_text("R1", "R1", -70.0, 0.0)], pads=[pad])
    findings = SilkDesignator().check(_ctx(near))
    assert [f for f in findings if f.severity == "WARN"] == []
    wide = [f for f in findings if "宽字形模型下" in f.message]
    assert wide and wide[0].severity == "INFO"
    assert any("R1 → R1 pin 1" in line for line in wide[0].evidence)


def test_ink_on_a_silk_layer_never_checks_the_other_face_s_pads():
    """A top-silk designator cannot print on a bottom-face pad."""
    bottom_pad = PadGeometry(
        id="R1.1", component="R1", component_id="c-R1", pin_number="1", net="",
        layer_id=1, effective_layer_ids=[2], x=0.0, y=0.0, local_x=0.0, local_y=0.0,
        width=40.0, height=40.0, shape="RECT", angle=0.0,
    )
    board = _silk_board(
        texts=[_silk_text("R1", "R1", -20.0, -10.0)], pads=[bottom_pad]
    )
    findings = SilkDesignator().check(_ctx(board))
    assert [f for f in findings if f.severity == "WARN"] == []


def test_a_designator_wholly_inside_a_neighbour_body_is_a_warning():
    """完全被压住 = the text box lies inside another part's body outline."""
    body = _silk_shape(
        "U1",
        [(-60.0, -60.0), (60.0, -60.0), (60.0, 60.0), (-60.0, 60.0)],
        layer_kind="COMPONENT_SHAPE",
        layer_id=48,
    )
    components = [
        ComponentPlacement(id="c-U1", designator="U1", layer_id=1),
        ComponentPlacement(id="c-R1", designator="R1", layer_id=1),
    ]
    covered = _silk_board(
        texts=[_silk_text("R1", "R1", -20.0, -10.0)],
        shapes=[body],
        components=components,
    )
    findings = SilkDesignator().check(_ctx(covered))
    warns = [f for f in findings if f.severity == "WARN"]
    assert len(warns) == 1
    assert "被 U1 的器件本体完全压住" in warns[0].message
    assert warns[0].target.component_ref == "R1"

    # Half outside the body: only the measurement row, no verdict.
    partial = _silk_board(
        texts=[_silk_text("R1", "R1", 40.0, -10.0)],
        shapes=[body],
        components=components,
    )
    findings = SilkDesignator().check(_ctx(partial))
    assert [f for f in findings if f.severity == "WARN"] == []
    assert any("部分" in f.message for f in findings if f.severity == "INFO")


def test_a_switched_off_designator_is_reported_as_a_reading():
    """``valueVisible=false``: the fact is read, the intent is not guessed."""
    board = _silk_board(
        texts=[
            _silk_text("C1", "C1", 0.0, 0.0),
            _silk_text("C2", "C2", 100.0, 0.0, visible=False),
            _silk_text("C3", "C3", 200.0, 0.0, visible=False),
        ]
    )
    findings = SilkDesignator().check(_ctx(board))
    hidden = [f for f in findings if "丝印被关掉" in f.message]
    assert hidden and hidden[0].severity == "INFO"
    assert "2 个位号" in hidden[0].message
    assert "C2, C3" in hidden[0].evidence[0]


def test_the_direction_row_is_a_distribution_not_a_verdict():
    """「方向一致」 has no quotable threshold, so it is a reading."""
    board = _silk_board(
        texts=[
            _silk_text("C1", "C1", 0.0, 0.0, angle=0.0),
            _silk_text("C2", "C2", 100.0, 0.0, angle=0.0),
            _silk_text("C3", "C3", 200.0, 0.0, angle=90.0),
            _silk_text("C4", "C4", 300.0, 0.0, angle=180.0),
        ]
    )
    findings = SilkDesignator().check(_ctx(board))
    rows = [f for f in findings if "文字方向分布" in f.message]
    assert len(rows) == 1 and rows[0].severity == "INFO"
    assert "0°×2" in rows[0].message and "90°×1" in rows[0].message
    assert "180°×1" in rows[0].message
    assert "没有可查的阈值" in rows[0].evidence[0]


def test_a_board_with_no_designators_reports_nothing_but_its_summary():
    board = _silk_board(texts=[])
    findings = SilkDesignator().check(_ctx(board))
    assert [f.severity for f in findings] == ["INFO"]
    assert "0 个位号记录" in findings[0].message


# ---------------------------------------------------------------------------
# 6. acceptance anchors — the three boards, measured
# ---------------------------------------------------------------------------


def test_bishe_foc_1_0_0_polarity_reads_five_parts_and_two_direction_splits():
    """毕设FOC 1.0.0 ``PCB1``: 5 polarised parts, 2 WARN, 0 ERROR.

    The five are ``LED1``/``LED4`` (``+``/``-``), ``LED5`` (``C``/``A``) and
    ``C115``/``C116`` (library ``Type: 聚合物``) — ``D1`` is a **bidirectional**
    SMCJ TVS and is excluded on the library's own ``Polarity: 双向``, which is
    the false alarm this rule was built to avoid. The two WARNs are the
    measured direction splits: ``LED0805-R-RD`` used at 90° and 0°, and
    ``CAP-TH_BD10.0-P5.00-D0.6-FD-A`` at 0° and 270°.
    """
    findings, section = _run(FOC_100)
    rows = _rows(section, findings, "PCB1")
    assert [f.severity for f in rows].count("ERROR") == 0

    polarity = [f for f in rows if f.rule_id == POLARITY_ID]
    # 岳 2026-10-11 裁：方向不统一降 INFO
    warns = [f for f in polarity if f.severity == "INFO" and "方向却有" in f.message]
    assert sorted(
        f.message.split("共用封装 ")[1].split("（")[0] for f in warns
    ) == ["'CAP-TH_BD10.0-P5.00-D0.6-FD-A'", "'LED0805-R-RD'"]
    led_warn = [f for f in warns if "LED0805-R-RD" in f.message][0]
    assert "方向却有 2 种：[0.0, 90.0]" in led_warn.message
    assert any(line.startswith("LED1: 极性轴 90.0°") for line in led_warn.evidence)
    assert any(line.startswith("LED4: 极性轴 0.0°") for line in led_warn.evidence)

    summary = [f for f in polarity if f.message.startswith("PCB1 极性器件读数")][0]
    assert "5 颗极性器件" in summary.message
    assert "3 颗原理图声明了极性脚" in summary.message
    assert "2 颗只有库件类型词" in summary.message
    assert "量出印刷方向标记的 5 颗" in summary.message

    gap = [f for f in polarity if "没有声明哪只脚是正极" in f.message]
    assert gap and "C115" in gap[0].evidence[0] and "C116" in gap[0].evidence[1]


def test_bishe_foc_1_0_0_silk_reads_one_warn_and_the_hidden_list():
    """毕设FOC 1.0.0 ``PCB1``: 122 designator records, 31 switched off.

    One WARN: ``C15``'s ink reaches ``R17`` pin 1 by 2.0 mil even at the
    narrowest glyph model. Five more designators only reach a pad under the
    widest model and are filed as one measurement row. ``PCB2`` is clean of
    WARNs.
    """
    findings, section = _run(FOC_100)
    rows = _rows(section, findings, "PCB1")
    silk = [f for f in rows if f.rule_id == SILK_ID]
    warns = [f for f in silk if f.severity == "WARN"]
    assert len(warns) == 1
    assert warns[0].message.startswith("PCB1 C15 的位号丝印压在焊盘上")
    assert "R17 pin 1" in warns[0].message

    wide = [f for f in silk if "宽字形模型下" in f.message]
    assert len(wide) == 1 and "5 个位号" in wide[0].message

    hidden = [f for f in silk if "丝印被关掉" in f.message][0]
    assert "31 个位号" in hidden.message
    assert len(hidden.evidence[0]) > 100

    summary = [f for f in silk if f.message.startswith("PCB1 丝印读数")][0]
    assert "122 个位号记录（显示 91、关掉 31）" in summary.message
    assert "板上焊盘 488 只" in summary.message

    rows2 = _rows(section, findings, "PCB2")
    silk2 = [f for f in rows2 if f.rule_id == SILK_ID]
    assert [f for f in silk2 if f.severity == "WARN"] == []


def test_bishe_foc_1_1_0_reports_the_board_with_a_hundred_designators_off():
    """毕设FOC 1.1.0 ``PCB1``: 105 designator records, **100 switched off**.

    A whole board's legend is off; that is a reading, not a verdict (the rule
    cannot tell "deliberately off" from "forgotten" — the same gap 151 recorded
    for DNP). ``PCB3`` carries the six 330 µF polymer capacitors, all five of
    the polarity rule's rows land there.
    """
    findings, section = _run(FOC_110)
    pcb1 = _rows(section, findings, "PCB1")
    hidden = [f for f in pcb1 if "丝印被关掉" in f.message]
    assert hidden and "100 个位号" in hidden[0].message
    silk_warns = [f for f in pcb1 if f.rule_id == SILK_ID and f.severity == "WARN"]
    assert silk_warns == [], "the board's designators are off, so nothing can collide"

    pcb3 = _rows(section, findings, "PCB3")
    polarity = [f for f in pcb3 if f.rule_id == POLARITY_ID]
    warn = [f for f in polarity if f.severity == "INFO" and "方向却有" in f.message]  # 岳裁降 INFO
    assert len(warn) == 1
    assert "6 颗极性器件共用封装 'CAP-TH_BD10.0-P5.00-D0.6-FD-A'" in warn[0].message
    assert "方向却有 2 种：[0.0, 90.0]" in warn[0].message
    gap = [f for f in polarity if "没有声明哪只脚是正极" in f.message][0]
    assert "6 颗" in gap.message

    silk3 = [f for f in pcb3 if f.rule_id == SILK_ID]
    silk_warn = [f for f in silk3 if f.severity == "WARN"]
    assert len(silk_warn) == 1 and "D2 的位号丝印压在焊盘上" in silk_warn[0].message


def test_robot_ctrl_foc_has_no_polarised_part_at_all():
    """ROBOT ``PCB1``: 0 polarised parts, 0 polarity WARN — and it says so.

    The board carries no diode, LED, electrolytic or battery part: every part's
    symbol pins are ``1``/``2`` and no library ``Type`` names one of the
    polarity words. The polarity rule still files its summary reading 「0 颗极性
    器件」, which is the difference between "there are none" and "not looked at".
    """
    findings, section = _run(ROBOT)
    rows = _rows(section, findings, "PCB1")
    polarity = [f for f in rows if f.rule_id == POLARITY_ID]
    assert [f.severity for f in polarity] == ["INFO"]
    assert "0 颗极性器件" in polarity[0].message

    silk = [f for f in rows if f.rule_id == SILK_ID]
    assert [f for f in silk if f.severity == "WARN"] == []
    hidden = [f for f in silk if "丝印被关掉" in f.message][0]
    assert "30 个位号" in hidden.message
    orphan = [f for f in silk if "找不到它命名的器件" in f.message][0]
    assert "R6" in orphan.evidence[0]
    assert "同一条位号的重复记录" in orphan.message


def test_the_llc_fixture_finds_real_defects_in_both_families():
    """llc's own layout is where both families have something to say.

    Measured: four SMB diodes placed in two directions (``D1``/``D2`` at 90°,
    ``D3``/``D4`` at 270°), ``C3``'s designator wholly inside ``U8``'s body
    outline, and ``D2``/``R2``'s ink over their own pads. ``D3``'s designator
    is 2/4 corners inside ``C5``'s body — the partial case, filed as a reading.
    """
    findings, section = _run(LLC)
    rows = _rows(section, findings, "PCB1")
    polarity_warns = [f for f in rows if f.rule_id == POLARITY_ID and f.severity == "INFO" and "方向却有" in f.message]  # 岳裁降 INFO
    assert len(polarity_warns) == 1
    assert "SMB_L4.3-W3.6-LS5.3-RD" in polarity_warns[0].message
    assert "方向却有 2 种：[90.0, 270.0]" in polarity_warns[0].message
    assert "D3: 极性轴 270.0°" in "\n".join(polarity_warns[0].evidence)

    silk_warns = [f for f in rows if f.rule_id == SILK_ID and f.severity == "WARN"]
    assert len(silk_warns) == 3
    texts = " | ".join(f.message for f in silk_warns)
    assert "D2 的位号丝印压在焊盘上" in texts
    assert "R2 的位号丝印压在焊盘上" in texts
    assert "C3 的位号丝印被 U8 的器件本体完全压住" in texts
    partial = [f for f in rows if "部分" in f.message and f.rule_id == SILK_ID]
    assert partial and "D3 落在 C5 本体轮廓内 2/4 角" in partial[0].evidence[0]


def test_the_rules_are_silent_on_a_board_with_no_pcb_document(tmp_path: Path):
    """The runner's absent-not-empty rule: no PCB → no section, no findings."""
    from boardwise.engines.pcbreview import run_pcb_review

    no_pcb = FIXTURES / "ProPrj_CH340G_2026-09-13.epro2"
    assert run_pcb_review(no_pcb) == ([], None)


def test_every_finding_carries_the_board_title():
    """钉 4: a PCB finding is stamped with the PCB document's title."""
    findings, section = _run(FOC_100)
    assert findings
    for entry in section["boards"]:
        for index in entry["findings"]:
            assert findings[index].board == entry["title"]


def test_the_evidence_is_json_serialisable():
    """Findings flow into the report's JSON, so their evidence must survive it."""
    findings, _section = _run(LLC)
    payload = [
        {"rule": f.rule_id, "severity": f.severity, "message": f.message,
         "evidence": f.evidence,
         "target": f.target.component_ref if f.target else None}
        for f in findings
    ]
    assert json.loads(json.dumps(payload, ensure_ascii=False))
