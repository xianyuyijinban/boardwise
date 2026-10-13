"""bug98-C: the CLI's own output is UTF-8, whatever the locale says.

Field report item 3: the Chinese in `report.json`'s `source.notes` came out
garbled on a GBK console. The data was never wrong — the file is UTF-8 — so the
defect, where there is one, sits in the CLI's *printing* path: Windows hands a
piped (or file-) redirected `sys.stdout` the locale codepage (`cp936` on this
machine), and every non-ASCII character then goes out as bytes that a UTF-8
reader shows as mojibake. `main()` puts both streams back on UTF-8 before the
parser runs.

What is pinned here, and why each test exists:

* `test_main_reconfigures_both_streams_to_utf8` — the unit contract, on stub
  streams, so the two arguments (`encoding`, `errors`) cannot be dropped or
  quietly changed by a later edit;
* `test_main_tolerates_a_stream_without_reconfigure` — the guard: pytest's
  capture shims and any odd file-like must not turn `main()` into an
  `AttributeError`;
* `test_main_reconfigures_before_it_parses` — *ordering*: the reconfigure has to
  happen before `argparse` prints usage/help, or `--help`'s own Chinese is the
  first thing to break;
* `test_report_content_is_utf8_on_a_gbk_pipe` — the field report, end to end:
  a real `checkup --file` run with stdio forced to GBK still emits UTF-8 bytes
  that decode back to the original Chinese — the report's own `note:` lines and
  the offline-tier headline;
* `test_bridge_error_is_utf8_on_a_gbk_pipe` — the other path the task names:
  a daemon-less `bridge call` diagnostic, same GBK stdio;
* `test_main_survives_capsys` — the capsys family stays green while `main()`
  reconfigures whatever stream capsys installed.

The GBK simulation is `PYTHONIOENCODING=gbk` on the child, not a machine-wide
locale change: it is exactly the encoding a cp936 pipe would get, it is
deterministic on any host, and `reconfigure` is the only thing that outranks it
— which is what makes these tests go red the moment the fix is removed.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import cli

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = Path(__file__).parent / "fixtures" / "ch340_golden.epro2"


def _free_port() -> str:
    """A port nothing is listening on — the daemon-less path below needs one."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return str(probe.getsockname()[1])


class _ReconfigurableStream:
    """A stand-in for `sys.stdout` that remembers how it was configured."""

    def __init__(self) -> None:
        self.reconfigures: list[dict] = []
        self.written: list[str] = []

    def reconfigure(self, **kwargs) -> None:
        self.reconfigures.append(kwargs)

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


class _BareStream:
    """The shape pytest's capture objects take: `write`/`flush`, no reconfigure."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        pass


def _gbk_pipe_env() -> dict:
    """The environment of a GBK console/pipe, minus any UTF-8 override."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("PYTHONIOENCODING", "PYTHONUTF8")
    }
    env["PYTHONIOENCODING"] = "gbk"
    env["BOARDWISE_NO_AUTO_DAEMON"] = "1"
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_cli(*args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        timeout=300,
    )


def test_main_reconfigures_both_streams_to_utf8(monkeypatch):
    out, err = _ReconfigurableStream(), _ReconfigurableStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    with pytest.raises(SystemExit):  # argparse's own way out of `--help`
        cli.main(["bridge", "--help"])
    assert out.reconfigures == [{"encoding": "utf-8", "errors": "replace"}]
    assert err.reconfigures == [{"encoding": "utf-8", "errors": "replace"}]


def test_main_tolerates_a_stream_without_reconfigure(monkeypatch):
    bare = _BareStream()
    monkeypatch.setattr(sys, "stdout", bare)
    monkeypatch.setattr(sys, "stderr", bare)
    with pytest.raises(SystemExit):  # not AttributeError: the guard held
        cli.main(["bridge", "--help"])


def test_main_reconfigures_before_it_parses(monkeypatch):
    """`--help`'s Chinese (e.g. `checkup`'s ``有益/有害/无害``) is printed by
    argparse, so a reconfigure after `parse_args` would be too late for it."""
    out = _ReconfigurableStream()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _ReconfigurableStream())
    with pytest.raises(SystemExit):
        cli.main(["checkup", "--help"])
    assert out.reconfigures, "stream was never reconfigured before argparse printed"
    assert out.written, "argparse printed nothing through the patched stream"
    assert any("usage:" in chunk for chunk in out.written)


def test_report_content_is_utf8_on_a_gbk_pipe(tmp_path):
    proc = _run_cli(
        "checkup", "--file", str(FIXTURE), "--out", str(tmp_path / "out"),
        env=_gbk_pipe_env(),
    )
    # The exit code is deliberately *not* pinned: the fixture's verdict moves
    # whenever a rule does, and this test is about the bytes on the pipe.
    # GBK bytes would not even decode here — that is the field's mojibake.
    text = proc.stdout.decode("utf-8")
    proc.stderr.decode("utf-8")
    assert "离线文件（--file）：不连编辑器" in text
    # A `note:` line, i.e. the report's own voice — the field's `source.notes`.
    assert "note: 页数带器件的只有" in text


def test_bridge_error_is_utf8_on_a_gbk_pipe():
    proc = _run_cli(
        "bridge", "--port", _free_port(), "call",
        "--action", "doc.list", "--params", "{}",
        env=_gbk_pipe_env(),
    )
    out = proc.stdout.decode("utf-8")
    err = proc.stderr.decode("utf-8")
    assert proc.returncode == 2, (out, err)
    assert "daemon not reachable" in (out + err)


def test_main_survives_capsys(capsys):
    with pytest.raises(SystemExit):
        cli.main(["bridge", "--help"])
    captured = capsys.readouterr()
    assert "usage:" in captured.out
