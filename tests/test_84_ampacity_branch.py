"""Issue #84: ``pcb-track-ampacity`` reads a **branch** off load-bearing copper.

The issue (岳, 2026-10-22, 审查线) is a pair of false positives on a real board:
``IRbus`` carries its main current on a 30 mil trunk plus two layers of pour and
reaches four 100 Ω shunt resistors' sense taps along 27 segments of 10 mil, and
``ACN`` the same with a pour whose cross-section is ~125 mil and five 10 mil
zero-crossing sense lines — and the rule, reading one declared current per net
against the layer's **narrowest** track, called those sense lines overloads (four
ERRORs, two nets × two layers). Its own words for why: the contract states one
current for the whole net and the rule had no notion of a branch.

What this file pins, in the order the rule decides it:

* the shape issue #84 reports — pour and/or wide trunk + narrow taps → **no
  ERROR**, one INFO per width class per layer **naming every segment** (width,
  count, total length, coordinate span, endpoints) and saying which copper the
  current is more likely to be in;
* the bar, both halves of it and both sides of the boundary —
  ``max(3 × narrowest segment, width the current needs)``, so 30.0 mil
  load-bears a 10 mil tap at 1.88 A (needs 28.2) while 29.9 does not, and an
  inner layer, which needs 140.0 mil for the same current, is not load-borne by
  a 100 mil trunk;
* the pour half of the bar: a pour whose **mean width** (area over the pour's
  longest extent) clears the bar counts, a sliver pour does not, and a net with
  no tracks at all stays the UNKNOWN it always was — 「pad and pour area is a
  different conductor model」 is why that row exists, and #84 does not turn it
  into silence;
* the bookkeeping the report needs: one row per width class (10 and 12 mil taps
  are two rows, not one average), one row per layer, every member of a two-name
  conductor named in the row, and the ``target.measurement`` still the measured
  width on a named layer (钉 3);
* the negative half of the issue's evidence: **margin is still silence**, so a
  layer whose copper already passes produces no row, branch or not.

Every number below is the issue's or is derived longhand from
:func:`~boardwise.rules.pcb.ipc.required_width_mil` in the test that asserts it:
1.88 A external needs **28.2** mil, 2.87 A needs **50.6**, 3 A needs **53.8**
outer / **140.0** inner.

Synthetic boards only — the real one is a company board and is not in the
repository (its archive was reported in the issue, not committed).
"""

from __future__ import annotations

from boardwise.core.designintent import DesignIntent, IntentSignal
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    PourShape,
    TrackSegment,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.ipc import (
    BRANCH_WIDTH_RATIO,
    TrackAmpacity,
    required_width_mil,
)

#: ``1``/``2`` are the external faces and ``16`` an inner signal layer, the same
#: vocabulary ``test_126c`` uses — the distinction is what picks ``OUTER_K``
#: (0.048) or ``INNER_K`` (0.024) and therefore the bar.
LAYERS = {
    1: LayerInfo(layer_id=1, name="Top Layer", layer_type="TOP"),
    2: LayerInfo(layer_id=2, name="Bottom Layer", layer_type="BOTTOM"),
    16: LayerInfo(layer_id=16, name="Inner2", layer_type="SIGNAL"),
}


def _track(
    ident: str,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: float,
    net: str = "IRbus",
    layer: int = 1,
) -> TrackSegment:
    """One segment of stated width on a stated layer, at stated coordinates."""
    return TrackSegment(
        id=ident,
        net=net,
        layer_id=layer,
        start=Point(x1, y1),
        end=Point(x2, y2),
        width=width,
    )


def _pour(
    ident: str,
    *,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    net: str = "IRbus",
    layer: int = 1,
) -> PourShape:
    """One axis-aligned pour rectangle, so its mean width is a subtraction.

    An axis-aligned rectangle is the case where ``area / longest side`` is **the
    width** rather than an average, which is what lets these tests state the
    pour's reading as an exact number (see
    :attr:`~boardwise.core.measure.LayerCopper.pour_mean_width`).
    """
    return PourShape(
        id=ident,
        net=net,
        layer_id=layer,
        kind="fill",
        points=[
            Point(x0, y0),
            Point(x1, y0),
            Point(x1, y1),
            Point(x0, y1),
        ],
    )


def _pad(component: str, pin: str, *, x: float, y: float, net: str) -> PadGeometry:
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        footprint_layer_id=1,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _board(
    tracks: list[TrackSegment],
    pours: list[PourShape] = (),
    pads: list[PadGeometry] = (),
    *,
    layers=None,
) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        layers=dict(layers if layers is not None else LAYERS),
        components=[
            ComponentPlacement(id="c-J1", designator="J1", x=0.0, y=0.0, layer_id=1)
        ],
        pads=list(pads),
        tracks=list(tracks),
        pours=list(pours),
    )


