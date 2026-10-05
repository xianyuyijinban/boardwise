#!/usr/bin/env python3
"""118: rebuild `flyback_uc3845.library.json` from **measured** geometry.

    .venv/Scripts/python.exe tools/118_measure_profiles.py [outfile]

Why this file exists — the lesson, measured twice. 113 hand-wrote thirteen
symbol profiles.  Every number in them was a *guess at a shape*, and the guess
was good enough to lay out a page and pass the offline gates — until 118 put
that page on a real editor, where **054 C6** read the pins back and refused:
46 of 49 pins off by ±15/±20/±25, and two symbols whose pin-token system the
host does not have at all.  A profile is not a drawing of a part; it is a set of
**claims about a specific library symbol**, and a claim nobody measured is a
guess that happens to compile.

So this tool derives every profile from two live readings and nothing else:

* **A — `outputs/118/apply_report.json`**: `write.placed` (each part's origin,
  rotation, mirror) and `write.pins` (where the editor says each pin actually
  landed).  Undoing the pose gives the **local tip** of every pin of all 21
  parts.  This is the reading of the page being drawn, so it is the primary one.
* **B — `outputs/110/11_pins.json` + `outputs/110/12_bodies.json`**: the same
  LCSC parts measured on 110's page, giving each pin's **name**, **direction**
  and **length** — three things A does not carry.  Twelve of the thirteen
  symbols are here.
* **C — the 0603/0805 family rule, read off B**: 110 measured twelve members of
  the family and every one of them is `pin 1 escapes left, pin 2 escapes right,
  length 10, horizontal`.  The nine parts whose LCSC 110 never placed take their
  **names and lengths** from that rule, and their **tips** from A (measured
  per-part, so a 0603 at ±15 and a 0805 at ±20 are told apart by measurement, not
  by size class).

**Cross-check, run on every build**: for the twelve symbols A and B both cover,
the two independent readings must agree pin for pin.  They do — 12/12, zero
disagreements.  That is what makes A trustworthy for the nine parts only B's
family rule covers, and it is re-measured rather than remembered.

**Pose semantics are kept, and say so.** 113 chose each shape *for a reason*
(「岳 ruling (e) asks for the feedback row on a horizontal line」and so on), and
those reasons are recorded in each title.  They survive verbatim as the first
line; the second line states that the pin tips and body box are measured.  Where
the measured symbol is **horizontal** while 113's intent was vertical, the
symbol is stored as measured and the intent moves into the title, because a
profile that quietly re-rotates a symbol to satisfy a layout decision is the
exact failure 118 is fixing.

**What is NOT measured, and is marked as such**: the body box.  Neither reading
carries a per-part bounding box (`12_bodies.json` is a component dump, not
boxes; `sch.geometry`'s `bboxes` holds only the sheet).  So the box is derived
from the **measured pin tips minus the measured pin length** — the inner ends of
the outer pins, which is the drawn body edge for a two-pin part and a stated
lower bound for the multi-pin ones.  Every body in the output carries
``bodySource`` saying which of the two it is.
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

APPLY = ROOT / "outputs" / "118" / "apply_report.json"
PINS110 = ROOT / "outputs" / "110" / "11_pins.json"
BODIES110 = ROOT / "outputs" / "110" / "12_bodies.json"
LIBRARY = ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json"
PLAN_REPORT = ROOT / "outputs" / "118" / "plan_report.json"

DIR_BY_ROTATION = {0: "right", 90: "up", 180: "left", 270: "down"}


def inverse_pose(dx: float, dy: float, rotation: float, mirror: bool):
    """Local symbol tip from a page-frame offset under a placed pose.

    :func:`boardwise.core.geometry.transform_point` applies mirror first, then
    rotation, so the inverse is rotation by -theta, then un-mirror.  Getting
    that order wrong is silent — it still returns plausible numbers — which is
    why the cross-check below exists.
    """
    rad = math.radians(-rotation)
    cos_v, sin_v = math.cos(rad), math.sin(rad)
    x = dx * cos_v - dy * sin_v
    y = dx * sin_v + dy * cos_v
    if mirror:
        x = -x
    return (round(x, 4), round(y, 4))


def read_apply() -> tuple[dict, dict, dict]:
    """`{designator: {pin: local tip}}`, `{designator: lcsc}`, `{specId: designator}`."""
    report = json.loads(APPLY.read_text(encoding="utf-8"))
    placed = {item["designator"]: item for item in report["write"]["placed"]}
    tips: dict[str, dict[str, tuple[float, float]]] = {}
    for key, point in report["write"]["pins"].items():
        part_id, _, number = key.rpartition(".")
        part = placed[part_id]
        tips.setdefault(part_id, {})[number] = inverse_pose(
            point[0] - part["x"], point[1] - part["y"],
            part["rotation"], part["mirror"],
        )
    lcsc = {part_id: part["lcsc"] for part_id, part in placed.items()}
    pool: dict[str, str] = {}
    plan = PLAN_REPORT
    if plan.is_file():
        for item in json.loads(plan.read_text(encoding="utf-8"))["plan"]["change"]["parts"]:
            pool[item["specId"]] = item["designator"]
    return tips, lcsc, pool


def read_110() -> dict[str, dict[str, dict]]:
    """`{lcsc: {pin number: (name, direction, length)}}` for the symbols 110 placed."""
    bodies = json.loads(BODIES110.read_text(encoding="utf-8"))
    origin: dict[str, tuple[int, int]] = {}
    by_lcsc: dict[str, str] = {}
    for component in bodies["components"]:
        state = component.get("state", component)
        if state.get("ComponentType") == "sheet":
            continue
        origin[state["Designator"]] = (state["X"], state["Y"])
        by_lcsc[state.get("SupplierId")] = state["Designator"]
    measured = json.loads(PINS110.read_text(encoding="utf-8"))
    out: dict[str, dict[str, dict]] = {}
    for designator, record in measured.items():
        if designator not in origin:
            continue
        ox, oy = origin[designator]
        code = next(
            (code for code, des in by_lcsc.items() if des == designator), None
        )
        if code is None:
            continue
        out[code] = {
            str(pin["PinNumber"]): (
                pin["PinName"], DIR_BY_ROTATION.get(pin["Rotation"], "right"),
                float(pin["PinLength"]),
            )
            for pin in record["pins"]
        }
        # A's cross-check needs the same local tips, recomputed the same way.
        out[code]["__tips__"] = {
            str(pin["PinNumber"]): (
                round(pin["X"] - ox, 4), round(pin["Y"] - oy, 4)
            )
            for pin in record["pins"]
        }
    return out


def cross_check(tips, lcsc, measured) -> list[str]:
    """A and B must agree pin for pin wherever both measured the same symbol."""
    problems = []
    for designator, local in sorted(tips.items()):
        record = measured.get(lcsc[designator])
        if not record:
            continue
        theirs = record["__tips__"]
        if set(theirs) != set(local):
            problems.append(
                f"{designator} ({lcsc[designator]}): token set differs, "
                f"A={sorted(local)} B={sorted(theirs)}"
            )
            continue
        for number, tip in sorted(local.items()):
            if tuple(theirs[number]) != tuple(tip):
                problems.append(
                    f"{designator} ({lcsc[designator]}) pin {number}: "
                    f"A reads {tip}, B reads {theirs[number]}"
                )
    return problems


def body_from_pins(local, pins):
    """The drawn body, from the **inner ends of the outer pins**.

    A pin that escapes ``left`` has its body to the **right** of its tip, so the
    inner end is ``tip + inward * length``; the body's edges are the inner ends.
    For a two-pin part those two inner ends are the body's own edges, so this is
    a measurement of the drawn extent.  For a multi-pin part the inner ends of the
    outermost pins bound the part in x and y but say nothing about the notch in
    between, so the box is a stated lower bound — which is exactly what
    `readability`'s body tests need (a wire must not cross a body; a box smaller
    than the truth is permissive, a box larger than the truth refuses a legal
    drawing), and it is labelled per profile by `bodySource`.
    """
    inward = {
        "left": (1.0, 0.0), "right": (-1.0, 0.0),
        "up": (0.0, -1.0), "down": (0.0, 1.0),
    }
    inner = []
    for number, tip in local.items():
        dx, dy = inward[pins[number][1]]
        length = pins[number][2]
        inner.append((tip[0] + dx * length, tip[1] + dy * length))
    xs = [point[0] for point in inner]
    ys = [point[1] for point in inner]
    return (
        round(min(xs), 4), round(min(ys), 4),
        round(max(xs), 4), round(max(ys), 4),
    )


def main(argv: list[str]) -> int:
    tips, lcsc, pool = read_apply()
    measured = read_110()

    problems = cross_check(tips, lcsc, measured)
    if problems:
        sys.stderr.write(
            "the two live readings disagree; the profiles would be a guess:\n  "
            + "\n  ".join(problems) + "\n"
        )
        return 2
    covered = sum(1 for part in tips if lcsc[part] in measured)
    print(f"cross-check: {covered}/{len(tips)} parts measured by BOTH readings, "
          f"0 disagreements")

    current = json.loads(LIBRARY.read_text(encoding="utf-8"))
    old_titles = {item["symbolRef"]: item.get("title", "") for item in current["profiles"]}

    # The 113 intent, kept as the first title line. Copied out of the current
    # library so this tool does not re-word another batch's decision.
    by_spec = json.loads(
        (ROOT / "outputs" / "118" / "plan_report.json").read_text(encoding="utf-8")
    )["plan"]["change"]["parts"]
    spec_of = {item["designator"]: item["specId"] for item in by_spec}

    out_profiles = []
    for entry in current["profiles"]:
        ref = entry["symbolRef"]
        designators = sorted(d for d, s in spec_of.items() if False)
        # which 118 designators use this symbolRef
        users = [item["designator"] for item in by_spec if item["symbolRef"] == ref]
        sample = users[0]
        local = tips[sample]
        record = measured.get(lcsc[sample])
        if record:
            source = (
                f"pins measured on 2026-10-04: tips from 118's pin read-back "
                f"({sample}, {lcsc[sample]}), names/directions/lengths from "
                f"110's 11_pins.json on the same LCSC"
            )
            pins = {
                number: (value[0], value[1], value[2])
                for number, value in record.items() if number != "__tips__"
            }
        else:
            source = (
                f"pins measured on 2026-10-04: tips from 118's pin read-back "
                f"({sample}, {lcsc[sample]}); names/directions/lengths from the "
                f"0603/0805 two-pin family rule read off 110's twelve "
                f"measurements of that family"
            )
            pins = {
                number: (
                    number,
                    "left" if local[number][0] < 0 else "right",
                    10.0,
                )
                for number in local
            }
        for number, tip in local.items():
            if number not in pins:
                raise SystemExit(f"{ref}: pin {number} has no direction/length")
        box = body_from_pins(local, pins)
        two_pin = len(pins) == 2
        intent = old_titles[ref]
        out_profiles.append({
            "symbolRef": ref,
            "title": (
                f"{intent}\n"
                f"[118] pins and body measured 2026-10-04 on the real host: "
                f"{source}. Body box = "
                + ("the two pins' inner ends (measured drawn extent)."
                   if two_pin else
                   "the outer pins' inner ends — a stated lower bound, since no "
                   "reading carries a per-part bounding box.")
            ),
            "body": list(box),
            "bodySource": (
                "measured: the two pins' inner ends"
                if two_pin else
                "derived lower bound: the outer pins' inner ends (no bbox in any reading)"
            ),
            "pins": [
                {
                    "number": number,
                    "name": pins[number][0],
                    "tip": [local[number][0], local[number][1]],
                    "direction": pins[number][1],
                    "length": pins[number][2],
                }
                for number in sorted(local, key=_pin_sort)
            ],
        })

    payload = {
        "kind": current["kind"],
        "libraryVersion": current["libraryVersion"],
        "source": (
            "blockwise-symbol-profile, MEASURED 2026-10-04 from the live editor "
            "(outputs/118/apply_report.json pin read-back; outputs/110/11_pins.json "
            "+ 12_bodies.json for names/directions/lengths). Built by "
            "tools/118_measure_profiles.py — do not hand-edit: a profile is a set "
            "of claims about one library symbol, and 113's hand-written ones were "
            "refused by 054 C6 on contact."
        ),
        "profiles": out_profiles,
    }
    target = pathlib.Path(argv[1]) if len(argv) > 1 else LIBRARY
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    shown = target.relative_to(ROOT).as_posix() if target.is_absolute() else target.as_posix()
    print(f"wrote {shown}: {len(out_profiles)} profiles")
    for item in out_profiles:
        print(f"  {item['symbolRef']:<18} pins={len(item['pins'])} body={item['body']}")
    return 0


def _pin_sort(number: str):
    return (0, int(number), "") if number.isdigit() else (1, 0, number)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
