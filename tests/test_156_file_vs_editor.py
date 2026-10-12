"""Task 156: two "file vs editor" audits, pinned as assertions.

Neither audit changes ``src/`` — both concluded "the file says so, the parser
read it right". Evidence: ``outputs/156/recon_*.txt``; the paste-ready pack for
Case A is ``outputs/156/export_loss_evidence.md``.

Case A — Board3's R1-R6 exist in the schematic and in the editor, not on the PCB
===============================================================================

The backup ``ProPrj_毕设FOC驱动板_2026-09-17.epro2`` declares six resistors
(``0805W8J0100T5E`` / C25278) on Board3's page and none of them on ``PCB3``.
155b proved the parser is not blind (it reads ``PCB3``'s *bottom-layer*
``R8``/``R18``/``R43``). This file adds the last gap 155b left open: **nothing is
hiding in a compressed segment**. The stream carries exactly one ``BLOB``
record — a base64 SVG logotype — and no gzip/zlib/xz/bz2 payload anywhere, so
the six parts are absent from the file, not from our reading of it.

Case B — the LED pin-number swap is electrically inert
======================================================

``NCD0805R1``'s symbol keeps its uuid across the two backups while its
``Pin Number`` attributes swap. This file traces the whole chain per revision —
symbol pin position -> pin number -> ``PAD_NET`` -> footprint pad number -> pad
position -> net — and shows that pin number ``n`` lands on pad number ``n`` in
**both** revisions, and that the net the ``+`` electrode sits on carries the same
partner part (a 470ohm R0603) in both. The numbering convention changed; the
circuit did not.
"""

from __future__ import annotations

import base64
import gzip
import json
import lzma
import re
import zlib
from functools import lru_cache
from pathlib import Path

from boardwise.engines.pcbreview import _pcb_documents
from boardwise.parsers.epro2_model import build_design_model, symbol_pin_names
from boardwise.parsers.epru import load_epro2_source
from boardwise.parsers.epru_stream import iter_epru_records, load_epru_text
from boardwise.parsers.schematic import build_project_model

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Batch convention (``evidence/064/anchors.py``): the ``_v1.0.0_2026-10-07``
#: backup is 1.0.0, ``_2026-09-17`` is 1.1.0.
BACKUP = {
    "1.0.0": FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2",
    "1.1.0": FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2",
}

BOARD3_UUID = "7dca2922104db3df"
SCH3_UUID = "4f0f123f421a8c42"
PAGE3_UUID = "40daf13560b1086b"
PCB3_UUID = "58db3514f9dead6e"
PCB1_UUID = "ab812fb712e14a62920977ed67aaf8f1"