def _ctx(board: BoardGeometry, amps: str, *, net: str = "IRbus") -> PcbReviewContext:
    return PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=None,
        intent=DesignIntent(
            signals=[IntentSignal(net=net, slots={"range": amps})], rails=[]
        ),
        module_of={},
    )


def _errors(findings) -> list:
    return [f for f in findings if f.severity == "ERROR"]


def _infos(findings) -> list:
    return [f for f in findings if f.severity == "INFO"]


#: The 实板 A ``IRbus`` shape, on one layer: a 30 mil trunk from (0, 100) to
#: (1200, 100), three 10 mil sense taps running 500 mil "up" off it, and a
#: 3000 × 500 mil pour the whole thing sits on (mean width **500.0** mil, well
#: clear of the 30.0 mil bar at 1.88 A).
def _real_board_shape() -> BoardGeometry:
    return _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=30.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
            _track("s2", x1=300.0, y1=100.0, x2=300.0, y2=600.0, width=10.0),
            _track("s3", x1=500.0, y1=100.0, x2=500.0, y2=600.0, width=10.0),
        ],
        [_pour("p1", x0=0.0, y0=0.0, x1=3000.0, y1=500.0)],
    )


# ---------------------------------------------------------------------------
# the shape the issue reports
# ---------------------------------------------------------------------------


def test_the_real_board_shape_is_one_unknown_that_names_every_tap():
    """Pour + 30 mil trunk + three 10 mil taps at 1.88 A: no ERROR, one named row.

    This is issue #84's ``IRbus`` arithmetic, done out: 1.88 A external needs
    ``required_width_mil(1.88)`` = **28.2475 → 28.2** mil, the taps are 10 mil,
    and the old rule fired an ERROR on that comparison. The layer also carries
    load-bearing copper — the trunk at 30.0 mil clears the bar
    ``max(3 × 10, 28.2475) = 30.0``, and the pour's mean width is 500.0 mil —
    so the row is an **UNKNOWN**: it names the three segments (class width,
    count, total length, span, longest segment and its endpoints), states the
    required width and the factor, and asks the reader to confirm which segments
    are in the current path.

    The assertions below are the shape of that row rather than its prose: the
    severity (INFO, not ERROR), the structured reading (钉 3: kind ``width``,
    the class's width, the layer it was read on), the two numbers a reviewer
    needs to disagree (28.2 required against 10.0 measured), the three ids, and
    the 「it is a branch」 clause naming the wider copper.
    """
    findings = TrackAmpacity().check(_ctx(_real_board_shape(), "1.88A"))
    assert _errors(findings) == [], [f.message for f in findings]
    infos = _infos(findings)
    assert len(infos) == 1, [f.message for f in findings]
    row = infos[0]
    assert "issue #84" in row.message
    assert row.rule_id == "pcb-track-ampacity"
    assert row.target.net_refs == ["IRbus"]
    assert row.target.measurement == {
        "kind": "width",
        "value": 10.0,
        "unit": "mil",
        "layer_ids": [1],
    }
    assert "1.88 A" in row.message
    assert f"{required_width_mil(1.88):.1f}" in row.message, "28.2 mil is the bar"
    assert "2.8x under" in row.message, "28.2 / 10.0 = 2.8"
    assert "3 segment(s) at 10.0 mil" in row.message
    assert "(100.0, 100.0) to (500.0, 600.0)" in row.message, "the span is named"
    assert "1 pour polygon(s)" in row.message and "500.0 mil mean width" in row.message
    assert "Confirm which segments are in the current path" in row.message
    # Every segment is named with its own numbers, in the evidence.
    joined = " | ".join(row.evidence)
    for ident in ("s1", "s2", "s3"):
        assert f"segment {ident!r}" in joined
    assert "segment 's3': 10.0000 mil, 500.00 mil, (500.0, 100.0) to (500.0, 600.0)" in joined
    assert "1500.00 mil total" in joined, "500 + 500 + 500"
    assert "required width 28.2475 mil for 1.88 A" in joined
    assert "the bar is max(3 × narrowest, required) = 30.0000 mil" in joined


