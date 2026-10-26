"""540C: the Python contract validator's declared subset must mean draft 2020-12.

The adversarial report (`.tmp_adversarial540/contracts-rust-retry/report.md`)
found three classes of deviation in `tools/contract_validate.py`, each covered
here by tests that fail on the old semantics:

* **F11** — `enum`/`const` guarded booleans only at the top level, so `[true]`
  matched `[1]` and `{"a": true}` matched `{"a": 1}`.
* **F12** — `1.0` was not an `integer`, `items` also re-validated the
  `prefixItems` positions, a boolean subschema crashed with `AttributeError`,
  chained/self `$ref` became an empty gate, and a `$ref`'s sibling keywords were
  dropped. `NaN`/`Infinity` were accepted by `json.loads` and treated as
  numbers.
* **F13** — the unknown-keyword check was lazy: a `oneOf` in a branch the
  instance never reached was never reported.

The five committed schemas keep their public positive inputs and their negative
cases, and every one of them must pass the whole-tree pre-check, so the fix is a
semantic one and not a patch for one example.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from boardwise.bridge.protocol import BridgeError, ErrorCodes, error_frame
from tools import differential as differential_module
from tools.contract_validate import (
    ContractValidationError,
    check_schema,
    load_path,
    loads_strict,
    validate,
)
from tools.differential import run_cases
from tools.differential_compare import canonical_bytes, main as compare_main

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "contracts" / "json"
INPUTS = ROOT / "contracts" / "differential" / "inputs"
CASES = ROOT / "contracts" / "differential" / "cases.json"

SCHEMA_NAMES = [
    "bridge-error-v1.schema.json",
    "draw-compile-result-v1.schema.json",
    "draw-page-compile-result-v1.schema.json",
    "draw-lint-result-v1.schema.json",
    "layout-plan-v1.schema.json",
    "review-report-v1.schema.json",
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


def _non_finite_cases() -> list[float]:
    return [float("nan"), float("inf"), float("-inf")]


# ---------------------------------------------------------------------------
# The committed schemas: pre-check, positives, negatives (no contract changed)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_name", SCHEMA_NAMES)
def test_every_committed_schema_is_inside_the_supported_subset(schema_name: str) -> None:
    """The whole tree — including unused `$defs` — is one pre-check away from red."""
    assert check_schema(_schema(schema_name)) is None


@pytest.mark.parametrize(("schema_name", "input_name"), POSITIVE_INPUTS)
def test_committed_schemas_accept_their_public_positive_inputs(
    schema_name: str, input_name: str
) -> None:
    assert validate(_json(INPUTS / input_name), _schema(schema_name)) == []


def test_bridge_schema_accepts_the_production_error_shapes() -> None:
    schema = _schema("bridge-error-v1.schema.json")
    assert validate(BridgeError(ErrorCodes.NO_CONNECTOR, "no connector").as_dict(), schema) == []
    frame = json.loads(error_frame(
        "contract-test", BridgeError(ErrorCodes.BAD_REQUEST, "bad ids", {"field": "ids"})
    ))
    assert validate(frame["error"], schema) == []


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
        "review-report-v1.schema.json", "review-report.json", ("environment", "writeAllowed"), True,
        "expected const False", id="review-write-allowed-is-not-claimable",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("planVersion",), True,
        "expected const 1", id="layout-version-is-a-number-not-a-boolean",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("parts", 0, "rotation"), -90,
        "not in enum", id="layout-invalid-rotation",
    ),
    pytest.param(
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("parts", 0, "x"), "95",
        "expected number", id="layout-coordinate-is-a-number",
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
        "layout-plan-v1.schema.json", "divider-cand1.layout.json", ("segments", 0, "points", 0, 0),
        "95", "expected number", id="layout-point-coordinates-are-numbers",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("command",), "lint",
        "expected const 'compile'", id="compile-command-is-fixed",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json",
        ("candidates", 0, "index"), -1, "below minimum",
        id="compile-candidate-index-is-nonnegative",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("failures",),
        [{"category": "unknown", "detail": "bad", "action": "fix"}], "not in enum",
        id="compile-refusal-category-is-frozen",
    ),
    pytest.param(
        "draw-compile-result-v1.schema.json", "divider-compile-result.json", ("previews",), [1],
        "expected string", id="compile-preview-paths-are-strings",
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
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("counts", "ERROR"), 1.5,
        "expected integer", id="lint-counts-are-integers",
    ),
    pytest.param(
        "draw-lint-result-v1.schema.json", "empty-page-lint-result.json", ("textReadable",), "yes",
        "expected boolean", id="lint-readability-is-boolean",
    ),
]


@pytest.mark.parametrize(("schema_name", "input_name", "path", "value", "message"), NEGATIVE_CASES)
def test_committed_schemas_still_reject_their_negative_cases(
    schema_name: str, input_name: str, path: tuple[Any, ...], value: Any, message: str
) -> None:
    payload = deepcopy(_json(INPUTS / input_name))
    _change(payload, path, value)
    errors = validate(payload, _schema(schema_name))
    assert errors, f"invalid {schema_name} instance was accepted"
    assert any(message in error for error in errors), errors


def test_coordinates_and_counts_reject_booleans() -> None:
    """A boolean in a coordinate slot is a type error, in a count slot as well."""
    layout = _schema("layout-plan-v1.schema.json")
    payload = deepcopy(_json(INPUTS / "divider-cand1.layout.json"))
    payload["parts"][0]["x"] = True
    assert any("expected number" in error for error in validate(payload, layout))
    lint = _schema("draw-lint-result-v1.schema.json")
    payload = deepcopy(_json(INPUTS / "empty-page-lint-result.json"))
    payload["counts"]["ERROR"] = True
    assert any("expected integer" in error for error in validate(payload, lint))


# ---------------------------------------------------------------------------
# F11: enum/const compare containers recursively, booleans are not numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instance", "schema"),
    [
        ({"a": True}, {"enum": [{"a": 1}]}),
        ([True, 2], {"enum": [[1, 2]]}),
        ([[True]], {"enum": [[[1]]]}),
        ({"a": [True]}, {"enum": [{"a": [1]}]}),
        ({"a": 1}, {"enum": [{"a": [True]}]}),
    ],
    ids=["dict-bool", "list-bool", "nested-list-bool", "dict-list-bool", "dict-vs-list-bool"],
)
def test_enum_separates_true_from_one_inside_containers(
    instance: Any, schema: dict[str, Any]
) -> None:
    errors = validate(instance, schema)
    assert errors, "a boolean inside a container was accepted for the integer 1"
    assert any("not in enum" in error for error in errors)


@pytest.mark.parametrize(
    ("instance", "schema"),
    [
        ({"a": True}, {"const": {"a": 1}}),
        ([True, 2], {"const": [1, 2]}),
        ([[True]], {"const": [[1]]}),
        ({"a": [1]}, {"const": {"a": [True]}}),
    ],
    ids=["dict-bool", "list-bool", "nested-list-bool", "dict-list-bool"],
)
def test_const_separates_true_from_one_inside_containers(
    instance: Any, schema: dict[str, Any]
) -> None:
    errors = validate(instance, schema)
    assert errors, "a boolean inside a container was accepted for the integer 1"
    assert any("expected const" in error for error in errors)


@pytest.mark.parametrize(
    ("instance", "schema"),
    [
        ({"a": 1}, {"enum": [{"a": 1}]}),
        ({"a": 1.0}, {"enum": [{"a": 1}]}),
        ([1, 2.0], {"enum": [[1, 2]]}),
        ({"b": 2, "a": 1}, {"const": {"a": 1, "b": 2}}),
        ([{"a": [1, {"b": None}]}], {"enum": [[{"a": [1, {"b": None}]}]]}),
    ],
    ids=["dict", "dict-float", "list-float", "key-order", "deep-null"],
)
def test_enum_and_const_still_match_json_values(instance: Any, schema: dict[str, Any]) -> None:
    """Numbers compare numerically (1 == 1.0) and object key order never matters."""
    assert validate(instance, schema) == []


def test_container_equality_is_length_and_key_strict() -> None:
    assert any("not in enum" in error for error in validate([1, 2], {"enum": [[1]]}))
    assert any(
        "not in enum" in error for error in validate({"a": 1}, {"enum": [{"a": 1, "b": 2}]})
    )


def test_an_empty_enum_rejects_every_value_and_says_so() -> None:
    """2020-12 makes the element a SHOULD, so `[]` is a defined "nothing matches"."""
    for instance in (1, "x", None, [], {}):
        errors = validate(instance, {"enum": []})
        assert errors and "not in enum" in errors[0]


# ---------------------------------------------------------------------------
# F12(a): `integer` is a finite number with a zero fractional part
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [1.0, 2.0, -0.0, 0.0, 3.0, 1e17], ids=repr)
def test_integer_accepts_finite_numbers_with_zero_fraction(value: float) -> None:
    assert validate(value, {"type": "integer"}) == []


@pytest.mark.parametrize(
    "value",
    [True, False, 1.5, -2.5, "1", None, [], {}],
    ids=["true", "false", "1.5", "-2.5", "string", "null", "array", "object"],
)
def test_integer_rejects_booleans_fractions_and_non_numbers(value: Any) -> None:
    errors = validate(value, {"type": "integer"})
    assert errors, f"{value!r} was accepted as an integer"
    assert any("expected integer" in error for error in errors)


@pytest.mark.parametrize("value", _non_finite_cases(), ids=["nan", "inf", "-inf"])
def test_integer_and_number_reject_non_finite_floats(value: float) -> None:
    """NaN would otherwise sail through `minimum` too, because comparisons are false."""
    assert any("expected integer" in error for error in validate(value, {"type": "integer"}))
    assert any("expected number" in error for error in validate(value, {"type": "number"}))
    assert validate(value, {"type": "number", "minimum": 0})


# ---------------------------------------------------------------------------
# F12(b): `items` applies only after `prefixItems`
# ---------------------------------------------------------------------------


def test_items_applies_only_after_the_prefix() -> None:
    schema = {"prefixItems": [{"type": "string"}], "items": {"type": "number"}}
    assert validate(["a", 1, 2.0], schema) == []
    errors = validate([1, "a"], schema)
    assert errors == ["$[0]: expected string, got int", "$[1]: expected number, got str"]


def test_items_false_rejects_only_the_tail() -> None:
    schema = {"prefixItems": [True, True], "items": False}
    assert validate(["a", 1], schema) == []
    errors = validate(["a", 1, "extra"], schema)
    assert errors == ["$[2]: rejected by a false schema: no value is allowed here"]


def test_absent_items_leaves_the_tail_unconstrained() -> None:
    schema = {"prefixItems": [{"type": "string"}], "minItems": 1}
    assert validate(["a", 1, {"any": [None]}], schema) == []


def test_prefix_positions_are_checked_by_the_prefix_schema_only() -> None:
    """A number at index 0 is a prefix violation, not a duplicate `items` violation."""
    schema = {"prefixItems": [{"type": "string"}], "items": {"type": "number"}}
    assert validate([1], schema) == ["$[0]: expected string, got int"]


# ---------------------------------------------------------------------------
# F12(c): boolean subschemas are schemas (`true` accepts, `false` rejects)
# ---------------------------------------------------------------------------

BOOLEAN_SUBSCHEMA_CASES = [
    pytest.param(True, {"x": 1}, True, id="root-true"),
    pytest.param(False, 1, False, id="root-false"),
    pytest.param({"type": "array", "items": True}, [1, {"a": 2}], True, id="items-true"),
    pytest.param({"type": "array", "items": False}, [], True, id="items-false-empty"),
    pytest.param({"type": "array", "items": False}, [1], False, id="items-false-item"),
    pytest.param({"type": "object", "properties": {"a": True}}, {"a": 1}, True, id="property-true"),
    pytest.param({"type": "object", "properties": {"a": False}}, {"a": 1}, False, id="property-false"),
    pytest.param({"type": "object", "additionalProperties": True}, {"z": 1}, True, id="additional-true"),
    pytest.param(
        {"type": "object", "additionalProperties": False}, {"z": 1}, False, id="additional-false"
    ),
    pytest.param(
        {"type": "object", "additionalProperties": {"type": "integer"}},
        {"z": "x"}, False, id="additional-schema",
    ),
    pytest.param(
        {"type": "array", "prefixItems": [True]}, ["x"], True, id="prefix-true"
    ),
    pytest.param(
        {"type": "array", "prefixItems": [False]}, ["x"], False, id="prefix-false"
    ),
    pytest.param({"$defs": {"any": True}, "$ref": "#/$defs/any"}, 1, True, id="def-true"),
    pytest.param({"$defs": {"never": False}, "$ref": "#/$defs/never"}, 1, False, id="def-false"),
]


@pytest.mark.parametrize(("schema", "instance", "accepted"), BOOLEAN_SUBSCHEMA_CASES)
def test_boolean_subschemas_accept_or_reject(schema: Any, instance: Any, accepted: bool) -> None:
    errors = validate(instance, schema)
    assert isinstance(errors, list)
    assert (errors == []) is accepted, errors


def test_no_boolean_subschema_position_raises_attribute_error() -> None:
    """Every position that legitimately holds a boolean is visited by both paths."""
    schemas = [
        True,
        False,
        {"type": "array", "items": True},
        {"type": "array", "items": False},
        {"type": "array", "prefixItems": [True, False], "items": False},
        {"type": "object", "properties": {"a": True}, "additionalProperties": False},
        {"type": "object", "additionalProperties": True},
        {"$defs": {"t": True, "f": False}, "$ref": "#/$defs/t"},
    ]
    instances = [[], [1], {}, {"a": 1, "b": 2}, 1, "x", None]
    for schema in schemas:
        check_schema(schema)
        for instance in instances:
            try:
                assert isinstance(validate(instance, schema), list)
            except ContractValidationError:
                pass  # a loud refusal is fine; a crash on `True.get` is not


# ---------------------------------------------------------------------------
# F12(d)+(e): `$ref` chains, sibling keywords, and circular refs fail loudly
# ---------------------------------------------------------------------------


def test_chained_refs_apply_the_final_constraint() -> None:
    schema = {
        "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"type": "string"}},
        "$ref": "#/$defs/a",
    }
    assert validate("ok", schema) == []
    errors = validate(123, schema)
    assert errors == ["$: expected string, got int"]


def test_sibling_keywords_of_a_ref_still_apply() -> None:
    """2020-12: `$ref` is an applicator, so `minLength` next to it is not dropped."""
    schema = {"$defs": {"s": {"type": "string"}}, "$ref": "#/$defs/s", "minLength": 5}
    assert validate("abcdef", schema) == []
    assert validate("ab", schema) == ["$: shorter than minLength 5"]


def test_sibling_required_and_properties_of_a_ref_still_apply() -> None:
    required = {
        "$defs": {"o": {"type": "object", "properties": {"p": {"type": "string"}}}},
        "$ref": "#/$defs/o",
        "required": ["p", "q"],
    }
    assert validate({"p": "x"}, required) == ["$: required key 'q' is missing"]
    constrained = {
        "$defs": {"o": {"type": "object"}},
        "$ref": "#/$defs/o",
        "properties": {"b": {"type": "integer"}},
        "required": ["b"],
    }
    assert validate({"b": "x"}, constrained) == ["$.b: expected integer, got str"]


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param({"$ref": "#"}, id="self-root"),
        pytest.param({"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"}, id="self-def"),
        pytest.param(
            {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
            "$ref": "#/$defs/a"},
            id="two-step-cycle",
        ),
    ],
)
def test_circular_ref_is_refused_instead_of_validating_nothing(schema: dict[str, Any]) -> None:
    with pytest.raises(ContractValidationError, match="circular \\$ref"):
        validate(1, schema)


def test_ref_cycle_fails_even_when_the_instance_never_reaches_it() -> None:
    """The old lazy check never entered the unused `$defs` entry."""
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "string"}},
        "$defs": {"loop": {"$ref": "#/$defs/loop"}},
    }
    with pytest.raises(ContractValidationError, match="circular \\$ref"):
        check_schema(schema)
    with pytest.raises(ContractValidationError, match="circular \\$ref"):
        validate({"ok": "x"}, schema)


def test_nothing_validates_a_self_referential_schema() -> None:
    """A `$ref` cycle must never come back as `[]` for an arbitrary instance."""
    schema = {"$defs": {"a": {"$ref": "#/$defs/a"}}, "$ref": "#/$defs/a"}
    for instance in (1, "x", None, [], {}):
        with pytest.raises(ContractValidationError):
            validate(instance, schema)


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"$defs": {"broken": {"$ref": "#/$defs/missing"}}}, "unresolvable"),
        ({"$defs": {"broken": {"$ref": "https://example.com/s.json"}}}, "only local"),
        ({"$defs": {"broken": {"$ref": "#/title"}}, "title": "x"}, "does not name a schema"),
    ],
    ids=["missing", "remote", "not-a-schema"],
)
def test_unusable_refs_are_refused_even_when_unused(
    schema: dict[str, Any], message: str
) -> None:
    with pytest.raises(ContractValidationError, match=message):
        validate({}, schema)


# ---------------------------------------------------------------------------
# F13: one whole-tree pre-check, not a keyword check on the paths taken
# ---------------------------------------------------------------------------


UNUSED_KEYWORD_SCHEMAS = [
    pytest.param({"oneOf": []}, {}, id="root"),
    pytest.param({"properties": {"rare": {"oneOf": []}}}, {"always": 1}, id="unused-property"),
    pytest.param({"$defs": {"rare": {"format": "uri"}}}, {}, id="unused-def"),
    pytest.param({"items": {"anyOf": []}}, [], id="items"),
    pytest.param({"prefixItems": [{"not": {}}]}, [], id="prefix-items"),
    pytest.param({"additionalProperties": {"uniqueItems": True}}, {}, id="additional"),
    pytest.param(
        {"properties": {"a": {"properties": {"b": {"$comment": "x"}}}}}, {"a": {}}, id="nested"
    ),
]


@pytest.mark.parametrize(("schema", "instance"), UNUSED_KEYWORD_SCHEMAS)
def test_unknown_keywords_fail_whether_or_not_the_instance_reaches_them(
    schema: dict[str, Any], instance: Any
) -> None:
    with pytest.raises(ContractValidationError, match="unsupported schema keyword"):
        validate(instance, schema)


def test_unknown_keyword_error_names_the_unreachable_branch() -> None:
    schema = {"properties": {"always": {"type": "string"}, "rare": {"oneOf": []}}}
    with pytest.raises(ContractValidationError) as caught:
        validate({"always": "x"}, schema)
    assert "/properties/rare" in str(caught.value)
    assert "oneOf" in str(caught.value)


def test_x_annotations_stay_allowed_everywhere() -> None:
    schema = {
        "type": "object",
        "x-presence": "documentation only",
        "properties": {"a": {"type": "integer", "x-reader-default": 0}},
        "additionalProperties": True,
        "$defs": {"d": {"type": "string", "x-note": "unused documentation"}},
    }
    assert check_schema(schema) is None
    assert validate({"a": 1}, schema) == []
    assert validate({"a": 1.5}, schema) == ["$.a: expected integer, got float"]


def test_malformed_subset_keywords_are_refused_as_schema_errors() -> None:
    with pytest.raises(ContractValidationError, match="invalid schema"):
        validate(1, {"items": "not-a-schema"})
    with pytest.raises(ContractValidationError, match="invalid schema"):
        validate(1, {"required": "key"})
    with pytest.raises(ContractValidationError, match="regular expression"):
        validate("x", {"pattern": "["})
    with pytest.raises(ContractValidationError, match="invalid schema"):
        validate([1], {"minItems": 1.5})


def test_count_keywords_accept_integer_valued_numbers() -> None:
    """2020-12 `minItems` is an integer value, so `2.0` is one and `True` is not."""
    assert validate(["a", "b"], {"minItems": 2.0, "maxItems": 2.0}) == []
    assert check_schema({"minLength": 1.0}) is None
    with pytest.raises(ContractValidationError, match="invalid schema"):
        check_schema({"minLength": True})


# ---------------------------------------------------------------------------
# An explicit `root=` must not become a way around the pre-check (follow-up A)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instance", "schema", "root", "message"),
    [
        pytest.param(1, {"oneOf": []}, {}, "unsupported schema keyword", id="dummy-root"),
        pytest.param(
            {"always": "x"}, {"type": "object"},
            {"properties": {"rare": {"oneOf": []}}},
            "unsupported schema keyword", id="unused-branch-of-explicit-root",
        ),
        pytest.param(
            1, {"$ref": "#/$defs/a"}, {"$defs": {"a": {"$ref": "#/$defs/a"}}},
            "circular \\$ref", id="cycle-in-explicit-root",
        ),
        pytest.param(
            {}, {"type": "object"}, {"$defs": {"broken": {"$ref": "#/$defs/missing"}}},
            "unresolvable", id="dangling-ref-in-explicit-root",
        ),
    ],
)
def test_an_explicit_root_still_gets_the_whole_tree_precheck(
    instance: Any, schema: Any, root: Any, message: str
) -> None:
    """This used to short-circuit: `root is not None` meant "already checked"."""
    with pytest.raises(ContractValidationError, match=message):
        validate(instance, schema, root=root)


def test_an_explicit_root_still_validates_the_given_schema() -> None:
    """A clean root must not vouch for the schema argument actually applied."""
    assert validate({"a": 1}, {"type": "object"}, root={}) == []
    assert validate(
        123, {"$ref": "#/$defs/a"}, root={"$defs": {"a": {"type": "string"}}}
    ) == ["$: expected string, got int"]
    assert validate(None, {"type": ["number", "null"]}, root={}) == []


# ---------------------------------------------------------------------------
# A `type` union is checked against the vocabulary (follow-up B)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instance", "schema"),
    [
        pytest.param({"a": 1}, {"type": ["object", "nonsense"]}, id="match-then-unknown"),
        pytest.param("x", {"type": ["string", "nonsense"]}, id="string-then-unknown"),
        pytest.param({"a": 1}, {"type": "nonsense"}, id="unknown-only"),
        pytest.param([1], {"type": ["array", "integer", "nonsense"]}, id="third-unknown"),
    ],
)
def test_an_unknown_type_name_is_a_schema_error_even_when_a_branch_matches(
    instance: Any, schema: dict[str, Any]
) -> None:
    """`any()` stops at the first matching branch, so the pre-check owns the vocabulary."""
    with pytest.raises(ContractValidationError, match="unsupported JSON Schema type"):
        validate(instance, schema)


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param({"$defs": {"weird": {"type": "nonsense"}}}, id="unused-def"),
        pytest.param({"properties": {"rare": {"type": "nonsense"}}}, id="unused-property"),
        pytest.param({"items": {"type": "nonsense"}}, id="items"),
        pytest.param({"type": "object", "additionalProperties": {"type": "nonsense"}},
                     id="additional"),
    ],
)
def test_an_unknown_type_name_fails_whether_or_not_the_instance_reaches_it(
    schema: dict[str, Any],
) -> None:
    with pytest.raises(ContractValidationError, match="unsupported JSON Schema type"):
        check_schema(schema)


def test_the_declared_type_unions_still_work() -> None:
    schema = {"type": ["number", "null"]}
    assert validate(None, schema) == []
    assert validate(1.5, schema) == []
    assert validate("x", schema) == ["$: expected ['number', 'null'], got str"]


def test_a_malformed_type_keyword_is_still_a_shape_error() -> None:
    for schema in ({"type": []}, {"type": 1}, {"type": ["object", 1]}):
        with pytest.raises(ContractValidationError, match="invalid schema"):
            check_schema(schema)


# ---------------------------------------------------------------------------
# F12(f): `NaN`/`Infinity` never enter through any JSON entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '[NaN]', '{"a": 1e999}'],
    ids=["nan", "inf", "-inf", "list-nan", "overflow"],
)
def test_strict_loader_rejects_non_finite_numbers(text: str) -> None:
    with pytest.raises(ContractValidationError, match="non-finite"):
        loads_strict(text)


def test_load_path_reads_through_the_same_strict_loader(tmp_path: Path) -> None:
    path = tmp_path / "schema.json"
    path.write_text('{"type": "number", "minimum": NaN}', encoding="utf-8")
    with pytest.raises(ContractValidationError, match="non-finite"):
        load_path(path)


def test_case_book_carrying_a_nan_is_refused(tmp_path: Path) -> None:
    book = _json(CASES)
    book["cases"][0]["expected"]["findingCount"] = float("nan")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(book), encoding="utf-8")
    with pytest.raises(ContractValidationError, match="non-finite"):
        run_cases(cases, ROOT)


def test_case_input_carrying_a_nan_is_refused_before_schema_validation(
    tmp_path: Path,
) -> None:
    """`metrics` is an unconstrained object, so only the loader can catch this."""
    payload = _json(INPUTS / "divider-compile-result.json")
    payload["candidates"][0]["metrics"]["ratio"] = float("nan")
    (tmp_path / "input.json").write_text(json.dumps(payload), encoding="utf-8")
    book = {
        "schema": "boardwise.differential-cases/1",
        "cases": [{
            "id": "compile-result-projection",
            "kind": "compile-result-projection",
            "input": "input.json",
            # A finite golden, so the refusal can only come from the input file:
            # the case book itself parses through the strict loader here.
            "expected": {
                "command": "compile", "ok": True, "candidateCount": 1,
                "failureCount": 0, "previewNames": [],
            },
        }],
    }
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(book), encoding="utf-8")
    assert "NaN" not in cases.read_text(encoding="utf-8")
    with pytest.raises(ContractValidationError, match="non-finite"):
        run_cases(cases, tmp_path)


def test_schema_carrying_a_nan_is_refused_through_the_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "contracts" / "json"
    fake.mkdir(parents=True)
    (fake / "draw-lint-result-v1.schema.json").write_text(
        '{"type": "object", "x-threshold": NaN}', encoding="utf-8"
    )
    book = {
        "schema": "boardwise.differential-cases/1",
        "cases": [{
            "id": "lint-result-projection",
            "kind": "lint-result-projection",
            "input": "contracts/differential/inputs/empty-page-lint-result.json",
            "expected": {},
        }],
    }
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(book), encoding="utf-8")
    # Against the committed schema the same book runs (and merely disagrees with
    # its empty golden), so the raise below is the NaN in the schema file.
    assert run_cases(cases, ROOT)["cases"][0]["ok"] is False
    monkeypatch.setattr(differential_module, "ROOT", tmp_path)
    with pytest.raises(ContractValidationError, match="non-finite"):
        run_cases(cases, ROOT)


@pytest.mark.parametrize("value", _non_finite_cases(), ids=["nan", "inf", "-inf"])
def test_canonical_bytes_refuses_non_finite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_bytes({"probe": value})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_bytes([{"nested": [value]}])


def test_compare_entry_refuses_a_report_carrying_nan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python_report = run_cases(CASES, ROOT)
    rust_report = deepcopy(python_report)
    rust_report["runner"] = "rust"
    rust_report["cases"][0]["actual"]["probe"] = float("nan")
    python_path = tmp_path / "python.json"
    rust_path = tmp_path / "rust.json"
    python_path.write_text(json.dumps(python_report), encoding="utf-8")
    rust_path.write_text(json.dumps(rust_report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["differential_compare", str(python_path), str(rust_path)])
    with pytest.raises(ContractValidationError, match="non-finite"):
        compare_main()


def test_compare_entry_still_compares_real_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strict loader must not disturb the accepted path."""
    python_report = run_cases(CASES, ROOT)
    rust_report = deepcopy(python_report)
    rust_report["runner"] = "rust"
    python_path = tmp_path / "python.json"
    rust_path = tmp_path / "rust.json"
    python_path.write_text(json.dumps(python_report), encoding="utf-8")
    rust_path.write_text(json.dumps(rust_report), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["differential_compare", str(python_path), str(rust_path)])
    assert compare_main() == 0


