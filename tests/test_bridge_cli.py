"""`boardwise bridge` CLI against a real daemon process.

The protocol tests in ``test_bridge.py`` drive the daemon in-process. This file
covers the other half of the contract: the CLI's own wiring and its **exit
codes**, which the README and ``docs/bridge.md`` state as promises —

    0  daemon up and connector attached
    1  daemon up, no connector (or the action failed)
    2  daemon not reachable

Nothing here needs EasyEDA, so it is automated rather than left to the manual
checklist. It is the slowest test in the suite (~1.5 s) because it starts a real
subprocess and waits for a port; the daemon is started once and shared by every
assertion to keep that cost to one startup.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import websockets

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _env(home: Path, port: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    return env


def _cli(args, env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


def test_status_without_a_daemon_exits_2(tmp_path):
    # The most common state in practice: nobody started the daemon. The message
    # must name the port, and the exit code must be distinguishable from
    # "running but no connector".
    env = _env(tmp_path, _free_port())
    result = _cli(["bridge", "status"], env)
    assert result.returncode == 2
    assert "daemon not reachable" in result.stdout


def _start_daemon(home: Path, port: int, env: dict):
    """Start one real ``bridge start`` process; hand back its console file.

    Its console goes to a *file* rather than a pipe. A pipe would have to be
    drained by a thread to be readable at all, and the pairing announcement —
    the one message the user is told to act on — is exactly the output worth
    asserting on. A file is readable at any point, non-blocking, on any OS.
    Returns ``(process, handle, console)``; the caller owns stopping it.
    """
    console = home / "daemon-console.log"
    handle = open(console, "w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "boardwise.cli", "bridge", "start"],
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env,
    )
    if not _wait_for_port(port):
        process.kill()
        handle.flush()
        raise AssertionError(
            f"daemon never listened on {port}: {console.read_text(encoding='utf-8')}"
        )
    return process, handle, console


def _stop_daemon(process, handle) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    handle.close()


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    """One real `bridge start` process, shared by the assertions below."""
    home = tmp_path_factory.mktemp("boardwise-home")
    port = _free_port()
    env = _env(home, port)
    process, handle, console = _start_daemon(home, port, env)
    try:
        yield {"home": home, "port": port, "env": env, "console": console}
    finally:
        _stop_daemon(process, handle)


def _console(daemon) -> str:
    return daemon["console"].read_text(encoding="utf-8")


def _audit_lines(home: Path) -> list[dict]:
    lines: list[dict] = []
    for path in sorted((home / "audit").glob("*.jsonl")):
        lines.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    return lines


async def _connector_hello_async(port: int, token: str) -> dict:
    """One connector handshake, awaited — see :func:`_connector_hello`."""
    async with websockets.connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
        banner = json.loads(await ws.recv())
        assert banner["event"] == "banner"
        await ws.send(json.dumps({
            "id": "hello",
            "action": "hello",
            "params": {
                "token": token,
                "role": "connector",
                "protocol": "1.0",
                "client": "boardwise-connector/0.2.0",
            },
        }))
        return json.loads(await ws.recv())


def _connector_hello(port: int, token: str) -> dict:
    """Run one connector handshake from this process, as the extension would.

    Deliberately the *real* socket and the *real* frames: this file's job is
    the CLI and the daemon as separate processes, so faking the client would
    leave exactly the seam it exists to cover. Returns the reply frame, ok or
    not — refusing a connector is as much a documented outcome as accepting it.
    """
    return asyncio.run(_connector_hello_async(port, token))


def _with_live_connector(port: int, token: str, body):
    """Run `body(reply)` with a connector **still attached** to the daemon.

    `_connector_hello` closes its socket before it returns, and since 004f that
    changes the answer the next connector gets: with nobody attached an unknown
    token may re-pair. Tests about *refusal* need a connector that is still
    there, so the assertions that depend on it run inside this scope. `body` is
    asynchronous, and runs inside this loop so the socket stays open.
    """

    async def run():
        async with websockets.connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            banner = json.loads(await ws.recv())
            assert banner["event"] == "banner"
            await ws.send(json.dumps({
                "id": "hello",
                "action": "hello",
                "params": {
                    "token": token,
                    "role": "connector",
                    "protocol": "1.0",
                    "client": "boardwise-connector/0.2.0",
                },
            }))
            return await body(json.loads(await ws.recv()))

    return asyncio.run(run())


def test_start_creates_a_64_hex_token(daemon):
    token = daemon["home"] / "token"
    assert token.exists(), "bridge start must create the token file"
    value = token.read_text(encoding="utf-8").strip()
    assert len(value) == 64
    assert all(character in "0123456789abcdef" for character in value)


def test_status_reports_no_connector_and_exits_1(daemon):
    result = _cli(["bridge", "status"], daemon["env"])
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"daemon up on 127.0.0.1:{daemon['port']}" in result.stdout
    assert "connector: not connected" in result.stdout


def test_editor_actions_without_a_connector_exit_1_with_no_connector(daemon):
    # The user-facing failure mode: the daemon is fine, the editor side is not.
    # The message must point at the likely cause, not print a bare code.
    png = daemon["home"] / "shot.png"
    screenshot = _cli(["bridge", "screenshot", str(png)], daemon["env"])
    assert screenshot.returncode == 1
    assert "NO_CONNECTOR" in screenshot.stdout + screenshot.stderr
    assert "EasyEDA" in screenshot.stdout + screenshot.stderr
    assert not png.exists(), "a failed screenshot must not leave an empty file"

    highlight = _cli(["bridge", "highlight", "abc"], daemon["env"])
    assert highlight.returncode == 1
    assert "NO_CONNECTOR" in highlight.stdout + highlight.stderr


def test_status_reports_no_pairing_before_the_first_connector(daemon):
    result = _cli(["bridge", "status"], daemon["env"])
    assert "paired connector: none" in result.stdout, result.stdout


def test_a_connector_pairs_itself_and_then_only_that_token_is_accepted(daemon):
    """The new-user flow, minus the editor — and the door closing behind it.

    A connector arrives with a token it invented, is trusted, and both the
    console and `bridge status` name it by fingerprint: the two places the user
    is looking. The token itself appears in neither. A *second* connector with
    a different token is then refused, which is the whole point of pairing
    rather than leaving the port open.
    """
    secret = "c0ffee" * 10 + "c0ff"  # 64 hex, invented by "the extension"
    reply = _connector_hello(daemon["port"], secret)
    assert reply["ok"] is True, reply
    fingerprint = reply["data"]["fingerprint"]
    assert len(fingerprint) == 8
    assert reply["data"]["paired"] is True

    # 1. written down, as the pairing record
    paired_file = daemon["home"] / "connector-token"
    assert paired_file.read_text(encoding="utf-8").strip() == secret

    # 2. announced on the daemon console, with the command to undo it
    console = _console(daemon)
    assert f"paired new connector (fingerprint {fingerprint})" in console, console
    assert "boardwise bridge revoke" in console

    # 3. visible in `status`
    result = _cli(["bridge", "status"], daemon["env"])
    assert f"paired connector: {fingerprint}" in result.stdout, result.stdout
    assert secret not in result.stdout

    # 4. and on the record, without the secret
    pairing = [record for record in _audit_lines(daemon["home"])
               if record["action"] == "pairing"]
    assert len(pairing) == 1
    assert pairing[0]["fingerprint"] == fingerprint
    assert pairing[0]["client"] == "boardwise-connector/0.2.0"

    # 5. a different connector is now a stranger — while this one is still
    # attached. With nobody attached an unknown token may re-pair (004f item
    # 2), so "a stranger is refused" only holds for a live pairing.
    async def check(reply):
        assert reply["ok"] is True, reply
        refused = await _connector_hello_async(daemon["port"], "deadbeef" * 8)
        assert refused["ok"] is False
        assert refused["error"]["code"] == "UNAUTHENTICATED"
        assert paired_file.read_text(encoding="utf-8").strip() == secret, (
            "a refused connector must not overwrite the pairing"
        )

    _with_live_connector(daemon["port"], secret, check)


def test_revoke_is_a_local_command_and_needs_no_daemon(tmp_path):
    """Deliberately usable when nothing is listening.

    The moment you most want to withdraw trust is the moment you are least
    sure what is running, so `revoke` must not depend on a healthy daemon.
    """
    env = _env(tmp_path, _free_port())  # no daemon started on this port

    empty = _cli(["bridge", "revoke"], env)
    assert empty.returncode == 0
    assert "nothing to revoke" in empty.stdout

    (tmp_path / "connector-token").write_text("super-secret", encoding="utf-8")
    revoked = _cli(["bridge", "revoke"], env)
    assert revoked.returncode == 0
    assert not (tmp_path / "connector-token").exists()
    assert "super-secret" not in revoked.stdout, "the token must never be echoed"

    # The revocation is audited by the CLI process itself — there is no daemon
    # here to write it. Both invocations are recorded, including the one with
    # nothing to do: "I ran revoke and it said there was nothing" is worth
    # being able to check afterwards.
    revocations = [record for record in _audit_lines(tmp_path)
                   if record["action"] == "revoke"]
    assert len(revocations) == 2
    assert revocations[0]["fingerprint"] is None
    assert len(revocations[1]["fingerprint"]) == 8
    assert all(record["ok"] is True for record in revocations)


def test_every_call_is_audited(daemon):
    # start() + the calls above must all be on disk, with role and outcome —
    # this is the only record of what the bridge was asked to do.
    lines = _audit_lines(daemon["home"])

    actions = {record["action"] for record in lines}
    assert {"ping", "export.screenshot", "canvas.highlight"} <= actions

    failures = [record for record in lines if record.get("ok") is False]
    assert any(record.get("error") == "NO_CONNECTOR" for record in failures)
    # The wrong-token connector was refused, and that is on the record.
    assert any(record.get("error") == "UNAUTHENTICATED" for record in failures)

    # Every socket that opened must also have closed, and the pair must name
    # the peer — that is what makes "did anything connect at all?" answerable
    # from the log alone (task 004b).
    assert any(record["action"] == "connect" and "peer" in record for record in lines)
    assert any(record["action"] == "disconnect" for record in lines)
    # …and every connect carries the handshake headers 004d will rule on.
    assert all("origin" in record for record in lines if record["action"] == "connect")

    # `ms` is the duration of a *request*. Connection and pairing lifecycle
    # events carry other fields instead — see docs/bridge.md §8.
    lifecycle = {"connect", "disconnect", "hello", "pairing", "revoke"}
    requests = [record for record in lines if record["action"] not in lifecycle]
    assert requests
    assert all(record["role"] == "cli" for record in requests)
    assert all("ms" in record for record in requests)


def test_status_ignores_an_ambient_http_proxy(monkeypatch, tmp_path):
    """A loopback connection must never be routed through a proxy.

    Measured 2026-09-16: with `HTTPS_PROXY` set (the sandbox sets one),
    `websockets` 17's default `proxy=True` sent a `ws://127.0.0.1` connect to
    the proxy and it answered `InvalidProxyStatus: 502` — which reads exactly
    like "the daemon is down" while the daemon is fine. `BridgeClient.open`
    therefore passes `proxy=None`, and this pins it.
    """
    import asyncio

    import boardwise.bridge.client as client_module

    seen: dict = {}

    class FakeSocket:
        async def close(self):
            return None

    async def fake_connect(uri, **kwargs):
        seen["uri"] = uri
        seen.update(kwargs)
        return FakeSocket()

    monkeypatch.setattr(client_module, "connect", fake_connect)

    async def hello(self):
        return {"ok": True}

    monkeypatch.setattr(client_module.BridgeClient, "hello", hello)
    asyncio.run(client_module.BridgeClient.open("ws://127.0.0.1:61190/eda", "t", "cli"))
    assert seen["proxy"] is None, "the loopback connect would go through a proxy"
    assert seen["uri"].startswith("ws://127.0.0.1:")


def test_status_ignores_an_ambient_http_proxy(monkeypatch, tmp_path):
    """A loopback connection must never be routed through a proxy.

    Measured 2026-09-16: with `HTTPS_PROXY` set (the sandbox sets one),
    `websockets` 17's default `proxy=True` sent a `ws://127.0.0.1` connect to
    the proxy and it answered `InvalidProxyStatus: 502` — which reads exactly
    like "the daemon is down" while the daemon is fine. `BridgeClient.open`
    therefore passes `proxy=None`, and this pins it.
    """
    import asyncio

    import boardwise.bridge.client as client_module

    seen: dict = {}

    class FakeSocket:
        async def close(self):
            return None

    async def fake_connect(uri, **kwargs):
        seen["uri"] = uri
        seen.update(kwargs)
        return FakeSocket()

    monkeypatch.setattr(client_module, "connect", fake_connect)

    async def hello(self):
        return {"ok": True}

    monkeypatch.setattr(client_module.BridgeClient, "hello", hello)
    asyncio.run(client_module.BridgeClient.open("ws://127.0.0.1:61190/eda", "t", "cli"))
    assert seen["proxy"] is None, "the loopback connect would go through a proxy"
    assert seen["uri"].startswith("ws://127.0.0.1:")


# --------------------------------------------------------------------------
# bridge update-connector (sys.self_update, 0.4.3)
# --------------------------------------------------------------------------


def _update_args(**over):
    import argparse

    base = dict(
        command="bridge",
        bridge_command="update-connector",
        bundle=None,
        version=None,
        yes=True,
        no_verify=False,
        port=None,
        instance=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


class _RecordingClient:
    """Stands in for ``BridgeClient``: records the calls, answers a canned payload.

    Two actions are answered because task 020 §WI-2 made the command read one
    after the other: ``sys.self_update`` returns the write's own reply, and
    ``sys.probe`` stands for the **reconnected** connector naming the build it
    is running. Two knobs describe what comes back from that second read:

    * ``running_version`` — an explicit version, for the tests that need the
      connector to disagree with the write; ``None`` (the default) echoes the
      version the last ``sys.self_update`` stored, i.e. "the update worked";
    * ``reconnect`` — ``False`` makes ``sys.probe`` answer ``NO_CONNECTOR``,
      which is what the daemon says when nothing is attached: the reload has not
      finished, or the editor is closed. The CLI has to read that as "not yet"
      and let its deadline decide, never as "the new build is 0.0.0".
    """

    opened = None
    calls: list = []
    #: The routing kwargs of every call, in order — this is where a `--instance`
    #: (or `--project`) hint is visible (`{"target_instance": "inst-A"}`, or `{}`).
    routes: list = []
    #: Explicit version for the reconnected connector, or ``None`` to echo the write.
    running_version: str | None = None
    #: ``False``: nothing is attached (``sys.probe`` → ``NO_CONNECTOR``).
    reconnect: bool = True
    #: The version the last ``sys.self_update`` stored — what a successful
    #: update leaves behind, and what ``sys.probe`` echoes when
    #: ``running_version`` is ``None``.
    stored_version: str = "0.4.3"
    #: The reload timer the reply carries (the connector really sends 500).
    reload_in_ms: int = 500
    #: The daemon's `ping` window table. Only the `--instance` verification reads
    #: it, because that path cannot use `sys.probe`: the window it updated
    #: reconnects under a new instance id, so the read has to be "which windows
    #: are online and what does each announce?" rather than "probe the window I
    #: named" (see `_reloaded_window_version`).
    windows: list = []

    @classmethod
    async def open(cls, uri, token, role, client=None):
        cls.opened = (uri, token, role, client)
        return cls()

    async def call(self, action, params=None, **route):
        type(self).calls.append((action, params))
        type(self).routes.append(route)
        import base64

        if action == "ping":
            return {"connector": True, "windows": [dict(w) for w in type(self).windows]}
        if action == "sys.probe":
            from boardwise.bridge.protocol import BridgeError, ErrorCodes

            if not type(self).reconnect:
                raise BridgeError(ErrorCodes.NO_CONNECTOR, "no connector is connected")
            reported = type(self).running_version
            if reported is None:
                reported = type(self).stored_version
            return {"version": "3.2.186", "connector": reported}

        type(self).stored_version = params["version"]
        return {
            "ok": True,
            "oldVersion": "0.4.2",
            "newVersion": params["version"],
            "bytes": len(base64.b64decode(params["bundleB64"])),
            "database": "User_team-7_v6",
            "reloadInMs": type(self).reload_in_ms,
        }

    async def close(self):
        return None


@pytest.fixture
def update_env(monkeypatch, tmp_path):
    """Isolated BOARDWISE_HOME (the command opens a CLI token) + a recording client."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    _RecordingClient.opened = None
    _RecordingClient.calls = []
    _RecordingClient.routes = []
    _RecordingClient.running_version = None
    _RecordingClient.reconnect = True
    _RecordingClient.stored_version = "0.4.3"
    _RecordingClient.reload_in_ms = 500
    _RecordingClient.windows = []
    monkeypatch.setattr(client_module, "BridgeClient", _RecordingClient)
    return tmp_path


