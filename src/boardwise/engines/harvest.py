"""Harvesting a curated part library out of boards (task 008b, work item 2).

008c will need a deterministic shelf of *real* parts. This module fills it from
boards the designer already built: every placed component contributes the
identity its library device carries — MPN, LCSC C-number, the library's own
device and footprint uuids, the footprint's **library** name, and the electrical
parameters verbatim.

Four rules the task sets, and what each one means in code:

1. **Walk the components.** Only devices the schematic actually *places* are
   harvested; a device sitting unused in the project's library has no
   designator, so it has no provenance and nothing to contribute.
2. **The vocabulary must be the library's.** ``footprint_name`` is the
   footprint document's own title (``R0402``), never the human label in
   ``Supplier Footprint`` (``0603``) — 006b measured what happens when the two
   are treated as one thing. When the name cannot be read, the field is empty
   and marked unverified: a guess here is worse than a blank.
3. **Merge by identity, keep the history.** The same C-number across boards
   becomes one entry, and ``provenance.designators`` accumulates
   ``"U1@smart_pillbox"``, ``"U5@thesis_FOC_board"`` — that track record is the
   confidence signal, so it is extended rather than overwritten. Duplicates are
   not re-added, which is also what makes re-running the tool idempotent.
4. **A conflict is recorded, not resolved.** When two boards describe the same
   C-number differently, the entry keeps the first (deterministic order) value
   and gains a note naming both. #202's discipline is that an unresolvable
   disagreement is reported, never averaged into a plausible-looking number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path

from ..core.parts import (
    FALSE,
    TRUE,
    UNKNOWN,
    LibraryCorrections,
    PartEntry,
    PartLibrary,
    PartProvenance,
    category_of,
    make_key,
)
from ..parsers.board_source import (
    LocalDevice,
    LocalProject,
    LocalProjectError,
    library_footprint_name,
    load_board_source,
)

#: Attribute keys that are **identity or bookkeeping**, not electrical
#: parameters. They have their own fields on the entry; keeping them out of
#: `params` is what makes "the electrical parameters verbatim" mean something.
NON_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "Supplier Part",
        "Manufacturer Part",
        "Manufacturer",
        "Supplier",
        "Datasheet",
        "LCSC Part Name",
        "JLCPCB Part Class",
        "Footprint",
        "Symbol",
        "3D Model",
        "3D Model Title",
        "3D Model Transform",
        "Add into BOM",
        "Convert to PCB",
        "Designator",
        "Name",
        "Global Net Name",
        "Value",
    }
)

#: ``JLCPCB Part Class`` -> the basic-part flag. The three spellings are the
#: measured ones: 岳翔宇's library writes 基础库/扩展库, and the imported catalog
#: parts (CH340N, DRV8350) write JLC's own English "Extended Part". Matching only
#: the Chinese pair would leave those two reported as "no evidence", which is a
#: false claim — the evidence is right there, in a third spelling.
BASIC_CLASS_EVIDENCE: dict[str, bool] = {
    "基础库": TRUE,
    "扩展库": FALSE,
    "basic": TRUE,
    "extended part": FALSE,
    "extended": FALSE,
}


#: ``(device uuid, library uuid) -> the library's footprint name, or ``None``
#: when it could not be asked``. The bridge is the only implementation; tests
#: pass a dictionary lookup, which is also how the live step stays opt-in.
#:
#: It is asked about the **device**, not about the project's footprint document.
#: Measured 2026-09-16 on the machine: a project-local footprint uuid fails in
#: `lib.footprint.get`, exactly as 006b found for project-local *symbol* uuids.
#: The working chain is `lib.device.get(device) → association.footprintUuid →
#: lib.footprint.get(footprintUuid)` — which is why the key here is the device
#: pair and the footprint uuid is looked up inside the live library.
Verifier = Callable[[str, str], "str | None"]


class HarvestError(ValueError):
    """The harvest cannot be performed as asked."""


@dataclass
class SourceReport:
    """What one board contributed (or why it could not)."""

    path: str
    board: str
    placements: int = 0
    real_parts: int = 0
    entries: int = 0
    #: Placed devices with no C-number: the abstract placeholders.
    placeholder_devices: list[str] = field(default_factory=list)
    #: Library devices this board never placed.
    unused_devices: int = 0
    #: Dangling references: a placement naming a device the file does not hold.
    missing_devices: list[str] = field(default_factory=list)
    #: Which format this board was read as (`eprj2-local` / `epro2-export`).
    #: Reported because the *same* board can be harvestable in one and not the
    #: other — that is the whole point of the two readers.
    kind: str = ""
    notes: list[str] = field(default_factory=list)
    skipped_reason: str = ""

    @property
    def ok(self) -> bool:
        return not self.skipped_reason


@dataclass
class HarvestResult:
    """The library plus everything a reader needs to judge it."""

    library: PartLibrary = field(default_factory=PartLibrary)
    sources: list[SourceReport] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    report: list[str] = field(default_factory=list)

    @property
    def entries(self) -> int:
        return len(self.library.parts)


def source_label(path: str | Path) -> str:
    """The path recorded in an entry's provenance — stable, and repo-relative.

    A committed library must not embed somebody's absolute directory: the file
    is meant to be reproducible from the repository, and a provenance string
    that changes with the caller's cwd would make the harvest look
    non-deterministic when it is not. So the label is the path relative to the
    nearest directory holding a ``pyproject.toml`` when the source lives under
    one, and the plain path otherwise.
    """
    source = Path(path)
    for parent in [source.resolve(), *source.resolve().parents]:
        if (parent / "pyproject.toml").is_file():
            try:
                return source.resolve().relative_to(parent).as_posix()
            except ValueError:  # pragma: no cover - cannot happen for a descendant
                break
    return source.as_posix()


@dataclass
class PlacedDevices:
    """The devices a board contributes entries for, and what was left out.

    One definition of "which devices this board is harvested for", used by both
    the harvester and the bridge verification — two copies of that rule is how
    the verifier and the harvest drift apart.
    """

    #: designator -> device (the first placement of a designator wins).
    devices: dict[str, LocalDevice] = field(default_factory=dict)
    #: Placed devices with no C-number: abstract placeholders, not curatable.
    placeholders: list[str] = field(default_factory=list)
    #: Placements naming a device the file does not hold.
    missing: list[str] = field(default_factory=list)


def placed_devices(project: LocalProject) -> PlacedDevices:
    """Walk a board's placements and keep the devices that can be curated."""
    out = PlacedDevices()
    for placement in project.placements:
        device = project.devices.get(placement.device_uuid)
        if device is None:
            out.missing.append(f"{placement.designator} -> {placement.device_uuid[:10]}")
            continue
        if not device.is_real_part:
            name = device.display_title or device.title
            if name not in out.placeholders:
                out.placeholders.append(name)
            continue
        out.devices.setdefault(placement.designator, device)
    return out


