"""528A: `bridge update-connector --no-reload` — write the record, dispatch no reload.

The whole feature is one promise: a caller with unsaved editor state can stage
a new bundle **without the page going away**. On the wire that promise is
`params.reload: false`; in the CLI it is a mode that (a) puts that field on the
frame, (b) never reads the window table back — nobody is going to reload, so
every poll would only dress a *known* "written, not running" up as exit 3's
"unknown" — and (c) skips the [y/N] gate, because the gate exists to protect
unsaved state and nothing here discards it.

The fake below is the same shape as `tests/test_165_update_connector.py`'s
(`_GatedClient`): it **implements the daemon's dangerous-tier gate** rather than
trusting a dict key, and it records whether each frame asked for a reload. So
"no reload was dispatched" is asserted from what the connector was *told*, not
from a comment.

Everything here is offline: a fake `BridgeClient`, no daemon, no 61190, no
editor.
"""

import argparse
import base64

import pytest


def _args(**over):
    base = dict(
        command="bridge",
        bridge_command="update-connector",
        bundle=None,
        version=None,
        yes=False,
        no_verify=False,
        port=None,
        instance=None,
        all=False,
        no_reload=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _windows(*keys, version="0.4.25"):
    return [
        {"windowKey": key, "instanceId": key, "connectorVersion": version} for key in keys
    ]


class _FakeConnector:
    """A fake that enforces the gate, writes per window, and counts reload asks.

    Knobs:

    * ``windows`` — the daemon's table **before** the write;
    * ``windows_after`` — the table from the write onwards (set it to express
      "the reloaded page came back"), ``None`` to leave the table unchanged;
    * ``write_fails`` — ``{windowKey: (code, message)}`` for windows whose write
      the daemon/connector refuses;
    * ``pre_528a_windows`` — windows whose **running build** predates 528A;
    * ``reload_in_ms`` — what a default write's reply says about the reload.

    **Two answers, computed independently.** 528A-b's red team found this fake
    itself was the reason the suite could not see the bug it now guards: one
    expression (`reload_flag is not False`) derived both "did the page reload"
    and `reloadInMs`, so the fake answered `reloadInMs: 0` exactly when the CLI
    assumed no reload had been dispatched — and the CLI's assumption was never
    read back. `_reload_plan` now answers `(reload happened, reloadInMs)` per
    window, and the pre-528A branch returns a **literal** without looking at
    `params.reload` at all, which is what an old build does.
    """

    opened = None
    calls: list = []
    routes: list = []
    #: Params that got **past** the gate, in order (``confirm`` stripped, exactly
    #: as the daemon consumes it).
    forwarded: list = []
    #: Every value of ``params.reload`` that was seen, in frame order — the
    #: record of what the connector was asked to do about the page.
    reload_flags: list = []
    #: Frames whose ``reload`` was not exactly ``false``, i.e. the page would
    #: have been reloaded. A `--no-reload` run must leave this empty.
    reloads: list = []
    refused: list = []
    windows: list = []
    windows_after: list | None = None
    wrote: bool = False
    window_databases: dict = {}
    database_versions: dict = {}
    database_default: str = "User_team-7_v6"
    write_fails: dict = {}
    reload_in_ms: int = 500
    #: Windows whose running build is **older than 528A**: it does not know
    #: `reload: false`, so it schedules the reload anyway and says `reloadInMs:
    #: 500`. Per window on purpose — `--all` writes to several and only some of
    #: them may be old.
    pre_528a_windows: set = set()

    @classmethod
    async def open(cls, uri, token, role, client=None):
        cls.opened = (uri, token, role, client)
        return cls()

    @classmethod
    def _table(cls) -> list:
        """The window table the daemon would report right now."""
        if cls.wrote and cls.windows_after is not None:
            return cls.windows_after
        return cls.windows

    @classmethod
    def _online_keys(cls) -> list:
        from boardwise.cli import _window_key

        return [_window_key(window) for window in cls._table()]

    @classmethod
    def _reload_plan(cls, window: str, params: dict) -> tuple[bool, int]:
        """``(did this window's page reload, its reply's reloadInMs)``.

        A 528A build: the frame's `reload: false` is honoured (nothing scheduled,
        `reloadInMs: 0`), anything else keeps the original write-then-reload
        behaviour. A window in :attr:`pre_528a_windows` takes the other branch.
        """
        if window in cls.pre_528a_windows:
            return True, 500
        if (params or {}).get("reload") is False:
            return False, 0
        return True, cls.reload_in_ms

    async def call(self, action, params=None, **route):
        from boardwise.bridge.protocol import BridgeError, ErrorCodes

        type(self).calls.append((action, params))
        type(self).routes.append(route)
        if action == "ping":
            return {"connector": True, "windows": [dict(w) for w in type(self)._table()]}

        # The daemon's gate, verbatim: a frame without `confirm is True` never
        # reaches the editor. `sys.self_update` is `dangerous`, so this refusal
        # is what a caller that dropped the token would actually meet.
        if (params or {}).get("confirm") is not True:
            raise BridgeError(
                ErrorCodes.CONFIRMATION_REQUIRED,
                "sys.self_update replaces running code or reloads the editor "
                "(dangerous tier); re-send with confirm: true. Nothing was "
                "forwarded to the editor.",
            )
        # An unhinted write is routed by the daemon to the only connected
        # window (with several up it answers WINDOW_UNSPECIFIED; the command
        # never sends that call — it refuses earlier).
        window = route.get("target_instance") or ""
        if not window:
            online = type(self)._online_keys()
            if len(online) == 1:
                window = online[0]
        if window in type(self).write_fails:
            code, message = type(self).write_fails[window]
            raise BridgeError(code, message)

        forwarded = {k: v for k, v in params.items() if k != "confirm"}
        reload_flag = (params or {}).get("reload", "<absent>")
        wants_reload, reload_in_ms = type(self)._reload_plan(window, params or {})
        type(self).forwarded.append(forwarded)
        type(self).reload_flags.append(reload_flag)
        if wants_reload:
            type(self).reloads.append(forwarded)
        database = type(self).window_databases.get(window, type(self).database_default)
        old_version = type(self).database_versions.get(database, "0.4.25")
        type(self).database_versions[database] = params["version"]
        type(self).wrote = True
        return {
            "ok": True,
            "oldVersion": old_version,
            "newVersion": params["version"],
            "bytes": len(base64.b64decode(params["bundleB64"])),
            "database": database,
            "reloadInMs": reload_in_ms,
        }

    async def close(self):
        return None


class _Pre528AConnector(_FakeConnector):
    """Every window runs a build **older than 528A** (the other fake implementation).

    It never looks at `params.reload`: the old code schedules
    ``location.reload()`` unconditionally, so the page goes away and the reply
    says ``reloadInMs: 500`` whatever the frame asked for. Keeping this as its
    own class — rather than as one more branch of the same expression the CLI
    uses — is the point: a fake that derives both answers from `params.reload`
    can only ever agree with the caller.
    """

    @classmethod
    def _reload_plan(cls, window: str, params: dict) -> tuple[bool, int]:
        return True, 500


_FIELDS = (
    "opened", "calls", "routes", "forwarded", "reload_flags", "reloads",
    "refused", "windows", "windows_after", "wrote", "window_databases",
    "database_versions", "write_fails",
)


def _reset_fake() -> None:
    """Clear both fakes' recorded state (the subclass shadows what it assigns)."""
    for cls in (_FakeConnector, _Pre528AConnector):
        for name in _FIELDS:
            setattr(cls, name, None)
        cls.calls = []
        cls.routes = []
        cls.forwarded = []
        cls.reload_flags = []
        cls.reloads = []
        cls.refused = []
        cls.windows = []
        cls.windows_after = None
        cls.wrote = False
        cls.window_databases = {}
        cls.database_versions = {}
        cls.write_fails = {}
        cls.database_default = "User_team-7_v6"
        cls.reload_in_ms = 500
        cls.pre_528a_windows = set()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    import boardwise.bridge.client as client_module

    _reset_fake()
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    monkeypatch.setattr(client_module, "BridgeClient", _FakeConnector)
    return tmp_path


@pytest.fixture
def pre_528a(monkeypatch, tmp_path):
    """The same harness with an editor running a connector from before 528A."""
    import boardwise.bridge.client as client_module

    _reset_fake()
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    monkeypatch.setattr(client_module, "BridgeClient", _Pre528AConnector)
    return tmp_path


@pytest.fixture
def fast_clock(monkeypatch):
    """Shrink the verification clock so the default path can be run for real."""
    import boardwise.cli as cli_module

    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_INTERVAL_S", 0.01)
    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_BUDGET_S", 0.2)
    monkeypatch.setattr(cli_module, "UPDATE_RELOAD_MARGIN_S", 0.0)
    monkeypatch.setattr(_FakeConnector, "reload_in_ms", 0)
    return cli_module


def _bundle(path, data=b"the new bundle\n"):
    path.write_bytes(data)
    return path


def _manifest():
    """The manifest the shipped connector build takes its version from, and its version.

    ``connector/package.json`` (528A-b): `build.mjs` bakes ``__BOARDWISE_VERSION__``
    from it, so it is the string a bundle *announces* and the one ``--version``
    has to match. ``extension.json`` supplies the uuid and its version only
    matters because :func:`test_the_two_manifests_agree_on_the_version` pins the
    two equal.

    The version is read, never hard-coded: `--version` must equal this string
    (528A-a), and a hard-coded literal would turn every version bump into a pile
    of red tests that look like real failures.
    """
    import json

    from boardwise.cli import _connector_artifacts, _connector_version_source

    _, extension_json = _connector_artifacts()
    package_json = _connector_version_source(extension_json)
    return package_json, json.loads(package_json.read_text(encoding="utf-8"))["version"]


def _V():
    """Shorthand: the version a bundle built from this repo reports."""
    return _manifest()[1]


def _self_update_calls(cls=_FakeConnector):
    return [(action, params) for action, params in cls.calls if action == "sys.self_update"]


def _actions(cls=_FakeConnector):
    return [action for action, _ in cls.calls]


def _reload_warning_lines(text: str) -> list[str]:
    """The lines of the pre-528A warning, in whichever mode printed them.

    "Which windows reloaded" is a claim about *specific* windows, so the test has
    to read the warning line itself — a bare substring check would be satisfied
    by the window table printed at the top of every `--all` run.
    """
    return [line for line in text.splitlines() if "RUNNING connector" in line]


# ---------------------------------------------------------------------------
# The promise: written, and no reload asked for
# ---------------------------------------------------------------------------


def test_no_reload_writes_the_record_and_dispatches_no_reload(fake, capsys):
    """The load-bearing line: the frame says `reload: false`, and nothing polls.

    Also the confirmation gate: this run passes **no** `--yes` and pytest's
    stdin is not a terminal, so the default path would refuse with exit 2
    ("confirmation needed"). Reaching the write at all is what proves the gate
    was skipped for the mode that cannot lose unsaved state.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), all=False, no_reload=True)
    )

    assert code == 0, capsys.readouterr().err
    assert _FakeConnector.reloads == [], "a reload was asked for"
    assert _actions() == ["ping", "sys.self_update"], (
        "no window-table read-back follows a write nobody will reload"
    )
    action, params = _self_update_calls()[0]
    assert params["reload"] is False
    assert params["confirm"] is True, "the daemon's dangerous-tier token is still needed"
    assert base64.b64decode(params["bundleB64"]) == b"the new bundle\n"

    out = capsys.readouterr()
    assert "written, NOT activated" in out.out
    assert "verified" not in out.out and "verified" not in out.err
    assert "菜单" in out.out, "the one way to activate has to be named"
    assert f"0.4.25 -> {_V()}" in out.out, "the write's own reply is still reported"
    assert _FakeConnector.refused == []


def test_the_default_frame_carries_no_reload_field(fake, capsys):
    """The default run's frames must not carry the field at all.

    `--no-reload` is opt-in: a frame that grew a `reload` key unasked would be a
    behaviour change for every existing caller, and the connector's default
    (reload) then depends on a value nobody chose.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=_V())

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=False)
    )

    assert code == 0, capsys.readouterr().err
    assert _FakeConnector.reload_flags == ["<absent>"]
    assert len(_FakeConnector.reloads) == 1


