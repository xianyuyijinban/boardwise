"""101 / B2 parser hardening: two defects from the external audit, one red test each.

Source: the audit (repo-root ``.tmp_bug_report.md``, gitignored — sections
``## 4.`` and ``## 5.``) and the task book ``tasks/101-b2-parser-hardening.md``.
Every test below was written against the revision that shipped the defect and is
**red** there; each asserts the defect's own payload — the audit's reproduction —
rather than the shape of the fix, so a different-but-correct fix still passes.

* **#4** — ``read_project_meta`` opened the archive a **second** time, outside the
  guard ``load_epru_text`` wraps the ``.epru`` member in, and its own handler
  caught only ``ValueError``/``UnicodeDecodeError``. Corrupting the CRC of
  ``project2.json`` alone — what a partially-copied download leaves behind —
  escaped as a raw ``zipfile.BadZipFile`` from every CLI call site (they catch
  ``(EncryptedProjectError, ValueError, OSError)``): a stack trace and exit 1,
  the code the README reserves for "the board has an ERROR".
* **#5** — ``schematic.py`` dereferenced ``record.body`` unconditionally, while
  the framing layer promises an empty or non-object body maps to ``body = None``
  and is "counted and skipped, **never raises**" (``epru_stream.py:161-172``).
  All six public entry points died on the audit's 2-record archive; the audit
  named ten line ranges, and the whole-file sweep below (`_iter_schematic_records`,
  ``_board_chain_from_records``, ``_collect_device_meta``, ``_commit_symbol``,
  ``_split_page``, ``_collect_symbols``, ``collect_symbol_details``) found the
  sweep's own two extra reachable ones plus a set of defensive call sites.

The synthetic archives are built in ``tmp_path``; ``tests/fixtures`` is read,
never written, and the one test that needs a *real* stream of empty bodies reads
``llc_board.epro2``'s 558 of them through the public readings.
"""

from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path
from typing import Any, Callable

import pytest

from boardwise import cli
from boardwise.core.geometry import ParseStats
from boardwise.parsers.epru_stream import (
    EncryptedProjectError,
    iter_epru_records,
    load_epru_text,
)
from boardwise.parsers.schematic import (
    _collect_device_meta,
    _collect_symbols,
    _iter_schematic_records,
    _split_page,
    board_partition,
    build_pin_offsets,
    build_project_model,
    build_schematic_model,
    collect_page_layout,
    collect_part_devices,
    collect_part_placements,
    collect_symbol_bodies,
    collect_symbol_defs,
    collect_symbol_details,
)

FIXTURES = Path(__file__).parent / "fixtures"
#: A real board whose stream carries hundreds of empty-body records — the shape
#: the framing layer already tolerates in the wild, and the one the guards must
#: be invisible on. Its bodies are ``LINE``/``NET``/``PAD_NET``/``GROUP``/
#: ``RULE_SELECTOR``; none of them is a ``DOCHEAD``/``META``/``PIN``/``ATTR``,
#: which is exactly why the audit's combination was unverified.
LLC = FIXTURES / "llc_board.epro2"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Never touch the real ``~/.boardwise`` (config, audit, sidecars)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))


# --------------------------------------------------------------------------
# builders: one record line, one document, one archive
# --------------------------------------------------------------------------


def _record(
    record_type: str,
    uid: str | None = None,
    body: dict | None = None,
    *,
    raw_body: str = "",
) -> str:
    """One ``.epru`` line: ``<envelope>||<body>|``.

    ``body=None`` writes the **empty body** the framing layer promises to
    tolerate (``<envelope>|||``) — counted as ``empty_body_records`` and handed
    on with ``body=None``. ``raw_body`` writes the body field verbatim, which is
    how the promise's second half (valid JSON that is not an object) is made.
    """
    envelope: dict[str, Any] = {"type": record_type}
    if uid is not None:
        envelope["id"] = uid
    text = raw_body if body is None else json.dumps(body)
    return json.dumps(envelope) + "||" + text + "|"


