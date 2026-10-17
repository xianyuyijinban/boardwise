"""Test configuration: make ``src/`` importable without installing the package."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402  (after sys.path, like everything else here)


@pytest.fixture(autouse=True)
def _no_auto_daemon(monkeypatch):
    """Keep the suite from starting real daemons (157).

    Since 157 every bridge command starts a daemon when none is listening, and a
    test run is exactly the place that must not happen: a green suite would leave
    background processes behind on the developer's machine, and whether a test
    passes would depend on what happens to be listening on 61190. The switch the
    feature ships with is the switch the tests use — `tests/test_157_*` unsets it
    for the tests that are *about* the auto-start, with a fake spawn.
    """
    monkeypatch.setenv("BOARDWISE_NO_AUTO_DAEMON", "1")


# C7 (perf-02B): `tests/_pcb_cache.py` installs a session cache in front of
# `boardwise.engines.pcbreview.run_pcb_review`, which was 383 calls / 444 s of
# worker time per full run — the largest single engine entry in the suite.
#
# It has to be imported **here**, before any test module: the PCB files bind the
# runner at module scope (`from boardwise.engines.pcbreview import
# run_pcb_review`), so a conftest that imported this later would leave every one
# of them holding the uncached name. The mechanism and the cache key are in that
# file; the pins for it are in `tests/test_pcb_review_cache.py`.
import _pcb_cache  # noqa: E402,F401  (after sys.path, like everything else here)

# ---------------------------------------------------------------------------
# 193 §A: the process/CPU guards — see tests/_process_guards.py for the whole
# story (why the machine needs them, and why they are wired to two hooks).
# ---------------------------------------------------------------------------
import _process_guards  # noqa: E402,F401  (after sys.path, like everything else here)

#: ``invocation_params.args`` is the invocation as pytest received it, which may
#: or may not carry the program name depending on the entry point (``pytest``,
#: ``python -m pytest``, ``pytest.main([...])``). Dropped, so the first real
#: argument is never mistaken for a test path.
_PROGRAM_NAMES = {"pytest", "pytest.exe", "py.test", "py.test.exe", "__main__.py", "pytest.py"}


def pytest_load_initial_conftests(early_config, parser, args):
    """193 §A: apply the process guards as early as pytest offers.

    Measured on pytest 9.1.1: this hook does **not** fire for a conftest-defined
    implementation (pluggy snapshots the hook implementations, and the conftest
    that defines this one is loaded *by* the hook call itself). It is wired
    anyway — it is the hook 193's task book names, it does fire when this module
    is loaded as a ``-p`` plugin, and it would fire first on a pytest that
    changed that ordering. :func:`pytest_configure` below is what actually
    guards a plain run; ``apply_guards`` runs once whichever comes first.
    """
    _process_guards.apply_guards(list(args))


def pytest_configure(config):
    """193 §A: the hook that does fire — before ``pytest_sessionstart``, where
    xdist spawns its workers, so the concurrency slot covers the whole suite.
    """
    invocation = getattr(config, "invocation_params", None)
    argv = list(invocation.args[1:]) if invocation is not None else sys.argv[1:]
    if argv and Path(argv[0]).name in _PROGRAM_NAMES:
        argv = argv[1:]
    option = getattr(config, "option", None)
    # The worker count is read off the **command line first**: xdist resolves
    # `-n auto` into a number in its own `pytest_configure`, and which of the two
    # configure implementations runs first is not ours to decide — reading only
    # the parsed option would report `-n 16` (a count nobody typed) for `-n auto`,
    # and would lose `--maxprocesses` (xdist's cap on auto) with it. The parsed
    # option is the fallback, for a count that came from `addopts`.
    typed = _process_guards.numprocesses(argv)
    _process_guards.apply_guards(
        argv,
        positional=list(config.args),
        numprocesses_value=typed if typed is not None else getattr(option, "numprocesses", None),
        maxprocesses=getattr(option, "maxprocesses", None),
    )

