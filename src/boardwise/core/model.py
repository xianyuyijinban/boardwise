"""Normalized design model for boardwise.

Stage 1 only consumes EasyEDA Pro schematic netlists (``.enet``), but this
model is the long-term contract: the review engine, and later the generator
and the simulator, all operate on these types.

The ``role`` / ``block`` fields on :class:`Component` are reserved intent
metadata for the stage-2 generator. Nothing populates them yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Net-name prefixes treated as ground. Module-level so it can become
#: configurable later without touching rule code. ``VEE`` is deliberately
#: absent: it is a *negative supply* in analog/ECL circuits, not a ground
#: (2026-09-18 ruling, M0-P0c).
GROUND_NET_PREFIXES: tuple[str, ...] = (
    "GND",
    "AGND",
    "DGND",
    "PGND",
    "EGND",
    "SGND",
    "VSS",
)


def is_ground_net(name: str | None) -> bool:
    """Return True for common ground net names (GND, AGND, PGND, VSS, ...).

    Prefix match on the upper-cased name, so ``GNDA`` and ``VSSA`` also count.
    ``None`` and empty names are never ground.

    **The name is only a candidate.** A net's role should come from declared
    intent and from device facts (a part's pin function, a rail's source); this
    inference exists so that rules have something to say about a name they were
    handed, and it is deliberately narrow — a name it does not recognise is
    "not known to be ground", not "not ground". ``VEE`` used to be listed here,
    which made a negative supply read as ground; it is now left to the
    declarations and device facts that should have been deciding it.
    """
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(prefix) for prefix in GROUND_NET_PREFIXES)


@dataclass
class Pin:
    """One pin of a component."""

    number: str
    name: str
    net: str | None = None


@dataclass
class Component:
    """One placed component, keyed by designator inside the model."""

    uid: str
    designator: str
    value: str = ""
    footprint: str = ""
    lcsc_part: str = ""
    manufacturer: str = ""
    mpn: str = ""
    datasheet: str = ""
    props: dict[str, Any] = field(default_factory=dict)
    pins: list[Pin] = field(default_factory=list)
    # Reserved intent metadata for the stage-2 generator. Unused today.
    role: str | None = None
    block: str | None = None


@dataclass
class Net:
    """One named net. ``pins`` holds (designator, pin_number) tuples."""

    name: str
    pins: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DesignModel:
    """The normalized board model.

    - ``components``: designator -> Component
    - ``nets``: net name -> Net (reverse-built by the parser)
    - ``raw``: untouched top-level blocks from the source file
      (designRule / differentialPair / netClass / equalLengthNetGroup),
      kept verbatim because future rules will consume them.
    """

    components: dict[str, Component] = field(default_factory=dict)
    nets: dict[str, Net] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
