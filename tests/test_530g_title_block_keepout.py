"""530G: the sheet's title block as a **keep-out**, from the page to the packing.

`docs/schematic-style-spec.md` S-01 has two halves — 「内容不进入标题栏矩形」 and
「整图下方留 ~15% 空白」 — and this batch lands both, at the two places the batch
contract names (`tasks/530g-*`): the rectangle (`core.pageframe`) and the packing
(`islandlayout.PageBudget` / `pack_islands`), with the compiler handing the packer
and the gate **one** derivation (`drawcompiler._try_island_variants`) and the CLI
deriving it from the page box it was handed (`cli._draw_compile`).

What the tests hold, in the order they read:

**A. the rectangle.** The block is not a ratio and not the legacy 320x100 carve
(`engines.layout.TITLE_BLOCK`, task 006): it is the sheet symbol's own ``TABLE``
primitive, 700x180, anchored to the sheet corner with the frame inset. The two
golden pages are read **from their own files** (the page's declared attributes and
the symbol document's table) and the model has to reproduce both; the render of
the flyback page (`evidence/521/521_page.svg`) is where the absolute numbers come
from and is cited in the module's own docstring.

**B. the packing.** On the real flyback page the islands are packed onto the sheet
the project declares, and then **nothing** the page draws — a part's body, a wire,
a text box, a flag's glyph — is inside the block or inside the blank band. The
reading is independent of the packer (the object walk in
:func:`_objects_inside`) *and* taken from the gate (`readability.check`'s
`out-of-page`/keep-out half), because a packer that reports its own compliance is
not a measurement.

**C. the no-op.** A page with no sheet stated packs **exactly** where it did
before this batch — the five offsets and the layout digest 530B/530C/530D froze
(``6239264238ef93e3…``). The blank band needs a sheet height and the keep-outs are
boxes on a sheet, so neither is evaluated without a `page_box`; that is what keeps
this batch from moving the drawing every earlier island batch measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core import pageframe
from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.core.symbolprofile import SymbolProfile, flag_glyph_box, pose_box
from boardwise.engines import drawcompiler as dc
from boardwise.engines import islandlayout as il
from boardwise.engines import readability as rb

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
FIXTURES = ROOT / "tests" / "fixtures"

#: The sheet the flyback's own project declares — A4 at the scale `ch340_golden`
#: and the flyback golden both use, and the same page the render in
#: ``evidence/521/521_page.svg`` draws.
FLYBACK_SHEET = (0.0, 0.0, 1170.0, 825.0)
#: The sheet the golden FOC board declares — the same A4 at 1.4142x the units,
#: which is where the block's *anchoring* (and not its size) shows up.
FOC_SHEET = (0.0, 0.0, 1655.0, 1170.0)

#: ``Title Block Position`` = 3 on every page here that has a title block at all.
POSITION = "3"


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


def _sheet_attrs_of(fixture: str) -> dict[str, str]:
    """The page attributes a fixture declares, through the repo's own parser."""
    import boardwise.parsers.schematic as schematic

    return dict(schematic.collect_page_layout(FIXTURES / fixture).sheet_attrs)


