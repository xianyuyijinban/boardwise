"""Start the daemon on demand, so a bridge command works on a fresh machine.

``boardwise bridge start`` is a *foreground* process: the daemon it runs dies with
the terminal that ran it, and nothing else on the machine brings it back. A user
who never started it — or who closed that window days ago — gets ``daemon not
reachable`` from every command that needs the bridge, with nothing telling them
that one command would have fixed it. The manual's answer ("double-click
`scripts\\start-daemon.bat` and keep the window open") is a second thing to
remember about a tool whose promise is one command.

So the CLI starts it. :func:`boardwise.cli._open_cli` is the single place every
bridge command goes through, and it calls :func:`ensure` before handing back the
port; the daemon is spawned **detached** — its own process group, its console
output redirected into a log file under the boardwise home — because the whole
point is that it outlives the command that started it.

Three properties the rest of this module is written around:

* **idempotent, and races resolved by waiting.** A port that already answers is
  never started over (whoever is behind it is the daemon as far as this process
  can tell), and a start that *another* process is already doing is waited for
  rather than duplicated: two daemons racing for one port means one of them loses
  the bind and dies, and the CLI that spawned it then reports a failure that did
  not happen. The start in flight is stamped by a file; a stamp older than
  :data:`STALE_START_SECONDS` is treated as abandoned and taken over, so a kernel
  that killed a starting daemon cannot park every later command.
* **honest when it fails.** "It did not start" with no reason is the state this
  feature exists to remove, so a daemon that died at startup is reported with its
  exit code and the tail of its own log.
* **optional.** :data:`OPT_OUT_ENV` restores the previous behaviour exactly.

Nothing here needs ``websockets``: the reachability probe is a plain TCP connect,
so this module is importable (and testable) on a machine where the bridge extras
are not installed. It is loaded through the CLI's ``_bridge_modules()`` seam
anyway, which is where that guard already lives.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from . import daemon as _daemon

#: Set to a truthy value ("1") to stop the CLI starting the daemon by itself.
#: The old behaviour, on purpose: an operator who manages the daemon by hand
#: (systemd, a scheduled task, `scripts\\start-daemon.bat`) must be able to say so.
OPT_OUT_ENV = "BOARDWISE_NO_AUTO_DAEMON"

#: How long a spawned daemon gets to accept a connection before this process
#: gives up and lets the command report the failure it already knows how to
#: report. Python start-up plus the bind is ~0.3 s from a warm checkout and
#: ~1 s from the frozen exe; 5 s is the "a slow machine, not a broken one" budget.
READY_TIMEOUT = 5.0

#: Poll interval while waiting for the port, and the per-attempt connect budget.
POLL_INTERVAL = 0.1
PROBE_TIMEOUT = 0.5

#: A start stamp older than this belongs to a process that is gone (killed, or
#: crashed between the claim and the spawn). Taking it over is what keeps one
#: dead start from parking every later command for good.
STALE_START_SECONDS = 30.0

#: Lines of the spawned daemon's log quoted back when it did not come up. Enough
#: for a traceback's last frames, not so many that the CLI's real error scrolls
#: off the screen.
LOG_TAIL_LINES = 12

#: Name of the start-in-flight stamp, and of the log directory, both under the
#: boardwise home. The log lives beside the audit directory rather than inside
#: it: `audit/` is a directory of JSONL records other things read by date, and a
#: raw console log in there would be the one file in it that is not one of those.
START_STAMP_NAME = "daemon-autostart.stamp"
LOG_DIR_NAME = "log"

# Windows: the child gets no console at all (DETACHED_PROCESS) and its own
# process group, so a Ctrl-C or a closed terminal in the parent cannot reach it.
_DETACHED_PROCESS = 0x00000008
_CREATE_NEW_PROCESS_GROUP = 0x00000200


class Spawn(Protocol):
    """The injectable process launcher: ``(argv, log_path) -> Popen``."""

    def __call__(self, argv: list[str], log: Path) -> subprocess.Popen: ...


#: A port probe: ``port -> already answering?``. Injectable so the tests never
#: open a socket, and so the orchestration can be pinned without a daemon.
Probe = Callable[[int], bool]


@dataclass(frozen=True)
class StartOutcome:
    """What :func:`ensure` did, in the words the CLI prints.

    ``ok`` is about the port, not about who started it: a start another process
    was already doing ends here with ``ok`` and ``waited`` — the command that
    wanted the daemon has one either way, and that is the only thing it asked.
    """

    ok: bool
    #: This process spawned a daemon.
    attempted: bool = False
    #: Someone else was already starting one and we waited for it.
    waited: bool = False
    log: Path | None = None
    #: Why it is not ok, in one sentence, for the operator reading stderr.
    detail: str = ""
    #: Tail of the spawned daemon's log, only when it failed to come up.
    log_tail: str = ""


# --------------------------------------------------------------------------
# paths, argv, opt-out
# --------------------------------------------------------------------------


def opted_out() -> bool:
    """Is the auto-start turned off for this process?

    Read from the environment on every call rather than cached at import: the
    value is a property of the invocation, and a module-level copy would make
    ``BOARDWISE_NO_AUTO_DAEMON=1 boardwise bridge status`` depend on import order.
    """
    value = os.environ.get(OPT_OUT_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def log_dir(home: Path | None = None) -> Path:
    return (home or _daemon.BOARDWISE_HOME) / LOG_DIR_NAME


def log_path(home: Path | None = None) -> Path:
    """Where a spawned daemon's console output goes, one file per day.

    Dated because the daemon does not rotate anything: a daemon started weeks ago
    and one started a minute ago write to different files, and the one the CLI
    quotes on failure is the one that just failed.
    """
    return log_dir(home) / f"daemon-{time.strftime('%Y-%m-%d')}.log"


def command(port: int) -> list[str]:
    """The argv that runs the daemon in the background, in both install shapes.

    Frozen (``boardwise.exe``, 028 batch 3a) the executable *is* the CLI, so the
    subcommand is handed to it directly; from a checkout or a pip install it is
    the interpreter that has to carry ``-m boardwise.cli``. Same door either way
    (``packaging/entry.py`` calls ``boardwise.cli:main``), which is what makes one
    expression enough.

    The port is always spelled out. The child would otherwise resolve it from
    ``BOARDWISE_PORT``, and that is not the port this process was told to use when
    the caller passed ``--port`` — the daemon would come up exactly where nothing
    is looking for it.
    """
    head = [sys.executable]
    if not getattr(sys, "frozen", False):
        head += ["-m", "boardwise.cli"]
    return head + ["bridge", "--port", str(port), "start"]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = PROBE_TIMEOUT) -> bool:
    """Is *anything* accepting connections on this port?

    A TCP connect, not a WebSocket handshake: the question the auto-start has to
    answer is "is a start needed", and the handshake is already the job of every
    command's own error handling. A port held by some *other* program therefore
    reads as "do not start one" — which is right, because starting a second
    daemon would not get the port back, it would only add a process that dies on
    the bind and a second, more confusing error.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def spawn_daemon(argv: list[str], log: Path) -> subprocess.Popen:
    """Start ``argv`` detached, with its console output appended to ``log``.

    ``close_fds`` and ``DEVNULL`` for stdin on purpose: a daemon that inherits the
    calling shell's stdin can hold a pipe open after the CLI exits, and the
    console output has to land somewhere a *later* process can read it — that file
    is what turns "it did not start" into a reason.
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = log.open("ab")
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    else:  # pragma: no cover - the shipped build is Windows; kept for a dev box on POSIX
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            close_fds=True,
            **kwargs,
        )
    finally:
        # The child holds its own copy of the descriptor; the parent must not keep
        # this one open past its own exit.
        handle.close()


def log_tail(path: Path | None, lines: int = LOG_TAIL_LINES) -> str:
    """The last meaningful lines of the failed daemon's log, or ``""``."""
    if path is None:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = [line for line in text.splitlines() if line.strip()]
    return "\n".join(tail[-lines:])


