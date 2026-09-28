#!/usr/bin/env python3
"""Regenerate 056's offline page previews: the eight scenes, as pictures.

    .venv/Scripts/python.exe tools/056_previews.py [output-dir]

writes ``outputs/056_preview/`` (the default; gitignored, because it is a build
product reproducible from the sources) and prints the manifest, one line per file
with its sha256:

* two SVG previews per scene that compiles — the page as the two checkers
  measured it, with the page, the keep-outs, the module frames (and the module each
  frame belongs to), the font-metric text boxes and the raw page metrics in the
  caption;
* the best candidate's **page document** as JSON (``*_page.json``) for the same
  scene: the module origins, frames and ports 057 consumes, in the shape
  `core/pagelayoutplan.py` defines;
* a refusal report per scene that does not compile — the four-category failure
  lines, every variant that was built and lost, and each module's own compile
  result. Three of the eight are meant to be refused (056 sec.4 scenarios 4-6), so
  their reports are the artefact.

**The scenario definitions live in exactly one place**: the CircuitSpec /
PresentationSpec / budget constructions are
:func:`tests.test_056_pagecompiler.scenes`, the module whose tests pin them against
the task book's table. This tool imports that module and never restates them — a
copy would be a second definition of the same page, and the first time the two
disagreed the preview would show a circuit no test ever compiled. ``tests/`` is not
a package, so the module is reached by putting both ``src/`` and ``tests/`` on
``sys.path`` (what ``tests/conftest.py`` does for pytest).

Determinism is a contract here, not a hope: the page compiler is deterministic and
:func:`boardwise.engines.svgpreview.render_svg` is a pure function of the plan, so
**two runs over one revision are byte-identical**. The digests below are printed
for exactly that check — run it twice and compare. Nothing in this tool depends on
the clock, the environment or the order of a set.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_056_pagecompiler as scenarios  # noqa: E402  (the scenario owner)
from boardwise.engines import svgpreview  # noqa: E402

#: Where the previews go by default, how many candidates per scene are drawn (the
#: ranking's own top two — the best page and its runner-up, which is what makes
#: "the ranking did something" visible), and what a previous run may have left
#: behind. Only files matching the pattern are swept: a stray file this tool did
#: not write is left where it is.
DEFAULT_OUT = ROOT / "outputs" / "056_preview"
CANDIDATES = 2
STALE_PATTERN = "056_scene*"

USAGE = "usage: 056_previews.py [output-dir]"


def scene_previews(out: Path, scene) -> tuple[list[Path], str]:
    """One scene -> ``(files written for it, one-line summary)``.

    A scene the compiler refuses is not a failure of this tool: for scenarios 4-6
    that *is* the expected outcome (056 sec.4), and the refusal report is the
    artefact — the categories, the reasons, the actions, every variant that was
    built and lost, and each module's own result.
    """
    result = scenarios.compile_scene(scene)
    if not result.ok:
        target = out / f"056_scene{scene.number:02d}_refused.txt"
        lines = [
            f"056 scene {scene.number}: {scene.title}",
            "refused by the page compiler",
            "",
            result.render_failures(),
            "",
            "modules (each compiled by the single-module pipeline):",
            *[
                f"  {name}: ok={compiled.ok} {compiled.categories()}"
                for name, compiled in result.modules.items()
            ],
            "",
            "variants built and refused:",
            *[
                f"  {item.variant}: {item.reason[:400]}"
                + (f" [{' | '.join(item.violations[:2])}]" if item.violations else "")
                for item in result.rejected
            ],
            "",
            "notes:",
            *[f"  {note}" for note in result.notes],
        ]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [target], f"refused ({', '.join(result.categories())})"
    written: list[Path] = []
    page = result.pages[0]
    written.append(_page_document(
        out / f"056_scene{scene.number:02d}_page.json", scene, result
    ))
    frames = [(module.id, module.frame) for module in page.modules]
    for index, page_plan in enumerate(result.pages[:CANDIDATES], start=1):
        written.append(svgpreview.write_preview(
            out / f"056_scene{scene.number:02d}_cand{index}.svg",
            page_plan.plan,
            scenarios.library(),
            page_box=scene.budget.page_box,
            keepouts=scene.budget.keepouts,
            frames=[(module.id, module.frame) for module in page_plan.modules],
            title=(f"056 scene {scene.number}: {scene.title} — candidate {index} "
                   f"({result.ranked[index - 1].describe_key()})"),
        ))
    del frames
    return written, f"drawn ({len(result.pages)} candidate(s))"


def _page_document(path: Path, scene, result) -> Path:
    """The best candidate's page document, plus a summary of what it says."""
    page = result.pages[0]
    path.write_text(
        json.dumps(page.to_jsonable(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def page_summary(scene, result) -> str:
    """One line per scene for the console: what the page decided, in words."""
    page = result.pages[0]
    modules = ", ".join(
        f"{module.id}@{module.origin[0]:g},{module.origin[1]:g}"
        for module in page.modules
    )
    ports = "; ".join(
        f"{module.id}: " + ", ".join(
            f"{port.net}={port.kind}" for port in module.ports
        )
        for module in page.modules
    )
    return f"frames [{modules}] ports [{ports}]"


def generate(out: Path) -> list[Path]:
    """Write the whole preview set under `out`, this run replacing the last."""
    out.mkdir(parents=True, exist_ok=True)
    for stale in sorted(out.glob(STALE_PATTERN)):
        stale.unlink()
    written: list[Path] = []
    for number, scene in sorted(scenarios.scenes().items()):
        result = scenarios.compile_scene(scene)
        paths, summary = scene_previews(out, scene)
        written.extend(paths)
        print(f"scene {number:2d}: {summary} -> "
              + ", ".join(path.name for path in paths))
        if result.ok:
            print(f"          {page_summary(scene, result)}")
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