def _sheet_symbol_table(fixture: str) -> dict[str, object]:
    """The sheet symbol's own ``TABLE`` record: the title block as drawn.

    Read straight out of the archive: ``DOCHEAD``s delimit the documents, the
    page's own ``Symbol`` attribute (the one whose siblings declare ``Width`` and
    ``Height``) names the sheet symbol, and the symbol document's ``TABLE`` is the
    block.  Nothing here goes through :mod:`boardwise.core.pageframe` — that is the
    point of the test that uses it.
    """
    from collections import Counter

    import boardwise.parsers.schematic as schematic
    from boardwise.parsers.epru_stream import ParseStats, load_epru_text

    path = FIXTURES / fixture
    text, meta = load_epru_text(path)
    stats = ParseStats(source=str(path), editor_version=meta.get("editorVersion"))
    records = schematic._iter_schematic_records(text, stats)
    split = schematic._split_page(records, stats)

    parents = Counter(
        str(item.body.get("parentId") or "")
        for item in split.loose
        if str(item.body.get("key") or "") == "Symbol"
        and any(
            str(other.body.get("key") or "") in ("Width", "Height")
            and str(other.body.get("parentId") or "")
            == str(item.body.get("parentId") or "")
            for other in split.loose
        )
    )
    assert parents, "no sheet symbol found in the fixture"
    symbol = ""
    for item in split.loose:
        if (
            str(item.body.get("key") or "") == "Symbol"
            and str(item.body.get("parentId") or "") in parents
        ):
            symbol = str(item.body.get("value") or "")

    uuid = ""
    found: dict[str, object] = {}
    for record in records:
        if record.type == "DOCHEAD":
            uuid = str((record.body or {}).get("uuid") or "")
            continue
        if uuid != symbol or record.body is None:
            continue
        if record.type == "TABLE":
            found["table"] = dict(record.body)
        elif record.type == "PART":
            found["bbox"] = list((record.body or {}).get("BBOX") or [])
    assert "table" in found, f"the sheet symbol {symbol} draws no TABLE"
    return found


def _objects_inside(plan, book, keep) -> list[str]:
    """Every object the page draws whose own box is inside ``keep``.

    An independent reading of "inside a keep-out", written the way a reader would
    check it by hand: a part's **drawn body** (not its pin tips), a wire's polyline
    segment, a text box, and a flag's glyph.  A wire is tested per segment because
    a polyline's bounding box is not the wire (`readability._check_page` makes the
    same point, and this walk is deliberately a second opinion on it).
    """
    hit: list[str] = []
    for part in plan.parts:
        profile = book.get(part.symbol_ref)
        box = (
            pose_box(
                profile.body, rotation=part.rotation, mirror=part.mirror,
                ox=part.x, oy=part.y,
            )
            if profile is not None else None
        )
        if box is not None and _overlaps(box, keep):
            hit.append(f"part {part.part_id}")
    for index, text in enumerate(plan.texts):
        if _overlaps(text.bbox, keep):
            hit.append(f"text[{index}] {text.text}")
    for index, symbol in enumerate(plan.power_symbols):
        profile = book.get(symbol.symbol_ref)
        glyph = (
            flag_glyph_box(
                profile, rotation=symbol.rotation, anchor=(symbol.x, symbol.y),
            )
            if profile is not None else None
        )
        if glyph is not None and _overlaps(glyph, keep):
            hit.append(f"flag[{index}] {symbol.net}")
    for index, segment in enumerate(plan.segments):
        for start, end in zip(segment.points, segment.points[1:]):
            box = (
                min(start[0], end[0]), min(start[1], end[1]),
                max(start[0], end[0]), max(start[1], end[1]),
            )
            if _overlaps(box, keep):
                hit.append(f"wire[{index}] {segment.net or '-'}")
                break
    return hit


def _overlaps(first, second) -> bool:
    return (
        first[0] < second[2] and second[0] < first[2]
        and first[1] < second[3] and second[1] < first[3]
    )


# ======================================================= A. the rectangle


def test_the_two_golden_pages_put_the_block_where_the_files_say_it_is() -> None:
    """The model against the two pages whose geometry differs only by scale.

    The flyback/ch340 goldens declare 1170x825 and put the block at
    ``(460, 10)-(1160, 190)``; the FOC golden declares 1655x1170 (the same A4 in
    1.4142x units) and puts it at ``(945, 10)-(1645, 190)`` — **the same 700x180
    block**, moved 485 units right with the wider sheet and not moved at all by the
    taller one.  Those two rectangles are the measured ones: the first is what the
    editor's own render of the flyback page draws (``evidence/521/521_page.svg``,
    the ``table-*`` fill rects), and the second is what the FOC page's own copies
    of the title-block fields show (every x shifted by exactly 485 = 1655 - 1170,
    every y unchanged).
    """
    assert pageframe.title_block_box(FLYBACK_SHEET) == (460.0, 10.0, 1160.0, 190.0)
    assert pageframe.title_block_box(FOC_SHEET) == (945.0, 10.0, 1645.0, 190.0)


