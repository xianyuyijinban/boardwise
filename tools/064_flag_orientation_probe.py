#!/usr/bin/env python3
"""064 live probe: place the flag poses, then read back what the editor drew.

    # 1. on the `test` project, after `boardwise bridge status` + `doc.list`对焦:
    .venv/Scripts/python.exe -m boardwise.cli bridge call --action sch.doc.new \\
        --params '{"name":"064_railflag_probe","confirm":true}' --yes --project test
    .venv/Scripts/python.exe tools/064_flag_orientation_probe.py place <pageUuid> DIR
    .venv/Scripts/python.exe -m boardwise.cli bridge call --action export.render \\
        --params '{"format":"svg","scope":"page","pageUuid":"<pageUuid>"}' --project test > DIR/render.json

    # 2. read the picture back (offline, no editor):
    .venv/Scripts/python.exe tools/064_flag_orientation_probe.py read DIR/render.json DIR/out.txt

    # 3. clean up: `sch.delete_primitives` with the uuids `place` printed, then
    #    `sch.doc.save`.

064 sec.2 makes this probe the only thing that can settle the compass: the
library hangs a **ground** flag's bars below its connection and a **rail** flag's
bar above it, and every flag profile this repo ships states the same *convention*
box, so the offline preview draws the two families identically. `place` puts one
of each family at all four rotations on a scratch page of the `test` project;
`read` pairs each rendered `c_partid="netflag"` group with the placement it was
asked for, reads which way its glyph extends, and checks the answer against
`drawcompiler.flag_rotation` — the production compass — so the live picture and
the compiler are compared number for number.

The rotations `place` hands `sch.place_power` are the **API's**, which is the
negation of a plan's (``cli.py``: ``editor_pose(flag.rotation, False)``; the
file's angle and the API's are opposite by construction — pit 11). `read` says
so on every line: a row's plan rotation is ``(-api rotation) % 360``.

Live discipline: write only to the named test project, after identity checks
(SKILL.md §4 R1); `place` always sends `pageUuid`, so a focus that moved is
refused rather than written to. Nothing here runs the editor by itself — it is
invoked by hand, the way the runbook does it.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from boardwise.engines import drawcompiler as dc  # noqa: E402

#: ``(kind, family, net, x, y, rotation handed to the API)`` — 100 units apart,
#: far more than one glyph is wide, so no two flags can be confused.
PLACED = (
    ("Power", "rail", "3V3", 200.0, 600.0, 0.0),
    ("Power", "rail", "3V3", 300.0, 600.0, 90.0),
    ("Power", "rail", "3V3", 400.0, 600.0, 180.0),
    ("Power", "rail", "3V3", 500.0, 600.0, 270.0),
    ("Ground", "gnd", "GND", 200.0, 400.0, 0.0),
    ("Ground", "gnd", "GND", 300.0, 400.0, 90.0),
    ("Ground", "gnd", "GND", 400.0, 400.0, 180.0),
    ("Ground", "gnd", "GND", 500.0, 400.0, 270.0),
)

DIRECTIONS = ((0.0, 1.0), (-1.0, 0.0), (0.0, -1.0), (1.0, 0.0))
NAMES = {(0.0, 1.0): "UP", (-1.0, 0.0): "LEFT", (0.0, -1.0): "DOWN", (1.0, 0.0): "RIGHT"}

_POINT = re.compile(r"(-?\d+(?:\.\d+)?)")

CLI = [str(ROOT / ".venv/Scripts/python.exe"), "-m", "boardwise.cli", "bridge", "call"]


def _call(action: str, params: dict, project: str) -> tuple[int, str]:
    done = subprocess.run(
        [*CLI, "--action", action, "--params", json.dumps(params),
         "--project", project],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def place(argv: list[str]) -> int:
    """Place the eight flags and write every response verbatim to ``DIR``."""
    page, out_dir = argv[0], Path(argv[1])
    project = argv[2] if len(argv) > 2 else "test"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, (kind, family, net, x, y, rotation) in enumerate(PLACED):
        params = {
            "kind": kind, "net": net, "x": x, "y": y, "rotation": rotation,
            "mirror": False, "pageUuid": page,
        }
        code, text = _call("sch.place_power", params, project)
        name = f"02_place_{index + 1}_{kind}_{rotation:g}.json"
        (out_dir / name).write_text(text, encoding="utf-8")
        rows.append({**params, "family": family, "exit": code,
                     "response": text.strip()})
        sys.stdout.write(
            f"{kind:6s} {net:4s} api rot {rotation:5.1f} at ({x:g},{y:g})"
            f" exit {code}  {text.strip()}\n"
        )
    (out_dir / "02_place_summary.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
    )
    return 0 if all(row["exit"] == 0 for row in rows) else 1


def _points(text: str) -> list[tuple[float, float]]:
    numbers = [float(item) for item in _POINT.findall(text or "")]
    return list(zip(numbers[0::2], numbers[1::2]))


def _glyph(group: ElementTree.Element) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """``(glyph points, the connection)`` for one netflag group, in canvas terms.

    The group holds the symbol's own pin in a ``part_pin`` child (its ``M x y`` is
    the connection) and the drawn glyph beside it — a bar for a rail, shrinking
    bars for a ground. The ``part_attr`` text is the net name, not geometry.
    """
    points: list[tuple[float, float]] = []
    connection: tuple[float, float] | None = None
    for node in list(group):
        if node.get("c_partid") == "part_pin":
            for child in node.iter():
                if child.get("d"):
                    numbers = _POINT.findall(child.get("d") or "")
                    if len(numbers) >= 2:
                        connection = (float(numbers[0]), -float(numbers[1]))
                    break
            continue
        if node.tag.endswith("text"):
            continue
        for attribute in ("points", "x1", "x2", "y1", "y2"):
            value = node.get(attribute)
            if value:
                points.extend(_points(value))
        if node.get("d"):
            points.extend(_points(node.get("d")))
    return [(x, -y) for x, y in points], connection or (0.0, 0.0)


def _direction(connection: tuple[float, float], points: list[tuple[float, float]]) -> str:
    """Which way the glyph extends from the connection, in **canvas** terms."""
    if not points:
        return "no glyph"
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    centre = (sum(xs) / len(xs), sum(ys) / len(ys))
    dx = centre[0] - connection[0]
    dy = centre[1] - connection[1]
    if abs(dx) >= abs(dy):
        return "RIGHT" if dx > 0 else "LEFT"
    return "UP" if dy > 0 else "DOWN"


def _expected(plan_rotation: float, family: str) -> str:
    """The direction the compass encodes as this plan rotation — its own answer."""
    for direction in DIRECTIONS:
        if dc.flag_rotation(direction, family) == plan_rotation:
            return NAMES[direction]
    raise SystemExit(f"no direction maps to plan rotation {plan_rotation!r}")


def read(argv: list[str]) -> int:
    """Read a rendered page back and check every flag against the compass."""
    payload = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    data = payload["data"]
    svg = (
        base64.b64decode(data).decode("utf-8")
        if payload.get("encoding") == "base64" else data
    )
    Path(argv[0]).with_suffix(".svg").write_text(svg, encoding="utf-8")
    root = ElementTree.fromstring(svg)
    groups = [node for node in root.iter() if node.get("c_partid") == "netflag"]

    lines = [
        "064 live probe: which way the editor draws each flag's glyph, per family",
        "=" * 100,
        f"page {payload.get('activatedPageUuid')}: {len(groups)} netflag group(s) in"
        f" the render, {len(PLACED)} flag(s) placed by this probe",
        "the plan rotation a row speaks for is (-api rotation) % 360 — `draw apply`",
        "hands `sch.place_power` the negated plan rotation (cli.py: editor_pose(...))",
        "-" * 100,
    ]
    failures = 0
    used: set[int] = set()
    for kind, family, net, x, y, api_rotation in PLACED:
        plan_rotation = (-api_rotation) % 360.0
        best: tuple[float, int, list[tuple[float, float]], tuple[float, float]] | None = None
        for index, group in enumerate(groups):
            if index in used:
                continue
            points, connection = _glyph(group)
            distance = abs(connection[0] - x) + abs(connection[1] - y)
            if best is None or distance < best[0]:
                best = (distance, index, points, connection)
        head = (
            f"{kind:6s} {net:4s} api rot {api_rotation:5.1f}"
            f" (= plan rot {plan_rotation:5.1f}) at ({x:g},{y:g})"
        )
        if best is None:
            lines.append(head + "  -> no netflag group found")
            failures += 1
            continue
        _distance, index, points, connection = best
        used.add(index)
        if abs(connection[0] - x) + abs(connection[1] - y) > 1e-6:
            lines.append(
                head + f"  -> nearest flag connects at ({connection[0]:g},"
                f"{connection[1]:g}) — NOT this placement"
            )
            failures += 1
            continue
        way = _direction(connection, points)
        want = _expected(plan_rotation, family)
        if way != want:
            failures += 1
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        lines.append(
            f"{head}  -> glyph {way:5s} (expect {want:5s}) "
            f"{'PASS' if way == want else 'FAIL'}"
            f"   canvas bbox x {min(xs):g}..{max(xs):g} y {min(ys):g}..{max(ys):g}"
        )
    lines.append("-" * 100)
    lines.append(
        f"{len(PLACED) - failures}/{len(PLACED)} pose(s) agree with the compass"
        + ("" if not failures else f" — {failures} DISAGREE")
    )
    lines.append(
        "the two families' natural poses, read off the picture: rail (Power-*) hangs"
    )
    lines.append(
        "its bar ABOVE the connection at plan rotation 0, ground (Ground-*) its bars"
    )
    lines.append("BELOW — 180 apart, which is why one compass cannot serve both.")
    text = "\n".join(lines) + "\n"
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.stdout.write(__doc__ or "")
        return 2
    if argv[1] == "place":
        return place(argv[2:])
    if argv[1] == "read":
        return read(argv[2:])
    sys.stdout.write(f"unknown mode {argv[1]!r}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
