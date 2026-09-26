"""Drift guard (045 §7): the dsh plugin wraps CLI commands **by name**.

`dsh-plugin/src/index.ts` builds argv arrays whose first token is a boardwise
CLI command. Renaming or removing such a command breaks the plugin on every dsh
machine, silently from pytest's point of view — unless this guard is watching.
The reverse direction (a new CLI command not yet wrapped) is a release-checklist
judgment, not a failure: see `tasks/045-dsh-plugin.md` §7.
"""

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "src" / "boardwise" / "cli.py"
PLUGIN = REPO / "dsh-plugin" / "src" / "index.ts"


def _cli_commands() -> set[str]:
    text = CLI.read_text(encoding="utf-8")
    # `add_parser("name"` — the name may sit on the next line (\s spans it).
    return set(re.findall(r"add_parser\(\s*[\"']([\w-]+)[\"']", text))


def _wrapped_commands() -> set[str]:
    text = PLUGIN.read_text(encoding="utf-8")
    commands = set()
    for argv in re.findall(r"const argv = \[([^\]]+)\]", text):
        first = argv.split(",", 1)[0].strip().strip("'\"")
        if first:
            commands.add(first)
    return commands


def test_every_command_the_dsh_plugin_spawns_exists_in_the_cli():
    wrapped = _wrapped_commands()
    assert wrapped, "guard vacuous: no argv arrays found in dsh-plugin/src/index.ts"
    missing = wrapped - _cli_commands()
    assert not missing, (
        f"dsh-plugin wraps CLI commands that no longer exist: {sorted(missing)} — "
        "a rename in cli.py must be mirrored in dsh-plugin (045 §7 sync discipline)"
    )
