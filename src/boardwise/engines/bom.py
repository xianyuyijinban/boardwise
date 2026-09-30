"""The BOM a board spec implies (task 008c, work item 1).

A BOM is an **output**, not an input — xianyuyijinban's rule from 2026-09-16, and the
reason 008c has no BOM among its three inputs: nobody writes one before the
schematic; the schematic *is* where the parts come from. So this module derives
the bill from what the spec already says:

* each block component's ``device`` binding, and
* the parameter values the spec assigns for that block,

resolved against the curated shelf (008b) so that every designator in the file
traces back to a **verified** identity.

Two rules carry over from the library's own discipline (#202):

1. **A binding that resolves to nothing unique is an open question, never a
   choice.** "Closest C-number" and "the only other 5.1k" are the same mistake.
2. **A conflict is recorded, not averaged.** The same C-number carrying two
   different values is a defect in the specification, and it is reported as one
   rather than silently becoming one row with one of the two numbers.

"Different" means different *values*, not different spellings: one C-number
carrying ``100nF`` on one board and ``0.1uF`` on another is one 100 nF part
(issue #39), and the two are compared through the value parsers of
:mod:`boardwise.rules.values` before they are called a conflict. A value neither
parser can read is compared as written — a disagreement nobody can decode is
still a disagreement, and "cannot read it" must never become "so it is fine".

Nothing is skipped in silence, either: a part with no binding at all — an
abstract `Res_0602` placeholder, say — produces an open question naming its
designator, because a BOM that quietly omits a part is worse than no BOM.
"""

from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .assemble import assemble
from ..core.blocks import BlockComponent, BoardSpec, DeviceBinding, designator_map
from ..core.parts import PartEntry, PartLibrary, PartError, load_parts
from ..rules.values import parse_capacitance_farads, parse_resistance_ohms

#: The columns a JLC upload expects, in its order. Kept to exactly these five so
#: the file can be handed to the fab; everything else a reader might want (MPN,
#: shelf key, parameters) is in the JSON form.
CSV_COLUMNS = ("Comment", "Designator", "Footprint", "LCSC", "Qty")

_DESIGNATOR_PARTS = re.compile(r"^(?P<prefix>[A-Za-z]+)(?P<number>\d*)$")


class BomError(ValueError):
    """The BOM cannot be produced as asked."""


def _designator_sort_key(designator: str) -> tuple[str, int, str]:
    """Sort `R2` before `R10`, and keep anything unexpected after the rest."""
    match = _DESIGNATOR_PARTS.match(designator)
    if match is None:
        return ("~", 0, designator)
    return (match["prefix"].upper(), int(match["number"] or 0), designator)


@dataclass
class BomRow:
    """One line: one physical part, and every designator that uses it."""

    lcsc: str
    key: str
    mpn: str
    comment: str
    footprint: str
    designators: list[str]
    #: The template footref the blocks declared, kept for the report: the shelf
    #: name above is the library's vocabulary and this is the block's own claim.
    declared_footprints: list[str]

    @property
    def quantity(self) -> int:
        return len(self.designators)

    def csv_row(self) -> list[str]:
        return [
            self.comment,
            ",".join(sorted(self.designators, key=_designator_sort_key)),
            self.footprint,
            self.lcsc,
            str(self.quantity),
        ]

    def as_json(self) -> dict[str, object]:
        return {
            "lcsc": self.lcsc,
            "key": self.key,
            "mpn": self.mpn,
            "comment": self.comment,
            "footprint": self.footprint,
            "declared_footprints": sorted(set(self.declared_footprints)),
            "designators": sorted(self.designators, key=_designator_sort_key),
            "quantity": self.quantity,
        }


