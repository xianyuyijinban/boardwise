"""537A · `boardwise doctor` under DeepSeek Harness (dsh): the workspace skill.

The gap this file pins: a dsh session loads the SOP from the **workspace's**
``.agents/skills/boardwise/SKILL.md`` (added for dsh in 536), but `doctor` kept
looking only at the two *user-level* skill directories and told a dsh user to run
``boardwise install-skill`` for Kimi Code / Claude Code — harnesses that have
nothing to do with the session they are in. The measured shape on the reporting
session: 7/10, with two unrelated red skill lines.

The contract (537A):

* a dsh environment (``DSH_SESSION_ID`` or ``DSH_HOME`` present) is judged on the
  workspace copy alone: byte-for-byte against ``resources.skill_md()``;
* ``current`` is green, ``missing`` / ``stale`` / ``unreadable`` are red, and the
  fix names the **workspace** location — never the Kimi/Claude install path;
* one ``skill-dsh`` line, no ``skill-kimi`` / ``skill-claude`` (nine lines in
  total instead of ten, which is the point: an unrelated line is not padded back);
* a non-dsh environment keeps exactly what it has: `skill_install.skill_statuses`
  and its two harness lines, ten checks.

Determinism: the test process itself runs inside a dsh session, so ``DSH_*`` is
stripped for the whole suite by `tests/conftest.py` before any test runs. This
file puts the markers back on purpose, per test, and the legacy cases assert
their absence explicitly rather than trusting the machine.

No daemon and no editor: `run_doctor` is a pure function of a `DoctorProbe`, and
the two end-to-end cases run the real CLI against a free port with the
auto-daemon switch off (157), the flow the reporting session actually used.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import resources, skill_install
from boardwise.cli import (
    DOCTOR_STEP_HINTS,
    EDITOR_INSTALL_ENV,
    run_doctor,
)

#: The healthy-machine probe and the check lookup are test_doctor's — the same
#: fixture the rest of the suite judges `doctor` by (test_069c does the same).
import test_doctor as base

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: The two markers a dsh session exports; either one is enough to say "this run
#: is a dsh session" (a thin launcher may carry only one of them).
DSH_MARKERS = ("DSH_SESSION_ID", "DSH_HOME")


def check(checks, name):
    [found] = [entry for entry in checks if entry.name == name]
    return found


def skill_lines(checks):
    """Every line whose name starts with ``skill`` — the set this batch is about."""
    return [entry.name for entry in checks if entry.name.startswith("skill")]


@pytest.fixture
def dsh_session(monkeypatch):
    """Make this test a dsh session, on purpose and in one place."""
    monkeypatch.setenv("DSH_SESSION_ID", "session-537a1")
    monkeypatch.setenv("DSH_HOME", str(ROOT / ".tmp_537a_dsh_home"))
    return monkeypatch


@pytest.fixture
def legacy_env(monkeypatch):
    """Take the dsh markers away, explicitly: legacy Kimi/Claude behaviour."""
    for name in DSH_MARKERS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def workspace_skill(workspace: Path) -> Path:
    """The path dsh reads the SOP from inside ``workspace``."""
    return workspace / ".agents" / "skills" / "boardwise" / "SKILL.md"


def make_workspace(root: Path, content: bytes | None) -> Path:
    """A workspace whose ``.agents`` skill file is ``content`` (or absent)."""
    path = workspace_skill(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        path.write_bytes(content)
    return path


def bundle_bytes() -> bytes:
    return resources.skill_md().read_bytes()


# --------------------------------------------------------------------------
# 1. which environment am I in? (the detection itself)
# --------------------------------------------------------------------------


def test_either_dsh_marker_is_enough_and_neither_means_legacy(monkeypatch):
    for name in DSH_MARKERS:
        monkeypatch.delenv(name, raising=False)
    assert skill_install.dsh_environment() is False

    for marker in DSH_MARKERS:
        for name in DSH_MARKERS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(marker, "set-by-the-session")
        assert skill_install.dsh_environment() is True, marker


# --------------------------------------------------------------------------
# 2. the status the doctor judges: one harness, the workspace copy
# --------------------------------------------------------------------------


def test_the_dsh_status_is_the_workspace_copy_and_judged_byte_for_byte(
    dsh_session, tmp_path
):
    source = resources.skill_md()
    path = make_workspace(tmp_path, bundle_bytes())

    statuses = skill_install.doctor_skill_statuses(source, tmp_path)

    assert [(status.harness, status.state) for status in statuses] == [("dsh", "current")]
    assert statuses[0].path == path
    assert statuses[0].reason == ""


def test_a_missing_stale_or_unreadable_workspace_copy_is_its_own_state(
    dsh_session, tmp_path
):
    source = resources.skill_md()

    absent = tmp_path / "absent"
    (workspace_skill(absent)).parent.mkdir(parents=True)
    [missing] = skill_install.doctor_skill_statuses(source, absent)
    assert missing.state == "missing"

    stale_root = tmp_path / "stale"
    make_workspace(stale_root, b"# an older SKILL.md was here\n")
    [stale] = skill_install.doctor_skill_statuses(source, stale_root)
    assert stale.state == "stale"

    # Something is at the path and cannot be read: a directory is the shape that
    # needs no permission games on any platform.
    unreadable_root = tmp_path / "unreadable"
    workspace_skill(unreadable_root).mkdir(parents=True)
    [unreadable] = skill_install.doctor_skill_statuses(source, unreadable_root)
    assert unreadable.state == "unreadable"
    assert unreadable.reason, "the OS reason must survive into the doctor line"


# --------------------------------------------------------------------------
# 3. the report: one green line, nine checks, no unrelated harnesses
# --------------------------------------------------------------------------


def test_a_current_workspace_copy_is_one_green_line_and_no_kimi_or_claude(
    dsh_session, tmp_path
):
    source = resources.skill_md()
    path = make_workspace(tmp_path, bundle_bytes())
    checks = run_doctor(
        base.healthy_probe(skill_statuses=skill_install.doctor_skill_statuses(source, tmp_path))
    )

    assert skill_lines(checks) == ["skill-dsh"]
    assert len(checks) == 9, [entry.name for entry in checks]
    assert all(entry.ok for entry in checks), [
        (entry.name, entry.detail) for entry in checks if not entry.ok
    ]
    entry = check(checks, "skill-dsh")
    assert entry.ok is True and entry.skipped is False
    assert entry.fix == ""
    assert str(path) in entry.detail
    assert "dsh" in entry.label and ".agents/skills/boardwise" in entry.label
    # The guided walkthrough has a slot for it, like the two legacy lines had.
    assert DOCTOR_STEP_HINTS["skill-dsh"] == 0


def test_a_missing_workspace_copy_is_red_and_says_where_dsh_reads_it(
    dsh_session, tmp_path
):
    source = resources.skill_md()
    path = make_workspace(tmp_path, None)
    checks = run_doctor(
        base.healthy_probe(skill_statuses=skill_install.doctor_skill_statuses(source, tmp_path))
    )

    entry = check(checks, "skill-dsh")
    assert entry.ok is False and entry.skipped is False
    assert str(path) in entry.detail
    assert ".agents/skills/boardwise" in entry.fix
    assert "dsh" in entry.fix
    # The whole complaint: a dsh user is not told to install a Kimi/Claude skill.
    assert "install-skill" not in entry.fix
    assert "kimi" not in entry.fix.lower() and "claude" not in entry.fix.lower()
    assert [name for name in skill_lines(checks)] == ["skill-dsh"]


def test_a_stale_workspace_copy_is_red_and_says_which_copy_wins(dsh_session, tmp_path):
    source = resources.skill_md()
    make_workspace(tmp_path, b"# an older SKILL.md was here\n")
    checks = run_doctor(
        base.healthy_probe(skill_statuses=skill_install.doctor_skill_statuses(source, tmp_path))
    )

    entry = check(checks, "skill-dsh")
    assert entry.ok is False
    assert "旧版/异版" in entry.detail and "权威" in entry.detail
    assert ".agents/skills/boardwise" in entry.fix
    assert "install-skill" not in entry.fix


def test_an_unreadable_workspace_copy_is_red_with_the_os_reason_and_no_install_fix(
    dsh_session, tmp_path
):
    source = resources.skill_md()
    path = workspace_skill(tmp_path)
    path.mkdir(parents=True)
    [status] = skill_install.doctor_skill_statuses(source, tmp_path)
    checks = run_doctor(base.healthy_probe(skill_statuses=(status,)))

    entry = check(checks, "skill-dsh")
    assert entry.ok is False
    assert "读不出来" in entry.detail and status.reason in entry.detail
    assert ".agents/skills/boardwise" in entry.fix
    assert "install-skill" not in entry.fix


def test_a_build_that_cannot_read_its_own_skill_md_still_skips_under_dsh(
    dsh_session, tmp_path
):
    # No authority to compare against: one skip, not a verdict — the legacy rule
    # (061) survives the harness switch, because "cannot tell" is still not "wrong".
    checks = run_doctor(base.healthy_probe(skill_statuses=()))

    assert skill_lines(checks) == ["skill"]
    assert check(checks, "skill").skipped is True


# --------------------------------------------------------------------------
# 4. the legacy side: unchanged, and it does not branch on DSH
# --------------------------------------------------------------------------


def test_the_legacy_environment_keeps_the_two_harness_lines(legacy_env, tmp_path):
    source = resources.skill_md()
    statuses = skill_install.doctor_skill_statuses(source, tmp_path)
    assert statuses == skill_install.skill_statuses(source)
    assert [status.harness for status in statuses] == list(skill_install.HARNESSES)

    checks = run_doctor(base.healthy_probe(skill_statuses=statuses))
    assert skill_lines(checks) == ["skill-kimi", "skill-claude"]
    assert len(checks) == 10
    for harness in skill_install.HARNESSES:
        entry = check(checks, f"skill-{harness}")
        assert ".kimi-code" in str(entry.detail) or ".claude" in str(entry.detail)


def test_the_old_skill_statuses_does_not_branch_on_the_dsh_markers(dsh_session):
    # `skill_statuses` is the 061 contract other callers (and tests) still hold:
    # it answers for the two user-level harnesses whatever session it runs in.
    statuses = skill_install.skill_statuses(resources.skill_md())

    assert [status.harness for status in statuses] == list(skill_install.HARNESSES)
    assert not [status for status in statuses if status.harness == "dsh"]


# --------------------------------------------------------------------------
# 5. end to end: the real CLI, no daemon (the reporting session's own command)
# --------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _env(home: Path, port: int, workspace: Path) -> dict:
    """A real dsh session's environment, with both offline inputs pinned.

    `DSH_HOME` is dropped and `DSH_SESSION_ID` kept on purpose: either marker is
    enough, and the run has to prove the detection works on the thin one too.
    `BOARDWISE_EDITOR_INSTALL` points at nothing, so the report cannot depend on
    the developer's editor; `BOARDWISE_NO_AUTO_DAEMON` keeps the test from
    spawning a daemon on the free port (157).
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    env["BOARDWISE_NO_AUTO_DAEMON"] = "1"
    env[EDITOR_INSTALL_ENV] = str(workspace / "no-editor-here")
    env["DSH_SESSION_ID"] = "session-537a1"
    env.pop("DSH_HOME", None)
    return env


