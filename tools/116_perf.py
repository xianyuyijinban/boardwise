#!/usr/bin/env python3
"""116 performance probes: where the flyback page's time actually went.

Read-only, offline.  Each probe answers one question, and between them they
locate the pathology without guessing at it — which matters, because the first
suspicion (that the new order-consumption pass was itself slow) was **wrong**:

* ``--profile``  cProfile of the whole compile, so the hot region is named;
* ``--ab``       compile once with the pass on and once with it off, so the
                 question "is the cost the pass's CPU, or the moves the pass
                 made?" is answered by measurement;
* ``--routes``   time each individual ``Router.route`` call, so a search that
                 *finds* its path after exhausting the corridor is visible
                 rather than hidden inside a total;
* ``--bounds``   the placements' bounding boxes with the pass on and off, to
                 rule out "the corridor grew" as the explanation.

    .venv/Scripts/python.exe tools/116_perf.py --all
"""

from __future__ import annotations

import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.core.symbolprofile import (  # noqa: E402
    SymbolPin,
    SymbolProfile,
)
from boardwise.engines import drawcompiler as dc  # noqa: E402

SPECS = ROOT / "blocklib" / "specs"


def book() -> dict[str, SymbolProfile]:
    payload = json.loads(
        (SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8"))
    out: dict[str, SymbolProfile] = {}
    for entry in payload["profiles"]:
        body = entry.get("body")
        out[entry["symbolRef"]] = SymbolProfile(
            symbol_ref=entry["symbolRef"], title=entry.get("title", ""),
            body=tuple(float(v) for v in body) if body else None,
            pins=[
                SymbolPin(
                    str(p["number"]), (float(p["tip"][0]), float(p["tip"][1])),
                    str(p.get("name", "")), str(p.get("direction", "")))
                for p in entry["pins"]
            ],
        )
    return out


def inputs():
    return (
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(SPECS / "flyback_uc3845.presentation.json"),
        book(),
    )


def compile_once():
    circuit, presentation, symbols = inputs()
    started = time.perf_counter()
    result = dc.compile(circuit, presentation, symbols,
                        dc.CompileBudget(max_candidates=64))
    return time.perf_counter() - started, result


def probe_profile() -> None:
    profiler = cProfile.Profile()
    profiler.enable()
    compile_once()
    profiler.disable()
    for sort in ("cumulative", "tottime"):
        stream = io.StringIO()
        pstats.Stats(profiler, stream=stream).sort_stats(sort).print_stats(30)
        print(f"\n===== profile, sorted by {sort} =====")
        print(stream.getvalue())


def probe_ab() -> None:
    """The pass on vs the pass off — the CPU of the pass against its moves."""
    saved = dc._honour_bound_orders
    for label, off in (("pass off", True), ("pass on", False)):
        if off:
            dc._honour_bound_orders = lambda *a, **k: None
        else:
            dc._honour_bound_orders = saved
        elapsed, result = compile_once()
        print(f"{label:9s} {elapsed:8.2f}s  ok={result.ok} "
              f"cands={len(result.candidates)} rejected={len(result.rejected)}")
    dc._honour_bound_orders = saved


def probe_routes() -> None:
    """Time each individual route, so a slow *successful* search is visible."""
    from boardwise.engines import router as rt

    real = rt.Router.route
    rows: list[tuple[float, bool, bool]] = []

    def traced(self, start, goal, **kw):
        started = time.perf_counter()
        found = real(self, start, goal, **kw)
        rows.append((time.perf_counter() - started, found is not None,
                     kw.get("targets") is not None))
        return found

    rt.Router.route = traced
    try:
        total, _ = compile_once()
    finally:
        rt.Router.route = real
    print(f"total {total:.2f}s")
    for elapsed, found, multi in sorted(rows, reverse=True):
        print(f"  {elapsed:8.2f}s found={found} multi_target={multi}")
    print(f"route calls: {len(rows)}  time inside route: "
          f"{sum(row[0] for row in rows):.2f}s")


def probe_bounds() -> None:
    """The bounding box per rung, pass on and off — is the corridor bigger?"""
    circuit, presentation, symbols = inputs()
    saved = dc._honour_bound_orders
    saved_gate = dc._relation_failures
    dc._relation_failures = lambda ctx, placed: []
    try:
        for label, off in (("off", True), ("on", False)):
            if off:
                dc._honour_bound_orders = lambda *a, **k: None
            else:
                dc._honour_bound_orders = saved
            binding = dc.bind_grammar(circuit, presentation, symbols)
            ctx = dc._prepare(circuit, presentation, binding, symbols,
                              dc.CompileBudget(max_candidates=64)).context
            assert ctx is not None
            for index, variant in enumerate(dc._variants(ctx)):
                placed, _failure = dc._place(ctx, variant)
                xs = [o[0] for o in placed.origins.values()]
                ys = [o[1] for o in placed.origins.values()]
                print(f"{label} v{index} {variant.label}: "
                      f"x[{min(xs):g},{max(xs):g}] y[{min(ys):g},{max(ys):g}] "
                      f"span {max(xs) - min(xs):g}x{max(ys) - min(ys):g}")
    finally:
        dc._honour_bound_orders = saved
        dc._relation_failures = saved_gate


PROBES = {
    "profile": probe_profile,
    "ab": probe_ab,
    "routes": probe_routes,
    "bounds": probe_bounds,
}


def main(argv: list[str]) -> int:
    wanted = argv[1:]
    if not wanted or wanted == ["--all"]:
        wanted = sorted(PROBES)
    else:
        wanted = [name.lstrip("-") for name in wanted]
    for name in wanted:
        if name not in PROBES:
            sys.stderr.write(f"unknown probe {name!r}; have {sorted(PROBES)}\n")
            return 2
        print(f"\n===== probe: {name} =====")
        PROBES[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
