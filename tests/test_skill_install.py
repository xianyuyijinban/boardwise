"""``boardwise install-skill``: install, idempotence, backup, uninstall, --agent (028 §三.2, 061, 062).

The rule worth testing hardest is the second one: a file that is already at the
destination and differs must be *kept* — copied to
``SKILL.md.bak-<YYYYMMDD-HHMMSS>`` before the new one lands. On a friend's
machine the alternative is an edit vanishing with no trace, and "no trace" is
also what makes it unprovable afterwards, so the tests assert on the bytes of
the backup rather than on the message.

Since 061 there are two destinations and the same file goes to both (Kimi Code
reads ``~/.kimi-code/skills/boardwise/``, Claude Code ``~/.claude/skills/``), so
"which harness" is a parameter of everything the CLI does. The tests drive each
side through *its own* environment variable (the same escape hatch shape as
``BOARDWISE_HOME``), and the autouse fixture below pins both of them, because
the CLI's default is now ``--harness all``: a test that pinned only one side
would write the other into the developer's real ``%USERPROFILE%\\.claude\\skills\\``
the moment it ran a bare ``install-skill``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from boardwise import skill_install
from boardwise.cli import main as cli_main

OLD = b"# an older SKILL.md somebody installed\n"
NEW = b"# the SKILL.md this build carries\n"


@pytest.fixture(autouse=True)
def skill_homes(tmp_path, monkeypatch):
    """Both harness skill directories, inside this test's tmp_path.

    Returns the two paths so a test can assert on them and pin the environment
    again (or ``delenv`` it, for the "this harness is not on this machine" case)
    without having to know the variable names twice.
    """
    homes = {
        harness: tmp_path / harness / "skills" / "boardwise"
        for harness in skill_install.HARNESSES
    }
    for harness, path in homes.items():
        monkeypatch.setenv(skill_install.SKILL_HOME_ENVS[harness], str(path))
    return homes


@pytest.fixture()
def home(tmp_path):
    return tmp_path / "kimi-code" / "skills" / "boardwise"


@pytest.fixture()
def source(tmp_path):
    path = tmp_path / "bundled-SKILL.md"
    path.write_bytes(NEW)
    return path


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """A home directory that is not this machine's.

    Needed wherever the *default* location is being judged: `Path.home()` is the
    one input the environment variables cannot stand in for (they are what
    replaces the defaults, and a test about the defaults must not set them).
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


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

    outcome = skill_install.install(source, home, now="20260923-101500")

    assert outcome.outcome == "updated"
    assert outcome.backup == home / "SKILL.md.bak-20260923-101500"
    assert outcome.backup.read_bytes() == OLD, "the displaced file survives, byte for byte"
    assert outcome.previous_bytes == len(OLD)
    assert (home / "SKILL.md").read_bytes() == NEW


def test_two_installs_on_one_day_leave_two_backups(home, source):
    """Two installs on the same day must not share a backup file (#40).

    The stamp used to be a bare date, so the second install of the day wrote the
    same name and the first backup was gone — the only record of whatever the
    first file was. No clock is pinned here on purpose: the point is what the
    field default does, and a pinned stamp would hide exactly that.
    """
    home.mkdir(parents=True)
    (home / "SKILL.md").write_bytes(OLD)

    first = skill_install.install(source, home)
    (home / "SKILL.md").write_bytes(b"# a hand edit, kept as a backup too\n")
    second = skill_install.install(source, home)

    assert first.backup != second.backup
    assert first.backup.exists() and second.backup.exists(), (
        "the first backup is still there: it is the only record of the first file"
    )
    assert first.backup.read_bytes() == OLD
    assert len(list(home.glob("SKILL.md.bak-*"))) == 2
    for path in (first.backup, second.backup):
        stamp = path.name.removeprefix("SKILL.md.bak-").split("-")[0:2]
        assert stamp[0].isdigit() and len(stamp[0]) == 8, path.name
        assert stamp[1].isdigit() and len(stamp[1]) == 6, (
            f"{path.name}: the stamp carries a time, not just a date (#40)"
        )