def test_the_gate_opens_at_exactly_three_times_the_narrowest_segment():
    """The bar's ratio half, pinned on both sides of the line.

    10 mil taps at 1.88 A: the bar is ``max(3 × 10, 28.2475)`` = **30.0** mil,
    which the required width alone would not reach (28.2 < 30.0) — so it is the
    ratio that decides here, and the two boards are stated at the line and one
    tenth of a mil under it:

    * a **30.0** mil trunk is load-bearing → the taps are an UNKNOWN row;
    * a **29.9** mil trunk is not → the row stays the ERROR it always was, with
      the trunk's 29.9 mil copper named in the layer's evidence.

    The margin of one tenth is deliberate: the comparison is ``>=`` with the same
    1e-9 epsilon the width comparison uses, so the boundary belongs to the branch
    reading and a board that lands exactly on it does not flip on float noise.
    """
    at_the_line = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=30.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
        ]
    )
    findings = TrackAmpacity().check(_ctx(at_the_line, "1.88A"))
    assert _errors(findings) == [], [f.message for f in findings]
    assert len(_infos(findings)) == 1
    assert "1 track(s) of 30.0 mil on layer 1" in _infos(findings)[0].message

    just_under = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=29.9),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
        ]
    )
    findings = TrackAmpacity().check(_ctx(just_under, "1.88A"))
    assert BRANCH_WIDTH_RATIO == 3.0
    errors = _errors(findings)
    assert len(errors) == 1, [f.message for f in findings]
    assert errors[0].target.measurement == {
        "kind": "width",
        "value": 10.0,
        "unit": "mil",
        "layer_ids": [1],
    }
    assert f"{required_width_mil(1.88):.1f}" in errors[0].message
    assert "issue #84" not in errors[0].message, "an ERROR is not the branch row"


def test_a_pour_carrying_the_current_is_enough_without_a_wide_trunk():
    """The ``ACN`` half of the issue: every track is 10 mil, the pour is the copper.

    2.87 A external needs ``required_width_mil(2.87)`` = **50.6** mil (the
    issue's own number for ``ACN``), so the taps are undersized by construction
    and no track is wide enough to be a trunk — the reading rests on the pour.
    An axis-aligned 3000 × 125 mil pour has ``area / longest side`` = **125.0**
    mil mean width, well over the ``max(30, 50.6)`` bar, so the five taps come
    out as one UNKNOWN naming them, not as five ERRORs.

    This is also the pin that the **bar** is not merely a ratio: the pour reading
    is compared against the width the current needs, so a pour that is much
    wider than the taps but still too narrow for the current does not open the
    gate (the next test).
    """
    board = _board(
        [
            _track(
                f"s{i}", x1=100.0 * i, y1=100.0, x2=100.0 * i, y2=600.0, width=10.0
            )
            for i in range(1, 6)
        ],
        [_pour("p1", x0=0.0, y0=0.0, x1=3000.0, y1=125.0)],
    )
    findings = TrackAmpacity().check(_ctx(board, "2.87A"))
    assert _errors(findings) == [], [f.message for f in findings]
    rows = [f for f in findings if "issue #84" in f.message]
    assert len(rows) == 1, [f.message for f in findings]
    row = rows[0]
    assert "5 segment(s) at 10.0 mil" in row.message
    assert f"{required_width_mil(2.87):.1f}" in row.message, "50.6 mil is the bar"
    assert "125.0 mil mean width" in row.message
    assert "5.1x under" in row.message, "50.6 / 10.0 = 5.1"
    assert "375000 sq mil" in " | ".join(row.evidence), "3000 × 125 mil of copper"


def test_a_sliver_pour_is_not_load_bearing_and_the_row_stays_an_error():
    """A pour *presence* is not a pour *conductor*: the mean width has to clear the bar.

    Same 10 mil taps and the same declaration as the test above, but the pour is
    a 500 × 10 mil sliver: ``area / longest side`` = **10.0** mil mean width
    against a 50.6 mil bar, so nothing on this conductor load-bears the current
    and the layer's narrowest track is judged — **ERROR**, one per layer, as
    before #84.
    """
    board = _board(
        [
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
            _track("s2", x1=300.0, y1=100.0, x2=300.0, y2=600.0, width=10.0),
        ],
        [_pour("p1", x0=0.0, y0=0.0, x1=500.0, y1=10.0)],
    )
    findings = TrackAmpacity().check(_ctx(board, "2.87A"))
    assert len(findings) == 1, [f.message for f in findings]
    assert findings[0].severity == "ERROR"
    assert findings[0].target.measurement["value"] == 10.0
    assert f"{required_width_mil(2.87):.1f}" in findings[0].message


