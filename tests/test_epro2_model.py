"""Tests for ``.epro2`` -> :class:`DesignModel` (task 002)."""

import json
import zipfile
from pathlib import Path

import pytest

from boardwise.core.geometry import ParseStats
from boardwise.engines.review import run_review
from boardwise.rules.connectivity import parse_resistance_ohms
from boardwise.parsers.epro2_model import (
    build_design_model,
    device_metas,
    footprint_titles,
)
from boardwise.parsers.epru import (
    EncryptedProjectError,
    Epro2Source,
    build_board_geometry,
    load_epro2_source,
    split_documents,
)

FIXTURE = Path(__file__).parent / "fixtures" / "llc_board.epro2"


# --------------------------------------------------------------------------
# synthetic .epru helpers
# --------------------------------------------------------------------------


def _line(record_type: str, body: dict | None = None, record_id: str | None = None) -> str:
    """Encode one ``.epru`` record: ``{envelope}||{body}|``."""
    envelope: dict = {"type": record_type}
    if record_id is not None:
        envelope["id"] = record_id
    payload = "" if body is None else json.dumps(body)
    return json.dumps(envelope) + "||" + payload + "|"


def _dochead(doc_type: str, uuid: str) -> str:
    return _line("DOCHEAD", {"docType": doc_type, "uuid": uuid, "editVersion": "3.2.91"})


def _source_from_text(text: str) -> Epro2Source:
    """Build an :class:`Epro2Source` from synthetic ``.epru`` text."""
    stats = ParseStats(source="<synthetic>")
    return Epro2Source(
        source="<synthetic>",
        stats=stats,
        documents=split_documents(text, stats),
        project_meta={"title": "synthetic"},
    )


#: One resistor placed on a two-pad footprint, with library metadata.
SYNTHETIC = "\n".join(
    [
        # --- DEVICE: the library part -----------------------------------
        _dochead("DEVICE", "dev1"),
        _line(
            "META",
            {
                "title": "R_10k_title",
                "attributes": {
                    "Value": "10k",
                    "Supplier Part": "C25804",
                    "Manufacturer": "null",  # unset attributes are literal "null"
                    "Manufacturer Part": "0805W8F1002T5E",
                    "Datasheet": "",
                },
            },
            "META",
        ),
        # --- DEVICE without a Value attribute ---------------------------
        _dochead("DEVICE", "dev2"),
        _line("META", {"title": "CONN-2P", "attributes": {"Supplier Part": "C12345"}}, "META"),
        # --- FOOTPRINT: two pads ----------------------------------------
        _dochead("FOOTPRINT", "fp1"),
        _line("META", {"title": "R0805"}, "META"),
        _line(
            "PAD",
            {"num": "1", "centerX": -30, "centerY": 0, "defaultPad": {"width": 40, "height": 40}},
            "p1",
        ),
        _line(
            "PAD",
            {"num": "2", "centerX": 30, "centerY": 0, "defaultPad": {"width": 40, "height": 40}},
            "p2",
        ),
        # --- PCB: two placements ----------------------------------------
        _dochead("PCB", "pcb1"),
        _line("COMPONENT", {"x": 0, "y": 0, "angle": 0, "attrs": {}}, "c1"),
        _line("ATTR", {"parentId": "c1", "key": "Designator", "value": "R1"}),
        _line("ATTR", {"parentId": "c1", "key": "Device", "value": "dev1"}),
        _line("ATTR", {"parentId": "c1", "key": "Footprint", "value": "fp1"}),
        _line("COMPONENT", {"x": 500, "y": 0, "angle": 90, "attrs": {}}, "c2"),
        _line("ATTR", {"parentId": "c2", "key": "Designator", "value": "J1"}),
        _line("ATTR", {"parentId": "c2", "key": "Device", "value": "dev2"}),
        # Pad 1 of R1 on GND, pad 2 unconnected; J1 has one PAD_NET only.
        _line("PAD_NET", {"padNet": "GND"}, '["PAD_NET","c1","1","p1"]'),
        _line("PAD_NET", {"padNet": ""}, '["PAD_NET","c1","2","p2"]'),
        _line("PAD_NET", {"padNet": "VCC"}, '["PAD_NET","c2","1","p1"]'),
    ]
)


