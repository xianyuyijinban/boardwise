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

**The body box: measured since 147, derived before that and still labelled so.**
The reading this tool's earlier version said did not exist does exist —
`sch.geometry --params {"bboxIds": [...]}` answers one box per primitive, stroke
included, which *is* the drawn extent of a placed symbol (147 measured it for
all 30 placed primitives of `test/P1`; `outputs/147/12_live_bodies.txt`).
`read_bboxes` folds that answer back through the pose each primitive was placed
at, and a symbol whose parts all agree keeps the measured box. The older
derivation — the **measured pin tips minus the measured pin length**, the inner
ends of the outer pins — stays as the fallback, and the profile's `notes` say
which of the two a profile carries. What 147 fixed by making this measured: the derived
box is the interval between the pins on the pin axis and therefore has **zero
extent perpendicular to it**, and a zero-area box is one no wire and no text row
can ever cross — three defects 岳 caught by eye on the landed page, with every
offline gate green (`outputs/147/FINDINGS.md`).

**`texts` and `notes` are carried through.** They are other batches'
measurements (146's symbol text anchors, 145c's C0603W provenance); a rebuild
that dropped them would delete a measurement nobody re-made.
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

from boardwise.core.symbolprofile import (  # noqa: E402
    FLAG_GLYPH_KIND_RAIL,
    FLAG_GLYPH_ROTATION_OFFSETS,
    SymbolProfile,
    flag_glyph_kind,
)

#: ``symbolRef -> flag family``, filled from the library at the start of a build.
_FLAG_KIND: dict[str, str] = {}

APPLY = ROOT / "outputs" / "118" / "apply_report.json"
PINS110 = ROOT / "outputs" / "110" / "11_pins.json"
BODIES110 = ROOT / "outputs" / "110" / "12_bodies.json"
LIBRARY = ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json"
PLAN_REPORT = ROOT / "outputs" / "118" / "plan_report.json"

#: 147: the per-primitive **body** reading this tool's docstring used to say did
#: not exist. `sch.geometry --params {"bboxIds": [...]}` answers one box per
#: primitive in page coordinates (stroke included), which is the drawn extent of a
#: placed symbol — so the body no longer has to be inferred from the pins' inner
#: ends. `BBOX_LAYOUT` is the landed page those ids came from: it carries the pose
#: of every primitive, and the box is folded back through that pose here.
#:
#: 147b: **both readings live under this tool's own output directory.** They were
#: born in `outputs/147/` and `outputs/146/cand/` — the working files of the two
#: batches that measured them — so rebuilding the library depended on another
#: batch's scratch directory surviving. A cross-batch input is copied next to the
#: tool that consumes it and named for what it is; the 147 originals stay where
#: they are, and `--bbox-reading`/`--bbox-layout` point the tool somewhere else
#: when a newer reading exists. Without either file the tool still runs and falls
#: back to the pin-derived body, labelled as such per profile.
BBOX_READING = ROOT / "outputs" / "118" / "11_geom_bboxes.json"
BBOX_LAYOUT = ROOT / "outputs" / "118" / "bbox_layout.json"

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
    drawing), and the profile's `notes` say which of the two it carries.
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


