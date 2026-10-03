#!/usr/bin/env python3
"""096 的证据探针：把两处缺陷按同一套代码在两个代码树上各测一次。

    .venv/Scripts/python.exe evidence/096/defect_probe.py <tree-root>

``<tree-root>`` 是要测的树（`src/` 与 `tests/` 都在它下面）：本探针
`sys.path` 只加**这一棵树**的 `src` 与 `tests`，所以「HEAD 树」那一次测的是修复前的
代码、「工作树」那一次测的是修复后的代码，两次场景构造完全同一处定义
（`tests/test_088_power_entry.py`），差别只有源码。

**只读**：不动仓库、不写任何源文件，只打印实测数字。

测得两件事：

1. ③a —— 4 成员电源轨 + mainPath 的页级场景：候选数、页级失败原文、每个模块自己的
   编译结果、rail 的 port 种类与段数、GND 的 port 种类；
2. ③b —— 岳样板声明在 1170x825 页面上：候选数、失败原文、每条候选图形的实测 bbox
   与页边距的比较；不声明页面的同一条电路作为对照。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
for extra in (ROOT / "src", ROOT / "tests"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import boardwise  # noqa: E402
import test_088_power_entry as s  # noqa: E402
from boardwise.core.circuitspec import CircuitSpec  # noqa: E402
from boardwise.core.presentationspec import PresentationSpec  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import pagecompiler as pc  # noqa: E402

RAIL, GND = s.RAIL, s.GND
PAGE = (0.0, 0.0, 1170.0, 825.0)


def wide_rail_page():
    """The 088 pinning scene: a four-member rail marked `mainPath`, page level."""
    spec = CircuitSpec.from_dict({
        **s._page_circuit().to_jsonable(),
        "parts": [*s._page_circuit().to_jsonable()["parts"],
                  {"id": "D1", "symbolRef": "CAP-TH_BD10.0-P5.00",
                   "value": "SMCJ28CA"}],
        "nets": [
            {"id": RAIL, "class": "power",
             "members": ["CN1.1", "D1.1", "C115.1", "R1.1"]},
            {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"]},
            {"id": GND, "class": "gnd",
             "members": ["CN1.2", "D1.2", "C115.2", "R2.2"]},
        ],
    })
    pres = PresentationSpec.from_dict({
        **s._page_presentation().to_jsonable(),
        "modules": [
            {"id": "inlet", "parts": ["CN1", "D1", "C115"],
             "grammarRef": "power-entry", "role": "the inlet"},
            {"id": "sense", "parts": ["R1", "R2"],
             "grammarRef": "voltage-divider", "role": "a divider on the rail"},
        ],
    })
    result = pc.compile_page(spec, pres, s.library(),
                             pc.PageCompileBudget(page_box=s.PAGE_BOX))
    print("--- 3a: four-member rail + mainPath, page level")
    print("    pages                 :", len(result.pages))
    print("    variants refused      :", len(result.rejected))
    print("    modules ok            :",
          {name: module.ok for name, module in sorted(result.modules.items())})
    for item in result.failures:
        print(f"    [{item.category}] {item.detail}")
    if result.ok:
        page = result.pages[0]
        kinds = page.port_kinds()
        print("    port kinds            :",
              {net: sorted(style) for net, style in kinds.items()})
        print("    rail segments (points):",
              [len(seg.points) for seg in page.plan.segments if seg.net == RAIL])
        print("    gnd is a flag         :", kinds.get(GND) == {pc.PAGE_PORT_FLAG})


def allowance(ctx, part_boxes):
    """``_annotation_allowance`` on either tree — this probe's one two-tree seam.

    HEAD (096) takes the context alone; 097 added the placed part boxes, because
    the estimate now also measures the part's own reference/value text and needs
    to know which part is at the drawing's left edge. The probe is documented to
    run on both trees, so it asks in whichever shape the function has.
    """
    if len(inspect.signature(dc._annotation_allowance).parameters) > 1:
        return dc._annotation_allowance(ctx, part_boxes)
    return dc._annotation_allowance(ctx)


def stated_sheet(trace: bool):
    """The 088 pinning scene: 岳's sample stated on a 1170x825 sheet."""
    spec, pres = s.inlet_circuit(), s.inlet_presentation()
    print("--- 3b: the 岳 sample on a stated 1170x825 sheet")
    result = s.compile_module(spec, pres, budget=dc.CompileBudget(page_box=PAGE))
    free = s.compile_module(spec, pres)
    print("    PAGE_MARGIN           :", dc.PAGE_MARGIN)
    print("    stated pages          :", len(result.candidates))
    print("    unstated pages        :", len(free.candidates))
    for item in result.failures:
        print(f"    [{item.category}] {item.detail}")
    inner = (PAGE[0] + dc.PAGE_MARGIN, PAGE[1] + dc.PAGE_MARGIN,
             PAGE[2] - dc.PAGE_MARGIN, PAGE[3] - dc.PAGE_MARGIN)
    print("    inner box (margin in):", inner)
    for index, plan in enumerate(result.candidates, start=1):
        box = pc._module_frame(plan, s.library(), 0.0)
        print("    cand%d drawn box       : %s  left excess=%g top excess=%g"
              % (index, tuple(round(v, 3) for v in box),
                 inner[0] - box[0], box[3] - inner[3]))
    if trace:
        original = dc._anchor_to_page

        def traced(ctx, origins, poses, residue):
            page = ctx.budget.page_box
            before = {
                pid: dc._part_box(ctx.profile(pid), poses[pid], origin)
                for pid, origin in origins.items()
            } if page is not None else {}
            original(ctx, origins, poses, residue)
            if before:
                side, vertical = allowance(ctx, before)
                raw_dx = (page[0] + dc.PAGE_MARGIN + side
                          - min(box[0] for box in before.values()))
                raw_dy = (page[3] - dc.PAGE_MARGIN - vertical
                          - max(box[3] for box in before.values()))
                after = {
                    pid: dc._part_box(ctx.profile(pid), poses[pid], origin)
                    for pid, origin in origins.items()
                }
                print("    [anchor] side=%g vertical=%g grid=%g"
                      % (side, vertical, ctx.budget.grid))
                print("    [anchor] raw dx=%g applied=%g (part left %g -> %g, target %g)"
                      % (raw_dx, min(b[0] for b in after.values()) - min(
                          b[0] for b in before.values()),
                         min(b[0] for b in before.values()),
                         min(b[0] for b in after.values()),
                         page[0] + dc.PAGE_MARGIN + side))
                print("    [anchor] raw dy=%g applied=%g (part top  %g -> %g, target %g)"
                      % (raw_dy, max(b[3] for b in after.values()) - max(
                          b[3] for b in before.values()),
                         max(b[3] for b in before.values()),
                         max(b[3] for b in after.values()),
                         page[3] - dc.PAGE_MARGIN - vertical))

        dc._anchor_to_page = traced
        s.compile_module(spec, pres, budget=dc.CompileBudget(page_box=PAGE))
        dc._anchor_to_page = original


