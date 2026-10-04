#!/usr/bin/env python3
"""115 probe: which relations sit between a branch and its owner, and does the
default `pin` basis already keep them?  Read-only; prints measurements."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import SymbolPin, SymbolProfile  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402

ORDER = ("above", "below", "left-of", "right-of", "adjacent")


def library_from(path: Path) -> dict[str, SymbolProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    book = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        book[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                SymbolPin(
                    str(p["number"]),
                    (float(p["tip"][0]), float(p["tip"][1])),
                    str(p.get("name", "")),
                    str(p.get("direction", "")))
                for p in entry["pins"]
            ],
        )
    return book


def probe(title, circuit, presentation, book):
    print(f"\n========== {title} ==========")
    ctx = dc._prepare(
        circuit, presentation, dc.bind_grammar(
            circuit, presentation, book), book, dc.CompileBudget(max_candidates=64),
    ).context
    assert ctx is not None
    print(f"axis={ctx.axis} progress={ctx.progress} chain={ctx.chain}")
    print("  -- every order-kind constraint --")
    for item in ctx.binding.constraints:
        if item.kind not in ORDER:
            continue
        kinds = {part_id: ctx.slots[part_id].kind
                 for part_id in (item.subject, item.object)
                 if part_id in ctx.slots}
        owner = {
            part_id: ctx.slots[part_id].owner
            for part_id in (item.subject, item.object)
            if part_id in ctx.slots
        }
        shared = sorted(
            set(dc._part_nets(ctx.circuit, item.subject).values())
            & set(dc._part_nets(ctx.circuit, item.object).values())
        )
        print(
            f"    {item.kind}({item.subject},{item.object}) "
            f"slotkinds={kinds} owners={owner} shared={shared}"
        )
    for part_id, slot in sorted(ctx.slots.items()):
        if slot.kind != "branch":
            continue
        relations = [
            f"{item.kind}({item.subject},{item.object})"
            for item in ctx.binding.constraints
            if item.kind in ORDER
            and {item.subject, item.object} == {part_id, slot.owner}
        ]
        if not relations and not any(
            item.subject == part_id or item.object == part_id
            for item in ctx.binding.constraints
            if item.kind in ORDER
        ):
            continue
        net = ctx.circuit.net(slot.shared_net)
        cls = net.cls if net is not None else "?"
        token = dc._shared_token(ctx, slot)
        owner_pose = (
            {slot.owner: ctx.accepted[slot.owner][0]}
            if ctx.accepted.get(slot.owner) else None
        )
        pin_dir = (
            dc._pin_direction(ctx, slot.owner, token, owner_pose)
            if owner_pose else None
        )
        print(
            f"  {part_id}: kind={slot.kind} owner={slot.owner} role={slot.role} "
            f"basis={slot.basis} shared={slot.shared_net}({cls}) "
            f"token={token} sign={slot.sign} axis={slot.offset_axis!r} "
            f"pin_dir={pin_dir} rels={relations}"
        )


def main() -> int:
    import test_098_ic_periphery as sc

    specs = ROOT / "blocklib" / "specs"
    circuit = CircuitSpec.load(specs / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(specs / "flyback_uc3845.presentation.json")
    book = library_from(specs / "flyback_uc3845.library.json")
    probe("flyback", circuit, presentation, book)

    wide_circuit, wide_presentation = sc.sample()
    probe("098 sample (wide)", wide_circuit, wide_presentation, sc.library())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())