#!/usr/bin/env python3
"""088b 的离线预览：电源入口跟进批的两个裁决，画成图或写成拒绝报告。

    .venv/Scripts/python.exe tools/088b_previews.py [output-dir]

写 ``outputs/088b_preview/``（默认；gitignore 的构建产物，可从源重放），并打印清单：
每个文件一行 sha256。产物三类：

* 能编译的场景 —— 候选 SVG（每个场景最多两个候选：最好的那个和它的亚军，"排名真的
  在做事"才看得见），场景 8 是页级（带模块虚线框）；
* 语法层的拒绝 —— 拒绝报告（四分类里的哪一类、措辞、以及可执行动作）；
* **spec 层的拒绝**（`branchOrder` 的校验三态里有两条发生在 spec 解析期，是异常而不是
  拒绝对象）—— 报告里写清异常类型与逐字消息，让"后来人能看见措辞"。

**场景定义只有一处**：电路/表现/预算的构造在 ``tests.test_088b_followups``，即那批断言的
同一个模块——复制一份就是同一个画法的第二个定义，两边一分歧，预览画的就是没有任何测试
编译过的电路。``tests/`` 不是包，所以按 ``tests/conftest.py`` 的做法把 ``src/`` 与
``tests/`` 都放进 ``sys.path``。

确定性在这里是契约：编译器是确定性的，``svgpreview.render_svg`` 是计划的纯函数，
所以**同一版跑两次逐字节一致**——下面的 digest 就是给这个检查用的。

对照面：088 自己的预览（`tools/088_previews.py` / `outputs/088_preview/`）里，
不声明模块的模块级场景本批**一张都不动**（出处符号与顺序都是声明触发的），
这是"零移动"的一部分；088b 的图是声明之后的样子。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_088b_followups as scenarios  # noqa: E402  (the scenario owner)
from boardwise.core.presentationspec import PresentationSpecError  # noqa: E402
from boardwise.engines import pagecompiler as pc  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

#: Where the previews go, how many candidates per scene are drawn, and what a
#: previous run may have left behind (only files matching the pattern are swept).
DEFAULT_OUT = ROOT / "outputs" / "088b_preview"
CANDIDATES = 2
STALE_PATTERN = "088b_*"

USAGE = "usage: 088b_previews.py [output-dir]"


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
    stem = f"088b_scene{number:02d}_{slug}"
    if not result.ok:
        written = _refusal(
            out / f"{stem}_refused.txt",
            f"088b scene {number}: refused by the compiler",
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
            title=(f"088b scene {number}: {slug} — candidate {index} "
                   f"({result.ranked[index - 1].describe_key()})"),
        ))
    return written, f"drawn ({len(result.candidates)} candidate(s))"


def grammar_scene(out: Path, number: int, slug: str, circuit_spec,
                  presentation_spec) -> tuple[list[Path], str]:
    """One scene the *grammar* refuses: the wording is the artefact."""
    result = scenarios.bind(circuit_spec, presentation_spec)
    categories = ", ".join(item.category for item in result.failures)
    written = _refusal(
        out / f"088b_scene{number:02d}_{slug}_refused.txt",
        f"088b scene {number}: refused by the grammar ({categories})",
        [
            *[
                f"[{item.category}] subject={item.subject!r}\n  {item.detail}\n"
                f"  try: {item.action}"
                for item in result.failures
            ],
        ],
    )
    return [written], f"refused by the grammar ({categories})"


def spec_scene(out: Path, number: int, slug: str, build) -> tuple[list[Path], str]:
    """One scene the *presentation spec* refuses (an exception, not a result)."""
    stem = f"088b_scene{number:02d}_{slug}"
    try:
        build()
    except PresentationSpecError as exc:
        written = _refusal(
            out / f"{stem}_refused.txt",
            f"088b scene {number}: refused by the presentation spec",
            [f"PresentationSpecError: {exc}", ""],
        )
        return [written], "refused by the spec"
    written = _refusal(
        out / f"{stem}_NOT_refused.txt",
        f"088b scene {number}: the spec accepted this document (unexpected)",
        [],
    )
    return [written], "NOT refused (unexpected)"


def page_scene(out: Path, number: int, slug: str) -> tuple[list[Path], str]:
    """The page-level scene: the inlet module beside a divider module."""
    circuit_spec, presentation_spec = scenarios.page_pair()
    result = pc.compile_page(
        circuit_spec, presentation_spec, scenarios.library(),
        pc.PageCompileBudget(page_box=scenarios.base088.PAGE_BOX),
    )
    stem = f"088b_scene{number:02d}_{slug}"
    if not result.ok:
        written = _refusal(
            out / f"{stem}_refused.txt",
            f"088b scene {number}: refused by the page compiler",
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
            out / f"{stem}_page_cand1.svg", page.plan, scenarios.library(),
            page_box=scenarios.base088.PAGE_BOX,
            frames=[(module.id, module.frame) for module in page.modules],
            title=(f"088b scene {number}: inlet (declared order) + divider on one "
                   f"page — gnd outlet inside the group, 069 flags at the "
                   f"boundary ({page.verdict})"),
        )
    ]
    return written, f"page drawn ({len(result.pages)} page(s), {page.verdict})"


def generate(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    for stale in sorted(out.glob(STALE_PATTERN)):
        stale.unlink()
    written: list[Path] = []

    plan: list[tuple[int, str, object, object]] = [
        (1, "sample_declared", *scenarios.sample(side="right")),
        (2, "mirror_declared", *scenarios.sample(side="left")),
        (3, "declared_no_order", *scenarios.sample(order=None)),
        (4, "four_branches_declared", *scenarios.sample(
            order=scenarios.FOUR, branches=scenarios.FOUR)),
        (5, "partial_order", *scenarios.sample(order=("C116",))),
        (6, "long_values_declared", *scenarios.sample(
            values={"C115": "330uF/35V", "C116": "330uF/35V"})),
        (7, "088_default_no_module", scenarios.inlet_circuit(),
         scenarios.undeclared(side="right")),
    ]
    for number, slug, circuit_spec, presentation_spec in plan:
        paths, summary = module_scene(out, number, slug, circuit_spec,
                                      presentation_spec)
        written.extend(paths)
        print(f"scene {number:2d} {slug}: {summary} -> "
              + ", ".join(path.name for path in paths))

    paths, summary = page_scene(out, 8, "page_group_and_divider")
    written.extend(paths)
    print(f"scene  8 page_group_and_divider: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = grammar_scene(
        out, 9, "order_names_the_inlet", scenarios.inlet_circuit(),
        scenarios.declared(order=("CN1", "D1")),
    )
    written.extend(paths)
    print(f"scene  9 order_names_the_inlet: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = grammar_scene(
        out, 10, "order_names_a_non_shunt", scenarios.inlet_circuit(),
        scenarios.declared(branches=("D1",), order=("C117", "D1"),
                           parts=("CN1", "D1", "C117")),
    )
    written.extend(paths)
    print(f"scene 10 order_names_a_non_shunt: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = spec_scene(
        out, 11, "order_names_an_unknown_designator",
        lambda: scenarios.declared(order=("C9", "D1")),
    )
    written.extend(paths)
    print(f"scene 11 order_names_an_unknown_designator: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = spec_scene(
        out, 12, "order_names_a_designator_twice",
        lambda: scenarios.declared(order=("D1", "D1", "C115")),
    )
    written.extend(paths)
    print(f"scene 12 order_names_a_designator_twice: {summary} -> "
          + ", ".join(path.name for path in paths))
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
