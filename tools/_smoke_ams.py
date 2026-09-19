"""Probe: the signed AMS1117 block assembles, and what the page looks like.

Reads the committed smoke spec (`blocklib/specs/ams1117_smoke.json`) rather than
building one inline, so the thing a human looks at on the canvas and the thing
this prints are the same input. Offline: this is the read-back for the real-host
smoke, not a substitute for it.

The three claims worth checking here are the ruling's:

* a block assembles at all, and by the path its own geometry decides: this one
  carries wires and flags now (task 010), so nothing is synthesised and the
  flag count is the template's rather than one per pin endpoint;
* which of the two anchor paths was taken is read off the design and printed
  rather than assumed, because that is the thing this probe exists to show;
* the same input assembles byte-identically twice.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.core.blocks import load_board_spec
from boardwise.engines.assemble import assemble

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "blocklib" / "specs" / "ams1117_smoke.json"


def _snapshot(design) -> str:
    """The page as a comparable string — the idempotence witness."""
    return json.dumps(
        {
            "parts": [(p.designator, p.x, p.y, p.rotation) for p in design.page.parts],
            "flags": [(f.net, f.kind, f.x, f.y) for f in design.page.flags],
            "labels": [(l.net, l.x, l.y) for l in design.page.labels],
            "wires": [(w.group, w.net, w.points) for w in design.page.wires],
            "ports": [(p.block, p.role, p.position) for p in design.ports],
        },
        sort_keys=True,
    )


def main() -> int:
    spec = load_board_spec(SPEC)
    design = assemble(spec)
    print(f"spec: {spec.name!r}, {len(spec.blocks)} block(s)")

    print(f"\nparts ({len(design.model.components)}):")
    for comp in sorted(design.model.components.values(), key=lambda c: c.designator):
        print(f"  {comp.designator:5s} {comp.lcsc_part or '<unbound>':10s} {comp.footprint or '-'}")

    synthesised = [line for line in design.report if "synthesised" in line]
    print(f"\nanchors: {len(design.page.flags)} flag(s), "
          f"{len(design.page.labels)} label(s), {len(design.page.wires)} wire run(s)"
          f" — {'synthesised' if synthesised else 'from the template geometry'}")
    for flag in sorted(design.page.flags, key=lambda f: (f.net, f.y, f.x)):
        print(f"  flag  {flag.net:5s} {flag.kind:7s} at ({flag.x:.0f}, {flag.y:.0f})")
    for label in sorted(design.page.labels, key=lambda l: (l.net, l.y, l.x)):
        print(f"  label {label.net:5s} at ({label.x:.0f}, {label.y:.0f})")

    print("\nports (anchor = the flag/label the port doubles as):")
    for port in design.ports:
        print(f"  {port.block}.{port.role:5s} {port.net_class:6s} at "
              f"({port.position[0]:.0f}, {port.position[1]:.0f})")

    print("\nnets:")
    for net in sorted(design.model.nets):
        pins = sorted(
            f"{des}.{pin.number}"
            for des, comp in design.model.components.items()
            for pin in comp.pins
            if pin.net == net
        )
        print(f"  {net:5s} {', '.join(pins)}")

    if design.notes:
        print("\nnotes:")
        for note in design.notes:
            print(f"  - {note}")

    again = assemble(load_board_spec(SPEC))
    same = _snapshot(design) == _snapshot(again)
    print(f"\nidempotent (same input, same page): {same}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
