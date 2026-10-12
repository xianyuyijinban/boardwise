"""157: a command that needs the bridge starts the daemon it cannot find.

The complaint this file pins: `boardwise bridge start` is a **foreground**
process, so the daemon dies with the terminal that ran it, and a user who never
started it — or who closed that window days ago — gets `daemon not reachable`
from every command that needs the bridge. The manual's repair ("double-click
`scripts\\start-daemon.bat`, keep the window open") is one more thing to remember
about a tool whose promise is one command.

So `_open_cli` — the single door every bridge command goes through — now starts
the daemon when nothing answers on the port, waits for it, and only then lets the
command continue into the error path it always had.

What is pinned here, and why each one is a way this feature could be worse than
the problem it fixes:

1. **one mount point** — `_open_cli` calls it, and it is the only caller in
   `cli.py`. A second copy would mean two behaviours to keep in step, which is
   exactly the drift the single door exists to prevent;
2. **start, then wait** — the port is polled until it answers or the budget runs
   out. Returning immediately after `Popen` would hand the command a daemon that
   is still importing;
3. **idempotent, races decided by waiting** — an answering port is never started
   over, and a start another process is already doing is waited for rather than
   duplicated (two daemons racing for one port is one dead process and one false
   failure report);
4. **honest failure** — a daemon that died at start-up is reported with its exit
   code and the tail of its log, because "it did not start", with no reason, is
   the state this feature exists to remove;
5. **optional** — `BOARDWISE_NO_AUTO_DAEMON=1` restores the old behaviour exactly,
   and it is the switch the rest of the suite runs with (`tests/conftest.py`), or
   a green suite would leave real daemons behind on the developer's machine.

The spawn is injected everywhere below: no test in this file starts a process or
opens a socket. The one exception is :func:`test_the_spawned_process_is_detached…`,
which launches a *short-lived `python -c`* to check the syscall-level shape of
`spawn_daemon` — never a daemon.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from boardwise.bridge import autostart
from boardwise.cli import DoctorProbe, run_doctor

REPO = Path(__file__).resolve().parent.parent
SKILL_MD = REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"

# --------------------------------------------------------------------------
# fakes: a port probe and a spawn, both recorded
# --------------------------------------------------------------------------


class _OpenAfter:
    """A port that answers only after N probes — i.e. after a spawn was made."""

    def __init__(self, after: int = 1):
        self.after = after
        self.calls = 0

    def __call__(self, port: int) -> bool:
        self.calls += 1
        return self.calls > self.after


class _NeverOpen:
    def __init__(self):
        self.calls = 0

    def __call__(self, port: int) -> bool:
        self.calls += 1
        return False


class _AlreadyOpen:
    def __init__(self):
        self.calls = 0

    def __call__(self, port: int) -> bool:
        self.calls += 1
        return True


class _OpenOnceSpawned:
    """A port that only answers after the spawn actually happened.

    The honest model of the real thing: the daemon's listen socket does not exist
    until the process that owns it does, so "the port opened" and "we spawned" are
    the same fact — and a test that let the port open without a spawn would prove
    the wrong half.
    """

    def __init__(self, spawn: "_Spawn"):
        self.spawn = spawn
        self.calls = 0

    def __call__(self, port: int) -> bool:
        self.calls += 1
        return bool(self.spawn.argv)


class _Process:
    """Enough of `Popen` for the failure branches: `poll()` is the exit code."""

    def __init__(self, code: int | None = None):
        self._code = code

    def poll(self):
        return self._code


class _Spawn:
    """A recorded stand-in for `spawn_daemon`."""

    def __init__(
        self,
        code: int | None = None,
        log_text: str = "",
        raises: OSError | None = None,
    ):
        self.code = code
        self.log_text = log_text
        self.raises = raises
        self.argv: list[list[str]] = []
        self.logs: list[Path] = []

    def __call__(self, argv: list[str], log: Path) -> _Process:
        self.argv.append(list(argv))
        self.logs.append(log)
        if self.raises is not None:
            raise self.raises
        if self.log_text:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(self.log_text, encoding="utf-8")
        return _Process(self.code)


# --------------------------------------------------------------------------
# fixtures: auto-start ON (the suite's conftest turns it off), a tmp home
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auto_start_on(monkeypatch, tmp_path):
    """Undo `tests/conftest.py`'s opt-out for this file, with a throwaway home."""
    monkeypatch.delenv(autostart.OPT_OUT_ENV, raising=False)
    # The default port comes from BOARDWISE_PORT when it is set, and a test that
    # asserted 61190 would then be measuring this shell instead of the code.
    monkeypatch.delenv("BOARDWISE_PORT", raising=False)
    monkeypatch.setattr("boardwise.bridge.daemon.BOARDWISE_HOME", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------
# 1. the orchestration
# --------------------------------------------------------------------------


def test_a_port_that_already_answers_is_never_started_over(tmp_path):
    """Somebody is listening: that is the daemon as far as this process can tell.

    Starting a second one would not get the port back (the new process dies on the
    bind) and would replace the command's real answer with a confusing failure.
    """
    spawn = _Spawn()
    outcome = autostart.ensure(
        61190, home=tmp_path, probe=_AlreadyOpen(), spawn=spawn, timeout=0.1
    )
    assert outcome.ok is True
    assert outcome.attempted is False and outcome.waited is False
    assert spawn.argv == [], "no process was started over the running daemon"


def test_a_closed_port_is_started_and_then_waited_for(tmp_path):
    """The whole feature in one call: nothing listening → spawn → wait → ok.

    The probe must be asked *after* the spawn, not just before it: a daemon that
    was started and not waited for is a daemon the command still cannot use.
    """
    probe = _OpenOnceSpawned(spawn := _Spawn())
    outcome = autostart.ensure(
        61190, home=tmp_path, probe=probe, spawn=spawn, timeout=1.0
    )
    assert outcome.ok is True
    assert outcome.attempted is True and outcome.waited is False
    assert probe.calls >= 2, "it asked the port again after the spawn instead of assuming"
    assert spawn.argv == [autostart.command(61190)]
    assert spawn.logs == [autostart.log_path(tmp_path)]
    # The stamp marks a start *in flight*: it must not survive a success, or the
    # next command would think a start is already running and only wait.
    assert not autostart.stamp_path(tmp_path).exists()


def test_a_start_another_process_is_doing_is_waited_for_not_duplicated(tmp_path):
    """The race, from the loser's seat.

    Two CLIs at once must not turn into two daemons competing for one port: the
    first binds, the second dies on the bind, and the CLI that spawned the second
    reports a failure that did not happen.
    """
    stamp = autostart.stamp_path(tmp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("4242 0\n", encoding="utf-8")  # a start in flight, not ours
    probe = _OpenAfter(after=2)
    spawn = _Spawn()

    outcome = autostart.ensure(61190, home=tmp_path, probe=probe, spawn=spawn, timeout=1.0)

    assert outcome.ok is True
    assert outcome.waited is True and outcome.attempted is False
    assert spawn.argv == [], "the second CLI started a second daemon"
    assert stamp.exists(), "the stamp belongs to the other process; it is not ours to clear"


def test_a_start_in_flight_that_never_arrives_is_reported_not_duplicated(tmp_path):
    """A fresh stamp plus no port is the other process's problem to explain.

    Waiting forever is not an option either, so this is where the timeout is
    spent: the outcome says another start is in progress, and this process still
    does not add a second one.
    """
    stamp = autostart.stamp_path(tmp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("4242 0\n", encoding="utf-8")
    spawn = _Spawn()

    outcome = autostart.ensure(
        61190, home=tmp_path, probe=_NeverOpen(), spawn=spawn, timeout=0.2
    )

    assert outcome.ok is False
    assert outcome.waited is True and outcome.attempted is False
    assert spawn.argv == []
    assert "另一个进程" in outcome.detail


def test_a_stale_stamp_is_taken_over(tmp_path):
    """An abandoned start must not park every later command for good.

    The stamp is a file, not a lock the kernel releases: a daemon killed between
    the claim and the bind leaves it behind. Age is what distinguishes "starting
    right now" from "was starting, is gone", and nothing else would ever start a
    daemon again on that machine.
    """
    stamp = autostart.stamp_path(tmp_path)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("4242 0\n", encoding="utf-8")
    old = time.time() - autostart.STALE_START_SECONDS - 5
    os.utime(stamp, (old, old))

    spawn = _Spawn()
    outcome = autostart.ensure(
        61190,
        home=tmp_path,
        probe=_OpenOnceSpawned(spawn),
        spawn=spawn,
        timeout=0.3,
    )

    assert outcome.ok is True and outcome.attempted is True
    assert spawn.argv == [autostart.command(61190)], "the stale start was taken over"


def test_a_daemon_that_dies_at_startup_is_reported_with_its_log(tmp_path):
    """「拉起失败要读日志尾部给出原因」 — the reason, not just the verdict.

    A port that never opened plus a process that already exited is a *different*
    fact from a slow machine, and the log is the only place the difference is
    written down.
    """
    spawn = _Spawn(code=1, log_text="Traceback (most recent call last):\nOSError: port in use\n")
    outcome = autostart.ensure(
        61190, home=tmp_path, probe=_NeverOpen(), spawn=spawn, timeout=0.2
    )

    assert outcome.ok is False
    assert outcome.attempted is True
    assert "退出码 1" in outcome.detail
    assert "OSError: port in use" in outcome.log_tail
    assert outcome.log == autostart.log_path(tmp_path)
    assert not autostart.stamp_path(tmp_path).exists(), "a failed start must not block the next one"


def test_a_process_that_stays_up_without_listening_says_exactly_that(tmp_path):
    """The other failure shape, and it is not the same sentence.

    A daemon that is alive but not listening is not "it crashed" — the reader's
    next move differs (look at the port, not at the traceback), so the detail
    distinguishes them.
    """
    outcome = autostart.ensure(
        61190,
        home=tmp_path,
        probe=_NeverOpen(),
        spawn=_Spawn(code=None, log_text="starting\n"),
        timeout=0.2,
    )
    assert outcome.ok is False
    assert "退出码" not in outcome.detail
    assert "没监听" in outcome.detail


def test_a_spawn_that_cannot_even_launch_is_reported_and_unblocks_the_next_one(tmp_path):
    """No interpreter, no executable, a permission error: an `OSError` here.

    It must not escape — the caller is on its way to its own error message — and
    it must not leave the stamp behind, or one unwritable log directory would
    stop the daemon from ever being started again.
    """
    outcome = autostart.ensure(
        61190,
        home=tmp_path,
        probe=_NeverOpen(),
        spawn=_Spawn(raises=OSError("WinError 5")),
        timeout=0.2,
    )
    assert outcome.ok is False and outcome.attempted is True
    assert "WinError 5" in outcome.detail
    assert not autostart.stamp_path(tmp_path).exists()


def test_the_opt_out_restores_the_old_behaviour_exactly(tmp_path, monkeypatch):
    """`BOARDWISE_NO_AUTO_DAEMON=1` — no probe, no spawn, no stamp, no message.

    The operator who manages the daemon themselves (a scheduled task, a service,
    `scripts\\start-daemon.bat`) must get the process they had before this task:
    the port is not even looked at, so this is blanket-neutral rather than merely
    "no spawn".
    """
    monkeypatch.setenv(autostart.OPT_OUT_ENV, "1")
    probe = _NeverOpen()
    spawn = _Spawn()

    outcome = autostart.ensure(61190, home=tmp_path, probe=probe, spawn=spawn, timeout=0.2)

    assert outcome.ok is False and outcome.attempted is False and outcome.waited is False
    assert probe.calls == 0 and spawn.argv == []
    assert not autostart.stamp_path(tmp_path).exists()
    assert autostart.OPT_OUT_ENV in outcome.detail


def test_the_command_is_the_same_door_in_both_install_shapes(monkeypatch):
    """Frozen exe vs checkout: one argv expression, two correct answers.

    `boardwise.exe` *is* the CLI (028), so the subcommand goes straight to it; from
    a checkout the interpreter carries `-m boardwise.cli`. The port is always
    explicit: the child would otherwise resolve it from `BOARDWISE_PORT`, which is
    not the port this process was told to use when the caller passed `--port`.
    """
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert autostart.command(61190) == [
        sys.executable, "-m", "boardwise.cli", "bridge", "--port", "61190", "start",
    ]

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\boardwise\boardwise.exe")
    assert autostart.command(62000) == [
        r"C:\boardwise\boardwise.exe", "bridge", "--port", "62000", "start",
    ]


def test_the_log_lives_beside_the_audit_directory_and_is_dated(tmp_path):
    """Where the failure message points has to be a path a reader can open."""
    path = autostart.log_path(tmp_path)
    assert path.parent == tmp_path / "log", "not inside audit/: that directory is JSONL records"
    assert path.name.startswith("daemon-") and path.suffix == ".log"
    assert time.strftime("%Y-%m-%d") in path.name


def test_spawn_daemon_asks_for_a_detached_child_with_a_redirected_console(tmp_path, monkeypatch):
    """The syscall-level shape: what `spawn_daemon` passes to `Popen`.

    Detached is the *point* — a daemon that dies with the CLI that started it
    solves nothing — and the redirected console is what makes the failure message
    above possible. `Popen` is recorded rather than launched, because the flags are
    part of the call and asking a real process what it was created with is a
    platform race this test does not need: `creationflags` is not even readable off
    a `Popen` on every Python version in this repo's range.
    """
    recorded: dict = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            recorded["argv"] = argv
            recorded.update(kwargs)
            self.argv = argv
            recorded["handle_open_at_call"] = not kwargs["stdout"].closed

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    log = tmp_path / "log" / "daemon-test.log"
    process = autostart.spawn_daemon(["boardwise", "bridge", "start"], log)

    assert process.argv == ["boardwise", "bridge", "start"]
    assert recorded["argv"] == ["boardwise", "bridge", "start"]
    assert recorded["stdin"] is subprocess.DEVNULL
    assert recorded["stderr"] is subprocess.STDOUT, "console output must land in one file"
    assert recorded["close_fds"] is True
    assert recorded["handle_open_at_call"] is True
    assert log.exists(), "the log file is created before the process is started"
    assert recorded["stdout"].closed, "the parent must not keep the descriptor past its own exit"
    if os.name == "nt":
        assert recorded["creationflags"] & 0x00000008, "DETACHED_PROCESS"
        assert recorded["creationflags"] & 0x00000200, "CREATE_NEW_PROCESS_GROUP"
    else:  # pragma: no cover - dev boxes only
        assert recorded["start_new_session"] is True


def test_the_spawned_process_really_writes_its_console_to_that_file(tmp_path):
    """The same call, actually run — with a two-line script, never a daemon.

    The reason the redirected console matters is that a *later* process reads that
    file to explain a failure, so the bytes really arriving is the property; a
    recorded `Popen` cannot show it.
    """
    log = tmp_path / "log" / "daemon-test.log"
    process = autostart.spawn_daemon(
        [sys.executable, "-c", "print('spawned-detached-marker'); raise SystemExit(3)"], log
    )
    assert process.wait(timeout=30) == 3

    text = log.read_text(encoding="utf-8", errors="replace")
    assert "spawned-detached-marker" in text
    assert autostart.log_tail(log) == "spawned-detached-marker"


# --------------------------------------------------------------------------
# 2. the mount point: one, and it is `_open_cli`
# --------------------------------------------------------------------------


def _bridge_args(*argv: str):
    from boardwise.cli import build_parser

    return build_parser().parse_args(list(argv))


@pytest.fixture
def recorded_ensure(monkeypatch):
    """Record what the CLI asks for, without a probe or a spawn."""
    calls: list[int] = []

    def fake(port: int, **kwargs):
        calls.append(port)
        return autostart.StartOutcome(ok=False, detail="fake")

    monkeypatch.setattr(autostart, "ensure", fake)
    return calls


def test_the_cli_starts_the_daemon_from_its_single_door(recorded_ensure):
    """`_open_cli` is the only place, so every bridge command gets it.

    Asserted through `_open_cli` itself rather than through one command: the point
    of the design is that commands do not each carry a copy, and a test on
    `bridge status` alone would not notice a second copy growing elsewhere.
    """
    from boardwise.cli import _open_cli

    _open_cli(_bridge_args("bridge", "status"))
    _open_cli(_bridge_args("bridge", "--port", "62001", "status"))
    assert recorded_ensure == [61190, 62001], "the port the command will dial, not a default"


def test_there_is_exactly_one_place_in_the_cli_that_starts_a_daemon():
    """The structural half: no second copy, anywhere in `cli.py`.

    The requirement is 「唯一挂载点」, and a grep is what makes it a property of the
    file rather than of the two functions someone happened to test.
    """
    source = (REPO / "src" / "boardwise" / "cli.py").read_text(encoding="utf-8")
    assert source.count("autostart.ensure(") == 1
    assert "def _ensure_daemon(" in source
    # …and the one caller is `_open_cli`: commands reach the bridge through it and
    # nowhere else.
    assert source.count("_ensure_daemon(") == 2  # the def and its one call site


def test_the_opt_out_stops_the_cli_before_it_looks_at_the_port(monkeypatch):
    """The switch at the CLI's own level: not a probe, not a spawn, no message."""
    from boardwise.cli import _open_cli

    monkeypatch.setenv(autostart.OPT_OUT_ENV, "1")
    probed: list[int] = []
    spawned: list[list[str]] = []
    monkeypatch.setattr(autostart, "port_open", lambda port, *a, **k: probed.append(port) or False)
    monkeypatch.setattr(autostart, "spawn_daemon", lambda argv, log: spawned.append(argv))

    _open_cli(_bridge_args("bridge", "status"))

    assert probed == [] and spawned == []


# --------------------------------------------------------------------------
# 3. what the user sees: the notice, and the failure
# --------------------------------------------------------------------------


class _Status:
    """A `BridgeClient` that answers whatever the test set as `ping`."""

    payload: dict = {"connector": False, "pairedFingerprint": None}

    @classmethod
    async def open(cls, uri, token, role, client=None):
        return cls()

    async def call(self, action, params=None):
        return type(self).payload

    async def close(self):
        return None


class _Refuses:
    @classmethod
    async def open(cls, uri, token, role, client=None):
        raise OSError("connection refused")


def _use_client(monkeypatch, client) -> None:
    import boardwise.bridge.client as client_module

    monkeypatch.setattr(client_module, "BridgeClient", client)


def test_an_auto_started_daemon_is_announced_before_the_command_s_answer(
    monkeypatch, capsys, tmp_path
):
    """Silent auto-start hides a process the user now owns — say it, on stderr.

    stderr and not stdout: the command's own answer (here, `bridge status`'s
    verdict line, first by design since issue #69) must not be pushed down by a
    diagnostic about this machine.
    """
    from boardwise.cli import _cmd_bridge_status

    log = tmp_path / "log" / "daemon-x.log"
    monkeypatch.setattr(
        autostart,
        "ensure",
        lambda port, **kw: autostart.StartOutcome(ok=True, attempted=True, log=log),
    )
    _use_client(monkeypatch, _Status)

    assert _cmd_bridge_status(_bridge_args("bridge", "status")) == 1

    captured = capsys.readouterr()
    assert "已自动拉起" in captured.err and str(log) in captured.err
    assert captured.out.splitlines()[0].startswith("未连接"), "the command's first line is intact"


def test_a_failed_auto_start_prints_the_reason_and_the_log_tail_then_the_old_error(
    monkeypatch, capsys, tmp_path
):
    """Failure is additive: a reason above, the existing message below.

    Nothing about the un-reachable path changes — the exit code, the sentence and
    the port it names are the ones that were pinned before (069b) — the auto-start
    only gets to explain itself first, which is the difference between "it did not
    start" and "here is why".
    """
    from boardwise.cli import _cmd_bridge_status

    log = tmp_path / "log" / "daemon-x.log"
    monkeypatch.setattr(
        autostart,
        "ensure",
        lambda port, **kw: autostart.StartOutcome(
            ok=False,
            attempted=True,
            log=log,
            detail="daemon 起来后 5s 内没有接受连接；进程已退出（退出码 1）",
            log_tail="OSError: port in use",
        ),
    )
    _use_client(monkeypatch, _Refuses)

    assert _cmd_bridge_status(_bridge_args("bridge", "status")) == 2

    captured = capsys.readouterr()
    assert "自动拉起 daemon 失败" in captured.err
    assert "退出码 1" in captured.err and str(log) in captured.err
    assert "OSError: port in use" in captured.err
    assert "daemon not reachable" in captured.out, "the pre-existing error is untouched"


def test_a_wait_for_someone_else_s_start_is_said_out_loud(monkeypatch, capsys):
    """Waiting silently looks like a hang; the wait has one sentence of its own."""
    from boardwise.cli import _cmd_bridge_status

    monkeypatch.setattr(
        autostart, "ensure", lambda port, **kw: autostart.StartOutcome(ok=True, waited=True)
    )
    _use_client(monkeypatch, _Status)

    assert _cmd_bridge_status(_bridge_args("bridge", "status")) == 1
    assert "另一个进程正在拉起 daemon" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 4. doctor: same path, and a line that tells the truth
# --------------------------------------------------------------------------


def test_doctor_goes_through_the_auto_start_like_every_other_command(
    monkeypatch, tmp_path, capsys
):
    """Requirement 5: doctor is not special-cased, it is a bridge command.

    Asserted by letting the real `_open_cli` run and recording only the auto-start:
    a doctor that skipped it would report "no daemon" on a machine where every
    other command had just started one.
    """
    from boardwise.cli import _cmd_doctor

    started: list[int] = []
    monkeypatch.setattr(
        autostart,
        "ensure",
        lambda port, **kw: started.append(port)
        or autostart.StartOutcome(ok=True, attempted=True, log=tmp_path / "log" / "d.log"),
    )
    monkeypatch.setenv("BOARDWISE_EDITOR_INSTALL", str(tmp_path / "no-editor"))
    _use_client(monkeypatch, _Refuses)

    _cmd_doctor(_bridge_args("doctor", "--port", "61234"))
    assert started == [61234]


def test_the_doctor_daemon_line_says_the_daemon_is_started_for_you():
    """The check's wording, from the pure runner.

    Red here now means "the auto-start did not work", not "you forgot to run a
    command" — so the label says the daemon is started on demand and the fix leads
    with the log to read. The command survives on the line as the foreground
    fallback, which is what it is now.
    """
    checks = run_doctor(DoctorProbe(port=61190, ping=None, ping_error="connection refused"))
    entry = next(c for c in checks if c.name == "daemon")

    assert entry.ok is False
    assert "不在会自动拉起" in entry.label
    assert str(autostart.log_path()) in entry.fix, "the fix names the log to read"
    assert "boardwise bridge start" in entry.fix, "the foreground fallback is still there"


# --------------------------------------------------------------------------
# 5. the documents, pinned the way the repo pins documents
# --------------------------------------------------------------------------


def test_the_documents_say_the_daemon_starts_itself_without_the_manual_step():
    """README / install manual / SOP, each naming the auto-start and the switch.

    The switch's *spelling* is read from the code rather than copied into this
    test, so renaming `autostart.OPT_OUT_ENV` cannot leave three documents telling
    users to set a variable nothing reads any more — the same discipline
    `tests/test_doc_claims.py` applies to the rest of the documentation.
    """
    switch = autostart.OPT_OUT_ENV
    for path in (REPO / "README.md", REPO / "docs" / "install.md", SKILL_MD):
        text = path.read_text(encoding="utf-8")
        assert switch in text, f"{path.name} does not name {switch}"
        assert "自动拉起" in text or "starts it" in text, (
            f"{path.name} does not say the daemon is started on demand"
        )