LED_SYMBOL_UUID = "8a24a32599584ee3a2f628a7c2c0e930"
LED_FOOTPRINT = {
    "1.0.0": ("8457a29dfc96438295dcde00c41cd537", "LED0805-R-RD"),
    "1.1.0": ("5fa341d1ab24f883", "LED0805-RD"),
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def epru_text(version: str) -> str:
    text, _meta = load_epru_text(BACKUP[version])
    return text


@lru_cache(maxsize=None)
def documents(version: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """``(by_uuid, by_type)`` over *every* document, not just the kept types.

    ``split_documents`` keeps PCB/FOOTPRINT/DEVICE/SYMBOL only, so BOARD, SCH
    and SCH_PAGE have to be segmented by hand to walk the board->page chain.
    """
    by_uuid: dict[str, dict] = {}
    by_type: dict[str, dict] = {}
    current: dict | None = None
    for record in iter_epru_records(epru_text(version)):
        if record.type == "DOCHEAD":
            body = record.body or {}
            current = {
                "docType": body.get("docType"),
                "uuid": body.get("uuid"),
                "head": body,
                "records": [],
            }
            by_uuid[str(body.get("uuid"))] = current
            by_type.setdefault(str(body.get("docType")), {})[str(body.get("uuid"))] = current
            continue
        if current is not None:
            current["records"].append(record)
    return by_uuid, by_type


def doc_body(version: str, uuid: str) -> dict:
    return documents(version)[0][uuid]


def meta_of(version: str, uuid: str) -> dict:
    for record in doc_body(version, uuid)["records"]:
        if record.type == "META" and record.body:
            return record.body
    return {}


def attrs_by_parent(version: str, uuid: str) -> dict[str, dict[str, object]]:
    """``parentId -> {key: value}`` for one document's ATTR records."""
    out: dict[str, dict[str, object]] = {}
    for record in doc_body(version, uuid)["records"]:
        if record.type != "ATTR" or not record.body:
            continue
        parent = str(record.body.get("parentId") or "")
        out.setdefault(parent, {})[str(record.body.get("key"))] = record.body.get("value")
    return out


def components_of(version: str, uuid: str) -> dict[str, dict]:
    """``designator -> {id, line, layerId, padNets: {pin: net}}`` for a PCB doc."""
    parent_attrs = attrs_by_parent(version, uuid)
    out: dict[str, dict] = {}
    ids: dict[str, str] = {}
    for record in doc_body(version, uuid)["records"]:
        if record.type == "COMPONENT":
            ids[str(record.id)] = record.id or ""
    for record in doc_body(version, uuid)["records"]:
        if record.type == "COMPONENT":
            designator = str(parent_attrs.get(str(record.id), {}).get("Designator") or "")
            if designator:
                out[designator] = {
                    "id": str(record.id),
                    "line": record.line_no,
                    "layerId": (record.body or {}).get("layerId"),
                    "padNets": {},
                }
        elif record.type == "PAD_NET" and record.body:
            try:
                _kind, component, pin, pad = json.loads(str(record.id))
            except (TypeError, ValueError):
                continue
            for entry in out.values():
                if entry["id"] == component:
                    entry["padNets"][str(pin)] = (str(pad), record.body.get("padNet"))
    return out


def footprint_pads(version: str, uuid: str) -> dict[str, dict]:
    """``pad record id -> {num, centerX, centerY}``."""
    out: dict[str, dict] = {}
    for record in doc_body(version, uuid)["records"]:
        if record.type == "PAD" and record.body:
            out[str(record.id)] = record.body
    return out


def net_members(model, designator: str, number: str) -> set[tuple[str, str]]:
    """The ``(designator, pin)`` pairs sharing the net that ``designator.number`` sits on."""
    component = model.components[designator]
    pin = next(p for p in component.pins if p.number == number)
    net = model.nets.get(pin.net or "")
    if net is None:
        return set()
    return {(str(d), str(n)) for d, n in net.pins}


# --------------------------------------------------------------------------
# Case A — R1-R6 are missing from PCB3, and nothing is hiding them
# --------------------------------------------------------------------------


def test_board3_page_and_pcb3_are_one_board() -> None:
    """The identity chain, so "Board3" and "PCB3" cannot be a name collision."""
    _by_uuid, by_type = documents("1.1.0")

    assert meta_of("1.1.0", BOARD3_UUID)["title"] == "Board3"
    assert meta_of("1.1.0", SCH3_UUID)["board"] == BOARD3_UUID
    assert meta_of("1.1.0", PAGE3_UUID)["schematic"] == SCH3_UUID
    assert meta_of("1.1.0", PCB3_UUID)["board"] == BOARD3_UUID
    assert meta_of("1.1.0", PCB3_UUID)["title"] == "PCB3"
    assert by_type["PCB"][PCB3_UUID] is doc_body("1.1.0", PCB3_UUID)


def test_board3_page_declares_r1_to_r6_as_the_0805_part() -> None:
    parent_attrs = attrs_by_parent("1.1.0", PAGE3_UUID)
    parts = {}
    for record in doc_body("1.1.0", PAGE3_UUID)["records"]:
        if record.type != "COMPONENT":
            continue
        attrs = parent_attrs.get(str(record.id), {})
        designator = str(attrs.get("Designator") or "")
        if designator:
            parts[designator] = (attrs.get("Device"), (record.body or {}).get("partId"))

    assert len(parts) == 39
    for designator in ("R1", "R2", "R3", "R4", "R5", "R6"):
        assert parts[designator] == ("a5513e47a1f01194", "0805W8J0100T5E.1")


def test_pcb3_carries_thirty_three_parts_and_none_of_them_is_r1_to_r6() -> None:
    pcb3 = components_of("1.1.0", PCB3_UUID)

    assert len(pcb3) == 33
    assert {"R8", "R18", "R43"} <= set(pcb3)
    assert not ({"R1", "R2", "R3", "R4", "R5", "R6"} & set(pcb3))
    # the schematic declares exactly six more than the board implements
    page = attrs_by_parent("1.1.0", PAGE3_UUID)
    declared = {
        str(attrs["Designator"])
        for attrs in page.values()
        if attrs.get("Designator")
    }
    assert declared - set(pcb3) == {"R1", "R2", "R3", "R4", "R5", "R6"}


def test_no_byte_of_the_pcb3_document_names_r1_to_r6() -> None:
    """Search the whole ``PCB3`` document, every record type, not just COMPONENT."""
    start = PCB3_UUID  # segment the text by the DOCHEAD records
    lines = epru_text("1.1.0").split("\n")
    begin = next(i for i, line in enumerate(lines) if PCB3_UUID in line and '"DOCHEAD"' in line)
    end = next(
        i
        for i, line in enumerate(lines)
        if i > begin and '"DOCHEAD"' in line
    )
    segment = "\n".join(lines[begin:end])
    assert '"title":"PCB3"' in segment
    assert len(segment) > 100_000

    pattern = re.compile(r"(?<![A-Za-z0-9_])R[1-6](?![0-9])")
    assert pattern.findall(segment) == []


def test_the_record_stream_holds_one_blob_and_no_compressed_payload() -> None:
    """The "it is hiding in a segment we skip" hypothesis, closed."""
    text = epru_text("1.1.0")
    blobs = [r for r in iter_epru_records(text) if r.type == "BLOB"]
    assert len(blobs) == 1
    content = str((blobs[0].body or {}).get("content") or "")
    assert content.startswith("data:image/svg+xml;base64,")

    raw = base64.b64decode(content.split(";base64,", 1)[1])
    assert raw.startswith(b"<?xml")  # a logotype, not a payload container
    for opener in (gzip.decompress, zlib.decompress, lzma.decompress):
        try:
            opener(raw)
        except Exception:  # noqa: BLE001 - any refusal means "not compressed"
            continue
        raise AssertionError(f"{opener.__module__} decoded the BLOB: it is a container")

    magic = [b"\x1f\x8b", b"\x78\x9c", b"\x78\x01", b"\x78\xda", b"\xfd7zXZ", b"BZh"]
    for line in text.split("\n"):
        payload = line.encode("utf-8", "replace")
        assert not any(payload.find(m) != -1 for m in magic)


def test_the_parser_reads_pcb3_bottom_layer_parts_that_are_there() -> None:
    """Contrast: the layer is not the reason. ``R8``/``R18``/``R43`` are layer 2."""
    pcb3 = components_of("1.1.0", PCB3_UUID)
    assert {pcb3[name]["layerId"] for name in ("R8", "R18", "R43")} == {2}

    source = load_epro2_source(BACKUP["1.1.0"])
    document = next(d for title, _uuid, d in _pcb_documents(source) if title == "PCB3")
    model = build_design_model(source, document)

    assert len(model.components) == 33
    assert {"R8", "R18", "R43"} <= set(model.components)
    assert model.components["R18"].value  # its DEVICE metadata resolved too
    assert not ({"R1", "R2", "R3", "R4", "R5", "R6"} & set(model.components))


# --------------------------------------------------------------------------
# Case B — the LED pin-number swap, end to end
# --------------------------------------------------------------------------


def test_the_symbol_keeps_its_drawing_and_swaps_only_the_pin_numbers() -> None:
    expected = {
        "1.0.0": {"1": "+", "2": "-"},
        "1.1.0": {"2": "+", "1": "-"},
    }
    for version in ("1.0.0", "1.1.0"):
        source = load_epro2_source(BACKUP[version])
        assert symbol_pin_names(source)[LED_SYMBOL_UUID] == expected[version]

    # the pin *geometry* is identical: the "+" pin sits at symbol-local x=+20,
    # and the pin that carries it is the one whose number swapped.
    for version in ("1.0.0", "1.1.0"):
        parents = attrs_by_parent(version, LED_SYMBOL_UUID)
        positions = {
            str(record.id): (record.body or {})
            for record in doc_body(version, LED_SYMBOL_UUID)["records"]
            if record.type == "PIN"
        }
        plus = next(pid for pid, a in parents.items() if a.get("Pin Name") == "+")
        minus = next(pid for pid, a in parents.items() if a.get("Pin Name") == "-")
        assert positions[plus]["x"] == 20
        assert positions[minus]["x"] == -20
        assert str(parents[plus]["Pin Number"]) == ("1" if version == "1.0.0" else "2")
        assert str(parents[minus]["Pin Number"]) == ("2" if version == "1.0.0" else "1")


def test_the_footprint_pad_numbers_swap_with_the_symbol() -> None:
    board_x_of = {}
    for version in ("1.0.0", "1.1.0"):
        uuid, title = LED_FOOTPRINT[version]
        assert meta_of(version, uuid)["title"] == title
        pads = footprint_pads(version, uuid)
        numbers = {str(pad["num"]): pad["centerX"] for pad in pads.values()}
        board_x_of[version] = numbers

    # 1.0.0: pad "1" on +x; 1.1.0: pad "1" on -x. The plus side is +x in both,
    # so the number that rides on it changed with the symbol.
    assert board_x_of["1.0.0"]["1"] > 0 > board_x_of["1.0.0"]["2"]
    assert board_x_of["1.1.0"]["1"] < 0 < board_x_of["1.1.0"]["2"]


def test_pin_number_equals_footprint_pad_number_in_both_revisions() -> None:
    for version in ("1.0.0", "1.1.0"):
        uuid, _title = LED_FOOTPRINT[version]
        pads = footprint_pads(version, uuid)
        pcb1 = components_of(version, PCB1_UUID)
        led1 = pcb1["LED1"]

        assert led1["padNets"], f"{version}: LED1 carries no PAD_NET"
        for pin, (pad_id, _net) in led1["padNets"].items():
            assert str(pads[pad_id]["num"]) == pin


def test_the_topology_the_schematic_draws_equals_the_one_the_pcb_wires() -> None:
    """Per revision: schematic pin ``n``'s net members == PCB pad ``n``'s.

    The *names* differ only because the schematic cluster is unnamed: the
    schematic parser synthesises ``NET<n>`` (``parsers/schematic.py``), the
    editor derives ``$1N<n>`` for the copper. Comparing member sets, not names,
    is what makes the comparison meaningful.
    """
    for version in ("1.0.0", "1.1.0"):
        project = build_project_model(BACKUP[version])
        board1 = next(
            b for b in project.boards if getattr(getattr(b, "board", None), "title", "") == "Board1"
        )
        source = load_epro2_source(BACKUP[version])
        document = next(d for title, _uuid, d in _pcb_documents(source) if title == "PCB1")
        model = build_design_model(source, document)

        schematic_led1 = board1.components["LED1"]
        for pin in schematic_led1.pins:
            assert net_members(board1, "LED1", pin.number) == net_members(
                model, "LED1", pin.number
            ), f"{version}: pin {pin.number} disagrees between schematic and PCB"


def test_the_plus_electrode_keeps_the_same_partner_in_both_revisions() -> None:
    """``+`` -> a 470ohm R0603 series part in both; only its designator moved."""
    seen = {}
    for version in ("1.0.0", "1.1.0"):
        project = build_project_model(BACKUP[version])
        board1 = next(
            b for b in project.boards if getattr(getattr(b, "board", None), "title", "") == "Board1"
        )
        source = load_epro2_source(BACKUP[version])
        document = next(d for title, _uuid, d in _pcb_documents(source) if title == "PCB1")
        model = build_design_model(source, document)

        component = board1.components["LED1"]
        plus = next(p for p in component.pins if p.name == "+")
        members = net_members(board1, "LED1", plus.number)
        partner = [d for d, _n in members if d != "LED1"]
        assert len(partner) == 1

        part = model.components[partner[0]]
        assert (part.value, part.footprint) == ("470Ω", "R0603")

        seen[version] = (plus.number, members)

    # the "+" pin number changed 1 -> 2; the circuit it lands in did not
    assert seen["1.0.0"][1] == {("LED1", "1"), ("U3", "2")}
    assert seen["1.1.0"][1] == {("LED1", "2"), ("U10", "2")}
