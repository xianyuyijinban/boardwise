"""165: `update-connector --all` must carry the dangerous-tier token, and a write
that the editor never re-evaluated must say what to do by hand.

Two field findings, both verified in the source before this batch:

1. `--all` sent its `sys.self_update` frames with the bare ``params`` while the
   single-window path added ``confirm: True``. The daemon's gate
   (``bridge/daemon.py::_gate_confirmation``) refuses anything else for a
   ``dangerous`` action, so `--all` was **unusable**: every window answered
   ``CONFIRMATION_REQUIRED`` and nothing was ever written. The fix is the token
   on every frame, and the fake below *enforces* the gate — so this file is red
   without the fix instead of merely asserting a dict key.

2. A write that lands ("ok: 0.4.25 -> 0.4.29") while the running connector keeps
   announcing 0.4.25 used to end with "unknown"/"mismatch" and no next step.
   The verification-failure paths now print what to do instead
   (``cli._write_without_activation_hint``).

Everything here is offline: a fake ``BridgeClient``, no daemon, no 61190.
"""

import argparse
import asyncio
import base64

import pytest


def _args(**over):
    base = dict(
        command="bridge",
        bridge_command="update-connector",
        bundle=None,
        version=None,
        yes=True,
        no_verify=False,
        port=None,
        instance=None,
        all=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _windows(*keys):
    return [
        {"windowKey": key, "instanceId": key, "connectorVersion": "0.4.25"} for key in keys
    ]


def _reloaded(*keys, version="0.4.29"):
    return [
        {"windowKey": key, "instanceId": key, "connectorVersion": version} for key in keys
    ]


class _GatedClient:
    """A fake that **implements the daemon's confirmation gate**.

    This is the point of the file: ``sys.self_update`` is ``dangerous``, so a
    frame without ``confirm is True`` raises ``CONFIRMATION_REQUIRED`` exactly
    as ``daemon.py::_gate_confirmation`` does — and the write never happens. A
    regression that drops the token from the `--all` path therefore shows up as
    a refusal per window, not as a passing test that reads a dict.
    """

    opened = None
    calls: list = []
    routes: list = []
    #: Every `sys.self_update` params dict that got **past** the gate, in order.
    forwarded: list = []
    #: Every refused frame, as `(window, confirm_value)`.
    refused: list = []
    #: The table **before** the write (the read-back's baseline) and, when set,
    #: the one from the write onwards — the shape that expresses "the reloaded
    #: page came back" (new instance ids) or "the old sockets linger".
    windows: list = []
    windows_after: list | None = None
    #: Set by the fake when a confirmed write has been forwarded.
    wrote: bool = False
    reload_in_ms: int = 500

    @classmethod
    async def open(cls, uri, token, role, client=None):
        cls.opened = (uri, token, role, client)
        return cls()

    async def call(self, action, params=None, **route):
        from boardwise.bridge.protocol import BridgeError, ErrorCodes

        type(self).calls.append((action, params))
        type(self).routes.append(route)
        if action == "ping":
            table = type(self).windows
            if type(self).wrote and type(self).windows_after is not None:
                table = type(self).windows_after
            return {"connector": True, "windows": [dict(w) for w in table]}
        # The gate, verbatim: identity check on `confirm`, params forwarded with
        # the token stripped.
        if (params or {}).get("confirm") is not True:
            window = route.get("target_instance") or ""
            type(self).refused.append((window, (params or {}).get("confirm")))
            raise BridgeError(
                ErrorCodes.CONFIRMATION_REQUIRED,
                "sys.self_update replaces running code or reloads the editor "
                f"(dangerous tier); re-send with confirm: true (got "
                f"{(params or {}).get('confirm')!r}). Nothing was forwarded to "
                "the editor.",
            )
        forwarded = {k: v for k, v in params.items() if k != "confirm"}
        type(self).forwarded.append(forwarded)
        type(self).wrote = True
        return {
            "ok": True,
            "oldVersion": "0.4.25",
            "newVersion": forwarded["version"],
            "bytes": len(base64.b64decode(forwarded["bundleB64"])),
            "database": "User_team-7_v6",
            "reloadInMs": type(self).reload_in_ms,
        }

    async def close(self):
        return None


@pytest.fixture
def gated(monkeypatch, tmp_path):
    import boardwise.bridge.client as client_module

    for name, value in (
        ("opened", None), ("calls", []), ("routes", []), ("forwarded", []),
        ("refused", []), ("windows", []), ("windows_after", None), ("wrote", False),
    ):
        setattr(_GatedClient, name, value)
    _GatedClient.reload_in_ms = 500
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    monkeypatch.setattr(client_module, "BridgeClient", _GatedClient)
    return tmp_path


@pytest.fixture
def fast_clock(monkeypatch):
    """Shrink the verification clock, like the other update-connector tests do."""
    import boardwise.cli as cli_module

    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_INTERVAL_S", 0.01)
    monkeypatch.setattr(cli_module, "UPDATE_VERIFY_BUDGET_S", 0.2)
    monkeypatch.setattr(cli_module, "UPDATE_RELOAD_MARGIN_S", 0.0)
    monkeypatch.setattr(_GatedClient, "reload_in_ms", 0)
    return cli_module


def _self_update_frames():
    return [params for action, params in _GatedClient.calls if action == "sys.self_update"]


# ---------------------------------------------------------------------------
# Problem 1: the `--all` path and the dangerous-tier token
# ---------------------------------------------------------------------------


def test_all_sends_confirm_on_every_frame(gated, fast_clock, capsys):
    """The bug itself: `--all` wrote nothing because no frame carried the token.

    Red before the fix — the gate refuses all three windows and the command
    exits 1 with three `CONFIRMATION_REQUIRED` writes.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A", "inst-B", "inst-C")
    _GatedClient.windows_after = _reloaded("inst-D", "inst-E", "inst-F")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True, all=True)
    )

    assert _GatedClient.refused == [], f"the gate refused: {_GatedClient.refused}"
    frames = _self_update_frames()
    assert len(frames) == 3, "one frame per online window"
    assert all(frame.get("confirm") is True for frame in frames), frames
    # …and the token reached the gate without riding along into the forwarded
    # params — the daemon strips it, so the fake strips it too.
    assert all("confirm" not in frame for frame in _GatedClient.forwarded)
    assert code == 0, capsys.readouterr().err


def test_all_routes_each_frame_to_its_own_window_with_the_token(gated, fast_clock):
    """`confirm` is added *next to* the routing, not instead of it."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A", "inst-B")

    _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True, all=True)
    )

    routes = [
        route
        for action, route in zip([a for a, _ in _GatedClient.calls], _GatedClient.routes)
        if action == "sys.self_update"
    ]
    assert routes == [{"target_instance": "inst-A"}, {"target_instance": "inst-B"}]


