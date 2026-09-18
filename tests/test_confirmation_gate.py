"""The creation gate (006c, work item 6).

岳翔宇's hard rule: creating a schematic page or a PCB **must be asked for
first**. The mechanism is a single choke point on the daemon — `create`-risk
actions are refused unless `params.confirm is True`, and `confirm` is consumed
there so it never reaches the connector.

These tests pin the three properties the task names:

1. a `create` action without `confirm` is refused with
   ``CONFIRMATION_REQUIRED``, and nothing was forwarded;
2. a non-``True`` ``confirm`` (a string, a number) is refused just the same —
   the check is identity, not truthiness;
3. the `confirm` parameter does not appear in the forwarded frame.

The connector's silence is the point of the design, so the tests also assert
the *reverse*: a `write` action carrying `confirm` has it stripped and is
forwarded as if the flag had never existed.
"""

from __future__ import annotations

import pytest

import test_bridge as tb
from boardwise.bridge.daemon import BridgeDaemon
from boardwise.bridge.protocol import ErrorCodes, action_spec

run = tb.run
TOKEN = tb.TOKEN

#: Actions from each risk class, so the gate's scope is asserted, not assumed.
CREATE_ACTIONS = ("sch.doc.new", "pcb.doc.new")
WRITE_ACTIONS = ("sch.place_wire", "doc.rename", "sch.doc.save")
READ_ACTIONS = ("doc.list", "sch.geometry", "doc.open")


# --------------------------------------------------------------------------
# the gate itself — no socket needed: it runs before anything is forwarded
# --------------------------------------------------------------------------


def test_create_actions_are_the_ones_the_gate_guards():
    for name in CREATE_ACTIONS:
        spec = action_spec(name)
        assert spec is not None and spec.risk == "create", name
    for name in WRITE_ACTIONS:
        assert action_spec(name).risk == "write", name
    for name in READ_ACTIONS:
        assert action_spec(name).risk == "read", name


@pytest.mark.parametrize("action", CREATE_ACTIONS)
def test_create_without_confirm_is_refused(tmp_path, action):
    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    spec = action_spec(action)
    with pytest.raises(Exception) as caught:
        run(daemon.handle_request(action, {}, "cli"))
    error = caught.value
    assert error.code == ErrorCodes.CONFIRMATION_REQUIRED
    # The message has to tell the caller what to do, or it is just a wall.
    assert "confirm" in error.message
    assert error.detail["action"] == action
    assert error.detail["risk"] == "create"
    assert error.detail["confirm"] is None
    assert spec.risk == "create"


@pytest.mark.parametrize(
    "confirm", ["true", "yes", 1, 0, [], {}, "True", None, False]
)
def test_create_with_a_non_true_confirm_is_refused(tmp_path, confirm):
    """Identity, not truthiness: only the boolean ``True`` opens the gate.

    `"yes"` and `1` are what a shell script reaches for, and accepting them
    would make the gate's meaning depend on the caller's language. `[]` and
    `{}` are here because they are falsy-but-not-False; `"True"` because it is
    the string that *looks* like the answer.
    """
    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    with pytest.raises(Exception) as caught:
        run(daemon.handle_request("pcb.doc.new", {"confirm": confirm}, "cli"))
    assert caught.value.code == ErrorCodes.CONFIRMATION_REQUIRED
    # `confirm` is echoed in the detail so a caller can see what was rejected.
    assert caught.value.detail["confirm"] == confirm


@pytest.mark.parametrize("action", CREATE_ACTIONS)
def test_create_with_confirm_true_passes_the_gate(tmp_path, action):
    """The gate must be passable — a refusal nobody can lift is a broken action.

    With no connector attached the flow moves on to the connector check, which
    is the next thing after the gate; reaching *that* proves the gate opened.
    """
    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    with pytest.raises(Exception) as caught:
        run(daemon.handle_request(action, {"confirm": True}, "cli"))
    assert caught.value.code == ErrorCodes.NO_CONNECTOR, (
        f"{action} should have passed the gate and failed later on the missing "
        "connector, not been refused again"
    )


@pytest.mark.parametrize("action", CREATE_ACTIONS + WRITE_ACTIONS + READ_ACTIONS)
def test_the_confirm_parameter_never_survives_the_gate(tmp_path, action):
    """Consumed on the way through, for every risk class.

    Stripping it uniformly is what keeps the connector a plain executor: it has
    no concept of confirmation, so it cannot be persuaded to create something
    the daemon declined, and it cannot accidentally depend on the flag either.
    """
    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    spec = action_spec(action)
    forwarded = daemon._gate_confirmation(spec, {"confirm": True, "keep": "me"})
    assert "confirm" not in forwarded
    assert forwarded == {"keep": "me"}


def test_the_gate_is_driven_by_risk_not_by_the_declared_params(tmp_path):
    """A create action that forgot to list `confirm` must still be gated.

    Keying the gate on `params` would fail *open*: the omission that makes the
    parameter undiscoverable would also make the action ungated. This simulates
    that entry and asserts the refusal still happens.
    """
    from boardwise.bridge.protocol import Action

    daemon = BridgeDaemon(token=TOKEN, home=tmp_path)
    forgetful = Action(
        name="sch.doc.new",
        summary="simulated entry that forgot to declare confirm",
        risk="create",
        params=("name",),  # ← no confirm
    )
    with pytest.raises(Exception) as caught:
        daemon._gate_confirmation(forgetful, {})
    assert caught.value.code == ErrorCodes.CONFIRMATION_REQUIRED
    # ...and the real entry does declare it, so callers can discover it.
    assert "confirm" in action_spec("sch.doc.new").params


# --------------------------------------------------------------------------
# end to end — over a real socket, with a stand-in connector
# --------------------------------------------------------------------------


def test_nothing_reaches_the_connector_when_a_create_is_refused(tmp_path):
    """The refusal happens before the forward, so the editor never sees it."""

    async def scenario():
        daemon = tb._daemon(tmp_path)
        server, port = await tb._start(daemon)
        async with server:
            connector_ws, _ = await tb._hello(port, "connector", token=TOKEN)
            fake = tb.FakeConnector(connector_ws, responses={"pcb.doc.new": {"pcbUuid": "p"}})
            import asyncio

            serving = asyncio.create_task(fake.serve())

            cli_ws, _ = await tb._hello(port, "cli", token=TOKEN)
            await cli_ws.send(tb.request_frame("pcb.doc.new", {}, id="r1"))
            reply = await tb._recv_frame(cli_ws)
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.CONFIRMATION_REQUIRED

            # Give any (wrong) forward a chance to arrive before asserting.
            await asyncio.sleep(0.05)
            assert fake.received == [], (
                "the refused create was forwarded to the connector anyway: "
                f"{fake.received}"
            )

            # …and with confirm it *does* go through, without the flag.
            await cli_ws.send(
                tb.request_frame("pcb.doc.new", {"confirm": True, "boardName": "B"}, id="r2")
            )
            reply2 = await tb._recv_frame(cli_ws)
            assert reply2["ok"] is True
            assert reply2["data"] == {"pcbUuid": "p"}
            assert len(fake.received) == 1
            forwarded = fake.received[0]
            assert forwarded["action"] == "pcb.doc.new"
            assert "confirm" not in (forwarded.get("params") or {}), (
                f"confirm reached the connector: {forwarded['params']}"
            )
            assert forwarded["params"] == {"boardName": "B"}

            serving.cancel()
            await connector_ws.close()
            await cli_ws.close()

    run(scenario())