@pytest.fixture
def fast_verify(monkeypatch):
    """Shrink the verification phase's clock (task 020 §WI-2) to nothing.

    The command reads these three at call time on purpose, so a test can run
    the real phase — real probes, real deadline arithmetic — in milliseconds
    instead of waiting out the 30 s budget. The reload timer goes to 0 as well,
    so nothing sleeps; the *rule* the timer encodes ("do not read the version
    before the reload has fired") is pinned on its own further down, where it
    can be measured properly.
    """
    import boardwise.cli as cli_module

    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_INTERVAL_S", 0.01)
    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_BUDGET_S", 0.2)
    monkeypatch.setattr(cli_module, "UPDATE_RELOAD_MARGIN_S", 0.0)
    monkeypatch.setattr(_RecordingClient, "reload_in_ms", 0)
    return cli_module


def test_update_connector_parses_its_arguments():
    from boardwise.cli import build_parser

    args = build_parser().parse_args(["bridge", "update-connector"])
    assert args.bridge_command == "update-connector"
    assert args.bundle is None and args.version is None and args.yes is False
    # Verification is on by default (task 020 §WI-2); `--no-verify` turns it off.
    assert args.no_verify is False

    args = build_parser().parse_args(
        ["bridge", "update-connector", "--bundle", "b.js", "--version", "9.9.9", "--yes"]
    )
    assert (args.bundle, args.version, args.yes) == ("b.js", "9.9.9", True)

    args = build_parser().parse_args(["bridge", "update-connector", "--no-verify"])
    assert args.no_verify is True
    # `--instance` (023 follow-up): absent by default, so an unhinted update
    # keeps behaving exactly as it did before the flag existed.
    assert args.instance is None
    args = build_parser().parse_args(["bridge", "update-connector", "--instance", "inst-A"])
    assert args.instance == "inst-A"


