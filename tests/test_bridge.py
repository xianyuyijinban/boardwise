"""Protocol-level bridge tests with a fake connector over a real WebSocket.

There is no EasyEDA in CI, so the connector is faked — but the socket is real:
every test starts a daemon on an OS-assigned port (never 61190) and drives the
same handshake, framing and routing the TypeScript extension will use. What is
*not* covered here is the ``eda.*`` calls themselves; those need the manual
checklist in ``docs/bridge.md``.

pytest-asyncio is not a dependency, so each test wraps one coroutine in
``asyncio.run`` and leaves the loop to itself.
"""

import asyncio
import base64
import json
import struct
import time
import zlib
from pathlib import Path

import pytest
import websockets
from websockets.protocol import State

from boardwise.bridge.daemon import (
    AUDIT_CONNECTOR_REJECTED,
    AUDIT_PAIRING,
    AUDIT_REPAIRING,
    MIN_CONNECTOR_VERSION,
    UNKNOWN_CONNECTOR_VERSION,
    WINDOW_KEY_SEPARATOR,
    AUDIT_REVOKE,
    BridgeDaemon,
    PendingCall,
    WindowConnection,
    _bound_port,
    _clock,
    check_origin,
    connector_fingerprint,
    connector_token_path,
    load_connector_token,
    revoke_connector_token,
    start_server,
    status_lines,
    window_listing,
)
from boardwise.bridge.protocol import (
    CONTEXT_KEYS,
    EVENT_BANNER,
    HELLO_TIMEOUT,
    PROTOCOL_VERSION,
    BridgeError,
    Connection,
    ErrorCodes,
    banner_frame,
    context_of,
    decode_frame,
    error_frame,
    frame_kind,
    merge_context,
    request_frame,
    response_frame,
)

TOKEN = "test-token-not-a-real-secret"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakeConnector:
    """Stands in for the .eext: answers actions with canned data.

    ``contexts`` maps an action name to the ``context`` object that action's
    response carries (023 §协议字段约定) — the window's live project/page at the
    moment it ran. Left empty it sends no context at all, which is exactly what a
    pre-023 connector build does, so every test that does not ask for one is also
    a backwards-compatibility test.
    """

    def __init__(self, websocket, responses=None, errors=None, contexts=None):
        self.ws = websocket
        self.responses = responses or {}
        self.errors = errors or {}
        self.contexts = contexts or {}
        self.received: list[dict] = []

    async def serve(self):
        async for raw in self.ws:
            frame = decode_frame(raw)
            if frame_kind(frame) != "request":
                # Either our own response echoing back, or the daemon's banner.
                continue
            self.received.append(frame)
            action = frame.get("action")
            if action in self.errors:
                await self.ws.send(error_frame(
                    frame.get("id"), self.errors[action],
                    context=self.contexts.get(action),
                ))
            else:
                await self.ws.send(response_frame(
                    frame.get("id"),
                    self.responses.get(action, {}),
                    context=self.contexts.get(action),
                ))


def _daemon(home: Path) -> BridgeDaemon:
    return BridgeDaemon(token=TOKEN, home=home)


async def _start(daemon: BridgeDaemon) -> tuple[object, int]:
    server = await start_server(daemon, "127.0.0.1", 0)
    return server, _bound_port(server)


async def _recv_frame(ws) -> dict:
    """Read the next frame that is not an event.

    The daemon sends a banner the moment the socket opens (docs/bridge.md §3),
    so every read has to step over it. This is the same problem both real
    clients have, handled the same way.
    """
    while True:
        frame = decode_frame(await ws.recv())
        if frame_kind(frame) != "event":
            return frame


async def _recv_event(ws) -> dict:
    """Read the next frame, requiring it to be an event."""
    frame = decode_frame(await ws.recv())
    assert frame_kind(frame) == "event", f"expected an event frame, got {frame}"
    return frame


async def _hello(
    port: int,
    role: str,
    token=TOKEN,
    protocol=PROTOCOL_VERSION,
    headers: dict | None = None,
    client: str = "fake",
    **extra: object,
):
    """Connect, expect the daemon's banner first, then answer with ``hello``.

    ``extra`` is merged into the hello params, which is how a connector
    announces optional fields such as ``connectorVersion``.
    """
    ws = await websockets.connect(
        f"ws://127.0.0.1:{port}", max_size=None, additional_headers=headers
    )
    await _recv_event(ws)
    await ws.send(request_frame("hello", {
        "token": token, "role": role, "protocol": protocol, "client": client,
        **extra,
    }, id="hello"))
    return ws, await _recv_frame(ws)


def _audit_records(home: Path) -> list[dict]:
    """Every audit record written under ``home``, oldest first."""
    records: list[dict] = []
    for path in sorted((home / "audit").glob("*.jsonl")):
        records.extend(
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
    return records


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=20))


async def _until(predicate, timeout: float = 5.0):
    """Poll until `predicate()` holds, or fail after `timeout` seconds.

    The daemon removes a window from the hub in its handler's `finally`, which
    runs when it notices the close — not the instant the client decides to
    close. Waiting for the condition is the honest way to say "no connector is
    attached"; a fixed sleep would be a guess about someone else's event loop.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never became true")


# --------------------------------------------------------------------------
# framing (no socket needed)
# --------------------------------------------------------------------------


def test_request_and_response_frames():
    request = decode_frame(request_frame("ping", {}, id="abc"))
    assert request == {"id": "abc", "action": "ping"}

    ok = decode_frame(response_frame("abc", {"pong": True}))
    assert ok == {"id": "abc", "ok": True, "data": {"pong": True}}

    bad = decode_frame(error_frame("abc", BridgeError(ErrorCodes.NO_CONNECTOR, "nope")))
    assert bad["ok"] is False
    assert bad["error"]["code"] == ErrorCodes.NO_CONNECTOR


def test_decode_frame_rejects_garbage():
    for raw in ("not json", "[]", '{"action": ""}'):
        with pytest.raises(BridgeError) as excinfo:
            decode_frame(raw)
        assert excinfo.value.code == ErrorCodes.BAD_REQUEST


def test_a_request_frame_carries_a_window_hint_only_when_it_is_given():
    """`targetInstance` is optional, and absent means absent (023 follow-up).

    The same rule the project hint follows: a caller that named nothing sends the
    pre-023 frame, and a caller that named a window sends exactly one field — not
    an empty string that would read as "route to the window called ''".
    """
    plain = decode_frame(request_frame("doc.list", {}, id="a"))
    assert plain == {"id": "a", "action": "doc.list"}

    named = decode_frame(request_frame("doc.list", {}, id="b", target_instance=" inst-x "))
    assert named["targetInstance"] == "inst-x"
    # Both hints may ride one frame; which one wins is the daemon's call, not
    # this function's (it must not drop either).
    both = decode_frame(request_frame(
        "doc.list", {}, id="c", target_project="test2", target_instance="inst-x"))
    assert both["targetProject"] == "test2" and both["targetInstance"] == "inst-x"


def test_frame_kind_classifies_by_the_strongest_key():
    assert frame_kind({"id": "a", "action": "ping"}) == "request"
    assert frame_kind({"id": "a", "ok": True, "data": {}}) == "response"
    assert frame_kind({"event": EVENT_BANNER}) == "event"
    # Precedence, for a frame that somehow carries two kinds: `ok` > `event`
    # > `action`. Predicting the odd case beats leaving it undefined.
    assert frame_kind({"ok": False, "event": EVENT_BANNER}) == "response"
    assert frame_kind({"event": EVENT_BANNER, "action": "ping"}) == "event"


def test_banner_frame_is_an_event_and_carries_no_secret():
    frame = decode_frame(banner_frame())
    assert frame_kind(frame) == "event"
    assert frame["event"] == EVENT_BANNER
    assert frame["data"]["expect"] == "hello"
    # It arrives before authentication, so it may only say what is already
    # public about the daemon — and nothing correlates with it.
    assert "id" not in frame
    assert "token" not in json.dumps(frame).lower()


# --------------------------------------------------------------------------
# handshake
# --------------------------------------------------------------------------


def test_hello_accepts_valid_token(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector")
            assert reply["ok"] is True
            assert reply["data"]["role"] == "connector"
            assert reply["data"]["protocol"] == PROTOCOL_VERSION
            assert daemon.has_connector()
            await ws.close()

    run(scenario())


def test_hello_rejects_bad_token(tmp_path):
    """Once a connector is paired, only *that* token is accepted.

    The very first connection is trusted by design (task 004c), so the
    rejection this test is about can only be observed afterwards — which is
    precisely the case that matters, because "afterwards" is when a different
    local process would be trying the daemon.

    The paired connector stays attached for the attempt. That is the condition
    under which refusing is correct: since 004f an unattached pairing may be
    re-taken (a sideload resets the extension's storage and with it the token),
    so "a stranger is refused" and "a stranger may re-pair" are different
    scenarios and this test is about the first one.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="the-real-one")
            assert first["ok"] is True
            assert load_connector_token(tmp_path) == "the-real-one"
            assert daemon.has_connector()

            ws, reply = await _hello(port, "connector", token="wrong")
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            # A refused connection must not disturb the pairing it failed.
            assert load_connector_token(tmp_path) == "the-real-one"
            await ws.close()
            await first_ws.close()

    run(scenario())


