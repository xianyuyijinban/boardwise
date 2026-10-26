"""540C: prove the public Python/golden differential path is executable."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

from tools.differential import SCHEMAS, main as differential_main, project_case, run_cases
from tools.differential_compare import (
    compare_reports,
    main as comparison_main,
    write_text_lf,
)
from tools import build_differential_fixtures as fixtures

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "contracts" / "differential" / "cases.json"
MANIFEST = ROOT / "contracts" / "differential" / "manifest.json"
EXPECTED_KINDS = {
    "review-report-projection",
    "layout-plan-geometry",
    "compile-result-projection",
    "compile-page-result-projection",
    "lint-result-projection",
}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_python_runner_executes_every_repository_golden_case() -> None:
    report = run_cases(CASES, ROOT)
    assert report["schema"] == "boardwise.differential-report/1"
    assert report["runner"] == "python"
    assert report["ok"] is True
    assert len(report["cases"]) == 5
    assert {case["kind"] for case in _json(CASES)["cases"]} == EXPECTED_KINDS
    assert all(case["ok"] and case["actual"] == case["expected"] for case in report["cases"])


def test_manifest_pins_sources_sanitized_inputs_and_case_book() -> None:
    manifest = _json(MANIFEST)
    assert manifest["schema"] == "boardwise.differential-manifest/1"
    for relative, expected in manifest["sources"].items():
        assert _sha(ROOT / relative) == expected
    for relative, expected in manifest["inputs"].items():
        assert _sha(ROOT / relative) == expected
    assert _sha(ROOT / manifest["caseBook"]["path"]) == manifest["caseBook"]["sha256"]
    assert manifest["regenerate"] == ".venv/Scripts/python.exe -m tools.build_differential_fixtures"


def test_differential_inputs_are_unique_and_machine_path_sanitized() -> None:
    book = _json(CASES)
    ids = [case["id"] for case in book["cases"]]
    assert len(ids) == len(set(ids)) == 5
    forbidden = [
        ".tmp_540", str(ROOT), str(ROOT).replace("\\", "/"),
        str(Path.home()), str(Path.home()).replace("\\", "/"),
    ]
    for case in book["cases"]:
        text = (ROOT / case["input"]).read_text(encoding="utf-8")
        assert all(value not in text for value in forbidden if value)


def test_python_cli_report_stdout_and_file_agree(tmp_path, monkeypatch, capsys) -> None:
    output = tmp_path / "python-differential.json"
    monkeypatch.setattr(sys, "argv", [
        "differential", "--cases", str(CASES), "--root", str(ROOT), "--output", str(output),
    ])
    assert differential_main() == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    stdout = json.loads(captured.out)
    assert stdout == _json(output)
    assert stdout["ok"] is True


def test_a_changed_golden_is_a_failure_not_a_pass(tmp_path, monkeypatch, capsys) -> None:
    book = deepcopy(_json(CASES))
    book["cases"][0]["expected"]["findingCount"] += 1
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(book), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [
        "differential", "--cases", str(cases), "--root", str(ROOT),
    ])
    assert differential_main() == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert [case["ok"] for case in report["cases"]] == [False, True, True, True, True]


def test_normalized_comparison_accepts_identical_cross_language_reports() -> None:
    python_report = run_cases(CASES, ROOT)
    rust_report = deepcopy(python_report)
    rust_report["runner"] = "rust"
    result = compare_reports(python_report, rust_report)
    assert result["ok"] is True
    assert result["caseCount"] == 5
    assert result["pythonNormalizedSha256"] == result["rustNormalizedSha256"]


def test_normalized_comparison_rejects_a_real_case_difference() -> None:
    python_report = run_cases(CASES, ROOT)
    rust_report = deepcopy(python_report)
    rust_report["runner"] = "rust"
    rust_report["cases"][0]["actual"]["findingCount"] += 1
    result = compare_reports(python_report, rust_report)
    assert result["ok"] is False
    assert result["pythonNormalizedSha256"] != result["rustNormalizedSha256"]


def _cross_language_reports() -> tuple[dict, dict]:
    python_report = run_cases(CASES, ROOT)
    rust_report = deepcopy(python_report)
    rust_report["runner"] = "rust"
    return python_report, rust_report


GOLDEN_INPUTS = {
    "review-report-projection": ROOT / "contracts/differential/inputs/review-report.json",
    "layout-plan-geometry": ROOT / "contracts/differential/inputs/divider-cand1.layout.json",
    "compile-result-projection": ROOT / "contracts/differential/inputs/divider-compile-result.json",
    "compile-page-result-projection": ROOT / "contracts/differential/inputs/page-compile-result.json",
    "lint-result-projection": ROOT / "contracts/differential/inputs/empty-page-lint-result.json",
}


def test_page_golden_projects_a_page_count_and_never_a_candidate_count() -> None:
    """A page document holds pages. Folding it into a module-shaped
    `candidateCount` would state a count the producer never wrote."""
    case = next(
        case for case in _json(CASES)["cases"]
        if case["kind"] == "compile-page-result-projection"
    )
    expected = case["expected"]
    assert "candidateCount" not in expected
    assert expected["pageCount"] == 8
    actual = project_case(case, ROOT)
    assert actual == expected
    assert len(actual["previewNames"]) == 16
    assert all(Path(name).name == name for name in actual["previewNames"])


def test_write_text_lf_never_translates_newlines(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    write_text_lf(path, '{\n  "a": "b"\n}\n')
    assert path.read_bytes() == b'{\n  "a": "b"\n}\n'


def test_contract_json_artifacts_carry_no_cr_bytes() -> None:
    offenders = [
        str(path) for path in sorted((ROOT / "contracts").rglob("*.json"))
        if b"\r" in path.read_bytes()
    ]
    assert not offenders, f"contract JSON must be LF, CR found in: {offenders}"


def test_manifest_hashes_are_hashes_of_the_lf_bytes() -> None:
    manifest = _json(MANIFEST)
    recorded = dict(manifest["inputs"])
    recorded[manifest["caseBook"]["path"]] = manifest["caseBook"]["sha256"]
    for relative, expected in recorded.items():
        raw = (ROOT / relative).read_bytes()
        assert b"\r" not in raw, f"{relative} would hash differently after a CRLF checkout"
        assert hashlib.sha256(raw).hexdigest() == expected, relative


def test_python_runner_writes_its_report_with_lf(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "python-differential.json"
    monkeypatch.setattr(sys, "argv", [
        "differential", "--cases", str(CASES), "--root", str(ROOT), "--output", str(output),
    ])
    assert differential_main() == 0
    assert b"\r" not in output.read_bytes()


def test_comparison_cli_output_is_lf_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The written comparison is a hashed contract artifact, so the `--output` file
    must carry LF bytes on every platform. The `capsys` assertion below compares
    the same text in-process only: a redirected stdout is still text-translated to
    CRLF on Windows, so nothing here claims stdout itself is LF."""
    python_doc, rust_doc = _cross_language_reports()
    python_report = tmp_path / "python-differential.json"
    rust_report = tmp_path / "rust-differential.json"
    output = tmp_path / "comparison.json"
    python_report.write_bytes(json.dumps(python_doc, ensure_ascii=False).encode("utf-8"))
    rust_report.write_bytes(json.dumps(rust_doc, ensure_ascii=False).encode("utf-8"))
    monkeypatch.setattr(sys, "argv", [
        "differential_compare", str(python_report), str(rust_report),
        "--output", str(output),
    ])
    assert comparison_main() == 0
    raw = output.read_bytes()
    assert b"\r" not in raw, "the comparison artifact must carry LF, not CRLF"
    assert raw.endswith(b"\n")
    assert raw.count(b"\n") == len(raw.decode("utf-8").splitlines())
    assert json.loads(raw.decode("utf-8"))["ok"] is True
    assert raw.decode("utf-8") == capsys.readouterr().out


