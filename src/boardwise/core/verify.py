"""Placement verification: did the editor actually place the golden part?

Why this module exists
----------------------
Task 006b revision 4 found the replay's fatal assumption (see
``tasks/006b-schematic-readability.md`` §E): every wire endpoint was replayed
at the *golden* symbol's pin tip, on the belief that whatever the library
resolved to would be that same symbol. It was not. ``Res_0402`` resolved to a
0603, a ``470Ω`` device to a ``1kΩ`` one, and a USB-C footprint whose pin
numbering had drifted from ``1..14`` to pad names (``A1B12``/``B5``…). Every
replayed endpoint then missed its pin tip, the pins floated, and the
connectivity collapsed — 51 differences that had nothing to do with the wire
geometry.

The fix has two halves. This module is the *detector*: given the golden model
and what the editor says it placed, decide whether the two still describe the
same part, pin for pin. The action planner (``engines.replay``) consumes the
answer and either remaps the endpoints or refuses to draw.

What can and cannot be measured
-------------------------------
There is no API to read a *placed* symbol's pin geometry on a schematic page:

* ``sch_PrimitivePin.getAll()`` returns empty — a pin belongs to the symbol,
  not to the page primitive set;
* the ``Symbol`` field of a component's state dump is an empty object — the
  editor declines to serialise the symbol reference;
* ``lib_Symbol.get`` returns ``ILIB_SymbolItem``, which carries identity and
  classification but **no pin geometry**.

So the honest evidence is the **editor's own netlist**, which reports every
pin's ``number``, ``name`` and resolved ``net`` (measured: the golden page's
own export lists 14 pins for USB1 with both ``number: "1"`` and
``name: "GND"``). Identity therefore has two stable keys, and this module uses
both:

1. **number** — the direct key, correct whenever the library version matches;
2. **name** — the *version-drift* key. Pin names come from the schematic
   author's intent (``GND``/``VBUS``/``CC1``) and survive a symbol redraw that
   renumbers every pin, which is exactly what happened to USB1.

``number`` is tried first because a number is unique within a symbol. When the
number sets disagree and the names can be matched (name for name, then
ordinal-within-name for the repeated ``GND``/``VBUS`` pads a connector legitimately
has), the mapping is recorded as *drifted* — the caller is told the pin numbering
has moved with the library version, rather than being handed 28 phantom pin
differences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from boardwise.core.model import Component, DesignModel

#: A part's pins matched by number — the library version is the same one the
#: golden was drawn against.
MATCH_EXACT = "exact"
#: A part's pins matched by name — the symbol was redrawn and renumbered, but
#: the pins are recognisably the same signals.
MATCH_DRIFTED = "drifted"
#: The part could not be matched at all: not the same device, or the pins
#: disagree on *both* keys. The draw flow must refuse the page.
MATCH_UNMAPPABLE = "unmappable"


@dataclass
class PinMap:
    """How a golden part's pins correspond to the placed part's pins.

    ``pairs`` maps *golden pin number* -> *placed pin number*. ``kind`` is one
    of :data:`MATCH_EXACT` / :data:`MATCH_DRIFTED` / :data:`MATCH_UNMAPPABLE`.
    ``unmatched`` lists golden pin numbers with no counterpart, and ``detail``
    is a one-line human reason safe to print in the acceptance report.
    """

    designator: str
    kind: str
    pairs: dict[str, str] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    detail: str = ""

    @property
    def ok(self) -> bool:
        """True when every golden pin has a placed counterpart."""
        return self.kind != MATCH_UNMAPPABLE and not self.unmatched

    def remap(self, golden_number: str) -> str:
        """The placed-page pin number a golden pin number lands on.

        Identity when the mapping is exact; the drifted counterpart otherwise.
        An unmapped number is returned unchanged — the caller checks
        :attr:`ok` first, so this is only a defensive default.
        """
        return self.pairs.get(golden_number, golden_number)


@dataclass
class PlacementCheck:
    """The per-designator verdict the acceptance report prints."""

    designator: str
    kind: str
    detail: str
    pin_map: PinMap | None = None

    @property
    def ok(self) -> bool:
        return self.kind != MATCH_UNMAPPABLE


@dataclass
class PlacementReport:
    """Every part's verdict, plus the flat list of problems worth stopping for."""

    checks: list[PlacementCheck] = field(default_factory=list)
    #: Pins of the placed page that matched no golden pin (extra pads).
    orphan_pins: dict[str, list[str]] = field(default_factory=dict)

    @property
    def unmappable(self) -> list[PlacementCheck]:
        return [c for c in self.checks if c.kind == MATCH_UNMAPPABLE]

    @property
    def drifted(self) -> list[PlacementCheck]:
        return [c for c in self.checks if c.kind == MATCH_DRIFTED]

    @property
    def ok(self) -> bool:
        """True when nothing blocks the draw: no unmappable part, no orphans.

        A *drifted* part is not a blocker — the endpoints are remapped by name
        and the drift is reported — but an unmappable part or an extra pad
        means the replayed geometry cannot be trusted and the run must stop
        before it draws a broken page.
        """
        return not self.unmappable and not any(self.orphan_pins.values())

    def blocks(self) -> str:
        """A one-line reason the report is not ok, or an empty string."""
        parts = [c.designator for c in self.unmappable]
        orphans = [d for d, pins in self.orphan_pins.items() if pins]
        if not parts and not orphans:
            return ""
        bits = []
        if parts:
            bits.append("unmappable parts: " + ", ".join(parts))
        if orphans:
            bits.append("extra pins on: " + ", ".join(orphans))
        return "; ".join(bits)

    def map_for(self, designator: str) -> PinMap | None:
        for check in self.checks:
            if check.designator == designator:
                return check.pin_map
        return None


