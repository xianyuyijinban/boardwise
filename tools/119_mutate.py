#!/usr/bin/env python3
"""The 119 mutation stand, same shape as 118's (and 117/116/115/114's).

    .venv/Scripts/python.exe tools/119_mutate.py <group>
    .venv/Scripts/python.exe tools/119_mutate.py --list

**119 changes compiler source**, so unlike 118 its groups aim at
``src/boardwise/engines/drawcompiler.py`` as well as at the data files.  That is
the point: 119's whole claim lives in one predicate, and a stand that only
mutated JSON could not tell whether any test is watching it.

The stand, unchanged from 118's, and for the same reasons:

* ``shutil.copy2`` for every file a group may touch (never ``git checkout``,
  never ``sed``),
* sha256 of the original and of the copy, restored bytes compared against the
  original **bytes** as well as the digest,
* a group whose find string is absent, or present more than once without an
  ``occurrence``, **exits 2** — a mutation off the executed path proves nothing
  (113's M3), and mutating "one of N" while calling it targeted is how 118's M4
  first came back green.

**The group table lives in ``outputs/119/mutation_groups.json``** for 118's
reason: the data-file find strings are JSON fragments, and writing them as
Python literals turns every quote into an escape problem.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
COMPILER = ROOT / "src" / "boardwise" / "engines" / "drawcompiler.py"
LIBRARY = ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json"
SPEC = ROOT / "blocklib" / "specs" / "flyback_uc3845.circuit.json"
TABLE = ROOT / "outputs" / "119" / "mutation_groups.json"

T118 = "tests/test_118_measured_profiles.py"
T119 = "tests/test_119_pose_ladder_widening.py"
T113 = "tests/test_113_flyback_grammar.py"

TARGETS = {
    "COMPILER": COMPILER, "LIBRARY": LIBRARY, "SPEC": SPEC,
}
#: Everything the stand restores, whatever a group happens to touch.
RESTORE = (COMPILER, LIBRARY, SPEC)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_groups() -> dict:
    return json.loads(TABLE.read_text(encoding="utf-8"))


def run(group: str) -> int:
    groups = load_groups()
    if group not in groups:
        sys.stderr.write(f"unknown group {group!r}; have {sorted(groups)}\n")
        return 2
    spec = groups[group]
    target = TARGETS[spec["target"]]
    find, replace = spec["find"], spec["replace"]
    source = target.read_text(encoding="utf-8")
    count = source.count(find)
    if count < 1:
        sys.stderr.write(
            f"{group}: the find string does not appear. A mutation off the "
            "executed path proves nothing (113's M3 lesson)." + chr(10)
        )
        return 2
    which = spec.get("occurrence", 1)
    if which < 1 or which > count:
        sys.stderr.write(
            f"{group}: occurrence {which} asked for, the find string appears "
            f"{count} time(s)." + chr(10)
        )
        return 2
    if count > 1 and "occurrence" not in spec:
        sys.stderr.write(
            f"{group}: the find string appears {count} times; name the one you "
            f"mean with occurrence, or this is not a targeted mutation." + chr(10)
        )
        return 2

    before = _sha(target)
    before_bytes = target.read_bytes()
    stage = ROOT / ".tmp119"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="119_mut_", dir=str(stage)))
    backups = {}
    for path in RESTORE:
        backup = scratch / path.name
        shutil.copy2(path, backup)
        backups[path] = _sha(path), path.read_bytes()
    print(f"{group}: {spec['what']}")
    print(f"  file    {target.relative_to(ROOT).as_posix()}")
    print(f"  before  sha256 {before}")
    try:
        head, _, tail = source.partition(find)
        rebuilt = head + replace + tail
        for _ in range(which - 1):
            head, _, tail = tail.partition(find)
            rebuilt = head + replace + tail
        target.write_text(rebuilt, encoding="utf-8", newline="")
        mutated = _sha(target)
        print(f"  mutated sha256 {mutated}")
        if mutated == before:
            sys.stderr.write(f"{group}: the mutation changed nothing\n")
            return 1
        # ``spec["tests"]`` entries are already full node ids (``file::test``);
        # they are passed through untouched.  A first version re-split and
        # re-joined them through a generator expression, which pytest answered
        # with "no tests ran" — and a harness that reports that as RED has
        # certified a mutation that proved nothing.  Hence the explicit check
        # below: **no tests ran is a harness failure, never a caught mutation.**
        tests = list(spec["tests"])
        for node in tests:
            assert "::" in node, (
                f"{group}: {node!r} is not a ``file::test`` node id"
            )
        result = subprocess.run(
            [str(PY), "-m", "pytest", *tests, "-q", "--basetemp=.tmp_pt_mut"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT,
        )
        tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
        if "no tests ran" in (result.stdout or ""):
            sys.stderr.write(
                f"{group}: pytest ran NO tests. That is a broken node id, not a "
                f"caught mutation, and reporting it as RED would certify "
                f"nothing." + chr(10) + tail[0] + chr(10)
            )
            return 2
        if result.returncode == 0:
            sys.stderr.write(
                f"{group}: the tests stayed GREEN - the mutation is not on the "
                f"executed path.\n{tail[0]}\n"
            )
            return 1
        red = [
            line for line in (result.stdout or "").splitlines()
            if line.startswith("FAILED") or " failed" in line
        ]
        print(f"  tests went RED ({tail[0]})")
        for line in red[:6]:
            print(f"    {line}")
    finally:
        for path, (_digest, original) in backups.items():
            backup = scratch / path.name
            shutil.copy2(backup, path)
    after = _sha(target)
    same = target.read_bytes() == before_bytes
    all_same = all(
        path.read_bytes() == original for path, (_d, original) in backups.items()
    )
    print(f"  after   sha256 {after}")
    print(f"  restored byte-identical: {same} (every data file: {all_same})")
    if after != before or not same or not all_same:
        sys.stderr.write(f"{group}: the restore did not reproduce the file\n")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[1] == "--list":
        for name, spec in sorted(load_groups().items()):
            print(f"{name}  {spec['target']:<9} {spec['what'][:80]}")
        return 0
    if len(argv) != 2:
        sys.stderr.write("usage: 119_mutate.py <group>|--list\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
