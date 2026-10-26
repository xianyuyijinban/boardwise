"""Shared decoupling-capacitor inventory and requirement decisions (540B3).

This module owns the electrical contract used by both the review rule and the
add-component idempotence probe: candidate identity, capacitor inventory,
value recovery and the single ``CapDecision`` comparison.  Findings, severity,
mode-sensitive rule evaluation and same-net diagnostics remain in
``rules.decap``.  No function here mutates the model or invents a second rule.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .model import Component, DesignModel, is_ground_net
from .partkind import CATEGORY_GATED, category_verdict, declared_category
from .values import decode_eia_3digit, mpn_value_code, parse_capacitance_farads

__all__ = [
    "VALUE_SOURCE_SCHEMATIC", "VALUE_SOURCE_SHELF", "VALUE_SOURCE_MPN",
    "VALUE_SOURCES_RECOVERED", "CapCandidate", "CapDecision",
    "looks_like_capacitor", "component_looks_like_capacitor", "gated_capacitor",
    "candidate_farads", "recovered_capacitance", "recovered_farads",
    "value_source_label", "cap_candidates_on", "decide_required_cap",
    "capacitance_text", "bridges_to_ground",
]

_CAP_DESIGNATOR = re.compile(r"^C\d")
_CHIP_SIZE_FOOTPRINT = re.compile(r"^(?:[A-Za-z]+[-_]?)?\d{4}$")
_CAPACITOR_CATEGORIES = frozenset({"capacitor"})

VALUE_SOURCE_SCHEMATIC = "schematic"
VALUE_SOURCE_SHELF = "shelf"
VALUE_SOURCE_MPN = "mpn"
VALUE_SOURCES_RECOVERED = frozenset({VALUE_SOURCE_SHELF, VALUE_SOURCE_MPN})
_VALUE_SOURCE_LABELS = {
    VALUE_SOURCE_SCHEMATIC: "schematic's own value field",
    VALUE_SOURCE_SHELF: "shelf entry this part's MPN / C-number resolves to",
    VALUE_SOURCE_MPN: "EIA value code inside its MPN",
}


def value_source_label(source: str) -> str:
    """Describe a value's recovery route without calling it a declaration."""
    return _VALUE_SOURCE_LABELS.get(
        str(source or ""), "part's own identity (an unrecorded recovery route)"
    )


@dataclass(frozen=True)
class CapCandidate:
    """The four identity fields a decision needs, plus ground/value evidence."""

    designator: str
    value: str = ""
    mpn: str = ""
    lcsc: str = ""
    footprint: str = ""
    grounded: bool = False
    value_source: str = ""


def looks_like_capacitor(
    designator: str,
    value: str,
    mpn: str,
    lcsc: str,
    library=None,
    *,
    footprint: str = "",
    name: str = "",
) -> bool:
    """Read capacitor identity from value, shelf declaration or C+shape evidence."""
    if parse_capacitance_farads(value or "") is not None:
        return True
    from .parts import resolve_facts

    if library is None:
        return bool(
            _CAP_DESIGNATOR.match(designator or "")
            and (
                mpn_value_code(mpn or "")
                or _CHIP_SIZE_FOOTPRINT.match((footprint or "").strip())
            )
        )
    entry, _matched = resolve_facts(library, mpn=mpn, lcsc=lcsc, name=name)
    if declared_category(entry, allow_machine=True) == "capacitor":
        return True
    if _CAP_DESIGNATOR.match(designator or "") and mpn_value_code(mpn or ""):
        return True
    if _CAP_DESIGNATOR.match(designator or "") and _CHIP_SIZE_FOOTPRINT.match(
        (footprint or "").strip()
    ):
        return True
    return False


def component_looks_like_capacitor(comp: Component, library) -> bool:
    """``looks_like_capacitor`` for a parsed Component, preserving device_name."""
    return looks_like_capacitor(
        comp.designator,
        comp.value or "",
        comp.mpn or "",
        comp.lcsc_part or "",
        library,
        footprint=comp.footprint or "",
        name=str(comp.props.get("device_name") or ""),
    )


def gated_capacitor(comp: Component, library) -> bool:
    """Whether the shelf names a capacitor only at a tier the rule cannot read."""
    if library is None:
        return False
    from .parts import resolve_facts

    entry, _matched = resolve_facts(
        library,
        mpn=comp.mpn or "",
        lcsc=comp.lcsc_part or "",
        name=str(comp.props.get("device_name") or ""),
    )
    return (
        category_verdict(entry, _CAPACITOR_CATEGORIES, allow_machine=True)
        == CATEGORY_GATED
    )


def candidate_farads(candidate: CapCandidate, library=None) -> float | None:
    """Read board value first, then a guarded MPN EIA code."""
    from_board = parse_capacitance_farads(candidate.value or "")
    if from_board is not None:
        return from_board
    if not looks_like_capacitor(
        candidate.designator,
        candidate.value,
        candidate.mpn,
        candidate.lcsc,
        library,
        footprint=candidate.footprint,
    ):
        return None
    code = mpn_value_code(candidate.mpn or "")
    if code is not None:
        return decode_eia_3digit(code, 1e-12)
    return None


