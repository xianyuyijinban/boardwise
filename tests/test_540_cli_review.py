"""540B5: review CLI registration/dispatch moves without behavior drift."""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import boardwise.cli as cli
from boardwise.commands import review as review_commands

from test_540_cli_draw import _subparsers
from test_540_shared_naming import PACKAGE, _in_package_imports
import test_owner_rules

ROOT = Path(__file__).resolve().parents[1]

DIRECT_HANDLERS = {
    "review": "_cmd_review",
    "checkup": "_cmd_checkup",
    "review-eval": "_cmd_review_eval",
    "review-mark": "_cmd_review_mark",
    "need-datasheet": "_cmd_need_datasheet",
    "triage": "_cmd_triage",
    "triage-batch": "_cmd_triage_batch",
    "review-evidence": "_cmd_review_evidence",
    "review-read": "_cmd_review_read",
}
PARTS_PARSER_COMMANDS = [
    "missing", "show", "list", "add", "accept-unknown", "fetch", "hunt",
    "classify", "select",
]
PARTS_REGISTRY_COMMANDS = [
    "select", "missing", "show", "list", "add", "accept-unknown", "fetch",
    "hunt", "classify",
]


def test_all_review_routes_use_the_command_module():
    body = inspect.getsource(cli.main)
    assert body.count("review_commands.dispatch_review(") == len(DIRECT_HANDLERS)
    for command, handler in DIRECT_HANDLERS.items():
        assert f'if args.command == "{command}":' in body
        assert f"return review_commands.dispatch_review(args, {handler})" in body
    assert "return review_commands.dispatch_parts(args, PARTS_COMMANDS)" in body
    assert "return review_commands.dispatch_bom(args, BOM_COMMANDS)" in body


def test_parts_and_bom_subcommand_order_is_frozen():
    top = _subparsers(cli.build_parser())
    parts = _subparsers(top.choices["parts"])
    assert list(parts.choices) == PARTS_PARSER_COMMANDS
    assert list(cli.PARTS_COMMANDS) == PARTS_REGISTRY_COMMANDS
    bom = _subparsers(top.choices["bom"])
    assert list(bom.choices) == ["export"]
    assert list(cli.BOM_COMMANDS) == ["export"]


def test_review_command_module_dependencies_stay_inside_review():
    assert _in_package_imports(PACKAGE / "commands" / "review.py") == {
        "engines/checkup.py", "engines/reviewread.py",
    }
    assert review_commands.TRIAGE_VERDICT_CHOICES is cli.TRIAGE_VERDICT_CHOICES
    assert review_commands.REVIEW_READ_SECTIONS is cli.REVIEW_READ_SECTIONS


def test_owner_manifest_covers_review_commands():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["batch"] == "540B6"
    assert data["modules"]["commands/review.py"] == "review"
    assert len(data["modules"]) == 142
    assert test_owner_rules.LEGACY_EDGES == frozenset()


def test_main_resolves_a_review_handler_at_call_time(monkeypatch):
    monkeypatch.setattr(cli, "_cmd_review", lambda args: 61)
    assert cli.main(["review"]) == 61


def test_main_dispatches_parts_and_bom_through_live_registries(monkeypatch):
    monkeypatch.setitem(cli.PARTS_COMMANDS, "missing", lambda args: 62)
    monkeypatch.setitem(cli.BOM_COMMANDS, "export", lambda args: 63)
    assert cli.main(["parts", "missing", "--file", "board.epro2"]) == 62
    assert cli.main(["bom", "export", "--spec", "spec.json"]) == 63


def test_dispatch_parts_uses_the_selected_registry_entry():
    args = argparse.Namespace(parts_command="missing")
    handlers = {"select": lambda _args: 71, "missing": lambda _args: 72}
    assert review_commands.dispatch_parts(args, handlers) == 72