def _symbol_document() -> list[str]:
    """A library ``SYMBOL`` document: two pins, their numbers/names, an outline."""
    return [
        _record("DOCHEAD", "sym-1", {"docType": "SYMBOL", "uuid": "sym-1"}),
        _record("META", "sym-meta", {"title": "R0402"}),
        _record("PIN", "pin-1", {"x": 0, "y": 0, "zIndex": 1}),
        _record("PIN", "pin-2", {"x": 30, "y": 0, "zIndex": 2}),
        _record("ATTR", "pin-1-number",
                {"parentId": "pin-1", "key": "Pin Number", "value": "1"}),
        _record("ATTR", "pin-1-name", {"parentId": "pin-1", "key": "Pin Name", "value": "A"}),
        _record("ATTR", "pin-2-number",
                {"parentId": "pin-2", "key": "Pin Number", "value": "2"}),
        _record("RECT", "outline", {"dotX1": -10, "dotY1": -10, "dotX2": 10, "dotY2": 10}),
    ]


def _page_document() -> list[str]:
    """A ``SCH_PAGE`` holding one resistor and one wire."""
    return [
        _record("DOCHEAD", "page-1", {"docType": "SCH_PAGE", "uuid": "page-1"}),
        _record("META", "page-meta", {"schematic": "sch-1"}),
        _record("COMPONENT", "c-r1", {"partId": "R0402.1", "x": 100, "y": -200,
                                      "rotation": 0, "isMirror": False, "zIndex": 10}),
        _record("ATTR", "c-r1-designator",
                {"parentId": "c-r1", "key": "Designator", "value": "R1"}),
        _record("ATTR", "c-r1-value", {"parentId": "c-r1", "key": "Value", "value": "10k"}),
        _record("ATTR", "c-r1-device", {"parentId": "c-r1", "key": "Device", "value": "dev-1"}),
        _record("ATTR", "c-r1-symbol", {"parentId": "c-r1", "key": "Symbol", "value": "sym-1"}),
        _record("WIRE", "wire-1", {"lineGroup": "g-1"}),
        _record("LINE", "line-1", {"lineGroup": "g-1", "startX": 100, "startY": -200,
                                   "endX": 140, "endY": -200}),
    ]


def _board_documents() -> list[str]:
    """The container's own board chain: ``SCH_PAGE.META.schematic`` → ``SCH`` → ``BOARD``."""
    return [
        _record("DOCHEAD", "sch-1", {"docType": "SCH", "uuid": "sch-1"}),
        _record("META", "sch-meta", {"board": "board-1"}),
        _record("DOCHEAD", "board-1", {"docType": "BOARD", "uuid": "board-1"}),
        _record("META", "board-meta", {"title": "Board1", "zIndex": 1}),
    ]


def _clean_stream() -> list[str]:
    """Three documents, every body readable — the baseline every test varies."""
    return [*_symbol_document(), *_page_document(), *_board_documents()]


def _spliced(lines: list[str], item: str, after: str) -> list[str]:
    """``lines`` with ``item`` inserted straight after the record whose id is ``after``.

    Records are named by their envelope id, so a test says *where* the damaged
    record sits without counting indices.
    """
    index = next(
        position for position, line in enumerate(lines)
        if json.loads(line.split("||", 1)[0]).get("id") == after
    )
    return [*lines[: index + 1], item, *lines[index + 1:]]


def _text(lines: list[str]) -> str:
    """The stream as the file holds it (one record per line, terminator included)."""
    return "\n".join(lines) + "\n"


def _records(lines: list[str]) -> list[Any]:
    """The raw records of a stream — what the framing layer hands the groupers."""
    return list(iter_epru_records(_text(lines), ParseStats()))


def _epro2(directory: Path, lines: list[str], name: str = "hardening.epro2") -> Path:
    """An ``.epro2`` archive holding exactly this record stream."""
    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("board.epru", _text(lines))
        archive.writestr(
            "project2.json", json.dumps({"title": "synthetic", "editorVersion": "3.2.186"})
        )
    return path


