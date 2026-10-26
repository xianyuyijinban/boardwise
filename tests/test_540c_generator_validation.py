"""540C: the fixture generator gates every payload on its real schema, strictly.

The regression this file pins: after the generator was made in-memory, it read
producer JSON with plain ``json.loads`` and projected without ``assert_valid`` — so a
contract-invalid or non-finite producer output could be published as golden. Every
read now goes through :mod:`tools.contract_validate`'s strict loader, and every
payload is validated against ``tools.differential.SCHEMAS[kind]`` before projection.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools import build_differential_fixtures as fixtures
from tools.contract_validate import ContractValidationError, load_path, loads_strict
from tools.differential import SCHEMAS

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts" / "differential"
INPUTS = CONTRACTS / "inputs"
GOLDEN_INPUTS = {
    "review-report-projection": INPUTS / "review-report.json",
    "layout-plan-geometry": INPUTS / "divider-cand1.layout.json",
    "compile-result-projection": INPUTS / "divider-compile-result.json",
    "compile-page-result-projection": INPUTS / "page-compile-result.json",
    "lint-result-projection": INPUTS / "empty-page-lint-result.json",
}


def _redirect(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(fixtures, "INPUTS", tmp_path / "inputs")
    monkeypatch.setattr(fixtures, "CASES", tmp_path / "cases.json")
    monkeypatch.setattr(fixtures, "MANIFEST", tmp_path / "manifest.json")


def _assert_nothing_published(tmp_path: Path) -> None:
    assert not (tmp_path / "inputs").exists()
    assert not (tmp_path / "cases.json").exists()
    assert not (tmp_path / "manifest.json").exists()


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_strict_loader_rejects_non_finite_numbers(token: str) -> None:
    with pytest.raises(ContractValidationError, match="non-finite"):
        loads_strict('{"probe": %s}' % token)


def test_strict_loader_accepts_a_normal_document(tmp_path: Path) -> None:
    path = tmp_path / "ok.json"
    path.write_text('{"probe": 1.5, "count": 2}', encoding="utf-8")
    assert load_path(path) == {"probe": 1.5, "count": 2}


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_a_non_finite_producer_file_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    _redirect(monkeypatch, tmp_path)
    poisoned = tmp_path / "review-report.json"
    poisoned.write_text('{"probe": %s}' % token, encoding="utf-8")
    produced = dict(GOLDEN_INPUTS)
    produced["review-report-projection"] = poisoned
    with pytest.raises(ContractValidationError, match="non-finite"):
        fixtures._regenerate(produced)
    _assert_nothing_published(tmp_path)


def test_a_contract_invalid_producer_file_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A violation the old projection-only path accepted: `command` is a const."""
    _redirect(monkeypatch, tmp_path)
    compile_result = json.loads(GOLDEN_INPUTS["compile-result-projection"].read_text(encoding="utf-8"))
    compile_result["command"] = "lint"
    poisoned = tmp_path / "compile-result.json"
    poisoned.write_text(json.dumps(compile_result, ensure_ascii=False), encoding="utf-8")
    produced = dict(GOLDEN_INPUTS)
    produced["compile-result-projection"] = poisoned
    with pytest.raises(ContractValidationError) as error:
        fixtures._regenerate(produced)
    assert "expected const 'compile'" in str(error.value)
    _assert_nothing_published(tmp_path)


def test_a_page_document_that_states_another_document_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The page case is gated by its own contract: a producer output that flips
    `document` back to a module cannot be published as a page golden."""
    _redirect(monkeypatch, tmp_path)
    page_result = json.loads(
        GOLDEN_INPUTS["compile-page-result-projection"].read_text(encoding="utf-8")
    )
    page_result["document"] = "module"
    poisoned = tmp_path / "page-compile-result.json"
    poisoned.write_text(json.dumps(page_result, ensure_ascii=False), encoding="utf-8")
    produced = dict(GOLDEN_INPUTS)
    produced["compile-page-result-projection"] = poisoned
    with pytest.raises(ContractValidationError) as error:
        fixtures._regenerate(produced)
    assert "expected const 'page'" in str(error.value)
    _assert_nothing_published(tmp_path)


def test_a_schema_invalid_report_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _redirect(monkeypatch, tmp_path)
    report = json.loads(GOLDEN_INPUTS["review-report-projection"].read_text(encoding="utf-8"))
    report["summary"]["exitCode"] = 4  # the schema's enum is [0, 1, 2, 3]
    poisoned = tmp_path / "review-report.json"
    poisoned.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    produced = dict(GOLDEN_INPUTS)
    produced["review-report-projection"] = poisoned
    with pytest.raises(ContractValidationError) as error:
        fixtures._regenerate(produced)
    assert "summary.exitCode" in str(error.value)
    _assert_nothing_published(tmp_path)


def test_every_read_goes_through_the_strict_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = fixtures.load_path

    def spy(path: object) -> object:
        seen.append(str(path))
        return real(path)

    monkeypatch.setattr(fixtures, "load_path", spy)
    _redirect(monkeypatch, tmp_path)
    fixtures._render(GOLDEN_INPUTS)
    for name in SCHEMAS.values():
        assert any(path.endswith(name) for path in seen), name
    for path in GOLDEN_INPUTS.values():
        assert any(seen_path.endswith(path.name) for seen_path in seen), path.name


def test_validation_runs_before_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    real_project = fixtures.project_payload

    def validate_spy(instance: object, schema: object) -> None:
        order.append("validate")

    def project_spy(kind: str, payload: object) -> dict:
        order.append("project")
        return real_project(kind, payload)

    monkeypatch.setattr(fixtures, "assert_valid", validate_spy)
    monkeypatch.setattr(fixtures, "project_payload", project_spy)
    fixtures._render(GOLDEN_INPUTS)
    assert order == ["validate", "project"] * len(GOLDEN_INPUTS)


def test_valid_public_inputs_still_publish_identical_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The new gate must not change a single byte of the current golden."""
    _redirect(monkeypatch, tmp_path)
    fixtures._publish(fixtures._render(GOLDEN_INPUTS))
    for name in fixtures.INPUT_NAMES.values():
        assert (tmp_path / "inputs" / name).read_bytes() == (INPUTS / name).read_bytes()
    assert (tmp_path / "cases.json").read_bytes() == (CONTRACTS / "cases.json").read_bytes()
    assert (tmp_path / "manifest.json").read_bytes() == (CONTRACTS / "manifest.json").read_bytes()


def test_manifest_schema_hashes_still_match_the_files_it_validates_with() -> None:
    manifest = json.loads((CONTRACTS / "manifest.json").read_text(encoding="utf-8"))
    for name in SCHEMAS.values():
        relative = f"contracts/json/{name}"
        assert manifest["schemas"][relative] == hashlib.sha256(
            (ROOT / relative).read_bytes()
        ).hexdigest()
