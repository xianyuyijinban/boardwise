#!/usr/bin/env python3
"""088 的离线预览：`power-entry` 十个场景，画成图或写成拒绝报告。

    .venv/Scripts/python.exe tools/088_previews.py [output-dir]

写 ``outputs/088_preview/``（默认；gitignore 的构建产物，可从源重放），并打印
清单：每个文件一行 sha256。产物三类：

* 能编译的场景 —— 候选 SVG（每个场景最多两个候选：最好的那个和它的亚军，"排名
  真的在做事"才看得见），页级场景带模块虚线框；
* 语法层拒绝的场景 —— 拒绝报告（四分类里的哪一类、措辞、以及可执行动作）；
* 编译器拒绝的场景 —— 拒绝报告 + 每个被建出来又落选的变体。

**场景定义只有一处**：电路/表现/预算的构造在
``tests.test_088_power_entry``，即那批断言的同一个模块——复制一份就是同一个
画法的第二个定义，两边一分歧，预览画的就是没有任何测试编译过的电路。
``tests/`` 不是包，所以按 ``tests/conftest.py`` 的做法把 ``src/`` 与 ``tests/``
都放进 ``sys.path``。

确定性在这里是契约：编译器是确定性的，``svgpreview.render_svg`` 是计划的纯函数，
所以**同一版跑两次逐字节一致**——下面的 digest 就是给这个检查用的。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_088_power_entry as scenarios  # noqa: E402  (the scenario owner)
from boardwise.engines import pagecompiler as pc  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

#: Where the previews go, how many candidates per scene are drawn, and what a
#: previous run may have left behind (only files matching the pattern are swept).
DEFAULT_OUT = ROOT / "outputs" / "088_preview"
CANDIDATES = 2
STALE_PATTERN = "088_*"

USAGE = "usage: 088_previews.py [output-dir]"


def _refusal(path: Path, headline: str, lines: list[str]) -> Path:
    path.write_text("\n".join([headline, *lines]) + "\n", encoding="utf-8")
    return path


def module_scene(out: Path, number: int, slug: str, circuit_spec, presentation_spec,
                 **budget) -> tuple[list[Path], str]:
    """One module scene: previews if it compiles, a refusal report if it does not."""
    result = scenarios.compile_module(
        circuit_spec, presentation_spec,
        budget=scenarios.dc.CompileBudget(**budget) if budget else None,
    )
    stem = f"088_scene{number:02d}_{slug}"
    if not result.ok:
        written = _refusal(
            out / f"{stem}_refused.txt",
            f"088 scene {number}: refused by the compiler",
            [
                result.render_failures(),
                "",
                "variants built and refused:",
                *[f"  {item.variant}: {item.reason[:300]}" for item in result.rejected],
            ],
        )
        return [written], f"refused ({', '.join(result.categories())})"
    written: list[Path] = []
    for index, plan in enumerate(result.candidates[:CANDIDATES], start=1):
        written.append(svgpreview.write_preview(
            out / f"{stem}_cand{index}.svg", plan, scenarios.library(),
            title=(f"088 scene {number}: {slug} — candidate {index} "
                   f"({result.ranked[index - 1].describe_key()})"),
        ))
    return written, f"drawn ({len(result.candidates)} candidate(s))"


def grammar_scene(out: Path, number: int, slug: str, circuit_spec,
                  presentation_spec) -> tuple[list[Path], str]:
    """One scene the *grammar* refuses: the wording is the artefact."""
    result = scenarios.bind(circuit_spec, presentation_spec)
    categories = ", ".join(item.category for item in result.failures)
    written = _refusal(
        out / f"088_scene{number:02d}_{slug}_refused.txt",
        f"088 scene {number}: refused by the grammar ({categories})",
        [
            *[
                f"[{item.category}] {item.detail}\n  try: {item.action}"
                for item in result.failures
            ],
        ],
    )
    return [written], f"refused by the grammar ({categories})"


def page_scene(out: Path) -> tuple[list[Path], str]:
    """Scene 10: the inlet module and a divider module on one page."""
    result = pc.compile_page(
        scenarios._page_circuit(), scenarios._page_presentation(),
        scenarios.library(), pc.PageCompileBudget(page_box=scenarios.PAGE_BOX),
    )
    if not result.ok:
        written = _refusal(
            out / "088_scene10_page_refused.txt",
            "088 scene 10: refused by the page compiler",
            [
                *[f"[{item.category}] {item.detail}" for item in result.failures],
                "",
                "variants built and refused:",
                *[f"  {item.variant}: {item.reason[:300]}" for item in result.rejected],
            ],
        )
        return [written], "page refused"
    page = result.pages[0]
    written = [
        svgpreview.write_preview(
            out / "088_scene10_page_cand1.svg", page.plan, scenarios.library(),
            page_box=scenarios.PAGE_BOX,
            frames=[(module.id, module.frame) for module in page.modules],
            title="088 scene 10: inlet + divider on one page",
        )
    ]
    return written, f"page drawn ({len(result.pages)} page(s))"


def generate(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    for stale in sorted(out.glob(STALE_PATTERN)):
        stale.unlink()
    written: list[Path] = []
    plan: list[tuple[int, str, str, object, object]] = [
        (1, "sample", "岳 sample: inlet, TVS and two 330uF", scenarios.inlet_circuit(),
         scenarios.inlet_presentation(side="right")),
        (2, "mirror", "input on the left", scenarios.inlet_circuit(),
         scenarios.inlet_presentation(side="left")),
        (3, "minimal", "inlet and one capacitor",
         scenarios.inlet_circuit(shunts=("C115",)), scenarios.inlet_presentation()),
        (4, "four_branches", "inlet and four branches",
         scenarios.inlet_circuit(shunts=("D1", "C115", "C116", "C117")),
         scenarios.inlet_presentation()),
        (8, "long_text", "long values and a big electrolytic",
         scenarios.inlet_circuit(values={"C115": "330uF/35V", "C116": "330uF/35V"}),
         scenarios.inlet_presentation()),
    ]
    for number, slug, _note, circuit_spec, presentation_spec in plan:
        paths, summary = module_scene(out, number, slug, circuit_spec,
                                      presentation_spec)
        written.extend(paths)
        print(f"scene {number:2d} {slug}: {summary} -> "
              + ", ".join(path.name for path in paths))

    paths, summary = grammar_scene(
        out, 5, "no_part", scenarios.inlet_circuit(interface=False),
        scenarios.inlet_presentation(),
    )
    written.extend(paths)
    print(f"scene  5 no_part: {summary} -> " + ", ".join(p.name for p in paths))

    paths, summary = grammar_scene(
        out, 6, "bad_part", scenarios.inlet_circuit(part_field="CN9"),
        scenarios.inlet_presentation(),
    )
    written.extend(paths)
    print(f"scene  6 bad_part: {summary} -> " + ", ".join(p.name for p in paths))

    paths, summary = grammar_scene(
        out, 7, "missing_class",
        scenarios.circuit(
            [scenarios.part("CN1", "XT30PW-M"), scenarios.part("C115", "C0402")],
            [scenarios.net(scenarios.RAIL, "power", ["CN1.1", "C115.1"]),
             scenarios.net("RET", "signal", ["CN1.2", "C115.2"])],
            interfaces=[{"net": scenarios.RAIL, "direction": "input",
                         "role": "rail", "part": "CN1", "provenance": "verified_recipe"}],
        ),
        scenarios.inlet_presentation(),
    )
    written.extend(paths)
    print(f"scene  7 missing_class: {summary} -> " + ", ".join(p.name for p in paths))

    paths, summary = module_scene(out, 9, "narrow", scenarios.inlet_circuit(),
                                  scenarios.inlet_presentation(),
                                  page_box=(0.0, 0.0, 200.0, 150.0))
    written.extend(paths)
    print(f"scene  9 narrow: {summary} -> " + ", ".join(p.name for p in paths))

    paths, summary = page_scene(out)
    written.extend(paths)
    print(f"scene 10 page: {summary} -> " + ", ".join(p.name for p in paths))
    return written


def manifest(paths: list[Path]) -> str:
    """One line per artefact: name, sha256, size — the two-run check's evidence."""
    return "\n".join(
        f"{path.name}  {hashlib.sha256(path.read_bytes()).hexdigest()}  "
        f"{path.stat().st_size} bytes"
        for path in paths
    )


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(USAGE, file=sys.stderr)
        return 2
    out = Path(argv[1]).resolve() if len(argv) == 2 else DEFAULT_OUT
    written = generate(out)
    print(f"\n{len(written)} preview file(s) in {out}")
    print(manifest(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