def test_generator_renders_the_committed_golden_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two renders of the committed inputs, published into a temp tree, are identical
    and equal the committed artifacts — the golden is a pure function of its inputs."""
    monkeypatch.setattr(fixtures, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(fixtures, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(fixtures, "MANIFEST", tmp_path / "manifest.json")
    first = fixtures._render(GOLDEN_INPUTS)
    fixtures._publish(first)
    second = fixtures._render(GOLDEN_INPUTS)
    assert first == second
    for name in fixtures.INPUT_NAMES.values():
        assert (tmp_path / "inputs" / name).read_bytes() == (
            ROOT / "contracts/differential/inputs" / name
        ).read_bytes()
    assert (tmp_path / "cases.json").read_bytes() == CASES.read_bytes()
    assert (tmp_path / "manifest.json").read_bytes() == MANIFEST.read_bytes()


def test_a_projection_failure_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F8: all projection happens before any final file write, so a failure leaves
    the previous golden untouched instead of a new input beside an old case book."""
    monkeypatch.setattr(fixtures, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(fixtures, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(fixtures, "MANIFEST", tmp_path / "manifest.json")
    real = fixtures.project_payload
    calls = {"n": 0}

    def boom(kind: str, payload: object) -> dict:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("injected projection failure")
        return real(kind, payload)

    monkeypatch.setattr(fixtures, "project_payload", boom)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        fixtures._regenerate(GOLDEN_INPUTS)
    assert not (tmp_path / "inputs").exists()
    assert not (tmp_path / "cases.json").exists()
    assert not (tmp_path / "manifest.json").exists()


def test_sanitizer_guard_follows_this_checkout_and_this_user() -> None:
    """F9: the markers are derived, not `C:/Users` and `E:/boardwise` literals."""
    markers = fixtures._forbidden_markers(
        root=Path("D:/work/boardwise"), home=Path("D:/users/bob")
    )
    assert any("boardwise" in marker for marker in markers)
    assert any("bob" in marker for marker in markers)
    with pytest.raises(RuntimeError, match="machine path"):
        fixtures._assert_clean("probe", '{"note": "D:/users/bob/.cache/x.json"}', markers)
    with pytest.raises(RuntimeError, match="residual absolute path"):
        fixtures._assert_clean("probe", '{"note": "/home/alice/board.epro2"}', markers)
    with pytest.raises(RuntimeError, match="residual absolute path"):
        fixtures._assert_clean("probe", '{"note": "C:/Users/someone/x.json"}', markers)


def test_public_golden_passes_the_residual_path_gate() -> None:
    """The gate must not fire on the golden it is guarding."""
    for path in sorted((ROOT / "contracts" / "differential").rglob("*.json")):
        fixtures._assert_clean(path.name, path.read_text(encoding="utf-8"))


def test_per_run_output_directory_is_sanitized_to_one_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`checkup --out` reads its own design-intent.md back, so each run gets a fresh
    directory; that directory's random name must never reach the golden."""
    monkeypatch.setattr(
        fixtures,
        "RUN_ROOT",
        Path("D:/work/boardwise/.tmp_540/differential_build/run-abc123"),
    )
    cleaned = fixtures._clean_text(
        "D:\\work\\boardwise\\.tmp_540\\differential_build\\run-abc123\\checkup\\report.json"
    )
    assert cleaned == "<OUT>/checkup/report.json"


def test_manifest_producers_reference_the_sanitized_out_placeholder() -> None:
    producers = _json(MANIFEST)["producers"]
    assert all("<WORK>" not in line for line in producers)
    assert all("<OUT>" in line for line in producers)


REVIEW_REPORT = ROOT / "contracts/differential/inputs/review-report.json"


def test_manifest_producer_versions_are_the_published_reports_own_values() -> None:
    """The manifest states the rule digests the golden report states — nothing else."""
    manifest = _json(MANIFEST)
    versions = _json(REVIEW_REPORT)["completion"]["sourceVersions"]
    assert manifest["producerVersions"] == versions
    assert set(manifest["producerVersions"]) == {"ruleset", "rulebody"}
    assert all(
        isinstance(value, str) and value for value in manifest["producerVersions"].values()
    )


def test_manifest_schemas_are_the_files_the_runner_gates_with() -> None:
    """One entry per case kind, hashed from the file the Python runner reads."""
    manifest = _json(MANIFEST)
    expected = {
        f"contracts/json/{name}": hashlib.sha256(
            (ROOT / "contracts" / "json" / name).read_bytes()
        ).hexdigest()
        for name in SCHEMAS.values()
    }
    assert manifest["schemas"] == expected
    assert len(manifest["schemas"]) == len(SCHEMAS) == 5
    assert not any("bridge-error" in path for path in manifest["schemas"])


def test_manifest_producer_versions_follow_this_runs_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a constant: change the report, and the rendered manifest follows it."""
    report = deepcopy(_json(REVIEW_REPORT))
    report["completion"]["sourceVersions"] = {
        "ruleset": "11111111",
        "rulebody": "22222222",
    }
    path = tmp_path / "review-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    produced = dict(GOLDEN_INPUTS)
    produced["review-report-projection"] = path
    monkeypatch.setattr(fixtures, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(fixtures, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(fixtures, "MANIFEST", tmp_path / "manifest.json")
    rendered = fixtures._render(produced)
    manifest = json.loads(rendered[tmp_path / "manifest.json"])
    assert manifest["producerVersions"] == {
        "ruleset": "11111111",
        "rulebody": "22222222",
    }


@pytest.mark.parametrize(
    ("python_value", "rust_value"),
    [(1, True), (95.0, 95), (0, False)],
    ids=["int-1-vs-true", "float-95-vs-int-95", "int-0-vs-false"],
)
def test_comparison_is_type_strict_for_numbers_and_booleans(
    python_value: object, rust_value: object
) -> None:
    """`1` and `true`, `95.0` and `95` are different JSON values, so they differ."""
    python_report, rust_report = _cross_language_reports()
    python_report["cases"][0]["actual"]["probe"] = python_value
    rust_report["cases"][0]["actual"]["probe"] = rust_value
    result = compare_reports(python_report, rust_report)
    assert result["ok"] is False
    assert result["pythonNormalizedSha256"] != result["rustNormalizedSha256"]


def test_comparison_requires_a_boolean_top_level_ok() -> None:
    python_report, rust_report = _cross_language_reports()
    rust_report["ok"] = 1
    with pytest.raises(ValueError, match="boolean"):
        compare_reports(python_report, rust_report)


def test_comparison_rejects_reports_from_different_books() -> None:
    python_report, rust_report = _cross_language_reports()
    rust_report["cases"].append(deepcopy(rust_report["cases"][0]))
    with pytest.raises(ValueError, match="case counts"):
        compare_reports(python_report, rust_report)


def test_python_runner_refuses_a_golden_that_spells_a_boolean_as_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F14: `1` must not pass for `true`, or the Rust side disagrees silently."""
    book = deepcopy(_json(CASES))
    compile_case = next(
        case for case in book["cases"] if case["kind"] == "compile-result-projection"
    )
    compile_case["expected"]["ok"] = 1
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(book), encoding="utf-8")
    report = run_cases(cases, ROOT)
    assert report["ok"] is False
    assert [case["ok"] for case in report["cases"]] == [True, True, False, True, True]
    monkeypatch.setattr(sys, "argv", [
        "differential", "--cases", str(cases), "--root", str(ROOT),
    ])
    assert differential_main() == 1
