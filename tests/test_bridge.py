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
import sys
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
    CONNECTOR_ALREADY_ACTIVE,
    MAX_RECENT_REJECTIONS,
    MIN_CONNECTOR_VERSION,
    UNKNOWN_CONNECTOR_VERSION,
    AUDIT_REVOKE,
    ActiveConnector,
    BridgeDaemon,
    RejectionNotice,
    _bound_port,
    _clock,
    check_origin,
    connector_fingerprint,
    connector_token_path,
    load_connector_token,
    revoke_connector_token,
    start_server,
    status_lines,
)
from boardwise.bridge.protocol import (
    EVENT_BANNER,
    HELLO_TIMEOUT,
    PROTOCOL_VERSION,
    BridgeError,
    ErrorCodes,
    banner_frame,
    decode_frame,
    error_frame,
    frame_kind,
    request_frame,
    response_frame,
)

TOKEN = "test-token-not-a-real-secret"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


class FakeConnector:
    """Stands in for the .eext: answers actions with canned data."""

    def __init__(self, websocket, responses=None, errors=None):
        self.ws = websocket
        self.responses = responses or {}
        self.errors = errors or {}
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
                await self.ws.send(error_frame(frame.get("id"), self.errors[action]))
            else:
                await self.ws.send(
                    response_frame(frame.get("id"), self.responses.get(action, {}))
                )


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

    The daemon clears `daemon.connector` from its handler's `finally`, which
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
            assert daemon.connector is not None
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
            assert daemon.connector is not None

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
            await _until(lambda: daemon.connector is None)
            assert daemon.connector is None

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
            assert daemon.connector is not None

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
# one active connector at a time (018 §A)
# --------------------------------------------------------------------------

#: Two editor windows, as the daemon sees them: two sockets, two instance ids,
#: one shared token (both windows run the same extension install, so the
#: extension storage — and the pairing record — is the same one).
WINDOW_A = "inst-101500123-aaaaaaaa"
WINDOW_B = "inst-101533456-bbbbbbbb"


class FakeSocket:
    """A connector socket whose liveness is whatever the test says it is.

    The daemon reads `state` to decide whether a connector is *attached*, so a
    double that answers it is the only way to test the reload window at all: in
    the wild the peer is gone while the handler has not yet run its `finally`,
    and no amount of sleeping makes a real socket reproduce that ordering
    reliably.
    """

    def __init__(self, state: State = State.CLOSED) -> None:
        self.state = state
        self.remote_address = ("127.0.0.1", 1)
        self.sent: list = []

    async def send(self, raw) -> None:
        self.sent.append(raw)

    async def close(self) -> None:
        self.state = State.CLOSED


def _held_by(instance_id: str = WINDOW_A, version: str = "0.4.4") -> ActiveConnector:
    return ActiveConnector(
        instance_id=instance_id,
        client=f"boardwise-connector/{version}",
        connector_version=version,
        peer="127.0.0.1:1",
        connected_at=time.time(),
    )


