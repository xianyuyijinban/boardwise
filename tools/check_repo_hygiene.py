#!/usr/bin/env python3
"""Repo hygiene guard: real schematic/PCB project containers never enter the repo.

Real projects (especially **company boards**) are read-only review input. Their
files must stay on the machine they came from — a commit leaks the design into
public history forever (deleting the file afterwards does NOT remove it).

The only project containers allowed tracked are the ones already reviewed and
approved, frozen in :data:`ALLOWLIST` below. Adding a legitimate new fixture
means appending its path to that list **in the same commit**, deliberately —
which is exactly the review moment this guard exists to force.

Usage:
    python tools/check_repo_hygiene.py            # check every tracked file
    python tools/check_repo_hygiene.py --staged   # check staged files (pre-commit)

Exit 0 = clean, 1 = violations found (they are listed on stderr).
"""
from __future__ import annotations

import re
import subprocess
import sys

# Project-container formats this guard watches. `.eprj3` is a *directory*
# (V4 folder format), so the pattern matches any path containing it.
_CONTAINER_RE = re.compile(r"\.(epro2|epro|eprj2|eprj3|epru|esch|epcb)(/|$)", re.IGNORECASE)

# The 22 project containers tracked as of 2026-09-26, each individually
# approved (own teaching/DIY boards + synthetic/golden fixtures). Frozen.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "blocklib/sources/ROBOT_ctrl_FOC.eprj2",
        "blocklib/sources/highspeed_motor_ctrl.eprj2",
        "blocklib/sources/smart_pillbox.eprj2",
        "blocklib/sources/thesis_FOC_board.eprj2",
        "reviewsets/injected/duplicate-designator.epro2",
        "reviewsets/injected/fixed-base.epro2",
        "reviewsets/injected/ldo-no-headroom.epro2",
        "reviewsets/injected/nc-pin-grounded.epro2",
        "reviewsets/injected/overvoltage-rail.epro2",
        "reviewsets/injected/v3-decap-missing.epro2",
        "reviewsets/injected/value-mpn-mismatch.epro2",
        "tests/fixtures/CH340G.eprj2",
        "tests/fixtures/CH340G_backup/CH340G_2026-09-13-18-21.epro2",
        "tests/fixtures/CH340G_backup/CH340G_2026-09-13-20-21.epro2",
        "tests/fixtures/ProPrj_CH340G_2026-09-13.epro2",
        "tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2",
        "tests/fixtures/ch340_golden.epro2",
        "tests/fixtures/eprj3_synth/eprj3_synth.eprj3",
        "tests/fixtures/llc_board.epro2",
        "tools/eprj2-recon/ch340g_decrypted.epru",
        "tools/eprj2-recon/ch340g_final.epru",
        "tools/eprj2-recon/ch340g_merged.epru",
    }
)

_BANNER = (
    "repo hygiene: project container(s) outside the allowlist —\n"
    "  real boards (above all COMPANY boards) must never be committed;\n"
    "  public history keeps them even after deletion. If a file is a\n"
    "  deliberately reviewed new fixture, add its path to ALLOWLIST in\n"
    "  tools/check_repo_hygiene.py in the same commit."
)


def _git(*args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        print(f"repo hygiene: git {' '.join(args)} failed: {out.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def violations(paths: list[str]) -> list[str]:
    return sorted(p for p in paths if _CONTAINER_RE.search(p) and p not in ALLOWLIST)


def main(argv: list[str]) -> int:
    if "--staged" in argv[1:]:
        paths = _git("diff", "--cached", "--name-only", "--diff-filter=ACM")
    else:
        paths = _git("ls-files")
    bad = violations(paths)
    if bad:
        print(_BANNER, file=sys.stderr)
        for p in bad:
            print(f"  OFFENDING: {p}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