def test_update_connector_defaults_point_at_the_repo_build():
    from boardwise.cli import _connector_artifacts

    bundle, manifest = _connector_artifacts()
    assert bundle == ROOT / "connector" / "dist" / "index.js"
    assert manifest == ROOT / "connector" / "extension.json"


def test_update_connector_payload_base64s_the_bundle_and_defaults_the_version(tmp_path):
    import base64

    from boardwise.cli import _update_connector_payload

    bundle = tmp_path / "index.js"
    bundle.write_bytes(b"console.log('bundle bytes');\n")
    manifest = tmp_path / "extension.json"
    manifest.write_text(json.dumps({"version": "1.2.3"}), encoding="utf-8")

    params, byte_count = _update_connector_payload(bundle, manifest, None)
    assert params["version"] == "1.2.3", "the default version comes from extension.json"
    assert base64.b64decode(params["bundleB64"]) == bundle.read_bytes()
    assert byte_count == len(bundle.read_bytes())

    params, _ = _update_connector_payload(bundle, manifest, "9.9.9")
    assert params["version"] == "9.9.9", "an explicit --version wins over the manifest"


def test_update_connector_payload_rejects_a_missing_bundle(tmp_path):
    from boardwise.cli import _update_connector_payload

    with pytest.raises(ValueError, match="bundle"):
        _update_connector_payload(tmp_path / "nope.js", tmp_path / "extension.json", "1.0.0")