# --------------------------------------------------------------------------
# synthetic source
# --------------------------------------------------------------------------


def test_synthetic_components_and_pins():
    model = build_design_model(_source_from_text(SYNTHETIC))
    assert set(model.components) == {"R1", "J1"}

    r1 = model.components["R1"]
    assert r1.uid == "c1"
    # Value attribute wins over the DEVICE title.
    assert r1.value == "10k"
    assert r1.footprint == "R0805"  # from the FOOTPRINT document title
    assert r1.lcsc_part == "C25804"
    assert r1.manufacturer == ""  # literal "null" is cleaned to ""
    assert r1.mpn == "0805W8F1002T5E"
    assert r1.datasheet == ""
    assert r1.props["DeviceTitle"] == "R_10k_title"
    assert r1.props["Device"] == "dev1"
    assert r1.props["Footprint"] == "fp1"

    assert [(p.number, p.net) for p in r1.pins] == [("1", "GND"), ("2", None)]


def test_value_falls_back_to_device_title():
    model = build_design_model(_source_from_text(SYNTHETIC))
    j1 = model.components["J1"]
    assert j1.value == "CONN-2P"  # no Value attribute -> DEVICE title
    assert j1.lcsc_part == "C12345"


def test_pins_come_from_pads_then_pad_net():
    # J1 sits on a footprint it does not own in this stream, so its only pin
    # is the one PAD_NET record names.
    model = build_design_model(_source_from_text(SYNTHETIC))
    assert [(p.number, p.net) for p in model.components["J1"].pins] == [("1", "VCC")]


def test_nets_are_reverse_built():
    model = build_design_model(_source_from_text(SYNTHETIC))
    assert set(model.nets) == {"GND", "VCC"}
    assert model.nets["GND"].pins == [("R1", "1")]
    assert model.nets["VCC"].pins == [("J1", "1")]


def test_pin_names_are_left_empty():
    # SYMBOL documents are dropped at parse time, so pin names do not exist.
    model = build_design_model(_source_from_text(SYNTHETIC))
    assert all(pin.name == "" for comp in model.components.values() for pin in comp.pins)


def test_missing_pcb_document_gives_empty_model():
    source = _source_from_text(_dochead("DEVICE", "dev1"))
    model = build_design_model(source)
    assert model.components == {}
    assert model.nets == {}


def test_device_metas_and_footprint_titles():
    source = _source_from_text(SYNTHETIC)
    assert set(device_metas(source)) == {"dev1", "dev2"}
    assert device_metas(source)["dev1"].title == "R_10k_title"
    assert footprint_titles(source) == {"fp1": "R0805"}


# --------------------------------------------------------------------------
# real fixture
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def source():
    return load_epro2_source(FIXTURE)


@pytest.fixture(scope="module")
def model(source):
    return build_design_model(source)


def test_fixture_component_count(model):
    assert len(model.components) == 47


def test_fixture_every_component_has_a_designator(model):
    assert all(c.designator for c in model.components.values())
    assert len(model.components) == len({c.designator for c in model.components.values()})


def test_fixture_device_join_is_complete(source, model):
    # The Device attribute resolved for every placement on this fixture.
    metas = device_metas(source)
    context = source.pcb_context()
    assert len(context.device_ids) == 47
    assert all(uid in metas for uid in context.device_ids.values())


def test_fixture_known_component(model):
    c7 = model.components["C7"]
    assert c7.value == "472M 1KV"
    assert c7.footprint == "CAP-TH_L12.5-W5.0-P7.50-D1.2"
    assert c7.lcsc_part == "C263262"
    assert c7.manufacturer == "Dersonic"
    assert [p.number for p in c7.pins] == ["1", "2"]


def test_fixture_pin_net_spot_checks(model):
    pins = {p.number: p.net for p in model.components["C3"].pins}
    assert pins == {"1": "DC+", "2": "DC-"}
    q1 = {p.number: p.net for p in model.components["Q1"].pins}
    assert q1 == {"1": "CHG", "2": "DC+", "3": "CHS"}