def test_the_block_is_anchored_to_the_corner_and_does_not_scale() -> None:
    """Anchoring, stated as the property the two files actually exhibit.

    A wider sheet moves the block (its distance from the right edge is constant),
    a taller sheet does not (its distance from the bottom edge is constant), and
    its size is the same on both — which is why the model is a size plus a corner
    and not a fraction of the sheet.
    """
    narrow = pageframe.title_block_box(FLYBACK_SHEET)
    wide = pageframe.title_block_box(FOC_SHEET)
    tall = pageframe.title_block_box((0.0, 0.0, 1170.0, 1655.0))
    for box in (narrow, wide, tall):
        assert (box[2] - box[0], box[3] - box[1]) == pageframe.TITLE_BLOCK_SIZE
        assert FLYBACK_SHEET[0] + box[1] == 10.0, box
    assert FLYBACK_SHEET[2] - narrow[2] == FOC_SHEET[2] - wide[2] == 10.0
    assert (narrow[1], narrow[3]) == (tall[1], tall[3]) == (10.0, 190.0)


def test_the_region_counts_do_not_move_the_block() -> None:
    """``X``/``Y Region Count`` divide the *frame*; the block is not a zone.

    The two measured pages declare 6x4, the one page that declares no block at all
    declares 6x4 too, and the block's own table is the same 700x180 in both — so
    the counts are read as the zone ticks they are, and changing them changes
    nothing here.
    """
    base = {
        "Width": "1655", "Height": "1170", "Blade Width": "10",
        "Title Block": "1", "Title Block Position": POSITION,
    }
    six = {**base, "X Region Count": "6", "Y Region Count": "4"}
    twelve = {**base, "X Region Count": "12", "Y Region Count": "8"}
    assert (
        pageframe.title_block_from_sheet_attrs(six)
        == pageframe.title_block_from_sheet_attrs(twelve)
        == (945.0, 10.0, 1645.0, 190.0)
    )


def test_the_declared_positions_are_the_four_corners() -> None:
    """Four declared positions, four corners, one measured between them.

    Only **3 = bottom-right** is measured (every page in this repo that has a
    title block declares 3, and the flyback page's own render draws a bottom-right
    block), and :data:`pageframe.TITLE_BLOCK_POSITION_MEASURED` says so — the other
    three are this batch's declared reading of a selector nothing here has driven,
    and a future batch that can render one of them moves it into that set.
    """
    assert pageframe.TITLE_BLOCK_POSITION_MEASURED == {"3"}
    assert pageframe.TITLE_BLOCK_POSITIONS["3"] == ("right", "bottom")
    corners = {
        position: pageframe.title_block_box(FLYBACK_SHEET, position=position)
        for position in ("1", "2", "3", "4")
    }
    assert corners["3"] == (460.0, 10.0, 1160.0, 190.0)
    assert corners["4"] == (460.0, 635.0, 1160.0, 815.0)
    assert corners["2"] == (10.0, 10.0, 710.0, 190.0)
    assert corners["1"] == (10.0, 635.0, 710.0, 815.0)
    assert len(set(corners.values())) == 4


def test_an_unknown_position_falls_back_to_the_measured_corner() -> None:
    """A position we cannot read must not become *no* keep-out.

    Falling back to bottom-right is the safe direction to be wrong in: a keep-out
    in roughly the right place costs layout space, and one that is skipped costs
    the rule.
    """
    for value in ("", "9", "bottom-right", None, "  "):
        assert pageframe.title_block_box(
            FLYBACK_SHEET, position=value,
        ) == (460.0, 10.0, 1160.0, 190.0)
    attrs = {"Width": "1170", "Height": "825", "Title Block Position": "nonsense"}
    assert pageframe.title_block_from_sheet_attrs(attrs) == (460.0, 10.0, 1160.0, 190.0)


