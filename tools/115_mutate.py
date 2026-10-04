#!/usr/bin/env python3
"""The 115 mutation stand, same shape as 114's (and 113's, 112's).

    .venv/Scripts/python.exe tools/115_mutate.py <group>

Each group names one literal find/replace in one source file and the tests that
must go **red** because of it. The stand:

* copies the file with ``shutil.copy2`` (never ``git checkout``, never ``sed``),
* records the sha256 of the copy and of the original,
* refuses to run if the find string is absent or not unique — a silent no-op
  mutation proves nothing (113's M3 lesson),
* runs the named tests and asserts they **fail**,
* restores from the copy and asserts the restored bytes equal the original
  (``cmp``-equivalent) and the sha256 matches.

Exit 0 when the group behaved as declared, 1 otherwise, 2 on a broken stand.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
COMPILER = ROOT / "src" / "boardwise" / "engines" / "drawcompiler.py"
READABILITY = ROOT / "src" / "boardwise" / "engines" / "readability.py"
TESTS = "tests/test_115_flyback_page.py"
FB_TESTS = "tests/test_113_flyback_grammar.py"

#: ``group -> (target, what it changes, find, replace, the tests)``
GROUPS: dict[str, tuple[Path, str, str, str, tuple[str, ...]]] = {
    "M1": (
        COMPILER,
        "the gate is removed: the criterion asks no longer whether the owner's "
        "symbol has a legal pose that already says the order, and overrides "
        "every variant whose pose the ladder has not yet exhausted — 098 scene "
        "08's exact regression, where pose-variant=1 mirrors U1 and every pad "
        "faces the wrong way",
        "        if _a_pose_says(ctx, slot, token, wanted):\n"
        "            continue\n",
        "        if False:\n"
        "            continue\n",
        (
            f"{TESTS}::test_the_criterion_is_conservative_when_another_pose_would_say_it",
        ),
    ),
    "M2": (
        COMPILER,
        "_a_pose_says asks only about the **first** accepted pose rather than all "
        "of them, so a symbol whose later poses would say the order is "
        "overridden anyway — the same 098 scene 08 regression reached through "
        "the pose set instead of through the sign",
        "    for pose in ctx.accepted.get(slot.owner, ()):",
        "    for pose in ctx.accepted.get(slot.owner, ())[:1]:",
        (
            f"{TESTS}::test_the_criterion_is_conservative_when_another_pose_would_say_it",
        ),
    ),
    "M3": (
        READABILITY,
        "the one ruler stops falling back to the pin's **name**, so a spec that "
        "names a pad by its symbol name (`D1.A` on a symbol numbered `1`/`2`) "
        "is once again reported as \"a pin the symbol has not got\" — 115-②'s "
        "own root cause",
        "    pin = profile.pin(token)\n"
        "    if pin is not None:\n"
        "        return str(pin.number)\n"
        "    for candidate in profile.pins:\n"
        "        if candidate.name == token:\n"
        "            return str(candidate.number)\n"
        "    return token",
        "    pin = profile.pin(token)\n"
        "    if pin is not None:\n"
        "        return str(pin.number)\n"
        "    return token",
        (
            f"{TESTS}::test_the_one_ruler_resolves_a_name_token_to_the_profiles_number",
            f"{TESTS}::test_a_name_spelled_member_of_a_shared_net_stops_being_unmentioned",
        ),
    ),
    "M4": (
        READABILITY,
        "constraint 9 looks the pad up under the spec's own token instead of the "
        "ruler's, so `required-pin-not-connected` fires on a name-spelled member "
        "whose pad is drawn",
        "            key = f\"{part_id}."
        "{_profile_pin_ruler(_profile_of(circuit_spec, profile_map, pin), token)}\"",
        "            key = f\"{part_id}.{token}\"",
        (
            f"{TESTS}::test_a_spec_naming_pins_by_name_gets_no_false_required_pin_finding",
        ),
    ),
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(group: str) -> int:
    if group not in GROUPS:
        sys.stderr.write(f"unknown group {group!r}; have {sorted(GROUPS)}\n")
        return 2
    target, what, find, replace, tests = GROUPS[group]
    source = target.read_text(encoding="utf-8")
    count = source.count(find)
    if count != 1:
        sys.stderr.write(
            f"{group}: the find string appears {count} times, expected exactly 1. "
            "A mutation off the executed path proves nothing (113's M3 lesson).\n"
        )
        return 2

    before = _sha(target)
    before_bytes = target.read_bytes()
    # The scratch lives **inside the tree** rather than in %TEMP%: the mutated
    # source is imported from `src/`, so the backup has to sit on the same
    # volume for the copy-and-restore to be a real byte-level round trip.
    stage = ROOT / ".tmp115"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="115_mut_", dir=str(stage)))
    backup = scratch / target.name
    shutil.copy2(target, backup)
    print(f"{group}: {what}")
    print(f"  file    {target.relative_to(ROOT).as_posix()}")
    print(f"  backup  sha256 {_sha(backup)}")
    print(f"  before  sha256 {before}")
    try:
        target.write_text(
            source.replace(find, replace, 1), encoding="utf-8", newline=""
        )
        mutated = _sha(target)
        print(f"  mutated sha256 {mutated}")
        if mutated == before:
            sys.stderr.write(f"{group}: the mutation changed nothing\n")
            return 1
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
        shutil.copy2(backup, target)
    after = _sha(target)
    same = target.read_bytes() == before_bytes
    print(f"  after   sha256 {after}")
    print(f"  restored byte-identical: {same}")
    if after != before or not same:
        sys.stderr.write(f"{group}: the restore did not reproduce the file\n")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: 115_mutate.py <group>\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))