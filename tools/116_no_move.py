#!/usr/bin/env python3
"""116 no-move probe: does the pass move a single origin on the five grammars?

Read-only.  Runs the five preview generators in a subprocess with
``sitecustomize`` on ``PYTHONPATH`` and, for every ``_place`` call, compares the
origins the pass produced with the origins the same rung produced with the pass
switched off.

This is the **structural** reason the 83 shipped previews are byte-identical,
and it is the assertion the batch should be judged on rather than a proxy: a
placement may legitimately carry a relation violation (088's ``near(D1, CN1)``
and 098's ``near(C1, U1)`` both do — the compile refuses them later, at the
readability gate), so "no accepted placement carries a violation" is not a true
statement about these circuits. "The pass moves nothing" is.

    .venv/Scripts/python.exe tools/116_no_move.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
SCRATCH = ROOT / "outputs" / "116"
TOOLS = ("053b_previews", "056_previews", "088_previews", "088b_previews",
         "098_previews")

INSTRUMENT = '''\
import atexit, json, os, sys
sys.path.insert(0, %(src)r)
sys.path.insert(0, %(tests)r)
from boardwise.engines import drawcompiler as dc

RECORD = os.environ["NO_MOVE_PROBE"]
TOOL = os.environ.get("NO_MOVE_TOOL", "?")
ROWS = []

_real_place = dc._place
_real_pass = dc._honour_bound_orders


def _place(ctx, variant):
    """Place the rung twice — pass on, pass off — and record the difference."""
    held = getattr(ctx, "_order_baseline", None)
    saved = _real_pass
    dc._honour_bound_orders = lambda *a, **k: None
    try:
        if held is not None:
            delattr(ctx, "_order_baseline")
        bare, bare_failure = _real_place(ctx, variant)
    finally:
        dc._honour_bound_orders = saved
    bare_origins = dict(bare.origins) if bare is not None else None

    if held is not None:
        setattr(ctx, "_order_baseline", held)
    helped, helped_failure = _real_place(ctx, variant)

    moved = []
    if bare_origins is not None and helped is not None:
        for part_id in sorted(bare_origins):
            if bare_origins[part_id] != helped.origins.get(part_id):
                moved.append([part_id, bare_origins[part_id],
                              list(helped.origins[part_id])])
    ROWS.append({
        "variant": variant.label,
        "moved": moved,
        "refused": helped_failure is not None or bare_failure is not None,
    })
    return helped, helped_failure


dc._place = _place


@atexit.register
def _drain():
    with open(RECORD, "w", encoding="utf-8") as handle:
        json.dump(ROWS, handle, ensure_ascii=False, indent=1)
'''


def main() -> int:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    here = Path(tempfile.mkdtemp(prefix="nomove_", dir=str(SCRATCH)))
    (here / "sitecustomize.py").write_text(
        INSTRUMENT % {"src": str(ROOT / "src"), "tests": str(ROOT / "tests")},
        encoding="utf-8",
    )
    report: dict[str, list] = {}
    for tool in TOOLS:
        record = here / f"{tool}.json"
        env = dict(os.environ)
        env["PYTHONPATH"] = ";".join(
            (str(here), str(ROOT / "src"), str(ROOT / "tests"))
        )
        env["NO_MOVE_PROBE"] = str(record)
        env["NO_MOVE_TOOL"] = tool
        result = subprocess.run(
            [str(PY), str(ROOT / "tools" / f"{tool}.py"), str(here / tool)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT, env=env,
        )
        if result.returncode != 0 or not record.is_file():
            sys.stderr.write(f"{tool} failed\n" + result.stdout[-2000:]
                             + result.stderr[-3000:])
            return 1
        report[tool] = json.loads(record.read_text(encoding="utf-8"))
    (SCRATCH / "no_move.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    total = moved = 0
    for tool, rows in sorted(report.items()):
        for row in rows:
            total += 1
            if row["moved"]:
                moved += 1
                print(f"MOVED {tool} {row['variant']}: {row['moved']}")
    print(f"{total} placements compared, {moved} with a moved origin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
