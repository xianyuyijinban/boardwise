"""A deliberately tiny suite the 193 guard tests drive in a subprocess.

It exists so the guard tests can run **real pytest processes** against the real
``tests/conftest.py`` guard without paying for the whole suite: this directory
is a whole-suite-shaped run (a directory argument, no ``-k``, no node id), so it
takes a concurrency slot exactly like `pytest tests/` does, and it finishes in
milliseconds.

The two environment variables it reads are the guard tests' controls — nothing
else sets them, so in a normal run this file is two trivial passes.
"""

import os
import time

_THREAD_VARS = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def test_guard_probe_holds_the_slot_when_asked():
    """Sleeps for ``BOARDWISE_GUARD_PROBE_HOLD`` seconds — i.e. holds the slot.

    The guard tests start two of these to occupy both machine-wide slots and
    watch a third run queue behind them.
    """
    hold = float(os.environ.get("BOARDWISE_GUARD_PROBE_HOLD") or 0)
    if hold:
        time.sleep(hold)
    assert hold >= 0


def test_guard_probe_thread_caps():
    """193 §A.4, asserted **in a real pytest child process**, not in-process."""
    if os.environ.get("BOARDWISE_GUARD_PROBE_THREADS") != "1":
        import pytest

        pytest.skip("only asserted when the guard test asks for it")
    for name in _THREAD_VARS:
        assert os.environ.get(name) == "1", f"{name} not capped: {os.environ.get(name)!r}"