def test_a_page_that_states_no_title_block_or_no_size_states_none() -> None:
    """``None`` is a statement, and there are exactly two ways to make it.

    ``Title Block = 0`` is the one value in this repo that is not ``1`` (级联多电平
    -主拓扑, 900x825) and is read as "this page has no block"; a page that states no
    usable width or height has no rectangle to carve.  Both readings are declared
    rather than measured, and the module's docstring says which — a caller that has
    no attributes at all (every compile path) reserves the block unconditionally,
    so the unverified reading is never the one a drawing depends on.
    """
    assert pageframe.title_block_from_sheet_attrs(
        {"Width": "900", "Height": "825", "Title Block": "0",
         "Title Block Position": POSITION}
    ) is None
    for attrs in (
        {"Title Block": "1", "Title Block Position": POSITION},
        {"Width": "0", "Height": "825", "Title Block": "1"},
        {"Width": "abc", "Height": "825", "Title Block": "1"},
    ):
        assert pageframe.title_block_from_sheet_attrs(attrs) is None
    assert pageframe.title_block_keepouts(None) == ()
    assert pageframe.title_block_keepouts(FLYBACK_SHEET) == (
        (460.0, 10.0, 1160.0, 190.0),
    )


def test_the_block_contains_the_legacy_320x100_carve() -> None:
    """The relationship to `engines.layout.TITLE_BLOCK`, asserted rather than told.

    The legacy constant is 320x100 at the bottom-right — a **subset** of the real
    block on every sheet, which is exactly why S-01 could not be kept by it: on the
    flyback's own sheet the island page as earlier batches packed it had 16 objects
    inside the carve and 30 inside the block
    (``evidence/530g/raw/50_gate.json``).
    """
    from boardwise.engines import layout as legacy

    real = pageframe.title_block_box(FLYBACK_SHEET)
    carve = (
        FLYBACK_SHEET[2] - 330.0, legacy.TITLE_BLOCK[1],
        FLYBACK_SHEET[2] - 10.0, legacy.TITLE_BLOCK[3],
    )
    assert (
        real[0] <= carve[0] and real[1] <= carve[1]
        and carve[2] <= real[2] and carve[3] <= real[3]
    ), (real, carve)
    assert (carve[2] - carve[0], carve[3] - carve[1]) == (320.0, 100.0)


@pytest.mark.parametrize(
    "fixture",
    ["ProPrj_ROBOT ctrl FOC_2026-09-16.epro2", "ch340_golden.epro2"],
)
def test_the_model_reproduces_each_fixtures_own_table(fixture: str) -> None:
    """The strongest reading available offline: the model against the *files*.

    The page's declared attributes go in, and the numbers that come out have to be
    the sheet symbol's own ``TABLE``: its ``colSizes``/``rowSizes`` are the block's
    size, its ``startY`` and its last row are the block's bottom and top edges, and
    the block's left edge is the right frame edge less that width.  Both fixtures
    (1170x825 and 1655x1170) have to satisfy it with the *same* block — which is
    the "anchored, not scaled" claim read off two archives rather than off a
    picture.
    """
    attrs = _sheet_attrs_of(fixture)
    symbol = _sheet_symbol_table(fixture)
    table = symbol["table"]
    width = float(attrs["Width"])
    margin = float(attrs["Blade Width"])
    table_width = sum(float(value) for value in table["colSizes"])
    table_height = sum(float(value) for value in table["rowSizes"])
    bottom = float(table["startY"]) + table_height

    box = pageframe.title_block_from_sheet_attrs(attrs)
    assert box is not None
    assert (table_width, table_height) == pytest.approx(pageframe.TITLE_BLOCK_SIZE)
    assert (box[2] - box[0], box[3] - box[1]) == pytest.approx(
        (table_width, table_height)
    )
    assert box[0] == pytest.approx(width - margin - table_width)
    assert box[2] == width - margin
    assert box[1] == pytest.approx(-bottom) == margin
    assert box[3] == pytest.approx(-float(table["startY"]))
    #: and the symbol's own part box agrees to within its own half-unit stroke
    bbox = symbol["bbox"]
    assert abs(float(bbox[0]) - float(table["startX"])) <= 1.0
    assert abs(float(bbox[2]) - (float(table["startX"]) + table_width)) <= 1.0