def test_a_taken_backup_name_gets_a_suffix_instead_of_overwriting(home, source):
    """Two installs inside one second are still two backups, not one (#40).

    The time part makes same-day collisions unlikely, not impossible, and the
    backups are the only record of a hand-edited SKILL.md — so an occupied name
    is stepped over rather than written over.
    """
    home.mkdir(parents=True)
    (home / "SKILL.md").write_bytes(OLD)
    first = skill_install.install(source, home, now="20260923-101500")

    (home / "SKILL.md").write_bytes(b"# a hand edit, kept as a backup too\n")
    second = skill_install.install(source, home, now="20260923-101500")

    assert second.backup == home / "SKILL.md.bak-20260923-101500-2"
    assert first.backup.read_bytes() == OLD, "the earlier backup was not overwritten"


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

    assert cli_main(["install-skill", "--harness", "kimi"]) == 0
    first = capsys.readouterr().out
    assert "installed" in first and str(home / "SKILL.md") in first

    assert cli_main(["install-skill", "--harness", "kimi"]) == 0
    assert "already current" in capsys.readouterr().out

    # A different file at the destination: backed up, then replaced.
    (home / "SKILL.md").write_bytes(OLD)
    assert cli_main(["install-skill", "--harness", "kimi"]) == 0
    updated = capsys.readouterr().out
    assert "updated" in updated
    assert "SKILL.md.bak-" in updated
    assert (home / "SKILL.md").read_bytes() == NEW
    assert sorted(path.name for path in home.glob("SKILL.md.bak-*"))

    assert cli_main(["install-skill", "--uninstall", "--harness", "kimi"]) == 0
    assert "removed" in capsys.readouterr().out
    # The backups stay behind, so the directory does too — reported as such.
    assert cli_main(["install-skill", "--uninstall", "--harness", "kimi"]) == 0
    assert "nothing to remove" in capsys.readouterr().out


# --------------------------------------------------------------------------
# the harness dimension (061, issue #11)
# --------------------------------------------------------------------------
#
# The reported failure was a *silent* one: `install-skill` wrote Kimi Code's
# directory and nothing else, so a Claude Code user had the toolchain without
# its SOP and no way to find out. The tests below are about the two destinations
# staying distinct (each env override covers its own side only), about the CLI
# defaulting to both, and about one side failing while the other still lands.


def test_each_harness_has_its_own_default_directory(fake_home, monkeypatch):
    for harness in skill_install.HARNESSES:
        monkeypatch.delenv(skill_install.SKILL_HOME_ENVS[harness], raising=False)

    assert skill_install.skill_dir(harness="kimi") == fake_home / ".kimi-code" / "skills" / "boardwise"
    assert skill_install.skill_dir(harness="claude") == fake_home / ".claude" / "skills" / "boardwise"
    assert skill_install.skill_path(harness="claude").name == "SKILL.md"
    assert skill_install.harness_dir("claude") == fake_home / ".claude"


def test_each_override_covers_only_its_own_side(skill_homes, tmp_path):
    # `BOARDWISE_SKILL_HOME` is the pre-061 name for the kimi side and must keep
    # meaning exactly that: a machine that exports it (028's tests, a friend with
    # an odd layout) must not thereby redirect Claude Code's copy too.
    assert skill_install.skill_dir(harness="kimi") == skill_homes["kimi"]
    assert skill_install.skill_dir(harness="claude") == skill_homes["claude"]
    assert (skill_install.SKILL_HOME_ENVS["kimi"]
            != skill_install.SKILL_HOME_ENVS["claude"]), "one variable per side"

    # An explicit directory still beats the environment: that argument is how the
    # module's own tests pick one exact directory, and the environment is not its
    # business.
    explicit = tmp_path / "explicit"
    assert skill_install.skill_dir(explicit, harness="claude") == explicit
    assert skill_install.skill_path(explicit, harness="claude") == explicit / "SKILL.md"


