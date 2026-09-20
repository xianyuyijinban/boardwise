"""Injected-defect board generator for task 011d sec.4 -- the signed subset.

The oracle (Yue Xiangyu) signs the proposal table before any variant may be
built (011 sec.6: an injected fault has to be one a person really makes), and
on 2026-09-19 he also ruled on the two faults the reference board itself
carries: **U3's value (1k) is right and its MPN is wrong; V3 must be tied to
VCC**. So the pipeline has two layers:

    golden fixture  --[BASE_FIXES]-->  fixed-base.epro2  --[VARIANTS]-->  variants

The **clean base** applies the oracle's two corrections, so it carries no known
defect of its own; every variant is derived from *it*, which is what makes an
injected fault a first-of-its-kind signal instead of a second copy of a fault
the board already had. ``led-overcurrent`` was ruled out by the oracle and is
gone from the table.

Usage:
    python reviewsets/injected/make_variants.py --list
    python reviewsets/injected/make_variants.py --generate
    python reviewsets/injected/make_variants.py --generate <id> ...
    python reviewsets/injected/make_variants.py --check

Every board is derived by surgery on the ``.epru`` JSON-line stream -- never by
re-drawing -- and lands beside this script:

    fixed-base.epro2 / .json    the corrected reference board
    <id>.epro2 / .json          one variant, one defect record naming the rule
                                that must catch the injected fault

**Splits (011e sec.2).** The live variants are split dev/holdout by a derived
rule -- ``sha1(id)`` ordering, first ``HOLDOUT_SIZE`` are held back -- because a
rule must not be tuned against the board it is graded on, and a hand-picked
split is a split somebody can re-pick after seeing a number. Splits are per
board, never per record: records on one board share its topology.

**Retired variants.** ``v3-decap-missing`` was retired 2026-09-20 (sec.1.2):
its injection is measurably invisible on this topology. The file stays on disk
and ``--check`` keeps covering it, but it is in neither split, carries no
annotation records, and ``--generate`` refuses to author it.

Two properties this script must keep, because fixtures rot silently:

* **every edit is value-based.** Records are located by content (designator,
  attribute key, value, lineGroup), each lookup asserts exactly one hit, and
  every rewritten line is checked against a byte-for-byte re-serialisation of
  its parsed self -- a format drift fails loudly instead of corrupting a
  fixture that then "passes";
* **regeneration is byte-identical.** Record ids are derived from the board id
  (sha1) and archive entries carry a fixed DOS timestamp, so ``--check`` can
  compare a fresh build against what is committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"

#: Who signed the proposal table, and when. The per-variant ``signed`` field
#: carries the same date; an empty one means "not signed, do not build".
SIGNED_BY = "Yue Xiangyu"
SIGNED_ON = "2026-09-19"

# ---------------------------------------------------------------------------
# The base: the golden page with the oracle's two 2026-09-19 corrections. Its
# fixes are not defects, so it gets no defect records -- only the design's own
# exceptions (carried over from the golden set, which is where the oracle
# signed them).
# ---------------------------------------------------------------------------

BASES = [
    {
        "id": "fixed-base",
        "fix": (
            "the oracle's two rulings: U3's declared MPN corrected to the 1k "
            "sibling, and V3 tied to the VCC net"
        ),
        "edits": [
            "U3 instance 'Manufacturer Part': FRC0805J471 TS -> FRC0805J102 TS",
            "V3's wire group: its NET label now reads VCC (was empty, so the net came out auto-named NET1)",
        ],
        "signed": SIGNED_ON,
        "builder": "fixed_base",
        "oracle_note": (
            "the substrate for every injected variant. Two corrections, both "
            "ruled 2026-09-19: 'U3 value 1k is right, MPN FRC0805J471 is "
            "wrong' and 'V3 must be tied to VCC'. The V3 fix is a net-name "
            "declaration on the existing wire, which is how a schematic ties "
            "two nets -- the capacitor C1 stays where it is and becomes a VCC "
            "decoupling cap, exactly what a 3.3V-mode CH340G wants. Only the "
            "instance's MPN claim is corrected; the local library device it "
            "points at still carries the old supplier fields, because "
            "re-picking the device would rewrite the library document and "
            "inventing a catalogue number for the 1k sibling would be "
            "fabrication (see the report)."
        ),
    },
]

# ---------------------------------------------------------------------------
# The variant table. The oracle reviews THIS, not the code below: ``fault`` is
# what the derived board gets wrong, ``edit`` is how the script does it,
# ``expects`` is the rule that has to catch it, and ``ref`` is the designator
# the annotation record hangs the defect on.
# ---------------------------------------------------------------------------

VARIANTS = [
    {
        "id": "v3-decap-missing",
        "fault": "C1 (the CH340G V3 0.1uF) removed from the board",
        "edit": "delete C1's COMPONENT record and its attribute stream",
        "expects": "decap-required-caps",
        "ref": "U1",
        "severity": "WARN",
        "signed": "",
        # Retired 2026-09-20 (task 011e sec.1.2, oracle's discretion). The file
        # stays on disk and stays byte-reproducible; it is simply no longer
        # part of the eval set.
        "retired": "2026-09-20",
        "builder": "v3_decap_missing",
        "oracle_note": (
            "RETIRED: on this topology the injection is invisible -- measured, "
            "not argued. In 3.3V mode the V3 capacitor requirement (facts tag "
            "mode: 5V) does not apply, and the requirement that does apply "
            "(VCC needs 0.1uF) is met by C9's 2.2uF with or without C1: the two "
            "boards produce identical rule output, det=0/1. The general "
            "property is that decap-required-caps compares against the LARGEST "
            "established capacitor on the net, so no single-capacitor removal "
            "on this board is visible at all (VCC carries four). Making it "
            "visible would mean editing three capacitors at once -- building a "
            "defect to fit the rule, which 011 sec.6 forbids. The missing-"
            "decoupling path stays covered by synthetic model tests. Kept as a "
            "board for the byte-identity guard, excluded from the per-variant "
            "detection criterion and from both splits."
        ),
    },
    {
        "id": "duplicate-designator",
        "fault": "a second page carries a second R24",
        "edit": "append a new SCH_PAGE holding a copy of R24's records",
        "expects": "conn-duplicate-designators",
        "ref": "R24",
        "severity": "ERROR",
        "signed": SIGNED_ON,
        "builder": "duplicate_designator",
        "oracle_note": (
            "the model keeps the last placement; the clash must be reported. "
            "The copy sits at the original's coordinates on purpose: a fault "
            "injection changes ONE thing, and moving it would also rewrite "
            "the netlist."
        ),
    },
    {
        "id": "nc-pin-grounded",
        "fault": "RT9013 pin4 (declared NC) wired to GND",
        "edit": (
            "clear U5.4's NO_CONNECT mark and add a wire from the pin tip to "
            "the grounded capacitor on the same row"
        ),
        "expects": "conn-nc-and-must-connect",
        "ref": "U5",
        "severity": "ERROR",
        "signed": SIGNED_ON,
        "builder": "nc_pin_grounded",
        "oracle_note": "an NC pin on any net is the textbook violation",
    },
    {
        "id": "overvoltage-rail",
        "fault": "the +5V rail renamed +9V (above the RT9013's 6V abs max)",
        "edit": "rename the net in the page's flag attributes (Name and Global Net Name)",
        "expects": "pwr-domain-vs-range",
        "ref": "U5",
        "severity": "ERROR",
        "signed": SIGNED_ON,
        "builder": "overvoltage_rail",
        "oracle_note": (
            "the domain inference reads the rail name; abs max is exceeded. "
            "Only the page's net declarations change -- the flag library "
            "device titles stay as they are, because renaming a net does not "
            "rename a part."
        ),
    },
    {
        "id": "ldo-no-headroom",
        "fault": "RT9013 input fed from the 3.3V rail (0V headroom < 400mV dropout)",
        "edit": "reroute U5.1's wire from +5V to the VOUT rail",
        "expects": "path-ldo-dropout",
        "ref": "U5",
        "severity": "ERROR",
        "signed": SIGNED_ON,
        "builder": "ldo_no_headroom",
        "oracle_note": "headroom 0 mV against the dropout fact",
    },
    {
        "id": "value-mpn-mismatch",
        "fault": "U3's value field changed to 2.2k while its MPN decodes 1k",
        "edit": "rewrite U3's Value attribute only",
        "expects": "param-value-mpn-match",
        "ref": "U3",
        "severity": "WARN",
        "signed": SIGNED_ON,
        "builder": "value_mpn_mismatch",
        "oracle_note": (
            "the single-field contradiction, now first-of-its-kind: the base "
            "has U3's value and MPN agreeing at 1k (the oracle's ruling), so "
            "this edit is the only disagreement on the board."
        ),
    },
]

# ---------------------------------------------------------------------------
# Split assignment (task 011e sec.2). A rule must not be tuned against the
# board it is graded on, so part of the injected family is held back.
#
# The choice is DERIVED, never picked: the eval-set ids are ordered by
# ``sha1(id)`` and the first HOLDOUT_SIZE go to holdout. Nothing about a board
# -- how interesting it is, whether its rule is already passing -- enters the
# rule, so nobody can quietly re-draw after seeing a number. The concrete
# result is pinned by a test, so changing the derivation is a visible decision
# rather than a silent re-roll.
#
# Splits are per BOARD, not per item: records on one board share its topology,
# so splitting them apart would leak the board across the boundary.
# ---------------------------------------------------------------------------

#: Out of the five live variants. One in three of the injected family, and at
#: least a third of *every* annotated board once the real-board pass (011e
#: sec.3) lands -- sec.2 asks for >=1/3.
HOLDOUT_SIZE = 2


def _variant_ids() -> list[str]:
    """Every variant the table carries, retired ones included."""
    return [v["id"] for v in VARIANTS]


def eval_ids() -> list[str]:
    """The variants that take part in grading -- retired ones excluded."""
    return [v["id"] for v in VARIANTS if not v.get("retired")]


def holdout_ids() -> list[str]:
    """The held-back slice, by the derivation above."""
    ranked = sorted(eval_ids(), key=lambda v: hashlib.sha1(v.encode()).hexdigest())
    return ranked[:HOLDOUT_SIZE]


def dev_ids() -> list[str]:
    return [v for v in eval_ids() if v not in holdout_ids()]


def split_of(variant_id: str) -> str:
    return "holdout" if variant_id in holdout_ids() else "dev"


# ---------------------------------------------------------------------------
# JSON-line helpers. Every line is ``{head}||{body}|`` in compact JSON; a few
# records carry an empty body (``{head}|||``).
# ---------------------------------------------------------------------------




def _render(head: dict, body: dict | None) -> str:
    head_text = json.dumps(head, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return f"{head_text}|||"
    body_text = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    return f"{head_text}||{body_text}|"


def _load(line: str) -> tuple[dict, dict | None]:
    head_text, sep, rest = line.partition("||")
    if not sep:
        raise ValueError(f"not a JSON-line record: {line[:60]!r}")
    body_text = rest[:-1] if rest.endswith("|") else rest
    head = json.loads(head_text)
    body = json.loads(body_text) if body_text else None
    if _render(head, body) != line:
        raise ValueError(f"line does not round-trip: {line[:80]!r}")
    return head, body


def _iter_records(lines: list[str]):
    for index, line in enumerate(lines):
        try:
            head, body = _load(line)
        except ValueError:
            continue
        yield index, head, body


def _records(lines: list[str], record_type: str) -> list[tuple[int, dict, dict | None]]:
    return [
        (i, h, b) for i, h, b in _iter_records(lines) if h.get("type") == record_type
    ]


def _designators(lines: list[str]) -> dict[str, str]:
    """COMPONENT id -> designator, from each component's attribute stream."""
    return {
        str(b.get("parentId")): str(b.get("value"))
        for _i, _h, b in _records(lines, "ATTR")
        if b and b.get("key") == "Designator" and b.get("value")
    }