def read_bboxes(
    profiles,
    reading: pathlib.Path | None = None,
    layout_path: pathlib.Path | None = None,
) -> dict[str, tuple[float, float, float, float]]:
    """``{symbolRef: local body box}`` from the host's own per-primitive bbox.

    ``reading``/``layout_path`` default to :data:`BBOX_READING` and
    :data:`BBOX_LAYOUT` (the copies under `outputs/118/`); the CLI overrides them
    for a newer `sch.geometry bboxIds` reading.

    The reading is a page box per **primitive id**; the poses come from the layout
    the ids were read off, matched on ``(x, y, rotation)`` — a pose that two
    different symbols share would make the mapping a guess, and that is reported
    and skipped rather than averaged.

    Flags fold through the glyph convention frame (``rotation + offset``, mirror
    false, about the anchor) exactly as `symbolprofile.flag_glyph_box` does, and
    their box is then extended back to the connection point so the leader is
    inside it — the same "away from the connection, starting at it" convention
    every flag profile in this repo states.
    """
    reading = BBOX_READING if reading is None else reading
    layout_path = BBOX_LAYOUT if layout_path is None else layout_path
    if not (reading.is_file() and layout_path.is_file()):
        return {}
    bboxes = json.loads(reading.read_text(encoding="utf-8")).get("bboxes", {})
    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    poses: dict[tuple[float, float, float], list[dict]] = {}

    def editor_rotation(angle: float) -> float:
        """The file's angle -> the angle `sch.geometry` reports back.

        `draw.py::_editor_rotation` lands ``R = -angle``, so a plan's 90 comes back
        as the editor's 270 (measured here on C13, the page's one rotated part:
        the layout says 90 and the read-back says 270). Keying the pose table on
        the file angle silently skipped it.
        """
        return (-angle) % 360

    for item in layout["parts"]:
        poses.setdefault(
            (item["x"], item["y"], editor_rotation(float(item["rotation"]))), []
        ).append({"symbolRef": item["symbolRef"], "mirror": bool(item["mirror"]),
                  "flag": False, "rotation": float(item["rotation"])})
    for item in layout.get("powerSymbols", []):
        poses.setdefault(
            (item["x"], item["y"], editor_rotation(float(item["rotation"]))), []
        ).append({"symbolRef": item["symbolRef"], "mirror": False, "flag": True,
                  "rotation": float(item["rotation"])})

    out: dict[str, list[tuple[float, float, float, float]]] = {}
    for record in json.loads(
        BBOX_READING.read_text(encoding="utf-8")
    ).get("components", []):
        state = record.get("state", {})
        comp = state.get("Component", {})
        pid = record.get("primitiveId")
        if comp.get("ComponentType") == "sheet" or pid not in bboxes:
            continue
        key = (float(state.get("X") or 0), float(state.get("Y") or 0),
               float(state.get("Rotation") or 0))
        candidates = poses.get(key, [])
        if len(candidates) != 1:
            continue
        entry = candidates[0]
        ref = entry["symbolRef"]
        box = bboxes[pid]
        page = (box["minX"], box["minY"], box["maxX"], box["maxY"])
        angle = entry["rotation"]
        mirror = entry["mirror"]
        if entry["flag"]:
            angle = entry["rotation"] + FLAG_GLYPH_ROTATION_OFFSETS[flag_glyph_kind_ref(ref)]
            mirror = False
        local = unpose_box(page, rotation=angle, mirror=mirror, ox=key[0], oy=key[1])
        if entry["flag"]:
            local = (local[0], min(0.0, local[1]), local[2], max(0.0, local[3]))
        out.setdefault(ref, []).append(local)
    agreed: dict[str, tuple[float, float, float, float]] = {}
    for ref, boxes in out.items():
        distinct = {tuple(box) for box in boxes}
        if len(distinct) != 1:
            print(f"  !! {ref}: the placed parts disagree ({len(distinct)} boxes); "
                  "the derived body stands")
            continue
        agreed[ref] = tuple(round(v, 1) for v in boxes[0])
    return agreed


def flag_glyph_kind_ref(ref: str) -> str:
    """The flag family of a ``symbolRef`` — a lookup into the profiles at hand."""
    return _FLAG_KIND.get(ref, FLAG_GLYPH_KIND_RAIL)


def unpose_box(box, *, rotation: float, mirror: bool, ox: float, oy: float):
    """Page box -> symbol-local box: the inverse of `core.symbolprofile.pose_box`.

    A rotated rectangle's axis-aligned bound folds back to a box whose own
    axis-aligned bound is the box that went in, so the round trip below is an
    identity rather than a tolerance.
    """
    from boardwise.core.symbolprofile import pose_box

    xs, ys = [], []
    for px, py in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        rad = math.radians(-rotation)
        x, y = px - ox, py - oy
        x, y = x * math.cos(rad) - y * math.sin(rad), x * math.sin(rad) + y * math.cos(rad)
        if mirror:
            x = -x
        xs.append(round(x, 6))
        ys.append(round(y, 6))
    out = (min(xs), min(ys), max(xs), max(ys))
    # Round-trip guard: the box must come back where it started under the one
    # fold every consumer uses.
    back = pose_box(out, rotation=rotation, mirror=mirror, ox=ox, oy=oy)
    assert all(abs(back[i] - box[i]) < 1e-6 for i in range(4)), (out, back, box)
    return out


#: What every profile whose body came from the host's own bbox reading carries.
MEASURED_BODY_SOURCE = (
    "measured: the host's per-primitive bbox (sch.geometry bboxIds), stroke "
    "included, folded back through the pose (147)"
)


def _note_body(notes: list[str]) -> list[str]:
    """Replace the ``body:`` note with what the box now is, keeping the rest."""
    out = [n for n in notes if not n.strip().lower().startswith("body:")]
    return [MEASURED_BODY_SOURCE + " — outputs/147/12_live_bodies.txt"] + out


def _kept_extra(entry: dict, ref: str, measured_bodies: dict) -> dict:
    """``texts``/``notes`` from the profile being rebuilt, verbatim.

    Other batches' measurements (146's symbol text anchors, 145c's C0603W
    provenance) live in these two keys; a rebuild that dropped them would delete
    a measurement nobody re-made.
    """
    extra: dict = {}
    if "texts" in entry:
        extra["texts"] = entry["texts"]
    if "notes" in entry:
        extra["notes"] = (
            _note_body(entry["notes"]) if ref in measured_bodies else entry["notes"]
        )
    return extra


