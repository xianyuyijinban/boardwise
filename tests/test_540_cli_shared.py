"""540B6: shared/assembly CLI extraction completes the 24-command surface."""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import boardwise.cli as cli
from boardwise.commands import assembly as assembly_commands
from boardwise.commands import shared as shared_commands

from test_540_cli_draw import _subparsers
from test_540_shared_naming import PACKAGE, _in_package_imports
import test_owner_rules

ROOT = Path(__file__).resolve().parents[1]
SHARED_DIRECT = {
    "doctor": "_cmd_doctor",
    "compare": "_cmd_compare",
    "persistence": "_cmd_persistence",
    "arch": "_cmd_arch",
}


def test_entry_is_only_parser_assembly_and_24_routes():
    parser_body = inspect.getsource(cli.build_parser)
    assert parser_body.count("register_") == 24
    assert ".add_parser(" not in parser_body
    main_body = inspect.getsource(cli.main)
    assert main_body.count("if args.command ==") == 24
    assert "return _cmd" not in main_body
    assert main_body.count("shared_commands.dispatch_shared(") == len(SHARED_DIRECT)
    for command, handler in SHARED_DIRECT.items():
        assert f'if args.command == "{command}":' in main_body
        assert f"return shared_commands.dispatch_shared(args, {handler})" in main_body
    assert "assembly_commands.dispatch_assembly(args, _cmd_install_skill)" in main_body
    for function, registry in (
        ("dispatch_bridge", "BRIDGE_COMMANDS"),
        ("dispatch_config", "CONFIG_COMMANDS"),
        ("dispatch_intent", "INTENT_COMMANDS"),
    ):
        assert f"shared_commands.{function}(args, {registry})" in main_body


def test_bridge_config_and_intent_subcommand_order_is_frozen():
    top = _subparsers(cli.build_parser())
    bridge = _subparsers(top.choices["bridge"])
    expected_bridge = [
        "start", "status", "revoke", "screenshot", "export-fab", "call",
        "highlight", "update-connector",
    ]
    assert list(bridge.choices) == expected_bridge
    assert list(cli.BRIDGE_COMMANDS) == expected_bridge
    config = _subparsers(top.choices["config"])
    assert list(config.choices) == ["get", "set", "show"]
    assert list(cli.CONFIG_COMMANDS) == ["get", "set", "show"]
    intent = _subparsers(top.choices["intent"])
    assert list(intent.choices) == ["audit", "set-rail"]
    assert list(cli.INTENT_COMMANDS) == ["audit", "set-rail"]
    assert "3.2.149" in top.choices["doctor"].description


def test_shared_and_assembly_modules_have_their_declared_dependencies():
    assert _in_package_imports(PACKAGE / "commands" / "shared.py") == set()
    assert _in_package_imports(PACKAGE / "commands" / "assembly.py") == {
        "skill_install.py"
    }


def test_owner_manifest_covers_the_final_command_modules():
    data = json.loads(
        (ROOT / "contracts" / "module-owners.json").read_text(encoding="utf-8")
    )
    assert data["batch"] == "540B6"
    assert data["modules"]["commands/shared.py"] == "shared"
    assert data["modules"]["commands/assembly.py"] == "assembly"
    assert len(data["modules"]) == 142
    assert test_owner_rules.LEGACY_EDGES == frozenset()


def test_bridge_help_callback_is_resolved_when_parser_is_built(monkeypatch):
    monkeypatch.setattr(cli, "_bridge_help_epilog", lambda: "B6-HELP-SENTINEL")
    top = _subparsers(cli.build_parser())
    assert "B6-HELP-SENTINEL" in top.choices["bridge"].format_help()


def test_main_resolves_direct_shared_and_assembly_handlers(monkeypatch):
    monkeypatch.setattr(cli, "_cmd_compare", lambda args: 81)
    monkeypatch.setattr(cli, "_cmd_install_skill", lambda args: 82)
    assert cli.main(["compare", "candidate.epro2"]) == 81
    assert cli.main(["install-skill"]) == 82


def test_main_dispatches_bridge_and_config_through_live_registries(monkeypatch):
    monkeypatch.setitem(cli.BRIDGE_COMMANDS, "status", lambda args: 83)
    monkeypatch.setitem(cli.CONFIG_COMMANDS, "show", lambda args: 84)
    assert cli.main(["bridge", "status"]) == 83
    assert cli.main(["config", "show"]) == 84


def test_dispatch_bridge_uses_the_selected_registry_entry():
    args = argparse.Namespace(bridge_command="status")
    handlers = {"start": lambda _args: 91, "status": lambda _args: 92}
    assert shared_commands.dispatch_bridge(args, handlers) == 92


def test_dispatch_intent_uses_the_selected_registry_entry():
    args = argparse.Namespace(intent_command="audit")
    handlers = {"set-rail": lambda _args: 93, "audit": lambda _args: 94}
    assert shared_commands.dispatch_intent(args, handlers) == 94
