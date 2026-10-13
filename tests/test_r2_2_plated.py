"""R2-2: the PAD ``plated`` flag — the real field, read tri-state, and consumed.

What R2 found (evidence in ``outputs/R2/plated_census.txt`` and the PR):

* ``plated`` **is** the plating field: both format specifications call it
  「是否金属化孔壁」, and the editor's own drill table / drill export splits PTH
  from NPTH on it. The parser always read the right key.
* Every one of the 3583 PAD records in the 14 board fixtures says
  ``plated: true`` — SMD pads, and the M2/M3 screw holes whose land equals their
  hole. So no fixture distinguishes a plated barrel from a mechanical hole, and
  the field had no consumer: :func:`pad_effective_layers` treated **every** hole
  as a plated barrel spanning every copper layer. That is the placeholder R2-2
  removes.

Pinned here:

1. :func:`_plated_flag` is tri-state — ``True``/``1``, ``False``/``0``, ``None``
   for anything else (an absent key is "did not say", not "not plated").
2. An NPTH pad is no barrel: on an **injected copy** of a fixture (one PAD
   record's ``plated`` flipped, located by value, exactly one hit), a pad with a
   land keeps only the outer faces (a 4-layer board loses layers 15/16 for it),
   and every other pad of the board is unchanged. A bare screw hole (land no
   larger than the hole) occupies no copper layer at all — pinned on the
   function directly, because the fixtures' screw-hole footprints are library
   entries that no board places.
3. Zero verdict flips by construction: the NPTH branch needs ``plated is
   False``, and no fixture has one — the census is pinned so a fixture that
   brings the first NPTH announces itself here.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.geometry import ComponentPlacement
from boardwise.engines.pcbreview import _pcb_documents
from boardwise.parsers.epru import (
    PadTemplate,
    _plated_flag,
    extract_board,
    load_epro2_source,
    pad_effective_layers,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"



def _inject_npth(source: Path, out: Path, **match) -> Path:
    """Copy ``source`` to ``out`` with exactly one PAD record set to ``plated: false``.

    The record is found by value — its parsed body's ``num``, ``defaultPad`` and
    ``hole`` equal ``match`` — and the edit asserts one hit, so a fixture whose
    content moved fails here instead of silently injecting nothing.
    """
    with zipfile.ZipFile(source) as archive:
        members = [(info, archive.read(info.filename)) for info in archive.infolist()]
    epru = [i for i, (info, _) in enumerate(members) if info.filename.endswith(".epru")]
    assert len(epru) == 1, [info.filename for info, _ in members]
    info, raw = members[epru[0]]
    lines = raw.decode("utf-8").split("\n")
    hits = []
    for index, line in enumerate(lines):
        if not line.startswith('{"type":"PAD"') or "||" not in line:
            continue
        body = json.loads(line.split("||", 1)[1].rstrip("|"))
        if all(body.get(key) == value for key, value in match.items()):
            hits.append(index)
    assert len(hits) == 1, f"{len(hits)} PAD records match {match}"
    line = lines[hits[0]]
    assert line.count('"plated":true') == 1
    lines[hits[0]] = line.replace('"plated":true', '"plated":false')
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for i, (member, data) in enumerate(members):
            archive.writestr(member, "\n".join(lines).encode("utf-8") if i == epru[0] else data)
    return out


def _pads_by_board(path: Path) -> dict[str, dict[tuple, object]]:
    source = load_epro2_source(path)
    boards = {}
    for title, _uuid, document in _pcb_documents(source):
        board = extract_board(document, source.footprints(), source.stats, source.footprint_artwork())
        boards[title] = {(pad.component_id, pad.id): pad for pad in board.pads}
    return boards


@pytest.mark.parametrize(
    ("value", "expected"),
    [(True, True), (1, True), (False, False), (0, False), (None, None), ("true", None), (2, None), (1.0, None)],
)
def test_the_flag_is_read_tri_state(value, expected):
    assert _plated_flag({"plated": value}) is expected


def test_an_absent_flag_is_unstated_and_the_hole_stays_a_barrel():
    assert _plated_flag({}) is None
    template = PadTemplate(
        id="e1", num="1", layer_id=12, local_x=0, local_y=0, width=60, height=60,
        shape="ELLIPSE", angle=0, hole_diameter=40, plated=None, hole_width=40, hole_height=40,
    )
    placement = ComponentPlacement(id="c1", layer_id=1)
    assert pad_effective_layers(template, placement, [1, 2, 15, 16]) == [1, 2, 15, 16]


def test_an_npth_pad_with_a_land_keeps_only_the_outer_faces(tmp_path):
    match = {
        "num": "4",
        "defaultPad": {"padType": "ELLIPSE", "width": 66.929, "height": 66.929},
        "hole": {"holeType": "ROUND", "width": 39.37, "height": 39.37},
    }
    injected = _inject_npth(FOC_100, tmp_path / "foc_npth.epro2", **match)
    before = _pads_by_board(FOC_100)
    after = _pads_by_board(injected)
    assert before.keys() == after.keys()

    flipped = []
    for title, pads in after.items():
        for key, pad in pads.items():
            old = before[title][key]
            if pad.plated is False:
                flipped.append((title, pad))
                assert old.effective_layer_ids == sorted(set(old.effective_layer_ids))
                assert pad.effective_layer_ids == [1, 2], (title, pad.component, pad.pin_number)
            else:
                assert pad.plated is True
                assert pad.effective_layer_ids == old.effective_layer_ids, (title, key)
    assert flipped, "the injected footprint is placed somewhere"
    four_layer = [pad for title, pad in flipped if set(before[title][(pad.component_id, pad.id)].effective_layer_ids) > {1, 2}]
    assert four_layer, "at least one placement is on the 4-layer board, where the barrel spanned 15/16"


def _template(**over):
    base = dict(
        id="e1", num="1", layer_id=12, local_x=0, local_y=0, width=126, height=126,
        shape="ELLIPSE", angle=0, hole_diameter=126, plated=False, hole_width=126, hole_height=126,
    )
    base.update(over)
    return PadTemplate(**base)


def test_a_bare_npth_screw_hole_occupies_no_copper_layer():
    """Land no larger than the hole: no copper anywhere (the M2/M3 screw-hole shape
    the fixtures' libraries carry, 126 x 126 land on a 126 hole). None of those
    footprints is placed on a fixture board, so the branch is pinned directly."""
    copper = [1, 2, 15, 16]
    top = ComponentPlacement(id="c1", layer_id=1)
    assert pad_effective_layers(_template(), top, copper) == []
    # Plated, the same pad is the barrel it always was.
    assert pad_effective_layers(_template(plated=True), top, copper) == copper


def test_an_npth_slot_compares_long_axis_with_long_axis():
    """A slot's ``hole.width`` is its long axis; the land's long axis may be its
    height. 47 x 87 land on a 63 x 24 slot has a ring on both axes."""
    copper = [1, 2]
    top = ComponentPlacement(id="c1", layer_id=1)
    slot = _template(width=47.244, height=86.614, hole_diameter=None, hole_width=62.992, hole_height=23.622)
    assert pad_effective_layers(slot, top, copper) == [1, 2]
    bare_slot = _template(width=23.622, height=62.992, hole_diameter=None, hole_width=62.992, hole_height=23.622)
    assert pad_effective_layers(bare_slot, top, copper) == []


def test_a_single_face_npth_land_sits_on_the_placements_face():
    copper = [1, 2, 15, 16]
    bottom = ComponentPlacement(id="c1", layer_id=2)
    single = _template(layer_id=1, width=80, height=80, hole_diameter=40, hole_width=40, hole_height=40)
    assert pad_effective_layers(single, bottom, copper) == [2]


def test_no_fixture_carries_an_npth_pad_so_no_verdict_can_move():
    """The census behind 「全夹具零判决翻转」. A fixture that brings the first
    ``plated: false`` (or a PAD with no flag) fails here, on purpose: that board
    is the first one whose verdicts R2-2 can change, and it deserves a look."""
    seen = {}
    total = 0
    for path in sorted(FIXTURES.glob("*.epro2")):
        templates = [t for pads in load_epro2_source(path).footprints().values() for t in pads]
        seen[path.name] = {repr(t.plated) for t in templates}
        total += len(templates)
    assert all(values <= {"True"} for values in seen.values()), seen
    # docs/epru-format.md §6.3 states this number; the doc may not outrun it.
    assert total == 3583


def _epru_line(type_: str, id_: str, body: dict) -> str:
    envelope = json.dumps({"type": type_, "ticket": 1, "id": id_}, separators=(",", ":"))
    return envelope + "||" + json.dumps(body, separators=(",", ":")) + "|"


def test_the_parser_reads_the_flag_tri_state_at_the_call_site():
    """Through the real parse: a PAD record with no ``plated`` key is a barrel
    (``None``), ``false`` is an NPTH, ``true`` stays plated."""
    from boardwise.parsers.epru import parse_epru_text

    def pad(id_, x, plated):
        body = {
            "num": id_, "layerId": 12, "centerX": x, "centerY": 0, "padAngle": 0,
            "defaultPad": {"padType": "ELLIPSE", "width": 80, "height": 80},
            "hole": {"holeType": "ROUND", "width": 40, "height": 40},
        }
        if plated is not ...:
            body["plated"] = plated
        return _epru_line("PAD", id_, body)

    text = "\n".join([
        _epru_line("DOCHEAD", "h1", {"docType": "FOOTPRINT", "uuid": "fp1", "editVersion": "3.2.91"}),
        pad("1", 0, ...), pad("2", 100, False), pad("3", 200, True),
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
    by_pin = {pad.pin_number: pad for pad in board.pads}
    # A 4-layer board: the barrel spans 1/2/15/16, the NPTH's land only 1/2.
    assert by_pin["1"].plated is None and by_pin["1"].effective_layer_ids == [1, 2, 15, 16]
    assert by_pin["2"].plated is False and by_pin["2"].effective_layer_ids == [1, 2]
    assert by_pin["3"].plated is True and by_pin["3"].effective_layer_ids == [1, 2, 15, 16]