@dataclass
class BomReport:
    """The bill, plus everything that kept it from being complete."""

    spec_name: str
    rows: list[BomRow] = field(default_factory=list)
    #: Designators the export could not resolve, one line each, with the reason.
    open_questions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when every placed component resolved to a shelf entry."""
        return not self.open_questions

    @property
    def parts(self) -> int:
        return sum(row.quantity for row in self.rows)

    def csv(self) -> str:
        """The JLC-shaped CSV, with `\\n` endings so it is diffable."""
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for row in self.rows:
            writer.writerow(row.csv_row())
        return buffer.getvalue()

    def render(self) -> list[str]:
        lines = [
            f"BOM for {self.spec_name}: {len(self.rows)} line(s), "
            f"{self.parts} placed part(s)"
        ]
        for row in self.rows:
            lines.append(
                f"  {row.lcsc:10} {row.comment[:22]:22} {row.footprint[:24]:24} "
                f"x{row.quantity:<3} {', '.join(sorted(row.designators, key=_designator_sort_key))}"
            )
        for question in self.open_questions:
            lines.append(f"  open question: {question}")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return lines

    def as_json(self) -> dict[str, object]:
        return {
            "spec": self.spec_name,
            "columns": list(CSV_COLUMNS),
            "lines": [row.as_json() for row in self.rows],
            "placed_parts": self.parts,
            "open_questions": list(self.open_questions),
            "notes": list(self.notes),
        }


def resolve_binding(
    binding: DeviceBinding, library: PartLibrary
) -> tuple[PartEntry | None, str]:
    """``(entry, reason)`` for one binding. ``entry is None`` means "ask a human".

    **The C-number is the key**, because that is the one identifier that means
    "the same physical part" — the rule the harvest merges by (008b). The uuid
    pair and the keyword are *not* fallbacks here: a project-local uuid is not a
    library key (006b measured that twice), and a keyword is a search, not an
    identity. They are reported in the reason so the reader can see what the
    block actually claimed.
    """
    lcsc = (binding.lcsc or "").strip()
    if not lcsc:
        claimed = binding.name or binding.keyword or "(nothing)"
        return (
            None,
            f"the block binds no C-number (it claims {claimed!r}), so there is "
            "nothing to look up on the shelf",
        )
    entry = library.by_lcsc().get(lcsc)
    if entry is None:
        return (
            None,
            f"{lcsc} is not on the shelf; the export will not substitute a "
            "similar part",
        )
    return (entry, "")


def _value_for(spec: BoardSpec, block_id: str, component: BlockComponent) -> str:
    """The value a component carries: the spec's parameter, else the block's own."""
    bound = component.params.get("value")
    if bound:
        return spec.parameter_value(block_id, bound)
    return ""


def _quantity(text: str) -> tuple[str, float] | None:
    """``(kind, amount)`` when a value field is one this module can read.

    The kind travels with the number because the two parsers do not share a
    unit: 100 ohms and 100 nF are two different parts, and a comparison that
    forgot that would call them one.
    """
    ohms = parse_resistance_ohms(text)
    if ohms is not None:
        return "resistance", ohms
    farads = parse_capacitance_farads(text)
    if farads is not None:
        return "capacitance", farads
    return None


def _values_agree(first: str, second: str) -> bool:
    """True when two Comment fields are the same value, however they are spelled.

    ``100nF`` and ``0.1uF`` are one 100 nF part, and a BOM that called that a
    conflict would clear the Comment of a row the two boards agree on (issue
    #39). The comparison goes through the value parsers, so ``10uF`` /
    ``10UF`` and ``4u7`` / ``4.7uF`` are one value too.

    Equality is :func:`math.isclose`, not ``==``: ``100nF`` decodes to
    ``1.0000000000000001e-07`` and ``0.1uF`` to ``1e-07``, so exact comparison
    would trade one false conflict for another. A value neither parser reads is
    compared as written — unreadable is not the same as equal, and refusing to
    call it a conflict would be the silent pass this module exists to avoid.
    """
    if first == second:
        return True
    left, right = _quantity(first), _quantity(second)
    if left is not None and right is not None and left[0] == right[0]:
        return math.isclose(left[1], right[1], rel_tol=1e-9)
    return False


def build_bom(spec: BoardSpec, library: PartLibrary) -> BomReport:
    """Derive the bill from a spec and the shelf.

    Every placed component is visited through `designator_map`, so the designator
    in the BOM is the **page** designator — the one that will be drawn — and not
    the template's local one. That is what makes the file match the schematic for
    a board that places one block twice.
    """
    report = BomReport(spec_name=spec.name)
    refs = designator_map(spec)
    rows: dict[str, BomRow] = {}
    values_seen: dict[str, dict[str, str]] = {}

    for block in spec.blocks:
        for component in block.template.components:
            designator = refs[block.id][component.ref]
            entry, reason = resolve_binding(component.device, library)
            if entry is None:
                report.open_questions.append(
                    f"{designator} (block {block.id}, ref {component.ref}): {reason}"
                )
                continue
            value = _value_for(spec, block.id, component)
            row = rows.get(entry.lcsc)
            if row is None:
                row = BomRow(
                    lcsc=entry.lcsc,
                    key=entry.key,
                    mpn=entry.mpn,
                    comment=value or entry.mpn or entry.key,
                    footprint=entry.footprint_name,
                    designators=[],
                    declared_footprints=[],
                )
                rows[entry.lcsc] = row
                values_seen[entry.lcsc] = {}
            row.designators.append(designator)
            if component.footprint:
                row.declared_footprints.append(component.footprint)
            values_seen[entry.lcsc][designator] = value
            comment = value or entry.mpn or entry.key
            if not _values_agree(comment, row.comment):
                # One C-number, two values: the BOM would have to print one of
                # them, so it prints **neither** and says so. (#202's discipline:
                # an unresolvable disagreement is reported, never averaged into a
                # plausible-looking number.) Two spellings of one value are not
                # two values, and `_values_agree` is what says so.
                report.open_questions.append(
                    f"{entry.lcsc}: two components carry different values "
                    f"({designator}={comment!r} against {row.comment!r}); the same "
                    "physical part cannot have two values and the export will not "
                    "pick one"
                )
                row.comment = ""

    report.rows = [rows[lcsc] for lcsc in sorted(rows)]
    if report.rows:
        report.notes.append(
            "the Footprint column is the **library's** name for the package, not "
            "the block's human label (006b's vocabulary rule)"
        )
    return report


def write_csv(report: BomReport, path: str | Path) -> Path:
    """Write the CSV. The report is still what carries the open questions."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(report.csv(), encoding="utf-8")
    return file


def load_library(path: str | Path) -> PartLibrary:
    """Read the shelf, with `BomError` so the CLI reports instead of tracing back."""
    try:
        return load_parts(path)
    except PartError as exc:  # pragma: no cover - exercised through the CLI
        raise BomError(str(exc)) from exc


def assemble_for_bom(spec: BoardSpec) -> BoardSpec:
    """Validate a spec the way the draw chain does before trusting its BOM.

    The BOM is derived from the **spec**, so a spec that cannot be assembled —
    two blocks claiming one designator, two circuits claiming one net name — has
    no trustworthy part list either. Running the assembler first means the export
    cannot describe a board that would never be drawn.
    """
    assemble(spec)
    return spec


__all__ = [
    "BomError",
    "BomReport",
    "BomRow",
    "CSV_COLUMNS",
    "assemble_for_bom",
    "build_bom",
    "load_library",
    "resolve_binding",
    "write_csv",
]
