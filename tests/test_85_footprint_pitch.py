"""Issue #85: a footprint's own pad pitch is not a routing item.

``pcb-voltage-spacing`` judged whichever pair of two nets came closest, and the
closest pair can be **one component's own two pads** — pin 1 on ``V`` against
pin 2 on ``GND`` on a 50 mil-pitch SOIC. That distance is the footprint's pad
pitch: the part's selection fixed it and no routing change can move it, so a WARN
there is a work order for something the engineer cannot do. On 实板 A (the
anonymised user board) four of ten WARNs were that shape, and two more were a
**track** against one component's pad — those two are routable and must stay
WARNs, which is the contrast this file also pins.

**The rule now reports such a pair without warning about it**, and the number it
grades is the gap a *layout* change could close: the nearest pair outside that
footprint, measured by asking
:func:`~boardwise.core.measure.net_clearance` with ``ignore_within_component``
set. Both numbers ride in the message, the evidence and ``target.measurement``
(岳's second reading of the same issue: 实板 A's ``GND``↔``V`` is **94.5 mil**
at the footprint's own pads and **114.7 mil** outside, and the 114.7 already
satisfies the 100 mil band).

Every expected number below is a subtraction on an axis-aligned fixture, written
out beside the assertion, so this file can be checked against the arithmetic
rather than against the rule:

    one component ``U1`` — pad 1 on ``HV`` at ``y = 0``, pad 2 on ``GND`` at
    ``y = 60``, both 40x40, so the pad-to-pad gap is ``60 - 40`` = **20.0 mil**;
    ``HV`` is declared 311 V by the contract and ``GND`` is 0 V as the board's
    reference, so the band is IPC-2221 B2's ``301–500 V → 100 mil`` and the pair
    violates it by 80 mil.

The library-level half (``net_clearance``'s new flag and the two new
``ClearanceResult`` fields) is pinned in the last three tests, because the rule's
behaviour is only as good as the reading it is built on.
"""

from __future__ import annotations

import pytest

from boardwise.core.designintent import IntentRail
from boardwise.core.geometry import PadGeometry, Point
from boardwise.core.measure import net_clearance
from boardwise.core.model import Pin
from boardwise.rules.pcb.ipc import VoltageSpacing

#: The synthetic helpers are 126c's — same board vocabulary, same hand-derivable
#: coordinates — so this file adds the *pitch* shape rather than a second
#: fixture language for the same two rules.
from test_126c_pcb_ipc_rules import (  # noqa: E402  (after the import block)
    _board,
    _component,
    _contract,
    _ctx,
    _model,
    _pad,
    _track,
)

#: ``HV`` / ``GND`` at 311 V / 0 V: the 300–500 V band of
#: :data:`~boardwise.rules.pcb.ipc.VOLTAGE_SPACING_MIL`, whose number is 100 mil.
#: Chosen over the 4 mil bottom band so a pitch that is a plausible footprint
#: gap (20 mil) is genuinely under the line rather than comfortably above it.
BAND_MIL = 100.0
PITCH_MIL = 20.0


def _pins() -> list[Pin]:
    return [Pin("1", "1", "HV"), Pin("2", "2", "GND")]


def _pitch_pads(*, second_y: float = 60.0) -> list[PadGeometry]:
    """``U1``'s two pads: pad 1 on ``HV`` at y=0, pad 2 on ``GND`` at y=60.

    Both 40x40, so the gap is ``second_y - 40`` — 20 mil for the default.
    """
    return [
        _pad("U1", "1", x=0.0, y=0.0, net="HV"),
        _pad("U1", "2", x=0.0, y=second_y, net="GND"),
    ]


def _spacing(board) -> list:
    """``VoltageSpacing``'s rows for the ``HV``/``GND`` fixture above."""
    model = _model([_component("U1", _pins())])
    intent = _contract(rails=[IntentRail(net="HV", slots={"voltage": "311V"})])
    return VoltageSpacing().check(_ctx(board, model, intent))


# ---------------------------------------------------------------------------
# the four verdicts a same-footprint pair can reach
# ---------------------------------------------------------------------------