def test_an_inner_layer_is_not_load_borne_by_copper_that_is_too_narrow_for_it():
    """The bar's ``needed`` half on an inner layer, where the current needs 140.0 mil.

    3 A internal needs ``required_width_mil(3.0, inner=True)`` = **140.0** mil
    (the ROBOT anchor's own number), so the bar on layer 16 is ``max(3 × 10,
    140.0)`` = 140.0 mil. A 100 mil trunk there is *wide* — ten times the 10 mil
    tap — and still cannot be said to carry the current itself, so the branch
    reading does not apply and the layer keeps its **ERROR**. Without the
    ``needed`` half of the bar this board would be silently downgraded to an
    UNKNOWN on the ratio alone, which is the direction that hides a real
    undersized conductor.
    """
    board = _board(
        [
            _track(
                "t1",
                x1=0.0,
                y1=100.0,
                x2=1200.0,
                y2=100.0,
                width=100.0,
                layer=16,
            ),
            _track(
                "s1",
                x1=100.0,
                y1=100.0,
                x2=100.0,
                y2=600.0,
                width=10.0,
                layer=16,
            ),
        ]
    )
    findings = TrackAmpacity().check(_ctx(board, "3A"))
    assert len(findings) == 1, [f.message for f in findings]
    assert findings[0].severity == "ERROR"
    assert findings[0].target.measurement["layer_ids"] == [16]
    assert "internal" in findings[0].message
    assert f"{required_width_mil(3.0, inner=True):.1f}" in findings[0].message


# ---------------------------------------------------------------------------
# the rows the report gets: one per class, one per layer, members named
# ---------------------------------------------------------------------------


def test_each_width_class_gets_its_own_row_narrowest_first():
    """Two branch design rules are two rows, not one average.

    The same pour-and-trunk board, with taps at **10** and **12** mil: the rule
    reports each level separately so a reviewer can see that the 10 mil class is
    the narrower one — one row would have to average 10 and 12 into a number the
    board does not state anywhere. Order is by width, so the report is
    deterministic.
    """
    board = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=30.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
            _track("s2", x1=200.0, y1=100.0, x2=200.0, y2=600.0, width=12.0),
            _track("s3", x1=300.0, y1=100.0, x2=300.0, y2=600.0, width=10.0),
        ],
        [_pour("p1", x0=0.0, y0=0.0, x1=3000.0, y1=500.0)],
    )
    findings = TrackAmpacity().check(_ctx(board, "1.88A"))
    assert _errors(findings) == [], [f.message for f in findings]
    rows = [f for f in findings if "issue #84" in f.message]
    assert [f.target.measurement["value"] for f in rows] == [10.0, 12.0]
    assert "2 segment(s) at 10.0 mil" in rows[0].message
    assert "1 segment(s) at 12.0 mil" in rows[1].message
    # The message names the class's longest segment (ties by id, so 's3' over
    # 's1'); the evidence lists every segment of the class.
    assert "'s3'" in rows[0].message
    assert "'s2'" in rows[1].message
    joined = " | ".join(rows[0].evidence)
    assert "segment 's1'" in joined and "segment 's3'" in joined


def test_each_layer_gets_its_own_row():
    """Two layers of taps are two rows, each naming its own layer.

    实板 A's ``IRbus`` false positive was four ERRORs on two nets — the count
    after #84 is the same four, INFO rather than ERROR, and each names the layer
    it was read on (钉 3). Here the taps are on layers 1 and 2 with a pour on
    each, so the rows are ``layer_ids`` ``[1]`` and ``[2]``.
    """
    board = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=30.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=10.0),
            _track(
                "s2",
                x1=100.0,
                y1=100.0,
                x2=100.0,
                y2=600.0,
                width=10.0,
                layer=2,
            ),
        ],
        [
            _pour("p1", x0=0.0, y0=0.0, x1=3000.0, y1=500.0, layer=1),
            _pour("p2", x0=0.0, y0=0.0, x1=3000.0, y1=500.0, layer=2),
        ],
    )
    findings = TrackAmpacity().check(_ctx(board, "1.88A"))
    assert _errors(findings) == [], [f.message for f in findings]
    rows = [f for f in findings if "issue #84" in f.message]
    assert [f.target.measurement["layer_ids"] for f in rows] == [[1], [2]]
    assert "layer 1 (Top Layer)" in rows[0].message
    assert "layer 2 (Bottom Layer)" in rows[1].message