def _norm_name(name: str) -> str:
    """Normalise a pin name for comparison: case- and space-insensitive.

    Measured on the machine (2026-09-14, USB1): the golden symbol spells the
    differential pairs ``DN2`` / ``DP1`` while the current library spells them
    ``Dn2`` / ``Dp1``. Those are the same signal; a case-sensitive comparison
    reported four pins as unmatchable and took the whole part down as
    "unmappable".
    """
    return "".join(str(name or "").split()).upper()


def _named_pins(pins) -> dict[str, str]:
    """number -> normalised name for the pins that carry a non-empty name."""
    return {
        str(p.number): _norm_name(p.name)
        for p in pins
        if str(p.name or "").strip()
    }


def _match_by_name(
    golden_names: dict[str, str], placed_names: dict[str, str],
) -> dict[str, str] | None:
    """Match golden pins to placed pins by name, then by ordinal within a name.

    Names are the join key because the schematic author's intent
    (``GND``/``VBUS``/``CC1``) survives a symbol redraw that renumbers every
    pin — which is exactly how USB1 drifted from ``1..14`` to pad names.

    A name that occurs once on each side matches trivially. A name that
    occurs *several* times — a Type-C connector genuinely has two ``GND`` and
    two ``VBUS`` pads — is matched by **ordinal position within that name**
    (the 1st golden ``GND`` -> the 1st placed ``GND``). This is deterministic
    and is the standard pin-mapping fallback; the alternative (refusing)
    would make the very drift this module exists to handle unmappable.

    The match is rejected unless it consumes *every* named golden pin, so a
    genuine mismatch (a name count that differs between the two sides) is
    still reported as unmappable rather than forced.
    """
    from collections import defaultdict

    golden_by_name: dict[str, list[str]] = defaultdict(list)
    for num, name in golden_names.items():
        golden_by_name[name].append(num)
    placed_by_name: dict[str, list[str]] = defaultdict(list)
    for num, name in placed_names.items():
        placed_by_name[name].append(num)

    pairs: dict[str, str] = {}
    for name, g_nums in golden_by_name.items():
        p_nums = placed_by_name.get(name, [])
        if len(p_nums) != len(g_nums):
            continue  # a name-count disagreement: leave it to the verdict
        for g_num, p_num in zip(g_nums, p_nums):
            pairs[g_num] = p_num
    return pairs or None


