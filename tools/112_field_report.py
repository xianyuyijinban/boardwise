#!/usr/bin/env python3
"""The synthetic-field before/after table for 112 (task book §交付纪律 5).

Prints, for one fixed synthetic page, what the old straight/L path drew and what
the obstacle search draws instead: point count, bend count, body-crossing count
and foreign-wire-crossing count. Offline, pure, no bridge.

    .venv/Scripts/python.exe tools/112_field_report.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.engines import addcomponent  # noqa: E402
from boardwise.engines.router import segment_hits_box  # noqa: E402

BODY = (-5.0, -5.0, 5.0, 5.0)
FOREIGN = (0.0, -60.0, 0.0, 60.0)  # another net's vertical run at x = 0


def _crossings(points, edge):
    """How many times the polyline crosses `edge` through both interiors.

    A proper crossing, stated independently of the router: the two segments meet
    at a point that is strictly interior to **both**. A shared endpoint, a tee
    and a collinear overlap are all something else, and each of them is a
    different (worse) thing than a crossing.
    """
    ax, ay, bx, by = edge
    n = 0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        # Sample the intersection of the two segments directly.
        if abs(y0 - y1) < 1e-9 and abs(ay - by) > 1e-9:
            # the polyline's segment is horizontal, the edge is vertical
            y = y0
            if min(ay, by) < y < max(ay, by) and min(x0, x1) < ax < max(x0, x1):
                n += 1
        if abs(x0 - x1) < 1e-9 and abs(ax - bx) > 1e-9:
            x = x0
            if min(ax, bx) < x < max(ax, bx) and min(y0, y1) < ay < max(y0, y1):
                n += 1
    return n


def _metrics(points, body, has_edge):
    points = [tuple(p) for p in points]
    bends = sum(
        1 for i in range(1, len(points) - 1)
        if not (
            abs(points[i][0] - points[i - 1][0]) < 1e-9
            and abs(points[i][0] - points[i + 1][0]) < 1e-9
        )
    )
    length = sum(
        abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(points, points[1:])
    )
    return {
        "points": len(points),
        "bends": bends,
        "length": length,
        "cuts_body": sum(
            1 for a, b in zip(points, points[1:]) if segment_hits_box(a, b, body)
        ) if body is not None else 0,
        "crosses_foreign": _crossings(points, FOREIGN) if has_edge else 0,
    }


CASES = [
    ("a body between two points", (-20.0, 0.0), (20.0, 0.0),
     addcomponent.ObstacleField(boxes=(BODY,)), BODY, False),
    ("a foreign run between two points", (-20.0, 0.0), (20.0, 0.0),
     addcomponent.ObstacleField(edges=(FOREIGN,)), None, True),
    ("both", (-20.0, 0.0), (20.0, 0.0),
     addcomponent.ObstacleField(boxes=(BODY,), edges=(FOREIGN,)), BODY, True),
    ("a body and a second body up the lane", (-20.0, 0.0), (20.0, 0.0),
     addcomponent.ObstacleField(boxes=(BODY, (-2.0, 20.0, 2.0, 80.0))), BODY, False),
    ("nothing in the way", (-20.0, -5.0), (5.0, 0.0),
     addcomponent.ObstacleField(), None, False),
]

HEADER = (
    "case                        | path        | pts bends len cuts crosses",
    "----------------------------+-------------+---------------------------",
)


def main() -> int:
    print("== 112 synthetic field: the old straight/L vs the obstacle search ==")
    print(f"body  = {BODY}")
    print(f"other = {FOREIGN}  (another net's run)")
    print()
    print("case                        | path        | pts bends len cuts crosses")
    print("-" * 27 + "+" + "-" * 13 + "+" + "-" * 27)
    for name, anchor, target, field, body, has_edge in CASES:
        before = addcomponent.wire_route(anchor, target)
        after = addcomponent.wire_route(anchor, target, avoid=field)
        for label, points in (("old (L)", before), ("new (search)", after)):
            if points is None:
                print(f"{name:<27} | {label:<12} | None — 无净通路")
                continue
            m = _metrics(points, body, has_edge)
            print(
                f"{name:<27} | {label:<12} | "
                f"{m['points']:>3} {m['bends']:>5} {m['length']:>4.0f} "
                f"{m['cuts_body']:>5} {m['crosses_foreign']:>7}"
            )
        print(f"{'':<27} | {'':<12} | {after if after else ''}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
