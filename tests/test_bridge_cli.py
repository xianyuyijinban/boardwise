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


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    """One real `bridge start` process, shared by the assertions below.

    Its console goes to a *file* rather than a pipe. A pipe would have to be
    drained by a thread to be readable at all, and the pairing announcement —
    the one message the user is told to act on — is exactly the output worth
    asserting on. A file is readable at any point, non-blocking, on any OS.
    """
    home = tmp_path_factory.mktemp("boardwise-home")
    port = _free_port()
    env = _env(home, port)
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
    try:
        if not _wait_for_port(port):
            process.kill()
            handle.flush()
            raise AssertionError(
                f"daemon never listened on {port}: {console.read_text(encoding='utf-8')}"
            )
        yield {"home": home, "port": port, "env": env, "console": console}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        handle.close()


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
        port=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


class _RecordingClient:
    """Stands in for ``BridgeClient``: records the calls, answers a canned payload."""

    opened = None
    calls: list = []

    @classmethod
    async def open(cls, uri, token, role, client=None):
        cls.opened = (uri, token, role, client)
        return cls()

    async def call(self, action, params=None):
        type(self).calls.append((action, params))
        import base64

        return {
            "ok": True,
            "oldVersion": "0.4.2",
            "newVersion": params["version"],
            "bytes": len(base64.b64decode(params["bundleB64"])),
            "database": "User_team-7_v6",
            "reloadInMs": 500,
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
    monkeypatch.setattr(client_module, "BridgeClient", _RecordingClient)
    return tmp_path


def test_update_connector_parses_its_arguments():
    from boardwise.cli import build_parser

    args = build_parser().parse_args(["bridge", "update-connector"])
    assert args.bridge_command == "update-connector"
    assert args.bundle is None and args.version is None and args.yes is False

    args = build_parser().parse_args(
        ["bridge", "update-connector", "--bundle", "b.js", "--version", "9.9.9", "--yes"]
    )
    assert (args.bundle, args.version, args.yes) == ("b.js", "9.9.9", True)


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
    assert "reloading" in out


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