def test_the_no_reload_write_is_the_same_write_as_the_default_one(fake, capsys):
    """④: the switch changes the reload, never the record.

    Same bundle bytes, same version — a `--no-reload` run that stored something
    else would be a second, silently different updater.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=False)
    )
    default = _FakeConnector.forwarded[-1]

    _FakeConnector.calls = []
    _FakeConnector.forwarded = []
    _FakeConnector.reload_flags = []
    _FakeConnector.reloads = []
    _FakeConnector.wrote = False
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = None
    _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), no_reload=True)
    )
    write_only = _FakeConnector.forwarded[-1]

    # The stored record is the same write: bundle bytes and version identical,
    # and `reload` is the *only* difference between the two frames.
    assert set(default) == {"bundleB64", "version"}
    assert set(write_only) == {"bundleB64", "version", "reload"}
    assert {k: v for k, v in write_only.items() if k != "reload"} == default


# ---------------------------------------------------------------------------
# Exit codes: the write's, never a verdict's
# ---------------------------------------------------------------------------


def test_a_refused_write_is_exit_1_with_the_reason(fake, capsys):
    from boardwise.bridge.protocol import ErrorCodes
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.write_fails = {
        "inst-A": (ErrorCodes.CONNECTOR_ERROR, "IndexedDB User_x_v6 has no object store")
    }

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), no_reload=True)
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "written, NOT activated" not in captured.out, "a refusal is not a write"
    assert ErrorCodes.CONNECTOR_ERROR in captured.err
    assert "has no object store" in captured.err


def test_an_addressing_refusal_is_exit_2_and_writes_nothing(fake, capsys):
    """Several windows online, none named: the refusal predates any write."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), no_reload=True)
    )

    captured = capsys.readouterr()
    assert code == 2
    assert _self_update_calls() == []
    assert "inst-A" in captured.err and "inst-B" in captured.err
    assert "菜单" not in captured.out