def test_update_connector_sends_sys_self_update_with_the_bundle(update_env, tmp_path, capsys):
    import base64

    from boardwise.cli import _cmd_bridge_update_connector

    bundle = tmp_path / "custom.js"
    bundle.write_bytes(b"the new bundle\n")
    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True)
    )
    assert code == 0
    assert _RecordingClient.calls, "sys.self_update was never called"
    action, params = _RecordingClient.calls[0]
    assert action == "sys.self_update"
    assert base64.b64decode(params["bundleB64"]) == b"the new bundle\n"
    assert params["version"] == "0.4.3"
    out = capsys.readouterr().out
    assert "0.4.2 -> 0.4.3" in out
    # The contract 020 upgraded: the command no longer stops at the write's own
    # reply (that only says "stored", and the OLD build goes on answering every
    # action perfectly). It reads the *running* connector's version back and
    # says so — and the old wording that told the reader to go and check
    # themselves is gone with it.
    assert "verified: running connector is now 0.4.3" in out
    assert "reloading" not in out
    assert [action for action, _ in _RecordingClient.calls] == ["sys.self_update", "sys.probe"]
    # Read after the write, and from the connector itself (`sys.probe`), not
    # from the write's echo of its own input.
    assert _RecordingClient.calls[1][1] is None
    assert _RecordingClient.opened is not None, "the read needs its own connection"


def test_update_connector_reports_a_connector_that_did_not_take_the_update(
    update_env, fast_verify, capsys
):
    # The fake-success window, made loud: the write stored 0.4.3 and the
    # connector answering is still 0.4.2. 020's whole point is that this exits 1
    # with the two versions named, instead of printing "ok" and returning 0.
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")
    _RecordingClient.running_version = "0.4.2"

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True)
    )

    assert code == 1
    captured = capsys.readouterr()
    assert "verified" not in captured.out
    assert "0.4.2 -> 0.4.3" in captured.out, "the write's own reply is still reported"
    assert "FAILED" in captured.err and "0.4.3" in captured.err and "0.4.2" in captured.err
    assert "did not take effect" in captured.err


def test_update_connector_calls_a_timeout_unknown_not_failed(
    update_env, fast_verify, capsys
):
    # Nothing came back inside the budget (editor closed, or still reloading):
    # the honest answer is exit 3 = "cannot state", never 0 and never 1.
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")
    _RecordingClient.reconnect = False

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True)
    )

    assert code == 3
    out = capsys.readouterr()
    assert "verified" not in out.out
    assert "UNKNOWN, not failed" in out.err
    assert "boardwise bridge status" in out.err
    # It waited and retried rather than giving up on the first read.
    assert [action for action, _ in _RecordingClient.calls].count("sys.probe") > 1


def test_update_connector_no_verify_restores_the_old_behaviour(
    update_env, tmp_path, capsys
):
    # `--no-verify` is the escape hatch: same write, no read-back, no waiting —
    # and it must not even open the second connection.
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = tmp_path / "custom.js"
    bundle.write_bytes(b"x")
    _RecordingClient.reconnect = False  # would be exit 3 if the phase ran

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True, no_verify=True)
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "0.4.2 -> 0.4.3" in out
    assert "reloading" in out
    assert "verified" not in out
    assert [action for action, _ in _RecordingClient.calls] == ["sys.self_update"]


def test_update_connector_verifies_a_rebuild_of_the_same_version(update_env, fast_verify, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.11", yes=True)
    )

    assert code == 0
    assert "verified: running connector is now 0.4.11" in capsys.readouterr().out


def test_update_connector_instance_routes_the_write_and_reads_the_window_table(
    update_env, fast_verify, capsys
):
    """`update-connector --instance INST` (023 follow-up): the whole point.

    Two things change at once, and both have to be asserted because either one
    alone would still "succeed": the write is routed at the named window (top
    level `targetInstance`), and the read-back — which cannot probe that window
    any more, its connection dies with the reload — answers from the daemon's
    window table: some online window announces the stored version. Here the
    reconnected window announces it under a *new* instance id, which is exactly
    what the real reload does.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")
    # `inst-A` is the window the write went to; after the reload it is *gone* and
    # a different connection (`inst-C`, a new id) is announcing the new build.
    # Nothing here would satisfy a "probe the window you named" rule, which is
    # exactly why the read-back had to change.
    _RecordingClient.windows = [
        {"windowKey": "inst-B", "instanceId": "inst-B", "connectorVersion": "0.4.2"},
        {"windowKey": "inst-C", "instanceId": "inst-C", "connectorVersion": "0.4.3"},
    ]

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True, instance="inst-A")
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "verified: running connector is now 0.4.3" in out
    # The named window is printed before the write, since after the reload
    # nothing can be asked which window it was.
    assert "-> window inst-A" in out
    assert [action for action, _ in _RecordingClient.calls][0] == "sys.self_update"
    # The write names the window; the read did not need to (and could not).
    assert _RecordingClient.routes[0] == {"target_instance": "inst-A"}
    assert "sys.probe" not in [action for action, _ in _RecordingClient.calls], (
        "the reloaded window reconnects under a new instance id — probing the old "
        "one would read nothing"
    )
    assert _RecordingClient.routes[1] == {}


def test_update_connector_instance_reports_a_window_still_on_the_old_build(
    update_env, fast_verify, capsys
):
    """`--instance`: the addressed window never reloaded — say so, exit 1.

    The read-back the flag needs is coarser than the single-window one (it can
    only see "a window announcing the stored version"), so the branch that keeps
    it honest is this one: the window we wrote to is still online under its own
    key and still announcing the build it had before.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")
    _RecordingClient.windows = [
        {"windowKey": "inst-A", "instanceId": "inst-A", "connectorVersion": "0.4.2"},
        {"windowKey": "inst-B", "instanceId": "inst-B", "connectorVersion": "0.4.2"},
    ]

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True, instance="inst-A")
    )

    assert code == 1
    captured = capsys.readouterr()
    assert "verified" not in captured.out
    assert "FAILED" in captured.err and "did not take effect" in captured.err
    assert "window inst-A is still answering on 0.4.2" in captured.err


