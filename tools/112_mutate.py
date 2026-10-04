#!/usr/bin/env python3
"""Mutation harness for 112: edit one line, run the named tests, restore, verify.

    .venv/Scripts/python.exe tools/112_mutate.py M1
    .venv/Scripts/python.exe tools/112_mutate.py --list

Each mutation is declared below as (id, file, find, replace, tests). The harness
copies the file to ``outputs/112/mut/<id>/``, records the sha256 of the original,
applies the literal find→replace (a missing ``find`` is a hard error — never a
silent no-op), runs the named tests (which must go RED), then restores the file
from the copy and re-checks the sha256 matches. No git, no sed.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
MUTDIR = ROOT / "outputs" / "112" / "mut"

ROUTER = "src/boardwise/engines/router.py"
ADDCOMP = "src/boardwise/engines/addcomponent.py"

MUTATIONS = [
    (
        "M1", ROUTER,
        # Drop the interior-clip test: a step that cuts a body would be accepted.
        "        for box in self.boxes:\n            if _segment_hits_box(start, end, box):\n                return False",
        "        for box in self.boxes:\n            if False:\n                return False",
        "tests/test_112_obstacle_routing.py tests/test_053b_drawcompiler.py",
    ),
    (
        "M2", ROUTER,
        # A foreign pin tip / wire vertex stops being a wall: only body boxes
        # are consulted, so a wire will happily run its vertex onto another
        # net's vertex — which the editor joins into a short.
        "        if _key(point) in self.blocked:\n            return True",
        "        if False:\n            return True",
        "tests/test_112_obstacle_routing.py",
    ),
    (
        "M3", ADDCOMP,
        # The honest-failure half removed: no clean path falls back to the old L.
        "    if avoid is None or avoid.empty:",
        "    if True:",
        "tests/test_112_obstacle_routing.py",
    ),
    (
        "M4", ADDCOMP,
        # A wall is no longer a reason to return None — the straight/L answer is
        # returned whatever the field says (the "silent press-through" the batch
        # exists to remove).
        "    path = lattice.route(anchor, goal_point, targets=[goal_point])\n    if path is None:\n        return None",
        "    path = lattice.route(anchor, goal_point, targets=[goal_point])\n    if path is None:\n        return [(ax, ay), (ax, ty), (tx, ty)]",
        "tests/test_112_obstacle_routing.py",
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_mutation(mid: str, rel: str, find: str, replace: str, tests: str) -> int:
    target = ROOT / rel
    before = sha(target)
    out = MUTDIR / mid
    out.mkdir(parents=True, exist_ok=True)
    backup = out / Path(rel).name
    shutil.copy2(target, backup)
    (out / "sha_before.txt").write_text(f"{before}  {rel}\n", encoding="utf-8")

    text = target.read_text(encoding="utf-8")
    if find not in text:
        print(f"[{mid}] FATAL: find-string not present in {rel} — no-op refused")
        shutil.copy2(backup, target)
        return 3
    target.write_text(text.replace(find, replace, 1), encoding="utf-8", newline="")
    print(f"[{mid}] applied to {rel}")

    result = subprocess.run(
        [str(PY), "-m", "pytest", *tests.split(), "-q", "--basetemp=.tmp_mut_112"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT,
    )
    tail = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "(no output)"
    red = result.returncode != 0
    print(f"[{mid}] tests: {'RED (expected)' if red else 'GREEN (!! mutation not caught)'} — {tail}")

    # Restore from the copy and verify byte-identity.
    shutil.copy2(backup, target)
    after = sha(target)
    ok = after == before
    (out / "sha_after.txt").write_text(f"{after}  {rel}\n", encoding="utf-8")
    print(f"[{mid}] restored: {after[:16]}… {'MATCHES original' if ok else 'DIFFERS (!!)'}")
    return 0 if (red and ok) else 1


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--list":
        for mid, rel, _f, _r, tests in MUTATIONS:
            print(f"{mid}  {rel}  tests: {tests}")
        return 0
    if len(argv) != 2:
        print("usage: 112_mutate.py <M1|M2|M3> | --list")
        return 2
    for mid, rel, find, replace, tests in MUTATIONS:
        if mid == argv[1]:
            return apply_mutation(mid, rel, find, replace, tests)
    print(f"unknown mutation {argv[1]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