def test_an_unreadable_bundle_is_still_exit_2(fake, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    code = _cmd_bridge_update_connector(
        _args(bundle=str(fake / "nope.js"), version=_V(), no_reload=True)
    )

    assert code == 2
    assert "nope.js" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Composition: `--all`, `--instance`, `--yes`, and the default path
# ---------------------------------------------------------------------------


def test_no_reload_all_writes_every_window_one_line_each(fake, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), all=True, no_reload=True)
    )

    out = capsys.readouterr()
    assert code == 0, out.err
    assert _FakeConnector.reloads == [], "every window must get the no-reload frame"
    assert _FakeConnector.reload_flags == [False, False]
    assert [
        route for action, route in zip(_actions(), _FakeConnector.routes)
        if action == "sys.self_update"
    ] == [{"target_instance": "inst-A"}, {"target_instance": "inst-B"}]
    assert f"inst-A: 0.4.25 -> {_V()}" in out.out
    # Both windows share one IndexedDB record (§10.27), so the second write is
    # an equal rewrite and its line says so: V -> V, not a fake 0.4.25.
    assert f"inst-B: {_V()} -> {_V()}" in out.out
    assert out.out.count("已写入未激活") == 2, "one written-not-activated line per window"
    assert "菜单" in out.out
    # 528A-c: re-evaluation is per window, and the message has to say so — a
    # reader who clicks once and believes all N windows are live is exactly the
    # hole R4 experiment ④ measured (an unclicked window keeps its instance id).
    assert "每个在线窗口各自点一次 boardwise 扩展菜单" in out.out
    assert "verified" not in out.out
    assert _actions().count("ping") == 1, "no verdict polls"