def test_a_new_token_re_pairs_when_nothing_is_attached(tmp_path):
    """The sideload self-heal (004f item 2).

    Sideloading a connector build resets the editor's extension storage, so the
    new build invents a fresh token and is then refused by the pairing *it*
    wrote on the previous run — an `UNAUTHENTICATED` loop that used to need a
    manual `bridge revoke`. With no connector attached the newcomer is not
    displacing anyone, so it is accepted and the replacement is announced.
    """

    notices = []

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_pairing=notices.append)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="before-sideload")
            assert first["ok"] is True
            await first_ws.close()
            # The editor's storage was wiped; the socket went with it. The
            # daemon notices the close asynchronously, so wait for the fact
            # rather than assuming it.
            await _until(lambda: not daemon.has_connector())
            assert not daemon.has_connector()

            ws, reply = await _hello(port, "connector", token="after-sideload")
            assert reply["ok"] is True, "an unattached pairing may be re-taken"
            assert load_connector_token(tmp_path) == "after-sideload"
            await ws.close()

    run(scenario())

    assert len(notices) == 2
    assert notices[0].repaired is False
    assert notices[1].repaired is True
    assert notices[1].replaced == connector_fingerprint("before-sideload")

    records = [record for record in _audit_records(tmp_path)
               if record["action"] in (AUDIT_PAIRING, AUDIT_REPAIRING)]
    assert [record["action"] for record in records] == [AUDIT_PAIRING, AUDIT_REPAIRING]
    assert records[1]["replacedFingerprint"] == connector_fingerprint("before-sideload")
    # The wording has to say what happened, not just that something did.
    assert "re-paired" in "\n".join(notices[1].console_lines())


def test_a_live_connector_is_not_displaced_by_a_new_token(tmp_path):
    """The other half: attached means attached.

    Re-pairing is only legitimate when nobody is being displaced. A second
    connector with a different token while one is attached is refused even
    though its token is unknown — otherwise anything on loopback could take the
    pairing from a healthy editor.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            live, first = await _hello(port, "connector", token="live-one")
            assert first["ok"] is True
            assert daemon.has_connector()

            intruder, reply = await _hello(port, "connector", token="intruder")
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            assert load_connector_token(tmp_path) == "live-one"
            await intruder.close()
            await live.close()

    run(scenario())

    assert not [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_REPAIRING]


def test_hello_records_the_connector_build_version(tmp_path):
    """Every connection leaves "which build was this" in the audit log (004f 5).

    Two sideloads in a row looked successful while the editor kept running the
    previous bundle, and the only symptom was a stack pointing at a line that
    had already been fixed. `sys.probe` answers the question — but only when
    someone thinks to ask, which is afterwards. The handshake is the one moment
    every build passes through.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", connectorVersion="0.4.1")
            assert reply["ok"] is True
            await ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert len(greetings) == 1
    assert greetings[0]["connectorVersion"] == "0.4.1"
    # …and it rides along in the `client` line, which is the part a human reads.
    assert "connector=0.4.1" in greetings[0]["client"]


def test_an_old_connector_without_a_version_is_accepted_and_marked(tmp_path):
    """Missing field is not a fault — it is an unknown, and it says so.

    Refusing connectors built before 0.4.1 would break the very upgrade this
    is meant to observe. The absence is recorded as "(version unknown)" so that
    an old build cannot be mistaken for a modern one that forgot its name.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector")  # no connectorVersion
            assert reply["ok"] is True, "backwards compatible by design"
            await ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert greetings[0]["connectorVersion"] is None
    assert greetings[0]["client"].endswith(UNKNOWN_CONNECTOR_VERSION)


def test_hello_rejects_unknown_role(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "wizard")
            assert reply["error"]["code"] == ErrorCodes.BAD_REQUEST
            await ws.close()

    run(scenario())


def test_first_frame_must_be_hello(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=None)
            await _recv_event(ws)  # the banner is not a request, it does not count
            await ws.send(request_frame("ping", {}, id="1"))
            reply = await _recv_frame(ws)
            assert reply["error"]["code"] == ErrorCodes.PROTOCOL_VIOLATION
            await ws.close()

    run(scenario())


def test_version_mismatch_is_reported(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", protocol="9.9")
            assert reply["error"]["code"] == ErrorCodes.VERSION_MISMATCH
            await ws.close()

    run(scenario())


# --------------------------------------------------------------------------
# pairing: trust on first use (task 004c)
# --------------------------------------------------------------------------


def test_version_mismatch_never_pairs(tmp_path):
    """A connector we cannot talk to must not become the paired one.

    Pairing is a commitment. Writing a record for a version we would then
    refuse would lock out the working connector that comes next, and the
    resulting `UNAUTHENTICATED` would point at the wrong problem entirely —
    which is why the version check runs before the secret is stored.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", protocol="9.9")
            assert reply["error"]["code"] == ErrorCodes.VERSION_MISMATCH
            await ws.close()
            assert load_connector_token(tmp_path) is None
            assert not connector_token_path(tmp_path).exists()

    run(scenario())


def test_first_connector_is_paired_and_remembered(tmp_path):
    """The whole feature: nobody types a 64-hex secret, and it is announced."""

    notices = []

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_pairing=notices.append)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector",
                                     token="generated-by-the-extension",
                                     client="boardwise-connector/0.2.0")
            assert reply["ok"] is True
            # The connector can see which pairing it is talking to.
            assert reply["data"]["paired"] is True
            assert reply["data"]["fingerprint"] == connector_fingerprint(
                "generated-by-the-extension"
            )
            await ws.close()

    run(scenario())

    assert load_connector_token(tmp_path) == "generated-by-the-extension"
    assert len(notices) == 1
    assert notices[0].fingerprint == connector_fingerprint("generated-by-the-extension")
    assert notices[0].client == "boardwise-connector/0.2.0"

    pairings = [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_PAIRING]
    assert len(pairings) == 1
    assert pairings[0]["ok"] is True
    assert pairings[0]["client"] == "boardwise-connector/0.2.0"
    assert pairings[0]["fingerprint"] == connector_fingerprint(
        "generated-by-the-extension"
    )
    assert "peer" in pairings[0]


def test_the_token_itself_never_reaches_the_audit_log(tmp_path):
    """A fingerprint is the only form of a secret that may be written down."""

    secret = "0123456789abcdef" * 4  # 64 hex, shaped like the real thing

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "connector", token=secret)
            await ws.close()

    run(scenario())

    logged = (tmp_path / "audit").glob("*.jsonl")
    text = "".join(path.read_text(encoding="utf-8") for path in logged)
    assert secret not in text
    assert secret[:8] not in text, "an 8-char slice of the token is still a leak"