# ==========================================================================
# 4. read_project_meta: one archive, one refusal
# ==========================================================================


def _corrupt_central_crc(source: Path, member: str, target: Path) -> Path:
    """A copy of ``source`` whose **central directory** states a wrong CRC-32.

    The audit's reproduction: the member's bytes are untouched and the archive
    stays a legal ZIP — what a partially-copied download leaves behind. The
    central directory is where ``ZipFile.read`` checks the CRC, so the damage
    is invisible until exactly this one entry is read.
    """
    raw = bytearray(source.read_bytes())
    offset = 0
    while True:
        offset = raw.find(b"PK\x01\x02", offset)
        assert offset >= 0, f"no central directory entry for {member!r}"
        name_len = struct.unpack_from("<H", raw, offset + 28)[0]
        name = raw[offset + 46: offset + 46 + name_len].decode("utf-8", "replace")
        if name == member:
            raw[offset + 16] ^= 0xFF  # the entry's CRC-32, first byte
            break
        offset += 46 + name_len
    target.write_bytes(bytes(raw))
    return target


def test_a_corrupt_metadata_member_is_refused_like_a_corrupt_document_stream(tmp_path):
    """One archive, two reads, one treatment — the audit's measurement.

    ``load_epru_text`` wraps the ``.epru`` member's read and converts
    ``RuntimeError``/``BadZipFile`` into the friendly ``EncryptedProjectError``;
    the ``project2.json`` read it makes one line later had no such handler, so
    the same damage came back as a raw ``zipfile.BadZipFile``. Both halves of the
    same archive now get the same refusal, the same advice, and a type the CLI's
    ``(EncryptedProjectError, ValueError, OSError)`` call sites catch.
    """
    plain = _epro2(tmp_path, _clean_stream())
    stream = _corrupt_central_crc(plain, "board.epru", tmp_path / "crc-stream.epro2")
    metadata = _corrupt_central_crc(plain, "project2.json", tmp_path / "crc-meta.epro2")

    with pytest.raises(EncryptedProjectError) as stream_error:
        load_epru_text(stream)
    with pytest.raises(EncryptedProjectError) as meta_error:
        load_epru_text(metadata)

    for error in (stream_error, meta_error):
        assert isinstance(error.value, ValueError), "the CLI catches ValueError, not BadZipFile"
        assert "Bad CRC-32" in str(error.value), "the cause is still named"
        assert "re-export it with that option disabled" in str(error.value)
    # ...and the healthy archive still reads, so the guard is not a blanket refusal
    text, meta = load_epru_text(plain)
    assert meta["title"] == "synthetic" and "DOCHEAD" in text


def test_a_corrupt_metadata_member_no_longer_escapes_the_cli(tmp_path, capsys):
    """Exit 1 is "the board has an ERROR"; a stack trace is not even that.

    The audit ran the CLI and got ``zipfile.BadZipFile`` with exit 1 — the code
    the README reserves for a found defect. Unreadable input is exit 2, and
    nothing about it is a traceback.
    """
    board = _corrupt_central_crc(
        _epro2(tmp_path, _clean_stream(), "cli.epro2"),
        "project2.json",
        tmp_path / "cli-crc.epro2",
    )

    code = cli.main(["review", str(board)])
    captured = capsys.readouterr()

    assert code == 2, "unreadable input, not a defect found on the board"
    assert "Traceback" not in captured.err
    assert "cli-crc.epro2" in captured.err + captured.out, "the message names the file"


# ==========================================================================
# 5. the schematic tier: the empty-body record is skipped, never fatal
# ==========================================================================