def test_no_reload_all_reports_a_partial_failure_as_exit_1(fake, capsys):
    from boardwise.bridge.protocol import ErrorCodes
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")
    _FakeConnector.write_fails = {"inst-B": (ErrorCodes.CONNECTOR_ERROR, "no file record")}

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), all=True, no_reload=True)
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "inst-B: 写入失败" in captured.out
    assert "no file record" in captured.out or "no file record" in captured.err


def test_no_reload_with_instance_routes_to_that_window(fake, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), instance="inst-B", no_reload=True)
    )

    assert code == 0, capsys.readouterr().err
    write_routes = [
        route for action, route in zip(_actions(), _FakeConnector.routes)
        if action == "sys.self_update"
    ]
    assert write_routes == [{"target_instance": "inst-B"}]
    assert "window inst-B" in capsys.readouterr().out


def test_yes_is_accepted_and_changes_nothing(fake, capsys):
    """`--yes` under `--no-reload` is allowed (scripts pass it unconditionally)."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=True)
    )

    assert code == 0, capsys.readouterr().err
    assert _FakeConnector.reloads == []
    assert _FakeConnector.reload_flags == [False]


def test_the_default_path_still_reloads_and_verifies(fake, fast_clock, capsys):
    """No regression: without the flag the 020 read-back still decides exit 0."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=_V())

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=False)
    )

    out = capsys.readouterr()
    assert code == 0, out.err
    assert f"verified: running connector is now {_V()}" in out.out
    assert "written, NOT activated" not in out.out
    assert _actions().count("ping") > 1, "the default path reads the table back"
    assert _FakeConnector.reloads, "the default frame has no `reload: false`"


