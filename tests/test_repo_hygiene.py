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
        ["git", "ls-files"], capture_output=True, text=True, encoding="utf-8", cwd=REPO
    )
    tracked = {
        p for p in out.stdout.splitlines() if guard._CONTAINER_RE.search(p)
    }
    assert guard.ALLOWLIST == tracked, (
        f"allowlist drift: only-in-allowlist={sorted(guard.ALLOWLIST - tracked)}, "
        f"only-tracked={sorted(tracked - guard.ALLOWLIST)}"
    )
