"""540C F5: the Python differential runner's failure surface is contract-shaped.

The Rust CLI states every request failure as one ``boardwise.cli-result/1``
document on stderr and exits 2. This module pins the same surface on the Python
side — an unusable input must never leave a traceback or exit 1 — and pins the
two paths that must not move: exit 0 with the report on stdout (byte for byte),
and exit 1 when a golden disagrees. argparse's own usage errors are pinned as
*unchanged* rather than converted: the Rust CLI now parses ``--flag=value`` and
answers ``-h``/``--help``, but its abbreviation, help ordering/wording and error
phrasing still differ (F6), so these tests pin only the Python side's boundary.

The tests read the trajectory both in process (``main`` + ``capsys``) and once
across the real process boundary (``python -m tools.differential``), because the
envelope is a promise about the *process*: stdout empty, stderr one JSON document,
and the exit code a script branches on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

import pytest

from tools.differential import (
    CLI_RESULT_SCHEMA,
    ERROR_EXIT_CODE,
    main as differential_main,
    run_cases,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "contracts" / "differential" / "cases.json"
LAYOUT_INPUT = (
    ROOT / "contracts" / "differential" / "inputs" / "divider-cand1.layout.json"
)


def _book() -> dict:
    return json.loads(CASES.read_text(encoding="utf-8"))


def _write_book(path: Path, book: dict) -> Path:
    path.write_text(json.dumps(book), encoding="utf-8")
    return path


def _invoke(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> int:
    monkeypatch.setattr(sys, "argv", argv)
    return differential_main()


def _one_envelope(stderr: str) -> dict:
    """stderr is exactly one JSON document: ``json.loads`` refuses extra data."""
    return json.loads(stderr)


def _assert_bad_request(stdout: str, stderr: str, code: int) -> dict:
    assert code == ERROR_EXIT_CODE == 2
    assert stdout == "", "a failure states no result on stdout"
    assert "Traceback" not in stderr
    envelope = _one_envelope(stderr)
    assert set(envelope) == {"schema", "command", "exitCode", "error"}
    assert envelope["schema"] == CLI_RESULT_SCHEMA == "boardwise.cli-result/1"
    assert envelope["command"] == "differential"
    assert envelope["exitCode"] == 2
    assert envelope["error"]["code"] == "BAD_REQUEST"
    assert "payload" not in envelope
    message = envelope["error"]["message"]
    assert isinstance(message, str) and message.strip()
    return envelope


def test_unknown_case_kind_is_a_bad_request_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    book = _book()
    book["cases"][0]["kind"] = "review-report-projection-typo"
    cases = _write_book(tmp_path / "cases.json", book)

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(cases), "--root", str(ROOT),
    ])
    captured = capsys.readouterr()
    envelope = _assert_bad_request(captured.out, captured.err, code)
    assert "unknown differential case kind" in envelope["error"]["message"]
    assert "review-report-projection-typo" in envelope["error"]["message"]


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda book: book.pop("cases"), "no cases array"),
        (lambda book: book.update(cases="not-a-list"), "no cases array"),
        (lambda book: book.update(cases=[42]), "is a JSON object, got int"),
    ],
    ids=["cases-missing", "cases-not-an-array", "case-not-an-object"],
)
def test_unusable_case_book_is_a_bad_request_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mutate: Callable[[dict], None],
    needle: str,
) -> None:
    book = _book()
    mutate(book)
    cases = _write_book(tmp_path / "cases.json", book)

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(cases), "--root", str(ROOT),
    ])
    captured = capsys.readouterr()
    envelope = _assert_bad_request(captured.out, captured.err, code)
    assert needle in envelope["error"]["message"]


def test_input_the_contract_schema_refuses_is_a_bad_request_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The layout-plan schema is `additionalProperties: false`; this is the
    F5 reproducer: an input the Python runner refuses used to raise a traceback."""
    payload = json.loads(LAYOUT_INPUT.read_text(encoding="utf-8"))
    payload["probe"] = True
    (tmp_path / "layout-with-extra-key.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    cases = _write_book(tmp_path / "cases.json", {
        "schema": "boardwise.differential-cases/1",
        "cases": [{
            "id": "layout-plan-geometry",
            "kind": "layout-plan-geometry",
            "input": "layout-with-extra-key.json",
            "expected": {"partCount": 2},
        }],
    })

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(cases), "--root", str(tmp_path),
    ])
    captured = capsys.readouterr()
    envelope = _assert_bad_request(captured.out, captured.err, code)
    assert "contract error" in envelope["error"]["message"]
    assert "probe" in envelope["error"]["message"]