def test_all_consent_still_comes_from_the_caller(gated, monkeypatch, capsys):
    """The token is only added after the [y/N] gate — a "no" writes nothing.

    `--yes`/the prompt runs in `_cmd_bridge_update_connector` *before*
    `_update_all_windows`, so adding `confirm: True` inside the latter cannot
    invent consent: answering "n" must still leave the wire silent.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A", "inst-B")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=False, all=True)
    )

    assert code == 2
    assert _self_update_frames() == [], "declining must not send a confirmed frame"
    assert "aborted" in capsys.readouterr().out


def test_the_single_window_path_and_all_agree_on_the_token(gated, fast_clock):
    """Both paths drive the same action, so both must carry the same consent."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")

    _GatedClient.windows = _windows("inst-A")
    _cmd_bridge_update_connector(_args(bundle=str(bundle), version="0.4.29", yes=True))
    single = _self_update_frames()[-1]

    _GatedClient.calls = []
    _GatedClient.windows = _windows("inst-A")
    _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True, all=True)
    )
    every = _self_update_frames()[-1]

    assert single["confirm"] is True and every["confirm"] is True


# ---------------------------------------------------------------------------
# Problem 2: the guidance for "written, never re-evaluated"
# ---------------------------------------------------------------------------


def test_mismatch_points_at_the_manual_reinstall(gated, fast_clock, capsys):
    """The field shape: the write stored 0.4.29, the connector answers 0.4.25.

    A reload that comes back announcing the *old* build is exit 1 — and the
    reader now gets the next step instead of a dead end.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A")
    _GatedClient.windows_after = _reloaded("inst-D", version="0.4.25")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True)
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "0.4.25" in err and "0.4.29" in err
    assert "没有重新评估" in err, "the guidance says why the write did not take"
    assert "卸载" in err and "重新导入 .eext" in err and "重启编辑器" in err
    assert "写入成功" in err and "新代码在跑" in err
    assert "bridge status" in err, "how to confirm afterwards"


def test_all_mismatch_points_at_the_manual_reinstall(gated, fast_clock, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A")
    _GatedClient.windows_after = _reloaded("inst-D", version="0.4.25")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True, all=True)
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "没有重新评估" in err and "重新导入 .eext" in err


def test_unknown_offers_the_guidance_as_the_likely_explanation(gated, fast_clock, capsys):
    """Exit 3 is still "unknown", so the guidance is offered conditionally.

    Nothing conclusive came back (the editor may simply still be reloading), so
    the sentence is led in with "复核下来若…" — the run is not called failed.
    """
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A")  # never leaves the table: no verdict

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True)
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "not failed" in err
    assert "复核下来若运行版本仍是旧的" in err
    assert "重新导入 .eext" in err


def test_all_unknown_offers_the_guidance_too(gated, fast_clock, capsys):
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True, all=True)
    )

    err = capsys.readouterr().err
    assert code == 3
    assert "复核下来若运行版本仍是旧的" in err and "重新导入 .eext" in err


def test_a_verified_run_prints_no_reinstall_guidance(gated, fast_clock, capsys):
    """The hint is for failures only — a green run must not tell anyone to reinstall."""
    from boardwise.cli import _cmd_bridge_update_connector

    bundle = gated / "b.js"
    bundle.write_bytes(b"x")
    _GatedClient.windows = _windows("inst-A")
    _GatedClient.windows_after = _reloaded("inst-D", version="0.4.29")

    code = _cmd_bridge_update_connector(
        _args(bundle=str(bundle), version="0.4.29", yes=True)
    )

    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "verified: running connector is now 0.4.29" in captured.out
    assert "重新导入" not in captured.out and "重新导入" not in captured.err


def test_no_bridge_action_can_uninstall_or_reimport_an_extension():
    """The feasibility answer, pinned: there is nothing to automate this with.

    Checked against the action table itself rather than prose, so a future action
    that *does* close the gap makes this test fail and forces the guidance to be
    revisited.
    """
    from boardwise.bridge.protocol import ACTIONS

    names = {action.name for action in ACTIONS}
    for needle in ("uninstall", "install", "reimport", "re_import", "restart", "reload"):
        assert not [name for name in names if needle in name], sorted(names)


def test_the_hint_names_the_write_not_running_distinction():
    """The wording itself, without a socket — the claim the guidance must make."""
    from boardwise.cli import _STILL_OLD_LEAD, _write_without_activation_hint

    plain = _write_without_activation_hint()
    assert plain.startswith("  ")
    assert "卸载" in plain and ".eext" in plain and "重启编辑器" in plain
    led = _write_without_activation_hint(lead=_STILL_OLD_LEAD)
    assert led.startswith(_STILL_OLD_LEAD)
    assert led.endswith(plain[2:])
