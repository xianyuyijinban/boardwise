"""A board as a **source of part identity** — the harvest's input.

Task 008b's harvest walks the components of a board and records what each
library device is. Two file formats can carry that, and they carry it in
different places:

| | `.eprj2` (local project) | `.epro2` (export) |
|---|---|---|
| project metadata | `projects` table | `project2.json` in the ZIP |
| documents | `documents.dataStr` = `"base64" + b64(gzip(array records))` | one `.epru` stream, `{envelope}||{body}|` lines |
| library documents | `components` table (symbols, footprints) | `SYMBOL` / `FOOTPRINT` documents |
| library devices | `devices` table + the `attributes` table | `DEVICE` documents, their `META.attributes` |
| the library's own ids | `devices.source` = `"<libraryDocUuid>|<libraryUuid>"` | `META.source`, the same form |
| placements | the schematic document's array records | the `SCH_PAGE` document's records |

Both end at the same two facts the harvest needs: **the designator → device
link**, and **the device's attributes** — from which come the LCSC C-number, the
MPN, and the footprint document whose title is the library vocabulary name
(`R0402`).

What this module will not do is pretend an unreadable board was empty. A local
project that was saved as an edit log only has no `devices` and no `attributes`
rows, and therefore no LCSC, no MPN and no footprint anywhere in it; the reader
raises with that explanation rather than returning an empty project that
downstream code would report as "0 entries harvested". (Measured 2026-09-16: the
same two boards, one shape gives nothing and the other gives 41 and 89 devices
with full identity — which is why "re-save it locally or export `.epro2`" is
the right advice, and why this module exists in two halves.)

Read-only throughout. These files are 岳翔宇's own projects.
"""

from __future__ import annotations

import base64
import gzip
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..core.geometry import ParseStats
from ..core.parts import UNKNOWN
from .epru_stream import EncryptedProjectError, iter_epru_records, load_epru_text

__all__ = [
    "DOC_PCB",
    "DOC_SCH_PAGE",
    "LocalDevice",
    "LocalDocument",
    "LocalLibraryDocument",
    "LocalPlacement",
    "LocalProject",
    "LocalProjectError",
    "device_provenance_labels",
    "library_footprint_name",
    "load_board_source",
    "load_exported_project",
    "load_local_project",
]

#: `documents.docType` values observed in the source boards (the local-project
#: side). Only the schematic page is needed; the PCB is recorded so a report can
#: say what a file contains.
DOC_SCH_PAGE = 1
DOC_PCB = 3

#: The document payload prefix in a local project: `<prefix><base64 of gzip>`.
_PAYLOAD_PREFIX = "base64"


class LocalProjectError(ValueError):
    """The file is not a readable board, or its shape is unknown."""


# --------------------------------------------------------------------------
# the common shape
# --------------------------------------------------------------------------


@dataclass
class LocalDocument:
    """One document of a local project, with its decoded record text."""

    uuid: str
    title: str
    display_title: str
    doc_type: int
    text: str


@dataclass
class LocalLibraryDocument:
    """One document of the board's library: a symbol, a footprint, a device."""

    uuid: str
    title: str
    doc_type: int
    library_doc_uuid: str = ""
    library_uuid: str = ""


@dataclass
class LocalDevice:
    """One library device **as this board holds it**.

    ``uuid`` is the key the schematic references. ``library_doc_uuid`` /
    ``library_uuid`` come from the ``source`` field and are the identity the
    *library* answers to — the pair ``lib.device.get`` and
    ``sch.place_component`` actually need. (006b measured that a project-local
    uuid answers ``found:false`` in the library, so the two must not be
    conflated.)
    """

    uuid: str
    title: str
    display_title: str
    library_doc_uuid: str = ""
    library_uuid: str = ""
    attributes: dict[str, str] = field(default_factory=dict)

    @property
    def is_real_part(self) -> bool:
        """A device with an LCSC C-number: an actual orderable part.

        The other kind is the abstract placeholder (``Res_0603`` / ``CAP_0402``
        with only a ``Value``), which is the shape that caused 006b's "library
        swap". It carries no identity, so it cannot become a curated entry —
        reported rather than silently skipped.
        """
        return bool(self.attributes.get("Supplier Part"))


@dataclass
class LocalPlacement:
    """One placed component: its designator and the device it uses."""

    designator: str
    device_uuid: str


