"""The ``.eprj3`` **folder** project — the V4 offline format, read-only (038, tier A).

`.epro2` is one ZIP with one record stream inside it; `.eprj3` is a **folder** whose
each document is a file of the same record format — `sch/<schematic>/<page>.esch2`
per schematic page, `pcb/<pcb>.epcb2`, and a `<name>.eprj3` JSON index that names
them. The framing layer (``{envelope}||{body}|`` + LF, DOCHEAD-delimited documents)
is byte-for-byte the same, so :func:`~boardwise.parsers.epru_stream.iter_epru_records`
and ``split_documents`` are reused untouched: this module only has to find the
files, glue them into the one stream every consumer already reads, and do the one
transform eprj3 adds.

**The one transform is `yAxisDirection`** (spec: `easyeda-pro-format-skill`,
`primitives/REFERENCE/ty-axis-direction.md`, MIT — fetched 2026-09-25). eprj3 local
files are written in the **cartesian** frame (y up) and marked `up`; the cloud
frame V3 uses is y **down**, which is what every consumer here assumes, so reading
has to flip y back and strip the marker:

* only the **schematic family** is flipped (`SCH` / `SCH_PAGE` / `SIM_SCH` /
  `SIMULATION` / `SYMBOL`); `FOOTPRINT` / `DEVICE` / `PCB` pass through untouched;
* the flipped fields are per primitive (the spec's table): ``y`` for
  ATTR/TEXT/PIN/COMPONENT, ``originY`` for CANVAS, ``startY``/``endY`` for LINE,
  ``dotY1``/``dotY2`` for RECT (plus an embedded ``text.y``), ``centerY`` for
  CIRCLE/ELLIPSE (plus ``text.y``), every element's ``y`` for POLY, the odd
  ``controls`` indices for BEZIER, ``pointY`` for BUSENTRY and every entry of a
  BUS's ``busEntry``, ``startY``/``referY``/``endY`` for ARC, ``startY`` for
  OBJ/TABLE;
* **amplitude fields are never touched** (``height`` / ``radius`` / ``length`` /
  ``expandHeight`` / …) and neither are ``rotation`` / ``isMirror`` / ``zIndex``:
  flipping them would break "flip twice and you are back";
* a missing field means `down` (the cloud frame), and any other value is treated
  as the cloud frame too — only the literal ``up`` flips, which is the spec's own
  rule ("实现只认字面量 'up'").

Where the marker sits in a line is **not** stated by the spec and the official
example project happens to contain none, so this reader accepts it in the
**envelope or the body** and strips it from whichever object held it. Both
placements are covered by the tests, and the day a real V4 export shows a third
one, the fixture is what will say so.

Tier A is **read-only SCH_PAGE**: PCB documents are deliberately not read here, and
asking for the pcb view is an honest error rather than an empty model (a model with
0 components and 0 nets reads as "a clean board" — SKILL pit 14).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

#: The index file's extension. A folder project is `<folder>/<name>.eprj3`.
EPRJ3_SUFFIX = ".eprj3"
#: Schematic page documents.
ESCH2_SUFFIX = ".esch2"

#: Document types whose coordinates are written y-up in an eprj3 file. Everything
#: else in the same stream passes through byte-for-byte.
SCHEMATIC_DOC_TYPES = frozenset({"SCH", "SCH_PAGE", "SIM_SCH", "SIMULATION", "SYMBOL"})

#: Which body field of which primitive carries y (the spec's table, verbatim).
FLIPPED_FIELDS: dict[str, tuple[str, ...]] = {
    "ATTR": ("y",),
    "TEXT": ("y",),
    "PIN": ("y",),
    "COMPONENT": ("y",),
    "CANVAS": ("originY",),
    "LINE": ("startY", "endY"),
    "ARC": ("startY", "referY", "endY"),
    "OBJ": ("startY",),
    "TABLE": ("startY",),
    "CIRCLE": ("centerY",),
    "ELLIPSE": ("centerY",),
    "RECT": ("dotY1", "dotY2"),
    "MASK_REGION": ("dotY1", "dotY2"),
    "BUSENTRY": ("pointY",),
}
#: Types whose embedded ``text`` object also carries a ``y``.
EMBEDDED_TEXT_TYPES = frozenset({"CIRCLE", "ELLIPSE", "RECT"})
#: Types whose ``points`` array is a list of ``{x, y}``.
POINTS_ARRAY_TYPES = frozenset({"POLY"})
#: Types whose ``controls`` array interleaves x and y (the odd indices are y).
CONTROLS_ARRAY_TYPES = frozenset({"BEZIER"})
#: Types whose ``busEntry`` array is a list of ``{pointY}``.
BUS_TYPES = frozenset({"BUS"})

#: The honest refusal for the tier this batch does not open.
PCB_TIER_ERROR = (
    "PCB 读取在 B 档（038 未开）：本批只接 eprj3 的**只读原理图**（SCH_PAGE）；"
    "空 PCB 模型会被误读成\"0 器件 0 网\"（SKILL 坑 14），所以这里报错而不是给一个空模型"
)


class Eprj3Error(ValueError):
    """The folder is not a readable eprj3 project (message says which part)."""


def looks_like_eprj3(path: str | Path) -> bool:
    """Is this a folder project? (a directory holding a ``*.eprj3`` index)"""
    candidate = Path(path)
    if candidate.is_dir():
        return any(candidate.glob(f"*{EPRJ3_SUFFIX}"))
    if candidate.is_file() and candidate.suffix.lower() == EPRJ3_SUFFIX:
        return True
    return False


def index_path(path: str | Path) -> Path:
    """The ``<name>.eprj3`` index of a folder project, or a refusal."""
    candidate = Path(path)
    if candidate.is_file() and candidate.suffix.lower() == EPRJ3_SUFFIX:
        return candidate
    if not candidate.is_dir():
        raise Eprj3Error(f"{candidate}: not a folder and not a {EPRJ3_SUFFIX} file")
    found = sorted(candidate.glob(f"*{EPRJ3_SUFFIX}"))
    if not found:
        raise Eprj3Error(
            f"{candidate}: no {EPRJ3_SUFFIX} index inside the folder — an eprj3 project "
            "is a folder whose <name>.eprj3 names its documents"
        )
    return found[0]


def read_index(path: str | Path) -> dict[str, Any]:
    """The project metadata (``name`` / ``owner_uuid`` / ``profile`` …).

    Read instead of ``project2.json``: the index is where eprj3 keeps the project
    identity, which is also why the "only a `.epro2` carries a project uuid" gap
    in `cli.py` can be fixed for folder projects (038 §2).
    """
    index = index_path(path)
    try:
        payload = json.loads(index.read_text(encoding="utf-8"))
    except OSError as exc:
        raise Eprj3Error(f"{index}: cannot be read ({exc})") from exc
    except ValueError as exc:
        raise Eprj3Error(f"{index}: is not JSON ({exc})") from exc
    if not isinstance(payload, dict):
        raise Eprj3Error(f"{index}: the index is not a JSON object")
    return payload


def page_files(path: str | Path) -> list[Path]:
    """Every schematic page file, deterministically ordered.

    ``sch/**/*.esch2`` — the schematic tree, one file per page (the spec's own
    layout: ``sch/<schematic>/<page>.esch2``). Sorted by path so two runs of the
    same read produce the same stream, and deduplicated case-insensitively the way
    the rest of the harness treats Windows paths.
    """
    root = Path(path)
    if root.is_file():
        root = root.parent
    found: dict[str, Path] = {}
    for candidate in sorted(root.glob(f"sch/**/*{ESCH2_SUFFIX}")):
        if candidate.is_file():
            found.setdefault(str(candidate).lower(), candidate)
    return [found[key] for key in sorted(found)]


def _flip(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return -value


def flip_line(line: str) -> str:
    """One record line, y-flipped per the spec's table, marker stripped.

    A line whose record type has no coordinates (``WIRE`` / ``META`` / ``GROUP`` /
    ``PART`` / …) is returned **untouched**, exactly as the spec says — the flip is
    keyed on (document type, primitive type), and amplitude fields are never in
    the table, so "flip twice" is a fixed point.
    """
    core = line[:-1] if line.endswith("|") else line
    if "yAxisDirection" not in core:
        return line
    if core.count("||") < 1:
        return line
    envelope_text, _, body_text = core.partition("||")
    try:
        envelope = json.loads(envelope_text)
    except ValueError:
        return line
    if not isinstance(envelope, dict):
        return line
    body: dict[str, Any] | None = None
    if body_text.strip():
        try:
            decoded = json.loads(body_text)
        except ValueError:
            decoded = None
        body = decoded if isinstance(decoded, dict) else None
    marker = envelope.pop("yAxisDirection", None)
    if body is not None:
        marker = body.pop("yAxisDirection", marker)
    if marker != "up":
        # Only the literal `up` flips (the spec's rule); anything else is the cloud
        # frame — and the marker still goes away, because a read strips it.
        return _join(envelope, body) if marker is not None else line
    if body is not None:
        _flip_body(str(envelope.get("type") or ""), body)
    return _join(envelope, body)


def _join(envelope: dict[str, Any], body: dict[str, Any] | None) -> str:
    text = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return text + "|||"
    return text + "||" + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "|"


def _flip_body(record_type: str, body: dict[str, Any]) -> None:
    for field in FLIPPED_FIELDS.get(record_type, ()):
        if field in body:
            body[field] = _flip(body[field])
    if record_type in EMBEDDED_TEXT_TYPES:
        embedded = body.get("text")
        if isinstance(embedded, dict) and "y" in embedded:
            embedded["y"] = _flip(embedded["y"])
    if record_type in POINTS_ARRAY_TYPES:
        for item in body.get("points") or []:
            if isinstance(item, dict) and "y" in item:
                item["y"] = _flip(item["y"])
    if record_type in CONTROLS_ARRAY_TYPES:
        controls = body.get("controls")
        if isinstance(controls, list):
            for index in range(1, len(controls), 2):
                controls[index] = _flip(controls[index])
    if record_type in BUS_TYPES:
        for entry in body.get("busEntry") or []:
            if isinstance(entry, dict) and "pointY" in entry:
                entry["pointY"] = _flip(entry["pointY"])


def _doc_type_of(line: str) -> str | None:
    core = line[:-1] if line.endswith("|") else line
    envelope_text, _, body_text = core.partition("||")
    try:
        envelope = json.loads(envelope_text)
    except ValueError:
        return None
    if not isinstance(envelope, dict) or envelope.get("type") != "DOCHEAD":
        return None
    try:
        head = json.loads(body_text) if body_text.strip() else {}
    except ValueError:
        return None
    return str((head or {}).get("docType") or "") if isinstance(head, dict) else None


def transform_text(text: str) -> str:
    """The whole page file: flip only inside the schematic family, keep the rest.

    The document type is tracked the way the stream itself declares it (the last
    ``DOCHEAD``), because the spec's rule is a **(document type, primitive type)**
    pair — a `POLY` means `points` in the schematic domain and `path` in the
    footprint domain, and dispatching on the primitive name alone would flip a
    footprint polygon without saying so.
    """
    out: list[str] = []
    doc_type: str | None = None
    for line in text.split("\n"):
        if not line:
            out.append(line)
            continue
        declared = _doc_type_of(line)
        if declared is not None:
            doc_type = declared
        if doc_type in SCHEMATIC_DOC_TYPES and "yAxisDirection" in line:
            out.append(flip_line(line))
        else:
            out.append(line)
    return "\n".join(out)


def load_eprj3_text(path: str | Path) -> tuple[str, dict[str, Any]]:
    """The project's record stream and metadata, in the same shape `.epro2` gives.

    Every page file is a complete record stream of its own (its own DOCHEAD), so
    gluing them with newlines yields exactly the multi-document stream the offline
    pipeline already reads. Files are read in path order, so the stream is
    reproducible; an unreadable page is reported with its path rather than skipped.
    """
    root = Path(path)
    if root.is_file():
        root = root.parent
    index = read_index(path)
    pages = page_files(root)
    if not pages:
        raise Eprj3Error(
            f"{root}: no schematic page ({ESCH2_SUFFIX}) under sch/ — tier A reads the "
            "schematic tree only"
        )
    chunks: list[str] = []
    for page in pages:
        try:
            chunks.append(transform_text(page.read_text(encoding="utf-8")))
        except OSError as exc:
            raise Eprj3Error(f"{page}: cannot be read ({exc})") from exc
        except UnicodeDecodeError:
            chunks.append(transform_text(
                page.read_text(encoding="utf-8", errors="replace")))
    text = "\n".join(chunk.rstrip("\n") for chunk in chunks)
    meta = dict(index)
    meta.setdefault("name", root.name)
    meta["format"] = "eprj3"
    meta["pages"] = [page.stem for page in pages]
    meta["sourcePath"] = str(root)
    return text, meta


def describe(path: str | Path) -> dict[str, Any]:
    """A sanity line for the evidence files: pages, components, nets (038 §3).

    Read-only and cheap: it counts what the stream declares without building a
    model, so a development-time comparison against the official example can be
    printed even when the model builder is not involved.
    """
    from .epru_stream import iter_epru_records

    text, meta = load_eprj3_text(path)
    counts: dict[str, int] = {}
    designs: list[str] = []
    for record in iter_epru_records(text):
        counts[record.type] = counts.get(record.type, 0) + 1
        if record.type == "ATTR" and (record.body or {}).get("key") == "Designator":
            value = str((record.body or {}).get("value") or "").strip()
            if value:
                designs.append(value)
    designators = sorted(set(designs))
    return {
        "source": str(path),
        "name": meta.get("name"),
        "ownerUuid": meta.get("owner_uuid"),
        "pages": meta.get("pages"),
        "componentInstances": counts.get("COMPONENT", 0),
        "wires": counts.get("WIRE", 0),
        "pins": counts.get("PIN", 0),
        "netlabels": sum(
            1 for record in iter_epru_records(text)
            if record.type == "ATTR" and (record.body or {}).get("key") == "NET"
        ),
        "designators": designators,
        "recordTypes": dict(sorted(counts.items())),
    }


def iter_pages(path: str | Path) -> Iterable[tuple[str, str]]:
    """``(page name, transformed text)`` per page — for callers that want one page."""
    root = Path(path)
    if root.is_file():
        root = root.parent
    for page in page_files(root):
        yield page.stem, transform_text(page.read_text(encoding="utf-8"))
