#!/usr/bin/env python3
"""The 114 zero-move gate, one half of it: 83 previews + 15 fixture containers.

    .venv/Scripts/python.exe tools/114_zero_move.py previews <out.sha256>
    .venv/Scripts/python.exe tools/114_zero_move.py boards   <out.txt>

Both halves are read-only and offline. ``previews`` re-runs the five preview
generators into scratch directories under ``outputs/114/`` and prints the sha256
of every file they produced — 111's §五/§六 method, which hashes the
*regenerated* products rather than the checked-in ones (a checked-in file that
was never regenerated would pass this gate by not existing).

``boards`` runs the offline review over the fifteen fixture containers (13
.epro2 + CH340G.eprj2 + eprj3_synth), records exit + E/W/I counts + a sha256
of the findings list per board, so two runs can be diffed line by line.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SCRATCH = ROOT / "outputs" / "114" / "previews"

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


def previews() -> str:
    lines: list[str] = []
    for family, tool in PREVIEW_TOOLS:
        out = SCRATCH / family
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
                lines.append(f"{_sha(file)} *{file.relative_to(ROOT).as_posix()}")
    return "\n".join(lines) + "\n"


def boards() -> str:
    lines: list[str] = []
    for board in BOARDS:
        report = SCRATCH / "boards" / f"{board.stem}.json"
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
            # No report was written (an input the offline reader refuses by
            # extension, `CH340G.eprj2`). The refusal text is the whole
            # reading here, so it is what gets hashed — otherwise this board
            # would read "-" twice and a change in the message would be
            # invisible to the diff.
            measured = result.stderr.strip().encode("utf-8")
        digest = hashlib.sha256(measured).hexdigest()[:12]
        lines.append(
            f"== {board.relative_to(ROOT)}: exit={result.returncode} "
            f"E={counts['ERROR']} W={counts['WARN']} I={counts['INFO']} "
            f"findingsha={digest}"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: 114_zero_move.py {previews|boards} <outfile>\n")
        return 2
    body = {"previews": previews, "boards": boards}[argv[1]]()
    Path(argv[2]).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