@dataclass
class LocalProject:
    """Everything the harvester needs from one board file."""

    path: str
    name: str = ""
    project_uuid: str = ""
    #: Which reader produced this: `"eprj2-local"` or `"epro2-export"`. Reported,
    #: because the same board can be harvestable in one format and not the other.
    kind: str = ""
    documents: list[LocalDocument] = field(default_factory=list)
    library_docs: dict[str, LocalLibraryDocument] = field(default_factory=dict)
    devices: dict[str, LocalDevice] = field(default_factory=dict)
    placements: list[LocalPlacement] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def materialised(self) -> bool:
        """Does this file carry its documents and library, or only an edit log?"""
        return bool(self.devices) or bool(self.library_docs)

    def referable_devices(self) -> dict[str, LocalDevice]:
        """The devices the schematic actually places, keyed by device uuid."""
        used = {p.device_uuid for p in self.placements if p.device_uuid}
        return {u: d for u, d in self.devices.items() if u in used}

    def designators_by_device(self) -> dict[str, list[str]]:
        """Device uuid -> the designators that use it, sorted."""
        out: dict[str, list[str]] = {}
        for placement in self.placements:
            if placement.device_uuid and placement.designator:
                out.setdefault(placement.device_uuid, []).append(placement.designator)
        return {uuid: sorted(set(names)) for uuid, names in out.items()}


def device_provenance_labels(project: LocalProject, device_uuid: str) -> list[str]:
    """``["U1"]`` — the designators this board places that device under."""
    return project.designators_by_device().get(device_uuid, [])


def library_footprint_name(project: LocalProject, device: LocalDevice) -> tuple[str, bool | None]:
    """``(library footprint name, verified)`` for a device.

    The name comes from the device's ``Footprint`` attribute resolved through the
    board's document table — that is the **library** spelling (``R0402``).
    ``verified`` is :data:`~boardwise.core.parts.UNKNOWN` here: confirming it
    against the live library is the bridge's job, and until it has run this is
    "read from the board", not "confirmed by the library".
    """
    footprint_uuid = (device.attributes.get("Footprint") or "").strip()
    if not footprint_uuid:
        return ("", UNKNOWN)
    document = project.library_docs.get(footprint_uuid)
    if document is None:
        return ("", UNKNOWN)
    return (document.title, UNKNOWN)


# NOTE (2026-09-16): there used to be a `footprint_library_uuid()` here, feeding
# the footprint *document* uuid into `lib.footprint.get`. It is gone on purpose:
# measured on the machine, that call fails — a project-local document uuid is not
# a library key (the same fact 006b recorded for project-local symbol uuids).
# The library's footprint uuid comes from `lib.device.get` →
# `item.association.footprintUuid`. Recorded here so nobody re-derives it.


def _split_source(source: str) -> tuple[str, str]:
    """``"<libraryDocUuid>|<libraryUuid>"`` -> ``(doc_uuid, library_uuid)``."""
    text = (source or "").strip()
    if "|" not in text:
        return ("", "")
    head, _, tail = text.partition("|")
    return (head.strip(), tail.strip())


# --------------------------------------------------------------------------
# `.eprj2` — the local project database
# --------------------------------------------------------------------------


def _table_names(cursor: sqlite3.Cursor) -> set[str]:
    return {row[0] for row in cursor.execute("select name from sqlite_master where type='table'")}


def _decode_payload(data_str: str, where: str) -> str:
    """``base64<BASE64 of gzip>`` -> record text.

    Raises rather than guessing: a payload that does not carry the known prefix
    is a different serialisation, and reading it with today's rules would
    produce silently wrong records.
    """
    if not isinstance(data_str, str) or not data_str.startswith(_PAYLOAD_PREFIX):
        raise LocalProjectError(
            f"{where}: document payload does not start with {_PAYLOAD_PREFIX!r} "
            f"(got {str(data_str)[:12]!r}); this file's serialisation is unknown"
        )
    try:
        blob = base64.b64decode(data_str[len(_PAYLOAD_PREFIX):])
    except ValueError as exc:
        raise LocalProjectError(f"{where}: payload is not base64: {exc}") from exc
    try:
        return gzip.decompress(blob).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LocalProjectError(f"{where}: payload is not gzip text: {exc}") from exc