def _component_id(lines: list[str], designator: str) -> str:
    by_id = _designators(lines)
    hits = sorted(cid for cid, des in by_id.items() if des == designator)
    if len(hits) != 1:
        raise ValueError(f"designator {designator!r}: {len(hits)} components")
    return hits[0]


def _component_records(lines: list[str], designator: str) -> list[int]:
    """The COMPONENT record's index plus every ATTR that belongs to it."""
    cid = _component_id(lines, designator)
    indices = [
        i for i, h, _b in _iter_records(lines)
        if h.get("type") == "COMPONENT" and str(h.get("id")) == cid
    ]
    if len(indices) != 1:
        raise ValueError(f"{designator}: {len(indices)} COMPONENT records")
    indices += [
        i for i, _h, b in _records(lines, "ATTR")
        if b and str(b.get("parentId")) == cid
    ]
    return sorted(indices)


def _next_ticket(lines: list[str]) -> int:
    tickets = [
        int(h["ticket"]) for _i, h, _b in _iter_records(lines) if isinstance(h.get("ticket"), int)
    ]
    return max(tickets) + 1


def _page_end(lines: list[str]) -> int:
    """Index of the first DOCHEAD after the schematic page's.

    New page records must be inserted here, not appended to the file: the
    parser keeps a record only while the *last* DOCHEAD opened a SCH_PAGE, so
    a trailing record lands inside the CONFIG/BLOB documents and is skipped --
    which looks exactly like "the wire was not drawn" (measured: both wire
    variants produced a dangling pin instead of a connection).
    """
    page = next(
        i for i, h, b in _records(lines, "DOCHEAD")
        if b and b.get("docType") == "SCH_PAGE"
    )
    for index, head, _body in _iter_records(lines):
        if index > page and head.get("type") == "DOCHEAD":
            return index
    raise ValueError("no document boundary after the schematic page")


