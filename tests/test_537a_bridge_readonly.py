"""537A: `bridge call --read-only`, the CLI-side hard gate.

The DSH ``boardwise_bridge`` tool is *documented* as read-only, but until 537A it
forwarded whatever action it was given, and the daemon only grades risk — it
refuses ``create``/``dangerous`` without confirmation, but a plain ``write``
(``doc.focus``, ``sch.place_wire``, ``sch.delete_primitives`` …) went straight
to the editor. This file pins the gate that closes the hole **before** the CLI
opens a socket or starts a daemon on demand:

* ``write`` / ``create`` / ``dangerous`` are refused locally with a non-zero
  exit, and the refusal names the action, the catalogue risk, ``--read-only``
  and the fact that **nothing was forwarded**;
* an action the catalogue does not know cannot be certified as ``read``, so it
  is refused the same way — the gate must not turn an unknown name into a
  connection attempt;
* a ``read`` action (daemon-owned ``ping`` and connector-owned reads) travels
  the old path untouched;
* without the flag every old behaviour stands, including forwarding a write and
  an unknown action so the daemon answers under its own codes.

The fake door is `_open_cli` itself: every case asserts whether it was reached,
so "refused before connecting" is the property under test, not an inference from
the message. The one end-to-end case points at a dead port with auto-start off,
where a connection attempt would surface as "daemon not reachable".

No test here talks to a daemon, an editor or a real bridge.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise.bridge.protocol import BridgeError, action_spec
from boardwise.cli import _cmd_bridge_call, build_parser

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _args(*argv: str):
    return build_parser().parse_args(["bridge", "call", *argv])


@pytest.fixture
def door(monkeypatch):
    """Replace `_open_cli` with a recorder — the gate must not need a socket.

    Returns ``(opened, clients)``: ``opened`` collects one entry per call that
    reached the door, ``clients`` the fake clients those calls produced. The
    client class is built per test so no case can see another's sent frames.
    """
    opened: list = []
    clients: list = []

    class FakeClient:
        """Records what would have gone over the wire."""

        def __init__(self) -> None:
            self.sent: list[dict] = []

        @classmethod
        async def open(cls, *args, **kwargs):
            client = cls()
            clients.append(client)
            return client

        async def call(self, action: str, params: dict, **kwargs) -> dict:
            self.sent.append({"action": action, "params": dict(params), **kwargs})
            return {"ok": True, "action": action}

        async def close(self) -> None:
            return None

    def fake_open(args):
        opened.append(args)
        return FakeClient, BridgeError, 1, "token"

    monkeypatch.setattr("boardwise.cli._open_cli", fake_open)
    return opened, clients


# --------------------------------------------------------------------------
# Refusals: before the door, with the four facts in stderr
# --------------------------------------------------------------------------

#: One action per non-read tier. The risk is looked up in the catalogue inside
#: the test as well, so this table cannot drift into an assumption of its own.
NON_READ = (
    ("doc.focus", "write"),
    ("sch.doc.new", "create"),
    ("sys.self_update", "dangerous"),
)


@pytest.mark.parametrize(("action", "risk"), NON_READ)
def test_read_only_refuses_non_read_actions_before_any_connection(
    action, risk, door, capsys
):
    opened, clients = door
    # The catalogue is the authority for both halves of this row.
    spec = action_spec(action)
    assert spec is not None and spec.risk == risk

    code = _cmd_bridge_call(_args("--action", action, "--read-only"))

    captured = capsys.readouterr()
    assert code != 0, "a refused action must not look like a successful call"
    assert captured.out == "", "nothing should be printed as if a payload came back"
    assert action in captured.err
    assert f"risk={risk}" in captured.err
    assert "--read-only" in captured.err
    assert "Nothing was forwarded" in captured.err
    assert "READ_ONLY_VIOLATION" in captured.err
    # The whole point: the refusal happened before the one door to the bridge.
    assert opened == []
    assert clients == []


def test_read_only_refuses_an_unknown_action_without_connecting(door, capsys):
    """An unknown name has no risk, so it cannot be *certified* as read.

    Forwarding it would be a connection operation taken on behalf of a model
    tool; the daemon's `UNKNOWN_ACTION` is the right answer only for a caller
    that did not ask for the read-only gate.
    """
    opened, clients = door

    code = _cmd_bridge_call(_args("--action", "no.such.action", "--read-only"))

    captured = capsys.readouterr()
    assert code != 0
    assert captured.out == ""
    assert "no.such.action" in captured.err
    assert "risk=unknown" in captured.err
    assert "not in the action catalogue" in captured.err
    assert "--read-only" in captured.err
    assert "Nothing was forwarded" in captured.err
    assert opened == []
    assert clients == []


def test_yes_does_not_widen_the_read_only_gate(door, capsys):
    """`--yes` answers the daemon's confirmation question; it cannot outrank a
    refusal the CLI made *before* the daemon was ever asked."""
    opened, _clients = door

    code = _cmd_bridge_call(_args("--action", "sch.doc.new", "--read-only", "--yes"))

    captured = capsys.readouterr()
    assert code != 0
    assert "risk=create" in captured.err
    assert "confirm" not in captured.out
    assert opened == []


# --------------------------------------------------------------------------
# Allowed: read actions still travel the old path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "owner"),
    (
        ("ping", "daemon"),
        ("doc.list", "connector"),
        ("sch.readback", "connector"),
    ),
)
def test_read_only_allows_read_actions_on_the_old_path(action, owner, door, capsys):
    opened, clients = door
    spec = action_spec(action)
    assert spec is not None and spec.risk == "read" and spec.owner == owner

    code = _cmd_bridge_call(
        _args("--action", action, "--read-only", "--params", '{"page": "sch"}')
    )

    captured = capsys.readouterr()
    assert code == 0
    assert len(opened) == 1, "a read action must still reach the daemon door"
    assert clients[0].sent == [{"action": action, "params": {"page": "sch"}}]
    assert json.loads(captured.out) == {"ok": True, "action": action}


# --------------------------------------------------------------------------
# The old contract: no flag, no change
# --------------------------------------------------------------------------


def test_parser_defaults_to_the_old_behaviour():
    assert _args("--action", "doc.list").read_only is False
    assert _args("--action", "doc.list", "--read-only").read_only is True


def test_without_the_flag_a_write_action_is_forwarded_as_before(door, capsys):
    opened, clients = door

    code = _cmd_bridge_call(
        _args("--action", "doc.focus", "--params", '{"pageType": "sch"}')
    )

    assert code == 0
    assert len(opened) == 1
    assert clients[0].sent == [
        {"action": "doc.focus", "params": {"pageType": "sch"}}
    ]
    assert json.loads(capsys.readouterr().out) == {"ok": True, "action": "doc.focus"}


def test_without_the_flag_an_unknown_action_still_reaches_the_daemon(door):
    """`UNKNOWN_ACTION` stays the daemon's answer; the new gate must not move
    that judgement into the CLI for callers that did not ask for read-only."""
    opened, clients = door

    code = _cmd_bridge_call(_args("--action", "no.such.action"))

    assert code == 0
    assert len(opened) == 1
    assert clients[0].sent == [{"action": "no.such.action", "params": {}}]


# --------------------------------------------------------------------------
# Process level: the gate fires before the door, not after it
# --------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _env(home: Path, port: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    # 157's switch: a refused write must not start a daemon either.
    env["BOARDWISE_NO_AUTO_DAEMON"] = "1"
    return env


def test_the_refusal_happens_before_the_cli_reaches_for_the_daemon(tmp_path):
    result = subprocess.run(
        [
            sys.executable, "-m", "boardwise.cli",
            "bridge", "call", "--action", "doc.focus", "--read-only",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(tmp_path, _free_port()),
        timeout=60,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "READ_ONLY_VIOLATION" in result.stderr
    assert "Nothing was forwarded" in result.stderr
    # If the gate ran after `_open_cli`, a dead port is what this would say.
    assert "daemon not reachable" not in result.stderr
    assert result.stdout == ""