# ---------------------------------------------------------------------------
# The CLI entry point keeps its observable behaviour
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools.contract_validate", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_cli_validate_accepts_a_committed_positive_input() -> None:
    result = _run_cli(
        str(INPUTS / "divider-cand1.layout.json"),
        str(SCHEMAS / "layout-plan-v1.schema.json"),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("valid:")


def test_cli_validate_still_rejects_an_invalid_instance(tmp_path: Path) -> None:
    instance = tmp_path / "instance.json"
    instance.write_text(
        json.dumps({"code": "NOT_A_CODE", "message": "bad"}), encoding="utf-8"
    )
    result = _run_cli(str(instance), str(SCHEMAS / "bridge-error-v1.schema.json"))
    assert result.returncode == 1
    assert "not in enum" in result.stdout
    assert result.stderr == ""


def test_cli_validate_refuses_a_non_finite_instance(tmp_path: Path) -> None:
    instance = tmp_path / "instance.json"
    instance.write_text('{"code": "BAD_REQUEST", "message": "bad", "detail": NaN}',
                        encoding="utf-8")
    result = _run_cli(str(instance), str(SCHEMAS / "bridge-error-v1.schema.json"))
    assert result.returncode == 1
    assert "non-finite" in result.stderr


# ---------------------------------------------------------------------------
# The runner's own golden book is unaffected by all of the above
# ---------------------------------------------------------------------------


def test_repository_golden_book_still_passes() -> None:
    report = run_cases(CASES, ROOT)
    assert report["ok"] is True
    assert all(case["ok"] for case in report["cases"])
