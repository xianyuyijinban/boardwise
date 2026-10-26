"""540B4: draw CLI registration/dispatch moves without its observable surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boardwise.cli as cli
from boardwise.commands import draw as draw_commands

from test_540_shared_naming import PACKAGE, _in_package_imports
import test_owner_rules

ROOT = Path(__file__).resolve().parents[1]

TOP_COMMANDS = [
    "review", "checkup", "need-datasheet", "triage", "triage-batch",
    "review-evidence", "review-read", "review-eval", "bridge", "review-mark",
    "edit", "doctor", "install-skill", "compare", "draw", "persistence",
    "lint", "parts", "bom", "pintable", "validate", "arch", "intent", "config",
]
DRAW_PARSER_COMMANDS = ["compile", "plan", "apply", "discard", "lint", "propose", "islands"]
DRAW_REGISTRY_COMMANDS = ["compile", "plan", "apply", "discard", "propose", "lint", "islands"]


def _subparsers(parser: argparse.ArgumentParser):
    return next(
        action for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def test_top_level_and_draw_command_order_are_frozen():
    top = _subparsers(cli.build_parser())
    assert list(top.choices) == TOP_COMMANDS
    draw = _subparsers(top.choices["draw"])
    assert list(draw.choices) == DRAW_PARSER_COMMANDS
    assert list(cli.DRAW_COMMANDS) == DRAW_REGISTRY_COMMANDS
    islands = _subparsers(draw.choices["islands"])
    assert list(islands.choices) == ["propose", "apply"]
    edit = _subparsers(top.choices["edit"])
    assert list(edit.choices) == ["plan", "preview", "apply"]
    assert list(cli.EDIT_COMMANDS) == ["plan", "preview", "apply"]
    assert cli.EDIT_DIRECTIONS == ("value", "mpn")
    pintable = _subparsers(top.choices["pintable"])
    assert list(pintable.choices) == ["check"]
    assert list(cli.PINTABLE_COMMANDS) == ["check"]


def test_draw_command_module_has_no_reverse_cli_or_review_dependency():
    assert _in_package_imports(PACKAGE / "commands" / "draw.py") == {
        "engines/generate.py", "core/portmeta.py",
    }
    assert cli.DEFAULT_ISLANDS_OUT == draw_commands.DEFAULT_ISLANDS_OUT


def test_owner_manifest_covers_the_two_command_modules():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["batch"] == "540B6"
    assert data["modules"]["commands/__init__.py"] == "assembly"
    assert data["modules"]["commands/draw.py"] == "draw"
    assert len(data["modules"]) == 142
    assert test_owner_rules.LEGACY_EDGES == frozenset()


def test_main_dispatches_through_the_live_draw_registry(monkeypatch):
    seen = []

    def fake_compile(args):
        seen.append(args)
        return 47

    monkeypatch.setitem(cli.DRAW_COMMANDS, "compile", fake_compile)
    code = cli.main([
        "draw", "compile", "--circuit", "c.json", "--presentation", "p.json",
        "--profiles", "s.json",
    ])
    assert code == 47
    assert [(item.command, item.draw_command, item.circuit) for item in seen] == [
        ("draw", "compile", "c.json")
    ]


def test_main_resolves_the_legacy_draw_handler_at_call_time(monkeypatch):
    seen = []

    def fake_legacy(args):
        seen.append(args)
        return 49

    monkeypatch.setattr(cli, "_cmd_draw", fake_legacy)
    assert cli.main(["draw"]) == 49
    assert [(item.command, item.draw_command) for item in seen] == [("draw", None)]


def test_dispatch_draw_calls_the_named_handler_not_legacy():
    args = argparse.Namespace(draw_command="compile")

    def named(_args):
        return 17

    def legacy(_args):
        return 18

    assert draw_commands.dispatch_draw(args, {"compile": named}, legacy) == 17


def test_main_dispatches_edit_through_the_live_registry(monkeypatch):
    seen = []

    def fake_apply(args):
        seen.append(args)
        return 51

    monkeypatch.setitem(cli.EDIT_COMMANDS, "apply", fake_apply)
    assert cli.main(["edit", "apply", "plan.json"]) == 51
    assert [(item.command, item.edit_command, item.plan) for item in seen] == [
        ("edit", "apply", "plan.json")
    ]


def test_main_resolves_lint_and_validate_handlers_at_call_time(monkeypatch):
    monkeypatch.setattr(cli, "_cmd_lint", lambda args: 52)
    monkeypatch.setattr(cli, "_cmd_validate", lambda args: 53)
    assert cli.main(["lint"]) == 52
    assert cli.main(["validate", "--spec", "spec.json"]) == 53


def test_dispatch_edit_calls_the_selected_handler():
    args = argparse.Namespace(edit_command="apply")
    handlers = {"plan": lambda _args: 21, "apply": lambda _args: 22}
    assert draw_commands.dispatch_edit(args, handlers) == 22


def test_main_dispatches_pintable_through_the_live_registry(monkeypatch):
    monkeypatch.setitem(cli.PINTABLE_COMMANDS, "check", lambda args: 54)
    assert cli.main(["pintable", "check", "--table", "table.json"]) == 54
