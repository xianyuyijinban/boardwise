"""R2-1 fixA: the three ways this rule could go quiet, disclosed.

The keepout rule passed review with three gaps about *what it does not say*
(the reviewer's low findings #2–#4):

1. a keepout whose ``prohibitType`` mixes a known word with an unknown one
   produced a ``WARN`` that never mentioned the unknown word — a reader counting
   「1 violation」 could not tell that part of the keepout was never judged;
2. a keepout whose only word is ``PLANE`` (or whose type list is empty) produced
   **no row at all**, silently, even with copper inside it;
3. a missing / empty ``regionType`` is read as ``PROHIBIT``, a conservative
   default that was nowhere written down.

Each is pinned here on a hand-built board, and each has an obvious mutation:
delete the disclosure and the matching test goes red.
"""

from __future__ import annotations

from boardwise.core.geometry import (
    BoardGeometry,
    LayerInfo,
    Point,
    PourShape,
    ProhibitRegion,
    TrackSegment,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb import keepout as keepout_module
from boardwise.rules.pcb.keepout import KeepoutViolation

RULE = KeepoutViolation()


def _board(**elements) -> BoardGeometry:
    board = BoardGeometry(layers={1: LayerInfo(1, "Top Layer", "TOP"), 2: LayerInfo(2, "Bottom Layer", "BOTTOM")})
    for key, value in elements.items():
        setattr(board, key, value)
    return board


def _region(words, *, region_type="PROHIBIT", layer=1, rid="k1"):
    return ProhibitRegion(
        id=rid, name="PROHIBIT", layer_id=layer, region_type=region_type,
        prohibit_types=list(words), points=[Point(0.0, 0.0)], radius=50.0,
    )


def _track(layer=1) -> TrackSegment:
    return TrackSegment(id="t1", net="SIG", layer_id=layer, start=Point(-100, 0), end=Point(100, 0), width=10)


def _run(board):
    return RULE.check(PcbReviewContext(board=board, board_title="PCB1"))


def _pour():
    square = [Point(-300, -300), Point(300, -300), Point(300, 300), Point(-300, 300)]
    return PourShape(id="p", net="GND", layer_id=1, kind="poured", points=square, rings=[square])


# ---------------------------------------------------------------------------
# 1. mixed known + unknown words: the WARN has to say the unknown part is not
#    judged and its meaning is uncertain
# ---------------------------------------------------------------------------


def test_a_mixed_word_keepout_says_the_unknown_word_is_not_judged():
    findings = _run(_board(
        tracks=[_track()],
        pours=[_pour()],
        prohibit_regions=[_region(["COPPER", "WIRE"])],
    ))
    assert len(findings) == 1 and findings[0].severity == "WARN"
    message = findings[0].message
    assert "不确定" in message, "the unknown word's meaning is uncertain and the row must say so"
    assert "WIRE" in message and "不判" in message
    assert any("unknown prohibitType words (meaning uncertain" in line for line in findings[0].evidence)


def test_a_known_word_alone_says_nothing_about_uncertainty():
    """The disclosure is not blanket noise: a purely-known keepout reads as
    before."""
    findings = _run(_board(pours=[_pour()], prohibit_regions=[_region(["COPPER"])]))
    assert len(findings) == 1 and "不确定" not in findings[0].message


# ---------------------------------------------------------------------------
# 2. PLANE-only (and an empty type list): a row, not silence
# ---------------------------------------------------------------------------


def test_a_plane_only_keepout_is_named_as_not_judged():
    findings = _run(_board(tracks=[_track()], prohibit_regions=[_region(["PLANE"])]))
    assert len(findings) == 1, "silence was the finding: it must produce a row"
    finding = findings[0]
    assert finding.severity == "INFO"
    assert "PLANE" in finding.message and "未判" in finding.message
    assert "t1" in finding.message, "the copper it is being silent about is listed"
    assert any("not judged" in line and "PLANE" in line for line in finding.evidence)


def test_a_keepout_with_no_type_at_all_is_named_too():
    findings = _run(_board(tracks=[_track()], prohibit_regions=[_region([])]))
    assert len(findings) == 1 and findings[0].severity == "INFO"
    assert "未判" in findings[0].message and "prohibitType 为空" in findings[0].message


def test_a_plane_only_keepout_with_nothing_inside_stays_silent():
    """Same gate as the unknown-word row: nothing inside, nothing to say."""
    assert _run(_board(prohibit_regions=[_region(["PLANE"])])) == []


def test_a_plane_keepout_beside_a_judged_word_keeps_the_warn_it_had():
    findings = _run(_board(tracks=[_track()], prohibit_regions=[_region(["TRACK", "PLANE"])]))
    assert len(findings) == 1 and findings[0].severity == "WARN"
    assert any("PLANE" in line and "not judged" in line for line in findings[0].evidence)


# ---------------------------------------------------------------------------
# 3. a missing / empty regionType is read as PROHIBIT, and said out loud
# ---------------------------------------------------------------------------


def test_a_missing_region_type_is_read_as_prohibit_and_the_row_says_so():
    findings = _run(_board(tracks=[_track()], prohibit_regions=[_region(["TRACK"], region_type="")]))
    assert len(findings) == 1 and findings[0].severity == "WARN"
    assert any("no regionType" in line and "PROHIBIT" in line for line in findings[0].evidence), (
        "the conservative default has to be visible on the row that applies it"
    )


def test_a_stated_region_type_does_not_get_that_note():
    findings = _run(_board(tracks=[_track()], prohibit_regions=[_region(["TRACK"], region_type="PROHIBIT")]))
    assert len(findings) == 1
    assert not any("no regionType" in line for line in findings[0].evidence)


def test_the_default_is_documented_where_the_rule_explains_itself():
    """The docstring is part of the contract here: the review asked for the
    default to be written down, not only applied."""
    text = keepout_module.__doc__ or ""
    assert "regionType" in text and "PROHIBIT" in text and "default" in text
