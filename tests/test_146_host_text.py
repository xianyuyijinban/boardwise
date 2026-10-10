"""146 — the host's own text, modelled; and the render's wire shape.

Four claims, each measured on the 145e render of `test/P1` rather than assumed:

1. the render has **one** text ruler, and the compiler and the lint read the same
   one (`core.textmetrics.render_width`);
2. a named wire's net name is anchored by the *host* at the midpoint of the
   wire's longest straight run, start-anchored (`wire_name_box`);
3. a reported wire's drawn segments are its flat `Line` list taken **pairwise**
   (`drawlint._wire_segments`) — the reading the render's own polylines show,
   with the path reading kept for the odd-length list the repo's fixtures use;
4. a part's designator and value are drawn where its **symbol** puts them, and
   the compiler reads those anchors from the library (`_declared_rows`) instead
   of inventing a free side — and a name stub whose row would land on the part it
   names steps out to the next rung (`drawapply._name_row_clash`).
"""

from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from boardwise.core import textmetrics  # noqa: E402
from boardwise.core.symbolprofile import SymbolPose  # noqa: E402
from boardwise.engines import drawapply, drawcompiler, drawlint  # noqa: E402

LIBRARY = json.loads(
    (ROOT / 'blocklib' / 'specs' / 'flyback_uc3845.library.json').read_text(
        encoding='utf-8'
    )
)


def _profile(symbol_ref: str):
    return drawapply.load_library(
        ROOT / 'blocklib' / 'specs' / 'flyback_uc3845.library.json'
    )[symbol_ref]


# ------------------------------------------------------- 1. one text ruler

def test_the_compiler_and_the_lint_measure_a_string_with_one_ruler():
    """Two rulers would let the compiler reserve one box and the lint another."""
    for text in ('R10', '17.8k 1% TH', 'PC817X2NIP0F', 'EE16_3+3_V02', '', 'ä'):
        assert drawlint.text_width(text) == pytest.approx(
            textmetrics.render_width(text), abs=1e-9
        )


def test_the_render_ruler_reproduces_the_boxes_the_render_drew():
    """Measured boxes on the 145e render, to the unit."""
    assert drawlint.text_width('R10') == pytest.approx(18.34, abs=0.01)
    assert drawlint.text_width('17.8k 1% TH') == pytest.approx(57.8, abs=0.05)
    assert drawlint.text_width('PC817X2NIP0F') == pytest.approx(71.14, abs=0.05)


# --------------------------------------- 2. where the host draws a net name

#: ``(wire points, net)`` -> the anchor the host drew the name at, read out of
#: `outputs/145e/render_P1.svg` (`x=`/`y=`, y negated) on 2026-10-10.
MEASURED_ANCHORS = {
    ('CLAMP_B', ((80, 680), (80, 640), (120, 640))): (80.0, 660.0),
    ('CLAMP', ((40, 680), (40, 790), (100, 790))): (40.0, 735.0),
    ('SW', ((160, 730), (165, 730), (165, 560), (200, 560))): (165.0, 645.0),
    ('SEC_SW', ((240, 730), (320, 730), (320, 790))): (280.0, 730.0),
    ('LED_A', ((780, 200), (780, 275), (795, 275))): (780.0, 237.5),
    ('GATE', ((170, 540), (160, 540))): (165.0, 540.0),
}


@pytest.mark.parametrize('measured', sorted(MEASURED_ANCHORS, key=lambda item: item[0]))
def test_the_name_anchor_is_the_midpoint_of_the_longest_run(measured):
    net, points = measured
    box = textmetrics.wire_name_box(points, net)
    assert box is not None
    assert (box[0], box[1]) == MEASURED_ANCHORS[measured]


def test_a_vertical_run_gets_a_vertical_row_and_a_horizontal_one_a_flat_row():
    vertical = textmetrics.wire_name_box(((80, 680), (80, 640), (120, 640)), 'CLAMP_B')
    flat = textmetrics.wire_name_box(((80, 640), (120, 640)), 'CLAMP_B')
    width = textmetrics.render_width('CLAMP_B')
    # vertical: 10 wide, as long as the name, running down from the anchor
    assert vertical == (80.0, 660.0, 90.0, 660.0 + width)
    # horizontal: as wide as the name, 10 tall
    assert flat == (100.0, 640.0, 100.0 + width, 650.0)


def test_a_split_run_is_still_one_run():
    """The host splits CLAMP's vertical at C5.1 (40, 740); the name's midpoint is
    still the whole 110-unit run's."""
    assert textmetrics.wire_name_box(
        ((40, 680), (40, 740), (40, 790), (100, 790)), 'CLAMP'
    )[:2] == (40.0, 735.0)


def test_the_one_wire_this_model_does_not_explain_is_named():
    """FB_SENSE is anchored at the arc-length midpoint; the model says so."""
    points = ((580, 305), (605, 305), (605, 360), (845, 360), (845, 305))
    assert textmetrics.wire_name_box(points, 'FB_SENSE')[:2] == (725.0, 360.0)
    assert textmetrics.WIRE_NAME_MODEL_EXCEPTION == 'FB_SENSE'


def test_a_wire_with_no_run_has_no_name_row():
    assert textmetrics.wire_name_box((), 'X') is None
    assert textmetrics.wire_name_box(((5, 5),), 'X') is None


