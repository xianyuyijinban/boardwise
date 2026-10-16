"""187c: the daemon-version self-check, and `parts add --resolve` in one step.

Two halves, one file, because they are one story about the same seam:

* **A** — a daemon is a **long-running process whose action catalogue is a
  load-time constant**, so a CLI upgraded underneath it talks to the previous
  table: a new action answers `UNKNOWN_ACTION` and a fixed one keeps its old
  meaning. `boardwise doctor` has diagnosed this since 069c, but only when it is
  run. The daemon's own version now travels on the `hello` ack — the handshake
  **every** bridge command already makes — and `bridge/client.py` says so once,
  on stderr, naming both versions and the one command that ends it. Nothing is
  restarted here: that closes online connectors' sockets, which is a real-machine
  action.

* **B** — `parts add --resolve`: one command from a datasheet to a landed entry,
  filling the `deviceUuid`/`libraryUuid` pair the verified gate demands from the
  online bridge. Offline is a **refusal** (exit 2, manual flags named) — an
  invented uuid passes the schema and fails on the board, which is the one
  outcome nobody can debug from the shelf.

Everything here is offline: the daemon is either driven at the socket seam (a
stub socket plus a scripted `hello`) or started **in-process** on an
OS-assigned port, and every `lib.device.search` answer comes from a fake client.
No EasyEDA, no 61190. Fixtures use neutral codes (R4b): no real project name and
no real part number.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import __version__ as CLI_VERSION
from boardwise import cli
from boardwise.bridge import client as client_module
from boardwise.bridge import daemon as daemon_module
from boardwise.core.parts import PartLibrary, load_parts, save_parts

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

NEUTRAL_MPN = "ACME-PWR-1000"
NEUTRAL_LCSC = "C9900000001"
NEUTRAL_DEVICE = "dev-acme-0001"
NEUTRAL_LIBRARY = "lib-acme-0001"

#: The build the fake daemon reports in the mismatch cases. Deliberately not a
#: released version: the assertion is that *both* numbers appear, and a number
#: that exists as a real build would let a half-broken message pass.
STALE_DAEMON_VERSION = "0.0.1-old"


def _facts() -> dict:
    provenance = "file:acme-pwr-1000.pdf p.4"
    return {
        "nc_pins": {"pins": ["2"], "provenance": provenance},
        "supply_pins": [
            {"pins": ["1"], "name": "VIN", "v_operating": [2.2, 5.5],
             "provenance": provenance}
        ],
    }


def _facts_file(tmp_path: Path) -> Path:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(_facts(), ensure_ascii=False), encoding="utf-8")
    return path


def _search_item(**over) -> dict:
    """One `lib.device.search` item, in the shape the connector's own notes name.

    `supplierId` / `footprintName` / `name` are the fields 180 measured the host
    answering with; the uuid pair is what a shelf entry needs. Which of them a
    real hit carries is exactly what the resolution refuses to assume, so every
    case below is built by removing one.
    """
    item = {
        "uuid": NEUTRAL_DEVICE,
        "libraryUuid": NEUTRAL_LIBRARY,
        "supplierId": NEUTRAL_LCSC,
        "footprintName": "SOIC-8_L5.0-W4.0-P1.27-LS6.0-BL",
        "name": NEUTRAL_MPN,
    }
    item.update(over)
    return item


def _search_answer(*items: dict) -> dict:
    return {
        "keyword": NEUTRAL_LCSC,
        "returned": len(items),
        "shown": len(items),
        "items": list(items),
    }


# --------------------------------------------------------------------------
# A — the daemon's version, and the CLI's one-line warning
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_drift_memory(monkeypatch):
    """A clean "already reported" memory per test.

    The de-duplication is per **process** on purpose (a command that opens two
    sockets has one finding), so without this the second test in a worker would
    be asserting on silence that belongs to the first.
    """
    monkeypatch.setattr(client_module, "_drift_reported", set())


def test_a_daemon_of_the_same_build_says_nothing():
    """The ordinary case: every command is silent about versions."""
    assert client_module.daemon_version_warning(CLI_VERSION) is None


def test_another_build_is_named_with_both_versions_and_the_way_out():
    text = client_module.daemon_version_warning(STALE_DAEMON_VERSION)
    assert text is not None
    assert text.startswith(f"boardwise bridge: daemon 运行 {STALE_DAEMON_VERSION} ≠ CLI ")
    assert CLI_VERSION in text
    # Why the mismatch matters, and the one command that ends it.
    assert "动作表是加载期常量" in text
    assert "`boardwise bridge start`" in text


def test_a_daemon_that_reports_no_version_is_unknown_not_a_comparison():
    """An older daemon answers without the field — that **is** the finding.

    Named as unknown rather than compared: printing `≠ 0.5.13` about a version
    nobody read would be inventing the number on the left of the sign.
    """
    for missing in (None, "", "   "):
        text = client_module.daemon_version_warning(missing)
        assert text is not None, missing
        assert "未知" in text
        assert CLI_VERSION in text
        assert "动作表是加载期常量" in text


class _StubSocket:
    async def close(self) -> None:
        return None


def _open_against(monkeypatch, greeting):
    """`BridgeClient.open` with no wire: the daemon says whatever `greeting` is."""
    async def fake_connect(uri, **kwargs):
        return _StubSocket()

    async def fake_hello(self):
        return greeting

    monkeypatch.setattr(client_module, "connect", fake_connect)
    monkeypatch.setattr(client_module.BridgeClient, "hello", fake_hello)
    return asyncio.run(
        client_module.BridgeClient.open("ws://127.0.0.1:61190/eda", "t", "cli")
    )


def test_a_matching_handshake_prints_nothing(monkeypatch, capsys):
    _open_against(monkeypatch, {"version": CLI_VERSION})
    assert capsys.readouterr().err == ""


def test_a_stale_handshake_warns_on_stderr_and_stays_out_of_stdout(monkeypatch, capsys):
    _open_against(monkeypatch, {"version": STALE_DAEMON_VERSION})
    captured = capsys.readouterr()
    assert STALE_DAEMON_VERSION in captured.err and CLI_VERSION in captured.err
    assert captured.out == "", "the warning must not mix into the command's answer"


def test_a_daemon_without_the_field_warns_once(monkeypatch, capsys):
    """Two connections, one finding — and no version to have been read."""
    _open_against(monkeypatch, {})          # the pre-187c ack
    _open_against(monkeypatch, {})          # a second command in the same process
    err = capsys.readouterr().err
    assert err.count("未知") == 1
    assert CLI_VERSION in err


def test_a_stale_daemon_is_reported_once_per_process(monkeypatch, capsys):
    for _ in range(2):
        _open_against(monkeypatch, {"version": STALE_DAEMON_VERSION})
    err = capsys.readouterr().err
    assert err.count("动作表是加载期常量") == 1, "one warning per command, not one per call"


def test_the_hello_ack_carries_the_daemons_own_version(tmp_path):
    """The daemon half: the field the warning reads exists, and is its own build."""
    from test_bridge import _daemon, _hello, _start, run

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            ws, reply = await _hello(port, "cli")
            try:
                assert reply["ok"] is True
                assert reply["data"]["version"] == CLI_VERSION
            finally:
                await ws.close()

    run(scenario())


def _cli_env(home: Path, port: int) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BOARDWISE_HOME"] = str(home)
    env["BOARDWISE_PORT"] = str(port)
    env["BOARDWISE_NO_AUTO_DAEMON"] = "1"
    return env


def _status_against_a_daemon(tmp_path: Path, monkeypatch, *, version: str | None) -> object:
    """A real daemon in this process, and a real `boardwise bridge status` process.

    The daemon is built from *this* checkout, so the mismatch is made by moving
    its version constant — which is exactly what an upgrade leaves behind: the
    process keeps the `__version__` it imported. Returns the CLI's result.
    """
    token = daemon_module.ensure_token(tmp_path)
    if version is not None:
        monkeypatch.setattr(daemon_module, "BOARDWISE_VERSION", version)
    daemon = daemon_module.BridgeDaemon(token=token, home=tmp_path)

    async def scenario():
        server = await daemon_module.start_server(daemon, "127.0.0.1", 0)
        env = _cli_env(tmp_path, daemon_module._bound_port(server))
        async with server:
            return await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "boardwise.cli", "bridge", "status"],
                capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
            )

    return asyncio.run(scenario())


def test_a_bridge_command_warns_against_a_stale_daemon(tmp_path, monkeypatch):
    """End to end: a daemon that outlived its upgrade, and a real CLI process.

    The assertion is on the CLI's **stderr**, because that is where a user of
    `bridge call` or `parts add --resolve` meets it.
    """
    result = _status_against_a_daemon(tmp_path, monkeypatch, version=STALE_DAEMON_VERSION)
    assert result.returncode == 1, result.stderr   # daemon up, no connector attached
    assert "daemon up on 127.0.0.1" in result.stdout, result.stdout
    assert f"daemon 运行 {STALE_DAEMON_VERSION} ≠ CLI {CLI_VERSION}" in result.stderr
    assert "boardwise bridge start" in result.stderr


def test_a_bridge_command_is_silent_against_its_own_daemon(tmp_path, monkeypatch):
    """The same path with the versions in agreement: no version talk at all."""
    result = _status_against_a_daemon(tmp_path, monkeypatch, version=None)
    assert "daemon up on 127.0.0.1" in result.stdout, result.stdout
    assert "动作表是加载期常量" not in result.stderr, result.stderr
    assert "≠ CLI" not in result.stderr, result.stderr


# --------------------------------------------------------------------------
# B — `parts add --resolve`
# --------------------------------------------------------------------------


class _FakeSearchBridge:
    """Stands in for `BridgeClient`: answers `lib.device.search`, records the asks.

    ``offline`` is the refused-connect case and an exception in ``answer`` is the
    call-failed case — different facts. Both end in a refusal, but neither may be
    reported as "the library has no such part", and this fake makes that
    distinction reachable. A callable ``answer`` is consulted per keyword, which
    is how the two-rung search is exercised without a second fake.
    """

    offline: Exception | None = None
    answer: object = {}
    calls: list[tuple[str, dict]] = []

    @classmethod
    async def open(cls, uri, token, role, client=""):
        if cls.offline is not None:
            raise cls.offline
        return cls()

    async def call(self, action, params=None):
        type(self).calls.append((action, dict(params or {})))
        if isinstance(self.answer, Exception):
            raise self.answer
        if callable(self.answer):
            return self.answer((params or {}).get("keyword"))
        return self.answer

    async def close(self) -> None:
        return None


@pytest.fixture
def bridge(monkeypatch, tmp_path):
    """Install the fake, reset its memory, and keep the real bridge home untouched."""
    _FakeSearchBridge.offline = None
    _FakeSearchBridge.answer = {}
    _FakeSearchBridge.calls = []
    monkeypatch.setattr(client_module, "BridgeClient", _FakeSearchBridge)
    monkeypatch.setattr(daemon_module, "BOARDWISE_HOME", tmp_path)
    return _FakeSearchBridge


def _shelf(tmp_path: Path) -> Path:
    return save_parts(PartLibrary(), tmp_path / "parts.json")


def _add(tmp_path: Path, *extra: str) -> int:
    return cli.main([
        "parts", "add", NEUTRAL_MPN, "--lcsc", NEUTRAL_LCSC,
        "--library", str(tmp_path / "parts.json"), *extra,
    ])


def test_resolve_is_refused_offline_and_names_the_manual_flags(bridge, capsys, tmp_path):
    """No daemon ⇒ exit 2 and the two flags a human can supply. No invented uuid."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    bridge.offline = ConnectionRefusedError("no daemon on this port")

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    err = capsys.readouterr().err
    assert code == 2
    assert "--resolve 需要在线 bridge" in err
    assert "--device-uuid" in err and "--library-uuid" in err
    assert shelf.read_bytes() == before, "a refused resolve writes nothing"


