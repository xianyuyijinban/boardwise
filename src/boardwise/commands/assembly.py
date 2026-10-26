"""Assembly-owned CLI surface registration and dispatch (540B6)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any


def register_install_skill_parser(sub: Any) -> None:
    """Register the historical `install-skill` command surface."""
    # The harness list comes from the module that writes to them: a harness added
    # there (and given a doctor line) must not need a second edit here to be
    # reachable from `--harness`, which is the shape the silently-missing Claude
    # Code copy had (issue #11).
    from .. import skill_install

    install_skill = sub.add_parser(
        "install-skill",
        help=(
            "Copy the bundled SKILL.md into the user-level skill directory of each "
            "agent harness (Kimi Code, Claude Code), or — with --agent — print the "
            "prompt that has any other harness's AI install it itself."
        ),
        description=(
            "Writes the SKILL.md this build carries where the agent reads it: "
            "~/.kimi-code/skills/boardwise/SKILL.md for Kimi Code (override the "
            "directory with BOARDWISE_SKILL_HOME) and "
            "~/.claude/skills/boardwise/SKILL.md for Claude Code (override with "
            "BOARDWISE_SKILL_HOME_CLAUDE). --harness picks one side; the default is "
            "all of them, because this toolchain is meant to work under either agent "
            "and one of them having no SOP is exactly the state that is impossible to "
            "notice from the outside. Idempotent: an identical file says 'already "
            "current' and is left alone. A *different* file is backed up to "
            "SKILL.md.bak-<YYYYMMDD-HHMMSS> first — never silently overwritten, and "
            "never overwritten by a second install on the same day either. --uninstall "
            "removes the installed copy from the selected harnesses, and each "
            "directory when it empties. --agent writes nothing: it prints the "
            "absolute path of the bundled SKILL.md and a paragraph to hand to an "
            "agent this build knows nothing about (Codex, Hermes, ...), whose skill "
            "directory *it* knows and we would only be guessing at (062)."
        ),
    )
    # `--uninstall` and `--agent` are the two that contradict each other outright
    # (tear the copy down / write nothing at all), and argparse refuses that pair
    # with a usage error (exit 2) instead of letting one silently win. `--harness`
    # stays out of the group: it legitimately combines with `--uninstall`, and a
    # group refuses *every* pair of its members, so putting all three in would
    # break `--uninstall --harness claude`. Its clash with `--agent` is refused in
    # the command instead, the same way `compare` refuses `--spec` next to a
    # candidate (the two are equally exclusive; only argparse's shape differs).
    # The default is None rather than "all" so that spelling the default out is
    # still visible to that check.
    action = install_skill.add_mutually_exclusive_group()
    action.add_argument(
        "--uninstall", action="store_true",
        help="Remove the installed copy instead of installing one.",
    )
    action.add_argument(
        "--agent", action="store_true",
        help=(
            "Print the absolute path of the bundled SKILL.md and a prompt to paste "
            "into any other agent harness, which installs it itself. Writes nothing."
        ),
    )
    install_skill.add_argument(
        "--harness", choices=(*skill_install.HARNESSES, *skill_install.ADVISORY_HARNESSES, "all"), default=None,
        help="Which agent harness to act on (default: all of them).",
    )


def dispatch_assembly(
    args: argparse.Namespace,
    handler: Callable[[argparse.Namespace], int],
) -> int:
    """Resolve an assembly-owned handler at call time."""
    return handler(args)