def _rid(variant_id: str, purpose: str, index: int = 0) -> str:
    """A deterministic 24-hex record id, so regeneration is byte-identical."""
    seed = f"boardwise-injected:{variant_id}:{purpose}:{index}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:24]


def _num(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _wire_lines(
    variant_id: str, tag: str, points_canvas: list[tuple[float, float]],
    ticket: int, z_index: float,
) -> list[str]:
    """A new WIRE with one LINE per segment. Canvas y is negated for the file."""
    wire_id = _rid(variant_id, f"wire:{tag}")
    out = [_render(
        {"type": "WIRE", "ticket": ticket, "id": wire_id}, {"zIndex": z_index}
    )]
    for index, (start, end) in enumerate(zip(points_canvas, points_canvas[1:])):
        out.append(_render(
            {"type": "LINE", "ticket": ticket + 1 + index,
             "id": _rid(variant_id, f"segment:{tag}", index)},
            {
                "fillColor": None, "fillStyle": None, "strokeColor": None,
                "strokeStyle": None, "strokeWidth": None,
                "startX": _num(start[0]), "startY": _num(-start[1]),
                "endX": _num(end[0]), "endY": _num(-end[1]),
                "lineGroup": wire_id,
            },
        ))
    return out


def _net_label_index(lines: list[str], group: str) -> int:
    """The ``NET`` label record of a wire group.

    Every wire group carries one -- mostly with an empty value, which is how
    the editor says "this net has no label". So a fix that wants to *name* a
    net must edit that record, not add a second one: the parser reads the
    first ``NET`` label it finds for the group, and an added record would sit
    behind the empty one and change nothing (measured on the first attempt at
    this fix -- the V3 net stayed NET1 and the base still failed its own
    check).
    """
    hits = [
        i for i, _h, body in _records(lines, "ATTR")
        if body and body.get("key") == "NET" and str(body.get("parentId")) == group
    ]
    if len(hits) != 1:
        raise ValueError(f"wire group {group}: {len(hits)} NET label records")
    return hits[0]


def _wire_group(lines: list[str], a: tuple[float, float], b: tuple[float, float]) -> str:
    """The lineGroup of the wire segment between two canvas points."""
    want = {(_num(a[0]), _num(-a[1]), _num(b[0]), _num(-b[1])),
            (_num(b[0]), _num(-b[1]), _num(a[0]), _num(-a[1]))}
    hits = [
        str(body.get("lineGroup"))
        for _i, _h, body in _records(lines, "LINE")
        if body and (body.get("startX"), body.get("startY"),
                     body.get("endX"), body.get("endY")) in want
    ]
    if len(hits) != 1:
        raise ValueError(f"wire {a}->{b}: {len(hits)} segments")
    return hits[0]


# ---------------------------------------------------------------------------
# The base builder: the golden page with the oracle's two corrections. Its
# edits are fixes, not injections, so it is kept apart from the variant
# builders on purpose -- a reader must never confuse the two.
# ---------------------------------------------------------------------------

#: U3's declared MPN and the 1k sibling of the same FOJAN 0805 series. The
#: oracle ruled 2026-09-19: the value (1k) is right, the MPN was wrong.
U3_WRONG_MPN = "FRC0805J471 TS"
U3_RIGHT_MPN = "FRC0805J102 TS"
#: V3's wire (canvas), whose net declaration is the one to rewrite.
V3_WIRE = ((166.0, 636.0), (200.0, 636.0))


def build_fixed_base(lines: list[str], board_id: str) -> list[str]:
    """Apply the oracle's two corrections to the golden board.

    * **U3's MPN**: ``471`` -> ``102`` (470 ohm -> 1k), so the declared part
      matches the declared value. Only the *instance's* claim changes; the
      local library device it points at keeps its old supplier fields, because
      re-picking the device would rewrite a library document and a catalogue
      number for the 1k sibling cannot be verified offline.
    * **V3 tied to VCC**: the pin's wire group gets a ``VCC`` net declaration.
      Nothing is rerouted and C1 stays: V3 and VCC become one net, so C1 turns
      into a VCC decoupling capacitor -- which is the 3.3V-mode wiring the
      CH340 manual draws, and it leaves the board's copper untouched.
    """
    component = _component_id(lines, "U3")
    mpn_index = next(
        i for i, _h, b in _records(lines, "ATTR")
        if b and str(b.get("parentId")) == component
        and b.get("key") == "Manufacturer Part"
    )
    head, body = _load(lines[mpn_index])
    if body.get("value") != U3_WRONG_MPN:
        raise ValueError(
            f"U3's MPN is {body.get('value')!r}, expected {U3_WRONG_MPN!r}"
        )
    out = list(lines)
    out[mpn_index] = _render(head, {**body, "value": U3_RIGHT_MPN})

    group = _wire_group(out, *V3_WIRE)
    label_index = _net_label_index(out, group)
    label_head, label_body = _load(out[label_index])
    out[label_index] = _render(
        label_head, {**label_body, "value": "VCC", "valueVisible": True}
    )
    return out


BASE_BUILDERS = {
    "fixed_base": build_fixed_base,
}


# ---------------------------------------------------------------------------
# Builders: lines in, lines out. Each locates its records by content and
# asserts a unique hit before touching anything.
# ---------------------------------------------------------------------------


def build_v3_decap_missing(lines: list[str], variant_id: str) -> list[str]:
    """C1's COMPONENT and attributes go away; its wires stay where they are.

    Leaving the wires is deliberate: the missing part is the fault, and a
    board whose copper also vanished would be a different (and uninteresting)
    mistake. The dangling run is what a person actually leaves behind.
    """
    drop = set(_component_records(lines, "C1"))
    if len(drop) < 2:
        raise ValueError("C1 has no attribute stream to delete")
    return [line for index, line in enumerate(lines) if index not in drop]


def build_duplicate_designator(lines: list[str], variant_id: str) -> list[str]:
    """A second page holds a second R24, at the same coordinates."""
    source_id = _component_id(lines, "R24")
    source = _component_records(lines, "R24")
    page_index = next(
        i for i, h, b in _records(lines, "DOCHEAD")
        if b and b.get("docType") == "SCH_PAGE"
    )
    page_head, page_body = _load(lines[page_index])
    anchor = next(
        i for i, h, b in _records(lines, "DOCHEAD")
        if b and b.get("docType") == "CONFIG"
    )

    ticket = _next_ticket(lines)
    new_id = _rid(variant_id, "component")
    block = [
        _render(
            {**page_head, "ticket": ticket},
            {**page_body, "uuid": _rid(variant_id, "page")},
        ),
        _render(
            {"type": "META", "ticket": ticket + 1, "id": "META"},
            {
                "title": "P2",
                "schematic": page_body.get("schematic"),
                "source": "",
                "zIndex": 1,
            },
        ),
    ]
    for offset, index in enumerate(source):
        head, body = _load(lines[index])
        fresh = _rid(variant_id, "record", offset)
        if body is not None and str(body.get("parentId")) == source_id:
            body = {**body, "parentId": new_id}
        block.append(_render({**head, "ticket": ticket + 2 + offset, "id": fresh}, body))

    return lines[:anchor] + block + lines[anchor:]


def build_nc_pin_grounded(lines: list[str], variant_id: str) -> list[str]:
    """Clear U5.4's no-connect mark, then wire the pin to nearby GND."""
    cid = _component_id(lines, "U5")
    nc_index = next(
        i for i, _h, b in _records(lines, "ATTR")
        if b and b.get("key") == "NO_CONNECT"
        and str(b.get("parentId", "")).startswith(cid)
    )
    # Canvas coordinates: the pin tip, then a dogleg to the grounded capacitor
    # C6's tip (300,440), which is an endpoint of the GND run on that row.
    route = [(294.0, 370.0), (288.0, 370.0), (288.0, 440.0), (300.0, 440.0)]
    wires = _wire_lines(variant_id, "u5-4-to-gnd", route, _next_ticket(lines), 9001.0)
    out = [line for index, line in enumerate(lines) if index != nc_index]
    at = _page_end(out)
    return out[:at] + wires + out[at:]


def build_overvoltage_rail(lines: list[str], variant_id: str) -> list[str]:
    """Rename the +5V net to +9V in the page's own net declarations."""
    targets = [
        i for i, _h, b in _records(lines, "ATTR")
        if b and b.get("value") == "+5V"
        and b.get("key") in ("Name", "Global Net Name")
    ]
    if not targets:
        raise ValueError("no +5V net declaration found")
    out = list(lines)
    for index in targets:
        head, body = _load(lines[index])
        out[index] = _render(head, {**body, "value": "+9V"})
    return out


def build_ldo_no_headroom(lines: list[str], variant_id: str) -> list[str]:
    """Move U5.1's drop from the +5V riser onto the VOUT rail.

    The stub ``(204,-400)-(194,-400)`` is deleted rather than extended: an
    extended stub would leave VIN on +5V *and* VCC, which merges the two nets
    and is not the fault under test. The replacement runs below the regulator
    body -- x=194 down, across at y=330 (clear of U5's body, which starts at
    y=350), then up to the VOUT rail's vertex at (300,390).
    """
    riser_group = None
    stub_index = None
    for index, _h, b in _records(lines, "LINE"):
        if not b or b.get("startY") != -400 or b.get("endY") != -400:
            continue
        ends = {(b.get("startX"), b.get("endX"))}
        if ends == {(204, 194)}:
            stub_index = index
            riser_group = str(b.get("lineGroup"))
    if stub_index is None or riser_group is None:
        raise ValueError("U5.1's stub segment not found")

    route = [(204.0, 400.0), (194.0, 400.0), (194.0, 330.0), (300.0, 330.0), (300.0, 390.0)]
    ticket = _next_ticket(lines)
    fresh: list[str] = []
    for offset, (start, end) in enumerate(zip(route, route[1:])):
        fresh.append(_render(
            {"type": "LINE", "ticket": ticket + offset,
             "id": _rid(variant_id, "segment:vin-to-vout", offset)},
            {
                "fillColor": None, "fillStyle": None, "strokeColor": None,
                "strokeStyle": None, "strokeWidth": None,
                "startX": _num(start[0]), "startY": _num(-start[1]),
                "endX": _num(end[0]), "endY": _num(-end[1]),
                "lineGroup": riser_group,
            },
        ))
    out = [line for index, line in enumerate(lines) if index != stub_index]
    at = _page_end(out)
    return out[:at] + fresh + out[at:]


def build_value_mpn_mismatch(lines: list[str], variant_id: str) -> list[str]:
    """Rewrite U3's Value only -- the MPN keeps saying 470 ohm."""
    cid = _component_id(lines, "U3")
    index = next(
        i for i, _h, b in _records(lines, "ATTR")
        if b and str(b.get("parentId")) == cid and b.get("key") == "Value"
    )
    head, body = _load(lines[index])
    if body.get("value") != "1k\u03a9":
        raise ValueError(f"U3's value is {body.get('value')!r}, expected '1k\\u03a9'")
    out = list(lines)
    out[index] = _render(head, {**body, "value": "2.2k\u03a9"})
    return out


BUILDERS = {
    "v3_decap_missing": build_v3_decap_missing,
    "duplicate_designator": build_duplicate_designator,
    "nc_pin_grounded": build_nc_pin_grounded,
    "overvoltage_rail": build_overvoltage_rail,
    "ldo_no_headroom": build_ldo_no_headroom,
    "value_mpn_mismatch": build_value_mpn_mismatch,
}


# ---------------------------------------------------------------------------
# archive + annotation output
# ---------------------------------------------------------------------------


def _read_lines(path: Path) -> tuple[list[str], bytes, dict]:
    """The ``.epru`` text as lines, its member payload, and the project meta."""
    with zipfile.ZipFile(path) as archive:
        members = {i.filename: archive.read(i) for i in archive.infolist()}
    name = max(
        (n for n in members if n.lower().endswith(".epru")), key=lambda n: len(members[n])
    )
    return members[name].decode("utf-8").splitlines(), members[name], members


def _write_archive(members: dict[str, bytes], epru_name: str, text: str, out: Path) -> None:
    """Write the archive with a fixed DOS timestamp (repeatable bytes)."""
    members = dict(members)
    members[epru_name] = text.encode("utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)


def _annotation(variant: dict, source_rel: str, base_id: str) -> dict:
    if variant.get("retired"):
        # A retired board makes no ground-truth claim. Leaving the defect
        # record in place would put an unfulfillable requirement into every
        # aggregate run that happened to glob this directory -- the harness
        # would report a miss for a fault the oracle has already ruled out of
        # scope. The injection is still described, in the generator's table and
        # in this note, so nothing is lost; only the claim is withdrawn.
        return {
            "schema": "boardwise-review-annotations/1",
            "board": f"injected-{variant['id']}",
            "source": source_rel,
            "split_default": "dev",
            "reviewed_by": "",
            "reviewed_at": "",
            "notes": (
                f"RETIRED {variant['retired']} (task 011e sec.1.2). Derived from "
                f"reviewsets/injected/{base_id}.epro2 by "
                f"reviewsets/injected/make_variants.py, which is the only "
                f"writer of this file. The board is kept on disk so the "
                f"byte-identity guard keeps covering it, but it carries NO "
                f"records: it is in neither split and takes part in no "
                f"detection criterion. Fault it was built with: "
                f"{variant['fault']}. Edit: {variant['edit']}. Oracle note: "
                f"{variant['oracle_note']}"
            ),
            "items": [],
        }
    split = split_of(variant["id"])
    return {
        "schema": "boardwise-review-annotations/1",
        "board": f"injected-{variant['id']}",
        "source": source_rel,
        "split_default": split,
        "reviewed_by": SIGNED_BY,
        "reviewed_at": variant["signed"],
        "notes": (
            f"Signed injected-defect board (task 011d sec.4; proposal signed by "
            f"{SIGNED_BY} on {variant['signed']}). Derived from "
            f"reviewsets/injected/{base_id}.epro2 (the corrected reference "
            f"board) by reviewsets/injected/make_variants.py, which is the only "
            f"writer of this file. Fault: {variant['fault']}. Edit: "
            f"{variant['edit']}. The defect record below is the whole ground "
            f"truth for the INJECTED fault: the named rule must catch it, and "
            f"anything that rule adds beyond this record is a false positive. "
            f"Findings from other rules are the base board's own (this board is "
            f"the base plus one edit, and the base's records live in "
            f"{base_id}.json) -- they land in the harness's unexplained column "
            f"here, which is why the per-variant report quotes the expected "
            f"rule's own columns rather than the board total. Split: {split} "
            f"(011e sec.2 -- assigned by sha1(id), see make_variants.py). "
            f"Oracle note: {variant['oracle_note']}"
        ),
        "items": [
            {
                "ref": variant["ref"],
                "rule_hint": variant["expects"],
                "kind": "defect",
                "severity": variant["severity"],
                "split": split,
                "note": (
                    f"Injected fault: {variant['fault']} ({variant['edit']}). "
                    f"Expected catch: {variant['expects']}."
                ),
            }
        ],
    }


def _golden_exceptions() -> list[dict]:
    """The design's own exceptions, carried over from the signed golden set.

    X1's grounded case and R24/R27's intended pull-downs are properties of the
    corrected design as much as of the golden one, so the base inherits them
    verbatim. The golden set's *defect* records are deliberately NOT copied:
    those are exactly the two faults this base fixes, and a base that still
    claimed them would be a base that lies about itself.
    """
    raw = json.loads(
        (ROOT / "reviewsets" / "ch340g_golden.json").read_text(encoding="utf-8")
    )
    exceptions = [item for item in raw["items"] if item["kind"] == "exception"]
    defects = [item for item in raw["items"] if item["kind"] == "defect"]
    if len(exceptions) != 3 or len(defects) != 2:
        raise ValueError(
            "the golden set changed shape: expected 3 exceptions and 2 defects, "
            f"found {len(exceptions)} and {len(defects)} -- the base's records "
            "are derived from it, so this needs a look before regenerating"
        )
    return exceptions


def _base_annotation(base: dict, source_rel: str) -> dict:
    return {
        "schema": "boardwise-review-annotations/1",
        "board": base["id"],
        "source": source_rel,
        "split_default": "dev",
        "reviewed_by": SIGNED_BY,
        "reviewed_at": base["signed"],
        "notes": (
            f"The corrected reference board (task 011d sec.4 follow-up; oracle "
            f"rulings of {base['signed']}). Derived from "
            f"{GOLDEN.relative_to(ROOT).as_posix()} by "
            f"reviewsets/injected/make_variants.py. Fix: {base['fix']}. Edits: "
            + "; ".join(base["edits"])
            + ". It carries NO defect records -- the oracle ruled the corrected "
            "board correct -- only the three exceptions copied from the signed "
            "golden set. Every injected variant is derived from this board, "
            "which is what makes an injected fault a first-of-its-kind signal. "
            f"Oracle note: {base['oracle_note']}"
        ),
        "items": _golden_exceptions(),
    }


def _board_lines() -> tuple[list[str], list[str], dict[str, bytes], str]:
    """Golden lines, the clean base's lines, archive members, ``.epru`` name."""
    golden_lines, _payload, members = _read_lines(GOLDEN)
    epru_name = next(n for n in members if n.lower().endswith(".epru"))
    base = BASES[0]
    base_lines = BASE_BUILDERS[base["builder"]](golden_lines, base["id"])
    if base_lines == golden_lines:
        raise ValueError("the base build changed nothing")
    return golden_lines, base_lines, members, epru_name


def generate(
    ids: list[str], out_dir: Path | None = None, *, rebuild_retired: bool = False
) -> int:
    """Build the clean base plus the requested variants; refuse the unsigned.

    ``out_dir`` redirects where the boards land. ``--check`` uses it to build
    into a scratch directory, so a comparison never overwrites the committed
    fixtures -- measured the hard way: writing first and comparing afterwards
    let a mutated build become the new baseline, and every later check then
    agreed with the mutant.

    ``rebuild_retired`` is the guard's door, and only the guard's: a retired
    board may not be *authored* any more, but it must still be rebuildable or
    ``--check`` would stop watching the file it left on disk -- and a fixture
    nobody checks is a fixture that rots. So the refusal below is skipped when
    the caller says it is verifying rather than authoring.
    """
    known = {v["id"]: v for v in VARIANTS}
    table = {**{b["id"]: b for b in BASES}, **known}
    requested = ids or [
        v["id"] for v in VARIANTS if v["signed"] and not v.get("retired")
    ]

    unknown = [i for i in requested if i not in table]
    if unknown:
        print(f"unknown board(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    refused = [i for i in requested if not table[i]["signed"]]
    if refused and not rebuild_retired:
        for i in refused:
            spec = table[i]
            if spec.get("retired"):
                print(
                    f"refusing to generate {i!r}: retired {spec['retired']} -- "
                    f"kept on disk for the byte-identity guard only, not part "
                    f"of the eval set. {spec.get('oracle_note', '')}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"refusing to generate {i!r}: not signed by the oracle "
                    f"(withdrawn/pending). {spec.get('oracle_note', '')}",
                    file=sys.stderr,
                )
        return 2
    if not requested:
        print(
            "refusing to generate: no board in the table is signed yet "
            "(see --list). Task 011d sec.4.",
            file=sys.stderr,
        )
        return 2

    _golden, base_lines, members, epru_name = _board_lines()
    base = BASES[0]
    # The base is always rebuilt: every variant is derived from it, so a build
    # that shipped a stale substrate would be a build whose variants cannot be
    # reproduced from what is on disk.
    target_dir = out_dir or HERE
    writes = [(
        "base", base["id"], base_lines,
        _base_annotation(base, _source_rel(base["id"])),
    )]
    for variant_id in requested:
        if variant_id == base["id"]:
            continue
        variant = known[variant_id]
        edited = BUILDERS[variant["builder"]](base_lines, variant_id)
        if edited == base_lines:
            print(f"{variant_id}: edit changed nothing", file=sys.stderr)
            return 2
        writes.append((
            "variant", variant_id, edited,
            _annotation(variant, _source_rel(variant_id), base["id"]),
        ))

    target_dir.mkdir(parents=True, exist_ok=True)
    for kind, board_id, lines, annotation in writes:
        board = target_dir / f"{board_id}.epro2"
        _write_archive(members, epru_name, "\n".join(lines), board)
        (target_dir / f"{board_id}.json").write_text(
            json.dumps(annotation, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"built {kind} {board.name} ({len(lines)} records) "
              f"+ {board_id}.json")
    print(f"\n{len(writes) - 1} variant(s) over the clean base; splits as assigned "
          "by sha1(id) (011e sec.2).")
    return 0


def _source_rel(board_id: str) -> str:
    """The board's canonical path, spelled the way an annotation must."""
    return (HERE / f"{board_id}.epro2").relative_to(ROOT).as_posix()


def _tracked_ids() -> list[str]:
    """Every board the guard watches: the base plus every variant in the table.

    Retired boards are included on purpose. They are no longer authored, but
    their files are still committed, and an unwatched fixture is one that can
    drift without anyone noticing.
    """
    return [BASES[0]["id"]] + _variant_ids()


def check() -> int:
    """A fresh build must be byte-identical to what is committed.

    Both artifacts are compared, board *and* annotation set: the set is
    generated too, so a change there is a change to the fixtures whatever it
    does to the board (measured: guarding only ``.epro2`` let a mutated set
    ship unnoticed).

    The build goes to ``.tmp_variant_check`` -- an in-repo scratch path, per
    the project's rule against system temp -- and the committed files are
    only *read*. Writing first and comparing afterwards was the original
    shape and it lied: a mutated build became the new baseline, and every
    later check agreed with the mutant.
    """
    ids = _tracked_ids()
    before = {
        (i, suffix): (HERE / f"{i}.{suffix}").read_bytes()
        for i in ids for suffix in ("epro2", "json")
    }
    missing = [f"{i}.{s}" for (i, s) in before if not (HERE / f"{i}.{s}").is_file()]
    if missing:
        print(f"missing generated artifacts: {', '.join(missing)}", file=sys.stderr)
        return 2
    scratch = ROOT / ".tmp_variant_check"
    shutil.rmtree(scratch, ignore_errors=True)
    try:
        code = generate(
            _tracked_ids(), out_dir=scratch, rebuild_retired=True
        )
        if code != 0:
            return code
        drifted = [
            f"{i}.{suffix}" for (i, suffix), payload in before.items()
            if payload != (scratch / f"{i}.{suffix}").read_bytes()
        ]
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if drifted:
        print(f"regeneration is not byte-identical: {', '.join(drifted)}",
              file=sys.stderr)
        return 1
    print(f"--check: {len(ids)} board(s) and their annotation sets "
          "rebuild byte-identically")
    return 0


def list_variants() -> int:
    base = BASES[0]
    print(f"boards derived from {GOLDEN.name}:")
    print(f"\n0. {base['id']}  [signed {base['signed']} by {SIGNED_BY}]")
    print(f"   fix:      {base['fix']}")
    for edit in base["edits"]:
        print(f"   - {edit}")
    print(f"   note:     {base['oracle_note']}")
    for index, variant in enumerate(VARIANTS, 1):
        if variant.get("retired"):
            state = f"RETIRED {variant['retired']}"
        elif variant["signed"]:
            state = f"signed {variant['signed']} by {SIGNED_BY}"
        else:
            state = "NOT SIGNED"
        print(f"\n{index}. {variant['id']}  [{state}]")
        print(f"   fault:    {variant['fault']}")
        print(f"   edit:     {variant['edit']}")
        print(f"   expects:  {variant['expects']} (ref {variant['ref']}, {variant['severity']})")
        if not variant.get("retired"):
            print(f"   split:    {split_of(variant['id'])}")
        print(f"   note:     {variant['oracle_note']}")
    live = eval_ids()
    print(f"\n{len(live)} of {len(VARIANTS)} variants in the eval set: {', '.join(live)}")
    print(f"   holdout: {', '.join(sorted(holdout_ids()))}")
    print(f"   dev:     {', '.join(sorted(dev_ids()))}")
    print(
        "\n`--generate` rebuilds the clean base and then the live signed variants, "
        "refusing anything unsigned or retired (task 011d sec.4; 011 sec.6: "
        "injected faults must be real mistakes; 011e sec.2: the split is derived "
        "from sha1(id), never picked)."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the proposal table")
    parser.add_argument("--generate", nargs="*", default=None, metavar="VARIANT",
                        help="build signed variants (default: all live signed ones)")
    parser.add_argument("--check", action="store_true",
                        help="rebuild and compare against the committed boards")
    parser.add_argument("--rebuild-retired", action="store_true",
                        help="maintenance: also rebuild retired fixtures (the "
                             "byte-identity guard's door; they stay in no split)")
    args = parser.parse_args()
    if args.check:
        return check()
    if args.list or args.generate is None:
        return list_variants()
    if args.rebuild_retired:
        # Maintenance verb: build the live set *plus* every retired board, so a
        # shared-helper change can be applied to the files the guard watches.
        requested = list(args.generate) or [
            v["id"] for v in VARIANTS if v["signed"]
        ]
        for variant in VARIANTS:
            if variant.get("retired") and variant["id"] not in requested:
                requested.append(variant["id"])
        return generate(requested, rebuild_retired=True)
    return generate(args.generate)


if __name__ == "__main__":
    sys.exit(main())