def devices_to_verify(
    sources: list[str | Path],
    *,
    corrections: "LibraryCorrections | None" = None,
) -> dict[tuple[str, str], str]:
    """The distinct device uuid pairs a harvest of ``sources`` will ask about.

    ``(library device uuid, library uuid) -> a label for the report``. Keyed by
    the device pair because that is what the bridge chain starts from; boards
    that cannot be read simply contribute nothing.

    The identity corrections are applied here too, and that is not an
    optimisation: the harvest will ask about the corrected pair, so a verifier
    that asked about the board's original one would answer `found:false` for
    exactly the entries the correction was written for.
    """
    wanted: dict[tuple[str, str], str] = {}
    for path in sources:
        try:
            project = load_board_source(path)
        except LocalProjectError:
            continue
        for device in placed_devices(project).devices.values():
            lcsc = (device.attributes.get("Supplier Part") or "").strip()
            override = corrections.identity_for(lcsc) if corrections else None
            if override is not None:
                pair = (override.deviceUuid, override.libraryUuid)
            else:
                pair = (device.library_doc_uuid, device.library_uuid)
            if not all(pair):
                continue
            wanted.setdefault(
                pair, device.display_title or device.title or pair[0]
            )
    return dict(sorted(wanted.items()))


#: The paths inside a `lib.device.get` dump that may carry the library footprint
#: uuid, in the order they are tried. The first one is the measured working
#: chain; the others are shape variants, and whichever answers is **reported**
#: rather than assumed — an unverified field name is exactly how a silent
#: "no such part" arrives.
FOOTPRINT_UUID_PATHS: tuple[tuple[str, ...], ...] = (
    ("association", "footprintUuid"),
    ("association", "footprint", "uuid"),
    ("association", "footprint"),
    ("footprintUuid",),
    ("footprint", "uuid"),
)