def test_the_pitch_pair_is_reported_with_both_numbers_and_downgraded_to_info():
    """The case the issue is about: pitch under the band, external pair over it.

    Geometry (:func:`_pitch_pads` plus two long tracks whose x-ranges all
    overlap the pads', so every gap below is a pure y subtraction):

    * ``HV`` pad 1 at y=0, 40x40 → it occupies y in ``[-20, 20]``;
    * ``GND`` pad 2 at y=60, 40x40 → y in ``[40, 80]``; **gap 20.0 mil**;
    * ``HV`` track on y=-200, 10 mil wide → y in ``[-205, -195]``;
    * ``GND`` track on y=400, 10 mil wide → y in ``[395, 405]``;
    * so the pairs *outside* the footprint measure ``395 - 20 = 375``
      (``HV`` pad to ``GND`` track), ``40 - (-195) = 235`` (``HV`` track to
      ``GND`` pad) and ``395 - (-195) = 590`` (track to track). The closest
      **external** pair is therefore **235.0 mil**, over the 100 mil band.

    Verdict: **INFO**, naming the pair as the footprint's own pitch and both
    numbers — because there is nothing left for a layout change to fix, which is
    exactly what the issue asked the row to say.
    """
    board = _board(
        _pitch_pads(),
        [
            _track("hv-1", x1=-900.0, y1=-200.0, x2=900.0, y2=-200.0,
                   net="HV", width=10.0),
            _track("gnd-1", x1=-900.0, y1=400.0, x2=900.0, y2=400.0,
                   net="GND", width=10.0),
        ],
    )
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO", finding.message
    assert finding.target.net_refs == ["GND", "HV"]
    assert "footprint pitch" in finding.message
    assert f"{PITCH_MIL:.1f} mil" in finding.message
    assert "235.0 mil" in finding.message and f"{BAND_MIL:.1f} mil" in finding.message
    assert "no routing change can move" in finding.message
    # The structured half (#85's third reading): the number rides with the pair
    # it was read from, and `within_one_footprint` is that question answered.
    assert finding.target.measurement == {
        "kind": "clearance", "value": PITCH_MIL, "unit": "mil",
        "element_a": "pad U1.2 on layer 1",
        "element_b": "pad U1.1 on layer 1",
        "component_a": "U1", "component_b": "U1",
        "within_one_footprint": True,
        "external_value": 235.0,
        "external_element_a": "pad U1.2 on layer 1",
        "external_element_b": "track hv-1 on layer 1",
        "external_component_a": "U1", "external_component_b": "",
        "element_a_detail": {"kind": "pad", "component": "U1", "pin": "2", "layers": [1]},
        "element_b_detail": {"kind": "pad", "component": "U1", "pin": "1", "layers": [1]},
        "shared_layer_ids": [1],
        "external_element_a_detail": {"kind": "pad", "component": "U1", "pin": "2", "layers": [1]},
        "external_element_b_detail": {"kind": "track", "component": "", "pin": "", "layers": [1]},
        "external_shared_layer_ids": [1],
    }
    # And the evidence names the second reading by the flag that took it.
    assert any(
        "outside U1" in line and "235.0000 mil" in line for line in finding.evidence
    ), finding.evidence


def test_the_external_pair_is_what_the_warn_is_about_when_it_fails():
    """Same pitch, an external pair **under** the band: INFO becomes WARN again.

    Two short tracks are added — ``HV`` on y=0 and ``GND`` on y=50, both 10 mil
    wide and both spanning x 400..600 — so their edge gap is ``50 - 5 - 5`` =
    **40.0 mil**, under the 100 mil band and **above** the 20 mil pitch (which
    therefore stays the closest pair and stays the one reported).

    The layout item is real, so the row is the WARN it always was — but it now
    says which of the two numbers the work order is about, and the external
    reading is the one that decides the severity.
    """
    board = _board(
        _pitch_pads(),
        [
            _track("hv-1", x1=400.0, y1=0.0, x2=600.0, y2=0.0,
                   net="HV", width=10.0),
            _track("gnd-1", x1=400.0, y1=50.0, x2=600.0, y2=50.0,
                   net="GND", width=10.0),
        ],
    )
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN", finding.message
    assert "footprint pitch" in finding.message
    assert "40.0 mil" in finding.message and "routing item" in finding.message
    assert finding.target.measurement["value"] == PITCH_MIL
    assert finding.target.measurement["within_one_footprint"] is True
    assert finding.target.measurement["external_value"] == 40.0


def test_a_pitch_with_no_measurable_external_pair_stays_info_and_says_so():
    """No external pair at all → INFO, with the reason stated rather than implied.

    ``GND``'s only other copper is a track on **layer 2** while both pads and
    the whole ``HV`` net are on layer 1, so once the footprint's own pair is kept
    out of the measurement there is no same-layer pair left (and the plan-view
    projection that remains — ``U1`` pad 1 against that track — shares no layer,
    which is 127b's drop).

    The row must not become a WARN on the strength of a pair 127b deliberately
    refuses to judge, and it must not fall silent either: the reader gets the
    pitch, the band, and the sentence saying no external spacing is asserted.
    """
    board = _board(
        _pitch_pads(),
        [
            _track("gnd-2", x1=500.0, y1=0.0, x2=700.0, y2=0.0,
                   net="GND", width=10.0, layer_id=2),
        ],
    )
    assert net_clearance(
        board, "HV", "GND", same_layer_only=True, ignore_within_component=True
    ) is None, (
        "the fixture's premise: with the footprint's own pair out, nothing is "
        "measurable"
    )
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO", finding.message
    assert "no external spacing is asserted" in finding.message
    assert "external_value" not in finding.target.measurement
    assert finding.target.measurement["within_one_footprint"] is True


