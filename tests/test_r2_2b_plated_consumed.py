"""R2-2 fixA: the NPTH reading is *consumed* — ``None`` and ``[]`` never mix.

PR #79 read ``plated`` tri-state and taught :func:`pad_effective_layers` that a
non-plated hole is no barrel. The last link did not hold: a bare mechanical
hole's ``effective_layer_ids`` came back ``[]``, and every consumer
(:func:`boardwise.core.measure._element_layers` above all) read the empty list
as 「the parser has not spoken」 and fell back to the pre-127b derivation — all
copper layers for a pad with a hole. Measured on a synthetic 4-layer board: a
126 x 126 land on a 126 x 126 hole came back as ``[1, 2, 15, 16]``, exactly the
placeholder R2-2 claimed to have removed.

The fix is one sentinel, applied everywhere:

* ``None`` — **nobody has read this pad** (a hand-built pad, a pad the parser
  could not place, a document naming no copper layer). Consumers fall back to
  their own derivation.
* ``[]`` — **the reading is 「no copper layer at all」** (a bare mechanical
  hole). Consumers must not guess over it.

Pinned here:

1. the parser's own contract: ``None`` when it cannot decide, ``[]`` when it
   decides 「no copper」;
2. the consumer's: on a synthetic 4-layer board a bare NPTH occupies **no**
   layer, and a plated through-hole occupies **all** of them;
3. the fallback is still there, but keyed on ``None`` — a hand-built pad the
   parser never saw keeps 125's behaviour, and the pair ``None`` / ``[]`` is
   what tells the two cases apart.
"""

from __future__ import annotations

import json

from boardwise.core import measure
from boardwise.core.geometry import ComponentPlacement, PadGeometry
from boardwise.parsers.epru import (
    PadTemplate,
    pad_effective_layers,
    parse_epru_text,
)

COPPER = [1, 2, 15, 16]


def _epru_line(type_: str, id_: str, body: dict) -> str:
    envelope = json.dumps({"type": type_, "ticket": 1, "id": id_}, separators=(",", ":"))
    return envelope + "||" + json.dumps(body, separators=(",", ":")) + "|"


def _pad(id_: str, x: float, *, plated: bool, land: float, hole: float) -> str:
    return _epru_line("PAD", id_, {
        "num": id_, "layerId": 12, "centerX": x, "centerY": 0, "padAngle": 0,
        "defaultPad": {"padType": "ELLIPSE", "width": land, "height": land},
        "hole": {"holeType": "ROUND", "width": hole, "height": hole},
        "plated": plated,
    })


def _board():
    """A synthetic 4-layer board: three plated/unplated holes on Multi-Layer.

    * pin ``1`` — ``plated: false``, land 126 on a 126 hole: a **bare mechanical
      hole**, no copper layer at all;
    * pin ``2`` — ``plated: true``, land 80 on a 40 hole: the **barrel** it
      always was;
    * pin ``3`` — ``plated: false``, land 80 on a 40 hole: an **NPTH with a
      land**, which keeps the two outer faces.
    """
    text = "\n".join([
        _epru_line("DOCHEAD", "h1", {"docType": "FOOTPRINT", "uuid": "fp1", "editVersion": "3.2.91"}),
        _pad("1", 0, plated=False, land=126, hole=126),
        _pad("2", 100, plated=True, land=80, hole=40),
        _pad("3", 200, plated=False, land=80, hole=40),
        _epru_line("DOCHEAD", "h2", {"docType": "PCB", "uuid": "pcb1", "editVersion": "3.2.91"}),
        _epru_line("LAYER", '["LAYER",1]', {"layerName": "Top Layer", "layerType": "TOP"}),
        _epru_line("LAYER", '["LAYER",2]', {"layerName": "Bottom Layer", "layerType": "BOTTOM"}),
        _epru_line("LAYER", '["LAYER",15]', {"layerName": "Inner1", "layerType": "SIGNAL"}),
        _epru_line("LAYER", '["LAYER",16]', {"layerName": "Inner2", "layerType": "SIGNAL"}),
        _epru_line("COMPONENT", "c1", {"x": 0, "y": 0, "angle": 0, "layerId": 1}),
        _epru_line("ATTR", "a1", {"parentId": "c1", "key": "Designator", "value": "J1"}),
        _epru_line("ATTR", "a2", {"parentId": "c1", "key": "Footprint", "value": "fp1"}),
    ])
    board = parse_epru_text(text)
    return board, {pad.pin_number: pad for pad in board.pads}


# ---------------------------------------------------------------------------
# 1. the consumer: what the layers actually come out as
# ---------------------------------------------------------------------------