def test_an_unknown_harness_is_refused_rather_than_defaulted(tmp_path):
    # The failure this guards: a typo falling through to the kimi default would
    # write into the wrong agent's directory and report success.
    with pytest.raises(ValueError, match="unknown harness 'ki mi'"):
        skill_install.skill_dir(harness="ki mi")
    with pytest.raises(ValueError, match="unknown harness"):
        skill_install.skill_path(harness="kimi-code")
    with pytest.raises(ValueError, match="unknown harness"):
        skill_install.harness_dir("Claude")


def test_install_writes_one_side_and_leaves_the_other_alone(source, skill_homes):
    outcome = skill_install.install(source, harness="claude")

    assert outcome.outcome == "installed"
    assert outcome.path == skill_homes["claude"] / "SKILL.md"
    assert outcome.path.read_bytes() == NEW
    assert not skill_homes["kimi"].exists(), "the harness not asked for is not touched"


def test_each_side_is_idempotent_on_its_own(source, skill_homes):
    for harness in skill_install.HARNESSES:
        assert skill_install.install(source, harness=harness).outcome == "installed"
        before = (skill_homes[harness] / "SKILL.md").stat().st_mtime_ns
        second = skill_install.install(source, harness=harness)
        assert second.outcome == "current"
        assert (skill_homes[harness] / "SKILL.md").stat().st_mtime_ns == before
        assert list(skill_homes[harness].glob("SKILL.md.bak-*")) == []


def test_a_different_file_is_backed_up_on_the_claude_side_too(source, skill_homes):
    directory = skill_homes["claude"]
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_bytes(OLD)

    outcome = skill_install.install(source, harness="claude", now="20260923-101500")

    assert outcome.outcome == "updated"
    assert outcome.backup == directory / "SKILL.md.bak-20260923-101500"
    assert outcome.backup.read_bytes() == OLD
    assert (directory / "SKILL.md").read_bytes() == NEW


def test_uninstall_takes_the_harness_it_was_given(source, skill_homes):
    for harness in skill_install.HARNESSES:
        skill_install.install(source, harness=harness)

    outcome = skill_install.uninstall(harness="claude")

    assert outcome.outcome == "removed" and outcome.removed_directory is True
    assert not skill_homes["claude"].exists()
    assert (skill_homes["kimi"] / "SKILL.md").read_bytes() == NEW, "kimi keeps its copy"


def test_the_cli_writes_both_sides_by_default(tmp_path, monkeypatch, capsys, skill_homes):
    # The default is the fix for issue #11 in one sentence: the toolchain is
    # meant to work under either agent, so both get the SOP — and the output says
    # which line is which, because a path under an unusual override may not.
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill"]) == 0
    first = capsys.readouterr().out
    for harness, directory in skill_homes.items():
        assert (directory / "SKILL.md").read_bytes() == NEW
        assert f"[{harness}]" in first
    assert first.count("installed") == len(skill_install.HARNESSES)

    assert cli_main(["install-skill"]) == 0
    second = capsys.readouterr().out
    assert second.count("already current") == len(skill_install.HARNESSES)


def test_the_harness_flag_picks_one_side(tmp_path, monkeypatch, capsys, skill_homes):
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill", "--harness", "claude"]) == 0
    out = capsys.readouterr().out
    assert (skill_homes["claude"] / "SKILL.md").read_bytes() == NEW
    assert not skill_homes["kimi"].exists()
    assert "[kimi]" not in out and "[claude]" in out

    # And the other direction, independently.
    assert cli_main(["install-skill", "--harness", "kimi"]) == 0
    capsys.readouterr()
    assert (skill_homes["kimi"] / "SKILL.md").read_bytes() == NEW


