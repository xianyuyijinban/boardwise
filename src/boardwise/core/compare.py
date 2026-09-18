"""Golden-vs-candidate design comparison — the referee for AI-drawn boards.

Compares two :class:`boardwise.core.model.DesignModel` instances at three
strictness levels (task 005):

1. **component level** — designator sets, then ``footprint`` / ``value`` /
   ``lcsc`` for common components;
2. **net level** — net-name sets, then per-net member sets;
3. **pin level** — the core: for common components, every pin's net mapping.

Normalisation rules are fixed here on purpose (they are the contract):

- **value**: case-insensitive; engineering-notation equality when both sides
  parse unambiguously (``10k`` == ``10K`` == ``10000``). A lowercase ``m``
  multiplier is treated as ambiguous (milli on a resistor, micro on old
  capacitor markings) and forces degenerate string comparison; so does any
  multi-token value (``472M 1KV`` never numerically equals ``472M``).
- **designator / net name / pin number**: exact strings, case-sensitive
  (``1`` and ``01`` are different pins).
- **footprint / lcsc**: exact strings after trimming.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from boardwise.core.model import DesignModel, Net

#: Difference levels, in report order.
COMPONENT_LEVEL = "component"
NET_LEVEL = "net"
PIN_LEVEL = "pin"

#: A part whose library symbol was redrawn and renumbered (see
#: :mod:`boardwise.core.verify`). Imported as a literal to keep this module
#: free of a compare -> verify import cycle; they are contractually equal.
DRIFTED_KIND = "drifted"


@dataclass
class Difference:
    """One difference, human-readable on every field."""

    level: str
    subject: str
    detail: str
    golden: str
    candidate: str

    def render(self) -> str:
        return (
            f"[{self.level}] {self.subject}: {self.detail}; "
            f"golden={self.golden!r} candidate={self.candidate!r}"
        )


@dataclass
class ComparisonReport:
    """Grouped differences; empty everywhere means the designs match."""

    component_differences: list[Difference] = field(default_factory=list)
    net_differences: list[Difference] = field(default_factory=list)
    pin_differences: list[Difference] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (
            len(self.component_differences)
            + len(self.net_differences)
            + len(self.pin_differences)
        )

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    def render(self) -> str:
        lines = [d.render() for d in self.component_differences]
        lines += [d.render() for d in self.net_differences]
        lines += [d.render() for d in self.pin_differences]
        lines.append(
            f"total: {self.total} difference(s) "
            f"(component {len(self.component_differences)}, "
            f"net {len(self.net_differences)}, "
            f"pin {len(self.pin_differences)})"
        )
        return "\n".join(lines)

    def to_jsonable(self) -> dict:
        def dump(diffs: list[Difference]) -> list[dict]:
            return [
                {
                    "level": d.level,
                    "subject": d.subject,
                    "detail": d.detail,
                    "golden": d.golden,
                    "candidate": d.candidate,
                }
                for d in diffs
            ]

        return {
            "component": dump(self.component_differences),
            "net": dump(self.net_differences),
            "pin": dump(self.pin_differences),
            "total": self.total,
        }


# --------------------------------------------------------------------------
# value normalisation
# --------------------------------------------------------------------------

#: A single engineering quantity: number, optional SI prefix, optional unit.
#: The prefix and unit are validated, not free-form, so ``472M 1KV`` (two
#: tokens) never matches this pattern and degrades to string comparison.
_QUANTITY_RE = re.compile(
    r"^(?P<num>[0-9]*\.?[0-9]+)\s*(?P<prefix>[pnuµμkKMR]|meg)?\s*"
    r"(?P<unit>Ω|ohm|Ohm|OHM|F|H)?$",
)

#: SI prefixes that are safe to interpret case-insensitively. Lowercase ``m``
#: is deliberately absent: on resistors it would be milli, on older capacitor
#: markings micro — the same string, two meanings four orders apart. A value
#: that only parses with ``m`` is therefore ambiguous and degrades to string
#: comparison instead of guessing.
_UNAMBIGUOUS_PREFIXES: dict[str, float] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "meg": 1e6,
    "R": 1.0,  # resistor decimal marker: 4R7 == 4.7
}


#: The resistor decimal marker: ``4R7`` means 4.7 Ω — the R *is* the decimal
#: point, so it is handled before the general quantity pattern.
_RESISTOR_R_RE = re.compile(r"^(?P<int>[0-9]+)R(?P<frac>[0-9]+)$")


def _parse_quantity(text: str) -> float | None:
    """Parse one engineering quantity to a plain number, or ``None``.

    Returns ``None`` for anything ambiguous or multi-token — the caller then
    falls back to string comparison. See the module docstring for the rules
    and the ``472M`` capacitor trap.
    """
    stripped = text.strip()
    if not stripped or any(ch.isspace() for ch in stripped):
        return None
    r_match = _RESISTOR_R_RE.match(stripped)
    if r_match:
        return float(f"{r_match.group('int')}.{r_match.group('frac')}")
    match = _QUANTITY_RE.match(stripped)
    if match is None:
        return None
    prefix = match.group("prefix")
    number = float(match.group("num"))
    if prefix is None:
        return number
    multiplier = _UNAMBIGUOUS_PREFIXES.get(prefix)
    if multiplier is None:
        return None  # ambiguous prefix (lowercase m): refuse to guess
    return number * multiplier


def values_equal(golden: str, candidate: str) -> bool:
    """Compare two component values under the task-005 normalisation rules."""
    g = (golden or "").strip()
    c = (candidate or "").strip()
    if g == c:
        return True
    if g.lower() == c.lower():
        return True  # case-insensitive equality, e.g. ``10k`` vs ``10K``
    g_num = _parse_quantity(g)
    c_num = _parse_quantity(c)
    if g_num is not None and c_num is not None:
        return g_num == c_num
    return False  # degenerate: string comparison already said "not equal"


def compare_models(
    golden: DesignModel,
    candidate: DesignModel,
    pin_maps: "dict[str, Any] | None" = None,
) -> ComparisonReport:
    """Compare two design models at component, net and per-pin level.

    ``pin_maps`` (F4, 006b revision 4) is an optional
    ``designator -> PinMap`` from :mod:`boardwise.core.verify`. When a part's
    library symbol was redrawn and renumbered, its golden pin *numbers* no
    longer address its placed pins — the identity is the pin *name*. Passing
    the map makes the per-pin comparison follow that identity, so a
    renumbered part is compared pin-for-pin instead of producing one phantom
    "pin extra / pin net mapping differs" pair per pin.

    A part whose map is :data:`~boardwise.core.verify.MATCH_DRIFTED` and whose
    mapped pins still disagree is a genuine difference — only the *addressing*
    is translated, never the verdict. Parts without a map keep the old
    number-addresses-number behaviour, so this is exactly backwards
    compatible.
    """
    report = ComparisonReport()

    def _candidate_pin(designator: str, number: str) -> str:
        """The candidate pin number a golden pin number addresses for a part."""
        if pin_maps:
            pin_map = pin_maps.get(designator)
            if pin_map is not None and pin_map.kind == DRIFTED_KIND:
                return pin_map.remap(number)
        return number

    # --- component level -------------------------------------------------
    golden_ids = set(golden.components)
    candidate_ids = set(candidate.components)
    for designator in sorted(golden_ids - candidate_ids):
        report.component_differences.append(
            Difference(COMPONENT_LEVEL, designator, "component missing in candidate", "present", "absent")
        )
    for designator in sorted(candidate_ids - golden_ids):
        report.component_differences.append(
            Difference(COMPONENT_LEVEL, designator, "component extra in candidate", "absent", "present")
        )
    for designator in sorted(golden_ids & candidate_ids):
        g = golden.components[designator]
        c = candidate.components[designator]
        if (g.footprint or "").strip() != (c.footprint or "").strip():
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "footprint differs", g.footprint, c.footprint)
            )
        if not values_equal(g.value, c.value):
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "value differs", g.value, c.value)
            )
        if (g.lcsc_part or "").strip() != (c.lcsc_part or "").strip():
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "lcsc differs", g.lcsc_part, c.lcsc_part)
            )

    # --- net level --------------------------------------------------------
    golden_nets = set(golden.nets)
    candidate_nets = set(candidate.nets)
    for name in sorted(golden_nets - candidate_nets):
        report.net_differences.append(
            Difference(NET_LEVEL, name, "net missing in candidate", "present", "absent")
        )
    for name in sorted(candidate_nets - golden_nets):
        report.net_differences.append(
            Difference(NET_LEVEL, name, "net extra in candidate", "absent", "present")
        )
    for name in sorted(golden_nets & candidate_nets):
        g_members = set(golden.nets[name].pins)
        c_members = set(candidate.nets[name].pins)
        # Translate golden members onto the candidate's addressing first: on a
        # renumbered part, ("USB1","1") and ("USB1","A1B12") are the same pin,
        # and reporting one as missing and the other as extra would be the
        # 28-phantom-difference trap F4 exists to close.
        g_translated = {
            (des, pin_maps[des].remap(num))
            if pin_maps and des in pin_maps and pin_maps[des].kind == DRIFTED_KIND
            else (des, num)
            for des, num in g_members
        }
        for member in sorted(g_translated - c_members):
            report.net_differences.append(
                Difference(NET_LEVEL, name, "member missing in candidate", f"{member[0]}.{member[1]}", "-")
            )
        for member in sorted(c_members - g_translated):
            report.net_differences.append(
                Difference(NET_LEVEL, name, "member extra in candidate", "-", f"{member[0]}.{member[1]}")
            )

    # --- pin level (the core) ---------------------------------------------
    for designator in sorted(golden_ids & candidate_ids):
        g_pins = {p.number: p for p in golden.components[designator].pins}
        c_pins = {p.number: p for p in candidate.components[designator].pins}
        # Which candidate pins the golden's pins address, per the identity map
        # (identity for every part whose symbol still matches).
        addressed = {
            number: _candidate_pin(designator, number) for number in g_pins
        }
        for number in sorted(g_pins):
            g_net = g_pins[number].net
            c_pin = c_pins.get(addressed[number])
            c_net = c_pin.net if c_pin is not None else "<<no such pin>>"
            if (g_net or "") != (c_net or ""):
                report.pin_differences.append(
                    Difference(
                        PIN_LEVEL,
                        f"{designator}.{number}",
                        "pin net mapping differs",
                        g_net or "unconnected",
                        c_net or "unconnected",
                    )
                )
        # A candidate pin is "extra" only when no golden pin addresses it.
        for number in sorted(set(c_pins) - set(addressed.values())):
            report.pin_differences.append(
                Difference(
                    PIN_LEVEL,
                    f"{designator}.{number}",
                    "pin extra in candidate",
                    "-",
                    c_pins[number].net or "unconnected",
                )
            )
    return report


def reconcile_names(candidate: DesignModel, golden: DesignModel) -> DesignModel:
    """Rename the candidate's nets to the golden names, matched by membership.

    Calibration-mode preprocessing. The editor names nets *it* finds unnamed
    ``$1N5, $1N22, …`` while our golden-side parser names the same clusters
    deterministically (``NET1, NET22, …``); a calibration comparison must ask
    "same connectivity?" — i.e. compare by membership — without letting a
    naming convention masquerade as a drawing error. A candidate net whose
    membership exactly matches a golden net is renamed; anything else keeps
    its name and surfaces as a real difference. Deliberately *not* used by
    the draw verdict, where the drawn board carries our names explicitly and
    names must match verbatim.
    """
    golden_by_members: dict[frozenset, str] = {}
    for name, net in golden.nets.items():
        golden_by_members.setdefault(frozenset(net.pins), name)

    renamed: dict[str, str] = {}
    taken: set[str] = set()
    for name, net in candidate.nets.items():
        match = golden_by_members.get(frozenset(net.pins))
        if match and match not in taken:
            renamed[name] = match
            taken.add(match)

    import copy as _copy

    out = DesignModel(raw=dict(candidate.raw))
    for designator, component in candidate.components.items():
        clone = _copy.deepcopy(component)
        for pin in clone.pins:
            if pin.net in renamed:
                pin.net = renamed[pin.net]
        out.components[designator] = clone
    nets: dict[str, Net] = {}
    for name, net in candidate.nets.items():
        new_name = renamed.get(name, name)
        entry = nets.setdefault(new_name, Net(name=new_name))
        for member in net.pins:
            if member not in entry.pins:
                entry.pins.append(member)
    out.nets = nets
    return out