def test_a_bare_npth_hole_consumes_no_copper_layer():
    """The whole point of fixA: the reading 「no copper」 survives consumption.

    Before the fix this returned ``{1, 2, 15, 16}`` — the pre-127b fallback,
    fired because the empty list was read as 「not resolved」.
    """
    board, by_pin = _board()
    bare = by_pin["1"]
    assert bare.plated is False and bare.has_hole and bare.layer_id == 12
    assert bare.effective_layer_ids == [], "the parser's answer is the empty reading"
    assert measure._element_layers(board, bare) == set(), "and it must reach the consumer as such"
    assert measure._comparable_layers(board, bare) == set(), "nothing to compare it on"


def test_a_plated_hole_still_spans_every_copper_layer():
    board, by_pin = _board()
    barrel = by_pin["2"]
    assert barrel.plated is True
    assert barrel.effective_layer_ids == COPPER
    assert measure._element_layers(board, barrel) == set(COPPER)
    assert measure._comparable_layers(board, barrel) == set(COPPER)


def test_an_npth_land_keeps_the_outer_faces_only():
    board, by_pin = _board()
    land = by_pin["3"]
    assert land.effective_layer_ids == [1, 2], "no barrel: the land's faces, not 15/16"
    assert measure._element_layers(board, land) == {1, 2}


# ---------------------------------------------------------------------------
# 2. the sentinel: None is not []
# ---------------------------------------------------------------------------


def test_a_pad_nobody_read_still_falls_back():
    """A hand-built pad leaves the field at ``None``, which is 「not read」.

    125's contract: a through-hole pad with no reading behind it is still the
    conservative barrel, and an SMD one is still its own face.
    """
    board, _ = _board()
    hand_built_barrel = PadGeometry(
        id="p", component="R1", pin_number="1", layer_id=12,
        width=126, height=126, hole_diameter=40, hole_width=40, hole_height=40,
    )
    assert hand_built_barrel.effective_layer_ids is None
    assert measure._element_layers(board, hand_built_barrel) == set(COPPER)
    hand_built_smd = PadGeometry(id="p", component="R1", pin_number="1", layer_id=2)
    assert measure._element_layers(board, hand_built_smd) == {2}


def test_an_empty_reading_is_not_a_fallback_trigger():
    """The distinguishing pair, side by side on one 4-layer board."""
    board, _ = _board()
    never_read = PadGeometry(id="never", layer_id=12, hole_diameter=40, hole_width=40, hole_height=40)
    read_as_none = PadGeometry(
        id="empty", layer_id=12, effective_layer_ids=[],
        hole_diameter=40, hole_width=40, hole_height=40, plated=False,
    )
    assert measure._element_layers(board, never_read) == set(COPPER), "None → the pre-127b fallback"
    assert measure._element_layers(board, read_as_none) == set(), "[] → the reading, kept"


def test_a_hand_built_npth_flag_is_read_rather_than_stored():
    """``PadGeometry.plated`` had no reader (the review's low finding #5): it has
    one now, so ``plated: false`` on a pad nobody else classified is not a
    barrel — it is that pad's own face, which is what an NPTH's land sits on."""
    board, _ = _board()
    hand_built_npth = PadGeometry(
        id="p", component="R1", pin_number="1", layer_id=2, plated=False,
        width=80, height=80, hole_diameter=40, hole_width=40, hole_height=40,
    )
    assert measure._element_layers(board, hand_built_npth) == {2}
    # Unstated (the default) is not False: the conservative barrel stays.
    unstated = PadGeometry(id="p", layer_id=2, hole_diameter=40, hole_width=40, hole_height=40)
    assert unstated.plated is None
    assert measure._element_layers(board, unstated) == set(COPPER)


# ---------------------------------------------------------------------------
# 3. the parser's own contract
# ---------------------------------------------------------------------------


def _template(**over) -> PadTemplate:
    base = dict(
        id="e1", num="1", layer_id=12, local_x=0, local_y=0, width=80, height=80,
        shape="ELLIPSE", angle=0, hole_diameter=40, plated=False,
        hole_width=40, hole_height=40,
    )
    base.update(over)
    return PadTemplate(**base)


def test_the_reader_says_none_when_it_cannot_decide():
    """No face and no footprint layer to fall back on: ``None``, not ``[]``."""
    nowhere = _template(layer_id=None, hole_diameter=None, hole_width=None, hole_height=None)
    assert pad_effective_layers(nowhere, ComponentPlacement(id="c1"), COPPER) is None


def test_a_document_naming_no_copper_layer_is_not_read_as_no_copper():
    """A barrel's 「every copper layer」 over a stackup that names none is
    「nothing to say」, not 「no copper」 — the same distinction one level up."""
    barrel = _template(plated=None)
    assert pad_effective_layers(barrel, ComponentPlacement(id="c1", layer_id=1), []) is None
    assert pad_effective_layers(barrel, ComponentPlacement(id="c1", layer_id=1), COPPER) == COPPER
