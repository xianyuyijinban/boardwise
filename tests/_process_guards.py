"""Process/CPU guards for **any** pytest run in this repository (193 §A).

Written after three subagents ran 4 xdist workers each plus probe/mutation
re-runs and flattened the machine: the doctrine said "parallel only `-n 4`",
and a rule in a document is a reminder, not a gate. These are gates — they sit
on the code path every pytest invocation already takes, so a caller who never
read the doctrine still gets stopped.

Four mechanisms, all **fail-open** (a guard that breaks the suite is worse than
the load it prevents):

1. **Lowered priority** — Windows ``BELOW_NORMAL_PRIORITY_CLASS``, POSIX
   ``os.nice(10)``. The controller lowers its own class, and xdist workers are
   its children, so they inherit it.
2. **Machine-wide concurrency slots = 2** — only *whole-suite* runs take one
   (a run narrowed to a file, a node id or ``-k`` is cheap and must not queue
   behind the two full runs). ``msvcrt.locking`` on two byte ranges of one slot
   file (``fcntl.lockf`` on POSIX — ``flock`` locks whole files and cannot
   address a byte range, so the record-locking call is the one that keeps the
   two-slot shape). A run that cannot get a slot **waits** and says so; the
   lock dies with the process, so a killed run never wedges the next one.
3. **Worker cap = 4** — ``-n auto`` / ``-n logical`` / ``-n >4`` is refused
   with a usage error. ``-n 0`` (serial) and ``-n 4`` pass. ``--maxprocesses=4``
   next to ``-n auto`` is fine: the cap is what matters, not the spelling.
4. **Thread-pool caps** — ``OMP/MKL/OPENBLAS/NUMEXPR_NUM_THREADS=1``, set with
   ``setdefault`` so an explicit setting of the caller's wins. This is the
   layer under xdist: one worker process can still fan out to every core
   through a BLAS thread pool.

``BOARDWISE_NO_TEST_GUARDS=1`` turns all four off — and "all four" is the whole
list: with the switch on, nothing is lowered and nothing is capped either (S3#7;
the priority drop and the thread caps used to run *before* the switch was read,
so a run that had asked for no guards still got two of them — the docstring said
"all four" while the code said "two of four"). A deliberate measurement run, and
CI, want the machine left as they found it.

**Where it is wired in, and why the hook alone is not enough.** 193's task book
asks for a ``pytest_load_initial_conftests`` hook in ``tests/conftest.py``.
Measured on pytest 9.1.1: that hook does **not** fire for an implementation
defined in a conftest file — pluggy hands out the hook implementations as a
snapshot, and the conftest that would define it is loaded *by* that very hook
call (``PytestPluginManager.pytest_load_initial_conftests``). A guard living
only there would be decoration. So ``tests/conftest.py`` wires the same
function to **both**:

* ``pytest_load_initial_conftests`` — the hook the task book names, kept for
  the ``-p``-loaded-plugin case and for a future pytest that changes the
  ordering;
* ``pytest_configure`` — the hook that *does* fire on every run, before
  ``pytest_sessionstart`` (where xdist spawns its workers), which is
  early enough for the slot to be held for the whole suite. It also runs
  inside ``wrap_session``, so ``pytest.exit`` from it exits cleanly with a
  usage-error code instead of a traceback.

``apply_guards`` is idempotent, so whichever fires first does the work and the
second is a no-op.

**Workers.** A slot is per *run*, not per process: the xdist workers must not
each queue for one. A worker is recognised by ``PYTEST_XDIST_WORKER`` (set
before the worker's own config is built) and by :data:`CHILD_ENV`, which the
slot holder sets in its environment — workers inherit it, so even a pytest that
does not announce itself the xdist way is covered.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

#: Turn every guard off: ``BOARDWISE_NO_TEST_GUARDS=1``.
GATE_OFF_ENV = "BOARDWISE_NO_TEST_GUARDS"

#: "Do not queue for a slot": set by a slot holder for its children (the xdist
#: workers inherit it), and available to anything else that is a child of a run
#: already holding one. A subprocess that *should* take a slot must clear it
#: (and ``PYTEST_XDIST_WORKER*``) from its environment.
CHILD_ENV = "BOARDWISE_TEST_GUARD_CHILD"

#: How many whole-suite pytest runs may be in flight machine-wide.
SLOT_COUNT = 2

#: The most workers a single run may ask for.
MAX_WORKERS = 4

_THREAD_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

#: Options that narrow what runs, so the run is **not** a whole-suite run and
#: does not take a slot. Only two families qualify (S3#5): a **keyword filter**
#: (``-k``) and *being named* — a file or a node id is matched by the positional
#: branch of :func:`narrowing_argv`. This is what
#: ``docs/testing-doctrine.md`` has said all along ("带文件名/节点/`-k` 的范围运行
#: 不占槽"); the code had a longer list.
#:
#: ``-m`` / ``--markexpr``, ``--lf`` / ``--last-failed``, ``--ff`` /
#: ``--failed-first``, ``--deselect`` and ``--ignore`` are **not** here, and that
#: is deliberate: they are *subtractive* — they drop what does not match, what
#: failed last time, or one path — so such a run still walks the whole suite
#: minus a little and is a hog like any other. ``--collect-only`` is not here
#: either: it runs no test, but the slots measure a run's **shape**, and a run
#: shaped like the whole suite takes a slot (use ``BOARDWISE_NO_TEST_GUARDS=1``
#: for a deliberate measurement).
_NARROW_FLAGS = frozenset(
    {
        "-k",
        "--keyword",
    }
)

#: Options whose **value** is the next argument: it must be skipped rather than
#: read as a positional (``-c pytest.ini`` is not "run one file"). This is what
#: keeps the subtractive options from leaking their argument into the positional
#: branch: ``--ignore tests/slow.py`` must not read as "a file was named", or the
#: very run S3#5 sends to the slots would slip past them through its own filter.
_VALUE_OPTIONS = frozenset(
    {
        "-c",
        "--config-file",
        "--rootdir",
        "--basetemp",
        "-p",
        "--dist",
        "--tx",
        "--maxprocesses",
        "--override-ini",
        "-o",
        "--confcutdir",
        "--junitxml",
        "--log-file",
        "--result-log",
        "--import-mode",
        "-m",
        "--markexpr",
        "--deselect",
        "--ignore",
        "--ignore-glob",
    }
)

_applied = False
_slot_handle = None  # kept alive for the process's lifetime: the lock is the handle


def guards_disabled() -> bool:
    """``BOARDWISE_NO_TEST_GUARDS=1`` — every guard is off."""
    return os.environ.get(GATE_OFF_ENV, "").strip() == "1"


def in_child() -> bool:
    """Whether this process is a **worker of a run that already has a slot**."""
    if os.environ.get("PYTEST_XDIST_WORKER"):
        return True
    return os.environ.get(CHILD_ENV, "").strip() == "1"


def _apply_thread_caps() -> None:
    """Pin the common thread pools to one thread, unless the caller said otherwise."""
    for name in _THREAD_VARS:
        os.environ.setdefault(name, "1")


def _lower_priority() -> None:
    """Drop this process (and the workers it spawns) to below-normal priority.

    ``argtypes``/``restype`` are set explicitly and the return value is checked:
    with ctypes' defaults the pseudo-handle ``GetCurrentProcess()`` arrives as a
    truncated 32-bit int, ``SetPriorityClass`` fails with 0, and a guard that
    ignores the result is a guard that does nothing (measured — the class read
    back as 0 before this was fixed).
    """
    try:
        if os.name == "nt":
            import ctypes

            below_normal = 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            kernel32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
            kernel32.SetPriorityClass.restype = ctypes.c_int
            if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), below_normal):
                raise OSError(ctypes.get_last_error(), "SetPriorityClass failed")
        else:
            os.nice(10)
    except Exception as exc:  # fail-open: priority is a courtesy, not a gate
        print(f"pytest 进程闸：降优先级失败（{exc}），继续", flush=True)


def numprocesses(argv: list[str]) -> "int | str | None":
    """The raw ``-n`` value named on a command line, or ``None``.

    ``int`` for anything ``int(value, 10)`` accepts, the string itself for
    ``auto``/``logical``/garbage, so the caller can tell "4" from "auto" without
    re-parsing. ``-n4``, ``-n=4`` and ``--numprocesses=4`` are all read;
    ``--noconftest`` is not (a glued short option is ``-n`` followed by its
    value, a long option never is).

    S3#4: the digits-only test (``value.isdigit()``) let ``-n +8`` and
    ``--numprocesses=+8`` through as "not a number, not our business", while
    xdist parsed exactly those to 8 workers (measured:
    ``xdist.plugin.parse_numprocesses("+8") == 8``, likewise ``" 8 "`` and
    ``"08"``). Whatever xdist accepts as a number, this must accept as the same
    number — the guard reads the value the same way xdist does, ``int(value,
    10)``, and only a value **that is not an integer** falls through to xdist's
    own usage error.
    """
    for index, arg in enumerate(argv):
        if arg in ("-n", "--numprocesses"):
            value = argv[index + 1] if index + 1 < len(argv) else None
        elif arg.startswith("--numprocesses=") or arg.startswith("-n="):
            value = arg.split("=", 1)[1]
        elif arg.startswith("-n") and not arg.startswith("--") and arg[2:].strip():
            value = arg[2:]
        else:
            continue
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        try:
            return int(value, 10)
        except ValueError:
            return value
    return None


def worker_violation(value: "int | str | None", maxprocesses: "int | None") -> str | None:
    """The message refusing a worker count, or ``None`` when it is acceptable.

    ``--maxprocesses=N`` (xdist's own cap on ``auto``) is honoured: ``-n auto
    --maxprocesses=4`` cannot exceed four and is allowed through.
    """
    if value is None:
        return None
    if isinstance(value, int):
        if value <= MAX_WORKERS:
            return None
        count = value
    elif value in ("auto", "logical"):
        if maxprocesses is not None and maxprocesses <= MAX_WORKERS:
            return None
        count = value
    else:
        return None  # xdist's own usage error; not this guard's business
    return (
        f"pytest 进程闸：拒绝 -n {count} —— 单次运行最多 {MAX_WORKERS} 个 worker"
        "（AGENTS.md：并行只许 `-n 4 --dist loadfile`）。\n"
        f"  改用 `-n 4`，或用 `{GATE_OFF_ENV}=1` 显式关掉进程闸。"
    )


def narrowing_argv(argv: list[str]) -> list[str]:
    """The arguments that make a run a **subset** run rather than a whole suite.

    Two things count (S3#5): a keyword filter, and a **name** — a file, a node id
    or a path that exists on disk. A directory is skipped on purpose: `pytest
    tests/` is the full run in this repository and must take a slot. Options
    whose argument is not a positional are consumed by :data:`_VALUE_OPTIONS`,
    which is what keeps `--ignore tests/slow.py` from reading as "a file was
    named".
    """
    found: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        index += 1
        if arg == "--":
            continue
        if arg in _VALUE_OPTIONS:
            index += 1  # its value is not a positional
            continue
        if arg in _NARROW_FLAGS:
            found.append(arg)
            continue
        if arg.startswith("--"):
            if arg.split("=", 1)[0] in _NARROW_FLAGS:
                found.append(arg)
            continue
        if arg.startswith("-"):
            # A short-option cluster: `-k PATTERN` was handled above, `-kPATTERN`
            # is the same filter glued, and `-q`/`-x`/`-s` are not filters.
            if arg.startswith("-k"):
                found.append(arg)
            continue
        # A positional: a node id, a file, or an existing file. A **directory**
        # is the whole suite (`pytest tests/` is the full run in this repo).
        if "::" in arg or arg.endswith(".py") or Path(arg).is_file():
            found.append(arg)
    return found


def slot_file() -> Path:
    """The slot file: ``$BOARDWISE_HOME/pytest-slots`` or ``~/.boardwise/pytest-slots``.

    A user-level path, not one inside the checkout: the two slots are
    machine-wide, and two checkouts (or two branches) on this machine must
    share them. Exposed for tests and for anyone who wants to look.
    """
    home = os.environ.get("BOARDWISE_HOME")
    base = Path(home) if home else Path.home() / ".boardwise"
    return base / "pytest-slots"


def _try_lock(path: Path) -> "tuple[int, object] | None":
    """Try each slot in turn; ``(index, handle)`` on success, ``None`` if taken.

    The handle is returned open on purpose — the lock lives exactly as long as
    it does, and closing it would release the slot.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        try:
            path.write_bytes(b"\0" * SLOT_COUNT)
        except OSError:
            pass  # another run created it first, or a lock is in the way
    handle = open(path, "r+b")
    for index in range(SLOT_COUNT):
        handle.seek(index)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.lockf(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB, 1, index)
        except OSError:
            continue
        return index, handle
    handle.close()
    return None


def acquire_slot(verbose: bool = True) -> "int | None":
    """Hold one of the :data:`SLOT_COUNT` machine-wide slots, waiting if needed.

    Waits rather than failing: two full suites is the floor this machine wants,
    and a run that is worth starting is worth queueing for. The wait is a
    single line (not a heartbeat per poll) and ``Ctrl+C`` propagates — an
    ``KeyboardInterrupt`` is deliberately not caught here.

    ``None`` means "no slot, run anyway": a broken slot file must not be able to
    stop the suite (fail-open).
    """
    global _slot_handle
    path = slot_file()
    announced = False
    while True:
        try:
            taken = _try_lock(path)
        except Exception as exc:
            if verbose:
                print(
                    f"pytest 进程闸：槽文件 {path} 不可用（{exc}），本次不占槽（fail-open）",
                    flush=True,
                )
            return None
        if taken is not None:
            index, handle = taken
            _slot_handle = handle
            if verbose:
                print(
                    f"pytest 进程闸：已取得全机并发槽 {index + 1}/{SLOT_COUNT}（{path}）",
                    flush=True,
                )
            return index
        if not announced:
            print(
                f"pytest 进程闸：全机并发槽 {SLOT_COUNT} 个都被占用，排队等待中"
                "（Ctrl+C 可中断；槽随进程退出自动释放）…",
                flush=True,
            )
            announced = True
        time.sleep(0.5)


def apply_guards(
    argv: "list[str] | None" = None,
    *,
    positional: "list[str] | None" = None,
    numprocesses_value: "int | str | None" = None,
    maxprocesses: "int | None" = None,
    verbose: bool = True,
) -> None:
    """Apply the guards once per process. Safe to call from several hooks.

    ``argv`` is the command line **without** the program name (options and
    positionals mixed, as ``sys.argv[1:]`` gives it). ``positional`` is the
    positional half alone when the caller has it parsed (``config.args``);
    without it the positionals are taken from ``argv`` by dropping everything
    that starts with ``-``. ``numprocesses_value`` lets a caller that already
    has xdist's parsed option pass it in, which is the only way ``addopts``
    from a config file is seen.
    """
    global _applied
    if _applied:
        return
    _applied = True

    # The switch first (S3#7): it turns off **all four** mechanisms, so the
    # priority drop and the thread caps must not run before it is read.
    if guards_disabled():
        if verbose:
            print(
                f"pytest 进程闸：已由 {GATE_OFF_ENV}=1 关闭（四项全关：不降优先级、不封线程、"
                "不占槽、不卡 worker 上限）",
                flush=True,
            )
        return

    # The two fail-open mechanisms next: they are fail-open, and they must apply
    # even to a run that is about to be refused for its worker count.
    _apply_thread_caps()
    _lower_priority()

    if in_child():
        return

    argv = list(sys.argv[1:] if argv is None else argv)
    if numprocesses_value is None:
        numprocesses_value = numprocesses(argv)
    message = worker_violation(numprocesses_value, maxprocesses)
    if message is not None:
        import pytest

        print(message, flush=True)
        pytest.exit(message, returncode=4)

    narrow = narrowing_argv(argv)
    if not narrow and positional is not None:
        # `-k`/`-m` live in argv, a node id or a file may live in either; when a
        # caller hands us parsed positionals, they are checked too so a filter
        # never gets lost between the two forms.
        narrow = narrowing_argv(positional)
    if not narrow:
        acquire_slot(verbose)
        # The slot is this run's, so its children are part of it — the xdist
        # workers must not each queue for a slot of their own.
        os.environ[CHILD_ENV] = "1"