def test_the_default_path_still_calls_a_timeout_unknown(fake, fast_clock, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = []  # nothing ever comes back

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=False)
    )

    out = capsys.readouterr()
    assert code == 3
    assert "UNKNOWN, not failed" in out.err
    assert "written, NOT activated" not in out.out


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def test_the_parser_knows_the_flag_and_defaults_it_off():
    from boardwise.cli import build_parser

    args = build_parser().parse_args(["bridge", "update-connector"])
    assert args.no_reload is False

    args = build_parser().parse_args(["bridge", "update-connector", "--no-reload"])
    assert args.no_reload is True

    args = build_parser().parse_args(
        ["bridge", "update-connector", "--no-reload", "--all", "--yes"]
    )
    assert (args.no_reload, args.all, args.yes) == (True, True, True)

    args = build_parser().parse_args(
        ["bridge", "update-connector", "--no-reload", "--instance", "inst-A"]
    )
    assert (args.no_reload, args.instance) == (True, "inst-A")


# ---------------------------------------------------------------------------
# 528A-a: `--version` labels the record, it does not re-label the bundle
# ---------------------------------------------------------------------------


def test_an_explicit_version_the_bundle_cannot_report_is_refused_before_any_write(
    fake, fast_clock, capsys
):
    """The field shape: `--version 0.5.18-nrl` against a bundle that says 0.5.18.

    The write used to happen, the reload used to happen, and the read-back used
    to compare the two strings and call a working update FAILED. Nothing is
    written now, and the message has to carry the three facts a reader cannot
    infer: what `--version` actually writes, why the mismatch can never verify,
    and how to tell two builds apart on purpose.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=f"{_V()}-nrl")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=f"{_V()}-nrl", yes=True, no_reload=False)
    )

    captured = capsys.readouterr()
    assert code == 2
    assert _actions() == [], "nothing may be sent: not even the pre-write ping"
    assert _self_update_calls() == [], "零写入"
    assert "ok:" not in captured.out
    # ① the label vs the embedded constant
    assert "--version" in captured.err and "version 字段" in captured.err
    assert "内联进 bundle" in captured.err and "extension.json" in captured.err
    # ② the verdict could never be anything but FAILED, and it is not about reload
    assert "永远不可能满足" in captured.err
    assert "重新求值" in captured.err
    assert "卸载重装" in captured.err
    # ③ the honest way to tell two builds apart
    assert "--bundle" in captured.err and "重新 build" in captured.err
    # …and the external-bundle note
    assert "仓库外" in captured.err


def test_a_matching_explicit_version_still_goes_through(fake, fast_clock, capsys):
    """`--version X` where X is the manifest's version == the default path."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=_V())

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), yes=True, no_reload=False)
    )

    out = capsys.readouterr()
    assert code == 0, out.err
    assert _self_update_calls()[0][1]["version"] == _V()
    assert f"verified: running connector is now {_V()}" in out.out


def test_no_version_keeps_the_default_path_verbatim(fake, fast_clock, capsys):
    """No `--version`: the manifest decides, exactly as it did before 528A-a."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=_V())

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=None, yes=True, no_reload=False)
    )

    out = capsys.readouterr()
    assert code == 0, out.err
    action, params = _self_update_calls()[0]
    assert params["version"] == _V(), "the default is the manifest's own version"
    assert f"0.4.25 -> {_V()}" in out.out
    assert f"verified: running connector is now {_V()}" in out.out


def test_all_refuses_the_same_mismatch_and_writes_nothing(fake, capsys):
    """`--all` passes the same gate — it is not a per-mode guard."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")

    code = _cmd_bridge_update_connector(
        _args(
            bundle=str(bundle),
            version=f"{_V()}-probe",
            all=True,
            no_reload=True,
        )
    )

    captured = capsys.readouterr()
    assert code == 2
    assert _self_update_calls() == []
    assert "拒绝写入" in captured.err
    assert "inst-A" not in captured.out and "已写入未激活" not in captured.out