def _array_placements(text: str, where: str) -> list[LocalPlacement]:
    """Designator -> device uuid from a local project's schematic records.

    Only two record types are read, and only the fields whose position is
    confirmed on the real files::

        ["COMPONENT", <id>, …]
        ["ATTR", <id>, <parentId>, "Designator"|"Device", <value>, …]

    Grouping by ``parentId`` was checked against grouping by stream adjacency on
    the real page — 98 instances, identical result — so either would do; the
    explicit parent link is the one that cannot drift when records are
    reordered.
    """
    attributes: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or not stripped.startswith("["):
            continue
        try:
            record = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(record, list) or not record:
            continue
        kind = record[0]
        if kind == "COMPONENT" and len(record) >= 2:
            component_id = str(record[1])
            if component_id not in attributes:
                attributes[component_id] = {}
                order.append(component_id)
        elif kind == "ATTR" and len(record) >= 5:
            key = str(record[3] or "")
            if key not in ("Designator", "Device"):
                continue
            value = record[4]
            if value is None:
                continue
            parent = str(record[2])
            attributes.setdefault(parent, {})[key] = str(value).strip()
            if parent not in order:
                order.append(parent)

    out: list[LocalPlacement] = []
    for component_id in order:
        attrs = attributes.get(component_id) or {}
        designator = attrs.get("Designator", "")
        device = attrs.get("Device", "")
        if not designator or not device:
            # Power flags and the title-block frame have a Device but no
            # designator; a designator without a device is a part with no
            # library identity. Neither is a placement the harvester can use.
            continue
        out.append(LocalPlacement(designator=designator, device_uuid=device))
    if not out:
        raise LocalProjectError(f"{where}: no placed component with both a designator and a device")
    return sorted(out, key=lambda p: (p.designator, p.device_uuid))


def _project_identity(cursor: sqlite3.Cursor, tables: set[str]) -> tuple[str, str]:
    if "projects" not in tables:
        return ("", "")
    row = cursor.execute("select uuid, name from projects limit 1").fetchone()
    if not row:
        return ("", "")
    return (str(row[1] or ""), str(row[0] or ""))


def load_local_project(path: str | Path) -> LocalProject:
    """Read a local project database (``.eprj2``). Read-only; never writes."""
    source = Path(path)
    if not source.is_file():
        raise LocalProjectError(f"{source}: not a file")
    try:
        connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:  # pragma: no cover - depends on the filesystem
        raise LocalProjectError(f"{source}: cannot open read-only: {exc}") from exc

    project = LocalProject(path=str(source), kind="eprj2-local")
    try:
        cursor = connection.cursor()
        tables = _table_names(cursor)
        if "documents" not in tables:
            raise LocalProjectError(
                f"{source}: no 'documents' table — this is not an EasyEDA local project"
            )

        project.name, project.project_uuid = _project_identity(cursor, tables)

        for uuid, title, display, doc_type, data_str in cursor.execute(
            "select uuid, title, display_title, docType, dataStr from documents"
        ).fetchall():
            text = _decode_payload(data_str, f"{source}: document {title or uuid!r}")
            project.documents.append(
                LocalDocument(
                    uuid=str(uuid),
                    title=str(title or ""),
                    display_title=str(display or ""),
                    doc_type=int(doc_type),
                    text=text,
                )
            )

        # An edit-log-only project is a whole-file condition, not a missing-page
        # one: nothing is materialised, so there is no library identity anywhere
        # in it. Saying "no schematic page" here would send a reader looking for
        # the wrong thing, and 004's recon already showed why it is empty.
        if not project.documents:
            raise LocalProjectError(
                f"{source}: this project holds only an edit log — its documents "
                "and library attributes were never saved into the file, so it "
                "carries no LCSC / MPN / footprint identity and cannot seed a "
                "part library. Re-save the project locally, or export an .epro2."
            )

        if "components" in tables:
            for uuid, title, doc_type, src in cursor.execute(
                "select uuid, title, docType, source from components"
            ).fetchall():
                doc_uuid, library_uuid = _split_source(src or "")
                project.library_docs[str(uuid)] = LocalLibraryDocument(
                    uuid=str(uuid),
                    title=str(title or ""),
                    doc_type=int(doc_type),
                    library_doc_uuid=doc_uuid,
                    library_uuid=library_uuid,
                )

        if "devices" in tables:
            for uuid, title, display, src in cursor.execute(
                "select uuid, title, display_title, source from devices"
            ).fetchall():
                doc_uuid, library_uuid = _split_source(src or "")
                project.devices[str(uuid)] = LocalDevice(
                    uuid=str(uuid),
                    title=str(title or ""),
                    display_title=str(display or ""),
                    library_doc_uuid=doc_uuid,
                    library_uuid=library_uuid,
                )

        if "attributes" in tables and project.devices:
            # `.fetchall()` before walking: reusing the cursor inside the loop
            # resets it, and the outer iteration then silently stops after one
            # row (measured the hard way — a board looked like it had one part).
            rows = cursor.execute(
                "select device_uuid, key, value from attributes"
            ).fetchall()
            for device_uuid, key, value in rows:
                device = project.devices.get(str(device_uuid))
                if device is None or value is None:
                    continue
                device.attributes[str(key)] = str(value)

        pages = [d for d in project.documents if d.doc_type == DOC_SCH_PAGE]
        if not pages:
            raise LocalProjectError(
                f"{source}: no schematic page document (docType={DOC_SCH_PAGE})"
            )
        seen: dict[str, LocalPlacement] = {}
        for page in pages:
            for placement in _array_placements(page.text, f"{source}: {page.title}"):
                seen.setdefault(placement.designator, placement)
        project.placements = sorted(seen.values(), key=lambda p: p.designator)
    finally:
        connection.close()
    return project