def test_a_branch_row_names_every_member_of_a_two_name_conductor():
    """The closure's names are in the branch row too, not only in the old ERROR.

    ``IRbus`` (60 mil, declared) and ``IRBUS`` (10 mil) are one conductor — the
    516 A2 closure — and 60 mil clears the bar (``max(3 × 10, 53.8) = 53.8`` for
    the declared 3 A), so the row is the branch row: the 实板 A shape with both
    names, on the same reading that used to make it an ERROR. The undeclared
    name still gets its standing INFO, so the report has exactly two INFO rows
    and no ERROR.
    """
    board = _board(
        [
            _track("a", x1=0.0, y1=0.0, x2=100.0, y2=0.0, width=60.0, net="IRbus"),
            _track("b", x1=50.0, y1=0.0, x2=150.0, y2=0.0, width=10.0, net="IRBUS"),
        ]
    )
    ctx = PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=None,
        intent=DesignIntent(
            signals=[IntentSignal(net="IRbus", slots={"range": "±3A"})], rails=[]
        ),
        module_of={},
    )
    findings = TrackAmpacity().check(ctx)
    assert _errors(findings) == [], [f.message for f in findings]
    assert sorted(f.severity for f in findings) == ["INFO", "INFO"]
    rows = [f for f in findings if "issue #84" in f.message]
    assert len(rows) == 1
    row = rows[0]
    assert "one conductor, 2 names" in row.message
    assert "'IRbus'" in row.message and "'IRBUS'" in row.message
    assert row.target.net_refs == ["IRBUS", "IRbus"]
    assert "one conductor: 'IRBUS' ≡ 'IRbus'" in " | ".join(row.evidence)
    untouched = [f for f in findings if "issue #84" not in f.message]
    assert len(untouched) == 1 and "unnamed net(s)" in untouched[0].message


# ---------------------------------------------------------------------------
# what did *not* change
# ---------------------------------------------------------------------------


def test_a_net_carrying_no_tracks_is_still_unknown_not_silent():
    """Pads and a pour, no track: the same UNKNOWN the rule always produced.

    #84 widened 「a pour is a different conductor model」 to cover a pour that
    carries a net's current *beside* its tracks; it did not make the absence of
    a track into a pass. A net declared at 3 A and carried on this document by a
    pour and one pad has no width to judge, and the row says which fact is
    missing rather than reporting silence or a made-up number.
    """
    board = _board(
        [],
        [_pour("p1", x0=0.0, y0=0.0, x1=2000.0, y1=2000.0)],
        [_pad("J1", "1", x=0.0, y=0.0, net="IRbus")],
    )
    findings = TrackAmpacity().check(_ctx(board, "3A"))
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "cannot be checked for ampacity" in findings[0].message
    assert "pads and pours only" in findings[0].message
    assert "issue #84" not in findings[0].message


def test_margin_is_still_silence_and_a_branch_is_only_an_undersized_segment():
    """Two ways to be silent, both unchanged.

    * the layer's narrowest track already carries the current (**40** mil
      against 28.2) → no row at all, even though a 130 mil trunk stands beside
      it; the branch reading is about segments the layer would otherwise
      *condemn*, not about finding copper to report;
    * the whole conductor is over-provisioned (every track 60 mil) → no row,
      which is the 526-era rule 「margin is not a defect」 unchanged.

    A rule that reported a branch on a passing layer would be inventing a work
    order for a conductor with nothing wrong with it, which is the failure mode
    the module's own docstring calls out: rows that mean nothing train readers to
    ignore the rows that do.
    """
    passing = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=130.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=40.0),
        ]
    )
    assert TrackAmpacity().check(_ctx(passing, "1.88A")) == []
    over_provisioned = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=60.0),
            _track("s1", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=60.0),
        ]
    )
    assert TrackAmpacity().check(_ctx(over_provisioned, "3A")) == []


def test_a_zero_width_segment_is_reported_rather_than_dividing_by_it():
    """A malformed record must not take the whole rule down with it.

    A segment whose record states 0.0 mil is narrower than any requirement, so
    the factor the branch row quotes would be a division by zero — and a rule
    that raises is skipped by the runner, which would drop **every** row this
    board has, not just this one. The row states the fact instead.
    """
    board = _board(
        [
            _track("t1", x1=0.0, y1=100.0, x2=1200.0, y2=100.0, width=30.0),
            _track("z0", x1=100.0, y1=100.0, x2=100.0, y2=600.0, width=0.0),
        ]
    )
    findings = TrackAmpacity().check(_ctx(board, "1.88A"))
    assert _errors(findings) == [], [f.message for f in findings]
    rows = [f for f in findings if "issue #84" in f.message]
    assert len(rows) == 1, [f.message for f in findings]
    assert rows[0].target.measurement["value"] == 0.0
    assert "0.0 mil width" in rows[0].message
    assert "there is no copper there to carry anything" in rows[0].message