def test_update_connector_instance_says_unknown_when_nothing_comes_back(
    update_env, fast_verify, capsys
):
    """No window online inside the budget: "unknown", never "failed" (exit 3).

    The gap between the reload and the reconnection is the normal state of a
    correct update, so it must not be read as a verdict — the same rule 020
    fixed for the single-window path, kept for the instance one.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")
    _RecordingClient.windows = []

    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="0.4.3", yes=True, instance="inst-A")
    )

    assert code == 3
    captured = capsys.readouterr()
    assert "verified" not in captured.out
    assert "UNKNOWN, not failed" in captured.err
    assert _RecordingClient.calls.count(("ping", None)) > 1, "it waited and retried"


def test_the_verify_phase_waits_out_the_reload_before_it_reads(monkeypatch):
    """The trap this phase was born with: the OLD build answers first.

    The reload sits on a ~500 ms timer, so a probe sent immediately after the
    write is answered by the build that is about to be replaced — reading that
    as "the update failed" would call a perfectly good update a failure. So the
    first read happens only after ``reloadInMs`` plus the margin. Measured with
    a real clock but a wide margin, because the property is an ordering, not a
    duration.
    """
    import asyncio
    import time

    from boardwise.cli import _await_running_connector_version

    reads: list[float] = []

    class Client:
        @classmethod
        async def open(cls, uri, token, role, client=None):
            return cls()

        async def call(self, action, params=None):
            reads.append(time.monotonic())
            return {"connector": "0.4.3"}

        async def close(self):
            return None

    from boardwise.bridge.protocol import BridgeError

    started = time.monotonic()
    version = asyncio.run(
        _await_running_connector_version(
            Client,
            BridgeError,
            61190,
            "t",
            reload_ms=120,
            interval_s=0.01,
            budget_s=1.0,
            margin_s=0.08,
        )
    )

    assert version == "0.4.3"
    assert len(reads) == 1, "the first answer is authoritative"
    assert reads[0] - started >= 0.19, "read before the reload window had elapsed"


def test_update_connector_asks_first_and_honours_a_no(update_env, monkeypatch, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x")

    # A non-terminal stdin is not consent: refuse without opening a socket.
    class NotATty:
        def isatty(self):
            return False

    monkeypatch.setattr(sys, "stdin", NotATty())
    code = _cmd_bridge_update_connector(_update_args(bundle=str(bundle), version="1.0.0", yes=False))
    assert code == 2
    assert _RecordingClient.opened is None
    assert "--yes" in capsys.readouterr().err

    # An interactive "no" aborts the same way; a "yes" proceeds.
    class Tty:
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    code = _cmd_bridge_update_connector(_update_args(bundle=str(bundle), version="1.0.0", yes=False))
    assert code == 2
    assert _RecordingClient.opened is None
    assert "aborted" in capsys.readouterr().out

    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    code = _cmd_bridge_update_connector(_update_args(bundle=str(bundle), version="1.0.0", yes=False))
    assert code == 0
    assert _RecordingClient.calls[0][0] == "sys.self_update"
    err = capsys.readouterr().err
    assert "RELOAD" in err and "unsaved changes" in err


def test_update_connector_refuses_a_payload_beyond_the_frame_cap(
    update_env, monkeypatch, capsys
):
    """The bundle rides one WebSocket frame; the guard names the knob to raise."""
    import boardwise.bridge.daemon as daemon_module

    from boardwise.cli import _cmd_bridge_update_connector

    bundle = update_env / "b.js"
    bundle.write_bytes(b"x" * 1024)
    monkeypatch.setattr(daemon_module, "MAX_FRAME_BYTES", 100)
    code = _cmd_bridge_update_connector(
        _update_args(bundle=str(bundle), version="1.0.0", yes=True)
    )
    assert code == 2
    assert _RecordingClient.opened is None
    assert "MAX_FRAME_BYTES" in capsys.readouterr().err


# --------------------------------------------------------------------------
# the client normalises a dead transport into DISCONNECTED (M0-P0d follow-up)
# --------------------------------------------------------------------------


def _abnormal_closure() -> BaseException:
    """A real ``ConnectionClosedError`` — the shape a killed daemon produces.

    Built through the library's own frames rather than a stub class, because the
    point of the test below is that the *real* exception type is caught: a
    hand-rolled stand-in would pass even if `client.call` only caught its parent
    by accident.
    """
    import importlib

    from websockets.exceptions import ConnectionClosedError

    frames = importlib.import_module("websockets.frames")
    return ConnectionClosedError(frames.Close(1006, "abnormal closure"), None)


class _DeadSocket:
    """A socket whose ``send`` fails the way a killed daemon makes it fail."""

    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.sent: list = []

    async def send(self, payload):
        self.sent.append(payload)
        raise self.error

    async def close(self):
        return None


@pytest.mark.parametrize(
    "error_factory",
    [_abnormal_closure, lambda: ConnectionResetError("connection reset by peer")],
    ids=["connection-closed", "os-error"],
)
def test_a_dead_transport_becomes_a_disconnected_code(error_factory):
    """The draw flow branches on a code, so the code has to exist.

    `engines/` does not import `bridge/`, so it cannot know about
    `websockets.ConnectionClosed`; it reads the error's `code` by string instead.
    That makes this layer responsible for turning every transport death into that
    one code — without it, a write whose connection died looks exactly like an
    action the editor refused, and the page's state gets reported as untouched
    (measured 2026-09-18: five parts on the page, "nothing was written").
    """
    import boardwise.bridge.client as client_module
    from boardwise.bridge.protocol import BridgeError, ErrorCodes

    socket_ = _DeadSocket(error_factory())
    client = client_module.BridgeClient(socket_, "token", "cli")

    with pytest.raises(BridgeError) as excinfo:
        asyncio.run(client.call("sch.place_component", {"x": 1, "y": 2}))

    assert excinfo.value.code == ErrorCodes.DISCONNECTED
    assert "sch.place_component" in excinfo.value.message
    assert excinfo.value.detail["action"] == "sch.place_component"
    assert socket_.sent, "the request really was attempted before the socket died"


def test_closing_a_socket_that_is_already_gone_is_not_an_error():
    """`close()` runs from a `finally`, including on the daemon-died path.

    Raising there would replace a failed-but-reported draw with a traceback and
    lose the report that says which writes are unaccounted for.
    """
    import boardwise.bridge.client as client_module

    client = client_module.BridgeClient(_DeadSocket(_abnormal_closure()), "token", "cli")
    asyncio.run(client.close())  # must not raise


# --------------------------------------------------------------------------
# `bridge status`: the instance that holds the bridge, and who was refused
# (018 §A — the daemon side is in test_bridge.py; this is the CLI wiring)
# --------------------------------------------------------------------------


class _StatusClient:
    """A `BridgeClient` whose `ping` answer is whatever the test sets."""

    payload: dict = {}
    opened = None

    @classmethod
    async def open(cls, uri, token, role, client=None):
        cls.opened = (uri, token, role, client)
        return cls()

    async def call(self, action, params=None):
        assert action == "ping", "status asks for nothing else"
        return type(self).payload

    async def close(self):
        return None


@pytest.fixture
def status_env(monkeypatch, tmp_path):
    """Isolated BOARDWISE_HOME (the command opens a CLI token) + a fake client."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    _StatusClient.opened = None
    _StatusClient.payload = {"connector": True, "pairedFingerprint": "deadbeef"}
    monkeypatch.setattr(client_module, "BridgeClient", _StatusClient)
    return tmp_path