def test_two_pads_of_one_footprint_that_overlap_are_still_a_warn():
    """The guard that keeps the downgrade from swallowing a **short**.

    Pad 2 is moved to y=30, so the two 40x40 pads overlap (pad 1 occupies
    y ``[-20, 20]``, pad 2 ``[10, 50]``): two nets at different voltages whose
    copper intersects on a shared layer are a **short**, and where it sits is
    not a reason to whisper. ``overlapping=True`` and ``distance == 0``, the
    severity stays WARN, and the message still says 「short」.
    """
    board = _board(_pitch_pads(second_y=30.0), [])
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN", finding.message
    assert "this is a short" in finding.message
    assert finding.target.measurement["value"] == 0.0
    assert finding.target.measurement["within_one_footprint"] is True, (
        "the pair is still one footprint's own pads — what changes the severity "
        "is that they touch, not where they are"
    )


def test_a_track_against_a_footprints_pad_is_not_a_footprint_pitch():
    """The other half of 实板 A's ten WARNs: 「走线对同颗焊盘」 stays a WARN.

    ``U1``'s two pads are 560 mil apart (``600 - 40``) so they cannot be the
    closest pair, and a ``GND`` track on y=60 passes ``55 - 20`` = **35.0 mil**
    from ``HV``'s pad 1. The pair has a component on one side only — a track
    belongs to no placement — so no component test can call it internal, and a
    track can be moved. ``within_one_footprint`` is ``False`` and the row is the
    WARN it always was.
    """
    board = _board(
        _pitch_pads(second_y=600.0),
        [
            _track("gnd-1", x1=-200.0, y1=60.0, x2=200.0, y2=60.0,
                   net="GND", width=10.0),
        ],
    )
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN", finding.message
    assert "35.0 mil" in finding.message
    assert "footprint pitch" not in finding.message
    assert finding.target.measurement["within_one_footprint"] is False
    # The rule walks its priced nets in sorted order, so ``GND`` (the track) is
    # the ``a`` side here — the component is on the ``b`` side only.
    assert finding.target.measurement["component_a"] == ""
    assert finding.target.measurement["component_b"] == "U1"
    assert "external_value" not in finding.target.measurement


def test_two_tracks_are_still_a_warn_on_a_board_that_has_a_footprint():
    """The control: having a component on the board changes nothing by itself.

    ``U1``'s pads are 560 mil apart and the closest pair is two long tracks 20
    mil apart centre to centre — ``20 - 5 - 5`` = **10.0 mil** edge to edge. The
    row is a WARN and both components are empty, which is the shape 126c's own
    widened assertion pins for ``HV``/``LV``.
    """
    board = _board(
        _pitch_pads(second_y=600.0),
        [
            _track("hv-1", x1=-900.0, y1=-300.0, x2=900.0, y2=-300.0,
                   net="HV", width=10.0),
            _track("gnd-1", x1=-900.0, y1=-280.0, x2=900.0, y2=-280.0,
                   net="GND", width=10.0),
        ],
    )
    findings = _spacing(board)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN", finding.message
    assert finding.target.measurement == {
        "kind": "clearance", "value": 10.0, "unit": "mil",
        "element_a": "track gnd-1 on layer 1",
        "element_b": "track hv-1 on layer 1",
        "component_a": "", "component_b": "",
        "within_one_footprint": False,
        "element_a_detail": {"kind": "track", "component": "", "pin": "", "layers": [1]},
        "element_b_detail": {"kind": "track", "component": "", "pin": "", "layers": [1]},
        "shared_layer_ids": [1],
    }


# ---------------------------------------------------------------------------
# the reading itself — the flag and the two fields the rule is built on
# ---------------------------------------------------------------------------


def _pitch_and_external() -> tuple:
    """The first fixture, as ``(board, pitch_reading, external_reading)``."""
    board = _board(
        _pitch_pads(),
        [
            _track("hv-1", x1=-900.0, y1=-200.0, x2=900.0, y2=-200.0,
                   net="HV", width=10.0),
            _track("gnd-1", x1=-900.0, y1=400.0, x2=900.0, y2=400.0,
                   net="GND", width=10.0),
        ],
    )
    return (
        board,
        net_clearance(board, "HV", "GND", same_layer_only=True),
        net_clearance(
            board, "HV", "GND",
            same_layer_only=True, ignore_within_component=True,
        ),
    )