def test_the_gate_applies_to_no_reload_too(fake, capsys):
    """`--no-reload` has no read-back, but the record it writes must still not lie.

    A record labelled with a version the bundle does not carry is exactly the
    trap the next default-path run falls into, so the mode does not get an
    exemption.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=f"{_V()}-probe", no_reload=True)
    )

    assert code == 2
    assert _self_update_calls() == []
    assert "written, NOT activated" not in capsys.readouterr().out


def test_the_gate_does_not_guess_when_the_manifest_is_unreadable(tmp_path, capsys):
    """No manifest → no comparison → refuse, rather than let a label through.

    Exercised on the pure helper: reaching it through the command would need the
    *repo* manifest to be missing, which is not a state a test may create.
    """
    from boardwise.cli import _explicit_version_refusal

    refusal = _explicit_version_refusal("1.2.3", tmp_path / "absent-extension.json")

    assert refusal is not None
    assert "--version 1.2.3" in refusal and "拒绝写入" in refusal
    assert "读不到" in refusal
    # Nothing to refuse when no explicit version was given: the manifest decides.
    assert _explicit_version_refusal(None, tmp_path / "absent-extension.json") is None
    # …or when the explicit version is the manifest's own (equal is not a mismatch).
    manifest, version = _manifest()
    assert _explicit_version_refusal(version, manifest) is None
    mismatch = _explicit_version_refusal(f"{version}-x", manifest)
    assert mismatch is not None and version in mismatch


def test_the_reinstall_route_is_conditional_on_one_version_string():
    """The hint's triage (528A-a): same string first, uninstall only if it is.

    Pinned without a socket because it is a claim about wording — and 165's
    assertions (卸载 / 重新导入 .eext / 重启编辑器) must survive the reordering.
    """
    from boardwise.cli import _STILL_OLD_LEAD, _write_without_activation_hint

    plain = _write_without_activation_hint()
    assert "先分诊" in plain
    assert "只在「写进存储的版本串 == 运行中的 connector 上报的版本串」时成立" in plain
    assert "自报家门" in plain
    assert "白丢一次配对状态" in plain
    # 165's phrases stay, and they now follow the condition rather than replace it.
    assert plain.index("先分诊") < plain.index("卸载该扩展")
    assert "重新导入 .eext" in plain and "重启编辑器" in plain
    led = _write_without_activation_hint(lead=_STILL_OLD_LEAD)
    assert led.startswith(_STILL_OLD_LEAD) and led.endswith(plain[2:])



# ---------------------------------------------------------------------------
# 528A-b/c: the running build may be older than 528A, and the version token
# ---------------------------------------------------------------------------


def test_no_reload_against_a_pre_528a_connector_says_the_page_reloaded(pre_528a, capsys):
    """The hole this file could not see: an old build reloads and we said it did not.

    A connector built before 528A does not know `reload: false`. It writes the
    record, schedules ``location.reload()`` anyway and answers ``reloadInMs: 500``
    — so the two sentences `--no-reload` prints ("no reload was dispatched",
    "unsaved edits are safe") are both false, and they were printed
    unconditionally because nothing ever read that field back. The write itself
    did land, so the exit code stays 0; the *page* is what changed.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(pre_528a / "b.js")
    _Pre528AConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), no_reload=True)
    )

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code == 0, "the record was written; the exit code is the write's"
    assert _Pre528AConnector.reloads, "the old build reloads whatever the frame asks"
    assert [p.get("reload") for _, p in _self_update_calls(_Pre528AConnector)] == [False], (
        "the frame still asks for no reload — the old build simply ignores the field"
    )

    assert "no reload was dispatched" not in text, (
        "the one sentence that must never be printed when the page went away"
    )
    assert "written, NOT activated" not in text
    assert "未保存的编辑不会丢" not in text
    # What the reader needs instead: which build, what it did, what may be lost,
    # and the one route that makes `--no-reload` mean what it says from then on.
    assert "528A" in text
    assert "仍然 reload" in text
    assert "可能已经丢失" in text
    assert "boardwise bridge update-connector --yes" in text
    assert "verified" not in text, "nothing was read back, so nothing was verified"


