#!/usr/bin/env python3
"""The 118 mutation stand, same shape as 117's (and 116/115/114/113/112's).

    .venv/Scripts/python.exe tools/118_mutate.py <group>

Each group names one literal find/replace in one file and the tests that must go
**red** because of it. The stand:

* copies every file it is about to touch with ``shutil.copy2`` (never ``git
  checkout``, never ``sed``),
* records the sha256 of each copy and of the original,
* refuses to run if the find string is absent or not unique — a silent no-op
  mutation proves nothing (113's M3 lesson; 117's M7 was exactly that shape,
  two opposite errors cancelling),
* runs the named tests and asserts they **fail**,
* restores from the copies and asserts the restored bytes equal the originals
  (``cmp``-equivalent) and the sha256s match.

**118 changes no compiler source.**  It replaces two data files —
``flyback_uc3845.library.json`` and ``flyback_uc3845.circuit.json`` — which the
tools rebuild from live measurements.  So the groups here mutate **those data
files**, because that is what the next `draw apply` will read back and what the
tests actually guard.

**The first version of this stand mutated the tools instead, and all seven groups
came back GREEN.**  That was a real gap rather than a quirk of the stand: the
tests read the evidence and the data, never the builders, so editing a builder is
invisible to them.  Keeping the *tools* honest needs a test that imports them;
118 does not have one and the SUMMARY says so instead of implying they are
covered.  The group table below is therefore aimed at the artefacts.

The table lives in ``outputs/118/mutation_groups.json`` rather than inline,
because the find strings are JSON fragments and writing them as Python literals
turns every quote in the data file into an escape problem (118 lost two rounds
to exactly that).
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
LIBRARY = ROOT / "blocklib" / "specs" / "flyback_uc3845.library.json"
SPEC = ROOT / "blocklib" / "specs" / "flyback_uc3845.circuit.json"
TABLE = ROOT / "outputs" / "118" / "mutation_groups.json"

T1 = "tests/test_118_measured_profiles.py"

TARGETS = {"LIBRARY": LIBRARY, "SPEC": SPEC}
#: Everything the stand restores, whatever a group happens to touch.
RESTORE = (LIBRARY, SPEC)


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
    # ``occurrence`` picks which match to rewrite, for a find string several
    # profiles legitimately share.  Without it the stand refuses: mutating "one
    # of four" and calling that targeted is how 118's M4 first came back green.
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
            "mean with occurrence, or this is not a targeted mutation." + chr(10)
        )
        return 2

    before = _sha(target)
    before_bytes = target.read_bytes()
    stage = ROOT / ".tmp118"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="118_mut_", dir=str(stage)))
    backups = {}
    for path in RESTORE:
        backup = scratch / path.name
        shutil.copy2(path, backup)
        backups[path] = (backup, _sha(path), path.read_bytes())
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
        tests = [f"{T1}::{name}" for name in spec["tests"]]
        result = subprocess.run(
            [str(PY), "-m", "pytest", *tests, "-q", "--basetemp=.tmp_pt_mut"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=ROOT,
        )
        tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
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
        for path, (backup, _digest, original) in backups.items():
            shutil.copy2(backup, path)
    after = _sha(target)
    same = target.read_bytes() == before_bytes
    all_same = all(
        path.read_bytes() == original for path, (_b, _d, original) in backups.items()
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
        sys.stderr.write("usage: 118_mutate.py <group>|--list\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