# ======================================================= B. the packing


def _packed(sheet, keepouts=()) -> il.PackedPage:
    circuit, presentation, book = _flyback()
    return il.island_page(
        circuit, presentation, book,
        page_budget=il.PageBudget(page_box=sheet, keepouts=tuple(keepouts)),
    )


def test_the_real_island_page_stays_out_of_the_title_block() -> None:
    """S-01's first half on the real page: **nothing** is inside the block.

    Two independent readings.  The packer's own audit (`keepout_conflicts`) is one;
    the second is a walk over everything the page draws — bodies, wires, texts,
    flag glyphs — taken against the block's box directly.  And the third is the
    gate the compiler itself uses (`readability.check` with the same page box and
    keep-out), whose page half must report nothing: a packing that only satisfies
    the packer would be a packing nobody measured.
    """
    circuit, presentation, book = _flyback()
    block = pageframe.title_block_box(FLYBACK_SHEET)
    page = _packed(FLYBACK_SHEET, (block,))
    assert page.keepouts == (block,)
    assert page.keepout_conflicts == []
    for island in page.blocks:
        assert not _overlaps(island.bbox(), block), island.island_id

    plan = page.plan()
    inside = _objects_inside(plan, book, block)
    assert inside == [], inside

    checked = rb.check(
        plan, circuit, presentation, book,
        page_box=FLYBACK_SHEET, keepouts=(block,),
    )
    page_rows = [
        item.render() for item in checked.hard_violations
        if "keep-out" in item.render() or "out-of-page" in item.render()
    ]
    assert page_rows == [], page_rows


def test_the_drawing_keeps_the_blank_band_clear() -> None:
    """S-01's second half: 15% of the sheet's height, below everything.

    The band is a fraction of the stated sheet and nothing else, so it is read
    here as the number it is: the flyback's own 825-unit sheet puts the floor at
    123.75, the golden FOC sheet's 1170 puts it at 175.5, and the drawing's lowest
    object is at or above whichever applies.
    """
    for sheet, expected in ((FLYBACK_SHEET, 123.75), (FOC_SHEET, 175.5)):
        page = _packed(sheet)
        assert page.floor == expected, (sheet, page.floor)
        assert page.bbox()[1] >= expected
        assert il.PageBudget().bottom_blank == il.BOTTOM_BLANK == 0.15
        assert any("S-01 blank band" in note for note in page.notes)


def test_the_bottom_row_is_snapped_up_to_the_floor() -> None:
    """The floor is a bound, not a hint — the invariant the audit leans on.

    `_snap` rounds to the *nearest* lattice point, so packing the bottom row with
    it can land a block up to half a grid **below** the floor it was lifted to
    clear; on the measured sheet that is 1.5 units inside the title block.  Every
    block's lowest edge is therefore at or above the floor, to the last float.
    """
    block = pageframe.title_block_box(FLYBACK_SHEET)
    page = _packed(FLYBACK_SHEET, (block,))
    for island in page.blocks:
        assert island.bbox()[1] >= page.floor - 1e-9, island.island_id
    assert page.bbox()[1] >= block[3]


