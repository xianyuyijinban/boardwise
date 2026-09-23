"""Install (or remove) the user-level copy of SKILL.md (028 batch 3b).

``boardwise install-skill`` is the last step of the friend install path: the exe
already carries SKILL.md (028 §二.1), so a machine with no repo can still put the
agent-facing checklist where Kimi Code looks for it
(``~/.kimi-code/skills/boardwise/SKILL.md``).

Three rules, and the second one is the point of the whole module:

1. **Idempotent.** Running it twice with the same SKILL.md says "already
   current" and touches nothing — no rewrite, no new backup file.
2. **Never silently overwrite.** A different file already at the destination is
   *somebody's* file — an older install, or a hand edit — so it is copied to
   ``SKILL.md.bak-<date>`` before the new one lands, and the backup's path is
   reported. On a friend's machine the alternative is losing an edit with no
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
from datetime import date
from pathlib import Path

#: Where the user-level skill directory lives. ``BOARDWISE_SKILL_HOME`` overrides
#: it — the same escape hatch shape as ``BOARDWISE_HOME`` for the daemon's state,
#: and what lets a test drive the whole flow inside a tmp directory.
SKILL_HOME_ENV = "BOARDWISE_SKILL_HOME"

#: The file name the user-level skill is expected to have.
SKILL_NAME = "SKILL.md"


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


def skill_dir(home: Path | None = None) -> Path:
    """The user-level skill directory, honouring :data:`SKILL_HOME_ENV`."""
    if home is not None:
        return Path(home)
    override = os.environ.get(SKILL_HOME_ENV)
    if override:
        return Path(override)
    return Path.home() / ".kimi-code" / "skills" / "boardwise"


def skill_path(home: Path | None = None) -> Path:
    """The user-level SKILL.md itself."""
    return skill_dir(home) / SKILL_NAME


def install(source: Path, home: Path | None = None, *, today: str | None = None) -> InstallOutcome:
    """Put ``source`` at the user-level SKILL.md, backing up anything different.

    ``today`` (``YYYY-MM-DD``) is injectable so the backup name is deterministic
    in tests; in the field it is today's date, which is what makes two backups on
    two days distinguishable and two on the same day identical — the second one
    then simply replaces the first, which is fine: it is the same file being
    displaced twice.
    """
    source = Path(source)
    destination = skill_path(home)
    try:
        wanted = source.read_bytes()
    except OSError as exc:
        raise SkillInstallError(f"cannot read the bundled SKILL.md at {source}: {exc}") from exc
    if not wanted:
        raise SkillInstallError(f"the bundled SKILL.md at {source} is empty")

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
        stamp = today or date.today().isoformat()
        backup = destination.with_name(f"{SKILL_NAME}.bak-{stamp}")
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


def uninstall(home: Path | None = None) -> UninstallOutcome:
    """Remove the user-level SKILL.md, and the skill directory if it empties.

    The directory is only removed when it is empty: a friend (or I) may have put
    something else in there, and a recursive delete is not what "--uninstall"
    promises.
    """
    destination = skill_path(home)
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