def footprint_uuid_of_device(item: object) -> tuple[str, str]:
    """``(footprint uuid, path)`` from a ``lib.device.get`` dump, or ``("", "")``.

    ``path`` is dotted, so a report can say which field the answer came from.
    """
    for path in FOOTPRINT_UUID_PATHS:
        node: object = item
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node.strip():
            return (node.strip(), ".".join(path))
    return ("", "")


def basic_flag(attributes: dict[str, str]) -> tuple[bool | None, str]:
    """``(flag, note)`` for the JLC basic-part marker, from evidence only."""
    raw = (attributes.get("JLCPCB Part Class") or "").strip()
    if not raw:
        return (UNKNOWN, "")
    flag = BASIC_CLASS_EVIDENCE.get(raw.lower())
    if flag is None:
        return (UNKNOWN, f"unrecognised JLCPCB Part Class {raw!r}; basic left unknown")
    return (flag, "")


def parameters_of(attributes: dict[str, str]) -> dict[str, str]:
    """The electrical/mechanical parameters, **verbatim**, units kept.

    No normalisation and no unit conversion: `"5.1kΩ ±1%"` is stored as written.
    A consumer that needs a number applies the value gate to the original text,
    which is the only place the SI prefix's case can still be honoured.
    """
    return {
        key: value
        for key, value in sorted(attributes.items())
        if key not in NON_PARAM_KEYS and not key.startswith("@") and value not in ("", "null")
    }


def _entry_for(
    project: LocalProject,
    device: LocalDevice,
    designator: str,
    board: str,
    verifier: "Verifier | None" = None,
    corrections: "LibraryCorrections | None" = None,
) -> PartEntry:
    """One placed device -> one candidate entry (before merging).

    ``verifier`` is the optional bridge check of the footprint name. It is asked
    about the **device's** library uuid pair and answers the name the live
    library uses; the footprint uuid itself is resolved inside the library, not
    taken from the project (a project-local footprint uuid is rejected there —
    measured). Keeping the check a callable rather than a field on the entry is
    deliberate: the library's field list is fixed by the task, and a
    project-local uuid does not belong in the curated shelf.

    ``corrections`` carries the two facts a board cannot supply (008b tail):
    the **identity** of entries whose stored library uuid cannot be a library
    key, and each entry's **datasheet PDF link** (a board carries a web page,
    not a file). The identity is applied *before* the verifier runs, so the
    bridge is asked about the identity the entry will actually carry — asking
    about the old one would answer `found:false` and leave an entry unverified
    for the very reason the correction exists to remove.
    """
    attributes = device.attributes
    footprint_name, footprint_verified = library_footprint_name(project, device)
    lcsc = (attributes.get("Supplier Part") or "").strip()
    override = corrections.identity_for(lcsc) if corrections else None
    if override is not None:
        device_uuid, library_uuid = override.deviceUuid, override.libraryUuid
    else:
        device_uuid, library_uuid = device.library_doc_uuid, device.library_uuid
    has_device_pair = bool(device_uuid and library_uuid)
    corrected_from = ""
    if verifier is not None and has_device_pair:
        checked = verifier(device_uuid, library_uuid)
        if checked is None:
            footprint_verified = UNKNOWN
        else:
            # The *library's* spelling is the vocabulary (`R0402`), and the
            # project's document title is a copy of it that can differ in case
            # (`r0402`) or be stale. So the library's answer is adopted, and a
            # difference is recorded rather than left as a silent mismatch.
            footprint_verified = TRUE
            if checked != footprint_name:
                corrected_from = footprint_name
                footprint_name = checked
    basic, basic_note = basic_flag(attributes)
    value = (attributes.get("Value") or "").strip()
    mpn = (attributes.get("Manufacturer Part") or "").strip()

    category = category_of(footprint_name, attributes.get("Designator", ""))
    key = make_key(
        category=category,
        value=value,
        mpn=mpn,
        footprint_name=footprint_name,
        title=device.display_title or device.title,
        lcsc=lcsc,
    )

    datasheet = corrections.datasheet_for(lcsc) if corrections else None

    notes: list[str] = []
    if override is not None and override.note:
        notes.append(override.note)
    if basic_note:
        notes.append(basic_note)
    if not footprint_name:
        notes.append(
            "the project's footprint document could not be read, so the library "
            "footprint name is empty (no name is guessed from the C-number)"
        )
    if corrected_from:
        notes.append(
            f"the library spells this footprint {footprint_name!r}; the project's "
            f"document said {corrected_from!r}. The library's spelling is kept "
            "(006b's vocabulary rule)."
        )
    if footprint_verified is UNKNOWN and verifier is not None and has_device_pair:
        notes.append(
            "the bridge could not be asked about this footprint name; it stays "
            "unverified rather than being assumed correct"
        )

    return PartEntry(
        key=key,
        value=value,
        mpn=mpn,
        lcsc=lcsc,
        manufacturer=(attributes.get("Manufacturer") or "").strip(),
        deviceUuid=device_uuid,
        libraryUuid=library_uuid,
        footprint_name=footprint_name,
        footprint_name_verified=footprint_verified,
        params=parameters_of(attributes),
        datasheetUrl=(attributes.get("Datasheet") or "").strip(),
        datasheetPdfUrl=datasheet.pdfUrl if datasheet is not None else "",
        basic=basic,
        provenance=PartProvenance(
            kind="board-extract",
            source=source_label(project.path),
            designators=[f"{designator}@{board}"],
            note=device.display_title or device.title,
        ),
        notes=notes,
    )