def test_an_unknown_harness_is_refused_by_the_parser_not_by_a_traceback(capsys):
    # `choices` is the outer guard (a clean usage error, exit 2); the module's
    # own ValueError is the inner one. Without the first, a typo would reach
    # `skill_dir` and come back as a traceback with exit 1.
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["install-skill", "--harness", "easyeda"])
    assert excinfo.value.code == 2
    assert "invalid choice: 'easyeda'" in capsys.readouterr().err


def test_uninstall_covers_the_selected_sides_only(tmp_path, monkeypatch, capsys, skill_homes):
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)
    assert cli_main(["install-skill"]) == 0
    capsys.readouterr()

    assert cli_main(["install-skill", "--uninstall", "--harness", "claude"]) == 0
    removed = capsys.readouterr().out
    assert "[claude]" in removed and "[kimi]" not in removed
    assert not (skill_homes["claude"] / "SKILL.md").exists()
    assert (skill_homes["kimi"] / "SKILL.md").exists()

    assert cli_main(["install-skill", "--uninstall"]) == 0
    both = capsys.readouterr().out
    # Kimi Code's copy was still there, Claude Code's was already gone — and the
    # second run says so per side instead of reporting one verdict for both.
    assert both.count("removed") == 1
    assert "[kimi]" in both and "nothing to remove" in both
    assert not skill_homes["kimi"].exists()


def test_one_failing_side_does_not_stop_the_other_and_still_exits_1(tmp_path, monkeypatch, capsys, skill_homes):
    # "Try every selected harness, then decide the exit code": a destination the
    # run cannot read (here a *directory* sitting where SKILL.md goes — the same
    # shape as a permissions failure, without needing to break a real one) must
    # not take Claude Code's copy down with it.
    kimi = skill_homes["kimi"]
    (kimi / "SKILL.md").mkdir(parents=True)
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill"]) == 1
    captured = capsys.readouterr()
    assert "[kimi]" in captured.err and "cannot read" in captured.err
    assert (skill_homes["claude"] / "SKILL.md").read_bytes() == NEW, "the other side still installed"
    assert "[claude]" in captured.out


# --------------------------------------------------------------------------
# skill_statuses: doctor's raw material (061 §3.1)
# --------------------------------------------------------------------------


def states(statuses):
    return [(status.harness, status.state) for status in statuses]


def test_statuses_judge_each_harness_against_the_bundled_file(source, skill_homes):
    skill_install.install(source, harness="kimi")
    skill_homes["claude"].mkdir(parents=True)
    (skill_homes["claude"] / "SKILL.md").write_bytes(OLD)

    statuses = skill_install.skill_statuses(source)

    assert states(statuses) == [("kimi", "current"), ("claude", "stale")]
    assert [status.path for status in statuses] == [
        skill_homes["kimi"] / "SKILL.md", skill_homes["claude"] / "SKILL.md"
    ]
    assert all(status.reason == "" for status in statuses)


def test_a_harness_with_nothing_installed_is_missing_not_absent(source, skill_homes):
    statuses = skill_install.skill_statuses(source)
    assert states(statuses) == [("kimi", "missing"), ("claude", "missing")]


def test_a_harness_that_is_not_on_this_machine_is_absent(source, fake_home, monkeypatch):
    # The distinction doctor's skip hangs on: `~/.claude` not existing cannot
    # mean "Claude Code is missing its SOP" — the user does not run Claude Code.
    for harness in skill_install.HARNESSES:
        monkeypatch.delenv(skill_install.SKILL_HOME_ENVS[harness], raising=False)

    statuses = skill_install.skill_statuses(source)

    assert states(statuses) == [("kimi", "harness-absent"), ("claude", "harness-absent")]
    assert statuses[0].path == fake_home / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"

    # A harness directory that *is* there flips just that one harness's verdict.
    (fake_home / ".claude").mkdir()
    assert states(skill_install.skill_statuses(source)) == [("kimi", "harness-absent"), ("claude", "missing")]