# ------------------------------- 3. a reported wire's drawn segments

def _wire_state(*points):
    return {'Net': 'N', 'Line': [c for point in points for c in point]}


def test_an_even_point_list_is_read_pairwise_not_as_a_path():
    """The host's own shape: two runs meeting at a corner, the fourth vertex
    retracing the first. The path reading would add a phantom diagonal."""
    state = _wire_state((80, 640), (80, 680), (120, 640), (80, 640))
    assert drawlint._wire_segments(state) == [
        ((80.0, 640.0), (80.0, 680.0)),
        ((120.0, 640.0), (80.0, 640.0)),
    ]
    wire = drawlint.Wire('w', state)
    assert wire.segments == drawlint._wire_segments(state)


def test_an_odd_point_list_keeps_the_path_reading_the_fixtures_use():
    state = _wire_state((100, 250), (100, 300), (150, 300))
    assert drawlint._wire_segments(state) == [
        ((100.0, 250.0), (100.0, 300.0)),
        ((100.0, 300.0), (150.0, 300.0)),
    ]


# ------------------------------- 4. a part's own text, and the name stub

def test_a_symbol_that_declares_its_rows_places_them_where_it_says():
    profile = _profile('R0603')
    assert [(t.kind, t.x, t.y) for t in profile.texts] == [
        ('reference', -10.0, 5.0), ('value', -10.0, -15.0),
    ]
    ctx = SimpleNamespace(
        circuit=SimpleNamespace(
            part=lambda part_id: SimpleNamespace(value='75k 1% 0603')
        )
    )
    rows = drawcompiler._declared_rows(
        ctx, 'R15', profile, SymbolPose(rotation=0, mirror=False), (190.0, 640.0)
    )
    width = textmetrics.render_width('R15')
    assert rows == [
        ('reference', 'R15', (180.0, 645.0, 180.0 + width, 655.0)),
        (
            'value', '75k 1% 0603',
            (180.0, 625.0, 180.0 + textmetrics.render_width('75k 1% 0603'), 635.0),
        ),
    ]


def test_a_turned_part_carries_its_rows_round_with_it():
    profile = _profile('SMD-4-PC817')
    ctx = SimpleNamespace(
        circuit=SimpleNamespace(
            part=lambda part_id: SimpleNamespace(value='PC817X2NIP0F')
        )
    )
    # U5 is locked at 180 in this drawing, and the host drew it at (725, 260)
    rows = drawcompiler._declared_rows(
        ctx, 'U5', profile, SymbolPose(rotation=180, mirror=False), (750.0, 285.0)
    )
    assert rows[1][2][:2] == (725.0, 260.0)


def test_a_symbol_without_declared_rows_declares_nothing():
    """Every profile written before 146 — the caller keeps its own ladder."""
    profile = _profile('PWR-GND')
    assert profile.texts == []
    ctx = SimpleNamespace(
        circuit=SimpleNamespace(part=lambda part_id: SimpleNamespace(value='x'))
    )
    assert drawcompiler._declared_rows(
        ctx, 'F1', profile, SymbolPose(), (0.0, 0.0)
    ) == []


def test_a_stub_whose_name_row_lands_on_its_own_symbol_is_not_taken():
    """Q1's GATE stub: 10 units long, the host draws `GATE` from x=165 to 192.2,
    and Q1's body starts at x=180 (145e). The next rung steps out of the way."""
    label = SimpleNamespace(net='GATE', x=170.0, y=540.0)
    body = ('the drawn body of Q1', (180.0, 530.0, 200.0, 550.0))
    short = drawapply._StubRun(
        points=((170.0, 540.0), (160.0, 540.0)), side=(-1.0, 0.0),
        shape='left 10', family='straight left',
    )
    long = drawapply._StubRun(
        points=((170.0, 540.0), (130.0, 540.0)), side=(-1.0, 0.0),
        shape='left 40', family='straight left',
    )
    assert drawapply._name_row_clash(label, short, (body,)) is not None
    assert drawapply._name_row_clash(label, long, (body,)) is None


def test_a_stub_with_no_owner_has_nothing_to_clash_with():
    label = SimpleNamespace(net='GATE', x=170.0, y=540.0)
    short = drawapply._StubRun(
        points=((170.0, 540.0), (160.0, 540.0)), side=(-1.0, 0.0),
        shape='left 10', family='straight left',
    )
    assert drawapply._name_row_clash(label, short, ()) is None


def test_the_stub_chooser_steps_out_past_its_own_symbol():
    """The whole point of the check: the same Q1/GATE fixture through the
    chooser picks the 40-unit rung (the first whose name row clears the
    transistor), where the pre-146 order answered `left 10`."""
    label = SimpleNamespace(
        net='GATE', x=170.0, y=540.0, part_id='Q1',
        bbox=(130.0, 535.5, 162.0, 544.5),
    )
    built = drawapply._Built(
        label_owner={'Q1': [('the drawn body of Q1', (180.0, 530.0, 200.0, 550.0))]}
    )
    stub, blockers = drawapply._place_label_stub(label, built, {}, ())
    assert stub is not None, blockers
    assert stub[-1] == (130.0, 540.0)