#: Fields a merge compares when the same C-number arrives from two boards. A
#: disagreement is *recorded*; the first value wins so the result is
#: deterministic, and the note says what the other board said.
_COMPARED_FIELDS = ("mpn", "manufacturer", "value", "footprint_name", "deviceUuid", "libraryUuid")


#: The fields whose value comes from the **live library** rather than from a
#: board: `lib.footprint.get` settles the spelling, and the run that asked is the
#: only thing that can say whether it did. An offline harvest cannot reproduce
#: them — which is a property of the *question*, not a weakness of the harvest —
#: so a comparison that claims anything without a bridge must set them aside, and
#: `--check --verify` is the comparison that does not have to.
#:
#: The rule lives here, in one place, because two copies of "which fields are
#: bridge-decided" is how a checker and its author stop agreeing.
BRIDGE_DECIDED_FIELDS = ("footprint_name", "footprint_name_verified")

#: Notes that only a bridge run can write. They are the *prose* half of the same
#: fact as `BRIDGE_DECIDED_FIELDS`: comparing them against a harvest that had no
#: bridge would report a difference in wording rather than in data.
BRIDGE_DECIDED_NOTE_MARKERS = ("spelling is kept", "could not be asked")

#: Library-level notes that exist because a bridge **ran**, not because of what
#: the boards say. `--verify` upgrades entries (`footprint_name` /
#: `footprint_name_verified` + the "spelling is kept" note), which is exactly
#: what retires the two spelling tallies: a name that was only ever spelled one
#: way stops being one once the live library answers for it. So a comparison
#: that had no bridge must set them aside as well — and the rule lives here so
#: the tool and the tests cannot write two versions of it.
#:
#: Matched by *marker* rather than by prefix: the note opens with a count, which
#: changes as soon as a board is added.
BRIDGE_DECIDED_LIBRARY_NOTE_MARKERS = (
    "footprint name(s) were spelled differently",
    "footprint name(s) are stored as their only source",
)


def strip_bridge_decided_notes(notes: list[str]) -> list[str]:
    """Library notes without the tallies only a bridge run resolves."""
    return [
        note
        for note in notes
        if not any(marker in note for marker in BRIDGE_DECIDED_LIBRARY_NOTE_MARKERS)
    ]


