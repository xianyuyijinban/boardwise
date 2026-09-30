"""Install (or remove) the user-level copy of SKILL.md (028 batch 3b, 061).

``boardwise install-skill`` is the last step of the friend install path: the exe
already carries SKILL.md (028 §二.1), so a machine with no repo can still put the
agent-facing checklist where the agent reads it. Two agents read a user-level
SKILL.md and they look in two different directories (issue #11):

* Kimi Code → ``~/.kimi-code/skills/boardwise/SKILL.md``
* Claude Code → ``~/.claude/skills/boardwise/SKILL.md``

One file serves both: it is the same SKILL.md either way, and the frontmatter it
already carries (``name`` + ``description``) is exactly what Claude Code keys
off — so there is no content fork to keep in sync, only two destinations. The
harness is therefore a *parameter* of every call here, never a hardcoded path:
:data:`HARNESSES` is the list, and which of them a run touches is the caller's
business (the CLI defaults to all of them).

Three rules, and the second one is the point of the whole module:

1. **Idempotent.** Running it twice with the same SKILL.md says "already
   current" and touches nothing — no rewrite, no new backup file.
2. **Never silently overwrite.** A different file already at the destination is
   *somebody's* file — an older install, or a hand edit — so it is copied to
   ``SKILL.md.bak-<YYYYMMDD-HHMMSS>`` before the new one lands, and the backup's
   path is reported. The stamp has a time part and an existing backup is never
   overwritten, so two installs on one day each leave their own file behind
   (#40). On a friend's machine the alternative is losing an edit with no
   trace, which is the failure this rule exists to prevent.
3. **Total on the filesystem.** A destination that cannot be read, written or
   removed raises :class:`SkillInstallError` with the path and the OS message;
   the CLI renders that as exit 1 rather than a traceback.

The module deals in paths and returns outcomes; printing is the CLI's business
(so the tests assert on outcomes rather than on stdout).
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: The agent harnesses that read a user-level SKILL.md, in the order every run
#: reports them. A second harness is two lines here (plus its own doctor line in
#: the CLI) — which is the point: issue #11 was a harness the installer silently
#: never wrote to, and the fix has to make the set of them visible, not implicit.
HARNESSES: tuple[str, ...] = ("kimi", "claude")

#: The harness's own directory under the home directory. Its existence *is* the
#: signal that this harness is on this machine (see :func:`skill_statuses`),
#: which is why it is named apart from the skill directory inside it: "nothing
#: installed" and "harness not in use here" are different answers and doctor
#: must not turn the second into an alarm.
HARNESS_DIRS: dict[str, str] = {"kimi": ".kimi-code", "claude": ".claude"}

#: Where the user-level skill directory lives, per harness. The override is the
#: same escape hatch shape as ``BOARDWISE_HOME`` for the daemon's state, and what
#: lets a test drive the whole flow inside a tmp directory. Each harness has its
#: own variable and each only covers its own side — one env var redirecting both
#: would make "install for Claude Code only" impossible to express in a test, and
#: would let a stale exported value quietly write somewhere nobody asked for.
SKILL_HOME_ENV = "BOARDWISE_SKILL_HOME"
SKILL_HOME_ENVS: dict[str, str] = {
    "kimi": SKILL_HOME_ENV,
    "claude": "BOARDWISE_SKILL_HOME_CLAUDE",
}

#: The file name the user-level skill is expected to have.
SKILL_NAME = "SKILL.md"

# Backup stamps carry a time part (#40): a date-only stamp made two installs on
# the same day write the same backup name, so the second one silently displaced
# the first. Seconds are still not uniqueness — the retry suffix below is.
_STAMP_FORMAT = "%Y%m%d-%H%M%S"


class SkillInstallError(RuntimeError):
    """A filesystem step failed; the message names the path and the OS reason."""


@dataclass(frozen=True)
class InstallOutcome:
    """What :func:`install` did — the CLI turns one of these into one line.

    ``outcome`` is one of ``installed`` / ``updated`` / ``current``;
    ``backup`` is the path the previous file was preserved as, when there was
    one, and ``None`` otherwise (so "no backup" is a fact, not a missing field).
    """

    outcome: str
    path: Path
    backup: Path | None = None
    previous_bytes: int | None = None

    @property
    def changed(self) -> bool:
        return self.outcome in ("installed", "updated")


@dataclass(frozen=True)
class UninstallOutcome:
    """What :func:`uninstall` did: ``removed`` / ``absent``, plus what went with it."""

    outcome: str
    path: Path
    removed_directory: bool = False


@dataclass(frozen=True)
class SkillStatus:
    """What is *at* one harness's skill path right now — doctor's raw material.

    ``state`` is one of:

    ``current``
        the installed SKILL.md is byte-for-byte the one this build carries;
    ``stale``
        a SKILL.md is installed and it is *not* this build's — an older install,
        or somebody's edit. The build's own copy is the authority (that is the
        whole reason to install one), so this is worth saying out loud;
    ``missing``
        the harness is here, nothing is installed for it;
    ``unreadable``
        something is at the path and could not be read; ``reason`` carries the
        OS message, because "cannot read it" without the reason is the kind of
        dead end this module exists to avoid;
    ``harness-absent``
        the harness itself is not on this machine (no ``~/.kimi-code`` /
        ``~/.claude``, and no override pointing at one), so there is nothing to
        report about its skill. A *skip* in doctor's terms: not a fault.

    Read-only by construction: this is a fact, and :func:`run_doctor` (the CLI's
    pure half) decides what it is worth, which is why the judgement words —
    "ok", "skipped" — are not in here.
    """

    harness: str
    path: Path
    state: str
    reason: str = ""


def _known_harness(harness: str) -> str:
    """``harness`` unchanged, or ``ValueError`` — a typo must not pick a path.

    Every entry point validates through here: a misspelled harness that fell
    through to "the kimi default" would install into the wrong agent's directory
    and report success, which is the class of silent wrong-place write this
    module's rules are about.
    """
    if harness not in HARNESS_DIRS:
        raise ValueError(
            f"unknown harness {harness!r}; known harnesses: {', '.join(HARNESSES)}"
        )
    return harness


def harness_dir(harness: str) -> Path:
    """The harness's own directory (``~/.kimi-code`` / ``~/.claude``)."""
    return Path.home() / HARNESS_DIRS[_known_harness(harness)]


