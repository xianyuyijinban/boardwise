"""issue #69 条 2: connection status you can see without knowing the command.

The complaint: 「状态只在 bridge status 命令里，硬件工程师/AI 轻度用户不知道连没连上，
干等 AI 返回」. Two halves, and they are deliberately different in cost:

* **the cheap half (here)** — `bridge status` leads with one sentence that answers
  the only question a light user has (can boardwise see my project?), and the SOP
  makes 「AI 开工第一句报连接状态」 a rule rather than a habit;
* the expensive half — a daemon status indicator — is explicitly *not* here; it is
  the productisation phase the issue defers.

What is pinned:

1. `daemon.status_summary` is **pure** and total: one line for a connected
   installation naming the projects, one line for an unconnected one naming the two
   repair steps **in the order they have to be done**;
2. the CLI prints that line **first**, above the window table it did not change, and
   prints it on the daemon-unreachable path too — a reader who has just started the
   daemon and still sees no window must still have the second half of the
   instruction in front of them;
3. the exit codes are unchanged (2 unreachable / 1 no connector / 0 connected): the
   new line is information, not a new verdict, and a caller keying on the code must
   not see a behaviour change;
4. a window that named no project is **counted and not invented** — the same
   discipline the window table already follows, and the failure mode a "helpful"
   summary line introduces (naming a project the daemon never heard of).
"""

from __future__ import annotations

import pytest

from boardwise.bridge.daemon import status_summary

CONNECTED_TWO = {
    "connector": True,
    "pairedFingerprint": "deadbeef",
    "windows": [
        {"windowKey": "window-A", "instanceId": "window-A", "projectName": "/test",
         "projectUuid": "uuid-test"},
        {"windowKey": "window-B", "instanceId": "window-B", "projectName": "test2",
         "projectUuid": "uuid-test2"},
    ],
}


# --------------------------------------------------------------------------
# the sentence itself (pure)
# --------------------------------------------------------------------------


def test_a_connected_installation_is_one_sentence_naming_the_projects():
    line = status_summary(CONNECTED_TWO)
    assert line.startswith("已连接 2 个窗口：")
    assert "/test" in line and "test2" in line
    assert "\n" not in line, "it is a verdict line, not a table"
    # The names are the ones a human calls them — the uuid is what the window table
    # below already prints, and repeating it here would make the headline noisier
    # than the detail it is supposed to replace.
    assert "uuid-test" not in line


def test_two_windows_on_one_project_are_counted_as_two_and_named_once():
    """The count and the list answer different questions, and both must be right.

    A colleague with two windows on the same board should see 「已连接 2 个窗口」 —
    that is the number the daemon has — and one name in the list, because there is
    one project. Printing the name twice would read as two projects.
    """
    line = status_summary({"connector": True, "windows": [
        {"windowKey": "a", "projectName": "毕设板", "projectUuid": "u1"},
        {"windowKey": "b", "projectName": "毕设板", "projectUuid": "u1"},
    ]})
    assert "已连接 2 个窗口" in line
    assert line.count("毕设板") == 1


def test_a_window_that_named_no_project_is_counted_and_never_invented():
    """The failure mode a helpful headline introduces (finding 4 above).

    A window right after an editor restart reads no project at all. The sentence
    has to say so — an empty list would read as "no project open", and a borrowed
    name from another window would be a claim the daemon cannot support.
    """
    line = status_summary({"connector": True, "windows": [{"windowKey": "a"}]})
    assert "已连接 1 个窗口" in line
    assert "没有报工程名" in line
    assert "未报工程名" in line, "the count of unnamed windows is stated too"


def test_no_windows_is_the_two_step_repair_in_the_order_it_has_to_be_done():
    """The issue's own sentence, with the order it gives.

    Daemon first: an extension cannot be seen by a daemon that is not running, so
    telling the reader to re-import the `.eext` first would have them redo the step
    they already did.
    """
    for payload in (
        {"connector": False},
        {"connector": True, "windows": []},
        {},
    ):
        line = status_summary(payload)
        assert line.startswith("未连接")
        assert "boardwise bridge start" in line
        assert "connector" in line
        assert line.index("bridge start") < line.index("connector"), line


def test_a_malformed_windows_field_does_not_raise_or_invent():
    """Same defensive contract `_status_windows` gives the table (018 §A).

    A status command that raises on a field from another process is worse than one
    that shows what it could read — the reader gets the repair line either way,
    which is the thing they came for.
    """
    for payload in ({"windows": "not a list"}, {"windows": [None, 42]}, {"windows": []}):
        assert status_summary(payload).startswith("未连接")


