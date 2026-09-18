"""The CLI's half of the creation gate (006c, work item 6).

The daemon refuses a `create` action without `confirm: true`; this is where a
human gets *asked*. The three behaviours the task names, from the caller's
side:

* `--yes` passes the confirmation straight through (the escape hatch for
  scripts);
* without `--yes`, `CONFIRMATION_REQUIRED` turns into a question, and "yes"
  retries **once** with `confirm: true`;
* "no" — and a stdin that is not a terminal — ends the call instead of
  guessing. A prompt nobody can see must not default to yes.

The daemon is replaced by a recording stub: what is under test is the CLI's
decisions, not the socket.
"""

from __future__ import annotations

import argparse
import io
import json

import pytest

from boardwise.bridge.protocol import BridgeError, ErrorCodes
from boardwise import cli


class RecordingClient:
    """Stands in for `BridgeClient`; records every call it is asked to make."""

    def __init__(self, refusals: int = 1):
        self.calls: list[dict] = []
        #: How many times it answers CONFIRMATION_REQUIRED before succeeding —
        #: models the daemon gate faithfully, including "always".
        self.refusals = refusals

    @classmethod
    async def open(cls, *_args, **_kwargs):
        return cls.instance

    async def call(self, action, params):
        self.calls.append({"action": action, "params": dict(params)})
        if self.refusals > 0 and params.get("confirm") is not True:
            self.refusals -= 1
            raise BridgeError(
                ErrorCodes.CONFIRMATION_REQUIRED,
                f"{action} creates a new document; re-send with confirm: true",
                {"action": action, "risk": "create", "confirm": params.get("confirm")},
            )
        return {"pcbUuid": "pcb-1", "focused": True}

    async def close(self):
        return None


class AlwaysRefusing(RecordingClient):
    """Refuses even with confirm — models a gate that cannot be lifted."""

    async def call(self, action, params):
        self.calls.append({"action": action, "params": dict(params)})
        raise BridgeError(
            ErrorCodes.CONFIRMATION_REQUIRED,
            "still refusing",
            {"action": action},
        )


def _patch(monkeypatch, stub_class, refusals: int = 1):
    """Install `stub_class` as the client, with its own instance.

    The instance is set *per class*: `open` resolves `cls.instance`, so a
    subclass that inherited a previous test's instance would answer for the
    wrong stub — which is exactly how the first version of this file produced a
    green result from a stub that was supposed to always refuse.
    """
    stub_class.instance = stub_class(refusals=refusals)
    monkeypatch.setattr(
        cli,
        "_open_cli",
        lambda _args: (stub_class, BridgeError, 61190, "test-token"),
    )
    return stub_class.instance


def _args(*extra: str) -> argparse.Namespace:
    parser = cli.build_parser()
    return parser.parse_args(["bridge", "call", "--action", "pcb.doc.new", *extra])


def _no_tty(monkeypatch):
    """A piped stdin: `isatty()` false, so nothing can be asked."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))


def _tty(monkeypatch, answer: str):
    class TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", TTY(""))
    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)


def test_yes_passes_the_confirmation_without_asking(monkeypatch):
    client = _patch(monkeypatch, RecordingClient)
    # `--yes` must work with no terminal at all: that is its whole purpose.
    _no_tty(monkeypatch)

    assert cli._cmd_bridge_call(_args("--yes")) == 0
    assert len(client.calls) == 1, "exactly one call: no refusal to recover from"
    assert client.calls[0]["params"]["confirm"] is True


def test_a_non_tty_stdin_ends_the_call_rather_than_assuming_yes(monkeypatch, capsys):
    client = _patch(monkeypatch, RecordingClient)
    _no_tty(monkeypatch)

    code = cli._cmd_bridge_call(_args())
    assert code == 1, "the refusal must surface, not be answered on the user's behalf"
    assert len(client.calls) == 1, "no retry without consent"
    assert "confirm" not in client.calls[0]["params"]
    err = capsys.readouterr().err
    assert "--yes" in err, "tell the caller how to proceed non-interactively"
    assert "not a terminal" in err


def test_answering_yes_retries_once_with_the_confirmation(monkeypatch, capsys):
    client = _patch(monkeypatch, RecordingClient)
    _tty(monkeypatch, "y")

    assert cli._cmd_bridge_call(_args()) == 0
    assert len(client.calls) == 2, "one refusal, one retry"
    assert "confirm" not in client.calls[0]["params"]
    assert client.calls[1]["params"]["confirm"] is True
    out = capsys.readouterr().out
    assert json.loads(out)["pcbUuid"] == "pcb-1"


@pytest.mark.parametrize("answer", ["", "n", "no", "N", "maybe"])
def test_anything_but_yes_declines(monkeypatch, answer):
    client = _patch(monkeypatch, RecordingClient)
    _tty(monkeypatch, answer)

    assert cli._cmd_bridge_call(_args()) == 1
    assert len(client.calls) == 1, f"answer {answer!r} must not retry"


def test_confirm_is_sent_once_and_is_a_boolean(monkeypatch):
    """`True`, not `"true"` — the daemon checks identity, not truthiness."""
    client = _patch(monkeypatch, RecordingClient)
    _tty(monkeypatch, "yes")

    cli._cmd_bridge_call(_args())
    sent = client.calls[-1]["params"]["confirm"]
    assert sent is True
    assert not isinstance(sent, str)


def test_params_still_parse_and_a_non_object_is_rejected(monkeypatch, capsys):
    client = _patch(monkeypatch, RecordingClient)
    _no_tty(monkeypatch)

    args = cli.build_parser().parse_args(
        ["bridge", "call", "--action", "pcb.doc.new", "--yes", "--params", "[1,2]"]
    )
    assert cli._cmd_bridge_call(args) == 2
    assert client.calls == [], "nothing should be sent for malformed params"
    assert "JSON object" in capsys.readouterr().err


def test_an_unliftable_refusal_is_reported_not_looped(monkeypatch, capsys):
    """If confirm was already sent and the daemon still refuses, stop.

    Looping would hammer the daemon; silently succeeding would be worse.
    """
    _patch(monkeypatch, AlwaysRefusing)
    _tty(monkeypatch, "y")

    assert cli._cmd_bridge_call(_args()) == 1
    err = capsys.readouterr().err
    assert ErrorCodes.CONFIRMATION_REQUIRED in err