#: The six public entry points the audit measured, plus the shared path
#: (``build_project_model``) all six go through. Each is paired with the reading
#: the fixture stream must produce, so "it did not crash" is never the assertion.
ENTRIES: dict[str, tuple[Callable[[Path], Any], Any]] = {
    "build_schematic_model": (
        lambda path: {name: part.value for name, part in
                      build_schematic_model(path).components.items()},
        {"R1": "10k"},
    ),
    "build_project_model": (
        lambda path: [board.board.title for board in build_project_model(path).boards],
        ["Board1"],
    ),
    "collect_part_devices": (collect_part_devices, {"R1": "dev-1"}),
    "collect_page_layout": (
        lambda path: [part.designator for part in collect_page_layout(path).parts],
        ["R1"],
    ),
    "collect_symbol_details": (
        lambda path: {uuid: (detail.title, sorted(detail.offsets)) for uuid, detail in
                      collect_symbol_details(path).items()},
        {"sym-1": ("R0402", ["1", "2"])},
    ),
    "build_pin_offsets": (
        lambda path: {name: sorted(offsets) for name, offsets in
                      build_pin_offsets(path).items()},
        {"R1": ["1", "2"]},
    ),
    "collect_part_placements": (
        lambda path: dict(collect_part_placements(path)),
        {(100.0, 200.0): "R1"},
    ),
}

#: The two body shapes ``iter_epru_records`` maps to ``body = None``
#: (``epru_stream.py:161-172``): an empty body field, and a body that is valid
#: JSON but not an object. The audit's payload is the first one.
BODY_SHAPES: dict[str, Callable[[], str]] = {
    "empty": lambda: _record("DOCHEAD", "d1"),
    "non-object": lambda: _record("DOCHEAD", "d1", raw_body="5"),
}

#: The three entry points whose reading comes from the ``SYMBOL`` documents.
SYMBOL_READERS = ["build_pin_offsets", "build_schematic_model", "collect_symbol_details"]


@pytest.mark.parametrize("shape", sorted(BODY_SHAPES))
@pytest.mark.parametrize("entry", sorted(ENTRIES))
def test_no_public_entry_point_dies_on_a_head_with_no_readable_body(entry, shape, tmp_path):
    """The audit's archive: its first record is ``{"type":"DOCHEAD","id":"d1"}|||``.

    Every entry point raised ``AttributeError: 'NoneType' object has no attribute
    'get'`` from ``_iter_schematic_records`` — the head is the first thing each of
    them reads — because the DOCHEAD branch dereferenced ``record.body`` while the
    framing layer promises that shape arrives as ``None``. A record with no
    readable body is skipped, and the documents around it read exactly as they do
    without it.
    """
    read, expected = ENTRIES[entry]
    damaged = _epro2(
        tmp_path, [BODY_SHAPES[shape](), *_clean_stream()], f"head-{shape}.epro2"
    )
    assert read(damaged) == expected


@pytest.mark.parametrize("entry", SYMBOL_READERS)
def test_an_empty_body_attribute_in_a_symbol_document_keeps_every_pin(entry, tmp_path):
    """The audit's other shape: an empty body on an ``ATTR``.

    Inside a ``SYMBOL`` document ``_commit_symbol`` read ``body.get("key")`` for
    every record it walked, so one body-less attribute took the whole symbol —
    and with it every pin number and name after it — down. The symbol reads as it
    does without the record: the attributes that name pins are filed by
    ``parentId``, and an unreadable one files nothing.
    """
    read, expected = ENTRIES[entry]
    lines = _spliced(_clean_stream(), _record("ATTR", "empty-attr"), after="outline")
    assert read(_epro2(tmp_path, lines, "empty-attr.epro2")) == expected


@pytest.mark.parametrize("entry", SYMBOL_READERS)
def test_an_empty_body_meta_in_a_symbol_document_keeps_the_symbol(entry, tmp_path):
    """A body-less ``META`` inside a ``SYMBOL`` document — a point the audit's list missed.

    ``_commit_symbol`` read the title off every ``META`` of the document before it
    looked at a single ``PIN``, so a body-less one was fatal there too. Skipping it
    leaves the symbol — and its title, which the earlier ``META`` already set —
    exactly as they were.
    """
    read, expected = ENTRIES[entry]
    lines = _spliced(_clean_stream(), _record("META", "empty-meta"), after="outline")
    assert read(_epro2(tmp_path, lines, "empty-symbol-meta.epro2")) == expected