def test_a_second_connector_is_refused_while_the_first_is_attached(tmp_path):
    """The accident this whole section exists to stop.

    Both windows present the **same** paired token, because they share one
    extension install — so the pairing check cannot tell them apart and used to
    let the second one displace the first. The two then took turns every few
    minutes, and each write landed in whichever project the window that happened
    to be winning had focused (measured 2026-09-21).
    """

    notices: list[RejectionNotice] = []
    shared_token = "one-token-for-one-extension-install"

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_rejection=notices.append)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(
                port, "connector", token=shared_token,
                instanceId=WINDOW_A, connectorVersion="0.4.10",
            )
            assert first["ok"] is True
            assert daemon.active_instance().instance_id == WINDOW_A

            second_ws, second = await _hello(
                port, "connector", token=shared_token,
                instanceId=WINDOW_B, connectorVersion="0.4.10",
            )
            assert second["ok"] is False
            assert second["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            # The refusal is *said*, then the socket closes: a bare disconnect
            # would be indistinguishable from a crash on the editor side.
            with pytest.raises(websockets.ConnectionClosed):
                await asyncio.wait_for(second_ws.recv(), timeout=5)

            # …and the window that had the bridge still has it.
            assert daemon.connector is not None
            assert daemon.active_instance().instance_id == WINDOW_A
            await first_ws.close()

    run(scenario())

    assert len(notices) == 1
    assert notices[0].active_instance_id == WINDOW_A
    assert notices[0].instance_id == WINDOW_B
    line = "\n".join(notices[0].console_lines())
    assert "另一个编辑器实例已连接" in line
    assert "关闭多余的 EasyEDA 窗口" in line

    refusals = [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_CONNECTOR_REJECTED]
    assert len(refusals) == 1
    assert refusals[0]["ok"] is False
    # Both sides of the collision, so the log answers "which two windows" after
    # the fact — the question that was unanswerable on 2026-09-21.
    assert refusals[0]["instanceId"] == WINDOW_B
    assert refusals[0]["activeInstanceId"] == WINDOW_A
    assert refusals[0]["connectorVersion"] == "0.4.10"
    assert refusals[0]["peer"], "the refused peer's address is what netstat is compared against"

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert [record["instanceId"] for record in greetings] == [WINDOW_A]


def test_connector_already_active_is_declared_once_and_only_in_the_protocol():
    """The refusal code belongs to the wire vocabulary, not to the daemon (018 §A).

    It was declared in ``daemon.py`` while every other code travelled out of
    ``ErrorCodes`` — two homes for one vocabulary, and the home that matters is
    the protocol's, because the connector reading ``error.code`` never imports
    the daemon. The daemon's name survives as an *alias*: the refusal site, the
    audit reader and the tests above refer to it by that name, and a second
    literal would be a second thing to keep in step. ``is`` rather than ``==``
    on purpose — a copy that happens to spell the same today is exactly the
    drift this test exists to catch.
    """
    from boardwise.bridge import daemon as daemon_module

    assert ErrorCodes.CONNECTOR_ALREADY_ACTIVE == "CONNECTOR_ALREADY_ACTIVE"
    assert daemon_module.CONNECTOR_ALREADY_ACTIVE is ErrorCodes.CONNECTOR_ALREADY_ACTIVE
    assert "CONNECTOR_ALREADY_ACTIVE" in daemon_module.__all__


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


def test_a_write_after_a_refusal_reaches_the_instance_that_holds_the_bridge(tmp_path):
    """The failure mode, end to end: the answer must come from window A.

    An audit record saying "refused" would not prove the routing; the request
    has to actually arrive on the socket that holds the bridge, which is the
    thing that was wrong when writes landed in the wrong project.
    """
    canned = {"components": [{"designator": "U1"}]}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A)
            fake = FakeConnector(first_ws, responses={"pcb.readback": canned})
            task = asyncio.create_task(fake.serve())

            second_ws, second = await _hello(port, "connector", token="t", instanceId=WINDOW_B)
            assert second["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            await second_ws.close()

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("pcb.readback", {}, id="r"))
            reply = decode_frame(await cli_ws.recv())
            assert reply["ok"] is True
            assert reply["data"] == canned
            assert len(fake.received) == 1, "the refused window must receive nothing"

            task.cancel()
            await first_ws.close()
            await cli_ws.close()

    run(scenario())


@pytest.mark.parametrize("state", [State.CLOSED, State.CLOSING])
def test_a_dead_socket_is_taken_over_without_a_fuss(tmp_path, state):
    """The reload path, which has to stay smooth.

    The socket is dead while `self.connector` is still set — exactly the state a
    reload leaves behind, because the handler's `finally` has not run yet.
    Nobody is being displaced, so the newcomer takes the bridge; refusing here
    would leave the extension dead until the daemon was restarted.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        daemon.connector = FakeSocket(state)
        daemon.active = _held_by()
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "connector", token="t", instanceId=WINDOW_B)
            assert reply["ok"] is True
            # The dead holder is gone from the daemon's books, not just stopped.
            assert daemon.active_instance().instance_id == WINDOW_B
            assert not isinstance(daemon.connector, FakeSocket)
            await ws.close()

    run(scenario())

    assert not [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_CONNECTOR_REJECTED]
    greeting = next(record for record in _audit_records(tmp_path)
                    if record["action"] == "hello" and record.get("ok") is True)
    assert greeting["instanceId"] == WINDOW_B
    assert greeting["tookOverFrom"] == WINDOW_A, "the log names what it replaced"


def test_a_connector_without_an_instance_id_is_named_by_its_connection(tmp_path):
    """Old builds keep working, and the daemon does not pretend otherwise.

    A connector that predates `instanceId` must still connect — refusing every
    existing install to add a diagnostic field would be a strange trade — so the
    daemon invents an id for the *connection* and records that it did.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, first = await _hello(port, "connector", token="t")
            assert first["ok"] is True
            first_instance = daemon.active_instance()
            assert first_instance is not None
            assert first_instance.instance_id.startswith("conn-")
            assert first_instance.instance_id_source == "connection"
            await first_ws.close()
            await _until(lambda: daemon.connector is None)

            # Per connection, not per daemon: the second socket gets its own.
            second_ws, second = await _hello(port, "connector", token="t")
            assert second["ok"] is True
            assert daemon.active_instance().instance_id != first_instance.instance_id
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