def test_no_reload_all_swaps_the_paragraph_and_names_the_reloaded_window(fake, capsys):
    """`--all` judges per window: one old build is enough to rewrite the summary.

    The windows of one editor share the storage record but not the running code,
    so `--all` can meet a 528A build in one window and an older one in the next.
    The reload half is decided by the build that executes each write — hence a
    per-window reading of `reloadInMs`, and a window named where it fired.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A", "inst-B")
    _FakeConnector.pre_528a_windows = {"inst-B"}

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), all=True, no_reload=True)
    )

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code == 0, text
    assert _FakeConnector.reload_flags == [False, False], "both frames ask for no reload"
    assert len(_FakeConnector.reloads) == 1, "only the old build schedules one"

    # The whole closing paragraph is the warning one — never the "nothing was
    # dispatched" summary with a footnote.
    assert "no reload was dispatched" not in text
    assert "written, NOT activated:" not in text
    # …and it names the window, because "some window reloaded" is not actionable.
    warning = _reload_warning_lines(text)
    assert len(warning) == 1, text
    assert "inst-B" in warning[0] and "inst-A" not in warning[0], (
        "only the window whose build reloaded may be named in the warning"
    )
    # The per-window line says which window is which, too. Both writes land in one
    # shared record, so inst-B's reply is the equal rewrite (0.5.18 -> 0.5.18) —
    # 坑 2's shape.
    assert f"inst-B: {_V()} -> {_V()}" in text and "仍然 reload 了" in text
    assert f"inst-A: 0.4.25 -> {_V()}" in text and "已写入未激活" in text
    assert "菜单" in text, "the activation route is still named"


def test_no_reload_all_against_an_all_pre_528a_table_names_every_window(pre_528a, capsys):
    """The both-old case: the paragraph swaps and both windows are listed."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(pre_528a / "b.js")
    _Pre528AConnector.windows = _windows("inst-A", "inst-B")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), all=True, no_reload=True)
    )

    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert code == 0, text
    assert len(_Pre528AConnector.reloads) == 2
    assert "no reload was dispatched" not in text
    assert "written, NOT activated:" not in text
    warning = _reload_warning_lines(text)
    assert len(warning) == 1, text
    assert "inst-A" in warning[0] and "inst-B" in warning[0]
    assert "boardwise bridge update-connector --yes" in text


def test_a_version_with_surrounding_whitespace_is_stripped_before_everything(
    fake, fast_clock, capsys
):
    """`--version " 0.5.18"` used to pass the gate and be written raw (528A-b).

    The gate compared ``version.strip()`` while the frame carried the *unstripped*
    string, so a label no bundle can ever announce landed in the record: a
    guaranteed FAILED read-back, and the uninstall-and-reinstall advice for a
    write that had worked. Windows makes it worse — ``--version "$VER"`` reads the
    version out of a file, `\\r` included.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.windows_after = _windows("inst-D", version=_V())

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=f"  {_V()}\r", yes=True)
    )

    captured = capsys.readouterr()
    assert code == 0, captured.err
    action, params = _self_update_calls()[0]
    assert params["version"] == _V(), (
        "the frame must carry the same token the gate compared, and the read-back too"
    )
    assert f"verified: running connector is now {_V()}" in captured.out
    assert "FAILED" not in captured.err and "卸载" not in captured.err


@pytest.mark.parametrize("blank", ["", " ", " \t\r\n"])
def test_a_blank_version_is_the_default_path_not_a_bad_request(fake, capsys, blank):
    """A blank `--version` is "not given" (528A-c).

    `--version "$VER"` with an empty VER is ordinary shell, and it used to reach
    the connector raw: `BAD_REQUEST`/exit 1 — neither the manifest default the
    code comment claimed nor the exit 2 the docs promise for bad input.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=blank, yes=True, no_reload=True)
    )

    captured = capsys.readouterr()
    assert code == 0, captured.err
    action, params = _self_update_calls()[0]
    assert params["version"] == _V(), "the default is the manifest's own version"
    assert "BAD_REQUEST" not in captured.err and "FAILED" not in captured.err
    assert "written, NOT activated" in captured.out


