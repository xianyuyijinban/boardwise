"""Compare normalized Python/Rust differential reports; only runner may differ."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.contract_validate import ensure_finite, load_path

REPORT_SCHEMA = "boardwise.differential-report/1"
COMPARISON_SCHEMA = "boardwise.differential-comparison/1"


def canonical_bytes(value: Any) -> bytes:
    """The one encoding a cross-language comparison may be decided on.

    Sorted keys, compact separators, UTF-8. Python's ``==`` calls ``True == 1``
    and ``95.0 == 95`` equal; a JSON contract that has to distinguish a boolean
    from a number cannot be decided by that operator, so the verdict comes from
    these bytes instead.

    Non-finite floats are refused rather than encoded: ``json.dumps`` would write
    ``NaN``/``Infinity``, which is not JSON and which the Rust side cannot read,
    so a hash over those bytes would not describe anything comparable.
    """
    ensure_finite(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def write_text_lf(path: Path, text: str) -> None:
    """Write exactly ``text`` with ``\\n`` line endings on every platform.

    Contract artifacts are hashed as *bytes* — ``contracts/differential/manifest.json``
    records those hashes — so a Windows text-mode write that turns ``\\n`` into
    ``\\r\\n`` would make the same golden hash differently per checkout. This is the
    single writer every contract-producing tool uses for that reason.
    """
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _normalized(report: dict[str, Any], expected_runner: str) -> dict[str, Any]:
    if report.get("schema") != REPORT_SCHEMA:
        raise ValueError(f"unexpected report schema: {report.get('schema')!r}")
    if report.get("runner") != expected_runner:
        raise ValueError(f"expected runner {expected_runner!r}, got {report.get('runner')!r}")
    if not isinstance(report.get("ok"), bool):
        raise ValueError(
            "differential report ok must be a JSON boolean, got "
            f"{report.get('ok')!r} — a report that cannot state its own verdict "
            "cannot be compared"
        )
    cases = report.get("cases")
    if not isinstance(cases, list):
        raise ValueError("differential report cases must be an array")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"differential report cases[{index}] must be an object")
        if not isinstance(case.get("ok"), bool):
            raise ValueError(
                f"differential report cases[{index}].ok must be a JSON boolean, "
                f"got {case.get('ok')!r}"
            )
    return {key: value for key, value in report.items() if key != "runner"}


def compare_reports(
    python_report: dict[str, Any], rust_report: dict[str, Any]
) -> dict[str, Any]:
    """Return a structured verdict plus hashes of the language-neutral reports."""
    python_normalized = _normalized(python_report, "python")
    rust_normalized = _normalized(rust_report, "rust")
    python_cases = len(python_normalized["cases"])
    rust_cases = len(rust_normalized["cases"])
    if python_cases != rust_cases:
        raise ValueError(
            f"the two reports ran different case counts: {python_cases} python vs "
            f"{rust_cases} rust — the comparison would be between different books"
        )
    python_encoded = canonical_bytes(python_normalized)
    rust_encoded = canonical_bytes(rust_normalized)
    return {
        "schema": COMPARISON_SCHEMA,
        "ok": python_encoded == rust_encoded,
        "pythonRunner": python_report["runner"],
        "rustRunner": rust_report["runner"],
        "caseCount": python_cases,
        "pythonNormalizedSha256": hashlib.sha256(python_encoded).hexdigest(),
        "rustNormalizedSha256": hashlib.sha256(rust_encoded).hexdigest(),
        "normalization": (
            "Remove only the runner field; both reports are then compared as canonical "
            "JSON (sorted keys, compact separators), so true and 1, or 95.0 and 95, "
            "are different values and ok is true only when the two encodings are "
            "byte-identical."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("python_report", type=Path)
    parser.add_argument("rust_report", type=Path)
    parser.add_argument("--output", type=Path, help="Also write the comparison as JSON.")
    args = parser.parse_args()
    # Same strict loader as the runner: a report carrying a NaN token is refused
    # here instead of being compared (and hashed) as if it were JSON.
    python_report = load_path(args.python_report)
    rust_report = load_path(args.rust_report)
    result = compare_reports(python_report, rust_report)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        # A text-mode write would turn these LF into CRLF on Windows and make the
        # same comparison hash differently per checkout, so it goes through the
        # one LF writer rather than Path.write_text.
        write_text_lf(args.output, text)
    print(text, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