def test_a_keepout_that_does_not_share_the_drawings_x_range_does_not_lift_it() -> None:
    """The x-test is what keeps a corner we never reach from costing height.

    The islands are packed in three columns whose right edge is 1037.4 on this
    page; a title block stated to the right of that (a corner no block goes near)
    must leave the packing on its blank-band floor, and the same block moved left
    under the islands must lift them.
    """
    far = (1200.0, 10.0, 1500.0, 190.0)
    near = (900.0, 10.0, 1160.0, 190.0)
    sheet = (0.0, 0.0, 1655.0, 1170.0)
    without = _packed(sheet, (far,))
    with_ = _packed(sheet, (near,))
    assert without.floor == 175.5, without.floor
    assert with_.floor == 190.0, with_.floor
    assert not any("S-01 keep-out" in note for note in without.notes)
    assert any("S-01 keep-out" in note for note in with_.notes)
    assert without.keepout_conflicts == [] and with_.keepout_conflicts == []


def test_a_page_with_no_sheet_packs_exactly_where_it_did_before() -> None:
    """The no-op guard: **530G's rule**, to the float and to the digest.

    Without a `page_box` there is no sheet height to take the blank band's fraction
    of, and no sheet for a keep-out to be a box on, so neither rule runs — which is
    what keeps *this* batch (the title-block keep-out) from moving the drawing the
    island batches froze.  The numbers below were re-pinned by **531**, and the
    reason is 531's own subject: the island layout's text stopped being a fiction
    (the boxes are the ones the host actually prints,
    `core.textmetrics.symbol_rows`), which moved the row pitch, the anchor's own box
    in the placement's avoidance set, and the second decoupling part's offset. The
    digest went `6239264238ef93e3…` → `a797e3afd89b4283…`, the page got 40 units
    **smaller** in both directions (`958.2 x 400.5` against `1038.2 x 440.5`), and
    the two rules this file tests still do exactly nothing without a sheet.

    **201H re-pinned them once more** (`e165aede…` → `565ab76d…`), and the mover is
    one row rather than a layout: the transformer's value row is hidden by S-21's
    first way out (it prints through its own pin typography), and a text box is part
    of the picture the digest states (`geometry_sha256`). `page.offsets` and
    `page.bbox()` did **not** move — the block extents, the wires, the flags and the
    parts are byte-identical (`evidence/201h/`) — which is what keeps this file's
    two rules no-ops without a sheet: `keepouts == ()`, `floor == margin`, no
    conflict.
    """
    circuit, presentation, book = _flyback()
    page = il.island_page(circuit, presentation, book)
    assert page.keepouts == ()
    assert page.floor == il.PageBudget().margin == 20.0
    assert page.keepout_conflicts == []
    assert page.offsets == {
        "primary": (140.0, 125.0),
        "secondary": (900.0, 95.0),
        "feedback": (550.0, 345.0),
        "bridge": (580.0, 110.0),
        "control": (100.0, 350.0),
    }
    assert page.bbox() == pytest.approx(
        (20.535064572425824, 20.0, 988.1874485165794, 400.5)
    )
    assert page.plan().geometry_sha256() == (
        "565ab76d0093f83c2d1053eb8d3dc60f85963a982c9137befe10e01e7f2112bd"
    ), (
        "the island page moved again: that is a *layout* batch's business, and this "
        "number is the witness of when — 532 re-pinned it from a797e3af… when the "
        "rows a part's own drawing occupies started deciding the pitch"
    )


def test_the_island_page_digest_is_the_frozen_one_for_the_compiler_too() -> None:
    """The same digest by the other road: `drawcompiler` packing the same islands.

    `_try_island_variants` builds its own page (it has to: it also reports), so the
    digest is read again through `drawcompiler` with no page box stated — the two
    roads must agree on the picture even though the compile itself is refused by
    the page's own `LED_K` text-overlap (530D's open finding, not this batch's).
    """
    circuit, presentation, book = _flyback()
    captured: list[il.PageBudget] = []
    original = il.island_page

    def capture(*args, page_budget=None, **kwargs):
        captured.append(page_budget)
        return original(*args, page_budget=page_budget, **kwargs)

    import boardwise.engines.islandlayout as layout_module

    layout_module.island_page = capture
    try:
        dc.compile(circuit, presentation, book, dc.CompileBudget())
    finally:
        layout_module.island_page = original
    assert len(captured) == 1
    assert captured[0].keepouts == () and captured[0].page_box is None


