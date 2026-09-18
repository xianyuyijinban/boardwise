"""Golden corrections that live *beside* the fixture, never inside it.

`tests/fixtures/ch340_golden.epro2` is evidence, and §G.3 of the task book is
explicit that it must not be edited — even where it is *known to be wrong*.
U3 is the case that forced this: the golden says `1kΩ` and 岳翔宇 confirmed on
2026-09-15 that this was his own mistake all those years ago (the correct value
is 2.2kΩ 0805), while the library device the golden names, `FRC0805J471 TS`,
is 470Ω and therefore wrong too.

So corrections go into a sidecar, `<fixture stem>.overrides.json`, which both
the draw plan and the comparison load. Every entry carries a `provenance`
string, and every hit is printed — the report must show *why* a value differs
from the fixture, or an override would be indistinguishable from a fudge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .model import DesignModel

#: Fields an override may touch. Deliberately narrow: value, the identity of
#: the device to place (lcsc / explicit uuid pair), and the package the
#: placement must prove it has.
OVERRIDABLE = (
    "value",
    "lcsc",
    # `place_*` on purpose: the golden's own `device_uuid` prop is a
    # *file-local* document uuid ("not found in the library", measured), so a
    # placeable pair needs its own keys rather than shadowing that one.
    "place_device_uuid",
    "place_library_uuid",
    "expect_footprint",
)


def sidecar_path_for(golden: str | Path) -> Path:
    """`ch340_golden.epro2` -> `ch340_golden.overrides.json` (same directory)."""
    path = Path(golden)
    return path.parent / f"{path.stem}.overrides.json"


@dataclass
class Override:
    """One designator's corrections, with the reason they exist."""

    designator: str
    fields: dict[str, str] = field(default_factory=dict)
    provenance: str = ""

    def render(self) -> str:
        pairs = ", ".join(f"{k}={v}" for k, v in sorted(self.fields.items()))
        return f"{self.designator}: {pairs} — {self.provenance or '(no provenance given)'}"


@dataclass
class AppliedOverrides:
    """What the sidecar said, and how much of it was used."""

    path: str = ""
    items: list[Override] = field(default_factory=list)
    #: Designators the sidecar named that the golden model does not contain.
    unknown: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return bool(self.items)

    def lines(self) -> list[str]:
        return [item.render() for item in self.items]


def load_overrides(path: str | Path) -> AppliedOverrides:
    """Read the sidecar. Missing file is not an error — most boards have none."""
    file = Path(path)
    if not file.is_file():
        return AppliedOverrides()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{file}: overrides sidecar is not readable JSON: {exc}") from exc

    applied = AppliedOverrides(path=str(file))
    components = raw.get("components") or {}
    if not isinstance(components, dict):
        raise ValueError(f"{file}: 'components' must be an object")
    for designator, body in components.items():
        if not isinstance(body, dict):
            raise ValueError(f"{file}: component {designator} must be an object")
        fields = {k: str(body[k]) for k in OVERRIDABLE if body.get(k) not in (None, "")}
        applied.items.append(
            Override(
                designator=str(designator),
                fields=fields,
                provenance=str(body.get("provenance") or "").strip(),
            )
        )
    return applied


def apply_overrides(model: DesignModel, applied: AppliedOverrides) -> list[str]:
    """Write the sidecar into the model in place. Returns per-hit report lines.

    Applied to the *golden* model, which is also the comparison baseline — so
    the diff afterwards compares the drawn board against the corrected truth,
    not against a value everyone agrees is wrong.
    """
    lines: list[str] = []
    for item in applied.items:
        component = model.components.get(item.designator)
        if component is None:
            applied.unknown.append(item.designator)
            continue
        before: dict[str, str] = {}
        for key, value in item.fields.items():
            if key == "value":
                before[key] = component.value
                component.value = value
            elif key == "lcsc":
                before[key] = component.lcsc_part
                component.lcsc_part = value
            else:
                before[key] = str(component.props.get(key, ""))
                component.props[key] = value
        changes = ", ".join(
            f"{k}: 黄金 {before.get(k) or '(空)'} → {v}" for k, v in sorted(item.fields.items())
        )
        lines.append(
            f"{item.designator}  {changes}"
            + (f"  [{item.provenance}]" if item.provenance else "  [(no provenance given)]")
        )
    return lines
