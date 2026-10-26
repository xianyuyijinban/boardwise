"""540C: executable compatibility checks for the versioned JSON contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from boardwise.bridge.protocol import BridgeError, ErrorCodes, error_frame
from tools.cli_contract import build_contract, canonical, main as cli_contract_main
from tools.contract_validate import ContractValidationError, validate

ROOT = Path(__file__).resolve().parents[1]
CLI_CONTRACT = ROOT / "contracts" / "cli" / "v1.json"
SCHEMAS = ROOT / "contracts" / "json"
INPUTS = ROOT / "contracts" / "differential" / "inputs"

EXPECTED_COMMANDS = [
    "review", "checkup", "need-datasheet", "triage", "triage-batch",
    "review-evidence", "review-read", "review-eval", "bridge", "review-mark",
    "edit", "doctor", "install-skill", "compare", "draw", "persistence",
    "lint", "parts", "bom", "pintable", "validate", "arch", "intent", "config",
]

POSITIVE_INPUTS = [
    ("review-report-v1.schema.json", "review-report.json"),
    ("layout-plan-v1.schema.json", "divider-cand1.layout.json"),
    ("draw-compile-result-v1.schema.json", "divider-compile-result.json"),
    ("draw-page-compile-result-v1.schema.json", "page-compile-result.json"),
    ("draw-lint-result-v1.schema.json", "empty-page-lint-result.json"),
]

_DELETE = object()


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema(name: str) -> dict[str, Any]:
    return _json(SCHEMAS / name)


def _change(payload: Any, path: tuple[Any, ...], value: Any) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    if value is _DELETE:
        target.pop(path[-1])
    else:
        target[path[-1]] = value


def test_cli_contract_matches_live_parser_and_check_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert CLI_CONTRACT.read_text(encoding="utf-8") == canonical(build_contract())
    monkeypatch.setattr(sys, "argv", ["cli_contract"])
    assert cli_contract_main() == 0
    assert "matches production" in capsys.readouterr().out


def test_cli_contract_pins_command_surface_and_error_vocabulary() -> None:
    contract = _json(CLI_CONTRACT)
    assert contract["schema"] == "boardwise.cli-contract/1"
    assert contract["contractVersion"] == 1
    assert list(contract["exitCodes"]["commands"]) == EXPECTED_COMMANDS
    parser_choices = next(
        action["choices"] for action in contract["parser"]["actions"]
        if isinstance(action["choices"], dict)
    )
    assert list(parser_choices) == EXPECTED_COMMANDS
    production_codes = {
        value for name, value in vars(ErrorCodes).items()
        if name.isupper() and isinstance(value, str)
    }
    assert set(contract["errorCodes"]["bridge"]) == production_codes
    assert contract["errorCodes"]["incompleteExitCode"] == 3
    assert contract["errorCodes"]["drawRefusalCategories"] == [
        "facts-missing", "circuit-invalid", "layout-unsat", "presentation-poor",
    ]


@pytest.mark.parametrize(("schema_name", "input_name"), POSITIVE_INPUTS)
def test_real_or_public_synthetic_inputs_match_schemas(
    schema_name: str, input_name: str
) -> None:
    assert validate(_json(INPUTS / input_name), _schema(schema_name)) == []


def test_bridge_schema_uses_the_production_error_vocabulary() -> None:
    production_codes = {
        value for name, value in vars(ErrorCodes).items()
        if name.isupper() and isinstance(value, str)
    }
    assert set(_schema("bridge-error-v1.schema.json")["properties"]["code"]["enum"]) == production_codes


def test_bridge_error_schema_accepts_actual_producer_shapes() -> None:
    without_detail = BridgeError(ErrorCodes.NO_CONNECTOR, "no connector").as_dict()
    assert validate(without_detail, _schema("bridge-error-v1.schema.json")) == []
    frame = json.loads(error_frame(
        "contract-test",
        BridgeError(ErrorCodes.BAD_REQUEST, "bad ids", {"field": "ids"}),
    ))
    assert validate(frame["error"], _schema("bridge-error-v1.schema.json")) == []


NEGATIVE_CASES = [
    pytest.param(
        "review-report-v1.schema.json", "review-report.json", ("summary",), _DELETE,
        "required key 'summary'", id="review-missing-summary",
    ),
    pytest.param(
        "review-report-v1.schema.json", "review-report.json", ("summary", "exitCode"), 4,
        "not in enum", id="review-invalid-exit-code",
    ),
    pytest.param(
        "review-report-v1.schema.json", "review-report.json", ("evidence", "delivery"), "partial",
        "expected object", id="review-delivery-is-not-a-string",
    ),
    pytest.param(
        "review-report-v1.schema.json", "review-report.json", ("environment", "writeAllowed"), True,
        "expected const False", id="review-write-allowed-is-not-claimable",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("parts", 0, "rotation"), -90,
        "not in enum", id="layout-invalid-rotation",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("geometrySha256",), "xyz",
        "does not match", id="layout-invalid-geometry-hash",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("unexpected",), True,
        "additional property", id="layout-is-closed-to-unknown-fields",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("parts",), [],
        "at least 1", id="layout-requires-a-part",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("command",), "lint",
        "expected const 'compile'", id="compile-command-is-fixed",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("candidates", 0, "index"), -1,
        "below minimum", id="compile-candidate-index-is-nonnegative",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("failures",),
        [{"category": "unknown", "detail": "bad", "action": "fix"}],
        "not in enum", id="compile-refusal-category-is-frozen",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("previews",), [1],
        "expected string", id="compile-preview-paths-are-strings",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json", ("document",),
        "module", "expected const 'page'", id="page-document-is-fixed",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json", ("pages", 0, "index"),
        -1, "below minimum", id="page-index-is-nonnegative",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json",
        ("pages", 0, "verdict"), "maybe", "not in enum", id="page-verdict-vocabulary",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json",
        ("pages", 0, "geometrySha256"), "xyz", "does not match",
        id="page-geometry-hash-shape",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json",
        ("pages", 0, "modules"), _DELETE, "required key 'modules'",
        id="page-item-states-its-modules",
    ),
    pytest.param(
        "draw-page-compile-result-v1.schema.json", "page-compile-result.json", ("previews",), [1],
        "expected string", id="page-preview-paths-are-strings",
    ),
    pytest.param(
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("source",), "offline",
        "not in enum", id="lint-source-vocabulary",
    ),
    pytest.param(
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("exitCode",), 2,
        "not in enum", id="lint-domain-exit-codes",
    ),
    pytest.param(
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("counts", "ERROR"), -1,
        "below minimum", id="lint-counts-are-nonnegative",
    ),
    pytest.param(
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("textReadable",), "yes",
        "expected boolean", id="lint-readability-is-boolean",
    ),
]


@pytest.mark.parametrize(("schema_name", "input_name", "path", "value", "message"), NEGATIVE_CASES)
def test_schema_negative_cases_are_rejected(
    schema_name: str, input_name: str, path: tuple[Any, ...], value: Any, message: str
) -> None:
    payload = deepcopy(_json(INPUTS / input_name))
    _change(payload, path, value)
    errors = validate(payload, _schema(schema_name))
    assert errors, f"invalid {schema_name} instance was accepted"
    assert any(message in error for error in errors), errors


def test_a_page_result_is_not_a_module_result_and_vice_versa() -> None:
    """Two documents, two contracts: the page case must never be folded into the
    module `candidates` shape, and the module case must never pass as a page."""
    page = _json(INPUTS / "page-compile-result.json")
    module = _json(INPUTS / "divider-compile-result.json")
    module_errors = validate(page, _schema("draw-compile-result-v1.schema.json"))
    assert module_errors, "the module contract accepted a page document"
    assert any("labelFallbacks" in error for error in module_errors), module_errors
    assert any("candidates" in error for error in module_errors), module_errors
    page_errors = validate(module, _schema("draw-page-compile-result-v1.schema.json"))
    assert page_errors, "the page contract accepted a module document"
    assert any("document" in error for error in page_errors), page_errors
    assert any("pages" in error for error in page_errors), page_errors


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"code": "NOT_A_CODE", "message": "bad"}, "not in enum"),
        ({"code": "BAD_REQUEST"}, "required key 'message'"),
        ({"code": "BAD_REQUEST", "message": "bad", "extra": 1}, "additional property"),
    ],
    ids=["unknown-code", "missing-message", "unknown-field"],
)
def test_bridge_error_negative_cases_are_rejected(payload: dict[str, Any], message: str) -> None:
    errors = validate(payload, _schema("bridge-error-v1.schema.json"))
    assert errors
    assert any(message in error for error in errors), errors


def test_validator_fails_loudly_on_unsupported_schema_keywords() -> None:
    with pytest.raises(ContractValidationError, match="unsupported schema keyword"):
        validate({}, {"type": "object", "oneOf": []})


@pytest.mark.parametrize("columns", ["40", "80", "160"])
def test_cli_contract_help_is_rendered_at_a_pinned_width(
    monkeypatch: pytest.MonkeyPatch, columns: str
) -> None:
    """The snapshot must not be a function of the terminal it was taken in."""
    monkeypatch.setenv("COLUMNS", columns)
    contract = _json(CLI_CONTRACT)
    assert contract["parser"]["helpWidth"] == 80
    assert canonical(build_contract()) == CLI_CONTRACT.read_text(encoding="utf-8")


def test_declared_exit_codes_include_the_argparse_usage_error() -> None:
    exit_codes = _json(CLI_CONTRACT)["exitCodes"]
    assert exit_codes["argparseUsageError"] == 2
    for family in ("commands", "subcommands"):
        for name, codes in exit_codes[family].items():
            assert 2 in codes, f"exitCodes.{family}.{name} omits the usage-error code 2"


@pytest.mark.parametrize(
    "argv",
    [
        ["doctor", "--definitely-not-a-flag"],
        ["draw", "compile", "--definitely-not-a-flag"],
        ["draw", "plan", "--definitely-not-a-flag"],
    ],
    ids=["doctor", "draw-compile", "draw-plan"],
)
def test_argparse_usage_errors_actually_exit_two(argv: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *argv],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 2, result.stderr
