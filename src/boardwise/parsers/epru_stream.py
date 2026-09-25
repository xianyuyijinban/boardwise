"""The ``.epru`` record *stream* — framing, decoding and document splitting.

Split out of :mod:`boardwise.parsers.epru` (006c, work item 4). The framing
layer used to live inside the PCB-geometry module, which meant the schematic
parser had to import a **private** name (``load_epru_text``) from the copper
builder in order to read a text file: two unrelated concerns sharing a module,
with the schematic side paying the coupling cost.

Format facts this module owns (reverse-engineered, see ``docs/epru-format.md``;
"confirmed" there means checked on the LLC fixture):

- ``.epro2`` is a ZIP holding ``project2.json`` plus one ``*.epru`` per document
  stream. **Zip entry names may be mojibake'd Chinese**, so the ``.epru`` member
  is matched by extension, never by name.
- ``.epru`` is a line record format: ``{envelope-json}||{body-json}|``
  terminated by ``\n``. Two real-world deviations are tolerated: the final line
  may lack the terminator, and a record may carry an **empty body**
  (``{envelope}|||``) — counted as ``empty_body_records`` and skipped, since
  there is no payload to read.
- The stream is a concatenation of **documents**, each introduced by a
  ``DOCHEAD`` record carrying a ``docType``. On the fixture: 252 documents —
  83 SYMBOL, 81 FOOTPRINT, 81 DEVICE, 1 SCH, 1 SCH_PAGE, **1 PCB**, ...

Everything is read in a single streaming pass. Unknown record types are counted
and skipped; malformed lines are counted and skipped. Neither ever raises.

What does **not** belong here: anything that knows what a pad, a track or a
netlist is. Those are views *over* this stream and live in
:mod:`boardwise.parsers.epru` (copper) and
:mod:`boardwise.parsers.epro2_model` (connectivity).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

#: Re-exported from :mod:`boardwise.core.geometry`, where it actually lives: a
#: :class:`~boardwise.core.geometry.BoardGeometry` carries one, so the type
#: belongs to the geometry model — moving it down here would invert the
#: layering (``core`` must not import ``parsers``). Importers of the stream get
#: it from this module so that reading the framing code does not require
#: knowing that.
from ..core.geometry import ParseStats

__all__ = [
    "DEVICE_DOC_TYPE",
    "Document",
    "EncryptedProjectError",
    "EpruRecord",
    "FIELD_SEP",
    "FOOTPRINT_DOC_TYPE",
    "KEPT_DOC_TYPES",
    "KNOWN_RECORD_TYPES",
    "PCB_DOC_TYPE",
    "ParseStats",
    "iter_epru_records",
    "load_epru_text",
    "read_project_meta",
    "split_documents",
]


class EncryptedProjectError(ValueError):
    """Raised when an ``.epro2`` file cannot be read at all.

    EasyEDA Pro's "save project as (local)" dialog offers an optional
    encryption checkbox. An encrypted export is not a ZIP archive, and an
    archive whose entries carry the encryption flag cannot be read either.
    Both cases land here with an actionable message instead of a confusing
    ``zipfile.BadZipFile`` / ``JSONDecodeError`` stack.
    """

#: Document types that hold data we need.
PCB_DOC_TYPE = "PCB"
FOOTPRINT_DOC_TYPE = "FOOTPRINT"
DEVICE_DOC_TYPE = "DEVICE"

#: Document types kept by :func:`split_documents`. Everything else is
#: dropped after counting, so memory stays proportional to useful data.
KEPT_DOC_TYPES: frozenset[str] = frozenset(
    {PCB_DOC_TYPE, FOOTPRINT_DOC_TYPE, DEVICE_DOC_TYPE}
)

#: Record types observed on the fixture. Anything outside this set is
#: reported in ``ParseStats.unknown_types`` — i.e. the format drifted.
KNOWN_RECORD_TYPES: frozenset[str] = frozenset(
    {
        "ACTIVE_LAYER", "ARC", "ATTR", "BEZIER", "BLOB", "CANVAS", "CIRCLE",
        "COMPONENT", "DIMENSION", "DOCHEAD", "ELE_PLACEHOLDER", "ELLIPSE",
        "FILL", "FONT", "GROUP", "LAYER", "LAYER_PHYS", "LINE", "META",
        "NET", "OBJ", "PAD", "PAD_NET", "PANELIZE", "PART", "PIN",
        "POLY", "POURED", "PREFERENCE", "PRIMITIVE", "RECT", "RULE",
        "RULE_SELECTOR", "RULE_TEMPLATE", "SILK_OPTS", "STRING", "TEXT",
        "VIA", "WIRE",
    }
)

#: Separator between envelope JSON and body JSON.
FIELD_SEP = "||"

@dataclass
class EpruRecord:
    """One decoded ``.epru`` line."""

    line_no: int
    type: str
    ticket: int | None = None
    id: str | None = None
    first_ticket: int | None = None
    body: dict[str, Any] | None = None

    @property
    def has_body(self) -> bool:
        return self.body is not None

@dataclass
class Document:
    """A ``DOCHEAD``-delimited document and the records that follow it."""

    doc_type: str | None
    uuid: str | None
    edit_version: str | None
    records: list[EpruRecord] = field(default_factory=list)

def iter_epru_records(text: str, stats: ParseStats | None = None) -> Iterator[EpruRecord]:
    """Decode ``.epru`` text record by record.

    Yields only well-formed records; malformed lines and empty-body records
    are counted on ``stats`` when one is passed. Never raises on bad input.
    """
    for line_no, line in enumerate(text.split("\n")):
        if not line:
            continue
        if stats is not None:
            stats.total_records += 1

        # A record ends with "|"; the final line of a file may not have one.
        core = line[:-1] if line.endswith("|") else line
        if FIELD_SEP not in core:
            if stats is not None:
                stats.malformed_records += 1
            continue

        envelope_text, body_text = core.split(FIELD_SEP, 1)
        try:
            envelope = json.loads(envelope_text)
        except ValueError:
            if stats is not None:
                stats.malformed_records += 1
            continue

        if not isinstance(envelope, dict):
            if stats is not None:
                stats.malformed_records += 1
            continue

        body: dict[str, Any] | None = None
        if body_text.strip():
            try:
                decoded = json.loads(body_text)
            except ValueError:
                if stats is not None:
                    stats.malformed_records += 1
                continue
            body = decoded if isinstance(decoded, dict) else None
        else:
            if stats is not None:
                stats.empty_body_records += 1

        record_type = str(envelope.get("type", ""))
        if stats is not None:
            stats.records_by_type[record_type] = stats.records_by_type.get(record_type, 0) + 1
            if record_type not in KNOWN_RECORD_TYPES:
                stats.unknown_types[record_type] = stats.unknown_types.get(record_type, 0) + 1

        yield EpruRecord(
            line_no=line_no,
            type=record_type,
            ticket=envelope.get("ticket"),
            id=envelope.get("id"),
            first_ticket=envelope.get("firstTicket"),
            body=body,
        )

def split_documents(text: str, stats: ParseStats) -> list[Document]:
    """Split the record stream into documents, keeping only the ones we need.

    A new document starts at every ``DOCHEAD`` record. Only PCB, FOOTPRINT
    and DEVICE documents are retained (records of all others are dropped
    after counting) so memory stays proportional to the useful data:

    * PCB       — the board: placements, copper, nets.
    * FOOTPRINT — pad shapes, instantiated per placement.
    * DEVICE    — library metadata (Value / LCSC / Manufacturer) joined to
      a placement through its ``Device`` attribute.
    """
    documents: list[Document] = []
    current: Document | None = None
    for record in iter_epru_records(text, stats):
        if record.type == "DOCHEAD":
            body = record.body or {}
            doc_type = body.get("docType")
            if doc_type is not None:
                stats.document_types[str(doc_type)] = stats.document_types.get(str(doc_type), 0) + 1
            current = Document(
                doc_type=doc_type,
                uuid=body.get("uuid"),
                edit_version=body.get("editVersion"),
            )
            if doc_type in KEPT_DOC_TYPES:
                documents.append(current)
                current.records.append(record)
            else:
                current = None
            continue
        if current is not None:
            current.records.append(record)
    return documents

# --------------------------------------------------------------------------
# archive reading
# --------------------------------------------------------------------------

def read_project_meta(path: str | Path) -> dict[str, Any]:
    """Read ``project2.json`` from an ``.epro2`` archive.

    Returns an empty dict when the archive has no project metadata, which
    keeps callers from having to special-case older backups.
    """
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.filename.lower().endswith("project2.json"):
                try:
                    decoded = json.loads(archive.read(info).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    return {}
                return decoded if isinstance(decoded, dict) else {}
    return {}

def load_epru_text(path: str | Path) -> tuple[str, dict[str, Any]]:
    """The project's record stream and metadata — **whatever container it is in**.

    One seam, three containers: a ``.epro2`` ZIP (one ``.epru`` stream inside it),
    and — since 038 — an **eprj3 folder** (one file per document, glued back into a
    single stream by :mod:`boardwise.parsers.eprj3`). Every caller above this line
    keeps taking ``(text, meta)`` and never learns which one it got, which is what
    made the V4 read-only tier a pure increment instead of eight call-site edits.

    Raises :class:`EncryptedProjectError` — with advice to re-export without
    the encryption option — when the file is not a readable ZIP, when its
    entries are flagged encrypted, or when nothing decodes. An eprj3 folder that
    cannot be read raises the same class from the reader (one refusal type for
    "this input is not readable", whatever the reason).
    """
    source_path = Path(path)
    from .eprj3 import Eprj3Error, load_eprj3_text, looks_like_eprj3

    if looks_like_eprj3(source_path):
        try:
            return load_eprj3_text(source_path)
        except Eprj3Error as exc:
            raise EncryptedProjectError(str(exc)) from exc
    hint = (
        "This project backup cannot be read. EasyEDA Pro's \"save as (local)\" "
        "dialog has an optional encryption checkbox — if the export was "
        "encrypted, re-export it with that option disabled and try again."
    )
    if not zipfile.is_zipfile(source_path):
        raise EncryptedProjectError(
            f"{source_path}: not an EasyEDA .epro2 archive (not a ZIP file). {hint}"
        )
    try:
        with zipfile.ZipFile(source_path) as archive:
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".epru")]
            if not members:
                raise EncryptedProjectError(
                    f"{source_path}: no .epru document stream inside the archive. {hint}"
                )
            if any(i.flag_bits & 0x1 for i in members):
                raise EncryptedProjectError(
                    f"{source_path}: archive entries are password-protected. {hint}"
                )
            member = max(members, key=lambda i: i.file_size)
            try:
                raw = archive.read(member)
            except (RuntimeError, zipfile.BadZipFile) as exc:
                # RuntimeError is what zipfile raises for encrypted/CRC-broken data.
                raise EncryptedProjectError(f"{source_path}: {exc}. {hint}") from exc
    except zipfile.BadZipFile as exc:
        raise EncryptedProjectError(f"{source_path}: corrupt archive ({exc}). {hint}") from exc

    meta = read_project_meta(source_path)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return text, meta
