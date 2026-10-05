#!/usr/bin/env python3
"""The 117 mutation stand, same shape as 115's (and 114's, 113's, 112's).

    .venv/Scripts/python.exe tools/117_mutate.py <group>

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
ROUTER = ROOT / "src" / "boardwise" / "engines" / "router.py"
T1 = "tests/test_117_net_merge_root_cause.py"
T2 = "tests/test_117_text_overlap.py"
T3 = "tests/test_117_order_wanted_sign.py"

#: ``group -> (target, what it changes, find, replace, the tests)``
GROUPS: dict[str, tuple[Path, str, str, str, tuple[str, ...]]] = {
    "M1": (
        COMPILER,
        "the dodge stops measuring the stretch past the root, where the branch's "
        "own other pad lands (116's version measured only the leg). C7.2 (PGND) "
        "drops back onto T1.A1 (AUX) and the netlist-partition-mismatch returns",
        "    if trail is not None:\n        far = (root[0] + trail[0], root[1] + trail[1])\n",
        "    if False:\n        far = (root[0] + trail[0], root[1] + trail[1])\n",
        (
            f"{T1}::test_the_trail_past_the_root_carries_no_foreign_pin",
            f"{T1}::test_the_readability_gate_no_longer_reports_a_partition_mismatch",
        ),
    ),
    "M2": (
        COMPILER,
        "the trail is measured from the **anchor** instead of from the root -- "
        "the frame error this batch actually made and caught: they are different "
        "points, so a dodge that moved the branch sideways is measured at a place "
        "it no longer occupies and the blocker is missed",
        "        if _blockers_between(root, far, part_id):\n",
        "        if _blockers_between(anchor, far, part_id):\n",
        (
            f"{T1}::test_the_trail_past_the_root_carries_no_foreign_pin",
            f"{T1}::test_the_trail_is_measured_from_the_root_and_not_from_the_anchor",
        ),
    ),
    "M3": (
        COMPILER,
        "the **label** ladder goes back to one offset per direction (116's "
        "version). The flyback's flag names have no free first rung and fall back "
        "into the collision, and 098's mirrored variants go back to being refused "
        "by texts[2] U1 x labels[0] SIG -- this mutation reproduces the batch's "
        "own byte-gate finding",
        "        for rung in range(1, TEXT_ESCALATION_STEPS + 1):\n"
        "            reach = rung - 1\n"
        "            if candidate_direction[0] != 0.0:\n"
        "                offset = (candidate_direction[0] * half_x * rung, 0.0)\n"
        "            else:\n"
        "                offset = (0.0, candidate_direction[1] * half_y * rung)\n",
        "        for rung in range(1, 2):\n"
        "            if candidate_direction[0] != 0.0:\n"
        "                offset = (candidate_direction[0] * half_x, 0.0)\n"
        "            else:\n"
        "                offset = (0.0, candidate_direction[1] * half_y)\n",
        (
            f"{T2}::test_a_flag_name_never_lands_on_a_part_body",
            f"{T2}::test_117_turns_four_098_previews_because_it_unlocks_refused_variants",
        ),
    ),
    "M4": (
        COMPILER,
        "the **part-text** ladder goes back to one rung per side (116's version), "
        "so the 385-unit EE16_3+3_V02 value falls back onto its own designator D3",
        "        for rung in range(1, TEXT_ESCALATION_STEPS + 1):\n"
        "            for side in TEXT_SIDES:\n",
        "        for rung in range(1, 2):\n"
        "            for side in TEXT_SIDES:\n",
        (
            f"{T2}::test_a_value_text_never_lands_on_another_text_or_flag_name",
        ),
    ),
    "M5": (
        COMPILER,
        "the ladder loses its **bound** (4 -> 64): it becomes search-as-far-as-it- "
        "takes, which is the other disease -- a flag name that has wandered across "
        "the page is electrically right and unreadable",
        "TEXT_ESCALATION_STEPS = 4\n",
        "TEXT_ESCALATION_STEPS = 64\n",
        (
            f"{T2}::test_the_ladder_is_bounded_so_a_flag_cannot_be_flung_off_its_pin",
        ),
    ),
    "M6": (
        COMPILER,
        "the order sign goes back to 116's table in full (both factors put back). "
        "The four kinds stop agreeing with the checker-derived _order_asks",
        "    negative = kind in (LEFT_OF, BELOW)\n"
        "    return index, (1.0 if own else -1.0) * (-1.0 if negative else 1.0)\n",
        "    negative = kind in (LEFT_OF, ABOVE)\n"
        "    return index, (-1.0 if own else 1.0) * (-1.0 if negative else 1.0)\n",
        (
            f"{T3}::test_the_order_sign_the_gate_asks_of_a_subject_is_the_one_taken",
            f"{T3}::test_the_two_sides_agree_with_the_gate_on_every_kind",
        ),
    ),
    "M7": (
        COMPILER,
        "only the **own** factor is put back (the sign table stays 117's), so "
        "the *other* end of every pair is asked the wrong way. This is the half "
        "116 never noticed either: a branch that is the **object** of its "
        "owner's relation now gets the subject's direction",
        "    return index, (1.0 if own else -1.0) * (-1.0 if negative else 1.0)\n",
        "    return index, (1.0 if own else 1.0) * (-1.0 if negative else 1.0)\n",
        (
            f"{T3}::test_the_two_sides_agree_with_the_gate_on_every_kind",
            f"{T3}::test_the_object_end_is_the_mirror_of_the_subject_end",
        ),
    ),
    "M8": (
        COMPILER,
        "the trail walk is allowed to run **unbounded** (the reach check is "
        "dropped), so a branch that cannot be cleared is parked arbitrarily far "
        "from what it hangs off instead of being left where it is and reported",
        "            walked = 0.0\n            while walked <= reach + step:\n",
        "            walked = 0.0\n            while walked <= 1e9:\n",
        (
            f"{T1}::test_the_trail_past_the_root_carries_no_foreign_pin",
            f"{T1}::test_the_trail_walk_is_bounded_by_the_parts_own_reach",
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
    stage = ROOT / ".tmp117"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="117_mut_", dir=str(stage)))
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
        sys.stderr.write("usage: 117_mutate.py <group>\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
