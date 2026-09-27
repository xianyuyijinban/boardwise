#!/usr/bin/env python3
"""Regenerate 053 stage B's offline previews: the twelve scenarios, as pictures.

    .venv/Scripts/python.exe tools/053b_previews.py [output-dir]

writes ``outputs/053b_preview/`` (the default; gitignored, because it is a build
product reproducible from the sources) and prints the manifest, one line per
file with its sha256:

* two SVG previews per scene that compiles — the drawing as the readability
  checker measured it, with the page, the keep-outs, the font-metric text boxes
  and the raw soft metrics in the caption;
* a refusal report per scene that does not compile — the four-category failure
  lines and every variant that was built and lost. Three of the twelve are meant
  to be refused (053 sec.5 scenarios 10-12), so their reports are the artefact.

**The scenario definitions live in exactly one place**: the CircuitSpec /
PresentationSpec / budget constructions are
:func:`tests.test_053b_drawcompiler.scenes`, the module whose tests pin them
against the task book's table. This tool imports that module and never restates
them — a copy would be a second definition of the same drawing, and the first
time the two disagreed the preview would show a circuit no test ever compiled.
``tests/`` is not a package, so the module is reached by putting both ``src/``
and ``tests/`` on ``sys.path`` (what ``tests/conftest.py`` does for pytest).

Determinism is a contract here, not a hope: the compiler is deterministic (053
stage A) and :func:`boardwise.engines.svgpreview.render_svg` is a pure function
of the plan, so **two runs over one revision are byte-identical**. The digests
below are printed for exactly that check — run it twice and compare. Nothing in
this tool depends on the clock, the environment or the order of a set.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import test_053b_drawcompiler as scenarios  # noqa: E402  (the scenario owner)
from boardwise.engines import svgpreview  # noqa: E402

#: Where the previews go by default, how many candidates per scene are drawn
#: (the ranking's own top two — the best plan and its runner-up, which is what
#: makes "the ranking did something" visible on the page), and what a previous
#: run may have left behind. Only files matching the pattern are swept: a stray
#: file this tool did not write is left where it is.
DEFAULT_OUT = ROOT / "outputs" / "053b_preview"
CANDIDATES = 2
STALE_PATTERN = "053b_scene*"

USAGE = "usage: 053b_previews.py [output-dir]"


def scene_previews(out: Path, scene) -> tuple[list[Path], str]:
    """One scene -> ``(files written for it, one-line summary)``.

    A scene the compiler refuses is not a failure of this tool: for scenarios
    10-12 that *is* the expected outcome (053 sec.5), and the refusal report is
    the artefact — the category, the reason, the action and every variant that
    was built and lost.
    """
    result = scenarios.compile_scene(scene)
    if not result.ok:
        target = out / f"053b_scene{scene.number:02d}_refused.txt"
        lines = [
            f"053b scene {scene.number}: {scene.title}",
            "refused by the compiler",
            "",
            result.render_failures(),
            "",
            "variants built and refused:",
            *[f"  {item.variant}: {item.reason[:400]}" for item in result.rejected],
        ]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return [target], f"refused ({', '.join(result.categories())})"
    written: list[Path] = []
    for index, plan in enumerate(result.candidates[:CANDIDATES], start=1):
        written.append(svgpreview.write_preview(
            out / f"053b_scene{scene.number:02d}_cand{index}.svg",
            plan, scenarios.library(),
            page_box=scene.budget.page_box,
            keepouts=scene.budget.keepouts,
            title=(f"053b scene {scene.number}: {scene.title} — candidate {index} "
                   f"({result.ranked[index - 1].describe_key()})"),
        ))
    return written, f"drawn ({len(result.candidates)} candidate(s))"


def generate(out: Path) -> list[Path]:
    """Write the whole preview set under `out`, this run replacing the last."""
    out.mkdir(parents=True, exist_ok=True)
    for stale in sorted(out.glob(STALE_PATTERN)):
        stale.unlink()
    written: list[Path] = []
    for number, scene in sorted(scenarios.scenes().items()):
        paths, summary = scene_previews(out, scene)
        written.extend(paths)
        print(f"scene {number:2d}: {summary} -> "
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