def spelling_notes(parts: list[PartEntry]) -> list[str]:
    """The library notes the footprint-spelling pass owes the reader.

    One definition, because the tool that writes the shelf and the tests that
    check it must count the same things the same way. Both tallies are
    *only* about what the boards spelled: `--verify` retires them by answering
    the question from the live library (see `BRIDGE_DECIDED_LIBRARY_NOTE_MARKERS`).
    """
    notes: list[str] = []
    spellings = sum(1 for p in parts if any("case-preserving" in n for n in p.notes))
    if spellings:
        notes.append(
            f"{spellings} footprint name(s) were spelled differently by different "
            "sources (a local project case-folds document titles; an export keeps "
            "the library's case). The case-preserving spelling is kept; "
            "`--verify` settles it against the live library."
        )
    folded_only = sum(
        1
        for p in parts
        if p.footprint_name and p.footprint_name == p.footprint_name.lower()
    )
    if folded_only:
        notes.append(
            f"{folded_only} footprint name(s) are stored as their only source "
            "spelled them, which for a local project is case-folded by the "
            "editor. Nothing is upper-cased here — a name with no second "
            "spelling has no evidence behind a rewrite. `--verify` replaces "
            "them with the library's own spelling."
        )
    return notes


def strip_bridge_decided(part: dict) -> dict:
    """A serialised entry without the fields (and notes) only a bridge settles."""
    clone = dict(part)
    for field_name in BRIDGE_DECIDED_FIELDS:
        clone.pop(field_name, None)
    clone["notes"] = [
        note
        for note in clone.get("notes", [])
        if not any(marker in note for marker in BRIDGE_DECIDED_NOTE_MARKERS)
    ]
    return clone


def prefer_footprint_spelling(first: str, second: str) -> tuple[str, bool]:
    """``(name, folded)`` for two spellings of the **same** footprint name.

    Measured 2026-09-16: the same footprint arrives as ``R0603`` from an
    ``.epro2`` export and ``r0603`` from an ``.eprj2`` local project — the
    editor's project database stores document titles case-folded, while the
    export is the library document as serialised. The library's own spelling is
    the case-preserving one (006b read ``R0402`` straight out of
    ``lib.footprint.get``), so when one candidate is the lowercase image of the
    other, that one is the folded copy.

    Returns ``(kept, was_folded)``. A difference that is *not* case-only is not
    this function's business — the caller records it as the disagreement it is.
    """
    if first == second or first.lower() != second.lower():
        return (first, False)
    first_folded = first == first.lower()
    second_folded = second == second.lower()
    if first_folded and not second_folded:
        return (second, True)
    return (first, False)


def _merge(into: PartEntry, other: PartEntry, conflicts: list[str]) -> None:
    """Fold a second occurrence into an entry, keeping the history and honesty."""
    for designator in other.provenance.designators:
        if designator not in into.provenance.designators:
            into.provenance.designators.append(designator)
    if other.provenance.note and other.provenance.note != into.provenance.note:
        into.provenance.note = f"{into.provenance.note}; {other.provenance.note}"
    # The source list is a **set of labels rendered sorted**, not a log. It used
    # to be appended in encounter order, which made the artifact depend on the
    # order the operator listed `--sources` on the command line — so "the same
    # sources produce the same file" was true only for one particular argument
    # order. A provenance list has no meaningful order to preserve.
    labels = {*_source_labels(into.provenance.source), *_source_labels(other.provenance.source)}
    into.provenance.source = "; ".join(sorted(labels))
    for field_name in _COMPARED_FIELDS:
        mine = getattr(into, field_name)
        theirs = getattr(other, field_name)
        if not mine and theirs:
            setattr(into, field_name, theirs)
            continue
        if not mine or not theirs or mine == theirs:
            continue
        if field_name == "footprint_name":
            kept, was_folded = prefer_footprint_spelling(mine, theirs)
            if kept != mine:
                setattr(into, field_name, kept)
                into.notes.append(
                    f"the sources spell this footprint {kept!r} and "
                    f"{mine if kept == theirs else theirs!r}; the case-preserving "
                    "spelling is kept (a local project case-folds document titles)"
                )
            elif kept.lower() == theirs.lower():
                # Same name, different case, and the first spelling already wins:
                # not a disagreement, so no conflict entry.
                pass
            continue
        conflicts.append(
            f"{into.lcsc}: {field_name} disagrees between boards — "
            f"kept {mine!r}, other source says {theirs!r}"
        )
    for key, value in other.params.items():
        if key not in into.params:
            into.params[key] = value
        elif into.params[key] != value:
            conflicts.append(
                f"{into.lcsc}: parameter {key!r} disagrees — "
                f"kept {into.params[key]!r}, other source says {value!r}"
            )
    if into.basic is UNKNOWN and other.basic is not UNKNOWN:
        into.basic = other.basic
    elif (
        into.basic is not UNKNOWN
        and other.basic is not UNKNOWN
        and into.basic != other.basic
    ):
        conflicts.append(
            f"{into.lcsc}: JLCPCB Part Class disagrees between boards — "
            f"kept basic={into.basic}, other source says basic={other.basic}"
        )
    if not into.datasheetUrl and other.datasheetUrl:
        into.datasheetUrl = other.datasheetUrl
    if not into.datasheetPdfUrl and other.datasheetPdfUrl:
        into.datasheetPdfUrl = other.datasheetPdfUrl
    for note in other.notes:
        if note not in into.notes:
            into.notes.append(note)