def _run_doctor_cli(workspace: Path, home: Path):
    port = _free_port()
    result = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", "doctor", "--port", str(port),
         "--json", str(home / "doctor.json")],
        cwd=str(workspace), env=_env(home, port, workspace),
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    payload = json.loads((home / "doctor.json").read_text(encoding="utf-8"))
    return result, payload


def test_the_cli_in_a_dsh_session_reports_one_workspace_skill_line(tmp_path):
    workspace = tmp_path / "workspace"
    make_workspace(workspace, bundle_bytes())

    result, payload = _run_doctor_cli(workspace, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    lines = [line for line in result.stdout.splitlines() if "审查 SOP" in line]
    assert len(lines) == 1, result.stdout
    assert lines[0].lstrip().startswith("PASS"), lines
    names = [entry["name"] for entry in payload["checks"]]
    assert names == [
        "editor-install", "skill-dsh", "daemon", "connector", "methods",
        "editor-version", "daemon-version", "connector-version", "project",
    ]
    assert "skill-kimi" not in str(names) and "skill-claude" not in str(names)
    # Nine checks, not ten: the unrelated harnesses are gone rather than padded.
    assert "2/9" in result.stdout, result.stdout


def test_the_cli_in_a_dsh_session_calls_out_a_missing_workspace_skill(tmp_path):
    workspace = tmp_path / "workspace"
    make_workspace(workspace, None)

    result, payload = _run_doctor_cli(workspace, tmp_path)

    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    entry = [item for item in payload["checks"] if item["name"] == "skill-dsh"][0]
    assert entry["ok"] is False and entry["skipped"] is False
    assert ".agents/skills/boardwise" in entry["fix"]
    assert "install-skill" not in entry["fix"]
    # The printed block for this line (mark, detail, fix) must not send a dsh user
    # to an install command either. Only that block: the report's closing sentence
    # names the command for *other* harnesses and is not a verdict about this one.
    out_lines = result.stdout.splitlines()
    [label_line] = [
        line for line in out_lines
        if line.lstrip().startswith("FAIL") and "审查 SOP" in line
    ]
    block = "\n".join(out_lines[out_lines.index(label_line):out_lines.index(label_line) + 3])
    assert "install-skill" not in block, block
    assert "1/9" in result.stdout, result.stdout