def test_ping_reports_the_active_instance_and_the_refusals(tmp_path):
    """What `bridge status` reads to answer "who is connected?"."""

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_rejection=lambda notice: None)
        server, port = await _start(daemon)
        async with server:
            conn_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                      connectorVersion="0.4.10")
            cli_ws, _ = await _hello(port, "cli")

            await cli_ws.send(request_frame("ping", {}, id="p1"))
            data = decode_frame(await cli_ws.recv())["data"]
            assert data["connector"] is True
            assert data["activeInstance"]["instanceId"] == WINDOW_A
            assert data["activeInstance"]["connectorVersion"] == "0.4.10"
            assert data["activeInstance"]["instanceIdSource"] == "hello"
            assert data["recentRejections"] == []

            for index in range(MAX_RECENT_REJECTIONS + 2):
                extra_ws, refused = await _hello(
                    port, "connector", token="t", instanceId=f"inst-extra-{index}",
                )
                assert refused["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
                await extra_ws.close()

            await cli_ws.send(request_frame("ping", {}, id="p2"))
            data = decode_frame(await cli_ws.recv())["data"]
            assert len(data["recentRejections"]) == MAX_RECENT_REJECTIONS, (
                "bounded: a refused window retries, so this list may not grow forever"
            )
            assert data["recentRejections"][0]["instanceId"] == (
                f"inst-extra-{MAX_RECENT_REJECTIONS + 1}"
            ), "newest first — the one just refused is the interesting one"

            await conn_ws.close()
            await cli_ws.close()

    run(scenario())


def test_status_lines_are_silent_when_there_is_nothing_to_say():
    """A daemon with no connector and no refusals prints what it always did."""
    assert status_lines({}) == []
    assert status_lines({"connector": False, "recentRejections": []}) == []


def test_status_lines_name_the_instance_and_the_refusals():
    lines = status_lines({
        "activeInstance": {
            "instanceId": WINDOW_A, "instanceIdSource": "hello", "client": "boardwise-connector",
            "connectorVersion": "0.4.10", "peer": "127.0.0.1:51234", "connectedAt": 1790000000.0,
        },
        "recentRejections": [{
            "ts": 1790000100.0, "instanceId": WINDOW_B, "connectorVersion": None,
            "reason": "another editor instance is already connected",
        }],
    })
    assert any(WINDOW_A in line and "connector 0.4.10" in line for line in lines)
    assert any(WINDOW_B in line and UNKNOWN_CONNECTOR_VERSION in line for line in lines)
    assert any("peer: 127.0.0.1:51234" in line for line in lines)
    assert all(line.startswith("  ") for line in lines)


def test_status_lines_mark_an_id_the_daemon_had_to_invent():
    """An invented id must not read like a claimed one."""
    lines = status_lines({"activeInstance": {
        "instanceId": "conn-0123456789abcdef", "instanceIdSource": "connection",
        "connectorVersion": None,
    }})
    assert any("no instanceId sent" in line for line in lines)


def test_status_lines_map_every_window_to_its_project():
    """The line that answers "which projects does 岳 have open?" (021 §2.3).

    The bridge talks to exactly one editor window, so the *other* windows are
    only visible through the refusals they left behind — each refusal naming the
    project of the window it turned away. Deduplicated by project, because a
    refused window retries every 20–40 s and the raw list is one project over
    and over.
    """
    lines = status_lines({
        "activeInstance": {
            "instanceId": WINDOW_A, "instanceIdSource": "hello", "client": "boardwise-connector",
            "connectorVersion": "0.4.11", "peer": "127.0.0.1:51234", "connectedAt": 1790000000.0,
            "projectName": "/test", "projectUuid": "uuid-test",
        },
        "recentRejections": [
            {"ts": 1790000100.0, "instanceId": WINDOW_B, "reason": "refused",
             "projectName": "test2", "projectUuid": "uuid-test2"},
            # The same window retrying — one project, not two.
            {"ts": 1790000120.0, "instanceId": WINDOW_B, "reason": "refused",
             "projectName": "test2", "projectUuid": "uuid-test2"},
            # An old build, which has no project to report.
            {"ts": 1790000130.0, "instanceId": "inst-old", "reason": "refused"},
        ],
    })

    assert any(
        "active instance" in line and "[project /test (uuid-test)]" in line for line in lines
    ), lines
    assert any(
        "refused connector" in line and "[project test2 (uuid-test2)]" in line for line in lines
    ), lines
    seen = [line for line in lines if "projects seen:" in line]
    assert seen == [
        "  projects seen: /test (active), test2 (refused), 1 instance(s) naming no project"
    ], seen


def test_status_lines_are_byte_identical_when_no_window_named_a_project():
    """Before 021 §2.3, word for word — and an old connector still gets that.

    Every field is optional, so the common case until the extension is
    sideloaded is a daemon that knows no projects at all. Its output must not
    grow a placeholder, an empty suffix or a summary line: nothing is known, so
    nothing is said.
    """
    stamp = 1790000000.0
    refusal_at = 1790000100.0
    data = {
        "activeInstance": {
            "instanceId": WINDOW_A, "instanceIdSource": "hello", "client": "boardwise-connector",
            "connectorVersion": "0.4.10", "peer": "127.0.0.1:51234", "connectedAt": stamp,
        },
        "recentRejections": [{
            "ts": refusal_at, "instanceId": WINDOW_B, "connectorVersion": None,
            "reason": "another editor instance is already connected",
        }],
    }

    assert status_lines(data) == [
        f"  active instance: {WINDOW_A} (connector 0.4.10)",
        f"    peer: 127.0.0.1:51234  connected: {_clock(stamp)}",
        f"  refused connector: {WINDOW_B} (connector {UNKNOWN_CONNECTOR_VERSION})"
        f" at {_clock(refusal_at)} — another editor instance is already connected",
    ]
    # And a daemon that knows nothing at all says nothing at all, as it did:
    # "1 instance naming no project" beside no project is not a fact worth a
    # line, and printing it would break the old output shape for nothing.
    assert status_lines({"recentRejections": [{"instanceId": WINDOW_B}]}) == [
        f"  refused connector: {WINDOW_B} (connector {UNKNOWN_CONNECTOR_VERSION}) at ? — refused"
    ]


def test_a_window_that_names_no_project_still_connects(tmp_path):
    """Backwards compatibility, both directions (021 §2.3).

    An old connector sends neither field, and must be welcomed exactly as
    before: refused devices keep their refusal reason, the holder keeps its
    slot. The daemon records the absence as ``None`` — it has no way to know
    that window's project, and filling it in with the project of the window it
    *is* talking to would be the very confusion this field exists to end.
    """

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_rejection=lambda notice: None)
        server, port = await _start(daemon)
        async with server:
            # An old build: no projectName, no projectUuid, no instanceId either.
            first_ws, first = await _hello(port, "connector", token="t")
            assert first["ok"] is True
            holder = daemon.active_instance()
            assert holder.project_name == ""
            assert holder.as_status()["projectName"] is None
            assert holder.as_status()["projectUuid"] is None

            second_ws, refused = await _hello(port, "connector", token="t",
                                              instanceId=WINDOW_B, projectName="test2")
            assert refused["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            await second_ws.close()

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("ping", {}, id="p"))
            data = decode_frame(await cli_ws.recv())["data"]
            assert data["activeInstance"]["projectName"] is None
            # A name without a uuid is kept as it came — half an identity is
            # still more than none, and the daemon does not invent the other half.
            assert data["recentRejections"][0]["projectName"] == "test2"
            assert data["recentRejections"][0]["projectUuid"] is None

            await first_ws.close()
            await cli_ws.close()

    run(scenario())

    # The audit log carries both windows' projects after the fact.
    refusals = [record for record in _audit_records(tmp_path)
                if record["action"] == AUDIT_CONNECTOR_REJECTED]
    assert refusals[0]["projectName"] == "test2"
    assert refusals[0]["projectUuid"] is None
    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert greetings[0]["projectName"] is None