def _source_labels(source: str) -> list[str]:
    """The labels inside a `provenance.source` string (`"; "`-joined)."""
    return [part.strip() for part in source.split(";") if part.strip()]


def _resolve_keys(entries: list[PartEntry]) -> None:
    """Give every entry a key, suffixing the ones whose base key is ambiguous.

    A base key claimed by more than one C-number is suffixed for **all** of its
    claimants, so nobody owns an ambiguous name and the result does not depend
    on iteration order. Measured on the real data: two different 100nF 0805
    capacitors (`C49678`, `C28233`) share the base key `cap.100n_0805`.
    """
    claimants: dict[str, set[str]] = {}
    for entry in entries:
        claimants.setdefault(entry.key, set()).add(entry.lcsc or entry.deviceUuid)
    for entry in entries:
        if len(claimants.get(entry.key, ())) > 1:
            suffix = (entry.lcsc or entry.deviceUuid).lower()
            entry.key = f"{entry.key}.{suffix}"
            entry.notes.append(
                "key disambiguated with the C-number: more than one part shares "
                "the value/footprint slug"
            )


def harvest_board(
    path: str | Path,
    *,
    verifier: Verifier | None = None,
    corrections: "LibraryCorrections | None" = None,
) -> tuple[list[PartEntry], SourceReport]:
    """Harvest one board. A file that cannot be read is **reported**, not faked."""
    source = Path(path)
    report = SourceReport(path=str(source), board=source.stem)
    try:
        project = load_board_source(source)
    except LocalProjectError as exc:
        report.skipped_reason = str(exc)
        return ([], report)
    report.kind = project.kind

    report.placements = len(project.placements)
    # One definition of "which devices this board is harvested for" — the bridge
    # verification asks about exactly the same set (see `devices_to_verify`).
    placed = placed_devices(project)
    report.missing_devices.extend(placed.missing)
    report.placeholder_devices.extend(placed.placeholders)
    wanted: dict[str, LocalDevice] = dict(placed.devices)

    entries: list[PartEntry] = []
    by_lcsc: dict[str, PartEntry] = {}
    for designator in sorted(wanted):
        entry = _entry_for(
            project, wanted[designator], designator, report.board, verifier, corrections
        )
        existing = by_lcsc.get(entry.lcsc)
        if existing is None:
            by_lcsc[entry.lcsc] = entry
            entries.append(entry)
        else:
            # One part placed twice is one entry with two designators; the same
            # C-number on two designators is the normal case (decoupling caps),
            # not a duplicate to be dropped.
            _merge(existing, entry, [])

    used = {d.uuid for d in wanted.values()}
    report.unused_devices = sum(
        1 for uuid, device in project.devices.items() if uuid not in used and device.is_real_part
    )
    report.real_parts = len(by_lcsc)
    report.entries = len(entries)
    report.notes.extend(project.notes)
    return (entries, report)


