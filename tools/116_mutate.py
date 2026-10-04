#!/usr/bin/env python3
"""The 116 mutation stand, same shape as 115's (and 114's, 113's, 112's).

    .venv/Scripts/python.exe tools/116_mutate.py <group>

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
TESTS = "tests/test_116_ordinal_consumption.py"

#: The two literal blocks M6 and M7 rewrite, kept out of the table so the
#: find-strings are written once and cannot drift from a reformat.
HEURISTIC_PUSH_FIND = (
    "                heappush(frontier, (\n"
    "                    total + estimate(other), counter, other, direction, total))"
)
HEURISTIC_BODY_FIND = (
    "            return float(\n"
    "                abs(node[0] - nearest[0]) + abs(node[1] - nearest[1])\n"
    "            )"
)
HEURISTIC_BODY_REPLACE = (
    "            return float(\n"
    "                (node[0] - nearest[0]) ** 2 + (node[1] - nearest[1]) ** 2\n"
    "            ) / 10.0"
)


#: ``group -> (target, what it changes, find, replace, the tests)``
GROUPS: dict[str, tuple[Path, str, str, str, tuple[str, ...]]] = {
    "M1": (
        COMPILER,
        "the baseline filter is dropped: the pass then acts on every relation "
        "**this** rung breaks, not only the ones the tightest rung also breaks. "
        "That is the version that rescues three rungs 098 had correctly refused "
        "— 098 goes from 1 candidate to 3 and three of the 83 previews move",
        "        if baseline is not None and (item.kind, item.subject, item.object) not in baseline:\n"
        "            continue\n",
        "",
        (
            f"{TESTS}::test_the_pass_moves_nothing_for_the_five_existing_grammars",
            f"{TESTS}::test_098_scene08_refusal_is_byte_identical_to_the_recorded_baseline",
        ),
    ),
    "M2": (
        COMPILER,
        "the chain no longer counts as immovable: a chain part is treated as a "
        "free side of a pair, so the pass walks a **page spine** off its own "
        "layout to satisfy an order — 114's 'the spine never moves' rule, broken",
        "        if ctx.locked(part_id) is not None or part_id in ctx.chain\n",
        "        if ctx.locked(part_id) is not None\n",
        (
            f"{TESTS}::test_the_chain_spine_is_never_moved_by_the_pass",
            f"{TESTS}::test_a_same_column_between_two_chain_parts_is_left_to_the_poses",
        ),
    ),
    "M3": (
        COMPILER,
        "a ``near`` is trimmed the wrong way round: the walking side is walked "
        "**away** from the reference by exactly the overshoot. The pair ends up "
        "further apart than it started, the round budget runs out, and the "
        "branch string is reported as unsolvable",
        "    sign = -1.0 if mine > theirs else 1.0\n",
        "    sign = 1.0 if mine > theirs else -1.0\n",
        (
            f"{TESTS}::test_a_near_between_two_branches_of_one_string_is_pulled_in",
        ),
    ),
    "M4": (
        COMPILER,
        "the order step takes 115's `_order_wanted` sign instead of the one this "
        "batch derived from the checker itself. The two are opposite on the "
        "**horizontal** kinds (115 only ever had a vertical case), so every "
        "`left-of` / `right-of` is walked the wrong way",
        "    index, sign = _order_asks(item.kind, walking == item.subject)\n"
        "    # An **order** kind is measured between the two **origins**",
        "    index, sign = _order_wanted(item.kind, walking == item.subject)\n"
        "    # An **order** kind is measured between the two **origins**",
        (
            f"{TESTS}::test_a_branch_order_naming_the_other_axis_is_honoured",
            f"{TESTS}::test_no_accepted_pose_says_it_so_the_pass_takes_over",
        ),
    ),
    "M5": (
        COMPILER,
        "the delta measured on the **pin** is written into the **origin** slot, "
        "so a part is moved by its own pad offset instead of by the amount the "
        "checker asked for — the 116 draft's first bug",
        "    delta = measured_wanted - measured_now\n",
        "    delta = measured_wanted\n",
        (
            f"{TESTS}::test_the_step_is_worked_out_on_the_pin_and_applied_to_the_origin",
        ),
    ),
    "M6": (
        ROUTER,
        "the A* heuristic is dropped (back to plain Dijkstra). Still "
        "**correct** — it returns the same cheapest wire and the 83 previews stay "
        "byte-identical — but the flyback page's two long nets take 98s and 39s "
        "each and the page goes back to 173s, over the budget the guard test pins",
        HEURISTIC_PUSH_FIND,
        "                heappush(frontier, (total, counter, other, direction, total))",
        (
            f"{TESTS}::test_the_flyback_page_compiles_within_its_time_budget",
        ),
    ),
    "M7": (
        ROUTER,
        "the heuristic **overestimates** (squared instead of Manhattan), which is "
        "the classic inadmissible-heuristic bug: A* still terminates and still "
        "returns *a* wire, but not the cheapest one — fast and quietly wrong",
        HEURISTIC_BODY_FIND,
        HEURISTIC_BODY_REPLACE,
        (
            f"{TESTS}::test_the_router_still_returns_the_cheapest_wire_not_merely_a_wire",
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
    stage = ROOT / ".tmp116"
    stage.mkdir(exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="116_mut_", dir=str(stage)))
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
        sys.stderr.write("usage: 116_mutate.py <group>\n")
        return 2
    return run(argv[1])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