def test_missing_case_file_is_a_bad_request_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    absent = tmp_path / "absent-cases.json"

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(absent), "--root", str(ROOT),
    ])
    captured = capsys.readouterr()
    envelope = _assert_bad_request(captured.out, captured.err, code)
    # The local diagnostic is kept (path included), but it is not the Rust text:
    # freezing the OS's localized wording as a contract would drift per platform.
    assert "I/O error" in envelope["error"]["message"]
    assert "absent-cases.json" in envelope["error"]["message"]


def test_output_whose_parent_directory_is_missing_is_a_bad_request_envelope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "missing-directory" / "python-differential.json"

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(CASES), "--root", str(ROOT),
        "--output", str(output),
    ])
    captured = capsys.readouterr()
    envelope = _assert_bad_request(captured.out, captured.err, code)
    assert "I/O error" in envelope["error"]["message"]
    # No half-written artifact and no directory invented on the way.
    assert not output.exists()
    assert not output.parent.exists()


def test_success_stdout_exit_and_bytes_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "python-differential.json"
    code = _invoke(monkeypatch, [
        "differential", "--cases", str(CASES), "--root", str(ROOT),
        "--output", str(output),
    ])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    # The exact bytes the runner has always printed: one pretty JSON document,
    # UTF-8, LF-terminated, no CR.
    expected = (json.dumps(run_cases(CASES, ROOT), ensure_ascii=False, indent=2) + "\n")
    assert captured.out == expected
    assert output.read_bytes() == captured.out.encode("utf-8")
    report = json.loads(captured.out)
    assert report["ok"] is True
    # Five cases, each a JSON `true`. `is True` rather than `== True` on purpose:
    # `1 == True` in Python, and a golden that spelled a boolean as 1 must not
    # pass here while the Rust side reads it as a number.
    assert len(report["cases"]) == 5
    assert all(case["ok"] is True for case in report["cases"])


def test_golden_mismatch_keeps_exit_one_and_the_report_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    book = _book()
    book["cases"][0]["expected"]["findingCount"] += 1
    cases = _write_book(tmp_path / "cases.json", book)

    code = _invoke(monkeypatch, [
        "differential", "--cases", str(cases), "--root", str(ROOT),
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == "", "a differing golden is a verdict, not a request failure"
    expected = (json.dumps(run_cases(cases, ROOT), ensure_ascii=False, indent=2) + "\n")
    assert captured.out == expected
    assert json.loads(captured.out)["ok"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["differential", "--cases"],
        ["differential", "--cases", str(CASES), "--definitely-not-a-flag"],
    ],
    ids=["flag-without-value", "unknown-flag"],
)
def test_argparse_usage_errors_are_left_to_argparse(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    """The stated boundary: usage errors are argparse's, not this envelope's.

    The Rust CLI now parses ``--flag=value`` and answers ``-h``/``--help``, so the
    two surfaces are no longer missing each other; what still differs is argparse's
    unambiguous-prefix abbreviation, its help ordering and wording, and its error
    phrasing (F6). This test therefore pins only the Python side's own boundary —
    argparse text on stderr, nothing on stdout, exit 2 — not a shared shape.
    """
    with pytest.raises(SystemExit) as exit_info:
        _invoke(monkeypatch, argv)
    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("usage: ")
    assert CLI_RESULT_SCHEMA not in captured.err


def _run_process(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "tools.differential", *arguments],
        cwd=ROOT,
        capture_output=True,
        env=environment,
        timeout=120,
    )


def test_real_process_success_is_zero_with_no_stderr_and_one_report() -> None:
    result = _run_process(["--cases", str(CASES), "--root", str(ROOT)])
    assert result.returncode == 0
    assert result.stderr == b""
    report = json.loads(result.stdout)
    assert report == run_cases(CASES, ROOT)
    # The bytes the runner already writes, not an aspiration: `print` to a pipe
    # translates "\n" to the platform newline (F7 tracks the Python/Rust LF drift
    # separately — this batch may not move it). On POSIX this is the LF text.
    expected = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").replace(
        "\n", os.linesep
    )
    assert result.stdout.decode("utf-8") == expected


def test_real_process_failure_is_two_with_one_envelope_and_empty_stdout(
    tmp_path: Path,
) -> None:
    result = _run_process(["--cases", str(tmp_path / "absent.json")])
    assert result.returncode == 2
    assert result.stdout == b"", "the failing process must print nothing on stdout"
    assert b"Traceback" not in result.stderr
    envelope = _one_envelope(result.stderr.decode("utf-8"))
    assert envelope["schema"] == CLI_RESULT_SCHEMA
    assert envelope["command"] == "differential"
    assert envelope["exitCode"] == 2
    assert envelope["error"]["code"] == "BAD_REQUEST"
    assert "payload" not in envelope
