"""193 §A: the process/CPU guards, driven as **real pytest subprocesses**.

The guards live in ``tests/_process_guards.py`` and are wired from
``tests/conftest.py``; they cannot be tested in-process, because what they do is
about processes (a slot is machine-wide, a worker count is a command line, a
priority class belongs to a process). So every test here starts a real
``python -m pytest`` against ``tests/_guard_probe/`` — a whole-suite-shaped but
millisecond-cheap suite — and reads what it printed.

Two things about the environment of those children, both deliberate:

* ``PYTEST_XDIST_WORKER*`` and ``BOARDWISE_TEST_GUARD_CHILD`` are removed, so a
  child that is *meant* to take a slot is not mistaken for a worker of the run
  that spawned it;
* the four thread-pool variables are removed, so the caps this file asserts are
  the guard's doing rather than something inherited.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PROBE_DIR = Path(__file__).resolve().parent / "_guard_probe"
PROBE_FILE = PROBE_DIR / "test_guard_probe.py"

HOLD_ENV = "BOARDWISE_GUARD_PROBE_HOLD"
THREADS_ENV = "BOARDWISE_GUARD_PROBE_THREADS"
GATE_ENV = "BOARDWISE_NO_TEST_GUARDS"
CHILD_ENV = "BOARDWISE_TEST_GUARD_CHILD"
THREAD_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

#: What the guard prints, asserted literally: these lines are the operator's only
#: signal that a run is queued behind someone else, so their wording is part of
#: the interface.
ACQUIRED = "已取得全机并发槽"
WAITING = "排队等待中"

_STRIPPED = (
    "PYTEST_XDIST_WORKER",
    "PYTEST_XDIST_WORKER_COUNT",
    CHILD_ENV,
    GATE_ENV,
    HOLD_ENV,
    THREADS_ENV,
    *THREAD_VARS,
)

_GUARDS_OFF = os.environ.get(GATE_ENV, "").strip() == "1"
_guards_on_only = pytest.mark.skipif(
    _GUARDS_OFF, reason=f"{GATE_ENV}=1 in this run: the guards are switched off"
)


def _child_env(**overrides) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if name not in _STRIPPED}
    env["PYTHONIOENCODING"] = "utf-8"  # the guard's lines are Chinese
    env.update({name: str(value) for name, value in overrides.items()})
    return env


def _pytest_argv(args: list[str], basetemp: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        *args,
        "--basetemp",
        str(basetemp),
        "-p",
        "no:cacheprovider",
        "-q",
    ]


def _spawn(args: list[str], basetemp: Path, env: dict[str, str]) -> subprocess.Popen:
    return subprocess.Popen(
        _pytest_argv(args, basetemp),
        cwd=REPO,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _collect(process: subprocess.Popen, timeout: int = 120) -> tuple[int, str]:
    out, _ = process.communicate(timeout=timeout)
    return process.returncode, out.decode("utf-8", "replace")


def _run(args: list[str], basetemp: Path, env: dict[str, str] | None = None, timeout: int = 120):
    process = _spawn(args, basetemp, env if env is not None else _child_env())
    code, text = _collect(process, timeout)
    return code, text


def _recycle(path: Path) -> None:
    """Delete this file's scratch directory — to the recycle bin, never ``rm``."""
    if os.name != "nt" or not path.exists():
        return
    script = (
        "Add-Type -AssemblyName Microsoft.VisualBasic; "
        "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory("
        f"'{path}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True)


@pytest.fixture(scope="module")
def guard_tmp():
    path = REPO / ".tmp_pt_193_guard"
    path.mkdir(parents=True, exist_ok=True)
    yield path
    _recycle(path)


@_guards_on_only
def test_whole_suite_run_queues_behind_two_slots(guard_tmp):
    """Two runs hold the slots; a third whole-suite run waits — and says so.

    Two holders, eight seconds each, third started in between. Whichever way the
    slots land (the run this test is part of may hold one of them itself), at
    least one of the three must have spent time in the queue, and all three must
    still finish green: waiting is not failing.
    """
    holders = [
        _spawn([str(PROBE_DIR)], guard_tmp / label, _child_env(**{HOLD_ENV: "8"}))
        for label in ("hold-a", "hold-b")
    ]
    time.sleep(2.0)
    code, text = _run([str(PROBE_DIR)], guard_tmp / "third")
    holder_results = [_collect(holder) for holder in holders]

    assert code == 0, text
    for holder_code, holder_text in holder_results:
        assert holder_code == 0, holder_text
    outputs = [text, *(holder_text for _, holder_text in holder_results)]
    assert any(WAITING in out for out in outputs), "\n".join(outputs)
    assert any(ACQUIRED in out for out in outputs), "\n".join(outputs)


@_guards_on_only
def test_auto_and_oversized_worker_counts_are_refused(guard_tmp):
    """`-n auto` and `-n > 4` stop the run; `-n 4` and a capped `auto` pass."""
    for spelling in (["-n", "auto"], ["--numprocesses=6"], ["-n4", "-q"]):
        args = [str(PROBE_DIR), *spelling]
        code, text = _run(args, guard_tmp / ("refuse-" + "-".join(spelling).replace("/", "_")))
        if spelling == ["-n4", "-q"]:
            assert code == 0, text  # `-n4` is `-n 4`: allowed
            continue
        assert code == 4, f"{spelling} should be a usage error, got {code}\n{text}"
        assert "进程闸：拒绝" in text, text

    code, text = _run(
        [str(PROBE_DIR), "-n", "auto", "--maxprocesses", "4"], guard_tmp / "auto-capped"
    )
    assert code == 0, f"`-n auto --maxprocesses=4` cannot exceed the cap; got {code}\n{text}"


@_guards_on_only
def test_range_run_takes_no_slot_and_does_not_queue(guard_tmp):
    """A run narrowed to a file is not the hog the slots exist for.

    Asserted while both slots are busy: the range run finishes at once and never
    prints a slot line at all.
    """
    holders = [
        _spawn([str(PROBE_DIR)], guard_tmp / label, _child_env(**{HOLD_ENV: "6"}))
        for label in ("busy-a", "busy-b")
    ]
    time.sleep(1.5)
    started = time.monotonic()
    code, text = _run([str(PROBE_FILE), "-q", "-n", "0"], guard_tmp / "range")
    elapsed = time.monotonic() - started
    for holder in holders:
        _collect(holder)

    assert code == 0, text
    assert ACQUIRED not in text and WAITING not in text, text
    assert elapsed < 4.0, f"a range run with -n 0 queued behind the slots ({elapsed:.1f}s)"


@_guards_on_only
def test_broken_slot_file_fails_open(guard_tmp):
    """A slot file that cannot be created must not be able to stop the suite."""
    blocker = guard_tmp / "not-a-directory"
    blocker.write_text("occupied by a file\n", encoding="utf-8")
    env = _child_env(BOARDWISE_HOME=str(blocker))
    # A directory argument: a slot-taking run, which is the only kind that ever
    # touches the slot file.
    code, text = _run([str(PROBE_DIR)], guard_tmp / "failopen", env)
    assert code == 0, text
    assert "fail-open" in text, text


@_guards_on_only
def test_thread_pool_caps_reach_the_test_process(guard_tmp):
    """§A.4 end to end: a real pytest process sees the four variables at 1."""
    env = _child_env(**{THREADS_ENV: "1"})
    code, text = _run([str(PROBE_FILE), "-q", "-k", "thread_caps"], guard_tmp / "threads", env)
    assert code == 0, text


@_guards_on_only
@pytest.mark.skipif(os.name != "nt", reason="priority class is a Windows concept")
def test_this_run_is_below_normal_priority():
    """Read back the class of the process running *this* test.

    The conftest guard lowered this session's own priority at configure time
    (xdist workers inherit it), and both the Windows API and the guard live in
    the same process here — so the reading is the guard's own work.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    kernel32.GetPriorityClass.argtypes = (ctypes.c_void_p,)
    kernel32.GetPriorityClass.restype = ctypes.c_uint32
    below_normal = 0x00004000
    assert kernel32.GetPriorityClass(kernel32.GetCurrentProcess()) == below_normal


def test_gate_switch_switches_the_guards_off(guard_tmp):
    """`BOARDWISE_NO_TEST_GUARDS=1` is the one way past all four mechanisms."""
    env = _child_env(**{GATE_ENV: "1"})
    code, text = _run([str(PROBE_DIR), "-n", "auto", "--maxprocesses", "2"], guard_tmp / "off", env)
    assert code == 0, f"the gate switch must let `-n auto` through; got {code}\n{text}"
    assert ACQUIRED not in text and WAITING not in text, text