def build_pin_map(
    designator: str,
    golden: Component,
    placed: Component | None,
) -> PinMap:
    """Match one golden part's pins to what the editor reports it placed.

    The ladder is deliberate, strongest key first:

    1. the part is absent from the placed page -> unmappable;
    2. every golden pin number exists on the placed part -> **exact**;
    3. the pins are name-addressable and match one-to-one -> **drifted**
       (the library renumbered the symbol; the signals are the same);
    4. anything else -> unmappable, with the disagreement spelled out.
    """
    if placed is None:
        return PinMap(
            designator=designator,
            kind=MATCH_UNMAPPABLE,
            detail="the part is not present on the drawn page",
        )

    golden_nums = [str(p.number) for p in golden.pins]
    placed_nums = {str(p.number) for p in placed.pins}

    # 2. the direct key: identical numbering means the library version matches.
    if golden_nums and all(n in placed_nums for n in golden_nums):
        return PinMap(
            designator=designator,
            kind=MATCH_EXACT,
            pairs={n: n for n in golden_nums},
            detail=f"{len(golden_nums)} pins matched by number",
        )

    # 3. the drift key — and it is *hybrid*, because that is what a real
    # symbol redraw looks like. Measured on the machine (2026-09-14, USB1):
    # the library renamed twelve pins to pad names (``1..12`` -> ``A1B12``,
    # ``B4A9``, ``B5``…) but left ``13``/``14`` numbered as before. Matching
    # "all by number" fails and so does "all by name"; the pins whose number
    # survives must be matched by number, and only the rest by name.
    golden_names = _named_pins(golden.pins)
    placed_names = _named_pins(placed.pins)
    if golden_names and placed_names:
        pairs: dict[str, str] = {}
        used: set[str] = set()
        leftover: list[str] = []
        for number in golden_nums:
            if number in placed_nums:
                pairs[number] = number
                used.add(number)
            else:
                leftover.append(number)
        if leftover:
            remaining = {
                k: v for k, v in placed_names.items() if k not in used
            }
            by_name = _match_by_name(
                {n: golden_names[n] for n in leftover if n in golden_names},
                remaining,
            )
            if by_name is not None:
                pairs.update(by_name)

        unmatched = [n for n in golden_nums if n not in pairs]
        if not unmatched and pairs:
            by_number = sum(1 for k, v in pairs.items() if k == v)
            return PinMap(
                designator=designator,
                kind=MATCH_DRIFTED,
                pairs=pairs,
                detail=(
                    "pin numbering drifted with the library version; "
                    f"{len(pairs)} pins matched "
                    f"({by_number} by number, {len(pairs) - by_number} by name)"
                ),
            )

    # 4. neither key lines up: refuse rather than draw a broken page.
    missing = [n for n in golden_nums if n not in placed_nums]
    return PinMap(
        designator=designator,
        kind=MATCH_UNMAPPABLE,
        unmatched=missing,
        detail=(
            f"no pin mapping: {len(missing)} golden pin(s) absent from the "
            f"placed part ({', '.join(missing[:6])}"
            + ("…" if len(missing) > 6 else "") + ")"
        ),
    )


def verify_placements(
    golden: DesignModel, placed: DesignModel,
) -> PlacementReport:
    """Build the whole-page placement verdict: golden part vs placed part.

    ``placed`` is the candidate model read back from the editor (netlist
    first, geometry as the fallback). Every golden component gets a check; a
    part the editor reports but the golden does not know is recorded as an
    orphan-pin carrier instead of being silently dropped.
    """
    report = PlacementReport()
    for designator in sorted(golden.components):
        golden_comp = golden.components[designator]
        placed_comp = placed.components.get(designator)
        pin_map = build_pin_map(designator, golden_comp, placed_comp)
        report.checks.append(
            PlacementCheck(
                designator=designator,
                kind=pin_map.kind,
                detail=pin_map.detail,
                pin_map=pin_map,
            )
        )
        if placed_comp is not None:
            mapped = set(pin_map.pairs.values())
            extra = [
                str(p.number) for p in placed_comp.pins
                if str(p.number) not in mapped
            ]
            if extra:
                report.orphan_pins[designator] = extra
    return report
