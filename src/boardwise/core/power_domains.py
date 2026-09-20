"""Net voltage-domain inference (task 011c sec.3.1).

The shared dependency of the PWR-1/PWR-2/PATH-1 rules: given a schematic
model and the curated part library, answer "what voltage is this net at, and
who says so". Only two evidence sources exist, both conservative:

1. **the net's own name**, through a whitelist of numeric forms (``+5V``,
   ``5V0``, ``3V3``, ``3.3V``, ``1V8``...). A bare ``VCC``/``VDD``/``VBUS``
   is **never** guessed: names lie, and the 011 family exists because a name
   that reads like a rail is not a declaration;
2. **the facts library's regulator outputs**: an ``ic.ldo`` entry whose MPN
   suffix decodes to an output voltage puts that voltage on the net its
   output pin sits on (RT9013-**33**GB -> 3.3 V). The output *pin* comes
   from the entry's own facts (its output-capacitor pin, i.e. the required
   cap that is not on a supply pin); the output *voltage* comes from the MPN
   suffix — never from a net name, which would be the tail wagging the dog.

Resolution is deliberately strict: one distinct value -> KNOWN (with its
source string quoted verbatim in reports); several disagreeing values ->
CONFLICT (an UNKNOWN, listing every source); no candidate at all -> UNKNOWN.
Every consumer therefore treats "unknown domain" as a first-class answer,
never as zero volts and never as "whatever the name looks like".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import DesignModel
from .parts import PartEntry, PartLibrary, find_facts

#: Domain states. KNOWN and CONFLICT/UNKNOWN mirror the harness's honesty
#: split: KNOWN asserts, the other two explain why they cannot.
KNOWN = "KNOWN"
CONFLICT = "CONFLICT"
UNKNOWN = "UNKNOWN"

# ``+5V`` / ``12V`` / ``3.3V`` — optional plus, number, trailing V.
_V_FORM = re.compile(r"^\+?(\d+(?:\.\d+)?)V$")
# ``5V0`` / ``3V3`` / ``1V8`` — the ShortJam commas-free rail style. Exactly
# one decimal digit: ``12V34`` is not a rail anyone names.
_MN_FORM = re.compile(r"^(\d+)V(\d)$")


def voltage_from_net_name(name: str | None) -> tuple[float, str] | None:
    """Decode a whitelisted rail name into ``(volts, source)`` — or None.

    The source string is what rules quote verbatim. Anything the whitelist
    does not recognise (``VCC``, ``VBUS``, ``VEE``, ``NET7``) returns None:
    not guessed, not zero.
    """
    if not name:
        return None
    m = _V_FORM.match(name)
    if m:
        volts = float(m.group(1))
        return volts, f"net name {name!r}"
    m = _MN_FORM.match(name)
    if m:
        volts = float(f"{m.group(1)}.{m.group(2)}")
        return volts, f"net name {name!r}"
    return None


def ldo_output_voltage(mpn: str) -> float | None:
    """Decode an LDO's fixed output voltage from its MPN suffix.

    ``RT9013-33GB`` -> 3.3, ``AMS1117-3.3`` -> 3.3. Returns None for anything
    the two known suffix shapes do not match: adjustable parts (``AMS1117-ADJ``)
    have no fixed output, and guessing one from the preceding digits would be
    fabrication.
    """
    if not mpn:
        return None
    m = re.search(r"(\d)\.(\d)V?$", mpn)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"(\d)(\d)(?:GB|G|B|SX|S|A)?$", mpn)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    return None


def ldo_output_pin(entry: PartEntry) -> str | None:
    """The LDO's output pin, from its own facts: the required capacitor that
    is not on a supply pin. Both measured entries (RT9013: caps on 1/5 with
    VIN on 1; AMS1117: cap on 2 with VIN on 3) resolve unambiguously; an entry
    that does not gets None and contributes no domain."""
    supply = {
        pin
        for record in entry.facts.get("supply_pins", [])
        for pin in record.get("pins", [])
    }
    for cap in entry.facts.get("required_caps", []):
        if cap.get("pin") not in supply:
            return cap.get("pin")
    return None


@dataclass
class DomainGuess:
    """One net's voltage verdict, with the evidence attached.

    ``source`` is the winning evidence string (KNOWN) or empty; ``detail``
    carries every candidate seen, so a CONFLICT can name both sides and an
    UNKNOWN can say "nobody speaks for this net".
    """

    net: str
    state: str
    volts: float | None = None
    source: str = ""
    detail: str = ""

    @property
    def is_known(self) -> bool:
        return self.state == KNOWN and self.volts is not None


def _facts_entry(
    model: DesignModel, library: PartLibrary
) -> dict[str, PartEntry]:
    """One exact-match shelf lookup per component, resolved once."""
    entries: dict[str, PartEntry] = {}
    for comp in model.components.values():
        entry = None
        if comp.mpn:
            entry = find_facts(library, mpn=comp.mpn)
        if entry is None and comp.lcsc_part:
            entry = find_facts(library, lcsc=comp.lcsc_part)
        if entry is not None:
            entries[comp.designator] = entry
    return entries


def infer_net_domains(
    model: DesignModel, library: PartLibrary
) -> dict[str, DomainGuess]:
    """Voltage verdicts for every net that has at least one candidate source.

    Nets with no candidate get no entry here; rules that need one must treat
    the absence as UNKNOWN with their own missing_fact (the caller knows what
    it asked for).
    """
    candidates: dict[str, list[tuple[float, str]]] = {}

    for name in model.nets:
        hit = voltage_from_net_name(name)
        if hit is not None:
            candidates.setdefault(name, []).append(hit)

    entries = _facts_entry(model, library)
    for comp in model.components.values():
        entry = entries.get(comp.designator)
        if entry is None or entry.category != "ic.ldo":
            continue
        volts = ldo_output_voltage(entry.mpn or comp.mpn)
        out_pin = ldo_output_pin(entry)
        if volts is None or out_pin is None:
            continue
        pin = next((p for p in comp.pins if p.number == out_pin), None)
        if pin is not None and pin.net:
            candidates.setdefault(pin.net, []).append(
                (volts, f"{comp.designator} {entry.mpn} output")
            )

    guesses: dict[str, DomainGuess] = {}
    for net, found in candidates.items():
        distinct = sorted({volts for volts, _ in found})
        if len(distinct) == 1:
            guesses[net] = DomainGuess(
                net=net,
                state=KNOWN,
                volts=distinct[0],
                source=found[0][1],
                detail="; ".join(f"{v} V per {s}" for v, s in found),
            )
        else:
            guesses[net] = DomainGuess(
                net=net,
                state=CONFLICT,
                volts=None,
                detail="; ".join(f"{v} V per {s}" for v, s in found)
                + " — the sources disagree, so no voltage is asserted",
            )
    return guesses


def domain_of(
    guesses: dict[str, DomainGuess], net: str | None
) -> tuple[float | None, str, str]:
    """The voltage of one net, as ``(volts, source, why_not)``.

    KNOWN returns ``(volts, source, "")``. Anything else returns
    ``(None, "", reason)`` where the reason is a ready-made missing_fact:
    an absent entry is "no source names this net's voltage", a CONFLICT
    quotes both sides. ``None``/empty net names are unknown too.
    """
    if not net:
        return None, "", "the pin has no net"
    guess = guesses.get(net)
    if guess is None:
        return None, "", f"no source names the voltage of net {net!r}"
    if guess.is_known:
        return guess.volts, guess.source, ""
    return None, "", (
        f"net {net!r} has conflicting voltage sources: {guess.detail}"
    )