def narrow_sheet(trace: bool):
    """088 preview scene 9: the same sample on a 200x150 sheet (refused either way).

    The only scene in the four preview families whose *artefact* moved under 096,
    because it is the only module-level scene that states a page — so the anchor
    runs, and the refusal report quotes the placements of the variants it built.
    """
    spec, pres = s.inlet_circuit(), s.inlet_presentation()
    page = (0.0, 0.0, 200.0, 150.0)
    print("--- 088 preview scene 9: the 岳 sample on a stated 200x150 sheet")
    result = s.compile_module(spec, pres, budget=dc.CompileBudget(page_box=page))
    free = s.compile_module(spec, pres)
    print("    stated candidates     :", len(result.candidates))
    print("    unstated candidates   :", len(free.candidates))
    free_box = pc._module_frame(free.best(), s.library(), 0.0)
    print("    the drawing itself    : %s  (%g x %g)"
          % (tuple(round(v, 3) for v in free_box),
             free_box[2] - free_box[0], free_box[3] - free_box[1]))
    print("    the page's inner box  : %s  (%g x %g)"
          % ((page[0] + dc.PAGE_MARGIN, page[1] + dc.PAGE_MARGIN,
              page[2] - dc.PAGE_MARGIN, page[3] - dc.PAGE_MARGIN),
             page[2] - page[0] - 2 * dc.PAGE_MARGIN,
             page[3] - page[1] - 2 * dc.PAGE_MARGIN))
    for item in result.failures:
        print(f"    [{item.category}] {item.detail[:200]}")
    if trace:
        original = dc._anchor_to_page

        def traced(ctx, origins, poses, residue):
            before = [
                dc._part_box(ctx.profile(pid), poses[pid], origin)
                for pid, origin in origins.items()
            ]
            original(ctx, origins, poses, residue)
            after = [
                dc._part_box(ctx.profile(pid), poses[pid], origin)
                for pid, origin in origins.items()
            ]
            print("    [anchor] part left %g -> %g (%+g), part top %g -> %g (%+g)"
                  % (min(b[0] for b in before), min(b[0] for b in after),
                     min(b[0] for b in after) - min(b[0] for b in before),
                     max(b[3] for b in before), max(b[3] for b in after),
                     max(b[3] for b in after) - max(b[3] for b in before)))

        dc._anchor_to_page = traced
        s.compile_module(spec, pres, budget=dc.CompileBudget(page_box=page))
        dc._anchor_to_page = original


def main() -> int:
    print(f"tree: {ROOT}")
    print(f"boardwise package: {Path(boardwise.__file__).resolve()}")
    print(f"_snap_inside present: {hasattr(dc, '_snap_inside')}")
    print(f"main_path_wire present: "
          f"{hasattr(__import__('boardwise.core.presentationspec', fromlist=['x']), 'main_path_wire')}")
    print()
    wide_rail_page()
    print()
    stated_sheet(trace=True)
    print()
    narrow_sheet(trace=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
