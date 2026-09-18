"""Parser tests for EasyEDA Pro ``.epro2`` / ``.epru`` geometry.

Counts asserted below were verified by inspecting the fixture directly —
note the important distinction between the *whole-file* record census
(which includes 81 FOOTPRINT + 83 SYMBOL library documents) and the counts
inside the single **PCB document**, which is what board geometry means.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.geometry import MIL_TO_MM, NetGeometry
from boardwise.parsers.epru import iter_epru_records, parse_epro2, parse_epru_text

FIXTURE = Path(__file__).parent / "fixtures" / "llc_board.epro2"

#: Whole-file record census (all 252 documents), from the format survey.
WHOLE_FILE_CENSUS = {
    "PAD": 281,
    "PAD_NET": 390,
    "VIA": 257,
    "LINE": 680,
    "POLY": 1022,
    "FILL": 444,
    "NET": 89,
    "COMPONENT": 98,
    "PIN": 265,
    "TEXT": 63,
    "RULE": 242,
    "LAYER": 2628,
    "LAYER_PHYS": 135,
    "DOCHEAD": 252,
}


@pytest.fixture(scope="module")
def board():
    return parse_epro2(FIXTURE)


def _record(type_: str, id_: str | None = None, body: dict | None = None, ticket: int = 1) -> str:
    """Build one ``.epru`` line. ``body=None`` produces an empty-body record."""
    envelope: dict = {"type": type_, "ticket": ticket}
    if id_ is not None:
        envelope["id"] = id_
    payload = json.dumps(body, separators=(",", ":")) if body is not None else ""
    return json.dumps(envelope, separators=(",", ":")) + "||" + payload + "|"


def _doc_head(doc_type: str, uuid: str = "u1", edit_version: str = "3.2.91") -> str:
    return _record("DOCHEAD", body={"docType": doc_type, "uuid": uuid, "editVersion": edit_version})


# --------------------------------------------------------------------------
# record / document census
# --------------------------------------------------------------------------


def test_total_record_count(board):
    # 11,798 lines: the survey said 11,799 (it counted the trailing newline
    # as a record); the last line has no terminator.
    assert board.stats.total_records == 11798


@pytest.mark.parametrize("record_type,expected", sorted(WHOLE_FILE_CENSUS.items()))
def test_whole_file_census_matches_survey(board, record_type, expected):
    assert board.stats.records_by_type.get(record_type) == expected


def test_document_census(board):
    docs = board.stats.document_types
    assert docs["PCB"] == 1
    assert docs["FOOTPRINT"] == 81
    assert docs["SYMBOL"] == 83
    assert docs["DEVICE"] == 81
    assert docs["SCH"] == 1
    assert sum(docs.values()) == 252


def test_pcb_document_is_the_geometry_source(board):
    """Board copper comes from the PCB doc, not from the library docs."""
    assert board.stats.pcb_records == 1419
    assert board.edit_version == "3.2.91"
    assert board.stats.editor_version == "3.2.121"


def test_board_level_counts(board):
    # VIA lives only in the PCB document, so the whole-file count carries over.
    assert len(board.vias) == 257
    # LINE/POLY/FILL counts in the survey are dominated by footprint and
    # symbol library documents; the PCB document itself has far fewer.
    assert len(board.tracks) == 49
    assert len(board.pours) == 134
    assert len(board.components) == 47
    assert len(board.pads) == 117
    # Everything the extractor consumes is absent from unconsumed_types.
    for consumed in ("VIA", "LINE", "POLY", "FILL", "COMPONENT", "ATTR", "PAD_NET", "LAYER"):
        assert consumed not in board.stats.unconsumed_types


def test_empty_body_records_are_counted_not_fatal(board):
    # 558 records carry no payload ("{envelope}|||"); the last line of the
    # file additionally lacks its terminator, yet nothing is malformed.
    assert board.stats.empty_body_records == 558
    assert board.stats.malformed_records == 0
    assert board.stats.unknown_types == {}


# --------------------------------------------------------------------------
# geometry sanity
# --------------------------------------------------------------------------


def test_board_outline_is_155_by_80_mm(board):
    outline = board.outline
    assert outline is not None
    bbox = outline.bbox
    assert bbox is not None
    assert bbox.width * MIL_TO_MM == pytest.approx(155.0, abs=0.1)
    assert bbox.height * MIL_TO_MM == pytest.approx(80.0, abs=0.1)


def test_all_geometry_sits_inside_the_outline(board):
    """Strong check on the coordinate frame: nothing may fall off the board."""
    outline = board.outline.bbox
    tolerance = 2.0  # mils: outline vs copper rounding
    points = [p.center for p in board.pads]
    points += [v.center for v in board.vias]
    for track in board.tracks:
        points += [track.start, track.end]
    for pour in board.pours:
        points += pour.points
    assert points
    for point in points:
        assert outline.min_x - tolerance <= point.x <= outline.max_x + tolerance
        assert outline.min_y - tolerance <= point.y <= outline.max_y + tolerance


def test_via_dimensions_are_in_mils(board):
    via = board.vias[0]
    assert via.via_diameter * MIL_TO_MM == pytest.approx(1.0, abs=0.01)
    assert via.hole_diameter * MIL_TO_MM == pytest.approx(0.5, abs=0.01)
    assert via.annular_ring == pytest.approx(9.84, abs=0.01)


def test_pad_pitch_matches_footprint_spec(board):
    """C7 is a 7.5 mm pitch TH capacitor; its pads must be 7.5 mm apart."""
    pads = board.pads_for_component("C7")
    assert len(pads) == 2
    (a, b) = sorted(pads, key=lambda p: p.x)
    assert (b.x - a.x) * MIL_TO_MM == pytest.approx(7.5, abs=0.01)
    assert a.hole_diameter * MIL_TO_MM == pytest.approx(1.2, abs=0.01)


def test_component_placement_transforms_footprint_pads(board):
    c7 = board.component("C7")
    assert c7 is not None
    assert c7.angle == 180
    # Footprint-local pads are at (-147.64, 0) and (+147.64, 0); rotated 180
    # degrees they swap sides around the placement origin at x=5175.0035.
    for pad in board.pads_for_component("C7"):
        assert pad.y == pytest.approx(c7.y, abs=1e-6)
        assert abs(pad.x - c7.x) == pytest.approx(147.64, abs=0.01)
        assert pad.local_x == pytest.approx(-147.64, abs=0.01) or pad.local_x == pytest.approx(
            147.64, abs=0.01
        )


def test_layer_table(board):
    assert board.layer_name(1) == "Top Layer"
    assert board.layer_name(2) == "Bottom Layer"
    assert board.layer_name(11) == "Board Outline Layer"
    assert board.layer(1).is_copper
    assert not board.layer(3).is_copper  # silkscreen
    copper_ids = [layer.layer_id for layer in board.copper_layers() if layer.layer_type != "INNER"]
    assert copper_ids[:2] == [1, 2]


def test_track_width_is_plausible_for_a_power_board(board):
    widths_mm = sorted({t.width * MIL_TO_MM for t in board.tracks})
    assert widths_mm[0] > 0.1
    assert max(widths_mm) >= 1.0  # power copper is >= 1 mm wide


# --------------------------------------------------------------------------
# net indexing API
# --------------------------------------------------------------------------


def test_net_index_covers_every_named_element(board):
    assert sum(net.pad_count for net in board.nets.values()) == len(board.pads) - board.stats.pads_without_net
    assert sum(net.via_count for net in board.nets.values()) == len(board.vias)
    assert sum(net.track_count for net in board.nets.values()) == len(board.tracks)


def test_net_query_returns_copper_for_dc_minus(board):
    dc_minus = board.net("DC-")
    assert dc_minus.pad_count == 13
    assert dc_minus.via_count == 177
    assert dc_minus.track_count == 10
    assert dc_minus.track_length > 0
    assert set(dc_minus.components) >= {"C7", "C8", "Q3", "Q4"}


def test_net_query_helpers_agree_with_net_object(board):
    assert board.pads_for_net("DC-") is board.net("DC-").pads
    assert board.vias_for_net("DC-") is board.net("DC-").vias
    assert board.tracks_for_net("DC-") is board.net("DC-").tracks
    assert board.pours_for_net("DC-") is board.net("DC-").pours
    assert board.track_length_for_net("DC-") == board.net("DC-").track_length


def test_unknown_net_returns_empty_geometry(board):
    missing = board.net("NO-SUCH-NET")
    assert isinstance(missing, NetGeometry)
    assert missing.element_count == 0
    assert missing.track_length == 0.0
    assert not board.has_net("NO-SUCH-NET")
    assert "NO-SUCH-NET" not in board.net_names()


def test_net_bbox_is_inside_the_board(board):
    bbox = board.net("DC-").bbox()
    assert bbox is not None
    outline = board.outline.bbox
    assert bbox.min_x >= outline.min_x - 2
    assert bbox.max_x <= outline.max_x + 2


def test_ground_nets_are_flagged(board):
    # This board's power nets are PCB-internal names ($1N...) plus a few
    # schematic names; none of them is a ground, so check the helper wiring
    # on both sides.
    assert not board.net("DC-").is_ground
    assert NetGeometry(name="GND").is_ground
    assert NetGeometry(name="$1N144224").is_ground is False


def test_pours_are_indexed_by_net(board):
    poured = [p for p in board.pours if p.kind == "fill"]
    assert poured
    assert all(p.points for p in poured)
    assert sum(net.pour_count for net in board.nets.values()) == len(
        [p for p in board.pours if p.net]
    )


# --------------------------------------------------------------------------
# malformed / synthetic input
# --------------------------------------------------------------------------


def test_malformed_lines_are_tolerated():
    text = "\n".join(
        [
            _doc_head("PCB"),
            "not-json-at-all|",
            "{oops|",
            '{"type":"VIA","ticket":2,"id":"v1"}||{"netName":"A","centerX":100,"centerY":-200,'
            '"holeDiameter":19.685,"viaDiameter":39.37,"viaType":"NORMAL"}',  # no terminator
        ]
    )
    board = parse_epru_text(text)
    assert board.stats.malformed_records == 2
    assert len(board.vias) == 1
    assert board.net("A").via_count == 1


def test_unknown_record_types_are_counted_not_fatal():
    text = "\n".join(
        [
            _doc_head("PCB"),
            _record("TELEPORT", id_="t1", body={"where": "moon"}),
            _record("VIA", id_="v1", body={"netName": "A", "centerX": 1, "centerY": -2,
                                           "holeDiameter": 10, "viaDiameter": 20}),
        ]
    )
    board = parse_epru_text(text)
    assert board.stats.unknown_types == {"TELEPORT": 1}
    assert len(board.vias) == 1


def test_empty_body_record_is_skipped_but_counted():
    text = "\n".join(
        [
            _doc_head("PCB"),
            _record("VIA", id_="v1", body=None),  # empty body -> skipped
            _record("VIA", id_="v2", body={"netName": "A", "centerX": 1, "centerY": -2,
                                           "holeDiameter": 10, "viaDiameter": 20}),
        ]
    )
    board = parse_epru_text(text)
    assert board.stats.empty_body_records == 1
    assert len(board.vias) == 1
    assert board.vias[0].id == "v2"


def test_missing_pcb_document_yields_empty_board():
    text = "\n".join([_doc_head("SCH"), _record("WIRE", id_="w1", body={"zIndex": 1})])
    board = parse_epru_text(text)
    assert board.outline is None
    assert board.pads == [] and board.vias == [] and board.tracks == []
    assert board.stats.document_types == {"SCH": 1}


def test_pads_are_instantiated_from_footprint_library():
    """End-to-end synthetic: footprint pads land at the placed position."""
    text = "\n".join(
        [
            _doc_head("FOOTPRINT", uuid="fp1"),
            _record("PAD", id_="e1", body={
                "num": "1", "layerId": 1, "centerX": -100, "centerY": 0,
                "defaultPad": {"padType": "RECT", "width": 20, "height": 30},
                "hole": None, "plated": True, "padAngle": 0}),
            _doc_head("PCB", uuid="pcb1"),
            _record("LAYER", id_='["LAYER",1]', body={"layerName": "Top Layer", "layerType": "TOP"}),
            _record("COMPONENT", id_="c1", body={"x": 1000, "y": -500, "angle": 0, "layerId": 1}),
            _record("ATTR", id_="a1", body={"parentId": "c1", "key": "Designator", "value": "R1"}),
            _record("ATTR", id_="a2", body={"parentId": "c1", "key": "Footprint", "value": "fp1"}),
            _record("PAD_NET", id_='["PAD_NET","c1","1","e1"]', body={"padNet": "VBUS"}),
        ]
    )
    board = parse_epru_text(text)
    assert len(board.pads) == 1
    pad = board.pads[0]
    assert (pad.component, pad.pin_number, pad.net) == ("R1", "1", "VBUS")
    assert (pad.x, pad.y) == (900.0, -500.0)
    assert (pad.width, pad.height, pad.shape) == (20.0, 30.0, "RECT")
    assert pad.is_smd
    assert board.net("VBUS").pad_count == 1
    assert board.layer_name(1) == "Top Layer"


def test_rectangle_path_is_expanded_to_corners():
    text = "\n".join(
        [
            _doc_head("PCB", uuid="pcb1"),
            _record("POLY", id_="p1", body={
                "polyType": "BOARD_OUTLINE", "layerId": 11, "netName": "",
                "path": ["R", 0, 0, 1000, 500, 0, 0]}),
        ]
    )
    board = parse_epru_text(text)
    assert board.outline is not None
    bbox = board.outline.bbox
    assert (bbox.min_x, bbox.min_y, bbox.max_x, bbox.max_y) == (0.0, -500.0, 1000.0, 0.0)


def test_iter_records_skips_blank_lines():
    text = "\n\n" + _record("VIA", id_="v1", body={"netName": "A"}) + "\n\n"
    records = list(iter_epru_records(text))
    assert len(records) == 1
    assert records[0].type == "VIA"


def test_summary_is_json_serialisable(board):
    assert json.loads(json.dumps(board.summary()))["vias"] == 257
    assert json.loads(json.dumps(board.stats.as_dict()))["pcb_records"] == 1419