def harvest(
    sources: list[str | Path],
    *,
    notes: list[str] | None = None,
    verifier: Verifier | None = None,
    corrections: "LibraryCorrections | None" = None,
) -> HarvestResult:
    """Harvest every source and merge them into one library.

    Merging is by **LCSC C-number**: that is the one key that means "the same
    physical part", which is why the identity is looked up by it rather than by
    MPN or by the project-local device uuid.

    ``corrections`` are the facts the boards cannot supply (see
    ``core/parts.py::LibraryCorrections``). They enter here rather than being
    edited into the file, so the library stays a deterministic function of
    *sources + corrections* and an offline `--check` keeps its meaning.
    """
    result = HarvestResult()
    by_lcsc: dict[str, PartEntry] = {}
    ordered: list[PartEntry] = []
    for path in sources:
        entries, report = harvest_board(
            path, verifier=verifier, corrections=corrections
        )
        result.sources.append(report)
        if not report.ok:
            continue
        result.library.sources.append(source_label(path))
        for entry in entries:
            existing = by_lcsc.get(entry.lcsc)
            if existing is None:
                by_lcsc[entry.lcsc] = entry
                ordered.append(entry)
            else:
                _merge(existing, entry, result.conflicts)

    _resolve_keys(ordered)
    result.library.parts = sorted(ordered, key=lambda p: p.key)
    result.library.notes = list(notes or []) + spelling_notes(result.library.parts)
    missing_pdf = sum(1 for p in result.library.parts if not p.datasheetPdfUrl)
    if missing_pdf and any(p.datasheetUrl for p in result.library.parts):
        result.library.notes.append(
            "the source boards declare a web datasheet page; the directly "
            "readable `datasheetPdfUrl` comes from the product endpoint, which "
            "needs the network, so it is recorded in the corrections sidecar by "
            f"`tools/backfill_datasheets.py`. {missing_pdf} entr(ies) carry no "
            "PDF link — a part the service does not answer for stays empty "
            "rather than being guessed."
        )
    result.report = describe(result)
    return result


def describe(result: HarvestResult) -> list[str]:
    """Human-readable summary — the numbers the acceptance asks to be reported."""
    lines: list[str] = []
    for source in result.sources:
        if not source.ok:
            lines.append(f"skip {source.board}: {source.skipped_reason}")
            continue
        lines.append(
            f"{source.board} [{source.kind}]: {source.placements} placements -> "
            f"{source.entries} entries ({source.real_parts} distinct C-number(s)); "
            f"{len(source.placeholder_devices)} abstract device(s) skipped, "
            f"{source.unused_devices} library device(s) unused"
        )
        if source.placeholder_devices:
            lines.append(
                "    abstract (no LCSC, cannot be curated): "
                + ", ".join(sorted(source.placeholder_devices))
            )
        if source.missing_devices:
            lines.append(
                "    dangling device reference(s): " + ", ".join(source.missing_devices)
            )
        for note in source.notes:
            lines.append(f"    note: {note}")
    lines.append(
        f"library: {result.entries} entries from "
        f"{sum(1 for s in result.sources if s.ok)} board(s)"
    )
    if result.conflicts:
        lines.append(f"conflicts recorded ({len(result.conflicts)}):")
        lines.extend(f"    {line}" for line in result.conflicts)
    return lines


def reconcile_counts(result: HarvestResult) -> dict[str, int]:
    """Distinct entries per source board — the "reconcile with the board" check.

    An entry counts once per board it was seen on, so a part shared by two
    boards appears in both totals and the sum exceeds the library size by
    exactly the number of shared parts. That is the property the acceptance
    asks to be checkable: every entry names a designator on the board it claims,
    and re-harvesting changes nothing.
    """
    counts: dict[str, int] = {}
    for entry in result.library.parts:
        for board in {d.partition("@")[2] for d in entry.provenance.designators}:
            if board:
                counts[board] = counts.get(board, 0) + 1
    return dict(sorted(counts.items()))


__all__ = [
    "BASIC_CLASS_EVIDENCE",
    "BRIDGE_DECIDED_FIELDS",
    "BRIDGE_DECIDED_LIBRARY_NOTE_MARKERS",
    "BRIDGE_DECIDED_NOTE_MARKERS",
    "FOOTPRINT_UUID_PATHS",
    "HarvestError",
    "HarvestResult",
    "NON_PARAM_KEYS",
    "PlacedDevices",
    "SourceReport",
    "Verifier",
    "basic_flag",
    "describe",
    "devices_to_verify",
    "footprint_uuid_of_device",
    "harvest",
    "harvest_board",
    "parameters_of",
    "placed_devices",
    "prefer_footprint_spelling",
    "reconcile_counts",
    "source_label",
    "spelling_notes",
    "strip_bridge_decided",
    "strip_bridge_decided_notes",
]