def test_net_clearance_names_the_placements_it_measured_between():
    """The two new ``ClearanceResult`` fields, and the pair they describe.

    ``component_a`` / ``component_b`` are the placements the two elements belong
    to — ``"U1"`` / ``"U1"`` here, ``""`` for anything that is not a pad — and
    ``within_one_footprint`` is the question they answer, so a caller does not
    parse a label to ask it.
    """
    _board_, pitch, _external = _pitch_and_external()
    assert pitch.distance == pytest.approx(PITCH_MIL)
    # The call's own argument order names the sides: ``a`` is ``HV``, so the
    # pitch pair is ``U1.1`` / ``U1.2``. (The rule's rows read the other way
    # round because it walks its priced nets in sorted order.)
    assert pitch.element_a == "pad U1.1 on layer 1"
    assert pitch.element_b == "pad U1.2 on layer 1"
    assert (pitch.component_a, pitch.component_b) == ("U1", "U1")
    assert pitch.within_one_footprint is True
    assert pitch.shares_a_layer is True


def test_ignore_within_component_answers_with_the_nearest_external_pair():
    """The flag's whole point: the same board, the number a layout change owns.

    ``HV`` track to ``GND`` pad is ``40 - (-195)`` = **235.0 mil**, and the pair
    is reported as itself — a component on one side only, so
    ``within_one_footprint`` is ``False``.
    """
    _board_, _pitch, external = _pitch_and_external()
    assert external.distance == pytest.approx(235.0)
    assert external.element_a == "track hv-1 on layer 1"
    assert external.element_b == "pad U1.2 on layer 1"
    assert external.component_a == "" and external.component_b == "U1"
    assert external.within_one_footprint is False


def test_the_flag_never_hides_a_track_against_a_pad():
    """A routable pair survives the flag — the half that must not be silenced.

    On the 「track against a footprint's pad」 fixture the closest pair is 35.0
    mil and it is **still 35.0** with the flag set: only a pair with a component
    on *both* sides is dropped, which is what keeps the flag from becoming a
    blanket「ignore anything near a component」.
    """
    board = _board(
        _pitch_pads(second_y=600.0),
        [
            _track("gnd-1", x1=-200.0, y1=60.0, x2=200.0, y2=60.0,
                   net="GND", width=10.0),
        ],
    )
    plain = net_clearance(board, "HV", "GND", same_layer_only=True)
    flagged = net_clearance(
        board, "HV", "GND", same_layer_only=True, ignore_within_component=True
    )
    assert plain.distance == pytest.approx(35.0)
    assert flagged is not None and flagged.distance == pytest.approx(35.0)
    assert flagged.within_one_footprint is False
    assert (flagged.component_a, flagged.component_b) == ("U1", "")


def test_the_empty_and_one_net_edges_never_raise():
    """A board with nothing, and a net against itself: ``None``, not a crash.

    The rule's own guard, and the library's: ``net_clearance`` refuses a
    self-pair and a net with no copper whatever the new flag says, so the flag
    cannot turn a documented ``None`` into an error on a real board.
    """
    empty = _board([], [])
    assert net_clearance(empty, "HV", "GND") is None
    assert net_clearance(
        empty, "HV", "GND", ignore_within_component=True
    ) is None
    board = _board(_pitch_pads(), [])
    assert net_clearance(board, "HV", "HV") is None
    assert net_clearance(
        board, "HV", "HV", ignore_within_component=True
    ) is None
    assert net_clearance(board, "HV", "NOPE") is None


def test_the_fixture_is_the_arithmetic_it_claims():
    """The fixture's own numbers, from the coordinates rather than the rule.

    A hand-check that the 20 mil the whole file turns on is ``60 - 40`` on
    40x40 pads, so a reader can see the fixture was not tuned to an answer.
    """
    pads = _pitch_pads()
    assert [pad.y for pad in pads] == [0.0, 60.0]
    assert all(pad.width == 40.0 and pad.height == 40.0 for pad in pads)
    first, second = pads
    gap = (second.y - second.height / 2) - (first.y + first.height / 2)
    assert gap == PITCH_MIL
    # ... and that the two 10 mil tracks whose gap the first test quotes are the
    # y values its docstring reads: 400 - 5 = 395 down to -200 + 5 = -195.
    assert Point(0.0, 395.0).y - Point(0.0, -195.0).y == 590.0
    assert Point(0.0, 40.0).y - Point(0.0, -195.0).y == 235.0
