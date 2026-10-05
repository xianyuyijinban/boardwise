#!/usr/bin/env python3
"""117 byte gate: 83 previews + 15 boards, **two separate scratch trees**.

    .venv/Scripts/python.exe tools/117_zero_move.py previews <out.sha256> <scratch>
    .venv/Scripts/python.exe tools/117_zero_move.py boards   <out.txt> <scratch>

Same method as 114/115/116's tool (hash the *regenerated* products, not the
checked-in ones), with one fix this batch had to make: **the scratch directory
is a parameter, not a constant.**

`tools/116_zero_move.py` hardcodes ``SCRATCH = outputs/116/previews``, so every
invocation overwrites the same tree. That is fine for "did anything change?"
against a *recorded* baseline, and useless for an A/B — the two runs share one
directory, so a stale file left by an earlier run is compared against itself.
This was not hypothetical: 116's own `§五` records that its after-set carried
four `098` cand2 files that the final code does not produce, and this batch's
first A/B run "found" 4 moved previews that were 116's stale leftovers, not a
real regression. Measured and re-measured against a fresh tree, the same code
moves nothing. Two directories, always.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"

PREVIEW_TOOLS = (
    ("053b", ROOT / "tools" / "053b_previews.py"),
    ("056", ROOT / "tools" / "056_previews.py"),
    ("088", ROOT / "tools" / "088_previews.py"),
    ("088b", ROOT / "tools" / "088b_previews.py"),
    ("098", ROOT / "tools" / "098_previews.py"),
)

BOARDS = (
    ROOT / "tests" / "fixtures" / "DCDC-12V9V转5V3V3_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "FPC触屏游戏机_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "ProPrj_CH340G_2026-09-13.epro2",
    ROOT / "tests" / "fixtures" / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
    ROOT / "tests" / "fixtures" / "ProPrj_智能药箱_2026-09-17.epro2",
    ROOT / "tests" / "fixtures" / "ProPrj_毕设FOC驱动板_2026-09-17.epro2",
    ROOT / "tests" / "fixtures" / "ProPrj_高速电机控制器_2026-09-16.epro2",
    ROOT / "tests" / "fixtures" / "ch340_golden.epro2",
    ROOT / "tests" / "fixtures" / "llc_board.epro2",
    ROOT / "tests" / "fixtures" / "毕设滤波采样_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "级联多电平-主拓扑_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "级联多电平-驱动模块_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "超声波_2026-09-27.epro2",
    ROOT / "tests" / "fixtures" / "CH340G.eprj2",
    ROOT / "tests" / "fixtures" / "eprj3_synth" / "eprj3_synth.eprj3",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def previews(scratch: Path) -> str:
    lines: list[str] = []
    for family, tool in PREVIEW_TOOLS:
        out = scratch / family
        out.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(PY), str(tool), str(out)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout + result.stderr)
            raise SystemExit(result.returncode)
        for file in sorted(out.rglob("*")):
            if file.is_file():
                lines.append(f"{_sha(file)} *{file.relative_to(scratch).as_posix()}")
    return "\n".join(lines) + "\n"


def boards(scratch: Path) -> str:
    lines: list[str] = []
    for board in BOARDS:
        report = scratch / "boards" / f"{board.stem}.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(PY), "-m", "boardwise.cli", "review", str(board),
             "--json", str(report)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT,
        )
        counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
        if report.is_file():
            payload = json.loads(report.read_text(encoding="utf-8"))
            findings = payload.get("findings") or []
            summary = payload.get("summary") or {}
            for level in counts:
                counts[level] = int(summary.get(level, 0))
            measured = json.dumps(
                findings, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        else:
            measured = result.stderr.strip().encode("utf-8")
        digest = hashlib.sha256(measured).hexdigest()[:12]
        lines.append(
            f"== {board.relative_to(ROOT)}: exit={result.returncode} "
            f"E={counts['ERROR']} W={counts['WARN']} I={counts['INFO']} "
            f"findingsha={digest}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.stderr.write(
            "usage: 117_zero_move.py {previews|boards} <outfile> <scratch-dir>\n"
        )
        return 2
    which, outfile, scratch = argv[1], Path(argv[2]), Path(argv[3])
    body = {"previews": previews, "boards": boards}[which](scratch)
    outfile.write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