def skill_dir(home: Path | None = None, *, harness: str = "kimi") -> Path:
    """The user-level skill directory for ``harness``, honouring its override.

    Precedence is explicit argument → environment override → the harness's own
    default location. ``home`` is how the tests and the CLI drive one exact
    directory; the override is how a user with an unusual layout does.
    """
    if home is not None:
        return Path(home)
    override = os.environ.get(SKILL_HOME_ENVS[_known_harness(harness)])
    if override:
        return Path(override)
    return harness_dir(harness) / "skills" / "boardwise"


def skill_path(home: Path | None = None, *, harness: str = "kimi") -> Path:
    """The user-level SKILL.md itself, for ``harness``."""
    return skill_dir(home, harness=harness) / SKILL_NAME


def _harness_in_use(harness: str) -> bool:
    """Does anything on this machine say this harness is used?

    Two signals and either is enough:

    * the harness's own directory exists (``~/.kimi-code`` / ``~/.claude``);
    * the user pointed this harness at a skill directory of their own through its
      override — somebody who exports ``BOARDWISE_SKILL_HOME_CLAUDE`` has said,
      in the only way available, that this harness is theirs. Judging *that*
      against a default home directory would report the harness absent for the
      one person who was explicit about it (and would make every test that
      drives the flow through the variable blind).

    With neither signal, the harness is not installed and its skill is not
    missing: it is not this machine's business. Doctor skips those instead of
    printing a red line for an editor the user has never run.
    """
    if os.environ.get(SKILL_HOME_ENVS[harness]):
        return True
    return harness_dir(harness).is_dir()


def _bundled_bytes(source: Path) -> bytes:
    """The SKILL.md this build carries, or :class:`SkillInstallError`.

    Shared by :func:`install` and :func:`skill_statuses` so both refuse the same
    two things (an unreadable source, an empty one) with the same words. The
    error is a ``RuntimeError``, which is also what ``resources.skill_md()``
    raises for a broken bundle — doctor catches that one class for both.
    """
    source = Path(source)
    try:
        wanted = source.read_bytes()
    except OSError as exc:
        raise SkillInstallError(f"cannot read the bundled SKILL.md at {source}: {exc}") from exc
    if not wanted:
        raise SkillInstallError(f"the bundled SKILL.md at {source} is empty")
    return wanted


