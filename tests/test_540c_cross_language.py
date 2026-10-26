"""540C: the Rust ``differential`` process must be a drop-in for the Python one.

This is the cross-language gate for the CLI surface, not for the report content
(`tests/test_540c_differential.py` and the golden corpus cover that). It runs
both processes and compares, for each observable behaviour:

* success (`--cases PATH`, `--cases=PATH`, repeated flags, `--output`) — exit 0,
  empty stderr, and the same normalized report on stdout;
* help (`-h` / `--help`) — exit 0, help on stdout, empty stderr;
* usage errors (unknown flag, missing value) — exit 2 with plain usage text on
  stderr, never the structured envelope;
* request failures (schema refusal, unknown case kind, unwritable ``--output``)
  — exit 2, empty stdout, one ``boardwise.cli-result/1`` envelope on stderr;
* a differing golden — exit 1 with the report on stdout.

When the Rust binary has not been built the whole module skips, so a plain
``pytest tests/`` does not fail for a missing artifact. That skip is *not*
acceptance: the final check must build the binary and see these tests pass, as
``docs/rust-platform.md`` records.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.differential_compare import canonical_bytes, compare_reports

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "contracts" / "differential" / "cases.json"
INPUT_ROOT = ROOT / "contracts" / "differential" / "inputs"
BINARY = ROOT / "rust" / "target" / "debug" / (
    "boardwise-cli.exe" if sys.platform == "win32" else "boardwise-cli"
)
CLI_RESULT_SCHEMA = "boardwise.cli-result/1"

pytestmark = pytest.mark.skipif(
    not BINARY.is_file(),
    reason="Rust CLI is not built (cargo build -p boardwise-cli); a skip is not acceptance",
)


def _python(*arguments: str) -> subprocess.CompletedProcess[str]:
    # argparse writes its help through the console encoding; pin the child to
    # UTF-8 so the test decodes the same text on every machine.
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "tools.differential", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
    )


def _rust(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BINARY), "differential", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _report(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _assert_same_report(
    python_result: subprocess.CompletedProcess[str],
    rust_result: subprocess.CompletedProcess[str],
) -> None:
    comparison = compare_reports(_report(python_result), _report(rust_result))
    assert comparison["ok"] is True, comparison
    assert comparison["pythonNormalizedSha256"] == comparison["rustNormalizedSha256"]


def _assert_envelope(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 2, result.stderr
    assert result.stdout == "", "a refusal states no report on stdout"
    envelope = json.loads(result.stderr)
    assert envelope["schema"] == CLI_RESULT_SCHEMA
    assert envelope["command"] == "differential"
    assert envelope["exitCode"] == 2
    assert envelope["error"]["code"] == "BAD_REQUEST"
    assert "payload" not in envelope


def _without_runner(report: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key != "runner"}


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _book(path: Path, *, kind: str, input_name: str, expected: Any) -> Path:
    return _write_json(
        path,
        {
            "schema": "boardwise.differential-cases/1",
            "cases": [
                {"id": "cross-language", "kind": kind, "input": input_name, "expected": expected}
            ],
        },
    )


def test_success_reports_match_in_both_flag_spellings() -> None:
    for arguments in (
        ["--cases", str(CASES), "--root", str(ROOT)],
        [f"--cases={CASES}", f"--root={ROOT}"],
    ):
        python_result = _python(*arguments)
        rust_result = _rust(*arguments)
        assert python_result.returncode == 0, python_result.stderr
        assert rust_result.returncode == 0, rust_result.stderr
        assert python_result.stderr == ""
        assert rust_result.stderr == ""
        _assert_same_report(python_result, rust_result)


def test_output_file_is_written_by_both_and_holds_the_same_report(tmp_path: Path) -> None:
    python_path = tmp_path / "python-differential.json"
    rust_path = tmp_path / "rust-differential.json"
    python_result = _python(
        "--cases", str(CASES), "--root", str(ROOT), "--output", str(python_path)
    )
    rust_result = _rust(
        f"--cases={CASES}", f"--root={ROOT}", f"--output={rust_path}"
    )
    assert python_result.returncode == 0, python_result.stderr
    assert rust_result.returncode == 0, rust_result.stderr
    _assert_same_report(python_result, rust_result)

    python_report = json.loads(python_path.read_text(encoding="utf-8"))
    rust_report = json.loads(rust_path.read_text(encoding="utf-8"))
    assert canonical_bytes(_without_runner(python_report)) == canonical_bytes(
        _without_runner(rust_report)
    )
    # Contract artifacts are hashed as bytes: the writer must not turn LF into
    # CRLF on Windows, exactly like `write_text_lf` on the Python side.
    assert b"\r\n" not in rust_path.read_bytes()
    assert b"\r\n" not in python_path.read_bytes()


def test_repeated_flags_take_the_last_value(tmp_path: Path) -> None:
    missing = tmp_path / "absent-book.json"
    arguments = [
        f"--cases={missing}",
        f"--cases={CASES}",
        f"--root={tmp_path}",
        f"--root={ROOT}",
    ]
    python_result = _python(*arguments)
    rust_result = _rust(*arguments)
    assert python_result.returncode == 0, python_result.stderr
    assert rust_result.returncode == 0, rust_result.stderr
    _assert_same_report(python_result, rust_result)


def test_help_is_stdout_exit_zero_and_stderr_empty() -> None:
    python_result = _python("-h")
    rust_result = _rust("--help")
    assert python_result.returncode == 0
    assert rust_result.returncode == 0
    assert python_result.stderr == ""
    assert rust_result.stderr == ""
    assert "usage" in python_result.stdout.lower()
    assert "usage" in rust_result.stdout.lower()
    assert rust_result.stdout.lstrip()[:1] != "{", "help is text, not the envelope"


def test_usage_errors_are_plain_usage_text_exit_two() -> None:
    for arguments in (["--bogus"], ["--cases"]):
        python_result = _python(*arguments)
        rust_result = _rust(*arguments)
        assert python_result.returncode == 2, arguments
        assert rust_result.returncode == 2, arguments
        # Python keeps argparse's own text; Rust states its own. Neither is the
        # structured envelope, and both say "usage".
        assert "usage" in python_result.stderr.lower()
        assert rust_result.stdout == ""
        assert "usage" in rust_result.stderr.lower()
        assert CLI_RESULT_SCHEMA not in rust_result.stderr
        with pytest.raises(json.JSONDecodeError):
            json.loads(rust_result.stderr)


def test_schema_invalid_and_unknown_kind_share_the_envelope_shape(tmp_path: Path) -> None:
    input_file = tmp_path / "bad.layout.json"
    input_file.write_text("{}\n", encoding="utf-8")
    schema_invalid = _book(
        tmp_path / "schema-invalid.json",
        kind="layout-plan-geometry",
        input_name=input_file.name,
        expected={},
    )
    unknown_kind = _book(
        tmp_path / "unknown-kind.json",
        kind="not-a-kind",
        input_name=input_file.name,
        expected={},
    )
    for book in (schema_invalid, unknown_kind):
        python_result = _python("--cases", str(book), "--root", str(tmp_path))
        rust_result = _rust("--cases", str(book), "--root", str(tmp_path))
        assert python_result.returncode == 2, book.name
        _assert_envelope(rust_result)
        _assert_envelope(python_result)


def test_output_parent_missing_is_the_same_request_failure(tmp_path: Path) -> None:
    output = tmp_path / "no-such-directory" / "report.json"
    python_result = _python("--output", str(output))
    rust_result = _rust("--output", str(output))
    _assert_envelope(python_result)
    _assert_envelope(rust_result)


def test_golden_mismatch_exits_one_on_both(tmp_path: Path) -> None:
    book = _book(
        tmp_path / "mismatch.json",
        kind="layout-plan-geometry",
        input_name="contracts/differential/inputs/divider-cand1.layout.json",
        expected={"geometrySha256": "0" * 64},
    )
    python_result = _python("--cases", str(book), "--root", str(ROOT))
    rust_result = _rust("--cases", str(book), "--root", str(ROOT))
    assert python_result.returncode == 1, python_result.stderr
    assert rust_result.returncode == 1, rust_result.stderr
    assert python_result.stderr == ""
    assert rust_result.stderr == ""
    python_report = json.loads(python_result.stdout)
    rust_report = json.loads(rust_result.stdout)
    assert python_report["ok"] is False
    assert rust_report["ok"] is False
    comparison = compare_reports(python_report, rust_report)
    assert comparison["ok"] is True, comparison