def _status_args():
    from boardwise.cli import build_parser

    return build_parser().parse_args(["bridge", "status"])


def test_status_prints_the_window_table(status_env, capsys):
    """The wiring, without a daemon: the daemon's lines have to reach stdout.

    `status_lines` renders them (tested in test_bridge.py) and `bridge status`
    has to print every one — this is the half that was missing, and a rendered
    line nobody prints is not a diagnosis.
    """
    from boardwise.cli import _cmd_bridge_status

    _StatusClient.payload = {
        "connector": True,
        "pairedFingerprint": "deadbeef",
        "windows": [
            {
                "windowKey": "window-A", "instanceId": "window-A",
                "instanceIdSource": "hello", "connectorVersion": "0.4.10",
                "peer": "127.0.0.1:51234", "connectedAt": 1790000000.0,
                "lastSeen": 1790000010.0, "routed": 2,
                "projectName": "/test", "projectUuid": "uuid-test",
                "pageUuid": "page-a", "pageType": "sch",
            },
            {
                "windowKey": "window-B", "instanceId": "window-B",
                "instanceIdSource": "hello", "connectorVersion": "0.4.10",
                "peer": "127.0.0.1:51235", "connectedAt": 1790000000.0,
                "lastSeen": 1790000000.0, "routed": 0,
                "projectName": "test2", "projectUuid": "uuid-test2",
                "pageUuid": None, "pageType": None,
            },
        ],
    }

    assert _cmd_bridge_status(_status_args()) == 0

    out = capsys.readouterr().out
    assert "windows: 2 connected" in out
    assert "window: window-A (connector 0.4.10)" in out
    assert "peer: 127.0.0.1:51234" in out
    assert "window: window-B (connector 0.4.10)" in out
    assert "projects seen: /test (window-A), test2 (window-B)" in out
    assert out.index("windows: 2 connected") < out.index("paired connector:")


def test_status_prints_nothing_extra_when_there_is_nothing_to_report(status_env, capsys):
    """A fresh daemon prints exactly what it printed before 023."""
    from boardwise.cli import _cmd_bridge_status

    _StatusClient.payload = {"connector": False, "pairedFingerprint": None}

    assert _cmd_bridge_status(_status_args()) == 1

    out = capsys.readouterr().out
    assert "connector: not connected" in out
    assert "windows:" not in out
    assert "projects seen" not in out


@pytest.fixture
def own_daemon(tmp_path):
    """A daemon this test may disturb; the shared one is asserted on elsewhere.

    A refusal is *state*: it stays in the daemon's memory and shows up in every
    later `status`. The shared fixture's assertions are written against a daemon
    that never saw one, and collection order is not something they should depend
    on. One extra process is the cheaper fix.
    """
    port = _free_port()
    env = _env(tmp_path, port)
    process, handle, console = _start_daemon(tmp_path, port, env)
    try:
        yield {"home": tmp_path, "port": port, "env": env, "console": console}
    finally:
        _stop_daemon(process, handle)


async def _hello_over(
    websocket, token: str, *, instance_id: str, version: str = "0.4.10",
    project_name: str | None = None, project_uuid: str | None = None,
) -> dict:
    """One connector handshake on an already-open socket.

    Sends the fields 018 §A added (``instanceId``, ``connectorVersion``) so the
    daemon can tell two windows apart. An id-less connector is a different case
    and is covered in test_bridge.py. Deliberately not named ``_connector_hello``
    like the helper above: that one takes a port and opens its own socket, and a
    second function of the same name would shadow it for every test in the file.

    ``project_name``/``project_uuid`` are the 021 §2.3 fields — the project the
    *window* has open — and are omitted unless a test passes them, which is also
    how an older connector arrives.
    """
    banner = json.loads(await websocket.recv())
    assert banner["event"] == "banner"
    await websocket.send(json.dumps({
        "id": "hello",
        "action": "hello",
        "params": {
            "token": token,
            "role": "connector",
            "protocol": "1.0",
            "client": f"boardwise-connector/{version}",
            "connectorVersion": version,
            "instanceId": instance_id,
            **({"projectName": project_name} if project_name else {}),
            **({"projectUuid": project_uuid} if project_uuid else {}),
        },
    }))
    return json.loads(await websocket.recv())