def capacitance_text(farads: float) -> str:
    """Format a recovered capacitance so it round-trips through the value parser."""
    for suffix, scale in (("F", 1.0), ("mF", 1e-3), ("uF", 1e-6), ("nF", 1e-9)):
        if farads >= scale:
            return f"{farads / scale:g}{suffix}"
    return f"{farads / 1e-12:g}pF"


def recovered_capacitance(
    designator: str,
    mpn: str,
    lcsc: str,
    library=None,
    *,
    footprint: str = "",
) -> tuple[str, str]:
    """Recover ``(value text, source)`` from shelf, then a guarded MPN code."""
    if library is not None:
        from .parts import resolve_facts

        entry, _matched = resolve_facts(library, mpn=mpn or None, lcsc=lcsc or None)
        if entry is not None and entry.value:
            if parse_capacitance_farads(entry.value) is not None:
                return entry.value, VALUE_SOURCE_SHELF
    if not looks_like_capacitor(
        designator, "", mpn, lcsc, library, footprint=footprint
    ):
        return "", ""
    code = mpn_value_code(mpn or "")
    if code is None:
        return "", ""
    farads = decode_eia_3digit(code, 1e-12)
    if farads is None:
        return "", ""
    return capacitance_text(farads), VALUE_SOURCE_MPN


def recovered_farads(candidate: object) -> float | None:
    """Read only a value recovered by shelf/MPN, never a schematic declaration."""
    if str(getattr(candidate, "value_source", "") or "") not in VALUE_SOURCES_RECOVERED:
        return None
    return parse_capacitance_farads(str(getattr(candidate, "value", "") or ""))


@dataclass(frozen=True)
class CapDecision:
    """The single comparison result shared by the rule and apply's probe."""

    state: str
    required_farads: float | None = None
    required_text: str = ""
    cap_designator: str = ""
    cap_farads: float | None = None

    @property
    def satisfied(self) -> bool:
        return self.state == "satisfied"


def decide_required_cap(
    declared_text: str,
    candidates: Sequence[CapCandidate],
    library=None,
) -> CapDecision:
    """Compare one required capacitance with an inventory, preserving old semantics."""
    required = parse_capacitance_farads(str(declared_text or ""))
    if required is None:
        return CapDecision("unparseable", required_text=str(declared_text or ""))
    best: tuple[CapCandidate, float] | None = None
    unreadable: CapCandidate | None = None
    for candidate in candidates:
        farads = candidate_farads(candidate, library)
        if farads is None:
            unreadable = unreadable or candidate
            continue
        if best is None or farads > best[1]:
            best = (candidate, farads)
    if best is None:
        if unreadable is not None:
            return CapDecision(
                "unreadable",
                required_farads=required,
                required_text=str(declared_text or ""),
                cap_designator=unreadable.designator,
            )
        return CapDecision(
            "missing", required_farads=required, required_text=str(declared_text or "")
        )
    candidate, farads = best
    return CapDecision(
        "satisfied" if farads + 1e-12 >= required else "too_small",
        required_farads=required,
        required_text=str(declared_text or ""),
        cap_designator=candidate.designator,
        cap_farads=farads,
    )


def bridges_to_ground(comp: Component, net_name: str) -> bool:
    """Whether the other terminal reaches a different ground net."""
    others = {
        pin.net for pin in comp.pins if pin.net is not None and pin.net != net_name
    }
    return any(is_ground_net(name) for name in others)


def cap_candidates_on(model: DesignModel, net_name: str, library=None) -> list[CapCandidate]:
    """Inventory grounded candidates on a net, including unreadable gated parts."""
    net = model.nets.get(net_name)
    if net is None:
        return []
    found: list[CapCandidate] = []
    for designator, _pin in net.pins:
        other = model.components.get(designator)
        if other is None:
            continue
        if not component_looks_like_capacitor(other, library) and not gated_capacitor(
            other, library
        ):
            continue
        if not bridges_to_ground(other, net_name):
            continue
        declared = str(other.value or "")
        source = (
            VALUE_SOURCE_SCHEMATIC
            if parse_capacitance_farads(declared) is not None
            else ""
        )
        if not declared.strip():
            recovered, source = recovered_capacitance(
                other.designator,
                str(other.mpn or ""),
                str(other.lcsc_part or ""),
                library,
                footprint=str(other.footprint or ""),
            )
            if recovered:
                declared = recovered
        found.append(
            CapCandidate(
                designator=other.designator,
                value=declared,
                mpn=other.mpn or "",
                lcsc=other.lcsc_part or "",
                footprint=other.footprint or "",
                grounded=True,
                value_source=source,
            )
        )
    return found