def test_a_paired_connector_pairs_only_once(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first, _ = await _hello(port, "connector", token="stable-token")
            await first.close()
            second, reply = await _hello(port, "connector", token="stable-token")
            assert reply["ok"] is True
            await second.close()

    run(scenario())

    pairings = [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_PAIRING]
    assert len(pairings) == 1, "reconnecting must not re-announce a pairing"


@pytest.mark.parametrize("token", ["", None])
def test_an_empty_token_never_pairs(tmp_path, token):
    """Pairing is not an open door for a client with no random source.

    Whatever else a hostile local process can do, it has to present *some*
    secret it invented — so an empty string can never become the pairing
    record, and nothing is written for it.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", token=token)
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            await ws.close()

    run(scenario())

    assert load_connector_token(tmp_path) is None
    assert not connector_token_path(tmp_path).exists()
    assert not [r for r in _audit_records(tmp_path) if r["action"] == AUDIT_PAIRING]
    # …and it is on the record as a refusal, not as silence.
    assert [r for r in _audit_records(tmp_path)
            if r["action"] == "hello" and r.get("ok") is False]


def test_pairing_a_connector_does_not_touch_the_cli_token(tmp_path):
    """Two independent secrets. A connector can never become a CLI caller."""

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            # Held open: while a connector is attached, an unknown token is
            # refused rather than re-pairing (004f item 2), and that is the
            # condition these two checks are about.
            conn, reply = await _hello(port, "connector", token="connector-secret")
            assert reply["ok"] is True

            # The connector's own token must not open the CLI door…
            cli_ws, cli_reply = await _hello(port, "cli", token="connector-secret")
            assert cli_reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            await cli_ws.close()

            # …nor must the CLI token open the connector door.
            intruder, intruder_reply = await _hello(port, "connector", token=TOKEN)
            assert intruder_reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            await intruder.close()

            # And the CLI still works with its own token.
            good, good_reply = await _hello(port, "cli")
            assert good_reply["ok"] is True
            await good.close()
            await conn.close()

    run(scenario())


def test_revoke_forgets_the_pairing_and_the_next_connector_re_pairs(tmp_path):
    """`revoke` is a reset, not a blocklist — and that is the specified shape.

    It cannot exclude one particular token, because it has no way to tell "the
    connector I distrust" from "the connector I just reinstalled". What it buys
    is that the trust decision happens again, out loud, on a console the user is
    watching (see `PairingNotice`), instead of silently persisting forever.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            original, first = await _hello(port, "connector", token="the-old-one")
            assert first["ok"] is True
            await original.close()

            # Revoked from another process while the daemon keeps running.
            revoked = revoke_connector_token(tmp_path)
            assert revoked == connector_fingerprint("the-old-one")
            assert load_connector_token(tmp_path) is None

            # A different connector now pairs instead.
            intruder, intruder_reply = await _hello(port, "connector", token="a-new-one")
            assert intruder_reply["ok"] is True, "the door is open again after revoke"
            assert load_connector_token(tmp_path) == "a-new-one"

            # …and the forgotten token is a stranger from then on. The new
            # connector stays attached for this, because an unattached pairing
            # may legitimately be re-taken (004f item 2).
            stale, stale_reply = await _hello(port, "connector", token="the-old-one")
            assert stale_reply["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            await stale.close()
            await intruder.close()

    run(scenario())

    pairings = [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_PAIRING]
    assert len(pairings) == 2, "each pairing is announced, including the second"
    assert pairings[0]["fingerprint"] != pairings[1]["fingerprint"]


def test_revoke_without_a_pairing_is_a_no_op(tmp_path):
    assert revoke_connector_token(tmp_path) is None
    assert load_connector_token(tmp_path) is None


def test_fingerprint_is_short_stable_and_not_derivable_by_eye(tmp_path):
    token = "a" * 64
    fingerprint = connector_fingerprint(token)
    assert fingerprint is not None
    assert len(fingerprint) == 8
    assert all(character in "0123456789abcdef" for character in fingerprint)
    assert fingerprint == connector_fingerprint(token), "must be stable"
    assert fingerprint != connector_fingerprint("b" * 64)
    assert connector_fingerprint(None) is None
    assert connector_fingerprint("") is None


# --------------------------------------------------------------------------
# the hub: many windows, routed by project (023)
# --------------------------------------------------------------------------

#: Two editor windows, as the daemon sees them: two sockets, two instance ids,
#: one shared token (both windows run the same extension install, so the
#: extension storage — and the pairing record — is the same one).
WINDOW_A = "inst-101500123-aaaaaaaa"
WINDOW_B = "inst-101533456-bbbbbbbb"


class FakeSocket:
    """A connector socket whose liveness is whatever the test says it is.

    The daemon reads `state` to decide whether a window is *online*, so a double
    that answers it is the only way to test the reload window at all: in the wild
    the peer is gone while the handler has not yet run its `finally`, and no
    amount of sleeping makes a real socket reproduce that ordering reliably.
    """

    def __init__(self, state: State = State.CLOSED) -> None:
        self.state = state
        self.remote_address = ("127.0.0.1", 1)
        self.sent: list = []

    async def send(self, raw) -> None:
        self.sent.append(raw)

    async def close(self) -> None:
        self.state = State.CLOSED


def _window(
    instance_id: str = WINDOW_A,
    version: str = "0.4.4",
    *,
    state: State = State.OPEN,
    project_name: str = "",
) -> WindowConnection:
    """A hub entry riding a socket whose liveness the test controls.

    ``state=State.OPEN`` by default because a hub entry that is not online is
    invisible to routing — which is the fact the reload tests are *about*, so
    they ask for it explicitly.
    """
    return WindowConnection(
        websocket=FakeSocket(state),
        key=instance_id,
        instance_id=instance_id,
        client=f"boardwise-connector/{version}",
        connector_version=version,
        peer="127.0.0.1:1",
        connected_at=time.time(),
        project_name=project_name,
    )


async def _ping(port: int) -> dict:
    """Ask a running daemon for its status, the way the CLI does."""
    cli_ws, _ = await _hello(port, "cli")
    try:
        await cli_ws.send(request_frame("ping", {}, id="p"))
        return decode_frame(await cli_ws.recv())["data"]
    finally:
        await cli_ws.close()


def test_every_window_that_authenticates_is_registered(tmp_path):
    """The accident 018 refused, and what 023 does instead.

    Both windows present the **same** paired token, because they share one
    extension install — so the pairing check cannot tell them apart, and 018's
    answer was to refuse the second with `CONNECTOR_ALREADY_ACTIVE`. A hardware
    engineer opens three or four windows as a matter of course, so refusing was
    the wrong fix: both register, both are listed with their own project, and
    *routing* decides which one a call reaches.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(
                port, "connector", token="shared", instanceId=WINDOW_A,
                connectorVersion="0.4.10", projectName="/test", projectUuid="uuid-test",
            )
            assert first["ok"] is True
            assert first["data"]["windowsOnline"] == 1
            assert first["data"]["windowKey"] == WINDOW_A

            second_ws, second = await _hello(
                port, "connector", token="shared", instanceId=WINDOW_B,
                connectorVersion="0.4.10", projectName="test2", projectUuid="uuid-test2",
            )
            assert second["ok"] is True, "a second window is welcome, not refused"
            assert second["data"]["windowsOnline"] == 2
            assert second["data"]["windowKey"] == WINDOW_B
            assert [w.key for w in daemon.live_windows()] == [WINDOW_A, WINDOW_B]

            data = await _ping(port)
            assert data["connector"] is True
            assert [w["windowKey"] for w in data["windows"]] == [WINDOW_A, WINDOW_B]
            assert [w["projectName"] for w in data["windows"]] == ["/test", "test2"]
            assert [w["connectorVersion"] for w in data["windows"]] == ["0.4.10", "0.4.10"]

            await first_ws.close()
            await second_ws.close()

    run(scenario())

    records = _audit_records(tmp_path)
    greetings = [r for r in records if r["action"] == "hello" and r.get("ok") is True]
    assert [r["instanceId"] for r in greetings] == [WINDOW_A, WINDOW_B]
    assert [r["windowKey"] for r in greetings] == [WINDOW_A, WINDOW_B]
    # How many windows were online *when each arrived* — so "was this the first
    # or the fourth?" needs no reconstruction from the surrounding records.
    assert [r["windowsOnline"] for r in greetings] == [1, 2]
    # …and the refusal record is gone from the log entirely: nothing is refused.
    assert not [r for r in records if r["action"] == AUDIT_CONNECTOR_REJECTED]


def test_the_refusal_machinery_is_gone_and_its_code_is_retired():
    """018's single-slot guard, removed — with the vocabulary it used kept.

    The code itself stays in `ErrorCodes`, because connector builds in the field
    read it and a name that vanished would leave their handling of it pointing at
    nothing. What must not come back is the *machinery*: pinned by name here so
    that re-introducing a refusal path is a deliberate act rather than a merge
    accident, and checked by identity so a copy that happens to spell the same
    today cannot stand in for it.
    """
    from boardwise.bridge import daemon as daemon_module

    assert ErrorCodes.CONNECTOR_ALREADY_ACTIVE == "CONNECTOR_ALREADY_ACTIVE"
    for gone in ("refuse_if_held", "RejectionNotice", "ActiveConnector", "active_instance"):
        assert not hasattr(daemon_module, gone), f"{gone} should have gone with 023"
    assert not hasattr(BridgeDaemon, "recent_rejections")
    assert not hasattr(BridgeDaemon, "on_rejection")
    # The retired audit record name survives as documentation of old logs, but no
    # longer as part of the module's API — nothing may write it again.
    assert AUDIT_CONNECTOR_REJECTED not in daemon_module.__all__
    assert daemon_module.AUDIT_CONNECTOR_REJECTED == "connector_rejected"


def test_every_error_code_is_spelled_as_its_own_name():
    """``ErrorCodes.X`` and the string on the wire are the same word.

    A code is read by two programs and by hand while reading a log. A value that
    drifts from its attribute name — or a raise site that invents a literal —
    stays invisible until someone greps the audit log for the code the source
    claims, so the spelling is pinned here rather than noticed later.
    """
    codes = {name: value for name, value in vars(ErrorCodes).items() if name.isupper()}
    assert codes, "ErrorCodes has no codes — the test would pass vacuously"
    assert {name: value for name, value in codes.items() if name != value} == {}


def test_a_project_hint_routes_to_the_window_that_has_it(tmp_path):
    """The point of the task: `--project test2` reaches window B, not A.

    An audit record saying "routed to inst-B" would not prove the routing. The
    request has to arrive on that window's socket and **not** on the other one —
    two different claims, and only the second one means a write cannot land in
    the wrong project.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            fake_a = FakeConnector(
                a_ws,
                responses={"doc.list": {"window": "A"}},
                contexts={"doc.list": {"projectName": "/test", "projectUuid": "uuid-test",
                                       "pageUuid": "page-a", "pageType": "sch"}},
            )
            fake_b = FakeConnector(b_ws, responses={"doc.list": {"window": "B"}})
            tasks = [asyncio.create_task(fake_a.serve()),
                     asyncio.create_task(fake_b.serve())]

            cli_ws, _ = await _hello(port, "cli")
            # …by project name,
            await cli_ws.send(request_frame("doc.list", {}, id="n", target_project="test2"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["data"] == {"window": "B"}
            # …and by project uuid.
            await cli_ws.send(request_frame("doc.list", {}, id="u", target_project="uuid-test"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["data"] == {"window": "A"}, "the hint decides, not the order"
            # The caller is also told *which* window answered, in that window's own
            # words — the fact an R1-style identity check needs, on the response
            # itself rather than inferred from a separate call.
            assert reply["context"] == {
                "projectName": "/test", "projectUuid": "uuid-test",
                "pageUuid": "page-a", "pageType": "sch",
            }

            assert [frame["action"] for frame in fake_a.received] == ["doc.list"]
            assert [frame["action"] for frame in fake_b.received] == ["doc.list"]
            # A hint is a routing instruction to the daemon, never something the
            # connector sees in the action's own params.
            assert "targetProject" not in fake_b.received[0]

            for task in tasks:
                task.cancel()
            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())

    routed = [record for record in _audit_records(tmp_path)
              if record["action"] == "doc.list"]
    assert [record["windowKey"] for record in routed] == [WINDOW_B, WINDOW_A]
    # Which project the call landed in, on the call's own line: the window may be
    # closed by the time anyone asks.
    assert [record["projectName"] for record in routed] == ["test2", "/test"]


def test_a_hint_that_matches_no_window_lists_the_online_ones(tmp_path):
    """``PROJECT_NOT_CONNECTED`` (023): the next move is to name a window.

    The message carries the list, not only the failure: the project the caller
    asked for may simply not be open, and the windows that *are* online are the
    only useful thing to say next.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="x", target_project="反激辅助电源"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.PROJECT_NOT_CONNECTED
            assert reply["error"]["message"] == (
                "no connected window has project '反激辅助电源' open; online windows: "
                f"/test ({WINDOW_A}), test2 ({WINDOW_B}) — a window can also be named "
                "by its instance id (boardwise bridge call --instance INSTANCE_ID)"
            )
            assert [c["windowKey"] for c in reply["error"]["detail"]["candidates"]] == [
                WINDOW_A, WINDOW_B,
            ]
            # No window was chosen, so no window is named on the frame.
            assert "context" not in reply

            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_a_hint_that_matches_two_windows_is_ambiguous(tmp_path):
    """``PROJECT_AMBIGUOUS``: the same project open twice, and no guessing.

    This is the double-activation case (023 §今晚不做: no dedup yet). Picking one
    — the newest, the first — is what makes a wrong-window write invisible, so
    the daemon refuses and names both candidates.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="test2", projectUuid="uuid-test2")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            fake_a = FakeConnector(a_ws, responses={"doc.list": {"window": "A"}})
            task = asyncio.create_task(fake_a.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="x", target_project="test2"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.PROJECT_AMBIGUOUS
            assert reply["error"]["message"] == (
                "project 'test2' matches 2 connected windows "
                f"(test2 ({WINDOW_A}), test2 ({WINDOW_B})); nothing was forwarded — "
                "close the duplicate window or name one of them"
            )
            assert len(reply["error"]["detail"]["candidates"]) == 2
            assert fake_a.received == [], "ambiguous means nothing was sent anywhere"

            task.cancel()
            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_an_instance_hint_reaches_that_window_without_any_project(tmp_path):
    """`--instance inst-B` reaches B — the gap `--project` cannot close.

    Measured 2026-09-22: the editor restarts and all three windows greet the
    daemon before the editor API is ready, so every `context` read comes back
    null and every window's project is unknown. A `--project` hint then has
    *nothing to match against* — including the window the caller is looking at —
    while the instance id was in the `hello` params from the first frame and is
    still there. This is the case the flag exists for, so the test is written
    without any project: two windows, both nameless, routed by id.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A)
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B)
            fake_a = FakeConnector(a_ws, responses={"doc.list": {"window": "A"}})
            fake_b = FakeConnector(b_ws, responses={"doc.list": {"window": "B"}})
            tasks = [asyncio.create_task(fake_a.serve()),
                     asyncio.create_task(fake_b.serve())]

            cli_ws, _ = await _hello(port, "cli")
            # The project hint cannot work here: nothing names a project.
            await cli_ws.send(request_frame("doc.list", {}, id="p", target_project="/test"))
            assert decode_frame(await cli_ws.recv())["error"]["code"] == (
                ErrorCodes.PROJECT_NOT_CONNECTED
            )
            # The instance hint does, and reaches exactly one window.
            await cli_ws.send(
                request_frame("doc.list", {}, id="i", target_instance=WINDOW_B))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True and reply["data"] == {"window": "B"}
            # Every window in the hub names no project, which is what the answer
            # says — and the caller still learns which window answered.
            assert "context" not in reply, "a window that read nothing sends nothing"

            assert [frame["action"] for frame in fake_a.received] == []
            assert [frame["action"] for frame in fake_b.received] == ["doc.list"]
            # An instance hint is addressed to the daemon, never forwarded into
            # the action's own params — same rule as the project hint.
            assert "targetInstance" not in fake_b.received[0]

            for task in tasks:
                task.cancel()
            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())

    routed = [record for record in _audit_records(tmp_path)
              if record["action"] == "doc.list" and record.get("ok") is True]
    assert [record["windowKey"] for record in routed] == [WINDOW_B]
    # The refused project hint is in the log too, and names no window: nothing
    # was chosen, so nothing is claimed to have answered.
    refused = [record for record in _audit_records(tmp_path)
               if record["action"] == "doc.list" and record.get("ok") is False]
    assert [record["error"] for record in refused] == [ErrorCodes.PROJECT_NOT_CONNECTED]
    assert "windowKey" not in refused[0]


def test_an_instance_hint_that_matches_no_window_lists_the_online_ones(tmp_path):
    """``WINDOW_NOT_CONNECTED``: the same shape as the project refusal.

    An instance id is a name someone typed or copied, so a miss is the ordinary
    outcome — a closed window, or an id from an earlier session. The message
    carries the windows that *are* online, because naming one of them is the
    caller's next move.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(
                request_frame("doc.list", {}, id="x", target_instance="inst-gone"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is False
            assert reply["error"]["code"] == ErrorCodes.WINDOW_NOT_CONNECTED
            assert reply["error"]["message"] == (
                "no connected window is instance 'inst-gone'; online windows: "
                f"/test ({WINDOW_A}), test2 ({WINDOW_B})"
            )
            assert [c["windowKey"] for c in reply["error"]["detail"]["candidates"]] == [
                WINDOW_A, WINDOW_B,
            ]
            assert "context" not in reply, "no window was chosen, so none is named"

            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_an_instance_hint_wins_over_a_project_hint(tmp_path):
    """Both hints on one frame: the instance decides.

    The two are not equally precise — an instance id names one connection, a
    project name can be claimed by several — so when a caller sends both, the
    narrower one routes. Here the project hint points at window B and the
    instance at window A: A answers, and B receives nothing at all.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            fake_a = FakeConnector(a_ws, responses={"doc.list": {"window": "A"}})
            fake_b = FakeConnector(b_ws, responses={"doc.list": {"window": "B"}})
            tasks = [asyncio.create_task(fake_a.serve()),
                     asyncio.create_task(fake_b.serve())]

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame(
                "doc.list", {}, id="both",
                target_project="test2", target_instance=WINDOW_A))
            reply = decode_frame(await cli_ws.recv())
            assert reply["data"] == {"window": "A"}
            assert [frame["action"] for frame in fake_b.received] == []
            # A hint that could not be honoured is not an error: the instance was
            # a name the daemon could resolve, so the project never had to be.

            for task in tasks:
                task.cancel()
            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_an_instance_hint_names_one_of_two_connections_sharing_an_id(tmp_path):
    """The `~2` suffix is addressable, so a double activation is pickable.

    Two live sockets claim one instance id (the 3.2.175 double activation): both
    stay registered, the second under the suffixed key, and a project hint stays
    ambiguous — deliberately, because the daemon will not choose. The instance
    hint is the caller's own answer to that: the unsuffixed key reaches the first
    connection, `~2` the second, both by exact match and neither by guessing.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="t",
                                           instanceId=WINDOW_A, projectName="test2")
            second_ws, second = await _hello(port, "connector", token="t",
                                             instanceId=WINDOW_A, projectName="test2")
            twin_key = f"{WINDOW_A}{WINDOW_KEY_SEPARATOR}2"
            fake_first = FakeConnector(first_ws, responses={"doc.list": {"window": "first"}})
            fake_second = FakeConnector(second_ws, responses={"doc.list": {"window": "twin"}})
            tasks = [asyncio.create_task(fake_first.serve()),
                     asyncio.create_task(fake_second.serve())]

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame(
                "doc.list", {}, id="twin", target_instance=twin_key))
            assert decode_frame(await cli_ws.recv())["data"] == {"window": "twin"}
            await cli_ws.send(request_frame(
                "doc.list", {}, id="first", target_instance=WINDOW_A))
            assert decode_frame(await cli_ws.recv())["data"] == {"window": "first"}

            assert [frame["action"] for frame in fake_first.received] == ["doc.list"]
            assert [frame["action"] for frame in fake_second.received] == ["doc.list"]

            for task in tasks:
                task.cancel()
            await cli_ws.close()
            await second_ws.close()
            await first_ws.close()

    run(scenario())


def test_several_windows_and_no_hint_are_refused_not_guessed(tmp_path):
    """``WINDOW_UNSPECIFIED``: the daemon will not pick for the caller.

    Before the hub there was nothing to pick. Now there is, and the whole reason
    023 exists is that "the most recent window" is not the same as "the window
    the caller meant" — an error the caller can read is cheaper than a write that
    landed somewhere plausible.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2", projectUuid="uuid-test2")
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="x"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.WINDOW_UNSPECIFIED
            assert reply["error"]["message"] == (
                "2 editor windows are connected and the request named no project; "
                "re-send with a project hint (boardwise bridge call --project "
                "NAME_OR_UUID) or an instance id (boardwise bridge call --instance "
                f"INSTANCE_ID) — online windows: /test ({WINDOW_A}), "
                f"test2 ({WINDOW_B})"
            )
            assert [c["windowKey"] for c in reply["error"]["detail"]["candidates"]] == [
                WINDOW_A, WINDOW_B,
            ]

            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_a_single_window_needs_no_hint(tmp_path):
    """The pre-023 contract, unchanged: one window answers a plain call.

    Every existing caller — `boardwise draw`, `bridge screenshot`, every script —
    sends no hint at all, and must keep working exactly as before as long as one
    window is connected.
    """
    canned = {"components": [{"designator": "U1"}]}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                      projectName="/test")
            fake = FakeConnector(conn_ws, responses={"pcb.readback": canned})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("pcb.readback", {}, id="r"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True
            assert reply["data"] == canned
            # An empty params object is omitted by `request_frame` (as it always
            # was), and the hint never rides in params at all: the forwarded frame
            # is the pre-023 frame in every byte.
            assert "params" not in fake.received[0]
            assert "targetProject" not in fake.received[0], (
                "a hint is addressed to the daemon, never forwarded into the action"
            )
            assert daemon.live_windows()[0].routed == 1

            task.cancel()
            await cli_ws.close()
            await conn_ws.close()

    run(scenario())


@pytest.mark.parametrize("state", [State.CLOSED, State.CLOSING])
def test_a_dead_socket_is_displaced_without_a_fuss(tmp_path, state):
    """The reload path, which has to stay smooth.

    The old socket is dead while its hub entry is still there — exactly the state
    a reload leaves behind, because the handler's `finally` has not run yet. The
    newcomer takes the same key back; keeping the dead row would mean routing into
    a socket that is gone.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        daemon.windows[WINDOW_A] = _window(WINDOW_A, state=state)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", token="t", instanceId=WINDOW_A)
            assert reply["ok"] is True
            assert reply["data"]["windowsOnline"] == 1, "the dead one is not counted"
            # The dead holder is gone from the hub, not just stopped.
            live = daemon.live_windows()
            assert [w.key for w in live] == [WINDOW_A]
            assert not isinstance(live[0].websocket, FakeSocket)
            await ws.close()

    run(scenario())

    greeting = next(record for record in _audit_records(tmp_path)
                    if record["action"] == "hello" and record.get("ok") is True)
    assert greeting["windowKey"] == WINDOW_A
    assert greeting["tookOverFrom"] == WINDOW_A, "the log names what it replaced"
    assert greeting["duplicateInstanceId"] is None


def test_a_connector_without_an_instance_id_is_named_by_its_connection(tmp_path):
    """Old builds keep working, and the daemon does not pretend otherwise.

    A connector that predates `instanceId` must still connect — refusing every
    existing install to add a diagnostic field would be a strange trade — so the
    daemon invents an id for the *connection* and records that it did. In the hub
    (023) that invented id is also the routing key, which is why it is spelled
    ``conn-…``: a key that looked like a claimed instance id would hide the fact
    that this window cannot be recognised again after a reconnect.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="t")
            assert first["ok"] is True
            assert first["data"]["windowKey"].startswith("conn-")
            window = daemon.live_windows()[0]
            assert window.instance_id_source == "connection"
            assert window.key == window.instance_id
            await first_ws.close()
            await _until(lambda: not daemon.has_connector())

            # Per connection, not per daemon: the second socket gets its own.
            second_ws, second = await _hello(port, "connector", token="t")
            assert second["ok"] is True
            assert daemon.live_windows()[0].key != window.key
            await second_ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert len(greetings) == 2
    assert all(record["instanceIdSource"] == "connection" for record in greetings)
    assert greetings[0]["instanceId"] != greetings[1]["instanceId"]


def test_hello_ack_announces_the_minimum_connector_version(tmp_path):
    """The one field the extension needs to say "please update" (018 §A/§B)."""

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", instanceId=WINDOW_A)
            assert reply["data"]["minConnectorVersion"] == MIN_CONNECTOR_VERSION
            await ws.close()

    run(scenario())

    # Pinned as a literal: the constant is what the connector compares against,
    # so a silent rename or a bump nobody told the connector about would show up
    # here rather than as a toast that never appears.
    assert MIN_CONNECTOR_VERSION == "0.4.10"


def test_ping_reports_every_window_and_what_each_has_done(tmp_path):
    """What `bridge status` reads to answer "who is connected, and to what?"."""

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(
                port, "connector", token="t", instanceId=WINDOW_A,
                connectorVersion="0.4.10", projectName="/test", projectUuid="uuid-test",
            )
            fake = FakeConnector(conn_ws, responses={"doc.list": {"documents": []}})
            task = asyncio.create_task(fake.serve())

            first = await _ping(port)
            assert first["connector"] is True
            assert [w["windowKey"] for w in first["windows"]] == [WINDOW_A]
            window = first["windows"][0]
            assert window["connectorVersion"] == "0.4.10"
            assert window["instanceIdSource"] == "hello"
            assert window["projectName"] == "/test"
            assert window["pageUuid"] is None and window["pageType"] is None
            assert window["routed"] == 0
            assert window["connectedAt"] and window["lastSeen"]

            # A second window grows the table rather than replacing a row, and
            # the call count is per window — the fact that makes "which one has
            # the AI been talking to?" answerable.
            second_ws, _ = await _hello(
                port, "connector", token="t", instanceId=WINDOW_B, projectName="test2",
            )
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="c", target_project="/test"))
            assert decode_frame(await cli_ws.recv())["ok"] is True

            data = await _ping(port)
            assert [w["windowKey"] for w in data["windows"]] == [WINDOW_A, WINDOW_B]
            assert [w["routed"] for w in data["windows"]] == [1, 0]

            task.cancel()
            await cli_ws.close()
            await second_ws.close()
            await conn_ws.close()

    run(scenario())


def test_ping_drops_a_window_as_soon_as_its_socket_closes(tmp_path):
    """Disconnect means gone: routing may not point at a dead window."""
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2")
            assert [w.key for w in daemon.live_windows()] == [WINDOW_A, WINDOW_B]

            await b_ws.close()
            await _until(lambda: [w.key for w in daemon.live_windows()] == [WINDOW_A])

            data = await _ping(port)
            assert [w["windowKey"] for w in data["windows"]] == [WINDOW_A]
            # …and a hint for the closed window's project is now a plain miss,
            # whose message lists the one window that is left.
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="x", target_project="test2"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.PROJECT_NOT_CONNECTED
            assert f"online windows: /test ({WINDOW_A})" in reply["error"]["message"]
            await cli_ws.close()
            await a_ws.close()

    run(scenario())

    closing = [record for record in _audit_records(tmp_path)
               if record["action"] == "disconnect" and record.get("windowKey") == WINDOW_B]
    assert len(closing) == 1
    # The project and page of the window that left, recorded as last known: after
    # this, the log is the only place its identity survives.
    assert closing[0]["projectName"] == "test2"
    assert closing[0]["routed"] == 0


def test_status_lines_are_silent_when_there_is_nothing_to_say():
    """A daemon with no connector prints exactly what it printed before 023."""
    assert status_lines({}) == []
    assert status_lines({"connector": False, "windows": []}) == []


def test_status_lines_render_the_window_table():
    """One block per window: key, build, project, page, times, calls answered.

    This is the line set that answers "which projects do I have open, and which
    one is boardwise talking to?" — a question that had no answer at all before
    021, and only had one for a single privileged window until 023.
    """
    stamp = 1790000000.0
    seen_at = 1790000123.0
    lines = status_lines({"windows": [
        {
            "windowKey": WINDOW_A, "instanceId": WINDOW_A, "instanceIdSource": "hello",
            "client": "boardwise-connector/3.2.186", "connectorVersion": "0.4.10",
            "peer": "127.0.0.1:51234", "connectedAt": stamp, "lastSeen": seen_at,
            "routed": 3, "projectName": "/test", "projectUuid": "uuid-test",
            "pageUuid": "page-a", "pageType": "sch",
        },
        {
            "windowKey": WINDOW_B, "instanceId": WINDOW_B, "instanceIdSource": "hello",
            "client": "boardwise-connector/3.2.186", "connectorVersion": None,
            "peer": "127.0.0.1:51235", "connectedAt": stamp, "lastSeen": stamp,
            "routed": 0, "projectName": "test2", "projectUuid": "uuid-test2",
            "pageUuid": None, "pageType": None,
        },
    ]})

    assert lines[0] == "  windows: 2 connected"
    assert (
        f"  window: {WINDOW_A} (connector 0.4.10)  [project /test (uuid-test)]" in lines
    )
    assert (
        f"    peer: 127.0.0.1:51234  connected: {_clock(stamp)}"
        f"  last seen: {_clock(seen_at)}  routed: 3" in lines
    )
    assert "    page: sch page-a" in lines
    # A window that has answered nothing says nothing about calls, and a build
    # that did not name itself is rendered as unknown rather than as blank.
    assert (
        f"  window: {WINDOW_B} (connector {UNKNOWN_CONNECTOR_VERSION})"
        "  [project test2 (uuid-test2)]" in lines
    )
    assert all("routed" not in line for line in lines if WINDOW_B in line)
    assert all("page:" not in line for line in lines if WINDOW_B in line)
    assert all(line.startswith("  ") for line in lines)
    assert any("projects seen:" in line for line in lines)


def test_status_lines_mark_an_id_the_daemon_had_to_invent():
    """An invented id must not read like a claimed one."""
    lines = status_lines({"windows": [{
        "windowKey": "conn-0123456789abcdef", "instanceId": "conn-0123456789abcdef",
        "instanceIdSource": "connection", "connectorVersion": None,
    }]})
    assert any("no instanceId sent" in line for line in lines)


def test_status_lines_map_every_online_window_to_its_project():
    """``projects seen`` upgraded from roles to the windows themselves (023).

    It used to group "the active window plus every refused one", because a
    refused socket was the only evidence the other projects existed. Every window
    is a hub row now, so the line names the windows that are actually reachable —
    and the keys it prints are exactly what a caller writes into ``--project``.
    """
    lines = status_lines({"windows": [
        {"windowKey": WINDOW_A, "instanceId": WINDOW_A, "connectorVersion": "0.4.11",
         "projectName": "/test", "projectUuid": "uuid-test"},
        {"windowKey": WINDOW_B, "instanceId": WINDOW_B, "connectorVersion": "0.4.11",
         "projectName": "test2", "projectUuid": "uuid-test2"},
        # An old build, which has no project to report.
        {"windowKey": "inst-old", "instanceId": "inst-old"},
    ]})

    seen = [line for line in lines if "projects seen:" in line]
    assert seen == [
        f"  projects seen: /test ({WINDOW_A}), test2 ({WINDOW_B}), "
        "1 window(s) naming no project"
    ], seen


def test_status_lines_name_both_windows_when_two_share_a_project():
    """Two windows on one project are two entries, not one folded row.

    That is the case where "which window did you mean?" stops being rhetorical,
    and the line a caller reads before typing ``--project`` has to show that the
    hint it is about to use is ambiguous.
    """
    lines = status_lines({"windows": [
        {"windowKey": WINDOW_A, "instanceId": WINDOW_A, "projectName": "test2"},
        {"windowKey": f"{WINDOW_A}{WINDOW_KEY_SEPARATOR}2",
         "instanceId": WINDOW_A, "projectName": "test2"},
    ]})
    assert [line for line in lines if "projects seen:" in line] == [
        f"  projects seen: test2 ({WINDOW_A}, {WINDOW_A}{WINDOW_KEY_SEPARATOR}2)"
    ]


def test_window_listing_names_each_window_by_its_key():
    """The one rendering every routing error ends with (023).

    A window that named no project is listed as such rather than left out: it is
    online, and a caller told "that project is not open" deserves to see the
    windows it *could* be talking to. An empty list renders as ``(none)`` so no
    message can end in a dangling colon.
    """
    assert window_listing([]) == "(none)"
    assert window_listing([
        _window(WINDOW_A, project_name="/test"),
        _window(WINDOW_B),
    ]) == f"/test ({WINDOW_A}), (no project) ({WINDOW_B})"


def test_status_lines_say_nothing_about_projects_nobody_named():
    """Nothing is known, so nothing is said — the 021 rule, kept in 023.

    Every project field is optional, so a daemon talking to old builds knows no
    projects at all. Its output must not grow a placeholder or an empty suffix,
    and the summary line must stay silent: "1 window naming no project" beside no
    project at all is not a fact worth a line.
    """
    stamp = 1790000000.0
    lines = status_lines({"windows": [{
        "windowKey": WINDOW_A, "instanceId": WINDOW_A, "instanceIdSource": "hello",
        "client": "boardwise-connector/3.2.186", "connectorVersion": "0.4.10",
        "peer": "127.0.0.1:51234", "connectedAt": stamp, "lastSeen": stamp,
        "routed": 0,
    }]})

    assert lines == [
        "  windows: 1 connected",
        f"  window: {WINDOW_A} (connector 0.4.10)",
        f"    peer: 127.0.0.1:51234  connected: {_clock(stamp)}"
        f"  last seen: {_clock(stamp)}",
    ]
    assert not [line for line in lines if "projects seen:" in line]


def test_a_window_that_names_no_project_still_connects_and_routes_around(tmp_path):
    """Backwards compatibility, both directions (021 §2.3 / 023).

    An old connector sends neither project field, and must be welcomed: it keeps
    a hub row, it can answer a plain single-window call, and its blank project is
    recorded as blank. It cannot be reached by a project hint — there is nothing
    to match — so a hint that only it could have answered comes back as a plain
    miss, listing it as the window that named no project. It **can** be reached by
    its key (`--instance`), which is the point of that hint: the daemon invented
    the key for it at registration, so even a window that named nothing at all
    has a name a caller can use.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            # An old build: no projectName, no projectUuid, no instanceId either.
            old_ws, old = await _hello(port, "connector", token="t")
            assert old["ok"] is True
            window = daemon.live_windows()[0]
            assert window.project_name == ""
            assert window.as_status()["projectName"] is None
            assert window.as_status()["projectUuid"] is None
            fake_old = FakeConnector(old_ws, responses={"doc.list": {"window": "old"}})
            old_task = asyncio.create_task(fake_old.serve())

            named_ws, named = await _hello(port, "connector", token="t",
                                           instanceId=WINDOW_B, projectName="test2")
            assert named["ok"] is True
            # A name without a uuid is kept as it came — half an identity is still
            # more than none, and the daemon does not invent the other half.
            assert daemon.window_for_instance(WINDOW_B).project_uuid == ""

            cli_ws, _ = await _hello(port, "cli")
            # No hint, two windows: refused, and the unnamed one is *listed*.
            await cli_ws.send(request_frame("doc.list", {}, id="a"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.WINDOW_UNSPECIFIED
            assert reply["error"]["message"].endswith(
                f"online windows: (no project) ({window.key}), test2 ({WINDOW_B})"
            )
            # A hint for a project nobody has: a miss that still shows both — a
            # project hint cannot reach the window that named none, and the
            # message now says what can.
            await cli_ws.send(request_frame("doc.list", {}, id="b", target_project="test9"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.PROJECT_NOT_CONNECTED
            assert reply["error"]["message"] == (
                "no connected window has project 'test9' open; online windows: "
                f"(no project) ({window.key}), test2 ({WINDOW_B}) — a window can "
                "also be named by its instance id (boardwise bridge call "
                "--instance INSTANCE_ID)"
            )
            # …and the key it is listed under reaches it, which is what makes
            # "no project" a routing *limitation* rather than a wall.
            await cli_ws.send(request_frame(
                "doc.list", {}, id="c", target_instance=window.key))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True and reply["data"] == {"window": "old"}

            old_task.cancel()
            await cli_ws.close()
            await old_ws.close()
            await named_ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert [record["projectName"] for record in greetings] == [None, "test2"]
    assert greetings[0]["windowKey"].startswith("conn-")


def test_each_window_reports_its_own_project(tmp_path):
    """The wire half: what `status` renders has to come off ``ping`` itself.

    Two windows, each naming a different project, both still connected — the
    manager of a three-window session reads exactly this to decide which one to
    address, so it is asserted end to end rather than only against a dict the
    test built.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            holder_ws, holder_reply = await _hello(
                port, "connector", token="t", instanceId=WINDOW_A,
                projectName="/test", projectUuid="uuid-test",
            )
            assert holder_reply["ok"] is True
            assert daemon.window_for_instance(WINDOW_A).project_name == "/test"
            assert daemon.window_for_instance(WINDOW_A).project_uuid == "uuid-test"

            extra_ws, extra_reply = await _hello(
                port, "connector", token="t", instanceId=WINDOW_B,
                projectName="test2", projectUuid="uuid-test2",
            )
            assert extra_reply["ok"] is True

            lines = status_lines(await _ping(port))
            assert any("[project /test (uuid-test)]" in line for line in lines), lines
            assert any("[project test2 (uuid-test2)]" in line for line in lines), lines
            assert any(
                line == f"  projects seen: /test ({WINDOW_A}), test2 ({WINDOW_B})"
                for line in lines
            ), lines

            await holder_ws.close()
            await extra_ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert [(record["projectName"], record["projectUuid"]) for record in greetings] == [
        ("/test", "uuid-test"), ("test2", "uuid-test2"),
    ]


def test_a_response_context_moves_where_that_window_routes(tmp_path):
    """The context is *live*: switching project in the editor moves the routing.

    A window that answers a call while showing another project is in that project
    from then on. Both directions are asserted, because only the pair is
    meaningful: the new project must find it, and the old one must **stop**
    matching — a stale project is a write aimed by a memory (023 §协议字段约定).
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test", projectUuid="uuid-test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="other", projectUuid="uuid-other")
            # A answers one call while showing test2 / a PCB page.
            fake_a = FakeConnector(
                a_ws,
                responses={"doc.list": {"window": "A"}},
                contexts={"doc.list": {"projectName": "test2", "projectUuid": "uuid-test2",
                                       "pageUuid": "page-pcb", "pageType": "pcb"}},
            )
            task = asyncio.create_task(fake_a.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="1", target_project="/test"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["data"] == {"window": "A"}

            window = daemon.window_for_instance(WINDOW_A)
            assert (window.project_name, window.project_uuid) == ("test2", "uuid-test2")
            assert (window.page_uuid, window.page_type) == ("page-pcb", "pcb")

            # The new project now finds it, by name and by uuid…
            for hint in ("test2", "uuid-test2"):
                await cli_ws.send(request_frame("doc.list", {}, id=hint, target_project=hint))
                assert decode_frame(await cli_ws.recv())["data"] == {"window": "A"}
            # …and the project it left no longer does.
            await cli_ws.send(request_frame("doc.list", {}, id="old", target_project="/test"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.PROJECT_NOT_CONNECTED

            lines = status_lines(await _ping(port))
            assert any("[project test2 (uuid-test2)]" in line for line in lines), lines
            assert any("    page: pcb page-pcb" in line for line in lines), lines

            task.cancel()
            await cli_ws.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_a_context_that_could_not_be_read_never_erases_what_is_known():
    """A null is not news (023 §协议字段约定).

    A window that has just lost its active document omits (or nulls) the page; it
    has *not* lost its project. Every unreadable key — missing, ``None``, empty,
    a number — leaves the known value alone, unknown keys are ignored rather than
    stored, and a context with nothing usable in it changes nothing at all.
    """
    connection = Connection(
        project_name="/test", project_uuid="uuid-test", page_uuid="page-sch",
    )

    # The wire spelling is fixed here because two programs write it: the connector
    # puts these keys in a response and the daemon reads them back.
    assert CONTEXT_KEYS == ("projectName", "projectUuid", "pageUuid", "pageType")

    changed = merge_context(connection, {
        "projectName": None, "projectUuid": "", "pageUuid": "page-pcb",
        "pageType": "pcb", "instanceId": "not-ours", "nonsense": 7,
    })
    assert changed == ("page_uuid", "page_type")
    assert connection.project_name == "/test", "a null must not erase a project"
    assert connection.project_uuid == "uuid-test"
    assert not hasattr(connection, "nonsense")
    assert connection.instance_id == "", "an unknown key is not written through"

    assert merge_context(connection, {"pageUuid": 1234}) == ()
    assert merge_context(connection, None) == ()
    assert merge_context(connection, "not an object") == ()
    # Idempotent: the same context twice reports no second change.
    assert merge_context(connection, {"pageType": "pcb"}) == ()
    assert context_of(connection) == {
        "projectName": "/test", "projectUuid": "uuid-test",
        "pageUuid": "page-pcb", "pageType": "pcb",
    }


def test_a_second_window_is_quiet_on_the_console_and_loud_in_status(tmp_path, capsys):
    """018's warning line, replaced by visibility that needs no reading.

    The console line existed because a refused window was invisible everywhere
    else. In the hub nothing is refused, so there is nothing alarming to print —
    and the old line must not come back, because a user told to "close the extra
    EasyEDA window" while three windows is the normal state has been given bad
    advice. What carries the fact instead is `bridge status`, which names both
    windows and both projects.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, _ = await _hello(port, "connector", token="t",
                                       instanceId=WINDOW_A, connectorVersion="0.4.10",
                                       projectName="/test")
            second_ws, second = await _hello(port, "connector", token="t",
                                             instanceId=WINDOW_B, connectorVersion="0.4.4",
                                             projectName="test2")
            assert second["ok"] is True
            lines = status_lines(await _ping(port))
            assert any(f"  window: {WINDOW_A} (connector 0.4.10)" in line for line in lines)
            assert any(f"  window: {WINDOW_B} (connector 0.4.4)" in line for line in lines)
            await second_ws.close()
            await first_ws.close()

    run(scenario())

    assert capsys.readouterr().out == "", (
        "nothing to warn about: several windows are the normal case now"
    )


def test_writes_to_one_window_serialise_while_other_windows_run_in_parallel(tmp_path):
    """023 §per-window 写互斥: one editor serialises, two editors do not.

    A write is a sequence the editor solves step by step, so two writes racing
    inside one window is how a half-drawn page happens. Two *windows* are two
    editors, though, and making them queue behind each other would turn the hub
    back into the single slot 023 removed. Measured by wall-clock overlap rather
    than by order: the fake connector occupies "the editor" for a fixed gap per
    write, and the intervals are compared.
    """
    gap = 0.25

    class SlowWriteConnector:
        """Holds the editor busy for `gap` seconds per write, and records when."""

        def __init__(self, ws):
            self.ws = ws
            self.spans: list[tuple[str, float, float]] = []

        async def serve(self):
            async for raw in self.ws:
                frame = decode_frame(raw)
                if frame_kind(frame) != "request":
                    continue
                started = time.perf_counter()
                await asyncio.sleep(gap)
                self.spans.append((frame["action"], started, time.perf_counter()))
                await self.ws.send(
                    response_frame(frame.get("id"), {"action": frame["action"]})
                )

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            b_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_B,
                                   projectName="test2")
            slow_a, slow_b = SlowWriteConnector(a_ws), SlowWriteConnector(b_ws)
            tasks = [asyncio.create_task(slow_a.serve()),
                     asyncio.create_task(slow_b.serve())]

            # Three separate CLI connections, because one connection is answered
            # one frame at a time — two *callers* are what makes writes race.
            clis = [await _hello(port, "cli") for _ in range(3)]
            await clis[0][0].send(request_frame(
                "sch.doc.save", {}, id="w1", target_project="/test"))
            await clis[1][0].send(request_frame(
                "doc.rename", {"uuid": "u", "name": "n"}, id="w2", target_project="/test"))
            await clis[2][0].send(request_frame(
                "pcb.modify_primitive", {"primitiveId": "p", "x": 1}, id="w3",
                target_project="test2"))

            replies = [decode_frame(await cli.recv()) for cli, _ in clis]
            assert all(reply["ok"] for reply in replies), replies
            assert [reply["data"]["action"] for reply in replies] == [
                "sch.doc.save", "doc.rename", "pcb.modify_primitive",
            ]

            spans = sorted((start, end) for _, start, end in slow_a.spans)
            assert len(spans) == 2, "both A writes ran, each exactly once"
            assert spans[1][0] >= spans[0][1] - 0.02, (
                "two writes into one window must not overlap — the editor is one "
                "thread of truth"
            )
            b_start, b_end = slow_b.spans[0][1:]
            assert min(b_end, spans[0][1]) - max(b_start, spans[0][0]) > gap / 3, (
                "a write to another window must run while this one is busy; "
                "serialising across windows would make the hub a queue again"
            )

            assert daemon.window_for_instance(WINDOW_A).routed == 2
            assert daemon.window_for_instance(WINDOW_B).routed == 1

            for task in tasks:
                task.cancel()
            for cli, _ in clis:
                await cli.close()
            await a_ws.close()
            await b_ws.close()

    run(scenario())


def test_a_read_does_not_take_the_write_lock(tmp_path):
    """Writes serialise; reads do not queue behind them (023 §per-window 互斥).

    `doc.list` cannot corrupt anything, so it must not wait for a write's lock —
    the window whose write is stuck is exactly the one a diagnosis wants to read.
    The lock is taken **by the test** rather than by a slow write: a real write
    would also occupy the connector's own single-threaded frame loop, and the two
    waits are different facts.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            fake = FakeConnector(a_ws, responses={"doc.list": {"documents": []},
                                                  "sch.doc.save": {"saved": True}})
            task = asyncio.create_task(fake.serve())
            window = daemon.window_for_instance(WINDOW_A)

            await window.write_lock.acquire()   # "a write is in flight"
            try:
                reader, _ = await _hello(port, "cli")
                await reader.send(request_frame("doc.list", {}, id="r", target_project="/test"))
                reply = decode_frame(await asyncio.wait_for(reader.recv(), timeout=2))
                assert reply["ok"] is True and reply["data"] == {"documents": []}

                writer, _ = await _hello(port, "cli")
                await writer.send(request_frame("sch.doc.save", {}, id="w", target_project="/test"))
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(writer.recv(), timeout=0.3)
            finally:
                window.write_lock.release()
            # …and the queued write runs the moment the lock is free.
            assert decode_frame(await asyncio.wait_for(writer.recv(), timeout=2))["ok"] is True

            task.cancel()
            await reader.close()
            await writer.close()
            await a_ws.close()

    run(scenario())


def test_a_response_from_another_window_does_not_answer_the_call(tmp_path):
    """A hub has to check *who* answered, not just which id came back.

    Request ids are random, so this is not a defence against a hostile window —
    it is a defence against a routing bug. With several windows, "some socket
    sent a frame with this id" and "the window I asked has answered" are different
    facts, and only the second one may resolve a call.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        a = _window(WINDOW_A)
        b = _window(WINDOW_B)
        daemon.windows = {WINDOW_A: a, WINDOW_B: b}
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        daemon.pending["r1"] = PendingCall(action="doc.list", window=a, future=future)

        assert daemon.resolve_connector_response({"id": "r1", "ok": True}, b) is False
        assert not future.done(), "window B must not answer window A's call"
        assert daemon.resolve_connector_response({"id": "nope", "ok": True}, a) is False
        assert daemon.resolve_connector_response({"id": "r1", "ok": True}, a) is True
        assert future.done() and future.result()["ok"] is True

    run(scenario())


def test_two_live_sockets_claiming_one_instance_id_both_stay_visible(tmp_path):
    """The 3.2.175 double activation: reported, not silently deduplicated.

    023 §今晚不做 keeps dedup off the table, so both connections are registered —
    the newcomer under a suffixed key — and the two rows are visible in `status`.
    Routing then reports the ambiguity instead of picking one, which is the whole
    point: a dropped connection is a window the user has and the AI cannot see.
    """
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="t",
                                           instanceId=WINDOW_A, projectName="test2")
            second_ws, second = await _hello(port, "connector", token="t",
                                             instanceId=WINDOW_A, projectName="test2")
            assert first["ok"] is True and second["ok"] is True
            twin_key = f"{WINDOW_A}{WINDOW_KEY_SEPARATOR}2"
            assert second["data"]["windowKey"] == twin_key
            assert [w.key for w in daemon.live_windows()] == [WINDOW_A, twin_key]

            data = await _ping(port)
            assert [w["windowKey"] for w in data["windows"]] == [WINDOW_A, twin_key]
            assert [w["instanceId"] for w in data["windows"]] == [WINDOW_A, WINDOW_A]

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("doc.list", {}, id="x", target_project="test2"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == ErrorCodes.PROJECT_AMBIGUOUS
            assert twin_key in reply["error"]["message"]

            await cli_ws.close()
            await second_ws.close()
            await first_ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert greetings[0]["duplicateInstanceId"] is None
    assert greetings[1]["duplicateInstanceId"] == WINDOW_A
    assert greetings[1]["windowKey"] == f"{WINDOW_A}{WINDOW_KEY_SEPARATOR}2"


# --------------------------------------------------------------------------
# request-header evidence (task 004c gathers; 004d decides)
# --------------------------------------------------------------------------


def test_connect_audit_records_origin_and_user_agent(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "connector", headers={"Origin": "http://evil.example"})
            await ws.close()

    run(scenario())

    connects = [record for record in _audit_records(tmp_path)
                if record["action"] == "connect"]
    assert connects
    assert connects[0]["origin"] == "http://evil.example"
    # websockets always sends one; the point is that we capture it.
    assert connects[0]["user_agent"]


def test_a_missing_origin_is_recorded_as_null(tmp_path):
    """Absent must be distinguishable from empty — 004d has to tell them apart."""

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "cli")
            await ws.close()

    run(scenario())

    connect = next(record for record in _audit_records(tmp_path)
                   if record["action"] == "connect")
    assert connect["origin"] is None, "websockets sends no Origin by default"


def test_check_origin_allows_everything_for_now():
    """004c is evidence-gathering only — the rule is 004d's job.

    Written as an assertion rather than left implicit so that 004d cannot
    quietly inherit "always allow" without deleting this test on purpose.
    """
    assert check_origin({"origin": "http://evil.example"}) is True
    assert check_origin({"origin": None}) is True
    assert check_origin({}) is True


def test_daemon_speaks_first_with_a_banner(tmp_path):
    """Task 004b: the handshake is message driven, so the daemon opens it.

    Nothing prompts this frame — it goes out the moment the socket is accepted.
    It is the connector's only proof that the socket is up, because the
    editor's connect callback does not reliably fire.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=None)
            try:
                banner = await asyncio.wait_for(_recv_event(ws), timeout=2)
                assert banner["data"]["server"] == "boardwise"
                assert banner["data"]["protocol"] == PROTOCOL_VERSION
                assert banner["data"]["expect"] == "hello"
                assert "id" not in banner
            finally:
                await ws.close()

    run(scenario())


def test_a_silent_connection_is_hung_up_and_audited(tmp_path, monkeypatch):
    """A client that takes the banner and says nothing is closed at the timeout.

    The timeout is shortened rather than waited out: what is under test is
    "the daemon gives up on its own and records why", not the exact number of
    seconds. Silence is unambiguous now — the client was spoken to first.
    """
    monkeypatch.setattr("boardwise.bridge.daemon.HELLO_TIMEOUT", 0.5)

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=None)
            await _recv_event(ws)  # take the banner, then stay silent
            frame = await _recv_frame(ws)
            assert frame["ok"] is False
            assert frame["error"]["code"] == ErrorCodes.UNAUTHENTICATED
            assert "no hello within" in frame["error"]["message"]
            with pytest.raises(websockets.ConnectionClosed):
                await asyncio.wait_for(ws.recv(), timeout=5)

    run(scenario())

    hello = next(r for r in _audit_records(tmp_path) if r["action"] == "hello")
    assert hello["ok"] is False
    assert hello["error"] == ErrorCodes.UNAUTHENTICATED
    assert "no hello within" in hello["reason"]


def test_raw_connection_and_disconnection_are_audited(tmp_path):
    """Connect/disconnect are recorded even when no handshake ever happens.

    That is the record that separates "never connected" from "connected and
    said nothing" — the distinction task 004b turned on, and the one that was
    missing from the audit log entirely.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws = await websockets.connect(f"ws://127.0.0.1:{port}", max_size=None)
            await _recv_event(ws)
            await ws.close()
            # `async with server` waits for the handler on exit, but the close
            # record is written in its `finally`, so give it a moment.
            deadline = time.time() + 2
            while time.time() < deadline:
                if any(r["action"] == "disconnect" for r in _audit_records(tmp_path)):
                    break
                await asyncio.sleep(0.05)

    run(scenario())

    records = _audit_records(tmp_path)
    assert records[0]["action"] == "connect", "connect must be the first record"
    assert records[0]["ok"] is True
    assert records[0]["role"] == "-", "nothing is authenticated yet"
    assert ":" in records[0]["peer"], "the peer address is what netstat is compared against"
    assert any(r["action"] == "disconnect" for r in records)


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------


def test_daemon_owned_ping_reports_connector_state(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("ping", {}, id="p1"))
            data = decode_frame(await cli_ws.recv())["data"]
            assert data["pong"] is True
            assert data["connector"] is False
            # Nothing has paired yet, and `bridge status` prints this line.
            assert data["pairedFingerprint"] is None
            # `boardwise doctor` compares this with the install the CLI runs
            # from: the action catalogue is a load-time constant, so a daemon
            # left running across a checkout answers new actions with
            # UNKNOWN_ACTION — and this field is what turns that into a
            # diagnosis instead of a mystery (012v2 §九).
            from boardwise import __version__

            assert data["version"] == __version__

            conn_ws, _ = await _hello(port, "connector")
            await cli_ws.send(request_frame("ping", {}, id="p2"))
            assert decode_frame(await cli_ws.recv())["data"]["connector"] is True
            await conn_ws.close()
            await cli_ws.close()

    run(scenario())


def test_unknown_action_is_refused(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "cli")
            await ws.send(request_frame("board.explode", {}, id="x"))
            reply = decode_frame(await ws.recv())
            assert reply["error"]["code"] == ErrorCodes.UNKNOWN_ACTION
            await ws.close()

    run(scenario())


def test_editor_action_without_connector_reports_no_connector(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "cli")
            await ws.send(request_frame("pcb.readback", {}, id="r1"))
            reply = decode_frame(await ws.recv())
            assert reply["error"]["code"] == ErrorCodes.NO_CONNECTOR
            await ws.close()

    run(scenario())


def test_pcb_readback_is_forwarded_to_connector(tmp_path):
    canned = {"components": [{"designator": "U1"}], "primitives": [{"id": "p1"}]}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, responses={"pcb.readback": canned})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("pcb.readback", {"includePrimitives": True}, id="r"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True
            assert reply["data"] == canned
            assert fake.received[0]["params"] == {"includePrimitives": True}

            task.cancel()
            await cli_ws.close()

    run(scenario())


def test_sch_readback_is_forwarded_to_connector(tmp_path):
    # Mirrors the pcb case: the task requires a stub round trip per action, and
    # sch/pcb differ only in which namespace the connector reads.
    canned = {"kind": "sch", "components": [{"designator": "R1", "net": "TX"}]}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, responses={"sch.readback": canned})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("sch.readback", {}, id="s1"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True
            assert reply["data"] == canned

            task.cancel()
            await cli_ws.close()

    run(scenario())


def test_connector_error_is_relayed(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, errors={
                "sch.readback": {"code": "EDA_BUSY", "message": "editor is busy"},
            })
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("sch.readback", {}, id="s"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["error"]["code"] == "EDA_BUSY"
            assert reply["error"]["message"] == "editor is busy"

            task.cancel()
            await cli_ws.close()

    run(scenario())


def test_connector_may_not_call_editor_actions_on_itself(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "connector")
            await ws.send(request_frame("pcb.readback", {}, id="c1"))
            reply = decode_frame(await ws.recv())
            assert reply["error"]["code"] == ErrorCodes.BAD_REQUEST
            await ws.close()

    run(scenario())


def test_document_current_roundtrip(tmp_path):
    canned = {"project": {"name": "CH340G"}, "document": {"name": "Sheet1"}, "type": "sch"}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, responses={"document.current": canned})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("document.current", {}, id="d"))
            assert decode_frame(await cli_ws.recv())["data"] == canned

            task.cancel()
            await cli_ws.close()

    run(scenario())


# --------------------------------------------------------------------------
# screenshot & highlight payloads
# --------------------------------------------------------------------------


def _tiny_png() -> bytes:
    """A 1x1 PNG built by hand — no image library needed."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def test_screenshot_returns_base64_png(tmp_path):
    png = _tiny_png()

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, responses={"export.screenshot": {
                "format": "png", "encoding": "base64",
                "data": base64.b64encode(png).decode("ascii"),
            }})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("export.screenshot", {"fit": True}, id="shot"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True
            assert base64.b64decode(reply["data"]["data"]) == png

            task.cancel()
            await cli_ws.close()

    run(scenario())


def test_highlight_forwards_uuids_and_color(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector")
            fake = FakeConnector(conn_ws, responses={"canvas.highlight": {
                "highlighted": 2, "cleared": False,
            }})
            task = asyncio.create_task(fake.serve())

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("canvas.highlight", {
                "uuids": ["e1", "e2"], "color": "#FF0000", "clear": False,
            }, id="h"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["data"]["highlighted"] == 2
            assert fake.received[0]["params"]["uuids"] == ["e1", "e2"]

            task.cancel()
            await cli_ws.close()

    run(scenario())


# --------------------------------------------------------------------------
# audit log
# --------------------------------------------------------------------------


def test_audit_log_records_calls(tmp_path):
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, _ = await _hello(port, "cli")
            await ws.send(request_frame("ping", {}, id="a"))
            await ws.recv()
            await ws.send(request_frame("board.explode", {}, id="b"))
            await ws.recv()
            await ws.close()

    run(scenario())

    log = tmp_path / "audit" / f'{__import__("time").strftime("%Y-%m-%d")}.jsonl'
    assert log.exists()
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    actions = [r["action"] for r in records]
    assert "ping" in actions
    assert "board.explode" in actions
    failed = next(r for r in records if r["action"] == "board.explode")
    assert failed["ok"] is False
    assert failed["error"] == ErrorCodes.UNKNOWN_ACTION
    assert failed["role"] == "cli"
    assert "ms" in failed


def test_audit_log_never_raises_when_unwritable(tmp_path):
    daemon = BridgeDaemon(token=TOKEN, home=tmp_path / "missing" / "deep")
    # Path does not exist and mkdir would fail on a file component; the point
    # is that audit() swallows OSError rather than breaking a live call.
    daemon.audit(action="ping", ok=True)


# --------------------------------------------------------------------------
# token helpers
# --------------------------------------------------------------------------


def test_ensure_token_is_stable_and_secret(tmp_path):
    from boardwise.bridge.daemon import ensure_token, load_token, token_path

    first = ensure_token(tmp_path)
    assert len(first) == 64  # 32 bytes as hex
    assert load_token(tmp_path) == first
    assert ensure_token(tmp_path) == first  # idempotent
    assert token_path(tmp_path).name == "token"