def _option(argv: list[str], name: str) -> pathlib.Path | None:
    """The value of ``--name PATH`` or ``--name=PATH`` in ``argv``, or ``None``."""
    for index, item in enumerate(argv):
        if item == name and index + 1 < len(argv):
            return pathlib.Path(argv[index + 1])
        if item.startswith(f"{name}="):
            return pathlib.Path(item.split("=", 1)[1])
    return None


def _shown(path: pathlib.Path) -> str:
    """``path`` as a repo-relative posix string when it is inside the repo."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _positionals(argv: list[str]) -> list[str]:
    """Everything in ``argv`` that is neither an option nor an option's value."""
    out: list[str] = []
    skip = False
    for item in argv[1:]:
        if skip:
            skip = False
            continue
        if item in ("--bbox-reading", "--bbox-layout"):
            skip = True
            continue
        if item.startswith("--") or item == "-h":
            continue
        out.append(item)
    return out


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
    _FLAG_KIND.clear()
    for item in current["profiles"]:
        _FLAG_KIND[item["symbolRef"]] = flag_glyph_kind(SymbolProfile.from_dict(item))
    reading = _option(argv, "--bbox-reading") or BBOX_READING
    layout_path = _option(argv, "--bbox-layout") or BBOX_LAYOUT
    measured_bodies = read_bboxes(current, reading, layout_path)
    print(f"147: {len(measured_bodies)} symbol(s) have the host's own bbox reading "
          f"({_shown(reading)}); the rest keep the pin-derived body")

    # The 113 intent, kept as the first title line. Copied out of the current
    # library so this tool does not re-word another batch's decision.
    by_spec = json.loads(
        (ROOT / "outputs" / "118" / "plan_report.json").read_text(encoding="utf-8")
    )["plan"]["change"]["parts"]
    spec_of = {item["designator"]: item["specId"] for item in by_spec}

    out_profiles = []
    for entry in current["profiles"]:
        ref = entry["symbolRef"]
        # which 118 designators use this symbolRef
        users = [item["designator"] for item in by_spec if item["symbolRef"] == ref]
        if not users:
            # A profile 118 never placed (145c added C0603W after 118 ran). Its
            # pins and title are another batch's measurement and are kept
            # verbatim; only a measured body can still update it.
            kept = dict(entry)
            if ref in measured_bodies:
                kept["body"] = list(measured_bodies[ref])
                kept["notes"] = _note_body(kept.get("notes", []))
            out_profiles.append(kept)
            continue
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
        derived = body_from_pins(local, pins)
        two_pin = len(pins) == 2
        intent = old_titles[ref]
        if ref in measured_bodies:
            box = list(measured_bodies[ref])
            body_line = (
                "Body box = the host's own per-primitive bbox (`sch.geometry` "
                "bboxIds), folded back through the pose, stroke included — the "
                "true drawn extent."
            )
            body_source = MEASURED_BODY_SOURCE
        else:
            box = list(derived)
            body_line = (
                "Body box = "
                + ("the two pins' inner ends (a lower bound: it is the pin axis, "
                   "with no extent perpendicular to it)."
                   if two_pin else
                   "the outer pins' inner ends — a stated lower bound.")
            )
            body_source = (
                "derived lower bound: the outer pins' inner ends (no bbox reading)"
            )
        out_profiles.append({
            "symbolRef": ref,
            "title": (
                f"{intent}\n"
                f"[118] pins and body measured 2026-10-04 on the real host: "
                f"{source}. {body_line}"
                + (" 147 re-measured the body; see the profile's `notes`."
                   if ref in measured_bodies else "")
            ),
            "body": box,
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
            **_kept_extra(entry, ref, measured_bodies),
        })

    payload = {
        "kind": current["kind"],
        "libraryVersion": current["libraryVersion"],
        "source": (
            "blockwise-symbol-profile, MEASURED 2026-10-04 from the live editor "
            "(outputs/118/apply_report.json pin read-back; outputs/110/11_pins.json "
            "+ 12_bodies.json for names/directions/lengths); every body box "
            "re-measured 2026-10-10 from the host's own per-primitive bbox "
            "(outputs/147/11_geom_bboxes.json, `sch.geometry bboxIds`). Built by "
            "tools/118_measure_profiles.py — do not hand-edit: a profile is a set "
            "of claims about one library symbol, and 113's hand-written ones were "
            "refused by 054 C6 on contact."
        ),
        "profiles": out_profiles,
    }
    positionals = _positionals(argv)
    target = pathlib.Path(positionals[0]) if positionals else LIBRARY
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