def skill_statuses(source: Path) -> tuple[SkillStatus, ...]:
    """Judge every harness's installed copy against ``source`` — one per harness.

    Offline and read-only: no harness is asked anything, the filesystem is the
    whole evidence (061 §三). The two states that must not be conflated are
    "this harness has nothing installed" (``missing``: a fault worth a doctor
    line) and "this harness is not on this machine" (``harness-absent``: a skip).
    """
    wanted = _bundled_bytes(source)
    statuses: list[SkillStatus] = []
    for harness in HARNESSES:
        path = skill_path(harness=harness)
        if not _harness_in_use(harness):
            statuses.append(SkillStatus(harness, path, "harness-absent"))
            continue
        try:
            installed = path.read_bytes()
        except FileNotFoundError:
            statuses.append(SkillStatus(harness, path, "missing"))
        except OSError as exc:
            # Present and unreadable (permissions, a directory in its place, a
            # lock) — the one case where the OS message is the finding.
            statuses.append(SkillStatus(harness, path, "unreadable", reason=str(exc)))
        else:
            statuses.append(
                SkillStatus(harness, path, "current" if installed == wanted else "stale")
            )
    return tuple(statuses)


def _free_backup_path(destination: Path, now: str | None) -> Path:
    """A backup path for ``destination`` that no backup already occupies.

    The clock is a parameter so tests get a deterministic name; in the field it
    is the current time down to the second. Two installs inside the same second
    are still the same name, so an occupied name gets a ``-2``/``-3`` suffix
    rather than being overwritten — "never silently overwrite" covers the
    backups too, and they are the only record of a hand-edited SKILL.md.
    """
    stamp = now or datetime.now().strftime(_STAMP_FORMAT)
    candidate = destination.with_name(f"{SKILL_NAME}.bak-{stamp}")
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = destination.with_name(f"{SKILL_NAME}.bak-{stamp}-{suffix}")
    return candidate


def install(
    source: Path,
    home: Path | None = None,
    *,
    harness: str = "kimi",
    now: str | None = None,
) -> InstallOutcome:
    """Put ``source`` at ``harness``'s user-level SKILL.md, backing up any different file.

    ``harness`` only decides the destination: there is no per-harness variant of
    the file (see the module docstring), and a run that wants both harnesses
    calls this twice — one destination per call is what makes the CLI's exit code
    able to say *which* side failed.

    ``now`` (``YYYYMMDD-HHMMSS``) is the injectable clock behind the backup
    name, so the tests can pin it. The field default is the current time, and
    the name is then free of collisions on its own: two installs on the same day
    are two different files, not the second one overwriting the first (#40).
    """
    source = Path(source)
    destination = skill_path(home, harness=harness)
    wanted = _bundled_bytes(source)

    previous: bytes | None = None
    if destination.exists():
        try:
            previous = destination.read_bytes()
        except OSError as exc:
            raise SkillInstallError(f"cannot read {destination}: {exc}") from exc
        if previous == wanted:
            return InstallOutcome("current", destination, previous_bytes=len(previous))

    backup: Path | None = None
    if previous is not None:
        backup = _free_backup_path(destination, now)
        try:
            shutil.copyfile(destination, backup)
        except OSError as exc:
            # No backup, no overwrite: the whole point is that the old file
            # survives, so a failed copy must stop here rather than proceed.
            raise SkillInstallError(f"cannot back up {destination} to {backup}: {exc}") from exc

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(wanted)
    except OSError as exc:
        raise SkillInstallError(f"cannot write {destination}: {exc}") from exc

    return InstallOutcome(
        "updated" if previous is not None else "installed",
        destination,
        backup=backup,
        previous_bytes=len(previous) if previous is not None else None,
    )


def uninstall(home: Path | None = None, *, harness: str = "kimi") -> UninstallOutcome:
    """Remove ``harness``'s user-level SKILL.md, and the skill directory if it empties.

    Same one-destination-per-call shape as :func:`install`: ``--uninstall`` for
    both harnesses is two calls, so a failure on one side still leaves the other
    one's result reportable.

    The directory is only removed when it is empty: a friend (or I) may have put
    something else in there, and a recursive delete is not what "--uninstall"
    promises.
    """
    destination = skill_path(home, harness=harness)
    directory = destination.parent
    if not destination.exists():
        return UninstallOutcome("absent", destination)
    try:
        destination.unlink()
    except OSError as exc:
        raise SkillInstallError(f"cannot remove {destination}: {exc}") from exc

    removed_directory = False
    try:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
            removed_directory = True
    except OSError:
        # A directory that will not go is not a failed uninstall: the file the
        # command promises to remove is gone. Left as it is, reported as such.
        removed_directory = False
    return UninstallOutcome("removed", destination, removed_directory=removed_directory)
