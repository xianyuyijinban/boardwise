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

