#!/usr/bin/env python3
"""098 的离线预览：`ic-periphery` 十个场景，画成图或写成拒绝报告。

    .venv/Scripts/python.exe tools/098_previews.py [output-dir]

写 ``outputs/098_preview/``（默认；gitignore 的构建产物，可从源重放），并打印
清单：每个文件一行 sha256。产物三类：

* 能编译的场景 —— 候选 SVG（每个场景最多两个候选：最好的那个和它的亚军，"排名
  真的在做事"才看得见），页级场景带模块虚线框；
* 语法层拒绝的场景 —— 拒绝报告（四分类里的哪一类、措辞、以及可执行动作）；
* 核心来自 intent 的场景 —— 绑定报告（核心那一行的 evidence 原文，含合同出处）。

**场景定义只有一处**：电路/表现/预算的构造在 ``tests.test_098_ic_periphery``，即那批
断言的同一个模块——复制一份就是同一个画法的第二个定义，两边一分歧，预览画的就是没有
任何测试编译过的电路。``tests/`` 不是包，所以按 ``tests/conftest.py`` 的做法把 ``src/``
与 ``tests/`` 都放进 ``sys.path``。

确定性在这里是契约：编译器是确定性的，``svgpreview.render_svg`` 是计划的纯函数，
所以**同一版跑两次逐字节一致**——下面的 digest 就是给这个检查用的。

**不删任何东西**（本批红线#4：零删除）：产物按名字原地覆盖，没有 sweep，也没有
``unlink``——前一版的 stale 文件由人处理，不由脚本处理。
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_098_ic_periphery as scenarios  # noqa: E402  (the scenario owner)
from boardwise.core.designintent import DesignIntent  # noqa: E402
from boardwise.engines import drawcompiler as dc  # noqa: E402
from boardwise.engines import grammar  # noqa: E402
from boardwise.engines import pagecompiler as pc  # noqa: E402
from boardwise.engines import svgpreview  # noqa: E402

#: Where the previews go and how many candidates per scene are drawn.
DEFAULT_OUT = ROOT / "outputs" / "098_preview"
CANDIDATES = 2

USAGE = "usage: 098_previews.py [output-dir]"


def _report(path: Path, headline: str, lines: list[str]) -> Path:
    path.write_text("\n".join([headline, *lines]) + "\n", encoding="utf-8")
    return path


def module_scene(out: Path, number: int, slug: str, circuit_spec, presentation_spec,
                 **budget) -> tuple[list[Path], str]:
    """One module scene: previews if it compiles, a refusal report if it does not."""
    result = scenarios.compile_module(
        circuit_spec, presentation_spec,
        budget=dc.CompileBudget(**budget) if budget else None,
    )
    stem = f"098_scene{number:02d}_{slug}"
    if not result.ok:
        written = _report(
            out / f"{stem}_refused.txt",
            f"098 scene {number}: refused by the compiler",
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
            title=(f"098 scene {number}: {slug} — candidate {index} "
                   f"({result.ranked[index - 1].describe_key()})"),
        ))
    return written, f"drawn ({len(result.candidates)} candidate(s))"


def grammar_scene(out: Path, number: int, slug: str, circuit_spec,
                  presentation_spec, *, note: str = "") -> tuple[list[Path], str]:
    """One scene the *grammar* refuses: the wording is the artefact."""
    result = scenarios.bind(circuit_spec, presentation_spec)
    categories = ", ".join(item.category for item in result.failures)
    written = _report(
        out / f"098_scene{number:02d}_{slug}_refused.txt",
        f"098 scene {number}: refused by the grammar ({categories})",
        [
            *([note, ""] if note else []),
            *[
                f"[{item.category}] {item.detail}\n  try: {item.action}"
                for item in result.failures
            ],
            "",
            "(a refusal is not an empty failure: the category, the reason and the "
            "action are the drawing that could not be made)",
        ],
    )
    return [written], f"refused by the grammar ({categories})"


def binding_scene(out: Path, number: int, slug: str, headline: str,
                  circuit_spec, presentation_spec, *, intent=None) -> tuple[list[Path], str]:
    """One scene that *binds*: the evidence is the artefact (098 scene 10)."""
    result = scenarios.bind(circuit_spec, presentation_spec, intent=intent)
    lines = [f"ok={result.ok}"]
    if not result.ok:
        lines.extend(
            f"[{item.category}] {item.detail}\n  try: {item.action}"
            for item in result.failures
        )
    else:
        for binding in result.bindings:
            lines.append(f"{binding.role:7s} {binding.part_id}")
            lines.append(f"    {binding.evidence}")
        lines.append("")
        lines.append("constraints:")
        lines.extend(
            f"  {item.kind:12s} {item.subject} -> {item.object}\n      {item.reason}"
            for item in result.constraints
        )
        lines.append("")
        lines.append("obligations:")
        lines.extend(
            f"  {item.kind} {list(item.nets)}\n      {item.reason}"
            for item in result.obligations
        )
    written = _report(out / f"098_scene{number:02d}_{slug}_binding.txt", headline, lines)
    return [written], f"bound (ok={result.ok})"


def page_scene(out: Path, *, main_path: bool) -> tuple[list[Path], str]:
    """Scene 9: the CH340 module and a USB socket module on one page."""
    slug = "page_mainpath" if main_path else "page"
    result = pc.compile_page(
        scenarios.page_circuit(), scenarios.page_presentation(main_path=main_path),
        scenarios.library(), pc.PageCompileBudget(page_box=scenarios.PAGE_BOX),
    )
    if not result.ok:
        written = _report(
            out / f"098_scene09_{slug}_refused.txt",
            "098 scene 9: refused by the page compiler",
            [
                *[f"[{item.category}] {item.detail}" for item in result.failures],
                "",
                "variants built and refused:",
                *[f"  {item.variant}: {item.reason[:300]}" for item in result.rejected],
            ],
        )
        return [written], "page refused"
    page = result.pages[0]
    kinds = page.port_kinds()
    written = [
        svgpreview.write_preview(
            out / f"098_scene09_{slug}_cand1.svg", page.plan, scenarios.library(),
            page_box=scenarios.PAGE_BOX,
            frames=[(module.id, module.frame) for module in page.modules],
            title=(f"098 scene 9: CH340 + USB on one page "
                   f"({'mainPath' if main_path else 'no mainPath'})"),
        )
    ]
    summary = ", ".join(
        f"{net}={sorted(kinds[net])[0]}" for net in sorted(kinds)
    )
    return written, f"page drawn ({summary})"


def generate(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    sample_circuit, sample_sheet = scenarios.sample()
    plain = [
        (1, "sample", "岳 CH340 样板：晶振簇 + 去耦 + V3 + 四条信号标签",
         sample_circuit, sample_sheet),
        (2, "mirror", "声明侧换侧：整组镜像（标签与簇同步）",
         scenarios.sample_circuit(),
         scenarios.sample_presentation(sides=scenarios.flipped_sides())),
        (3, "minimal", "核心 + 1 去耦（核心由结构认）",
         scenarios.circuit(
             [scenarios.part("U1", "SOIC-16-CORE", "CH340G"),
              scenarios.part("C3", "C0402", "100nF")],
             [
                 scenarios.net(scenarios.RAIL, "power", ["U1.16", "C3.1"]),
                 scenarios.net(scenarios.GND, "gnd", ["U1.1", "C3.2"]),
                 scenarios.net("SIG", "signal", ["U1.4"]),
             ],
         ),
         scenarios.sample_presentation(declared=False, core=None, module_parts=(),
                                       signals=(), port_roles={})),
        (4, "two_clusters", "两个 bridge 各自带 shunt（两簇）",
         scenarios.circuit(
             [
                 scenarios.part("U1", "SOIC-16-CORE", "DUAL"),
                 scenarios.part("X1", "XTAL-2P", "12MHz"),
                 scenarios.part("X2", "XTAL-2P", "32kHz"),
                 scenarios.part("C1", "C0402", "22pF"),
                 scenarios.part("C2", "C0402", "15pF"),
             ],
             [
                 scenarios.net(scenarios.RAIL, "power", ["U1.16"]),
                 scenarios.net(scenarios.GND, "gnd", ["U1.1", "C1.2", "C2.2"]),
                 scenarios.net("A1", "signal", ["U1.4", "X1.1", "C1.1"]),
                 scenarios.net("B1", "signal", ["U1.5", "X1.2"]),
                 scenarios.net("A2", "signal", ["U1.6", "X2.1", "C2.1"]),
                 scenarios.net("B2", "signal", ["U1.7", "X2.2"]),
             ],
         ),
         scenarios.sample_presentation(declared=False, core=None, module_parts=(),
                                       signals=(), port_roles={},
                                       sidePreferences={})),
        (7, "long_text", "长值 + 长网名不压线不穿体",
         scenarios.sample_circuit(
             signals=scenarios.LONG_SIGNALS,
             values={"C1": "22pF/50V NPO", "C2": "22pF/50V NPO",
                     "C3": "100nF/50V X7R", "C4": "100nF/50V X7R"},
         ),
         scenarios.sample_presentation(signals=scenarios.LONG_SIGNALS)),
    ]
    for number, slug, note, circuit_spec, presentation_spec in plain:
        paths, summary = module_scene(out, number, slug, circuit_spec,
                                      presentation_spec)
        written.extend(paths)
        print(f"scene {number:2d} {slug}: {summary} -> "
              + ", ".join(path.name for path in paths))

    stray_circuit = scenarios.sample_circuit(
        extra_parts=[scenarios.part("R7", "R0402", "1k")],
        extra_nets=[
            scenarios.net("LEDA", "signal", ["R7.1"]),
            scenarios.net("LEDK", "signal", ["R7.2"]),
        ],
    )
    paths, summary = grammar_scene(
        out, 5, "ambiguous_core", *scenarios.sample_core_ambiguity(),
        note="两颗多脚件、没有声明：核心认不出来，语法点名两处可写处。",
    )
    written.extend(paths)
    print(f"scene  5 ambiguous_core: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = grammar_scene(
        out, 6, "foreign_part", stray_circuit,
        scenarios.sample_presentation(
            module_parts=(*scenarios.SAMPLE_MODULE_PARTS, "R7")
        ),
        note="模块里混进一颗不碰核心任何脚的两脚件：点名它实际连着谁。",
    )
    written.extend(paths)
    print(f"scene  6 foreign_part: {summary} -> "
          + ", ".join(path.name for path in paths))

    paths, summary = module_scene(out, 8, "narrow", sample_circuit, sample_sheet,
                                  page_box=(0.0, 0.0, 300.0, 200.0))
    written.extend(paths)
    print(f"scene  8 narrow: {summary} -> "
          + ", ".join(path.name for path in paths))

    for main_path in (False, True):
        paths, summary = page_scene(out, main_path=main_path)
        written.extend(paths)
        print(f"scene  9 page{'_mainpath' if main_path else ''}: {summary} -> "
              + ", ".join(path.name for path in paths))

    document = DesignIntent.from_dict({
        "blocks": [{
            "id": "serial", "kind": "usb-serial", "parts": ["U1", "X1", "C1"],
            "provenance": scenarios.PROV,
        }],
    })
    paths, summary = binding_scene(
        out, 10, "intent_core",
        "098 scene 10: the core comes from the contract (no modules[].core)",
        scenarios.sample_circuit(),
        scenarios.sample_presentation(declared=False, core=None),
        intent=document,
    )
    written.extend(paths)
    print(f"scene 10 intent_core: {summary} -> "
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
