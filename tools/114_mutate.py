#!/usr/bin/env python3
"""The 114 mutation stand, same shape as 113's (and 112's).

    .venv/Scripts/python.exe tools/114_mutate.py <group>

Each group names one literal find/replace in one source file and the tests that
must go **red** because of it. The stand:

* copies the file with ``shutil.copy2`` (never ``git checkout``, never ``sed``),
* records the sha256 of the copy and of the original,
* refuses to run if the find string is absent or not unique — a silent no-op
  mutation proves nothing, which is 113's M3 lesson: that one's first version
  changed a fallback branch no input ever reaches and the tests stayed green,
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
TARGET = ROOT / "src" / "boardwise" / "engines" / "drawcompiler.py"
TESTS = "tests/test_114_compiler_islands.py"
FB_TESTS = "tests/test_113_flyback_grammar.py"

#: ``group -> (what it changes, find, replace, the tests)``
GROUPS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "M1": (
        "the ownership fixed point's second pass stops at the first answer: a "
        "branch that a **branch peer** claims on a node of its own keeps the "
        "chain part it happened to share a ground with, so the flyback's aux "
        "reservoir stays on the transformer instead of moving under its own "
        "rectifier",
        "            better.sort(key=lambda name: (ranks.get(name, 0), name))\n"
        "            if current == better[0]:\n"
        "                continue\n"
        "            links[part_id] = better[0]\n"
        "            owner[part_id] = owner[better[0]]",
        "            better.sort(key=lambda name: (ranks.get(name, 0), name))\n"
        "            if current == better[0]:\n"
        "                continue\n"
        "            if current and current in chain_ids:\n"
        "                continue\n"
        "            links[part_id] = better[0]\n"
        "            owner[part_id] = owner[better[0]]",
        (
            f"{TESTS}::test_the_flyback_page_no_longer_refuses_either_of_the_two_gaps",
            f"{TESTS}::test_a_series_string_arm_is_owned_through_the_arm_that_reaches_the_chain",
        ),
    ),
    "M2": (
        "an unanchored arm of a ring is given a blanket owner instead of being "
        "refused, so a closed string is silently attached to the chain",
        '            if here:\n'
        '                strings[part_id] = ",".join(sorted(here))\n'
        '    return owner, links, strings',
        '            if here:\n'
        '                strings[part_id] = ",".join(sorted(here))\n'
        '        if part_id not in owner and chain_ids:\n'
        '            owner[part_id] = chain_ids[0]\n'
        '            links[part_id] = chain_ids[0]\n'
        '    return owner, links, strings',
        (
            f"{TESTS}::test_a_string_that_reaches_no_chain_is_refused_and_names_the_link",
            f"{TESTS}::test_the_string_refusal_words_name_the_net_and_offer_an_action",
        ),
    ),
    "M3": (
        "the lane relaxation walks the group's edges in **grammar** order "
        "instead of putting the edges that touch a chain or locked part first, so "
        "a branch settles itself onto a row and is then dragged off it again by "
        "the edge the chain already placed (the flyback: the U5-U4 edge and the "
        "R7-U4 edge trade places)",
        "        for here, there, shared in fixed_edges + free_edges:",
        "        for here, there, shared in edges:",
        (
            f"{FB_TESTS}::test_the_layout_stage_no_longer_refuses_the_feedback_row",
        ),
    ),
    "M4": (
        "the foreign-pin dodge falls back to a per-part net check, so the "
        "owner's own other pins stop counting as foreign and the aux run walks "
        "across the transformer's ground pin again",
        '            if (pins_of.get(pin.number) or pins_of.get(pin.name, "")) '
        'in own:\n'
        '                continue',
        "            if set(pins_of.values()) & own:\n"
        "                continue",
        (f"{TESTS}::test_a_branch_nudges_its_root_clear_of_a_foreign_pin_on_the_run",),
    ),
    "M5": (
        "the unordered chain parking keeps the part on the spine's own axial "
        "position instead of taking its `near` partner's, which is what put the "
        "flyback's secondary rectifier at the head of the chain with its winding "
        "pin facing back into the transformer",
        "        shifted[axial] = origins[partner][axial]",
        "        shifted[axial] = origins[part_id][axial]",
        (
            f"{TESTS}::test_an_unordered_chain_part_is_parked_beside_its_near_partner",
        ),
    ),

}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(group: str) -> int:
    if group not in GROUPS:
        sys.stderr.write(f"unknown group {group!r}; have {sorted(GROUPS)}\n")
        return 2
    what, find, replace, tests = GROUPS[group]
    source = TARGET.read_text(encoding="utf-8")
    count = source.count(find)
    if count != 1:
        sys.stderr.write(
            f"{group}: the find string appears {count} times, expected exactly 1. "
            "A mutation off the executed path proves nothing (113's M3 lesson).\n"
        )
        return 2

    before = _sha(TARGET)
    before_bytes = TARGET.read_bytes()
    # The scratch lives **inside the tree** rather than in %TEMP%: the mutated
    # source is imported from `src/`, so the backup has to sit on the same
    # volume for the copy-and-restore to be a real byte-level round trip.
    stage = ROOT / ".tmp114"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="114_mut_", dir=str(stage)))
    backup = scratch / TARGET.name
    shutil.copy2(TARGET, backup)
    print(f"{group}: {what}")
    print(f"  backup  sha256 {_sha(backup)}")
    print(f"  before  sha256 {before}")
    try:
        TARGET.write_text(
            source.replace(find, replace, 1), encoding="utf-8", newline=""
        )
        mutated = _sha(TARGET)
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
        print(f"  tests went RED ({tail[0]})")
    finally:
        shutil.copy2(backup, TARGET)
        shutil.rmtree(scratch, ignore_errors=True)
    after = _sha(TARGET)
    same = TARGET.read_bytes() == before_bytes
    print(f"  after   sha256 {after}")
    print(f"  restored byte-identical: {same}")
    if after != before or not same:
        sys.stderr.write(f"{group}: the restore did not reproduce the file\n")
        return 1
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: 114_mutate.py <group>\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