# --------------------------------------------------------------------------
# the start-in-flight stamp
# --------------------------------------------------------------------------


def stamp_path(home: Path | None = None) -> Path:
    return (home or _daemon.BOARDWISE_HOME) / START_STAMP_NAME


def _claim(stamp: Path) -> bool:
    """Create the stamp exclusively. ``False`` means somebody else owns the start.

    ``O_EXCL`` is the lock: two CLIs starting at the same instant cannot both win,
    and the loser waits instead of spawning a second daemon.
    """
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        handle = os.open(stamp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return False
    try:
        os.write(handle, f"{os.getpid()} {time.time()}\n".encode("utf-8"))
    except OSError:
        pass
    finally:
        os.close(handle)
    return True


def _release(stamp: Path) -> None:
    try:
        stamp.unlink()
    except OSError:
        pass


def _stale(stamp: Path, seconds: float = STALE_START_SECONDS) -> bool:
    """Has the start that owns this stamp been abandoned?

    A stamp that is simply *gone* counts as abandoned: the process that held it
    finished (its daemon either came up — then the port probe would have stopped
    us — or it failed), so there is nothing left to wait for.
    """
    try:
        return (time.time() - stamp.stat().st_mtime) > seconds
    except OSError:
        return True


def _wait_for(
    probe: Probe, port: int, timeout: float, interval: float = POLL_INTERVAL
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        if probe(port):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


# --------------------------------------------------------------------------
# the orchestration
# --------------------------------------------------------------------------


def ensure(
    port: int,
    *,
    home: Path | None = None,
    probe: Probe | None = None,
    spawn: Spawn | None = None,
    timeout: float = READY_TIMEOUT,
) -> StartOutcome:
    """Make sure something is listening on ``port``, starting a daemon if not.

    Returns after the port answers, or after it is clear that it will not within
    ``timeout``. Never raises: the caller is on the way to an error message it
    already has, and a failure to *start* something is not a reason to replace
    that message with a traceback.
    """
    if opted_out():
        return StartOutcome(
            ok=False, detail=f"{OPT_OUT_ENV} 已设置：按旧行为不自动拉起"
        )

    probe = probe or port_open
    spawn = spawn or spawn_daemon

    if probe(port):
        return StartOutcome(ok=True)

    log = log_path(home)
    stamp = stamp_path(home)

    if not _claim(stamp):
        # Somebody else is starting one. Wait for theirs; do not add a second.
        if _wait_for(probe, port, timeout):
            return StartOutcome(ok=True, waited=True)
        if not _stale(stamp):
            return StartOutcome(
                ok=False,
                waited=True,
                log=log,
                detail=(
                    f"另一个进程正在拉起 daemon（启动戳 {stamp}），"
                    f"等了 {timeout:g}s 端口仍不可连"
                ),
            )
        # That start is gone without a daemon to show for it: take the stamp over
        # and do it here, otherwise nothing ever starts one again.
        _release(stamp)
        if not _claim(stamp):
            return StartOutcome(
                ok=False,
                waited=True,
                log=log,
                detail=f"另一个进程正在拉起 daemon（启动戳 {stamp}），等了 {timeout:g}s 端口仍不可连",
            )

    try:
        try:
            process = spawn(command(port), log)
        except OSError as exc:
            return StartOutcome(
                ok=False,
                attempted=True,
                log=log,
                detail=f"daemon 进程没能启动：{exc}",
            )
        if _wait_for(probe, port, timeout):
            return StartOutcome(ok=True, attempted=True, log=log)
        code = process.poll()
        detail = f"daemon 起来后 {timeout:g}s 内没有接受连接"
        detail += (
            f"；进程已退出（退出码 {code}）" if code is not None else "；进程还在，但没监听这个端口"
        )
        return StartOutcome(
            ok=False, attempted=True, log=log, detail=detail, log_tail=log_tail(log)
        )
    finally:
        # Released on every path out of here, success included: the stamp marks a
        # start *in flight*, not a daemon that is up. Only the stamp this call
        # claimed is ever released — a wait that never owned it returns above.
        _release(stamp)
