"""Probe: can a rail port be named at assembly time without a template flag?

The assembler refuses a power/ground port that has no flag at its position,
with the justification "there is no way to invent a flag symbol". This probe
checks that justification instead of assuming it.

Two facts it establishes, offline:

1. `sch.place_power` (the connector action) takes `(kind, net, x, y, rotation,
   mirror)` — **no symbol uuid**. The editor resolves the flag glyph from
   `kind` + `net` itself. So a flag *can* be invented as long as a position is
   known, which is exactly what a datasheet block's port metadata carries.
2. A `PlacedFlag` with an empty `symbol_uuid` survives the replay: the uuid is
   only consulted for the annotation-box prediction (`replay.py:532`), and its
   absence degrades to `glyph=None` rather than raising. So the assembler could
   place a flag with no template-side symbol and the downstream chain would
   accept it.

Before the fix this file reports the current behaviour; it is kept as the
evidence attached to the decision, not as a deliverable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "src")

ROOT = Path(__file__).resolve().parents[1]


def probe_connector_takes_no_symbol() -> bool:
    """The connector action's signature is the whole argument."""
    src = (ROOT / "connector" / "src" / "actions.ts").read_text(encoding="utf-8")
    start = src.index("export const schPlacePower")
    end = src.index("export const schPlaceNetport")
    body = src[start:end]
    call = body[body.index("createNetFlag") : body.index("createNetFlag") + 300]
    has_symbol = "symbol" in body.lower().replace("symbols", "")
    ok = "createNetFlag" in body and not has_symbol
    print(f"1. sch.place_power takes no symbol uuid: {ok}")
    print(f"   call: {' '.join(call.split())[:110]}...")
    return ok


def probe_empty_symbol_uuid_survives_replay() -> bool:
    """A flag with no uuid must not break the replay."""
    from boardwise.core.model import DesignModel
    from boardwise.engines.layout import Rect
    from boardwise.engines.replay import build_replay_plan, sheet_frame_from_bbox
    from boardwise.parsers.schematic import NetLabelAnchor, PageLayout, PlacedFlag

    frame = sheet_frame_from_bbox(Rect(0.0, 0.0, 1170.0, 825.0))
    page = PageLayout()
    page.flags.append(
        PlacedFlag(
            net="+5V", kind="Power", x=0.0, y=0.0, rotation=0.0, mirror=False,
            symbol_uuid="",
        )
    )
    page.labels.append(NetLabelAnchor(net="SIG", x=10.0, y=0.0, rotation=0.0))
    try:
        plan = build_replay_plan(DesignModel(), page, frame, {}, bodies=None)
    except Exception as exc:  # noqa: BLE001 - the point is to see what happens
        print(f"2. a flag with no symbol uuid survives the replay: False ({exc!r})")
        return False
    steps = [s for s in plan.net_names if s.kind == "Power"]
    ok = len(steps) == 1 and steps[0].net == "+5V"
    print(f"2. a flag with no symbol uuid survives the replay: {ok}")
    print(f"   the plan still names +5V with a Power step at "
          f"({steps[0].x:.0f}, {steps[0].y:.0f})" if ok else "   no Power step")
    return ok


def main() -> int:
    a = probe_connector_takes_no_symbol()
    b = probe_empty_symbol_uuid_survives_replay()
    print()
    if a and b:
        print("VERDICT: the assembler's justification does not hold. A rail port")
        print("         can be named at assembly time: the position comes from the")
        print("         port, and the glyph comes from the editor.")
    else:
        print("VERDICT: at least one half failed — read the lines above.")
    return 0 if (a and b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