def test_an_override_alone_makes_a_harness_count_as_in_use(source, fake_home, monkeypatch):
    # Somebody who exports the variable has said this harness is theirs; judging
    # that against a default home directory would report the harness absent for
    # the one person who was explicit about it.
    monkeypatch.delenv(skill_install.SKILL_HOME_ENVS["kimi"], raising=False)
    explicit = fake_home / "elsewhere" / "boardwise"
    monkeypatch.setenv(skill_install.SKILL_HOME_ENVS["claude"], str(explicit))

    statuses = skill_install.skill_statuses(source)

    assert states(statuses) == [("kimi", "harness-absent"), ("claude", "missing")]


def test_an_unreadable_installed_copy_carries_the_os_reason(source, skill_homes):
    # Something is at the path and cannot be read. "Cannot tell" without the
    # reason is the dead end this is meant to avoid, so the OS message travels.
    (skill_homes["claude"] / "SKILL.md").mkdir(parents=True)

    status, = [s for s in skill_install.skill_statuses(source) if s.harness == "claude"]

    assert status.state == "unreadable"
    assert status.reason, "the OS message is the finding here"
    assert str(skill_homes["claude"] / "SKILL.md") == str(status.path)


def test_a_bundled_file_that_cannot_be_read_is_an_error_not_a_verdict(tmp_path):
    # No authority to compare against means no statuses at all — doctor turns the
    # empty tuple into one skipped line rather than calling every harness stale.
    # (The error is a RuntimeError, which is also what `resources.skill_md()`
    # raises, so the CLI catches one class for both.)
    with pytest.raises(RuntimeError, match="cannot read the bundled SKILL.md"):
        skill_install.skill_statuses(tmp_path / "nope.md")
    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    with pytest.raises(skill_install.SkillInstallError, match="is empty"):
        skill_install.skill_statuses(empty)


# --------------------------------------------------------------------------
# --agent: the prompt for the harnesses we deliberately do not know (062)
# --------------------------------------------------------------------------
#
# 岳's call after issue #11: a table of harness skill directories is a permanent
# guess, wrong the moment a new agent appears — so a harness this build does not
# know gets a *prompt* instead, which its own AI finishes with the one fact only
# that AI holds (where it looks for skills). The tests below are therefore about
# two things: that the paragraph says what it has to say, and that the command
# itself writes nothing at all — pasting a prompt must never be a way to get a
# surprise write on this machine.


def tree(root: Path) -> dict:
    """Every path under ``root`` with a fingerprint — ``{}`` when it does not exist.

    "Zero filesystem change" is a claim about the disk, so it is measured on the
    disk: a message that merely *reads* as read-only would not catch a mutation
    that writes the file and reports nothing.
    """
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): (
            ("dir",) if path.is_dir()
            else ("file", hashlib.sha256(path.read_bytes()).hexdigest())
        )
        for path in sorted(root.rglob("*"))
    }


def test_the_agent_flag_prints_the_prompt_and_writes_nothing(tmp_path, monkeypatch, capsys, skill_homes):
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)
    before = tree(tmp_path)

    assert cli_main(["install-skill", "--agent"]) == 0

    out = capsys.readouterr().out
    assert out.count(str(source)) == 2, (
        "the absolute path outside the block *and* inside it: the pasted part has "
        "to stand on its own, it is the part that travels to the other agent"
    )
    assert "boardwise" in out and "SKILL.md" in out, "the directory name and the file name"
    assert "bak-" in out, "the backup rule, the same one the install path follows"
    assert "验证" in out, "the other agent has to check that it landed"
    assert "粘给你" in out and "AI" in out, "and the human line that says what to do with it"
    assert ".kimi-code" not in out and ".claude" not in out, (
        "no path table — the whole point is that *the other agent* knows its own"
    )

    assert tree(tmp_path) == before, "zero filesystem change"
    for directory in skill_homes.values():
        assert not directory.exists(), "not even the directory is created"


