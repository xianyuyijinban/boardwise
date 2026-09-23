"""``boardwise install-skill``: install, idempotence, backup, uninstall (028 §三.2).

The rule worth testing hardest is the second one: a file that is already at the
destination and differs must be *kept* — copied to ``SKILL.md.bak-<date>`` before
the new one lands. On a friend's machine the alternative is an edit vanishing
with no trace, and "no trace" is also what makes it unprovable afterwards, so the
tests assert on the bytes of the backup rather than on the message.

The CLI is exercised through ``BOARDWISE_SKILL_HOME`` (the same escape hatch
shape as ``BOARDWISE_HOME``), so nothing here can touch the real
``%USERPROFILE%\\.kimi-code\\skills\\``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise import skill_install
from boardwise.cli import main as cli_main

OLD = b"# an older SKILL.md somebody installed\n"
NEW = b"# the SKILL.md this build carries\n"


@pytest.fixture()
def home(tmp_path):
    return tmp_path / "kimi-code" / "skills" / "boardwise"


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "bundled-SKILL.md"
    path.write_bytes(NEW)
    return path


def test_install_creates_the_directory_and_the_file(home, source):
    outcome = skill_install.install(source, home)
    assert outcome.outcome == "installed"
    assert outcome.backup is None
    assert outcome.path == home / "SKILL.md"
    assert outcome.changed is True
    assert outcome.path.read_bytes() == NEW


def test_a_second_install_is_current_and_touches_nothing(home, source):
    skill_install.install(source, home)
    before = (home / "SKILL.md").stat().st_mtime_ns
    outcome = skill_install.install(source, home)
    assert outcome.outcome == "current"
    assert outcome.changed is False
    assert outcome.backup is None
    assert (home / "SKILL.md").read_bytes() == NEW
    assert (home / "SKILL.md").stat().st_mtime_ns == before, "an identical file is left alone"
    assert list(home.glob("SKILL.md.bak-*")) == [], "and nothing is backed up"


def test_a_different_file_is_backed_up_before_it_is_replaced(home, source):
    home.mkdir(parents=True)
    (home / "SKILL.md").write_bytes(OLD)

    outcome = skill_install.install(source, home, today="2026-09-23")

    assert outcome.outcome == "updated"
    assert outcome.backup == home / "SKILL.md.bak-2026-09-23"
    assert outcome.backup.read_bytes() == OLD, "the displaced file survives, byte for byte"
    assert outcome.previous_bytes == len(OLD)
    assert (home / "SKILL.md").read_bytes() == NEW


def test_uninstall_removes_the_file_and_the_empty_directory(home, source):
    skill_install.install(source, home)

    outcome = skill_install.uninstall(home)

    assert outcome.outcome == "removed"
    assert outcome.removed_directory is True
    assert not home.exists()


def test_uninstall_leaves_a_directory_that_still_holds_something(home, source):
    # A recursive delete is not what --uninstall promises: other files in the
    # skill directory belong to whoever put them there.
    skill_install.install(source, home)
    (home / "notes.md").write_text("mine", encoding="utf-8")

    outcome = skill_install.uninstall(home)

    assert outcome.outcome == "removed"
    assert outcome.removed_directory is False
    assert home.is_dir()
    assert (home / "notes.md").read_text(encoding="utf-8") == "mine"


def test_uninstalling_nothing_is_reported_not_faked(home):
    outcome = skill_install.uninstall(home)
    assert outcome.outcome == "absent"
    assert not home.exists()


def test_a_missing_or_empty_source_is_an_error_with_the_path(tmp_path, home):
    with pytest.raises(skill_install.SkillInstallError, match="cannot read the bundled SKILL.md"):
        skill_install.install(tmp_path / "nope.md", home)
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    with pytest.raises(skill_install.SkillInstallError, match="is empty"):
        skill_install.install(empty, home)


def test_the_cli_installs_idempotently_and_removes(tmp_path, monkeypatch, capsys):
    # The four states through the real entry point, with the destination
    # overridden by the environment variable the friend-facing docs mention.
    home = tmp_path / "skills" / "boardwise"
    monkeypatch.setenv(skill_install.SKILL_HOME_ENV, str(home))
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill"]) == 0
    first = capsys.readouterr().out
    assert "installed" in first and str(home / "SKILL.md") in first

    assert cli_main(["install-skill"]) == 0
    assert "already current" in capsys.readouterr().out

    # A different file at the destination: backed up, then replaced.
    (home / "SKILL.md").write_bytes(OLD)
    assert cli_main(["install-skill"]) == 0
    updated = capsys.readouterr().out
    assert "updated" in updated
    assert "SKILL.md.bak-" in updated
    assert (home / "SKILL.md").read_bytes() == NEW
    assert sorted(path.name for path in home.glob("SKILL.md.bak-*"))

    assert cli_main(["install-skill", "--uninstall"]) == 0
    assert "removed" in capsys.readouterr().out
    # The backups stay behind, so the directory does too — reported as such.
    assert cli_main(["install-skill", "--uninstall"]) == 0
    assert "nothing to remove" in capsys.readouterr().out