def test_resolve_fills_the_pair_so_one_command_closes_the_gate(bridge, capsys, tmp_path):
    """The scenario this batch is for: datasheet read → one command → verified entry."""
    shelf = _shelf(tmp_path)
    report = tmp_path / "report.json"
    bridge.answer = _search_answer(_search_item())

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified",
                "--json", str(report))
    out = capsys.readouterr().out
    assert code == 0, out
    # An exact key, asked for by the C-number itself.
    assert bridge.calls == [("lib.device.search", {"keyword": NEUTRAL_LCSC, "limit": 8})]
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert entry is not None
    assert (entry.deviceUuid, entry.libraryUuid) == (NEUTRAL_DEVICE, NEUTRAL_LIBRARY)
    assert entry.facts_verified is True and entry.facts == _facts()
    assert "gate: facts_verified = true" in out
    written = json.loads(shelf.read_text(encoding="utf-8"))["parts"][0]
    assert written["deviceUuid"] == NEUTRAL_DEVICE
    assert written["libraryUuid"] == NEUTRAL_LIBRARY
    # The machine shape says which pair landed, and that the bridge supplied it.
    machine = json.loads(report.read_text(encoding="utf-8"))
    assert machine["deviceUuid"] == NEUTRAL_DEVICE
    assert machine["libraryUuid"] == NEUTRAL_LIBRARY
    assert machine["resolveRequested"] is True