def test_a_keepout_that_leaves_no_room_is_refused_with_its_own_numbers() -> None:
    """The accounting half: no room means a refusal that names what took it.

    On a sheet too short for the drawing *plus* the floor, the compiler refuses and
    the refusal says which keep-out and which band set the floor — the "放不下时记账"
    clause, read end to end.  Before this batch the island path's own refusal was
    dropped on the floor by `_no_candidate_failures` (which reads `rejected`, not
    `failures`), so a page whose sheet did not fit reported "no variant produced a
    plan, and none recorded a reason" — a refusal without a reason, on the one
    refusal that had one.
    """
    circuit, presentation, book = _flyback()
    short = (0.0, 0.0, 1170.0, 500.0)
    result = dc.compile(
        circuit, presentation, book,
        dc.CompileBudget(page_box=short, keepouts=pageframe.title_block_keepouts(short)),
    )
    assert result.ok is False and result.candidates == []
    rendered = result.render_failures()
    assert "outside the stated page" in rendered, rendered
    assert "keep-out box(es)" in rendered, rendered
    assert "packing floor at y=190" in rendered, rendered
    assert "1 variant(s) were built and refused" in rendered, rendered
    assert [item.variant for item in result.rejected] == ["island-page (5 islands)"]


def test_a_packing_defect_is_refused_rather_than_drawn() -> None:
    """The guard on `keepout_conflicts`, forced because the floor makes it unreachable.

    `_page_floor` lifts the whole page above every keep-out sharing the drawing's
    x-range, so a conflict cannot arise from a stated keep-out — which is exactly
    why the branch needs a test: a guard nobody can reach is a guard nobody checks.
    The page here is a real one with its audit field populated, and the compiler has
    to refuse it and say why.
    """
    circuit, presentation, book = _flyback()
    original = il.island_page

    def conflicted(*args, page_budget=None, **kwargs):
        page = original(*args, page_budget=page_budget, **kwargs)
        page.keepout_conflicts = [
            "island 'bridge' at (0, 0)-(10, 10) is inside keep-out "
            "keepouts[0] (0, 0)-(20, 20)"
        ]
        return page

    import boardwise.engines.islandlayout as layout_module

    layout_module.island_page = conflicted
    try:
        result = dc.compile(
            circuit, presentation, book,
            dc.CompileBudget(keepouts=((0.0, 0.0, 20.0, 20.0),)),
        )
    finally:
        layout_module.island_page = original
    assert result.ok is False
    assert "inside a keep-out after packing" in result.render_failures()
    assert "island 'bridge'" in result.render_failures()


# ======================================================= C. the wiring


def test_the_packer_and_the_gate_are_handed_the_same_keepouts() -> None:
    """One derivation, two consumers — read off what each of them was given.

    The contract's own clause: `CompileBudget.keepouts` reaches the island packer
    and the readability gate as **the same tuple**, not two boxes derived twice.
    Both ends are recorded here (the packer through its `PageBudget`, the gate
    through the keyword it was called with) so the test fails if either is handed
    something else.
    """
    circuit, presentation, book = _flyback()
    keep = pageframe.title_block_box(FIXTURES and FLYBACK_SHEET)
    page = _packed(FLYBACK_SHEET, (keep,))
    assert page.keepouts == (keep,)

    budgets: list[il.PageBudget] = []
    gates: list[tuple] = []
    original_page = il.island_page
    original_check = rb.check

    def capture_page(*args, page_budget=None, **kwargs):
        budgets.append(page_budget)
        return original_page(*args, page_budget=page_budget, **kwargs)

    def capture_check(*args, **kwargs):
        gates.append(tuple(kwargs.get("keepouts") or ()))
        return original_check(*args, **kwargs)

    import boardwise.engines.islandlayout as layout_module

    layout_module.island_page = capture_page
    rb.check = capture_check
    try:
        dc.compile(
            circuit, presentation, book,
            dc.CompileBudget(
                page_box=FLYBACK_SHEET, keepouts=(keep,),
            ),
        )
    finally:
        layout_module.island_page = original_page
        rb.check = original_check
    assert [budget.keepouts for budget in budgets] == [(keep,)]
    assert [budget.page_box for budget in budgets] == [FLYBACK_SHEET]
    assert gates == [(keep,)]