def test_the_version_gate_runs_before_the_daemon_is_opened(fake, capsys):
    """"Nothing was written" has to hold for the machine, not just the storage.

    `_open_cli` mints `~/.boardwise/token` and may start a daemon; a command that
    is going to be refused by the version gate reads only local files, so it must
    not get that far (528A-b note).
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=f"{_V()}-nope", yes=True)
    )

    captured = capsys.readouterr()
    assert code == 2
    assert _actions() == [], "nothing may be sent: not even the pre-write ping"
    assert "拒绝写入" in captured.err
    assert not (fake / "token").is_file(), (
        "_open_cli creates the token on first use; a refused command must stop before it"
    )


def test_a_disconnected_transport_is_not_reported_as_a_refusal(fake, capsys):
    """A dead socket is not "the editor refused it" (528A-b note).

    `client.call` normalises every transport death into `DISCONNECTED`, and the
    frame may well have reached the editor — so asserting "refused", or letting
    the reader re-run an update that already landed, is a claim nobody measured.
    The message has to say *unknown* and name the read that settles it.
    """
    from boardwise.bridge.protocol import ErrorCodes
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = _bundle(fake / "b.js")
    _FakeConnector.windows = _windows("inst-A")
    _FakeConnector.write_fails = {
        "inst-A": (
            ErrorCodes.DISCONNECTED,
            "the daemon connection closed while 'sys.self_update' was in flight "
            "(ConnectionClosedError); the action's outcome is unknown",
        )
    }

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version=_V(), no_reload=True)
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "不确定" in captured.err
    assert "update-connector failed" not in captured.err, (
        "the generic refusal line asserts the wrong thing ('failed' == refused)"
    )
    assert "written, NOT activated" not in captured.out
    assert "--no-reload" in captured.err and "bridge status" in captured.err


# ---------------------------------------------------------------------------
# 528A-b: which manifest the guard has to read
# ---------------------------------------------------------------------------


def test_the_guard_compares_the_version_the_bundle_actually_announces(tmp_path):
    """The gate's premise: `build.mjs` bakes the version from `package.json`.

    ``__BOARDWISE_VERSION__`` comes from `pkg.version` (`connector/build.mjs`);
    `extension.json` only supplies `__BOARDWISE_UUID__`. Reading the extension
    manifest here meant the gate refused the *only honest* label as soon as the
    two files drifted — and the default path wrote a label no bundle can report.
    """
    import json

    from boardwise.cli import _connector_manifest_version

    (tmp_path / "package.json").write_text(
        json.dumps({"name": "boardwise-connector", "version": "9.9.9"}), encoding="utf-8"
    )
    extension_json = tmp_path / "extension.json"
    extension_json.write_text(
        json.dumps({"uuid": "a0", "version": "1.1.1"}), encoding="utf-8"
    )

    assert _connector_manifest_version(extension_json) == "9.9.9", (
        "the announced version is package.json's, not extension.json's"
    )

    # The fallback: a frozen exe's --add-data list carries extension.json and not
    # package.json, and the guard must not deny every `--version` there.
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "extension.json").write_text(
        json.dumps({"uuid": "a0", "version": "2.2.2"}), encoding="utf-8"
    )
    assert _connector_manifest_version(frozen / "extension.json") == "2.2.2"


def test_the_two_manifests_agree_on_the_version():
    """`package.json` and `extension.json` must carry the same version.

    One is the string the bundle announces (baked by `build.mjs`, the one doctor
    and `update-connector` compare against); the other is the manifest the editor
    loads. Nothing in the repo checked they agree (020's audit, line 38), and a
    drift writes a record that can never verify — on the **default** path, with no
    `--version` involved. Bumping the version means editing both files.
    """
    import json

    from boardwise.cli import _connector_artifacts, _connector_version_source

    _, extension_json = _connector_artifacts()
    package_json = _connector_version_source(extension_json)
    in_package = json.loads(package_json.read_text(encoding="utf-8"))["version"]
    in_extension = json.loads(extension_json.read_text(encoding="utf-8"))["version"]

    assert in_package == in_extension, (
        f"connector/package.json 的 version 是 {in_package!r}，"
        f"connector/extension.json 的是 {in_extension!r} —— 改版本时两个文件都要改："
        "前者被 build.mjs 内联成 __BOARDWISE_VERSION__（connector 自报的版本），"
        "后者是编辑器加载的那份清单；drift 会让 update-connector 的默认路径写出一个"
        "永远验收不过的记录（必然 FAILED + 劝人卸载重装）"
    )