def test_both_explicit_uuids_win_and_the_bridge_is_not_asked(bridge, capsys, tmp_path):
    """Nothing left to fill ⇒ nothing to fetch: this path must work offline."""
    shelf = _shelf(tmp_path)
    bridge.offline = ConnectionRefusedError("no daemon on this port")

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified",
                "--device-uuid", "explicit-device-id",
                "--library-uuid", "explicit-library-id")
    out = capsys.readouterr().out
    assert code == 0, out
    assert bridge.calls == [], "an explicit pair must not open a network path"
    assert "显式优先" in out
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert (entry.deviceUuid, entry.libraryUuid) == (
        "explicit-device-id", "explicit-library-id"
    )


def test_an_explicit_device_uuid_wins_and_the_search_fills_the_other_half(
    bridge, capsys, tmp_path
):
    shelf = _shelf(tmp_path)
    bridge.answer = _search_answer(_search_item())

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified",
                "--device-uuid", "explicit-device-id")
    out = capsys.readouterr().out
    assert code == 0, out
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert (entry.deviceUuid, entry.libraryUuid) == (
        "explicit-device-id", NEUTRAL_LIBRARY
    )
    assert "deviceUuid=explicit-device-id" in out


def test_two_items_carrying_the_c_number_are_refused_with_the_candidates(
    bridge, capsys, tmp_path
):
    """An exact key must be unique, and the refusal ends in what came back."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    bridge.answer = _search_answer(_search_item(uuid="dev-a"), _search_item(uuid="dev-b"))

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    err = capsys.readouterr().err
    assert code == 2
    assert "must be unique" in err
    assert "dev-a" in err and "dev-b" in err, "the candidates must be listed, not counted"
    assert shelf.read_bytes() == before


def test_the_mpn_is_the_fallback_key_when_the_c_number_finds_nothing(
    bridge, capsys, tmp_path
):
    """`--resolve` is documented as "by MPN or C-number": both are searched."""
    shelf = _shelf(tmp_path)
    answers = {
        NEUTRAL_LCSC: _search_answer({"uuid": "dev-other", "supplierId": "C1"}),
        NEUTRAL_MPN: _search_answer(_search_item()),
    }
    bridge.answer = answers.__getitem__

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    assert code == 0, capsys.readouterr().out
    assert [params["keyword"] for _, params in bridge.calls] == [NEUTRAL_LCSC, NEUTRAL_MPN]
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert (entry.deviceUuid, entry.libraryUuid) == (NEUTRAL_DEVICE, NEUTRAL_LIBRARY)


def test_an_mpn_hit_that_carries_another_c_number_is_a_disagreement(
    bridge, capsys, tmp_path
):
    """Found by MPN, but the item's own C-number is a different part: refuse."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    answers = {
        NEUTRAL_LCSC: _search_answer({"uuid": "dev-other", "supplierId": "C1"}),
        NEUTRAL_MPN: _search_answer(_search_item(supplierId="C1")),
    }
    bridge.answer = answers.__getitem__

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    err = capsys.readouterr().err
    assert code == 2
    assert "disagrees" in err and "C1" in err
    assert shelf.read_bytes() == before


def test_a_half_uuid_pair_is_refused_rather_than_filled(bridge, capsys, tmp_path):
    """One uuid is not an identity: the pair is what the shelf's schema demands."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    bridge.answer = _search_answer(_search_item(libraryUuid=""))

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    err = capsys.readouterr().err
    assert code == 2
    assert "library uuid" in err
    assert shelf.read_bytes() == before


def test_a_daemon_that_cannot_answer_is_not_reported_as_no_such_part(
    bridge, capsys, tmp_path
):
    """A bridge failure and an empty result list are different facts."""
    shelf = _shelf(tmp_path)
    bridge.answer = RuntimeError("WINDOW_UNSPECIFIED: several windows are online")

    code = _add(tmp_path, "--resolve", "--facts", str(_facts_file(tmp_path)), "--verified")
    err = capsys.readouterr().err
    assert code == 2
    assert "WINDOW_UNSPECIFIED" in err
    assert "--device-uuid" in err, "every refusal names the manual way through"
    assert json.loads(shelf.read_text(encoding="utf-8"))["parts"] == []