def test_draw_compile_reserves_the_title_block_for_an_island_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI end of it: `--page-box` alone makes S-01 bite.

    The island page is the only page-scale drawing the single-module compiler
    produces, so `draw compile` derives the block from the stated page box for it
    and says so; the packer's own two S-01 notes are in the same report, which is
    what shows the keep-out travelled all the way down rather than stopping in
    `cli.py`.

    **530F 重钉**: this run used to be refused (by the page's own `LED_K`
    text-overlap, 530D's open finding), so the assertions read the notes, "which are
    written whether or not a candidate survives".  It is **delivered** now — 530F's
    delivery policy (`drawcompiler.ISLAND_GATE_TOLERATED_LIMITS`) tolerates a
    host-printed row and names it — so the run's exit code and the payload's `ok`
    move with it.

    **531 重钉 the account itself**: the page used to deliver with one tolerated row
    (the `LED_K` label wire's own name row over `R7`) and then delivered with
    **none**, because the placement learned where the host prints a part's own rows
    and moved `R7` off it.

    **532 re-pinned it again, and the change is a different one in kind**: the
    account is not empty any more, and what is in it is not a wire's name row but
    the **transformer's own pin typography** (`T1`'s `2`/`5`/`5` over its own
    `EE16_3+3_V02`) — a class `readability` could not see at all before this batch
    (`KIND_PIN_TEXT_PRESSED`). So the assertion is no longer "no such line": it is
    the exact line, three times, and the two older kinds are asserted **absent**,
    which is the stronger form of what 531 wrote.
    """
    report = tmp_path / "compile.json"
    code = cli.main([
        "draw", "compile",
        "--circuit", str(SPECS / "flyback_uc3845.circuit.json"),
        "--presentation", str(SPECS / "flyback_uc3845.presentation.json"),
        "--profiles", str(SPECS / "flyback_uc3845.library.json"),
        "--page-box", "0,0,1170,825",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    notes = "\n".join(payload["notes"])
    assert "S-01: reserving the sheet's title block" in notes, notes
    assert "(460.0, 10.0, 1160.0, 190.0)" in notes, notes
    assert "S-01 keep-out: 1 keep-out box(es)" in notes, notes
    assert "S-01 blank band" in notes, notes
    assert payload["ok"] is True
    assert len(payload["candidates"]) == 1 and payload["rejected"] == []
    assert "tolerated: " not in notes, (
        "201H: the transformer's value row is hidden by S-21's first way out, so "
        f"the delivery gate has nothing left to tolerate: {notes}"
    )
    assert "the delivery gate tolerated" not in notes, notes


def test_draw_compile_leaves_a_single_module_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The other half of the wiring: a module is not a page.

    The divider presentation declares one module and no islands, so it draws the
    module it always drew (`drawcompiler` step 5 sends it the single-module way)
    and this stage states no sheet for it — a title-block keep-out here would be a
    box about a page the drawing is not being placed on.
    """
    fixtures = ROOT / "tests" / "fixtures" / "drawapply"
    report = tmp_path / "module.json"
    code = cli.main([
        "draw", "compile",
        "--circuit", str(fixtures / "divider.circuit.json"),
        "--presentation", str(fixtures / "divider.presentation.json"),
        "--profiles", str(fixtures / "library.json"),
        "--page-box", "0,-1000,1200,0",
        "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True and payload["candidates"]
    assert "S-01" not in "\n".join(payload["notes"])
