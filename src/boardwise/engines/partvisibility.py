"""Hiding a placed part's **value row** (532) — what the host actually reads.

S-21's way out of a text collision is 「值应隐藏」, and until 532 that sentence
stopped at the plan: `islandlayout` left the row out of the plan's text list and
`drawapply` wrote no visibility at all, so the host painted it anyway. Measured on
a live landing (`evidence/531/report.md` §5.4): four values the plan had hidden,
**4/4 printed**, because a placed part's designator and value rows are the host's
own annotations — "C1 places no text primitive, so the drawn text is the host's".

Where the flag lives, measured on `test/P1` (`evidence/532/probes/10_hide_probe.py`,
the whole document source read and written back with one byte changed): a placed
part is a ``COMPONENT`` record, and the row the host prints for its **value** is
the ``ATTR`` record whose ``key`` is ``"Name"`` and whose ``parentId`` is that
component (``value: "={Value}"`` for most devices, ``"={Manufacturer Part}"`` for
the four whose drawn name is the device's own).  Its ``valueVisible`` is the flag:
set ``false`` and the row leaves the render — verified, 2 rows → 1, same page,
same instant, one flag changed.

The channel is ``sys.set_document_source``, and it is the *only* one this host
offers: `sch_PrimitiveComponent.modify` takes ``otherProperty`` (the BOM's string
map, where the design value lives) and nothing else, `sch.modify_primitive` is
pose-only by construction, and there is no connector action that addresses an
attribute record — this batch may not add one either, because the daemon's action
catalogue is a load-time constant and the connector already running in the editor
(0.5.18) is the one this repository can call.  So the write is the whole
document's source text, read back after the write, which is exactly the shape
`sys.set_document_source` states for itself.

Nothing here talks to the bridge: the two functions take the document source as a
string and return it changed (or a reason it could not be), so the parsing is
tested offline and the CLI does the I/O.
"""

from __future__ import annotations

import json
import re

__all__ = [
    "VALUE_ROW_KEY",
    "hide_value_rows",
    "value_row_attributes",
    "value_row_visible",
]

#: The attribute key whose record the host prints a placed part's **value row**
#: with.  Measured, not chosen: on `test/P1` the 19 parts' rows the render draws in
#: ``#0000FF`` are the ``Name`` records, and the designator rows (``#000080``) are
#: the ``Designator`` ones (`evidence/532/probes/12_pin_text.py` reads the fills).
VALUE_ROW_KEY = "Name"


def _records(source: str) -> list[tuple[dict, str, int, int]]:
    """``(head, body, bodyStart, bodyEnd)`` for every record line of a document.

    The source is a line per record, ``<head>||<body>|``, which is the shape
    ``sys.get_document_source`` returns and the shape the ``.epro`` stream uses.
    A line that does not parse is skipped rather than fatal: this reader is looking
    for one attribute inside a file the host owns, and a record it cannot read is
    not evidence about the one it can.
    """
    out: list[tuple[dict, str, int, int]] = []
    position = 0
    for line in source.split("\n"):
        line_start = position
        position += len(line) + 1
        if "||" not in line:
            continue
        head, body = line.split("||", 1)
        try:
            out.append((
                json.loads(head), body,
                line_start + len(head) + 2, line_start + len(line),
            ))
        except ValueError:
            continue
    return out


def value_row_attributes(source: str) -> dict[str, tuple[str, int, int]]:
    """``designator -> (attributeId, bodyStart, bodyEnd)`` for the value rows.

    Two joins, both stated by the document itself: the ``Designator`` attribute
    names the part (its ``value``) and owns it (its ``parentId`` is the component
    record's id), and the ``Name`` attribute of that same component is the value
    row.  A part with no ``Name`` record has no value row to hide — kept out
    rather than guessed at.
    """
    records = _records(source)
    component_of: dict[str, str] = {}
    for head, body, _start, _end in records:
        if head.get("type") != "ATTR" or '"Designator"' not in body:
            continue
        try:
            payload = json.loads(body.rstrip("|"))
        except ValueError:
            continue
        parent = str(payload.get("parentId") or "")
        designator = str(payload.get("value") or "")
        if parent and designator:
            component_of[parent] = designator
    out: dict[str, tuple[str, int, int]] = {}
    for head, body, start, end in records:
        if head.get("type") != "ATTR" or '"Name"' not in body:
            continue
        try:
            payload = json.loads(body.rstrip("|"))
        except ValueError:
            continue
        if payload.get("key") != VALUE_ROW_KEY:
            continue
        designator = component_of.get(str(payload.get("parentId") or ""))
        if designator and designator not in out:
            out[designator] = (str(head.get("id") or ""), start, end)
    return out


def hide_value_rows(
    source: str, designators: list[str],
) -> tuple[str, list[str], list[str]]:
    """``source`` with those parts' value rows set ``valueVisible: false``.

    Returns ``(source, hidden, missing)``: the changed text, the designators whose
    row was actually flipped, and the ones the document does not carry a value row
    for.  A designator whose flag was **already** ``false`` is reported as hidden
    (the page is in the state the plan asks for) rather than as a change — this
    runs on a page this same run may have just drawn, and the substitution is
    idempotent by construction: it only ever writes ``false``.

    The edit is a byte-level substitution **inside one record**, and the record's
    own text is left alone otherwise: the host re-serialises the document it is
    given, so rewriting the JSON would be this module's formatting defending
    itself against a file it does not own.
    """
    rows = value_row_attributes(source)
    hidden: list[str] = []
    missing: list[str] = []
    edits: list[tuple[int, int, str]] = []
    for designator in designators:
        entry = rows.get(designator)
        if entry is None:
            missing.append(designator)
            continue
        _attribute_id, start, end = entry
        body = source[start:end]
        flipped = re.sub(
            r'"valueVisible"\s*:\s*true', '"valueVisible":false', body, count=1,
        )
        if flipped != body:
            edits.append((start, end, flipped))
        hidden.append(designator)
    # Applied from the **end** of the document backwards, so an edit that changes
    # the text's length cannot move the offsets of the records still to come.
    out = source
    for start, end, flipped in sorted(edits, reverse=True):
        out = out[:start] + flipped + out[end:]
    return out, hidden, missing


def value_row_visible(source: str, designator: str) -> bool | None:
    """Is this part's value row printed on this document? ``None`` if unknowable.

    The read-back half of :func:`hide_value_rows`: the flag lives in the record the
    write addressed, so the caller reads **that record** rather than searching the
    document for the string. ``None`` means the document carries no value row for
    the designator at all — not "not printed", which would be the flattering way to
    read a missing record.
    """
    entry = value_row_attributes(source).get(designator)
    if entry is None:
        return None
    _attribute_id, start, end = entry
    body = source[start:end]
    if '"valueVisible":false' in body:
        return False
    if '"valueVisible":true' in body:
        return True
    return None