# --------------------------------------------------------------------------
# the CLI wiring: the sentence comes first, the table is untouched
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
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    _StatusClient.opened = None
    _StatusClient.payload = dict(CONNECTED_TWO)
    monkeypatch.setattr(client_module, "BridgeClient", _StatusClient)
    return tmp_path


def _status_args():
    from boardwise.cli import build_parser

    return build_parser().parse_args(["bridge", "status"])


def test_the_verdict_line_is_the_first_thing_printed(status_env, capsys):
    """First, not last: the reader who does not know the command reads one line.

    Everything below it is the same detail block as before — this is an addition
    above, not a replacement of anything, so a reader debugging the bridge still
    finds the window table exactly where it was.
    """
    from boardwise.cli import _cmd_bridge_status

    assert _cmd_bridge_status(_status_args()) == 0

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0] == status_summary(CONNECTED_TWO)
    assert lines[0].startswith("已连接 2 个窗口")
    # The old lines are all still there, below it.
    assert "boardwise bridge: daemon up on 127.0.0.1:" in out
    assert "connector: connected" in out
    assert "windows: 2 connected" in out
    assert "window: window-A" in out
    assert "projects seen: /test (window-A), test2 (window-B)" in out
    assert "paired connector: deadbeef" in out


def test_the_verdict_line_sits_above_the_table_it_summarises(status_env, capsys):
    """Ordering is the feature: a summary printed under its own detail is decoration."""
    from boardwise.cli import _cmd_bridge_status

    _cmd_bridge_status(_status_args())
    out = capsys.readouterr().out
    assert out.index("已连接 2 个窗口") < out.index("windows: 2 connected")


def test_an_unconnected_daemon_still_prints_the_repair_before_its_reason(
    monkeypatch, tmp_path, capsys
):
    """The one path with no `ping` answer, and the one a new user hits first.

    `boardwise bridge status` on a machine where nothing has been started is the
    very first command of the install, and it used to print a socket error. The
    two steps that follow are the whole of 第 3 步 and 第 2 步 of the manual, so
    printing them here is the cheapest possible guidance — and printing them
    *before* the error keeps the error as the reason rather than the advice.
    """
    from boardwise.cli import _cmd_bridge_status

    class _Refuses:
        @classmethod
        async def open(cls, uri, token, role, client=None):
            raise OSError("connection refused")

    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path))
    import boardwise.bridge.client as client_module

    monkeypatch.setattr(client_module, "BridgeClient", _Refuses)

    assert _cmd_bridge_status(_status_args()) == 2

    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]
    assert lines[0].startswith("未连接")
    assert "boardwise bridge start" in lines[0]
    assert "daemon not reachable" in lines[1], "the reason stays, below the advice"


def test_the_exit_codes_are_unchanged_by_the_new_line(status_env, capsys):
    """2 / 1 / 0 exactly as before (finding 3 above).

    A caller keying on the exit code must not see a behaviour change from a change
    that only added a line of output. Asserted per state rather than once, because
    the states are what the codes mean.
    """
    from boardwise.cli import _cmd_bridge_status

    _StatusClient.payload = dict(CONNECTED_TWO)
    assert _cmd_bridge_status(_status_args()) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("已连接")

    _StatusClient.payload = {"connector": False, "pairedFingerprint": None}
    assert _cmd_bridge_status(_status_args()) == 1
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("未连接")
    # The detail line it had before is still what says "the daemon is up".
    assert "connector: not connected" in out


def test_a_fresh_daemon_prints_two_lines_and_no_table(status_env, capsys):
    """The 023 output-shape guarantee, one line longer.

    A daemon with nothing paired has exactly one thing to say — the verdict and the
    daemon's own liveness. No window table, no `projects seen`: those lines exist to
    enumerate windows, and there are none. Pinned because the summary line is new
    and a future change to "always print the projects list" would make an idle
    editor look like it has an unnamed project open.
    """
    from boardwise.cli import _cmd_bridge_status

    _StatusClient.payload = {"connector": False, "pairedFingerprint": None}

    assert _cmd_bridge_status(_status_args()) == 1

    out = capsys.readouterr().out
    assert "windows:" not in out
    assert "projects seen" not in out
    assert len([line for line in out.splitlines() if line.strip()]) == 4, out