def test_each_window_reports_its_own_project(tmp_path):
    """The point of the whole feature: the two projects, seen from the daemon.

    `bridge status` is rendered by :func:`status_lines`, but what it renders has
    to come off the wire: two windows, each naming a different project, and the
    refused one must keep its project even though its socket is closed a moment
    after it speaks — that closed socket is all the evidence there will ever be
    that the second project is open.
    """

    async def scenario():
        daemon = BridgeDaemon(token=TOKEN, home=tmp_path, on_rejection=lambda notice: None)
        server, port = await _start(daemon)
        async with server:
            holder_ws, holder_reply = await _hello(
                port, "connector", token="t", instanceId=WINDOW_A,
                projectName="/test", projectUuid="uuid-test",
            )
            assert holder_reply["ok"] is True
            assert daemon.active_instance().project_name == "/test"
            assert daemon.active_instance().project_uuid == "uuid-test"

            extra_ws, refused = await _hello(
                port, "connector", token="t", instanceId=WINDOW_B,
                projectName="test2", projectUuid="uuid-test2",
            )
            assert refused["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            await extra_ws.close()

            cli_ws, _ = await _hello(port, "cli")
            await cli_ws.send(request_frame("ping", {}, id="p"))
            data = decode_frame(await cli_ws.recv())["data"]

            lines = status_lines(data)
            assert any("[project /test (uuid-test)]" in line for line in lines), lines
            assert any("[project test2 (uuid-test2)]" in line for line in lines), lines
            assert any(
                line == "  projects seen: /test (active), test2 (refused)" for line in lines
            ), lines

            await holder_ws.close()
            await cli_ws.close()

    run(scenario())

    greetings = [record for record in _audit_records(tmp_path)
                 if record["action"] == "hello" and record.get("ok") is True]
    assert [(record["projectName"], record["projectUuid"]) for record in greetings] == [
        ("/test", "uuid-test")
    ]


def test_the_daemon_prints_the_refusal_line_when_nobody_listens(tmp_path, capsys):
    """`bridge start` installs no callback, so the daemon prints it itself.

    The line is the whole safety mechanism (018 §A): it is the only thing that
    tells the user two windows are fighting over the bridge, and the process
    that happens to own the console is an implementation detail.
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, _ = await _hello(port, "connector", token="t",
                                       instanceId=WINDOW_A, connectorVersion="0.4.10")
            second_ws, refused = await _hello(port, "connector", token="t",
                                              instanceId=WINDOW_B, connectorVersion="0.4.4")
            assert refused["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            await second_ws.close()
            await first_ws.close()

    run(scenario())

    printed = capsys.readouterr().out
    assert "另一个编辑器实例已连接" in printed
    assert WINDOW_A in printed
    assert "connector 0.4.10" in printed, "name the holder's build, not the refused one's"


def test_the_refusal_is_still_said_on_a_console_that_cannot_render_chinese(
    tmp_path, monkeypatch
):
    """A non-CJK code page must not swallow the one warning the user gets.

    On a Windows console that is not UTF-8 or GBK, printing the Chinese line
    raises `UnicodeEncodeError`. The daemon then says the same thing in ASCII
    rather than saying nothing — losing this line would leave the user with two
    windows fighting over the bridge and no explanation.
    """

    class AsciiOnlyConsole:
        """A stdout whose encoding refuses anything above U+007F."""

        def __init__(self) -> None:
            self.text = ""

        def write(self, text: str) -> None:
            text.encode("ascii")  # raises UnicodeEncodeError, like the real one
            self.text += text

        def flush(self) -> None:
            pass

    console = AsciiOnlyConsole()
    monkeypatch.setattr(sys, "stdout", console)

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            first_ws, _ = await _hello(port, "connector", token="t",
                                       instanceId=WINDOW_A, connectorVersion="0.4.10")
            second_ws, refused = await _hello(port, "connector", token="t",
                                              instanceId=WINDOW_B)
            assert refused["error"]["code"] == CONNECTOR_ALREADY_ACTIVE
            await second_ws.close()
            await first_ws.close()

    run(scenario())

    assert "another editor instance is already connected" in console.text
    assert WINDOW_A in console.text
    assert console.text.isascii(), "the fallback must be encodable by definition"


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