def test_an_empty_body_pin_in_a_symbol_document_drops_only_that_pin(tmp_path):
    """A body-less ``PIN`` is a record with nothing to read, not a pin at (0, 0).

    The audit's list stopped at ``:997`` for this function; the same walk
    dereferences the body of a ``META`` (``:968``) and of a ``PIN`` (``:973``)
    first. The other pin — position, number and name — survives, and the drop is
    what the framing layer already counted (``empty_body_records``), not a
    ``pins_dropped_no_number`` this reader had to invent.
    """
    lines = _spliced(_clean_stream(), _record("PIN", "empty-pin"), after="outline")
    path = _epro2(tmp_path, lines, "empty-pin.epro2")

    assert {name: sorted(offsets) for name, offsets in build_pin_offsets(path).items()} == {
        "R1": ["1", "2"]
    }
    stats = ParseStats()
    build_schematic_model(path, parse_stats=stats)
    assert stats.empty_body_records == 1
    assert stats.pins_dropped_no_number == 0


@pytest.mark.parametrize("after", ["board-meta", "page-meta", "sch-meta"])
def test_an_empty_body_meta_does_not_break_the_board_chain(after, tmp_path):
    """A body-less ``META`` on the chain documents (``BOARD``/``SCH_PAGE``/``SCH``).

    ``_board_chain_from_records`` read ``title``/``board``/``schematic`` off every
    ``META`` it met; the audit named the head half (``:379-380``) and this line
    (``:387``). "There is no body to read" means only the missing fact is lost, so
    the chain must read as it does when the record is **absent** — not as it does
    for a record that states something (a ``{}`` body still appends its board to
    the order, and two METAs in one ``BOARD`` document are two boards). The board
    comes back with its own title and the page with its own parts.
    """
    damaged = _epro2(
        tmp_path,
        _spliced(_clean_stream(), _record("META", "empty-meta"), after=after),
        f"chain-{after}.epro2",
    )
    absent = _epro2(tmp_path, _clean_stream(), f"chain-{after}-absent.epro2")

    assert ([board.board.title for board in build_project_model(damaged).boards]
            == [board.board.title for board in build_project_model(absent).boards]
            == ["Board1"])
    assert ({name: part.value for name, part in build_schematic_model(damaged).components.items()}
            == {name: part.value for name, part in build_schematic_model(absent).components.items()}
            == {"R1": "10k"})


def test_the_two_passes_of_the_page_split_agree_on_a_head_with_no_body(tmp_path):
    """Pass 1 guards the body-less ``DOCHEAD`` (``:737``); pass 2 did not (``:798``).

    Sixty lines apart, the same record was skipped by one pass and dereferenced by
    the other — the audit's "inconsistent with itself". The reading must be the one
    a head with an **empty object** body gives, because that is what the framing
    layer says the two shapes are: ``body is None`` and ``body == {}`` are the same
    input to every reader above it.
    """
    damaged = _split_page(_records(
        _spliced(_page_document(), _record("DOCHEAD", "extra"), after="page-1")))
    twin = _split_page(_records(
        _spliced(_page_document(), _record("DOCHEAD", "extra", {}), after="page-1")))

    assert damaged == twin
    assert {inst.attrs.get("Designator") for inst in damaged.instances} == {"R1"}


def test_a_head_with_no_body_reads_exactly_like_one_with_an_empty_object(tmp_path):
    """``body is None`` ≡ ``{}`` for every reader that dereferences a head's body.

    The same equivalence at the record level, over the four readers the audit named
    for the head shape: ``board_partition`` (``:309-311``), ``_collect_device_meta``
    (``:485``), ``_collect_symbols`` (``:1055``) and ``_iter_schematic_records``
    (``:240``). The groupers take a record list a caller may build from
    ``iter_epru_records`` directly, which is how the first three are reached — the
    entry points never hand them a head they would have dropped.
    """
    damaged_lines = [_record("DOCHEAD", "d1"), *_clean_stream()]
    twin_lines = [_record("DOCHEAD", "d1", {}), *_clean_stream()]
    damaged, twin = _records(damaged_lines), _records(twin_lines)

    assert board_partition(damaged, project_meta={}) == board_partition(twin, project_meta={})
    assert _collect_device_meta(damaged) == _collect_device_meta(twin)
    assert _collect_symbols(damaged, ParseStats()) == _collect_symbols(twin, ParseStats())
    assert _split_page(damaged) == _split_page(twin)
    assert _iter_schematic_records(_text(damaged_lines), ParseStats()) == \
        _iter_schematic_records(_text(twin_lines), ParseStats())