def test_the_agent_flag_leaves_an_installed_copy_alone(tmp_path, monkeypatch, capsys, skill_homes):
    # The difference between the two flags in one test: `--harness kimi` would
    # replace the file it finds here, backing it up first; `--agent` prints a
    # paragraph, and the older copy that paragraph describes is still where it was.
    kimi = skill_homes["kimi"]
    kimi.mkdir(parents=True)
    (kimi / "SKILL.md").write_bytes(OLD)
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill", "--agent"]) == 0

    capsys.readouterr()
    assert (kimi / "SKILL.md").read_bytes() == OLD, "the copy that was there is still the copy"
    assert list(kimi.glob("SKILL.md.bak-*")) == [], "and nothing was backed up on its behalf"


def test_agent_and_uninstall_is_refused_by_the_parser(capsys, skill_homes):
    """``--agent`` is a third job, not a switch on the job the other two do.

    The pair argparse can see: "tear the copy down" and "write nothing at all"
    contradict each other outright, so the group refuses it as a usage error.
    """
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["install-skill", "--agent", "--uninstall"])
    assert excinfo.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


@pytest.mark.parametrize("harness", ["kimi", "all"])
def test_agent_and_harness_is_refused_with_the_same_exit_code(harness, capsys, skill_homes):
    """The pair argparse *cannot* see, refused identically (exit 2).

    ``--harness`` sits outside the mutually exclusive group because it is a
    legitimate companion of ``--uninstall`` ("remove the copy on this side only")
    and a group refuses every pair among its members — so the ``--agent`` clash
    is refused in the command, the way ``compare`` refuses ``--spec`` next to a
    candidate. ``all`` is in the list because it is the default spelled out: the
    parser's default for ``--harness`` is ``None`` precisely so that writing the
    default down is still visible here.
    """
    assert cli_main(["install-skill", "--agent", "--harness", harness]) == 2
    err = capsys.readouterr().err
    assert "--agent" in err and "--harness" in err, err


def test_the_harness_default_is_still_every_harness(tmp_path, monkeypatch, capsys, skill_homes):
    # `--harness` defaults to None now instead of "all" (so the group above can
    # see an explicit "all"): the meaning of *not passing it* must not have moved
    # with the spelling.
    source = tmp_path / "SKILL.md"
    source.write_bytes(NEW)
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: source)

    assert cli_main(["install-skill"]) == 0
    out = capsys.readouterr().out
    for harness, directory in skill_homes.items():
        assert (directory / "SKILL.md").read_bytes() == NEW
        assert f"[{harness}]" in out


def test_agent_exits_1_when_the_bundled_skill_cannot_be_read(tmp_path, monkeypatch, capsys):
    # A prompt to copy a file that is not there is worse than no prompt, so the
    # three shapes a broken bundle takes all exit 1 rather than printing a
    # paragraph that names an uncopyable path.
    def no_bundle():
        raise RuntimeError("this build carries no SKILL.md")

    monkeypatch.setattr("boardwise.resources.skill_md", no_bundle)
    assert cli_main(["install-skill", "--agent"]) == 1
    assert "this build carries no SKILL.md" in capsys.readouterr().err

    monkeypatch.setattr("boardwise.resources.skill_md", lambda: tmp_path / "nope.md")
    assert cli_main(["install-skill", "--agent"]) == 1
    assert "nope.md" in capsys.readouterr().err

    empty = tmp_path / "empty.md"
    empty.write_bytes(b"")
    monkeypatch.setattr("boardwise.resources.skill_md", lambda: empty)
    assert cli_main(["install-skill", "--agent"]) == 1
    assert "is empty" in capsys.readouterr().err