async def _fake_connector(
    uri: str,
    token: str,
    *,
    instance_id: str,
    project_name: str | None = None,
    project_uuid: str | None = None,
    responses: dict | None = None,
    context: dict | None = None,
):
    """A connector window that stays connected and answers actions.

    Returns ``(websocket, task)``; the caller closes the socket and cancels the
    task. It exists so the *real* CLI process can be run against a *real* daemon
    with windows attached: the CLI is a subprocess, so the sockets answering it
    have to be driven from this process's event loop.
    """
    ws = await websockets.connect(uri, max_size=None)
    reply = await _hello_over(
        ws, token, instance_id=instance_id,
        project_name=project_name, project_uuid=project_uuid,
    )
    assert reply["ok"] is True, reply

    async def serve():
        async for raw in ws:
            frame = json.loads(raw)
            if "action" not in frame or "ok" in frame:
                continue
            answer = {"id": frame.get("id"), "ok": True,
                      "data": (responses or {}).get(frame["action"], {})}
            if context:
                answer["context"] = context
            await ws.send(json.dumps(answer))

    return ws, asyncio.create_task(serve())


def test_status_lists_every_connected_window(own_daemon):
    """End to end: a real daemon, two windows, a real CLI process.

    The question `status` has to answer — "which projects are open, and which one
    is boardwise talking to?" — is asked *while* both windows are connected, so
    both sockets stay open while the CLI runs. Before 023 only the privileged one
    could appear here; the other was a refusal, and after it retried enough times
    an unbounded list of them.
    """
    uri = f"ws://127.0.0.1:{own_daemon['port']}"
    token = "the-shared-extension-token"  # both windows share one install

    async def scenario():
        a_ws, _ = await _fake_connector(uri, token, instance_id="window-A",
                                        project_name="/test", project_uuid="uuid-test")
        b_ws, _ = await _fake_connector(uri, token, instance_id="window-B",
                                        project_name="test2", project_uuid="uuid-test2")
        try:
            return await asyncio.to_thread(
                _cli, ["bridge", "status"], own_daemon["env"])
        finally:
            await a_ws.close()
            await b_ws.close()

    result = asyncio.run(scenario())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "connector: connected" in result.stdout
    assert "windows: 2 connected" in result.stdout
    assert "window: window-A (connector 0.4.10)" in result.stdout
    assert "window: window-B (connector 0.4.10)" in result.stdout
    assert token not in result.stdout, "the pairing secret must never be printed"


def test_status_maps_every_window_to_its_project(own_daemon):
    """021 §2.3 / 023, end to end: every project, with the key that reaches it.

    The question a user with three or four editor windows asks — "which projects
    does boardwise know about?" — is answerable because each window announces its
    own project as it connects, and in 023 every one of them is a row rather than
    a refusal. `projects seen` prints the hub keys, which is exactly what a caller
    writes into `--project`.
    """
    uri = f"ws://127.0.0.1:{own_daemon['port']}"
    token = "the-shared-extension-token"  # both windows share one install

    async def scenario():
        a_ws, _ = await _fake_connector(uri, token, instance_id="window-A",
                                        project_name="/test", project_uuid="uuid-test")
        b_ws, _ = await _fake_connector(uri, token, instance_id="window-B",
                                        project_name="test2", project_uuid="uuid-test2")
        try:
            return await asyncio.to_thread(
                _cli, ["bridge", "status"], own_daemon["env"])
        finally:
            await a_ws.close()
            await b_ws.close()

    result = asyncio.run(scenario())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[project /test (uuid-test)]" in result.stdout, result.stdout
    assert "[project test2 (uuid-test2)]" in result.stdout, result.stdout
    assert "projects seen: /test (window-A), test2 (window-B)" in result.stdout, result.stdout
    assert token not in result.stdout


def test_call_project_hint_reaches_that_window_from_the_cli(own_daemon):
    """`bridge call --project test2`, end to end (023).

    The flag crosses three layers — argparse, the request frame's top-level
    `targetProject`, and the daemon's route — and any one of them silently
    dropping it would still produce a *successful* call, just in the wrong
    project. So both halves are asserted: the answer comes from window B, and the
    same daemon with no hint at all refuses instead of guessing.
    """
    uri = f"ws://127.0.0.1:{own_daemon['port']}"
    token = "the-shared-extension-token"

    async def scenario():
        a_ws, a_task = await _fake_connector(
            uri, token, instance_id="window-A", project_name="/test",
            project_uuid="uuid-test",
            responses={"doc.list": {"window": "A"}},
        )
        b_ws, b_task = await _fake_connector(
            uri, token, instance_id="window-B", project_name="test2",
            project_uuid="uuid-test2",
            responses={"doc.list": {"window": "B"}},
            context={"projectName": "test2", "projectUuid": "uuid-test2",
                     "pageUuid": "page-b", "pageType": "sch"},
        )
        try:
            routed = await asyncio.to_thread(
                _cli,
                ["bridge", "call", "--action", "doc.list", "--project", "test2"],
                own_daemon["env"],
            )
            # By uuid as well: the two spellings of one window have to work.
            by_uuid = await asyncio.to_thread(
                _cli,
                ["bridge", "call", "--action", "doc.list", "--project", "uuid-test"],
                own_daemon["env"],
            )
            unhinted = await asyncio.to_thread(
                _cli, ["bridge", "call", "--action", "doc.list"], own_daemon["env"])
            missing = await asyncio.to_thread(
                _cli, ["bridge", "call", "--action", "doc.list", "--project", "test9"],
                own_daemon["env"])
        finally:
            for task in (a_task, b_task):
                task.cancel()
            await a_ws.close()
            await b_ws.close()
        return routed, by_uuid, unhinted, missing

    routed, by_uuid, unhinted, missing = asyncio.run(scenario())

    assert routed.returncode == 0, routed.stdout + routed.stderr
    assert '"window": "B"' in routed.stdout, routed.stdout
    assert by_uuid.returncode == 0 and '"window": "A"' in by_uuid.stdout
    # The two refusals are the honest half of the feature: the daemon will not
    # choose a window, and says which ones it could have chosen.
    assert unhinted.returncode == 1
    assert "WINDOW_UNSPECIFIED" in unhinted.stdout + unhinted.stderr
    assert "window-A" in unhinted.stderr and "window-B" in unhinted.stderr
    assert missing.returncode == 1
    assert "PROJECT_NOT_CONNECTED" in missing.stdout + missing.stderr
    assert token not in routed.stdout + routed.stderr