# --------------------------------------------------------------------------
# `.epro2` — the exported project
# --------------------------------------------------------------------------

#: Document types an exported project keeps that matter here. `split_documents`
#: in `epru_stream` keeps PCB/FOOTPRINT/DEVICE only, so this reader walks the
#: record stream itself: it also needs SYMBOL (nothing here, but a footprint's
#: sibling) and, importantly, `SCH_PAGE` for the placements.
_EXPORT_DOC_TYPES = ("DEVICE", "FOOTPRINT", "SYMBOL", "SCH_PAGE")


def load_exported_project(path: str | Path) -> LocalProject:
    """Read an exported project (``.epro2``) — one ``.epru`` record stream.

    Two passes over the same stream, deliberately:

    * the **metadata** pass here needs only ``DOCHEAD`` + ``META``, and it needs
      ``META.source`` (``"<libraryDocUuid>|<libraryUuid>"``), which the existing
      device-meta collector does not read;
    * the **placement** link comes from
      :func:`boardwise.parsers.schematic.collect_part_devices`, i.e. from the
      proven ``_split_page`` grouping. Re-deriving "which ATTRs belong to this
      COMPONENT" was tried and measured wrong: the rule has four clauses and a
      version that missed one attributed designators to the wrong device
      (85 placements found, a different 85 than the parser's).
    """
    from .schematic import collect_library_documents, collect_part_devices

    source = Path(path)
    try:
        text, meta = load_epru_text(source)
    except EncryptedProjectError as exc:
        raise LocalProjectError(f"{source}: {exc}") from exc

    stats = ParseStats(source=str(source), editor_version=meta.get("editorVersion"))
    project = LocalProject(
        path=str(source), name=str(meta.get("title") or ""), kind="epro2-export"
    )

    devices: dict[str, LocalDevice] = {}
    current_uuid = ""
    current_device: LocalDevice | None = None
    for record in iter_epru_records(text, stats):
        if record.type == "DOCHEAD":
            body = record.body or {}
            in_device = str(body.get("docType") or "") == "DEVICE"
            current_uuid = str(body.get("uuid") or "") if in_device else ""
            current_device = None
            if in_device and current_uuid:
                current_device = LocalDevice(uuid=current_uuid, title="", display_title="")
                devices[current_uuid] = current_device
            continue
        if current_device is None or record.type != "META":
            continue
        body = record.body or {}
        title = str(body.get("title") or "")
        doc_uuid, library_uuid = _split_source(str(body.get("source") or ""))
        current_device.title = title
        current_device.display_title = title
        current_device.library_doc_uuid = doc_uuid
        current_device.library_uuid = library_uuid
        attributes = body.get("attributes") or {}
        if isinstance(attributes, dict):
            for key, value in attributes.items():
                if value is None or str(value) in ("", "null"):
                    continue
                current_device.attributes[str(key)] = str(value).strip()
        current_device = None  # one META per document

    for uuid, (title, src) in collect_library_documents(source).items():
        doc_uuid, library_uuid = _split_source(src)
        project.library_docs[uuid] = LocalLibraryDocument(
            uuid=uuid,
            title=title,
            doc_type=0,
            library_doc_uuid=doc_uuid,
            library_uuid=library_uuid,
        )

    placements = collect_part_devices(source)
    if not placements:
        raise LocalProjectError(
            f"{source}: no placed component with both a designator and a device"
        )
    project.devices = devices
    project.placements = [
        LocalPlacement(designator=designator, device_uuid=device)
        for designator, device in sorted(placements.items())
    ]
    if not project.devices:
        project.notes.append(
            "this export carries no DEVICE document, so it has no library "
            "identity to harvest"
        )
    return project


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

#: Suffix -> reader. The harvest takes whatever boards it is given, so the
#: format is decided by the file, in one place.
_READERS = {
    ".eprj2": load_local_project,
    ".epro2": load_exported_project,
}


def load_board_source(path: str | Path) -> LocalProject:
    """Read a board of either format. Raises :class:`LocalProjectError`."""
    source = Path(path)
    reader = _READERS.get(source.suffix.lower())
    if reader is None:
        raise LocalProjectError(
            f"{source}: unsupported board format {source.suffix or '(none)'!r}; "
            f"known: {', '.join(sorted(_READERS))}"
        )
    return reader(source)
