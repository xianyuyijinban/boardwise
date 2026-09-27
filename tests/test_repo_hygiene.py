"""Repo hygiene as a test: no unapproved project containers tracked (see
tools/check_repo_hygiene.py). A red here means someone committed a real
board — most likely a company board — and it must be scrubbed from
history, not just deleted."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_no_unapproved_project_containers_tracked():
    out = subprocess.run(
        [sys.executable, str(REPO / "tools" / "check_repo_hygiene.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO,
    )
    assert out.returncode == 0, out.stderr


def _load_guard():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_repo_hygiene", REPO / "tools" / "check_repo_hygiene.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_allowlist_matches_current_tracked_containers():
    """The frozen allowlist neither rots (lists a deleted file) nor drifts
    (a container sneaks in unlisted) — both directions are checked."""
    guard = _load_guard()

    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, cwd=REPO
    )
    tracked = {
        p
        for p in out.stdout.decode("utf-8").split("\0")
        if p and guard._CONTAINER_RE.search(p)
    }
    assert guard.ALLOWLIST == tracked, (
        f"allowlist drift: only-in-allowlist={sorted(guard.ALLOWLIST - tracked)}, "
        f"only-tracked={sorted(tracked - guard.ALLOWLIST)}"
    )


def test_a_v4_sheet_file_trips_the_guard():
    """`.esch2` is a project container even though `esch` is followed by a digit.

    The pattern's `(/|$)` anchor used to make every V4 sheet file invisible to
    this guard (047): `P1.esch2` matched neither `esch` (a digit follows) nor
    anything else, so a company V4 sheet could have entered the repo with the
    guard reporting clean. A file nobody has approved must be an offence.
    """
    guard = _load_guard()

    assert guard.violations(["some/company/board/P1.esch2"]) == [
        "some/company/board/P1.esch2"
    ]
    assert guard.violations(["tests/fixtures/foo.ESCH2"]) == [
        "tests/fixtures/foo.ESCH2"
    ]
    # A folder-format project is caught through the same regex (the `.eprj3`
    # index names the directory), so the sheet inside it cannot slip past.
    assert guard.violations(["proj/ProPrj.eprj3", "proj/sch/P1.esch2"]) == [
        "proj/ProPrj.eprj3",
        "proj/sch/P1.esch2",
    ]


def test_a_temporary_copy_of_a_sheet_file_does_not_trip_the_guard():
    """`foo.esch2.tmp` is not the container the pattern is about.

    The anchor is what keeps the guard from swallowing every file that merely
    starts with a container's name — `bar.epro2.tmp` and `bar.esch2.bak` are
    ordinary files (and `.tmp_*` scratch trees full of them are the normal
    working state of this repo).
    """
    guard = _load_guard()

    assert guard.violations(["foo/bar.esch2.tmp"]) == []
    assert guard.violations(["foo/bar.esch2.bak", "foo/bar.epro2.txt"]) == []
    # A file that merely *contains* the name is not the name either.
    assert guard.violations(["docs/esch2-format-notes.md"]) == []