def test_call_instance_hint_reaches_that_window_from_the_cli(own_daemon):
    """`bridge call --instance inst-B`, end to end — the gap this flag closes.

    Both windows here announce **no project**, which is what the editor looks
    like right after a restart (measured 2026-09-22: three windows present
    themselves before the editor API is ready, so every context read is null).
    `--project` then has nothing to match — the call is refused — while the
    instance id the window sent in its `hello` still routes. Three layers have
    to carry it (argparse → `targetInstance` → the daemon's `route`) and the
    refusal for a name that is not online has to name the windows that are.
    """
    uri = f"ws://127.0.0.1:{own_daemon['port']}"
    token = "the-shared-extension-token"

    async def scenario():
        a_ws, a_task = await _fake_connector(
            uri, token, instance_id="window-A",
            responses={"doc.list": {"window": "A"}},
        )
        b_ws, b_task = await _fake_connector(
            uri, token, instance_id="window-B",
            responses={"doc.list": {"window": "B"}},
        )
        try:
            routed = await asyncio.to_thread(
                _cli,
                ["bridge", "call", "--action", "doc.list", "--instance", "window-B"],
                own_daemon["env"],
            )
            by_project = await asyncio.to_thread(
                _cli,
                ["bridge", "call", "--action", "doc.list", "--project", "test2"],
                own_daemon["env"],
            )
            missing = await asyncio.to_thread(
                _cli,
                ["bridge", "call", "--action", "doc.list", "--instance", "window-gone"],
                own_daemon["env"],
            )
        finally:
            for task in (a_task, b_task):
                task.cancel()
            await a_ws.close()
            await b_ws.close()
        return routed, by_project, missing

    routed, by_project, missing = asyncio.run(scenario())

    assert routed.returncode == 0, routed.stdout + routed.stderr
    assert '"window": "B"' in routed.stdout, routed.stdout
    # The dead end the flag removes: no window can be named by a project, so the
    # project hint matches nothing.
    assert by_project.returncode == 1
    assert "PROJECT_NOT_CONNECTED" in by_project.stdout + by_project.stderr
    assert missing.returncode == 1
    assert "WINDOW_NOT_CONNECTED" in missing.stdout + missing.stderr
    assert "window-A" in missing.stderr and "window-B" in missing.stderr
    assert token not in routed.stdout + routed.stderr


def test_bridge_call_project_flag_wiring(monkeypatch, tmp_path):
    """argparse → the client's `target_project`, and nothing when absent.

    The hint is passed as a keyword the client turns into the frame's top-level
    field, and it is *omitted* rather than sent empty: a frame with
    ``"targetProject": ""`` would be a hint that names the empty string, and the
    pre-023 frame is what a caller without the flag should be sending.
    """
    import boardwise.bridge.client as client_module
    from boardwise.cli import _cmd_bridge_call, build_parser

    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))

    class Recorder:
        calls: list = []

        @classmethod
        async def open(cls, *args, **kwargs):
            return cls()

        async def call(self, action, params, **kwargs):
            type(self).calls.append({"action": action, "params": dict(params), **kwargs})
            return {"ok": True}

        async def close(self):
            return None

    Recorder.calls = []
    monkeypatch.setattr(client_module, "BridgeClient", Recorder)

    parser = build_parser()
    assert parser.parse_args(["bridge", "call", "--action", "doc.list"]).project is None
    assert parser.parse_args(
        ["bridge", "call", "--action", "doc.list", "--project", "test2"]
    ).project == "test2"

    plain = parser.parse_args(["bridge", "call", "--action", "doc.list"])
    assert _cmd_bridge_call(plain) == 0
    hinted = parser.parse_args(
        ["bridge", "call", "--action", "doc.list", "--project", " test2 "]
    )
    assert _cmd_bridge_call(hinted) == 0
    by_instance = parser.parse_args(
        ["bridge", "call", "--action", "doc.list", "--instance", " inst-A "]
    )
    assert _cmd_bridge_call(by_instance) == 0
    both = parser.parse_args(
        ["bridge", "call", "--action", "doc.list", "--project", "test2",
         "--instance", "inst-A"]
    )
    assert _cmd_bridge_call(both) == 0

    assert Recorder.calls == [
        {"action": "doc.list", "params": {}},
        {"action": "doc.list", "params": {}, "target_project": "test2"},
        {"action": "doc.list", "params": {}, "target_instance": "inst-A"},
        # Both ride one frame; which one decides is the daemon's business, and
        # the CLI must not drop either on the way there.
        {"action": "doc.list", "params": {}, "target_project": "test2",
         "target_instance": "inst-A"},
    ]


def _not_our_daemon():
    """A loopback listener that answers the WebSocket handshake with garbage.

    A plain TCP server: it accepts, reads whatever arrives, and replies with
    bytes that are not an HTTP response — which is what any other process on
    the port looks like to the client library.
    """
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    port = listener.getsockname()[1]

    def serve():
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:  # the listener was closed at the end of the test
                return
            try:
                connection.recv(4096)
                connection.sendall(b"nothing here speaks websocket\r\n\r\n")
            except OSError:
                pass
            finally:
                connection.close()

    threading.Thread(target=serve, daemon=True).start()
    return port, listener


def test_status_against_a_port_that_is_not_our_daemon_exits_2(tmp_path):
    """Another process on the port is a sentence, not a traceback.

    Measured 2026-09-22: a stray listener on the bridge port accepts the TCP
    connection and then fails the WebSocket handshake, and `websockets` raises
    `InvalidMessage` — not an `OSError` — so the one command a confused user
    runs printed a Python traceback instead of the line every other
    unreachable-daemon case prints.
    """
    port, listener = _not_our_daemon()
    try:
        result = _cli(["bridge", "status"], _env(tmp_path, port))
    finally:
        listener.close()

    assert result.returncode == 2, result.stdout + result.stderr
    assert f"daemon not reachable on 127.0.0.1:{port}" in result.stdout
    assert "Traceback" not in result.stderr, result.stderr