def test_fixture_nets_reverse_built_from_pins(model):
    connected = sum(1 for c in model.components.values() for p in c.pins if p.net)
    assert connected == sum(len(n.pins) for n in model.nets.values())
    assert model.nets["DC+"].pins  # non-empty


def test_fixture_unconnected_pins_have_no_net(model):
    assert any(p.net is None for c in model.components.values() for p in c.pins)


def test_geometry_and_model_share_one_parse(source, model):
    board = build_board_geometry(source)
    # Same designator keys on both sides -> cross-reference by designator.
    assert set(model.components) == {c.designator for c in board.components}
    for designator, component in model.components.items():
        placement = board.component(designator)
        assert placement is not None
        assert placement.id == component.uid
    # One walk: building the second view must not double-count anything.
    assert source.stats.pcb_records == len(source.first_document("PCB").records)


def test_model_matches_geometry_pads(source, model):
    board = build_board_geometry(source)
    for designator, component in model.components.items():
        pads = board.pads_for_component(designator)
        assert {p.pin_number for p in pads} <= {p.number for p in component.pins}


def test_value_fallback_is_usable_by_value_parsing_rules(model):
    # The fallback (DEVICE title) is a display string, but for passives it is
    # still parseable, so value-driven L1 rules behave as on .enet.
    assert parse_resistance_ohms(model.components["R1"].value) == pytest.approx(10000)
    # For semiconductors it is a part number and must simply not parse.
    assert model.components["Q1"].value == "B3M040065H"
    assert parse_resistance_ohms(model.components["Q1"].value) is None


def test_l1_rules_run_on_epro2_model(model):
    # Every registered rule answers on an .epro2-sourced model, and its
    # findings are well formed. This fixture's 7 findings were all
    # decoupling-per-ic's, which 015 retired, so the loop is now general
    # rather than driven by whatever this one board happened to trip.
    from boardwise.engines.review import BUILTIN_RULES

    assert run_review(model) == []
    for rule in BUILTIN_RULES:
        findings = rule.check(model)
        assert isinstance(findings, list)
        assert all(f.rule_id for f in findings)
        assert all(f.severity in {"ERROR", "WARN", "INFO"} for f in findings)
        assert all(isinstance(f.evidence, list) for f in findings)


# --------------------------------------------------------------------------
# unreadable / encrypted input
# --------------------------------------------------------------------------


def test_non_zip_backup_is_reported_as_encrypted(tmp_path):
    bad = tmp_path / "bad.epro2"
    bad.write_bytes(b"\x00\x01\x02not a zip at all")
    with pytest.raises(EncryptedProjectError) as excinfo:
        load_epro2_source(bad)
    assert "re-export" in str(excinfo.value)


def test_zip_without_epru_member_is_reported(tmp_path):
    archive = tmp_path / "empty.epro2"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("project2.json", "{}")
    with pytest.raises(EncryptedProjectError):
        load_epro2_source(archive)


def _set_encryption_flag(path: Path) -> None:
    """Flip the "entry is encrypted" bit in a ZIP written by ``zipfile``.

    ``zipfile`` refuses to *write* encrypted entries, so the bit is patched
    into the headers afterwards: general purpose bit 0 in the local file
    header (offset 6) and in the central directory entry (offset 8).
    """
    raw = bytearray(path.read_bytes())
    local = raw.find(b"PK\x03\x04")
    central = raw.rfind(b"PK\x01\x02")
    assert local != -1 and central != -1
    raw[local + 6] |= 0x01
    raw[central + 8] |= 0x01
    path.write_bytes(bytes(raw))


def test_zip_with_encrypted_flag_is_reported(tmp_path):
    archive = tmp_path / "flagged.epro2"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("board.epru", '{"type":"DOCHEAD"}|||')
    _set_encryption_flag(archive)
    with pytest.raises(EncryptedProjectError) as excinfo:
        load_epro2_source(archive)
    assert "password" in str(excinfo.value)
