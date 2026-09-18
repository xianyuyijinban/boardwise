"""P4 quantified bug list: replay the 2026-09-13 21:51 v1 draw offline.

The v1 flow (before revision 3) placed components on a naive grid
(origin (0,0), pitch 150, 4 per row — the CLI args of that run), computed
pin positions by adding FILE-space offsets to canvas y (the sign bug), and
wired signal nets with straight L-shapes from an anchor pin while power
nets got floating flags with no wires at all.

This replay reconstructs exactly that geometry deterministically and runs
the revision-3 validator over it, feeding the *true* canvas pin tips —
which is how the sign bug becomes counted violations instead of a vibe.
The result is the quantified bug list for the drawn P4 page.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.core.model import DesignModel  # noqa: E402
from boardwise.engines import layout  # noqa: E402
from boardwise.engines.generate import (  # noqa: E402
    _is_power_net,
    _layout_order,
)
from boardwise.engines.layout import Placement, RoutedNet  # noqa: E402
from boardwise.parsers.schematic import (  # noqa: E402
    build_pin_offsets,
    build_schematic_model,
)

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ch340_golden.epro2"

V1_ORIGIN = (0.0, 0.0)
V1_PITCH = 150.0
V1_PER_ROW = 4
V1_JUNCTION_DROP = 40.0


def replay_v1(model: DesignModel, file_offsets: dict):
    """Rebuild the v1 geometry: returns (placements, routes, true_tips)."""
    _host, order = _layout_order(model)

    # --- v1 placements: naive grid, exactly as generate_plan v1 did
    v1_pos: dict[str, tuple[float, float]] = {}
    for index, designator in enumerate(order):
        col = index % V1_PER_ROW
        row = index // V1_PER_ROW
        v1_pos[designator] = (
            V1_ORIGIN[0] + col * V1_PITCH,
            V1_ORIGIN[1] + row * V1_PITCH,
        )

    placements = [
        Placement(
            designator,
            v1_pos[designator][0],
            v1_pos[designator][1],
            layout.component_bbox(v1_pos[designator][0], v1_pos[designator][1],
                                  file_offsets.get(designator, {})),
        )
        for designator in order
    ]

    # --- v1 pin positions: FILE offsets added to canvas y (the sign bug)
    v1_pins = {
        (des, number): (x + dx, y + dy)
        for des, (x, y) in v1_pos.items()
        for number, (dx, dy) in file_offsets.get(des, {}).items()
    }
    # the TRUE canvas tips: canvas y negates the file offset's y
    true_tips = {
        (des, number): (x + dx, y - dy)
        for des, (x, y) in v1_pos.items()
        for number, (dx, dy) in file_offsets.get(des, {}).items()
    }

    # --- v1 wiring: straight L per member from the anchor; power = flags only
    routes: list[RoutedNet] = []
    for name in sorted(model.nets):
        net = model.nets[name]
        members = list(net.pins)
        if not members:
            continue
        if _is_power_net(name):
            kind = "Ground" if name.upper().startswith("GND") else "Power"
            for des, pin in members:
                x, y = v1_pins[(des, pin)]
                routes.append(RoutedNet(net=name, polylines=[], attach=(x, y), kind=kind))
            continue
        anchor = members[0]
        ax, ay = v1_pins[anchor]
        routes.append(
            RoutedNet(net=name, polylines=[], attach=(ax, ay - V1_JUNCTION_DROP), kind="port")
        )
        for des, pin in members[1:]:
            bx, by = v1_pins[(des, pin)]
            points = [(ax, ay)]
            if abs(bx - ax) > 1e-6:
                points.append((bx, ay))
            if abs(by - ay) > 1e-6:
                points.append((bx, by))
            if len(points) == 1:
                points.append((bx, by))
            routes.append(RoutedNet(net=name, polylines=[points], attach=None, kind="wire"))
    return placements, routes, true_tips


def main() -> int:
    golden = build_schematic_model(GOLDEN)
    file_offsets = build_pin_offsets(GOLDEN)
    placements, routes, true_tips = replay_v1(golden, file_offsets)
    violations = layout.validate_full(golden, placements, routes, true_tips)
    # dedupe identical findings (a repeated segment pair reads as one defect)
    seen: set[tuple[str, str, str]] = set()
    unique: list[layout.Violation] = []
    for v in violations:
        key = (v.code, v.subject, v.detail)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    violations = unique

    from collections import Counter

    counts = Counter(v.code for v in violations)
    print(f"P4 v1 replay: {len(placements)} placements, {len(routes)} route steps")
    print(f"violations: {len(violations)} total")
    for code, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {code:26} {count}")
    print()
    by_code: dict[str, list] = {}
    for v in violations:
        by_code.setdefault(v.code, []).append(v)
    for code, items in sorted(by_code.items()):
        print(f"--- {code} ({len(items)}) ---")
        for v in items[:6]:
            print(f"  {v.render()[:150]}")
        if len(items) > 6:
            print(f"  … and {len(items) - 6} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