def test_the_empty_body_count_stays_where_the_contract_puts_it(tmp_path):
    """The count lives in the framing layer, so no reader above it has to invent one.

    This is what "counted and skipped" means: ``iter_epru_records`` counts the
    record, and every reader above it skips it because ``body is None`` — no second
    counter, and no reader left to decide for itself.
    """
    lines = [_record("DOCHEAD", "d1"), *_clean_stream(), _record("LINE", "empty-line")]
    text, _meta = load_epru_text(_epro2(tmp_path, lines))

    stats = ParseStats()
    records = list(iter_epru_records(text, stats))

    assert stats.empty_body_records == 2
    assert stats.malformed_records == 0, "an empty body is not a malformed line"
    assert sum(1 for record in records if record.body is None) == 2


def test_a_real_fixture_full_of_empty_bodies_reads_the_same_with_them_filled_in(tmp_path):
    """``llc_board.epro2`` does carry 558 of them, so the guards must be invisible.

    Every empty body in the real stream is rewritten as ``{}`` — the other shape
    the framing layer calls the same thing — and every reading of the board must
    be byte-for-byte the same answer. This is the zero-movement check expressed
    as an assertion rather than as a one-off comparison.
    """
    filled = _with_empty_bodies_filled(LLC, tmp_path / "llc-filled.epro2")

    stats = ParseStats()
    plain_model = build_schematic_model(LLC, parse_stats=stats)
    assert stats.empty_body_records >= 500, "the fixture's empty bodies are the point"

    assert build_schematic_model(filled) == plain_model
    assert collect_page_layout(filled) == collect_page_layout(LLC)
    assert collect_symbol_details(filled) == collect_symbol_details(LLC)
    # the two entry points that read the same records through a third walk
    assert build_pin_offsets(filled) == build_pin_offsets(LLC)
    assert collect_part_placements(filled) == collect_part_placements(LLC)


def _with_empty_bodies_filled(source: Path, target: Path) -> Path:
    """``source`` repacked with every ``|||`` record terminator written ``||{}|``."""
    with zipfile.ZipFile(source) as archive:
        members = {info.filename: archive.read(info) for info in archive.infolist()}
    with zipfile.ZipFile(target, "w") as out:
        for name, data in members.items():
            if name.lower().endswith(".epru"):
                text = data.decode("utf-8")
                filled = "".join(
                    line[:-3] + "||{}|" if line.endswith("|||") else line
                    for line in text.splitlines(keepends=True)
                )
                data = filled.encode("utf-8")
            out.writestr(name, data)
    return target


# ==========================================================================
# the two public helpers the six entry points are built from
# ==========================================================================


@pytest.mark.parametrize("reader", ["collect_symbol_defs", "collect_symbol_bodies"])
def test_the_symbol_helpers_read_the_damaged_stream_like_the_intact_one(reader, tmp_path):
    """``collect_symbol_defs``/``collect_symbol_bodies`` are public and read the same walk."""
    read = collect_symbol_defs if reader == "collect_symbol_defs" else collect_symbol_bodies
    clean = _epro2(tmp_path, _clean_stream(), "clean.epro2")
    damaged = _epro2(
        tmp_path,
        [BODY_SHAPES["empty"](),
         *_spliced(_clean_stream(), _record("ATTR", "empty-attr"), after="outline")],
        "both-shapes.epro2",
    )
    assert read(clean) != {} and read(damaged) == read(clean)
