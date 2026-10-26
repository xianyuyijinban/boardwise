"""Emit/check the 540C versioned CLI contract from the live Python surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from boardwise.bridge.protocol import ErrorCodes
from boardwise.cli import INCOMPLETE_EXIT_CODE, build_parser
from boardwise.engines.grammar.base import (
    FAILURE_CIRCUIT_INVALID,
    FAILURE_FACTS_MISSING,
    FAILURE_LAYOUT_UNSAT,
    FAILURE_PRESENTATION_POOR,
)
from tools.differential_compare import write_text_lf

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "cli" / "v1.json"

# The width every help string in the contract is rendered at. argparse's default
# formatter asks the terminal (`COLUMNS`, falling back to 80) how wide it is, so a
# snapshot taken without pinning it is a function of whoever ran the check — the
# same parser then "drifts" on a 40-column shell and on a 160-column one.
HELP_WIDTH = 80

# Exit codes are command-family contracts, not a universal pass/fail vocabulary.
TOP_EXIT_CODES = {
    "review": [0, 1, 2, 3],
    "checkup": [0, 1, 2, 3],
    "need-datasheet": [0, 2, 3],
    "triage": [0, 2, 3],
    "triage-batch": [0, 2, 3],
    "review-evidence": [0, 1, 2, 3],
    "review-read": [0, 2, 3],
    "review-eval": [0, 2],
    "bridge": [0, 1, 2, 3],
    "review-mark": [0, 1, 2],
    "edit": [0, 2, 3, 4, 5],
    "doctor": [0, 1, 2],
    "install-skill": [0, 1, 2],
    "compare": [0, 1, 2],
    "draw": [0, 1, 2, 3, 4, 5],
    "persistence": [0, 1, 2, 3],
    "lint": [0, 1, 2],
    "parts": [0, 1, 2],
    "bom": [0, 1, 2],
    "pintable": [0, 1, 2],
    "validate": [0, 1, 2],
    "arch": [0, 2],
    "intent": [0, 2],
    "config": [0, 2],
}
SUBCOMMAND_EXIT_CODES = {
    "review.finalize": [0, 1, 2, 3],
    "draw.compile": [0, 2, 5],
    "draw.plan": [0, 2, 3, 5],
    "draw.apply": [0, 2, 3, 4, 5],
    "draw.discard": [0, 2, 3, 4, 5],
    "draw.lint": [0, 1, 2, 3],
    "draw.propose": [0, 2, 5],
    "draw.islands.propose": [0, 2, 5],
    "draw.islands.apply": [0, 2, 5],
}
EXIT_MEANINGS = {
    "0": "Success or a completed result; checkup still requires completion.verdict != incomplete.",
    "1": "Command-specific domain result or ERROR; never read as a universal failure code.",
    "2": "Usage, input or output refusal; no design write is implied.",
    "3": "The state cannot be stated, or review completion is incomplete; not a clean board.",
    "4": "A plan precondition or identity/guard check refused the operation.",
    "5": "A plan/input is unusable or the compiler/proposer refused; not an apply success.",
}


def _type_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "__qualname__", getattr(value, "__name__", repr(value)))


class _FixedWidthHelpFormatter(argparse.HelpFormatter):
    """A help formatter that renders at :data:`HELP_WIDTH` instead of the terminal.

    Only the snapshot needs this: users still see their own terminal's wrapping.
    Setting it on the parser being read (not on any process-wide state) is what
    keeps ``build_contract()`` the same on a 40-column and a 160-column shell.
    """

    def __init__(
        self,
        prog: str,
        indent_increment: int = 2,
        max_help_position: int = 24,
        width: int | None = None,
    ) -> None:
        super().__init__(
            prog,
            indent_increment=indent_increment,
            max_help_position=max_help_position,
            width=HELP_WIDTH,
        )


def _help_text(parser: argparse.ArgumentParser) -> str:
    """This parser's full help, rendered at the pinned width, then restored."""
    original = parser.formatter_class
    parser.formatter_class = _FixedWidthHelpFormatter
    try:
        return parser.format_help()
    finally:
        parser.formatter_class = original


def _parser_tree(parser: argparse.ArgumentParser) -> dict[str, Any]:
    actions = []
    for action in parser._actions:
        row = {
            "optionStrings": list(action.option_strings),
            "dest": action.dest,
            "nargs": repr(action.nargs),
            "const": repr(action.const),
            "default": repr(action.default),
            "type": _type_name(action.type),
            "required": action.required,
            "help": action.help,
            "metavar": repr(action.metavar),
        }
        if isinstance(action, argparse._SubParsersAction):
            row["choices"] = {
                name: _parser_tree(choice) for name, choice in action.choices.items()
            }
        else:
            row["choices"] = repr(action.choices)
        actions.append(row)
    return {
        "prog": parser.prog,
        "description": parser.description,
        "epilog": parser.epilog,
        "helpWidth": HELP_WIDTH,
        "help": _help_text(parser),
        "actions": actions,
    }


def _bridge_error_codes() -> list[str]:
    return sorted(
        value
        for name, value in vars(ErrorCodes).items()
        if name.isupper() and isinstance(value, str)
    )


def build_contract() -> dict[str, Any]:
    parser = build_parser()
    top = next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    command_names = list(top.choices)
    assert command_names == list(TOP_EXIT_CODES), (command_names, list(TOP_EXIT_CODES))
    return {
        "schema": "boardwise.cli-contract/1",
        "contractVersion": 1,
        "entryPoint": {
            "module": "boardwise.cli",
            "parser": "build_parser",
            "main": "main",
        },
        "parser": _parser_tree(parser),
        "exitCodes": {
            "meanings": EXIT_MEANINGS,
            "argparseUsageError": 2,
            "commands": TOP_EXIT_CODES,
            "subcommands": SUBCOMMAND_EXIT_CODES,
            "unlistedSubcommands": (
                "Not listed separately: read the enclosing top-level command family. "
                "An argparse usage error always exits 2 for every command and every "
                "listed subcommand, so 2 is present in every set above."
            ),
        },
        "errorCodes": {
            "incompleteExitCode": INCOMPLETE_EXIT_CODE,
            "drawRefusalCategories": [
                FAILURE_FACTS_MISSING,
                FAILURE_CIRCUIT_INVALID,
                FAILURE_LAYOUT_UNSAT,
                FAILURE_PRESENTATION_POOR,
            ],
            "bridge": _bridge_error_codes(),
        },
    }


def canonical(contract: dict[str, Any]) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write contracts/cli/v1.json.")
    args = parser.parse_args()
    current = canonical(build_contract())
    if args.write:
        CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        # LF on every platform: the artifact is hashed as bytes by whoever pins it.
        write_text_lf(CONTRACT_PATH, current)
        print(CONTRACT_PATH)
        return 0
    if not CONTRACT_PATH.is_file() or CONTRACT_PATH.read_text(encoding="utf-8") != current:
        print(f"CLI contract is stale: {CONTRACT_PATH}; regenerate with --write")
        return 1
    print(f"CLI contract matches production: {CONTRACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
